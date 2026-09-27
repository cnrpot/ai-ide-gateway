"""统一协议入口。

router 只负责校验网关 key、选择 provider 和透传协议响应；账号池、token 刷新
与签到由各自 provider 负责。
"""
from __future__ import annotations

import asyncio
import contextlib
import hmac
import json
import logging
import re
from typing import Any

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .auth import check as check_key
from .config import ProviderConfig, settings
from .panel import (
    PANEL_DIR,
    clear_session_cookie,
    panel_enabled,
    set_session_cookie,
    valid_session,
)
from .management import ManagementError, ManagementHub
from .routing import resolve

logging.basicConfig(level=logging.INFO, format="%(asctime)s [router] %(message)s")
log = logging.getLogger("router")

app = FastAPI(title="ai-ide-gateway router", version="1.1.0")
app.mount("/panel/assets", StaticFiles(directory=str(PANEL_DIR / "assets")), name="panel-assets")


@app.on_event("startup")
async def _startup() -> None:
    app.state.client = httpx.AsyncClient(
        timeout=httpx.Timeout(settings.request_timeout, connect=settings.connect_timeout)
    )
    app.state.management = ManagementHub(app.state.client)
    if settings.allow_anonymous:
        log.warning("ALLOW_ANONYMOUS=1：网关 API 鉴权已显式关闭")
    elif not settings.gateway_keys:
        log.error("GATEWAY_API_KEYS 为空：/v1 接口将全部返回 401，请配置网关 key")


@app.on_event("shutdown")
async def _shutdown() -> None:
    client = getattr(app.state, "client", None)
    if client is not None:
        with contextlib.suppress(Exception):
            await client.aclose()


def _client() -> httpx.AsyncClient:
    client = getattr(app.state, "client", None)
    if client is None:
        client = httpx.AsyncClient(
            timeout=httpx.Timeout(settings.request_timeout, connect=settings.connect_timeout)
        )
        app.state.client = client
    return client


def _management() -> ManagementHub:
    hub = getattr(app.state, "management", None)
    if hub is None:
        hub = ManagementHub(_client())
        app.state.management = hub
    return hub


def _panel_guard(request: Request) -> JSONResponse | None:
    if not panel_enabled():
        return JSONResponse({"detail": "未配置 PANEL_ADMIN_KEY"}, status_code=503)
    if not valid_session(request):
        return JSONResponse({"detail": "需要登录管理面板"}, status_code=401)
    return None


def _management_error(exc: ManagementError) -> JSONResponse:
    return JSONResponse({"detail": exc.message}, status_code=exc.status_code)


def _backend_for_host(hostname: str | None) -> ProviderConfig | None:
    host = (hostname or "").split(":", 1)[0].lower().rstrip(".")
    if host == settings.panel_qoder_host.lower().rstrip("."):
        return settings.providers["qoder"]
    if host == settings.panel_codebuddy_host.lower().rstrip("."):
        return settings.providers["codebuddy"]
    return None


def _backend_for_path(path: str) -> tuple[ProviderConfig, str, str] | None:
    for prefix, name in (("/qoder", "qoder"), ("/codebuddy", "codebuddy")):
        if path == prefix or path.startswith(prefix + "/"):
            remainder = path[len(prefix) :] or "/"
            return settings.providers[name], remainder, prefix
    return None


def _rewrite_console_body(content: bytes, provider: ProviderConfig, prefix: str, content_type: str) -> bytes:
    if not any(kind in content_type.lower() for kind in ("text/html", "javascript", "text/css")):
        return content
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError:
        return content
    roots = ("assets", "console", "documents", "ui", "v1") if provider.name == "qoder" else ("admin", "v1")
    for root in roots:
        pattern = re.compile(r"([\"'`])/(" + re.escape(root) + r")(?=[/\"'`?])")
        text = pattern.sub(rf"\1{prefix}/\2", text)
        text = re.sub(r"(?<![A-Za-z0-9_])/(" + re.escape(root) + r")(?=/)", rf"{prefix}/\1", text)
    if provider.name == "qoder":
        text = text.replace('href="/"', f'href="{prefix}/"').replace("href='/'", f"href='{prefix}/'")
    return text.encode("utf-8")


