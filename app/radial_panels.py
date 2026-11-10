# -*- coding: utf-8 -*-
"""选项径向菜单子面板 (乐谱/播放/声音/歌曲): 每项 = PanelItem (标签 + 线框控件)。
   所有设置一律「先改草稿 → 共用长按【确认】一次提交」: 控件改动只写草稿,
   有任一项与当前值不同 →【确认】可用; 长按 800ms 依序提交全部改动项, 存档一次,
   需要时只重建一次; 某项失败 = 保留其草稿, 可再次确认。
   提交走主窗既有字段与应用路径 (_save_cfg / _rebuild / _set_strip_layout /
   _toggle_mute / _apply_audio_device …), 不另建设置通路。"""
import copy
from common import OCT_RANGE, ROWS, NO_ASSIGN, STRIP_LABEL_MODES
import settings_store as store
from radial_controls import (PanelItem, LButton, Cycle, Dropdown, Segmented, LSlider,
                             KeyCells, ConfirmNode)

ROW_NAMES = {NO_ASSIGN: '不映射', 1: '第一排', 2: '第二排', 3: '第三排'}


class Field:
    """一个设置项的草稿: current() 读主窗当前值; apply(v) 写主窗 → (成功, 需重建);
       sync(v) 提交后把控件拨回实际保存值 (消除取整误差)"""
    def __init__(self, item, current, apply, sync=None):
        self.item, self.current, self.apply, self.sync = item, current, apply, sync
        self.draft = copy.deepcopy(current())

    def dirty(self):
        return self.draft != self.current()


class Panel:
    """子面板基类: items 自上而下 (连线按顺序分配), 末尾 = 共用【确认】节点"""
    def __init__(self, ov):
        self.ov, self.mw, self.k = ov, ov.mw, ov.k
        self.items, self.fields, self._ids = [], [], {}
        self.confirm = None
        self.build()
        if self.fields:
            self.confirm = ConfirmNode(ov, self.k, self.commit, self.any_dirty)
            self.items.append(self.confirm)
        for it in self.items:
            for w in it.widgets():
                w.show(); w.raise_()

    def build(self):
        pass

    def item(self, iid, label):
        it = PanelItem(self.ov, self.k, label)
        self.items.append(it); self._ids[iid] = it
        return it

    def field(self, item, current, apply, sync=None):
        f = Field(item, current, apply, sync)
        self.fields.append(f)
        return f

    def set_draft(self, f, v):
        """控件改动 → 只写草稿, 刷新蓝点与【确认】可用态"""
        f.draft = v
        self.refresh()

    def refresh(self):
        for f in self.fields:
            f.item.set_mark(f.dirty())
        if self.confirm is not None:
            self.confirm.btn.set_dirty(self.any_dirty())

    def any_dirty(self):
        return any(f.dirty() for f in self.fields)

    def find(self, iid):
        return self._ids.get(iid)

    def commit(self):
        """长按确认: 依序提交全部改动项 → 存档一次 → 需要时重建一次。
           返回 False = 有项失败 (其草稿保留, 可再次确认)"""
        mw = self.mw
        ok_all, rebuild = True, False
        for f in [f for f in self.fields if f.dirty()]:
            try:
                ok, rb = f.apply(copy.deepcopy(f.draft))
            except Exception:
                ok, rb = False, False
            ok_all &= bool(ok)
            rebuild |= bool(ok and rb)
        mw._save_cfg()
        if rebuild:
            mw._rebuild(keep_view=True)
        self.refresh_strips()
        for f in self.fields:                        # 控件回读实际保存值
            if not f.dirty():
                f.draft = copy.deepcopy(f.current())
                if f.sync is not None:
                    f.sync(f.draft)
        for f in self.fields:
            f.item.set_mark(f.dirty())
        return ok_all

    def cancel_holds(self):
        """取消进行中的长按 → True = 确有取消 (Esc 先消费在这里)"""
        b = self.confirm.btn if self.confirm is not None else None
        if b is not None and b.holding():
            b.cancel()
            return True
        return False

    def destroy(self):
        for it in self.items:
            for w in it.widgets():
                w.hide(); w.deleteLater()
        self.items, self.fields = [], []

    def refresh_strips(self):
        mw = self.mw
        for st in (getattr(mw, 'score_strip', None),
                   getattr(getattr(mw, 'score_float', None), 'strip', None)):
            if st is not None:
                st.update()
        sf = getattr(mw, 'score_float', None)
        if sf is not None:
            sf.apply_display()


