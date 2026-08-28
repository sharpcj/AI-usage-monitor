"""Platform-independent business logic for AI Usage Monitor.

UI backends (ui/macos.py, ui/windows.py, ui/linux.py) render the state
exposed here; this module must not import any GUI toolkit.
"""

import os
import subprocess
import sys
import threading
import time
from datetime import datetime

from config import load_config, save_config, CONFIG_FILE
import secret_store
from providers import codex_provider, glm_provider, ark_provider

REFRESH_INTERVAL_DEFAULT = 300  # 5 minutes


# --- formatting helpers ---

def human_reset(resets_at):
    """Format reset timestamp to human-readable countdown."""
    if not resets_at:
        return ""
    # resets_at could be epoch (int/float) or ISO string
    if isinstance(resets_at, (int, float)):
        epoch = resets_at
    elif isinstance(resets_at, str):
        try:
            epoch = datetime.fromisoformat(
                resets_at.replace("Z", "+00:00")
            ).timestamp()
        except (ValueError, TypeError):
            return ""
    else:
        return ""

    mins = int((epoch - time.time()) / 60)
    if mins <= 0:
        return "已重置"
    d, h, m = mins // 1440, (mins % 1440) // 60, mins % 60
    if d:
        return f"{d}天{h}小时"
    if h:
        return f"{h}小时{m:02d}分"
    return f"{m}分钟"


def color_for_remaining(remaining_pct):
    """Return hex color string based on remaining percentage."""
    if remaining_pct is None:
        return "#8e8e93"
    if remaining_pct <= 15:
        return "#ff453a"  # red
    if remaining_pct <= 40:
        return "#ff9f0a"  # orange
    return "#30d158"  # green


def clamp_percent(value):
    """Convert a percentage to float and clamp it to 0..100."""
    try:
        return max(0.0, min(100.0, float(value)))
    except (TypeError, ValueError):
        return None


def make_bar(remaining_pct, width=12):
    """Make a text progress bar showing remaining portion."""
    remaining_pct = clamp_percent(remaining_pct)
    if remaining_pct is None:
        return "-" * width
    filled = int(round(remaining_pct / 100 * width))
    return "█" * filled + "░" * (width - filled)


def pad_label(label, width=4):
    """Pad a label with full-width spaces so progress bars align.

    Chinese chars count as one unit; we pad to `width` CJK chars using
    full-width spaces (U+3000), which keep alignment in menu bars.
    """
    label = str(label)
    current = sum(1 for ch in label if ord(ch) > 0x2E80) + sum(
        1 for ch in label if ord(ch) <= 0x2E80 and ch != " "
    )
    pad = max(0, width - current)
    return label + "\u3000" * pad


def open_path(path):
    """Open a file/URL with the platform default application."""
    if sys.platform == "win32":
        os.startfile(str(path))  # noqa: S606 (Windows API)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


# --- menu model (rendered by each UI backend) ---

class MenuItem:
    """One menu row. action=None means display-only (no callback)."""

    def __init__(self, text, action=None):
        self.text = text
        self.action = action  # None | "refresh" | "config" | "about"


class MenuSeparator:
    pass


