"""The single Modal App every cloud piece registers on, plus shared images, volume and secrets.

Deploy everything with:   modal deploy apps/api/deploy.py
Dev-serve with:           modal serve apps/api/deploy.py

Secrets: fill .env.modal from .env.modal.example, then run
  modal secret create abtract-secrets --from-dotenv .env.modal
"""

from __future__ import annotations

import os

import modal

APP_NAME = "abtract"
DATA_DIR = "/data"

app = modal.App(APP_NAME)

data_volume = modal.Volume.from_name("abtract-data", create_if_missing=True)
volumes = {DATA_DIR: data_volume}

secrets = [modal.Secret.from_name("abtract-secrets")]

_PY_DEPS = [
    "pydantic>=2.7",
    "openai>=1.50",
    "google-genai>=1.20",
    "httpx>=0.27",
    "playwright>=1.47",
    "fastapi[standard]>=0.115",
    "beautifulsoup4>=4.12",
    "lxml>=5.0",
    "markdownify>=0.13",
    "python-dotenv>=1.0",
    "rich>=13.0",
]

_base_build = modal.Image.debian_slim(python_version="3.12").pip_install(*_PY_DEPS).env({"ABTRACT_DATA_DIR": DATA_DIR})

# Lightweight image: store, dashboard, site server, optimizer, text agent.
base_image = _base_build.add_local_python_source("app")

# Browser image: Playwright + Chromium for the dom and vision agents.
browser_image = _base_build.run_commands(
    "playwright install-deps chromium",
    "playwright install chromium",
).add_local_python_source("app")

# Sandbox image for validating Gemini-written sites (untrusted code never runs in our own containers).
sandbox_image = modal.Image.debian_slim(python_version="3.12").pip_install(
    "beautifulsoup4>=4.12", "lxml>=5.0", "html5lib>=1.1"
)


def running_on_modal() -> bool:
    return bool(os.environ.get("MODAL_TASK_ID")) or os.path.isdir(DATA_DIR) and not modal.is_local()
