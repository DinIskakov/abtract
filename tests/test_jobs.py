"""Job orchestration (abtract/jobs.py) with every collaborator faked: tmp data_dir, no site server, no LLM."""
from __future__ import annotations

import time

import pytest

from abtract import jobs, store
from abtract.config import settings
from abtract.hosting import urls
from abtract.intake.mirror import MirrorReport
from abtract.metrics.score import aggregate
from abtract.optimizer import findings
from abtract.schemas import Action, AgentKind, Episode, Job, RunSummary, SiteVersion, Step, Task

TASKS = [
    Task(id="t_price", kind="answer", prompt="How much is an H100?", expected_answer="3.95", trap="canvas"),
    Task(id="t_page", kind="url", prompt="Go to pricing", expected_url_pattern=r"^pricing\.html$", trap="nav"),
    Task(id="t_form", kind="action", prompt="Join the waitlist", expected_event="waitlist_submit", trap="form"),
]


@pytest.fixture
def tmp_store(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path / "data")
    monkeypatch.setattr(settings, "gemini_api_key", "")
    monkeypatch.delenv("ABTRACT_OPTIMIZER_MODEL", raising=False)
    return tmp_path / "data"


def _fake_episode(run: RunSummary, task: Task, model_id: str, kind: str, *, success: bool, mode: str | None = None,
                  steps: int = 2) -> Episode:
    ep = Episode(run_id=run.run_id, site_id=run.site_id, site_version=run.site_version, task_id=task.id,
                 agent_kind=AgentKind(kind), model_id=model_id, success=success,
                 failure_mode=None if success else mode, judge_reason="ok" if success else f"expected x, got y",
                 finished_at=time.time() + 1)
    ep.steps = [Step(index=i, url=run.site_url, action=Action(type="navigate", url="pricing.html")) for i in range(steps)]
    ep.usage.input_tokens, ep.usage.output_tokens = 1000, 100
    return ep


def make_fake_run_swarm(calls: list, *, text_success: bool = False):
    """A run_swarm stand-in: text agents succeed/fail per flag, dom succeeds, vision runs out of steps."""

    def fake_run_swarm(site_id, site_version, tasks, model_ids, agent_kinds, *, site_url, local, on_episode=None, **kw):
        calls.append({"site_id": site_id, "site_version": site_version, "tasks": tasks, "model_ids": model_ids,
                      "agent_kinds": agent_kinds, "site_url": site_url, "local": local, "kw": kw})
        run = RunSummary(site_id=site_id, site_version=site_version, site_url=site_url, tasks=list(tasks),
                         model_ids=list(model_ids), agent_kinds=[AgentKind(k) for k in agent_kinds])
        store.save_run(run)
        episodes = []
        for m in model_ids:
            for k in agent_kinds:
                k = AgentKind(k).value
                for t in tasks:
                    if k == "text":
                        ep = _fake_episode(run, t, m, k, success=text_success, mode="wrong_answer")
                    elif k == "dom":
                        ep = _fake_episode(run, t, m, k, success=t.kind.value != "action", mode="no_event")
                    else:
                        ep = _fake_episode(run, t, m, k, success=False, mode="max_steps", steps=10)
                    store.save_episode(ep)
                    episodes.append(ep)
                    if on_episode:
                        on_episode(ep)
        aggregate(run, episodes)
        store.save_run(run)
        return run

    return fake_run_swarm


def _fake_mirror_to_store(url, *, site_id=None, **kw):
    site_id = site_id or "fake-site"
    d = store.site_dir(site_id, "v0")
    d.mkdir(parents=True, exist_ok=True)
    (d / "index.html").write_text("<html><body><a href='pricing.html'>Pricing</a></body></html>")
    (d / "pricing.html").write_text("<html><body>$3.95</body></html>")
    import json

    (d / "abtract-tasks.json").write_text(json.dumps([t.model_dump(mode="json") for t in TASKS]))
    sv = SiteVersion(site_id=site_id, version="v0", notes=f"Mirrored from {url}", changed_files=["index.html", "pricing.html"])
    store.register_version(sv)
    return sv, MirrorReport(root_url=url, pages=["index.html", "pricing.html"], assets=[], tasks_file=True)


