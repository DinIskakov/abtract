"""Run one agent against one site locally and print the Episode.

    uv run python -m abtract.agents.run_local --agent text --model mock --site-url http://localhost:9000/ \
        --task-id t01_h100_price [--tasks demo_site/tasks.json] [--prompt "free-form task"] [-v]

Serve the demo site first, e.g. `python3 -m http.server 9000 -d demo_site/v0`, or point --site-url at the hosted site.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from abtract.schemas import AgentKind, Task, TaskKind

from . import run_agent


def load_tasks(path: Path) -> list[Task]:
    data = json.loads(path.read_text())
    if isinstance(data, dict):
        data = data.get("tasks") or data.get("items") or list(data.values())
    return [Task.model_validate(t) for t in data]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Run one abtract agent locally.")
    ap.add_argument("--agent", choices=[k.value for k in AgentKind], required=True)
    ap.add_argument("--model", default="mock")
    ap.add_argument("--site-url", default="http://localhost:9000/")
    ap.add_argument("--task-id")
    ap.add_argument("--tasks", default="demo_site/tasks.json")
    ap.add_argument("--prompt", help="free-form task prompt instead of --task-id")
    ap.add_argument("--max-steps", type=int)
    ap.add_argument("--run-id", default="local")
    ap.add_argument("--site-id", default="demo")
    ap.add_argument("--site-version", default="v0")
    ap.add_argument("--screenshot-dir", help="vision agent: where to write NN.png (default: <data_dir>/runs/<run_id>/screenshots/<episode>/)")
    ap.add_argument("-v", "--verbose", action="store_true", help="print observations and model replies as they happen")
    ap.add_argument("--summary-only", action="store_true", help="do not print the full Episode JSON")
    args = ap.parse_args(argv)

    if args.prompt:
        task = Task(id=args.task_id or "adhoc", kind=TaskKind.answer, prompt=args.prompt)
    elif args.task_id:
        tasks = load_tasks(Path(args.tasks))
        task = next((t for t in tasks if t.id == args.task_id), None)
        if task is None:
            print(f"task {args.task_id!r} not found in {args.tasks}; known: {[t.id for t in tasks]}", file=sys.stderr)
            return 2
    else:
        ap.error("give --task-id or --prompt")
        return 2  # pragma: no cover
    if args.max_steps:
        task.max_steps = args.max_steps

    from abtract.agents.base import BaseAgent  # noqa: F401  (import check)

    kind = AgentKind(args.agent)
    # Build the agent ourselves so we can attach the verbose logger; same construction as run_agent().
    if kind == AgentKind.text:
        from abtract.agents.text_agent import TextAgent as Impl
    elif kind == AgentKind.dom:
        from abtract.agents.dom_agent import DomAgent as Impl
    else:
        from abtract.agents.vision_agent import VisionAgent as Impl
    agent = Impl(
        model_id=args.model, run_id=args.run_id, site_id=args.site_id, site_version=args.site_version,
        screenshot_dir=Path(args.screenshot_dir) if args.screenshot_dir else None,
    )
    if args.verbose:
        agent.log = lambda m: print(m, file=sys.stderr, flush=True)
    ep = agent.run(task, args.site_url)

    if not args.summary_only:
        print(ep.model_dump_json(indent=2))
    status = "answer=" + repr(ep.final_answer) if ep.final_answer is not None else f"failure={ep.failure_mode}"
    err = f" error={ep.error!r}" if ep.error else ""
    print(
        f"[{ep.agent_kind.value}/{ep.model_id}] task={task.id} steps={ep.n_steps} {status}{err} "
        f"llm_calls={ep.usage.llm_calls} tokens={ep.usage.input_tokens}+{ep.usage.output_tokens} "
        f"cost=${ep.cost_usd:.5f} time={ep.duration_s:.1f}s final_url={ep.final_url}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())


__all__ = ["main", "load_tasks", "run_agent"]
