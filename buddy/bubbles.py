"""Transient comic-style speech bubbles attached to Buddy's floating face."""
import math
import re
from PySide6.QtCore import Qt, QRectF, QPointF, QTimer, QPoint, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QFont
from PySide6.QtWidgets import QWidget, QApplication

def split_phrases(text, max_chars=82):
    """Split at sentence/phrase boundaries without cutting words."""
    tokens = re.findall(r'\S+\s*', text.strip())
    result, current = [], ''
    for token in tokens:
        word = token.strip()
        if current and len(current) + len(token) > max_chars:
            result.append(current.strip()); current = ''
        current += token
        if len(current) >= 29 and re.search(r'[.!?;,:—]$', word):
            result.append(current.strip()); current = ''
    if current.strip():
        result.append(current.strip())
    return result or ['']

class SpeechBubble(QWidget):
    """A small dark bubble; tail sits on the side facing the face."""
    def __init__(self, parent=None):
        super().__init__(parent, Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint |
                         Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setFixedSize(286, 106)
        self.content = ''
        self.full_phrase = ''
        self.tint = QColor('#a78bfa')
        self.tail_side = 'left'
        self.tail_edge = 'bottom'
        self.setWindowTitle('Buddy speech')

    def set_phrase(self, phrase, color, side, edge):
        self.content = phrase
        self.full_phrase = phrase
        self.tint = QColor(color)
        self.tail_side = side
        self.tail_edge = edge
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        # A transparent outer margin allows the tinted border and tail to glow.
        body = QRectF(17, 13, 252, 78)
        path = QPainterPath()
        path.addRoundedRect(body, 16, 16)
        tail = QPainterPath()
        if self.tail_edge == 'top':
            x = 60 if self.tail_side == 'left' else 223
            tail.moveTo(x-15, 15); tail.lineTo(x-5, 2); tail.lineTo(x+15, 15)
        else:
            x = 60 if self.tail_side == 'left' else 223
            tail.moveTo(x-15, 89); tail.lineTo(x-5, 104); tail.lineTo(x+15, 89)
        path = path.united(tail)
        glow = QColor(self.tint); glow.setAlpha(55)
        p.setPen(QPen(glow, 8))
        p.setBrush(QColor('#29334e'))
        p.drawPath(path)
        p.setPen(QPen(self.tint, 2.4))
        p.drawPath(path)
        p.setPen(QColor('#f0f4ff'))
        f = QFont('Segoe UI', 10)
        p.setFont(f)
        p.drawText(QRectF(34, 22, 220, 62),
                   Qt.AlignVCenter | Qt.AlignLeft | Qt.TextWordWrap, self.content)
        p.end()

class BubbleController:
    """Display one short phrase at a time; duration tracks spoken WAV length."""
    def __init__(self, face_window):
        self.face = face_window
        self.bubble = SpeechBubble()
        self.timer = QTimer(face_window)
        self.timer.timeout.connect(self._advance)
        self.hide_timer = QTimer(face_window)
        self.hide_timer.setSingleShot(True)
        self.hide_timer.timeout.connect(self._fade_out)
        self.fade_in = QPropertyAnimation(self.bubble, b'windowOpacity', face_window)
        self.fade_in.setDuration(180)
        self.fade_in.setEasingCurve(QEasingCurve.OutCubic)
        self.fade_out = QPropertyAnimation(self.bubble, b'windowOpacity', face_window)
        self.fade_out.setDuration(370)
        self.fade_out.finished.connect(self.bubble.hide)
        self.phrases = []
        self.index = 0
        self.duration_ms = 0
        self._active = False
        self.last_position = -1

    def begin(self, text, duration_ms):
        self.stop()
        self.phrases = split_phrases(text)
        self.index = 0
        self.duration_ms = max(1000, int(duration_ms))
        self._active = True
        self._display()
        self.bubble.content = ''
        self.bubble.update()

    def sync_position(self, position_ms):
        """Reveal words from the actual playback clock, not a separate timer."""
        if not self._active or not self.phrases:
            return
        position_ms = max(0, min(self.duration_ms, int(position_ms)))
        if position_ms < self.last_position:
            self.last_position = -1
        self.last_position = position_ms
        # Allocate more time to longer phrases; approximate word onset naturally.
        weights = [max(5, len(part)) for part in self.phrases]
        total = sum(weights)
        cursor = 0
        selected = len(self.phrases)-1
        portion = 1.0
        for index, weight in enumerate(weights):
            span = self.duration_ms * weight/total
            if position_ms < cursor + span:
                selected = index
                portion = (position_ms-cursor)/max(1,span)
                break
            cursor += span
        if selected != self.index:
            self.index = selected
            self._display()
        phrase = self.phrases[selected]
        # Reveal word groups progressively (no mid-letter chopping).
        words = phrase.split()
        reveal_count = min(len(words), max(1, math.ceil(len(words)*portion)))
        revealed = ' '.join(words[:reveal_count])
        if revealed != self.bubble.content:
            self.bubble.content = revealed
            self.bubble.update()

    def _display(self):
        if self.index >= len(self.phrases):
            self.timer.stop()
            self.hide_timer.start(3400)
            self._active = False
            return
        screen = self.face.screen() or QApplication.primaryScreen()
        if screen is None:
            return
        area = screen.availableGeometry()
        rect = self.face.frameGeometry()
        # Prefer beside Buddy; alternate above/below when near a screen edge.
        to_right = area.right() - rect.right() >= 294
        to_left = rect.left() - area.left() >= 294
        x = rect.right() + 10 if to_right or not to_left else rect.left() - 296
        x = max(area.left(), min(x, area.right() - 286))
        desired = rect.top() + (self.index % 2) * 99 - 35
        y = max(area.top(), min(desired, area.bottom() - 106))
        tail_edge = 'bottom' if y + 53 < rect.center().y() else 'top'
        tail_side = 'left' if x > rect.center().x() else 'right'
        self.bubble.set_phrase(self.phrases[self.index],
                               self.face.face.border_color().name(), tail_side, tail_edge)
        self.bubble.move(x,y)
        self.fade_out.stop()
        self.fade_in.stop()
        self.bubble.setWindowOpacity(0.0)
        self.bubble.show()
        self.bubble.raise_()
        self.fade_in.setStartValue(0.0)
        self.fade_in.setEndValue(1.0)
        self.fade_in.start()

    def _advance(self):
        self.index += 1
        self._display()

    def _fade_out(self):
        if not self.bubble.isVisible():
            return
        self.fade_in.stop()
        self.fade_out.stop()
        self.fade_out.setStartValue(self.bubble.windowOpacity())
        self.fade_out.setEndValue(0.0)
        self.fade_out.start()

    def speaking_finished(self):
        # Keep the final phrase visible, then disappear naturally.
        self.timer.stop()
        if self.phrases:
            self.index = len(self.phrases)-1
            self._display()
            self.bubble.content = self.phrases[-1]
            self.bubble.update()
        self._active = False
        self.hide_timer.start(3300)

    def reposition(self):
        if self.bubble.isVisible():
            self._display()

    def stop(self):
        self.timer.stop()
        self.hide_timer.stop()
        self.fade_in.stop()
        self.fade_out.stop()
        self.bubble.hide()
        self._active = False
