# -*- coding: utf-8 -*-
"""对话框:
   OctaveMapDialog         音域分配(三排键串 + C1~B7 每个八度 -> 排/不映射)
   TransposeAnalysisDialog 移调分析与选择(-12~+12 黑键/未分配·超域/可演奏统计)
   SettingsDialog          自定义设置(键位/音域分配/播放整形/开始延迟/音域高亮)
   NoteSettingsDialog      音符字母显示 (O 轮新增, 主窗卷帘与编辑器同步生效)
   AppSettingsDialog       输出设备 + 语言 (O 轮新增)
   TrackSoundDialog        轨道独立音源 SF2+音色 (O 轮新增)"""
import os
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
                    NOTE_SOLFA, NOTE_JIANPU)
from i18n import t
from keymap import KeyMapper
from sound import SoundEngine, enumerate_audio_devices


class NoteSettingsDialog(QDialog):
    """音符字母设置弹窗 (O 轮): 音符上显示的文字 = 默认音符字母
       模式: 音名+八度 / 纯音名 / 唱名 / 简谱 / 键位(输出按键) / 自定义 12 音 / 隐藏
       确定后由主窗写回并同步到主窗卷帘与编辑器卷帘"""
    _MODES = (('name', '音名+八度 (C4)'), ('letter', '纯音名 (C)'),
              ('solfa', '唱名 (do re mi)'), ('jianpu', '简谱 (1 2 3)'),
              ('key', '键位 (显示输出按键)'), ('custom', '自定义 (12 音)'),
              ('none', '不显示'))
    _HINTS = {'name': '音名+八度: 现状默认, 如 C4 / C#4',
              'letter': '纯音名: 只显示音级, 如 C / C#',
              'solfa': '唱名: 固定唱名+八度, 黑键带升号, 如 do[4] / ♯do[5]',
              'jianpu': '简谱: 以 C 调记谱+八度, 黑键带升号, 如 1[4] / ♯4[5]',
              'key': '键位: 已映射显示按键字母, 未映射显示音名; 黑键加♯, 如 A[4] / ♯C[5]',
              'custom': '自定义: 按音级 (C..B) 逐格填写显示字符',
              'none': '不显示: 音符上不画任何文字'}
    def __init__(self, mw):
        super().__init__(mw)
        self.setWindowTitle(t('音符字母'))
        self.setMinimumWidth(520)
        self.mw = mw
        self.mode = mw.note_label_mode
        self.custom = dict(mw.note_label_custom)
        lay = QVBoxLayout(self)
        box = QGroupBox(t('音符字母'))
        g = QGridLayout(box); g.setContentsMargins(8, 4, 8, 4)
        g.addWidget(QLabel(t('显示模式')), 0, 0)
        self.cmb_mode = QComboBox()
        for code, lbl in self._MODES:
            self.cmb_mode.addItem(t(lbl), code)
        self.cmb_mode.setCurrentIndex(max(0, self.cmb_mode.findData(self.mode)))
        self.cmb_mode.currentIndexChanged.connect(self._mode_changed)
        g.addWidget(self.cmb_mode, 0, 1)
        self.lb_hint = QLabel()
        self.lb_hint.setStyleSheet('color:#999;')
        g.addWidget(self.lb_hint, 1, 0, 1, 2)
        # 自定义 12 音级输入行
        self.lb_custom = QLabel(t('自定义 12 音级 (每格最多 2 字符, 留空 = 该音级不显示)'))
        g.addWidget(self.lb_custom, 2, 0, 1, 2)
        row = QHBoxLayout(); row.setSpacing(3)
        self._eds = {}
        for pc in range(12):
            col = QVBoxLayout(); col.setSpacing(1)
            cap = QLabel(NOTE_NAMES[pc]); cap.setAlignment(Qt.AlignCenter)
            cap.setStyleSheet('color:#888; font-size:9px;')
            ed = QLineEdit(self.custom.get(pc, '')); ed.setMaxLength(2)
            ed.setFixedWidth(34); ed.setAlignment(Qt.AlignCenter)
            ed.setPlaceholderText(t('空 = 不显示'))
            self._eds[pc] = ed
            col.addWidget(cap); col.addWidget(ed)
            row.addLayout(col)
        g.addLayout(row, 3, 0, 1, 2)
        self.lb_preview = QLabel()
        self.lb_preview.setStyleSheet('color:#e8b05a;')
        g.addWidget(self.lb_preview, 4, 0, 1, 2)
        lay.addWidget(box)
        bot = QHBoxLayout()
        b_cancel = QPushButton(t('取消')); b_cancel.clicked.connect(self.reject)
        b_ok = QPushButton(t('确定')); b_ok.setDefault(True)
        b_ok.clicked.connect(self._accept)
        bot.addStretch(1); bot.addWidget(b_cancel); bot.addWidget(b_ok)
        lay.addLayout(bot)
        self._mode_changed()
    def _mode_changed(self, *_i):
        m = self.cmb_mode.currentData()
        custom_on = m == 'custom'
        self.lb_custom.setVisible(custom_on)
        for ed in self._eds.values(): ed.setVisible(custom_on)
        self.lb_hint.setText(t(self._HINTS.get(m, '')))
        self._update_preview()
    def _label_of(self, note):
        """预览用: 与 view_roll.PianoRoll._note_label 同规则的本地实现
           (Q 轮) 唱名/简谱/键位 带八度; 键位黑键加♯, 未映射回退音名"""
        m = self.cmb_mode.currentData(); pc = note % 12
        oct_s = '[%d]' % (note // 12 - 1)
        if m == 'name': return f"{NOTE_NAMES[pc]}{note // 12 - 1}"
        if m == 'letter': return NOTE_NAMES[pc]
        if m == 'solfa': return NOTE_SOLFA[pc] + oct_s
        if m == 'jianpu': return NOTE_JIANPU[pc] + oct_s
        if m == 'key':
            mapper = self.mw.mapper
            body = (mapper.note_char.get(note)
                    if mapper is not None and not mapper.err else None)
            if body is None:
                body = NOTE_NAMES[pc].replace('#', '')   # ♯ 前缀已表达升号
            return ('♯' + body + oct_s) if pc in BLACK_SET else (body + oct_s)
        if m == 'custom':
            return self._eds[pc].text().strip() or '·'
        return '·'
    def _update_preview(self):
        self.lb_preview.setText(t('预览: {s}',
                                  s='  '.join(f"{n}->{self._label_of(n)}" for n in
                                              (60, 62, 64, 67, 61, 72))))
    def _accept(self):
        self.mode = self.cmb_mode.currentData()
        self.custom = {pc: ed.text().strip()[:2] for pc, ed in self._eds.items()}
        self.accept()
