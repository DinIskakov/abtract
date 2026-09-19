"""Choose the tasks an intake job runs against a freshly mirrored site.

    pick_tasks(site_id, version, source_url=...) -> (tasks, how)   how: "site-provided" | "gemini" | "site-derived"

Order of preference:
  1. <site dir>/abtract-tasks.json, validated against the captured website
  2. Gemini writes tasks from the site files (abtract.optimizer.task_gen) when a key is configured
  3. tasks derived from actual homepage text and links to captured pages
The chosen list is persisted to sites/<site_id>/tasks.json (store.save_site_tasks) so loop jobs reuse it.
"""
from __future__ import annotations

import json
import re
from collections import deque
from pathlib import Path
from urllib.parse import unquote, urlsplit

from bs4 import BeautifulSoup

from abtract import store
from abtract.config import settings
from abtract.optimizer.task_gen import task_site_files, validate_tasks
from abtract.schemas import Task, TaskKind

TASKS_FILE = "abtract-tasks.json"


def _site_provided(site_id: str, version: str) -> list[Task]:
    p = store.site_dir(site_id, version) / TASKS_FILE
    if not p.is_file():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except ValueError:
        return []
    if isinstance(data, dict):
        data = data.get("tasks", [])
    if not isinstance(data, list):
        return []
    return validate_tasks(data, task_site_files(p.parent), n=len(data))


def _link_target(root: Path, page: Path, href: str) -> Path | None:
    """Resolve an internal link using the same directory/.html aliases as the site server."""
    try:
        parts = urlsplit(href)
        if parts.scheme or parts.netloc or not parts.path:
            return None
        path = unquote(parts.path)
        target = ((root if path.startswith("/") else page.parent) / path.lstrip("/")).resolve()
        if not target.is_relative_to(root):
            return None
        if target.is_dir():
            target = target / "index.html"
        elif not target.is_file() and not path.endswith("/"):
            target = target.with_name(target.name + ".html")
        target = target.resolve()
        if target.is_relative_to(root) and target.is_file() and target.suffix.lower() in {".html", ".htm"}:
            return target
    except (ValueError, OSError):
        pass
    return None


def discovered_tasks(site_id: str, version: str, *, n: int = 8, quick: bool = False) -> list[Task]:
    """Build a bounded set from captured content; a broken or uncaptured link is never a destination."""
    if n <= 0:
        raise ValueError("task count must be positive")
    root = store.site_dir(site_id, version).resolve()
    home = root / "index.html"
    if not home.is_file():
        raise FileNotFoundError(f"no captured homepage under {root}")
    prefix = "quick" if quick else "discovered"
    soup = BeautifulSoup(home.read_bytes(), "html.parser")
    tasks: list[Task] = []
    heading = soup.find("h1")
    if heading and heading.get_text(" ", strip=True):
        tasks.append(Task(id=f"{prefix}_headline", kind="answer",
                          prompt="What is the main headline on the homepage?",
                          expected_answer=heading.get_text(" ", strip=True), max_steps=3))
    queue = deque([home])
    seen = {home}
    while queue and len(tasks) < n:
        page = queue.popleft()
        page_soup = soup if page == home else BeautifulSoup(page.read_bytes(), "html.parser")
        for link in page_soup.find_all("a", href=True):
            target = _link_target(root, page, str(link["href"]))
            if target is None or target in seen:
                continue
            seen.add(target)
            if not quick:
                queue.append(target)
            label = link.get_text(" ", strip=True) or str(link.get("aria-label") or "").strip()
            if not label:
                # An icon-only link can still lead to a page with an identifiable heading/title.
                destination = BeautifulSoup(target.read_bytes(), "html.parser")
                title = destination.find("h1") or destination.find("title")
                label = title.get_text(" ", strip=True) if title else ""
            if not label:
                continue
            path = target.relative_to(root).as_posix()
            routes = [path]
            if path.endswith(".html"):
                routes.append(path[:-5])
            if path.endswith("/index.html"):
                routes.extend([path[:-10], path[:-11]])
            pattern = "^(?:" + "|".join(re.escape(p) for p in routes) + r")(?:[?#].*)?$"
            tasks.append(Task(id=f"{prefix}_link_{len(seen) - 1}", kind="url", max_steps=6 if quick else 10,
                              prompt=f'Find the page linked as "{label[:120]}" on this site and stop there.',
                              expected_url_pattern=pattern, tags=["navigation"]))
            if len(tasks) >= n:
                break
    if not tasks:
        tasks = [Task(id=f"{prefix}_home", kind="url", prompt="Open the homepage and stop there.",
                      expected_url_pattern=r"^(?:index\.html)?(?:[?#].*)?$", max_steps=3)]
    return tasks


def pick_tasks(site_id: str, version: str, *, source_url: str | None = None, n_generated: int = 8,
               persist: bool = True) -> tuple[list[Task], str]:
    """Return (tasks, how), grounded in the captured site. `source_url` is informational only."""
    tasks = _site_provided(site_id, version)
    how = "site-provided"
    if not tasks and settings.gemini_api_key:
        try:
            from abtract.optimizer.task_gen import generate_tasks

            tasks = generate_tasks(site_id, version, n=n_generated)
            how = "gemini"
        except Exception:  # noqa: BLE001  fall through to deterministic site discovery
            tasks = []
    if not tasks:
        tasks = discovered_tasks(site_id, version, n=n_generated)
        how = "site-derived"
    if persist:
        store.save_site_tasks(site_id, tasks)
        store.commit()
    return tasks, how


def pick_quick_tasks(site_id: str, version: str) -> list[Task]:
    """Three short, checkable tasks, without waiting for task-generation inference.

    Preserve the full task file. The quick run records its own task subset and limits
    so later optimization can use exactly the same evaluation conditions.
    """
    tasks = _site_provided(site_id, version)
    if not tasks:
        tasks = discovered_tasks(site_id, version, n=3, quick=True)
    return [t.model_copy(update={"max_steps": min(t.max_steps, 6), "timeout_s": 60.0})
            for t in sorted(tasks, key=lambda t: (t.max_steps, t.kind == TaskKind.action))[:3]]
