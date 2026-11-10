# -*- coding: utf-8 -*-
"""节拍分析 (四期): 源音频 -> BPM/拍号/拍点, 供转录后自动标记。
   引擎降级链: 系统 Python 桥接 BeatNet (需 pip 安装 BeatNet + torch,
   扒谱同环境) -> 本进程 librosa 拍点跟踪 (多音高扩展包自带) -> None。
   纯逻辑零 UI; 测试直调 analyze_audio。"""

import json
import os
import subprocess
import sys

from PySide6.QtCore import QThread, Signal

CREATE_NO_WINDOW = 0x08000000


def _ensure_vendor():
    """librosa 链所在 vendor 目录补进 sys.path (便携/开发双布局; 幂等)"""
    try:
        from paths import vendor_dir
        vd = vendor_dir()
        if os.path.isdir(vd) and vd not in sys.path:
            sys.path.append(vd)
    except Exception:
        pass


def find_beatnet_interp():
    """探测装有 BeatNet 的系统 Python (扒谱桥接同源候选列表); 无 -> None"""
    try:
        from sys_bridge import _candidate_pythons
        cands = _candidate_pythons()
    except Exception:
        return None
    for py in cands:
        try:
            r = subprocess.run(
                [py, "-c", "import BeatNet"],
                capture_output=True, text=True, timeout=120,
                creationflags=CREATE_NO_WINDOW)
            if r.returncode == 0:
                return py
        except Exception:
            continue
    return None


_BEATNET_RUNNER = r"""
import json, sys
audio = sys.argv[1]
try:
    from BeatNet.BeatNet import BeatNet
    m = BeatNet(1, mode="offline", inference_model="DBN", plot=[], thread=False)
    out = m.process(audio)
    beats = [[float(r[0]), int(r[1])] for r in out]
    print(json.dumps({"ok": True, "beats": beats}))
except Exception as e:
    print(json.dumps({"ok": False, "err": str(e)}))
"""


def _beatnet_subprocess(interp, audio_path):
    """在 interp (系统 Python) 里跑 BeatNet 分析, 返回 beats=[[秒,拍号]...] 或 None"""
    import tempfile
    runner = os.path.join(tempfile.gettempdir(), "snow_beatnet_run.py")
    with open(runner, "w", encoding="utf-8") as f:
        f.write(_BEATNET_RUNNER)
    try:
        r = subprocess.run(
            [interp, runner, os.path.abspath(audio_path)],
            capture_output=True, text=True, timeout=600,
            creationflags=CREATE_NO_WINDOW)
        out = (r.stdout or "").strip().splitlines()
        line = out[-1] if out else ""
        if not line.startswith("{"):
            return None
        data = json.loads(line)
        return data.get("beats") if data.get("ok") else None
    except Exception:
        return None


