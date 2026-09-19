import json

from app.gemini_harness import GEMINI_PACKAGE, GEMINI_VERSION, gemini_command
from app.gemini_telemetry import parse_gemini_telemetry


def stream(*events):
    return "\n".join(json.dumps(event) for event in events)


def test_native_command_preserves_prompt_as_one_argument():
    prompt = "Answer literally: $(echo unsafe); `echo unsafe`"
    command = gemini_command("gemini-2.5-flash", prompt)
    assert command[command.index("--prompt") + 1] == prompt
    assert command[-2:] == ["--model", "gemini-2.5-flash"]
    assert command[command.index("--output-format") + 1] == "stream-json"
    assert command[command.index("--approval-mode") + 1] == "yolo"
    assert "--skip-trust" in command
    assert "--model" not in gemini_command(None, prompt)
    assert f"@google/gemini-cli@{GEMINI_VERSION}" == GEMINI_PACKAGE


def test_native_gemini_usage_models_and_tool_failures():
    # Mirrors the pinned CLI's StreamJsonFormatter and nonInteractiveCli events.
    usage = {"input_tokens": 100, "output_tokens": 10, "cached": 40, "input": 60}
    tool = {"type": "tool_use", "tool_id": "t1", "tool_name": "web_fetch"}
    result = parse_gemini_telemetry(
        stream(
            {"type": "init", "model": "gemini-primary"},
            tool,
            tool,
            {"type": "tool_result", "tool_id": "t1", "status": "error"},
            {"type": "tool_result", "tool_id": "t1", "status": "error"},
            {
                "type": "result",
                "status": "success",
                "stats": {
                    **usage,
                    "tool_calls": 1,
                    "models": {
                        "gemini-primary": usage,
                        "gemini-helper": {
                            "input_tokens": 0,
                            "output_tokens": 0,
                            "cached": 0,
                        },
                    },
                },
            },
        )
    )
    assert result.trace_complete
    assert result.tokens.input_tokens == 100  # Cache already included.
    assert result.tokens.cached_input_tokens == 40
    assert result.tokens.output_tokens == 10
    assert result.tokens.reasoning_output_tokens is None
    assert result.tokens.cache_write_input_tokens is None
    assert result.tool_calls == result.failed_tool_calls == 1
    assert result.tool_calls_by_type == {"web_fetch": 1}
    assert result.models_reported == ["gemini-helper", "gemini-primary"]
    assert result.per_model["gemini-primary"].tokens.input_tokens == 100
    assert result.estimated_cost_usd is None


def test_partial_gemini_trace_does_not_invent_usage():
    result = parse_gemini_telemetry(
        stream(
            {"type": "tool_use", "tool_id": "t2", "tool_name": "run_shell_command"},
            {"type": "error", "severity": "error", "message": "connection lost"},
        )
    )
    assert result.tool_calls == 1
    assert not result.trace_complete
    assert result.tokens.input_tokens is None
    assert result.models_reported == []


def test_malformed_gemini_trace_is_ignored_and_invalid_usage_unknown():
    assert parse_gemini_telemetry('noise\n[]\n{\n{"answer":"done"}').tool_calls is None
    result = parse_gemini_telemetry(
        "\x1b[32m"
        + stream(
            {
                "type": "result",
                "status": "error",
                "stats": {"input_tokens": -1, "output_tokens": "2", "cached": True},
            }
        )
        + "\x1b[0m"
    )
    assert result.trace_complete  # Terminal trace, not task success.
    assert result.tokens.input_tokens is None
    assert result.tokens.output_tokens is None
    assert result.tokens.cached_input_tokens is None


def test_gemini_final_stats_are_authoritative_over_partial_tool_events():
    result = parse_gemini_telemetry(
        stream({"type": "result", "stats": {"tool_calls": 4}})
    )
    assert result.tool_calls == 4
    assert result.tool_calls_by_type == {}
