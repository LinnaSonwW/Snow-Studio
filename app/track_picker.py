# -*- coding: utf-8 -*-
"""乐谱排选轨浮层 (编辑器卷帘之上, 演奏谱面板以上的区域)。
   入口: 演奏谱左列「+」块 / 轨名 → 卷帘变暗且不可交互, 中央浮现「选择」菱形;
   点击「选择」→ 北/南滑出「添加」「收起」「删除」, 顶部「乐谱切换」条由一条线
   向两侧展开; 四条斜向音轨 (东南/东北/西南/西北 = 第 1~4 轨)、左列 (第 5~9 轨)、
   右列 (第 10~14 轨) 同时弹出, 左右列自顶向下依次「放大 → 缩小 → 再放大」。
   14 个槽位始终全部显示: 无对应音轨的槽位 = 默认「音轨」占位 (不可点)。
   音轨条菱形勾选框: 蓝色填充 = 并入当前乐谱排, 空白 = 不选; 同排 ≥2 轨 = 合并车道。
   动画 = 单一时钟 (16ms PreciseTimer) 逐帧计算; 命中 = 绘制变换的逆映射。
   坐标 = 设计示意图实测 (「选择」中心为原点), 按可用区域整体缩放 (上限 1.0)。"""
import math
from PySide6.QtCore import Qt, QTimer, QElapsedTimer, QPointF, QRectF, QEvent
from PySide6.QtGui import (QPainter, QColor, QPen, QFont, QPolygonF, QTransform,
                           QPainterPath)
from PySide6.QtWidgets import QWidget
from i18n import t as tr

DIA_R = 66.0                         # 菱形半对角线
NS_OFF = 165.0                       # 添加 / 收起 距中心
DEL_Y = 330.0                        # 删除 (收起正下方, 与乐谱切换条上下对称)
DIAG_CX, DIAG_CY = 143.0, 140.0      # 斜条中心
DIAG_W, DIAG_H = 246.0, 90.0
SIDE_W, SIDE_H = 371.0, 56.0
SIDE_ROWS = ((-152.0, 497.0), (-77.0, 447.0), (0.0, 332.0),
             (77.0, 447.0), (152.0, 497.0))          # (行 y, 中心 |x|) 自顶向下
SW_Y, SW_W, SW_H = -327.0, 448.0, 97.0               # 乐谱切换条
SW_ROD = 15.0                        # 两端竖轴宽
BOX_X0, BOX_X1 = -690.0, 690.0       # 整体包围盒 (缩放依据)
BOX_Y0, BOX_Y1 = -380.0, 400.0
CAP_H = 28                           # 顶部提示行 (不参与缩放)
# 斜向槽位 = 第 1~4 轨 (用户指定顺序: 东南 / 东北 / 西南 / 西北)
DIAG_SLOTS = ((1, 1), (1, -1), (-1, 1), (-1, -1))
N_SLOTS = 4 + 2 * len(SIDE_ROWS)     # 14
LAYOUT_NAMES = {'follow': '跟弹', 'bars': '小节谱'}

def _ease_cubic(p):
    return 1.0 - (1.0 - p) ** 3


def _ease_back(p, s=1.70158):
    p -= 1.0
    return 1.0 + (s + 1.0) * p * p * p + s * p * p


def _pop(p):
    """放大 → 缩小 → 再放大 (落定 1.0): 0 → 1.15 → 0.92 → 1.0, 各段端点导数为 0"""
    if p <= 0.0:
        return 0.0
    if p < 0.40:
        return 1.15 * _ease_cubic(p / 0.40)
    if p < 0.70:
        return 1.15 - 0.23 * (1.0 - math.cos((p - 0.40) / 0.30 * math.pi)) / 2.0
    if p < 1.0:
        return 0.92 + 0.08 * (1.0 - math.cos((p - 0.70) / 0.30 * math.pi)) / 2.0
    return 1.0


def _clamp(v):
    return 0.0 if v < 0.0 else (1.0 if v > 1.0 else v)


