"""
AI Suite — Task Scheduler (v3.0+)
Cron-style 定时任务 + 自然语言调度
支持：每天9点 / 每小时 / 每周一 / 5分钟后
"""
import os
import json
import threading
import time
import re
from datetime import datetime, timedelta
from typing import Optional, Callable

SCHEDULE_FILE = os.path.expanduser("~/.ai-suite/scheduled.json")

# ═══════ 时间解析 ═══════

def parse_schedule(text: str) -> dict:
    """
    解析自然语言时间表达，返回 {type, next_run_ts, cron?, interval_seconds?}
    支持：
      - "每天 9:00" / "每天早上9点"
      - "每小时" / "每小时30分"
      - "每周一 8:00"
      - "5分钟后" / "10分钟后"
      - "明天8点"
      - "30秒后"
      - cron 表达式: "0 9 * * *"
    """
    text = text.strip()
    now = datetime.now()

    # Cron 表达式 (5 字段)
    if re.match(r'^[\d*,/]+\s+[\d*,/]+\s+[\d*,/]+\s+[\d*,/]+\s+[\d*,/]+$', text):
        return {"type": "cron", "cron": text}

    # N秒/分/小时后
    m = re.match(r'(\d+)\s*(秒|分|小时|分钟)后', text)
    if m:
        n = int(m.group(1))
        unit = m.group(2)
        if unit in ('秒',):
            delta = timedelta(seconds=n)
        elif unit in ('分', '分钟'):
            delta = timedelta(minutes=n)
        else:
            delta = timedelta(hours=n)
        target = now + delta
        return {"type": "once", "next_run_ts": target.isoformat(), "interval_seconds": int(delta.total_seconds())}

    # 每天 HH:MM
    m = re.match(r'每天\s*(\d{1,2})[:：点](\d{0,2})?', text)
    if m:
        h, mi = int(m.group(1)), int(m.group(2) or 0)
        target = now.replace(hour=h, minute=mi, second=0, microsecond=0)
        if target <= now:
            target += timedelta(days=1)
        return {"type": "daily", "hour": h, "minute": mi, "next_run_ts": target.isoformat()}

    # 明天 HH:MM
    m = re.match(r'明天\s*(\d{1,2})[:：点](\d{0,2})?', text)
    if m:
        h, mi = int(m.group(1)), int(m.group(2) or 0)
        target = (now + timedelta(days=1)).replace(hour=h, minute=mi, second=0, microsecond=0)
        return {"type": "once", "next_run_ts": target.isoformat()}

    # 每小时
    if '每小时' in text:
        mi = 0
        m = re.search(r'(\d+)\s*分', text)
        if m:
            mi = int(m.group(1))
        target = now.replace(minute=mi, second=0, microsecond=0)
        if target <= now:
            target += timedelta(hours=1)
        return {"type": "hourly", "minute": mi, "next_run_ts": target.isoformat(),
                "interval_seconds": 3600}

    # 每周X HH:MM
    WEEKDAYS = {'一': 0, '二': 1, '三': 2, '四': 3, '五': 4, '六': 5, '日': 6, '天': 6}
    m = re.match(r'每周(\S)\s*(\d{1,2})[:：点](\d{0,2})?', text)
    if m:
        wd = WEEKDAYS.get(m.group(1))
        if wd is not None:
            h, mi = int(m.group(2)), int(m.group(3) or 0)
            days_ahead = wd - now.weekday()
            if days_ahead <= 0:
                days_ahead += 7
            target = (now + timedelta(days=days_ahead)).replace(hour=h, minute=mi, second=0, microsecond=0)
            return {"type": "weekly", "weekday": wd, "hour": h, "minute": mi,
                    "next_run_ts": target.isoformat()}

    # 无法解析
    return {"type": "unknown", "error": f"无法解析时间表达: {text}"}


