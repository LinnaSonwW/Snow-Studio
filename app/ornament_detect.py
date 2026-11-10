# -*- coding: utf-8 -*-
"""装饰性快速音群识别 (密度峰检测六层流水线)。

职责:
    识别 MIDI 音符序列中的"装饰性快速音群" (琶音/跑动/颤音等密度突增段落)。
    不用单一快/慢阈值, 而是在密度曲线上做峰检测: 峰 (密度升→短暂保持→回落)
    = 装饰音群; 平台 (持续高位) = 快速旋律, 不折叠。输出 JSON 建议
    (strong/weak/candidate 三级 + 中文解释标签), 供演奏谱折叠与自动打琶音
    标识 (Note.arp) 使用。六层: 预处理 → 特征提取 → 候选检测 → 特征评估
    → 决策 → 输出; 另附 App 集成适配 (notes_to_dicts / apply_suggestions)。
不负责:
    不做声部分离; 不考虑变速 (单一 BPM) 与拍号变化 (bar_beats 可选参预留);
    不直接编辑工程数据 (写 arp 后由调用方触发 _rebuild)。
依赖:
    numpy (缺失时 analyze/run_analysis 返回带 error 的空结果, 不抛异常);
    mido 仅 analyze_midi_ornaments 读文件用; 零 Qt、零项目内 import。

实现裁定 (规格未覆盖处, 按此执行):
    A1 峰检测窗口越界时按边界值钳边取可用样本 (空窗跳过) —— 严格的
       w<i<len-w 会让曲首附近的装饰音永远漏检;
    A2 min(左,右) 综合基线按规格保留: 纯快速跑动的台阶沿会成候选, 但其中
       边界扩展因密度持续高位被 span 上限截断 —— 引入"完整峰规则": 两侧缘
       回落到基线 (或触达曲界) 的完整峰 = 装饰音组, 按原置信度分级;
    A3 start_idx/end_idx 为音符下标 (含端点, 覆盖密度区间 lo..hi 的音符
       lo..hi+1); peak_idx 为密度曲线下标 (峰所在区间);
    A4 (变速轮) 密度曲线换算为秒制 1/ioi_sec (times_sec 按 tmap 分段真实
       秒), 突出度 = (峰密度-基线)/基线 (基线相对) —— 变速前后同一判据
       (4× 对比在任何 BPM 段 prominence 恒为 3), 秒制来自绝对时间故不依赖
       tick 网格是否忠实拍位; 跨度上限仍按拍 (ioi_beat 参数, 缺省回退 1/d);
    A5 (变速轮) tsig 给出时小节归属/列数统计按 bar_starts 逐段累计, 拍点
       距离按各段分母制拍长 (tpb*4/den; 6/8 以八分为一拍);
    A6 (平台折叠轮) 快速旋律平台段/超长跑动不再丢弃: 被跨度/音数截断的
       高密区取"未截断扩展"全区, 挖去已被完整组覆盖的区间后按上限贪婪
       切块 (≤span_limit 拍、≤max_notes 音), 每块作为折叠建议 (plateau 标
       志); 其分级只看排版必要性 —— 邻小节相对列数 ≥ layout_threshold 或
       本小节列数绝对值 ≥ plateau_min_columns (平台内部小节邻居同样密,
       相对指标失效, 用绝对列数兜底) → strong, 否则 candidate; 同小节互斥
       对平台块豁免 (块间构造上互不重叠)。整曲均匀快速 (无密度对比) 仍不
       折叠 —— "平台段"以存在周围慢速织体对比为前提;
    A7 (打标对齐轮) 中位数平滑会把"单区间大休止"从密度曲线上抹掉, 窗口
       基线跨休止取值会让邻段织体互相污染 —— 按 iv > span_limit 的休止把
       曲线切段, 各段独立检测 (窗口/扩展不跨段); 建议 note_indices 为过滤
       后列表下标, run_analysis 附 _src_map (过滤后→原始下标) 供打标精确
       回溯 (和弦/力度删音后不过滤会错位)。
"""
from __future__ import annotations

import bisect

import mido
from typing import Optional

try:
    import numpy as np
except ImportError:                     # 便携基础包无 numpy: 主入口降级不炸
    np = None

DEFAULT_PARAMS = {
    'chord_window': 0.05,               # 同起点判定窗口 (拍)
    'velocity_threshold': 20,           # 力度过滤地板值
    'window_sizes': [3, 5, 8],          # 多尺度峰检测窗口半宽 (音符数)
    'prominence_threshold': 1.2,        # 峰突出度阈值 (密度单位)
    'boundary_factor': 1.2,             # 边界扩展阈值 = baseline * 该系数
    'span_limit': 2.0,                  # 组节拍跨度上限 (拍)
    'max_notes_per_group': 12,          # 组音符数上限
    'confidence_threshold_strong': 0.75,
    'confidence_threshold_weak': 0.60,
    'layout_threshold': 1.5,            # 排版必要性 = 本小节列数/邻小节列数
    'plateau_min_columns': 8,           # 平台折叠: 本小节列数绝对门槛
    'plateau_density_ratio': 0.3,       # 平台延续: 密度 ≥ 种子峰密度×该系数
    'feature_weights': [0.30, 0.30, 0.15, 0.15, 0.05, 0.05],
    'bpm': 120.0,                       # 全曲单一 BPM (变速为后续扩展)
    'bar_beats': 4.0,                   # 每小节拍数 (4/4 假设; 预留拍号联动)
}
_ALGO_VER = 'peak_detection_v1'
_EPS = 1e-9


