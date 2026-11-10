# -*- coding: utf-8 -*-
"""音频分离 Worker (分离轮): BS-Roformer (SW 六轨 / Inst 人声伴奏)。
   推理由 bs-roformer-infer 的 CLI 完成 (输入文件夹内全部 wav →
   <原名单>_<instr>.wav 输出)。
   执行环境自动选择: 便携版本地有 torch → 自身进程解释器;
   否则借用系统 Python (sys_bridge, 需 torch + bs_roformer 组件)。"""
import os
import shutil
import subprocess
import tempfile

from PySide6.QtCore import QThread, Signal

import paths
from i18n import t
from transcription_mode import _bridge, _local_torch

CREATE_NO_WINDOW = 0x08000000

# 模型 → (ckpt, yaml)  相对 data/models
_MODELS = {
    'sw': ('separation/sw/BS-Roformer-SW.ckpt',
           'separation/sw/BS-Roformer-SW.yaml'),
    'inst': ('separation/inst/BS-Roformer-Resurrection-Inst.ckpt',
             'separation/inst/BS-Roformer-Resurrection-Inst.yaml'),
}


def model_paths(model):
    """模型 ckpt/yaml 绝对路径; 未导入 → (None, None)"""
    ck, cf = _MODELS[model]
    ck_p = os.path.join(paths.models_dir(), *ck.split('/'))
    cf_p = os.path.join(paths.models_dir(), *cf.split('/'))
    return (ck_p if os.path.isfile(ck_p) else None,
            cf_p if os.path.isfile(cf_p) else None)


def ensure_inference_cfg(yaml_path):
    """幂等补丁: Sucial 原版 yaml 缺 bs-roformer-infer 所需的
       inference.num_overlap (文本级插入, 避开 !!python/tuple 解析)。"""
    try:
        with open(yaml_path, encoding='utf-8') as f:
            text = f.read()
        if 'num_overlap' in text:
            return
        out = []
        inserted = False
        for line in text.splitlines():
            out.append(line)
            if not inserted and line.strip() == 'inference:':
                out.append('  num_overlap: 4')
                inserted = True
        if inserted:
            with open(yaml_path, 'w', encoding='utf-8') as f:
                f.write('\n'.join(out) + '\n')
    except OSError:
        pass


def separation_available(model):
    ck, cf = model_paths(model)
    return bool(ck and cf)


_CUDA_CACHE: dict = {}                         # 解释器路径 → 是否有 CUDA


def has_cuda(interp):
    """解释器的 torch 是否可用 CUDA (结果按解释器缓存); 探测失败 → False"""
    if interp not in _CUDA_CACHE:
        try:
            r = subprocess.run(
                [interp, '-c',
                 'import torch;print(1 if torch.cuda.is_available() else 0)'],
                capture_output=True, text=True, timeout=120,
                creationflags=CREATE_NO_WINDOW)
            _CUDA_CACHE[interp] = r.stdout.strip().endswith('1')
        except Exception:
            _CUDA_CACHE[interp] = False
    return _CUDA_CACHE[interp]


def child_env():
    """子进程环境: 强制 UTF-8 stdio (中文 Windows 默认 GBK 会崩)"""
    env = dict(os.environ)
    env['PYTHONUTF8'] = '1'
    env['PYTHONIOENCODING'] = 'utf-8'
    return env


