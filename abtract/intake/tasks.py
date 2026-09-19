"""Choose the tasks an intake job runs against a freshly mirrored site.

    pick_tasks(site_id, version, source_url=...) -> (tasks, how)   how: "site-provided" | "gemini" | "generic"

Order of preference:
  1. <site dir>/abtract-tasks.json  (a site that ships its own checkable tasks, e.g. our demo site)
  2. Gemini writes tasks from the site files (abtract.optimizer.task_gen) when a key is configured
  3. a generic set of url-kind navigation tasks with loose patterns that fit most marketing sites
The chosen list is persisted to sites/<site_id>/tasks.json (store.save_site_tasks) so loop jobs reuse it.
"""
from __future__ import annotations

import json

from abtract import store
from abtract.config import settings
from abtract.schemas import Task, TaskKind

TASKS_FILE = "abtract-tasks.json"

GENERIC_TASKS: list[dict] = [
    {"id": "g01_pricing", "prompt": "Find the pricing page of this site and stop there.",
     "expected_url_pattern": r"pric|plans?", "tags": ["navigation", "pricing"]},
    {"id": "g02_docs", "prompt": "Find the documentation (docs or guides) section of this site and stop on it.",
     "expected_url_pattern": r"docs?|documentation|guides?", "tags": ["navigation", "docs"]},
    {"id": "g03_contact", "prompt": "Find the page where you can contact this company or get support, and stop there.",
     "expected_url_pattern": r"contact|support|help", "tags": ["navigation", "contact"]},
    {"id": "g04_signup", "prompt": "Find the page where a new user signs up, registers or gets started, and stop there.",
     "expected_url_pattern": r"sign-?up|register|get-?started|start|waitlist|trial", "tags": ["navigation", "signup"]},
    {"id": "g05_about", "prompt": "Find the page that describes the company or the team behind this site, and stop there.",
     "expected_url_pattern": r"about|company|team", "tags": ["navigation", "about"]},
    {"id": "g06_blog", "prompt": "Find the blog, changelog or news section of this site and stop on it.",
     "expected_url_pattern": r"blog|changelog|news|releases?", "tags": ["navigation", "blog"]},
]


def generic_tasks() -> list[Task]:
    return [Task(kind=TaskKind.url, max_steps=10, trap="generic", **t) for t in GENERIC_TASKS]


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
    tasks: list[Task] = []
    for t in data if isinstance(data, list) else []:
        try:
            tasks.append(Task(**t))
        except Exception:  # noqa: BLE001  one malformed task should not sink the file
            continue
    return tasks


def pick_tasks(site_id: str, version: str, *, source_url: str | None = None, n_generated: int = 8,
               persist: bool = True) -> tuple[list[Task], str]:
    """Return (tasks, how). `source_url` is informational only (kept for the log / future heuristics)."""
    tasks = _site_provided(site_id, version)
    how = "site-provided"
    if not tasks and settings.gemini_api_key:
        try:
            from abtract.optimizer.task_gen import generate_tasks

            tasks = generate_tasks(site_id, version, n=n_generated)
            how = "gemini"
        except Exception:  # noqa: BLE001  fall through to the generic set
            tasks = []
    if not tasks:
        tasks = generic_tasks()
        how = "generic"
    if persist:
        store.save_site_tasks(site_id, tasks)
        store.commit()
    return tasks, how
