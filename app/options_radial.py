# -*- coding: utf-8 -*-
"""选项径向菜单 (按设计图2): 全屏顶层浮层。
   打开: 黑色遮罩 200ms 0→50%, 遮罩下方一切不可交互 (播放保持当前状态);
   中心菱形【选项】0→1 缩放入场 (200ms); 五个菱形沿各自方向平移展开
   (南=收起 东南=歌曲 东北=播放 西南=声音 西北=乐谱), 同时弹性缩放
   0.6→1.12→0.94→1.0 (~450ms), 依次错开 40ms。
   关闭: 点【收起】/ 点遮罩空白 / Esc → 回收到中心并缩小, 遮罩淡出 (共 200ms)。
   子面板: 所点按钮高亮并移到对应侧作为根节点, 其余淡出; 树状连线逐段描边
   (每段 150ms), 子项沿连线依次滑入淡入 (间隔 30ms); 左上「← 返回」;
   Esc 先返回上一级再关闭菜单。坐标 = 设计稿实测 (选项中心为原点), 按屏缩放。"""
from PySide6.QtCore import Qt, QPointF, QRectF, QEvent
from PySide6.QtGui import QPainter, QColor, QPen, QPolygonF, QPainterPath
from PySide6.QtWidgets import QWidget, QApplication
import ui_motion as M
from radial_controls import font, Tween
from track_radial import TrackRadial

DESIGN_W, DESIGN_H = 2000.0, 940.0    # 设计包络 (子面板最远端; 缩放依据)
R = 54.0                              # 菱形半对角线
D = 57.0                              # 相邻菱形中心偏移 (共边拼接 + 3px 缝)
BUTTONS = (                           # (id, 文字, 槽位, 子面板根节点, 子面板侧)
    ('song', '歌曲', (D, D), (300.0, 230.0), 1),
    ('play', '播放', (D, -D), (300.0, -170.0), 1),
    ('audio', '声音', (-D, D), (-470.0, 230.0), -1),
    ('score', '乐谱', (-D, -D), (-470.0, 0.0), -1),
)
EDGE = 150.0                          # 根节点中心 → 子项近端
GAP_Y = 54.0                          # 子项行距
SPINE0, SPINE_STEP = 30.0, 19.0       # 竖干: 最外层项距根中心 / 每近一项外移
OPEN_MS = 120 + (len(BUTTONS) - 1) * M.STAGGER + M.ELASTIC


def diamond(c, r):
    return QPolygonF([QPointF(c.x(), c.y() - r), QPointF(c.x() + r, c.y()),
                      QPointF(c.x(), c.y() + r), QPointF(c.x() - r, c.y())])


def in_diamond(pos, c, r):
    return abs(pos.x() - c.x()) + abs(pos.y() - c.y()) <= r