# ---------------------------------------------------------------- 第一层

def preprocess(notes: list[dict], ppq: int, chord_window: float = 0.05,
               velocity_threshold: int = 20) -> list[dict]:
    """第一层 预处理: 排序 → 同起点和弦归并 → 低力度过滤。

    公式1  和弦簇: 距簇首音 start 差 < chord_window*ppq 的连续音为一簇,
           簇内最低音作代表 (其余丢弃);
    公式2  力度过滤: velocity < max(velocity_threshold, 全曲力度 p10) 删除。
    参数:
        notes: [{'start_tick','pitch','duration','velocity'}, ...] (只读,
               元素引用原样透传, 额外键如 _src_idx 保留)
        ppq: 每拍 tick 数 (<=0 钳 1)
    → 返回: 过滤后的新列表 (元素为输入 dict 引用, 不修改输入)
    """
    if not notes:
        return []
    if ppq is None or int(ppq) <= 0:
        ppq = 1
    ppq = int(ppq)
    seq = sorted(notes, key=lambda d: (float(d['start_tick']), int(d['pitch'])))
    win = max(0.0, float(chord_window)) * ppq
    out: list[dict] = []
    i, n = 0, len(seq)
    while i < n:                                    # 和弦簇归并 (保留最低音)
        j = i + 1
        while j < n and float(seq[j]['start_tick']) - float(seq[i]['start_tick']) < win:
            j += 1
        out.append(min(seq[i:j], key=lambda d: int(d['pitch'])))
        i = j
    floor_v = max(0, int(velocity_threshold))
    if np is not None:
        vels = [int(d['velocity']) for d in seq]
        floor_v = max(floor_v, float(np.percentile(vels, 10)))
    return [d for d in out if int(d['velocity']) >= floor_v - _EPS]


# ---------------------------------------------------------------- 第二层

def _moving_median(a: 'np.ndarray', half: int = 2) -> 'np.ndarray':
    """移动窗口中位数平滑 (窗口 2*half+1, 边缘以边界值钳边补齐)。"""
    if a.size == 0 or half <= 0:
        return a
    pad = np.pad(a, half, mode='edge')
    win = np.lib.stride_tricks.sliding_window_view(pad, 2 * half + 1)
    return np.median(win, axis=1)


def extract_features(notes: list[dict], ppq: int, bpm: float = 120.0,
                     bar_beats: float = 4.0, times_sec=None,
                     tsig=None) -> dict:
    """第二层 特征提取。公式:
    1  ioi_beat[i] = (start[i+1]-start[i])/ppq;
       ioi_sec = diff(times_sec) (times_sec 按分段真实秒) 或 ioi_beat*60/bpm
    2  density[i] = 1/max(ioi_sec[i],1e-6) (秒制密度), 移动中位数平滑 (半宽1)
    3  measure_id: tsig 给出时按 bar_starts 逐段累计小节号, 否则
       floor(start/(ppq*bar_beats))
    4  beat_distance = min(frac, 1-frac); 拍长 = tpb*4/den (tsig 分段分母制,
       6/8 以八分为一拍), 无 tsig 时 = 每拍 ppq tick
    5  小节统计: columns = 独立起点数; median_ioi = 小节内相邻 IOI 中位数 (秒)
    6  global_baseline_ioi = 去掉前后 5% 分位外样点后的 IOI 中位数 (秒)
    参数:
        times_sec: 每音符绝对秒 (与 notes 等长; 变速曲按 tmap 分段换算)
        tsig: 分段拍号表 (鸭子: bar_starts/bar_ticks_at/at; 零项目 import)
    → 返回 dict: density_curve / ioi_beat / ioi_sec / measure_ids /
      beat_distances / measure_stats / global_baseline_ioi (+ ppq/bpm 附加)
    """
    if ppq is None or int(ppq) <= 0:
        ppq = 480
    ppq = int(ppq)
    bpm = float(bpm) if bpm and float(bpm) > 0 else 120.0
    bar_beats = float(bar_beats) if bar_beats and float(bar_beats) > 0 else 4.0
    n = len(notes)
    if n == 0:
        return {'density_curve': np.zeros(0), 'ioi_beat': np.zeros(0),
                'ioi_sec': np.zeros(0), 'measure_ids': np.zeros(0, dtype=int),
                'beat_distances': np.zeros(0), 'measure_stats': {},
                'global_baseline_ioi': 0.0, 'ppq': ppq, 'bpm': bpm}
    st = np.array([float(d['start_tick']) for d in notes])
    ioi_beat = np.diff(st) / ppq
    if times_sec is not None and len(times_sec) == n:
        ioi_sec = np.diff(np.asarray(times_sec, dtype=float))
    else:
        ioi_sec = ioi_beat * (60.0 / bpm)
    density = _moving_median(1.0 / np.maximum(ioi_sec, 1e-6), 1)
    # 半宽 1 (窗口 3): 半宽 2 会把间隔 <=2 个慢区间的两束琶音桥接成假平台,
    # 破坏"峰 vs 平台"判别 (混排双琶音场景实测), 故取最小有效平滑
    # 小节归属 + 拍点距离 (tsig 给出即逐段累计 —— 单段非 4/4 (如整曲 6/8)
    # 也必须走分段拍格; 无 tsig 回退单一 bar_beats)
    if tsig is not None and n:
        bars = list(tsig.bar_starts(0, int(st[-1]) + 1, limit=4096))
        bt0 = np.array([float(b[0]) for b in bars])
        bno = np.array([int(b[1]) for b in bars], dtype=int)
        blow = np.array([float(ppq * 4) / float(tsig.at(int(b[0]))[1])
                         for b in bars])        # 各段一拍 tick 数 (分母制)
        idx = np.searchsorted(bt0, st, 'right') - 1
        measure_ids = bno[np.clip(idx, 0, len(bars) - 1)]
        bpos = (st - bt0[np.clip(idx, 0, len(bars) - 1)]) / blow[
            np.clip(idx, 0, len(bars) - 1)]
        frac = bpos - np.floor(bpos)
        bdist = np.minimum(frac, 1.0 - frac)
    else:
        measure_ids = np.floor(st / (ppq * bar_beats)).astype(int) + 1
        bpos = st / ppq
        frac = bpos - np.floor(bpos)
        bdist = np.minimum(frac, 1.0 - frac)
    mstats: dict[int, dict] = {}
    for m in np.unique(measure_ids):
        sel = measure_ids == m
        inner = ioi_sec[sel[:-1] & sel[1:]]         # 两端都在本小节内的 IOI
        mstats[int(m)] = {
            'columns': int(np.unique(st[sel]).size),
            'median_ioi': float(np.median(inner)) if inner.size else 0.0}
    if ioi_sec.size:
        lo5, hi95 = np.percentile(ioi_sec, [5.0, 95.0])
        core = ioi_sec[(ioi_sec >= lo5) & (ioi_sec <= hi95)]
        gbase = float(np.median(core if core.size else ioi_sec))
    else:
        gbase = 0.0                                 # 单音符: 无 IOI 可言
    return {'density_curve': density, 'ioi_beat': ioi_beat, 'ioi_sec': ioi_sec,
            'measure_ids': measure_ids, 'beat_distances': bdist,
            'measure_stats': mstats, 'global_baseline_ioi': gbase,
            'ppq': ppq, 'bpm': bpm}


