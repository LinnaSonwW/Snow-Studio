# -*- coding: utf-8 -*-
"""扒谱专用视图 (分离轮):
   ViewSwitcher     顶栏双段式切换胶囊 (✦ 星弹 | ♪ 扒谱), QSettings 记忆
   TranscribeView   扒谱工作台: 音频选择/转录路线/音频分离(SW 六轨·Inst 人声伴奏)/
                    逐轨工作台 (波形·静音·独奏·保存WAV·音量·转MIDI) / 状态区
   转写与分离分别复用 TranscriptionController 与 separation.SeparationWorker;
   逐轨「转MIDI」写入当前工程 (需已加载 MIDI 工程, 否则提示)。"""
import os
import time

from PySide6.QtCore import Qt, QSettings, QRectF, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen, QPolygonF
from PySide6.QtCore import QPointF
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                               QPushButton, QRadioButton, QProgressBar, QSpinBox,
                               QScrollArea, QFileDialog, QMessageBox,
                               QButtonGroup, QSlider, QComboBox, QFrame,
                               QSizePolicy, QCheckBox, QDialog)

from i18n import t
import separation
import paths

_AUDIO_EXT = ('.wav', '.mp3', '.flac', '.ogg', '.m4a', '.aac', '.wma')
_STEM_COLORS = {'bass': '#5aa2e8', 'drums': '#e8925a', 'guitar': '#6fd18a',
                'piano': '#b58ae8', 'vocals': '#e86fa8', 'other': '#9aa3b0',
                'instrumental': '#e8c05a'}
_ENGINE_LABELS = (('transkun', 'Transkun 钢琴'), ('muscriptor', 'MuScriptor 多乐器'))


def _peaks_of(path, buckets=120):
    """wav → 每桶峰值振幅 (0..1), 用于波形绘制; 失败返回空。
    (基础版修复) numpy/soundfile 为扩展包依赖, 延迟到函数内导入:
    主窗启动 import 本模块时不得硬依赖扩展包 (否则无 vendor 即闪退)"""
    try:
        import numpy as np
        import soundfile as sf
        data, _sr = sf.read(path, dtype='float32', always_2d=True)
        mono = data.mean(axis=1)
        if mono.size == 0:
            return []
        n = min(buckets, mono.size)
        edges = np.linspace(0, mono.size, n + 1, dtype=int)
        out = []
        for a, b in zip(edges, edges[1:]):
            seg = mono[a:b] if b > a else mono[a:a + 1]
            out.append(float(np.max(np.abs(seg))) if seg.size else 0.0)
        mx = max(out) or 1.0
        return [v / mx for v in out]
    except Exception:
        return []


class ViewSwitcher(QFrame):
    """顶栏双段式视图切换胶囊: view_changed('galaxy' | 'transcribe')"""

    view_changed = Signal(str)

    def __init__(self):
        super().__init__()
        self.setObjectName('viewSwitcher')
        self.setStyleSheet(
            '#viewSwitcher{background:#10141c;border:1px solid #2a3442;'
            'border-radius:10px;}'
            'QPushButton{border:none;background:transparent;color:#8a94a2;'
            'padding:5px 14px;font-weight:600;}'
            'QPushButton:checked{color:#f5f7fa;background:#3d6ea5;'
            'border-radius:8px;}')
        lay = QHBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(2)
        self.b_galaxy = QPushButton(t('✦ 星弹'))
        self.b_transcribe = QPushButton(t('♪ 扒谱'))
        for b in (self.b_galaxy, self.b_transcribe):
            b.setCheckable(True)
            b.setFocusPolicy(Qt.NoFocus)
            b.setCursor(Qt.PointingHandCursor)
            lay.addWidget(b)
        grp = QButtonGroup(self)
        grp.setExclusive(True)
        grp.addButton(self.b_galaxy)
        grp.addButton(self.b_transcribe)
        self.b_galaxy.setChecked(True)
        grp.buttonClicked.connect(self._emit)
        self._grp = grp

    def _emit(self, btn):
        if btn is self.b_transcribe:
            self.view_changed.emit('transcribe')
        else:
            self.view_changed.emit('galaxy')

    def set_view(self, view):
        for b, v in ((self.b_galaxy, 'galaxy'),
                     (self.b_transcribe, 'transcribe')):
            b.setChecked(v == view)


