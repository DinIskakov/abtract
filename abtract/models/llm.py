"""One chat() call for every provider. Returns text plus token usage so every agent's cost is measured the same way.

Messages are role + content, where content is a string or a list of parts:
  {"type": "text", "text": "..."}
  {"type": "image", "png_base64": "..."}          (only if the model supports_vision)
"""
from __future__ import annotations

import base64
import json
import logging
import os
import re
import threading
import time
from typing import Any

from pydantic import BaseModel

from abtract.config import settings
from abtract.schemas import ModelSpec, Usage

log = logging.getLogger("abtract.models")


class ChatMessage(BaseModel):
    role: str  # "system" | "user" | "assistant"
    content: str | list[dict[str, Any]]


class LLMResponse(BaseModel):
    text: str
    usage: Usage
    raw: dict[str, Any] = {}


class LLMError(RuntimeError):
    pass


def chat(
    spec: ModelSpec,
    messages: list[ChatMessage],
    *,
    json_mode: bool = False,
    max_output_tokens: int | None = None,
    temperature: float = 0.2,
    retries: int = 3,
    timeout_s: float | None = None,
) -> LLMResponse:
    """Blocking. Retries transient failures with backoff. Raises LLMError after `retries` attempts."""
    if any(_has_image(m) for m in messages) and not spec.supports_vision:
        raise LLMError(f"model {spec.id} does not accept images")
    max_out = max_output_tokens or spec.max_output_tokens
    last_err: Exception | None = None
    for attempt in range(retries):
        t0 = time.time()
        try:
            if spec.provider == "modal":
                resp = _chat_openai_compatible(spec, messages, json_mode, max_out, temperature, timeout_s)
            elif spec.provider == "gemini":
                resp = _chat_gemini(spec, messages, json_mode, max_out, temperature, timeout_s)
            elif spec.provider == "mock":
                resp = _chat_mock(spec, messages, json_mode)
            else:
                raise LLMError(f"unknown provider {spec.provider}")
            resp.usage.llm_calls = 1
            resp.usage.llm_latency_ms = int((time.time() - t0) * 1000)
            return resp
        except LLMError:
            raise
        except Exception as e:  # noqa: BLE001  transient: rate limit, network, 5xx
            last_err = e
            if attempt + 1 < retries:
                time.sleep(min(2**attempt, 8))
    raise LLMError(f"{spec.id}: {last_err}") from last_err


def _has_image(m: ChatMessage) -> bool:
    return isinstance(m.content, list) and any(p.get("type") == "image" for p in m.content)


# --------------------------------------------------------------------------- Modal model-name resolution
#
# The OpenAI `model` field for a Modal Shared Endpoint is whatever name the gateway lists under GET /v1/models. The
# registry stores the library ID (deepseek-ai/DeepSeek-V4.1-Flash); the gateway may list exactly that, or an endpoint
# hostname (deepseek-v4-1-flash.us-west.modal.direct). We fetch the listing once per process, match each configured
# name against it (exact -> case-insensitive -> normalized -> normalized substring) and cache the answer. When the
# listing is unavailable or nothing matches, the configured name is sent unchanged.

_MIN_SUBSTRING_LEN = 4                              # "k3" alone must not match anything
_MODAL_MODEL_NAMES: dict[str, list[str]] = {}        # endpoint URL -> listing; [] = fetch failed
_MODAL_RESOLVED: dict[tuple[str, str], str] = {}     # (endpoint URL, spec.model) -> name to send
_resolve_lock = threading.Lock()


def modal_base_url(spec: ModelSpec) -> str:
    """Per-model API base URL, including /v1, or the shared gateway fallback."""
    suffix = re.sub(r"[^A-Za-z0-9]+", "_", spec.id).upper()
    override = os.environ.get(f"ABTRACT_BASE_URL_{suffix}", "").strip()
    return (override or settings.modal_inference_base_url).rstrip("/")


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


_HOSTNAME = re.compile(r"[a-z0-9-]+(\.[a-z0-9-]+)+\.[a-z]{2,}")  # deepseek-v4-1-flash.us-west.modal.direct


