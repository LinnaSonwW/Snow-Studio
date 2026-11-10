# -*- coding: utf-8 -*-
"""转录引擎分支选择弹窗 (分支轮): 点「模型扒谱」后先选路线再转写。
   路线来自 transcription_mode.TRANSCRIBE_ENGINES 注册表 ——
   以后新增模型只需扩展注册表, 本弹窗自动出现新分支。"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout,
                               QLabel, QRadioButton, QPushButton)

from transcription_mode import TRANSCRIBE_ENGINES
from i18n import t


class TranscribeEngineDialog(QDialog):
    """模型扒谱路线选择: transkun=钢琴专用 / muscriptor=多乐器 (注册表驱动)。"""

    def __init__(self, parent, default_route: str = ''):
        super().__init__(parent)
        self.setWindowTitle(t('选择转录路线'))
        self.setMinimumWidth(420)
        self.engine_id: str | None = None

        lay = QVBoxLayout(self)
        lay.addWidget(QLabel(t('请选择转录模型路线:')))

        self._radios = []
        for eid, label, desc in TRANSCRIBE_ENGINES:
            rb = QRadioButton(f'{label} — {desc}')
            if eid == default_route:
                rb.setChecked(True)
            rb.toggled.connect(self._sync_buttons)
            lay.addWidget(rb)
            self._radios.append((rb, eid))

        if not any(rb.isChecked() for rb, _ in self._radios):
            self._radios[0][0].setChecked(True)

        lay.addStretch(1)
        bot = QHBoxLayout()
        bot.addStretch(1)
        b_cancel = QPushButton(t('取消')); b_cancel.clicked.connect(self.reject)
        b_ok = QPushButton(t('确定')); b_ok.setDefault(True)
        b_ok.clicked.connect(self.accept)
        bot.addWidget(b_cancel); bot.addWidget(b_ok)
        lay.addLayout(bot)
        self._sync_buttons()

    def _sel_id(self):
        for rb, eid in self._radios:
            if rb.isChecked():
                return eid
        return None

    def _sync_buttons(self):
        has = self._sel_id() is not None
        for w in self.findChildren(__import__(
                'PySide6.QtWidgets', fromlist=['QPushButton']).QPushButton):
            if w.text() in (t('确定'), t('取消')):
                w.setEnabled(has)

    def selected_engine(self):
        return self._sel_id()