# ---------------------------------------------------------------- 第三层

def _expand_edge(d: 'np.ndarray', i: int, limit: float,
                 span_limit: float, max_notes: int, forward: bool,
                 iv: 'np.ndarray' = None):
    """从峰 i (密度下标) 向单侧扩展 (抬升阈值 limit 由调用方给出)。

    扩展条件 density[j] > limit (完整峰 = 基线*bf; 平台全区 = max(基线*bf,
    ratio*种子密度) —— 防止种子旁慢速间隔把极小基线带出去, 见 A6);
    空隙容忍: 连续 2 个区间低于阈值才停 (允许 1 个慢区间孔洞); 越界停视为
    完整。跨度按 iv 全区间累计 (孔洞也计入, 尾部越出组的低区间回减), 超过
    span_limit 或音符数超过 max_notes 即被截断 → 不完整 (平台碎片)。
    → 返回 (end 下标含, complete bool)
    """
    iv = 1.0 / d if iv is None else iv
    end = i
    span = float(iv[i])
    count = 2                                   # 峰区间两端各 1 音
    gap = 0
    step = 1 if forward else -1
    j = i + step
    last = i
    while 0 <= j < d.size:
        span += float(iv[j])                    # 全区间累计 (尾部回减)
        last = j
        if d[j] > limit:
            if span > span_limit + _EPS:
                return end, False
            if count + 1 > max_notes:
                return end, False
            end = j
            count += 1
            gap = 0
        else:
            if float(iv[j]) > span_limit + _EPS:
                break                           # 大休止 (超过块上限) = 硬边界
            gap += 1
            if gap >= 2:
                break                           # 密度回落 → 完整峰缘
        j += step
    while last != end:                          # 回减尾部越出组的低区间
        span -= float(iv[last])
        last -= step
    return end, True


