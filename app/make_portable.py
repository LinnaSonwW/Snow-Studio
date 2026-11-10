# -*- coding: utf-8 -*-
"""便携包构建脚本 (便捷版): 生成免安装绿色目录
   内容 = 嵌入式 Python 3.10 + PySide6/mido 运行环境 (libs/, 依赖单开文件夹)
         + 本项目代码 + FFmpeg (_runtime) + FluidSynth 运行库 (fluidsynth/)
   不含: numpy / librosa 多音高分析链 / torch / 模型权重 ——
         由程序内 设置 → 扩展包下载 (PyPI 镜像) 与 导入模型压缩包 (哈希校验)
         自助补齐; 环境自检会明确标注缺失。
   运行: python make_portable.py
   输出: ../genshi-便捷版/  (run.bat 启动)"""
import os
import shutil
import subprocess
import sys
import zipfile
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
DST = os.path.join(os.path.dirname(ROOT), 'genshi-便捷版')
PY_DIR = os.path.join(DST, 'python')
SP_SRC = r'C:\Users\LinnaSnow\AppData\Local\Programs\Python\Python310\Lib\site-packages'
PY_EMBED_URLS = (
    'https://www.python.org/ftp/python/3.10.11/python-3.10.11-embed-amd64.zip',
    'https://mirrors.huaweicloud.com/python/3.10.11/python-3.10.11-embed-amd64.zip',
)
# 便携包 libs/ 包含的第三方包 (编辑器/播放/MIDI/SF2 试听 所需最小集)
# packaging = mido 硬依赖; numpy 不带 (多音高扩展包导入 _vendor 时自带)
KEEP_DIRS = ('PySide6', 'shiboken6', 'mido', 'packaging')
KEEP_FILES = ('fluidsynth.py',)
# 开发/测试脚本不进便携包
DEV_PREFIX = ('_test', '_bench', '_dbg', '_prof', '_uitest', '_patch',
              '_smoke', '_verify', '_launcher')

FFMPEG_URL = 'https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip'
FF_CACHE = os.path.join(ROOT, '_runtime', 'ffmpeg-essentials.zip')

# ---- PySide6 裁剪 (瘦身轮): 白名单外整体删除, 约省 440MB ----
# 保留: Core/Gui/Widgets (界面), Quick/Qml/QuickWidgets/ShaderTools (卷帘 QML),
#       Multimedia 三件套 + plugins/multimedia (原曲对照 QMediaPlayer),
#       Network/Svg/OpenGL/Concurrent, opengl32sw (老显卡软件 GL 兜底)
PS6_DEL_FILE = (
    'Qt6WebEngine*', 'Qt6Pdf*', 'Qt6Designer*', 'Qt6Quick3D*', 'Qt63D*',
    'Qt6Charts*', 'Qt6DataVis*', 'Qt6Sensors*', 'Qt6SerialPort*', 'Qt6Sql*',
    'Qt6Test*', 'Qt6WebChannel*', 'Qt6WebSockets*', 'Qt6HttpServer*',
    'Qt6RemoteObjects*', 'Qt6Scxml*', 'Qt6NetworkAuth*', 'Qt6Location*',
    'Qt6Positioning*', 'Qt6Bluetooth*', 'Qt6Nfc*', 'Qt6Spatial*',
    'Qt6TextToSpeech*', 'Qt6VirtualKeyboard*', 'Qt6Help*', 'Qt6UiTools*',
    'Qt6StateMachine*', 'Qt6QuickDialogs2*', 'Qt6WebView*',
    'QtWebEngine*', 'QtPdf*', 'QtDesigner*', 'QtQuick3D*', 'Qt3D*',
    'QtCharts*', 'QtDataVisualization*', 'QtSensors*', 'QtSerialPort*',
    'QtSql*', 'QtTest*', 'QtWebChannel*', 'QtWebSockets*', 'QtHttpServer*',
    'QtRemoteObjects*', 'QtScxml*', 'QtNetworkAuth*', 'QtLocation*',
    'QtPositioning*', 'QtBluetooth*', 'QtNfc*', 'QtSpatial*',
    'QtTextToSpeech*', 'QtVirtualKeyboard*', 'QtHelp*', 'QtUiTools*',
    'QtStateMachine*', 'QtWebView*', '*.exe',
)
PS6_DEL_DIR = ('resources', 'translations', 'metatypes',
               'qml/QtQuick3D', 'qml/Qt5Compat', 'qml/QtWebView',
               'qml/QtWebSockets', 'qml/QtWebChannel', 'qml/QtCharts',
               'qml/QtDataVisualization', 'qml/Qt3D', 'qml/QtGraphs',
               'qml/QtSensors', 'qml/QtTest', 'qml/QtWeb', 'qml/QtLocation',
               'qml/QtBluetooth', 'qml/QtNfc',
               'plugins/sqldrivers', 'plugins/sceneparsers', 'plugins/renderers',
               'plugins/qmltooling', 'plugins/webview', 'plugins/canbus',
               'plugins/position', 'plugins/sensors')


