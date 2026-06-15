"""
AutoGen 多模型编排器
本地 Ollama + Claude API + Gemini API → 自动路由
"""
import os, json, asyncio
from typing import Optional

# API Key 加载 — 优先明文(快)，可选加密 vault
def load_keys():
    # 明文文件优先 — 避免 key_vault/cryptography 导入耗时
    env_file = os.path.expanduser("~/.model_keys.json")
    if os.path.exists(env_file):
        with open(env_file) as f:
            keys = json.load(f)
        if keys:
            return keys
    # 降级：加密 vault (如有)
    try:
        from key_vault import load_keys as _load
        keys = _load()
        if keys:
            return keys
    except ImportError:
        pass
    return {}

def save_keys(keys):
    env_file = os.path.expanduser("~/.model_keys.json")
    with open(env_file, "w") as f:
        json.dump(keys, f, indent=2)
    os.chmod(env_file, 0o600) if os.name != "nt" else None

# ═══════ Agent 配置 ═══════
OLLAMA_CONFIG = {
    "config_list": [
        {"api_type": "ollama", "model": "qwen3:8b",
         "client_host": "http://localhost:11434"}
    ],
    "temperature": 0.7,
}

CLAUDE_CONFIG_TEMPLATE = {
    "config_list": [
        {"api_type": "anthropic", "model": "claude-fable-5",
         "api_key": "PLACEHOLDER",
         "base_url": "https://api.anthropic.com"}
    ],
    "temperature": 0.7,
}

GEMINI_CONFIG_TEMPLATE = {
    "config_list": [
        {"api_type": "gemini", "model": "gemini-2.5-flash",
         "api_key": "PLACEHOLDER"}
    ],
    "temperature": 0.7,
}

GPT_CONFIG_TEMPLATE = {
    "config_list": [
        {"api_type": "openai", "model": "gpt-5.4-thinking",
         "api_key": "PLACEHOLDER"}
    ],
    "temperature": 0.7,
}

OPENROUTER_IMAGE_MODELS = {
    "openai": "openai/gpt-5.4-image-2",
    "gemini": "google/gemini-3.1-flash-image-preview",
}

OPENROUTER_MODELS = {
    "claude":         "anthropic/claude-fable-5",
    "claude-sonnet":  "anthropic/claude-sonnet-4-6",
    "claude-haiku":   "anthropic/claude-haiku-4-5-20251001",
    "gpt":            "openai/gpt-5.5",
    "gpt-mini":       "openai/gpt-4o-mini",
    "gemini":         "google/gemini-3.5-flash",
    "gemini-fast":    "google/gemini-2.5-flash",
}

# DeepSeek via Anthropic-compatible API (same endpoint as Claude Code)
def _load_deepseek_config():
    keys = load_keys()
    return {
        "base_url": "https://api.deepseek.com/anthropic",
        "api_key": keys.get("deepseek_key", ""),
        "model": "deepseek-v4-pro",
        "display": "DeepSeek V4 Pro (100万ctx)",
    }

DEEPSEEK_CONFIG = None  # Lazy init: avoid blocking import during module load
def get_deepseek_config():
    global DEEPSEEK_CONFIG
    if DEEPSEEK_CONFIG is None:
        DEEPSEEK_CONFIG = _load_deepseek_config()
    return DEEPSEEK_CONFIG

# ═══════ AI Gateway — 统一多提供商抽象 ═══════

class AIGateway:
    """统一的 AI 提供商接口 — runtime switching, fallback chains, usage tracking"""

    def __init__(self):
        self.usage = {"calls": 0, "tokens": 0, "providers": {}}

    def chat(self, prompt: str, system: str = "", provider: str = None,
             submodel: str = "claude") -> dict:
        """
        统一对话 — 自动路由或指定提供商。
        返回: {provider, reply, error, tokens_used}
        """
        import time as _t
        start = _t.time()

        if not provider:
            provider = smart_route(prompt)

        self.usage["calls"] += 1
        self.usage["providers"][provider] = self.usage["providers"].get(provider, 0) + 1

        # Try primary provider
        reply = None
        error = None
        try:
            if provider == "ollama":
                reply = chat_ollama(prompt, system=system)
            elif provider == "deepseek":
                reply = chat_deepseek(prompt, system=system)
            elif provider in OPENROUTER_MODELS:
                reply = chat_openrouter(prompt, system=system, submodel=provider)
            else:
                reply = chat_ollama(prompt, system=system)
                provider = "ollama"
        except Exception as e:
            error = str(e)
            # Fallback chain: local Ollama → DeepSeek → OpenRouter models
            fallback_chain = ["ollama", "deepseek", "claude", "gpt", "gemini-fast"]
            for fb in fallback_chain:
                if fb == provider:
                    continue
                try:
                    if fb == "ollama":
                        reply = chat_ollama(prompt, system=system)
                    elif fb == "deepseek":
                        reply = chat_deepseek(prompt, system=system)
                    elif fb in OPENROUTER_MODELS:
                        reply = chat_openrouter(prompt, system=system, submodel=fb)
                    else:
                        continue
                    provider = fb
                    error = None  # 降级成功，清除错误
                    break
                except Exception:
                    pass

        elapsed = round(_t.time() - start, 1)
        tokens = estimateTokens(reply) if reply else 0
        self.usage["tokens"] += tokens

        return {"provider": provider, "reply": reply or "", "error": error,
                "tokens": tokens, "elapsed_s": elapsed}

    def provider_health(self) -> dict:
        """检查各提供商可用性"""
        health = {"ollama": False, "deepseek": False, "openrouter": False}
        try:
            import urllib.request
            urllib.request.urlopen("http://localhost:11434/api/tags", timeout=2)
            health["ollama"] = True
        except:
            pass
        keys = load_keys()
        health["deepseek"] = bool(keys.get("deepseek_key"))
        health["openrouter"] = bool(keys.get("openrouter_key"))
        health["providers_count"] = sum(1 for v in health.values() if v)
        return {"ok": True, "health": health, "usage": self.usage}

    def stats(self) -> dict:
        return {"usage": self.usage, "providers": len(self.usage.get("providers", {}))}


