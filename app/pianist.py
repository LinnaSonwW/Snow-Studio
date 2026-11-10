# -*- coding: utf-8 -*-
"""物理按键整形: 把音符事件整形为可被游戏识别的按键序列。
   八度折叠后一个物理键可对应多个音高: act[sc] 为该键的活跃音符集合。
   折叠冲突策略(固定, 不可切换): 重敲 —— 按键期间新音到达 => 释放再按,
   保证每个触发都能拨弦; 同一时刻到达的折叠音并入同一次按键
   (物理上无法同瞬按两下同一键)。
   状态机/键: WANT_DOWN -> DOWN -> (tap计时|WANT_UP) -> IDLE
              DOWN/WANT_UP 期间新音 -> REDOWN(先抬再按)
   保证: 按住>=min_hold, 同键两次动作间隔>=min_gap; 拥塞过甚则丢弃并计数。"""
class KeyPianist:
    IDLE, WANT_DOWN, DOWN, WANT_UP, REDOWN = range(5)
    def __init__(self, mapper, out, mode='hold',
                 min_hold=0.045, min_gap=0.055, tap=0.070):
        self.mapper, self.out = mapper, out
        self.mode, self.min_hold, self.min_gap, self.tap = mode, min_hold, min_gap, tap
        self.st = {}     # sc -> [phase, busy_until, tap_at, want_at]
        self.act = {}    # sc -> set(活跃音符)  折叠引用
        self.dropped = self.deferred = 0
    def note_on(self, note, now):
        sc = self.mapper.key_of(note) if self.mapper else None
        if sc is None: return                          # 未映射/超域/未启用键盘输出
        self.act.setdefault(sc, set()).add(note)
        s = self.st.get(sc)
        if s is None:
            self.st[sc] = [self.WANT_DOWN, 0, 0, now]
            return
        ph = s[0]
        if ph == self.IDLE:
            s[0] = self.WANT_DOWN; s[3] = now
        elif ph in (self.DOWN, self.WANT_UP, self.REDOWN):
            s[0] = self.REDOWN; s[3] = now             # 重敲
        # WANT_DOWN: 同刻到达的折叠音并入本次按键
    def note_off(self, note, now):
        sc = self.mapper.key_of(note) if self.mapper else None
        if sc is None: return
        a = self.act.get(sc)
        if a is not None: a.discard(note)
        s = self.st.get(sc)
        if not s or s[0] == self.IDLE: return
        if a: return                                   # 该键仍有其他活跃音符
        if s[0] == self.WANT_DOWN:                     # 还没按下就全部结束
            self.dropped += 1; s[0] = self.IDLE; return
        if s[0] == self.REDOWN:                        # 重敲未完成即结束: 转为抬键
            self.dropped += 1; s[0] = self.WANT_UP; return
        if self.mode == 'tap': return                  # tap: 抬键由 tap 计时驱动
        s[0] = self.WANT_UP                            # hold: 至少按满 min_hold
    def poll(self, now):
        ops = []
        for sc, s in self.st.items():
            ph = s[0]
            if ph == self.WANT_DOWN and now >= s[1]:
                ops.append((sc, True)); s[0] = self.DOWN
                s[1] = now + self.min_hold
                if self.mode == 'tap': s[2] = now + self.tap
                if now - s[3] > 0.004: self.deferred += 1
            elif ph == self.DOWN and self.mode == 'tap' and now >= s[2]:
                ops.append((sc, False)); s[0] = self.IDLE; s[1] = now + self.min_gap
            elif ph == self.WANT_UP and now >= s[1]:
                ops.append((sc, False)); s[0] = self.IDLE; s[1] = now + self.min_gap
            elif ph == self.REDOWN and now >= s[1]:
                ops.append((sc, False)); s[0] = self.WANT_DOWN
                s[1] = now + self.min_gap; s[3] = now
        self.out.send(ops)
    def idle(self): return all(s[0] == self.IDLE for s in self.st.values())
    def panic(self):
        ops = [(sc, False) for sc, s in self.st.items() if s[0] != self.IDLE]
        for s in self.st.values(): s[0] = self.IDLE
        self.act.clear()
        self.out.send(ops); self.out.panic()