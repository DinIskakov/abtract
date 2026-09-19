"""Gemini reads a site version and writes checkable tasks of all three kinds.

    generate_tasks(site_id, version, n=8) -> list[Task]

answer tasks quote facts that are literally on the site (expected_answer + aliases), url tasks point at real pages,
action tasks use the `api/<name>` forms found in the site with a concrete email. Every task is validated with
Task(**t) and cross-checked against the files (url targets exist, action endpoints exist); invalid ones are dropped.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from abtract import store
from abtract.models.llm import ChatMessage, chat, extract_json  # noqa: F401  (patchable)
from abtract.models.registry import get_model
from abtract.optimizer.rewrite import site_files
from abtract.schemas import Task, TaskKind

GENERATOR_MODEL = "gemini-flash"
_API_RE = re.compile(r"""(?:action\s*=\s*|fetch\(\s*|url\s*[:=]\s*|open\(\s*['"][A-Z]+['"]\s*,\s*)['"]([^'"]*api/[A-Za-z0-9_\-/]+)['"]""")
_NAME_RE = re.compile(r"""<(?:input|select|textarea)[^>]*\bname\s*=\s*['"]([^'"]+)['"]""", re.I)

RULES = """\
You write evaluation tasks for AI web agents against the static website given below. A task is something a real user
would ask an assistant to do on this site. Every task must be automatically checkable:

- kind "answer": the agent must report a fact. Give "expected_answer" EXACTLY as it appears on the site (a price,
  a number, a name, a limit) and 2-4 "answer_aliases" with other spellings ("$3.95", "3.95/hr", "3.95 per hour").
  The fact must be literally present in the HTML text below. Prefer facts that appear only on a sub-page or inside
  a table/list so the agent has to navigate.
- kind "url": the agent must end on a specific page. "expected_url_pattern" is a regex against the path relative to
  the site root (e.g. "^pricing(\\.html|/)?$" or "docs/quickstart"). The page MUST exist in the files below.
- kind "action": the agent must submit a form or press a button that the site records via an `api/<name>` request.
  "expected_event" is the endpoint name after `api/` (e.g. "waitlist_submit" for `api/waitlist_submit`), and
  "expected_event_match" is a subset of the submitted field names -> values, using concrete values that you put in the
  prompt (use the email agent@example.com and the company "Example Corp" when a form needs them). Only use endpoints
  and field names that appear in the site files.

Write prompts a human would write ("How much does an H100 cost per hour?", "Sign me up for the waitlist with
agent@example.com"), do not mention HTML, selectors or hints. Mix easy and hard tasks. Also set "trap" to a short
label of the site feature that makes the task hard for agents (e.g. "js_rendered_pricing", "canvas_chart",
"unlabeled_form", "overlay_modal", "hidden_stale_text", "icon_only_nav"), or null.

Return ONLY JSON: {"tasks": [ {"id": "t01_short_slug", "kind": ..., "prompt": ..., "expected_answer": ...,
"answer_aliases": [...], "expected_url_pattern": ..., "expected_event": ..., "expected_event_match": {...},
"max_steps": 15, "tags": [...], "trap": ...}, ... ]}
"""


def _pages(files: dict[str, str]) -> list[str]:
    return sorted(p for p in files if p.lower().endswith((".html", ".htm")))


def _api_endpoints(files: dict[str, str]) -> dict[str, set[str]]:
    """endpoint name -> field names seen in the same file (best effort)."""
    out: dict[str, set[str]] = {}
    for text in files.values():
        names = set(_NAME_RE.findall(text))
        for m in _API_RE.finditer(text):
            name = m.group(1).split("api/", 1)[1].strip("/")
            if name:
                out.setdefault(name, set()).update(names)
    return out


def _page_exists(pattern: str, pages: list[str]) -> bool:
    try:
        rx = re.compile(pattern)
    except re.error:
        return False
    for p in pages:
        cands = {p, "/" + p}
        if p.endswith("index.html"):
            d = p[: -len("index.html")]
            cands |= {d, d.rstrip("/"), "/" + d}
        if any(rx.search(c) for c in cands):
            return True
    return False


def validate_tasks(raw: list[dict[str, Any]], files: dict[str, str], *, n: int) -> list[Task]:
    pages = _pages(files)
    endpoints = _api_endpoints(files)
    corpus = "\n".join(files.values()).lower()
    tasks: list[Task] = []
    for i, t in enumerate(raw):
        try:
            t = dict(t)
            t.setdefault("id", f"t{i + 1:02d}")
            t["id"] = re.sub(r"[^A-Za-z0-9_.-]", "_", str(t["id"]))[:40]
            for k in ("answer_aliases", "tags"):
                if t.get(k) is None:
                    t[k] = []
            if t.get("expected_event_match") is None:
                t["expected_event_match"] = {}
            task = Task(**t)
        except Exception:  # noqa: BLE001
            continue
        if task.kind == TaskKind.answer:
            if not task.expected_answer:
                continue
            if task.expected_answer.lower() not in corpus and not any(a.lower() in corpus for a in task.answer_aliases):
                continue  # not a fact on the site
        elif task.kind == TaskKind.url:
            if not task.expected_url_pattern or not _page_exists(task.expected_url_pattern, pages):
                continue
        else:
            if not task.expected_event:
                continue
            task.expected_event = task.expected_event.split("api/", 1)[-1].strip("/")
            if endpoints and task.expected_event not in endpoints:
                continue
        if any(x.id == task.id for x in tasks):
            task.id = f"{task.id}_{i}"
        tasks.append(task)
        if len(tasks) >= n:
            break
    return tasks


def generate_tasks(site_id: str, version: str, n: int = 8, *, model_id: str = GENERATOR_MODEL,
                   site_dir: Path | None = None) -> list[Task]:
    site_dir = site_dir or store.site_dir(site_id, version)
    files = site_files(site_dir)
    if not files:
        raise FileNotFoundError(f"no site files under {site_dir}")
    endpoints = _api_endpoints(files)
    inventory = ["# Pages", *[f"- {p}" for p in _pages(files)], "", "# api endpoints found (name: field names)"]
    inventory += [f"- {k}: {sorted(v)}" for k, v in sorted(endpoints.items())] or ["- (none found)"]
    body = "\n\n".join(f"### FILE: {p}\n```\n{c}\n```" for p, c in files.items())
    user = (f"Write {n} tasks ({max(1, n // 2)} answer, {max(1, n // 4)} url, {max(1, n - n // 2 - n // 4)} action) "
            f"for site {site_id}/{version}.\n\n" + "\n".join(inventory) + "\n\n# Site files\n" + body)
    if len(user) > 250_000:
        user = user[:250_000] + "\n... [truncated]"
    r = chat(get_model(model_id), [ChatMessage(role="system", content=RULES), ChatMessage(role="user", content=user)],
             json_mode=True, max_output_tokens=8192, temperature=0.4)
    data = extract_json(r.text)
    raw = data.get("tasks") if isinstance(data, dict) else data
    if not isinstance(raw, list):
        raise RuntimeError(f"task generator returned no task list: {r.text[:200]!r}")
    tasks = validate_tasks(raw, files, n=n)
    if not tasks:
        raise RuntimeError("task generator produced no valid tasks")
    return tasks


def save_tasks(tasks: list[Task], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([t.model_dump(mode="json") for t in tasks], indent=2))
