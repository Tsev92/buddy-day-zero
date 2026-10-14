"""Standalone desktop shell around the original Buddy face and Day Zero brain."""
from PySide6.QtCore import QObject, Qt, QThread, Signal, QEvent, QSettings, QTimer
from PySide6.QtGui import QFont, QAction, QKeySequence, QShortcut
from PySide6.QtMultimedia import QMediaDevices
from PySide6.QtWidgets import (QApplication, QDialog, QHBoxLayout, QLabel,
    QLineEdit, QMainWindow, QPushButton, QScrollArea, QSizePolicy, QMenu,
    QTextBrowser, QVBoxLayout, QWidget, QMessageBox, QCheckBox, QComboBox, QProgressBar, QTabWidget)
from .face import Face
from .version import VERSION
from .audio import Microphone, Speaker, transcribe_wav, synthesize_wav, normalize_pcm_wav
from .updates import check_release, download_verified, UpdateError
from .bubbles import BubbleController
from .listening import SilenceDetector
from .wake import WakeListener, prepare_model
from .speech_visuals import voice_envelope

STYLE = """QWidget { background: #101925; color: #e6f3ff; font-family: 'Segoe UI', sans-serif; }
QPushButton { background: #253b51; border: 1px solid #436079; border-radius: 8px; padding: 7px 11px; }
QPushButton:hover { background: #355571; }
QPushButton:disabled { color: #7c8e9c; }
QLineEdit { background: #1b2a3a; border: 1px solid #4c657a; border-radius: 7px; padding: 9px; }
QTextBrowser { background: #142132; border: 1px solid #33495f; border-radius: 10px; padding: 10px; }
"""

class ReplyTask(QObject):
    finished = Signal(str)
    failed = Signal(str)
    def __init__(self, brain, text):
        super().__init__()
        self.brain, self.text = brain, text
    def run(self):
        try: self.finished.emit(self.brain.reply(self.text))
        except Exception as exc: self.failed.emit(str(exc))

class UpdateTask(QObject):
    progress = Signal(int)
    finished = Signal(object)
    failed = Signal(str)
    def __init__(self, action, release=None, folder=None):
        super().__init__(); self.action=action; self.release=release; self.folder=folder
    def run(self):
        try:
            if self.action == 'check': self.finished.emit(check_release())
            else: self.finished.emit(download_verified(self.release,self.folder,self.progress.emit))
        except Exception as exc: self.failed.emit(str(exc))

class LearningTask(QObject):
    finished = Signal(str)
    def __init__(self, brain):
        super().__init__()
        self.brain=brain
    def run(self):
        try:
            self.finished.emit(self.brain.process_exchange() or 'no_change')
        except Exception:
            self.finished.emit('error')


class ReflectTask(QObject):
    finished = Signal(bool)
    failed = Signal(str)
    def __init__(self, brain, memory):
        super().__init__()
        self.brain, self.memory = brain, memory
    def run(self):
        try:
            self.memory.mark_reflection_attempt()
            self.finished.emit(self.brain.reflect())
        except Exception as exc:
            self.failed.emit(str(exc))


class VoiceTask(QObject):
    finished = Signal(object)
    failed = Signal(str)
    def __init__(self, action, value, voice='alloy', model='tts-1', speed=1.0):
        super().__init__()
        self.action, self.value = action, value
        self.voice, self.model, self.speed = voice, model, speed
    def run(self):
        try:
            result = transcribe_wav(self.value) if self.action == 'transcribe' else synthesize_wav(self.value, self.voice, self.model, self.speed)
            self.finished.emit(result)
        except Exception as exc:
            self.failed.emit(str(exc))

class WakeSetupTask(QObject):
    finished = Signal(str)
    failed = Signal(str)
    def __init__(self, data_dir):
        super().__init__()
        self.data_dir = data_dir
    def run(self):
        try:
            try:
                import vosk
            except ImportError:
                import subprocess, sys
                subprocess.run([sys.executable,'-m','pip','install','vosk>=0.3.45,<0.4'],
                               check=True, timeout=240)
            self.finished.emit(prepare_model(self.data_dir))
        except Exception as exc:
            self.failed.emit(str(exc))

