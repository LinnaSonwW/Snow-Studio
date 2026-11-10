# -*- coding: utf-8 -*-
"""主窗顶栏自绘控件: 菱形菜单簇 / 歌曲条 / 八边形播放键 /
   BPM 盒 / 提示面板 / 添加音轨。尺寸对齐参照图1。"""
import math
from PySide6.QtCore import Qt, Signal, QRectF, QPointF
from PySide6.QtGui import (QPainter, QColor, QPen, QFont, QPolygonF,
                           QFontMetrics, QRegion)
from PySide6.QtWidgets import QWidget, QAbstractButton


_LINE = QColor(230, 234, 240, 220)
_STROKE = 0.5                               # 按钮外框极细白线
_ACCENT = QColor(232, 176, 90)
_TIP = QColor(90, 210, 120)
_MUTE_ON = QColor(70, 200, 110)
_KEYS_ON = QColor(70, 150, 230)

BAR_H = 52
BTN_S = 52
TRANSPORT_GAP = 10
MID_ROW_GAP = 10
BPM_W = 220
SONG_W = 420
TIPS_H = BAR_H + MID_ROW_GAP + BAR_H
TIPS_W = 280


def _diamond(cx, cy, r):
    return QPolygonF([
        QPointF(cx, cy - r), QPointF(cx + r, cy),
        QPointF(cx, cy + r), QPointF(cx - r, cy)])


def _hexagon(cx, cy, rx, ry):
    return QPolygonF([
        QPointF(cx - rx, cy),
        QPointF(cx - rx * 0.55, cy - ry),
        QPointF(cx + rx * 0.55, cy - ry),
        QPointF(cx + rx, cy),
        QPointF(cx + rx * 0.55, cy + ry),
        QPointF(cx - rx * 0.55, cy + ry)])


class DiamondBtn(QAbstractButton):
    def __init__(self, text, tip='', shortcut='', parent=None):
        super().__init__(parent)
        self.setText(text)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)
        self.setFixedSize(72, 72)
        self._hover = False
        self.tip_text = tip
        self.shortcut_text = shortcut
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAutoFillBackground(False)

    def _diamond_poly(self):
        cx, cy = self.width() / 2, self.height() / 2
        r = min(self.width(), self.height()) * 0.42
        return _diamond(cx, cy, r)

    def resizeEvent(self, e):
        # 仅菱形可点/可画, 避免 72×72 方框互相遮挡破坏矩阵
        self.setMask(QRegion(self._diamond_poly().toPolygon()))
        super().resizeEvent(e)

    def showEvent(self, e):
        self.setMask(QRegion(self._diamond_poly().toPolygon()))
        super().showEvent(e)

    def enterEvent(self, e):
        self._hover = True; self.update(); super().enterEvent(e)

    def leaveEvent(self, e):
        self._hover = False; self.update(); super().leaveEvent(e)

    def paintEvent(self, _ev):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        poly = self._diamond_poly()
        fill_a = 40 if self.isChecked() else (28 if self._hover or self.isDown() else 10)
        p.setBrush(QColor(255, 255, 255, fill_a))
        p.setPen(QPen(_LINE if not self.isChecked() else QColor(232, 176, 90), _STROKE))
        p.drawPolygon(poly)
        p.setPen(QColor(235, 238, 245))
        p.setFont(QFont('Segoe UI', 10))
        p.drawText(self.rect(), Qt.AlignCenter, self.text())


class GearBtn(QAbstractButton):
    """中央设置: 小菱形外框 + 齿轮 (对齐矩阵中心)。"""

    def __init__(self, tip='', shortcut='', parent=None):
        super().__init__(parent)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)
        self.setFixedSize(40, 40)
        self._hover = False
        self.tip_text = tip
        self.shortcut_text = shortcut
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAutoFillBackground(False)

    def _diamond_poly(self):
        cx, cy = self.width() / 2, self.height() / 2
        return _diamond(cx, cy, 15.0)

    def resizeEvent(self, e):
        self.setMask(QRegion(self._diamond_poly().toPolygon()))
        super().resizeEvent(e)

    def showEvent(self, e):
        self.setMask(QRegion(self._diamond_poly().toPolygon()))
        super().showEvent(e)

    def enterEvent(self, e):
        self._hover = True; self.update(); super().enterEvent(e)

    def leaveEvent(self, e):
        self._hover = False; self.update(); super().leaveEvent(e)

    def paintEvent(self, _ev):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        cx, cy = self.width() / 2, self.height() / 2
        poly = self._diamond_poly()
        # 参照图: 中心菱形偏实心白
        fill = QColor(255, 255, 255, 210 if self._hover else 175)
        p.setBrush(fill)
        p.setPen(QPen(_LINE, _STROKE))
        p.drawPolygon(poly)
        # 深色齿轮
        p.setPen(QPen(QColor(40, 42, 48), 1.2))
        p.setBrush(Qt.NoBrush)
        teeth = 8
        for i in range(teeth):
            a0 = math.radians(i * 360 / teeth - 10)
            a1 = math.radians(i * 360 / teeth + 10)
            mid = (a0 + a1) * 0.5
            p.drawLine(QPointF(cx + 5.5 * math.cos(a0), cy + 5.5 * math.sin(a0)),
                       QPointF(cx + 8.2 * math.cos(mid), cy + 8.2 * math.sin(mid)))
            p.drawLine(QPointF(cx + 8.2 * math.cos(mid), cy + 8.2 * math.sin(mid)),
                       QPointF(cx + 5.5 * math.cos(a1), cy + 5.5 * math.sin(a1)))
        p.setBrush(QColor(40, 42, 48))
        p.drawEllipse(QPointF(cx, cy), 4.2, 4.2)
        p.setBrush(fill)
        p.drawEllipse(QPointF(cx, cy), 2.0, 2.0)


