# -*- coding: utf-8 -*-
"""扒谱乐器选择 — 对齐 MuScriptor 官方 `list-instruments` / `--instruments`。

不选任何乐器 = 自动检测 (transcribe 不传 instruments);
选中若干 = 硬约束, 只解码这些乐器组。
界面显示中文名, 传给模型仍用官方英文 id。
"""
from __future__ import annotations

from PySide6.QtCore import Qt, QSettings
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QWidget, QGridLayout, QCheckBox, QFrame,
)
from i18n import t
from window_chrome import fade_scale_in

# 官方 muscriptor list-instruments 顺序 (MT3_FULL_PLUS)
INSTRUMENT_CATALOG: list[tuple[str, str]] = [
    ('acoustic_piano', '原声钢琴'),
    ('electric_piano', '电钢琴'),
    ('chromatic_percussion', '半音打击乐'),
    ('organ', '风琴'),
    ('acoustic_guitar', '原声吉他'),
    ('clean_electric_guitar', '清音电吉他'),
    ('distorted_electric_guitar', '失真电吉他'),
    ('acoustic_bass', '原声贝斯'),
    ('electric_bass', '电贝斯'),
    ('violin', '小提琴'),
    ('viola', '中提琴'),
    ('cello', '大提琴'),
    ('contrabass', '低音提琴'),
    ('orchestral_harp', '竖琴'),
    ('timpani', '定音鼓'),
    ('string_ensemble', '弦乐组'),
    ('synth_strings', '合成弦乐'),
    ('voice', '人声'),
    ('orchestra_hit', '管弦乐重击'),
    ('trumpet', '小号'),
    ('trombone', '长号'),
    ('tuba', '大号'),
    ('french_horn', '圆号'),
    ('brass_section', '铜管组'),
    ('soprano_and_alto_sax', '高音/中音萨克斯'),
    ('tenor_sax', '次中音萨克斯'),
    ('baritone_sax', '上低音萨克斯'),
    ('oboe', '双簧管'),
    ('english_horn', '英国管'),
    ('bassoon', '巴松'),
    ('clarinet', '单簧管'),
    ('flutes', '长笛类'),
    ('synth_lead', '合成主音'),
    ('synth_pad', '合成铺底'),
    ('drums', '鼓组'),
]

_SETTINGS_ORG = 'MidiKeymap'
_SETTINGS_APP = 'PianoRollPlayer'
_SETTINGS_KEY = 'transcribe/instruments'


class TranscribeInstrumentsDialog(QDialog):
    """多选官方乐器组; 返回 selected_ids (空列表 = 自动检测)。"""

    def __init__(self, parent=None, preselected: list[str] | None = None):
        super().__init__(parent)
        self.setWindowTitle(t('选择乐器'))
        self.setMinimumSize(520, 480)
        self.selected_ids: list[str] = []
        self._boxes: dict[str, QCheckBox] = {}

        if preselected is None:
            preselected = _load_saved_ids()

        lay = QVBoxLayout(self)
        hint = QLabel(t(
            '不选 = 自动检测全部乐器; 勾选后只识别所选乐器 (MuScriptor 硬约束)。\n'
            '名称对应官方 list-instruments。'))
        hint.setWordWrap(True)
        hint.setStyleSheet('color:#999;')
        lay.addWidget(hint)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        body = QWidget()
        grid = QGridLayout(body)
        grid.setContentsMargins(4, 4, 4, 4)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(4)
        cols = 2
        for i, (iid, zh) in enumerate(INSTRUMENT_CATALOG):
            cb = QCheckBox(f'{zh}  ({iid})')
            cb.setChecked(iid in preselected)
            self._boxes[iid] = cb
            grid.addWidget(cb, i // cols, i % cols)
        scroll.setWidget(body)
        lay.addWidget(scroll, 1)

        tools = QHBoxLayout()
        b_all = QPushButton(t('全选'))
        b_none = QPushButton(t('全不选 (自动检测)'))
        b_all.clicked.connect(self._select_all)
        b_none.clicked.connect(self._select_none)
        tools.addWidget(b_all)
        tools.addWidget(b_none)
        tools.addStretch(1)
        lay.addLayout(tools)

        bot = QHBoxLayout()
        b_cancel = QPushButton(t('取消'))
        b_ok = QPushButton(t('开始模型扒谱'))
        b_ok.setDefault(True)
        b_cancel.clicked.connect(self.reject)
        b_ok.clicked.connect(self._accept)
        bot.addStretch(1)
        bot.addWidget(b_cancel)
        bot.addWidget(b_ok)
        lay.addLayout(bot)
        fade_scale_in(self)

    def _select_all(self):
        for cb in self._boxes.values():
            cb.setChecked(True)

    def _select_none(self):
        for cb in self._boxes.values():
            cb.setChecked(False)

    def _accept(self):
        self.selected_ids = [
            iid for iid, cb in self._boxes.items() if cb.isChecked()
        ]
        _save_ids(self.selected_ids)
        self.accept()


def _load_saved_ids() -> list[str]:
    st = QSettings(_SETTINGS_ORG, _SETTINGS_APP)
    raw = st.value(_SETTINGS_KEY, '')
    if not raw:
        return []
    if isinstance(raw, (list, tuple)):
        ids = [str(x) for x in raw]
    else:
        ids = [x.strip() for x in str(raw).split(',') if x.strip()]
    valid = {iid for iid, _ in INSTRUMENT_CATALOG}
    return [i for i in ids if i in valid]


def _save_ids(ids: list[str]):
    st = QSettings(_SETTINGS_ORG, _SETTINGS_APP)
    st.setValue(_SETTINGS_KEY, ','.join(ids))
