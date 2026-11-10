# -*- coding: utf-8 -*-
"""Capella 式原始音高事件 → 声组织 (Tonteppich / Rohtöne)。

对齐 audio2score 流程:
  多音高识别 → 带响度包络的音高轨迹 → 画成连续软边声组织

实现: librosa harmonic + piptrack → 同音高帧拼接, 保留逐帧响度包络。
"""
from __future__ import annotations
from dataclasses import dataclass, field

from PySide6.QtCore import QThread, Signal


@dataclass
class RawPitchEvent:
    """一条原始音高轨迹 (Rohton), 含时间-响度包络。"""
    pitch: int
    start_sec: float
    end_sec: float
    loudness: float = 1.0                          # 平均响度 0..1
    timbre: str = ''
    # 逐帧包络: (time_sec, loudness 0..1); 空则绘制时用纺锤形回退
    envelope: list[tuple[float, float]] = field(default_factory=list)


def analyze_multipitch(audio_path: str, *,
                       sr: int = 22050,
                       hop_length: int = 512,
                       fmin: float = 65.0,
                       fmax: float = 2093.0,
                       mag_floor: float = 0.05,
                       max_voices: int = 6,
                       gap_frames: int = 5,
                       snap_onsets: bool = True) -> list[RawPitchEvent]:
    """多音高识别 → (pitch, time, loudness envelope, timbre) 列表。
       (对齐轮) snap_onsets=True 时, 用"声组织起点分布 × onset 分布"互相关
       估计本曲的系统性滞后帧数 (阈值爬坡等造成, 只允许向前拉, 上限 6 帧),
       整层统一平移, 与 Transkun 等转录结果的时间基准对齐。"""
    import numpy as np
    import librosa

    y, sr = librosa.load(audio_path, sr=sr, mono=True)
    if y.size == 0:
        return []
    try:
        y_h = librosa.effects.harmonic(y, margin=2.0)
    except Exception:
        y_h = y

    hop_sec = float(hop_length) / sr
    onset_frames = []
    if snap_onsets:
        try:
            onset_frames = list(librosa.onset.onset_detect(
                y=y_h, sr=sr, hop_length=hop_length, units='frames',
                backtrack=True))
        except Exception:
            onset_frames = []

    pitches, mags = librosa.piptrack(
        y=y_h, sr=sr, hop_length=hop_length,
        fmin=fmin, fmax=fmax, threshold=0.1)
    try:
        y_p = librosa.effects.percussive(y, margin=2.0)
        rms_h = librosa.feature.rms(y=y_h, hop_length=hop_length)[0]
        rms_p = librosa.feature.rms(y=y_p, hop_length=hop_length)[0]
    except Exception:
        rms_h = librosa.feature.rms(y=y_h, hop_length=hop_length)[0]
        rms_p = np.zeros_like(rms_h)

    n_frames = pitches.shape[1]
    times = librosa.frames_to_time(np.arange(n_frames), sr=sr, hop_length=hop_length)
    mag_max = float(np.max(mags)) if mags.size else 1.0
    if mag_max <= 1e-12:
        return []

    frame_peaks: list[list[tuple[int, float]]] = []
    for f in range(n_frames):
        col_p = pitches[:, f]
        col_m = mags[:, f]
        idxs = np.where((col_p > 0) & (col_m / mag_max >= mag_floor))[0]
        if idxs.size == 0:
            frame_peaks.append([])
            continue
        order = idxs[np.argsort(col_m[idxs])[::-1][:max_voices]]
        peaks = []
        seen = set()
        for i in order:
            midi = int(round(librosa.hz_to_midi(float(col_p[i]))))
            midi = max(21, min(108, midi))
            if midi in seen:
                continue
            seen.add(midi)
            peaks.append((midi, float(col_m[i] / mag_max)))
        frame_peaks.append(peaks)

    open_tracks: dict[int, dict] = {}
    events: list[RawPitchEvent] = []

    def _flush(midi: int):
        tr = open_tracks.pop(midi, None)
        if tr is None:
            return
        louds = tr['loud']
        frames = tr['frames']
        mean_l = float(np.mean(louds)) if louds else 0.0
        if mean_l < mag_floor * 0.5:
            return
        i0, i1 = int(frames[0]), int(frames[-1])
        rh = float(np.mean(rms_h[i0:i1 + 1])) if i1 >= i0 else 0.0
        rp = float(np.mean(rms_p[i0:i1 + 1])) if i1 >= i0 else 0.0
        timbre = 'harmonic' if rh >= rp * 1.15 else ('noise' if rp > rh * 1.25 else '')
        env = [(float(times[fr]), max(0.02, min(1.0, float(L))))
               for fr, L in zip(frames, louds)]
        # 缺口帧用线性插值补点, 包络更连续
        if len(env) >= 2:
            env = _fill_envelope_gaps(env, hop_sec=hop_sec,
                                      gap_frames=gap_frames)
        events.append(RawPitchEvent(
            pitch=midi,
            start_sec=env[0][0],
            end_sec=env[-1][0] + hop_sec,
            loudness=max(0.05, min(1.0, mean_l)),
            timbre=timbre,
            envelope=env,
        ))

    for f, peaks in enumerate(frame_peaks):
        active = {m for m, _ in peaks}
        for midi, L in peaks:
            if midi in open_tracks:
                tr = open_tracks[midi]
                if f - tr['frames'][-1] <= gap_frames + 1:
                    tr['frames'].append(f)
                    tr['loud'].append(L)
                else:
                    _flush(midi)
                    open_tracks[midi] = {'frames': [f], 'loud': [L]}
            else:
                open_tracks[midi] = {'frames': [f], 'loud': [L]}
        for midi in list(open_tracks.keys()):
            if midi in active:
                continue
            if f - open_tracks[midi]['frames'][-1] > gap_frames:
                _flush(midi)

    for midi in list(open_tracks.keys()):
        _flush(midi)

    # (对齐轮) 全局滞后估计: 声组织起点分布 × onset 分布 互相关 →
    # 整层向前平移 s 帧 (只拉早不推晚), 消除阈值爬坡的系统性滞后
    if snap_onsets and events:
        s = _estimate_lag_frames(
            [int(round(e.start_sec / hop_sec)) for e in events],
            onset_frames)
        if s < 0:
            shift = s * hop_sec
            for e in events:
                e.start_sec = max(0.0, e.start_sec + shift)
                e.end_sec = max(0.0, e.end_sec + shift)
                e.envelope = [(max(0.0, t + shift), v) for t, v in e.envelope]

    min_dur = hop_length / sr * 1.5
    return [e for e in events if (e.end_sec - e.start_sec) >= min_dur]


