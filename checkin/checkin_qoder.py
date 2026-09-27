"""Qoder CN 签到（token 来自 config.json）。

注意：QoderGateway 后端已在面板加载时自动 claim，本脚本默认关闭
（CHECKIN_ENABLE_QODER=0），仅在「只跑签到、不跑网关」场景下启用。
"""
from __future__ import annotations

from .common import accounts, client, log, mask

API = "https://openapi.qoder.com.cn"
CLIENT_TYPE = "10"


def _headers(acct: dict) -> dict:
    return {
        "Accept": "application/json",
        "User-Agent": "Qoder",
        "Authorization": f"Bearer {acct['token']}",
        "Cosy-ClientType": CLIENT_TYPE,
        "Cosy-Version": acct.get("version", "0.3.4"),
    }


def checkin_one(acct: dict, http) -> bool:
    name = acct.get("name") or mask(acct.get("token", ""))
    headers = _headers(acct)
    try:
        r = http.get(f"{API}/sash/api/v1/me/campaigns", headers=headers)
        if r.status_code != 200:
            log(f"[Qoder:{name}] 活动列表失败 HTTP {r.status_code}")
            return False
        campaigns = r.json().get("campaigns") or []
    except Exception as exc:  # noqa: BLE001
        log(f"[Qoder:{name}] 查询失败：{exc}")
        return False
    targets = [
        c for c in campaigns
        if c.get("claimStatus") == "CLAIMABLE" and c.get("actionType") == "CLAIM_BENEFIT"
    ]
    if not targets:
        log(f"[Qoder:{name}] 无可领取活动（或已自动领取）")
        return True
    ok = True
    for c in targets:
        try:
            resp = http.post(
                f"{API}/sash/api/v1/me/campaigns/{c['campaignId']}/claim", headers=headers
            )
            body = resp.json()
            log(
                f"[Qoder:{name}] 领取 {c.get('campaignKey')} -> "
                f"status={body.get('status')} replayed={body.get('replayed')}"
            )
        except Exception as exc:  # noqa: BLE001
            log(f"[Qoder:{name}] 领取失败：{exc}")
            ok = False
    return ok


def run() -> bool:
    accts = [a for a in accounts("qoder") if a.get("token")]
    if not accts:
        log("[Qoder] 配置中没有 qoder 账号，跳过")
        return True
    with client() as http:
        return all(checkin_one(a, http) for a in accts)


if __name__ == "__main__":
    import sys

    sys.exit(0 if run() else 1)
