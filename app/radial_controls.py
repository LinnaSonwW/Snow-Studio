# -*- coding: utf-8 -*-
"""选项径向菜单子面板的线框控件 (白底黑描边 · 主色蓝, 尺寸按 k 缩放):
   LButton 按钮 (悬停加深5%+上移1px / 按下0.95 / 选中蓝 / 禁用40% / 2px 焦点环;
   文字切换 = 旧值向上弹出淡出、新值自下向上淡入) · Cycle 循环切换 · Dropdown 下拉 ·
   Segmented 分段选择 (选中底 160ms 滑动) · LSlider 滑条 (实时数值 + 数字框,
   双击恢复默认) · HoldConfirm 长按确认 · KeyCells 按键格 · Bubble 提示气泡 ·
   PanelItem 标签+控件外框。动画全部走 ui_motion 单时钟。"""
import math
from PySide6.QtCore import Qt, Signal, QRectF, QPointF, QPoint, QTimer, QEvent, \
    QVariantAnimation
from PySide6.QtGui import QPainter, QColor, QPen, QFont, QPainterPath, QFontMetrics
from PySide6.QtWidgets import QWidget, QLineEdit, QMenu, QGraphicsOpacityEffect
import ui_motion as M

INSET = 3.5          # 控件外缘留白 (上移 1px + 焦点环)
BOX_QSS = ('QLineEdit{background:#ffffff;border:1px solid #1a1a1a;border-radius:4px;'
           'color:#1a1a1a;font-family:"Segoe UI","Microsoft YaHei UI",Arial;'
           'font-size:%dpx;padding:0 2px;}'
           'QLineEdit:focus{border:2px solid #2f7cf6;}'
           'QLineEdit:disabled{color:#a0a0a0;border-color:#b8b8b8;}')
MENU_QSS = ('QMenu{background:#ffffff;border:1px solid #1a1a1a;border-radius:6px;'
            'padding:4px;}QMenu::item{color:#1a1a1a;padding:5px 22px 5px 14px;'
            'border-radius:4px;font-size:%dpx;}'
            'QMenu::item:selected{background:#2f7cf6;color:#ffffff;}')


def font(px, bold=False):
    f = QFont()
    f.setFamilies(['Segoe UI', 'Microsoft YaHei UI', 'Arial'])   # 拉丁字母 / 中文回退
    f.setPixelSize(max(8, int(round(px))))
    f.setBold(bold)
    return f


def mix(a, b, t):
    a, b = QColor(a), QColor(b)
    return QColor(int(a.red() + (b.red() - a.red()) * t),
                  int(a.green() + (b.green() - a.green()) * t),
                  int(a.blue() + (b.blue() - a.blue()) * t),
                  int(a.alpha() + (b.alpha() - a.alpha()) * t))


class Tween:
    """单值补间 (宿主时钟驱动): to() 自当前值起跑; value(now); busy(now)"""
    def __init__(self, v=0.0):
        self.a = self.b = float(v)
        self.t0, self.ms, self.ease = -1e9, 1.0, M.ease_out

    def to(self, v, now, ms, ease=M.ease_out):
        self.a = self.value(now)
        self.b, self.t0, self.ms, self.ease = float(v), now, max(1.0, ms), ease

    def jump(self, v):
        self.a = self.b = float(v)

    def value(self, now):
        return self.a + (self.b - self.a) * self.ease(M.clamp((now - self.t0) / self.ms))

    def busy(self, now):
        return self.a != self.b and now - self.t0 < self.ms
class _Anim(QWidget):
    """控件基类: 悬停/按下补间 + 单时钟 + 焦点; 子类实现 draw(p, now)"""
    def __init__(self, parent, k):
        super().__init__(parent)
        self.k = float(k)
        self.hov, self.prs = Tween(), Tween()
        self.focused = False
        self.clock = M.Clock(self, lambda _n: self.update(), self._busy)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setCursor(Qt.PointingHandCursor)

    def _busy(self, now):
        return self.hov.busy(now) or self.prs.busy(now) or self.anim_busy(now)

    def anim_busy(self, now):
        return False

    def kick(self):
        self.clock.run(); self.update()

    def enterEvent(self, ev):
        self.hov.to(1, self.clock.now(), M.MICRO); self.kick()

    def leaveEvent(self, ev):
        self.hov.to(0, self.clock.now(), M.MICRO); self.kick()

    def focusInEvent(self, ev):
        self.focused = ev.reason() in (Qt.TabFocusReason, Qt.BacktabFocusReason)
        self.update(); super().focusInEvent(ev)

    def focusOutEvent(self, ev):
        self.focused = False; self.update(); super().focusOutEvent(ev)

    def changeEvent(self, ev):
        if ev.type() == QEvent.EnabledChange:
            self.setCursor(Qt.PointingHandCursor if self.isEnabled() else Qt.ArrowCursor)
            self.update()
        super().changeEvent(ev)

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        if not self.isEnabled():
            p.setOpacity(0.4)
        self.draw(p, self.clock.now())
        p.end()

    def frame(self, p, now, selected=False, fill=None):
        """统一线框外壳: 悬停加深5%+上移1px · 按下缩放0.95 · 选中蓝描边 · 焦点环。
           减少动态效果 = 只保留颜色变化。返回内容区 (已施加变换)"""
        h, pr = self.hov.value(now), self.prs.value(now)
        r = QRectF(self.rect()).adjusted(INSET, INSET, -INSET, -INSET)
        if not M.reduced() and self.isEnabled():
            c = r.center()
            s = 1.0 - 0.05 * pr
            p.translate(c.x(), c.y() - 1.0 * h)
            p.scale(s, s)
            p.translate(-c.x(), -c.y())
        rad = 5.0 * self.k
        base = QColor(fill) if fill is not None else QColor(M.PAPER)
        p.setBrush(base.darker(int(100 + 5 * h)) if self.isEnabled() else base)
        p.setPen(QPen(QColor(M.BLUE) if selected else QColor(M.INK), 1.3))
        p.drawRoundedRect(r, rad, rad)
        if self.focused:
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(QColor(M.BLUE), 2.0))
            p.drawRoundedRect(r.adjusted(-2.5, -2.5, 2.5, 2.5), rad + 2, rad + 2)
        return r

    def flip_text(self, p, r, now, old, new, t0, color=M.INK, align=Qt.AlignCenter):
        """文字上下翻转: 旧值向上弹出淡出, 新值自下向上淡入 (减少动态 = 交叉淡入淡出)"""
        q = M.ease_out(M.clamp((now - t0) / M.dur(M.FLIP)))
        p.save()
        p.setClipRect(r)
        p.setPen(QColor(color))
        o0 = p.opacity()
        dy = 0.0 if M.reduced() else r.height() * 0.7
        if q < 1.0 and old:
            p.setOpacity(o0 * (1 - q))
            p.drawText(r.translated(0, -dy * q), align, old)
        p.setOpacity(o0 * q)
        p.drawText(r.translated(0, dy * (1 - q)), align, new)
        p.restore()
        return q < 1.0


