"""
Flask 文生图 Web 前端 — 自然语言输入 → 自动生图
启动: python gen_web.py
打开: http://localhost:5000
"""
import json, os, sys, time, shutil, subprocess, threading, uuid
import urllib.request, urllib.error
from fastapi import FastAPI, Request, UploadFile, File, WebSocket
from fastapi.responses import JSONResponse, FileResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from auth_middleware import AuthMiddleware, AUTH_TOKEN as _AUTH_TOKEN
from logger import get_logger
_log = get_logger("gen_web")

# PyInstaller frozen 环境下 sys.executable 是 EXE 自身，不能用来 spawn 子进程
def _get_real_python():
    if getattr(sys, 'frozen', False):
        for n in ['python', 'python3', 'py']:
            found = shutil.which(n)
            if found:
                return found
        for ver in ['312', '311', '310', '313']:
            p = f'C:/Python{ver}/python.exe'
            if os.path.exists(p):
                return p
        p = os.path.expandvars(f'%LOCALAPPDATA%\\Programs\\Python\\Python312\\python.exe')
        if os.path.exists(p):
            return p
    return sys.executable

app = FastAPI(title="AI Suite Gen Web", docs_url=None, redoc_url=None)
app.add_middleware(AuthMiddleware)
_log.info("gen_web starting on port 5000")

app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"],
    allow_headers=["*"], allow_credentials=True,
)

COMFYUI_DIR = "C:/Users/86538/ComfyUI"
COMFYUI_URL = "http://127.0.0.1:8188"
OUTPUT_DIR = "C:/Users/86538/Downloads/generated"
MODEL = "sd_xl_base_1.0.safetensors"
STEPS, CFG, WIDTH, HEIGHT = 25, 7.0, 1024, 1024

os.makedirs(OUTPUT_DIR, exist_ok=True)
os.makedirs("static", exist_ok=True)

# 全局状态
state = {"status": "idle", "message": "", "image": None, "prompt_id": None, "positive": "", "negative": "", "seed": None}
comfyui_proc = None

# ═══════════════ 核心逻辑 ═══════════════

def ollama_chat(messages: list) -> str:
    req = json.dumps({"model": "lingmo-uncensored", "messages": messages,
                       "stream": False, "format": "json"}).encode()
    resp = urllib.request.urlopen(
        urllib.request.Request("http://localhost:11434/api/chat", req), timeout=120)
    return json.loads(resp.read())["message"]["content"]

DEFAULT_NEG = "lowres, worst quality, bad quality, jpeg artifacts, sketch, monochrome, watermark, signature, text"

def enhance_prompt(user_input: str) -> tuple:
    """Try Ollama, fallback to template if unavailable"""
    # Try Ollama first
    try:
        urllib.request.urlopen("http://localhost:11434/api/tags", timeout=1)
        sys_msg = """You are an expert SDXL prompt engineer. Convert user description into JSON:
{"positive": "...detailed English prompt with quality tags...", "negative": "...quality issues to avoid..."}
Include masterpiece, best quality, highly detailed, 8k. Describe faithfully."""
        result = json.loads(ollama_chat([
            {"role": "system", "content": sys_msg},
            {"role": "user", "content": user_input}
        ]))
        return result["positive"], result.get("negative", DEFAULT_NEG)
    except:
        pass
    # Template fallback (when ComfyUI is running, Ollama is off)
    return (f"masterpiece, best quality, highly detailed, 8k, photorealistic, {user_input}",
            DEFAULT_NEG)

def comfyui_ready() -> bool:
    try:
        urllib.request.urlopen(f"{COMFYUI_URL}/system_stats", timeout=2)
        return True
    except:
        return False

def start_comfyui():
    global comfyui_proc
    if comfyui_ready():
        return
    # 硬件检测：VRAM 不足 8GB 则拒绝启动
    try:
        from hw_monitor import can_start_comfyui
        if not can_start_comfyui():
            raise RuntimeError("VRAM 不足，无法启动 ComfyUI。请关闭其他应用后重试。")
    except ImportError: pass
    # Kill Ollama to free VRAM
    subprocess.run(["taskkill", "/f", "/im", "ollama.exe"], capture_output=True,
                   creationflags=subprocess.CREATE_NO_WINDOW)
    time.sleep(2)
    comfyui_proc = subprocess.Popen([_get_real_python(), "main.py"], cwd=COMFYUI_DIR,
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                     creationflags=subprocess.CREATE_NO_WINDOW)
    for _ in range(60):
        if comfyui_ready():
            return
        time.sleep(2)
    raise RuntimeError("ComfyUI startup timeout")

