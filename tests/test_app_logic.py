import unittest
from unittest.mock import Mock, patch

from app import AIUsageMonitor, clamp_percent, make_bar, pad_label


class AppLogicTests(unittest.TestCase):
    def test_codex_title_uses_most_depleted_window(self):
        app = object.__new__(AIUsageMonitor)
        app.last_results = {
            "codex": {
                "primary": {"used_percent": 10},
                "secondary": {"used_percent": 95},
            }
        }

        title, _ = app.compute_title()

        self.assertEqual(title, "CX 5%")

    def test_codex_title_prefers_five_hour_window(self):
        app = object.__new__(AIUsageMonitor)
        app.last_results = {
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

        title, _ = app.compute_title()

        # Title uses the 5-hour window (5% used -> 95% remaining),
        # not the weekly window (43% used -> 57% remaining)
        self.assertEqual(title, "CX 95%")

    def test_progress_bar_clamps_invalid_percentage(self):
        self.assertEqual(clamp_percent(-10), 0.0)
        self.assertEqual(clamp_percent(110), 100.0)
        self.assertIsNone(clamp_percent("invalid"))
        self.assertEqual(make_bar(-10), "░" * 12)
        self.assertEqual(make_bar(110), "█" * 12)

    def test_pad_label_aligns_quota_labels(self):
        # 4-char CJK labels get no padding; shorter labels get full-width spaces
        self.assertEqual(pad_label("小时限额"), "小时限额")
        self.assertEqual(pad_label("每周限额"), "每周限额")
        self.assertEqual(len(pad_label("限额")), 4)  # 2 CJK + 2 full-width spaces

    def test_main_thread_poll_applies_completed_refresh(self):
        import threading

        app = object.__new__(AIUsageMonitor)
        app._refresh_lock = threading.Lock()
        app._refresh_ready = True
        app._update_menu = Mock()
        timer = Mock()

        app._poll_refresh(timer)

        app._update_menu.assert_called_once_with()
        self.assertFalse(app._refresh_ready)

    @patch("app.codex_provider.get_usage")
    @patch("app.load_config")
    def test_refresh_reloads_config(self, load_config, codex_usage):
        import threading

        load_config.return_value = {
            "refresh_interval": 300,
            "codex": {"enabled": False},
            "glm": {"enabled": False, "api_key": "", "base_url": ""},
            "ark": {"enabled": False, "cookie": "", "web_id": ""},
        }
        app = object.__new__(AIUsageMonitor)
        app.cfg = {
            "codex": {"enabled": True},
            "glm": {"enabled": False},
            "ark": {"enabled": False},
        }
        app.last_results = {}
        app._refresh_lock = threading.Lock()
        app._refresh_in_progress = False
        app._update_menu = Mock()

        # Run the background worker synchronously to verify config reload
        app._do_refresh()

        codex_usage.assert_not_called()
        self.assertFalse(app.cfg["codex"]["enabled"])


if __name__ == "__main__":
    unittest.main()
