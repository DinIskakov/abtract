"""Common observe -> think -> act loop shared by the text, dom and vision agents.

Subclasses implement the environment side (start / observe / act / current_url / close); this module owns the
episode bookkeeping: step records, usage + cost accounting, terminal actions, timeouts and the guarantee that
run() never raises.
"""
from __future__ import annotations

import json
import re
import time
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urljoin, urlparse

from abtract.config import settings
from abtract.models import llm
from abtract.models.llm import ChatMessage
from abtract.models.registry import get_model
from abtract.schemas import Action, AgentKind, Episode, ModelSpec, Step, Task

from .prompts import system_prompt

# Observation text windows (text and dom agents page through longer text with `scroll`).
TEXT_CAP = 12_000
SCROLL_OVERLAP = 800

_TRUTHY = {"1", "true", "yes", "on", "checked", "y"}


class ActionError(Exception):
    """An action could not be carried out (element missing, off-site navigation, HTTP error...). Recorded as
    Step.error; the episode continues."""


@dataclass
class Observation:
    text: str                          # what goes into the prompt (and is counted in Step.observation_chars)
    url: str
    png_base64: str | None = None      # vision agent only
    screenshot_path: str | None = None # relative to settings.data_dir when available


# --------------------------------------------------------------------------- reply parsing

_TYPE_ALIASES: dict[str, str] = {
    "navigate": "navigate", "goto": "navigate", "go_to": "navigate", "go": "navigate", "open": "navigate",
    "visit": "navigate", "navigate_to": "navigate", "open_url": "navigate", "load": "navigate", "url": "navigate",
    "click": "click", "press": "click", "tap": "click", "submit": "click", "click_element": "click",
    "click_on": "click", "toggle": "click", "check": "click",
    "type": "type", "fill": "type", "input": "type", "enter": "type", "type_text": "type", "write": "type",
    "set": "type", "fill_in": "type", "enter_text": "type", "type_into": "type",
    "select": "select", "select_option": "select", "choose": "select", "pick": "select", "dropdown": "select",
    "scroll": "scroll", "scroll_down": "scroll", "scroll_up": "scroll", "page_down": "scroll", "page_up": "scroll",
    "back": "back", "go_back": "back", "history_back": "back", "previous": "back", "navigate_back": "back",
    "answer": "answer", "final_answer": "answer", "final": "answer", "done": "answer", "finish": "answer",
    "finished": "answer", "complete": "answer", "respond": "answer", "report": "answer", "return": "answer",
    "submit_answer": "answer", "reply": "answer", "result": "answer", "task_complete": "answer",
    "give_up": "give_up", "giveup": "give_up", "abort": "give_up", "fail": "give_up", "quit": "give_up",
    "impossible": "give_up", "cannot": "give_up", "cant": "give_up", "stop": "give_up", "terminate": "give_up",
}
_ID_KEYS = ("id", "element_id", "element", "element_index", "index", "number", "ref", "target", "elementId", "n")
_TEXT_KEYS = ("text", "value", "answer", "content", "input", "string", "message", "query")
_URL_KEYS = ("url", "href", "link", "page", "target", "path")
_REASON_KEYS = ("reason", "text", "message", "explanation", "why")
_THOUGHT_KEYS = ("thought", "thoughts", "reasoning", "reason", "thinking", "rationale", "plan", "analysis")


def _first(d: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for k in keys:
        if k in d and d[k] is not None and d[k] != "":
            return d[k]
    return None


def _to_int(v: Any) -> int | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, float) and v.is_integer():
        return int(v)
    if isinstance(v, dict):
        return _to_int(_first(v, _ID_KEYS))
    if isinstance(v, str):
        m = re.search(r"\d+", v)
        if m:
            return int(m.group())
    return None


def _to_str(v: Any) -> str | None:
    if v is None:
        return None
    if isinstance(v, str):
        return v
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False)
    return str(v)


