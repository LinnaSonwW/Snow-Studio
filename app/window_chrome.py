# -*- coding: utf-8 -*-
"""暗黑圆角无边框窗口基类 (FL/iOS 玻璃风):
   自绘标题栏(拖动/双击最大化/最小化/关闭) + 比背景稍白的细边框 + 外圈黑色光晕
   + 八向边缘缩放。子类通过 setContent() 放入主体内容。
   窗口按钮图标为 QPainter 矢量自绘 (字体无关), 扁平无外框, 悬停变色/关闭红 (主流做法)。"""
import random, time
from PySide6.QtCore import (Qt, QRectF, QPointF, QTimer, QSize, QObject,
                            QEvent, QPropertyAnimation, QAbstractAnimation,
                            QParallelAnimationGroup, QEasingCurve)
from PySide6.QtGui import QColor, QPainter, QPen, QRegion, QPainterPath
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                               QPushButton, QApplication,
                               QGraphicsOpacityEffect)


class _HoverPulse(QObject):
    """悬停脉冲: 进入时透明度 1.0→0.72→1.0 柔和闪动 (QSS 无法过渡 hover,
       通用替代方案; 事件过滤器挂在按钮上)"""
    def __init__(self, w, frm, dur):
        QObject.__init__(self, w)
        self._frm = frm; self._dur = dur
        eff = QGraphicsOpacityEffect(w); w.setGraphicsEffect(eff)
        eff.setOpacity(1.0)
        self._anim = QPropertyAnimation(eff, b'opacity', w)
        self._anim.setDuration(dur)
        self._anim.setKeyValues([(0, 1.0), (0.5, frm), (1, 1.0)])
    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.HoverEnter:
            a = self._anim; a.stop()
            a.setStartValue(1.0); a.start()
        return QObject.eventFilter(self, obj, ev)


def hover_pulse(w, frm=0.72, duration=180):
    """(交互轮) 悬停脉冲反馈: 进入时透明度柔和闪动一次。
       依赖 QSS :hover 的按钮直接可用 (效果叠加, 不改样式)。"""
    w.setAttribute(Qt.WA_Hover, True)
    f = _HoverPulse(w, frm, duration)
    w.installEventFilter(f)
    return f


def fade_scale_in(w, duration=150):
    """(交互轮) 弹窗入场动效: 150ms 淡入 + 0.97→1.0 缩放 (中心原点)。
       QWidget 无 setGraphicsTransform —— 缩放用窗口几何动画实现;
       挂 showEvent 钩子, 首次显示时触发 (几何在 show 时已定稿)。
       函数内延迟 import 动画类, 供各弹窗 show 前调用。"""
    from PySide6.QtCore import (QPropertyAnimation, QParallelAnimationGroup,
                                QEasingCurve, QRect)
    w.setWindowOpacity(0.0)
    orig_se = w.showEvent
    def _se(ev):
        w.setWindowOpacity(1.0)
        g0 = w.geometry()
        sw = max(1, int(g0.width() * 0.97))
        sh = max(1, int(g0.height() * 0.97))
        # (修复) QRect.center() 返回 QPoint —— 新版 PySide6 不可序列解包,
        # moveCenter 直接收 QPoint 原样传入
        start = QRect(0, 0, sw, sh); start.moveCenter(g0.center())
        g = QParallelAnimationGroup(w)
        a1 = QPropertyAnimation(w, b'windowOpacity', g)
        a1.setDuration(duration); a1.setStartValue(0.0); a1.setEndValue(1.0)
        a1.setEasingCurve(QEasingCurve.OutCubic)
        a2 = QPropertyAnimation(w, b'geometry', g)
        a2.setDuration(duration); a2.setStartValue(start); a2.setEndValue(g0)
        a2.setEasingCurve(QEasingCurve.OutCubic)
        g.start(QAbstractAnimation.DeleteWhenStopped)
        orig_se(ev)
    w.showEvent = _se


