# -*- coding: utf-8 -*-
"""模型层 (X 轮新增): 音乐数据的写入唯一入口 —— 音符/Tempo 修改 + 不变量 + 统一撤销
   职责边界:
     管: 写入统一维护 push → 修改 → retime; Tempo 修改统一维护 tick↔秒 时间映射;
         编辑会话 (EditSession) 状态与 undo; raw_notes 对象身份稳定
         (普通写操作原地改 id 不变, 仅 undo 恢复快照时整体替换 —— _test_model.py 常驻断言)。
     不管: UI 刷新 (deck.refresh/_rebuild/卷帘重绘仍由 editor._commit 与 mainwindow 负责);
           读取路径; 播放/窗口调用。
   finish() 幂等: retime 为纯函数 (tick→sec 重算, 重复调用结果一致), 重复提交无额外
   登记、无累积副作用; editor._commit 内部也会 retime, 两次结果恒等、无行为差异。
   无 Qt 依赖 (QSettings 由 settings_store 封装), 可脱离 GUI 做纯逻辑测试。"""
from copy import deepcopy
import settings_store as store
from common import NOTE_MIN, NOTE_MAX
from midi_data import retime

UNDO_MAX = 100           # 撤销栈上限 (X 轮迁自 editor.py)
EDITOR_TITLE = "钢琴卷帘"   # (30②) 编辑窗标题基名 (脏标记 * 拼接用)


class EditSession:
    """快照式撤销 (X 轮迁自 editor.py, 逻辑原样)。快照 = (raw_notes深拷贝,
       选中nid集, 新建默认音长); tempo 条目 = ('tempo', 事件快照) 与音符同栈交替回退。
       dirty = 撤销栈深度 != 最近一次保存时的栈深度"""
    def __init__(self, mw, roll):
        self.mw = mw; self.roll = roll
        self.undo_stack = []
        self._base_len = 0
        self.dirty = False
        self.on_notify = None    # (P1-A) UI 通知回调: mainwindow 注册; None = 纯数据模式
        self.last_len_ticks = store.load_last_len()   # (30③) 上次绘制长度持久化
    def capture(self):
        return (deepcopy(self.mw.raw_notes), set(self.roll.selection), self.last_len_ticks)
    def push(self, snap=None):
        """任何改动前调用; 可传 press 时 capture() 的预捕获(实现'纯点击不进撤销栈')"""
        snap = snap or self.capture()
        self.undo_stack.append(snap)
        if len(self.undo_stack) > UNDO_MAX: self.undo_stack.pop(0)
        self._notify()
    def push_tempo(self, events_before):
        """(Q 轮) 变速 lanes 修改前调用: 压入 tempo 类撤销条目 (与音符撤销同一栈)"""
        self.undo_stack.append(('tempo', list(events_before)))
        if len(self.undo_stack) > UNDO_MAX: self.undo_stack.pop(0)
        self._notify()
    def abort_last(self):
        """状态已还原为 push 前时, 回退刚 push 的那步 (如 Esc 取消新建)"""
        if self.undo_stack: self.undo_stack.pop()
        self._notify()
    def mark_saved(self):
        self._base_len = len(self.undo_stack); self._notify()
    def undo(self):
        if not self.undo_stack: return False
        entry = self.undo_stack[-1]
        if isinstance(entry, tuple) and entry and entry[0] == 'tempo':
            self.undo_stack.pop()
            self.mw.tmap.restore_events(entry[1])
            self.mw._apply_tempo_change()
            self._notify(); return True
        if isinstance(entry, tuple) and entry and entry[0] == 'scale_tempo':
            # (缩放变速轮) 复合条目: 一步同时还原 音符缩放 + BPM
            self.undo_stack.pop()
            self._restore(entry[1])
            self.mw.tmap.restore_events(list(entry[2]))
            self.mw._apply_tempo_change()
            self._notify(); return True
        self._restore(self.undo_stack.pop()); return True
    def _restore(self, snap):
        """用快照覆盖主窗口数据(列表对象被替换, 调用方需随后 _editor_commit 同步卷帘)"""
        notes, sel, last_len = snap
        self.mw.raw_notes = notes
        self.roll.selection = set(sel)
        self.last_len_ticks = last_len
        self._notify()
    def _notify(self):
        """(P1-A) 只计算数据状态并触发 on_notify 回调; UI 展示由壳层 (mainwindow) 负责,
           model 由此实现零 UI 依赖 (回调异常不影响数据层)。"""
        self.dirty = len(self.undo_stack) != self._base_len
        if self.on_notify is not None:
            try:
                self.on_notify(self)
            except Exception:
                pass


