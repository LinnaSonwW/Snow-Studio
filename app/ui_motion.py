# -*- coding: utf-8 -*-
"""UI 动效单源 (悬浮乐谱 / 选项径向菜单 / 子面板控件共用):
   时长常量 · cubic-bezier 缓动 · 关键帧弹性包络 · 「减少动态效果」降级 · 单时钟。
   减少动态效果 = 读取 Windows「在 Windows 中显示动画」(SPI_GETCLIENTAREAANIMATION);
   开启时一切位移/缩放改为 150ms 纯淡入淡出 (调用方以 reduced() 分支)。"""
import math
import sys
from PySide6.QtCore import Qt, QTimer, QElapsedTimer

MICRO = 120          # 悬停 / 按下
PANEL = 240          # 面板展开 / 收起
ELASTIC = 450        # 弹性入场 (400–500)
STAGGER = 40         # 径向按钮错峰
TREE_SEG = 150       # 树状连线每段
ITEM_STAGGER = 30    # 子项错峰
MASK = 200           # 遮罩淡入 / 关闭总时长
CENTER_IN = 200      # 中心菱形缩放入场
FLIP = 240           # 文字上下翻转
SEG_SLIDE = 160      # 分段选择滑块
PLAY_ICON = 180      # 播放/暂停图标切换
BAR_HOVER = 150      # 悬停进度条 → 工具栏滑出延迟
BAR_HIDE = 400       # 离开 → 工具栏收回延迟
TIP_DELAY = 500      # 按钮提示气泡延迟
HOLD = 800           # 长按确认
HOLD_SHAKE = 600     # 长按震动起点
REDUCED = 150        # 减少动态效果: 统一淡入淡出

BLUE = '#2f7cf6'     # 主色 (进度条蓝)
GREEN = '#32c864'    # 成功绿 (= 音轨指示灯)
RED = '#e0453a'
INK = '#1a1a1a'      # 线框描边 / 文字
PAPER = '#ffffff'


def clamp(v, lo=0.0, hi=1.0):
    return lo if v < lo else (hi if v > hi else v)


def bezier(x1, y1, x2, y2):
    """CSS cubic-bezier(x1,y1,x2,y2) → f(p): 二分求参数 s 使 x(s)=p, 返回 y(s)"""
    def bx(s, a, b):
        return 3 * a * s * (1 - s) ** 2 + 3 * b * s * s * (1 - s) + s ** 3
    def f(p):
        p = clamp(p)
        lo, hi = 0.0, 1.0
        for _ in range(22):
            mid = (lo + hi) / 2
            if bx(mid, x1, x2) < p: lo = mid
            else: hi = mid
        return bx((lo + hi) / 2, y1, y2)
    return f


ease_out = bezier(0.2, 0.8, 0.2, 1.0)      # 进入
ease_in = bezier(0.4, 0.0, 1.0, 1.0)       # 退出
ease_hold = bezier(0.4, 0.0, 0.6, 1.0)     # 长按填充 (开头稍慢)




def ease_back(p, s=1.70158):
    """spring 近似: 轻微过冲后落定"""
    p = clamp(p) - 1.0
    return 1.0 + (s + 1.0) * p ** 3 + s * p * p


def keyframes(p, pts):
    """分段余弦插值: pts=[(t0,v0),(t1,v1)...] t 升序 0..1, 段端点导数为 0"""
    p = clamp(p)
    for (t0, v0), (t1, v1) in zip(pts, pts[1:]):
        if p <= t1:
            q = 0.0 if t1 <= t0 else (p - t0) / (t1 - t0)
            return v0 + (v1 - v0) * (1 - math.cos(q * math.pi)) / 2
    return pts[-1][1]


def radial_pop(p):
    """径向按钮弹性缩放 0.6 → 1.12 → 0.94 → 1.0"""
    return keyframes(p, [(0, 0.6), (0.45, 1.12), (0.72, 0.94), (1.0, 1.0)])


def shake(p, px=4.0, n=3):
    """左右抖动位移 (p 0..1, n 次往返, 振幅随时间衰减)"""
    p = clamp(p)
    return px * math.sin(p * n * 2 * math.pi) * (1 - p)


_reduced = None


def reduced(refresh=False):
    """系统「减少动态效果」: Windows 关闭了客户区动画 = True; 测试可直接写 _reduced"""
    global _reduced
    if _reduced is None or refresh:
        _reduced = False
        if sys.platform == 'win32':
            try:
                import ctypes
                v = ctypes.c_int(1)
                # SPI_GETCLIENTAREAANIMATION = 0x1042
                if ctypes.windll.user32.SystemParametersInfoW(0x1042, 0,
                                                              ctypes.byref(v), 0):
                    _reduced = not bool(v.value)
            except Exception:
                _reduced = False
    return _reduced


def dur(ms):
    """减少动态效果开启时统一 150ms"""
    return REDUCED if reduced() else ms


class Clock:
    """单时钟: 16ms PreciseTimer 逐帧回调 tick(now); busy() 返回 False 即停表。
       skew 供离屏测试跳过动画 (QElapsedTimer 不推进时直接快进)"""
    def __init__(self, owner, tick, busy):
        self._el = QElapsedTimer(); self._el.start()
        self.skew = 0.0
        self._tick, self._busy = tick, busy
        self.timer = QTimer(owner)
        self.timer.setTimerType(Qt.PreciseTimer)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self._on)

    def now(self):
        return self._el.elapsed() + self.skew

    def run(self):
        if not self.timer.isActive():
            self.timer.start()

    def settle(self, ms=10000.0):
        self.skew += ms
        self._on()

    def _on(self):
        now = self.now()
        self._tick(now)
        if not self._busy(now):
            self.timer.stop()