def build_panel(kind, ov):
    return {'score': ScorePanel, 'play': PlayPanel,
            'audio': AudioPanel, 'song': SongPanel}[kind](ov)


SIZE_MODES = (('w', '谱面长度', 600, 3840, 1020, 10),     # (键, 标签, 下限, 上限, 默认, 步进) px
              ('h', '谱面高度', 100, 500, 250, 5))


class ScorePanel(Panel):
    """乐谱 (西北): 音符大小 / 音轨名称 / 乐谱格式 / 乐谱类型 / 乐谱排数 / 皮肤 / 谱面长度⇄高度"""
    BASE_PT = 8.0                                # 音符大小 100% = 8pt; 每 1pt = 12.5%

    def build(self):
        mw, k = self.mw, self.k
        sf = getattr(mw, 'score_float', None)
        it = self.item('note', '音符大小')
        s = it.add(LSlider(None, k, 50, 200, mw.strip_font / self.BASE_PT * 100, 100,
                           '{:g}%', 12.5, box_w=52))
        f = self.field(it, lambda: int(self.mw.strip_font), self._apply_font,
                       lambda v, s=s: s.set_value(v / self.BASE_PT * 100))
        s.valueChanged.connect(lambda v, f=f: self.set_draft(
            f, int(round(self.BASE_PT * v / 100.0))))
        it = self.item('name', '音轨名称')
        s = it.add(LSlider(None, k, 5, 18, mw.strip_name_font, 7, '{:.0f}pt', 1))
        f = self.field(it, lambda: int(self.mw.strip_name_font), self._apply_name,
                       lambda v, s=s: s.set_value(v))
        s.valueChanged.connect(lambda v, f=f: self.set_draft(f, int(v)))
        it = self.item('layout', '乐谱格式')
        seg = it.add(Segmented(None, k, [('bars', '节奏谱'), ('follow', '轨道谱')],
                               mw.strip_layout))
        f = self.field(it, lambda: self.mw.strip_layout,
                       lambda v: (self.mw._set_strip_layout(v), (True, False))[1],
                       lambda v, s=seg: s.set_value(v))
        seg.changed.connect(lambda v, f=f: self.set_draft(f, v))
        it = self.item('label', '乐谱类型')
        opts = [('jianpu', '简谱'), ('key', '键盘谱')]
        if self._label_mode() == 'name':
            opts.append(('name', '音名'))
        c = it.add(Cycle(None, k, opts, self._label_mode()))
        f = self.field(it, self._label_mode, self._apply_label,
                       lambda v, c=c: c.set_value(v))
        c.changed.connect(lambda v, f=f: self.set_draft(f, v))
        it = self.item('rows', '乐谱排数')
        seg = it.add(Segmented(None, k, [(n, str(n)) for n in (1, 2, 3, 4)], self._rows_now()))
        f = self.field(it, self._rows_now, self._apply_rows, lambda v, s=seg: s.set_value(v))
        seg.changed.connect(lambda v, f=f: self.set_draft(f, v))
        it = self.item('skin', '皮肤切换')
        c = it.add(Cycle(None, k, [('clear', '透明'), ('opaque', '不透明')],
                         getattr(mw, 'score_skin', 'opaque')))
        f = self.field(it, lambda: getattr(self.mw, 'score_skin', 'opaque'),
                       self._apply_skin, lambda v, c=c: c.set_value(v))
        c.changed.connect(lambda v, f=f: self.set_draft(f, v))
        self._build_size()

    # ---- 谱面长度 ⇄ 谱面高度 (点击标签切换; 单位 px; 两值各自草稿) ----
    def _build_size(self):
        k = self.k
        it = self.item('size', SIZE_MODES[0][1])
        self.size_mode = 0
        self.s_size = it.add(LSlider(None, k, 0, 1, 0, 0, '{:.0f}px', 1, box_w=56))
        self.f_size = self.field(it, self._size_now, self._apply_size,
                                 lambda v: self._show_size())
        self.s_size.valueChanged.connect(self._size_changed)
        it.set_label_toggle([m[1] for m in SIZE_MODES], self._size_toggle)
        self._show_size()

    def _size_now(self):
        return {'w': int(self.mw.score_float_w), 'h': int(self.mw.score_row_h)}

    def _show_size(self):
        key, _, lo, hi, d, step = SIZE_MODES[self.size_mode]
        self.s_size.configure(lo, hi, self.f_size.draft[key], d, '{:.0f}px', step)

    def _size_toggle(self, i):
        self.size_mode = i
        self._show_size()

    def _size_changed(self, v):
        d = dict(self.f_size.draft)
        d[SIZE_MODES[self.size_mode][0]] = int(v)
        self.set_draft(self.f_size, d)

    def _apply_size(self, v):
        self.mw.score_float_w, self.mw.score_row_h = int(v['w']), int(v['h'])
        return True, False

    # ---- 其余提交 ----
    def _apply_font(self, pt):
        self.mw.strip_font = max(4, min(24, int(pt)))
        return True, True

    def _apply_name(self, pt):
        self.mw.strip_name_font = int(pt)
        return True, False

    def _label_mode(self):
        i = self.mw.strip_label
        return STRIP_LABEL_MODES[i] if 0 <= i < len(STRIP_LABEL_MODES) else 'key'

    def _apply_label(self, mode):
        self.mw.strip_label = STRIP_LABEL_MODES.index(mode)
        return True, True

    def _rows_now(self):
        sf = getattr(self.mw, 'score_float', None)
        return sf._rows if sf is not None else store.load_score_rows()

    def _apply_rows(self, n):
        sf = getattr(self.mw, 'score_float', None)
        if sf is not None:
            sf.set_rows(n)
        else:
            store.save_score_rows(n)
        return True, False

    def _apply_skin(self, v):
        self.mw.score_skin = v
        return True, False