def parse_reply(text: str) -> tuple[str | None, Action | None, str | None]:
    """Turn a model reply into (thought, Action, error). Lenient: tolerates missing "thought", the action at top
    level, `{"action": "click", "id": 3}`, `{"action": {"click": {"id": 3}}}`, string ids like "[3]", aliases such
    as goto/fill/done, and `args`/`params` wrappers. Returns error (and action None) if nothing usable is found."""
    try:
        data: Any = llm.extract_json(text)
    except Exception as e:  # noqa: BLE001
        return None, None, f"reply was not valid JSON ({e}); reply with a single JSON object"
    if isinstance(data, list):
        data = next((x for x in data if isinstance(x, dict)), None)
    if not isinstance(data, dict):
        return None, None, "reply JSON was not an object"

    thought = _to_str(_first(data, _THOUGHT_KEYS))
    action_raw: Any = data.get("action")
    if action_raw is None and isinstance(data.get("actions"), list) and data["actions"]:
        action_raw = data["actions"][0]
    if action_raw is None:
        action_raw = data  # action given at top level
    if isinstance(action_raw, str):
        # {"action": "click", "id": 3}  or  {"action": "answer: $3"}  or bare "click"
        head, _, tail = action_raw.strip().partition(":")
        merged: dict[str, Any] = {k: v for k, v in data.items() if k not in ("action", "thought")}
        merged["type"] = head.strip()
        if tail.strip() and "text" not in merged:
            merged["text"] = tail.strip()
        action_raw = merged
    if not isinstance(action_raw, dict):
        return thought, None, "action must be a JSON object"

    a = dict(action_raw)
    for wrapper in ("args", "params", "parameters", "arguments", "input"):
        if isinstance(a.get(wrapper), dict):
            inner = a.pop(wrapper)
            a = {**inner, **a}
    atype = _first(a, ("type", "action", "name", "action_type", "kind", "command", "op", "tool"))
    if atype is None:
        # {"click": {"id": 3}} or {"answer": "$3.95"}
        for k, v in a.items():
            if k.lower() in _TYPE_ALIASES:
                atype = k
                if isinstance(v, dict):
                    a = {**v, **{kk: vv for kk, vv in a.items() if kk != k}}
                elif isinstance(v, (str, int, float)):
                    a = {**a, "_scalar": v}
                break
    if atype is None:
        return thought, None, "action has no \"type\"; use one of navigate/click/type/select/scroll/back/answer/give_up"
    atype_s = str(atype).strip().lower().replace("-", "_").replace(" ", "_")
    canon = _TYPE_ALIASES.get(atype_s)
    if canon is None and atype_s.endswith(("_action", "action")):
        canon = _TYPE_ALIASES.get(atype_s.replace("_action", "").replace("action", ""))
    if canon is None:
        return thought, None, f"unknown action type {atype!r}; use navigate/click/type/select/scroll/back/answer/give_up"

    scalar = a.get("_scalar")
    try:
        if canon == "navigate":
            url = _to_str(_first(a, _URL_KEYS) or scalar)
            if not url:
                return thought, None, "navigate needs a \"url\""
            return thought, Action(type="navigate", url=url), None
        if canon == "click":
            eid = _to_int(_first(a, _ID_KEYS) if _first(a, _ID_KEYS) is not None else scalar)
            if eid is None:
                return thought, None, "click needs a numeric \"id\" from the observation"
            return thought, Action(type="click", id=eid), None
        if canon == "type":
            eid = _to_int(_first(a, _ID_KEYS))
            txt = _to_str(_first(a, _TEXT_KEYS) if _first(a, _TEXT_KEYS) is not None else scalar)
            if eid is None:
                return thought, None, "type needs a numeric \"id\" of a field"
            return thought, Action(type="type", id=eid, text=txt or ""), None
        if canon == "select":
            eid = _to_int(_first(a, _ID_KEYS))
            val = _to_str(_first(a, ("value", "option", "text", "label", "choice")) or scalar)
            if eid is None:
                return thought, None, "select needs a numeric \"id\" of a dropdown"
            return thought, Action(type="select", id=eid, value=val or ""), None
        if canon == "scroll":
            d = _to_str(_first(a, ("direction", "dir", "where", "to")) or scalar) or ""
            if "up" in atype_s:
                d = "up"
            d = "up" if d.strip().lower().startswith(("u", "top", "-")) else "down"
            return thought, Action(type="scroll", direction=d), None
        if canon == "back":
            return thought, Action(type="back"), None
        if canon == "answer":
            txt = _to_str(_first(a, _TEXT_KEYS) if _first(a, _TEXT_KEYS) is not None else scalar)
            if txt is None and atype_s in ("stop", "quit"):
                return thought, Action(type="give_up", reason=thought or atype_s), None
            return thought, Action(type="answer", text=(txt or "").strip()), None
        if canon == "give_up":
            reason = _to_str(_first(a, _REASON_KEYS) or scalar) or thought or "no reason given"
            return thought, Action(type="give_up", reason=reason), None
    except Exception as e:  # noqa: BLE001  pydantic validation etc.
        return thought, None, f"could not build action: {e}"
    return thought, None, f"unhandled action type {canon}"  # pragma: no cover


