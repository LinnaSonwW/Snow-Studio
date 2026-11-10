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


class KeymapDialog(QDialog):
    """自定义键位: 每排 白键7(CDEFGAB) + 黑键0~5(C#D#F#G#A#, 留空 = 不映射)"""
    def __init__(self, parent, row_keys):
        super().__init__(parent)
        self.setWindowTitle(t("自定义键位"))
        self.setMinimumWidth(480)
        self.row_keys = {r: row_keys.get(r, (DEFAULT_ROW_KEYS[r], '')) for r in ROWS}
        lay = QVBoxLayout(self)
        box = QGroupBox(t("每排键位（白键 7 个依次对应 C D E F G A B；"
                          "黑键 0~5 个依次对应 C# D# F# G# A#）"))
        g = QGridLayout(box); g.setContentsMargins(8, 4, 8, 4); g.setVerticalSpacing(3)
        g.addWidget(QLabel(t("排")), 0, 0)
        g.addWidget(QLabel(t("白键 (7 个)")), 0, 1)
        g.addWidget(QLabel(t("黑键 (0~5 个, 留空 = 不映射)")), 0, 2)
        self._eds = {}
        for r in ROWS:
            wk, bk = self.row_keys[r]
            g.addWidget(QLabel(t(ROW_NAMES[r])), r + 1, 0)
            ed_w = QLineEdit(wk); ed_w.setMaxLength(7)
            ed_w.setFixedWidth(110); ed_w.setAlignment(Qt.AlignCenter)
            ed_b = QLineEdit(bk); ed_b.setMaxLength(5)
            ed_b.setFixedWidth(90); ed_b.setAlignment(Qt.AlignCenter)
            ed_b.setPlaceholderText(t('未映射'))
            g.addWidget(ed_w, r + 1, 1); g.addWidget(ed_b, r + 1, 2)
            self._eds[r] = (ed_w, ed_b)
        lay.addWidget(box)
        b_def = QPushButton(t("恢复默认")); b_def.clicked.connect(self._reset_default)
        lay.addWidget(b_def)
        bot = QHBoxLayout()
        b_cancel = QPushButton(t("取消")); b_cancel.clicked.connect(self.reject)
        b_ok = QPushButton(t("确定")); b_ok.setDefault(True); b_ok.clicked.connect(self._accept)
        bot.addStretch(1); bot.addWidget(b_cancel); bot.addWidget(b_ok)
        lay.addLayout(bot)
    def _reset_default(self):
        for r in ROWS:
            ed_w, ed_b = self._eds[r]
            ed_w.setText(DEFAULT_ROW_KEYS[r])
            ed_b.setText(DEFAULT_ROW_KEYS_BLACK[r])
    def _accept(self):
        rk = {r: (self._eds[r][0].text().strip().upper(),
                  self._eds[r][1].text().strip().upper()) for r in ROWS}
        m = KeyMapper(rk, DEFAULT_OCT_ASSIGN)      # 仅校验键位本身
        if m.err:
            QMessageBox.warning(self, t("键位无效"), m.err); return
        self.row_keys = rk
        self.accept()
    def values(self):
        return dict(self.row_keys)
