# -*- coding: utf-8 -*-
"""扩展包下载器 (PyPI 镜像版):
   ExtensionDownloaderDialog  树形列表 (多音高扩展包 / 模型扒谱依赖扩展包 /
                              CUDA 版本按显卡细分) + 逐行下载按钮 + 勾选批量
                              + 底部蓝色下载/安装进度条
   下载: 清华 PyPI 镜像 simple 索引逐包解析最优 wheel (cp310-win_amd64 优先,
         钉版本, 缺失回退最新) 流式下载到 _downloads/*.part;
         CUDA 行为阿里云 pytorch-wheels 镜像 torch+torchaudio 成对直链。
   安装: 全部解压到项目 _vendor (wheel 的 *.data 目录重映射, 防越界) ——
         便携版 ._pth 与开发机 sys.path 均含 _vendor, 且无需管理员权限。
   清单: 两扩展包 = 本机可运行环境 dist-info/METADATA 递归闭包, 钉精确版本;
         torch 本体与 numpy/mido (程序/CUDA 行提供) 不在内。"""
import os
import re
import shutil
import time
import urllib.error
import urllib.request
import zipfile
from urllib.parse import quote, urljoin, urlsplit

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel,
                               QPushButton, QProgressBar, QTreeWidget,
                               QTreeWidgetItem, QMessageBox, QStyle,
                               QStyleOptionViewItem)

from i18n import t
import paths

APP_ROOT = paths.APP_ROOT                     # 模块全局, 测试可覆写
DL_DIR = paths.downloads_dir()
VENDOR_DIR = paths.vendor_dir()
# PyPI 镜像回退链: 任一镜像 403/429/超时/缺包/过慢 → 切下一个 (索引与文件同源重解析)
# 顺序依据 2026-09 实测 (numpy 2.2.6 wheel 8MB 分段): 上交 2.4MB/s /
# 阿里云 0.24MB/s / 清华 403 限流 —— 上交对象存储最快, 清华拥堵限流高发
MIRRORS = ('https://mirror.sjtu.edu.cn/pypi/web/simple/',
           'https://mirrors.aliyun.com/pypi/simple/',
           'https://pypi.tuna.tsinghua.edu.cn/simple/')
_M = 'https://mirror.sjtu.edu.cn/pytorch-wheels'               # CUDA 主源 (实测 2.5~6.8 MB/s)
_M_ALT = 'https://mirrors.aliyun.com/pytorch-wheels'           # 备用 (实测仅 ~0.2 MB/s)
# 完整浏览器 UA: 简短自定义 UA 会被镜像 CDN 的反爬规则命中 (403)
_UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
       '(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36')


def _norm(name):
    """PEP 503 包名归一"""
    return re.sub(r'[-_.]+', '-', name).lower()


# ---------------------------------------------------------------- 清单 ----
# 多音高扩展包 = _vendor 实际内容 (librosa 链 26 包, 钉版)
_MULTIPITCH = (
    ('librosa', '0.11.0'), ('numba', '0.67.0'), ('llvmlite', '0.49.0'),
    ('scipy', '1.15.3'), ('scikit-learn', '1.7.2'), ('numpy', '2.2.6'),
    ('joblib', '1.6.0'), ('cloudpickle', '3.1.2'), ('soundfile', '0.14.0'),
    ('cffi', '2.1.1'), ('pycparser', '3.0'), ('soxr', '1.1.0'),
    ('audioread', '3.1.0'), ('pooch', '1.9.0'), ('requests', '2.34.2'),
    ('urllib3', '2.7.0'), ('certifi', '2026.7.22'),
    ('charset-normalizer', '3.5.1'), ('idna', '3.19'), ('msgpack', '1.2.2'),
    ('decorator', '5.3.1'), ('lazy-loader', '0.5'), ('packaging', '26.3'),
    ('platformdirs', '4.11.8'), ('threadpoolctl', '3.7.0'),
    ('typing-extensions', '4.16.0'),
)

