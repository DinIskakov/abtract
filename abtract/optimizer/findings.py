"""Plain-language findings report for a swarm run, for the person who pasted the URL.

    write_findings(run, episodes, tasks, baseline=None) -> markdown (<= ~300 words rule-based, never raises)

Always rule-based (headline numbers, success by agent and by model, the 5 hardest tasks with their dominant failure
mode, and "what this suggests" bullets inferred from which agent kinds fail where). When a Gemini key is configured
(or ABTRACT_OPTIMIZER_MODEL=mock) a <=150-word "what's tripping agents and the top 3 fixes" paragraph from the model
is appended; any error there appends nothing.
"""
from __future__ import annotations

import os
from collections import Counter

from abtract.config import settings
from abtract.metrics.score import compare, metric_block
from abtract.models.llm import ChatMessage, chat  # noqa: F401  (chat is patchable in tests)
from abtract.models.registry import get_model
from abtract.optimizer.rewrite import OPTIMIZER_MODEL, failure_section, metrics_tables
from abtract.schemas import Episode, RunSummary, Task, TaskKind

MODE_LABEL = {
    "wrong_answer": "wrong answer", "wrong_page": "ended on the wrong page", "no_event": "form never submitted",
    "max_steps": "ran out of steps", "gave_up": "gave up", "error": "crashed", "timeout": "timed out",
}
LLM_SYSTEM = """\
You explain the results of an AI-agent usability test to the owner of a website, in plain English, without jargon.
The site was visited by three kinds of agents: a text agent (HTTP only, no JavaScript), a DOM agent (real browser,
reads the accessibility tree) and a vision agent (real browser, reads screenshots). Given the metrics and the failed
attempts below, write at most 150 words: one short paragraph titled "What's tripping agents on your site", then
"Top 3 fixes" as three numbered one-line items, concrete and specific to this site. No markdown headers, no preamble."""


def _pct(x: float) -> str:
    return f"{100 * x:.0f}%"


def _kind(e: Episode) -> str:
    return e.agent_kind.value if hasattr(e.agent_kind, "value") else str(e.agent_kind)


def _rate(eps: list[Episode]) -> float | None:
    return (sum(1 for e in eps if e.success) / len(eps)) if eps else None


def _evidence(failed: list[Episode]) -> str:
    """One judge reason or last-step error from the failures, trimmed."""
    for e in failed:
        for s in reversed(e.steps):
            if s.error:
                return f"error: {s.error}"[:140].replace("\n", " ")
        if e.judge_reason:
            return e.judge_reason[:140].replace("\n", " ")
        if e.error:
            return e.error[:140].replace("\n", " ")
    return ""


def _headline(run: RunSummary, episodes: list[Episode], tasks: list[Task]) -> list[str]:
    o = run.overall if run.overall.episodes else metric_block(episodes)
    n_models = len(run.model_ids or {e.model_id for e in episodes})
    n_agents = len(run.agent_kinds or {_kind(e) for e in episodes})
    grid = f"{n_models} model{'s' if n_models != 1 else ''} x {n_agents} agent kind{'s' if n_agents != 1 else ''} x {len(tasks)} task{'s' if len(tasks) != 1 else ''}"
    return [f"# Findings for {run.site_id}/{run.site_version}", "",
            f"**{_pct(o.success_rate)} of {o.episodes} attempts succeeded** ({grid}). "
            f"On average an attempt took {o.avg_steps:.1f} steps and {o.avg_duration_s:.0f} s and cost "
            f"${o.avg_cost_usd:.4f}; total spend ${o.total_cost_usd:.2f}."]


def _by(episodes: list[Episode], key, label: str) -> str:
    groups: dict[str, list[Episode]] = {}
    for e in episodes:
        groups.setdefault(key(e), []).append(e)
    parts = [f"{k} {_pct(_rate(v) or 0.0)} ({len(v)})" for k, v in sorted(groups.items())]
    return f"- By {label}: " + (" · ".join(parts) if parts else "-")


