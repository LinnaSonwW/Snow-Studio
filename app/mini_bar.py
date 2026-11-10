# -*- coding: utf-8 -*-
"""悬浮迷你播放条 (FL Studio 风格): 总在最前 / 无边框 / 不占任务栏 (Qt.Tool)
   标题 + 时间 + 可拖动进度条 + 播放暂停/停止。
   只读主窗口状态 (mw.cur_sec / mw.total_sec / mw.thread),
   定位复用主窗口 scrub 流程 (_scrub_begin/_seek_visual/_scrub_end);
   由 mainwindow._poll_ui 每 40ms 调 sync() 保持同步。"""
import os
from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (QWidget, QLabel, QPushButton, QHBoxLayout,
                               QVBoxLayout)
from common import fmt_sec
from i18n import t as tr        # 别名 tr: sync() 里 t 是播放线程
from window_chrome import hover_pulse
import settings_store as store

ACCENT, TRACK, HANDLE, HANDLE_EDGE = '#e8b05a', '#2a2a33', '#ffe2a8', '#8a6a30'
QSS = ("#MiniBar { background:#17171c; border:1px solid #3a3a44; }"
       "QPushButton { background:#26262e; border:1px solid #3a3a44;"
       " border-radius:3px; color:#d6d6de; font-size:13px; }"
       "QPushButton:hover { background:#33333d; }"
       "QPushButton:pressed { background:#3d3d4a; }")
class MiniBar(QWidget):
    def __init__(self, mw):
        super().__init__(None, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
                         | Qt.Tool)
        self.mw = mw
        self.setWindowTitle(tr("悬浮播放条"))
        self.setFixedSize(300, 74)
        self.setObjectName('MiniBar'); self.setStyleSheet(QSS)
        self._drag_off = None                   # 无边框窗口拖动偏移
        self._scrubbing = False                 # 进度条拖动中 (sync 冻结 fraction)
        # ---- 第一行: 标题 + 时间 + 关闭 ----
        self.lb_title = QLabel(tr("未加载 MIDI"))
        self.lb_title.setFont(QFont('Segoe UI', 9))
        self.lb_title.setStyleSheet("color:#d6d6de; border:none; background:transparent;")
        self.lb_time = QLabel("0:00.0 / 0:00.0")
        self.lb_time.setFont(QFont('Segoe UI', 8))
        self.lb_time.setStyleSheet("color:#8d8d9c; border:none; background:transparent;")
        b_x = QPushButton("✕"); b_x.setFixedSize(18, 18)
        b_x.setStyleSheet("font-size:9px; color:#9a6570;")
        b_x.clicked.connect(self.hide)          # hideEvent 负责存几何+通知主窗
        top = QHBoxLayout(); top.setSpacing(4)
        top.addWidget(self.lb_title); top.addStretch(1)
        top.addWidget(self.lb_time); top.addWidget(b_x)
        # ---- 第二行: 进度条 ----
        self.seek = _MiniSeek(self)
        # ---- 第三行: 播放/暂停 + 停止 ----
        self.b_play = QPushButton("▶"); self.b_play.setFixedSize(46, 24)
        self.b_play.clicked.connect(self.mw.toggle_play)
        self.b_stop = QPushButton("⏹"); self.b_stop.setFixedSize(46, 24)
        self.b_stop.clicked.connect(self.mw.stop_all)
        hover_pulse(self.b_play); hover_pulse(self.b_stop)   # (交互轮) 悬停脉冲
        bot = QHBoxLayout(); bot.setSpacing(6)
        bot.addWidget(self.b_play); bot.addWidget(self.b_stop); bot.addStretch(1)
        lay = QVBoxLayout(self); lay.setContentsMargins(8, 6, 8, 6); lay.setSpacing(4)
        lay.addLayout(top); lay.addWidget(self.seek); lay.addLayout(bot)
    # ---- 状态同步 (主窗口 _poll_ui 每 40ms 调用) ----
    def sync(self):
        mw = self.mw
        self.lb_time.setText(f"{fmt_sec(mw.cur_sec)} / {fmt_sec(mw.total_sec)}")
        name = os.path.basename(mw._midi_path) if mw._midi_path else tr('未加载 MIDI')
        fm = self.lb_title.fontMetrics()
        self.lb_title.setText(fm.elidedText(name, Qt.ElideRight, 160))
        th = mw.thread
        playing = th is not None and th.isRunning() and not th.paused
        self.b_play.setText("⏸" if playing else "▶")
        if not self._scrubbing:
            self.seek.set_fraction(mw.cur_sec / mw.total_sec if mw.total_sec > 0 else 0.0)
    def retranslate(self):
        """(O 轮) 语言切换后刷新窗口标题 (标题行文字由 sync 每 40ms 刷新)"""
        self.setWindowTitle(tr("悬浮播放条"))
    # ---- 无边框窗口拖动 (标题行/空白处按住即可移动) ----
    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            self._drag_off = (ev.globalPosition().toPoint()
                              - self.frameGeometry().topLeft())
    def mouseMoveEvent(self, ev):
        if self._drag_off is not None and ev.buttons() & Qt.LeftButton:
            self.move(ev.globalPosition().toPoint() - self._drag_off)
    def mouseReleaseEvent(self, ev):
        self._drag_off = None
    def hideEvent(self, ev):
        store.save_mini_geometry(self.saveGeometry())
        self.mw._mini_hidden()
        super().hideEvent(ev)
class _MiniSeek(QWidget):
    """迷你进度条: 按下/拖动 = 定位 (暂停→拖动→恢复, 与主卷帘擦洗同一套流程)"""
    def __init__(self, bar):
        super().__init__(bar)
        self.bar = bar; self.frac = 0.0
        self.setCursor(Qt.PointingHandCursor)
    def set_fraction(self, f):
        f = min(max(f, 0.0), 1.0)
        if f != self.frac:
            self.frac = f; self.update()
    def _sec_at(self, x):
        mw = self.bar.mw
        return min(max(x / max(1.0, self.width()), 0.0), 1.0) * mw.total_sec
    def mousePressEvent(self, ev):
        mw = self.bar.mw
        if mw.total_sec <= 0: return
        self.bar._scrubbing = True; mw._scrub_begin()
        self.set_fraction(ev.position().x() / max(1.0, self.width()))
        mw._seek_visual(self._sec_at(ev.position().x()))
    def mouseMoveEvent(self, ev):
        if self.bar._scrubbing and self.bar.mw.total_sec > 0:
            self.set_fraction(ev.position().x() / max(1.0, self.width()))
            self.bar.mw._seek_visual(self._sec_at(ev.position().x()))
    def mouseReleaseEvent(self, ev):
        if self.bar._scrubbing:
            self.bar._scrubbing = False
            self.bar.mw._scrub_end(self._sec_at(ev.position().x()))
    def paintEvent(self, ev):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        y = (h - 6) / 2
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(TRACK))
        p.drawRoundedRect(QRectF(0, y, w, 6), 3.0, 3.0)
        fx = w * self.frac
        if fx >= 3.0:
            p.setBrush(QColor(ACCENT))
            p.drawRoundedRect(QRectF(0, y, fx, 6), 3.0, 3.0)
        p.setPen(QPen(QColor(HANDLE_EDGE), 1)); p.setBrush(QColor(HANDLE))
        p.drawEllipse(QRectF(fx - 4.5, h / 2 - 4.5, 9, 9))
