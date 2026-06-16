"""
AI Suite — Learning Memory System (v3.0+)
自动记录用户偏好、使用习惯、Agent 反馈 → 越用越聪明
"""
import os
import json
import sqlite3
import subprocess
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
        category TEXT DEFAULT 'general',  -- preference / fact / feedback / pattern / skill / archived
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
    CREATE TABLE IF NOT EXISTS instincts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        instinct_id TEXT UNIQUE NOT NULL,     -- e.g. 'prefer-functional-style'
        trigger_desc TEXT NOT NULL,            -- 何时触发
        action TEXT NOT NULL,                  -- 做什么
        confidence REAL DEFAULT 0.5,           -- 0.3-0.9
        domain TEXT DEFAULT 'general',         -- code-style/testing/git/workflow/security
        scope TEXT DEFAULT 'project',          -- project/global
        project_id TEXT,                       -- 项目隔离标识
        evidence TEXT,                         -- JSON array of observations
        source TEXT DEFAULT 'session_observation',
        created_at TEXT DEFAULT (datetime('now','localtime')),
        updated_at TEXT DEFAULT (datetime('now','localtime')),
        access_count INTEGER DEFAULT 0
    );
    CREATE INDEX IF NOT EXISTS idx_pref_key ON preferences(key);
    CREATE INDEX IF NOT EXISTS idx_mem_category ON memories(category);
    CREATE INDEX IF NOT EXISTS idx_feedback_rating ON feedback(rating);
    CREATE INDEX IF NOT EXISTS idx_instinct_domain ON instincts(domain);
    CREATE INDEX IF NOT EXISTS idx_instinct_scope ON instincts(scope);
    CREATE INDEX IF NOT EXISTS idx_instinct_confidence ON instincts(confidence);
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


# ═══════ Self-Evolution System (Hermes Agent inspired) ═══════

def evolve_skill_from_session(task: str, result: dict, tools_used: list) -> dict:
    """
    闭环学习：从成功的 Agent 会话自动创建可复用技能。
    触发条件: 任务成功 + 使用了≥2个工具 + 模式新颖
    """
    if not result.get("success"): return {"created": False}
    turns = result.get("turns", 0)
    if turns < 2 or len(tools_used) < 2: return {"created": False}

    # Generate skill name from task
    task_words = task.replace('，',' ').replace('、',' ').split()
    skill_name = '_'.join(w for w in task_words[:3] if len(w) >= 2 and not w.startswith('http'))

    # Check if similar skill already exists
    existing = search_memories(query=skill_name, limit=1)
    if existing and existing[0].get("importance", 0) > 0.6:
        return {"created": False, "reason": "similar skill exists"}

    # Create skill as high-importance memory
    tool_chain = " → ".join(tools_used[:8])
    skill_content = f"""# {skill_name}
任务模板: {task[:300]}
工具链: {tool_chain}
轮次: {turns}轮
结果: {result.get('result', '')[:300]}"""

    add_memory(skill_content, category="skill", source="agent_evolved", importance=0.7)
    return {"created": True, "skill": skill_name, "tools": len(tools_used)}


def curator_prune(min_importance: float = 0.3, max_age_days: int = 30):
    """
    Curator 模式：定期清理低质量/过时的记忆。
    保留: 高重要性 (>0.5) 或 近期访问过的
    归档: 低重要性 + 长期未访问
    """
    conn = _get_db()
    # Archive low-importance, stale memories
    sql = """UPDATE memories SET category = 'archived'
             WHERE importance < ? AND access_count < 3
             AND accessed_at < datetime('now', ?)"""
    conn.execute(sql, (min_importance, f'-{max_age_days} days'))
    archived = conn.rowcount
    conn.commit()
    conn.close()
    return {"archived": archived, "reason": f"importance<{min_importance}, stale>{max_age_days}d"}


def adaptive_context(user_msg: str, recent_tools: list = None) -> str:
    """
    自适应上下文构建 — 学习用户习惯模式。
    - 常用目录
    - 偏好工具
    - 最近话题
    """
    ctx_parts = []

    # Recently used tools → preference
    if recent_tools:
        tool_counts = {}
        for t in recent_tools[-20:]:
            tool_counts[t] = tool_counts.get(t, 0) + 1
        top = sorted(tool_counts.items(), key=lambda x: x[1], reverse=True)[:3]
        ctx_parts.append(f"最近常用工具: {', '.join(f'{t}({c}次)' for t,c in top)}")

    # Learn from user's message patterns
    if len(user_msg) > 200:
        ctx_parts.append("用户偏好详细描述")
    elif '?' in user_msg or '？' in user_msg:
        ctx_parts.append("用户在提问，需要简洁回答")

    return "\n".join(ctx_parts)