class PlayPanel(Panel):
    """播放 (东北): 音域分配 / 按键分配 / 映射范围 / 映射输出 / 映射模式 / 播放延迟 / 重叠处理"""
    def build(self):
        mw, k = self.mw, self.k
        # 音域分配: 左格切换音域 (浏览, 不算修改), 右格切换该音域的映射排 (草稿)
        it = self.item('range', '音域分配')
        self.oct = 4 if 4 in OCT_RANGE else list(OCT_RANGE)[0]
        self.c_oct = it.add(Cycle(None, k, [(o, 'C%d–B%d' % (o, o)) for o in OCT_RANGE],
                                  self.oct))
        self.c_oct_row = it.add(Cycle(None, k, [(r, ROW_NAMES[r]) for r in (NO_ASSIGN,) + ROWS],
                                      mw.oct_assign.get(self.oct, NO_ASSIGN)), 74)
        self.f_oct = self.field(it, lambda: dict(self.mw.oct_assign), self._apply_oct,
                                lambda v: self._pick_oct(self.oct))
        self.c_oct.changed.connect(self._pick_oct)
        self.c_oct_row.changed.connect(self._assign_oct)
        # 按键分配: 右格切换排 (浏览), 键格监听绑定 (草稿)
        it = self.item('keys', '按键分配')
        self.krow = ROWS[-1]
        self.f_keys = self.field(it, lambda: dict(self.mw.row_keys), self._apply_keys,
                                 lambda v: self._pick_krow(self.krow))
        self.cells = it.add(KeyCells(None, k, list(self.f_keys.draft[self.krow][0]),
                                     self._bind))
        self.c_krow = it.attach(Cycle(self.ov, k, [(r, ROW_NAMES[r]) for r in ROWS],
                                      self.krow), 70)     # 外挂在项右侧: 键格不被挤窄
        self.c_krow.changed.connect(self._pick_krow)
        # 映射范围: 打开音轨径向选择器, 勾选只改草稿
        it = self.item('scope', '映射范围')
        self.b_scope = it.add(LButton(None, k, ''))
        self.f_scope = self.field(it, self._scope_now, self._apply_scope,
                                  lambda v: self._scope_label())
        self.b_scope.clicked.connect(self._open_tracks)
        self._scope_label()
        it = self.item('out', '映射输出')
        c = it.add(Cycle(None, k, [(True, '启用'), (False, '停用')], mw.chk_out.isChecked()))
        f = self.field(it, lambda: bool(self.mw.chk_out.isChecked()), self._apply_out,
                       lambda v, c=c: c.set_value(v))
        c.changed.connect(lambda v, f=f: self.set_draft(f, v))
        it = self.item('mode', '映射模式')
        c = it.add(Cycle(None, k, [('hold', '长按模式'), ('tap', '点按模式')], mw.piano_mode))
        f = self.field(it, lambda: self.mw.piano_mode, self._apply_mode,
                       lambda v, c=c: c.set_value(v))
        c.changed.connect(lambda v, f=f: self.set_draft(f, v))
        it = self.item('delay', '播放延迟')
        c = it.add(Cycle(None, k, [(s, '%d 秒' % s) for s in range(0, 11)], mw.start_delay))
        f = self.field(it, lambda: int(self.mw.start_delay), self._apply_delay,
                       lambda v, c=c: c.set_value(v))
        c.changed.connect(lambda v, f=f: self.set_draft(f, v))
        it = self.item('overlap', '重叠处理')       # 点击切换 (非下拉)
        c = it.add(Cycle(None, k, [('truncate', '截断模式'), ('merge', '叠加模式')],
                         mw.overlap_mode))
        f = self.field(it, lambda: self.mw.overlap_mode, self._apply_overlap,
                       lambda v, c=c: c.set_value(v))
        c.changed.connect(lambda v, f=f: self.set_draft(f, v))

    # ---- 音域分配 ----
    def _pick_oct(self, o):
        self.oct = o
        self.c_oct_row.set_value(self.f_oct.draft.get(o, NO_ASSIGN))

    def _assign_oct(self, row):
        d = dict(self.f_oct.draft); d[self.oct] = row
        self.set_draft(self.f_oct, d)

    def _apply_oct(self, v):
        self.mw.oct_assign = dict(v)
        return True, True

    # ---- 按键分配 ----
    def _pick_krow(self, r):
        self.krow = r
        self.c_krow.set_value(r, flip=False)
        self.cells.set_keys(list(self.f_keys.draft[r][0]))

    def _bind(self, i, ch):
        """同排白键内重复 = 互换; 被其它排 / 黑键占用 = 拒绝 (键格抖动)"""
        keys = dict(self.f_keys.draft)
        white, black = keys[self.krow]
        if ch == white[i]:
            return True
        used = ''.join(w + b for r, (w, b) in keys.items() if r != self.krow) + black
        if ch in used:
            self.mw.statusBar().showMessage('按键 %s 已被其它排或黑键占用' % ch, 3000)
            return False
        w = list(white)
        if ch in w:
            w[w.index(ch)] = w[i]
        w[i] = ch
        keys[self.krow] = (''.join(w), black)
        self.cells.set_keys(w)
        self.set_draft(self.f_keys, keys)
        return True

    def _apply_keys(self, v):
        self.mw.row_keys = dict(v)
        return True, True

    # ---- 映射范围: 选择器勾选 = 草稿 ----
    def _scope_now(self):
        from track_radial import mapped_tids
        return frozenset(mapped_tids(self.mw))

    def _scope_label(self):
        n, tot = len(self.f_scope.draft), len(self.mw.tracks)
        self.b_scope.set_text('音轨 · 全部' if n >= tot else '音轨 · %d/%d' % (n, tot))

    def scope_has(self, tid):
        return tid in self.f_scope.draft

    def scope_toggle(self, tid):
        self.set_draft(self.f_scope, frozenset(self.f_scope.draft ^ {tid}))
        self._scope_label()

    def _open_tracks(self):
        self.ov.open_tracks(self.scope_has, self.scope_toggle)

    def _apply_scope(self, v):
        allt = {t.tid for t in self.mw.tracks}
        self.mw.map_tids = None if set(v) >= allt else set(v)
        return True, True

    # ---- 其余提交 ----
    def _apply_out(self, on):
        """映射输出 (含管理员权限提示与重建, 走主窗键盘输出开关)"""
        mw = self.mw
        mw.chk_out.setChecked(bool(on))
        return mw.chk_out.isChecked() == bool(on), False

    def _apply_mode(self, v):
        mw = self.mw
        mw.piano_mode = v
        t = mw.thread
        if t is not None and t.isRunning():
            t.pianist.mode = v
        return True, False

    def _apply_delay(self, s):
        self.mw.start_delay = int(s)
        return True, False

    def _apply_overlap(self, v):
        self.mw.overlap_mode = v
        return True, True


