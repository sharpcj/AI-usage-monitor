#!/usr/bin/env python3
"""
AI Usage Monitor - cross-platform tray app.
Monitors Codex / GLM / Volcengine Ark coding plan quotas.

Usage:
    .venv/bin/python app.py

Backends:
    macOS   -> rumps menu bar app
    Windows -> pystray tray icon + tkinter flyout
    Linux   -> AyatanaAppIndicator + PyGObject

First-time setup: edit ~/.config/ai-usage-monitor/config.json
"""

import sys

# Shared, platform-neutral logic
from core import (  # noqa: F401 (re-exported for tests / tooling)
    UsageMonitor,
    clamp_percent,
    color_for_remaining,
    human_reset,
    make_bar,
    pad_label,
)

if sys.platform == "darwin":  # noqa: C901
    from ui.macos import AIUsageMonitor  # noqa: F401 (test compatibility)


def main():
    if sys.platform == "darwin":
        from ui.macos import run
    elif sys.platform == "win32":
        from ui.windows import run
    elif sys.platform.startswith("linux"):
        from ui.linux import run
    else:
        raise SystemExit(f"不支持的平台: {sys.platform}")
    run()


if __name__ == "__main__":
    main()
