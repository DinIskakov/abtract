"""Gemini reads a site version plus the swarm's failures and writes a new version.

    build_context()     agent-perception primer + metric tables + failed traces + the site's text files
    propose_rewrite()   Gemini -> {"notes": ..., "files": {path: full content}, "deleted": [...]}
    apply_rewrite()     copy parent -> new version dir, write files, validate (check_site.py, in a modal.Sandbox
                        when not local), one LLM fix round on failure, register the SiteVersion
    optimize_site()     the three above; `optimize_site_remote` is the Modal function wrapper.

`chat` is imported into this module's namespace so tests can monkeypatch `app.optimizer.rewrite.chat`.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from app import store
from app.metrics.score import per_model_agent, relative_path
from app.modal_app import APP_NAME, DATA_DIR, app, base_image, running_on_modal, sandbox_image, secrets, volumes
from app.models.llm import ChatMessage, chat, extract_json  # noqa: F401  (chat is patched in tests)
from app.models.registry import get_model
from app.optimizer import check_site as check_site_module
from app.schemas import Episode, MetricBlock, RunSummary, SiteVersion, Task

OPTIMIZER_MODEL = os.environ.get("ABTRACT_OPTIMIZER_MODEL", "").strip() or "gemini-flash"  # "mock" = offline smoke
TEXT_EXTS = {".html", ".htm", ".css", ".js", ".mjs", ".json", ".txt", ".md", ".svg", ".xml"}
FILE_CHAR_CAP = 12_000
CONTEXT_CHAR_CAP = 250_000
MAX_FAILED_EPISODES_PER_TASK = 3
TRACE_TAIL_STEPS = 6

AGENT_PRIMER = """\
# How each kind of AI agent perceives a web page

- text agent: plain HTTP GET, converts raw HTML to text. Does NOT run JavaScript, so anything injected or fetched by JS
  is invisible and JS-only buttons do nothing. It DOES see text that CSS hides (display:none, visibility:hidden,
  off-screen), so hidden or contradictory text confuses it. Links are seen only by their anchor text and href; images,
  canvas, CSS pseudo-content (::before/::after) and icons are invisible. Forms are submitted by POSTing the named fields.
- dom agent: a real browser (Playwright). Observes the visible innerText plus a numbered list of interactive elements
  (links, buttons, inputs, selects) with their labels/names. Runs JavaScript. Cannot see CSS pseudo-element content,
  canvas drawings, or images. Elements without an accessible name (unlabeled inputs, icon-only buttons, divs with
  onclick) are hard or impossible for it to use. Overlays/modals that intercept clicks make it fail.
- vision agent: a real browser, observes screenshots with numbered labels on interactive elements. Can read text in
  canvas/images and pseudo-content, but low-contrast or tiny text, content below the fold, cookie banners and
  click-blocking overlays cause failures. It also needs accessible names to type into the right field.

Agents succeed when the facts are in server-rendered HTML as real text, the structure uses semantic elements
(<table>, <label for>, <button>, <select>, <a> with descriptive anchor text), nothing blocks clicks, and the same
fact is stated once, consistently, everywhere.
"""

REWRITE_RULES = """\
You are rewriting a static website so that AI agents (text / DOM / vision, described above) succeed at their tasks
more often, in fewer steps, at lower cost. Human visitors must not notice a downgrade.

Hard rules:
1. Keep the visual design and ALL content and facts. Prices, limits, names, numbers, wording of facts must not change.
   You may add clarifying text (e.g. a real <table> that repeats data that was only in a canvas or image).
2. Links stay RELATIVE (e.g. "pricing.html", "../index.html"). Never start a link with "/" or a host name.
3. Do not rename, move or delete pages. Do not change file names.
4. Keep every `api/...` endpoint name and every form/payload field name exactly as they are (the server records them).
5. Only return files you changed; each returned file must be its COMPLETE new content (no diffs, no ellipses, no
   markdown fences). Files you do not return are kept as they are.
6. Prefer server-rendered static HTML over JS-injected content: if content is built or fetched by JavaScript, put the
   same content directly in the HTML too (keep the JS if you like).
7. Use real semantic elements: <table> for tabular data, <label for=...> on every input, <button>/<a> with descriptive
   text (not "click here" / icon-only), <select> for choices, <nav> with plain <a> links.
8. No click-blocking overlays, modals, cookie walls or delayed pop-ups; if one exists, remove it or make it dismissed
   by default and non-blocking.
9. No content that exists only in CSS pseudo-elements (::before/::after content), canvas, SVG text or images: add the
   same data as real text / a table next to it.
10. No hidden text that contradicts visible text (display:none, visibility:hidden, aria-hidden, off-screen, comments).
    Delete stale or contradictory hidden content; do not add any.