def estimateTokens(text: str) -> int:
    """Token 估算 — 中英文分别计算，优先 tiktoken"""
    if not text:
        return 0
    try:
        import tiktoken
        enc = tiktoken.get_encoding("cl100k_base")
        return len(enc.encode(text))
    except (ImportError, Exception):
        pass
    # 降级：中文 ~0.65 token/char, 英文 ~0.28 token/char
    import re
    cn_chars = len(re.findall(r'[一-鿿　-〿＀-￯]', text))
    en_chars = len(text) - cn_chars
    return max(1, int(cn_chars * 0.65 + en_chars / 3.5))

# Global gateway instance
gateway = AIGateway()

# ═══════ 简易编排（不用完整 AutoGen 重依赖）══
try:
    from litellm import completion
    HAS_LITELLM = True
except ImportError:
    HAS_LITELLM = False

    def completion(**kwargs):
        raise RuntimeError("litellm not installed. Run: pip install litellm")

def chat_ollama(prompt: str, system: str = "", model_name: str = "deepseek-r1:14b") -> str:
    """本地 Ollama 对话 — 直连，不用 LiteLLM"""
    import urllib.request as ur
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    else:
        messages.append({"role": "system", "content": "你是一个直接、诚实的AI助手。用第一人称自然回答。你的名字是g0dness。"})
    messages.append({"role": "user", "content": prompt})
    body = json.dumps({
        "model": model_name,
        "messages": messages,
        "stream": False
    }).encode()
    req = ur.Request("http://localhost:11434/api/chat", body,
                      headers={"Content-Type": "application/json"})
    resp = json.loads(ur.urlopen(req, timeout=120).read())
    return resp["message"]["content"]

def stream_ollama(prompt: str, system: str = "", model_name: str = "deepseek-r1:14b"):
    """Ollama 流式 — yield token by token (line-buffered, UTF-8 safe)"""
    import urllib.request as ur
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    else:
        messages.append({"role": "system", "content": "你是一个直接、诚实的AI助手。用第一人称自然回答。你的名字是g0dness。"})
    messages.append({"role": "user", "content": prompt})
    body = json.dumps({"model": model_name, "messages": messages, "stream": True}).encode()
    req = ur.Request("http://localhost:11434/api/chat", body,
                      headers={"Content-Type": "application/json"})
    resp = ur.urlopen(req, timeout=120)
    # Read line by line using file-like iterator (handles UTF-8 correctly)
    for line_bytes in resp:
        line = line_bytes.decode("utf-8", errors="replace").strip()
        if not line: continue
        try:
            data = json.loads(line)
            token = data.get("message", {}).get("content", "")
            if token:
                yield token
        except json.JSONDecodeError:
            pass

CACHE_SYSTEM_PROMPT = "你是 g0dness，一个直接高效的 AI 助手。用中文回复。"

def chat_deepseek(prompt: str, system: str = "") -> str:
    """DeepSeek V4 — Anthropic Messages API"""
    import urllib.request as ur
    messages = []
    sys_text = system if system else CACHE_SYSTEM_PROMPT
    body = json.dumps({
        "model": get_deepseek_config()["model"],
        "max_tokens": 8192,
        "system": sys_text,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False
    }).encode()
    req = ur.Request(f"{get_deepseek_config()['base_url']}/v1/messages", body,
                      headers={"Content-Type": "application/json",
                               "x-api-key": get_deepseek_config()["api_key"],
                               "anthropic-version": "2023-06-01"})
    resp = json.loads(ur.urlopen(req, timeout=180).read())
    # Anthropic format: content is a list of blocks
    for block in resp.get("content", []):
        if block.get("type") == "text":
            return block["text"]
    return str(resp)[:500]

