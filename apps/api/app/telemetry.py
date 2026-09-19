"""Normalize native CLI events; never use agent-authored claims as telemetry."""

import json
import math
import re
from collections import Counter
from typing import Any, Literal

from pydantic import BaseModel, Field


class TokenUsage(BaseModel):
    # Total input includes cache reads/writes. Output semantics are harness-specific:
    # Codex includes reasoning; Gemini CLI exposes candidate output only.
    input_tokens: int | None = None
    cached_input_tokens: int | None = None
    cache_write_input_tokens: int | None = None
    output_tokens: int | None = None
    reasoning_output_tokens: int | None = None


class ModelUsage(BaseModel):
    tokens: TokenUsage
    estimated_cost_usd: float | None = None


class Telemetry(BaseModel):
    trace_complete: bool = False
    tokens: TokenUsage = Field(default_factory=TokenUsage)
    models_reported: list[str] = Field(default_factory=list)
    per_model: dict[str, ModelUsage] = Field(default_factory=dict)
    tool_calls: int | None = None
    tool_calls_by_type: dict[str, int] = Field(default_factory=dict)
    failed_tool_calls: int | None = None
    estimated_cost_usd: float | None = None
    cost_source: Literal["token_price_estimate", "harness_estimate"] | None = None
    cost_scope: Literal["model_tokens_only", "harness_reported"] | None = None
    cost_model_source: Literal["requested", "reported"] | None = None
    pricing_reference: str | None = None
    pricing_as_of: str | None = None
    sandbox_cost_usd: float | None = None


# Standard per-million token prices. Refresh explicitly, not during a benchmark.
# https://developers.openai.com/api/docs/models/gpt-5.4-mini
# https://developers.openai.com/api/docs/models/gpt-5.4
PRICES = {"gpt-5.4-mini": (0.75, 0.075, 4.5), "gpt-5.4": (2.5, 0.25, 15.0)}
PRICING_AS_OF = "2026-09-19"
ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def count(value: Any) -> int | None:
    return value if type(value) is int and value >= 0 else None


def money(value: Any) -> float | None:
    if type(value) in (int, float) and math.isfinite(value) and value >= 0:
        return float(value)
    return None


def total(values: list[int | None]) -> int | None:
    return (
        sum(v for v in values if v is not None)
        if values and None not in values
        else None
    )


def claude_tokens(usage: dict[str, Any], *, camel: bool = False) -> TokenUsage:
    names = (
        (
            "inputTokens",
            "cacheReadInputTokens",
            "cacheCreationInputTokens",
            "outputTokens",
        )
        if camel
        else (
            "input_tokens",
            "cache_read_input_tokens",
            "cache_creation_input_tokens",
            "output_tokens",
        )
    )
    uncached, cached, written, output = (count(usage.get(key)) for key in names)
    return TokenUsage(
        input_tokens=total([uncached, cached, written]),
        cached_input_tokens=cached,
        cache_write_input_tokens=written,
        output_tokens=output,
    )


def parse_telemetry(
    harness: str,
    stdout: str,
    requested_model: str | None,
) -> Telemetry:
    if harness == "gemini":
        from app.gemini_telemetry import parse_gemini_telemetry

        return parse_gemini_telemetry(stdout)
    result = Telemetry()
    events: list[dict[str, Any]] = []
    for line in ANSI.sub("", stdout).splitlines():
        try:
            value = json.loads(line)
        except (ValueError, TypeError):
            continue
        if isinstance(value, dict) and isinstance(value.get("type"), str):
            events.append(value)
    if not events:
        return result

    models: set[str] = set()
    tools: dict[str, str] = {}
    failures: set[str] = set()
    usages: list[dict[str, Any]] = []
    recognized = False
    for event in events:
        kind = event["type"]
        if harness == "codex":
            recognized |= kind.startswith(("thread.", "turn.", "item."))
            if kind == "turn.completed" and isinstance(event.get("usage"), dict):
                usages.append(event["usage"])
                result.trace_complete = True
            elif kind in ("turn.started", "turn.failed", "error"):
                result.trace_complete = False
            item = event.get("item")
            if kind in ("item.started", "item.completed") and isinstance(item, dict):
                tool_type, tool_id = item.get("type"), item.get("id")
                if tool_type in (
                    "command_execution",
                    "web_search",
                    "mcp_tool_call",
                    "file_change",
                ) and isinstance(tool_id, str):
                    tools[tool_id] = tool_type
                    exit_code = item.get("exit_code")
                    if item.get("status") == "failed" or (
                        type(exit_code) is int and exit_code != 0
                    ):
                        failures.add(tool_id)
            model = event.get("model")
            if isinstance(model, str):
                models.add(model)
        else:
            recognized |= kind in ("system", "assistant", "user", "result")
            message = event.get("message", {})
            if not isinstance(message, dict):
                message = {}
            model = message.get("model") if kind == "assistant" else event.get("model")
            if isinstance(model, str):
                models.add(model)
            content = message.get("content", [])
            if isinstance(content, list):
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    if (
                        kind == "assistant"
                        and block.get("type") == "tool_use"
                        and isinstance(block.get("id"), str)
                    ):
                        tools[block["id"]] = str(block.get("name", "unknown"))
                    if (
                        kind == "user"
                        and block.get("type") == "tool_result"
                        and block.get("is_error") is True
                        and isinstance(block.get("tool_use_id"), str)
                    ):
                        failures.add(block["tool_use_id"])
            if kind == "result":
                result.trace_complete = True
                if isinstance(event.get("usage"), dict):
                    result.tokens = claude_tokens(event["usage"])
                cost = money(event.get("total_cost_usd"))
                if cost is not None:
                    result.estimated_cost_usd = cost
                    result.cost_source = "harness_estimate"
                    result.cost_scope = "harness_reported"
                    result.cost_model_source = "reported"
                model_usage = event.get("modelUsage", {})
                if isinstance(model_usage, dict):
                    for name, usage in model_usage.items():
                        if isinstance(usage, dict):
                            models.add(name)
                            result.per_model[name] = ModelUsage(
                                tokens=claude_tokens(usage, camel=True),
                                estimated_cost_usd=money(usage.get("costUSD")),
                            )

    result.models_reported = sorted(models)
    if recognized:
        result.tool_calls = len(tools)
        result.tool_calls_by_type = dict(Counter(tools.values()))
        result.failed_tool_calls = len(failures)
    if harness == "codex" and usages:
        result.tokens = TokenUsage(
            **{
                name: total([count(usage.get(name)) for usage in usages])
                for name in TokenUsage.model_fields
            }
        )
        # Only estimate a known, single model. Never infer a price for an alias.
        model = next(iter(models)) if len(models) == 1 else requested_model
        tokens = result.tokens
        if (
            len(models) <= 1
            and model in PRICES
            and tokens.input_tokens is not None
            and tokens.cached_input_tokens is not None
            and tokens.output_tokens is not None
            and tokens.cached_input_tokens <= tokens.input_tokens
        ):
            assert model is not None
            input_price, cached_price, output_price = PRICES[model]
            result.estimated_cost_usd = round(
                (
                    (tokens.input_tokens - tokens.cached_input_tokens) * input_price
                    + tokens.cached_input_tokens * cached_price
                    + tokens.output_tokens * output_price
                )
                / 1_000_000,
                8,
            )
            result.cost_source = "token_price_estimate"
            result.cost_scope = "model_tokens_only"
            result.cost_model_source = "reported" if models else "requested"
            result.pricing_reference = (
                f"https://developers.openai.com/api/docs/models/{model}"
            )
            result.pricing_as_of = PRICING_AS_OF
    return result
