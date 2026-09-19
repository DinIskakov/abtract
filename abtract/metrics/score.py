"""Judge episodes and aggregate them into MetricBlocks.

judge()     decides success / failure_mode / judge_reason for one Episode against its Task.
aggregate() fills RunSummary.overall / per_model / per_agent / per_task / per_trap.
compare()   deltas between two RunSummaries (used by the loop's printed table).

Everything here is deterministic and offline except the optional Gemini fallback for `answer` tasks, which only
runs when the string match fails, `use_llm_judge=True` and GEMINI_API_KEY is set.
"""
from __future__ import annotations

import re
import time
from collections import Counter
from typing import Any
from urllib.parse import urlsplit

from abtract import store
from abtract.config import settings
from abtract.schemas import Episode, MetricBlock, RunSummary, Task, TaskKind

# failure modes an agent sets itself (before judging)
AGENT_FAILURE_MODES = {"gave_up", "max_steps", "error", "timeout"}

# words that carry no information when comparing answers ("$3.95/hr" == "3.95 per hour")
_NOISE_WORDS = {"per", "usd", "dollar", "dollars", "the", "a", "an",
                "is", "it", "its", "it's"}
_UNITS = {"hr": "hour", "hrs": "hour", "hours": "hour", "mo": "month", "months": "month",
          "seconds": "second", "sec": "second", "minutes": "minute", "mins": "minute", "days": "day"}
_PUNCT_TO_SPACE = re.compile(r"[\s$,/\\|;:!?()\[\]{}<>\"'`*_+=~^#&@%-]+")


# --------------------------------------------------------------------------- answer matching

def normalize_answer(s: str | None) -> str:
    """Normalize formatting while preserving decimal values and meaningful units."""
    if not s:
        return ""
    s = s.lower()
    s = _PUNCT_TO_SPACE.sub(" ", s)
    s = re.sub(r"(?<!\d)\.|\.(?!\d)", " ", s)
    words = [_UNITS.get(w, w) for w in s.split() if w not in _NOISE_WORDS]
    return " ".join(words)


def _contains(haystack: str, needle: str) -> bool:
    """needle appears in haystack at word boundaries (so '8' does not match '128')."""
    if not needle or not haystack:
        return False
    return re.search(r"(?<![\w.])" + re.escape(needle) + r"(?![\w.])", haystack) is not None


def answer_matches(answer: str | None, expected: str | None, aliases: list[str] | None = None) -> str | None:
    """Return the candidate that matched (for the judge_reason) or None."""
    ans = normalize_answer(answer)
    if not ans:
        return None
    # Ambiguous or negated statements need semantic judging rather than a substring pass.
    if re.search(r"\b(not|isn't|isn’t|either|or|maybe|perhaps)\b", (answer or "").lower()):
        return None
    units = {"hour", "month", "second", "minute", "day"}
    expected_units = set(normalize_answer(expected).split()) & units
    answer_units = set(ans.split()) & units
    if expected_units and answer_units and expected_units != answer_units:
        return None
    for cand in [expected, *(aliases or [])]:
        exp = normalize_answer(cand)
        if not exp:
            continue
        if _contains(ans, exp):
            return cand
    return None


def _llm_answer_judge(task: Task, answer: str) -> tuple[bool, str] | None:
    """Ask Gemini whether the answer states the same fact. Returns None when unavailable / failed."""
    if not settings.gemini_api_key:
        return None
    try:
        from abtract.models.llm import ChatMessage, chat, extract_json
        from abtract.models.registry import get_model

        prompt = (
            "You grade an AI agent's answer to a web task.\n"
            f"Task: {task.prompt}\n"
            f"Expected answer: {task.expected_answer!r}\n"
            f"Also acceptable: {task.answer_aliases!r}\n"
            f"Agent's answer: {answer!r}\n\n"
            "Does the agent's answer state the same fact as the expected answer (same value, units may differ "
            "in formatting)? Extra correct context is fine; a different value, a hedge between several values, "
            "or a missing value is wrong.\n"
            'Reply with JSON: {"correct": true|false, "reason": "<one sentence>"}'
        )
        r = chat(get_model("gemini-flash"), [ChatMessage(role="user", content=prompt)], json_mode=True,
                 max_output_tokens=256, temperature=0.0)
        data = extract_json(r.text)
        return bool(data.get("correct")), str(data.get("reason", ""))
    except Exception as e:  # noqa: BLE001  never let the judge crash a run
        return False, f"llm judge unavailable: {e}"