class DiamondCluster(QWidget):
    """四向菱形 + 中央齿轮: 悬浮/文件/编曲/保存 等距十字, 尖端贴近中心。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAutoFillBackground(False)
        self.b_file = DiamondBtn('文件')     # 左
        self.b_float = DiamondBtn('悬浮')    # 上
        self.b_edit = DiamondBtn('编曲')     # 右
        self.b_save = DiamondBtn('保存')     # 下
        self.b_gear = GearBtn()              # 中
        for b in (self.b_file, self.b_float, self.b_edit, self.b_save, self.b_gear):
            b.setParent(self)
        self._place()

    def _place(self):
        # DiamondBtn 72×72, 可视半对角 r≈30.2; 略留缝, 尖端不叠线
        bw = self.b_file.width()
        bh = self.b_file.height()
        gw, gh = self.b_gear.width(), self.b_gear.height()
        r = min(bw, bh) * 0.42
        d = r + 7.0                          # 中心 → 各大菱形中心
        side = int(round(2 * (d + bw * 0.5) + 4))
        self.setFixedSize(side, side)
        cx = side * 0.5
        cy = side * 0.5

        def _tl(ox, oy, w, h):
            return round(ox - w * 0.5), round(oy - h * 0.5)

        self.b_float.move(*_tl(cx, cy - d, bw, bh))   # 上
        self.b_file.move(*_tl(cx - d, cy, bw, bh))    # 左
        self.b_edit.move(*_tl(cx + d, cy, bw, bh))    # 右
        self.b_save.move(*_tl(cx, cy + d, bw, bh))    # 下
        self.b_gear.move(*_tl(cx, cy, gw, gh))        # 中
        self.b_gear.raise_()

    def resizeEvent(self, e):
        self._place(); super().resizeEvent(e)


class StatusDiamond(QAbstractButton):
    def __init__(self, on_color, tip='', shortcut='', parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)
        self.setFixedSize(18, 18)
        self._on = QColor(on_color)
        self._hover = False
        self.tip_text = tip
        self.shortcut_text = shortcut

    def enterEvent(self, e):
        self._hover = True; self.update(); super().enterEvent(e)

    def leaveEvent(self, e):
        self._hover = False; self.update(); super().leaveEvent(e)

    def paintEvent(self, _ev):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        cx, cy = self.width() / 2, self.height() / 2
        poly = _diamond(cx, cy, 6.5)
        if self.isChecked():
            p.setBrush(self._on)
            p.setPen(QPen(self._on.lighter(120), _STROKE))
        else:
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(self._on if self._hover else _LINE, _STROKE))
        p.drawPolygon(poly)


class HexIconBtn(QAbstractButton):
    """播放/停止: 八边形外框 (参照图1)"""
    def __init__(self, kind, tip='', shortcut='', parent=None):
        super().__init__(parent)
        self.kind = kind
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)
        self.setFixedSize(BTN_S, BAR_H)
        self._hover = False
        self.tip_text = tip
        self.shortcut_text = shortcut
        self._playing = False

    def set_playing(self, on):
        on = bool(on)
        if on != self._playing:
            self._playing = on; self.update()

    def enterEvent(self, e):
        self._hover = True; self.update(); super().enterEvent(e)

    def leaveEvent(self, e):
        self._hover = False; self.update(); super().leaveEvent(e)

    def paintEvent(self, _ev):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        cx, cy = self.width() / 2, self.height() / 2
        rx, ry = self.width() / 2 - 2, self.height() / 2 - 2
        cut = min(rx, ry) * 0.28
        octo = QPolygonF([
            QPointF(cx - rx + cut, cy - ry),
            QPointF(cx + rx - cut, cy - ry),
            QPointF(cx + rx, cy - ry + cut),
            QPointF(cx + rx, cy + ry - cut),
            QPointF(cx + rx - cut, cy + ry),
            QPointF(cx - rx + cut, cy + ry),
            QPointF(cx - rx, cy + ry - cut),
            QPointF(cx - rx, cy - ry + cut),
        ])
        p.setBrush(QColor(255, 255, 255, 28 if self._hover or self.isDown() else 8))
        p.setPen(QPen(_LINE, _STROKE))
        p.drawPolygon(octo)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(240, 244, 250))
        if self.kind == 'play':
            if self._playing:
                p.drawRect(QRectF(cx - 6, cy - 7, 4, 14))
                p.drawRect(QRectF(cx + 2, cy - 7, 4, 14))
            else:
                p.drawPolygon(QPolygonF([
                    QPointF(cx - 5, cy - 8),
                    QPointF(cx + 8, cy),
                    QPointF(cx - 5, cy + 8)]))
        else:
            p.drawRect(QRectF(cx - 6, cy - 6, 12, 12))


class SongBar(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(SONG_W, BAR_H)
        self._name = ''
        self.b_mute = StatusDiamond(_MUTE_ON)
        self.b_keys = StatusDiamond(_KEYS_ON)
        self.b_mute.setParent(self)
        self.b_keys.setParent(self)

    def set_song_name(self, name):
        self._name = name or ''
        self.update()

    def resizeEvent(self, e):
        x = self.width() - 26
        cy = self.height() / 2
        self.b_mute.move(x, int(cy - 15))
        self.b_keys.move(x, int(cy + 1))
        super().resizeEvent(e)

    def paintEvent(self, _ev):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(1, 1, self.width() - 2, self.height() - 2)
        p.setBrush(QColor(255, 255, 255, 10))
        p.setPen(QPen(_LINE, _STROKE))
        p.drawRoundedRect(r, 28, 28)
        f = QFont('Segoe UI', 11)
        p.setFont(f)
        p.setPen(_ACCENT)
        label = '歌曲：'
        p.drawText(QRectF(14, 0, 60, self.height()),
                   Qt.AlignVCenter | Qt.AlignLeft, label)
        fm = QFontMetrics(f)
        lx = 14 + fm.horizontalAdvance(label) + 4
        p.setPen(QColor(230, 234, 240))
        elide = fm.elidedText(self._name, Qt.ElideRight,
                              max(40, self.width() - lx - 40))
        p.drawText(QRectF(lx, 0, self.width() - lx - 36, self.height()),
                   Qt.AlignVCenter | Qt.AlignLeft, elide)


class BpmBox(QWidget):
    valueChanged = Signal(int)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(BPM_W, BAR_H)
        self._val = 120

    def value(self):
        return self._val

    def setValue(self, v):
        v = max(20, min(400, int(v)))
        if v != self._val:
            self._val = v; self.update()

    def setRange(self, lo, hi):
        self._lo, self._hi = int(lo), int(hi)

    def blockSignals(self, b):
        return super().blockSignals(b)

    def mousePressEvent(self, e):
        if e.button() != Qt.LeftButton: return
        if self._hit_up(e.position()):
            self.setValue(self._val + 1); self.valueChanged.emit(self._val)
        elif self._hit_dn(e.position()):
            self.setValue(self._val - 1); self.valueChanged.emit(self._val)

    def wheelEvent(self, e):
        d = 1 if e.angleDelta().y() > 0 else -1
        self.setValue(self._val + d); self.valueChanged.emit(self._val)

    def _hit_up(self, pos):
        return pos.x() > self.width() - 28 and pos.y() < self.height() / 2

    def _hit_dn(self, pos):
        return pos.x() > self.width() - 28 and pos.y() >= self.height() / 2

    def paintEvent(self, _ev):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(1, 1, self.width() - 2, self.height() - 2)
        p.setBrush(QColor(255, 255, 255, 10))
        p.setPen(QPen(_LINE, _STROKE))
        p.drawRoundedRect(r, 28, 28)
        f = QFont('Segoe UI', 11)
        p.setFont(f)
        p.setPen(_ACCENT)
        p.drawText(QRectF(14, 0, self.width() - 40, self.height()),
                   Qt.AlignVCenter | Qt.AlignLeft, f'BPM : {self._val}')
        ax = self.width() - 18
        mid = self.height() / 2
        p.setPen(Qt.NoPen); p.setBrush(_LINE)
        p.drawPolygon(QPolygonF([
            QPointF(ax, mid - 11), QPointF(ax - 6, mid - 3), QPointF(ax + 6, mid - 3)]))
        p.drawPolygon(QPolygonF([
            QPointF(ax, mid + 11), QPointF(ax - 6, mid + 3), QPointF(ax + 6, mid + 3)]))


class TipsPanel(QWidget):
    """高=歌曲+间隔+BPM; 宽近方形 (参照图1)"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self._tip = ''
        self._shortcut = ''
        self.setFixedSize(TIPS_W, TIPS_H)

    def apply_size(self, win_w=None):
        self.setFixedSize(TIPS_W, TIPS_H)

    def clear_tips(self):
        self.set_tips('', '')

    def set_tips(self, tip, shortcut):
        tip = tip or ''
        shortcut = shortcut or ''
        if tip != self._tip or shortcut != self._shortcut:
            self._tip, self._shortcut = tip, shortcut
            self.update()

    def paintEvent(self, _ev):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(1, 1, self.width() - 2, self.height() - 2)
        p.setBrush(QColor(255, 255, 255, 8))
        p.setPen(QPen(_LINE, _STROKE))
        p.drawRoundedRect(r, 28, 28)
        if not self._tip and not self._shortcut:
            return
        f = QFont('Segoe UI', 10)
        p.setFont(f)
        p.setPen(_TIP)
        half = self.height() / 2
        if self._tip:
            p.drawText(QRectF(14, 4, self.width() - 28, half - 6),
                       Qt.AlignVCenter | Qt.AlignLeft, self._tip)
        if self._shortcut:
            p.drawText(QRectF(14, half, self.width() - 28, half - 4),
                       Qt.AlignVCenter | Qt.AlignLeft, self._shortcut)


