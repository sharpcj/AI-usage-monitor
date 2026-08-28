"""Store provider credentials in the user's macOS Keychain."""

import getpass
import json
import subprocess

ARK_SERVICE = "ai-usage-monitor.ark"
GLM_SERVICE = "ai-usage-monitor.glm"
ACCOUNT = getpass.getuser()


def _keychain_add(service, secret):
    """Write a secret to the Keychain, passing it via stdin (not argv).

    `security` re-asks when `-w` has no value, so the secret is supplied
    twice on stdin and never appears in the process argument list.
    """
    result = subprocess.run(
        [
            "security",
            "add-generic-password",
            "-U",
            "-a",
            ACCOUNT,
            "-s",
            service,
            "-w",
        ],
        input=f"{secret}\n{secret}\n",
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError("无法写入 macOS Keychain")


def _keychain_find(service):
    """Read a secret from the Keychain; returns None when absent."""
    result = subprocess.run(
        [
            "security",
            "find-generic-password",
            "-a",
            ACCOUNT,
            "-s",
            service,
            "-w",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
    )
    if result.returncode != 0:
        return None
    return result.stdout.strip()


# --- Ark ---

def save_ark_credentials(cookie, web_id):
    payload = json.dumps({"cookie": cookie, "web_id": web_id}, separators=(",", ":"))
    _keychain_add(ARK_SERVICE, payload)


def load_ark_credentials():
    payload = _keychain_find(ARK_SERVICE)
    if payload is None:
        return "", ""
    try:
        data = json.loads(payload)
    except (json.JSONDecodeError, TypeError):
        return "", ""
    return str(data.get("cookie", "")), str(data.get("web_id", ""))


def resolve_ark_credentials(cfg, save_config_callback):
    """Migrate legacy plaintext credentials, then return Keychain credentials."""
    ark = cfg.get("ark") or {}
    cookie = str(ark.get("cookie", ""))
    web_id = str(ark.get("web_id", ""))
    if cookie:
        save_ark_credentials(cookie, web_id)
        ark["cookie"] = ""
        ark["web_id"] = ""
        cfg["ark"] = ark
        save_config_callback(cfg)
        return cookie, web_id
    return load_ark_credentials()


# --- GLM ---

def save_glm_api_key(api_key):
    _keychain_add(GLM_SERVICE, api_key)


def load_glm_api_key():
    return _keychain_find(GLM_SERVICE) or ""


def resolve_glm_api_key(cfg, save_config_callback):
    """Migrate a legacy plaintext API key, then return the Keychain key."""
    glm = cfg.get("glm") or {}
    api_key = str(glm.get("api_key", ""))
    if api_key:
        save_glm_api_key(api_key)
        glm["api_key"] = ""
        cfg["glm"] = glm
        save_config_callback(cfg)
        return api_key
    return load_glm_api_key()
