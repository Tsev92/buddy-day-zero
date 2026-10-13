"""Single, expanding, auto-scrolling speech bubble for Buddy's floating face.

Audio playback and caption rendering are separate: the entire response is stored
before playback, and the bubble uses a monotonic timer with safe completion.
"""
import math
import re
from PySide6.QtCore import Qt, QRectF, QTimer, QElapsedTimer, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QTextDocument, QFont
from PySide6.QtWidgets import QWidget, QApplication


def split_phrases(text, max_chars=82):
    """Legacy helper retained for callers; presentation uses one bubble now."""
    tokens = re.findall(r'\S+\s*', text.strip())
    phrases, current = [], ''
    for token in tokens:
        if current and len(current) + len(token) > max_chars:
            phrases.append(current.strip())
            current = ''
        current += token
        if len(current) >= 29 and re.search(r'[.!?;,:—]$', token.strip()):
            phrases.append(current.strip())
            current = ''
    if current.strip():
        phrases.append(current.strip())
    return phrases or ['']


def visible_words(text, fraction):
    """Always return the prefix of the COMPLETE response, never just a phrase."""
    words = list(re.finditer(r'\S+', text))
    if not words:
        return ''
    count = min(len(words), max(1, math.ceil(len(words) * max(0.0, min(1.0, fraction)))))
    return text[:words[count - 1].end()]


