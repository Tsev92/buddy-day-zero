"""Presentation smoke tests: no API requests, no microphone, no network."""
import os
import tempfile
import unittest
from pathlib import Path
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from buddy.bubbles import split_phrases
from buddy.face import Face
from buddy.core import BuddyCore
from buddy.memory import Memory
from buddy.brain import Brain
from buddy.desktop import DesktopBuddy
from buddy.listening import SilenceDetector

class PresentationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def test_bubble_phrases(self):
        text = 'Oh! This is fascinating. Are you telling me the moon moves the ocean? Really!'
        parts = split_phrases(text, 55)
        self.assertGreater(len(parts), 1)
        self.assertEqual(' '.join(parts).split(), text.split())
        self.assertTrue(all(len(part) <= 55 for part in parts))

    def test_face_modes(self):
        face = Face()
        face.progress(65)
        self.assertEqual(face.update_percent, 65)
        face.celebrate()
        self.assertTrue(face.celebrating)
        face.progress(None)
        face.close()

    def test_floating_shell(self):
        with tempfile.TemporaryDirectory() as folder:
            core = BuddyCore(Path(folder))
            memory = Memory(Path(folder))
            buddy = DesktopBuddy(core, memory, Brain(memory))
            self.assertTrue(buddy.windowFlags() & buddy.windowFlags().FramelessWindowHint)
            self.assertIsNotNone(buddy.bubbles)
            self.assertIsNotNone(buddy.wake_listener)
            buddy.wake_listener.stop()
            buddy.close()

    def test_ends_speech_without_click(self):
        d = SilenceDetector()
        base = d.began
        import array
        speech = array.array('h', [6000] * 5000).tobytes()
        self.assertEqual(d.inspect(speech, base + 0.3), 'keep')
        self.assertEqual(d.inspect(speech, base + 0.5), 'keep')
        self.assertEqual(d.inspect(b'', base + 2.2), 'send')

if __name__ == '__main__':
    unittest.main()
