"""Shared glue for scripts/run_swarm.py and scripts/run_loop.py (both the plain-python and `modal run` paths).

    swarm_main(...)  -> (RunSummary, episodes)   one swarm run, printed as a rich table
    loop_main(...)   -> list[(version, RunSummary)]  run -> optimize -> run ... with a comparison table
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Callable

from rich.console import Console

from abtract import store
from abtract.config import settings
from abtract.models.registry import select_models
from abtract.schemas import Episode, RunSummary, SiteVersion, Task
from abtract.swarm.report import estimate_table, print_run, versions_table
from abtract.swarm.runner import BudgetExceeded, estimate_run_cost, run_swarm, serve_site_locally

console = Console()
REPO_ROOT = Path(__file__).resolve().parents[2]
CONFIRM_ABOVE_USD = 5.0  # estimates above this ask for confirmation on a TTY unless --yes


def parse_list(s: str | list[str] | None) -> list[str]:
    if not s:
        return []
    if isinstance(s, list):
        return [x for x in s if x]
    return [x.strip() for x in s.split(",") if x.strip()]


def parse_models(spec: str | list[str] | None) -> list[str]:
    """`--models` -> model ids. Accepts ids and selectors (cheapest:N, vision, all, default, mock), comma-separated."""
    text = ",".join(parse_list(spec)) if isinstance(spec, list) else (spec or "")
    try:
        return [m.id for m in select_models(text)]
    except ValueError as e:
        raise SystemExit(f"--models: {e}") from None


# --------------------------------------------------------------------------- cost estimate / budget

def show_estimate(tasks: list[Task], model_ids: list[str], agent_kinds: list[str], *, budget_usd: float | None,
                  yes: bool, per_iteration: bool = False) -> dict:
    """Print the estimate table; exit if it is over the budget; ask before an expensive run on an interactive TTY.

    Never blocks when stdin is not a TTY (cron, `modal run`, CI): it prints and continues.
    """
    estimate = estimate_run_cost(tasks, model_ids, agent_kinds)
    console.print(estimate_table(estimate, budget_usd, per_iteration=per_iteration))
    if budget_usd is not None and estimate["total_usd"] > budget_usd:
        raise SystemExit(f"swarm: estimated ${estimate['total_usd']:.2f} exceeds --budget-usd {budget_usd:.2f}; "
                         f"raise the budget or use fewer models/agents/tasks (e.g. --models cheapest:3 --limit 5)")
    if estimate["total_usd"] > CONFIRM_ABOVE_USD and not yes:
        if sys.stdin is not None and sys.stdin.isatty():
            reply = console.input(f"swarm: this may cost ~${estimate['total_usd']:.2f}. Continue? [y/N] ")
            if reply.strip().lower() not in ("y", "yes"):
                raise SystemExit("swarm: aborted")
        else:
            console.print("swarm: no TTY, continuing without confirmation (pass --budget-usd to cap spend)")
    return estimate


# --------------------------------------------------------------------------- site

def ensure_site_in_store(site_id: str, version: str) -> None:
    """For local runs: import demo_site/<version> (or demo_site) into the store when the version is missing."""
    if store.site_dir(site_id, version).is_dir():
        return
    candidates = [REPO_ROOT / "demo_site" / version, REPO_ROOT / "demo_site"] if site_id == "demo" else []
    for src in candidates:
        if src.is_dir() and any(src.glob("*.html")):
            console.print(f"swarm: importing {src} -> store as {site_id}/{version}")
            store.import_site(site_id, version, src, notes="imported from demo_site")
            return
    raise SystemExit(f"site version {site_id}/{version} not found at {store.site_dir(site_id, version)} "
                     f"(import it with store.import_site or scripts/import_demo_site.py)")


def setup_site(site_id: str, version: str, *, local: bool, site_base_url: str | None = None
               ) -> tuple[Callable[[str], str], Callable[[], None]]:
    """Returns (url_for_version, stop_fn). Local: serves the store on a free port; cloud: the deployed site server."""
    if site_base_url:
        settings.site_base_url = site_base_url.rstrip("/")
    if local:
        ensure_site_in_store(site_id, version)
        base, stop = serve_site_locally()
        return (lambda v: f"{base}/s/{site_id}/{v}/"), stop
    if not settings.site_base_url:
        raise SystemExit("cloud runs need the deployed site server URL: set ABTRACT_SITE_BASE_URL in .env or pass "
                         "--site-base-url https://<workspace>--abtract-site-server.modal.run (printed by `modal deploy deploy.py`)")
    return (lambda v: settings.site_url(site_id, v)), (lambda: None)


# --------------------------------------------------------------------------- tasks

def load_tasks(spec: str, site_id: str, version: str, *, limit: int | None = None) -> list[Task]:
    """`generate` -> Gemini writes tasks for the site version; otherwise a JSON file (list or {"tasks": [...]})."""
    if spec.strip().lower() == "generate":
        from abtract.optimizer.task_gen import generate_tasks, save_tasks

        if site_id == "demo":
            ensure_site_in_store(site_id, version)
        tasks = generate_tasks(site_id, version, n=limit or 8)
        out = store.root() / "sites" / store._safe(site_id) / f"tasks.{store._safe(version)}.generated.json"
        save_tasks(tasks, out)
        console.print(f"swarm: generated {len(tasks)} tasks -> {out}")
    else:
        path = Path(spec)
        if not path.is_file():
            raise SystemExit(f"tasks file not found: {path}")
        data = json.loads(path.read_text())
        if isinstance(data, dict):
            data = data.get("tasks", [])
        tasks = [Task(**t) for t in data]
    if limit:
        tasks = tasks[:limit]
    if not tasks:
        raise SystemExit("no tasks")
    return tasks


# --------------------------------------------------------------------------- progress

def _progress(total: int) -> Callable[[Episode], None]:
    done = {"n": 0}

    def on_episode(ep: Episode) -> None:
        done["n"] += 1
        status = "ok  " if ep.success else "FAIL"
        extra = "" if ep.success else f" [{ep.failure_mode}]"
        console.print(f"[{done['n']:3d}/{total}] {status} {ep.model_id:22s} {ep.agent_kind.value:6s} {ep.task_id:24s} "
                      f"steps={ep.n_steps:2d} {ep.duration_s:6.1f}s ${ep.cost_usd:.4f}{extra}", highlight=False)

    return on_episode


# --------------------------------------------------------------------------- entrypoints

def swarm_main(*, site: str, version: str, models: str | list[str], agents: str | list[str], tasks: str | list[Task],
               local: bool, site_base_url: str | None = None, concurrency: int = 8, run_id: str | None = None,
               use_llm_judge: bool = True, limit: int | None = None, budget_usd: float | None = None,
               yes: bool = False) -> tuple[RunSummary, list[Episode]]:
    model_ids, agent_kinds = parse_models(models), parse_list(agents)
    url_for, stop = setup_site(site, version, local=local, site_base_url=site_base_url)
    try:
        task_list = tasks if isinstance(tasks, list) else load_tasks(tasks, site, version, limit=limit)
        site_url = url_for(version)
        console.print(f"swarm: {site}/{version} at {site_url}  models={model_ids} agents={agent_kinds} "
                      f"tasks={len(task_list)}  ({'local' if local else 'modal'})")
        estimate = show_estimate(task_list, model_ids, agent_kinds, budget_usd=budget_usd, yes=yes)
        t0 = time.time()
        try:
            run = run_swarm(site, version, task_list, model_ids, agent_kinds, site_url=site_url, local=local,
                            concurrency=concurrency, run_id=run_id, on_episode=_progress(estimate["episodes"]),
                            use_llm_judge=use_llm_judge, budget_usd=budget_usd)
        except BudgetExceeded as e:
            raise SystemExit(f"swarm: {e}") from None
        episodes = store.load_episodes(run.run_id)
        console.print(f"swarm: done in {time.time() - t0:.0f}s, spent ${run.overall.total_cost_usd:.4f}; "
                      f"saved {store.run_dir(run.run_id)}")
        print_run(run, episodes, console)
        return run, episodes
    finally:
        stop()


def loop_main(*, site: str, version: str, iterations: int, models: str | list[str], agents: str | list[str], tasks: str,
              local: bool, site_base_url: str | None = None, concurrency: int = 8, use_llm_judge: bool = True,
              limit: int | None = None, budget_usd: float | None = None, yes: bool = False
              ) -> list[tuple[str, RunSummary]]:
    """`budget_usd` applies to each swarm run (iteration), not to the whole loop."""
    model_ids, agent_kinds = parse_models(models), parse_list(agents)
    url_for, stop = setup_site(site, version, local=local, site_base_url=site_base_url)
    results: list[tuple[str, RunSummary]] = []
    notes: list[SiteVersion] = []
    try:
        task_list = load_tasks(tasks, site, version, limit=limit)
        estimate = show_estimate(task_list, model_ids, agent_kinds, budget_usd=budget_usd, yes=yes, per_iteration=True)
        console.print(f"loop: {iterations + 1} swarm runs -> ~${estimate['total_usd'] * (iterations + 1):.2f} in total")
        current = version
        for i in range(iterations + 1):
            console.rule(f"iteration {i}/{iterations}: swarm on {site}/{current}")
            try:
                run = run_swarm(site, current, task_list, model_ids, agent_kinds, site_url=url_for(current),
                                local=local, concurrency=concurrency, on_episode=_progress(estimate["episodes"]),
                                use_llm_judge=use_llm_judge, budget_usd=budget_usd)
            except BudgetExceeded as e:
                raise SystemExit(f"loop: {e}") from None
            print_run(run, store.load_episodes(run.run_id), console)
            results.append((current, run))
            if i == iterations:
                break
            console.rule(f"optimizing {site}/{current} from run {run.run_id}")
            if local:
                from abtract.optimizer.rewrite import optimize_site

                sv = optimize_site(site, current, run.run_id, local=True)
            else:
                from abtract.optimizer.rewrite import optimize_site_remote

                sv = SiteVersion(**optimize_site_remote.remote(site, current, run.run_id))
                store.register_version(sv)  # local mirror of the volume's versions.json (files stay on the volume)
            notes.append(sv)
            console.print(f"optimizer: {sv.site_id}/{sv.version} (parent {sv.parent}) changed {sv.changed_files}")
            console.print(sv.notes, highlight=False)
            current = sv.version
    finally:
        stop()
    console.rule("summary")
    console.print(versions_table(results))
    for sv in notes:
        console.print(f"\n[bold]{sv.version}[/bold] (from {sv.parent}) changed: {', '.join(sv.changed_files) or '-'}")
        console.print(sv.notes, highlight=False)
    return results