class SpeechBubble(QWidget):
    WIDTH = 300
    MIN_HEIGHT = 66
    MARGIN = 17
    TEXT_WIDTH = WIDTH - 2 * 33

    def __init__(self, parent=None):
        super().__init__(parent, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint |
                         Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setFixedSize(self.WIDTH, self.MIN_HEIGHT)
        self.full_text = ''
        self.content = ''
        self.tint = QColor('#a78bfa')
        self.tail_side = 'left'
        self._scroll = 0.0
        self._scroll_target = 0.0
        self._max_height = 203
        self.document = QTextDocument(self)
        self.document.setDocumentMargin(0)
        self.document.setDefaultFont(QFont('Segoe UI', 10))
        self.document.setTextWidth(self.TEXT_WIDTH)
        self.setWindowTitle('Buddy speech')

    def set_text(self, text, final=False):
        self.content = text
        self.document.setPlainText(text)
        # Document height is the full text height, never a truncated sentence.
        needed = math.ceil(self.document.size().height()) + 32
        height = max(self.MIN_HEIGHT, min(self._max_height, needed))
        if self.height() != height:
            self.setFixedHeight(height)
        inner_height = max(1, height - 30)
        self._scroll_target = max(0.0, self.document.size().height() - inner_height)
        if final:
            self._scroll = self._scroll_target
        self.update()

    def animate_scroll(self):
        if abs(self._scroll_target - self._scroll) > 0.1:
            self._scroll += (self._scroll_target - self._scroll) * 0.28
            self.update()
        else:
            self._scroll = self._scroll_target

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        h = self.height()
        body = QRectF(13, 5, self.width() - 26, h - 10)
        path = QPainterPath()
        path.addRoundedRect(body, 16, 16)
        # Horizontal tail always faces the center of Buddy's floating face.
        cy = h / 2
        tail = QPainterPath()
        if self.tail_side == 'left':
            tail.moveTo(16, cy - 13)
            tail.lineTo(1, cy)
            tail.lineTo(16, cy + 13)
        else:
            w = self.width()
            tail.moveTo(w - 16, cy - 13)
            tail.lineTo(w - 1, cy)
            tail.lineTo(w - 16, cy + 13)
        path = path.united(tail)
        glow = QColor(self.tint)
        glow.setAlpha(48)
        p.setPen(QPen(glow, 7))
        p.setBrush(QColor('#29334e'))
        p.drawPath(path)
        p.setPen(QPen(self.tint, 2.2))
        p.drawPath(path)
        p.save()
        p.setClipRect(QRectF(28, 16, self.TEXT_WIDTH + 2, h - 30))
        p.translate(30, 16 - self._scroll)
        self.document.setDefaultStyleSheet('body { color: #f0f4ff; }')
        context = __import__('PySide6.QtGui', fromlist=['QAbstractTextDocumentLayout']).QAbstractTextDocumentLayout.PaintContext()
        context.palette.setColor(context.palette.Text, QColor('#f0f4ff'))
        self.document.documentLayout().draw(p, context)
        p.restore()
        p.end()


class BubbleController:
    """One stable window for the entire utterance, with independent reveal timer."""

    def __init__(self, face_window):
        self.face = face_window
        self.bubble = SpeechBubble()
        self.timer = QTimer(face_window)
        self.timer.setInterval(35)
        self.timer.timeout.connect(self._tick)
        self.clock = QElapsedTimer()
        self.hide_timer = QTimer(face_window)
        self.hide_timer.setSingleShot(True)
        self.hide_timer.timeout.connect(self._fade_out)
        self.fade_in = QPropertyAnimation(self.bubble, b'windowOpacity', face_window)
        self.fade_in.setDuration(170)
        self.fade_in.setEasingCurve(QEasingCurve.OutCubic)
        self.fade_out = QPropertyAnimation(self.bubble, b'windowOpacity', face_window)
        self.fade_out.setDuration(400)
        self.fade_out.finished.connect(self.bubble.hide)
        self.full_text = ''
        self.duration_ms = 0
        self.last_position = 0
        self._active = False
        self._last_geometry = None

    def begin(self, text, duration_ms):
        self.stop()
        self.full_text = str(text or '').strip()
        self.duration_ms = max(400, int(duration_ms))
        self.last_position = 0
        self._active = True
        self.clock.start()
        self.bubble.full_text = self.full_text
        self.bubble._max_height = max(self.bubble.MIN_HEIGHT, self.face.height())
        self.bubble.set_text('', final=True)
        self.reposition()
        self.bubble.setWindowOpacity(0)
        self.bubble.show()
        self.fade_in.setStartValue(0)
        self.fade_in.setEndValue(1)
        self.fade_in.start()
        self.timer.start()

    def _tick(self):
        if self._active:
            # QMediaPlayer sometimes never reports positions on Windows.
            self.sync_position(self.clock.elapsed())
        self.bubble.animate_scroll()

    def sync_position(self, position_ms):
        if not self._active:
            return
        position_ms = max(self.last_position, int(position_ms), self.clock.elapsed())
        self.last_position = min(position_ms, self.duration_ms)
        fraction = self.last_position / self.duration_ms
        if self.last_position >= self.duration_ms:
            text = self.full_text
        else:
            text = visible_words(self.full_text, fraction)
        if text != self.bubble.content:
            old_height = self.bubble.height()
            self.bubble.set_text(text, final=False)
            if old_height != self.bubble.height():
                self.reposition()

    def reposition(self):
        screen = self.face.screen() or QApplication.primaryScreen()
        if screen is None:
            return
        rect = self.face.frameGeometry()
        area = screen.availableGeometry()
        width = self.bubble.width()
        gap = 6
        right_room = area.right() - rect.right()
        left_room = rect.left() - area.left()
        place_right = right_room >= width + gap or right_room >= left_room
        x = rect.right() + gap if place_right else rect.left() - width - gap
        x = max(area.left(), min(x, area.right() - width + 1))
        self.bubble.tail_side = 'left' if x > rect.center().x() else 'right'
        y = rect.center().y() - self.bubble.height() / 2
        y = max(area.top(), min(int(y), area.bottom() - self.bubble.height() + 1))
        self.bubble.move(int(x), int(y))
        self.bubble.update()

    def speaking_finished(self):
        if not self.full_text:
            self.stop()
            return
        self._active = False
        self.bubble.set_text(self.full_text, final=True)
        self.reposition()
        self.timer.start()
        self.hide_timer.start(3600)

    def _fade_out(self):
        self.timer.stop()
        self.fade_in.stop()
        self.fade_out.stop()
        self.fade_out.setStartValue(self.bubble.windowOpacity())
        self.fade_out.setEndValue(0.0)
        self.fade_out.start()

    def stop(self):
        self._active = False
        self.timer.stop()
        self.hide_timer.stop()
        self.fade_in.stop()
        self.fade_out.stop()
        self.bubble.hide()
