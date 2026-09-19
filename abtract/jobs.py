"""Background jobs behind the landing page: intake (mirror -> tasks -> swarm -> findings) and loop (optimize -> swarm)*N.

    start_job(job)        save it, then run it in the background: `run_job.spawn(job.id)` inside Modal (the deployed
                          dashboard), a daemon thread otherwise (local dev). Returns the job immediately.
    run_job_sync(job_id)  the actual work; updates jobs/<job_id>.json after every phase / episode so the progress
                          page can poll `store.load_job(job_id)` (call store.reload() first when on Modal).
                          Never raises: failures end with status "failed" + `error`.
    run_job               Modal function wrapper (base_image; episodes still fan out to `run_episode` containers).

Phases written to Job.phase:
    intake: "Mirroring site" -> "Choosing tasks" -> "Running swarm" -> "Writing findings" -> done
    loop:   ["Running swarm on vN (baseline)"] -> ("Optimizing vN" -> "Running swarm on vN+1") x iterations
            -> "Writing findings" -> done
Collaborators are imported into this namespace (run_swarm, serve_site_locally, mirror_to_store, pick_tasks,
optimize_site, write_findings) so tests can monkeypatch `abtract.jobs.<name>`.
"""
from __future__ import annotations

import threading
import time
import traceback
from typing import Any

import modal

from abtract import store
from abtract.hosting import urls
from abtract.intake.mirror import mirror_to_store
from abtract.intake.tasks import pick_tasks
from abtract.modal_app import APP_NAME, app, base_image, secrets, volumes
from abtract.models.registry import DEFAULT_SWARM, get_model
from abtract.optimizer.findings import write_findings
from abtract.optimizer.preview import attempt, inspect_page, update_attempts
from abtract.optimizer.rewrite import optimize_site
from abtract.schemas import AgentKind, Episode, Job, JobPreview, PreviewAttempt, RunSummary, Task
from abtract.swarm.runner import run_swarm, serve_site_locally

DEFAULT_AGENTS = [AgentKind.text, AgentKind.dom, AgentKind.vision]
MAX_LOG_LINES = 400


# --------------------------------------------------------------------------- progress

def _progress(job: Job, phase: str | None = None, done: int | None = None, total: int | None = None,
              log_line: str | None = None) -> None:
    """Update the job file (and commit the volume) so the progress page sees it."""
    if phase is not None and phase != job.phase:
        job.phase = phase
        if log_line is None:
            log_line = phase
    if done is not None:
        job.progress_done = done
    if total is not None:
        job.progress_total = total
    if log_line:
        job.log.append(f"[{time.strftime('%H:%M:%S')}] {log_line}")
        if len(job.log) > MAX_LOG_LINES:
            job.log = job.log[:20] + ["[...]"] + job.log[-(MAX_LOG_LINES - 21):]
    if job.live_preview:
        job.live_preview.updated_at = time.time()
    store.save_job(job)
    store.commit()


def _grid_size(tasks: list[Task], model_ids: list[str], agent_kinds: list[AgentKind]) -> int:
    n = 0
    for m in model_ids:
        try:
            vision_ok = get_model(m).supports_vision
        except KeyError:
            vision_ok = True
        for k in agent_kinds:
            if k == AgentKind.vision and not vision_ok:
                continue
            n += len(tasks)
    return n


# --------------------------------------------------------------------------- one swarm run (shared by both job types)

