# -*- coding: utf-8 -*-
"""SF2 音源: pyfluidsynth 加载(不可用则纯视觉+纯键盘) 与 发声封装
   支持用户选择音频驱动与系统播放设备(设置弹窗), 支持音源静音(不影响键盘输出)。"""
import os
from common import IS_WIN
from i18n import t
_fs_error = ""
fluidsynth = None
def _load_fs_module():
    global fluidsynth, _fs_error
    if IS_WIN:
        here = os.path.dirname(os.path.abspath(__file__))
        env = os.environ.get('FLUIDSYNTH_HOME')
        cands = [here, os.path.join(here, 'fluidsynth', 'bin'),
                 os.path.join(here, 'fluidsynth'), os.getcwd()]
        if env: cands += [env, os.path.join(env, 'bin')]
        for d in cands:
            try:
                if d and os.path.isdir(d) and any(
                        f.lower().startswith('fluidsynth') and f.lower().endswith('.dll')
                        for f in os.listdir(d)):
                    try: os.add_dll_directory(d)
                    except Exception: pass
                    os.environ['PATH'] = d + os.pathsep + os.environ.get('PATH', '')
                    break
            except Exception:
                continue
    try:
        import fluidsynth as _fs
        fluidsynth = _fs
    except Exception as e:
        _fs_error = str(e)
_load_fs_module()


class _mute_fluidsynth_stderr:
    """压制 fluidsynth C 层控制台噪音 (SDL3 / 无 MIDI-in)。Windows 上常打到 stdout。"""
    def __enter__(self):
        self._devnull = open(os.devnull, 'w')
        self._olds = []
        for fd in (1, 2):
            try:
                old = os.dup(fd)
                os.dup2(self._devnull.fileno(), fd)
                self._olds.append((fd, old))
            except Exception:
                pass
        return self

    def __exit__(self, *exc):
        for fd, old in reversed(self._olds):
            try:
                os.dup2(old, fd)
                os.close(old)
            except Exception:
                pass
        try:
            self._devnull.close()
        except Exception:
            pass
        return False


def enumerate_audio_devices(driver):
    """枚举某驱动的系统播放设备名; 未选驱动/缺绑定/枚举失败返回 [] (调用方回退 Qt 枚举)。
       优先 fluidsynth settings 选项表, 空则回退 Qt Multimedia 的系统输出设备名。"""
    if not driver:
        return []
    if fluidsynth is None:
        return _qt_audio_devices()
    out = []
    try:
        if hasattr(fluidsynth, 'new_fluid_settings'):
            s = fluidsynth.new_fluid_settings()
            try:
                fluidsynth.fluid_settings_setstr(s, b'audio.driver', driver.encode())
                if hasattr(fluidsynth, 'fluid_settings_foreach_option'):
                    key = f'audio.{driver}.device'.encode()
                    fluidsynth.fluid_settings_foreach_option(
                        s, key, None,
                        lambda _data, name: out.append(
                            name.decode(errors='replace') if isinstance(name, bytes)
                            else str(name)))
            finally:
                try: fluidsynth.delete_fluid_settings(s)
                except Exception: pass
    except Exception:
        out = []
    return out or _qt_audio_devices()
def _qt_audio_devices():
    """系统音频输出设备名 (Qt Multimedia); 模块不可用返回 []"""
    try:
        from PySide6.QtMultimedia import QMediaDevices
        return [d.description() for d in QMediaDevices.audioOutputs()]
    except Exception:
        return []
