"""
AI Suite — Local RAG (v4.0)
本地文档索引与检索：索引目录下所有文本/PDF/代码文件
用法:
  from local_rag import LocalRAG
  rag = LocalRAG()
  rag.index_directory("~/Documents")
  results = rag.search("machine learning tutorial")
"""

import os, json, time, hashlib, sqlite3, re
from typing import List, Dict

RAG_DIR = os.path.expanduser("~/.ai-suite")
DB_PATH = os.path.join(RAG_DIR, "local_rag.db")

# ═══════ Embedding ═══════

def _chunk_embed(text: str, dim: int = 256) -> List[float]:
    """Same simple embed as rag_memory.py for consistency"""
    text = text.lower()
    vec = [0.0] * dim
    for i in range(len(text) - 2):
        h = hashlib.md5(text[i:i+3].encode()).digest()
        for j in range(0, len(h), 2):
            idx = int.from_bytes(h[j:j+2], 'big') % dim
            vec[idx] += 0.05
    words = text.split()
    for i in range(len(words) - 1):
        h = hashlib.md5(f"{words[i]}_{words[i+1]}".encode()).digest()
        for j in range(0, len(h), 2):
            idx = int.from_bytes(h[j:j+2], 'big') % dim
            vec[idx] += 0.1
    norm = sum(v * v for v in vec) ** 0.5
    return [v / norm for v in vec] if norm > 0 else vec

def _cosine(a, b):
    return sum(x * y for x, y in zip(a, b))

# ═══════ Local RAG ═══════

