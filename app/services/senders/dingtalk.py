from app.models.alertmanager import NotificationMessage
from app.services.formatter import render_text
from app.services.senders.base import BaseSender


class DingTalkSender(BaseSender):
    def make_payload(self, message: NotificationMessage) -> dict:
        title = "Kubernetes Critical Alert" if message.status == "firing" else "Kubernetes Alert Resolved"
        return {"msgtype": "markdown", "markdown": {
            "title": title,
            "text": render_text(message).replace("\n", "  \n"),
        }}

    def is_platform_success(self, data: dict) -> bool:
        return data.get("errcode") == 0
