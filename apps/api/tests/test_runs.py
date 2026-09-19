import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app import runs
from app.main import app

REPORT = {
    "answer": "Use modal.Sandbox.create().\n```python\nimport modal\n```",
    "actions": ["Read the documentation"],
    "sources": ["https://modal.com/docs/guide/sandboxes"],
    "limitations": [],
}
BODY = {
    "url": "https://modal.com",
    "tasks": ["How do I create a sandbox?"],
    "harnesses": [{"name": "codex"}],
}


@pytest.fixture
def backend(monkeypatch):
    monkeypatch.setattr(runs.settings, "openai_api_key", SecretStr("test-key"))
    monkeypatch.setattr(runs.settings, "anthropic_api_key", SecretStr("test-other"))
    monkeypatch.setattr(runs.modal.App.lookup, "aio", AsyncMock())
    monkeypatch.setattr(runs, "image_for", MagicMock())
    sandboxes = []

    async def create(**kwargs):
        sandbox = MagicMock()
        sandbox.object_id = f"sb-{len(sandboxes)}"
        process = MagicMock()
        process.stdout.read.aio = AsyncMock(return_value='{"event":"test"}')
        process.stderr.read.aio = AsyncMock(return_value="")
        process.wait.aio = AsyncMock(return_value=0)
        process.stdin.drain.aio = AsyncMock()
        sandbox.exec.aio = AsyncMock(return_value=process)
        sandbox.filesystem.stat.aio = AsyncMock()
        sandbox.filesystem.stat.aio.return_value.size = len(json.dumps(REPORT))
        sandbox.filesystem.read_text.aio = AsyncMock(return_value=json.dumps(REPORT))
        sandbox.terminate.aio = AsyncMock()
        sandboxes.append(sandbox)
        return sandbox

    factory = AsyncMock(side_effect=create)
    monkeypatch.setattr(runs.modal.Sandbox.create, "aio", factory)
    return factory, sandboxes


def test_endpoint_expands_matrix_into_fresh_sandboxes(backend):
    factory, sandboxes = backend
    response = TestClient(app).post(
        "/api/runs",
        json={
            **BODY,
            "tasks": ["Question one", "Question two"],
            "harnesses": [{"name": "codex"}, {"name": "claude"}],
            "repetitions": 2,
        },
    )
    assert response.status_code == 200
    results = response.json()
    assert len(results) == factory.call_count == 8
    assert len({r["sandbox_id"] for r in results}) == 8
    assert all(r["status"] == "completed" and r["report"] == REPORT for r in results)
    assert {r["repetition"] for r in results} == {1, 2}
    for sandbox in sandboxes:
        sandbox.terminate.aio.assert_awaited_once()
        if not sandbox.exec.aio.call_args.kwargs["pty"]:
            sandbox.exec.aio.return_value.stdin.write_eof.assert_called_once()
            sandbox.exec.aio.return_value.stdin.drain.aio.assert_awaited_once()


@pytest.mark.parametrize("failure", ["missing", "malformed", "exit", "timeout"])
def test_failure_returns_error_and_cleans_up(backend, failure):
    factory, sandboxes = backend
    original = factory.side_effect

    async def create(**kwargs):
        sandbox = await original(**kwargs)
        if failure == "missing":
            sandbox.filesystem.stat.aio.side_effect = FileNotFoundError("result.json")
        elif failure == "malformed":
            sandbox.filesystem.read_text.aio.return_value = '{"answer": 42}'
        elif failure == "exit":
            sandbox.exec.aio.return_value.wait.aio.return_value = 1
        else:
            sandbox.exec.aio.side_effect = TimeoutError("time budget exceeded")
        return sandbox

    factory.side_effect = create
    result = TestClient(app).post("/api/runs", json=BODY).json()[0]
    assert result["status"] == "error"
    assert result["error"]
    assert result["report"] is None
    sandboxes[0].terminate.aio.assert_awaited_once()


def test_missing_credentials_fails_before_creating_sandbox(backend, monkeypatch):
    monkeypatch.setattr(runs.settings, "openai_api_key", None)
    response = TestClient(app).post("/api/runs", json=BODY)
    assert response.status_code == 503
    backend[0].assert_not_called()


@pytest.mark.parametrize(
    "changes",
    [
        {"url": "file:///etc/passwd"},
        {"tasks": [" "]},
        {"repetitions": 0},
        {"harnesses": [{"name": "unknown"}]},
        {"tasks": ["q"] * 10, "repetitions": 5},
    ],
)
def test_invalid_requests_do_not_launch(backend, changes):
    assert (
        TestClient(app).post("/api/runs", json={**BODY, **changes}).status_code == 422
    )
    backend[0].assert_not_called()


def test_native_commands_pass_model_and_prompt_without_shell():
    prompt = "Question with $(shell syntax)"
    for name in ("codex", "claude"):
        args = runs.command(runs.HarnessConfig(name=name, model="test-model"), prompt)
        assert args[0] == name
        assert args[-3:] == ["--model", "test-model", prompt]


def test_cleanup_failure_preserves_report_and_redacts_key(backend):
    factory, _ = backend
    original = factory.side_effect

    async def create(**kwargs):
        sandbox = await original(**kwargs)
        sandbox.terminate.aio.side_effect = RuntimeError("cleanup failed")
        sandbox.exec.aio.return_value.stdout.read.aio.return_value = "test-key"
        return sandbox

    factory.side_effect = create
    result = TestClient(app).post("/api/runs", json=BODY).json()[0]
    assert result["status"] == "completed"
    assert result["cleanup_error"]
    assert result["stdout"] == "[REDACTED]"


