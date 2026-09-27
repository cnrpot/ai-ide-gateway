"""统一网关的客户端 API-key 校验。"""
from __future__ import annotations

import hmac

from .config import settings


def _extract(authorization: str | None, x_api_key: str | None) -> str | None:
    if authorization:
        parts = authorization.split(None, 1)
        if len(parts) == 2 and parts[0].lower() == "bearer":
            return parts[1].strip()
        return authorization.strip()
    if x_api_key:
        return x_api_key.strip()
    return None


def check(authorization: str | None, x_api_key: str | None = None) -> bool:
    if not settings.auth_enabled:
        return True
    key = _extract(authorization, x_api_key)
    if not key:
        return False
    # 常量时间比较，避免时序侧信道
    return any(hmac.compare_digest(key, k) for k in settings.gateway_keys)
