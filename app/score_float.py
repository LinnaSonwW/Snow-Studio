# -*- coding: utf-8 -*-
"""悬浮乐谱 (按设计图2): 只保留谱面本体 + 左侧音轨名称栏;
   顶部 4px 播放进度条 (悬停 8px + 拖动圆点 + 时间气泡, 点击跳转),
   悬停进度条 150ms 后工具栏向上滑出 (【选项】【收起】【▷/‖】【□】【—】【×】),
   离开 400ms 收回; 左上 BPM/节奏 元数据 (双击原位编辑)。
   谱面渲染复用 ScoreStrip/PerformanceStrip.qml (禁止复制实现);
   进度/播放/跳转全部走主窗 PlaybackController 既有接口 (不另建播放时钟)。"""
from PySide6.QtCore import (Qt, QRectF, QPointF, QPoint, QTimer, QEvent,
                            QVariantAnimation, Signal)
from PySide6.QtGui import (QPainter, QColor, QPen, QFontMetrics, QKeySequence,
                           QShortcut, QCursor, QPainterPath)
from PySide6.QtWidgets import (QWidget, QLineEdit, QComboBox, QApplication,
                               QMessageBox)
from common import KB_W, fmt_sec
from i18n import t as tr
import settings_store as store
from score_strip import ScoreStrip, ROW_H_PX
import ui_motion as M
from radial_controls import Tween, Bubble, font, BOX_QSS

TOP_H = 70           # 工具栏行 + BPM 行 (工具栏隐藏时透明, 不挡桌面)
BAR_Z = 12           # 进度条悬停带 (细条贴在谱面顶边)
BODY_Y = TOP_H + BAR_Z
META_X, META_Y = 1, 42   # BPM/节奏 元数据 (左上, 常显)
PILL_Y = 6               # 工具栏行顶 (位于 BPM 正上方)
TSIG_PRESETS = ('2/4', '3/4', '4/4', '6/8')


class FloatStrip(ScoreStrip):
    """悬浮谱专用车道: 只读宿主无「+」选轨入口 —— 编辑器空白乐谱排 () 不进悬浮谱;
       全部为空白排 (编辑器刚打开未选轨) 时回落为全部音轨, 谱面不会空白"""
    def set_lanes(self, tids):
        keys = [k for k in tids if not (isinstance(k, (list, tuple)) and len(k) == 0)]
        if not keys:
            keys = [t.tid for t in getattr(self.mw, 'tracks', [])]
        super().set_lanes(keys)


class _TextRef:
    """兼容旧测试的 lb_bpm / lb_ts .text() 读取口"""
    def __init__(self, fn):
        self._fn = fn

    def text(self):
        return self._fn()


def label_width(name_pt):
    """轨名栏宽随「音轨名称」字号: 默认 7pt = 64px (与卷帘键盘列同宽)"""
    return int(max(40, min(200, round(KB_W * float(name_pt) / 7.0))))


