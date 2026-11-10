# -*- coding: utf-8 -*-
"""音高声组织 (Pitch Tissue) — Capella / Melodyne 式连续软边轨迹。

不是音符方块: 每条 Rohton 是一条随响度起伏粗细的纺锤/云雾带,
多圈半透明填充做出羽化边缘。数据来自 multipitch 包络。
"""
from __future__ import annotations
import math
from dataclasses import dataclass, field

from PySide6.QtCore import QRectF, QPointF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QBrush

from common import HEADER_H, KB_W


@dataclass
class PitchBlob:
    """一条连续音高轨迹: envelope = [(tick, intensity 0..1), ...]。"""
    pitch: int
    start_tick: float
    end_tick: float
    intensity: float = 1.0
    instrument: str = ''
    key: int = 0
    envelope: list[tuple[float, float]] = field(default_factory=list)


class PitchTissue:
    """声组织层: 连续包络 → 软边灰色轨迹。"""

    def __init__(self):
        self.blobs: list[PitchBlob] = []
        self._by_key: dict[int, PitchBlob] = {}
        self.version = 0

    def clear(self):
        self.blobs.clear()
        self._by_key.clear()
        self.version += 1

    def upsert(self, key: int, pitch: int, start_tick: float, end_tick: float,
               intensity: float = 1.0, instrument: str = '',
               envelope: list[tuple[float, float]] | None = None):
        end_tick = max(start_tick + 1.0, end_tick)
        intensity = max(0.05, min(1.0, float(intensity)))
        env = list(envelope) if envelope else []
        b = self._by_key.get(key)
        if b is None:
            b = PitchBlob(pitch, start_tick, end_tick, intensity, instrument, key, env)
            self._by_key[key] = b
            self.blobs.append(b)
        else:
            b.pitch = pitch
            b.start_tick = start_tick
            b.end_tick = end_tick
            b.intensity = intensity
            b.instrument = instrument
            b.envelope = env
        self.version += 1

    def remove_keys(self, keys: set[int]):
        if not keys:
            return
        self.blobs = [b for b in self.blobs if b.key not in keys]
        for k in keys:
            self._by_key.pop(k, None)
        self.version += 1

    def load_raw_events(self, events, sec_to_tick):
        """用多音高 RawPitchEvent (含包络) 重建声组织。"""
        self.clear()
        merged = _merge_same_pitch(events, gap_sec=0.22)
        for i, e in enumerate(merged):
            st = float(sec_to_tick(e.start_sec))
            en = float(sec_to_tick(e.end_sec))
            env_src = getattr(e, 'envelope', None) or []
            if env_src:
                env = [(float(sec_to_tick(t)), max(0.02, min(1.0, float(L))))
                       for t, L in env_src]
            else:
                env = _spindle_envelope(st, en, max(0.2, float(getattr(e, 'loudness', 1.0))))
            self.upsert(
                i, int(e.pitch), st, en,
                intensity=max(0.2, float(getattr(e, 'loudness', 1.0))),
                instrument=str(getattr(e, 'timbre', '') or ''),
                envelope=env)

    def draw(self, p: QPainter, roll, *, ta: float | None = None,
             tb: float | None = None, local_x0: float = 0.0):
        if roll.tmap is None or not self.blobs:
            return
        lo, hi = roll.note_low, roll.note_high
        rh = roll.row_h()
        if rh <= 0:
            return
        y_off = (roll.view_note_start - lo) * rh
        w = float(roll.width())
        ppt = roll.ppb / roll.tmap.tpb
        tile_mode = ta is not None and tb is not None
        vis_t0 = ta if tile_mode else roll.view_tick
        vis_t1 = tb if tile_mode else roll.tick_of_x(w)

        p.save()
        p.setRenderHint(QPainter.Antialiasing, True)
        if tile_mode:
            p.setClipRect(QRectF(0, HEADER_H, max(1.0, (tb - ta) * ppt),
                                 roll.height() - HEADER_H))
        else:
            p.setClipRect(QRectF(KB_W, HEADER_H, w - KB_W, roll.height() - HEADER_H))

        for b in self.blobs:
            if not (lo - 1 <= b.pitch <= hi + 1):
                continue
            if b.end_tick <= vis_t0 or b.start_tick >= vis_t1:
                continue
            cy = HEADER_H + (hi - b.pitch) * rh - y_off + rh * 0.5
            samples = self._screen_samples(b, roll, ppt, ta, local_x0, tile_mode,
                                           vis_t0, vis_t1, w)
            if len(samples) < 2:
                continue
            self._draw_ribbon(p, samples, cy, rh, b.intensity)

        p.restore()

    def _screen_samples(self, b: PitchBlob, roll, ppt, ta, local_x0, tile_mode,
                        vis_t0, vis_t1, w) -> list[tuple[float, float]]:
        """→ [(x_px, intensity), ...] 可见区间内 (含瓦片边界插值)。"""
        env = b.envelope
        if len(env) < 2:
            env = _spindle_envelope(b.start_tick, b.end_tick, b.intensity)

        def x_of(tick: float) -> float:
            if tile_mode:
                return local_x0 + (tick - ta) * ppt
            x = roll.x_of_tick(tick)
            return max(KB_W + 1.0, min(w - 1.0, x))

        if b.end_tick <= vis_t0 or b.start_tick >= vis_t1:
            return []

        # 保留略宽范围, 便于边界插值
        pts = []
        for tick, inten in env:
            if tick < vis_t0 - 0.5 or tick > vis_t1 + 0.5:
                continue
            pts.append((tick, max(0.02, min(1.0, inten))))
        if not pts:
            mid = 0.5 * (max(b.start_tick, vis_t0) + min(b.end_tick, vis_t1))
            pts = [(mid, b.intensity)]
        # 瓦片/视口边界插值: 轨迹跨边界时补端点, 避免接缝断带
        bounds = []
        if b.start_tick < vis_t1 and b.end_tick > vis_t0:
            if b.start_tick < vis_t0 < b.end_tick:
                bounds.append(vis_t0)
            if b.start_tick < vis_t1 < b.end_tick:
                bounds.append(vis_t1)
        tick_set = {t for t, _ in pts}
        for bt in bounds:
            if bt not in tick_set:
                pts.append((bt, _interp_envelope(env, bt)))
        pts.sort(key=lambda p: p[0])
        out = [(x_of(t), i) for t, i in pts]
        if len(out) < 2:
            t_lo = max(b.start_tick, vis_t0)
            t_hi = min(b.end_tick, vis_t1)
            if t_hi > t_lo:
                out = [(x_of(t_lo), _interp_envelope(env, t_lo)),
                       (x_of(t_hi), _interp_envelope(env, t_hi))]
            elif out:
                out = [out[0], (out[0][0] + 1.0, out[0][1])]
        # 缩放联动降采样: 放大保留更密点, 缩小略稀化
        min_step = max(0.75, min(2.2, 14.0 / max(ppt, 0.4)))
        if len(out) > 4:
            dec = [out[0]]
            for x, inten in out[1:-1]:
                if abs(x - dec[-1][0]) >= min_step:
                    dec.append((x, inten))
            dec.append(out[-1])
            out = dec
        return out

    @staticmethod
    def _draw_ribbon(p: QPainter, samples: list[tuple[float, float]],
                     cy: float, row_h: float, base_inten: float):
        """多层半透明纺锤带: 外圈羽化 + 内芯更实 (对齐参考图软边灰云)。"""
        max_half = max(2.8, row_h * 0.72)
        min_half = max(0.45, row_h * 0.03)

        def halves(scale: float) -> list[float]:
            out = []
            for _, inten in samples:
                t = inten ** 0.75
                h = min_half + (max_half - min_half) * t * scale
                out.append(h)
            return out

        # 四层羽化: 最外几乎透明 → 芯部更实
        layers = (
            (1.85, 10 + int(14 * base_inten)),
            (1.40, 22 + int(28 * base_inten)),
            (1.08, 48 + int(45 * base_inten)),
            (0.82, 85 + int(75 * base_inten)),
        )
        p.setPen(Qt.NoPen)
        for scale, alpha in layers:
            path = _ribbon_path(samples, cy, halves(scale))
            if path is None:
                continue
            p.setBrush(QBrush(QColor(200, 208, 218, max(6, min(210, alpha)))))
            p.drawPath(path)

    def draw_tile(self, p: QPainter, roll, ta: float, tb: float, *,
                  tile_w: float, v_margin: float = 0.0, local_x0: float = 0.0):
        self.draw(p, roll, ta=ta, tb=tb, local_x0=local_x0)

    def clear_tile_cache(self):
        pass


