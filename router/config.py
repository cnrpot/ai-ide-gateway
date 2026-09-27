"""Router 配置：全部来自环境变量。"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field


def _csv(name: str) -> list[str]:
    return [x.strip() for x in os.environ.get(name, "").split(",") if x.strip()]


def _bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _float(name: str, default: float) -> float:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return max(0.1, float(raw))
    except ValueError as exc:
        raise ValueError(f"{name} 必须是数字: {raw!r}") from exc


@dataclass
class ProviderConfig:
    name: str
    base_url: str
    backend_key: str


@dataclass
class Settings:
    gateway_keys: list[str] = field(default_factory=lambda: _csv("GATEWAY_API_KEYS"))
    default_provider: str = os.environ.get("DEFAULT_PROVIDER", "codebuddy")
    allow_anonymous: bool = field(default_factory=lambda: _bool("ALLOW_ANONYMOUS", False))
    qoder_models: list[str] = field(
        default_factory=lambda: _csv("QODER_MODELS") or ["lite"]
    )
    request_timeout: float = field(default_factory=lambda: _float("REQUEST_TIMEOUT", 300.0))
    connect_timeout: float = field(default_factory=lambda: _float("CONNECT_TIMEOUT", 15.0))
    health_timeout: float = field(default_factory=lambda: _float("HEALTH_TIMEOUT", 5.0))
    panel_admin_key: str = field(default_factory=lambda: os.environ.get("PANEL_ADMIN_KEY", "").strip())
    panel_cookie_secure: bool = field(default_factory=lambda: _bool("PANEL_COOKIE_SECURE", False))
    qoder_admin_password: str = field(
        default_factory=lambda: os.environ.get("QODER_ADMIN_PASSWORD", "").strip()
    )
    codebuddy_admin_key: str = field(
        default_factory=lambda: os.environ.get("CODEBUDDY_ADMIN_KEY", "").strip()
    )
    checkin_config_path: str = field(
        default_factory=lambda: os.environ.get("CHECKIN_CONFIG", "/data/checkin/config.json").strip()
        or "/data/checkin/config.json"
    )
    checkin_log_path: str = field(
        default_factory=lambda: os.environ.get("CHECKIN_LOG", "/data/checkin/checkin.log").strip()
        or "/data/checkin/checkin.log"
    )
    panel_base_domain: str = field(
        default_factory=lambda: os.environ.get("PANEL_BASE_DOMAIN", "localhost").strip() or "localhost"
    )
    panel_qoder_host: str = field(
        default_factory=lambda: os.environ.get(
            "PANEL_QODER_HOST",
            f"qoder.{os.environ.get('PANEL_BASE_DOMAIN', 'localhost').strip() or 'localhost'}",
        ).strip()
    )
    panel_codebuddy_host: str = field(
        default_factory=lambda: os.environ.get(
            "PANEL_CODEBUDDY_HOST",
            f"codebuddy.{os.environ.get('PANEL_BASE_DOMAIN', 'localhost').strip() or 'localhost'}",
        ).strip()
    )
    model_routes: dict[str, str] = field(default_factory=dict)
    providers: dict[str, ProviderConfig] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.default_provider not in {"qoder", "codebuddy"}:
            raise ValueError(
                f"DEFAULT_PROVIDER 必须是 qoder 或 codebuddy: {self.default_provider!r}"
            )
        raw = os.environ.get("MODEL_ROUTES", "").strip()
        if raw:
            try:
                parsed = json.loads(raw)
                if not isinstance(parsed, dict):
                    raise ValueError("MODEL_ROUTES 须为 JSON 对象")
                self.model_routes = {str(k): str(v) for k, v in parsed.items()}
            except Exception as exc:  # noqa: BLE001
                raise ValueError(f"MODEL_ROUTES 不是合法 JSON: {exc}") from exc
        self.providers = {
            "qoder": ProviderConfig(
                "qoder",
                os.environ.get("QODER_BASE_URL", "http://qoder:5050").rstrip("/"),
                os.environ.get("QODER_BACKEND_KEY", ""),
            ),
            "codebuddy": ProviderConfig(
                "codebuddy",
                os.environ.get("CODEBUDDY_BASE_URL", "http://codebuddy:8787").rstrip("/"),
                os.environ.get("CODEBUDDY_BACKEND_KEY", ""),
            ),
        }

    @property
    def auth_enabled(self) -> bool:
        # 安全默认是 fail-closed；只有显式 ALLOW_ANONYMOUS=1 才允许匿名。
        return not self.allow_anonymous


settings = Settings()
