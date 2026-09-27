"""ai-ide-gateway 统一 OpenAI 兼容入口。

- 单一对外端口，按 model 前缀/规则把请求分发到 Qoder / CodeBuddy 后端。
- 统一客户端 API-key 鉴权；转发时改写为各后端自己的 key。
- 流式(SSE)透传。
"""
from __future__ import annotations

import contextlib
import json
import logging

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse

from .auth import check as check_key
from .config import settings
from .routing import resolve

logging.basicConfig(level=logging.INFO, format="%(asctime)s [router] %(message)s")
log = logging.getLogger("router")

app = FastAPI(title="ai-ide-gateway router", version="1.0.0")


@app.on_event("startup")
async def _startup() -> None:
    app.state.client = httpx.AsyncClient(timeout=httpx.Timeout(300.0, connect=15.0))
    if not settings.auth_enabled:
        log.warning("GATEWAY_API_KEYS 为空：网关鉴权已关闭，请勿裸暴露公网！")


@app.on_event("shutdown")
async def _shutdown() -> None:
    with contextlib.suppress(Exception):
        await app.state.client.aclose()


def _unauth() -> JSONResponse:
    return JSONResponse(
        {"error": {"message": "无效的 API key", "type": "invalid_request_error"}},
        status_code=401,
    )


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "providers": list(settings.providers)}

@app.get("/v1/models")
async def list_models(request: Request):
    if not check_key(request.headers.get("authorization"), request.headers.get("x-api-key")):
        return _unauth()
    data = [
        {"id": f"qoder/{m}", "object": "model", "owned_by": "qoder"}
        for m in settings.qoder_models
    ]
    cb = settings.providers["codebuddy"]
    try:
        headers = {"Authorization": f"Bearer {cb.backend_key}"} if cb.backend_key else {}
        r = await app.state.client.get(f"{cb.base_url}/v1/models", headers=headers)
        for item in r.json().get("data", []):
            mid = item.get("id")
            if mid:
                data.append(
                    {"id": f"codebuddy/{mid}", "object": "model", "owned_by": "codebuddy"}
                )
    except Exception as exc:  # noqa: BLE001
        log.warning("拉取 codebuddy 模型失败: %s", exc)
    return {"object": "list", "data": data}


async def _forward(request: Request, path: str, force_provider: str | None = None):
    if not check_key(request.headers.get("authorization"), request.headers.get("x-api-key")):
        return _unauth()
    raw = await request.body()
    try:
        body = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        return JSONResponse({"error": {"message": "请求体不是合法 JSON"}}, status_code=400)

    resolved_provider, upstream_model = resolve(body.get("model", ""))
    provider = force_provider or resolved_provider
    prov = settings.providers.get(provider)
    if prov is None:
        return JSONResponse({"error": {"message": f"未知 provider: {provider}"}}, status_code=400)

    body["model"] = upstream_model
    payload = json.dumps(body).encode()
    headers = {"Content-Type": "application/json", "Accept": request.headers.get("accept", "*/*")}
    if prov.backend_key:
        headers["Authorization"] = f"Bearer {prov.backend_key}"
    url = f"{prov.base_url}{path}"

    if body.get("stream"):
        return _proxy_stream(url, headers, payload, provider)
    try:
        r = await app.state.client.post(url, headers=headers, content=payload)
    except httpx.HTTPError as exc:
        return JSONResponse({"error": {"message": f"后端 {provider} 请求失败: {exc}"}}, status_code=502)
    return Response(
        content=r.content,
        status_code=r.status_code,
        media_type=r.headers.get("content-type", "application/json"),
    )


def _proxy_stream(url: str, headers: dict, payload: bytes, provider: str) -> StreamingResponse:
    async def gen():
        try:
            async with app.state.client.stream("POST", url, headers=headers, content=payload) as r:
                async for chunk in r.aiter_raw():
                    if chunk:
                        yield chunk
        except httpx.HTTPError as exc:
            log.warning("后端 %s 流式失败: %s", provider, exc)
            err = json.dumps({"error": {"message": f"后端 {provider} 流式失败: {exc}"}})
            yield f"data: {err}\n\n".encode()

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    return await _forward(request, "/v1/chat/completions")


@app.post("/v1/messages")
async def anthropic_messages(request: Request):
    # Anthropic 格式仅 codebuddy 后端支持，固定分发过去。
    return await _forward(request, "/v1/messages", force_provider="codebuddy")


