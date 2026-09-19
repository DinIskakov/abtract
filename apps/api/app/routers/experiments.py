"""Frontend options and a pollable experiment endpoint."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.config import settings
from app.experiments import (
    Experiment,
    ExperimentRequest,
    public_experiment,
    read_experiment,
    start_experiment,
)
from app.runs import Harness, credentials

router = APIRouter(tags=["experiments"])


class HarnessOption(BaseModel):
    id: str
    name: Harness
    model: str | None
    label: str
    available: bool
    reason: str | None = None


class SupervisorOption(BaseModel):
    name: str = "Gemini"
    model: str
    available: bool


class ExperimentOptions(BaseModel):
    supervisor: SupervisorOption
    harnesses: list[HarnessOption]


@router.get("/experiments/options", response_model=ExperimentOptions)
async def experiment_options() -> ExperimentOptions:
    choices: list[tuple[str, Harness, str | None, str]] = [
        ("codex-mini", "codex", "gpt-5.4-mini", "Codex · GPT-5.4 mini"),
        (
            "gemini-flash",
            "gemini",
            settings.gemini_model,
            f"Gemini CLI · {settings.gemini_model}",
        ),
        ("claude-sonnet", "claude", None, "Claude Code · default"),
    ]
    harnesses = []
    for identifier, name, model, label in choices:
        reason = None
        try:
            credentials(name)
        except ValueError as exc:
            reason = str(exc)
        harnesses.append(
            HarnessOption(
                id=identifier,
                name=name,
                model=model,
                label=label,
                available=reason is None,
                reason=reason,
            )
        )
    return ExperimentOptions(
        supervisor=SupervisorOption(
            model=settings.gemini_model,
            available=next(
                item.available for item in harnesses if item.name == "gemini"
            ),
        ),
        harnesses=harnesses,
    )


@router.post("/experiments", response_model=Experiment, status_code=202)
async def create_experiment(request: ExperimentRequest) -> Experiment:
    try:
        credentials("gemini")  # Supervisor is independent of tested harnesses.
        for harness in request.harnesses:
            credentials(harness.name)
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return public_experiment(await start_experiment(request))


@router.get("/experiments/{experiment_id}", response_model=Experiment)
async def get_experiment(experiment_id: str) -> Experiment:
    try:
        experiment = await read_experiment(experiment_id)
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=404, detail="Experiment not found") from exc
    return public_experiment(experiment)
