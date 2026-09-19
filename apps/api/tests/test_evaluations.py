import asyncio
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from app import gemini
from app.evaluations import EvaluationRequest, content_hash, evaluate
from app.proposals import ProposalRequest, document_evidence, propose
from app.runs import AgentReport, HarnessConfig, RunResult


def example_run(
    answer: str = "Use Sandbox.create().\n```python\nx = 1\n```", **changes: object
) -> RunResult:
    data = dict(
        task="How do I create a sandbox?",
        task_index=0,
        repetition=1,
        harness=HarnessConfig(name="codex"),
        harness_version="test",
        status="completed",
        duration_seconds=5,
        report=AgentReport(
            answer=answer,
            actions=[],
            sources=["https://example.com/docs"],
            limitations=[],
        ),
    )
    data.update(changes)
    return RunResult.model_validate(data)


def request(
    run: RunResult, criteria: list[dict[str, object]], semantic: bool = False
) -> EvaluationRequest:
    return EvaluationRequest.model_validate(
        {
            "runs": [run],
            "rubrics": [
                {
                    "task_id": "sandbox-create",
                    "task_index": 0,
                    "task": run.task,
                    "criteria": criteria,
                }
            ],
            "semantic_judge": semantic,
        }
    )


def criterion(kind: str, **values: object) -> dict[str, object]:
    return {"id": kind, "kind": kind, "description": kind, **values}


def test_deterministic_checks_and_missing_cost() -> None:
    report = asyncio.run(
        evaluate(
            request(
                example_run(),
                [
                    criterion("required_text", values=["Sandbox.create"]),
                    criterion("forbidden_text", values=["fake API"]),
                    criterion("python_syntax"),
                    criterion("required_sources", values=["https://example.com/docs"]),
                    criterion("duration_budget", limit=6),
                    criterion("cost_budget", limit=1),
                ],
            )
        )
    )
    assert report.unknown == 1
    assert [check.outcome for check in report.runs[0].checks] == ["pass"] * 6 + [
        "unknown"
    ]
    assert "not total billing" in report.runs[0].checks[-1].reason


def test_failure_and_invalid_python() -> None:
    report = asyncio.run(
        evaluate(
            request(
                example_run("```python\nif\n```"),
                [
                    criterion("python_syntax"),
                    criterion("required_text", values=["Sandbox"]),
                ],
            )
        )
    )
    assert report.failed == 1
    assert report.runs[0].checks[1].evidence == ["if\n"]


def test_infra_failure_is_not_success() -> None:
    report = asyncio.run(
        evaluate(
            request(
                example_run(status="error", report=None, error="timeout"),
                [criterion("python_syntax")],
            )
        )
    )
    assert report.failed == 1
    assert report.runs[0].checks[0].reason == "timeout"
    assert report.runs[0].checks[1].outcome == "unknown"


@pytest.mark.parametrize(
    "criteria",
    [
        [criterion("required_text")],
        [criterion("semantic")],
        [criterion("duration_budget", limit=float("nan"))],
        [criterion("python_syntax"), criterion("python_syntax")],
    ],
)
def test_reject_invalid_rubrics(criteria: list[dict[str, object]]) -> None:
    with pytest.raises(ValidationError):
        request(example_run(), criteria)


def test_judge_evidence_and_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    mock = AsyncMock(
        return_value=gemini.Generation(
            data={
                "checks": [
                    {
                        "check_id": "semantic",
                        "outcome": "pass",
                        "reason": "Correct method",
                        "evidence": ["Sandbox.create()"],
                    }
                ]
            },
            requested_model="judge",
            reported_model="judge-001",
        )
    )
    monkeypatch.setattr(gemini, "generate", mock)
    report = asyncio.run(
        evaluate(
            request(
                example_run(),
                [criterion("semantic", reference_answer="Use Sandbox.create().")],
                True,
            )
        )
    )
    assert report.passed == 1
    assert report.runs[0].judge is not None
    assert report.runs[0].judge.reported_model == "judge-001"
    assert report.runs[0].checks[1].method == "llm_judge"