def same_origin(url: str, site_url: str) -> bool:
    a, b = urlparse(url), urlparse(site_url)
    return a.scheme in ("http", "https") and a.netloc.lower() == b.netloc.lower()


# --------------------------------------------------------------------------- the loop

class BaseAgent:
    kind: AgentKind = AgentKind.text  # overridden by subclasses

    def __init__(
        self,
        model_id: str,
        run_id: str,
        site_id: str,
        site_version: str,
        screenshot_dir: Path | None = None,
    ):
        self.model_id = model_id
        self.spec: ModelSpec = get_model(model_id)
        self.run_id = run_id
        self.site_id = site_id
        self.site_version = site_version
        self.screenshot_dir = Path(screenshot_dir) if screenshot_dir else None
        self.site_url: str = ""
        self.episode: Episode | None = None
        self.log: Callable[[str], None] | None = None  # set by run_local for live tracing

    # ---- environment hooks (subclasses)
    def start(self, site_url: str, episode: Episode) -> None:  # open client/browser and load site_url
        raise NotImplementedError

    def observe(self) -> Observation:
        raise NotImplementedError

    def act(self, action: Action) -> None:  # raise ActionError for recoverable failures
        raise NotImplementedError

    def current_url(self) -> str:
        return self.site_url

    def healthy(self) -> bool:  # False => environment is dead, abort the episode
        return True

    def close(self) -> None:
        pass

    # ---- helpers for subclasses
    def resolve_url(self, url: str) -> str:
        return urljoin(self.current_url() or self.site_url, url.strip())

    def check_origin(self, url: str) -> str:
        """Resolve `url` against the current page and refuse anything off the site's host."""
        full = self.resolve_url(url)
        if not same_origin(full, self.site_url):
            raise ActionError(f"refused: {full} is not on this site's origin ({urlparse(self.site_url).netloc}); stay on the site")
        return full

    def screenshot_rel_path(self, step_index: int) -> tuple[Path, str] | None:
        """Absolute path to write step screenshot to and the path to record (relative to settings.data_dir)."""
        if self.screenshot_dir is None:
            return None
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)
        p = self.screenshot_dir / f"{step_index:02d}.png"
        try:
            rel = str(p.resolve().relative_to(Path(settings.data_dir).resolve()))
        except ValueError:
            rel = str(p)
        return p, rel

    # ---- prompt construction
    def build_messages(self, task: Task, history: list[dict[str, Any]], obs: Observation, step_index: int, max_steps: int) -> list[ChatMessage]:
        hist_lines = []
        for h in history:
            act = json.dumps(h["action"], ensure_ascii=False) if h.get("action") else "(unparseable reply)"
            th = (h.get("thought") or "").replace("\n", " ")
            if len(th) > 200:
                th = th[:200] + "..."
            res = f"ERROR: {h['error']}" if h.get("error") else "ok"
            hist_lines.append(f"{h['index'] + 1}. thought: {th or '-'} | action: {act} | result: {res}")
        history_block = "\n".join(hist_lines) if hist_lines else "(none yet)"
        header = (
            f"TASK: {task.prompt}\n\n"
            f"This is step {step_index + 1} of at most {max_steps}.\n\n"
            f"PREVIOUS STEPS:\n{history_block}\n\n"
            f"CURRENT OBSERVATION:\n"
        )
        footer = "\nReply with one JSON object: {\"thought\": \"...\", \"action\": {...}}"
        if obs.png_base64:
            content: str | list[dict[str, Any]] = [
                {"type": "text", "text": header + obs.text},
                {"type": "image", "png_base64": obs.png_base64},
                {"type": "text", "text": footer.strip()},
            ]
        else:
            content = header + obs.text + "\n" + footer
        return [ChatMessage(role="system", content=system_prompt(self.kind)), ChatMessage(role="user", content=content)]

    # ---- the loop
    def run(self, task: Task, site_url: str) -> Episode:
        ep = Episode(
            run_id=self.run_id, site_id=self.site_id, site_version=self.site_version,
            task_id=task.id, agent_kind=self.kind, model_id=self.model_id,
        )
        self.episode = ep
        self.site_url = site_url
        history: list[dict[str, Any]] = []
        max_steps = task.max_steps or settings.default_max_steps
        time_limit = task.timeout_s or settings.episode_timeout_s
        deadline = ep.started_at + time_limit
        started = False
        try:
            if self.kind == AgentKind.vision and not self.spec.supports_vision:
                ep.failure_mode = "error"
                ep.error = "model has no vision"
                return ep
            self.start(site_url, ep)
            started = True
            terminal = False
            for i in range(max_steps):
                if time.time() > deadline:
                    ep.failure_mode = "timeout"
                    ep.error = f"episode exceeded {time_limit}s"
                    break
                t0 = time.time()
                url_before = self._safe_url()
                try:
                    obs = self.observe()
                except Exception as e:  # noqa: BLE001
                    if not self.healthy():
                        raise
                    obs = Observation(text=f"(observation failed: {type(e).__name__}: {e})", url=url_before)
                self._log(f"--- step {i + 1}/{max_steps} @ {url_before}\n{obs.text[:1500]}{'...' if len(obs.text) > 1500 else ''}")
                messages = self.build_messages(task, history, obs, i, max_steps)
                call_options = {}
                if task.timeout_s is not None:
                    remaining = deadline - time.time()
                    if remaining <= 0:
                        ep.failure_mode, ep.error = "timeout", f"episode exceeded {time_limit}s"
                        break
                    call_options = {"timeout_s": min(15.0, remaining), "retries": 1}
                resp = llm.chat(self.spec, messages, json_mode=True, **call_options)
                ep.usage.add(resp.usage)
                thought, action, err = parse_reply(resp.text)
                self._log(f"model: {resp.text[:500]}")
                step = Step(
                    index=i, url=url_before, observation_chars=len(obs.text), thought=thought,
                    action=action or Action(type="noop"), screenshot_path=obs.screenshot_path,
                )
                if err:
                    step.error = err
                elif action.type == "answer":
                    ep.final_answer = action.text or ""
                    terminal = True
                elif action.type == "give_up":
                    ep.failure_mode = "gave_up"
                    terminal = True
                else:
                    try:
                        self.act(action)
                    except ActionError as e:
                        step.error = str(e)
                    except Exception as e:  # noqa: BLE001  playwright/httpx errors: recoverable unless env is dead
                        if not self.healthy():
                            raise
                        step.error = f"{type(e).__name__}: {str(e).splitlines()[0][:300] if str(e) else ''}"
                step.latency_ms = int((time.time() - t0) * 1000)
                ep.steps.append(step)
                history.append({"index": i, "thought": thought, "action": action.model_dump(exclude_none=True) if action else None, "error": step.error})
                if step.error:
                    self._log(f"step error: {step.error}")
                if terminal:
                    break
            else:
                ep.failure_mode = "max_steps"
        except Exception as e:  # noqa: BLE001  never raise out of run()
            ep.failure_mode = "error"
            ep.error = f"{type(e).__name__}: {e}"
            self._log("episode error:\n" + traceback.format_exc())
        finally:
            ep.finished_at = time.time()
            if started:
                ep.final_url = self._safe_url()
            ep.cost_usd = ep.usage.cost_usd(self.spec)
            try:
                self.close()
            except Exception:  # noqa: BLE001
                pass
        return ep

    def _safe_url(self) -> str:
        try:
            return self.current_url() or self.site_url
        except Exception:  # noqa: BLE001
            return self.site_url

    def _log(self, msg: str) -> None:
        if self.log:
            try:
                self.log(msg)
            except Exception:  # noqa: BLE001
                pass