def _draw_caption_icon(p, kind, col, s):
    """窗口按钮矢量图标: min=横线 / max=方框 / restore=双方框 / close=叉
       直接画在目标 painter 上 (矢量, 任意尺寸清晰, 不依赖字体)"""
    pen = QPen(QColor(col), 1.5)
    pen.setCapStyle(Qt.FlatCap)
    p.setPen(pen); p.setBrush(Qt.NoBrush)
    m = s * 0.28                                    # 图标边距
    if kind == 'min':
        p.drawLine(QPointF(m, s / 2), QPointF(s - m, s / 2))
    elif kind == 'max':
        p.drawRect(QRectF(m, m + 1, s - 2 * m, s - 2 * m - 2))
    elif kind == 'restore':
        w = s - 2 * m
        p.drawRect(QRectF(m, m + 2.5, w - 2.5, w - 2.5))
        p.drawRect(QRectF(m + 2.5, m, w - 2.5, w - 2.5))
    else:                                           # close
        p.drawLine(QPointF(m, m), QPointF(s - m, s - m))
        p.drawLine(QPointF(s - m, m), QPointF(m, s - m))


def _qcol(spec):
    """颜色解析: 兼容 'rgba(r, g, b, a)' CSS 函数式字符串 (QColor 不认, 会变黑),
       其余交给 QColor (#hex / 颜色名); 解析失败回退全透明"""
    if isinstance(spec, str) and spec.lstrip().lower().startswith('rgba'):
        try:
            parts = spec[spec.find('(') + 1:spec.rfind(')')].split(',')
            return QColor(*[int(x) for x in parts[:4]])
        except (ValueError, TypeError):
            return QColor(0, 0, 0, 0)
    c = QColor(spec)
    return c if c.isValid() else QColor(0, 0, 0, 0)


class CaptionButton(QPushButton):
    """窗口控制按钮: 自绘图标 + 自绘背景 (完全掌控悬停态, 不受全局 QSS 影响)
       关闭钮悬停变红; rad=胶囊/方角半径"""
    def __init__(self, kind, w, h, rad, tip='',
                 bg_rest='rgba(255, 255, 255, 0)', bg_hover='#33333d',
                 bg_down='#3d3d4a', hover_red='#b3454f'):
        super().__init__()
        self.kind = kind                            # min / max / restore / close
        self._hover = False
        self._rad = rad
        self._bg_rest = _qcol(bg_rest)
        self._bg_hover = _qcol(bg_hover)
        self._bg_down = _qcol(bg_down)
        self._hover_red = _qcol(hover_red)
        self.setFixedSize(w, h)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(tip)
    def set_kind(self, kind):
        """max <-> restore 图标切换 (窗口最大化状态变化时)"""
        if kind != self.kind:
            self.kind = kind; self.update()
    def enterEvent(self, ev):
        self._hover = True; self.update(); super().enterEvent(ev)
    def leaveEvent(self, ev):
        self._hover = False; self.update(); super().leaveEvent(ev)
    def paintEvent(self, ev):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        close = self.kind == 'close'
        if self.isDown():
            bg = self._bg_down if not (close and self._hover) else '#933841'
            col = '#ffffff'
        elif self._hover:
            bg = self._hover_red if close else self._bg_hover
            col = '#ffffff'
        else:
            bg, col = self._bg_rest, '#d6d6de'
        p.setPen(Qt.NoPen); p.setBrush(QColor(bg))
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.drawRoundedRect(r, self._rad, self._rad)
        _draw_caption_icon(p, self.kind, col, min(self.width(), self.height()))

_FX_CHARS = '!<>-_\\/[]{}=+*^?#01'          # (W 轮) 乱码字符集 (纯 ASCII 符号与数字)