11. Explain briefly in "notes" what you changed and why, referring to the failures, for a dashboard reader.

Return ONLY JSON of this exact shape:
{"notes": "<what changed and why>", "files": {"relative/path.html": "<FULL new file content>", ...}, "deleted": []}
"""


# --------------------------------------------------------------------------- context


def site_files(site_dir: Path, *, cap: int | None = FILE_CHAR_CAP) -> dict[str, str]:
    """relative path -> text of every text-like file under site_dir (sorted, each truncated to `cap` chars)."""
    out: dict[str, str] = {}
    for p in sorted(site_dir.rglob("*")):
        if not p.is_file() or p.suffix.lower() not in TEXT_EXTS:
            continue
        try:
            text = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if cap and len(text) > cap:
            text = text[:cap] + f"\n... [truncated, {len(text) - cap} more chars]"
        out[p.relative_to(site_dir).as_posix()] = text
    return out


def _fmt_block(name: str, b: MetricBlock) -> str:
    modes = ", ".join(f"{k}={v}" for k, v in b.failure_modes.items()) or "-"
    return (
        f"| {name} | {b.episodes} | {100 * b.success_rate:.0f}% | {b.avg_steps:.1f} | {b.avg_duration_s:.1f}s "
        f"| ${b.avg_cost_usd:.4f} | {modes} |"
    )


def metrics_tables(run: RunSummary, episodes: list[Episode]) -> str:
    hdr = "| group | episodes | success | avg steps | avg time | avg cost | failure modes |\n|---|---|---|---|---|---|---|"
    lines = [
        f"# Swarm results for {run.site_id}/{run.site_version} (run {run.run_id})",
        "",
        "## Overall",
        hdr,
        _fmt_block("all", run.overall),
        "",
        "## Per model x agent",
        hdr,
    ]
    lines += [_fmt_block(f"{m} / {a}", b) for (m, a), b in per_model_agent(episodes).items()]
    lines += ["", "## Per agent kind", hdr] + [_fmt_block(k, b) for k, b in run.per_agent.items()]
    tasks = {t.id: t for t in run.tasks}
    lines += ["", "## Per task", hdr]
    for tid, b in run.per_task.items():
        t = tasks.get(tid)
        label = f"{tid} ({t.kind.value}{', trap=' + t.trap if t and t.trap else ''})" if t else tid
        lines.append(_fmt_block(label, b))
    if run.per_trap:
        lines += ["", "## Per trap", hdr] + [_fmt_block(k, b) for k, b in run.per_trap.items()]
    return "\n".join(lines)


def _trunc(s: Any, n: int) -> str:
    s = "" if s is None else str(s).replace("\n", " ")
    return s if len(s) <= n else s[: n - 3] + "..."


def _expected(task: Task) -> str:
    if task.kind.value == "answer":
        return f"answer {task.expected_answer!r}" + (f" (aliases {task.answer_aliases})" if task.answer_aliases else "")
    if task.kind.value == "url":
        return f"end on a page whose path matches /{task.expected_url_pattern}/"
    m = f" with {task.expected_event_match}" if task.expected_event_match else ""
    return f"site records event {task.expected_event!r}{m}"


def _files_touched(ep: Episode) -> set[str]:
    out = set()
    for s in ep.steps:
        for u in (s.url, s.action.url):
            if not u:
                continue
            p = relative_path(u, ep.site_id, ep.site_version)
            if not p or p.endswith("/"):
                p += "index.html"
            out.add(p)
    return out


def failure_section(run: RunSummary, episodes: list[Episode]) -> tuple[str, set[str]]:
    """Failed episodes per task (truncated traces). Also returns the site files those traces visited."""
    lines: list[str] = ["# Failures (what the agents tried, up to 3 per task)"]
    referenced: set[str] = set()
    for task in run.tasks:
        failed = [e for e in episodes if e.task_id == task.id and not e.success]
        if not failed:
            continue
        total = sum(1 for e in episodes if e.task_id == task.id)
        lines += [
            "",
            f"## Task {task.id} [{task.kind.value}{', trap=' + task.trap if task.trap else ''}] "
            f"- {len(failed)}/{total} failed",
            f"Prompt: {task.prompt}",
            f"Expected: {_expected(task)}",
        ]
        # prefer a mix of agent kinds so the optimizer sees different perceptions
        failed.sort(key=lambda e: (e.agent_kind.value, e.model_id))
        picked: list[Episode] = []
        for kind in ("text", "dom", "vision"):
            picked += [e for e in failed if e.agent_kind.value == kind][:1]
        for e in failed:
            if len(picked) >= MAX_FAILED_EPISODES_PER_TASK:
                break
            if e not in picked:
                picked.append(e)
        for e in picked[:MAX_FAILED_EPISODES_PER_TASK]:
            referenced |= _files_touched(e)
            lines.append(
                f"- {e.model_id} / {e.agent_kind.value}: failure_mode={e.failure_mode} "
                f"steps={e.n_steps} judge={_trunc(e.judge_reason, 200)}"
                + (f" error={_trunc(e.error, 200)}" if e.error else "")
                + (f" final_answer={_trunc(e.final_answer, 120)!r}" if e.final_answer else "")
            )
            for s in e.steps[-TRACE_TAIL_STEPS:]:
                act = s.action.model_dump(exclude_none=True)
                lines.append(
                    f"    {s.index}. at {_trunc(relative_path(s.url, e.site_id, e.site_version) or '/', 60)} "
                    f"thought={_trunc(s.thought, 160)!r} action={_trunc(json.dumps(act), 160)}"
                    + (f" ERROR={_trunc(s.error, 120)}" if s.error else "")
                )
    if len(lines) == 1:
        lines.append("(no failures)")
    return "\n".join(lines), referenced


def build_context(site_id: str, version: str, run: RunSummary, episodes: list[Episode]) -> str:
    parts = [AGENT_PRIMER, metrics_tables(run, episodes)]
    failures, referenced = failure_section(run, episodes)
    parts.append(failures)
    files = site_files(store.site_dir(site_id, version))
    budget = CONTEXT_CHAR_CAP - sum(len(p) for p in parts) - 2_000
    ordered = sorted(files, key=lambda p: (p not in referenced, not p.endswith(".html"), p))
    included, skipped = [], []
    for path in ordered:
        chunk = f"\n\n### FILE: {path}\n```\n{files[path]}\n```"
        if len(chunk) <= budget:
            included.append(chunk)
            budget -= len(chunk)
        else:
            skipped.append(path)
    site_part = f"# Site files for {site_id}/{version} (paths relative to the site root)" + "".join(included)
    if skipped:
        site_part += "\n\n(omitted for size, unchanged: " + ", ".join(skipped) + ")"
    parts.append(site_part)
    return "\n\n".join(parts)


# --------------------------------------------------------------------------- proposal


def _strip_fence(s: str) -> str:
    s = s.strip("\n")
    if s.lstrip().startswith("```"):
        s = s.lstrip()
        s = s.split("\n", 1)[1] if "\n" in s else ""
        if s.rstrip().endswith("```"):
            s = s.rstrip()[:-3]
    return s


def _safe_rel(path: str) -> str | None:
    p = path.strip().replace("\\", "/")
    while p.startswith("./") or p.startswith("/"):
        p = p[2:] if p.startswith("./") else p[1:]  # "/pricing.html" and "./pricing.html" mean site-root-relative
    if not p or ".." in p.split("/") or ":" in p:
        return None
    return p


def _clean_proposal(data: dict[str, Any]) -> dict[str, Any]:
    files_in = data.get("files") or {}
    if not isinstance(files_in, dict):
        raise ValueError("proposal 'files' must be an object of path -> content")
    files: dict[str, str] = {}
    for path, content in files_in.items():
        rel = _safe_rel(str(path))
        if rel is None:
            continue
        if isinstance(content, (dict, list)):
            content = json.dumps(content, indent=2)
        files[rel] = _strip_fence(str(content))
    deleted = [d for d in (_safe_rel(str(x)) for x in (data.get("deleted") or [])) if d]
    notes = str(data.get("notes") or "").strip() or "(no notes from the optimizer)"
    return {"notes": notes, "files": files, "deleted": deleted}


def propose_rewrite(
    context: str,
    *,
    error_report: str | None = None,
    previous: dict[str, Any] | None = None,
    model_id: str = OPTIMIZER_MODEL,
) -> dict[str, Any]:
    """Ask Gemini for a rewrite proposal. With `error_report`, ask it to fix its previous proposal instead."""
    user = context
    if error_report:
        prev = json.dumps(previous or {}, indent=1)
        if len(prev) > 120_000:
            prev = prev[:120_000] + "\n... [truncated]"
        user += (
            "\n\n# Your previous proposal FAILED validation\n"
            f"Validator report:\n{error_report}\n\n"
            f"Your previous proposal was:\n{prev}\n\n"
            "Fix every reported problem (keep links relative, only link to files that exist, keep the file names) "
            "and return the corrected proposal as the same JSON shape, with FULL contents for every file you return."
        )
    messages = [ChatMessage(role="system", content=REWRITE_RULES), ChatMessage(role="user", content=user)]
    r = chat(get_model(model_id), messages, json_mode=True, max_output_tokens=32768, temperature=0.3)
    try:
        data = extract_json(r.text)
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(f"optimizer returned unparseable JSON ({e}); reply started: {r.text[:300]!r}") from e
    return _clean_proposal(data)


# --------------------------------------------------------------------------- apply + validate


def materialize(site_id: str, parent_version: str, new_version: str, proposal: dict[str, Any]) -> Path:
    """Copy parent -> new version dir (fresh), write proposal files, delete listed non-page files."""
    src = store.site_dir(site_id, parent_version)
    if not src.is_dir():
        raise FileNotFoundError(f"site version {site_id}/{parent_version} not found at {src}")
    dst = store.site_dir(site_id, new_version)
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)
    for rel, content in proposal["files"].items():
        p = dst / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    for rel in proposal["deleted"]:
        p = dst / rel
        if p.suffix.lower() in (".html", ".htm"):
            continue  # pages are never deleted
        if p.is_file():
            p.unlink()
    return dst


def _validate_local(site_dir: Path) -> str | None:
    cmd = [sys.executable, check_site_module.__file__, str(site_dir)]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if p.returncode == 0:
        return None
    return (p.stdout + p.stderr).strip() or f"check_site exited {p.returncode}"


def _validate_sandbox(site_id: str, version: str) -> str | None:
    import modal

    src = Path(check_site_module.__file__).read_text(encoding="utf-8")
    if running_on_modal() or getattr(app, "app_id", None) is None:
        sb_app = None if running_on_modal() else modal.App.lookup(APP_NAME, create_if_missing=True)
    else:
        sb_app = app
    sb = modal.Sandbox.create(app=sb_app, image=sandbox_image, volumes=volumes, timeout=120)
    try:
        f = sb.open("/root/check_site.py", "w")
        f.write(src)
        f.close()
        remote_dir = f"{DATA_DIR}/sites/{store._safe(site_id)}/{store._safe(version)}"
        proc = sb.exec("python", "/root/check_site.py", remote_dir, timeout=110)
        out = proc.stdout.read()
        err = proc.stderr.read()
        rc = proc.wait()
    finally:
        sb.terminate()
    if rc == 0:
        return None
    return (out + err).strip() or f"check_site exited {rc}"


def validate_version(site_id: str, version: str, *, local: bool) -> str | None:
    """None when the site passes check_site; otherwise the report text."""
    if local:
        return _validate_local(store.site_dir(site_id, version))
    store.commit()  # the sandbox reads the volume
    return _validate_sandbox(site_id, version)


def apply_rewrite(
    site_id: str,
    parent_version: str,
    proposal: dict[str, Any],
    *,
    local: bool = True,
    context: str | None = None,
    version: str | None = None,
) -> SiteVersion:
    """Write the proposal as a new version, validate it, retry once via Gemini when `context` is given,
    register and return it only if validation succeeds."""
    proposal = _clean_proposal(proposal)
    new_version = version or store.next_version(site_id)
    materialize(site_id, parent_version, new_version, proposal)
    report = validate_version(site_id, new_version, local=local)
    notes = proposal["notes"]
    if report and context is not None:
        try:
            fix = propose_rewrite(context, error_report=report, previous=proposal)
            merged = {
                "notes": fix["notes"] or notes,
                "files": {**proposal["files"], **fix["files"]},
                "deleted": sorted(set(proposal["deleted"]) | set(fix["deleted"])),
            }
            materialize(site_id, parent_version, new_version, merged)
            report2 = validate_version(site_id, new_version, local=local)
            proposal, notes = merged, merged["notes"]
            report = report2
        except Exception as e:  # noqa: BLE001  keep the first proposal, note the failure
            report = f"{report}\n\n(fix attempt failed: {type(e).__name__}: {e})"
    if report:
        shutil.rmtree(store.site_dir(site_id, new_version))
        store.commit()
        raise RuntimeError(f"Rewrite rejected after validation: {report}")
    changed = sorted(set(proposal["files"]) | set(proposal["deleted"]))
    sv = SiteVersion(site_id=site_id, version=new_version, parent=parent_version, notes=notes, changed_files=changed)
    store.register_version(sv)
    store.commit()
    return sv


def optimize_site(site_id: str, version: str, run_id: str, *, local: bool) -> SiteVersion:
    """One optimizer iteration: read run + episodes + site, ask Gemini, write & validate the next version."""
    store.reload()
    run = store.load_run(run_id)
    episodes = store.load_episodes(run_id)
    context = build_context(site_id, version, run, episodes)
    proposal = propose_rewrite(context)
    return apply_rewrite(site_id, version, proposal, local=local, context=context)


@app.function(image=base_image, volumes=volumes, secrets=secrets, timeout=1800)
def optimize_site_remote(site_id: str, version: str, run_id: str) -> dict:
    sv = optimize_site(site_id, version, run_id, local=False)
    return sv.model_dump(mode="json")
