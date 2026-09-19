"""Opt-in integration test: creates paid Modal and model API workloads."""

import os

import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.mark.skipif(os.getenv("UPTRACK_LIVE") != "1", reason="Set UPTRACK_LIVE=1")
def test_real_question_in_modal():
    harness = os.getenv("UPTRACK_HARNESS", "codex")
    response = TestClient(app).post(
        "/api/runs",
        json={
            "url": "https://modal.com/docs/guide/sandboxes",
            "tasks": [
                "How do I create a Modal sandbox? Include a Python code example."
            ],
            "harnesses": [{"name": harness, "model": os.getenv("UPTRACK_MODEL")}],
            "timeout_seconds": 300,
        },
    )
    assert response.status_code == 200, response.text
    result = response.json()[0]
    assert result["status"] == "completed", response.text
    assert result["sandbox_id"]
    assert result["exit_code"] == 0
    assert result["cleanup_error"] is None
    assert result["report"]["answer"].strip()
    assert result["execution_duration_seconds"] > 0
    assert result["telemetry"]["trace_complete"]
    assert result["telemetry"]["tokens"]["input_tokens"] > 0