class LButton(_Anim):
    """线框按钮: set_text 自动走翻转过渡; selected = 主色描边"""
    clicked = Signal()

    def __init__(self, parent, k, text='', px=13):
        super().__init__(parent, k)
        self._text, self._old, self._t_flip = text, '', -1e9
        self.selected = False
        self.px = px
        self.warn = False                    # 右侧警告图标 (设备断开)

    def text(self):
        return self._text

    def set_text(self, t, flip=True):
        if t == self._text:
            return
        self._old, self._text = self._text, t
        self._t_flip = self.clock.now() if flip else -1e9
        self.kick()

    def anim_busy(self, now):
        return now - self._t_flip < M.dur(M.FLIP) + 20

    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            self.prs.to(1, self.clock.now(), M.MICRO * 0.6); self.kick()
        ev.accept()

    def mouseReleaseEvent(self, ev):
        if ev.button() != Qt.LeftButton:
            return
        self.prs.to(0, self.clock.now(), M.MICRO); self.kick()
        if self.rect().contains(ev.position().toPoint()):
            self.clicked.emit()

    def mouseDoubleClickEvent(self, ev):
        self.mousePressEvent(ev)             # 快速连点 = 连续切换, 不丢第二击

    def keyPressEvent(self, ev):
        if ev.key() in (Qt.Key_Space, Qt.Key_Return, Qt.Key_Enter):
            self.clicked.emit(); ev.accept()
        else:
            super().keyPressEvent(ev)

    def draw(self, p, now):
        r = self.frame(p, now, self.selected)
        p.setFont(font(self.px * self.k))
        tr_ = r.adjusted(6 * self.k, 0, -(18 if self.warn else 6) * self.k, 0)
        self.flip_text(p, tr_, now, self._old, self._text, self._t_flip)
        if self.warn:
            self._draw_warn(p, QPointF(r.right() - 10 * self.k, r.center().y()))

    def _draw_warn(self, p, c):
        s = 6.0 * self.k
        p.setPen(QPen(QColor(M.RED), 1.4))
        p.setBrush(QColor(255, 236, 230))
        p.drawPolygon([QPointF(c.x(), c.y() - s), QPointF(c.x() + s, c.y() + s * 0.8),
                       QPointF(c.x() - s, c.y() + s * 0.8)])
        p.setFont(font(9 * self.k, True))
        p.drawText(QRectF(c.x() - s, c.y() - s * 0.6, 2 * s, 1.6 * s), Qt.AlignCenter, '!')


class Cycle(LButton):
    """循环切换: 左键下一项 / 右键·滚轮下 = 上一项; options=[(值, 文字)]"""
    changed = Signal(object)

    def __init__(self, parent, k, options, value, px=13):
        super().__init__(parent, k, '', px)
        self.options = list(options)
        self.value = value
        self._text = self._label(value)
        self.clicked.connect(lambda: self.step(1))

    def _label(self, v):
        return next((t for o, t in self.options if o == v), str(v))

    def set_value(self, v, flip=True):
        self.value = v
        self.set_text(self._label(v), flip)

    def step(self, d):
        vals = [o for o, _ in self.options]
        i = vals.index(self.value) if self.value in vals else -1
        self.set_value(vals[(i + d) % len(vals)])
        self.changed.emit(self.value)

    def contextMenuEvent(self, ev):
        self.step(-1); ev.accept()

    def wheelEvent(self, ev):
        self.step(-1 if ev.angleDelta().y() > 0 else 1); ev.accept()


class Dropdown(LButton):
    """下拉选择: 点击弹出浅色菜单, 选中后文字翻转为新值; options=[(值, 文字)]"""
    picked = Signal(object)

    def __init__(self, parent, k, options, value, px=13):
        super().__init__(parent, k, '', px)
        self.options = list(options)
        self.value = value
        self._text = self._label(value)
        self.clicked.connect(self.popup)

    def _label(self, v):
        return next((t for o, t in self.options if o == v), str(v))

    def set_value(self, v, flip=True):
        self.value = v
        self.set_text(self._label(v), flip)

    def popup(self):
        m = QMenu(self)
        m.setStyleSheet(MENU_QSS % int(13 * self.k))
        for o, t in self.options:
            a = m.addAction(('✓ ' if o == self.value else '   ') + t)
            a.setData(o)
        a = m.exec(self.mapToGlobal(QPoint(0, self.height())))
        if a is not None and a.data() != self.value:
            self.set_value(a.data())
            self.picked.emit(self.value)

    def draw(self, p, now):
        super().draw(p, now)
        r = QRectF(self.rect()).adjusted(INSET, INSET, -INSET, -INSET)
        x, y, s = r.right() - (24 if self.warn else 10) * self.k, r.center().y(), 3 * self.k
        p.setPen(QPen(QColor(M.INK), 1.3))
        p.drawPolyline([QPointF(x - s, y - s / 2), QPointF(x, y + s / 2),
                        QPointF(x + s, y - s / 2)])


