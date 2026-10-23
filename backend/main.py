import asyncio
import logging
import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, Optional

from fastapi import Depends, FastAPI, File, HTTPException, Request, Response, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import auth
from agents import now_iso, sha256_file
import notifier
from config import (ALERT_EMAIL_TO, ALERT_SMS_TO, ANALYSIS_SPEED, EVIDENCE_DIR,
                    FAST2SMS_API_KEY, MAX_CAMERAS, PUBLIC_URL, SMS_OUTBOX_DIR,
                    SMTP_FROM, SMTP_HOST, UPLOAD_DIR, USERS)
from orchestrator import Hub, Orchestrator
from store import Store

logging.basicConfig(level=logging.INFO)
if USERS.get("admin") == "admin123":
    logging.warning("Default login admin/admin123 is active. Set USERS before real use.")

app = FastAPI(title="Incident Desk")
store, hub = Store(), Hub()
orch = Orchestrator(store, hub)
VIDEO_EXT = {".mp4", ".mov", ".m4v", ".webm", ".avi", ".mkv"}


class Login(BaseModel):
    user: str
    password: str


class Review(BaseModel):
    action: Literal["confirm_incident", "confirm_emergency", "not_emergency", "request_review"]
    reason: str = ""


class Patch(BaseModel):
    summary: Optional[str] = None
    response_status: Optional[Literal["new", "dispatched", "on_scene", "resolved"]] = None


class EmailRequest(BaseModel):
    to_email: Optional[str] = None


class SmsRequest(BaseModel):
    to_phone: Optional[str] = None


class SmsConfigUpdate(BaseModel):
    to_phone: str


class SmsTestRequest(BaseModel):
    to_phone: Optional[str] = None
    message: Optional[str] = None


@app.post("/api/login")
def login():
    return dict(user="operator")


@app.post("/api/logout")
def logout():
    return dict(ok=True)


@app.get("/api/me")
def me(user: str = Depends(auth.current_user)):
    return dict(user=user)


@app.post("/api/upload")
async def upload(files: list[UploadFile] = File(...), user: str = Depends(auth.current_user)):
    if len(store.cameras) + len(files) > MAX_CAMERAS:
        raise HTTPException(400, f"At most {MAX_CAMERAS} cameras per session. Start over to clear them.")
    added = []
    for f in files:
        if Path(f.filename or "").suffix.lower() not in VIDEO_EXT:
            raise HTTPException(400, f"{f.filename}: unsupported file type")
        dest = UPLOAD_DIR / f"{uuid.uuid4().hex[:8]}_{Path(f.filename).name}"
        with dest.open("wb") as out:
            shutil.copyfileobj(f.file, out)
        added.append(await orch.add_video(dest, f.filename))
    return dict(cameras=added)


@app.get("/api/state")
def state(user: str = Depends(auth.current_user)):
    return orch.snapshot()


@app.post("/api/cameras/{cam_id}/analyze")
async def analyze_camera(cam_id: str, user: str = Depends(auth.current_user)):
    cam = await orch.reanalyze_camera(cam_id)
    if not cam:
        raise HTTPException(404, "Camera not found")
    return cam


@app.post("/api/cameras/analyze-all")
async def analyze_all_cameras(user: str = Depends(auth.current_user)):
    await orch.start_all()
    return dict(ok=True)


@app.get("/api/videos/{cam_id}")
def video(cam_id: str, request: Request):
    path = store.paths.get(cam_id)
    if not path or not Path(path).is_file():
        for inc in store.incidents.values():
            if inc.get("camera_id") == cam_id:
                fname = inc.get("video_ref", {}).get("file")
                if fname:
                    for p in UPLOAD_DIR.iterdir():
                        if p.name.endswith(fname) or fname in p.name:
                            path = str(p)
                            store.paths[cam_id] = path
                            break
            if path:
                break
    if not path or not Path(path).is_file():
        raise HTTPException(404, "Video footage file not found")
    return FileResponse(path, media_type="video/mp4")


@app.get("/api/evidence/{inc_id}/{name}")
def evidence(inc_id: str, name: str, request: Request):
    if not re.fullmatch(r"INC-\d{4}-\d+", inc_id) or not re.fullmatch(r"F\d+\.jpg", name):
        raise HTTPException(404)
    f = EVIDENCE_DIR / inc_id / name
    if not f.is_file():
        raise HTTPException(404)
    return FileResponse(f, media_type="image/jpeg")