def _detect_range(d: 'np.ndarray', iv: 'np.ndarray', off: int,
                  window_sizes, prominence_threshold: float,
                  boundary_factor: float, span_limit: float,
                  max_notes: int, plateau_density_ratio: float) -> list[dict]:
    """单段 (无大休止) 峰检测 + 平台切块; 下标统一 +off 折回全曲坐标。"""
    n = d.size
    sizes = [max(1, int(w)) for w in (window_sizes or (3, 5, 8))]
    best_base = np.full(n, np.inf)
    best_prom = np.full(n, -np.inf)
    votes = np.zeros(n, dtype=int)
    for w in sizes:
        pad = np.pad(d, w, mode='edge')
        win = np.lib.stride_tricks.sliding_window_view(pad, w)
        left = np.percentile(win[0:n], 75, axis=1)              # d[i-w .. i-1]
        right = np.percentile(win[w + 1:w + 1 + n], 75, axis=1)  # d[i+1 .. i+w]
        base = np.minimum(left, right)
        prom = (d - base) / np.maximum(base, 1e-9)              # 基线相对 (A4)
        pk = np.zeros(n, dtype=bool)
        pk[1:n - 1] = prom[1:n - 1] >= prominence_threshold
        votes += pk
        upd = pk & (prom > best_prom)
        best_base[upd] = base[upd]
        best_prom[upd] = prom[upd]
    groups = []
    for ii in np.nonzero(votes >= 2)[0]:
        i = int(ii)
        base = float(best_base[i])
        lo, ok_l = _expand_edge(d, i, base * boundary_factor,
                                span_limit, max_notes, forward=False, iv=iv)
        hi, ok_r = _expand_edge(d, i, base * boundary_factor,
                                span_limit, max_notes, forward=True, iv=iv)
        groups.append({'start_idx': lo, 'end_idx': hi + 1, 'peak_idx': i,
                       'baseline': base, 'prominence': float(best_prom[i]),
                       'span': float(np.sum(iv[lo:hi + 1])),
                       'complete': bool(ok_l and ok_r)})
    groups.sort(key=lambda g: g['start_idx'])
    merged: list[dict] = []
    for g in groups:
        if merged:
            p = merged[-1]
            if g['start_idx'] - p['end_idx'] <= 2:            # 间隔 <= 2 音
                lo = min(p['start_idx'], g['start_idx'])
                hi = max(p['end_idx'], g['end_idx'])
                span = float(np.sum(iv[lo:hi + 1]))
                if span <= span_limit + _EPS:
                    keep = p if p['prominence'] >= g['prominence'] else g
                    merged[-1] = {'start_idx': lo, 'end_idx': hi,
                                  'peak_idx': keep['peak_idx'],
                                  'baseline': keep['baseline'],
                                  'prominence': keep['prominence'],
                                  'span': span,
                                  'complete': bool(p['complete'] and g['complete'])}
                    continue
        merged.append(dict(g))
    final = [g for g in merged if g['complete']]
    # ---- (平台折叠轮 A6) 被跨度/音数截断的高密区 → 全区切块折叠 ----
    covered_iv = set()
    for g in final:                         # 完整组覆盖的区间 (音符 s..e-1)
        covered_iv.update(range(g['start_idx'], g['end_idx']))
    extents = []
    for ii in np.nonzero(votes >= 2)[0]:
        i = int(ii)
        if any(g['peak_idx'] == i for g in final):
            continue                        # 完整组已折叠的峰跳过
        base = float(best_base[i])
        # 未截断扩展 (忽略跨度/音数上限, 密度回落即停) = 平台全区;
        # 抬升阈值带种子密度比例下限 (A6): 防止种子旁慢速间隔的极小基线
        # 把普通织体卷进平台区
        limit = max(base * boundary_factor,
                    plateau_density_ratio * float(d[i]))
        lo, _ = _expand_edge(d, i, limit, float('inf'),
                             10 ** 9, forward=False, iv=iv)
        hi, _ = _expand_edge(d, i, limit, float('inf'),
                             10 ** 9, forward=True, iv=iv)
        extents.append([lo, hi, i, base, float(best_prom[i])])
    extents.sort()
    merged_ex = []
    for ex in extents:                      # 同区多峰 (入沿/出沿) 合并范围
        if merged_ex and ex[0] <= merged_ex[-1][1] + 1:
            merged_ex[-1][1] = max(merged_ex[-1][1], ex[1])
        else:
            merged_ex.append(ex)
    plateau = []
    for a, b, seed, base, prom in merged_ex:
        k = a
        while k <= b:                       # 挖去已覆盖区间 → 贪婪切块
            while k <= b and k in covered_iv:
                k += 1
            if k > b:
                break
            s0 = k
            span = 0.0
            cnt = 1
            e0 = k
            while e0 <= b and e0 not in covered_iv:
                w = float(iv[e0])
                if e0 > s0 and (span + w > span_limit + _EPS
                                or cnt + 1 > max_notes):
                    break                   # 上限触顶 → 本块收口
                span += w
                cnt += 1
                e0 += 1
            end_i = max(e0 - 1, s0)
            if end_i + 1 - s0 + 1 >= 3:     # 平台块 ≥3 音 (2 音非"段")
                plateau.append({
                    'start_idx': int(s0), 'end_idx': int(end_i + 1),
                    'peak_idx': int(seed), 'baseline': base,
                    'prominence': prom,
                    'span': float(np.sum(iv[s0:end_i + 1])),
                    'complete': True, 'plateau': True})
            k = end_i + 1
    final.extend(plateau)
    return [{**g, 'start_idx': g['start_idx'] + off,
             'end_idx': g['end_idx'] + off,
             'peak_idx': g['peak_idx'] + off} for g in final]


def detect_peaks(density_curve, window_sizes=(3, 5, 8),
                 prominence_threshold: float = 1.2,
                 boundary_factor: float = 1.2, span_limit: float = 2.0,
                 max_notes: int = 12, ioi_beat=None,
                 plateau_density_ratio: float = 0.3) -> list[dict]:
    """第三层 候选检测: 多尺度峰检测 + 边界扩展 + 相邻峰合并 + 平台切块。

    公式1  单尺度峰: 左基线 = p75(density[i-w:i]), 右基线 = p75(density[i+1:
           i+1+w]) (越界按边界值钳边, 见 A1); 综合基线 = min(左, 右);
           突出度 = (density[i] - 综合基线)/基线 (基线相对, 秒制密度下变速
           前后同一判据, 见 A4) >= prominence_threshold 即峰;
    公式2  多尺度验证: 至少在 2 个窗口半宽下都是峰;
    公式3  边界扩展: density[j] > baseline*boundary_factor, 连续 2 区间低于
           阈值才停; 跨度 <= span_limit 拍 (ioi_beat, 缺省 1/density)、
           音符数 <= max_notes;
    公式4  相邻峰合并: 间隔 <= 2 音 且 合并后跨度 <= span_limit;
    公式5  (大休止分段) ioi > span_limit 的区间 = 乐句硬边界: 中位数平滑会
           把单区间休止从密度曲线上抹掉, 故按 iv 切段后各段独立检测, 窗口
           与扩展不跨段 (A7)。
    参数: ioi_beat = 每区间拍数 (与密度曲线等长; 跨度按拍计)。
    → 返回: [{'start_idx','end_idx' (音符下标含端点), 'peak_idx' (密度下标),
             'baseline','prominence' (基线相对), 'span' (拍), 'complete',
             'plateau' (平台分段块, 见 A6)}, ...] (按 start_idx 升序)
    """
    if np is None:
        return []
    d_all = np.asarray(density_curve, dtype=float)
    n = d_all.size
    if n < 3:
        return []
    iv_all = (np.asarray(ioi_beat, dtype=float)
              if ioi_beat is not None and len(ioi_beat) == n else 1.0 / d_all)
    # (A7) 大休止切段: 各段独立检测 (窗口/扩展不跨段, 段基线不受邻段污染)
    cuts = np.nonzero(iv_all > span_limit + _EPS)[0]
    bounds = [0] + [int(c) + 1 for c in cuts] + [n]
    out = []
    for a, b in zip(bounds[:-1], bounds[1:]):
        if b - a >= 3:
            out.extend(_detect_range(d_all[a:b], iv_all[a:b], a, window_sizes,
                                     prominence_threshold, boundary_factor,
                                     span_limit, max_notes,
                                     plateau_density_ratio))
    out.sort(key=lambda g: g['start_idx'])
    return out


