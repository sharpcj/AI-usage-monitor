"""Configuration management for AI usage monitor."""

import copy
import json
import os
import tempfile
from pathlib import Path

CONFIG_DIR = Path.home() / ".config" / "ai-usage-monitor"
CONFIG_FILE = CONFIG_DIR / "config.json"

DEFAULT_CONFIG = {
    "refresh_interval": 300,  # seconds (5 minutes)
    "glm": {
        "enabled": True,
        "api_key": "",
        # "https://open.bigmodel.cn/api/monitor/usage/quota/limit" (domestic)
        # "https://api.z.ai/api/monitor/usage/quota/limit" (international)
        "base_url": "https://open.bigmodel.cn",
    },
    "ark": {
        "enabled": True,
        "cookie": "",
        "web_id": "",
    },
    "bailian": {
        "enabled": True,
        "cookie": "",
        "sec_token": "",
    },
    "deepseek": {
        "enabled": True,
        "api_key": "",
        # Open-platform console session token (NOT the API key): only this
        # can read account-wide daily spend. Run ./update-deepseek-token.sh.
        "platform_token": "",
    },
    "codex": {
        "enabled": True,
    },
}


def load_config():
    """Load config, persisting missing defaults without replacing user values."""
    if not CONFIG_FILE.exists():
        return copy.deepcopy(DEFAULT_CONFIG)
    try:
        saved = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        cfg = copy.deepcopy(DEFAULT_CONFIG)
        if not isinstance(saved, dict):
            return cfg
        updated = copy.deepcopy(saved)
        for key, default in DEFAULT_CONFIG.items():
            if key not in updated:
                updated[key] = copy.deepcopy(default)
            elif isinstance(default, dict) and isinstance(updated[key], dict):
                for field, value in default.items():
                    updated[key].setdefault(field, copy.deepcopy(value))
        for key in cfg:
            if key in saved:
                if isinstance(cfg[key], dict) and isinstance(saved[key], dict):
                    cfg[key] = {**cfg[key], **saved[key]}
                elif not isinstance(cfg[key], dict):
                    cfg[key] = saved[key]
        if updated != saved:
            try:
                save_config(updated)
            except OSError:
                # A read-only file must not discard valid user settings.
                pass
        return cfg
    except (json.JSONDecodeError, OSError):
        return copy.deepcopy(DEFAULT_CONFIG)


def save_config(cfg):
    """Atomically save config with owner-only permissions."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(CONFIG_DIR, 0o700)
    fd, temp_name = tempfile.mkstemp(prefix="config.", suffix=".tmp", dir=CONFIG_DIR)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(cfg, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp_name, 0o600)
        os.replace(temp_name, CONFIG_FILE)
        os.chmod(CONFIG_FILE, 0o600)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)