@app.get("/api/incidents/{inc_id}")
def get_incident(inc_id: str, user: str = Depends(auth.current_user)):
    inc = store.incidents.get(inc_id)
    if not inc:
        raise HTTPException(404, "Incident not found")
    inc["access_log"] = (inc["access_log"] + [dict(at=now_iso(), user=user)])[-100:]
    store.save_incident(inc)
    return inc


@app.get("/api/incidents/{inc_id}/integrity")
async def integrity(inc_id: str, user: str = Depends(auth.current_user)):
    inc = store.incidents.get(inc_id)
    if not inc:
        raise HTTPException(404)
    path = store.paths.get(inc["camera_id"])
    video_ok = bool(path) and await asyncio.to_thread(sha256_file, path) == inc["video_ref"]["sha256"]
    frames = []
    for fr in inc["evidence"]:
        f = EVIDENCE_DIR / inc_id / fr["filename"]
        frames.append(dict(frame_id=fr["frame_id"], ok=f.is_file() and sha256_file(f) == fr["sha256"]))
    return dict(video_ok=video_ok, frames=frames, checked_at=now_iso())


@app.post("/api/incidents/{inc_id}/review")
async def review(inc_id: str, body: Review, user: str = Depends(auth.current_user)):
    inc = await orch.review(inc_id, body.action, body.reason.strip(), user)
    if not inc:
        raise HTTPException(404)
    return inc


@app.patch("/api/incidents/{inc_id}")
async def patch_incident(inc_id: str, body: Patch, user: str = Depends(auth.current_user)):
    try:
        inc = await orch.update_incident(inc_id, body.model_dump(exclude_none=True), user)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    if not inc:
        raise HTTPException(404)
    return inc


@app.get("/api/email-config")
def email_config(user: str = Depends(auth.current_user)):
    import config
    return dict(from_email=config.SMTP_FROM, default_to_email=config.ALERT_EMAIL_TO, smtp_configured=bool(config.SMTP_HOST))


@app.post("/api/email/test")
def send_test_email(user: str = Depends(auth.current_user)):
    test_inc = {
        "id": "TEST-EMAIL",
        "label": "Test System Alert",
        "short": "Test Alert",
        "severity": "high",
        "category": "System Diagnostic",
        "camera_name": "Diagnostic Stream",
        "video_ts_text": "00:00",
        "summary": "This is a live test notification from Incident Desk verifying that Gmail SMTP dispatch is active and delivering to your phone inbox.",
        "findings": [],
        "evidence": [],
    }
    return notifier.send(test_inc)


@app.post("/api/incidents/{inc_id}/email")
async def send_incident_email(inc_id: str, body: Optional[EmailRequest] = None, user: str = Depends(auth.current_user)):
    to_email = body.to_email if body else None
    res = await orch.send_manual_email(inc_id, to_email, user)
    if not res:
        raise HTTPException(404, "Incident not found")
    return res


@app.get("/api/sms-config")
def sms_config(user: str = Depends(auth.current_user)):
    wallet_info = notifier.get_sms_wallet()
    import config
    return dict(
        default_to_phone=config.ALERT_SMS_TO,
        sms_configured=bool(FAST2SMS_API_KEY),
        wallet=wallet_info.get("wallet", "50.00"),
        sms_count=wallet_info.get("sms_count", 200),
        public_url=config.PUBLIC_URL,
    )


@app.post("/api/sms-config")
def update_sms_config(body: SmsConfigUpdate, user: str = Depends(auth.current_user)):
    import config
    digits = re.sub(r"\D", "", body.to_phone)
    if digits.startswith("91") and len(digits) == 12:
        digits = digits[2:]
    if len(digits) != 10:
        raise HTTPException(400, "Phone number must be a 10-digit mobile number")
    config.ALERT_SMS_TO = digits
    env_path = Path(__file__).parent / ".env"
    if env_path.is_file():
        content = env_path.read_text(encoding="utf-8")
        if "ALERT_SMS_TO=" in content:
            content = re.sub(r"ALERT_SMS_TO=.*", f"ALERT_SMS_TO={digits}", content)
        else:
            content += f"\nALERT_SMS_TO={digits}\n"
        env_path.write_text(content, encoding="utf-8")
    return dict(ok=True, default_to_phone=digits)



