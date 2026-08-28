import os
import shutil
import unittest

from providers import codex_provider


CODEX_BIN = shutil.which("codex") or os.environ.get("CODEX_BIN", "")


class CodexProviderTests(unittest.TestCase):
    def test_normalizes_live_app_server_response(self):
        result = codex_provider._normalize_rate_limits(
            {
                "limitId": "codex",
                "primary": {
                    "usedPercent": 4,
                    "windowDurationMins": 10080,
                    "resetsAt": 1787015175,
                },
                "secondary": None,
                "credits": {
                    "hasCredits": False,
                    "unlimited": False,
                    "balance": "0",
                },
                "planType": "plus",
            }
        )

        self.assertEqual(result["primary"]["used_percent"], 4.0)
        self.assertEqual(result["primary"]["label"], "每周限额")
        self.assertEqual(result["credits"]["balance"], "0")
        self.assertEqual(result["source"], "live")

    @unittest.skipUnless(os.path.exists(CODEX_BIN), "Codex CLI unavailable")
    def test_reads_live_quota_from_app_server(self):
        result = codex_provider.get_live_usage(CODEX_BIN, timeout=20)

        self.assertEqual(result["source"], "live")
        self.assertIsInstance(result["primary"]["used_percent"], float)
        self.assertIn("balance", result["credits"])

    def test_formats_overage_credit_balance(self):
        label = codex_provider.format_credits(
            {"credits": {"has_credits": False, "unlimited": False, "balance": "0"}}
        )
        self.assertEqual(label, "超额额度: 0")


if __name__ == "__main__":
    unittest.main()
