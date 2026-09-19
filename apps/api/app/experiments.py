"""One small, persisted A/B workflow; Gemini supervises every experiment."""

import asyncio
import logging
from datetime import UTC, datetime
from typing import Literal, Self
from uuid import uuid4

from pydantic import BaseModel, Field, HttpUrl, model_validator

from app.artifacts import load_artifact, save_artifact
from app.evaluations import (
    Criterion,
    EvaluationReport,
    EvaluationRequest,
    TaskRubric,
    content_hash,
)
from app.proposals import ProposalReport, ProposalRequest
from app.routers.evaluations import create_evaluation, create_proposal
from app.routers.runs import create_runs
from app.runs import HarnessConfig, RunRequest, RunResult
from app.task_generation import Difficulty, fetch_page, generate_tasks

logger = logging.getLogger(__name__)
Phase = Literal[
    "planning",
    "baseline",
    "baseline_evaluation",
    "proposing",
    "variant",
    "variant_evaluation",
    "completed",
    "failed",
]
RETRIEVAL_NOTE = (
    "Controlled single-page HTTP comparison: native shell HTTP retrieval, no hosted "
    "search. Gemini generates questions, judges answers, and proposes frozen patches. "
    "One repetition is a demo, not statistical evidence of improvement."
)


class ExperimentRequest(BaseModel):
    url: HttpUrl
    harnesses: list[HarnessConfig] = Field(min_length=1, max_length=4)
    task_count: int = Field(default=3, ge=1, le=3)
    difficulty: Difficulty = "easy"
    latency_budget_seconds: float = Field(default=15, gt=0, le=180, allow_inf_nan=False)

    @model_validator(mode="after")
    def distinct_harnesses(self) -> Self:
        if len({(h.name, h.model) for h in self.harnesses}) != len(self.harnesses):
            raise ValueError("Choose each harness and model combination only once")
        if self.url.username or self.url.password:
            raise ValueError("Page URLs must not contain credentials")
        return self


class Experiment(BaseModel):
    experiment_id: str = Field(default_factory=lambda: str(uuid4()))
    url: HttpUrl
    phase: Phase = "planning"
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    tasks: list[TaskRubric] = Field(default_factory=list)
    harnesses: list[HarnessConfig]
    difficulty: Difficulty = "easy"
    latency_budget_seconds: float = Field(default=15, gt=0, le=180, allow_inf_nan=False)
    baseline_runs: list[RunResult] = Field(default_factory=list)
    baseline_evaluation: EvaluationReport | None = None
    proposal: ProposalReport | None = None
    variant_runs: list[RunResult] = Field(default_factory=list)
    variant_evaluation: EvaluationReport | None = None
    error: str | None = None
    note: str | None = RETRIEVAL_NOTE
    concurrency: int


jobs: dict[str, asyncio.Task[None]] = {}


async def persist(experiment: Experiment, phase: Phase) -> None:
    experiment.phase = phase
    experiment.updated_at = datetime.now(UTC)
    await asyncio.to_thread(
        save_artifact, "experiments", experiment.experiment_id, experiment
    )


