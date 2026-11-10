# -*- coding: utf-8 -*-
"""音频转录控制器: 多音高分析 (声组织) 与 MuScriptor 模型扒谱 为两项独立功能。

  · start_multipitch  — librosa 多音高 → Pitch Tissue (只读参考层)
  · start_model       — MuScriptor → 按乐器建轨写音符

两项可单独运行, 也可先后对同一音频各跑一遍; 互不强制绑定。
"""
from __future__ import annotations
import json
import os
import subprocess
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, QThread, Signal, QTimer
from PySide6.QtGui import QPainter

from midi_data import Note, TempoMap, Track
from pitch_tissue import PitchTissue
from multipitch_tissue import MultipitchTissueWorker
import paths
import sys_bridge

_DEFAULT_MODEL_DIR = Path(paths.models_dir()) / 'muscriptor_small'


def _model_dir() -> Path:
    """MuScriptor 模型目录: 环境变量优先 (设置内可改), 否则项目内置目录"""
    d = os.environ.get('MUSCRIPTOR_MODEL_DIR')
    return Path(d) if d else _DEFAULT_MODEL_DIR


DEFAULT_MODEL_DIR = _model_dir()


def resolve_model_weights() -> str | Path:
    d = _model_dir()
    local = d / 'model.safetensors'
    if local.is_file():
        return local
    if d.is_dir() and (d / 'config.json').is_file():
        return d
    return 'small'


# (分支轮) 转录引擎注册表: 弹窗/设置按此表生成, 新增模型只需扩展此元组
# (id, 名称, 说明)
TRANSCRIBE_ENGINES = (
    ('transkun', '钢琴专用路线',
     'Transkun v2 · 钢琴单音色高精度转录, 结果写入单轨'),
    ('muscriptor', '多乐器路线',
     'MuScriptor · 多乐器自动检测/指定, 按乐器分轨'),
)


def _pkg_on_disk(name):
    """(自检诊断) 组件目录是否已落在扩展目录 —— 区分「没下载」与「下载了但导入失败」"""
    for base in (paths.vendor_dir(), os.path.join(paths.APP_ROOT, '_vendor')):
        if os.path.isdir(os.path.join(base, name)):
            return base
    return None


def _muscriptor_fail_lines(e):
    """③ muscriptor 导入失败时的解释行 (组件/权重二分 + 双轨指引)"""
    lines = []
    if 'torch' in str(e):
        lines.append('   组件本身在, 是它依赖的 PyTorch 导入失败 —— '
                     '先按 ② 解决 PyTorch, 再重启程序')
    else:
        lines.append('   安装方法 (便捷版): 设置 → 扩展包下载 → '
                     '「模型扒谱依赖扩展包」, 装完重启程序')
    if str(resolve_model_weights()) != 'small':
        lines.append('   备注: ⑦ 的模型权重已就绪; 本条检查的是 Python 组件'
                     ' (来自「扩展包下载」), 与模型文件是两回事')
    lines.append(f'   主版本命令行: pip install muscriptor ({e})')
    return lines


def _local_torch() -> bool:
    """本地 (隔离环境) 是否已能拿到 torch"""
    import importlib.util
    try:
        return importlib.util.find_spec('torch') is not None
    except Exception:
        return False


def _bridge() -> dict | None:
    """可借用的系统 Python 环境 (torch + 组件), 无 → None"""
    try:
        import sys_bridge
        return sys_bridge.find_bridge()
    except Exception:
        return None


