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
            self.db.execute('CREATE TABLE IF NOT EXISTS emotions (name TEXT PRIMARY KEY, intensity INTEGER NOT NULL DEFAULT 2)')
            self.db.execute('CREATE TABLE IF NOT EXISTS experiences (id INTEGER PRIMARY KEY, created TEXT NOT NULL, event TEXT NOT NULL, emotion TEXT NOT NULL, impact INTEGER NOT NULL)')
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

    EMOTIONS = ('joy','curiosity','confidence','affection','frustration','melancholy')

    def emotional_context(self):
        with self.lock:
            values = dict(self.db.execute('SELECT name,intensity FROM emotions'))
            events = self.db.execute(
                'SELECT event,emotion,impact FROM experiences ORDER BY id DESC LIMIT 6').fetchall()
        state = ', '.join('%s=%s/5' % (name,values.get(name,2)) for name in self.EMOTIONS)
        history = '\n'.join('- %s (%s, impact %s)' % (event,emotion,impact)
                             for event,emotion,impact in events)
        return 'Current emotional state: ' + state + '\nFormative experiences:\\n' + (history or 'None recorded yet.')

    def experience(self, event, emotion, impact=1):
        if emotion not in self.EMOTIONS or not isinstance(event,str) or not event.strip():
            raise ValueError('Experience requires a grounded event and recognized emotion')
        impact = max(-2,min(2,int(impact)))
        with self.lock, self.db:
            self.db.execute('INSERT INTO experiences(created,event,emotion,impact) VALUES(?,?,?,?)',
                            (datetime.now(timezone.utc).isoformat(),event[:260],emotion,impact))
            old = self.db.execute('SELECT intensity FROM emotions WHERE name=?',(emotion,)).fetchone()
            strength = max(0,min(5,(old[0] if old else 2)+impact))
            self.db.execute('INSERT OR REPLACE INTO emotions(name,intensity) VALUES(?,?)',(emotion,strength))