@pytest.fixture
def faked(tmp_store, monkeypatch):
    calls: list = []
    monkeypatch.setattr(jobs, "run_swarm", make_fake_run_swarm(calls))
    monkeypatch.setattr(jobs, "mirror_to_store", _fake_mirror_to_store)
    monkeypatch.setattr(jobs, "serve_site_locally", lambda port=None: ("http://127.0.0.1:1", lambda: None))
    findings_calls: list = []

    def stub_findings(run, episodes, tasks, *, baseline=None):
        findings_calls.append({"run": run, "n_episodes": len(episodes), "tasks": tasks, "baseline": baseline})
        return f"FINDINGS for {run.site_version}"

    monkeypatch.setattr(jobs, "write_findings", stub_findings)
    return {"swarm": calls, "findings": findings_calls}


def _phase_order(job: Job, *phases: str) -> None:
    text = "\n".join(job.log)
    positions = [text.find(p) for p in phases]
    assert all(p >= 0 for p in positions), f"missing phases in log: {phases} -> {positions}\n{text}"
    assert positions == sorted(positions), f"phases out of order: {phases} -> {positions}"


# --------------------------------------------------------------------------- intake

def test_intake_job_runs_all_phases(faked):
    job = Job(type="intake", url="http://127.0.0.1:9/", model_ids=["mock"], agent_kinds=["text", "dom"])
    store.save_job(job)
    out = jobs.run_job_sync(job.id)
    saved = store.load_job(job.id)
    assert out.status == saved.status == "done" and saved.error is None
    assert saved.phase == "Done"
    assert saved.site_id == "fake-site" and saved.site_version == "v0"
    assert len(saved.run_ids) == 1 and store.load_run(saved.run_ids[0]).site_id == "fake-site"
    assert saved.progress_total == 2 * len(TASKS) and saved.progress_done == saved.progress_total
    assert saved.findings == "FINDINGS for v0"
    _phase_order(saved, "Mirroring site", "Choosing tasks", "Running swarm", "Writing findings", "done")
    assert any("3 tasks (site-provided)" in line for line in saved.log)
    # the swarm was called with the job's grid against the locally served site
    call = faked["swarm"][0]
    assert call["site_id"] == "fake-site" and call["site_version"] == "v0" and call["local"] is True
    assert call["model_ids"] == ["mock"] and [k.value for k in call["agent_kinds"]] == ["text", "dom"]
    assert call["site_url"] == "http://127.0.0.1:1/s/fake-site/v0/"
    assert [t.id for t in call["tasks"]] == [t.id for t in TASKS]
    assert store.load_site_tasks("fake-site") is not None
    # findings got the persisted episodes
    assert faked["findings"][0]["n_episodes"] == 2 * len(TASKS) and faked["findings"][0]["baseline"] is None
    assert saved.updated_at >= saved.created_at


def test_intake_defaults_to_default_swarm_and_all_agents(faked, monkeypatch):
    monkeypatch.setattr(jobs, "DEFAULT_SWARM", ["mock"])
    job = Job(type="intake", url="http://127.0.0.1:9/")
    store.save_job(job)
    jobs.run_job_sync(job.id)
    call = faked["swarm"][0]
    assert call["model_ids"] == ["mock"] and [k.value for k in call["agent_kinds"]] == ["text", "dom", "vision"]
    assert store.load_job(job.id).progress_total == 3 * len(TASKS)


def test_progress_is_written_during_the_swarm(faked, monkeypatch):
    seen: list[int] = []
    real_save = store.save_job

    def spy(job):
        seen.append(job.progress_done)
        real_save(job)

    monkeypatch.setattr(store, "save_job", spy)
    job = Job(type="intake", url="http://127.0.0.1:9/", model_ids=["mock"], agent_kinds=["text"])
    store.save_job(job)
    jobs.run_job_sync(job.id)
    assert [n for n in seen if n] and max(seen) == len(TASKS)
    assert sorted(set(seen)) == list(range(0, len(TASKS) + 1))  # 0,1,2,3: one save per episode


# --------------------------------------------------------------------------- loop

def _fake_optimize_site(site_id, version, run_id, *, local):
    import shutil

    new = store.next_version(site_id)
    shutil.copytree(store.site_dir(site_id, version), store.site_dir(site_id, new))
    (store.site_dir(site_id, new) / "pricing.html").write_text("<html><body><table><tr><td>$3.95</td></tr></table></body></html>")
    sv = SiteVersion(site_id=site_id, version=new, parent=version, notes=f"fake optimizer from {run_id}",
                     changed_files=["pricing.html"])
    store.register_version(sv)
    return sv