def _worst_tasks(episodes: list[Episode], tasks: list[Task], n: int = 5) -> list[str]:
    by_task: dict[str, list[Episode]] = {}
    for e in episodes:
        by_task.setdefault(e.task_id, []).append(e)
    task_of = {t.id: t for t in tasks}
    rows = []
    for tid, eps in by_task.items():
        failed = [e for e in eps if not e.success]
        if not failed:
            continue
        rows.append((len(failed) / len(eps), len(failed), tid, eps, failed))
    rows.sort(key=lambda r: (-r[0], -r[1], r[2]))
    out = ["", "## Hardest tasks"]
    for _, _, tid, eps, failed in rows[:n]:
        t = task_of.get(tid)
        mode, cnt = Counter(e.failure_mode or "unknown" for e in failed).most_common(1)[0]
        ev = _evidence(failed)
        kind = f"{t.kind.value}" + (f", trap: {t.trap}" if t and t.trap else "") if t else "?"
        prompt = (t.prompt if t else tid)
        prompt = prompt if len(prompt) <= 90 else prompt[:87] + "..."
        out.append(f"- **{tid}** ({kind}) failed {len(failed)}/{len(eps)}; mostly {MODE_LABEL.get(mode, mode)} ({cnt}). "
                   f"\"{prompt}\"" + (f" - {ev}" if ev else ""))
    if len(out) == 2:
        out.append("- none: every task succeeded at least once per attempt")
    return out


def _suggestions(episodes: list[Episode], tasks: list[Task]) -> list[str]:
    task_of = {t.id: t for t in tasks}
    by_task: dict[str, dict[str, list[Episode]]] = {}
    for e in episodes:
        by_task.setdefault(e.task_id, {}).setdefault(_kind(e), []).append(e)
    js_only, visual_only, vision_only_fail = [], [], []
    for tid, kinds in by_task.items():
        r = {k: _rate(v) for k, v in kinds.items()}
        text, dom, vision = r.get("text"), r.get("dom"), r.get("vision")
        if text == 0.0 and ((dom or 0) > 0 or (vision or 0) > 0):
            js_only.append(tid)
        if dom == 0.0 and (vision or 0) > 0:
            visual_only.append(tid)
        if vision == 0.0 and (dom or 0) > 0:
            vision_only_fail.append(tid)
    failed = [e for e in episodes if not e.success]
    modes = Counter(e.failure_mode or "unknown" for e in failed)
    n_fail = max(1, len(failed))
    out: list[str] = ["", "## What this suggests"]

    def tl(ids: list[str]) -> str:
        ids = sorted(ids)
        return ", ".join(ids[:4]) + (f" (+{len(ids) - 4})" if len(ids) > 4 else "")

    if js_only:
        out.append(f"- Text agents fail where browser agents succeed on {tl(js_only)}: that content only exists after "
                   "JavaScript runs. Put the same facts and links in the server-rendered HTML.")
    if visual_only:
        out.append(f"- The DOM agent fails where the vision agent succeeds on {tl(visual_only)}: the information is "
                   "visual-only (canvas, image, CSS-drawn). Add it as real text or a table as well.")
    if vision_only_fail:
        out.append(f"- The vision agent fails where the DOM agent succeeds on {tl(vision_only_fail)}: something in the "
                   "rendered page hides it (overlays, low contrast, below the fold, tiny text).")
    action_ids = [t.id for t in tasks if t.kind == TaskKind.action]
    action_eps = [e for e in episodes if e.task_id in set(action_ids)]
    if action_eps and _rate(action_eps) == 0.0:
        out.append("- Every form/button task failed: the forms are hard to operate. Label every input with <label for>, "
                   "use a real <button type=submit>, and make the submit endpoint a plain form action.")
    if modes.get("max_steps", 0) / n_fail >= 0.3:
        out.append(f"- {modes['max_steps']} attempts ran out of steps: navigation is unclear. Use a plain <nav> with "
                   "descriptive link text so agents find the right page quickly.")
    if modes.get("wrong_answer", 0) / n_fail >= 0.3:
        out.append(f"- {modes['wrong_answer']} attempts reported a wrong answer: facts are ambiguous, stale or stated "
                   "differently in different places (hidden text, tabs, footnotes). State each fact once, plainly.")
    if modes.get("gave_up", 0) / n_fail >= 0.3:
        out.append(f"- {modes['gave_up']} attempts gave up: agents could not find the content at all. Check that the "
                   "answer is visible as text on a page reachable from the home page.")
    if (modes.get("error", 0) + modes.get("timeout", 0)) / n_fail >= 0.3:
        out.append(f"- {modes.get('error', 0) + modes.get('timeout', 0)} attempts crashed or timed out: the site or the "
                   "agents were unreliable (slow pages, blocked requests). Re-run before drawing conclusions.")
    if not failed:
        out.append("- Nothing tripped the agents: every attempt succeeded. Optimize for fewer steps and lower cost next.")
    if len(out) == 2:
        out.append("- Failures are spread evenly across agent kinds and modes; look at the per-task traces in the "
                   "dashboard for specifics.")
    return out[:8]


