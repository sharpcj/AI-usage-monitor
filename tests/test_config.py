import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import config


class ConfigTests(unittest.TestCase):
    def test_old_config_persists_missing_defaults_and_preserves_values(self):
        saved = {
            "refresh_interval": 60,
            "glm": {"enabled": False, "api_key": "test-key", "custom": 1},
            "ark": {"enabled": False},
            "codex": {"enabled": True},
            "custom_section": {"keep": True},
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            config_dir = Path(temp_dir)
            config_file = config_dir / "config.json"
            config_file.write_text(json.dumps(saved), encoding="utf-8")
            with patch.object(config, "CONFIG_DIR", config_dir), patch.object(
                config, "CONFIG_FILE", config_file
            ):
                loaded = config.load_config()
                persisted = json.loads(config_file.read_text(encoding="utf-8"))
                for section in ("bailian", "deepseek"):
                    self.assertEqual(persisted[section], config.DEFAULT_CONFIG[section])
                    self.assertEqual(loaded[section], config.DEFAULT_CONFIG[section])
                for key, value in saved.items():
                    if isinstance(value, dict):
                        for field, original in value.items():
                            self.assertEqual(persisted[key][field], original)
                    else:
                        self.assertEqual(persisted[key], value)
                if os.name == "posix":
                    self.assertEqual(os.stat(config_file).st_mode & 0o777, 0o600)
                with patch.object(config, "save_config") as save:
                    config.load_config()
                    save.assert_not_called()

    def test_invalid_config_is_not_overwritten(self):
        for raw in ("not-json", "[]"):
            with self.subTest(raw=raw), tempfile.TemporaryDirectory() as temp_dir:
                config_file = Path(temp_dir) / "config.json"
                config_file.write_text(raw, encoding="utf-8")
                with patch.object(config, "CONFIG_FILE", config_file), patch.object(
                    config, "save_config"
                ) as save:
                    self.assertEqual(config.load_config(), config.DEFAULT_CONFIG)
                    save.assert_not_called()

    def test_migration_write_failure_preserves_loaded_settings(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_file = Path(temp_dir) / "config.json"
            config_file.write_text('{"refresh_interval": 60}', encoding="utf-8")
            with patch.object(config, "CONFIG_FILE", config_file), patch.object(
                config, "save_config", side_effect=OSError("read only")
            ):
                self.assertEqual(config.load_config()["refresh_interval"], 60)

    def test_defaults_are_deep_copied(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_file = Path(temp_dir) / "missing.json"
            with patch.object(config, "CONFIG_FILE", config_file):
                first = config.load_config()
                first["ark"]["enabled"] = False
                second = config.load_config()

        self.assertTrue(second["ark"]["enabled"])

    def test_saved_config_round_trips(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_dir = Path(temp_dir) / "settings"
            config_file = config_dir / "config.json"
            with patch.object(config, "CONFIG_DIR", config_dir), patch.object(
                config, "CONFIG_FILE", config_file
            ):
                config.save_config(config.DEFAULT_CONFIG)
                self.assertEqual(config.load_config(), config.DEFAULT_CONFIG)
                self.assertEqual(
                    json.loads(config_file.read_text(encoding="utf-8")),
                    config.DEFAULT_CONFIG,
                )
                self.assertEqual(list(config_dir.glob("*.tmp")), [])

    @unittest.skipUnless(os.name == "posix", "Requires POSIX permission bits, not Windows ACLs")
    def test_saved_config_is_private(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_dir = Path(temp_dir) / "private"
            config_file = config_dir / "config.json"
            with patch.object(config, "CONFIG_DIR", config_dir), patch.object(
                config, "CONFIG_FILE", config_file
            ):
                config.save_config(config.DEFAULT_CONFIG)

            self.assertEqual(os.stat(config_dir).st_mode & 0o777, 0o700)
            self.assertEqual(os.stat(config_file).st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main()
