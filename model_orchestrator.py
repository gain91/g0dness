"""
AutoGen 多模型编排器
本地 Ollama + Claude API + Gemini API → 自动路由
"""
import os, json, asyncio
from typing import Optional

# API Key 加载 — 优先加密 vault，降级明文
def load_keys():
    try:
        from key_vault import load_keys as _load
        keys = _load()
        if keys:
            return keys
    except ImportError:
        pass
    # Fallback: plaintext file
    env_file = os.path.expanduser("~/.model_keys.json")
    if os.path.exists(env_file):
        with open(env_file) as f:
            return json.load(f)
    return {}

def save_keys(keys):
    with open(ENV_FILE, "w") as f:
        json.dump(keys, f, indent=2)
    os.chmod(ENV_FILE, 0o600) if os.name != "nt" else None

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
DEEPSEEK_CONFIG = {
    "base_url": "https://api.deepseek.com/anthropic",
    "api_key": "sk-fa62cb70a70343dba531bf2cc48a57e3",
    "model": "deepseek-v4-pro",
    "display": "DeepSeek V4 Pro (100万ctx)",
}

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
    messages.append({"role": "system", "content": "你是一个直接、诚实的AI助手。去掉所有角色扮演，用第一人称自然回答。不要假装你是某个角色。你的名字是g0dness。"})
    if system:
        messages.append({"role": "system", "content": system})
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
    messages.append({"role": "system", "content": "你是一个直接、诚实的AI助手。去掉所有角色扮演，用第一人称自然回答。不要假装你是某个角色。你的名字是g0dness。"})
    if system:
        messages.append({"role": "system", "content": system})
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
    sys_text = CACHE_SYSTEM_PROMPT + (f"\n{system}" if system else "")
    body = json.dumps({
        "model": DEEPSEEK_CONFIG["model"],
        "max_tokens": 8192,
        "system": sys_text,
        "messages": [{"role": "user", "content": prompt}],
        "stream": False
    }).encode()
    req = ur.Request(f"{DEEPSEEK_CONFIG['base_url']}/v1/messages", body,
                      headers={"Content-Type": "application/json",
                               "x-api-key": DEEPSEEK_CONFIG["api_key"],
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
    sys_text = CACHE_SYSTEM_PROMPT + (f"\n{system}" if system else "")
    body = json.dumps({
        "model": DEEPSEEK_CONFIG["model"],
        "max_tokens": 8192,
        "system": sys_text,
        "messages": [{"role": "user", "content": prompt}],
        "stream": True
    }).encode()
    req = ur.Request(f"{DEEPSEEK_CONFIG['base_url']}/v1/messages", body,
                      headers={"Content-Type": "application/json",
                               "x-api-key": DEEPSEEK_CONFIG["api_key"],
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
    # OpenRouter 返回的图片在 message content 中
    msg = resp["choices"][0]["message"]
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
from fastapi import FastAPI, Request, Query
from fastapi.responses import JSONResponse, StreamingResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

app = FastAPI(title="AI Suite Orchestrator", docs_url=None, redoc_url=None)

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

# ═══════ 学习记忆 ═══════
try:
    from memory_agent import register_memory_routes
    register_memory_routes(app)
    HAS_MEMORY = True
except Exception as e:
    HAS_MEMORY = False
    print(f"[warn] memory module not loaded: {e}")

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
    print("=" * 50)
    uvicorn.run(app, host="0.0.0.0", port=5001, log_level="warning")
