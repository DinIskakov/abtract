#!/usr/bin/env python
"""The full loop: swarm vN -> Gemini optimizes -> vN+1 -> swarm ... -> comparison table of every version.

Local (agents in-process, site served from ./data, optimizer validation via subprocess):
    uv run python scripts/run_loop.py --local --site demo --version v0 --iterations 2 \
        --models mock --agents text,dom --tasks demo_site/tasks.json

On Modal (episodes via run_episode.map, optimizer via optimize_site_remote, validation in a modal.Sandbox):
    modal run scripts/run_loop.py --site demo --version v0 --iterations 2 \
        --models deepseek-v4.1-flash,glm-5.3-flash,kimi-k3 --agents text,dom,vision \
        --tasks demo_site/tasks.json [--site-base-url https://<workspace>--abtract-site-server.modal.run]

The optimizer always needs GEMINI_API_KEY (in .env locally, in the `abtract-secrets` Modal secret in the cloud).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.modal_app import app  # noqa: E402  `modal run` looks this up

try:
    import deploy  # noqa: E402,F401
except Exception:  # noqa: BLE001
    import app.optimizer.rewrite  # noqa: E402,F401
    import app.swarm.runner  # noqa: E402,F401

from app.swarm.cli import loop_main  # noqa: E402

DEFAULT_MODELS = "default"


@app.local_entrypoint()
def main(
    site: str = "demo",
    version: str = "v0",
    iterations: int = 2,
    tasks: str = "demo_site/tasks.json",
    models: str = DEFAULT_MODELS,
    agents: str = "text,dom,vision",
    site_base_url: str = "",
    local: bool = False,
    concurrency: int = 8,
    limit: int = 0,
    llm_judge: bool = True,
    budget_usd: float = 0.0,
    yes: bool = False,
) -> None:
    """`modal run scripts/run_loop.py --site demo --version v0 --iterations 2 ...`"""
    loop_main(
        site=site,
        version=version,
        iterations=iterations,
        models=models,
        agents=agents,
        tasks=tasks,
        local=local,
        site_base_url=site_base_url or None,
        concurrency=concurrency,
        use_llm_judge=llm_judge,
        limit=limit or None,
        budget_usd=budget_usd or None,
        yes=yes,
    )


def _cli() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--site", default="demo")
    p.add_argument("--version", default="v0", help="starting version")
    p.add_argument("--iterations", type=int, default=2, help="number of optimize steps (runs = iterations + 1)")
    p.add_argument("--tasks", default="demo_site/tasks.json", help="tasks JSON file, or 'generate'")
    p.add_argument(
        "--models",
        default=DEFAULT_MODELS,
        help="comma-separated model ids and/or selectors: cheapest:N, vision, all, default, mock",
    )
    p.add_argument("--agents", default="text,dom,vision")
    p.add_argument("--site-base-url", default="")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--local", action="store_true", help="everything in-process")
    mode.add_argument("--modal", action="store_true", help="episodes + optimizer on Modal (ephemeral app)")
    p.add_argument("--concurrency", type=int, default=8)
    p.add_argument("--limit", type=int, default=0, help="only the first N tasks")
    p.add_argument("--no-llm-judge", action="store_true")
    p.add_argument("--budget-usd", type=float, default=0.0, help="per swarm run: refuse to start above this estimate")
    p.add_argument("--yes", "-y", action="store_true", help="do not ask for confirmation when the estimate is > $5")
    a = p.parse_args()
    local = not a.modal
    kwargs = dict(
        site=a.site,
        version=a.version,
        iterations=a.iterations,
        models=a.models,
        agents=a.agents,
        tasks=a.tasks,
        local=local,
        site_base_url=a.site_base_url or None,
        concurrency=a.concurrency,
        use_llm_judge=not a.no_llm_judge,
        limit=a.limit or None,
        budget_usd=a.budget_usd or None,
        yes=a.yes,
    )
    if local:
        loop_main(**kwargs)
    else:
        import modal

        from app.config import settings

        if not (a.site_base_url or settings.site_base_url):
            raise SystemExit("--modal runs need --site-base-url or ABTRACT_SITE_BASE_URL (or use --local)")
        with modal.enable_output(), app.run():
            loop_main(**kwargs)


if __name__ == "__main__":
    _cli()