def _tail_ease(p):
    """胶囊后沿: 慢一拍起步 (前 25% 停留 = 拉伸), 再带轻微回弹落定"""
    return M.ease_back(M.clamp((p - 0.25) / 0.75))


class Segmented(_Anim):
    """分段选择 (单选): 选中项主色填充, 切换时选中底 160ms 平滑滑到新位置"""
    changed = Signal(object)

    def __init__(self, parent, k, options, value, px=13):
        super().__init__(parent, k)
        self.options = list(options)
        self.px = px
        self.index = max(0, [o for o, _ in options].index(value)
                         if value in [o for o, _ in options] else 0)
        # 弹性胶囊: 选中底左右两缘各自补间 —— 前沿先到 (ease-out), 后沿慢一拍
        # 带轻微回弹跟上 (spring), 移动中底色横向拉伸 (不做上下翻转)
        self.lo, self.hi = Tween(self.index), Tween(self.index + 1)
        self.hover_i = -1

    def value(self):
        return self.options[self.index][0]

    def set_value(self, v):
        vals = [o for o, _ in self.options]
        if v in vals and vals.index(v) != self.index:
            now = self.clock.now()
            right = vals.index(v) > self.index
            self.index = vals.index(v)
            if M.reduced():
                self.lo.jump(self.index); self.hi.jump(self.index + 1)
            else:                                # 朝移动方向的一缘 = 前沿
                fast, slow = (M.SEG_SLIDE, M.ease_out), (M.SEG_SLIDE * 2.2, _tail_ease)
                lo_s, hi_s = (slow, fast) if right else (fast, slow)
                self.lo.to(self.index, now, *lo_s)
                self.hi.to(self.index + 1, now, *hi_s)
            self.kick()

    def anim_busy(self, now):
        return self.lo.busy(now) or self.hi.busy(now)

    def _sel_span(self, now):
        """胶囊当前 [左缘, 右缘] (格单位); 回弹不压缩到 0.6 格以下"""
        a, b = self.lo.value(now), self.hi.value(now)
        if b - a < 0.6:
            m = (a + b) / 2
            a, b = m - 0.3, m + 0.3
        return a, b

    def _cell(self, i):
        r = QRectF(self.rect()).adjusted(INSET, INSET, -INSET, -INSET)
        w = r.width() / len(self.options)
        return QRectF(r.x() + w * i, r.y(), w, r.height())

    def _at(self, x):
        for i in range(len(self.options)):
            c = self._cell(i)
            if c.left() <= x < c.right():
                return i
        return -1

    def mouseMoveEvent(self, ev):
        i = self._at(ev.position().x())
        if i != self.hover_i:
            self.hover_i = i; self.update()

    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            i = self._at(ev.position().x())
            if i >= 0 and i != self.index:
                self.set_value(self.options[i][0])
                self.changed.emit(self.value())
        ev.accept()

    def keyPressEvent(self, ev):
        d = {Qt.Key_Left: -1, Qt.Key_Right: 1}.get(ev.key())
        if d is None:
            return super().keyPressEvent(ev)
        i = max(0, min(len(self.options) - 1, self.index + d))
        if i != self.index:
            self.set_value(self.options[i][0]); self.changed.emit(self.value())

    def draw(self, p, now):
        r = QRectF(self.rect()).adjusted(INSET, INSET, -INSET, -INSET)
        rad = 5.0 * self.k
        clip = QPainterPath(); clip.addRoundedRect(r, rad, rad)
        p.setBrush(QColor(M.PAPER)); p.setPen(Qt.NoPen)
        p.drawPath(clip)
        p.save(); p.setClipPath(clip)
        if 0 <= self.hover_i != self.index:
            p.fillRect(self._cell(self.hover_i), QColor(0, 0, 0, 13))
        w = r.width() / len(self.options)
        a, b = self._sel_span(now)
        sel = QRectF(r.x() + w * a, r.y(), w * (b - a), r.height())
        cap = QPainterPath(); cap.addRoundedRect(sel, rad, rad)
        p.fillPath(cap, QColor(M.BLUE))
        p.setPen(QPen(QColor(M.INK), 1.0))
        for i in range(1, len(self.options)):
            x = r.x() + w * i
            p.drawLine(QPointF(x, r.top()), QPointF(x, r.bottom()))
        p.setFont(font(self.px * self.k))
        o0 = p.opacity()
        for color, clip in ((M.INK, None), ('#ffffff', sel)):
            if clip is not None:
                p.setClipRect(clip, Qt.IntersectClip)  # 选中底覆盖处文字反白
            for i, (_, t) in enumerate(self.options):
                p.setPen(QColor(color))
                p.drawText(self._cell(i), Qt.AlignCenter, t)
        p.setOpacity(o0)
        p.restore()
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(M.INK), 1.3)); p.drawRoundedRect(r, rad, rad)
        if self.focused:
            p.setPen(QPen(QColor(M.BLUE), 2.0))
            p.drawRoundedRect(r.adjusted(-2.5, -2.5, 2.5, 2.5), rad + 2, rad + 2)


