"""Buddy Day Zero: native desktop companion with self-updating code."""
import os
import sys
from pathlib import Path
from buddy.core import BuddyCore
from buddy.memory import Memory
from buddy.brain import Brain


def load_local_env(path):
    if not path.is_file(): return
    for line in path.read_text(encoding='utf-8-sig').splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line: continue
        key, value = line.split('=', 1)
        if key.strip() in ('OPENAI_API_KEY', 'BUDDY_MODEL', 'BUDDY_GITHUB_REPO'):
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def main():
    from PySide6.QtWidgets import QApplication
    from buddy.desktop import DesktopBuddy
    root = Path(__file__).resolve().parent
    load_local_env(root / '.env')
    app = QApplication(sys.argv)
    app.setApplicationName('Buddy Day Zero')
    core = BuddyCore(root / 'data')
    memory = Memory(root / 'data')
    window = DesktopBuddy(core, memory, Brain(memory))
    window.show()
    return app.exec()

if __name__ == '__main__':
    raise SystemExit(main())