class ArrowCaptionBtn(QAbstractButton):
    """窗控箭头按钮 (参照图1 横向并排)"""
    def __init__(self, kind, tip='', parent=None):
        super().__init__(parent)
        self.kind = kind
        self.setFixedSize(40, 32)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)
        self.tip_text = tip
        self.shortcut_text = ''
        self._hover = False

    def enterEvent(self, e):
        self._hover = True; self.update(); super().enterEvent(e)

    def leaveEvent(self, e):
        self._hover = False; self.update(); super().leaveEvent(e)

    def paintEvent(self, _ev):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        poly = QPolygonF([
            QPointF(2, 2), QPointF(w - 11, 2), QPointF(w - 2, h / 2),
            QPointF(w - 11, h - 2), QPointF(2, h - 2)])
        hot = self.kind == 'close' and self._hover
        fill = QColor(200, 60, 70, 180) if hot else QColor(255, 255, 255, 20 if self._hover else 8)
        p.setBrush(fill)
        p.setPen(QPen(_LINE, _STROKE))
        p.drawPolygon(poly)
        p.setPen(QPen(QColor(245, 248, 252), 1.2))
        if self.kind == 'min':
            p.drawLine(QPointF(10, h / 2), QPointF(w - 15, h / 2))
        else:
            p.drawLine(QPointF(11, 9), QPointF(w - 16, h - 9))
            p.drawLine(QPointF(w - 16, 9), QPointF(11, h - 9))