class _TitleLabel(QWidget):
    """自绘标题文字 (W 轮)。窗口配置类属性 title_fx={pre,cur,alt,suf} 时:
       点击热段(cur)触发动画 —— 乱码收缩 → 向右展开逐字落位为 alt; 再点切回 (可逆装饰)。
       未配置的窗口 (编辑窗/迷你条) 与普通 QLabel 行为一致, 点击文字透传给标题栏拖动。
       动画只重绘本标签 (33ms), _fx_tick(now_ms) 纯时间参数驱动, 便于离屏测试精确推进。"""
    SHRINK_MS, EXPAND_MS, TICK_MS = 260, 420, 33

    def __init__(self, text, win):
        super().__init__()
        self._win = win; self._base = text
        f = self.font(); f.setPixelSize(12); self.setFont(f)
        self._hover = False
        self._seg = None; self._disp = None; self._seg_w = None
        self._phase = None; self._is_alt = False
        if self._fx() is not None:
            self._seg = self._fx()['cur']
            self.setCursor(Qt.PointingHandCursor)
            self._timer = QTimer(self); self._timer.setInterval(self.TICK_MS)
            self._timer.timeout.connect(
                lambda: self._fx_tick(time.monotonic() * 1000.0))
        self.setMouseTracking(True)

    def _fx(self):
        return getattr(self._win, 'title_fx', None)

    # ---- 几何: 布局宽度固定取两态热段较大者, 动画不引起整行抖动 ----
    def _full_text(self):
        fx = self._fx()
        return self._base if fx is None else fx['pre'] + self._seg + fx['suf']
    def sizeHint(self):
        fm = self.fontMetrics()
        fx = self._fx()
        if fx is None:
            w = fm.horizontalAdvance(self._base)
        else:
            w = (fm.horizontalAdvance(fx['pre'])
                 + max(fm.horizontalAdvance(fx['cur']),
                       fm.horizontalAdvance(fx['alt']))
                 + fm.horizontalAdvance(fx['suf']))
        return QSize(w + 2, fm.height() + 4)
    def minimumSizeHint(self):
        return self.sizeHint()

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setPen(QColor('#c9d2dc' if self._hover else '#9aa4b0'))
        fm = self.fontMetrics(); h = self.height()
        base = fm.ascent() + (h - fm.height()) // 2
        fx = self._fx()
        if fx is None:
            p.drawText(0, base, self._base); return
        x = 0.0
        p.drawText(QPointF(x, base), fx['pre'])
        x += fm.horizontalAdvance(fx['pre'])
        seg = self._disp if self._disp is not None else self._seg
        w = (self._seg_w if self._seg_w is not None
             else fm.horizontalAdvance(self._seg))
        p.save()
        p.setClipRect(QRectF(x, 0, max(w, 1.0), h))
        p.drawText(QRectF(x, 0, fm.horizontalAdvance(seg) + 4, h),
                   Qt.AlignLeft | Qt.AlignVCenter, seg)
        p.restore()
        x += w
        p.drawText(QPointF(x, base), fx['suf'])

    # ---- 交互: 仅热段文字矩形可点, 其余透传给标题栏拖动 ----
    def mousePressEvent(self, ev):
        if (ev.button() == Qt.LeftButton and self._phase is None
                and self._fx() is not None):
            fm = self.fontMetrics()
            lo = fm.horizontalAdvance(self._fx()['pre'])
            hi = lo + fm.horizontalAdvance(self._seg)
            if lo <= ev.position().x() <= hi + 2:
                self._start_fx(); ev.accept(); return
        ev.ignore()

    def enterEvent(self, e):
        self._hover = True; self.update()
    def leaveEvent(self, e):
        self._hover = False; self.update()

    # ---- 动画状态机: 收缩(全程乱码) → 展开(从左到右逐字落位) ----
    def _start_fx(self):
        fx = self._fx()
        self._is_alt = not self._is_alt
        self._target = fx['alt'] if self._is_alt else fx['cur']
        self._phase = 'shrink'
        self._t0 = time.monotonic() * 1000.0
        fm = self.fontMetrics()
        w_cur = fm.horizontalAdvance(fx['cur'])
        w_alt = fm.horizontalAdvance(fx['alt'])
        self._w_from = float(w_cur)
        self._w_to = float(min(w_cur, w_alt)) * 0.25    # 收缩到约 1/4 宽
        self._timer.start(); self.update()

    @staticmethod
    def _scr(n):
        return ''.join(random.choice(_FX_CHARS) for _ in range(n))

    def _fx_tick(self, now):
        if self._phase is None:
            return
        if self._phase == 'shrink':
            p = min(1.0, (now - self._t0) / self.SHRINK_MS)
            self._seg_w = self._w_from + (self._w_to - self._w_from) * p
            self._disp = self._scr(len(self._target))
            if p >= 1.0:
                self._phase = 'expand'; self._t0 = now
                self._w_from = self._seg_w
                self._w_to = float(self.fontMetrics().horizontalAdvance(self._target))
        else:
            p = min(1.0, (now - self._t0) / self.EXPAND_MS)
            self._seg_w = self._w_from + (self._w_to - self._w_from) * p
            rev = min(1.0, p / 0.8) * len(self._target)  # 前 80% 时间逐字落位
            self._disp = ''.join(
                ch if i < rev else random.choice(_FX_CHARS)
                for i, ch in enumerate(self._target))
            if p >= 1.0:                                 # 落位收尾
                self._seg = self._target
                self._disp = None; self._seg_w = None; self._phase = None
                self._timer.stop()
        self.update()


