"""Platform-independent state, settings and confirmed actions."""
import json
import os
import secrets
import threading
from pathlib import Path

DEFAULTS = {"name": "Buddy", "voice_enabled": True, "speech_rate": 1.0, "volume": 75}

class BuddyCore:
    def __init__(self, data_dir):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.path = self.data_dir / 'settings.json'
        self.lock = threading.RLock()
        self.settings = dict(DEFAULTS)
        if self.path.exists():
            try:
                loaded = json.loads(self.path.read_text(encoding='utf-8'))
                for key, value in loaded.items():
                    if key in DEFAULTS:
                        self.settings[key] = self.validate(key, value)
            except (OSError, ValueError, TypeError):
                # Bad settings should not prevent Buddy from starting.
                pass
        self.pending = {}
        self.save()

    @staticmethod
    def validate(key, value):
        if key == 'name':
            if not isinstance(value, str) or not 1 <= len(value.strip()) <= 40:
                raise ValueError('Name must be 1–40 characters')
            return value.strip()
        if key == 'voice_enabled':
            if not isinstance(value, bool):
                raise ValueError('Voice enabled must be true or false')
            return value
        if key == 'speech_rate':
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0.5 <= value <= 2.0:
                raise ValueError('Speech rate must be between 0.5 and 2.0')
            return float(value)
        if key == 'volume':
            if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 100:
                raise ValueError('Volume must be between 0 and 100')
            return value
        raise ValueError('Unknown setting')

    def save(self):
        with self.lock:
            tmp = self.path.with_suffix('.tmp')
            tmp.write_text(json.dumps(self.settings, indent=2), encoding='utf-8')
            os.replace(tmp, self.path)

    def snapshot(self):
        with self.lock:
            return dict(self.settings)

    def propose(self, key, value):
        value = self.validate(key, value)
        with self.lock:
            token = secrets.token_urlsafe(24)
            self.pending[token] = (key, value)
            return token

    def resolve(self, token, confirm):
        with self.lock:
            change = self.pending.pop(token, None)
            if change is None:
                raise ValueError('Change expired or already handled')
            if confirm:
                key, value = change
                self.settings[key] = value
                self.save()
            return self.snapshot()
