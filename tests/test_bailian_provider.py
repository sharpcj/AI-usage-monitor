import json
import unittest
from unittest.mock import Mock, patch

import requests

from providers import bailian_provider as provider
from update_bailian_creds import extract_credentials, main
import secret_store


def gateway(usage):
    return {"code": "200", "successResponse": True, "data": {
        "DataV2": {"data": {"success": True, "data": usage}}
    }}


def curl(cookie="session=private", token="csrf-private"):
    from urllib.parse import urlencode
    url = provider.GATEWAY_URL + "?api=" + provider.API_NAME
    return "curl '" + url + "' -b '" + cookie + "' --data-raw '" + urlencode({"sec_token": token}) + "'"


class UsageTests(unittest.TestCase):
    def test_gateway_ratios_are_used_not_remaining_percent(self):
        data = provider.parse_usage(gateway({
            "per1MonthPercentage": 0.125,
            "per1MonthResetTime": 1796000000000,
        }))
        self.assertEqual(data["quotas"], [{
            "level": "monthly", "percent": 12.5, "reset_timestamp": 1796000000,
        }])
        self.assertEqual(provider.format_usage(data), [("月度限额", 12.5, 1796000000)])

    def test_unwrapped_legacy_windows_and_zero(self):
        data = provider.parse_usage({"per5HourPercentage": 0, "per1WeekPercentage": 1.2})
        self.assertEqual([q["percent"] for q in data["quotas"]], [0, 100])
        self.assertEqual([q["level"] for q in data["quotas"]], ["session", "weekly"])

    def test_unknown_is_not_zero(self):
        for payload in ({}, {"per1MonthPercentage": None}, {"per1MonthResetTime": 1796000000000}):
            with self.subTest(payload=payload):
                self.assertIn("error", provider.parse_usage(gateway(payload)))

    def test_invalid_ratios_are_errors(self):
        for value in (True, "invalid", float("nan"), float("inf"), -1, [], {}):
            with self.subTest(value=value):
                self.assertIn("error", provider.parse_usage(gateway({"per1MonthPercentage": value})))

    def test_login_failure_inside_http_200(self):
        result = provider.parse_usage({"code": "200", "successResponse": True, "data": {
            "success": False, "errorCode": "BailianGateway.Login.NotLogined",
        }})
        self.assertIn("登录态", result["error"])

    def test_permission_and_malformed_and_business_failure(self):
        for payload in (None, [], {"data": "invalid"}, {"successResponse": False},
                        gateway({"success": False, "errorCode": "NoPermission"})):
            self.assertIn("error", provider.parse_usage(payload))
        self.assertEqual(provider.format_usage({"error": "bad"}), [])

    def test_reset_formats(self):
        normalize = provider._reset_timestamp
        self.assertEqual(normalize("1796000000000"), 1796000000)
        self.assertEqual(normalize(1796000000), 1796000000)
        self.assertEqual(normalize("2026-11-17T08:00:00+08:00"), normalize("2026-11-17T00:00:00Z"))
        self.assertEqual(normalize("2026-11-17 08:00:00"), normalize("2026-11-17T00:00:00Z"))
        for value in (None, True, 0, -1, "oops", float("inf")):
            self.assertIsNone(normalize(value))

    @patch("providers.bailian_provider.requests.post")
    def test_http_request_contract(self, post):
        post.return_value = Mock(status_code=200)
        post.return_value.json.return_value = gateway({"per1MonthPercentage": 0.3})
        self.assertNotIn("error", provider.get_usage("private-cookie", "private-csrf"))
        args = post.call_args.kwargs
        self.assertEqual(args["headers"]["Cookie"], "private-cookie")
        self.assertEqual(args["data"]["sec_token"], "private-csrf")
        self.assertEqual(json.loads(args["data"]["params"])["Api"], provider.API_NAME)
        self.assertEqual(args["data"]["region"], "cn-beijing")
        self.assertFalse(args["allow_redirects"])
        self.assertEqual(args["timeout"], 15)

    @patch("providers.bailian_provider.requests.post")
    def test_request_failures_do_not_leak_credentials(self, post):
        for status in (302, 401, 403, 429, 500):
            post.return_value = Mock(status_code=status)
            self.assertIn("error", provider.get_usage("private-cookie"))
        post.return_value = Mock(status_code=200)
        post.return_value.json.side_effect = ValueError("private-cookie")
        self.assertNotIn("private-cookie", provider.get_usage("private-cookie")["error"])
        post.side_effect = requests.RequestException("private-cookie")
        self.assertNotIn("private-cookie", provider.get_usage("private-cookie")["error"])

    @patch("providers.bailian_provider.requests.post")
    def test_no_cookie_does_not_query(self, post):
        self.assertIn("error", provider.get_usage(""))
        post.assert_not_called()