# ---------------------------------------------------------------- 第四层

def evaluate_features(candidate_groups: list[dict], notes: list[dict],
                      features: dict, weights=None) -> list[dict]:
    """第四层 特征评估: 7 特征 + 加权置信度 + 解释标签。

    特征: span 跨度(拍); contrast 组内IOI中位数/邻小节IOI中位数 (秒制,
    变速时物理时间可比; 邻小节缺失回退自身小节→全局基线); cv 组内IOI变异
    系数 (秒制, 常速下与拍制等值); landing 落点 (末音到拍点距离归一, 分段
    分母制拍格); tail_slowdown 尾部减速 (秒制); abs_speed 绝对速度
    (>0.3s→-1, <0.05s→+0.5); layout_impact 本小节列数/邻小节平均列数
    (缺失回退 1.0)。
    置信度 = w0*span分 + w1*contrast分 + w2*landing + w3*tail + w4*cv分 +
    w5*abs_speed, 钳到 [0,1]; 标签: 短促/突出密集/落在拍点/尾部减速/不均匀间隔。
    → 返回: 每组附加 'measure' / 'features' / 'confidence' / 'reasons'
    """
    w = list(weights) if weights and len(weights) >= 6 else \
        [0.30, 0.30, 0.15, 0.15, 0.05, 0.05]
    ppq = float(features.get('ppq', 480) or 480)
    ioi_sec = features['ioi_sec']
    measure_ids = features['measure_ids']
    bdist = features['beat_distances']
    mstats = features['measure_stats']
    gbase = float(features.get('global_baseline_ioi', 0.0))
    out = []
    for g in candidate_groups or []:
        s, e = int(g['start_idx']), int(g['end_idx'])
        m = int(measure_ids[s])
        inner = ioi_sec[s:e]                        # 组内 IOI (秒)
        mean_i = float(np.mean(inner)) if inner.size else 0.0
        nbrs = [mstats[k] for k in (m - 1, m + 1) if k in mstats]
        # 1 span 跨度 (末音起点 - 首音起点, 拍)
        span = (float(notes[e]['start_tick']) - float(notes[s]['start_tick'])) / ppq
        # 2 contrast 对比度 (秒制; 邻小节中位缺失回退: 自身小节 → 全局基线;
        #   回退到自身小节时剔除组内区间 —— 组填满小节时含组中位数会自比自)
        meds = [float(nb['median_ioi']) for nb in nbrs if nb['median_ioi'] > 0]
        if meds:
            denom = float(np.mean(meds))
        else:
            own_iv = [float(ioi_sec[k]) for k in range(ioi_sec.size)
                      if int(measure_ids[k]) == m
                      and int(measure_ids[k + 1]) == m
                      and not (s <= k < e)]
            own_med = float(np.median(own_iv)) if own_iv else 0.0
            denom = own_med if own_med > 0 else gbase
        contrast = (float(np.median(inner)) / denom) if denom > 0 and inner.size else 1.0
        # 3 cv 变异系数 (秒制; 常速与拍制等值)
        cv = (float(np.std(inner)) / mean_i) if mean_i > 0 and inner.size else 0.0
        # 4 landing 落点 (0.15 拍内贴拍点给满分)
        landing = max(0.0, min(1.0, 1.0 - float(bdist[e]) / 0.15))
        # 5 tail_slowdown 尾部减速 (秒制: 组后秒 IOI/组内均值 - 1)/2, 钳 [0,1])
        tail = 0.0
        if e < ioi_sec.size and mean_i > 0:
            tail = max(0.0, min(1.0, (float(ioi_sec[e]) / mean_i - 1.0) / 2.0))
        # 6 abs_speed 绝对速度
        seg = ioi_sec[s:e]
        if seg.size:
            avg_s, min_s = float(np.mean(seg)), float(np.min(seg))
            abs_speed = -1.0 if avg_s > 0.3 else (0.5 if min_s < 0.05 else 0.0)
        else:
            abs_speed = 0.0
        # 7 layout_impact 排版影响 (邻小节缺失/全零回退 1.0)
        cols = float(mstats.get(m, {}).get('columns', 0))
        ncols = [float(nb['columns']) for nb in nbrs if nb['columns'] > 0]
        layout = cols / float(np.mean(ncols)) if ncols and cols > 0 else 1.0
        span_score = 1.0 if span <= 1.5 else (0.5 if span <= 2.5 else 0.0)
        contrast_score = 1.0 if contrast <= 0.4 else (0.5 if contrast <= 0.6 else 0.0)
        cv_score = 0.5 if cv > 0.3 else 0.0
        conf = (w[0] * span_score + w[1] * contrast_score + w[2] * landing +
                w[3] * tail + w[4] * cv_score + w[5] * abs_speed)
        conf = max(0.0, min(1.0, conf))
        reasons = []
        if span <= 1.5:
            reasons.append('短促')
        if contrast <= 0.5:
            reasons.append('突出密集')
        if landing > 0.7:
            reasons.append('落在拍点')
        if tail > 0.5:
            reasons.append('尾部减速')
        if cv > 0.3:
            reasons.append('不均匀间隔')
        out.append({**g, 'measure': m,
                    'features': {'span': span, 'contrast': contrast, 'cv': cv,
                                 'landing': landing, 'tail_slowdown': tail,
                                 'abs_speed': abs_speed,
                                 'layout_impact': layout, 'columns': cols},
                    'confidence': conf, 'reasons': reasons})
    return out