def _rewrite_console_header(value: str, provider: ProviderConfig, prefix: str, name: str) -> str:
    if name.lower() == "location" and value.startswith("/") and not value.startswith(prefix + "/"):
        roots = ("assets", "console", "documents", "ui", "v1") if provider.name == "qoder" else ("admin", "v1")
        if any(value == f"/{root}" or value.startswith(f"/{root}/") for root in roots):
            return prefix + value
    if name.lower() == "set-cookie" and provider.name == "codebuddy":
        return re.sub(r"(;\s*path=)/admin(?=;|$)", rf"\1{prefix}/admin", value, flags=re.IGNORECASE)
    return value


async def _proxy_host_request(
    request: Request,
    provider: ProviderConfig,
    *,
    upstream_path: str | None = None,
    public_prefix: str = "",
) -> Response:
    """在同一个网关端口上承载两个后端原生控制台。

    控制台使用根路径和绝对资源 URL，因此采用主机名路由，而不是把它们
    塞进 `/qoder`、`/codebuddy` 子路径。浏览器仍然看到原始后端路径，
    登录 cookie、静态资源和前端 API 不需要重写。
    """
    path = upstream_path or request.url.path or "/"
    url = f"{provider.base_url}{path}"
    if request.url.query:
        url += f"?{request.url.query}"
    skip = {"host", "content-length", "connection", "transfer-encoding"}
    headers = {key: value for key, value in request.headers.items() if key.lower() not in skip}
    headers["x-forwarded-host"] = request.headers.get("host", "")
    headers["x-forwarded-proto"] = request.url.scheme
    try:
        upstream = await _client().request(
            request.method,
            url,
            headers=headers,
            content=await request.body(),
            follow_redirects=False,
        )
    except httpx.TimeoutException:
        return JSONResponse({"detail": f"后端 {provider.name} 请求超时"}, status_code=504)
    except httpx.HTTPError as exc:
        log.warning("面板代理 %s 请求失败: %s", provider.name, type(exc).__name__)
        return JSONResponse({"detail": f"后端 {provider.name} 暂时不可用"}, status_code=502)

    content_type = upstream.headers.get("content-type", "")
    body = _rewrite_console_body(upstream.content, provider, public_prefix, content_type) if public_prefix else upstream.content
    response = Response(content=body, status_code=upstream.status_code, media_type=None)
    allowed = {
        "cache-control",
        "content-disposition",
        "content-type",
        "etag",
        "last-modified",
        "location",
        "retry-after",
        "set-cookie",
    }
    for key, value in upstream.headers.multi_items():
        if key.lower() in allowed:
            hostname = (request.url.hostname or "").lower().rstrip(".")
            if (
                key.lower() == "set-cookie"
                and not settings.panel_cookie_secure
                and (hostname == "localhost" or hostname.endswith(".localhost"))
            ):
                # 本机 HTTP 聚合入口没有 TLS；去掉后端 Secure cookie 属性，
                # 否则 CodeBuddy 管理会话在 localhost 上无法继续使用。
                value = re.sub(r";\s*secure(?=;|$)", "", value, flags=re.IGNORECASE)
            if public_prefix:
                value = _rewrite_console_header(value, provider, public_prefix, key)
            response.headers.append(key, value)
    return response


@app.middleware("http")
async def _backend_console_hosts(request: Request, call_next):
    path_target = _backend_for_path(request.url.path)
    if path_target is not None:
        provider, upstream_path, public_prefix = path_target
        return await _proxy_host_request(
            request,
            provider,
            upstream_path=upstream_path,
            public_prefix=public_prefix,
        )
    provider = _backend_for_host(request.url.hostname)
    if provider is not None:
        return await _proxy_host_request(request, provider)
    return await call_next(request)


def _error(message: str, status_code: int, error_type: str = "invalid_request_error") -> JSONResponse:
    return JSONResponse(
        {"error": {"message": message, "type": error_type}},
        status_code=status_code,
    )


def _unauth() -> JSONResponse:
    return _error("无效或缺失的网关 API key", 401, "authentication_error")


def _response_headers(response: httpx.Response) -> dict[str, str]:
    """只复制不会暴露内部连接细节的响应头。"""
    names = ("content-type", "cache-control", "retry-after", "x-request-id")
    return {name: response.headers[name] for name in names if name in response.headers}


def _request_headers(request: Request, provider: ProviderConfig) -> dict[str, str]:
    headers = {
        "Accept": request.headers.get("accept", "*/*"),
        "Content-Type": request.headers.get("content-type", "application/json"),
    }
    # 客户端的网关 key 永远不向下游透传；每个 provider 使用自己的后端 key。
    if provider.backend_key:
        headers["Authorization"] = f"Bearer {provider.backend_key}"
    return headers


