"""Modal entrypoint. Importing the submodules registers their functions on the shared `app`.

    modal deploy deploy.py       # persistent URLs
    modal serve deploy.py        # hot-reloading dev URLs
"""
from abtract.modal_app import app  # noqa: F401

# Side-effect imports: each of these attaches @app.function(...) definitions to `app`.
import abtract.hosting.serve  # noqa: E402,F401  site server:   /s/{site_id}/{version}/...
import abtract.dashboard.app  # noqa: E402,F401  dashboard:     /
import abtract.swarm.runner  # noqa: E402,F401   run_episode / run_swarm
import abtract.optimizer.rewrite  # noqa: E402,F401  optimize_site
import abtract.jobs  # noqa: E402,F401  run_job (intake / loop jobs started from the dashboard)
