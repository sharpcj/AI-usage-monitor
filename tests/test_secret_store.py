import json
import unittest
from unittest.mock import Mock, patch

import secret_store


class SecretStoreTests(unittest.TestCase):
    @patch("secret_store.subprocess.run")
    def test_loads_ark_credentials_from_keychain(self, run):
        run.return_value = Mock(
            returncode=0,
            stdout=json.dumps({"cookie": "private-cookie", "web_id": "private-web-id"}),
        )

        result = secret_store.load_ark_credentials()

        self.assertEqual(result, ("private-cookie", "private-web-id"))

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


class KeychainTransportTests(unittest.TestCase):
    @patch("secret_store.subprocess.run")
    def test_secret_is_passed_via_stdin_not_argv(self, run):
        run.return_value = Mock(returncode=0)

        secret_store.save_glm_api_key("super-secret-key")

        call = run.call_args
        argv = call.args[0]
        stdin_input = call.kwargs.get("input")
        self.assertNotIn("super-secret-key", argv)
        self.assertIn("super-secret-key", stdin_input)


class GlmKeychainTests(unittest.TestCase):
    @patch("secret_store.subprocess.run")
    def test_loads_glm_api_key_from_keychain(self, run):
        run.return_value = Mock(returncode=0, stdout="stored-api-key\n")

        result = secret_store.load_glm_api_key()

        self.assertEqual(result, "stored-api-key")

    @patch("secret_store.subprocess.run")
    def test_loads_missing_glm_key_as_empty(self, run):
        run.return_value = Mock(returncode=44, stdout="")

        result = secret_store.load_glm_api_key()

        self.assertEqual(result, "")

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
    def test_resolves_to_keychain_when_config_has_no_plaintext(self, load_key):
        load_key.return_value = "keychain-key"
        cfg = {"glm": {"enabled": True, "api_key": "", "base_url": ""}}
        save_config = Mock()

        result = secret_store.resolve_glm_api_key(cfg, save_config)

        self.assertEqual(result, "keychain-key")
        save_config.assert_not_called()


if __name__ == "__main__":
    unittest.main()
