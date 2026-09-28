import httpx
import pytest

from app.services.formatter import format_notification
from app.services.senders.dingtalk import DingTalkSender
from app.services.senders.feishu import FeishuSender
from app.services.senders.wecom import WeComSender


@pytest.mark.asyncio
async def test_feishu_success(firing):
    def handler(request):
        assert request.url.path == "/feishu"
        assert b'"msg_type":"post"' in request.content
        return httpx.Response(200, json={"code": 0})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await FeishuSender(client).send("https://example.invalid/feishu", format_notification(firing))
    assert result.success


@pytest.mark.asyncio
async def test_dingtalk_retries_500(monkeypatch, firing):
    calls = 0
    def handler(request):
        nonlocal calls
        calls += 1
        assert b'"msgtype":"markdown"' in request.content
        return httpx.Response(500 if calls == 1 else 200, json={"errcode": 0})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await DingTalkSender(client).send("https://example.invalid/dingtalk", format_notification(firing))
    assert result.success
    assert calls == 2


@pytest.mark.asyncio
async def test_wecom_timeout_final_failure(firing):
    calls = 0
    def handler(request):
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("secret-in-exception", request=request)
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await WeComSender(client).send("https://example.invalid/wecom", format_notification(firing))
    assert not result.success
    assert result.error_type == "ReadTimeout"
    assert calls == 3


@pytest.mark.asyncio
async def test_dingtalk_400_does_not_retry(firing):
    calls = 0
    def handler(request):
        nonlocal calls
        calls += 1
        return httpx.Response(400, json={"errcode": 1})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        result = await DingTalkSender(client).send("https://example.invalid/dingtalk", format_notification(firing))
    assert not result.success
    assert calls == 1