def submit_workflow(positive, negative, seed):
    workflow = {
        "4": {"class_type": "CheckpointLoaderSimple", "inputs": {"ckpt_name": MODEL}},
        "6": {"class_type": "CLIPTextEncode", "inputs": {"text": positive, "clip": ["4", 1]}},
        "7": {"class_type": "CLIPTextEncode", "inputs": {"text": negative, "clip": ["4", 1]}},
        "5": {"class_type": "EmptyLatentImage", "inputs": {"width": WIDTH, "height": HEIGHT, "batch_size": 1}},
        "3": {"class_type": "KSampler", "inputs": {"seed": seed, "steps": STEPS, "cfg": CFG,
                "sampler_name": "dpmpp_2m", "scheduler": "karras", "denoise": 1.0,
                "model": ["4", 0], "positive": ["6", 0], "negative": ["7", 0], "latent_image": ["5", 0]}},
        "8": {"class_type": "VAEDecode", "inputs": {"samples": ["3", 0], "vae": ["4", 2]}},
        "9": {"class_type": "SaveImage", "inputs": {"filename_prefix": "gen", "images": ["8", 0]}}
    }
    payload = json.dumps({"prompt": workflow}).encode()
    resp = urllib.request.Request(f"{COMFYUI_URL}/prompt", payload,
                                   headers={"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(resp).read())["prompt_id"]

def poll_result(prompt_id, max_retries=150, timeout_sec=300):
    """轮询直到生图完成，返回图片路径。最多150次(5分钟)，超时退出"""
    import time as _t
    start = _t.time()
    retries = 0
    while retries < max_retries:
        try:
            if _t.time() - start > timeout_sec:
                return None  # 超时
            history = json.loads(
                urllib.request.urlopen(f"{COMFYUI_URL}/history/{prompt_id}", timeout=10).read())
            if prompt_id in history:
                outputs = history[prompt_id]["outputs"]
                if "9" in outputs:
                    img = outputs["9"]["images"][0]
                    src = os.path.join(COMFYUI_DIR, "output", img["subfolder"], img["filename"])
                    dst = os.path.join(OUTPUT_DIR, img["filename"])
                    shutil.copy2(src, dst)
                    return f"/output/{img['filename']}"
            time.sleep(2)
            retries += 1
        except Exception:
            time.sleep(2)
            retries += 1
    return None  # 超过最大重试次数


def generate_worker(user_input: str):
    """后台生成线程"""
    global state
    try:
        state["status"] = "enhancing"
        state["message"] = "Ollama 增强提示词..."
        positive, negative = enhance_prompt(user_input)
        state["positive"] = positive
        state["negative"] = negative

        state["status"] = "switching"
        state["message"] = "切换到 ComfyUI..."
        start_comfyui()

        state["status"] = "generating"
        state["message"] = "生成图片中..."
        seed = int(time.time())
        state["seed"] = seed
        prompt_id = submit_workflow(positive, negative, seed)
        state["prompt_id"] = prompt_id

        img_url = poll_result(prompt_id)
        state["status"] = "done"
        state["message"] = "生成完成！"
        state["image"] = img_url
    except Exception as e:
        state["status"] = "error"
        state["message"] = str(e)

video_state = {"status": "idle", "message": "", "frames": [], "image": None}

# ═══════════════ Image API ═══════════════

@app.post("/api/generate")
async def api_generate(request: Request):
    global state
    old_status = state.get("status", "idle")
    if old_status in ("enhancing", "switching", "generating"):
        return JSONResponse({"error": "正在生成中，请等待..."}, 400)
    data = await request.json()
    user_input = data.get("prompt", "").strip()
    if not user_input:
        return JSONResponse({"error": "请输入描述"}, 400)
    # 使用 clear+update 避免线程间引用丢失
    state.clear()
    state.update({"status": "starting", "message": "", "image": None,
                  "positive": "", "negative": "", "seed": None, "prompt_id": None})
    threading.Thread(target=generate_worker, args=(user_input,), daemon=True).start()
    return {"ok": True}

@app.get("/api/status")
async def api_status():
    return {k: state[k] for k in ["status", "message", "image", "positive", "negative", "seed"]}

# ═══════════════ Volcengine Video ═══════════════
VOLC_VIDEO_MODELS = {
    "seedance": "doubao-seedance-2-0-260128",
    "wan_i2v": "wan2-1-14b-i2v-250225",
}

VOLC_IMAGE_MODELS = {
    # 优先使用 .model_keys.json 中的 volcengine_endpoint_id (ep-xxx)
    "seedream5": "doubao-seedream-5-0-260128",
}

def volc_image_gen(prompt, model_key="seedream5"):
    """Seedream 图像生成

    优先使用 .model_keys.json 中的 volcengine_endpoint_id (ep-xxx 格式)，
    因为火山方舟现在要求推理接入点 ID，直接传模型名返回 404。
    """
    import urllib.request as ur
    keys_path = "C:/Users/86538/.model_keys.json"
    with open(keys_path) as f:
        keys = json.load(f)
    api_key = keys.get("volcengine_key", "")
    if not api_key:
        return None, "Volcengine key not set"

    # 优先用 endpoint_id，fallback 到模型名称
    model = keys.get("volcengine_endpoint_id") or VOLC_IMAGE_MODELS.get(model_key, VOLC_IMAGE_MODELS["seedream5"])

    body = json.dumps({
        "model": model,
        "prompt": prompt,
        "n": 1
    }).encode()
    req = ur.Request(
        "https://ark.cn-beijing.volces.com/api/v3/images/generations",
        body,
        headers={"Content-Type": "application/json",
                  "Authorization": f"Bearer {api_key}"}
    )
    resp = json.loads(ur.urlopen(req, timeout=60).read())
    img_url = resp.get("data", [{}])[0].get("url", "")
    if img_url:
        fname = f"seedream_{int(time.time())}.png"
        local_path = os.path.join(OUTPUT_DIR, fname)
        ur.urlretrieve(img_url, local_path)
        # 费用追踪
        try:
            from cost_tracker import track_image
            track_image(model, 1)
        except Exception:
            pass
        return f"/output/{fname}", None
    return None, "No image in response"

def volc_video_create(prompt, model_key="seedance", image_url=None, ratio="16:9", duration=5):
    """创建火山引擎视频任务，返回 task_id"""
    import urllib.request as ur
    keys_path = "C:/Users/86538/.model_keys.json"
    with open(keys_path) as f:
        keys = json.load(f)
    api_key = keys.get("volcengine_key", "")
    if not api_key:
        return None, "Volcengine key not set"

    # 视频专用 endpoint_id，不用生图的
    model = keys.get("volcengine_video_endpoint_id", "ep-20260616203500-hdrsf")

    content = [{"type": "text", "text": prompt}]
    if image_url:
        content.append({
            "type": "image_url",
            "image_url": {"url": image_url},
            "role": "reference_image"
        })

    body_dict = {
        "model": model,
        "content": content,
        "ratio": ratio,
        "duration": duration,
        "watermark": False,
    }
    body = json.dumps(body_dict).encode()
    req = ur.Request(
        "https://ark.cn-beijing.volces.com/api/v3/contents/generations/tasks",
        body,
        headers={"Content-Type": "application/json",
                  "Authorization": f"Bearer {api_key}"}
    )
    resp = json.loads(ur.urlopen(req, timeout=30).read())
    if "error" in resp:
        return None, resp["error"].get("message", str(resp["error"]))
    return resp.get("id"), None

def volc_video_poll(task_id):
    """轮询视频任务，返回视频 URL"""
    import urllib.request as ur
    keys_path = "C:/Users/86538/.model_keys.json"
    with open(keys_path) as f:
        keys = json.load(f)
    api_key = keys.get("volcengine_key", "")

    for _ in range(120):  # max 10 min
        time.sleep(5)
        req = ur.Request(
            f"https://ark.cn-beijing.volces.com/api/v3/contents/generations/tasks/{task_id}",
            headers={"Authorization": f"Bearer {api_key}"}
        )
        resp = json.loads(ur.urlopen(req, timeout=15).read())
        status = resp.get("status", "")
        if status in ("completed", "succeeded"):
            vurl = resp.get("content", {}).get("video_url", "") or resp.get("video_url", "") or resp.get("url", "")
            return vurl, None
        elif status in ("failed", "cancelled", "error"):
            return None, f"Video generation {status}: {resp}"
    return None, "Timeout after 10 min"

# ═══════════════ OpenRouter Image ═══════════════
def or_image_gen(prompt, provider="openai"):
    import urllib.request as ur
    keys_path = "C:/Users/86538/.model_keys.json"
    if not os.path.exists(keys_path):
        return None, "No API keys configured"
    with open(keys_path) as f:
        keys = json.load(f)
    api_key = keys.get("openrouter_key")
    if not api_key:
        return None, "OpenRouter key not set"
    models = {"openai": "openai/gpt-5.4-image-2", "gemini": "google/gemini-3.1-flash-image-preview"}
    model = models.get(provider, models["openai"])
    body = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "modalities": ["image", "text"],
    }).encode()
    req = ur.Request("https://openrouter.ai/api/v1/chat/completions", body,
                     headers={"Content-Type": "application/json",
                              "Authorization": f"Bearer {api_key}",
                              "HTTP-Referer": "http://localhost:5000"})
    resp = json.loads(ur.urlopen(req, timeout=180).read())
    msg = resp["choices"][0]["message"]
    # GPT-5.4-image 返回在 images 字段
    images = msg.get("images", [])
    if images:
        return images[0]["image_url"]["url"], None
    # Gemini 可能在 content 列表里
    content = msg.get("content", "")
    if isinstance(content, list):
        for part in content:
            if part.get("type") == "image_url":
                return part["image_url"]["url"], None
    elif isinstance(content, str) and content.startswith("data:image"):
        return content, None
    return str(content)[:200] if content else "No image returned", None

