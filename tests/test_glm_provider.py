import unittest

from providers import glm_provider


class GlmProviderTests(unittest.TestCase):
    def test_formats_credit_limit_quotas(self):
        data = {
            "limits": [
                {
                    "type": "CREDIT_LIMIT",
                    "unit": 3,
                    "number": 5,
                    "percentage": 6,
                    "nextResetTime": 1787902964103,
                },
                {
                    "type": "CREDIT_LIMIT",
                    "unit": 6,
                    "number": 1,
                    "percentage": 6,
                    "nextResetTime": 1788414791996,
                },
            ],
            "level": "lite",
        }

        rows = glm_provider.format_usage(data)

        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0][0], "小时限额")
        self.assertEqual(rows[1][0], "月度限额")
        # epoch milliseconds are normalized to seconds
        self.assertEqual(rows[0][2], 1787902964.103)

    def test_formats_token_limit_quotas_with_iso_reset(self):
        data = {
            "limits": [
                {
                    "type": "TOKENS_LIMIT",
                    "percentage": 40,
                    "nextResetTime": "2026-09-04T00:00:00Z",
                },
                {
                    "type": "TOKENS_LIMIT",
                    "percentage": 10,
                    "nextResetTime": "2026-08-28T12:00:00Z",
                },
            ],
            "level": "pro",
        }

        rows = glm_provider.format_usage(data)

        self.assertEqual(len(rows), 2)
        # sorted by reset time: the earlier reset (12:00) comes first
        self.assertEqual(rows[0], ("小时限额", 10, rows[0][2]))
        self.assertEqual(rows[1][0], "每周限额")

    def test_ignores_unrelated_limit_types(self):
        data = {
            "limits": [
                {"type": "TIME_LIMIT", "percentage": 3, "currentValue": 1, "usage": 30},
            ],
            "level": "lite",
        }

        # TIME_LIMIT (MCP usage) is not a quota window row
        self.assertEqual(glm_provider.format_usage(data), [("MCP每月", 3, None)])


if __name__ == "__main__":
    unittest.main()
