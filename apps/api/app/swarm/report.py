"""Rich tables for the CLI scripts: one run (model x agent grid) and a version-over-version comparison."""

from __future__ import annotations

from rich.console import Console
from rich.table import Table

from app.metrics.score import per_model_agent
from app.schemas import Episode, MetricBlock, RunSummary


def _pct(x: float) -> str:
    return f"{100 * x:5.1f}%"


def _row(block: MetricBlock) -> list[str]:
    modes = ", ".join(f"{k}={v}" for k, v in block.failure_modes.items()) or "-"
    return [
        str(block.episodes),
        _pct(block.success_rate),
        f"{block.avg_steps:.1f}",
        f"{block.avg_duration_s:.1f}s",
        f"${block.avg_cost_usd:.4f}",
        modes,
    ]


def _row_with_total(block: MetricBlock) -> list[str]:
    cells = _row(block)
    return cells[:5] + [f"${block.total_cost_usd:.4f}"] + cells[5:]


def run_table(run: RunSummary, episodes: list[Episode]) -> Table:
    """model x agent grid; the footer has one line per model (all agents) with its total spend, then the run total."""
    t = Table(title=f"run {run.run_id}  site={run.site_id}/{run.site_version}  ({run.overall.episodes} episodes)")
    for col in ("model", "agent", "n", "success", "avg steps", "avg time", "avg cost", "total cost", "failure modes"):
        t.add_column(col, justify="right" if col not in ("model", "agent", "failure modes") else "left")
    for (model_id, agent), block in per_model_agent(episodes).items():
        t.add_row(model_id, agent, *_row_with_total(block))
    t.add_section()
    for model_id, block in sorted(run.per_model.items()):
        t.add_row(f"[bold]{model_id}", "all", *_row_with_total(block))
    t.add_row("[bold]all", "", *_row_with_total(run.overall))
    return t


def estimate_table(estimate: dict, budget_usd: float | None = None, *, per_iteration: bool = False) -> Table:
    """The pre-run cost estimate from runner.estimate_run_cost, one row per model plus the total."""
    a = estimate["assumptions"]
    title = (
        f"cost estimate{' per iteration' if per_iteration else ''}: {estimate['episodes']} episodes, "
        f"~{a['avg_steps']} steps x ~{a['tokens_in_per_step']} in / {a['tokens_out_per_step']} out tokens"
        + (f"  (budget ${budget_usd:.2f})" if budget_usd is not None else "")
    )
    t = Table(title=title)
    for col, justify in (("model", "left"), ("episodes", "right"), ("est. cost", "right")):
        t.add_column(col, justify=justify)
    for model_id, usd in estimate["per_model"].items():
        t.add_row(model_id, str(a["episodes_per_model"].get(model_id, "?")), f"${usd:.2f}")
    t.add_section()
    over = budget_usd is not None and estimate["total_usd"] > budget_usd
    t.add_row(
        "[bold]total", str(estimate["episodes"]), f"[bold {'red' if over else 'green'}]${estimate['total_usd']:.2f}"
    )
    return t


def per_task_table(run: RunSummary) -> Table:
    t = Table(title="per task")
    for col in ("task", "kind", "trap", "n", "success", "avg steps", "avg time", "avg cost", "failure modes"):
        t.add_column(col, justify="right" if col in ("n", "success", "avg steps", "avg time", "avg cost") else "left")
    tasks = {x.id: x for x in run.tasks}
    for task_id, block in run.per_task.items():
        task = tasks.get(task_id)
        t.add_row(task_id, task.kind.value if task else "?", (task.trap if task else None) or "-", *_row(block))
    return t


def versions_table(results: list[tuple[str, RunSummary]]) -> Table:
    """One row per site version: success rate, avg steps, avg time, avg cost (+ delta vs the first version)."""
    t = Table(title="site versions")
    for col in ("version", "run", "episodes", "success", "avg steps", "avg time", "avg cost", "failure modes"):
        t.add_column(col, justify="right" if col not in ("version", "run", "failure modes") else "left")
    base: MetricBlock | None = None
    for version, run in results:
        b = run.overall
        base = base or b
        d = b.success_rate - base.success_rate
        succ = _pct(b.success_rate) + (f" ({d:+.0%})" if b is not base else "")
        modes = ", ".join(f"{k}={v}" for k, v in b.failure_modes.items()) or "-"
        t.add_row(
            version,
            run.run_id,
            str(b.episodes),
            succ,
            f"{b.avg_steps:.1f}",
            f"{b.avg_duration_s:.1f}s",
            f"${b.avg_cost_usd:.4f}",
            modes,
        )
    return t


def print_run(run: RunSummary, episodes: list[Episode], console: Console | None = None) -> None:
    console = console or Console()
    console.print(run_table(run, episodes))
    if run.per_task:
        console.print(per_task_table(run))
