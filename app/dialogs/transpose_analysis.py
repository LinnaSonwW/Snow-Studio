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


class TransposeAnalysisDialog(QDialog):
    """请选择偏移量: -12~+12 每档统计(按音符事件计数)
       传入 row_keys 时用真实键位判定可演奏 (黑键须实际映射才计入, 与 KeyMapper 一致);
       未传时按旧口径近似 (八度已分配即视为可演奏)"""
    def __init__(self, parent, raw_notes, oct_assign, current=0, row_keys=None):
        super().__init__(parent)
        self.setWindowTitle(t("请选择偏移量"))
        self.resize(440, 580)
        self.chosen = None
        self.current = current
        self.oct_assign = {o: oct_assign.get(o, NO_ASSIGN) for o in OCT_RANGE}
        # ---- 统计: 每档 偏移 -> (黑键, 未分配·超域, 可演奏) ----
        mapper = KeyMapper(row_keys, self.oct_assign) if row_keys else None
        self.stats = {}
        for tshift in range(-12, 13):
            bl = bad = ok = 0
            for nt in raw_notes:
                n = nt.note + tshift
                if mapper is not None:
                    # 真实键位: 黑键数=信息列(移调后落在黑键上即计);
                    # 可演奏 = covers (黑键须实际映射); 其余不可奏计入"未分配·超域"
                    if NOTE_MIN <= n <= NOTE_MAX and n % 12 in BLACK_SET:
                        bl += 1
                    if mapper.covers(n): ok += 1
                    else: bad += 1
                elif not (NOTE_MIN <= n <= NOTE_MAX):
                    bad += 1
                elif n % 12 in BLACK_SET:
                    bl += 1
                    if self.oct_assign.get(n // 12 - 1, NO_ASSIGN) != NO_ASSIGN:
                        ok += 1
                elif self.oct_assign.get(n // 12 - 1, NO_ASSIGN) == NO_ASSIGN:
                    bad += 1
                else:
                    ok += 1
            self.stats[tshift] = (bl, bad, ok)
        # 推荐: 可演奏最多, 同分取 |偏移| 小(更接近原调)
        self.best = max(self.stats, key=lambda tshift: (self.stats[tshift][2],
                                                        -abs(tshift)))
        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(t('共 {n} 个音符事件 · 统计基于当前音域分配'
                               '（点表头排序, 双击行 = 选择并确定）', n=len(raw_notes))))
        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            [t("偏移"), t("黑键数"), t("未分配·超域"), t("可演奏"), t("备注")])
        self.table.verticalHeader().setVisible(False)
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setAlternatingRowColors(True)
        hh = self.table.horizontalHeader()
        hh.setSectionsClickable(True)
        hh.sectionClicked.connect(self._on_header)
        lay.addWidget(self.table, 1)
        self._sort_col, self._sort_desc = None, False
        self._fill()
        self.table.cellDoubleClicked.connect(self._dbl)
        bot = QHBoxLayout(); bot.addStretch(1)
        b_cancel = QPushButton(t("取消")); b_cancel.clicked.connect(self.reject)
        b_ok = QPushButton(t("确定")); b_ok.setDefault(True); b_ok.clicked.connect(self._ok)
        bot.addWidget(b_cancel); bot.addWidget(b_ok)
        lay.addLayout(bot)
    def _fill(self):
        ts = list(self.stats)
        if self._sort_col is None:
            ts.sort(key=lambda x: (abs(x), x))            # 默认 |偏移| 升序
        else:
            c = self._sort_col
            if c == 1:   kf = lambda x: self.stats[x][0]
            elif c == 2: kf = lambda x: self.stats[x][1]
            elif c == 3: kf = lambda x: self.stats[x][2]
            elif c == 4: kf = lambda x: (x == self.best, -abs(x))
            else:        kf = lambda x: x
            ts.sort(key=kf, reverse=self._sort_desc)
        self.table.setRowCount(0)
        for tshift in ts:
            bl, bad, ok = self.stats[tshift]
            remark = (t('★ 推荐') if tshift == self.best
                      else (t('当前') if tshift == self.current else ""))
            r = self.table.rowCount(); self.table.insertRow(r)
            for c, txt in enumerate((f"{tshift:+d}", str(bl), str(bad), str(ok), remark)):
                it = QTableWidgetItem(txt)
                if c in (0, 4): it.setTextAlignment(Qt.AlignCenter)
                else:           it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                if tshift == self.best: it.setForeground(QColor('#e8b05a'))
                self.table.setItem(r, c, it)
        self.table.resizeColumnsToContents()
        for r in range(self.table.rowCount()):            # 预选当前移调行
            if int(self.table.item(r, 0).text()) == self.current:
                self.table.selectRow(r); break
    def _on_header(self, col):
        if self._sort_col == col: self._sort_desc = not self._sort_desc
        else:                     self._sort_col = col; self._sort_desc = False
        self._fill()
    def _dbl(self, row, _col):
        self.chosen = int(self.table.item(row, 0).text())
        self.accept()
    def _ok(self):
        sel = self.table.selectedItems()
        if not sel:
            QMessageBox.information(self, t("提示"), t("请先选择一个偏移量")); return
        self.chosen = int(self.table.item(sel[0].row(), 0).text())
        self.accept()
