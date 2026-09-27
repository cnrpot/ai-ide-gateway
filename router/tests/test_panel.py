from __future__ import annotations

import unittest

import httpx

from router.app import app
from router.config import settings


class PanelTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.old_panel_key = settings.panel_admin_key
        self.old_qoder_base = settings.providers["qoder"].base_url
        self.old_codebuddy_base = settings.providers["codebuddy"].base_url
        self.old_qoder_host = settings.panel_qoder_host
        self.old_codebuddy_host = settings.panel_codebuddy_host
        settings.panel_admin_key = "panel-test-key"
        settings.panel_qoder_host = "qoder.localhost"
        settings.panel_codebuddy_host = "codebuddy.localhost"
        self.old_panel_cookie_secure = settings.panel_cookie_secure
        settings.panel_cookie_secure = False
        settings.providers["qoder"].base_url = "http://qoder"
        settings.providers["codebuddy"].base_url = "http://codebuddy"

        async def handler(request: httpx.Request) -> httpx.Response:
            if request.url.host == "qoder" and request.url.path == "/":
                return httpx.Response(200, text="<html>qoder console</html>")
            if request.url.host == "codebuddy" and request.url.path == "/health":
                return httpx.Response(200, json={"status": "ok"})
            return httpx.Response(200, json={"ok": True})

        app.state.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

    async def asyncTearDown(self) -> None:
        await app.state.client.aclose()
        settings.panel_admin_key = self.old_panel_key
        settings.panel_cookie_secure = self.old_panel_cookie_secure
        settings.providers["qoder"].base_url = self.old_qoder_base
        settings.providers["codebuddy"].base_url = self.old_codebuddy_base
        settings.panel_qoder_host = self.old_qoder_host
        settings.panel_codebuddy_host = self.old_codebuddy_host

    async def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://localhost:8080",
        )

    async def test_login_status_and_console_urls(self) -> None:
        async with await self._client() as client:
            panel = await client.get("/panel/")
            self.assertEqual(panel.status_code, 200)
            self.assertIn("统一管理面板", panel.text)
            self.assertEqual((await client.get("/panel/api/status")).status_code, 401)
            self.assertEqual(
                (await client.post("/panel/api/login", json={"key": "wrong"})).status_code,
                401,
            )
            login = await client.post("/panel/api/login", json={"key": "panel-test-key"})
            self.assertEqual(login.status_code, 200)
            status = await client.get("/panel/api/status")

        self.assertEqual(status.status_code, 200)
        payload = status.json()
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["consoles"]["qoder"], "http://localhost:8080/qoder/")
        self.assertEqual(payload["consoles"]["codebuddy"], "http://localhost:8080/codebuddy/admin/")

    async def test_host_proxy_keeps_backend_root_paths(self) -> None:
        async with await self._client() as client:
            qoder = await client.get("/", headers={"Host": "qoder.localhost:8080"})
            codebuddy = await client.get("/health", headers={"Host": "codebuddy.localhost:8080"})

        self.assertEqual(qoder.status_code, 200)
        self.assertIn("qoder console", qoder.text)
        self.assertEqual(codebuddy.json(), {"status": "ok"})

    async def test_path_proxy_rewrites_qoder_console_urls(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            if request.url.host == "qoder" and request.url.path == "/":
                return httpx.Response(
                    200,
                    content=(
                        '<html><base href="/"><script src="/assets/app.js"></script>'
                        '<script>fetch("/v1/models")</script></html>'
                    ).encode(),
                    headers={"content-type": "text/html; charset=utf-8"},
                )
            if request.url.host == "qoder" and request.url.path == "/assets/app.js":
                return httpx.Response(
                    200,
                    content=b'fetch(`/v1/models`);',
                    headers={"content-type": "application/javascript"},
                )
            return httpx.Response(404)

        await app.state.client.aclose()
        app.state.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        async with await self._client() as client:
            page = await client.get("/qoder/")
            script = await client.get("/qoder/assets/app.js")

        self.assertEqual(page.status_code, 200)
        self.assertIn('src="/qoder/assets/app.js"', page.text)
        self.assertIn('fetch("/qoder/v1/models")', page.text)
        self.assertIn('href="/qoder/"', page.text)
        self.assertIn("/qoder/v1/models", script.text)

    async def test_path_proxy_rewrites_codebuddy_cookie_and_location(self) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.host, "codebuddy")
            self.assertEqual(request.url.path, "/admin/login")
            return httpx.Response(
                302,
                headers={
                    "location": "/admin/",
                    "set-cookie": "session=abc; Path=/admin; Secure; HttpOnly",
                },
            )

        await app.state.client.aclose()
        app.state.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        async with await self._client() as client:
            response = await client.get("/codebuddy/admin/login")

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["location"], "/codebuddy/admin/")
        self.assertEqual(
            response.headers["set-cookie"],
            "session=abc; Path=/codebuddy/admin; HttpOnly",
        )


if __name__ == "__main__":
    unittest.main()
