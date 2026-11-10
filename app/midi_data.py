# -*- coding: utf-8 -*-
"""MIDI 数据层: 解析 / TempoMap(tick<->秒) / 同音重叠处理 / sec重算 / 另存 (纯数据, 无界面依赖)
   多音轨: 音符携带 tid, Track 保存轨道元数据(名称/通道/静音/独奏); 鼓轨(10通道)默认静音"""
import bisect
import itertools
from collections import deque
from dataclasses import dataclass, field
import mido
_note_seq = itertools.count(1)                 # Note 稳定 id 发号器
@dataclass
class Track:
    """轨道元数据 (多音轨): 名称/通道/静音/独奏; is_drum=channel 10 打击乐"""
    tid: int
    name: str = ''
    channel: int = -1
    is_drum: bool = False
    muted: bool = False
    solo: bool = False
@dataclass(eq=False)
class Note:
    note: int; vel: int
    start_tick: int; end_tick: int
    start_sec: float; end_sec: float
    playable: bool = True
    # nid: 稳定自增 id —— 编辑器选中集/撤销快照/播放高亮 均按 nid 跨副本追踪同一音符
    nid: int = field(default_factory=lambda: next(_note_seq))
    tid: int = 0                                # 所属轨道 (多音轨)
    arp: int = 0                                # (琶音轮) 琶音分组 id (0=无, >0=组)
class TempoMap:
    """tick↔秒 双向换算, 分段线性, 支持任意多次中途变速 (Q 轮起支持在线编辑)"""
    def __init__(self, tpb, changes):
        dedup = {}
        for t, tp in changes: dedup[t] = tp
        if 0 not in dedup: dedup[0] = 500000
        ch = sorted(dedup.items())
        self.tpb = tpb
        self.ticks = [t for t, _ in ch]
        self.tempos = [tp for _, tp in ch]
        self.bpms = [60e6 / tp for tp in self.tempos]
        self.cum = [0.0]
        for i in range(1, len(ch)):
            self.cum.append(self.cum[-1] +
                mido.tick2second(ch[i][0] - ch[i-1][0], tpb, self.tempos[i-1]))
        self.version = 0                        # (Q 轮) 编辑版本号 (驱动瓦片缓存失效)
    def _rebuild(self):
        """ticks/tempos 变更后重排 + 重算 bpms/cum, 并递增版本号"""
        dedup = {}
        for t, tp in zip(self.ticks, self.tempos): dedup[t] = tp
        ch = sorted(dedup.items())
        self.ticks = [t for t, _ in ch]
        self.tempos = [tp for _, tp in ch]
        self.bpms = [60e6 / tp for tp in self.tempos]
        self.cum = [0.0]
        for i in range(1, len(ch)):
            self.cum.append(self.cum[-1] +
                mido.tick2second(ch[i][0] - ch[i-1][0], self.tpb, self.tempos[i-1]))
        self.version += 1
    def events(self):
        """[(tick, bpm)] 事件列表 (时间顺序)"""
        return list(zip(self.ticks, self.bpms))
    def index_at(self, tick):
        """tick 对应的事件下标 (不存在返回 -1)"""
        try: return self.ticks.index(int(tick))
        except ValueError: return -1
    def set_bpm_index(self, idx, bpm):
        """修改第 idx 个事件的 BPM (20..400 外钳制)"""
        bpm = max(20.0, min(400.0, float(bpm)))
        if 0 <= idx < len(self.ticks):
            self.tempos[idx] = 60e6 / bpm
            self._rebuild()
    def insert_event(self, tick, bpm):
        """在 tick 处插入分割事件 (分割: BPM 取所在段当前值); 返回事件 tick"""
        tick = max(0, int(tick))
        tp = 60e6 / max(20.0, min(400.0, float(bpm)))
        if tick in self.ticks:
            i = self.ticks.index(tick)
            self.tempos[i] = tp
        else:
            i = bisect.bisect_left(self.ticks, tick)
            self.ticks.insert(i, tick); self.tempos.insert(i, tp)
        self._rebuild()
        return tick
    def remove_event(self, tick):
        """删除 tick 处事件 (与前一事件合并); 最早的事件不可删"""
        i = self.index_at(tick)
        if i <= 0: return False                # 不存在 / 最早事件
        del self.ticks[i]; del self.tempos[i]
        self._rebuild()
        return True
    def restore_events(self, events):
        """撤销 tempo 修改: 恢复事件列表 [(tick, bpm)]"""
        self.ticks = [int(t) for t, _b in events]
        self.tempos = [60e6 / max(20.0, min(400.0, float(b))) for _t, b in events]
        self._rebuild()
    def tick2sec(self, tick):
        i = bisect.bisect_right(self.ticks, tick) - 1
        return self.cum[i] + mido.tick2second(tick - self.ticks[i], self.tpb, self.tempos[i])
    def sec2tick(self, sec):
        i = min(max(bisect.bisect_right(self.cum, sec) - 1, 0), len(self.cum) - 1)
        return self.ticks[i] + mido.second2tick(sec - self.cum[i], self.tpb, self.tempos[i])
    def bpm_at_tick(self, tick):
        return self.bpms[max(0, bisect.bisect_right(self.ticks, tick) - 1)]
