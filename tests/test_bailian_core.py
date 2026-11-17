"""Bailian integration tests: no network, credentials store, or GUI required."""

import ast
import copy
from pathlib import Path
import unittest
from unittest.mock import patch

import core
from config import DEFAULT_CONFIG
from core import MenuItem, UsageMonitor, color_for_remaining


ROOT = Path(__file__).resolve().parents[1]


def monitor_config():
    return {
        "codex": {"enabled": False},
        "glm": {"enabled": False},
        "ark": {"enabled": False},
        "deepseek": {"enabled": False},
        "bailian": {"enabled": True, "cookie": "", "sec_token": ""},
    }


def bare_monitor():
    monitor = object.__new__(UsageMonitor)
    monitor.cfg = monitor_config()
    monitor.last_results = {}
    monitor.last_refresh = None
    monitor.issues = []
    return monitor


def usage(*percentages):
    return {
        "quotas": [
            {"level": "monthly", "percent": percent, "reset_timestamp": None}
            for percent in percentages
        ],
        "source": "cookie",
    }


def menu_texts(monitor):
    return [item.text for item in monitor.build_menu() if isinstance(item, MenuItem)]


class BailianTitleMenuTests(unittest.TestCase):
    def test_title_uses_minimum_remaining_across_all_quotas(self):
        monitor = bare_monitor()
        monitor.last_results = {"bailian": usage(20, 92)}
        self.assertEqual(monitor.compute_title(), ("BL 8%", color_for_remaining(8)))

    def test_title_combines_with_existing_providers(self):
        monitor = bare_monitor()
        monitor.last_results = {
            "codex": {"primary": {"used_percent": 4}},
            "bailian": usage(65),
            "deepseek": {"today": 1.23, "currency": "CNY"},
        }
        self.assertEqual(
            monitor.compute_title(),
            ("CX 96% · BL 35% · DS ¥1.23", color_for_remaining(35)),
        )

    def test_title_clamps_percentages_and_skips_unknown_values(self):
        monitor = bare_monitor()
        monitor.last_results = {"bailian": usage(None, "invalid", 125, -10)}
        self.assertEqual(monitor.compute_title()[0], "BL 0%")

    def test_title_omits_errors_empty_and_unknown_quotas(self):
        monitor = bare_monitor()
        for payload in ({"error": "登录态失效"}, usage(), usage(None, "invalid")):
            with self.subTest(payload=payload):
                monitor.last_results = {"bailian": payload}
                self.assertEqual(monitor.compute_title(), ("AI⚡", color_for_remaining(None)))

    def test_menu_renders_only_actual_monthly_quota_and_source(self):
        monitor = bare_monitor()
        monitor.last_results = {"bailian": usage(25)}
        texts = menu_texts(monitor)
        self.assertIn("百炼 Token Plan", texts)
        self.assertIn("  数据源: 控制台 Cookie", texts)
        self.assertEqual(sum("剩余75%" in text for text in texts), 1)
        self.assertTrue(any("月度" in text and "█" in text for text in texts))
        self.assertFalse(any("小时" in text or "每周" in text for text in texts))

    def test_menu_renders_returned_reset_countdown(self):
        monitor = bare_monitor()
        data = usage(25)
        data["quotas"][0]["reset_timestamp"] = 4600
        monitor.last_results = {"bailian": data}
        with patch("core.time.time", return_value=1000):
            self.assertTrue(any("1小时00分" in text for text in menu_texts(monitor)))

    def test_menu_renders_error_and_empty_states(self):
        monitor = bare_monitor()
        for payload, expected in (({"error": "登录态已失效"}, "⚠ 登录态已失效"),
                                  (usage(), "暂无数据")):
            with self.subTest(payload=payload):
                monitor.last_results = {"bailian": payload}
                self.assertTrue(any(expected in text for text in menu_texts(monitor)))

    def test_absent_null_or_disabled_config_hides_section(self):
        monitor = bare_monitor()
        monitor.last_results = {"bailian": usage(25)}
        for section in (None, {"enabled": False}):
            monitor.cfg["bailian"] = section
            self.assertNotIn("百炼 Token Plan", menu_texts(monitor))
        del monitor.cfg["bailian"]
        self.assertNotIn("百炼 Token Plan", menu_texts(monitor))


