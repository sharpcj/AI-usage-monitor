#!/usr/bin/env python3
"""
AI Usage Monitor - macOS menu bar app
Monitors Codex / GLM / Volcengine Ark coding plan quotas.

Usage:
    .venv/bin/python app.py

First-time setup: edit ~/.config/ai-usage-monitor/config.json
"""

import json
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

import rumps

# Ensure we can import local modules
sys.path.insert(0, str(Path(__file__).parent))

from config import load_config, save_config, CONFIG_FILE
import secret_store
from providers import codex_provider, glm_provider, ark_provider

REFRESH_INTERVAL_DEFAULT = 300  # 5 minutes


def _noop_callback(sender):
    """Empty callback so menu items render as normal (not grayed out)."""
    pass


def human_reset(resets_at):
    """Format reset timestamp to human-readable countdown."""
    if not resets_at:
        return ""
    # resets_at could be epoch (int/float) or ISO string
    if isinstance(resets_at, (int, float)):
        epoch = resets_at
    elif isinstance(resets_at, str):
        try:
            epoch = datetime.fromisoformat(
                resets_at.replace("Z", "+00:00")
            ).timestamp()
        except (ValueError, TypeError):
            return ""
    else:
        return ""

    mins = int((epoch - time.time()) / 60)
    if mins <= 0:
        return "已重置"
    d, h, m = mins // 1440, (mins % 1440) // 60, mins % 60
    if d:
        return f"{d}天{h}小时"
    if h:
        return f"{h}小时{m:02d}分"
    return f"{m}分钟"


def color_for_remaining(remaining_pct):
    """Return hex color string based on remaining percentage."""
    if remaining_pct is None:
        return "#8e8e93"
    if remaining_pct <= 15:
        return "#ff453a"  # red
    if remaining_pct <= 40:
        return "#ff9f0a"  # orange
    return "#30d158"  # green


def clamp_percent(value):
    """Convert a percentage to float and clamp it to 0..100."""
    try:
        return max(0.0, min(100.0, float(value)))
    except (TypeError, ValueError):
        return None


def make_bar(remaining_pct, width=12):
    """Make a text progress bar showing remaining portion."""
    remaining_pct = clamp_percent(remaining_pct)
    if remaining_pct is None:
        return "-" * width
    filled = int(round(remaining_pct / 100 * width))
    return "█" * filled + "░" * (width - filled)


def pad_label(label, width=4):
    """Pad a label with full-width spaces so progress bars align.

    Chinese chars count as one unit; we pad to `width` CJK chars using
    full-width spaces (U+3000), which keep alignment in menu bars.
    """
    label = str(label)
    current = sum(1 for ch in label if ord(ch) > 0x2E80) + sum(
        1 for ch in label if ord(ch) <= 0x2E80 and ch != " "
    )
    # approximate: CJK chars and latin chars both count as 1 slot here;
    # we only need consistency across the fixed label set
    pad = max(0, width - current)
    return label + "\u3000" * pad


