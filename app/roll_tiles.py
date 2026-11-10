# -*- coding: utf-8 -*-
"""瓦片渲染器 (P3-G 自 view_roll.py 抽出; 预加载轮 2026-09-08 重构):
   网格/标尺/音符的 tick 锚定分片缓存与绘制。
   职责: 画布/标尺双层瓦片缓存、瓦片绘制(blit)、单瓦片渲染、空闲预取(缓冲圈)。
   不负责: 垂直静态层(bgV)、播放指针、实时层(选中/高亮)、输入事件。
   预加载轮架构 (定稿: 主视口+一圈缓冲区 = 预加载/渲染分界, 概览条仅可视化):
     · 标尺条与画布瓦片分离 —— 标尺 key 无纵向量/音符版本, 纵向滚动与音符
       编辑零失效 (tempo 变化经 tmap.version 失效);
     · 画布瓦片按 int(view_note_start) 行锚定烘焙 (frac=0 相位, 底部留
       V_MARGIN_ROWS 行余量), blit 时叠加 -frac*row_h 子像素偏移 ——
       纵向滚动从"整体作废重烘"变为"命中+平移贴图";
     · 缓存上限 = 内存预算 (~96MB) 折算片数, 淘汰离当前视口最远者
       (滑出视口的瓦片就近保留 = "滑出转预加载");
     · prefetch(): 空闲时按离视野距离烘焙视口 ±M 屏 (M 随缩放联动) 内的
       缺失瓦片, 滑入视口即命中 = "预加载转渲染"。
   TileRenderer 持 roll 引用, 经动态分派调用 roll 的 _note_colors/_draw_note_label/
   visible_notes (editor 覆写版自动生效)。"""
import math
from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import QColor, QPainter, QPen, QPixmap, QPolygonF
from common import KB_W, HEADER_H
import snap as snap_mod

TILE_W = 1024.0           # 瓦片宽 (逻辑 px): 网格/标尺/音符按 tick 锚定分片缓存
TISSUE_PAD_PX = 24.0      # 声组织瓦片左右重叠 (羽化跨片混合, 消接缝)
TILE_CACHE_MAX = 10       # (QML ruler_only 冻结路径保留) 旧单层缓存上限
CANVAS_BUDGET = 96 * 1024 * 1024   # 画布瓦片内存预算: 上限 = 预算/单片字节
CANVAS_MIN, CANVAS_MAX = 12, 40    # 预算折算片数的上下钳位 (dpr 大时保底 12)
RULER_CACHE_MAX = 64      # 标尺条瓦片上限 (单片仅 1024×HEADER_H, 极廉价)
V_MARGIN_ROWS = 2         # 画布瓦片底部余量行数: 吸收行内小数滚动相位


