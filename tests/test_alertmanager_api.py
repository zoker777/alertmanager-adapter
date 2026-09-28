from fastapi.testclient import TestClient

from app.main import app


def test_valid_payload_and_probes(config, firing, monkeypatch):
    monkeypatch.setenv("CONFIG_PATH", "config/config.yaml")
    with TestClient(app) as client:
        async def fake_dispatch(payload):
            return {"status": "partial_success", "environment": "production", "severity": "critical", "team": "ops", "channels": {"feishu": "success", "dingtalk": "failed"}}
        app.state.dispatcher.dispatch = fake_dispatch
        response = client.post("/api/v1/alertmanager", json=firing.model_dump(mode="json"))
        assert response.status_code == 200
        assert response.json()["status"] == "partial_success"
        assert client.get("/healthz").status_code == 200
        assert client.get("/readyz").status_code == 200
        metrics = client.get("/metrics")
        assert metrics.status_code == 200
        assert "alertmanager_adapter_requests_total" in metrics.text


def test_invalid_payload(monkeypatch):
    monkeypatch.setenv("CONFIG_PATH", "config/config.yaml")
    with TestClient(app) as client:
        assert client.post("/api/v1/alertmanager", content="{").status_code == 422
        assert client.post("/api/v1/alertmanager", json={"status": "firing"}).status_code == 422
