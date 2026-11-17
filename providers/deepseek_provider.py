"""DeepSeek usage provider.

DeepSeek is pay-as-you-go (no subscription quota), so there is no
"remaining percentage". Two independent sources:

1. Balance - public API, API-KEY auth (official, stable):
       GET https://api.deepseek.com/user/balance
2. Daily spend - open-platform console internal API, BROWSER SESSION TOKEN
   auth, account-wide (covers every API key of the account):
       GET https://platform.deepseek.com/api/v0/usage/cost?month=&year=

The spend endpoint rejects API keys and answers HTTP 200 with
``{"code": 40003, "msg": "Authorization Failed (invalid token)"}`` when the
session token expired, so auth failures are detected in the body, not via
the HTTP status.
"""

from datetime import date, datetime, timedelta

import requests

BALANCE_URL = "https://api.deepseek.com/user/balance"
COST_URL = "https://platform.deepseek.com/api/v0/usage/cost"

# The console API sits behind a WAF: a bare curl/python UA is blocked (429),
# while the browser chrome below gets through.
PLATFORM_HEADERS = {
    "accept": "*/*",
    "x-app-version": "1.0.0",
    "user-agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/148.0.0.0 Safari/537.36"
    ),
}

AUTH_FAILED_CODE = 40003

# Completed months never change; caching them keeps the 5-minute refresh at
# one or two requests instead of re-reading history every tick.
_FROZEN_MONTHS = {}


class PlatformTokenExpired(RuntimeError):
    """The console session token is missing, invalid, or expired."""


# --- helpers ---

def _to_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _sum_cost(blocks):
    """Sum the monetary entries of one usage block (REQUEST carries counts)."""
    total = 0.0
    for block in blocks or []:
        for entry in block.get("usage") or []:
            if entry.get("type") == "REQUEST":
                continue
            total += _to_float(entry.get("amount"))
    return total


def _normalize_date(value, year):
    """Normalize a platform date ('2026-10-19' or '10-19') to ISO form."""
    if not isinstance(value, str) or not value:
        return None
    text = value.strip()
    if len(text) == 10:
        return text
    if len(text) == 5:  # MM-DD
        return f"{year}-{text}"
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date().isoformat()
    except (ValueError, TypeError):
        return None


# --- balance ---

def get_balance(api_key, timeout=10) -> dict:
    """Query account balance with an API key.

    Returns {"is_available": bool, "balances": [{"currency", "total",
    "granted", "topped_up"}, ...]} or {"error": message}.
    """
    headers = {"Accept": "application/json", "Authorization": f"Bearer {api_key}"}
    try:
        resp = requests.get(BALANCE_URL, headers=headers, timeout=timeout)
    except requests.RequestException as e:
        return {"error": f"网络错误: {e}"}
    if resp.status_code in (401, 403):
        return {"error": "API Key 无效"}
    if resp.status_code >= 400:
        return {"error": f"余额接口错误: HTTP {resp.status_code}"}
    try:
        data = resp.json()
    except ValueError as e:
        return {"error": f"解析错误: {e}"}

    infos = data.get("balance_infos") or []
    if not infos:
        return {"error": "未返回余额数据"}
    balances = [
        {
            "currency": info.get("currency", "CNY"),
            "total": _to_float(info.get("total_balance")),
            "granted": _to_float(info.get("granted_balance")),
            "topped_up": _to_float(info.get("topped_up_balance")),
        }
        for info in infos
    ]
    return {"is_available": bool(data.get("is_available")), "balances": balances}


# --- daily spend (console API) ---

def _fetch_month_cost(platform_token, year, month, timeout=15):
    """Return {ISO date: cost} for one month from the console API."""
    url = f"{COST_URL}?month={month}&year={year}"
    headers = {**PLATFORM_HEADERS, "authorization": f"Bearer {platform_token}"}
    try:
        resp = requests.get(url, headers=headers, timeout=timeout)
    except requests.RequestException as e:
        raise RuntimeError(f"网络错误: {e}") from e

    if resp.status_code == 429:
        raise RuntimeError("请求被平台限流，请稍后重试")
    if resp.status_code >= 400:
        raise RuntimeError(f"消费接口错误: HTTP {resp.status_code}")
    try:
        payload = resp.json()
    except ValueError as e:
        raise RuntimeError(f"解析错误: {e}") from e

    code = payload.get("code")
    if code == AUTH_FAILED_CODE:
        raise PlatformTokenExpired(
            "平台 Token 失效或已过期，请重新获取（运行 ./update-deepseek-token.sh）"
        )
    if code not in (0, None):
        raise RuntimeError(payload.get("msg") or f"消费接口返回 code={code}")

    biz = (payload.get("data") or {}).get("biz_data") or []
    if isinstance(biz, dict):  # tolerate a non-list shape
        biz = [biz]

    days = {}
    for block in biz:
        for day in block.get("days") or []:
            key = _normalize_date(day.get("date"), year)
            if not key:
                continue
            days[key] = days.get(key, 0.0) + _sum_cost(day.get("data"))
    return days


