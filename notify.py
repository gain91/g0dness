"""
AI Suite — Notification system (v3.0)
Windows toast 通知 + 后台任务队列
"""
import os
import subprocess
import json
import threading
import time
from datetime import datetime

# ═══════ Windows Toast 通知 ═══════

def notify(title: str, body: str = "", duration: int = 5):
    """
    弹出 Windows 原生通知。
    优先用 PowerShell Toast，降级用 balloon tip。
    """
    try:
        # Windows 10/11 原生 Toast
        ps_script = f'''
        [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] > $null
        $template = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
        $texts = $template.GetElementsByTagName("text")
        $texts.Item(0).AppendChild($template.CreateTextNode("{title}")) > $null
        $texts.Item(1).AppendChild($template.CreateTextNode("{body}")) > $null
        $toast = [Windows.UI.Notifications.ToastNotification]::new($template)
        $notifier = [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("AI Suite")
        $notifier.Show($toast)
        '''
        subprocess.run(["powershell", "-Command", ps_script],
                      capture_output=True, timeout=10,
                      creationflags=subprocess.CREATE_NO_WINDOW)
        return {"ok": True, "method": "toast"}
    except:
        pass

    # Fallback: 简单托盘气泡（通过临时 VBS）
    try:
        vbs = f'''
        Set objShell = CreateObject("WScript.Shell")
        objShell.Popup "{body}", {duration}, "{title}", 64
        '''
        vbs_path = os.path.expanduser("~/.ai-suite/_notify.vbs")
        os.makedirs(os.path.dirname(vbs_path), exist_ok=True)
        with open(vbs_path, "w") as f:
            f.write(vbs)
        subprocess.Popen(["wscript", vbs_path],
                        creationflags=subprocess.CREATE_NO_WINDOW)
        return {"ok": True, "method": "vbs_popup"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ═══════ 后台任务队列 ═══════

_task_queue = []
_task_lock = threading.Lock()
_task_counter = 0


class BackgroundTask:
    def __init__(self, task_id: str, description: str, model: str = "deepseek"):
        self.id = task_id
        self.description = description
        self.model = model
        self.status = "pending"  # pending | running | done | error
        self.result = None
        self.error = None
        self.created_at = datetime.now().isoformat()
        self.finished_at = None
        self._thread = None

    def to_dict(self):
        return {
            "id": self.id, "description": self.description, "model": self.model,
            "status": self.status, "result": self.result, "error": self.error,
            "created_at": self.created_at, "finished_at": self.finished_at
        }


def run_task_async(task_id: str, task_desc: str, model: str = "deepseek") -> dict:
    """启动后台 Agent 任务，立即返回"""
    global _task_counter
    with _task_lock:
        task = BackgroundTask(task_id, task_desc, model)
        _task_queue.append(task)
        _task_counter += 1

    def _runner():
        task.status = "running"
        try:
            from agent import Agent
            a = Agent(model_key=model)
            result = a.run(task_desc)
            task.result = result.get("result", "")
            task.status = "done" if result.get("success") else "error"
            if not result.get("success"):
                task.error = task.result
            task.finished_at = datetime.now().isoformat()

            # 通知用户
            if task.status == "done":
                preview = task.result[:200] + ("..." if len(task.result) > 200 else "")
                notify("AI Suite Agent ✅", f"任务完成: {task_desc[:60]}\n{preview}")
            else:
                notify("AI Suite Agent ❌", f"任务失败: {task_desc[:60]}\n{task.error or '未知错误'}")

        except Exception as e:
            task.status = "error"
            task.error = str(e)
            task.finished_at = datetime.now().isoformat()
            notify("AI Suite Agent ❌", f"任务异常: {task_desc[:60]}\n{e}")

    task._thread = threading.Thread(target=_runner, daemon=True)
    task._thread.start()
    return task.to_dict()


def list_tasks() -> list:
    with _task_lock:
        return [t.to_dict() for t in _task_queue]


def get_task(task_id: str) -> dict:
    with _task_lock:
        for t in _task_queue:
            if t.id == task_id:
                return t.to_dict()
    return {"error": "task not found"}


# ═══════ 系统托盘通知 ═══════

def notify_tray(title: str, body: str = ""):
    """
    通过 win32 API 发系统托盘气泡通知。
    需要在 start_ai_suite.pyw 的托盘线程中调用（有窗口句柄才能收消息）。
    如果不在托盘上下文，降级到 PowerShell toast。
    """
    # 尝试 PowerShell toast（不需要窗口句柄）
    return notify(title, body)


# ═══════ FastAPI 路由 ═══════

def _parse_error(e):
    return str(e)

try:
    from fastapi import Request
    from fastapi.responses import JSONResponse
    HAS_FASTAPI = True
except:
    HAS_FASTAPI = False


def register_notify_routes(app):
    """向 FastAPI app 注册通知 + 后台任务路由"""
    if not HAS_FASTAPI:
        return

    @app.post("/api/notify")
    async def api_notify(request: Request):
        data = await request.json()
        title = data.get("title", "AI Suite")
        body = data.get("body", "")
        result = notify(title, body)
        return result

    @app.post("/api/agent/task")
    async def api_agent_task(request: Request):
        """后台 Agent 任务：立即返回，后台执行，完成后通知"""
        data = await request.json()
        task_desc = data.get("task", "").strip()
        model = data.get("model", "deepseek")
        if not task_desc:
            return JSONResponse({"error": "empty task"}, 400)
        import uuid
        task_id = data.get("task_id") or str(uuid.uuid4())[:8]
        task = run_task_async(task_id, task_desc, model)
        return task

    @app.get("/api/agent/tasks")
    async def api_agent_tasks():
        return {"tasks": list_tasks()}

    @app.get("/api/agent/tasks/{task_id}")
    async def api_agent_task_status(task_id: str):
        return get_task(task_id)


# ═══════ CLI ═══════

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        title = sys.argv[1]
        body = sys.argv[2] if len(sys.argv) > 2 else ""
        result = notify(title, body)
        print(result)
    else:
        result = notify("AI Suite", "你好！这是一条测试通知 🎉")
        print(result)