# --------------------------------------------------------------------------- url matching

_PREFIX_RE = re.compile(r"^s/[^/]+/[^/]+/")


def relative_path(url: str | None, site_id: str | None = None, version: str | None = None) -> str:
    """Path of `url` relative to the site root: no scheme/host, no `/s/{site_id}/{version}/` prefix,
    no leading slash, no query/fragment. 'https://x.modal.run/s/demo/v0/pricing/?a=1' -> 'pricing/'."""
    if not url:
        return ""
    parts = urlsplit(url.strip())
    path = parts.path if parts.scheme or parts.netloc else url.split("?", 1)[0].split("#", 1)[0]
    path = path.lstrip("/")
    if site_id and version:
        exact = f"s/{store._safe(site_id)}/{store._safe(version)}/"
        if path.startswith(exact):
            return path[len(exact):]
    return _PREFIX_RE.sub("", path, count=1)


def url_matches(pattern: str | None, url: str | None, site_id: str | None = None, version: str | None = None) -> bool:
    if not pattern:
        return False
    path = relative_path(url, site_id, version)
    try:
        return re.search(pattern, path) is not None or re.search(pattern, "/" + path) is not None
    except re.error:
        return pattern in path


# --------------------------------------------------------------------------- event matching

def _payload_matches(payload: dict[str, Any], expected: dict[str, Any]) -> bool:
    for k, v in (expected or {}).items():
        if k not in payload:
            return False
        if str(payload[k]).strip().lower() != str(v).strip().lower():
            return False
    return True


def find_matching_event(episode: Episode, task: Task):
    store.reload()  # see the site server's commits when on Modal (no-op locally)
    events = store.read_events(episode.site_id, episode.site_version, episode_id=episode.id)
    for ev in events:
        if ev.name == task.expected_event and _payload_matches(ev.payload, task.expected_event_match):
            return ev
    return None


# --------------------------------------------------------------------------- judge

def judge(episode: Episode, task: Task, *, use_llm_judge: bool = True) -> Episode:
    """Set episode.success / failure_mode / judge_reason in place and return it."""
    pre = episode.failure_mode if episode.failure_mode in AGENT_FAILURE_MODES else None
    kind = TaskKind(task.kind)

    if kind == TaskKind.answer:
        if episode.final_answer is None or not str(episode.final_answer).strip():
            episode.success = False
            episode.failure_mode = pre or "wrong_answer"
            episode.judge_reason = f"no answer given ({episode.failure_mode})"
            return episode
        hit = answer_matches(episode.final_answer, task.expected_answer, task.answer_aliases)
        if hit is not None:
            episode.success = True
            episode.failure_mode = None
            episode.judge_reason = f"answer matches {hit!r}"
            return episode
        if use_llm_judge:
            verdict = _llm_answer_judge(task, str(episode.final_answer))
            if verdict is not None:
                ok, reason = verdict
                episode.success = ok
                episode.failure_mode = None if ok else "wrong_answer"
                episode.judge_reason = f"llm judge: {reason}"
                return episode
        episode.success = False
        episode.failure_mode = "wrong_answer"
        episode.judge_reason = f"expected {task.expected_answer!r}, got {str(episode.final_answer)[:200]!r}"
        return episode

    if kind == TaskKind.url:
        if pre == "gave_up" or not episode.final_url:
            episode.success = False
            episode.failure_mode = pre or "wrong_page"
            episode.judge_reason = f"no final page to check ({episode.failure_mode})"
            return episode
        path = relative_path(episode.final_url, episode.site_id, episode.site_version)
        if url_matches(task.expected_url_pattern, episode.final_url, episode.site_id, episode.site_version):
            episode.success = True
            episode.failure_mode = None
            episode.judge_reason = f"final path {path!r} matches /{task.expected_url_pattern}/"
        else:
            episode.success = False
            episode.failure_mode = pre or "wrong_page"
            episode.judge_reason = f"final path {path!r} does not match /{task.expected_url_pattern}/"
        return episode

    # action: the site must have recorded the event for this episode, whatever the agent thinks happened
    ev = find_matching_event(episode, task)
    if ev is not None:
        episode.success = True
        episode.failure_mode = None
        episode.judge_reason = f"site recorded event {ev.name!r} with {ev.payload}"
    else:
        episode.success = False
        episode.failure_mode = pre or "no_event"
        want = f"{task.expected_event!r}" + (f" matching {task.expected_event_match}" if task.expected_event_match else "")
        episode.judge_reason = f"no event {want} recorded for this episode ({episode.failure_mode})"
    return episode


