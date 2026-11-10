# -*- coding: utf-8 -*-
"""密度检测结果分级勾选对话框 (密度交互轮):
   DensityResultDialog   点击"识别密度" → 先检测 → 按 强/弱/候选 三级列出
                         分组明细, 勾选要自动打琶音组的层级 (可多选);
                         "重打" 勾选 = 先清当前音轨全部琶音标识再打 (含手动)"""
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QCheckBox,
                               QLabel, QPushButton, QTextBrowser)
from i18n import t

_TIERS = (('strong_suggestions', '强建议', True),
          ('weak_suggestions', '弱建议', False),
          ('candidates', '候选建议', False))


class DensityResultDialog(QDialog):
    """检测结果分级勾选: checked_tiers() → 要落标的层级键列表; retag() → 重打"""
    def __init__(self, parent, tname, result):
        super().__init__(parent)
        self.setWindowTitle(t('密度识别 · {name}', name=tname))
        self.setMinimumWidth(440)
        v = QVBoxLayout(self)
        v.addWidget(QLabel(t(
            '检出密度突增段落如下, 勾选要自动打琶音组的层级:')))
        self._counts_dbg = {k: len(result.get(k, []) or [])
                            for k in ('strong_suggestions',
                                      'weak_suggestions', 'candidates')}
        self._checks = {}
        for key, label, dft in _TIERS:
            groups = result.get(key, []) or []
            n_notes = sum(len(g['note_indices']) for g in groups)
            n_pl = sum(1 for g in groups if g.get('plateau'))
            txt = t('{l}: {g} 组 · {n} 音', l=label, g=len(groups), n=n_notes)
            if n_pl:
                txt += t(' (含平台块 {p} 组)', p=n_pl)
            cb = QCheckBox(txt)
            cb.setChecked(dft and bool(groups))
            cb.setEnabled(bool(groups))
            v.addWidget(cb)
            self._checks[key] = cb
        detail = QTextBrowser()
        detail.setReadOnly(True)
        lines = []
        for key, label, _ in _TIERS:
            for g in result.get(key, []) or []:
                pl = t(' · 平台块') if g.get('plateau') else ''
                rs = (' · ' + '/'.join(g.get('reasons', []))) \
                    if g.get('reasons') else ''
                lines.append(t('{l} · 小节 {m} · {n} 音 · 置信度 {c:.2f}{pl}{r}',
                               l=label, m=g['measure'], n=len(g['note_indices']),
                               c=g['confidence'], pl=pl, r=rs))
        if lines:
            detail.setPlainText('\n'.join(lines))
        else:
            detail.setPlainText(t('未检出密度突增段落'))
        v.addWidget(detail, 1)
        self.chk_retag = QCheckBox(t(
            '重打: 先清除当前音轨全部琶音标识再打标 (含手动标识, 可撤销)'))
        v.addWidget(self.chk_retag)
        bb = QHBoxLayout()
        ok = QPushButton(t('打标')); cancel = QPushButton(t('取消'))
        ok.setDefault(True)
        bb.addStretch(1); bb.addWidget(cancel); bb.addWidget(ok)
        v.addLayout(bb)
        cancel.clicked.connect(self.reject)
        ok.clicked.connect(self.accept)

    def checked_tiers(self) -> list:
        """→ 勾选的层级键列表 (strong_suggestions/weak_suggestions/candidates)"""
        return [key for key, _cb in self._checks.items()
                if _cb.isEnabled() and _cb.isChecked()]

    def retag(self) -> bool:
        """→ 是否先清当前音轨全部琶音标识再打标"""
        return self.chk_retag.isChecked()
