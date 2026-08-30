#!/usr/bin/env python3
"""Cross-platform bootstrap launcher.

Creates the virtualenv if missing, verifies dependencies (installing
them only when absent), then starts the app with the correct backend.

Usage:
    python3 start.py          (macOS / Linux)
    python start.py           (Windows, or double-click start.bat)
"""

import os
import shutil
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


def _uv_venv():
    """Create the venv with uv (ships its own pip; robust on systems that
    lack python3-venv/ensurepip). Pinned to the current interpreter so apt's
    PyGObject (system site-packages, Linux) stays visible."""
    cmd = ["uv", "venv", "--python", sys.executable]
    if sys.platform.startswith("linux"):
        cmd.append("--system-site-packages")
    subprocess.run([*cmd, str(VENV_DIR)], check=True)


def ensure_venv():
    if venv_python().exists():
        return
    print("首次运行：创建虚拟环境 .venv ...")
    if sys.platform.startswith("linux") and shutil.which("uv"):
        # Prefer uv on Linux: many distros (e.g. Ubuntu without python3-venv)
        # create a venv with no pip at all, and uv pins the system python so
        # apt-installed PyGObject remains importable.
        _uv_venv()
        return
    venv.create(
        VENV_DIR,
        with_pip=True,
        system_site_packages=sys.platform.startswith("linux"),
    )
    # venv.create() can succeed while pip is still missing (no ensurepip).
    if shutil.which("uv") and run_venv(code="import pip").returncode != 0:
        print("标准 venv 缺少 pip（系统未装 python3-venv），改用 uv 重建 ...")
        shutil.rmtree(VENV_DIR, ignore_errors=True)
        _uv_venv()


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
    uv = shutil.which("uv")
    if uv and run_venv(code="import pip").returncode != 0:
        # venv 里没有 pip 模块，用 uv 自带的 pip 安装。
        result = subprocess.run(
            [
                uv, "pip", "install", "-q",
                "--python", str(venv_python()),
                "-r", str(REQUIREMENTS),
            ]
        )
        pip_hint = f"  uv pip install --python {venv_python()} -r {REQUIREMENTS}"
    else:
        result = run_venv(
            args=["-m", "pip", "install", "-q", "-r", str(REQUIREMENTS)]
        )
        pip_hint = f"  {venv_python()} -m pip install -r {REQUIREMENTS}"
    if result.returncode != 0:
        sys.exit(f"依赖安装失败。请检查网络，或手动执行:\n{pip_hint}")


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
