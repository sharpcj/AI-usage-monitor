import json
import unittest
from unittest.mock import Mock, patch

from providers import ark_provider


def _arkcli_json(periods, auth_method="sso"):
    return json.dumps({
        "viewer": {"auth_method": auth_method, "account_id": "test"},
        "items": [
            {
                "product": "coding-plan",
                "subscribed": True,
                "periods": periods,
            },
            {"product": "agent-plan", "subscribed": False, "periods": []},
        ],
    })


class ArkProviderTests(unittest.TestCase):
    @patch("providers.ark_provider.requests.post")
    def test_expired_cookie_is_reported_before_json_parsing(self, post):
        response = Mock(status_code=403)
        response.json.side_effect = ValueError("HTML response")
        post.return_value = response

        result = ark_provider.get_usage("csrfToken=token; session=value", "web-id")

        self.assertEqual(result["error"], "Cookie 过期，请重新获取")

    def test_extracts_complete_url_encoded_csrf_cookie_value(self):
        token = ark_provider._extract_csrf_token(
            "other=x; csrfToken=Ab-_123%2Fvalue; session=y"
        )
        self.assertEqual(token, "Ab-_123/value")


class ArkCliPathTests(unittest.TestCase):
    @patch("providers.ark_provider.shutil.which", return_value=None)
    def test_returns_none_when_arkcli_not_installed(self, _which):
        self.assertIsNone(ark_provider.get_usage_via_arkcli())

    @patch("providers.ark_provider.shutil.which", return_value="/usr/local/bin/arkcli")
    @patch("providers.ark_provider.subprocess.run")
    def test_parses_usage_plan_json(self, run, _which):
        run.return_value = Mock(
            returncode=0,
            stdout=_arkcli_json([
                {"label": "session", "percent": 12.5, "reset_at": 1787902964103},
                {"label": "monthly", "percent": 30.0, "reset_at": 1788414791},
            ]),
        )

        result = ark_provider.get_usage_via_arkcli()

        self.assertEqual(result["source"], "arkcli")
        self.assertEqual(len(result["quotas"]), 2)
        session = result["quotas"][0]
        self.assertEqual(session["level"], "session")
        self.assertEqual(session["percent"], 12.5)
        # millisecond reset_at is normalized to seconds
        self.assertEqual(session["reset_timestamp"], 1787902964.103)
        self.assertEqual(result["quotas"][1]["reset_timestamp"], 1788414791)

    @patch("providers.ark_provider.shutil.which", return_value="/usr/local/bin/arkcli")
    @patch("providers.ark_provider.subprocess.run")
    def test_raises_when_not_logged_in(self, run, _which):
        run.return_value = Mock(
            returncode=0, stdout=_arkcli_json([], auth_method="none")
        )

        with self.assertRaisesRegex(RuntimeError, "未登录"):
            ark_provider.get_usage_via_arkcli()

    @patch("providers.ark_provider.shutil.which", return_value="/usr/local/bin/arkcli")
    @patch("providers.ark_provider.subprocess.run")
    def test_raises_when_command_fails(self, run, _which):
        run.return_value = Mock(returncode=1, stdout="", stderr="boom\nline2")

        with self.assertRaisesRegex(RuntimeError, "line2"):
            ark_provider.get_usage_via_arkcli()

    @patch("providers.ark_provider.shutil.which", return_value="/usr/local/bin/arkcli")
    @patch("providers.ark_provider.subprocess.run")
    def test_raises_when_no_subscribed_coding_plan(self, run, _which):
        run.return_value = Mock(
            returncode=0,
            stdout=json.dumps({
                "viewer": {"auth_method": "sso"},
                "items": [{"product": "coding-plan", "subscribed": False}],
            }),
        )

        with self.assertRaisesRegex(RuntimeError, "未找到已订阅"):
            ark_provider.get_usage_via_arkcli()

    def test_formats_5h_label_as_hour_window(self):
        rows = ark_provider.format_usage({
            "quotas": [{"label": "", "level": "5h", "percent": 20, "reset_timestamp": None}],
            "source": "arkcli",
        })
        self.assertEqual(rows[0][0], "小时限额")


if __name__ == "__main__":
    unittest.main()
