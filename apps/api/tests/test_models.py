"""Pricing table, model selection, Modal model-name resolution, cost estimate and budget cap. Fully offline."""

from __future__ import annotations

import re
import time
from types import SimpleNamespace

import pytest

import app.agents
from app import store
from app.config import settings
from app.models import llm, registry
from app.models.llm import ChatMessage, match_model_name, resolve_modal_model
from app.models.pricing import CHECKED_ON, SHARED_ENDPOINT_MODELS
from app.models.registry import CHEAPEST_10, DEFAULT_SWARM, MODELS, cost_rank, get_model, select_models
from app.schemas import Episode, ModelSpec, Task
from app.swarm.runner import BudgetExceeded, estimate_run_cost, run_swarm

TASKS = [Task(id=f"t{i}", kind="answer", prompt="?", expected_answer="1") for i in range(4)]


@pytest.fixture
def tmp_store(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    monkeypatch.setattr(settings, "gemini_api_key", "")
    return tmp_path


@pytest.fixture
def fresh_resolution():
    llm.reset_modal_model_cache()
    yield
    llm.reset_modal_model_cache()


def _ids(specs: list[ModelSpec]) -> list[str]:
    return [s.id for s in specs]


# --------------------------------------------------------------------------- pricing table -> registry


def test_pricing_rows_are_verified_positive_and_unique():
    ids = [r["id"] for r in SHARED_ENDPOINT_MODELS]
    modal_ids = [r["modal_id"] for r in SHARED_ENDPOINT_MODELS]
    assert ids and len(ids) == len(set(ids)) and len(modal_ids) == len(set(modal_ids))
    assert CHECKED_ON == "2026-09-19"
    for r in SHARED_ENDPOINT_MODELS:
        assert r["shared_endpoint"] is True
        assert r["input_price_per_m"] > 0 and r["output_price_per_m"] > 0
        assert r["source_url"].startswith("https://modal.com/library/")
        assert r["checked_on"] == CHECKED_ON
        assert re.fullmatch(r"[\w.-]+/[\w.-]+", r["modal_id"]), r["modal_id"]
        assert isinstance(r["supports_vision"], bool)
        assert r["context_tokens"] > 0


def test_registry_is_built_from_the_pricing_table():
    for r in SHARED_ENDPOINT_MODELS:
        spec = MODELS[r["id"]]
        assert spec.provider == "modal" and spec.model == r["modal_id"]
        assert spec.input_price_per_m == r["input_price_per_m"] and spec.output_price_per_m == r["output_price_per_m"]
        assert spec.supports_vision == r["supports_vision"]
    assert MODELS["mock"].provider == "mock" and MODELS["gemini-flash"].provider == "gemini"
    assert CHEAPEST_10[:2] == DEFAULT_SWARM
    assert all(m in MODELS for m in DEFAULT_SWARM)
    assert get_model("kimi-k3").model == "moonshotai/Kimi-K3"
    with pytest.raises(KeyError):
        get_model("nope")


def test_env_override_replaces_the_model_string(monkeypatch):
    monkeypatch.setenv("ABTRACT_MODEL_KIMI_K3", "kimi-k3.us-west.modal.direct")
    monkeypatch.setenv("ABTRACT_MODEL_DEEPSEEK_V4_1_FLASH", "  ")  # blank = keep the default
    built = registry.build_models()
    assert built["kimi-k3"].model == "kimi-k3.us-west.modal.direct"
    assert built["kimi-k3"].input_price_per_m == MODELS["kimi-k3"].input_price_per_m
    assert built["deepseek-v4.1-flash"].model == "deepseek-ai/DeepSeek-V4.1-Flash"
    assert registry.env_key("deepseek-v4.1-flash") == "ABTRACT_MODEL_DEEPSEEK_V4_1_FLASH"


def test_cheapest_is_sorted_by_cost_rank():
    assert cost_rank(get_model("kimi-k3")) == pytest.approx(0.8 * 3.00 + 0.2 * 15.00)
    ranks = [cost_rank(MODELS[i]) for i in CHEAPEST_10]
    assert ranks == sorted(ranks)
    assert 0 < len(CHEAPEST_10) <= 10
    assert all(MODELS[i].provider == "modal" for i in CHEAPEST_10)
    assert CHEAPEST_10[0] == "deepseek-v4.1-flash"
    assert set(CHEAPEST_10) <= {r["id"] for r in SHARED_ENDPOINT_MODELS}


# --------------------------------------------------------------------------- select_models


def test_select_models_ids_and_selectors():
    assert _ids(select_models("deepseek-v4.1-flash,kimi-k3")) == ["deepseek-v4.1-flash", "kimi-k3"]
    assert _ids(select_models("cheapest:2")) == CHEAPEST_10[:2]
    assert _ids(select_models("cheapest:100")) == CHEAPEST_10  # capped at what exists
    assert _ids(select_models("cheapest")) == CHEAPEST_10
    assert _ids(select_models("default")) == DEFAULT_SWARM
    assert _ids(select_models("mock")) == ["mock"]
    vision = select_models("vision")
    assert vision and all(s.supports_vision and s.provider == "modal" for s in vision)
    assert [cost_rank(s) for s in vision] == sorted(cost_rank(s) for s in vision)
    assert set(_ids(select_models("all"))) == {r["id"] for r in SHARED_ENDPOINT_MODELS}
    assert _ids(select_models(" mock , mock,DEFAULT ")) == ["mock", *DEFAULT_SWARM]  # dedupe, spaces, case
    assert _ids(select_models("CHEAPEST:1")) == CHEAPEST_10[:1]
    assert _ids(select_models("gemini-flash,cheapest:1")) == ["gemini-flash", CHEAPEST_10[0]]


@pytest.mark.parametrize("bad", ["", "nope", "cheapest:x", "cheapest:0", "mock,,nope"])
def test_select_models_rejects_bad_specs(bad):
    with pytest.raises(ValueError):
        select_models(bad)


# --------------------------------------------------------------------------- resolve_modal_model


def _spec(model: str, provider: str = "modal") -> ModelSpec:
    return ModelSpec(id="x", provider=provider, model=model, display_name="x")


def _listing(monkeypatch, names, calls=None):
    def discover(base_url=None):
        if calls is not None:
            calls.append(1)
        if isinstance(names, Exception):
            raise names
        return list(names)

    monkeypatch.setattr(registry, "discover_modal_models", discover)


def test_match_model_name_rules():
    names = [
        "deepseek-ai/DeepSeek-V4.1-Flash",
        "glm-5-3-flash.us-west.modal.direct",
        "glm-5-3.us-west.modal.direct",
        "moonshotai/kimi-k3",
        "Qwen/Qwen3.8-2.4T-A95B",
    ]
    assert match_model_name("deepseek-ai/DeepSeek-V4.1-Flash", names) == "deepseek-ai/DeepSeek-V4.1-Flash"  # exact
    assert match_model_name("moonshotai/Kimi-K3", names) == "moonshotai/kimi-k3"  # case
    assert match_model_name("zai-org/GLM-5.3-Flash", names) == "glm-5-3-flash.us-west.modal.direct"  # normalized
    assert match_model_name("zai-org/GLM-5.3", names) == "glm-5-3.us-west.modal.direct"  # equality beats substring
    assert match_model_name("Qwen3.8-2.4T-A95B", names) == "Qwen/Qwen3.8-2.4T-A95B"  # org prefix optional
    assert (
        match_model_name("zai-org/GLM-5.3", ["glm-5-3-flash.us-west.modal.direct"])
        == "glm-5-3-flash.us-west.modal.direct"
    )  # substring, last resort
    assert match_model_name("openai/gpt-oss-120b", names) is None
    assert match_model_name("moonshotai/Kimi-K3", ["k3"]) is None  # too short to trust
    assert match_model_name("x", []) is None


def test_resolve_exact_name_is_sent_as_is(monkeypatch, fresh_resolution):
    _listing(monkeypatch, ["deepseek-ai/DeepSeek-V4.1-Flash", "other/Model"])
    assert resolve_modal_model(_spec("deepseek-ai/DeepSeek-V4.1-Flash")) == "deepseek-ai/DeepSeek-V4.1-Flash"


def test_resolve_matches_endpoint_hostname(monkeypatch, fresh_resolution):
    _listing(monkeypatch, ["deepseek-v4-1-flash.us-west.modal.direct", "glm-5-3-flash.us-west.modal.direct"])
    assert resolve_modal_model(_spec("deepseek-ai/DeepSeek-V4.1-Flash")) == "deepseek-v4-1-flash.us-west.modal.direct"
    assert resolve_modal_model(_spec("zai-org/GLM-5.3-Flash")) == "glm-5-3-flash.us-west.modal.direct"


def test_resolve_no_match_or_no_listing_leaves_name_unchanged(monkeypatch, fresh_resolution):
    calls: list[int] = []
    _listing(monkeypatch, ["something/else"], calls)
    assert resolve_modal_model(_spec("moonshotai/Kimi-K3")) == "moonshotai/Kimi-K3"
    llm.reset_modal_model_cache()
    _listing(monkeypatch, RuntimeError("MODAL_PROXY_TOKEN is not set"), calls)
    assert resolve_modal_model(_spec("moonshotai/Kimi-K3")) == "moonshotai/Kimi-K3"
    assert resolve_modal_model(_spec("zai-org/GLM-5.3")) == "zai-org/GLM-5.3"
    assert len(calls) == 2  # one listing per process (per reset), even when it fails


def test_resolve_is_cached_and_skips_non_modal(monkeypatch, fresh_resolution):
    calls: list[int] = []
    _listing(monkeypatch, ["kimi-k3.us-west.modal.direct"], calls)
    assert resolve_modal_model(_spec("gemini-3.8-flash", provider="gemini")) == "gemini-3.8-flash"
    assert calls == []
    for _ in range(3):
        assert resolve_modal_model(_spec("moonshotai/Kimi-K3")) == "kimi-k3.us-west.modal.direct"
    assert len(calls) == 1


def test_chat_sends_the_resolved_name(monkeypatch, fresh_resolution):
    captured: dict = {}

    class FakeCompletions:
        def create(self, **kw):
            captured.update(kw)
            return SimpleNamespace(
                id="r1",
                model=kw["model"],
                choices=[SimpleNamespace(message=SimpleNamespace(content="hi"))],
                usage=SimpleNamespace(prompt_tokens=7, completion_tokens=2),
            )

    class FakeOpenAI:
        def __init__(self, **kw):
            captured["client_kwargs"] = kw
            self.chat = SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setattr("openai.OpenAI", FakeOpenAI)
    monkeypatch.setattr(settings, "modal_proxy_token", "wk-x.ws-y")
    _listing(monkeypatch, ["kimi-k3.us-west.modal.direct"])
    r = llm.chat(get_model("kimi-k3"), [ChatMessage(role="user", content="hello")], retries=1)
    assert captured["model"] == "kimi-k3.us-west.modal.direct"
    assert captured["client_kwargs"]["api_key"] == "wk-x.ws-y"
    assert captured["client_kwargs"]["max_retries"] == 0
    assert captured["client_kwargs"]["timeout"] == settings.step_timeout_s
    assert r.text == "hi" and r.usage.input_tokens == 7 and r.usage.llm_calls == 1


def test_gemini_auth_failure_is_actionable_and_not_retried(monkeypatch):
    calls = []

    class Rejected(Exception):
        code = 401

    def reject(*a, **kw):
        calls.append(1)
        raise Rejected("ACCESS_TOKEN_TYPE_UNSUPPORTED")

    monkeypatch.setattr(llm, "_chat_gemini", reject)
    with pytest.raises(llm.LLMError, match="Google AI Studio.*GEMINI_API_KEY.*abtract-secrets"):
        llm.chat(get_model("gemini-flash"), [ChatMessage(role="user", content="hello")])
    assert calls == [1]


def test_per_model_endpoint_url_falls_back_to_gateway(monkeypatch):
    monkeypatch.setattr(settings, "modal_inference_base_url", "https://gateway.example/v1/")
    monkeypatch.setenv("ABTRACT_BASE_URL_DEEPSEEK_V4_1_FLASH", " https://deepseek.example/v1/ ")
    monkeypatch.setenv("ABTRACT_BASE_URL_GLM_5_3_FLASH", " ")
    assert llm.modal_base_url(get_model("deepseek-v4.1-flash")) == "https://deepseek.example/v1"
    assert llm.modal_base_url(get_model("glm-5.3-flash")) == "https://gateway.example/v1"


def test_discovery_uses_requested_endpoint(monkeypatch):
    captured = {}

    def fake_get(url, **kwargs):
        captured.update(url=url, **kwargs)
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {"data": [{"id": "served-model"}]})

    monkeypatch.setattr("httpx.get", fake_get)
    monkeypatch.setattr(settings, "modal_proxy_token", "test-proxy-token")
    assert registry.discover_modal_models("https://endpoint.example/v1/") == ["served-model"]
    assert captured["url"] == "https://endpoint.example/v1/models"
    assert captured["headers"]["Authorization"] == "Bearer test-proxy-token"


