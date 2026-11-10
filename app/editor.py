# -*- coding: utf-8 -*-
"""MIDI 编辑器 v1 (FL Studio 风格, 仅全屏编辑窗使用):
   EditorWindow       编辑器独立窗口 (标题栏关闭时走主窗口的未保存确认)
   EditSession        (X 轮迁至 model.py, 此处再导出保持 import 兼容)
   EditablePianoRoll  可编辑卷帘: 画笔P/选择E · 右键删除 · 框选拉伸 · 快捷键
   与主窗口解耦: 通过 mw 引用查询播放态 / 提交刷新 / 试听 / 状态栏"""
from PySide6.QtCore import Qt, QTimer, QRectF, QPointF
from PySide6.QtGui import (QColor, QPen, QBrush, QFont, QPolygonF, QPainter,
                           QCursor, QPixmap)
from PySide6.QtWidgets import QApplication, QWidget, QSplitter, QDialog
from common import KB_W, HEADER_H, NOTE_MIN, NOTE_MAX, MAX_PPB
from midi_data import Note, retime
from model import EditSession, UNDO_MAX, EDITOR_TITLE   # (X 轮) 会话状态机迁至模型层
from view_roll import PianoRoll
from tempo_editor import TempoLane
from window_chrome import ChromeWindow
import snap as snap_mod             # (P1-B) 对齐服务: 档位+吸附纯函数
from i18n import t as tr        # 别名 tr: _do_* 系列里 t 是局部 tick 变量
import settings_store as store
import cursors                      # 统一风格工具指针
CLICK_EPS = 3.0          # 拖动启动阈值(px): 小于它视为点击, 不产生编辑
HANDLE_PX = 5.0          # 音符右缘改长手柄命中半宽
_PN = ('C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B')
def _nname(n):            # 本地音名 (免改文件头部的 import 列表)
    return f"{_PN[n % 12]}{n // 12 - 1}"
def _cursor_prefs(mw):
    """指针设置: (大小 standard/large, 选择样式 arrow/bracket)"""
    return (getattr(mw, 'cursor_size', 'standard') or 'standard',
            getattr(mw, 'select_cursor', 'arrow') or 'arrow')
def _tool_cursor(kind, dpr=1.0, size='standard', select_style='arrow'):
    """工具指针 (统一风格, 见 cursors.py): 准星 = 画笔/框选/删除, 箭头 = 选择/移动/复制"""
    return cursors.tool_cursor(kind, dpr, size, select_style)
class ToolIndicator(QWidget):
    """(FL 式) 当前工具指示框: 图标 + 名称, 实时反映当前功能; 图标与鼠标指针
       同一绘制函数 (cursors.draw_glyph), 指针与指示框永远一致"""
    LABELS = {'pencil': '画笔 P', 'select': '选择 E', 'move': '移动',
              'copy': '复制', 'rubber': '框选', 'erase': '删除'}
    def __init__(self):
        super().__init__()
        self.setFixedSize(92, 22)
        self.state = 'pencil'
        self.select_style = 'arrow'
    def set_state(self, s):
        if s in self.LABELS and s != self.state:
            self.state = s; self.update()
    def set_select_style(self, st):
        if st != self.select_style:
            self.select_style = st; self.update()
    def paintEvent(self, ev):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        p.setPen(QPen(QColor('#3a3a44'), 1)); p.setBrush(QColor(20, 20, 26, 210))
        p.drawRoundedRect(QRectF(0.5, 0.5, w - 1.0, h - 1.0), 3.0, 3.0)
        p.save()
        p.translate(3.0, (h - 18.0) / 2.0); p.scale(0.75, 0.75)   # 24 逻辑 → 18px 图标
        cursors.draw_glyph(p, self.state, self.select_style)
        p.restore()
        p.setPen(QColor('#d6d6de')); p.setFont(QFont('Segoe UI', 8))
        p.drawText(QRectF(24.0, 0, w - 26.0, h), Qt.AlignVCenter | Qt.AlignLeft,
                   tr(self.LABELS[self.state]))
class RollMiniMap(QWidget):
    """(FL 式) 顶部概览条: 整曲微缩音符 + 视野窗口。
       拖窗口 = 平移; 拖窗口右缘 = 连续缩放 (拉长看更多 / 拉短看更少,
       最长可到全曲 → 看到所有音符); 滚轮上 = 前进, 下 = 后退;
       点击窗口外 = 跳转并继续拖动。"""
    def __init__(self, roll):
        super().__init__()
        self.roll = roll
        self._mode = None                     # None / 'pan' / 'resize'
        self._press_x = 0.0; self._grab_center = 0.0
        self._notes_pm = None; self._cache_key = None   # (G-opt) 微缩音符位图缓存
        self.setFixedHeight(32)
    def _total(self):
        r = self.roll
        return max(1.0, r.total_tick) if r.tmap is not None else 1.0
    def _has_timeline(self) -> bool:
        """有音符、声组织或音频时长撑开时间轴 → 概览条可拖动。"""
        r = self.roll
        if r.tmap is None:
            return False
        if r.notes:
            return True
        if getattr(r, 'transcription', None) is not None:
            return True
        mw = getattr(r, 'mw', None)
        disp = float(getattr(mw, 'total_tick_display', 0) or 0) if mw else 0.0
        return r.total_tick > r.bar_ticks or disp > r.bar_ticks
    def _x_to_tick(self, x):
        return min(max(x / max(1.0, self.width()), 0.0), 1.0) * self._total()
    def paintEvent(self, ev):
        r = self.roll
        p = QPainter(self); w, h = self.width(), self.height()
        p.fillRect(0, 0, w, h, QColor('#101014'))
        if r.tmap is None or not self._has_timeline():
            p.setPen(QColor('#55555f')); p.setFont(QFont('Segoe UI', 8))
            p.drawText(self.rect(), Qt.AlignCenter,
                       tr('概览条: 打开 MIDI 或分析音频后在此拖动视野'))
            return
        total = self._total()
        if r.notes:
            # ---- (G-opt) 微缩音符位图缓存: 音符数/总长/尺寸不变则直接 blit ----
            key = (len(r.notes), round(r.total_tick, 1), w, h, getattr(r, '_data_ver', 0))
            if key != self._cache_key:
                self._cache_key = key
                dpr = self.devicePixelRatioF()
                pm = QPixmap(int(w * dpr), int(h * dpr))
                pm.setDevicePixelRatio(dpr); pm.fill(Qt.transparent)
                pp = QPainter(pm)
                lo = min(nt.note for nt in r.notes); hi = max(nt.note for nt in r.notes)
                span_n = max(12.0, float(hi - lo + 1))
                nh = max(1.2, (h - 6.0) / span_n)
                for nt in r.notes:
                    x = nt.start_tick / total * w
                    nw = max(1.0, nt.end_tick / total * w - x)
                    ny = 2.0 + (hi - nt.note) / span_n * (h - 6.0)
                    col = QColor(r.track_colors.get(getattr(nt, 'tid', 0), '#6f8fc0'))
                    pp.fillRect(QRectF(x, ny, nw, nh), col)
                pp.end()
                self._notes_pm = pm
            p.drawPixmap(0, 0, self._notes_pm)
        else:
            # 无声组织/MIDI 音符: 用声组织微缩条或时长占位, 仍显示视野窗口
            tx = getattr(r, 'transcription', None)
            tissue = getattr(tx, 'tissue', None) if tx else None
            blobs = list(getattr(tissue, 'blobs', None) or [])
            if blobs:
                for b in blobs:
                    x0 = b.start_tick / total * w
                    x1 = b.end_tick / total * w
                    bw = max(1.0, x1 - x0)
                    cy = h * 0.5
                    p.setPen(Qt.NoPen)
                    p.setBrush(QColor(200, 208, 218, 72))
                    p.drawRect(QRectF(x0, cy - 3.0, bw, 6.0))
            else:
                p.setPen(QColor('#3a4048'))
                p.drawLine(QPointF(2, h / 2), QPointF(w - 2, h / 2))
        # ---- (预加载轮) 缓冲圈可视化: 视口 ±M 屏预取范围 (仅展示, 不参与决策) ----
        ring = r.tiles.prefetch_span()
        if ring is not None:
            rx0 = ring[0] / self._total() * w
            rx1 = min(ring[1] / self._total() * w, float(w))
            p.setPen(QPen(QColor(255, 226, 168, 45), 1))
            p.setBrush(QColor(255, 226, 168, 14))
            p.drawRect(QRectF(rx0, 1.0, max(2.0, rx1 - rx0), h - 2.0))
        t0 = r.view_tick / total * w                      # 视野窗口
        t1 = (r.view_tick + r.visible_span()) / total * w
        p.setPen(QPen(QColor('#ffe2a8'), 1.4))
        p.setBrush(QColor(255, 226, 168, 30))
        p.drawRect(QRectF(t0, 1.0, max(6.0, t1 - t0), h - 2.0))
        p.setPen(QPen(QColor('#ffe2a8'), 1))                      # 右缘手柄竖纹
        for i in (-2.0, 0.0, 2.0):
            p.drawLine(QPointF(t1 - 3.0 + i, h / 2 - 4), QPointF(t1 - 3.0 + i, h / 2 + 4))
        if r.playhead_tick is not None:                           # 播放头
            px = r.playhead_tick / total * w
            p.setPen(QPen(QColor('#ff3b30'), 1))
            p.drawLine(QPointF(px, 0), QPointF(px, h))
    def mousePressEvent(self, ev):
        r = self.roll
        if r.tmap is None: return
        x = ev.position().x()
        t0 = r.view_tick / self._total() * self.width()
        t1 = (r.view_tick + r.visible_span()) / self._total() * self.width()
        if abs(x - t1) <= 6:
            self._mode = 'resize'             # 抓右缘: 拉长/拉短视野
        else:
            self._mode = 'pan'
            self._press_x = x
            self._grab_center = r.view_tick + r.visible_span() / 2
            if not (t0 <= x <= t1):
                r.set_view_center(self._x_to_tick(x))     # 点窗口外: 跳转
    def mouseMoveEvent(self, ev):
        r = self.roll
        if self._mode == 'pan':
            k = 0.25 if (ev.modifiers() & Qt.ShiftModifier) else 1.0   # (G1) Shift=精细滑动
            r.set_view_center(self._grab_center
                              + (ev.position().x() - self._press_x)
                              / max(1.0, self.width()) * self._total() * k)
        elif self._mode == 'resize':
            span = max(r._min_span(),
                       self._x_to_tick(ev.position().x()) - max(0.0, r.view_tick))
            r.set_view_span(span)
    def mouseReleaseEvent(self, ev):
        self._mode = None
    def wheelEvent(self, ev):
        dy = ev.angleDelta().y()
        if dy and self.roll.tmap is not None:
            # (H) 上=后退, 下=前进
            self.roll.pan_by((-0.05 if dy > 0 else 0.05) * self.roll.visible_span())
