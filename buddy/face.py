"""Buddy's Day Zero-inspired native Qt face. No browser or legacy imports."""
import math
import random
import time
from PySide6.QtCore import Qt, QRectF, QPointF, QTimer
from PySide6.QtGui import QColor, QPainter, QPen, QPainterPath, QRadialGradient
from PySide6.QtWidgets import QWidget

class Face(QWidget):
    EXPRESSIONS = (
        "neutral", "excited", "flustered", "surprised", "skeptical",
        "curious", "amused", "thoughtful", "pleased", "proud",
        "sleepy", "mischievous", "worried", "determined", "inspired"
    )
    def __init__(self):
        super().__init__()
        self.setMinimumSize(240, 135)
        self.display_aspect = 16 / 9
        self.mood = "idle"
        self.expression = "neutral"
        self.expression_until = 0.0
        self.audio_level = 0.0
        self.mic_level = 0.0
        self.eye_style = 'pupils'
        self.mouth_style = 'classic'
        self.eye_color = '#a8ecff'
        self.eyebrow_style = 'single'
        self._nod = 0
        self._nod_phase = -100
        self._next_nod = time.monotonic() + 1
        self.update_percent = None
        self.celebrating = False
        self.celebrate_ticks = 0
        self.wake_active = False
        self.tick = 0
        self.blink_amount = 0.0
        self.blink_until = 0.0
        self.next_blink = time.monotonic() + random.uniform(1.8, 5.2)
        self.gaze_x = self.gaze_y = 0.0
        self.target_x = self.target_y = 0.0
        self.next_gaze = time.monotonic() + 1.4
        self.next_idle = time.monotonic() + 5.0
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.animate)
        self.timer.start(35)

    def customize(self, eyes=None, mouth=None, color=None, eyebrows=None):
        if eyes in ('classic','pupils','round','sleepy','pixel'):
            self.eye_style = eyes
        if mouth in ('classic','smile','wry','cat','pixel','lips'):
            self.mouth_style = mouth
        if color in ('#a8ecff','#bda7ff','#9becba','#ffc58f','#ffc1de'):
            self.eye_color = color
        if eyebrows in ('single','both','none'):
            self.eyebrow_style = eyebrows
        self.update()

    def border_color(self):
        tones = {'neutral':'#55cfe7','curious':'#a77bff','excited':'#ffd35b',
                 'flustered':'#ff83b4','surprised':'#fff09a','skeptical':'#ad88e8',
                 'amused':'#ff9e76','thoughtful':'#829bff','pleased':'#6fe1b2',
                 'proud':'#ffc16b','sleepy':'#5078c8','mischievous':'#db77e8',
                 'worried':'#7896d7','determined':'#ff9971','inspired':'#e2b0ff'}
        statuses = {'listening':'#49e3f4','thinking':'#9676f5',
                    'error':'#ff657b','speaking':'#55cfe7','updating':'#b08aff'}
        if self.celebrating:
            return QColor('#78e5ac')
        return QColor(statuses.get(self.mood, tones.get(self.expression, '#55cfe7')))

    def progress(self, percent=None):
        self.update_percent = percent
        self.mood = 'updating' if percent is not None else 'idle'
        self.update()

    def celebrate(self):
        self.update_percent = 100
        self.celebrating = True
        self.celebrate_ticks = 0
        self.express('excited', 4.0)

    def express(self, expression, duration=7.0):
        self.expression = expression if expression in self.EXPRESSIONS else "neutral"
        self.expression_until = time.monotonic() + duration if duration else float("inf")
        self.update()

    def animate(self):
        now = time.monotonic()
        self.tick += 1
        if self.celebrating:
            self.celebrate_ticks += 1
            if self.celebrate_ticks > 115:
                self.celebrating = False
                self.progress(None)
        if now >= self.expression_until and self.expression != "neutral":
            self.expression = "neutral"
        if now >= self.next_blink:
            self.blink_until = now + 0.18
            self.next_blink = now + random.uniform(2.2, 6.0)
        self.blink_amount = max(0.055, abs(now - (self.blink_until - .09)) / .09) if now < self.blink_until else 1.0
        if now >= self.next_gaze:
            self.target_x = random.choice((-16,-10,-5,0,0,5,10,16))
            self.target_y = random.choice((-7,-3,0,0,4,7))
            self.next_gaze = now + random.uniform(.7, 2.3)
        if self.mood == 'thinking':
            self.target_x, self.target_y = 8, -12
        elif self.mood == 'listening':
            self.target_x, self.target_y = 0, 0
        self.gaze_x += (self.target_x - self.gaze_x) * .15
        self.gaze_y += (self.target_y - self.gaze_y) * .085
        if self.mood == 'listening' and self.mic_level > .12 and now >= self._next_nod:
            self._nod_phase = now
            self._next_nod = now + random.uniform(1.4, 2.9)
        phase = now - self._nod_phase
        self._nod = (5 * math.sin(phase * math.pi / .66) ** 2
                     if self.mood == 'listening' and 0 <= phase < .66 else 0)
        # Return to the lively OG idle cadence.
        if self.mood == "idle" and now >= self.next_idle and self.expression == "neutral":
            self.express("curious", random.uniform(1.0, 2.0))
            self.next_idle = now + random.uniform(4.5, 9)
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        # Leave the area outside Buddy's rounded face transparent in the frameless window.
        w,h = self.width(),self.height()
        s = min(w/320, h/180)
        p.translate((w-320*s)/2,(h-180*s)/2)
        p.scale(s,s)
        t = self.tick*.035
        e = self.expression
        # Day Zero palette: indigo face, soft cyan pill-shaped eyes, gentle bloom.
        bg = QColor("#222943")
        p.setPen(Qt.NoPen)
        p.setBrush(bg)
        p.drawRoundedRect(QRectF(3,3,314,174),38,38)
        # Restored V0.22.1 color identity: expressions tint the glowing border.
        border_colors = {
            'neutral':'#55cfe7', 'curious':'#a77bff',
            'excited':'#ffd35b', 'flustered':'#ff83b4',
            'surprised':'#fff09a', 'skeptical':'#ad88e8',
            'amused':'#ff9e76', 'thoughtful':'#829bff',
            'pleased':'#6fe1b2', 'proud':'#ffc16b',
            'sleepy':'#5078c8', 'mischievous':'#db77e8',
            'worried':'#7896d7', 'determined':'#ff9971',
            'inspired':'#e2b0ff'
        }
        status_colors = {
            'listening':'#49e3f4', 'thinking':'#9676f5',
            'error':'#ff657b', 'speaking':'#55cfe7'
        }
        border = self.border_color()
        rate = .24 if e == 'sleepy' else (4.5 if self.mood == 'speaking' else 1.15)
        pulse = .72 + .28 * math.sin(t * rate)
        if self.mood == 'speaking':
            pulse = max(pulse, .65 + .28 * math.sin(t * 7) ** 2)
        p.setBrush(Qt.NoBrush)
        for inset, thickness, alpha in ((3.5, 6.5, 30), (5.5, 3.6, 85), (6.5, 1.8, 230)):
            glow = QColor(border)
            glow.setAlpha(int(alpha * pulse))
            p.setPen(QPen(glow, thickness, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            p.drawRoundedRect(QRectF(inset,inset,320-2*inset,180-2*inset),36,36)
        if self.update_percent is not None and not self.celebrating:
            # Indeterminate spinner: archive servers don't always send a usable size.
            p.setBrush(Qt.NoBrush)
            for x, offset in ((105, 0), (215, 165)):
                ring = QRectF(x-27, 51, 54, 54)
                p.setPen(QPen(QColor('#45536c'), 6))
                p.drawEllipse(ring)
                p.setPen(QPen(QColor('#a8ecff'), 7, Qt.SolidLine, Qt.RoundCap))
                start_angle = int((self.tick * 9 + offset) % 360)
                p.drawArc(ring, start_angle * 16, 95 * 16)
            p.end()
            return
        if self.celebrating:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor('#ffe49b'))
            for i in range(12):
                angle = i * 1.87 + self.tick * .09
                radius = 58 + 15 * math.sin(i * 1.9)
                x = 160 + radius * math.cos(angle) * 1.8
                y = 88 + radius * math.sin(angle)
                size = 3.2 + i % 3
                p.drawEllipse(QRectF(x-size, y-size, size*2, size*2))
        if self.wake_active and self.update_percent is None:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor('#49e3f4'))
            p.drawEllipse(QRectF(22, 21, 7, 7))
        if self.mood == 'listening':
            # The familiar animated ( ) brackets show when Buddy is listening.
            glow = QColor('#a8ecff')
            glow.setAlpha(int(150 + 90 * (0.5 + 0.5 * math.sin(t * 5))))
            p.setPen(QPen(glow, 4.2, Qt.SolidLine, Qt.RoundCap))
            p.setBrush(Qt.NoBrush)
            for cx, sign in ((34, -1), (286, 1)):
                bracket = QPainterPath()
                bracket.moveTo(cx - sign * 2, 42)
                bracket.cubicTo(cx + sign * 12, 61, cx + sign * 12, 103,
                                cx - sign * 2, 125)
                p.drawPath(bracket)
        p.save()
        p.translate(160,93 + self._nod)
        if e == "curious": p.rotate(3.2)
        elif e == "skeptical": p.rotate(-3.0)
        elif e == "flustered": p.rotate(1.8*math.sin(t*2))
        p.translate(-160,-93)
        eye = QColor(self.eye_color)
        dark = QColor("#222943")
        eyes = ((105,83),(215,83))
        for idx,(cx,cy) in enumerate(eyes):
            cx += self.gaze_x
            cy += self.gaze_y
            width,height = 51.0,76.0
            if self.eye_style == 'round': width,height = 61,61
            elif self.eye_style == 'sleepy': height = 40
            elif self.eye_style == 'pixel': width,height = 49,65
            if e == "surprised": width,height = 46,87
            elif e == "excited": width,height = 57,79
            elif e == "sleepy": height = 23
            elif e == "skeptical": height = 41 if idx == 0 else 63
            elif e == "worried": height = 59
            elif e == "thoughtful": height = 58
            elif e == "determined": height = 49
            elif e == "mischievous": height = 58 if idx == 0 else 68
            elif e in ("pleased","amused","proud"): height = 32
            height *= self.blink_amount
            rect = QRectF(cx-width/2,cy-height/2,width,height)
            # Soft bloom drawn in layers; no expensive blur effects.
            for extra,alpha in ((16,9),(9,20),(4,37)):
                glow = QColor(152,232,255,alpha)
                p.setBrush(glow)
                p.drawRoundedRect(rect.adjusted(-extra/2,-extra/2,extra/2,extra/2),
                                  min(width,height)/2+extra/2,min(width,height)/2+extra/2)
            p.setBrush(eye)
            if self.eye_style == 'pixel': p.drawRect(rect)
            else: p.drawRoundedRect(rect,min(width,height)/2,min(width,height)/2)
            if self.eye_style in ('pupils','round','sleepy','pixel') and height > 17:
                p.save()
                clip = QPainterPath()
                if self.eye_style == 'pixel': clip.addRect(rect)
                else: clip.addRoundedRect(rect,min(width,height)/2,min(width,height)/2)
                p.setClipPath(clip)
                p.setBrush(QColor('#344d6c'))
                px = cx + max(-11,min(11,self.gaze_x*.7))
                py = cy + max(-13,min(13,self.gaze_y*.65 - (8 if self.mood == 'thinking' else 0)))
                if self.eye_style == 'pixel': p.drawRect(QRectF(px-6,py-12,12,24))
                else: p.drawRoundedRect(QRectF(px-7,py-14,14,28),7,7)
                p.restore()
            if e == "surprised" and self.blink_amount > .5:
                p.setBrush(dark)
                p.drawEllipse(QRectF(cx-5,cy-10,10,20))
            elif e == "thoughtful" and self.blink_amount > .5:
                p.setBrush(QColor(34,41,67,130))
                p.drawRoundedRect(QRectF(cx-14,cy+7,28,9),4,4)
        # OG signature brow: a temporary acting cue, not permanent anatomy.
        # Left on SCREEN (eye center 105); dramatic emotions use both brows.
        p.setBrush(Qt.NoBrush)
        expressive = e in ('curious','skeptical','mischievous','thoughtful',
                           'surprised','worried','determined','inspired')
        thinking_cue = self.mood == 'thinking'
        # A brief arch during neutral idle looks like a spontaneous quirk.
        idle_cue = (self.mood == 'idle' and e == 'neutral'
                    and self.tick % 230 < 27)
        if self.eyebrow_style != 'none' and (expressive or thinking_cue or idle_cue):
            both = (self.eyebrow_style == 'both'
                    or e in ('surprised','worried','determined'))
            centers = (105,215) if both else (105,)
            p.setPen(QPen(eye,3.6,Qt.SolidLine,Qt.RoundCap))
            for bx in centers:
                arch = 7 if e in ('skeptical','curious','surprised') else 3
                wiggle = 2 * math.sin(self.tick*.14)
                brow = QPainterPath()
                brow.moveTo(bx-18,39)
                brow.quadTo(bx,23-arch+wiggle,bx+18,36)
                p.drawPath(brow)
        # Mouth family matches the same rounded, softly illuminated eye language.
        mouth_color = QColor(self.eye_color)
        p.setPen(QPen(mouth_color,4.5,Qt.SolidLine,Qt.RoundCap,Qt.RoundJoin))
        p.setBrush(Qt.NoBrush)
        cx,cy = (177.0,143.0) if self.mood == 'thinking' else (160.0,145.0)
        if self.mood == 'thinking':
            path = QPainterPath()
            path.moveTo(cx-12,cy+5)
            path.quadTo(cx+2,cy+8,cx+13,cy-8)
            p.drawPath(path)
            p.restore()
            p.end()
            return
        if self.mouth_style == 'lips':
            p.setBrush(mouth_color)
            opening = max(1.0, 13*self.audio_level) if self.mood == 'speaking' else 2.2
            lips = QPainterPath()
            lips.moveTo(cx-25,cy)
            lips.cubicTo(cx-13,cy-12,cx-5,cy-10,cx,cy-5)
            lips.cubicTo(cx+6,cy-10,cx+14,cy-12,cx+25,cy)
            lips.cubicTo(cx+14,cy+12+opening,cx-14,cy+12+opening,cx-25,cy)
            p.drawPath(lips)
            p.setPen(QPen(QColor('#33405d'),2))
            p.drawLine(QPointF(cx-18,cy+2),QPointF(cx+18,cy+2))
            p.restore()
            p.end()
            return
        path = QPainterPath()
        if self.mood == "speaking":
            opening = 2.5 + 19 * max(0.0, min(1.0, self.audio_level))
            p.setPen(Qt.NoPen); p.setBrush(mouth_color)
            p.drawRoundedRect(QRectF(cx-12,cy-opening/2,24,opening),min(10,opening/2),min(10,opening/2))
        elif e in ("excited","inspired","surprised"):
            p.setPen(Qt.NoPen); p.setBrush(mouth_color)
            radius = 10 if e == "surprised" else 13
            p.drawEllipse(QRectF(cx-radius,cy-radius*.65,radius*2,radius*1.3))
            if e != "surprised":
                p.setBrush(dark); p.drawEllipse(QRectF(cx-6,cy-3,12,9))
        elif self.mouth_style == 'pixel':
            p.setBrush(mouth_color); p.setPen(Qt.NoPen)
            p.drawRect(QRectF(cx-15,cy-2,30,9))
        elif self.mouth_style == 'cat':
            path.moveTo(cx-20,cy-5); path.quadTo(cx-10,cy+14,cx,cy)
            path.quadTo(cx+10,cy+14,cx+20,cy-5); p.drawPath(path)
        elif self.mouth_style == 'wry':
            path.moveTo(cx-10,cy+5); path.quadTo(cx+5,cy+11,cx+20,cy-8); p.drawPath(path)
        elif self.mouth_style == 'smile':
            path.moveTo(cx-20,cy-5); path.quadTo(cx,cy+24,cx+20,cy-5); p.drawPath(path)
        elif e in ("pleased","amused","proud","mischievous"):
            path.moveTo(cx-17,cy-5)
            path.cubicTo(cx-8,cy+12,cx+8,cy+12,cx+17,cy-5 if e!="mischievous" else cy-10)
            p.drawPath(path)
        elif e == "worried":
            path.moveTo(cx-12,cy+4)
            path.quadTo(cx,cy-9,cx+12,cy+4)
            p.drawPath(path)
        elif e == "flustered":
            p.drawLine(QPointF(cx-9,cy),QPointF(cx+9,cy+2))
        elif e == "skeptical":
            path.moveTo(cx-13,cy+2); path.quadTo(cx,cy-3,cx+13,cy+1); p.drawPath(path)
        elif e == "sleepy":
            p.drawLine(QPointF(cx-9,cy),QPointF(cx+9,cy))
        elif e == "determined":
            p.drawLine(QPointF(cx-13,cy+2),QPointF(cx+13,cy+2))
        elif e == "thoughtful":
            p.setPen(Qt.NoPen); p.setBrush(mouth_color)
            p.drawEllipse(QRectF(cx-4,cy-3,8,8))
        elif e == "curious":
            path.moveTo(cx-11,cy-2); path.quadTo(cx+1,cy+9,cx+12,cy-1); p.drawPath(path)
        else:
            path.moveTo(cx-10,cy); path.quadTo(cx,cy+4,cx+10,cy); p.drawPath(path)
        p.restore()
        p.end()