def stream_deepseek(prompt: str, system: str = ""):
    """DeepSeek V4 流式 — Anthropic SSE format"""
    import urllib.request as ur
    sys_text = system if system else CACHE_SYSTEM_PROMPT
    body = json.dumps({
        "model": get_deepseek_config()["model"],
        "max_tokens": 8192,
        "system": sys_text,
        "messages": [{"role": "user", "content": prompt}],
        "stream": True
    }).encode()
    req = ur.Request(f"{get_deepseek_config()['base_url']}/v1/messages", body,
                      headers={"Content-Type": "application/json",
                               "x-api-key": get_deepseek_config()["api_key"],
                               "anthropic-version": "2023-06-01"})
    resp = ur.urlopen(req, timeout=180)
    for line_bytes in resp:
        line = line_bytes.decode("utf-8", errors="replace").strip()
        if not line or not line.startswith("data:"):
            continue
        try:
            data = json.loads(line[6:])
            # Anthropic SSE: {"type":"content_block_delta","delta":{"type":"text_delta","text":"..."}}
            if data.get("type") == "content_block_delta":
                text = data.get("delta", {}).get("text", "")
                if text:
                    yield text
            elif data.get("type") == "message_stop":
                break
        except json.JSONDecodeError:
            pass

def stream_openrouter(prompt: str, system: str = "", submodel: str = "claude"):
    """OpenRouter 流式 — 缓存友好：static system → user request"""
    import urllib.request as ur
    keys = load_keys()
    api_key = keys.get("openrouter_key", "")
    if not api_key:
        yield "[错误] 未设置 OpenRouter Key"
        return
    model_id = OPENROUTER_MODELS.get(submodel, OPENROUTER_MODELS["claude"])
    # 缓存友好结构：static system first, dynamic user last
    messages = [{"role": "system", "content": CACHE_SYSTEM_PROMPT + (f"\n{system}" if system else "")}]
    messages.append({"role": "user", "content": prompt})
    body = json.dumps({"model": model_id, "messages": messages, "stream": True}).encode()
    req = ur.Request("https://openrouter.ai/api/v1/chat/completions", body,
                      headers={"Content-Type": "application/json",
                               "Authorization": f"Bearer {api_key}",
                               "HTTP-Referer": "http://localhost:5001",
                               "X-Title": "AI Suite"})
    resp = ur.urlopen(req, timeout=120)
    for line_bytes in resp:
        line = line_bytes.decode("utf-8", errors="replace").strip()
        if not line or not line.startswith("data:"):
            continue
        if line == "data: [DONE]":
            break
        try:
            data = json.loads(line[6:])
            delta = data.get("choices", [{}])[0].get("delta", {})
            content = delta.get("content", "")
            if content:
                yield content
        except json.JSONDecodeError:
            pass

def chat_claude(prompt: str, system: str = "") -> str:
    """Claude API 对话"""
    keys = load_keys()
    api_key = keys.get("anthropic_key")
    if not api_key:
        return "[错误] 未设置 Anthropic API Key。请运行 setup_keys()"

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    resp = completion(
        model="claude-sonnet-4-6",
        messages=messages,
        api_key=api_key,
        temperature=0.7,
    )
    return resp.choices[0].message.content

def chat_gemini(prompt: str, system: str = "") -> str:
    """Gemini API 对话"""
    keys = load_keys()
    api_key = keys.get("google_key")
    if not api_key:
        return "[错误] 未设置 Google API Key。请运行 setup_keys()"

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    resp = completion(
        model="gemini/gemini-3.5-flash",
        messages=messages,
        api_key=api_key,
        temperature=0.7,
    )
    return resp.choices[0].message.content

def chat_openrouter(prompt: str, system: str = "", submodel: str = "claude") -> str:
    """OpenRouter 统一网关 — 缓存友好结构"""
    import urllib.request as ur
    keys = load_keys()
    api_key = keys.get("openrouter_key")
    if not api_key:
        return "[错误] 未设置 OpenRouter API Key。"
    model = OPENROUTER_MODELS.get(submodel, OPENROUTER_MODELS["claude"])
    messages = [{"role": "system", "content": CACHE_SYSTEM_PROMPT + (f"\n{system}" if system else "")}]
    messages.append({"role": "user", "content": prompt})
    body = json.dumps({"model": model, "messages": messages}).encode()
    req = ur.Request("https://openrouter.ai/api/v1/chat/completions", body,
                      headers={"Content-Type": "application/json",
                               "Authorization": f"Bearer {api_key}",
                               "HTTP-Referer": "http://localhost:5001",
                               "X-Title": "AI Suite"})
    resp = json.loads(ur.urlopen(req, timeout=120).read())
    return resp["choices"][0]["message"]["content"]