def test_loop_job_optimizes_and_reruns(faked, monkeypatch):
    monkeypatch.setattr(jobs, "optimize_site", _fake_optimize_site)
    # an intake happened before: site v0 + tasks + a baseline run
    _fake_mirror_to_store("http://x/")
    store.save_site_tasks("fake-site", TASKS)
    baseline = jobs.run_swarm("fake-site", "v0", TASKS, ["mock"], ["text"], site_url="http://x/s/fake-site/v0/", local=True)
    faked["swarm"].clear()

    job = Job(type="loop", site_id="fake-site", site_version="v0", run_ids=[baseline.run_id], iterations=2,
              model_ids=["mock"], agent_kinds=["text"])
    store.save_job(job)
    jobs.run_job_sync(job.id)
    saved = store.load_job(job.id)
    assert saved.status == "done", saved.error
    assert saved.site_version == "v2"
    assert saved.run_ids[0] == baseline.run_id and len(saved.run_ids) == 3
    assert [v.version for v in store.list_versions("fake-site")] == ["v0", "v1", "v2"]
    assert [c["site_version"] for c in faked["swarm"]] == ["v1", "v2"]
    assert all([t.id for t in c["tasks"]] == [t.id for t in TASKS] for c in faked["swarm"])
    _phase_order(saved, "Optimizing v0", "Running swarm on v1", "Optimizing v1", "Running swarm on v2", "Writing findings")
    assert saved.findings == "FINDINGS for v2"
    f = faked["findings"][-1]
    assert f["baseline"] is not None and f["baseline"].run_id == baseline.run_id and f["run"].site_version == "v2"
    assert saved.progress_done == saved.progress_total


def test_loop_job_without_baseline_runs_one_first(faked, monkeypatch):
    monkeypatch.setattr(jobs, "optimize_site", _fake_optimize_site)
    _fake_mirror_to_store("http://x/")
    job = Job(type="loop", site_id="fake-site", iterations=1, model_ids=["mock"], agent_kinds=["dom"])
    store.save_job(job)
    jobs.run_job_sync(job.id)
    saved = store.load_job(job.id)
    assert saved.status == "done", saved.error
    assert [c["site_version"] for c in faked["swarm"]] == ["v0", "v1"]
    assert len(saved.run_ids) == 2 and saved.site_version == "v1"
    assert any("baseline" in line for line in saved.log)


# --------------------------------------------------------------------------- failures & start_job

def test_failing_job_sets_status_failed(faked, monkeypatch):
    def boom(url, *, site_id=None, **kw):
        raise RuntimeError("could not fetch anything")

    monkeypatch.setattr(jobs, "mirror_to_store", boom)
    job = Job(type="intake", url="http://127.0.0.1:9/", model_ids=["mock"], agent_kinds=["text"])
    store.save_job(job)
    out = jobs.run_job_sync(job.id)  # must not raise
    saved = store.load_job(job.id)
    assert out.status == saved.status == "failed"
    assert "could not fetch anything" in saved.error and saved.phase == "Mirroring site"
    assert any("FAILED in phase 'Mirroring site'" in line for line in saved.log)
    assert saved.run_ids == [] and saved.findings is None


def test_loop_job_missing_site_fails(faked):
    job = Job(type="loop", site_id="nope", site_version="v0", model_ids=["mock"], agent_kinds=["text"])
    store.save_job(job)
    saved = jobs.run_job_sync(job.id)
    assert saved.status == "failed" and "nope/v0" in saved.error


def test_start_job_runs_in_a_thread_locally(faked):
    job = Job(type="intake", url="http://127.0.0.1:9/", model_ids=["mock"], agent_kinds=["text"])
    returned = jobs.start_job(job)
    assert returned.id == job.id and (store.jobs_dir() / f"{job.id}.json").exists()
    for _ in range(200):
        if store.load_job(job.id).status in ("done", "failed"):
            break
        time.sleep(0.05)
    saved = store.load_job(job.id)
    assert saved.status == "done", saved.error
    assert saved in store.list_jobs()