# 模型扒谱扩展包 = transkun+muscriptor 的 METADATA 依赖闭包 (钉版)
# 排除: torch/torchaudio (CUDA 行按显卡成对装), numpy/mido (程序自带)
_TRANSCRIBE = (
    ('transkun', '2.0.1'), ('muscriptor', '0.3.0'),
    ('transformers', '4.50.0'), ('tokenizers', '0.21.4'),
    ('regex', '2026.5.9'), ('safetensors', '0.8.0'),
    ('huggingface-hub', '0.36.2'), ('filelock', '3.29.4'),
    ('fsspec', '2026.6.0'), ('pyyaml', '6.0.3'),
    ('sympy', '1.14.0'), ('mpmath', '1.3.0'), ('networkx', '3.4.2'),
    ('jinja2', '3.1.6'), ('markupsafe', '2.1.5'),
    ('beat-this', '1.1.0'), ('rotary-embedding-torch', '0.8.9'),
    ('einops', '0.8.2'), ('einx', '0.4.3'), ('frozendict', '2.4.7'),
    ('loguru', '0.7.3'), ('win32-setctime', '1.2.0'), ('colorama', '0.4.6'),
    ('torch-einops-utils', '0.1.4'), ('ncls', '0.0.68'),
    ('pretty-midi', '0.2.11.post0'), ('six', '1.17.0'),
    ('importlib-resources', '6.5.2'), ('mir-eval', '0.8.2'),
    ('pydub', '0.25.1'), ('seaborn', '0.13.2'), ('matplotlib', '3.10.8'),
    ('contourpy', '1.3.2'), ('cycler', '0.12.1'), ('fonttools', '4.61.1'),
    ('kiwisolver', '1.4.9'), ('pillow', '10.4.0'), ('pyparsing', '3.3.1'),
    ('python-dateutil', '2.9.0.post0'), ('pytz', '2026.2'),
    ('tzdata', '2026.2'), ('pandas', '2.3.3'),
    ('tensorboard', '2.20.0'), ('absl-py', '2.4.0'), ('grpcio', '1.81.1'),
    ('markdown', '3.10.2'), ('protobuf', '7.35.1'),
    ('tensorboard-data-server', '0.7.2'), ('werkzeug', '3.1.8'),
    ('setuptools', '80.10.2'), ('tqdm', '4.68.3'),
    ('torch-optimizer', '0.3.0'), ('pytorch-ranger', '0.1.1'),
    ('sox', '1.4.1'), ('moduleconf', '0.1.4'),
    # (分离轮) BS-Roformer 分离推理栈
    ('bs-roformer-infer', '0.1.5'), ('beartype', '0.14.0'),
    ('ml-collections', ''),
    ('fastapi', '0.137.2'), ('starlette', '1.3.1'), ('pydantic', '2.10.6'),
    ('pydantic-core', '2.27.2'), ('annotated-types', '0.7.0'),
    ('typing-inspection', '0.4.2'), ('annotated-doc', '0.0.4'),
    ('httpx', '0.28.1'), ('anyio', '4.14.0'), ('httpcore', '1.0.9'),
    ('sniffio', '1.3.1'), ('typer', '0.26.7'), ('shellingham', '1.5.4'),
    ('rich', '15.0.0'), ('markdown-it-py', '4.2.0'), ('mdurl', '0.1.2'),
    ('pygments', '2.20.0'), ('uvicorn', '0.49.0'), ('click', '8.4.1'),
    ('h11', '0.16.0'), ('httptools', '0.8.0'), ('python-dotenv', '1.2.1'),
    ('watchfiles', '1.2.0'), ('websockets', '12.0'),
    ('python-multipart', '0.0.32'),
    # 转录运行时共享依赖 (transkun 路线不装多音高包时也需要)
    ('scipy', '1.15.3'), ('soxr', '1.1.0'), ('soundfile', '0.14.0'),
    ('cffi', '2.1.1'), ('pycparser', '3.0'), ('requests', '2.34.2'),
    ('urllib3', '2.7.0'), ('certifi', '2026.7.22'),
    ('charset-normalizer', '3.5.1'), ('idna', '3.19'),
    ('packaging', '26.3'), ('typing-extensions', '4.16.0'),
    ('decorator', '5.3.1'),
)

