# -*- coding: utf-8 -*-
"""对话框:
   OctaveMapDialog         音域分配(三排键串 + C1~B7 每个八度 -> 排/不映射)
   TransposeAnalysisDialog 移调分析与选择(-12~+12 黑键/未分配·超域/可演奏统计)
   SettingsDialog          自定义设置(键位/音域分配/播放整形/开始延迟/音域高亮)
   NoteSettingsDialog      音符字母显示 (O 轮新增, 主窗卷帘与编辑器同步生效)
   AppSettingsDialog       输出设备 + 语言 (O 轮新增)
   TrackSoundDialog        轨道独立音源 SF2+音色 + 音量增幅 (O 轮新增)"""
import os
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QGridLayout,
                               QGroupBox, QLabel, QLineEdit,
                               QPushButton, QSpinBox, QFileDialog)
from i18n import t
from window_chrome import fade_scale_in


class TrackSoundDialog(QDialog):
    """轨道音源/重命名弹窗 (Q 轮交互): 双击名称按钮或概览条打开
       可重命名轨道 + 为其指定独立 SF2/音色# (留空 = 不设独立音源)
       + 音量增幅 100%~800%; 确定后由主窗统一应用, 立即生效"""
    def __init__(self, mw, track, info):
        super().__init__(mw)
        self.setWindowTitle(t('轨道音源 / 重命名'))
        self.setMinimumWidth(500)
        self.mw = mw; self.tid = track.tid
        self.path = info['path'] if info else None      # None = 不设独立音源
        self.preset = info['preset'] if info else 0
        g0 = float(info.get('gain', 1.0)) if info else 1.0
        self.gain = max(1.0, min(8.0, g0))
        self.gain_pct = int(round(self.gain * 100))
        self.new_name = (track.name or t('轨道 {n}', n=track.tid + 1))
        lay = QVBoxLayout(self)
        box = QGroupBox(t('轨道名称 / 音源'))
        g = QGridLayout(box); g.setContentsMargins(8, 4, 8, 4)
        g.addWidget(QLabel(t('名称')), 0, 0)
        self.ed_name = QLineEdit(self.new_name); self.ed_name.setMaxLength(24)
        g.addWidget(self.ed_name, 0, 1)
        g.addWidget(QLabel(t('当前')), 1, 0)
        self.lb_cur = QLabel(); self.lb_cur.setStyleSheet('color:#7ec97e;')
        g.addWidget(self.lb_cur, 1, 1)
        row = QHBoxLayout()
        b_browse = QPushButton(t('浏览 SF2…')); b_browse.clicked.connect(self._browse)
        b_global = QPushButton(t('不设独立音源')); b_global.clicked.connect(self._use_global)
        row.addWidget(b_browse); row.addWidget(b_global); row.addStretch(1)
        g.addLayout(row, 2, 0, 1, 2)
        g.addWidget(QLabel(t('音色#')), 3, 0)
        self.sp_preset = QSpinBox(); self.sp_preset.setRange(0, 127)
        self.sp_preset.setValue(int(self.preset))
        g.addWidget(self.sp_preset, 3, 1)
        g.addWidget(QLabel(t('音量增幅')), 4, 0)
        self.sp_gain = QSpinBox()
        self.sp_gain.setRange(100, 800)
        self.sp_gain.setSingleStep(10)
        self.sp_gain.setSuffix('%')
        self.sp_gain.setValue(self.gain_pct)
        self.sp_gain.setToolTip(t('增强该轨音源响度 (100%=原声, 最高 800%)'))
        g.addWidget(self.sp_gain, 4, 1)
        hint = QLabel(t('立即生效; 仅本次会话有效 (重新载入 MIDI 后还原为全局音源)'))
        hint.setStyleSheet('color:#999;')
        g.addWidget(hint, 5, 0, 1, 2)
        lay.addWidget(box)
        bot = QHBoxLayout()
        b_cancel = QPushButton(t('取消')); b_cancel.clicked.connect(self.reject)
        b_ok = QPushButton(t('确定')); b_ok.setDefault(True)
        b_ok.clicked.connect(self._accept)
        bot.addStretch(1); bot.addWidget(b_cancel); bot.addWidget(b_ok)
        lay.addLayout(bot)
        fade_scale_in(self)                        # (交互轮) 弹窗入场动效
        self._refresh()
    def _refresh(self):
        self.lb_cur.setText(os.path.basename(self.path) if self.path
                            else t('未设独立音源'))
    def _browse(self):
        path, _ = QFileDialog.getOpenFileName(self, t('选择 SF2 音源'),
                                              self.mw._last_dir,
                                              'SoundFont (*.sf2);;All (*)')
        if path: self.path = path; self._refresh()
    def _use_global(self):
        self.path = None; self._refresh()
    def _accept(self):
        self.new_name = self.ed_name.text().strip()
        self.preset = self.sp_preset.value()
        self.gain_pct = int(self.sp_gain.value())
        self.gain = self.gain_pct / 100.0
        self.accept()
