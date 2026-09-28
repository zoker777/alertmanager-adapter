"""Alertmanager input and platform-independent notification models."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Alert(BaseModel):
    model_config = ConfigDict(extra="ignore")

    status: Literal["firing", "resolved"]
    labels: dict[str, str]
    annotations: dict[str, str] = Field(default_factory=dict)
    startsAt: datetime | None = None
    endsAt: datetime | None = None


class AlertmanagerPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    receiver: str
    status: Literal["firing", "resolved"]
    groupLabels: dict[str, str] = Field(default_factory=dict)
    commonLabels: dict[str, str] = Field(default_factory=dict)
    commonAnnotations: dict[str, str] = Field(default_factory=dict)
    alerts: list[Alert] = Field(min_length=1)


class NotificationAlert(BaseModel):
    status: str
    alertname: str
    namespace: str = ""
    pod: str = ""
    container: str = ""
    summary: str = ""
    description: str = ""
    starts_at: datetime | None = None


class NotificationMessage(BaseModel):
    status: str
    alertname: str
    severity: str
    environment: str
    team: str
    namespace: str = ""
    summary: str = ""
    description: str = ""
    alerts_count: int
    starts_at: datetime | None = None
    alerts: list[NotificationAlert]
    label_fallback: bool = False