class SeparationWorker(QThread):
    """音频分离: CLI 批处理 (输入目录内全部 wav)。
       progress(pct, 0, msg) 汇报推理余量; stems_ready([(instr, path)...])
       汇报产出的分轨; finished_ok / failed 收尾。"""

    progress = Signal(int, int, str)
    stems_ready = Signal(list)
    finished_ok = Signal()
    failed = Signal(str)

    def __init__(self, audio_path: str, model: str = 'sw', parent=None):
        super().__init__(parent)
        self.audio_path = audio_path
        self.model = model
        self._proc: subprocess.Popen | None = None
        self._abort = False

    def stop(self):
        self._abort = True
        if self._proc is not None and self._proc.poll() is None:
            try:
                self._proc.kill()
            except Exception:
                pass

    # ---- 解释器选择: 本地 torch 优先, 否则系统 Python 桥接 ----
    def _interpreter(self):
        if _local_torch():
            import sys
            return sys.executable, None
        br = _bridge()
        if br:
            return br['python'], 'bridge'
        return None, None

    def run(self):
        try:
            ck, cf = model_paths(self.model)
            if not (ck and cf):
                self.failed.emit('分离模型未导入: 请在「导入模型压缩包」'
                                 f'安装 {self.model} 模型')
                return
            ensure_inference_cfg(cf)               # (兼容轮) 补 num_overlap 字段
            interp, mode = self._interpreter()
            if not interp:
                self.failed.emit('没有可用的推理环境: 本地无 torch, 也未找到'
                                 '可借用的系统 Python (需 torch + bs_roformer)。'
                                 '请在「扩展包下载」安装 CUDA 版本与模型扒谱依赖。')
                return
            use_cuda = has_cuda(interp)            # (GPU 轮) 检测可用 CUDA
            dev = 'cuda' if use_cuda else 'cpu'
            self.progress.emit(0, 0, t('推理设备: ')
                               + ('CUDA (GPU)' if use_cuda else 'CPU'))
            self.progress.emit(0, 0, '准备音频…')
            in_dir = tempfile.mkdtemp(prefix='sepin_')
            out_dir = tempfile.mkdtemp(prefix='sepout_')
            base = os.path.splitext(os.path.basename(self.audio_path))[0]
            wav_in = os.path.join(in_dir, base + '.wav')
            if self.audio_path.lower().endswith('.wav'):
                shutil.copyfile(self.audio_path, wav_in)
            else:                                      # mp3/flac… → ffmpeg 转 wav
                ff = os.path.join(paths.ffmpeg_dir(), 'ffmpeg.exe')
                if not os.path.isfile(ff):
                    ff = 'ffmpeg'
                r = subprocess.run([ff, '-y', '-loglevel', 'error', '-i',
                                    self.audio_path, '-ar', '44100', '-ac',
                                    '2', wav_in], capture_output=True,
                                   creationflags=CREATE_NO_WINDOW)
                if r.returncode != 0 or not os.path.isfile(wav_in):
                    self.failed.emit('音频转换失败 (ffmpeg)')
                    return
            cmd = [interp, '-c',
                   'from bs_roformer.inference import main; main()',
                   '--input_folder', in_dir, '--store_dir', out_dir,
                   '--config_path', cf, '--model_path', ck,
                   '--device', dev]
            self.progress.emit(0, 0, '模型加载与推理中…')
            self._proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding='utf-8', errors='replace',
                cwd=out_dir, creationflags=CREATE_NO_WINDOW,
                env=child_env())
            for line in self._proc.stdout:             # 进度: 剩余时间/分块
                line = line.strip()
                if line and not self._abort:
                    self.progress.emit(0, 0, line[-120:])
            rc = self._proc.wait()
            if self._abort:
                self.failed.emit('已取消')
                return
            if rc != 0:
                err = ''.join(self._proc.stderr.readlines()[-6:])
                self.failed.emit(f'系统组件执行失败 (exit {rc}):\n{err}')
                return
            stems = []
            for f in sorted(os.listdir(out_dir)):
                if f.lower().endswith('.wav') and f.startswith(base + '_'):
                    instr = f[len(base) + 1:-4]
                    dst = os.path.join(out_dir, f)
                    stems.append((instr, dst))
            if not stems:
                self.failed.emit('分离完成但没有产出音轨')
                return
            self.stems_ready.emit(stems)
            self.finished_ok.emit()
        except Exception as e:
            self.failed.emit(str(e))