# ---------------------------------------------------------------- 第五层

def make_decisions(evaluated_groups: list[dict],
                   threshold_strong: float = 0.75,
                   threshold_weak: float = 0.60,
                   layout_threshold: float = 1.5,
                   max_notes: int = 12,
                   plateau_min_columns: int = 8) -> dict:
    """第五层 决策: 置信度 × 排版必要性 × 音数约束 分级 + 同小节互斥。

    规则: strong = conf>=强阈 且 layout>=排版阈 且 音数<=上限;
          weak   = conf>=弱阈 且 同上约束;
          candidate = conf>=0.5 且 音数<=上限; 其余拒绝。
    平台分段块 (plateau, A6) 只看排版必要性: 邻小节相对列数 >= layout_threshold
    或 本小节列数 >= plateau_min_columns → strong (折叠), 否则 candidate;
    同小节互斥对其豁免 (块间构造上互不重叠)。
    → 返回: {'strong_suggestions','weak_suggestions','candidates'} 各组列表
    """
    recs = {'strong_suggestions': [], 'weak_suggestions': [], 'candidates': []}
    pool = sorted(evaluated_groups or [],
                  key=lambda g: (-float(g['confidence']), int(g['start_idx'])))
    taken: set[int] = set()
    kept = []
    for g in pool:
        if g.get('plateau'):                        # 平台块豁免互斥
            kept.append(g)
            continue
        m = int(g['measure'])
        if m in taken:
            continue                                # 同小节互斥
        taken.add(m)
        kept.append(g)
    for g in kept:
        cnt = int(g['end_idx']) - int(g['start_idx']) + 1
        c = float(g['confidence'])
        li = float(g['features'].get('layout_impact', 1.0))
        if cnt > max_notes:
            continue
        if g.get('plateau'):
            if (li >= layout_threshold - _EPS
                    or float(g['features'].get('columns', 0))
                    >= plateau_min_columns - _EPS):
                recs['strong_suggestions'].append(g)   # 折叠 (排版必要)
            else:
                recs['candidates'].append(g)
            continue
        if c >= threshold_strong - _EPS and li >= layout_threshold - _EPS:
            recs['strong_suggestions'].append(g)
        elif c >= threshold_weak - _EPS and li >= layout_threshold - _EPS:
            recs['weak_suggestions'].append(g)
        elif c >= 0.5 - _EPS:
            recs['candidates'].append(g)
    for tier in recs:                                   # 按小节序稳定输出
        recs[tier].sort(key=lambda g: (int(g['measure']), int(g['start_idx'])))
    return recs


# ---------------------------------------------------------------- 第六层

def format_output(recommendations: dict, notes: list[dict],
                  algorithm_version: str = _ALGO_VER,
                  parameters: Optional[dict] = None,
                  features: Optional[dict] = None) -> dict:
    """第六层 输出: 打包成 JSON 兼容 dict (json.dumps 可直接序列化)。

    → 返回: {'algorithm_version','parameters','strong_suggestions',
             'weak_suggestions','candidates','global_stats'}; 每组含
             group_id/note_indices/measure/confidence/features/reasons;
             global_stats 由 features 取 (缺省时给零值)。
    """
    def _entry(g: dict, gid: int) -> dict:
        return {'group_id': 'g%03d' % gid,
                'note_indices': list(range(int(g['start_idx']),
                                           int(g['end_idx']) + 1)),
                'measure': int(g.get('measure', 0)),
                'confidence': round(float(g['confidence']), 4),
                'features': {k: round(float(v), 6)
                             for k, v in g['features'].items()},
                'reasons': list(g.get('reasons', [])),
                'plateau': bool(g.get('plateau', False))}

    out = {'algorithm_version': algorithm_version,
           'parameters': dict(parameters or {}),
           'strong_suggestions': [], 'weak_suggestions': [], 'candidates': []}
    gid = 1
    for tier in ('strong_suggestions', 'weak_suggestions', 'candidates'):
        entries = []
        for g in recommendations.get(tier, []) or []:
            entries.append(_entry(g, gid))
            gid += 1
        out[tier] = entries
    if features is not None:
        tm = float(features.get('global_baseline_ioi', 0.0))
        tot = len(features.get('measure_stats') or {})
    else:
        tm, tot = 0.0, 0
    out['global_stats'] = {'track_median_ioi': round(tm, 6),
                           'total_measures': tot,
                           'avg_notes_per_measure': (len(notes) / tot) if tot else 0.0}
    return out


