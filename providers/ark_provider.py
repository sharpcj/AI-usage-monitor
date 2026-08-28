"""Volcengine Ark Coding Plan usage provider.

Preferred path: official `arkcli` (npm @volcengine/ark-cli) via
`arkcli usage plan --format json`. Falls back to the internal console
API with browser Cookie credentials.
"""

import json
import shutil
import subprocess
from urllib.parse import unquote

import requests


ARK_API_URL = (
    "https://console.volcengine.com/api/top/ark/cn-beijing/2024-01-01/GetCodingPlanUsage"
)
CONSOLE_URL = (
    "https://console.volcengine.com/ark/region:ark+cn-beijing/openManagement"
    "?LLM=%7B%7D&advancedActiveKey=subscribe"
)


def _extract_csrf_token(cookie):
    """Extract and URL-decode csrfToken from a cookie string."""
    for part in cookie.split(";"):
        name, separator, value = part.strip().partition("=")
        if separator and name == "csrfToken":
            return unquote(value)
    return None


# --- Official arkcli path ---

def _normalize_reset_ts(value):
    """Normalize an arkcli reset_at epoch (s or ms) to seconds; None if unset."""
    if not isinstance(value, (int, float)) or value <= 0:
        return None
    return value / 1000 if value > 1e12 else value


def _parse_arkcli_output(raw):
    """Parse `arkcli usage plan --format json` output into the internal shape."""
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise RuntimeError("arkcli 输出不是有效 JSON")
    try:
        data = json.loads(raw[start:end + 1])
    except json.JSONDecodeError:
        raise RuntimeError("arkcli 输出解析失败")

    viewer = data.get("viewer") or {}
    if viewer.get("auth_method") == "none" or not viewer.get("auth_method"):
        raise RuntimeError("arkcli 未登录，请运行: arkcli auth login")

    items = data.get("items") or []
    coding = next(
        (
            i
            for i in items
            if str(i.get("product", "")).startswith("coding-plan")
            and i.get("subscribed")
        ),
        None,
    )
    if not coding:
        raise RuntimeError("arkcli: 未找到已订阅的 Coding Plan")

    quotas = []
    for period in coding.get("periods") or []:
        quotas.append({
            "level": period.get("label", ""),
            "percent": period.get("percent", 0),
            "reset_timestamp": _normalize_reset_ts(period.get("reset_at")),
        })
    if not quotas:
        raise RuntimeError("arkcli: Coding Plan 无用量数据")
    return {"quotas": quotas, "source": "arkcli"}


def get_usage_via_arkcli(timeout=20):
    """Query usage via the official arkcli.

    Returns None when arkcli is not installed; raises RuntimeError when it is
    installed but the query fails (not logged in, no subscription, ...).
    """
    if shutil.which("arkcli") is None:
        return None
    try:
        proc = subprocess.run(
            ["arkcli", "usage", "plan", "--format", "json"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError("arkcli 查询超时")
    except OSError as e:
        raise RuntimeError(f"arkcli 启动失败: {e}")
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip().splitlines()
        hint = detail[-1][:120] if detail else f"exit {proc.returncode}"
        raise RuntimeError(f"arkcli 查询失败: {hint}")
    return _parse_arkcli_output(proc.stdout)


def get_usage(cookie, web_id=""):
    """
    Query Volcengine Ark Coding Plan usage via internal console API.

    Args:
        cookie: Full cookie string from browser (must contain csrfToken)
        web_id: x-web-id header value from browser

    Returns dict:
      {
        "quotas": [
          {"level": "session"|"weekly"|"monthly"|"5h", "percent": float, "reset_timestamp": epoch},
          ...
        ],
        "source": "cookie",
      }
    or {"error": "message"} on failure.
    """
    csrf_token = _extract_csrf_token(cookie)
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
        "Origin": "https://console.volcengine.com",
        "Referer": CONSOLE_URL,
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36"
        ),
        "Cookie": cookie,
    }
    if csrf_token:
        headers["x-csrf-token"] = csrf_token
    if web_id:
        headers["x-web-id"] = web_id

    try:
        resp = requests.post(ARK_API_URL, headers=headers, json={}, timeout=10)
        if resp.status_code in (401, 403):
            return {"error": "Cookie 过期，请重新获取"}
        if resp.status_code >= 400:
            return {"error": f"火山方舟接口错误: HTTP {resp.status_code}"}
        data = resp.json()
    except requests.RequestException as e:
        return {"error": f"网络错误: {e}"}
    except (ValueError, KeyError) as e:
        return {"error": f"解析错误: {e}"}

    quota = data.get("Result", {}).get("QuotaUsage", [])
    if not quota:
        err_msg = (
            data.get("ResponseMetadata", {})
            .get("Error", {})
            .get("Message", "未找到用量数据")
        )
        return {"error": err_msg}

    quotas = []
    for q in quota:
        level = q.get("Level", "")
        percent = q.get("Percent", 0)
        reset_ts = q.get("ResetTimestamp")
        # ResetTimestamp may be a string ISO date or epoch
        if isinstance(reset_ts, str):
            try:
                from datetime import datetime
                reset_ts = datetime.fromisoformat(
                    reset_ts.replace("Z", "+00:00")
                ).timestamp()
            except (ValueError, TypeError):
                reset_ts = None
        quotas.append({
            "level": level,
            "percent": percent,
            "reset_timestamp": reset_ts,
        })

    return {"quotas": quotas, "source": "cookie"}


LEVEL_LABELS = {
    "session": "小时限额",
    "5h": "小时限额",
    "weekly": "每周限额",
    "monthly": "月度限额",
}


def format_usage(data):
    """
    Format Ark usage data for display.
    Returns list of (label, percent, resets_at_or_None) tuples.
    """
    if not data or "error" in data:
        return []

    quotas = data.get("quotas", [])
    rows = []
    for q in quotas:
        label = LEVEL_LABELS.get(q["level"], q["level"])
        rows.append((label, q["percent"], q.get("reset_timestamp")))
    return rows