def _baseline_line(baseline: RunSummary, run: RunSummary) -> list[str]:
    d = compare(baseline, run)["overall"]
    sr, st, co = d["success_rate"], d["avg_steps"], d["avg_cost_usd"]
    sign = "+" if sr["delta"] >= 0 else ""
    return ["", f"**Compared with {baseline.site_version}** (run {baseline.run_id}): success {_pct(sr['a'])} -> "
                f"{_pct(sr['b'])} ({sign}{100 * sr['delta']:.0f} pts), avg steps {st['a']:.1f} -> {st['b']:.1f}, "
                f"avg cost ${co['a']:.4f} -> ${co['b']:.4f}."]


def rule_based_findings(run: RunSummary, episodes: list[Episode], tasks: list[Task],
                        baseline: RunSummary | None = None) -> str:
    lines = _headline(run, episodes, tasks)
    if baseline is not None:
        lines += _baseline_line(baseline, run)
    lines += ["", _by(episodes, _kind, "agent"), _by(episodes, lambda e: e.model_id, "model")]
    lines += _worst_tasks(episodes, tasks)
    lines += _suggestions(episodes, tasks)
    return "\n".join(lines)


def _optimizer_model_id() -> str:
    return os.environ.get("ABTRACT_OPTIMIZER_MODEL", "").strip() or OPTIMIZER_MODEL


def llm_findings(run: RunSummary, episodes: list[Episode], *, model_id: str | None = None,
                 char_cap: int = 40_000) -> str | None:
    """Gemini's <=150-word take, or None. Uses only the metric tables and failed traces (no site files)."""
    model_id = model_id or _optimizer_model_id()
    failures, _ = failure_section(run, episodes)
    context = metrics_tables(run, episodes) + "\n\n" + failures
    if len(context) > char_cap:
        context = context[:char_cap] + "\n... [truncated]"
    msgs = [ChatMessage(role="system", content=LLM_SYSTEM),
            ChatMessage(role="user", content=f"Site: {run.site_id}/{run.site_version}\n\n{context}")]
    r = chat(get_model(model_id), msgs, max_output_tokens=600, temperature=0.3)
    text = (r.text or "").strip()
    return text or None


def write_findings(run: RunSummary, episodes: list[Episode], tasks: list[Task], *,
                   baseline: RunSummary | None = None) -> str:
    """Markdown findings for humans. Never raises."""
    try:
        text = rule_based_findings(run, episodes, tasks, baseline)
    except Exception as e:  # noqa: BLE001
        o = run.overall
        text = (f"# Findings for {run.site_id}/{run.site_version}\n\n{_pct(o.success_rate)} of {o.episodes} attempts "
                f"succeeded.\n\n(report generator failed: {type(e).__name__}: {e})")
    want_llm = bool(settings.gemini_api_key) or os.environ.get("ABTRACT_OPTIMIZER_MODEL", "").strip() == "mock"
    if want_llm and episodes:
        try:
            extra = llm_findings(run, episodes)
            if extra:
                text += "\n\n## In plain English\n\n" + extra
        except Exception:  # noqa: BLE001
            pass
    return text