class CredentialTests(unittest.TestCase):
    def test_curl_cookie_and_csrf(self):
        self.assertEqual(extract_credentials(curl()), ("session=private", "csrf-private"))
        self.assertEqual(extract_credentials(curl().replace("-b 'session=private'", "-H 'cookie: session=private'")),
                         ("session=private", "csrf-private"))
        self.assertEqual(extract_credentials(curl(token="a+b=/")), ("session=private", "a+b=/"))

    def test_reject_wrong_request_and_never_execute(self):
        for raw in ("https://example.com", "cookie=private", "curl 'bad", "curl https://evil.test -b x=y",
                    curl().replace("/api/v2/usage", "/api/v2/subscription"), curl(cookie="")):
            with self.subTest(raw=raw):
                self.assertRaises(ValueError, extract_credentials, raw)

    @patch("secret_store.keyring.set_password")
    @patch("secret_store.keyring.get_password")
    def test_storage_and_migration(self, get_secret, set_secret):
        cfg = {"bailian": {"cookie": "a=b", "sec_token": "csrf"}}
        save = Mock()
        self.assertEqual(secret_store.resolve_bailian_credentials(cfg, save), ("a=b", "csrf"))
        self.assertEqual(json.loads(set_secret.call_args.args[2]), {"cookie": "a=b", "sec_token": "csrf"})
        self.assertEqual(set_secret.call_args.args[0], secret_store.BAILIAN_SERVICE)
        self.assertEqual(cfg["bailian"], {"cookie": "", "sec_token": ""})
        save.assert_called_once_with(cfg)
        get_secret.return_value = json.dumps({"cookie": "stored=1", "sec_token": "s"})
        self.assertEqual(secret_store.resolve_bailian_credentials({}, Mock()), ("stored=1", "s"))
        for value in (None, "bad", "[]", "null"):
            get_secret.return_value = value
            self.assertEqual(secret_store.load_bailian_credentials(), ("", ""))

    @patch("secret_store.save_bailian_credentials", side_effect=RuntimeError("unavailable"))
    def test_failed_migration_does_not_clear(self, _save):
        cfg = {"bailian": {"cookie": "a=b", "sec_token": "csrf"}}
        callback = Mock()
        self.assertRaises(RuntimeError, secret_store.resolve_bailian_credentials, cfg, callback)
        self.assertEqual(cfg["bailian"]["cookie"], "a=b")
        callback.assert_not_called()

    @patch("update_bailian_creds.read_clipboard", return_value=curl())
    @patch("update_bailian_creds.save_bailian_credentials")
    @patch("update_bailian_creds.bailian_provider.get_usage", return_value={"error": "expired"})
    def test_failed_verification_does_not_store(self, _usage, save, _clipboard):
        self.assertEqual(main([]), 1)
        save.assert_not_called()

    @patch("update_bailian_creds.read_clipboard", return_value=curl())
    @patch("update_bailian_creds.save_bailian_credentials")
    @patch("update_bailian_creds.load_bailian_credentials", return_value=("session=private", "csrf-private"))
    @patch("update_bailian_creds.bailian_provider.get_usage", return_value={"quotas": []})
    def test_script_validates_then_saves_and_reads_back(self, usage, _load, save, _clipboard):
        self.assertEqual(main([]), 0)
        save.assert_called_once_with("session=private", "csrf-private")
        self.assertEqual(usage.call_count, 2)


if __name__ == "__main__":
    unittest.main()
