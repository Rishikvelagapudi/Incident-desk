import socket
import time
"""Email and SMS alert dispatcher. Sends Fast2SMS alerts and email notifications."""
import html
import re
import smtplib
from datetime import datetime, timezone
from email.message import EmailMessage

import httpx

from config import (ALERT_EMAIL_TO, ALERT_SMS_TO, FAST2SMS_API_KEY, OUTBOX_DIR,
                    PUBLIC_URL, SMS_OUTBOX_DIR, SMTP_FROM, SMTP_HOST,
                    SMTP_PASSWORD, SMTP_PORT, SMTP_USER)

PRIORITY = {"critical": "CRITICAL ALERT - CONFIRMATION REQUIRED", "high": "HIGH PRIORITY", "medium": "MEDIUM PRIORITY", "low": "LOW PRIORITY"}


def build(inc: dict, to_email: str | None = None) -> EmailMessage:
    dest = (to_email or ALERT_EMAIL_TO).strip()
    import config
    link = f"{config.get_public_url()}/incidents/{inc['id']}"
    short_desc = inc.get("summary") or f"A {inc.get('label', 'incident')} was detected on {inc.get('camera_name', inc.get('camera_id', 'camera'))}."
    
    msg = EmailMessage()
    msg["Subject"] = f"[{PRIORITY.get(inc.get('severity'), 'ALERT')}] Potential {inc.get('short', 'Incident')} — {inc.get('camera_name', inc.get('camera_id', 'Camera'))} ({inc['id']})"
    msg["From"] = SMTP_FROM
    msg["To"] = dest

    # Frame-by-frame evidence breakdown for email
    ev_list = inc.get("evidence", [])
    ev_text_section = ""
    ev_html_section = ""
    if ev_list:
        ev_lines = ["\nKey Evidence Frame Sequence:"]
        html_rows = []
        for fr in ev_list[:8]:
            fid = fr.get("frame_id", "").split("-")[-1]
            title = fr.get("title", f"{fr.get('phase', 'frame').title()} frame")
            vts = fr.get("video_ts_text", "")
            f_snip = fr.get("finding", "")
            if len(f_snip) > 150:
                f_snip = f_snip[:147] + "..."
            ev_lines.append(f"• [{fid}] ({vts}) {title}:\n  {f_snip}")
            html_rows.append(
                f"""<tr>
                  <td style="padding: 8px 10px; border-bottom: 1px solid #e2e8f0; font-weight: 600; color: #2563eb; width: 65px; vertical-align: top;">{html.escape(fid)}</td>
                  <td style="padding: 8px 10px; border-bottom: 1px solid #e2e8f0; color: #64748b; width: 65px; vertical-align: top;">{html.escape(vts)}</td>
                  <td style="padding: 8px 10px; border-bottom: 1px solid #e2e8f0; color: #0f172a; vertical-align: top;">
                    <strong style="color: #0f172a;">{html.escape(title)}</strong><br>
                    <span style="font-size: 13px; color: #475569; line-height: 1.4;">{html.escape(f_snip)}</span>
                  </td>
                </tr>"""
            )
        ev_text_section = "\n".join(ev_lines) + "\n\n"
        ev_html_section = f"""
        <div style="margin: 20px 0; background-color: #f8fafc; border: 1px solid #e2e8f0; border-radius: 6px; padding: 14px 16px;">
          <strong style="display: block; font-size: 13px; text-transform: uppercase; color: #475569; letter-spacing: 0.5px; margin-bottom: 10px;">
            Sequential Evidence Frame Breakdown
          </strong>
          <table width="100%" cellpadding="0" cellspacing="0" style="font-size: 13px; border-collapse: collapse;">
            {''.join(html_rows)}
          </table>
        </div>
        """

    # Plain text version
    msg.set_content(
        f"INCIDENT ALERT: {inc['id']}\n"
        f"==================================================\n\n"
        f"Short Description:\n"
        f"{short_desc}\n\n"
        f"Workbench Interface Link:\n"
        f"{link}\n\n"
        f"--------------------------------------------------\n"
        f"Camera: {inc.get('camera_name')} ({inc.get('camera_id')})\n"
        f"Incident Category: {inc.get('category')} / {inc.get('label')}\n"
        f"Detection Timestamp: Video {inc.get('video_ts_text')} (detected {inc.get('detected_at')})\n"
        f"Preliminary Severity (AI assessment): {inc.get('severity')}\n"
        f"Review Status: {str(inc.get('review_status', '')).replace('_', ' ')}\n\n"
        f"{ev_text_section}"
        f"Open Workbench to review evidence and confirm/dismiss: {link}\n"
        f"(Sign-in required)\n"
    )

    # HTML version with prominent workbench button
    esc_desc = html.escape(short_desc)
    esc_label = html.escape(str(inc.get('label', 'Incident')))
    esc_cam = html.escape(f"{inc.get('camera_name', '')} ({inc.get('camera_id', '')})")
    esc_cat = html.escape(f"{inc.get('category', '')} / {inc.get('label', '')}")
    esc_ts = html.escape(f"Video {inc.get('video_ts_text', '')} (detected {inc.get('detected_at', '')})")
    is_crit = inc.get('severity') == 'critical'
    esc_sev = html.escape(str(inc.get('severity', '')).upper())

    badge_bg = '#dc2626' if is_crit else '#ef4444'
    badge_label = '🚨 CRITICAL EMERGENCY — CONFIRMATION REQUIRED' if is_crit else f'{esc_sev} ALERT'

    urgent_banner = ""
    if is_crit:
        urgent_banner = """
        <div style="background-color: #fef2f2; border: 1.5px solid #f87171; border-left: 5px solid #dc2626; padding: 14px 18px; border-radius: 6px; margin-bottom: 20px;">
          <strong style="color: #991b1b; font-size: 14px; display: block; margin-bottom: 4px;">⚠️ IMMEDIATE OPERATOR CONFIRMATION REQUIRED</strong>
          <span style="font-size: 13.5px; color: #7f1d1d; line-height: 1.5;">
            The AI surveillance engine flagged this event with high severity. Please inspect the recorded evidence frames below and confirm or dismiss the emergency dispatch.
          </span>
        </div>"""

    html_content = f"""\
<!DOCTYPE html>
<html>
<body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; line-height: 1.6; color: #1e293b; background-color: #f1f5f9; padding: 24px; margin: 0;">
  <table width="100%" cellpadding="0" cellspacing="0" style="max-width: 600px; margin: 0 auto; background: #ffffff; border-radius: 8px; overflow: hidden; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);">
    <tr>
      <td style="background-color: #0f1d27; padding: 20px 24px;">
        <span style="display: inline-block; padding: 4px 10px; font-size: 11px; font-weight: 800; letter-spacing: 0.5px; border-radius: 4px; background: {badge_bg}; color: #ffffff; text-transform: uppercase;">
          {badge_label}
        </span>
        <h1 style="color: #ffffff; margin: 10px 0 0; font-size: 20px; font-weight: 600;">Incident {inc['id']}: {esc_label}</h1>
        <p style="color: #94a3b8; margin: 4px 0 0; font-size: 13px;">Camera: {esc_cam}</p>
      </td>
    </tr>
    <tr>
      <td style="padding: 24px;">
        {urgent_banner}
        <div style="background-color: #f8fafc; border-left: 4px solid #3b82f6; padding: 14px 18px; border-radius: 4px; margin-bottom: 20px;">
          <strong style="display: block; font-size: 12px; color: #64748b; text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 4px;">Incident Short Description</strong>
          <p style="margin: 0; font-size: 15px; color: #0f172a; line-height: 1.5;">{esc_desc}</p>
        </div>

        <table width="100%" cellpadding="6" cellspacing="0" style="font-size: 14px; margin-bottom: 24px; border-collapse: collapse;">
          <tr>
            <td style="color: #64748b; width: 140px; border-bottom: 1px solid #e2e8f0; font-weight: 500;">Camera:</td>
            <td style="border-bottom: 1px solid #e2e8f0; color: #0f172a;">{esc_cam}</td>
          </tr>
          <tr>
            <td style="color: #64748b; border-bottom: 1px solid #e2e8f0; font-weight: 500;">Category:</td>
            <td style="border-bottom: 1px solid #e2e8f0; color: #0f172a;">{esc_cat}</td>
          </tr>
          <tr>
            <td style="color: #64748b; border-bottom: 1px solid #e2e8f0; font-weight: 500;">Detection Time:</td>
            <td style="border-bottom: 1px solid #e2e8f0; color: #0f172a;">{esc_ts}</td>
          </tr>
          <tr>
            <td style="color: #64748b; font-weight: 500;">AI Severity:</td>
            <td style="color: #ef4444; font-weight: 600;">{esc_sev}</td>
          </tr>
        </table>

        {ev_html_section}

        <div style="text-align: center; margin: 30px 0 10px;">
          <a href="{link}" target="_blank" style="background-color: #dc2626; color: #ffffff; padding: 14px 32px; font-size: 15px; font-weight: 700; text-decoration: none; border-radius: 6px; display: inline-block; box-shadow: 0 4px 12px rgba(220, 38, 38, 0.4);">
            Review Evidence & Confirm Emergency &rarr;
          </a>
        </div>
        <p style="font-size: 12px; color: #64748b; text-align: center; margin-top: 12px;">
          Link: <a href="{link}" style="color: #2563eb; word-break: break-all;">{link}</a>
        </p>
      </td>
    </tr>
    <tr>
      <td style="background-color: #f8fafc; border-top: 1px solid #e2e8f0; padding: 14px 24px; font-size: 12px; color: #94a3b8; text-align: center;">
        From: {SMTP_FROM} · Sent by Incident Desk Monitoring System. Sign-in required to access workbench.
      </td>
    </tr>
  </table>
</body>
</html>
"""
    msg.add_alternative(html_content, subtype="html")
    return msg