@pytest.mark.parametrize("evidence", [["invented quote"], []])
def test_hallucinated_judge_evidence_is_unknown(
    monkeypatch: pytest.MonkeyPatch, evidence: list[str]
) -> None:
    monkeypatch.setattr(
        gemini,
        "generate",
        AsyncMock(
            return_value=gemini.Generation(
                data={
                    "checks": [
                        {
                            "check_id": "semantic",
                            "outcome": "pass",
                            "reason": "Correct",
                            "evidence": evidence,
                        }
                    ]
                },
                requested_model="judge",
            )
        ),
    )
    report = asyncio.run(
        evaluate(
            request(
                example_run(),
                [criterion("semantic", reference_answer="Use Sandbox.create().")],
                True,
            )
        )
    )
    assert report.unknown == 1
    assert report.runs[0].checks[1].error


def test_judge_failure_keeps_deterministic_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        gemini,
        "generate",
        AsyncMock(side_effect=gemini.GeminiError("Gemini returned HTTP 429")),
    )
    report = asyncio.run(
        evaluate(
            request(
                example_run(),
                [
                    criterion("required_text", values=["Sandbox"]),
                    criterion("semantic", reference_answer="Use Sandbox.create()."),
                ],
                True,
            )
        )
    )
    assert report.runs[0].checks[1].outcome == "pass"
    assert report.runs[0].checks[2].outcome == "unknown"


def proposal_request() -> ProposalRequest:
    run = example_run("Use Sandbox.make().")
    evaluation = asyncio.run(
        evaluate(request(run, [criterion("required_text", values=["Sandbox.create"])]))
    )
    return ProposalRequest.model_validate(
        {
            "evaluation": evaluation,
            "runs": [run],
            "documents": [
                {
                    "url": "https://example.com/docs",
                    "body": "Create a sandbox using Sandbox.create().",
                }
            ],
        }
    )


def test_proposal_freezes_validated_patch(monkeypatch: pytest.MonkeyPatch) -> None:
    req = proposal_request()
    failed_ref = f"{req.runs[0].run_id}/required_text"
    monkeypatch.setattr(
        gemini,
        "generate",
        AsyncMock(
            return_value=gemini.Generation(
                data={
                    "summary": "Clarify method",
                    "patches": [
                        {
                            "url": "https://example.com/docs",
                            "old_text": "Sandbox.create()",
                            "new_text": "the Python method Sandbox.create()",
                            "rationale": "Clarify the method; hypothesis only",
                            "failed_check_refs": [failed_ref],
                        }
                    ],
                },
                requested_model="judge",
            )
        ),
    )
    report = asyncio.run(propose(req))
    assert report.patches[0].patch.expected_sha256
    assert not report.applied
    assert report.patches[0].failed_check_refs == [failed_ref]
    assert report.variant_id.startswith("variant-")


@pytest.mark.parametrize(
    "old_text,reference",
    [("not in document", "valid"), ("Sandbox.create()", "invalid")],
)
def test_proposal_rejects_fabricated_patches(
    monkeypatch: pytest.MonkeyPatch, old_text: str, reference: str
) -> None:
    req = proposal_request()
    ref = (
        f"{req.runs[0].run_id}/required_text" if reference == "valid" else "missing/run"
    )
    monkeypatch.setattr(
        gemini,
        "generate",
        AsyncMock(
            return_value=gemini.Generation(
                data={
                    "summary": "Clarify",
                    "patches": [
                        {
                            "url": "https://example.com/docs",
                            "old_text": old_text,
                            "new_text": "replacement",
                            "rationale": "hypothesis",
                            "failed_check_refs": [ref],
                        }
                    ],
                },
                requested_model="judge",
            )
        ),
    )
    with pytest.raises(gemini.GeminiError):
        asyncio.run(propose(req))


def test_proposal_rejects_changed_run_evidence() -> None:
    req = proposal_request()
    data = req.model_dump()
    data["runs"][0]["report"]["answer"] = "modified after evaluation"
    with pytest.raises(ValidationError, match="evidence changed"):
        ProposalRequest.model_validate(data)