class AIUsageMonitor(rumps.App):
    def __init__(self):
        super().__init__(
            "AI⚡",
            icon=None,
            template=None,
            quit_button=rumps.MenuItem("退出"),
        )
        self.cfg = load_config()
        self.last_results = {}
        self.last_refresh = None
        self._refresh_lock = threading.Lock()
        self._refresh_in_progress = False
        self._refresh_ready = False

        # Menu items
        self.menu_items = {}
        self.status_item = rumps.MenuItem("初始化中...", callback=_noop_callback)
        self.refresh_item = rumps.MenuItem("立即刷新", callback=self._on_refresh)
        self.config_item = rumps.MenuItem("编辑配置", callback=self._on_edit_config)
        self.about_item = rumps.MenuItem("关于", callback=self._on_about)

    def compute_title(self):
        """Build menu bar title from latest results (showing remaining %)."""
        bits = []
        all_remaining = []

        if self.last_results.get("codex"):
            cx = self.last_results["codex"]
            if "error" not in cx:
                # Title shows the 5-hour quota when available
                windows = [cx.get("primary"), cx.get("secondary")]
                windows = [w for w in windows if w]
                five_hour = [
                    w for w in windows if w.get("label") == "小时限额"
                ]
                target = five_hour or windows
                used_values = [
                    clamp_percent(w.get("used_percent")) for w in target
                ]
                used_values = [v for v in used_values if v is not None]
                if used_values:
                    remaining = 100 - max(used_values)
                    bits.append(f"CX {remaining:.0f}%")
                    all_remaining.append(remaining)

        if self.last_results.get("glm"):
            glm = self.last_results["glm"]
            if "error" not in glm:
                limits = glm.get("limits", [])
                quota_limits = [
                    l
                    for l in limits
                    if l.get("type") in glm_provider.QUOTA_TYPES
                ]
                if quota_limits:
                    used_values = [
                        clamp_percent(limit.get("percentage"))
                        for limit in quota_limits
                    ]
                    used_values = [value for value in used_values if value is not None]
                    if used_values:
                        remaining = 100 - max(used_values)
                        bits.append(f"GLM {remaining:.0f}%")
                        all_remaining.append(remaining)

        if self.last_results.get("ark"):
            ark = self.last_results["ark"]
            if "error" not in ark:
                quotas = ark.get("quotas", [])
                # Title shows the session (5-hour) quota only
                session_quotas = [
                    q for q in quotas if q.get("level") in ("session", "5h")
                ]
                target_quotas = session_quotas or quotas
                used_values = [clamp_percent(q.get("percent")) for q in target_quotas]
                used_values = [value for value in used_values if value is not None]
                if used_values:
                    remaining = 100 - max(used_values)
                    bits.append(f"ARK {remaining:.0f}%")
                    all_remaining.append(remaining)

        worst = min(all_remaining, default=None)
        color = color_for_remaining(worst)

        title = " · ".join(bits) if bits else "AI⚡"
        return title, color

    def refresh_all(self):
        """Fetch usage from all enabled providers in a background thread."""
        with self._refresh_lock:
            if self._refresh_in_progress:
                return
            self._refresh_in_progress = True

        self.title = "刷新中..."
        thread = threading.Thread(target=self._do_refresh, daemon=True)
        thread.start()

    def _do_refresh(self):
        """Background worker: fetch data, then update UI on main thread."""
        try:
            self.cfg = load_config()
            results = {}
            issues = []

            # --- Codex ---
            if self.cfg["codex"]["enabled"]:
                try:
                    data = codex_provider.get_usage()
                    if data:
                        results["codex"] = data
                    else:
                        issues.append("Codex: 暂无会话数据")
                except Exception as e:
                    issues.append(f"Codex: {e}")

            # --- GLM ---
            if self.cfg["glm"]["enabled"]:
                try:
                    api_key = secret_store.resolve_glm_api_key(
                        self.cfg, save_config
                    )
                    if api_key:
                        data = glm_provider.get_usage(
                            api_key, self.cfg["glm"]["base_url"]
                        )
                        results["glm"] = data
                    else:
                        issues.append("GLM: API Key 未设置")
                except Exception as e:
                    issues.append(f"GLM: {e}")

            # --- Ark ---
            if self.cfg["ark"]["enabled"]:
                try:
                    data = None
                    try:
                        data = ark_provider.get_usage_via_arkcli()
                    except Exception as arkcli_err:
                        # arkcli exists but failed; fall back to Cookie below
                        ark_fallback_reason = str(arkcli_err)
                    else:
                        ark_fallback_reason = None
                    if data:
                        results["ark"] = data
                    else:
                        cookie, web_id = secret_store.resolve_ark_credentials(
                            self.cfg, save_config
                        )
                        if cookie:
                            results["ark"] = ark_provider.get_usage(cookie, web_id)
                            if ark_fallback_reason:
                                results["ark"]["warning"] = ark_fallback_reason
                        elif ark_fallback_reason:
                            issues.append(f"ARK: {ark_fallback_reason}")
                        else:
                            issues.append(
                                "ARK: Cookie 未设置（或安装 arkcli 并运行 "
                                "arkcli auth login）"
                            )
                except Exception as e:
                    issues.append(f"ARK: {e}")

            self.last_results = results
            self.last_refresh = datetime.now()
            self.issues = issues
            with self._refresh_lock:
                self._refresh_ready = True
        except Exception as exc:
            # Never leave the UI permanently in "刷新中..." if config loading
            # or an unexpected provider error escapes the provider-level guards.
            self.issues = [f"刷新失败: {exc}"]
            with self._refresh_lock:
                self._refresh_ready = True
        finally:
            with self._refresh_lock:
                self._refresh_in_progress = False

    def _poll_refresh(self, timer):
        """Main-run-loop callback that applies completed worker results."""
        with self._refresh_lock:
            if not self._refresh_ready:
                return
            self._refresh_ready = False
        self._update_menu()

    def _update_menu(self):
        """Rebuild the dropdown menu."""
        self.menu.clear()

        # --- Status line ---
        if self.last_refresh:
            time_str = self.last_refresh.strftime("%H:%M:%S")
            self.menu.add(rumps.MenuItem(f"最后刷新: {time_str}", callback=_noop_callback))
        self.menu.add(rumps.separator)

        # --- Codex section ---
        if self.cfg["codex"]["enabled"]:
            self.menu.add(rumps.MenuItem("Codex (OpenAI)", callback=_noop_callback))
            cx = self.last_results.get("codex")
            if cx and "error" not in cx:
                rows = codex_provider.format_usage(cx)
                if rows:
                    for label, pct, resets in rows:
                        used = clamp_percent(pct)
                        if used is None:
                            continue
                        remaining = 100 - used
                        bar = make_bar(remaining)
                        reset_str = human_reset(resets)
                        line = f"  {pad_label(label)} {bar} 剩余{remaining:.0f}%"
                        if reset_str:
                            line += f" · {reset_str}"
                        item = rumps.MenuItem(line, callback=_noop_callback)
                        self.menu.add(item)
                    plan = cx.get("plan_type", "")
                    if plan:
                        self.menu.add(
                            rumps.MenuItem(f"  套餐: {plan}", callback=_noop_callback)
                        )
                    self.menu.add(
                        rumps.MenuItem(
                            f"  {codex_provider.format_credits(cx)}",
                            callback=_noop_callback,
                        )
                    )
                    source = "服务端实时" if cx.get("source") == "live" else "本地快照"
                    self.menu.add(
                        rumps.MenuItem(f"  数据源: {source}", callback=_noop_callback)
                    )
                    if cx.get("warning"):
                        self.menu.add(
                            rumps.MenuItem(f"  ⚠ {cx['warning']}", callback=_noop_callback)
                        )
                else:
                    self.menu.add(rumps.MenuItem("  暂无数据", callback=_noop_callback))
            else:
                err = cx.get("error", "未知错误") if cx else "暂无数据"
                self.menu.add(rumps.MenuItem(f"  ⚠ {err}", callback=_noop_callback))
            self.menu.add(rumps.separator)

        # --- GLM section ---
        if self.cfg["glm"]["enabled"]:
            self.menu.add(rumps.MenuItem("GLM (智谱)", callback=_noop_callback))
            glm = self.last_results.get("glm")
            if glm and "error" not in glm:
                rows = glm_provider.format_usage(glm)
                if rows:
                    for label, pct, resets in rows:
                        used = clamp_percent(pct)
                        if used is None:
                            continue
                        remaining = 100 - used
                        bar = make_bar(remaining)
                        reset_str = human_reset(resets)
                        line = f"  {pad_label(label)} {bar} 剩余{remaining:.0f}%"
                        if reset_str:
                            line += f" · {reset_str}"
                        self.menu.add(rumps.MenuItem(line, callback=_noop_callback))
                    level = glm.get("level", "")
                    if level:
                        self.menu.add(
                            rumps.MenuItem(f"  套餐: {level}", callback=_noop_callback)
                        )
                else:
                    self.menu.add(rumps.MenuItem("  暂无数据", callback=_noop_callback))
            else:
                err = glm.get("error", "未知错误") if glm else "暂无数据"
                self.menu.add(rumps.MenuItem(f"  ⚠ {err}", callback=_noop_callback))
            self.menu.add(rumps.separator)

        # --- Ark section ---
        if self.cfg["ark"]["enabled"]:
            self.menu.add(rumps.MenuItem("ARK (火山方舟)", callback=_noop_callback))
            ark = self.last_results.get("ark")
            if ark and "error" not in ark:
                rows = ark_provider.format_usage(ark)
                if rows:
                    for label, pct, resets in rows:
                        used = clamp_percent(pct)
                        if used is None:
                            continue
                        remaining = 100 - used
                        bar = make_bar(remaining)
                        reset_str = human_reset(resets)
                        line = f"  {pad_label(label)} {bar} 剩余{remaining:.0f}%"
                        if reset_str:
                            line += f" · {reset_str}"
                        self.menu.add(rumps.MenuItem(line, callback=_noop_callback))
                    source = (
                        "arkcli (官方)"
                        if ark.get("source") == "arkcli"
                        else "控制台 Cookie"
                    )
                    self.menu.add(
                        rumps.MenuItem(
                            f"  数据源: {source}", callback=_noop_callback
                        )
                    )
                    if ark.get("warning"):
                        self.menu.add(
                            rumps.MenuItem(
                                f"  ⚠ {ark['warning']}", callback=_noop_callback
                            )
                        )
                else:
                    self.menu.add(rumps.MenuItem("  暂无数据", callback=_noop_callback))
            else:
                err = ark.get("error", "未知错误") if ark else "暂无数据"
                self.menu.add(rumps.MenuItem(f"  ⚠ {err}", callback=_noop_callback))
            self.menu.add(rumps.separator)

        # --- Issues ---
        issues = getattr(self, "issues", [])
        if issues:
            self.menu.add(rumps.MenuItem("⚠ 注意事项", callback=_noop_callback))
            for issue in issues:
                self.menu.add(rumps.MenuItem(f"  {issue}", callback=_noop_callback))
            self.menu.add(rumps.separator)

        # --- Actions ---
        self.menu.add(self.refresh_item)
        self.menu.add(self.config_item)
        self.menu.add(self.about_item)

        # --- Update title ---
        title, _color = self.compute_title()
        self.title = title

    # --- Callbacks ---

    def _on_refresh(self, sender):
        """Manual refresh."""
        self.refresh_all()

    def _on_edit_config(self, sender):
        """Open config file in default editor."""
        # Ensure config exists
        if not CONFIG_FILE.exists():
            save_config(load_config())
        subprocess.Popen(["open", str(CONFIG_FILE)])
        rumps.notification(
            "AI Usage Monitor",
            "配置文件已打开",
            "修改后请点击'立即刷新'",
        )

    def _on_about(self, sender):
        rumps.alert(
            "AI Usage Monitor",
            "监控 OpenAI Codex / GLM / 火山方舟 Coding Plan 用量\n\n"
            f"配置文件: {CONFIG_FILE}\n"
            "每 5 分钟自动刷新\n\n"
            "MIT License",
        )


if __name__ == "__main__":
    app = AIUsageMonitor()

    # Timer for auto-refresh
    interval = app.cfg.get("refresh_interval", REFRESH_INTERVAL_DEFAULT)

    def on_tick(timer):
        app.refresh_all()

    timer = rumps.Timer(on_tick, interval)
    # This timer is created and started on the Cocoa main run loop. The
    # worker thread only sets _refresh_ready; it never creates an NSTimer.
    ui_timer = rumps.Timer(app._poll_refresh, 0.1)

    # Initial refresh first, then begin the 5-minute schedule.
    app.refresh_all()
    timer.start()
    ui_timer.start()

    # Clean up PID file on quit
    _pid_file = Path.home() / ".config" / "ai-usage-monitor" / "app.pid"

    def _cleanup_pid():
        try:
            _pid_file.unlink(missing_ok=True)
        except OSError:
            pass

    # rumps replaces quit_button's callback during initializeStatusBar(), so
    # register cleanup on the framework's actual before-quit event instead.
    rumps.events.before_quit.register(_cleanup_pid)

    app.run()
