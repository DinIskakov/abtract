"""Regressions for time to first result and a continuously filled worker pool."""
import threading
from types import SimpleNamespace

import pytest

from abtract.config import settings
from abtract.schemas import RunSummary, Task
from abtract.swarm import runner


@pytest.mark.parametrize("local", [False, True])
def test_slow_attempt_does_not_block_new_attempts(tmp_path, monkeypatch, local):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    tasks = [Task(id=name, kind="answer", prompt=name) for name in ["slow", "fast", "next"]]
    payloads = runner.build_payloads(RunSummary(site_id="demo", site_version="v0", site_url="u"), tasks, ["mock"], ["text"])
    next_started = threading.Event()
    slow_released = threading.Event()
    lock = threading.Lock()
    counts = {"active": 0, "peak": 0}
    completed, started = [], []
    coordinator = threading.get_ident()

    def execute(p):
        with lock:
            counts["active"] += 1
            counts["peak"] = max(counts["peak"], counts["active"])
        try:
            if p["task"]["id"] == "slow":
                assert next_started.wait(2), "the next attempt waited for the slow batch member"
                slow_released.set()
            elif p["task"]["id"] == "next":
                assert not slow_released.is_set()
                next_started.set()
            return runner.error_episode(p, "fixture result").model_dump(mode="json")
        finally:
            with lock:
                counts["active"] -= 1

    def on_episode(ep):
        assert threading.get_ident() == coordinator
        completed.append(ep.task_id)

    def on_start(ps):
        assert threading.get_ident() == coordinator
        started.extend(p["task"]["id"] for p in ps)

    monkeypatch.setattr(runner, "run_episode_sync", execute)
    monkeypatch.setattr(runner, "run_episode", SimpleNamespace(remote=execute))
    if local:
        result = runner._fan_out_local(payloads, 2, on_episode, on_start=on_start)
    else:
        result = runner._fan_out_modal(payloads, on_episode, concurrency=2, on_start=on_start)
    assert slow_released.is_set()
    assert counts["peak"] <= 2
    assert completed[0] == "fast"
    assert started == ["slow", "fast", "next"]
    assert {ep.task_id for ep in result} == set(started)


def test_remote_error_keeps_its_original_task(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    tasks = [Task(id=name, kind="answer", prompt=name) for name in ["first", "second"]]
    payloads = runner.build_payloads(RunSummary(site_id="demo", site_version="v0", site_url="u"), tasks, ["mock"], ["text"])
    def execute(p):
        raise RuntimeError(f"failure on {p['task']['id']}")
    monkeypatch.setattr(runner, "run_episode", SimpleNamespace(remote=execute))
    result = runner._fan_out_modal(payloads, None, concurrency=2)
    assert all(f"failure on {ep.task_id}" in ep.error for ep in result)


def test_short_checks_start_first_without_changing_coverage():
    tasks = [Task(id="long", kind="action", prompt="Sign up", max_steps=20),
             Task(id="short", kind="answer", prompt="Headline?", max_steps=3)]
    run = RunSummary(site_id="demo", site_version="v0", site_url="u")
    payloads = runner.build_payloads(run, tasks, ["mock", "gemini-flash"], ["text", "dom", "vision"])
    assert len(payloads) == 12
    assert all(p["task"]["id"] == "short" for p in payloads[:6])
    assert [p["model_id"] for p in payloads[:2]] == ["mock", "gemini-flash"]
    assert len({(p["task"]["id"], p["model_id"], p["agent_kind"]) for p in payloads}) == 12
