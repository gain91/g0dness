"""费用追踪 — OpenRouter / Volcengine 按 token 计费"""
import json
import os
import time
from collections import defaultdict

from logger import get_logger

_log = get_logger("cost_tracker")

COST_DIR = os.path.expanduser("~/.ai-suite")
COST_FILE = os.path.join(COST_DIR, "cost.json")
os.makedirs(COST_DIR, exist_ok=True)

# 每百万 token 价格 (USD, 2026年6月)
PRICING = {
    # OpenRouter / Anthropic
    "anthropic/claude-fable-5": {"input": 15, "output": 75},
    "anthropic/claude-sonnet-4-6": {"input": 3, "output": 15},
    "anthropic/claude-haiku-4-5": {"input": 0.80, "output": 4},
    # OpenRouter / OpenAI
    "openai/gpt-5.5": {"input": 2.5, "output": 10},
    "openai/gpt-4o-mini": {"input": 0.15, "output": 0.60},
    "openai/gpt-5.4-image-2": {"input": 8, "output": 15},
    # OpenRouter / Google
    "google/gemini-3.5-flash": {"input": 0.15, "output": 0.60},
    "google/gemini-2.5-flash": {"input": 0.075, "output": 0.30},
    # DeepSeek (直连，当前免费)
    "deepseek-v4-pro": {"input": 0, "output": 0},
    # Volcengine 生图
    "doubao-seedream-5-0-260128": {"input": 0, "output": 0.035},  # per image
}


def _load_costs() -> dict:
    if os.path.exists(COST_FILE):
        try:
            with open(COST_FILE, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {"total_cost": 0.0, "by_model": {}, "by_date": {}, "history": []}


def _save_costs(data: dict):
    with open(COST_FILE, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def track(provider: str, model: str, prompt_tokens: int, completion_tokens: int):
    """记录一次调用费用"""
    pricing = PRICING.get(model, {"input": 0, "output": 0})
    cost = (prompt_tokens * pricing["input"] + completion_tokens * pricing["output"]) / 1_000_000

    data = _load_costs()
    data["total_cost"] = round(data["total_cost"] + cost, 6)

    # 按模型统计
    data["by_model"].setdefault(model, {"calls": 0, "cost": 0.0, "tokens": 0})
    data["by_model"][model]["calls"] += 1
    data["by_model"][model]["cost"] = round(data["by_model"][model]["cost"] + cost, 6)
    data["by_model"][model]["tokens"] += prompt_tokens + completion_tokens

    # 按日期统计
    today = time.strftime("%Y-%m-%d")
    data["by_date"].setdefault(today, 0.0)
    data["by_date"][today] = round(data["by_date"][today] + cost, 6)

    # 历史记录 (保留最近 1000 条)
    data["history"].append({
        "ts": int(time.time()),
        "provider": provider,
        "model": model,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "cost": cost,
    })
    if len(data["history"]) > 1000:
        data["history"] = data["history"][-1000:]

    _save_costs(data)
    return cost


def track_image(model: str, count: int = 1):
    """记录生图费用 (按张计费)"""
    pricing = PRICING.get(model, {"output": 0.035})
    cost = pricing["output"] * count

    data = _load_costs()
    data["total_cost"] = round(data["total_cost"] + cost, 6)

    data["by_model"].setdefault(model, {"calls": 0, "cost": 0.0, "tokens": 0})
    data["by_model"][model]["calls"] += 1
    data["by_model"][model]["cost"] = round(data["by_model"][model]["cost"] + cost, 6)

    today = time.strftime("%Y-%m-%d")
    data["by_date"].setdefault(today, 0.0)
    data["by_date"][today] = round(data["by_date"][today] + cost, 6)

    data["history"].append({
        "ts": int(time.time()), "provider": "volcengine", "model": model,
        "prompt_tokens": 0, "completion_tokens": 0, "cost": cost, "images": count,
    })
    if len(data["history"]) > 1000:
        data["history"] = data["history"][-1000:]

    _save_costs(data)
    return cost


def get_stats() -> dict:
    """获取费用统计"""
    return _load_costs()
