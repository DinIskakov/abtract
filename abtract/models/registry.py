"""The collection of agent brains we can swarm with.

The Modal entries are generated from the verified price table in `pricing.py` (one row per model with a Shared
Endpoint price on modal.com/library). Adding a model = adding a row there. `gemini-flash` and `mock` are hand-written.

Modal hosted inference is OpenAI-compatible. Each spec's `model` defaults to the library ID;
`llm.resolve_modal_model` matches it against what GET /v1/models lists for your
proxy token (library ID or endpoint hostname) at first use. Set ABTRACT_MODEL_<ID> (id upper-cased, non-alphanumerics
-> "_", e.g. ABTRACT_MODEL_DEEPSEEK_V4_1_FLASH) to force a name; `scripts/list_models.py` shows both.

Selectors (`select_models`, used by `--models`): comma-separated ids and/or
    cheapest:N   the N cheapest Modal models by cost_rank (0.8*input + 0.2*output price: agent traffic is input-heavy)
    vision       every Modal model that accepts images, cheapest first
    all          every Modal model, cheapest first
    default      DEFAULT_SWARM
    mock         the offline stand-in
"""
from __future__ import annotations

import os
import re

from abtract.config import settings
from abtract.models.pricing import SHARED_ENDPOINT_MODELS
from abtract.schemas import ModelSpec


def env_key(model_id: str) -> str:
    """Environment variable that overrides the `model` string sent to the gateway for this id."""
    return "ABTRACT_MODEL_" + re.sub(r"[^A-Za-z0-9]+", "_", model_id).upper()


def _spec_from_row(row: dict) -> ModelSpec:
    return ModelSpec(
        id=row["id"], provider="modal",
        model=os.environ.get(env_key(row["id"]), "").strip() or row["modal_id"],
        display_name=row["display_name"], supports_vision=bool(row["supports_vision"]),
        input_price_per_m=float(row["input_price_per_m"]), output_price_per_m=float(row["output_price_per_m"]),
    )


def build_models() -> dict[str, ModelSpec]:
    """Registry from the price table + Gemini + mock, reading ABTRACT_MODEL_<ID> overrides now."""
    models = {row["id"]: _spec_from_row(row) for row in SHARED_ENDPOINT_MODELS}
    # ---- Gemini (also usable as a swarm member, but its main job is optimizer / task generator / judge)
    models["gemini-flash"] = ModelSpec(
        id="gemini-flash", provider="gemini", model=settings.gemini_model,
        display_name=f"Gemini ({settings.gemini_model})", supports_vision=True,
        input_price_per_m=0.50, output_price_per_m=3.00, max_output_tokens=8192,
    )
    # ---- Offline stand-in so the pipeline can be exercised with no API keys
    models["mock"] = ModelSpec(
        id="mock", provider="mock", model="mock", display_name="Mock (scripted)", supports_vision=True,
    )
    return models


MODELS: dict[str, ModelSpec] = build_models()


def cost_rank(spec: ModelSpec) -> float:
    """USD per 1M tokens of typical agent traffic: 80% input (observations re-sent every step), 20% output."""
    return 0.8 * spec.input_price_per_m + 0.2 * spec.output_price_per_m


def _modal_models(*, vision_only: bool = False) -> list[ModelSpec]:
    return sorted((m for m in MODELS.values() if m.provider == "modal" and (m.supports_vision or not vision_only)),
                  key=cost_rank)


CHEAPEST_10: list[str] = [m.id for m in _modal_models()[:10]]
DEFAULT_SWARM: list[str] = [m.id for m in _modal_models()[:2]]


def get_model(model_id: str) -> ModelSpec:
    try:
        return MODELS[model_id]
    except KeyError:
        raise KeyError(f"Unknown model '{model_id}'. Known: {', '.join(MODELS)}") from None


def list_models(vision_only: bool = False) -> list[ModelSpec]:
    return [m for m in MODELS.values() if (m.supports_vision or not vision_only)]


def select_models(spec: str) -> list[ModelSpec]:
    """Parse a `--models` spec (see module docstring) into specs, in order, without duplicates.

    Raises ValueError for an empty spec, an unknown id, or a malformed selector.
    """
    tokens = [t.strip() for t in (spec or "").split(",")]
    if not any(tokens):
        raise ValueError("empty model spec (try: default, cheapest:3, vision, all, mock, or ids)")
    chosen: list[ModelSpec] = []
    for token in tokens:
        if not token:
            raise ValueError(f"empty item in model spec {spec!r}")
        key = token.lower()
        if key == "all":
            picks = _modal_models()
        elif key == "vision":
            picks = _modal_models(vision_only=True)
        elif key == "default":
            picks = [MODELS[i] for i in DEFAULT_SWARM]
        elif key == "mock":
            picks = [MODELS["mock"]]
        elif key == "cheapest" or key.startswith("cheapest:"):
            n_text = key.partition(":")[2]
            try:
                n = len(CHEAPEST_10) if not n_text else int(n_text)
            except ValueError:
                raise ValueError(f"bad selector {token!r}: expected cheapest:N with an integer N") from None
            if n < 1:
                raise ValueError(f"bad selector {token!r}: N must be >= 1")
            picks = [MODELS[i] for i in CHEAPEST_10[:n]]
        elif token in MODELS:
            picks = [MODELS[token]]
        else:
            raise ValueError(f"unknown model {token!r}; known ids: {', '.join(MODELS)}; "
                             f"selectors: cheapest:N, vision, all, default, mock")
        for m in picks:
            if m.id not in {c.id for c in chosen}:
                chosen.append(m)
    return chosen


def discover_modal_models(base_url: str | None = None) -> list[str]:
    """Ask the Modal inference gateway which model names this proxy token can call."""
    import httpx

    if not settings.modal_proxy_token:
        raise RuntimeError("MODAL_PROXY_TOKEN is not set")
    r = httpx.get(
        f"{(base_url or settings.modal_inference_base_url).rstrip('/')}/models",
        headers={"Authorization": f"Bearer {settings.modal_proxy_token}"},
        timeout=30,
    )
    r.raise_for_status()
    return [m["id"] for m in r.json().get("data", [])]