# steps: ('pypi', (包名, 钉版)) 走清华镜像解析; ('url', (文件名, 直链)) 直下
PYPI_PACKS = (
    {'id': 'multipitch',
     'display': 'librosa 链 %d 包 (PyPI 镜像)' % len(_MULTIPITCH),
     'size': '≈120 MB',
     'desc': '多音高分析依赖 (librosa 链) → 安装到 _vendor, 缺它则「声组织」不可用',
     'steps': [('pypi', p) for p in _MULTIPITCH]},
    {'id': 'transcribe',
     'display': 'transkun+muscriptor 生态 %d 包 (PyPI 镜像)' % len(_TRANSCRIBE),
     'size': '≈150 MB',
     'desc': '模型扒谱依赖 → 安装到 _vendor; torch 本体在「CUDA 版本」行按显卡安装, '
             'numpy/mido 程序自带',
     'steps': [('pypi', p) for p in _TRANSCRIBE]},
    {'id': 'beatnet',
     'display': 'BeatNet 节拍分析 (PyPI 镜像)',
     'size': '≈10 MB + 权重自动下载',
     'desc': '(四期) 转录后自动节拍标记 (BPM/拍号) → 装入系统 Python 桥接环境; '
             '未安装时自动降级 librosa 拍点',
     'steps': [('pypi', 'BeatNet==1.1.3')]},
)


def _cuda_pack(cid, ver, gb, gpu):
    """CUDA 行: torch+torchaudio 与 torch 同版本成对 (muscriptor 依赖 torchaudio)"""
    steps = []
    for pkg in ('torch', 'torchaudio'):
        f = '%s-%s%%2B%s-cp310-cp310-win_amd64.whl' % (pkg, ver, cid)
        steps.append(('url', (f.replace('%2B', '+'),
                              '%s/%s/%s' % (_M, cid, f))))
    return {'id': cid, 'gpu': gpu, 'size': '≈%.1f GB' % gb,
            'desc': gpu,
            'display': 'torch+torchaudio %s (%s)' % (ver, cid),
            'steps': steps}


CUDA_PACKS = (
    _cuda_pack('cu118', '2.7.1', 2.6,
               'GTX 900 / 10 系也能用 (Maxwell·Pascal·Volta·Turing·Ampere·Ada) 老卡万金油'),
    _cuda_pack('cu121', '2.5.1', 2.3, 'RTX 20 / 30 / 40 系 (Turing·Ampere·Ada)'),
    _cuda_pack('cu126', '2.7.1', 2.5, 'GTX 10 系及以上 (Pascal 起, 不含 GTX 900)'),
    _cuda_pack('cu128', '2.7.1', 2.6, 'RTX 50 系 (Blackwell) 必选 · Turing 及以上'),
)

# ------------------------------------------------------- wheel 解析 ----
# 注意: 三个元组的顺序 = 优先级升序 (index 越大越优先, 配合 max 选取)
_PY_TAG = ('py2.py3', 'py3', 'cp310')
_ABI_TAG = ('none', 'abi3', 'cp310')
_PLAT_TAG = ('any', 'win_amd64')
_RE_MAJOR = re.compile(r'^cp3(\d+)$')


def _py_ok(py, abi):
    """python 标签可行性: cp310/py3 直可装; cp3x-abi3 向前兼容 (x<=10)"""
    if py in _PY_TAG:
        return True
    if abi == 'abi3':
        m = _RE_MAJOR.match(py)
        return bool(m) and int(m.group(1)) <= 10
    return False


def _verkey(ver):
    """版本排序键: 提取数字段 ('0.2.11.post0' → (0,2,11,0))"""
    return tuple(int(x) for x in re.findall(r'\d+', ver))


def _parse_wheel(fn):
    """wheel 文件名 → (归一名, 版本, py, abi, plat); 非 wheel/解析失败 → None"""
    if not fn.endswith('.whl'):
        return None
    m = re.match(r'^(.+?)-(\d[^-]*)-([^-]+)-([^-]+)-([^-]+)\.whl$', fn)
    if not m:
        return None
    return (_norm(m.group(1)), m.group(2)) + m.groups()[2:]


def _wheel_rank(py, abi, plat):
    return (_PLAT_TAG.index(plat), _ABI_TAG.index(abi), _PY_TAG.index(py)
            if py in _PY_TAG else -1)


