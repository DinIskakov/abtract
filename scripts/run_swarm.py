#!/usr/bin/env python
"""Run one swarm (models x agents x tasks) against one site version and print the results table.

Local, in-process (serves the site from ./data on a free port; works offline with --models mock):
    uv run python scripts/run_swarm.py --local --site demo --version v0 --tasks demo_site/tasks.json --models mock --agents text,dom

On Modal (episodes run as `run_episode` containers; the site must be deployed: `modal deploy deploy.py`):
    modal run scripts/run_swarm.py --site demo --version v0 --tasks demo_site/tasks.json \
        --models deepseek-v4.1-flash,glm-5.3-flash,kimi-k3 --agents text,dom,vision \
        [--site-base-url https://<workspace>--abtract-site-server.modal.run]

`--models` takes ids and/or selectors: `cheapest:10`, `vision`, `all`, `default`, `mock` (see registry.select_models).
`--budget-usd 5` refuses to start above a $5 estimate and stops scheduling episodes once recorded spend reaches it.
`--yes` skips the confirmation prompt that a >$5 estimate triggers on an interactive terminal.
`--tasks generate` asks Gemini to write tasks for the site version (needs GEMINI_API_KEY).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from abtract.modal_app import app  # noqa: E402  `modal run` looks this up

try:  # register every Modal function on `app` (hosting/dashboard may not exist yet in a partial checkout)
    import deploy  # noqa: E402,F401
except Exception:  # noqa: BLE001
    import abtract.optimizer.rewrite  # noqa: E402,F401
    import abtract.swarm.runner  # noqa: E402,F401

from abtract.swarm.cli import swarm_main  # noqa: E402

DEFAULT_MODELS = "default"


@app.local_entrypoint()
def main(
    site: str = "demo",
    version: str = "v0",
    tasks: str = "demo_site/tasks.json",
    models: str = DEFAULT_MODELS,
    agents: str = "text,dom,vision",
    site_base_url: str = "",
    local: bool = False,
    concurrency: int = 8,
    run_id: str = "",
    limit: int = 0,
    llm_judge: bool = True,
    budget_usd: float = 0.0,
    yes: bool = False,
) -> None:
    """`modal run scripts/run_swarm.py --site demo --version v0 ...` (flags come from this signature)."""
    swarm_main(site=site, version=version, models=models, agents=agents, tasks=tasks, local=local,
               site_base_url=site_base_url or None, concurrency=concurrency, run_id=run_id or None,
               use_llm_judge=llm_judge, limit=limit or None, budget_usd=budget_usd or None, yes=yes)


def _cli() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--site", default="demo")
    p.add_argument("--version", default="v0")
    p.add_argument("--tasks", default="demo_site/tasks.json", help="tasks JSON file, or 'generate'")
    p.add_argument("--models", default=DEFAULT_MODELS,
                   help="comma-separated model ids and/or selectors: cheapest:N, vision, all, default, mock "
                        "(see abtract/models/registry.py)")
    p.add_argument("--agents", default="text,dom,vision", help="comma-separated: text,dom,vision")
    p.add_argument("--site-base-url", default="", help="deployed site server URL (cloud runs)")
    p.add_argument("--local", action="store_true", help="run agents in-process and serve the site locally")
    p.add_argument("--concurrency", type=int, default=8)
    p.add_argument("--run-id", default="")
    p.add_argument("--limit", type=int, default=0, help="only the first N tasks")
    p.add_argument("--no-llm-judge", action="store_true", help="never ask Gemini to grade answers")
    p.add_argument("--budget-usd", type=float, default=0.0,
                   help="refuse estimates above this and stop scheduling at the allowance; running calls may overshoot")
    p.add_argument("--yes", "-y", action="store_true", help="do not ask for confirmation when the estimate is > $5")
    a = p.parse_args()
    kwargs = dict(site=a.site, version=a.version, models=a.models, agents=a.agents, tasks=a.tasks, local=a.local,
                  site_base_url=a.site_base_url or None, concurrency=a.concurrency, run_id=a.run_id or None,
                  use_llm_judge=not a.no_llm_judge, limit=a.limit or None, budget_usd=a.budget_usd or None, yes=a.yes)
    if a.local:
        swarm_main(**kwargs)
    else:  # plain python without `modal run`: start an ephemeral app so run_episode.map works
        import modal
        from abtract.config import settings

        if not (a.site_base_url or settings.site_base_url):
            raise SystemExit("cloud runs need --site-base-url or ABTRACT_SITE_BASE_URL (or use --local)")
        with modal.enable_output(), app.run():
            swarm_main(**kwargs)


if __name__ == "__main__":
    _cli()
