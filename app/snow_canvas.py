# -*- coding: utf-8 -*-
"""主窗中央背景: reactbits Particles (QPainter, 无 OpenGL)。
   https://reactbits.dev/backgrounds/particles?moveParticlesOnHover=false

   默认参数对齐官网; moveParticlesOnHover=false。
   不使用 QOpenGLWidget (本机曾 access violation)。"""
from __future__ import annotations
import math
import random
import time
from PySide6.QtCore import Qt, QTimer, QSettings, QPointF
from PySide6.QtGui import QPainter, QColor, QRadialGradient, QBrush
from PySide6.QtWidgets import QWidget

# ---- 官网默认 / URL ----
PARTICLE_COUNT = 200
PARTICLE_SPREAD = 10.0
SPEED = 0.1
PARTICLE_COLORS = ['#ffffff', '#ffffff', '#ffffff']
MOVE_ON_HOVER = False
ALPHA_PARTICLES = False
BASE_SIZE = 100.0
SIZE_RANDOMNESS = 1.0
CAMERA_DISTANCE = 20.0
DISABLE_ROTATION = False

_FPS = 30
_FOV_DEG = 15.0


def _hex_rgb(hex_s: str):
    h = hex_s.lstrip('#')
    if len(h) == 3:
        h = ''.join(c * 2 for c in h)
    n = int(h[:6], 16)
    return ((n >> 16) & 255) / 255.0, ((n >> 8) & 255) / 255.0, (n & 255) / 255.0


def _rot_xyz(x, y, z, rx, ry, rz):
    # Z → Y → X
    cz, sz = math.cos(rz), math.sin(rz)
    x, y = x * cz - y * sz, x * sz + y * cz
    cy, sy = math.cos(ry), math.sin(ry)
    x, z = x * cy + z * sy, -x * sy + z * cy
    cx, sx = math.cos(rx), math.sin(rx)
    y, z = y * cx - z * sx, y * sx + z * cx
    return x, y, z


