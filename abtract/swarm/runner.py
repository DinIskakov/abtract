"""Fan a swarm of (model x agent x task) episodes out, locally or as Modal functions, and aggregate the results.

    run_episode_sync(payload)   one episode: run the agent, judge it, save it. Never raises.
    run_episode                 the same thing as a Modal function (browser_image, so dom/vision agents work).
    estimate_run_cost(...)      what a grid will roughly cost before anything is launched.
    run_swarm(...)              build the grid, fan out (ThreadPoolExecutor or run_episode.map), aggregate, save.
                                `budget_usd` raises BudgetExceeded up front and (locally) stops submitting when spent.
    serve_site_locally()        serve the store's site versions on a free local port for --local runs.

payload = {run_id, site_id, site_version, site_url, task: Task.model_dump(), model_id, agent_kind}
"""
from __future__ import annotations

import logging
import socket
import threading
import time
import traceback
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Callable

from abtract import store
from abtract.metrics.score import aggregate, judge
from abtract.modal_app import app, base_image, browser_image, secrets, volumes
from abtract.models.registry import get_model
from abtract.schemas import AgentKind, Episode, RunSummary, Task

OnEpisode = Callable[[Episode], None]
log = logging.getLogger("abtract.swarm")

# Pre-run estimate defaults. Agent traffic is input-heavy: every step re-sends the system prompt, the task and a
# page observation (a few thousand tokens), and gets back one small JSON action.
DEFAULT_AVG_STEPS = 8
DEFAULT_TOKENS_IN_PER_STEP = 6000
DEFAULT_TOKENS_OUT_PER_STEP = 250
VISION_INPUT_MULTIPLIER = 1.5  # a screenshot costs more input tokens than the text/DOM observation it replaces


class BudgetExceeded(RuntimeError):
    """The pre-run cost estimate is above the caller's budget. Nothing was launched or saved."""

    def __init__(self, estimate: dict[str, Any], budget_usd: float):
        self.estimate = estimate
        self.budget_usd = budget_usd
        super().__init__(f"estimated cost ${estimate['total_usd']:.2f} for {estimate['episodes']} episodes exceeds "
                         f"the budget of ${budget_usd:.2f}")


# --------------------------------------------------------------------------- one episode

def _task_of(payload: dict[str, Any]) -> Task:
    t = payload["task"]
    return t if isinstance(t, Task) else Task(**t)


def error_episode(payload: dict[str, Any], exc: BaseException | str) -> Episode:
    """An Episode standing in for an agent run that could not even produce one (container crash, timeout, ...)."""
    task = _task_of(payload)
    msg = exc if isinstance(exc, str) else f"{type(exc).__name__}: {exc}"
    return Episode(
        run_id=payload["run_id"],
        site_id=payload["site_id"],
        site_version=payload["site_version"],
        task_id=task.id,
        agent_kind=AgentKind(payload["agent_kind"]),
        model_id=payload["model_id"],
        finished_at=time.time(),
        success=False,
        failure_mode="error",
        error=msg[:2000],
        judge_reason="infrastructure error before judging",
    )


def run_episode_sync(payload: dict[str, Any]) -> dict[str, Any]:
    """Run one agent episode, judge it, persist it. Returns Episode.model_dump(). Never raises."""
    task = _task_of(payload)
    run_id, site_id, site_version = payload["run_id"], payload["site_id"], payload["site_version"]
    model_id, agent_kind, site_url = payload["model_id"], payload["agent_kind"], payload["site_url"]

    try:
        import abtract.agents as agents  # looked up at call time so tests can monkeypatch abtract.agents.run_agent

        ep = agents.run_agent(
            agent_kind, model_id, task, site_url,
            run_id=run_id, site_id=site_id, site_version=site_version, screenshot_dir=None,
        )
        if not isinstance(ep, Episode):
            ep = Episode(**ep)
    except BaseException as e:  # noqa: BLE001  the contract says agents never raise; belt and braces
        ep = error_episode(payload, e)
        ep.error = (ep.error or "") + "\n" + traceback.format_exc()[-1500:]

    if ep.finished_at is None:
        ep.finished_at = time.time()
    if not ep.cost_usd:
        try:
            ep.cost_usd = ep.usage.cost_usd(get_model(model_id))
        except Exception:  # noqa: BLE001
            pass

    store.commit()  # flush screenshots so the volume can be reloaded inside judge (no-op locally)
    try:
        judge(ep, task, use_llm_judge=bool(payload.get("use_llm_judge", True)))
    except Exception as e:  # noqa: BLE001
        ep.success = False
        ep.failure_mode = ep.failure_mode or "error"
        ep.judge_reason = f"judge crashed: {type(e).__name__}: {e}"
    store.save_episode(ep)
    store.commit()
    return ep.model_dump(mode="json")


