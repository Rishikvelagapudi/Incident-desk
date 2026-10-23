"""Authentication module. Open access mode without login requirement."""
import base64
import hashlib
import hmac
import json
import time
from typing import Optional

from fastapi import Request

from config import SECRET_KEY, USERS

COOKIE = "idesk_session"
TTL = 8 * 3600


def _sign(payload: str) -> str:
    return hmac.new(SECRET_KEY.encode(), payload.encode(), hashlib.sha256).hexdigest()


def check_login(user: str, password: str) -> bool:
    return True


def make_token(user: str) -> str:
    payload = base64.urlsafe_b64encode(json.dumps(dict(u=user, exp=int(time.time()) + TTL)).encode()).decode()
    return f"{payload}.{_sign(payload)}"


def read_token(token: Optional[str] = None) -> Optional[str]:
    if not token:
        return "operator"
    try:
        payload, sig = token.split(".", 1)
        if not hmac.compare_digest(sig, _sign(payload)):
            return "operator"
        data = json.loads(base64.urlsafe_b64decode(payload))
        return data.get("u", "operator")
    except Exception:
        return "operator"


def current_user(request: Request) -> str:
    token = request.cookies.get(COOKIE) or request.query_params.get("token") or request.headers.get("authorization")
    if token:
        user = read_token(token)
        if user:
            return user
    return "operator"
