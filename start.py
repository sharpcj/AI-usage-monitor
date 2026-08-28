#!/usr/bin/env python3
"""Cross-platform bootstrap launcher.

Creates the virtualenv if missing, verifies dependencies (installing
them only when absent), then starts the app with the correct backend.

Usage:
    python3 start.py          (macOS / Linux)
    python start.py           (Windows, or double-click start.bat)
"""

import os
import subprocess
import sys
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV_DIR = ROOT / ".venv"
REQUIREMENTS = ROOT / "requirements.txt"

# Import probe per platform; if it passes, skip pip entirely (offline-safe).
PROBES = {
    "darwin": "import rumps, requests, keyring",
    "win32": "import pystray, PIL, requests, keyring",
    "linux": "import requests, keyring",
}

LINUX_SYSTEM_PACKAGES = (
    "sudo apt install python3-gi gir1.2-ayatanaappindicator3-0.1 "
    "gir1.2-gtk-3.0 gir1.2-notify-0.7"
)


def venv_python():
    return VENV_DIR / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def ensure_venv():
    if venv_python().exists():
        return
    print("首次运行：创建虚拟环境 .venv ...")
    # On Linux we need system_site_packages so PyGObject (installed via apt)
    # is visible inside the venv; pip cannot build it reliably.
    venv.create(
        VENV_DIR,
        with_pip=True,
        system_site_packages=sys.platform.startswith("linux"),
    )


def run_venv(code=None, args=None, **kwargs):
    cmd = [str(venv_python()), *args] if args else [
        str(venv_python()), "-c", code
    ]
    return subprocess.run(cmd, **kwargs)


def deps_ok():
    probe = PROBES.get(sys.platform)
    if probe is None:
        sys.exit(f"不支持的平台: {sys.platform}")
    return run_venv(code=probe).returncode == 0


def ensure_deps():
    if deps_ok():
        return
    print("安装依赖 ...")
    result = run_venv(
        args=["-m", "pip", "install", "-q", "-r", str(REQUIREMENTS)]
    )
    if result.returncode != 0:
        sys.exit(
            "依赖安装失败。请检查网络，或手动执行:\n"
            f"  {venv_python()} -m pip install -r {REQUIREMENTS}"
        )


def check_linux_system_packages():
    if not sys.platform.startswith("linux"):
        return
    probe = (
        "import gi; "
        "gi.require_version('AyatanaAppIndicator3', '0.1'); "
        "gi.require_version('Gtk', '3.0'); "
        "gi.require_version('Notify', '0.7')"
    )
    if run_venv(code=probe).returncode != 0:
        sys.exit(
            "缺少 Linux 系统包（PyGObject / Ayatana AppIndicator）。\n"
            f"请先运行: {LINUX_SYSTEM_PACKAGES}"
        )


def main():
    ensure_venv()
    ensure_deps()
    check_linux_system_packages()
    print("启动 AI Usage Monitor ...")
    os.execv(
        str(venv_python()), [str(venv_python()), str(ROOT / "app.py")]
    )


if __name__ == "__main__":
    main()