def _env_report(exc: Exception | None = None) -> str:
    """(环境自检) 模型扒谱环境逐项检测报告 —— 普通用户可读的大白话分条目格式:
       ①Python ②PyTorch ③MuScriptor ④Transkun ⑤librosa ⑥FFmpeg ⑦模型权重;
       传入 exc 时按异常关键词追加针对性修复提示 (CUDA 算力不兼容 → 显卡对照;
       OOM → 换小模型; HF 授权 → 登录/离线权重)。检测逻辑与旧版完全一致。"""
    import shutil
    import sys
    Y, N = '✓', '✗'
    lines = ['—— 模型扒谱环境自检 ——', '']
    missing = []

    # ① Python
    v = sys.version_info
    py_ok = (3, 10) <= v <= (3, 12)
    lines.append(f'① Python 运行环境')
    lines.append(f'   {Y} 正常 ({v.major}.{v.minor}.{v.micro})' if py_ok else
                 f'   {N} 版本 {v.major}.{v.minor}.{v.micro} 过新或过旧 ——'
                 ' 本组件需要 Python 3.10~3.12')
    if not py_ok:
        missing.append('①')

    # ② PyTorch (AI 运行框架)
    br = _bridge()                                # 桥接探测 (进程内缓存)
    lines.append('')
    lines.append('② AI 运行框架 (PyTorch)')
    torch_missing = False
    try:
        import torch
        try:
            cuda_ok = bool(torch.cuda.is_available())
            gpu = torch.cuda.get_device_name(0) if cuda_ok else ''
        except Exception:
            cuda_ok, gpu = False, ''
        if cuda_ok:
            lines.append(f'   {Y} 正常 ({torch.__version__}，已识别显卡 {gpu})')
        else:
            lines.append(f'   {Y} 已安装 (无可用显卡，将用电脑 CPU 运行，速度较慢)')
    except Exception as e:
        torch_missing = True
        if _pkg_on_disk('torch'):
            lines.append(f'   {N} 已下载但导入失败 ({e}) —— 常见原因: '
                         '①依赖不全, 先在「扩展包下载」装「模型扒谱依赖扩展包」; '
                         '②系统缺少 VC++ 运行库 (安装 Microsoft Visual C++ '
                         '2015-2022 Redistributable 后重启)')
        else:
            lines.append(f'   {N} 本地未安装 —— 转录模型没有它无法运行')
        if br:
            lines.append(f'   {Y} 已检测到系统 Python 可借用 (torch 组件齐全): '
                         f'{br["python"]} —— 模型扒谱将借用其执行, 无需下载')
    lines.append('   安装方法 (便捷版, 推荐): 设置 → 扩展包下载 → '
                 '「CUDA 版本(按显卡选其一)」+「模型扒谱依赖扩展包」, 装完重启程序')
    lines.append('   安装方法 (主版本/命令行, 按显卡选一条):')
    lines.append('   · RTX 20/30/40/50 系显卡:')
    lines.append('       pip install torch --index-url https://download.pytorch.org/whl/cu128')
    lines.append('   · GTX 10/16 系等老显卡:')
    lines.append('       pip install torch --index-url https://download.pytorch.org/whl/cu126')
    lines.append('   · GTX 900 系:')
    lines.append('       pip install torch --index-url https://download.pytorch.org/whl/cu118')
    lines.append('   · 没有 N 卡:')
    lines.append('       pip install torch    (CPU 版，转写较慢，建议搭配小模型)')
    if torch_missing and not br:
        missing.append('②')

    # ③ MuScriptor (多乐器转录组件)
    lines.append('')
    lines.append('③ 多乐器转录组件 (MuScriptor)')
    try:
        import muscriptor                    # noqa: F401
        lines.append(f'   {Y} 已安装')
    except Exception as e:
        lines.append(f'   {N} 未安装 —— 只影响「多乐器路线」模型扒谱')
        lines.extend(_muscriptor_fail_lines(e))
        if 'torch' in str(e) and br:
            lines.append(f'   {Y} 已检测到系统 Python 可借用 —— '
                         '模型扒谱将借用其执行, 无需本地安装')
        if not (br and br.get('muscriptor')):
            missing.append('③')

    # ④ Transkun (钢琴转录组件)
    lines.append('')
    lines.append('④ 钢琴转录组件 (Transkun)')
    try:
        import transkun as _tk
        tk_proj = Path(paths.models_dir()) / 'transkun' / '2.0.pt'
        tk_pkg = Path(_tk.__file__).parent / 'pretrained' / '2.0.pt'
        if tk_proj.is_file():
            lines.append(f'   {Y} 已安装 (权重: 项目内 models/transkun)')
            tk_ok = True
        elif tk_pkg.is_file():
            lines.append(f'   {Y} 已安装 (权重: transkun 包内 pretrained)')
            tk_ok = True
        else:
            raise FileNotFoundError(str(tk_pkg))
    except Exception as e:
        lines.append(f'   {N} 未安装 —— 只影响「钢琴专用路线」模型扒谱')
        lines.append(f'   安装方法: pip install transkun ({e})')
        missing.append('④')

    # ⑤ librosa (多音高分析组件)
    lines.append('')
    lines.append('⑤ 多音高分析组件 (librosa)')
    try:
        import librosa                       # noqa: F401
        lines.append(f'   {Y} 已安装')
    except Exception as e:
        lines.append(f'   {N} 未安装 —— 只影响「多音高分析」功能，'
                     '其他功能不受影响')
        lines.append('   安装方法 (便捷版): 设置 → 扩展包下载 → 「多音高扩展包」，'
                     '装完重启程序')
        lines.append(f'   主版本命令行: pip install librosa ({e})')
        missing.append('⑤')

    # ⑥ FFmpeg (音频解码)
    lines.append('')
    lines.append('⑥ 音频解码组件 (FFmpeg)')
    ffmpeg = shutil.which('ffmpeg')
    if ffmpeg:
        bundled = '_runtime' in ffmpeg.lower()
        lines.append(f'   {Y} 正常{("（" + ffmpeg + "）") if bundled else "（已内置）"}'
                     if bundled else f'   {Y} 正常 ({ffmpeg})')
    else:
        lines.append(f'   {N} 未找到 —— 只影响 mp3/m4a 等压缩音频的读取'
                     '（wav 格式不受影响）')
        lines.append('   安装方法: 下载 FFmpeg 后加入 PATH，或改用 wav 格式音频')
        missing.append('⑥')

    # ⑦ 模型权重文件
    lines.append('')
    lines.append('⑦ 模型权重文件 (muscriptor_small)')
    d2 = _model_dir()
    w = resolve_model_weights()
    if str(w) != 'small':
        lines.append(f'   {Y} 已就绪 ({w})')
    else:
        lines.append(f'   {N} 未找到 (应在 {d2} 文件夹内放置 model.safetensors)')
        lines.append('   获取方法 (便捷版): 设置 → 导入模型压缩包 → '
                     '选择 muscriptor_small 官方 zip (校验哈希后自动安装)')
        lines.append('   获取方法: 到 HuggingFace 下载 muscriptor-small 权重'
                     '（需注册登录并接受许可，仅限非商业使用），'
                     '或从其他电脑复制整个文件夹')
        missing.append('⑦')

    # 本次运行失败原因 + 针对性提示 (模型扒谱失败时自动附上)
    if exc is not None:
        lines.append('')
        lines.append('—— 本次运行失败原因 ——')
        lines.append(str(exc))
        low = str(exc).lower()
        if any(w in low for w in ('no kernel image', 'not compatible',
                                  'sm_', 'cuda capability')):
            lines.append('原因: 你的显卡与当前 AI 框架版本不匹配。'
                         '请按上面②的安装方法，选择与显卡匹配的版本重新安装。')
        elif 'out of memory' in low:
            lines.append('原因: 内存/显存不足。建议改用「小模型」，'
                         '或截短音频后重试。')
        elif any(w in low for w in ('huggingface', 'hf_token', 'gated',
                                    'license', '401', '403')):
            lines.append('原因: 模型权重需要登录 HuggingFace 并接受许可后'
                         '才能下载，详见⑦的获取方法。')
        elif 'sf_wchar_open' in low or 'sndfile' in low:
            lines.append('原因: soundfile 组件缺少自带的 libsndfile (运行时'
                         '撞上了 PATH 里 FluidSynth 的旧版)。'
                         '在「扩展包下载」重装「多音高扩展包」即可补回，'
                         '装完重启程序。')

    # 汇总
    lines.append('')
    if missing:
        names = {'①': 'Python 运行环境', '②': 'AI 运行框架', '③': '多乐器转录组件',
                 '④': '钢琴转录组件', '⑤': '多音高分析组件', '⑥': '音频解码组件',
                 '⑦': '模型权重文件'}
        lines.append('—— 检查结果 ——')
        lines.append('模型扒谱功能暂时无法使用，缺少: ' + '、'.join(missing))
        lines.append('按上面各条的安装方法补齐后，再点一次「模型扒谱」即可。')
        lines.append('软件的编辑 / 播放等其他功能不受影响。')
    else:
        lines.append('—— 检查结果 ——')
        lines.append('全部就绪，可以使用模型扒谱功能。')
    return '\n'.join(lines)


