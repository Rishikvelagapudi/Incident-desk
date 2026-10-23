import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import notifier
from config import SMTP_FROM, ALERT_EMAIL_TO


def test_build_email_default():
    inc = {
        "id": "INC-2026-001",
        "category": "Road safety",
        "label": "Possible vehicle collision",
        "short": "Road Accident",
        "severity": "critical",
        "camera_id": "CAM-01",
        "camera_name": "Main Intersection",
        "video_ts_text": "00:15",
        "detected_at": "2026-10-20T01:00:00Z",
        "review_status": "awaiting_review",
        "summary": "A possible vehicle collision was detected by CAM-01 at video time 00:15.",
    }
    msg = notifier.build(inc)
    assert msg["From"] == "rishikvelagapudi@gmail.com"
    assert msg["To"] == "rishikvelagapudi@gmail.com"
    content = msg.get_body(preferencelist=("plain",)).get_content()
    assert "/incidents/INC-2026-001" in content
    assert "Short Description" in content
    assert inc["summary"] in content


def test_build_email_dynamic_recipient():
    inc = {
        "id": "INC-2026-002",
        "category": "Public safety",
        "label": "Possible person fall",
        "short": "Person Fall",
        "severity": "high",
        "camera_id": "CAM-02",
        "camera_name": "Lobby Area",
        "video_ts_text": "01:20",
        "detected_at": "2026-10-20T01:05:00Z",
        "review_status": "awaiting_review",
        "summary": "A person fall was detected near the entrance.",
    }
    custom_email = "dynamic_user@example.com"
    msg = notifier.build(inc, custom_email)
    assert msg["From"] == "rishikvelagapudi@gmail.com"
    assert msg["To"] == custom_email
    content = msg.get_body(preferencelist=("plain",)).get_content()
    assert "/incidents/INC-2026-002" in content
    assert inc["summary"] in content


def test_send_email_outbox_fallback(monkeypatch):
    monkeypatch.setattr("notifier.SMTP_HOST", "")
    inc = {
        "id": "INC-2026-003",
        "category": "Industrial safety",
        "label": "Possible unauthorized entry",
        "short": "Restricted-Zone Entry",
        "severity": "high",
        "camera_id": "CAM-03",
        "camera_name": "Gate 4",
        "video_ts_text": "02:10",
        "detected_at": "2026-10-20T01:10:00Z",
        "review_status": "awaiting_review",
        "summary": "Unauthorized entry into restricted zone.",
    }
    res = notifier.send(inc, "rishikvelagapudi@gmail.com")
    assert res["status"] in ("sent", "logged")
    assert res["to"] == "rishikvelagapudi@gmail.com"


def test_build_sms():
    inc = {
        "id": "INC-2026-004",
        "category": "Road safety",
        "label": "Possible vehicle collision",
        "short": "Road Accident",
        "severity": "critical",
        "camera_id": "CAM-01",
        "camera_name": "Main Intersection",
        "video_ts_text": "00:15",
        "detected_at": "2026-10-20T01:00:00Z",
        "review_status": "awaiting_review",
        "summary": "A possible vehicle collision was detected by CAM-01 at video time 00:15. Review footage.",
    }
    sms_text = notifier.build_sms(inc)
    assert "INC-2026-004" in sms_text
    assert "Road Accident" in sms_text
    assert "Main Intersection" in sms_text
    assert "00:15" in sms_text
    assert "/incidents/INC-2026-004" in sms_text
    assert "Desc:" in sms_text


def test_send_sms_invalid_phone():
    inc = {
        "id": "INC-2026-005",
        "label": "Fire outbreak",
        "short": "Fire Alert",
        "summary": "Smoke detected.",
    }
    res = notifier.send_sms(inc, "12345")
    assert res["status"] == "failed"
    assert "10-digit" in res["detail"]


def test_send_sms_outbox_archive(tmp_path, monkeypatch):
    from config import SMS_OUTBOX_DIR
    inc = {
        "id": "INC-2026-006",
        "label": "Perimeter breach",
        "short": "Security Breach",
        "summary": "Perimeter sensor triggered at fence B.",
        "camera_name": "Fence B",
        "video_ts_text": "03:45",
    }
    res = notifier.send_sms(inc, "9876543210")
    # Even if Fast2SMS fails due to route transaction or network, outbox file must be written
    outbox_file = SMS_OUTBOX_DIR / "INC-2026-006_9876543210.txt"
    assert outbox_file.is_file()
    content = outbox_file.read_text(encoding="utf-8")
    assert "INC-2026-006" in content
    assert "Security Breach" in content
    assert "/incidents/INC-2026-006" in content


def test_get_sms_wallet():
    wallet_info = notifier.get_sms_wallet()
    assert "wallet" in wallet_info
    assert "sms_count" in wallet_info
    assert wallet_info["configured"] is True


def test_get_delivery_report():
    report = notifier.get_delivery_report("fake_request_id_123")
    assert isinstance(report, dict)
    assert "message" in report or "data" in report or "success" in report


def test_build_sms_critical_confirmation():
    critical_inc = {
        "id": "INC-2026-099",
        "category": "Road safety",
        "label": "Possible vehicle collision",
        "short": "Road Accident",
        "severity": "critical",
        "camera_id": "CAM-01",
        "camera_name": "Main Highway",
        "video_ts_text": "00:45",
        "detected_at": "2026-10-22T19:00:00Z",
        "review_status": "awaiting_review",
        "summary": "A high-speed vehicle collision was detected. Bounding boxes overlapped with acute deceleration.",
    }
    sms_text = notifier.build_sms(critical_inc)
    assert "[CRITICAL ALERT - CONFIRMATION REQUIRED]" in sms_text
    assert "INC-2026-099" in sms_text
    assert "Road Accident" in sms_text
    assert "Confirm Link:" in sms_text
    assert "/incidents/INC-2026-099" in sms_text


def test_send_test_message():
    from config import SMS_OUTBOX_DIR
    res = notifier.send_test_message("9876543210", "Custom test notification")
    assert res["status"] in ("sent", "logged", "failed")
    assert res["to"] == "9876543210"
    assert "Custom test notification" in res["text"]
    outbox_file = SMS_OUTBOX_DIR / "TEST_9876543210.txt"
    assert outbox_file.is_file()


def test_build_email_critical_confirmation_banner():
    critical_inc = {
        "id": "INC-2026-101",
        "category": "Road safety",
        "label": "Possible vehicle collision",
        "short": "Road Accident",
        "severity": "critical",
        "camera_id": "CAM-01",
        "camera_name": "Main Highway",
        "video_ts_text": "00:45",
        "detected_at": "2026-10-23T12:00:00Z",
        "review_status": "awaiting_review",
        "summary": "Critical high-velocity vehicle impact detected on CAM-01.",
        "evidence": [],
    }
    msg = notifier.build(critical_inc)
    assert "[CRITICAL ALERT - CONFIRMATION REQUIRED]" in msg["Subject"]
    html_part = next(p for p in msg.iter_parts() if p.get_content_type() == "text/html").get_content()
    assert "IMMEDIATE OPERATOR CONFIRMATION REQUIRED" in html_part
    assert "Review Evidence & Confirm Emergency" in html_part
    assert "/incidents/INC-2026-101" in html_part




