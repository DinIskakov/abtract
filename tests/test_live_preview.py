"""Progress must contain useful evidence before the complete run/report is available."""
import time

from fastapi.testclient import TestClient

from abtract import jobs, store
from abtract.config import settings
from abtract.dashboard.app import create_app
from abtract.optimizer.preview import attempt, inspect_page, update_attempts
from abtract.schemas import Episode, Job, JobPreview, RunSummary, Task
from tests.test_jobs import TASKS, _fake_mirror_to_store, make_fake_run_swarm


def test_initial_checks_use_html_evidence_and_respect_labels():
    html = b'''<canvas></canvas><a href="details.html">Learn more</a>
    <label for="email">Email</label><input id="email">
    <span id="plan-label">Plan</span><select aria-labelledby="plan-label"></select>
    <input type="hidden"><input name="unknown">'''
    notes = inspect_page("index.html", html)
    assert len(notes) == 3
    assert any("1 form field(s)" in note for note in notes)
    assert any("1 canvas" in note for note in notes)
    assert all("index.html" in note for note in notes)


def test_execution_errors_and_skips_do_not_become_usability_findings():
    preview = JobPreview(total=3)
    base = dict(run_id="r", site_id="site", site_version="v0", task_id="task", agent_kind="text", model_id="mock")
    eps = [Episode(**base, failure_mode="error", success=False, error="provider unavailable"),
           Episode(**base, failure_mode="timeout", success=False),
           Episode(**base, failure_mode="error", success=False, error="budget exhausted: no call started")]
    update_attempts(preview, [attempt(ep, {}) for ep in eps])
    assert (preview.completed, preview.failed, preview.errors, preview.skipped) == (3, 0, 2, 1)
    assert not any("completed attempt(s) have failed on" in note for note in preview.findings)
    assert [r.outcome for r in preview.recent] == ["skipped", "error", "error"]


def test_partial_findings_use_only_observed_attempts():
    preview = JobPreview(total=20)
    task = Task(id="price", kind="answer", prompt="Find the price", expected_answer="5")
    results = [attempt(Episode(run_id="r", site_id="site", site_version="v0", task_id="price",
                              agent_kind="text", model_id="mock", success=success,
                              judge_reason="observed evidence"), {task.id: task}) for success in [False, True]]
    update_attempts(preview, results)
    assert preview.completed == 2 and preview.passed == 1 and preview.failed == 1
    assert "1 of 2 completed attempt(s)" in preview.findings[0]
    assert "Other attempts may change" in preview.findings[0]
    assert preview.recent[0].reason == "observed evidence"


def test_api_publishes_page_checks_and_attempts_before_final_report(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "dashboard_password", "")
    monkeypatch.setattr(settings, "gemini_api_key", "")
    monkeypatch.setattr(jobs, "serve_site_locally", lambda: ("http://example", lambda: None))
    job = Job(type="intake", url="https://example.com", model_ids=["mock"], agent_kinds=["text"])
    store.save_job(job)
    snapshots = []
    with TestClient(create_app()) as client:
        def snapshot():
            data = client.get(f"/api/jobs/{job.id}").json()
            snapshots.append(data)
            assert data["status"] == "running" and data["findings"] is None
            return data["live_preview"]

        def mirror(url, *, site_id=None, on_page):
            on_page("index.html", b"<canvas></canvas>")
            preview = snapshot()
            assert preview["pages_scanned"] == 1 and preview["observations"]
            return _fake_mirror_to_store(url, site_id=site_id)

        real_fake_swarm = make_fake_run_swarm([])

        def swarm(*args, on_episode, **kwargs):
            assert snapshot()["total"] == len(TASKS)
            def completed(ep):
                on_episode(ep)
                preview = snapshot()
                assert preview["recent"][0]["episode_id"] == ep.id
                assert preview["findings"]
            return real_fake_swarm(*args, on_episode=completed, **kwargs)

        monkeypatch.setattr(jobs, "mirror_to_store", mirror)
        monkeypatch.setattr(jobs, "run_swarm", swarm)
        monkeypatch.setattr(jobs, "write_findings", lambda *a, **k: "Final findings")
        out = jobs.run_job_sync(job.id)
        assert out.status == "done", out.error
        assert out.findings == "Final findings"
        assert any(0 < data["live_preview"]["completed"] < len(TASKS) for data in snapshots)
        assert "live_preview" not in client.get("/api/jobs").json()[0]


def test_new_version_clears_previous_attempts_even_if_swarm_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(jobs, "serve_site_locally", lambda: ("http://example", lambda: None))
    job = Job(type="loop", model_ids=["mock"], agent_kinds=["text"],
              live_preview=JobPreview(site_version="v0", passed=7, completed=7, observations=["Old version check"]))
    def swarm(*args, on_episode, **kwargs):
        saved = store.load_job(job.id).live_preview
        assert saved.site_version == "v1" and saved.completed == 0 and saved.observations == []
        on_episode(Episode(run_id="r", site_id="site", site_version="v1", task_id=TASKS[0].id,
                           agent_kind="text", model_id="mock", success=True, finished_at=time.time()))
        raise RuntimeError("worker stopped")
    monkeypatch.setattr(jobs, "run_swarm", swarm)
    import pytest
    with pytest.raises(RuntimeError, match="worker stopped"):
        jobs._run_swarm_phase(job, "site", "v1", TASKS, phase="Running swarm", local=True)
    saved = store.load_job(job.id).live_preview
    assert saved.completed == saved.passed == 1