class TranscriptionMode:
    """会话状态: 声组织 + 模型写入统计 (挂在 roll.transcription 上时负责声组织显示)。"""

    def __init__(self, audio_path: str):
        self.audio_path = audio_path
        self.duration_sec = 0.0
        self.tissue = PitchTissue()
        self.progress = (0, 0)
        self.status = ''
        self.version = 0
        self.running = True
        self.tissue_ready = False
        self.draft_ready = False
        self.notes_written = 0

    @property
    def spectrogram(self):
        return self.tissue

    def bump(self):
        self.version += 1

    def draw_tissue(self, p: QPainter, roll):
        self.tissue.draw(p, roll)


class TranscriptionWorker(QThread):
    """MuScriptor 流式推理 → 音符起止事件 (落轨由 Controller 负责)。"""
    started_note = Signal(int, int, float, str, float)  # index, pitch, start_tick, instrument, conf
    ended_note = Signal(int, float)                     # index, end_tick
    progress = Signal(int, int)
    finished_ok = Signal()
    failed = Signal(str)

    def __init__(self, audio_path: str, sec_to_tick: Callable[[float], float],
                 instruments: list[str] | None = None):
        super().__init__()
        self.audio_path = audio_path
        self._sec_to_tick = sec_to_tick
        self._instruments = list(instruments) if instruments else None

    def run(self):
        try:
            from muscriptor.transcription_model import TranscriptionModel
            from muscriptor.events import NoteStartEvent, NoteEndEvent, ProgressEvent
        except ImportError as e:
            self.failed.emit(_env_report(
                ImportError(f'未安装 muscriptor: pip install muscriptor ({e})')))
            return
        try:
            import warnings
            model = TranscriptionModel.load_model(weights_path=resolve_model_weights())
            eos_misses: list[str] = []
            kwargs = {'no_eos_is_ok': True}
            if self._instruments:
                kwargs['instruments'] = self._instruments
            with warnings.catch_warnings(record=True) as caught:
                warnings.simplefilter('always', RuntimeWarning)
                for ev in model.transcribe(self.audio_path, **kwargs):
                    if self.isInterruptionRequested():
                        return
                    if isinstance(ev, ProgressEvent):
                        self.progress.emit(ev.completed, ev.total)
                    elif isinstance(ev, NoteStartEvent):
                        st = self._sec_to_tick(ev.start_time)
                        self.started_note.emit(ev.index, ev.pitch, st, ev.instrument, 1.0)
                    elif isinstance(ev, NoteEndEvent):
                        en = self._sec_to_tick(ev.end_time)
                        self.ended_note.emit(ev.start_event.index, en)
                for w in caught:
                    msg = str(w.message)
                    if 'did not emit EOS' in msg:
                        eos_misses.append(msg)
            if eos_misses:
                print(f'[muscriptor] {len(eos_misses)} chunk(s) hit token cap (notes still written)',
                      flush=True)
            self.finished_ok.emit()
        except Exception as e:
            self.failed.emit(_env_report(e))


