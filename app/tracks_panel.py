# -*- coding: utf-8 -*-
"""音轨甲板 (FL 机架风格, Q 轮交互改版):
   TrackDeck   主窗音轨面板: 每轨 2/8 分 = 静音色块+名称按钮(20%) + 该轨概览条(80%)
               底部 + 按钮 新增空音轨
   TrackStrip  单轨概览条: 该轨音符按整曲时间轴缩略 + 播放头竖线
               点击/拖动 = 定位播放头; 滑轮 = 播放头快进/快退
   静音色块    带轨色小方块, 点击切换该轨静音 (静音=空白方块), 独立于主窗静音按钮
   名称按钮    深色带阴影按钮, 单击=设为当前轨, 双击=弹窗(导入音源/重命名)
   TrackButton 编辑器当前轨选择下拉 (文字)
   行为经 mw 回调驱动主窗状态 (新增 UI 纯文字)"""
from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import (QColor, QFont, QPainter, QPen, QBrush,
                           QRadialGradient)
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                               QPushButton, QScrollArea, QSizePolicy,
                               QGraphicsDropShadowEffect, QMenu, QCheckBox)
from common import TRACK_COLORS
from i18n import t as tr

ROW_H = 28               # 行高 (概览条)
def track_hex(tid):
    return TRACK_COLORS[tid % len(TRACK_COLORS)]
class _MuteDiamond(QPushButton):
    """静音菱形 (设计规范): 旋转 45° 圆角方块, **常绿** (不随静音变色);
       状态反馈 = 光晕: 发声中 → 一圈淡化的绿光; 静音 → 光晕熄灭 (暗绿)。"""
    def __init__(self, deck, tid, muted):
        super().__init__()
        self.deck = deck; self.tid = tid
        self.setCheckable(True); self.setChecked(muted)
        self.setFixedSize(22, 22)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(tr('该轨静音/取消静音 (独立于主窗静音)'))
    def paintEvent(self, _ev):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        cx, cy = self.width() / 2, self.height() / 2
        r = 7.0                                     # 菱形半对角
        muted = self.isChecked()
        # 淡化绿光: 发声中亮、静音熄 (光晕即状态反馈)
        glow = QRadialGradient(cx, cy, r + 5.5)
        glow.setColorAt(0.0, QColor(120, 220, 150, 18 if muted else 70))
        glow.setColorAt(1.0, QColor(120, 220, 150, 0))
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(glow))
        p.drawEllipse(QPointF(cx, cy), r + 5.5, r + 5.5)
        # 菱形本体: 旋转 45° 的圆角方块 (绿填充 + 深描边)
        p.save()
        p.translate(cx, cy); p.rotate(45.0)
        p.setPen(QPen(QColor('#22261f'), 1))
        p.setBrush(QColor('#3f8f57') if muted else QColor('#5fd07a'))
        p.drawRoundedRect(QRectF(-r, -r, r * 2, r * 2), 3.0, 3.0)
        p.restore()
class _NameButton(QPushButton):
    """轨道名称按钮: 单击=设为当前轨, 双击=音源/重命名弹窗"""
    def __init__(self, text, deck, tid):
        super().__init__(text)
        self.deck = deck; self.tid = tid
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setCursor(Qt.PointingHandCursor)
        eff = QGraphicsDropShadowEffect(self)
        eff.setBlurRadius(8); eff.setOffset(0, 2)
        eff.setColor(QColor(0, 0, 0, 170))
        self.setGraphicsEffect(eff)
        self.setToolTip(tr('单击 设为当前轨 · 双击 音源/重命名'))
    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            self.deck.mw._on_track_activate(self.tid)
        super().mousePressEvent(ev)
    def mouseDoubleClickEvent(self, ev):
        self.deck.mw._on_track_sound(self.tid)
class _DeckRow(QWidget):
    """甲板单行容器: 单击空白处 = 设为当前轨; 右键 = 音源/重命名 · 删除音轨"""
    def __init__(self, deck, tid, active=False):
        super().__init__()
        self.deck = deck; self.tid = tid
        self.strip = None
        self._active = active
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet('background:transparent;')

    def set_active(self, active: bool):
        self._active = bool(active)
        self.update()

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        r = QRectF(0.5, 0.5, w - 1, h - 1)
        if self._active:
            p.setPen(QPen(QColor(232, 176, 90, 150), 1.0))
        else:
            p.setPen(QPen(QColor(230, 234, 240, 40), 0.5))
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(r, 3, 3)
        p.end()

    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            self.deck.mw._on_track_activate(self.tid)
        super().mousePressEvent(ev)
    def contextMenuEvent(self, ev):
        m = QMenu(self)
        m.setStyleSheet(
            'QMenu { background:#1b1b21; color:#d6d6de; border:1px solid #3a3a44; }'
            'QMenu::item { padding:4px 18px; }'
            'QMenu::item:selected { background:#33333d; }')
        a_snd = m.addAction(tr('音源 / 重命名…'))
        m.addSeparator()
        a_del = m.addAction(tr('删除音轨'))
        act = m.exec(ev.globalPos())
        if act == a_snd: self.deck.mw._on_track_sound(self.tid)
        elif act == a_del: self.deck.mw._track_remove(self.tid)