def _cron_next(cron_expr: str, from_time: datetime = None) -> datetime:
    """简陋 cron 计算下次运行时间（5字段: M H DoM Mon DoW）"""
    now = from_time or datetime.now()
    fields = cron_expr.strip().split()
    if len(fields) != 5:
        return None
    minute, hour, dom, month, dow = fields

    def _match(val, expr, max_val):
        if expr == '*':
            return True
        for part in expr.split(','):
            if '/' in part:
                base, step = part.split('/')
                base = 0 if base == '*' else int(base)
                step = int(step)
                if val >= base and (val - base) % step == 0:
                    return True
            elif '-' in part:
                lo, hi = part.split('-')
                if int(lo) <= val <= int(hi):
                    return True
            elif part == str(val):
                return True
        return False

    # Try each time from now onward (up to 366 days ahead)
    for days in range(366):
        dt = now + timedelta(minutes=1) + timedelta(days=days)
        dt = dt.replace(second=0, microsecond=0)
        # Check each hour
        for h in range(24):
            for m in range(60):
                check = dt.replace(hour=h, minute=m)
                if check <= now:
                    continue
                if (_match(check.minute, minute, 60) and
                    _match(check.hour, hour, 24) and
                    _match(check.day, dom, 31) and
                    _match(check.month, month, 12) and
                    _match(check.weekday(), dow, 7)):
                    return check
    return None


# ═══════ 任务存储 ═══════

class ScheduledTask:
    def __init__(self, task_id: str, description: str, schedule_raw: str, model: str = "deepseek"):
        parsed = parse_schedule(schedule_raw)
        self.id = task_id
        self.description = description
        self.schedule_raw = schedule_raw
        self.schedule = parsed
        self.model = model
        self.created_at = datetime.now().isoformat()
        self.last_run = None
        self.next_run = parsed.get("next_run_ts")
        self.enabled = True
        self._thread = None
        self._running = False  # Prevent overlapping runs

    def to_dict(self):
        return {
            "id": self.id, "description": self.description,
            "schedule": self.schedule_raw, "schedule_parsed": self.schedule,
            "model": self.model, "created_at": self.created_at,
            "last_run": self.last_run, "next_run": self.next_run,
            "enabled": self.enabled, "running": self._running
        }


_tasks: dict = {}
_lock = threading.Lock()
_runner_thread = None
_stop_flag = False


def _load():
    global _tasks
    if os.path.exists(SCHEDULE_FILE):
        try:
            with open(SCHEDULE_FILE) as f:
                data = json.load(f)
            for item in data:
                t = ScheduledTask(item["id"], item["description"],
                                 item.get("schedule", item.get("schedule_raw", "")),
                                 item.get("model", "deepseek"))
                t.created_at = item.get("created_at", t.created_at)
                t.last_run = item.get("last_run")
                t.next_run = item.get("next_run")
                t.enabled = item.get("enabled", True)
                t.schedule = item.get("schedule_parsed", t.schedule)
                _tasks[t.id] = t
        except:
            pass


def _save():
    with _lock:
        data = [t.to_dict() for t in _tasks.values()]
    os.makedirs(os.path.dirname(SCHEDULE_FILE), exist_ok=True)
    with open(SCHEDULE_FILE, "w") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def add_task(description: str, schedule_raw: str, model: str = "deepseek", task_id: str = None) -> dict:
    """添加定时任务"""
    import uuid
    tid = task_id or str(uuid.uuid4())[:8]
    task = ScheduledTask(tid, description, schedule_raw, model)
    with _lock:
        _tasks[tid] = task
    _save()
    return task.to_dict()


def remove_task(task_id: str) -> bool:
    with _lock:
        if task_id in _tasks:
            del _tasks[task_id]
            _save()
            return True
    return False


def list_tasks() -> list:
    with _lock:
        return [t.to_dict() for t in _tasks.values()]


def get_task(task_id: str) -> dict:
    with _lock:
        t = _tasks.get(task_id)
        return t.to_dict() if t else {"error": "not found"}


# ═══════ 调度引擎 ═══════

def _run_task(task: ScheduledTask):
    """执行定时任务"""
    if task._running:
        return  # Already running, skip this cycle
    task._running = True
    task.last_run = datetime.now().isoformat()
    try:
        from agent import Agent
        a = Agent(model_key=task.model)
        result = a.run(task.description)
        # 通知
        try:
            from notify import notify
            preview = (result.get("result", "") or "")[:150]
            notify(f"⏰ {task.description[:40]}", f"完成: {preview}")
        except:
            pass
    except Exception as e:
        try:
            from notify import notify
            notify(f"⏰ 失败: {task.description[:40]}", str(e))
        except:
            pass
    task._running = False
    _save()


