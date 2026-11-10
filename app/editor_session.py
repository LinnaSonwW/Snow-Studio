# -*- coding: utf-8 -*-
"""编辑器生命周期控制器 (P1-C 自 mainwindow.py 收编): 编辑窗开关/提交刷新/撤销入口/
   对齐同步/选区移调分析。只负责"编辑器领域"的流程编排; 数据写入仍经 model,
   UI 刷新仍走 mw._rebuild/_update_playhead; 手势与绘制留在 editor.py。
   mainwindow 保留同名一行委托作为稳定接口 (editor/tempo_editor/_smoke_all 调用点零改动)。"""
import os
from copy import deepcopy
from PySide6.QtWidgets import (QMessageBox, QDialog, QWidget, QVBoxLayout,
                               QHBoxLayout, QPushButton, QLabel,
                               QMenu, QComboBox, QCheckBox, QFileDialog,
                               QSlider, QStackedWidget, QButtonGroup)
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtCore import Qt, QTimer
from i18n import t as tr
import settings_store as store
from midi_data import retime, load_midi, Note, same_pitch_truncations
from model import EditSession
from editor import EditorWindow, EditablePianoRoll, RollMiniMap, ToolIndicator
from window_chrome import hover_pulse
from tempo_editor import TempoLane
from score_strip import ScoreStrip               # (P0b) 演奏谱横幅 (悬浮窗宿主已移主窗)


def _next_strip_layout(mw):
    """(小节谱轮) 排版切换: follow ⇄ bars"""
    order = ('follow', 'bars')
    cur = getattr(mw, 'strip_layout', 'follow')
    return order[(order.index(cur) + 1) % len(order)] if cur in order else 'follow'
from tracks_panel import TrackButton, track_hex
from dialogs import TransposeAnalysisDialog
from transcription_mode import TranscriptionController
from beat_analysis import analyze_audio            # (四期) 节拍分析引擎链
from beat_analysis import BeatAnalysisWorker       # (四期) QThread 分析 worker