def _librosa_track(audio_path):
    """librosa 拍点跟踪 (多音高扩展包自带); BPM 折算到 60-200 常规区间。
       变速容忍: beat_track 默认 tightness 会把拍点冻结在单一速度网格上,
       起音贴合度差时逐级放宽重跟踪; 仍冻结则直接以起音作拍点
       (变速段检测依赖真实拍点时刻, 规则网格会抹掉变速信息)"""
    _ensure_vendor()
    try:
        import bisect
        import librosa
        y, sr = librosa.load(audio_path, mono=True, duration=240)
        try:
            onsets = [float(t) for t in
                      librosa.onset.onset_detect(y=y, sr=sr, units="time")]
        except Exception:
            onsets = []

        def _score(bts):
            """拍点→最近起音的中位距离 (秒); 贴合起音则小"""
            if not bts or len(onsets) < 2:
                return 1.0
            ds = []
            for b in bts:
                i = bisect.bisect_left(onsets, b)
                cand = [onsets[j] for j in (i - 1, i) if 0 <= j < len(onsets)]
                ds.append(min((abs(b - c) for c in cand), default=1.0))
            ds.sort()
            return ds[len(ds) // 2]

        # 起音间隔四分位离散度: 单一速度时 IOI 集中, 变速/散板时呈多峰;
        # beat_track 拍点只会吸附到包络峰上 (贴合度恒优), 无法据此判别冻结,
        # 必须用 IOI 离散度决定优先尝试的 tightness
        spread = 0.0
        if len(onsets) >= 6:
            ios = sorted(b - a for a, b in zip(onsets, onsets[1:])
                         if b - a > 0.05)
            if len(ios) >= 4:
                med = ios[len(ios) // 2]
                if med > 1e-3:
                    q25 = ios[max(0, int(0.25 * len(ios)))]
                    q75 = ios[min(len(ios) - 1, int(0.75 * len(ios)))]
                    spread = (q75 - q25) / med
        best = None
        for tg in ((20, 50, 100) if spread >= 0.15 else (100, 50, 20)):
            tempo, beats = librosa.beat.beat_track(y=y, sr=sr, units="time",
                                                   tightness=tg)
            bts = [float(b) for b in beats]
            sc = _score(bts)
            if best is None or sc < best[0]:
                best = (sc, tempo, bts)
            if sc <= 0.03:                        # 拍点已贴合起音, 无需再试
                break
        sc, tempo, bts = best
        if not bts:
            return None
        if sc > 0.12 and len(onsets) >= 4:        # 仍冻结在规则网格 → 起音即拍点
            bts = onsets
        bpm = float(tempo[0] if hasattr(tempo, "__len__") else tempo)
        if bpm <= 0 and len(bts) >= 2:
            bpm = 60.0 * (len(bts) - 1) / (bts[-1] - bts[0])
        if bpm <= 0:
            return None
        while bpm < 60:
            bpm *= 2
        while bpm > 200:
            bpm /= 2
        beats = [[t, ((i) % 4) + 1] for i, t in enumerate(bts)]
        return {"bpm": round(bpm, 1), "num": 4, "den": 4,
                "beats": beats, "engine": "librosa"}
    except Exception:
        return None


def _derive_from_beats(beats):
    """BeatNet 拍点 [[秒, 拍号]...] -> bpm + 拍号 (强拍间隔拍数众数, 分母按 4)"""
    if not beats:
        return None
    import statistics
    times = [float(r[0]) for r in beats]
    nums = [int(r[1]) for r in beats]
    if len(times) < 4:
        return None
    ivs = [b - a for a, b in zip(times, times[1:]) if b - a > 0.05]
    if not ivs:
        return None
    bpm = 60.0 / statistics.median(ivs)
    while bpm < 60:
        bpm *= 2
    while bpm > 200:
        bpm /= 2
    max_bar = max(nums) if max(nums) > 1 else 4
    return {"bpm": round(bpm, 1), "num": int(max_bar), "den": 4,
            "beats": [[float(a), int(b)] for a, b in beats],
            "engine": "beatnet"}


class BeatAnalysisWorker(QThread):
    """后台分析线程: 完成 emit done(结果 dict), 失败/无结论 emit failed(提示)"""
    done = Signal(dict)
    failed = Signal(str)

    def __init__(self, audio_path, prefer_beatnet=True, parent=None):
        super().__init__(parent)
        self.audio_path = audio_path
        self.prefer_beatnet = bool(prefer_beatnet)

    def run(self):
        res = analyze_audio(self.audio_path,
                            prefer_beatnet=self.prefer_beatnet)
        if res:
            self.done.emit(res)
        else:
            self.failed.emit('节拍分析失败 — 已保持转录原状 (可安装节拍分析扩展包后重试)')


def tempo_segments(beats, beats_per_bar=4, min_bars=2, split_pct=0.05):
    """(四期优化) 拍点 [[秒, 拍号]…] → 变速段检测。
       逐拍瞬时 BPM (60/差分) → 3 拍中位数滤波; 段内最小二乘拟合 BPM
       (线性回归 斜率=60/BPM), 局部偏离段值 ≥split_pct 且段长 ≥min_bars
       → 切分段。输出 [{'t0','t1','bpm','beats'}], t1 可为 None (=曲尾)"""
    if not beats or len(beats) < 4:
        return []
    pts = [(float(r[0]), i) for i, r in enumerate(beats)]
    inst = [60.0 / (b - a) for (a, _i), (b, _j) in zip(pts, pts[1:]) if b - a > 1e-4]
    # 3 点中位数滤波
    med = []
    for i in range(len(inst)):
        win = inst[max(0, i - 1):i + 2]
        med.append(sorted(win)[len(win) // 2])

    def ls_fit(ts, ks):
        """最小二乘 (x=拍序号, y=秒): bpm = 60/斜率 (秒每拍)"""
        if len(ts) < 2:
            return None
        n = len(ts)
        mk = sum(ks) / n
        mt = sum(ts) / n
        num = sum((k - mk) * (t - mt) for k, t in zip(ks, ts))
        den = sum((k - mk) ** 2 for k in ks)
        if den <= 1e-9:
            return None
        slope = num / den                # 秒每拍
        return 60.0 / slope if slope > 1e-6 else None

    segs = []
    start = 0                                    # 段内起始拍索引
    seg_bpm = med[0] if med else None
    i = 1
    while i < len(beats):
        fit = ls_fit([pts[j][0] for j in range(start, i)],
                     [pts[j][1] for j in range(start, i)])
        if fit:
            seg_bpm = fit
        # 下一拍偏离判定 (用瞬时值)
        nxt = med[i] if i < len(med) else None
        over = nxt is not None and seg_bpm and             abs(nxt - seg_bpm) / seg_bpm >= split_pct
        seg_long = (i - start) >= min_bars * beats_per_bar
        if over and seg_long:
            fit2 = ls_fit([pts[j][0] for j in range(start, i)],
                          [pts[j][1] for j in range(start, i)])
            bpm_seg = round(fit2 or seg_bpm, 1)
            segs.append({'t0': pts[start][0], 't1': pts[i][0],
                         'bpm': max(30.0, min(300.0, bpm_seg)),
                         'beats': i - start})
            start = i
            seg_bpm = med[i] if i < len(med) else None
        i += 1
    # 尾段
    fit2 = ls_fit([pts[j][0] for j in range(start, len(beats))],
                  [pts[j][1] for j in range(start, len(beats))])
    if fit2 or segs:
        bpm_seg = round(fit2, 1) if fit2 else None
        segs.append({'t0': pts[start][0], 't1': None,
                     'bpm': max(30.0, min(300.0, bpm_seg)) if bpm_seg else 120.0,
                     'beats': len(beats) - start})
    # 段 0 锚定时间零点: 首个检出拍之前的区域沿用段 0 速度
    # (否则 [0, 首拍) 的时间跨度会在重缩放时坍缩, 音符绝对秒漂移)
    if segs:
        segs[0]['t0'] = 0.0
    return segs


def meter_segments_from_beats(beats):
    """(四期优化) BeatNet 下拍序列 → 拍号段 [(sec_start, num)] (分母按 4;
       下拍间隔拍数众数区域合并; 下拍证据 = 拍号写入依据)"""
    segs = []
    t0 = None
    cnt = 0
    for r in beats:
        t = float(r[0]); b = int(r[1])
        if b == 1:
            if t0 is not None:
                segs.append((t0, cnt))
            t0 = t; cnt = 1
        elif t0 is not None:
            cnt += 1
    if t0 is not None:
        segs.append((t0, cnt))
    out = []
    for t0, n in segs:
        if not out or out[-1][1] != n:
            out.append((t0, n))
    return out


def analyze_audio(audio_path, prefer_beatnet=True):
    """分析入口: BeatNet 桥接优先 -> librosa 降级 -> None。
       返回 {"bpm", "num", "den", "beats", "segments", "engine"} 或 None
       (segments = 变速段检测产物, 供结论行与段落级写入)"""
    if prefer_beatnet:
        interp = find_beatnet_interp()
        if interp:
            beats = _beatnet_subprocess(interp, audio_path)
            if beats:
                res = _derive_from_beats(beats)
                if res:
                    res["engine"] = "beatnet"
                    res["segments"] = tempo_segments(beats)
                    return res
    res = _librosa_track(audio_path)
    if res:
        res["segments"] = tempo_segments(res.get("beats", []))
        return res
    if not prefer_beatnet:
        return None
    interp = find_beatnet_interp()                    # librosa 失败再试 BeatNet
    if interp:
        beats = _beatnet_subprocess(interp, audio_path)
        if beats:
            res = _derive_from_beats(beats)
            if res:
                res["engine"] = "beatnet"
                res["segments"] = tempo_segments(beats)
                return res
    return None
