from fastapi.testclient import TestClient

from app.artifacts import save_artifact
from app.main import app
from app.runs import AgentReport, HarnessConfig, RunResult


def test_saved_run_can_be_loaded_by_the_frontend():
    run = RunResult(
        task="A question",
        task_index=0,
        repetition=1,
        harness=HarnessConfig(name="codex"),
        harness_version="test",
    )
    save_artifact("runs", run.run_id, run)
    response = TestClient(app).get(f"/api/runs/{run.run_id}")
    assert response.status_code == 200
    assert response.json() == run.model_dump(mode="json")


def test_unknown_or_invalid_artifact_id_returns_not_found():
    client = TestClient(app)
    for kind in ("runs", "evaluations", "proposals"):
        assert client.get(f"/api/{kind}/not-a-uuid").status_code == 404
        assert (
            client.get(f"/api/{kind}/00000000-0000-0000-0000-000000000000").status_code
            == 404
        )


def test_proposals_reject_modified_evaluation_evidence():
    client = TestClient(app)
    run = RunResult(
        task="A question",
        task_index=0,
        repetition=1,
        harness=HarnessConfig(name="codex"),
        harness_version="test",
        status="completed",
        report=AgentReport(answer="actual", actions=[], sources=[], limitations=[]),
    )
    evaluation = client.post(
        "/api/evaluations",
        json={
            "runs": [run.model_dump(mode="json")],
            "rubrics": [
                {
                    "task_id": "task-1",
                    "task_index": 0,
                    "task": run.task,
                    "criteria": [
                        {
                            "id": "keyword",
                            "kind": "required_text",
                            "description": "Expected keyword",
                            "values": ["expected"],
                        }
                    ],
                }
            ],
        },
    ).json()
    evaluation["runs"][0]["checks"][1]["reason"] = "Modified failure"
    response = client.post(
        "/api/proposals",
        json={
            "evaluation": evaluation,
            "runs": [run.model_dump(mode="json")],
            "documents": [{"url": "https://example.com/", "body": "Documentation"}],
        },
    )
    assert response.status_code == 409