def session_mining(recent_convs: list = None) -> list:
    """
    会话挖掘 — 扫描历史对话，发现可复用工作流模式。
    返回: 发现的模式列表
    """
    patterns = []
    recent = search_memories(category="skill", limit=20)
    feedback = get_feedback_stats()

    # Pattern: if user frequently asks for a workflow, elevate it
    if feedback["total"] > 5:
        success_rate = feedback["good"] / feedback["total"] if feedback["total"] else 0
        if success_rate > 0.7:
            patterns.append({
                "type": "high_success",
                "message": f"Agent 成功率高 ({success_rate:.0%})，可尝试更复杂任务",
                "confidence": success_rate
            })
        elif success_rate < 0.3:
            patterns.append({
                "type": "low_success",
                "message": f"Agent 成功率偏低 ({success_rate:.0%})，建议简化任务或切换模型",
                "confidence": 1 - success_rate
            })

    if recent:
        patterns.append({
            "type": "skills_available",
            "count": len(recent),
            "top_skills": [s["content"][:100] for s in recent[:3]]
        })

    return patterns


# ═══════ Instinct System (ECC-inspired) ═══════

def get_project_id() -> str:
    """从 git remote URL 生成项目隔离标识 (12字符哈希)"""
    import hashlib
    try:
        r = subprocess.run(["git", "remote", "get-url", "origin"],
                          capture_output=True, text=True, timeout=5,
                          cwd=os.path.expanduser("~"),
                          creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        if r.returncode == 0 and r.stdout.strip():
            return hashlib.md5(r.stdout.strip().encode()).hexdigest()[:12]
    except:
        pass
    # Fallback: 用当前工作目录
    return hashlib.md5(os.getcwd().encode()).hexdigest()[:12]


def add_instinct(instinct_id: str, trigger_desc: str, action: str,
                 confidence: float = 0.5, domain: str = "general",
                 scope: str = "project", project_id: str = None,
                 evidence: str = "", source: str = "session_observation") -> dict:
    """创建或更新本能"""
    if project_id is None:
        project_id = get_project_id()
    conn = _get_db()
    existing = conn.execute("SELECT id, confidence, evidence FROM instincts WHERE instinct_id=?",
                           (instinct_id,)).fetchone()
    if existing:
        # 更新: 运行平均置信度
        new_conf = min(0.9, (existing["confidence"] + confidence) / 2)
        old_evidence = existing["evidence"] or "[]"
        try:
            ev_list = json.loads(old_evidence)
        except:
            ev_list = []
        if evidence:
            ev_list.append(evidence)
        ev_list = ev_list[-10:]  # 最多保留 10 条证据
        conn.execute("""UPDATE instincts SET confidence=?, evidence=?, updated_at=datetime('now','localtime'),
                       access_count=access_count+1 WHERE instinct_id=?""",
                    (new_conf, json.dumps(ev_list, ensure_ascii=False), instinct_id))
    else:
        conn.execute("""INSERT INTO instincts (instinct_id, trigger_desc, action, confidence, domain,
                       scope, project_id, evidence, source) VALUES (?,?,?,?,?,?,?,?,?)""",
                    (instinct_id, trigger_desc, action, confidence, domain, scope,
                     project_id, json.dumps([evidence] if evidence else [], ensure_ascii=False), source))
    conn.commit()
    conn.close()
    return {"ok": True, "instinct_id": instinct_id, "confidence": confidence}


def get_instincts(domain: str = None, scope: str = None, min_confidence: float = 0.0,
                  project_id: str = None, limit: int = 50) -> list:
    """查询本能"""
    conn = _get_db()
    sql = "SELECT * FROM instincts WHERE confidence >= ?"
    params = [min_confidence]
    if domain:
        sql += " AND domain=?"
        params.append(domain)
    if scope:
        sql += " AND scope=?"
        params.append(scope)
    if project_id:
        sql += " AND (project_id=? OR scope='global')"
        params.append(project_id)
    sql += " ORDER BY confidence DESC, access_count DESC LIMIT ?"
    params.append(limit)
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [{"id": r["id"], "instinct_id": r["instinct_id"], "trigger": r["trigger_desc"],
             "action": r["action"], "confidence": r["confidence"], "domain": r["domain"],
             "scope": r["scope"], "project_id": r["project_id"],
             "evidence": json.loads(r["evidence"]) if r["evidence"] else [],
             "source": r["source"], "access_count": r["access_count"]}
            for r in rows]


def update_instinct_confidence(instinct_id: str, delta: float) -> dict:
    """调整本能置信度 (+0.05 成功 / -0.2 失败)"""
    conn = _get_db()
    row = conn.execute("SELECT confidence FROM instincts WHERE instinct_id=?", (instinct_id,)).fetchone()
    if not row:
        conn.close()
        return {"ok": False, "error": "instinct not found"}
    new_conf = max(0.1, min(0.9, row["confidence"] + delta))
    conn.execute("UPDATE instincts SET confidence=?, updated_at=datetime('now','localtime') WHERE instinct_id=?",
                (new_conf, instinct_id))
    conn.commit()
    conn.close()
    return {"ok": True, "instinct_id": instinct_id, "new_confidence": round(new_conf, 2)}


def promote_instinct(instinct_id: str) -> dict:
    """晋升项目本能到全局"""
    conn = _get_db()
    row = conn.execute("SELECT * FROM instincts WHERE instinct_id=?", (instinct_id,)).fetchone()
    if not row:
        conn.close()
        return {"ok": False, "error": "instinct not found"}
    if row["scope"] == "global":
        conn.close()
        return {"ok": False, "error": "already global"}
    if row["confidence"] < 0.7:
        conn.close()
        return {"ok": False, "error": f"confidence too low ({row['confidence']}), need >= 0.7"}
    conn.execute("UPDATE instincts SET scope='global', project_id=NULL WHERE instinct_id=?",
                (instinct_id,))
    conn.commit()
    conn.close()
    return {"ok": True, "instinct_id": instinct_id, "scope": "global"}


def evolve_instincts_to_skill() -> dict:
    """聚类相关本能为技能"""
    conn = _get_db()
    rows = conn.execute("""SELECT * FROM instincts WHERE confidence >= 0.6
                          ORDER BY domain, confidence DESC""").fetchall()
    conn.close()

    if len(rows) < 3:
        return {"created": False, "reason": "insufficient instincts", "count": len(rows)}

    # 按 domain 分组
    by_domain = {}
    for r in rows:
        d = r["domain"] or "general"
        by_domain.setdefault(d, []).append(r)

    created = []
    for domain, instincts in by_domain.items():
        if len(instincts) < 2:
            continue
        # 生成技能
        skill_name = f"learned_{domain}"
        skill_content = f"# {skill_name}\n\n自动从 {len(instincts)} 个本能进化而来:\n\n"
        for inst in instincts:
            skill_content += f"- [{inst['confidence']:.1f}] {inst['trigger_desc']} → {inst['action']}\n"
        add_memory(skill_content, category="skill", source="instinct_evolved", importance=0.7)
        created.append({"skill": skill_name, "domain": domain, "instincts": len(instincts)})

    return {"created": bool(created), "skills": created}


def observe_pattern(task: str, tools_used: list, outcome: str, corrections: list = None):
    """从会话中提取本能模式"""
    if not tools_used:
        return

    # 模式1: 工具使用偏好
    if len(tools_used) >= 2:
        tool_chain = " → ".join(tools_used[:5])
        add_instinct(
            instinct_id=f"tool-chain-{tools_used[0]}-{tools_used[-1]}",
            trigger_desc=f"执行类似任务时",
            action=f"使用工具链: {tool_chain}",
            confidence=0.4,
            domain="workflow",
            evidence=f"任务: {task[:100]}, 工具: {tool_chain}"
        )

    # 模式2: 用户纠正 → 学习
    if corrections:
        for correction in corrections[:3]:
            correction_id = f"correction-{correction[:30].replace(' ', '-').lower()}"
            add_instinct(
                instinct_id=correction_id,
                trigger_desc=f"遇到类似场景时",
                action=correction,
                confidence=0.6,
                domain="correction",
                evidence=f"任务: {task[:100]}, 纠正: {correction}"
            )

    # 模式3: 成功/失败 → 调整相关本能置信度
    if outcome == "success":
        for tool in tools_used[:3]:
            similar = get_instincts(domain="workflow", limit=5)
            for inst in similar:
                if tool in inst.get("action", ""):
                    update_instinct_confidence(inst["instinct_id"], 0.05)
    elif outcome == "failure":
        for tool in tools_used[:3]:
            similar = get_instincts(domain="workflow", limit=5)
            for inst in similar:
                if tool in inst.get("action", ""):
                    update_instinct_confidence(inst["instinct_id"], -0.1)


def instinct_status() -> dict:
    """本能系统状态总览"""
    conn = _get_db()
    total = conn.execute("SELECT COUNT(*) as c FROM instincts").fetchone()["c"]
    by_domain = conn.execute("SELECT domain, COUNT(*) as c, AVG(confidence) as avg_conf FROM instincts GROUP BY domain").fetchall()
    by_scope = conn.execute("SELECT scope, COUNT(*) as c FROM instincts GROUP BY scope").fetchall()
    high_conf = conn.execute("SELECT COUNT(*) as c FROM instincts WHERE confidence >= 0.7").fetchone()["c"]
    conn.close()
    return {
        "total": total,
        "high_confidence": high_conf,
        "by_domain": {r["domain"]: {"count": r["c"], "avg_confidence": round(r["avg_conf"], 2)} for r in by_domain},
        "by_scope": {r["scope"]: r["c"] for r in by_scope}
    }


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

    # Self-evolution endpoints
    @app.post("/api/memory/evolve")
    async def api_evolve(request: Request):
        """从 Agent 会话创建技能"""
        data = await request.json()
        result = evolve_skill_from_session(
            data.get("task", ""),
            data.get("result", {}),
            data.get("tools_used", []))
        return result

    @app.post("/api/memory/curator")
    async def api_curator():
        """Curator 清理低质量记忆"""
        return curator_prune()

    @app.get("/api/memory/mine")
    async def api_mine():
        """会话挖掘 — 发现可复用模式"""
        return {"patterns": session_mining()}

    @app.get("/api/memory/adaptive")
    async def api_adaptive(q: str = ""):
        """自适应上下文"""
        return {"context": adaptive_context(q)}

    @app.get("/api/agent/learn")
    async def api_agent_learn(task: str = "", success: str = "true", turns: int = 1,
                               model: str = "", tools: str = ""):
        """Agent 学习钩子 — 每次 Agent 任务完成后调用"""
        try:
            tools_list = tools.split(",") if tools else []
            add_feedback(task, "", "good" if success == "true" else "bad")
            # Auto-evolve on success
            if success == "true" and turns >= 2:
                evolve_skill_from_session(task,
                    {"success": True, "turns": turns, "result": ""}, tools_list)
            # 本能观察
            observe_pattern(task, tools_list, "success" if success == "true" else "failure")
            curator_prune(min_importance=0.2, max_age_days=60)
            stats = get_feedback_stats()
            return {"ok": True, "stats": stats, "skills": len(search_memories(category="skill", limit=100))}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # ═══════ Instinct Routes ═══════

    @app.get("/api/memory/instincts")
    async def api_list_instincts(domain: str = "", scope: str = "", min_confidence: float = 0.0):
        """列出本能"""
        try:
            project_id = get_project_id()
            instincts = get_instincts(domain=domain or None, scope=scope or None,
                                     min_confidence=min_confidence, project_id=project_id)
            return {"ok": True, "instincts": instincts, "project_id": project_id}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    @app.post("/api/memory/instincts")
    async def api_add_instinct(request: Request):
        """手动添加本能"""
        try:
            data = await request.json()
            result = add_instinct(
                instinct_id=data["instinct_id"],
                trigger_desc=data["trigger"],
                action=data["action"],
                confidence=data.get("confidence", 0.5),
                domain=data.get("domain", "general"),
                scope=data.get("scope", "project"),
                evidence=data.get("evidence", "")
            )
            return result
        except Exception as e:
            return {"ok": False, "error": str(e)}

    @app.post("/api/memory/instincts/{instinct_id}/promote")
    async def api_promote_instinct(instinct_id: str):
        """晋升项目本能到全局"""
        return promote_instinct(instinct_id)

    @app.get("/api/memory/instincts/status")
    async def api_instinct_status():
        """本能系统状态总览"""
        return {"ok": True, "status": instinct_status()}

    @app.post("/api/memory/instincts/evolve")
    async def api_evolve_instincts():
        """触发本能→技能进化"""
        return evolve_instincts_to_skill()


# ═══════ Init ═══════

init()
print(f"[memory] Learning memory system ready, db: {MEMORY_DB}")