def test_endpoint_returns_native_telemetry_even_when_report_is_missing(backend):
    factory, _ = backend
    original = factory.side_effect

    async def create(**kwargs):
        sandbox = await original(**kwargs)
        sandbox.exec.aio.return_value.stdout.read.aio.return_value = json.dumps(
            {
                "type": "turn.completed",
                "usage": {
                    "input_tokens": 100,
                    "cached_input_tokens": 10,
                    "output_tokens": 5,
                },
            }
        )
        sandbox.filesystem.stat.aio.side_effect = FileNotFoundError("result.json")
        return sandbox

    factory.side_effect = create
    result = (
        TestClient(app)
        .post(
            "/api/runs",
            json={
                **BODY,
                "harnesses": [{"name": "codex", "model": "gpt-5.4-mini"}],
            },
        )
        .json()[0]
    )
    assert result["status"] == "error"
    assert result["telemetry"]["tokens"]["input_tokens"] == 100
    assert result["telemetry"]["estimated_cost_usd"] > 0
    assert result["execution_duration_seconds"] is not None


def test_runs_overlap_and_respect_concurrency_limit(backend):
    factory, _ = backend
    original = factory.side_effect
    active = 0
    peak = 0
    gate = asyncio.Event()

    async def create(**kwargs):
        nonlocal active, peak
        sandbox = await original(**kwargs)

        async def wait():
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            if active == 2:
                gate.set()
            try:
                # A sequential implementation cannot pass this rendezvous.
                await asyncio.wait_for(gate.wait(), timeout=2)
                await asyncio.sleep(0.01)
                return 0
            finally:
                active -= 1

        sandbox.exec.aio.return_value.wait.aio.side_effect = wait
        return sandbox

    factory.side_effect = create
    response = TestClient(app).post(
        "/api/runs",
        json={
            **BODY,
            "tasks": [f"Question {i}" for i in range(5)],
            "max_concurrency": 2,
        },
    )
    assert response.status_code == 200
    assert all(r["status"] == "completed" for r in response.json())
    assert peak == 2
    assert active == 0


def test_failed_run_does_not_cancel_other_runs(backend):
    factory, sandboxes = backend
    original = factory.side_effect

    async def create(**kwargs):
        sandbox = await original(**kwargs)
        if len(sandboxes) == 1:
            sandbox.exec.aio.return_value.wait.aio.return_value = 1
        return sandbox

    factory.side_effect = create
    results = (
        TestClient(app)
        .post(
            "/api/runs",
            json={
                **BODY,
                "tasks": ["First", "Second"],
            },
        )
        .json()
    )
    assert [r["status"] for r in results] == ["error", "completed"]
    for sandbox in sandboxes:
        sandbox.terminate.aio.assert_awaited_once()


def test_capture_survives_failed_harness_and_reports_patch_exposure(backend):
    factory, _ = backend
    original = factory.side_effect

    async def create(**kwargs):
        sandbox = await original(**kwargs)
        harness_process = sandbox.exec.aio.return_value
        harness_process.wait.aio.return_value = 1
        harness_process.stdout.read.aio.return_value = json.dumps(
            {
                "type": "item.completed",
                "item": {
                    "type": "command_execution",
                    "command": "curl https://modal.com/",
                },
            }
        )
        setup = MagicMock()
        setup.wait.aio = AsyncMock(return_value=0)
        sandbox.exec.aio.side_effect = [setup, harness_process]
        sandbox.filesystem.read_text.aio.return_value = json.dumps(
            {
                "url": "https://modal.com/",
                "method": "GET",
                "started_at": 1,
                "duration_ms": 5,
                "status_code": 200,
                "patch": {"patch_id": "example", "status": "applied"},
            }
        )
        sandbox.filesystem.stat.aio.side_effect = FileNotFoundError()
        return sandbox

    factory.side_effect = create
    result = (
        TestClient(app)
        .post(
            "/api/runs",
            json={
                **BODY,
                "capture_http": True,
                "variant_id": "B",
                "patches": [
                    {
                        "patch_id": "example",
                        "url": "https://modal.com/",
                        "expected_sha256": "a" * 64,
                        "old_text": "old",
                        "new_text": "new",
                    }
                ],
            },
        )
        .json()[0]
    )
    assert result["status"] == "error"
    assert result["observations"]["applied_patch_ids"] == ["example"]
    assert result["observations"]["unobserved_patch_ids"] == []
    assert result["observations"]["capture_error"] is None
    assert len(result["observations"]["native_tool_events"]) == 1
    assert result["variant_id"] == "B"


def test_failed_wait_preserves_available_native_trace(backend):
    factory, _ = backend
    original = factory.side_effect

    async def create(**kwargs):
        sandbox = await original(**kwargs)
        sandbox.exec.aio.return_value.wait.aio.side_effect = TimeoutError("expired")
        sandbox.exec.aio.return_value.stdout.read.aio.return_value = "partial trace"
        return sandbox

    factory.side_effect = create
    result = TestClient(app).post("/api/runs", json=BODY).json()[0]
    assert result["status"] == "error"
    assert result["stdout"] == "partial trace"
