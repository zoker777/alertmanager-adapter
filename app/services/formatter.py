"""Convert Alertmanager groups to a bounded, platform-neutral message."""

from app.models.alertmanager import AlertmanagerPayload, NotificationAlert, NotificationMessage
from app.utils.helpers import display_time


def format_notification(payload: AlertmanagerPayload) -> NotificationMessage:
    first = payload.alerts[0]
    common = payload.commonLabels
    fallback = False

    def label(name: str, default: str = "") -> str:
        nonlocal fallback
        value = common.get(name) or first.labels.get(name)
        if value:
            return value
        if default:
            fallback = True
        return default

    alerts = [
        NotificationAlert(
            status=alert.status,
            alertname=alert.labels.get("alertname", "未知告警"),
            namespace=alert.labels.get("namespace", ""),
            pod=alert.labels.get("pod", ""),
            container=alert.labels.get("container", ""),
            summary=alert.annotations.get("summary", ""),
            description=alert.annotations.get("description", ""),
            starts_at=alert.startsAt,
        )
        for alert in payload.alerts[:10]
    ]
    return NotificationMessage(
        status=payload.status,
        alertname=label("alertname", "未知告警"),
        severity=label("severity", "warning"),
        environment=label("environment", "unknown"),
        team=label("team", "ops"),
        namespace=label("namespace"),
        summary=payload.commonAnnotations.get("summary") or first.annotations.get("summary", ""),
        description=payload.commonAnnotations.get("description") or first.annotations.get("description", ""),
        alerts_count=len(payload.alerts),
        starts_at=first.startsAt,
        alerts=alerts,
        label_fallback=fallback,
    )


def render_text(message: NotificationMessage) -> str:
    title = "🚨 Kubernetes 告警" if message.status == "firing" else "✅ Kubernetes 告警恢复"
    lines = [
        title,
        f"状态：{message.status.upper()}",
        f"级别：{message.severity.upper()}",
        f"环境：{message.environment}",
        f"团队：{message.team}",
        f"告警：{message.alertname}",
        f"当前告警数量：{message.alerts_count}",
    ]
    if message.namespace:
        lines.append(f"Namespace：{message.namespace}")
    if message.summary:
        lines.append(f"摘要：{message.summary}")
    if message.description:
        lines.append(f"描述：{message.description}")
    if message.starts_at:
        lines.append(f"开始时间：{display_time(message.starts_at)}")
    for index, alert in enumerate(message.alerts, 1):
        detail = [f"{index}. {alert.alertname} ({alert.status.upper()})"]
        for name, value in (("Namespace", alert.namespace), ("Pod", alert.pod), ("Container", alert.container)):
            if value:
                detail.append(f"{name}：{value}")
        if alert.description:
            detail.append(f"描述：{alert.description}")
        lines.append(" | ".join(detail))
    if message.alerts_count > len(message.alerts):
        lines.append(f"其余 {message.alerts_count - len(message.alerts)} 条告警已省略")
    return "\n".join(lines)