def generate_image_openrouter(prompt: str, provider: str = "openai") -> Optional[str]:
    """通过 OpenRouter 调用图像生成模型，返回 base64 data URL 或 None"""
    import urllib.request as ur
    keys = load_keys()
    api_key = keys.get("openrouter_key")
    if not api_key:
        return None
    model = OPENROUTER_IMAGE_MODELS.get(provider, OPENROUTER_IMAGE_MODELS["openai"])
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "modalities": ["image", "text"],
    }).encode()
    req = ur.Request("https://openrouter.ai/api/v1/chat/completions", body,
                      headers={"Content-Type": "application/json",
                               "Authorization": f"Bearer {api_key}",
                               "HTTP-Referer": "http://localhost:5001"})
    resp = json.loads(ur.urlopen(req, timeout=120).read())
    # OpenRouter 可能返回错误体，先检查
    if "error" in resp:
        raise Exception(resp["error"].get("message", str(resp["error"])))
    try:
        msg = resp["choices"][0]["message"]
    except (KeyError, IndexError) as e:
        raise Exception(f"Unexpected OpenRouter response: {json.dumps(resp, ensure_ascii=False)[:500]}") from e
    content = msg.get("content", "")
    if isinstance(content, list):
        for part in content:
            if part.get("type") == "image_url":
                return part["image_url"]["url"]
    elif isinstance(content, str) and content.startswith("data:image"):
        return content
    return str(content)[:200]

def chat_gpt(prompt: str, system: str = "") -> str:
    """GPT-4o API 对话"""
    keys = load_keys()
    api_key = keys.get("openai_key")
    if not api_key:
        return "[错误] 未设置 OpenAI API Key。请运行 setup_keys()"

    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    resp = completion(
        model="gpt-4o",
        messages=messages,
        api_key=api_key,
        temperature=0.7,
    )
    return resp.choices[0].message.content

# ═══════ 智能路由 ═══════
ROUTING_PROMPT = """你是一个任务路由器。根据用户输入复杂度选择合适的模型。

可选模型（按价格从低到高）：
- ollama: 本地免费，适合一般对话、翻译、简单代码
- claude-haiku: 便宜快速，适合日常问答 (OpenRouter)
- gemini-fast: 便宜快速，适合简单任务 (OpenRouter)
- gpt-mini: 便宜，适合创意简单任务 (OpenRouter)
- claude-sonnet: 性价比，适合中等推理 (OpenRouter)
- gemini: 均衡，适合多模态分析 (OpenRouter)
- claude: 最强，适合深度推理、复杂分析、长文本 (OpenRouter)
- gpt: 最强，适合复杂创意 (OpenRouter)

规则：简单任务用便宜模型，复杂任务才用最强模型。
只回复模型名: ollama, claude-haiku, claude-sonnet, claude, gpt-mini, gpt, gemini-fast, gemini

用户输入: {input}
"""

def smart_route(user_input: str) -> str:
    """用本地 Ollama 判断复杂度 + 硬件状态选择模型"""
    # 硬件感知：低资源时优先用云端便宜模型
    try:
        from hw_monitor import get_tier
        tier = get_tier()
    except:
        tier = "medium"

    try:
        result = chat_ollama(ROUTING_PROMPT.format(input=user_input[:500]))
        result = result.strip().lower()
        for m in ["claude-haiku", "claude-sonnet", "claude",
                  "gpt-mini", "gpt",
                  "gemini-fast", "gemini",
                  "ollama"]:
            if m in result:
                return m
        return "ollama"
    except:
        # 硬件降级：极简模式强制本地
        return "ollama" if tier == "minimal" else "gemini-fast"

# ═══════ 统一入口 ═══════
def chat(user_input: str, force_model: Optional[str] = None, submodel: str = "claude") -> dict:
    """统一对话接口，自动路由或指定模型"""
    model = force_model or smart_route(user_input)

    try:
        if model == "ollama":
            reply = chat_ollama(user_input)
        elif model == "deepseek":
            reply = chat_deepseek(user_input)
        elif model in OPENROUTER_MODELS:
            reply = chat_openrouter(user_input, submodel=model)
        else:
            reply = chat_ollama(user_input)
            model = "ollama"
        return {"model": model, "reply": reply, "error": None}
    except Exception as e:
        # 任何模型失败 → 降级到 Ollama
        try:
            reply = chat_ollama(user_input)
            return {"model": "ollama", "reply": reply, "error": f"{model} 调用失败: {e}，降级到 Ollama"}
        except:
            return {"model": "none", "reply": "", "error": str(e)}