class StemRow(QWidget):
    """逐轨工作台行: 波形 + 播放/静音/独奏/移除/保存WAV + 音量 + 转MIDI
       自带 QMediaPlayer 播放该行 wav; 静音/独奏真正控制音频输出。"""

    removed = Signal(object)
    transcribe_requested = Signal(object)
    audible_changed = Signal()                    # 静音/独奏变化 → 刷新混音

    def __init__(self, instr, path, mw):
        super().__init__()
        self.instr = instr
        self.path = path
        self.mw = mw
        self.peaks = _peaks_of(path)
        self.muted = False
        self.solo = False
        self.player = None                            # QMediaPlayer (懒创建)
        self.audio_out = None                         # QAudioOutput (懒创建)
        color = _STEM_COLORS.get(instr, '#9aa3b0')
        self.setStyleSheet(
            f'QWidget#stemRow{{background:#12161f;border:1px solid #232d3c;'
            f'border-radius:8px;}}'
            f'QLabel#stemName{{color:{color};font-weight:700;}}'
            f'QPushButton{{background:#1b2230;border:1px solid #2a3442;'
            f'border-radius:6px;color:#c8d0dc;padding:3px 8px;}}'
            f'QPushButton:checked{{background:#3d6ea5;color:#fff;'
            f'border-color:#3d6ea5;}}'
            f'QSlider::groove:horizontal{{height:3px;background:#2a3442;}}'
            f'QSlider::handle:horizontal{{width:9px;margin:-4px 0;'
            f'background:#c8d0dc;border-radius:4px;}}')
        self.setObjectName('stemRow')
        row = QHBoxLayout(self)
        row.setContentsMargins(10, 6, 10, 6)
        row.setSpacing(8)
        name = QLabel(instr)
        name.setObjectName('stemName')
        name.setFixedWidth(72)
        row.addWidget(name)
        self.wave = _Wave(self.peaks, color)
        self.wave.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.wave.setFixedHeight(44)
        row.addWidget(self.wave, 1)
        self.b_mute = QPushButton(t('静音'))
        self.b_mute.setCheckable(True)
        self.b_mute.clicked.connect(self._mute_changed)
        self.b_solo = QPushButton(t('独奏'))
        self.b_solo.setCheckable(True)
        self.b_solo.clicked.connect(self._solo_changed)
        self.b_del = QPushButton(t('移除'))
        self.b_del.clicked.connect(lambda: self.removed.emit(self))
        self.b_save = QPushButton(t('保存WAV…'))
        self.b_save.clicked.connect(self._save)
        for b in (self.b_mute, self.b_solo, self.b_del, self.b_save):
            row.addWidget(b)
        self.combo = QComboBox()
        for val, lbl in _ENGINE_LABELS:
            self.combo.addItem(lbl, val)
        if instr == 'piano':
            self.combo.setCurrentIndex(0)
        else:
            self.combo.setCurrentIndex(1)
        row.addWidget(self.combo)
        self.vol = QSlider(Qt.Horizontal)
        self.vol.setRange(0, 200)
        self.vol.setValue(100)
        self.vol.setFixedWidth(80)
        self.vol.valueChanged.connect(self._apply_volume)
        row.addWidget(self.vol)
        self.b_go = QPushButton(t('转 MIDI'))
        self.b_go.clicked.connect(
            lambda: self.transcribe_requested.emit(self))
        row.addWidget(self.b_go)

    def _ensure_player(self):
        """懒创建 QMediaPlayer + QAudioOutput"""
        from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
        if self.player is None:
            self.player = QMediaPlayer()
            self.audio_out = QAudioOutput()
            self.player.setAudioOutput(self.audio_out)
            self.player.setSource(QUrl.fromLocalFile(self.path))
        return self.player, self.audio_out

    def _toggle_play(self):
        player, _out = self._ensure_player()
        from PySide6.QtMultimedia import QMediaPlayer
        if player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            player.pause()
            self.b_play.setText(t('播放'))
        else:
            player.play()
            self.b_play.setText(t('暂停'))

    def _apply_volume(self, v):
        _player, out = self._ensure_player()
        out.setVolume(max(0.0, min(2.0, v / 100.0)))

    def _mute_changed(self):
        """静音 → setMuted + setVolume(0) 绕过 Qt FFmpeg 后端 bug"""
        _player, out = self._ensure_player()
        on = self.b_mute.isChecked()
        self.muted = on
        out.setMuted(on)
        out.setVolume(0.0 if on else self.vol.value() / 100.0 * 2.0)
        self.audible_changed.emit()

    def _solo_changed(self):
        """独奏切换 → 静音其他行 / 取消时恢复其他行"""
        self.solo = self.b_solo.isChecked()
        self.audible_changed.emit()
        parent = self.parentWidget()
        if parent is None:
            return
        lay = parent.layout()
        if lay is None:
            return
        for i in range(lay.count()):
            w = lay.itemAt(i).widget()
            if w is not None and isinstance(w, StemRow) and w is not self:
                if self.solo:
                    w.b_mute.setChecked(True)
                    w._mute_changed()
                else:
                    w.b_mute.setChecked(False)
                    w._mute_changed()

    def _save(self):
        dst, _f = QFileDialog.getSaveFileName(
            self, t('保存 WAV'), f'{self.instr}.wav', 'WAV (*.wav)')
        if dst:
            import shutil
            shutil.copyfile(self.path, dst)