class LSlider(_Anim):
    """滑条: 蓝色填充 + 实时数值 (经过填充区反白) + 右侧数字框 (可直接输入);
       双击滑条恢复默认; 滚轮步进。valueChanged 拖动中连续发出"""
    valueChanged = Signal(float)

    def __init__(self, parent, k, lo, hi, value, default, fmt='{:.0f}%', step=1.0,
                 box_w=46):
        super().__init__(parent, k)
        self.lo, self.hi, self.default, self.fmt, self.step = lo, hi, default, fmt, step
        self.v = float(value)
        self._drag = False
        self.box = QLineEdit(self)
        self.box.setAlignment(Qt.AlignCenter)
        self.box.setStyleSheet(BOX_QSS % int(12 * k))
        self.box.editingFinished.connect(self._from_box)
        self.box_w = box_w
        self._sync_box()

    def resizeEvent(self, ev):
        bw = int(self.box_w * self.k)
        self.box.setGeometry(self.width() - bw - int(INSET), int(INSET),
                             bw, self.height() - int(2 * INSET))

    def _track(self):
        r = QRectF(self.rect()).adjusted(INSET, INSET, -INSET, -INSET)
        return r.adjusted(0, 0, -(self.box_w + 6) * self.k, 0)

    def text(self):
        return self.fmt.format(self.v)

    def set_value(self, v, emit=False):
        v = max(self.lo, min(self.hi, round(float(v) / self.step) * self.step))
        if v == self.v:
            return
        self.v = v
        self._sync_box(); self.update()
        if emit:
            self.valueChanged.emit(v)

    def _sync_box(self):
        if not self.box.hasFocus():
            self.box.setText(('%g' % self.v))

    def configure(self, lo, hi, value, default, fmt, step):
        """改量程/单位 (同一滑条切换不同设置, 例: 谱面长度 ⇄ 谱面高度)"""
        self.lo, self.hi, self.default, self.fmt, self.step = lo, hi, default, fmt, step
        self.v = max(lo, min(hi, float(value)))
        self._sync_box(); self.update()

    def _from_box(self):
        try:
            v = float(self.box.text().replace('%', '').strip())
        except ValueError:
            v = self.v
        self.set_value(v, emit=True); self.box.setText('%g' % self.v)

    def _from_x(self, x):
        t = self._track()
        q = M.clamp((x - t.left()) / max(1.0, t.width()))
        self.set_value(self.lo + (self.hi - self.lo) * q, emit=True)

    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton and self._track().contains(ev.position()):
            self._drag = True
            self.prs.to(1, self.clock.now(), M.MICRO); self.kick()
            self._from_x(ev.position().x())
        ev.accept()

    def mouseMoveEvent(self, ev):
        if self._drag:
            self._from_x(ev.position().x())

    def mouseReleaseEvent(self, ev):
        self._drag = False
        self.prs.to(0, self.clock.now(), M.MICRO); self.kick()

    def mouseDoubleClickEvent(self, ev):
        if self._track().contains(ev.position()):
            self.set_value(self.default, emit=True)

    def wheelEvent(self, ev):
        self.set_value(self.v + (self.step if ev.angleDelta().y() > 0 else -self.step),
                       emit=True)
        ev.accept()

    def keyPressEvent(self, ev):
        d = {Qt.Key_Left: -1, Qt.Key_Down: -1, Qt.Key_Right: 1, Qt.Key_Up: 1}.get(ev.key())
        if d is None:
            return super().keyPressEvent(ev)
        self.set_value(self.v + d * self.step, emit=True)

    def draw(self, p, now):
        t = self._track()
        rad = 5.0 * self.k
        h = self.hov.value(now)
        clip = QPainterPath(); clip.addRoundedRect(t, rad, rad)
        p.setPen(Qt.NoPen); p.setBrush(QColor(M.PAPER).darker(int(100 + 5 * h)))
        p.drawPath(clip)
        q = (self.v - self.lo) / max(1e-9, self.hi - self.lo)
        fill = QRectF(t.x(), t.y(), t.width() * q, t.height())
        p.save(); p.setClipPath(clip)
        p.fillRect(fill, QColor(M.BLUE))
        p.setFont(font(12 * self.k))
        p.setPen(QColor(M.INK)); p.drawText(t, Qt.AlignCenter, self.text())
        p.setClipRect(fill, Qt.IntersectClip)
        p.setPen(QColor('#ffffff')); p.drawText(t, Qt.AlignCenter, self.text())
        p.restore()
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(M.BLUE) if self._drag else QColor(M.INK), 1.3))
        p.drawRoundedRect(t, rad, rad)
        if self.focused:
            p.setPen(QPen(QColor(M.BLUE), 2.0))
            p.drawRoundedRect(t.adjusted(-2.5, -2.5, 2.5, 2.5), rad + 2, rad + 2)


