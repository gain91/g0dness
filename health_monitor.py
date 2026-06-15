"""健康监控 + 自动恢复 — 后台线程每 30s 检测服务状态"""
import os
import subprocess
import socket
import threading
import time

from logger import get_logger

_log = get_logger("health_monitor")


def _check_port(host: str, port: int, timeout: float = 2.0) -> bool:
    """TCP 端口连通性检测"""
    try:
        s = socket.create_connection((host, port), timeout=timeout)
        s.close()
        return True
    except (socket.timeout, ConnectionRefusedError, OSError):
        return False


def _check_ollama() -> bool:
    return _check_port("localhost", 11434)


def _check_comfyui() -> bool:
    return _check_port("127.0.0.1", 8188)


HEALTH_CHECKS = {
    "ollama": _check_ollama,
    "comfyui": _check_comfyui,
}


def start_health_monitor(interval: int = 30):
    """启动后台健康监控线程 — 检测 Ollama/ComfyUI，自动重启"""

    def _loop():
        _log.info("health monitor started (interval=%ds)", interval)
        while True:
            for name, check in HEALTH_CHECKS.items():
                try:
                    ok = check()
                    if not ok:
                        _log.warning("%s is DOWN", name)
                        if name == "ollama":
                            _log.info("attempting to restart ollama...")
                            try:
                                subprocess.Popen(
                                    ["ollama", "serve"],
                                    stdout=subprocess.DEVNULL,
                                    stderr=subprocess.DEVNULL,
                                    creationflags=subprocess.CREATE_NO_WINDOW
                                    if os.name == "nt" else 0,
                                )
                            except Exception as e:
                                _log.error("failed to restart ollama: %s", e)
                except Exception as e:
                    _log.error("health check %s error: %s", name, e)
            time.sleep(interval)

    t = threading.Thread(target=_loop, daemon=True, name="health-monitor")
    t.start()
    return t
