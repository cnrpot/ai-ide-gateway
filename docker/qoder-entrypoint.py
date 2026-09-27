"""QoderGateway 容器启动前的可重复鉴权初始化。"""
from __future__ import annotations

import os
import sys


def _enabled(name: str, default: bool = True) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def bootstrap() -> None:
    key = os.environ.get("QODER_BACKEND_KEY", "").strip()
    require_auth = _enabled("QODER_REQUIRE_AUTH", True)
    if require_auth and not key:
        raise RuntimeError(
            "QODER_BACKEND_KEY 为空；为避免 Qoder 后端裸奔，请在 .env 中设置它，"
            "或显式设置 QODER_REQUIRE_AUTH=0"
        )
    if not key:
        return

    # 导入上游模块会初始化 /data/.qoder/qoder2api.db。
    from qoder2api.config import load_config, save_config

    current = load_config()
    allowed = [str(item) for item in current.get("allowed_keys", []) if str(item)]
    if key not in allowed:
        allowed.append(key)
    save_config({"auth_required": require_auth, "allowed_keys": allowed})


def main() -> None:
    bootstrap()
    os.execvp(
        "uvicorn",
        [
            "uvicorn",
            "qoder2api.app:app",
            "--host",
            os.environ.get("QODER_HOST", "0.0.0.0"),
            "--port",
            os.environ.get("QODER_PORT", "5050"),
        ],
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:  # noqa: BLE001
        print(f"Qoder 启动初始化失败: {exc}", file=sys.stderr)
        raise