def load_midi(path):
    """逐轨解析(保留轨道信息), FIFO 配对 on/off
       -> (TempoMap, notes, 小节tick, 拍号, tracks)
       tracks 仅含含音符的轨; channel 9(打击乐) 标记鼓轨并默认静音"""
    mid = None
    for cs in ('utf-8', 'latin-1'):               # 轨道名/文本编码: 优先 utf-8 (中文)
        try:
            mid = mido.MidiFile(path, charset=cs); break
        except UnicodeDecodeError:
            continue
    tpb = mid.ticks_per_beat
    tempos, tsigs, raw, meta = [], [], [], {}
    arp_meta = {}                                # (琶音轮) 原始轨号 -> [(gid, tick, note)]
    for ti, tr in enumerate(mid.tracks):
        t = 0; pend = {}; name = None; chan = None
        for msg in tr:
            t += msg.time
            typ = msg.type
            if typ == 'set_tempo': tempos.append((t, msg.tempo))
            elif typ == 'time_signature': tsigs.append((t, msg.numerator, msg.denominator))
            elif typ == 'track_name' and not name and msg.name.strip():
                name = msg.name.strip()
            elif typ == 'marker' and msg.text.startswith('ARPGROUP'):
                # (琶音轮) save_midi 写入的分组标记: "ARPGROUP gid:tick:note …"
                for tok in msg.text[len('ARPGROUP'):].split():
                    try:
                        g, s, n = tok.split(':')
                        arp_meta.setdefault(ti, []).append((int(g), int(s), int(n)))
                    except ValueError:
                        continue                # 损坏令牌静默跳过 (无分组降级)
            elif typ == 'note_on' and msg.velocity > 0:
                if chan is None: chan = msg.channel
                pend.setdefault(msg.note, deque()).append((t, msg.velocity))
            elif typ == 'note_off' or (typ == 'note_on' and msg.velocity == 0):
                if chan is None: chan = msg.channel
                q = pend.get(msg.note)
                if q:
                    st, vel = q.popleft()
                    raw.append((st, t, msg.note, vel, ti))
        if any(r[4] == ti for r in raw):
            meta[ti] = (name or f'轨道 {ti + 1}', chan)
    tsigs.sort(key=lambda x: x[0])
    tmap = TempoMap(tpb, tempos)
    used = sorted(meta)                                   # 含音符的原始轨号
    tid_of = {ti: i for i, ti in enumerate(used)}
    tracks = []
    for i, ti in enumerate(used):
        name, chan = meta[ti]
        tracks.append(Track(tid=i, name=name, channel=(-1 if chan is None else chan),
                            is_drum=(chan == 9), muted=(chan == 9)))
    notes = [Note(n, v, s, e, tmap.tick2sec(s), tmap.tick2sec(e), tid=tid_of[ti])
             for s, e, n, v, ti in raw]
    # (琶音轮) 按 (轨, 起点, 音高) 回填分组; 匹配失败静默 = 无分组 (降级安全)
    if arp_meta:
        lookup = {(tid_of[ti], s, n): g
                  for ti, lst in arp_meta.items() if ti in tid_of
                  for g, s, n in lst}
        for nt in notes:
            nt.arp = lookup.get((nt.tid, nt.start_tick, nt.note), 0)
    notes.sort(key=lambda nt: (nt.start_tick, nt.note))
    num, den = tsigs[0][1:] if tsigs else (4, 4)
    return tmap, notes, tpb * 4 * num / den, (num, den), tracks,         [(t, n, d) for t, n, d in tsigs] or [(0, num, den)]