class MetaChip(QWidget):
    """左上 BPM/节奏: 悬停虚线下划线 + 文本光标; 双击原位编辑 (BPM 输入框自动全选,
       20–300 越界抖动后回退原值; 节奏下拉 2/4 3/4 4/4 6/8 亦可自定义);
       回车 / 点外部 = 确认, Esc = 取消; 确认后数字 1.0→1.1→1.0 放大反馈"""
    FIELD = {'bpm': 40, 'ts': 58}
    LABEL = (('bpm', 'BPM：'), ('ts', '节奏：'))

    def __init__(self, host):
        super().__init__(host)
        self.host = host
        self.vals = {'bpm': '120', 'ts': '4/4'}
        self.hover = self.editing = self.editor = None
        self.t_pulse = {'bpm': -1e9, 'ts': -1e9}
        self.f, self.fb = font(12), font(12, True)
        self.clock = M.Clock(self, lambda _n: self.update(),
                             lambda n: any(n - t < 260 for t in self.t_pulse.values()))
        self.setMouseTracking(True)
        fm = QFontMetrics(self.f)
        w = 10 + sum(fm.horizontalAdvance(l) + self.FIELD[k] + 10 for k, l in self.LABEL)
        self.setFixedSize(w + 16, 24)            # +16 = 节奏下拉箭头

    def field(self, key):
        fm = QFontMetrics(self.f)
        x = 10.0
        for k, lab in self.LABEL:
            x += fm.horizontalAdvance(lab)
            if k == key:
                return QRectF(x, 0, self.FIELD[k], self.height())
            x += self.FIELD[k] + 10
        return QRectF()

    def set_values(self, bpm, ts):
        if (bpm, ts) != (self.vals['bpm'], self.vals['ts']):
            self.vals = {'bpm': bpm, 'ts': ts}
            self.update()

    def pulse(self, key):
        self.t_pulse[key] = self.clock.now(); self.clock.run()

    def _key_at(self, pos):
        return next((k for k, _ in self.LABEL if self.field(k).contains(pos)), None)

    def mouseMoveEvent(self, ev):
        k = self._key_at(ev.position())
        if k != self.hover:
            self.hover = k
            self.setCursor(Qt.IBeamCursor if k else Qt.ArrowCursor)
            self.update()
        ev.ignore()

    def leaveEvent(self, ev):
        self.hover = None; self.update()

    def mousePressEvent(self, ev):
        ev.ignore()                              # 交给窗口拖动

    def mouseDoubleClickEvent(self, ev):
        k = self._key_at(ev.position())
        if k:
            self.begin_edit(k)
        ev.accept()

    def paintEvent(self, ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setBrush(QColor(255, 255, 255, 235)); p.setPen(QPen(QColor(M.INK), 1.0))
        p.drawRoundedRect(r, 5, 5)
        fm = QFontMetrics(self.f)
        now = self.clock.now()
        x = 10.0
        for k, lab in self.LABEL:
            p.setFont(self.f); p.setPen(QColor('#555a62'))
            lw = fm.horizontalAdvance(lab)
            p.drawText(QRectF(x, 0, lw, self.height()), Qt.AlignVCenter, lab)
            fr = self.field(k)
            if self.editing != k:
                s = 1.0 if M.reduced() else \
                    M.keyframes((now - self.t_pulse[k]) / 240.0, [(0, 1), (0.4, 1.1), (1, 1)])
                p.save()
                c = QPointF(fr.left() + 2, fr.center().y())
                p.translate(c); p.scale(s, s); p.translate(-c)
                p.setFont(self.fb); p.setPen(QColor(M.INK))
                p.drawText(fr.adjusted(2, 0, 0, 0), Qt.AlignVCenter | Qt.AlignLeft, self.vals[k])
                p.restore()
                if self.hover == k:              # 悬停虚线下划线 = 可编辑
                    tw = QFontMetrics(self.fb).horizontalAdvance(self.vals[k])
                    pen = QPen(QColor(M.BLUE), 1.0, Qt.DashLine)
                    p.setPen(pen)
                    y = fr.center().y() + 8
                    p.drawLine(QPointF(fr.left() + 2, y), QPointF(fr.left() + 2 + tw, y))
            x = fr.right() + 10
        p.end()

    # ---- 原位编辑 ----
    def begin_edit(self, key):
        if self.editor is not None:
            self.end_edit(True)
        fr = self.field(key).adjusted(0, 3, 0, -3).toRect()
        if key == 'bpm':
            ed = QLineEdit(self.vals['bpm'], self)
            ed.setStyleSheet(BOX_QSS % 12)
            ed.returnPressed.connect(lambda: self.end_edit(True))
        else:
            ed = QComboBox(self)
            ed.setEditable(True)
            ed.addItems(list(TSIG_PRESETS))
            ed.setEditText(self.vals['ts'])
            ed.setStyleSheet('QComboBox{background:#fff;border:1px solid #2f7cf6;'
                             'border-radius:4px;font-size:12px;padding:0 2px;}')
            ed.lineEdit().returnPressed.connect(lambda: self.end_edit(True))
            ed.activated.connect(lambda _i: self.end_edit(True))
            fr.setWidth(fr.width() + 16)
        ed.setGeometry(fr)
        self.editing, self.editor = key, ed
        ed.show(); ed.setFocus()
        le = ed if isinstance(ed, QLineEdit) else ed.lineEdit()
        le.selectAll()
        QApplication.instance().installEventFilter(self)
        self.update()

    def eventFilter(self, obj, ev):
        ed = self.editor
        if ed is None:
            return False
        t = ev.type()
        if t == QEvent.KeyPress and ev.key() == Qt.Key_Escape:
            self.end_edit(False); return True
        if t == QEvent.MouseButtonPress and isinstance(obj, QWidget):
            inside = obj is ed or ed.isAncestorOf(obj)
            view = ed.view() if isinstance(ed, QComboBox) else None
            if view is not None and (obj is view or view.isAncestorOf(obj)
                                     or obj is view.window()):
                inside = True
            if not inside:
                self.end_edit(True)
        return False

    def end_edit(self, commit):
        ed, key = self.editor, self.editing
        if ed is None:
            return
        QApplication.instance().removeEventFilter(self)
        txt = (ed.text() if isinstance(ed, QLineEdit) else ed.currentText()).strip()
        ok = True
        if commit and txt != self.vals[key]:
            ok = self.host.commit_meta(key, txt)
        if not ok:
            self._shake_then_close(ed)
            return
        self.editor = self.editing = None
        ed.hide(); ed.deleteLater()
        if commit and txt != self.vals[key]:
            self.pulse(key)
        self.update()

    def _shake_then_close(self, ed):
        """越界: 输入框左右抖动 (4px ×3, 200ms) 后回退原值"""
        x0 = ed.x()
        a = QVariantAnimation(self)
        a.setDuration(200); a.setStartValue(0.0); a.setEndValue(1.0)
        a.valueChanged.connect(lambda v: ed.move(int(x0 + M.shake(v, 4.0, 3)), ed.y()))

        def done():
            if self.editor is ed:
                self.editor = self.editing = None
            ed.hide(); ed.deleteLater(); self.update()
        a.finished.connect(done)
        a.start(QVariantAnimation.DeleteWhenStopped)


# 工具栏按钮: (id, 文本/图标, 提示, 快捷键)
TOOLS = (('opt', '选项', '选项', 'O'), ('fold', '收起', '收起谱面', 'F'),
         ('play', None, '播放 / 暂停', 'Space'), ('stop', None, '停止', 'S'),
         ('min', None, '最小化', 'M'), ('close', None, '关闭', 'Ctrl+W'))
TEXT_W, ICON_W, BTN_H, PILL_PAD = 46.0, 30.0, 24.0, 4.0


class TopLayer(QWidget):
    """顶部交互层 (窗口坐标 0..BODY_Y): 进度条 + 悬停滑出的工具栏。
       光标位置 50ms 轮询判定悬停 (透明顶层窗口对全透明像素不收鼠标事件)"""
    def __init__(self, host):
        super().__init__(host)
        self.host = host
        self.show_t = Tween(0.0)                 # 工具栏显隐 0..1
        self.thick = Tween(0.0)                  # 进度条 4→8px
        self.hov, self.prs = {}, None            # 按钮悬停补间 / 按下 id
        self.hov_btn = None
        self.pos, self.total, self.playing = 0.0, 0.0, False
        self.t_icon = -1e9                       # 播放/暂停图标切换起点
        self.drag = False
        self.drag_q = 0.0
        self.in_bar = False
        self.clock = M.Clock(self, lambda _n: self.update(), self._busy)
        self._show_timer = QTimer(self); self._show_timer.setSingleShot(True)
        self._show_timer.timeout.connect(lambda: self.set_shown(True))
        self._hide_timer = QTimer(self); self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(lambda: self.set_shown(False))
        self._tip_timer = QTimer(self); self._tip_timer.setSingleShot(True)
        self._tip_timer.timeout.connect(self._show_tip)
        self._poll = QTimer(self); self._poll.setInterval(50)
        self._poll.timeout.connect(self._poll_hover)
        self.tip = Bubble(self.window())
        self.time_tip = Bubble(self.window())
        self.setMouseTracking(True)

    def _busy(self, now):
        return (self.show_t.busy(now) or self.thick.busy(now)
                or any(t.busy(now) for t in self.hov.values())
                or now - self.t_icon < M.PLAY_ICON + 20)

    @property
    def shown(self):
        return self.show_t.b > 0.5

    def set_shown(self, on):
        if on == self.shown:
            return
        now = self.clock.now()
        self.show_t.to(1.0 if on else 0.0, now, M.dur(M.PANEL),
                       M.ease_out if on else M.ease_in)
        if not on:
            self.tip.hide_now()
        self.clock.run()

    # ---- 几何 ----
    def pill(self):
        """工具栏: 在 BPM/节奏 元数据正上方滑出 (左缘与之对齐)"""
        w = sum(TEXT_W if t else ICON_W for _, t, _, _ in TOOLS) + 2 * PILL_PAD + 8
        x = float(META_X)
        lift = 0.0 if M.reduced() else 8.0 * (1 - self.show_t.value(self.clock.now()))
        return QRectF(x, PILL_Y + lift, w, BTN_H + 2 * PILL_PAD)

    def hover_zone(self):
        """工具栏 + 其下方 BPM 行 + 进度条带: 光标在此走廊内不收回 (经 BPM 行
           从进度条移到工具栏不会触发 400ms 收回)"""
        pr = self.pill()
        return QRectF(pr.x() - 6, pr.y() - 6, pr.width() + 12, BODY_Y - pr.y() + 8)

    def buttons(self):
        """[(id, rect)] —— 按钮固定尺寸, 图标切换不改布局"""
        pr = self.pill()
        x = pr.x() + PILL_PAD
        out = []
        for i, (bid, txt, _, _) in enumerate(TOOLS):
            w = TEXT_W if txt else ICON_W
            if i == 2:
                x += 8                           # 文字钮 / 图标钮之间的分隔
            out.append((bid, QRectF(x, pr.y() + PILL_PAD, w, BTN_H)))
            x += w
        return out

    def bar_rect(self):
        h = 4.0 + 4.0 * self.thick.value(self.clock.now())
        return QRectF(0, BODY_Y - h, self.width(), h)

    def _q_at(self, x):
        return M.clamp(x / max(1.0, self.width()))

    def sync(self, cur, total, playing):
        changed = playing != self.playing
        if changed:
            self.playing = playing
            self.t_icon = self.clock.now(); self.clock.run()
        if not self.drag and (abs(cur - self.pos) * self.width() > 0.4 * max(total, 1e-6)
                              or total != self.total):
            self.pos, self.total = cur, total
            self.update(0, BODY_Y - 12, self.width(), 12)
        elif changed:
            self.update()

    def _btn_at(self, pos):
        if self.show_t.value(self.clock.now()) < 0.6:
            return None
        return next((b for b, r in self.buttons() if r.contains(pos)), None)

    def paintEvent(self, ev):
        now = self.clock.now()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        # 悬停带: alpha=1 让透明顶层窗口在此处可收到光标 (视觉不可见)
        p.fillRect(QRectF(0, BODY_Y - BAR_Z, self.width(), BAR_Z), QColor(0, 0, 0, 1))
        a = self.show_t.value(now)
        if a > 0.01:
            p.save(); p.setOpacity(a)
            pr = self.pill()
            p.setBrush(QColor(M.PAPER)); p.setPen(QPen(QColor(M.INK), 1.2))
            p.drawRoundedRect(pr, 8, 8)
            for bid, r in self.buttons():
                self._paint_btn(p, bid, r, now)
            p.restore()
        # 进度条
        br = self.bar_rect()
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(210, 214, 220, 230))
        p.drawRoundedRect(br, br.height() / 2, br.height() / 2)
        q = self.drag_q if self.drag else (self.pos / self.total if self.total > 0 else 0.0)
        q = M.clamp(q)
        p.setBrush(QColor(M.BLUE))
        p.drawRoundedRect(QRectF(br.x(), br.y(), br.width() * q, br.height()),
                          br.height() / 2, br.height() / 2)
        t = self.thick.value(now)
        if t > 0.05:                             # 悬停: 拖动圆点
            p.setOpacity(t)
            c = QPointF(min(br.width() - 7, max(7.0, br.width() * q)), br.center().y())
            p.setBrush(QColor('#ffffff')); p.setPen(QPen(QColor(M.BLUE), 2.0))
            p.drawEllipse(c, 5.5, 5.5)
        p.end()

    def _paint_btn(self, p, bid, r, now):
        tw = self.hov.get(bid)
        h = tw.value(now) if tw is not None else 0.0
        pressed = self.prs == bid
        p.save()
        if not M.reduced():
            c = r.center()
            s = 0.95 if pressed else 1.0
            p.translate(c.x(), c.y() - h); p.scale(s, s); p.translate(-c.x(), -c.y())
        rr = r.adjusted(2, 2, -2, -2)
        p.setBrush(QColor(0, 0, 0, int(13 * h + (10 if pressed else 0))))
        p.setPen(Qt.NoPen)
        p.drawRoundedRect(rr, 5, 5)
        hot = QColor(M.RED) if bid == 'close' and h > 0.5 else QColor(M.INK)
        txt = next(t for b, t, _, _ in TOOLS if b == bid)
        if txt:
            p.setPen(hot); p.setFont(font(12))
            p.drawText(rr, Qt.AlignCenter, txt)
        else:
            self._paint_icon(p, bid, rr.center(), hot, now)
        p.restore()

    def _paint_icon(self, p, bid, c, color, now):
        s = 6.0                                  # 统一 12×12 图标框
        pen = QPen(color, 1.6); pen.setJoinStyle(Qt.RoundJoin); pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen); p.setBrush(Qt.NoBrush)
        if bid == 'play':
            # 新图标 -90°→0° 淡入, 旧图标 0°→90° 淡出 (同一图标框, 按钮不跳动)
            q = M.ease_out(M.clamp((now - self.t_icon) / M.dur(M.PLAY_ICON)))
            new = 'pause' if self.playing else 'play'
            old = 'play' if self.playing else 'pause'
            for icon, o, rot in ((new, q, -90 * (1 - q)), (old, 1 - q, 90 * q)):
                if o <= 0.01:
                    continue
                p.save()
                p.setOpacity(p.opacity() * o)
                if not M.reduced():
                    p.translate(c); p.rotate(rot); p.translate(-c)
                if icon == 'play':
                    path = QPainterPath()
                    path.moveTo(c.x() - s * 0.65, c.y() - s)
                    path.lineTo(c.x() + s * 0.95, c.y())
                    path.lineTo(c.x() - s * 0.65, c.y() + s)
                    path.closeSubpath()
                    p.drawPath(path)
                else:
                    for dx in (-s * 0.45, s * 0.45):
                        p.drawLine(QPointF(c.x() + dx, c.y() - s), QPointF(c.x() + dx, c.y() + s))
                p.restore()
        elif bid == 'stop':
            p.drawRect(QRectF(c.x() - s * 0.8, c.y() - s * 0.8, s * 1.6, s * 1.6))
        elif bid == 'min':
            p.drawLine(QPointF(c.x() - s, c.y()), QPointF(c.x() + s, c.y()))
        elif bid == 'close':
            d = s * 0.8
            p.drawLine(QPointF(c.x() - d, c.y() - d), QPointF(c.x() + d, c.y() + d))
            p.drawLine(QPointF(c.x() + d, c.y() - d), QPointF(c.x() - d, c.y() + d))

    # ---- 悬停: 光标轮询 (进度条 150ms → 滑出; 离开进度条与工具栏 400ms → 收回) ----
    def suspend(self, on):
        """选项菜单打开期间: 停悬停检测/提示气泡, 已弹出的立即隐藏 (不压到菜单上)"""
        self._suspended = bool(on)
        if on:
            for t in (self._show_timer, self._hide_timer, self._tip_timer):
                t.stop()
            self.tip.hide_now(); self.time_tip.hide_now()
            if self.hov_btn is not None:
                self._set_hover_btn(None)
            self.tip.hide_now()

    def _poll_hover(self):
        if not self.isVisible() or getattr(self, '_suspended', False):
            return
        pos = QPointF(self.mapFromGlobal(QCursor.pos()))
        in_bar = 0 <= pos.x() <= self.width() and BODY_Y - BAR_Z <= pos.y() <= BODY_Y + 2
        in_tool = self.shown and self.hover_zone().contains(pos)
        if in_bar != self.in_bar:
            self.in_bar = in_bar
            self.thick.to(1.0 if in_bar or self.drag else 0.0, self.clock.now(), M.MICRO)
            self.clock.run()
        if self.drag or in_bar or in_tool:
            self._hide_timer.stop()
            if in_bar and not self.shown and not self._show_timer.isActive():
                self._show_timer.start(M.BAR_HOVER)
        else:
            self._show_timer.stop()
            if self.shown and not self._hide_timer.isActive():
                self._hide_timer.start(M.BAR_HIDE)
        b = self._btn_at(pos) if in_tool else None
        if b != self.hov_btn:
            self._set_hover_btn(b)

    def _set_hover_btn(self, b):
        now = self.clock.now()
        if self.hov_btn is not None:
            self.hov[self.hov_btn].to(0, now, M.MICRO)
        self.hov_btn = b
        self.tip.hide_now()
        self._tip_timer.stop()
        if b is not None:
            self.hov.setdefault(b, Tween()).to(1, now, M.MICRO)
            self._tip_timer.start(M.TIP_DELAY)
        self.setCursor(Qt.PointingHandCursor if b else Qt.ArrowCursor)
        self.clock.run()

    def _show_tip(self):
        """按钮上方提示气泡: 功能名 + 快捷键"""
        b = self.hov_btn
        if b is None:
            return
        _, _, name, key = next(t for t in TOOLS if t[0] == b)
        r = dict(self.buttons())[b]
        self.tip.show_text('%s  (%s)' % (tr(name), key),
                           self.mapToGlobal(QPoint(int(r.center().x()), int(r.top()))))

    # ---- 点击 / 拖动 ----
    def _on_bar(self, pos):
        return BODY_Y - BAR_Z <= pos.y() <= BODY_Y + 2

    def mousePressEvent(self, ev):
        pos = ev.position()
        if ev.button() != Qt.LeftButton:
            ev.ignore(); return
        b = self._btn_at(pos)
        if b is not None:
            self.prs = b; self.update(); ev.accept(); return
        if self._on_bar(pos) and self.total > 0:
            self.drag = True
            self.drag_q = self._q_at(pos.x())
            self.host.seek_begin()
            self.host.seek_move(self.drag_q)
            self._time_tip(pos)
            self.update(); ev.accept(); return
        ev.ignore()                              # 空白处: 交给窗口拖动

    def mouseMoveEvent(self, ev):
        if self.drag:
            self.drag_q = self._q_at(ev.position().x())
            self.host.seek_move(self.drag_q)
            self._time_tip(ev.position())
            self.update(); ev.accept(); return
        ev.ignore()

    def mouseReleaseEvent(self, ev):
        if self.drag:
            self.drag = False
            self.host.seek_end(self.drag_q)
            self.pos = self.drag_q * self.total
            self.time_tip.hide_now()
            self.thick.to(1.0 if self.in_bar else 0.0, self.clock.now(), M.MICRO)
            self.clock.run(); ev.accept(); return
        b, self.prs = self.prs, None
        self.update()
        if b is not None and self._btn_at(ev.position()) == b:
            self.host.tool(b)
            ev.accept(); return
        ev.ignore()

    def _time_tip(self, pos):
        """拖动时间气泡: 当前时间 / 总时长"""
        cur = self.drag_q * self.total
        self.time_tip.show_text('%s / %s' % (fmt_sec(cur), fmt_sec(self.total)),
                                self.mapToGlobal(QPoint(int(pos.x()), int(BODY_Y - 10))))

    def showEvent(self, ev):
        self._poll.start(); super().showEvent(ev)

    def hideEvent(self, ev):
        self._poll.stop(); self.tip.hide_now(); self.time_tip.hide_now()
        super().hideEvent(ev)


