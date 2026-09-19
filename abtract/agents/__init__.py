"""Agent entrypoint used by the swarm runner. Implementations live in text_agent.py, dom_agent.py, vision_agent.py.

Contract:
    run_agent(agent_kind, model_id, task, site_url, run_id=..., site_id=..., site_version=..., screenshot_dir=None) -> Episode

- Never raises for agent-level failures: catches everything, fills Episode.error / failure_mode ("error"/"timeout"/"max_steps"/"gave_up").
- Does NOT judge success (metrics/score.py does that); leaves Episode.success = None.
- Sends header `X-Abtract-Episode: <episode.id>` on every HTTP request / browser context so the site server can attribute SiteEvents.
- Fills Episode.usage from every chat() call and Episode.cost_usd via usage.cost_usd(spec).
"""
from __future__ import annotations

from pathlib import Path

from abtract.schemas import AgentKind, Episode, Task


def run_agent(
    agent_kind: AgentKind | str,
    model_id: str,
    task: Task,
    site_url: str,
    *,
    run_id: str,
    site_id: str,
    site_version: str,
    screenshot_dir: Path | None = None,
) -> Episode:
    kind = AgentKind(agent_kind)
    if kind == AgentKind.text:
        from abtract.agents.text_agent import TextAgent as Impl
    elif kind == AgentKind.dom:
        from abtract.agents.dom_agent import DomAgent as Impl
    elif kind == AgentKind.vision:
        from abtract.agents.vision_agent import VisionAgent as Impl
    else:  # pragma: no cover
        raise ValueError(kind)
    agent = Impl(model_id=model_id, run_id=run_id, site_id=site_id, site_version=site_version, screenshot_dir=screenshot_dir)
    return agent.run(task, site_url)
