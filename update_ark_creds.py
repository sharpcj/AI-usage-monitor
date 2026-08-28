"""Update Ark credentials in Keychain from a cURL command.

Input sources, in priority order:
1. Piped stdin (recommended):   cat curl.txt | ./update-ark.sh
                               ./update-ark.sh <<'EOF' ... EOF
2. Clipboard (interactive):    copy the cURL in the browser (Copy as cURL),
                               then just run ./update-ark.sh — the script
                               reads it from the clipboard via pbpaste.
                               No pasting, no Enter, no Ctrl+D needed.
"""
import shlex
import subprocess
import sys

from secret_store import save_ark_credentials, load_ark_credentials
from providers.ark_provider import get_usage


def clear_clipboard():
    """Overwrite the clipboard so the copied cURL (with Cookie) doesn't linger."""
    try:
        subprocess.run(
            ["pbcopy"],
            input="",
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=5,
        )
    except Exception:
        pass


def read_curl_command():
    """Read the cURL command from stdin, or from the clipboard if interactive."""
    if not sys.stdin.isatty():
        return sys.stdin.read().strip()

    # Interactive: try clipboard first
    try:
        clip = subprocess.run(
            ["pbpaste"], capture_output=True, text=True, timeout=5
        )
        if clip.returncode == 0 and clip.stdout.strip():
            clear_clipboard()
            return clip.stdout.strip()
    except Exception:
        pass

    print("ERROR: clipboard is empty.")
    print("First copy the cURL command in the browser (DevTools -> Copy as cURL),")
    print("then run this script again.")
    sys.exit(1)


CURL_CMD = read_curl_command()

if not CURL_CMD:
    print("ERROR: no input received")
    sys.exit(1)

try:
    tokens = shlex.split(CURL_CMD)
except ValueError as e:
    print(f"ERROR: 无法解析输入的 cURL 命令（可能剪贴板内容不完整）: {e}")
    sys.exit(1)
cookie = None
web_id = None
for i, t in enumerate(tokens):
    if t in ("-b", "--cookie") and i + 1 < len(tokens):
        cookie = tokens[i + 1]
    if t.startswith("x-web-id:"):
        web_id = t.split(":", 1)[1].strip()

if not cookie or not web_id:
    print("ERROR: could not extract cookie or x-web-id from the cURL command")
    print(f"  cookie found: {bool(cookie)}")
    print(f"  web_id found: {bool(web_id)}")
    sys.exit(1)

print(f"cookie_len={len(cookie)} web_id_len={len(web_id)}")
save_ark_credentials(cookie, web_id)
print("saved_to_keychain=True")

cookie2, web_id2 = load_ark_credentials()
result = get_usage(cookie2, web_id2)
if "error" in result:
    print(f'verify=FAIL error={result["error"]}')
else:
    print(f'verify=OK quota_count={len(result.get("quotas", []))}')
    for q in result.get("quotas", []):
        print(f'  {q["level"]}: {q["percent"]}%')
