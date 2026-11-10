# -*- coding: utf-8 -*-
"""QSettings 持久化: 三排键串 / 八度分配 / 播放参数 / 窗口几何
   读取时逐项校验, 非法自动回退默认。
   出于安全考虑不持久化“启用键盘输出”复选框(避免启动即向系统注入按键)。"""
from PySide6.QtCore import QSettings
from common import (OCT_RANGE, ROWS, DEFAULT_ROW_KEYS, DEFAULT_ROW_KEYS_BLACK,
                    DEFAULT_OCT_ASSIGN, NO_ASSIGN, NOTE_MODES)
ORG, APP = "MidiKeymap", "PianoRollPlayer"
_INT_PARAMS = {          # key -> (默认, 下限, 上限)
    'transpose': (0, 0, 0),          # 播放层移调锁死 0
    'min_hold':  (45, 10, 200),
    'min_gap':   (55, 10, 200),
    'tap':       (70, 20, 300),
    'delay':     (3, 0, 10),
    'preset':    (0, 0, 127),
    'strip_font': (8, 4, 24),        # (UI轮) 演奏谱音符字母字号 (pt; 径向菜单 50%≈4pt)
    'src_gain': (100, 0, 800),       # 音源音量 (% 全局比例缩放力度, 可增幅到 800%)
    'sfx_volume': (100, 0, 100),     # 音效音量 (%) 预留接口
    'strip_name_font': (7, 5, 18),   # (UI轮) 演奏谱轨名字号 (独立于音符字母)
    'deck_font': (8, 6, 18),         # (UI轮) 主窗甲板轨道名字号 (pt)
    'strip_page_bars': (2, 1, 8),    # (跟随二轮) 演奏谱翻页每页小节数
    'score_row_h': (250, 100, 500),  # (设置轮) 悬浮谱每排高 (px)
    'score_float_w': (1020, 600, 3840),  # (设置轮) 悬浮谱窗口宽 (px)
    'strip_label': (0, 0, 2),        # (字符轮) 演奏谱字符模式 (STRIP_LABEL_MODES 索引)
    'strip_jianpu_base': (4, 1, 8),  # (字符轮) 简谱基准八度 (该八度不加点=中音区)
    'transcribe_manual_bpm': (120, 30, 300),  # (速度方案轮) 手动唯一 BPM
}
_STR_PARAMS = {          # key -> (默认, 合法值)
    'mode':    ('hold', ('hold', 'tap')),
    'overlap': ('merge', ('merge', 'truncate')),
    'map_scope': ('merge', ('merge', 'active')),   # 键盘映射范围: 合并所有音轨/仅当前音轨
    'key_label': ('1=C', ('1=C', '1=G', '1=D', '1=A', '1=E', '1=B',
                          '1=#F', '1=#C', '1=F', '1=bB', '1=bE', '1=bA',
                          '1=bD', '1=bG')),   # (标记轮) 调性标注 (显示用)
    'strip_layout': ('follow', ('follow', 'bars')),  # (排版轮) 演奏谱排版: follow=跟弹 bars=小节谱
    'score_skin': ('opaque', ('opaque', 'clear')),   # 悬浮谱皮肤: 不透明 / 透明
    'cursor_size': ('standard', ('standard', 'large')),   # 编辑器指针大小: 标准 / 大 (1.5×)
    'select_cursor': ('arrow', ('arrow', 'bracket')),     # 选择工具指针: 箭头+角标 / 四角括号+落点
    'transcribe_tempo_scheme': ('fixed_auto', ('adaptive', 'fixed_auto', 'fixed_manual')),
    # (速度方案轮) 转录速度方案: adaptive=跟随原曲速度变化 fixed_auto=自动检测唯一 BPM(推荐) fixed_manual=手动设置唯一 BPM
}
def _valid_row_pair(s_w, s_b):
    """返回 (白键7, 黑键0~5); 兼容历史存档: 旧 12 键自动拆白/黑, 旧 7 键黑键视为未映射"""
    sw = str(s_w).strip().upper()
    sb = str(s_b).strip().upper()
    if len(sw) == 12 and len(set(sw)) == 12:          # 旧 12 键档: 拆分
        return sw[:7], sw[7:]
    if len(sw) == 7 and len(set(sw)) == 7:
        if sb and (len(sb) > 5 or len(set(sb)) != len(sb)): sb = ''
        return sw, sb
    return None
