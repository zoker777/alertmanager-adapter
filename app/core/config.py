"""Load and validate the ConfigMap-backed application configuration."""

import os
import re
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Channel = Literal["feishu", "dingtalk", "wecom"]
ENV_REF = re.compile(r"^[A-Z_][A-Z0-9_]*$")


def validate_env_ref(value: str) -> str:
    if not ENV_REF.fullmatch(value):
        raise ValueError("webhook reference must be an environment variable name")
    return value


class ServerConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    host: str = "0.0.0.0"
    port: int = Field(default=8080, ge=1, le=65535)


class Route(BaseModel):
    model_config = ConfigDict(extra="forbid")
    environment: str = Field(min_length=1)
    severity: str = Field(min_length=1)
    team: str = Field(min_length=1)
    channels: list[Channel] = Field(min_length=1)

    @field_validator("environment", "severity", "team")
    @classmethod
    def nonblank(cls, value: str) -> str:
        value = value.strip()
        if not value or value == "*":
            raise ValueError("must be a nonblank exact-match value")
        return value

    @field_validator("channels")
    @classmethod
    def unique_channels(cls, value: list[Channel]) -> list[Channel]:
        if len(value) != len(set(value)):
            raise ValueError("duplicate channels")
        return value


class DefaultRoute(BaseModel):
    model_config = ConfigDict(extra="forbid")
    channels: list[Channel] = Field(min_length=1)
    webhook_ref: dict[Channel, str]

    @model_validator(mode="after")
    def check_refs(self) -> "DefaultRoute":
        if len(self.channels) != len(set(self.channels)):
            raise ValueError("duplicate default channels")
        if set(self.channels) != set(self.webhook_ref):
            raise ValueError("default webhook_ref must cover exactly the default channels")
        for ref in self.webhook_ref.values():
            validate_env_ref(ref)
        return self


class RoutingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    routes: list[Route] = Field(min_length=1)
    default: DefaultRoute


class AppConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    server: ServerConfig = Field(default_factory=ServerConfig)
    routing: RoutingConfig
    webhooks: dict[str, dict[str, dict[Channel, str]]]

    @model_validator(mode="after")
    def check_routes(self) -> "AppConfig":
        seen: set[tuple[str, str, str]] = set()
        for route in self.routing.routes:
            key = (route.environment, route.severity, route.team)
            if key in seen:
                raise ValueError(f"duplicate route: {key}")
            seen.add(key)
            targets = self.webhooks.get(route.environment, {}).get(route.team, {})
            for channel in route.channels:
                if not targets.get(channel):
                    raise ValueError(f"missing webhook reference for {route.environment}/{route.team}/{channel}")
        for environment, teams in self.webhooks.items():
            if not environment.strip() or not teams:
                raise ValueError("webhooks must contain nonblank environments and teams")
            for team, channels in teams.items():
                if not team.strip() or not channels:
                    raise ValueError(f"invalid webhook mapping for {environment}/{team}")
                for ref in channels.values():
                    validate_env_ref(ref)
        return self


def load_config(path: str | None = None) -> AppConfig:
    path = path or os.getenv("CONFIG_PATH", "/app/config/config.yaml")
    try:
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ValueError(f"cannot load config at {path}: {exc}") from exc
    return AppConfig.model_validate(data)