@app.function(image=browser_image, volumes=volumes, secrets=secrets, timeout=900, max_containers=40)
def run_episode(payload: dict) -> dict:
    return run_episode_sync(payload)


@app.function(image=base_image, volumes=volumes, secrets=secrets, timeout=300)
def save_run_remote(run: dict) -> str:
    """Write a RunSummary produced by a local coordinator onto the Volume so the dashboard/optimizer see it."""
    r = RunSummary(**run)
    store.save_run(r)
    store.commit()
    return r.run_id


# --------------------------------------------------------------------------- the grid

def build_payloads(run: RunSummary, tasks: list[Task], model_ids: list[str], agent_kinds: list[AgentKind | str],
                   *, use_llm_judge: bool = True) -> list[dict[str, Any]]:
    payloads: list[dict[str, Any]] = []
    for model_id in model_ids:
        spec = get_model(model_id)  # KeyError early for typos
        for kind in agent_kinds:
            kind = AgentKind(kind)
            if kind == AgentKind.vision and not spec.supports_vision:
                continue
            for task in tasks:
                payloads.append({
                    "run_id": run.run_id,
                    "site_id": run.site_id,
                    "site_version": run.site_version,
                    "site_url": run.site_url,
                    "task": task.model_dump(mode="json"),
                    "model_id": model_id,
                    "agent_kind": kind.value,
                    "use_llm_judge": use_llm_judge,
                })
    return payloads


def estimate_run_cost(
    tasks: list[Task],
    model_ids: list[str],
    agent_kinds: list[AgentKind | str],
    *,
    avg_steps: int = DEFAULT_AVG_STEPS,
    tokens_in_per_step: int = DEFAULT_TOKENS_IN_PER_STEP,
    tokens_out_per_step: int = DEFAULT_TOKENS_OUT_PER_STEP,
) -> dict[str, Any]:
    """Rough USD cost of the (model x agent x task) grid before launching it.

    Per episode: min(avg_steps, task.max_steps) steps, each sending `tokens_in_per_step` input tokens (x1.5 for the
    vision agent) and receiving `tokens_out_per_step`. Vision is skipped for models without vision, like
    build_payloads. Cached-prompt discounts are ignored, so this errs high.
    Returns {"episodes", "per_model": {id: usd}, "total_usd", "assumptions"}.
    """
    kinds = [AgentKind(k) for k in agent_kinds]
    per_model: dict[str, float] = {}
    per_model_episodes: dict[str, int] = {}
    for model_id in model_ids:
        spec = get_model(model_id)  # KeyError early for typos
        usd, n = 0.0, 0
        for kind in kinds:
            if kind == AgentKind.vision and not spec.supports_vision:
                continue
            mult = VISION_INPUT_MULTIPLIER if kind == AgentKind.vision else 1.0
            for task in tasks:
                steps = min(avg_steps, task.max_steps)
                tok_in = steps * tokens_in_per_step * mult
                tok_out = steps * tokens_out_per_step
                usd += (tok_in * spec.input_price_per_m + tok_out * spec.output_price_per_m) / 1_000_000
                n += 1
        per_model[model_id] = usd
        per_model_episodes[model_id] = n
    return {
        "episodes": sum(per_model_episodes.values()),
        "per_model": per_model,
        "total_usd": sum(per_model.values()),
        "assumptions": {
            "avg_steps": avg_steps,
            "tokens_in_per_step": tokens_in_per_step,
            "tokens_out_per_step": tokens_out_per_step,
            "vision_input_multiplier": VISION_INPUT_MULTIPLIER,
            "episodes_per_model": per_model_episodes,
            "note": "steps capped at each task's max_steps; cached-prompt discounts ignored",
        },
    }


def _key(p: dict[str, Any]) -> tuple[str, str, str]:
    return (p["model_id"], p["agent_kind"], _task_of(p).id)


def _ep_key(e: Episode) -> tuple[str, str, str]:
    return (e.model_id, AgentKind(e.agent_kind).value, e.task_id)


