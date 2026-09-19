"""Progress must contain useful evidence before the complete run/report is available."""

import time

import httpx
import pytest
from fastapi.testclient import TestClient

from app import jobs, store
from app.config import settings
from app.optimizer import preview as previews
from app.optimizer.preview import attempt, inspect_page, summarize_page, update_attempts
from app.routers.product import create_app
from app.schemas import Episode, Job, JobPreview, PageSummary, Task
from tests.test_jobs import TASKS, _fake_mirror_to_store, make_fake_run_swarm


def test_homepage_summary_is_useful_even_without_obstacles():
    html = b'<title>Example</title><h1>Build things</h1><a href="/">Home</a><form></form>'
    page = summarize_page(html)
    assert (page.title, page.heading, page.links, page.forms) == ("Example", "Build things", 1, 1)
    assert not inspect_page("index.html", html)


def test_first_look_is_available_before_the_worker_starts(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "dashboard_password", "")
    job = Job(type="intake", url="https://example.com", scan_mode="quick")
    store.save_job(job)
    original = store.load_job(job.id).model_dump()
    monkeypatch.setattr(
        previews, "fetch_first_look", lambda url: JobPreview(page=PageSummary(title="Homepage"), pages_scanned=1)
    )
    with TestClient(create_app()) as client:
        r = client.get(f"/api/jobs/{job.id}/first-look")
        assert r.status_code == 200 and r.json()["page"]["title"] == "Homepage"
    assert store.load_job(job.id).model_dump() == original


def test_first_look_failure_does_not_fail_the_job(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "dashboard_password", "")
    job = Job(type="intake", url="https://example.com")
    store.save_job(job)

    def timeout(url):
        raise httpx.ReadTimeout("slow origin")

    monkeypatch.setattr(previews, "fetch_first_look", timeout)
    with TestClient(create_app()) as client:
        assert client.get(f"/api/jobs/{job.id}/first-look").json() is None
    assert store.load_job(job.id).status == "queued"


@pytest.mark.parametrize(
    "body,available", [(b"<title>Example</title><canvas></canvas>", True), (b"x" * 2_000_001, False)]
)
def test_first_look_reads_only_bounded_html(monkeypatch, body, available):
    transport = httpx.MockTransport(
        lambda req: httpx.Response(200, headers={"content-type": "text/html"}, content=body)
    )
    with httpx.Client(transport=transport) as client:
        monkeypatch.setattr(previews.httpx, "stream", lambda *a, **kw: client.stream("GET", "https://example.com"))
        if available:
            result = previews.fetch_first_look("https://example.com")
            assert result.page.title == "Example" and result.observations
        else:
            with pytest.raises(ValueError, match="limit"):
                previews.fetch_first_look("https://example.com")


def test_initial_checks_use_html_evidence_and_respect_labels():
    html = b"""<canvas></canvas><a href="details.html">Learn more</a>
    <label for="email">Email</label><input id="email">
    <span id="plan-label">Plan</span><select aria-labelledby="plan-label"></select>
    <input type="hidden"><input name="unknown">"""
    notes = inspect_page("index.html", html)
    assert len(notes) == 3
    assert any("1 form field(s)" in note for note in notes)
    assert any("1 canvas" in note for note in notes)
    assert all("index.html" in note for note in notes)


def test_execution_errors_and_skips_do_not_become_usability_findings():
    preview = JobPreview(total=3)
    base = dict(run_id="r", site_id="site", site_version="v0", task_id="task", agent_kind="text", model_id="mock")
    eps = [
        Episode(**base, failure_mode="error", success=False, error="provider unavailable"),
        Episode(**base, failure_mode="timeout", success=False),
        Episode(**base, failure_mode="error", success=False, error="budget exhausted: no call started"),
    ]
    update_attempts(preview, [attempt(ep, {}) for ep in eps])
    assert (preview.completed, preview.failed, preview.errors, preview.skipped) == (3, 0, 2, 1)
    assert not any("completed attempt(s) have failed on" in note for note in preview.findings)
    assert [r.outcome for r in preview.recent] == ["skipped", "error", "error"]


def test_partial_findings_use_only_observed_attempts():
    preview = JobPreview(total=20)
    task = Task(id="price", kind="answer", prompt="Find the price", expected_answer="5")
    results = [
        attempt(
            Episode(
                run_id="r",
                site_id="site",
                site_version="v0",
                task_id="price",
                agent_kind="text",
                model_id="mock",
                success=success,
                judge_reason="observed evidence",
            ),
            {task.id: task},
        )
        for success in [False, True]
    ]
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

        def swarm(*args, on_episode, on_start, **kwargs):
            assert snapshot()["total"] == len(TASKS)
            on_start([{"task": t.model_dump(), "model_id": "mock", "agent_kind": "text"} for t in TASKS])
            assert len(snapshot()["active"]) == len(TASKS)

            def completed(ep):
                on_episode(ep)
                preview = snapshot()
                assert preview["recent"][0]["episode_id"] == ep.id
                assert preview["findings"]
                assert all(a["task_id"] != ep.task_id for a in preview["active"])

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
    job = Job(
        type="loop",
        model_ids=["mock"],
        agent_kinds=["text"],
        live_preview=JobPreview(site_version="v0", passed=7, completed=7, observations=["Old version check"]),
    )

    def swarm(*args, on_episode, **kwargs):
        saved = store.load_job(job.id).live_preview
        assert saved.site_version == "v1" and saved.completed == 0 and saved.observations == []
        on_episode(
            Episode(
                run_id="r",
                site_id="site",
                site_version="v1",
                task_id=TASKS[0].id,
                agent_kind="text",
                model_id="mock",
                success=True,
                finished_at=time.time(),
            )
        )
        raise RuntimeError("worker stopped")

    monkeypatch.setattr(jobs, "run_swarm", swarm)
    import pytest

    with pytest.raises(RuntimeError, match="worker stopped"):
        jobs._run_swarm_phase(job, "site", "v1", TASKS, phase="Running swarm", local=True)
    saved = store.load_job(job.id).live_preview
    assert saved.completed == saved.passed == 1
