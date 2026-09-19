"""Gemini CLI 0.60 native stream-json events, without inferred pricing."""

import json
from collections import Counter
from typing import Any

from app.telemetry import ANSI, ModelUsage, Telemetry, TokenUsage, count


def gemini_tokens(stats: dict[str, Any]) -> TokenUsage:
    # `input_tokens` is total prompt usage; `input` excludes cached tokens.
    # The streaming schema does not expose thoughts/reasoning or cache writes.
    return TokenUsage(
        input_tokens=count(stats.get("input_tokens")),
        cached_input_tokens=count(stats.get("cached")),
        output_tokens=count(stats.get("output_tokens")),
    )


def parse_gemini_telemetry(stdout: str) -> Telemetry:
    result = Telemetry()
    models: set[str] = set()
    tools: dict[str, str] = {}
    failures: set[str] = set()
    recognized = False
    final_tool_count: int | None = None
    for line in ANSI.sub("", stdout).splitlines():
        try:
            event = json.loads(line)
        except (ValueError, TypeError):
            continue
        if not isinstance(event, dict):
            continue
        kind = event.get("type")
        if kind not in (
            "init",
            "message",
            "tool_use",
            "tool_result",
            "error",
            "result",
        ):
            continue
        recognized = True
        if kind == "init":
            result.trace_complete = False
            model = event.get("model")
            if isinstance(model, str):
                models.add(model)
        elif kind == "tool_use":
            tool_id, name = event.get("tool_id"), event.get("tool_name")
            if isinstance(tool_id, str) and isinstance(name, str):
                tools[tool_id] = name
        elif kind == "tool_result":
            tool_id = event.get("tool_id")
            if isinstance(tool_id, str) and event.get("status") == "error":
                failures.add(tool_id)
        elif kind == "result":
            result.trace_complete = True
            stats = event.get("stats")
            if not isinstance(stats, dict):
                continue
            result.tokens = gemini_tokens(stats)
            final_tool_count = count(stats.get("tool_calls"))
            model_stats = stats.get("models", {})
            if isinstance(model_stats, dict):
                for model, usage in model_stats.items():
                    if isinstance(usage, dict):
                        models.add(model)
                        result.per_model[model] = ModelUsage(
                            tokens=gemini_tokens(usage)
                        )
    result.models_reported = sorted(models)
    if recognized:
        result.tool_calls = (
            final_tool_count if final_tool_count is not None else len(tools)
        )
        result.tool_calls_by_type = dict(Counter(tools.values()))
        result.failed_tool_calls = len(failures)
    return result