class AddTrackBtn(QAbstractButton):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setText('添加音轨')
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)
        self.setFixedSize(160, 32)
        self._hover = False
        self.tip_text = ''
        self.shortcut_text = ''

    def enterEvent(self, e):
        self._hover = True; self.update(); super().enterEvent(e)

    def leaveEvent(self, e):
        self._hover = False; self.update(); super().leaveEvent(e)

    def paintEvent(self, _ev):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        cx, cy = self.width() / 2, self.height() / 2
        poly = _hexagon(cx, cy, self.width() / 2 - 2, self.height() / 2 - 3)
        p.setBrush(QColor(255, 255, 255, 24 if self._hover else 8))
        p.setPen(QPen(_LINE, _STROKE))
        p.drawPolygon(poly)
        p.setPen(QColor(235, 238, 245))
        p.setFont(QFont('Segoe UI', 10))
        p.drawText(self.rect(), Qt.AlignCenter, self.text())


class TipHoverFilter:
    def __init__(self, panel):
        self.panel = panel
        self._filters = []

    def bind(self, widget):
        from PySide6.QtCore import QObject, QEvent

        class _F(QObject):
            def __init__(self, w, panel):
                QObject.__init__(self, w)
                self.w, self.panel = w, panel
            def eventFilter(self, obj, ev):
                if ev.type() == QEvent.Enter:
                    self.panel.set_tips(getattr(self.w, 'tip_text', '') or '',
                                        getattr(self.w, 'shortcut_text', '') or '')
                elif ev.type() == QEvent.Leave:
                    self.panel.clear_tips()
                return False
        f = _F(widget, self.panel)
        widget.installEventFilter(f)
        self._filters.append(f)
