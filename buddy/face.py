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
        self.update_percent = None
        self.celebrating = False
        self.celebrate_ticks = 0
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

    def express(self, expression, duration=7.0):
        self.expression = expression if expression in self.EXPRESSIONS else "neutral"
        self.expression_until = time.monotonic() + duration if duration else float("inf")
        self.update()

    def animate(self):
        now = time.monotonic()
        self.tick += 1
        if now >= self.expression_until and self.expression != "neutral":
            self.expression = "neutral"
        if now >= self.next_blink:
            self.blink_until = now + 0.18
            self.next_blink = now + random.uniform(2.2, 6.0)
        self.blink_amount = max(0.055, abs(now - (self.blink_until - .09)) / .09) if now < self.blink_until else 1.0
        if now >= self.next_gaze:
            self.target_x = random.choice((-8, -4, 0, 0, 4, 8))
            self.target_y = random.choice((-3, 0, 0, 3))
            self.next_gaze = now + random.uniform(1.2, 3.4)
        self.gaze_x += (self.target_x - self.gaze_x) * .085
        self.gaze_y += (self.target_y - self.gaze_y) * .085
        # Idle motion is subtle: Day Zero Buddy is curious, not assigned a random personality.
        if self.mood == "idle" and now >= self.next_idle and self.expression == "neutral":
            self.express("curious", random.uniform(1.0, 2.0))
            self.next_idle = now + random.uniform(9, 16)
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
        border = QColor(status_colors.get(self.mood, border_colors.get(e, '#55cfe7')))
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
        p.save()
        p.translate(160,93)
        if e == "curious": p.rotate(3.2)
        elif e == "skeptical": p.rotate(-3.0)
        elif e == "flustered": p.rotate(1.8*math.sin(t*2))
        p.translate(-160,-93)
        eye = QColor("#a8ecff")
        dark = QColor("#222943")
        eyes = ((105,83),(215,83))
        for idx,(cx,cy) in enumerate(eyes):
            cx += self.gaze_x
            cy += self.gaze_y
            width,height = 51.0,76.0
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
            p.drawRoundedRect(rect,min(width,height)/2,min(width,height)/2)
            if e == "surprised" and self.blink_amount > .5:
                p.setBrush(dark)
                p.drawEllipse(QRectF(cx-5,cy-10,10,20))
            elif e == "thoughtful" and self.blink_amount > .5:
                p.setBrush(QColor(34,41,67,130))
                p.drawRoundedRect(QRectF(cx-14,cy+7,28,9),4,4)
        # Eyebrows and lids are expressed with small shape changes.
        p.setBrush(Qt.NoBrush)
        if e in ("worried","determined","skeptical","mischievous"):
            p.setPen(QPen(eye,3.6,Qt.SolidLine,Qt.RoundCap))
            for i,cx in enumerate((105,215)):
                if e == "worried":
                    a,b = ((cx-16,35),(cx+15,42)) if i == 0 else ((cx-15,42),(cx+16,35))
                elif e == "determined":
                    a,b = ((cx-16,37),(cx+16,45)) if i == 0 else ((cx-16,45),(cx+16,37))
                elif e == "skeptical":
                    a,b = ((cx-16,35),(cx+16,33)) if i == 0 else ((cx-16,39),(cx+16,34))
                else:
                    a,b = ((cx-16,40),(cx+16,34)) if i == 0 else ((cx-16,34),(cx+16,40))
                p.drawLine(QPointF(*a),QPointF(*b))
        # Mouth family matches the same rounded, softly illuminated eye language.
        mouth_color = QColor("#a8ecff")
        p.setPen(QPen(mouth_color,4.5,Qt.SolidLine,Qt.RoundCap,Qt.RoundJoin))
        p.setBrush(Qt.NoBrush)
        cx,cy = 160.0,145.0
        path = QPainterPath()
        if self.mood == "speaking":
            opening = 5 + 10*max(.15,min(1.0,self.audio_level or (.45+.35*math.sin(t*8)**2)))
            p.setPen(Qt.NoPen); p.setBrush(mouth_color)
            p.drawRoundedRect(QRectF(cx-12,cy-opening/2,24,opening),min(10,opening/2),min(10,opening/2))
        elif e in ("excited","inspired","surprised"):
            p.setPen(Qt.NoPen); p.setBrush(mouth_color)
            radius = 10 if e == "surprised" else 13
            p.drawEllipse(QRectF(cx-radius,cy-radius*.65,radius*2,radius*1.3))
            if e != "surprised":
                p.setBrush(dark); p.drawEllipse(QRectF(cx-6,cy-3,12,9))
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
