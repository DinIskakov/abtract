import os
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

API_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    app_name: str = "Abtract API"
    app_version: str = "0.1.0"
    debug: bool = False
    modal_app_name: str = "uptrack"
    openai_api_key: SecretStr | None = None
    anthropic_api_key: SecretStr | None = None
    cors_origins: list[str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]
    modal_proxy_token: str = ""
    modal_inference_base_url: str = "https://inference.us-west.modal.direct/v1"
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.8-flash"
    dashboard_password: str = Field(
        "", validation_alias="ABTRACT_DASHBOARD_PASSWORD")
    job_swarm_budget_usd: float = Field(
        5, validation_alias="ABTRACT_JOB_SWARM_BUDGET_USD")
    job_swarm_concurrency: int = Field(
        16, validation_alias="ABTRACT_JOB_SWARM_CONCURRENCY")
    data_dir: Path = Field(
        default=Path("/data" if os.path.exists("/data") else "./data"),
        validation_alias="ABTRACT_DATA_DIR",
    )
    site_base_url: str = Field("", validation_alias="ABTRACT_SITE_BASE_URL")
    default_max_steps: int = Field(15, validation_alias="ABTRACT_MAX_STEPS")
    step_timeout_s: int = Field(60, validation_alias="ABTRACT_STEP_TIMEOUT_S")
    episode_timeout_s: int = Field(
        600, validation_alias="ABTRACT_EPISODE_TIMEOUT_S")

    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env", API_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    def site_url(self, site_id: str, version: str) -> str:
        base = self.site_base_url.rstrip("/") or "http://localhost:8000"
        return f"{base}/s/{site_id}/{version}/"


# pydantic-settings resolves validation aliases from the environment
settings = Settings()  # type: ignore[call-arg]