def test_start_job_spawns_on_modal(faked, monkeypatch):
    import modal

    spawned: list[str] = []
    monkeypatch.setattr(modal, "is_local", lambda: False)
    monkeypatch.setattr(jobs.run_job, "spawn", lambda job_id: spawned.append(job_id), raising=False)
    job = Job(type="intake", url="http://127.0.0.1:9/")
    jobs.start_job(job)
    assert spawned == [job.id]
    assert store.load_job(job.id).status == "queued"


# --------------------------------------------------------------------------- findings (rule-based, real)

def test_write_findings_rule_based(tmp_store, monkeypatch):
    monkeypatch.setattr(findings, "chat", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("no llm")))
    calls: list = []
    fake = make_fake_run_swarm(calls)
    run = fake("s", "v0", TASKS, ["mock"], ["text", "dom", "vision"], site_url="http://x/s/s/v0/", local=True)
    episodes = store.load_episodes(run.run_id)
    text = findings.write_findings(run, episodes, TASKS)
    assert text.startswith("# Findings for s/v0")
    assert "of 9 attempts succeeded" in text
    assert "By agent: dom 67% (3) · text 0% (3) · vision 0% (3)" in text
    assert "By model: mock" in text
    assert "## Hardest tasks" in text and "**t_form** (action, trap: form) failed 3/3" in text
    assert "wrong answer" in text or "form never submitted" in text
    assert "## What this suggests" in text
    assert "JavaScript" in text  # text fails where dom succeeds
    assert "form" in text.lower() and "ran out of steps" in text
    assert len(text.split()) <= 420
    assert "In plain English" not in text  # no key, no LLM section
    # baseline comparison line for loop jobs
    better = make_fake_run_swarm([], text_success=True)("s", "v1", TASKS, ["mock"], ["text", "dom", "vision"],
                                                       site_url="http://x/s/s/v1/", local=True)
    text2 = findings.write_findings(better, store.load_episodes(better.run_id), TASKS, baseline=run)
    assert "**Compared with v0**" in text2 and "22% -> 56% (+33 pts)" in text2


def test_write_findings_llm_section_with_mock(tmp_store, monkeypatch):
    monkeypatch.setenv("ABTRACT_OPTIMIZER_MODEL", "mock")
    monkeypatch.setenv("ABTRACT_MOCK_REPLY", "Agents trip on the canvas. Top 3 fixes: 1. table 2. labels 3. nav")
    run = make_fake_run_swarm([])("s", "v0", TASKS, ["mock"], ["text"], site_url="http://x/s/s/v0/", local=True)
    text = findings.write_findings(run, store.load_episodes(run.run_id), TASKS)
    assert "## In plain English" in text and "Agents trip on the canvas" in text


def test_write_findings_never_raises(tmp_store):
    run = RunSummary(site_id="s", site_version="v0", site_url="u")
    text = findings.write_findings(run, [], [])
    assert "Findings for s/v0" in text


# --------------------------------------------------------------------------- urls

def test_resolve_site_base_url(monkeypatch):
    monkeypatch.setattr(settings, "site_base_url", "https://ws--abtract-site.modal.run/")
    assert urls.resolve_site_base_url() == "https://ws--abtract-site.modal.run"
    assert urls.site_url("demo", "v0") == "https://ws--abtract-site.modal.run/s/demo/v0/"
    assert urls.demo_site_url() == urls.site_url("demo", "v0")
    # no env, modal lookup fails -> localhost, and the failure is cached
    monkeypatch.setattr(settings, "site_base_url", "")
    monkeypatch.setattr(urls, "_cached", None)
    monkeypatch.setattr(urls, "_failed_at", None)
    n = {"calls": 0}

    def fail():
        n["calls"] += 1
        raise RuntimeError("no modal token")

    monkeypatch.setattr(urls, "_modal_web_url", fail)
    assert urls.resolve_site_base_url() == "http://localhost:8000"
    assert urls.resolve_site_base_url() == "http://localhost:8000" and n["calls"] == 1
    monkeypatch.setattr(urls, "_modal_web_url", lambda: "https://x.modal.run/")
    assert urls.resolve_site_base_url(refresh=True) == "https://x.modal.run"
    assert urls.site_url("a", "v1") == "https://x.modal.run/s/a/v1/"
