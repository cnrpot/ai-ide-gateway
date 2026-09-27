from __future__ import annotations

import json
import unittest

import httpx

from router.app import app
from router.config import settings


class RouterProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.old_keys = settings.gateway_keys
        self.old_anonymous = settings.allow_anonymous
        self.old_qoder_key = settings.providers["qoder"].backend_key
        self.old_codebuddy_key = settings.providers["codebuddy"].backend_key
        settings.gateway_keys = ["gateway-test"]
        settings.allow_anonymous = False
        settings.providers["qoder"].backend_key = "qoder-backend"
        settings.providers["codebuddy"].backend_key = "codebuddy-backend"
        self.seen: list[tuple[str, str | None, str | None]] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content or b"{}")
            self.seen.append(
                (request.url.path, request.headers.get("authorization"), body.get("model"))
            )
            if request.url.path == "/v1/models":
                return httpx.Response(200, json={"data": [{"id": "auto"}]})
            if body.get("stream"):
                return httpx.Response(
                    200,
                    stream=httpx.ByteStream(b"data: {\"done\":true}\n\ndata: [DONE]\n\n"),
                    headers={"content-type": "text/event-stream"},
                )
            return httpx.Response(
                200,
                json={"model": body.get("model")},
                headers={"x-request-id": "mock-request"},
            )

        app.state.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    async def asyncTearDown(self) -> None:
        await app.state.client.aclose()
        settings.gateway_keys = self.old_keys
        settings.allow_anonymous = self.old_anonymous
        settings.providers["qoder"].backend_key = self.old_qoder_key
        settings.providers["codebuddy"].backend_key = self.old_codebuddy_key

    async def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://router")

    async def test_auth_and_protocol_routing(self) -> None:
        async with await self._client() as client:
            self.assertEqual((await client.get("/v1/models")).status_code, 401)
            models = await client.get(
                "/v1/models", headers={"Authorization": "Bearer gateway-test"}
            )
            qoder = await client.post(
                "/v1/chat/completions",
                headers={"Authorization": "Bearer gateway-test"},
                json={"model": "qoder/lite", "messages": []},
            )
            responses = await client.post(
                "/v1/responses",
                headers={"Authorization": "Bearer gateway-test"},
                json={"model": "codebuddy/auto", "input": "hello"},
            )
            messages = await client.post(
                "/v1/messages",
                headers={"Authorization": "Bearer gateway-test"},
                json={"model": "claude", "messages": []},
            )

        self.assertEqual(models.status_code, 200)
        self.assertEqual([item["id"] for item in models.json()["data"]], ["qoder/lite", "codebuddy/auto"])
        self.assertEqual(qoder.json()["model"], "lite")
        self.assertEqual(responses.json()["model"], "auto")
        self.assertEqual(messages.json()["model"], "claude")
        self.assertIn(("/v1/chat/completions", "Bearer qoder-backend", "lite"), self.seen)
        self.assertIn(("/v1/responses", "Bearer codebuddy-backend", "auto"), self.seen)
        self.assertIn(("/v1/messages", "Bearer codebuddy-backend", "claude"), self.seen)

    async def test_streaming_is_transparent(self) -> None:
        async with await self._client() as client:
            response = await client.post(
                "/v1/chat/completions",
                headers={"Authorization": "Bearer gateway-test"},
                json={"model": "qoder/lite", "messages": [], "stream": True},
            )
        self.assertEqual(response.status_code, 200)
        self.assertIn("data: [DONE]", response.text)
        self.assertEqual(response.headers.get("content-type"), "text/event-stream")

    async def test_anthropic_rejects_qoder_prefix(self) -> None:
        async with await self._client() as client:
            response = await client.post(
                "/v1/messages",
                headers={"Authorization": "Bearer gateway-test"},
                json={"model": "qoder/lite", "messages": []},
            )
        self.assertEqual(response.status_code, 400)


if __name__ == "__main__":
    unittest.main()