# ═══════ 设置向导 ═══════
def setup_keys():
    """交互式设置 API Key"""
    print("=" * 50)
    print("  AutoGen 多模型编排器 - API Key 设置")
    print("=" * 50)
    print()
    print("Claude API Key (去 https://console.anthropic.com 获取)")
    print("没有的话直接回车跳过")
    anthropic_key = input("> ").strip()

    print()
    print("Gemini API Key (去 https://aistudio.google.com 获取)")
    print("没有的话直接回车跳过")
    google_key = input("> ").strip()

    print()
    print("OpenAI API Key (去 https://platform.openai.com 获取)")
    print("没有的话直接回车跳过")
    openai_key = input("> ").strip()

    print()
    print("OpenRouter API Key (去 https://openrouter.ai/keys 获取)")
    print("一把 Key 调 Claude + GPT + Gemini，推荐！")
    print("没有的话直接回车跳过")
    openrouter_key = input("> ").strip()

    keys = {}
    if anthropic_key:
        keys["anthropic_key"] = anthropic_key
    if google_key:
        keys["google_key"] = google_key
    if openai_key:
        keys["openai_key"] = openai_key
    if openrouter_key:
        keys["openrouter_key"] = openrouter_key

    save_keys(keys)
    print()
    if keys:
        print(f"✅ 已保存 {len(keys)} 个 Key")
    else:
        print("⚠️ 未设置任何 Key，仅本地 Ollama 可用")

# ═══════ Web API (FastAPI) ═══════
from fastapi import FastAPI, Request, Query, WebSocket
from fastapi.responses import JSONResponse, StreamingResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from auth_middleware import AuthMiddleware, AUTH_TOKEN as _AUTH_TOKEN
from logger import get_logger
_log = get_logger("model_orchestrator")
import uvicorn

app = FastAPI(title="AI Suite Orchestrator", docs_url=None, redoc_url=None)
app.add_middleware(AuthMiddleware)
_log.info("model_orchestrator starting on port 5001")

app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"],
    allow_headers=["*"], allow_credentials=True,
)

@app.get("/")
async def index():
    return HTMLResponse("<h2>AI Suite Orchestrator :5001</h2><p>Chat at <a href='http://localhost:5000/chat'>localhost:5000/chat</a></p>")

@app.post("/api/chat")
async def api_chat(request: Request):
    data = await request.json()
    prompt = data.get("prompt", "").strip()
    if not prompt:
        return JSONResponse({"error": "empty prompt"}, 400)
    force_model = data.get("model")
    submodel = data.get("submodel", "claude")
    result = chat(prompt, force_model=force_model if force_model else None, submodel=submodel)
    return result

@app.post("/api/chat/stream")
async def api_chat_stream(request: Request):
    data = await request.json()
    prompt = data.get("prompt", "").strip()
    force_model = data.get("model")
    submodel = data.get("submodel", "claude")
    system = data.get("system", "")

    async def generate():
        try:
            if force_model == "deepseek":
                for token in stream_deepseek(prompt, system=system):
                    yield f"data: {json.dumps({'token': token, 'model': 'deepseek-v4-pro'}, ensure_ascii=False)}\n\n"
            elif force_model and force_model in OPENROUTER_MODELS:
                for token in stream_openrouter(prompt, system=system, submodel=force_model):
                    yield f"data: {json.dumps({'token': token, 'model': force_model}, ensure_ascii=False)}\n\n"
            elif force_model and force_model.startswith("ollama:"):
                ollama_model = force_model.split(":", 1)[1]
                for token in stream_ollama(prompt, system=system, model_name=ollama_model):
                    yield f"data: {json.dumps({'token': token, 'model': ollama_model}, ensure_ascii=False)}\n\n"
            elif force_model == "ollama" or not force_model:
                for token in stream_ollama(prompt, system=system):
                    yield f"data: {json.dumps({'token': token, 'model': 'ollama'}, ensure_ascii=False)}\n\n"
            else:
                result = chat(prompt, force_model=force_model, submodel=submodel)
                yield f"data: {json.dumps({'token': result['reply'], 'model': result['model'], 'done': True}, ensure_ascii=False)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'error': str(e)}, ensure_ascii=False)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(generate(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

@app.post("/api/image_gen")
async def api_image_gen(request: Request):
    data = await request.json()
    prompt = data.get("prompt", "").strip()
    provider = data.get("provider", "openai")
    if not prompt:
        return JSONResponse({"error": "empty prompt"}, 400)
    try:
        result = generate_image_openrouter(prompt, provider)
        return {"ok": True, "image": result, "provider": provider}
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, 500)

# ═══════ Conversation Memory API ═══════
try:
    from db import list_convs, create_conv, delete_conv, add_message, get_messages, clear_messages, search_messages
    HAS_DB = True
except:
    HAS_DB = False

@app.get("/api/conversations")
async def api_list_convs():
    if not HAS_DB: return {"convs": []}
    return {"convs": list_convs()}

@app.post("/api/conversations")
async def api_create_conv(request: Request):
    if not HAS_DB: return JSONResponse({"error": "db not available"}, 500)
    data = await request.json() or {}
    cid = create_conv(title=data.get("title", "New Chat"), model=data.get("model", "ollama"))
    return {"id": cid}

@app.get("/api/conversations/{cid}/messages")
async def api_get_messages(cid: str):
    if not HAS_DB: return {"messages": []}
    return {"messages": get_messages(cid)}