class BailianRefreshTests(unittest.TestCase):
    def refresh(self, monitor, credentials=("test-cookie", "test-sec-token"),
                data=None, error=None):
        with patch("core.load_config", return_value=copy.deepcopy(monitor.cfg)), \
             patch("core.secret_store.resolve_bailian_credentials", create=True,
                   return_value=credentials) as resolve, \
             patch("core.bailian_provider.get_usage", return_value=data,
                   side_effect=error) as fetch:
            monitor._do_refresh()
        return resolve, fetch

    def test_refresh_resolves_credentials_and_preserves_result(self):
        monitor = bare_monitor()
        data = usage(20)
        resolve, fetch = self.refresh(monitor, data=data)
        resolve.assert_called_once_with(monitor.cfg, core.save_config)
        fetch.assert_called_once_with("test-cookie", "test-sec-token")
        self.assertEqual(monitor.last_results["bailian"], data)
        self.assertEqual(monitor.issues, [])
        self.assertIsNotNone(monitor.last_refresh)

    def test_missing_cookie_is_renderable_error_without_request(self):
        monitor = bare_monitor()
        _, fetch = self.refresh(monitor, credentials=("", ""))
        fetch.assert_not_called()
        self.assertEqual(monitor.last_results["bailian"], {"error": "Cookie 未设置"})
        self.assertEqual(monitor.issues, ["百炼: Cookie 未设置"])

    def test_returned_error_is_retained_for_menu_and_issues(self):
        monitor = bare_monitor()
        self.refresh(monitor, data={"error": "登录态已失效"})
        self.assertEqual(monitor.last_results["bailian"], {"error": "登录态已失效"})
        self.assertIn("百炼: 登录态已失效", monitor.issues)
        self.assertTrue(any("⚠ 登录态已失效" in text for text in menu_texts(monitor)))

    def test_exception_does_not_discard_other_provider_results(self):
        monitor = bare_monitor()
        monitor.cfg["codex"]["enabled"] = True
        codex = {"primary": {"used_percent": 4}}
        with patch("core.codex_provider.get_usage", return_value=codex):
            self.refresh(monitor, error=RuntimeError("查询失败"))
        self.assertEqual(monitor.last_results["codex"], codex)
        self.assertEqual(monitor.last_results["bailian"], {"error": "查询失败"})
        self.assertIn("百炼: 查询失败", monitor.issues)
        self.assertIsNotNone(monitor.last_refresh)

    def test_resolver_exception_is_retained(self):
        monitor = bare_monitor()
        with patch("core.load_config", return_value=monitor.cfg), \
             patch("core.secret_store.resolve_bailian_credentials", create=True,
                   side_effect=RuntimeError("凭据存储不可用")):
            monitor._do_refresh()
        self.assertEqual(monitor.last_results["bailian"], {"error": "凭据存储不可用"})
        self.assertIn("百炼: 凭据存储不可用", monitor.issues)

    def test_absent_null_or_disabled_config_does_not_fetch(self):
        monitor = bare_monitor()
        for section in (None, {"enabled": False}):
            monitor.cfg["bailian"] = section
            resolve, fetch = self.refresh(monitor)
            resolve.assert_not_called()
            fetch.assert_not_called()
            self.assertEqual(monitor.issues, [])
        del monitor.cfg["bailian"]
        resolve, fetch = self.refresh(monitor)
        resolve.assert_not_called()
        fetch.assert_not_called()
        self.assertEqual(monitor.issues, [])


class BailianIntegrationStructureTests(unittest.TestCase):
    def test_default_config_has_enabled_provider_and_empty_credentials(self):
        self.assertEqual(DEFAULT_CONFIG["bailian"], {
            "enabled": True, "cookie": "", "sec_token": "",
        })

    def test_windows_registers_generic_provider_without_importing_gui(self):
        tree = ast.parse((ROOT / "ui/windows.py").read_text(encoding="utf-8"))
        sections = next(node.value for node in tree.body
                        if isinstance(node, ast.Assign)
                        and any(isinstance(target, ast.Name) and target.id == "SECTIONS"
                                for target in node.targets))
        self.assertIn(("百炼 Token Plan", "bailian", "bailian_provider"),
                      ast.literal_eval(sections))

    def test_core_keeps_gui_free_imports(self):
        tree = ast.parse((ROOT / "core.py").read_text(encoding="utf-8"))
        modules = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                modules.append(node.module or "")
        forbidden = {"ui", "rumps", "tkinter", "pystray", "gi", "PIL", "PyQt5", "PySide6"}
        self.assertFalse({name.split(".")[0] for name in modules} & forbidden)


if __name__ == "__main__":
    unittest.main()
