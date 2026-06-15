"""工具调用审计日志 — 记录所有工具调用到 JSONL"""
import json
import os
import time

from logger import get_logger

_log = get_logger("tool_audit")

AUDIT_DIR = os.path.expanduser("~/.ai-suite/logs")
AUDIT_FILE = os.path.join(AUDIT_DIR, "tool_audit.jsonl")
os.makedirs(AUDIT_DIR, exist_ok=True)


def log_tool_call(tool_name: str, params: dict, result: dict):
    """记录工具调用到审计日志"""
    entry = {
        "ts": time.time(),
        "tool": tool_name,
        "params": json.dumps(params, ensure_ascii=False)[:500],
        "ok": result.get("ok"),
        "error": str(result.get("error", ""))[:200],
    }
    try:
        with open(AUDIT_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception as e:
        _log.warning("failed to write audit log: %s", e)


def get_recent_calls(limit: int = 100) -> list:
    """读取最近 N 条审计记录"""
    if not os.path.exists(AUDIT_FILE):
        return []
    lines = []
    with open(AUDIT_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                try:
                    lines.append(json.loads(line))
                except Exception:
                    pass
    return lines[-limit:]