def test_resolution_cache_is_separate_for_each_endpoint(monkeypatch, fresh_resolution):
    calls = []

    def discover(base_url=None):
        calls.append(base_url)
        return ["model-first"] if base_url == "https://first.example/v1" else ["model-second"]

    monkeypatch.setattr(registry, "discover_modal_models", discover)
    monkeypatch.setenv("ABTRACT_BASE_URL_FIRST", "https://first.example/v1")
    monkeypatch.setenv("ABTRACT_BASE_URL_SECOND", "https://second.example/v1")
    first = ModelSpec(id="first", provider="modal", model="vendor/model", display_name="First")
    second = first.model_copy(update={"id": "second"})
    for _ in range(2):
        assert resolve_modal_model(first) == "model-first"
        assert resolve_modal_model(second) == "model-second"
    assert calls == ["https://first.example/v1", "https://second.example/v1"]


@pytest.mark.parametrize(
    "model_id,suffix",
    [
        ("deepseek-v4.1-flash", "DEEPSEEK_V4_1_FLASH"),
        ("glm-5.3-flash", "GLM_5_3_FLASH"),
    ],
)
def test_chat_uses_its_models_endpoint(monkeypatch, fresh_resolution, model_id, suffix):
    captured = {}
    spec = get_model(model_id)
    base = f"https://{model_id}.example/v1"

    class FakeOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.complete))

        def complete(self, **kwargs):
            captured["model"] = kwargs["model"]
            return SimpleNamespace(id="test", model=kwargs["model"], choices=[], usage=None)

    monkeypatch.setattr("openai.OpenAI", FakeOpenAI)
    monkeypatch.setattr(settings, "modal_proxy_token", "test-token")
    monkeypatch.setenv(f"ABTRACT_BASE_URL_{suffix}", base)
    _listing(monkeypatch, [spec.model])
    llm.chat(spec, [ChatMessage(role="user", content="test")], retries=1)
    assert captured["base_url"] == base and captured["model"] == spec.model


