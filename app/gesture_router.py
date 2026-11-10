# -*- coding: utf-8 -*-
"""手势路由器 (Y 轮): 一次鼠标手势唯一 owner 的状态机。
   TempoLane(遮罩子控件) 与 EditablePianoRoll 共享同一画面区域,
   press 时经 begin() 仲裁 owner, move/release 用 check() 校验, release 用 end() 清理。
   规则: 异 owner 手势进行中时 begin 失败 (调用方吞掉事件);
         owner 只能由持有者 end; end 校验 who 防止误清; 无状态残留。"""


class GestureRouter:
    OWNER_MIDI = 'midi'
    OWNER_TEMPO = 'tempo'

    def __init__(self):
        self._owner = None

    @property
    def owner(self):
        return self._owner

    @property
    def busy(self):
        return self._owner is not None

    def begin(self, who):
        """press 时刻仲裁: 空闲或已是同 owner 才成功; 异 owner 手势进行中拒绝。"""
        if self._owner is not None and self._owner != who:
            return False
        self._owner = who
        return True

    def check(self, who):
        """move 期间校验: owner 未被清理/切换才继续本手势。"""
        return self._owner == who

    def end(self, who):
        """release 清理: 仅当 who 持有时清空 (误调/异 owner 调用无副作用)。"""
        if self._owner == who:
            self._owner = None