def _pick_wheel(html, page, name, pin=''):
    """simple 索引页 → 最优 (文件名, 链接): 钉版优先, 缺失回退最新; 无 → None
       相对链接以实际索引页 URL 为 base 解析 (各镜像包路径不同)"""
    cands = []
    for href, text in re.findall(r'href="([^"]+)"[^>]*>([^<]+)</a>', html):
        p = _parse_wheel(text.strip())
        if p is None or p[0] != _norm(name):
            continue
        _, ver, py, abi, plat = p
        if plat in _PLAT_TAG and _py_ok(py, abi):
            cands.append((ver, _wheel_rank(py, abi, plat),
                          text.strip(), href))
    if not cands:
        return None
    pool = [c for c in cands if _norm(c[0]) == _norm(pin or c[0])]
    if not pool:                                       # 钉版缺失 → 回退最新
        pool = cands
    ver, _rk, fn, href = max(pool, key=lambda c: (_verkey(c[0]), c[1]))
    return fn, urljoin(page, href)


def _http_text(url):
    req = urllib.request.Request(url, headers={'User-Agent': _UA})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode('utf-8', 'replace')


# (限速轮) 速度守卫: 平均速度持续过低 → 抛 _SlowMirror 换镜像
SLOW_GRACE_S = 6.0                             # TCP 慢启动宽限 (秒)
SLOW_MIN_BPS = 1024 * 1024                     # 1 MB/s 判慢线 (国内正常镜像 2~10+ MB/s)


def _is_slow(done, elapsed):
    """平均速度判慢: 超过宽限期且仍低于阈值 → True (小文件/刚起步不算)"""
    return elapsed > SLOW_GRACE_S and done / max(1e-3, elapsed) < SLOW_MIN_BPS


class _SlowMirror(Exception):
    """镜像可用但速度过低"""


class _BadDownload(Exception):
    """下载产物不合格: 截断 / 非 zip (错误页) / 压缩包损坏 → 重下或换源"""


class _Abort(Exception):
    """用户中止"""


# (连接诊断轮) 系统代理残留/安全软件拦截 + 多源切换 --------------------------
_NO_PROXY_OPENER = None


def _conn_refused(e):
    """URLError 是否为连接被拒 (WinError 10061 / ConnectionRefusedError)"""
    r = getattr(e, 'reason', e)
    return isinstance(r, ConnectionRefusedError) or '10061' in str(r)


def _open_url(req, timeout):
    """默认走系统代理; 连接被拒 (典型: 代理软件已关但系统代理残留) →
       绕过代理直连重试; 仍失败抛回原错误 (供上层友好映射)"""
    global _NO_PROXY_OPENER
    try:
        return urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.URLError as e:
        if not _conn_refused(e):
            raise
        if _NO_PROXY_OPENER is None:
            _NO_PROXY_OPENER = urllib.request.build_opener(
                urllib.request.ProxyHandler({}))
        try:
            return _NO_PROXY_OPENER.open(req, timeout=timeout)
        except Exception:
            raise e


def _friendly_net_err(e):
    """网络错误 → 大白话原因与自查建议"""
    s = str(getattr(e, 'reason', e))
    if '10061' in s:
        return ('连接被拒绝 — 常见原因: '
                '①开了代理/VPN 但软件已关闭, 系统代理没取消 (程序已自动尝试绕过代理直连); '
                '②安全软件拦截了程序联网; ③镜像临时不可用。'
                '请检查后重试或换网络环境。')
    if '10060' in s or 'timed out' in s.lower() or '超时' in s:
        return '连接超时 — 网络或镜像临时不可用, 请稍后重试'
    return s


def _wrap_net(e):
    if isinstance(e, urllib.error.URLError):
        return RuntimeError(_friendly_net_err(e))
    return e


def _alt_urls(url):
    """CUDA 直链备用源: 主源 ↔ 备源 (其余源无备用)"""
    if url.startswith(_M + '/'):
        return [url, _M_ALT + url[len(_M):]]
    if url.startswith(_M_ALT + '/'):
        return [url, _M + url[len(_M_ALT):]]
    return [url]


def _step_attempts(urls):
    """先广后深: 所有源各设防跑一遍; 全部源都慢才不设防重试"""
    return [(u, True) for u in urls] + [(u, False) for u in urls]