class TrackStrip(QWidget):
    """单轨概览条: 该轨音符按整曲时间轴缩略 + 播放头竖线 + 定位(单击/拖动)"""
    def __init__(self, deck, tid):
        super().__init__()
        self.deck = deck; self.tid = tid
        self.notes = []            # [(start_tick, end_tick, note)] 快照 (deck.refresh)
        self.total = 1.0           # 整曲 tick 跨度 (缩放基准)
        self.frac = None           # 播放头位置 0..1 (None = 不画)
        self._press_x = None
        self.setMinimumHeight(ROW_H - 6)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setToolTip(tr('单击/拖动 定位播放头 · 双击 设置该轨音源'))
    def _sec_at(self, x):
        tick = min(max(x / max(1.0, self.width()), 0.0), 1.0) * self.total
        tmap = self.deck.mw.tmap
        return tmap.tick2sec(tick) if tmap else 0.0
    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton and self.total > 1:
            self._press_x = ev.position().x()
            self.deck.mw._scrub_begin()
            self.deck.mw._seek_visual(self._sec_at(self._press_x))
    def mouseMoveEvent(self, ev):
        if self._press_x is not None:
            self.deck.mw._seek_visual(self._sec_at(ev.position().x()))
    def mouseReleaseEvent(self, ev):
        if self._press_x is not None:
            self._press_x = None
            self.deck.mw._scrub_end(self._sec_at(ev.position().x()))
    def mouseDoubleClickEvent(self, ev):
        self.deck.mw._on_track_sound(self.tid)
    def paintEvent(self, ev):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        p.fillRect(0, 0, w, h, QColor('#101014'))
        if self.notes:
            lo = min(n for _s, _e, n in self.notes)
            hi = max(n for _s, _e, n in self.notes)
            span = max(12.0, float(hi - lo + 1))
            nh = max(2.0, (h - 6.0) / span * 0.9)
            col = QColor(track_hex(self.tid))
            total = max(1.0, self.total)
            for s, e, n in self.notes:
                x = s / total * w
                nw = min(max(1.5, e / total * w - x), max(1.5, w - x))
                ny = 2.0 + (hi - n) / span * (h - 6.0)
                p.fillRect(QRectF(x, ny, nw, nh), col)
        if self.frac is not None:
            x = self.frac * w
            p.setPen(QPen(QColor('#ff3b30'), 1))
            p.drawLine(QPointF(x, 0), QPointF(x, h))
