"""签到脚本共用工具：配置加载、日志、脱敏、HTTP。"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path
from typing import Callable

import httpx

BASE_DIR = Path(__file__).parent
CONFIG_PATH = Path(os.environ.get("CHECKIN_CONFIG", BASE_DIR / "config.json"))
LOG_PATH = Path(os.environ.get("CHECKIN_LOG", BASE_DIR / "checkin.log"))


def log(msg: str) -> None:
    line = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def mask(token: str) -> str:
    token = token or ""
    return f"...{token[-6:]}" if len(token) > 6 else "***"


def load_config() -> dict:
    if not CONFIG_PATH.exists():
        log(f"未找到配置文件 {CONFIG_PATH}，请从 config.example.json 复制并填入 token")
        return {}
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        log(f"配置文件解析失败: {exc}")
        return {}


def accounts(provider: str) -> list[dict]:
    data = load_config().get(provider) or []
    return data if isinstance(data, list) else [data]


def client() -> httpx.Client:
    return httpx.Client(timeout=30.0)


def run_accounts(
    label: str,
    accts: list[dict],
    http: httpx.Client,
    fn: Callable[[dict, httpx.Client], bool],
) -> bool:
    """执行全部账号，不因首个失败而短路。"""
    if not accts:
        log(f"[{label}] 配置中没有账号，跳过")
        return True
    results: list[bool] = []
    for account in accts:
        try:
            results.append(bool(fn(account, http)))
        except Exception as exc:  # noqa: BLE001
            name = account.get("name") or mask(
                str(account.get("token") or account.get("access_token") or "")
            )
            log(f"[{label}:{name}] 未处理异常：{exc}")
            results.append(False)
    failed = len(results) - sum(results)
    if failed:
        log(f"[{label}] 完成：成功 {len(results) - failed}，失败 {failed}")
    else:
        log(f"[{label}] 完成：{len(results)} 个账号全部成功")
    return not failed
