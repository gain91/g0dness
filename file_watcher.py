"""
AI Suite — File Watcher (v3.1)
监控文件夹变化 → 自动触发 Agent 处理
"""
import os
import json
import time
import threading
import hashlib
from datetime import datetime

WATCH_CONFIG = os.path.expanduser("~/.ai-suite/watchers.json")

# ═══════ Watcher ═══════

class FolderWatcher:
    def __init__(self, watch_id: str, folder: str, action: str = "notify",
                 pattern: str = "*", model: str = "deepseek"):
        self.id = watch_id
        self.folder = folder
        self.action = action  # notify | ocr | summarize | agent:{prompt}
        self.pattern = pattern
        self.model = model
        self.enabled = True
        self.created_at = datetime.now().isoformat()
        self._seen = set()  # file hashes already processed
        self._thread = None

    def to_dict(self):
        return {
            "id": self.id, "folder": self.folder, "action": self.action,
            "pattern": self.pattern, "model": self.model,
            "enabled": self.enabled, "created_at": self.created_at
        }


_watchers: dict = {}
_lock = threading.Lock()
_stop_flag = False
_watch_thread = None


def _load():
    global _watchers
    if os.path.exists(WATCH_CONFIG):
        try:
            with open(WATCH_CONFIG) as f:
                data = json.load(f)
            for item in data:
                w = FolderWatcher(item["id"], item["folder"], item.get("action", "notify"),
                                 item.get("pattern", "*"), item.get("model", "deepseek"))
                w.enabled = item.get("enabled", True)
                w.created_at = item.get("created_at", w.created_at)
                if item.get("seen"):
                    w._seen = set(str(x) for x in item["seen"])
                _watchers[w.id] = w
        except:
            pass


def _save():
    data = []
    with _lock:
        for w in _watchers.values():
            d = w.to_dict()
            d["seen"] = list(w._seen)
            data.append(d)
    os.makedirs(os.path.dirname(WATCH_CONFIG), exist_ok=True)
    with open(WATCH_CONFIG, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def add_watcher(folder: str, action: str = "notify", pattern: str = "*",
                model: str = "deepseek", watch_id: str = None) -> dict:
    import uuid
    folder = os.path.abspath(os.path.expanduser(folder))
    if not os.path.isdir(folder):
        return {"error": f"Folder not found: {folder}"}
    tid = watch_id or str(uuid.uuid4())[:8]
    w = FolderWatcher(tid, folder, action, pattern, model)
    with _lock:
        _watchers[tid] = w
    _save()
    return w.to_dict()


def remove_watcher(watch_id: str) -> bool:
    with _lock:
        if watch_id in _watchers:
            del _watchers[watch_id]
            _save()
            return True
    return False


def list_watchers() -> list:
    with _lock:
        return [w.to_dict() for w in _watchers.values()]


def _file_hash(filepath: str) -> str:
    """快速文件哈希（大小+mtime）"""
    try:
        stat = os.stat(filepath)
        return f"{stat.st_size}:{stat.st_mtime}"
    except:
        return ""


def _execute_action(watcher: FolderWatcher, filepath: str):
    """执行监工动作"""
    basename = os.path.basename(filepath)
    try:
        if watcher.action == "notify":
            from notify import notify
            notify(f"📁 新文件: {basename}", filepath)
        elif watcher.action == "ocr":
            import tools
            result = tools.execute("ocr", {"image_path": filepath})
            if result.get("ok") and result.get("text"):
                from notify import notify
                preview = result["text"][:200]
                notify(f"📝 OCR: {basename}", preview)
        elif watcher.action.startswith("agent:"):
            prompt = watcher.action[6:].replace("{file}", filepath).replace("{name}", basename)
            from agent import Agent
            a = Agent(model_key=watcher.model)
            a.run(prompt)
        elif watcher.action == "summarize":
            import tools
            result = tools.execute("read_file", {"path": filepath})
            if result.get("ok") and result.get("content"):
                from agent import Agent
                a = Agent(model_key=watcher.model)
                a.run(f"Summarize this file content briefly:\n\n{result['content'][:5000]}")
    except Exception as e:
        from notify import notify
        notify(f"❌ 监工失败: {basename}", str(e))


def _watch_loop():
    """后台轮询所有监工"""
    global _stop_flag
    while not _stop_flag:
        with _lock:
            watchers = list(_watchers.values())
        for w in watchers:
            if not w.enabled or not os.path.isdir(w.folder):
                continue
            try:
                import fnmatch
                for fname in os.listdir(w.folder):
                    fpath = os.path.join(w.folder, fname)
                    if not os.path.isfile(fpath):
                        continue
                    if not fnmatch.fnmatch(fname, w.pattern):
                        continue
                    fhash = _file_hash(fpath)
                    if fhash and fhash not in w._seen:
                        w._seen.add(fhash)
                        # 只保留最近 1000 条
                        if len(w._seen) > 1000:
                            w._seen = set(list(w._seen)[-900:])
                        _execute_action(w, fpath)
            except Exception:
                pass
        _save()
        time.sleep(5)  # 每5秒轮询一次


def start():
    global _stop_flag, _watch_thread
    _load()
    _stop_flag = False
    if _watch_thread and _watch_thread.is_alive():
        return {"ok": True, "watchers": len(_watchers)}
    _watch_thread = threading.Thread(target=_watch_loop, daemon=True)
    _watch_thread.start()
    return {"ok": True, "watchers": len(_watchers)}


def stop():
    global _stop_flag
    _stop_flag = True
    return {"ok": True}


# ═══════ FastAPI Routes ═══════

def register_routes(app):
    from fastapi import Request
    from fastapi.responses import JSONResponse

    @app.get("/api/watchers")
    async def api_list():
        return {"watchers": list_watchers()}

    @app.post("/api/watchers")
    async def api_add(request: Request):
        data = await request.json()
        folder = data.get("folder", "")
        action = data.get("action", "notify")
        pattern = data.get("pattern", "*")
        model = data.get("model", "deepseek")
        if not folder:
            return JSONResponse({"error": "folder required"}, 400)
        return add_watcher(folder, action, pattern, model)

    @app.delete("/api/watchers/{wid}")
    async def api_delete(wid: str):
        return {"ok": remove_watcher(wid)}


# ═══════ Init ═══════

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "start":
        print(start())
    else:
        print("File Watcher — 监控文件夹变化自动处理")
        print("  Actions: notify | ocr | summarize | agent:prompt")
