"""macOS backend: rumps menu bar app."""

import threading
from pathlib import Path

import rumps

import core
from core import UsageMonitor, load_config, CONFIG_FILE


def _noop_callback(sender):
    """Empty callback so menu items render as normal (not grayed out)."""
    pass


class AIUsageMonitor(rumps.App):
    def __init__(self):
        super().__init__(
            "AI⚡",
            icon=None,
            template=None,
            quit_button=rumps.MenuItem("退出"),
        )
        self.monitor = UsageMonitor()
        self._refresh_lock = threading.Lock()
        self._refresh_ready = False

        # Menu items
        self.refresh_item = rumps.MenuItem("立即刷新", callback=self._on_refresh)
        self.config_item = rumps.MenuItem("编辑配置", callback=self._on_edit_config)
        self.about_item = rumps.MenuItem("关于", callback=self._on_about)

    # --- compatibility properties (tests / external tooling) ---

    @property
    def cfg(self):
        return self.monitor.cfg

    @property
    def last_results(self):
        return self.monitor.last_results

    @last_results.setter
    def last_results(self, value):
        self.monitor.last_results = value

    def compute_title(self):
        return self.monitor.compute_title()

    def _do_refresh(self):
        self.monitor._do_refresh()

    # --- refresh flow ---

    def refresh_all(self):
        """Fetch usage from all enabled providers in a background thread."""
        self.title = "刷新中..."
        self.monitor.refresh_async(on_done=self._mark_ready)

    def _mark_ready(self):
        """Worker-thread completion flag; applied on the main run loop."""
        self._refresh_ready = True

    def _poll_refresh(self, timer):
        """Main-run-loop callback that applies completed worker results."""
        with self._refresh_lock:
            if not self._refresh_ready:
                return
            self._refresh_ready = False
        self._update_menu()

    def _update_menu(self):
        """Rebuild the dropdown menu from the core menu model."""
        self.menu.clear()
        for item in self.monitor.build_menu():
            if isinstance(item, core.MenuSeparator):
                self.menu.add(rumps.separator)
                continue
            callback = self._action_callback(item.action)
            self.menu.add(rumps.MenuItem(item.text, callback=callback))

        title, _color = self.monitor.compute_title()
        self.title = title

    def _action_callback(self, action):
        return {
            "refresh": self._on_refresh,
            "config": self._on_edit_config,
            "about": self._on_about,
        }.get(action, _noop_callback)

    # --- callbacks ---

    def _on_refresh(self, sender):
        self.refresh_all()

    def _on_edit_config(self, sender):
        """Open config file in default editor."""
        if not CONFIG_FILE.exists():
            from config import save_config

            save_config(load_config())
        core.open_path(CONFIG_FILE)
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


def run():
    app = AIUsageMonitor()

    interval = app.monitor.cfg.get("refresh_interval", core.REFRESH_INTERVAL_DEFAULT)

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
