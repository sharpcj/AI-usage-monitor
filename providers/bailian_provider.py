"""Aliyun Bailian personal Token Plan usage (console session, not API key)."""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone, timedelta
from typing import Any

import requests

CONSOLE_URL = (
    "https://bailian.console.aliyun.com/cn-beijing/subscription/token-plan/personal"
)
API_NAME = "zeldaHttp.apikeyMgr./tokenplan/personal/api/v2/usage"
GATEWAY_URL = "https://bailian-cs.console.aliyun.com/data/api.json"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36"
)
WINDOWS = (
    ("per5Hour", "session", "小时限额"),
    ("per1Week", "weekly", "每周限额"),
    ("per1Month", "monthly", "月度限额"),
)


def _reset_timestamp(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        epoch = float(value)
    except (ValueError, TypeError):
        try:
            stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=timezone(timedelta(hours=8)))
            return stamp.timestamp()
        except (ValueError, TypeError, OverflowError):
            return None
    if not math.isfinite(epoch) or epoch <= 0:
        return None
    return epoch / 1000 if epoch > 1e12 else epoch


def _failure(data):
    """Return safe diagnostics, never raw response text (may contain secrets)."""
    code = str(data.get("errorCode") or data.get("ErrorCode") or data.get("code") or "")
    if "Login" in code or "Token" in code or code == "ConsoleNeedLogin":
        return {"error": "百炼登录态已失效，请重新运行 update_bailian_creds.py"}
    if "NoPermission" in code or "NotAuthorised" in code:
        return {"error": "百炼账号无权查询个人 Token Plan，请检查账号权限"}
    return {"error": "百炼用量查询失败，请检查订阅、登录态或控制台接口是否变更"}


def parse_usage(payload) -> dict[str, Any]:
    """Unwrap the console V2 gateway and convert usage ratios to used percent.

    The public console fetcher reads data.DataV2.data, checks success, then
    returns its data. Percentage fields are ratios (0.25 means 25% USED).
    Missing fields are unknown, never interpreted as zero usage.
    """
    if not isinstance(payload, dict):
        return {"error": "百炼响应格式异常"}
    node = payload
    # Support both wire gateway response and the fetcher's unwrapped result.
    for _ in range(6):
        if not isinstance(node, dict):
            return {"error": "百炼响应格式异常"}
        if node.get("success") is False or node.get("successResponse") is False:
            return _failure(node)
        if node.get("errorCode") or node.get("ErrorCode"):
            return _failure(node)
        if any(prefix + "Percentage" in node for prefix, _, _ in WINDOWS):
            break
        if "DataV2" in node:
            node = node["DataV2"]
        elif "data" in node:
            node = node["data"]
        else:
            return _failure(node)
    if not isinstance(node, dict):
        return {"error": "百炼响应格式异常"}
    quotas = []
    for prefix, level, _ in WINDOWS:
        value = node.get(prefix + "Percentage")
        if value is None:
            continue
        if isinstance(value, bool):
            return {"error": "百炼额度比例格式异常"}
        try:
            ratio = float(value)
        except (ValueError, TypeError):
            return {"error": "百炼额度比例格式异常"}
        if not math.isfinite(ratio) or ratio < 0:
            return {"error": "百炼额度比例格式异常"}
        quotas.append({
            "level": level,
            "percent": min(ratio * 100, 100.0),
            "reset_timestamp": _reset_timestamp(node.get(prefix + "ResetTime")),
        })
    if not quotas:
        return {"error": "未找到百炼个人 Token Plan 用量，请确认已订阅或更新登录态"}
    return {"quotas": quotas, "source": "cookie"}


def get_usage(cookie, sec_token=""):
    if not cookie or not cookie.strip():
        return {"error": "百炼登录态未设置，请运行 update_bailian_creds.py"}
    body = {
        "params": json.dumps({
            "Api": API_NAME,
            "V": "1.0",
            "Data": {"cornerstoneParam": {
                "feURL": CONSOLE_URL,
                "protocol": "V2",
                "console": "ONE_CONSOLE",
                "productCode": "p_efm",
                "switchUserType": 3,
                "domain": "bailian.console.aliyun.com",
                "consoleSite": "BAILIAN_ALIYUN",
                "xsp_lang": "zh-CN",
            }},
        }),
        "region": "cn-beijing",
    }
    if sec_token:
        body["sec_token"] = sec_token
    try:
        response = requests.post(
            GATEWAY_URL,
            params={"action": "BroadScopeAspnGateway", "product": "sfm_bailian", "api": API_NAME, "_v": ""},
            data=body,
            headers={
                "Cookie": cookie,
                "Accept": "application/json, text/plain, */*",
                "Content-Type": "application/x-www-form-urlencoded",
                "Origin": "https://bailian.console.aliyun.com",
                "Referer": CONSOLE_URL,
                "User-Agent": USER_AGENT,
            },
            timeout=15,
            allow_redirects=False,
        )
        if response.status_code in (301, 302, 303, 307, 308, 401, 403):
            return {"error": "百炼登录态失效或访问被拒绝，请重新获取控制台 cURL"}
        if response.status_code >= 400:
            return {"error": f"百炼接口错误: HTTP {response.status_code}"}
        return parse_usage(response.json())
    except requests.RequestException:
        return {"error": "百炼网络请求失败，请检查网络后重试"}
    except (ValueError, TypeError):
        return {"error": "百炼响应不是有效 JSON，可能需要重新登录或完成安全验证"}


def format_usage(data) -> list[tuple[str, float, Any]]:
    if not data or "error" in data:
        return []
    labels = {level: label for _, level, label in WINDOWS}
    return [
        (str(labels.get(q["level"], q["level"])), float(q["percent"]), q.get("reset_timestamp"))
        for q in data.get("quotas", [])
    ]