# --------------------------------------------------------------------------- aggregation

def _cost(ep: Episode) -> float:
    if ep.cost_usd:
        return ep.cost_usd
    try:
        from abtract.models.registry import get_model

        return ep.usage.cost_usd(get_model(ep.model_id))
    except Exception:  # noqa: BLE001
        return 0.0


def metric_block(episodes: list[Episode]) -> MetricBlock:
    n = len(episodes)
    if n == 0:
        return MetricBlock()
    succ = sum(1 for e in episodes if e.success)
    costs = [_cost(e) for e in episodes]
    modes = Counter(e.failure_mode for e in episodes if not e.success and e.failure_mode)
    return MetricBlock(
        episodes=n,
        success_rate=succ / n,
        avg_steps=sum(e.n_steps for e in episodes) / n,
        avg_duration_s=sum(e.duration_s for e in episodes) / n,
        avg_cost_usd=sum(costs) / n,
        total_cost_usd=sum(costs),
        failure_modes=dict(sorted(modes.items())),
    )


def _group(episodes: list[Episode], key) -> dict[str, MetricBlock]:
    groups: dict[str, list[Episode]] = {}
    for e in episodes:
        k = key(e)
        if k is None:
            continue
        groups.setdefault(str(k), []).append(e)
    return {k: metric_block(v) for k, v in sorted(groups.items())}


def aggregate(run: RunSummary, episodes: list[Episode]) -> RunSummary:
    trap_of = {t.id: t.trap for t in run.tasks}
    run.overall = metric_block(episodes)
    run.per_model = _group(episodes, lambda e: e.model_id)
    run.per_agent = _group(episodes, lambda e: e.agent_kind.value if hasattr(e.agent_kind, "value") else e.agent_kind)
    run.per_task = _group(episodes, lambda e: e.task_id)
    run.per_trap = _group(episodes, lambda e: trap_of.get(e.task_id))
    run.finished_at = time.time()
    return run


def per_model_agent(episodes: list[Episode]) -> dict[tuple[str, str], MetricBlock]:
    """model x agent grid for the printed table."""
    groups: dict[tuple[str, str], list[Episode]] = {}
    for e in episodes:
        ak = e.agent_kind.value if hasattr(e.agent_kind, "value") else str(e.agent_kind)
        groups.setdefault((e.model_id, ak), []).append(e)
    return {k: metric_block(v) for k, v in sorted(groups.items())}


# --------------------------------------------------------------------------- comparison

_FIELDS = ("success_rate", "avg_steps", "avg_duration_s", "avg_cost_usd", "episodes")


def _delta(a: MetricBlock | None, b: MetricBlock | None) -> dict[str, Any]:
    a = a or MetricBlock()
    b = b or MetricBlock()
    out: dict[str, Any] = {}
    for f in _FIELDS:
        va, vb = getattr(a, f), getattr(b, f)
        out[f] = {"a": va, "b": vb, "delta": vb - va}
    return out


def compare(a: RunSummary, b: RunSummary) -> dict[str, Any]:
    """Deltas b - a for overall and each per_* dimension. Positive success_rate delta = b is better."""
    def dim(name: str) -> dict[str, Any]:
        da, db = getattr(a, name), getattr(b, name)
        return {k: _delta(da.get(k), db.get(k)) for k in sorted(set(da) | set(db))}

    return {
        "a": {"run_id": a.run_id, "site_version": a.site_version},
        "b": {"run_id": b.run_id, "site_version": b.site_version},
        "overall": _delta(a.overall, b.overall),
        "per_model": dim("per_model"),
        "per_agent": dim("per_agent"),
        "per_task": dim("per_task"),
        "per_trap": dim("per_trap"),
    }
