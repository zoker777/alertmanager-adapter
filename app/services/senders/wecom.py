from app.models.alertmanager import NotificationMessage
from app.services.formatter import render_text
from app.services.senders.base import BaseSender


class WeComSender(BaseSender):
    def make_payload(self, message: NotificationMessage) -> dict:
        return {"msgtype": "markdown", "markdown": {"content": render_text(message)}}

    def is_platform_success(self, data: dict) -> bool:
        return data.get("errcode") == 0
