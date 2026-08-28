"""Windows backend: pystray tray icon + tkinter flyout panel.

Thread model:
- pystray runs detached on a background thread (tray icon + menus).
- tkinter runs on the main thread (root.mainloop()).
- Cross-thread UI updates go through a queue drained by an `after` pump.
"""

import ctypes
import queue
import threading
import tkinter as tk
from tkinter import ttk

import pystray
from PIL import Image, ImageDraw

import core
from core import UsageMonitor

ICON_SIZE = 32

SECTIONS = (
    ("Codex (OpenAI)", "codex", "codex_provider"),
    ("GLM (智谱)", "glm", "glm_provider"),
    ("ARK (火山方舟)", "ark", "ark_provider"),
)


def _cursor_pos():
    class POINT(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

    pt = POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y


class FlyoutPanel:
    """Borderless always-on-top window shown next to the tray icon."""

    WIDTH = 360

    def __init__(self, root, monitor, on_refresh):
        self.root = root
        self.monitor = monitor
        self.on_refresh = on_refresh
        self.win = None

    @property
    def visible(self):
        return self.win is not None

    def show(self):
        self.close()
        win = self.win = tk.Toplevel(self.root)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.title("AI Usage Monitor")
        x, y = _cursor_pos()
        # Pop up above-left of the cursor (tray icons sit at the taskbar).
        px = max(8, x - self.WIDTH - 24)
        py = max(8, y - 420)
        win.geometry(f"{self.WIDTH}x420+{px}+{py}")
        win.bind("<Escape>", lambda e: self.close())
        win.bind("<FocusOut>", lambda e: self.close())
        self.render()
        win.focus_set()

    def close(self, *_):
        if self.win is not None:
            win, self.win = self.win, None
            win.destroy()

    def render(self):
        """(Re)draw panel contents from monitor.last_results."""
        if self.win is None:
            return
        for child in self.win.winfo_children():
            child.destroy()

        m = self.monitor
        if m.last_refresh:
            ttk.Label(
                self.win,
                text=f"最后刷新: {m.last_refresh.strftime('%H:%M:%S')}",
                foreground="#555555",
            ).pack(anchor="w", padx=12, pady=(10, 4))

        for title, key, provider_name in SECTIONS:
            data = m.last_results.get(key)
            if data is None or "error" in data:
                continue
            provider = getattr(core, provider_name)
            self._section(title, provider.format_usage(data), data)

        if m.issues:
            ttk.Label(self.win, text="⚠ 注意事项", foreground="#ff9f0a").pack(
                anchor="w", padx=12, pady=(8, 2)
            )
            for issue in m.issues:
                ttk.Label(
                    self.win,
                    text=issue,
                    foreground="#a03000",
                    wraplength=330,
                ).pack(anchor="w", padx=24)

        btns = tk.Frame(self.win)
        btns.pack(side="bottom", fill="x", padx=12, pady=10)
        ttk.Button(btns, text="立即刷新", command=self._refresh).pack(side="right")

    def _section(self, title, rows, data):
        ttk.Label(self.win, text=title, font=("", 11, "bold")).pack(
            anchor="w", padx=12, pady=(8, 2)
        )
        for label, pct, resets in rows:
            used = core.clamp_percent(pct)
            if used is None:
                continue
            remaining = 100 - used
            reset_str = core.human_reset(resets)
            row = tk.Frame(self.win)
            row.pack(fill="x", padx=12)
            ttk.Label(row, text=label, width=10, anchor="w").pack(side="left")
            bar = ttk.Progressbar(
                row, length=140, maximum=100, value=remaining
            )
            bar.pack(side="left", padx=6)
            text = f"剩余{remaining:.0f}%"
            if reset_str:
                text += f" · {reset_str}"
            color = core.color_for_remaining(remaining)
            ttk.Label(row, text=text, foreground=color).pack(side="left")
        meta = []
        if title.startswith("Codex"):
            plan = data.get("plan_type", "")
            if plan:
                meta.append(f"套餐: {plan}")
            meta.append(core.codex_provider.format_credits(data))
            meta.append(
                "服务端实时" if data.get("source") == "live" else "本地快照"
            )
        elif title.startswith("GLM"):
            level = data.get("level", "")
            if level:
                meta.append(f"套餐: {level}")
        elif title.startswith("ARK"):
            meta.append(
                "arkcli (官方)" if data.get("source") == "arkcli" else "控制台 Cookie"
            )
        if meta:
            ttk.Label(
                self.win, text="  ·  ".join(meta), foreground="#555555"
            ).pack(anchor="w", padx=12)

    def _refresh(self):
        self.on_refresh()


class WindowsBackend:
    def __init__(self):
        self.monitor = UsageMonitor()
        self.root = None
        self.icon = None
        self.panel = None
        self._q = queue.Queue()

    # --- icon ---

    def _icon_image(self, color):
        img = Image.new("RGBA", (ICON_SIZE, ICON_SIZE), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        d.ellipse((2, 2, ICON_SIZE - 2, ICON_SIZE - 2), fill=color)
        d.ellipse((8, 8, ICON_SIZE - 8, ICON_SIZE - 8), fill="white")
        d.polygon(
            [(18, 9), (12, 18), (16, 18), (14, 24), (21, 15), (17, 15)],
            fill=color,
        )  # lightning bolt
        return img

    # --- event loop plumbing ---

    def _pump(self):
        while True:
            try:
                fn = self._q.get_nowait()
            except queue.Empty:
                break
            try:
                fn()
            except Exception:
                pass
        if self.root:
            self.root.after(50, self._pump)

    def _dispatch(self, fn):
        """Schedule fn on the tkinter main thread."""
        self._q.put(fn)

    # --- refresh flow ---

    def refresh(self):
        self.monitor.refresh_async(on_done=self._apply)

    def _apply(self):
        """Worker-thread completion; marshal to the tk main thread."""
        self._dispatch(self._apply_in_main)

    def _apply_in_main(self):
        title, color = self.monitor.compute_title()
        if self.icon:
            self.icon.title = title or "AI Usage Monitor"
            self.icon.icon = self._icon_image(color)
        if self.panel and self.panel.visible:
            self.panel.render()

    # --- tray callbacks (pystray worker thread; marshal to main) ---

    def _open_panel(self, icon=None, item=None):
        self._dispatch(self.panel.show)

    def _on_refresh(self, icon=None, item=None):
        self.refresh()

    def _on_config(self, icon=None, item=None):
        if not core.CONFIG_FILE.exists():
            from config import load_config, save_config

            save_config(load_config())
        core.open_path(core.CONFIG_FILE)

    def _on_quit(self, icon=None, item=None):
        if self.icon:
            self.icon.stop()
        self._dispatch(self.root.quit)

    # --- entry point ---

    def run(self):
        import tkinter as tk

        self.root = tk.Tk()
        self.root.withdraw()
        self.panel = FlyoutPanel(self.root, self.monitor, self.refresh)

        title, color = self.monitor.compute_title()
        menu = pystray.Menu(
            pystray.MenuItem("打开详情", self._open_panel, default=True),
            pystray.MenuItem("立即刷新", self._on_refresh),
            pystray.MenuItem("编辑配置", self._on_config),
            pystray.MenuItem("退出", self._on_quit),
        )
        self.icon = pystray.Icon(
            "ai-usage-monitor",
            self._icon_image(color),
            title or "AI Usage Monitor",
            menu,
        )
        self.icon.run_detached()

        self.root.after(50, self._pump)

        interval = self.monitor.cfg.get(
            "refresh_interval", core.REFRESH_INTERVAL_DEFAULT
        )

        def tick():
            self.refresh()
            schedule()

        def schedule():
            t = threading.Timer(interval, tick)
            t.daemon = True
            t.start()

        self.refresh()
        schedule()

        self.root.mainloop()


def run():
    WindowsBackend().run()
