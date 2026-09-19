"""Bounded observations of exposed tool events and explicitly proxied HTTP."""

import json
import re
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from pydantic import BaseModel, Field

from app.variants import PatchOutcome

MAX_BODY = 32_768
MAX_EVENTS = 200
SENSITIVE = re.compile(r"authorization|cookie|password|secret|token|api.?key", re.I)
ANSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


def safe_url(url: str) -> str:
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return "[INVALID_URL]"
    host = parts.hostname or ""
    if ":" in host:
        host = f"[{host}]"
    if port:
        host += f":{port}"
    query = [
        (key, "[REDACTED]" if SENSITIVE.search(key) else value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
    ]
    return urlunsplit((parts.scheme, host, parts.path, urlencode(query), ""))


def redact(value: Any, secrets: list[str]) -> Any:
    if isinstance(value, dict):
        return {
            key: "[REDACTED]" if SENSITIVE.search(key) else redact(item, secrets)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item, secrets) for item in value]
    if isinstance(value, str):
        for secret in secrets:
            if secret:
                value = value.replace(secret, "[REDACTED]")
        value = re.sub(r"https?://[^\s\"<>]+", lambda match: safe_url(match[0]), value)
    return value


class HTTPObservation(BaseModel):
    url: str
    method: str
    started_at: float
    duration_ms: float
    status_code: int | None = None
    content_type: str | None = None
    original_sha256: str | None = None
    modified_sha256: str | None = None
    original_body: str | None = None
    response_body: str | None = None
    body_truncated: bool = False
    # Hashes cover full decoded HTTP entity bytes, before redaction/truncation.
    hash_scope: str = "decoded_entity_bytes"
    patch: PatchOutcome | None = None
    error: str | None = None


class Observations(BaseModel):
    schema_version: str = "1"
    capture_http: bool = False
    coverage: str = (
        "Only target-origin GET requests honoring the sandbox HTTP proxy are "
        "captured. Provider-hosted search, bypassed traffic, hidden reasoning, "
        "and whether delivered content was used are not observable."
    )
    http: list[HTTPObservation] = Field(default_factory=list)
    native_tool_events: list[dict[str, Any]] = Field(default_factory=list)
    tool_events_truncated: bool = False
    http_events_truncated: bool = False
    capture_error: str | None = None
    applied_patch_ids: list[str] = Field(default_factory=list)
    unobserved_patch_ids: list[str] = Field(default_factory=list)


def tool_events(stdout: str, secrets: list[str]) -> tuple[list[dict[str, Any]], bool]:
    events: list[dict[str, Any]] = []
    truncated = False
    for line_number, line in enumerate(ANSI.sub("", stdout).splitlines(), 1):
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if not isinstance(event, dict) or not isinstance(event.get("type"), str):
            continue
        item = event.get("item", {})
        blocks = (
            event.get("message", {}).get("content", [])
            if isinstance(event.get("message"), dict)
            else []
        )
        if (
            isinstance(item, dict)
            and isinstance(item.get("type"), str)
            and item.get("type")
            in {
                "command_execution",
                "web_search",
                "mcp_tool_call",
                "file_change",
            }
            or event.get("type") in {"tool_use", "tool_result"}
        ):
            payload = event
        elif isinstance(blocks, list):
            selected = [
                block
                for block in blocks
                if isinstance(block, dict)
                and isinstance(block.get("type"), str)
                and block.get("type") in {"tool_use", "tool_result"}
            ]
            if not selected:
                continue
            payload = {"type": event.get("type"), "content": selected}
        else:
            continue
        if len(events) >= MAX_EVENTS:
            truncated = True
            break
        payload = redact(payload, secrets)
        encoded = json.dumps(payload)
        if len(encoded) > MAX_BODY:
            payload = {"preview": encoded[:MAX_BODY], "truncated": True}
            truncated = True
        events.append({"trace_line": line_number, "event": payload})
    return events, truncated
