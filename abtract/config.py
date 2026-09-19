"""Environment-driven settings. Import `settings` and read attributes; nothing here touches the network."""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()  # no-op if there is no .env


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


class Settings:
    # Modal hosted inference (OpenAI-compatible)
    modal_proxy_token: str = _env("MODAL_PROXY_TOKEN")
    modal_inference_base_url: str = _env("MODAL_INFERENCE_BASE_URL", "https://inference.us-west.modal.direct/v1")

    # Gemini
    gemini_api_key: str = _env("GEMINI_API_KEY")
    gemini_model: str = _env("GEMINI_MODEL", "gemini-3.8-flash")
    dashboard_password: str = _env("ABTRACT_DASHBOARD_PASSWORD")
    job_swarm_budget_usd: float = float(_env("ABTRACT_JOB_SWARM_BUDGET_USD", "5"))
    job_swarm_concurrency: int = int(_env("ABTRACT_JOB_SWARM_CONCURRENCY", "16"))

    # Storage. On Modal the Volume is mounted at /data (see abtract/modal_app.py).
    data_dir: Path = Path(_env("ABTRACT_DATA_DIR", "/data" if os.path.exists("/data") else "./data"))

    # Public URL where site versions are served, e.g. https://ws--abtract-site-server.modal.run
    site_base_url: str = _env("ABTRACT_SITE_BASE_URL").rstrip("/")

    # Agent loop defaults
    default_max_steps: int = int(_env("ABTRACT_MAX_STEPS", "15"))
    step_timeout_s: int = int(_env("ABTRACT_STEP_TIMEOUT_S", "60"))
    episode_timeout_s: int = int(_env("ABTRACT_EPISODE_TIMEOUT_S", "600"))

    def site_url(self, site_id: str, version: str) -> str:
        """URL of the root of one hosted site version. Site server mounts versions at /s/{site_id}/{version}/."""
        base = self.site_base_url or "http://localhost:8000"
        return f"{base}/s/{site_id}/{version}/"


settings = Settings()
