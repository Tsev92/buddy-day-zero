"""Standalone desktop shell around the original Buddy face and Day Zero brain."""
from PySide6.QtCore import QObject, Qt, QThread, Signal, QEvent, QSettings, QTimer
from PySide6.QtGui import QFont, QAction, QKeySequence, QShortcut
from PySide6.QtWidgets import (QApplication, QDialog, QHBoxLayout, QLabel,
    QLineEdit, QMainWindow, QPushButton, QScrollArea, QSizePolicy, QMenu,
    QTextBrowser, QVBoxLayout, QWidget, QMessageBox)
from .face import Face
from .version import VERSION
from .audio import Microphone, Speaker, transcribe_wav, synthesize_wav
from .updates import check_release, download_verified, UpdateError
from .bubbles import BubbleController
from .listening import SilenceDetector

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
    finished = Signal(object)
    failed = Signal(str)
    def __init__(self, action, release=None, folder=None):
        super().__init__(); self.action=action; self.release=release; self.folder=folder
    def run(self):
        try:
            if self.action == 'check': self.finished.emit(check_release())
            else: self.finished.emit(download_verified(self.release,self.folder))
        except Exception as exc: self.failed.emit(str(exc))

class VoiceTask(QObject):
    finished = Signal(object)
    failed = Signal(str)
    def __init__(self, action, value):
        super().__init__()
        self.action, self.value = action, value
    def run(self):
        try:
            result = transcribe_wav(self.value) if self.action == 'transcribe' else synthesize_wav(self.value)
            self.finished.emit(result)
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
        layout.addLayout(row)
        self.conversation_button = QPushButton('Start Conversation Mode')
        self.conversation_button.clicked.connect(self.toggle_conversation_mode)
        layout.addWidget(self.conversation_button)
        self.status = QLabel('')
        layout.addWidget(self.status)
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
            try:
                audio = self.mic.stop()
                self.buddy.face.mood = 'thinking'
                self._voice_task('transcribe', audio)
                self.status.setText('Transcribing your voice…')
            except Exception as exc:
                self.voice_failed(str(exc))
            return
        if self.worker_thread is not None or self.voice_thread is not None:
            return
        try:
            self.mic.start()
            self.mic_recording = True
            self._mic_offset = 0
            self._detector = SilenceDetector()
            self.monitor.start()
            self.mic_button.setText('■ Cancel')
            self.buddy.face.mood = 'listening'
            self.status.setText('Listening… pause when you finish speaking.')
        except Exception as exc:
            self.voice_failed(str(exc))

    def _poll_recording(self):
        if not self.mic_recording or self._detector is None:
            return
        chunk, self._mic_offset = self.mic.read_since(self._mic_offset)
        decision = self._detector.inspect(chunk)
        if decision == 'send':
            self.mic_recording = False
            self.monitor.stop()
            self.mic_button.setText('Record')
            try:
                audio = self.mic.stop()
                self.buddy.face.mood = 'thinking'
                self._voice_task('transcribe', audio)
            except Exception as exc:
                self.voice_failed(str(exc))
        elif decision == 'timeout':
            self.monitor.stop()
            self.mic.cancel()
            self.mic_recording = False
            self.mic_button.setText('Record')
            self.buddy.face.mood = 'idle'
            self.status.setText('No speech detected.')
            if self.conversation_mode:
                self.toggle_conversation_mode()

    def _voice_task(self, action, value):
        if self.voice_thread is not None: return
        self.voice_action = action
        self.voice_thread = QThread(self)
        self.voice_worker = VoiceTask(action, value)
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
            self.input.setText(value)
            self.status.setText('')
            self._send_transcription = True
        else:
            try:
                self.speaker.play_wav(value)
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

    def speaking_changed(self, active):
        self.buddy.face.mood = 'speaking' if active else 'idle'

    def send(self):
        message = self.input.text().strip()
        if not message or self.worker_thread is not None or self.mic_recording: return
        if len(message) > 4000:
            self.status.setText('Message too long (4000 characters maximum).'); return
        self.input.clear()
        self.append('user', message)
        self.input.setEnabled(False); self.send_button.setEnabled(False)
        self.status.setText('Buddy is thinking…')
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
        self.status.setText('')
        self.buddy.face.express('curious', 2.0)
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
        self.speaker.stop()
        super().closeEvent(event)

class SettingsDialog(QDialog):
    def __init__(self, buddy):
        super().__init__(buddy)
        self.buddy = buddy
        self.setWindowTitle('Buddy Day Zero Settings')
        self.setStyleSheet(STYLE)
        self.setMinimumWidth(330)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel('Buddy name'))
        self.name = QLineEdit(buddy.core.snapshot()['name'])
        layout.addWidget(self.name)
        note = QLabel('Audio recording and spoken replies are available from Talk.\nBuddy keeps his Day Zero memory separate.')
        note.setWordWrap(True); layout.addWidget(note)
        save = QPushButton('Save name…')
        save.clicked.connect(self.save_name)
        layout.addWidget(save)
        layout.addWidget(QLabel(f'Buddy Day Zero v{VERSION}'))
        update = QPushButton('Check for updates…')
        update.clicked.connect(self.buddy.check_updates)
        layout.addWidget(update)

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
        self.update_thread = None

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
        self.update_worker.finished.connect(self._update_finished)
        self.update_worker.failed.connect(self._update_failed)
        self.update_worker.finished.connect(self.update_thread.quit)
        self.update_worker.failed.connect(self.update_thread.quit)
        self.update_thread.finished.connect(self._update_cleanup)
        self.update_thread.start()

    def check_updates(self):
        if self.update_thread is not None: return
        self._run_update_task('check')

    def _update_finished(self, result):
        if isinstance(result,dict):
            if not result['newer']:
                QMessageBox.information(self,'Buddy Day Zero',f'You are up to date (v{VERSION}).')
                return
            answer=QMessageBox.question(self,'Buddy Day Zero update',
                f"Version {result['version']} is available.\n\n{result['notes'][:500]}\n\nDownload and install?",
                QMessageBox.Yes | QMessageBox.No)
            if answer == QMessageBox.Yes: self._queued_release = result
        else:
            answer=QMessageBox.question(self,'Update downloaded',
                'Update verified. Buddy will close, install the update, and reopen. Continue?',
                QMessageBox.Yes | QMessageBox.No)
            if answer != QMessageBox.Yes: return
            import os,sys,subprocess
            from pathlib import Path
            root=Path(__file__).resolve().parent.parent
            subprocess.Popen([sys.executable,str(root/'update_helper.py'),
                              '--root',str(root),'--archive',str(result),'--pid',str(os.getpid())],
                             cwd=root,creationflags=getattr(subprocess,'CREATE_NEW_PROCESS_GROUP',0))
            QApplication.instance().quit()

    def _update_failed(self, message):
        QMessageBox.warning(self,'Update error',message)

    def _update_cleanup(self):
        self.update_worker.deleteLater()
        self.update_thread.deleteLater()
        self.update_thread = None
        queued=getattr(self,'_queued_release',None)
        self._queued_release=None
        if queued: self._run_update_task('download',queued)

    def open_chat(self):
        if self.chat_dialog is None: self.chat_dialog = ChatDialog(self)
        self.chat_dialog.show(); self.chat_dialog.raise_(); self.chat_dialog.activateWindow()
        self.chat_dialog.input.setFocus()

    def open_settings(self):
        if self.settings_dialog is None: self.settings_dialog = SettingsDialog(self)
        self.settings_dialog.name.setText(self.core.snapshot()['name'])
        self.settings_dialog.show(); self.settings_dialog.raise_()
