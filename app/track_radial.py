# -*- coding: utf-8 -*-
"""音轨径向选择器 (播放 →「映射范围 · 音轨」): 浅色线框版。
   布局与入场动画复用钢琴卷帘「乐谱添加音轨」(track_picker): 中心菱形【收起】,
   四条斜向音轨 (东南/东北/西南/西北 = 第 1~4 轨) 自中心平移放大, 左右各 5 条横向
   音轨自顶向下依次「放大 → 缩小 → 再放大」; 14 槽恒显示, 无轨 = 占位不可点。
   每条音轨内端绿色菱形指示灯: 亮 = 已映射到键盘输出, 灰 = 未映射。
   由选项径向浮层持有并绘制 (同一时钟), 自身不是 QWidget。"""
import math
from PySide6.QtCore import Qt, QPointF, QRectF
from PySide6.QtGui import QColor, QPen, QPolygonF, QTransform, QPainterPath
from track_picker import (DIA_R, DIAG_CX, DIAG_CY, DIAG_W, DIAG_H, SIDE_W, SIDE_H,
                          SIDE_ROWS, DIAG_SLOTS, N_SLOTS, _ease_cubic, _ease_back,
                          _pop, _clamp)
from radial_controls import font
import ui_motion as M

SCALE = 0.56                     # 设计坐标 (track_picker) → 径向浮层设计坐标
CENTER = (0.0, 60.0)             # 默认中心 (径向浮层设计坐标, 选项中心为原点)
# 选择器半高 (斜条旋转后的外包络, 设计坐标): 用于摆在播放子面板下方且不越出屏幕
HALF_H = (DIAG_CY + (DIAG_W + DIAG_H) / 2 / math.sqrt(2)) * SCALE


def mapped_tids(mw):
    """当前映射到键盘输出的轨集合 (map_tids=None = 全部轨)"""
    mt = getattr(mw, 'map_tids', None)
    allt = {t.tid for t in getattr(mw, 'tracks', [])}
    return set(allt) if mt is None else set(mt) & allt


