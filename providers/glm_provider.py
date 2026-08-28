"""GLM Coding Plan usage provider - calls official API."""

from datetime import datetime

import requests

# Coding plans expose quotas either as token limits (older pro plans) or
# credit limits (credit-based plans such as "lite").
QUOTA_TYPES = ("TOKENS_LIMIT", "CREDIT_LIMIT")


def _to_epoch(value):
    """Normalize a reset time (epoch ms, epoch s, or ISO string) to epoch s."""
    if isinstance(value, (int, float)):
        return value / 1000 if value > 1e12 else value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(
                value.replace("Z", "+00:00")
            ).timestamp()
        except (ValueError, TypeError):
            return None
    return None


def get_usage(api_key, base_url="https://open.bigmodel.cn"):
    """
    Query GLM coding plan usage via official API.

    Args:
        api_key: GLM API key (Bearer token)
        base_url: "https://open.bigmodel.cn" (domestic) or "https://api.z.ai" (international)

    Returns dict:
      {
        "limits": [
          {"type": "TIME_LIMIT", "percentage": int, "usage": int, "currentValue": int, "remaining": int},
          {"type": "TOKENS_LIMIT", "percentage": int, "nextResetTime": ...},
          ...
        ],
        "level": str (e.g. "pro"),
      }
    or {"error": "message"} on failure.
    """
    url = f"{base_url}/api/monitor/usage/quota/limit"
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        data = resp.json()
        if data.get("success") and data.get("data"):
            return data["data"]
        return {"error": data.get("msg", "查询失败")}
    except requests.RequestException as e:
        return {"error": f"网络错误: {e}"}
    except (ValueError, KeyError) as e:
        return {"error": f"解析错误: {e}"}


def format_usage(data):
    """
    Format GLM usage data for display.
    Returns list of (label, percent, resets_at_or_None) tuples.
    """
    if not data or "error" in data:
        return []

    limits = data.get("limits", [])
    level = data.get("level", "unknown")
    rows = []

    quota_limits = [l for l in limits if l.get("type") in QUOTA_TYPES]
    # Sort by reset time if available - shorter window first (5h before monthly)
    quota_limits.sort(key=lambda x: _to_epoch(x.get("nextResetTime")) or 0)

    for q in quota_limits:
        rows.append(("额度", q.get("percentage", 0), _to_epoch(q.get("nextResetTime"))))

    # If we have two quota windows, label them
    if len(rows) >= 2:
        rows[0] = ("小时限额", rows[0][1], rows[0][2])
        second = quota_limits[1]
        second_label = "月度限额" if second.get("unit") == 6 else "每周限额"
        rows[1] = (second_label, rows[1][1], rows[1][2])

    # MCP usage
    mcp = next((l for l in limits if l.get("type") == "TIME_LIMIT"), None)
    if mcp:
        mcp_pct = round(mcp.get("currentValue", 0) / max(mcp.get("usage", 1), 1) * 100)
        rows.append(("MCP每月", mcp_pct, None))

    return rows