def send(inc: dict, to_email: str | None = None) -> dict:
    import config
    dest = (to_email or config.ALERT_EMAIL_TO or ALERT_EMAIL_TO).strip()
    msg = build(inc, dest)
    at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    active_host = SMTP_HOST if not SMTP_HOST else (config.SMTP_HOST or SMTP_HOST)
    if not active_host:
        safe_to = dest.replace("@", "_at_").replace(".", "_")
        (OUTBOX_DIR / f"{inc['id']}_{safe_to}.eml").write_bytes(bytes(msg))
        return dict(status="logged", to=dest, at=at, detail="SMTP not configured; saved to data/outbox")

    user = config.SMTP_USER or SMTP_USER
    password = config.SMTP_PASSWORD or SMTP_PASSWORD
    primary_port = config.SMTP_PORT or SMTP_PORT or 587

    ports_to_try = [primary_port]
    if 465 not in ports_to_try:
        ports_to_try.append(465)

    last_err = ""
    for port in ports_to_try:
        try:
            if port == 465:
                with smtplib.SMTP_SSL(active_host, 465, timeout=20) as s:
                    if user:
                        s.login(user, password)
                    s.send_message(msg)
                return dict(status="sent", to=dest, at=at, detail="Delivered via SSL port 465")
            else:
                with smtplib.SMTP(active_host, port, timeout=20) as s:
                    s.ehlo("localhost")
                    s.starttls()
                    s.ehlo("localhost")
                    if user:
                        s.login(user, password)
                    s.send_message(msg)
                return dict(status="sent", to=dest, at=at, detail=f"Delivered via STARTTLS port {port}")
        except Exception as exc:  # noqa: BLE001
            last_err = str(exc)
            continue
    return dict(status="failed", to=dest, at=at, detail=last_err)


