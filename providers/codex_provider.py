"""Codex usage provider - reads rate_limits from local rollout JSONL files."""

import glob
import json
import os
import select
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path


def _window_label(window_minutes):
    if window_minutes is None:
        return "限额"
    try:
        minutes = int(window_minutes)
    except (TypeError, ValueError):
        return "限额"
    if minutes >= 10080:
        return "每周限额"
    if minutes >= 300:
        return "小时限额"
    return "限额"


def _normalize_percent(value):
    try:
        return max(0.0, min(100.0, float(value)))
    except (TypeError, ValueError):
        return None


def _normalize_rate_limits(rate_limits, source="live"):
    """Normalize app-server camelCase quota data to the app's internal shape."""
    primary = rate_limits.get("primary") or {}
    secondary = rate_limits.get("secondary") or {}
    credits = rate_limits.get("credits") or {}

    return {
        "primary": {
            "used_percent": _normalize_percent(
                primary.get("usedPercent", primary.get("used_percent"))
            ),
            "resets_at": primary.get("resetsAt", primary.get("resets_at")),
            "label": _window_label(
                primary.get("windowDurationMins", primary.get("window_minutes"))
            ),
        },
        "secondary": {
            "used_percent": _normalize_percent(
                secondary.get("usedPercent", secondary.get("used_percent"))
            ),
            "resets_at": secondary.get("resetsAt", secondary.get("resets_at")),
            "label": _window_label(
                secondary.get("windowDurationMins", secondary.get("window_minutes"))
            ) if secondary else None,
        },
        "plan_type": rate_limits.get("planType", rate_limits.get("plan_type", "unknown")),
        "credits": {
            "has_credits": bool(
                credits.get("hasCredits", credits.get("has_credits", False))
            ),
            "unlimited": bool(credits.get("unlimited", False)),
            "balance": str(credits.get("balance", "0")),
        },
        "updated_at": datetime.now().astimezone().isoformat(),
        "source": source,
    }


def _find_codex_binary():
    """Find a Codex CLI that supports app-server."""
    candidates = []
    if os.environ.get("CODEX_BIN"):
        candidates.append(os.environ["CODEX_BIN"])

    path_bin = shutil.which("codex")
    if path_bin:
        candidates.append(path_bin)

    cache_patterns = [
        str(Path.home() / "Library/Caches/JetBrains/**/node_modules/@openai/"
            "codex-darwin-arm64/vendor/aarch64-apple-darwin/bin/codex"),
        str(Path.home() / "Library/Caches/Google/**/node_modules/@openai/"
            "codex-darwin-arm64/vendor/aarch64-apple-darwin/bin/codex"),
    ]
    for pattern in cache_patterns:
        matches = glob.glob(pattern, recursive=True)
        matches.sort(key=os.path.getmtime, reverse=True)
        candidates.extend(matches)

    for candidate in candidates:
        if candidate and os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            return candidate
    return None


def get_live_usage(codex_binary, timeout=15):
    """Fetch the current server-side quota via Codex app-server JSON-RPC."""
    proc = subprocess.Popen(
        [codex_binary, "app-server"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        bufsize=1,
    )
    request_id = 0

    def send(method, params=None, notification=False):
        nonlocal request_id
        payload = {"method": method, "params": params or {}}
        if not notification:
            request_id += 1
            payload["id"] = request_id
        proc.stdin.write(json.dumps(payload) + "\n")
        proc.stdin.flush()
        return None if notification else request_id

    def wait_for(target_id):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            remaining = deadline - time.monotonic()
            ready, _, _ = select.select([proc.stdout], [], [], remaining)
            if not ready:
                break
            line = proc.stdout.readline()
            if not line:
                break
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue
            if message.get("id") != target_id:
                continue
            if message.get("error"):
                raise RuntimeError(message["error"].get("message", "Codex RPC failed"))
            return message.get("result") or {}
        raise TimeoutError("Codex app-server 查询超时")

    try:
        init_id = send(
            "initialize",
            {
                "clientInfo": {
                    "name": "ai_usage_monitor",
                    "title": "AI Usage Monitor",
                    "version": "0.1.0",
                }
            },
        )
        wait_for(init_id)
        send("initialized", notification=True)
        quota_id = send("account/rateLimits/read")
        result = wait_for(quota_id)
        rate_limits = result.get("rateLimits")
        if not isinstance(rate_limits, dict):
            raise RuntimeError("Codex 未返回额度数据")
        return _normalize_rate_limits(rate_limits, source="live")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=3)
        for stream in (proc.stdin, proc.stdout):
            if stream:
                stream.close()


