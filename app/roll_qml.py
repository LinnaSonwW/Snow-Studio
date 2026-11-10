# -*- coding: utf-8 -*-
"""QML 渲染桥 (QML 迁移步骤1): 卷帘画布的 音符/网格 → QQuickWidget/Scene Graph。
   架构 (规格定案): QML 只负责"画出来" —— 输入事件仍由 PianoRoll 捕获
   (QQuickWidget 与覆盖层均 WA_TransparentForMouseEvents), 手势/编辑逻辑零迁移;
   Python 侧经 NoteListModel(QAbstractListModel) 暴露音符, 数据变化用行级
   dataChanged 增量通知 (规格红线: 禁止 beginResetModel 做增量 —— 仅 set_data
   整体换数据源时合法 reset)。视图属性 (viewTick/pxPerTick/rowH/topPitch...)
   经桥 QObject Property 推送, 16ms 渲染时钟统一 push (值不变零代价),
   平移 = content 容器单属性位移 (Scene Graph 只做变换)。
   回退阀: QML 场景加载失败 → roll.qml_fallback() 整体回退光栅瓦片;
   环境开关 ROLL_QML=0 完全禁用 (不 import QtQuick, 行为与迁移前一致)。"""
import os
from PySide6.QtCore import (QObject, Signal, Property, Qt, QUrl, QRect,
                            QModelIndex, QAbstractListModel, QTimer, QPointF)
from PySide6.QtWidgets import QWidget
from PySide6.QtGui import QPainter, QColor, QPen
from PySide6.QtQuick import QQuickPaintedItem, QQuickWindow
from PySide6.QtQml import qmlRegisterType
from PySide6.QtQuickWidgets import QQuickWidget
from common import KB_W, HEADER_H
from roll_tiles import TILE_W

USE_QML = os.environ.get('ROLL_QML', '1') != '0'    # 应急开关: =0 纯光栅回退
COLOR_ACTIVE = '#ffb020'        # 当前演奏 (与 _note_colors 激活色一致)
COLOR_UNPLAY = '#7c5158'        # 不可演奏 (与 _note_colors 一致)


