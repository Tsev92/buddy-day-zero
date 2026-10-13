"""Standalone desktop shell around the original Buddy face and Day Zero brain."""
from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QApplication, QDialog, QHBoxLayout, QLabel,
    QLineEdit, QMainWindow, QPushButton, QScrollArea, QSizePolicy,
    QTextBrowser, QVBoxLayout, QWidget, QMessageBox)
from .face import Face
from .version import VERSION
from .updates import check_release, download_verified, UpdateError

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
        layout.addLayout(row)
        self.status = QLabel('')
        layout.addWidget(self.status)
        for message in buddy.memory.recent(80):
            self.append(message['role'], message['content'])
        if not buddy.memory.count():
            self.append('assistant', '…Hello?')
        self.worker_thread = None

    def append(self, role, message):
        from html import escape
        name = self.buddy.core.snapshot()['name'] if role == 'assistant' else 'You'
        self.log.append(f'<p style="margin:7px 0"><b>{escape(name)}:</b> {escape(message).replace(chr(10), "<br>")}</p>')
        self.log.verticalScrollBar().setValue(self.log.verticalScrollBar().maximum())

    def send(self):
        message = self.input.text().strip()
        if not message or self.worker_thread is not None: return
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

    def failed(self, error):
        self.status.setText(error)
        self.append('assistant', f'[Message could not be sent: {error}]')

    def cleanup(self):
        self.worker.deleteLater()
        self.worker_thread.deleteLater()
        self.worker_thread = None
        self.input.setEnabled(True); self.send_button.setEnabled(True)
        self.buddy.face.mood = 'idle'
        self.input.setFocus()

    def closeEvent(self, event):
        if self.worker_thread is not None:
            self.hide(); event.ignore(); return
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
        note = QLabel('Voice and audio controls return in a later release.\nThis build keeps the Day Zero memory separate.')
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
        self.setWindowFlags(Qt.Window | Qt.WindowStaysOnTopHint)
        self.setStyleSheet(STYLE)
        self.setMinimumSize(300, 225)
        self.resize(440, 305)
        self.face = Face()  # Day Zero native face
        self.face.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        root = QWidget(); layout = QVBoxLayout(root)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.addWidget(self.face, 1)
        controls = QHBoxLayout()
        chat = QPushButton('💬 Talk')
        chat.clicked.connect(self.open_chat)
        settings = QPushButton('⚙ Settings')
        settings.clicked.connect(self.open_settings)
        update = QPushButton('↻ Update')
        update.clicked.connect(self.check_updates)
        controls.addWidget(chat); controls.addStretch(); controls.addWidget(update); controls.addWidget(settings)
        layout.addLayout(controls)
        self.setCentralWidget(root)
        self.chat_dialog = None
        self.settings_dialog = None
        self.update_thread = None

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