class TranskunWorker(QThread):
    """Transkun 流式推理 → 音符事件 (钢琴专用路线, 单轨输出)。
       复刻 transkun CLI 核心: moduleconf 读模型结构 → torch.load 权重 →
       pydub 解码音频 → soxr 重采样 → model.transcribe() → Data.Note 列表 (秒)。
       进度: 模型推理为一次前向, 无分段回调, 以「转写中…」提示。"""
    notes_ready = Signal(list)              # [(pitch, start_tick, end_tick), ...]
    progress = Signal(int, int)
    finished_ok = Signal()
    failed = Signal(str)

    def __init__(self, audio_path: str, sec_to_tick: Callable[[float], float],
                 weight_path: str = '', conf_path: str = ''):
        super().__init__()
        self.audio_path = audio_path
        self._sec_to_tick = sec_to_tick
        self._weight = weight_path or None   # None = transkun 包内置权重
        self._conf = conf_path or None

    def run(self):
        try:
            import moduleconf
            import numpy as np
            import torch
        except ImportError as e:
            self.failed.emit(_env_report(
                ImportError(f'模型扒谱依赖缺失 ({e})'), muscriptor_missing=True))
            return
        try:
            tk_dir = Path(paths.models_dir()) / 'transkun'
            weight = self._weight or os.path.join(str(tk_dir), '2.0.pt')
            conf = self._conf or os.path.join(str(tk_dir), '2.0.conf')
            if not os.path.isfile(weight):
                import transkun
                import pkg_resources
                weight = pkg_resources.resource_filename(
                    'transkun', 'pretrained/2.0.pt')
            if not os.path.isfile(conf):
                import pkg_resources
                conf = pkg_resources.resource_filename(
                    'transkun', 'pretrained/2.0.conf')

            self.progress.emit(0, 1)
            confManager = moduleconf.parseFromFile(conf)
            TransKun = confManager['Model'].module.TransKun
            conf = confManager['Model'].config

            device = 'cuda' if torch.cuda.is_available() else 'cpu'
            checkpoint = torch.load(weight, map_location=device)
            model = TransKun(conf=conf).to(device)
            sd = checkpoint.get('best_state_dict') or checkpoint.get('state_dict')
            model.load_state_dict(sd, strict=False)
            model.eval()
            torch.set_grad_enabled(False)

            # 音频解码: pydub (走 FFmpeg, 支持 mp3/aac/wav 全格式) → float32
            import pydub
            audio_seg = pydub.AudioSegment.from_file(self.audio_path)
            y = np.array(audio_seg.get_array_of_samples()).reshape(
                -1, audio_seg.channels)
            y = np.float32(y) / 2 ** 15
            fs = audio_seg.frame_rate

            if fs != model.fs:
                import soxr
                y = soxr.resample(y, fs, model.fs)

            x = torch.from_numpy(y).to(device)
            notes = model.transcribe(x)

            # 负 pitch = CC 踏板事件 (延音), 简化处理: 只保留 pitch>0 的音符
            out = []
            for n in notes:
                if n.pitch > 0:
                    st = int(self._sec_to_tick(max(0.0, n.start)))
                    en = int(self._sec_to_tick(max(0.0, n.end)))
                    if en > st:
                        out.append((n.pitch, st, en))

            self.notes_ready.emit(out)
            self.finished_ok.emit()
        except Exception as e:
            self.failed.emit(_env_report(e))


class _BridgeBase(QThread):
    """系统 Python 子进程桥接公共件 (桥接轮): 命令构建 + 流式读取 + 中止"""

    def __init__(self, bridge: dict):
        super().__init__()
        self._py = bridge['python']
        self._proc: subprocess.Popen | None = None
        self._abort = False

    def stop(self):
        self._abort = True
        if self._proc is not None and self._proc.poll() is None:
            try:
                self._proc.kill()
            except Exception:
                pass

    @staticmethod
    def _popen(cmd):
        return subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding='utf-8', errors='replace',
            creationflags=0x08000000)          # CREATE_NO_WINDOW

    def _fail_msg(self, returncode, err_tail):
        tail = (err_tail or '').strip().splitlines()[-5:]
        return ('系统 Python 执行失败 (exit %s):\n%s'
                % (returncode, '\n'.join(tail) if tail else '无输出'))