def _scheduler_loop():
    """后台调度线程"""
    global _stop_flag
    while not _stop_flag:
        now = datetime.now()
        with _lock:
            for task in list(_tasks.values()):
                if not task.enabled or not task.next_run:
                    continue
                try:
                    next_dt = datetime.fromisoformat(task.next_run)
                except:
                    continue
                if now >= next_dt:
                    # Execute in thread
                    t = threading.Thread(target=_run_task, args=(task,), daemon=True)
                    t.start()

                    # Calculate next run
                    if task.schedule.get("type") == "daily":
                        h, mi = task.schedule["hour"], task.schedule["minute"]
                        new_next = now.replace(hour=h, minute=mi, second=0, microsecond=0) + timedelta(days=1)
                        task.next_run = new_next.isoformat()
                    elif task.schedule.get("type") == "hourly":
                        mi = task.schedule.get("minute", 0)
                        new_next = (now + timedelta(hours=1)).replace(minute=mi, second=0, microsecond=0)
                        task.next_run = new_next.isoformat()
                    elif task.schedule.get("type") == "weekly":
                        wd = task.schedule["weekday"]
                        h, mi = task.schedule["hour"], task.schedule["minute"]
                        days_ahead = wd - now.weekday()
                        if days_ahead <= 0:
                            days_ahead += 7
                        new_next = (now + timedelta(days=days_ahead)).replace(hour=h, minute=mi, second=0, microsecond=0)
                        task.next_run = new_next.isoformat()
                    elif task.schedule.get("type") == "cron":
                        next_dt = _cron_next(task.schedule["cron"], now)
                        if next_dt:
                            task.next_run = next_dt.isoformat()
                    elif task.schedule.get("type") == "once":
                        task.enabled = False  # 一次性任务完成后禁用
                        task.next_run = None
                    _save()
        time.sleep(30)  # 每30秒检查一次


def start_scheduler():
    """启动调度器"""
    global _runner_thread, _stop_flag
    _load()
    if _runner_thread and _runner_thread.is_alive():
        return
    _stop_flag = False
    _runner_thread = threading.Thread(target=_scheduler_loop, daemon=True)
    _runner_thread.start()
    return {"ok": True, "tasks": len(_tasks)}


def stop_scheduler():
    global _stop_flag
    _stop_flag = True
    return {"ok": True}


# ═══════ FastAPI 路由 ═══════

def register_scheduler_routes(app):
    from fastapi import Request
    from fastapi.responses import JSONResponse

    @app.get("/api/scheduler")
    async def api_scheduler_list():
        return {"tasks": list_tasks()}

    @app.post("/api/scheduler")
    async def api_scheduler_add(request: Request):
        data = await request.json()
        desc = data.get("task", "").strip()
        schedule = data.get("schedule", "").strip()
        model = data.get("model", "deepseek")
        if not desc or not schedule:
            return JSONResponse({"error": "task and schedule required"}, 400)
        task = add_task(desc, schedule, model)
        return task

    @app.delete("/api/scheduler/{task_id}")
    async def api_scheduler_delete(task_id: str):
        ok = remove_task(task_id)
        return {"ok": ok}

    @app.post("/api/scheduler/{task_id}/toggle")
    async def api_scheduler_toggle(task_id: str):
        with _lock:
            t = _tasks.get(task_id)
            if t:
                t.enabled = not t.enabled
                _save()
                return t.to_dict()
        return JSONResponse({"error": "not found"}, 404)


# ═══════ CLI ═══════

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        if cmd == "add" and len(sys.argv) > 2:
            schedule = sys.argv[2]
            desc = " ".join(sys.argv[3:]) if len(sys.argv) > 3 else "默认任务"
            print(add_task(desc, schedule))
        elif cmd == "list":
            for t in list_tasks():
                print(f"  {t['id']}: {t['description']} @ {t['schedule']} [{t['next_run']}]")
        elif cmd == "start":
            print(start_scheduler())
    else:
        print("AI Suite Scheduler")
        print("  add '<schedule>' <desc>  — 添加任务")
        print("  list                      — 列出任务")
        print("  start                     — 启动调度器")
        print()
        print("时间表达示例: '每天 9:00' '每小时' '每周一 8:00' '5分钟后' '明天8点'")