@app.post("/api/conversations/{cid}/messages")
async def api_add_message(cid: str, request: Request):
    if not HAS_DB: return {"ok": True}
    data = await request.json()
    add_message(cid, data.get("role", "user"), data.get("content", ""), data.get("tokens", 0))
    return {"ok": True}

@app.delete("/api/conversations/{cid}")
async def api_delete_conv(cid: str):
    if not HAS_DB: return {"ok": True}
    delete_conv(cid)
    return {"ok": True}

@app.delete("/api/conversations/{cid}/messages")
async def api_clear_messages(cid: str):
    if not HAS_DB: return {"ok": True}
    clear_messages(cid)
    return {"ok": True}

@app.get("/api/search")
async def api_search(q: str = Query("")):
    if not q or not HAS_DB: return {"results": []}
    return {"results": search_messages(q)}

@app.get("/api/models")
async def api_models():
    keys = load_keys()
    return {
        "ollama": {"available": True, "free": True},
        "claude": {"available": "anthropic_key" in keys, "free": False},
        "gemini": {"available": "google_key" in keys, "free": False},
        "gpt": {"available": "openai_key" in keys, "free": False},
        "openrouter": {"available": "openrouter_key" in keys, "free": False,
                       "models": list(OPENROUTER_MODELS.keys())},
    }

# ═══════ AI Gateway API ═══════

@app.get("/api/gateway/health")
async def api_gateway_health():
    import asyncio
    return await asyncio.to_thread(gateway.provider_health)

@app.get("/api/gateway/stats")
async def api_gateway_stats():
    return gateway.stats()

@app.post("/api/gateway/chat")
async def api_gateway_chat(request: Request):
    data = await request.json()
    prompt = data.get("prompt", "").strip()
    if not prompt:
        return JSONResponse({"error": "empty prompt"}, 400)
    return gateway.chat(prompt, system=data.get("system", ""),
                        provider=data.get("provider"),
                        submodel=data.get("submodel", "claude"))

# ═══════ Tool API ═══════
try:
    from tools import list_tools, execute as tool_execute
    HAS_TOOLS = True
except:
    HAS_TOOLS = False

@app.get("/api/tools")
async def api_list_tools():
    if not HAS_TOOLS: return {"tools": []}
    return {"tools": list_tools()}

@app.post("/api/tools/{tool_name}")
async def api_execute_tool(tool_name: str, request: Request):
    if not HAS_TOOLS: return JSONResponse({"ok": False, "error": "tools not available"}, 500)
    params = await request.json() or {}
    return tool_execute(tool_name, params)

# ═══════ Skills Marketplace ═══════
SKILLS_DIR = os.path.expanduser("~/.ai-suite/skills")
SKILLS = {}

def load_skills():
    global SKILLS
    SKILLS = {}
    if not os.path.isdir(SKILLS_DIR):
        return
    for fname in os.listdir(SKILLS_DIR):
        if fname.endswith(".md"):
            path = os.path.join(SKILLS_DIR, fname)
            with open(path, encoding="utf-8") as f:
                content = f.read()
            # Parse: first line is "# name", rest is template
            lines = content.strip().split("\n")
            name = lines[0].replace("# ", "").strip() if lines else fname[:-3]
            SKILLS[name] = {"name": name, "file": fname, "template": "\n".join(lines[1:]).strip()}

load_skills()

@app.get("/api/skills")
async def api_list_skills():
    return {"skills": list(SKILLS.values())}

@app.post("/api/skills/{skill_name}")
async def api_use_skill(skill_name: str, request: Request):
    if skill_name not in SKILLS:
        return JSONResponse({"error": "skill not found"}, 404)
    data = await request.json() or {}
    prompt = SKILLS[skill_name]["template"]
    # Replace placeholders
    prompt = prompt.replace("{{args}}", data.get("args", ""))
    for k, v in data.get("params", {}).items():
        prompt = prompt.replace(f"{{{{{k}}}}}", str(v))
    result = chat(prompt, force_model=data.get("model"))
    return result

# ═══════ Agent 路由 ═══════
try:
    from agent import Agent, register_routes as register_agent_routes
    register_agent_routes(app)
    HAS_AGENT = True
except Exception as e:
    HAS_AGENT = False
    print(f"[warn] agent module not loaded: {e}")

# ═══════ 通知 & 后台任务 ═══════
try:
    from notify import register_notify_routes
    register_notify_routes(app)
    HAS_NOTIFY = True
except Exception as e:
    HAS_NOTIFY = False
    print(f"[warn] notify module not loaded: {e}")

# ═══════ 定时任务调度器 ═══════
try:
    from scheduler import register_scheduler_routes, start_scheduler
    register_scheduler_routes(app)
    start_scheduler()
    HAS_SCHEDULER = True
