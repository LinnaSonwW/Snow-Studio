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


class OctaveMapDialog(QDialog):
    """音域分配: 八度 -> 排/不映射 (键位编辑见"自定义键位"对话框)"""
    def __init__(self, parent, oct_assign):
        super().__init__(parent)
        self.setWindowTitle(t("音域分配"))
        self.setMinimumWidth(430)
        self.oct_assign = {o: oct_assign.get(o, NO_ASSIGN) for o in OCT_RANGE}
        lay = QVBoxLayout(self)
        box2 = QGroupBox(t("八度分配（多个八度可共用一排；不映射 = 该八度不演奏）"))
        og = QGridLayout(box2); og.setContentsMargins(8, 4, 8, 4)
        og.addWidget(QLabel(t("八度")), 0, 0); og.addWidget(QLabel(t("分配到")), 0, 1)
        self.cmb_oct = {}
        for i, o in enumerate(OCT_RANGE):
            og.addWidget(QLabel(f"C{o}~B{o}"), i + 1, 0)
            cb = QComboBox()
            cb.addItem(t("不映射"), NO_ASSIGN)
            for r in ROWS:
                cb.addItem(t(ROW_NAMES[r]), r)
            cb.setCurrentIndex(max(0, cb.findData(self.oct_assign[o])))
            self.cmb_oct[o] = cb
            og.addWidget(cb, i + 1, 1)
        og.setColumnStretch(2, 1)
        lay.addWidget(box2)
        bot = QHBoxLayout()
        b_def = QPushButton(t("恢复默认")); b_def.clicked.connect(self._reset_default)
        bot.addWidget(b_def); bot.addStretch(1)
        b_cancel = QPushButton(t("取消")); b_cancel.clicked.connect(self.reject)
        b_ok = QPushButton(t("确定")); b_ok.setDefault(True); b_ok.clicked.connect(self.accept)
        bot.addWidget(b_cancel); bot.addWidget(b_ok)
        lay.addLayout(bot)
    def _reset_default(self):
        for o in OCT_RANGE:
            cb = self.cmb_oct[o]
            cb.setCurrentIndex(max(0, cb.findData(DEFAULT_OCT_ASSIGN[o])))
    def values(self):
        return {o: self.cmb_oct[o].currentData() for o in OCT_RANGE}
