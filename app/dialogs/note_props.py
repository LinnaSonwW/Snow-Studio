# -*- coding: utf-8 -*-
"""对话框:
   OctaveMapDialog         音域分配(三排键串 + C1~B7 每个八度 -> 排/不映射)
   TransposeAnalysisDialog 移调分析与选择(-12~+12 黑键/未分配·超域/可演奏统计)
   SettingsDialog          自定义设置(键位/音域分配/播放整形/开始延迟/音域高亮)
   NoteSettingsDialog      音符字母显示 (O 轮新增, 主窗卷帘与编辑器同步生效)
   AppSettingsDialog       输出设备 + 语言 (O 轮新增)
   TrackSoundDialog        轨道独立音源 SF2+音色 (O 轮新增)"""
import os
import re
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QCheckBox,
                               QGroupBox, QLabel, QLineEdit, QComboBox,
                               QPushButton, QMessageBox, QSpinBox,
                               QTableWidget,
                               QTableWidgetItem, QAbstractItemView, QFileDialog)
from common import (OCT_RANGE, ROWS, ROW_NAMES, DEFAULT_ROW_KEYS,
                    DEFAULT_ROW_KEYS_BLACK, DEFAULT_OCT_ASSIGN, NO_ASSIGN,
                    NOTE_MIN, NOTE_MAX, BLACK_SET, NOTE_NAMES,
                    NOTE_SOLFA, NOTE_JIANPU, note_name)
from i18n import t
from keymap import KeyMapper
from sound import SoundEngine, enumerate_audio_devices


class NotePropsDialog(QDialog):
    """双击音符属性: 音高/力度/起点/时值 精确输入 (Q 轮)"""
    def __init__(self, parent, nt, total_tick):
        super().__init__(parent)
        self.setWindowTitle(t('音符属性'))
        self.setMinimumWidth(360)
        g = QGridLayout(self)
        g.addWidget(QLabel(t('音高')), 0, 0)
        self.sp_note = QSpinBox(); self.sp_note.setRange(0, 127)
        self.sp_note.setValue(nt.note)
        g.addWidget(self.sp_note, 0, 1)
        g.addWidget(QLabel(t('力度')), 1, 0)
        self.sp_vel = QSpinBox(); self.sp_vel.setRange(1, 127)
        self.sp_vel.setValue(nt.vel)
        g.addWidget(self.sp_vel, 1, 1)
        g.addWidget(QLabel(t('起点')), 2, 0)
        self.sp_start = QSpinBox(); self.sp_start.setRange(0, int(total_tick))
        self.sp_start.setValue(int(nt.start_tick))
        g.addWidget(self.sp_start, 2, 1)
        g.addWidget(QLabel(t('时值')), 3, 0)
        self.sp_dur = QSpinBox(); self.sp_dur.setRange(1, int(total_tick) + 1)
        self.sp_dur.setValue(int(nt.end_tick - nt.start_tick))
        g.addWidget(self.sp_dur, 3, 1)
        bb = QHBoxLayout()
        ok = QPushButton(t('确定')); cancel = QPushButton(t('取消'))
        ok.setDefault(True)
        bb.addStretch(1); bb.addWidget(cancel); bb.addWidget(ok)
        g.addLayout(bb, 4, 0, 1, 2)
        cancel.clicked.connect(self.reject); ok.clicked.connect(self.accept)
    def values(self):
        """→ (音高, 力度, 起点, 终点); 起点/时值钳制合法范围"""
        start = max(0, self.sp_start.value())
        dur = max(1, self.sp_dur.value())
        return (self.sp_note.value(), self.sp_vel.value(), start, start + dur)


