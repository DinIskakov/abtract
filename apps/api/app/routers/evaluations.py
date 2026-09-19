"""Evaluation and proposal endpoints; no automatic patch application."""

import asyncio

from fastapi import APIRouter, HTTPException

from app.artifacts import load_artifact, save_artifact
from app.evaluations import EvaluationReport, EvaluationRequest, evaluate
from app.gemini import GeminiError
from app.proposals import ProposalReport, ProposalRequest, propose

router = APIRouter(tags=["evaluations"])


@router.post("/evaluations", response_model=EvaluationReport)
async def create_evaluation(request: EvaluationRequest) -> EvaluationReport:
    result = await evaluate(request)
    await asyncio.to_thread(
        save_artifact, "evaluation_inputs", result.evaluation_id, request
    )
    await asyncio.to_thread(save_artifact, "evaluations", result.evaluation_id, result)
    return result


@router.post("/proposals", response_model=ProposalReport)
async def create_proposal(request: ProposalRequest) -> ProposalReport:
    saved = await get_evaluation(request.evaluation.evaluation_id)
    if saved != request.evaluation:
        raise HTTPException(
            status_code=409, detail="Evaluation evidence changed; use the saved report"
        )
    try:
        result = await propose(request)
    except GeminiError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    await asyncio.to_thread(save_artifact, "proposals", result.proposal_id, result)
    return result


@router.get("/evaluations/{evaluation_id}", response_model=EvaluationReport)
async def get_evaluation(evaluation_id: str) -> EvaluationReport:
    try:
        data = await asyncio.to_thread(load_artifact, "evaluations", evaluation_id)
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=404, detail="Evaluation not found") from exc
    return EvaluationReport.model_validate(data)


@router.get("/proposals/{proposal_id}", response_model=ProposalReport)
async def get_proposal(proposal_id: str) -> ProposalReport:
    try:
        data = await asyncio.to_thread(load_artifact, "proposals", proposal_id)
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=404, detail="Proposal not found") from exc
    return ProposalReport.model_validate(data)
