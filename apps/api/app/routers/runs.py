import asyncio

from fastapi import APIRouter, HTTPException

from app.artifacts import load_artifact, save_artifact
from app.runs import RunRequest, RunResult, credentials, run_one

router = APIRouter(tags=["runs"])


@router.post("/runs", response_model=list[RunResult])
async def create_runs(request: RunRequest) -> list[RunResult]:
    """Wait for a small batch; each combination receives a fresh sandbox."""
    try:
        for harness in request.harnesses:
            credentials(harness.name)
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    combinations = len(request.harnesses) * len(request.tasks) * request.repetitions
    semaphore = asyncio.Semaphore(request.max_concurrency or combinations)

    async def limited_run(
        harness_index: int, task_index: int, repetition: int
    ) -> RunResult:
        async with semaphore:
            result = await run_one(
                request,
                request.harnesses[harness_index],
                task_index,
                repetition,
            )
            await asyncio.to_thread(save_artifact, "runs", result.run_id, result)
            return result

    return await asyncio.gather(
        *[
            limited_run(harness_index, task_index, repetition)
            for harness_index in range(len(request.harnesses))
            for task_index in range(len(request.tasks))
            for repetition in range(1, request.repetitions + 1)
        ]
    )


@router.get("/runs/{run_id}", response_model=RunResult)
async def get_run(run_id: str) -> RunResult:
    try:
        data = await asyncio.to_thread(load_artifact, "runs", run_id)
    except (ValueError, FileNotFoundError) as exc:
        raise HTTPException(status_code=404, detail="Run not found") from exc
    return RunResult.model_validate(data)
