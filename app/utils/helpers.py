"""Small helpers shared by formatters and senders."""

from datetime import datetime
from zoneinfo import ZoneInfo


def display_time(value: datetime | None) -> str:
    if value is None:
        return "未知"
    return value.astimezone(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M:%S")