def _explicit_provider(model: str) -> str | None:
    head, sep, _rest = (model or "").partition("/")
    return head if sep and head in settings.providers else None


async def _provider_probe(name: str, provider: ProviderConfig) -> tuple[str, dict[str, Any]]:
    # Qoder 没有公开 /health，根路径是无鉴权的 landing page；CodeBuddy 有 /health。
    path = "/health" if name == "codebuddy" else "/"
    try:
        response = await _client().get(
            f"{provider.base_url}{path}", timeout=settings.health_timeout
        )
        return name, {"ok": response.status_code < 400, "status_code": response.status_code}
    except httpx.HTTPError as exc:
        return name, {"ok": False, "error": type(exc).__name__}


@app.get("/health")
async def health() -> dict[str, Any]:
    """进程存活探针，不要求后端账号已经配置。"""
    return {
        "status": "ok",
        "service": "router",
        "auth_required": settings.auth_enabled,
        "providers": sorted(settings.providers),
    }


def _panel_console_urls(request: Request) -> dict[str, str]:
    host = request.headers.get("host", "localhost:8080")
    scheme = request.url.scheme
    return {
        "qoder": f"{scheme}://{host}/qoder/",
        "codebuddy": f"{scheme}://{host}/codebuddy/admin/",
    }


@app.get("/")
async def panel_root() -> RedirectResponse:
    return RedirectResponse("/panel/", status_code=307)


@app.get("/panel")
async def panel_redirect() -> RedirectResponse:
    return RedirectResponse("/panel/", status_code=307)


@app.get("/panel/", response_class=FileResponse)
async def panel_index() -> FileResponse:
    return FileResponse(PANEL_DIR / "index.html")


@app.get("/panel/api/config")
async def panel_config(request: Request) -> dict[str, Any]:
    return {
        "enabled": panel_enabled(),
        "consoles": _panel_console_urls(request),
        "api_base": f"{request.url.scheme}://{request.headers.get('host', 'localhost:8080')}",
    }


@app.post("/panel/api/login")
async def panel_login(request: Request) -> Response:
    if not panel_enabled():
        return JSONResponse({"detail": "未配置 PANEL_ADMIN_KEY"}, status_code=503)
    try:
        payload = await request.json()
    except ValueError:
        payload = {}
    supplied = str(payload.get("key") or "").strip()
    if not supplied or not hmac.compare_digest(supplied, settings.panel_admin_key):
        return JSONResponse({"detail": "管理面板密钥错误"}, status_code=401)
    response = JSONResponse({"status": "ok"})
    set_session_cookie(response)
    return response


@app.get("/panel/api/session")
async def panel_session(request: Request) -> JSONResponse:
    return JSONResponse({"authenticated": valid_session(request)})


@app.post("/panel/api/logout")
async def panel_logout() -> Response:
    response = JSONResponse({"status": "ok"})
    clear_session_cookie(response)
    return response


@app.get("/panel/api/status")
async def panel_status(request: Request) -> JSONResponse:
    if not panel_enabled():
        return JSONResponse({"detail": "未配置 PANEL_ADMIN_KEY"}, status_code=503)
    if not valid_session(request):
        return JSONResponse({"detail": "需要登录管理面板"}, status_code=401)
    pairs = await asyncio.gather(
        *(_provider_probe(name, provider) for name, provider in settings.providers.items())
    )
    providers = dict(pairs)
    return JSONResponse(
        {
            "status": "ok" if all(item.get("ok") for item in providers.values()) else "degraded",
            "providers": providers,
            "consoles": _panel_console_urls(request),
            "checkin": {"status": "profile-managed", "profile": "checkin"},
        }
    )


@app.get("/panel/api/overview")
async def panel_overview(request: Request) -> JSONResponse:
    """Return all provider management data used by the single-page console."""
    denied = _panel_guard(request)
    if denied is not None:
        return denied
    pairs = await asyncio.gather(
        *(_provider_probe(name, provider) for name, provider in settings.providers.items())
    )
    probes = dict(pairs)
    try:
        payload = await _management().overview(probes)
    except ManagementError as exc:
        return _management_error(exc)
    return JSONResponse(payload)


@app.get("/panel/api/qoder/overview")
async def panel_qoder_overview(request: Request) -> JSONResponse:
    denied = _panel_guard(request)
    if denied is not None:
        return denied
    try:
        return JSONResponse(await _management().qoder.overview())
    except ManagementError as exc:
        return _management_error(exc)