class _Worker(QThread):
    """串行 下载+安装 队列; tick(阶段, 已完成, 总量, 附言) 进度"""
    tick = Signal(str, int, int, str)
    item_done = Signal(str, bool, str)
    all_done = Signal()

    def __init__(self, packs, parent=None):
        super().__init__(parent)
        self.packs = packs
        self._abort = False
        self._pref = None                             # 本队列内测速合格的镜像

    def stop(self):
        self._abort = True

    def _mirror_order(self):
        """尝试顺序: 测速合格的首选镜像优先, 其余按原顺序"""
        rest = [m for m in MIRRORS if m != self._pref]
        return ([self._pref] if self._pref in MIRRORS else []) + rest

    def run(self):
        os.makedirs(DL_DIR, exist_ok=True)
        for pk in self.packs:
            if self._abort:
                break
            try:
                steps = pk['steps']
                for k, (kind, arg) in enumerate(steps, 1):
                    if self._abort:
                        raise _Abort()
                    if k > 1:                          # 步间限速, 防镜像限流
                        time.sleep(0.3)
                    pre = '[%d/%d] ' % (k, len(steps))
                    if kind == 'pypi':
                        self._step_pypi(arg, pk['id'], pre)
                    else:
                        self._step_url(arg, pk['id'], pre)
                self.item_done.emit(pk['id'], True, '')
            except _Abort:
                self._cleanup()
                break
            except Exception as e:                    # 网络/磁盘 → 单包失败不挡后续
                self._cleanup()
                self.item_done.emit(pk['id'], False, str(e))
        self.all_done.emit()

    def _cleanup(self):
        if os.path.isdir(DL_DIR):
            for f in os.listdir(DL_DIR):
                if f.endswith('.part'):
                    try:
                        os.remove(os.path.join(DL_DIR, f))
                    except OSError:
                        pass

    def _step_pypi(self, arg, pid, pre):
        """按镜像链解析+下载 (先广后深): 所有镜像各设防一遍, 慢 6s 即换;
           全部慢后最后一轮不设防 —— 接受最慢的继续下, 而非报失败"""
        name, pin = arg
        last = None
        for base, enforce in _step_attempts(self._mirror_order()):
            page = base + _norm(name) + '/'
            try:
                fn, url = _pick_wheel(_http_text(page), page, name, pin)
                if fn is None:
                    raise RuntimeError('镜像索引中没有可用 wheel: %s' % name)
                for _attempt in (1, 2):               # (完整性轮) 坏产物重下一次
                    try:
                        path = self._download(
                            url, fn, '%s%s %s' % (pre, name, pid),
                            enforce_speed=enforce)
                        self._extract(fn, path, pre)
                        break
                    except _BadDownload:
                        self._cleanup()
                        if _attempt == 2:
                            raise
                self._pref = base                       # 完整下完 → 记为首选
                return
            except _Abort:
                raise
            except (_SlowMirror, _BadDownload) as e:  # 慢源/坏产物 → 换镜像重下
                self._cleanup()
                last = e
            except Exception as e:                    # 该镜像失败 → 下一个
                self._cleanup()
                last = e
        raise _wrap_net(last) if isinstance(last, urllib.error.URLError) \
            else (last if last is not None else RuntimeError('无可用镜像'))

    def _step_url(self, arg, pid, pre):
        """CUDA 直链多源尝试: 先广后深 —— 所有源各设防跑一遍 (慢源 6s 即弃),
           全部源都慢才不设防死磕; 连接层故障直接换源; 报错经友好翻译"""
        fname, url = arg
        label = '%s%s %s' % (pre, fname, pid)
        last = None
        skip = None                                   # 连接层故障的源 (本轮跳过)
        for u, enforce in _step_attempts(_alt_urls(url)):
            if skip and urlsplit(u).netloc == skip:
                continue
            try:
                path = self._download(u, fname, label, enforce_speed=enforce)
                self._extract(fname, path, pre)
                return
            except _SlowMirror as e:                  # 慢源 → 下一源 (先广后深)
                self._cleanup()
                last = e
                self.tick.emit(t('下载'), 0, 0,
                               t('速度过慢, 切换备用源…'))
            except _BadDownload as e:                 # 坏产物 → 下一源重下
                self._cleanup()
                last = e
            except urllib.error.URLError as e:        # 连接层故障 → 换源
                self._cleanup()
                last = e
                skip = urlsplit(u).netloc
        raise _wrap_net(last)

    def _download(self, url, fname, label, enforce_speed=True):
        self.tick.emit(t('下载'), 0, 0, label)
        req = urllib.request.Request(url, headers={'User-Agent': _UA})
        try:
            resp = _open_url(req, 60)
        except urllib.error.HTTPError as e:           # 403/429 等限流 → 稍候重试一次
            if e.code in (403, 429) or e.code >= 500:
                time.sleep(2)
                resp = _open_url(req, 60)
            else:
                raise
        with resp:
            total = int(resp.headers.get('Content-Length') or 0)
            tmp = os.path.join(DL_DIR, fname + '.part')
            done = 0
            t0 = time.time()
            with open(tmp, 'wb') as f:
                while True:
                    if self._abort:
                        raise _Abort()
                    b = resp.read(262144)
                    if not b:
                        break
                    f.write(b)
                    done += len(b)
                    el = time.time() - t0
                    if enforce_speed and _is_slow(done, el):
                        raise _SlowMirror(            # 限速轮: 慢源弃下换镜像
                            '%s: %.0f KB/s 过慢' % (fname, done / el / 1024))
                    sp = done / max(1e-3, el)
                    self.tick.emit(t('下载'), done, total, '%s%.1f MB/s'
                                   % (label, sp / 1048576.0))
        if total > 0 and done != total:               # (完整性轮) 流被提前掐断
            raise _BadDownload('%s: 下载不完整 %d/%d 字节'
                               % (fname, done, total))
        final = os.path.join(DL_DIR, fname)
        if os.path.exists(final):
            os.remove(final)
        os.rename(tmp, final)
        return final

    def _extract(self, fname, path, pre):
        """wheel/zip 解压进 _vendor (wheel 的 *.data/<kind>/ 重映射到根);
           完整性哨兵: PK 魔数 + 可打开, 不合格抛 _BadDownload 交由上层重下"""
        self.tick.emit(t('安装'), 0, 0, pre + fname)
        with open(path, 'rb') as f:
            if f.read(4) != b'PK\x03\x04':            # (完整性轮) 错误页/HTML 等
                raise _BadDownload('%s: 下载内容不是有效压缩包' % fname)
        try:
            zf = zipfile.ZipFile(path)
        except zipfile.BadZipFile as e:               # 截断/中央目录缺失
            raise _BadDownload('%s: 压缩包损坏 (%s)' % (fname, e))
        with zf:
            os.makedirs(VENDOR_DIR, exist_ok=True)
            infos = [i for i in zf.infolist() if not i.is_dir()]
            for n, info in enumerate(infos):
                if self._abort:
                    raise _Abort()
                rel = _safe_rel(info.filename, fname)
                if rel is None:
                    continue
                dst = os.path.join(VENDOR_DIR, *rel.split('/'))
                d = os.path.dirname(dst)
                if d:
                    os.makedirs(d, exist_ok=True)
                with zf.open(info) as src, open(dst, 'wb') as out:
                    shutil.copyfileobj(src, out, 262144)
                if n % 32 == 0 or n == len(infos) - 1:
                    self.tick.emit(t('安装'), n + 1, len(infos), pre + fname)
        os.remove(path)


