# -*- coding: utf-8 -*-
"""变速 lanes (Q 轮): BPM 速度轨, FL 式「拉起遮罩」——覆盖在卷帘下部, 不改变卷帘尺寸
   横轴 = 时间 (与卷帘同一 ppb/view_tick, x 映射含键盘对齐, 随卷帘 viewChanged 同步)
   纵轴 = BPM 20..400 (左 64px 与卷帘键盘列对齐, 画 BPM 刻度)
   Tempo 事件 = 横向矩形条 (x=事件 tick, 宽=该 BPM 持续到下一事件, y=BPM)
   顶部拉手 = 上下拖动升降 lanes (FL 式 Pull up grip); 双击条 = 精确 BPM 输入;
   右键条 = 精确输入 · 在光标处分割 · 删除事件 (与前一合并); 滚轮转发卷帘
   撤销 = EditSession 统一撤销栈的 tempo 条目 (与音符编辑同一套 Ctrl+Z/Y)"""
import math
from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import QColor, QPainter, QPen, QFont, QWheelEvent
from PySide6.QtWidgets import QWidget, QMenu
from common import KB_W, HEADER_H
from i18n import t as tr

BPM_MIN, BPM_MAX = 20.0, 400.0
HANDLE_H = 10.0            # 拉手高 (lanes 折叠时仅剩这条拉手)
BAR_TH = 10                # 事件条厚

