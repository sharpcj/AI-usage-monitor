import unittest
from datetime import datetime
from unittest.mock import Mock, patch

from core import (
    UsageMonitor,
    MenuItem,
    MenuSeparator,
    clamp_percent,
    color_for_remaining,
    make_bar,
    pad_label,
)


def bare_monitor():
    monitor = object.__new__(UsageMonitor)
    monitor.last_results = {}
    monitor.issues = []
    monitor.last_refresh = None
    return monitor


class FormatHelperTests(unittest.TestCase):
    def test_progress_bar_clamps_invalid_percentage(self):
        self.assertEqual(clamp_percent(-10), 0.0)
        self.assertEqual(clamp_percent(110), 100.0)
        self.assertIsNone(clamp_percent("invalid"))
        self.assertEqual(make_bar(-10), "░" * 12)
        self.assertEqual(make_bar(110), "█" * 12)

    def test_pad_label_aligns_quota_labels(self):
        self.assertEqual(pad_label("小时限额"), "小时限额")
        self.assertEqual(pad_label("每周限额"), "每周限额")
        self.assertEqual(len(pad_label("限额")), 4)  # 2 CJK + 2 full-width spaces

    def test_color_for_remaining(self):
        self.assertEqual(color_for_remaining(5), "#ff453a")
        self.assertEqual(color_for_remaining(30), "#ff9f0a")
        self.assertEqual(color_for_remaining(80), "#30d158")
        self.assertEqual(color_for_remaining(None), "#8e8e93")


class TitleTests(unittest.TestCase):
    def test_codex_title_uses_most_depleted_window(self):
        monitor = bare_monitor()
        monitor.last_results = {
            "codex": {
                "primary": {"used_percent": 10},
                "secondary": {"used_percent": 95},
            }
        }

        title, _color = monitor.compute_title()

        self.assertEqual(title, "CX 5%")

    def test_codex_title_prefers_five_hour_window(self):
        monitor = bare_monitor()
        monitor.last_results = {
            "codex": {
                "primary": {
                    "used_percent": 5,
                    "label": "小时限额",
                },
                "secondary": {
                    "used_percent": 43,
                    "label": "每周限额",
                },
            }
        }

        title, _color = monitor.compute_title()

        # Title uses the 5-hour window (5% used -> 95% remaining),
        # not the weekly window (43% used -> 57% remaining)
        self.assertEqual(title, "CX 95%")

    def test_title_combines_providers(self):
        monitor = bare_monitor()
        monitor.last_results = {
            "codex": {"primary": {"used_percent": 4, "label": "小时限额"}},
            "ark": {
                "quotas": [
                    {"level": "session", "percent": 53},
                    {"level": "monthly", "percent": 10},
                ]
            },
        }

        title, color = monitor.compute_title()

        self.assertEqual(title, "CX 96% · ARK 47%")
        self.assertEqual(color, "#30d158")


class RefreshTests(unittest.TestCase):
    @patch("core.codex_provider.get_usage")
    @patch("core.load_config")
    def test_refresh_reloads_config(self, load_config, codex_usage):
        load_config.return_value = {
            "refresh_interval": 300,
            "codex": {"enabled": False},
            "glm": {"enabled": False, "api_key": "", "base_url": ""},
            "ark": {"enabled": False, "cookie": "", "web_id": ""},
        }
        monitor = UsageMonitor()

        # Run the background worker synchronously to verify config reload
        monitor._do_refresh()

        codex_usage.assert_not_called()
        self.assertFalse(monitor.cfg["codex"]["enabled"])

    @patch("core.load_config")
    def test_refresh_survives_provider_exceptions(self, load_config):
        load_config.return_value = {
            "refresh_interval": 300,
            "codex": {"enabled": True},
            "glm": {"enabled": False, "api_key": "", "base_url": ""},
            "ark": {"enabled": False, "cookie": "", "web_id": ""},
        }
        monitor = UsageMonitor()

        with patch(
            "core.codex_provider.get_usage",
            side_effect=RuntimeError("codexploded"),
        ):
            monitor._do_refresh()

        self.assertEqual(
            monitor.issues, ["Codex: codexploded"]
        )


class MenuModelTests(unittest.TestCase):
    def test_build_menu_contains_actions_and_status(self):
        monitor = bare_monitor()
        monitor.cfg = {
            "codex": {"enabled": True},
            "glm": {"enabled": False},
            "ark": {"enabled": False},
        }
        monitor.last_refresh = datetime(2026, 8, 28, 10, 0, 0)
        monitor.last_results = {}

        items = monitor.build_menu()

        texts = [i.text for i in items if isinstance(i, MenuItem)]
        self.assertTrue(any("最后刷新" in t for t in texts))
        self.assertTrue(any("Codex (OpenAI)" in t for t in texts))
        actions = [
            i.action for i in items if isinstance(i, MenuItem) and i.action
        ]
        self.assertIn("refresh", actions)
        self.assertIn("config", actions)
        self.assertIn("about", actions)
        self.assertTrue(any(isinstance(i, MenuSeparator) for i in items))

    def test_build_menu_marks_action_items(self):
        monitor = bare_monitor()
        monitor.cfg = {
            "codex": {"enabled": False},
            "glm": {"enabled": False},
            "ark": {"enabled": False},
        }

        items = monitor.build_menu()

        refresh = next(
            i for i in items if isinstance(i, MenuItem) and i.action == "refresh"
        )
        self.assertEqual(refresh.text, "立即刷新")


if __name__ == "__main__":
    unittest.main()