class TrackDeck(QWidget):
    """音轨甲板面板 (主版本结构 + 透明蒙版): scroll(轨道行) + 底部 brow("+"按钮)"""
    def __init__(self, mw):
        super().__init__()
        self.mw = mw
        self.total_tick = 1.0
        self._rows = []            # [(row, strip, tid)]
        self.setStyleSheet(
            # (透明轮) 蒙版: 与主版本同结构, 仅背景换 transparent 融入 SNOW 背景
            'QWidget { background:transparent; color:#d6d6de; }'
            'QPushButton { background:transparent; color:#c8cfd8;'
            ' border:none; border-radius:3px; font-size:10px; }'
            'QPushButton:hover { background:rgba(255, 255, 255, 14); }'
            'QScrollArea { border:none; background:transparent; }'
            'QLabel { background:transparent; }')
        self._inner = QWidget()
        self._col = QVBoxLayout(self._inner)
        self._col.setContentsMargins(3, 3, 3, 3); self._col.setSpacing(2)
        self._hint = QLabel(tr('导入 MIDI 后在此显示音轨')); self._hint.hide()
        self._hint.setStyleSheet('color:#666678;')
        scroll = QScrollArea(); scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setWidget(self._inner)
        v = QVBoxLayout(self); v.setContentsMargins(0, 0, 0, 0); v.setSpacing(2)
        v.addWidget(scroll, 1)
        brow = QHBoxLayout(); brow.setContentsMargins(0, 0, 0, 2)
        brow.addStretch(1)
        from main_chrome import AddTrackBtn
        b_add = AddTrackBtn()
        b_add.tip_text = tr('新增空音轨 (在编辑器中选中该轨绘制音符)')
        b_add.shortcut_text = ''
        b_add.clicked.connect(lambda: mw._track_add())
        brow.addWidget(b_add); brow.addStretch(1)
        v.addLayout(brow)
    def _ensure_hint(self):
        """空轨提示标签 (常驻复用): 若 C++ 对象已被销毁则重建 (防悬空引用崩溃)"""
        from shiboken6 import isValid
        if self._hint is None or not isValid(self._hint):
            self._hint = QLabel(tr('导入 MIDI 后在此显示音轨')); self._hint.hide()
            self._hint.setStyleSheet('color:#666678;')
        return self._hint
    def reload(self, tracks, active_tid, fonts, total_tick):
        """按主窗轨道状态重建行 (导入/静音/改名/当前轨/音源变化后调用)"""
        self.total_tick = max(1.0, total_tick)
        while self._col.count():
            it = self._col.takeAt(0)
            w = it.widget()
            if w is not None and w is not self._hint:
                w.hide(); w.deleteLater()     # 行部件重建; _hint 常驻复用不销毁
        self._rows = []
        if not tracks:
            hint = self._ensure_hint()
            hint.show(); self._col.addWidget(hint)
        for t in tracks:
            row = self._make_row(t, t.tid == active_tid, t.tid in fonts)
            self._col.addWidget(row)
            self._rows.append((row, row.strip, t.tid))
        self._col.addStretch(1)
        self.refresh()

    def _make_row(self, t, active, has_font):
        """行 = [静音菱形 + 名称按钮] 20% + 概览条 80% (2/8 分)。
           (透明轮) 行背景透明融入 SNOW 背景; 当前轨仅琥珀细边框标识"""
        row = _DeckRow(self, t.tid, active=active)
        h = QHBoxLayout(row); h.setContentsMargins(4, 2, 4, 2); h.setSpacing(6)
        # 静音菱形: 常绿方块 (光晕=状态反馈); 上下居中
        chip = _MuteDiamond(self, t.tid, t.muted)
        chip.setToolTip(tr('该轨静音/取消静音 (独立于主窗静音)'))
        chip.clicked.connect(lambda _=False, tt=t.tid: self.mw._on_track_toggle(tt, 'mute'))
        # 名称按钮: 深色统一色 + 阴影; 单击=当前轨, 双击=音源/重命名
        badge = '[鼓] ' if t.is_drum else ''
        name = _NameButton(badge + (t.name or tr('轨道 {n}', n=t.tid + 1)),
                           self, t.tid)
        name.setFont(QFont('Segoe UI', 9))
        # (UI轮) 轨名字号自定义: 甲板 QSS 的 font-size 优先级高于 setFont,
        # 须经本行级 QSS 覆盖 (默认 8pt ≈ 旧行观感)
        name.setStyleSheet('font-size:%dpt;' % int(getattr(self.mw, 'deck_font', 8)))
        strip = TrackStrip(self, t.tid)
        if has_font:
            strip.setStyleSheet('border:1px solid #e8b05a;')   # 已设独立音源标记
        row.strip = strip
        head = QWidget(); head.setAttribute(Qt.WA_StyledBackground, True)
        head.setStyleSheet('QWidget { background:transparent; border:none; }')
        hh = QHBoxLayout(head); hh.setContentsMargins(0, 0, 0, 0); hh.setSpacing(6)
        hh.addWidget(chip, 0, Qt.AlignVCenter)   # (设计轮) 菱形上下居中
        hh.addWidget(name, 1)
        h.addWidget(head, 1)               # 20%: 静音块 + 名称按钮
        h.addWidget(strip, 4)              # 80%: 概览条
        return row
    def refresh(self):
        """编辑提交后刷新条内容 (行结构不变): 一次遍历 raw_notes 分轨快照"""
        lists = {}
        for nt in self.mw.raw_notes:
            lists.setdefault(nt.tid, []).append((nt.start_tick, nt.end_tick, nt.note))
        self.total_tick = max((e for lst in lists.values() for _s, e, _n in lst),
                              default=1920.0)
        for _row, strip, tid in self._rows:
            strip.notes = lists.get(tid, [])
            strip.total = self.total_tick
            strip.update()
    def set_playhead(self, tick, total=None):
        """播放头同步 (主窗 _update_playhead 每 40ms 调用)"""
        total = max(1.0, total if total is not None else self.total_tick)
        frac = min(max(tick / total, 0.0), 1.0)
        for _row, strip, _tid in self._rows:
            strip.frac = frac; strip.update()