class BridgeMuscriptorWorker(_BridgeBase):
    """MuScriptor 桥接: 系统 Python 跑 muscriptor CLI (jsonl 流式, 秒单位),
       事件逐行解析 → 复用 TranscriptionWorker 同款信号 (落轨由 Controller 负责)。"""

    started_note = Signal(int, int, float, str, float)  # index, pitch, start_tick, instrument, conf
    ended_note = Signal(int, float)                     # index, end_tick
    progress = Signal(int, int)
    finished_ok = Signal()
    failed = Signal(str)

    def __init__(self, bridge: dict, audio_path: str,
                 sec_to_tick: Callable[[float], float],
                 instruments: list[str] | None = None,
                 weights_path: str | None = None):
        super().__init__(bridge)
        self.audio_path = audio_path
        self._sec_to_tick = sec_to_tick
        self._instruments = list(instruments) if instruments else None
        self._weights = weights_path

    def run(self):
        try:
            cmd = [self._py, '-m', 'muscriptor', 'transcribe',
                   self.audio_path, '-f', 'jsonl', '-o', '-',
                   '--device', 'auto', '--detect-tempo', 'false']
            if self._weights:
                cmd += ['-m', self._weights]
            if self._instruments:
                cmd += ['--instruments', ','.join(self._instruments)]
            proc = self._proc = self._popen(cmd)
            err_tail = []

            import threading

            def _drain():                      # stderr 并行排空 (防管道死锁)
                try:
                    for line in proc.stderr:
                        err_tail.append(line.rstrip())
                except Exception:
                    pass

            threading.Thread(target=_drain, daemon=True).start()
            starts = set()
            for line in proc.stdout:
                if self._abort:
                    break
                line = line.strip()
                if not line.startswith('{'):
                    continue
                try:
                    ev = json.loads(line)
                except ValueError:
                    continue
                t = ev.get('type')
                if t == 'start':
                    starts.add(ev.get('index'))
                    self.started_note.emit(
                        int(ev.get('index', 0)), int(ev.get('pitch', 0)),
                        self._sec_to_tick(max(0.0, float(ev.get('start_time', 0)))),
                        str(ev.get('instrument') or '未知'), 1.0)
                elif t == 'end':
                    self.ended_note.emit(
                        int(ev.get('start_event_index', -1)),
                        self._sec_to_tick(max(0.0, float(ev.get('end_time', 0)))))
                elif t == 'progress':
                    self.progress.emit(int(ev.get('done', 0)),
                                       int(ev.get('total', 0)))
            rc = proc.wait()
            if self._abort:
                return
            if rc != 0:
                self.failed.emit(self._fail_msg(rc, ''.join(err_tail[-20:])))
                return
            self.finished_ok.emit()
        except Exception as e:
            self.failed.emit(_env_report(e))


class BridgeTranskunWorker(_BridgeBase):
    """Transkun 桥接: 系统 Python 跑 transkun CLI (MIDI 输出) →
       mido 解析 (tempo 换算秒 → 我们的 tick) → notes_ready 单轨载荷。"""

    notes_ready = Signal(list)                     # [(pitch, start_tick, end_tick), ...]
    progress = Signal(int, int)
    finished_ok = Signal()
    failed = Signal(str)

    def __init__(self, bridge: dict, audio_path: str,
                 sec_to_tick: Callable[[float], float],
                 weight_path: str | None = None,
                 conf_path: str | None = None):
        super().__init__(bridge)
        self.audio_path = audio_path
        self._sec_to_tick = sec_to_tick
        self._weight = weight_path
        self._conf = conf_path

    def run(self):
        import mido
        import tempfile
        out_mid = None
        try:
            fd, out_mid = tempfile.mkstemp(suffix='.mid')
            os.close(fd)
            dev = 'cuda' if sys_bridge.cuda_ok(self._py) else 'cpu'
            cmd = [self._py, '-c',
                   'from transkun.transcribe import main; main()',
                   self.audio_path, out_mid, '--device', dev]
            if self._weight:
                cmd += ['--weight', self._weight]
            if self._conf:
                cmd += ['--conf', self._conf]
            proc = self._proc = self._popen(cmd)
            err_tail = []

            import threading

            def _drain():
                try:
                    for line in proc.stderr:
                        err_tail.append(line.rstrip())
                except Exception:
                    pass

            threading.Thread(target=_drain, daemon=True).start()
            rc = proc.wait()
            if self._abort:
                return
            if rc != 0:
                self.failed.emit(self._fail_msg(rc, ''.join(err_tail[-20:])))
                return
            mid = mido.MidiFile(out_mid)
            tpb = mid.ticks_per_beat or 480
            # 事件: 按轨道累计 tick + tempo 变化 → 秒
            notes = []
            for tr in mid.tracks:
                abs_tick = 0
                tempo = 500000                       # µs/拍 (默认 120BPM)
                active = {}                          # (ch, note) → start_tick
                for msg in tr:
                    abs_tick += msg.time
                    if msg.type == 'set_tempo':
                        tempo = msg.tempo
                    elif msg.type == 'note_on' and msg.velocity > 0:
                        active[(msg.channel, msg.note)] = abs_tick
                    elif msg.type in ('note_off',) or \
                            (msg.type == 'note_on' and msg.velocity == 0):
                        k = (msg.channel, msg.note)
                        st = active.pop(k, None)
                        if st is None:
                            continue
                        st_s = mido.tick2second(st, tpb, tempo)
                        en_s = mido.tick2second(abs_tick, tpb, tempo)
                        st_t = int(self._sec_to_tick(max(0.0, st_s)))
                        en_t = int(self._sec_to_tick(max(0.0, en_s)))
                        if en_t > st_t:
                            notes.append((msg.note, st_t, en_t))
            self.notes_ready.emit(notes)
            self.finished_ok.emit()
        except Exception as e:
            self.failed.emit(_env_report(e))
        finally:
            if out_mid and os.path.exists(out_mid):
                try:
                    os.remove(out_mid)
                except OSError:
                    pass


