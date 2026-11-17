"""Validate and store Bailian console credentials without executing a cURL.

Edge: 开发者工具 → 网络 → 筛选 /tokenplan/personal/api/v2/usage →
右键请求 → 复制 → 复制为 cURL (bash)。运行本文件，默认读取剪贴板。
Credentials must never be pasted into chat or passed as command arguments.
"""

import argparse
import shlex
import shutil
import subprocess
import sys
from urllib.parse import parse_qs, urlsplit

from providers import bailian_provider
from secret_store import load_bailian_credentials, save_bailian_credentials


def extract_credentials(raw):
    """Extract Cookie and sec_token from Edge's Copy as cURL (bash)."""
    try:
        parts = shlex.split(raw.replace("\\\n", " "))
    except ValueError:
        raise ValueError("cURL 格式不完整，请使用“复制为 cURL (bash)”")
    if not parts or parts[0] != "curl":
        raise ValueError("请复制用量请求的完整 cURL (bash)，不是页面地址或 API Key")
    cookie, body, urls = "", "", []
    index = 1
    while index < len(parts):
        part = parts[index]
        if part.startswith("https://"):
            urls.append(part)
        elif part in ("-H", "--header", "-b", "--cookie", "--data", "--data-raw", "--data-binary", "--data-urlencode", "-d", "--url"):
            index += 1
            if index >= len(parts):
                raise ValueError("cURL 参数缺失")
            value = parts[index]
            if part in ("-H", "--header"):
                name, sep, header = value.partition(":")
                if sep and name.lower() == "cookie":
                    cookie = header.strip()
            elif part in ("-b", "--cookie"):
                cookie = value
            elif part == "--url":
                urls.append(value)
            elif part == "--data-urlencode":
                # Avoid local file references and ambiguous multi-part bodies.
                raise ValueError("请使用浏览器原始“复制为 cURL (bash)”，不支持 --data-urlencode")
            else:
                body = value
        index += 1
    if not any(
        urlsplit(url).hostname == "bailian-cs.console.aliyun.com"
        and urlsplit(url).path == "/data/api.json"
        and parse_qs(urlsplit(url).query).get("api") == [bailian_provider.API_NAME]
        for url in urls
    ):
        raise ValueError("不是百炼个人 Token Plan 用量请求，请筛选 /tokenplan/personal/api/v2/usage")
    if not cookie or "=" not in cookie or "\n" in cookie or "\r" in cookie:
        raise ValueError("请求未包含有效 Cookie，请登录后重新复制完整 cURL")
    sec_token = parse_qs(body, keep_blank_values=True).get("sec_token", [""])[0]
    return cookie, sec_token


def read_clipboard():
    if sys.platform == "win32":
        command = ["powershell", "-NoProfile", "-Command", "Get-Clipboard -Raw"]
    else:
        command = next((cmd for cmd in (
            ["pbpaste"], ["wl-paste", "--no-newline"],
            ["xclip", "-selection", "clipboard", "-o"],
            ["xsel", "--clipboard", "--output"],
        ) if shutil.which(cmd[0])), None)
    if command is None:
        raise RuntimeError("未找到剪贴板工具，请安装 wl-clipboard/xclip，或通过 --stdin 传入")
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        raise RuntimeError("读取剪贴板失败")
    if result.returncode != 0 or not result.stdout.strip():
        raise RuntimeError("剪贴板为空或无法读取，请先复制完整 cURL")
    return result.stdout


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stdin", action="store_true", help="从标准输入读取，而不是剪贴板")
    args = parser.parse_args(argv)
    try:
        cookie, sec_token = extract_credentials(sys.stdin.read() if args.stdin else read_clipboard())
        usage = bailian_provider.get_usage(cookie, sec_token)
        if usage.get("error"):
            print(f"verify=FAIL {usage['error']}（未写入凭据存储）")
            return 1
        save_bailian_credentials(cookie, sec_token)
        stored = load_bailian_credentials()
        if stored != (cookie, sec_token):
            print("verify=FAIL 系统凭据存储回读不一致")
            return 1
        verified = bailian_provider.get_usage(*stored)
        if verified.get("error"):
            print(f"verify=FAIL {verified['error']}")
            return 1
        print("saved_to_keyring=True readback_ok=True verify=OK")
        for label, used, _ in bailian_provider.format_usage(verified):
            print(f"{label}: 剩余 {100 - used:.1f}%")
        print("点击托盘“立即刷新”；首次接入需重启程序。")
        return 0
    except (ValueError, RuntimeError) as exc:
        # These exceptions have static messages and never include input secrets.
        # Keyring exceptions may include backend details: don't print those.
        if isinstance(exc, ValueError):
            print(f"ERROR: {exc}")
        else:
            print("ERROR: 剪贴板读取或系统凭据存储失败，请检查本机权限和剪贴板工具")
        return 1


if __name__ == "__main__":
    sys.exit(main())
