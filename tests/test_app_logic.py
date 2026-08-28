"""Tests that exercise the macOS rumps UI layer (darwin only)."""

import sys
import threading
import unittest
from unittest.mock import Mock

try:
    from app import AIUsageMonitor

    HAS_MAC_UI = sys.platform == "darwin"
except Exception:  # rumps / PyObjC unavailable on non-macOS runners
    HAS_MAC_UI = False


@unittest.skipUnless(HAS_MAC_UI, "requires macOS UI stack (rumps)")
class MacOSAppTests(unittest.TestCase):
    def test_main_thread_poll_applies_completed_refresh(self):
        app = object.__new__(AIUsageMonitor)
        app._refresh_lock = threading.Lock()
        app._refresh_ready = True
        app._update_menu = Mock()
        timer = Mock()

        app._poll_refresh(timer)

        app._update_menu.assert_called_once_with()
        self.assertFalse(app._refresh_ready)

    def test_app_delegates_state_to_monitor(self):
        app = object.__new__(AIUsageMonitor)
        app.monitor = Mock()
        app.monitor.cfg = {"codex": {"enabled": True}}
        app.monitor.last_results = {"codex": {}}

        self.assertEqual(app.cfg, app.monitor.cfg)
        self.assertEqual(app.last_results, app.monitor.last_results)

        app.last_results = {}
        self.assertEqual(app.monitor.last_results, {})


if __name__ == "__main__":
    unittest.main()