class NoteListModel(QAbstractListModel):
    """音符数据桥 (规格: QAbstractListModel, 不走 JSON/字符串序列化)。
       角色 = pitch/startTick/duration/state/noteColor/label;
       state: 0=普通 1=当前演奏 2=不可演奏 3=已适配(一键原琴化已否决, 恒不出现)。
       noteColor/label 由 Python 侧按现有渲染函数 (_note_colors/_note_label)
       计算 —— QML 保持"哑渲染", 调色板/字母逻辑零复制。"""
    PitchRole = Qt.UserRole + 1
    StartTickRole = Qt.UserRole + 2
    DurationRole = Qt.UserRole + 3
    StateRole = Qt.UserRole + 4
    ColorRole = Qt.UserRole + 5
    LabelRole = Qt.UserRole + 6

    def __init__(self, roll):
        super().__init__()
        self.roll = roll
        self._rows = []            # Note 引用 (与 roll.notes 同源)
        self._row_of = {}          # nid -> 行号
        self._active = frozenset()

    def roleNames(self):
        return {self.PitchRole: b"pitch", self.StartTickRole: b"startTick",
                self.DurationRole: b"duration", self.StateRole: b"state",
                self.ColorRole: b"noteColor", self.LabelRole: b"label"}

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._rows)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self._rows)):
            return None
        nt = self._rows[index.row()]
        nid = getattr(nt, 'nid', id(nt))
        if role == self.PitchRole: return int(nt.note)
        if role == self.StartTickRole: return float(nt.start_tick)
        if role == self.DurationRole:
            return float(max(1, nt.end_tick - nt.start_tick))
        if role == self.StateRole:
            return 1 if nid in self._active else (2 if not nt.playable else 0)
        if role == self.ColorRole:
            return self.roll._note_colors(nt, False)[0].name()
        if role == self.LabelRole:
            return self.roll._note_label(nt) or ''
        return None

    # ---- 增量更新 (规格红线: 变化行 dataChanged, 不整体 reset) ----
    def set_notes(self, notes):
        """整体换数据源 (set_data/提交/撤销) —— 唯一合法 reset 场景"""
        self.beginResetModel()
        self._rows = list(notes)
        self._row_of = {getattr(nt, 'nid', id(nt)): i
                        for i, nt in enumerate(self._rows)}
        self.endResetModel()

    def update_states(self, nids):
        """播放头跨越/高亮集变化: 仅受影响行 dataChanged (规格§数据桥接)"""
        hit = [self._row_of[n] for n in set(nids) if n in self._row_of]
        for row in hit:
            self.dataChanged.emit(self.index(row, 0), self.index(row, 0))

    def set_active(self, active_nids):
        """维护 _active 状态集 + 对变化行发 dataChanged (old∪new 的差集行)"""
        old = self._active
        self._active = frozenset(active_nids)
        self.update_states(old | self._active)

    def add_note(self, nt):
        nid = getattr(nt, 'nid', id(nt))
        if nid in self._row_of:
            self.note_row_updated(nt); return
        row = len(self._rows)
        self.beginInsertRows(QModelIndex(), row, row)
        self._rows.append(nt); self._row_of[nid] = row
        self.endInsertRows()

    def remove_note(self, nid):
        row = self._row_of.pop(nid, None)
        if row is None: return
        self.beginRemoveRows(QModelIndex(), row, row)
        del self._rows[row]
        self._row_of = {getattr(nt, 'nid', id(nt)): i
                        for i, nt in enumerate(self._rows)}
        self.endRemoveRows()

    def note_row_updated(self, nt):
        """拖动帧: 单音符几何/颜色行级刷新"""
        nid = getattr(nt, 'nid', id(nt))
        row = self._row_of.get(nid)
        if row is not None:
            self.dataChanged.emit(self.index(row, 0), self.index(row, 0))

    def refresh_all(self):
        """轨道色/字母模式等全局视觉参数变化: 行级 dataChanged 全量 (罕见)"""
        if self._rows:
            self.dataChanged.emit(self.index(0, 0),
                                  self.index(len(self._rows) - 1, 0))


