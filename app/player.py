# -*- coding: utf-8 -*-
"""播放线程: 唯一的时间轴推进者
   事件调度(SF2发声 + 物理按键) / 变速锚点 / seek/暂停 / 结束判定"""
import bisect, queue, time
from PySide6.QtCore import QThread, Signal
class PlayerThread(QThread):
    playbackFinished = Signal()
    def __init__(self, events, notes, total, engine, pianist, start=0.0,
                 track_ch=None):
        super().__init__()
        self.events = events
        self.ev_times = [e[0] for e in events]
        self.notes, self.total = notes, total
        self.engine, self.pianist = engine, pianist
        self.track_ch = track_ch if track_ch is not None else {}   # tid->通道 (持引用, 换音源即时生效)
        self.cmd = queue.Queue()
        self.speed = 1.0
        self.cur_music = 0.0
        self.paused = False
        self.sounding = frozenset()
        self._sounding = set()
        self._start = min(max(start, 0.0), total)   # (新) FL 式: 从任意位置起播
    # ---- UI 线程安全接口 ----
    def pause(self):  self.cmd.put(('pause', None))
    def resume(self): self.cmd.put(('resume', None))
    def seek(self, sec):   self.cmd.put(('seek', sec))     # 定位(播放态则重触发长音)
    def vseek(self, sec):  self.cmd.put(('vseek', sec))    # 拖动中: 只移指针静音
    def stop(self):    self.cmd.put(('stop', None))
    def set_speed(self, v): self.speed = v                 # 原子写, 线程内重锚点
    def replace_data(self, events, notes, total):
        """(C2) 暂停保留现场: 换上重建后的事件/音符表 (调用方随后 seek 回暂停点)"""
        self.events = events
        self.ev_times = [e[0] for e in events]
        self.notes, self.total = notes, total
    # ---- 内部 ----
    def _ch_of(self, nt):
        """音符所属轨道的发声通道 (未设独立音源的轨 = 全局通道 0)"""
        return self.track_ch.get(nt.tid, 0)
    def _anchor(self, music):
        self._am = music; self._aw = time.perf_counter()
    def _all_silent(self):
        for nt in self._sounding: self.engine.noteoff(nt.note, self._ch_of(nt))
        self._sounding.clear(); self.sounding = frozenset()
        self.pianist.panic()
    def _apply_seek(self, sec, retrigger):
        self._all_silent()
        sec = min(max(sec, 0.0), self.total)
        self.ev_i = bisect.bisect_right(self.ev_times, sec)
        self._anchor(sec); self.cur_music = sec
        if retrigger:                      # 恢复此刻仍在延续中的长音
            now = time.perf_counter()
            for nt in self.notes:
                if nt.start_sec <= sec < nt.end_sec:
                    self.engine.noteon(nt.note, nt.vel, self._ch_of(nt))
                    self._sounding.add(nt)
                    self.pianist.note_on(nt.note, now)
            self.sounding = frozenset(self._sounding)
    def run(self):
        self._apply_seek(self._start, True)   # 从起播点开始, 此刻延续中的长音重新触发
        paused = False; speed = self.speed; ending = 0.0
        running = True
        while running:
            try:
                while True:
                    c, arg = self.cmd.get_nowait()
                    if c == 'stop': running = False
                    elif c == 'pause': paused = True; self.paused = True; self._all_silent()
                    elif c == 'resume': paused = False; self.paused = False
                    elif c == 'seek': self._apply_seek(arg, not paused)
                    elif c == 'vseek': self._apply_seek(arg, False)
            except queue.Empty:
                pass
            if not running: break
            now = time.perf_counter()
            s = self.speed
            if s != speed:                 # 实时变速, 音乐时间连续不跳
                music = self._am + (now - self._aw) * speed
                self._anchor(music); speed = s
            if paused:
                time.sleep(0.03); continue
            music = self._am + (now - self._aw) * speed
            self.cur_music = music
            ev, n = self.events, len(self.events)
            while self.ev_i < n and ev[self.ev_i][0] <= music:
                _, is_on, nt = ev[self.ev_i]; self.ev_i += 1
                ch = self._ch_of(nt)
                if is_on:
                    self.engine.noteon(nt.note, nt.vel, ch)
                    self._sounding.add(nt)
                    self.pianist.note_on(nt.note, now)
                else:
                    self._sounding.discard(nt)
                    # 同音高且同通道都无延续者才发 off (不同轨同音高互不干扰)
                    if not any(x.note == nt.note and self._ch_of(x) == ch
                               for x in self._sounding):
                        self.engine.noteoff(nt.note, ch)
                    self.pianist.note_off(nt.note, now)
            self.sounding = frozenset(self._sounding)
            self.pianist.poll(now)         # 物理整形在此统一发送
            if (music >= self.total and self.ev_i >= n
                    and not self._sounding and self.pianist.idle()):
                if ending == 0: ending = now
                elif now - ending > 0.25: break
            else:
                ending = 0
            time.sleep(0.002)
        self._all_silent()
        self.playbackFinished.emit()