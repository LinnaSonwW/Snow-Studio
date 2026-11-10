# -*- coding: utf-8 -*-
"""主窗口: 组装各模块 / 键位映射与音域分配 / 播放控制 / 统计 / QSettings 持久化
   + MIDI 编辑器集成(editor.py): 编辑会话生命周期 / 提交刷新 / 另存 MIDI(save_midi)
   “启用键盘输出”不复位保存(安全), 其余配置(三排键串/八度分配/移调/模式等)均持久化。"""
import os, time
from copy import deepcopy
from PySide6.QtCore import (Qt, QTimer, QByteArray, QEvent, QSettings, QPoint,
                            QRect,
                            QPropertyAnimation, QAbstractAnimation, QEasingCurve)
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout,
                               QPushButton, QSlider, QLabel, QStackedLayout,
                               QFileDialog, QMessageBox, QDoubleSpinBox,
                               QSpinBox, QComboBox, QCheckBox, QDialog,
                               QMenu, QGraphicsOpacityEffect)
from common import (IS_WIN, ROWS, ROW_NAMES, NOTE_MIN, NOTE_MAX, KB_W,
                    FOLLOW_X_FRAC, fmt_sec)
from midi_data import (load_midi, resolve_overlaps, Note, Track, retime, TsigMap,
                       save_midi)
from performance_model import (compile_performance,          # (P0) 演奏事件编译 (core-data)
                               compile_performance_by_tid)
from keymap import KeyMapper
from keyout import KeyboardOut
from pianist import KeyPianist
from sound import SoundEngine
from player import PlayerThread
from dialogs import (OctaveMapDialog, TransposeAnalysisDialog, KeymapDialog,
                     SettingsDialog, NoteSettingsDialog, AppSettingsDialog,
                     TrackSoundDialog)
from dialogs.unified_settings import UnifiedSettingsDialog
from window_chrome import ChromeWindow, CaptionButton, hover_pulse
from model import MusicModel, EDITOR_TITLE     # (X 轮/P1-A) 模型层 + 标题基名
from gesture_router import GestureRouter       # (Y 轮) 手势路由: 一次手势唯一 owner
from editor_session import EditorSessionController   # (P1-C) 编辑器生命周期控制器
from playback_controller import PlaybackController   # (P2-D)
from track_controller import TrackController         # (P2-D)
from editor import (EditorWindow, EditSession, EditablePianoRoll,
                    ToolIndicator, RollMiniMap)
from mini_bar import MiniBar
from tracks_panel import TrackDeck, TrackButton, track_hex
from score_float import ScoreFloat                 # 悬浮乐谱 (谱面本体 + 悬停工具栏 + 选项径向菜单)
import project_session                             # (工程轮) 编曲工程记忆
from view_roll import PianoRoll                    # (UI二轮) 独立卷帘视图模型
from tempo_editor import TempoLane
from main_chrome import (DiamondCluster, DiamondBtn, SongBar, HexIconBtn, BpmBox,
                         TipsPanel, ArrowCaptionBtn, TipHoverFilter,
                         BAR_H, SONG_W, BPM_W, TRANSPORT_GAP, MID_ROW_GAP,
                         TIPS_W, TIPS_H)
import i18n
from i18n import t as tr        # 别名 tr: 主窗大量用 t 表示播放线程
import settings_store as store

# ---- (布局轮) 主窗顶栏改自绘控件; 仅保留少量全局标签色 ----
MAIN_QSS = (
    'QLabel { color:#c8ccd4; }'
    'QCheckBox { color:#c8ccd4; }'
    'QDoubleSpinBox, QSpinBox { background: rgba(255, 255, 255, 18);'
    ' color:#d6d6de; border:none; border-radius:4px; }')

class _StatusShim:
    def __init__(self, lbl): self._lbl = lbl
    def showMessage(self, msg, timeout=0): self._lbl.setText(msg)
    def currentMessage(self): return self._lbl.text()
    def clear(self): self._lbl.setText('')

if IS_WIN:
    import ctypes

