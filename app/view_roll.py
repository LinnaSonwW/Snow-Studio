# -*- coding: utf-8 -*-
"""Piano Roll 画布: 音符绘制/键盘侧栏/小节标尺/播放指针/缩放平移/擦洗定位
   视图范围独立于键盘映射, 支持滚轮平滑滚动查看 C1~B8。
   v1.1 编辑器支持: set_data(keep_view) / 细网格跟随 snap / 激活高亮按 nid 匹配 /
   _begin_scrub·_begin_pan 可复用 / _draw_editor_overlay 子类钩子 (基类行为不变)"""
import bisect
import math
import os
from PySide6.QtCore import Qt, Signal, QTimer, QRectF, QRect, QPointF
from PySide6.QtGui import (QPainter, QColor, QPen, QFont, QPolygonF, QPixmap,
                           QFontMetrics)
from PySide6.QtWidgets import QWidget
from roll_tiles import TileRenderer   # (P3-G) 瓦片渲染器
# (真机止损 2026-09-08) 三档真机验证结论: mode 2 (QQuickPaintedItem) 在真机
# 可见窗口下存在环境相关的渲染几何缺陷 (音块位置/尺寸错位, offscreen 全对),
# 按《QML渲染性能回归排查清单》止损原则恢复光栅默认; QML 三模式保留为
# opt-in 研究线 (0=光栅 / 1=delegate / 2=MuseScore), 详见《QML渲染迁移报告》§13。
QML_MODE = os.environ.get('ROLL_QML', '0')
USE_QML = QML_MODE != '0'
from common import (BLACK_SET, KB_W, HEADER_H, MIN_PPB, MAX_PPB,
                    note_name, NOTE_NAMES, NOTE_MIN, NOTE_MAX,
                    NOTE_SOLFA, NOTE_JIANPU)