def test_variant_exposure_is_separate_from_answer_correctness() -> None:
    run = example_run(variant_id="B", variant_sha256="a" * 64)
    report = asyncio.run(evaluate(request(run, [criterion("python_syntax")])))
    assert report.passed == 1
    assert report.runs[0].variant_exposure == "unverified"
    assert not report.runs[0].variant_attribution_eligible
    run.observations.applied_patch_ids = ["patch-1"]
    report = asyncio.run(evaluate(request(run, [criterion("python_syntax")])))
    assert report.runs[0].variant_exposure == "observed"
    assert report.runs[0].variant_attribution_eligible
    run.observations.capture_error = "capture failed"
    report = asyncio.run(evaluate(request(run, [criterion("python_syntax")])))
    assert not report.runs[0].variant_attribution_eligible
    assert report.passed == 1


def test_endpoints_persist_frontend_evidence() -> None:
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as client:
        req = request(example_run(), [criterion("python_syntax")])
        response = client.post("/api/evaluations", json=req.model_dump(mode="json"))
        assert response.status_code == 200
        data = response.json()
        restored = client.get(f"/api/evaluations/{data['evaluation_id']}")
        assert restored.status_code == 200
        assert restored.json()["runs"][0]["checks"][1]["outcome"] == "pass"


def test_python_parser_resource_limit_is_unknown() -> None:
    answer = "```python\nx=" + "+".join("1" for _ in range(3000)) + "\n```"
    report = asyncio.run(
        evaluate(request(example_run(answer), [criterion("python_syntax")]))
    )
    assert report.unknown == 1
    assert "parser recursion" in report.runs[0].checks[1].reason


@pytest.mark.parametrize(
    "body",
    [
        {"candidates": [None]},
        {"candidates": [{"finishReason": "STOP", "content": {"parts": [None]}}]},
    ],
)
def test_gemini_malformed_response_is_safe_error(
    monkeypatch: pytest.MonkeyPatch, body: dict[str, object]
) -> None:
    import httpx
    from pydantic import SecretStr

    from app.config import settings

    monkeypatch.setattr(settings, "gemini_api_key", SecretStr("fixture-only"))
    transport = httpx.MockTransport(lambda _: httpx.Response(200, json=body))
    client = httpx.AsyncClient(transport=transport)
    monkeypatch.setattr(gemini.httpx, "AsyncClient", lambda **_: client)
    with pytest.raises(gemini.GeminiError, match="invalid structured output"):
        asyncio.run(gemini.generate("instructions", {}, {}))


def test_semantic_judges_overlap_with_limit_and_preserve_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def exercise() -> None:
        active = 0
        peak = 0
        entered = 0
        first_five = asyncio.Event()
        later_finished = asyncio.Event()
        completion_order = []

        async def fake_generate(
            instructions: str, payload: dict[str, object], schema: dict[str, object]
        ) -> gemini.Generation:
            nonlocal active, peak, entered
            index = int(str(payload["answer"]))
            active += 1
            entered += 1
            peak = max(peak, active)
            if entered == 5:
                first_five.set()
            await asyncio.wait_for(first_five.wait(), timeout=2)
            if index == 0:
                await asyncio.wait_for(later_finished.wait(), timeout=2)
            if index == 4:
                later_finished.set()
            completion_order.append(index)
            active -= 1
            return gemini.Generation(
                requested_model="judge",
                data={
                    "checks": [
                        {
                            "check_id": "semantic",
                            "outcome": "pass",
                            "reason": "Fixture evidence",
                            "evidence": [str(index)],
                        }
                    ]
                },
            )

        monkeypatch.setattr(gemini, "generate", fake_generate)
        runs = [example_run(str(index)) for index in range(6)]
        req = request(
            runs[0], [criterion("semantic", reference_answer="fixture")], True
        )
        req.runs = runs
        report = await evaluate(req)
        assert peak == 5
        assert report.passed == 6
        assert [run.run_id for run in report.runs] == [run.run_id for run in runs]
        assert completion_order != list(range(6))

    asyncio.run(exercise())


def test_proposal_context_omits_scripts_but_hashes_full_document() -> None:
    document = (
        proposal_request()
        .documents[0]
        .model_copy(
            update={"body": "<script>private code</script><main>Visible help</main>"}
        )
    )
    evidence = document_evidence(document)
    assert "private code" not in evidence["body"]
    assert "Visible help" in evidence["body"]
    assert evidence["original_sha256"] == content_hash(document.body)
