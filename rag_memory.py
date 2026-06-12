"""
AI Suite — RAG Memory System (v4.0)
向量化长期记忆：嵌入 + 检索 + Agent 上下文增强
用法:
  from rag_memory import RAGMemory
  rag = RAGMemory()
  rag.remember("用户喜欢 Python")
  results = rag.recall("编程语言偏好")
"""

import os, json, sqlite3, time, hashlib
from typing import List, Dict, Optional

MEMORY_DIR = os.path.expanduser("~/.ai-suite")
DB_PATH = os.path.join(MEMORY_DIR, "rag_memory.db")

# ═══════ Simple embedding (no external deps) ═══════

def _simple_embed(text: str, dim: int = 256) -> List[float]:
    """
    轻量级嵌入 — 基于字符 n-gram + TF-IDF 风格的哈希。
    优点: 零依赖，即时计算。缺点: 语义精度不如 transformer。
    对于本地记忆检索足够用。
    """
    text = text.lower()
    vec = [0.0] * dim
    # Character trigrams
    for i in range(len(text) - 2):
        trigram = text[i:i+3]
        h = hashlib.md5(trigram.encode()).digest()
        for j in range(0, len(h), 2):
            idx = int.from_bytes(h[j:j+2], 'big') % dim
            vec[idx] += 0.05
    # Word bigrams
    words = text.split()
    for i in range(len(words) - 1):
        bigram = f"{words[i]}_{words[i+1]}"
        h = hashlib.md5(bigram.encode()).digest()
        for j in range(0, len(h), 2):
            idx = int.from_bytes(h[j:j+2], 'big') % dim
            vec[idx] += 0.1
    # Normalize
    norm = sum(v * v for v in vec) ** 0.5
    if norm > 0:
        vec = [v / norm for v in vec]
    return vec

def cosine_sim(a: List[float], b: List[float]) -> float:
    return sum(x * y for x, y in zip(a, b))

# ═══════ RAG Memory ═══════

class RAGMemory:
    def __init__(self, dim: int = 256):
        self.dim = dim
        os.makedirs(MEMORY_DIR, exist_ok=True)
        self.db = sqlite3.connect(DB_PATH)
        self.db.row_factory = sqlite3.Row
        self._init_db()

    def _init_db(self):
        self.db.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT DEFAULT 'general',
                content TEXT NOT NULL,
                embedding BLOB,
                importance REAL DEFAULT 0.5,
                created_at REAL,
                access_count INTEGER DEFAULT 0,
                last_access REAL
            );
            CREATE INDEX IF NOT EXISTS idx_mem_category ON memories(category);
        """)
        self.db.commit()

    def remember(self, content: str, category: str = "general", importance: float = 0.5):
        """存储一条记忆"""
        emb = _simple_embed(content, self.dim)
        now = time.time()
        self.db.execute(
            "INSERT INTO memories(category, content, embedding, importance, created_at, last_access) VALUES(?,?,?,?,?,?)",
            (category, content, json.dumps(emb), importance, now, now)
        )
        self.db.commit()

    def recall(self, query: str, category: str = None, top_k: int = 5) -> List[Dict]:
        """语义检索记忆"""
        q_emb = _simple_embed(query, self.dim)
        rows = self.db.execute(
            "SELECT * FROM memories WHERE 1=1" + (f" AND category='{category}'" if category else ""),
        ).fetchall()

        scored = []
        for r in rows:
            try:
                emb = json.loads(r["embedding"])
                sim = cosine_sim(q_emb, emb)
                # Boost by importance and recency
                recency = 1.0 / (1.0 + (time.time() - r["last_access"]) / 86400)
                score = sim * 0.6 + r["importance"] * 0.25 + recency * 0.15
                scored.append((score, dict(r)))
            except:
                pass

        scored.sort(key=lambda x: x[0], reverse=True)
        results = []
        for score, row in scored[:top_k]:
            self.db.execute(
                "UPDATE memories SET access_count = access_count + 1, last_access = ? WHERE id = ?",
                (time.time(), row["id"])
            )
            row["_score"] = round(score, 3)
            results.append(row)
        self.db.commit()
        return results

    def forget(self, memory_id: int):
        """删除一条记忆"""
        self.db.execute("DELETE FROM memories WHERE id=?", (memory_id,))
        self.db.commit()

    def build_context(self, query: str, max_tokens: int = 2000) -> str:
        """构建 Agent 上下文 — 从记忆中检索相关片段"""
        results = self.recall(query, top_k=8)
        if not results:
            return ""
        lines = ["[相关记忆]"]
        for r in results:
            lines.append(f"- [{r['category']}] {r['content'][:300]}")
        return "\n".join(lines)[:max_tokens]

    def get_preferences(self) -> List[str]:
        """获取用户偏好记忆"""
        results = self.recall("偏好 喜欢 习惯 常用", category="preference", top_k=10)
        return [r["content"] for r in results]

    def stats(self) -> Dict:
        row = self.db.execute(
            "SELECT COUNT(*) as total, AVG(importance) as avg_imp, SUM(access_count) as total_access FROM memories"
        ).fetchone()
        return {"total": row["total"], "avg_importance": round(row["avg_imp"] or 0, 2),
                "total_accesses": row["total_access"] or 0}

    def cleanup_low_value(self, threshold: int = 0):
        """清理低价值记忆（访问次数 <= threshold）"""
        self.db.execute("DELETE FROM memories WHERE access_count <= ? AND importance < 0.2", (threshold,))
        self.db.commit()


# ═══════ Global instance ═══════

rag = RAGMemory()

# ═══════ CLI ═══════

if __name__ == "__main__":
    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        if cmd == "remember" and len(sys.argv) > 2:
            rag.remember(" ".join(sys.argv[2:]))
            print("已记住")
        elif cmd == "recall" and len(sys.argv) > 2:
            for r in rag.recall(" ".join(sys.argv[2:])):
                print(f"  [{r['_score']}] [{r['category']}] {r['content'][:100]}")
        elif cmd == "stats":
            print(rag.stats())
    else:
        print(f"RAG Memory: {rag.stats()['total']} 条记忆")
