"""WorkBuddy（腾讯 CodeBuddy）签到（token 来自 config.json）。

注意：codebuddy2api 后端已内置每日签到，本脚本默认关闭（CHECKIN_ENABLE_WORKBUDDY=0），
仅在「只跑签到、不跑网关」场景下启用。
"""
from __future__ import annotations

import time

from .common import accounts, client, log, mask

API_BASE = "https://copilot.tencent.com/v2/billing/meter"


def _headers(acct: dict) -> dict:
    return {
        "Authorization": f"Bearer {acct['access_token']}",
        "X-User-Id": str(acct.get("uid", "")),
        "X-Domain": acct.get("domain", ""),
        "Content-Type": "application/json",
    }


def checkin_one(acct: dict, http) -> bool:
    name = acct.get("name") or mask(acct.get("access_token", ""))
    exp = acct.get("expires_at") or 0
    if exp and exp / 1000 < time.time():
        log(f"[WorkBuddy:{name}] accessToken 已过期，需重新导出 token")
        return False
    try:
        s = http.post(f"{API_BASE}/checkin-status", headers=_headers(acct), json={})
        status = s.json()
    except Exception as exc:  # noqa: BLE001
        log(f"[WorkBuddy:{name}] 查询状态失败：{exc}")
        return False
    if status.get("code") != 0:
        log(f"[WorkBuddy:{name}] 查询状态异常：{status.get('msg')}")
        return False
    if (status.get("data") or {}).get("today_checked_in"):
        log(f"[WorkBuddy:{name}] 今日已签到")
        return True
    try:
        c = http.post(f"{API_BASE}/daily-checkin", headers=_headers(acct), json={})
        claim = c.json()
    except Exception as exc:  # noqa: BLE001
        log(f"[WorkBuddy:{name}] 领取失败：{exc}")
        return False
    if claim.get("code") in (0, 10001):
        credit = (claim.get("data") or {}).get("credit", "?")
        log(f"[WorkBuddy:{name}] 签到成功/今日已签，积分：{credit}")
        return True
    log(f"[WorkBuddy:{name}] 签到失败：{claim.get('msg')}")
    return False


def run() -> bool:
    accts = [a for a in accounts("workbuddy") if a.get("access_token")]
    if not accts:
        log("[WorkBuddy] 配置中没有 workbuddy 账号，跳过")
        return True
    with client() as http:
        return all(checkin_one(a, http) for a in accts)


if __name__ == "__main__":
    import sys

    sys.exit(0 if run() else 1)
