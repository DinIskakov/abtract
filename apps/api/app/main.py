from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.hosting.serve import create_app as create_site_app
from app.routers import health, runs
from app.routers.product import create_app as create_product_app


def create_app() -> FastAPI:
    application = create_product_app()
    application.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    application.include_router(health.router, prefix="/api")
    application.include_router(runs.router, prefix="/api")

    @application.get("/")
    async def root() -> dict[str, str]:
        return {
            "message": f"Welcome to {settings.app_name}",
            "docs": "/api/docs",
            "health": "/api/health",
        }

    # The hosted test sites are backend resources and share the API process locally.
    # This keeps one Python server and avoids a second port or launch command.
    application.mount("/", create_site_app())

    return application


app = create_app()
