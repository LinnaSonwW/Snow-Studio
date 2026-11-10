# -*- coding: utf-8 -*-
"""对话框:
   OctaveMapDialog         音域分配(三排键串 + C1~B7 每个八度 -> 排/不映射)
   TransposeAnalysisDialog 移调分析与选择(-12~+12 黑键/未分配·超域/可演奏统计)
   SettingsDialog          自定义设置(键位/音域分配/播放整形/开始延迟/音域高亮)
   NoteSettingsDialog      音符字母显示 (O 轮新增, 主窗卷帘与编辑器同步生效)
   AppSettingsDialog       输出设备 + 语言 (O 轮新增)
   TrackSoundDialog        轨道独立音源 SF2+音色 (O 轮新增)"""
import os
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QCheckBox,
                               QGroupBox, QLabel, QComboBox,
                               QPushButton, QMessageBox, QSpinBox,
                               QProgressDialog,
                               QTableWidget,
                               QTableWidgetItem, QAbstractItemView, QFileDialog,
                               QTextEdit)
from common import (OCT_RANGE, ROWS, ROW_NAMES, DEFAULT_ROW_KEYS,
                    DEFAULT_ROW_KEYS_BLACK, DEFAULT_OCT_ASSIGN, NO_ASSIGN,
                    NOTE_MIN, NOTE_MAX, BLACK_SET, NOTE_NAMES,
                    NOTE_SOLFA, NOTE_JIANPU)
from i18n import t
from keymap import KeyMapper
from sound import SoundEngine, enumerate_audio_devices