class SoundEngine:
    DRIVERS_WIN = ('dsound', 'wasapi', 'waveout', 'portaudio')
    DRIVERS_OTHER = ('pulseaudio', 'alsa', 'coreaudio', 'jack', 'portaudio')
    def __init__(self):
        self.fs = None                      # Synth (首次加载轨道音源时惰性启动)
        self.muted = False                  # 音源静音门 (键盘输出不经过这里, 不受影响)
        self.audio_driver = ''              # '' = 自动; 见 设置弹窗
        self.audio_device = ''              # '' = 系统默认
        # ---- (O 轮) 发声只走每轨独立 SF2: 单合成器多音色库 + 通道分配 ----
        self.track_channels = {}            # tid -> 通道 (1..15 跳过9; 鼓轨=9); 播放线程持同一引用
        self.track_fonts = {}               # tid -> dict(path, sfid, preset, gain)
        self._font_cache = {}               # abspath -> sfid (同一 SF2 多轨复用, 不重复加载)
        self._ch_gain = {}                  # ch -> 响度倍率 (1.0..8.0), noteon 时缩放力度
        self.master_gain = 1.0              # 音源音量 (全局比例 0..8, 与轨增益相乘)
    def _alloc_channel(self, tid):
        """给轨道分配合成器通道: 复用已有; 否则取最小空闲 (1..15 跳过 9); 满则回退 -1(静默)"""
        if tid in self.track_channels: return self.track_channels[tid]
        used = set(self.track_channels.values())
        for c in range(1, 16):
            if c == 9 or c in used: continue
            return c
        return -1
    def load_track_font(self, tid, path, preset=0, is_drum=False, gain=1.0):
        """为轨道加载独立 SF2 并分配通道 (鼓轨优先通道 9 + bank 128); 返回通道号
           sfload 的 update_midi_preset 必须为 0 —— 传 1 会把全部通道程序重置为
           新音源, 已分配轨道的声音被冲掉 (此前"仍播主界面音源"的根因);
           未分配音源的通道无程序, noteon 静默
           gain: 响度倍率 1.0~8.0 (100%~800%), 在 noteon 时缩放力度"""
        if fluidsynth is None:
            raise RuntimeError(t('pyfluidsynth 不可用: {e}', e=_fs_error or t('未安装')))
        if self.fs is None: self._start_audio()
        ap = os.path.abspath(path)
        sfid = self._font_cache.get(ap)
        if sfid is None:
            sfid = self.fs.sfload(ap, 0)
            if not isinstance(sfid, int) or sfid < 0:
                raise RuntimeError(t('SF2 加载失败(文件损坏或不是有效 SoundFont)'))
            self._font_cache[ap] = sfid
        old = self.track_channels.get(tid)          # 换音源前清掉旧通道上正在响的音
        if old is not None and old >= 0:
            for n in range(128):
                try: self.fs.noteoff(old, n)
                except Exception: pass
            self._ch_gain.pop(old, None)
        if is_drum and 9 not in self.track_channels.values():
            ch, bank = 9, 128
        else:
            ch, bank = self._alloc_channel(tid), 0
        if ch < 0:                                  # 通道耗尽: 该轨静默
            self.track_fonts.pop(tid, None)
            return -1
        g = max(1.0, min(8.0, float(gain)))
        self.track_channels[tid] = ch
        self.track_fonts[tid] = {
            'path': ap, 'sfid': sfid, 'preset': int(preset), 'gain': g}
        self._ch_gain[ch] = g
        try: self.fs.program_select(ch, sfid, bank, int(preset))
        except Exception: pass
        return ch
    def clear_track_font(self, tid):
        """取消轨道独立音源 (通道释放, 该轨静默)"""
        ch = self.track_channels.pop(tid, None)
        if ch is not None and ch >= 0 and self.fs is not None:
            for n in range(128):
                try: self.fs.noteoff(ch, n)
                except Exception: pass
            self._ch_gain.pop(ch, None)
        self.track_fonts.pop(tid, None)
    def clear_track_fonts(self):
        for tid in list(self.track_channels): self.clear_track_font(tid)
    def set_track_preset(self, tid, preset):
        info = self.track_fonts.get(tid)
        if info is not None:
            info['preset'] = int(preset)
            try: self.fs.program_select(self.track_channels[tid],
                                        info['sfid'], 0, int(preset))
            except Exception: pass
    def set_track_gain(self, tid, gain):
        """设置已加载轨的响度倍率 (1.0~8.0); 未加载则忽略"""
        info = self.track_fonts.get(tid)
        if info is None:
            return
        g = max(1.0, min(8.0, float(gain)))
        info['gain'] = g
        ch = self.track_channels.get(tid)
        if ch is not None:
            self._ch_gain[ch] = g
    def _set_device(self, fs, drv):
        """驱动与用户所选设备一致时, 启动前注入 audio.<drv>.device 设置"""
        dev = self.audio_device
        if not dev or drv != self.audio_driver: return
        try:
            fluidsynth.fluid_settings_setstr(
                fs.settings, f'audio.{drv}.device'.encode(), dev.encode())
        except Exception:
            pass
    def _start_audio(self):
        drivers = self.DRIVERS_WIN if IS_WIN else self.DRIVERS_OTHER
        env = os.environ.get('FLUID_AUDIO_DRIVER')
        if env: drivers = (env,) + tuple(drivers)
        if self.audio_driver:               # 用户指定驱动优先, 失败仍回退自动
            drivers = ((self.audio_driver,)
                       + tuple(d for d in drivers if d != self.audio_driver))
        # 跳过 sdl3: 未 SDL_Init 时 fluidsynth 会刷屏警告, 且我们只用系统音频驱动
        drivers = tuple(d for d in drivers if d != 'sdl3')
        for drv in drivers:
            try:
                with _mute_fluidsynth_stderr():
                    fs = fluidsynth.Synth()
                    self._set_device(fs, drv)
                    self._start_audio_only(fs, drv)
                self.fs = fs; return
            except Exception:
                continue
        raise RuntimeError(t('FluidSynth 音频驱动启动失败(可设 FLUID_AUDIO_DRIVER 指定如 dsound)'))

    @staticmethod
    def _start_audio_only(fs, drv: str):
        """只启音频输出, 不建 MIDI-in 驱动。

        pyfluidsynth.Synth.start() 默认会 new_fluid_midi_driver; 无硬件 MIDI
        输入时刷屏 `not enough MIDI in devices` / `Device default does not exists`。
        本应用只走 noteon/noteoff API, 不需要 MIDI 输入口。
        """
        fs.setting('audio.driver', drv)
        try:
            from fluidsynth import new_fluid_audio_driver
        except ImportError:
            fs.start(driver=drv)
            return
        fs.audio_driver = new_fluid_audio_driver(fs.settings, fs.synth)
        fs.midi_driver = None
        fs.router = None
        fs.custom_router_callback = None
    def noteon(self, note, vel, ch=0):
        """发声 (未配音源的通道无程序, 天然静默; 静音门开启时不发声;
           通道增益按倍率缩放力度, 上限 127)"""
        if self.fs is not None and not self.muted:
            g = self._ch_gain.get(ch, 1.0) * self.master_gain
            v = int(min(127, max(0, round(int(vel) * g))))
            if v <= 0:
                return
            try: self.fs.noteon(ch, note, v)
            except Exception: pass
    def noteoff(self, note, ch=0):
        if self.fs is not None:
            try: self.fs.noteoff(ch, note)
            except Exception: pass
    def set_muted(self, m):
        """静音开关: 开启时清掉所有已用通道上正在响的音"""
        self.muted = bool(m)
        if self.muted and self.fs is not None:
            for ch in [0] + list(self.track_channels.values()):
                for n in range(128):
                    try: self.fs.noteoff(ch, n)
                    except Exception: pass
