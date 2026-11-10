# -*- coding: utf-8 -*-
"""Shared audio separation and task status for transcription workspaces."""
from PySide6.QtCore import QObject, Signal
import separation


class TranscribeWorkspace(QObject):
    changed = Signal()
    stems_added = Signal(list)

    def __init__(self, mw):
        super().__init__(mw)
        self.mw = mw
        self.views = []
        self.audio_path = ''
        self.stems = []
        self.worker = None
        self._workers = set()
        self.status = '就绪'
        self.progress = (0, 0)
        self.beat_text = ''
        self.beat_callback = None
        ctrl = mw.transcription_ctrl
        ctrl.progress.connect(self._progress)
        ctrl.running_changed.connect(self.changed)
        ctrl.transcription_complete.connect(self._done)
        ctrl.model_failed.connect(self._failed)
        ctrl.tissue_failed.connect(self._failed)
        ctrl.mode_exited.connect(self._exited)

    def register(self, view):
        self.views.append(view)
        view.set_audio(self.audio_path, publish=False) if self.audio_path else None
        view._add_stems(self.stems)
        view.set_beat_result(self.beat_text, self.beat_callback, publish=False)
        self.changed.connect(view.sync_state)
        self.stems_added.connect(view._add_stems)
        view.sync_state()

    def unregister(self, view):
        if view in self.views:
            self.views.remove(view)
            self.changed.disconnect(view.sync_state)
            self.stems_added.disconnect(view._add_stems)

    def set_audio(self, path):
        self.audio_path = path
        for view in self.views:
            view.set_audio(path, publish=False)

    def _progress(self, done, total, message):
        self.status = message
        self.progress = (done, total)
        self.changed.emit()

    def _done(self):
        self.progress = (0, 0)
        self.changed.emit()

    def _failed(self, message):
        self.status = message
        self.progress = (0, 0)
        self.changed.emit()

    def _exited(self):
        self.status = '就绪'
        self.progress = (0, 0)
        self.changed.emit()

    def start_separation(self, model):
        if self.worker is not None:
            return
        if not self.audio_path:
            self._failed('请先选择音频')
            return
        if not separation.separation_available(model):
            self._failed('分离模型未导入 — 请在「导入模型压缩包」安装对应模型 zip')
            return
        worker = separation.SeparationWorker(self.audio_path, model=model)
        self.worker = worker
        self._workers.add(worker)
        worker.progress.connect(self._sep_progress)
        worker.stems_ready.connect(self._sep_stems)
        worker.failed.connect(self._sep_failed)
        worker.finished.connect(self._sep_finished)
        self.status = '分离中…'
        self.changed.emit()
        worker.start()

    def _sep_progress(self, done, total, message):
        if self.sender() is self.worker:
            self._progress(done, total, message[-120:])

    def _sep_stems(self, stems):
        if self.sender() is not self.worker:
            return
        self.stems.extend(stems)
        self.stems_added.emit(stems)
        self.status = '分离完成 — 音轨已加入下方工作台'
        self.changed.emit()

    def _sep_failed(self, message):
        if self.sender() is self.worker:
            self._failed(message)

    def _sep_finished(self):
        worker = self.sender()
        self._workers.discard(worker)
        if self.worker is worker:
            self.worker = None
        worker.deleteLater()
        self.changed.emit()

    def remove_stem(self, path):
        self.stems = [(instrument, source) for instrument, source in self.stems if source != path]
        for view in self.views:
            view._remove_stem_path(path)

    def shutdown(self):
        self.worker = None
        for worker in list(self._workers):
            worker.stop()
            worker.wait(1000)
        if any(worker.isRunning() for worker in self._workers):
            return False
        for view in list(self.views):
            view.dispose()
        return True