except Exception as e:
    HAS_SCHEDULER = False
    print(f"[warn] scheduler module not loaded: {e}")

# ═══════ 对话导出/导入 ═══════
@app.get("/api/conversations/{cid}/export")
async def api_export_conv(cid: str, fmt: str = "json"):
    """导出对话 — json 或 markdown"""
    try:
        from db import get_db
        db = get_db()
        msgs = db.execute("SELECT role, content, tokens, created_at FROM messages WHERE conv_id=? ORDER BY created_at", (cid,)).fetchall()
        if not msgs:
            return JSONResponse({"error": "not found"}, 404)
        title = db.execute("SELECT title FROM conversations WHERE id=?", (cid,)).fetchone()
        title = title[0] if title else "Untitled"

        if fmt == "md":
            md = f"# {title}\n\n"
            for m in msgs:
                role = "**You**" if m["role"] == "user" else "**AI**" if m["role"] == "assistant" else f"**{m['role']}**"
                md += f"{role}:\n{m['content']}\n\n---\n\n"
            return {"ok": True, "format": "markdown", "data": md, "filename": f"{title}.md"}
        else:
            return {"ok": True, "format": "json", "data": {
                "title": title, "id": cid,
                "messages": [{"role": m["role"], "content": m["content"], "tokens": m["tokens"]} for m in msgs]
            }, "filename": f"{title}.json"}
    except Exception as e:
        return JSONResponse({"error": str(e)}, 500)

@app.post("/api/conversations/import")
async def api_import_conv(request: Request):
    """导入 JSON 对话"""
    try:
        from db import get_db
        import uuid, time
        data = await request.json()
        db = get_db()
        cid = f"import_{uuid.uuid4().hex[:8]}"
        db.execute("INSERT INTO conversations (id, title, model, created_at) VALUES (?, ?, ?, ?)",
                   (cid, data.get("title", "Imported"), "ollama", int(time.time())))
        for m in data.get("messages", []):
            db.execute("INSERT INTO messages (conv_id, role, content, tokens, created_at) VALUES (?,?,?,?,?)",
                       (cid, m.get("role","user"), m.get("content",""), m.get("tokens",0), int(time.time())))
        db.commit()
        return {"ok": True, "id": cid, "count": len(data.get("messages", []))}
    except Exception as e:
        return JSONResponse({"error": str(e)}, 500)

# ═══════ 动态模型列表 ═══════
_OR_MODELS_CACHE = {"data": [], "ts": 0}

@app.get("/api/models/openrouter")
async def api_openrouter_models():
    """动态获取 OpenRouter 可用模型列表 (缓存 1 小时)"""
    import time as _t
    if _t.time() - _OR_MODELS_CACHE["ts"] < 3600 and _OR_MODELS_CACHE["data"]:
        return {"ok": True, "models": _OR_MODELS_CACHE["data"], "cached": True}
    try:
        import urllib.request as _ur2
        keys = load_keys()
        api_key = keys.get("openrouter_key")
        if not api_key:
            return {"ok": False, "error": "OpenRouter key not set"}
        req = _ur2.Request("https://openrouter.ai/api/v1/models",
                          headers={"Authorization": f"Bearer {api_key}"})
        resp = _ur2.urlopen(req, timeout=15)
        data = json.loads(resp.read())
        models = []
        for m in data.get("data", []):
            models.append({
                "id": m.get("id"),
                "name": m.get("name", m.get("id", "")),
                "context_length": m.get("context_length", 0),
                "pricing": m.get("pricing", {}),
            })
        _OR_MODELS_CACHE["data"] = sorted(models, key=lambda x: x.get("name", ""))
        _OR_MODELS_CACHE["ts"] = _t.time()
        return {"ok": True, "models": _OR_MODELS_CACHE["data"], "cached": False}
    except Exception as e:
        return {"ok": False, "error": str(e), "models": _OR_MODELS_CACHE["data"] or []}

# ═══════ 学习记忆 ═══════
try:
    from memory_agent import register_memory_routes
    register_memory_routes(app)
    HAS_MEMORY = True
except Exception as e:
    HAS_MEMORY = False
    print(f"[warn] memory module not loaded: {e}")

# ═══════ Cost Tracking ═══════
try:
    from cost_tracker import get_stats as cost_stats, track as cost_track
    HAS_COST = True
except Exception:
    HAS_COST = False
    cost_stats = lambda: {}
    cost_track = lambda *a, **kw: 0

@app.get("/api/cost/stats")
async def api_cost_stats():
    return {"ok": True, "stats": cost_stats()}

# ═══════ Templates ═══════
try:
    from templates_lib import load_templates, add_template, delete_template
    HAS_TEMPLATES = True
except Exception:
    HAS_TEMPLATES = False
    load_templates = lambda: []
    add_template = lambda n, p, c="": {"error": "unavailable"}
    delete_template = lambda tid: False

@app.get("/api/templates")
async def api_list_templates():
    return {"ok": True, "templates": load_templates()}