def _find_rate_limits(obj):
    """Recursively search for 'rate_limits' key in a nested dict/list."""
    if isinstance(obj, dict):
        rl = obj.get("rate_limits")
        if isinstance(rl, dict):
            return rl
        for v in obj.values():
            r = _find_rate_limits(v)
            if r:
                return r
    elif isinstance(obj, list):
        for v in obj:
            r = _find_rate_limits(v)
            if r:
                return r
    return None


def _get_local_usage():
    """
    Read the most recent rate_limits from Codex session rollout files.

    Returns dict:
      {
        "primary": {"used_percent": float, "resets_at": epoch_or_None, "label": "周额度"},
        "secondary": {"used_percent": float, "resets_at": epoch_or_None, "label": "5小时额度"},
        "plan_type": str,
        "credits": {...},
        "updated_at": str (timestamp of the log entry),
      }
    or None if no data found.
    """
    sessions_dir = os.path.join(os.path.expanduser("~"), ".codex", "sessions")
    pattern = os.path.join(sessions_dir, "*", "*", "*", "rollout-*.jsonl")
    files = glob.glob(pattern)
    if not files:
        # try without the extra level for older layouts
        pattern2 = os.path.join(sessions_dir, "*", "*", "rollout-*.jsonl")
        files = glob.glob(pattern2)
    if not files:
        return None

    files.sort(key=os.path.getmtime, reverse=True)

    for fpath in files[:10]:
        found = None
        found_ts = None
        try:
            with open(fpath, "r", errors="ignore") as fh:
                for line in fh:
                    if '"rate_limits"' not in line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    rl = _find_rate_limits(entry)
                    if rl:
                        found = rl
                        ts = entry.get("timestamp")
                        if ts:
                            found_ts = ts
        except (OSError, IOError):
            continue
        if found:
            primary = found.get("primary") or {}
            secondary = found.get("secondary") or {}

            # window_minutes 10080 = weekly, 300 = 5h
            pm = primary.get("window_minutes", 0)
            sm = secondary.get("window_minutes", 0) if secondary else 0

            # Determine which is weekly vs 5h based on window_minutes
            if pm >= 10080:
                primary_label = "每周限额"
            elif pm >= 300 and pm < 10080:
                primary_label = "小时限额"
            else:
                primary_label = "限额"

            if secondary:
                if sm >= 10080:
                    secondary_label = "每周限额"
                elif sm >= 300:
                    secondary_label = "小时限额"
                else:
                    secondary_label = "限额"
            else:
                secondary_label = None

            return {
                "primary": {
                    "used_percent": primary.get("used_percent"),
                    "resets_at": primary.get("resets_at"),
                    "label": primary_label,
                },
                "secondary": {
                    "used_percent": secondary.get("used_percent") if secondary else None,
                    "resets_at": secondary.get("resets_at") if secondary else None,
                    "label": secondary_label,
                },
                "plan_type": found.get("plan_type", "unknown"),
                "credits": found.get("credits", {}),
                "updated_at": found_ts,
                "source": "local",
            }

    return None


def get_usage():
    """Prefer a live app-server query; fall back to a clearly marked local snapshot."""
    codex_binary = _find_codex_binary()
    live_error = None
    if codex_binary:
        try:
            return get_live_usage(codex_binary)
        except Exception as exc:
            live_error = str(exc)
    else:
        live_error = "未找到 Codex CLI"

    local = _get_local_usage()
    if local:
        local["warning"] = f"实时查询失败，显示本地快照：{live_error}"
        return local
    return {"error": f"Codex 实时查询失败：{live_error}"}


def format_credits(data):
    credits = data.get("credits") or {}
    if credits.get("unlimited"):
        return "超额额度: 不限量"
    return f"超额额度: {credits.get('balance', '0')}"


def format_usage(data):
    """Format codex usage data for display. Returns list of (label, percent, resets_at) tuples."""
    if not data:
        return []
    rows = []
    p = data["primary"]
    if p["used_percent"] is not None:
        rows.append((p["label"], p["used_percent"], p["resets_at"]))
    s = data["secondary"]
    if s and s["used_percent"] is not None:
        rows.append((s["label"], s["used_percent"], s["resets_at"]))
    return rows