def _safe_rel(name, fname):
    """归一化成员路径; 越界(../ 绝对盘符)拒绝; wheel 的 *.data/<kind>/ 重映射到根"""
    rel = name.replace('\\', '/').lstrip('/')
    if re.match(r'^[A-Za-z]:', rel) or '..' in rel.split('/'):
        return None
    if fname.endswith('.whl') and '.data/' in rel:
        post = rel.split('.data/', 1)[1]
        kind, _, tail = post.partition('/')
        if kind in ('purelib', 'platlib', 'data') and tail:
            rel = tail
        else:
            return None                               # scripts 等不落盘
    return rel


class _CheckTree(QTreeWidget):
    """(Win11 可见轮) 整行点击 = 翻转勾选; 点在指示器上时交给原生处理 (不重复翻转)"""
    def mouseReleaseEvent(self, ev):
        idx = self.indexAt(ev.position().toPoint())
        it = self.itemFromIndex(idx)
        toggle = False
        if it is not None and idx.column() < 2 \
                and it.flags() & Qt.ItemIsUserCheckable:
            opt = QStyleOptionViewItem()
            self.initStyleOption(opt, idx)
            ind = self.style().subElementRect(
                QStyle.SE_ItemViewItemCheckIndicator, opt, self)
            toggle = not ind.contains(ev.position().toPoint())
        super().mouseReleaseEvent(ev)
        if toggle:
            it.setCheckState(
                0, Qt.Unchecked if it.checkState(0) == Qt.Checked
                else Qt.Checked)


