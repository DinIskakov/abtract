import json

import pytest

from app.telemetry import parse_telemetry


def stream(*events):
    return "\n".join(json.dumps(event) for event in events)


def test_codex_usage_tools_and_cost_do_not_double_count():
    tool = {"id": "cmd-1", "type": "command_execution"}
    telemetry = parse_telemetry(
        "codex",
        stream(
            {"type": "item.started", "item": tool},
            {"type": "item.completed", "item": {**tool, "exit_code": 1}},
            {"type": "item.completed", "item": {**tool, "exit_code": 1}},
            {
                "type": "turn.completed",
                "usage": {
                    "input_tokens": 10000,
                    "cached_input_tokens": 4000,
                    "cache_write_input_tokens": 0,
                    "output_tokens": 2000,
                    "reasoning_output_tokens": 1000,
                },
            },
        ),
        "gpt-5.4-mini",
    )
    assert telemetry.trace_complete
    assert telemetry.tool_calls == telemetry.failed_tool_calls == 1
    assert telemetry.tool_calls_by_type == {"command_execution": 1}
    assert telemetry.estimated_cost_usd == pytest.approx(0.0138)
    assert telemetry.cost_scope == "model_tokens_only"
    assert telemetry.cost_model_source == "requested"
    assert telemetry.models_reported == []  # Requested is not observed.
    assert telemetry.tokens.reasoning_output_tokens == 1000  # Not added to output.


def test_codex_aggregates_turns_and_unknown_model_has_no_price():
    usage = {"input_tokens": 100, "cached_input_tokens": 10, "output_tokens": 5}
    result = parse_telemetry(
        "codex",
        stream(
            {"type": "turn.completed", "usage": usage},
            {"type": "turn.completed", "usage": usage},
        ),
        "unknown-model",
    )
    assert result.tokens.input_tokens == 200
    assert result.tokens.output_tokens == 10
    assert result.tokens.reasoning_output_tokens is None
    assert result.estimated_cost_usd is None


def test_claude_final_usage_overrides_intermediate_messages_and_tracks_models():
    result = parse_telemetry(
        "claude",
        stream(
            {"type": "system", "subtype": "init", "model": "claude-primary"},
            {
                "type": "assistant",
                "message": {
                    "model": "claude-primary",
                    "usage": {
                        "input_tokens": 99999,
                    },
                    "content": [{"type": "tool_use", "id": "t1", "name": "Bash"}],
                },
            },
            {
                "type": "user",
                "message": {
                    "content": [
                        {"type": "tool_result", "tool_use_id": "t1", "is_error": True},
                    ]
                },
            },
            {
                "type": "result",
                "total_cost_usd": 0.12,
                "usage": {
                    "input_tokens": 100,
                    "cache_read_input_tokens": 200,
                    "cache_creation_input_tokens": 50,
                    "output_tokens": 25,
                },
                "modelUsage": {
                    "claude-primary": {
                        "inputTokens": 60,
                        "cacheReadInputTokens": 200,
                        "cacheCreationInputTokens": 50,
                        "outputTokens": 20,
                        "costUSD": 0.1,
                    },
                    "claude-helper": {
                        "inputTokens": 40,
                        "cacheReadInputTokens": 0,
                        "cacheCreationInputTokens": 0,
                        "outputTokens": 5,
                        "costUSD": 0.02,
                    },
                },
            },
        ),
        "requested-alias",
    )
    assert result.tokens.input_tokens == 350
    assert result.tokens.output_tokens == 25
    assert result.models_reported == ["claude-helper", "claude-primary"]
    assert result.per_model["claude-helper"].tokens.input_tokens == 40
    assert result.estimated_cost_usd == 0.12
    assert result.cost_source == "harness_estimate"
    assert result.tool_calls == result.failed_tool_calls == 1


@pytest.mark.parametrize("harness", ["codex", "claude"])
def test_missing_or_malformed_data_remains_unknown(harness):
    result = parse_telemetry(harness, 'noise\n[]\n42\n{"answer":"done"}\n{', None)
    assert result.tokens.input_tokens is None
    assert result.estimated_cost_usd is None
    assert result.tool_calls is None
    assert not result.trace_complete


def test_partial_trace_retains_tools_without_inventing_usage():
    result = parse_telemetry(
        "codex",
        stream(
            {"type": "item.started", "item": {"id": "w1", "type": "web_search"}},
            {"type": "turn.failed", "error": {"message": "provider error"}},
        ),
        "gpt-5.4-mini",
    )
    assert result.tool_calls == 1
    assert not result.trace_complete
    assert result.estimated_cost_usd is None


def test_claude_pty_ansi_and_invalid_cost():
    result = parse_telemetry(
        "claude",
        "\x1b[32m"
        + stream(
            {
                "type": "result",
                "total_cost_usd": float("nan"),
                "usage": {
                    "input_tokens": -1,
                    "output_tokens": "12",
                },
            },
        )
        + "\x1b[0m",
        None,
    )
    assert result.trace_complete
    assert result.estimated_cost_usd is None
    assert result.tokens.input_tokens is result.tokens.output_tokens is None


def test_codex_mixed_reported_models_does_not_apply_single_price():
    result = parse_telemetry(
        "codex",
        stream(
            {"type": "thread.started", "model": "gpt-5.4-mini"},
            {
                "type": "turn.completed",
                "model": "another-model",
                "usage": {
                    "input_tokens": 100,
                    "cached_input_tokens": 0,
                    "output_tokens": 5,
                },
            },
        ),
        "gpt-5.4-mini",
    )
    assert result.estimated_cost_usd is None
    assert result.models_reported == ["another-model", "gpt-5.4-mini"]
