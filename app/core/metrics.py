from prometheus_client import Counter, Histogram

REQUESTS = Counter(
    "alertmanager_adapter_requests_total", "Alertmanager webhook requests", ["status"]
)
NOTIFICATIONS = Counter(
    "alertmanager_adapter_notifications_total", "Notifications by outcome",
    ["environment", "severity", "team", "channel", "status"],
)
FAILURES = Counter(
    "alertmanager_adapter_notification_failures_total", "Failed notifications",
    ["environment", "severity", "team", "channel"],
)
DURATION = Histogram(
    "alertmanager_adapter_notification_duration_seconds", "Notification delivery duration",
    ["environment", "severity", "team", "channel"],
)
ROUTE_FALLBACK = Counter(
    "alertmanager_adapter_route_fallback_total", "Default routes used",
    ["environment", "severity", "team"],
)