def _interp_envelope(env: list[tuple[float, float]], tick: float) -> float:
    """包络线性插值 (tick 单位与 env 一致)。"""
    if not env:
        return 0.3
    if tick <= env[0][0]:
        return env[0][1]
    if tick >= env[-1][0]:
        return env[-1][1]
    for i in range(len(env) - 1):
        t0, l0 = env[i]
        t1, l1 = env[i + 1]
        if t0 <= tick <= t1:
            if t1 <= t0:
                return l0
            a = (tick - t0) / (t1 - t0)
            return max(0.02, min(1.0, l0 * (1.0 - a) + l1 * a))
    return env[-1][1]


def _merge_same_pitch(events, *, gap_sec: float = 0.22):
    """同音高且间隙很小的轨迹拼成一条连续包络, 避免碎成方块感。"""
    if not events:
        return []
    from multipitch_tissue import RawPitchEvent
    ordered = sorted(events, key=lambda e: (e.pitch, e.start_sec))
    out = []
    cur = None
    for e in ordered:
        if cur is None:
            cur = RawPitchEvent(
                pitch=e.pitch, start_sec=e.start_sec, end_sec=e.end_sec,
                loudness=e.loudness, timbre=e.timbre,
                envelope=list(e.envelope or []))
            continue
        if e.pitch == cur.pitch and e.start_sec <= cur.end_sec + gap_sec:
            # 拼接包络; 间隙用低响度细丝连接
            if e.start_sec > cur.end_sec and cur.envelope:
                mid_t = 0.5 * (cur.end_sec + e.start_sec)
                cur.envelope.append((mid_t, 0.06))
            cur.envelope.extend(e.envelope or [])
            cur.end_sec = max(cur.end_sec, e.end_sec)
            cur.loudness = max(cur.loudness, e.loudness)
            if e.timbre and not cur.timbre:
                cur.timbre = e.timbre
        else:
            out.append(cur)
            cur = RawPitchEvent(
                pitch=e.pitch, start_sec=e.start_sec, end_sec=e.end_sec,
                loudness=e.loudness, timbre=e.timbre,
                envelope=list(e.envelope or []))
    if cur is not None:
        out.append(cur)
    return out


