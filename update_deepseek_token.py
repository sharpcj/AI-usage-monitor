"""Store the DeepSeek open-platform session token used for spend queries.

The public API only exposes balance; daily spend lives behind the console
endpoint `platform.deepseek.com/api/v0/usage/cost`, which accepts a BROWSER
session token (never an API key).

Get the token:
  1. Log in at https://platform.deepseek.com
  2. DevTools -> Console, run:
       JSON.parse(localStorage.getItem('userToken')).value
  3. Copy the printed string, then run (clipboard mode):
       ./update-deepseek-token.sh
     or pipe it:
       pbpaste | ./update-deepseek-token.sh

A pasted `Authorization: Bearer ...` header or a full cURL command is also
accepted; the token is extracted from it.
"""

import json
import re
import shutil
import subprocess
import sys
from datetime import date

from providers import deepseek_provider
from secret_store import (
    load_deepseek_api_key,
    load_deepseek_platform_token,
    save_deepseek_platform_token,
)


def get_clipboard_tool():
    """Return a callable that reads the clipboard text, or None."""
    if shutil.which("pbpaste"):
        return lambda: subprocess.run(
            ["pbpaste"], capture_output=True, text=True, timeout=5
        )
    if shutil.which("wl-paste"):
        return lambda: subprocess.run(
            ["wl-paste", "--no-newline"], capture_output=True, text=True, timeout=5
        )
    if shutil.which("xclip"):
        return lambda: subprocess.run(
            ["xclip", "-selection", "clipboard", "-o"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    if shutil.which("xsel"):
        return lambda: subprocess.run(
            ["xsel", "--clipboard", "--output"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    return None


def clear_clipboard():
    """Overwrite the clipboard so the token does not linger."""
    clearers = {
        "pbcopy": ["pbcopy"],
        "wl-copy": ["wl-copy", "--clipboard"],
        "xclip": ["xclip", "-selection", "clipboard"],
        "xsel": ["xsel", "--clipboard", "--input"],
    }
    for name, cmd in clearers.items():
        if shutil.which(name):
            try:
                subprocess.run(
                    cmd,
                    input="",
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    text=True,
                    timeout=5,
                )
            except Exception:
                pass
            return


def read_input():
    """Read the token (or cURL/Auth header) from stdin or the clipboard."""
    if not sys.stdin.isatty():
        return sys.stdin.read().strip()

    read_clip = get_clipboard_tool()
    if read_clip is None:
        print("ERROR: no clipboard tool found.")
        print("On Linux install one of: wl-clipboard (Wayland), xclip, or xsel.")
        print("Alternatively pipe the token via stdin:")
        print("  echo '<token>' | ./update-deepseek-token.sh")
        sys.exit(1)

    try:
        clip = read_clip()
        if clip.returncode == 0 and clip.stdout.strip():
            clear_clipboard()
            return clip.stdout.strip()
    except Exception:
        pass

    print("ERROR: clipboard is empty.")
    print("Copy the token first (see the header of this script), then rerun.")
    sys.exit(1)


def extract_token(raw):
    """Accept a bare token, an `Authorization: Bearer x` header, or a cURL.

    Also tolerates the whole localStorage JSON ({"value": "..."}) that the
    Application panel shows, which is the most common copy mistake.
    """
    text = raw.strip().strip("'\"").strip()

    if text.startswith("{"):
        try:
            data = json.loads(text)
        except (json.JSONDecodeError, TypeError):
            pass
        else:
            if isinstance(data, dict):
                value = data.get("value") or data.get("token")
                if isinstance(value, str) and value.strip():
                    return value.strip().strip("'\"")

    match = re.search(r"(?:authorization:\s*)?bearer\s+([A-Za-z0-9._\-]+)", text, re.I)
    if match:
        return match.group(1)
    # A bare JWT/session token: dot-separated segments or a long blob.
    if re.fullmatch(r"[A-Za-z0-9._\-]+", text):
        return text
    return ""


def main():
    raw = read_input()
    if not raw:
        print("ERROR: 没有收到输入")
        return 1

    token = extract_token(raw)
    if not token:
        print("ERROR: 无法从输入中识别出平台 Token")
        print("  期望: 直接粘贴 token 字符串，或 `Authorization: Bearer ...` 头，或完整 cURL")
        return 1

    print(f"token_len={len(token)}")

    today = date.today()
    try:
        days = deepseek_provider._fetch_month_cost(token, today.year, today.month)
    except deepseek_provider.PlatformTokenExpired as e:
        print(f"verify=FAIL error={e}")
        return 1
    except RuntimeError as e:
        print(f"verify=FAIL error={e}")
        return 1

    save_deepseek_platform_token(token)
    print("saved_to_keychain=True")

    # Read back through the same path the app uses.
    stored = load_deepseek_platform_token()
    print(f"readback_ok={stored == token}")

    try:
        spend = deepseek_provider.get_daily_cost(stored or token, window_days=7)
    except RuntimeError as e:
        print(f"verify=FAIL error={e}")
        return 1

    print(f"today={spend['today']:.4f} last7={spend['last7']:.4f} days={len(spend['days'])}")
    if not load_deepseek_api_key():
        print("提示: 还未配置 API Key（余额显示需要）。可在 config.json 的")
        print("      deepseek.api_key 填入一次，首次刷新会自动迁移到系统凭据存储。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