class HoldConfirm(_Anim):
    """长按确认 (每个子面板共用一个)。未修改: 「确认」40%, 点击无动作;
       已修改: 「长按确认」+ 描边呼吸 2 次; 按住 800ms 填充 (文字随填充反白,
       600ms 起 ±1px 震动) → commit() 返回 True = 弹性 0.96→1.08→1.0 + 蓝转绿 +
       ✓ 描边 + 绿色光环外扩 8px, 1s 后淡回禁用; False = 红填 + 抖动 + 「失败，重试」。
       提前松开/移出/Esc/失焦 = 2 倍速回退 (≤200ms); 不足 150ms = 「按住以确认」气泡"""
    RING = 10                                # 光环外扩留白 (设计 px)

    def __init__(self, parent, k, commit, dirty_fn=None):
        super().__init__(parent, k)
        self.commit = commit
        self.dirty_fn = dirty_fn                 # 「已生效」结束时复核是否仍有待确认修改
        self.dirty = False
        self.state, self.t0 = 'idle', -1e9   # idle|hold|back|ok|fail
        self.t_arm = -1e9
        self.f0 = self.s0 = 0.0
        self.tip = None
        self.clock._tick = self.step
        self.setAttribute(Qt.WA_NoMousePropagation)

    def body(self):
        m = self.RING * self.k
        return QRectF(self.rect()).adjusted(m, m, -m, -m)

    def set_dirty(self, d):
        d = bool(d)
        if d and not self.dirty:
            self.t_arm = self.clock.now()
        self.dirty = d
        if not d and self.state in ('hold', 'back', 'tap', 'fail'):
            self.state = 'idle'
        self.kick()

    def holding(self):
        return self.state == 'hold'

    def _fill(self, now):
        dt = now - self.t0
        if self.state == 'hold':
            return M.ease_hold(dt / M.HOLD)
        if self.state == 'back':
            return self.f0 * (1 - M.ease_out(M.clamp(dt / self._back_ms())))
        if self.state == 'tap':                 # 误点引导: 闪到 ~10% 后回退
            return 0.1 * M.keyframes(dt / 320.0, [(0, 0), (0.4, 1), (1, 0)])
        if self.state in ('ok', 'fail'):
            return 1.0
        return 0.0

    def _back_ms(self):
        return min(200.0, max(60.0, self.f0 * M.HOLD / 2))

    def _scale(self, now):
        dt = now - self.t0
        if M.reduced():
            return 1.0
        if self.state == 'hold':
            return 1.0 - 0.04 * M.ease_out(M.clamp(dt / 100.0))
        if self.state == 'back':
            return 0.96 + 0.04 * M.ease_out(M.clamp(dt / self._back_ms()))
        if self.state == 'ok':
            return M.keyframes(dt / 300.0, [(0, 0.96), (0.45, 1.08), (1.0, 1.0)])
        return 1.0

    OK_MS, FAIL_MS, TAP_MS = 1300.0, 900.0, 320.0

    def anim_busy(self, now):
        return self.state != 'idle' or now - self.t_arm < 1250

    def step(self, now):
        """状态推进 (时钟回调, 不在 paint 内做副作用)"""
        dt, st = now - self.t0, self.state
        if st == 'hold' and dt >= M.HOLD:
            self._complete(now)
        elif (st == 'ok' and dt >= self.OK_MS) or (st == 'fail' and dt >= self.FAIL_MS) \
                or (st == 'tap' and dt >= self.TAP_MS) \
                or (st == 'back' and dt >= self._back_ms()):
            if st == 'ok':                       # 按草稿实况复核: 「已生效」期间又改值 = 保持可用
                self.dirty = bool(self.dirty_fn()) if self.dirty_fn else False
                if self.dirty:
                    self.t_arm = now
            self.state = 'idle'
        self.update()

    def _complete(self, now):
        try:
            ok = bool(self.commit())
        except Exception:
            ok = False
        self.state, self.t0 = ('ok' if ok else 'fail'), now
        self.kick()

    def cancel(self):
        if self.state == 'hold':
            now = self.clock.now()
            self.f0 = self._fill(now)
            self.state, self.t0 = 'back', now
            self.kick()

    def _start(self):
        if self.dirty and self.state in ('idle', 'back', 'tap', 'fail'):
            self.state, self.t0 = 'hold', self.clock.now()
            self.kick()

    def _release(self, inside=True):
        now = self.clock.now()
        if not self.dirty:
            return                               # 无待确认修改: 点击无动作
        if self.state != 'hold':
            return
        if now - self.t0 < 150:                  # 误点引导
            self.state, self.t0 = 'tap', now
            self._hint()
            self.kick()
        else:
            self.cancel()

    def _hint(self):
        if self.tip is None:
            self.tip = Bubble(self.window())
        b = self.body()
        self.tip.show_text('按住以确认',
                           self.mapToGlobal(QPoint(int(b.center().x()), int(b.top()))),
                           1500)

    # ---- 事件: 提前松开 / 移出 / Esc / 失焦 = 取消 ----
    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton and self.body().contains(ev.position()):
            self.setFocus(Qt.MouseFocusReason)
            self._start()
        ev.accept()

    def mouseMoveEvent(self, ev):
        if self.state == 'hold' and not self.body().contains(ev.position()):
            self.cancel()

    def mouseReleaseEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            self._release(self.body().contains(ev.position()))
        ev.accept()

    def leaveEvent(self, ev):
        self.cancel(); super().leaveEvent(ev)

    def focusOutEvent(self, ev):
        self.cancel(); super().focusOutEvent(ev)

    def keyPressEvent(self, ev):
        if ev.key() == Qt.Key_Escape and self.state == 'hold':
            self.cancel(); ev.accept()
        elif ev.key() in (Qt.Key_Space, Qt.Key_Return) and not ev.isAutoRepeat():
            self._start()
            ev.accept()
        else:
            super().keyPressEvent(ev)

    def keyReleaseEvent(self, ev):
        if ev.key() in (Qt.Key_Space, Qt.Key_Return) and not ev.isAutoRepeat():
            self._release(True); ev.accept()
        else:
            super().keyReleaseEvent(ev)

    def event(self, ev):
        if ev.type() == QEvent.WindowDeactivate:
            self.cancel()
        return super().event(ev)

    def paintEvent(self, ev):                    # 禁用态 40% 由 draw 自管 (仍可点 = 收起)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        self.draw(p, self.clock.now())
        p.end()

    def draw(self, p, now):
        st, dt = self.state, now - self.t0
        b = self.body()
        rad = 6.0 * self.k
        dx = 0.0
        if not M.reduced():
            if st == 'hold' and dt > M.HOLD_SHAKE:
                dx = 1.0 if int(dt / 30) % 2 else -1.0
            elif st == 'fail':
                dx = M.shake(dt / 200.0, 4.0 * self.k, 3)
        s = self._scale(now)
        c = b.center()
        p.translate(c.x() + dx, c.y()); p.scale(s, s); p.translate(-c.x(), -c.y())
        # 成功光环: 自按钮边缘外扩 8px 并淡出 (400ms)
        if st == 'ok' and dt < 400 and not M.reduced():
            q = dt / 400.0
            e = 8.0 * self.k * M.ease_out(q)
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(QColor(50, 200, 100, int(200 * (1 - q))), 2.0))
            p.drawRoundedRect(b.adjusted(-e, -e, e, e), rad + e, rad + e)
        fade = 1.0                               # ok 末段淡回默认样式
        if st == 'ok' and dt > 1000:
            fade = 1.0 - M.clamp((dt - 1000) / 300.0)
        active = self.dirty or st in ('ok', 'fail')
        p.setOpacity(1.0 if active else 0.4)
        clip = QPainterPath(); clip.addRoundedRect(b, rad, rad)
        p.setPen(Qt.NoPen); p.setBrush(QColor(M.PAPER).darker(int(100 + 5 * self.hov.value(now))))
        p.drawPath(clip)
        f = self._fill(now)
        if st == 'ok':
            col = mix(M.BLUE, M.GREEN, M.clamp(dt / 150.0))
        elif st == 'fail':
            col = QColor(M.RED)
        else:
            col = QColor(M.BLUE)
        fill = QRectF(b.x(), b.y(), b.width() * f, b.height())
        p.save(); p.setClipPath(clip)
        p.setOpacity(p.opacity() * fade)
        p.fillRect(fill, col)
        p.restore()
        self._draw_label(p, b, fill, st, dt, fade)
        pen = QColor(M.INK)
        if self.dirty and st == 'idle':          # 进入可用: 描边呼吸 1→0.5→1 ×2 (1.2s)
            q = (now - self.t_arm) / 1200.0
            if q < 1.0:
                pen.setAlphaF(1.0 - 0.5 * (1 - math.cos(q * 4 * math.pi)) / 2)
        elif st == 'ok':
            pen = mix(M.INK, M.GREEN, fade)
        elif st == 'fail':
            pen = QColor(M.RED)
        p.setBrush(Qt.NoBrush); p.setPen(QPen(pen, 1.3))
        p.drawRoundedRect(b, rad, rad)
        if self.focused:
            p.setPen(QPen(QColor(M.BLUE), 2.0))
            p.drawRoundedRect(b.adjusted(-2.5, -2.5, 2.5, 2.5), rad + 2, rad + 2)

    def _draw_label(self, p, b, fill, st, dt, fade):
        """文字: 黑底稿 + 填充区内白字 (裁切 = 文字颜色随进度从左到右反转)"""
        p.setFont(font(13 * self.k))
        if st == 'ok':
            txt = '已生效'
        elif st == 'fail':
            txt = '失败，重试'
        else:
            txt = '长按确认' if self.dirty else '确认'
        fm = QFontMetrics(p.font())
        cw = 14 * self.k if st == 'ok' else 0.0          # ✓ 图标位
        tw = fm.horizontalAdvance(txt) + cw
        x0 = b.center().x() - tw / 2
        tr_ = QRectF(x0 + cw, b.y(), tw - cw, b.height())
        ink = mix('#ffffff', M.INK, 1 - fade) if st == 'ok' else QColor(M.INK)
        for color, clip in ((ink, None), (QColor('#ffffff'), fill)):
            p.save()
            if clip is not None:
                if clip.width() <= 0 or fade <= 0:
                    p.restore(); break
                p.setClipRect(clip)
                p.setOpacity(p.opacity() * fade)
            p.setPen(color)
            p.drawText(tr_, Qt.AlignVCenter | Qt.AlignLeft, txt)
            if st == 'ok':                                  # ✓ 描边动画 200ms
                q = M.clamp((dt - 150) / 200.0) if not M.reduced() else 1.0
                path = QPainterPath()
                cy, s = b.center().y(), 4.5 * self.k
                pts = [QPointF(x0 + 1, cy), QPointF(x0 + s, cy + s * 0.9),
                       QPointF(x0 + cw - 2, cy - s)]
                path.moveTo(pts[0]); path.lineTo(pts[1]); path.lineTo(pts[2])
                pen = QPen(color, 1.8); pen.setCapStyle(Qt.RoundCap)
                L = path.length()
                pen.setDashPattern([max(0.01, L * q / 1.8), 1e4])
                p.setPen(pen); p.setBrush(Qt.NoBrush)
                if q > 0:
                    p.drawPath(path)
            p.restore()


