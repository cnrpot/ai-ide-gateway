from __future__ import annotations

import unittest

import httpx

from checkin import checkin_trae
from checkin.common import run_accounts


class TraeCheckinTests(unittest.TestCase):
    def test_accounts_continue_after_claim_failure(self) -> None:
        seen: list[tuple[str, str | None]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append((request.url.path, request.headers.get("authorization")))
            if request.headers.get("authorization") == "Cloud-IDE-JWT first-token":
                if request.url.path.endswith("/status"):
                    return httpx.Response(200, json={"checked_in": False, "enable": True})
                return httpx.Response(200, json={"code": 1001, "message": "temporary failure"})
            return httpx.Response(200, json={"checked_in": True, "credits": 10})

        old_log = checkin_trae.log
        checkin_trae.log = lambda _message: None
        try:
            accounts = [
                {"name": "first", "token": "first-token"},
                {"name": "second", "token": "second-token"},
            ]
            with httpx.Client(transport=httpx.MockTransport(handler)) as client:
                result = run_accounts("Trae", accounts, client, checkin_trae.checkin_one)
        finally:
            checkin_trae.log = old_log

        self.assertFalse(result)
        self.assertEqual(
            [path for path, _auth in seen],
            [
                "/trae/api/v2/ug/checkin_credits/status",
                "/trae/api/v2/ug/checkin_credits/claim",
                "/trae/api/v2/ug/checkin_credits/status",
            ],
        )
        self.assertEqual(seen[-1][1], "Cloud-IDE-JWT second-token")


if __name__ == "__main__":
    unittest.main()