class SnowCanvas(QWidget):
    """Particles 背景 (类名保留兼容 mainwindow)。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        st = QSettings('MidiKeymap', 'PianoRollPlayer')
        self._static = str(st.value('ui/snow_static', 'false')).lower() == 'true'
        self.setMinimumHeight(120)
        self.setAttribute(Qt.WA_OpaquePaintEvent, True)
        self.setAutoFillBackground(True)
        pal = self.palette()
        pal.setColor(self.backgroundRole(), QColor(0, 0, 0))
        self.setPalette(pal)

        self._t0 = time.monotonic()
        self._elapsed_ms = 0.0
        self._last = self._t0
        self._rot_z = 0.0
        self._particles = self._spawn()

        self._timer = QTimer(self)
        self._timer.setInterval(max(1, int(1000 / _FPS)))
        self._timer.timeout.connect(self._tick)

    def _spawn(self):
        rnd = random.Random(42)
        palette = [_hex_rgb(c) for c in PARTICLE_COLORS]
        out = []
        for _ in range(PARTICLE_COUNT):
            while True:
                x = rnd.random() * 2 - 1
                y = rnd.random() * 2 - 1
                z = rnd.random() * 2 - 1
                ln = x * x + y * y + z * z
                if 0 < ln <= 1:
                    break
            r = rnd.random() ** (1.0 / 3.0)
            rx, ry, rz, rw = rnd.random(), rnd.random(), rnd.random(), rnd.random()
            col = palette[rnd.randrange(len(palette))]
            out.append({
                'p': (x * r, y * r, z * r),
                'r': (rx, ry, rz, rw),
                'c': col,
            })
        return out

    def _on_hover(self, x, y):
        pass

    def _on_leave(self):
        pass

    def showEvent(self, e):
        self._last = time.monotonic()
        if not self._static:
            self._timer.start()
        super().showEvent(e)

    def hideEvent(self, e):
        self._timer.stop()
        super().hideEvent(e)

    def _tick(self):
        now = time.monotonic()
        delta_ms = (now - self._last) * 1000.0
        self._last = now
        self._elapsed_ms += delta_ms * SPEED
        if not DISABLE_ROTATION:
            self._rot_z += 0.01 * SPEED
        self.update()

    def paintEvent(self, _e):
        w = max(1, self.width())
        h = max(1, self.height())
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.fillRect(0, 0, w, h, QColor(0, 0, 0))

        t = 0.0 if self._static else (self._elapsed_ms * 0.001)
        elapsed = self._elapsed_ms
        rx = 0.0 if DISABLE_ROTATION else math.sin(elapsed * 0.0002) * 0.1
        ry = 0.0 if DISABLE_ROTATION else math.cos(elapsed * 0.0005) * 0.15
        rz = 0.0 if DISABLE_ROTATION else self._rot_z

        fov = math.radians(_FOV_DEG)
        focal = 1.0 / math.tan(fov * 0.5)
        aspect = w / float(h)
        # 投影到屏幕的尺度
        scale_y = h * 0.5
        scale_x = scale_y  # 再用 aspect 校正 x

        # 按深度远→近画, 近处盖住远处
        draws = []
        for part in self._particles:
            px, py, pz = part['p']
            rnd = part['r']
            # position * spread; z *= 10
            px *= PARTICLE_SPREAD
            py *= PARTICLE_SPREAD
            pz *= PARTICLE_SPREAD * 10.0

            px, py, pz = _rot_xyz(px, py, pz, rx, ry, rz)

            # 漂浮 (对齐 vertex shader)
            px += math.sin(t * rnd[2] + 6.28 * rnd[3]) * (0.1 + 1.4 * rnd[0])
            py += math.sin(t * rnd[1] + 6.28 * rnd[0]) * (0.1 + 1.4 * rnd[3])
            pz += math.sin(t * rnd[3] + 6.28 * rnd[1]) * (0.1 + 1.4 * rnd[2])

            # view: camera at (0,0,CAMERA_DISTANCE) → 平移 -camera
            mx, my, mz = px, py, pz - CAMERA_DISTANCE
            if mz >= -0.05:
                continue
            dist = math.sqrt(mx * mx + my * my + mz * mz) + 1e-6

            # NDC-ish perspective
            ndc_x = (mx / -mz) * focal / aspect
            ndc_y = (my / -mz) * focal
            sx = (ndc_x * 0.5 + 0.5) * w
            sy = (1.0 - (ndc_y * 0.5 + 0.5)) * h

            if SIZE_RANDOMNESS == 0.0:
                psz = BASE_SIZE
            else:
                psz = (BASE_SIZE * (1.0 + SIZE_RANDOMNESS * (rnd[0] - 0.5))) / dist
            # 映射到像素半径 (官网 baseSize 偏大, 缩放到可读范围)
            radius = max(0.8, min(18.0, psz * 0.09))

            cr, cg, cb = part['c']
            # + 0.2 * sin(uv.yxx + uTime + vRandom.y * 6.28) — 用时间近似闪色
            pulse = 0.2 * math.sin(t + rnd[1] * 6.28)
            cr = min(1.0, max(0.0, cr + pulse))
            cg = min(1.0, max(0.0, cg + pulse * 0.85))
            cb = min(1.0, max(0.0, cb + pulse * 0.7))
            draws.append((mz, sx, sy, radius, cr, cg, cb))

        draws.sort(key=lambda d: d[0])  # 远→近 (mz 更负更远)
        for _mz, sx, sy, radius, cr, cg, cb in draws:
            if sx < -20 or sy < -20 or sx > w + 20 or sy > h + 20:
                continue
            if ALPHA_PARTICLES:
                g = QRadialGradient(sx, sy, radius)
                col = QColor(int(cr * 255), int(cg * 255), int(cb * 255), 200)
                g.setColorAt(0.0, col)
                g.setColorAt(0.8, QColor(int(cr * 255), int(cg * 255), int(cb * 255), 40))
                g.setColorAt(1.0, QColor(0, 0, 0, 0))
                p.setPen(Qt.NoPen)
                p.setBrush(QBrush(g))
                p.drawEllipse(QPointF(sx, sy), radius, radius)
            else:
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(int(cr * 255), int(cg * 255), int(cb * 255)))
                p.drawEllipse(QPointF(sx, sy), radius, radius)
        p.end()
