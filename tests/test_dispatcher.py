import asyncio
import logging

import httpx
import pytest

from app.core.router import Router
from app.core.logging import configure_logging
from app.services.dispatcher import Dispatcher
from app.services.senders.base import SendResult


@pytest.mark.asyncio
async def test_channel_failure_is_isolated_and_concurrent(config, firing, monkeypatch):
    for name in ("PROD_OPS_FEISHU_WEBHOOK", "PROD_OPS_DINGTALK_WEBHOOK", "PROD_OPS_WECOM_WEBHOOK"):
        monkeypatch.setenv(name, f"https://example.invalid/{name}")
    async with httpx.AsyncClient() as client:
        dispatcher = Dispatcher(Router(config), client)
        active = 0
        peak = 0
        async def send_success(url, message):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            await asyncio.sleep(0.01)
            active -= 1
            return SendResult(True, 200)
        async def send_failure(url, message):
            await asyncio.sleep(0.01)
            return SendResult(False, 500, "RetryableDeliveryError")
        dispatcher.senders["feishu"].send = send_success
        dispatcher.senders["dingtalk"].send = send_failure
        dispatcher.senders["wecom"].send = send_success
        result = await dispatcher.dispatch(firing)
    assert result["status"] == "partial_success"
    assert result["channels"] == {"feishu": "success", "dingtalk": "failed", "wecom": "success"}
    assert peak == 2


@pytest.mark.asyncio
async def test_missing_secret_does_not_leak_url(config, firing, monkeypatch, caplog):
    token = "top-secret-token"
    monkeypatch.setenv("PROD_OPS_FEISHU_WEBHOOK", f"https://example.invalid/{token}")
    monkeypatch.delenv("PROD_OPS_DINGTALK_WEBHOOK", raising=False)
    monkeypatch.delenv("PROD_OPS_WECOM_WEBHOOK", raising=False)
    async with httpx.AsyncClient() as client:
        dispatcher = Dispatcher(Router(config), client)
        async def raise_secret(url, message):
            raise RuntimeError(f"failed at {url}")
        dispatcher.senders["feishu"].send = raise_secret
        with caplog.at_level(logging.ERROR):
            result = await dispatcher.dispatch(firing)
    assert result["status"] == "failed"
    assert token not in caplog.text
    assert "https://example.invalid" not in caplog.text


def test_http_client_access_log_is_suppressed():
    import logging
    configure_logging()
    assert logging.getLogger("httpx").getEffectiveLevel() > logging.INFO
    assert logging.getLogger("httpcore").getEffectiveLevel() > logging.INFO


@pytest.mark.asyncio
async def test_fallback_uses_default_ref(config, firing, monkeypatch):
    payload = firing.model_copy(deep=True)
    payload.commonLabels["team"] = "unknown-team"
    monkeypatch.setenv("DEFAULT_FEISHU_WEBHOOK", "https://example.invalid/default")
    async with httpx.AsyncClient() as client:
        dispatcher = Dispatcher(Router(config), client)
        urls = []
        async def capture(url, message):
            urls.append(url)
            return SendResult(True, 200)
        dispatcher.senders["feishu"].send = capture
        result = await dispatcher.dispatch(payload)
    assert result["status"] == "success"
    assert urls == ["https://example.invalid/default"]
