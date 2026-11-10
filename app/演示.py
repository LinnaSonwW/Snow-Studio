# -*- coding: utf-8 -*-
"""入口: 深色主题 + 主窗口
   运行: python 演示.py    (依赖: PySide6, mido; 可选 pyfluidsynth)
   模块划分见各文件头部注释, 修 bug / 加功能时只需提交对应模块文件。"""
import os
import sys
import faulthandler
faulthandler.enable()

# (内置轮) librosa 及其依赖链移植于 _vendor/ 或 data/vendor/: 最终用户免 pip 安装。
# append 回退式 —— 本机已装 librosa 时优先用系统环境
import paths
_VENDOR = paths.vendor_dir()
if os.path.isdir(_VENDOR) and _VENDOR not in sys.path:
    sys.path.append(_VENDOR)

# (内置轮) FFmpeg: 音频解码/转写加载用; 前置到进程 PATH, 免安装且优先于系统
_FFMPEG = paths.ffmpeg_dir()
if os.path.isfile(os.path.join(_FFMPEG, 'ffmpeg.exe')):
    os.environ['PATH'] = _FFMPEG + os.pathsep + os.environ.get('PATH', '')

_FS = paths.fluidsynth_dir()
if os.path.isdir(_FS):
    os.environ['FLUIDSYNTH_HOME'] = _FS
    os.environ['PATH'] = _FS + os.pathsep + os.environ.get('PATH', '')

from PySide6.QtGui import QColor, QPalette
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
import i18n
import settings_store as store
import project_session                     # (工程轮) 编曲工程记忆
from mainwindow import MainWindow


def apply_dark(app):
    pal = QPalette()
    pal.setColor(QPalette.Window, QColor('#1e1e24')); pal.setColor(QPalette.WindowText, QColor('#d6d6de'))
    pal.setColor(QPalette.Base, QColor('#17171c')); pal.setColor(QPalette.Text, QColor('#d6d6de'))
    pal.setColor(QPalette.Button, QColor('#26262e')); pal.setColor(QPalette.ButtonText, QColor('#d6d6de'))
    pal.setColor(QPalette.Highlight, QColor('#3d6ea5')); pal.setColor(QPalette.HighlightedText, QColor('#ffffff'))
    app.setStyle('Fusion'); app.setPalette(pal)


def main():
    app = QApplication(sys.argv)
    apply_dark(app)
    i18n.set_lang(store.load_lang())
    win = MainWindow(); win.show()
    # (工程轮) 启动自动续开: 读取最后一个工程的伴生记忆 (音源/设置) 并恢复
    QTimer.singleShot(0, lambda: project_session.autoload(win))
    sys.exit(app.exec())


if __name__ == '__main__':
    try:
        main()
    except Exception:
        import traceback
        traceback.print_exc()
        raise