class UsageMonitor:
    """Aggregates provider results; completely UI-agnostic."""

    def __init__(self):
        self.cfg = load_config()
        self.last_results = {}
        self.last_refresh = None
        self.issues = []
        self._refresh_lock = threading.Lock()
        self._refresh_in_progress = False

    # --- refresh ---

    def refresh_async(self, on_done=None):
        """Start a background refresh; on_done() runs in the worker thread."""
        with self._refresh_lock:
            if self._refresh_in_progress:
                return
            self._refresh_in_progress = True

        def worker():
            try:
                self._do_refresh()
            finally:
                with self._refresh_lock:
                    self._refresh_in_progress = False
            if on_done:
                try:
                    on_done()
                except Exception:
                    pass

        threading.Thread(target=worker, daemon=True).start()

    def _do_refresh(self):
        """Fetch usage from all enabled providers."""
        try:
            self.cfg = load_config()
            results = {}
            issues = []

            # --- Codex ---
            if self.cfg["codex"]["enabled"]:
                try:
                    data = codex_provider.get_usage()
                    if data:
                        results["codex"] = data
                    else:
                        issues.append("Codex: 暂无会话数据")
                except Exception as e:
                    issues.append(f"Codex: {e}")

            # --- GLM ---
            if self.cfg["glm"]["enabled"]:
                try:
                    api_key = secret_store.resolve_glm_api_key(
                        self.cfg, save_config
                    )
                    if api_key:
                        data = glm_provider.get_usage(
                            api_key, self.cfg["glm"]["base_url"]
                        )
                        results["glm"] = data
                    else:
                        issues.append("GLM: API Key 未设置")
                except Exception as e:
                    issues.append(f"GLM: {e}")

            # --- Ark ---
            if self.cfg["ark"]["enabled"]:
                try:
                    data = None
                    try:
                        data = ark_provider.get_usage_via_arkcli()
                    except Exception as arkcli_err:
                        # arkcli exists but failed; fall back to Cookie below
                        ark_fallback_reason = str(arkcli_err)
                    else:
                        ark_fallback_reason = None
                    if data:
                        results["ark"] = data
                    else:
                        cookie, web_id = secret_store.resolve_ark_credentials(
                            self.cfg, save_config
                        )
                        if cookie:
                            results["ark"] = ark_provider.get_usage(cookie, web_id)
                            if ark_fallback_reason:
                                results["ark"]["warning"] = ark_fallback_reason
                        elif ark_fallback_reason:
                            issues.append(f"ARK: {ark_fallback_reason}")
                        else:
                            issues.append(
                                "ARK: Cookie 未设置（或安装 arkcli 并运行 "
                                "arkcli auth login）"
                            )
                except Exception as e:
                    issues.append(f"ARK: {e}")

            self.last_results = results
            self.last_refresh = datetime.now()
            self.issues = issues
        except Exception as exc:
            # Never leave the UI stuck if config loading or an unexpected
            # provider error escapes the provider-level guards.
            self.issues = [f"刷新失败: {exc}"]

    # --- title ---

    def compute_title(self):
        """Build the tray title from latest results (showing remaining %)."""
        bits = []
        all_remaining = []

        if self.last_results.get("codex"):
            cx = self.last_results["codex"]
            if "error" not in cx:
                # Title shows the 5-hour quota when available
                windows = [cx.get("primary"), cx.get("secondary")]
                windows = [w for w in windows if w]
                five_hour = [
                    w for w in windows if w.get("label") == "小时限额"
                ]
                target = five_hour or windows
                used_values = [
                    clamp_percent(w.get("used_percent")) for w in target
                ]
                used_values = [v for v in used_values if v is not None]
                if used_values:
                    remaining = 100 - max(used_values)
                    bits.append(f"CX {remaining:.0f}%")
                    all_remaining.append(remaining)

        if self.last_results.get("glm"):
            glm = self.last_results["glm"]
            if "error" not in glm:
                limits = glm.get("limits", [])
                quota_limits = [
                    l
                    for l in limits
                    if l.get("type") in glm_provider.QUOTA_TYPES
                ]
                if quota_limits:
                    used_values = [
                        clamp_percent(limit.get("percentage"))
                        for limit in quota_limits
                    ]
                    used_values = [value for value in used_values if value is not None]
                    if used_values:
                        remaining = 100 - max(used_values)
                        bits.append(f"GLM {remaining:.0f}%")
                        all_remaining.append(remaining)

        if self.last_results.get("ark"):
            ark = self.last_results["ark"]
            if "error" not in ark:
                quotas = ark.get("quotas", [])
                # Title shows the session (5-hour) quota only
                session_quotas = [
                    q for q in quotas if q.get("level") in ("session", "5h")
                ]
                target_quotas = session_quotas or quotas
                used_values = [clamp_percent(q.get("percent")) for q in target_quotas]
                used_values = [value for value in used_values if value is not None]
                if used_values:
                    remaining = 100 - max(used_values)
                    bits.append(f"ARK {remaining:.0f}%")
                    all_remaining.append(remaining)

        worst = min(all_remaining, default=None)
        color = color_for_remaining(worst)

        title = " · ".join(bits) if bits else "AI⚡"
        return title, color

    # --- menu model ---

    def build_menu(self):
        """Build the platform-neutral dropdown menu model."""
        items = []

        if self.last_refresh:
            time_str = self.last_refresh.strftime("%H:%M:%S")
            items.append(MenuItem(f"最后刷新: {time_str}"))
        items.append(MenuSeparator())

        items.extend(self._codex_section())
        items.extend(self._glm_section())
        items.extend(self._ark_section())

        if self.issues:
            items.append(MenuItem("⚠ 注意事项"))
            for issue in self.issues:
                items.append(MenuItem(f"  {issue}"))
            items.append(MenuSeparator())

        items.append(MenuItem("立即刷新", "refresh"))
        items.append(MenuItem("编辑配置", "config"))
        items.append(MenuItem("关于", "about"))
        return items

    def _usage_rows(self, rows):
        """Render (label, used_pct, resets) rows as display-only items."""
        out = []
        for label, pct, resets in rows:
            used = clamp_percent(pct)
            if used is None:
                continue
            remaining = 100 - used
            bar = make_bar(remaining)
            reset_str = human_reset(resets)
            line = f"  {pad_label(label)} {bar} 剩余{remaining:.0f}%"
            if reset_str:
                line += f" · {reset_str}"
            out.append(MenuItem(line))
        return out

    def _codex_section(self):
        if not self.cfg["codex"]["enabled"]:
            return []
        items = [MenuItem("Codex (OpenAI)")]
        cx = self.last_results.get("codex")
        if cx and "error" not in cx:
            rows = codex_provider.format_usage(cx)
            if rows:
                items.extend(self._usage_rows(rows))
                plan = cx.get("plan_type", "")
                if plan:
                    items.append(MenuItem(f"  套餐: {plan}"))
                items.append(MenuItem(f"  {codex_provider.format_credits(cx)}"))
                source = "服务端实时" if cx.get("source") == "live" else "本地快照"
                items.append(MenuItem(f"  数据源: {source}"))
                if cx.get("warning"):
                    items.append(MenuItem(f"  ⚠ {cx['warning']}"))
            else:
                items.append(MenuItem("  暂无数据"))
        else:
            err = cx.get("error", "未知错误") if cx else "暂无数据"
            items.append(MenuItem(f"  ⚠ {err}"))
        items.append(MenuSeparator())
        return items

    def _glm_section(self):
        if not self.cfg["glm"]["enabled"]:
            return []
        items = [MenuItem("GLM (智谱)")]
        glm = self.last_results.get("glm")
        if glm and "error" not in glm:
            rows = glm_provider.format_usage(glm)
            if rows:
                items.extend(self._usage_rows(rows))
                level = glm.get("level", "")
                if level:
                    items.append(MenuItem(f"  套餐: {level}"))
            else:
                items.append(MenuItem("  暂无数据"))
        else:
            err = glm.get("error", "未知错误") if glm else "暂无数据"
            items.append(MenuItem(f"  ⚠ {err}"))
        items.append(MenuSeparator())
        return items

    def _ark_section(self):
        if not self.cfg["ark"]["enabled"]:
            return []
        items = [MenuItem("ARK (火山方舟)")]
        ark = self.last_results.get("ark")
        if ark and "error" not in ark:
            rows = ark_provider.format_usage(ark)
            if rows:
                items.extend(self._usage_rows(rows))
                source = (
                    "arkcli (官方)"
                    if ark.get("source") == "arkcli"
                    else "控制台 Cookie"
                )
                items.append(MenuItem(f"  数据源: {source}"))
                if ark.get("warning"):
                    items.append(MenuItem(f"  ⚠ {ark['warning']}"))
            else:
                items.append(MenuItem("  暂无数据"))
        else:
            err = ark.get("error", "未知错误") if ark else "暂无数据"
            items.append(MenuItem(f"  ⚠ {err}"))
        items.append(MenuSeparator())
        return items
