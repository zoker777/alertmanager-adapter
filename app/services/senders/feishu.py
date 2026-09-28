from app.models.alertmanager import NotificationMessage
from app.services.formatter import render_text
from app.services.senders.base import BaseSender


class FeishuSender(BaseSender):
    def make_payload(self, message: NotificationMessage) -> dict:
        return {
            "msg_type": "post",
            "content": {"post": {"zh_cn": {
                "title": "Kubernetes 告警" if message.status == "firing" else "Kubernetes 告警恢复",
                "content": [[{"tag": "text", "text": line}] for line in render_text(message).splitlines()],
            }}},
        }

    def is_platform_success(self, data: dict) -> bool:
        return data.get("code", data.get("StatusCode")) == 0