class KeyCells(_Anim):
    """1–7 按键格: 点击某格进入监听 (闪烁), 按下键盘字母/数字完成绑定, Esc/失焦取消;
       on_bind(i, ch) 返回 False = 拒绝 (该格抖动)"""
    def __init__(self, parent, k, keys, on_bind):
        super().__init__(parent, k)
        self.keys = list(keys)
        self.on_bind = on_bind
        self.listen = -1
        self.t_listen = self.t_bad = -1e9
        self.bad = -1
        self.hover_i = -1

    def set_keys(self, keys):
        self.keys = list(keys); self.update()

    def anim_busy(self, now):
        return self.listen >= 0 or now - self.t_bad < 220

    def _cell(self, i):
        r = QRectF(self.rect()).adjusted(INSET, INSET, -INSET, -INSET)
        gap = 3.0 * self.k
        w = (r.width() - gap * 6) / 7
        return QRectF(r.x() + i * (w + gap), r.y(), w, r.height())

    def _at(self, pos):
        return next((i for i in range(7) if self._cell(i).contains(pos)), -1)

    def mouseMoveEvent(self, ev):
        i = self._at(ev.position())
        if i != self.hover_i:
            self.hover_i = i; self.update()

    def leaveEvent(self, ev):
        self.hover_i = -1; super().leaveEvent(ev)

    def mousePressEvent(self, ev):
        i = self._at(ev.position())
        if ev.button() == Qt.LeftButton and i >= 0:
            self.listen, self.t_listen = i, self.clock.now()
            self.setFocus(Qt.MouseFocusReason)
            self.kick()
        ev.accept()

    def focusOutEvent(self, ev):
        self.listen = -1; super().focusOutEvent(ev)

    def keyPressEvent(self, ev):
        if self.listen < 0:
            return super().keyPressEvent(ev)
        ev.accept()
        if ev.key() == Qt.Key_Escape:
            self.listen = -1; self.update(); return
        ch = ev.text().upper()
        if len(ch) != 1 or not ch.isalnum():
            return
        i = self.listen
        self.listen = -1
        if self.on_bind(i, ch):
            self.keys[i] = ch
        else:
            self.bad, self.t_bad = i, self.clock.now()
        self.kick()

    def draw(self, p, now):
        rad = 4.0 * self.k
        for i in range(7):
            c = self._cell(i)
            if i == self.bad and now - self.t_bad < 200 and not M.reduced():
                c = c.translated(M.shake((now - self.t_bad) / 200.0, 4.0 * self.k), 0)
            lis = i == self.listen
            blink = lis and int((now - self.t_listen) / 280) % 2 == 0
            bg = QColor('#e8f1ff') if blink else QColor(M.PAPER)
            if i == self.hover_i and not lis:
                bg = bg.darker(105)
            p.setBrush(bg)
            p.setPen(QPen(QColor(M.BLUE) if lis else QColor(M.INK), 2.0 if lis else 1.2))
            p.drawRoundedRect(c, rad, rad)
            p.setPen(QColor('#8a8f98'))
            p.setFont(font(8 * self.k))
            p.drawText(c.adjusted(2, 1, 0, 0), Qt.AlignLeft | Qt.AlignTop, str(i + 1))
            p.setPen(QColor(M.BLUE) if lis else QColor(M.INK))
            p.setFont(font(13 * self.k, True))
            k = self.keys[i] if i < len(self.keys) else ''
            p.drawText(c.adjusted(0, 3 * self.k, 0, 0), Qt.AlignCenter, '…' if lis else k)