def _variants(name: str) -> list[str]:
    """Strings a model may be listed under: the full name, the part after the org slash, the first hostname label."""
    out = [name]
    if "/" in name:
        out.append(name.rsplit("/", 1)[1])
    elif _HOSTNAME.fullmatch(name):
        out.append(name.split(".", 1)[0])
    return out


def match_model_name(wanted: str, available: list[str]) -> str | None:
    """Pick the listed name for `wanted`: exact -> case-insensitive -> normalized equality (org prefix / hostname
    suffix ignored) -> normalized substring either way. None when nothing fits."""
    if wanted in available:
        return wanted
    by_lower = {a.lower(): a for a in available}
    if wanted.lower() in by_lower:
        return by_lower[wanted.lower()]
    w_norms = [n for n in (_norm(v) for v in _variants(wanted)) if n]
    if not w_norms:
        return None
    for a in available:
        if any(_norm(v) in w_norms for v in _variants(a)):
            return a
    hits = []
    for a in available:
        a_norms = [n for n in (_norm(v) for v in _variants(a)) if len(n) >= _MIN_SUBSTRING_LEN]
        if any((w in an or an in w) for w in w_norms if len(w) >= _MIN_SUBSTRING_LEN for an in a_norms):
            hits.append(a)
    return min(hits, key=len) if hits else None  # several hits: the shortest listed name is the closest


def _modal_model_names(base_url: str) -> list[str]:
    with _resolve_lock:
        if base_url not in _MODAL_MODEL_NAMES:
            from abtract.models import registry  # looked up at call time so tests can monkeypatch discover_modal_models

            try:
                _MODAL_MODEL_NAMES[base_url] = list(registry.discover_modal_models(base_url=base_url))
            except Exception as e:  # noqa: BLE001  no token, network down, gateway 5xx: send configured names as-is
                log.warning("could not list Modal models (%s: %s); using configured model names unchanged",
                            type(e).__name__, e)
                _MODAL_MODEL_NAMES[base_url] = []
        return _MODAL_MODEL_NAMES[base_url]


def resolve_modal_model(spec: ModelSpec) -> str:
    """The `model` string to send to the Modal gateway for `spec`. Resolved once per process; never raises."""
    if spec.provider != "modal":
        return spec.model
    base_url = modal_base_url(spec)
    key = (base_url, spec.model)
    if key in _MODAL_RESOLVED:
        return _MODAL_RESOLVED[key]
    names = _modal_model_names(base_url)
    resolved = match_model_name(spec.model, names) or spec.model
    with _resolve_lock:
        _MODAL_RESOLVED[key] = resolved
    if resolved != spec.model:
        log.info("modal model %s: '%s' -> '%s' (matched in /v1/models)", spec.id, spec.model, resolved)
    elif names and spec.model not in names:
        log.warning("modal model %s: '%s' is not among the %d names in /v1/models; sending it unchanged "
                    "(set ABTRACT_MODEL_%s or run scripts/list_models.py)", spec.id, spec.model, len(names),
                    re.sub(r"[^A-Za-z0-9]+", "_", spec.id).upper())
    else:
        log.info("modal model %s: sending '%s'", spec.id, spec.model)
    return resolved


def reset_modal_model_cache() -> None:
    """Forget the gateway listing and every resolved name (tests, or after `modal endpoint create`)."""
    with _resolve_lock:
        _MODAL_MODEL_NAMES.clear()
        _MODAL_RESOLVED.clear()


# --------------------------------------------------------------------------- Modal (OpenAI-compatible)

