"""Router 配置：全部来自环境变量。"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field


def _csv(name: str) -> list[str]:
    return [x.strip() for x in os.environ.get(name, "").split(",") if x.strip()]


@dataclass
class ProviderConfig:
    name: str
    base_url: str
    backend_key: str


@dataclass
class Settings:
    gateway_keys: list[str] = field(default_factory=lambda: _csv("GATEWAY_API_KEYS"))
    default_provider: str = os.environ.get("DEFAULT_PROVIDER", "codebuddy")
    qoder_models: list[str] = field(
        default_factory=lambda: _csv("QODER_MODELS") or ["lite"]
    )
    model_routes: dict[str, str] = field(default_factory=dict)
    providers: dict[str, ProviderConfig] = field(default_factory=dict)

    def __post_init__(self) -> None:
        raw = os.environ.get("MODEL_ROUTES", "").strip()
        if raw:
            try:
                self.model_routes = {str(k): str(v) for k, v in json.loads(raw).items()}
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
        return bool(self.gateway_keys)


settings = Settings()
