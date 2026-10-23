import sys
from pathlib import Path
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent))

from main import app, store  # noqa: E402


def test_sms_config_endpoints():
    client = TestClient(app)
    # GET /api/sms-config
    res = client.get("/api/sms-config")
    assert res.status_code == 200
    data = res.json()
    assert "default_to_phone" in data
    assert "wallet" in data
    assert "sms_count" in data
    assert "sms_configured" in data

    # POST /api/sms-config
    res_post = client.post("/api/sms-config", json={"to_phone": "9876543210"})
    assert res_post.status_code == 200
    assert res_post.json()["default_to_phone"] == "9876543210"


def test_sms_test_endpoint():
    client = TestClient(app)
    res = client.post("/api/sms/test", json={"to_phone": "9876543210", "message": "Test SMS API"})
    assert res.status_code == 200
    data = res.json()
    assert data["status"] in ("sent", "logged", "failed")
    assert data["to"] == "9876543210"


def test_sms_outbox_endpoint():
    client = TestClient(app)
    res = client.get("/api/sms-outbox")
    assert res.status_code == 200
    data = res.json()
    assert "outbox" in data
    assert isinstance(data["outbox"], list)


def test_audit_logs_endpoint():
    client = TestClient(app)
    # Ensure there is at least one incident with audit data in store
    store.incidents["INC-2026-TEST"] = {
        "id": "INC-2026-TEST",
        "short": "Test Incident",
        "label": "Test Incident Label",
        "camera_id": "CAM-01",
        "camera_name": "Test Cam",
        "audit": [{"at": "2026-10-23T10:00:00Z", "actor": "agent", "action": "Detected incident"}],
        "access_log": [{"at": "2026-10-23T10:05:00Z", "user": "operator"}],
    }

    res = client.get("/api/audit-logs")
    assert res.status_code == 200
    data = res.json()
    assert "audit_logs" in data
    assert "access_logs" in data
    assert len(data["audit_logs"]) >= 1
    found = any(log["incident_id"] == "INC-2026-TEST" for log in data["audit_logs"])
    assert found