# ---------------------------------------------------------------- 主入口

def _empty_result(parameters: Optional[dict] = None,
                  error: str = '') -> dict:
    """空结果骨架 (边界/异常兜底, 不向上抛异常)。"""
    r = {'algorithm_version': _ALGO_VER, 'parameters': dict(parameters or {}),
         'strong_suggestions': [], 'weak_suggestions': [], 'candidates': [],
         'global_stats': {'track_median_ioi': 0.0, 'total_measures': 0,
                          'avg_notes_per_measure': 0.0}}
    if error:
        r['error'] = error
    return r


class _SeqTMap:
    """独立文件路径用最小分段速度表 (tick→秒; 与 TempoMap 鸭子兼容子集)。"""

    def __init__(self, ppq: int, tempos: list):
        ev = {}
        for t, tp in tempos:
            ev[max(0, int(t))] = max(1, int(tp))
        self.ticks = sorted(ev)
        self.tempos = [ev[t] for t in self.ticks]
        self.tpb = max(1, int(ppq))
        self.cum = [0.0]
        for i in range(1, len(self.ticks)):
            self.cum.append(self.cum[-1] +
                            mido.tick2second(self.ticks[i] - self.ticks[i - 1],
                                             self.tpb, self.tempos[i - 1]))

    def sec(self, tick) -> float:
        i = bisect.bisect_right(self.ticks, int(tick)) - 1
        i = max(0, min(i, len(self.ticks) - 1))
        return self.cum[i] + mido.tick2second(int(tick) - self.ticks[i],
                                              self.tpb, self.tempos[i])


