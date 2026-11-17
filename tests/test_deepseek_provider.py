import json
import unittest
from datetime import date
from unittest.mock import Mock, patch

from providers import deepseek_provider


def _cost_payload(days):
    """Build a console-API cost response: days = {date: [(type, amount), ...]}."""
    return {
        "code": 0,
        "msg": "",
        "data": {
            "biz_data": [
                {
                    "total": [],
                    "days": [
                        {
                            "date": day,
                            "data": [
                                {
                                    "model": "deepseek-v4-flash",
                                    "usage": [
                                        {"type": kind, "amount": amount}
                                        for kind, amount in entries
                                    ],
                                }
                            ],
                        }
                        for day, entries in days.items()
                    ],
                }
            ]
        },
    }


class BalanceTests(unittest.TestCase):
    @patch("providers.deepseek_provider.requests.get")
    def test_parses_balance_infos(self, get):
        get.return_value = Mock(
            status_code=200,
            json=Mock(
                return_value={
                    "is_available": True,
                    "balance_infos": [
                        {
                            "currency": "CNY",
                            "total_balance": "7.63",
                            "granted_balance": "0.00",
                            "topped_up_balance": "7.63",
                        }
                    ],
                }
            ),
        )

        result = deepseek_provider.get_balance("sk-test")

        self.assertTrue(result["is_available"])
        self.assertEqual(result["balances"][0]["total"], 7.63)
        self.assertEqual(result["balances"][0]["topped_up"], 7.63)

    @patch("providers.deepseek_provider.requests.get")
    def test_reports_invalid_api_key(self, get):
        get.return_value = Mock(status_code=401, json=Mock(return_value={}))

        self.assertEqual(
            deepseek_provider.get_balance("bad")["error"], "API Key 无效"
        )


class DailyCostTests(unittest.TestCase):
    @patch("providers.deepseek_provider.requests.get")
    def test_sums_cost_entries_and_ignores_request_counts(self, get):
        get.return_value = Mock(
            status_code=200,
            json=Mock(
                return_value=_cost_payload(
                    {
                        "2026-10-19": [
                            ("PROMPT_CACHE_HIT_TOKEN", "0.25"),
                            ("PROMPT_CACHE_MISS_TOKEN", "0.50"),
                            ("RESPONSE_TOKEN", "1.00"),
                            ("REQUEST", "42"),
                        ]
                    }
                )
            ),
        )

        days = deepseek_provider._fetch_month_cost("token", 2026, 10)

        self.assertEqual(days["2026-10-19"], 1.75)

    @patch("providers.deepseek_provider.requests.get")
    def test_expired_token_is_detected_in_body(self, get):
        get.return_value = Mock(
            status_code=200,
            json=Mock(
                return_value={
                    "code": 40003,
                    "msg": "Authorization Failed (invalid token)",
                    "data": None,
                }
            ),
        )

        with self.assertRaises(deepseek_provider.PlatformTokenExpired):
            deepseek_provider._fetch_month_cost("stale", 2026, 10)

    def test_seven_day_window_spans_two_months(self):
        calls = []

        def fake_month(token, year, month, timeout=15):
            calls.append((year, month))
            return {
                "2026-10-30": 1.0,
                "2026-10-31": 2.0,
                "2026-11-01": 4.0,
                "2026-11-02": 8.0,
            }

        with patch(
            "providers.deepseek_provider._month_cost_cached", side_effect=fake_month
        ):
            result = deepseek_provider.get_daily_cost(
                "token", window_days=7, today=date(2026, 11, 3)
            )

        self.assertEqual(calls, [(2026, 10), (2026, 11)])
        self.assertEqual(len(result["days"]), 7)
        self.assertEqual(result["days"][0]["date"], "2026-10-28")
        self.assertEqual(result["days"][-1], {"date": "2026-11-03", "cost": 0.0})
        self.assertEqual(result["today"], 0.0)
        self.assertEqual(result["last7"], 15.0)

    def test_today_and_last7_follow_the_window(self):
        with patch(
            "providers.deepseek_provider._month_cost_cached",
            return_value={
                "2026-10-13": 1.0,
                "2026-10-18": 2.0,
                "2026-10-19": 3.5,
            },
        ):
            result = deepseek_provider.get_daily_cost(
                "token", window_days=7, today=date(2026, 10, 19)
            )

        self.assertEqual(result["today"], 3.5)
        self.assertEqual(result["last7"], 6.5)


class AggregateTests(unittest.TestCase):
    def test_balance_only_degrades_with_a_warning(self):
        with patch.object(
            deepseek_provider,
            "get_balance",
            return_value={
                "is_available": True,
                "balances": [
                    {
                        "currency": "CNY",
                        "total": 7.63,
                        "granted": 0.0,
                        "topped_up": 7.63,
                    }
                ],
            },
        ):
            result = deepseek_provider.get_usage("sk-test", platform_token="")

        self.assertEqual(result["balances"][0]["total"], 7.63)
        self.assertIsNone(result["today"])
        self.assertIn("平台 Token 未设置", result["warning"])

    def test_without_any_credential_reports_error(self):
        result = deepseek_provider.get_usage()

        self.assertIn("error", result)
        self.assertIn("API Key 未设置", result["error"])

    def test_spend_does_not_lose_balance_when_token_expired(self):
        with patch.object(
            deepseek_provider,
            "get_balance",
            return_value={
                "is_available": True,
                "balances": [
                    {"currency": "CNY", "total": 5.0, "granted": 0.0, "topped_up": 5.0}
                ],
            },
        ), patch.object(
            deepseek_provider, "get_daily_cost", side_effect=RuntimeError("已过期")
        ):
            result = deepseek_provider.get_usage("sk-test", platform_token="stale")

        self.assertEqual(result["balances"][0]["total"], 5.0)
        self.assertIn("已过期", result["warning"])


class FormattingTests(unittest.TestCase):
    def test_money_keeps_four_decimals_for_tiny_amounts(self):
        self.assertEqual(deepseek_provider.format_money(0.0042), "¥0.0042")
        self.assertEqual(deepseek_provider.format_money(12.5), "¥12.50")
        self.assertEqual(deepseek_provider.format_money(1234.5), "¥1,234.50")

    def test_usage_rows_show_today_and_seven_days(self):
        rows = deepseek_provider.format_usage(
            {
                "currency": "CNY",
                "today": 1.23,
                "last7": 8.5,
                "balances": [
                    {"currency": "CNY", "total": 7.63, "granted": 0.0, "topped_up": 7.63}
                ],
            }
        )

        labels = [label for label, _ in rows]
        self.assertEqual(labels, ["今日消费", "近7天合计", "账户余额"])
        self.assertEqual(rows[0][1], "¥1.23")
        # Balance is shown as a plain amount, without the top-up breakdown.
        self.assertEqual(rows[2][1], "¥7.63")


if __name__ == "__main__":
    unittest.main()
