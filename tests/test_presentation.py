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
            message = 'One two three four five six seven eight nine ten.'
            bubble.begin(message, 1600)
            first = bubble.bubble.content
            QTest.qWait(850)
            self.assertGreater(len(bubble.bubble.content.split()), 1)
            self.assertGreater(len(bubble.bubble.content), len(first))
            QTest.qWait(900)
            self.assertEqual(bubble.bubble.content, message)
            self.assertEqual(bubble.full_text, message)
            self.assertLessEqual(bubble.bubble.height(), buddy.height())
            bubble.stop()
            buddy.wake_listener.stop()
            buddy.close()

    def test_one_bubble_autoscrolls_full_long_reply(self):
        with tempfile.TemporaryDirectory() as folder:
            memory = Memory(Path(folder))
            buddy = DesktopBuddy(BuddyCore(Path(folder)), memory, Brain(memory))
            buddy.show()
            message = ' '.join('Sentence %s has many wonderful little words.' % i for i in range(35))
            bubbles = buddy.bubbles
            bubbles.begin(message, 4000)
            bubbles.sync_position(2000)
            self.assertGreater(len(bubbles.bubble.content.split()), 25)
            self.assertLessEqual(bubbles.bubble.height(), buddy.height())
            self.assertGreater(bubbles.bubble._scroll_target, 0)
            first_window = bubbles.bubble.winId()
            bubbles.sync_position(3900)
            self.assertEqual(bubbles.bubble.winId(), first_window)
            bubbles.speaking_finished()
            self.assertEqual(bubbles.bubble.content, message)
            self.assertEqual(bubbles.bubble._scroll, bubbles.bubble._scroll_target)
            self.assertLessEqual(bubbles.bubble.height(), buddy.height())
            bubbles.stop()
            buddy.wake_listener.stop()
            buddy.close()

    def test_empty_or_stalled_caption_shows_full_answer_on_finish(self):
        with tempfile.TemporaryDirectory() as folder:
            memory = Memory(Path(folder))
            buddy = DesktopBuddy(BuddyCore(Path(folder)), memory, Brain(memory))
            message = 'The complete response should always appear at the end of speech.'
            buddy.bubbles.begin(message, 5000)
            buddy.bubbles.speaking_finished()
            self.assertEqual(buddy.bubbles.bubble.content, message)
            buddy.bubbles.stop()
            buddy.wake_listener.stop()
            buddy.close()

    def test_bubble_real_text_widget_renders_more_than_first_word(self):
        from PySide6.QtWidgets import QTextEdit
        with tempfile.TemporaryDirectory() as folder:
            memory = Memory(Path(folder))
            buddy = DesktopBuddy(BuddyCore(Path(folder)), memory, Brain(memory))
            buddy.show()
            bubble = buddy.bubbles
            message = 'I definitely say many more words after the first word.'
            bubble.begin(message, 1600)
            self.assertIsInstance(bubble.bubble.text_view, QTextEdit)
            QTest.qWait(700)
            self.app.processEvents()
            self.assertGreater(len(bubble.bubble.text_view.toPlainText().split()), 1)
            self.assertFalse(bubble.bubble.text_view.grab().isNull())
            bubble.speaking_finished()
            self.assertEqual(bubble.bubble.text_view.toPlainText(), message)
            bubble.stop()
            buddy.wake_listener.stop()
            buddy.close()

    def test_customization_and_action_faces(self):
        face = Face()
        face.resize(360,203)
        face.customize(eyes='pupils', mouth='lips', color='#ffc1de', eyebrows='single')
        self.assertEqual(face.mouth_style, 'lips')
        self.assertEqual(face.eyebrow_style, 'single')
        face.show()
        for mood in ('idle','listening','thinking','speaking','error'):
            face.mood = mood
            face.mic_level = .8
            face.animate()
            self.app.processEvents()
            self.assertFalse(face.grab().isNull(), mood)
        face.customize(eyes='pixel', mouth='cat', eyebrows='both')
        self.app.processEvents()
        self.assertFalse(face.grab().isNull())
        face.close()

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