# --------------------------------------------------------------------------- estimate_run_cost


def test_estimate_run_cost_math():
    est = estimate_run_cost(
        TASKS[:2],
        ["kimi-k3", "qwen3.8-max"],
        ["text", "vision"],
        avg_steps=10,
        tokens_in_per_step=1000,
        tokens_out_per_step=100,
    )
    kimi, qwen = get_model("kimi-k3"), get_model("qwen3.8-max")
    assert kimi.supports_vision and not qwen.supports_vision

    def ep(spec, mult):
        return (10 * 1000 * mult * spec.input_price_per_m + 10 * 100 * spec.output_price_per_m) / 1e6

    assert est["per_model"]["kimi-k3"] == pytest.approx(2 * ep(kimi, 1.0) + 2 * ep(kimi, 1.5))
    assert est["per_model"]["qwen3.8-max"] == pytest.approx(2 * ep(qwen, 1.0))  # vision skipped
    assert est["episodes"] == 6
    assert est["assumptions"]["episodes_per_model"] == {"kimi-k3": 4, "qwen3.8-max": 2}
    assert est["total_usd"] == pytest.approx(sum(est["per_model"].values()))
    assert est["assumptions"]["avg_steps"] == 10 and est["assumptions"]["vision_input_multiplier"] == 1.5
    assert estimate_run_cost(TASKS, ["mock"], ["text", "dom", "vision"])["total_usd"] == 0.0
    with pytest.raises(KeyError):
        estimate_run_cost(TASKS, ["nope"], ["text"])


