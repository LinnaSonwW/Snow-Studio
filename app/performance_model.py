# -*- coding: utf-8 -*-
"""演奏事件编译层 (P0 批次1): raw_notes + TempoMap -> PerformanceEvent 纯编译产物。
   职责: 只做"纯时间翻译"五字段 (start_tick/duration_ticks/bar/beat/notes),
         全程只用 tick, 不读 sec (tick 是唯一时间真相)。
   不负责: keys/hand/articulation 计算 (占位 None, 未来"一键原琴化"/指法模块经
           fill_keys/fill_hand 回调参数注入, 数据层不改); 不入撤销栈; 不缓存
           (调用方按数据变化时机重算, 当前挂载点 = mainwindow._rebuild);
           不写任何数据 (纯函数, 不改入参, 与 midi_data.resolve_overlaps 同风格)。
   依赖: 仅 stdlib; Note/TempoMap 鸭子类型, 零 Qt、零项目内 import (core-data 红线)。"""
from dataclasses import dataclass, replace
from typing import Callable, Optional


@dataclass(frozen=True)
class PerformanceEvent:
    """演奏事件: 同一 start_tick 的一组音符 = 一个事件 (和弦=多键块, 规划 2.1)。
       keys/hand/articulation 为占位字段, 本层不算, 默认 None。"""
    start_tick: int
    duration_ticks: int
    bar: int
    beat: float
    notes: list[int]                    # MIDI pitch (升序, 保留重复: 忠实翻译, 去重属策略层)
    arps: tuple = ()                    # (琶音轮) 与 notes 对齐的分组 id (0=无; 事件级取任意>0)
    keys: Optional[list[str]] = None    # 占位: 原琴键位 (fill_keys 回调注入)
    hand: Optional[str] = None          # 占位: 左右手 (fill_hand 回调注入)
    articulation: Optional[str] = None  # 占位: 奏法 (未来模块注入)


def compile_performance(raw_notes, tempo_map, *,
                        time_signature=(4, 4),
                        fill_keys: Optional[Callable[[int], list[str]]] = None,
                        fill_hand: Optional[Callable[[PerformanceEvent], str]] = None,
                        tsig_map=None,
                        ) -> list[PerformanceEvent]:
    """编译演奏事件表 (纯函数): 按 start_tick 严格相等分组 (零启发式,
       容差量化属未来 Quantize 模块), 事件按 start_tick 升序。
       bar 段长与 load_midi/mw.bar_ticks 同惯例 tpb*4*分子/分母
       (分母=4 时即方案公式 tpb*分子); 拍号由参数显式给出
       (TempoMap 不携带拍号, mainwindow 挂载时传 mw.tsig)。
       (二期) tsig_map 给出时 bar/beat 按分段拍号表计算 (曲中变拍),
       未给出时回退单一 time_signature"""
    num, den = int(time_signature[0]), int(time_signature[1])
    tpb = max(1, int(tempo_map.tpb))
    ticks_per_bar = max(1, tpb * 4 * num // den)
    beat_scale = den / (tpb * 4.0)      # beat = 小节内偏移 * beat_scale + 1
    # (二期) 分段拍号: [(段起, num, den, 段前累计小节数)] — 事件按段取 bar/beat
    seg_ctx = None
    if tsig_map is not None and len(tsig_map.events()) > 1:
        segs = tsig_map.events()
        seg_ctx = []
        bars_before = 0
        for i, (t0, n, d) in enumerate(segs):
            w = max(1.0, tpb * 4.0 * n / d)
            t1 = segs[i + 1][0] if i + 1 < len(segs) else None
            seg_ctx.append((t0, t1, n, d, w, bars_before))
            bars_before += max(1, -(-((t1 - t0) // w)) if t1 is not None else 1)
    def _bar_beat(tick):
        """tick → (bar, beat): 分段优先, 回退单一拍号"""
        if seg_ctx is not None:
            for t0, t1, n, d, w, bars_before in seg_ctx:
                if t1 is None or tick < t1:
                    k = int((tick - t0) // w)
                    beat = (tick - t0 - k * w) * d / (tpb * 4.0) + 1
                    return bars_before + k + 1, beat
        k = int(tick // ticks_per_bar)
        return k + 1, (tick - k * ticks_per_bar) * beat_scale + 1
    groups = {}                         # start_tick -> [音符] (零启发式分组)
    for nt in raw_notes:
        groups.setdefault(int(nt.start_tick), []).append(nt)
    events = []
    for st in sorted(groups):
        grp = groups[st]
        pairs = sorted((int(nt.note), int(getattr(nt, 'arp', 0) or 0))
                       for nt in grp)
        pitches = [p for p, _a in pairs]
        arps = tuple(a for _p, a in pairs)
        dur = max(int(nt.end_tick) for nt in grp) - st
        tick = max(0, st)               # 防御: 负 tick 钳 0 再做小节换算
        _bar, _beat = _bar_beat(tick)
        ev = PerformanceEvent(
            start_tick=st, duration_ticks=max(0, dur),
            bar=_bar,
            beat=_beat,
            notes=pitches,
            arps=arps,
            keys=[k for p in pitches for k in fill_keys(p)] if fill_keys else None)
        if fill_hand is not None:       # 回调收到已含 keys 的事件, 返回值写回 hand
            ev = replace(ev, hand=fill_hand(ev))
        events.append(ev)
    return events


def compile_performance_by_tid(raw_notes, tempo_map, *,
                               time_signature=(4, 4),
                               fill_keys: Optional[Callable[[int], list[str]]] = None,
                               fill_hand: Optional[Callable[[PerformanceEvent], str]] = None,
                               tsig_map=None,
                               ) -> dict[int, list[PerformanceEvent]]:
    """按轨分道编译 (演奏谱车道数据源): {tid: [事件表]}, tid 升序。
       各轨独立走 compile_performance —— 同 tick 跨轨不合组 (车道=乐器;
       单/多乐器模式判断只发生在 UI 层, 数据层不区分, 规格§3.4)。纯函数。"""
    groups = {}
    for nt in raw_notes:
        groups.setdefault(getattr(nt, 'tid', 0), []).append(nt)
    return {tid: compile_performance(lst, tempo_map, time_signature=time_signature,
                                     fill_keys=fill_keys, fill_hand=fill_hand,
                                     tsig_map=tsig_map)
            for tid, lst in sorted(groups.items())}

# (密度轮收编) 旧"快速连续演奏"分组 group_fast_runs 已删除: 密度峰检测
# ornament_detect.py (六层流水线) 为其全量替代, 生产/测试均不再引用。
