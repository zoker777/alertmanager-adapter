"""Shared HTTP transport, retry policy and result type for robot webhooks."""

from abc import ABC, abstractmethod
from dataclasses import dataclass

import httpx
from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.models.alertmanager import NotificationMessage


@dataclass(frozen=True)
class SendResult:
    success: bool
    http_status: int | None = None
    error_type: str | None = None


class RetryableDeliveryError(Exception):
    def __init__(self, http_status: int | None = None):
        self.http_status = http_status
        super().__init__("retryable delivery failure")


class DeliveryError(Exception):
    def __init__(self, http_status: int | None = None):
        self.http_status = http_status
        super().__init__("delivery failure")


class BaseSender(ABC):
    def __init__(self, client: httpx.AsyncClient):
        self.client = client

    @abstractmethod
    def make_payload(self, message: NotificationMessage) -> dict:
        ...

    @abstractmethod
    def is_platform_success(self, data: dict) -> bool:
        ...

    async def send(self, webhook_url: str, message: NotificationMessage) -> SendResult:
        try:
            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(3),
                wait=wait_exponential(multiplier=1, min=1, max=4),
                retry=retry_if_exception_type((RetryableDeliveryError, httpx.TimeoutException, httpx.ConnectError)),
                reraise=True,
            ):
                with attempt:
                    response = await self.client.post(webhook_url, json=self.make_payload(message), timeout=5.0)
                    if response.status_code in (408, 429) or 500 <= response.status_code <= 599:
                        raise RetryableDeliveryError(response.status_code)
                    if response.status_code >= 400:
                        raise DeliveryError(response.status_code)
                    try:
                        data = response.json()
                    except ValueError:
                        raise DeliveryError(response.status_code) from None
                    if not isinstance(data, dict) or not self.is_platform_success(data):
                        raise DeliveryError(response.status_code)
                    return SendResult(True, response.status_code)
        except (RetryableDeliveryError, DeliveryError) as exc:
            return SendResult(False, exc.http_status, type(exc).__name__)
        except httpx.RequestError as exc:
            return SendResult(False, None, type(exc).__name__)
        return SendResult(False, None, "UnexpectedDeliveryState")