def _spindle_envelope(t0: float, t1: float, peak: float,
                      n: int = 12) -> list[tuple[float, float]]:
    """无逐帧数据时的纺锤回退包络 (两端细、中间鼓)。"""
    if t1 <= t0:
        t1 = t0 + 1.0
    n = max(4, n)
    out = []
    for i in range(n):
        a = i / (n - 1)
        tick = t0 + (t1 - t0) * a
        w = math.sin(math.pi * a)
        out.append((tick, max(0.05, peak * (0.15 + 0.85 * w))))
    return out


def _ribbon_path(samples: list[tuple[float, float]], cy: float,
                 half_h: list[float]) -> QPainterPath | None:
    """平滑上缘左→右 + 下缘右→左, 闭合软带 (类 Melodyne 云雾)。"""
    n = len(samples)
    if n < 2 or len(half_h) != n:
        return None
    top = [QPointF(x, cy - h) for (x, _), h in zip(samples, half_h)]
    bot = [QPointF(x, cy + h) for (x, _), h in zip(samples, half_h)]
    path = QPainterPath()
    _append_smooth(path, top, start=True)
    _append_smooth(path, list(reversed(bot)), start=False)
    path.closeSubpath()
    return path


def _append_smooth(path: QPainterPath, pts: list[QPointF], *, start: bool):
    """Catmull-Rom 近似的三次贝塞尔折线, 减少折角方块感。"""
    if not pts:
        return
    if start:
        path.moveTo(pts[0])
    else:
        path.lineTo(pts[0])
    if len(pts) == 1:
        return
    if len(pts) == 2:
        path.lineTo(pts[1])
        return
    for i in range(len(pts) - 1):
        p0 = pts[i - 1] if i > 0 else pts[i]
        p1 = pts[i]
        p2 = pts[i + 1]
        p3 = pts[i + 2] if i + 2 < len(pts) else p2
        c1 = QPointF(p1.x() + (p2.x() - p0.x()) / 6.0,
                     p1.y() + (p2.y() - p0.y()) / 6.0)
        c2 = QPointF(p2.x() - (p3.x() - p1.x()) / 6.0,
                     p2.y() - (p3.y() - p1.y()) / 6.0)
        path.cubicTo(c1, c2, p2)