class TrackPickerOverlay(QWidget):
    """卷帘子控件: 覆盖卷帘 (演奏谱横幅以上), 吞掉全部鼠标/滚轮/键盘 = 卷帘不可交互"""
    def __init__(self, roll, ctrl):
        super().__init__(roll)
        self.roll = roll
        self.ctrl = ctrl                     # EditorSessionController
        self.lane_idx = 0
        self.phase = 'hidden'                # hidden | open | closing
        self.t_open = self.t_exp = self.t_col = self.t_close = None
        self.t_sw = None                     # 乐谱切换转轮起始
        self._sw_prev = ''
        self._flash = {}                     # 槽位 id -> 点击反馈起始 ms
        self._hover = None                   # 悬停元素 id
        self._skew = 0.0
        self._clock = QElapsedTimer(); self._clock.start()
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.PreciseTimer)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        roll.installEventFilter(self)
        self.hide()

    # ---------- 生命周期 ----------
    @property
    def expanded(self):
        return self.t_exp is not None and self.t_col is None

    def open_for(self, lane_idx):
        """打开/重定向到第 lane_idx 排 (已打开时只切换目标排, 不重放动画)"""
        self.lane_idx = int(lane_idx)
        if self.phase != 'open':
            self.phase = 'open'
            self.t_open = self._now()
            self.t_exp = self.t_col = self.t_close = self.t_sw = None
            self._flash = {}
        self.sync_geometry()
        self.show(); self.raise_(); self.setFocus()
        self._run()
        self.update()

    def close_overlay(self):
        if self.phase in ('hidden', 'closing'):
            return
        self.phase = 'closing'
        self.t_close = self._now()
        self._run()

    def settle(self):
        """跳过全部动画到终态 (测试用: 离屏环境动画时钟不推进)"""
        self._skew += 10000.0
        self._tick()

    def sync_geometry(self):
        """覆盖卷帘全宽; 下缘止于演奏谱横幅顶 (横幅保持可见, 选轨即时预览);
           横幅以上空间不足 (整体缩放 < 0.6, 字过小) 时改为覆盖整个卷帘"""
        r = self.roll
        h = r.height()
        strip = getattr(r, 'score_strip', None)
        if strip is not None and strip.isVisible() and 80 < strip.y() < h:
            k = min((r.width() - 16) / (BOX_X1 - BOX_X0),
                    (strip.y() - CAP_H - 12) / (BOX_Y1 - BOX_Y0))
            if k >= 0.6:
                h = strip.y()
        self.setGeometry(0, 0, r.width(), h)

    def eventFilter(self, obj, ev):
        if obj is self.roll and ev.type() == QEvent.Resize and self.isVisible():
            self.sync_geometry()
        return False

    # ---------- 布局 (设计坐标, 「选择」中心为原点) ----------
    def _tracks(self):
        return list(getattr(self.ctrl.mw, 'tracks', []) or [])[:N_SLOTS]

    def _layout(self):
        els = [{'kind': 'dia', 'id': 'select', 'x': 0.0, 'y': 0.0, 'grp': 'c'},
               {'kind': 'dia', 'id': 'add', 'x': 0.0, 'y': -NS_OFF, 'grp': 'ns'},
               {'kind': 'dia', 'id': 'fold', 'x': 0.0, 'y': NS_OFF, 'grp': 'ns'},
               {'kind': 'dia', 'id': 'delete', 'x': 0.0, 'y': DEL_Y, 'grp': 'ns'},
               {'kind': 'sw', 'id': 'switch', 'x': 0.0, 'y': SW_Y,
                'w': SW_W, 'h': SW_H, 'grp': 'sw'}]
        tracks = self._tracks()
        def tid(i):
            return tracks[i].tid if i < len(tracks) else None
        for i, (sx, sy) in enumerate(DIAG_SLOTS):
            els.append({'kind': 'bar', 'id': 'slot%d' % i, 'tid': tid(i),
                        'grp': 'diag', 'x': sx * DIAG_CX, 'y': sy * DIAG_CY,
                        'w': DIAG_W, 'h': DIAG_H,
                        'rot': 45.0 if sx * sy > 0 else -45.0,
                        'inner': -sx, 'dark': True})
        n = len(SIDE_ROWS)
        for side, first in ((-1, 4), (1, 4 + n)):
            for r, (y, ax) in enumerate(SIDE_ROWS):
                els.append({'kind': 'bar', 'id': 'slot%d' % (first + r),
                            'tid': tid(first + r), 'grp': 'side', 'row': r,
                            'y_prev': SIDE_ROWS[r - 1][0] if r else y,
                            'x': side * ax, 'y': y, 'w': SIDE_W, 'h': SIDE_H,
                            'rot': 0.0, 'inner': -side, 'dark': False})
        return els

    # ---------- 时钟 / 几何 ----------
    def _now(self):
        return self._clock.elapsed() + self._skew

    def _scale(self):
        s = min((self.width() - 16) / (BOX_X1 - BOX_X0),
                (self.height() - CAP_H - 12) / (BOX_Y1 - BOX_Y0), 1.0)
        return max(0.3, s)

    def origin(self):
        """「选择」中心的控件坐标 (包围盒整体居中于提示行以下的区域)"""
        k = self._scale()
        cx = self.width() / 2.0 - (BOX_X0 + BOX_X1) / 2.0 * k
        cy = CAP_H + (self.height() - CAP_H) / 2.0 - (BOX_Y0 + BOX_Y1) / 2.0 * k
        return cx, cy

    def _dim(self, now):
        if self.phase == 'hidden' or self.t_open is None:
            return 0.0
        a = _ease_cubic(_clamp((now - self.t_open) / 200.0))
        if self.phase == 'closing':
            a *= 1.0 - _ease_cubic(_clamp((now - self.t_close) / 200.0))
        return a

    def can_delete(self):
        rows = getattr(self.ctrl, 'score_rows', [])
        return len(rows) > 1 or bool(rows and rows[0])

    def _state(self, el, now):
        """元素当前 (x, y, scale, opacity, unfold) / None = 不可见。时序 (点「选择」起算):
           北/南菱形 0~260ms 自中心滑出 (最早); 乐谱切换条 40ms 起 一条线 → 两端竖轴
           向两侧展开; 斜条 60~400ms 自中心平移放大; 左右列 120ms 起自顶向下每行
           +80ms「放大→缩小→再放大」(最后); 各组同时进行。收回 = 180ms 合拢到中心"""
        g = el['grp']
        uf = 1.0
        if g == 'c':
            p = _clamp((now - self.t_open - 60.0) / 240.0)
            x, y, s, o = el['x'], el['y'], _ease_back(p), min(1.0, p * 3.0)
        else:
            if self.t_exp is None:
                return None
            dt = (self.t_col if self.t_col is not None else now) - self.t_exp
            if g == 'ns':
                p = _clamp(dt / 260.0)
                e = _ease_back(p)
                x, y, s, o = el['x'] * e, el['y'] * e, 0.4 + 0.6 * e, min(1.0, p * 3.0)
                if el['id'] == 'delete' and not self.can_delete():
                    o *= 0.4
            elif g == 'sw':
                p = _clamp((dt - 40.0) / 300.0)
                x, y, s, o = el['x'], el['y'], 1.0, min(1.0, p * 4.0)
                uf = _ease_cubic(p)
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
            if self.t_col is not None:
                f = 1.0 - _ease_cubic(_clamp((now - self.t_col) / 180.0))
                if g == 'sw':
                    uf *= f; o *= f
                else:
                    x, y, s, o = x * f, y * f, s * f, o * f
        if self.phase == 'closing':
            f = 1.0 - _ease_cubic(_clamp((now - self.t_close) / 180.0))
            s, o, uf = s * (0.6 + 0.4 * f), o * f, uf * f
        t0 = self._flash.get(el['id'])
        if t0 is not None and now - t0 < 200.0:
            s *= 1.0 + 0.08 * math.sin((now - t0) / 200.0 * math.pi)
        if s < 0.02 or o < 0.02 or uf < 0.0:
            return None
        return x, y, s, o, uf

    def _xf(self, el, st):
        """设计坐标元素 → 控件坐标变换 (绘制 / 命中 / 间距测试共用)"""
        k = self._scale()
        ox, oy = self.origin()
        tf = QTransform()
        tf.translate(ox + st[0] * k, oy + st[1] * k)
        tf.rotate(el.get('rot', 0.0))
        tf.scale(st[2] * k, st[2] * k)
        return tf

    def _local_shape(self, el, uf=1.0):
        """元素局部轮廓 (菱形 / 矩形; 乐谱切换条按展开比例收窄)"""
        path = QPainterPath()
        if el['kind'] == 'dia':
            r = DIA_R
            path.addPolygon(QPolygonF([QPointF(0, -r), QPointF(r, 0),
                                       QPointF(0, r), QPointF(-r, 0),
                                       QPointF(0, -r)]))
        else:
            w = el['w'] if el['kind'] != 'sw' else max(SW_ROD * 2, el['w'] * uf)
            path.addRect(QRectF(-w / 2, -el['h'] / 2, w, el['h']))
        return path

    def _clickable(self, el):
        if el['kind'] == 'bar':
            return el['tid'] is not None           # 占位槽不可点
        if el['id'] == 'delete':
            return self.can_delete()
        if el['id'] == 'switch':
            return self.expanded
        return True

    def _hit(self, pos):
        now = self._now()
        for el in sorted(self._layout(), key=lambda e: e['kind'] != 'dia'):
            st = self._state(el, now)
            if st is None or st[3] < 0.5 or not self._clickable(el):
                continue
            inv, ok = self._xf(el, st).inverted()
            if ok and self._local_shape(el, st[4]).contains(inv.map(QPointF(pos))):
                return el
        return None

    # ---------- 绘制 ----------
    def _row_tids(self):
        rows = getattr(self.ctrl, 'score_rows', [])
        return rows[self.lane_idx] if 0 <= self.lane_idx < len(rows) else []

    def paintEvent(self, _ev):
        now = self._now()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor(8, 10, 14, int(165 * self._dim(now))))
        checked = set(self._row_tids())
        names = {t.tid: t.name for t in self._tracks()}
        colors = getattr(self.roll, 'track_colors', {}) or {}
        for el in self._layout():
            st = self._state(el, now)
            if st is None:
                continue
            p.save()
            p.setTransform(self._xf(el, st))
            p.setOpacity(st[3])
            hov = self._hover == el['id'] and self._clickable(el)
            if el['kind'] == 'dia':
                self._paint_dia(p, el['id'], hov)
            elif el['kind'] == 'sw':
                self._paint_switch(p, el, st[4], hov, now)
            else:
                t = el['tid']
                self._paint_bar(p, el, names.get(t) if t is not None else None,
                                colors.get(t, '#4f9cf9'), t in checked, hov)
            p.restore()
        if self._dim(now) > 0.5:
            p.setOpacity(1.0)
            p.setPen(QColor(200, 206, 216))
            p.setFont(QFont('Segoe UI', 9))
            n = len(checked)
            rows = len(getattr(self.ctrl, 'score_rows', [])) or 1
            txt = tr('第 {i} 排 / 共 {m} 排 · 已选 {n} 轨',
                     i=self.lane_idx + 1, m=rows, n=n)
            if n >= 2:
                txt += tr(' (合并)')
            p.drawText(QRectF(0, 6, self.width(), CAP_H - 6), Qt.AlignHCenter, txt)
        p.end()

    def _font(self, px, bold=False):
        f = QFont('Segoe UI')
        f.setPixelSize(px)                 # 像素制: 随设计坐标一起缩放
        f.setBold(bold)
        return f

    def _paint_dia(self, p, kid, hov):
        r = DIA_R
        poly = QPolygonF([QPointF(0, -r), QPointF(r, 0), QPointF(0, r), QPointF(-r, 0)])
        p.setBrush(QColor(52, 56, 64) if hov else QColor(30, 32, 37))
        p.setPen(QPen(QColor(232, 176, 90) if kid == 'select' and self.expanded
                      else QColor(255, 255, 255, 90), 1.6))
        p.drawPolygon(poly)
        p.setPen(QColor(240, 242, 246))
        p.setFont(self._font(24, True))
        label = {'select': tr('选择'), 'add': tr('添加'),
                 'fold': tr('收起'), 'delete': tr('删除')}[kid]
        p.drawText(QRectF(-r, -r, 2 * r, 2 * r), Qt.AlignCenter, label)

    def _paint_bar(self, p, el, name, color, on, hov):
        """音轨条: 菱形勾选框在内端 (蓝填 = 选中, 空框 = 不选); 真实轨外端带轨色条;
           name=None = 占位槽 (默认「音轨」样式, 不可点)"""
        w, h = el['w'], el['h']
        base = QColor(88, 92, 100) if el['dark'] else QColor(128, 132, 140)
        if hov:
            base = base.lighter(118)
        p.setBrush(base)
        p.setPen(QPen(QColor(255, 255, 255, 60), 1.4))
        p.drawRoundedRect(QRectF(-w / 2, -h / 2, w, h), 5, 5)
        inner = el['inner']
        if name is not None:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(color))
            p.drawRect(QRectF(-inner * (w / 2 - 8) - 2.5, -h / 2 + 8, 5, h - 16))
        cx, d = inner * (w / 2 - 28), 11.0
        box = QPolygonF([QPointF(0, -d), QPointF(d, 0), QPointF(0, d), QPointF(-d, 0)])
        p.save()
        p.translate(cx, 0)
        p.rotate(-el.get('rot', 0.0))       # 勾选框恒为屏幕正菱形 (斜条上不随条旋转)
        p.setBrush(QColor('#4f9cf9') if on else Qt.NoBrush)
        p.setPen(QPen(QColor('#8fc0ff') if on else QColor(235, 238, 245, 170), 1.6))
        p.drawPolygon(box)
        p.restore()
        p.setPen(QColor(245, 246, 248) if name is not None else QColor(225, 228, 234))
        p.setFont(self._font(22))
        txt = name if name is not None else tr('音轨')
        txt = p.fontMetrics().elidedText(txt, Qt.ElideRight, int(w - 112))
        p.drawText(QRectF(-w / 2 + 56, -h / 2, w - 112, h), Qt.AlignCenter, txt)

    def _layout_name(self, mode):
        return tr(LAYOUT_NAMES.get(mode, LAYOUT_NAMES['follow']))

    def _paint_switch(self, p, el, uf, hov, now):
        """乐谱切换条: 一条线 (两竖轴重合) → 竖轴向两侧拉开成整条; 文字转轮切换"""
        h = el['h']
        w = max(SW_ROD * 2, el['w'] * uf)
        body = QRectF(-w / 2, -h / 2, w, h)
        p.setBrush(QColor(98, 102, 110) if hov else QColor(88, 92, 100))
        p.setPen(QPen(QColor(255, 255, 255, 70), 1.6))
        p.drawRoundedRect(body, 4, 4)
        p.setBrush(QColor(70, 74, 82))
        for sx in (-1, 1):
            p.drawRect(QRectF(sx * (w / 2 - SW_ROD / 2) - SW_ROD / 2, -h / 2,
                              SW_ROD, h))
        if uf < 0.6:
            return
        p.setOpacity(p.opacity() * _clamp((uf - 0.6) / 0.4))
        p.setClipRect(QRectF(-w / 2 + SW_ROD, -h / 2, w - 2 * SW_ROD, h))
        p.setFont(self._font(24, True))
        p.setPen(QColor(240, 242, 246))
        cur = self._layout_name(getattr(self.ctrl.mw, 'strip_layout', 'follow'))
        q = 1.0 if self.t_sw is None else _ease_cubic(_clamp((now - self.t_sw) / 260.0))
        base_o = p.opacity()
        if q < 1.0 and self._sw_prev:
            p.setOpacity(base_o * (1.0 - q))            # 旧: 向上平移并淡出
            p.drawText(QRectF(-w / 2, -h / 2 - q * h * 0.6, w, h),
                       Qt.AlignCenter, self._sw_prev)
        p.setOpacity(base_o * q)                        # 新: 自下向上平移并淡入
        p.drawText(QRectF(-w / 2, -h / 2 + (1.0 - q) * h * 0.6, w, h),
                   Qt.AlignCenter, cur)

    # ---------- 时钟驱动 ----------
    def _run(self):
        if not self._timer.isActive():
            self._timer.start()

    def _busy(self, now):
        """任一动画未结束 → 不停表 (收回/转轮/点击反馈同样计入; 漏计收回 =
           展开久置后再点「选择」收回第一帧即停表, 卡住直到鼠标移动才跳到终态)"""
        if self.phase == 'closing':
            return True
        if now - self.t_open < 320.0:
            return True
        if self.t_col is not None:
            return True
        if self.t_exp is not None and now - self.t_exp < 1000.0:
            return True
        if self.t_sw is not None and now - self.t_sw < 280.0:
            return True
        return bool(self._flash)

    def _tick(self):
        now = self._now()
        if self.phase == 'closing' and now - self.t_close >= 220.0:
            self.phase = 'hidden'
            self._timer.stop()
            self.hide()
            self.roll.setFocus()
            return
        if self.t_col is not None and now - self.t_col >= 200.0:
            self.t_exp = self.t_col = None
        self._flash = {k: v for k, v in self._flash.items() if now - v < 220.0}
        if self.phase == 'hidden' or not self._busy(now):
            self._timer.stop()
        self.update()

    # ---------- 交互 ----------
    def mousePressEvent(self, ev):
        ev.accept()
        if ev.button() != Qt.LeftButton or self.phase != 'open':
            return
        el = self._hit(ev.position())
        if el is None:
            if not self.expanded:
                self.close_overlay()
            return
        kid, now = el['id'], self._now()
        if kid == 'select':
            if self.expanded:
                self.t_col = now
            else:
                self.t_exp, self.t_col = now, None
        elif kid == 'add':
            self.lane_idx = self.ctrl.add_score_row()
            self._flash[kid] = now
        elif kid == 'delete':
            self.lane_idx = self.ctrl.remove_score_row(self.lane_idx)
            self._flash[kid] = now
        elif kid == 'fold':
            self.close_overlay()
        elif kid == 'switch':
            mw = self.ctrl.mw
            cur = getattr(mw, 'strip_layout', 'follow')
            self._sw_prev = self._layout_name(cur)
            mw._set_strip_layout('bars' if cur == 'follow' else 'follow')
            self.t_sw = now
        else:
            self.ctrl.toggle_row_tid(self.lane_idx, el['tid'])
            self._flash[kid] = now
        self._run()
        self.update()

    def mouseDoubleClickEvent(self, ev):
        self.mousePressEvent(ev)            # 快速连点 = 连续切换, 不丢第二击

    def mouseMoveEvent(self, ev):
        ev.accept()
        el = self._hit(ev.position()) if self.phase == 'open' else None
        hid = el['id'] if el else None
        if hid != self._hover:
            self._hover = hid
            self.setCursor(Qt.PointingHandCursor if el else Qt.ArrowCursor)
            self.update()

    def mouseReleaseEvent(self, ev):
        ev.accept()

    def wheelEvent(self, ev):
        ev.accept()

    def contextMenuEvent(self, ev):
        ev.accept()

    def keyPressEvent(self, ev):
        if ev.key() == Qt.Key_Escape:
            self.close_overlay()
        elif ev.key() == Qt.Key_Space:
            self.ctrl.mw.toggle_play()
        ev.accept()
