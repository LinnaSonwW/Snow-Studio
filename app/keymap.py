# -*- coding: utf-8 -*-
"""键位映射: 音高 -> 物理键(扫描码)
   两层结构: 八度 -> 排 -> 该排键位 (白键7: CDEFGAB + 黑键0~5: C#D#F#G#A#)
   row_keys = {排号: (白键串, 黑键串)}; 黑键串可留空 = 该排黑键无键盘映射(音源仍可发声)
   支持多个八度共用一排(八度折叠, 见”音域分配”), 也支持八度”不映射”。"""
from common import (OCT_RANGE, ROWS, ROW_NAMES, WHITE_PC, BLACK_PCS,
                    BLACK_SET, NOTE_MIN, NOTE_MAX, NO_ASSIGN)
from i18n import t
from keyout import scancode_of
class KeyMapper:
    def __init__(self, row_keys, oct_assign):
        """row_keys: {排号: (白键7字符串, 黑键0~5字符串)}; oct_assign: {八度: 排号 或 NO_ASSIGN}"""
        self.err = None
        self.row_keys = {}; self.oct_assign = {}
        self.note_sc = {}; self.note_char = {}    # 音高->扫描码 / 音高->按键字符(显示用)
        self.note_low, self.note_high = NOTE_MIN, NOTE_MAX
        # 1) 三排键串: 白键固定 7 个; 黑键 0~5 个(空 = 不映射); 全部键位排内/跨排不得重复
        seen_char = {}
        for r in ROWS:
            pair = row_keys.get(r, ("", ""))
            wk = str(pair[0]).strip().upper()
            bk = str(pair[1]).strip().upper()
            if len(wk) != 7:
                self.err = t('{row} 白键需要 7 个按键(依次对应 C D E F G A B), 当前 {n} 个',
                             row=t(ROW_NAMES[r]), n=len(wk)); return
            if len(set(wk)) != 7:
                self.err = t('{row} 白键有重复', row=t(ROW_NAMES[r])); return
            if len(bk) > 5:
                self.err = t('{row} 黑键最多 5 个(对应 C# D# F# G# A#), 当前 {n} 个',
                             row=t(ROW_NAMES[r]), n=len(bk)); return
            if len(set(bk)) != len(bk):
                self.err = t('{row} 黑键有重复', row=t(ROW_NAMES[r])); return
            if set(wk) & set(bk):
                self.err = t('{row} 黑键与白键键位重复', row=t(ROW_NAMES[r])); return
            self.row_keys[r] = (wk, bk)
        for r, (wk, bk) in self.row_keys.items():
            for ch in wk + bk:
                if ch in seen_char:
                    self.err = t('按键 {ch} 在 {a} 与 {b} 中重复',
                                 ch=ch, a=t(ROW_NAMES[seen_char[ch]]),
                                 b=t(ROW_NAMES[r])); return
                seen_char[ch] = r
        # 2) 八度分配: 0=不映射, 1..3=排号
        for o in OCT_RANGE:
            v = oct_assign.get(o, NO_ASSIGN)
            if v not in (NO_ASSIGN,) + ROWS:
                self.err = t('八度 C{o} 的分配值非法: {v}', o=o, v=repr(v)); return
            self.oct_assign[o] = v
        used = [o for o in OCT_RANGE if self.oct_assign[o] != NO_ASSIGN]
        if not used:
            self.err = t('没有任何八度被映射到键位（请在"音域分配…"中设置）'); return
        # 3) 覆盖范围(显示用): 最低已分配八度的 C ~ 最高已分配八度的 B
        self.note_low = (min(used) + 1) * 12
        self.note_high = (max(used) + 1) * 12 + 11
        # 4) 音高 -> 扫描码 (白键 + 已设置的黑键; 黑键未设置 = 不映射不输出)
        for o in OCT_RANGE:
            r = self.oct_assign[o]
            if r == NO_ASSIGN: continue
            wk, bk = self.row_keys[r]
            for i, pc in enumerate(WHITE_PC):          # 白键 C D E F G A B
                self.note_sc[(o + 1) * 12 + pc] = scancode_of(wk[i])
                self.note_char[(o + 1) * 12 + pc] = wk[i]
            for j, pc in enumerate(BLACK_PCS):         # 黑键 C# D# F# G# A#
                if j < len(bk):
                    self.note_sc[(o + 1) * 12 + pc] = scancode_of(bk[j])
                    self.note_char[(o + 1) * 12 + pc] = bk[j]
    # ---- 查询 ----
    def key_of(self, note):
        """音高 -> 扫描码; 未映射/超域 返回 None (黑键未设置 = 不映射)"""
        if self.err: return None
        if not (NOTE_MIN <= note <= NOTE_MAX): return None
        if self.oct_assign.get(note // 12 - 1, NO_ASSIGN) == NO_ASSIGN: return None
        return self.note_sc.get(note)
    def in_scope(self, note):
        """已分配八度内的音高 (含黑键; 不要求键位映射, 用于音源发声/卷帘可演奏色)。"""
        if self.err:
            return False
        if not (NOTE_MIN <= note <= NOTE_MAX):
            return False
        return self.oct_assign.get(note // 12 - 1, NO_ASSIGN) != NO_ASSIGN

    def covers(self, note):
        """音高有键盘映射 (键位输出用)。"""
        return self.key_of(note) is not None
    def classify(self, note):
        """playable / black(已映射黑键) / unassigned / out (统计用)"""
        if self.err: return "unassigned"
        if not (NOTE_MIN <= note <= NOTE_MAX): return "out"
        if self.oct_assign.get(note // 12 - 1, NO_ASSIGN) == NO_ASSIGN: return "unassigned"
        if note % 12 in BLACK_SET: return "black"
        return 'playable' if self.note_sc.get(note) else 'unassigned'