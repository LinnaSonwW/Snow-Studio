# -*- coding: utf-8 -*-
"""对齐服务 (P1-B 自 editor.py 抽出): 对齐档位定义 + tick 吸附纯函数, 零 Qt 依赖。
   职责: 档位→tick 换算 / 画笔落点取格(floor) / 拖动就近吸附(round)。
   不负责: Alt 修饰键读取 (UI 层, EditablePianoRoll._snap_ticks 处理) /
          档位切换入口 (roll.set_snap) / 绘制 / 撤销。
   (最小移动轮) 无对齐不再落到 1 tick 级 —— 调用方以 min_step_ticks(tpb)
   兜底, 使最小移动量子为 1/96 拍。"""

SNAP_CHOICES = (                               # (D6) 对齐档位 (拍; None=tick 级)
    ('Line (自适应)', 'line'), ('无', None), ('1/6 拍', 1.0 / 6), ('1/4 拍', 0.25),
    ('1/3 拍', 1.0 / 3), ('1/2 拍', 0.5), ('1 拍', 1.0), ('1 小节', 'bar'))

# (最小移动轮) 无对齐时的最小移动量子 (拍): 1 tick (1/480 拍) 过细不好调,
# 统一钳到 1/96 拍 (FL 同款最细步长; tpb=480 时 = 5 tick)
MIN_STEP_BEATS = 1.0 / 96


def min_step_ticks(tpb):
    """无对齐时的最小移动量子 (tick); tpb 未知回退 1"""
    if not tpb:
        return 1
    return max(1, int(round(tpb * MIN_STEP_BEATS)))

# (Line 轮·FL 同款) 自适应阶梯 (拍): 缩小越甚 显示/吸附越粗, 反之越细;
# 保证最细可见网格间距 ≥ 8px (与画布网格合并阈值一致)




# (Line 轮·FL 同款) 自适应阶梯 (拍): 缩小越甚 显示/吸附越粗, 反之越细;
# 保证最细网格间距 ≥ 60px (按 FL 截图实测校准: beat≈300px 时取 1/3 拍=12 格)
LINE_LADDER_BEATS = (1.0 / 6, 0.25, 1.0 / 3, 0.5, 1.0, 2.0, 4.0, 8.0, 16.0)
LINE_MIN_PX = 60.0


def line_step_beats(ppb):
    """Line (自适应) 档: 当前横向缩放 (ppb = 每拍像素) 下最细可见网格 (拍数)。
       FL 官方: "the grid changes resolution as the Piano roll is Zoomed
       horizontally" —— 取阶梯中 间距 ≥60px 的最细档。"""
    if not ppb or ppb <= 0:
        return 1.0
    for beats in LINE_LADDER_BEATS:
        if beats * ppb >= LINE_MIN_PX:
            return beats
    return LINE_LADDER_BEATS[-1]

def snap_ticks(snap, tpb, bar_ticks, ppb=None):
    """档位 → tick 数; None(无对齐) 或 tpb 未知 → None; 'bar' → 小节拍数;
       'line' → 随缩放自适应的最细可见网格 (需 ppb, 缺省回退 1/2 拍)。"""
    if snap is None or tpb is None:
        return None
    if snap == 'bar':
        return max(1, int(round(bar_ticks)))
    if snap == 'line':
        if ppb is None or ppb <= 0:
            return max(1, int(round(tpb * 0.5)))
        return max(1, int(round(line_step_beats(ppb) * tpb)))
    return max(1, int(round(snap * tpb)))


def snap_floor(t, st):
    """画笔落点: 取所在格 (向下取整); st=None 时由调用方兜底最小量子
       (min_step_ticks), 本函数仅做裸取整; 负值钳 0。"""
    t = max(0.0, t)
    if st is None:
        return int(round(t))
    return int(t // st) * st


def snap_round(t, st):
    """拖动/改长落点: 就近吸附; st=None 时同上由调用方兜底。"""
    if st is None:
        return int(round(t))
    return int(round(t / st)) * st
