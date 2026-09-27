"""Single-page management adapters for the bundled providers.

The provider projects keep their own storage and runtime processes.  This module
exposes a deliberately small, credential-safe adapter layer so the gateway panel
can manage them from one page without embedding or linking their native UIs.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import threading
import time
from pathlib import Path
from typing import Any

import httpx

from .config import settings


class ManagementError(RuntimeError):
    """An expected provider management failure safe to show in the panel."""

    def __init__(self, message: str, status_code: int = 502) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _response_error(response: httpx.Response, fallback: str) -> ManagementError:
    detail = fallback
    try:
        payload = response.json()
        if isinstance(payload, dict):
            value = payload.get("detail") or payload.get("message") or payload.get("error")
            if isinstance(value, str) and value.strip():
                detail = value.strip()
    except (ValueError, TypeError):
        pass
    # Never pass bearer credentials or raw upstream response bodies to the UI.
    detail = re.sub(r"(?i)(bearer|token|secret|key)\s*[:=]\s*[^,\s]+", r"\1=[redacted]", detail)
    return ManagementError(detail[:240], 503 if response.status_code in (401, 403) else 502)


class QoderAdmin:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self.client = client

    async def request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> Any:
        token = settings.qoder_admin_password
        if not token:
            raise ManagementError("未配置 QODER_ADMIN_PASSWORD", 503)
        try:
            response = await self.client.request(
                method,
                f"{settings.providers['qoder'].base_url}{path}",
                headers={"x-gateway-token": token, "accept": "application/json"},
                json=payload if payload is not None else None,
                timeout=settings.health_timeout * 4,
            )
        except httpx.TimeoutException as exc:
            raise ManagementError("Qoder 管理接口超时", 504) from exc
        except httpx.HTTPError as exc:
            raise ManagementError("Qoder 管理接口暂时不可用", 502) from exc
        if response.status_code >= 400:
            raise _response_error(response, "Qoder 管理操作失败")
        try:
            return response.json()
        except ValueError as exc:
            raise ManagementError("Qoder 返回了无效数据", 502) from exc

    async def overview(self) -> dict[str, Any]:
        status, accounts = await asyncio.gather(
            self.request("GET", "/ui/status"),
            self.request("GET", "/ui/accounts"),
        )
        return {"status": status, "accounts": accounts}

    async def action(self, body: dict[str, Any]) -> Any:
        action = str(body.get("action") or "").strip()
        if action == "import_pat":
            pat = str(body.get("pat") or "").strip()
            if not pat:
                raise ManagementError("请填写 Qoder PAT", 400)
            return await self.request("POST", "/ui/session", {"pat": pat})
        if action == "batch_import":
            records = body.get("accounts") or body.get("records")
            if not isinstance(records, list) or not records:
                raise ManagementError("批量账号必须是非空数组", 400)
            return await self.request("POST", "/ui/accounts/batch-import", {"accounts": records})
        if action == "select":
            return await self.request("POST", "/ui/accounts/select", {"uid": str(body.get("uid") or "")})
        if action == "toggle":
            return await self.request(
                "POST",
                "/ui/accounts/toggle",
                {"uid": str(body.get("uid") or ""), "enabled": bool(body.get("enabled", True))},
            )
        if action == "delete":
            uid = str(body.get("uid") or "").strip()
            if not uid:
                raise ManagementError("缺少 Qoder 账号 UID", 400)
            return await self.request("DELETE", f"/ui/accounts/{uid}")
        if action == "refresh_tokens":
            return await self.request("POST", "/ui/accounts/refresh-tokens")
        if action == "quota":
            return await self.request("GET", "/ui/accounts/quota")
        raise ManagementError("未知的 Qoder 管理操作", 400)


class CodeBuddyAdmin:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self.client = client
        self._sid: str | None = None
        self._csrf: str | None = None
        self._expires = 0.0
        self._lock = asyncio.Lock()

    def reset(self) -> None:
        self._sid = None
        self._csrf = None
        self._expires = 0.0

    async def _login(self) -> None:
        key = settings.codebuddy_admin_key
        if not key:
            raise ManagementError("未配置 CODEBUDDY_ADMIN_KEY", 503)
        try:
            response = await self.client.post(
                f"{settings.providers['codebuddy'].base_url}/admin/api/login",
                json={"key": key},
                timeout=settings.health_timeout * 4,
            )
        except httpx.TimeoutException as exc:
            raise ManagementError("WorkBuddy 管理接口超时", 504) from exc
        except httpx.HTTPError as exc:
            raise ManagementError("WorkBuddy 管理接口暂时不可用", 502) from exc
        if response.status_code >= 400:
            raise _response_error(response, "WorkBuddy 管理登录失败")
        try:
            csrf = response.json().get("csrf")
            sid = response.cookies.get("workbuddy_admin")
        except (ValueError, KeyError):
            csrf, sid = None, None
        if not isinstance(csrf, str) or not csrf or not isinstance(sid, str) or not sid:
            raise ManagementError("WorkBuddy 管理登录返回不完整", 502)
        self._sid, self._csrf, self._expires = sid, csrf, time.time() + 11 * 3600

    async def _ensure_login(self) -> None:
        if self._sid and self._csrf and self._expires > time.time():
            return
        async with self._lock:
            if self._sid and self._csrf and self._expires > time.time():
                return
            await self._login()

    async def request(
        self,
        method: str,
        path: str,
        payload: dict[str, Any] | None = None,
        *,
        retry: bool = True,
    ) -> Any:
        await self._ensure_login()
        headers = {"accept": "application/json"}
        if self._csrf:
            headers["X-CSRF-Token"] = self._csrf
        if self._sid:
            headers["Cookie"] = f"workbuddy_admin={self._sid}"
        try:
            response = await self.client.request(
                method,
                f"{settings.providers['codebuddy'].base_url}{path}",
                headers=headers,
                json=payload if payload is not None else None,
                timeout=settings.health_timeout * 6,
            )
        except httpx.TimeoutException as exc:
            raise ManagementError("WorkBuddy 管理接口超时", 504) from exc
        except httpx.HTTPError as exc:
            raise ManagementError("WorkBuddy 管理接口暂时不可用", 502) from exc
        if response.status_code in (401, 403) and retry:
            self.reset()
            return await self.request(method, path, payload, retry=False)
        if response.status_code >= 400:
            raise _response_error(response, "WorkBuddy 管理操作失败")
        try:
            return response.json()
        except ValueError as exc:
            raise ManagementError("WorkBuddy 返回了无效数据", 502) from exc

    async def overview(self) -> dict[str, Any]:
        return await self.request("GET", "/admin/api/overview")

    async def action(self, body: dict[str, Any]) -> Any:
        action = str(body.get("action") or "").strip()
        if action in {"refresh", "status", "checkin"}:
            aid = str(body.get("id") or "").strip()
            if not aid:
                raise ManagementError("缺少 WorkBuddy 账号 ID", 400)
            return await self.request("POST", f"/admin/api/accounts/{aid}/actions/{action}")
        if action in {"pool_status", "pool_checkin"}:
            return await self.request("POST", f"/admin/api/pool/actions/{action.removeprefix('pool_')}")
        if action == "pool_settings":
            values = {key: body[key] for key in ("routing", "auto_checkin", "checkin_time") if key in body}
            return await self.request("PATCH", "/admin/api/pool/settings", values)
        if action == "add_account":
            return await self.request("POST", "/admin/api/accounts", {k: body[k] for k in ("name", "credential") if k in body})
        if action == "edit_account":
            aid = str(body.get("id") or "").strip()
            return await self.request("PATCH", f"/admin/api/accounts/{aid}", {k: body[k] for k in ("name", "enabled", "active") if k in body})
        if action == "delete_account":
            aid = str(body.get("id") or "").strip()
            return await self.request("DELETE", f"/admin/api/accounts/{aid}")
        if action == "add_key":
            return await self.request("POST", "/admin/api/keys", {"name": body.get("name") or "统一面板客户端"})
        if action == "revoke_key":
            kid = str(body.get("id") or "").strip()
            return await self.request("DELETE", f"/admin/api/keys/{kid}")
        if action == "test":
            return await self.request("POST", "/admin/api/test", {"model": body.get("model"), "prompt": body.get("prompt")})
        if action == "oauth_start":
            return await self.request("POST", "/admin/api/oauth/start", {"name": body.get("name")})
        if action == "oauth_poll":
            return await self.request("POST", f"/admin/api/oauth/{body.get('flow_id')}/poll")
        if action == "oauth_cancel":
            return await self.request("DELETE", f"/admin/api/oauth/{body.get('flow_id')}")
        raise ManagementError("未知的 WorkBuddy 管理操作", 400)


class CheckinManager:
    PROVIDERS = {"trae", "qoder", "workbuddy"}
    _run_lock = threading.Lock()

    def __init__(self) -> None:
        self.path = Path(settings.checkin_config_path)
        self.log_path = Path(settings.checkin_log_path)

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {provider: [] for provider in self.PROVIDERS}
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise ManagementError("签到配置无法读取", 500) from exc
        if not isinstance(value, dict):
            raise ManagementError("签到配置格式无效", 500)
        return {provider: value.get(provider) if isinstance(value.get(provider), list) else [] for provider in self.PROVIDERS}

    @staticmethod
    def _summary(provider: str, item: dict[str, Any], index: int) -> dict[str, Any]:
        token = str(item.get("token") or item.get("access_token") or "")
        return {
            "index": index,
            "name": str(item.get("name") or f"{provider}-{index + 1}"),
            "token_configured": bool(token),
            "token_hint": f"…{token[-4:]}" if len(token) >= 4 else ("已配置" if token else "未配置"),
            "region": item.get("region", ""),
            "uid": item.get("uid", ""),
            "domain": item.get("domain", ""),
            "version": item.get("version", ""),
            "expires_at": item.get("expires_at", 0),
            "device_id_configured": bool(item.get("device_id")),
        }

    def overview(self) -> dict[str, Any]:
        data = self._load()
        return {
            "configured": self.path.exists(),
            "path": str(self.path),
            "providers": {
                provider: {
                    "count": len(data[provider]),
                    "accounts": [self._summary(provider, item, index) for index, item in enumerate(data[provider]) if isinstance(item, dict)],
                }
                for provider in sorted(self.PROVIDERS)
            },
            "log": self._tail_log(),
        }

    def _tail_log(self) -> list[str]:
        try:
            return self.log_path.read_text(encoding="utf-8").splitlines()[-80:]
        except OSError:
            return []

    def save_account(self, provider: str, account: dict[str, Any]) -> dict[str, Any]:
        if provider not in self.PROVIDERS:
            raise ManagementError("未知的签到 provider", 400)
        if not isinstance(account, dict):
            raise ManagementError("签到账号格式无效", 400)
        data = self._load()
        item = dict(account)
        token_key = "access_token" if provider == "workbuddy" else "token"
        token = str(item.get(token_key) or "").strip()
        if not token:
            raise ManagementError("签到账号必须填写 token", 400)
        item[token_key] = token
        item["name"] = str(item.get("name") or f"{provider}-{len(data[provider]) + 1}").strip()[:60]
        index = item.pop("index", None)
        if isinstance(index, int) and 0 <= index < len(data[provider]):
            data[provider][index] = item
        else:
            data[provider].append(item)
        self._save(data)
        return self.overview()

    def delete_account(self, provider: str, index: int) -> dict[str, Any]:
        if provider not in self.PROVIDERS:
            raise ManagementError("未知的签到 provider", 400)
        data = self._load()
        if index < 0 or index >= len(data[provider]):
            raise ManagementError("签到账号不存在", 404)
        data[provider].pop(index)
        self._save(data)
        return self.overview()

    def _save(self, data: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        os.replace(tmp, self.path)

    def run(self, provider: str) -> dict[str, Any]:
        if provider not in self.PROVIDERS:
            raise ManagementError("未知的签到 provider", 400)
        if not self._run_lock.acquire(blocking=False):
            raise ManagementError("已有签到任务正在执行", 409)
        try:
            os.environ["CHECKIN_CONFIG"] = str(self.path)
            os.environ["CHECKIN_LOG"] = str(self.log_path)
            from checkin import checkin_qoder, checkin_trae, checkin_workbuddy

            runner = {
                "trae": checkin_trae.run,
                "qoder": checkin_qoder.run,
                "workbuddy": checkin_workbuddy.run,
            }[provider]
            ok = bool(runner())
            return {"provider": provider, "ok": ok, "overview": self.overview()}
        except ManagementError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise ManagementError(f"{provider} 签到执行失败，请查看日志", 502) from exc
        finally:
            self._run_lock.release()


class ManagementHub:
    def __init__(self, client: httpx.AsyncClient) -> None:
        self.qoder = QoderAdmin(client)
        self.codebuddy = CodeBuddyAdmin(client)
        self.checkin = CheckinManager()

    async def overview(self, probes: dict[str, dict[str, Any]]) -> dict[str, Any]:
        async def safe(coro, label: str) -> dict[str, Any]:
            try:
                return {"ok": True, "data": await coro}
            except ManagementError as exc:
                return {"ok": False, "error": exc.message, "status_code": exc.status_code}
            except Exception:
                return {"ok": False, "error": f"{label} 管理数据暂时不可用", "status_code": 502}

        qoder, codebuddy = await asyncio.gather(
            safe(self.qoder.overview(), "Qoder"),
            safe(self.codebuddy.overview(), "WorkBuddy"),
        )
        return {
            "status": "ok" if all(item.get("ok") for item in probes.values()) else "degraded",
            "gateway": {
                "default_provider": settings.default_provider,
                "model_routes": dict(settings.model_routes),
                "models": [f"qoder/{model}" for model in settings.qoder_models],
            },
            "providers": {
                "qoder": {"health": probes.get("qoder", {}), "management": qoder},
                "codebuddy": {"health": probes.get("codebuddy", {}), "management": codebuddy},
            },
            "checkin": await asyncio.to_thread(self.checkin.overview),
        }
