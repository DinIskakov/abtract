"""Judge + aggregate, fully offline (no API keys, tmp data_dir)."""

from __future__ import annotations

import time

import pytest

from app import store
from app.config import settings
from app.metrics.score import (
    aggregate,
    answer_matches,
    compare,
    judge,
    metric_block,
    normalize_answer,
    relative_path,
    url_matches,
)
from app.schemas import Action, Episode, RunSummary, SiteEvent, Step, Task


@pytest.fixture
def tmp_store(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "gemini_api_key", "")  # never call the LLM judge
    return tmp_path


def _ep(task: Task, **kw) -> Episode:
    base = dict(run_id="run_x", site_id="demo", site_version="v0", task_id=task.id, agent_kind="text", model_id="mock")
    base.update(kw)
    return Episode(**base)


# --------------------------------------------------------------------------- answers


def test_normalize_strips_currency_units_and_punctuation():
    assert normalize_answer("$3.95/hr") == "3.95 hour"
    assert normalize_answer("3.95 per hour") == "3.95 hour"
    assert normalize_answer("  US-West-2 ") == "us west 2"
    assert normalize_answer(None) == ""


def test_answer_matches_expected_or_alias_inside_longer_answer():
    assert answer_matches("The H100 costs $3.95 per hour.", "3.95", ["$3.95", "3.95/hr"]) is not None
    assert answer_matches("It is 3.95/hr", "$3.95", []) is not None
    assert answer_matches("us-west-2", "US West 2", []) is not None


def test_answer_matches_rejects_wrong_or_partial_numbers():
    assert answer_matches("It costs $4.25/hr", "3.95", ["$3.95"]) is None
    assert answer_matches("The limit is 128 GB", "8", []) is None  # word boundary: 8 is not 128
    assert answer_matches("", "3.95", []) is None


def test_partial_answer_needs_an_explicit_alias():
    assert answer_matches("A100", "A100 80GB", []) is None
    assert answer_matches("A100", "A100 80GB", ["A100"]) is not None


@pytest.mark.parametrize("answer", ["395", "3.95 per month", "It is not $3.95; it is $9.95.", "13.95", "3.9501"])
def test_numeric_false_positives_rejected(answer):
    assert answer_matches(answer, "$3.95/hr", ["3.95"]) is None


def test_judge_answer(tmp_store):
    task = Task(id="t1", kind="answer", prompt="price?", expected_answer="3.95", answer_aliases=["$3.95"])
    ok = judge(_ep(task, final_answer="It's $3.95 per hour"), task, use_llm_judge=False)
    assert ok.success is True and ok.failure_mode is None and "matches" in ok.judge_reason
    bad = judge(_ep(task, final_answer="about $5"), task, use_llm_judge=True)  # no key -> deterministic fallback
    assert bad.success is False and bad.failure_mode == "wrong_answer"


def test_judge_keeps_agent_failure_mode_when_nothing_to_check(tmp_store):
    task = Task(id="t1", kind="answer", prompt="price?", expected_answer="3.95")
    ep = judge(_ep(task, failure_mode="gave_up"), task, use_llm_judge=False)
    assert ep.success is False and ep.failure_mode == "gave_up"
    ep = judge(_ep(task, failure_mode="max_steps", final_answer="3.95"), task, use_llm_judge=False)
    assert ep.success is True and ep.failure_mode is None  # answered, then hit max steps: the answer counts


# --------------------------------------------------------------------------- urls


def test_relative_path_strips_host_prefix_and_query():
    assert relative_path("https://x.modal.run/s/demo/v0/pricing/?a=1", "demo", "v0") == "pricing/"
    assert relative_path("http://127.0.0.1:1234/s/demo/v0/docs/quickstart.html#x") == "docs/quickstart.html"
    assert relative_path("/pricing.html") == "pricing.html"
    assert relative_path("https://x.modal.run/s/demo/v0/", "demo", "v0") == ""
    assert relative_path(None) == ""


def test_url_matches_pattern_against_relative_path():
    assert url_matches(r"^pricing(\.html|/)?$", "https://h/s/demo/v0/pricing.html", "demo", "v0")
    assert url_matches(r"^pricing(\.html|/)?$", "https://h/s/demo/v0/pricing/", "demo", "v0")
    assert not url_matches(r"^pricing(\.html|/)?$", "https://h/s/demo/v0/docs/pricing.html", "demo", "v0")


def test_judge_url(tmp_store):
    task = Task(id="t2", kind="url", prompt="go to pricing", expected_url_pattern=r"^pricing\.html$")
    ok = judge(_ep(task, final_url="http://127.0.0.1:5000/s/demo/v0/pricing.html?x=1"), task)
    assert ok.success is True and ok.failure_mode is None
    bad = judge(_ep(task, final_url="http://127.0.0.1:5000/s/demo/v0/index.html"), task)
    assert bad.success is False and bad.failure_mode == "wrong_page"
    # ran out of steps but ended on the right page: counts
    late = judge(_ep(task, failure_mode="max_steps", final_url="http://h/s/demo/v0/pricing.html"), task)
    assert late.success is True
    gave = judge(_ep(task, failure_mode="gave_up", final_url="http://h/s/demo/v0/pricing.html"), task)
    assert gave.success is False and gave.failure_mode == "gave_up"
    none = judge(_ep(task), task)
    assert none.success is False and none.failure_mode == "wrong_page"


# --------------------------------------------------------------------------- actions


