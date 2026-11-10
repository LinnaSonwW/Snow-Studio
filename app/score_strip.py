# -*- coding: utf-8 -*-
"""演奏谱横幅 (P0 批次2, 规格《联动演奏谱视图_技术规格》): PerformanceEvent 的只读渲染。
   lead sheet 哲学: 只给节拍/键位骨架, 块宽=时值但用与下一事件的间隔表达节奏,
   不锁死每个音的时值观感。
   容器: roll 子控件, 与 TempoLane 同几何公式互斥显示 (切换不重算缩放, 共用同一
   tick 刻度)。缩放 ppb 恒取 roll.ppb —— 不构成第二把独立缩放; view_tick 恒随
   roll viewChanged 同步 (统一播放跟随: 播放中由卷帘按"跟随"开关带动横幅,
   横幅不再自滚 —— 2026-09-08 用户裁定, 取代规格§2 横幅独立播放移动)。
   (演奏谱重设计一期 2026-09-26) 时间刻度尺取消 → 顶部 20px 行 = 小节号行
   (只画小节线+小节号); 横幅内速度编辑入口 (双击/右键) 随刻度尺移除,
   速度编辑统一走 Tempo 车道与卷帘标尺右键; 蓝线/首尾圆点删除,
   音符时值改由亮起动效时长 (durMs) 表达。
   色彩语义: 黑字=普通  蓝=当前演奏 (方块点亮+外圈柔光+蓝字, 亮起时长=时值)
   红字=不可播放(优先级最高, 红压蓝)
   绿=已适配(**"一键原琴化"已否决 2026-09-07, 暂无来源, 仅保留语义位不启用**)。
   车道数据 = mw.perf_by_tid (compile_performance_by_tid 产物); 模式/车道选择在
   UI 层 (editor_session)。
   QML-2 渲染迁移: 车道/字母标签/网格/小节号行绘制移交 PerformanceStrip.qml
   (Scene Graph; 演奏点亮 = QML 绑定 playheadTick, 零逐帧 Python 工作);
   本 widget 保留 输入事件/几何 —— QQuickWidget
   WA_TransparentForMouseEvents, 事件通路零改动。与悬浮窗宿主 (ScoreFloat)
   共用同一份 QML 组件文件 (规格§8 禁止两份实现)。"""
import os
import bisect
import unicodedata
from PySide6.QtCore import (QObject, Signal, Property, Qt, QUrl, QModelIndex,
                            QAbstractListModel, QPointF, QRectF, QTimer,
                            QVariantAnimation, QAbstractAnimation, QEasingCurve)
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout,
                               QLabel, QPushButton)
from PySide6.QtGui import (QWheelEvent, QPainter, QPen, QFont, QColor,
                           QFontMetrics)
from PySide6.QtQuickWidgets import QQuickWidget
from window_chrome import fade_scale_in   # BPM/拍号双击弹窗入场动效 (修复 NameError)
from common import (KB_W, HEADER_H, note_name, jianpu_dots,
                    STRIP_LABEL_MODES, NOTE_JIANPU)
from i18n import t as tr
import settings_store as store
from tempo_editor import HANDLE_H

RULER_H = 20               # 小节号行高 (演奏谱重设计一期: 刻度行 → 小节号行)
CONTENT_TOP = HANDLE_H + RULER_H   # 拉手 + 小节号行以下的车道区
COL_W = 56.0               # (小节谱 v2) 基准列距 px (colW 桥属性; v9 起排版按流式盒宽)
GAP = 28.0                 # (小节谱 v9) 相邻方框之间的恒定空白 px (等距基准)
ROW_H_PX = 250             # (多排轮) 悬浮谱每排默认高 (可在设置「悬浮谱排高」改)
# 色彩语义 (谱面化 2026-09-08; 一期 2026-09-26: 蓝线/圆点删除 → 蓝仅表演奏点亮)
# 黑字=普通  蓝=当前演奏 (方块点亮/外圈柔光/蓝字, 亮起时长=时值)
# 红字=不可演奏(优先级最高, 红压蓝)
# GREEN='已适配'——"一键原琴化"已否决 (2026-09-07 用户决策), 语义位保留不启用
COLOR_TEXT = '#101318'
COLOR_BLUE = '#3f8cff'     # 演奏中: 方块点亮 + 外圈柔光 + 字母白字
COLOR_RED = '#a8433f'
COLOR_GREEN = '#50dc78'
# 网格色 (谱面化 2026-09-08: 白底, 网格竖线灰化 —— 用户裁定纯黑太重;
# 小节线深灰 > 拍线中灰 > 细网格浅灰, 层级保持。
# 一期: 拍线已随刻度尺移除, PEN_BEAT 保留语义位)
PEN_BAR = '#6f757c'
PEN_BEAT = '#989ea6'
PEN_SUB = '#c9cdd2'

# QML 调色板单源 (Python 侧常量经上下文属性注入, QML 不持色值)
STRIP_PAL = {
    'bg': '#ffffff', 'rulerFill': '#ffffff', 'sep': '#d0d3d8',
    'bar': PEN_BAR, 'beat': PEN_BEAT, 'sub': PEN_SUB,
    'barNo': '#333333',
    'laneCol': '#f2f3f5', 'name': '#3a4048', 'empty': '#9aa4b0',
    'text': COLOR_TEXT, 'blue': COLOR_BLUE, 'red': COLOR_RED,
    'green': COLOR_GREEN, 'chipDefault': '#4f9cf9',
    'gold': '#e8b05a',               # (琶音轮) 琶音虚线平行线金色
    'ballRed': '#ff4a3d'}            # (小球轮) 小球进入琶音子音的亮红
                                     #  (可演奏色, 不复用不可演奏的暗红 red)


def classify_event(ev, mapper, playhead_tick):
    """事件配色纯函数 (规格§4, 优先级强制 红>蓝>白):
       红 = 事件含任一不可演奏音 (mapper.in_scope 失败; mapper.err 时全红,
            与 roll nt.playable 口径一致); 蓝 = 播放头 ∈ [start, start+时值)
            (右开); 白 = 普通。GREEN='已适配' 无来源("一键原琴化"已否决), 不返回。
       (QML-2 起 state 角色 = 红/白二值, 蓝由 QML 按 playheadTick 绑定计算)"""
    if mapper is None or mapper.err:
        return 'red'
    if any(not mapper.in_scope(p) for p in ev.notes):
        return 'red'
    if playhead_tick is not None and ev.duration_ticks > 0 \
            and ev.start_tick <= playhead_tick < ev.start_tick + ev.duration_ticks:
        return 'blue'
    return 'white'


def _uniq_starts(rows):
    """行键 = start: 同刻多行 (合并车道的普通音 + 琶音块、多个琶音块) 依次
       +0.001 tick 错开, 否则 EventListModel 对账时互相覆盖"""
    used = set()
    for r in rows:
        k = r['start']
        while k in used:
            k += 0.001
        used.add(k)
        r['start'] = k
    return rows


class EventListModel(QAbstractListModel):
    """单车道演奏事件模型: start_tick 键控增量对账 —— 移除失配行 / 新行插入 /
       变化行 dataChanged, 零 reset (规格§数据桥接红线)。
       角色: startTick/duration(时值, 蓝窗口径)/blockTicks(视觉宽, min(时值,
       到下一事件))/state(0=普通 2=不可演奏; 蓝=QML 按 playheadTick 绑定)/label"""
    StartTickRole = Qt.UserRole + 1
    DurationRole = Qt.UserRole + 2
    BlockTicksRole = Qt.UserRole + 3
    StateRole = Qt.UserRole + 4
    LabelRole = Qt.UserRole + 5
    DurMsRole = Qt.UserRole + 6        # (动画轮) 音符时值毫秒 (方框动效时长驱动)
    NoteLabelsRole = Qt.UserRole + 7   # (阶梯轮) 单音标签列表 (升序, 一音一格)
    SubYRole = Qt.UserRole + 8         # (琶音轮) 琶音窄块垂直偏移 px (和弦=0)
    NoteDotsRole = Qt.UserRole + 9     # (点轮) 简谱八度点: 每音符 [上加, 下加]
    XTickRole = Qt.UserRole + 14       # (排版轮) 显示起点 tick
    WTickRole = Qt.UserRole + 15       # (排版轮) 显示时值 tick
    XPxRole = Qt.UserRole + 16         # (小节谱轮) 显示起点 px (行内容原点, 列布局)
    RowIdxRole = Qt.UserRole + 17      # (小节谱轮) 所属排下标 (列布局按排过滤)
    WPxRole = Qt.UserRole + 18         # (琶音轮) 显示宽 px (合并块跨列; 普通=列宽)
    ArpSeqRole = Qt.UserRole + 19      # (琶音轮) 顺播序列 [[tick_off, label]…]

    def __init__(self):
        super().__init__()
        self._rows = []       # dict 行 (按 start 排序; 渲染只读行数据, 序不敏感)
        self._row_of = {}     # start_tick -> 行号

    def roleNames(self):
        return {self.StartTickRole: b"startTick", self.DurationRole: b"duration",
                self.BlockTicksRole: b"blockTicks", self.StateRole: b"state",
                self.LabelRole: b"label", self.DurMsRole: b"durMs",
                self.NoteLabelsRole: b"noteLabels", self.SubYRole: b"subY",
                self.NoteDotsRole: b"noteDots",
                self.XTickRole: b"xTick", self.WTickRole: b"wTick",
                self.XPxRole: b"xPx", self.RowIdxRole: b"rowIdx",
                self.WPxRole: b"wPx", self.ArpSeqRole: b"arpSeq"}

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self._rows)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or not (0 <= index.row() < len(self._rows)):
            return None
        r = self._rows[index.row()]
        if role == self.StartTickRole: return float(r['start'])
        if role == self.DurationRole: return float(r['dur'])
        if role == self.BlockTicksRole: return float(r['block'])
        if role == self.StateRole: return int(r['state'])
        if role == self.LabelRole: return r['label']
        if role == self.DurMsRole: return float(r.get('durMs', 400))
        if role == self.NoteLabelsRole: return list(r.get('noteLabels', []))
        if role == self.SubYRole: return float(r.get('subY', 0.0))
        if role == self.NoteDotsRole: return list(r.get('noteDots', []))
        if role == self.XTickRole: return float(r.get('xTick', r['start']))
        if role == self.WTickRole: return float(r.get('wTick', r['dur']))
        if role == self.XPxRole: return float(r.get('xPx', 0.0))
        if role == self.RowIdxRole: return int(r.get('rowIdx', 0))
        if role == self.WPxRole: return float(r.get('wPx', COL_W))
        if role == self.ArpSeqRole: return list(r.get('arpSeq', []))
        return None

    def set_events(self, rows):
        """键控增量对账 (行 = dict: start/dur/block/state/label)"""
        new_keys = {r['start'] for r in rows}
        for i in range(len(self._rows) - 1, -1, -1):
            if self._rows[i]['start'] not in new_keys:
                self.beginRemoveRows(QModelIndex(), i, i)
                del self._rows[i]
                self.endRemoveRows()
        self._row_of = {r['start']: i for i, r in enumerate(self._rows)}
        for pos, r in enumerate(rows):
            i = self._row_of.get(r['start'])
            if i is None:
                self.beginInsertRows(QModelIndex(), pos, pos)
                self._rows.insert(pos, r)
                self._row_of = {rr['start']: j
                                for j, rr in enumerate(self._rows)}
                self.endInsertRows()
            elif self._rows[i] != r:
                self._rows[i] = r
                self.dataChanged.emit(self.index(i, 0), self.index(i, 0))