def _fan_out_local(payloads: list[dict[str, Any]], concurrency: int, on_episode: OnEpisode | None,
                   budget_usd: float | None = None) -> list[Episode]:
    """Run payloads on a thread pool, at most `concurrency` in flight. With a budget, stop submitting once the
    episodes that came back have cost more than it; whatever was never submitted becomes an error episode."""
    episodes: list[Episode] = []
    pending = list(payloads)
    in_flight: dict[Any, dict[str, Any]] = {}
    spent = 0.0
    width = max(1, concurrency)

    def over_budget() -> bool:
        return budget_usd is not None and spent >= budget_usd

    with ThreadPoolExecutor(max_workers=width) as pool:
        def submit_more() -> None:
            while pending and len(in_flight) < width and not over_budget():
                p = pending.pop(0)
                in_flight[pool.submit(run_episode_sync, p)] = p

        submit_more()
        while in_flight:
            done, _ = wait(list(in_flight), return_when=FIRST_COMPLETED)
            for fut in done:
                p = in_flight.pop(fut)
                try:
                    ep = Episode(**fut.result())
                except Exception as e:  # noqa: BLE001
                    ep = error_episode(p, e)
                    store.save_episode(ep)
                spent += ep.cost_usd
                episodes.append(ep)
                if on_episode:
                    on_episode(ep)
            submit_more()

    if pending:  # only possible when the budget ran out
        log.warning("budget exhausted after $%.4f (budget $%.2f): %d of %d episodes not started",
                    spent, budget_usd or 0.0, len(pending), len(payloads))
        for p in pending:
            ep = error_episode(p, f"budget exhausted: ${spent:.4f} spent of ${budget_usd:.2f} before this episode started")
            store.save_episode(ep)
            episodes.append(ep)
            if on_episode:
                on_episode(ep)
    return episodes


def _modal_batch(payloads: list[dict[str, Any]], on_episode: OnEpisode | None) -> list[Episode]:
    episodes: list[Episode] = []
    errors: list[BaseException] = []
    for r in run_episode.map(payloads, order_outputs=False, return_exceptions=True):
        if isinstance(r, BaseException):
            errors.append(r)
            continue
        ep = Episode(**r)
        store.save_episode(ep)  # local mirror of what the container wrote to the Volume
        episodes.append(ep)
        if on_episode:
            on_episode(ep)
    # exceptions come back unordered, so pair them with whichever payloads produced no episode
    seen = {_ep_key(e) for e in episodes}
    missing = [p for p in payloads if _key(p) not in seen]
    for i, p in enumerate(missing):
        exc = errors[i] if i < len(errors) else RuntimeError("no result returned from Modal")
        ep = error_episode(p, exc)
        store.save_episode(ep)
        episodes.append(ep)
        if on_episode:
            on_episode(ep)
    return episodes


def _fan_out_modal(payloads: list[dict[str, Any]], on_episode: OnEpisode | None,
                   budget_usd: float | None = None, concurrency: int = 8) -> list[Episode]:
    """Bound cloud fan-out and stop scheduling new batches when the episode allowance is spent.

    Already running calls can exceed the allowance; this is not a provider billing cap.
    """
    episodes: list[Episode] = []
    spent = 0.0
    width = max(1, concurrency)
    for offset in range(0, len(payloads), width):
        if budget_usd is not None and spent >= budget_usd:
            for payload in payloads[offset:]:
                ep = error_episode(payload, f"budget exhausted: ${spent:.4f} spent of ${budget_usd:.2f}")
                store.save_episode(ep)
                episodes.append(ep)
                if on_episode:
                    on_episode(ep)
            break
        batch = _modal_batch(payloads[offset:offset + width], on_episode)
        episodes.extend(batch)
        spent += sum(ep.cost_usd for ep in batch)
    return episodes


