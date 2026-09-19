import asyncio

from fastapi import APIRouter, HTTPException

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
    semaphore = asyncio.Semaphore(request.max_concurrency)

    async def limited_run(
        harness_index: int, task_index: int, repetition: int
    ) -> RunResult:
        async with semaphore:
            return await run_one(
                request,
                request.harnesses[harness_index],
                task_index,
                repetition,
            )

    return await asyncio.gather(
        *[
            limited_run(harness_index, task_index, repetition)
            for harness_index in range(len(request.harnesses))
            for task_index in range(len(request.tasks))
            for repetition in range(1, request.repetitions + 1)
        ]
    )