class ScoreFloat(QWidget):
    """悬浮乐谱窗口 (独立顶层, 置顶, 任务栏可见以便最小化)。
       主窗接口: strip / refresh_meta / sync_progress / refresh_page_fit /
       set_key_label / _apply_bpm / _apply_tsig / _rows"""
    def __init__(self, roll, mw):
        super().__init__(None, Qt.Window | Qt.FramelessWindowHint
                         | Qt.WindowStaysOnTopHint)
        self.mw = mw
        self.setWindowTitle(tr('谱面·跟弹-播放示范'))
        self.setObjectName('ScoreFloat')
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.key_label = str(getattr(mw, 'key_label', '1=C'))
        self._drag_off = None
        self.folded = False
        self._fold_h = None                      # 折叠动画中的当前高
        self._fold_anim = None
        self.overlay = None                      # 选项径向菜单 (惰性创建)
        self.strip = FloatStrip(roll, mw, parent=self)    # 复用渲染组件 (同一 QML)
        self.strip.interactive = False           # 只读: 不接手势
        self.strip.setToolTip('')
        self.layer = TopLayer(self)
        self.meta = MetaChip(self)
        self.lb_bpm = _TextRef(lambda: self.meta.vals['bpm'])
        self.lb_ts = _TextRef(lambda: self.meta.vals['ts'])
        self._rows = store.load_score_rows()
        self.strip.set_rows(self._rows)
        self.apply_display(push=False)
        for bid, _, _, key in TOOLS:             # 窗口内快捷键 (提示气泡同文案)
            sc = QShortcut(QKeySequence(key), self)
            sc.activated.connect(lambda b=bid: self.tool(b))
        self._sync = QTimer(self); self._sync.setInterval(120)
        self._sync.timeout.connect(self._sync_tick)
        self._apply_rows_size()

    # ---- 尺寸 / 显示设置 ----
    def body_h(self):
        row_h = max(80, int(getattr(self.mw, 'score_row_h', ROW_H_PX)))
        return self._rows * row_h

    def _full_h(self):
        return BODY_Y + self.body_h() + 1

    def _apply_rows_size(self):
        """宽 = 设置 score_float_w; 高 = 工具栏区 + 进度条带 + 排数 × score_row_h"""
        w = max(600, int(getattr(self.mw, 'score_float_w', 1020)))
        h = BODY_Y + 1 if self.folded else self._full_h()
        if self._fold_h is not None:
            h = int(self._fold_h)
        self.setFixedSize(w, h)
        self.strip.setGeometry(1, BODY_Y, w - 2, self.body_h())
        self.layer.setGeometry(0, 0, w, BODY_Y)
        self.meta.move(META_X, META_Y)
        self.layer.raise_(); self.meta.raise_()
        self.update()

    def refresh_page_fit(self):
        """设置变化 (排高/宽度/每页小节数/轨名) → 重算窗口尺寸并重推数据"""
        self.apply_display()

    def apply_display(self, push=True):
        """轨名栏宽随「音轨名称」字号; 皮肤 透明/不透明"""
        self.strip.kb_w = label_width(getattr(self.mw, 'strip_name_font', 7))
        self.strip.skin_clear = getattr(self.mw, 'score_skin', 'opaque') == 'clear'
        self._apply_rows_size()
        if push:
            self.strip.update()

    def set_rows(self, n):
        n = max(1, min(4, int(n)))
        if n == self._rows:
            return
        self._rows = n
        store.save_score_rows(n)
        self.strip.set_rows(n)
        self._apply_rows_size()

    def paintEvent(self, ev):
        p = QPainter(self)
        body = QRectF(0.5, BODY_Y - 0.5, self.width() - 1, self.height() - BODY_Y)
        if body.height() > 1:
            if self.strip.skin_clear:
                p.fillRect(body, QColor(0, 0, 0, 1))   # 透明皮肤: 仍可拖动 / 悬停
            else:
                p.setBrush(QColor(M.PAPER)); p.setPen(QPen(QColor('#9aa0a8'), 1.0))
                p.drawRect(body)
        p.end()

    # ---- 播放 / 进度 (主窗 PlaybackController 既有接口) ----
    def sync_progress(self, cur, total, playing):
        self.layer.sync(float(cur), float(total), bool(playing))

    def _sync_tick(self):
        mw = self.mw
        self.sync_progress(mw.cur_sec, mw.total_sec, mw._is_playing())

    def seek_begin(self):
        self.mw._slider_pressed()

    def seek_move(self, q):
        mw = self.mw
        mw.slider.blockSignals(True)
        mw.slider.setValue(int(round(q * 1000)))
        mw.slider.blockSignals(False)
        mw._slider_moved(int(round(q * 1000)))   # 视觉跳转: 谱面同步滚动到对应位置

    def seek_end(self, q):
        mw = self.mw
        mw.slider.blockSignals(True)
        mw.slider.setValue(int(round(q * 1000)))
        mw.slider.blockSignals(False)
        mw._slider_released()

    # ---- 工具栏 ----
    def tool(self, bid):
        if bid == 'opt':
            self.open_options()
        elif bid == 'fold':
            self.toggle_fold()
        elif bid == 'play':
            self.mw.toggle_play()
            self._sync_tick()
        elif bid == 'stop':
            self.mw.stop_all()                   # 暂停 + 进度归零
            self._sync_tick()
        elif bid == 'min':
            self.showMinimized()
        elif bid == 'close':
            self.request_close()

    def toggle_fold(self):
        """收起: 谱面折叠为只剩进度条和工具栏; 再次点击展开 (高度过渡 240ms)"""
        self.folded = not self.folded
        a0 = self.height()
        a1 = BODY_Y + 1 if self.folded else self._full_h()
        if self._fold_anim is not None:
            self._fold_anim.stop()
        anim = QVariantAnimation(self)
        anim.setDuration(M.dur(M.PANEL))
        anim.setStartValue(0.0); anim.setEndValue(1.0)   # 线性进度, 缓动在 Python 侧
        ease = M.ease_in if self.folded else M.ease_out

        def step(v):
            self._fold_h = a0 + (a1 - a0) * ease(float(v))
            self._apply_rows_size()

        def done():
            self._fold_h = None
            self._apply_rows_size()
        anim.valueChanged.connect(step)
        anim.finished.connect(done)
        self._fold_anim = anim
        anim.start()

    def request_close(self):
        """关闭: 有未保存修改时先二次确认"""
        sess = getattr(self.mw, 'edit_session', None)
        if sess is not None and getattr(sess, 'dirty', False):
            ret = QMessageBox.question(
                self, tr('关闭乐谱'),
                tr('编辑器中有未保存的修改。\n确定关闭悬浮乐谱吗? (修改仍保留在编辑器中)'),
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if ret != QMessageBox.Yes:
                return False
        self.hide()
        return True

    # ---- BPM / 节奏 (沿用原有应用逻辑) ----
    def commit_meta(self, key, txt):
        """MetaChip 确认: 返回 False = 输入非法 (输入框抖动后回退原值)"""
        if self.mw.tmap is None:
            return False
        if key == 'bpm':
            try:
                v = float(txt)
            except ValueError:
                return False
            if not 20.0 <= v <= 300.0:
                return False
            self._apply_bpm(v)
            return True
        try:
            n, d = (int(x) for x in txt.replace(' ', '').split('/'))
        except ValueError:
            return False
        if not (1 <= n <= 16 and d in (1, 2, 4, 8, 16, 32)):
            return False
        self._apply_tsig(n, d)
        return True

    def _meta_tick(self):
        """BPM 取值位置 = 悬浮谱卷帘当前指针 (无指针 = 0)"""
        t = self.strip.roll.playhead_tick
        return max(0.0, float(t)) if t is not None else 0.0

    def refresh_meta(self, ph=None):
        mw = self.mw
        if mw.tmap is None:
            return
        t = self._meta_tick() if ph is None else max(0.0, float(ph))
        ts = '%d/%d' % tuple(getattr(mw, 'tsig', (4, 4)))
        self.meta.set_values('%.0f' % mw.tmap.bpm_at_tick(t), ts)

    def _apply_bpm(self, bpm):
        """BPM 应用: 指针处已有速度事件 = 改写, 否则插入 (有编辑会话走 model 可撤销)"""
        mw = self.mw
        t = self._meta_tick()
        if getattr(mw, 'edit_session', None) is not None:
            if t in mw.tmap.ticks:
                mw.model.tempo_set(mw.tmap.ticks.index(t), bpm)
            else:
                mw.model.tempo_insert(t, bpm)
        else:
            if t in mw.tmap.ticks:
                mw.tmap.set_bpm_index(mw.tmap.ticks.index(t), bpm)
            else:
                mw.tmap.insert_event(t, bpm)
            mw._apply_tempo_change()
        self.refresh_meta()

    def _apply_tsig(self, num, den):
        self.mw._set_time_signature(num, den)
        self.refresh_meta()

    def _edit_bpm(self):
        self.meta.begin_edit('bpm')

    def _edit_tsig(self):
        self.meta.begin_edit('ts')

    def set_key_label(self, text):
        self.key_label = str(text)

    # ---- 选项径向菜单 ----
    def open_options(self):
        from options_radial import OptionsOverlay
        if self.overlay is None:
            self.overlay = OptionsOverlay(self)
        self.overlay.open()

    # ---- 窗口拖动 (空白处/谱面按住即可移动; 进度条与按钮各自消费) ----
    def mousePressEvent(self, ev):
        if ev.button() == Qt.LeftButton:
            self._drag_off = ev.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, ev):
        if self._drag_off is not None and ev.buttons() & Qt.LeftButton:
            self.move(ev.globalPosition().toPoint() - self._drag_off)

    def mouseReleaseEvent(self, ev):
        self._drag_off = None

    def showEvent(self, ev):
        self._sync.start()
        super().showEvent(ev)

    def hideEvent(self, ev):
        self._sync.stop()
        if self.overlay is not None and self.overlay.isVisible():
            self.overlay.close_now()
        mw = self.mw
        if getattr(mw, '_score_float_hidden', None) is not None:
            mw._score_float_hidden()
        super().hideEvent(ev)