class _SeqTsig:
    """独立文件路径用最小分段拍号表 (bar_starts/bar_ticks_at/at/measure_start
    鸭子兼容; 相邻同值段合并, tick=0 必有段)。"""

    LIMIT = 4096

    def __init__(self, ppq: int, events: list):
        ev = {}
        for t, n, d in events:
            ev[max(0, int(t))] = (max(1, int(n)), max(1, int(d)))
        seg = [(t, ev[t][0], ev[t][1]) for t in sorted(ev)]
        if seg[0][0] != 0:
            seg.insert(0, (0, seg[0][1], seg[0][2]))
        self._seg = [seg[0]]
        for s in seg[1:]:
            if s[1:] != self._seg[-1][1:]:
                self._seg.append(s)
        self.tpb = max(1, int(ppq))

    def events(self):
        return list(self._seg)

    def at(self, tick):
        cur = self._seg[0][1:]
        for t, n, d in self._seg:
            if int(tick) >= t:
                cur = (n, d)
            else:
                break
        return cur

    def bar_ticks_at(self, tick) -> float:
        n, d = self.at(tick)
        return max(1.0, self.tpb * 4.0 * n / d)

    def measure_start(self, tick) -> int:
        """tick 所在小节的起点 tick (段内按段宽整除; 段边界强制小节线)。"""
        t = int(tick)
        for i, (t0, n, d) in enumerate(self._seg):
            t1 = self._seg[i + 1][0] if i + 1 < len(self._seg) else None
            if t1 is not None and t >= t1:
                continue
            w = self.bar_ticks_at(t0)
            return int(t0 + int((t - t0) // w) * w)
        return 0

    def bar_starts(self, lo, hi, limit: int = 4096):
        """[lo,hi) 内各小节起点 (tick, 1基全局小节号) 升序, 上限 limit 条。"""
        out = []
        lo = max(0, int(lo))
        hi = int(hi)
        no = 1
        for i, (t0, n, d) in enumerate(self._seg):
            w = max(1, int(round(self.tpb * 4.0 * n / d)))
            t1 = self._seg[i + 1][0] if i + 1 < len(self._seg) else hi
            bt = t0
            while bt < t1 and bt < hi:
                if bt >= lo:
                    out.append((bt, no))
                    if len(out) >= min(int(limit), self.LIMIT):
                        return out
                no += 1
                bt += w
        return out


def run_analysis(notes: list[dict], ppq: int,
                 parameters: Optional[dict] = None,
                 times_sec=None, tsig=None) -> dict:
    """对内存音符 dict 直接跑六层流水线 (analyze_midi_ornaments 的内核,
    也是 App 集成入口: 配 notes_to_dicts 使用)。

    参数: times_sec 每音符绝对秒 (变速曲按 tmap 分段换算传入); tsig 分段
    拍号表 (鸭子 bar_starts/bar_ticks_at/at)。
    """
    params = dict(DEFAULT_PARAMS)
    if parameters:
        params.update(parameters)
    if np is None:
        return _empty_result(params, 'numpy 未安装, 密度分析不可用')
    if ppq is None or int(ppq) <= 0:
        ppq = 480
    filtered = preprocess(notes or [], int(ppq), params['chord_window'],
                          params['velocity_threshold'])
    if times_sec is not None and len(times_sec) == len(notes or []):
        # 和弦/力度过滤会删音 → times 按对象身份同步过滤 (错位即静默失效)
        keep = {id(d): times_sec[i] for i, d in enumerate(notes or [])}
        times_sec = [keep[id(d)] for d in filtered]
    features = extract_features(filtered, int(ppq), float(params['bpm']),
                                float(params['bar_beats']),
                                times_sec=times_sec, tsig=tsig)
    cands = detect_peaks(features['density_curve'], params['window_sizes'],
                         params['prominence_threshold'],
                         params['boundary_factor'], params['span_limit'],
                         int(params['max_notes_per_group']),
                         ioi_beat=features['ioi_beat'],
                         plateau_density_ratio=float(
                             params['plateau_density_ratio']))
    evaluated = evaluate_features(cands, filtered, features,
                                  weights=params['feature_weights'])
    recs = make_decisions(evaluated, params['confidence_threshold_strong'],
                          params['confidence_threshold_weak'],
                          params['layout_threshold'],
                          int(params['max_notes_per_group']),
                          int(params['plateau_min_columns']))
    result = format_output(recs, filtered, _ALGO_VER, params, features=features)
    # (打标对齐轮) 过滤后→原始音符下标映射: 建议 note_indices 是过滤后
    # 列表的下标, apply_suggestions 经此回溯 (和弦/力度删音后不过滤会错位)
    result['_src_map'] = ([int(d['_src_idx']) for d in filtered]
                          if any('_src_idx' in d for d in filtered) else None)
    return result


def analyze_midi_ornaments(midi_path, parameters: Optional[dict] = None) -> dict:
    """主入口: 读 MIDI 文件 (合并全轨) → 六层流水线 → JSON 建议。

    变速/变拍: 文件内 set_tempo / time_signature 元事件逐段解析 —— IOI 按
    真实秒制换算、小节归属按分段拍号 (无元事件时回退 120 BPM / 4/4)。
    参数: midi_path 文件路径; parameters 覆盖 DEFAULT_PARAMS 的任意子集。
    → 返回: JSON 兼容 dict; 文件不可读/numpy 缺失/无音符/分析异常时返回带
      'error' 键 (可读但无音符时不带) 的空结果, 不抛异常。
    """
    params = dict(DEFAULT_PARAMS)
    if parameters:
        params.update(parameters)
    if np is None:
        return _empty_result(params, 'numpy 未安装, 密度分析不可用')
    try:
        mid = mido.MidiFile(midi_path)
    except Exception as exc:
        return _empty_result(params, 'MIDI 读取失败: %s' % exc)
    ppq = int(mid.ticks_per_beat or 480)
    notes = []
    tempos: list = []
    tsigs: list = []
    for track in mid.tracks:
        time = 0
        for msg in track:
            time += msg.time
            if msg.type == 'set_tempo':
                tempos.append((time, msg.tempo))
            elif msg.type == 'time_signature':
                tsigs.append((time, msg.numerator, msg.denominator))
            elif msg.type == 'note_on' and msg.velocity > 0:
                notes.append({'start_tick': time, 'pitch': int(msg.note),
                              'velocity': int(msg.velocity), 'duration': 0})
    if not notes:
        return _empty_result(params)
    try:
        tmap = _SeqTMap(ppq, tempos or [(0, 500000)])
        tsig = _SeqTsig(ppq, tsigs or [(0, 4, 4)])
        times = [tmap.sec(d['start_tick']) for d in notes]
        return run_analysis(notes, ppq, params, times_sec=times, tsig=tsig)
    except Exception as exc:
        return _empty_result(params, '分析失败: %s' % exc)


# ------------------------------------------------------- App 集成适配

def notes_to_dicts(notes: list) -> list[dict]:
    """Note-like (start_tick/note/vel 或 velocity/end_tick) → 规格 dict。

    附 '_src_idx' 记录原列表下标: preprocess 会筛除音符, 下标经此回溯,
    apply_suggestions 才能把建议映射回原音符 (零项目 import, 鸭子类型)。
    """
    return [{'start_tick': int(nt.start_tick), 'pitch': int(nt.note),
             'duration': int(nt.end_tick) - int(nt.start_tick),
             'velocity': int(getattr(nt, 'vel', getattr(nt, 'velocity', 0))),
             '_src_idx': i}
            for i, nt in enumerate(notes)]


def apply_suggestions(result: dict, notes: list,
                      dicts: Optional[list[dict]] = None,
                      tier: str = 'strong_suggestions',
                      start_gid: int = 1) -> list:
    """把建议组写回音符 arp 标识 (gid 自 start_gid 起每组 +1, 99 后回 1)。

    只写 arp==0 的音 (手动标识优先, 已有组号不动); note_indices 是过滤后
    列表的下标 —— 优先用 result['_src_map'] (run_analysis 附带的过滤后→
    原始下标映射) 回溯; 缺省时退回 dicts 的 _src_idx (要求 dicts 恰为未
    过滤的全量列表, 仅在确认无删音时正确); 多层级联时按层传 start_gid
    续号, 防止跨层撞号。
    → 返回: 实际写入的 (note, gid) 列表
    """
    src_map = result.get('_src_map')
    if src_map is None and dicts:
        src_map = [int(d.get('_src_idx', i)) for i, d in enumerate(dicts)]
    changed = []
    gid = max(0, int(start_gid) - 1)
    if gid < 1:
        gid = 0
    for sug in result.get(tier, []) or []:
        gid = (gid % 99) + 1
        for idx in sug.get('note_indices', []):
            ni = (src_map[idx] if (src_map and 0 <= idx < len(src_map)
                                   and src_map[idx] >= 0) else idx)
            if not isinstance(ni, int) or not (0 <= ni < len(notes)):
                continue
            nt = notes[ni]
            if int(getattr(nt, 'arp', 0) or 0) > 0:
                continue
            nt.arp = gid
            changed.append((nt, gid))
    return changed