class _Wave(QWidget):
    """极简波形: 峰值镜像条 + 播放位置红色指针"""

    def __init__(self, peaks, color):
        super().__init__()
        self._peaks = peaks
        self._color = color
        self._play_ratio = 0.0                      # 0.0~1.0 播放进度

    def set_play_ratio(self, ratio):
        self._play_ratio = max(0.0, min(1.0, ratio))
        self.update()

    def paintEvent(self, ev):
        p = QPainter(self)
        w, h = self.width(), self.height()
        p.fillRect(self.rect(), QColor('#0c1017'))
        if not self._peaks:
            return
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(self._color))
        n = len(self._peaks)
        bw = w / n
        mid = h / 2
        for i, v in enumerate(self._peaks):
            bh = max(1.0, v * (h - 6))
            p.drawRect(QRectF(i * bw + 0.5, mid - bh / 2, max(1.0, bw - 1.0),
                              bh))
        # 播放位置红色指针
        if self._play_ratio > 0:
            px = w * self._play_ratio
            p.setPen(QPen(QColor('#e84a4a'), 2))
            p.drawLine(QPointF(px, 2), QPointF(px, h - 2))


class TranscribeView(QWidget):
    """扒谱工作台: 音频 → (可选)分离 → 逐轨转 MIDI"""

    def __init__(self, mw):
        super().__init__()
        self.mw = mw
        self.setAutoFillBackground(True)
        pal = self.palette()
        pal.setColor(self.backgroundRole(), QColor('#0b0e14'))
        self.setPalette(pal)
        self.setAcceptDrops(True)
        self.audio_path = ''
        self._disposed = False
        if not hasattr(mw, 'transcribe_workspace'):
            from transcribe_workspace import TranscribeWorkspace
            mw.transcribe_workspace = TranscribeWorkspace(mw)
        self.workspace = mw.transcribe_workspace
        self._beat_cb = None                     # (四期) 节拍结论行的修正回调
        self._sep_worker = None
        self._players = {}                        # id(row) -> (QMediaPlayer, QAudioOutput)
        self._playing_row = None
        self._mix_players = {}                    # id(row) -> (QMediaPlayer, QAudioOutput) 全部播放
        self._playing_all = False
        self._mix_dur = 1000                      # mix 播放总时长 (ms)
        self._slider_drag = False

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 12, 18, 12)
        root.setSpacing(10)

        # 音频
        lb1 = QLabel(t('音频 (点击选择或拖入)'))
        lb1.setStyleSheet('color:#8a94a2;font-weight:600;')
        root.addWidget(lb1)
        self.b_audio = QPushButton(t('🎵 选择音频文件…'))
        self.b_audio.setMinimumHeight(44)
        self.b_audio.setStyleSheet(
            'QPushButton{background:#12161f;border:1px dashed #3a4a5a;'
            'border-radius:8px;color:#c8d0dc;text-align:left;padding:0 14px;}'
            'QPushButton:hover{border-color:#3d6ea5;}')
        self.b_audio.clicked.connect(self._pick_audio)
        root.addWidget(self.b_audio)

        # 音频分离 (卡片式模型选择)
        sep_box = QFrame()
        sep_box.setObjectName('sepBox')
        sep_box.setStyleSheet(
            '#sepBox{background:#12161f;border:1px solid #232d3c;'
            'border-radius:8px;}'
            '#sepBox QPushButton{background:#1b2230;border:1px solid #2a3442;'
            'border-radius:6px;color:#c8d0dc;padding:4px 10px;}'
            '#sepBox QPushButton:hover{border-color:#3d6ea5;}')
        sv = QVBoxLayout(sep_box)
        sv.setContentsMargins(12, 8, 12, 8)
        cap = QLabel(t('音频分离 (BS-Roformer · 需已导入分离模型)'))
        cap.setStyleSheet('font-weight:600;')
        sv.addWidget(cap)
        sr = QHBoxLayout()
        sr.setSpacing(10)
        card_ss = (
            'QPushButton{background:#12161f;border:1px solid #2a3442;'
            'border-radius:8px;color:#8a94a2;text-align:left;'
            'padding:8px 12px;font-weight:600;}'
            'QPushButton:checked{border:2px solid #e8b05a;'
            'background:#1a2338;color:#f5f7fa;}'
            'QPushButton:hover{border-color:#e8b05a;}')
        self.rb_sw = QPushButton(t('六轨 SW\n贝斯/鼓/吉他/钢琴/人声/其他'))
        self.rb_inst = QPushButton(t('人声/伴奏 Inst\n人声 + 伴奏两轨'))
        for b in (self.rb_sw, self.rb_inst):
            b.setCheckable(True)
            b.setMinimumHeight(52)
            b.setStyleSheet(card_ss)
        btn_grp = QButtonGroup(self)
        btn_grp.setExclusive(True)
        btn_grp.addButton(self.rb_sw)
        btn_grp.addButton(self.rb_inst)
        self.rb_sw.setChecked(True)
        sr.addWidget(self.rb_sw)
        sr.addWidget(self.rb_inst)
        sr.addStretch(1)
        self.b_sep = QPushButton(t('开始分离'))
        self.b_sep.clicked.connect(self._start_sep)
        sr.addWidget(self.b_sep)
        sv.addLayout(sr)
        self.pb_sep = QProgressBar()
        self.pb_sep.setRange(0, 0)
        self.pb_sep.hide()
        sv.addWidget(self.pb_sep)
        self.lb_sep = QLabel('')
        self.lb_sep.setStyleSheet('color:#8a94a2;')
        sv.addWidget(self.lb_sep)
        root.addWidget(sep_box)

        # 播放全部 + 可拖动进度条 (主窗同款样式)
        pb_row = QHBoxLayout()
        pb_row.setContentsMargins(0, 0, 0, 0)
        self.b_play_all = QPushButton(t('播放全部'))
        self.b_play_all.setFixedHeight(30)
        self.b_play_all.setStyleSheet(
            'QPushButton{background:#3d6ea5;color:#fff;border:none;'
            'border-radius:8px;font-weight:700;padding:0 18px;}'
            'QPushButton:hover{background:#4a7dbd;}')
        self.b_play_all.clicked.connect(self._toggle_play_all)
        pb_row.addWidget(self.b_play_all)
        self.time_lbl = QLabel('0:00.0 / 0:00.0')
        self.time_lbl.setMinimumWidth(130)
        self.time_lbl.setStyleSheet('color:#c8d0dc;')
        pb_row.addWidget(self.time_lbl)
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, 1000)
        self.slider.setFocusPolicy(Qt.NoFocus)
        self.slider.setFixedHeight(14)
        self.slider.setStyleSheet(
            'QSlider::groove:horizontal { height:2px; background:#5a6270; }'
            'QSlider::handle:horizontal { width:10px; height:10px;'
            ' margin:-4px 0; background:#e8eef6; border-radius:1px; }'
            'QSlider::sub-page:horizontal { background:#9aa3b0; }')
        self.slider.sliderPressed.connect(self._slider_pressed)
        self.slider.sliderMoved.connect(self._slider_moved)
        self.slider.sliderReleased.connect(self._slider_released)
        pb_row.addWidget(self.slider, 1)
        root.addLayout(pb_row)

        # ⑤ 逐轨工作台
        self.work_scroll = QScrollArea()
        self.work_scroll.setWidgetResizable(True)
        self.work_scroll.setFrameShape(QScrollArea.NoFrame)
        self.work_holder = QWidget()
        self.work_lay = QVBoxLayout(self.work_holder)
        self.work_lay.setContentsMargins(0, 0, 0, 0)
        self.work_lay.setSpacing(6)
        self.work_lay.addStretch(1)
        self.work_scroll.setWidget(self.work_holder)
        self.work_scroll.setMinimumHeight(120)
        root.addWidget(self.work_scroll, 1)

        # ⑤ 状态
        self.lb_status = QLabel(t('就绪'))
        self.lb_status.setStyleSheet('color:#8a94a2;')
        root.addWidget(self.lb_status)
        # (四期) 节拍分析结论行 (可点击修正) + 自动分析开关
        self.lb_beat = QLabel('')
        self.lb_beat.setStyleSheet('color:#8ab4e8;')
        self.lb_beat.setTextInteractionFlags(Qt.TextBrowserInteraction)
        self.lb_beat.linkActivated.connect(
            lambda _h: self._beat_cb and self._beat_cb())
        self.lb_beat.hide()
        root.addWidget(self.lb_beat)
        self.chk_beat_auto = QCheckBox(t('转录后自动节拍分析'))
        self.chk_beat_auto.setChecked(bool(getattr(mw, 'beat_auto', True)))
        self.chk_beat_auto.toggled.connect(
            lambda on: (setattr(mw, 'beat_auto', on), mw._save_cfg(),
                        self.workspace.changed.emit()))
        root.addWidget(self.chk_beat_auto)
        # (速度方案轮) 速度方案: 跟随原曲 / 自动检测唯一 BPM / 手动唯一 BPM
        scheme_row = QHBoxLayout()
        scheme_row.setContentsMargins(0, 0, 0, 0)
        scheme_row.addWidget(QLabel(t('速度方案')))
        self.cmb_scheme = QComboBox()
        self.cmb_scheme.addItem(t('跟随原曲速度变化'), 'adaptive')
        self.cmb_scheme.addItem(t('自动检测唯一 BPM（推荐）'), 'fixed_auto')
        self.cmb_scheme.addItem(t('手动设置唯一 BPM'), 'fixed_manual')
        self.cmb_scheme.setCurrentIndex(max(0, self.cmb_scheme.findData(
            getattr(mw, 'transcribe_tempo_scheme', 'fixed_auto'))))
        self.cmb_scheme.currentIndexChanged.connect(self._on_scheme_changed)
        scheme_row.addWidget(self.cmb_scheme)
        self.sp_manual_bpm = QSpinBox()
        self.sp_manual_bpm.setRange(30, 300)
        self.sp_manual_bpm.setValue(int(getattr(mw, 'transcribe_manual_bpm', 120)))
        self.sp_manual_bpm.setSuffix(' BPM')
        self.sp_manual_bpm.setToolTip(t('手动唯一 BPM 范围 30-300, 音符时长按此速度标定'))
        self.sp_manual_bpm.valueChanged.connect(
            lambda v: (setattr(mw, 'transcribe_manual_bpm', v), mw._save_cfg(),
                       self.workspace.changed.emit()))
        scheme_row.addWidget(self.sp_manual_bpm)
        scheme_row.addStretch(1)
        root.addLayout(scheme_row)
        self._on_scheme_changed()              # 初始可见性 (手动 BPM 仅手动方案显示)
        tx_row = QHBoxLayout()
        self.cmb_engine = QComboBox()
        for engine, label in _ENGINE_LABELS:
            self.cmb_engine.addItem(label, engine)
        self.b_transcribe = QPushButton(t('转写原音频'))
        self.b_transcribe.clicked.connect(self._start_transcribe)
        self.pb_tx = QProgressBar()
        self.pb_tx.hide()
        tx_row.addWidget(self.cmb_engine)
        tx_row.addWidget(self.b_transcribe)
        tx_row.addWidget(self.pb_tx, 1)
        root.insertLayout(2, tx_row)
        self.workspace.register(self)

    def _on_scheme_changed(self, *_):
        """(速度方案轮) 方案切换: 存档 + 手动 BPM 框仅手动方案显示"""
        mw = self.mw
        val = self.cmb_scheme.currentData()
        mw.transcribe_tempo_scheme = str(val)
        mw._save_cfg()
        self.sp_manual_bpm.setVisible(val == 'fixed_manual')
        if self in self.workspace.views:
            self.workspace.changed.emit()

    def set_beat_result(self, text, on_click=None, publish=True):
        """(四期) 节拍分析结论行: text 展示; on_click 给出时变为可点击修正链接"""
        self._beat_cb = on_click
        if publish:
            self.workspace.beat_text = text
            self.workspace.beat_callback = on_click
        self.lb_beat.setText(
            f'<a href="#beat" style="color:#8ab4e8;">{text}</a>'
            if on_click else text)
        self.lb_beat.setVisible(bool(text))
    def _beat_cb_default(self):
        pass

    def sync_state(self):
        if self._disposed:
            return
        ctrl = self.mw.transcription_ctrl
        busy = ctrl.model_running
        separating = self.workspace.worker is not None
        self.lb_status.setText(t(self.workspace.status))
        self.b_sep.setEnabled(not separating)
        self.pb_sep.setVisible(separating)
        self.b_transcribe.setEnabled(not busy)
        self.pb_tx.setVisible(busy)
        done, total = self.workspace.progress
        self.pb_tx.setRange(0, max(0, total))
        self.pb_tx.setValue(done)
        for row in self._visible_stem_rows():
            row.b_go.setEnabled(not busy)
        for widget, value in ((self.chk_beat_auto, self.mw.beat_auto),
                              (self.sp_manual_bpm, self.mw.transcribe_manual_bpm)):
            widget.blockSignals(True)
            if widget is self.chk_beat_auto:
                widget.setChecked(value)
            else:
                widget.setValue(value)
            widget.blockSignals(False)
        self.cmb_scheme.blockSignals(True)
        self.cmb_scheme.setCurrentIndex(max(0, self.cmb_scheme.findData(
            self.mw.transcribe_tempo_scheme)))
        self.cmb_scheme.blockSignals(False)
        self.sp_manual_bpm.setVisible(self.cmb_scheme.currentData() == 'fixed_manual')

    def dispose(self):
        if self._disposed:
            return
        self._disposed = True
        self.workspace.unregister(self)
        self._stop_play_all()
        for player, output in self._players.values():
            player.stop()
            player.deleteLater()
            output.deleteLater()
        self._players.clear()
        for row in self._visible_stem_rows():
            if row.player is not None:
                row.player.stop()
                row.player.deleteLater()
            if row.audio_out is not None:
                row.audio_out.deleteLater()

    # ---- 视图生命周期 (mainwindow 切换时调用) ----
    def activate(self):
        self.show()

    def deactivate(self):
        self.hide()

    # ---- 拖放 ----
    def dragEnterEvent(self, ev):         # noqa: N802
        if ev.mimeData().hasUrls():
            ev.acceptProposedAction()

    def dropEvent(self, ev):              # noqa: N802
        for u in ev.mimeData().urls():
            p = u.toLocalFile()
            if p.lower().endswith(_AUDIO_EXT):
                self.set_audio(p)
                break

    # ---- 播放全部 / 可拖动进度条 ----
    @staticmethod
    def _fmt_ms(ms):
        """毫秒 → m:ss.d"""
        s = ms / 1000.0
        return f'{int(s) // 60}:{s % 60:04.1f}'

    def _toggle_play_all(self):
        if self._playing_all:
            self._stop_play_all()
            self.b_play_all.setText(t('播放全部'))
            self.time_lbl.setText('0:00.0 / 0:00.0')
            self.slider.setValue(0)
            for row in self._visible_stem_rows():
                row.wave.set_play_ratio(0.0)
            return
        rows = self._audible_rows()
        if not rows:
            self.lb_status.setText(t('没有可播放的音轨'))
            return
        self._stop_play_all()
        self._mix_players.clear()
        from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
        for row in rows:
            pl = QMediaPlayer(self)
            out = QAudioOutput(self)
            out.setVolume(1.0)
            pl.setAudioOutput(out)
            pl.setSource(QUrl.fromLocalFile(row.path))
            self._mix_players[id(row)] = (pl, out)
            row.player = pl                          # 存回行, 静音/独奏可控制
            row.audio_out = out
            row.wave.set_play_ratio(0.0)
        # 用最长音轨的 player 驱动进度联动
        first = self._mix_players[rows[0] and id(rows[0])]
        first[0].positionChanged.connect(self._mix_position)
        first[0].durationChanged.connect(
            lambda d: setattr(self, '_mix_dur', max(1, d)))
        self._mix_dur = 1
        for pl, _out in self._mix_players.values():
            pl.play()
        self._playing_all = True
        self.b_play_all.setText(t('停止'))

    def _mix_position(self, pos):
        """positionChanged → 滑条 + 时间标签 + 红色指针 (拖动中跳过)"""
        if self._slider_drag:
            return
        dur = max(1, self._mix_dur)
        self.slider.blockSignals(True)
        self.slider.setValue(min(1000, pos * 1000 // dur))
        self.slider.blockSignals(False)
        self.time_lbl.setText(
            f'{self._fmt_ms(pos)} / {self._fmt_ms(dur)}')
        ratio = min(1.0, pos / dur)
        for row in self._visible_stem_rows():
            row.wave.set_play_ratio(ratio)

    def _slider_pressed(self):
        self._slider_drag = True

    def _slider_moved(self, v):
        dur = max(1, self._mix_dur)
        self.time_lbl.setText(
            f'{self._fmt_ms(v * dur // 1000)} / {self._fmt_ms(dur)}')

    def _slider_released(self):
        """拖完松手 → seek 全部 mix players 到滑条位置"""
        self._slider_drag = False
        pos = self.slider.value() * self._mix_dur // 1000
        for pl, _out in self._mix_players.values():
            pl.setPosition(pos)

    def _stop_play_all(self):
        playing_rows = set(self._mix_players)
        for pl, _out in self._mix_players.values():
            pl.stop()
            pl.deleteLater()
            _out.deleteLater()
        self._mix_players.clear()
        for row in self._visible_stem_rows():
            row.wave.set_play_ratio(0.0)
            if id(row) in playing_rows:
                row.player = None
                row.audio_out = None
        self._playing_all = False

    def _max_stem_sec(self):
        mx = 0.0
        for row in self._visible_stem_rows():
            try:
                import soundfile as sf
                info = sf.info(row.path)
                mx = max(mx, info.frames / info.samplerate)
            except Exception:
                pass
        return mx if mx > 0 else 3.0

    def _audible_rows(self):
        rows = self._visible_stem_rows()
        soloed = [r for r in rows if r.solo]
        if soloed:
            return soloed
        return [r for r in rows if not r.muted]

    def _visible_stem_rows(self):
        out = []
        for i in range(self.work_lay.count() - 1):   # 末尾是 stretch
            w = self.work_lay.itemAt(i).widget()
            if isinstance(w, StemRow):
                out.append(w)
        return out

    # ---- 音频 ----
    def set_audio(self, path, publish=True):
        if publish:
            self.workspace.set_audio(path)
            return
        self.audio_path = path
        dur = ''
        try:
            import soundfile as sf
            info = sf.info(path)
            dur = f'{info.frames / info.samplerate:.1f}s'
        except Exception:
            pass
        self.b_audio.setText('🎵 ' + os.path.basename(path) + '   ' + dur)
        self.lb_status.setText(t('音频就绪 — 可分离音轨或直接转写'))

    def _pick_audio(self):
        dst, _f = QFileDialog.getOpenFileName(
            self, t('选择音频'), '',
            t('音频 (*.wav *.mp3 *.flac *.ogg *.m4a *.aac)'))
        if dst:
            self.set_audio(dst)

    # ---- 分离 ----
    def _sep_model(self):
        return 'inst' if self.rb_inst.isChecked() else 'sw'

    def _start_sep(self):
        self.workspace.start_separation(self._sep_model())

    def _add_stems(self, stems):
        for instr, path in stems:
            row = StemRow(instr, path, self.mw)
            row.removed.connect(self._remove_stem)
            row.transcribe_requested.connect(self._start_stem_transcribe)
            row.audible_changed.connect(self._refresh_mix_audio)
            self.work_lay.insertWidget(self.work_lay.count() - 1, row)
        if stems:
            self.lb_sep.setText(t('分离完成 — 音轨已加入下方工作台'))
        self.sync_state()

    def _refresh_mix_audio(self):
        """(对齐轮) 静音/独奏变化 → 实时更新各分轨的静音状态"""
        rows = self._visible_stem_rows()
        any_solo = any(r.solo for r in rows)
        for r in rows:
            key = id(r)
            if key in self._mix_players:
                _pl, out = self._mix_players[key]
                if any_solo:
                    out.setMuted(not r.solo)
                else:
                    out.setMuted(r.muted)

    def _remove_stem(self, row):
        self.workspace.remove_stem(row.path)

    def _remove_stem_path(self, path):
        self._stop_play_all()
        for row in self._visible_stem_rows():
            if row.path == path:
                self.work_lay.removeWidget(row)
                row.hide()
                row.deleteLater()

    # ---- 转写 ----
    def _ensure_editor(self):
        if self.mw.edit_roll is None:
            self.mw._open_editor()
        return self.mw.edit_roll is not None

    def _start_transcribe(self):
        if not self.audio_path:
            self.lb_status.setText(t('请先选择音频'))
            return
        if not self._ensure_editor():
            return
        self._transcribe_audio(self.audio_path, self.cmb_engine.currentData())

    def _start_stem_transcribe(self, row):
        if not self.mw.tmap:
            QMessageBox.information(
                self, t('提示'),
                t('转写结果需要写入工程 — 请先打开一个 MIDI 文件'))
            return
        if not self._ensure_editor():
            return
        self._transcribe_audio(row.path, row.combo.currentData())

    def _transcribe_audio(self, path, engine):
        ctrl = self.mw.transcription_ctrl
        if ctrl.model_running:
            self.lb_status.setText(t('扒谱任务正在运行，请等待完成'))
            return
        if engine == 'transkun':
            ctrl.start_transkun(path)
        else:
            from dialogs import TranscribeInstrumentsDialog
            dlg = TranscribeInstrumentsDialog(self.mw.editor_win or self)
            if dlg.exec() != QDialog.Accepted:
                return
            ctrl.start_model(path, instruments=dlg.selected_ids or None)
        self.sync_state()

    def _open_editor(self):
        self.mw._open_editor()