class TrackButton(QPushButton):
    """编辑器当前轨选择按钮 (文字下拉): 显示当前轨, 单击弹出音轨列表,
       滑轮 上/下 = 切换上一条/下一条音轨 (循环)"""
    def __init__(self, mw):
        super().__init__(tr('轨道 ▾'))
        self.mw = mw
        self._tracks = []
        self._popup = None
        self.setFixedHeight(22)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(tr('选择当前轨 (新音符归属此轨) · 滑轮切换 · 尾部勾选显示音符'))
        self.setStyleSheet(
            'QPushButton { text-align:center; padding:1px 10px; color:#d6d6de;'
            ' background:#222228; border:1px solid #3a3a44; border-radius:3px; }'
            'QPushButton:hover { background:#33333d; }')
        self.clicked.connect(self._open_popup)
    def wheelEvent(self, ev):
        """(Q 轮) 滑轮 上=上一条音轨, 下=下一条音轨 (循环)"""
        if len(self._tracks) < 2:
            ev.ignore(); return
        cur = next((i for i, t in enumerate(self._tracks)
                    if t.tid == self.mw.active_tid), 0)
        step = -1 if ev.angleDelta().y() > 0 else 1     # 上=上一条, 下=下一条
        t = self._tracks[(cur + step) % len(self._tracks)]
        self.mw._on_track_activate(t.tid)               # reload 由 _sync_track_ui 完成
    def reload(self, tracks, active_tid):
        """同步按钮显示为当前轨 (轨道色文字, 鼓轨带 [鼓] 徽标)"""
        self._tracks = tracks
        t = next((x for x in tracks if x.tid == active_tid), None)
        if t is None:
            self.setText(tr('轨道 ▾')); return
        nm = ('[鼓] ' if t.is_drum else '') + (t.name or tr('轨道 {n}', n=t.tid + 1))
        self.setText(f'{nm} ▾')
        self.setStyleSheet(
            'QPushButton { text-align:center; padding:1px 10px;'
            f' color:{track_hex(t.tid)}; background:#222228;'
            ' border:1px solid #3a3a44; border-radius:3px; }'
            'QPushButton:hover { background:#33333d; }')
    def _open_popup(self):
        if not self._tracks: return
        pop = QWidget(self, Qt.Popup)              # 点外部自动收起
        pop.setStyleSheet(
            'QWidget { background:#1b1b21; }'
            'QPushButton { background:#26262e; color:#d6d6de;'
            ' border:1px solid #3a3a44; border-radius:3px; text-align:left;'
            ' padding:1px 8px; }'
            'QPushButton:hover { background:#33333d; }'
            'QCheckBox { color:#d6d6de; spacing:0; }'
            'QCheckBox::indicator { width:14px; height:14px;'
            ' border:1px solid #5a5a66; border-radius:2px; background:#1a1a20; }'
            'QCheckBox::indicator:checked { background:#4f9cf9;'
            ' border:1px solid #6ab0ff; }')
        v = QVBoxLayout(pop); v.setContentsMargins(6, 6, 6, 6); v.setSpacing(2)
        head = QLabel(tr('选择当前轨 (新音符归属此轨)'))
        head.setFont(QFont('Segoe UI', 8))
        v.addWidget(head)
        roll = getattr(self.mw, 'edit_roll', None)
        hidden = set(getattr(roll, 'hidden_tids', ())) if roll is not None else set()
        for t in self._tracks:
            active = t.tid == self.mw.active_tid
            row = QWidget(pop)
            hl = QHBoxLayout(row)
            hl.setContentsMargins(0, 0, 0, 0)
            hl.setSpacing(4)
            b = QPushButton(('✓ ' if active else '')
                            + ('[鼓] ' if t.is_drum else '')
                            + (t.name or tr('轨道 {n}', n=t.tid + 1)))
            b.setFont(QFont('Segoe UI', 9)); b.setFixedHeight(22)
            b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            b.clicked.connect(lambda _=False, tt=t.tid:
                              (self.mw._on_track_activate(tt), pop.close()))
            cb = QCheckBox()
            cb.setFixedSize(18, 18)
            cb.setChecked(t.tid not in hidden)
            cb.setToolTip(tr('显示该轨音符'))
            cb.setFocusPolicy(Qt.NoFocus)
            cb.clicked.connect(lambda checked, tt=t.tid: self._toggle_show(tt, checked))
            hl.addWidget(b, 1)
            hl.addWidget(cb, 0, Qt.AlignVCenter)
            v.addWidget(row)
        pop.adjustSize()
        pop.move(self.mapToGlobal(self.rect().bottomLeft()))
        pop.show()
        self._popup = pop

    def _toggle_show(self, tid, checked):
        """尾部勾选: 控制卷帘是否绘制该轨音符 (不关闭弹层)。"""
        roll = getattr(self.mw, 'edit_roll', None)
        if roll is None:
            return
        roll.set_track_notes_visible(tid, bool(checked))
