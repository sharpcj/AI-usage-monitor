import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import config


class ConfigTests(unittest.TestCase):
    def test_defaults_are_deep_copied(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_file = Path(temp_dir) / "missing.json"
            with patch.object(config, "CONFIG_FILE", config_file):
                first = config.load_config()
                first["ark"]["enabled"] = False
                second = config.load_config()

        self.assertTrue(second["ark"]["enabled"])

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