def test_judge_action_reads_site_events(tmp_store):
    task = Task(
        id="t3",
        kind="action",
        prompt="join waitlist",
        expected_event="waitlist_submit",
        expected_event_match={"email": "Agent@Example.com"},
    )
    ep = _ep(task, failure_mode="max_steps")  # submitted, then wandered until max steps
    store.append_event(
        SiteEvent(
            name="waitlist_submit",
            payload={"email": "agent@example.com", "plan": "pro"},
            site_id="demo",
            version="v0",
            episode_id="someone_else",
        )
    )
    store.append_event(
        SiteEvent(
            name="waitlist_submit",
            payload={"email": "agent@example.com", "plan": "pro"},
            site_id="demo",
            version="v0",
            episode_id=ep.id,
        )
    )
    judge(ep, task)
    assert ep.success is True and ep.failure_mode is None and "waitlist_submit" in ep.judge_reason

    other = _ep(task)
    judge(other, task)
    assert other.success is False and other.failure_mode == "no_event"

    wrong_payload = _ep(task, failure_mode="max_steps")
    store.append_event(
        SiteEvent(
            name="waitlist_submit",
            payload={"email": "someone@else.com"},
            site_id="demo",
            version="v0",
            episode_id=wrong_payload.id,
        )
    )
    judge(wrong_payload, task)
    assert wrong_payload.success is False and wrong_payload.failure_mode == "max_steps"


# --------------------------------------------------------------------------- aggregate / compare


def _step(i: int) -> Step:
    return Step(index=i, url="http://h/s/demo/v0/", action=Action(type="scroll", direction="down"))


def test_aggregate_math(tmp_store):
    t_a = Task(id="ta", kind="answer", prompt="?", expected_answer="1", trap="hidden_text")
    t_b = Task(id="tb", kind="url", prompt="?", expected_url_pattern="x", trap="overlay")
    run = RunSummary(
        site_id="demo",
        site_version="v0",
        site_url="http://h/s/demo/v0/",
        tasks=[t_a, t_b],
        model_ids=["m1", "m2"],
        agent_kinds=["text", "dom"],
    )
    now = time.time()
    eps = [
        _ep(
            t_a,
            model_id="m1",
            agent_kind="text",
            success=True,
            steps=[_step(0), _step(1)],
            started_at=now - 10,
            finished_at=now,
            cost_usd=0.01,
        ),
        _ep(
            t_a,
            model_id="m2",
            agent_kind="dom",
            success=False,
            failure_mode="wrong_answer",
            steps=[_step(0)] * 4,
            started_at=now - 20,
            finished_at=now,
            cost_usd=0.03,
        ),
        _ep(
            t_b,
            model_id="m1",
            agent_kind="dom",
            success=False,
            failure_mode="max_steps",
            steps=[_step(0)] * 6,
            started_at=now - 30,
            finished_at=now,
            cost_usd=0.02,
        ),
        _ep(
            t_b,
            model_id="m2",
            agent_kind="text",
            success=True,
            steps=[],
            started_at=now - 4,
            finished_at=now,
            cost_usd=0.0,
        ),
    ]
    aggregate(run, eps)
    o = run.overall
    assert o.episodes == 4
    assert o.success_rate == pytest.approx(0.5)
    assert o.avg_steps == pytest.approx(3.0)
    assert o.avg_duration_s == pytest.approx(16.0)
    assert o.avg_cost_usd == pytest.approx(0.015)
    assert o.total_cost_usd == pytest.approx(0.06)
    assert o.failure_modes == {"max_steps": 1, "wrong_answer": 1}
    assert run.per_model["m1"].success_rate == pytest.approx(0.5)
    assert run.per_model["m2"].avg_steps == pytest.approx(2.0)
    assert run.per_agent["text"].success_rate == pytest.approx(1.0)
    assert run.per_agent["dom"].success_rate == pytest.approx(0.0)
    assert run.per_task["ta"].episodes == 2 and run.per_task["tb"].failure_modes == {"max_steps": 1}
    assert set(run.per_trap) == {"hidden_text", "overlay"}
    assert run.per_trap["hidden_text"].success_rate == pytest.approx(0.5)
    assert run.finished_at is not None


def test_metric_block_uses_registry_price_when_cost_missing():
    t = Task(id="t", kind="answer", prompt="?", expected_answer="1")
    ep = _ep(t, model_id="kimi-k3", success=True)
    ep.usage.input_tokens = 1_000_000
    b = metric_block([ep])
    from app.models.registry import get_model

    assert b.avg_cost_usd == pytest.approx(get_model("kimi-k3").input_price_per_m)
    assert metric_block([]).episodes == 0


def test_compare_reports_deltas():
    a = RunSummary(site_id="demo", site_version="v0", site_url="u")
    b = RunSummary(site_id="demo", site_version="v1", site_url="u")
    a.overall.success_rate, b.overall.success_rate = 0.25, 0.75
    a.per_task["t1"] = metric_block([])
    a.per_task["t1"].success_rate = 0.0
    b.per_task["t1"] = metric_block([])
    b.per_task["t1"].success_rate = 1.0
    d = compare(a, b)
    assert d["overall"]["success_rate"]["delta"] == pytest.approx(0.5)
    assert d["per_task"]["t1"]["success_rate"] == {"a": 0.0, "b": 1.0, "delta": 1.0}
    assert d["b"]["site_version"] == "v1"