def log(msg):
    print(msg, flush=True)


def copytree(src, dst):
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns('__pycache__'),
                    dirs_exist_ok=True)


def is_dev(name):
    return name.startswith(DEV_PREFIX) or name == 'make_portable.py'


def slim_pyside6(ps6):
    """白名单外整体删除 (Qt6*.dll / *.pyd 通配 + 目录 + 开发工具 exe)"""
    import glob
    n = 0
    for pat in PS6_DEL_FILE:
        for f in glob.glob(os.path.join(ps6, pat)):
            os.remove(f)
            n += 1
    for rel in PS6_DEL_DIR:
        d = os.path.join(ps6, rel.replace('/', os.sep))
        if os.path.isdir(d):
            shutil.rmtree(d, ignore_errors=True)
            n += 1
    log('  PySide6 裁剪: 删除 %d 项' % n)


def fetch_ffmpeg(dst_dir):
    """FFmpeg essentials 精简构建 (~160MB); 失败回退项目 full 构建"""
    os.makedirs(dst_dir, exist_ok=True)
    if not os.path.isfile(FF_CACHE):
        try:
            log('下载 FFmpeg essentials …')
            urllib.request.urlretrieve(FFMPEG_URL, FF_CACHE)
        except Exception as e:
            log('  下载失败 (%s)' % e)
    if os.path.isfile(FF_CACHE):
        with zipfile.ZipFile(FF_CACHE) as z:
            for info in z.infolist():
                base = os.path.basename(info.filename)
                if base in ('ffmpeg.exe', 'ffprobe.exe'):
                    with z.open(info) as src, \
                            open(os.path.join(dst_dir, base), 'wb') as out:
                        shutil.copyfileobj(src, out, 262144)
                    log('  取出 %s' % base)
        return
    full = os.path.join(ROOT, '_runtime', 'ffmpeg')
    if os.path.isdir(full):
        log('  回退: 复制项目 full 构建')
        copytree(full, dst_dir)


def fetch_embed(zpath):
    for url in PY_EMBED_URLS:
        try:
            log('下载嵌入式 Python 3.10.11: %s …' % url)
            urllib.request.urlretrieve(url, zpath)
            return
        except Exception as e:
            log('  失败 (%s), 换源…' % e)
    raise SystemExit('嵌入式 Python 下载失败 (python.org 与华为云镜像均不可达)')


