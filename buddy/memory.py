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
            self.db.execute("CREATE TABLE IF NOT EXISTS reflection_calls (id INTEGER PRIMARY KEY, created TEXT NOT NULL)")
            self.db.execute("CREATE TABLE IF NOT EXISTS mind_meta (name TEXT PRIMARY KEY, value TEXT NOT NULL)")
            self.db.execute("CREATE TABLE IF NOT EXISTS ideas (id INTEGER PRIMARY KEY, created TEXT NOT NULL, title TEXT NOT NULL, detail TEXT NOT NULL, kind TEXT NOT NULL, source TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'new')")
            self.db.execute("CREATE TABLE IF NOT EXISTS beliefs (topic TEXT PRIMARY KEY, stance TEXT NOT NULL, reason TEXT NOT NULL, confidence INTEGER NOT NULL, updated TEXT NOT NULL)")
            self.db.execute("CREATE TABLE IF NOT EXISTS belief_history (id INTEGER PRIMARY KEY, created TEXT NOT NULL, topic TEXT NOT NULL, old_stance TEXT, new_stance TEXT NOT NULL, evidence TEXT NOT NULL)")
            self.db.execute("CREATE TABLE IF NOT EXISTS reflections (id INTEGER PRIMARY KEY, created TEXT NOT NULL, content TEXT NOT NULL, evidence TEXT NOT NULL)")
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
        return 'Current emotional state: ' + state + '\nFormative experiences:\n' + (history or 'None recorded yet.')

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

    def ideas(self, include_dismissed=False, limit=40):
        with self.lock:
            q = ('SELECT id,title,detail,kind,source,status,created FROM ideas ' +
                 ('' if include_dismissed else "WHERE status!='dismissed' ") +
                 'ORDER BY id DESC LIMIT ?')
            rows = self.db.execute(q,(limit,)).fetchall()
        return [dict(zip(('id','title','detail','kind','source','status','created'),r)) for r in rows]

    def add_idea(self, title, detail, kind='curiosity', source='conversation'):
        if kind not in ('curiosity','interest','project') or source not in ('conversation','reflection','manual'):
            raise ValueError('Unrecognized idea provenance')
        title,detail = str(title).strip()[:110],str(detail).strip()[:600]
        if len(title)<4 or len(detail)<8: return False
        with self.lock,self.db:
            existing = self.db.execute("SELECT id FROM ideas WHERE lower(title)=lower(?) AND status!='dismissed'",(title,)).fetchone()
            if existing: return False
            self.db.execute('INSERT INTO ideas(created,title,detail,kind,source,status) VALUES(?,?,?,?,?,?)',
                 (datetime.now(timezone.utc).isoformat(),title,detail,kind,source,'new'))
        return True

    def set_idea_status(self, idea_id, status):
        if status not in ('new','exploring','developing','set_aside','discussed','dismissed'):
            raise ValueError('Invalid idea status')
        with self.lock,self.db:
            self.db.execute('UPDATE ideas SET status=? WHERE id=?',(status,int(idea_id)))

    def beliefs(self, limit=24):
        with self.lock:
            rows=self.db.execute('SELECT topic,stance,reason,confidence,updated FROM beliefs ORDER BY updated DESC LIMIT ?',(limit,)).fetchall()
        return [dict(zip(('topic','stance','reason','confidence','updated'),r)) for r in rows]

    def consider_belief(self, topic, stance, reason, confidence=1):
        topic,stance,reason=(str(v).strip()[:length] for v,length in ((topic,90),(stance,350),(reason,350)))
        if not topic or len(stance)<8 or len(reason)<8: return False
        confidence=max(1,min(5,int(confidence)))
        now=datetime.now(timezone.utc).isoformat()
        with self.lock,self.db:
            old=self.db.execute('SELECT stance,confidence FROM beliefs WHERE topic=?',(topic,)).fetchone()
            if old and old[0]==stance: return False
            self.db.execute('INSERT OR REPLACE INTO beliefs(topic,stance,reason,confidence,updated) VALUES(?,?,?,?,?)',
                            (topic,stance,reason,confidence,now))
            self.db.execute('INSERT INTO belief_history(created,topic,old_stance,new_stance,evidence) VALUES(?,?,?,?,?)',
                            (now,topic,old[0] if old else None,stance,reason))
        return True

    def add_reflection(self, content, evidence):
        content,evidence=str(content).strip()[:700],str(evidence).strip()[:400]
        if len(content)<10 or not evidence: return False
        with self.lock,self.db:
            self.db.execute('INSERT INTO reflections(created,content,evidence) VALUES(?,?,?)',
                            (datetime.now(timezone.utc).isoformat(),content,evidence))
        return True

    def reflections(self, limit=12):
        with self.lock:
            rows=self.db.execute('SELECT created,content,evidence FROM reflections ORDER BY id DESC LIMIT ?',(limit,)).fetchall()
        return [dict(zip(('created','content','evidence'),r)) for r in rows]

    def reflection_budget_used(self, date):
        with self.lock:
            return self.db.execute('SELECT COUNT(*) FROM reflections WHERE substr(created,1,10)=?',(date,)).fetchone()[0]

    def history(self, limit=16):
        with self.lock:
            rows=self.db.execute('SELECT created,topic,old_stance,new_stance,evidence FROM belief_history ORDER BY id DESC LIMIT ?',(limit,)).fetchall()
        return [dict(zip(('created','topic','previous','current','reason'),r)) for r in rows]

    def character_sheet(self):
        with self.lock:
            emotions=dict(self.db.execute('SELECT name,intensity FROM emotions'))
            events=self.db.execute('SELECT emotion, COUNT(*) FROM experiences GROUP BY emotion').fetchall()
            messages=self.db.execute('SELECT COUNT(*) FROM messages').fetchone()[0]
        evidence=dict(events)
        # A numerical score requires evidence. Unknown traits are NOT zeros.
        traits={'Curiosity': 'curiosity','Confidence':'confidence','Affection':'affection',
                'Emotional openness':'joy','Independence':None,'Sociability':None,'Playfulness':None}
        return {
            'messages':messages,
            'emotions':{k:emotions.get(k,2) for k in self.EMOTIONS},
            'traits':{name:(min(100,emotions.get(key,2)*20) if key and evidence.get(key,0)>=2 else None)
                      for name,key in traits.items()},
            'evidence':evidence,
            'ideas':self.ideas(),'beliefs':self.beliefs(),'reflections':self.reflections(),
            'history':self.history()
        }

    def reflection_due(self):
        with self.lock:
            last = self.db.execute("SELECT value FROM mind_meta WHERE name='last_reflection_messages'").fetchone()
            prior = int(last[0]) if last else 0
            return self.count() >= 2 and self.count() > prior

    def reflection_calls_today(self, date):
        with self.lock:
            return self.db.execute('SELECT COUNT(*) FROM reflection_calls WHERE substr(created,1,10)=?',(date,)).fetchone()[0]

    def mark_reflection_attempt(self):
        with self.lock,self.db:
            self.db.execute('INSERT INTO reflection_calls(created) VALUES(?)',
                            (datetime.now(timezone.utc).isoformat(),))
            self.db.execute("INSERT OR REPLACE INTO mind_meta(name,value) VALUES('last_reflection_messages',?)",(str(self.count()),))
