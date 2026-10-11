"""Local settings: API keys, model choices and optional login state.

Values live only in ~/.video2doc/config.json on this computer. Environment
variables keep priority so scripted setups behave as before. Secrets are never
returned to the browser: the UI only receives "configured" plus a short mask.
"""
import json
import os
import re
import threading
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

from scripts.platform_utils import load_user_config, save_user_config, user_config_path

from .pipeline import DEFAULT_ENRICH_MODEL, WHISPER_MODELS, parse_hotwords


PROVIDERS = (
    {
        "id": "doubao",
        "label": "豆包语音（火山引擎）",
        "field": "doubao_api_key",
        "env": "DOUBAO_API_KEY",
        "get_key_url": "https://console.volcengine.com/speech/new/setting/apikeys",
        "docs_url": "https://www.volcengine.com/docs/6561/1354868",
        "uses": ["语音识别（云端首选）：豆包录音文件识别大模型 2.0（volc.seedasr.auc）"],
        "hint": "在火山引擎控制台创建 API Key，并开通“豆包录音文件识别 2.0”。",
    },
    {
        "id": "siliconflow",
        "label": "硅基流动 SiliconFlow",
        "field": "siliconflow_api_key",
        "env": "SILICONFLOW_API_KEY",
        "get_key_url": "https://cloud.siliconflow.cn/account/ak",
        "docs_url": "https://docs.siliconflow.cn/",
        "uses": ["语音识别（云端备选）：TeleSpeechASR（TeleAI/TeleSpeechASR）",
                 "AI 摘要 / 要点 / 标签：下方可选的对话模型"],
        "hint": "注册后在“API 密钥”页面新建，形如 sk-…。",
    },
)
SECRET_FIELDS = {
    "doubao_api_key": "DOUBAO_API_KEY",
    "siliconflow_api_key": "SILICONFLOW_API_KEY",
    "xhs_cookie": "XHS_COOKIE",
}
OPTION_FIELDS = {
    "enrich_model": {"env": "VIDEO2DOC_ENRICH_MODEL", "default": DEFAULT_ENRICH_MODEL},
    "whisper_model": {"env": "VIDEO2DOC_WHISPER_MODEL", "default": "turbo"},
    "whisper_language": {"env": "VIDEO2DOC_WHISPER_LANGUAGE", "default": "zh"},
    "cookies_file": {"env": "VIDEO2DOC_COOKIES_FILE", "default": ""},
    "douyin_storage_state": {"env": "VIDEO2DOC_DOUYIN_STORAGE_STATE", "default": ""},
    "auto_update_tools": {"env": None, "default": True},
    "hotwords": {"env": None, "default": ""},
}
ENRICH_MODEL_PRESETS = (
    "deepseek-ai/DeepSeek-V3",
    "deepseek-ai/DeepSeek-R1",
    "Qwen/Qwen3-32B",
    "Qwen/Qwen3-8B",
    "THUDM/GLM-4-9B-0414",
)
WHISPER_LANGUAGES = ("zh", "auto", "en", "ja", "ko", "yue", "fr", "de", "es", "ru")
_MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/:-]{0,127}$")
_SECRET_MAX = 4096


class SettingsError(ValueError):
    pass


def _mask(value):
    value = str(value)
    if len(value) < 12:
        return "已设置"
    return f"{value[:4]}…{value[-4:]}"


def secret_status(field):
    env_name = SECRET_FIELDS[field]
    env_value = os.environ.get(env_name, "") if env_name else ""
    stored = load_user_config().get(field, "")
    if env_value:
        return {"configured": True, "source": "env", "env": env_name, "preview": _mask(env_value)}
    if stored:
        return {"configured": True, "source": "config", "env": env_name, "preview": _mask(stored)}
    return {"configured": False, "source": "none", "env": env_name, "preview": ""}


def effective_secret(field):
    env_name = SECRET_FIELDS[field]
    return (os.environ.get(env_name, "") if env_name else "") or str(load_user_config().get(field, "") or "")


def public_settings():
    config = load_user_config()
    options = {}
    for field, spec in OPTION_FIELDS.items():
        env_value = os.environ.get(spec["env"], "") if spec["env"] else ""
        if env_value:
            value, source = env_value, "env"
        elif field in config:
            value, source = config[field], "config"
        else:
            value, source = spec["default"], "default"
        options[field] = {"value": value, "source": source, "env": spec["env"],
                          "default": spec["default"]}
    home = str(Path.home())
    path = str(user_config_path())
    return {
        "config_path": "~" + path[len(home):] if path.startswith(home) else path,
        "providers": [
            {key: provider[key] for key in ("id", "label", "get_key_url", "docs_url", "uses", "hint")}
            | {"field": provider["field"], **secret_status(provider["field"])}
            for provider in PROVIDERS
        ],
        "secrets": {"xhs_cookie": secret_status("xhs_cookie")},
        "options": options,
        "choices": {
            "enrich_model_presets": list(ENRICH_MODEL_PRESETS),
            "whisper_models": sorted(WHISPER_MODELS),
            "whisper_languages": list(WHISPER_LANGUAGES),
        },
    }


def _clean_secret(value):
    if not isinstance(value, str):
        raise SettingsError("Key 必须是字符串")
    value = value.strip()
    if len(value) > _SECRET_MAX or any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
        raise SettingsError("Key 格式无效")
    return value