class TsigMap:
    """分段拍号表 (二期): [(tick, num, den)] 升序, tick=0 必有段。
       小节线跨段累计 (每段宽度 = tpb*4*num/den; 拍号变更处前段末小节截断)。
       version 驱动瓦片缓存失效 (与 TempoMap 同机制)"""
    LIMIT = 4096

    def __init__(self, tpb, events=None):
        self.tpb = int(tpb)
        self.version = 0
        self._seg = []                       # [(tick, num, den)] 升序
        self.set_events(events or [(0, 4, 4)])

    def set_events(self, events):
        seg = {}
        for t, n, d in events:
            t = max(0, int(t)); n = max(1, int(n)); d = max(1, int(d))
            seg[t] = (n, d)
        self._seg = [(t, seg[t][0], seg[t][1]) for t in sorted(seg)]
        if self._seg[0][0] != 0:             # tick=0 必有段 (首段缺失补齐)
            n, d = self._seg[0][1], self._seg[0][2]
            self._seg.insert(0, (0, n, d))
        # (二期) 相邻同值段合并 (冗余段删除; 保留 tick 最小者)
        out = [self._seg[0]]
        for t, n, d in self._seg[1:]:
            if (n, d) != (out[-1][1], out[-1][2]):
                out.append((t, n, d))
        self._seg = out
        self.version += 1

    def events(self):
        return [(t, n, d) for t, n, d in self._seg]

    def at(self, tick):
        """tick 所在段 (num, den)"""
        cur = self._seg[0][1:]
        for t, n, d in self._seg:
            if t <= tick:
                cur = (n, d)
            else:
                break
        return cur

    def bar_ticks_at(self, tick):
        n, d = self.at(tick)
        return max(1.0, self.tpb * 4.0 * n / d)

    def measure_start(self, tick):
        """tick 所在小节的小节起点 tick (跨段累计; 段边界即小节线)"""
        tick = max(0, int(tick))
        segs = self._seg
        si = 0
        while si + 1 < len(segs) and segs[si + 1][0] <= tick:
            si += 1
        t0 = segs[si][0]
        n, d = segs[si][1], segs[si][2]
        w = max(1.0, self.tpb * 4.0 * n / d)
        return t0 + int((tick - t0) // w) * w

    def bar_starts(self, from_tick=0, to_tick=None, limit=LIMIT):
        """[(start_tick, bar_no)] 从 ≥from_tick 的小节起 (bar_no 1 基跨段累计),
           到 to_tick (None=曲尾) — 拍号段起点即小节线, 段末不足一小节按截断小节计
           (段界 tick 归属下一段: 内层先判段界再追加, 不产生重复小节起点)"""
        if to_tick is None:
            to_tick = float('inf')
        segs = self._seg
        out = []
        bars = 0                              # 跨段累计小节数
        si = 0
        while si < len(segs) and len(out) < limit:
            t0 = segs[si][0]
            t1 = segs[si + 1][0] if si + 1 < len(segs) else float('inf')
            n, d = segs[si][1], segs[si][2]
            w = max(1.0, self.tpb * 4.0 * n / d)
            k = 0
            while True:
                bt = t0 + k * w
                if bt >= to_tick or len(out) >= limit:
                    break
                if si + 1 < len(segs) and bt >= segs[si + 1][0]:
                    break                     # 段界归下一段 (不重复输出)
                if bt >= from_tick - 1e-6:
                    out.append((bt, bars + k + 1))
                k += 1
            si += 1
            if t1 >= to_tick:
                break
            bars += max(1, int(-(-(min(t1, to_tick) - t0) // w)))   # 段内小节数(含截断)
        return out

    def set_segment(self, tick, num, den):
        """右键节拍标记: 清 tick 起的旧段后插入新段 (set_events 统一相邻
           同值段合并); tick 由调用方吸附到小节起点"""
        tick = max(0, int(tick))
        num, den = max(1, int(num)), max(1, int(den))
        seg = [(t, n, d) for t, n, d in self._seg if t < tick]
        if not seg or (seg[-1][1], seg[-1][2]) != (num, den):
            seg.append((tick, num, den))
        self.set_events(seg)


def resolve_overlaps(notes, tmap, mode):
    """DAW 导出的同音重叠处理 (按轨道+音高分组, 不跨轨合并):
       merge    重叠/相接 -> 合并为一个长音
       truncate 前音在下一个触发点截断, 之后重新按下(同刻双击去重)
       返回 (新列表, 统计dict)"""
    groups = {}
    for nt in notes: groups.setdefault((nt.tid, nt.note), []).append(nt)
    out, st = [], {'merged': 0, 'truncated': 0, 'dedup': 0}
    for lst in groups.values():
        lst.sort(key=lambda n: n.start_tick)
        cur = None
        for nt in lst:
            if cur is not None and nt.start_tick < cur.end_tick:
                if mode == 'merge':
                    if nt.end_tick > cur.end_tick: cur.end_tick = nt.end_tick
                    cur.vel = max(cur.vel, nt.vel)
                    st['merged'] += 1; continue
                cur.end_tick = nt.start_tick          # truncate
                if cur.end_tick > cur.start_tick:
                    out.append(cur); st['truncated'] += 1
                else:
                    st['dedup'] += 1                  # 同刻双击: 前音零长, 丢弃
                cur = nt; continue
            if cur is not None: out.append(cur)
            cur = nt
        if cur is not None: out.append(cur)
    for nt in out:
        nt.start_sec = tmap.tick2sec(nt.start_tick)
        nt.end_sec = tmap.tick2sec(nt.end_tick)
    out.sort(key=lambda n: (n.start_tick, n.note))
    return out, st
def same_pitch_truncations(notes):
    """截断 (编辑器按钮): 同轨同音高音符的重叠时值 → 每个音符结束
       ≤ 下一同音高音符起始 (链条式按 start 排序逐对钳制; 全包含/同起点
       重复音同样消重叠, 最短保 1 tick)。
       纯计算不改原列表; 返回 [(note, new_end)] (仅含需修改者), 空表 = 无重叠"""
    groups = {}
    for nt in notes: groups.setdefault((nt.tid, nt.note), []).append(nt)
    out = []
    for lst in groups.values():
        lst.sort(key=lambda n: (n.start_tick, n.end_tick))
        for a, b in zip(lst, lst[1:]):
            if a.end_tick > b.start_tick:
                out.append((a, max(a.start_tick + 1, b.start_tick)))
    return out
def retime(notes, tmap):
    """编辑 tick 后重算 sec —— 播放调度/进度条/seek 全依赖 sec, 必须与 tick 同步"""
    for nt in notes:
        nt.start_sec = tmap.tick2sec(nt.start_tick)
        nt.end_sec = tmap.tick2sec(nt.end_tick)
def save_midi(path, tmap, tracks, notes, tsig=(4, 4), tsig_events=None):
    """多轨另存 (type-1 MIDI): 轨道0 = 拍号(多段)+全部速度事件, 其后每轨一条
       (track_name + 该轨音符, 通道沿用轨道首通道, 同 tick 时 off 先于 on, 力度钳 1~127)。
       tsig_events=[(tick,num,den)] 给出时写多段拍号, 否则按单一 tsig"""
    tpb = int(tmap.tpb)
    mid = mido.MidiFile(type=1, ticks_per_beat=tpb, charset='utf-8')  # 中文轨道名
    tr0 = mido.MidiTrack(); mid.tracks.append(tr0)
    if tsig_events:
        meta = [(max(0, int(t)), 0,
                 mido.MetaMessage('time_signature', numerator=int(n),
                                  denominator=int(dd)))
                for t, n, dd in tsig_events]
    else:
        n, d = (int(tsig[0]), int(tsig[1])) if tsig else (4, 4)
        meta = [(0, 0, mido.MetaMessage('time_signature', numerator=n, denominator=d))]
    for tick, tp in zip(tmap.ticks, tmap.tempos):
        meta.append((int(round(tick)), 1, mido.MetaMessage('set_tempo', tempo=int(tp))))
    meta.sort(key=lambda e: (e[0], e[1]))
    last = 0
    for tick, _o, msg in meta:
        msg.time = max(0, tick - last); last = tick; tr0.append(msg)
    tr0.append(mido.MetaMessage('end_of_track', time=0))
    by_tid = {}
    for nt in notes: by_tid.setdefault(nt.tid, []).append(nt)
    tinfo = {t.tid: t for t in tracks}
    for tid in sorted(by_tid):
        t = tinfo.get(tid)
        tr = mido.MidiTrack(); mid.tracks.append(tr)
        if t is not None and t.name:
            tr.append(mido.MetaMessage('track_name', name=t.name, time=0))
        ch = 0 if t is None or t.channel < 0 else t.channel
        ev = []
        # (琶音轮) 分组标记 (tick0, 文本纯 ASCII): "ARPGROUP gid:start:note …"
        _marks = [nt for nt in by_tid[tid] if getattr(nt, 'arp', 0)]
        if _marks:
            txt = 'ARPGROUP ' + ' '.join(
                f'{int(nt.arp)}:{max(0, int(round(nt.start_tick)))}:{int(nt.note)}'
                for nt in _marks)
            ev.append((0, -1, mido.MetaMessage('marker', text=txt)))
        for nt in by_tid[tid]:
            s = max(0, int(round(nt.start_tick)))
            e = max(s + 1, int(round(nt.end_tick)))
            v = max(1, min(127, int(nt.vel)))
            ev.append((s, 1, mido.Message('note_on', note=int(nt.note),
                                          velocity=v, channel=ch)))
            ev.append((e, 0, mido.Message('note_off', note=int(nt.note),
                                          velocity=0, channel=ch)))
        ev.sort(key=lambda x: (x[0], x[1]))          # 同 tick: off(0) 先于 on(1)
        last = 0
        for tick, _o, msg in ev:
            msg.time = max(0, tick - last); last = tick; tr.append(msg)
        tr.append(mido.MetaMessage('end_of_track', time=0))
    mid.save(path)