@app.post("/panel/api/qoder/action")
async def panel_qoder_action(request: Request) -> JSONResponse:
    denied = _panel_guard(request)
    if denied is not None:
        return denied
    try:
        body = await request.json()
        return JSONResponse(await _management().qoder.action(body if isinstance(body, dict) else {}))
    except ManagementError as exc:
        return _management_error(exc)
    except ValueError:
        return JSONResponse({"detail": "请求不是有效 JSON"}, status_code=400)


@app.get("/panel/api/codebuddy/overview")
async def panel_codebuddy_overview(request: Request) -> JSONResponse:
    denied = _panel_guard(request)
    if denied is not None:
        return denied
    try:
        return JSONResponse(await _management().codebuddy.overview())
    except ManagementError as exc:
        return _management_error(exc)


@app.post("/panel/api/codebuddy/action")
async def panel_codebuddy_action(request: Request) -> JSONResponse:
    denied = _panel_guard(request)
    if denied is not None:
        return denied
    try:
        body = await request.json()
        return JSONResponse(await _management().codebuddy.action(body if isinstance(body, dict) else {}))
    except ManagementError as exc:
        return _management_error(exc)
    except ValueError:
        return JSONResponse({"detail": "请求不是有效 JSON"}, status_code=400)


@app.get("/panel/api/checkin")
async def panel_checkin_overview(request: Request) -> JSONResponse:
    denied = _panel_guard(request)
    if denied is not None:
        return denied
    try:
        return JSONResponse(await asyncio.to_thread(_management().checkin.overview))
    except ManagementError as exc:
        return _management_error(exc)


@app.post("/panel/api/checkin/accounts")
async def panel_checkin_account(request: Request) -> JSONResponse:
    denied = _panel_guard(request)
    if denied is not None:
        return denied
    try:
        body = await request.json()
        if not isinstance(body, dict):
            raise ManagementError("请求格式无效", 400)
        provider = str(body.get("provider") or "")
        account = body.get("account")
        return JSONResponse(
            await asyncio.to_thread(_management().checkin.save_account, provider, account)
        )
    except ManagementError as exc:
        return _management_error(exc)
    except ValueError:
        return JSONResponse({"detail": "请求不是有效 JSON"}, status_code=400)


@app.delete("/panel/api/checkin/accounts/{provider}/{index}")
async def panel_checkin_delete(request: Request, provider: str, index: int) -> JSONResponse:
    denied = _panel_guard(request)
    if denied is not None:
        return denied
    try:
        return JSONResponse(
            await asyncio.to_thread(_management().checkin.delete_account, provider, index)
        )
    except ManagementError as exc:
        return _management_error(exc)


@app.post("/panel/api/checkin/run")
async def panel_checkin_run(request: Request) -> JSONResponse:
    denied = _panel_guard(request)
    if denied is not None:
        return denied
    try:
        body = await request.json()
        provider = str(body.get("provider") or "") if isinstance(body, dict) else ""
        return JSONResponse(await asyncio.to_thread(_management().checkin.run, provider))
    except ManagementError as exc:
        return _management_error(exc)
    except ValueError:
        return JSONResponse({"detail": "请求不是有效 JSON"}, status_code=400)


@app.get("/health/ready")
async def readiness() -> JSONResponse:
    """依赖就绪探针，供编排和运维使用。"""
    pairs = await asyncio.gather(
        *(_provider_probe(name, provider) for name, provider in settings.providers.items())
    )
    providers = dict(pairs)
    ready = all(item.get("ok") for item in providers.values())
    return JSONResponse(
        {"status": "ok" if ready else "degraded", "providers": providers},
        status_code=200 if ready else 503,
    )


@app.get("/v1/models")
async def list_models(request: Request) -> JSONResponse:
    if not check_key(request.headers.get("authorization"), request.headers.get("x-api-key")):
        return _unauth()

    data = [
        {"id": f"qoder/{model}", "object": "model", "owned_by": "qoder"}
        for model in settings.qoder_models
    ]
    provider = settings.providers["codebuddy"]
    try:
        headers = {"Accept": "application/json"}
        if provider.backend_key:
            headers["Authorization"] = f"Bearer {provider.backend_key}"
        response = await _client().get(f"{provider.base_url}/v1/models", headers=headers)
        payload = response.json()
        items = payload.get("data", []) if isinstance(payload, dict) else []
        for item in items:
            model_id = item.get("id") if isinstance(item, dict) else None
            if model_id:
                data.append(
                    {"id": f"codebuddy/{model_id}", "object": "model", "owned_by": "codebuddy"}
                )
    except (httpx.HTTPError, ValueError, TypeError) as exc:
        log.warning("拉取 codebuddy 模型失败: %s", type(exc).__name__)
    return JSONResponse({"object": "list", "data": data})


