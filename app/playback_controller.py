# -*- coding: utf-8 -*-
"""播放控制器 (P2-D 自 mainwindow.py 收编): 播放/暂停/停止/倒计时/线程生命周期/
   速度换算/seek 与擦洗入口/进度条联动/试听。只负责播放领域流程编排;
   时间轴推进在 player.PlayerThread, 发声在 SoundEngine, 按键输出在 KeyPianist。
   mainwindow 保留同名一行委托作为稳定接口 (mini_bar/editor/_smoke_all 调用点零改动)。"""
import time
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QMessageBox
from PySide6.QtMultimedia import QMediaPlayer
from i18n import t as tr
from player import PlayerThread
from pianist import KeyPianist
from keyout import KeyboardOut

_LEAKED_THREADS = []     # (加固) stop 超时的线程保引用: QThread 带活线程被析构
                         # 会刷 "QThread: Destroyed while thread is still running"


class PlaybackController:
    def __init__(self, mw):
        self.mw = mw

    def play_or_stop(self):
        """空格 = 播放↔停止回0 (26); ▶ 按钮 = 播放↔暂停"""
        mw = self.mw
        t = mw.thread
        if t is not None and t.isRunning():
            mw.stop_all()
        elif self._original_playing():
            mw.stop_all()
        else:
            self._start_play()

    def toggle_play(self):
        mw = self.mw
        t = mw.thread
        oa = getattr(mw, 'original_audio', None)
        if t is None or not t.isRunning():
            if self._original_playing():
                # 仅原曲: 暂停
                if oa is not None:
                    oa.pause()
                mw.b_play.setText('▶')
            else:
                self._start_play()
        elif t.paused:
            t.resume(); mw.b_play.setText('⏸')
            if oa is not None and mw.play_original:
                oa.resume()
        else:
            t.pause(); mw.b_play.setText('▶')
            if oa is not None:
                oa.pause()

    def _make_pianist(self):
        mw = self.mw
        out = KeyboardOut(mw.chk_out.isChecked())
        mapper = mw.mapper if mw.chk_out.isChecked() else None
        return KeyPianist(mapper, out, mw.piano_mode,
                          mw.min_hold, mw.min_gap, mw.tap)

    def _want_original(self) -> bool:
        mw = self.mw
        oa = getattr(mw, 'original_audio', None)
        return bool(getattr(mw, 'play_original', False)
                    and oa is not None and oa.path)

    def _playback_total(self) -> float:
        """播放时间轴总长: 音符末尾与原曲时长取较大 (勾选原曲时不提前结束)。"""
        mw = self.mw
        total = float(mw.total_sec or 0)
        if self._want_original():
            oa = mw.original_audio
            dur = float(getattr(oa, 'duration_sec', 0) or 0)
            if dur > 0:
                total = max(total, dur)
        return total

    def _sync_playback_total(self):
        """把主窗 total_sec 撑到播放总长 (进度条/播放头/线程一致)。"""
        mw = self.mw
        total = self._playback_total()
        if total > 0:
            mw.total_sec = max(float(mw.total_sec or 0), total)

    def _original_playing(self) -> bool:
        mw = self.mw
        oa = getattr(mw, 'original_audio', None)
        if oa is None or not getattr(mw, 'play_original', False) or not oa.path:
            return False
        return oa._player.playbackState() == QMediaPlayer.PlayingState

    def _start_play(self):
        mw = self.mw
        if mw._cd_timer is not None: return    # 倒计时进行中: 忽略重复触发
        want_orig = self._want_original()
        if not mw.out_notes and not want_orig:
            QMessageBox.information(mw, tr("提示"),
                                    tr('没有可演奏音符: 请先打开 MIDI,\n'
                                       '并确认键位映射有效 / 调整移调')); return
        if not mw.engine.track_fonts and not want_orig:
            QMessageBox.information(mw, tr("提示"),
                                    tr('请先为音轨指定 SF2 音源:\n'
                                       '在下方音轨概览条上 双击 → 选择音源文件'))
            return
        if mw.chk_out.isChecked() and mw.mapper and mw.mapper.err:
            QMessageBox.warning(mw, tr("映射错误"), mw.mapper.err); return
        if want_orig:
            self._sync_playback_total()
        delay = mw.start_delay
        if delay > 0 and not want_orig:
            mw.b_play.setEnabled(False)
            mw._count = delay
            mw.statusBar().showMessage(
                tr('{n} 秒后开始演奏, 请切换到游戏窗口…', n=delay))
            mw._cd_timer = QTimer(mw); mw._cd_timer.setInterval(1000)
            mw._cd_timer.timeout.connect(self._cd_tick)
            mw._cd_timer.start()
        else:
            self._launch_thread()

    def _cd_tick(self):
        mw = self.mw
        mw._count -= 1
        if mw._count <= 0:
            mw._cd_timer.stop(); mw._cd_timer = None
            mw.b_play.setEnabled(True)
            self._launch_thread()
        else:
            mw.statusBar().showMessage(
                tr('{n} 秒后开始演奏, 请切换到游戏窗口…', n=mw._count))

    def _launch_thread(self):
        mw = self.mw
        self._stop_playback()
        rate = self._speed_factor()
        if self._want_original():
            self._sync_playback_total()
        play_total = self._playback_total()
        has_midi = bool(mw.out_notes and mw.events is not None)
        if has_midi:
            # total 含原曲时长: 最后一个音符之后仍推进播放头, 直到原曲播完
            th = PlayerThread(mw.events, mw.out_notes, max(play_total, 0.001),
                              mw.engine, self._make_pianist(),
                              start=mw.cur_sec,
                              track_ch=mw.engine.track_channels)
            th.speed = rate
            th.playbackFinished.connect(mw._on_thread_done)
            mw.thread = th; th.start()
        else:
            # 仅原曲: 用定时器推进 playhead 到音频结束
            mw.thread = None
            self._start_original_only_timer()
        mw.b_play.setText("⏸")
        if self._want_original():
            mw.original_audio.set_enabled(True)
            mw.original_audio.play_at(mw.cur_sec, rate=rate)

    def _start_original_only_timer(self):
        """无 MIDI 事件时靠定时器推进播放头, 直到原曲结束。"""
        mw = self.mw
        if getattr(mw, '_orig_only_timer', None) is not None:
            mw._orig_only_timer.stop()
        t = QTimer(mw)
        t.setInterval(40)

        def _tick():
            if not getattr(mw, 'play_original', False):
                t.stop(); return
            oa = mw.original_audio
            if oa._player.playbackState() != QMediaPlayer.PlayingState:
                t.stop()
                mw.b_play.setText('▶')
                return
            pos = oa._player.position() / 1000.0
            mw.cur_sec = pos
            mw._update_playhead(pos)

        t.timeout.connect(_tick)
        mw._orig_only_timer = t
        t.start()

    def _on_thread_done(self):
        mw = self.mw
        t = mw.thread
        if t is not None:
            t.wait(1000)
            mw.stat_lbl.setText(mw._stat_full() + '  |  ' +
                tr('整形: 推迟 {a} 丢弃 {b}',
                   a=t.pianist.deferred, b=t.pianist.dropped))
        mw.thread = None
        mw.b_play.setText("▶")
        oa = getattr(mw, 'original_audio', None)
        if oa is not None:
            oa.stop()
        ot = getattr(mw, '_orig_only_timer', None)
        if ot is not None:
            ot.stop()
            mw._orig_only_timer = None
        mw.statusBar().showMessage(tr('演奏完成 (播完停在结尾)'))

    def _stop_playback(self):
        mw = self.mw
        if mw._cd_timer is not None:
            mw._cd_timer.stop(); mw._cd_timer = None
            mw.b_play.setEnabled(True)
        t = mw.thread
        if t is not None:
            t.stop()
            if not t.wait(2000):
                t.wait(5000)                      # 引擎/驱动偶发阻塞: 再给 5s
            if t.isRunning():                     # 仍不退: 保引用防析构警告
                _LEAKED_THREADS[:] = [x for x in _LEAKED_THREADS if x.isRunning()]
                _LEAKED_THREADS.append(t)
            mw.thread = None
        ot = getattr(mw, '_orig_only_timer', None)
        if ot is not None:
            ot.stop()
            mw._orig_only_timer = None
        oa = getattr(mw, 'original_audio', None)
        if oa is not None:
            oa.stop()
        mw.b_play.setText("▶")

    def stop_all(self):
        mw = self.mw
        self._stop_playback()
        self._seek_visual(0.0); mw._update_playhead(0.0)

    def _speed_factor(self):
        """(P 轮) 播放速度 = 设定 BPM / 文件 BPM"""
        mw = self.mw
        return max(0.05, min(8.0, mw.sp_bpm.value() / mw._file_bpm)) \
            if mw._file_bpm else 1.0

    def _bpm_changed(self, _v):
        """(P 轮) BPM 改变 → 换算播放速度, 正在播放时实时生效"""
        mw = self.mw
        rate = self._speed_factor()
        if mw.thread is not None and mw.thread.isRunning():
            mw.thread.set_speed(rate)
        oa = getattr(mw, 'original_audio', None)
        if oa is not None and mw.play_original:
            oa.set_rate(rate)
        import project_session                     # (工程轮) BPM 入工程记忆
        project_session.save(mw)

    # ---------- 定位 / 拖动 ----------
    def _is_playing(self):
        t = self.mw.thread
        if t is not None and t.isRunning() and not t.paused:
            return True
        return self._original_playing()

    def _seek_visual(self, sec):
        mw = self.mw
        mw.cur_sec = min(max(sec, 0.0), max(mw.total_sec, 0.001))
        t = mw.thread
        if t is not None and t.isRunning(): t.vseek(mw.cur_sec)
        oa = getattr(mw, 'original_audio', None)
        if oa is not None and mw.play_original:
            oa.seek(mw.cur_sec)
        mw._update_playhead(mw.cur_sec)

    def _seek_real(self, sec):
        mw = self.mw
        mw.cur_sec = min(max(sec, 0.0), max(mw.total_sec, 0.001))
        t = mw.thread
        if t is not None and t.isRunning(): t.seek(mw.cur_sec)
        oa = getattr(mw, 'original_audio', None)
        if oa is not None and mw.play_original:
            oa.seek(mw.cur_sec)
        mw._update_playhead(mw.cur_sec)

    def _scrub_begin(self):
        mw = self.mw
        mw._was_playing = self._is_playing()
        if mw.thread is not None and mw.thread.isRunning() and not mw.thread.paused:
            mw.thread.pause()
        oa = getattr(mw, 'original_audio', None)
        if oa is not None:
            oa.pause()

    def _scrub_end(self, sec):
        mw = self.mw
        self._seek_real(sec)
        if mw._was_playing:
            if mw.thread is not None and mw.thread.isRunning():
                mw.thread.resume()
            if self._want_original():
                mw.original_audio.resume()

    def _slider_pressed(self):
        mw = self.mw
        mw._dragging = True
        mw._was_playing = self._is_playing()
        if mw.thread is not None and mw.thread.isRunning() and not mw.thread.paused:
            mw.thread.pause()
        oa = getattr(mw, 'original_audio', None)
        if oa is not None:
            oa.pause()

    def _slider_moved(self, v):
        self.mw._seek_visual(v / 1000.0 * max(self.mw.total_sec, 0.001))

    def _slider_released(self):
        mw = self.mw
        mw._dragging = False
        self._seek_real(mw.slider.value() / 1000.0 * max(mw.total_sec, 0.001))
        if mw._was_playing:
            if mw.thread is not None and mw.thread.isRunning():
                mw.thread.resume()
            if self._want_original():
                mw.original_audio.resume()

    def _preview(self, note, on):
        """试听: 走当前轨的发声通道 (该轨未配音源则静默)"""
        mw = self.mw
        ch = mw.engine.track_channels.get(mw.active_tid, 0)
        if on: mw.engine.noteon(note, 100, ch)
        else: mw.engine.noteoff(note, ch)
