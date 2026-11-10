# -*- coding: utf-8 -*-
"""目录布局统一解析 (规范轮):
   便捷版分层布局  app/ python/ libs/ runtime/{ffmpeg,fluidsynth} data/{models,vendor,downloads}
   开发项目旧布局  根目录平铺 + _vendor + _runtime/ffmpeg + models/
   原则: 新布局存在则优先, 否则回退旧布局 —— 两个环境共用同一份代码。
   QML 与模块同级, 由各模块按 __file__ 自行定位, 不经过本模块。"""
import os

# 程序根定位:
#   便捷版分层布局: 本模块位于 <根>/app/ 下 → 根为上一级 (判据: 上一级有 libs/)
#   开发项目旧布局: 本模块位于项目根 → 根即所在目录
_HERE = os.path.dirname(os.path.abspath(__file__))
if os.path.basename(_HERE) == 'app' \
        and os.path.isdir(os.path.join(os.path.dirname(_HERE), 'libs')):
    APP_ROOT = os.path.dirname(_HERE)
else:
    APP_ROOT = _HERE


def _first(*cands):
    """第一个存在的目录; 全不存在则返回第一个 (写入目标用)"""
    for c in cands:
        if os.path.isdir(c):
            return c
    return cands[0]


def vendor_dir():
    """扩展包安装目标 (librosa 链等, sys.path 上的可导入目录)"""
    return _first(os.path.join(APP_ROOT, 'data', 'vendor'),
                  os.path.join(APP_ROOT, '_vendor'))


def models_dir():
    """模型权重根目录 (muscriptor_small / transkun 由导入器创建)"""
    return _first(os.path.join(APP_ROOT, 'data', 'models'),
                  os.path.join(APP_ROOT, 'models'))


def downloads_dir():
    """扩展包下载缓存"""
    return os.path.join(APP_ROOT, 'data', 'downloads')


def ffmpeg_dir():
    """FFmpeg 可执行目录 (PATH 前置用)"""
    return _first(os.path.join(APP_ROOT, 'runtime', 'ffmpeg'),
                  os.path.join(APP_ROOT, '_runtime', 'ffmpeg'))


def fluidsynth_dir():
    """FluidSynth 运行库目录 (SF2 试听)"""
    return _first(os.path.join(APP_ROOT, 'runtime', 'fluidsynth'),
                  os.path.join(APP_ROOT, 'fluidsynth'))