class AppSettingsDialog(QDialog):
    """设置弹窗 (O 轮): 选择系统播放设备(驱动+设备) 与 界面语言
       确定后由主窗应用: 语言即时切换; 设备重建音源引擎(播放中禁止)"""
    def __init__(self, mw):
        super().__init__(mw)
        self.setWindowTitle(t('设置'))
        self.setMinimumWidth(460)
        self.mw = mw
        self.driver = mw.audio_driver            # '' = 自动
        self.device = mw.audio_device            # '' = 系统默认
        self.lang = mw.current_lang
        lay = QVBoxLayout(self)
        # ---- 输出设备 ----
        gd = QGroupBox(t('发声输出设备 (SF2 试听与演奏发声的音频输出)'))
        dg = QGridLayout(gd); dg.setContentsMargins(8, 4, 8, 4)
        dg.addWidget(QLabel(t('驱动')), 0, 0)
        self.cmb_driver = QComboBox()
        self.cmb_driver.addItem(t('自动'), '')
        for drv in SoundEngine.DRIVERS_WIN:
            self.cmb_driver.addItem(drv, drv)
        self.cmb_driver.setCurrentIndex(max(0, self.cmb_driver.findData(self.driver)))
        self.cmb_driver.currentIndexChanged.connect(self._driver_changed)
        dg.addWidget(self.cmb_driver, 0, 1)
        dg.addWidget(QLabel(t('设备')), 1, 0)
        self.cmb_device = QComboBox()
        dg.addWidget(self.cmb_device, 1, 1)
        lb_hint = QLabel(t('切换设备需重建音源; 播放中不可切换'))
        lb_hint.setStyleSheet('color:#999;')
        dg.addWidget(lb_hint, 2, 0, 1, 2)
        lay.addWidget(gd)
        # ---- 语言 ----
        gl = QGroupBox(t('语言 / Language'))
        lg = QGridLayout(gl); lg.setContentsMargins(8, 4, 8, 4)
        lg.addWidget(QLabel(t('语言 / Language')), 0, 0)
        self.cmb_lang = QComboBox()
        self.cmb_lang.addItem(t('中文'), 'zh')
        self.cmb_lang.addItem('English', 'en')
        self.cmb_lang.setCurrentIndex(max(0, self.cmb_lang.findData(self.lang)))
        lg.addWidget(self.cmb_lang, 0, 1)
        lb_lang = QLabel(t('切换立即生效; 如编辑器已打开将先关闭'))
        lb_lang.setStyleSheet('color:#999;')
        lg.addWidget(lb_lang, 1, 0, 1, 2)
        lay.addWidget(gl)
        # ---- (自检轮) 模型扒谱环境自检 ----
        ge = QGroupBox(t('模型扒谱环境自检 (Python / PyTorch / GPU / FFmpeg / 权重)'))
        eg = QVBoxLayout(ge); eg.setContentsMargins(8, 4, 8, 4)
        b_env = QPushButton(t('运行环境自检')); b_env.setFocusPolicy(Qt.NoFocus)
        b_env.setToolTip(t('逐项检测模型扒谱所需环境, 并给出对应显卡的安装建议'))
        self.txt_env = QTextEdit(); self.txt_env.setReadOnly(True)
        self.txt_env.setMinimumHeight(150)
        self.txt_env.setFont(QFont('Consolas', 9))
        self.txt_env.setPlaceholderText(
            t('点击「运行环境自检」检测 Python / PyTorch / GPU / FFmpeg / 模型权重'))
        b_env.clicked.connect(self._run_env_check)
        eg.addWidget(b_env)
        eg.addWidget(self.txt_env)
        lay.addWidget(ge)
        # ---- (导入轮) 模型扒谱: 路线 + 模型压缩包导入 ----
        gm = QGroupBox(t('模型扒谱 (路线 + 模型导入)'))
        mg = QGridLayout(gm); mg.setContentsMargins(8, 4, 8, 4)
        mg.addWidget(QLabel(t('默认转录路线')), 0, 0)
        self.cmb_route = QComboBox()
        self.cmb_route.addItem(t('每次弹窗选择'), '')
        self.cmb_route.addItem(t('钢琴专用 (Transkun)'), 'transkun')
        self.cmb_route.addItem(t('多乐器 (MuScriptor)'), 'muscriptor')
        self.cmb_route.setCurrentIndex(max(0, self.cmb_route.findData(mw.transcribe_route)))
        self.cmb_route.setToolTip(t('选了默认路线后, 点「模型扒谱」直接走该路线, 不再弹窗'))
        mg.addWidget(self.cmb_route, 0, 1)
        b_imp = QPushButton(t('导入模型压缩包…')); b_imp.setFocusPolicy(Qt.NoFocus)
        b_imp.setToolTip(t('选择官方模型压缩包 (zip), 校验唯一哈希通过后安装到 models/'))
        b_imp.clicked.connect(self._import_model)
        mg.addWidget(b_imp, 1, 0)
        lb_imp = QLabel(t('MuScriptor / Transkun 模型均可, 哈希不符将被拒绝'))
        lb_imp.setStyleSheet('color:#999;')
        mg.addWidget(lb_imp, 1, 1)
        self.lb_models = QLabel()
        self.lb_models.setStyleSheet('color:#555;')
        mg.addWidget(self.lb_models, 2, 0, 1, 2)
        lay.addWidget(gm)
        self._refresh_models()
        # ---- (扩展包轮) 扩展包下载 ----
        gx = QGroupBox(t('扩展包下载 (多音高分析 / 模型扒谱依赖 / CUDA 版本)'))
        xg = QGridLayout(gx); xg.setContentsMargins(8, 4, 8, 4)
        b_dl = QPushButton(t('下载扩展包…')); b_dl.setFocusPolicy(Qt.NoFocus)
        b_dl.setToolTip(t('缺多音高分析 / 模型扒谱依赖时在此补齐 (清华 PyPI 镜像); '
                          'CUDA 按显卡细分可选装 (阿里云镜像)'))
        b_dl.clicked.connect(self._open_ext_downloader)
        xg.addWidget(b_dl, 0, 0)
        lb_dl = QLabel(t('下载后自动解压安装; 安装后重启程序生效'))
        lb_dl.setStyleSheet('color:#999;')
        xg.addWidget(lb_dl, 0, 1)
        lay.addWidget(gx)
        bot = QHBoxLayout()
        b_cancel = QPushButton(t('取消')); b_cancel.clicked.connect(self.reject)
        b_ok = QPushButton(t('确定')); b_ok.setDefault(True)
        b_ok.clicked.connect(self._accept)
        bot.addStretch(1); bot.addWidget(b_cancel); bot.addWidget(b_ok)
        lay.addLayout(bot)
        self._driver_changed()
    def _run_env_check(self):
        """(自检轮) 模型扒谱环境逐项检测 → 只读报告框"""
        from transcription_mode import _env_report
        self.txt_env.setPlainText(_env_report())
    def _open_ext_downloader(self):
        """(扩展包轮) 弹出扩展包下载器"""
        from dialogs.extension_downloader import ExtensionDownloaderDialog
        ExtensionDownloaderDialog(self).exec()
    def _refresh_models(self):
        """(导入轮) 当前模型安装状态行"""
        from model_import import MODEL_PACKS, model_status
        st = model_status()
        self.lb_models.setText(t('模型状态: ') + '   '.join(
            ('✓ ' if st[p['id']] else '✗ ') + p['label'] for p in MODEL_PACKS))
    def _import_model(self):
        """(导入轮) 选择模型压缩包 → 后台哈希校验 → 解压安装到 models/"""
        from model_import import ModelImportWorker
        path, _f = QFileDialog.getOpenFileName(
            self, t('选择模型压缩包'), '', t('模型压缩包 (*.zip)'))
        if not path:
            return
        self._start_import(ModelImportWorker(path, parent=self))
    def _start_import(self, worker):
        """启动导入 Worker, 附模态进度与覆盖确认"""
        from model_import import MODEL_PACKS
        self._imp = worker
        pd = QProgressDialog(t('正在导入模型 (哈希校验/解压)…'), t('取消'),
                             0, 100, self)
        pd.setWindowModality(Qt.WindowModal)
        pd.setMinimumDuration(0)
        self._pd = pd

        def on_tick(phase, done, total, msg):
            pd.setLabelText('%s  %s' % (phase, msg))
            if total > 0:
                pd.setRange(0, 100)
                pd.setValue(min(100, done * 100 // total))
            else:
                pd.setRange(0, 0)

        def on_done(mid):
            pd.close()
            self._refresh_models()
            for p in MODEL_PACKS:
                if p['id'] == mid:
                    QMessageBox.information(
                        self, t('导入完成'),
                        t('%s 已安装到 models/%s') % (p['label'], p['target']))

        def on_failed(err):
            pd.close()
            QMessageBox.warning(self, t('导入失败'), err)

        def on_confirm(mid):
            pd.close()
            for p in MODEL_PACKS:
                if p['id'] == mid:
                    if QMessageBox.question(
                            self, t('模型已存在'),
                            t('%s 已安装, 覆盖吗?') % p['label']) == QMessageBox.Yes:
                        from model_import import ModelImportWorker as W
                        self._start_import(W(worker.zip_path, pack=p,
                                             overwrite=True, parent=self))
                    return

        worker.tick.connect(on_tick)
        worker.done.connect(on_done)
        worker.failed.connect(on_failed)
        worker.need_confirm.connect(on_confirm)
        pd.canceled.connect(worker.stop)
        worker.start()
    def _driver_changed(self, *_i):
        drv = self.cmb_driver.currentData()
        keep = self.cmb_device.currentText()
        self.cmb_device.clear()
        self.cmb_device.addItem(t('系统默认'), '')
        devs = enumerate_audio_devices(drv) if drv else []
        for d in devs:
            self.cmb_device.addItem(d, d)
        self.cmb_device.setEnabled(bool(drv))
        if drv:                                   # 恢复原选择 (仍在列表时)
            i = self.cmb_device.findData(self.device)
            if i > 0: self.cmb_device.setCurrentIndex(i)
            elif keep: self.cmb_device.setEditText(keep)
    def _accept(self):
        drv = self.cmb_driver.currentData()
        dev = self.cmb_device.currentData() or ''
        if ((drv, dev) != (self.mw.audio_driver, self.mw.audio_device)
                and self.mw._is_playing()):
            QMessageBox.warning(self, t('提示'),
                                t('切换设备需重建音源; 播放中不可切换'))
            return
        self.driver = drv; self.device = dev
        self.lang = self.cmb_lang.currentData()
        self.transcribe_route = self.cmb_route.currentData() or ''
        import settings_store as _store
        _store.save_transcribe_cfg(self.transcribe_route)
        self.accept()
