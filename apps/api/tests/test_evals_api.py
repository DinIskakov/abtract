"""Tests for Abtract Evals and Regeneration Report FastAPI Endpoints."""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_root_endpoint_includes_evals_sample() -> None:
    response = client.get("/")
    assert response.status_code == 200
    data = response.json()
    assert data["message"] == "Welcome to Abtract API"
    assert data["evals_sample"] == "/api/evals/sample-report"


def test_get_sample_report_endpoint() -> None:
    response = client.get("/api/evals/sample-report?include_benchmark=true")
    assert response.status_code == 200
    report = response.json()

    assert report["app_name"] == "ShopAgent Checkout"
    assert report["variant_evaluated"] == "A"
    assert "agent_readiness_score" in report
    assert "a2a_metrics" in report
    assert "friction_hotspots" in report
    assert "transformation_directives" in report
    assert "markdown_content" in report
    assert len(report["friction_hotspots"]) > 0
    assert len(report["transformation_directives"]) > 0

    # Verify A/B benchmark is included in sample
    assert report["benchmark_comparison"] is not None
    assert report["benchmark_comparison"]["step_efficiency_ratio"] > 0


def test_post_evaluate_endpoint() -> None:
    # Use sample endpoint data to test evaluation
    sample_res = client.get("/api/evals/sample-report")
    assert sample_res.status_code == 200

    # Build a minimal episode payload
    payload = [
        {
            "episode_id": "ep_test_01",
            "session_id": "s_01",
            "sandbox_id": "sb_01",
            "variant_id": "A",
            "app_version_hash": "v1",
            "task": {
                "task_id": "t1",
                "name": "Quick Test",
                "instruction": "Test",
                "start_url": "https://example.com",
            },
            "agent_model": "gemini-2.5-flash",
            "terminal_status": "success",
            "goal_completion_score": 1.0,
            "total_steps": 2,
            "total_wall_clock_ms": 1200.0,
            "total_cost_usd": 0.002,
            "total_friction_events": 0,
            "steps": [],
        }
    ]

    response = client.post("/api/evals/evaluate", json=payload)
    assert response.status_code == 200
    metrics = response.json()
    assert metrics["variant_id"] == "A"
    assert metrics["total_episodes"] == 1
    assert metrics["task_completion_rate"] == 1.0
    assert "agent_readiness_score" in metrics


def test_post_benchmark_endpoint() -> None:
    payload = {
        "suite_id": "suite_api_test",
        "app_name": "API Test App",
        "baseline_variant": "A",
        "candidate_variant": "B",
        "episodes": [
            {
                "episode_id": "ep_a",
                "session_id": "s_a",
                "sandbox_id": "sb_a",
                "variant_id": "A",
                "app_version_hash": "v1",
                "task": {
                    "task_id": "t1",
                    "name": "T1",
                    "instruction": "I1",
                    "start_url": "https://example.com",
                },
                "agent_model": "gemini-2.5-flash",
                "terminal_status": "failed_max_steps_exceeded",
                "goal_completion_score": 0.2,
                "total_steps": 10,
                "total_wall_clock_ms": 15000.0,
                "total_cost_usd": 0.05,
                "total_friction_events": 3,
                "steps": [],
            },
            {
                "episode_id": "ep_b",
                "session_id": "s_b",
                "sandbox_id": "sb_b",
                "variant_id": "B",
                "app_version_hash": "v2",
                "task": {
                    "task_id": "t1",
                    "name": "T1",
                    "instruction": "I1",
                    "start_url": "https://example.com",
                },
                "agent_model": "gemini-2.5-flash",
                "terminal_status": "success",
                "goal_completion_score": 1.0,
                "total_steps": 3,
                "total_wall_clock_ms": 3000.0,
                "total_cost_usd": 0.01,
                "total_friction_events": 0,
                "steps": [],
            },
        ],
    }

    response = client.post("/api/evals/benchmark", json=payload)
    assert response.status_code == 200
    bench = response.json()
    assert bench["baseline"]["variant_id"] == "A"
    assert bench["candidate"]["variant_id"] == "B"
    assert bench["delta_tcr"] == 1.0
    assert bench["cost_reduction_pct"] > 0