class MusicModel:
    """主窗数据的模型门面: 所有音符/Tempo 写入经此类, 保证不变量
       (push 先行 / retime 同步 / 列表对象身份)。读取仍由调用方直读 mw.raw_notes
       (热路径零间接), 本类不缓存任何数据。"""
    def __init__(self, mw):
        self._mw = mw

    # ---- 会话 ----
    @property
    def session(self):
        return self._mw.edit_session
    def push(self, snap=None):
        """音符改动前压栈; 可传预捕获快照 (纯点击不入栈由调用方判定)"""
        self.session.push(snap)
    def push_tempo(self, events_before):
        self.session.push_tempo(events_before)

    # ---- 写入原语 (拖动过程用: 只改数据, 不 retime; 松手统一 finish()) ----
    def begin_add(self, note, snap=None):
        """push + 原地追加 (新建拖动在按下即入栈, Esc 走 session.abort_last 回退)"""
        self.push(snap)
        self.append_notes([note])
    def append_notes(self, notes):
        """批量原地追加 (不 push 不 retime —— 调用方已入栈时用, 如 Ctrl 克隆拖拽)"""
        self._mw.raw_notes.extend(notes)
    def set_note_span(self, note, start, end):
        """原地改起止 tick (创建/拉伸拖动中每帧调用, 不 retime)"""
        note.start_tick, note.end_tick = start, end
    def set_note_pos(self, note, start):
        """原地改起点 (移动/左缘拉伸拖动中每帧调用, 不 retime)"""
        note.start_tick = start
    def set_note_end(self, note, end):
        """原地改终点 (创建拖长/右缘拉伸拖动中每帧调用, 不 retime)"""
        note.end_tick = end
    def set_note_pitch(self, note, nn):
        """原地改音高 (移动拖动换行, 不 retime)"""
        note.note = nn
    def remove_notes(self, nids):
        """原地过滤删除 (保持 raw_notes 列表对象身份)"""
        self._mw.raw_notes[:] = [o for o in self._mw.raw_notes if o.nid not in nids]
    def finish(self):
        """写入提交点: 统一 retime (tick→sec 幂等重算)。拖动松手/命名操作后调用;
           重复调用无额外副作用 (纯函数, 且不入撤销栈)。"""
        if self._mw.tmap is not None:
            retime(self._mw.raw_notes, self._mw.tmap)

    # ---- 命名操作 (一次性动作: push → 修改 → finish, 一步撤销) ----
    def add_notes(self, notes, snap=None):
        """批量追加 (剪贴板粘贴/克隆落位): push + extend + retime"""
        self.push(snap)
        self._mw.raw_notes.extend(notes)
        self.finish()
    def delete_notes(self, nids):
        """批量删除: push + 原地过滤 + retime"""
        self.push()
        self.remove_notes(nids)
        self.finish()
    def apply_note_props(self, note, note_num, vel, start, end):
        """双击属性写入: push + 四项赋值 (时值最小 1 tick) + retime"""
        self.push()
        note.note, note.vel = note_num, vel
        note.start_tick, note.end_tick = start, max(start + 1, end)
        self.finish()
    def apply_note_props_multi(self, nids, ops):
        """(编辑轮) 批量属性写入: ops = {'note'/'vel'/'start'/'dur'/'arp': (mode, v)},
           mode 0=不变/1=设为/2=增减(arp 行=清除)。push 一次 → 单遍应用 → finish,
           整批一步撤销。应用顺序 起点→时值→音高→力度→琶音"""
        self.push()
        mode_s, mode_v = ops.get('start', (0, 0)), ops.get('dur', (0, 0))
        mn, mv = ops.get('note', (0, 0)), ops.get('vel', (0, 0))
        ma = ops.get('arp', (0, 0))
        if ma[0] == 1 and int(ma[1]) <= 0:
            # 设为琶音 (组号 0 = 自动): 取选区外未占用的最小组号, 分次设置互不合并
            used = {int(getattr(o, 'arp', 0) or 0) for o in self._mw.raw_notes
                    if o.nid not in nids}
            ma = (1, next((g for g in range(1, 100) if g not in used), 99))
        for nt in self._mw.raw_notes:
            if nt.nid not in nids:
                continue
            if mode_s[0] == 1:                    # 起点设为: 各自时值保持
                dur0 = nt.end_tick - nt.start_tick
                nt.start_tick, nt.end_tick = mode_s[1], mode_s[1] + dur0
            elif mode_s[0] == 2:                  # 起点增减: 整体平移 (钳 0 不改时值)
                ns = max(0, nt.start_tick + mode_s[1])
                shift = ns - nt.start_tick
                nt.start_tick += shift
                nt.end_tick += shift
            nt.start_tick = max(0, nt.start_tick)
            if mode_v[0] == 1:                    # 时值设为: 锚定各自起点
                nt.end_tick = nt.start_tick + max(1, mode_v[1])
            elif mode_v[0] == 2:
                nt.end_tick = max(nt.start_tick + 1, nt.end_tick + mode_v[1])
            if mn[0] == 1:
                nt.note = max(NOTE_MIN, min(NOTE_MAX, mn[1]))
            elif mn[0] == 2:
                nt.note = max(NOTE_MIN, min(NOTE_MAX, nt.note + mn[1]))
            if mv[0] == 1:
                nt.vel = max(1, min(127, mv[1]))
            elif mv[0] == 2:
                nt.vel = max(1, min(127, nt.vel + mv[1]))
            if ma[0] == 1:                        # (琶音轮) 设为组号 / 清除
                nt.arp = max(0, int(ma[1]))
            elif ma[0] == 2:
                nt.arp = 0
        self.finish()
    def transpose_notes(self, nids, semi, snap=None):
        """选区整体移调 (O9 路径预留): 钳 C1~B8 音域后原地改音高 + retime"""
        self.push(snap)
        for nt in self._mw.raw_notes:
            if nt.nid in nids:
                nt.note = max(NOTE_MIN, min(NOTE_MAX, nt.note + semi))
        self.finish()

    # ---- Tempo (时间映射统一维护: push_tempo → 改表 → retime) ----
    def tempo_set(self, idx, bpm):
        self.push_tempo(self._mw.tmap.events())
        self._mw.tmap.set_bpm_index(idx, bpm)
        self.finish()
    def tempo_insert(self, tick, bpm):
        self.push_tempo(self._mw.tmap.events())
        self._mw.tmap.insert_event(tick, bpm)
        self.finish()
    def tempo_delete(self, tick):
        self.push_tempo(self._mw.tmap.events())
        self._mw.tmap.remove_event(tick)
        self.finish()

    # ---- 撤销 ----
    def undo(self):
        ok = self.session.undo()          # tempo 分支内部已 retime (_apply_tempo_change)
        if ok:
            self.finish()                 # 音符分支恢复快照后补 retime (幂等, 防调用方遗漏)
        return ok
