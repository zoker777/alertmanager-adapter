from app.services.formatter import format_notification, render_text


def test_firing_and_resolution(firing):
    firing_message = format_notification(firing)
    text = render_text(firing_message)
    assert "🚨 Kubernetes 告警" in text
    assert "order-service-7f987" in text
    assert "2026-09-23 16:00:00" in text
    resolved = firing.model_copy(update={"status": "resolved"})
    assert "✅ Kubernetes 告警恢复" in render_text(format_notification(resolved))


def test_label_defaults(firing):
    payload = firing.model_copy(deep=True)
    for key in ("environment", "severity", "team"):
        payload.commonLabels.pop(key)
        payload.alerts[0].labels.pop(key)
    message = format_notification(payload)
    assert (message.environment, message.severity, message.team) == ("unknown", "warning", "ops")
    assert message.label_fallback


def test_common_label_first_and_first_alert_fallback(firing):
    payload = firing.model_copy(deep=True)
    payload.commonLabels["team"] = "backend"
    payload.commonLabels.pop("environment")
    message = format_notification(payload)
    assert message.team == "backend"
    assert message.environment == "production"
    assert not message.label_fallback


def test_group_is_bounded(firing):
    payload = firing.model_copy(deep=True)
    payload.alerts = payload.alerts * 25
    message = format_notification(payload)
    assert message.alerts_count == 25
    assert len(message.alerts) == 10
    assert "其余 15 条告警已省略" in render_text(message)
