"""Presentation smoke tests: no API requests, no microphone, no network."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import io, math, struct, wave
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from buddy.bubbles import BubbleController
from buddy.bubbles import split_phrases
from buddy.face import Face
from buddy.core import BuddyCore
from buddy.memory import Memory
from buddy.brain import Brain
from buddy.desktop import DesktopBuddy
from buddy.listening import SilenceDetector
from buddy.speech_visuals import voice_envelope

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
        face.show()
        self.app.processEvents()
        self.assertFalse(face.grab().isNull())
        face.celebrate()
        self.app.processEvents()
        self.assertFalse(face.grab().isNull())
        self.assertTrue(face.celebrating)
        face.progress(None)
        face.close()

    def test_floating_shell(self):
        with tempfile.TemporaryDirectory() as folder:
            core = BuddyCore(Path(folder))
            memory = Memory(Path(folder))
            buddy = DesktopBuddy(core, memory, Brain(memory))
            self.assertTrue(buddy.windowFlags() & Qt.FramelessWindowHint)
            self.assertIsNotNone(buddy.bubbles)
            self.assertIsNotNone(buddy.wake_listener)
            buddy.wake_listener.stop()
            buddy.close()

    def test_hidden_conversation_mode(self):
        with tempfile.TemporaryDirectory() as folder:
            buddy = DesktopBuddy(BuddyCore(Path(folder)),
                                 Memory(Path(folder)), Brain(Memory(Path(folder))))
            with patch('buddy.desktop.ChatDialog.toggle_microphone'):
                buddy.open_conversation()
            self.assertTrue(buddy.chat_dialog.conversation_mode)
            self.assertFalse(buddy.chat_dialog.isVisible())
            buddy.end_conversation()
            self.assertFalse(buddy.chat_dialog.conversation_mode)
            buddy.wake_listener.stop()
            buddy.close()

    def test_waveform_follows_audio_pauses(self):
        output = io.BytesIO()
        with wave.open(output, 'wb') as sound:
            sound.setnchannels(1)
            sound.setsampwidth(2)
            sound.setframerate(16000)
            frames = [0]*1600 + [int(12000*math.sin(i*.15)) for i in range(3200)] + [0]*1600
            sound.writeframes(struct.pack('<%dh'%len(frames),*frames))
        levels = voice_envelope(output.getvalue())
        self.assertGreater(max(levels), .4)
        self.assertEqual(levels[0],0.)
        self.assertEqual(levels[-1],0.)

    def test_bubbles_keep_revealing_without_player_position_events(self):
        with tempfile.TemporaryDirectory() as folder:
            memory = Memory(Path(folder))
            buddy = DesktopBuddy(BuddyCore(Path(folder)), memory, Brain(memory))
            buddy.show()
            bubble = buddy.bubbles
            bubble.begin('One two three four five six seven eight nine ten.', 1600)
            first = bubble.bubble.content
            QTest.qWait(850)
            self.assertGreater(len(bubble.bubble.content.split()), 1)
            self.assertGreater(len(bubble.bubble.content), len(first))
            QTest.qWait(900)
            self.assertEqual(bubble.bubble.content,
                             'One two three four five six seven eight nine ten.')
            bubble.stop()
            buddy.wake_listener.stop()
            buddy.close()

    def test_spinner_and_listening_brackets_render(self):
        face = Face()
        face.resize(360,203)
        face.mood = 'listening'
        face.show()
        self.app.processEvents()
        listening = face.grab().toImage()
        face.mood = 'idle'
        self.app.processEvents()
        idle = face.grab().toImage()
        self.assertNotEqual(listening, idle)
        face.progress(-1)
        self.app.processEvents()
        first = face.grab().toImage()
        face.tick += 20
        self.app.processEvents()
        second = face.grab().toImage()
        self.assertNotEqual(first,second)
        face.close()

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
