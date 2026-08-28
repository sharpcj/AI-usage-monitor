import json
import unittest
from unittest.mock import Mock, call, patch

import secret_store


class ArkKeyringTests(unittest.TestCase):
    @patch("secret_store.keyring.get_password")
    def test_loads_ark_credentials(self, get_password):
        get_password.return_value = json.dumps(
            {"cookie": "private-cookie", "web_id": "private-web-id"}
        )

        result = secret_store.load_ark_credentials()

        get_password.assert_called_once_with(
            secret_store.ARK_SERVICE, secret_store.ACCOUNT
        )
        self.assertEqual(result, ("private-cookie", "private-web-id"))

    @patch("secret_store.keyring.get_password", return_value=None)
    def test_loads_missing_ark_credentials_as_empty(self, get_password):
        self.assertEqual(secret_store.load_ark_credentials(), ("", ""))

    @patch("secret_store.keyring.get_password")
    def test_keychain_failure_returns_empty(self, get_password):
        get_password.side_effect = RuntimeError("no secret service")

        self.assertEqual(secret_store.load_ark_credentials(), ("", ""))
        self.assertEqual(secret_store.load_glm_api_key(), "")

    @patch("secret_store.keyring.set_password")
    def test_saves_ark_credentials_as_json_payload(self, set_password):
        secret_store.save_ark_credentials("cookie-1", "web-1")

        payload = set_password.call_args.args[2]
        self.assertEqual(
            json.loads(payload), {"cookie": "cookie-1", "web_id": "web-1"}
        )

    @patch("secret_store.save_ark_credentials")
    def test_migrates_config_credentials_and_clears_plaintext(self, save_secret):
        cfg = {
            "ark": {
                "enabled": True,
                "cookie": "private-cookie",
                "web_id": "private-web-id",
            }
        }
        save_config = Mock()

        result = secret_store.resolve_ark_credentials(cfg, save_config)

        self.assertEqual(result, ("private-cookie", "private-web-id"))
        save_secret.assert_called_once_with("private-cookie", "private-web-id")
        self.assertEqual(cfg["ark"]["cookie"], "")
        self.assertEqual(cfg["ark"]["web_id"], "")
        save_config.assert_called_once_with(cfg)


class GlmKeyringTests(unittest.TestCase):
    @patch("secret_store.keyring.get_password", return_value="stored-api-key")
    def test_loads_glm_api_key(self, get_password):
        self.assertEqual(secret_store.load_glm_api_key(), "stored-api-key")
        get_password.assert_called_once_with(
            secret_store.GLM_SERVICE, secret_store.ACCOUNT
        )

    @patch("secret_store.keyring.set_password")
    def test_saves_glm_api_key(self, set_password):
        secret_store.save_glm_api_key("key-1")

        self.assertEqual(
            set_password.call_args, call(secret_store.GLM_SERVICE, secret_store.ACCOUNT, "key-1")
        )

    @patch("secret_store.save_glm_api_key")
    def test_migrates_plaintext_glm_key_and_clears_config(self, save_key):
        cfg = {"glm": {"enabled": True, "api_key": "legacy-key", "base_url": ""}}
        save_config = Mock()

        result = secret_store.resolve_glm_api_key(cfg, save_config)

        self.assertEqual(result, "legacy-key")
        save_key.assert_called_once_with("legacy-key")
        self.assertEqual(cfg["glm"]["api_key"], "")
        save_config.assert_called_once_with(cfg)

    @patch("secret_store.load_glm_api_key")
    def test_resolves_to_keyring_when_config_has_no_plaintext(self, load_key):
        load_key.return_value = "keychain-key"
        cfg = {"glm": {"enabled": True, "api_key": "", "base_url": ""}}
        save_config = Mock()

        result = secret_store.resolve_glm_api_key(cfg, save_config)

        self.assertEqual(result, "keychain-key")
        save_config.assert_not_called()


if __name__ == "__main__":
    unittest.main()