class LocalRAG:
    def __init__(self, dim: int = 256):
        self.dim = dim
        os.makedirs(RAG_DIR, exist_ok=True)
        self.db = sqlite3.connect(DB_PATH)
        self.db.row_factory = sqlite3.Row
        self._init_db()

    def _init_db(self):
        self.db.executescript("""
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_path TEXT UNIQUE NOT NULL,
                file_type TEXT,
                size_bytes INTEGER,
                indexed_at REAL
            );
            CREATE TABLE IF NOT EXISTS chunks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                doc_id INTEGER REFERENCES documents(id),
                chunk_index INTEGER,
                content TEXT,
                embedding BLOB,
                token_count INTEGER DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_chunks_doc ON chunks(doc_id);
        """)
        self.db.commit()

    def index_file(self, file_path: str, chunk_size: int = 500) -> int:
        """索引单个文件"""
        if not os.path.exists(file_path):
            return 0
        file_path = os.path.abspath(file_path)

        # Check if already indexed
        existing = self.db.execute(
            "SELECT id FROM documents WHERE file_path=?", (file_path,)
        ).fetchone()
        if existing:
            self.db.execute("DELETE FROM chunks WHERE doc_id=?", (existing["id"],))
            self.db.execute("DELETE FROM documents WHERE id=?", (existing["id"],))

        # Read file
        ext = os.path.splitext(file_path)[1].lower()
        try:
            if ext in ('.py', '.js', '.ts', '.html', '.css', '.json', '.txt', '.md',
                       '.c', '.cpp', '.h', '.rs', '.java', '.go', '.yaml', '.yml',
                       '.toml', '.sh', '.bat', '.ps1', '.csv', '.xml', '.ini', '.cfg'):
                with open(file_path, 'r', encoding='utf-8', errors='replace') as f:
                    text = f.read()
            elif ext == '.pdf':
                try:
                    import PyPDF2
                    reader = PyPDF2.PdfReader(file_path)
                    text = "\n".join(page.extract_text() or "" for page in reader.pages)
                except ImportError:
                    return 0
            elif ext in ('.docx', '.doc'):
                try:
                    import docx
                    doc = docx.Document(file_path)
                    text = "\n".join(p.text for p in doc.paragraphs)
                except ImportError:
                    return 0
            else:
                return 0  # unsupported type
        except:
            return 0

        if not text or not text.strip():
            return 0

        # Insert document
        self.db.execute(
            "INSERT INTO documents(file_path, file_type, size_bytes, indexed_at) VALUES(?,?,?,?)",
            (file_path, ext, len(text), time.time())
        )
        doc_id = self.db.execute("SELECT last_insert_rowid()").fetchone()[0]

        # Chunk and embed
        chunks = self._chunk_text(text, chunk_size)
        for i, chunk in enumerate(chunks):
            emb = _chunk_embed(chunk, self.dim)
            self.db.execute(
                "INSERT INTO chunks(doc_id, chunk_index, content, embedding, token_count) VALUES(?,?,?,?,?)",
                (doc_id, i, chunk, json.dumps(emb), len(chunk.split()))
            )

        self.db.commit()
        return len(chunks)

    def index_directory(self, directory: str) -> Dict:
        """索引整个目录"""
        directory = os.path.expanduser(directory)
        if not os.path.isdir(directory):
            return {"ok": False, "error": f"Not a directory: {directory}"}
        total_files = 0
        total_chunks = 0
        for root, dirs, files in os.walk(directory):
            dirs[:] = [d for d in dirs if not d.startswith('.')]
            for f in files:
                if f.startswith('.') or f.startswith('~'):
                    continue
                fp = os.path.join(root, f)
                chunks = self.index_file(fp)
                if chunks:
                    total_files += 1
                    total_chunks += chunks
        return {"ok": True, "files": total_files, "chunks": total_chunks, "directory": directory}

    def search(self, query: str, top_k: int = 5) -> List[Dict]:
        """搜索相关文档片段"""
        q_emb = _chunk_embed(query, self.dim)
        rows = self.db.execute("""
            SELECT c.*, d.file_path FROM chunks c
            JOIN documents d ON c.doc_id = d.id
        """).fetchall()

        scored = []
        for r in rows:
            try:
                emb = json.loads(r["embedding"])
                sim = _cosine(q_emb, emb)
                scored.append((sim, dict(r)))
            except:
                pass

        scored.sort(key=lambda x: x[0], reverse=True)
        return [{"score": round(s, 3), "file": r["file_path"],
                 "content": r["content"][:500]} for s, r in scored[:top_k]]

    def build_context(self, query: str, max_tokens: int = 3000) -> str:
        """构建 RAG 上下文"""
        results = self.search(query, top_k=5)
        if not results:
            return ""
        lines = [f"[文档检索结果: {query}]"]
        for r in results:
            lines.append(f"--- {r['file']} (相关度: {r['score']}) ---")
            lines.append(r['content'][:500])
        return "\n".join(lines)[:max_tokens]

    def _chunk_text(self, text: str, size: int) -> List[str]:
        """将文本切分为重叠的 chunks"""
        chunks = []
        words = text.split()
        for i in range(0, len(words), size // 2):
            chunk = " ".join(words[i:i + size])
            if len(chunk) > 20:
                chunks.append(chunk)
        return chunks

    def stats(self) -> Dict:
        docs = self.db.execute("SELECT COUNT(*) as c FROM documents").fetchone()["c"]
        chunks = self.db.execute("SELECT COUNT(*) as c FROM chunks").fetchone()["c"]
        return {"documents": docs, "chunks": chunks}

    def clear_index(self):
        self.db.execute("DELETE FROM chunks")
        self.db.execute("DELETE FROM documents")
        self.db.commit()


# ═══════ Global instance ═══════

local_rag = LocalRAG()

# ═══════ CLI ═══════

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        if cmd == "index" and len(sys.argv) > 2:
            path = os.path.expanduser(sys.argv[2])
            if os.path.isdir(path):
                r = local_rag.index_directory(path)
                print(f"Indexed {r['files']} files, {r['chunks']} chunks")
            else:
                chunks = local_rag.index_file(path)
                print(f"Indexed {chunks} chunks")
        elif cmd == "search" and len(sys.argv) > 2:
            for r in local_rag.search(" ".join(sys.argv[2:])):
                print(f"[{r['score']}] {r['file']}: {r['content'][:100]}")
        elif cmd == "stats":
            print(local_rag.stats())
    else:
        print(local_rag.stats())
