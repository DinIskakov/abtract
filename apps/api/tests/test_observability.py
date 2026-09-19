import json

from app.observability import MAX_EVENTS, redact, safe_url, tool_events


def test_url_and_nested_credential_redaction():
    url = "https://user:password@example.com/docs?token=secret&page=one#private"
    assert safe_url(url) == "https://example.com/docs?token=%5BREDACTED%5D&page=one"
    payload = redact(
        {
            "Authorization": "Bearer sensitive",
            "args": {"api_key": "sensitive", "url": url, "output": "known-key"},
        },
        ["known-key"],
    )
    assert "sensitive" not in json.dumps(payload)
    assert "secret" not in json.dumps(payload)
    assert payload["args"]["output"] == "[REDACTED]"


def test_native_tools_preserve_exposed_arguments_results_and_order():
    events = [
        {
            "type": "item.completed",
            "item": {
                "id": "c1",
                "type": "command_execution",
                "command": "curl https://example.com",
                "aggregated_output": "page",
            },
        },
        {
            "type": "assistant",
            "message": {
                "content": [
                    {"type": "thinking", "thinking": "do not retain"},
                    {
                        "type": "tool_use",
                        "id": "a1",
                        "name": "Read",
                        "input": {"file": "docs.txt"},
                    },
                ]
            },
        },
        {
            "type": "tool_use",
            "tool_id": "g1",
            "tool_name": "web_fetch",
            "parameters": {"url": "https://example.com"},
        },
        {"type": "tool_result", "tool_id": "g1", "status": "success", "output": "page"},
    ]
    observed, truncated = tool_events(
        "noise\n" + "\n".join(map(json.dumps, events)), []
    )
    assert len(observed) == 4
    assert not truncated
    assert observed[0]["trace_line"] == 2
    assert observed[2]["event"]["parameters"]["url"] == "https://example.com"
    assert "do not retain" not in json.dumps(observed)


def test_tool_event_limit_is_explicit():
    event = json.dumps({"type": "tool_use", "parameters": {"secret": "hidden"}})
    observed, truncated = tool_events("\n".join([event] * (MAX_EVENTS + 1)), [])
    assert len(observed) == MAX_EVENTS
    assert truncated
    assert "hidden" not in json.dumps(observed)


def test_malformed_events_do_not_break_result_collection():
    events, truncated = tool_events(
        '{"type": []}\n{"type": "item.completed", "item": {"type": {}}}', []
    )
    assert events == []
    assert not truncated


def test_malformed_url_in_tool_output_does_not_break_collection():
    event = {"type": "tool_result", "output": "Fetched https://example.com:invalid/"}
    events, _ = tool_events(json.dumps(event), [])
    assert events[0]["event"]["output"] == "Fetched [INVALID_URL]"
