"""Trae CN 签到（token 来自 config.json，容器可运行）。"""
from __future__ import annotations

from .common import accounts, client, log, mask

API_BASE = "https://api.trae.cn/trae/api/v2/ug/checkin_credits"
REQ_SOURCE = 1


def _headers(acct: dict) -> dict:
    h = {
        "Authorization": f"Cloud-IDE-JWT {acct['token']}",
        "Content-Type": "application/json",
    }
    if acct.get("device_id"):
        h["x-device-id"] = str(acct["device_id"])
    if acct.get("region"):
        h["X-User-Region"] = acct["region"]
    return h


def _unwrap(resp: dict) -> dict:
    if "checked_in" not in resp and isinstance(resp.get("data"), dict):
        return resp["data"]
    return resp


def checkin_one(acct: dict, http) -> bool:
    name = acct.get("name") or mask(acct.get("token", ""))
    try:
        r = http.post(f"{API_BASE}/status", headers=_headers(acct), json={"req_source": REQ_SOURCE})
        r.raise_for_status()
        status = _unwrap(r.json())
    except Exception as exc:  # noqa: BLE001
        log(f"[Trae:{name}] 查询签到状态失败：{exc}")
        return False
    if status.get("checked_in"):
        log(f"[Trae:{name}] 今日已签到，积分：{status.get('credits')}")
        return True
    if not status.get("enable", True):
        log(f"[Trae:{name}] 签到不可用")
        return False
    try:
        c = http.post(f"{API_BASE}/claim", headers=_headers(acct), json={"req_source": REQ_SOURCE})
        c.raise_for_status()
        claim = c.json()
    except Exception as exc:  # noqa: BLE001
        log(f"[Trae:{name}] 领取失败：{exc}")
        return False
    if claim.get("code") == 0:
        log(f"[Trae:{name}] 签到成功")
        return True
    log(f"[Trae:{name}] 签到失败：{claim.get('message') or claim}")
    return False


def run() -> bool:
    accts = [a for a in accounts("trae") if a.get("token")]
    if not accts:
        log("[Trae] 配置中没有 trae 账号，跳过")
        return True
    with client() as http:
        return all(checkin_one(a, http) for a in accts)


if __name__ == "__main__":
    import sys

    sys.exit(0 if run() else 1)