class OptionsOverlay(QWidget):
    """phase: hidden → opening → radial ⇄ (enter → panel → leave) → closing → hidden"""
    def __init__(self, host):
        # 以悬浮乐谱为所有者窗口: 系统保证浮层恒在谱面之上 (同为置顶窗口时
        # 无所有者关系会被刚激活的谱面压到下面)
        super().__init__(host, Qt.Tool | Qt.FramelessWindowHint
                         | Qt.WindowStaysOnTopHint)
        self.host = host                     # ScoreFloat
        self.mw = host.mw
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.phase, self.t0 = 'hidden', 0.0
        self.sel = None                      # 当前子面板按钮 id
        self.panel = None                    # radial_panels.Panel
        self.hover = None
        self.k = 1.0
        self._hov = {}                       # 按钮悬停补间
        self._from_panel = False
        self.clock = M.Clock(self, self._tick, self._busy)
        self.tracks = TrackRadial(self)

    # ---- 坐标 ----
    def to_px(self, x, y):
        return (self.width() / 2.0 + x * self.k, self.height() / 2.0 + y * self.k)

    def pt(self, x, y):
        return QPointF(*self.to_px(x, y))

    def btn(self, bid):
        return next(b for b in BUTTONS if b[0] == bid)

    # ---- 生命周期 ----
    def open(self):
        M.reduced(refresh=True)
        scr = self.host.screen() or QApplication.primaryScreen()
        # 只盖工作区 (不含任务栏) 且四周内缩 1px: 不被壁纸引擎等识别为全屏/最大化程序
        self.setGeometry(scr.availableGeometry().adjusted(1, 1, -1, -1))
        self.k = max(0.55, min(1.15, self.width() / DESIGN_W, self.height() / DESIGN_H))
        self._drop_panel()
        self.tracks.phase = 'hidden'
        self.phase, self.t0, self.sel, self.hover = 'opening', self.clock.now(), None, None
        layer = getattr(self.host, 'layer', None)
        if layer is not None:
            layer.suspend(True)                  # 停工具栏悬停与气泡, 已弹出的立即隐藏
        self.show(); self.raise_(); self.activateWindow(); self.setFocus()
        self.clock.run(); self.update()

    def close_menu(self):
        if self.phase in ('hidden', 'closing'):
            return
        if self.panel is not None:
            self.panel.cancel_holds()
        self.tracks.phase = 'hidden'
        self._from_panel = self.sel is not None
        self.phase, self.t0 = 'closing', self.clock.now()
        self.clock.run()

    def _finish_close(self):
        self._drop_panel()
        self.sel = None
        self.phase = 'hidden'
        self.hide()
        self.host.activateWindow()

    def hideEvent(self, ev):
        layer = getattr(self.host, 'layer', None)
        if layer is not None:
            layer.suspend(False)
        super().hideEvent(ev)

    def close_now(self):
        self._drop_panel()
        self.phase = 'hidden'
        self.clock.timer.stop()
        self.hide()

    def enter(self, bid):
        """进入子面板: 按钮高亮并移到对应侧作为根节点, 其余淡出"""
        from radial_panels import build_panel
        self.sel = bid
        self.phase, self.t0 = 'enter', self.clock.now()
        self.panel = build_panel(bid, self)
        self._layout_items(self.clock.now())
        self.clock.run(); self.update()

    def leave(self):
        """← 返回: 子项与连线淡出, 根节点回到原槽位, 其余按钮淡入"""
        if self.phase not in ('enter', 'panel'):
            return
        if self.panel is not None:
            self.panel.cancel_holds()
        self.tracks.phase = 'hidden'
        self.phase, self.t0 = 'leave', self.clock.now()
        self.clock.run()

    def _drop_panel(self):
        if self.panel is not None:
            self.panel.destroy()
            self.panel = None

    def back(self):
        """Esc 层级: 长按中 → 取消; 音轨选择器 → 收起; 否则收回整个菜单
           (子面板不单独退回, 保持弹出直到菜单收回)"""
        now = self.clock.now()
        if self.panel is not None and self.panel.cancel_holds():
            return
        if self.tracks.phase == 'open':
            self.tracks.close(now); self.clock.run(); return
        self.close_menu()

    # ---- 时间线 ----
    ENTER_MOVE = 240.0                   # 根节点移位
    LEAVE_MS = 150.0 + 240.0

    def _busy(self, now):
        if self.phase in ('opening', 'closing', 'leave', 'enter'):
            return True
        return self.tracks.busy(now) or any(t.busy(now) for t in self._hov.values())

    def _open_ms(self):
        return M.REDUCED if M.reduced() else OPEN_MS

    def _enter_total(self):
        if M.reduced():
            return M.REDUCED + 10
        n = len(self.panel.items) if self.panel is not None else 1
        return self.ENTER_MOVE + (n - 1) * M.ITEM_STAGGER + 3 * M.TREE_SEG + M.PANEL + 20

    def _leave_ms(self):
        return M.REDUCED if M.reduced() else self.LEAVE_MS

    def _tick(self, now):
        dt = now - self.t0
        self.tracks.tick(now)
        ph = self.phase
        if ph == 'opening' and dt >= self._open_ms():
            self.phase = 'radial'
        elif ph == 'closing' and dt >= M.MASK + 10:
            self._finish_close(); return
        elif ph == 'enter' and dt >= self._enter_total():
            self.phase = 'panel'
        elif ph == 'leave' and dt >= self._leave_ms():
            self._drop_panel(); self.sel = None
            self.phase, self.t0 = 'radial', now
        if self.panel is not None:
            self._layout_items(now)
        self.update()

    def settle(self):
        """跳过动画到终态 (离屏测试)"""
        for _ in range(4):
            self.clock.settle(5000.0)

    # ---- 子面板几何 (设计坐标; 树干深度: 离中间项越远, 竖干越靠外) ----
    def root(self):
        b = self.btn(self.sel)
        return b[3], b[4]

    def _l_point(self, a, b, q):
        """沿 L 形 (先横后竖) 路径的进度点: 根节点移位轨迹 = 连线轨迹"""
        lh, lv = abs(b[0] - a[0]), abs(b[1] - a[1])
        d = (lh + lv) * M.clamp(q)
        if d <= lh:
            return (a[0] + (b[0] - a[0]) * (d / lh if lh else 1), a[1])
        return (b[0], a[1] + (b[1] - a[1]) * ((d - lh) / lv if lv else 1))

    def root_pos(self, now):
        """根节点当前设计坐标 (enter: 槽位→根; leave: 根→槽位)"""
        b = self.btn(self.sel)
        slot, rt = b[2], b[3]
        dt = now - self.t0
        if self.phase == 'enter':
            q = 1.0 if M.reduced() else M.ease_out(M.clamp(dt / self.ENTER_MOVE))
        elif self.phase == 'leave':
            q = 1.0 if M.reduced() else \
                1.0 - M.ease_out(M.clamp((dt - 150.0) / 240.0))
        else:
            q = 1.0
        return self._l_point(slot, rt, q)

    def item_geom(self, i):
        """第 i 项: (连线折点列表[设计坐标], 本项块近端 x, 中心 y)"""
        (rx, ry), side = self.root()
        n = len(self.panel.items)
        mid = (n - 1) / 2.0
        y = ry + (i - mid) * GAP_Y
        near = rx + side * EDGE
        dist = abs(i - mid)
        if dist < 0.25:
            pts = [(rx + side * R, ry), (near, y)]
        else:
            # 最外层项用最内竖干 (横线不与其它竖干相交), 紧邻中间项用最外竖干
            dmax = round(mid + 0.01)
            off = SPINE0 + SPINE_STEP * (dmax - round(dist + 0.01))
            sx = rx + side * off
            if off < R:                          # 竖干自根菱形斜边引出
                dy = R - off
                pts = [(sx, ry + (dy if y > ry else -dy)), (sx, y), (near, y)]
            else:                                # 越过顶点: 共用横干后再分叉
                pts = [(rx + side * R, ry), (sx, ry), (sx, y), (near, y)]
        return pts, near, y

    # ---- 子面板时序: 根节点移位 → 每项连线逐段描边 (每段 150ms, 项间 30ms) →
    #      该项沿连线滑入并淡入; 离开 = 150ms 同时淡出 ----
    def _line_start(self, i):
        return self.ENTER_MOVE + i * M.ITEM_STAGGER

    def line_prog(self, i, nseg, now):
        """→ (已画段数的连续进度 0..nseg, 透明度)"""
        dt = now - self.t0
        if self.phase in ('leave', 'closing'):
            return float(nseg), 1.0 - M.clamp(dt / (M.REDUCED if M.reduced() else 150.0))
        if self.phase == 'panel' or M.reduced():
            return float(nseg), (1.0 if self.phase == 'panel' else M.clamp(dt / M.REDUCED))
        return max(0.0, min(float(nseg), (dt - self._line_start(i)) / M.TREE_SEG)), 1.0

    def item_vis(self, i, nseg, now):
        """→ (透明度, 沿连线方向的滑入偏移 0..1)"""
        dt = now - self.t0
        if self.phase in ('leave', 'closing'):
            return 1.0 - M.clamp(dt / (M.REDUCED if M.reduced() else 150.0)), 0.0
        if self.phase == 'panel':
            return 1.0, 0.0
        if M.reduced():
            return M.clamp(dt / M.REDUCED), 0.0
        t = M.clamp((dt - self._line_start(i) - (nseg - 1) * M.TREE_SEG) / M.PANEL)
        return t, 1.0 - M.ease_out(t)

    def _layout_items(self, now):
        """子项控件逐帧定位 (近端对齐 + 滑入偏移) 与透明度; 音轨选择器打开时压暗"""
        if self.panel is None:
            return
        (rx, ry), side = self.root()
        k = self.k
        dimf = 0.35 if self.tracks.phase == 'open' else 1.0
        for i, it in enumerate(self.panel.items):
            pts, near, y = self.item_geom(i)
            o, slide = self.item_vis(i, len(pts) - 1, now)
            bw = it.block_w()
            nx, ny = self.to_px(near, y)
            x = nx if side > 0 else nx - bw
            x -= side * 24 * k * slide           # 自根节点一侧沿连线滑入
            it.place(x, ny - it.height() / 2.0, o * dimf)
            it.show_all(o > 0.01)

    @staticmethod
    def partial(pts, prog):
        """折线 [(x, y)…] 的前 prog 段 (连续值) → QPointF 列表 (坐标系不变)"""
        out = [QPointF(*pts[0])]
        for j in range(1, len(pts)):
            f = prog - (j - 1)
            if f <= 0:
                break
            a, b = pts[j - 1], pts[j]
            f = min(1.0, f)
            out.append(QPointF(a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f))
        return out

    # ---- 绘制 ----
    def _mask(self, now):
        dt = now - self.t0
        if self.phase == 'opening':
            return M.ease_out(M.clamp(dt / M.MASK))
        if self.phase == 'closing':
            return 1.0 - M.ease_in(M.clamp(dt / M.dur(M.MASK)))
        return 1.0

    def _btn_state(self, b, idx, now):
        """径向按钮 (x, y, scale, opacity) 设计坐标 / None"""
        dt = now - self.t0
        (sx, sy), ph = b[2], self.phase
        if ph == 'opening':
            if M.reduced():
                return sx, sy, 1.0, M.clamp(dt / M.REDUCED)
            p = M.clamp((dt - 120 - idx * M.STAGGER) / M.ELASTIC)
            if p <= 0:
                return None
            e = M.ease_out(min(1.0, p / 0.55))   # 平移: 自中心沿各自方向
            return sx * e, sy * e, M.radial_pop(p), min(1.0, p * 3)
        if ph == 'closing':
            if self._from_panel:
                return None
            f = 1.0 - M.ease_in(M.clamp(dt / (M.REDUCED if M.reduced() else 140.0)))
            if M.reduced():
                return sx, sy, 1.0, f
            return sx * f, sy * f, 0.6 + 0.4 * f, f
        if ph in ('enter', 'panel', 'leave') and b[0] != self.sel:
            if ph == 'leave':
                o = M.clamp((dt - 150.0) / 240.0) if not M.reduced() else M.clamp(dt / M.REDUCED)
            elif ph == 'enter':
                o = 1.0 - M.clamp(dt / 160.0)
            else:
                o = 0.0
            return (sx, sy, 1.0, o) if o > 0.01 else None
        if ph in ('enter', 'panel', 'leave') and b[0] == self.sel:
            x, y = self.root_pos(now)
            return x, y, 1.0, 1.0
        return sx, sy, 1.0, 1.0

    def _center_state(self, now):
        dt, ph = now - self.t0, self.phase
        if ph == 'opening':
            q = M.clamp(dt / (M.REDUCED if M.reduced() else M.CENTER_IN))
            return (1.0 if M.reduced() else M.ease_out(q)), min(1.0, q * 2)
        if ph == 'closing':
            if self._from_panel:
                return None
            f = 1.0 - M.ease_in(M.clamp((dt - 60.0) / 140.0))
            return (1.0 if M.reduced() else 0.5 + 0.5 * f), f
        if ph == 'enter':
            return 1.0, 1.0 - M.clamp(dt / 160.0)
        if ph == 'leave':
            return 1.0, M.clamp((dt - 150.0) / 240.0)
        if ph == 'panel':
            return None
        return 1.0, 1.0

    def paintEvent(self, ev):
        now = self.clock.now()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        m = self._mask(now)
        p.fillRect(self.rect(), QColor(0, 0, 0, int(255 * 0.5 * m)))
        # 子面板: 根节点移位轨迹 + 树状连线 + 返回
        if self.sel is not None and self.panel is not None:
            fade = m if self.phase == 'closing' else 1.0
            p.setOpacity(fade)
            self._paint_tree(p, now)
            p.setOpacity(1.0)
        cs = self._center_state(now)
        if cs is not None and cs[1] > 0.01:
            self._paint_dia(p, self.pt(0, 0), R * cs[0], '选项', cs[1], 'center')
        for idx, b in enumerate(BUTTONS):
            st = self._btn_state(b, idx, now)
            if st is None and not (self.phase == 'closing' and b[0] == self.sel):
                continue
            if st is None:                       # 自子面板关闭: 根节点随遮罩淡出
                x, y = b[3]
                st = (x, y, 1.0, m)
            if st[3] <= 0.01:
                continue
            self._paint_dia(p, self.pt(st[0], st[1]), R * st[2], b[1], st[3], b[0],
                            selected=b[0] == self.sel)
        self.tracks.paint(p, now, under=lambda: self._paint_track_link(p, now))
        p.end()

    def _paint_dia(self, p, c, r, text, o, bid, selected=False):
        """线框菱形: 白底黑描边; 悬停加深 5%; 选中 (根节点) = 主色描边 + 浅蓝底"""
        h = self._hov.get(bid).value(self.clock.now()) if bid in self._hov else 0.0
        rr = r * self.k
        p.save()
        p.setOpacity(o)
        if not M.reduced() and h > 0 and not selected:
            c = QPointF(c.x(), c.y() - h)        # 悬停上移 1px
        if selected:
            p.setBrush(QColor('#eaf2ff'))
            p.setPen(QPen(QColor(M.BLUE), 2.2))
        else:
            p.setBrush(QColor(M.PAPER).darker(int(100 + 5 * h)))
            p.setPen(QPen(QColor(M.INK), 1.6))
        p.drawPolygon(diamond(c, rr))
        p.setPen(QColor(M.BLUE) if selected else QColor(M.INK))
        p.setFont(font(max(9, 17 * self.k * (r / R) if r > 0 else 9), True))
        p.drawText(QRectF(c.x() - rr, c.y() - rr, 2 * rr, 2 * rr), Qt.AlignCenter, text)
        p.restore()

    def _line_pen(self, o=1.0):
        """连线: 遮罩上的白色细线 (线宽与菱形描边一致)"""
        pen = QPen(QColor(255, 255, 255, int(235 * o)), 1.6)
        pen.setCapStyle(Qt.FlatCap); pen.setJoinStyle(Qt.MiterJoin)
        return pen

    def _arrow(self, p, tip, direction, o):
        s = 7 * self.k
        p.setPen(Qt.NoPen); p.setBrush(QColor(255, 255, 255, int(235 * o)))
        p.drawPolygon(QPolygonF([tip, QPointF(tip.x() - direction * s, tip.y() - s * 0.6),
                                 QPointF(tip.x() - direction * s, tip.y() + s * 0.6)]))

    def _paint_tree(self, p, now):
        b = self.btn(self.sel)
        side = b[4]
        dt = now - self.t0
        # 根节点移位轨迹 (先横后竖, 与根节点同步描出; 抵达后淡出)
        if self.phase in ('enter', 'leave') and not M.reduced():
            if self.phase == 'enter':
                q = M.ease_out(M.clamp(dt / self.ENTER_MOVE))
                o = 1.0 - M.clamp((dt - self.ENTER_MOVE) / 300.0)
            else:
                q = 1.0 - M.ease_out(M.clamp((dt - 150.0) / 240.0))
                o = q
            if o > 0.01 and q > 0:
                a = b[2]
                pts = [a, (b[3][0], a[1]), b[3]]
                lh = abs(b[3][0] - a[0]); lv = abs(b[3][1] - a[1])
                prog = (lh + lv) * q
                seg = prog / lh if prog <= lh else 1 + (prog - lh) / max(1e-6, lv)
                p.setPen(self._line_pen(o))
                p.drawPolyline([self.pt(q2.x(), q2.y()) for q2 in self.partial(pts, seg)])
        # 树状连线
        for i, it in enumerate(self.panel.items):
            pts, near, y = self.item_geom(i)
            nseg = len(pts) - 1
            prog, o = self.line_prog(i, nseg, now)
            if prog <= 0 or o <= 0.01:
                continue
            path = [self.pt(q.x(), q.y()) for q in self.partial(pts, prog)]
            p.setPen(self._line_pen(o))
            p.drawPolyline(path)
            if prog >= nseg - 0.01:
                self._arrow(p, path[-1], side, o)

    def open_tracks(self, is_on=None, toggle=None):
        """「映射范围 · 音轨」→ 音轨径向选择器: 摆在播放子面板正下方 (不压子项),
           屏幕放不下时上移贴底; 勾选经 is_on/toggle 写子面板草稿"""
        from track_radial import HALF_H
        bottom = max(it.y() + it.height() for it in self.panel.items)
        cy = (bottom - self.height() / 2.0) / self.k + 24.0 + HALF_H
        cy = min(cy, self.height() / 2.0 / self.k - HALF_H - 8.0)
        self.tracks.open(self.clock.now(), (0.0, cy), is_on, toggle)
        self.clock.run(); self.update()

    def _paint_track_link(self, p, now):
        """「映射范围」→ 音轨选择器【收起】: 经子面板右侧走线槽下行, 在选择器
           上方的空档横穿, 再竖直落到【收起】顶点 (不穿越子项与音轨条)"""
        if self.tracks.phase != 'open' or self.panel is None:
            return
        it = self.panel.find('scope')
        if it is None:
            return
        from track_radial import HALF_H
        q = M.clamp((now - self.tracks.t_open) / 300.0)
        k = self.k
        a = QPointF(it.x() + it.block_w(), it.y() + it.height() / 2.0)
        gx = max(i.x() + i.block_w() for i in self.panel.items) + 16 * k   # 右侧走线槽
        c = self.tracks.center_px()
        top = QPointF(c.x(), c.y() - 66 * k * 0.56)
        ly = c.y() - (HALF_H + 10.0) * k               # 选择器外包络上方
        pts = [(a.x(), a.y()), (gx, a.y()), (gx, ly), (top.x(), ly), (top.x(), top.y())]
        p.setPen(self._line_pen(0.9))
        p.drawPolyline(self.partial(pts, 4.0 * q))

    # ---- 输入 (遮罩吞掉一切, 下方不可交互) ----
    def _hit_btn(self, pos):
        now = self.clock.now()
        if self.phase == 'radial':
            for idx, b in enumerate(BUTTONS):
                if in_diamond(pos, self.pt(*b[2]), R * self.k):
                    return b[0]
            if in_diamond(pos, self.pt(0, 0), R * self.k):
                return 'center'
        elif self.phase == 'panel':
            if self.tracks.phase == 'open':
                return None
            x, y = self.root_pos(now)
            if in_diamond(pos, self.pt(x, y), R * self.k):
                return 'root'
        return None

    def mousePressEvent(self, ev):
        ev.accept()
        if ev.button() != Qt.LeftButton:
            return
        pos = ev.position()
        now = self.clock.now()
        if self.tracks.phase == 'open':
            if not self.tracks.press(pos):
                self.tracks.close(now)           # 选择器外空白 = 收起选择器
            self.clock.run(); self.update(); return
        hit = self._hit_btn(pos)
        if self.phase == 'radial':
            if hit == 'center' or hit is None:
                self.close_menu()
            else:
                self.enter(hit)
        elif self.phase == 'panel':
            if hit == 'root':
                self.leave()                     # 根节点 → 回到径向菜单换子面板
            elif hit is None:
                self.close_menu()                # 子面板保持弹出, 直到整个菜单收回

    def mouseDoubleClickEvent(self, ev):
        ev.accept()

    def mouseMoveEvent(self, ev):
        ev.accept()
        pos = ev.position()
        if self.tracks.phase == 'open':
            if self.tracks.move(pos):
                self.update()
            hid = self.tracks.hover
        else:
            hid = self._hit_btn(pos)
            if hid != self.hover:
                now = self.clock.now()
                if self.hover in self._hov:
                    self._hov[self.hover].to(0, now, M.MICRO)
                if hid is not None:
                    self._hov.setdefault(hid, Tween()).to(1, now, M.MICRO)
                self.hover = hid
                self.clock.run()
        self.setCursor(Qt.PointingHandCursor if hid else Qt.ArrowCursor)

    def wheelEvent(self, ev):
        ev.accept()

    def contextMenuEvent(self, ev):
        ev.accept()

    def keyPressEvent(self, ev):
        if ev.key() == Qt.Key_Escape:
            self.back()
        ev.accept()

    def changeEvent(self, ev):
        if ev.type() == QEvent.ActivationChange and not self.isActiveWindow() \
                and self.panel is not None:
            self.panel.cancel_holds()            # 窗口失焦: 取消长按
        super().changeEvent(ev)