from i18n import t
import settings_store as store
import math
class PianoRoll(QWidget):
    viewChanged = Signal()
    scrubStarted = Signal()
    scrubMoved = Signal(float)
    scrubFinished = Signal(float)
    notePreview = Signal(int, bool)
    def __init__(self, span=3):
        super().__init__()
        self.tmap = None; self.notes = []
        self.tsig_map = None                    # (二期) 分段拍号表 (set_data 绑定)
        self.bar_ticks = 1920.0; self.total_tick = 0.0
        self.ppb = 70.0; self.view_tick = 0.0
        self.playhead_tick = None
        self.active_notes = frozenset()
        self.preview_note = None
        self.view_oct_span = span               # 简略版3八度, 全屏5八度
        self.view_note_start = 48.0             # 默认从 C3 (MIDI 48) 起步，浮点数支持平滑滚动
        self._drag = None
        self.snap_beats = store.load_snap('line')  # 对齐/细网格档位; 'line'=FL 自适应 (30③/Line轮)
        self._edge_key = None; self._edge_counts = (0, 0)
        self.range_lo = self.range_hi = None    # (D4) 音域高亮 (MIDI note)
        self.track_colors = {}                  # (多音轨) tid -> 轨道色 hex
        self.active_tid = 0                     # (多音轨) 当前轨 (编辑器子类使用)
        self.hidden_tids = set()                # 取消勾选的轨: 卷帘不画其音符
        # (O 轮) 音符字母显示: name/letter/solfa/jianpu/key/custom/none (音符设置弹窗)
        self.label_mode = 'name'
        self.label_custom = {}                  # custom 模式: 音级pc -> 显示字符
        self.label_keymap = None                # key 模式: 音高 -> 输出按键字符 (主窗注入)
        self._bgV = None; self._bgV_key = None  # (G-opt) 垂直层: 行背景/音域框/琴键
        self.tiles = TileRenderer(self)         # (P3-G) 瓦片渲染器 (缓存/绘制收口)
        # ---- (QML-1) 渲染迁移: 画布区音符/网格 → QQuickWidget/Scene Graph ----
        # QML 只负责"画出来": 输入事件仍由本 widget 捕获 (画布子控件
        # WA_TransparentForMouseEvents); 手势/编辑逻辑零迁移。
        self._qml_active = False                # 瓦片 key 域标记 + 回退阀状态
        self.qml = None
        if USE_QML:
            # (真机实测 2026-09-07) GL 场景图路径下渲染线程不会回调 Python 的
            # paint() 覆写 (offscreen+software 正常) —— 强制软件渲染循环:
            # paint() 回到 GUI 线程, QML 场景内容轻量 CPU 绘制即可。
            os.environ['QT_QUICK_BACKEND'] = 'software'
            os.environ['QSG_RENDER_LOOP'] = 'software'
            try:
                from PySide6.QtQuick import QQuickWindow
                from roll_qml import RollQmlBridge, PaintedRollHost
                if QML_MODE == '2':
                    self.qml = PaintedRollHost(self)      # (QML-3) MuseScore 路线
                else:
                    self.qml = RollQmlBridge(self)        # (QML-1) delegate 路线
                self._qml_active = True
                # (性能回归第1步) 打印实际生效的渲染后端 —— 排查"真机误走
                # software 纯 CPU 光栅"这类全局变卡问题
                try:
                    backend = QQuickWindow.sceneGraphBackend() or '(default)'
                except Exception:
                    backend = '(unknown)'
                print('[QML-DIAG] sceneGraphBackend=%s | QSG_RENDER_LOOP=%s | '
                      'QT_QUICK_BACKEND=%s | QT_QPA_PLATFORM=%s | instances=2'
                      % (backend,
                         os.environ.get('QSG_RENDER_LOOP', '(auto)'),
                         os.environ.get('QT_QUICK_BACKEND', '(default)'),
                         os.environ.get('QT_QPA_PLATFORM', '(default)')))
            except Exception as e:              # 失败不阻断启动, 回退光栅瓦片
                print('QML 初始化失败, 回退光栅:', repr(e))
                self.qml = None
        self._ph_x = None; self._ph_key = None  # (P 轮) 播放头窄带更新跟踪
        self._sorted = []; self._starts = []    # (25) 音符按 start 排序索引
        self._lookback = 1.0                    # (perf轮) 回看窗口 = P99 时长 (替代全曲最长)
        self._long_notes = []                   # (perf轮) 超 P99 长音小表 (尾随扫描)
        self._color_cache = {}                  # (tid, 力度档, 激活) -> (fill, edge)
        self._fm_note = None                    # (perf轮) QFontMetrics 惰性单例
        self._adv_cache = {}                    # (perf轮) 文本 -> 水平宽度 (烘焙热路径)
        self._lbl_pm = {}                       # (perf轮) (文本,dpr) -> 预渲染标签图
        self._data_ver = 0                      # (L) 音符数据版本 (缓存失效用)
        self.show_edge_banners = True           # (新) ↑/↓ 剩余音符提示 (编辑器关闭)
        self._dirty = None                      # (D1) 渲染时钟脏区: None/'all'/QRect
        self._clock = QTimer(self); self._clock.setInterval(16)
        self._clock.timeout.connect(self._clock_tick); self._clock.start()
        self.setAttribute(Qt.WA_OpaquePaintEvent)   # (P 轮) 整矩形自绘, 免背景擦除
        self.f_note = QFont('Segoe UI', 7)
        self.f_kb = QFont('Segoe UI', 8, QFont.Bold)
        self.f_bar = QFont('Segoe UI', 8)
        self.setMinimumHeight(320)
    # ---------- 几何与视图范围 ----------
    @property
    def note_low(self): return int(self.view_note_start)
    @property
    def note_high(self): return self.note_low + self.view_oct_span * 12 - 1
    @property
    def n_rows(self): return self.view_oct_span * 12
    # ---- (QML-1) active_notes/playhead_tick 属性化: 拦截主窗轮询/编辑器直写,
    #      变化经桥 行级 dataChanged / 属性推送 (增量, 不整体 reset) ----
    @property
    def active_notes(self): return self._active_notes
    @active_notes.setter
    def active_notes(self, nids):
        nids = frozenset(nids) if nids is not None else frozenset()
        old = getattr(self, '_active_notes', frozenset())
        self._active_notes = nids                 # 对象集 (1b 键盘高亮取 .note)
        self._live_index = {getattr(a, 'nid', id(a)): a
                            for a in nids}        # (perf轮) nid->note 实时层索引
        if nids == old: return
        if getattr(self, 'qml', None) is not None:
            self.qml.set_active_notes(nids)       # 维护状态集 + 仅变化行 dataChanged
        self.request_update(self.roll_rect())     # 键盘侧栏高亮仍由 QWidget 绘制
    @property
    def playhead_tick(self): return self._playhead_tick
    @playhead_tick.setter
    def playhead_tick(self, t):
        self._playhead_tick = t
        if getattr(self, 'qml', None) is not None:
            self.qml.set_playhead(t)
    def x_of_tick(self, t): return KB_W + (t - self.view_tick) / self.tmap.tpb * self.ppb
    def tick_of_x(self, x): return self.view_tick + (x - KB_W) / self.ppb * self.tmap.tpb
    def row_h(self): return (self.height() - HEADER_H) / self.n_rows
    def _note_at_y(self, y):
        if self.row_h() <= 0: return None
        frac = self.view_note_start - self.note_low
        y_off = frac * self.row_h()
        n = int(self.note_high - (y - HEADER_H + y_off) // self.row_h())
        return n if NOTE_MIN <= n <= NOTE_MAX else None
    def _clamp_view_note(self):
        max_start = NOTE_MAX - self.view_oct_span * 12 + 1
        self.view_note_start = max(float(NOTE_MIN), min(float(max_start), self.view_note_start))
    # ---------- 数据 ----------
    def _content_span_ticks(self) -> float:
        """可滚动/可见时间轴长度: 音符末尾、项目显示范围、声组织/音频时长取最大。"""
        note_end = max((nt.end_tick for nt in self.notes), default=0.0)
        span = note_end
        mw = getattr(self, 'mw', None)
        if mw is not None:
            span = max(span, float(getattr(mw, 'total_tick_display', 0) or 0))
        tx = getattr(self, 'transcription', None)
        if tx is not None and self.tmap is not None:
            tissue = getattr(tx, 'tissue', None)
            if tissue is not None and tissue.blobs:
                span = max(span, max(b.end_tick for b in tissue.blobs))
            elif getattr(tx, 'duration_sec', 0) > 0:
                span = max(span, float(self.tmap.sec2tick(tx.duration_sec)))
        return span

    def refresh_content_span(self):
        """无音符时 (仅声组织/音频) 同步可滚动长度并刷新概览条。"""
        if self.tmap is None:
            return
        self.total_tick = self._content_span_ticks()
        self._clamp_view()
        self.update()
        self.viewChanged.emit()

    def set_data(self, tmap, notes, bar_ticks, keep_view=False,
                 tsig_map=None):
        """keep_view=True: 保持缩放/平移/音域/播放头 (编辑器提交刷新时用);
        tsig_map: 分段拍号表 (绑定后 roll_tiles 分段小节线/逐段小节号分支
        生效, 版本号进瓦片 key 驱动重烘; 缺省维持单一线距回退)"""
        self.tmap = tmap; self.notes = notes
        self.bar_ticks = float(bar_ticks)
        self.tsig_map = tsig_map
        self.total_tick = self._content_span_ticks()
        self._edge_key = None
        # (25) 可见窗口索引: 按 start_tick 排序 + 回看窗口界;
        #      (perf轮) 回看窗从"全曲最长音"收紧为 P99 时长, 超过的长音进
        #      _long_notes 小表由 visible_notes 尾随扫描补充 —— 有全曲长音
        #      (如伴奏垫音) 不再让每个瓦片/每帧退化为近全量扫描
        durs = sorted(nt.end_tick - nt.start_tick for nt in notes)
        if len(durs) >= 64:
            thr = max(1.0, durs[int(len(durs) * 0.99) - 1])
            self._lookback = float(thr)
            self._long_notes = [nt for nt in notes
                                if nt.end_tick - nt.start_tick > thr]
            main = [nt for nt in notes if nt.end_tick - nt.start_tick <= thr]
        else:
            self._lookback = float(durs[-1]) if durs else 1.0
            self._long_notes = []
            main = notes
        self._sorted = sorted(((nt.start_tick, nt) for nt in main),
                              key=lambda p: p[0])
        self._starts = [s for s, _nt in self._sorted]
        self._color_cache = {}
        self.tiles.clear()
        self._data_ver += 1                     # 音符层缓存失效
        if self.qml is not None:
            self.qml.refresh_all()              # (QML-1) 轨道色行级刷新
        if keep_view:
            self._clamp_view(); self.update()
        else:
            self.playhead_tick = 0
            self.fit_all()
        if self.qml is not None:
            self.qml.set_notes(self.notes)      # (QML-1) 整体换源 = 唯一合法 reset
        self.viewChanged.emit()
    def min_ppb(self):
        """(新) 缩放下限: 常规 MIN_PPB; 长曲自动放宽, 保证最大视野(全曲+1小节)可见"""
        span_max = self.total_tick + self.bar_ticks
        if self.tmap is None or span_max <= 0: return MIN_PPB
        fit = (self.width() - KB_W) / (span_max / self.tmap.tpb)
        return max(1.0, min(MIN_PPB, fit))
    def fit_all(self):
        if self.tmap is None: return
        beats = self.total_tick / self.tmap.tpb
        if beats > 0:
            self.ppb = float(min(MAX_PPB, max(self.min_ppb(),
                                              (self.width() - KB_W) / beats)))
        self.view_tick = 0.0; self.update()
    def _clamp_view(self):
        vis = (self.width() - KB_W) / self.ppb * self.tmap.tpb
        hi = max(0.0, self.total_tick + self.bar_ticks - vis)
        self.view_tick = min(max(self.view_tick, 0.0), hi)
    # ---------- 渲染时钟与背景缓存 (D1, FL 式) ----------
    @staticmethod
    def _norm_dirty_rect(region):
        """QWidget.update 只接受 QRect; 统一 QRectF/float 脏区。"""
        if region is None or region == 'all':
            return 'all'
        if isinstance(region, QRect):
            return region
        if isinstance(region, QRectF):
            return region.toAlignedRect()
        return QRect(int(region.x()), int(region.y()),
                       max(1, int(region.width())), max(1, int(region.height())))

    def request_update(self, region=None):
        """输入热路径只标脏; 16ms 时钟统一重绘 (≤60fps, 与输入速率解耦)"""
        if region is None:
            self._dirty = 'all'
        elif self._dirty != 'all':
            region = self._norm_dirty_rect(region)
            if region == 'all':
                self._dirty = 'all'
            else:
                self._dirty = region if self._dirty is None else self._dirty.united(region)
    def _clock_tick(self):
        if self.qml is not None:
            self.qml.push_view()                # (QML-1) 视图属性推送 (值不变零代价)
        if self._dirty is None:
            # (预加载轮) 空闲预取: 无脏区/无手势/可见时, 每 tick 至多烘 1 片缓冲圈
            # (滑入视口即命中; 交互/拖动帧零抢占; 播放跟随方向也被提前烘好)
            if (self.qml is None and self._drag is None
                    and self.tmap is not None and self.isVisible()
                    and not getattr(self, 'render_silent', False)):
                self.tiles.prefetch()
            return
        d, self._dirty = self._dirty, None
        if self.qml is not None:
            self.qml.sync_dynamic()             # 拖动帧行级增量 (规格: 不 reset)
            self.qml.ovl.update()               # 覆盖层 (选中/橡皮筋) 同帧重绘
        if d == 'all':
            self.update()
        else:
            self.update(self._norm_dirty_rect(d))
    def roll_rect(self):
        """卷帘区矩形 (拖动中只需重绘这里: 网格/标尺/琴键都是静态的)"""
        return QRect(int(KB_W), int(HEADER_H), max(1, self.width() - int(KB_W)),
                     max(1, self.height() - int(HEADER_H)))
    def set_range_highlight(self, lo, hi):
        """(D4) 音域高亮: lo/hi = MIDI note; None = 关"""
        self.range_lo, self.range_hi = lo, hi
        self._bgV_key = None; self.update()     # 音域框在垂直层
    def set_track_colors(self, colors):
        """(多音轨) 设置 tid -> 轨道色 hex 映射 (音符是动态层, 无需重建背景缓存)"""
        self.track_colors = dict(colors)
        self._color_cache = {}
        self.tiles.clear()
        self._data_ver += 1                     # 音符层缓存失效
        self.update()
    def set_note_label(self, mode=None, custom=None, keymap=None):
        """(O 轮) 音符字母显示设置: 任一参数传 None 表示保持不变"""
        if mode is not None: self.label_mode = mode
        if custom is not None: self.label_custom = dict(custom)
        if keymap is not None: self.label_keymap = keymap
        self.tiles.clear()
        self._data_ver += 1
        if self.qml is not None:
            self.qml.refresh_all()              # (QML-1) 字母模式行级刷新
        self.update()
    def _note_label(self, nt):
        """音符字母文本钩子: 按当前显示模式返回文本
           (Q 轮) 唱名/简谱/键位 追加 [八度]; 键位黑键统一 ♯ 前缀 (未映射回退音名);
           none 模式返回 None (不显示)"""
        m = self.label_mode
        pc = nt.note % 12
        oct_s = '[%d]' % (nt.note // 12 - 1)
        if m == 'name': return note_name(nt.note)
        if m == 'letter': return NOTE_NAMES[pc]
        if m == 'solfa': return NOTE_SOLFA[pc] + oct_s
        if m == 'jianpu': return NOTE_JIANPU[pc] + oct_s
        if m == 'key':
            # 已映射 = 按键字母; 未映射 = 音名; 黑键一律加 ♯ 前缀 (与唱名/简谱一致)
            body = self.label_keymap.get(nt.note) if self.label_keymap else None
            if body is None:
                body = NOTE_NAMES[pc].replace('#', '')   # ♯ 前缀已表达升号
            return ('♯' + body + oct_s) if pc in BLACK_SET else (body + oct_s)
        if m == 'custom':
            return (self.label_custom.get(pc) or '').strip() or None
        return None                             # none 模式
    def _label_for_width(self, full, avail):
        """(Q 轮) 按可用宽度选择显示级别: 完整名称 → 简短(首字+…) → None
           (perf轮) 字宽查询走缓存: 字体固定, 文本集有限 (音名/键位×八度)"""
        fm = self._fm_note
        if fm is None:
            fm = self._fm_note = QFontMetrics(self.f_note)
        adv = self._adv_cache
        w = adv.get(full)
        if w is None:
            w = adv[full] = fm.horizontalAdvance(full)
        if w <= avail: return full
        short = full[:1] + '…'
        ws = adv.get(short)
        if ws is None:
            ws = adv[short] = fm.horizontalAdvance(short)
        return short if ws <= avail else None
    def _label_pixmap(self, text, dpr):
        """(perf轮) 标签预渲染: 8 向描边 + 正文烘进小位图, 绘制退化为一次 blit。
           瓦片重烘风暴时每音符省 9 次字形排版; 按 (文本, dpr) 缓存 (文本集有限)
           边距 1.5 逻辑 px 吸收描边偏移; setDevicePixelRatio 保物理像素 1:1 清晰"""
        key = (text, round(dpr, 2))
        pm = self._lbl_pm.get(key)
        if pm is not None: return pm
        fm = self._fm_note
        if fm is None:
            fm = self._fm_note = QFontMetrics(self.f_note)
        w = int(math.ceil(fm.horizontalAdvance(text))) + 4
        h = fm.height() + 4
        pm = QPixmap(int(w * dpr), int(h * dpr))
        pm.setDevicePixelRatio(dpr)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setFont(self.f_note)
        r = QRectF(2, 2, w - 4.0, h - 4.0)   # AlignVCenter|AlignLeft; 整数域防亚相移
        p.setPen(QColor('#101318'))              # 字母极细黑描边 (8 向偏移)
        for ddx, ddy in ((1, 0), (-1, 0), (0, 1), (0, -1),
                         (1, 1), (1, -1), (-1, 1), (-1, -1)):
            p.drawText(r.translated(ddx, ddy), Qt.AlignVCenter | Qt.AlignLeft, text)
        p.setPen(QColor(238, 243, 250, 235))
        p.drawText(r, Qt.AlignVCenter | Qt.AlignLeft, text)
        p.end()
        self._lbl_pm[key] = pm
        return pm
    def _draw_note_label(self, p, nt, x0, x1, y, nh):
        """在音符上画字母 (8 向黑描边 + 浅色正文), 按屏宽三级显示:
           太窄 → 不显示; 稍宽 → 简短名称(首字+…); 足够宽 → 完整名称
           (perf轮) 绘制来自 _label_pixmap 预渲染位图 (一次 blit)"""
        full = self._note_label(nt)
        if not full: return
        avail = (x1 - x0) - 8                   # 音符内左右留白
        if avail <= 4 or self.row_h() < 11: return
        text = self._label_for_width(full, avail)
        if not text: return
        fm = self._fm_note
        if fm is None:
            fm = self._fm_note = QFontMetrics(self.f_note)
        dpr = p.device().devicePixelRatioF() if p.device() is not None else 1.0
        pm = self._label_pixmap(text, dpr)
        # 锚点 = 旧矩形 AlignVCenter|AlignLeft 同位 (像素对照实测校正 +0,-2:
        # Qt 对齐舍入在位图与直绘两路径的相位差, 恒定偏移)
        h = fm.height() + 4
        p.drawPixmap(QPointF(x0 + 0.0, y + nh / 2.0 - h / 2.0 + 2.0), pm)
    def _dynamic_nids(self):
        """(L) 每帧实时绘制(不进音符缓存层)的 nid 集合; 子类可覆写"""
        return set()
    def _live_note_objects(self):
        """(perf轮) 实时层待绘 (nid, note) 列表 —— O(live) 取代每帧全量扫
           可见候选。基类 = 播放高亮音符; 编辑器覆写叠加拖动/新建/删除标记"""
        return list(getattr(self, '_live_index', {}).items())
    def visible_notes(self, t0, t1):
        """(25) 可见窗口候选: 二分定位 start ∈ [t0-回看窗, t1] 的音符;
           (perf轮) 回看窗 = P99 时长, 超 P99 长音走 _long_notes 小表补充
           (与窗口相交判定), 候选再经 行/像素 裁剪即为实际可见"""
        if not self._starts: return []
        lo = bisect.bisect_left(self._starts, t0 - self._lookback)
        hi = bisect.bisect_right(self._starts, t1)
        hidden = self.hidden_tids
        if not hidden:
            out = [nt for _s, nt in self._sorted[lo:hi]]
        else:
            out = [nt for _s, nt in self._sorted[lo:hi]
                   if getattr(nt, 'tid', 0) not in hidden]
        lng = self._long_notes
        if lng:
            for nt in lng:
                if nt.start_tick > t1 or nt.end_tick <= t0: continue
                if hidden and getattr(nt, 'tid', 0) in hidden: continue
                out.append(nt)
        return out

    def set_track_notes_visible(self, tid, visible: bool):
        """音轨下拉勾选: 控制该轨音符是否画在卷帘上 (默认显示)。"""
        tid = int(tid)
        if visible:
            self.hidden_tids.discard(tid)
        else:
            self.hidden_tids.add(tid)
        self._data_ver += 1
        if getattr(self, 'tiles', None) is not None:
            self.tiles.clear_canvas()
        self.request_update()
    def _note_colors(self, nt, is_active):
        """音符配色钩子(带缓存): 激活高亮 > 轨道色(力度分档调明暗) > 不可播放暗红
           描边统一为极细近黑 (M1)"""
        key = (getattr(nt, 'tid', 0), nt.vel >> 5, bool(is_active))
        hit = self._color_cache.get(key)
        if hit is not None: return hit
        edge = QColor('#101318')
        if is_active:
            cols = (QColor('#ffb020'), edge)
        elif nt.playable:
            base = QColor(self.track_colors.get(key[0], '#4f9cf9'))
            v = (key[1] + 0.5) / 4.0                      # 力度档代表值
            cols = (base.lighter(int(165 - 55 * v)), edge)
        else:
            cols = (QColor('#7c5158'), edge)
        self._color_cache[key] = cols
        return cols
    # ---------- 视野窗口控制 (顶部概览条联动) ----------
    def visible_span(self):
        """当前视野覆盖的 tick 跨度"""
        return (self.width() - KB_W) / self.ppb * self.tmap.tpb
    def _min_span(self):
        return (self.width() - KB_W) / MAX_PPB * self.tmap.tpb
    def set_view_span(self, ticks):
        """概览条右缘拖动: 拉长窗口=看更多, 拉短=看更少 (左缘保持不动);
           上限 = 全曲(+1小节) → 可放大到看到所有音符"""
        if self.tmap is None: return
        ticks = min(max(ticks, self._min_span()), self.total_tick + self.bar_ticks)
        self.ppb = float(min(MAX_PPB, max(self.min_ppb(),
                        (self.width() - KB_W) / ticks * self.tmap.tpb)))
        if self.qml is not None: self.qml.zoom_hold_on()   # (性能回归第8步) 连续缩放节流
        self._clamp_view(); self.update(); self.viewChanged.emit()
    def set_view_center(self, tick):
        """概览条拖动/跳转: 视野中心定位"""
        self.view_tick = tick - self.visible_span() / 2
        self._clamp_view(); self.update(); self.viewChanged.emit()
    def pan_by(self, dticks):
        """概览条/滚轮: 前进(+)/后退(-) 平移"""
        self.view_tick += dticks
        self._clamp_view(); self.update(); self.viewChanged.emit()
    # ---------- (P2-E) 公开 API: 跨模块只经此修改视图/播放头状态 ----------
    def set_view_tick(self, t):
        """公开设置视野起点 (钳制+重绘+广播); tempo_editor 中键平移使用"""
        self.view_tick = t
        self._clamp_view(); self.update(); self.viewChanged.emit()
    def set_playhead(self, tick, full=False):
        """公开设置播放头 (拖动预览守卫在 roll 内部); 主窗 40ms 轮询使用"""
        if getattr(self, '_ph_preview', False): return   # (R 轮) 预览中不被覆盖
        self.playhead_tick = tick
        self.update_playhead_region(full=full)
    def set_active_notes(self, nids):
        """播放高亮 nid 集; 返回是否变化 (供调用方决定窄带全量刷新)"""
        changed = nids != self.active_notes
        self.active_notes = nids
        return changed
    # ---------- 绘制 ----------
    def paintEvent(self, ev):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        p.fillRect(0, 0, w, h, QColor('#0e1a24'))   # (配色轮·FL 式) 亮底暗线体系
        if self.tmap is None:
            p.setPen(QColor('#7a7a88')); p.setFont(QFont('Segoe UI', 11))
            p.drawText(self.rect(), Qt.AlignCenter,
                       t('打开一个 .mid 文件开始  (支持拖放)'))
            return
        tpb = self.tmap.tpb; rh = self.row_h()
        lo, hi, nr = self.note_low, self.note_high, self.n_rows
        t0 = max(self.view_tick, 0.0); t1 = self.tick_of_x(w)
        # 计算平滑滚动的垂直偏移量
        frac = self.view_note_start - lo
        y_off = frac * rh
        # ====== 1. 垂直层缓存 (行背景/音域框/琴键, 行锚定 + 底部余量) ======
        # (预加载轮) key 用 int(view_note_start): 行内小数相位只影响贴图偏移,
        # 不再整体重建; 烘焙 frac=0 相位 + 底部 2 行余量, blit 叠加 -y_off
        dpr = self.devicePixelRatioF()
        keyV = (int(self.view_note_start), w, h, self.range_lo, self.range_hi,
                self.view_oct_span)   # (Q 轮) 跨度入 key: Ctrl+滚轮 上下缩放
        if keyV != self._bgV_key:
            self._bgV_key = keyV
            self._bgV = QPixmap(int(w * dpr), int((h + 2.0 * rh) * dpr))
            self._bgV.setDevicePixelRatio(dpr)
            self._bgV.fill(QColor('#0e1a24'))
            bp = QPainter(self._bgV)
            vs0 = self.view_note_start
            self.view_note_start = float(int(vs0))   # 行锚定相位 (lo/hi 不变)
            try:
                self._draw_static_v(bp, v_margin=2.0 * rh)
            finally:
                self.view_note_start = vs0
            bp.end()
        p.drawPixmap(QPointF(0, -y_off), self._bgV)
        # 分隔线不随行相位位移: 紧贴 blit 直绘 (原在 _draw_static_v 末尾)
        p.setPen(QPen(QColor('#000000'), 1))
        p.drawLine(QPointF(KB_W, 0), QPointF(KB_W, h))
        p.drawLine(QPointF(0, HEADER_H), QPointF(w, HEADER_H))
        # ====== 1a. 瓦片层 (网格/标尺/音符, tick 锚定): 平移/擦洗零重绘, 只 blit ======
        skip = self._dynamic_nids()                 # 选中/拖动中音符不进瓦片 (无残影)
        if self.qml is not None:
            self.tiles.draw(p, skip, ruler_only=True)   # (QML-1) 网格/音符归 QML 画布
        else:
            self.tiles.draw(p, skip)
        # ====== 1a2. 扒谱声组织层 (正式音符之下) ======
        self._draw_transcription_candidates(p)
        # ====== 1b. 激活/预览琴键高亮 (动态, 叠在静态缓存上) ======
        act_pitches = {a.note for a in self.active_notes}
        if self.preview_note is not None: act_pitches.add(self.preview_note)
        if act_pitches:
            p.save()
            p.setClipRect(QRectF(0, HEADER_H, KB_W, h - HEADER_H))
            bw = KB_W * 0.62
            for i in range(-1, nr + 1):
                n = hi - i; y = HEADER_H + i * rh - y_off
                if n not in act_pitches: continue
                if (n % 12) not in BLACK_SET:
                    p.setBrush(QColor('#ffc84d')); p.setPen(QPen(QColor('#b3b3bd'), 1))
                    p.drawRect(QRectF(0.5, y, KB_W - 1.0, max(rh, 1.0)))
                else:
                    p.setBrush(QColor('#c9860a')); p.setPen(QPen(QColor('#3c3c46'), 1))
                    p.drawRect(QRectF(KB_W - bw, y - rh * 0.05, bw, max(rh * 1.05, 1.0)))
            p.restore()
        # ====== 1c. 活动音符(播放高亮)与选中音符: 每帧实时绘制 (瓦片之上覆盖) ======
        # (QML-1) QML 模式: 活动高亮经模型 state 行级增量, 选中由覆盖层描边
        # (perf轮) _live_note_objects() 直接给 (nid, note) 列表, live 为空零迭代
        #          —— 旧路径每帧全量扫可见候选 (播放中 25fps 空转数千次)
        if self.qml is None:
            live = self._live_note_objects()
            if live:
                act = set(getattr(self, '_live_index', ()))   # 仅播放中 (琥珀)
                p.save()
                p.setClipRect(QRectF(KB_W, HEADER_H, w - KB_W, h - HEADER_H))
                for nid, nt in live:
                    if not (lo - 1 <= nt.note <= hi + 1): continue
                    x0 = self.x_of_tick(nt.start_tick); x1 = self.x_of_tick(nt.end_tick)
                    if x1 < KB_W or x0 > w: continue
                    y = HEADER_H + (hi - nt.note) * rh - y_off + 1.0
                    nh = max(rh - 1.0, 2.0)
                    x0 = max(x0, KB_W + 1.0); x1 = min(x1, float(w) - 1.0)
                    if x1 - x0 < 6.0: x1 = x0 + 6.0
                    fill, edge = self._note_colors(nt, nid in act)
                    p.setPen(QPen(edge, 1)); p.setBrush(fill)
                    p.drawRoundedRect(QRectF(x0, y, x1 - x0, nh), 3.0, 3.0)
                    self._draw_note_label(p, nt, x0, x1, y, nh)   # 选中/高亮时字母不消失
                p.restore()
        # ====== 2. 播放指针 (动态; 标尺/变速标记已在静态缓存里) ======
        # (QML-1) QML 模式播放头由画布内 Rectangle 绘制
        if self.qml is None and self.playhead_tick is not None:
            x = self.x_of_tick(self.playhead_tick)
            if KB_W <= x <= w + 30:
                p.setPen(QPen(QColor('#ff3b30'), 2))
                p.drawLine(QPointF(x, 0), QPointF(x, h))
                p.setPen(Qt.NoPen); p.setBrush(QColor('#ff3b30'))
                p.drawPolygon(QPolygonF([QPointF(x-5, 0), QPointF(x+5, 0), QPointF(x, 7)]))
        # ====== 4. 边缘音符提示 (编辑器关闭; 计数缓存) ======
        if self.show_edge_banners:
            key = (lo, hi)
            if self._edge_key != key:
                self._edge_counts = (sum(1 for nt in self.notes if nt.note > hi),
                                     sum(1 for nt in self.notes if nt.note < lo))
                self._edge_key = key
            above_count, below_count = self._edge_counts
            if above_count > 0:
                p.fillRect(QRectF(KB_W, HEADER_H, w - KB_W, 18), QColor(0, 0, 0, 140))
                p.setPen(QColor('#e8b05a')); p.setFont(self.f_bar)
                p.drawText(QRectF(KB_W, HEADER_H, w - KB_W, 18), Qt.AlignCenter,
                           t('↑ 还有 {n} 个音符 (在键盘区滚轮向上查看)', n=above_count))
            if below_count > 0:
                p.fillRect(QRectF(KB_W, h - 18, w - KB_W, 18), QColor(0, 0, 0, 140))
                p.setPen(QColor('#e8b05a')); p.setFont(self.f_bar)
                p.drawText(QRectF(KB_W, h - 18, w - KB_W, 18), Qt.AlignCenter,
                           t('↓ 还有 {n} 个音符 (在键盘区滚轮向下查看)', n=below_count))
        # ====== 5. 编辑器覆写钩子 (选中/橡皮筋/参考线/气泡) ======
        # (QML-1) QML 模式由 _QmlOverlay 子控件绘制 (需叠在 QML 画布之上)
        if self.qml is None:
            self._draw_editor_overlay(p)
    def _draw_static_v(self, p, v_margin=0.0):
        """(G-opt) 垂直层: 行背景/音域框/琴键 — 仅上下滚音域或尺寸变化时重画。
           (预加载轮) v_margin>0 = 行锚定烘焙: 底部多画余量行; 分隔线移出本函数
           (由调用方直绘, 不随行相位位移)。QML mode2 直绘传缺省 0, 行为不变"""
        w, h = self.width(), self.height()
        rh = self.row_h()
        lo, hi, nr = self.note_low, self.note_high, self.n_rows
        m = float(v_margin)
        extra = int(round(m / rh)) if rh > 0 else 0
        frac = self.view_note_start - lo
        y_off = frac * rh
        # ---- 行背景 + 音域框 (裁剪卷帘区) ----
        p.save()
        p.setClipRect(QRectF(KB_W, HEADER_H, w - KB_W, h - HEADER_H + m))
        for i in range(-1, nr + 1 + extra):
            n = hi - i; y = HEADER_H + i * rh - y_off
            p.fillRect(QRectF(KB_W, y, w - KB_W, rh + 0.6),
                       QColor('#2a3a44') if (n % 12) in BLACK_SET else QColor('#34444e'))
            if n % 12 == 0:
                p.fillRect(QRectF(KB_W, y + rh - 1, w - KB_W, 1), QColor('#2e3e48'))
        if self.range_lo is not None and self.range_hi is not None:      # (D4) 边框式·绿色
            y_top = HEADER_H + (hi - self.range_hi) * rh - y_off
            y_bot = HEADER_H + (hi - self.range_lo) * rh - y_off + rh
            p.setPen(QPen(QColor(80, 220, 120, 180), 2))
            p.setBrush(Qt.NoBrush)
            p.drawRect(QRectF(KB_W + 1.0, y_top, w - KB_W - 2.0, y_bot - y_top))
            p.setPen(QColor(120, 235, 150, 220)); p.setFont(QFont('Segoe UI', 7))
            if y_top > HEADER_H + 14:
                p.drawText(QPointF(KB_W + 6.0, y_top - 3.0),
                           f"C{self.range_lo // 12 - 1}~B{self.range_hi // 12 - 1}")
        p.restore()
        # ---- 键盘侧栏 (FL 式琴键; 激活高亮由 paintEvent 动态叠加) ----
        p.save()
        p.setClipRect(QRectF(0, HEADER_H, KB_W, h - HEADER_H + m))
        p.fillRect(QRectF(0, HEADER_H, KB_W, h - HEADER_H + m), QColor('#14181e'))
        for i in range(-1, nr + 1 + extra):                       # 白键
            n = hi - i; y = HEADER_H + i * rh - y_off
            if (n % 12) not in BLACK_SET:
                p.setBrush(QColor('#d5d8dc')); p.setPen(QPen(QColor('#9ba1ab'), 1))
                p.drawRect(QRectF(0.5, y, KB_W - 1.0, max(rh, 1.0)))
                if n % 12 == 0:                           # C 标签小牌
                    ly, lh = y + rh * 0.18, max(rh * 0.64, 8)
                    p.setBrush(QColor('#c9ced4')); p.setPen(Qt.NoPen)
                    p.drawRoundedRect(QRectF(3, ly, KB_W - 10, lh), 2, 2)
                    p.setPen(QColor('#3a4048')); p.setFont(self.f_kb)
                    p.drawText(QRectF(3, ly, KB_W - 10, lh), Qt.AlignCenter,
                               f"C{n // 12 - 1}")
        for i in range(-1, nr + 1 + extra):                       # 黑键
            n = hi - i; y = HEADER_H + i * rh - y_off
            if (n % 12) in BLACK_SET:
                bw = KB_W * 0.62
                p.setBrush(QColor('#181c22')); p.setPen(QPen(QColor('#2e343d'), 1))
                p.drawRect(QRectF(KB_W - bw, y - rh * 0.05, bw, max(rh * 1.05, 1.0)))
        p.restore()
        # (预加载轮) 分隔线移出: 不随行相位位移, 由 paintEvent 紧贴 bgV blit 直绘
    # ---------- (P3-G) 瓦片层已迁至 roll_tiles.TileRenderer (self.tiles) ----------
    def update_playhead_region(self, full=False):
        """(P 轮) 播放头窄带重绘: 播放中只刷新旧 x 两条竖带 (视野/尺寸变化时全量)"""
        x = self.x_of_tick(self.playhead_tick) if self.playhead_tick is not None else None
        key = (self.view_tick, self.view_note_start, self.width(),
               self.height(), self.ppb)
        if full or self.playhead_tick is None or getattr(self, '_ph_key', None) != key:
            self.update()
        else:
            old = self._ph_x if self._ph_x is not None else x
            x0 = max(0, int(min(old, x)) - 8)
            self.update(QRect(x0, 0, int(abs(x - old)) + 16, self.height()))
        self._ph_x = x; self._ph_key = key
    def _draw_transcription_candidates(self, p):
        """子类可覆写: 扒谱声组织层"""
        pass
    def _draw_editor_overlay(self, p):
        """基类空实现, editor.EditablePianoRoll 覆写"""
        pass
    # ---------- 交互 ----------
    def _begin_scrub(self, x):
        self._drag = ('scrub',); self.scrubStarted.emit(); self._do_scrub(x)
    def _begin_pan(self, x):
        self._drag = ('pan', x, self.view_tick); self.setCursor(Qt.ClosedHandCursor)
    def wheelEvent(self, ev):
        if self.tmap is None: return
        dx, dy = ev.angleDelta().x(), ev.angleDelta().y()
        mods = ev.modifiers()
        mx = ev.position().x()
        if mx < KB_W and dy != 0:
            # 鼠标在左侧钢琴键区域: 滚轮滚动音域
            # (滚动轮·FL 同款) 整行对齐: 增量累加, 视野按整行取整 (无半行残条)
            self._vscroll_acc = getattr(self, '_vscroll_acc', 0.0) + dy / 120.0
            rows = int(self._vscroll_acc)
            if rows:
                self._vscroll_acc -= rows
                self.view_note_start = int(self.view_note_start) + rows
            self._clamp_view_note()
            self.request_update()
            self.viewChanged.emit()
        else:
            # 鼠标在右侧卷帘区域: 滚轮 上=前进 / 下=后退 (不再依赖标尺行);
            # Shift+滚轮 = 以光标为锚缩放; 顶部概览条右缘拖动可连续缩放
            if mods & Qt.ShiftModifier:
                anchor = self.tick_of_x(mx)
                f = 1.25 if dy > 0 else 0.8
                self.ppb = float(min(MAX_PPB, max(self.min_ppb(), self.ppb * f)))
                self.view_tick = anchor - (mx - KB_W) / self.ppb * self.tmap.tpb
                if self.qml is not None: self.qml.zoom_hold_on()   # (性能回归第8步)
            else:
                self.view_tick += (dy if dy else dx) * 0.0018 * self.visible_span()
            self._clamp_view()
            self.request_update(); self.viewChanged.emit()
    def mousePressEvent(self, ev):
        if self.tmap is None or not (ev.buttons() & Qt.LeftButton): return
        pos = ev.position(); x, y = pos.x(), pos.y()
        if y < HEADER_H and x >= KB_W:
            self._begin_scrub(x)
        elif x < KB_W and y >= HEADER_H:
            n = self._note_at_y(y)
            if n is not None:
                self.preview_note = n; self.notePreview.emit(n, True); self.update()
        else:
            self._begin_pan(x)
    def mouseMoveEvent(self, ev):
        if not self._drag: return
        x = ev.position().x()
        if self._drag[0] == 'pan':
            self.view_tick = self._drag[2] - (x - self._drag[1]) / self.ppb * self.tmap.tpb
            self._clamp_view(); self.request_update(); self.viewChanged.emit()
        else:
            self._do_scrub(x)
    def mouseReleaseEvent(self, ev):
        if self._drag:
            kind = self._drag[0]; self._drag = None
            if kind == 'scrub':
                self.scrubFinished.emit(
                    self.tmap.tick2sec(min(max(self.tick_of_x(ev.position().x()), 0.0),
                                           self.total_tick)))
            else:
                self.setCursor(Qt.ArrowCursor)
        if self.preview_note is not None:
            self.notePreview.emit(self.preview_note, False)
            self.preview_note = None; self.update()
    def _do_scrub(self, x):
        t = min(max(self.tick_of_x(x), 0.0), self.total_tick)
        if self.snap_beats is not None and hasattr(self, '_snap_round'):
            t = min(max(self._snap_round(t), 0.0), self.total_tick)
        self.scrubMoved.emit(self.tmap.tick2sec(t))
    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        if self.tmap is not None:
            self._clamp_view()
        lane = getattr(self, 'tempo_lane', None)
        if lane is not None: lane.reposition()   # (Q 轮) 遮罩 lanes 保持锚定底部
        strip = getattr(self, 'score_strip', None)
        if strip is not None: strip.reposition()   # (P0b) 演奏谱横幅同容器锚定
        if self.qml is not None:
            self.qml.reposition()               # (QML-1) 画布/覆盖层几何同步
        self.viewChanged.emit()
    def qml_fallback(self):
        """(QML-1) 场景加载/运行失败: 整体回退光栅瓦片渲染。
           瓦片 key 含 _qml_active (O1 教训), 回退后自动换缓存域重建。"""
        if self.qml is not None:
            self.qml.quick.deleteLater()
            self.qml.ovl.deleteLater()
            self.qml = None
        self._qml_active = False
        self.tiles.clear()
        self.update()