@app.post("/api/seedream")
async def api_seedream(request: Request):
    data = await request.json()
    prompt = data.get("prompt", "").strip()
    model = data.get("model", "seedream5")
    if not prompt: return JSONResponse({"error": "empty prompt"}, 400)
    try:
        url, err = volc_image_gen(prompt, model)
        if err: return JSONResponse({"ok": False, "error": err}, 500)
        return {"ok": True, "image": url, "provider": model}
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, 500)

@app.post("/api/or_image")
async def api_or_image(request: Request):
    data = await request.json()
    prompt = data.get("prompt", "").strip()
    provider = data.get("provider", "openai")
    if not prompt: return JSONResponse({"error": "empty prompt"}, 400)
    try:
        url, err = or_image_gen(prompt, provider)
        if err: return JSONResponse({"ok": False, "error": err}, 500)
        return {"ok": True, "image": url, "provider": provider}
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, 500)

# ═══════════════ Video API ═══════════════

@app.post("/api/generate_video")
async def api_generate_video(request: Request):
    global video_state
    if video_state["status"] in ("creating", "generating"):
        return JSONResponse({"error": "正在生成视频中，请等待..."}, 400)
    data = await request.json()
    user_input = data.get("prompt", "").strip()
    model = data.get("model", "seedance")
    image_url = data.get("image_url")
    ratio = data.get("ratio", "16:9")
    duration = data.get("duration", 5)
    if not user_input: return JSONResponse({"error": "请输入描述"}, 400)
    video_state = {"status": "creating", "message": "创建视频任务...", "url": None, "task_id": None}
    threading.Thread(target=volc_video_worker, args=(user_input, model, image_url, ratio, duration), daemon=True).start()
    return {"ok": True}