class Bubble(QWidget):
    """提示气泡 (顶层无焦点, 不吃鼠标): 指向 tip 全局点上方, 淡入, ms 后自动淡出"""
    def __init__(self, parent=None):
        super().__init__(parent, Qt.ToolTip | Qt.FramelessWindowHint
                         | Qt.WindowStaysOnTopHint | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.text = ''
        self._hide = QTimer(self); self._hide.setSingleShot(True)
        self._hide.timeout.connect(self._fade_out)
        self._anim = QVariantAnimation(self)
        self._anim.valueChanged.connect(self.setWindowOpacity)
        self._anim.finished.connect(self._done)
        self._out = False

    def show_text(self, text, tip, ms=0):
        self.text = text
        fm = QFontMetrics(font(12))
        w, h = fm.horizontalAdvance(text) + 20, fm.height() + 12
        self.setFixedSize(w, h + 6)
        self.move(tip.x() - w // 2, tip.y() - h - 10)
        if self.isVisible() and not self._out:  # 已显示 (拖动跟随): 只改文字/位置
            self.update()
            if ms > 0:
                self._hide.start(ms)
            return
        self._out = False
        self._anim.stop()
        self._anim.setDuration(M.dur(M.MICRO)); self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self.setWindowOpacity(0.0); self.show(); self.raise_(); self._anim.start()
        self.update()
        if ms > 0:
            self._hide.start(ms)

    def _fade_out(self):
        if not self.isVisible():
            return
        self._out = True
        self._anim.stop()
        self._anim.setDuration(M.dur(M.MICRO)); self._anim.setStartValue(self.windowOpacity())
        self._anim.setEndValue(0.0); self._anim.start()

    def _done(self):
        if self._out:
            self.hide()

    def hide_now(self):
        self._hide.stop(); self._anim.stop(); self.hide()

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(0.5, 0.5, self.width() - 1, self.height() - 7)
        path = QPainterPath(); path.addRoundedRect(r, 5, 5)
        cx = self.width() / 2
        tri = QPainterPath()
        tri.moveTo(cx - 5, r.bottom() - 0.5); tri.lineTo(cx, r.bottom() + 5.5)
        tri.lineTo(cx + 5, r.bottom() - 0.5); tri.closeSubpath()
        p.setPen(Qt.NoPen); p.setBrush(QColor(26, 26, 26, 235))
        p.drawPath(path.united(tri))
        p.setPen(QColor('#ffffff')); p.setFont(font(12))
        p.drawText(r, Qt.AlignCenter, self.text)
        p.end()


class PanelItem(QWidget):
    """子面板设置项: 线框外框 + 左侧标签 + 右侧控件横排; attach() 的外挂控件
       (确认 / 所属排) 与本项同步移动淡入 (由径向浮层统一驱动)"""
    W, H, LABEL_W = 282.0, 42.0, 88.0                # 标签列容纳 5 个汉字 (声音可视化)

    def __init__(self, parent, k, label):
        super().__init__(parent)
        self.k, self.label = k, label
        self.ctrls = []                      # [(widget, 设计宽 0=占满剩余)]
        self.extras = []                     # [(widget, 设计宽)]
        self.resize(int(self.W * k), int(self.H * k))
        self.setAttribute(Qt.WA_StyledBackground, False)
        self.setAttribute(Qt.WA_NoMousePropagation)   # 子控件未消费的点击也不漏到遮罩
        self.setMouseTracking(True)

    def add(self, w, width=0):
        w.setParent(self); self.ctrls.append((w, width)); self._lay(); return w

    def attach(self, w, width):
        self.extras.append((w, width)); return w

    def block_w(self):
        """本项 + 外挂控件总宽 (px), 用于树状连线箭头落点"""
        gap = 8 * self.k
        return self.width() + sum(int(wd * self.k) + gap for _, wd in self.extras)

    def _lay(self):
        k = self.k
        x = self.LABEL_W * k
        right = self.width() - 6 * k
        h = self.height() - 10 * k
        fixed = sum(int(wd * k) for _, wd in self.ctrls if wd > 0)
        gaps = 4 * k * max(0, len(self.ctrls) - 1)
        flex = max(20, right - x - fixed - gaps)
        for w, wd in self.ctrls:
            ww = int(wd * k) if wd > 0 else int(flex)
            w.setGeometry(int(x), int(5 * k), ww, int(h))
            x += ww + 4 * k

    def place(self, x, y, opacity=1.0):
        """本项左上角 → (x, y); 外挂控件依次排在右侧; 统一透明度"""
        k = self.k
        self.move(int(x), int(y))
        ex = x + self.width() + 8 * k
        for w, wd in self.extras:
            m = getattr(w, 'RING', 0) * k
            w.setGeometry(int(ex - m), int(y - m), int(wd * k + 2 * m),
                          int(self.height() + 2 * m))
            ex += wd * k + 8 * k
        for w in self.widgets():
            set_opacity(w, opacity)

    def show_all(self, on=True):
        for w in self.widgets():
            if w.isVisible() != on:
                w.setVisible(on)

    def widgets(self):
        return [self] + [w for w, _ in self.extras]

    # ---- 可点击标签 (例: 谱面长度 ⇄ 谱面高度) ----
    def set_label_toggle(self, labels, on_toggle):
        """labels=[文字…]; 点击标签区循环切换, 文字上下翻转; on_toggle(新序号)"""
        self._labels, self._li, self._on_toggle = list(labels), 0, on_toggle
        self.label = self._labels[0]
        self.setCursor(Qt.ArrowCursor)

    def _label_rect(self):
        return QRectF(0, 0, self.LABEL_W * self.k, self.height())

    def mousePressEvent(self, ev):
        """吞掉本项内一切点击 (标签区/空隙不漏到遮罩 → 子面板不会被误收起)"""
        ev.accept()
        if ev.button() == Qt.LeftButton and getattr(self, '_labels', None) \
                and self._label_rect().contains(ev.position()):
            self._old_label, self._t_label = self.label, _now_ms()
            self._li = (self._li + 1) % len(self._labels)
            self.label = self._labels[self._li]
            self._on_toggle(self._li)
            self._label_timer().start()

    def mouseDoubleClickEvent(self, ev):
        self.mousePressEvent(ev)

    def mouseReleaseEvent(self, ev):
        ev.accept()

    def mouseMoveEvent(self, ev):
        ev.accept()
        if getattr(self, '_labels', None):
            hot = self._label_rect().contains(ev.position())
            self.setCursor(Qt.PointingHandCursor if hot else Qt.ArrowCursor)

    def wheelEvent(self, ev):
        ev.accept()

    def _label_timer(self):
        t = getattr(self, '_lt', None)
        if t is None:
            t = self._lt = QTimer(self); t.setInterval(16)
            t.timeout.connect(self._label_step)
        return t

    def _label_step(self):
        if _now_ms() - self._t_label > M.dur(M.FLIP) + 20:
            self._lt.stop()
        self.update()

    def set_mark(self, on):
        """已改动未确认: 标签旁蓝点"""
        if bool(on) != getattr(self, 'mark', False):
            self.mark = bool(on); self.update()

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        k = self.k
        r = QRectF(self.rect()).adjusted(0.75, 0.75, -0.75, -0.75)
        p.setBrush(QColor(M.PAPER)); p.setPen(QPen(QColor(M.INK), 1.3))
        p.drawRoundedRect(r, 6 * k, 6 * k)
        p.setFont(font(14 * k, True))
        lr = QRectF(10 * k, 0, (self.LABEL_W - 22) * k, self.height())
        t0 = getattr(self, '_t_label', None)
        if t0 is not None and _now_ms() - t0 < M.dur(M.FLIP):
            q = M.ease_out(M.clamp((_now_ms() - t0) / M.dur(M.FLIP)))
            dy = 0.0 if M.reduced() else self.height() * 0.6
            p.save(); p.setClipRect(lr); p.setPen(QColor(M.INK))
            p.setOpacity(1 - q); p.drawText(lr.translated(0, -dy * q),
                                            Qt.AlignVCenter | Qt.AlignLeft, self._old_label)
            p.setOpacity(q); p.drawText(lr.translated(0, dy * (1 - q)),
                                        Qt.AlignVCenter | Qt.AlignLeft, self.label)
            p.restore()
        else:
            p.setPen(QColor(M.INK))
            p.drawText(lr, Qt.AlignVCenter | Qt.AlignLeft, self.label)
        if getattr(self, '_labels', None):       # 可切换标识 ⇅
            p.setPen(QColor('#8a8f98')); p.setFont(font(11 * k))
            p.drawText(QRectF((self.LABEL_W - 16) * k, 0, 12 * k, self.height()),
                       Qt.AlignCenter, '⇅')
        if getattr(self, 'mark', False):
            p.setPen(Qt.NoPen); p.setBrush(QColor(M.BLUE))
            p.drawEllipse(QPointF(5 * k, self.height() / 2), 2.6 * k, 2.6 * k)
        p.end()


def _now_ms():
    from PySide6.QtCore import QDateTime
    return float(QDateTime.currentMSecsSinceEpoch())


class ConfirmNode:
    """子面板共用的长按【确认】: 作为最后一个树节点 (与设置项同一接口参与定位/淡入)"""
    W, H = 132.0, 42.0

    def __init__(self, parent, k, commit, dirty_fn):
        self.k = k
        self.btn = HoldConfirm(parent, k, commit, dirty_fn)
        self.extras = []
        self._w, self._h = int(self.W * k), int(self.H * k)
        self._x = self._y = 0
        self.label = '确认'

    def width(self):
        return self._w

    def height(self):
        return self._h

    def x(self):
        return self._x

    def y(self):
        return self._y

    def block_w(self):
        return self._w

    def widgets(self):
        return [self.btn]

    def place(self, x, y, opacity=1.0):
        m = HoldConfirm.RING * self.k
        self._x, self._y = int(x), int(y)
        self.btn.setGeometry(int(x - m), int(y - m), int(self._w + 2 * m), int(self._h + 2 * m))
        set_opacity(self.btn, opacity)

    def show_all(self, on=True):
        self.btn.setVisible(on)

    def set_mark(self, on):
        pass


def set_opacity(w, o):
    """QGraphicsOpacityEffect 透明度 (o≥0.999 移除效果, 免离屏合成开销)"""
    eff = w.graphicsEffect()
    if o >= 0.999:
        if eff is not None:
            w.setGraphicsEffect(None)
        return
    if not isinstance(eff, QGraphicsOpacityEffect):
        eff = QGraphicsOpacityEffect(w); w.setGraphicsEffect(eff)
    eff.setOpacity(max(0.0, o))