class RollQmlBridge(QObject):
    """视图属性桥: QML 经 bridge.xxx 绑定, notify 信号驱动增量重绑。
       sync_dynamic (16ms 时钟, 仅拖动帧): 选中/新建行 dataChanged + 缺行补插 +
       已删行移除 —— 编辑手势对 QML 零感知。"""
    viewChanged = Signal()
    playheadMoved = Signal()

    def __init__(self, roll):
        super().__init__(roll)
        self.roll = roll
        self.model = NoteListModel(roll)
        self._vt = {}
        self._ph = None
        self._ppt_base = None
        # (性能回归第8步) 缩放节流: 滚轮密集缩放时 pptBase 冻结, QML 用
        # xScale = ppt/pptBase 顶帧; 防抖 220ms 后重算基准并复位 xScale=1
        self._zoom_hold = False
        self._zoom_timer = QTimer(self)
        self._zoom_timer.setSingleShot(True)
        self._zoom_timer.setInterval(220)
        self._zoom_timer.timeout.connect(self._zoom_settle)
        self.quick = QQuickWidget(roll)
        self.quick.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.quick.setClearColor(Qt.transparent)
        self.quick.setResizeMode(QQuickWidget.ResizeMode.SizeRootObjectToView)
        ctx = self.quick.rootContext()
        ctx.setContextProperty('bridge', self)
        ctx.setContextProperty('noteModel', self.model)
        ctx.setContextProperty('blackClasses', [1, 3, 6, 8, 10])
        qml_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                'PianoRoll.qml')
        self.quick.setSource(QUrl.fromLocalFile(qml_path))
        self.quick.statusChanged.connect(self._on_status)
        self._on_status(self.quick.status())
        self.ovl = _QmlOverlay(roll)          # 覆盖层在 QML 画布之上
        self.ovl.raise_()
        self.reposition()

    # ---- 几何: 画布区 = 卷帘去键盘列/标尺行 ----
    def reposition(self):
        r = self.roll
        geo = QRect(int(KB_W), int(HEADER_H),
                    max(1, r.width() - int(KB_W)),
                    max(1, r.height() - int(HEADER_H)))
        self.quick.setGeometry(geo)
        self.ovl.setGeometry(geo)

    def _on_status(self, st):
        if st == QQuickWidget.Status.Error:
            print('PianoRoll.qml 加载失败, 回退光栅:', self.quick.errors())
            self.roll.qml_fallback()

    # ---- (性能回归第8步) 缩放节流 ----
    def zoom_hold_on(self):
        """滚轮缩放事件: 冻结 pptBase (QML xScale 顶帧), 220ms 防抖后重算基准"""
        if not self._zoom_hold:
            self._zoom_hold = True
        self._zoom_timer.start()

    def _zoom_settle(self):
        self._zoom_hold = False
        self.push_view()                    # 重算 pptBase → QML xScale 复位 1

    # ---- 视图属性推送 (16ms 时钟; 值不变零代价) ----
    def push_view(self):
        r = self.roll
        tpb = r.tmap.tpb if r.tmap else 480
        lo, hi = r.note_low, r.note_high
        top = hi - (r.view_note_start - lo)     # 画布顶行浮点音高 (含滚动相位)
        ppt = (r.ppb / tpb) if r.tmap else 0.1
        if not self._zoom_hold:
            self._ppt_base = ppt                # 非缩放窗口: 基准随实际密度
        vals = {'viewTick': r.view_tick,
                'pxPerTick': ppt,
                'pptBase': self._ppt_base if self._ppt_base else ppt,
                'rowH': r.row_h(), 'topPitch': top,
                'tpb': float(tpb), 'barTicks': float(r.bar_ticks),
                'subStepTicks': self._sub_step(),
                'rangeLo': r.range_lo if r.range_lo is not None else -999,
                'rangeHi': r.range_hi if r.range_hi is not None else -999}
        changed = {k: v for k, v in vals.items() if self._vt.get(k) != v}
        if changed:
            self._vt.update(changed)
            self.viewChanged.emit()

    def _sub_step(self):
        """对齐细网格步长 (Python 折算密度规则, QML 哑渲染)"""
        r = self.roll
        if r.snap_beats is None or r.tmap is None: return 0
        step_beats = (r.bar_ticks / r.tmap.tpb if r.snap_beats == 'bar'
                      else r.snap_beats)
        return step_beats * r.tmap.tpb \
            if step_beats > 0 and step_beats * r.ppb >= 8 else 0

    def set_playhead(self, t):
        t = float(t) if t is not None else -1.0
        if t != self._ph:
            self._ph = t
            self.playheadMoved.emit()

    # ---- 模型委托 (view_roll 调用面) ----
    def set_notes(self, notes):
        self.model.set_notes(notes)
    def set_active_notes(self, notes_objs):
        """对象集 → nid 集 (保持 active_notes=Note 对象集的既有语义)"""
        self.model.set_active({getattr(a, 'nid', id(a)) for a in notes_objs})
    def refresh_all(self):
        self.model.refresh_all()

    # ---- 拖动帧同步 (规格: 编辑中行级增量, 手势层零感知) ----
    def sync_dynamic(self):
        r = self.roll
        valid = {getattr(nt, 'nid', id(nt)) for nt in r.notes}
        for nid in [n for n in self.model._row_of if n not in valid]:
            self.model.remove_note(nid)         # 拖删/撤销移除的行
        want = set(r._dynamic_nids())           # editor: 选中集 = 拖动集
        if want:
            by_nid = {getattr(nt, 'nid', id(nt)): nt for nt in r.notes}
            for nid in want:
                nt = by_nid.get(nid)
                if nt is None: continue
                if nid in self.model._row_of:
                    self.model.note_row_updated(nt)
                else:
                    self.model.add_note(nt)     # 新建/Ctrl 克隆补插

    # ---- QML Property (notify 驱动绑定增量重估) ----
    @Property(float, notify=viewChanged)
    def viewTick(self): return self._vt.get('viewTick', 0.0)
    @Property(float, notify=viewChanged)
    def pxPerTick(self): return self._vt.get('pxPerTick', 0.1)
    @Property(float, notify=viewChanged)
    def pptBase(self): return self._vt.get('pptBase', 0.1)
    @Property(float, notify=viewChanged)
    def rowH(self): return self._vt.get('rowH', 12.0)
    @Property(float, notify=viewChanged)
    def topPitch(self): return self._vt.get('topPitch', 71.0)
    @Property(float, notify=viewChanged)
    def tpb(self): return self._vt.get('tpb', 480.0)
    @Property(float, notify=viewChanged)
    def barTicks(self): return self._vt.get('barTicks', 1920.0)
    @Property(float, notify=viewChanged)
    def subStepTicks(self): return self._vt.get('subStepTicks', 0.0)
    @Property(int, notify=viewChanged)
    def rangeLo(self): return self._vt.get('rangeLo', -999)
    @Property(int, notify=viewChanged)
    def rangeHi(self): return self._vt.get('rangeHi', -999)
    @Property(float, notify=playheadMoved)
    def playheadTick(self): return self._ph if self._ph is not None else -1.0


