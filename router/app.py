"""统一协议入口。

router 只负责校验网关 key、选择 provider 和透传协议响应；账号池、token 刷新
与签到由各自 provider 负责。
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from typing import Any

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse

from .auth import check as check_key
from .config import ProviderConfig, settings
from .routing import resolve

logging.basicConfig(level=logging.INFO, format="%(asctime)s [router] %(message)s")
log = logging.getLogger("router")

app = FastAPI(title="ai-ide-gateway router", version="1.1.0")


@app.on_event("startup")
async def _startup() -> None:
    app.state.client = httpx.AsyncClient(
        timeout=httpx.Timeout(settings.request_timeout, connect=settings.connect_timeout)
    )
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