class ChromeWindow(QWidget):
    # (M8) WA_TranslucentBackground 仅用于把四角裁成平滑圆角,
    #      窗体本体为不透明纯色, 无玻璃透视效果
    TRANSLUCENT = True
    RES = 8              # 边缘缩放热区(px)
    RAD = 8              # 圆角
    MAR = 0              # 内容贴边
    BAR = 34             # 标题栏高度
    BAR_BUTTONS = True   # 标题栏右侧窗口按钮 (主窗移入工具条后置 False)
    RESIZABLE = True     # 边缘缩放/最大化按钮/双击最大化 (主窗固定尺寸后置 False)
    BG = '#1b2026'       # 窗底色
    BORDER = '#4a515c'   # 稍亮细边框

    def __init__(self, title):
        super().__init__(None, Qt.Window | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TranslucentBackground)   # 圆角裁切用
        self._title = title
        self.setWindowTitle(title)                 # 任务栏/系统标题
        self._press = None            # (方向, 全局起点, 起始 geometry)
        self._bar_drag = None
        self._maxed = False
        self._normal = None
        self.setMinimumSize(420, 300)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._make_bar())
        self.frame = QWidget()
        self.frame.setObjectName('ChromeFrame')
        self.frame.setStyleSheet(self.FRAME_QSS)
        fl = QVBoxLayout(self.frame)
        fl.setContentsMargins(0, 0, 0, 0); fl.setSpacing(0)
        root.addWidget(self.frame, 1)
        self._content = None
    def setContent(self, w, margins=(0, 0, 0, 0)):
        """放入主体内容 (位于自绘标题栏之下)"""
        self._content = w
        self.frame.layout().addWidget(w)
        self.frame.layout().setContentsMargins(*margins)
    # ---- 自绘标题栏 ----
    def _make_bar(self):
        bar = QWidget(); bar.setFixedHeight(self.BAR)
        h = QHBoxLayout(bar); h.setContentsMargins(12, 5, 8, 5); h.setSpacing(4)
        lb = _TitleLabel(self._title, self)
        self._title_lb = lb                # (W 轮) 标题动画控件引用
        h.addWidget(lb); h.addStretch(1)
        if self.BAR_BUTTONS:      # (编辑窗) 标题栏窗口按钮: 扁平自绘图标, 悬停显底
            from i18n import t
            self._btn_max = None
            buttons = [('min', self.showMinimized, '最小化')]
            if self.RESIZABLE:                # 固定尺寸窗不提供最大化
                buttons.append(('max', self._toggle_max, '最大化 / 还原'))
            buttons.append(('close', self.close, '关闭'))
            for kind, cb, tip in buttons:
                b = CaptionButton(kind, 34, 24, 4, tip=t(tip))
                b.clicked.connect(cb)
                if kind == 'max': self._btn_max = b
                h.addWidget(b)
        bar.mousePressEvent = self._bar_press
        bar.mouseMoveEvent = self._bar_move
        bar.mouseReleaseEvent = self._bar_rel
        bar.mouseDoubleClickEvent = self._bar_dbl
        return bar
    def _bar_press(self, ev):
        if ev.button() == Qt.LeftButton and not self._maxed:
            self._bar_drag = (ev.globalPosition().toPoint()
                              - self.frameGeometry().topLeft())
    def _bar_move(self, ev):
        if self._bar_drag is not None and ev.buttons() & Qt.LeftButton:
            self.move(ev.globalPosition().toPoint() - self._bar_drag)
    def _bar_rel(self, ev):
        self._bar_drag = None
    def _bar_dbl(self, ev):
        if self.RESIZABLE: self._toggle_max()
    def _toggle_max(self):
        g = QApplication.primaryScreen().availableGeometry()
        if self._maxed:
            self._maxed = False
            if self._normal is not None: self.setGeometry(self._normal)
        else:
            self._maxed = True
            self._normal = self.geometry()
            self.setGeometry(g.adjusted(4, 4, -4, -4))
        if getattr(self, '_btn_max', None) is not None:      # 图标 最大化⇄还原
            self._btn_max.set_kind('restore' if self._maxed else 'max')
    # ---- 八向边缘缩放 ----
    _CURS = {'l': Qt.SizeHorCursor, 'r': Qt.SizeHorCursor, 't': Qt.SizeVerCursor,
             'b': Qt.SizeVerCursor, 'lt': Qt.SizeFDiagCursor, 'rb': Qt.SizeFDiagCursor,
             'tr': Qt.SizeBDiagCursor, 'bl': Qt.SizeBDiagCursor}
    def _edge_at(self, pos):
        m = self.RES; r = self.rect()
        L = pos.x() <= m; R = pos.x() >= r.width() - m
        T = pos.y() <= m; B = pos.y() >= r.height() - m
        if L and T: return 'lt'
        if R and T: return 'tr'
        if L and B: return 'bl'
        if R and B: return 'rb'
        if L: return 'l'
        if R: return 'r'
        if T: return 't'
        if B: return 'b'
        return None
    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton and not self._maxed:
            d = self._edge_at(ev.position().toPoint()) if self.RESIZABLE else None
            if d:
                self._press = (d, ev.globalPosition().toPoint(), self.frameGeometry())
                return
        super().mousePressEvent(ev)
    def mouseMoveEvent(self, ev):
        gp = ev.globalPosition().toPoint()
        if self._press is None:
            d = self._edge_at(ev.position().toPoint()) if self.RESIZABLE else None
            self.setCursor(self._CURS.get(d, Qt.ArrowCursor))
            super().mouseMoveEvent(ev); return
        d, gp0, geo = self._press
        dx = gp.x() - gp0.x(); dy = gp.y() - gp0.y()
        nx, ny, nw, nh = geo.x(), geo.y(), geo.width(), geo.height()
        if 'l' in d: nw = geo.width() - dx; nx = geo.x() + dx
        if 'r' in d: nw = geo.width() + dx
        if 't' in d: nh = geo.height() - dy; ny = geo.y() + dy
        if 'b' in d: nh = geo.height() + dy
        nw = max(nw, self.minimumWidth()); nh = max(nh, self.minimumHeight())
        self.setGeometry(nx, ny, nw, nh)
    def mouseReleaseEvent(self, ev):
        self._press = None
        super().mouseReleaseEvent(ev)
    # ---- 窗底与边框 (M8): 抗锯齿圆角, 四角逐像素透明 ----
    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        p.setPen(QPen(QColor(self.BORDER), 1))
        p.setBrush(QColor(self.BG))
        p.drawRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1),
                          self.RAD, self.RAD)