class ExtensionDownloaderDialog(QDialog):
    """扩展包下载: 树形分组 + 逐行/勾选下载 + 蓝色下载与安装进度条"""
    def __init__(self, mw):
        super().__init__(mw)
        self.setWindowTitle(t('扩展包下载'))
        self.resize(780, 540)
        self.mw = mw
        self.worker = None
        self.rows = {}                                # id -> (行, 按钮, 条目)
        lay = QVBoxLayout(self)
        lb = QLabel(t('多音高 / 模型扒谱依赖走 PyPI 镜像三源自动择优 (上交/阿里云/清华), '
                      'CUDA 走上交/阿里云双源自动切换; '
                      '点击行任意位置勾选, 下载后自动解压安装, 重启程序生效'))
        lb.setWordWrap(True)
        lb.setStyleSheet('color:#666;')
        lay.addWidget(lb)
        self.tree = _CheckTree()
        self.tree.setHeaderLabels([t('文件 / 说明'), t('大小'), t('操作')])
        self.tree.header().setSectionResizeMode(
            0, self.tree.header().ResizeMode.Stretch)
        self.tree.setColumnWidth(1, 80)
        self.tree.setColumnWidth(2, 96)
        # (Win11 可见轮) 指示器显式样式: Fusion 深色调色板下未勾选指示器近乎隐形
        # (部分系统主题下尤甚) —— 样式表优先级高于一切系统绘制, 三端一致可见
        self.tree.setStyleSheet(
            'QTreeWidget::indicator{width:14px;height:14px;'
            'border:1px solid #90a4b8;border-radius:3px;background:#1b2530;}'
            'QTreeWidget::indicator:hover{border-color:#1e6fd9;}'
            'QTreeWidget::indicator:checked{background:#1e6fd9;'
            'border-color:#1e6fd9;}'
            'QToolTip{background:#0f1720;color:#d6d6de;'
            'border:1px solid #3a4a5a;}')
        lay.addWidget(self.tree, 1)
        self._add_group(t('多音高扩展包'), PYPI_PACKS[0:1])
        self._add_group(t('模型扒谱依赖扩展包'), PYPI_PACKS[1:2])
        self._add_group(t('节拍分析扩展包'), PYPI_PACKS[2:3])
        self._add_group(t('CUDA 版本 (按显卡选其一)'), CUDA_PACKS, open=False)
        self.pb = QProgressBar()
        self.pb.setRange(0, 100)
        self.pb.setFormat('%p%')
        self.pb.setStyleSheet(
            'QProgressBar{border:1px solid #c9d4e0;border-radius:3px;'
            'background:#eef2f7;text-align:center;height:14px;}'
            'QProgressBar::chunk{background:#1e6fd9;border-radius:2px;}')
        lay.addWidget(self.pb)
        self.lb_status = QLabel(t('就绪'))
        self.lb_status.setStyleSheet('color:#555;')
        lay.addWidget(self.lb_status)
        bot = QHBoxLayout()
        self.b_batch = QPushButton(t('下载勾选项'))
        self.b_batch.clicked.connect(self._batch)
        bot.addWidget(self.b_batch)
        bot.addStretch(1)
        self.b_close = QPushButton(t('关闭'))
        self.b_close.clicked.connect(self._close_clicked)
        bot.addWidget(self.b_close)
        lay.addLayout(bot)
        self.tree.itemChanged.connect(lambda *_: self._sync_batch())
        self._sync_batch()

    # ---- 构建列表 ----
    def _add_group(self, title, packs, open=True):
        root = QTreeWidgetItem([title, '', ''])
        f = root.font(0)
        f.setBold(True)
        root.setFont(0, f)
        root.setFlags(Qt.ItemIsEnabled)
        root.setToolTip(0, t('勾选后可用下方「下载勾选项」批量下载'))
        self.tree.addTopLevelItem(root)
        for pk in packs:
            child = QTreeWidgetItem([pk['display'], pk['size'], ''])
            for c in range(3):                        # (Win11 可见轮) 三列悬停均有提示
                child.setToolTip(c, pk['desc'])
            child.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
            child.setCheckState(0, Qt.Unchecked)
            root.addChild(child)
            btn = QPushButton(t('下载'))
            btn.setFocusPolicy(Qt.NoFocus)
            btn.setFixedWidth(84)
            btn.clicked.connect(lambda _=False, i=pk: self._single(i))
            self.tree.setItemWidget(child, 2, btn)
            self.rows[pk['id']] = (child, btn, pk)
        root.setExpanded(open)

    # ---- 动作 ----
    def _single(self, pk):
        self._start([pk])

    def _batch(self):
        its = [pk for _id, (child, _btn, pk) in self.rows.items()
               if child.checkState(0) == Qt.Checked]
        self._start(its)

    def _start(self, packs):
        if self.worker is not None and self.worker.isRunning():
            self.lb_status.setText(t('已有下载在进行, 请先停止'))
            return
        if not packs:
            self.lb_status.setText(t('没有可下载项'))
            return
        os.makedirs(DL_DIR, exist_ok=True)
        self.worker = _Worker(packs, self)
        self.worker.tick.connect(self._tick)
        self.worker.item_done.connect(self._item_done)
        self.worker.all_done.connect(self._all_done)
        self._set_ui_running(True, len(packs))
        self.worker.start()

    def _tick(self, phase, done, total, msg):
        if total > 0:
            self.pb.setRange(0, 100)
            self.pb.setValue(min(100, done * 100 // total))
        else:                                         # 总长未知 → 流水灯
            self.pb.setRange(0, 0)
        self.lb_status.setText(msg)

    def _item_done(self, pid, ok, err):
        child, btn, _pk = self.rows[pid]
        if ok:
            child.setCheckState(0, Qt.Unchecked)
            btn.setText(t('已安装'))
            btn.setEnabled(False)
            self.lb_status.setText(t('%s 安装完成, 重启程序后生效') % pid)
        else:
            self.lb_status.setStyleSheet('color:#b00;')
            self.lb_status.setText(t('%s 失败: %s') % (pid, err))
            QMessageBox.warning(self, t('下载/安装失败'), t('%s: %s') % (pid, err))

    def _all_done(self):
        self._set_ui_running(False, 0)
        self.pb.setRange(0, 100)
        self.pb.setValue(0)
        self.lb_status.setStyleSheet('color:#555;')
        self.lb_status.setText(t('队列结束 (下载目录: _downloads)'))

    def _set_ui_running(self, running, n):
        for _id, (child, btn, _pk) in self.rows.items():
            if btn.text() != t('已安装'):
                btn.setEnabled(not running)
            child.setDisabled(running)
        self.b_batch.setEnabled(not running)
        self.b_batch.setText(t('下载勾选项') if not running
                             else t('下载中 0/%d…' % n))
        self.b_close.setText(t('停止') if running else t('关闭'))

    def _sync_batch(self):
        if self.worker is None or not self.worker.isRunning():
            n = sum(1 for _id, (c, _b, _pk) in self.rows.items()
                    if c.checkState(0) == Qt.Checked)
            self.b_batch.setText(t('下载勾选项 (%d)' % n))

    def _close_clicked(self):
        if self.worker is not None and self.worker.isRunning():
            self.worker.stop()
            self.lb_status.setText(t('正在停止…'))
            return
        self.reject()

    def closeEvent(self, ev):
        if self.worker is not None and self.worker.isRunning():
            self.worker.stop()
            self.worker.wait(3000)
        super().closeEvent(ev)