class StripQmlBridge(QObject):
    """横幅视图属性桥: QML 经 bridge.xxx 绑定, notify 驱动增量重估。
       push() 由 ScoreStrip.update() 触发 (值不变零代价); 车道行级对账也在此
       (每车道的行变化经 EventListModel dataChanged, 不整体 reset)。"""
    viewChanged = Signal()
    playheadMoved = Signal()
    lanesChanged = Signal()

    def __init__(self, strip):
        super().__init__(strip)
        self.strip = strip
        self._vt = {}
        self._ph = None
        self._lane_models = {}     # tid -> EventListModel
        self._lane_sig = None
        self._starts = {}          # tid -> 起点有序数组 (perf_ver 门失效, bisect 用)
        self._bars_view_x = 0.0    # (连续滚动) 当前视口流水 x
        self._pages_sig = None     # (整页排版轮) 页链缓存门 (列表 + 排数 + 排宽)
        self._pages = []           # 页链 [{'rows': [[节…]…], 'flip': tick|None}]
        self._bars_page = 0        # 当前页下标 (悬浮窗整页排版)
        self._bars_sig = None      # (小节谱轮) 列表缓存门 (perf_ver + 车道 + tsig)
        self._bars_cache = {'cols': [], 'secs': [], 'per_bar': 4}
        # (小节谱 v2) 列流缓存: cols=音符起点去重升序, secs=节表 (4列/节连续编号)
        self._bars_by_row = []     # 每排网格表 [[x_px, bar_no]…] (QML Canvas)
        self._ball_segs = []       # (小球轮) 小节谱飞行段表 (ballSegs 属性)
        self._ball_sig = None      # (小球缓存轮) 目标序列缓存门 (_ball_targets)
        self._ball_tg = {}         # tid -> 目标序列 (数据+字体+车道几何, 视口无关)
        self._ball_sts = {}        # tid -> 目标起点升序数组 (映射 bisect 用)
        self._ball_km = None       # 缓存时 _label_keymap 引用 (同一性失效门)
        self.quick = QQuickWidget(strip)
        self.quick.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.quick.setClearColor(Qt.transparent)
        self.quick.setResizeMode(QQuickWidget.ResizeMode.SizeRootObjectToView)
        ctx = self.quick.rootContext()
        ctx.setContextProperty('bridge', self)
        ctx.setContextProperty('pal', STRIP_PAL)
        ctx.setContextProperty('emptyHint', tr('该轨道无音符'))
        ctx.setContextProperty('blankHint', tr('空白乐谱排 · 点击左侧 + 选择音轨'))
        qml = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           'PerformanceStrip.qml')
        self.quick.setSource(QUrl.fromLocalFile(qml))

    def reposition(self):
        w = max(1, self.strip.width())
        h = max(1, self.strip.height())
        if self.strip.parentWidget() is self.strip.roll:
            self.quick.setGeometry(0, int(HANDLE_H), w, max(1, h - int(HANDLE_H)))
        else:
            self.quick.setGeometry(0, 0, w, h)

    def push(self):
        """全量推送 (ScoreStrip.update 触发): 视图/播放头/车道对账"""
        strip = self.strip
        r, mw = strip.roll, strip.mw
        tpb = mw.tmap.tpb if mw.tmap else 480
        ppt = (r.ppb / tpb) if mw.tmap else 0.1
        page_ticks = max(1.0, strip.page_bars * mw.bar_ticks) \
            if mw.tmap else 3840.0
        # (多排修复轮) rows>1 恒整页铺满: 非翻页模式若取卷帘缩放, 每排画的
        # 跨度 ≠ pageTicks (卷帘一屏 ~3.5 小节 vs 排步进 3 小节) → 相邻排重叠,
        # 重叠区网格/事件/播放头画两遍 = 双指针的真正根源 (用户诊断)
        page_fit = getattr(strip, 'page_mode', False) or \
            max(1, int(getattr(strip, '_rows', 1))) > 1
        if page_fit and strip.width() > strip.kb_w:
            # 整页恰好铺满横幅宽度 (缩放固定, 与卷帘缩放解耦)
            ppt = (strip.width() - strip.kb_w) / page_ticks
        vals = {'viewTick': strip.view_tick,
                'pxPerTick': ppt,
                'barTicks': float(mw.bar_ticks), 'tpb': float(tpb),
                'beatsPerBar': float(self._tsig_num()),
                'pageTicks': float(page_ticks),
                'rows': int(getattr(strip, '_rows', 1)),
                'labelPt': float(getattr(mw, 'strip_font', 8)),
                'namePt': float(getattr(mw, 'strip_name_font', 7)),
                'kbW': int(strip.kb_w),
                'skinClear': bool(getattr(strip, 'skin_clear', False)),
                'colMode': self._bars_active(),
                'colGen': (int(strip.width()), len(self._bars_cache['secs']),
                           int(self._bars_view_x),
                           int(getattr(strip, '_rows', 1)))}
        changed = {k: v for k, v in vals.items() if self._vt.get(k) != v}
        if changed:
            self._vt.update(changed)
            self.viewChanged.emit()
        ph = r.playhead_tick
        ph = float(ph) if ph is not None else -1.0
        if ph != self._ph:
            self._ph = ph
            self.playheadMoved.emit()
        if self._bars_active():                    # (小节谱轮) 列布局通路
            old_grid = self._bars_by_row
            old_segs = self._ball_segs
            self._push_lanes_bars()
            if self._bars_by_row != old_grid \
                    or self._ball_segs != old_segs:  # 换页/段表变化: 同轮重绘
                self.viewChanged.emit()
        else:
            self._bars_by_row = []
            self._ball_segs = []                   # (小球轮) 非小节谱恒空
            self._push_lanes(ppt)

    def _tsig_num(self):
        return self.strip.mw.tsig[0] if getattr(self.strip.mw, 'tsig', None) else 4

    def _push_lanes(self, ppt):
        """车道推送 (性能修复 2026-09-08): perf_ver 版本门 + 视口窗口化。
           旧行为: 每次 push 全量重建全部车道行 —— 2212 音大曲每 40ms 轮询一次
           O(N) dict/字符串重建 + 全量对账, 播放跟随下挤爆 GUI 线程
           ("卷帘+演奏谱一起播放很卡, 单独卷帘不卡"的根因; 单独卷帘时横幅隐藏,
           推送被隐藏期门挂起故免疫)。
           现在: 行数据只依赖 perf_by_tid/mapper/_label_keymap/轨道名/演奏谱字符
           模式 —— 全部仅在 mw._rebuild 重建 → perf_ver 唯一失效点; 视口窗口
           [vt-2span, vt+span] 内的事件才建行 (起点数组按车道缓存 + bisect),
           delegate 数与数据量解耦。
           已知边界: 起点早于左缘 2 屏的超长延音不显示 (罕见, 接受)。"""
        strip = self.strip
        r, mw = strip.roll, strip.mw
        tids = strip.lane_tids
        ver = getattr(mw, 'perf_ver', 0)
        names = [strip._track_name(t) for t in tids]
        colors = [strip.lane_color(t) for t in tids]
        counts = [len(self.strip.lane_events(t)) for t in tids]
        sig = (tuple(tids), tuple(names), tuple(colors), tuple(counts), ver)
        if sig != self._lane_sig:
            self._lane_sig = sig
            self._starts = {}                  # 数据/车道变化: 起点缓存全失效
            self.lanesChanged.emit()
        mapper = mw.mapper
        tpb = mw.tmap.tpb if mw.tmap else 480
        rows_n = max(1, int(getattr(strip, '_rows', 1)))
        if getattr(strip, 'page_mode', False):
            span = max(1.0, strip.page_bars * mw.bar_ticks)   # 一排 = 一页
        else:
            span = max(1.0, (strip.width() - strip.kb_w) / r.ppb * tpb) if r.ppb > 0 else 1.0
        wt0 = strip.view_tick - 2.0 * span     # 左余量 2 屏: 吸收左侧入场条目+翻页滑动起点
        # (挤开修复轮) 字符度量: 镜像 QML 方框宽合成 (逐字符 advance + 间距)
        _f = QFont('Segoe UI')
        _f.setPointSizeF(float(getattr(mw, 'strip_font', 8)))
        fm = QFontMetrics(_f)
        spacing = max(4.0, float(getattr(mw, 'strip_font', 8)) * 0.7)
        # (多排轮) 第 r 排视野 = view_tick + r*pageTicks: 窗口须覆盖整个「张」;
        # 翻页滑动中 view_tick 前移, 上限再 +1 页吸收滑动终点
        page_span = max(1.0, strip.page_bars * mw.bar_ticks) if mw.tmap else 3840.0
        if getattr(strip, 'page_mode', False):
            wt1 = strip.view_tick + (rows_n + 1.0) * span
        else:
            wt1 = strip.view_tick + max(span, page_span * rows_n) + span
        for tid in tids:
            evs = self.strip.lane_events(tid)
            starts = self._starts.get(tid)
            if starts is None:
                starts = [int(e.start_tick) for e in evs]
                self._starts[tid] = starts
            # (琶音轮) 车道音高中位数: 琶音窄块垂直偏移的参照系
            all_p = sorted(p for e in evs for p in e.notes)
            med = all_p[len(all_p) // 2] if all_p else 0
            # (槽位轮) 车道几何: 蓝线 y (与 QML line Rectangle 同式) + 字号档距
            # (多排轮) 每排 lane_h = (row_h - ruler)/lanes, 与 QML laneH 同式:
            # 内嵌宿主 quick 顶让出 HANDLE_H (QML 见不到), 悬浮宿主全幅
            embedded = strip.parentWidget() is strip.roll
            content_h = strip.height() - (HANDLE_H if embedded else 0)
            lane_h = (content_h / rows_n - RULER_H) / max(1, len(tids))
            label_pt = float(getattr(mw, 'strip_font', 8))
            # (槽位轮) 槽位锚线 y: 线上 3 槽 / 线下 2 槽以此为界
            # (一期: 蓝线已删, 锚线保留为纯布局基准)
            line_y = min(lane_h - 3.0,
                         lane_h / 2.0 + max(7.0, label_pt * 0.85))
            rows = []
            # (槽位轮) 链式状态: 前行槽位 idx/起点/方框估宽 —— 方框之间不允许
            # 相互挤在一起, 挤则沿槽位表顺时针轮转 (槽位互不重叠, 任何缩放不糊)
            prev_idx = 0
            prev_start = None
            prev_w = 0.0
            j = bisect.bisect_left(starts, wt0)
            while j < len(evs):
                ev = evs[j]
                start = starts[j]
                if start >= wt1: break
                dur = max(1, int(ev.duration_ticks))
                next_st = (int(evs[j + 1].start_tick) if j + 1 < len(evs)
                           else start + dur)
                block = max(1, min(dur, next_st - start))
                state = 2 if (mapper is None or mapper.err
                              or any(not mapper.in_scope(p)
                                     for p in ev.notes)) else 0
                # (动画轮) 时值毫秒: 方框动效时长由音符时值决定 (变速曲按位置换算)
                dur_ms = (mw.tmap.tick2sec(start + dur)
                          - mw.tmap.tick2sec(start)) * 1000.0
                label = strip._block_text(ev)
                nlabels = strip._note_labels(ev)   # (挤开修复轮) 复用单音标签
                # (槽位轮) 该事件方框高 (镜像 QML bx 公式: 数字 + 八度点方向叠)
                dots = strip._note_dots(ev)
                mx_u = max((d[0] for d in dots), default=0)
                mx_d = max((d[1] for d in dots), default=0)
                dot_d = max(2.6, label_pt * 0.38)
                up_part = (2.5 + mx_u * dot_d + (mx_u - 1) * 1.5) if mx_u else 0.0
                dn_part = (2.5 + mx_d * dot_d + (mx_d - 1) * 1.5) if mx_d else 0.0
                box_h = max(14.0, 4.0 + label_pt * 1.75 + up_part + dn_part)
                # (方向感知) prefer: 上加点用线上槽 / 下加点用线下槽;
                # 无点传 0 → _ladder_sub_y 内按音高 (rep vs 车道中位) 定侧
                prefer = -1 if mx_u else (1 if mx_d else 0)
                crowded = (prev_start is not None
                           and (start - prev_start) * ppt < prev_w)
                sub_y, prev_idx = strip._ladder_sub_y(
                    ev, block, ppt, med, line_y, box_h, lane_h,
                    prefer, prev_idx, crowded)
                prev_start = start
                prev_w = self._box_width(nlabels, fm, spacing)   # (挤开修复轮) 镜像 QML 实宽
                x_t, w_t = float(start), float(dur)
                rows.append({'start': start, 'dur': dur, 'block': block,
                             'state': state, 'label': label,
                             'noteLabels': nlabels,
                             'noteDots': dots,
                             'subY': sub_y,
                             'durMs': max(60.0, dur_ms),
                             'xTick': x_t, 'wTick': w_t})
                j += 1
            self._model_for(tid).set_events(_uniq_starts(rows))

    # ---------- (小节谱 v2) 列布局: 列=音符 (起点去重/同刻共列), 等距列宽,
    #              节 = per_bar 列连续分节 (无空节), 页 = 整节填充行宽 ----------
    @staticmethod
    def _ev_gid(ev):
        """(琶音轮) 事件琶音组 = 首个 >0 的音符分组 id (0 = 正常事件)"""
        for a in getattr(ev, 'arps', ()):
            if a > 0:
                return int(a)
        return 0

    def _bars_active(self):
        """bars 模式开关: strip_layout=='bars' 且拍号表/TempoMap 就绪"""
        mw = self.strip.mw
        return (getattr(mw, 'strip_layout', 'follow') == 'bars'
                and getattr(mw, 'tsig_map', None) is not None
                and mw.tmap is not None)

    def _bars_table(self, tids):
        """(小节谱 v9) 列流表 + 每列盒宽 (perf_ver+车道+字号 门缓存):
           cols = 正常音起点 ∪ 每琶音"拍块"代表起点 —— 琶音组按拍分块:
           同一拍内的组音合并为 1 块 (琶音占一拍 = 1 容纳名额, 可读),
           跨拍的组拆成多块各归其位 (不再拽回最早位置); 同刻和弦共列;
           节 = per_bar 列连续分节 (无空节) —— per_bar = 当前拍号分子 (默认 4)。
           col_w = 每列盒宽 (该列跨车道最宽盒 + 间隙余量; 琶音列 = 块宽),
           排版按方框左右边缘等距: 列间空白恒为 GAP, 宽盒自然多占宽度。
           → {'cols','col_w','secs':[{'no','ci0','ncols'}],'per_bar'}"""
        mw = self.strip.mw
        per_bar = max(1, int(mw.tsig[0])) if getattr(mw, 'tsig', None) else 4
        label_pt = float(getattr(mw, 'strip_font', 8))
        ver = (getattr(mw, 'perf_ver', 0), tuple(tids), per_bar, label_pt)
        if self._bars_sig == ver:
            return self._bars_cache
        beat_ticks = max(1.0, mw.bar_ticks / per_bar)   # 一拍 = 节宽/拍数
        group_rep, buckets = self._arp_buckets(tids, beat_ticks)
        ticks = set()
        for tid in tids:
            for e in self.strip.lane_events(tid):
                if not self._ev_gid(e):
                    ticks.add(int(e.start_tick))
        ticks.update(group_rep.values())       # 每拍块 1 名额 (块内首音起点)
        cols = sorted(ticks)
        # (拍号联动轮) 节 = 按所在位置拍号分子分块 (4/4→4 列, 3/4→3 列...):
        # 拍号标签更改后小节谱节宽随之联动
        tsm = getattr(mw, 'tsig_map', None)
        sec_of_col = [0] * len(cols)
        secs = []
        i = 0
        while i < len(cols):
            num = int(tsm.at(cols[i])[0]) if tsm is not None else 4
            ncols = max(1, min(num, len(cols) - i))
            secs.append({'no': len(secs) + 1, 'ci0': i, 'ncols': ncols})
            for k in range(ncols):
                sec_of_col[i + k] = len(secs) - 1
            i += ncols
        _f = QFont('Segoe UI')
        _f.setPointSizeF(label_pt)
        fm = QFontMetrics(_f)
        spacing = max(4.0, label_pt * 0.7)
        col_w = [0.0] * len(cols)
        for tid in tids:
            for e in self.strip.lane_events(tid):
                if self._ev_gid(e):
                    continue
                ci = bisect.bisect_left(cols, int(e.start_tick))
                w = self._box_width(self.strip._note_labels(e), fm, spacing)
                if w > col_w[ci]:
                    col_w[ci] = w
        for key, rep_t in group_rep.items():
            its = buckets[key]
            w = self._arp_width(
                its, self.strip._note_labels, fm, spacing,
                label_pt) + 8.0       # 琶音块: 含组间呼吸间距的整块宽
            rep_ci = bisect.bisect_left(cols, rep_t)
            if w > col_w[rep_ci]:
                col_w[rep_ci] = w
        col_w = [round(w + GAP, 2) for w in col_w]   # 盒宽 + 列间空白 = 占位
        # (整页排版轮) 每节末音结束刻: 翻页刻 = 衔接节前一节演奏完最后一个音
        sec_end = [cols[s['ci0'] + s['ncols'] - 1] + 1 for s in secs]
        for tid in tids:
            for e in self.strip.lane_events(tid):
                if self._ev_gid(e):
                    continue
                ci = bisect.bisect_left(cols, int(e.start_tick))
                if ci < len(cols):
                    si = sec_of_col[ci]
                    sec_end[si] = max(sec_end[si], int(e.start_tick)
                                      + int(e.duration_ticks))
        for key, rep_t in group_rep.items():
            si = sec_of_col[bisect.bisect_left(cols, rep_t)]
            for t, e in buckets[key]:
                sec_end[si] = max(sec_end[si], int(t) + int(e.duration_ticks))
        # (连续滚动轮) 全曲流水坐标: 节线/列盒左缘的累计 x (页无关)
        col_x = [0.0] * len(cols)
        sec_x = [0.0] * len(secs)
        x = 0.0
        for si, s in enumerate(secs):
            sec_x[si] = x
            x += GAP / 2.0                      # 节首半距留白
            for k in range(s['ncols']):
                ci = s['ci0'] + k
                col_x[ci] = x
                x += col_w[ci]                  # 盒占位 (盒宽+GAP)
            x += GAP / 2.0                      # 节尾半距留白
        self._bars_sig = ver
        self._bars_cache = {'cols': cols, 'col_w': col_w, 'secs': secs,
                            'per_bar': per_bar, 'sec_of_col': sec_of_col,
                            'col_x': col_x, 'sec_x': sec_x, 'flow_w': x,
                            'sec_end': sec_end}
        return self._bars_cache

    def _bars_paged(self):
        """悬浮窗小节谱 = 整页排版 (1~4 排同一规则); 内嵌谱 = 连续滚动"""
        return self.strip.parentWidget() is not self.strip.roll

    def _bars_pages(self, cache, rows_n, W):
        """(整页排版轮) 页链: 每排按排宽贪心装入整小节, 装不下的小节整节
           移到下一排 (不切半节, 排首恒为节线); 每页末排末节 = 衔接节,
           同时作为下一页首节; 翻页刻 = 衔接节前一节末音结束 (钳到衔接节
           起点)。单节页无衔接 (下一页从下一节起, 防原地死循环)。
           → [{'rows': [[节下标…]…], 'flip': tick|None (末页 None)}]"""
        key = (self._bars_sig, int(rows_n), round(float(W), 1))
        if self._pages_sig == key:
            return self._pages
        secs, sec_x = cache['secs'], cache['sec_x']
        cols, sec_end = cache['cols'], cache['sec_end']
        n = len(secs)

        def sec_w(si):
            return (sec_x[si + 1] if si + 1 < n else cache['flow_w']) - sec_x[si]

        pages = []
        start = 0
        while start < n:
            rows = []
            si = start
            for _r in range(rows_n):
                if si >= n:
                    break
                row = [si]                     # 超宽单节也独占一排 (不丢节)
                used = sec_w(si)
                si += 1
                while si < n and used + sec_w(si) <= W + 0.01:
                    used += sec_w(si)
                    row.append(si)
                    si += 1
                rows.append(row)
            last = rows[-1][-1]
            if last >= n - 1:
                pages.append({'rows': rows, 'flip': None})
                break
            nxt = last if last > start else last + 1
            t_next = cols[secs[nxt]['ci0']]
            pages.append({'rows': rows,
                          'flip': min(sec_end[nxt - 1], t_next)})
            start = nxt
        self._pages_sig = key
        self._pages = pages
        return pages

    def _flow_x_of_tick(self, t):
        """(连续滚动) tick → 全曲流水 x px (列间按时间比例插值)"""
        cache = self._bars_cache
        cols, col_x = cache['cols'], cache['col_x']
        if not cols:
            return 0.0
        if len(cols) < 2:
            return col_x[0]
        k = min(max(bisect.bisect_right(cols, t) - 1, 0), len(cols) - 2)
        frac = min(max((t - cols[k]) / max(1.0, cols[k + 1] - cols[k]), 0.0),
                   1.0)
        return col_x[k] + frac * (col_x[k + 1] - col_x[k])

    def _tick_at_flow_x(self, x):
        """流水 x → tick (插值逆运算; 越界钳首/末列)"""
        cache = self._bars_cache
        cols, col_x = cache['cols'], cache['col_x']
        if not cols:
            return 0.0
        if x <= col_x[0]:
            return cols[0]
        if x >= col_x[-1]:
            return cols[-1]
        k = bisect.bisect_right(col_x, x) - 1
        frac = (x - col_x[k]) / max(1.0, col_x[k + 1] - col_x[k])
        return cols[k] + frac * (cols[k + 1] - cols[k])

    @classmethod
    def _arp_width(cls, items, label_fn, fm, spacing, label_pt):
        """(负空间分组) 琶音块盒宽镜像 QML: 全部标签按 _box_width 紧排,
           再加 (起点组数-1) × 呼吸间距 (QML breath = max(9, labelPt×1.0));
           不再计 '|' 分隔符"""
        labels = []
        for _t, e in items:
            labels.extend(label_fn(e))
        groups = len({int(e.start_tick) for _t, e in items})
        breath = max(9.0, float(label_pt) * 1.0)
        return (cls._box_width(labels, fm, spacing)
                + breath * max(0, groups - 1))

    def _arp_buckets(self, tids, beat_ticks):
        """(琶音按拍分块) 组内音同一拍 (距块首音 < beat_ticks 的窗口) 合并
           1 块, 跨拍拆块各归其位。
           → (group_rep {(tid,g,块序): 块内最早起点},
              buckets {(tid,g,块序): [(tick, 事件)…] 时刻升序})"""
        mw = self.strip.mw
        group_rep = {}
        buckets = {}
        by_g = {}
        for tid in tids:
            for e in self.strip.lane_events(tid):
                g = self._ev_gid(e)
                if g:
                    by_g.setdefault((tid, g), []).append(
                        (int(e.start_tick), e))
        for key, evs in by_g.items():
            evs.sort(key=lambda x: x[0])
            ci = 0
            t0 = None
            for t, e in evs:
                if t0 is None or t - t0 >= beat_ticks:
                    ci += 1
                    t0 = t
                    key2 = key + (ci,)
                    group_rep[key2] = t
                    buckets[key2] = []
                buckets[key + (ci,)].append((t, e))
        return group_rep, buckets

    def _arp_sections(self, tids, cols, sec_of_col, group_rep, buckets):
        """(琶音) 拍块 → 列映射: 代表列 (块内首音起点的列, bisect 精确命中)
           与所在节。→ [( (tid,g,si,items), rep_ci )…] (按 rep_ci 升序);
           items=[(时刻tick, 事件)…] 时刻升序"""
        out = []
        for key, rep_t in group_rep.items():
            tid, g, bi = key
            its = sorted(buckets[key])
            rep_ci = bisect.bisect_left(cols, rep_t)
            si = sec_of_col[rep_ci]
            out.append(((tid, g, si, its), rep_ci))
        out.sort(key=lambda x: x[1])
        return out

    def _push_lanes_bars(self):
        """(小节谱 v3) 列布局推送: 一音一列, 节距 = max(基准, 内容宽) ——
           盒宽 = 内容宽不缩字, 宽盒拉长所在节; 页 = 变宽节累积填充;
           行 dict 携带 xPx / rowIdx / wPx (内容宽)"""
        strip = self.strip
        mw = strip.mw
        tids = strip.lane_tids
        ver = getattr(mw, 'perf_ver', 0)
        names = [strip._track_name(t) for t in tids]
        colors = [strip.lane_color(t) for t in tids]
        counts = [len(self.strip.lane_events(t)) for t in tids]
        sig = (tuple(tids), tuple(names), tuple(colors), tuple(counts), ver)
        if sig != self._lane_sig:
            self._lane_sig = sig
            self._starts = {}
            self.lanesChanged.emit()
        cache = self._bars_table(tids)
        cols, secs = cache['cols'], cache['secs']
        col_w = cache['col_w']
        per_bar = cache['per_bar']
        rows_n = max(1, int(getattr(strip, '_rows', 1)))
        if not secs:
            self._bars_by_row = [[] for _ in range(rows_n)]
            self._ball_segs = []                   # (小球轮) 空谱无段
            for m in self._lane_models.values():   # 全量清空 (含已移除 tid)
                m.set_events([])
            return
        W = max(60.0, strip.width() - strip.kb_w)    # 一排窗口宽
        ph = self._ph if (self._ph or 0) >= 0 else 0.0
        col_x, sec_x = cache['col_x'], cache['sec_x']
        self._bars_by_row = []
        col_pos = {}                           # 全局列号 -> (排, 盒左缘相对 x)
        if self._bars_paged():
            # (整页排版轮) 悬浮窗 1~4 排: 排首 = 节线, 只放整小节, 末排末节
            # = 衔接节 (下一页首节); 页由 sync_playhead 按翻页刻切换
            pages = self._bars_pages(cache, rows_n, W)
            pg = pages[min(max(0, int(self._bars_page)), len(pages) - 1)]
            for r in range(rows_n):
                row = pg['rows'][r] if r < len(pg['rows']) else []
                lines = []
                if row:
                    r0x = sec_x[row[0]]
                    for si in row:
                        s = secs[si]
                        lines.append([sec_x[si] - r0x, s['no']])
                        for k in range(s['ncols']):
                            cik = s['ci0'] + k
                            col_pos[cik] = (r, col_x[cik] - r0x)
                self._bars_by_row.append(lines)
            first = pg['rows'][0][0]
            last = pg['rows'][-1][-1]
            self._bars_view_x = float(sec_x[first])
            win_lo = cols[secs[first]['ci0']]
            win_hi = cols[secs[last]['ci0'] + secs[last]['ncols'] - 1] + 1
        else:
            # 内嵌谱: 播放头锚定 1/4 连续滚动 (原行为)
            view_x = min(max(self._flow_x_of_tick(ph) - 0.25 * W, 0.0),
                         max(0.0, cache['flow_w'] - W))
            self._bars_view_x = view_x
            for r in range(rows_n):
                r0x = view_x + r * W
                r1x = r0x + W
                lines = []
                for si, s in enumerate(secs):
                    sx = sec_x[si]
                    w_sec = GAP + sum(col_w[s['ci0']:s['ci0'] + s['ncols']])
                    if not (sx < r1x and sx + w_sec > r0x):
                        continue               # 本节与排窗口无重叠
                    lines.append([sx - r0x, s['no']])
                    for k in range(s['ncols']):
                        cik = s['ci0'] + k
                        cx = col_x[cik]
                        if r0x <= cx < r1x:
                            col_pos[cik] = (r, cx - r0x)
                self._bars_by_row.append(lines)
            win_lo = self._tick_at_flow_x(view_x)
            win_hi = self._tick_at_flow_x(view_x + rows_n * W) + 1
        mapper = mw.mapper
        embedded = strip.parentWidget() is strip.roll
        content_h = strip.height() - (HANDLE_H if embedded else 0)
        lane_h = (content_h / rows_n - RULER_H) / max(1, len(tids))
        label_pt = float(getattr(mw, 'strip_font', 8))
        line_y = min(lane_h - 3.0, lane_h / 2.0 + max(7.0, label_pt * 0.85))
        _f = QFont('Segoe UI')
        _f.setPointSizeF(label_pt)
        fm = QFontMetrics(_f)
        spacing = max(4.0, label_pt * 0.7)
        # ---- (琶音按拍分块) 琶音块预构建: 与源轨同车道, 强制下排 (prefer=1);
        #      同一拍内的组音合并 1 块 (占 1 容纳名额), 跨拍拆块各归其位;
        #      块宽 = 内容宽; 顺播序列/(组间呼吸间距) 按组内时刻 ----
        beat_ticks = max(1.0, mw.bar_ticks / per_bar)
        group_rep, buckets = self._arp_buckets(tids, beat_ticks)
        arp_g = self._arp_sections(tids, cols, cache['sec_of_col'],
                                   group_rep, buckets)
        arp_blocks = {}                        # tid -> [块行 dict…]
        for (tid, g, si, items), rep_ci in arp_g:
            pos = col_pos.get(rep_ci)
            if pos is None:
                continue                   # 不在本页/视口
            r, x_px = pos
            start_tick = items[0][0]
            # (琶音可读轮) 点亮窗口持续到块内末音结束 —— 顺播放大完整走完,
            # 不再随首个音的时值提前熄灭缩小
            dur = max([int(e.duration_ticks) for _t, e in items]
                      + [int(items[-1][0]) - start_tick
                         + int(items[-1][1].duration_ticks)])
            nlabels = []
            ndots = []
            for _t, e in items:
                nlabels.extend(strip._note_labels(e))
                ndots.extend(strip._note_dots(e))
            w_px = self._arp_width(
                items, strip._note_labels, fm, spacing, label_pt)
            dur_ms = (mw.tmap.tick2sec(start_tick + dur)
                      - mw.tmap.tick2sec(start_tick)) * 1000.0
            seq = []
            prev_pitch = None                      # 连音检测: 记录前一音高
            for _t, e in items:                    # 同起点标签同亮 (= 和弦一致)
                pitches = list(e.pitches) if hasattr(e, 'pitches') else list(e.notes)
                for i, lbl in enumerate(strip._note_labels(e)):
                    is_legato = (pitches[i] == prev_pitch)  # 同音高=连音
                    seq.append([int(e.start_tick) - start_tick, lbl, is_legato])
                    prev_pitch = pitches[i]
            state = 2 if (mapper is None or mapper.err
                          or any(not mapper.in_scope(p)
                                 for _t, e in items for p in e.notes)) else 0
            mx_u = max((d[0] for d in ndots), default=0)
            mx_d = max((d[1] for d in ndots), default=0)
            dot_d = max(2.6, label_pt * 0.38)
            up_part = (2.5 + mx_u * dot_d + (mx_u - 1) * 1.5) if mx_u else 0.0
            dn_part = (2.5 + mx_d * dot_d + (mx_d - 1) * 1.5) if mx_d else 0.0
            box_h = max(14.0, 4.0 + label_pt * 1.75 + up_part + dn_part)
            sub_y, _pi2 = strip._ladder_sub_y(
                items[0][1], dur, 0.0, 0, line_y, box_h, lane_h,
                1, 0, False)                   # 强制下排 (线下贴线槽)
            arp_blocks.setdefault(tid, []).append({
                'start': start_tick,           # 同刻防键撞由 _uniq_starts 统一处理
                'dur': dur, 'block': dur, 'state': state,
                'label': ' '.join(nlabels),
                'noteLabels': nlabels, 'noteDots': ndots,
                'subY': sub_y, 'durMs': max(60.0, dur_ms),
                'xPx': x_px, 'wPx': w_px, 'rowIdx': r,
                'arpSeq': seq})
        for tid in tids:
            evs = self.strip.lane_events(tid)
            starts = self._starts.get(tid)
            if starts is None:
                starts = [int(e.start_tick) for e in evs]
                self._starts[tid] = starts
            rows = []
            j = bisect.bisect_left(starts, win_lo if win_lo is not None else 0)
            while j < len(evs):
                s = starts[j]
                if win_hi is not None and s >= win_hi:
                    break
                ev = evs[j]
                if self._ev_gid(ev):        # (琶音轮) 琶音事件 → 块 (源轨车道)
                    j += 1
                    continue
                ci = bisect.bisect_left(cols, s)   # 精确命中 (cols=起点并集)
                pos = col_pos.get(ci)
                if pos is None:
                    j += 1
                    continue               # 不在本页/视口
                r, x_px = pos
                dur = max(1, int(ev.duration_ticks))
                state = 2 if (mapper is None or mapper.err
                              or any(not mapper.in_scope(p)
                                     for p in ev.notes)) else 0
                dur_ms = (mw.tmap.tick2sec(s + dur)
                          - mw.tmap.tick2sec(s)) * 1000.0
                nlabels = strip._note_labels(ev)
                w_px = self._box_width(nlabels, fm, spacing)   # 盒宽=内容宽
                dots = strip._note_dots(ev)
                mx_u = max((d[0] for d in dots), default=0)
                mx_d = max((d[1] for d in dots), default=0)
                dot_d = max(2.6, label_pt * 0.38)
                up_part = (2.5 + mx_u * dot_d + (mx_u - 1) * 1.5) if mx_u else 0.0
                dn_part = (2.5 + mx_d * dot_d + (mx_d - 1) * 1.5) if mx_d else 0.0
                box_h = max(14.0, 4.0 + label_pt * 1.75 + up_part + dn_part)
                # (琶音不占位轮) 固定中排槽 (线上贴线, 梯位第 3 槽):
                # 节距已自适应内容宽, 无需轮换避让; 下排让给琶音块
                sub_y = line_y - 2.0 - box_h
                rows.append({'start': s, 'dur': dur, 'block': dur,
                             'state': state, 'label': strip._block_text(ev),
                             'noteLabels': nlabels, 'noteDots': dots,
                             'subY': sub_y, 'durMs': max(60.0, dur_ms),
                             'xPx': x_px, 'wPx': w_px, 'rowIdx': r})
                j += 1
            rows.extend(arp_blocks.get(tid, []))   # (琶音并轨轮) 块并入源轨车道
            self._model_for(tid).set_events(_uniq_starts(rows))
        # ---- (仿冰与火之舞小球轮) 飞行段表: 各车道从完整 lane_events 构建
        #      (不受 win_lo/win_hi 窗口限制), 只推两端至少一端在本页/视口内的段 ----
        self._ball_segs = self._build_ball_segs(
            tids, cols, col_pos, arp_g, W, lane_h, label_pt, line_y,
            fm, spacing)
        # (连续滚动轮) 视口 x 每次变化都进 colGen → viewChanged 已驱动重绘

    def _build_ball_segs(self, tids, cols, col_pos, arp_g, W, lane_h,
                         label_pt, line_y, fm, spacing):
        """(仿冰与火之舞小球轮) 小节谱飞行段表 (ballSegs) —— 拆两步:
           1) 每车道「目标序列」缓存 (_ball_targets): 内容只依赖 数据/字体/
              车道几何/列流, 与视口、翻页、滚动无关;
           2) 每次 push 只做映射 (_map_ball_segs): 用当前 col_pos 把目标映到
              屏幕坐标, 按列号 bisect 出可见区间再生成段 dict —— 播放中每
              40ms 的 push 不再全曲重测字宽/琶音 x 偏移/框高。
           (段语义与原全量构建逐值一致): 段 = 前目标结束 tick → 本目标起始
           tick; 结束 = 前目标起点+时值 (琶音子音取到下一目标起点为止);
           飞行 <80ms (含重叠) 时出发改为到达前 80ms (不早于前目标起点),
           到达时刻恒准时。轨迹 = 上下交替半圆弧 (车道全曲段序奇偶定边,
           不随翻页重置), 竖直半径 = min(水平半径, 车道高×0.3), 琶音块内
           子音之间 ×0.6。坐标: x = 排内框中心 x (与行 dict xPx 同坐标系;
           琶音子音 = 块 xPx + 标签中心偏移), y = 车道局部框顶/底边。
           跨排拆两半时间, 跨页从排左缘飞入。只推两端至少一端在当前页/视口
           内的段 (按 t0 升序)。"""
        if self.strip.mw.tmap is None:
            return []
        self._ball_targets(tids, cols, arp_g, lane_h, label_pt, line_y,
                           fm, spacing)
        return self._map_ball_segs(tids, col_pos, W, lane_h)

    def _ball_targets(self, tids, cols, arp_g, lane_h, label_pt, line_y,
                      fm, spacing):
        """(小球缓存轮) 每车道目标序列缓存。目标 = {st 起始 tick, dur 原时值,
           eff (琶音子音截到下一目标起点), arp, gid, ci (cols 下标; 琶音 =
           代表列), dx (普通音 = 框中心相对框左缘半宽 / 琶音 = 块内标签中心
           x), y_top/y_bot 框顶/底 y, t0 (到达段出发 tick, 保底 80ms 后),
           side (到达段边 = 车道全曲段序奇偶), in_blk (到达段是否琶音块内
           子音间 = 短弧)}。
           缓存键 = perf_ver + 车道键 + labelPt + 演奏谱字符模式 (strip_label)
           + strip_jianpu_base + lane_h + line_y + spacing + _bars_sig
           (cols 列表签名, _bars_cache 重建即失效) + _label_keymap 同一性
           (键位字母变化改字宽); 任一变化重建。变速走 _rebuild → perf_ver,
           t0 的秒换算随之失效。普通音 ci/几何同源 cols (键含 _bars_sig)。"""
        strip = self.strip
        mw = strip.mw
        tmap = mw.tmap
        km = getattr(mw, '_label_keymap', None)
        mode = STRIP_LABEL_MODES[
            int(getattr(mw, 'strip_label', 0)) % len(STRIP_LABEL_MODES)]
        sig = (getattr(mw, 'perf_ver', 0), tuple(tids), float(label_pt), mode,
               int(getattr(mw, 'strip_jianpu_base', 4)),
               float(lane_h), float(line_y), float(spacing), self._bars_sig)
        if sig == self._ball_sig and km is self._ball_km:
            return self._ball_tg                  # 缓存命中: 零重建
        dot_d = max(2.6, label_pt * 0.38)
        breath = max(9.0, float(label_pt))

        def _parts(dots):
            mx_u = max((d[0] for d in dots), default=0)
            mx_d = max((d[1] for d in dots), default=0)
            up = (2.5 + mx_u * dot_d + (mx_u - 1) * 1.5) if mx_u else 0.0
            dn = (2.5 + mx_d * dot_d + (mx_d - 1) * 1.5) if mx_d else 0.0
            return max(14.0, 4.0 + label_pt * 1.75 + up + dn)

        out = {}
        sts = {}
        for tid in tids:
            evs = strip.lane_events(tid)
            # ---- 琶音块表: (组号, 起点) → (代表列, 块内标签中心 x, 框顶/底 y) ----
            arp_tg = {}
            for (tid2, g, _si, items), rep_ci in arp_g:
                if tid2 != tid:
                    continue
                raw = []                         # (起点, 字宽, 字符数) 逐标签
                for _t, e in items:
                    for lbl in strip._note_labels(e):
                        adv = 0.0
                        nch = 0
                        for ch in lbl:
                            if unicodedata.combining(ch):
                                continue
                            adv += fm.horizontalAdvance(ch) + 1.0
                            nch += 1
                        raw.append((int(e.start_tick), adv, nch))
                n = len(raw)
                flat = []                        # (起点, 块内字形中心 x)
                cur_x = 3.0                      # QML nrow.x = 3 (标签 Row 左缘)
                for i, (st, adv, nch) in enumerate(raw):
                    grp_end = i + 1 >= n or raw[i + 1][0] != st
                    flat.append((st, cur_x + max(0.0, adv - nch) / 2.0))
                    # item 推进 = 字宽 (镜像 txt.implicitWidth+1)
                    #   + 组尾 breath (max(9, labelPt), 末标签不加) + Row spacing
                    cur_x += adv + (breath if (grp_end and i + 1 < n) else 0.0) \
                        + spacing
                i = 0                            # 同刻组 (和弦子音) 合并 1 目标
                groups = []
                while i < n:
                    j = i
                    while j + 1 < n and flat[j + 1][0] == flat[i][0]:
                        j += 1
                    groups.append((flat[i][0], (flat[i][1] + flat[j][1]) / 2.0))
                    i = j + 1
                ndots = []                       # 块几何与推送行同式
                for _t, e in items:
                    ndots.extend(strip._note_dots(e))
                box_h = _parts(ndots)
                blk_dur = max([int(e.duration_ticks) for _t, e in items]
                              + [int(items[-1][0]) - int(items[0][0])
                                 + int(items[-1][1].duration_ticks)])
                sub_y, _pix = strip._ladder_sub_y(
                    items[0][1], blk_dur, 0.0, 0, line_y, box_h, lane_h,
                    1, 0, False)                 # 强制下排 (与推送行一致)
                for st, cx in groups:
                    arp_tg[(g, st)] = (rep_ci, cx, sub_y, sub_y + box_h)
            # ---- 普通目标表: 起点 → (半宽, 框顶/底 y) (同刻和弦 = 1 目标) ----
            norm_tg = {}
            for e in evs:
                if self._ev_gid(e):
                    continue
                st = int(e.start_tick)
                if st in norm_tg:
                    continue
                box_h = _parts(strip._note_dots(e))
                sub_y = line_y - 2.0 - box_h
                norm_tg[st] = (self._box_width(
                    strip._note_labels(e), fm, spacing) / 2.0,
                    sub_y, sub_y + box_h)
            # ---- 目标序列 (原始起点升序; 同刻普通在前, 与 _uniq_starts 一致) ----
            seq = []
            seen = set()
            for e in evs:
                g = self._ev_gid(e)
                st = int(e.start_tick)
                key = (1, g, st) if g else (0, 0, st)
                if key in seen:
                    continue
                seen.add(key)
                if g:
                    geo = arp_tg.get((g, st))
                    ci = geo[0] if geo else None
                    dx = geo[1] if geo else 0.0
                    y_top = geo[2] if geo else None
                    y_bot = geo[3] if geo else None
                else:
                    geo = norm_tg[st]
                    ci = bisect.bisect_left(cols, st)
                    dx, y_top, y_bot = geo
                seq.append({'st': st, 'dur': max(1, int(e.duration_ticks)),
                            'arp': bool(g), 'gid': int(g or 0), 'ci': ci,
                            'dx': dx, 'y_top': y_top, 'y_bot': y_bot})
            seq.sort(key=lambda t: (t['st'], 1 if t['arp'] else 0))
            for i, t in enumerate(seq):          # 子音时值截到下一目标起点
                t['eff'] = min(t['dur'], max(0, seq[i + 1]['st'] - t['st'])) \
                    if (t['arp'] and i + 1 < len(seq)) else t['dur']
            if seq:
                seq[0].update(t0=0.0, side=0, in_blk=False)
            for k in range(1, len(seq)):         # 到达段参数 (段序 = 车道全曲序)
                pv, cu = seq[k - 1], seq[k]
                # 起点→起点: 出发 = 前目标起点, 到达 = 本目标起点 (t1 = cu['st'])
                # min(.., st-1): 同刻目标 (普通音 + 琶音块同 tick) 时保证 t1 > t0, 避免零时长段
                cu['t0'] = min(float(pv['st']), float(cu['st']) - 1.0)
                cu['side'] = 1 if (k - 1) % 2 == 0 else -1
                cu['in_blk'] = (pv['arp'] and cu['arp']
                    and pv['gid'] == cu['gid']
                    and pv['ci'] is not None
                    and pv['ci'] == cu['ci'])
            out[tid] = seq
            sts[tid] = [t['st'] for t in seq]
        self._ball_sig = sig
        self._ball_km = km
        self._ball_tg = out
        self._ball_sts = sts
        return out

    def _map_ball_segs(self, tids, col_pos, W, lane_h):
        """(小球缓存轮) push 映射: 缓存目标序列 → 当前页/视口段 dict。
           col_pos 键 = 连续列号区间 (整页/连续滚动都是); 目标可见 ⟺ 其列号
           落在 [cmin,cmax] ⟺ 起始 tick ≥ cols[cmin] 且 (普通音) < cols[cmax+1]
           / (琶音子音) < 代表列起点 + 拍宽 —— 据此对缓存序列按 st bisect 出
           候选区间, 向前多取 1 个前驱 / 向后多取 1 个后继, 只对这些相邻对
           生成段; 端点列都不在 col_pos 的对跳过 (与全量构建一致) —— 不遍历
           全曲。跨排拆两半时间 / 跨页左缘飞入 / 出页右缘飞向排右缘, 规则
           与原全量构建相同。"""
        mw = self.strip.mw
        tmap = mw.tmap
        if tmap is None or not col_pos:
            return []
        cols = self._bars_cache.get('cols') or []
        if not cols:
            return []
        beat = max(1.0, mw.bar_ticks / max(1, self._bars_cache['per_bar']))
        cmin = min(col_pos)
        cmax = max(col_pos)
        lo_t = cols[cmin]
        hi_t = cols[cmax + 1] + beat if cmax + 1 < len(cols) else None

        def _ry(dx, short):
            r = min(max(1.0, abs(dx) / 2.0), lane_h * 0.3)
            return r * 0.6 if short else r       # 琶音块内子音短弧

        out = []
        for li, tid in enumerate(tids):
            tg = self._ball_tg.get(tid)
            if not tg:
                continue
            sts = self._ball_sts[tid]
            a = max(0, bisect.bisect_left(sts, lo_t) - 1)   # 前驱 1 个
            b = (bisect.bisect_left(sts, hi_t) - 1) if hi_t is not None \
                else len(tg) - 1
            b = min(len(tg) - 1, b + 1)                     # 后继 1 个
            segs = []
            for k in range(a + 1, b + 1):
                pv, cu = tg[k - 1], tg[k]
                ci = pv['ci']
                pp = col_pos.get(ci) if ci is not None else None
                ci = cu['ci']
                cp = col_pos.get(ci) if ci is not None else None
                if pp is None and cp is None:
                    continue                 # 两端都不在本页/视口
                if pp is not None:
                    pp = (pp[0], pp[1] + pv['dx'])   # (排, 排内中心 x)
                if cp is not None:
                    cp = (cp[0], cp[1] + cu['dx'])
                side = cu['side']
                t0 = cu['t0']
                t1 = float(cu['st'])
                y0e = pv['y_top'] if side > 0 else pv['y_bot']
                y1e = cu['y_top'] if side > 0 else cu['y_bot']
                if y0e is None:
                    y0e = y1e
                if y1e is None:
                    y1e = y0e
                base = {'lane': li, 't0': t0, 't1': t1, 'side': side,
                        'arp': cu['arp'], 'prevArp': pv['arp']}
                if pp is None:                   # 跨页: 前目标不在页 → 左缘飞入
                    segs.append(dict(base, x0=0.0, y0=y1e, row0=cp[0],
                                     x1=cp[1], y1=y1e, row1=cp[0],
                                     ry=_ry(cp[1], False)))
                elif cp is None:                 # 目标已出页右缘 → 飞向排右缘
                    segs.append(dict(base, x0=pp[1], y0=y0e, row0=pp[0],
                                     x1=W, y1=y1e, row1=pp[0],
                                     ry=_ry(W - pp[1], False)))
                elif pp[0] != cp[0]:             # 跨排: 拆两半时间 (各半段弧)
                    tmid = (t0 + t1) / 2.0
                    segs.append(dict(base, t1=tmid, x0=pp[1], y0=y0e,
                                     row0=pp[0], x1=W, y1=y0e, row1=pp[0],
                                     arp=pv['arp'],
                                     ry=_ry(W - pp[1], False)))
                    segs.append(dict(base, t0=tmid, x0=0.0, y0=y1e,
                                     row0=cp[0], x1=cp[1], y1=y1e, row1=cp[0],
                                     ry=_ry(cp[1], False)))
                else:
                    segs.append(dict(base, x0=pp[1], y0=y0e, row0=pp[0],
                                     x1=cp[1], y1=y1e, row1=cp[0],
                                     ry=_ry(cp[1] - pp[1], cu['in_blk'])))
            segs.sort(key=lambda s: s['t0'])     # QML 按 t0 升序线性查找
            out.extend(segs)
        return out

    def _model_for(self, tid):
        m = self._lane_models.get(tid)
        if m is None:
            m = EventListModel()
            self._lane_models[tid] = m
        return m

    @staticmethod
    def _box_width(nlabels, fm, spacing):
        """(挤开修复轮) 方框宽镜像 QML bx.width 合成:
           Row = Σ(单音标签字符 advance + 1) + spacing×(音数-1); Box = max(Row+8, 12)。
           旧估 8+9×字符数 低估多音和弦/大字号 → 拥挤漏判 → 方块重叠 (用户截图)。
           再 +4px: 演奏中加粗/方框放大余量"""
        n = 0
        w = 0.0
        for lbl in nlabels:
            for ch in lbl:
                if unicodedata.combining(ch):
                    continue
                w += fm.horizontalAdvance(ch) + 1.0
            n += 1
        if n > 1:
            w += spacing * (n - 1)
        return max(w + 8.0, 12.0) + 4.0

    def set_playhead(self, t):
        t = float(t) if t is not None else -1.0
        if t != self._ph:
            self._ph = t
            self.playheadMoved.emit()

    @Property(float, notify=viewChanged)
    def viewTick(self): return self._vt.get('viewTick', 0.0)
    @Property(float, notify=viewChanged)
    def pxPerTick(self): return self._vt.get('pxPerTick', 0.1)
    @Property(float, notify=viewChanged)
    def barTicks(self): return self._vt.get('barTicks', 1920.0)
    @Property(float, notify=viewChanged)
    def tpb(self): return self._vt.get('tpb', 480.0)
    @Property(float, notify=viewChanged)
    def beatsPerBar(self): return self._vt.get('beatsPerBar', 4.0)
    @Property(float, notify=viewChanged)
    def labelPt(self): return self._vt.get('labelPt', 8.0)
    @Property(float, notify=viewChanged)
    def namePt(self): return self._vt.get('namePt', 7.0)
    @Property(int, notify=viewChanged)
    def rows(self): return int(self._vt.get('rows', 1))
    @Property(float, notify=viewChanged)
    def pageTicks(self): return float(self._vt.get('pageTicks', 3840.0))
    @Property(int, notify=viewChanged)
    def kbW(self):
        """左侧音轨名称栏宽 (编辑器内嵌恒 KB_W 与卷帘键盘对齐; 悬浮谱随轨名设置)"""
        return int(self._vt.get('kbW', KB_W))
    @Property(bool, notify=viewChanged)
    def skinClear(self):
        """透明皮肤: 谱面背景透明, 音符与轨名保持不透明"""
        return bool(self._vt.get('skinClear', False))
    @Property(float, notify=playheadMoved)
    def playheadTick(self): return self._ph if self._ph is not None else -1.0
    @Property(int, notify=lanesChanged)
    def laneCount(self): return len(self.strip.lane_tids)
    @Property('QVariant', notify=lanesChanged)
    def laneNames(self):
        return [self.strip._track_name(t) for t in self.strip.lane_tids]
    @Property('QVariant', notify=lanesChanged)
    def laneColors(self):
        return [self.strip.lane_color(t) for t in self.strip.lane_tids]
    @Property('QVariant', notify=lanesChanged)
    def laneBlank(self):
        """空白乐谱排 (未选轨) 标记: QML 左列显示「+」块"""
        return [t == () for t in self.strip.lane_tids]
    @Property(bool, notify=lanesChanged)
    def laneEditable(self):
        """内嵌横幅可点左列选轨; 悬浮窗只读"""
        return bool(self.strip.lane_editable())
    @Property('QVariant', notify=lanesChanged)
    def laneCounts(self):
        return [len(self.strip.lane_events(t)) for t in self.strip.lane_tids]
    @Property('QVariant', notify=lanesChanged)
    def laneModels(self):
        return [self._model_for(t) for t in self.strip.lane_tids]
    @Property('QVariant', notify=viewChanged)
    def barStarts(self):
        """(二期) 可见范围小节起点表 [[tick, bar_no], …] (分段拍号;
           单段时 QML 仍走 barTicks 步进, 此表仅多段时非空)"""
        tsm = getattr(self.strip.mw, 'tsig_map', None)
        if tsm is None or len(tsm.events()) <= 1:
            return []
        vt = self._vt.get('viewTick', 0.0)
        span = max(1.0, self._vt.get('pageTicks', 3840.0)
                   * max(1, int(self._vt.get('rows', 1))))
        pairs = tsm.bar_starts(int(vt), int(vt + span * 1.5), limit=1024)
        return [[float(t), float(no)] for t, no in pairs]
    @Property(bool, notify=viewChanged)
    def colMode(self):
        """(小节谱轮) 列布局开关 (QML delegate/网格/播放头分流)"""
        return bool(self._vt.get('colMode', False))
    @Property(float, notify=viewChanged)
    def colW(self):
        """(小节谱轮) 固定列宽 px (等距; 与 Python COL_W 单源)"""
        return COL_W
    @Property('QVariant', notify=viewChanged)
    def barsByRow(self):
        """(小节谱轮) 每排网格表 [[[x_px, bar_no]…]…] (Canvas 小节线/小节号)"""
        return self._bars_by_row
    @Property('QVariant', notify=viewChanged)
    def ballSegs(self):
        """(小球轮) 小节谱飞行段表 [{lane,t0,t1,x0,y0,row0,x1,y1,row1,
           side,arp,prevArp,ry}…] (QML 小球 + 轨迹弧层; 非小节谱恒空)"""
        return self._ball_segs
    

class ScoreStrip(QWidget):
    """演奏谱横幅 (可复用组件, 规格§8: 编曲区内嵌与悬浮窗共用本类)。
       parent=None 时作为 roll 子控件 (共容器互斥); 传 parent 则嵌入该宿主布局
       (悬浮窗)。interactive=False = 只读展示不接手势 (悬浮窗宿主, 规格§8)。
       QML-2: 渲染在 PerformanceStrip.qml (本类仅交互/几何/数据同步)。"""
    def __init__(self, roll, mw, parent=None):
        super().__init__(parent if parent is not None else roll)
        self.roll = roll
        self.mw = mw
        self.interactive = True
        self.view_tick = roll.view_tick            # 自有视野 (ppb 恒取 roll.ppb)
        self.page_mode = False                     # (跟随二轮) 翻页模式: 跟随开+播放中
        self._page_anim = None                     # (交互轮) 翻页滑动动画
        self._page_anim_end = None                 # 当前滑动目标页首

        self._rows = 1                             # (多排轮) 显示排数, 悬浮窗 set_rows
        self.kb_w = KB_W                           # 左侧轨名栏宽 (悬浮谱宿主可改)
        self.skin_clear = False                    # 透明皮肤 (悬浮谱宿主可改)
        self.lane_tids = []                        # 车道 tid 序 (宿主注入)
        self._resizing = False
        self._resize_y0 = 0.0
        self._resize_h0 = 0.0
        self.setMouseTracking(True)
        self.setToolTip(tr('拖动顶部拉手 上下拉起演奏谱 · 字母=演奏事件 · '
                           '蓝线=未播余量(首尾圆点) · 跟随模式整页翻页 · '
                           '刻度行双击改/插速度 · 右键 精确/删除 · 滚轮同卷帘'))
        self._push_pending = False             # (性能回归第9步) 隐藏期挂起推送
        self.bridge = StripQmlBridge(self)
        self.reposition()
    def set_rows(self, n):
        """(多排轮) 悬浮窗排数 1..4: 同一窗口纵向堆叠 N 排连续小节页。
           编辑器内嵌实例不调用 (恒 1 排, 行为不变)。"""
        n = max(1, min(4, int(n)))
        if n == self._rows:
            return
        self._rows = n
        self.update()
    def showEvent(self, ev):
        """隐藏期间挂起的数据推送在显示时补齐 (性能回归第9步)。
           (空元素修复轮) 补推延迟到下一事件循环轮: 原生 show 事件泵内同步
           重建 QML 车道模型会重入 (真实 Windows 与离屏行为分叉), 曾致
           悬浮谱首开空白且暂停/空闲期无兜底推送不自愈"""
        if getattr(self, 'bridge', None) is not None \
                and getattr(self, '_push_pending', False):
            self._push_pending = False
            QTimer.singleShot(0, self._do_push)
        super().showEvent(ev)
    # ---------- 几何 (与 TempoLane 同公式, 共用容器互斥显示) ----------
    def reposition(self):
        if self.parentWidget() is not self.roll:
            self.bridge.reposition()               # 悬浮宿主: 布局管几何
            return
        rh = self.roll.height()
        lane = getattr(self.mw, 'tempo_lane', None)
        lane_h = lane.lane_h if lane is not None else 140.0
        total = max(HANDLE_H, min(HANDLE_H + lane_h, rh - int(HEADER_H)))
        self.setGeometry(0, rh - total, self.roll.width(), total)
        self.bridge.reposition()
    def set_lane_height(self, h, save=True):
        """与 TempoLane 共用 lane_h (切换面板时高度一致)"""
        lane = getattr(self.mw, 'tempo_lane', None)
        if lane is not None:
            lane.set_lane_height(h, save=save)
        self.reposition()
        self.update()
    def _paint_handle(self, p):
        """顶部拉手 (与 TempoLane 同款 FL 式 Pull up grip)"""
        w = self.width()
        p.fillRect(QRectF(0, 0, w, HANDLE_H), QColor('#101318'))
        gx = w / 2
        p.setPen(QColor('#4a515c'))
        for k, dx in enumerate((-6, 0, 6)):
            yy = 3 + (k % 2) * 3
            p.drawLine(QPointF(gx + dx - 2, yy), QPointF(gx + dx + 2, yy))
        p.setPen(QColor('#666678'))
        p.setFont(QFont('Segoe UI', 7))
        p.drawText(QRectF(gx + 12, 0, 90, HANDLE_H),
                   Qt.AlignVCenter | Qt.AlignLeft, '▾')
    def paintEvent(self, ev):
        if self.parentWidget() is self.roll:
            p = QPainter(self)
            self._paint_handle(p)
        super().paintEvent(ev)
    def resizeEvent(self, ev):
        if getattr(self, 'bridge', None) is not None:
            self.bridge.reposition()
        super().resizeEvent(ev)
    # ---------- 视图映射 (tick 等比例; ppb 单源 = roll) ----------
    def x_of_tick(self, t):
        tpb = self.mw.tmap.tpb if self.mw.tmap else 480
        return self.kb_w + (t - self.view_tick) / tpb * self.roll.ppb
    def tick_of_x(self, x):
        tpb = self.mw.tmap.tpb if self.mw.tmap else 480
        return self.view_tick + (x - self.kb_w) / self.roll.ppb * tpb
    @property
    def page_bars(self):
        """翻页模式每页小节数 (设置→显示, params/strip_page_bars, 默认 2)"""
        return max(1, int(getattr(self.mw, 'strip_page_bars', 2)))
    def _snap_page(self, t):
        """(多排修复轮) 向下取整到页倍数: 多排时视野恒以页首为锚,
           保证每排小节线与排首对齐、相邻排零重叠"""
        pt = max(1.0, self.page_bars * self.mw.bar_ticks) \
            if self.mw.tmap else 3840.0
        return max(0.0, float(int(t / pt) * pt))
    def on_roll_view_changed(self):
        """卷帘视野变化: 非翻页模式恒同步 (翻页模式中横幅视野由 sync_playhead
           按页驱动, 不随卷帘)。rows>1 时吸附到页倍数 (整页铺满配对);
           列布局按整小节页锚定 (页宽可变, 无 tick 倍数可言)"""
        if not getattr(self, 'page_mode', False):
            if not self.bridge._bars_active():   # (连续滚动) 小节谱与卷帘时间轴脱钩
                vt = self.roll.view_tick
                if self._rows > 1:
                    vt = self._snap_page(vt)
                self.view_tick = vt
        self.update()
    def sync_playhead(self):
        """主窗 40ms 轮询 (跟随二轮 2026-09-08): 跟随开+播放中 = 翻页模式 ——
           视野固定 N 小节整页 (页与页小节线对齐: 1|2→3|4→5|6...), 指针划完
           当前页翻下一页; 其余情况 (跟随关/暂停/停止) 视野恒随卷帘。
           指针线/蓝线侵蚀每轮同步。"""
        mw = self.mw
        # (连续滚动轮) 悬浮谱恒跟随播放 (无需到卷帘开跟随); 内嵌谱由跟随开关控制
        follow = (bool(getattr(mw, 'follow_on', False))
                  or self.parentWidget() is not self.roll)
        page = (follow and mw._is_playing()
                and mw.tmap is not None
                and self.roll.playhead_tick is not None
                and self.width() > self.kb_w)
        if page and not self.bridge._bars_active():
                page_ticks = self.page_bars * mw.bar_ticks
                # (多排轮) 一张 = rows 排 × 每排 page_bars 小节: 指针划完整张的
                # 最后一排才翻到下一张张首 (rows=1 退化为逐页翻, 与旧行为一致)
                rows_n = max(1, int(self._rows))
                cur_page = int(self.roll.playhead_tick / page_ticks)
                target = max(0.0, float((cur_page // rows_n) * rows_n * page_ticks))
                if abs(self.view_tick - target) > 0.5:
                    self._slide_view_to(target)        # (交互轮) 翻页 150ms 滑动
        elif self.bridge._bars_active() and self.bridge._bars_paged():
            # (整页排版轮) 悬浮窗小节谱 1~4 排: 当前页 = 播放头已越过的翻页刻
            # 个数 (翻页刻 = 衔接节前一节末音结束); 整页直接切换不滑动,
            # 暂停/停止同样按播放头定页 (谱面停在正在演奏的那一页)
            self.bridge._bars_page = self.bars_page_at(
                self.roll.playhead_tick or 0.0)
        elif self.page_mode:                       # 退出翻页: 回到卷帘视野
            self.view_tick = self.roll.view_tick
            if self._rows > 1:                     # (多排修复轮) 吸附页首
                self.view_tick = self._snap_page(self.view_tick)
        self.page_mode = page
        self.update()
    def bars_page_at(self, tick):
        """(整页排版轮) tick 所在页下标: 首个翻页刻 > tick 的页"""
        br = self.bridge
        cache = br._bars_cache or {}
        if not cache.get('secs'):
            return 0
        rows_n = max(1, int(self._rows))
        W = max(60.0, self.width() - self.kb_w)
        pages = br._bars_pages(cache, rows_n, W)
        for k, pg in enumerate(pages):
            if pg['flip'] is None or tick < pg['flip']:
                return k
        return len(pages) - 1
    def _slide_view_to(self, target):
        """翻页滑动: 150ms OutCubic 从当前视野滑向新页首。
           轮询重复触发同目标时不重启 (沿用进行中的滑动自然收敛)。
           被替换/销毁的旧动画引用先置空再 stop, 防悬空访问。"""
        old = self._page_anim
        self._page_anim = None
        if old is not None:
            try:
                if old.state() == QAbstractAnimation.Running                         and self._page_anim_end == target:
                    self._page_anim = old; self._page_anim_end = target
                    return                          # 沿用进行中的同目标滑动
                old.stop()
            except RuntimeError:
                pass                                # 已被销毁的残留引用
        anim = QVariantAnimation(self)
        anim.setStartValue(self.view_tick); anim.setEndValue(target)
        anim.setDuration(150); anim.setEasingCurve(QEasingCurve.OutCubic)
        anim.valueChanged.connect(self._slide_step)
        anim.finished.connect(self._slide_done)
        anim.start(QAbstractAnimation.DeleteWhenStopped)
        self._page_anim = anim
        self._page_anim_end = target
    def _slide_step(self, v):
        self.view_tick = float(v); self.update()
    def _slide_done(self):
        target = self._page_anim_end
        self._page_anim = None; self._page_anim_end = None   # DeleteWhenStopped 已删动画
        self.view_tick = float(target); self.update()
    def update(self, *a):
        """(QML-2) 重绘入口 = 数据同步入口。
           (性能回归第9步) 隐藏时跳过 push 只记挂起, 避免三实例空转。
           (重入修复 2026-09-08) push 经 singleShot(0) 合并调度 —— viewChanged
           链内同步重建 QML 车道模型会重入事件循环 (QML 委托创建泵事件),
           导致滚动步进永不完成/画布不跟随 —— 推迟到独立事件循环轮次执行。"""
        b = getattr(self, 'bridge', None)
        if b is not None:
            if self.isVisible():
                if not getattr(self, '_push_scheduled', False):
                    self._push_scheduled = True
                    QTimer.singleShot(0, self._do_push)
            else:
                self._push_pending = True
        super().update(*a)
    def _do_push(self):
        self._push_scheduled = False
        if self.isVisible():
            self.bridge.push()
        else:
            self._push_pending = True
    # ---------- 车道配置 ----------
    # 车道键: int = 单轨; tuple(≥2) = 合并轨 (多轨音符并集编译为一条车道);
    # () = 空白乐谱排 (无轨, 左列显示「+」)
    def set_lanes(self, tids):
        keys = []
        for k in tids:
            if isinstance(k, (list, tuple)):
                k = tuple(k)
                k = k[0] if len(k) == 1 else k
            keys.append(k)
        self.lane_tids = keys
        self.update()
    def lane_events(self, key):
        """车道演奏事件: 单轨 = perf_by_tid; 合并轨 = 并集编译 (perf_ver 门缓存)"""
        mw = self.mw
        if not isinstance(key, tuple):
            return mw.perf_by_tid.get(key, [])
        if not key or mw.tmap is None:
            return []
        ver = getattr(mw, 'perf_ver', 0)
        cache = getattr(self, '_merged', None)
        if cache is None or cache.get(None) != ver:
            cache = self._merged = {None: ver}
        evs = cache.get(key)
        if evs is None:
            evs = cache[key] = self._compile_merged(key)
        return evs
    def _compile_merged(self, key):
        """合并车道: 琶音事件取各源轨自身编译结果 (组号按轨偏移 (i+1)*1000+g,
           不同轨同号组不串组), 其余音符跨轨同刻合成和弦; 同刻琶音与普通音
           分列两个事件, 普通音不被卷进别轨的琶音块"""
        from dataclasses import replace
        from performance_model import compile_performance
        mw = self.mw
        arp_evs = []
        plain = []
        for i, tid in enumerate(key):
            own = mw.perf_by_tid.get(tid, [])
            arp_ticks = set()
            for e in own:
                if StripQmlBridge._ev_gid(e):
                    arp_ticks.add(int(e.start_tick))
                    arp_evs.append(replace(e, arps=tuple(
                        (i + 1) * 1000 + a if a > 0 else 0 for a in e.arps)))
            plain.extend(n for n in mw.raw_notes
                         if getattr(n, 'tid', 0) == tid
                         and int(n.start_tick) not in arp_ticks)
        evs = compile_performance(
            plain, mw.tmap, tsig_map=getattr(mw, 'tsig_map', None),
            fill_keys=getattr(mw, 'perf_fill_keys', None)) + arp_evs
        evs.sort(key=lambda e: (int(e.start_tick),
                                1 if StripQmlBridge._ev_gid(e) else 0))
        return evs
    def lane_color(self, key):
        if isinstance(key, tuple):
            if not key:
                return 'transparent'
            key = key[0]
        return self.roll.track_colors.get(key, '#4f9cf9')
    def lane_editable(self):
        return self.interactive and self.parentWidget() is self.roll
    def _track_name(self, tid):
        if isinstance(tid, tuple):
            return ' + '.join(self._track_name(t) for t in tid)
        for t in self.mw.tracks:
            if t.tid == tid: return t.name
        return tr('轨道 {n}', n=tid + 1)
    def _note_labels(self, ev):
        """单音标签列表 (升序音高一一对应); 字符模式 = 设置「演奏谱字符」:
           key = 键位字母 (一级, 未映射回退音名) / jianpu = 简谱数字 (纯数字,
           八度点由 _note_dots 几何圆点表达, 组合符整形偏移大/点小已弃用) /
           name = 音名"""
        mode = STRIP_LABEL_MODES[
            int(getattr(self.mw, 'strip_label', 0)) % len(STRIP_LABEL_MODES)]
        if mode == 'jianpu':   # 简谱 (纯数字)
            return [NOTE_JIANPU[p % 12] for p in ev.notes]
        if mode == 'name':     # 音名
            return [note_name(p) for p in ev.notes]
        km = getattr(self.mw, '_label_keymap', None) or {}
        return [km.get(p) or note_name(p) for p in ev.notes]
    def _note_dots(self, ev):
        """(点轮) 简谱八度点: 每音符 [上加数, 下加数] (QML 几何圆点图元);
           非简谱模式 = [] (无点)"""
        mode = STRIP_LABEL_MODES[
            int(getattr(self.mw, 'strip_label', 0)) % len(STRIP_LABEL_MODES)]
        if mode != 'jianpu':
            return []
        base = int(getattr(self.mw, 'strip_jianpu_base', 4))
        return [list(jianpu_dots(p, base)) for p in ev.notes]
    def _block_text(self, ev):
        """块内文字: 单音标签空格拼接 (同格和弦保持单行拼接表达)"""
        return ' '.join(self._note_labels(ev))
    @staticmethod
    def _ladder_sub_y(ev, block, ppt, med, line_y, box_h, lane_h,
                      prefer=0, prev_idx=0, crowded=False):
        """(槽位轮·方向感知) 行阶梯统一函数 —— 方块不相互挤、不跨蓝线、
           且八度点方向与所在侧一致:
           槽位表 = 按车道几何生成的绝对 y (lane 局部), 5 候选:
           线上 A3/A2/A1 (顶/中/贴线, 同侧间隔 box_h+2 互不重叠) +
           线下 B1/B2 (贴线/底); ≥1 过滤去重升序, 车道矮时自然缩排。
           prefer: -1 = 上加点 (用线上槽) / +1 = 下加点 (用线下槽) /
           0 = 无点按音高 (rep vs med);
           不挤 → 该侧贴线槽; 拥挤且 prev 在同侧 → 向外轮转 (上方块向上
           叠 / 下方块向下叠, 环绕); prev 在异侧 → 该侧贴线槽进入。
           返回 (y, idx); idx 供链式维护。"""
        narrow = block * ppt < 24.0
        chord = len(ev.notes) != 1
        a1 = line_y - 2.0 - box_h
        a2 = a1 - box_h - 2.0
        a3 = a2 - box_h - 2.0
        b1 = line_y + 4.0
        b2 = min(lane_h - box_h - 1.0, b1 + box_h + 2.0)
        slots = sorted({y for y in (a3, a2, a1, b1, b2) if y >= 1.0})
        if not slots:
            return 1.0, 0
        above = [i for i, s in enumerate(slots) if s <= a1 + 0.5]
        below = [i for i, s in enumerate(slots) if s >= b1 - 0.5]
        if prefer == 0:
            rep = ev.notes[0] if len(ev.notes) == 1 \
                else ev.notes[len(ev.notes) // 2]
            prefer = -1 if rep >= med else 1
        side = above if prefer < 0 else below
        if not side:
            side = above or below or [0]
        if crowded and prev_idx in side:
            i = side.index(prev_idx)
            idx = side[(i - 1) % len(side)] if prefer < 0 \
                else side[(i + 1) % len(side)]
        else:
            idx = side[-1] if prefer < 0 else side[0]   # 该侧贴线槽进入
        return slots[idx], idx
    # ---------- 交互 (渲染在 QML, 命中/写入全部留在本层) ----------
    def lane_at(self, x, y):
        """内嵌横幅左列命中: → 车道序号 / None (轨名列之外或不在车道内)"""
        if x > self.kb_w or not self.lane_tids:
            return None
        y -= HANDLE_H if self.parentWidget() is self.roll else 0
        lane_h = (self.height() - HANDLE_H) / max(1, int(self._rows)) - RULER_H
        lane_h /= max(1, len(self.lane_tids))
        if y < RULER_H or lane_h <= 0:
            return None
        i = int((y - RULER_H) // lane_h)
        return i if 0 <= i < len(self.lane_tids) else None
    def mousePressEvent(self, ev):
        if not self.interactive or self.parentWidget() is not self.roll:
            super().mousePressEvent(ev); return
        if ev.button() == Qt.LeftButton and ev.position().y() <= HANDLE_H:
            r = self.mw.router
            if not r.begin(r.OWNER_TEMPO): ev.accept(); return
            lane = getattr(self.mw, 'tempo_lane', None)
            self._resizing = True
            self._resize_y0 = ev.globalPosition().y()
            self._resize_h0 = lane.lane_h if lane is not None else 140.0
            self.setCursor(Qt.SizeVerCursor)
            ev.accept(); return
        # 乐谱区交互保护: 事件不再冒泡到底层卷帘 (曾误触发画笔添加音符)
        i = self.lane_at(ev.position().x(), ev.position().y())
        cb = getattr(self, 'on_lane_click', None)
        if ev.button() == Qt.LeftButton and i is not None and cb is not None:
            cb(i)
        ev.accept()
    def mouseDoubleClickEvent(self, ev):
        if self.interactive and self.parentWidget() is self.roll:
            ev.accept(); return
        super().mouseDoubleClickEvent(ev)
    def mouseMoveEvent(self, ev):
        if self.parentWidget() is self.roll and getattr(self, '_resizing', False):
            r = self.mw.router
            if not r.check(r.OWNER_TEMPO): ev.accept(); return
            dy = self._resize_y0 - ev.globalPosition().y()
            self.set_lane_height(self._resize_h0 + dy, save=False)
            ev.accept(); return
        if self.parentWidget() is self.roll and ev.position().y() <= HANDLE_H:
            self.setCursor(Qt.SizeVerCursor)
        elif self.lane_editable() and self.lane_at(
                ev.position().x(), ev.position().y()) is not None:
            self.setCursor(Qt.PointingHandCursor)
        else:
            self.setCursor(Qt.ArrowCursor)
        if self.interactive and self.parentWidget() is self.roll:
            ev.accept(); return
        super().mouseMoveEvent(ev)
    def mouseReleaseEvent(self, ev):
        if getattr(self, '_resizing', False):
            self._resizing = False
            self.mw.router.end(self.mw.router.OWNER_TEMPO)
            import settings_store as store
            lane = getattr(self.mw, 'tempo_lane', None)
            if lane is not None:
                store.save_lane_h(lane.lane_h)
            ev.accept(); return
        if self.interactive and self.parentWidget() is self.roll:
            ev.accept(); return
        super().mouseReleaseEvent(ev)
    def wheelEvent(self, ev):
        """滚轮转发卷帘 (缩放/平移与 MIDI 编辑同一套; x 对齐卷帘);
           悬浮宿主只读不接手势 (interactive=False, 规格§8)"""
        if not self.interactive:
            ev.ignore(); return
        new = QWheelEvent(QPointF(ev.position().x(), 300),
                          QPointF(ev.position().x(), 300),
                          ev.pixelDelta(), ev.angleDelta(), ev.buttons(),
                          ev.modifiers(), Qt.ScrollUpdate, False)
        self.roll.wheelEvent(new)
    # (演奏谱重设计一期 2026-09-26) 横幅内速度编辑入口 (刻度行双击/右键) 已随
    # 时间刻度尺移除 —— 速度编辑统一走 Tempo 车道与卷帘标尺右键 (_mark_bpm)。
    # 悬浮窗底部 BPM 数值 (_MetaLabel 双击) 不受影响。