class MainWindow(ChromeWindow):
    RAD = 8                 # 暗黑圆角
    BG = '#000000'          # Particles 黑底
    BORDER = '#3a414c'      # 稍白细边框 (随底色加深调暗)
    FRAME_QSS = '#ChromeFrame { background:transparent; border:none; }'
    BAR = 34                # 标题栏不含窗口按钮, 比编辑窗矮
    BAR_BUTTONS = False     # (O 轮) 窗口按钮移入工具条 设置 旁 (见 _build_ui)
    RESIZABLE = False       # (P 轮) 主窗固定尺寸: 无最大化/边缘缩放
    # (W 轮) 标题动画: 点击 Snow 的 now 段 -> 乱码收缩 -> 向右展开落位 igma (Sigma), 再点切回
    title_fx = {'pre': 'S', 'cur': 'now', 'alt': 'igma', 'suf': ' 原琴工作站'}

    def eventFilter(self, obj, e):
        # (Galaxy 轮) overlay/deck → canvas 鼠标转发 (canvas 在 stack index 0 不收)
        if obj in getattr(self, '_galaxy_mouse_sources', ()):
            t = e.type()
            if t == QEvent.MouseMove and self.canvas is not None:
                p = e.position() if hasattr(e, 'position') else e.pos()
                # overlay/deck 与 canvas 是 stack 兄弟, 不能 mapFrom(兄弟);
                # 经全局坐标中转
                gp = obj.mapToGlobal(p.toPoint())
                cp = self.canvas.mapFromGlobal(gp)
                self.canvas._on_hover(cp.x(), cp.y())
            elif t == QEvent.Leave and self.canvas is not None:
                # 仅当离开整个中央区时熄灭; 子控件间穿梭不熄
                if obj is getattr(self, '_overlay_ref', None):
                    self.canvas._on_leave()
        return super().eventFilter(obj, e)
    def __init__(self):
        super().__init__('Snow 原琴工作站')
        self.setAcceptDrops(True)
        self._new_ui_window = None
        self._legacy_window_state = None
        self.tmap = None; self.raw_notes = []; self.notes = []
        self.model = MusicModel(self)      # (X 轮) 音符/Tempo 写入经模型层
        self.router = GestureRouter()      # (Y 轮) Piano Roll 与 Tempo lanes 输入层仲裁
        self.ed_sess = EditorSessionController(self)   # (P1-C) 编辑器生命周期控制器
        self.pb_ctrl = PlaybackController(self)        # (P2-D)
        self.trk_ctrl = TrackController(self)          # (P2-D)
        self.out_notes = []; self.events = []; self.total_sec = 0.0
        self.perf_events = []       # (P0) 演奏事件编译产物 (_rebuild 重算, 可整体丢弃)
        self.perf_by_tid = {}       # (P0b) 分道演奏事件 {tid: [事件]} (演奏谱横幅数据源)
        self.perf_ver = 0           # (性能修复 2026-09-08) 演奏数据版本: 横幅推送缓存失效门
        self.score_strip = None     # (P0b) 演奏谱横幅 (编辑器打开时存在; 与 tempo_lane 互斥)
        self.score_float = None     # (P0b·规格§8) 谱面悬浮窗 (编辑器会话内存在)
        self.total_tick_display = 1920.0    # 甲板概览条缩放基准 (整曲最大结束 tick)
        self._file_bpm = 120.0              # 导入文件的 BPM (播放速度换算基准)
        self.bar_ticks = 1920.0; self.mapper = None
        self.tsig_map = TsigMap(480, [(0, 4, 4)])   # (二期) 分段拍号表
        self.thread = None; self.cur_sec = 0.0
        self._last_dir = ''; self._dragging = False; self._was_playing = False
        self._cd_timer = None
        # ---- MIDI 编辑器状态 (流程见下方"编辑器"区块) ----
        self.edit_session = None            # EditSession; None = 当前无编辑会话
        self.editor_win = None              # EditorWindow 宿主窗
        self.edit_roll = None               # EditablePianoRoll 可编辑卷帘
        self._edit_backup = None            # 打开编辑器时的 raw_notes 备份("放弃"还原点)
        self.tsig = (4, 4)                  # 拍号 (另存 MIDI 需写回)
        self._midi_path = ''                # 来源文件路径 (另存对话框默认名)
        self.mini = None                    # 悬浮播放条 (MiniBar; None=未创建)
        self.tracks = []                    # (多音轨) Track 元数据列表
        self.active_tid = 0                 # (多音轨) 编辑器当前轨
        self.track_btn = None               # 编辑器当前轨选择按钮 (打开编辑器时创建)
        # ---- (O 轮) 语言 / 音符字母 / 输出设备 / 音源静音 ----
        self.current_lang = i18n.get_lang()
        self.note_label_mode, self.note_label_custom = store.load_note_label()
        self.transcribe_route = store.load_transcribe_cfg()
        self.audio_driver, self.audio_device = store.load_audio()
        self._stat_args = None              # 状态行统计参数 (retranslate 重算用)
        self._mapper_err = None
        self.engine = SoundEngine()
        self.engine.audio_driver = self.audio_driver
        self.engine.audio_device = self.audio_device
        self.engine.set_muted(store.load_mute())
        from original_audio import OriginalAudioPlayer
        self.original_audio = OriginalAudioPlayer(self)
        self.original_audio.error.connect(
            lambda m: self.statusBar().showMessage(m, 5000))
        self.play_original = False              # 编辑器勾选「播放原曲」
        self.original_audio_volume = 1.0        # 原曲音量 0..1
        # ---- 配置载入(QSettings, 非法回退默认) ----
        self.row_keys, self.oct_assign, self._params = store.load_settings()
        P = self._params
        self.overlap_mode = P.get('overlap', 'merge')       # (多音轨/设置中心) 属性化
        self.piano_mode = P.get('mode', 'hold')
        self.map_scope = P.get('map_scope', 'merge')        # (P 轮) 键盘映射范围
        self.trans = 0          # 播放层移调已锁死 0: 输出 = 卷帘实际音符 (旧存档值忽略)
        self.min_hold = int(P.get('min_hold', 45)) / 1000.0
        self.min_gap = int(P.get('min_gap', 55)) / 1000.0
        self.tap = int(P.get('tap', 70)) / 1000.0
        self.start_delay = int(P.get('delay', 3))
        self.range_hl_on = bool(P.get('range_hl', True))
        self.follow_on = bool(P.get('follow', True))   # (统一播放跟随) 消费孤儿参数
        self.scale_bpm_link = bool(P.get('scale_bpm_link', False))  # (缩放变速轮) 区域缩放联动 BPM
        self.beat_auto = bool(P.get('beat_auto', True))  # (四期) 转录后自动节拍分析
        self.key_label = str(P.get('key_label', '1=C'))  # (标记轮) 调性标注 (显示用)
        self.strip_layout = str(P.get('strip_layout', 'follow'))  # (排版轮) 演奏谱排版
        if self.strip_layout not in ('follow', 'bars'):
            self.strip_layout = 'follow'           # 节拍谱已删除: 旧存档回落跟弹
        self.cursor_size = str(P.get('cursor_size', 'standard'))      # 编辑器指针大小
        self.select_cursor = str(P.get('select_cursor', 'arrow'))    # 选择工具指针样式
        self.transcribe_tempo_scheme = str(P.get(
            'transcribe_tempo_scheme', 'fixed_auto'))  # (速度方案轮) 转录速度方案
        self.transcribe_manual_bpm = int(P.get(
            'transcribe_manual_bpm', 120))             # (速度方案轮) 手动唯一 BPM
        self.strip_font = int(P.get('strip_font', 8))  # (UI轮) 演奏谱字符大小 (pt)
        self.strip_name_font = int(P.get('strip_name_font', 7))  # (UI轮) 谱轨名字号 (独立)
        self.deck_font = int(P.get('deck_font', 8))    # (UI轮) 主窗甲板轨道名字号 (pt)
        self.score_float = None                            # (UI二轮) 演奏谱悬浮窗
        self._score_roll = None                            # 悬浮窗独立卷帘 (无编辑器时)
        self.strip_page_bars = int(P.get('strip_page_bars', 2))  # (跟随二轮) 谱翻页小节数
        self.score_row_h = int(P.get('score_row_h', 250))    # (设置轮) 悬浮谱每排高
        self.score_float_w = int(P.get('score_float_w', 1020))  # (设置轮) 悬浮谱宽
        self.score_skin = str(P.get('score_skin', 'opaque'))     # 悬浮谱皮肤 透明/不透明
        self.src_gain = int(P.get('src_gain', 100))              # 音源音量 % (0..800)
        self.sfx_volume = int(P.get('sfx_volume', 100))          # 音效音量 % (预留)
        self.engine.master_gain = self.src_gain / 100.0
        self.map_tids = None    # 映射范围·音轨 (径向选择器): None=全部轨; 集合=仅这些轨
        self.strip_label = int(P.get('strip_label', 0))          # (字符轮) 谱字符模式
        self.strip_jianpu_base = int(P.get('strip_jianpu_base', 4))  # (字符轮) 简谱基准八度
        self.range_lo = int(P.get('range_lo', 3))
        self.range_hi = int(P.get('range_hi', 5))
        self._build_ui()
        # 独占全屏：覆盖整个屏幕，隐藏任务栏
        self.showFullScreen()
        self._ui_timer = QTimer(self); self._ui_timer.setInterval(40)
        self._ui_timer.timeout.connect(self._poll_ui); self._ui_timer.start()
        self._stat_t = 0.0
        QShortcut(QKeySequence(Qt.Key_Space), self).activated.connect(self.play_or_stop)  # (26)
        QShortcut(QKeySequence('Ctrl+O'), self).activated.connect(self.open_midi)
        QShortcut(QKeySequence('Ctrl+E'), self).activated.connect(self._open_editor)
        QShortcut(QKeySequence('Ctrl+S'), self).activated.connect(self._save_midi_as)
        QShortcut(QKeySequence('Alt+F1'), self).activated.connect(
            self._toggle_play_original_shortcut)
        # (工程轮) 启动自动续开挂在真实入口 演示.py (测试不经入口, 避免串扰)
    def statusBar(self):
        """兼容垫片: 无边框主窗以底部 QLabel 显示状态文字"""
        if getattr(self, '_status_shim', None) is None:
            self._status_shim = _StatusShim(self._status_lbl)
        return self._status_shim
    # ---------- UI ----------
    def _build_ui(self):
        self.setStyleSheet(MAIN_QSS)
        central = QWidget(); self.setContent(central)
        lay = QVBoxLayout(central); lay.setContentsMargins(8, 4, 8, 6); lay.setSpacing(6)

        # ---- 顶栏三区: 菱形簇 | 歌曲+播放+BPM | 提示+窗控 ----
        top = QHBoxLayout(); top.setSpacing(14)
        cluster = DiamondCluster()
        self.b_open = cluster.b_file
        self.b_mini = cluster.b_float
        self.b_edit = cluster.b_edit
        self.b_save = cluster.b_save
        self.b_cfg = cluster.b_gear          # 齿轮 = 统一设置
        self.b_set = self.b_cfg              # 兼容旧引用
        self.b_note = self.b_cfg
        self.b_mini.setCheckable(True)
        self.b_open.tip_text = tr('打开 MIDI 文件')
        self.b_open.shortcut_text = 'Ctrl+O'
        self.b_mini.tip_text = tr('悬浮 (演奏 / 谱面)')
        self.b_mini.shortcut_text = ''
        self.b_edit.tip_text = tr('打开钢琴卷帘编辑器')
        self.b_edit.shortcut_text = 'Ctrl+E'
        self.b_save.tip_text = tr('保存 MIDI')
        self.b_save.shortcut_text = 'Ctrl+S'
        self.b_cfg.tip_text = tr('设置 (键位 / 音符 / 输出 / 语言)')
        self.b_cfg.shortcut_text = ''
        self.b_open.clicked.connect(self.open_midi)
        self.b_edit.clicked.connect(self._open_editor)
        self.b_save.clicked.connect(self._save_midi_as)
        self.b_mini.clicked.connect(self._toggle_float_flyout)
        self.b_cfg.clicked.connect(self._open_unified_settings)
        top.addWidget(cluster, 0, Qt.AlignTop)

        mid = QVBoxLayout(); mid.setSpacing(MID_ROW_GAP)
        mid.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.song_bar = SongBar()
        self.b_mute = self.song_bar.b_mute
        self.chk_out = self.song_bar.b_keys
        self.b_mute.tip_text = tr('音源静音 (不影响键盘输出)')
        self.b_mute.shortcut_text = ''
        self.chk_out.tip_text = tr('启用键盘输出')
        self.chk_out.shortcut_text = ''
        self.b_mute.clicked.connect(self._toggle_mute)
        self.chk_out.toggled.connect(self._output_toggled)
        mid.addWidget(self.song_bar, 0, Qt.AlignLeft)

        transport = QHBoxLayout(); transport.setSpacing(TRANSPORT_GAP)
        transport.setAlignment(Qt.AlignLeft)
        self.b_play = HexIconBtn('play', tip=tr('播放 / 暂停'), shortcut='Space')
        self.b_stop = HexIconBtn('stop', tip=tr('停止并回到开头'), shortcut='')
        self.b_play.clicked.connect(self.toggle_play)
        self.b_stop.clicked.connect(self.stop_all)
        self.sp_bpm = BpmBox()
        self.sp_bpm.setRange(20, 400)
        self.sp_bpm.setValue(120)
        self.sp_bpm.tip_text = tr('播放速度 (导入时读取文件 BPM)')
        self.sp_bpm.shortcut_text = ''
        self.sp_bpm.valueChanged.connect(self._bpm_changed)
        transport.addWidget(self.b_play)
        transport.addWidget(self.b_stop)
        transport.addWidget(self.sp_bpm)
        mid.addLayout(transport)
        top.addLayout(mid, 0)

        # 提示框: 顶与歌曲齐 / 底与 BPM 齐
        self.tips = TipsPanel()
        top.addWidget(self.tips, 0, Qt.AlignTop)

        # 弹性空白把窗控顶到最右边
        top.addStretch(1)

        # (分离轮) 视图切换器: 星弹 | 扒谱 — 贴窗控左侧 (用户标记位置)
        from transcribe_view import ViewSwitcher
        self.view_switcher = ViewSwitcher()
        self.view_switcher.view_changed.connect(self._switch_main_view)
        top.addWidget(self.view_switcher, 0, Qt.AlignTop)
        st = QSettings('MidiKeymap', 'PianoRollPlayer')
        v = str(st.value('ui/view', 'galaxy'))
        # 全谱主视图已删: 旧存档值回落到星弹
        self.view_switcher.set_view('galaxy' if v == 'fullscore' else v)

        # 最小化 / 关闭 — 贴主窗最右侧
        self.b_new_ui = QPushButton(tr('新界面'))
        self.b_new_ui.setObjectName('newUiButton')
        self.b_new_ui.setFocusPolicy(Qt.NoFocus)
        self.b_new_ui.setCursor(Qt.PointingHandCursor)
        self.b_new_ui.setFixedHeight(self.view_switcher.sizeHint().height())
        self.b_new_ui.setStyleSheet(
            'QPushButton{background:#10141c;color:#c8ccd4;'
            'border:1px solid #2a3442;border-radius:8px;padding:5px 14px;'
            'font-weight:600;}'
            'QPushButton:hover{background:#29333e;color:#f5f7fa;}'
            'QPushButton:pressed{background:#384553;}')
        self.b_new_ui.tip_text = tr('新界面')
        self.b_new_ui.shortcut_text = ''
        self.b_new_ui.clicked.connect(self._open_new_ui)
        top.addWidget(self.b_new_ui, 0, Qt.AlignTop)
        caps = QHBoxLayout(); caps.setSpacing(4)
        caps.setContentsMargins(0, 0, 0, 0)
        caps.setAlignment(Qt.AlignTop | Qt.AlignRight)
        self.b_wmin = ArrowCaptionBtn('min', tip=tr('最小化'))
        self.b_wclose = ArrowCaptionBtn('close', tip=tr('关闭'))
        self.b_wmin.clicked.connect(self.showMinimized)
        self.b_wclose.clicked.connect(self.close)
        caps.addWidget(self.b_wmin)
        caps.addWidget(self.b_wclose)
        top.addLayout(caps, 0)
        lay.addLayout(top)

        # 悬停提示绑定 (无悬停时提示区空白)
        self._tip_filter = TipHoverFilter(self.tips)
        for w in (self.b_open, self.b_mini, self.b_edit, self.b_save, self.b_cfg,
                  self.b_mute, self.chk_out, self.b_play, self.b_stop, self.sp_bpm,
                  self.b_new_ui, self.b_wmin, self.b_wclose):
            self._tip_filter.bind(w)

        # ---- 进度条 (设计图双细线区) ----
        self.slider = QSlider(Qt.Horizontal); self.slider.setRange(0, 1000)
        self.slider.setFocusPolicy(Qt.NoFocus)
        self.slider.setFixedHeight(14)
        self.slider.setStyleSheet(
            'QSlider::groove:horizontal { height:2px; background:#5a6270; }'
            'QSlider::handle:horizontal { width:10px; height:10px; margin:-4px 0;'
            ' background:#e8eef6; border-radius:1px; }'
            'QSlider::sub-page:horizontal { background:#9aa3b0; }')
        self.slider.sliderPressed.connect(self._slider_pressed)
        self.slider.sliderMoved.connect(self._slider_moved)
        self.slider.sliderReleased.connect(self._slider_released)
        self.time_lbl = QLabel('0:00.0 / 0:00.0'); self.time_lbl.setMinimumWidth(130)
        self.bpm_lbl = QLabel(''); self.bpm_lbl.setStyleSheet('color:#e8b05a;')
        self.stat_lbl = QLabel(''); self.stat_lbl.setStyleSheet('color:#e8b05a;')
        self._status_lbl = QLabel('')
        self._status_lbl.setStyleSheet('color:#8a94a2; padding-left:2px;')
        rowp = QHBoxLayout(); rowp.setSpacing(8)
        rowp.addWidget(self.time_lbl); rowp.addWidget(self.slider, 1)
        rowp.addWidget(self.bpm_lbl)
        lay.addLayout(rowp)
        # 统计行保留但弱化 (原状态提示改由右侧悬停提示承担)
        rowi = QHBoxLayout(); rowi.setSpacing(8)
        rowi.addWidget(self.stat_lbl, 1); rowi.addWidget(self._status_lbl)
        lay.addLayout(rowi)

        # ---- 中央: Lightfall 背景 + 透明甲板 ----
        self.deck = TrackDeck(self)
        from snow_canvas import SnowCanvas
        self.canvas = SnowCanvas()
        overlay = QWidget()
        overlay.setAttribute(Qt.WA_TranslucentBackground, True)
        overlay.setStyleSheet('background: transparent;')
        overlay.setMouseTracking(True)
        ov = QVBoxLayout(overlay)
        ov.setContentsMargins(6, 4, 6, 10); ov.setSpacing(4)
        ov.addWidget(self.deck, 1)
        stack = QStackedLayout()
        stack.setStackingMode(QStackedLayout.StackAll)
        stack.setContentsMargins(0, 0, 0, 0)
        stack.addWidget(self.canvas)
        stack.addWidget(overlay)
        overlay.installEventFilter(self)
        self.deck.installEventFilter(self)
        self.deck.setMouseTracking(True)
        self._overlay_ref = overlay
        self._galaxy_mouse_sources = (overlay, self.deck)
        central_holder = QWidget(); central_holder.setLayout(stack)
        lay.addWidget(central_holder, 1)

        # ---- (分离轮) 扒谱专用视图 (加入堆叠第 3 层, 切换器控制显隐) ----
        from transcribe_view import TranscribeView, ViewSwitcher
        self.transcribe_view = TranscribeView(self)
        stack.addWidget(self.transcribe_view)
        self.transcribe_view.hide()

        # ---- (全谱轮已删) 内嵌全谱面板移除, 全谱=悬浮演奏谱多排 ----
        self._main_view = 'galaxy'
        self.setFixedSize(1280, 860)
        self.b_mute.setChecked(self.engine.muted)
        self._apply_range_hl()
        self._refresh_song_title()
        self._init_float_flyout()

    def _open_new_ui(self):
        if self._new_ui_window is not None and self._new_ui_window.isVisible():
            self._new_ui_window.raise_()
            self._new_ui_window.activateWindow()
            return
        try:
            if self._new_ui_window is None:
                from new_interface import NewInterfaceWindow
                window = NewInterfaceWindow(self)
                window.return_requested.connect(self._return_to_legacy_ui)
                self._new_ui_window = window
            self._legacy_window_state = self.windowState()
            window = self._new_ui_window
            window.showFullScreen()
            window.raise_()
            window.activateWindow()
        except Exception as exc:
            self.statusBar().showMessage(tr('新界面') + ': ' + str(exc), 5000)
            return
        self.hide()

    def _return_to_legacy_ui(self):
        state = self._legacy_window_state
        if state is not None:
            self.setWindowState(state)
        self.show()
        self.raise_()
        self.activateWindow()
        if self._new_ui_window is not None:
            self._new_ui_window.hide()

    def _refresh_song_title(self):
        """歌曲条: 显示已导入 MIDI 文件名"""
        name = os.path.basename(self._midi_path) if self._midi_path else ''
        if hasattr(self, 'song_bar'):
            self.song_bar.set_song_name(name)

    def _switch_main_view(self, view):
        """(分离轮) 星弹 ↔ 扒谱 两段视图切换"""
        if view == self._main_view:
            return
        self._main_view = view
        galaxy = view == 'galaxy'
        transcribe = view == 'transcribe'
        self.canvas.setVisible(galaxy)
        self._overlay_ref.setVisible(galaxy)
        self.transcribe_view.setVisible(transcribe)
        QSettings('MidiKeymap', 'PianoRollPlayer').setValue('ui/view', view)

    def _open_unified_settings(self):
        """齿轮: 统一设置 (键位/音符/输出语言)"""
        dlg = UnifiedSettingsDialog(self)
        if dlg.exec() != QDialog.Accepted:
            return
        pk, pn, pa = dlg.page_keys, dlg.page_note, dlg.page_app
        # ---- 键位/播放页 ----
        self.row_keys = pk.row_keys
        self.oct_assign = pk.oct_assign
        self.overlap_mode = pk.overlap_mode
        self.piano_mode = pk.piano_mode
        self.map_scope = pk.map_scope
        self.min_hold = pk.min_hold
        self.min_gap = pk.min_gap
        self.tap = pk.tap
        self.start_delay = pk.start_delay
        self.range_hl_on = pk.range_hl_on
        self.range_lo = pk.range_lo
        self.range_hi = pk.range_hi
        self.strip_font = pk.strip_font
        self.strip_name_font = pk.strip_name_font
        self.deck_font = pk.deck_font
        self.strip_page_bars = pk.strip_page_bars
        self.score_row_h = pk.score_row_h
        self.score_float_w = pk.score_float_w
        self.strip_label = pk.strip_label
        self.strip_jianpu_base = pk.strip_jianpu_base
        self.cursor_size = pk.cursor_size
        self.select_cursor = pk.select_cursor
        self._save_cfg()
        self._apply_cursor_prefs()
        self._apply_range_hl()
        self._rebuild(keep_view=True)
        self._sync_track_ui()
        for sf in (getattr(self, 'score_strip', None),
                   getattr(getattr(self, 'score_float', None), 'strip', None)):
            if sf is not None:
                sf.update()
        flt = getattr(self, 'score_float', None)
        if flt is not None:
            flt.refresh_page_fit()   # (加宽轮) 每页小节数变化 → 悬浮窗宽度重算
        if self.thread is not None and self.thread.isRunning():
            pnist = self.thread.pianist
            pnist.mode = self.piano_mode
            pnist.min_hold = self.min_hold
            pnist.min_gap = self.min_gap
            pnist.tap = self.tap
        # ---- 音符页 ----
        self.note_label_mode = pn.mode
        self.note_label_custom = pn.custom
        store.save_note_label(self.note_label_mode, self.note_label_custom)
        self._apply_note_label()
        # ---- 输出/语言页 ----
        if pa.lang != self.current_lang:
            self.current_lang = pa.lang
            i18n.set_lang(pa.lang)
            store.save_lang(pa.lang)
            editor = self.editor_win
            if editor is not None:
                geometry = editor.saveGeometry()
                page = editor.pages.currentIndex()
                editor.close()
                if self.editor_win is None:
                    self._open_editor()
                    if self.editor_win is not None:
                        self.editor_win.restoreGeometry(geometry)
                        self.ed_sess._set_workspace_page(page)
            self.retranslate_ui()
        if (pa.driver, pa.device) != (self.audio_driver, self.audio_device):
            self.audio_driver, self.audio_device = pa.driver, pa.device
            store.save_audio(self.audio_driver, self.audio_device)
            self._apply_audio_device()
        if pa.transcribe_route != self.transcribe_route:
            self.transcribe_route = pa.transcribe_route
            store.save_transcribe_cfg(self.transcribe_route)
        self.statusBar().showMessage(tr('设置已应用'), 3000)
    # ---------- 悬浮播放条 + 演奏谱 (合并到「悬浮」) ----------
    def _toggle_float_flyout(self):
        """悬浮按钮点击 → 弹出/收回「演奏」/「谱面」子菱形"""
        if getattr(self, '_fly_pos', None) is not None \
                and self._fly_pos.isVisible():
            self._hide_float_flyout()
        else:
            self._show_float_flyout()

    def _flyout_centers(self):
        """悬浮按钮中心 (主窗坐标系) → 左右子菱形的目标左上角坐标"""
        c = self.b_mini.mapTo(self, self.b_mini.rect().center())
        w, h = self._fly_pos.width(), self._fly_pos.height()
        gap = 62                                   # 悬浮中心 → 子菱形中心
        ly, ry = c.y() - h // 2, c.y() - h // 2
        return (c.x() - gap - w // 2, ly), (c.x() + gap - w // 2, ry), (c.x(), c.y())

    def _show_float_flyout(self, animate=True):
        """子菱形从悬浮正后方滑向左右两侧 + 淡入 (离屏测试传 animate=False)"""
        (lx, ly), (rx, ry), (cx, cy) = self._flyout_centers()
        w, h = self._fly_pos.width(), self._fly_pos.height()
        self._fly_anims = []
        for b, (tx, ty) in ((self._fly_pos, (lx, ly)),
                            (self._fly_score, (rx, ry))):
            fx = QGraphicsOpacityEffect(b)
            b.setGraphicsEffect(fx)
            b.move(cx - w // 2, cy - h // 2)       # 起点: 悬浮正后方
            b.raise_()
            b.show()
            if not animate:
                b.move(tx, ty)
                fx.setOpacity(1.0)
                continue
            a = QPropertyAnimation(b, b'pos', self)
            a.setDuration(150)
            a.setStartValue(QPoint(cx - w // 2, cy - h // 2))
            a.setEndValue(QPoint(tx, ty))
            a.setEasingCurve(QEasingCurve.OutCubic)
            o = QPropertyAnimation(fx, b'opacity', self)
            o.setDuration(150)
            o.setStartValue(0.0); o.setEndValue(1.0)
            o.setEasingCurve(QEasingCurve.OutCubic)
            for anim in (a, o):
                anim.start(QAbstractAnimation.DeleteWhenStopped)
                self._fly_anims.append(anim)
        self.b_mini.setChecked(True)

    def _hide_float_flyout(self):
        self._fly_pos.hide()
        self._fly_score.hide()
        self.b_mini.setChecked(False)

    def mousePressEvent(self, ev):
        # 点击主窗其他区域 → 收回 flyout 子按钮 (按钮自身点击不会传到这里)
        fp = getattr(self, '_fly_pos', None)
        if fp is not None and fp.isVisible():
            self._hide_float_flyout()
        super().mousePressEvent(ev)

    def _init_float_flyout(self):
        """创建演奏/谱面两个弹出子菱形 (较小的原按键图形, 悬浮按钮左右滑出)"""
        self._fly_pos = DiamondBtn('演奏', tip='自动演奏悬浮窗 (播放条 + BPM)',
                                   parent=self)
        self._fly_score = DiamondBtn('谱面', tip='悬浮演奏谱', parent=self)
        for b in (self._fly_pos, self._fly_score):
            b.setFixedSize(56, 56)                 # 比按键簇 (72) 小一档
            b.hide()
            b.clicked.connect(self._flyout_pick)
        self._fly_anims = []

    def _flyout_pick(self):
        """子按钮回调: 演奏 → MiniBar; 谱面 → ScoreFloat"""
        sender = self.sender()
        is_pos = sender is self._fly_pos
        self._hide_float_flyout()
        if is_pos:
            if getattr(self, 'mini', None) is not None \
                    and self.mini.isVisible():
                self._toggle_mini(False)
            else:
                self._toggle_mini(True)
        else:
            sf = getattr(self, 'score_float', None)
            if sf is not None and sf.isVisible():
                sf.hide()
                self.b_score_float.setChecked(False) \
                    if hasattr(self, 'b_score_float') else None
            else:
                self._toggle_score_float(True)

    def _toggle_mini(self, on):
        if on:
            if self.mini is None:
                self.mini = MiniBar(self)
                geom = self._params.get('mini_geom')
                if isinstance(geom, QByteArray):
                    self.mini.restoreGeometry(geom)
                else:
                    self.mini.move(self.x() + self.width() - self.mini.width() - 24,
                                   self.y() + 60)
            self.mini.show(); self.mini.sync()
            # (分离轮) 演奏/谱面解耦: MiniBar 开启不再自动联动 ScoreFloat
            self.statusBar().showMessage(
                tr('自动演奏悬浮窗已开启 · 置顶可拖'), 4000)
        else:
            if self.mini is not None and self.mini.isVisible():
                self.mini.hide()

    def _mini_hidden(self):
        """MiniBar 关闭 (解耦轮): 不再联动谱面, 仅保留钩子"""
    def _score_float_hidden(self):
        """ScoreFloat 关闭 (解耦轮): 不再联动演奏条, 仅保留钩子"""
    def _toggle_score_float(self, on):
        """演奏谱悬浮窗 (并入「悬浮」): 编辑器开绑编辑卷帘; 否则绑独立卷帘模型"""
        if on:
            if getattr(self, 'score_float', None) is None:
                roll = self.edit_roll
                if roll is None:
                    roll = self._score_roll = self._make_score_roll()
                self.score_float = ScoreFloat(roll, self)
                roll.viewChanged.connect(self.score_float.strip.on_roll_view_changed)
                self._score_float_lanes()
                self.score_float.move(
                    self.x() + self.width() - self.score_float.width() - 16,
                    self.y() + 60)
            if self.score_float is not None and self.tmap is not None:
                self.score_float.show(); self.score_float.raise_()
                self.score_float.refresh_meta()
                self._float_avoid_editor_ruler()   # (避让轮) 不遮主卷帘标尺行
        elif getattr(self, 'score_float', None) is not None:
            self.score_float.hide()
    def _make_score_roll(self):
        """悬浮窗独立卷帘视图模型 (不显示): 承载 ppb/视野/指针供谱面页驱动"""
        roll = PianoRoll()
        roll.setAttribute(Qt.WA_TransparentForMouseEvents)
        if self.tmap is not None:
            roll.set_data(self.tmap, self.raw_notes, self.bar_ticks,
                          keep_view=True, tsig_map=self.tsig_map)
        roll.set_track_colors({t.tid: track_hex(t.tid) for t in self.tracks})
        return roll
    def _set_strip_layout(self, mode):
        """(排版轮) 演奏谱排版: follow=跟弹(原始 tick)
           bars=小节谱(列布局: 起点并集分列/等距列宽/按小节翻页);
           双实例推送 + 按钮/设置文案 + 持久化 (节拍谱已删除, 旧值回落跟弹)"""
        mode = mode if mode in ('follow', 'bars') else 'follow'
        self.strip_layout = mode
        self._save_cfg()
        name = {'follow': tr('排版: 跟弹'), 'bars': tr('排版: 小节谱')}[mode]
        for b in (getattr(self, 'b_strip_layout', None),
                  getattr(getattr(self, 'score_float', None), 'b_layout', None)):
            if b is None:
                continue
            try:
                b.setText(name)
            except RuntimeError:
                pass                                  # 编辑器已关闭, 控件已销毁
        for sf in (getattr(self, 'score_strip', None),
                   getattr(getattr(self, 'score_float', None), 'strip', None)):
            if sf is not None:
                sf.update()                            # push 重算行数据
        for st in (getattr(self, 'score_strip', None),
                   getattr(getattr(self, 'score_float', None), 'strip', None)):
            if st is not None and st.bridge._bars_active():
                st.on_roll_view_changed()              # 列布局: 视野重锚定到页首

    def _apply_beat_analysis(self, res):
        """(四期+优化) 分析结果写入工程: 拍点 → 变速段检测 → 段落级写入
           (音符按段重缩放, 绝对秒保持 = 与源音频严格同步)。
           无拍点数据时回退单一 BPM 写入; 拍号仅在 BeatNet 下拍证据时写入。
           (速度方案轮) 按速度方案分发: fixed_auto = 检测 BPM 单段重缩放;
           fixed_manual 在转录完成时已应用, 此处不再覆盖"""
        import beat_analysis as _ba
        if getattr(self, 'transcribe_tempo_scheme', '') == 'fixed_manual':
            return                                  # 手动 BPM 已在转录完成时应用
        beats = res.get('beats') or []
        segs = res.get('segments') or []
        if not segs and len(beats) >= 4:
            import beat_analysis as _ba
            segs = _ba.tempo_segments(beats)
        engine = res.get('engine', '')
        n_beats = len(beats)
        if getattr(self, 'transcribe_tempo_scheme', '') == 'fixed_auto':
            # (速度方案轮) 自动检测唯一 BPM: 单段重缩放 (绝对秒保持)
            bpm = float(res.get('bpm', 0) or 0)
            if bpm < 20 or bpm > 400:
                self.statusBar().showMessage(
                    tr('速度方案 fixed_auto: 检测 BPM 越界, 未应用'), 5000)
                return
            self._apply_tempo_segments(
                [{'t0': 0.0, 't1': None, 'bpm': bpm}])
            self._set_key_label(str(res.get('key', '1=C')))
            self.statusBar().showMessage(
                tr('速度方案 fixed_auto 已写入: 唯一 BPM={b:.1f} (音符已对齐)',
                   b=bpm), 5000)
            return
        if len(segs) >= 2:
            # 段落级: 每段 BPM; 拍号段 = BeatNet 下拍证据 (librosa 无下拍 → 沿用现拍号)
            meter_segs = None
            if engine == 'beatnet':
                meter_segs = _ba.meter_segments_from_beats(beats)
            self._apply_tempo_segments(segs, meter_segs)
            self._set_key_label(str(res.get('key', '1=C')))
            n_show = meter_segs[0][1] if meter_segs else int(
                res.get('num', 4))
            self.statusBar().showMessage(
                tr('节拍分析已写入: BPM={b:.0f} · 变速 {c} 段 · 拍号 {n}/4 ({e})',
                   b=segs[0]['bpm'], c=len(segs), n=n_show,
                   e='BeatNet' if engine == 'beatnet' else 'librosa'), 6000)
            return
        # 单段回退 (adaptive): 单段重缩放 (绝对秒保持) —— 修复旧"只改 tick0 速度
        # 不重缩放音符"的时间失真
        bpm = float(res.get('bpm', 0) or 0)
        if bpm < 20 or bpm > 400:
            return
        self._apply_tempo_segments([{'t0': 0.0, 't1': None, 'bpm': bpm}])
        if engine == 'beatnet':
            self.tsig_map.set_events([(0, int(res.get('num', 4)),
                                       int(res.get('den', 4)))])
        self._set_key_label(str(res.get('key', '1=C')))
        self.statusBar().showMessage(
            tr('节拍分析已写入: BPM={b:.0f} · {n}/{d} · 1=C ({e})',
               b=bpm, n=int(res.get('num', 4)), d=int(res.get('den', 4)),
               e='BeatNet' if engine == 'beatnet' else 'librosa'), 6000)

    def _apply_tempo_segments(self, segs, meter_segs=None):
        """(四期优化) 段落级变速写入: 段边界 sec → 旧 tick 空间 → 新速度事件;
           音符 tick 按段线性重缩放 (绝对秒保持 = 与源音频同步);
           TsigMap 段重排 (有下拍证据的段写入拍号); 空闲期无兜底推送由 rebuild 兜底"""
        old = self.tmap
        tpb = old.tpb
        # 段边界 (sec) → 旧 tick; 每段新空间速率
        bounds_old = [old.sec2tick(max(0.0, s['t0'])) for s in segs]
        bounds_new = [0]
        rates_new = []
        for k, s in enumerate(segs):
            rate = tpb * s['bpm'] / 60.0
            rates_new.append(rate)
            if k + 1 < len(segs):
                bounds_new.append(bounds_new[-1]
                                  + (segs[k + 1]['t0'] - s['t0']) * rate)
        # 新 TempoMap: 每段一条速度事件
        from midi_data import TempoMap as _TM
        new_map = _TM(tpb, [(bounds_new[k], 60e6 / segs[k]['bpm'])
                            for k in range(len(segs))])
        # 音符重缩放: 逐音符按所在段速率映射 (绝对秒不变)
        secs_s = [old.tick2sec(int(nt.start_tick)) for nt in self.raw_notes]
        secs_e = [old.tick2sec(int(nt.end_tick)) for nt in self.raw_notes]
        for i, nt in enumerate(self.raw_notes):
            sec_s = secs_s[i]
            si = len(segs) - 1
            for k in range(len(segs) - 1):
                if sec_s < segs[k + 1]['t0']:
                    si = k; break
            nt.start_tick = int(round(bounds_new[si]
                                      + (sec_s - segs[si]['t0'])
                                      * rates_new[si]))
            nt.end_tick = int(round(bounds_new[si]
                                    + (secs_e[i] - segs[si]['t0'])
                                    * rates_new[si]))
        # TsigMap 段重排 (新 tick 空间): 有下拍证据的段写拍号, 否则沿用
        new_tsig = []
        last = (4, 4)
        for k, s in enumerate(segs):
            sec0 = s['t0']
            sec1 = segs[k + 1]['t0'] if k + 1 < len(segs) else float('inf')
            mt = None
            for sec_m, num_m in (meter_segs or []):
                if sec0 - 0.5 <= sec_m < min(sec1, sec0 + tpb * 4):
                    mt = (num_m, 4)
                    break
            if mt is None and new_tsig:
                mt = new_tsig[-1][1:]                 # 沿用前段 (拍号持续到变更)
            if mt is None:
                mt = last
            new_tsig.append((int(round(bounds_new[k])), mt[0], mt[1]))
        self.tsig_map = __import__('midi_data').TsigMap(tpb, new_tsig)
        self.tsig = self.tsig_map.at(0)
        self.bar_ticks = self.tsig_map.bar_ticks_at(0)
        self.tmap = new_map
        self._rebuild(keep_view=True)

    def _set_key_label(self, v):
        """(标记轮) 调性标注: 存档 + 悬浮谱左上角同步 (编辑器右键标尺调用)"""
        self.key_label = str(v)
        self._save_cfg()
        sf = getattr(self, 'score_float', None)
        if sf is not None:
            sf.set_key_label(self.key_label)
        er = getattr(self, 'edit_roll', None)
        if er is not None and getattr(er, 'tiles', None) is not None:
            er.tiles.clear()                       # 标尺标签重绘 (调性文本变更)
            er.update()
        project_session.save(self)                 # (工程轮) 调性标注入工程记忆

    def _score_float_lanes(self):
        """悬浮窗车道: 编辑器开 = 编辑器车道选择; 未开 = 全部音轨"""
        sf = getattr(self, 'score_float', None)
        if sf is None: return
        es = getattr(self, 'ed_sess', None)
        if self.edit_roll is not None and es is not None:
            sf.strip.set_lanes(es._lane_tids())
        else:
            sf.strip.set_lanes([t.tid for t in self.tracks])
    def _score_float_rebind(self):
        """编辑器会话结束: 悬浮窗换绑独立卷帘"""
        sf = getattr(self, 'score_float', None)
        if sf is None: return
        old_roll = sf.strip.roll
        try: old_roll.viewChanged.disconnect(sf.strip.on_roll_view_changed)
        except Exception: pass
        roll = self._make_score_roll()
        self._score_roll = roll
        sf.strip.roll = roll
        roll.viewChanged.connect(sf.strip.on_roll_view_changed)
        self._score_float_lanes()
        sf.strip.update()
    def _set_time_signature(self, num, den):
        """(UI二轮) 修改拍号: bar_ticks 重算 + 全量重建 (另存 MIDI 写回)"""
        if self.tmap is None: return
        self.tsig = (int(num), int(den))
        self.bar_ticks = float(self.tmap.tpb * 4 * int(num) / int(den))
        self.tsig_map.set_events([(0, int(num), int(den))])   # 全曲拍号 = 单段
        self._rebuild(keep_view=True)
        er = getattr(self, 'edit_roll', None)   # (二期收尾) 编辑卷帘同步段宽/绑定
        if er is not None:                      # (version 自增 → 瓦片自动重烘)
            er.bar_ticks = self.bar_ticks
            er.tsig_map = self.tsig_map
            er.update()
        self._score_float_refresh_data()
    def _score_float_refresh_data(self):
        """编辑数据变化后刷新悬浮窗独立卷帘 (换绑/重建后保持谱面同步)"""
        sf = getattr(self, 'score_float', None)
        if sf is None or self.tmap is None: return
        if sf.strip.roll is not self.edit_roll:
            sf.strip.roll.set_data(self.tmap, self.raw_notes, self.bar_ticks,
                                   keep_view=True, tsig_map=self.tsig_map)
            sf.strip.roll.set_track_colors(
                {t.tid: track_hex(t.tid) for t in self.tracks})
        self._score_float_lanes()
    # ---- (P2-D) playback: see playback_controller.PlaybackController (stable iface) ----
    def play_or_stop(self): self.pb_ctrl.play_or_stop()
    def toggle_play(self): self.pb_ctrl.toggle_play()
    def _make_pianist(self): return self.pb_ctrl._make_pianist()
    def _start_play(self): self.pb_ctrl._start_play()
    def _cd_tick(self): self.pb_ctrl._cd_tick()
    def _launch_thread(self): self.pb_ctrl._launch_thread()
    def _on_thread_done(self): self.pb_ctrl._on_thread_done()
    def _stop_playback(self): self.pb_ctrl._stop_playback()
    def stop_all(self): self.pb_ctrl.stop_all()
    def _speed_factor(self): return self.pb_ctrl._speed_factor()
    def _bpm_changed(self, _v): self.pb_ctrl._bpm_changed(_v)
    def _is_playing(self): return self.pb_ctrl._is_playing()
    def _seek_visual(self, sec): self.pb_ctrl._seek_visual(sec)
    def _seek_real(self, sec): self.pb_ctrl._seek_real(sec)
    def _scrub_begin(self): self.pb_ctrl._scrub_begin()
    def _scrub_end(self, sec): self.pb_ctrl._scrub_end(sec)
    def _slider_pressed(self): self.pb_ctrl._slider_pressed()
    def _slider_moved(self, v): self.pb_ctrl._slider_moved(v)
    def _slider_released(self): self.pb_ctrl._slider_released()
    def _preview(self, note, on): self.pb_ctrl._preview(note, on)
    # ---- (P2-D) tracks: see track_controller.TrackController (stable iface) ----
    def _range_notes(self): return self.trk_ctrl._range_notes()
    def _apply_range_hl(self): self.trk_ctrl._apply_range_hl()
    def _sound_tids(self): return self.trk_ctrl._sound_tids()
    def _sync_track_ui(self): self.trk_ctrl._sync_track_ui()
    def _on_track_toggle(self, tid, kind): self.trk_ctrl._on_track_toggle(tid, kind)
    def _on_track_activate(self, tid): self.trk_ctrl._on_track_activate(tid)
    def _track_add(self): self.trk_ctrl._track_add()
    def _track_remove(self, tid): self.trk_ctrl._track_remove(tid)
    def _on_track_rename(self, tid, name): self.trk_ctrl._on_track_rename(tid, name)
    def _on_track_sound(self, tid): self.trk_ctrl._on_track_sound(tid)
    def _apply_track_font(self, tid, path, preset, gain=1.0):
        self.trk_ctrl._apply_track_font(tid, path, preset, gain=gain)
    # ---- (P1-C) editor lifecycle: see editor_session.EditorSessionController ----
    def _open_editor(self):
        self.ed_sess._open_editor()
        self._float_avoid_editor_ruler()

    def _set_meter_segment(self, tick, num, den):
        """(二期) 右键节拍标记: 从 tick 所在小节起变更拍号段 (后段保留),
           全量重建联动 (卷帘网格/演奏谱/变速 Lane/悬浮谱/状态区)"""
        self.tsig_map.set_segment(int(tick), int(num), int(den))
        self._rebuild(keep_view=True)
        self.statusBar().showMessage(
            tr('节拍已标记 {n}/{d} (自该小节起) — 拍号暂不入撤销栈', 5000)
            if False else tr('节拍已标记 {n}/{d} (自该小节起)',
                             n=int(num), d=int(den)), 5000)

    def _float_avoid_editor_ruler(self):
        """(避让轮) 悬浮谱不得遮挡主卷帘标尺行: 否则标尺左键/右键点击
           全部落在悬浮谱窗口上 (该窗口鼠标只读), 标尺交互整体失灵"""
        ed = getattr(self, 'edit_roll', None)
        sf = getattr(self, 'score_float', None)
        if ed is None or sf is None or not sf.isVisible():
            return
        tl = ed.mapToGlobal(QPoint(0, 0))
        ruler = QRect(tl.x(), tl.y(), ed.width(), 28)
        fr = sf.frameGeometry()
        if fr.intersects(ruler):
            sf.move(fr.x(), ruler.bottom() + 8)
    def _toggle_play_original_shortcut(self):
        self.ed_sess._shortcut_toggle_play_original()
    def _set_editor_snap(self, v): self.ed_sess._set_editor_snap(v)
    def _sync_snap_btn(self): self.ed_sess._sync_snap_btn()
    def _confirm_discard(self): return self.ed_sess._confirm_discard()
    def _discard_edits(self): self.ed_sess._discard_edits()
    def _end_edit_session(self, rebuild=True): self.ed_sess._end_edit_session(rebuild)
    def _editor_commit(self): self.ed_sess._editor_commit()
    def _edit_undo(self): self.ed_sess._edit_undo()
    def _analyze_selection(self): self.ed_sess._analyze_selection()
    def _apply_selection_transpose(self, sel_nids, off): self.ed_sess._apply_selection_transpose(sel_nids, off)
    def _on_edit_notify(self, sess):
        w = self.editor_win
        if w is not None:                 # (30②) 标题脏标记 *
            w.setWindowTitle(tr(EDITOR_TITLE) + (" *" if sess.dirty else ""))
        if self.edit_roll is not None:
            self.edit_roll.set_status(
                tr('撤销 {a}', a=len(sess.undo_stack))
                + (tr('  · 有未保存改动') if sess.dirty else tr('  · 无未保存改动')))
    # ---------- 配置持久化 ----------
    def _save_cfg(self):
        store.save_settings(self.row_keys, self.oct_assign, {
            'transpose': self.trans,
            'mode': self.piano_mode,
            'overlap': self.overlap_mode,
            'map_scope': self.map_scope,
            'min_hold': int(round(self.min_hold * 1000)),
            'min_gap': int(round(self.min_gap * 1000)),
            'tap': int(round(self.tap * 1000)),
            'delay': self.start_delay,
            'range_hl': self.range_hl_on,
            'follow': self.follow_on,
            'scale_bpm_link': self.scale_bpm_link,
            'beat_auto': self.beat_auto,
            'key_label': self.key_label,
            'strip_layout': self.strip_layout,
            'cursor_size': self.cursor_size,
            'select_cursor': self.select_cursor,
            'transcribe_tempo_scheme': self.transcribe_tempo_scheme,
            'transcribe_manual_bpm': self.transcribe_manual_bpm,
            'strip_font': self.strip_font,
            'strip_name_font': self.strip_name_font,
            'deck_font': self.deck_font,
            'strip_page_bars': self.strip_page_bars,
            'score_row_h': self.score_row_h,
            'score_float_w': self.score_float_w,
            'strip_label': self.strip_label,
            'strip_jianpu_base': self.strip_jianpu_base,
            'score_skin': getattr(self, 'score_skin', 'opaque'),
            'src_gain': int(getattr(self, 'src_gain', 100)),
            'sfx_volume': int(getattr(self, 'sfx_volume', 100)),
            'range_lo': self.range_lo,
            'range_hi': self.range_hi,
        })
    def _set_trans(self, v):
        """播放层移调已锁死 0 (输出只按卷帘实际音符); 保留接口, 任何值都归零"""
        self.trans = 0
    def _output_toggled(self, on):
        if on and IS_WIN:
            try:
                if not ctypes.windll.shell32.IsUserAnAdmin():
                    QMessageBox.warning(self, tr("权限提示"),
                        tr('当前不是管理员权限。\n若游戏以管理员运行, 按键将无法送达,\n'
                           '请以管理员身份重启本程序。'))
            except Exception:
                pass
        if on and not IS_WIN:
            QMessageBox.warning(self, tr("不支持"),
                                tr('键盘输出仅支持 Windows (SendInput)'))
            self.chk_out.setChecked(False)
        self._rebuild(keep_view=True)
    # ---------- 播放控制 ----------
    def _poll_ui(self):
        if self.mini is not None and self.mini.isVisible():
            self.mini.sync()
        t = self.thread
        playing = t is not None and t.isRunning() and not t.paused
        if hasattr(self.b_play, 'set_playing'):
            self.b_play.set_playing(playing)
        if t is not None and t.isRunning():
            self.cur_sec = min(t.cur_music, self.total_sec)
            # 编辑器: 按 nid 匹配高亮 (raw层与解析层副本 nid 一致, 见 _rebuild)
            ed_act_changed = False
            if self.edit_roll is not None and self.editor_win is not None \
                    and self.editor_win.isVisible():
                # (高亮修复轮) 变更检测在 sounding 层; 高亮集合解析回原始音符
                # (按 nid) —— 移调副本的音高行 ≠ 卷帘可见音符格, 高亮必须
                # 吸附在可见格上 (移调只改变实际按键的音高, 不挪谱面高亮)
                ed_act_changed = t.sounding != getattr(
                    self, '_edit_last_snd', None)
                self._edit_last_snd = t.sounding
                if ed_act_changed:
                    raw_by = {nt.nid: nt for nt in self.raw_notes}
                    self.edit_roll.active_notes = frozenset(
                        raw_by.get(n.nid, n) for n in t.sounding)
            self._update_playhead(self.cur_sec, force_full=ed_act_changed)
            now = time.monotonic()
            if now - self._stat_t > 0.5:
                self._stat_t = now
                self.stat_lbl.setText(self._stat_full() + '  |  ' +
                    tr('整形: 推迟 {a} 丢弃 {b}',
                       a=t.pianist.deferred, b=t.pianist.dropped))
    def _update_playhead(self, cur, force_full=False):
        if self.tmap is None: return
        ph = self.tmap.sec2tick(cur)
        # (UI二轮) 悬浮窗播放静默: 悬浮窗可见+播放中 → 卷帘/甲板/概览停渲染省性能
        sf = getattr(self, 'score_float', None)
        silent = (sf is not None and sf.isVisible() and self._is_playing())
        if sf is not None and sf.isVisible():
            sf.strip.roll.playhead_tick = ph        # 悬浮窗卷帘数据源 (页驱动/蓝线)
        if not silent:
            self.deck.set_playhead(ph, self.total_tick_display)   # (P 轮) 甲板播放头
        # 编辑器窗口指针同步 (数据照常供横幅页驱动; 渲染按静默门控)
        if self.edit_roll is not None and self.editor_win is not None \
                and self.editor_win.isVisible():
            self.edit_roll.render_silent = silent   # (UI二轮) 静默期预取也停
            # (R 轮) 拖动中指针预览: 不被 40ms 轮询覆盖
            if not getattr(self.edit_roll, '_ph_preview', False):
                self.edit_roll.playhead_tick = ph
                if not silent:
                    self.edit_roll.update_playhead_region(full=force_full)  # (P 轮) 窄带
            # (统一播放跟随 2026-09-08) "跟随"开关 + 播放中: 卷帘锚定 30% 处随
            # 指针平移 (set_view_tick → viewChanged 带动横幅一起动; 瓦片缓存命中
            # 零重绘; 手势拖拽期间不抢占; 悬浮窗静默期停 (省渲染, 卷帘冻结);
            # 暂停时 _is_playing=False 自由浏览)
            if (getattr(self, 'follow_on', False) and self._is_playing()
                    and not silent and self.edit_roll._drag is None
                    and not getattr(self.edit_roll, '_ph_preview', False)):
                anchor_px = (self.edit_roll.width() - KB_W) * FOLLOW_X_FRAC
                self.edit_roll.set_view_tick(
                    max(0.0, ph - anchor_px / self.edit_roll.ppb * self.tmap.tpb))
        if not silent:
            if getattr(self, 'edit_minimap', None) is not None \
                    and self.editor_win is not None and self.editor_win.isVisible():
                self.edit_minimap.update()              # 概览条播放头同步
            if getattr(self, 'tempo_lane', None) is not None \
                    and self.editor_win is not None and self.editor_win.isVisible():
                self.tempo_lane.update()                # (Q 轮) lanes 播放头同步
        if getattr(self, 'score_strip', None) is not None \
                and self.editor_win is not None and self.editor_win.isVisible():
            self.score_strip.sync_playhead()        # 横幅: 指针/蓝线侵蚀同步
        if sf is not None and sf.isVisible():
            sf.strip.sync_playhead()                # 悬浮窗: 指针/蓝线侵蚀 + 翻页
            sf.refresh_meta(ph)                     # 左上角 BPM/节奏 (值变化才重绘)
            sf.sync_progress(cur, self.total_sec, self._is_playing())
        if not self._dragging:
            self.slider.blockSignals(True)
            self.slider.setValue(int(cur / self.total_sec * 1000) if self.total_sec > 0 else 0)
            self.slider.blockSignals(False)
        self.time_lbl.setText(f"{fmt_sec(cur)} / {fmt_sec(self.total_sec)}")
        self.bpm_lbl.setText(f"♩={self.tmap.bpm_at_tick(ph) * self._speed_factor():.0f}")
    # ---------- 文件 ----------
    def open_midi(self, parent=None):
        path, _ = QFileDialog.getOpenFileName(parent or self, tr("打开 MIDI"), self._last_dir,
                                              "MIDI (*.mid *.midi);;All (*)")
        return self._open_path(path) if path else False
    def _open_path(self, path):
        if self.edit_session is not None and not self._confirm_discard():
            return False                            # 取消: 保留编辑现场
        project_session.save(self)                  # (工程轮) 切歌前刷写当前工程
        try:
            tmap, notes, bar_ticks, tsig, tracks, tsig_events = load_midi(path)
        except Exception as e:
            QMessageBox.critical(self.editor_win or self, tr("错误"),
                                 tr('MIDI 解析失败:\n{e}', e=e))
            return False
        self._stop_playback()
        if self.edit_session is not None:           # 已确认过: 结束旧编辑会话
            self._discard_edits()
            self._end_edit_session(rebuild=False)   # 马上载入新数据, 无需重复重建
        self._last_dir = os.path.dirname(path)
        self.tmap, self.raw_notes, self.bar_ticks = tmap, notes, bar_ticks
        self.tsig = tsig; self._midi_path = path    # 拍号/路径供"另存 MIDI"使用
        self.tsig_map = TsigMap(tmap.tpb, tsig_events)   # (二期) 分段拍号表
        self._refresh_song_title()
        self.tracks = tracks                        # (多音轨) 轨道元数据
        self.active_tid = tracks[0].tid if tracks else 0
        self.engine.clear_track_fonts()             # (O 轮) 新 MIDI: 轨道独立音源还原
        self._file_bpm = max(1.0, float(tmap.bpms[0]) if tmap.bpms else 120.0)
        self.sp_bpm.blockSignals(True)
        self.sp_bpm.setValue(int(round(self._file_bpm)))   # (P 轮) 导入读取文件 BPM
        self.sp_bpm.blockSignals(False)
        self.cur_sec = 0.0
        self._rebuild()
        self._sync_track_ui()
        self.statusBar().showMessage(
            tr('已打开 {f} · 拍号 {a}/{b} · BPM {bpm} · tempo 变化 {c} 处 · '
               '点 编曲 编辑', f=os.path.basename(path), a=tsig[0], b=tsig[1],
               bpm=round(self._file_bpm), c=len(tmap.ticks)), 6000)
        if project_session.restore(self):           # (工程轮) 恢复音源/设置
            self.statusBar().showMessage(
                tr('已恢复工程记忆 (音源/播放设置)'), 4000)
        return True
    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls(): e.acceptProposedAction()
    def dropEvent(self, e):
        for u in e.mimeData().urls():
            f = u.toLocalFile().lower()
            if f.endswith(('.mid', '.midi')): self._open_path(u.toLocalFile()); return
            if f.endswith('.sf2'):              # (O 轮) 无全局音源: 引导到轨道音源
                self.statusBar().showMessage(
                    tr('SF2 请在下方音轨的概览条上 双击 为音轨单独指定'), 5000)
                return
    # ---------- MIDI 编辑器 ----------
    # editor.py 与主窗口的接口约定:
    #   数据入口   mw.raw_notes / mw.tmap / mw.bar_ticks  (编辑直接改动 raw_notes)
    #   查询播放态 mw._is_playing()       试听 mw._preview(note, on)
    #   提交刷新   mw._editor_commit()    编辑器每次改动 / 撤销 后调用
    #   关闭流程   _confirm_discard() -> _discard_edits() -> _end_edit_session()
    #              (EditorWindow.closeEvent 即按此顺序回调, 见 editor.py)
    def _save_midi_as(self):
        """raw_notes(含编辑成果) 另存为 type-1 MIDI; 成功返回 True 并标记会话已保存"""
        if self.tmap is None:
            QMessageBox.information(self, tr("提示"), tr('请先打开 MIDI 文件')); return False
        if not self.raw_notes:
            QMessageBox.information(self, tr("提示"), tr('当前没有音符可保存')); return False
        if self._midi_path:                       # 默认名: 原名_edited.mid (不覆盖原文件)
            root, _ = os.path.splitext(self._midi_path)
            suggest = root + '_edited.mid'
        else:
            suggest = os.path.join(self._last_dir or os.getcwd(), 'untitled.mid')
        path, _ = QFileDialog.getSaveFileName(self, tr("另存 MIDI"), suggest,
                                              "MIDI (*.mid);;All (*)")
        if not path: return False
        if not path.lower().endswith(('.mid', '.midi')): path += '.mid'
        try:
            retime(self.raw_notes, self.tmap)     # 兜底保证 tick/sec 一致
            save_midi(path, self.tmap, self.tracks, self.raw_notes, self.tsig,
                      tsig_events=self.tsig_map.events())
        except Exception as e:
            QMessageBox.critical(self, tr("保存失败"), str(e)); return False
        self._last_dir = os.path.dirname(path)
        if self.edit_session is not None:
            self.edit_session.mark_saved()        # dirty=False: 关闭时保留编辑成果
        project_session.save_as(self, path)       # (工程轮) 工程记忆写到新位置
        self.statusBar().showMessage(
            tr('已保存 {n} 个音符 → {p}', n=len(self.raw_notes), p=path), 5000)
        return True
    # ---------- 键位 / 音域 / 移调分析 ----------
    # ---------- 重建输出数据(映射/移调/重叠策略变化/编辑器提交) ----------
    def _rebuild(self, keep_view=False):
        """由 raw_notes 重建派生数据: 移调副本 -> 重叠处理 -> 映射分类 -> 事件表 -> 视图.
           keep_view=True: 保持卷帘缩放/平移/音域/播放头(编辑器提交刷新/配置微调用)"""
        if self.tmap is None: return
        t = self.thread
        paused_live = t is not None and t.isRunning() and t.paused   # (C2) 暂停中保留现场
        if not paused_live:
            self._stop_playback()
        mapper = KeyMapper(self.row_keys, self.oct_assign)
        self.mapper = mapper
        # (O 轮) 键位字母表 (音符字母"键位"模式): 音高 -> 输出按键字符
        self._label_keymap = {} if mapper.err else dict(mapper.note_char)
        if self.edit_roll is not None:
            self.edit_roll.label_keymap = self._label_keymap
        trans = self.trans                       # (P 轮) 播放层移调 (主窗移调分析)
        # nid/tid 原样带入解析层副本: 播放高亮(nid匹配)/轨道着色 在各卷帘通用
        notes = [Note(nt.note + trans, nt.vel, nt.start_tick, nt.end_tick,
                      nt.start_sec, nt.end_sec, nid=nt.nid, tid=nt.tid)
                 for nt in self.raw_notes]
        notes, ov = resolve_overlaps(notes, self.tmap, self.overlap_mode)
        sound = self._sound_tids()                # (多音轨) 发声轨道集合
        n_black = n_bad = 0
        if mapper.err is None:
            for nt in notes:
                nt.playable = mapper.in_scope(nt.note)
                if nt.tid not in sound: continue  # 静音/未独奏轨: 显示但不发声
                cls = mapper.classify(nt.note)
                if cls == 'black': n_black += 1
                elif cls != 'playable': n_bad += 1
        else:
            for nt in notes: nt.playable = False
        self.notes = notes
        # (P 轮) 映射范围: 仅当前音轨 / 合并所有音轨 (显示不受影响, 只影响发声输出)
        if self.map_scope == 'active':
            self.out_notes = [nt for nt in notes
                              if nt.playable and nt.tid in sound
                              and nt.tid == self.active_tid]
        else:
            self.out_notes = [nt for nt in notes if nt.playable and nt.tid in sound]
        mt = getattr(self, 'map_tids', None)      # 径向选择器「映射范围·音轨」
        if mt is not None:
            self.out_notes = [nt for nt in self.out_notes if nt.tid in mt]
        ev = []
        for nt in self.out_notes:
            ev.append((nt.start_sec, 1, nt)); ev.append((nt.end_sec, 0, nt))
        ev.sort(key=lambda e: (e[0], e[1]))
        self.events = ev
        self.total_sec = max((nt.end_sec for nt in self.out_notes), default=0.0)
        # (P0) 演奏事件: raw_notes+TempoMap 纯编译产物 (只读, 不参与播放/撤销;
        #       _rebuild 只在数据变化时触发, 此处无条件重算即天然缓存失效)
        # keys 注入 = _label_keymap (键位=一级信息, 规格§7: 未注入降级音名由视图处理)
        fill_k = (lambda p: [self._label_keymap[p]]
                  if p in self._label_keymap else []) if self._label_keymap else None
        self.perf_fill_keys = fill_k      # 合并车道 (多轨并集) 编译复用同一键位注入
        self.perf_events = compile_performance(self.raw_notes, self.tmap,
                                               tsig_map=self.tsig_map,
                                               fill_keys=fill_k)
        self.perf_by_tid = compile_performance_by_tid(self.raw_notes, self.tmap,
                                                      tsig_map=self.tsig_map,
                                                      fill_keys=fill_k)
        self.perf_ver += 1          # (性能修复) 演奏数据版本: 横幅起点缓存/行重建失效
        if paused_live:
            t.replace_data(self.events, self.out_notes, self.total_sec)   # (C2) 换新数据表
        if keep_view:
            self.cur_sec = min(self.cur_sec, self.total_sec)   # 编辑中保持进度
        else:
            self.cur_sec = 0.0
        if paused_live:
            t.seek(self.cur_sec)                # (C2) 静默回到暂停点
        self._update_playhead(self.cur_sec)
        n_sound = sum(1 for nt in notes if nt.tid in sound)   # 发声轨音符总数
        self._stat_args = (len(self.out_notes), n_sound, n_black, n_bad,
                           ov['merged'], ov['truncated'], ov['dedup'], trans)
        self._mapper_err = mapper.err
        self.stat_lbl.setText(self._stat_full())
        # (空元素修复轮) 工程重建后悬浮谱车道自愈: 修「先开悬浮窗后开 MIDI,
        # lane_tids 停留在空列表 → 悬浮谱永久空白」的顺序缺陷
        if getattr(self, 'score_float', None) is not None:
            self._score_float_lanes()
    # ---------- 配置持久化 ----------
    # ---------- 键位 / 音域 / 移调分析 ----------
    def _open_keymap_dialog(self):
        dlg = KeymapDialog(self, self.row_keys)
        if dlg.exec() == KeymapDialog.Accepted:
            self.row_keys = dlg.values()
            self._save_cfg(); self._rebuild(keep_view=True)
            self.statusBar().showMessage(tr('键位已更新'), 3000)
    def _open_oct_dialog(self):
        dlg = OctaveMapDialog(self, self.oct_assign)
        if dlg.exec() == OctaveMapDialog.Accepted:
            self.oct_assign = dlg.values()
            self._save_cfg(); self._rebuild(keep_view=True)
    def _open_note_settings(self):
        """(O 轮) 音符设置弹窗: 默认音符字母显示 (主窗卷帘与编辑器同步生效)"""
        dlg = NoteSettingsDialog(self)
        if dlg.exec() == QDialog.Accepted:
            self.note_label_mode = dlg.mode
            self.note_label_custom = dlg.custom
            store.save_note_label(self.note_label_mode, self.note_label_custom)
            self._apply_note_label()
            self.statusBar().showMessage(tr('音符字母显示已应用'), 3000)
    def _toggle_mute(self, on):
        """(O 轮) 音源静音: 只影响 SF2 发声与试听, 键盘输出不受影响"""
        self.engine.set_muted(on)
        store.save_mute(on)
        self.statusBar().showMessage(
            tr('音源已静音') if on else tr('音源已恢复发声'), 3000)
    def _open_app_settings(self):
        """(O 轮) 设置弹窗: 输出设备 + 语言 (语言即时生效, 设备重建音源)"""
        dlg = AppSettingsDialog(self)
        if dlg.exec() != QDialog.Accepted: return
        if dlg.lang != self.current_lang:          # ---- 语言: 即时生效 ----
            self.current_lang = dlg.lang
            i18n.set_lang(dlg.lang)
            store.save_lang(dlg.lang)
            if self.editor_win is not None:
                self.editor_win.close()            # closeEvent 含未保存确认
            self.retranslate_ui()
            self.statusBar().showMessage(tr('界面语言已切换'), 3000)
        if (dlg.driver, dlg.device) != (self.audio_driver, self.audio_device):
            self.audio_driver, self.audio_device = dlg.driver, dlg.device
            store.save_audio(self.audio_driver, self.audio_device)
            self._apply_audio_device()
    def _apply_audio_device(self):
        """(O 轮) 输出设备变化: 音源链已启动则重建引擎并恢复各轨音源; 否则下次生效"""
        if self.engine.fs is None:                 # 尚未启动音频: 只记录待用
            self.statusBar().showMessage(
                tr('输出设备已保存, 将在下次加载音源时生效'), 4000)
            return
        mute = self.engine.muted
        old_fonts = dict(self.engine.track_fonts)  # 每轨独立音源: 重建后逐轨恢复
        try:
            self.engine.fs.delete()
        except Exception:
            pass
        self.engine = SoundEngine()
        self.engine.audio_driver = self.audio_driver
        self.engine.audio_device = self.audio_device
        self.engine.master_gain = getattr(self, 'src_gain', 100) / 100.0
        self.engine.set_muted(mute)
        for tid, info in old_fonts.items():        # 恢复各轨独立音源 (失败静默跳过)
            t = next((x for x in self.tracks if x.tid == tid), None)
            try:
                self.engine.load_track_font(
                    tid, info['path'], info['preset'],
                    is_drum=bool(t and t.is_drum),
                    gain=float(info.get('gain', 1.0)))
            except Exception:
                continue
        self.statusBar().showMessage(tr('输出设备已切换'), 3000)
    def _apply_cursor_prefs(self):
        """指针大小 / 选择样式变更: 清缓存 → 编辑卷帘指针与工具指示框即时刷新"""
        import cursors
        cursors.clear_cache()
        er = getattr(self, 'edit_roll', None)
        if er is not None:
            er._restore_hover_cursor(); er._sync_tool_hint()
    def _open_settings(self):
        """(M4) 自定义设置弹窗: 统一写回后一次 rebuild 应用"""
        dlg = SettingsDialog(self)
        if dlg.exec() == QDialog.Accepted:
            self.row_keys = dlg.row_keys
            self.oct_assign = dlg.oct_assign
            self.overlap_mode = dlg.overlap_mode
            self.piano_mode = dlg.piano_mode
            self.map_scope = dlg.map_scope
            self.min_hold = dlg.min_hold
            self.min_gap = dlg.min_gap
            self.tap = dlg.tap
            self.start_delay = dlg.start_delay
            self.range_hl_on = dlg.range_hl_on
            self.range_lo = dlg.range_lo
            self.range_hi = dlg.range_hi
            self.strip_font = dlg.strip_font
            self.strip_name_font = dlg.strip_name_font
            self.deck_font = dlg.deck_font
            self.strip_page_bars = dlg.strip_page_bars
            self.score_row_h = dlg.score_row_h
            self.score_float_w = dlg.score_float_w
            self.strip_label = dlg.strip_label
            self.strip_jianpu_base = dlg.strip_jianpu_base
            self.cursor_size = dlg.cursor_size
            self.select_cursor = dlg.select_cursor
            self._save_cfg()
            self._apply_cursor_prefs()
            self._apply_range_hl()
            self._rebuild(keep_view=True)
            self._sync_track_ui()    # (UI轮) 甲板行按新轨名字号重建
            for sf in (getattr(self, 'score_strip', None),
                       getattr(getattr(self, 'score_float', None), 'strip', None)):
                if sf is not None:
                    sf.update()      # (UI轮) 演奏谱字号等显示参数重推
            flt = getattr(self, 'score_float', None)
            if flt is not None:
                flt.refresh_page_fit()   # (加宽轮) 每页小节数变化 → 宽度重算
            if self.thread is not None and self.thread.isRunning():
                pn = self.thread.pianist
                pn.mode = self.piano_mode
                pn.min_hold = self.min_hold
                pn.min_gap = self.min_gap
                pn.tap = self.tap
            self.statusBar().showMessage(tr('设置已应用'), 3000)
    def _open_transpose_dialog(self):
        if not self.raw_notes:
            QMessageBox.information(self, tr("提示"),
                                    tr('请先打开 MIDI 文件再分析移调')); return
        dlg = TransposeAnalysisDialog(self, self.raw_notes, self.oct_assign,
                                      current=self.trans,
                                      row_keys=self.row_keys)
        if dlg.exec() == TransposeAnalysisDialog.Accepted and dlg.chosen is not None:
            self._set_trans(dlg.chosen)
    # ---------- (O 轮) 音符字母 / 统计文案 / 语言刷新 ----------
    # ---------- (O 轮) 音符字母 / 统计文案 / 语言刷新 ----------
    def _apply_note_label(self):
        """音符字母设置同步到编辑器卷帘 (键位表由 _rebuild 注入; 主窗无卷帘)"""
        if self.edit_roll is not None:
            self.edit_roll.set_note_label(self.note_label_mode, self.note_label_custom)
    def _fmt_stat(self):
        """状态行统计 (按当前语言重排); 无数据返回 ''"""
        a = getattr(self, '_stat_args', None)
        if not a: return ''
        return tr('可演奏 {a}/{b} (含黑键 {c}) | 未映射·超域 {d} | '
                  '重叠: 合并{e} 截断{g} 去重{h} | 移调 {v:+d}',
                  a=a[0], b=a[1], c=a[2], d=a[3], e=a[4], g=a[5], h=a[6], v=a[7])
    def _stat_full(self):
        s = self._fmt_stat()
        err = getattr(self, '_mapper_err', None)
        return s + ("   ⚠ " + err if err else "")
    def retranslate_ui(self):
        """(O 轮) 语言切换后刷新常驻界面文案"""
        self.b_play.tip_text = tr('播放 / 暂停')
        self.b_play.shortcut_text = 'Space'
        self.b_stop.tip_text = tr('停止并回到开头')
        self.b_open.setText(tr('文件'))
        self.b_open.tip_text = tr('打开 MIDI 文件')
        self.b_open.shortcut_text = 'Ctrl+O'
        self.b_edit.setText(tr('编曲'))
        self.b_edit.tip_text = tr('打开钢琴卷帘编辑器')
        self.b_edit.shortcut_text = 'Ctrl+E'
        self.b_save.setText(tr('保存'))
        self.b_save.tip_text = tr('保存 MIDI')
        self.b_save.shortcut_text = 'Ctrl+S'
        self.b_mini.setText(tr('悬浮'))
        self.b_mini.tip_text = tr('悬浮窗 (演奏 / 谱面, 置顶可拖)')
        self.b_cfg.tip_text = tr('设置 (键位 / 音符 / 输出 / 语言)')
        self.b_mute.tip_text = tr('音源静音 (不影响键盘输出)')
        self.chk_out.tip_text = tr('启用键盘输出')
        self.b_wmin.tip_text = tr('最小化')
        self.b_wclose.tip_text = tr('关闭')
        self.b_new_ui.setText(tr('新界面'))
        self.b_new_ui.tip_text = tr('新界面')
        self._sync_track_ui()
        if self.mini is not None:
            self.mini.retranslate()
        self._sync_snap_btn()
        self.stat_lbl.setText(self._stat_full())
        self._refresh_song_title()
        for w in (self.b_open, self.b_mini, self.b_edit, self.b_save):
            w.update()
    # ---------- 重建输出数据(映射/移调/重叠策略变化/编辑器提交) ----------
    def _apply_tempo_change(self, full=True):
        """变速修改后同步: 重算音符秒值并重建派生数据; 播放中自动原位续播"""
        if self.tmap is None: return
        was = self._is_playing(); pos = self.cur_sec
        if full:
            if self.thread is not None:
                self._stop_playback()
            retime(self.raw_notes, self.tmap)
            self._rebuild(keep_view=True)
            self.cur_sec = min(pos, self.total_sec)
            if was:
                self._launch_thread()
        else:
            pass   # full=False 无任何调用方 (原 else 分支随 P2-D 事故丢失, 不可恢复; 死分支)
    def closeEvent(self, ev):
        if self.edit_session is not None:           # 编辑中退出: 走未保存确认
            if not self._confirm_discard():
                ev.ignore(); return
            self._discard_edits()
            self._end_edit_session(rebuild=False)   # 即将退出, 无需重建
        ctrl = getattr(self, 'transcription_ctrl', None)
        if ctrl is not None and not ctrl.shutdown():
            QMessageBox.information(self, tr('提示'),
                                    tr('后台任务正在结束，请稍后再关闭'))
            ev.ignore()
            return
        if self._new_ui_window is not None:
            self._new_ui_window.shutdown()
            self._new_ui_window = None
        if self.mini is not None:
            self.mini.close()
        project_session.save(self)                  # (工程轮) 退出前刷写工程记忆
        self._stop_playback()
        store.save_geometry(self.saveGeometry())
        try:
            if self.engine.fs is not None: self.engine.fs.delete()
        except Exception:
            pass
        super().closeEvent(ev)