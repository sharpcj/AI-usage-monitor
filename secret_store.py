"""Store provider credentials in the system secret store.

Uses the `keyring` library, which picks the native backend per platform:
macOS Keychain, Windows Credential Manager, Linux Secret Service.
"""

import getpass
import json

import keyring

ARK_SERVICE = "ai-usage-monitor.ark"
GLM_SERVICE = "ai-usage-monitor.glm"
ACCOUNT = getpass.getuser()


def _set(service, secret):
    try:
        keyring.set_password(service, ACCOUNT, secret)
    except Exception as e:
        raise RuntimeError(f"无法写入系统凭据存储: {e}") from e


def _get(service):
    try:
        return keyring.get_password(service, ACCOUNT)
    except Exception:
        return None


# --- Ark ---

def save_ark_credentials(cookie, web_id):
    payload = json.dumps({"cookie": cookie, "web_id": web_id}, separators=(",", ":"))
    _set(ARK_SERVICE, payload)


def load_ark_credentials():
    payload = _get(ARK_SERVICE)
    if not payload:
        return "", ""
    try:
        data = json.loads(payload)
    except (json.JSONDecodeError, TypeError):
        return "", ""
    return str(data.get("cookie", "")), str(data.get("web_id", ""))


def resolve_ark_credentials(cfg, save_config_callback):
    """Migrate legacy plaintext credentials, then return stored credentials."""
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
    _set(GLM_SERVICE, api_key)


def load_glm_api_key():
    return _get(GLM_SERVICE) or ""


def resolve_glm_api_key(cfg, save_config_callback):
    """Migrate a legacy plaintext API key, then return the stored key."""
    glm = cfg.get("glm") or {}
    api_key = str(glm.get("api_key", ""))
    if api_key:
        save_glm_api_key(api_key)
        glm["api_key"] = ""
        cfg["glm"] = glm
        save_config_callback(cfg)
        return api_key
    return load_glm_api_key()