def _run_swarm_phase(job: Job, site_id: str, version: str, tasks: list[Task], *, phase: str, local: bool) -> RunSummary:
    model_ids = list(job.model_ids) or list(DEFAULT_SWARM)
    agent_kinds = [AgentKind(k) for k in job.agent_kinds] or list(DEFAULT_AGENTS)
    total = _grid_size(tasks, model_ids, agent_kinds)
    previous = job.live_preview
    job.live_preview = JobPreview(site_version=version, total=total, task_sample=[t.prompt for t in tasks[:4]],
                                  pages_scanned=previous.pages_scanned if previous and previous.site_version == version else 0,
                                  observations=previous.observations if previous and previous.site_version == version else [])
    _progress(job, phase, 0, total,
              f"{phase}: {len(tasks)} tasks x models {model_ids} x agents {[k.value for k in agent_kinds]} "
              f"= {total} episodes ({'local' if local else 'modal'})")
    stop = lambda: None  # noqa: E731
    if local:
        base, stop = serve_site_locally()
        site_url = f"{base}/s/{site_id}/{version}/"
    else:
        site_url = urls.site_url(site_id, version)
    _progress(job, log_line=f"site served at {site_url}")
    counter = {"n": 0}
    results: list[PreviewAttempt] = []
    task_of = {t.id: t for t in tasks}

    def on_episode(ep: Episode) -> None:
        counter["n"] += 1
        job.swarm_spent_usd += ep.cost_usd
        results.append(attempt(ep, task_of))
        update_attempts(job.live_preview, results)
        status = "ok  " if ep.success else f"FAIL[{ep.failure_mode}]"
        kind = ep.agent_kind.value if hasattr(ep.agent_kind, "value") else ep.agent_kind
        _progress(job, done=counter["n"],
                  log_line=f"{counter['n']}/{total} {status} {ep.model_id} {kind} {ep.task_id} "
                           f"steps={ep.n_steps} {ep.duration_s:.0f}s ${ep.cost_usd:.4f}")

    kwargs: dict[str, Any] = {}
    if job.budget_usd is not None:
        kwargs["budget_usd"] = max(0.0, job.budget_usd - job.swarm_spent_usd)
    try:
        run = run_swarm(site_id, version, tasks, model_ids, agent_kinds, site_url=site_url, local=local,
                        on_episode=on_episode, **kwargs)
    finally:
        try:
            stop()
        except Exception:  # noqa: BLE001
            pass
    job.run_ids.append(run.run_id)
    job.site_id, job.site_version = site_id, version
    o = run.overall
    _progress(job, done=total, log_line=f"run {run.run_id}: {100 * o.success_rate:.0f}% success over {o.episodes} "
                                         f"episodes, avg {o.avg_steps:.1f} steps, total ${o.total_cost_usd:.2f}")
    return run


def _findings_phase(job: Job, run: RunSummary, tasks: list[Task], baseline: RunSummary | None = None) -> None:
    _progress(job, "Writing findings")
    episodes = store.load_episodes(run.run_id)
    job.findings = write_findings(run, episodes, tasks, baseline=baseline)
    _progress(job, log_line="findings written")


# --------------------------------------------------------------------------- job types

def _run_intake(job: Job, *, local: bool) -> None:
    if not job.url:
        raise ValueError("intake job needs a url")
    job.live_preview = JobPreview()
    _progress(job, "Mirroring site", 0, 0, f"Mirroring site {job.url}")
    last_page_update = 0.0

    def on_page(path: str, html: bytes) -> None:
        nonlocal last_page_update
        preview = job.live_preview
        preview.pages_scanned += 1
        preview.observations = (preview.observations + inspect_page(path, html))[:8]
        if preview.pages_scanned == 1 or time.monotonic() - last_page_update >= 1:
            _progress(job, log_line=f"Read {preview.pages_scanned} page(s); latest: {path}")
            last_page_update = time.monotonic()

    sv, report = mirror_to_store(job.url, site_id=job.site_id, on_page=on_page)
    job.live_preview.pages_scanned = len(report.pages)
    job.site_id, job.site_version = sv.site_id, sv.version
    msg = (f"mirrored {len(report.pages)} pages and {len(report.assets)} assets into {sv.site_id}/{sv.version}"
           + (f"; {len(report.errors)} fetch errors" if report.errors else "")
           + (f"; {len(report.skipped)} skipped" if report.skipped else "")
           + (f"; {report.unresolved_links} unresolved links" if report.unresolved_links else "")
           + ("; site ships abtract-tasks.json" if report.tasks_file else ""))
    _progress(job, log_line=msg)
    for e in report.errors[:5]:
        _progress(job, log_line=f"  mirror: {e}")

    _progress(job, "Choosing tasks")
    tasks, how = pick_tasks(sv.site_id, sv.version, source_url=job.url)
    _progress(job, log_line=f"{len(tasks)} tasks ({how}): " + ", ".join(t.id for t in tasks[:8])
              + (" ..." if len(tasks) > 8 else ""))

    run = _run_swarm_phase(job, sv.site_id, sv.version, tasks, phase="Running swarm", local=local)
    _findings_phase(job, run, tasks)


def _latest_run_for(site_id: str, version: str) -> RunSummary | None:
    runs = [r for r in store.list_runs() if r.site_id == site_id and r.site_version == version and r.finished_at]
    return runs[-1] if runs else None