class ChatDialog(QDialog):
    def __init__(self, buddy):
        super().__init__(buddy)
        self.buddy = buddy
        self.setWindowTitle('Talk to Buddy')
        self.resize(460, 480)
        self.setStyleSheet(STYLE)
        layout = QVBoxLayout(self)
        self.log = QTextBrowser()
        self.log.setOpenExternalLinks(False)
        layout.addWidget(self.log)
        row = QHBoxLayout()
        self.input = QLineEdit()
        self.input.setPlaceholderText('Say something to Buddy…')
        self.input.returnPressed.connect(self.send)
        self.send_button = QPushButton('Send')
        self.send_button.clicked.connect(self.send)
        row.addWidget(self.input, 1); row.addWidget(self.send_button)
        self.mic_button = QPushButton('🎙 Record')
        self.mic_button.clicked.connect(self.toggle_microphone)
        row.addWidget(self.mic_button)
        self.finish_button = QPushButton('✓ Finish')
        self.finish_button.setEnabled(False)
        self.finish_button.clicked.connect(self.finish_microphone)
        row.addWidget(self.finish_button)
        layout.addLayout(row)
        self.conversation_button = QPushButton('Start Conversation Mode')
        self.conversation_button.clicked.connect(self.toggle_conversation_mode)
        layout.addWidget(self.conversation_button)
        self.status = QLabel('')
        layout.addWidget(self.status)
        layout.addWidget(QLabel('Microphone input level'))
        self.input_meter = QProgressBar()
        self.input_meter.setRange(0,100)
        self.input_meter.setValue(0)
        self.input_meter.setFormat('%v%')
        layout.addWidget(self.input_meter)
        for message in buddy.memory.recent(80):
            self.append(message['role'], message['content'])
        if not buddy.memory.count():
            self.append('assistant', '…Hello?')
        self.worker_thread = None
        self.voice_thread = None
        self.voice_worker = None
        self.mic = Microphone(self)
        self.mic_recording = False
        self._mic_offset = 0
        self._detector = None
        self.conversation_mode = False
        self.monitor = QTimer(self)
        self.monitor.setInterval(120)
        self.monitor.timeout.connect(self._poll_recording)
        self.speaker = Speaker(self)
        self.speaker.speakingChanged.connect(self.speaking_changed)
        self.speaker.error.connect(self.voice_failed)
        self._heard_speaker = False
        self._reply_for_bubble = ''
        self._speech_levels = []
        self._speech_timer = QTimer(self)
        self._speech_timer.setInterval(40)
        self._speech_timer.timeout.connect(self._sync_speech_visuals)

    def append(self, role, message):
        from html import escape
        name = self.buddy.core.snapshot()['name'] if role == 'assistant' else 'You'
        self.log.append(f'<p style="margin:7px 0"><b>{escape(name)}:</b> {escape(message).replace(chr(10), "<br>")}</p>')
        self.log.verticalScrollBar().setValue(self.log.verticalScrollBar().maximum())

    def toggle_microphone(self):
        if self.mic_recording:
            self.mic_recording = False
            self.monitor.stop()
            self.mic_button.setText('🎙 Record')
            self.finish_button.setEnabled(False)
            self.input_meter.setValue(0)
            self.mic.cancel()
            self.buddy.face.mood = 'idle'
            self.buddy.face.mic_level = 0
            self.status.setText('Recording cancelled.')
            return
        if self.worker_thread is not None or self.voice_thread is not None:
            return
        try:
            self.buddy.pause_wake()
            self.mic.start(self.buddy._settings.value('mic/id',''))
            self.mic_recording = True
            self._mic_offset = 0
            self._detector = SilenceDetector(
                silence_seconds=float(self.buddy._settings.value('mic/pause',2.5)),
                threshold=float(self.buddy._settings.value('mic/threshold',0.012)))
            self.monitor.start()
            self.finish_button.setEnabled(True)
            self.mic_button.setText('■ Cancel')
            self.buddy.face.mood = 'listening'
            self.status.setText('Listening… pause when you finish speaking.')
        except Exception as exc:
            self.voice_failed(str(exc))

    def finish_microphone(self):
        if not self.mic_recording: return
        self.mic_recording = False
        self.monitor.stop()
        self.mic_button.setText('🎙 Record')
        self.finish_button.setEnabled(False)
        self.input_meter.setValue(0)
        try:
            audio = self.mic.stop()
            self.buddy.face.mood='thinking'
            self.buddy.face.mic_level=0
            self.status.setText('Processing your speech…')
            self._voice_task('transcribe',audio)
        except Exception as exc:
            self.voice_failed(str(exc))

    def _poll_recording(self):
        if not self.mic_recording or self._detector is None:
            return
        chunk, self._mic_offset = self.mic.read_since(self._mic_offset)
        decision = self._detector.inspect(chunk)
        if chunk:
            import audioop
            try:
                self.buddy.face.mic_level = min(1.0, audioop.rms(chunk, 2)/11000)
            except (ValueError, audioop.error):
                self.buddy.face.mic_level = 0.0
            self.input_meter.setValue(int(100*self.buddy.face.mic_level))
        if decision == 'send':
            self.status.setText('Pause detected; processing speech…')
            self.finish_microphone()
        elif decision == 'timeout':
            self.monitor.stop()
            self.mic.cancel()
            self.mic_recording = False
            self.finish_button.setEnabled(False)
            self.input_meter.setValue(0)
            self.mic_button.setText('Record')
            self.buddy.face.mood = 'idle'
            self.status.setText('No speech detected.')
            if self.conversation_mode:
                self.toggle_conversation_mode()

    def toggle_conversation_mode(self):
        if self.conversation_mode:
            self.conversation_mode = False
            self.conversation_button.setText('Start Conversation Mode')
            self.status.setText('Conversation ended.')
            QTimer.singleShot(1200, self.buddy._maybe_start_wake)
            if self.mic_recording:
                self.monitor.stop()
                self.mic.cancel()
                self.mic_recording = False
                self.finish_button.setEnabled(False)
                self.input_meter.setValue(0)
                self.mic_button.setText('Record')
                self.buddy.face.mood = 'idle'
            return
        self.conversation_mode = True
        self.conversation_button.setText('End Conversation Mode')
        if not self.mic_recording and self.worker_thread is None and self.voice_thread is None:
            self.toggle_microphone()

    def _resume_conversation(self):
        if self.conversation_mode and not self.mic_recording:
            if self.worker_thread is None and self.voice_thread is None:
                self.toggle_microphone()

    def _voice_task(self, action, value):
        if self.voice_thread is not None: return
        self.voice_action = action
        self.voice_thread = QThread(self)
        self.voice_worker = VoiceTask(action, value,
            self.buddy._settings.value('voice/name','alloy'),
            self.buddy._settings.value('voice/model','tts-1'),
            float(self.buddy._settings.value('voice/speed',1.0)))
        self.voice_worker.moveToThread(self.voice_thread)
        self.voice_thread.started.connect(self.voice_worker.run)
        self.voice_worker.finished.connect(self.voice_succeeded)
        self.voice_worker.failed.connect(self.voice_failed)
        self.voice_worker.finished.connect(self.voice_thread.quit)
        self.voice_worker.failed.connect(self.voice_thread.quit)
        self.voice_thread.finished.connect(self.voice_cleanup)
        self.voice_thread.start()

    def voice_succeeded(self, value):
        if self.voice_action == 'transcribe':
            normalized = ' '.join(value.lower().strip().split())
            if self.conversation_mode and any(bye in normalized for bye in
                 ('goodbye buddy', 'bye buddy', 'stop listening', 'end conversation')):
                self.append('user', value)
                self.toggle_conversation_mode()
                self._send_transcription = False
            else:
                self.input.setText(value)
                self.status.setText('')
                self._send_transcription = True
        else:
            try:
                # Streamed WAV headers can claim hours of nonexistent samples.
                # Feed BOTH the player and caption clock the same repaired audio.
                repaired_audio, duration = normalize_pcm_wav(value)
                self._speech_levels = voice_envelope(repaired_audio)
                self.buddy.bubbles.begin(self._reply_for_bubble, duration)
                self.speaker.play_wav(repaired_audio)
                self.status.setText('')
            except Exception as exc:
                self.voice_failed(str(exc))

    def voice_failed(self, error):
        self.status.setText('Voice: ' + error)
        if self.buddy.face.mood in ('listening', 'thinking', 'speaking'):
            self.buddy.face.mood = 'idle'

    def voice_cleanup(self):
        self.voice_worker.deleteLater()
        self.voice_thread.deleteLater()
        self.voice_worker = self.voice_thread = None
        if getattr(self, '_send_transcription', False):
            self._send_transcription = False
            self.send()

    def _sync_speech_visuals(self):
        position = max(0, self.speaker.player.position())
        index = min(len(self._speech_levels)-1, position//40)
        if self._speech_levels and index >= 0:
            target = self._speech_levels[index]
            self.buddy.face.audio_level += (target-self.buddy.face.audio_level)*.65
        self.buddy.bubbles.sync_position(position)

    def speaking_changed(self, active):
        self.buddy.face.mood = 'speaking' if active else 'idle'
        if active:
            self._heard_speaker = True
            self._speech_timer.start()
        elif self._heard_speaker:
            self._speech_timer.stop()
            self.buddy.face.audio_level = 0.0
            self._heard_speaker = False
            self.buddy.bubbles.speaking_finished()
            QTimer.singleShot(850, self._resume_conversation)
            if not self.conversation_mode:
                QTimer.singleShot(900, self.buddy._maybe_start_wake)

    def send(self):
        message = self.input.text().strip()
        if not message or self.worker_thread is not None or self.mic_recording: return
        if len(message) > 4000:
            self.status.setText('Message too long (4000 characters maximum).'); return
        self.input.clear()
        self.append('user', message)
        self.input.setEnabled(False); self.send_button.setEnabled(False)
        self.status.setText('Buddy is thinking…')
        self.buddy.pause_wake()
        self.buddy.face.mood = 'thinking'
        self.worker_thread = QThread(self)
        self.worker = ReplyTask(self.buddy.brain, message)
        self.worker.moveToThread(self.worker_thread)
        self.worker_thread.started.connect(self.worker.run)
        self.worker.finished.connect(self.succeeded)
        self.worker.failed.connect(self.failed)
        self.worker.finished.connect(self.worker_thread.quit)
        self.worker.failed.connect(self.worker_thread.quit)
        self.worker_thread.finished.connect(self.cleanup)
        self.worker_thread.start()

    def succeeded(self, answer):
        self.append('assistant', answer)
        # Learning happens after the actual reply, never delaying the human.
        QTimer.singleShot(4000, self.buddy._maybe_learn)
        self.status.setText('')
        self.buddy.face.express('curious', 2.0)
        self._reply_for_bubble = answer
        if self.voice_thread is None:
            self.status.setText('Preparing speech…')
            self._voice_task('speak', answer)

    def failed(self, error):
        self.status.setText(error)
        self.append('assistant', f'[Message could not be sent: {error}]')

    def cleanup(self):
        self.worker.deleteLater()
        self.worker_thread.deleteLater()
        self.worker_thread = None
        self.input.setEnabled(True); self.send_button.setEnabled(True)
        if self.buddy.face.mood != 'speaking':
            self.buddy.face.mood = 'idle'
        self.input.setFocus()

    def closeEvent(self, event):
        if self.worker_thread is not None or self.voice_thread is not None:
            self.hide(); event.ignore(); return
        if self.mic_recording:
            self.mic.cancel()
            self.mic_recording = False
        self.monitor.stop()
        self._speech_timer.stop()
        self.conversation_mode = False
        self.buddy.bubbles.stop()
        self.speaker.stop()
        QTimer.singleShot(1000, self.buddy._maybe_start_wake)
        super().closeEvent(event)


class CharacterSheetDialog(QDialog):
    """Display observed character development; no stat or belief editing controls."""
    def __init__(self, buddy):
        super().__init__(buddy)
        self.buddy = buddy
        self.setWindowTitle('Buddy · Character Sheet')
        self.resize(615,520)
        self.setStyleSheet(STYLE)
        layout=QVBoxLayout(self)
        tabs=QTabWidget()
        self.pages={}
        for label in ('Personality','Emotions','Beliefs','Reflections','History','Learning'):
            page=QTextBrowser()
            page.setReadOnly(True)
            tabs.addTab(page,label)
            self.pages[label]=page
        layout.addWidget(tabs)
        row=QHBoxLayout()
        refresh=QPushButton('Refresh')
        refresh.clicked.connect(self.refresh)
        row.addWidget(refresh)
        close=QPushButton('Close')
        close.clicked.connect(self.close)
        row.addWidget(close)
        layout.addLayout(row)
        self.refresh()

    def refresh(self):
        from html import escape
        safe=lambda value: escape(str(value))
        sheet=self.buddy.memory.character_sheet()
        traits=sheet['traits']
        rows=[]
        for name,value in traits.items():
            if value is None:
                rows.append('<p><b>%s:</b> Not enough evidence yet</p>' % safe(name))
            else:
                rows.append('<p><b>%s:</b> %d/100</p>' % (safe(name),value))
        rows.append('<p><i>Scores are observed expression frequencies across recorded replies (at least five required), not assigned personality traits. These cannot be edited.</i></p>')
        self.pages['Personality'].setHtml('<h3>Developing personality</h3>'+''.join(rows))
        self.pages['Emotions'].setHtml('<h3>Persistent emotional state</h3>'+''.join(
            '<p><b>%s:</b> %s/5 (%s recorded experiences)</p>' % (
                safe(name.title()),strength,sheet['evidence'].get(name,0))
            for name,strength in sheet['emotions'].items()))
        self.pages['Beliefs'].setHtml('<h3>Tentative beliefs</h3>'+(''.join(
            '<p><b>%s</b> · %s/5<br>%s<br><i>%s</i></p>' % (
                safe(x['topic']),x['confidence'],safe(x['stance']),safe(x['reason']))
            for x in sheet['beliefs']) or '<p>No beliefs recorded yet.</p>'))
        self.pages['Reflections'].setHtml('<h3>Recorded independent reflections</h3>'+(''.join(
            '<p><b>%s</b><br>%s<br><small>Grounded in: %s</small></p>' % (
                safe(x['created'][:16]),safe(x['content']),safe(x['evidence']))
            for x in sheet['reflections']) or '<p>Buddy has not recorded any reflections yet.</p>'))
        self.pages['History'].setHtml('<h3>Changing his mind</h3>'+(''.join(
            '<p><b>%s</b> · %s<br>%s → %s<br><small>%s</small></p>' % (
                safe(x['topic']),safe(x['created'][:16]),
                safe(x['previous'] or 'No earlier stance'),
                safe(x['current']),safe(x['reason']))
            for x in sheet['history']) or '<p>No belief changes recorded yet.</p>'))
        self.pages['Learning'].setHtml('<h3>Conversation learning timeline</h3>'+
            '<p>Every evaluated exchange is labeled as learned, no meaningful change, or error. '
            'The quoted evidence comes from the actual dialogue.</p>'+(''.join(
            '<p><b>%s</b> · %s<br>%s<br><i>Evidence: %s</i><br><small>Changes: %s</small></p>' %
            (safe(x['status'].replace('_',' ').title()),safe(x['created'][:16]),
             safe(x['summary']),safe(x['evidence'] or '—'),safe(x['changes'] or '—'))
            for x in sheet['learning']) or '<p>No exchanges processed yet.</p>'))


class IdeaJournalDialog(QDialog):
    def __init__(self, buddy):
        super().__init__(buddy)
        self.buddy=buddy
        self.setWindowTitle('Buddy · Idea Journal')
        self.resize(580,465)
        self.setStyleSheet(STYLE)
        layout=QVBoxLayout(self)
        layout.addWidget(QLabel('Buddy’s questions, interests and projects from actual conversations and reflections.'))
        self.choices=QComboBox()
        self.choices.currentIndexChanged.connect(self.show_selected)
        layout.addWidget(self.choices)
        self.detail=QTextBrowser()
        self.detail.setReadOnly(True)
        layout.addWidget(self.detail)
        row=QHBoxLayout()
        discuss=QPushButton('Discuss with Buddy')
        discuss.clicked.connect(self.discuss)
        row.addWidget(discuss)
        for label,status in (('Explore','exploring'),('Develop','developing'),
                              ('Set aside','set_aside'),('Dismiss','dismissed')):
            button=QPushButton(label)
            button.clicked.connect(lambda _checked=False, s=status: self.change_status(s))
            row.addWidget(button)
        layout.addLayout(row)
        self.refresh()

    def refresh(self):
        previous=self.choices.currentData()
        self.choices.blockSignals(True)
        self.choices.clear()
        for idea in self.buddy.memory.ideas(limit=80):
            self.choices.addItem(idea['title']+' ['+idea['status']+']',idea['id'])
        index=self.choices.findData(previous)
        self.choices.setCurrentIndex(index if index>=0 else (0 if self.choices.count() else -1))
        self.choices.blockSignals(False)
        self.show_selected()

    def selected(self):
        current=self.choices.currentData()
        return next((i for i in self.buddy.memory.ideas(limit=80) if i['id']==current),None)

    def show_selected(self, *_):
        from html import escape
        idea=self.selected()
        if not idea:
            self.detail.setPlainText('No ideas recorded yet. They grow from actual conversations and saved reflections.')
        else:
            self.detail.setHtml('<h3>'+escape(idea['title'])+'</h3><p>'+
                escape(idea['detail'])+'</p><p><i>Type: '+
                escape(idea['kind'])+' · Source: '+escape(idea['source'])+
                ' · Status: '+escape(idea['status'])+'</i></p>')

    def change_status(self, status):
        idea=self.selected()
        if idea:
            self.buddy.memory.set_idea_status(idea['id'],status)
            self.refresh()

    def discuss(self):
        idea=self.selected()
        if not idea: return
        self.buddy.memory.set_idea_status(idea['id'],'discussed')
        self.buddy.open_chat()
        self.buddy.chat_dialog.input.setText(
            'I saw your saved idea about '+idea['title']+'. '+idea['detail'])
        self.close()


class SettingsDialog(QDialog):
    def __init__(self, buddy):
        super().__init__(buddy)
        self.buddy = buddy
        self.setWindowTitle('Buddy Day Zero Settings')
        self.setStyleSheet(STYLE)
        self.setMinimumWidth(370)
        self.resize(440,720)
        outer=QVBoxLayout(self)
        scroll=QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        controls=QWidget()
        layout=QVBoxLayout(controls)
        scroll.setWidget(controls)
        outer.addWidget(scroll)
        layout.addWidget(QLabel('Buddy name'))
        self.name = QLineEdit(buddy.core.snapshot()['name'])
        layout.addWidget(self.name)
        note = QLabel('Audio recording and spoken replies are available from Talk.\nBuddy keeps his Day Zero memory separate.')
        note.setWordWrap(True); layout.addWidget(note)
        save = QPushButton('Save name…')
        save.clicked.connect(self.save_name)
        layout.addWidget(save)
        self.wake_box = QCheckBox('Enable local "Hey Buddy" wake phrase')
        self.wake_box.setChecked(buddy._settings.value('wake_enabled', False, type=bool))
        self.wake_box.toggled.connect(self.toggle_wake)
        layout.addWidget(self.wake_box)
        self.wake_status = QLabel('Wake detection runs locally; first enable downloads an offline model.')
        self.wake_status.setWordWrap(True)
        layout.addWidget(self.wake_status)
        self._wake_setup_thread = None
        layout.addWidget(QLabel('Microphone & Listening'))
        self.mic_choice = QComboBox()
        self.refresh_microphones()
        layout.addWidget(self.mic_choice)
        mic_refresh=QPushButton('Refresh microphones')
        mic_refresh.clicked.connect(self.refresh_microphones)
        layout.addWidget(mic_refresh)
        layout.addWidget(QLabel('Pause before Buddy responds'))
        self.pause_choice=QComboBox()
        for name,secs in (('Short · 1.5 seconds',1.5),('Normal · 2.5 seconds',2.5),
                          ('Patient · 4 seconds',4.0),('Very patient · 6 seconds',6.0)):
            self.pause_choice.addItem(name,secs)
        self.pause_choice.setCurrentIndex(max(0,self.pause_choice.findData(
            float(buddy._settings.value('mic/pause',2.5)))))
        layout.addWidget(self.pause_choice)
        layout.addWidget(QLabel('Microphone sensitivity'))
        self.sensitivity_choice=QComboBox()
        for label,threshold in (('Low · Ignore background noise',.025),
                                ('Normal',.012),('High · Hear quiet speech',.006)):
            self.sensitivity_choice.addItem(label,threshold)
        self.sensitivity_choice.setCurrentIndex(max(0,self.sensitivity_choice.findData(
            float(buddy._settings.value('mic/threshold',.012)))))
        layout.addWidget(self.sensitivity_choice)
        save_mic=QPushButton('Save microphone settings')
        save_mic.clicked.connect(self.save_microphone_settings)
        layout.addWidget(save_mic)
        layout.addWidget(QLabel('Idle Reflection & Independent Thoughts'))
        self.reflect_enabled=QCheckBox('Allow occasional independent reflection (uses API tokens)')
        self.reflect_enabled.setChecked(buddy._settings.value('mind/reflect_enabled',True,type=bool))
        layout.addWidget(self.reflect_enabled)
        layout.addWidget(QLabel('Maximum reflection attempts per day'))
        self.daily_reflections=QComboBox()
        for n in (2,4,8):
            self.daily_reflections.addItem(str(n),n)
        self.daily_reflections.setCurrentIndex(max(0,self.daily_reflections.findData(
            int(buddy._settings.value('mind/daily_limit',4)))))
        layout.addWidget(self.daily_reflections)
        save_mind=QPushButton('Save reflection settings')
        save_mind.clicked.connect(self.save_mind_settings)
        layout.addWidget(save_mind)
        layout.addWidget(QLabel('Voice & Speech'))
        self.voice_choice = QComboBox()
        for v in ('alloy','ash','ballad','coral','echo','fable','nova','onyx','sage','shimmer'):
            self.voice_choice.addItem(v.title(),v)
        self.voice_choice.setCurrentIndex(max(0,self.voice_choice.findData(
            buddy._settings.value('voice/name','alloy'))))
        layout.addWidget(self.voice_choice)
        self.model_choice = QComboBox()
        for model in ('tts-1','tts-1-hd','gpt-4o-mini-tts'):
            self.model_choice.addItem(model,model)
        self.model_choice.setCurrentIndex(max(0,self.model_choice.findData(
            buddy._settings.value('voice/model','tts-1'))))
        layout.addWidget(self.model_choice)
        layout.addWidget(QLabel('Speaking speed'))
        self.speed_choice = QComboBox()
        for speed in (.75,1.0,1.15,1.3,1.5):
            self.speed_choice.addItem(str(speed)+'×',speed)
        self.speed_choice.setCurrentIndex(max(0,self.speed_choice.findData(
            float(buddy._settings.value('voice/speed',1.0)))))
        layout.addWidget(self.speed_choice)
        save_voice = QPushButton('Save Voice & Speech')
        save_voice.clicked.connect(self.save_voice_settings)
        layout.addWidget(save_voice)
        preview_voice = QPushButton('Preview selected voice')
        preview_voice.clicked.connect(self.preview_voice)
        layout.addWidget(preview_voice)
        self.preview_speaker = Speaker(self)
        self.preview_thread = None
        layout.addWidget(QLabel('Customize Buddy'))
        self.face_preview = Face()
        self.face_preview.setFixedSize(260, 147)
        layout.addWidget(self.face_preview)
        self.face_controls = {}
        options = (
            ('eyes','Eye shape', ('classic','round','sleepy','pixel')),
            ('pupils','Pupil shape', ('none','oval','round','slit','pixel')),
            ('mouth','Mouth', ('classic','smile','wry','cat','pixel','lips')),
            ('eyebrows','Eyebrows', ('single','both','none')),
            ('color','Face color', ('#a8ecff','#bda7ff','#9becba','#ffc58f','#ffc1de'))
        )
        current = {'eyes':buddy.face.eye_style,'pupils':buddy.face.pupil_style,'mouth':buddy.face.mouth_style,
                   'eyebrows':buddy.face.eyebrow_style,'color':buddy.face.eye_color}
        for key, title, choices in options:
            layout.addWidget(QLabel(title))
            combo = QComboBox()
            for choice in choices:
                label = {'#a8ecff':'Cyan','#bda7ff':'Lavender',
                         '#9becba':'Mint','#ffc58f':'Peach','#ffc1de':'Pink',
                         'single':'Signature single eyebrow'}.get(choice,choice.title())
                combo.addItem(label,choice)
            combo.setCurrentIndex(max(0, combo.findData(current[key])))
            combo.currentIndexChanged.connect(self.preview_customization)
            self.face_controls[key] = combo
            layout.addWidget(combo)
        self.preview_customization()
        test_row = QHBoxLayout()
        for mood in ('idle','thinking','speaking','listening'):
            button = QPushButton(mood.title())
            button.clicked.connect(lambda _checked=False, m=mood: self.test_expression(m))
            test_row.addWidget(button)
        layout.addLayout(test_row)
        apply_button = QPushButton('Apply Buddy appearance')
        apply_button.clicked.connect(self.apply_customization)
        layout.addWidget(apply_button)
        reset_button = QPushButton('Restore default appearance')
        reset_button.clicked.connect(self.reset_customization)
        layout.addWidget(reset_button)
        layout.addWidget(QLabel(f'Buddy Day Zero v{VERSION}'))
        update = QPushButton('Check for updates…')
        update.clicked.connect(self.buddy.check_updates)
        layout.addWidget(update)

    def refresh_microphones(self):
        previous=self.mic_choice.currentData() if hasattr(self,'mic_choice') else None
        saved=self.buddy._settings.value('mic/id','')
        self.mic_choice.clear()
        self.mic_choice.addItem('System default microphone','')
        devices=QMediaDevices.audioInputs()
        for device in devices:
            self.mic_choice.addItem(device.description(),bytes(device.id()).hex())
        selected=previous if previous is not None else saved
        index=self.mic_choice.findData(selected)
        self.mic_choice.setCurrentIndex(max(0,index))

    def save_microphone_settings(self):
        self.buddy._settings.setValue('mic/id',self.mic_choice.currentData())
        self.buddy._settings.setValue('mic/pause',self.pause_choice.currentData())
        self.buddy._settings.setValue('mic/threshold',self.sensitivity_choice.currentData())

    def save_mind_settings(self):
        self.buddy._settings.setValue('mind/reflect_enabled',self.reflect_enabled.isChecked())
        self.buddy._settings.setValue('mind/daily_limit',self.daily_reflections.currentData())

    def preview_customization(self, *_):
        options = {key: widget.currentData() for key,widget in self.face_controls.items()}
        self.face_preview.customize(**options)

    def apply_customization(self):
        options = {key: widget.currentData() for key,widget in self.face_controls.items()}
        self.buddy.face.customize(**options)
        for key,value in options.items():
            self.buddy._settings.setValue('appearance/'+key,value)

    def reset_customization(self):
        defaults = {'eyes':'classic','pupils':'oval','mouth':'classic',
                    'eyebrows':'single','color':'#a8ecff'}
        for key,widget in self.face_controls.items():
            widget.setCurrentIndex(widget.findData(defaults[key]))
        self.apply_customization()

    def save_voice_settings(self):
        settings = self.buddy._settings
        settings.setValue('voice/name',self.voice_choice.currentData())
        settings.setValue('voice/model',self.model_choice.currentData())
        settings.setValue('voice/speed',self.speed_choice.currentData())

    def preview_voice(self):
        if self.preview_thread is not None:
            return
        self.preview_thread = QThread(self)
        self.preview_worker = VoiceTask('speak',
            'Hello there. This is how my voice sounds.',
            self.voice_choice.currentData(),self.model_choice.currentData(),
            self.speed_choice.currentData())
        self.preview_worker.moveToThread(self.preview_thread)
        self.preview_thread.started.connect(self.preview_worker.run)
        self.preview_worker.finished.connect(self._play_preview)
        self.preview_worker.failed.connect(self._preview_error)
        self.preview_worker.finished.connect(self.preview_thread.quit)
        self.preview_worker.failed.connect(self.preview_thread.quit)
        self.preview_thread.finished.connect(self._preview_cleanup)
        self.preview_thread.start()

    def _play_preview(self, wav):
        self.preview_speaker.play_wav(normalize_pcm_wav(wav)[0])

    def _preview_error(self, message):
        QMessageBox.warning(self,'Voice preview failed',message)

    def _preview_cleanup(self):
        self.preview_worker.deleteLater()
        self.preview_thread.deleteLater()
        self.preview_worker = self.preview_thread = None

    def test_expression(self, mood):
        self.face_preview.mood = mood
        self.face_preview.express('skeptical' if mood == 'thinking' else 'neutral', 2)
        self.face_preview.audio_level = .75 if mood == 'speaking' else 0
        self.face_preview.update()

    def toggle_wake(self, enabled):
        if not enabled:
            self.buddy._settings.setValue('wake_enabled', False)
            self.buddy.wake_listener.stop()
            self.wake_status.setText('Wake phrase disabled.')
            return
        answer = QMessageBox.question(
            self, 'Enable local wake phrase?',
            'Buddy needs to download an offline English speech model (about 40 MB) and may install Vosk. '
            'Wake listening stays on this device; normal conversation audio is only sent when you speak. '
            'Continue?', QMessageBox.Yes | QMessageBox.No)
        if answer != QMessageBox.Yes:
            self.wake_box.blockSignals(True)
            self.wake_box.setChecked(False)
            self.wake_box.blockSignals(False)
            return
        self.wake_box.setEnabled(False)
        self.wake_status.setText('Preparing offline wake detection… this may take a few minutes.')
        self._wake_setup_thread = QThread(self)
        self._wake_setup_worker = WakeSetupTask(self.buddy.core.data_dir)
        self._wake_setup_worker.moveToThread(self._wake_setup_thread)
        self._wake_setup_thread.started.connect(self._wake_setup_worker.run)
        self._wake_setup_worker.finished.connect(self._wake_ready)
        self._wake_setup_worker.failed.connect(self._wake_failed)
        self._wake_setup_worker.finished.connect(self._wake_setup_thread.quit)
        self._wake_setup_worker.failed.connect(self._wake_setup_thread.quit)
        self._wake_setup_thread.finished.connect(self._wake_cleanup)
        self._wake_setup_thread.start()

    def _wake_ready(self, model_path):
        self.buddy._settings.setValue('wake_enabled', True)
        self.wake_status.setText('Ready! Say "Hey Buddy" when he is idle.')
        self.buddy._maybe_start_wake()

    def _wake_failed(self, error):
        self.wake_status.setText('Wake setup failed: ' + error)
        self.wake_box.blockSignals(True)
        self.wake_box.setChecked(False)
        self.wake_box.blockSignals(False)

    def _wake_cleanup(self):
        self._wake_setup_worker.deleteLater()
        self._wake_setup_thread.deleteLater()
        self._wake_setup_worker = self._wake_setup_thread = None
        self.wake_box.setEnabled(True)

    def save_name(self):
        try:
            new = self.name.text().strip()
            old = self.buddy.core.snapshot()['name']
            if new == old: return
            token = self.buddy.core.propose('name', new)
            answer = QMessageBox.question(self, 'Confirm change', f'Change Buddy’s name from {old} to {new}?')
            self.buddy.core.resolve(token, answer == QMessageBox.Yes)
            self.buddy.setWindowTitle(self.buddy.core.snapshot()['name'])
        except ValueError as exc:
            QMessageBox.warning(self, 'Invalid setting', str(exc))

class DesktopBuddy(QMainWindow):
    def __init__(self, core, memory, brain):
        super().__init__()
        self.core, self.memory, self.brain = core, memory, brain
        self.setWindowTitle('Buddy Day Zero')
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        # The border is drawn by Face; the window has no OS frame or control bar.
        self.setStyleSheet(STYLE + """
            QWidget#buddyRoot, QWidget#buddyFace {
                background: transparent; border: none;
            }
        """)
        self.setMinimumSize(240, 135)
        self.resize(360, 203)
        self.face = Face()
        self.face.setObjectName('buddyFace')
        self.face.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.face.installEventFilter(self)
        root = QWidget()
        root.setObjectName('buddyRoot')
        layout = QVBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.face, 1)
        self.setCentralWidget(root)
        self._drag_origin = None
        self._drag_window_origin = None
        self._did_drag = False
        self._settings = QSettings('BuddyDayZero', 'Desktop')
        self.face.customize(
            eyes=self._settings.value('appearance/eyes','classic'),
            pupils=self._settings.value('appearance/pupils','oval'),
            mouth=self._settings.value('appearance/mouth','classic'),
            eyebrows=self._settings.value('appearance/eyebrows','single'),
            color=self._settings.value('appearance/color','#a8ecff'))
        # Keyboard alternatives remain available even without window chrome.
        for sequence, callback in (('Ctrl+T', self.open_chat),
                                   ('Ctrl+,', self.open_settings),
                                   ('Ctrl+U', self.check_updates)):
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.activated.connect(callback)
        stored = self._settings.value('position')
        if stored is not None:
            try:
                self.move(stored)
            except (TypeError, ValueError):
                pass
        self.setToolTip('Click to talk · Drag to move · Right-click for options')
        self.chat_dialog = None
        self.settings_dialog = None
        self.character_dialog = None
        self.ideas_dialog = None
        self.update_thread = None
        self.reflection_thread = None
        self.learning_thread = None
        self._learning_timer = QTimer(self)
        self._learning_timer.setInterval(60000)
        self._learning_timer.timeout.connect(self._maybe_learn)
        self._learning_timer.start()
        QTimer.singleShot(8000,self._maybe_learn)
        self._reflection_timer = QTimer(self)
        self._reflection_timer.setInterval(10*60*1000)
        self._reflection_timer.timeout.connect(self._maybe_reflect)
        self._reflection_timer.start()
        QTimer.singleShot(120000, self._maybe_reflect)
        self.bubbles = BubbleController(self)
        self.wake_listener = WakeListener(self.core.data_dir, lambda: Microphone(self), self)
        self.wake_listener.heard.connect(self.open_conversation)
        self.wake_listener.failed.connect(self._wake_warning)
        self.wake_listener.stateChanged.connect(lambda on: setattr(self.face, 'wake_active', on))
        QTimer.singleShot(1600, self._maybe_start_wake)
        # Restart-time acknowledgement is shown only after the installer succeeded.
        from pathlib import Path
        complete = self.core.data_dir.parent/'.buddy_update'/'completed_version.txt'
        try:
            success = False
            if complete.is_file():
                success = complete.read_text(encoding='utf8').strip() == VERSION
                complete.unlink()
            else:
                # An upgrade FROM 0.23.7 still uses that version's updater, which
                # did not yet write the completion marker. Accept its success log
                # only when the backed-up old version differs from the new one.
                root = self.core.data_dir.parent
                backup_version = root/'.buddy_update'/'backup'/'VERSION.txt'
                legacy_log = root/'buddy-update.log'
                if backup_version.is_file() and legacy_log.is_file():
                    before = backup_version.read_text(encoding='utf8').strip()
                    log_text = legacy_log.read_text(encoding='utf8')
                    success = before != VERSION and log_text.startswith('Updated ')
            acknowledged = self.core.data_dir.parent/'.buddy_update'/'celebrated_version.txt'
            if success and (not acknowledged.is_file() or acknowledged.read_text(encoding='utf8').strip() != VERSION):
                acknowledged.write_text(VERSION,encoding='utf8')
                QTimer.singleShot(900, self._celebrate_updated)
        except OSError:
            pass

    def open_character_sheet(self):
        if self.character_dialog is None:
            self.character_dialog = CharacterSheetDialog(self)
        self.character_dialog.refresh()
        self.character_dialog.show()
        self.character_dialog.raise_()

    def open_idea_journal(self):
        if self.ideas_dialog is None:
            self.ideas_dialog = IdeaJournalDialog(self)
        self.ideas_dialog.refresh()
        self.ideas_dialog.show()
        self.ideas_dialog.raise_()

    def _maybe_learn(self):
        from datetime import datetime, timezone
        if self.learning_thread is not None or self.reflection_thread is not None or self.update_thread is not None:
            return
        if self.chat_dialog is not None and self.chat_dialog.worker_thread is not None:
            return
        today=datetime.now(timezone.utc).date().isoformat()
        # Maximum twelve extraction calls per UTC day, including no-change outcomes.
        if self.memory.learning_count_today(today)>=12:
            return
        if self.memory.next_unprocessed_exchange() is None:
            return
        self.learning_thread=QThread(self)
        self.learning_worker=LearningTask(self.brain)
        self.learning_worker.moveToThread(self.learning_thread)
        self.learning_thread.started.connect(self.learning_worker.run)
        self.learning_worker.finished.connect(self._learning_ready)
        self.learning_worker.finished.connect(self.learning_thread.quit)
        self.learning_thread.finished.connect(self._learning_cleanup)
        self.learning_thread.start()

    def _learning_ready(self, status):
        if self.character_dialog is not None and self.character_dialog.isVisible():
            self.character_dialog.refresh()
        if self.ideas_dialog is not None and self.ideas_dialog.isVisible():
            self.ideas_dialog.refresh()

    def _learning_cleanup(self):
        self.learning_worker.deleteLater()
        self.learning_thread.deleteLater()
        self.learning_worker=self.learning_thread=None
        if getattr(self,'_close_after_learning',False):
            self._close_after_learning=False
            QTimer.singleShot(0,self.close)

    def _maybe_reflect(self):
        from datetime import datetime, timezone
        if not self._settings.value('mind/reflect_enabled',True,type=bool):
            return
        if self.reflection_thread is not None or self.learning_thread is not None or self.update_thread is not None:
            return
        if self.chat_dialog is not None:
            chat = self.chat_dialog
            if chat.mic_recording or chat.worker_thread is not None or chat.voice_thread is not None:
                return
        date = datetime.now(timezone.utc).date().isoformat()
        if self.memory.reflection_calls_today(date) >= int(self._settings.value('mind/daily_limit',4)):
            return
        if not self.memory.reflection_due():
            return
        self.reflection_thread = QThread(self)
        self.reflection_worker = ReflectTask(self.brain,self.memory)
        self.reflection_worker.moveToThread(self.reflection_thread)
        self.reflection_thread.started.connect(self.reflection_worker.run)
        self.reflection_worker.finished.connect(self._reflection_ready)
        self.reflection_worker.failed.connect(self._reflection_failed)
        self.reflection_worker.finished.connect(self.reflection_thread.quit)
        self.reflection_worker.failed.connect(self.reflection_thread.quit)
        self.reflection_thread.finished.connect(self._reflection_cleanup)
        self.reflection_thread.start()

    def _reflection_ready(self, did_reflect):
        if did_reflect:
            self.setToolTip('Buddy saved a new reflection · Open his Character Sheet')
            if self.character_dialog is not None and self.character_dialog.isVisible():
                self.character_dialog.refresh()
            if self.ideas_dialog is not None and self.ideas_dialog.isVisible():
                self.ideas_dialog.refresh()
            # Only occasionally share a *recorded* idea, without demanding a reply.
            from datetime import datetime,timezone
            today=datetime.now(timezone.utc).date().isoformat()
            if (self.memory.count() >= 12 and
                self._settings.value('mind/last_overture','') != today and
                (self.chat_dialog is None or not self.chat_dialog.isVisible())):
                notes=self.memory.reflections(1)
                if notes:
                    self._settings.setValue('mind/last_overture',today)
                    thought=notes[0]['content'][:170]
                    self.bubbles.begin(thought,9000)
                    QTimer.singleShot(9500,self.bubbles.speaking_finished)

    def _reflection_failed(self, error):
        self.setToolTip('Reflection unavailable: '+str(error)[:120])

    def _reflection_cleanup(self):
        self.reflection_worker.deleteLater()
        self.reflection_thread.deleteLater()
        self.reflection_worker=self.reflection_thread=None
        if getattr(self,'_close_after_reflection',False):
            self._close_after_reflection=False
            QTimer.singleShot(0,self.close)

    def _wake_warning(self, message):
        self.setToolTip('Wake phrase unavailable: ' + message)

    def _maybe_start_wake(self):
        if not self._settings.value('wake_enabled',False,type=bool):
            return
        if self.chat_dialog is not None:
            if self.chat_dialog.mic_recording or self.chat_dialog.conversation_mode:
                return
        self.wake_listener.start()

    def pause_wake(self):
        self.wake_listener.stop()

    def _celebrate_updated(self):
        self.face.celebrate()
        QApplication.beep()
        self.bubbles.begin('We did it! Update complete!', 3200)
        QTimer.singleShot(3500, self.bubbles.speaking_finished)

    def closeEvent(self,event):
        if self.learning_thread is not None:
            self._close_after_learning=True
            self.hide()
            event.ignore()
            return
        if self.reflection_thread is not None:
            self._close_after_reflection=True
            self.hide()
            event.ignore()
            return
        self._reflection_timer.stop()
        self._learning_timer.stop()
        super().closeEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        if not self._settings.contains('position'):
            screen = self.screen() or QApplication.primaryScreen()
            if screen is not None:
                area = screen.availableGeometry()
                self.move(area.right() - self.width() - 24,
                          area.bottom() - self.height() - 24)

    def eventFilter(self, watched, event):
        if watched is self.face:
            kind = event.type()
            if kind == QEvent.MouseButtonPress and event.button() == Qt.LeftButton:
                self._drag_origin = event.globalPosition().toPoint()
                self._drag_window_origin = self.pos()
                self._did_drag = False
                return True
            if kind == QEvent.MouseMove and self._drag_origin is not None:
                delta = event.globalPosition().toPoint() - self._drag_origin
                if delta.manhattanLength() > 5:
                    self._did_drag = True
                if self._did_drag:
                    self.move(self._drag_window_origin + delta)
                    self.bubbles.reposition()
                return True
            if kind == QEvent.MouseButtonRelease and event.button() == Qt.LeftButton:
                moving = self._did_drag
                self._drag_origin = self._drag_window_origin = None
                self._did_drag = False
                if moving:
                    self._settings.setValue('position', self.pos())
                else:
                    self.open_chat()
                return True
            if kind == QEvent.ContextMenu:
                self._show_face_menu(event.globalPos())
                return True
            if kind == QEvent.MouseButtonPress and event.button() == Qt.RightButton:
                return True
            if kind == QEvent.MouseButtonRelease and event.button() == Qt.RightButton:
                return True
        return super().eventFilter(watched, event)

    def _show_face_menu(self, position):
        menu = QMenu(self)
        menu.addAction('💬 Talk to Buddy', self.open_chat)
        active = self.chat_dialog is not None and self.chat_dialog.conversation_mode
        if active:
            menu.addAction('⏹ End Conversation Mode', self.end_conversation)
        else:
            menu.addAction('🎙 Start Conversation Mode', self.open_conversation)
        menu.addAction('💡 Idea Journal', self.open_idea_journal)
        menu.addAction('🧠 Character Sheet', self.open_character_sheet)
        menu.addAction('⚙ Settings', self.open_settings)
        menu.addAction('↻ Check for updates', self.check_updates)
        menu.addSeparator()
        menu.addAction(f'Buddy Day Zero v{VERSION}').setEnabled(False)
        menu.addAction('✕ Quit Buddy', self.close)
        menu.exec(position)

    def _run_update_task(self, action, release=None):
        if self.update_thread is not None: return
        self.update_thread = QThread(self)
        self.update_worker = UpdateTask(action,release,self.core.data_dir.parent/'.buddy_update')
        self.update_worker.moveToThread(self.update_thread)
        self.update_thread.started.connect(self.update_worker.run)
        self.update_worker.progress.connect(lambda _percent: self.face.progress(-1))
        self.update_worker.finished.connect(self._update_finished)
        self.update_worker.failed.connect(self._update_failed)
        self.update_worker.finished.connect(self.update_thread.quit)
        self.update_worker.failed.connect(self.update_thread.quit)
        self.update_thread.finished.connect(self._update_cleanup)
        self.update_thread.start()

    def check_updates(self):
        if self.update_thread is not None:
            return
        if self.chat_dialog is not None:
            chat = self.chat_dialog
            if chat.mic_recording or chat.worker_thread is not None or chat.voice_thread is not None:
                QMessageBox.information(self, 'Finish your conversation',
                    'Please finish the current recording or response before updating Buddy.')
                return
        self._run_update_task('check')

    def _update_finished(self, result):
        if isinstance(result,dict):
            # Defer the modal approval dialog until the check QThread is cleaned up.
            # Nested dialog event loops previously raced _update_cleanup and lost approval.
            self._pending_check_result = result
        else:
            self._restart_archive = result
            self.face.progress(-1)
            QTimer.singleShot(200, self._install_and_restart)

    def _show_update_offer(self, result):
        self.face.progress(None)
        if not result['newer']:
            QMessageBox.information(self,'Buddy Day Zero',f'You are up to date (v{VERSION}).')
            return
        answer=QMessageBox.question(
            self,'Buddy Day Zero update',
            f"Version {result['version']} is available.\\n\\n{result['notes'][:500]}\\n\\nDownload and install?",
            QMessageBox.Yes | QMessageBox.No)
        if answer == QMessageBox.Yes:
            self.face.progress(-1)
            QTimer.singleShot(0,lambda release=result: self._run_update_task('download',release))

    def _announce_restart(self):
        self._announce_thread = QThread(self)
        self._announce_worker = VoiceTask('speak', 'Update is ready! I will now restart.')
        self._announce_worker.moveToThread(self._announce_thread)
        self._announce_thread.started.connect(self._announce_worker.run)
        self._announce_worker.finished.connect(self._announce_audio)
        self._announce_worker.failed.connect(self._announce_failure)
        self._announce_worker.finished.connect(self._announce_thread.quit)
        self._announce_worker.failed.connect(self._announce_thread.quit)
        self._announce_thread.finished.connect(self._announcement_cleanup)
        self._announce_thread.start()

    def _announce_audio(self, wav):
        self._restart_speaker = Speaker(self)
        self._restart_started = False
        self._restart_speaker.speakingChanged.connect(self._restart_voice_state)
        self.bubbles.begin('Update is ready! I will now restart.', 2400)
        try:
            self._restart_speaker.play_wav(wav)
            QTimer.singleShot(15000, self._install_and_restart)
        except Exception:
            QTimer.singleShot(1800, self._install_and_restart)

    def _announce_failure(self, message):
        self.bubbles.begin('Update is ready. I will now restart.', 2300)
        QTimer.singleShot(2300, self._install_and_restart)

    def _announcement_cleanup(self):
        self._announce_worker.deleteLater()
        self._announce_thread.deleteLater()
        self._announce_thread = None

    def _restart_voice_state(self, playing):
        if playing:
            self._restart_started = True
        elif getattr(self, '_restart_started', False):
            QTimer.singleShot(200, self._install_and_restart)

    def _install_and_restart(self):
        archive = getattr(self, '_restart_archive', None)
        if archive is None:
            return
        import os, sys, subprocess
        from pathlib import Path
        root = Path(__file__).resolve().parent.parent
        try:
            subprocess.Popen([sys.executable, str(root/'update_helper.py'),
                              '--root', str(root), '--archive', str(archive),
                              '--pid', str(os.getpid())], cwd=root,
                             creationflags=getattr(subprocess, 'CREATE_NEW_PROCESS_GROUP', 0))
        except OSError as exc:
            self.face.progress(None)
            QMessageBox.warning(self, 'Update could not start', str(exc))
            return
        self._restart_archive = None
        QApplication.instance().quit()

    def _update_failed(self, message):
        self.face.progress(None)
        QMessageBox.warning(self,'Update error',message)

    def _update_cleanup(self):
        self.update_worker.deleteLater()
        self.update_thread.deleteLater()
        self.update_thread = None
        result=getattr(self,'_pending_check_result',None)
        self._pending_check_result=None
        if result is not None:
            QTimer.singleShot(0,lambda offer=result: self._show_update_offer(offer))

    def open_conversation(self):
        # Start the existing conversation engine without showing the chat window.
        if self.chat_dialog is None:
            self.chat_dialog = ChatDialog(self)
        if not self.chat_dialog.conversation_mode:
            self.chat_dialog.toggle_conversation_mode()

    def end_conversation(self):
        if self.chat_dialog is not None and self.chat_dialog.conversation_mode:
            self.chat_dialog.toggle_conversation_mode()

    def open_chat(self):
        if self.chat_dialog is None: self.chat_dialog = ChatDialog(self)
        self.chat_dialog.show(); self.chat_dialog.raise_(); self.chat_dialog.activateWindow()
        self.chat_dialog.input.setFocus()

    def open_settings(self):
        if self.settings_dialog is None: self.settings_dialog = SettingsDialog(self)
        self.settings_dialog.name.setText(self.core.snapshot()['name'])
        self.settings_dialog.show(); self.settings_dialog.raise_()
