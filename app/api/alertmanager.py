from fastapi import APIRouter, Request

from app.core.metrics import REQUESTS
from app.models.alertmanager import AlertmanagerPayload

router = APIRouter()


@router.post("/api/v1/alertmanager")
async def receive_alertmanager(payload: AlertmanagerPayload, request: Request) -> dict:
    result = await request.app.state.dispatcher.dispatch(payload)
    REQUESTS.labels(result["status"]).inc()
    return result
