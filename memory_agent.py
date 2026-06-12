"""
AI Suite — Learning Memory System (v3.0+)
自动记录用户偏好、使用习惯、Agent 反馈 → 越用越聪明
"""
import os
import json
import sqlite3
from datetime import datetime

MEMORY_DB = os.path.expanduser("~/.ai-suite/agent_memory.db")

# ═══════ Schema ═══════

def _get_db():
    conn = sqlite3.connect(MEMORY_DB)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA encoding='UTF-8'")
    return conn

def init():
    os.makedirs(os.path.dirname(MEMORY_DB), exist_ok=True)
    conn = _get_db()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS preferences (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        key TEXT UNIQUE NOT NULL,       -- e.g. 'default_model', 'language', 'code_style'
        value TEXT NOT NULL,
        confidence REAL DEFAULT 0.5,    -- 0~1, 置信度
        count INTEGER DEFAULT 1,        -- 被确认次数
        updated_at TEXT DEFAULT (datetime('now','localtime'))
    );
    CREATE TABLE IF NOT EXISTS memories (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        category TEXT DEFAULT 'general',  -- preference / fact / feedback / pattern
        content TEXT NOT NULL,
        source TEXT,                      -- 来源: 'agent_observed' / 'user_stated' / 'agent_inferred'
        embedding TEXT,                   -- 预留：文本 embedding (json array)
        importance REAL DEFAULT 0.5,      -- 0~1
        created_at TEXT DEFAULT (datetime('now','localtime')),
        accessed_at TEXT DEFAULT (datetime('now','localtime')),
        access_count INTEGER DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS feedback (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        agent_task TEXT NOT NULL,        -- 原始任务
        agent_result TEXT,               -- Agent 输出摘要
        rating TEXT,                     -- good / bad / neutral
        comment TEXT,
        created_at TEXT DEFAULT (datetime('now','localtime'))
    );
    CREATE INDEX IF NOT EXISTS idx_pref_key ON preferences(key);
    CREATE INDEX IF NOT EXISTS idx_mem_category ON memories(category);
    CREATE INDEX IF NOT EXISTS idx_feedback_rating ON feedback(rating);
    """)
    conn.commit()
    conn.close()

# ═══════ Preferences ═══════

def set_preference(key: str, value: str, confidence: float = 0.5):
    conn = _get_db()
    existing = conn.execute("SELECT count, confidence FROM preferences WHERE key=?", (key,)).fetchone()
    if existing:
        new_count = existing[0] + 1
        new_conf = min(1.0, (existing[1] * existing[0] + confidence) / new_count)
        conn.execute("UPDATE preferences SET value=?, confidence=?, count=?, updated_at=datetime('now','localtime') WHERE key=?",
                    (value, new_conf, new_count, key))
    else:
        conn.execute("INSERT INTO preferences (key, value, confidence) VALUES (?,?,?)", (key, value, confidence))
    conn.commit()
    conn.close()

def get_preference(key: str, default=None):
    conn = _get_db()
    row = conn.execute("SELECT value, confidence FROM preferences WHERE key=?", (key,)).fetchone()
    conn.close()
    if row:
        return {"value": row[0], "confidence": row[1]}
    return {"value": default, "confidence": 0}

def list_preferences() -> list:
    conn = _get_db()
    rows = conn.execute("SELECT key, value, confidence, count FROM preferences ORDER BY confidence DESC").fetchall()
    conn.close()
    return [{"key": r[0], "value": r[1], "confidence": r[2], "count": r[3]} for r in rows]

# ═══════ Memories ═══════

def add_memory(content: str, category: str = "general", source: str = "agent_observed",
                importance: float = 0.5):
    conn = _get_db()
    conn.execute(
        "INSERT INTO memories (category, content, source, importance) VALUES (?,?,?,?)",
        (category, content, source, importance))
    conn.commit()
    conn.close()

def search_memories(query: str = None, category: str = None, limit: int = 20) -> list:
    """搜索记忆，按重要性 + 访问频率排序"""
    conn = _get_db()
    sql = "SELECT id, category, content, source, importance, access_count FROM memories WHERE 1=1"
    params = []
    if query:
        sql += " AND content LIKE ?"
        params.append(f"%{query}%")
    if category:
        sql += " AND category=?"
        params.append(category)
    sql += " ORDER BY importance DESC, access_count DESC LIMIT ?"
    params.append(limit)
    rows = conn.execute(sql, params).fetchall()
    # Update access
    if rows:
        ids = [r[0] for r in rows]
        conn.execute(f"UPDATE memories SET access_count=access_count+1, accessed_at=datetime('now','localtime') WHERE id IN ({','.join('?'*len(ids))})", ids)
        conn.commit()
    conn.close()
    return [{"id": r[0], "category": r[1], "content": r[2], "source": r[3],
             "importance": r[4], "access_count": r[5]} for r in rows]

def get_relevant_memories(task: str, limit: int = 5) -> list:
    """根据任务获取相关记忆（简单关键词匹配）"""
    keywords = [w for w in task.replace('，',',').replace('、',' ').split()
                if len(w) >= 2]
    if not keywords:
        return search_memories(limit=limit)
    # 每个关键词搜一次
    results = []
    seen = set()
    for kw in keywords[:5]:
        for m in search_memories(query=kw, limit=3):
            if m["id"] not in seen:
                results.append(m)
                seen.add(m["id"])
    return sorted(results, key=lambda x: x["importance"], reverse=True)[:limit]

# ═══════ Feedback ═══════

def add_feedback(task: str, result: str = "", rating: str = "neutral", comment: str = ""):
    conn = _get_db()
    conn.execute("INSERT INTO feedback (agent_task, agent_result, rating, comment) VALUES (?,?,?,?)",
                (task, result[:500], rating, comment))
    conn.commit()
    conn.close()

def get_feedback_stats() -> dict:
    conn = _get_db()
    total = conn.execute("SELECT COUNT(*) FROM feedback").fetchone()[0]
    good = conn.execute("SELECT COUNT(*) FROM feedback WHERE rating='good'").fetchone()[0]
    bad = conn.execute("SELECT COUNT(*) FROM feedback WHERE rating='bad'").fetchone()[0]
    conn.close()
    return {"total": total, "good": good, "bad": bad,
            "neutral": total - good - bad}

# ═══════ Auto-Learning ═══════

def learn_from_conversation(user_msg: str, assistant_reply: str, model_used: str):
    """从对话中自动提取偏好"""
    # 检测语言偏好
    cn_chars = sum(1 for c in user_msg if '一' <= c <= '鿿')
    if cn_chars > 5:
        set_preference("language", "zh-CN", 0.6)

    # 检测代码偏好
    if '```' in user_msg or 'def ' in user_msg or 'function ' in user_msg:
        set_preference("user_writes_code", "true", 0.7)

    # 记录常用模型
    if model_used:
        set_preference(f"model_used:{model_used}", "1", 0.4)


def learn_from_agent_result(task: str, result: dict, model: str):
    """从 Agent 执行结果中学习"""
    success = result.get("success", False)
    turns = result.get("turns", 0)

    # 记录任务复杂度 vs 模型匹配
    if success and turns <= 3:
        add_memory(f"模型 {model} 高效完成任务: {task[:200]}",
                   category="pattern", source="agent_observed", importance=0.4)
    elif not success:
        add_memory(f"模型 {model} 未能完成任务: {task[:200]}",
                   category="pattern", source="agent_observed", importance=0.6)

    # 提取任务中可能的事实
    if success:
        add_memory(f"任务完成: {task[:200]} → {result.get('result', '')[:200]}",
                   category="fact", source="agent_observed", importance=0.3)


# ═══════ Context Builder ═══════

def build_agent_context(task: str) -> str:
    """为 Agent 构建个性化上下文"""
    parts = []

    # 偏好
    lang = get_preference("language")
    if lang["confidence"] > 0.5:
        parts.append(f"用户语言偏好: {lang['value']}")

    code_pref = get_preference("user_writes_code")
    if code_pref["confidence"] > 0.5:
        parts.append("用户经常编写代码")

    # 相关记忆
    memories = get_relevant_memories(task, limit=3)
    if memories:
        parts.append("相关历史:")
        for m in memories:
            parts.append(f"  - {m['content'][:200]}")

    # 反馈统计
    stats = get_feedback_stats()
    if stats["total"] > 0:
        good_rate = stats["good"] / stats["total"] * 100
        parts.append(f"历史满意度: {good_rate:.0f}% ({stats['good']}/{stats['total']})")

    return "\n".join(parts) if parts else ""


# ═══════ FastAPI 路由 ═══════

def register_memory_routes(app):
    from fastapi import Request
    from fastapi.responses import JSONResponse

    @app.get("/api/memory/preferences")
    async def api_prefs():
        return {"preferences": list_preferences()}

    @app.post("/api/memory/preferences")
    async def api_set_pref(request: Request):
        data = await request.json()
        set_preference(data["key"], data.get("value", ""), data.get("confidence", 0.5))
        return get_preference(data["key"])

    @app.get("/api/memory/search")
    async def api_search(q: str = "", category: str = ""):
        return {"memories": search_memories(query=q or None, category=category or None)}

    @app.post("/api/memory")
    async def api_add_memory(request: Request):
        data = await request.json()
        add_memory(data["content"], data.get("category", "general"),
                  data.get("source", "user_stated"), data.get("importance", 0.5))
        return {"ok": True}

    @app.post("/api/memory/feedback")
    async def api_feedback(request: Request):
        data = await request.json()
        add_feedback(data.get("task", ""), data.get("result", ""),
                    data.get("rating", "neutral"), data.get("comment", ""))
        return get_feedback_stats()

    @app.get("/api/memory/context")
    async def api_context(task: str = ""):
        return {"context": build_agent_context(task)}


# ═══════ Init ═══════

init()
print(f"[memory] Learning memory system ready, db: {MEMORY_DB}")