class _QmlOverlay(QWidget):
    """编辑器覆盖层 (QML 画布之上): 选中描边/橡皮筋/参考线/气泡/删除预览。
       透明 + 不接收鼠标 —— 输入仍归 PianoRoll, QML 不实现任何编辑逻辑。"""
    def __init__(self, roll):
        super().__init__(roll)
        self.roll = roll
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_NoSystemBackground)
    def paintEvent(self, ev):
        p = QPainter(self)
        p.translate(-int(KB_W), -int(HEADER_H))   # 复用 widget 坐标绘制钩子
        self.roll._draw_editor_overlay(p)


# ==================== QML-3 / MuseScore 路线 (ROLL_QML=2) ====================
# 报告§13 裁决后立项: 不再用 delegate-per-note, 改为 QQuickPaintedItem 内用
# QPainter 复用 roll_tiles.py 已验证的绘制函数 (网格/音符/行底色/音域框),
# 数据直接读 roll 状态 —— 消除 NoteListModel/增量对账/缩放节流整套机器。
# Qt 6.9+ 且 OpenGL 时 renderTarget=FramebufferObject 可硬件加速绘制;
# 非 GL 环境自动回落 QImage (仍为 CPU 绘制, 与光栅同量级)。

class NotesPaintedItem(QQuickPaintedItem):
    """MuseScore 路线画布: paint() 内以 QPainter 调 roll_tiles 已验证函数
       全量重绘画布区 (行底色/音域框/网格/音符/琥珀高亮), 数据直读 roll 状态。
       Qt 6.9+ OpenGL 时 FBO 目标硬件加速; 否则 Image (CPU 光栅+上传)。"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self._roll = None
        # (真机实测 2026-09-07) FBO 目标在真机 GL 上描边/圆角矩形/文字静默不渲染
        # (仅 fillRect 可见) —— 按文档正确路径回退 Image 目标 (CPU 光栅+纹理上传)
        self.setRenderTarget(QQuickPaintedItem.RenderTarget.Image)
        self.setFillColor(QColor(Qt.transparent))    # 背景由 paint() 自绘
    def set_roll(self, roll):
        self._roll = roll
        self.update()
    def paint(self, painter):
        roll = self._roll
        if roll is None or roll.tmap is None:
            return
        w = self.width(); h = self.height()
        painter.fillRect(0, 0, w, h, QColor('#171b21'))
        painter.save()
        # 平移到卷帘 widget 坐标系: 行底色/网格/音符函数全部按 widget 坐标书写
        painter.translate(-int(KB_W), -int(HEADER_H))
        roll._draw_static_v(painter)                 # 行底色/音域框 (键盘越界自动裁)
        painter.setRenderHint(QPainter.Antialiasing, False)
        ppt = roll.ppb / roll.tmap.tpb
        ta = roll.view_tick
        x0 = 0.0
        active = getattr(roll, '_active_notes', frozenset())
        while x0 < w:                                # 1024 分块 (与瓦片同宽)
            painter.save()
            painter.translate(x0, 0)
            ta_c = ta + x0 / ppt
            tb_c = ta_c + min(TILE_W, w - x0) / ppt
            roll.tiles.draw_grid_area(painter, ta_c, tb_c)
            painter.setRenderHint(QPainter.Antialiasing, True)
            roll.tiles.draw_notes_range(painter, ta_c, tb_c, frozenset(),
                                        active_fn=lambda nt: nt in active)
            painter.restore()
            x0 += TILE_W
        painter.restore()
        # ---- 播放头 (item 本地坐标; item 已定位在 KB_W, 组件内不再加偏移) ----
        if roll.playhead_tick is not None:
            x = (roll.playhead_tick - roll.view_tick) * (roll.ppb / roll.tmap.tpb)
            if 0 <= x <= w + 30:
                painter.setPen(QPen(QColor('#ff3b30'), 2))
                painter.drawLine(QPointF(x, 0), QPointF(x, h))


qmlRegisterType(NotesPaintedItem, 'RollCanvas', 1, 0, 'NotesPaintedItem')


class _PaintedModelShim:
    """mode 2 模型通知折叠器: paint() 直读 roll 状态, 任何模型事件都只需一次重绘"""
    def __init__(self, host):
        self._host = host
    def refresh_all(self): self._host.update()
    def update_states(self, nids): self._host.update()
    def set_notes(self, notes): self._host.update()
    def add_note(self, nt): self._host.update()
    def remove_note(self, nid): self._host.update()
    def note_row_updated(self, nt): self._host.update()


class PaintedRollHost:
    """ROLL_QML=2 宿主: 与 RollQmlBridge 同接口 (view_roll 调用面零改动),
       但渲染 = NotesPaintedItem 全量重绘, 无模型/增量/节流机器。
       交互/覆盖层 (_QmlOverlay) 仍留 Python —— 输入通路零改动。"""
    def __init__(self, roll):
        self.roll = roll
        self.quick = QQuickWidget(roll)
        self.quick.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.quick.setClearColor(Qt.transparent)
        self.quick.setResizeMode(QQuickWidget.ResizeMode.SizeRootObjectToView)
        qml = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           'PaintedRoll.qml')
        self.quick.setSource(QUrl.fromLocalFile(qml))
        root = self.quick.rootObject()
        self.painted = root if isinstance(root, NotesPaintedItem) \
            else root.findChild(NotesPaintedItem) if root is not None else None
        if self.painted is not None:
            self.painted.set_roll(roll)
        self.ovl = _QmlOverlay(roll)                 # 编辑覆盖层在画布之上
        self.model = _PaintedModelShim(self)         # view_roll 的刷新调用面
        self._vsig = None                            # 视图状态指纹 (push_view 差分)
        self.ovl.raise_()
        self.reposition()
    def reposition(self):
        r = self.roll
        geo = QRect(int(KB_W), int(HEADER_H),
                    max(1, r.width() - int(KB_W)),
                    max(1, r.height() - int(HEADER_H)))
        self.quick.setGeometry(geo)
        self.ovl.setGeometry(geo)
    def push_view(self):
        """视图/播放头状态指纹差分: 变化才调度 painted 重绘 (空闲零开销)。
           (真机修复 2026-09-08) 概览条/中键平移等只改 roll.update() 的路径,
           由 16ms 时钟经此统一调度 QML 画布跟随 —— 否则画布不跟随 (只动标尺)。"""
        r = self.roll
        sig = (r.view_tick, r.view_note_start, r.ppb, r.playhead_tick,
               r.range_lo, r.range_hi)
        if sig != self._vsig:
            self._vsig = sig
            if self.painted is not None:
                self.painted.update()
    def sync_dynamic(self):
        self.update()
    def set_notes(self, notes):
        self.update()
    def set_active_notes(self, notes):
        self.update()
    def refresh_all(self):
        self.update()
    def set_playhead(self, t):
        self.push_view()                             # 播放头变化并入同一差分调度
    def zoom_hold_on(self):
        pass                                         # paint 直读 roll.ppb, 无需节流
    def update(self):
        if self.painted is not None:
            self.painted.update()
