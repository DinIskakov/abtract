from datetime import UTC, datetime

from fastapi import APIRouter
from pydantic import BaseModel

from app.config import settings

router = APIRouter(prefix="/health", tags=["Health"])


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str
    timestamp: str


@router.get("", response_model=HealthResponse)
async def check_health() -> HealthResponse:
    return HealthResponse(
        status="healthy",
        service=settings.app_name,
        version=settings.app_version,
        timestamp=datetime.now(UTC).isoformat(),
    )
