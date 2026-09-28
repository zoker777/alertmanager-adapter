"""Exact route matching with a required default route."""

from dataclasses import dataclass

from app.core.config import AppConfig, Channel


@dataclass(frozen=True)
class RouteResult:
    channels: list[Channel]
    webhook_refs: dict[Channel, str]
    matched: bool


class Router:
    def __init__(self, config: AppConfig):
        self.config = config
        self._routes = {
            (route.environment, route.severity, route.team): route
            for route in config.routing.routes
        }

    def resolve(self, environment: str, severity: str, team: str) -> RouteResult:
        route = self._routes.get((environment, severity, team))
        if route is None:
            default = self.config.routing.default
            return RouteResult(default.channels, default.webhook_ref, False)
        refs = self.config.webhooks[environment][team]
        return RouteResult(route.channels, {channel: refs[channel] for channel in route.channels}, True)