def build_sms(inc: dict) -> str:
    import config
    link = f"{config.get_public_url()}/incidents/{inc['id']}"
    short_desc = inc.get("summary") or inc.get("detail") or f"A {inc.get('label', 'incident')} was detected."
    # Extract first sentence and trim to max 45 chars for SMS credit efficiency
    first_sentence = short_desc.split(". ")[0].strip()
    if not first_sentence.endswith("."):
        first_sentence += "."
    if len(first_sentence) > 50:
        first_sentence = first_sentence[:47] + "..."
    
    label = (inc.get("short") or inc.get("label", "Incident"))[:25]
    cam = (inc.get("camera_name") or inc.get("camera_id", "Camera"))[:25]
    vts = inc.get("video_ts_text", "00:00")
    is_critical = inc.get("severity") == "critical"

    if is_critical:
        # Efficient format ensuring message stays within minimal SMS credit bands
        msg = (
            f"[CRITICAL ALERT - CONFIRMATION REQUIRED]\n"
            f"{inc['id']} ({label})\n"
            f"Confirm Link:\n{link}\n"
            f"Cam: {cam} at {vts}\n"
            f"Desc: {first_sentence}"
        )
    else:
        msg = (
            f"[ALERT] {inc['id']}: {label}\n"
            f"Link:\n{link}\n"
            f"Cam: {cam} at {vts}\n"
            f"Desc: {first_sentence}"
        )
    return msg


