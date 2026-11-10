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


class SettingsDialog(QDialog):
    """自定义设置弹窗: 键位 / 音域分配 / 播放整形 / 开始延迟 / 音域高亮
       确定后由主窗统一写回并 rebuild (一次重建应用全部改动)"""
    def __init__(self, mw):
        super().__init__(mw)
        self.setWindowTitle(t('自定义设置'))
        self.setMinimumWidth(540)
        self.mw = mw
        self.row_keys = dict(mw.row_keys)
        self.oct_assign = dict(mw.oct_assign)
        self.overlap_mode = mw.overlap_mode
        self.piano_mode = mw.piano_mode
        self.map_scope = mw.map_scope
        self.min_hold = int(round(mw.min_hold * 1000))
        self.min_gap = int(round(mw.min_gap * 1000))
        self.tap = int(round(mw.tap * 1000))
        self.start_delay = mw.start_delay
        self.range_hl_on = mw.range_hl_on
        self.range_lo = mw.range_lo; self.range_hi = mw.range_hi
        self.strip_font = int(getattr(mw, 'strip_font', 8))
        self.strip_name_font = int(getattr(mw, 'strip_name_font', 7))
        self.deck_font = int(getattr(mw, 'deck_font', 8))
        self.strip_page_bars = int(getattr(mw, 'strip_page_bars', 2))
        self.score_row_h = int(getattr(mw, 'score_row_h', 250))
        self.score_float_w = int(getattr(mw, 'score_float_w', 1020))
        self.strip_label = int(getattr(mw, 'strip_label', 0))
        self.strip_jianpu_base = int(getattr(mw, 'strip_jianpu_base', 4))
        self.cursor_size = getattr(mw, 'cursor_size', 'standard')
        self.select_cursor = getattr(mw, 'select_cursor', 'arrow')
        lay = QVBoxLayout(self)
        # ---- 键位 ----
        gk = QGroupBox(t('键位 (白键 7 = CDEFGAB · 黑键 0~5 = C#D#F#G#A#, 留空不映射)'))
        g = QGridLayout(gk); g.setContentsMargins(8, 4, 8, 4); g.setVerticalSpacing(3)
        g.addWidget(QLabel(t('排')), 0, 0)
        g.addWidget(QLabel(t('白键 (7 个)')), 0, 1)
        g.addWidget(QLabel(t('黑键 (0~5 个)')), 0, 2)
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
        lay.addWidget(gk)
        # ---- 音域分配 ----
        ga = QGroupBox(t('音域分配 (八度 → 排)'))
        og = QGridLayout(ga); og.setContentsMargins(8, 4, 8, 4)
        self._oct = {}
        for i, o in enumerate(OCT_RANGE):
            og.addWidget(QLabel(f'C{o}~B{o}'), i % 4, (i // 4) * 2)
            cb = QComboBox()
            cb.addItem(t('不映射'), NO_ASSIGN)
            for r in ROWS:
                cb.addItem(t(ROW_NAMES[r]), r)
            cb.setCurrentIndex(max(0, cb.findData(self.oct_assign[o])))
            self._oct[o] = cb
            og.addWidget(cb, i % 4, (i // 4) * 2 + 1)
        lay.addWidget(ga)
        # ---- 播放整形 / 开始延迟 ----
        gp = QGroupBox(t('播放'))
        pg = QGridLayout(gp); pg.setContentsMargins(8, 4, 8, 4)
        pg.addWidget(QLabel(t('重叠处理')), 0, 0)
        self.cmb_overlap = QComboBox()
        self.cmb_overlap.addItem(t('合并为长音'), 'merge')
        self.cmb_overlap.addItem(t('截断重敲'), 'truncate')
        self.cmb_overlap.setCurrentIndex(
            max(0, self.cmb_overlap.findData(self.overlap_mode)))
        pg.addWidget(self.cmb_overlap, 0, 1)
        pg.addWidget(QLabel(t('按键模式')), 0, 2)
        self.cmb_mode = QComboBox()
        self.cmb_mode.addItem(t('长按保持'), 'hold')
        self.cmb_mode.addItem(t('固定敲击'), 'tap')
        self.cmb_mode.setCurrentIndex(max(0, self.cmb_mode.findData(self.piano_mode)))
        pg.addWidget(self.cmb_mode, 0, 3)
        pg.addWidget(QLabel(t('最短按住')), 1, 0)
        self.sp_hold = QSpinBox(); self.sp_hold.setRange(10, 200)
        self.sp_hold.setValue(self.min_hold); self.sp_hold.setSuffix('ms')
        pg.addWidget(self.sp_hold, 1, 1)
        pg.addWidget(QLabel(t('同键间隔')), 1, 2)
        self.sp_gap = QSpinBox(); self.sp_gap.setRange(10, 200)
        self.sp_gap.setValue(self.min_gap); self.sp_gap.setSuffix('ms')
        pg.addWidget(self.sp_gap, 1, 3)
        pg.addWidget(QLabel(t('敲击时长')), 2, 0)
        self.sp_tap = QSpinBox(); self.sp_tap.setRange(20, 300)
        self.sp_tap.setValue(self.tap); self.sp_tap.setSuffix('ms')
        pg.addWidget(self.sp_tap, 2, 1)
        pg.addWidget(QLabel(t('开始延迟')), 2, 2)
        self.sp_delay = QSpinBox(); self.sp_delay.setRange(0, 10)
        self.sp_delay.setValue(self.start_delay); self.sp_delay.setSuffix('s')
        pg.addWidget(self.sp_delay, 2, 3)
        pg.addWidget(QLabel(t('映射范围')), 3, 0)
        self.cmb_scope = QComboBox()
        self.cmb_scope.addItem(t('合并所有音轨'), 'merge')
        self.cmb_scope.addItem(t('仅当前音轨'), 'active')
        self.cmb_scope.setCurrentIndex(max(0, self.cmb_scope.findData(self.map_scope)))
        self.cmb_scope.setToolTip(t('键盘映射/演奏只输出所选范围的音符'))
        pg.addWidget(self.cmb_scope, 3, 1)
        lay.addWidget(gp)
        # ---- 显示: 音域高亮 ----
        gd = QGroupBox(t('显示'))
        dg = QGridLayout(gd); dg.setContentsMargins(8, 4, 8, 4)
        self.chk_range = QCheckBox(t('音域高亮 (绿色边框)'))
        self.chk_range.setChecked(self.range_hl_on)
        dg.addWidget(self.chk_range, 0, 0)
        dg.addWidget(QLabel('C'), 0, 1)
        self.sp_rlo = QSpinBox(); self.sp_rlo.setRange(1, 8)
        self.sp_rlo.setValue(self.range_lo)
        dg.addWidget(self.sp_rlo, 0, 2)
        dg.addWidget(QLabel('~ B'), 0, 3)
        self.sp_rhi = QSpinBox(); self.sp_rhi.setRange(1, 8)
        self.sp_rhi.setValue(self.range_hi)
        dg.addWidget(self.sp_rhi, 0, 4)
        dg.addWidget(QLabel(t('演奏谱字符大小')), 1, 0)
        self.sp_sfont = QSpinBox(); self.sp_sfont.setRange(6, 24)
        self.sp_sfont.setValue(self.strip_font); self.sp_sfont.setSuffix('pt')
        self.sp_sfont.setToolTip(t('演奏谱视图音块字母的显示字号'))
        dg.addWidget(self.sp_sfont, 1, 1)
        dg.addWidget(QLabel(t('主窗轨道名字号')), 2, 0)
        self.sp_dfont = QSpinBox(); self.sp_dfont.setRange(6, 18)
        self.sp_dfont.setValue(self.deck_font); self.sp_dfont.setSuffix('pt')
        self.sp_dfont.setToolTip(t('主窗口音轨甲板轨道名称的显示字号'))
        dg.addWidget(self.sp_dfont, 2, 1)
        dg.addWidget(QLabel(t('演奏谱轨名字号')), 2, 2)
        self.sp_nfont = QSpinBox(); self.sp_nfont.setRange(5, 18)
        self.sp_nfont.setValue(self.strip_name_font); self.sp_nfont.setSuffix('pt')
        self.sp_nfont.setToolTip(t('演奏谱/悬浮窗车道轨名的显示字号 (独立于音符字母字号)'))
        dg.addWidget(self.sp_nfont, 2, 3)
        dg.addWidget(QLabel(t('演奏谱每页小节数')), 3, 0)
        self.sp_page = QSpinBox(); self.sp_page.setRange(1, 8)
        self.sp_page.setValue(self.strip_page_bars); self.sp_page.setSuffix('小节')
        self.sp_page.setToolTip(t('跟随模式: 演奏谱按此小节数整页翻页 (1|2→3|4→…)'))
        dg.addWidget(self.sp_page, 3, 1)
        dg.addWidget(QLabel(t('悬浮谱排高')), 3, 2)
        self.sp_rowh = QSpinBox(); self.sp_rowh.setRange(100, 500)
        self.sp_rowh.setValue(self.score_row_h); self.sp_rowh.setSuffix('px')
        self.sp_rowh.setToolTip(t('悬浮演奏谱每一排的高度; 排数在悬浮窗底部调节'))
        dg.addWidget(self.sp_rowh, 3, 3)
        dg.addWidget(QLabel(t('悬浮谱宽度')), 4, 0)
        self.sp_floatw = QSpinBox(); self.sp_floatw.setRange(600, 3840)
        self.sp_floatw.setValue(self.score_float_w); self.sp_floatw.setSuffix('px')
        self.sp_floatw.setToolTip(t('悬浮演奏谱窗口宽度; 配合每页小节数控制音符密度'))
        dg.addWidget(self.sp_floatw, 4, 1)
        dg.addWidget(QLabel(t('演奏谱字符')), 5, 0)
        self.cmb_slabel = QComboBox()
        self.cmb_slabel.addItem(t('键位字母'), 0)
        self.cmb_slabel.addItem(t('简谱'), 1)
        self.cmb_slabel.addItem(t('音名'), 2)
        self.cmb_slabel.setCurrentIndex(
            max(0, self.cmb_slabel.findData(self.strip_label)))
        self.cmb_slabel.setToolTip(t('演奏谱音块显示的字符风格'))
        dg.addWidget(self.cmb_slabel, 5, 1)
        dg.addWidget(QLabel(t('简谱基准八度')), 5, 2)
        self.sp_jbase = QSpinBox(); self.sp_jbase.setRange(1, 8)
        self.sp_jbase.setValue(self.strip_jianpu_base); self.sp_jbase.setPrefix('C')
        self.sp_jbase.setToolTip(t('简谱中音区基准: 该八度不加点, 高八度数字上加·, 低八度下加·'))
        dg.addWidget(self.sp_jbase, 5, 3)
        dg.addWidget(QLabel(t('编辑器指针大小')), 6, 0)
        self.cmb_csize = QComboBox()
        self.cmb_csize.addItem(t('标准'), 'standard')
        self.cmb_csize.addItem(t('大'), 'large')
        self.cmb_csize.setCurrentIndex(max(0, self.cmb_csize.findData(self.cursor_size)))
        self.cmb_csize.setToolTip(t('钢琴卷帘编辑器内的工具指针大小 (大 = 1.5 倍)'))
        dg.addWidget(self.cmb_csize, 6, 1)
        dg.addWidget(QLabel(t('选择工具指针')), 6, 2)
        self.cmb_csel = QComboBox()
        self.cmb_csel.addItem(t('箭头 + 角标'), 'arrow')
        self.cmb_csel.addItem(t('四角括号 + 中心落点'), 'bracket')
        self.cmb_csel.setCurrentIndex(max(0, self.cmb_csel.findData(self.select_cursor)))
        self.cmb_csel.setToolTip(t('选择工具 (E) 在空白处的指针样式; 悬停音符时显示移动/复制'))
        dg.addWidget(self.cmb_csel, 6, 3)
        dg.setColumnStretch(5, 1)
        lay.addWidget(gd)
        bot = QHBoxLayout()
        b_def = QPushButton(t('恢复默认')); b_def.clicked.connect(self._reset_keys)
        bot.addWidget(b_def)
        b_cancel = QPushButton(t('取消')); b_cancel.clicked.connect(self.reject)
        b_ok = QPushButton(t('确定')); b_ok.setDefault(True)
        b_ok.clicked.connect(self._accept)
        bot.addStretch(1); bot.addWidget(b_cancel); bot.addWidget(b_ok)
        lay.addLayout(bot)
    def _reset_keys(self):
        for r in ROWS:
            self._eds[r][0].setText(DEFAULT_ROW_KEYS[r])
            self._eds[r][1].setText(DEFAULT_ROW_KEYS_BLACK[r])
    def _accept(self):
        rk = {r: (self._eds[r][0].text().strip().upper(),
                  self._eds[r][1].text().strip().upper()) for r in ROWS}
        m = KeyMapper(rk, DEFAULT_OCT_ASSIGN)
        if m.err:
            QMessageBox.warning(self, t('键位无效'), m.err); return
        self.row_keys = rk
        self.oct_assign = {o: cb.currentData() for o, cb in self._oct.items()}
        self.overlap_mode = self.cmb_overlap.currentData()
        self.piano_mode = self.cmb_mode.currentData()
        self.map_scope = self.cmb_scope.currentData()
        self.min_hold = self.sp_hold.value() / 1000.0
        self.min_gap = self.sp_gap.value() / 1000.0
        self.tap = self.sp_tap.value() / 1000.0
        self.start_delay = self.sp_delay.value()
        self.range_hl_on = self.chk_range.isChecked()
        lo, hi = sorted((self.sp_rlo.value(), self.sp_rhi.value()))
        self.range_lo = lo; self.range_hi = hi
        self.strip_font = self.sp_sfont.value()
        self.strip_name_font = self.sp_nfont.value()
        self.deck_font = self.sp_dfont.value()
        self.strip_page_bars = self.sp_page.value()
        self.score_row_h = self.sp_rowh.value()
        self.score_float_w = self.sp_floatw.value()
        self.strip_label = self.cmb_slabel.currentData()
        self.strip_jianpu_base = self.sp_jbase.value()
        self.cursor_size = self.cmb_csize.currentData()
        self.select_cursor = self.cmb_csel.currentData()
        self.accept()
