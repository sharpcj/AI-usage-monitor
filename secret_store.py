"""Store provider credentials in the system secret store.

Uses the `keyring` library, which picks the native backend per platform:
macOS Keychain, Windows Credential Manager, Linux Secret Service.
"""

import getpass
import json

import keyring

ARK_SERVICE = "ai-usage-monitor.ark"
GLM_SERVICE = "ai-usage-monitor.glm"
DEEPSEEK_SERVICE = "ai-usage-monitor.deepseek"
DEEPSEEK_PLATFORM_SERVICE = "ai-usage-monitor.deepseek-platform"
BAILIAN_SERVICE = "ai-usage-monitor.bailian"
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


# --- Bailian ---

def save_bailian_credentials(cookie, sec_token=""):
    _set(BAILIAN_SERVICE, json.dumps(
        {"cookie": cookie, "sec_token": sec_token}, separators=(",", ":")
    ))


def load_bailian_credentials():
    try:
        data = json.loads(_get(BAILIAN_SERVICE) or "{}")
        if not isinstance(data, dict):
            return "", ""
        return str(data.get("cookie") or ""), str(data.get("sec_token") or "")
    except (ValueError, TypeError):
        return "", ""


def resolve_bailian_credentials(cfg, save_config_callback):
    bailian = cfg.get("bailian") or {}
    cookie = str(bailian.get("cookie") or "")
    sec_token = str(bailian.get("sec_token") or "")
    if cookie:
        save_bailian_credentials(cookie, sec_token)
        bailian["cookie"] = ""
        bailian["sec_token"] = ""
        cfg["bailian"] = bailian
        save_config_callback(cfg)
        return cookie, sec_token
    return load_bailian_credentials()


# --- DeepSeek ---

def save_deepseek_api_key(api_key):
    _set(DEEPSEEK_SERVICE, api_key)


def load_deepseek_api_key():
    return _get(DEEPSEEK_SERVICE) or ""


def save_deepseek_platform_token(token):
    _set(DEEPSEEK_PLATFORM_SERVICE, token)


def load_deepseek_platform_token():
    return _get(DEEPSEEK_PLATFORM_SERVICE) or ""


def resolve_deepseek_credentials(cfg, save_config_callback):
    """Migrate legacy plaintext values, then return (api_key, platform_token)."""
    deepseek = cfg.get("deepseek") or {}
    api_key = str(deepseek.get("api_key", ""))
    platform_token = str(deepseek.get("platform_token", ""))
    if api_key or platform_token:
        if api_key:
            save_deepseek_api_key(api_key)
            deepseek["api_key"] = ""
        if platform_token:
            save_deepseek_platform_token(platform_token)
            deepseek["platform_token"] = ""
        cfg["deepseek"] = deepseek
        save_config_callback(cfg)
    return load_deepseek_api_key(), load_deepseek_platform_token()
