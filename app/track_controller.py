# -*- coding: utf-8 -*-
"""轨道控制器 (P2-D 自 mainwindow.py 收编): 轨道增删改名/静音切换/当前轨切换/
   音域高亮/发声轨集合/每轨独立 SF2 应用。只负责轨道领域流程编排;
   甲板绘制在 tracks_panel.py, SF2 内部在 sound.py, 数据重建走 mw._rebuild。
   mainwindow 保留同名一行委托作为稳定接口 (tracks_panel/_smoke_all 调用点零改动)。"""
from PySide6.QtWidgets import QMessageBox, QDialog
from i18n import t as tr
from midi_data import Track
from tracks_panel import track_hex
from dialogs import TrackSoundDialog


class TrackController:
    def __init__(self, mw):
        self.mw = mw

    def _range_notes(self):
        """(D4) 当前音域高亮范围 -> (MIDI lo, hi) 或 (None, None)"""
        mw = self.mw
        if not mw.range_hl_on: return None, None
        lo_o, hi_o = sorted((mw.range_lo, mw.range_hi))
        return (lo_o + 1) * 12, (hi_o + 1) * 12 + 11
    def _apply_range_hl(self):
        """(D4) 音域高亮应用到已存在的编辑卷帘 (主窗无卷帘)"""
        mw = self.mw
        lo, hi = self._range_notes()
        if mw.edit_roll is not None:
            mw.edit_roll.set_range_highlight(lo, hi)
    # ---------- 多音轨: 发声过滤与轨道 UI ----------
    def _sound_tids(self):
        """发声轨道集合: 未静音轨 (鼓轨默认静音; 静音由甲板色块控制, 独立于主窗静音)"""
        return {t.tid for t in self.mw.tracks if not t.muted}
    def _sync_track_ui(self):
        """甲板/编辑卷帘轨道色/当前轨下拉/音源标记 同步 (行点击/导入/编辑提交后调用)"""
        mw = self.mw
        mw.total_tick_display = max(
            (nt.end_tick for nt in mw.raw_notes),
            default=float(getattr(mw, 'bar_ticks', 1920.0) or 1920.0) * 8)
        colors = {t.tid: track_hex(t.tid) for t in mw.tracks}
        if mw.edit_roll is not None:
            mw.edit_roll.set_track_colors(colors)
        fonts = set(mw.engine.track_fonts)
        mw.deck.reload(mw.tracks, mw.active_tid, fonts,
                       mw.total_tick_display)
        if mw.track_btn is not None:
            mw.track_btn.reload(mw.tracks, mw.active_tid)
    def _on_track_toggle(self, tid, kind):
        mw = self.mw
        t = next((x for x in mw.tracks if x.tid == tid), None)
        if t is None: return
        t.muted = not t.muted                      # (Q 轮) 色块静音: 仅该轨
        mw._rebuild(keep_view=True)              # 发声集合变化 → 重建事件表
        self._sync_track_ui()
        import project_session                     # (工程轮) 静音态入工程记忆
        project_session.save(mw)
    def _on_track_activate(self, tid):
        mw = self.mw
        mw.active_tid = tid                      # 甲板/编辑器当前轨切换
        if mw.edit_roll is not None:
            mw.edit_roll.set_active_tid(tid)     # (P2-E) 公开 API
        if mw.map_scope == 'active':             # (P 轮) 仅映射当前轨: 重建输出
            mw._rebuild(keep_view=True)
        self._sync_track_ui()
    def _track_add(self):
        """(P 轮) 甲板 + 按钮: 新增空音轨 (在编辑器中选中该轨绘制音符)"""
        mw = self.mw
        # 无 MIDI 时也允许建轨: 顺带初始化空时间轴, 便于立刻打开卷帘
        if mw.tmap is None:
            from midi_data import TempoMap
            tpb = 480
            bpm = float(getattr(mw, '_file_bpm', 120.0) or 120.0)
            mw.tmap = TempoMap(tpb, [(0, int(60e6 / bpm))])
            mw.bar_ticks = float(4 * tpb)
            if not mw.raw_notes:
                mw.raw_notes = []
            mw.total_tick_display = max(
                float(getattr(mw, 'total_tick_display', 0) or 0),
                float(mw.bar_ticks * 8))
        tid = (max(t.tid for t in mw.tracks) + 1) if mw.tracks else 0
        mw.tracks.append(Track(tid=tid, name=tr('新音轨 {n}', n=tid + 1)))
        mw.active_tid = tid
        if mw.edit_roll is not None:
            mw.edit_roll.set_active_tid(tid)     # (P2-E) 公开 API
        self._sync_track_ui()
        mw.statusBar().showMessage(
            tr('已新增音轨 {n}: 在编辑器中选中该轨即可绘制音符', n=tid + 1), 5000)
    def _track_remove(self, tid):
        """(Q 轮) 甲板右键 删除音轨: 连同该轨音符与独立音源一并移除"""
        mw = self.mw
        t = next((x for x in mw.tracks if x.tid == tid), None)
        if t is None: return
        if len(mw.tracks) <= 1:
            QMessageBox.information(mw, tr("提示"), tr('至少保留一条音轨')); return
        n = sum(1 for nt in mw.raw_notes if nt.tid == tid)
        if n:
            ret = QMessageBox.question(
                mw, tr('删除音轨'),
                tr('将删除音轨「{name}」及其 {n} 个音符, 确定?',
                   name=t.name or tr('轨道 {n}', n=tid + 1), n=n),
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if ret != QMessageBox.Yes: return
        gone = {nt.nid for nt in mw.raw_notes if nt.tid == tid}
        mw.engine.clear_track_font(tid)
        mw.raw_notes[:] = [nt for nt in mw.raw_notes if nt.tid != tid]
        mw.tracks = [t for t in mw.tracks if t.tid != tid]
        if mw.edit_roll is not None:
            mw.edit_roll.discard_selection(gone)  # (P2-E) 公开 API
            mw.edit_roll.hidden_tids.discard(tid)
        if mw.active_tid == tid:
            mw.active_tid = mw.tracks[0].tid if mw.tracks else 0
            if mw.edit_roll is not None:
                mw.edit_roll.set_active_tid(mw.active_tid)
        mw._rebuild(keep_view=True)
        self._sync_track_ui()
        mw.statusBar().showMessage(tr('音轨已删除'), 3000)
    def _on_track_rename(self, tid, name):
        mw = self.mw
        t = next((x for x in mw.tracks if x.tid == tid), None)
        if t is not None and name: t.name = name
        self._sync_track_ui()
    # ---------- (O 轮) 每轨独立 SF2 音源 ----------
    def _on_track_sound(self, tid):
        """甲板 名称按钮/概览条 双击: 重命名轨道 + 为其指定独立 SF2 / 音色#"""
        mw = self.mw
        t = next((x for x in mw.tracks if x.tid == tid), None)
        if t is None: return
        dlg = TrackSoundDialog(mw, t, mw.engine.track_fonts.get(tid))
        if dlg.exec() != QDialog.Accepted: return
        if dlg.new_name and dlg.new_name != t.name:
            t.name = dlg.new_name                       # (Q 轮) 弹窗内重命名
        self._apply_track_font(tid, dlg.path, dlg.preset, gain=dlg.gain)
    def _apply_track_font(self, tid, path, preset, gain=1.0):
        """应用/清除轨道独立音源 (清除 = 该轨静默); 即时生效; gain=1.0~8.0"""
        mw = self.mw
        t = next((x for x in mw.tracks if x.tid == tid), None)
        is_drum = bool(t and t.is_drum)
        try:
            if path:
                mw.engine.load_track_font(
                    tid, path, preset, is_drum=is_drum, gain=gain)
            else:
                mw.engine.clear_track_font(tid)
        except Exception as e:
            QMessageBox.warning(mw, tr('SF2 加载失败'), str(e)); return
        self._sync_track_ui()                      # 音源按钮琥珀态刷新
        import project_session                     # (工程轮) 音源入工程记忆
        project_session.save(mw)
        mw.statusBar().showMessage(tr('轨道音源已应用'), 3000)
