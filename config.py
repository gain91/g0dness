"""AI Suite 配置系统 — YAML 文件 + 环境变量覆盖"""
import os
import json

CONFIG_DIR = os.path.expanduser("~/.ai-suite")
CONFIG_FILE = os.path.join(CONFIG_DIR, "config.json")

DEFAULTS = {
    "gen_web": {
        "comfyui_dir": "C:/ComfyUI",
        "output_dir": os.path.expanduser("~/Downloads/generated"),
        "steps": 25,
        "width": 1024,
        "height": 1024,
        "cfg": 7.0,
    },
    "orchestrator": {
        "default_model": "ollama",
        "max_turns": 15,
        "request_timeout": 120,
        "stream_timeout": 300,
    },
    "tools": {
        "shell_timeout": 30,
        "cache_ttl": {
            "system_info": 15,
            "web_search": 60,
        },
        "max_results": 200,
    },
    "logging": {
        "level": "INFO",
    },
    "auth": {
        "enabled": False,
        "token": None,
    },
}

_config_cache = None


def load_config() -> dict:
    """加载配置，JSON 文件合并到默认值，环境变量覆盖"""
    global _config_cache
    if _config_cache is not None:
        return _config_cache

    cfg = json.loads(json.dumps(DEFAULTS))  # deep copy

    # 读 JSON 配置文件
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                user_cfg = json.load(f)
            _deep_merge(cfg, user_cfg)
        except Exception:
            pass

    # 环境变量覆盖: AI_SUITE_SECTION_KEY=value
    _apply_env_overrides(cfg)

    _config_cache = cfg
    return cfg


def save_config(cfg: dict):
    """保存配置到 JSON 文件"""
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


def get(section: str, key: str, default=None):
    """快捷取值: config.get('orchestrator', 'max_turns')"""
    cfg = load_config()
    return cfg.get(section, {}).get(key, default)


def _deep_merge(base: dict, override: dict):
    """递归合并 override 到 base"""
    for k, v in override.items():
        if k in base and isinstance(base[k], dict) and isinstance(v, dict):
            _deep_merge(base[k], v)
        else:
            base[k] = v


def _apply_env_overrides(cfg: dict):
    """AI_SUITE_GEN_WEB_STEPS=30 → cfg['gen_web']['steps']=30"""
    prefix = "AI_SUITE_"
    for env_key, env_val in os.environ.items():
        if not env_key.startswith(prefix):
            continue
        parts = env_key[len(prefix):].lower().split("_", 1)
        if len(parts) != 2:
            continue
        section, key = parts
        if section in cfg and key in cfg[section]:
            try:
                # 类型转换
                orig = cfg[section][key]
                if isinstance(orig, bool):
                    cfg[section][key] = env_val.lower() in ("1", "true", "yes")
                elif isinstance(orig, int):
                    cfg[section][key] = int(env_val)
                elif isinstance(orig, float):
                    cfg[section][key] = float(env_val)
                else:
                    cfg[section][key] = env_val
            except (ValueError, TypeError):
                pass