async def _forward(
    request: Request,
    path: str,
    *,
    force_provider: str | None = None,
    supported_providers: set[str] | None = None,
) -> Response:
    if not check_key(request.headers.get("authorization"), request.headers.get("x-api-key")):
        return _unauth()

    raw = await request.body()
    try:
        body = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        return _error("请求体不是合法 JSON", 400)
    if not isinstance(body, dict):
        return _error("请求体必须是 JSON 对象", 400)

    model = str(body.get("model") or "")
    explicit = _explicit_provider(model)
    resolved_provider, upstream_model = resolve(model)
    if force_provider and explicit and explicit != force_provider:
        return _error(
            f"{path} 不支持显式 provider {explicit}，请使用 {force_provider}/<model>",
            400,
        )
    provider_name = force_provider or resolved_provider
    if supported_providers and provider_name not in supported_providers:
        return _error(f"provider {provider_name} 不支持 {path}", 400)

    provider = settings.providers.get(provider_name)
    if provider is None:
        return _error(f"未知 provider: {provider_name}", 400)

    body["model"] = upstream_model
    payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
    headers = _request_headers(request, provider)
    url = f"{provider.base_url}{path}"

    if bool(body.get("stream")):
        return await _forward_stream(url, headers, payload, provider_name)

    try:
        response = await _client().post(url, headers=headers, content=payload)
    except httpx.TimeoutException:
        return _error(f"后端 {provider_name} 请求超时", 504, "upstream_timeout")
    except httpx.HTTPError as exc:
        log.warning("后端 %s 请求失败: %s", provider_name, type(exc).__name__)
        return _error(f"后端 {provider_name} 暂时不可用", 502, "upstream_error")
    return Response(
        content=response.content,
        status_code=response.status_code,
        headers=_response_headers(response),
        media_type=None,
    )


async def _forward_stream(
    url: str, headers: dict[str, str], payload: bytes, provider: str
) -> Response:
    try:
        request = _client().build_request("POST", url, headers=headers, content=payload)
        upstream = await _client().send(request, stream=True)
    except httpx.TimeoutException:
        return _error(f"后端 {provider} 请求超时", 504, "upstream_timeout")
    except httpx.HTTPError as exc:
        log.warning("后端 %s 流式连接失败: %s", provider, type(exc).__name__)
        return _error(f"后端 {provider} 暂时不可用", 502, "upstream_error")

    if upstream.status_code >= 400:
        try:
            content = await upstream.aread()
        finally:
            await upstream.aclose()
        return Response(
            content=content,
            status_code=upstream.status_code,
            headers=_response_headers(upstream),
            media_type=None,
        )

    async def generate():
        try:
            async for chunk in upstream.aiter_raw():
                if chunk:
                    yield chunk
        except httpx.HTTPError as exc:
            log.warning("后端 %s 流式读取失败: %s", provider, type(exc).__name__)
            error = json.dumps(
                {"error": {"message": f"后端 {provider} 流式读取失败", "type": "upstream_error"}},
                ensure_ascii=False,
            )
            yield f"data: {error}\n\n".encode("utf-8")
        finally:
            await upstream.aclose()

    response_headers = _response_headers(upstream)
    response_headers.setdefault("cache-control", "no-cache")
    response_headers["x-accel-buffering"] = "no"
    response_headers.setdefault("content-type", "text/event-stream")
    return StreamingResponse(generate(), status_code=upstream.status_code, headers=response_headers)


@app.post("/v1/chat/completions")
async def chat_completions(request: Request) -> Response:
    return await _forward(request, "/v1/chat/completions")


@app.post("/v1/responses")
async def responses(request: Request) -> Response:
    # QoderGateway 当前只有 Chat Completions；Responses 由 codebuddy2api 提供。
    return await _forward(
        request,
        "/v1/responses",
        force_provider="codebuddy",
        supported_providers={"codebuddy"},
    )


@app.post("/v1/messages")
async def anthropic_messages(request: Request) -> Response:
    # Anthropic Messages 同样只由 codebuddy2api 适配。
    return await _forward(
        request,
        "/v1/messages",
        force_provider="codebuddy",
        supported_providers={"codebuddy"},
    )