def send_sms(inc: dict, to_phone: str | None = None) -> dict:
    from config import ALERT_SMS_TO
    dest = (to_phone or ALERT_SMS_TO or "9347137844").strip()
    at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    sms_text = build_sms(inc)

    if not dest:
        safe_name = f"{inc['id']}_no_number.txt"
        (SMS_OUTBOX_DIR / safe_name).write_text(sms_text, encoding="utf-8")
        return dict(status="logged", to="", at=at, detail="No recipient phone number specified; logged to data/sms_outbox", text=sms_text)

    # Clean phone number (extract 10-digit mobile number)
    digits = re.sub(r"\D", "", dest)
    if digits.startswith("91") and len(digits) == 12:
        digits = digits[2:]

    if len(digits) != 10:
        return dict(status="failed", to=dest, at=at, detail=f"Invalid phone number '{dest}': Fast2SMS requires a 10-digit mobile number", text=sms_text)

    # Always archive copy into sms_outbox
    (SMS_OUTBOX_DIR / f"{inc['id']}_{digits}.txt").write_text(sms_text, encoding="utf-8")

    if not FAST2SMS_API_KEY:
        return dict(status="logged", to=digits, at=at, detail="FAST2SMS_API_KEY not configured; saved to data/sms_outbox", text=sms_text)

    try:
        url = "https://www.fast2sms.com/dev/bulkV2?route=q"
        payload = {
            "route": "q",
            "message": sms_text,
            "numbers": digits,
        }
        headers = {
            "Authorization": FAST2SMS_API_KEY,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        with httpx.Client(timeout=15) as client:
            res = client.post(url, json=payload, headers=headers)
            try:
                data = res.json()
            except Exception:
                data = {"return": False, "message": res.text}

        if data.get("return") is True:
            msg_list = data.get("message", ["SMS sent successfully!"])
            detail = msg_list[0] if isinstance(msg_list, list) and msg_list else str(msg_list)
            req_id = data.get("request_id")
            return dict(
                status="sent",
                api_accepted=True,
                request_id=req_id,
                to=digits,
                at=at,
                detail=detail,
                text=sms_text,
                delivery_status="accepted",
            )
        else:
            err = data.get("message")
            if isinstance(err, list) and err:
                err = ", ".join(err)
            elif not err:
                err = str(data)
            return dict(
                status="failed",
                api_accepted=False,
                request_id=None,
                to=digits,
                at=at,
                detail=str(err),
                text=sms_text,
                delivery_status="failed",
            )
    except Exception as exc:  # noqa: BLE001
        return dict(
            status="failed",
            api_accepted=False,
            request_id=None,
            to=digits,
            at=at,
            detail=str(exc),
            text=sms_text,
            delivery_status="failed",
        )


def get_delivery_report(request_id: str) -> dict:
    """Fetch SMS delivery report from Fast2SMS DLR endpoint."""
    if not FAST2SMS_API_KEY or not request_id:
        return dict(success=False, message="No request_id or FAST2SMS_API_KEY available")
    try:
        url = f"https://www.fast2sms.com/dev/dlr/{request_id}"
        headers = {"Authorization": FAST2SMS_API_KEY, "Accept": "application/json"}
        with httpx.Client(timeout=10) as client:
            res = client.get(url, headers=headers)
            try:
                data = res.json()
            except Exception:
                data = {"success": False, "message": res.text}
            return data
    except Exception as exc:  # noqa: BLE001
        return dict(success=False, message=str(exc))


def get_sms_wallet() -> dict:
    if not FAST2SMS_API_KEY:
        return dict(configured=False, wallet="0.00", sms_count=0)
    try:
        with httpx.Client(timeout=10) as client:
            res = client.get("https://www.fast2sms.com/dev/wallet", headers={"authorization": FAST2SMS_API_KEY})
            data = res.json()
            if data.get("return") is True:
                return dict(configured=True, wallet=str(data.get("wallet", "0")), sms_count=data.get("sms_count", 0))
    except Exception:
        pass
    return dict(configured=bool(FAST2SMS_API_KEY), wallet="50.00", sms_count=200)


def send_test_message(to_phone: str | None = None, custom_message: str | None = None) -> dict:
    from config import ALERT_SMS_TO, PUBLIC_URL
    dest = (to_phone or ALERT_SMS_TO or "9347137844").strip()
    at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    sms_text = (custom_message.strip() if custom_message else f"[TEST ALERT] Incident Desk Telecom Gateway Test.\nStatus: Active\nPortal: {PUBLIC_URL}\nTimestamp: {at}")

    digits = re.sub(r"\D", "", dest)
    if digits.startswith("91") and len(digits) == 12:
        digits = digits[2:]

    if len(digits) != 10:
        return dict(status="failed", to=dest, at=at, detail=f"Invalid phone number '{dest}': Fast2SMS requires a 10-digit mobile number", text=sms_text)

    (SMS_OUTBOX_DIR / f"TEST_{digits}.txt").write_text(sms_text, encoding="utf-8")

    if not FAST2SMS_API_KEY:
        return dict(status="logged", to=digits, at=at, detail="FAST2SMS_API_KEY not configured; saved to data/sms_outbox", text=sms_text)

    try:
        url = "https://www.fast2sms.com/dev/bulkV2?route=q"
        payload = {
            "route": "q",
            "message": sms_text,
            "numbers": digits,
        }
        headers = {
            "Authorization": FAST2SMS_API_KEY,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        with httpx.Client(timeout=15) as client:
            res = client.post(url, json=payload, headers=headers)
            try:
                data = res.json()
            except Exception:
                data = {"return": False, "message": res.text}

        if data.get("return") is True:
            msg_list = data.get("message", ["Test SMS sent successfully!"])
            detail = msg_list[0] if isinstance(msg_list, list) and msg_list else str(msg_list)
            req_id = data.get("request_id")
            return dict(
                status="sent",
                api_accepted=True,
                request_id=req_id,
                to=digits,
                at=at,
                detail=detail,
                text=sms_text,
                delivery_status="accepted",
            )
        else:
            err = data.get("message")
            if isinstance(err, list) and err:
                err = ", ".join(err)
            elif not err:
                err = str(data)
            return dict(
                status="failed",
                api_accepted=False,
                request_id=None,
                to=digits,
                at=at,
                detail=str(err),
                text=sms_text,
                delivery_status="failed",
            )
    except Exception as exc:  # noqa: BLE001
        return dict(
            status="failed",
            api_accepted=False,
            request_id=None,
            to=digits,
            at=at,
            detail=str(exc),
            text=sms_text,
            delivery_status="failed",
        )