def _valid_oct(v):
    try: v = int(v)
    except (TypeError, ValueError): return None
    return v if v in (NO_ASSIGN,) + ROWS else None
def load_settings():
    """-> (row_keys, oct_assign, params)"""
    st = QSettings(ORG, APP)
    rk = {}
    for r in ROWS:
        pair = _valid_row_pair(st.value(f"row_keys/{r}", DEFAULT_ROW_KEYS[r]),
                               st.value(f"row_keys_black/{r}",
                                        DEFAULT_ROW_KEYS_BLACK[r]))
        rk[r] = pair if pair else (DEFAULT_ROW_KEYS[r], DEFAULT_ROW_KEYS_BLACK[r])
    # 旧版默认黑键全空 → 启用完整 36 键布局 (音源+键盘)
    if all(not rk[r][1] for r in ROWS):
        rk = {r: (rk[r][0], DEFAULT_ROW_KEYS_BLACK[r]) for r in ROWS}
    used = ''.join(w + b for w, b in rk.values())
    if len(set(used)) != len(used):                   # 跨排重复: 整体回默认
        rk = {r: (DEFAULT_ROW_KEYS[r], DEFAULT_ROW_KEYS_BLACK[r]) for r in ROWS}
    oa = {}
    for o in OCT_RANGE:
        v = _valid_oct(st.value(f"oct_assign/{o}", DEFAULT_OCT_ASSIGN[o]))
        oa[o] = DEFAULT_OCT_ASSIGN[o] if v is None else v
    params = {}
    for k, (d, lo, hi) in _INT_PARAMS.items():
        try:
            v = int(float(st.value(f"params/{k}", d)))
            params[k] = v if lo <= v <= hi else d
        except (TypeError, ValueError):
            params[k] = d
    for k, (d, legal) in _STR_PARAMS.items():
        v = st.value(f"params/{k}", d)
        params[k] = v if v in legal else d
    try:
        params['speed'] = min(3.0, max(0.25, float(st.value('params/speed', 1.0))))
    except (TypeError, ValueError):
        params['speed'] = 1.0
    params['win_geom'] = st.value('ui/geometry')
    params['mini_geom'] = st.value('ui/mini_geom')
    params['roll_fold'] = _to_bool(st.value('ui/roll_fold', False), False)
    params['follow'] = _to_bool(st.value('params/follow', True), True)
    params['beat_auto'] = _to_bool(st.value('params/beat_auto', True), True)
    params['scale_bpm_link'] = _to_bool(st.value('params/scale_bpm_link', False), False)
    params['range_hl'] = _to_bool(st.value('params/range_hl', True), True)
    for k, d in (('range_lo', 3), ('range_hi', 5)):
        try: params[k] = min(8, max(1, int(float(st.value(f'params/{k}', d)))))
        except (TypeError, ValueError): params[k] = d
    return rk, oa, params
def save_settings(row_keys, oct_assign, params):
    st = QSettings(ORG, APP)
    for r in ROWS:
        pair = row_keys.get(r, (DEFAULT_ROW_KEYS[r], DEFAULT_ROW_KEYS_BLACK[r]))
        st.setValue(f"row_keys/{r}", pair[0])
        st.setValue(f"row_keys_black/{r}", pair[1])
    for o in OCT_RANGE:
        st.setValue(f"oct_assign/{o}", oct_assign.get(o, DEFAULT_OCT_ASSIGN[o]))
    for k, v in params.items():
        st.setValue(f"params/{k}", v)
def _to_bool(v, d):
    if isinstance(v, bool): return v
    if v in ('true', 'True', '1', 1): return True
    if v in ('false', 'False', '0', 0): return False
    return d
def save_geometry(geom):
    QSettings(ORG, APP).setValue('ui/geometry', geom)
def save_mini_geometry(geom):
    QSettings(ORG, APP).setValue('ui/mini_geom', geom)
def save_roll_fold(on):
    QSettings(ORG, APP).setValue('ui/roll_fold', bool(on))