def _clean_option(field, value):
    if field == "auto_update_tools":
        if not isinstance(value, bool):
            raise SettingsError("auto_update_tools 必须是布尔值")
        return value
    if not isinstance(value, str):
        raise SettingsError(f"{field} 必须是字符串")
    value = value.strip()
    if field == "enrich_model":
        if value and not _MODEL_RE.fullmatch(value):
            raise SettingsError("模型名称格式无效")
    elif field == "whisper_model":
        if value and value not in WHISPER_MODELS:
            raise SettingsError("Whisper 模型无效")
    elif field == "whisper_language":
        if value and value not in WHISPER_LANGUAGES:
            raise SettingsError("Whisper 语言无效")
    elif field == "hotwords":
        if len(value) > 4000:
            raise SettingsError("热词总长度不能超过 4000 字符")
        value = "，".join(parse_hotwords(value))
    elif field in {"cookies_file", "douyin_storage_state"}:
        if len(value) > 1024 or any(ord(ch) < 32 for ch in value):
            raise SettingsError("路径格式无效")
        if value and not Path(value).expanduser().is_file():
            raise SettingsError(f"文件不存在：{value}")
    return value


def update_settings(payload):
    """Validate and persist; empty strings remove a value (falls back to default)."""
    if not isinstance(payload, dict):
        raise SettingsError("请求体必须是对象")
    updates = {}
    for field, value in (payload.get("secrets") or {}).items():
        if field not in SECRET_FIELDS:
            raise SettingsError(f"未知 Key：{field}")
        updates[field] = _clean_secret(value) if value is not None else None
    for field, value in (payload.get("options") or {}).items():
        if field not in OPTION_FIELDS:
            raise SettingsError(f"未知设置：{field}")
        updates[field] = _clean_option(field, value) if value is not None else None
    if not updates:
        raise SettingsError("没有需要保存的内容")
    save_user_config(updates)
    _models_cache.clear()
    return public_settings()


def _request(url, *, headers, data=None, method="GET", timeout=15):
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.headers, response.read()
    except urllib.error.HTTPError as exc:
        body = exc.read()
        exc.close()
        return exc.code, exc.headers, body


def verify_key(provider_id, key=None):
    """Probe the provider with a harmless request. Only the key itself is sent."""
    provider = next((item for item in PROVIDERS if item["id"] == provider_id), None)
    if provider is None:
        raise SettingsError("未知服务商")
    key = _clean_secret(key) if key else effective_secret(provider["field"])
    if not key:
        return {"ok": False, "message": "尚未填写 Key"}
    try:
        if provider_id == "siliconflow":
            status, _, _ = _request("https://api.siliconflow.cn/v1/models?type=text&sub_type=chat",
                                    headers={"Authorization": f"Bearer {key}"})
            if status == 200:
                return {"ok": True, "message": "Key 有效（已连通硅基流动）"}
            return {"ok": False, "message": "Key 无效或已停用" if status in (401, 403)
                    else f"硅基流动返回 HTTP {status}"}
        # Doubao has no "whoami" endpoint: querying a random task id returns
        # 45000092 (task not found) for a valid key and 45000010 for an invalid one.
        status, headers, _ = _request(
            "https://openspeech.bytedance.com/api/v3/auc/bigmodel/query",
            headers={"Content-Type": "application/json", "x-api-key": key,
                     "X-Api-Resource-Id": "volc.seedasr.auc", "X-Api-Request-Id": str(uuid.uuid4())},
            data=b"{}", method="POST")
        code = (headers or {}).get("X-Api-Status-Code", "")
        if code in {"45000092", "20000000", "20000001", "20000002"}:
            return {"ok": True, "message": "Key 有效（已连通豆包录音文件识别 2.0）"}
        if status in (401, 403) or code == "45000010":
            return {"ok": False, "message": "Key 无效，或未开通豆包录音文件识别 2.0"}
        return {"ok": False, "message": f"豆包返回 HTTP {status} / {code or '无状态码'}"}
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return {"ok": False, "message": f"网络连接失败：{type(exc).__name__}"}


_models_cache = {}
_models_lock = threading.Lock()


def enrich_models():
    """Chat models available to the configured SiliconFlow key (cached 10 minutes)."""
    key = effective_secret("siliconflow_api_key")
    if not key:
        return {"models": list(ENRICH_MODEL_PRESETS), "source": "presets"}
    with _models_lock:
        cached = _models_cache.get("models")
        if cached and time.time() - cached[0] < 600:
            return {"models": cached[1], "source": "siliconflow"}
    try:
        status, _, body = _request("https://api.siliconflow.cn/v1/models?type=text&sub_type=chat",
                                   headers={"Authorization": f"Bearer {key}"})
        if status != 200:
            raise ValueError(status)
        ids = sorted({str(item.get("id")) for item in json.loads(body.decode("utf-8")).get("data", [])
                      if _MODEL_RE.fullmatch(str(item.get("id") or ""))})
    except (ValueError, OSError, urllib.error.URLError, json.JSONDecodeError):
        return {"models": list(ENRICH_MODEL_PRESETS), "source": "presets"}
    with _models_lock:
        _models_cache["models"] = (time.time(), ids)
    return {"models": ids, "source": "siliconflow"}
