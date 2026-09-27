"""统一管理面板的轻量会话和静态资源。"""
from __future__ import annotations

import hashlib
import hmac
import time
from pathlib import Path

from fastapi import Request
from fastapi.responses import Response

from .config import settings

PANEL_DIR = Path(__file__).parent / "panel"
PANEL_COOKIE = "ai_ide_panel"
PANEL_TTL = 12 * 60 * 60


def panel_enabled() -> bool:
    return bool(settings.panel_admin_key)


def _signature(timestamp: str) -> str:
    return hmac.new(
        settings.panel_admin_key.encode("utf-8"),
        timestamp.encode("ascii"),
        hashlib.sha256,
    ).hexdigest()


def issue_session() -> str:
    timestamp = str(int(time.time()))
    return f"{timestamp}.{_signature(timestamp)}"


def valid_session(request: Request) -> bool:
    if not panel_enabled():
        return False
    raw = request.cookies.get(PANEL_COOKIE, "")
    timestamp, separator, signature = raw.partition(".")
    if not separator or not timestamp or not signature:
        return False
    try:
        issued = int(timestamp)
    except ValueError:
        return False
    if abs(int(time.time()) - issued) > PANEL_TTL:
        return False
    return hmac.compare_digest(signature, _signature(timestamp))


def set_session_cookie(response: Response) -> None:
    response.set_cookie(
        PANEL_COOKIE,
        issue_session(),
        max_age=PANEL_TTL,
        httponly=True,
        samesite="strict",
        secure=settings.panel_cookie_secure,
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(PANEL_COOKIE, path="/")