class TranscriptionController(QObject):
    """编排: 多音高分析与 MuScriptor 模型扒谱 可独立启停。"""

    tissue_changed = Signal()
    tissue_complete = Signal(int)          # event count
    transcription_complete = Signal()
    progress = Signal(int, int, str)
    tissue_failed = Signal(str)
    model_failed = Signal(str)
    mode_exited = Signal()
    spectrogram_ready = Signal()
    running_changed = Signal()

    def __init__(self, mw):
        super().__init__()
        self.mw = mw
        self.mode: TranscriptionMode | None = None
        self._tx_worker: TranscriptionWorker | None = None
        self._tk_worker: TranskunWorker | None = None
        self._tissue_worker: MultipitchTissueWorker | None = None
        self._workers = {}
        self._open: dict[int, Note] = {}
        self._inst_tid: dict[str, int] = {}
        self._pushed = False
        self._refresh_pending = False
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(80)
        self._refresh_timer.timeout.connect(self._flush_refresh)

    @property
    def active(self) -> bool:
        return self.mode is not None

    @property
    def tissue_running(self) -> bool:
        w = self._tissue_worker
        return w is not None and w.isRunning()

    @property
    def model_running(self) -> bool:
        return any(w is not None and w.isRunning()
                   for w in (self._tx_worker, self._tk_worker))

    def start_multipitch(self, audio_path: str):
        """仅多音高分析 → 声组织 (Tonteppich)。"""
        if self.tissue_running or not self._prepare_session(audio_path):
            return False
        self._cancel_tissue()
        roll = self.mw.edit_roll
        self.mode.tissue.clear()
        self.mode.tissue_ready = False
        self.mode.bump()
        roll.transcription = self.mode
        self._invalidate_tiles()
        roll.update()

        self._tissue_worker = MultipitchTissueWorker(audio_path)
        self._watch_worker(self._tissue_worker, '_tissue_worker', [
            ('progress', self._on_tissue_progress),
            ('finished_events', self._on_tissue_events),
            ('failed', self._on_tissue_fail),
        ])
        self._tissue_worker.start()
        self.running_changed.emit()
        self.progress.emit(0, 0, '多音高分析中…')

    def start_model(self, audio_path: str, instruments: list[str] | None = None):
        """仅 MuScriptor 模型扒谱 → 建轨写音符。
           (桥接轮) 本地无 torch 但系统 Python 可借用 → 走子进程桥接。"""
        if self.model_running or not self._prepare_session(audio_path):
            return False
        self._cancel_model()
        self._pushed = False
        inst = list(instruments) if instruments else None
        sec_fn = self.mw.tmap.sec2tick

        if not _local_torch():
            br = _bridge()
            if br and br.get('muscriptor'):
                w = resolve_model_weights()
                weights = None if str(w) == 'small' else str(w)
                self._tx_worker = BridgeMuscriptorWorker(
                    br, audio_path, sec_fn, instruments=inst,
                    weights_path=weights)
                self._watch_worker(self._tx_worker, '_tx_worker', [
                    ('started_note', self._on_start),
                    ('ended_note', self._on_end),
                    ('progress', self._on_progress),
                    ('finished_ok', self._on_tx_done),
                    ('failed', self._on_fail),
                ])
                self._tx_worker.start()
                self.running_changed.emit()
                self.progress.emit(0, 0,
                                   '借用系统 Python 环境转写中… (MuScriptor)')
                return

        self._tx_worker = TranscriptionWorker(audio_path, sec_fn, instruments=inst)
        self._watch_worker(self._tx_worker, '_tx_worker', [
            ('started_note', self._on_start),
            ('ended_note', self._on_end),
            ('progress', self._on_progress),
            ('finished_ok', self._on_tx_done),
            ('failed', self._on_fail),
        ])
        self._tx_worker.start()
        self.running_changed.emit()
        if inst:
            self.progress.emit(0, 0, f'模型扒谱中… 乐器×{len(inst)}')
        else:
            self.progress.emit(0, 0, '模型扒谱中… 自动检测乐器')

    def start_transkun(self, audio_path: str):
        """钢琴专用路线 → Transkun 转写 → 单轨写入。
           (桥接轮) 本地无 torch 但系统 Python 可借用 → 走子进程桥接。"""
        if self.model_running or not self._prepare_session(audio_path):
            return False
        self._pushed = False
        sec_fn = self.mw.tmap.sec2tick
        if not _local_torch():
            br = _bridge()
            if br and br.get('transkun'):
                w_p = os.path.join(str(paths.models_dir()), 'transkun', '2.0.pt')
                c_p = os.path.join(str(paths.models_dir()), 'transkun', '2.0.conf')
                self._tk_worker = BridgeTranskunWorker(
                    br, audio_path, sec_fn,
                    weight_path=w_p if os.path.isfile(w_p) else None,
                    conf_path=c_p if os.path.isfile(c_p) else None)
                self._watch_worker(self._tk_worker, '_tk_worker', [
                    ('notes_ready', self._on_transkun_notes),
                    ('progress', self._on_progress),
                    ('finished_ok', self._on_tx_done),
                    ('failed', self._on_fail),
                ])
                self._tk_worker.start()
                self.running_changed.emit()
                self.progress.emit(0, 0, '借用系统 Python 环境转写中… (Transkun)')
                return
        self._tk_worker = TranskunWorker(audio_path, sec_fn)
        self._watch_worker(self._tk_worker, '_tk_worker', [
            ('notes_ready', self._on_transkun_notes),
            ('progress', self._on_progress),
            ('finished_ok', self._on_tx_done),
            ('failed', self._on_fail),
        ])
        self._tk_worker.start()
        self.running_changed.emit()
        self.progress.emit(0, 0, '钢琴专用路线转写中…')

    def _on_transkun_notes(self, events):
        """Transkun 转写完成 → 单轨「钢琴」写入音符。"""
        if self.mode is None or self.mw.edit_roll is None:
            return
        mw = self.mw
        tid = self._tid_for_instrument('钢琴')
        self._ensure_pushed()
        notes = []
        for pitch, st, en in events:
            notes.append(Note(int(pitch), 80, int(st), int(en), 0.0, 0.0, tid=tid))
        if notes:
            mw.model.append_notes(notes)
        if self.mode:
            self.mode.notes_written = len(notes)
            self.mode.bump()
        self._schedule_refresh()

    def _prepare_session(self, audio_path: str) -> bool:
        mw = self.mw
        roll = mw.edit_roll
        if roll is None:
            self.model_failed.emit('请先打开编辑器')
            return False
        ap = os.path.abspath(audio_path)
        if self.mode is not None and os.path.abspath(self.mode.audio_path) != ap:
            if self.model_running or self.tissue_running:
                return False
            self.exit_mode(keep_notes=True)
        if self.mode is None:
            self.mode = TranscriptionMode(audio_path)
            self._inst_tid.clear()
            self._pushed = False
        self._ensure_timebase(audio_path)
        return True

    def _watch_worker(self, worker, field, bindings):
        callbacks = []
        for signal, slot in bindings:
            def guarded(*args, callback=slot, owner=worker, name=field):
                if getattr(self, name) is owner:
                    callback(*args)
            getattr(worker, signal).connect(guarded)
            callbacks.append((signal, guarded))
        self._workers[worker] = callbacks
        worker.finished.connect(lambda: self._release_worker(worker, field))

    def _release_worker(self, worker, field):
        self._workers.pop(worker, None)
        if getattr(self, field) is worker:
            setattr(self, field, None)
        worker.deleteLater()
        self.running_changed.emit()

    def _cancel_worker(self, field):
        worker = getattr(self, field)
        setattr(self, field, None)
        if worker is not None:
            for signal, callback in self._workers.get(worker, []):
                getattr(worker, signal).disconnect(callback)
            worker.requestInterruption()
            if hasattr(worker, 'stop'):
                worker.stop()
            worker.quit()
        self.running_changed.emit()

    def _cancel_tissue(self):
        self._cancel_worker('_tissue_worker')

    def _cancel_model(self):
        self._cancel_worker('_tx_worker')
        self._cancel_worker('_tk_worker')
        self._open.clear()

    def cancel(self):
        self._refresh_timer.stop()
        self._cancel_tissue()
        self._cancel_model()

    def shutdown(self):
        self.cancel()
        for worker in list(self._workers):
            worker.requestInterruption()
            if hasattr(worker, 'stop'):
                worker.stop()
            worker.quit()
            worker.wait(1000)
        return not any(worker.isRunning() for worker in self._workers)

    def exit_mode(self, *, keep_notes: bool = True):
        self.cancel()
        roll = self.mw.edit_roll
        if roll is not None:
            roll.transcription = None
            roll.tiles.clear()
            roll._bgV_key = None
            roll.update()
        self.mode = None
        self.mode_exited.emit()

    def _ensure_timebase(self, audio_path: str):
        mw = self.mw
        try:
            import librosa
            dur = float(librosa.get_duration(path=audio_path))
        except Exception:
            dur = 60.0
        self.mode.duration_sec = dur
        if mw.tmap is None:
            tpb = 480
            bpm = 120.0
            mw.tmap = TempoMap(tpb, [(0, int(60e6 / bpm))])
            mw.bar_ticks = float(4 * tpb)
        end_tick = float(mw.tmap.sec2tick(dur))
        disp = float(getattr(mw, 'total_tick_display', 1920.0) or 1920.0)
        mw.total_tick_display = max(disp, end_tick)
        mw.total_sec = max(float(getattr(mw, 'total_sec', 0) or 0), dur)
        if mw.edit_roll is not None:
            roll = mw.edit_roll
            roll.set_data(mw.tmap, mw.raw_notes, mw.bar_ticks, keep_view=True)
            roll.refresh_content_span()
            mm = getattr(mw, 'edit_minimap', None)
            if mm is not None:
                mm.update()

    def _ensure_pushed(self):
        if self._pushed:
            return
        mw = self.mw
        if getattr(mw, 'edit_session', None) is not None and hasattr(mw, 'model'):
            mw.model.push()
            self._pushed = True

    def _tid_for_instrument(self, instrument: str) -> int:
        mw = self.mw
        name = (instrument or '').strip() or tr_fallback_track(mw)
        if name in self._inst_tid:
            return self._inst_tid[name]
        if not getattr(mw, 'tracks', None):
            mw.tracks = []
        for t in mw.tracks:
            if t.name and t.name == name:
                self._inst_tid[name] = t.tid
                return t.tid
            if t.name and name.lower() in t.name.lower():
                self._inst_tid[name] = t.tid
                return t.tid
        tid = max((t.tid for t in mw.tracks), default=-1) + 1
        mw.tracks.append(Track(tid, name))
        self._inst_tid[name] = tid
        if hasattr(mw, '_sync_track_ui'):
            mw._sync_track_ui()
        return tid

    def _on_tissue_progress(self, done, total):
        self.progress.emit(done, total, f'多音高分析 {done}/{total}')

    def _on_tissue_events(self, events):
        if self.mode is None:
            return
        sec_fn = lambda s: float(self.mw.tmap.sec2tick(s))
        self.mode.tissue.load_raw_events(events, sec_fn)
        self.mode.tissue_ready = True
        self.mode.bump()
        self.tissue_changed.emit()
        self.spectrogram_ready.emit()
        roll = self.mw.edit_roll
        if roll is not None:
            roll.transcription = self.mode
            if hasattr(roll, 'tiles'):
                if hasattr(roll.tiles, 'clear_tissue'):
                    roll.tiles.clear_tissue()
                roll.tiles.clear()
        mw = self.mw
        if self.mode.tissue.blobs:
            span = max(b.end_tick for b in self.mode.tissue.blobs)
            mw.total_tick_display = max(
                float(getattr(mw, 'total_tick_display', 0) or 0), float(span))
        if roll is not None:
            roll.refresh_content_span()
            mm = getattr(mw, 'edit_minimap', None)
            if mm is not None:
                mm.update()
        self._schedule_refresh()
        n = len(events)
        self.progress.emit(0, 0, f'声组织就绪 · {n} 条')
        self.tissue_complete.emit(n)
        self._tissue_worker = None

    def _on_tissue_fail(self, msg: str):
        self._tissue_worker = None
        self.progress.emit(0, 0, f'多音高分析失败: {msg}')
        self.tissue_failed.emit(msg)

    def _on_start(self, index, pitch, start_tick, instrument, conf):
        if self.mode is None:
            return
        mw = self.mw
        tid = self._tid_for_instrument(instrument)
        st = int(start_tick)
        tpb = int(mw.tmap.tpb) if mw.tmap else 480
        note = Note(int(pitch), 80, st, st + max(1, tpb // 4), 0.0, 0.0, tid=tid)
        self._ensure_pushed()
        mw.model.append_notes([note])
        self._open[index] = note
        self.mode.notes_written += 1
        self.mode.bump()
        self._schedule_refresh()

    def _on_end(self, index, end_tick):
        if self.mode is None:
            return
        note = self._open.pop(index, None)
        if note is None:
            return
        note.end_tick = max(note.start_tick + 1, int(end_tick))
        self.mw.model.finish()
        self.mode.bump()
        self._schedule_refresh()

    def _on_progress(self, done, total):
        if self.mode:
            self.mode.progress = (done, total)
        n = self.mode.notes_written if self.mode else 0
        self.progress.emit(done, total, f'模型写入 {n} · {done}/{total}')

    def _on_tx_done(self):
        mw = self.mw
        self._open.clear()
        if self.mode:
            self.mode.draft_ready = True
            self.mode.running = False
            self.mode.status = '完成'
            self.mode.bump()
        if self._pushed:
            mw.model.finish()
        self._flush_refresh()
        if hasattr(mw, '_editor_commit'):
            mw._editor_commit()
        n = self.mode.notes_written if self.mode else 0
        self.progress.emit(0, 0, f'模型扒谱完成 · 已写入 {n} 个音符')
        self._tx_worker = None
        self._tk_worker = None
        self.running_changed.emit()
        self.transcription_complete.emit()

    def _on_fail(self, msg: str):
        self._tx_worker = None
        self._tk_worker = None
        self.running_changed.emit()
        self._open.clear()
        self.model_failed.emit(msg)

    def _invalidate_tiles(self):
        roll = self.mw.edit_roll
        if roll is None:
            return
        roll.tiles.clear()
        roll._bgV_key = None

    def _schedule_refresh(self):
        self._refresh_pending = True
        if not self._refresh_timer.isActive():
            self._refresh_timer.start()

    def _flush_refresh(self):
        if not self._refresh_pending:
            return
        self._refresh_pending = False
        roll = self.mw.edit_roll
        if roll is None:
            return
        if hasattr(roll.tiles, 'clear_canvas'):
            roll.tiles.clear_canvas()
        else:
            roll.tiles.clear()
        if hasattr(roll, '_data_ver'):
            roll._data_ver += 1
        roll.request_update()


def tr_fallback_track(mw) -> str:
    try:
        from i18n import tr
        return tr('轨道 1')
    except Exception:
        return 'Track 1'
