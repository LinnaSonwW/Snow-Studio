# -*- coding: utf-8 -*-
"""编辑器工具指针 (统一风格): 指针位图与工具指示框图标共用同一绘制函数 draw_glyph。
   规则: 深色外描边 + 白色主体, 每种工具一处强调色; 逻辑画布 24px, 按屏幕缩放
   (devicePixelRatio) × 指针大小 (标准 1.0 / 大 1.5) 生成位图, 边缘恒锐利。
   主体两类: 准星 = 需要对准格子的操作 (画笔 / 框选 / 删除, 热点 = 准星中心);
   箭头 = 作用于已有音符的操作 (选择 / 移动 / 复制, 热点 = 箭头尖)。
   选择工具另有「四角括号 + 中心落点」样式 (设置切换, 热点 = 落点)。"""
from PySide6.QtCore import Qt, QPointF, QRectF
from PySide6.QtGui import QColor, QPen, QPainter, QPixmap, QCursor, QPolygonF

OUTLINE = QColor(12, 14, 18, 235)
BODY = QColor(255, 255, 255)
ACCENT = {'pencil': QColor('#ffc15a'), 'erase': QColor('#ff5a5a'),
          'copy': QColor('#3fd07a')}
SIZE_MULT = {'standard': 1.0, 'large': 1.5}
SELECT_STYLES = ('arrow', 'bracket')
KINDS = ('pencil', 'select', 'move', 'copy', 'rubber', 'erase')
CROSS = QPointF(8.0, 8.0)             # 准星中心 (热点)
ARROW_TIP = QPointF(3.0, 2.0)         # 箭头尖 (热点)