class AudioPanel(Panel):
    """声音 (西南): 输出设备 / 音效音量 / 音源静音 / 音源音量 / 声音可视化"""
    def build(self):
        mw, k = self.mw, self.k
        it = self.item('device', '输出设备')
        devs = self._devices()
        cur = mw.audio_device or ''
        opts = [('', '系统默认')] + [(d, d) for d in devs]
        if cur and cur not in devs:
            opts.append((cur, cur))
        self.dd_dev = it.add(Dropdown(None, k, opts, cur, px=12))
        self.dd_dev.warn = bool(cur) and cur not in devs       # 设备断开: 警告图标
        f = self.field(it, lambda: self.mw.audio_device or '', self._apply_device,
                       lambda v: self.dd_dev.set_value(v))
        self.dd_dev.picked.connect(lambda v, f=f: self.set_draft(f, v))
        it = self.item('sfx', '音效音量')
        s = it.add(LSlider(None, k, 0, 100, getattr(mw, 'sfx_volume', 100), 100))
        f = self.field(it, lambda: int(getattr(self.mw, 'sfx_volume', 100)),
                       self._apply_sfx, lambda v, s=s: s.set_value(v))
        s.valueChanged.connect(lambda v, f=f: self.set_draft(f, int(v)))
        it = self.item('mute', '音源静音')
        c = it.add(Cycle(None, k, [(True, '开启'), (False, '关闭')], bool(mw.engine.muted)))
        f = self.field(it, lambda: bool(self.mw.engine.muted), self._apply_mute,
                       lambda v, c=c: c.set_value(v))
        c.changed.connect(lambda v, f=f: self.set_draft(f, v))
        it = self.item('gain', '音源音量')
        self.s_gain = it.add(LSlider(None, k, 0, 800, getattr(mw, 'src_gain', 100), 100))
        f = self.field(it, lambda: int(getattr(self.mw, 'src_gain', 100)),
                       self._apply_gain, lambda v: self.s_gain.set_value(v))
        self.s_gain.valueChanged.connect(lambda v, f=f: self.set_draft(f, int(v)))
        self.s_gain.setEnabled(not mw.engine.muted)            # 静音开启时禁用
        it = self.item('viz', '声音可视化')
        b = it.add(LButton(None, k, '预留'))
        b.setEnabled(False)

    def _devices(self):
        try:
            import sys
            from sound import enumerate_audio_devices
            drv = self.mw.audio_driver or ('wasapi' if sys.platform == 'win32' else '')
            return list(dict.fromkeys(enumerate_audio_devices(drv)))
        except Exception:
            return []

    def _apply_device(self, dev):
        mw = self.mw
        mw.audio_device = dev
        store.save_audio(mw.audio_driver, mw.audio_device)
        mw._apply_audio_device()
        self.dd_dev.warn = False; self.dd_dev.update()
        return True, False

    def _apply_sfx(self, v):
        self.mw.sfx_volume = int(v)               # 预留接口: 仅存档
        return True, False

    def _apply_mute(self, on):
        mw = self.mw
        mw._toggle_mute(bool(on))
        b = getattr(mw, 'b_mute', None)
        if b is not None and b.isCheckable():
            b.blockSignals(True); b.setChecked(bool(on)); b.blockSignals(False)
        self.s_gain.setEnabled(not on)
        return bool(mw.engine.muted) == bool(on), False

    def _apply_gain(self, v):
        mw = self.mw
        mw.src_gain = int(v)
        mw.engine.master_gain = mw.src_gain / 100.0
        return True, False


class SongPanel(Panel):
    """歌曲 (东南): 保留接口, 以后录入功能选项 (无设置项 = 无【确认】)"""
    def build(self):
        it = self.item('reserved', '歌曲')
        b = it.add(LButton(None, self.k, '保留接口 · 待录入'))
        b.setEnabled(False)
