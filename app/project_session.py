# -*- coding: utf-8 -*-
"""编曲工程记忆 (工程轮): 音源与播放设置随 MIDI 伴生文件记忆/恢复。
   伴生文件 <曲名>.snowproj.json 与 MIDI 同目录 (随文件走), 记录:
   每轨 SF2 音源/音色/增益/静音、播放 BPM、移调、调性标注、当前轨、播放位置。
   轨道身份按轨道名优先、序号兜底 (tid 每次载入重排, 不作身份)。
   QSettings project/last_midi 记住最后一个工程, 启动自动续开。
   恢复音源直接走 engine.load_track_font 并静默降级 (SF2 缺失/失效不弹窗)。"""
import json
import os

from PySide6.QtCore import QSettings

from i18n import t as tr

_SIDE = '.snowproj.json'
_ORG = 'MidiKeymap'
_APP = 'PianoRollPlayer'


def sidecar_path(midi_path):
    """MIDI 路径 → 伴生工程文件路径"""
    return (midi_path or '') + _SIDE


def save_last_midi(path):
    QSettings(_ORG, _APP).setValue('project/last_midi', path or '')


def load_last_midi():
    v = QSettings(_ORG, _APP).value('project/last_midi', '', type=str)
    return v or ''


def clear_last_midi():
    QSettings(_ORG, _APP).remove('project/last_midi')


def capture(mw):
    """当前工程状态 → dict (音源/静音/BPM/移调/调性/当前轨/播放位置)"""
    tracks = []
    fonts = getattr(mw.engine, 'track_fonts', {}) or {}
    for t in getattr(mw, 'tracks', []) or []:
        info = fonts.get(t.tid) or {}
        tracks.append({
            'name': t.name,
            'index': int(t.tid),
            'sf2': info.get('path') or None,
            'preset': int(info.get('preset', 0)),
            'gain': float(info.get('gain', 1.0)),
            'muted': bool(getattr(t, 'muted', False)),
        })
    active = getattr(mw, 'tracks', []) or []
    active_name = ''
    if 0 <= getattr(mw, 'active_tid', -1) < len(active):
        active_name = active[mw.active_tid].name
    return {
        'version': 1,
        'tracks': tracks,
        'bpm': float(mw.sp_bpm.value()),
        'file_bpm': float(getattr(mw, '_file_bpm', 120.0)),
        'trans': int(getattr(mw, 'trans', 0)),
        'key_label': getattr(mw, 'key_label', '1=C'),
        'active_track': active_name,
        'cur_sec': float(getattr(mw, 'cur_sec', 0.0)),
    }


def save(mw):
    """捕获当前状态并写入当前 MIDI 的伴生文件 (内容未变跳过写盘)"""
    path = getattr(mw, '_midi_path', '')
    if not path or getattr(mw, 'tmap', None) is None:
        return False
    data = capture(mw)
    j = json.dumps(data, ensure_ascii=False, sort_keys=True)
    if j == getattr(mw, '_proj_last_json', ''):
        return False                       # 内容未变: 不重复写盘
    try:
        with open(sidecar_path(path), 'w', encoding='utf-8') as f:
            f.write(j)
    except OSError:
        return False
    mw._proj_last_json = j
    save_last_midi(path)
    return True


def save_as(mw, new_path):
    """另存 MIDI 后: 工程记忆写到新位置的伴生文件"""
    if not new_path:
        return False
    data = capture(mw)
    try:
        with open(sidecar_path(new_path), 'w', encoding='utf-8') as f:
            f.write(json.dumps(data, ensure_ascii=False, sort_keys=True))
    except OSError:
        return False
    mw._proj_last_json = json.dumps(data, ensure_ascii=False, sort_keys=True)
    save_last_midi(new_path)
    return True


def load_data(midi_path):
    """读伴生工程文件 → dict (不存在/损坏 = None)"""
    p = sidecar_path(midi_path)
    if not p or not os.path.isfile(p):
        return None
    try:
        with open(p, encoding='utf-8') as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _match_tracks(live_tracks, saved_tracks):
    """轨道身份匹配: 轨道名优先、序号兜底 → {tid: 保存条目}"""
    by_name = {s.get('name'): s for s in saved_tracks}
    used = set()
    out = {}
    for t in live_tracks:
        ent = by_name.get(t.name)
        if ent is None and 0 <= t.tid < len(saved_tracks):
            cand = saved_tracks[t.tid]
            if id(cand) not in used:
                ent = cand
        if ent is not None:
            used.add(id(ent))
            out[t.tid] = ent
    return out


def restore(mw):
    """载入 MIDI 后应用伴生工程 (音源/静音/BPM/移调/调性/当前轨/播放位置)。
       在 _open_path 的 clear_track_fonts 与重建之后调用。→ 是否有工程被恢复"""
    path = getattr(mw, '_midi_path', '')
    data = load_data(path) if path else None
    if not data:
        return False
    saved = data.get('tracks') or []
    matched = _match_tracks(getattr(mw, 'tracks', []) or [], saved)
    for t in getattr(mw, 'tracks', []) or []:
        ent = matched.get(t.tid)
        if ent is None:
            continue
        sf2 = ent.get('sf2')
        if sf2 and os.path.isfile(sf2):
            try:                           # 静默恢复 (缺失/失效不弹窗)
                mw.engine.load_track_font(
                    t.tid, sf2, int(ent.get('preset', 0)),
                    is_drum=bool(getattr(t, 'is_drum', False)),
                    gain=float(ent.get('gain', 1.0)))
            except Exception:
                pass
        t.muted = bool(ent.get('muted', getattr(t, 'muted', False)))
    bpm = data.get('bpm')
    if bpm:
        mw.sp_bpm.setValue(int(round(float(bpm))))   # 触发 _bpm_changed 应用速率
    # 播放层移调已锁死 0: 旧工程记忆里的 trans 不再恢复
    kl = data.get('key_label')
    if kl and kl != getattr(mw, 'key_label', ''):
        mw._set_key_label(kl)
    act = data.get('active_track')
    if act:
        for t in getattr(mw, 'tracks', []) or []:
            if t.name == act:
                mw.active_tid = t.tid
                break
    cur = data.get('cur_sec')
    if cur and float(cur) > 0:
        mw.cur_sec = max(0.0, float(cur))
    mw._sync_track_ui()
    mw.statusBar().showMessage(
        tr('已恢复工程记忆 (音源/播放设置)'), 4000)
    return True


def autoload(mw):
    """启动自动续开: 读取 project/last_midi 并打开 (文件缺失清键)"""
    p = load_last_midi()
    if not p:
        return False
    if not os.path.isfile(p):
        clear_last_midi()
        return False
    mw._open_path(p)
    return True