def run_swarm(
    site_id: str,
    site_version: str,
    tasks: list[Task],
    model_ids: list[str],
    agent_kinds: list[AgentKind | str],
    *,
    site_url: str,
    local: bool,
    concurrency: int = 8,
    run_id: str | None = None,
    on_episode: OnEpisode | None = None,
    use_llm_judge: bool = True,
    budget_usd: float | None = None,
) -> RunSummary:
    """Run every (model x agent x task) episode against one hosted site version and return the aggregated run.

    `budget_usd`: raise BudgetExceeded before launching anything when the estimate is above it. Locally, also stop
    submitting episodes/batches once actual spend reaches it (the rest are recorded as errors).
    In-flight calls may overshoot; the allowance excludes Gemini helper calls and hosting/compute.
    """
    kinds = [AgentKind(k) for k in agent_kinds]
    estimate = estimate_run_cost(tasks, model_ids, kinds)
    log.info("swarm estimate: %d episodes, ~$%.2f (%s)", estimate["episodes"], estimate["total_usd"],
             ", ".join(f"{k} ${v:.2f}" for k, v in estimate["per_model"].items()) or "-")
    if budget_usd is not None and estimate["total_usd"] > budget_usd:
        raise BudgetExceeded(estimate, budget_usd)

    run = RunSummary(
        site_id=site_id, site_version=site_version, site_url=site_url,
        tasks=list(tasks), model_ids=list(model_ids), agent_kinds=kinds,
        **({"run_id": run_id} if run_id else {}),
    )
    store.save_run(run)
    payloads = build_payloads(run, tasks, model_ids, kinds, use_llm_judge=use_llm_judge)
    if not payloads:
        raise ValueError("empty swarm grid (no tasks, or no model supports the requested agents)")

    if local:
        episodes = _fan_out_local(payloads, concurrency, on_episode, budget_usd=budget_usd)
    else:
        episodes = _fan_out_modal(payloads, on_episode, budget_usd=budget_usd, concurrency=concurrency)

    spent = sum(e.cost_usd for e in episodes)
    if budget_usd is not None and spent > budget_usd:
        log.warning("swarm spent $%.4f, over the $%.2f budget%s", spent, budget_usd,
                    " (in-flight calls were allowed to finish)")
    else:
        log.info("swarm spent $%.4f (estimate was $%.2f)", spent, estimate["total_usd"])

    aggregate(run, episodes)
    store.save_run(run)
    store.commit()
    if not local:
        try:
            save_run_remote.remote(run.model_dump(mode="json"))
        except Exception as e:  # noqa: BLE001  the local copy is still complete
            print(f"[swarm] warning: could not save run.json to the Modal volume: {e}")
    return run


# --------------------------------------------------------------------------- local site serving

def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_for_port(port: int, timeout: float = 15.0) -> None:
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return
        except OSError:
            time.sleep(0.1)
    raise RuntimeError(f"local site server did not start on port {port}")


class _SitesHandler(SimpleHTTPRequestHandler):
    """Static fallback: serves <data_dir>/sites/<site>/<version>/... at /s/<site>/<version>/... (no events)."""

    def translate_path(self, path: str) -> str:
        if path.startswith("/s/"):
            path = path[2:]
        return super().translate_path(path)

    def log_message(self, *args: Any) -> None:  # quiet
        pass


def serve_site_locally(port: int | None = None) -> tuple[str, Callable[[], None]]:
    """Start a site server in a daemon thread. Returns (base_url, stop_fn); site root = f"{base}/s/{site}/{ver}/".

    Prefers abtract.hosting.serve.create_app() under uvicorn (records SiteEvents, needed for action tasks);
    falls back to a plain static server over the store when the hosting module is not available.
    """
    port = port or _free_port()
    stop: Callable[[], None]
    try:
        import uvicorn
        from abtract.hosting.serve import create_app

        server = uvicorn.Server(uvicorn.Config(create_app(), host="127.0.0.1", port=port, log_level="warning"))
        threading.Thread(target=server.run, daemon=True, name="abtract-site").start()

        def stop() -> None:
            server.should_exit = True

        mode = "abtract.hosting.serve"
    except Exception as e:  # noqa: BLE001  module missing or failed to build -> static fallback
        sites = store.root() / "sites"
        sites.mkdir(parents=True, exist_ok=True)
        httpd = ThreadingHTTPServer(("127.0.0.1", port), partial(_SitesHandler, directory=str(sites)))
        threading.Thread(target=httpd.serve_forever, daemon=True, name="abtract-site").start()
        stop = httpd.shutdown
        mode = f"static fallback (no event recording; hosting.serve unavailable: {type(e).__name__}: {e})"
    _wait_for_port(port)
    base = f"http://127.0.0.1:{port}"
    print(f"[swarm] serving sites at {base}/s/<site>/<version>/  via {mode}")
    return base, stop