@app.get("/api/video_status")
async def api_video_status():
    return video_state

def volc_video_worker(prompt, model, image_url=None, ratio="16:9", duration=5):
    global video_state
    try:
        task_id, err = volc_video_create(prompt, model, image_url, ratio, duration)
        if err:
            video_state["status"] = "error"; video_state["message"] = err; return
        video_state["task_id"] = task_id
        video_state["status"] = "generating"
        video_state["message"] = "云端生成中..."
        url, err = volc_video_poll(task_id)
        if err:
            video_state["status"] = "error"; video_state["message"] = err; return
        video_state["status"] = "done"
        video_state["url"] = url
        video_state["message"] = "视频完成！"
    except Exception as e:
        video_state["status"] = "error"
        video_state["message"] = str(e)

@app.get("/api/comfyui_status")
async def api_comfyui_status():
    return {"running": comfyui_ready()}

@app.get("/api/ollama_status")
async def api_ollama_status():
    try:
        urllib.request.urlopen("http://localhost:11434/api/tags", timeout=2)
        return {"running": True}
    except:
        return {"running": False}

@app.get("/api/switch_to_ollama")
async def api_switch_to_ollama():
    global state, comfyui_proc
    state["status"] = "switching_ollama"
    state["message"] = "切换到 Ollama..."
    if comfyui_proc:
        try: comfyui_proc.terminate(); comfyui_proc.wait(timeout=5)
        except: comfyui_proc.kill()
        comfyui_proc = None
    time.sleep(2)
    subprocess.Popen(["ollama", "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     creationflags=subprocess.CREATE_NO_WINDOW)
    for _ in range(15):
        try:
            urllib.request.urlopen("http://localhost:11434/api/tags", timeout=2)
            state = {"status": "idle", "message": "", "image": None, "positive": "", "negative": "", "seed": None, "prompt_id": None}
            return {"ok": True}
        except: time.sleep(1)
    state["status"] = "idle"; state["message"] = "Ollama 启动超时"
    return JSONResponse({"ok": False, "error": "Ollama 启动超时"})

@app.get("/output/{filename}")
async def serve_image(filename: str):
    # block path traversal
    if '..' in filename or '/' in filename or '\\' in filename:
        return JSONResponse({"error": "invalid path"}, 400)
    return FileResponse(os.path.join(OUTPUT_DIR, filename))

@app.get("/api/history")
async def api_history():
    files = []
    if os.path.exists(OUTPUT_DIR):
        for f in sorted(os.listdir(OUTPUT_DIR), reverse=True):
            path = os.path.join(OUTPUT_DIR, f)
            if os.path.isfile(path):
                sz = os.path.getsize(path); mt = os.path.getmtime(path)
                files.append({"name": f, "url": f"/output/{f}", "size": sz,
                    "size_str": f"{sz/1024:.0f}KB" if sz<1024*1024 else f"{sz/1024/1024:.1f}MB",
                    "time": time.strftime("%m-%d %H:%M", time.localtime(mt)),
                    "type": "video" if f.endswith('.mp4') else "image"})
    return {"files": files, "folder": OUTPUT_DIR}

@app.get("/api/open_folder")
async def api_open_folder():
    os.startfile(OUTPUT_DIR); return {"ok": True}

@app.get("/api/hw_status")
async def api_hw_status():
    try:
        import psutil
        mem = psutil.virtual_memory()
        ram = round(mem.available / (1024**3), 1)
        from hw_monitor import get_free_vram_gb, get_tier, can_start_comfyui
        return {"free_ram_gb": ram, "free_vram_gb": get_free_vram_gb(),
                "tier": get_tier(), "comfyui_ok": can_start_comfyui()}
    except:
        return {"free_ram_gb": 8, "free_vram_gb": 12, "tier": "medium", "comfyui_ok": True}

@app.get("/api/lan_qr")
async def api_lan_qr():
    """返回局域网访问 URL 和二维码"""
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
    except:
        ip = "127.0.0.1"
    url = f"http://{ip}:5000/mobile"
    qr_url = f"https://api.qrserver.com/v1/create-qr-code/?size=200x200&data={url}"
    return {"ok": True, "url": url, "qr_url": qr_url, "ip": ip}

MOBILE_HTML = r"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1,user-scalable=no">
<title>AI Suite · 手机遥控</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,sans-serif;background:#1a1a2e;color:#e0e0e0;height:100vh;display:flex;flex-direction:column}
.header{background:#16213e;padding:12px;display:flex;gap:6px;align-items:center}
.header h1{font-size:16px;background:linear-gradient(135deg,#a78bfa,#f472b6);-webkit-background-clip:text;-webkit-text-fill-color:transparent;flex:1}
.header select{background:#0f3460;color:#e0e0e0;border:1px solid #533483;padding:6px;border-radius:6px;font-size:12px}
.tabs{display:flex;gap:4px;padding:8px 12px}
.tab{padding:8px 16px;border:none;border-radius:8px;font-size:13px;cursor:pointer;background:#0f3460;color:#888}
.tab.active{background:#533483;color:#fff}
.chat{flex:1;overflow-y:auto;padding:12px;display:flex;flex-direction:column;gap:10px}
.msg{padding:10px 14px;border-radius:12px;max-width:90%;line-height:1.5;font-size:14px;word-break:break-word}
.msg.user{align-self:flex-end;background:#533483;color:#fff}
.msg.assistant{align-self:flex-start;background:#16213e;border:1px solid #333}
.msg .role{font-size:10px;opacity:.5;margin-bottom:3px}
.input-area{display:flex;gap:8px;padding:12px;background:#16213e;border-top:1px solid #333}
.input-area textarea{flex:1;background:#0f3460;color:#e0e0e0;border:1px solid #533483;border-radius:8px;padding:10px;font-size:14px;resize:none;min-height:44px;max-height:100px;font-family:inherit;outline:none}
.input-area button{background:#a78bfa;color:#fff;border:none;padding:10px 16px;border-radius:8px;font-size:14px;font-weight:bold}
.status{text-align:center;font-size:11px;color:#666;padding:4px}
.spinner{width:20px;height:20px;border:2px solid #333;border-top-color:#a78bfa;border-radius:50%;animation:spin .7s linear infinite;display:inline-block;vertical-align:middle;margin-right:6px}
@keyframes spin{to{transform:rotate(360deg)}}
.tool-log{font-size:11px;color:#a78bfa;padding:4px 8px;background:rgba(167,139,250,.1);border-radius:4px;margin:2px 0}
</style>
</head>
<body>
<div class="header">
  <h1>🤖 AI Suite</h1>
  <select id="modelSel" onchange="switchModel()">
    <option value="deepseek">DeepSeek V4</option>
    <option value="ollama:qwen3:8b">Qwen3 本地</option>
    <option value="ollama:deepseek-r1:14b">DeepSeek-R1 本地</option>
    <option value="claude">Claude 云端</option>
    <option value="gemini">Gemini 云端</option>
  </select>
</div>
<div class="tabs">
  <button class="tab active" onclick="switchTab('chat')">💬 对话</button>
  <button class="tab" onclick="switchTab('agent')">🤖 Agent</button>
</div>
<div class="chat" id="chatLog"></div>
<div class="status" id="status">就绪</div>
<div class="input-area">
  <textarea id="input" placeholder="输入内容..." rows="1"></textarea>
  <button id="sendBtn" onclick="send()">发送</button>
</div>
<script>
const ORCH = window.location.protocol + '//' + window.location.hostname + ':5001';
let mode = 'chat', model = 'deepseek';

function switchTab(t) {
  mode = t;
  document.querySelectorAll('.tab').forEach((b,i) => b.classList.toggle('active', (i===0&&t==='chat')||(i===1&&t==='agent')));
  document.getElementById('input').placeholder = t==='agent' ? '输入任务，Agent 自动执行...' : '输入内容...';
}

function switchModel() { model = document.getElementById('modelSel').value; }

function addMsg(role, text) {
  let div = document.createElement('div');
  div.className = 'msg ' + role;
  div.innerHTML = '<div class="role">' + (role==='user'?'你':role==='agent'?'🤖Agent':'g0dness') + '</div>' + text.replace(/</g,'&lt;');
  document.getElementById('chatLog').appendChild(div);
  div.scrollIntoView({behavior:'smooth'});
  return div;
}

async function send() {
  let input = document.getElementById('input'), text = input.value.trim();
  if (!text) return;
  input.value = ''; document.getElementById('sendBtn').disabled = true;
  document.getElementById('status').innerHTML = '<span class="spinner"></span>处理中...';

  addMsg('user', text);

  if (mode === 'agent') {
    try {
      let r = await fetch(ORCH + '/api/agent/stream', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({task: text, model: model})
      });
      let div = addMsg('agent', '');
      let full = '', tools = [];
      let reader = r.body.getReader(), decoder = new TextDecoder(), buf = '';
      while (true) {
        let {done, value} = await reader.read();
        if (done) break;
        buf += decoder.decode(value, {stream: true});
        let lines = buf.split('\n'); buf = lines.pop();
        for (let line of lines) {
          if (!line.startsWith('data: ') || line === 'data: [DONE]') continue;
          try {
            let evt = JSON.parse(line.slice(6));
            if (evt.type === 'thinking') { full = evt.text; }
            else if (evt.type === 'tool_call') { tools.push('🔧 ' + evt.tool); }
            else if (evt.type === 'tool_result') { tools.push((evt.result?.ok?'✅':'❌') + ' ' + evt.tool); }
            else if (evt.type === 'done') { full = evt.text || full; }
            div.innerHTML = '<div class="role">🤖Agent</div>' + (full||'...').replace(/</g,'&lt;');
            if (tools.length) div.innerHTML += '<div class="tool-log">' + tools.join(' · ') + '</div>';
          } catch(e) {}
        }
      }
    } catch(e) { addMsg('assistant', '错误: ' + e.message); }
  } else {
    try {
      let r = await fetch(ORCH + '/api/chat/stream', {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({prompt: text, model: model})
      });
      let div = addMsg('assistant', '');
      let full = '';
      let reader = r.body.getReader(), decoder = new TextDecoder(), buf = '';
      while (true) {
        let {done, value} = await reader.read();
        if (done) break;
        buf += decoder.decode(value, {stream: true});
        let lines = buf.split('\n'); buf = lines.pop();
        for (let line of lines) {
          if (!line.startsWith('data: ') || line === 'data: [DONE]') continue;
          try {
            let d = JSON.parse(line.slice(6));
            if (d.token) { full += d.token; div.innerHTML = '<div class="role">g0dness</div>' + full.replace(/</g,'&lt;'); }
          } catch(e) {}
        }
      }
    } catch(e) { addMsg('assistant', '错误: ' + e.message); }
  }
  document.getElementById('sendBtn').disabled = false;
  document.getElementById('status').textContent = '就绪';
}

document.getElementById('input').addEventListener('keydown', function(e) {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); }
});
</script>
</body>
</html>"""

@app.get("/mobile")
async def mobile():
    return HTMLResponse(MOBILE_HTML)

@app.get("/qr")
async def qr_page():
    """独立 QR 页面"""
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
    except:
        ip = "127.0.0.1"
    url = f"http://{ip}:5000/mobile"
    qr = f"https://api.qrserver.com/v1/create-qr-code/?size=250x250&data={url}"
    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="zh"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>AI Suite · 扫码遥控</title>
<style>
*{{margin:0;padding:0;box-sizing:border-box}}
body{{font-family:-apple-system,sans-serif;background:#1a1a2e;color:#e0e0e0;display:flex;justify-content:center;align-items:center;height:100vh;flex-direction:column}}
img{{border-radius:16px;background:#fff;padding:8px}}
h2{{font-size:18px;margin-bottom:16px;background:linear-gradient(135deg,#a78bfa,#f472b6);-webkit-background-clip:text;-webkit-text-fill-color:transparent}}
p{{color:#888;font-size:12px;margin-top:12px;word-break:break-all;text-align:center;max-width:300px}}
</style></head>
<body>
<h2>📱 手机扫码遥控</h2>
<img src="{qr}" width="250" height="250" alt="QR">
<p>{url}</p>
<p style="color:#666;margin-top:8px">同一 WiFi 下扫码即可</p>
</body></html>""")

@app.post("/api/autostart")
async def api_autostart(request: Request):
    """开关开机自启"""
    data = await request.json()
    enable = data.get("enable", False)
    import win32com.client
    startup_dir = os.path.join(os.environ["APPDATA"],
        "Microsoft\\Windows\\Start Menu\\Programs\\Startup")
    shortcut_path = os.path.join(startup_dir, "AI_Suite.lnk")
    if enable:
        # v3.0: 指向 Tauri EXE
        exe_dir = os.path.dirname(os.path.abspath(__file__))
        tauri_exe = os.path.join(exe_dir, "AI_Suite", "AI_Suite.exe")
        if not os.path.exists(tauri_exe):
            # Fallback to old pywebview launcher
            tauri_exe = os.path.join(exe_dir, "AI_Suite", "AI_Suite.exe.old")
        shell = win32com.client.Dispatch("WScript.Shell")
        shortcut = shell.CreateShortcut(shortcut_path)
        shortcut.TargetPath = tauri_exe
        shortcut.WorkingDirectory = exe_dir
        shortcut.save()
    else:
        if os.path.exists(shortcut_path):
            os.remove(shortcut_path)
    return {"ok": True, "enabled": enable}

@app.get("/api/open_claude")
async def api_open_claude():
    subprocess.Popen(["cmd","/c","start","claude"], cwd=os.path.expanduser("~"))
    return {"ok": True}

@app.get("/api/open_codex")
async def api_open_codex():
    subprocess.Popen(["cmd","/c","start","codex"], cwd=os.path.expanduser("~"))
    return {"ok": True}

UPLOAD_DIR = os.path.join(OUTPUT_DIR, "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

@app.post("/api/upload")
async def api_upload(file: UploadFile = File(...)):
    # 🔴 fix: path traversal — use basename only, reject None filename
    if not file.filename:
        return JSONResponse({"error": "filename required"}, 400)
    safe_name = f"{int(time.time())}_{os.path.basename(file.filename)}"
    path = os.path.join(UPLOAD_DIR, safe_name)
    # Extra safeguard: ensure resolved path stays within UPLOAD_DIR
    if not os.path.abspath(path).startswith(os.path.abspath(UPLOAD_DIR)):
        return JSONResponse({"error": "invalid filename"}, 400)
    content = await file.read()
    with open(path, "wb") as f: f.write(content)
    result = {"ok": True, "url": f"/output/uploads/{safe_name}", "name": safe_name, "type": "file"}
    ext = os.path.splitext(file.filename)[1].lower()
    text = ""
    try:
        if ext == ".pdf":
            from PyPDF2 import PdfReader
            reader = PdfReader(path)
            text = "\n".join([p.extract_text() or "" for p in reader.pages[:50]])
        elif ext in (".docx", ".doc"):
            from docx import Document
            doc = Document(path)
            text = "\n".join([p.text for p in doc.paragraphs])
    except Exception as e:
        text = f"[解析失败: {e}]"
    if text:
        result["text"] = text[:10000]; result["type"] = "document"
    return result

@app.get("/output/uploads/{filename}")
async def serve_upload(filename: str):
    if '..' in filename or '/' in filename or '\\' in filename:
        return JSONResponse({"error": "invalid path"}, 400)
    return FileResponse(os.path.join(UPLOAD_DIR, filename))

# ═══════════════ 前端 ═══════════════

CHAT_HTML_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ollama-chat.html")

@app.get("/")
async def index():
    return HTMLResponse(HTML)

@app.get("/chat")
async def chat():
    with open(CHAT_HTML_PATH, encoding="utf-8") as f:
        return HTMLResponse(f.read())

HTML = r"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>🎨 AI 自动生图</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
  background:#0f0f0f;color:#e0e0e0;min-height:100vh;display:flex;flex-direction:column;align-items:center}
.container{max-width:900px;width:100%;padding:20px}
h1{text-align:center;margin:20px 0;font-size:28px;background:linear-gradient(135deg,#a78bfa,#f472b6);
  -webkit-background-clip:text;-webkit-text-fill-color:transparent}
.status-bar{display:flex;gap:10px;justify-content:center;margin-bottom:20px}
.status-dot{display:inline-block;width:10px;height:10px;border-radius:50%}
.status-item{font-size:13px;padding:6px 14px;border-radius:20px;background:#1a1a1a;
  display:flex;align-items:center;gap:6px}
.status-item.on .status-dot{background:#10b981;box-shadow:0 0 6px #10b981}
.status-item.off .status-dot{background:#ef4444}
.card{background:#1a1a1a;border-radius:16px;padding:24px;margin-bottom:16px;border:1px solid #2a2a2a}
.prompt-area{width:100%;background:#0f0f0f;border:1px solid #333;border-radius:12px;
  color:#e0e0e0;padding:14px;font-size:15px;resize:vertical;min-height:80px;
  outline:none;transition:border .3s}
.prompt-area:focus{border-color:#a78bfa}
.btn{display:inline-flex;align-items:center;gap:8px;padding:12px 28px;border-radius:25px;
  font-size:15px;font-weight:600;cursor:pointer;border:none;transition:.2s}
.btn-primary{background:linear-gradient(135deg,#a78bfa,#f472b6);color:#fff;width:100%;
  justify-content:center;margin-top:12px}
.btn-primary:hover{transform:translateY(-1px);box-shadow:0 4px 20px rgba(167,139,250,.3)}
.btn-primary:disabled{opacity:.5;cursor:not-allowed;transform:none}
.progress{text-align:center;padding:30px}
.progress .spinner{width:40px;height:40px;border:3px solid #333;border-top-color:#a78bfa;
  border-radius:50%;animation:spin .8s linear infinite;margin:0 auto 16px}
@keyframes spin{to{transform:rotate(360deg)}}
.result-img{width:100%;border-radius:12px;margin-top:12px}
.prompt-box{background:#0f0f0f;border-radius:8px;padding:12px;margin:8px 0;font-size:13px;
  color:#aaa;max-height:100px;overflow-y:auto}
.prompt-box span{color:#a78bfa}
</style>
</head>
<body>
<div class="container">
  <h1>🎨 自然语言 → AI 生图</h1>

  <div class="status-bar" id="statusBar">
    <div class="status-item off" id="ollamaStatus">
      <span class="status-dot"></span> Ollama
    </div>
    <div class="status-item off" id="comfyuiStatus">
      <span class="status-dot"></span> ComfyUI
    </div>
  </div>

  <div class="card">
    <textarea class="prompt-area" id="promptInput"
      placeholder="输入你想生成的画面，任意自然语言...&#10;例如：一只橘猫坐在云朵上，星空背景，宫崎骏风格"></textarea>
    <button class="btn btn-primary" id="genBtn" onclick="generate()">
      ✨ 一键生图
    </button>
  </div>

  <div id="resultArea"></div>
</div>

<script>
let polling = null;

async function checkStatus() {
  try {
    let r = await fetch('/api/ollama_status');
    let o = await r.json();
    document.getElementById('ollamaStatus').className = 'status-item ' + (o.running?'on':'off');
    r = await fetch('/api/comfyui_status');
    let c = await r.json();
    document.getElementById('comfyuiStatus').className = 'status-item ' + (c.running?'on':'off');
  } catch(e) {}
}
checkStatus(); setInterval(checkStatus, 5000);

async function generate() {
  const input = document.getElementById('promptInput').value.trim();
  if (!input) return alert('请输入描述');
  const btn = document.getElementById('genBtn');
  btn.disabled = true;
  btn.textContent = '⏳ 准备中...';
  document.getElementById('resultArea').innerHTML = '';

  try {
    let r = await fetch('/api/generate', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({prompt: input})
    });
    if (!r.ok) { alert((await r.json()).error); btn.disabled=false; btn.textContent='✨ 一键生图'; return; }
    poll();
  } catch(e) { alert('请求失败: '+e); btn.disabled=false; btn.textContent='✨ 一键生图'; }
}

function poll() {
  if (polling) clearInterval(polling);
  const area = document.getElementById('resultArea');
  polling = setInterval(async () => {
    try {
      let r = await fetch('/api/status');
      let s = await r.json();
      let html = '';

      if (s.status === 'enhancing') {
        html = '<div class="progress"><div class="spinner"></div><p>💬 Ollama 增强提示词...</p></div>';
      } else if (s.status === 'switching') {
        html = '<div class="progress"><div class="spinner"></div><p>🔄 切换到 ComfyUI...</p></div>';
      } else if (s.status === 'generating') {
        html = '<div class="progress"><div class="spinner"></div><p>🎨 生成图片中...</p></div>';
        if (s.positive) html += '<div class="prompt-box"><span>正向:</span> '+s.positive+'</div>';
        if (s.negative) html += '<div class="prompt-box"><span>负向:</span> '+s.negative+'</div>';
      } else if (s.status === 'done') {
        clearInterval(polling);
        document.getElementById('genBtn').disabled = false;
        document.getElementById('genBtn').textContent = '✨ 一键生图';
        html = '<h3 style="margin:12px 0;color:#10b981">✅ 生成完成</h3>';
        if (s.image) html += '<img class="result-img" src="'+s.image+'" alt="generated">';
        if (s.positive) html += '<div class="prompt-box"><span>正向:</span> '+s.positive+'</div>';
        if (s.seed) html += '<p style="color:#666;font-size:12px;margin-top:8px">Seed: '+s.seed+'</p>';
      } else if (s.status === 'error') {
        clearInterval(polling);
        document.getElementById('genBtn').disabled = false;
        document.getElementById('genBtn').textContent = '✨ 一键生图';
        html = '<div class="card" style="color:#ef4444">❌ 错误: '+s.message+'</div>';
      }

      area.innerHTML = html;
    } catch(e) {}
  }, 1500);
}
</script>
</body>
</html>"""

if __name__ == "__main__":
    print("="*50)
    print("  AI Auto Image Gen Web Frontend")
    print("  Open: http://localhost:5000")
    print("="*50)
    # 启动健康监控
    try:
        from health_monitor import start_health_monitor
        start_health_monitor()
        print("  Health Monitor: started")
    except Exception as e:
        print(f"  Health Monitor: {e}")
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5000, log_level="warning")
