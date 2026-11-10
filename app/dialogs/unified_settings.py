# -*- coding: utf-8 -*-
"""统一设置枢纽: 键位整形 + 音符字母 + 输出语言 三页签合并。"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QTabWidget,
                               QPushButton, QScrollArea, QMessageBox)
from i18n import t
from common import DEFAULT_OCT_ASSIGN, ROWS
from keymap import KeyMapper
from dialogs.settings_dialog import SettingsDialog
from dialogs.note_settings import NoteSettingsDialog
from dialogs.app_settings import AppSettingsDialog


def _strip_bot(dlg):
    """去掉对话框底栏确定/取消, 作为页签内容嵌入。"""
    dlg.setWindowFlags(Qt.Widget)
    lay = dlg.layout()
    if lay is None or lay.count() < 1:
        return
    last = lay.itemAt(lay.count() - 1)
    if last is None or last.layout() is None:
        return
    row = last.layout()
    while row.count():
        it = row.takeAt(0)
        w = it.widget()
        if w is not None:
            w.hide(); w.deleteLater()
    lay.removeItem(last)


class UnifiedSettingsDialog(QDialog):
    """设置 = 自定义设置 + 音符设置 + 应用设置"""
    def __init__(self, mw, parent=None):
        super().__init__(parent or mw)
        self.mw = mw
        self.setWindowTitle(t('设置'))
        self.setMinimumWidth(580)
        self.setMinimumHeight(520)
        self.page_keys = SettingsDialog(mw); _strip_bot(self.page_keys)
        self.page_note = NoteSettingsDialog(mw); _strip_bot(self.page_note)
        self.page_app = AppSettingsDialog(mw); _strip_bot(self.page_app)
        tabs = QTabWidget()
        tabs.addTab(self._wrap(self.page_keys), t('键位 / 播放'))
        tabs.addTab(self._wrap(self.page_note), t('音符字母'))
        tabs.addTab(self._wrap(self.page_app), t('输出 / 语言'))
        lay = QVBoxLayout(self)
        lay.addWidget(tabs, 1)
        bot = QHBoxLayout()
        b_cancel = QPushButton(t('取消')); b_cancel.clicked.connect(self.reject)
        b_ok = QPushButton(t('确定')); b_ok.setDefault(True)
        b_ok.clicked.connect(self._ok)
        bot.addStretch(1); bot.addWidget(b_cancel); bot.addWidget(b_ok)
        lay.addLayout(bot)

    @staticmethod
    def _wrap(inner):
        sc = QScrollArea(); sc.setWidgetResizable(True)
        sc.setFrameShape(QScrollArea.NoFrame)
        sc.setWidget(inner)
        return sc

    def _ok(self):
        pk = self.page_keys
        rk = {r: (pk._eds[r][0].text().strip().upper(),
                  pk._eds[r][1].text().strip().upper()) for r in ROWS}
        m = KeyMapper(rk, DEFAULT_OCT_ASSIGN)
        if m.err:
            QMessageBox.warning(self, t('键位无效'), m.err); return
        pk.row_keys = rk
        pk.oct_assign = {o: cb.currentData() for o, cb in pk._oct.items()}
        pk.overlap_mode = pk.cmb_overlap.currentData()
        pk.piano_mode = pk.cmb_mode.currentData()
        pk.map_scope = pk.cmb_scope.currentData()
        pk.min_hold = pk.sp_hold.value() / 1000.0
        pk.min_gap = pk.sp_gap.value() / 1000.0
        pk.tap = pk.sp_tap.value() / 1000.0
        pk.start_delay = pk.sp_delay.value()
        pk.range_hl_on = pk.chk_range.isChecked()
        lo, hi = sorted((pk.sp_rlo.value(), pk.sp_rhi.value()))
        pk.range_lo, pk.range_hi = lo, hi
        pk.strip_font = pk.sp_sfont.value()
        pk.strip_name_font = pk.sp_nfont.value()
        pk.deck_font = pk.sp_dfont.value()
        pk.strip_page_bars = pk.sp_page.value()
        pk.score_row_h = pk.sp_rowh.value()
        pk.score_float_w = pk.sp_floatw.value()
        pk.strip_label = pk.cmb_slabel.currentData()
        pk.strip_jianpu_base = pk.sp_jbase.value()
        pk.cursor_size = pk.cmb_csize.currentData()
        pk.select_cursor = pk.cmb_csel.currentData()

        pn = self.page_note
        pn.mode = pn.cmb_mode.currentData()
        pn.custom = {pc: ed.text().strip()[:2] for pc, ed in pn._eds.items()}

        pa = self.page_app
        drv = pa.cmb_driver.currentData()
        dev = pa.cmb_device.currentData() or ''
        if ((drv, dev) != (self.mw.audio_driver, self.mw.audio_device)
                and self.mw._is_playing()):
            QMessageBox.warning(self, t('提示'),
                                t('切换设备需重建音源; 播放中不可切换'))
            return
        pa.driver, pa.device = drv, dev
        pa.lang = pa.cmb_lang.currentData()
        pa.transcribe_route = pa.cmb_route.currentData() or ''
        self.accept()