def main():
    os.makedirs(DST, exist_ok=True)

    # ---- 1. 嵌入式 Python 3.10.11 ----
    if not os.path.isfile(os.path.join(PY_DIR, 'python.exe')):
        zpath = os.path.join(DST, 'python-embed.zip')
        if not os.path.isfile(zpath):
            fetch_embed(zpath)
        log('解压嵌入式 Python …')
        with zipfile.ZipFile(zpath) as z:
            z.extractall(PY_DIR)
        os.remove(zpath)

    # ---- 2. ._pth: 模块搜索路径 (嵌入式默认隔离, 需显式列出; 相对 python/ 目录)
    #      ..\data\vendor 预留: 扩展包下载器运行时装入 librosa 链后, 下次启动直接可 import
    with open(os.path.join(PY_DIR, 'python310._pth'), 'w', encoding='utf-8') as f:
        f.write('python310.zip\n.\n..\n..\\libs\n..\\app\n..\\data\\vendor\n'
                'import site\n')

    # ---- 3. libs/: 依赖单开文件夹 (PySide6 / shiboken6 / mido / packaging / fluidsynth.py)
    libs_dst = os.path.join(DST, 'libs')
    os.makedirs(libs_dst, exist_ok=True)
    log('复制 PySide6 运行环境到 libs/ (~640MB) …')
    for name in os.listdir(SP_SRC):
        src = os.path.join(SP_SRC, name)
        if os.path.isdir(src) and name in KEEP_DIRS:
            copytree(src, os.path.join(libs_dst, name))
        elif os.path.isfile(src) and name in KEEP_FILES:
            shutil.copy2(src, os.path.join(libs_dst, name))
    slim_pyside6(os.path.join(libs_dst, 'PySide6'))

    # ---- 4. 项目代码 + QML → app/ (排除开发/测试脚本) ----
    log('复制项目代码到 app/ …')
    app_dst = os.path.join(DST, 'app')
    os.makedirs(app_dst, exist_ok=True)
    for name in os.listdir(ROOT):
        src = os.path.join(ROOT, name)
        if is_dev(name):
            continue
        if (name.endswith(('.py', '.qml')) or name == 'qmldir') and os.path.isfile(src):
            dst = os.path.join(app_dst, name)
            if os.path.exists(dst) and os.path.samefile(src, dst):
                continue                                   # 脚本自身在便携版内时跳过
            shutil.copy2(src, dst)
        elif name == 'dialogs' and os.path.isdir(src):
            copytree(src, os.path.join(app_dst, 'dialogs'))

    # ---- 4b. FFmpeg essentials 与 FluidSynth 运行库 → runtime/; 预建 data/ ----
    log('FFmpeg essentials (runtime/ffmpeg, ~160MB) …')
    fetch_ffmpeg(os.path.join(DST, 'runtime', 'ffmpeg'))
    fs_src = r'C:\Users\LinnaSnow\Desktop\yanshi\fluidsynth-v2.6.0-win10-x64-cpp11\bin'
    if os.path.isdir(fs_src):
        log('复制 FluidSynth 运行库 (runtime/fluidsynth, ~6MB) …')
        copytree(fs_src, os.path.join(DST, 'runtime', 'fluidsynth'))
    for d in ('data/models', 'data/vendor', 'data/downloads'):
        os.makedirs(os.path.join(DST, d.replace('/', os.sep)), exist_ok=True)

    # ---- 5. 启动器 exe (PyInstaller 可用时; 失败仅提示, run.bat 始终可用) ----
    if os.path.isfile(os.path.join(ROOT, '_launcher_src.py')):
        import tempfile
        try:
            log('构建启动器 Snow原琴工作站.exe …')
            subprocess.run(
                [sys.executable, '-m', 'PyInstaller', '--onefile',
                 '--noconsole', '--clean', '--distpath', DST,
                 '--workpath', os.path.join(tempfile.gettempdir(), 'gs_launch_w'),
                 '--specpath', os.path.join(tempfile.gettempdir(), 'gs_launch_s'),
                 os.path.join(ROOT, '_launcher_src.py')],
                check=True, capture_output=True)
            src_exe = os.path.join(DST, '_launcher_src.exe')
            dst_exe = os.path.join(DST, 'Snow原琴工作站.exe')
            if os.path.isfile(src_exe):
                os.remove(dst_exe)
                os.rename(src_exe, dst_exe)
                log('  完成: Snow原琴工作站.exe (%.1f MB)'
                    % (os.path.getsize(dst_exe) / 1048576.0))
        except Exception as e:
            log('  启动器构建跳过 (%s); 可用 run.bat 启动' % e)

    # ---- 6. 启动脚本 + 说明 ----
    doc_src = os.path.join(ROOT, '便携版软件功能介绍.md')
    if os.path.isfile(doc_src):
        shutil.copy2(doc_src, os.path.join(DST, '软件功能介绍.md'))
    with open(os.path.join(DST, 'run.bat'), 'w', encoding='gbk') as f:
        f.write('@echo off\r\n'
                'cd /d %~dp0\r\n'
                'set "FLUIDSYNTH_HOME=%~dp0runtime\\fluidsynth"\r\n'
                'set "PATH=%~dp0runtime\\fluidsynth;%~dp0runtime\\ffmpeg;%PATH%"\r\n'
                'start "" python\\python.exe app\\演示.py\r\n')
    with open(os.path.join(DST, '使用说明.txt'), 'w', encoding='utf-8') as f:
        f.write(
            'Sigma & Snow 原琴工作站 - 便捷版 (核心版)\r\n'
            '================================\r\n'
            '双击 run.bat 启动 (免安装, 自带 Python 与 PySide6)。\r\n\r\n'
            '目录结构: app=程序代码  libs=依赖库  python=内置Python\r\n'
            '          runtime=运行库(ffmpeg/fluidsynth)  data=运行期数据\r\n\r\n'
            '已内置: 编辑/播放/网格/MIDI 全功能 + SF2 试听 (FluidSynth 运行库) + FFmpeg。\r\n'
            '本包不含多音高分析 (librosa 链) 与模型扒谱 (torch / 模型权重), 缺失时:\r\n'
            '  1. 多音高分析 / 模型扒谱依赖: 设置 → 扩展包下载 → 对应扩展包\r\n'
            '     (自动走清华/阿里云 PyPI 镜像下载并安装, 无需手动 pip)\r\n'
            '  2. 模型权重: 设置 → 导入模型压缩包 → 选择官方模型 zip\r\n'
            '     (校验唯一哈希通过后安装到 data/models/, 哈希不符会被拒绝)\r\n'
            '  3. GPU 加速: 设置 → 扩展包下载 → CUDA 版本, 按显卡型号选其一\r\n'
            '状态可在 设置 → 模型扒谱环境自检 中查看。\r\n')

    size = 0
    for base, _dirs, files in os.walk(DST):
        for f in files:
            size += os.path.getsize(os.path.join(base, f))
    log('完成: %s  (约 %.2f GB)' % (DST, size / 1024 ** 3))


if __name__ == '__main__':
    main()
