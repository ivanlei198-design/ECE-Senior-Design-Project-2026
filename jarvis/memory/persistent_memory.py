import sqlite3
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent / "jarvis_memory.db"

class PersistentMemory:
    def __init__(self):
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        self._init_db()

    def _init_db(self):
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS facts (key TEXT PRIMARY KEY, value TEXT, updated_at TEXT);
            CREATE TABLE IF NOT EXISTS conversations (id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT, user_input TEXT, response TEXT);
            CREATE TABLE IF NOT EXISTS agent_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT, agent TEXT, task TEXT, result TEXT, success INTEGER);
            CREATE TABLE IF NOT EXISTS code_snapshots (id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT, filename TEXT, code TEXT, language TEXT);
        """)
        self.conn.commit()

    def store(self, key, value):
        self.conn.execute("INSERT OR REPLACE INTO facts VALUES (?,?,?)", (key, str(value), datetime.now().isoformat()))
        self.conn.commit()

    def recall(self, key):
        r = self.conn.execute("SELECT value FROM facts WHERE key=?", (key,)).fetchone()
        return r[0] if r else None

    def recall_all(self):
        return {k: v for k, v in self.conn.execute("SELECT key,value FROM facts").fetchall()}

    def recall_prefix(self, prefix):
        rows = self.conn.execute("SELECT key,value FROM facts WHERE key LIKE ?", (prefix + "%",)).fetchall()
        return {k: v for k, v in rows}

    def forget(self, key):
        self.conn.execute("DELETE FROM facts WHERE key=?", (key,))
        self.conn.commit()

    def log_conversation(self, user_input, response):
        self.conn.execute("INSERT INTO conversations (timestamp,user_input,response) VALUES (?,?,?)",
                          (datetime.now().isoformat(), user_input, response[:2000]))
        self.conn.commit()

    def get_conversation_context(self, n=5):
        rows = self.conn.execute("SELECT user_input,response FROM conversations ORDER BY id DESC LIMIT ?", (n,)).fetchall()
        return "\n".join(f"User: {r[0]}\nAssistant: {r[1][:200]}" for r in reversed(rows))

    def log_agent(self, agent, task, result, success=True):
        self.conn.execute("INSERT INTO agent_logs (timestamp,agent,task,result,success) VALUES (?,?,?,?,?)",
                          (datetime.now().isoformat(), agent, task[:500], result[:1000], int(success)))
        self.conn.commit()

    def save_code(self, filename, code, language="python"):
        self.conn.execute("INSERT INTO code_snapshots (timestamp,filename,code,language) VALUES (?,?,?,?)",
                          (datetime.now().isoformat(), filename, code, language))
        self.conn.commit()

    def get_latest_code(self, filename):
        r = self.conn.execute("SELECT code FROM code_snapshots WHERE filename=? ORDER BY id DESC LIMIT 1", (filename,)).fetchone()
        return r[0] if r else None
