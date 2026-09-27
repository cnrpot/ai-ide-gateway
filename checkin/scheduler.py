"""统一签到调度：按 env 配置的时刻每天触发各家签到。

用法：
  python -m checkin.scheduler          # 常驻定时循环（容器默认）
  python -m checkin.scheduler --once   # 立即把已启用的都跑一遍后退出
"""
from __future__ import annotations

import os
import sys
import time
from datetime import date, datetime

from . import checkin_qoder, checkin_trae, checkin_workbuddy
from .common import log

# (名称, 启用开关 env, 时刻 env, 默认时刻, 执行函数)
JOBS = [
    ("trae", "CHECKIN_ENABLE_TRAE", "CHECKIN_TIME_TRAE", "08:30", checkin_trae.run),
    ("qoder", "CHECKIN_ENABLE_QODER", "CHECKIN_TIME_QODER", "10:05", checkin_qoder.run),
    ("workbuddy", "CHECKIN_ENABLE_WORKBUDDY", "CHECKIN_TIME_WORKBUDDY", "08:35", checkin_workbuddy.run),
]


def _enabled(env: str) -> bool:
    return os.environ.get(env, "0").strip().lower() in ("1", "true", "yes", "on")


def _run_once() -> None:
    ran = False
    for name, en, _tenv, _def, fn in JOBS:
        if _enabled(en):
            log(f"[scheduler] 触发 {name} 签到")
            try:
                fn()
            except Exception as exc:  # noqa: BLE001
                log(f"[scheduler] {name} 异常：{exc}")
            ran = True
    if not ran:
        log("[scheduler] 没有启用任何签到任务（检查 CHECKIN_ENABLE_*）")


def _loop() -> None:
    last_run: dict[str, date] = {}
    enabled = [j[0] for j in JOBS if _enabled(j[1])]
    log(f"[scheduler] 启动，已启用：{enabled or '（无）'}")
    while True:
        now = datetime.now()
        hhmm = now.strftime("%H:%M")
        for name, en, tenv, default, fn in JOBS:
            if not _enabled(en):
                continue
            target = os.environ.get(tenv, default) or default
            if hhmm == target and last_run.get(name) != now.date():
                log(f"[scheduler] 到点触发 {name} 签到 ({target})")
                try:
                    fn()
                except Exception as exc:  # noqa: BLE001
                    log(f"[scheduler] {name} 异常：{exc}")
                last_run[name] = now.date()
        time.sleep(20)


if __name__ == "__main__":
    if "--once" in sys.argv:
        _run_once()
    else:
        _loop()
