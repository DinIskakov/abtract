"""Filesystem-backed result store. Locally this is ./data; on Modal it is the mounted Volume at /data.

Layout is documented in abtract/schemas.py. Callers running inside Modal must call `commit()` after writes
so other containers (dashboard, optimizer) can see them.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from pathlib import Path

from abtract.config import settings
from abtract.schemas import Episode, Job, RunSummary, SiteEvent, SiteVersion, Task

_SAFE = re.compile(r"[^A-Za-z0-9_.-]")


def _safe(s: str) -> str:
    safe = _SAFE.sub("_", s)
    return "_" if safe in ("", ".", "..") else safe


def root() -> Path:
    return Path(settings.data_dir)


def _write_json(path: Path, text: str) -> None:
    """Readers polling jobs/runs see a complete JSON document, never an in-progress write."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, suffix=".tmp", delete=False) as f:
        tmp = Path(f.name)
        try:
            f.write(text)
            f.close()
            os.replace(tmp, path)
        finally:
            tmp.unlink(missing_ok=True)


# --------------------------------------------------------------------------- sites

def site_dir(site_id: str, version: str) -> Path:
    return root() / "sites" / _safe(site_id) / _safe(version)


def versions_path(site_id: str) -> Path:
    return root() / "sites" / _safe(site_id) / "versions.json"


def list_versions(site_id: str) -> list[SiteVersion]:
    p = versions_path(site_id)
    if not p.exists():
        return []
    return [SiteVersion(**v) for v in json.loads(p.read_text())]


def list_sites() -> list[str]:
    d = root() / "sites"
    return sorted(p.name for p in d.iterdir() if p.is_dir()) if d.exists() else []


def register_version(v: SiteVersion) -> None:
    versions = [x for x in list_versions(v.site_id) if x.version != v.version]
    versions.append(v)
    versions.sort(key=lambda x: x.created_at)
    p = versions_path(v.site_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    _write_json(p, json.dumps([x.model_dump() for x in versions], indent=2))


def import_site(site_id: str, version: str, src: Path, *, parent: str | None = None, notes: str = "") -> SiteVersion:
    """Copy a directory of site files into the store as a new version."""
    dst = site_dir(site_id, version)
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)
    files = sorted(str(p.relative_to(dst)) for p in dst.rglob("*") if p.is_file())
    v = SiteVersion(site_id=site_id, version=version, parent=parent, notes=notes, changed_files=files)
    register_version(v)
    return v


def next_version(site_id: str) -> str:
    nums = [int(v.version[1:]) for v in list_versions(site_id) if re.fullmatch(r"v\d+", v.version)]
    return f"v{(max(nums) + 1) if nums else 0}"


# --------------------------------------------------------------------------- runs & episodes

def run_dir(run_id: str) -> Path:
    return root() / "runs" / _safe(run_id)


def save_run(run: RunSummary) -> None:
    d = run_dir(run.run_id)
    d.mkdir(parents=True, exist_ok=True)
    _write_json(d / "run.json", run.model_dump_json(indent=2))


def load_run(run_id: str) -> RunSummary:
    return RunSummary.model_validate_json((run_dir(run_id) / "run.json").read_text())


def list_runs() -> list[RunSummary]:
    d = root() / "runs"
    if not d.exists():
        return []
    runs = []
    for p in d.iterdir():
        f = p / "run.json"
        if f.exists():
            try:
                runs.append(RunSummary.model_validate_json(f.read_text()))
            except Exception:  # noqa: BLE001  half-written file
                continue
    return sorted(runs, key=lambda r: r.created_at)


def save_episode(ep: Episode) -> Path:
    d = run_dir(ep.run_id) / "episodes"
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{_safe(ep.id)}.json"
    _write_json(p, ep.model_dump_json(indent=2))
    return p


def load_episodes(run_id: str) -> list[Episode]:
    d = run_dir(run_id) / "episodes"
    if not d.exists():
        return []
    eps = []
    for p in sorted(d.glob("*.json")):
        try:
            eps.append(Episode.model_validate_json(p.read_text()))
        except Exception:  # noqa: BLE001
            continue
    return eps


def screenshot_dir(run_id: str, episode_id: str) -> Path:
    d = run_dir(run_id) / "screenshots" / _safe(episode_id)
    d.mkdir(parents=True, exist_ok=True)
    return d


# --------------------------------------------------------------------------- site events

def events_path(site_id: str, version: str) -> Path:
    return root() / "events" / _safe(site_id) / f"{_safe(version)}.jsonl"


def append_event(ev: SiteEvent) -> None:
    p = events_path(ev.site_id, ev.version)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a") as f:
        f.write(ev.model_dump_json() + "\n")


def read_events(site_id: str, version: str, episode_id: str | None = None) -> list[SiteEvent]:
    p = events_path(site_id, version)
    if not p.exists():
        return []
    out = []
    for line in p.read_text().splitlines():
        if not line.strip():
            continue
        ev = SiteEvent.model_validate_json(line)
        if episode_id is None or ev.episode_id == episode_id:
            out.append(ev)
    return out


# --------------------------------------------------------------------------- Modal volume sync

def commit() -> None:
    """Persist writes when running inside Modal. No-op locally."""
    try:
        from abtract.modal_app import data_volume, running_on_modal

        if running_on_modal():
            data_volume.commit()
    except Exception:  # noqa: BLE001
        pass


def reload() -> None:
    """See other containers' writes when running inside Modal. No-op locally."""
    try:
        from abtract.modal_app import data_volume, running_on_modal

        if running_on_modal():
            data_volume.reload()
    except Exception:  # noqa: BLE001
        pass


# --------------------------------------------------------------------------- jobs

def jobs_dir() -> Path:
    d = root() / "jobs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_job(job: "Job") -> None:
    import time as _time

    job.updated_at = _time.time()
    _write_json(jobs_dir() / f"{_safe(job.id)}.json", job.model_dump_json(indent=2))


def load_job(job_id: str) -> "Job":
    from abtract.schemas import Job

    return Job.model_validate_json((jobs_dir() / f"{_safe(job_id)}.json").read_text())


def list_jobs() -> list["Job"]:
    from abtract.schemas import Job

    out = []
    for p in jobs_dir().glob("*.json"):
        try:
            out.append(Job.model_validate_json(p.read_text()))
        except Exception:  # noqa: BLE001
            continue
    return sorted(out, key=lambda j: j.created_at)


# --------------------------------------------------------------------------- per-site task lists (intake / loop jobs)

def site_tasks_path(site_id: str) -> Path:
    return root() / "sites" / _safe(site_id) / "tasks.json"


def save_site_tasks(site_id: str, tasks: list["Task"]) -> Path:
    """Persist the task list an intake job chose for a site so later loop jobs reuse the same tasks."""
    p = site_tasks_path(site_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    _write_json(p, json.dumps([t.model_dump(mode="json") for t in tasks], indent=2))
    return p


def load_site_tasks(site_id: str) -> list["Task"] | None:
    """The tasks saved by save_site_tasks, or None when the site has none yet."""
    from abtract.schemas import Task

    p = site_tasks_path(site_id)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text())
    except ValueError:
        return None
    if isinstance(data, dict):
        data = data.get("tasks", [])
    return [Task(**t) for t in data]
