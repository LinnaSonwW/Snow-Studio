# -*- coding: utf-8 -*-
"""共用常量与工具(被所有模块引用, 不依赖其他本地模块)"""
import sys
import unicodedata
IS_WIN = sys.platform == 'win32'
# ---------------- 记谱 ----------------
NOTE_NAMES = ['C','C#','D','D#','E','F','F#','G','G#','A','A#','B']
BLACK_SET = {1, 3, 6, 8, 10}
WHITE_PC  = [0, 2, 4, 5, 7, 9, 11]           # C D E F G A B
BLACK_PCS = (1, 3, 6, 8, 10)                 # C# D# F# G# A# (黑键播放, 每排后5键)
# 音符字母显示模式 (音符设置弹窗; view_roll.PianoRoll._note_label 消费)
NOTE_MODES = ('name', 'letter', 'solfa', 'jianpu', 'key', 'custom', 'none')
NOTE_SOLFA = ('do', '♯do', 're', '♯re', 'mi', 'fa',          # 固定唱名, 黑键带升号
              '♯fa', 'sol', '♯sol', 'la', '♯la', 'si')
NOTE_JIANPU = ('1', '♯1', '2', '♯2', '3', '4',               # 简谱(以C调), 黑键带升号
               '♯4', '5', '♯5', '6', '♯6', '7')
# ---------------- 多音轨: 轨道调色板 (避开播放高亮琥珀色 #ffb020) ----------------
TRACK_COLORS = ('#4f9cf9', '#4fd08a', '#c88bf0', '#5ad4c8',
                '#f08ab0', '#8ab4f0', '#d8d86a', '#e8946a')
# ---------------- 音域体系: C1 ~ B8 (MIDI 24 ~ 119) ----------------
OCT_RANGE = range(1, 9)                       # 八度 1..8 (扩展支持C8)
NOTE_MIN, NOTE_MAX = 24, 119                  # C1, B8
_NN_CACHE = {}
def note_name(n):
    """音名(带缓存, 绘制热路径)"""
    s = _NN_CACHE.get(n)
    if s is None:
        s = f"{NOTE_NAMES[n % 12]}{n // 12 - 1}"; _NN_CACHE[n] = s
    return s
# ---------------- 演奏谱字符模式 (score_strip.ScoreStrip._note_labels 消费) ----------------
STRIP_LABEL_MODES = ('key', 'jianpu', 'name')   # 键位字母(默认) / 简谱 / 音名
DOT_ABOVE, DOT_BELOW = '\u0307', '\u0323'       # 简谱高/低八度组合点 (低音下加·, 高音上加·)
_JP_CACHE = {}
def jianpu_label(n, base=4):
    """简谱标签(带缓存, 绘制热路径): NOTE_JIANPU 音级 + 八度点 (基准八度=中音区不加点)"""
    key = (n, base)
    s = _JP_CACHE.get(key)
    if s is None:
        d = n // 12 - 1 - base
        s = NOTE_JIANPU[n % 12] + (DOT_ABOVE * d if d > 0 else DOT_BELOW * -d)
        _JP_CACHE[key] = s
    return s
def jianpu_dots(n, base=4):
    """简谱八度点几何: -> (上加圆点数, 下加圆点数) (演奏谱独立圆点图元用;
    组合符方案字体整形偏移大/点小, 已弃用于演奏谱)"""
    d = n // 12 - 1 - base
    return (d, 0) if d > 0 else (0, -d)
def label_width(s):
    """显示宽度估算用的字符数 (跳过组合符零宽点)"""
    return sum(1 for ch in s if not unicodedata.combining(ch))
def fmt_sec(sec):
    sec = max(0.0, sec); m = int(sec // 60)
    return f"{m}:{sec - 60 * m:04.1f}"
# ---------------- 三排键位 ----------------
ROWS = (1, 2, 3)
ROW_NAMES = {1: '第一排', 2: '第二排', 3: '第三排'}
# 默认键位(图片同款全折叠): 每排 12 键 = 白键7 (CDEFGAB) + 黑键5 (C#D#F#G#A#)
# 三排 36 键互不重复: 白键 QWERTYU/ASDFGHJ/ZXCVBNM, 黑键 23567/IOPKL/01489
# 默认键位: 每排白键 7 + 黑键 5 (C#D#F#G#A#), 三排 36 键互不重复
DEFAULT_ROW_KEYS        = {1: 'QWERTYU', 2: 'ASDFGHJ', 3: 'ZXCVBNM'}
DEFAULT_ROW_KEYS_BLACK  = {1: '23567', 2: 'IOPKL', 3: '01489'}
# 默认音域分配(图片同款全折叠): C1~B3→第三排, C4→第二排, C5~B7→第一排
DEFAULT_OCT_ASSIGN = {1: 3, 2: 3, 3: 3, 4: 2, 5: 1, 6: 1, 7: 1, 8: 0}
NO_ASSIGN = 0                                  # "不映射"标记(1..3=排号)
# ---------------- PianoRoll 绘制常量 ----------------
KB_W, HEADER_H = 64.0, 28.0
MIN_PPB, MAX_PPB = 16.0, 480.0
VIEW_OCT_SPAN_COMPACT = 3
VIEW_OCT_SPAN_FULL = 5
FOLLOW_X_FRAC = 0.30         # 播放跟随: 播放头锚定横坐标 (画布宽比例, 卷帘/横幅共用)
# 对齐档位定义移至 editor.EditablePianoRoll._SNAP_CHOICES (C1: 收敛死代码)
if IS_WIN:                                     # 提高调度精度
    import atexit, ctypes
    try:
        ctypes.windll.winmm.timeBeginPeriod(1)
        atexit.register(ctypes.windll.winmm.timeEndPeriod, 1)
    except Exception:
        pass