class EditorSessionController:
    def __init__(self, mw):
        self.mw = mw
        # (P0b) 演奏谱面板状态 (规格§2.1/§3: 模式判断只在 UI 层, 不进数据层)
        self.panel_mode = 'tempo_editor'     # 'tempo_editor' | 'performance_view'
        # 乐谱排: 每排 = 并入该排的 tid 列表 (空 = 空白排; ≥2 = 合并为一条车道)
        self.score_rows = [[]]
        self._rows_song = None               # 乐谱排所属曲目 (换曲重置)
        self.picker = None                   # 选轨浮层 (TrackPickerOverlay)
        self._init_transcription_ctrl()

    def _open_editor(self):
        """打开编辑器: 备份 raw_notes -> 组装编辑窗(工具条+可编辑卷帘) -> 建会话.
           不强制 MIDI: 有音轨即可; 无时间轴时自动建空 TempoMap。"""
        mw = self.mw
        if not getattr(mw, 'tracks', None):
            QMessageBox.information(
                mw, tr("提示"),
                tr('请先添加一条音轨再打开编辑器')); return
        if mw.tmap is None:
            from midi_data import TempoMap
            tpb = 480
            bpm = float(getattr(mw, '_file_bpm', 120.0) or 120.0)
            mw.tmap = TempoMap(tpb, [(0, int(60e6 / bpm))])
            mw.bar_ticks = float(4 * tpb)
            if not mw.raw_notes:
                mw.raw_notes = []
            # 空项目默认 8 小节视野, 后续画音符 / 扒谱会再拉伸
            mw.total_tick_display = max(
                float(getattr(mw, 'total_tick_display', 0) or 0),
                float(mw.bar_ticks * 8))
        if mw.edit_session is not None:              # 已开着: 仅前置
            mw.editor_win.raise_(); mw.editor_win.activateWindow(); return
        mw._stop_playback()
        mw._edit_backup = deepcopy(mw.raw_notes)   # "放弃编辑"的还原点
        win = EditorWindow(mw)
        roll = EditablePianoRoll(mw, span=5)         # 5八度窗口 (C1~B8)
        if mw.raw_notes:                             # 初始音域窗口对准音符范围
            lo = min(nt.note for nt in mw.raw_notes)
            hi = max(nt.note for nt in mw.raw_notes)
            roll.view_note_start = (lo + hi) / 2 - 30  # 5*12/2 居中
            roll._clamp_view_note()
        roll.set_data(mw.tmap, mw.raw_notes, mw.bar_ticks,
                      tsig_map=mw.tsig_map)
        # 空谱面: 至少铺满 total_tick_display, 避免 fit_all 缩成 0
        if not mw.raw_notes:
            roll.total_tick = max(float(roll.total_tick),
                                  float(mw.total_tick_display))
        roll.scrubStarted.connect(mw._scrub_begin)   # 标尺擦洗定位, 与主卷帘一致
        roll.scrubMoved.connect(lambda s: mw._seek_visual(s))
        roll.scrubFinished.connect(mw._scrub_end)
        roll.notePreview.connect(mw._preview)        # 键盘侧栏试听
        roll.set_track_colors({t.tid: track_hex(t.tid) for t in mw.tracks})
        roll.active_tid = mw.active_tid              # (多音轨) 当前轨延续
        roll.set_note_label(mw.note_label_mode, mw.note_label_custom)   # (O 轮)
        roll.label_keymap = getattr(mw, '_label_keymap', None)            # (O 轮)
        mw.tool_indicator = ToolIndicator()          # 顶部工具指示框 (FL 式)
        mw.edit_minimap = RollMiniMap(roll)          # 顶部概览条 (视野窗口/缩放)
        roll.viewChanged.connect(mw.edit_minimap.update)
        mw.track_btn = TrackButton(mw)               # 当前轨选择按钮 (文字下拉)
        # ---- 编辑窗工具条: 只调主窗口/会话 API, 不依赖编辑器内部实现 ----
        bar = QHBoxLayout(); bar.setContentsMargins(6, 3, 6, 3)
        b_undo = QPushButton(tr("↶ 撤销")); b_undo.setFocusPolicy(Qt.NoFocus)
        b_undo.clicked.connect(mw._edit_undo)
        mw.b_snap = QPushButton(); mw.b_snap.setFocusPolicy(Qt.NoFocus)
        mw._snap_menu = QMenu(mw.b_snap)        # (D6) 对齐档位下拉菜单
        for lbl, v in EditablePianoRoll._SNAP_CHOICES:
            act = mw._snap_menu.addAction(tr(lbl)); act.setCheckable(True)
            act.triggered.connect(lambda _c=False, vv=v: self._set_editor_snap(vv))
        mw.b_snap.setMenu(mw._snap_menu)
        b_sv = QPushButton(tr("💾 另存 MIDI")); b_sv.setFocusPolicy(Qt.NoFocus)
        b_sv.clicked.connect(mw._save_midi_as)
        b_an2 = QPushButton(tr("分析")); b_an2.setFocusPolicy(Qt.NoFocus)   # (O 轮) 选区移调分析
        b_an2.setToolTip(tr('分析选中音符移调的黑键数量 (逻辑同主窗移调分析)'))
        b_an2.clicked.connect(self._analyze_selection)
        b_tr = QPushButton(tr('截断')); b_tr.setFocusPolicy(Qt.NoFocus)     # (截断轮) 同音高消重叠
        b_tr.setToolTip(tr('当前音轨同音高重叠截断: 每个音符结束 ≤ 下一同音高音符起始 (可撤销)'))
        b_tr.clicked.connect(self._truncate_overlaps)
        b_density = QPushButton(tr('识别密度')); b_density.setFocusPolicy(Qt.NoFocus)   # (密度轮) 琶音自动打标
        b_density.setToolTip(tr(
            '识别当前音轨密度突增段落 (琶音/装饰音群), 自动打琶音组标识\n'
            '→ 演奏谱折叠显示 (可撤销; 已有手动标识保留)\n'
            'Shift+点击: 清除当前音轨全部琶音标识后重新打标 (含手动, 可撤销)'))
        b_density.clicked.connect(self._detect_density)
        b_multipitch = QPushButton(tr('多音高分析')); b_multipitch.setFocusPolicy(Qt.NoFocus)
        b_multipitch.setToolTip(tr('导入音频: librosa 多音高识别 → 声组织 (只读参考层)'))
        b_multipitch.clicked.connect(self._start_multipitch)
        b_model = QPushButton(tr('模型扒谱')); b_model.setFocusPolicy(Qt.NoFocus)
        b_model.setToolTip(tr('导入音频: MuScriptor 模型 → 按乐器建轨写音符'))
        b_model.clicked.connect(self._start_model_transcription)
        # ---- (P0b) 面板模式: 变速编辑器 / 演奏谱视图 (规格§2.1 两级选择框) ----
        lbl_panel = QLabel(tr('面板'))
        mw.panel_combo = QComboBox(); mw.panel_combo.setFocusPolicy(Qt.NoFocus)
        mw.panel_combo.addItem(tr('变速编辑器'), 'tempo_editor')
        mw.panel_combo.addItem(tr('演奏谱视图'), 'performance_view')
        mw.panel_combo.currentIndexChanged.connect(
            lambda _i: self._set_panel_mode(mw.panel_combo.currentData()))
        # 乐谱排选轨已移入演奏谱左列「+」交互块 (旧 单/多乐器 · 旋律/伴奏 · 轨道菜单 ·
        # 排版 按钮删除); 属性置空保持旧调用点 (mainwindow._set_strip_layout 等) 安全
        mw.instr_combo = mw.mel_combo = mw.acc_combo = None
        mw.lanes_btn = mw.b_strip_layout = None
        # (UI二轮) 谱面悬浮窗启动入口已移至主窗工具栏 (b_score), 可独立于编辑器使用
        # (统一播放跟随 2026-09-08) 播放跟随开关: 播放中卷帘锚定 30% 随指针平移,
        # 横幅/悬浮窗经 viewChanged 一起动; 两种面板模式均可用 (跟随的是卷帘视野)。
        # 文案/提示 = 认领 i18n 孤儿串; 状态存 params/follow (孤儿参数闭环)
        mw.b_follow = QPushButton(tr('跟随')); mw.b_follow.setFocusPolicy(Qt.NoFocus)
        mw.b_follow.setCheckable(True)
        mw.b_follow.setChecked(bool(getattr(mw, 'follow_on', True)))
        mw.b_follow.setToolTip(tr('播放时卷帘自动跟随播放头'))
        mw.b_follow.setStyleSheet(
            "QPushButton:checked { color:#ffe2a8;"
            " background: rgba(232, 176, 90, 36);"
            " border:1px solid rgba(232, 176, 90, 150); }")
        mw.b_follow.clicked.connect(self._toggle_follow)
        # (缩放变速轮) 与跟随同款交互: 金色高亮开 / 灰关, 持久化 params/scale_bpm_link
        mw.b_scale_bpm = QPushButton(tr('缩放变速')); mw.b_scale_bpm.setFocusPolicy(Qt.NoFocus)
        mw.b_scale_bpm.setCheckable(True)
        mw.b_scale_bpm.setChecked(bool(getattr(mw, 'scale_bpm_link', False)))
        mw.b_scale_bpm.setToolTip(tr('开启后: 区域缩放音符按比例联动 BPM (缩放 2 倍 → BPM ×2)'))
        mw.b_scale_bpm.setStyleSheet(
            "QPushButton:checked { color:#ffe2a8;"
            " background: rgba(232, 176, 90, 36);"
            " border:1px solid rgba(232, 176, 90, 150); }")
        mw.b_scale_bpm.clicked.connect(self._toggle_scale_bpm)
        hint = QLabel(tr('P 画笔(点击创建, 点音符记时值) · E 选择 · 右键删除 · '
                         '拖动移动 · 边缘拉伸 · Ctrl+拖动复制 · 播放中编辑被忽略'))   # (C3/D2/28)
        hint.setStyleSheet("color:#999;")
        mw._edit_hint_lbl = hint            # (密度轮) 工具行行内反馈位
        bar.addWidget(mw.tool_indicator); bar.addWidget(mw.track_btn)
        b_snd = QPushButton(tr('音源…')); b_snd.setFocusPolicy(Qt.NoFocus)
        b_snd.setToolTip(tr('为当前音轨指定 SF2 音源, 并可增强响度至 800%'))
        b_snd.clicked.connect(self._edit_active_track_sound)
        for b in (b_snd, b_undo, mw.b_snap, b_sv, b_an2, b_tr, b_density,
                  b_multipitch, b_model):
            bar.addWidget(b); hover_pulse(b)   # (交互轮) 悬停脉冲
        bar.addWidget(lbl_panel); bar.addWidget(mw.panel_combo)
        bar.addWidget(mw.b_follow)
        bar.addWidget(mw.b_scale_bpm)
        bar.addStretch(1); bar.addWidget(hint)
        # ---- 原曲播放 / 导入 MIDI (钢琴卷帘顶层) ----
        audio_bar = QHBoxLayout(); audio_bar.setContentsMargins(6, 0, 6, 2)
        mw.chk_play_orig = QCheckBox(tr('播放原曲'))
        mw.chk_play_orig.setFocusPolicy(Qt.NoFocus)
        mw.chk_play_orig.setChecked(bool(getattr(mw, 'play_original', False)))
        mw.chk_play_orig.setToolTip(
            tr('勾选后与钢琴卷帘同步播放原曲音频 (Alt+F1 切换);\n'
               '扒谱时自动使用该音频; 否则请先选择音频文件'))
        mw.chk_play_orig.toggled.connect(self._toggle_play_original)
        # 原曲音量: 紧挨勾选框
        mw.lbl_orig_vol = QLabel(tr('音量'))
        mw.lbl_orig_vol.setStyleSheet('color:#aaa;')
        mw.sl_orig_vol = QSlider(Qt.Horizontal)
        mw.sl_orig_vol.setFocusPolicy(Qt.NoFocus)
        mw.sl_orig_vol.setRange(0, 100)
        mw.sl_orig_vol.setFixedWidth(88)
        vol_pct = int(round(float(getattr(mw, 'original_audio_volume', 1.0)) * 100))
        vol_pct = max(0, min(100, vol_pct))
        mw.sl_orig_vol.setValue(vol_pct)
        mw.sl_orig_vol.setToolTip(tr('原曲播放音量'))
        mw.lbl_orig_vol_val = QLabel(f'{vol_pct}%')
        mw.lbl_orig_vol_val.setStyleSheet('color:#aaa; min-width:2.2em;')
        mw.sl_orig_vol.valueChanged.connect(self._on_original_volume)
        oa = getattr(mw, 'original_audio', None)
        if oa is not None:
            oa.set_volume(vol_pct / 100.0)
        mw.lbl_orig_audio = QLabel()
        mw.lbl_orig_audio.setStyleSheet('color:#aaa;')
        mw.lbl_orig_audio.setMinimumWidth(120)
        b_pick_aud = QPushButton(tr('选择音频…'))
        b_pick_aud.setFocusPolicy(Qt.NoFocus)
        b_pick_aud.setToolTip(tr('选择要作为原曲播放的音频文件'))
        b_pick_aud.clicked.connect(self._pick_original_audio)
        b_imp_mid = QPushButton(tr('导入 MIDI'))
        b_imp_mid.setFocusPolicy(Qt.NoFocus)
        b_imp_mid.setToolTip(
            tr('导入 MIDI 并覆盖当前显示音轨上的全部音符'))
        b_imp_mid.clicked.connect(self._import_midi_to_active_track)
        mw.chk_show_tissue = QCheckBox(tr('显示声组织'))
        mw.chk_show_tissue.setFocusPolicy(Qt.NoFocus)
        show_t = bool(getattr(mw, 'show_sound_tissue', True))
        mw.show_sound_tissue = show_t
        roll.show_tissue = show_t
        mw.chk_show_tissue.setChecked(show_t)
        mw.chk_show_tissue.setToolTip(
            tr('显示 / 隐藏 Tonteppich (Sound Tissue / 声组织) 层'))
        mw.chk_show_tissue.toggled.connect(self._toggle_show_tissue)
        audio_bar.addWidget(mw.chk_play_orig)
        audio_bar.addWidget(mw.lbl_orig_vol)
        audio_bar.addWidget(mw.sl_orig_vol)
        audio_bar.addWidget(mw.lbl_orig_vol_val)
        audio_bar.addWidget(mw.lbl_orig_audio, 1)
        audio_bar.addWidget(mw.chk_show_tissue)
        audio_bar.addWidget(b_pick_aud); hover_pulse(b_pick_aud)
        audio_bar.addWidget(b_imp_mid); hover_pulse(b_imp_mid)
        self._refresh_orig_audio_label()
        body = QWidget()
        lay = QVBoxLayout(body); lay.setContentsMargins(2, 0, 2, 2); lay.setSpacing(2)
        lay.addLayout(bar); lay.addLayout(audio_bar); lay.addWidget(mw.edit_minimap)
        # ---- (Y 轮) 变速 lanes: FL 式拉起遮罩, 覆盖卷帘下部 (卷帘尺寸不变) ----
        mw.tempo_lane = TempoLane(roll, mw, lane_h=max(40.0, store.load_lane_h()))
        roll.tempo_lane = mw.tempo_lane          # 卷帘 resize 时 lanes 保持锚定
        # ---- (P0b) 演奏谱横幅: 与 lanes 共用底部容器互斥显示 (规格§2.1) ----
        mw.score_strip = ScoreStrip(roll, mw)
        mw.score_strip.setVisible(False)         # 默认 = 变速编辑器 (既有行为零变化)
        roll.score_strip = mw.score_strip        # 卷帘 resize 时横幅保持锚定
        roll.viewChanged.connect(mw.score_strip.on_roll_view_changed)
        from track_picker import TrackPickerOverlay
        self.picker = TrackPickerOverlay(roll, self)
        mw.score_strip.on_lane_click = self._open_track_picker
        self._sync_score_rows()
        # 面板状态跨编辑器会话保留: 恢复选择框显示与互斥可见性
        mw.panel_combo.blockSignals(True)
        mw.panel_combo.setCurrentIndex(1 if self.panel_mode == 'performance_view' else 0)
        mw.panel_combo.blockSignals(False)
        if self.panel_mode == 'performance_view':
            self._set_panel_mode('performance_view')
        lay.addWidget(roll, 1)
        shell = QWidget()
        shell_lay = QVBoxLayout(shell)
        shell_lay.setContentsMargins(2, 0, 2, 2)
        shell_lay.setSpacing(4)
        common_bar = QHBoxLayout()
        win.b_file = QPushButton(tr('文件'))
        win.file_menu = QMenu(win.b_file)
        win.a_open_midi = win.file_menu.addAction(tr('打开 MIDI 文件…'))
        win.a_open_midi.triggered.connect(self._open_editor_midi)
        win.a_import_midi = win.file_menu.addAction(tr('导入 MIDI 到当前轨（覆盖）…'))
        win.a_import_midi.triggered.connect(self._import_midi_to_active_track)
        win.b_file.setMenu(win.file_menu)
        win.b_settings = QPushButton(tr('设置'))
        win.b_settings.clicked.connect(lambda: mw._open_unified_settings(parent=win))
        win.b_roll_page = QPushButton(tr('钢琴卷帘'))
        win.b_transcribe_page = QPushButton(tr('扒谱'))
        win.page_group = QButtonGroup(win)
        for index, button in enumerate((win.b_roll_page, win.b_transcribe_page)):
            button.setCheckable(True)
            win.page_group.addButton(button, index)
        for button in (win.b_file, win.b_settings, win.b_roll_page, win.b_transcribe_page):
            button.setFocusPolicy(Qt.NoFocus)
            common_bar.addWidget(button)
        common_bar.addStretch(1)
        shell_lay.addLayout(common_bar)
        win.pages = QStackedWidget()
        win.pages.addWidget(body)
        from transcribe_view import TranscribeView
        win.transcribe_view = TranscribeView(mw)
        win.pages.addWidget(win.transcribe_view)
        win.page_group.idClicked.connect(self._set_workspace_page)
        win.b_roll_page.setChecked(True)
        shell_lay.addWidget(win.pages, 1)
        win.open_shortcut = QShortcut(QKeySequence('Ctrl+O'), win)
        win.open_shortcut.activated.connect(self._open_editor_midi)
        win.save_shortcut = QShortcut(QKeySequence('Ctrl+S'), win)
        win.save_shortcut.activated.connect(mw._save_midi_as)
        win.setContent(shell)
        mw.editor_win = win; mw.edit_roll = roll
        mw.edit_session = EditSession(mw, roll)
        mw.edit_session.on_notify = mw._on_edit_notify   # (P1-A) 撤销状态 UI 通知
        self._sync_snap_btn()                       # (D6) 对齐按钮显示当前档位
        mw._apply_range_hl()                      # (D4) 编辑卷帘同步音域高亮
        mw._sync_track_ui()                       # (多音轨) 甲板/幽灵着色同步
        roll.setFocusPolicy(Qt.StrongFocus)            # 画布接收 P/E 等按键
        win.show(); roll.setFocus()
        roll.fit_all()          # 布局完成后按真实宽度重新适配全曲 (show 前宽度未定)
        mw.statusBar().showMessage(
            tr('编辑器已打开: 改动实时提交到播放数据 · 关闭时可选 另存/放弃'))
    def _set_workspace_page(self, index):
        mw = self.mw
        win = mw.editor_win
        if win is None:
            return
        win.pages.setCurrentIndex(index)
        win.page_group.button(index).setChecked(True)
        if index == 0:
            mw.edit_roll.setFocus()
        else:
            win.transcribe_view.sync_state()

    def _open_editor_midi(self):
        mw = self.mw
        win = mw.editor_win
        geometry = win.saveGeometry() if win is not None else None
        if mw.open_midi(parent=win):
            mw._open_editor()
            if mw.editor_win is not None and geometry is not None:
                mw.editor_win.restoreGeometry(geometry)

    def _transcribe_views(self):
        workspace = getattr(self.mw, 'transcribe_workspace', None)
        return list(workspace.views) if workspace is not None else []

    def _set_editor_snap(self, v):
        if self.mw.edit_roll is not None:
            self.mw.edit_roll.set_snap(v)
            self._sync_snap_btn()

    def _edit_active_track_sound(self):
        """钢琴卷帘: 打开与主窗相同的音源弹窗 (含音量增幅), 作用于当前轨。"""
        mw = self.mw
        tid = getattr(mw, 'active_tid', None)
        if tid is None and getattr(mw, 'tracks', None):
            tid = mw.tracks[0].tid
        if tid is None:
            QMessageBox.information(
                mw, tr('提示'), tr('请先添加一条音轨再打开编辑器'))
            return
        mw._on_track_sound(tid)
    # ---------- (P0b) 演奏谱面板: 模式切换 / 乐谱排选轨 (规格§2.1/§3) ----------
    def _sync_score_rows(self):
        """换曲 = 乐谱排重置为一个空白排; 同曲只剔除已删除的轨"""
        mw = self.mw
        song = getattr(mw, '_midi_path', '') or id(getattr(mw, 'tracks', None))
        if song != self._rows_song:
            self._rows_song = song
            self.score_rows = [[]]
            return
        valid = {t.tid for t in getattr(mw, 'tracks', [])}
        self.score_rows = [[t for t in r if t in valid] for r in self.score_rows] or [[]]
    def _lane_tids(self):
        """乐谱排 → 车道键: [] = () 空白排; [t] = t; [t1, t2…] = 合并车道 (轨序)"""
        order = {t.tid: i for i, t in enumerate(getattr(self.mw, 'tracks', []))}
        keys = []
        for r in self.score_rows:
            ts = sorted((t for t in r if t in order), key=order.get)
            keys.append(ts[0] if len(ts) == 1 else tuple(ts))
        return keys
    def _push_lanes(self):
        for sf in (getattr(self.mw, 'score_strip', None),
                   getattr(getattr(self.mw, 'score_float', None), 'strip', None)):
            if sf is not None:
                sf.set_lanes(self._lane_tids())   # 内嵌横幅与悬浮窗同步车道
    def toggle_row_tid(self, idx, tid):
        """选轨浮层: 勾选/取消某轨并入第 idx 排 (即时生效)"""
        if not 0 <= idx < len(self.score_rows):
            return
        row = self.score_rows[idx]
        if tid in row:
            row.remove(tid)
        else:
            row.append(tid)
        self._push_lanes()
    def add_score_row(self):
        """选轨浮层「添加」: 末尾追加空白乐谱排, 返回其序号"""
        self.score_rows.append([])
        self._push_lanes()
        return len(self.score_rows) - 1
    def remove_score_row(self, idx):
        """选轨浮层「删除」: 删第 idx 排 (只删排配置, 不动音符), 返回删后应编辑的排号;
           仅剩一排时清空为空白排 (始终至少保留一排)"""
        if not 0 <= idx < len(self.score_rows):
            return 0
        if len(self.score_rows) <= 1:
            self.score_rows = [[]]
            idx = 0
        else:
            del self.score_rows[idx]
            idx = max(0, idx - 1)
        self._push_lanes()
        return idx
    def _open_track_picker(self, idx):
        if self.picker is not None and 0 <= idx < len(self.score_rows):
            self.picker.open_for(idx)
    def _set_panel_mode(self, mode):
        """一级选择框: 变速编辑器 ⇄ 演奏谱视图 (同容器互斥, 不重算缩放, 规格§2.1)"""
        mw = self.mw
        self.panel_mode = mode
        strip = getattr(mw, 'score_strip', None)
        if strip is None: return
        perf = (mode == 'performance_view')
        if mw.tempo_lane is not None:
            mw.tempo_lane.setVisible(not perf)
        strip.setVisible(perf)
        if perf:
            strip.reposition()                 # 与 lanes 同几何
            self._push_lanes()
        elif self.picker is not None:
            self.picker.close_overlay()
    # (UI二轮) 谱面悬浮窗开关移至主窗 _toggle_score_float; 编辑器会话结束时
    # 由 _end_edit_session 调 mw._score_float_rebind() 换绑独立卷帘 (不再关闭)
    # ---------- (统一播放跟随 2026-09-08) 开关 ----------
    def _toggle_follow(self, on):
        """播放跟随开关: 播放中卷帘按 30% 锚点随指针平移 (mainwindow._update_playhead
           驱动), 横幅/悬浮窗/概览条经 viewChanged 一起动; 持久化 params/follow"""
        mw = self.mw
        mw.follow_on = on
        mw._save_cfg()

    def _toggle_scale_bpm(self, on):
        """(缩放变速轮) 区域缩放联动 BPM 开关: 金色高亮开/灰关, 持久化
           params/scale_bpm_link (交互逻辑与跟随一致)"""
        mw = self.mw
        mw.scale_bpm_link = on
        mw._save_cfg()

    def _sync_snap_btn(self):
        """(D6) 工具条对齐按钮/菜单 与 编辑卷帘档位同步"""
        mw = self.mw
        if mw.edit_roll is None or not hasattr(mw, 'b_snap'): return
        lbl = mw.edit_roll._snap_label()
        mw.b_snap.setText(tr('对齐: {s} ▾', s=lbl))
        for act in mw._snap_menu.actions():
            act.setChecked(act.text() == lbl)
    def _confirm_discard(self):
        """编辑器存在未保存改动时询问; True=可以关闭(已另存/放弃/无改动), False=取消"""
        mw = self.mw
        if mw.edit_session is None or not mw.edit_session.dirty:
            return True
        ret = QMessageBox.warning(mw.editor_win or mw, tr("未保存的改动"),
            tr('编辑器中有未保存的改动。\n是否另存到 MIDI 文件?'),
            QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel,
            QMessageBox.Save)
        if ret == QMessageBox.Save:
            return mw._save_midi_as()
        return ret != QMessageBox.Cancel
    def _discard_edits(self):
        """放弃编辑: 仍有未保存改动时还原到备份; 已另存(或无改动)则保留编辑成果"""
        mw = self.mw
        if (mw.edit_session is not None and mw.edit_session.dirty
                and mw._edit_backup is not None):
            mw.raw_notes = mw._edit_backup
        mw._edit_backup = None
    def _end_edit_session(self, rebuild=True):
        """结束编辑会话: 拆除编辑窗引用, 按最终 raw_notes 重建主窗口派生数据"""
        mw = self.mw
        ctrl = getattr(mw, 'transcription_ctrl', None)
        if ctrl is not None and ctrl.active:
            ctrl.exit_mode()
        if mw.editor_win is not None:
            mw.editor_win.transcribe_view.dispose()
        mw.edit_session = None; mw.edit_roll = None
        mw._edit_backup = None
        mw.edit_minimap = None; mw.tool_indicator = None
        mw.tempo_lane = None
        mw.score_strip = None; mw.panel_combo = None; mw.instr_combo = None
        mw.mel_combo = None; mw.acc_combo = None; mw.lanes_btn = None
        mw.b_strip_layout = None
        self.picker = None                      # 浮层随卷帘销毁
        mw.track_btn = None                     # (修复) 按钮随编辑器销毁, 置空防空引用
        mw.chk_play_orig = None
        mw.lbl_orig_audio = None
        mw.chk_show_tissue = None
        mw.sl_orig_vol = None
        mw.lbl_orig_vol = None
        mw.lbl_orig_vol_val = None
        if mw.score_float is not None:          # (UI二轮) 悬浮窗独立存活: 换绑独立卷帘
            mw._score_float_rebind()
        if mw.editor_win is not None:
            w = mw.editor_win; mw.editor_win = None
            w.hide(); w.deleteLater()
        if rebuild and mw.tmap is not None:
            retime(mw.raw_notes, mw.tmap)      # 兜底: 保证 tick/sec 一致
            mw._rebuild(keep_view=True)
    def _editor_commit(self):
        """编辑器改动 raw_notes 后的提交刷新(编辑器每次编辑/撤销后调用):
           重算 sec -> 重建 移调/重叠/映射/事件表(保持视图与指针) -> 同步编辑卷帘/甲板"""
        mw = self.mw
        if mw.tmap is None: return
        retime(mw.raw_notes, mw.tmap)
        mw._rebuild(keep_view=True)
        if mw.edit_roll is not None:
            mw.edit_roll.set_data(mw.tmap, mw.raw_notes,
                                  mw.bar_ticks, keep_view=True,
                                  tsig_map=mw.tsig_map)
        mw.deck.refresh()                        # (Q 轮) 主窗甲板概览条同步刷新
        if mw.tempo_lane is not None:
            mw.tempo_lane.update()               # (Q 轮) lanes 事件条随编辑刷新
    def _edit_undo(self):
        if self.mw.edit_session is not None and self.mw.edit_session.undo():
            self._editor_commit()
    # ---------- (O 轮) 编辑器选区移调分析 (逻辑与主窗移调分析一致) ----------
    def _analyze_selection(self):
        """编辑窗 分析 按钮: 统计框选音符各档移调的黑键数量, 选择后移调选区"""
        mw = self.mw
        if mw.edit_session is None or mw.edit_roll is None: return
        sel = {nt.nid for nt in mw.raw_notes if nt.nid in mw.edit_roll.selection}
        if not sel:
            mw.statusBar().showMessage(tr('请先框选/选择音符后再分析'), 3000)
            return
        sel_notes = [nt for nt in mw.raw_notes if nt.nid in sel]
        # 复用主窗弹窗: 传入选区音符 + 真实键位 -> 统计/推荐/双击选择 逻辑完全一致
        dlg = TransposeAnalysisDialog(mw.editor_win or mw, sel_notes,
                                      mw.oct_assign, current=0,
                                      row_keys=mw.row_keys)
        if dlg.exec() != TransposeAnalysisDialog.Accepted: return
        self._apply_selection_transpose(sel, dlg.chosen)
    def _truncate_overlaps(self):
        """编辑窗 截断 按钮: 当前音轨同音高重叠时值截断
           (每个音符结束 ≤ 下一同音高音符起始, 一步撤销)"""
        mw = self.mw
        if mw.edit_session is None or mw.edit_roll is None: return
        if mw._is_playing():                 # (28) 播放中忽略改动
            mw.statusBar().showMessage(
                tr('播放中 · 改动被忽略 (暂停/停止后可编辑)'), 3000)
            return
        track_notes = [nt for nt in mw.raw_notes if nt.tid == mw.active_tid]
        changes = same_pitch_truncations(track_notes)
        if not changes:
            mw.statusBar().showMessage(tr('当前音轨无同音高重叠'), 3000)
            return
        mw.edit_session.push()
        for nt, new_end in changes:
            mw.model.set_note_span(nt, nt.start_tick, new_end)
        self._editor_commit()
        mw.statusBar().showMessage(
            tr('已截断 {n} 处同音高重叠', n=len(changes)), 3000)

    def _detect_density(self, retag=None):
        """编辑窗 识别密度 按钮: 当前音轨密度突增段落 → 先检测 → 弹窗按
           强/弱/候选 三级列出分组明细, 用户勾选要落标的层级 → 确定后统一
           打琶音组标识 (一步撤销)。弹窗勾选"重打"(或 Shift/Ctrl+点击预勾)
           = 先清当前音轨全部琶音标识再打 (含手动标识)"""
        from PySide6.QtWidgets import QApplication
        mw = self.mw
        if mw.edit_session is None or mw.edit_roll is None: return
        if mw._is_playing():                 # (28) 播放中忽略改动
            self._density_flash(tr('播放中 · 改动被忽略 (暂停/停止后可编辑)'))
            return
        import ornament_detect as od         # 懒加载 (numpy 缺失时空结果降级)
        track_notes = [nt for nt in mw.raw_notes if nt.tid == mw.active_tid]
        if len(track_notes) < 3:
            self._density_flash(tr('密度识别: 当前音轨音符太少 (<3), 无法识别'))
            return
        dicts = od.notes_to_dicts(track_notes)
        tname = next((t.name for t in mw.tracks if t.tid == mw.active_tid),
                     '?')
        times = [float(mw.tmap.tick2sec(int(nt.start_tick)))
                 for nt in track_notes]      # (变速轮) 分段真实秒
        result = od.run_analysis(dicts, mw.tmap.tpb, {
            'bpm': float(mw.tmap.bpm_at_tick(0)),
            'bar_beats': max(1.0, float(mw.bar_ticks) / float(mw.tmap.tpb))},
            times_sec=times, tsig=mw.tsig_map)
        counts = {k: len(result[k]) for k in
                  ('strong_suggestions', 'weak_suggestions', 'candidates')}
        if sum(counts.values()) == 0:
            self._density_flash(tr(
                '密度识别 [{name}]: 未检出密度突增段落', name=tname))
            return
        # (交互轮) 检测 → 弹窗分级勾选 → 确定后统一打标
        from dialogs import DensityResultDialog
        dlg = DensityResultDialog(mw.editor_win, tname, result)
        if retag:                            # Shift/Ctrl+点击: 预勾重打
            dlg.chk_retag.setChecked(True)
        if not dlg.exec():
            return                           # 取消: 不打标
        tiers = dlg.checked_tiers()
        if not tiers:
            self._density_flash(tr('密度识别: 未勾选任何层级, 不打标'))
            return
        mw.edit_session.push()               # 一步撤销 (写标识前压栈)
        if dlg.retag():                      # 重打: 清当前轨旧标识 (含手动)
            for nt in track_notes:
                nt.arp = 0
        changed = []
        gid = 0
        for key in ('strong_suggestions', 'weak_suggestions', 'candidates'):
            if key not in tiers:
                continue
            k = counts[key]
            changed += od.apply_suggestions(result, track_notes, dicts,
                                            tier=key, start_gid=gid + 1)
            gid += k                         # 组号跨层级联 (1..99 循环)
        self._editor_commit()
        self._density_flash(tr(
            '密度识别 [{name}]: 已标 {n} 音 (强 {s} · 弱 {w} · 候选 {c})'
            '{rt} — 可撤销', name=tname, n=len(changed),
            s=counts['strong_suggestions'] if 'strong_suggestions' in tiers else 0,
            w=counts['weak_suggestions'] if 'weak_suggestions' in tiers else 0,
            c=counts['candidates'] if 'candidates' in tiers else 0,
            rt=' · 重打' if dlg.retag() else ''))

    def _density_flash(self, text):
        """编辑窗内行内反馈 (6s 后还原快捷键提示): 状态栏在主窗结论行,
           编辑窗 (独立窗口) 内不可见 —— 密度轮补此可见反馈位"""
        mw = self.mw
        mw.statusBar().showMessage(text, 6000)      # 主窗通道保留
        lbl = getattr(mw, '_edit_hint_lbl', None)
        if lbl is None:
            return
        if not hasattr(lbl, '_orig'):
            lbl._orig = (lbl.text(), lbl.styleSheet())
        lbl.setText(text)
        lbl.setStyleSheet('color:#e8b05a;')
        QTimer.singleShot(6000, lambda: lbl.setText(lbl._orig[0]))
        QTimer.singleShot(6000,
                          lambda: lbl.setStyleSheet(lbl._orig[1]))

    def _apply_selection_transpose(self, sel_nids, off):
        """选区整体移调 (一步撤销, 钳 C1~B8), 提交刷新"""
        mw = self.mw
        if not off: return
        mw.model.transpose_notes(sel_nids, off)   # (P1收口) push+钳制+retime 接线既有API
        self._editor_commit()
        mw.statusBar().showMessage(tr('已将选中音符移调 {n:+d} 半音', n=off), 3000)

    # ---------- 多音高分析 / 模型扒谱 (独立功能) ----------
    def _init_transcription_ctrl(self):
        mw = self.mw
        if hasattr(mw, 'transcription_ctrl'):
            return
        mw.transcription_ctrl = TranscriptionController(mw)
        mw.transcription_ctrl.progress.connect(self._on_trans_progress)
        mw.transcription_ctrl.tissue_failed.connect(self._on_tissue_failed)
        mw.transcription_ctrl.model_failed.connect(self._on_model_failed)
        mw.transcription_ctrl.tissue_complete.connect(self._on_tissue_complete)
        mw.transcription_ctrl.transcription_complete.connect(self._on_transcription_complete)

    def _ensure_editor_for_transcription(self):
        """无 MIDI 时也可扒谱: 建空 TempoMap 并打开编辑器。"""
        mw = self.mw
        if mw.tmap is None:
            from midi_data import TempoMap, Track
            mw.tmap = TempoMap(480, [(0, 500000)])
            mw.bar_ticks = float(4 * 480)
            mw.total_tick_display = float(mw.bar_ticks * 4)
            if not mw.raw_notes:
                mw.raw_notes = []
            if not getattr(mw, 'tracks', None):
                mw.tracks = [Track(0, tr('轨道 1'))]
        if mw.edit_roll is None:
            self._open_editor()

    def _pick_transcription_audio(self) -> str | None:
        mw = self.mw
        path, _ = QFileDialog.getOpenFileName(
            mw.editor_win or mw, tr('选择音频'),
            '', tr('音频 (*.wav *.mp3 *.flac *.ogg *.m4a *.aac);;全部 (*.*)'))
        return path or None

    def _bind_transcription_audio(self, path: str):
        """分析/扒谱音频同时作为原曲播放源。"""
        mw = self.mw
        oa = getattr(mw, 'original_audio', None)
        if oa is not None:
            oa.set_source(path)
            self._refresh_orig_audio_label()

    def _start_multipitch(self):
        mw = self.mw
        path = self._pick_transcription_audio()
        if not path:
            return
        self._ensure_editor_for_transcription()
        if mw.edit_roll is None:
            return
        self._bind_transcription_audio(path)
        mw.transcription_ctrl.start_multipitch(path)
        mw.statusBar().showMessage(tr('多音高分析中: 生成声组织…'), 6000)

    def _start_model_transcription(self):
        """模型扒谱: 先选转录路线 (分支轮), 再按路线分派。"""
        mw = self.mw
        path = self._pick_transcription_audio()
        if not path:
            return
        from dialogs.transcribe_engine import TranscribeEngineDialog
        dlg = TranscribeEngineDialog(mw.editor_win or mw,
                                     default_route=mw.transcribe_route)
        if dlg.exec() != QDialog.Accepted:
            return
        engine = dlg.selected_engine()
        self._ensure_editor_for_transcription()
        if mw.edit_roll is None:
            return
        self._bind_transcription_audio(path)
        if engine == 'transkun':
            mw.transcription_ctrl.start_transkun(path)
            mw.statusBar().showMessage(tr('钢琴专用路线转写中…'), 6000)
        else:
            from dialogs import TranscribeInstrumentsDialog
            dlg2 = TranscribeInstrumentsDialog(mw.editor_win or mw)
            if dlg2.exec() != QDialog.Accepted:
                return
            instruments = dlg2.selected_ids or None   # 空 = 官方默认自动检测
            mw.transcription_ctrl.start_model(path, instruments=instruments)
            if instruments:
                mw.statusBar().showMessage(
                    tr('模型扒谱中: 已选 {n} 种乐器…', n=len(instruments)), 6000)
            else:
                mw.statusBar().showMessage(
                    tr('模型扒谱中: 自动检测乐器…'), 6000)

    def _refresh_orig_audio_label(self):
        mw = self.mw
        lbl = getattr(mw, 'lbl_orig_audio', None)
        if lbl is None:
            return
        oa = getattr(mw, 'original_audio', None)
        path = oa.path if oa is not None else ''
        if path:
            import os
            lbl.setText(tr('原曲: {f}', f=os.path.basename(path)))
            lbl.setToolTip(path)
        else:
            lbl.setText(tr('原曲: 未选择'))
            lbl.setToolTip('')

    def _toggle_show_tissue(self, on):
        """显示/隐藏 Tonteppich · Sound Tissue (声组织)。"""
        mw = self.mw
        mw.show_sound_tissue = bool(on)
        roll = mw.edit_roll
        if roll is None:
            return
        roll.show_tissue = bool(on)
        # 画布 key 含 show_tissue: 清缓存后按新可见性重烘
        if getattr(roll, 'tiles', None) is not None:
            roll.tiles.clear()
        roll.update()

    def _toggle_play_original(self, on):
        mw = self.mw
        mw.play_original = bool(on)
        oa = getattr(mw, 'original_audio', None)
        if oa is None:
            return
        if not on:
            oa.set_enabled(False)
            return
        if not oa.path:
            # 勾选但无源: 弹出选择
            if not self._pick_original_audio():
                mw.play_original = False
                chk = getattr(mw, 'chk_play_orig', None)
                if chk is not None:
                    chk.blockSignals(True)
                    chk.setChecked(False)
                    chk.blockSignals(False)
                return
        oa.set_enabled(True)

    def _shortcut_toggle_play_original(self):
        """Alt+F1: 切换「播放原曲」勾选 (编辑器未开时先打开)。"""
        mw = self.mw
        if mw.edit_roll is None:
            self._open_editor()
            if mw.edit_roll is None:
                return
        chk = getattr(mw, 'chk_play_orig', None)
        if chk is not None:
            chk.toggle()
        else:
            self._toggle_play_original(not getattr(mw, 'play_original', False))

    def _on_original_volume(self, pct: int):
        mw = self.mw
        vol = max(0, min(100, int(pct))) / 100.0
        mw.original_audio_volume = vol
        oa = getattr(mw, 'original_audio', None)
        if oa is not None:
            oa.set_volume(vol)
        lbl = getattr(mw, 'lbl_orig_vol_val', None)
        if lbl is not None:
            lbl.setText(f'{int(pct)}%')

    def _pick_original_audio(self) -> bool:
        mw = self.mw
        path, _ = QFileDialog.getOpenFileName(
            mw.editor_win or mw, tr('选择原曲音频'),
            '', tr('音频 (*.wav *.mp3 *.flac *.ogg *.m4a *.aac);;全部 (*.*)'))
        if not path:
            return False
        oa = getattr(mw, 'original_audio', None)
        if oa is None:
            return False
        oa.set_source(path)
        self._refresh_orig_audio_label()
        # 若已勾选播放原曲, 撑开时间轴
        if oa.duration_sec > 0:
            mw.total_sec = max(float(mw.total_sec or 0), float(oa.duration_sec))
        mw.statusBar().showMessage(tr('已选择原曲: {f}', f=path), 4000)
        return True

    def _import_midi_to_active_track(self):
        """导入 MIDI: 合并文件内全部音符, 覆盖写入当前显示音轨。"""
        mw = self.mw
        if mw.edit_roll is None or mw.edit_session is None or mw.tmap is None:
            QMessageBox.information(
                mw, tr('提示'), tr('请先打开编辑器')); return
        path, _ = QFileDialog.getOpenFileName(
            mw.editor_win or mw, tr('导入 MIDI 到当前音轨'),
            '', tr('MIDI 文件 (*.mid *.midi);;全部 (*.*)'))
        if not path:
            return
        try:
            src_tmap, src_notes, _bar, _tsig, _tracks, _tsig_events = load_midi(path)
        except Exception as e:
            QMessageBox.warning(
                mw.editor_win or mw, tr('导入失败'),
                tr('无法读取 MIDI:\n{e}', e=e)); return
        if not src_notes:
            QMessageBox.information(
                mw.editor_win or mw, tr('提示'),
                tr('该 MIDI 没有可导入的音符')); return
        tid = int(getattr(mw, 'active_tid', 0) or 0)
        # tick 换算到当前项目 tpb (用秒对齐再转 tick, 保留相对时值)
        scale = float(mw.tmap.tpb) / float(src_tmap.tpb or 480)
        new_notes = []
        for nt in src_notes:
            st = max(0, int(round(nt.start_tick * scale)))
            en = max(st + 1, int(round(nt.end_tick * scale)))
            new_notes.append(Note(
                int(nt.note), int(nt.vel), st, en, 0.0, 0.0, tid=tid))
        mw.model.push()
        # 删除当前轨全部音符, 再写入导入
        mw.raw_notes[:] = [o for o in mw.raw_notes if o.tid != tid]
        mw.model.append_notes(new_notes)
        mw.model.finish()
        # 拉长显示范围
        max_tick = max(nt.end_tick for nt in mw.raw_notes) if mw.raw_notes else 0
        mw.total_tick_display = max(
            float(getattr(mw, 'total_tick_display', 0) or 0),
            float(max_tick + (mw.bar_ticks or 1920)))
        self._editor_commit()
        if mw.edit_roll is not None:
            mw.edit_roll.total_tick = max(
                float(mw.edit_roll.total_tick), float(mw.total_tick_display))
            mw.edit_roll.update()
        mw.statusBar().showMessage(
            tr('已导入 MIDI 到当前音轨 · {n} 个音符', n=len(new_notes)), 5000)

    def _on_trans_progress(self, done, total, msg):
        mw = self.mw
        if total > 0:
            mw.statusBar().showMessage(f'{msg} ({done}/{total})', 0)
        else:
            mw.statusBar().showMessage(msg, 0)

    def _on_tissue_failed(self, msg):
        mw = self.mw
        QMessageBox.warning(mw.editor_win or mw, tr('多音高分析失败'), msg)

    def _on_model_failed(self, msg):
        mw = self.mw
        QMessageBox.warning(mw.editor_win or mw, tr('模型扒谱失败'), msg)

    def _on_tissue_complete(self, n: int):
        mw = self.mw
        mw.statusBar().showMessage(tr('声组织就绪 · {n} 条轨迹', n=n), 6000)

    def _show_beat_override(self):
        """覆盖弹窗: 手动修正自动分析的 BPM/拍号/调性 (写入同一数据)"""
        from PySide6.QtWidgets import (QDialog, QHBoxLayout, QVBoxLayout,
                                       QLabel, QDoubleSpinBox, QSpinBox,
                                       QComboBox, QPushButton)
        from window_chrome import fade_scale_in
        mw = self.mw
        bpm0 = float(mw.tmap.bpm_at_tick(0))
        n0, d0 = mw.tsig_map.at(0)
        dlg = QDialog(mw)
        dlg.setWindowTitle(tr('节拍修正'))
        v = QVBoxLayout(dlg)
        r1 = QHBoxLayout(); r1.addWidget(QLabel(tr('BPM:')))
        sp_bpm = QDoubleSpinBox(); sp_bpm.setRange(20.0, 400.0)
        sp_bpm.setDecimals(1); sp_bpm.setValue(bpm0)
        r1.addWidget(sp_bpm); v.addLayout(r1)
        r2 = QHBoxLayout(); r2.addWidget(QLabel(tr('节拍:')))
        sp_n = QSpinBox(); sp_n.setRange(1, 32); sp_n.setValue(n0)
        cmb_d = QComboBox()
        for dn in (2, 4, 8, 16):
            cmb_d.addItem(f'/ {dn}', dn)
        cmb_d.setCurrentIndex(max(0, cmb_d.findData(d0)))
        r2.addWidget(sp_n); r2.addWidget(cmb_d); v.addLayout(r2)
        r3 = QHBoxLayout(); r3.addWidget(QLabel(tr('调性:')))
        cmb_key = QComboBox()
        keys = ('1=C', '1=G', '1=D', '1=A', '1=E', '1=B', '1=#F', '1=#C',
                '1=F', '1=bB', '1=bE', '1=bA', '1=bD', '1=bG')
        cmb_key.addItems(keys)
        cur = str(getattr(mw, 'key_label', '1=C'))
        cmb_key.setCurrentIndex(max(0, keys.index(cur)))
        r3.addWidget(cmb_key); v.addLayout(r3)
        bb = QHBoxLayout(); bb.addStretch(1)
        b_cancel = QPushButton(tr('取消')); b_cancel.clicked.connect(dlg.reject)
        b_ok = QPushButton(tr('确定')); b_ok.setDefault(True)
        b_ok.clicked.connect(dlg.accept)
        bb.addWidget(b_cancel); bb.addWidget(b_ok)
        v.addLayout(bb)
        fade_scale_in(dlg)
        if dlg.exec() != QDialog.Accepted: return
        mw._apply_beat_analysis({'bpm': sp_bpm.value(),
                                 'num': sp_n.value(), 'den': cmb_d.currentData(),
                                 'key': keys[cmb_key.currentIndex()],
                                 'engine': 'manual'})

    def _on_transcription_complete(self):
        mw = self.mw
        n = 0
        ctrl = getattr(mw, 'transcription_ctrl', None)
        if ctrl is not None and ctrl.mode is not None:
            n = ctrl.mode.notes_written
        mw.statusBar().showMessage(tr('模型扒谱完成 · 已写入 {n} 个音符', n=n), 6000)
        # (速度方案轮) 手动唯一 BPM: 无需节拍分析, 转录完成即按手动 BPM 重缩放
        if getattr(mw, 'transcribe_tempo_scheme', '') == 'fixed_manual':
            bpm = max(30, min(300, int(getattr(mw, 'transcribe_manual_bpm', 120))))
            mw._apply_tempo_segments(
                [{'t0': 0.0, 't1': None, 'bpm': float(bpm)}])
            for tv in self._transcribe_views():
                tv.set_beat_result(tr('速度方案: 手动唯一 BPM {b} 已应用 '
                                      '(音符已对齐)', b=bpm), None)
            return                                   # 手动方案: 不需要节拍分析
        # (四期) 转录后自动节拍分析: 源音频 → BPM/拍号/调性 写入工程
        if not getattr(mw, 'beat_auto', True):
            return
        ap = None
        if ctrl is not None and ctrl.mode is not None:
            ap = getattr(ctrl.mode, 'audio_path', None)
        if not ap or not os.path.isfile(ap):
            return
        from beat_analysis import BeatAnalysisWorker
        self._beat_worker = BeatAnalysisWorker(ap)
        session = mw.edit_session
        self._beat_worker.done.connect(
            lambda res: self._on_beat_done(res) if mw.edit_session is session else None)
        self._beat_worker.failed.connect(
            lambda m: mw.statusBar().showMessage(m, 4000))
        self._beat_worker.start()
        mw.statusBar().showMessage(tr('节拍分析中… (源音频 BPM/拍号检测)'), 4000)

    def _on_beat_done(self, res):
        """节拍分析完成: 段落级写入 (BPM/拍号段/调性) + 结论行 (点击可覆盖)"""
        mw = self.mw
        mw._apply_beat_analysis(res)
        for tv in self._transcribe_views():
            n_seg = len(res.get('segments') or [])
            txt = 'BPM={b:.0f}'.format(b=res['bpm'])
            if n_seg >= 2:
                txt += ' · 变速 {c} 段'.format(c=n_seg)
            txt += ' · {n}/{d} · 1=C  (点击修正)'.format(
                n=res['num'], d=res['den'])
            tv.set_beat_result(txt, lambda: self._show_beat_override())