@app.post("/api/templates")
async def api_add_template(request: Request):
    data = await request.json()
    tpl = add_template(data.get("name", ""), data.get("prompt", ""), data.get("category", "自定义"))
    return {"ok": True, "template": tpl}

@app.delete("/api/templates/{tid}")
async def api_delete_template(tid: str):
    ok = delete_template(tid)
    return {"ok": ok}

# ═══════ Tool Audit ═══════
try:
    from tool_audit import get_recent_calls
    HAS_AUDIT = True
except Exception:
    HAS_AUDIT = False
    get_recent_calls = lambda n=100: []

@app.get("/api/audit/tools")
async def api_tool_audit(limit: int = 100):
    return {"ok": True, "calls": get_recent_calls(limit)}

# ═══════ WebSocket Chat ═══════
import asyncio
import json as _json

@app.websocket("/ws/chat")
async def ws_chat(ws: WebSocket):
    """WebSocket 双向聊天 — 支持 cancel + SSE 降级"""
    await ws.accept()
    cancel_event = asyncio.Event()

    async def _recv_loop():
        while True:
            try:
                msg = await ws.receive_text()
                data = _json.loads(msg)
                if data.get("action") == "cancel":
                    cancel_event.set()
            except Exception:
                break

    recv_task = asyncio.create_task(_recv_loop())

    try:
        while True:
            data = await ws.receive_json()
            if data.get("action") == "cancel":
                cancel_event.set()
                continue
            if data.get("action") != "send":
                continue

            prompt = data.get("prompt", "").strip()
            if not prompt:
                await ws.send_json({"type": "error", "error": "empty prompt"})
                continue

            model = data.get("model", "ollama")
            system = data.get("system", "")

            try:
                tokens_out = 0
                if model == "ollama" or model == "deepseek-r1":
                    for token in stream_ollama(prompt, system=system, model_name=model):
                        if cancel_event.is_set():
                            await ws.send_json({"type": "cancelled"})
                            break
                        await ws.send_json({"type": "token", "token": token})
                        tokens_out += 1
                elif model in OPENROUTER_MODELS:
                    for token in stream_openrouter(prompt, system=system, submodel=model):
                        if cancel_event.is_set():
                            await ws.send_json({"type": "cancelled"})
                            break
                        await ws.send_json({"type": "token", "token": token})
                        tokens_out += 1
                else:
                    # 同步模型 — 单次返回
                    reply = chat(prompt, force_model=model, submodel=model)
                    await ws.send_json({"type": "token", "token": reply["reply"]})

                if HAS_COST and tokens_out:
                    cost_track("openrouter" if model in OPENROUTER_MODELS else model,
                               model, len(prompt) // 3, tokens_out)
                await ws.send_json({"type": "done", "tokens": tokens_out})
            except Exception as e:
                await ws.send_json({"type": "error", "error": str(e)})
    except Exception:
        pass
    finally:
        recv_task.cancel()
        try:
            await ws.close()
        except Exception:
            pass

# ═══════ 文件监工 ═══════
try:
    from file_watcher import register_routes as register_watcher_routes, start as start_watcher
    register_watcher_routes(app)
    start_watcher()
    HAS_WATCHER = True
except Exception as e:
    HAS_WATCHER = False
    print(f"[warn] file_watcher not loaded: {e}")

if __name__ == "__main__":
    print("=" * 50)
    print("  AutoGen Multi-Model Orchestrator")
    try:
        import urllib.request
        urllib.request.urlopen("http://localhost:11434/api/tags", timeout=2)
        print("  Ollama: connected")
    except:
        print("  Ollama: offline")
    keys = load_keys()
    print(f"  Claude: {'configured' if 'anthropic_key' in keys else 'not set'}")
    print(f"  Gemini: {'configured' if 'google_key' in keys else 'not set'}")
    print(f"  GPT: {'configured' if 'openai_key' in keys else 'not set'}")
    print(f"  OpenRouter: {'configured' if 'openrouter_key' in keys else 'not set'}")
    print(f"  DeepSeek: configured")
    print(f"  Agent: {'loaded' if HAS_AGENT else 'not loaded'}")
    print(f"  Notify: {'loaded' if HAS_NOTIFY else 'not loaded'}")
    print(f"  Web: http://localhost:5001")
    print(f"  Cost Tracker: {'loaded' if HAS_COST else 'not loaded'}")
    print(f"  Templates: {'loaded' if HAS_TEMPLATES else 'not loaded'}")
    print(f"  Audit: {'loaded' if HAS_AUDIT else 'not loaded'}")
    print("=" * 50)
    # 启动健康监控
    try:
        from health_monitor import start_health_monitor
        start_health_monitor()
        print("  Health Monitor: started")
    except Exception as e:
        print(f"  Health Monitor: {e}")
    uvicorn.run(app, host="0.0.0.0", port=5001, log_level="warning")
