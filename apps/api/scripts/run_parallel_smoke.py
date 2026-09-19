"""Run five real Codex tasks through FastAPI and save evidence under /docs.

From apps/api: uv run python scripts/run_parallel_smoke.py
Creates billable Modal sandboxes and OpenAI API requests.
"""

import asyncio
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import httpx
import modal

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings  # noqa: E402
from app.main import app  # noqa: E402

TASKS = [
    (
        "01-basic-sandbox",
        "easy",
        "How do I create a Modal Sandbox from a local Python "
        "program, run a command that prints hello, read its output, and terminate it? "
        "Give a minimal complete example using the current Modal Python SDK.",
    ),
    (
        "02-timeouts-and-processes",
        "easy",
        "Explain the difference between a Modal "
        "Sandbox lifetime and a Sandbox.exec timeout. Give a Python example with a "
        "120-second sandbox lifetime and a 10-second command timeout that captures "
        "stdout, stderr, and exit code and always cleans up. Explain failure behavior.",
    ),
    (
        "03-filesystem-migration",
        "medium",
        "Our old code uses `with sb.open('/workspace/"
        "result.json', 'r') as f: data = f.read()`, but Modal says the legacy "
        "filesystem "
        "API is no longer supported. Rewrite the file write/read/validation flow with "
        "the current Python API. Reject files over 1 MB before downloading them and "
        "handle a missing file. Give a complete example and link current docs.",
    ),
    (
        "04-bounded-parallelism",
        "hard",
        "Write a complete async Python example using "
        "the current Modal SDK that runs five independent commands in five fresh "
        "sandboxes, with at most two sandboxes active at once. Preserve input order, "
        "return failures as per-run results so one failure does not abort siblings, "
        "capture stdout/stderr/exit codes, and terminate every created sandbox even "
        "on errors or cancellation. Explain which operations are awaited and how the "
        "concurrency cap includes cleanup.",
    ),
    (
        "05-snapshot-isolation",
        "hard",
        "Design a reproducible Modal benchmark using "
        "one prepared filesystem snapshot and three independent fresh sandboxes "
        "restored from it. Give current Python code that writes a different marker in "
        "each sandbox and demonstrates the other runs cannot see it. Explain "
        "filesystem "
        "versus memory snapshots, current retention limits, how to record the snapshot "
        "ID, and why copying credentials into a baseline snapshot is undesirable. "
        "Do not claim to execute against Modal unless you actually have credentials.",
    ),
]


async def main() -> None:
    batch_started = datetime.now(UTC)
    output = (
        Path(__file__).resolve().parents[3]
        / "docs"
        / ("parallel-" + batch_started.strftime("%Y%m%dT%H%M%SZ"))
    )
    output.mkdir(parents=True)
    request = {
        "url": "https://modal.com/docs",
        "tasks": [task[2] for task in TASKS],
        "harnesses": [{"name": "codex", "model": "gpt-5.4-mini"}],
        "repetitions": 1,
        "max_concurrency": 5,
        "timeout_seconds": 300,
    }
    (output / "request.json").write_text(json.dumps(request, indent=2) + "\n")
    print(f"Artifacts: {output}", flush=True)
    modal_app = await modal.App.lookup.aio(
        settings.modal_app_name, create_if_missing=True
    )
    samples: list[dict] = []

    async def monitor() -> None:
        previous: set[str] = set()
        while True:
            try:
                sandboxes = [
                    sb async for sb in modal.Sandbox.list.aio(app_id=modal_app.app_id)
                ]
                codes = await asyncio.gather(*(sb.poll.aio() for sb in sandboxes))
                active = {
                    sb.object_id
                    for sb, code in zip(sandboxes, codes, strict=True)
                    if code is None
                }
                samples.append(
                    {"at": datetime.now(UTC).isoformat(), "active_ids": sorted(active)}
                )
                if active != previous:
                    print(f"Modal active sandboxes: {len(active)}", flush=True)
                    previous = active
            except Exception as exc:
                samples.append({"at": datetime.now(UTC).isoformat(), "error": str(exc)})
            await asyncio.sleep(1)

    monitor_task = asyncio.create_task(monitor())
    started = time.monotonic()
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            response = await client.post("/api/runs", json=request, timeout=600)
        response.raise_for_status()
        results = response.json()
    finally:
        monitor_task.cancel()
        await asyncio.gather(monitor_task, return_exceptions=True)
        (output / "modal-observations.json").write_text(
            json.dumps(samples, indent=2) + "\n"
        )
    elapsed = time.monotonic() - started
    ids = {r["sandbox_id"] for r in results if r["sandbox_id"]}
    observed_peak = max(
        (len(ids.intersection(s.get("active_ids", []))) for s in samples), default=0
    )
    events = []
    summary_runs = []
    for (slug, difficulty, _), result in zip(TASKS, results, strict=True):
        (output / f"{slug}.run.json").write_text(json.dumps(result, indent=2) + "\n")
        if result["report"] is not None:
            (output / f"{slug}.result.json").write_text(
                json.dumps(result["report"], indent=2) + "\n"
            )
        if result["execution_started_at"] and result["execution_finished_at"]:
            events.extend(
                [
                    (result["execution_started_at"], 1),
                    (result["execution_finished_at"], -1),
                ]
            )
        summary_runs.append(
            {
                k: result[k]
                for k in (
                    "run_id",
                    "sandbox_id",
                    "status",
                    "duration_seconds",
                    "execution_started_at",
                    "execution_finished_at",
                    "error",
                    "cleanup_error",
                )
            }
            | {"task": slug, "difficulty": difficulty}
        )
    active = peak = 0
    for _, delta in sorted(events):
        active += delta
        peak = max(peak, active)
    summary = {
        "batch_started_at": batch_started.isoformat(),
        "wall_seconds": round(elapsed, 3),
        "summed_run_seconds": round(sum(r["duration_seconds"] for r in results), 3),
        "execution_peak_concurrency": peak,
        "modal_observed_peak_concurrency": observed_peak,
        "distinct_sandboxes": len(ids),
        "runs": summary_runs,
    }
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2), flush=True)
    assert len(results) == len(ids) == 5
    assert all(
        r["status"] == "completed" and r["cleanup_error"] is None for r in results
    )
    assert peak == observed_peak == 5, "Five-way overlap was not demonstrated"


if __name__ == "__main__":
    asyncio.run(main())