def test_estimate_caps_steps_at_task_max_steps():
    short = [Task(id="s", kind="answer", prompt="?", expected_answer="1", max_steps=2)]
    est = estimate_run_cost(short, ["kimi-k3"], ["text"], avg_steps=8, tokens_in_per_step=1000, tokens_out_per_step=0)
    assert est["total_usd"] == pytest.approx(2 * 1000 * 3.00 / 1e6)


# --------------------------------------------------------------------------- run_swarm budget


def test_run_swarm_raises_budget_exceeded_before_launching(tmp_store, monkeypatch):
    def must_not_run(*a, **k):
        raise AssertionError("an episode was launched despite the budget")

    monkeypatch.setattr(app.agents, "run_agent", must_not_run)
    with pytest.raises(BudgetExceeded) as ei:
        run_swarm(
            "demo", "v0", TASKS, ["kimi-k3"], ["text"], site_url="u", local=True, run_id="run_budget", budget_usd=0.001
        )
    assert ei.value.budget_usd == 0.001 and ei.value.estimate["total_usd"] > 0.001
    assert "exceeds" in str(ei.value)
    assert not (store.run_dir("run_budget") / "run.json").exists()


def _one_dollar_agent(agent_kind, model_id, task, site_url, *, run_id, site_id, site_version, screenshot_dir=None):
    return Episode(
        run_id=run_id,
        site_id=site_id,
        site_version=site_version,
        task_id=task.id,
        agent_kind=agent_kind,
        model_id=model_id,
        final_answer="1",
        cost_usd=1.0,
        finished_at=time.time(),
    )


