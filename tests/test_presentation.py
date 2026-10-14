"""Presentation smoke tests: no API requests, no microphone, no network."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import io, math, struct, wave
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox
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
from buddy.audio import normalize_pcm_wav

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

    def test_repair_inflated_wav_duration_and_playback_bytes(self):
        from io import BytesIO
        import logging
        output = BytesIO()
        with wave.open(output, 'wb') as audio:
            audio.setnchannels(1)
            audio.setsampwidth(2)
            audio.setframerate(16000)
            audio.writeframes(b'\x00\x00' * 32000)
        original = bytearray(output.getvalue())
        # Simulate a streaming TTS WAV that claims millions of samples.
        struct.pack_into('<I', original, 40, 0x7fffffff)
        with wave.open(BytesIO(original), 'rb') as bad:
            self.assertGreater(bad.getnframes() / bad.getframerate(), 1000)
        with self.assertLogs('buddy.audio', level='WARNING') as captured:
            corrected, milliseconds = normalize_pcm_wav(bytes(original))
        self.assertEqual(milliseconds, 2000)
        self.assertTrue(any('repairing header' in line for line in captured.output))
        with wave.open(BytesIO(corrected), 'rb') as good:
            self.assertEqual(good.getnframes(), 32000)
            self.assertEqual(good.getframerate(), 16000)
            self.assertEqual(len(good.readframes(32000)), 64000)
        self.assertEqual(normalize_pcm_wav(corrected)[1], 2000)

    def test_signature_eyebrow_is_transient_and_left_only(self):
        face = Face()
        face.customize(eyebrows='single')
        face.mood = 'idle'
        face.expression = 'neutral'
        self.assertEqual(face.eyebrow_style, 'single')
        face.expression = 'skeptical'
        face.show()
        self.app.processEvents()
        self.assertFalse(face.grab().isNull())
        face.close()

    def test_independent_eye_and_pupil_choices(self):
        face = Face()
        face.customize(eyes='round', pupils='slit', mouth='lips')
        self.assertEqual(face.eye_style, 'round')
        self.assertEqual(face.pupil_style, 'slit')
        self.assertEqual(face.mouth_style, 'lips')
        face.show()
        for mood in ('thinking','speaking','idle','listening'):
            face.mood = mood
            face.audio_level = .8
            face.animate()
            self.app.processEvents()
            self.assertFalse(face.grab().isNull())
        face.close()

    def test_emotional_journal_persists_on_disk(self):
        with tempfile.TemporaryDirectory() as folder:
            memory = Memory(Path(folder))
            memory.add('user','Hello again')
            memory.experience('I feel happy about our progress','joy',1)
            self.assertIn('joy=3/5',memory.emotional_context())
            memory.db.close()
            again = Memory(Path(folder))
            self.assertIn('joy=3/5',again.emotional_context())
            self.assertEqual(again.count(),1)
            again.db.close()

    def test_settings_voice_options_and_expression_preview(self):
        with tempfile.TemporaryDirectory() as folder:
            memory = Memory(Path(folder))
            buddy = DesktopBuddy(BuddyCore(Path(folder)),memory,Brain(memory))
            buddy.open_settings()
            dlg = buddy.settings_dialog
            self.assertEqual(dlg.voice_choice.count(),10)
            self.assertEqual(dlg.face_controls['pupils'].count(),5)
            dlg.voice_choice.setCurrentIndex(dlg.voice_choice.findData('sage'))
            dlg.save_voice_settings()
            self.assertEqual(buddy._settings.value('voice/name'),'sage')
            dlg.test_expression('thinking')
            self.assertEqual(dlg.face_preview.mood,'thinking')
            dlg.close()
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

    def test_mind_journals_persist_and_are_read_only(self):
        from buddy.desktop import CharacterSheetDialog, IdeaJournalDialog
        with tempfile.TemporaryDirectory() as folder:
            memory=Memory(Path(folder))
            memory.add('user','Hello. I wonder how people learn good manners.')
            memory.add('assistant','I think learning manners might take practice.')
            self.assertTrue(memory.reflection_due())
            self.assertTrue(memory.add_reflection('I want to understand social expectations.',
                                                   'people learn good manners'))
            self.assertTrue(memory.add_idea('How manners work',
                'Why do expectations about manners vary between people?','curiosity','reflection'))
            self.assertTrue(memory.consider_belief('manners',
                'I think kindness matters when expressing disagreement.',
                'We discussed social expectations in conversation.',1))
            self.assertFalse(memory.character_sheet()['traits']['Independence'])
            self.assertEqual(len(memory.ideas()),1)
            buddy=DesktopBuddy(BuddyCore(Path(folder)),memory,Brain(memory))
            dlg=CharacterSheetDialog(buddy)
            self.assertIn('How manners',str(memory.ideas()[0]['title']))
            dlg.close()
            buddy.wake_listener.stop()
            buddy.close()
            memory.mark_reflection_attempt()
            self.assertFalse(memory.reflection_due())
            memory.db.close()
            reloaded=Memory(Path(folder))
            self.assertEqual(len(reloaded.beliefs()),1)
            self.assertEqual(len(reloaded.reflections()),1)
            self.assertEqual(reloaded.reflection_calls_today(reloaded.reflections()[0]['created'][:10]),1)
            reloaded.db.close()

    def test_turn_intent_distinguishes_goodbye_correction_and_self_question(self):
        from buddy.brain import conversation_intent, response_guidance, response_problem
        self.assertEqual(conversation_intent("How are you today?"),'wellbeing')
        self.assertEqual(conversation_intent("I want to know what's on your mind."),'self_question')
        self.assertEqual(conversation_intent("Stop asking me what's on my mind."),'correction')
        self.assertEqual(conversation_intent("That's enough for now we can end conversation."),'goodbye')
        self.assertIn('Answer how YOU are',response_guidance('How are you?',0,[]))
        self.assertTrue(response_problem('How are you?',
            "Ready for whatever's on your mind. How about you?",[]))
        self.assertTrue(response_problem("What's on your mind?",
            "Lately I've been thinking about who I am.",[]))

    def test_personality_repair_blocks_fake_reflection_and_unwanted_question(self):
        import json
        with tempfile.TemporaryDirectory() as folder:
            memory=Memory(Path(folder))
            brain=Brain(memory,key='fake-test-api-key')
            def response(text):
                return io.BytesIO(json.dumps({'choices':[{'message':{'content':text}}]}).encode())
            for input_text,first,repaired in [
                ('How are you today?',"Ready to help! How about you?",
                 "I feel curious. I haven't formed much of an opinion about myself yet."),
                ("I want to know what's on your mind.",
                 "Lately I've been thinking about my personality. What's on your mind?",
                 "I'm wondering how to tell when a question is too personal."),
                ("Stop asking me what's on my mind.",
                 "Sure! What's on your mind?",'Fair. I was doing that a lot.'),
                ("That's enough for now we can end conversation.",
                 "Sure, but what would you like to talk about next?",'Alright. Talk later.')
            ]:
                with patch('buddy.brain.urllib.request.urlopen',
                           side_effect=[response(first),response(repaired)]) as api:
                    self.assertEqual(brain.reply(input_text),repaired)
                    self.assertEqual(api.call_count,2)
            self.assertEqual(memory.count(),8)
            self.assertEqual(memory.reflections(),[])
            memory.db.close()

    def test_grounded_answer_skips_extra_repair_call(self):
        import json
        with tempfile.TemporaryDirectory() as folder:
            memory=Memory(Path(folder))
            brain=Brain(memory,key='fake-test-api-key')
            reply="I'm curious about why people value politeness so much."
            raw=io.BytesIO(json.dumps({'choices':[{'message':{'content':reply}}]}).encode())
            with patch('buddy.brain.urllib.request.urlopen',return_value=raw) as api:
                self.assertEqual(brain.reply("What's on your mind?"),reply)
                api.assert_called_once()
            memory.db.close()

    def test_conversation_learning_saves_grounded_view_and_question(self):
        import json
        with tempfile.TemporaryDirectory() as folder:
            memory=Memory(Path(folder))
            memory.add('user','I think our interests develop with time and experience.')
            memory.add('assistant','I think curiosity matters because it makes me want to explore things.')
            brain=Brain(memory,key='test-key')
            exchange=memory.next_unprocessed_exchange()
            self.assertIsNotNone(exchange)
            report={'meaningful':True,
                    'summary':'Buddy and the user discussed developing interests.',
                    'evidence':'our interests develop with time',
                    'belief':{'topic':'curiosity','stance':'I think curiosity is useful for discovery.',
                              'reason':'It motivates me to explore things.',
                              'quote':'I think curiosity matters','confidence':1},
                    'idea':{'title':'Recognizing interests',
                             'detail':'How will I recognize a new lasting personal interest?',
                             'kind':'curiosity'}}
            fake=io.BytesIO(json.dumps({'choices':[{'message':{'content':json.dumps(report)}}]}).encode())
            with patch('buddy.brain.urllib.request.urlopen',return_value=fake) as mock_api:
                self.assertEqual(brain.process_exchange(),'learned')
                mock_api.assert_called_once()
            self.assertEqual(len(memory.beliefs()),1)
            self.assertEqual(len(memory.ideas()),1)
            self.assertEqual(memory.learning_timeline()[0]['status'],'learned')
            self.assertEqual(memory.character_sheet()['learning'][0]['evidence'],'our interests develop with time')
            self.assertIsNone(memory.next_unprocessed_exchange())
            memory.db.close()
            loaded=Memory(Path(folder))
            self.assertEqual(loaded.learning_timeline()[0]['status'],'learned')
            self.assertEqual(len(loaded.beliefs()),1)
            loaded.db.close()

    def test_learning_no_change_and_fake_evidence_not_promoted(self):
        import json
        for report in (
            {'meaningful':False,'summary':'','evidence':'','belief':None,'idea':None},
            {'meaningful':True,'summary':'Buddy remembered flying','evidence':'I flew across the ocean',
             'belief':None,'idea':None}
        ):
            with tempfile.TemporaryDirectory() as folder:
                memory=Memory(Path(folder))
                memory.add('user','Hello there!')
                memory.add('assistant','Hello.')
                brain=Brain(memory,key='test-key')
                fake=io.BytesIO(json.dumps({'choices':[{'message':{'content':json.dumps(report)}}]}).encode())
                with patch('buddy.brain.urllib.request.urlopen',return_value=fake):
                    self.assertEqual(brain.process_exchange(),'no_change')
                self.assertEqual(memory.beliefs(),[])
                self.assertEqual(memory.ideas(),[])
                self.assertEqual(memory.learning_timeline()[0]['status'],'no_change')
                memory.db.close()

    def test_learning_does_not_promote_user_opinion_without_buddy_evidence(self):
        import json
        with tempfile.TemporaryDirectory() as folder:
            memory=Memory(Path(folder))
            memory.add('user','I believe all conversation is nurture for you.')
            memory.add('assistant','I wonder how that will shape my own interests.')
            brain=Brain(memory,key='test-key')
            report={'meaningful':True,'summary':'The pair discussed learning and nurture.',
                    'evidence':'conversation is nurture for you',
                    'belief':{'topic':'nurture','stance':'I believe conversations are all my nurture.',
                              'reason':'The user told me this.',
                              'quote':'I believe all conversation is nurture for you','confidence':5},
                    'idea':None}
            fake=io.BytesIO(json.dumps({'choices':[{'message':{'content':json.dumps(report)}}]}).encode())
            with patch('buddy.brain.urllib.request.urlopen',return_value=fake):
                self.assertEqual(brain.process_exchange(),'learned')
            self.assertEqual(memory.beliefs(),[])
            memory.db.close()

    def test_reflection_rejects_unverifiable_evidence(self):
        import json
        with tempfile.TemporaryDirectory() as folder:
            memory=Memory(Path(folder))
            memory.add('user','Why is kindness important?')
            memory.add('assistant','I wonder whether kindness means telling the truth gently.')
            brain=Brain(memory,key='not-sent-to-network')
            fake_report={'reflection':'I traveled to the sea yesterday.',
                         'evidence':'I swam in the sea yesterday.',
                         'ideas':[{'title':'Ocean swimming','detail':'I remember swimming','kind':'curiosity'}],
                         'belief':None}
            response=json.dumps({'choices':[{'message':{'content':json.dumps(fake_report)}}]}).encode()
            with patch('buddy.brain.urllib.request.urlopen',return_value=io.BytesIO(response)):
                self.assertFalse(brain.reflect())
            self.assertEqual(memory.reflections(),[])
            self.assertEqual(memory.ideas(),[])
            memory.db.close()

    def test_update_approval_defers_download_until_dialog_closes(self):
        with tempfile.TemporaryDirectory() as folder:
            memory=Memory(Path(folder))
            buddy=DesktopBuddy(BuddyCore(Path(folder)),memory,Brain(memory))
            release={'newer':True,'version':'0.99.0','notes':'A test release'}
            with patch('buddy.desktop.QMessageBox.question',return_value=QMessageBox.Yes), \
                 patch.object(buddy,'_run_update_task') as run_task:
                buddy._update_finished(release)
                run_task.assert_not_called()
                buddy._show_update_offer(release)
                self.app.processEvents()
                run_task.assert_called_once_with('download',release)
            buddy.wake_listener.stop()
            buddy.close()

    def test_microphone_settings_and_reflection_budget(self):
        with tempfile.TemporaryDirectory() as folder:
            memory=Memory(Path(folder))
            buddy=DesktopBuddy(BuddyCore(Path(folder)),memory,Brain(memory))
            buddy.open_settings()
            dlg=buddy.settings_dialog
            self.assertEqual(dlg.pause_choice.count(),4)
            self.assertEqual(dlg.sensitivity_choice.count(),3)
            dlg.pause_choice.setCurrentIndex(dlg.pause_choice.findData(4.0))
            dlg.save_microphone_settings()
            self.assertEqual(float(buddy._settings.value('mic/pause')),4.0)
            dlg.daily_reflections.setCurrentIndex(dlg.daily_reflections.findData(2))
            dlg.save_mind_settings()
            self.assertEqual(int(buddy._settings.value('mind/daily_limit')),2)
            dlg.close()
            buddy.wake_listener.stop()
            buddy.close()

    def test_updater_installs_new_dependencies_before_completion(self):
        from update_helper import install_dependencies
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            (root/'requirements.txt').write_text('opencv-python-headless>=4.9,<5\\n')
            with patch('update_helper.subprocess.run') as run:
                run.return_value.returncode=0
                run.return_value.stdout='Requirement already satisfied'
                self.assertIn('satisfied',install_dependencies(root,python='python'))
                command=run.call_args.args[0]
                self.assertEqual(command[:4],['python','-m','pip','install'])
                self.assertEqual(command[-2:],['-r',str(root/'requirements.txt')])
            with patch('update_helper.subprocess.run') as run:
                run.return_value.returncode=1
                run.return_value.stderr='Network unavailable'
                with self.assertRaisesRegex(RuntimeError,'Network unavailable'):
                    install_dependencies(root,python='python')

    def test_named_camera_picker_and_live_preview_failure_message(self):
        from buddy.desktop import CameraTestDialog
        with tempfile.TemporaryDirectory() as folder:
            memory=Memory(Path(folder))
            buddy=DesktopBuddy(BuddyCore(Path(folder)),memory,Brain(memory))
            with patch('buddy.desktop.camera_devices',return_value=[
                (0,'Integrated Webcam'),(1,'USB Streaming Camera')]):
                buddy.open_settings()
                settings=buddy.settings_dialog
                settings.refresh_cameras()
                self.assertIn('USB Streaming Camera',settings.camera_index.itemText(1))
                settings.camera_index.setCurrentIndex(1)
                with patch.object(CameraTestDialog,'start') as start:
                    settings.test_camera()
                    start.assert_called_once()
                    self.assertEqual(settings._camera_preview.index,1)
                    self.assertIn('USB Streaming Camera',settings._camera_preview.windowTitle())
                settings._camera_preview.close()
            settings.close()
            buddy.wake_listener.stop()
            buddy.close()

    def test_camera_name_discovery_fallback_and_preview_failure(self):
        from buddy.desktop import CameraTestDialog
        with tempfile.TemporaryDirectory() as folder:
            memory=Memory(Path(folder))
            buddy=DesktopBuddy(BuddyCore(Path(folder)),memory,Brain(memory))
            with patch('buddy.desktop.camera_devices',return_value=[]):
                buddy.open_settings()
                dlg=buddy.settings_dialog
                dlg.refresh_cameras()
                self.assertIn('name unavailable',dlg.camera_index.itemText(0))
                dlg._camera_preview=CameraTestDialog(buddy,0,'Camera 0')
                with patch.object(dlg._camera_preview.camera,'open',
                                  side_effect=RuntimeError('Device busy')):
                    dlg._camera_preview.start()
                    self.assertIn('Device busy',dlg._camera_preview.status.text())
                    self.assertFalse(buddy.face.camera_active)
                dlg._camera_preview.close()
                dlg.close()
            buddy.wake_listener.stop()
            buddy.close()

    def test_camera_permissions_and_no_remote_access(self):
        from buddy.vision import VisionPolicy, relevant_to_camera
        from buddy.desktop import ReplyTask
        default=VisionPolicy()
        self.assertFalse(default.may_track(True))
        self.assertFalse(default.may_capture(True,True))
        local=VisionPolicy(True,'always',False,0)
        self.assertTrue(local.may_track(False))
        self.assertFalse(local.may_capture(True,True))
        allowed=VisionPolicy(True,'conversation',True,0)
        self.assertFalse(allowed.may_track(False))
        self.assertTrue(allowed.may_track(True))
        self.assertFalse(allowed.may_capture(False,True))
        self.assertFalse(allowed.may_capture(True,False))
        self.assertTrue(allowed.may_capture(True,True))
        self.assertTrue(relevant_to_camera('How many fingers am I holding up?'))
        self.assertTrue(relevant_to_camera('Buddy, what do you think of my haircut?'))
        self.assertFalse(relevant_to_camera("I'm having a bad day."))
        self.assertFalse(relevant_to_camera("What is the meaning of friendship?"))

    def test_camera_is_disabled_by_default_and_hardware_kill_switch(self):
        with tempfile.TemporaryDirectory() as folder:
            memory=Memory(Path(folder))
            buddy=DesktopBuddy(BuddyCore(Path(folder)),memory,Brain(memory))
            self.assertFalse(buddy.vision_policy().enabled)
            with patch.object(buddy.camera,'open') as open_device:
                self.assertIsNone(buddy.capture_for_turn('How many fingers?'))
                buddy.sync_camera()
                open_device.assert_not_called()
            buddy.open_settings()
            settings=buddy.settings_dialog
            self.assertFalse(settings.camera_enabled.isChecked())
            self.assertFalse(settings.camera_cloud.isChecked())
            settings.camera_enabled.setChecked(True)
            settings.camera_cloud.setChecked(True)
            settings.camera_tracking.setCurrentIndex(settings.camera_tracking.findData('off'))
            settings.save_camera_settings()
            self.assertTrue(buddy.vision_policy().cloud)
            buddy.disable_camera()
            self.assertFalse(buddy.vision_policy().enabled)
            self.assertFalse(buddy.face.camera_active)
            self.assertFalse(settings.camera_enabled.isChecked())
            settings.close()
            buddy.wake_listener.stop()
            buddy.close()

    def test_camera_pupil_indicator_and_no_pupil_mode(self):
        face=Face()
        face.customize(pupils='none')
        face.camera_active=True
        face.camera_analyzing=True
        face.tracked_face=(.3,-.2)
        face.animate()
        face.show()
        self.app.processEvents()
        self.assertFalse(face.grab().isNull())
        self.assertNotEqual(face.gaze_x,0)
        face.close()

    def test_ends_speech_without_click(self):
        d = SilenceDetector()
        base = d.began
        import array
        speech = array.array('h', [6000] * 5000).tobytes()
        self.assertEqual(d.inspect(speech, base + 0.3), 'keep')
        self.assertEqual(d.inspect(speech, base + 0.5), 'keep')
        self.assertEqual(d.inspect(b'', base + 2.2), 'keep')
        self.assertEqual(d.inspect(b'', base + 3.1), 'send')

if __name__ == '__main__':
    unittest.main()