def _month_cost_cached(platform_token, year, month, timeout=15):
    today = date.today()
    frozen = (year, month) < (today.year, today.month)
    key = (year, month)
    if frozen and key in _FROZEN_MONTHS:
        return _FROZEN_MONTHS[key]
    days = _fetch_month_cost(platform_token, year, month, timeout=timeout)
    if frozen:
        _FROZEN_MONTHS[key] = days
    return days


def get_daily_cost(platform_token, window_days=7, today=None, timeout=15) -> dict:
    """Sum spend over the last `window_days` days (today inclusive).

    Returns {"today", "last7", "days": [{"date", "cost"}], "currency",
    "source"} or raises RuntimeError / PlatformTokenExpired.
    """
    if not platform_token:
        raise PlatformTokenExpired("平台 Token 未设置")
    today = today or date.today()
    start = today - timedelta(days=max(window_days, 1) - 1)

    per_day = {}
    seen = set()
    cursor = start
    while cursor <= today:
        key = (cursor.year, cursor.month)
        if key not in seen:
            seen.add(key)
            per_day.update(_month_cost_cached(platform_token, *key, timeout=timeout))
        cursor += timedelta(days=1)

    series = []
    cursor = start
    while cursor <= today:
        iso = cursor.isoformat()
        series.append({"date": iso, "cost": round(per_day.get(iso, 0.0), 4)})
        cursor += timedelta(days=1)

    return {
        "currency": "CNY",
        "today": series[-1]["cost"],
        "last7": round(sum(item["cost"] for item in series), 4),
        "days": series,
        "source": "platform",
    }


# --- aggregate ---

def get_usage(api_key="", platform_token="", window_days=7) -> dict:
    """Collect balance + spend. Balance and spend degrade independently."""
    result: dict = {
        "currency": "CNY",
        "balances": [],
        "days": [],
        "today": None,
        "last7": None,
    }
    issues = []

    if api_key:
        balance = get_balance(api_key)
        if "error" in balance:
            issues.append(balance["error"])
        else:
            result["balances"] = balance["balances"]
            result["is_available"] = balance.get("is_available", True)
            if balance["balances"]:
                result["currency"] = balance["balances"][0]["currency"]
    else:
        issues.append("API Key 未设置（仅显示消费，不显示余额）")

    if platform_token:
        try:
            spend = get_daily_cost(platform_token, window_days=window_days)
            result.update(
                {
                    key: spend[key]
                    for key in ("currency", "today", "last7", "days", "source")
                }
            )
        except RuntimeError as e:
            issues.append(str(e))
    else:
        issues.append("平台 Token 未设置（今日/近 7 天消费需要）")

    if not result["balances"] and result["today"] is None:
        result["error"] = "；".join(issues) or "暂无数据"
        return result
    if issues:
        result["warning"] = "；".join(issues)
    return result


# --- formatting ---

def format_money(value, currency="CNY", compact=False):
    """Format a CNY/USD amount; tiny amounts keep 4 decimals."""
    if value is None:
        return "-"
    symbol = {"CNY": "¥", "USD": "$"}.get(currency, "")
    if compact:
        text = f"{value:.4f}" if 0 < abs(value) < 0.01 else f"{value:.2f}"
    else:
        text = f"{value:.4f}" if 0 < abs(value) < 0.01 else f"{value:,.2f}"
    return f"{symbol}{text}"


def format_amount(value, currency="CNY"):
    """Compact amount for the tray title (no thousands separators)."""
    return format_money(value, currency, compact=True)


def format_usage(data):
    """Summary rows as (label, text) pairs for the menu."""
    if not data or "error" in data:
        return []
    rows = []
    currency = data.get("currency", "CNY")
    if data.get("today") is not None:
        rows.append(("今日消费", format_money(data["today"], currency)))
        rows.append(("近7天合计", format_money(data.get("last7"), currency)))
    balances = data.get("balances") or []
    if balances:
        primary = balances[0]
        rows.append(
            (
                "账户余额",
                format_money(primary.get("total"), primary.get("currency", currency)),
            )
        )
    return rows