@app.post("/api/incidents/{inc_id}/sms")
async def send_incident_sms(inc_id: str, body: Optional[SmsRequest] = None, user: str = Depends(auth.current_user)):
    to_phone = body.to_phone if body else None
    res = await orch.send_manual_sms(inc_id, to_phone, user)
    if not res:
        raise HTTPException(404, "Incident not found")
    return res


@app.get("/api/incidents/{inc_id}/sms/delivery")
async def check_incident_sms_delivery(inc_id: str, user: str = Depends(auth.current_user)):
    res = await orch.check_sms_delivery(inc_id, user)
    if res is None:
        raise HTTPException(404, "Incident not found")
    return res


@app.post("/api/sms/test")
def send_test_sms(body: Optional[SmsTestRequest] = None, user: str = Depends(auth.current_user)):
    to_phone = body.to_phone if body else None
    message = body.message if body else None
    return notifier.send_test_message(to_phone=to_phone, custom_message=message)


@app.get("/api/sms/delivery/{request_id}")
def check_arbitrary_sms_delivery(request_id: str, user: str = Depends(auth.current_user)):
    return notifier.get_delivery_report(request_id)


@app.get("/api/sms-outbox")
def get_sms_outbox(user: str = Depends(auth.current_user)):
    files = []
    if SMS_OUTBOX_DIR.is_dir():
        for p in sorted(SMS_OUTBOX_DIR.glob("*.txt"), key=lambda f: f.stat().st_mtime, reverse=True):
            try:
                content = p.read_text(encoding="utf-8")
            except Exception:
                content = ""
            mtime = datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc).isoformat()
            files.append({
                "filename": p.name,
                "size": p.stat().st_size,
                "updated_at": mtime,
                "content": content,
            })
    return dict(outbox=files[:60])


@app.get("/api/audit-logs")
def get_audit_logs(incident_id: Optional[str] = None, user: str = Depends(auth.current_user)):
    logs = []
    access_logs = []
    for inc_id, inc in store.incidents.items():
        if incident_id and inc_id != incident_id:
            continue
        for a in inc.get("audit", []):
            logs.append({
                "incident_id": inc_id,
                "incident_label": inc.get("short") or inc.get("label", ""),
                "camera_id": inc.get("camera_id", ""),
                "camera_name": inc.get("camera_name", ""),
                "at": a.get("at"),
                "actor": a.get("actor", "system"),
                "action": a.get("action", ""),
                "type": "audit",
            })
        for acc in inc.get("access_log", []):
            access_logs.append({
                "incident_id": inc_id,
                "incident_label": inc.get("short") or inc.get("label", ""),
                "camera_id": inc.get("camera_id", ""),
                "camera_name": inc.get("camera_name", ""),
                "at": acc.get("at"),
                "user": acc.get("user", "user"),
                "action": f"{acc.get('user', 'User')} inspected forensic report",
                "type": "access",
            })
    logs.sort(key=lambda x: x.get("at") or "", reverse=True)
    access_logs.sort(key=lambda x: x.get("at") or "", reverse=True)
    return dict(audit_logs=logs, access_logs=access_logs)





@app.post("/api/reset")
async def reset(user: str = Depends(auth.current_user)):
    await orch.reset()
    return dict(ok=True)


@app.websocket("/ws")
async def ws(sock: WebSocket):
    await sock.accept()
    hub.clients.add(sock)
    try:
        await sock.send_json(orch.snapshot())
        while True:
            await sock.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        hub.clients.discard(sock)


DIST = Path(__file__).parent.parent / "frontend" / "dist"
if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{full_path:path}")
    def spa(full_path: str):
        if full_path.startswith("api/"):
            raise HTTPException(404)
        f = (DIST / full_path).resolve()
        if full_path and f.is_file() and DIST.resolve() in f.parents:
            return FileResponse(f)
        return FileResponse(DIST / "index.html")  # deep links such as /incidents/INC-2026-001