def _chat_openai_compatible(spec, messages, json_mode, max_out, temperature, timeout_s=None) -> LLMResponse:
    from openai import OpenAI

    if not settings.modal_proxy_token:
        raise LLMError("MODAL_PROXY_TOKEN is not set (see .env.example)")
    # chat() owns retries. SDK retries here used to multiply one request into up
    # to nine attempts and could keep a demo worker blocked for many minutes.
    client = OpenAI(api_key=settings.modal_proxy_token, base_url=modal_base_url(spec),
                    timeout=timeout_s if timeout_s is not None else settings.step_timeout_s, max_retries=0)
    oa_messages = []
    for m in messages:
        if isinstance(m.content, str):
            oa_messages.append({"role": m.role, "content": m.content})
        else:
            parts = []
            for p in m.content:
                if p["type"] == "text":
                    parts.append({"type": "text", "text": p["text"]})
                elif p["type"] == "image":
                    parts.append({"type": "image_url", "image_url": {"url": f"data:image/png;base64,{p['png_base64']}"}})
            oa_messages.append({"role": m.role, "content": parts})
    kwargs: dict[str, Any] = dict(model=resolve_modal_model(spec), messages=oa_messages, max_tokens=max_out,
                                  temperature=temperature)
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    r = client.chat.completions.create(**kwargs)
    text = (r.choices[0].message.content or "") if r.choices else ""
    u = r.usage
    usage = Usage(input_tokens=getattr(u, "prompt_tokens", 0) or 0, output_tokens=getattr(u, "completion_tokens", 0) or 0)
    return LLMResponse(text=text, usage=usage, raw={"id": r.id, "model": r.model})


# --------------------------------------------------------------------------- Gemini

def _chat_gemini(spec, messages, json_mode, max_out, temperature, timeout_s=None) -> LLMResponse:
    from google import genai
    from google.genai import types

    if not settings.gemini_api_key:
        raise LLMError("GEMINI_API_KEY is not set (see .env.example)")
    options = {"http_options": types.HttpOptions(timeout=max(1, int(timeout_s * 1000)),
                                                retry_options=types.HttpRetryOptions(attempts=1))} if timeout_s is not None else {}
    client = genai.Client(api_key=settings.gemini_api_key, **options)
    system_parts = [m.content for m in messages if m.role == "system" and isinstance(m.content, str)]
    contents = []
    for m in messages:
        if m.role == "system":
            continue
        role = "model" if m.role == "assistant" else "user"
        if isinstance(m.content, str):
            parts = [types.Part.from_text(text=m.content)]
        else:
            parts = []
            for p in m.content:
                if p["type"] == "text":
                    parts.append(types.Part.from_text(text=p["text"]))
                elif p["type"] == "image":
                    parts.append(types.Part.from_bytes(data=base64.b64decode(p["png_base64"]), mime_type="image/png"))
        contents.append(types.Content(role=role, parts=parts))
    config = types.GenerateContentConfig(
        system_instruction="\n\n".join(system_parts) or None,
        max_output_tokens=max_out,
        temperature=temperature,
        response_mime_type="application/json" if json_mode else None,
    )
    r = client.models.generate_content(model=spec.model, contents=contents, config=config)
    um = r.usage_metadata
    usage = Usage(
        input_tokens=getattr(um, "prompt_token_count", 0) or 0,
        output_tokens=(getattr(um, "candidates_token_count", 0) or 0) + (getattr(um, "thoughts_token_count", 0) or 0),
    )
    return LLMResponse(text=r.text or "", usage=usage, raw={"model": spec.model})


# --------------------------------------------------------------------------- Mock

def _chat_mock(spec, messages, json_mode) -> LLMResponse:
    """Deterministic stand-in. Set ABTRACT_MOCK_REPLY to control the text; default is a give_up action or
    a JSON echo so agents and the optimizer can be smoke-tested offline."""
    reply = os.environ.get("ABTRACT_MOCK_REPLY")
    if reply is None:
        reply = json.dumps({"thought": "mock model", "action": {"type": "give_up", "reason": "mock"}}) if json_mode else "mock reply"
    n_in = sum(len(m.content) if isinstance(m.content, str) else 500 for m in messages) // 4
    return LLMResponse(text=reply, usage=Usage(input_tokens=n_in, output_tokens=len(reply) // 4), raw={"mock": True})


def extract_json(text: str) -> dict[str, Any]:
    """Pull the first JSON object out of a model reply that may be wrapped in prose or ```json fences."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text[3:]
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    depth = 0
    for i in range(start, len(text)):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[start : i + 1])
    raise ValueError(f"no JSON object in reply: {text[:200]!r}")
