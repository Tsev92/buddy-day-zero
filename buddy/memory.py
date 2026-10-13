"""Fresh, independent Day Zero memory. Never opens a legacy Buddy database."""
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

class Memory:
    def __init__(self, data_dir):
        path = Path(data_dir)
        path.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path / 'day_zero.db', check_same_thread=False)
        self.lock = threading.RLock()
        with self.lock, self.db:
            self.db.execute('CREATE TABLE IF NOT EXISTS messages (id INTEGER PRIMARY KEY, created TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN (\'user\',\'assistant\')), content TEXT NOT NULL)')
            self.db.execute('CREATE TABLE IF NOT EXISTS observations (id INTEGER PRIMARY KEY, created TEXT NOT NULL, detail TEXT NOT NULL, evidence TEXT NOT NULL)')

    def add(self, role, content):
        if role not in ('user', 'assistant') or not isinstance(content, str) or not content.strip():
            raise ValueError('Invalid memory entry')
        with self.lock, self.db:
            self.db.execute('INSERT INTO messages(created,role,content) VALUES(?,?,?)', (datetime.now(timezone.utc).isoformat(), role, content.strip()))

    def recent(self, limit=24):
        with self.lock:
            rows = self.db.execute('SELECT role,content FROM (SELECT id,role,content FROM messages ORDER BY id DESC LIMIT ?) ORDER BY id', (limit,)).fetchall()
        return [{'role': r, 'content': c} for r,c in rows]

    def count(self):
        with self.lock:
            return self.db.execute('SELECT COUNT(*) FROM messages').fetchone()[0]

    def observations(self):
        with self.lock:
            return [{'detail': d, 'evidence': e} for d,e in self.db.execute('SELECT detail,evidence FROM observations ORDER BY id DESC LIMIT 12')]

    def add_observation(self, detail, evidence):
        if not detail.strip() or not evidence.strip():
            raise ValueError('Observation requires evidence')
        with self.lock, self.db:
            self.db.execute('INSERT INTO observations(created,detail,evidence) VALUES(?,?,?)', (datetime.now(timezone.utc).isoformat(),detail.strip(),evidence.strip()))