def load_snap(default=None):
    """编辑器对齐档位 (30③): 'off'=None / 'bar'=1小节 / 'line'=自适应 /
       浮点字符串=拍数; 非法回退 default"""
    s = QSettings(ORG, APP).value('edit/snap', '')
    if s == 'off': return None
    if s in ('bar', 'line'): return s
    try: v = float(s)
    except (TypeError, ValueError): return default
    return v if v in (1 / 6, 0.25, 1 / 3, 0.5, 1.0) else default
def save_snap(snap):
    s = ('off' if snap is None else
         'bar' if snap == 'bar' else
         'line' if snap == 'line' else str(float(snap)))
    QSettings(ORG, APP).setValue('edit/snap', s)
def load_last_len():
    """上次绘制音符长度 ticks (30③); None=未记忆"""
    try:
        v = int(float(QSettings(ORG, APP).value('edit/last_len', 0)))
        return v if v > 0 else None
    except (TypeError, ValueError):
        return None
def save_last_len(ticks):
    QSettings(ORG, APP).setValue('edit/last_len', int(ticks))
# ---------- (O 轮) 语言 / 音符字母 / 输出设备 / 音源静音 ----------
def load_lang():
    v = QSettings(ORG, APP).value('ui/lang', 'zh')
    return v if v in ('zh', 'en') else 'zh'
def save_lang(lang):
    QSettings(ORG, APP).setValue('ui/lang', lang if lang in ('zh', 'en') else 'zh')
def load_note_label():
    """-> (显示模式, {音级pc: 显示字符}); 非法逐项回退"""
    st = QSettings(ORG, APP)
    mode = st.value('ui/note_mode', 'name')
    if mode not in NOTE_MODES: mode = 'name'
    custom = {}
    for pc in range(12):
        v = st.value(f'note_custom/{pc}')
        custom[pc] = str(v)[:2] if v is not None else ''
    return mode, custom
def save_note_label(mode, custom):
    st = QSettings(ORG, APP)
    if mode in NOTE_MODES: st.setValue('ui/note_mode', mode)
    for pc in range(12):
        st.setValue(f'note_custom/{pc}', str(custom.get(pc, '') or '')[:2])
def load_audio():
    """-> (驱动, 设备); '' = 自动/系统默认"""
    st = QSettings(ORG, APP)
    d = str(st.value('audio/driver', '') or '')
    if d not in ('', 'dsound', 'wasapi', 'waveout', 'portaudio'): d = ''
    e = str(st.value('audio/device', '') or '')
    return d, e
def save_audio(driver, device):
    st = QSettings(ORG, APP)
    st.setValue('audio/driver', driver if driver else '')
    st.setValue('audio/device', device if device else '')
def load_transcribe_cfg():
    """模型扒谱默认路线 (导入轮): route 一项; 权重/模型目录改为压缩包导入 models/"""
    st = QSettings(ORG, APP)
    route = str(st.value('transcribe/route', '') or '')
    if route not in ('transkun', 'muscriptor'): route = ''
    return route
def save_transcribe_cfg(route):
    st = QSettings(ORG, APP)
    st.setValue('transcribe/route', route if route in ('transkun', 'muscriptor') else '')
    st.remove('transcribe/weight')                # 清理旧版手填路径残留
    st.remove('transcribe/muscriptor_dir')
def load_mute():
    return _to_bool(QSettings(ORG, APP).value('ui/mute', False), False)
def save_mute(on):
    QSettings(ORG, APP).setValue('ui/mute', bool(on))
def load_lane_h():
    """变速 lanes 高度 (ui/lane_h, 40..400 钳制)"""
    try:
        v = float(QSettings(ORG, APP).value('ui/lane_h', 150))
    except (TypeError, ValueError):
        v = 150.0
    return max(40.0, min(400.0, v))
def save_lane_h(h):
    QSettings(ORG, APP).setValue('ui/lane_h', float(h))
def load_score_rows():
    """悬浮演奏谱显示排数 (score_float/rows, 1..4 钳制, 默认 2)"""
    try:
        v = int(QSettings(ORG, APP).value('score_float/rows', 2))
    except (TypeError, ValueError):
        v = 2
    return max(1, min(4, v))
def save_score_rows(n):
    QSettings(ORG, APP).setValue('score_float/rows', int(n))