def test_local_run_stops_submitting_once_spend_passes_budget(tmp_store, monkeypatch):
    monkeypatch.setattr(app.agents, "run_agent", _one_dollar_agent)
    run = run_swarm(
        "demo",
        "v0",
        TASKS,
        ["mock"],
        ["text", "dom"],
        site_url="u",
        local=True,
        concurrency=1,
        run_id="run_stop",
        budget_usd=2.5,
    )  # estimate is $0 (mock), so it launches
    eps = store.load_episodes("run_stop")
    ran = [e for e in eps if e.error is None]
    stopped = [e for e in eps if e.error and "budget exhausted" in e.error]
    assert len(eps) == 8 and len(ran) == 3 and len(stopped) == 5  # $1, $2, $3 > $2.5 -> stop
    assert all(e.success and e.cost_usd == 1.0 for e in ran)
    assert all(e.success is False and e.failure_mode == "error" and e.cost_usd == 0.0 for e in stopped)
    assert run.overall.episodes == 8 and run.overall.total_cost_usd == pytest.approx(3.0)
    assert run.overall.failure_modes == {"error": 5}


def test_no_budget_runs_everything(tmp_store, monkeypatch):
    monkeypatch.setattr(app.agents, "run_agent", _one_dollar_agent)
    run = run_swarm("demo", "v0", TASKS, ["mock"], ["text"], site_url="u", local=True, concurrency=2, run_id="run_all")
    assert run.overall.episodes == 4 and run.overall.total_cost_usd == pytest.approx(4.0)
    assert run.overall.failure_modes == {}