class TempoLane(QWidget):
    """BPM 速度轨 lanes: 覆盖式遮罩 (卷帘尺寸/内容不变)"""
    def __init__(self, roll, mw, lane_h=150.0):
        super().__init__(roll)                  # 卷帘子控件: 覆盖其下部
        self.roll = roll
        self.mw = mw
        self.lane_h = float(lane_h)             # 事件区高 (不含拉手)
        self.selected = -1
        self.drag_idx = -1
        self.drag_bpm0 = 0.0
        self._pushed = False                    # 拖动撤销是否已入栈
        self._menu_tick = 0.0
        self._resizing = False
        self._resize_y0 = 0.0; self._resize_h0 = 0.0
        self._pan_x0 = 0.0
        self.setMouseTracking(True)
        self.setToolTip(tr('拖动顶部拉手 上下拉起变速 lanes · 拖动条 改 BPM · '
                           '双击 精确 BPM · 右键 分割/删除'))
        self.reposition()
    # ---------- 尺寸 ----------
    def reposition(self):
        """覆盖在卷帘底部 (拉手在遮罩顶缘); 卷帘尺寸变化时保持锚定"""
        rh = self.roll.height()
        total = max(HANDLE_H, min(HANDLE_H + self.lane_h, rh - int(HEADER_H)))
        self.setGeometry(0, rh - total, self.roll.width(), total)
    def set_lane_height(self, h, save=True):
        max_h = max(0.0, self.roll.height() - HANDLE_H - HEADER_H)
        self.lane_h = max(0.0, min(max_h, float(h)))
        self.reposition()
        if save:
            import settings_store as store
            store.save_lane_h(self.lane_h)
    # ---------- 视图同步 (与卷帘共享) ----------
    @property
    def tmap(self):
        return self.mw.tmap
    def x_of_tick(self, t):
        return self.roll.x_of_tick(t)
    # ---------- 事件命中 ----------
    def _events(self):
        return self.tmap.events()
    def _total(self):
        return max(1.0, self.mw.total_tick_display)
    def _hit(self, x, y):
        """命中事件下标 (y 在事件区, x 在事件条范围内); 未命中 -1"""
        if y < HANDLE_H: return -1              # 拉手区
        evs = self._events()
        for i, (t, b) in enumerate(evs):
            x0 = self.x_of_tick(t)
            x1 = self.x_of_tick(evs[i + 1][0]) if i + 1 < len(evs) \
                else self.x_of_tick(self._total()) + 40
            mid = self.y_of_bpm(b)
            if x0 - 3 <= x <= x1 + 3 and abs(y - mid) <= 9: return i
        return -1
    def y_of_bpm(self, b):
        pad = 6.0
        scale = (self.height() - HANDLE_H - 2 * pad) / (BPM_MAX - BPM_MIN)
        return HANDLE_H + pad + (BPM_MAX - b) * scale
    def bpm_of_y(self, y):
        pad = 6.0
        scale = (self.height() - HANDLE_H - 2 * pad) / (BPM_MAX - BPM_MIN)
        b = BPM_MAX - (y - HANDLE_H - pad) / scale
        return max(BPM_MIN, min(BPM_MAX, b))
    # ---------- 绘制 ----------
    def paintEvent(self, ev):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        p.fillRect(0, 0, w, h, QColor('#171b21'))
        if self.tmap is None: return
        # ---- 拉手 (FL 式 Pull up grip): 深色条 + 中央握点 ----
        p.fillRect(QRectF(0, 0, w, HANDLE_H), QColor('#101318'))
        gx = w / 2
        p.setPen(QColor('#4a515c'))
        for k, dx in enumerate((-6, 0, 6)):
            yy = 3 + (k % 2) * 3
            p.drawLine(QPointF(gx + dx - 2, yy), QPointF(gx + dx + 2, yy))
        p.setPen(QColor('#666678')); p.setFont(QFont('Segoe UI', 7))
        p.drawText(QRectF(gx + 12, 0, 90, HANDLE_H),
                   Qt.AlignVCenter | Qt.AlignLeft, '▾')
        # ---- 左侧 BPM 刻度 (与卷帘键盘列对齐) ----
        p.fillRect(0, HANDLE_H, int(KB_W), h - HANDLE_H, QColor('#14181e'))
        p.setFont(QFont('Segoe UI', 8))
        b = 100
        while b <= BPM_MAX:
            y = self.y_of_bpm(b)
            if HANDLE_H + 4 <= y <= h - 4:
                p.setPen(QPen(QColor('#3a4450'), 1))
                p.drawLine(QPointF(KB_W - 8, y), QPointF(KB_W, y))
                p.setPen(QColor('#8a94a2'))
                p.drawText(QRectF(2, y - 8, KB_W - 12, 16),
                           Qt.AlignRight | Qt.AlignVCenter, str(b))
            b += 100
        # ---- BPM 横向参考线 (画布区) ----
        p.setPen(QPen(QColor('#252b33'), 1))
        b = 100
        while b <= BPM_MAX:
            y = self.y_of_bpm(b)
            if y >= HANDLE_H + 4 and y <= h - 4:
                p.drawLine(QPointF(KB_W, y), QPointF(w, y))
            b += 50
        # ---- 时间网格 (与卷帘同 view_tick/ppb: 小节线竖向贯穿 lanes) ----
        bt = self.mw.bar_ticks
        t = math.floor(self.roll.view_tick / bt) * bt
        while t <= self.roll.tick_of_x(w) + bt:
            x = self.x_of_tick(t)
            if x >= KB_W:
                p.setPen(QPen(QColor('#333b46'), 1))
                p.drawLine(QPointF(x, HANDLE_H), QPointF(x, h))
            t += bt
        # ---- Tempo 事件条 ----
        evs = self._events()
        total = self._total()
        for i, (t, b) in enumerate(evs):
            x0 = self.x_of_tick(t)
            x1 = self.x_of_tick(evs[i + 1][0]) if i + 1 < len(evs) \
                else self.x_of_tick(total) + 40
            x0 = max(x0, KB_W); x1 = max(x1, x0 + 6)
            y = self.y_of_bpm(b)
            sel = (i == self.selected)
            fill = QColor('#ffb020') if sel else QColor('#e8b05a')
            p.setPen(QPen(QColor('#101318'), 1)); p.setBrush(fill)
            p.drawRect(QRectF(x0, y - BAR_TH / 2, x1 - x0, BAR_TH))
            p.setBrush(QColor('#ffe2a8') if sel else QColor('#d5d8dc'))
            p.drawRect(QRectF(x0 - 2.5, y - BAR_TH / 2 - 1.5, 5, BAR_TH + 3))
            label = ('%.1f' % b) if b != int(b) else ('%d' % int(b))
            p.setPen(QColor('#171b21')); p.setFont(QFont('Segoe UI', 8))
            p.drawText(QPointF(x0 + 5, y - BAR_TH / 2 - 3), label)
        # ---- 播放头 (与卷帘同步) ----
        ph = self.roll.playhead_tick
        if ph is not None:
            x = self.x_of_tick(ph)
            if x >= KB_W:
                p.setPen(QPen(QColor('#ff3b30'), 1))
                p.drawLine(QPointF(x, 0), QPointF(x, h))
    # ---------- 交互 ----------
    def _push_undo(self):
        if self.mw.edit_session is not None:
            self.mw.model.push_tempo(self.tmap.events())   # (X 轮) 经模型层入栈
    def mousePressEvent(self, ev):
        r = self.mw.router                                  # (Y 轮) 手势仲裁
        if ev.button() == Qt.LeftButton and ev.position().y() <= HANDLE_H:
            if not r.begin(r.OWNER_TEMPO): ev.accept(); return
            self._resizing = True
            self._resize_y0 = ev.globalPosition().y()
            self._resize_h0 = self.lane_h
            self.setCursor(Qt.SizeVerCursor)
            ev.accept(); return
        if ev.button() == Qt.LeftButton:
            i = self._hit(ev.position().x(), ev.position().y())
            self.selected = i
            if not r.begin(r.OWNER_TEMPO): ev.accept(); return   # (Y 轮) 空白同样占 owner
            if i >= 0:
                self.drag_idx = i
                self.drag_bpm0 = self._events()[i][1]
                self._pushed = False
            # (Y 轮) 空白/命中都 accept 且不透传: lanes 区域绝不触发底层 MIDI 编辑
            self.update(); ev.accept(); return
        if ev.button() == Qt.MiddleButton:
            if not r.begin(r.OWNER_TEMPO): ev.accept(); return
            self._pan_x0 = ev.position().x()
            self._pan_t0 = self.roll.view_tick   # (Y 轮) 修复: _pan_t0 此前从未赋值
            ev.accept(); return
        ev.accept()
    def mouseMoveEvent(self, ev):
        r = self.mw.router                                  # (Y 轮) 手势校验
        if getattr(self, '_resizing', False):
            if not r.check(r.OWNER_TEMPO): ev.accept(); return
            dy = self._resize_y0 - ev.globalPosition().y()   # 上拖 = 拉起
            self.set_lane_height(self._resize_h0 + dy, save=False)
            ev.accept(); return
        if self.drag_idx >= 0:
            if not r.check(r.OWNER_TEMPO): ev.accept(); return
            new_bpm = round(self.bpm_of_y(ev.position().y()))   # 吸附整数 BPM
            cur = self._events()[self.drag_idx][1]
            if new_bpm != cur:
                if not self._pushed:
                    self._push_undo(); self._pushed = True
                self.tmap.set_bpm_index(self.drag_idx, new_bpm)
                self.mw._apply_tempo_change()
            self.update()
        elif ev.buttons() & Qt.MiddleButton:
            if not r.check(r.OWNER_TEMPO): ev.accept(); return
            dx = ev.position().x() - self._pan_x0
            self.roll.view_tick = self._pan_t0 - dx / self.roll.ppb * self.tmap.tpb
            self.roll._clamp_view(); self.roll.update(); self.roll.viewChanged.emit()
        elif self._hit(ev.position().x(), ev.position().y()) >= 0 \
                or ev.position().y() <= HANDLE_H:
            self.setCursor(Qt.SizeVerCursor)
        else:
            self.setCursor(Qt.ArrowCursor)
        ev.accept()
    def mouseReleaseEvent(self, ev):
        r = self.mw.router
        if getattr(self, '_resizing', False):
            self._resizing = False
            r.end(r.OWNER_TEMPO)                 # (Y 轮) 手势收尾清 owner
            import settings_store as store
            store.save_lane_h(self.lane_h)
            ev.accept(); return
        if self.drag_idx >= 0:
            self.drag_idx = -1
            self._pushed = False
        self.update()
        r.end(r.OWNER_TEMPO)                     # (Y 轮) 统一清理, 无状态残留
    def mouseDoubleClickEvent(self, ev):
        i = self._hit(ev.position().x(), ev.position().y())
        if i >= 0: self.win_precise(i)
        super().mouseDoubleClickEvent(ev)
    def contextMenuEvent(self, ev):
        # QContextMenuEvent 无 .position() (Qt6 仅 QMouseEvent/QWheelEvent 等有), 用 .pos()
        p = ev.pos()
        i = self._hit(p.x(), p.y())
        if i < 0: return
        self.selected = i; self.update()
        tick = min(max(p.x(), KB_W), self.width())
        self._menu_tick = self.roll.tick_of_x(tick)
        m = QMenu(self)
        m.setStyleSheet(
            'QMenu { background:#1b1b21; color:#d6d6de; border:1px solid #3a3a44; }'
            'QMenu::item { padding:4px 18px; }'
            'QMenu::item:selected { background:#33333d; }')
        a_pre = m.addAction(tr('精确 BPM…'))
        a_split = m.addAction(tr('在光标处分割'))
        m.addSeparator()
        a_del = m.addAction(tr('删除事件 (与前一合并)'))
        if i == 0: a_del.setEnabled(False)      # 最早事件不可删
        act = m.exec(ev.globalPos())
        if act == a_pre: self.win_precise(i)
        elif act == a_split: self._split_at(i, self._menu_tick)
        elif act == a_del: self._delete_event(i)
    def wheelEvent(self, ev):
        """滚轮转发卷帘 (缩放/平移与 MIDI 编辑同一套; x 对齐卷帘)"""
        new = QWheelEvent(QPointF(ev.position().x(), 300),
                          QPointF(ev.position().x(), 300),
                          ev.pixelDelta(), ev.angleDelta(), ev.buttons(),
                          ev.modifiers(), Qt.ScrollUpdate, False)
        self.roll.wheelEvent(new)
    # ---------- 编辑入口 (右键菜单/双击调用) ----------
    def win_precise(self, idx):
        """双击条: 精确 BPM 输入 (S 轮原设计; T 轮重构丢失本方法致双击 AttributeError,
           X 轮补回并改经模型层 tempo_set 写入)"""
        if not (0 <= idx < len(self._events())): return
        from PySide6.QtWidgets import (QDoubleSpinBox, QDialog, QHBoxLayout,
                                       QPushButton, QVBoxLayout)
        dlg = QDialog(self)
        dlg.setWindowTitle(tr('精确 BPM…'))
        v = QVBoxLayout(dlg)
        sp = QDoubleSpinBox(); sp.setRange(20.0, 400.0); sp.setDecimals(1)
        sp.setValue(self.tmap.bpms[idx])
        row = QHBoxLayout(); row.addWidget(sp)
        b_ok = QPushButton(tr('确定')); b_ok.clicked.connect(dlg.accept)
        b_no = QPushButton(tr('取消')); b_no.clicked.connect(dlg.reject)
        row.addWidget(b_ok); row.addWidget(b_no)
        v.addLayout(row)
        if dlg.exec() != QDialog.Accepted: return
        self.mw.model.tempo_set(idx, float(sp.value()))   # (X 轮) push+改表+retime
        self.mw._apply_tempo_change()
        self.update()
    def _split_at(self, idx, cursor_tick):
        """在光标处分割事件 (吸附到拍; BPM 取所在段当前值)"""
        tmap = self.tmap
        beat = self.mw.bar_ticks / 4
        tick = max(0.0, round(cursor_tick / beat) * beat)
        bpm = tmap.bpm_at_tick(tick)
        self.mw.model.tempo_insert(tick, bpm)   # (X 轮) push_tempo+改表+retime
        self.mw._apply_tempo_change()
    def _delete_event(self, idx):
        """删除事件 (与前一事件合并); 最早事件不可删"""
        if idx <= 0:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.information(self, tr('提示'), tr('最早的事件不可删除')); return
        self.mw.model.tempo_delete(self._events()[idx][0])   # (X 轮) push+删表+retime
        self.mw._apply_tempo_change()
