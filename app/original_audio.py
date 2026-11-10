# -*- coding: utf-8 -*-
"""原曲音频播放: QMediaPlayer 与钢琴卷帘/主窗播放头同步。

勾选「播放原曲」后, 随空格/▶/擦洗/seek 启停与定位。
音源优先用扒谱音频; 也可手动选择任意音频文件。
"""
from __future__ import annotations
import os

from PySide6.QtCore import QObject, QUrl, Signal
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput


class OriginalAudioPlayer(QObject):
    """薄封装: set_source / play_at / pause / resume / stop / seek。"""

    source_changed = Signal(str)   # path or ''
    error = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._path = ''
        self._duration_sec = 0.0
        self._enabled = False
        self._audio = QAudioOutput(self)
        self._player = QMediaPlayer(self)
        self._player.setAudioOutput(self._audio)
        self._player.errorOccurred.connect(self._on_error)
        self._player.durationChanged.connect(self._on_duration)

    @property
    def path(self) -> str:
        return self._path

    @property
    def duration_sec(self) -> float:
        return self._duration_sec

    @property
    def enabled(self) -> bool:
        return self._enabled

    def set_enabled(self, on: bool):
        self._enabled = bool(on)
        if not self._enabled:
            self.stop()

    def set_source(self, path: str | None):
        path = (path or '').strip()
        if path == self._path:
            return
        self.stop()
        self._path = path
        self._duration_sec = 0.0
        if path and os.path.isfile(path):
            self._player.setSource(QUrl.fromLocalFile(os.path.abspath(path)))
            # 时长可能异步到达; 同步兜底
            try:
                import librosa
                self._duration_sec = float(librosa.get_duration(path=path))
            except Exception:
                pass
        else:
            self._path = ''
            self._player.setSource(QUrl())
        self.source_changed.emit(self._path)

    def _on_duration(self, ms: int):
        if ms > 0:
            self._duration_sec = max(self._duration_sec, ms / 1000.0)

    def _on_error(self, *_args):
        err = self._player.errorString() or '音频播放失败'
        self.error.emit(err)

    def play_at(self, sec: float, *, rate: float = 1.0):
        if not self._enabled or not self._path:
            return
        self._player.setPlaybackRate(max(0.05, min(4.0, float(rate))))
        self.seek(sec)
        if self._player.playbackState() != QMediaPlayer.PlayingState:
            self._player.play()

    def pause(self):
        if self._player.playbackState() == QMediaPlayer.PlayingState:
            self._player.pause()

    def resume(self):
        if not self._enabled or not self._path:
            return
        if self._player.playbackState() != QMediaPlayer.PlayingState:
            self._player.play()

    def stop(self):
        self._player.stop()

    def seek(self, sec: float):
        if not self._path:
            return
        ms = int(max(0.0, float(sec)) * 1000)
        self._player.setPosition(ms)

    def set_rate(self, rate: float):
        self._player.setPlaybackRate(max(0.05, min(4.0, float(rate))))

    def set_volume(self, vol: float):
        """线性音量 0.0~1.0 (对应 UI 0%~100%)。"""
        self._audio.setVolume(max(0.0, min(1.0, float(vol))))

    @property
    def volume(self) -> float:
        return float(self._audio.volume())
