from __future__ import annotations

import unittest
import tempfile
from pathlib import Path

import httpx

from router.app import app
from router.config import settings
from router.management import ManagementHub


class PanelTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.old_panel_key = settings.panel_admin_key
        self.old_qoder_base = settings.providers["qoder"].base_url
        self.old_codebuddy_base = settings.providers["codebuddy"].base_url
        self.old_qoder_host = settings.panel_qoder_host
        self.old_codebuddy_host = settings.panel_codebuddy_host
        self.old_qoder_admin_password = settings.qoder_admin_password
        self.old_codebuddy_admin_key = settings.codebuddy_admin_key
        self.old_checkin_config_path = settings.checkin_config_path
        self.old_checkin_log_path = settings.checkin_log_path
        self.tempdir = tempfile.TemporaryDirectory()
        settings.panel_admin_key = "panel-test-key"
        settings.panel_qoder_host = "qoder.localhost"
        settings.panel_codebuddy_host = "codebuddy.localhost"
        self.old_panel_cookie_secure = settings.panel_cookie_secure
        settings.panel_cookie_secure = False
        settings.qoder_admin_password = "qoder-admin-test"
        settings.codebuddy_admin_key = "codebuddy-admin-test-key-0123456789"
        settings.checkin_config_path = str(Path(self.tempdir.name) / "config.json")
        settings.checkin_log_path = str(Path(self.tempdir.name) / "checkin.log")
        settings.providers["qoder"].base_url = "http://qoder"
        settings.providers["codebuddy"].base_url = "http://codebuddy"

        async def handler(request: httpx.Request) -> httpx.Response:
            if request.url.host == "qoder" and request.url.path == "/":
                return httpx.Response(200, text="<html>qoder console</html>")
            if request.url.host == "qoder" and request.url.path == "/ui/status":
                return httpx.Response(200, json={"ready": True, "mode": "accounts", "accounts_count": 1})
            if request.url.host == "qoder" and request.url.path == "/ui/accounts":
                return httpx.Response(
                    200,
                    json={
                        "active_uid": "q-1",
                        "accounts": [{"uid": "q-1", "name": "Qoder test", "enabled": True, "user_type": "cn"}],
                    },
                )
            if request.url.host == "codebuddy" and request.url.path == "/health":
                return httpx.Response(200, json={"status": "ok"})
            if request.url.host == "codebuddy" and request.url.path == "/admin/api/login":
                return httpx.Response(
                    200,
                    json={"csrf": "csrf-test"},
                    headers={"set-cookie": "workbuddy_admin=session-test; Path=/admin; HttpOnly"},
                )
            if request.url.host == "codebuddy" and request.url.path == "/admin/api/overview":
                return httpx.Response(
                    200,
                    json={"accounts": [], "pool": {"routing": "round_robin", "auto_checkin": True, "checkin_time": "09:00"}, "keys": [], "models": []},
                )
            return httpx.Response(200, json={"ok": True})

        app.state.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        app.state.management = ManagementHub(app.state.client)

    async def asyncTearDown(self) -> None:
        await app.state.client.aclose()
        settings.panel_admin_key = self.old_panel_key
        settings.panel_cookie_secure = self.old_panel_cookie_secure
        settings.qoder_admin_password = self.old_qoder_admin_password
        settings.codebuddy_admin_key = self.old_codebuddy_admin_key
        settings.checkin_config_path = self.old_checkin_config_path
        settings.checkin_log_path = self.old_checkin_log_path
        settings.providers["qoder"].base_url = self.old_qoder_base
        settings.providers["codebuddy"].base_url = self.old_codebuddy_base
        settings.panel_qoder_host = self.old_qoder_host
        settings.panel_codebuddy_host = self.old_codebuddy_host
        self.tempdir.cleanup()

    async def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://localhost:8080",
        )

    async def test_login_status_and_console_urls(self) -> None:
        async with await self._client() as client:
            panel = await client.get("/panel/")
            self.assertEqual(panel.status_code, 200)
            self.assertIn("一个页面", panel.text)
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

    async def test_single_page_overview_aggregates_provider_management_data(self) -> None:
        async with await self._client() as client:
            login = await client.post("/panel/api/login", json={"key": "panel-test-key"})
            self.assertEqual(login.status_code, 200)
            response = await client.get("/panel/api/overview")

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["providers"]["qoder"]["management"]["ok"])
        self.assertEqual(payload["providers"]["qoder"]["management"]["data"]["accounts"]["active_uid"], "q-1")
        self.assertTrue(payload["providers"]["codebuddy"]["management"]["ok"])
        self.assertEqual(payload["checkin"]["providers"]["trae"]["count"], 0)

    async def test_single_page_checkin_config_masks_tokens(self) -> None:
        async with await self._client() as client:
            await client.post("/panel/api/login", json={"key": "panel-test-key"})
            saved = await client.post(
                "/panel/api/checkin/accounts",
                json={"provider": "trae", "account": {"name": "demo", "token": "trae-secret-token", "region": "cn"}},
            )
            listed = await client.get("/panel/api/checkin")

        self.assertEqual(saved.status_code, 200)
        self.assertEqual(listed.status_code, 200)
        self.assertNotIn("trae-secret-token", listed.text)
        self.assertEqual(listed.json()["providers"]["trae"]["accounts"][0]["token_hint"], "…oken")


if __name__ == "__main__":
    unittest.main()
