"""
Gateway Router — AI Gateway 管理 API
"""
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/api/gateway", tags=["gateway"])

# 导入 gateway 实例（在主模块中初始化）
from model_orchestrator import gateway, load_keys, OPENROUTER_MODELS


@router.get("/health")
async def gateway_health():
    """Gateway 健康检查"""
    import asyncio
    return await asyncio.to_thread(gateway.provider_health)


@router.get("/stats")
async def gateway_stats():
    """Gateway 统计信息"""
    return gateway.stats()


@router.post("/chat")
async def gateway_chat(request: Request):
    """Gateway 聊天接口"""
    data = await request.json()
    prompt = data.get("prompt", "").strip()
    if not prompt:
        return JSONResponse({"error": "empty prompt"}, 400)
    return gateway.chat(prompt, system=data.get("system", ""),
                        provider=data.get("provider"),
                        submodel=data.get("submodel", "claude"))


@router.get("/models")
async def list_models():
    """列出可用模型"""
    keys = load_keys()
    return {
        "ollama": {"available": True, "free": True},
        "claude": {"available": "anthropic_key" in keys, "free": False},
        "gemini": {"available": "google_key" in keys, "free": False},
        "gpt": {"available": "openai_key" in keys, "free": False},
        "openrouter": {"available": "openrouter_key" in keys, "free": False,
                       "models": list(OPENROUTER_MODELS.keys())},
    }


@router.get("/models/openrouter")
async def list_openrouter_models():
    """列出 OpenRouter 模型"""
    return {"models": list(OPENROUTER_MODELS.keys())}


@router.get("/cost/stats")
async def cost_stats():
    """费用统计"""
    try:
        from cost_tracker import get_stats
        return get_stats()
    except:
        return {"total_cost": 0, "requests": 0}
