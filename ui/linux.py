"""Linux backend: AyatanaAppIndicator + PyGObject.

Requires system packages (apt):
    sudo apt install python3-gi gir1.2-ayatanaappindicator3-0.1 \
                     gir1.2-gtk-3.0 gir1.2-notify-0.7

Thread model: refresh runs in worker threads; UI updates are marshalled
back to the GLib main loop via GLib.idle_add.
"""

import gi

gi.require_version("AyatanaAppIndicator3", "0.1")
gi.require_version("Gtk", "3.0")
gi.require_version("Notify", "0.7")
from gi.repository import AyatanaAppIndicator3 as AppInd  # noqa: E402
from gi.repository import GLib, Gtk, Notify  # noqa: E402

import core  # noqa: E402
from core import UsageMonitor  # noqa: E402

INDICATOR_ID = "ai-usage-monitor"
ICON_NAME = "utilities-system-monitor"
FALLBACK_TITLE = "AI⚡"


class LinuxBackend:
    def __init__(self):
        self.monitor = UsageMonitor()
        self.indicator = None
        self.menu = None

    # --- refresh flow ---

    def refresh(self):
        self.monitor.refresh_async(
            on_done=lambda: GLib.idle_add(self._apply)
        )

    def _apply(self):
        """Main-thread callback: update label and rebuild the menu."""
        title, _color = self.monitor.compute_title()
        self._set_label(title)
        self._rebuild_menu(self.monitor.build_menu())
        return False  # one-shot idle source

    def _set_label(self, text):
        label = text or FALLBACK_TITLE
        try:
            self.indicator.set_label(label, label)
        except Exception:
            # Desktop environments without AppIndicator label support
            # (e.g. minimal GNOME without the extension) still show the menu.
            pass

    # --- menu ---

    def _rebuild_menu(self, items):
        new_menu = Gtk.Menu()
        for item in items:
            if isinstance(item, core.MenuSeparator):
                new_menu.append(Gtk.SeparatorMenuItem())
                continue
            mi = Gtk.MenuItem(label=item.text)
            if item.action:
                mi.connect("activate", self._on_action, item.action)
            else:
                mi.set_sensitive(False)  # display-only row
            new_menu.append(mi)
        new_menu.show_all()
        self.indicator.set_menu(new_menu)
        if self.menu:
            self.menu.destroy()
        self.menu = new_menu

    def _on_action(self, widget, action):
        if action == "refresh":
            self.refresh()
        elif action == "config":
            self._edit_config()
        elif action == "about":
            self._about()

    def _edit_config(self):
        if not core.CONFIG_FILE.exists():
            from config import load_config, save_config

            save_config(load_config())
        core.open_path(core.CONFIG_FILE)
        Notify.Notification.new(
            "AI Usage Monitor", "配置文件已打开，修改后请点击'立即刷新'", None
        ).show()

    def _about(self):
        dialog = Gtk.MessageDialog(
            modal=True,
            message_type=Gtk.MessageType.INFO,
            buttons=Gtk.ButtonsType.OK,
            text="AI Usage Monitor",
            secondary_text=(
                "监控 OpenAI Codex / GLM / 火山方舟 Coding Plan 用量\n\n"
                f"配置文件: {core.CONFIG_FILE}\n"
                "每 5 分钟自动刷新\n\n"
                "MIT License"
            ),
        )
        dialog.run()
        dialog.destroy()

    def _on_quit(self, widget):
        Gtk.main_quit()

    # --- entry point ---

    def run(self):
        Notify.init(INDICATOR_ID)
        self.indicator = AppInd.Indicator.new(
            INDICATOR_ID,
            ICON_NAME,
            AppInd.IndicatorCategory.APPLICATION_STATUS,
        )
        self.indicator.set_status(AppInd.IndicatorStatus.ACTIVE)
        self._set_label(FALLBACK_TITLE)
        self.menu = Gtk.Menu()
        self.indicator.set_menu(self.menu)

        interval = self.monitor.cfg.get(
            "refresh_interval", core.REFRESH_INTERVAL_DEFAULT
        )

        quit_item = Gtk.MenuItem(label="退出")
        quit_item.connect("activate", self._on_quit)
        quit_item.show()
        self.menu.append(quit_item)

        GLib.timeout_add_seconds(interval, self._tick)
        GLib.idle_add(self.refresh)
        Gtk.main()

    def _tick(self):
        self.refresh()
        return True  # keep repeating


def run():
    LinuxBackend().run()
