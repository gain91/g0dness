"""
AI Suite — SQLite 对话持久化
conversations: 会话列表
messages: 每条消息 (role, content, tokens, time)
"""
import sqlite3, json, time, os

DB_PATH = os.path.expanduser("~/.ai-suite/memory.db")
os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn

def init():
    db = get_db()
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA encoding='UTF-8'")
    db.execute("PRAGMA case_sensitive_like=OFF")
    db.executescript("""
        CREATE TABLE IF NOT EXISTS conversations (
            id TEXT PRIMARY KEY,
            title TEXT DEFAULT 'New Chat',
            model TEXT DEFAULT 'ollama',
            created_at REAL,
            updated_at REAL
        );
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conv_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            tokens INTEGER DEFAULT 0,
            created_at REAL,
            FOREIGN KEY (conv_id) REFERENCES conversations(id)
        );
        CREATE INDEX IF NOT EXISTS idx_msg_conv ON messages(conv_id);
    """)
    db.commit()
    db.close()

init()

# ─── Conversations ───

def list_convs(limit=50):
    db = get_db()
    rows = db.execute(
        "SELECT * FROM conversations ORDER BY updated_at DESC LIMIT ?", (limit,)
    ).fetchall()
    db.close()
    return [dict(r) for r in rows]

def create_conv(conv_id=None, title="New Chat", model="ollama"):
    db = get_db()
    cid = conv_id or f"conv_{int(time.time()*1000)}"
    now = time.time()
    db.execute(
        "INSERT OR REPLACE INTO conversations(id, title, model, created_at, updated_at) VALUES(?,?,?,?,?)",
        (cid, title, model, now, now)
    )
    db.commit()
    db.close()
    return cid

def delete_conv(conv_id):
    db = get_db()
    db.execute("DELETE FROM messages WHERE conv_id=?", (conv_id,))
    db.execute("DELETE FROM conversations WHERE id=?", (conv_id,))
    db.commit()
    db.close()

def update_conv_title(conv_id, title):
    db = get_db()
    db.execute("UPDATE conversations SET title=?, updated_at=? WHERE id=?",
               (title, time.time(), conv_id))
    db.commit()
    db.close()

# ─── Messages ───

def add_message(conv_id, role, content, tokens=0):
    db = get_db()
    now = time.time()
    db.execute(
        "INSERT INTO messages(conv_id, role, content, tokens, created_at) VALUES(?,?,?,?,?)",
        (conv_id, role, content, tokens, now)
    )
    # auto-title: first user message
    if role == 'user':
        existing = db.execute("SELECT COUNT(*) FROM messages WHERE conv_id=? AND role='user'", (conv_id,)).fetchone()[0]
        if existing == 1:
            title = content[:40].replace('\n',' ') + ('...' if len(content)>40 else '')
            db.execute("UPDATE conversations SET title=?, updated_at=? WHERE id=?", (title, now, conv_id))
    else:
        db.execute("UPDATE conversations SET updated_at=? WHERE id=?", (now, conv_id))
    db.commit()
    db.close()

def get_messages(conv_id, limit=200):
    db = get_db()
    rows = db.execute(
        "SELECT * FROM messages WHERE conv_id=? ORDER BY id ASC LIMIT ?", (conv_id, limit)
    ).fetchall()
    db.close()
    return [dict(r) for r in rows]

def clear_messages(conv_id):
    db = get_db()
    db.execute("DELETE FROM messages WHERE conv_id=?", (conv_id,))
    db.commit()
    db.close()

def search_messages(query, limit=20):
    db = get_db()
    rows = db.execute(
        "SELECT m.*, c.title as conv_title FROM messages m JOIN conversations c ON m.conv_id=c.id "
        "WHERE m.content LIKE ? ORDER BY m.created_at DESC LIMIT ?",
        (f"%{query}%", limit)
    ).fetchall()
    db.close()
    return [dict(r) for r in rows]
