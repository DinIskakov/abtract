"""run_swarm end to end with a fake run_agent (no site server, no LLM, tmp data_dir)."""

from __future__ import annotations

import json
import sys
import urllib.request

import pytest

import app.agents
from app import store
from app.config import settings
from app.schemas import Action, AgentKind, Episode, RunSummary, Step, Task
from app.swarm.runner import build_payloads, run_episode_sync, run_swarm, serve_site_locally

TASKS = [
    Task(id="t_price", kind="answer", prompt="price?", expected_answer="3.95", answer_aliases=["$3.95"], trap="hidden"),
    Task(id="t_page", kind="url", prompt="go to pricing", expected_url_pattern=r"^pricing\.html$", trap="nav"),
]


@pytest.fixture
def tmp_store(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "gemini_api_key", "")
    return tmp_path


def fake_run_agent(agent_kind, model_id, task, site_url, *, run_id, site_id, site_version, screenshot_dir=None):
    """text agents succeed, dom agents fail; never sets success."""
    kind = AgentKind(agent_kind)
    ep = Episode(
        run_id=run_id, site_id=site_id, site_version=site_version, task_id=task.id, agent_kind=kind, model_id=model_id
    )
    ep.steps = [
        Step(index=0, url=site_url, action=Action(type="navigate", url="pricing.html")),
        Step(index=1, url=site_url + "pricing.html", action=Action(type="answer", text="x")),
    ]
    ep.usage.input_tokens, ep.usage.output_tokens = 1000, 100
    if kind == AgentKind.text:
        ep.final_answer = f"It costs ${task.expected_answer}/hr" if task.expected_answer else "done"
        ep.final_url = site_url + "pricing.html"
    else:
        ep.final_answer = "no idea"
        ep.final_url = site_url
        ep.failure_mode = "max_steps"
    import time

    ep.finished_at = time.time()
    return ep


def test_run_swarm_local_grid(tmp_store, monkeypatch):
    monkeypatch.setattr(app.agents, "run_agent", fake_run_agent)
    run = run_swarm(
        "demo",
        "v0",
        TASKS,
        ["mock", "gemini-flash"],
        ["text", "dom"],
        site_url="http://127.0.0.1:1/s/demo/v0/",
        local=True,
        concurrency=4,
        run_id="run_test",
    )
    assert isinstance(run, RunSummary) and run.run_id == "run_test"
    # files
    run_json = store.run_dir("run_test") / "run.json"
    assert run_json.exists()
    saved = RunSummary.model_validate_json(run_json.read_text())
    assert saved.overall.episodes == 8
    ep_files = list((store.run_dir("run_test") / "episodes").glob("*.json"))
    assert len(ep_files) == 8
    # metrics
    assert run.overall.episodes == 8
    assert run.overall.success_rate == pytest.approx(0.5)
    assert run.per_agent["text"].success_rate == pytest.approx(1.0)
    assert run.per_agent["dom"].success_rate == pytest.approx(0.0)
    # dom answered wrongly on the answer task (judged on the answer) and ran out of steps on the url task
    assert run.per_agent["dom"].failure_modes == {"max_steps": 2, "wrong_answer": 2}
    assert set(run.per_model) == {"mock", "gemini-flash"}
    assert set(run.per_task) == {"t_price", "t_page"}
    assert set(run.per_trap) == {"hidden", "nav"}
    assert run.overall.avg_steps == pytest.approx(2.0)
    assert run.per_model["gemini-flash"].avg_cost_usd > 0  # priced from usage via the registry
    assert run.finished_at is not None
    # every episode was judged and persisted with a reason
    eps = store.load_episodes("run_test")
    assert all(e.success is not None and e.judge_reason for e in eps)
    assert {e.task_id for e in eps if e.success} == {"t_price", "t_page"}


def test_vision_skipped_for_models_without_vision(tmp_store):
    run = RunSummary(site_id="demo", site_version="v0", site_url="u", tasks=TASKS)
    payloads = build_payloads(run, TASKS, ["mock", "qwen3.8-max"], ["vision", "text"])
    combos = {(p["model_id"], p["agent_kind"]) for p in payloads}
    assert combos == {("mock", "vision"), ("mock", "text"), ("qwen3.8-max", "text")}
    assert len(payloads) == 3 * len(TASKS)
    assert isinstance(payloads[0]["task"], dict) and payloads[0]["site_url"] == "u"


def test_agent_exception_becomes_error_episode(tmp_store, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("browser exploded")

    monkeypatch.setattr(app.agents, "run_agent", boom)
    payload = build_payloads(
        RunSummary(site_id="demo", site_version="v0", site_url="u", tasks=TASKS[:1]), TASKS[:1], ["mock"], ["text"]
    )[0]
    d = run_episode_sync(payload)
    ep = Episode(**d)
    assert ep.success is False and ep.failure_mode == "error" and "browser exploded" in ep.error
    assert (store.run_dir(payload["run_id"]) / "episodes" / f"{ep.id}.json").exists()


def test_unknown_model_fails_fast(tmp_store):
    with pytest.raises(KeyError):
        run_swarm("demo", "v0", TASKS, ["nope"], ["text"], site_url="u", local=True)


def test_serve_site_locally_static_fallback(tmp_store, monkeypatch):
    monkeypatch.setitem(sys.modules, "app.hosting.serve", None)  # force the static fallback
    d = store.site_dir("demo", "v0")
    d.mkdir(parents=True)
    (d / "index.html").write_text("<html><body><a href='pricing.html'>Pricing</a></body></html>")
    base, stop = serve_site_locally()
    try:
        with urllib.request.urlopen(f"{base}/s/demo/v0/index.html", timeout=5) as r:
            assert r.status == 200 and b"Pricing" in r.read()
        with urllib.request.urlopen(f"{base}/s/demo/v0/", timeout=5) as r:
            assert b"Pricing" in r.read()  # directory -> index.html
    finally:
        stop()


def test_payload_roundtrip_json(tmp_store):
    run = RunSummary(site_id="demo", site_version="v0", site_url="u", tasks=TASKS)
    payloads = build_payloads(run, TASKS, ["mock"], ["text"])
    assert json.loads(json.dumps(payloads)) == payloads  # Modal serializes payloads; keep them plain