class NotePropsMultiDialog(QDialog):
    """框选批量音符属性: 音高/力度/起点/时值 = 输入框 (留空 = 不改; 填值 = 全部
       设为该值, 起点设为即全部叠到同一起点); 琶音 = 平铺 设为/清除 两按钮
       (都不按 = 不改; 设为 = 每次分配新的空闲组号, 分次设置互不合并)"""
    KEEP, SET, CLEAR = 0, 1, 2
    ARP_NEW = 0                        # arp (SET, ARP_NEW) → 模型分配空闲组号
    KEYS = ('note', 'vel', 'start', 'dur')
    def __init__(self, parent, nt, total_tick, count, notes=None):
        super().__init__(parent)
        self.setWindowTitle(t('音符属性 · 选中 {n} 个 · 参考音 {r}',
                              n=count, r=note_name(nt.note)))
        self.setMinimumWidth(380)
        self._tt = int(total_tick)
        src = list(notes) if notes else [nt]
        vals = {'note': [n.note for n in src], 'vel': [n.vel for n in src],
                'start': [int(n.start_tick) for n in src],
                'dur': [int(n.end_tick - n.start_tick) for n in src]}
        labels = {'note': t('音高'), 'vel': t('力度'),
                  'start': t('起点'), 'dur': t('时值')}
        units = {'note': t('音名或 MIDI 号'), 'vel': '1 ~ 127',
                 'start': 'tick', 'dur': 'tick'}
        g = QGridLayout(self)
        self._edits = {}
        for r, key in enumerate(self.KEYS):
            g.addWidget(QLabel(labels[key]), r, 0)
            ed = QLineEdit()
            ed.setClearButtonEnabled(True)
            ed.setPlaceholderText(self._summary(key, vals[key]))
            ed.textChanged.connect(lambda _s, e=ed, k=key: self._mark(e, k))
            g.addWidget(ed, r, 1)
            g.addWidget(QLabel(units[key]), r, 2)
            self._edits[key] = ed
        g.addWidget(QLabel(t('琶音')), 4, 0)
        box = QHBoxLayout()
        self.bt_arp_set = QPushButton(t('设为琶音'))
        self.bt_arp_clr = QPushButton(t('清除琶音'))
        for b, other in ((self.bt_arp_set, self.bt_arp_clr),
                         (self.bt_arp_clr, self.bt_arp_set)):
            b.setCheckable(True)
            b.setAutoDefault(False)
            b.toggled.connect(lambda on, o=other: on and o.setChecked(False))
            box.addWidget(b)
        box.addStretch(1)
        g.addLayout(box, 4, 1, 1, 2)
        bb = QHBoxLayout()
        ok = QPushButton(t('确定')); cancel = QPushButton(t('取消'))
        ok.setDefault(True)
        bb.addStretch(1); bb.addWidget(cancel); bb.addWidget(ok)
        g.addLayout(bb, 5, 0, 1, 3)
        cancel.clicked.connect(self.reject); ok.clicked.connect(self._try_accept)

    @staticmethod
    def _summary(key, vs):
        """占位提示 = 选区当前值 (全同 → 该值; 否则 最小 ~ 最大)"""
        fmt = note_name if key == 'note' else str
        lo, hi = min(vs), max(vs)
        return fmt(lo) if lo == hi else '%s ~ %s' % (fmt(lo), fmt(hi))

    def _parse(self, key, s):
        """→ 合法设为值 / None (空 = 不改) / ValueError (非法输入)"""
        s = s.strip()
        if not s:
            return None
        if key == 'note':
            v = _parse_note(s)
            lo, hi = NOTE_MIN, NOTE_MAX
        else:
            v = int(s)
            lo, hi = {'vel': (1, 127), 'start': (0, self._tt),
                      'dur': (1, self._tt + 1)}[key]
        if not lo <= v <= hi:
            raise ValueError(s)
        return v

    def _mark(self, ed, key):
        """填了值的行高亮 (将生效); 非法输入红框"""
        try:
            v = self._parse(key, ed.text())
            ed.setStyleSheet('' if v is None else 'border: 1px solid #4f9cf9;')
        except ValueError:
            ed.setStyleSheet('border: 1px solid #e05050;')

    def _try_accept(self):
        for key, ed in self._edits.items():
            try:
                self._parse(key, ed.text())
            except ValueError:
                ed.setFocus(); ed.selectAll()
                return
        self.accept()

    def ops(self):
        """→ {'note'/'vel'/'start'/'dur': (mode, v), 'arp': (mode, v)};
           mode 0=不改 / 1=设为; arp: 1=设为(新组号, v=ARP_NEW) / 2=清除"""
        out = {}
        for key, ed in self._edits.items():
            try:
                v = self._parse(key, ed.text())
            except ValueError:
                v = None
            out[key] = (self.KEEP, 0) if v is None else (self.SET, v)
        if self.bt_arp_set.isChecked():
            out['arp'] = (self.SET, self.ARP_NEW)
        elif self.bt_arp_clr.isChecked():
            out['arp'] = (self.CLEAR, 0)
        else:
            out['arp'] = (self.KEEP, 0)
        return out


def _parse_note(s):
    """音名 (C4 / C#4 / Db4, 大小写不敏感) 或 MIDI 号 → MIDI 音高"""
    if s.lstrip('-').isdigit():
        return int(s)
    u = s[0].upper() + s[1:]
    flats = {'Db': 'C#', 'Eb': 'D#', 'Gb': 'F#', 'Ab': 'G#', 'Bb': 'A#'}
    name = u[:2] if len(u) > 1 and u[1] in '#b' else u[:1]
    octv = u[len(name):]
    name = flats.get(name, name)
    if name not in NOTE_NAMES or not octv.lstrip('-').isdigit():
        raise ValueError(s)
    return NOTE_NAMES.index(name) + (int(octv) + 1) * 12
