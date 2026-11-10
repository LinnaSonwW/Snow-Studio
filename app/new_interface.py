# -*- coding: utf-8 -*-
"""Independent QML workspace; the legacy window owns all application state."""
import os

from PySide6.QtCore import Qt, Signal, Slot, QUrl
from PySide6.QtQuickWidgets import QQuickWidget
from PySide6.QtWidgets import QWidget, QVBoxLayout


class NewInterfaceWindow(QWidget):
    return_requested = Signal()

    def __init__(self, main_window, qml_path=None):
        super().__init__(None, Qt.Window | Qt.FramelessWindowHint)
        self.main_window = main_window
        self._shutting_down = False
        self.setWindowTitle('Snow 原琴工作站 · 新界面')
        self.setMinimumSize(420, 300)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.quick = QQuickWidget(self)
        self.quick.setResizeMode(QQuickWidget.SizeRootObjectToView)
        self.quick.rootContext().setContextProperty('newInterfaceHost', self)
        self.quick.statusChanged.connect(self._qml_status_changed)
        layout.addWidget(self.quick)
        path = qml_path or os.path.join(os.path.dirname(__file__), 'NewInterface.qml')
        self.quick.setSource(QUrl.fromLocalFile(os.path.abspath(path)))
        if self.quick.status() != QQuickWidget.Ready:
            message = self._qml_error()
            self.deleteLater()
            raise RuntimeError(message)

    def _qml_error(self):
        return '; '.join(error.toString() for error in self.quick.errors()) or 'QML 未就绪'

    def _qml_status_changed(self, status):
        if status == QQuickWidget.Error and self.isVisible():
            self.main_window.statusBar().showMessage(self._qml_error(), 5000)
            self.return_requested.emit()

    @Slot()
    def returnToLegacy(self):
        if not self._shutting_down:
            self.return_requested.emit()

    def closeEvent(self, event):
        if self._shutting_down:
            event.accept()
        else:
            event.ignore()
            self.returnToLegacy()

    def shutdown(self):
        self._shutting_down = True
        self.close()
        self.deleteLater()
