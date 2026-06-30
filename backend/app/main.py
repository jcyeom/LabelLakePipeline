"""FastAPI application entrypoint (backend_design_prd 애플리케이션 레이어링)."""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.routers import (
    alerts,
    audit,
    dashboard,
    datasets,
    drift,
    fusion,
    gold,
    labels,
    reviews,
    runs,
)
from app.config import get_settings
from app.db import init_db
from app.errors import (
    LLPError,
    http_exception_handler,
    llp_error_handler,
    validation_exception_handler,
)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Startup: create tables (MVP). Production uses Alembic migrations instead.
    init_db()
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allow_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Every error path returns the same ErrorResponse envelope (error_code/message/details).
    app.add_exception_handler(LLPError, llp_error_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(RequestValidationError, validation_exception_handler)

    for module in (labels, fusion, reviews, drift, datasets, gold, audit, dashboard, alerts, runs):
        app.include_router(module.router)

    @app.get("/health", tags=["meta"])
    def health() -> dict:
        return {"status": "ok", "app": settings.app_name}

    return app


app = create_app()
