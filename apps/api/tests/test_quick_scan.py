"""Fast scans must remain bounded, checkable, and comparable when optimized."""

import json
import time
from types import SimpleNamespace

from app import jobs, store
from app.agents import base
from app.config import settings
from app.intake.tasks import pick_quick_tasks
from app.routers.product import JobRequest, _build_job
from app.schemas import Job, RunSummary, Task
from tests.test_jobs import TASKS, _fake_mirror_to_store, _fake_optimize_site, make_fake_run_swarm


def test_quick_tasks_skip_inference_and_keep_full_site_tasks(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    sv, _ = _fake_mirror_to_store("https://example.com")
    store.save_site_tasks(sv.site_id, TASKS)
    selected = pick_quick_tasks(sv.site_id, "v0")
    assert len(selected) == 3
    assert all(t.max_steps <= 6 and t.timeout_s == 60 for t in selected)
    assert store.load_site_tasks(sv.site_id) == TASKS
    assert all(
        "timeout_s" not in t or t["timeout_s"] is None
        for t in json.loads((store.site_dir(sv.site_id, "v0") / "abtract-tasks.json").read_text())
    )


def test_quick_tasks_use_real_homepage_links(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    root = store.site_dir("site", "v0")
    root.mkdir(parents=True)
    (root / "index.html").write_text(
        '<h1>Build things</h1><a href="pricing.html">Pricing</a>'
        '<a href="missing.html">Missing</a><a href="https://outside.example">Outside</a>'
        '<a href="../escape.html">Escape</a>'
    )
    (root / "pricing.html").write_text("Plans")
    tasks = pick_quick_tasks("site", "v0")
    assert len(tasks) == 2 and tasks[0].expected_answer == "Build things"
    assert tasks[1].expected_url_pattern == r"^pricing\.html(?:[?#].*)?$"
    assert "Pricing" in tasks[1].prompt


def test_quick_job_avoids_task_generation_and_final_llm_report(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(jobs, "mirror_to_store", _fake_mirror_to_store)
    monkeypatch.setattr(jobs, "serve_site_locally", lambda: ("http://example", lambda: None))

    def forbidden(*a, **kw):
        raise AssertionError("quick scan waited for a model-generated helper")

    monkeypatch.setattr(jobs, "pick_tasks", forbidden)
    monkeypatch.setattr(jobs, "write_findings", forbidden)
    calls = []
    monkeypatch.setattr(jobs, "run_swarm", make_fake_run_swarm(calls))
    job = Job(
        type="intake", url="https://example.com", scan_mode="quick", model_ids=["mock"], agent_kinds=["text", "dom"]
    )
    store.save_job(job)
    result = jobs.run_job_sync(job.id)
    assert result.status == "done", result.error
    assert result.progress_total == 6 and result.findings
    assert calls[0]["kw"]["use_llm_judge"] is False
    assert calls[0]["kw"]["scan_mode"] == "quick"
    assert all(t.max_steps <= 6 for t in calls[0]["tasks"])


def test_optimizing_quick_scan_reuses_baseline_tasks_and_limits(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    sv, _ = _fake_mirror_to_store("https://example.com")
    store.save_site_tasks(sv.site_id, TASKS)
    selected = pick_quick_tasks(sv.site_id, "v0")[:1]
    run = RunSummary(
        site_id=sv.site_id,
        site_version="v0",
        site_url="https://example.com",
        scan_mode="quick",
        tasks=selected,
        model_ids=["mock"],
        agent_kinds=["text"],
        finished_at=time.time(),
    )
    store.save_run(run)
    job = _build_job(JobRequest(type="loop", site_id=sv.site_id, site_version="v0", run_id=run.run_id))
    assert job.scan_mode == "quick"
    calls = []
    monkeypatch.setattr(jobs, "run_swarm", make_fake_run_swarm(calls))
    monkeypatch.setattr(jobs, "optimize_site", _fake_optimize_site)
    monkeypatch.setattr(jobs, "serve_site_locally", lambda: ("http://example", lambda: None))
    store.save_job(job)
    result = jobs.run_job_sync(job.id)
    assert result.status == "done", result.error
    assert calls[0]["tasks"] == selected and calls[0]["kw"]["use_llm_judge"] is False


def test_quick_agent_checks_deadline_after_observation(monkeypatch):
    now = time.time()
    clock = {"now": now}
    monkeypatch.setattr(base, "time", SimpleNamespace(time=lambda: clock["now"]))

    class Agent(base.BaseAgent):
        def start(self, *a):
            pass

        def observe(self):
            clock["now"] += 10
            return base.Observation(text="Home", url="https://example.com")

    def forbidden(*a, **kw):
        raise AssertionError("inference started after the deadline")

    monkeypatch.setattr(base.llm, "chat", forbidden)
    ep = Agent(model_id="mock", run_id="r", site_id="s", site_version="v0").run(
        Task(id="t", kind="answer", prompt="Headline?", timeout_s=5), "https://example.com"
    )
    assert ep.failure_mode == "timeout" and not ep.steps


def test_quick_agent_limits_each_inference_call(monkeypatch):
    captured = {}

    class Agent(base.BaseAgent):
        def start(self, *a):
            pass

        def observe(self):
            return base.Observation(text="Home", url="https://example.com")

    def chat(spec, messages, **kw):
        captured.update(kw)
        return base.llm._chat_mock(spec, messages, True)

    monkeypatch.setattr(base.llm, "chat", chat)
    Agent(model_id="mock", run_id="r", site_id="s", site_version="v0").run(
        Task(id="t", kind="answer", prompt="Headline?", timeout_s=60), "https://example.com"
    )
    assert 0 < captured["timeout_s"] <= 15 and captured["retries"] == 1
