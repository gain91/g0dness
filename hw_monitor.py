"""
AI Suite — Hardware Monitor
检测 RAM/VRAM 状态，用于智能模型选择
"""
import subprocess, json, os, sys

def get_free_ram_gb():
    """返回可用 RAM (GB) — psutil 主方案，PowerShell 备用"""
    try:
        import psutil
        mem = psutil.virtual_memory()
        val = round(mem.available / (1024**3), 1)
        if val > 0:
            return val
    except:
        pass
    # fallback
    try:
        result = subprocess.run(
            ["powershell", "-Command",
             "[math]::Round((Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory/1MB,1)"],
            capture_output=True, text=True, timeout=10)
        val = float(result.stdout.strip())
        if val > 0:
            return round(val, 1)
    except:
        pass
    return 8.0

def get_free_vram_gb():
    """返回可用 VRAM (GB)，nvidia-smi / 默认"""
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0)
        return round(float(result.stdout.strip().split('\n')[0]) / 1024, 1)
    except:
        pass
    return 12.0  # RTX 5070 Ti default

# ─── Model Tiering ───

TIERS = {
    "minimal":  (4, 4, "极简模式"),
    "low":      (6, 5, "低配模式"),
    "medium":   (12, 7, "标准模式"),
    "high":     (24, 10, "高性能模式"),
}

OLLAMA_TIER_MAP = {
    "minimal": "qwen3:8b",
    "low": "qwen3:8b",
    "medium": "deepseek-r1:14b",
    "high": "deepseek-r1:14b",
}

def get_tier():
    """根据当前硬件状态返回 tier"""
    ram = get_free_ram_gb()
    vram = get_free_vram_gb()
    if ram < 4 or vram < 4:
        return "minimal"
    elif ram < 8 or vram < 6:
        return "low"
    elif ram < 16 or vram < 8:
        return "medium"
    return "high"

def get_best_model():
    """返回当前硬件下最佳本地模型"""
    return OLLAMA_TIER_MAP.get(get_tier(), "qwen3:8b")

def can_start_comfyui():
    """判断是否有足够 VRAM 启动 ComfyUI (SDXL ~6.5GB)"""
    vram = get_free_vram_gb()
    ram = get_free_ram_gb()
    return vram >= 8 and ram >= 8

def can_start_animagine():
    """判断是否有足够 VRAM 启动 Animagine XL (12GB)"""
    return get_free_vram_gb() >= 14

if __name__ == "__main__":
    print(f"Free RAM:  {get_free_ram_gb():.1f} GB")
    print(f"Free VRAM: {get_free_vram_gb():.1f} GB")
    print(f"Tier:      {get_tier()}")
    print(f"Best model: {get_best_model()}")
    print(f"ComfyUI:   {'OK' if can_start_comfyui() else 'Insufficient VRAM'}")