def _estimate_lag_frames(start_frames: list[int], onset_frames: list[int],
                         max_lag: int = 6, min_agree: float = 0.5) -> int:
    """逐事件配对投票估计系统性滞后 (帧): 每个组织起点在 [自身, 自身+max_lag]
       帧内找最近 onset 投一票 (组织起点只可能偏晚); 票数过半的滞后才生效。
       返回负数 = 组织应向前移 |返回值| 帧 (与平移量同号)。"""
    votes: dict[int, int] = {}
    total = 0
    for t in start_frames:
        best = None
        for o in onset_frames:
            d = t - o
            if 0 <= d <= max_lag and (best is None or d < best):
                best = d
        if best is not None:
            votes[best] = votes.get(best, 0) + 1
            total += 1
    if not votes:
        return 0
    late, n = max(votes.items(), key=lambda kv: kv[1])
    return -late if n / total >= min_agree else 0


def _fill_envelope_gaps(env: list[tuple[float, float]], *,
                        hop_sec: float, gap_frames: int) -> list[tuple[float, float]]:
    """短缺口处插值响度, 避免包络断裂成方块感。"""
    if len(env) < 2:
        return env
    out = [env[0]]
    max_gap = hop_sec * (gap_frames + 3.5)
    for (t0, l0), (t1, l1) in zip(env, env[1:]):
        dt = t1 - t0
        if dt > hop_sec * 1.25 and dt <= max_gap:
            n = max(1, int(round(dt / hop_sec)) - 1)
            for k in range(1, n + 1):
                a = k / (n + 1)
                out.append((t0 + dt * a, l0 * (1 - a) + l1 * a))
        out.append((t1, l1))
    return out


class MultipitchTissueWorker(QThread):
    """后台多音高分析 → 批量 RawPitchEvent。"""
    progress = Signal(int, int)
    finished_events = Signal(object)
    failed = Signal(str)

    def __init__(self, audio_path: str):
        super().__init__()
        self.audio_path = audio_path

    def run(self):
        try:
            self.progress.emit(0, 2)
            if self.isInterruptionRequested():
                return
            self.progress.emit(1, 2)
            events = analyze_multipitch(self.audio_path)
            if self.isInterruptionRequested():
                return
            self.progress.emit(2, 2)
            self.finished_events.emit(events)
        except Exception as e:
            self.failed.emit(str(e))
