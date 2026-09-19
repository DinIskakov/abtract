"""Modal entrypoint. Importing the submodules registers their functions on the shared `app`.

modal deploy apps/api/deploy.py       # persistent URLs
modal serve apps/api/deploy.py        # hot-reloading dev URLs
"""

# Side-effect imports: each of these attaches @app.function(...) definitions to `app`.
import app.hosting.serve  # noqa: E402,F401  site server:   /s/{site_id}/{version}/...
import app.jobs  # noqa: E402,F401  run_job (intake / loop jobs started from the dashboard)
import app.optimizer.rewrite  # noqa: E402,F401  optimize_site
import app.routers.product  # noqa: E402,F401  product API
import app.swarm.runner  # noqa: E402,F401   run_episode / run_swarm
from app.modal_app import app  # noqa: F401