class TileRenderer:
    def __init__(self, roll):
        self.roll = roll
        self._tiles = {}     # 画布瓦片: ('C', i, 行锚, ...) -> QPixmap(h+2rh)
        self._rulers = {}    # 标尺瓦片: ('R', i, ...) -> QPixmap(1024×HEADER_H)
        self._tissue = {}    # 声组织瓦片: 与音符解耦, 缩放/tissue.version 才失效
        self._v_margin = 0.0  # 画布纵向烘焙余量 (px, 渲染期临时); QML 直绘恒 0
        self._ruler_only = False

    def clear(self):
        self._tiles.clear()
        self._rulers.clear()
        self._tissue.clear()

    def clear_tissue(self):
        """仅清声组织位图 (音符瓦片可保留)。"""
        self._tissue.clear()

    def clear_canvas(self):
        """仅清网格+音符画布 (声组织位图保留, 供音符流式写入复用)。"""
        self._tiles.clear()

    # ---------- 视野/键值/预算 ----------
    def _visible_tiles(self):
        """当前视口覆盖的瓦片下标范围 [i0, i1]"""
        roll = self.roll
        view_px = roll.view_tick / roll.tmap.tpb * roll.ppb
        w = roll.width()
        i0 = max(0, int(math.floor((view_px - KB_W) / TILE_W)))
        i1 = int(math.ceil((view_px - KB_W + w) / TILE_W))
        return i0, i1

    def _ring_tiles(self):
        """缓冲圈: 视口 ±M 片, M 以屏为单位 → 缩放联动 (定稿的分界定义)"""
        i0, i1 = self._visible_tiles()
        m = max(2, int(0.75 * (i1 - i0 + 1)))
        return i0, i1, m

    def _canvas_key(self, i, skip):
        roll = self.roll
        tx = getattr(roll, 'transcription', None)
        # 弱网格态 + 声组织版本 (位图已烘焙进画布时 key 需含 version)
        tissue_ver = 0
        traj = 0
        if tx is not None:
            traj = 1
            if getattr(tx, 'tissue_ready', False):
                tissue = getattr(tx, 'tissue', None)
                tissue_ver = getattr(tissue, 'version', 0) if tissue else 0
        # 行锚 = int(view_note_start): 行内小数相位不进 key (纵向滚动命中)
        return ('C', i, int(roll.view_note_start), round(roll.ppb, 2),
                roll.height(), roll._data_ver, roll.active_tid, roll.snap_beats,
                roll.bar_ticks, len(roll.tmap.ticks), roll.view_oct_span,
                getattr(getattr(roll, 'tsig_map', None), 'version', 0),
                getattr(roll.tmap, 'version', 0), roll.label_mode,
                tuple(sorted(roll.label_custom.items())), tuple(sorted(skip)),
                traj, tissue_ver,
                1 if getattr(roll, 'show_tissue', True) else 0,
                tuple(sorted(getattr(roll, 'hidden_tids', ()))))

    def _tissue_key(self, i):
        """声组织独立缓存键: 不含 _data_ver (音符改动不重烘声组织)。"""
        roll = self.roll
        tx = getattr(roll, 'transcription', None)
        tissue = getattr(tx, 'tissue', None) if tx else None
        ver = getattr(tissue, 'version', 0) if tissue else 0
        return ('T', i, int(roll.view_note_start), round(roll.ppb, 2),
                roll.height(), roll.view_oct_span, ver,
                round(roll.devicePixelRatioF(), 2))

    def _ruler_key(self, i):
        roll = self.roll
        # 无纵向量/音符版本: 纵向滚动与音符编辑零失效
        return ('R', i, round(roll.ppb, 2), roll.bar_ticks,
                len(roll.tmap.ticks), getattr(roll.tmap, 'version', 0),
                getattr(getattr(roll, 'tsig_map', None), 'version', 0))

    def _evict_canvas(self):
        """内存预算淘汰: 超预算时淘汰离当前视口最远的瓦片 (视口外就近保留)"""
        roll = self.roll
        if roll.tmap is None:
            return
        dpr = roll.devicePixelRatioF()
        per = TILE_W * (roll.height() + V_MARGIN_ROWS * roll.row_h()) \
            * dpr * dpr * 4
        max_n = getattr(self, '_cache_max_override', None)   # 测试钩子: 覆盖预算
        if max_n is None:
            max_n = max(CANVAS_MIN,
                        min(CANVAS_MAX, int(CANVAS_BUDGET / max(1.0, per))))
        i0, i1 = self._visible_tiles()
        while len(self._tiles) > max_n:
            far_k, far_d = None, -1
            for k in self._tiles:
                i = k[1]
                d = 0 if i0 <= i <= i1 else min(abs(i - i0), abs(i - i1))
                if d > far_d:
                    far_k, far_d = k, d
            if far_k is None:
                break
            del self._tiles[far_k]

    # ---------- 绘制入口 ----------
    def draw(self, p, skip=frozenset(), ruler_only=False):
        """blit 视口内的瓦片; 未命中才渲染。
           光栅路线: 标尺条(y=0) + 画布瓦片(y=-frac*row_h 行锚定偏移) 双层。
           ruler_only (QML-1 冻结路径): 旧单层行为原样保留。
           skip (拖动中音符) 并入画布 key: 不进瓦片、由实时层每帧绘制 (无残影)"""
        roll = self.roll
        self._ruler_only = ruler_only
        if ruler_only:
            self._draw_legacy(p, skip)
            return
        view_px = roll.view_tick / roll.tmap.tpb * roll.ppb
        rh = roll.row_h()
        y_off = -(roll.view_note_start - int(roll.view_note_start)) * rh
        i0, i1 = self._visible_tiles()
        x0 = int(round(KB_W + i0 * TILE_W - view_px))   # 首片整数定位, 片间无缝
        # ---- 标尺条 (y=0 全宽: 键盘列上方仍是标尺行, 不裁剪) ----
        for i in range(i0, i1 + 1):
            rk = self._ruler_key(i)
            pm = self._rulers.get(rk)
            if pm is None:
                pm = self.render_ruler(i)
                self._rulers[rk] = pm
                while len(self._rulers) > RULER_CACHE_MAX:
                    self._rulers.pop(next(iter(self._rulers)))
            p.drawPixmap(QPointF(x0 + (i - i0) * TILE_W, 0), pm)
        # ---- 画布瓦片 (键盘遮罩 2026-09-08): 裁剪到画布区 [KB_W, width) ——
        #      网格/音符不再画上琴键 (竖线穿透钢琴块的根因: 瓦片 blit 起点
        #      x0 ≤ KB_W, 视野左侧内容外溢), 键盘列底下内容不参与合成;
        #      瓦片位图保持全宽 (tick 锚定与滚动位置无关, 不能烘焙期裁) ----
        rh = roll.row_h()
        y_off = -(roll.view_note_start - int(roll.view_note_start)) * rh
        p.save()
        p.setClipRect(QRectF(KB_W, 0, roll.width() - KB_W, roll.height()))
        for i in range(i0, i1 + 1):
            ck = self._canvas_key(i, skip)
            pm = self._tiles.get(ck)
            if pm is None:
                pm = self.render_canvas(i, skip)
                self._tiles[ck] = pm
                self._evict_canvas()
            p.drawPixmap(QPointF(x0 + (i - i0) * TILE_W, y_off), pm)
        p.restore()

    def _draw_legacy(self, p, skip):
        """(QML-1 ruler_only 冻结路径) 旧单层瓦片: 标尺行+小节线段, 行为不变
           (key 首元素为 int i, 与新 'C'/'R' 域天然不串)"""
        roll = self.roll
        view_px = roll.view_tick / roll.tmap.tpb * roll.ppb
        base = (round(roll.ppb, 2), round(roll.view_note_start, 3), roll.height(),
                roll._data_ver, roll.active_tid, roll.snap_beats,
                roll.bar_ticks, len(roll.tmap.ticks), roll.view_oct_span,
                getattr(getattr(roll, 'tsig_map', None), 'version', 0),
                getattr(roll.tmap, 'version', 0),
                roll.label_mode, tuple(sorted(roll.label_custom.items())),
                tuple(sorted(skip)), True)
        i0, i1 = self._visible_tiles()
        x0 = int(round(KB_W + i0 * TILE_W - view_px))
        for k, i in enumerate(range(i0, i1 + 1)):
            key = (i,) + base
            pm = self._tiles.get(key)
            if pm is None:
                pm = self.render(i, skip)
                self._tiles[key] = pm
                while len(self._tiles) > TILE_CACHE_MAX:
                    self._tiles.pop(next(iter(self._tiles)))
            p.drawPixmap(QPointF(x0 + (i - i0) * TILE_W, 0), pm)

    # ---------- 单瓦片渲染 ----------
    def render(self, i, skip=frozenset()):
        """(QML ruler_only 路径) 渲染第 i 片: 标尺行段 (旧单层行为)"""
        roll = self.roll
        tile_ticks = TILE_W / roll.ppb * roll.tmap.tpb
        ta = i * tile_ticks
        dpr = roll.devicePixelRatioF()
        pm = QPixmap(int(TILE_W * dpr), int(roll.height() * dpr))
        pm.setDevicePixelRatio(dpr); pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing, False)   # 网格直线: 免抗锯齿更省更清晰
        if getattr(self, '_ruler_only', False):
            self.draw_ruler_row(p, ta, ta + tile_ticks)
        p.end()
        return pm

    def render_ruler(self, i):
        """渲染第 i 片标尺条 (1024×HEADER_H): 底色/小节编号 (刻度轮: 仅数字,
           竖线/变速刻度移除 —— 画布区全程小节线归画布瓦片)"""
        roll = self.roll
        tile_ticks = TILE_W / roll.ppb * roll.tmap.tpb
        ta = i * tile_ticks
        dpr = roll.devicePixelRatioF()
        pm = QPixmap(int(TILE_W * dpr), int(HEADER_H * dpr))
        pm.setDevicePixelRatio(dpr); pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing, False)
        self.draw_ruler_row(p, ta, ta + tile_ticks, line_h=HEADER_H, lines=False)
        p.end()
        return pm

    def render_canvas(self, i, skip=frozenset()):
        """渲染第 i 片画布 (1024×(h+2rh)): 网格 + 声组织位图 + 音符/字母。
           纵向行锚定: 以 frac=0 相位烘焙 (blit 时叠加 -frac*row_h), 底部留
           V_MARGIN_ROWS 行余量 —— 纵向滚动不再整体重烘"""
        roll = self.roll
        tile_ticks = TILE_W / roll.ppb * roll.tmap.tpb
        ta = i * tile_ticks
        tb = ta + tile_ticks
        dpr = roll.devicePixelRatioF()
        h = roll.height()
        rh = roll.row_h()
        pm = QPixmap(int(TILE_W * dpr), int((h + V_MARGIN_ROWS * rh) * dpr))
        pm.setDevicePixelRatio(dpr); pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing, False)   # 网格直线: 免抗锯齿更省更清晰
        vs0 = roll.view_note_start
        roll.view_note_start = float(int(vs0))   # 行锚定相位 (lo/hi 不变, frac→0)
        try:
            self._v_margin = V_MARGIN_ROWS * rh
            self.draw_grid_area(p, ta, tb)
            # 声组织: 独立位图缓存, 音符改动只 blit 不重算矢量
            self._blit_tissue(p, i, ta, tb)
            p.setRenderHint(QPainter.Antialiasing, True)    # 音符/字母: 抗锯齿
            self.draw_notes_range(p, ta, tb, skip)
        finally:
            self._v_margin = 0.0
            roll.view_note_start = vs0
        p.end()
        return pm

    def _blit_tissue(self, p, i, ta, tb):
        """把已烘焙的声组织瓦片画进画布 (网格之上、音符之下)。"""
        roll = self.roll
        if not getattr(roll, 'show_tissue', True):
            return
        tx = getattr(roll, 'transcription', None)
        if tx is None or not getattr(tx, 'tissue_ready', False):
            return
        tissue = getattr(tx, 'tissue', None)
        if tissue is None or not tissue.blobs:
            return
        tk = self._tissue_key(i)
        tpm = self._tissue.get(tk)
        if tpm is None:
            tpm = self._render_tissue_tile(i, ta, tb)
            self._tissue[tk] = tpm
            self._evict_tissue()
        pad = TISSUE_PAD_PX
        dpr = roll.devicePixelRatioF()
        sx = int(round(pad * dpr))
        sw = int(round(TILE_W * dpr))
        sh = tpm.height()
        p.drawPixmap(0, 0, sw, sh, tpm, sx, 0, sw, sh)

    def _render_tissue_tile(self, i, ta, tb):
        """光栅化一片声组织 (透明底), 左右各留 TISSUE_PAD_PX 重叠区消接缝。"""
        roll = self.roll
        dpr = roll.devicePixelRatioF()
        h = roll.height()
        rh = roll.row_h()
        pad = TISSUE_PAD_PX
        pm_w = TILE_W + 2.0 * pad
        pm = QPixmap(int(pm_w * dpr), int((h + V_MARGIN_ROWS * rh) * dpr))
        pm.setDevicePixelRatio(dpr)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing, True)
        vs0 = roll.view_note_start
        roll.view_note_start = float(int(vs0))
        try:
            self._v_margin = V_MARGIN_ROWS * rh
            ppt = roll.ppb / roll.tmap.tpb
            pad_ticks = pad / max(ppt, 1e-6)
            tissue = roll.transcription.tissue
            p.translate(pad, 0.0)
            tissue.draw_tile(p, roll, ta - pad_ticks, tb + pad_ticks,
                             tile_w=pm_w, v_margin=self._v_margin,
                             local_x0=0.0)
        finally:
            self._v_margin = 0.0
            roll.view_note_start = vs0
        p.end()
        return pm

    def _evict_tissue(self):
        """声组织瓦片上限 (与画布同量级, 不含音符改动失效)。"""
        max_n = max(CANVAS_MIN, min(CANVAS_MAX, 24))
        while len(self._tissue) > max_n:
            self._tissue.pop(next(iter(self._tissue)))

    # ---------- 分区绘制 (QML mode2 亦直调: 签名/缺省行为不可变) ----------
    def draw_grid_range(self, p, ta, tb):
        """[ta,tb) 范围内的 网格/拍线/小节标尺/BPM 标记 (兼容入口 = 全量两段)"""
        self.draw_grid_area(p, ta, tb)
        self.draw_ruler_row(p, ta, tb)
    @staticmethod
    def _bar_multiple(ppt, bt0):
        """(自适应网格·FL 式) 小节合并倍数 N (2 的幂, 1..64):
           保证 N×小节宽 ≥ 8px —— 极限缩放时小节线/拍线向粗合并,
           每瓦片线条数有上限 (缩小时网格糊成一团的根因)"""
        bar_px = bt0 * ppt
        if bar_px >= 8.0 or bar_px <= 0:
            return 1
        return min(64, 2 ** int(math.ceil(math.log2(8.0 / bar_px))))
    def draw_grid_area(self, p, ta, tb):
        """[ta,tb) 画布区网格: 隔行小节底色 / 对齐细网格 / 拍线 / 小节线(全程)
           (Q 轮修复) 瓦片本地坐标: x=0 为 ta, 不引用任何视野量 —— 否则每片开头
           64px 网格/小节线被窗口坐标裁剪掉 (放大后小节线缺失的根因)。
           (预加载轮) 全程小节线自标尺行移入画布瓦片 (标尺条只画条内段);
           _v_margin > 0 时网格延伸进底部余量 (行锚定烘焙)
           (自适应网格·FL 式) 小节线/底色按 N 小节合并 (保证 N×小节宽 ≥ 8px,
           2 的幂), 拍线仅在拍距 ≥8px 时绘制 —— 极限缩放时线条数有上限。
           (扒谱模式) 深色网格 + 白色音高声组织 (Pitch Tissue, 非频谱)。"""
        roll = self.roll
        h = roll.height() + self._v_margin
        tpb = roll.tmap.tpb
        ppt = roll.ppb / tpb
        p.save()
        p.setClipRect(QRectF(0, HEADER_H, TILE_W, h - HEADER_H))
        tx = getattr(roll, 'transcription', None)
        traj_on = tx is not None   # 扒谱会话中弱化网格; 声组织位图叠在网格上

        bt0 = roll.bar_ticks
        n = self._bar_multiple(ppt, bt0)
        step_bar = bt0 * n
        # (配色轮·FL 式) 亮底暗线: 小节线最深, 拍线次之 —— 线是"缝隙"非"凸脊"
        pen_bar = QPen(QColor('#0c1a24'), 1)
        pen_beat = QPen(QColor('#24343e'), 1)
        pen_sub = QPen(QColor('#20303a'), 1)
        if traj_on:
            pen_bar = QPen(QColor(90, 130, 180, 70), 1)
            pen_beat = QPen(QColor(255, 255, 255, 18), 1)

        # (二期) 分段拍号: 小节线按段起点+段内步进 (段边界强制小节线)
        tsm = getattr(roll, 'tsig_map', None)
        if tsm is not None and len(tsm.events()) > 1:
            for bt_start, _no in tsm.bar_starts(ta - 1, tb + 1, limit=2048):
                n_seg = self._bar_multiple(ppt, tsm.bar_ticks_at(bt_start))
                m0 = tsm.measure_start(bt_start)
                k = int(round((bt_start - m0)
                              / max(1.0, tsm.bar_ticks_at(bt_start))))
                if k % max(1, n_seg):
                    continue
                x0b = (bt_start - ta) * ppt
                p.setPen(pen_bar)
                p.drawLine(QPointF(x0b, HEADER_H), QPointF(x0b, h))
        else:
            t = math.floor(ta / step_bar) * step_bar
            while t <= tb:
                x0b = (t - ta) * ppt
                p.setPen(pen_bar)
                p.drawLine(QPointF(x0b, HEADER_H), QPointF(x0b, h))
                t += step_bar

        if not traj_on:
            # (解耦轮) 网格布局与吸附解耦: 显示恒为 FL 式自适应阶梯
            # (line_step_beats, 随缩放自动合并 ≥60px), 与对齐档位无关 ——
            # 对齐只决定音符落点, 不改变网格布局
            st = snap_mod.line_step_beats(roll.ppb) * tpb
            t = math.floor(ta / st) * st
            while t <= tb:
                x = (t - ta) * ppt
                p.setPen(pen_sub)
                p.drawLine(QPointF(x, HEADER_H), QPointF(x, h))
                t += st

        if tpb * ppt >= 8.0:                      # (自适应网格) 拍距 <8px 整级省略
            t = math.floor(ta / tpb) * tpb
            while t <= tb:
                if traj_on and abs(t % bt0) < 1e-6:
                    t += tpb
                    continue
                x = (t - ta) * ppt
                p.setPen(pen_beat)
                p.drawLine(QPointF(x, HEADER_H), QPointF(x, h))
                t += tpb

        p.restore()
    def draw_ruler_row(self, p, ta, tb, line_h=None, lines=True):
        """[ta,tb) 小节标尺行 + 小节线 + 变速标记。
           line_h: 小节线下探深度; None = 旧逻辑 (ruler_only→HEADER_H 段 /
           全量→画布高)。标尺条瓦片传 HEADER_H (画布区段由画布瓦片负责)
           (自适应网格·FL 式) 小节线/编号随合并倍数 N 稀疏化 (与画布网格同式)
           (刻度轮) render_ruler 传 lines=False: 标尺条只保留小节号数字 ——
           竖线/速度刻度移除, 竖线由画布瓦片全程绘制 (不再"侵蚀"刻度尺)"""
        roll = self.roll
        h = roll.height()
        tpb = roll.tmap.tpb
        ppt = roll.ppb / tpb
        p.fillRect(QRectF(0, 0, TILE_W, HEADER_H), QColor('#132029'))
        bt = roll.bar_ticks; bar_w = bt / tpb * roll.ppb
        n = self._bar_multiple(ppt, bt)
        lab_step = max(1 if bar_w >= 36 else (4 if bar_w >= 9 else 16), n)
        step = bt * n
        t = math.floor(ta / step) * step
        pen_bar = QPen(QColor('#333b46'), 1)
        if line_h is None:
            line_h = HEADER_H if getattr(self, '_ruler_only', False) else h
        tsm = getattr(roll, 'tsig_map', None)
        multi = tsm is not None and len(tsm.events()) > 1
        if multi:
            # (二期收尾) 分段拍号: 线位/小节号随段宽 (bar_starts 逐段起点),
            # 与画布网格分段分支同口径 —— 旧实现按单一线距步进, 段边界错位;
            # lines=False (刻度条) 时只出小节号不出线
            for bt_start, no in tsm.bar_starts(max(0, ta - 1), tb + 1,
                                               limit=2048):
                n_seg = self._bar_multiple(ppt, tsm.bar_ticks_at(bt_start))
                m0 = tsm.measure_start(bt_start)
                k = int(round((bt_start - m0)
                              / max(1.0, tsm.bar_ticks_at(bt_start))))
                if k % max(1, n_seg):
                    continue                    # 极限缩小: 段内 N 合一稀疏
                x = (bt_start - ta) * ppt
                if lines:
                    p.setPen(pen_bar)
                    p.drawLine(QPointF(x, 0), QPointF(x, line_h))
                if (no - 1) % lab_step == 0:
                    p.setPen(QColor('#9aa4b0')); p.setFont(roll.f_bar)
                    p.drawText(QPointF(x + 3, HEADER_H - 9), str(no))
        else:
            while t <= tb:
                x = (t - ta) * ppt
                if lines:
                    p.setPen(pen_bar); p.drawLine(QPointF(x, 0), QPointF(x, line_h))
                bar_no = int(round(t / bt)) + 1
                if (bar_no - 1) % lab_step == 0:
                    p.setPen(QColor('#9aa4b0')); p.setFont(roll.f_bar)
                    p.drawText(QPointF(x + 3, HEADER_H - 9), str(bar_no))
                t += step
        if lines:
            p.setFont(roll.f_bar)
            for i, tc in enumerate(roll.tmap.ticks):
                if ta <= tc <= tb:
                    x = (tc - ta) * ppt
                    p.setPen(QPen(QColor('#d99a3d'), 1))
                    p.drawLine(QPointF(x, HEADER_H - 6), QPointF(x, HEADER_H))
                    p.setPen(QColor('#e8b05a'))
                    p.drawText(QPointF(x + 3, 10), f"{roll.tmap.bpms[i]:.0f}")
        if not lines:
            # (标记轮) FL 式旗标标注: 左尖角五边形指向标记位置, 类型配色
            mw = getattr(roll, 'mw', None)
            if mw is not None:
                key_text = str(getattr(mw, 'key_label', '1=C'))
                fm = p.fontMetrics()

                def _flag(x, y, text, tcol, bg):
                    """FL 式旗标: 五边形 (左尖角) + 居中文字"""
                    w = fm.horizontalAdvance(text) + 14
                    h = 13
                    p.setPen(QPen(QColor('#0d1117'), 1))
                    p.setBrush(QColor(bg))
                    poly = QPolygonF([
                        QPointF(x, y + h / 2),           # 左尖角指向 tick
                        QPointF(x + 4, y),
                        QPointF(x + w, y),
                        QPointF(x + w, y + h),
                        QPointF(x + 4, y + h)])
                    p.drawPolygon(poly)
                    p.setPen(tcol)
                    p.drawText(QRectF(x + 5, y, w - 6, h),
                               Qt.AlignVCenter | Qt.AlignHCenter, text)

                # 节拍旗标 (每个拍号段起点: 各段拍号各自标注 —— 拍号更改后
                # 标签随段联动, 不再恒显曲首 4/4); 调性旗标跟首面拍号旗标右侧
                tsm = getattr(mw, 'tsig_map', None)
                if tsm is not None:
                    first_dx = None
                    for ev_t, ev_n, ev_d in tsm.events():
                        if not (ta <= ev_t <= tb):
                            continue
                        dx = (ev_t - ta) * ppt
                        _flag(dx, 13, '♩%d/%d' % (ev_n, ev_d),
                              QColor('#ffffff'), '#2a313b')
                        if first_dx is None:
                            first_dx = dx
                    if first_dx is not None:
                        mw_dx = fm.horizontalAdvance('♩4/4') + 14
                        _flag(first_dx + mw_dx + 2, 13, key_text,
                              QColor('#8ab4e8'), '#182430')
                # BPM 旗标: 每个速度事件处 (金字, 30px 密度守护)
                last_x = -100
                for i, tc in enumerate(roll.tmap.ticks):
                    if ta <= tc <= tb:
                        x = (tc - ta) * ppt
                        if x - last_x < 30:
                            continue
                        last_x = x
                        _flag(x, 1, f"{roll.tmap.bpms[i]:.0f}",
                              QColor('#e8b05a'), '#2a313b')
    def draw_notes_range(self, p, ta, tb, skip=frozenset(), active_fn=None):
        """[ta,tb) 范围内的音符 + 字母。
           跨片长音在相邻瓦片重复绘制 (overdraw, 像素重合无缝) —— 瓦片本地坐标,
           不钳位到瓦片边界 (否则每片出现断口 + 字母重复);
           skip (选中/拖动中音符) 不进瓦片, 由实时层每帧绘制 (无拖动残影);
           active_fn (QML-3/MuseScore 路线): nt -> 是否当前演奏 (琥珀高亮);
           _v_margin > 0 时底部余量行的音符一并烘焙 (行锚定)
           (perf轮 P3/P5) 两段式: <6px 远景快段收集后 AA 关逐色 fillRect
           (无描边/圆角/字母, 同色零状态切换); ≥6px 放大段逐音符但
           同色连续复用 pen/brush (_color_cache 返回同一元组对象, 身份判同)"""
        roll = self.roll
        rh = roll.row_h()
        lo, hi = roll.note_low, roll.note_high
        y_off = (roll.view_note_start - lo) * rh
        ppt = roll.ppb / roll.tmap.tpb          # 每 tick 像素
        m = self._v_margin
        n_min = lo - 1 - (int(round(m / rh)) if m > 0 and rh > 0 else 0)
        p.save()
        p.setClipRect(QRectF(0, HEADER_H, TILE_W,
                             roll.height() + m - HEADER_H))
        fast = []                               # (QRectF, fill) 远景快段
        slow = []                               # 放大段: 逐音符圆角+描边+字母
        for nt in roll.visible_notes(ta, tb):
            if nt.end_tick <= ta or nt.start_tick >= tb: continue
            if getattr(nt, 'nid', id(nt)) in skip: continue
            if not (n_min <= nt.note <= hi + 1): continue
            x0 = (nt.start_tick - ta) * ppt; x1 = (nt.end_tick - ta) * ppt
            y = HEADER_H + (hi - nt.note) * rh - y_off + 1.0
            nh = max(rh - 1.0, 2.0)
            fill, edge = roll._note_colors(nt, bool(active_fn and active_fn(nt)))
            w = x1 - x0
            if w < 6.0:                         # (P5) 原 <2.5 才快绘; 2.5~6 平铺直角
                fast.append((QRectF(x0, y, max(w, 6.0) if w >= 2.5
                                    else max(w, 1.2), nh), fill))
                continue
            slow.append((nt, x0, x1, y, nh, fill, edge))
        if fast:                                # AA 关 + 显式色参: 状态切换归零
            p.setRenderHint(QPainter.Antialiasing, False)
            for r, fill in fast:
                p.fillRect(r, fill)
            p.setRenderHint(QPainter.Antialiasing, True)
        last = None                             # (P3) 同色连续复用 pen/brush
        for nt, x0, x1, y, nh, fill, edge in slow:
            cols = (fill, edge)
            if cols is not last:
                p.setPen(QPen(edge, 1)); p.setBrush(fill); last = cols
            p.drawRoundedRect(QRectF(x0, y, x1 - x0, nh), 3.0, 3.0)
            roll._draw_note_label(p, nt, x0, x1, y, nh)
        p.restore()

    # ---------- (预加载轮) 空闲预取: 缓冲圈 ----------
    def prefetch(self):
        """空闲预取一片: 视口 ±M 屏 (缓冲圈) 内缺失的画布/标尺瓦片, 按离视野
           距离升序, 每次调用最多烘焙 1 片 (16ms 时钟空闲驱动, 交互帧零抢占)。
           返回是否做了工作 (False = 缓冲圈已满)"""
        roll = self.roll
        if roll.tmap is None or roll.width() <= 0 or roll.height() <= 0:
            return False
        i0, i1, m = self._ring_tiles()
        center = (i0 + i1) / 2.0
        order = [i for i in sorted(range(i0 - m, i1 + m + 1),
                                   key=lambda t: abs(t - center)) if i >= 0]
        for i in order:
            ck = self._canvas_key(i, frozenset())
            if ck not in self._tiles:
                self._tiles[ck] = self.render_canvas(i, frozenset())
                self._evict_canvas()
                return True
        for i in order:
            rk = self._ruler_key(i)
            if rk not in self._rulers:
                self._rulers[rk] = self.render_ruler(i)
                while len(self._rulers) > RULER_CACHE_MAX:
                    self._rulers.pop(next(iter(self._rulers)))
                return True
        return False

    def prefetch_span(self):
        """缓冲圈覆盖的 tick 区间 (概览条可视化用; 无数据返回 None)"""
        roll = self.roll
        if roll.tmap is None:
            return None
        i0, i1, m = self._ring_tiles()
        tile_ticks = TILE_W / roll.ppb * roll.tmap.tpb
        return (max(0.0, (i0 - m) * tile_ticks), (i1 + m + 1) * tile_ticks)
