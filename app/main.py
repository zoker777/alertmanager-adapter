"""FastAPI application and process lifecycle."""

from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Response
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from pydantic import ValidationError
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

from app.api.alertmanager import router as alertmanager_router
from app.core.config import load_config
from app.core.logging import configure_logging, logger
from app.core.metrics import REQUESTS
from app.core.router import Router
from app.services.dispatcher import Dispatcher


@asynccontextmanager
async def lifespan(application: FastAPI):
    configure_logging()
    try:
        config = load_config()
    except ValidationError as exc:
        fields = [".".join(map(str, error["loc"])) or "root" for error in exc.errors()]
        logger.error("configuration validation failed", extra={"error_type": "ValidationError", "fields": fields})
        raise
    except Exception as exc:
        logger.error("configuration loading failed", extra={"error_type": type(exc).__name__})
        raise
    application.state.config = config
    application.state.router = Router(config)
    async with httpx.AsyncClient() as client:
        application.state.dispatcher = Dispatcher(application.state.router, client)
        logger.info("configuration loaded")
        yield


app = FastAPI(title="Alertmanager Adapter", lifespan=lifespan)
app.include_router(alertmanager_router)


@app.exception_handler(RequestValidationError)
async def invalid_payload(request, exc: RequestValidationError):
    if request.url.path == "/api/v1/alertmanager":
        REQUESTS.labels("invalid").inc()
    return await request_validation_exception_handler(request, exc)


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


@app.get("/readyz")
def readyz() -> dict:
    return {"status": "ready"} if hasattr(app.state, "router") else Response(status_code=503)


@app.get("/metrics")
def metrics() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