def _run_loop(job: Job, *, local: bool) -> None:
    if not job.site_id:
        raise ValueError("loop job needs a site_id")
    site_id = job.site_id
    versions = store.list_versions(site_id)
    version = job.site_version or (versions[-1].version if versions else "v0")
    if not store.site_dir(site_id, version).is_dir():
        raise FileNotFoundError(f"site version {site_id}/{version} is not in the store")
    tasks = store.load_site_tasks(site_id)
    if not tasks:
        tasks, how = pick_tasks(site_id, version, source_url=job.url)
        _progress(job, log_line=f"{len(tasks)} tasks ({how})")

    # baseline: the run the loop starts from (the intake run, normally)
    baseline: RunSummary | None = None
    if job.run_ids:
        try:
            baseline = store.load_run(job.run_ids[-1])
        except Exception:  # noqa: BLE001
            baseline = None
    if baseline is None or baseline.site_id != site_id or baseline.site_version != version:
        baseline = _latest_run_for(site_id, version)
    if baseline is None:
        baseline = _run_swarm_phase(job, site_id, version, tasks, phase=f"Running swarm on {version} (baseline)", local=local)
    else:
        job.site_version = version
        _progress(job, log_line=f"baseline: run {baseline.run_id} on {version} "
                                f"({100 * baseline.overall.success_rate:.0f}% success)")

    last_run = baseline
    job.baseline_run_id = baseline.run_id
    _progress(job, log_line=f"comparison baseline: {baseline.run_id}")
    for i in range(max(1, job.iterations)):
        if job.budget_usd is not None and job.swarm_spent_usd >= job.budget_usd:
            raise RuntimeError("swarm budget exhausted; no further optimization iteration started")
        _progress(job, f"Optimizing {version}", i, job.iterations,
                  f"Optimizing {version} from run {last_run.run_id} (iteration {i + 1}/{job.iterations})")
        sv = optimize_site(site_id, version, last_run.run_id, local=local)
        _progress(job, log_line=f"{sv.version} written (changed: {', '.join(sv.changed_files) or 'nothing'})")
        note = sv.notes.strip().splitlines()[0] if sv.notes.strip() else ""
        if note:
            _progress(job, log_line=f"  optimizer: {note[:300]}")
        version = sv.version
        last_run = _run_swarm_phase(job, site_id, version, tasks, phase=f"Running swarm on {version}", local=local)
        delta = 100 * (last_run.overall.success_rate - baseline.overall.success_rate)
        _progress(job, log_line=f"{version} vs {baseline.site_version}: success {delta:+.0f} pts")
    _findings_phase(job, last_run, tasks, baseline=baseline)


# --------------------------------------------------------------------------- entrypoints

def run_job_sync(job_id: str) -> Job:
    """Run a saved job to completion. Never raises; the returned/saved Job carries status done|failed."""
    store.reload()
    job = store.load_job(job_id)
    job.status = "running"
    job.error = None
    _progress(job, log_line=f"job {job.id} ({job.type}) started")
    local = modal.is_local()
    try:
        if job.type == "intake":
            _run_intake(job, local=local)
        elif job.type == "loop":
            _run_loop(job, local=local)
        else:
            raise ValueError(f"unknown job type {job.type!r}")
        job.status = "done"
        _progress(job, "Done", log_line="done")
    except Exception as e:  # noqa: BLE001
        job.status = "failed"
        job.error = f"{type(e).__name__}: {e}"
        tb = traceback.format_exc().strip().splitlines()
        _progress(job, log_line=f"FAILED in phase '{job.phase}': {job.error}")
        for line in tb[-6:]:
            job.log.append("    " + line)
        try:
            store.save_job(job)
            store.commit()
        except Exception:  # noqa: BLE001
            pass
    return job


def start_job(job: Job) -> Job:
    """Persist the job and run it in the background. Inside Modal -> run_job.spawn; locally -> daemon thread."""
    job.status = "queued"
    store.save_job(job)
    store.commit()
    if not modal.is_local():
        try:
            run_job.spawn(job.id)  # hydrated from the deployed app's layout (same app, see App._init_container)
        except Exception:  # noqa: BLE001  e.g. this module was not part of the deployed layout: look it up by name
            modal.Function.from_name(APP_NAME, "run_job").spawn(job.id)
    else:
        threading.Thread(target=run_job_sync, args=(job.id,), daemon=True, name=f"abtract-job-{job.id}").start()
    return job


@app.function(image=base_image, volumes=volumes, secrets=secrets, timeout=3600)
def run_job(job_id: str) -> None:
    run_job_sync(job_id)
