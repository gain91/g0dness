"""
全自动文生图：自然语言 → SDXL 生图
用法: python gen_image.py "一个穿汉服的女孩站在樱花树下，夕阳"
"""
import sys, json, time, os, shutil, subprocess, urllib.request, urllib.error

COMFYUI_DIR = "C:/Users/86538/ComfyUI"
COMFYUI_URL = "http://127.0.0.1:8188"
OUTPUT_DIR = "C:/Users/86538/Downloads/generated"
MODEL = "sd_xl_base_1.0.safetensors"  # 或 "animagine-xl-4.0.safetensors"
STEPS = 25
CFG = 7.0
WIDTH = 1024
HEIGHT = 1024

# ── Step 1: 用 Ollama 增强提示词 ──
def enhance_prompt(user_input: str) -> tuple[str, str]:
    """用 Ollama 把自然语言转成 SDXL 提示词+负向词"""
    system_prompt = """You are an expert SDXL prompt engineer. Convert the user's natural language description into:
1. A detailed English positive prompt optimized for SDXL, using keywords like: masterpiece, best quality, 8k, detailed, <user's content>
2. A negative prompt with common quality issues.

Respond ONLY in JSON format:
{"positive": "...", "negative": "..."}

Rules:
- Positive: include quality tags + detailed visual description + style keywords
- Negative: lowres, bad anatomy, bad hands, text, watermark, blurry, ugly, deformed, extra fingers, mutated hands, poorly drawn face, cloned face, disfigured, gross proportions, missing arms, missing legs, extra limbs, fused fingers, too many fingers, long neck
- Keep positive under 200 tokens, negative under 100 tokens
"""
    req = json.dumps({
        "model": "qwen3:8b",
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_input}
        ],
        "stream": False,
        "format": "json",
    }).encode()

    print(f"💬 增强提示词: {user_input}")

    try:
        resp = urllib.request.urlopen(
            urllib.request.Request("http://localhost:11434/api/chat", req),
            timeout=120
        )
        data = json.loads(resp.read())
        result = json.loads(data["message"]["content"])
        print(f"   正向: {result['positive'][:100]}...")
        print(f"   负向: {result['negative'][:100]}...")
        return result["positive"], result["negative"]
    except Exception as e:
        print(f"   ⚠️ Ollama 增强失败: {e}，使用默认模板")
        return (
            f"masterpiece, best quality, 8k, detailed, {user_input}",
            "lowres, bad anatomy, bad hands, text, watermark, blurry, ugly, deformed"
        )


# ── Step 2: 服务切换 ──
def switch_to_comfyui():
    """杀死 Ollama，启动 ComfyUI"""
    print("🔌 停止 Ollama...")
    subprocess.run(["taskkill", "/f", "/im", "ollama.exe"],
                   capture_output=True, shell=True)
    time.sleep(2)

    # 检查 ComfyUI 是否已在运行
    try:
        urllib.request.urlopen(f"{COMFYUI_URL}/system_stats", timeout=3)
        print("✅ ComfyUI 已在运行")
        return
    except:
        pass

    print("🚀 启动 ComfyUI...")
    subprocess.Popen(
        [sys.executable, "main.py"],
        cwd=COMFYUI_DIR,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    # 等待上线
    for i in range(60):
        try:
            urllib.request.urlopen(f"{COMFYUI_URL}/system_stats", timeout=2)
            print("✅ ComfyUI 就绪")
            return
        except:
            time.sleep(2)
    raise RuntimeError("ComfyUI 启动超时")


# ── Step 3: 构建工作流 ──
def build_workflow(positive: str, negative: str, seed: int) -> dict:
    """构建 SDXL ComfyUI 工作流 JSON"""
    return {
        "4": {  # Load Checkpoint
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": MODEL}
        },
        "6": {  # CLIP Text Encode (Positive)
            "class_type": "CLIPTextEncode",
            "inputs": {
                "text": positive,
                "clip": ["4", 1]
            }
        },
        "7": {  # CLIP Text Encode (Negative)
            "class_type": "CLIPTextEncode",
            "inputs": {
                "text": negative,
                "clip": ["4", 1]
            }
        },
        "5": {  # Empty Latent Image
            "class_type": "EmptyLatentImage",
            "inputs": {
                "width": WIDTH,
                "height": HEIGHT,
                "batch_size": 1
            }
        },
        "3": {  # KSampler
            "class_type": "KSampler",
            "inputs": {
                "seed": seed,
                "steps": STEPS,
                "cfg": CFG,
                "sampler_name": "dpmpp_2m",
                "scheduler": "karras",
                "denoise": 1.0,
                "model": ["4", 0],
                "positive": ["6", 0],
                "negative": ["7", 0],
                "latent_image": ["5", 0]
            }
        },
        "8": {  # VAE Decode
            "class_type": "VAEDecode",
            "inputs": {
                "samples": ["3", 0],
                "vae": ["4", 2]
            }
        },
        "9": {  # Save Image
            "class_type": "SaveImage",
            "inputs": {
                "filename_prefix": "gen",
                "images": ["8", 0]
            }
        }
    }


# ── Step 4: 提交 & 等待 ──
def generate_image(workflow: dict) -> str:
    """提交到 ComfyUI，轮询等待完成，返回文件路径"""
    # 提交
    payload = json.dumps({"prompt": workflow}).encode()
    req = urllib.request.Request(f"{COMFYUI_URL}/prompt", payload,
                                  headers={"Content-Type": "application/json"})
    resp = json.loads(urllib.request.urlopen(req).read())
    prompt_id = resp["prompt_id"]
    print(f"🎨 生成中... (ID: {prompt_id})")

    # 轮询进度
    while True:
        try:
            history = json.loads(
                urllib.request.urlopen(f"{COMFYUI_URL}/history/{prompt_id}", timeout=10).read()
            )
            if prompt_id in history:
                outputs = history[prompt_id]["outputs"]
                if "9" in outputs:  # 我们的 SaveImage 节点
                    img_info = outputs["9"]["images"][0]
                    src = os.path.join(COMFYUI_DIR, "output", img_info["subfolder"],
                                       img_info["filename"])
                    os.makedirs(OUTPUT_DIR, exist_ok=True)
                    dst = os.path.join(OUTPUT_DIR, img_info["filename"])
                    shutil.copy2(src, dst)
                    print(f"✅ 完成！图片: {dst}")
                    return dst
            time.sleep(2)
        except Exception as e:
            print(f"   等待中... ({e})")
            time.sleep(2)


# ── Main ──
def main():
    if len(sys.argv) < 2:
        print("用法: python gen_image.py \"自然语言描述\"")
        print("示例: python gen_image.py \"a cat sitting on a cloud\"")
        return

    user_input = sys.argv[1]
    seed = int(time.time())

    print("=" * 50)
    print(f"🔮 全自动生图: {user_input}")
    print("=" * 50)

    # Phase 1: 用 Ollama 增强提示词
    positive, negative = enhance_prompt(user_input)

    # Phase 2: 切换到 ComfyUI
    switch_to_comfyui()

    # Phase 3: 生成
    workflow = build_workflow(positive, negative, seed)
    output_path = generate_image(workflow)

    # 打开图片
    os.startfile(output_path)
    print(f"📂 {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