async def execute(experiment: Experiment, task_count: int) -> None:
    try:
        document = await fetch_page(experiment.url)
        # Redirects are resolved once, then both arms use the same canonical URL.
        experiment.url = document.url
        generated = await generate_tasks(document, task_count, experiment.difficulty)
        # Freeze identical correctness and runtime criteria for both arms.
        experiment.tasks = [
            task.model_copy(
                update={
                    "criteria": [
                        *task.criteria,
                        Criterion(
                            id="agent_latency",
                            kind="execution_duration_budget",
                            description=(
                                "Agent runtime budget, excluding sandbox startup"
                            ),
                            limit=experiment.latency_budget_seconds,
                        ),
                    ]
                }
            )
            for task in generated
        ]
        request = RunRequest(
            url=experiment.url,
            tasks=[task.task for task in experiment.tasks],
            harnesses=experiment.harnesses,
            max_concurrency=experiment.concurrency,
            capture_http=True,
            retrieval_mode="direct_http",
            timeout_seconds=180,
        )
        await persist(experiment, "baseline")
        experiment.baseline_runs = await create_runs(request)
        await persist(experiment, "baseline_evaluation")
        experiment.baseline_evaluation = await create_evaluation(
            EvaluationRequest(
                runs=experiment.baseline_runs,
                rubrics=experiment.tasks,
                semantic_judge=True,
            )
        )
        await persist(experiment, "proposing")
        observed = [
            event
            for run in experiment.baseline_runs
            for event in run.observations.http
            if event.url == str(document.url) and event.status_code == 200
        ]
        if not observed or any(
            event.original_sha256 != content_hash(document.body) for event in observed
        ):
            experiment.note = (
                RETRIEVAL_NOTE + " No variant was generated: the exact source page "
                "was not observed consistently in baseline traffic. Choose a stable "
                "documentation page; the baseline results remain available."
            )
            await persist(experiment, "completed")
            return
        experiment.proposal = await create_proposal(
            ProposalRequest(
                evaluation=experiment.baseline_evaluation,
                runs=experiment.baseline_runs,
                documents=[document],
            )
        )
        if not experiment.proposal.patches:
            experiment.note = RETRIEVAL_NOTE + " " + experiment.proposal.summary
            await persist(experiment, "completed")
            return
        variant = request.model_copy(
            update={
                "variant_id": experiment.proposal.variant_id,
                "patches": [item.patch for item in experiment.proposal.patches],
            }
        )
        await persist(experiment, "variant")
        experiment.variant_runs = await create_runs(variant)
        await persist(experiment, "variant_evaluation")
        experiment.variant_evaluation = await create_evaluation(
            EvaluationRequest(
                runs=experiment.variant_runs,
                rubrics=experiment.tasks,
                semantic_judge=True,
            )
        )
        await persist(experiment, "completed")
    except asyncio.CancelledError:
        experiment.error = "Experiment interrupted by server shutdown; start a new run."
        await persist(experiment, "failed")
        raise
    except Exception as exc:
        # Known public errors have safe messages; never expose provider payloads.
        from app.gemini import GeminiError
        from app.task_generation import PageError

        experiment.error = (
            str(exc)
            if isinstance(exc, (GeminiError, PageError))
            else "Experiment could not finish. Saved earlier stages remain available."
        )
        logger.error(
            "Experiment %s failed (%s)", experiment.experiment_id, type(exc).__name__
        )
        await persist(experiment, "failed")


async def start_experiment(request: ExperimentRequest) -> Experiment:
    experiment = Experiment(
        url=request.url,
        harnesses=request.harnesses,
        difficulty=request.difficulty,
        latency_budget_seconds=request.latency_budget_seconds,
        concurrency=len(request.harnesses) * request.task_count,
    )
    await persist(experiment, "planning")
    task = asyncio.create_task(execute(experiment, request.task_count))
    jobs[experiment.experiment_id] = task

    def finished(done: asyncio.Task[None]) -> None:
        jobs.pop(experiment.experiment_id, None)
        if not done.cancelled() and done.exception() is not None:
            logger.error(
                "Experiment %s could not save its final state", experiment.experiment_id
            )

    task.add_done_callback(finished)
    return experiment.model_copy(deep=True)


async def read_experiment(identifier: str) -> Experiment:
    # A job may finish while the thread reads an earlier phase from disk. Remember
    # its presence before yielding so a polling race cannot overwrite completion.
    was_active = identifier in jobs
    data = await asyncio.to_thread(load_artifact, "experiments", identifier)
    experiment = Experiment.model_validate(data)
    if (
        experiment.phase not in {"completed", "failed"}
        and not was_active
        and identifier not in jobs
    ):
        experiment.error = "Server restarted during this experiment; start a new run."
        await persist(experiment, "failed")
    return experiment


def public_experiment(experiment: Experiment) -> Experiment:
    """Polling stays small; GET /api/runs/{run_id} retains the complete record."""
    result = experiment.model_copy(deep=True)
    for run in [*result.baseline_runs, *result.variant_runs]:
        run.stdout = ""
        run.stderr = ""
        run.observations.native_tool_events = []
        for event in run.observations.http:
            event.original_body = None
            event.response_body = None
    return result


async def shutdown_experiments() -> None:
    active = list(jobs.values())
    for task in active:
        task.cancel()
    if active:
        await asyncio.gather(*active, return_exceptions=True)
