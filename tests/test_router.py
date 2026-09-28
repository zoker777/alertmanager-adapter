import pytest
from pydantic import ValidationError

from app.core.config import AppConfig
from app.core.router import Router


@pytest.mark.parametrize("environment,severity,team,channels", [
    ("production", "critical", "ops", ["feishu", "dingtalk", "wecom"]),
    ("production", "warning", "ops", ["feishu"]),
    ("production", "critical", "backend", ["feishu", "dingtalk"]),
    ("test", "critical", "ops", ["feishu"]),
    ("test", "critical", "ops-dingtalk-smoke", ["dingtalk"]),
])
def test_exact_routes(config, environment, severity, team, channels):
    result = Router(config).resolve(environment, severity, team)
    assert result.matched
    assert result.channels == channels


def test_default_route(config):
    result = Router(config).resolve("unknown", "warning", "ops")
    assert not result.matched
    assert result.webhook_refs == {"feishu": "DEFAULT_FEISHU_WEBHOOK"}


def test_invalid_route_rejected(config):
    data = config.model_dump()
    data["routing"]["routes"][0]["channels"] = ["slack"]
    with pytest.raises(ValidationError):
        AppConfig.model_validate(data)


def test_missing_webhook_mapping_rejected(config):
    data = config.model_dump()
    del data["webhooks"]["production"]["ops"]["wecom"]
    with pytest.raises(ValidationError):
        AppConfig.model_validate(data)


def test_webhook_url_cannot_be_committed_in_config(config):
    data = config.model_dump()
    data["webhooks"]["production"]["ops"]["feishu"] = "https://example.invalid/secret"
    with pytest.raises(ValidationError):
        AppConfig.model_validate(data)