class TrackRadial:
    """浮层内图层: open() / close() / paint(p, now) / press(pos) / busy(now)。
       勾选只改子面板草稿 (is_on / toggle 钩子), 长按【确认】才写入 map_tids"""
    def __init__(self, ov):
        self.ov = ov
        self.mw = ov.mw
        self.phase = 'hidden'            # hidden | open | closing
        self.t_open = self.t_close = 0.0
        self.center = CENTER
        self.flash = {}
        self.hover = None
        self.is_on = lambda tid: tid in mapped_tids(self.mw)
        self.toggle = lambda tid: None

    def visible(self):
        return self.phase != 'hidden'

    def open(self, now, center=None, is_on=None, toggle=None):
        self.center = tuple(center) if center is not None else CENTER
        if is_on is not None:
            self.is_on, self.toggle = is_on, toggle
        self.phase, self.t_open, self.flash = 'open', now, {}

    def close(self, now):
        if self.phase == 'open':
            self.phase, self.t_close = 'closing', now

    def busy(self, now):
        if self.phase == 'closing':
            return True
        return self.phase == 'open' and (now - self.t_open < 1100 or bool(self.flash))

    def tick(self, now):
        if self.phase == 'closing' and now - self.t_close >= 220:
            self.phase = 'hidden'
        self.flash = {k: v for k, v in self.flash.items() if now - v < 220}

    # ---- 布局 (track_picker 设计坐标) ----
    def layout(self):
        tracks = list(getattr(self.mw, 'tracks', []) or [])[:N_SLOTS]

        def tid(i):
            return tracks[i].tid if i < len(tracks) else None
        els = [{'kind': 'dia', 'id': 'fold', 'x': 0.0, 'y': 0.0, 'grp': 'c'}]
        for i, (sx, sy) in enumerate(DIAG_SLOTS):
            els.append({'kind': 'bar', 'id': 'slot%d' % i, 'tid': tid(i), 'grp': 'diag',
                        'x': sx * DIAG_CX, 'y': sy * DIAG_CY, 'w': DIAG_W, 'h': DIAG_H,
                        'rot': 45.0 if sx * sy > 0 else -45.0, 'inner': -sx})
        n = len(SIDE_ROWS)
        for side, first in ((-1, 4), (1, 4 + n)):
            for r, (y, ax) in enumerate(SIDE_ROWS):
                els.append({'kind': 'bar', 'id': 'slot%d' % (first + r),
                            'tid': tid(first + r), 'grp': 'side', 'row': r,
                            'y_prev': SIDE_ROWS[r - 1][0] if r else y,
                            'x': side * ax, 'y': y, 'w': SIDE_W, 'h': SIDE_H,
                            'rot': 0.0, 'inner': -side})
        return els

    def state(self, el, now):
        """(x, y, scale, opacity) 或 None —— 时序同 track_picker: 中心 0~240ms 弹出;
           斜条 60~400ms 自中心平移放大; 左右列 120ms 起自顶向下每行 +80ms 弹三段;
           收回 = 180ms 合拢到中心并淡出。减少动态效果 = 原位 150ms 淡入"""
        dt = now - self.t_open
        g = el['grp']
        if M.reduced():
            x, y, s, o = el['x'], el['y'], 1.0, _clamp(dt / M.REDUCED)
        elif g == 'c':
            p = _clamp(dt / 240.0)
            x, y, s, o = 0.0, 0.0, _ease_back(p), min(1.0, p * 3.0)
        elif g == 'diag':
            p = _clamp((dt - 60.0) / 340.0)
            e = _ease_cubic(p)
            x, y = el['x'] * e, el['y'] * e
            s, o = _ease_back(p) * 0.85 + 0.15 * e, min(1.0, p * 2.5)
        else:
            p = _clamp((dt - 120.0 - 80.0 * el['row']) / 380.0)
            x = el['x']
            y = el['y_prev'] + (el['y'] - el['y_prev']) * _ease_cubic(min(1.0, p / 0.4))
            s, o = _pop(p), min(1.0, p * 3.0)
        if self.phase == 'closing':
            f = 1.0 - _ease_cubic(_clamp((now - self.t_close) / 180.0))
            if M.reduced():
                o *= f
            else:
                x, y, s, o = x * f, y * f, s * (0.6 + 0.4 * f), o * f
        t0 = self.flash.get(el['id'])
        if t0 is not None and now - t0 < 200.0 and not M.reduced():
            s *= 1.0 + 0.08 * math.sin((now - t0) / 200.0 * math.pi)
        if s < 0.02 or o < 0.02:
            return None
        return x, y, s, o

    def xf(self, el, st):
        """track_picker 设计坐标 → 浮层控件坐标"""
        k = self.ov.k * SCALE
        ox, oy = self.ov.to_px(*self.center)
        tf = QTransform()
        tf.translate(ox + st[0] * k, oy + st[1] * k)
        tf.rotate(el.get('rot', 0.0))
        tf.scale(st[2] * k, st[2] * k)
        return tf

    def center_px(self):
        return QPointF(*self.ov.to_px(*self.center))

    def shape(self, el):
        path = QPainterPath()
        if el['kind'] == 'dia':
            r = DIA_R
            path.addPolygon(QPolygonF([QPointF(0, -r), QPointF(r, 0), QPointF(0, r),
                                       QPointF(-r, 0), QPointF(0, -r)]))
        else:
            path.addRect(QRectF(-el['w'] / 2, -el['h'] / 2, el['w'], el['h']))
        return path

    def hit(self, pos):
        if self.phase != 'open':
            return None
        now = self.ov.clock.now()
        for el in sorted(self.layout(), key=lambda e: e['kind'] != 'dia'):
            st = self.state(el, now)
            if st is None or st[3] < 0.5:
                continue
            if el['kind'] == 'bar' and el['tid'] is None:
                continue                         # 占位槽不可点
            inv, ok = self.xf(el, st).inverted()
            if ok and self.shape(el).contains(inv.map(QPointF(pos))):
                return el
        return None

    def press(self, pos):
        """→ True = 已消费。点【收起】回到播放子面板; 点音轨 = 切换映射"""
        el = self.hit(pos)
        now = self.ov.clock.now()
        if el is None:
            return False
        if el['id'] == 'fold':
            self.close(now)
        else:
            self.toggle(el['tid'])               # 只改草稿, 长按【确认】才生效
            self.flash[el['id']] = now
        return True

    # ---- 绘制 (浅色线框) ----
    def paint(self, p, now, under=None):
        """under: 压暗层之上、音轨条之下的绘制 (映射范围连线被音轨条遮住, 不穿越)"""
        if self.phase == 'hidden':
            return
        dim = _clamp((now - self.t_open) / 200.0)
        if self.phase == 'closing':
            dim *= 1.0 - _clamp((now - self.t_close) / 200.0)
        p.fillRect(QRectF(0, 0, self.ov.width(), self.ov.height()),
                   QColor(0, 0, 0, int(70 * dim)))
        if under is not None:
            under()
        on = {t.tid for t in self.mw.tracks if self.is_on(t.tid)}
        names = {t.tid: t.name or ('音轨 %d' % (t.tid + 1)) for t in self.mw.tracks}
        roll = getattr(getattr(self.ov.host, 'strip', None), 'roll', None)
        colors = getattr(roll, 'track_colors', {}) or {}
        for el in self.layout():
            st = self.state(el, now)
            if st is None:
                continue
            p.save()
            p.setTransform(self.xf(el, st))
            p.setOpacity(st[3])
            hov = self.hover == el['id']
            if el['kind'] == 'dia':
                self._paint_dia(p, hov)
            else:
                t = el['tid']
                self._paint_bar(p, el, names.get(t) if t is not None else None,
                                colors.get(t, M.BLUE), t in on, hov)
            p.restore()

    def _paint_dia(self, p, hov):
        r = DIA_R
        poly = QPolygonF([QPointF(0, -r), QPointF(r, 0), QPointF(0, r), QPointF(-r, 0)])
        p.setBrush(QColor(M.PAPER).darker(105) if hov else QColor(M.PAPER))
        p.setPen(QPen(QColor(M.INK), 2.4))
        p.drawPolygon(poly)
        p.setPen(QColor(M.INK)); p.setFont(font(26, True))
        p.drawText(QRectF(-r, -r, 2 * r, 2 * r), Qt.AlignCenter, '收起')

    def _paint_bar(self, p, el, name, color, on, hov):
        """音轨条: 白底黑框; 内端绿色菱形指示灯 (亮=已映射 / 灰=未映射); 外端轨色条;
           name=None = 占位槽「音轨」(不可点)"""
        w, h = el['w'], el['h']
        p.setBrush(QColor(M.PAPER).darker(106) if hov else QColor(M.PAPER))
        p.setPen(QPen(QColor(M.INK) if name is not None else QColor('#9aa0a8'), 2.4))
        p.drawRoundedRect(QRectF(-w / 2, -h / 2, w, h), 8, 8)
        inner = el['inner']
        if name is not None:
            p.setPen(Qt.NoPen); p.setBrush(QColor(color))
            p.drawRect(QRectF(-inner * (w / 2 - 12) - 4, -h / 2 + 10, 8, h - 20))
        cx, d = inner * (w / 2 - 34), 14.0
        box = QPolygonF([QPointF(0, -d), QPointF(d, 0), QPointF(0, d), QPointF(-d, 0)])
        p.save()
        p.translate(cx, 0)
        p.rotate(-el.get('rot', 0.0))           # 指示灯恒为屏幕正菱形
        if name is None:
            p.setBrush(Qt.NoBrush); p.setPen(QPen(QColor('#c4c8ce'), 2.0))
        elif on:
            p.setBrush(QColor(M.GREEN)); p.setPen(QPen(QColor('#1e8c46'), 2.0))
        else:
            p.setBrush(QColor('#d4d7dc')); p.setPen(QPen(QColor('#9aa0a8'), 2.0))
        p.drawPolygon(box)
        p.restore()
        p.setPen(QColor(M.INK) if name is not None else QColor('#9aa0a8'))
        p.setFont(font(26))
        txt = name if name is not None else '音轨'
        txt = p.fontMetrics().elidedText(txt, Qt.ElideRight, int(w - 140))
        p.drawText(QRectF(-w / 2 + 70, -h / 2, w - 140, h), Qt.AlignCenter, txt)

    def move(self, pos):
        el = self.hit(pos)
        hid = el['id'] if el else None
        if hid != self.hover:
            self.hover = hid
            return True
        return False