class EditorWindow(ChromeWindow):
    """编辑器宿主窗口 (FL 风格: 贴边/平滑圆角/细亮轮廓)"""
    RAD = 6                 # 可见的平滑真圆角
    BG = '#262b31'          # 暗黑不透明
    BORDER = '#565b61'      # 稍亮细边框
    FRAME_QSS = '#ChromeFrame { background:transparent; border:none; }'
    def __init__(self, mw):
        super().__init__(tr(EDITOR_TITLE))
        self._mw = mw
        self.resize(1180, 800)
    def closeEvent(self, ev):
        mw = self._mw
        if mw.edit_session is not None:
            if not mw._confirm_discard():
                ev.ignore(); return
            mw._discard_edits()
            mw._end_edit_session()
        super().closeEvent(ev)
class EditablePianoRoll(PianoRoll):
    """可编辑卷帘。数据即 mw.raw_notes(原地增删改), 松手统一 _commit。
       _drag 复用基类槽位, 种类: 'scrub'/'pan'(基类) +
       'move'/'resize'/'rubber'/'erase'(本类, [4]位="已入栈"标志,
       resize/move 追加 [5]=拉伸锚 'r'/'l'/'' 见 (20));
       画笔创建为点击即建 (记忆时值), 无拖拽状态"""
    _SNAP_CHOICES = snap_mod.SNAP_CHOICES         # (P1-B) 档位表迁至 snap.py (类别名兼容)
    def __init__(self, mw, span=5):
        super().__init__(span)
        self.mw = mw
        self.tool = 'pencil'                      # 'pencil' 画笔 / 'select' 选择
        self.selection = set()                    # 选中音符 nid 集
        self._press_snap = None                   # 按下时预捕获的快照(延迟入栈用)
        self._press_pos = (0.0, 0.0)              # 按下位置(纯点击判定)
        self._bubble = None                       # (x, y, text) 操作气泡
        self._guide_tick = None                   # 拖动中的吸附参考线
        self._guide_ticks = set()                 # (交互轮) 金色指示竖线集: 音符起始+结束
        self._hover_pos = None
        self._snap_mem = self.snap_beats if self.snap_beats is not None else 0.25
        self._erase_preview = None                # (17) 右键删除预览的音符 nid
        self._erase_marked = set()                # (交互轮) 滑删标记集 (淡红, 松手才删)
        self._pending_dup = None                  # (D2) Ctrl+拖拽待克隆的 nid 集
        self._ctrl_click = None                   # (D2) Ctrl 纯点击 (nid, 按下前是否已选)
        self._clipboard = []                      # (Q 轮) 内部剪贴板
        self._ph_preview = False                  # (R 轮) 指针预览中 (主窗不覆盖)
        self.active_tid = 0                       # (多音轨) 当前轨: 可编辑; 其他轨幽灵只读
        self.show_edge_banners = False            # (新) 编辑器不显示 ↑/↓ 剩余音符提示
        self.transcription = None                 # (扒谱) 声组织会话; None=正常模式
        self.show_tissue = True                   # 显示 Tonteppich / Sound Tissue
        self._drag_items = []                     # (G-opt) 拖动预计算: (音符, 原值) 对
        self._nid_map_c = None                    # (perf轮) nid->note 索引缓存
        self._nid_map_v = -1                      # (perf轮) 索引对应的 _data_ver
        self._last_hover = (None, None)           # (G-opt) 悬停节流: (x, 行)
        self._drag_copy = False                   # Ctrl+拖动复制进行中 (指针/指示框 = 复制)
        self.setMouseTracking(True)               # 无按键悬停也要刷新光标形状
        self.setCursor(self._cursor('pencil'))
    # ---------- (P2-E) 公开 API: 跨模块只经此读写编辑器状态 ----------
    def set_active_tid(self, tid):
        """当前轨切换 (甲板/新增轨/删轨回退使用; 不直改属性)"""
        self.active_tid = tid
    def discard_selection(self, nids):
        """从选区移除 nid 集 (删轨清理; 不直改 selection)"""
        self.selection = self.selection - set(nids)
    def set_label_keymap(self, km):
        self.label_keymap = km
    def set_note_center(self, lo, hi):
        """初始视野对准音符范围中点 (开编辑器时)"""
        self.view_note_start = (lo + hi) / 2 - 30
        self._clamp_view_note()
    def _draw_transcription_candidates(self, p):
        """扒谱声组织: 已烘焙进瓦片则跳过矢量 overlay (避免每帧卡顿)。"""
        if not getattr(self, 'show_tissue', True):
            return
        tx = self.transcription
        if tx is None:
            return
        if getattr(tx, 'tissue_ready', False):
            return
        if hasattr(tx, 'draw_tissue'):
            tx.draw_tissue(p, self)
    def snap_label(self):
        """对齐档位显示文本 (公开只读)"""
        return self._snap_label()
    # ---------- 吸附 ----------
    def _snap_ticks(self):
        """当前对齐档位对应的 tick 数; None = tick 级。
           按住 Alt 临时反转 (6): 开→关, 关→回到上一档位 (FL 同款)"""
        snap = self.snap_beats
        if QApplication.keyboardModifiers() & Qt.AltModifier:
            snap = (self._snap_mem or 0.25) if snap is None else None
        bt = self.bar_ticks
        if snap == 'bar' and self.tmap is not None:
            tsm = getattr(self.mw, 'tsig_map', None)
            if tsm is not None:
                bt = tsm.bar_ticks_at(self._last_hover[0]
                                      if self._last_hover else 0)
        return snap_mod.snap_ticks(snap, self.tmap.tpb if self.tmap else None,
                                   bt, self.ppb)   # (Line轮) ppb 供自适应档
    def _snap_floor(self, t):
        tsm = getattr(self.mw, 'tsig_map', None)
        if (self.snap_beats == 'bar' and self.tmap is not None
                and tsm is not None and len(tsm.events()) > 1):
            return tsm.measure_start(t)          # (二期) 分段拍号: 小节起点精确吸附
        st = self._snap_ticks() or snap_mod.min_step_ticks(
            self.tmap.tpb if self.tmap else None)   # (最小移动轮) 无对齐 ≥1/96 拍
        return snap_mod.snap_floor(t, st)
    def _snap_round(self, t):
        tsm = getattr(self.mw, 'tsig_map', None)
        if (self.snap_beats == 'bar' and self.tmap is not None
                and tsm is not None and len(tsm.events()) > 1):
            m0 = tsm.measure_start(t)            # 分段: 就近小节起点 (向前/向后半小节判定)
            return (m0 + tsm.bar_ticks_at(m0)
                    if t - m0 >= tsm.bar_ticks_at(m0) / 2.0 else m0)
        st = self._snap_ticks() or snap_mod.min_step_ticks(
            self.tmap.tpb if self.tmap else None)
        return snap_mod.snap_round(t, st)
    def _snap_label(self):
        for lbl, v in self._SNAP_CHOICES:
            if v == self.snap_beats: return tr(lbl)
        return tr('自定义')
    def set_snap(self, snap):
        """(D6) 对齐档位设置入口 (菜单/G 键共用); 同步按钮 + 持久化 (30③)"""
        if snap is not None: self._snap_mem = snap
        self.snap_beats = snap
        store.save_snap(snap)
        self.set_status(tr('对齐: {s}', s=self._snap_label()))
        if getattr(self.mw, 'b_snap', None) is not None:
            self.mw._sync_snap_btn()
        self.update()
    def _cycle_snap(self):                        # G 键: 按菜单顺序循环
        vals = [v for _lbl, v in self._SNAP_CHOICES]
        i = vals.index(self.snap_beats) if self.snap_beats in vals else 0
        self.set_snap(vals[(i + 1) % len(vals)])
    def wheelEvent(self, ev):
        """(Q 轮) 编辑器滚轮体系:
           拖动中 Shift+滚轮 = 平移视野并按当前指针重新落点 (可画超窗口长音符, 精确到对齐格)
           Shift+滚轮 = 左右滚动 | Ctrl+滚轮 = 上下缩放(可见八度 1..8) | Alt+滚轮 = 左右缩放
           标尺行滚轮 = 视野缩放 (G1 保留) | 普通滚轮 = 上下滚动音域 (键盘/画布统一)"""
        if self.tmap is None: return
        dy, dx = ev.angleDelta().y(), ev.angleDelta().x()
        mods = ev.modifiers()
        pos = ev.position(); mx, my = pos.x(), pos.y()
        if self._drag is not None and (mods & Qt.ShiftModifier):
            # 拖动中平移: 视野移动后按当前指针位置重新落点 (音符随之延伸/移动)
            self.view_tick += (0.15 if dy < 0 else -0.15) * self.visible_span()
            self._clamp_view()
            kind = self._drag[0]
            if kind == 'move': self._do_move(mx, my)
            elif kind == 'resize': self._do_resize(mx, my)
            elif kind == 'scale': self._do_scale(mx, my)
        elif mods & Qt.ShiftModifier:             # 左右滚动 (上=后退, 下=前进)
            self.view_tick += (-0.15 if dy > 0 else 0.15) * self.visible_span()
            self._clamp_view()
        elif mods & Qt.ControlModifier:           # 上下缩放: 可见八度跨度 1..8
            n = self.view_oct_span + (-1 if dy > 0 else 1) * max(1, abs(dy) // 120)
            self.view_oct_span = int(max(1, min(8, n)))
            self._clamp_view_note()
            self._bgV_key = None                  # 跨度并入 bgV key
            self.tiles.clear()                   # (P3-G) 经渲染器作废
        elif mods & Qt.AltModifier:               # 左右缩放 (光标锚点)
            anchor = self.tick_of_x(mx)
            f = 1.15 if dy > 0 else 1 / 1.15
            self.ppb = float(min(MAX_PPB, max(self.min_ppb(), self.ppb * f)))
            self.view_tick = anchor - (mx - KB_W) / self.ppb * self.tmap.tpb
            self._clamp_view()
            if self.qml is not None: self.qml.zoom_hold_on()   # (性能回归第8步)
        elif my < HEADER_H and dy:                # 标尺行: 视野缩放 (G1 保留)
            f = 1.15 if dy > 0 else 1 / 1.15
            anchor = self.tick_of_x(mx)
            self.ppb = float(min(MAX_PPB, max(self.min_ppb(), self.ppb * f)))
            self.view_tick = anchor - (mx - KB_W) / self.ppb * self.tmap.tpb
            self._clamp_view()
            if self.qml is not None: self.qml.zoom_hold_on()   # (性能回归第8步)
        else:                                     # 上下滚动音域 (键盘/画布统一)
            # (滚动轮·FL 同款) 整行对齐滚动: 滚轮增量累加, 视野按整行取整 ——
            # 顶部/底部不再留半行残条, 点击目标行不会错位 (防误触)
            self._vscroll_acc = getattr(self, '_vscroll_acc', 0.0) + \
                (dy if dy else dx) / 120.0
            rows = int(self._vscroll_acc)
            if rows:
                self._vscroll_acc -= rows
                self.view_note_start = int(self.view_note_start) + rows
            self._clamp_view_note()
        self.request_update(); self.viewChanged.emit()
    # ---------- 命中测试 / 坐标 ----------
    _COLS_RED = (QColor(255, 156, 156), QColor(122, 61, 61))
    _COLS_GHOST = (QColor(126, 130, 142, 80), QColor(168, 174, 188, 110))
    def _note_colors(self, nt, is_active):
        """(多音轨) 当前轨 = 正常轨道色; 其他轨 = 灰色半透明幽灵 (FL 式, 只读)。
           (交互轮) 滑删标记 / 拖动中的选中音符 = 淡红 (判定先于幽灵轨)
           (perf轮 P3) 返回类级共享元组: draw_notes_range 按身份判同复用笔刷"""
        nid = getattr(nt, 'nid', None)
        if getattr(self, '_erase_marked', None) and nid in self._erase_marked:
            return self._COLS_RED
        k = self._drag[0] if self._drag else None
        if k in ('move', 'resize', 'scale') and nid in self.selection:
            return self._COLS_RED
        if getattr(nt, 'tid', 0) != self.active_tid:
            return self._COLS_GHOST
        return super()._note_colors(nt, is_active)
    def _dynamic_nids(self):
        """(预加载轮) 仅"正在被拖动改形"的音符实时绘制并从瓦片剔除:
           move/resize 越阈值后 = 选区 (起点处旧位图须抹除防残影; 未越阈值 =
           纯点击, 空集); create = 新音符 (落地时 _commit 作废重烘);
           纯点击选择/框选 = 空集 —— 选中态由瓦片位图+覆盖层描边表达,
           选中/取消选中不再整体重烘可见瓦片"""
        k = self._drag[0] if self._drag else None
        if k in ('move', 'resize', 'scale'):
            return set(self.selection) if self._drag[4] else set()
        if k == 'erase':                          # (交互轮) 标记淡红 + 悬停描边走实时层
            marked = set(getattr(self, '_erase_marked', set()))
            if self._erase_preview: marked.add(self._erase_preview)
            return marked
        return set()
    def _nid_map(self):
        """(perf轮) nid->note 索引 (随 _data_ver 失效): overlay 描边/删除标记
           O(1) 取对象, 取代每帧全量扫可见候选"""
        if self._nid_map_c is None or self._nid_map_v != self._data_ver:
            self._nid_map_c = {getattr(nt, 'nid', id(nt)): nt
                               for nt in self.notes}
            self._nid_map_v = self._data_ver
        return self._nid_map_c
    def _live_note_objects(self):
        """(perf轮) 覆写: 播放高亮 + 拖动/新建/删除标记音符 (与 _dynamic_nids
           同状态源, 直接给对象, 免逐帧 nid 过滤扫描)"""
        out = super()._live_note_objects()
        d = self._drag
        k = d[0] if d else None
        if k in ('move', 'resize', 'scale'):
            if d[4]:                              # 已越阈值入栈: 拖动项实时绘制
                out += [(nt.nid, nt) for nt, _o in self._drag_items]
        elif k == 'erase':
            m = self._nid_map()
            for nid in self._erase_marked:
                nt = m.get(nid)
                if nt is not None: out.append((nid, nt))
            if self._erase_preview:
                nt = m.get(self._erase_preview)
                if nt is not None: out.append((self._erase_preview, nt))
        return out
    def _hit_test(self, x, y):
        """返回 (音符, 边缘手柄); 手柄: 'r'=右缘改长 / 'l'=左缘反向缩放 (20)
           (多音轨) 仅命中当前轨, 其他轨幽灵只读"""
        if self.tmap is None or x < KB_W or y < HEADER_H: return None, None
        n = self._note_at_y(y)
        if n is None: return None, None
        t = self.tick_of_x(x)
        best = None
        for nt in self.visible_notes(self.view_tick, self.tick_of_x(self.width())):
            if getattr(nt, 'tid', 0) != self.active_tid: continue
            if nt.note == n and nt.start_tick <= t < nt.end_tick:
                if best is None or nt.start_tick >= best.start_tick: best = nt
        if best is None: return None, None
        if abs(x - self.x_of_tick(best.end_tick)) <= HANDLE_PX: return best, 'r'
        if abs(x - self.x_of_tick(best.start_tick)) <= HANDLE_PX: return best, 'l'
        return best, None
    def _ticks_str(self, t):
        t = max(0, t)
        bar = int(t // self.bar_ticks) + 1
        beat = int((t % self.bar_ticks) // self.tmap.tpb) + 1
        return f"{bar}.{beat}"
    def _default_len(self):
        return max(1, int(self.tmap.tpb * 2))     # 首次创建默认 2 分音符 (2 拍), 之后沿用记忆
    def _create_len(self):
        """(交互改版) 新音符时值 = 记忆时值 (点其他音符可记录); 无记忆 = 2 分音符"""
        return max(1, int(self.mw.edit_session.last_len_ticks or self._default_len()))
    # ---------- 状态 / 试听 ----------
    def set_status(self, text):
        """EditSession._notify 与各操作都会调用: 显示到主窗口状态栏并重绘"""
        try: self.mw.statusBar().showMessage(text, 4000)
        except Exception: pass
        self.update()
    def _ping(self, note):
        """短促试听 (新建音符 / 拖动变调时)"""
        if note is None: return
        self.mw._preview(note, True)
        QTimer.singleShot(130, lambda: self.mw._preview(note, False))
    def _ping_note(self, nt):
        """单击已有音符试听: 走该音符所属轨音源, 按时值发声 (约 80~600ms)。"""
        if nt is None:
            return
        mw = self.mw
        ch = mw.engine.track_channels.get(nt.tid, 0)
        vel = max(1, min(127, int(nt.vel)))
        pitch = int(nt.note)
        mw.engine.noteon(pitch, vel, ch)
        if self.tmap is not None:
            dur = (self.tmap.tick2sec(nt.end_tick)
                   - self.tmap.tick2sec(nt.start_tick))
            ms = int(max(0.08, min(0.6, float(dur))) * 1000)
        else:
            ms = 150
        QTimer.singleShot(ms, lambda p=pitch, c=ch: mw.engine.noteoff(p, c))
    def _set_bubble(self, x, y, text):
        self._bubble = (x, y, text)
    # ---------- 编辑提交 ----------
    def _start_editing(self):
        """拖动首次越过阈值 / 首次真删除: 压入预捕获快照。
           (28) 播放中改动被忽略: 调用方需先确认 self.mw._is_playing() 为 False"""
        self.mw.edit_session.push(self._press_snap)
        self._press_snap = None
    def _commit(self):
        """一次编辑落地: 排序 + 重算 sec + 主窗口重建(播放数据/统计/各卷帘同步)"""
        mw = self.mw
        mw.raw_notes.sort(key=lambda n: (n.start_tick, n.note))
        retime(mw.raw_notes, self.tmap)
        mw._editor_commit()
        self.set_status(tr('共 {n} 个音符 · 选中 {m}',
                          n=len(mw.raw_notes), m=len(self.selection)))
    # ---------- 按下分发 ----------
    def mousePressEvent(self, ev):
        if self.tmap is None: return
        pos = ev.position(); x, y = pos.x(), pos.y()
        r = self.mw.router                        # (Y 轴) 手势仲裁
        if y < HEADER_H and x >= KB_W                 and ev.button() == Qt.RightButton:
            # (标记轮) 标尺右键: 标记 BPM / 调性 (点击位置 = tick 语义)
            self._show_ruler_menu(x, ev.globalPosition().toPoint())
            ev.accept(); return
        if y < HEADER_H and x >= KB_W:            # 标尺: 擦洗定位(基类)
            if not r.begin(r.OWNER_MIDI): ev.accept(); return
            self._begin_scrub(x); return
        if x < KB_W and y >= HEADER_H:            # 键盘侧栏: 试听(基类)
            n = self._note_at_y(y)
            if n is not None:
                self.preview_note = n; self.notePreview.emit(n, True); self.update()
            return
        if ev.button() == Qt.MiddleButton:        # 中键: 平移(基类)
            if not r.begin(r.OWNER_MIDI): ev.accept(); return
            self._begin_pan(x); return
        if ev.button() == Qt.RightButton:         # 右键: 删除(可拖动清扫)
            if not r.begin(r.OWNER_MIDI): ev.accept(); return
            self._press_right(x, y); return
        if ev.button() == Qt.LeftButton:
            if not r.begin(r.OWNER_MIDI): ev.accept(); return
            self._press_edit(x, y); ev.accept()
    # ---------- (标记轮) 标尺右键标记: BPM / 节拍 / 调性 ----------
    def _show_ruler_menu(self, x, gpos):
        """标尺右键菜单 (FL 式): 点击位置 = tick 语义。
           非模态 popup + triggered —— 旧 exec 模态循环在真实平台会吞掉
           菜单关闭后的左键事件, 导致标尺擦洗失灵 (用户实测)"""
        from PySide6.QtWidgets import QMenu
        tick = max(0, int(round(self.tick_of_x(x))))
        menu = QMenu(self)
        a_bpm = menu.addAction(tr('标记 BPM…'))
        a_meter = menu.addAction(tr('标记节拍…'))
        a_key = menu.addAction(tr('标记调性…'))
        a_bpm.triggered.connect(lambda checked=False: self._mark_bpm(tick))
        a_meter.triggered.connect(lambda checked=False: self._mark_meter(tick))
        a_key.triggered.connect(lambda checked=False: self._mark_key())
        menu.popup(gpos)                          # 非模态: 不干扰左键擦洗

    def _mark_meter(self, tick):
        """节拍标记 (二期): 吸附点击位置所在小节起点, 从该处起变更拍号段
           (后段保留; 全量重建联动 卷帘网格/演奏谱/悬浮谱/状态区)"""
        from PySide6.QtWidgets import (QDialog, QHBoxLayout, QVBoxLayout,
                                       QLabel, QSpinBox, QComboBox, QPushButton)
        from window_chrome import fade_scale_in
        tsm = self.mw.tsig_map
        m_start = tsm.measure_start(tick)          # 吸附所在小节起点
        num0, den0 = tsm.at(m_start)
        dlg = QDialog(self)
        dlg.setWindowTitle(tr('标记节拍'))
        v = QVBoxLayout(dlg)
        row = QHBoxLayout()
        row.addWidget(QLabel(tr('节拍:')))
        sp_n = QSpinBox(); sp_n.setRange(1, 32); sp_n.setValue(num0)
        cmb_d = QComboBox()
        for dn in (2, 4, 8, 16):
            cmb_d.addItem(f'/ {dn}', dn)
        cmb_d.setCurrentIndex(max(0, cmb_d.findData(den0)))
        row.addWidget(sp_n); row.addWidget(cmb_d)
        v.addLayout(row)
        bb = QHBoxLayout(); bb.addStretch(1)
        b_cancel = QPushButton(tr('取消')); b_cancel.clicked.connect(dlg.reject)
        b_ok = QPushButton(tr('确定')); b_ok.setDefault(True)
        b_ok.clicked.connect(dlg.accept)
        bb.addWidget(b_cancel); bb.addWidget(b_ok)
        v.addLayout(bb)
        fade_scale_in(dlg)
        if dlg.exec() != QDialog.Accepted: return
        self.mw._set_meter_segment(m_start, sp_n.value(), cmb_d.currentData())
        self.set_status(tr('节拍已标记 {n}/{d} (自小节 {m} 起)',
                           n=sp_n.value(), d=cmb_d.currentData(),
                           m=int(m_start / (self.mw.bar_ticks)) + 1))

    def _mark_bpm(self, tick):
        """在 tick 处标记 BPM: 预填该位置当前值, 确定后写入并五处联动"""
        from PySide6.QtWidgets import (QDialog, QHBoxLayout, QVBoxLayout,
                                       QLabel, QDoubleSpinBox, QPushButton)
        from window_chrome import fade_scale_in
        tmap = self.mw.tmap
        dlg = QDialog(self)
        dlg.setWindowTitle(tr('标记 BPM'))
        v = QVBoxLayout(dlg)
        row = QHBoxLayout()
        row.addWidget(QLabel(tr('BPM:')))
        sp = QDoubleSpinBox(); sp.setRange(20.0, 400.0); sp.setDecimals(1)
        sp.setValue(float(tmap.bpm_at_tick(tick)))
        sp.setToolTip(tr('20–400; 该位置已有速度事件则原地修改, 否则从此处插入新速度段'))
        row.addWidget(sp)
        v.addLayout(row)
        bb = QHBoxLayout(); bb.addStretch(1)
        b_cancel = QPushButton(tr('取消')); b_cancel.clicked.connect(dlg.reject)
        b_ok = QPushButton(tr('确定')); b_ok.setDefault(True)
        b_ok.clicked.connect(dlg.accept)
        bb.addWidget(b_cancel); bb.addWidget(b_ok)
        v.addLayout(bb)
        fade_scale_in(dlg)
        if dlg.exec() != QDialog.Accepted: return
        self._apply_mark_bpm(tick, float(sp.value()))

    def _apply_mark_bpm(self, tick, bpm):
        """BPM 标记落地: 复合入撤销栈 + _apply_tempo_change 五处联动 (测试直调)"""
        tmap = self.mw.tmap
        idx = tmap.index_at(tick)
        if idx >= 0:
            self.mw.model.tempo_set(idx, bpm)      # 该位置已有速度事件: 原地改
        else:
            self.mw.model.tempo_insert(tick, bpm)  # 没有: 从此插入新速度段
        self.mw._apply_tempo_change()
        self.set_status(tr('已标记 BPM={b:g} (位置 {t} ticks) — Ctrl+Z 可还原',
                           b=bpm, t=tick))

    def _mark_key(self):
        """调性标注: 显示用元数据 (简谱固定 1=C 记谱, 不影响数字)"""
        from PySide6.QtWidgets import (QDialog, QHBoxLayout, QVBoxLayout,
                                       QLabel, QComboBox, QPushButton)
        from window_chrome import fade_scale_in
        keys = ('1=C', '1=G', '1=D', '1=A', '1=E', '1=B', '1=#F', '1=#C',
                '1=F', '1=bB', '1=bE', '1=bA', '1=bD', '1=bG')
        cur = str(getattr(self.mw, 'key_label', '1=C'))
        dlg = QDialog(self)
        dlg.setWindowTitle(tr('标记调性'))
        v = QVBoxLayout(dlg)
        row = QHBoxLayout()
        row.addWidget(QLabel(tr('调性:')))
        cmb = QComboBox()
        cmb.addItems(keys)
        cmb.setCurrentIndex(max(0, keys.index(cur)))
        cmb.setToolTip(tr('标注显示于悬浮谱左上角; 简谱数字仍按 1=C 记谱'))
        row.addWidget(cmb)
        v.addLayout(row)
        bb = QHBoxLayout(); bb.addStretch(1)
        b_cancel = QPushButton(tr('取消')); b_cancel.clicked.connect(dlg.reject)
        b_ok = QPushButton(tr('确定')); b_ok.setDefault(True)
        b_ok.clicked.connect(dlg.accept)
        bb.addWidget(b_cancel); bb.addWidget(b_ok)
        v.addLayout(bb)
        fade_scale_in(dlg)
        if dlg.exec() != QDialog.Accepted: return
        self._apply_mark_key(keys[cmb.currentIndex()])

    def _apply_mark_key(self, key):
        """调性标注落地: 存档 + 悬浮谱左上角同步 (测试直调)"""
        self.mw._set_key_label(key)
        self.set_status(tr('调性已标注 {k} (显示标注, 不改变简谱数字)', k=key))

    def _press_edit(self, x, y):
        n = self._note_at_y(y)
        if n is None: return
        mods = QApplication.keyboardModifiers()
        # (UI轮) 选区尾部缩放柄优先命中 (Shift/Ctrl 加选时让位走音符/框选)
        if len(self.selection) > 1 and self._hit_scale_handle(x, y) \
                and not (mods & (Qt.ShiftModifier | Qt.ControlModifier)):
            self._begin_scale_drag(x, y)
            return
        nt, edge = self._hit_test(x, y)
        if nt is not None:                        # 点在音符上: 选择 + 准备拖动/拉伸
            dup = bool(mods & Qt.ControlModifier)
            sh = bool(mods & Qt.ShiftModifier) and not dup   # (Q 轮) Shift 加选
            was_sel = nt.nid in self.selection
            if dup and not was_sel:
                self.selection = self.selection | {nt.nid}
            elif sh and not was_sel:
                self.selection = self.selection | {nt.nid}
            elif not dup and not sh and nt.nid not in self.selection:
                self.selection = {nt.nid}
            self._ctrl_click = (nt.nid, was_sel) if dup else None
            self._begin_note_drag(x, y, nt, edge, dup=dup)
            return
        if self.tool == 'pencil':                 # 空白: 画笔画音符 / 选择框选
            self._begin_create(x, y, n)
        else:
            base = (set(self.selection)
                    if mods & (Qt.ShiftModifier | Qt.ControlModifier) else set())  # (12) Shift 加选
            self._drag = ('rubber', x, y, x, y, base)
            self.setCursor(self._cursor('rubber'))
            self._sync_tool_hint(); self.update()
    def _begin_note_drag(self, x, y, grab, edge, dup=False):
        """按下已有音符: 预捕获快照(纯点击不进撤销栈), 记录各选中音符原始值。
           dup=True (Ctrl): 越过阈值时克隆整个选区并拖动克隆体 (D2)"""
        self._press_snap = self.mw.edit_session.capture()
        self._press_pos = (x, y)
        orig = {o.nid: (o.start_tick, o.end_tick, o.note)
                for o in self.mw.raw_notes if o.nid in self.selection}
        self._drag_items = [(nt, orig[nt.nid]) for nt in self.mw.raw_notes
                            if nt.nid in orig]    # (G-opt) 拖动只遍历选中项
        t = self._snap_round(self.tick_of_x(x))
        anchor = edge if edge else ''             # (20) 'r'/'l'/''
        if edge:   # (UI轮) resize 元组第7位 = 被抓音符本体 (方块只调该音符时值)
            self._drag = ('resize', t, grab.note, orig, False, anchor, grab)
        else:
            self._drag = ('move', t, grab.note, orig, False, anchor)
        self._pending_dup = set(orig) if dup else None
        if not edge:
            self.setCursor(self._cursor('copy' if dup else 'move'))
        self._sync_tool_hint()
        self.update()
    def _restore_ph(self):
        """拖动结束: 恢复真实播放位置"""
        self._ph_preview = False
        if self.tmap is not None:
            self.playhead_tick = self.tmap.sec2tick(self.mw.cur_sec)
        self.update()
    def _begin_create(self, x, y, n):
        """画笔: 点击即创建 —— 时值 = 记忆时值 (点其他音符可记录), 无记忆默认
           2 分音符; 旧"拖拽定长"模式已取消。起始按对齐吸附, 一步撤销。
           (28) 播放中改动被忽略: 拒绝并提示"""
        if self.mw._is_playing():
            self.set_status(tr('播放中 · 改动被忽略 (暂停/停止后可编辑; 选择与浏览不受限)'))
            return
        t0 = self._snap_floor(self.tick_of_x(x))
        note = Note(n, 100, t0, t0 + self._create_len(),
                    0.0, 0.0, tid=self.active_tid)   # 新音符归属当前轨 (多音轨)
        self.mw.model.add_notes([note])       # push+追加+retime 一步 (可 Ctrl+Z)
        self.selection = {note.nid}
        self._ping(n)
        self._commit()
        self._set_bubble(x, y, tr('{nn} · 长 {l:g}拍',
                                 nn=_nname(n), l=(note.end_tick - t0) / self.tmap.tpb))
    def _press_right(self, x, y):
        if self.mw._is_playing():                 # (28) 播放中忽略改动
            self.set_status(tr('播放中 · 改动被忽略 (暂停/停止后可编辑; 选择与浏览不受限)'))
            return
        nt, _e = self._hit_test(x, y)
        self._erase_preview = nt.nid if nt is not None else None   # (17) 红描边预览
        self._press_snap = self.mw.edit_session.capture()
        self._press_pos = (x, y)
        self._drag = ('erase', False)             # 首次真删除才入栈; 纯点击在释放时删
        self.setCursor(self._cursor('erase'))     # 删除态: 准星 + 红色禁止角标
        self._sync_tool_hint()
        self.update()
    # ---------- 拖动处理 ----------
    def mouseMoveEvent(self, ev):
        pos = ev.position(); x, y = pos.x(), pos.y()
        if self._drag is None:
            self._hover_pos = (x, y)
            row = self._note_at_y(y)              # (G-opt) 行未变且位移小 → 跳过重测
            lx, lrow = self._last_hover
            if row != lrow or abs(x - lx) > 2:
                self._last_hover = (x, row)
                self._update_hover_cursor(x, y)
            return
        if not self.mw.router.check(self.mw.router.OWNER_MIDI): return   # (Y 轮) 手势校验
        kind = self._drag[0]
        if kind == 'scrub':
            self._do_scrub(x)
        elif kind == 'pan':                       # 基类平移逻辑
            self.view_tick = self._drag[2] - (x - self._drag[1]) / self.ppb * self.tmap.tpb
            self._clamp_view(); self.update(); self.viewChanged.emit()
        elif kind == 'move': self._do_move(x, y)
        elif kind == 'resize': self._do_resize(x, y)
        elif kind == 'scale': self._do_scale(x, y)
        elif kind == 'rubber': self._do_rubber(x, y)
        elif kind == 'erase': self._do_erase(x, y)
    def _do_move(self, x, y):
        d = self._drag
        _k, t_press, n_press, orig, pushed = d[:5]
        if not pushed:                            # 未越过阈值前不动数据
            px, py = self._press_pos
            if abs(x - px) < CLICK_EPS and abs(y - py) < CLICK_EPS: return
            if self.mw._is_playing():             # (28) 播放中忽略改动
                self._drag = None; self._press_snap = None
                self._pending_dup = None; self._ctrl_click = None
                self.set_status(tr('播放中 · 改动被忽略 (暂停/停止后可编辑; 选择与浏览不受限)'))
                self.update(); return
            self._start_editing()
            if self._pending_dup:                 # (D2) Ctrl+拖拽: 克隆选区再拖
                clones = [Note(nt.note, nt.vel, nt.start_tick, nt.end_tick,
                               nt.start_sec, nt.end_sec, tid=nt.tid)
                          for nt in self.mw.raw_notes if nt.nid in self._pending_dup]
                self.mw.model.append_notes(clones)   # (X 轮) 原地追加 (栈已入)
                self.selection = {c.nid for c in clones}
                orig = {c.nid: (c.start_tick, c.end_tick, c.note) for c in clones}
                self._drag_items = list(zip(clones, [orig[c.nid] for c in clones]))
                self._pending_dup = None
                self._drag_copy = True
                self._drag = ('move', t_press, n_press, orig, True, '')
            else:
                self._drag = ('move', t_press, n_press, orig, True, d[5])
        t = self._snap_round(self.tick_of_x(x))
        dx = t - t_press
        dn = 0
        n = self._note_at_y(y)
        if n is not None: dn = n - n_press
        if orig:                                  # 组整体钳制, 保持和弦形状
            lo = min(v[2] for v in orig.values()); hi = max(v[2] for v in orig.values())
            dn = max(dn, NOTE_MIN - lo); dn = min(dn, NOTE_MAX - hi)
        pitch_changed = False
        for nt, o in self._drag_items:            # (G-opt) 只遍历选中项
            s = max(0, o[0] + dx); e = max(s + 1, o[1] + dx); nn = o[2] + dn
            if nt.note != nn: pitch_changed = True
            self.mw.model.set_note_span(nt, s, e)            # (X 轮) 原语写 tick
            if nt.note != nn: self.mw.model.set_note_pitch(nt, nn)
        if pitch_changed and len(orig) == 1:
            self._ping(next(iter(orig.values()))[2] + dn)
        self._guide_tick = t                # (交互轮) 红色指针不再随手势移动
        self._guide_ticks = {min(nt.start_tick for nt, _o in self._drag_items),
                             max(nt.end_tick for nt, _o in self._drag_items)}
        tpb = self.tmap.tpb
        if len(orig) == 1:
            o = next(iter(orig.values()))
            s = max(0, o[0] + dx); e = max(s + 1, o[1] + dx)
            self._set_bubble(x, y, tr('{nn} · {pos} · 长 {l:g}拍',
                                     nn=_nname(o[2] + dn), pos=self._ticks_str(s),
                                     l=(e - s) / tpb))
        else:
            self._set_bubble(x, y, tr('{n}个音符 · Δ{d:+g}拍 · {p:+d}半音',
                                     n=len(orig), d=dx / tpb, p=dn))
        self.request_update(self.roll_rect())
    def _do_resize(self, x, y):
        _k, t_press, grab, orig, pushed, anchor, grab_nt = self._drag
        if not pushed:
            px, py = self._press_pos
            if abs(x - px) < CLICK_EPS: return
            if self.mw._is_playing():             # (28) 播放中忽略改动
                self._drag = None; self._press_snap = None
                self.set_status(tr('播放中 · 改动被忽略 (暂停/停止后可编辑; 选择与浏览不受限)'))
                self.update(); return
            self._start_editing()
            self._drag = ('resize', t_press, grab, orig, True, anchor, grab_nt)
        t = self._snap_round(self.tick_of_x(x))
        self._apply_resize(orig, t - t_press, anchor, x, y)
        self._guide_tick = t                # (交互轮) 红色指针不再随手势移动
        self._guide_ticks = {grab_nt.start_tick, grab_nt.end_tick}
        self.request_update(self.roll_rect())
    def _apply_resize(self, orig, dx, anchor, x, y):
        """拉伸 (UI轮 2026-09-08 语义定稿): 音符左右缘方块 = 统一调整被框选的
           所有音符时值 (右缘: 全体终点 +dx / 左缘: 全体起点 +dx, 时值随动)。
           组等比缩放 = 选区包围盒尾部手柄 (_do_scale), 两者不混。
           钳制: 左缘起点≥0 / 终点≥起点+最短 (最短=对齐步长);
           写入走 _drag_items (raw 层对象, 与渲染层不保证同一身份)。"""
        if not orig: return
        tpb = self.tmap.tpb
        min_len = self._snap_ticks() or 1
        items = [(nt, o) for nt, o in self._drag_items if nt.nid in orig]
        if not items: return
        if anchor == 'l':                         # 左缘方块: 全体起点 +dx
            for nt, o in items:
                self.mw.model.set_note_pos(
                    nt, max(0, min(o[1] - min_len, o[0] + dx)))
            self._set_bubble(x, y, tr('{n}个音符 · 左缘 {d:+g}拍',
                                     n=len(items), d=dx / tpb))
        else:                                     # 右缘方块: 全体终点 +dx
            for nt, o in items:
                self.mw.model.set_note_end(nt, max(o[0] + min_len, o[1] + dx))
            self._set_bubble(x, y, tr('{n}个音符 · 右缘 {d:+g}拍',
                                     n=len(items), d=dx / tpb))
    def _selection_bounds(self):
        """选区包围盒 (画布区 widget px): (bx0, by0, bx1, by1) / None。
           覆盖层虚线框与尾部缩放柄共用同一几何"""
        if not self.selection: return None
        bx0 = by0 = 1e9; bx1 = by1 = -1e9
        lo, hi, rh = self.note_low, self.note_high, self.row_h()
        y_off = (self.view_note_start - lo) * rh
        w = self.width()
        for nt in self.visible_notes(self.view_tick, self.tick_of_x(w)):
            if nt.nid not in self.selection: continue
            if not (lo - 1 <= nt.note <= hi + 1): continue
            x0 = self.x_of_tick(nt.start_tick); x1 = self.x_of_tick(nt.end_tick)
            if x1 < KB_W or x0 > w: continue
            y = HEADER_H + (hi - nt.note) * rh - y_off + 1.0
            nh = max(rh - 1.0, 2.0)
            x0 = max(x0, KB_W + 1.0); x1 = min(x1, float(w) - 1.0)
            if x1 - x0 < 6.0: x1 = x0 + 6.0
            bx0 = min(bx0, x0); bx1 = max(bx1, x1)
            by0 = min(by0, y); by1 = max(by1, y + nh)
        if bx1 <= bx0: return None
        return (bx0, by0, bx1, by1)
    def _scale_handle_pos(self):
        """缩放手柄位置: 选区尾缘 + 1/2 拍 (视觉呼吸间隔), 垂直居中。
           返回 (x, y) 画布像素 / None"""
        if len(self.selection) < 2: return None
        if self._drag is not None and self._drag[0] == 'rubber': return None
        b = self._selection_bounds()
        if b is None: return None
        return (b[2] + self.ppb / 2.0, (b[1] + b[3]) / 2.0)
    def _hit_scale_handle(self, x, y):
        """缩放手柄命中 (多选且非框选中): 手柄 ±(HANDLE_PX+4, 9)px"""
        pos = self._scale_handle_pos()
        if pos is None: return False
        return abs(x - pos[0]) <= HANDLE_PX + 4 and abs(y - pos[1]) <= 9
    def _begin_scale_drag(self, x, y):
        """选区尾部手柄按下: 组等比缩放入场 (快照/原始值记录同音符拖拽)"""
        self._press_snap = self.mw.edit_session.capture()
        self._press_pos = (x, y)
        orig = {o.nid: (o.start_tick, o.end_tick, o.note)
                for o in self.mw.raw_notes if o.nid in self.selection}
        self._drag_items = [(nt, orig[nt.nid]) for nt in self.mw.raw_notes
                            if nt.nid in orig]    # (G-opt) 只遍历选中项
        self._drag = ('scale', self.tick_of_x(x), None, orig, False, '')
        # (缩放变速轮) 记录 tempo 原始事件表供 Esc 回退/复合撤销; bpm0 在首帧取
        self._scale_tevents = list(self.mw.tmap.events())
        self._scale_bpm0 = None
        self.setCursor(Qt.SizeHorCursor)
        self.update()
    def _do_scale(self, x, y):
        """组等比缩放: 以选区左缘为锚, 抓手对齐落点定比例 (UI轮 新手柄)"""
        _k, t_press, _g, orig, pushed, _a = self._drag
        if not pushed:
            px, py = self._press_pos
            if abs(x - px) < CLICK_EPS: return
            if self.mw._is_playing():             # (28) 播放中忽略改动
                self._drag = None; self._press_snap = None
                self.set_status(tr('播放中 · 改动被忽略 (暂停/停止后可编辑; 选择与浏览不受限)'))
                self.update(); return
            self._start_editing()
            self._drag = ('scale', t_press, None, orig, True, '')
            # (缩放变速轮) 联动开启时把栈顶音符快照升级为复合条目:
            # 一次撤销同时还原 音符缩放 + BPM
            sess = self.mw.edit_session
            if getattr(self.mw, 'scale_bpm_link', False) and sess.undo_stack:
                top = sess.undo_stack[-1]
                if isinstance(top, tuple) and len(top) == 3 \
                        and not isinstance(top[0], str):
                    sess.undo_stack[-1] = ('scale_tempo', top,
                                           tuple(self._scale_tevents))
        t = self._snap_round(self.tick_of_x(x))
        anchor_t = min(v[0] for v in orig.values())
        ref = max(1.0, t_press - anchor_t)   # 按下柄位 = 1.0 (柄静止不缩放)
        if ref > 1.0:
            scale = max(0.05, (t - anchor_t) / ref)
            self._scale_notes(orig, anchor_t, scale, False, self._snap_ticks() or 1)
            self._scale_bpm_maybe(anchor_t, scale)   # (缩放变速轮) BPM 随比例联动
            self._set_bubble(x, y, tr('{n}个音符 · ×{s:.2f}', n=len(orig), s=scale))
        self._guide_tick = t                # (交互轮) 红色指针不再随手势移动
        self._guide_ticks = {min(nt.start_tick for nt, _o in self._drag_items),
                             max(nt.end_tick for nt, _o in self._drag_items)}
        self.request_update(self.roll_rect())
    def _scale_notes(self, orig, anchor_t, scale, from_right, min_len):
        """以 anchor_t 为锚等比缩放选中音符; 钳最短 min_len, 起点≥0"""
        for nt, o in self._drag_items:            # (G-opt) 只遍历选中项
            if from_right:                        # 右端为锚: 向左缩放 (20)
                s = anchor_t - (anchor_t - o[0]) * scale
                e = anchor_t - (anchor_t - o[1]) * scale
            else:
                s = anchor_t + (o[0] - anchor_t) * scale
                e = anchor_t + (o[1] - anchor_t) * scale
            s = max(0, int(round(s)))
            e = max(s + min_len, int(round(e)))
            self.mw.model.set_note_span(nt, s, e)
    # ---------- (缩放变速轮) 区域缩放联动 BPM ----------
    def _scale_bpm_maybe(self, anchor_t, scale):
        """联动开关开: 区域缩放 k 倍 → 锚点处 BPM × k (120 → ×2 → 240)"""
        if not getattr(self.mw, 'scale_bpm_link', False):
            return
        tmap = self.mw.tmap
        if self._scale_bpm0 is None:
            self._scale_bpm0 = tmap.bpm_at_tick(anchor_t)
        target = round(max(20.0, min(400.0, self._scale_bpm0 * scale)), 1)
        idx = tmap.index_at(anchor_t)
        if idx >= 0:
            tmap.set_bpm_index(idx, target)     # 锚点已有速度事件: 原地改
        else:
            tmap.insert_event(anchor_t, target)  # 没有: 从锚点起插入新速度段
    def _do_rubber(self, x, y):
        d = self._drag
        self._drag = ('rubber', d[1], d[2], x, y, d[5])
        t0, t1 = sorted((self.tick_of_x(d[1]), self.tick_of_x(x)))
        ns = [v for v in (self._note_at_y(d[2]), self._note_at_y(y)) if v is not None]
        if not ns: return
        n_lo, n_hi = min(ns), max(ns)
        sel = set(d[5])
        for nt in self.notes:                     # 行有交叠 + 时间有交叠即入选 (仅当前轨)
            if getattr(nt, 'tid', 0) != self.active_tid: continue
            if n_lo <= nt.note <= n_hi and nt.start_tick < t1 and nt.end_tick > t0:
                sel.add(nt.nid)
        self.selection = sel
        self.request_update(self.roll_rect())
    def _do_erase(self, x, y):
        nt, _e = self._hit_test(x, y)
        self._erase_preview = nt.nid if nt is not None else None   # (17) 预览跟随
        if nt is None: return
        if nt.nid in self._erase_marked: return
        if not self._drag[1]:                     # 首次扫中: 一次撤销入栈
            self._start_editing()
            self._drag = ('erase', True)
        self._erase_marked.add(nt.nid)            # (交互轮) 标记淡红, 松手才删
        self.request_update(self.roll_rect())
    # ---------- 释放 / 取消 ----------
    def mouseReleaseEvent(self, ev):
        if self._drag:
            d = self._drag; kind = d[0]; self._drag = None
            self._drag_copy = False
            if kind == 'scrub':                   # 基类擦洗收尾
                self.scrubFinished.emit(self.tmap.tick2sec(
                    min(max(self.tick_of_x(ev.position().x()), 0.0), self.total_tick)))
            elif kind == 'pan':
                self._restore_hover_cursor()
            else:
                self._finish_drag(d, ev.position().x(), ev.position().y())
                self._restore_hover_cursor()
        if self.preview_note is not None:         # 键盘侧栏试听复位(基类行为)
            self.notePreview.emit(self.preview_note, False)
            self.preview_note = None
        self.mw.router.end(self.mw.router.OWNER_MIDI)   # (Y 轮) 手势收尾清 owner (校验 who)
        self._sync_tool_hint()
        self.update()
    def _record_len(self, nt):
        """(交互改版) 画笔点击已有音符: 记录其时值为新音符默认长度 (持久化)"""
        if self.tool != 'pencil' or self.tmap is None or nt is None: return
        L = int(nt.end_tick - nt.start_tick)
        if L <= 0: return
        sess = self.mw.edit_session
        if sess.last_len_ticks == L: return
        sess.last_len_ticks = L
        store.save_last_len(L)                    # (30③) 持久化
        self.set_status(tr('已记录时值 {l:g} 拍 (新音符将使用该时值)',
                           l=L / self.tmap.tpb))
    def _finish_drag(self, d, x=None, y=None):
        kind = d[0]
        if kind in ('move', 'resize', 'scale'):
            if d[4]:
                self.mw.model.finish()            # (X 轮) 统一 retime (幂等)
                self._commit()                    # 已入栈 = 有数据改动
            elif self._ctrl_click is not None:    # (D2) Ctrl 纯点击 = 切换选中
                nid, was_sel = self._ctrl_click
                if was_sel: self.selection = self.selection - {nid}
                nt = next((o for o in self.mw.raw_notes if o.nid == nid), None)
                if nt is not None:
                    self._record_len(nt)          # (交互改版) 画笔点音符记时值
                    self._ping_note(nt)
                self.update()
            elif kind in ('move', 'resize'):
                # 纯单击音符: 试听该音 (未拖动改数据); 画笔同时记录其时值
                items = getattr(self, '_drag_items', None) or []
                if items:
                    self._record_len(items[0][0])
                    self._ping_note(items[0][0])
        elif kind == 'erase':
            marked = getattr(self, '_erase_marked', set())
            if marked:                            # (交互轮) 松手统一删除标记集
                self.mw.model.remove_notes(marked)
                self.selection -= marked
                self._data_ver += 1               # 音符层缓存失效 (L)
                self.mw.model.finish()
                self._commit()
            elif x is not None:                   # (17) 纯右键点击: 释放时确认删除
                nt, _e = self._hit_test(x, y)
                if nt is not None:
                    self._start_editing()
                    self.mw.model.remove_notes({nt.nid})
                    self.selection.discard(nt.nid)
                    self.mw.model.finish()
                    self._commit()
        # 'rubber': 仅改选择, 无需提交
        self._press_snap = None
        self._pending_dup = None; self._ctrl_click = None
        if kind == 'scale':                       # (缩放变速轮) 手势收尾清 tempo 状态
            self._scale_tevents = None; self._scale_bpm0 = None
        self._erase_preview = None
        self._erase_marked = set()                # (交互轮) 滑删标记清空
        self._bubble = None; self._guide_tick = None
        self._guide_ticks = set()
        self._restore_ph()                  # (R 轮) 恢复真实播放位置
    def _escape(self):
        d = self._drag
        if d is not None and d[0] in ('move', 'resize', 'erase', 'scale'):
            pushed = (d[1] if d[0] == 'erase' else d[4])
            self._drag = None
            sess = self.mw.edit_session
            if pushed and sess is not None and sess.undo_stack:
                snap = sess.undo_stack[-1]        # 本操作入栈的那份快照
                tevents = None
                if isinstance(snap, tuple) and snap and snap[0] == 'scale_tempo':
                    tevents = list(snap[2]); snap = snap[1]   # (缩放变速轮) 复合条目
                sess.abort_last()
                self.mw.raw_notes[:] = snap[0]    # 原地还原, 保持列表对象不变
                self.selection = set(snap[1])
                sess.last_len_ticks = snap[2]
                if tevents is not None:           # (缩放变速轮) tempo 一并回退
                    self.mw.tmap.restore_events(tevents)
                self._commit()
                self.set_status(tr("已取消本次操作"))
            self._press_snap = None
            self._pending_dup = None; self._ctrl_click = None
            self._drag_copy = False
            self._restore_hover_cursor()          # 取消后指针回悬停态 (不残留移动/复制)
            if d is None or d[0] == 'scale':      # (缩放变速轮) 手势状态清空
                self._scale_tevents = None; self._scale_bpm0 = None
            self._erase_preview = None
            self._erase_marked = set()
            self._bubble = None; self._guide_tick = None; self._guide_ticks = set()
            self._restore_ph()
            self._sync_tool_hint()
            self.update(); return
        if self.selection:
            self.selection = set(); self.update()
    # ---------- (Q 轮) 剪贴板: Ctrl+C/X/V (内部剪贴板, 相对最早选中起点) ----------
    def _copy_selection(self, cut=False):
        sel = [nt for nt in self.mw.raw_notes if nt.nid in self.selection]
        if not sel:
            self.set_status(tr('没有选中的音符')); return
        t0 = min(nt.start_tick for nt in sel)
        self._clipboard = [(nt.start_tick - t0, nt.end_tick - t0,
                            nt.note, nt.vel) for nt in sel]
        if cut:
            self._delete_selection()
            self.set_status(tr('已剪切 {n} 个音符', n=len(self._clipboard)))
        else:
            self.set_status(tr('已复制 {n} 个音符', n=len(self._clipboard)))
    def _paste_clipboard(self):
        if not self._clipboard:
            self.set_status(tr('剪贴板为空')); return
        base = 0 if self.playhead_tick is None else max(0, int(self._snap_floor(self.playhead_tick)))
        news = [Note(nn, vv, base + rs, base + re_, 0.0, 0.0, tid=self.active_tid)
                for rs, re_, nn, vv in self._clipboard]
        self.mw.model.add_notes(news)             # (X 轮) push+extend+retime 一步
        self.selection = {o.nid for o in news}
        self._commit()
        self.set_status(tr('已粘贴 {n} 个音符', n=len(self.selection)))
    def mouseDoubleClickEvent(self, ev):
        if self.tmap is None: return
        if self.mw._is_playing():                 # (编辑轮) 播放守护补齐
            self.set_status(tr('播放中 · 改动被忽略 (暂停/停止后可编辑; 选择与浏览不受限)'))
            return
        nt, _edge = self._hit_test(ev.position().x(), ev.position().y())
        if nt is None:
            super().mouseDoubleClickEvent(ev); return
        raw = next((o for o in self.mw.raw_notes if o.nid == nt.nid), None)
        if raw is None:
            super().mouseDoubleClickEvent(ev); return
        if nt.nid in self.selection and len(self.selection) > 1:
            # (编辑轮) 框选批量: 双击选中集内音符 → 三态批量对话框, 整批一步撤销
            from dialogs import NotePropsMultiDialog
            sel_notes = [o for o in self.mw.raw_notes if o.nid in self.selection]
            dlg = NotePropsMultiDialog(self, raw, self.mw.total_tick_display,
                                       len(self.selection), sel_notes)
            if dlg.exec() != QDialog.Accepted: return
            self.mw.model.apply_note_props_multi(set(self.selection), dlg.ops())
            self._commit()
            self.set_status(tr('已批量修改 {n} 个音符属性 · Ctrl+Z 可还原',
                               n=len(self.selection)))
            return
        from dialogs import NotePropsDialog
        dlg = NotePropsDialog(self, raw, self.mw.total_tick_display)
        if dlg.exec() != QDialog.Accepted: return
        note_n, vel_n, st, en = dlg.values()
        self.mw.model.apply_note_props(raw, note_n, vel_n, st, en)   # (X 轮) push+写+retime
        self._commit()
        self.set_status(tr('已修改音符属性'))
    # ---------- 键盘快捷键 ----------
    def keyReleaseEvent(self, ev):
        if ev.key() == Qt.Key_Control and (self._drag is None
                                           or self._drag[0] in ('scrub', 'pan')):
            self._refresh_cursor()
        super().keyReleaseEvent(ev)
    def keyPressEvent(self, ev):
        k = ev.key(); mods = ev.modifiers()
        if k == Qt.Key_Control and (self._drag is None
                                    or self._drag[0] in ('scrub', 'pan')):
            self._refresh_cursor()
        if self._drag is not None and self._drag[0] not in ('scrub', 'pan'):
            if k == Qt.Key_Escape: self._escape()  # 拖动中只响应 Esc(取消)
            return
        if k == Qt.Key_Space:                     # 编辑窗激活时主窗口快捷键不生效
            self.mw.toggle_play(); return
        if mods & Qt.ControlModifier:
            if k == Qt.Key_Z:
                self.mw._edit_undo()
                return
            if k == Qt.Key_S: self.mw._save_midi_as(); return
            if k == Qt.Key_A:
                self.selection = {nt.nid for nt in self.mw.raw_notes}
                self.set_status(tr('全选 {n} 个音符', n=len(self.selection))); self.update(); return
            if k == Qt.Key_D:
                self.selection = set(); self.update(); return
            if k == Qt.Key_B: self._duplicate_selection(); return
            if k == Qt.Key_C:
                self._copy_selection(); return                 # (Q 轮) 复制
            if k == Qt.Key_X:
                self._copy_selection(cut=True); return         # (Q 轮) 剪切
            if k == Qt.Key_V:
                self._paste_clipboard(); return                # (Q 轮) 粘贴
            if k in (Qt.Key_Left, Qt.Key_Right):  # (9) Ctrl+←→ 改长度
                self._nudge(k, mods); return
            super().keyPressEvent(ev); return
        if k == Qt.Key_P:
            self.tool = 'pencil'
            self.set_status(tr("画笔: 空白处按下画出音符 · 拖动定长 · 右键删除"))
            self._refresh_cursor(); self._sync_tool_hint(); return
        if k == Qt.Key_E:
            self.tool = 'select'
            self.set_status(tr("选择: 点选/框选 · 拖动移动 · 右缘拉伸 · 右键删除"))
            self._refresh_cursor(); self._sync_tool_hint(); return
        if k == Qt.Key_G: self._cycle_snap(); return
        if k in (Qt.Key_Delete, Qt.Key_Backspace): self._delete_selection(); return
        if k == Qt.Key_Escape: self._escape(); return
        if k in (Qt.Key_Left, Qt.Key_Right, Qt.Key_Up, Qt.Key_Down):
            self._nudge(k, mods); return
        super().keyPressEvent(ev)
    # ---------- 命令式编辑(按键触发) ----------
    def _delete_selection(self):
        if not self.selection: return
        if self.mw._is_playing():                 # (28) 播放中忽略改动
            self.set_status(tr('播放中 · 改动被忽略 (暂停/停止后可编辑)')); return
        n = len(self.selection)
        self.mw.model.delete_notes(self.selection)   # (X 轮) push+原地过滤+retime
        self.selection = set()
        self.set_status(tr('删除 {n} 个音符', n=n))
        self._commit()
    def _duplicate_selection(self):
        """Ctrl+B: 选区整体向右复制一份(步长 = 选区时间跨度)"""
        if not self.selection: return
        sel = [nt for nt in self.mw.raw_notes if nt.nid in self.selection]
        if not sel: return
        if self.mw._is_playing():                 # (28) 播放中忽略改动
            self.set_status(tr('播放中 · 改动被忽略 (暂停/停止后可编辑)')); return
        span = max(nt.end_tick for nt in sel) - min(nt.start_tick for nt in sel)
        span = max(span, self._snap_ticks() or 1)
        clones = [Note(nt.note, nt.vel, nt.start_tick + span, nt.end_tick + span,
                       nt.start_sec, nt.end_sec, tid=nt.tid) for nt in sel]
        self.mw.model.add_notes(clones)   # (P1收口) push改前+原地extend+retime 一步
        self.selection = {c.nid for c in clones}
        self.set_status(tr('复制 {n} 个音符 → 右移 {s} ticks', n=len(clones), s=span))
        self._commit()
    def _nudge(self, k, mods):
        """方向键: 左右按对齐步微移(无对齐=1/96拍) / 上下移调(Shift=八度);
           Ctrl+←→=改长度 (9)"""
        if not self.selection: return
        if self.mw._is_playing():                 # (28) 播放中忽略改动
            self.set_status(tr('播放中 · 改动被忽略 (暂停/停止后可编辑)')); return
        sel = [nt for nt in self.mw.raw_notes if nt.nid in self.selection]
        if not sel: return
        self.mw.edit_session.push()
        tpb = self.tmap.tpb
        if k in (Qt.Key_Left, Qt.Key_Right) and mods & Qt.ControlModifier:
            st = self._snap_ticks() or snap_mod.min_step_ticks(tpb)
            d = st if k == Qt.Key_Right else -st
            for nt in sel:
                nt.end_tick = max(nt.start_tick + 1, nt.end_tick + d)
            self.set_status(tr('改长 {d} tick ({g} 拍)',
                               d=d, g=round(d / tpb, 4)))
        elif k in (Qt.Key_Left, Qt.Key_Right):
            st = self._snap_ticks() or snap_mod.min_step_ticks(tpb)
            d = st if k == Qt.Key_Right else -st
            for nt in sel:
                nt.start_tick = max(0, nt.start_tick + d)
                nt.end_tick = max(nt.start_tick + 1, nt.end_tick + d)
            self.set_status(tr('移动 {d} tick ({g} 拍)',
                               d=d, g=round(d / tpb, 4)))
        else:
            step = 12 if (mods & Qt.ShiftModifier) else 1
            d = step if k == Qt.Key_Up else -step
            lo = min(nt.note for nt in sel); hi = max(nt.note for nt in sel)
            d = max(d, NOTE_MIN - lo); d = min(d, NOTE_MAX - hi)
            for nt in sel: nt.note += d
            self.set_status(tr('移调 {d:+d} 半音', d=d))
        self._commit()
    # ---------- 悬停光标 ----------
    def _refresh_cursor(self):
        if self._hover_pos is not None:
            self._update_hover_cursor(*self._hover_pos)
    def _restore_hover_cursor(self):
        """拖动收尾: 按悬停位置恢复工具指针 (无悬停信息时回默认)"""
        if self._hover_pos is not None:
            self._update_hover_cursor(*self._hover_pos)
        else:
            self.setCursor(self._cursor(self.tool))
    def _cursor(self, kind):
        """当前屏幕缩放 × 设置 (大小 / 选择样式) 下的工具指针"""
        size, style = _cursor_prefs(self.mw)
        return _tool_cursor(kind, self.devicePixelRatioF(), size, style)
    def _sync_tool_hint(self):
        """顶部工具指示框同步: 画笔/选择/框选/删除 (直观反馈当前功能)"""
        w = getattr(self.mw, 'tool_indicator', None)
        if w is None: return
        d = self._drag[0] if self._drag else None
        w.set_select_style(_cursor_prefs(self.mw)[1])
        if d in ('erase', 'rubber'):
            w.set_state(d)
        elif d == 'move':
            w.set_state('copy' if (self._drag_copy or self._pending_dup) else 'move')
        else:
            w.set_state(self.tool)
    def _update_hover_cursor(self, x, y):
        if self.tmap is None: return
        if x < KB_W or y < HEADER_H:
            self.setCursor(self._cursor(self.tool)); return
        if len(self.selection) > 1 and self._hit_scale_handle(x, y):
            self.setCursor(Qt.SizeHorCursor)   # (UI轮) 选区尾部缩放柄
            return
        nt, edge = self._hit_test(x, y)
        ctrl = bool(QApplication.keyboardModifiers() & Qt.ControlModifier)
        if edge:
            self.setCursor(Qt.SizeHorCursor)      # 拉伸柄: 系统双箭头保证精度
        elif nt is not None and ctrl:
            self.setCursor(self._cursor('copy'))  # Ctrl 悬停音符: 拖动即复制
        elif nt is not None and self.tool == 'select':
            self.setCursor(self._cursor('move'))  # 选择工具悬停音符: 可拖动移动
        else:
            self.setCursor(self._cursor(self.tool))
    # ---------- 编辑器覆写层(选中/橡皮筋/参考线/气泡/工具条) ----------
    def _draw_editor_overlay(self, p):
        if self.tmap is None: return
        w, h = self.width(), self.height()
        lo, hi, rh = self.note_low, self.note_high, self.row_h()
        y_off = (self.view_note_start - lo) * rh
        # (perf轮) 不再每帧全量扫可见候选: 删除预览/选中描边按 nid 查 _nid_map
        m = (self._nid_map()
             if (self._erase_preview is not None or self.selection) else None)
        # 1) 右键删除预览: 目标音符红色描边 (17)
        if self._erase_preview is not None:
            nt = m.get(self._erase_preview)
            if nt is not None and lo - 1 <= nt.note <= hi + 1:
                x0 = max(self.x_of_tick(nt.start_tick), KB_W + 1.0)
                x1 = min(self.x_of_tick(nt.end_tick), float(w) - 1.0)
                y = HEADER_H + (hi - nt.note) * rh - y_off + 1.0
                nh = max(rh - 1.0, 2.0)
                p.setBrush(Qt.NoBrush); p.setPen(QPen(QColor('#ff5555'), 2))
                p.drawRoundedRect(QRectF(x0 - 1.5, y - 1.5,
                                         max(6.0, x1 - x0) + 3.0, nh + 3.0), 3.0, 3.0)
        # 2) 选中: 淡红 tint (交互轮: 取代金色描边/虚线框/尾部方块 ——
        #    尾部缩放柄命中区保留但不再绘制, 交互逻辑不变)
        #    (视觉轮) 左右缘黄色方块已移除: 改时值交互本就按音符边缘
        #    接近判定 (_hit_test HANDLE_PX), 抓音符尾缘即改长, 方块纯提示
        if self.selection:
            for nid in self.selection:
                nt = m.get(nid)
                if nt is None: continue
                if not (lo - 1 <= nt.note <= hi + 1): continue
                x0 = self.x_of_tick(nt.start_tick); x1 = self.x_of_tick(nt.end_tick)
                if x1 < KB_W or x0 > w: continue
                y = HEADER_H + (hi - nt.note) * rh - y_off + 1.0
                nh = max(rh - 1.0, 2.0)
                x0 = max(x0, KB_W + 1.0); x1 = min(x1, float(w) - 1.0)
                if x1 - x0 < 6.0: x1 = x0 + 6.0
                p.setPen(Qt.NoPen); p.setBrush(QColor(255, 120, 120, 110))
                p.drawRoundedRect(QRectF(x0, y, x1 - x0, nh), 3.0, 3.0)
            # (交互轮补齐) 缩放手柄: 尾缘 + 1/2 拍处的左右双头箭头标识
            pos = self._scale_handle_pos()
            if pos is not None:
                xh, yh = pos
                p.setPen(Qt.NoPen); p.setBrush(QColor('#7e93a8'))
                p.drawPolygon(QPolygonF([QPointF(xh - 11, yh), QPointF(xh - 5, yh - 4),
                                         QPointF(xh - 5, yh + 4)]))
                p.drawPolygon(QPolygonF([QPointF(xh + 11, yh), QPointF(xh + 5, yh - 4),
                                         QPointF(xh + 5, yh + 4)]))
                p.drawRect(QRectF(xh - 5, yh - 1.2, 10, 2.4))
        # 2) 橡皮筋
        if self._drag is not None and self._drag[0] == 'rubber':
            _k, x0, y0, x1, y1, _b = self._drag
            p.setPen(QPen(QColor('#39d0ff'), 1, Qt.DashLine))
            p.setBrush(QBrush(QColor(57, 208, 255, 26)))
            p.drawRect(QRectF(min(x0, x1), min(y0, y1), abs(x1 - x0), abs(y1 - y0)))
        # 3) 吸附参考线 (交互轮: 音符起始+结束各一条金色指示竖线)
        if self._guide_ticks:
            p.setPen(QPen(QColor(255, 214, 90, 150), 1, Qt.DashLine))
            for gt in sorted(self._guide_ticks):
                gx = self.x_of_tick(gt)
                if KB_W <= gx <= w:
                    p.drawLine(int(gx), HEADER_H, int(gx), h)
        # 4) 操作气泡(音名 · 小节.拍 · 长度)
        if self._bubble:
            bx, by, text = self._bubble
            p.setFont(self.f_bar)
            rect = QRectF(bx + 14, by - 30, p.fontMetrics().horizontalAdvance(text) + 16, 22)
            if rect.right() > w - 4: rect.moveLeft(w - 4 - rect.width())
            if rect.top() < HEADER_H + 2: rect.moveTop(by + 16)
            p.setPen(QPen(QColor('#4a4a56'), 1)); p.setBrush(QColor(24, 24, 30, 235))
            p.drawRoundedRect(rect, 4.0, 4.0)
            p.setPen(QColor('#ffe2a8')); p.drawText(rect, Qt.AlignCenter, text)
        # 5) 底部工具提示条(基类有"下方还有音符"横幅时让位)
        if self._edge_counts[1] == 0:
            info = (tr('画笔P') if self.tool == 'pencil' else tr('选择E')
                    + tr(' · 对齐 {s} · 选中 {n} · Alt临时关对齐 · Ctrl+拖动复制 · '
                         'Ctrl+Z撤销 · 空格播放',
                         s=self._snap_label(), n=len(self.selection)))
            p.setFont(self.f_bar)
            rect = QRectF(KB_W + 8, h - 22,
                          p.fontMetrics().horizontalAdvance(info) + 16, 18)
            p.setPen(QPen(QColor('#3a3a44'), 1)); p.setBrush(QColor(20, 20, 26, 200))
            p.drawRect(rect)
            p.setPen(QColor('#9fd49f')); p.drawText(rect, Qt.AlignCenter, info)
