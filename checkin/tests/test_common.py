from __future__ import annotations

import unittest

import httpx

from checkin.common import run_accounts


class RunAccountsTests(unittest.TestCase):
    def test_does_not_short_circuit_after_failure(self) -> None:
        seen: list[str] = []

        def check(account: dict, _http: httpx.Client) -> bool:
            seen.append(account["name"])
            return account["name"] != "first"

        with httpx.Client() as client:
            result = run_accounts(
                "test",
                [{"name": "first"}, {"name": "second"}],
                client,
                check,
            )
        self.assertFalse(result)
        self.assertEqual(seen, ["first", "second"])


if __name__ == "__main__":
    unittest.main()