def _line(p, a, b, w=1.5, body=BODY):
    """两遍描边: 深色宽笔打底 + 主体细笔 (深浅背景都清晰)"""
    p.setPen(QPen(OUTLINE, w + 2.0, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.drawLine(a, b)
    p.setPen(QPen(body, w, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.drawLine(a, b)


def _fill(p, poly, body=BODY):
    """封闭图形: 深色描边 + 主体填充"""
    p.setPen(QPen(OUTLINE, 1.6, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.setBrush(body)
    p.drawPolygon(poly)


def _crosshair(p, c=CROSS):
    """准星: 四臂留空中心 (不遮挡落点) + 1px 中心点"""
    gap, arm = 2.5, 7.0
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        _line(p, QPointF(c.x() + dx * gap, c.y() + dy * gap),
              QPointF(c.x() + dx * arm, c.y() + dy * arm))
    p.setPen(Qt.NoPen)
    p.setBrush(OUTLINE); p.drawEllipse(c, 1.6, 1.6)
    p.setBrush(BODY); p.drawEllipse(c, 0.8, 0.8)


def _arrow(p):
    t = ARROW_TIP
    _fill(p, QPolygonF([t, QPointF(3.0, 15.5), QPointF(6.4, 12.4),
                        QPointF(8.8, 17.4), QPointF(11.0, 16.4),
                        QPointF(8.7, 11.5), QPointF(13.0, 11.5)]))


def _bracket(p, c=CROSS):
    """四角括号 + 中心落点 (选择工具备选样式)"""
    h, L = 6.0, 3.0
    for sx, sy in ((-1, -1), (1, -1), (-1, 1), (1, 1)):
        k = QPointF(c.x() + sx * h, c.y() + sy * h)
        _line(p, k, QPointF(k.x() - sx * L, k.y()))
        _line(p, k, QPointF(k.x(), k.y() - sy * L))
    p.setPen(Qt.NoPen)
    p.setBrush(OUTLINE); p.drawEllipse(c, 2.2, 2.2)
    p.setBrush(BODY); p.drawEllipse(c, 1.2, 1.2)

# ---------- 角标 (右下 / 右上区域, 不压准星中心与箭头尖) ----------
def _badge_pencil(p):
    """小笔: 笔尖朝左上 (指向准星)"""
    _line(p, QPointF(21.5, 12.5), QPointF(16.5, 17.5), 2.4)
    _fill(p, QPolygonF([QPointF(14.2, 19.8), QPointF(15.3, 16.7),
                        QPointF(17.3, 18.7)]), ACCENT['pencil'])


def _badge_rubber(p):
    """虚线小方框 (框选)"""
    r = QRectF(14.5, 14.5, 7.5, 7.5)
    p.setBrush(Qt.NoBrush)
    p.setPen(QPen(OUTLINE, 3.2)); p.drawRect(r)
    pen = QPen(BODY, 1.4, Qt.CustomDashLine); pen.setDashPattern([2.0, 1.6])
    p.setPen(pen); p.drawRect(r)


def _badge_erase(p):
    """红色禁止符 (删除)"""
    c = QPointF(18.0, 18.0)
    p.setPen(QPen(OUTLINE, 4.0)); p.setBrush(Qt.NoBrush); p.drawEllipse(c, 4.2, 4.2)
    p.setPen(QPen(ACCENT['erase'], 1.8)); p.drawEllipse(c, 4.2, 4.2)
    _line(p, QPointF(15.2, 20.8), QPointF(20.8, 15.2), 1.8, ACCENT['erase'])


def _badge_select(p):
    """四角括号 (选择)"""
    c, h, L = QPointF(18.5, 18.5), 3.6, 2.0
    for sx, sy in ((-1, -1), (1, -1), (-1, 1), (1, 1)):
        k = QPointF(c.x() + sx * h, c.y() + sy * h)
        _line(p, k, QPointF(k.x() - sx * L, k.y()), 1.3)
        _line(p, k, QPointF(k.x(), k.y() - sy * L), 1.3)


def _badge_move(p):
    """四向移动箭头"""
    c, r = QPointF(18.0, 18.0), 4.6
    _line(p, QPointF(c.x() - r, c.y()), QPointF(c.x() + r, c.y()), 1.3)
    _line(p, QPointF(c.x(), c.y() - r), QPointF(c.x(), c.y() + r), 1.3)
    a = 1.9
    for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        tip = QPointF(c.x() + dx * (r + 1.2), c.y() + dy * (r + 1.2))
        bx, by = c.x() + dx * (r - 1.0), c.y() + dy * (r - 1.0)
        _fill(p, QPolygonF([tip, QPointF(bx + dy * a, by + dx * a),
                            QPointF(bx - dy * a, by - dx * a)]))


def _badge_copy(p):
    """绿色圆 + 白色加号 (Ctrl 复制)"""
    c = QPointF(18.5, 18.5)
    p.setPen(QPen(OUTLINE, 1.6)); p.setBrush(ACCENT['copy']); p.drawEllipse(c, 4.4, 4.4)
    p.setPen(QPen(BODY, 1.6, Qt.SolidLine, Qt.RoundCap))
    p.drawLine(QPointF(c.x() - 2.3, c.y()), QPointF(c.x() + 2.3, c.y()))
    p.drawLine(QPointF(c.x(), c.y() - 2.3), QPointF(c.x(), c.y() + 2.3))


_BADGE = {'pencil': _badge_pencil, 'rubber': _badge_rubber, 'erase': _badge_erase,
          'select': _badge_select, 'move': _badge_move, 'copy': _badge_copy}


def draw_glyph(p, kind, select_style='arrow'):
    """在 24×24 逻辑坐标内画一种工具图形 (指针位图 / 工具指示框共用)"""
    if kind == 'select' and select_style == 'bracket':
        _bracket(p)
        return
    if kind in ('pencil', 'rubber', 'erase'):
        _crosshair(p)
    else:
        _arrow(p)
    _BADGE.get(kind, _badge_select)(p)


def hotspot(kind, select_style='arrow'):
    """热点 (24 逻辑坐标): 准星中心 / 箭头尖 / 括号落点"""
    if kind in ('pencil', 'rubber', 'erase') or \
            (kind == 'select' and select_style == 'bracket'):
        return CROSS
    return ARROW_TIP


_CACHE = {}


def tool_cursor(kind, dpr=1.0, size='standard', select_style='arrow'):
    """工具指针 (按 种类 × 屏幕缩放 × 大小 × 选择样式 缓存)"""
    dpr = max(1.0, round(float(dpr or 1.0), 2))
    mult = SIZE_MULT.get(size, 1.0)
    style = select_style if select_style in SELECT_STYLES else 'arrow'
    key = (kind, dpr, mult, style)
    cur = _CACHE.get(key)
    if cur is not None:
        return cur
    px = int(round(24 * mult * dpr))
    pm = QPixmap(px, px)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.scale(mult * dpr, mult * dpr)
    draw_glyph(p, kind, style)
    p.end()
    pm.setDevicePixelRatio(dpr)
    hs = hotspot(kind, style)
    cur = QCursor(pm, int(round(hs.x() * mult)), int(round(hs.y() * mult)))
    _CACHE[key] = cur
    return cur


def clear_cache():
    _CACHE.clear()
