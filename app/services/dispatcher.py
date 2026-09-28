"""Resolve a route and dispatch each channel independently and concurrently."""

import asyncio
import logging
import os
import time
from uuid import uuid4

import httpx

from app.core.logging import logger
from app.core.metrics import DURATION, FAILURES, NOTIFICATIONS, ROUTE_FALLBACK
from app.core.router import Router
from app.models.alertmanager import AlertmanagerPayload
from app.services.formatter import format_notification
from app.services.senders.base import BaseSender, SendResult
from app.services.senders.dingtalk import DingTalkSender
from app.services.senders.feishu import FeishuSender
from app.services.senders.wecom import WeComSender


class Dispatcher:
    def __init__(self, router: Router, client: httpx.AsyncClient):
        self.router = router
        self.senders: dict[str, BaseSender] = {
            "feishu": FeishuSender(client),
            "dingtalk": DingTalkSender(client),
            "wecom": WeComSender(client),
        }

    async def dispatch(self, payload: AlertmanagerPayload, request_id: str | None = None) -> dict:
        request_id = request_id or uuid4().hex
        message = format_notification(payload)
        route = self.router.resolve(message.environment, message.severity, message.team)
        context = {
            "request_id": request_id,
            "alertname": message.alertname,
            "environment": message.environment,
            "severity": message.severity,
            "team": message.team,
            "route_match": route.matched,
            "fallback": not route.matched or message.label_fallback,
        }
        if message.label_fallback:
            logger.warning("routing label default used", extra={**context, "route_fallback": True})
        if not route.matched:
            ROUTE_FALLBACK.labels(message.environment, message.severity, message.team).inc()
            logger.warning("default route used", extra={**context, "route_fallback": True})

        async def deliver(channel: str) -> tuple[str, str]:
            started = time.monotonic()
            webhook = os.getenv(route.webhook_refs[channel])
            if webhook:
                try:
                    result = await self.senders[channel].send(webhook, message)
                except Exception as exc:
                    # Isolate unexpected sender errors. Never serialize exception text; it can contain URLs.
                    result = SendResult(False, None, type(exc).__name__)
            else:
                result = SendResult(False, None, "MissingWebhookEnv")
            status = "success" if result.success else "failed"
            duration = time.monotonic() - started
            labels = (message.environment, message.severity, message.team, channel)
            NOTIFICATIONS.labels(*labels, status).inc()
            DURATION.labels(*labels).observe(duration)
            if not result.success:
                FAILURES.labels(*labels).inc()
            logger.log(
                logging.INFO if result.success else logging.ERROR,
                "notification delivery completed",
                extra={**context, "channel": channel, "status": status,
                       "http_status": result.http_status, "duration_ms": round(duration * 1000),
                       "error_type": result.error_type},
            )
            return channel, status

        outcomes = await asyncio.gather(*(deliver(channel) for channel in route.channels))
        channels = dict(outcomes)
        successes = sum(status == "success" for status in channels.values())
        overall = "success" if successes == len(channels) else "partial_success" if successes else "failed"
        return {
            "status": overall,
            "environment": message.environment,
            "severity": message.severity,
            "team": message.team,
            "channels": channels,
        }
