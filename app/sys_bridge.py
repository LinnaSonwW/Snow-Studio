# -*- coding: utf-8 -*-
"""系统 Python 桥接 (桥接轮):
   便捷版是隔离环境, 自身没有 torch 时无法直接导入; 本模块探测用户电脑上
   已安装的系统 Python (含 torch + muscriptor/transkun 组件) —— 找到则
   模型扒谱改由系统 Python 子进程 CLI 执行, 不再强制软件内下载 2.3GB。

   find_bridge()  探测并缓存 →
     {'python': 路径, 'torch': True, 'muscriptor': True, 'transkun': True}
     或 None (没有可借用的环境)。
   探针用 importlib.util.find_spec (瞬时, 不真正 import torch)。"""
import json
import os
import re
import subprocess
import sys

import paths

CREATE_NO_WINDOW = 0x08000000              # GUI 程序弹子进程不闪控制台
_PROBE_TIMEOUT = 20                        # 单个候选探测超时 (秒)
_CUDA_CACHE = {}                           # 解释器路径 → CUDA 可用 (torch 导入较慢, 缓存)

# 探针: 只查组件是否可得 (find_spec 瞬时, 不真正 import torch)
_PROBE = (
    "import importlib.util as _u, json\n"
    "r = {}\n"
    "for _m in ('torch', 'muscriptor', 'transkun', 'bs_roformer'):\n"
    "    try:\n"
    "        r[_m] = _u.find_spec(_m) is not None\n"
    "    except Exception:\n"
    "        r[_m] = False\n"
    "print(json.dumps(r))\n"
)

_CACHE = None                              # None=未探测; dict/False=已探测结果


def _self_python():
    return os.path.normcase(os.path.abspath(sys.executable))


def _under_app_root(p):
    try:
        return os.path.normcase(os.path.abspath(p)).startswith(
            os.path.normcase(paths.APP_ROOT + os.sep))
    except Exception:
        return False


def _candidate_pythons():
    """候选系统 Python: py 启动器清单 + PATH 上的 python; 排除自带解释器"""
    cands, seen = [], set()
    me = _self_python()

    def add(p):
        p = os.path.normpath(str(p).strip().strip('*').strip())
        if os.path.splitext(p)[1].lower() != '.exe':
            p = os.path.join(p, 'python.exe')
        if not os.path.isfile(p):
            return
        k = os.path.normcase(p)
        if k in seen or k == me or _under_app_root(p):
            return
        seen.add(k)
        cands.append(p)

    try:                                    # py 启动器: 每行末尾是解释器路径
        out = subprocess.run(['py', '-0p'], capture_output=True, text=True,
                             timeout=15, creationflags=CREATE_NO_WINDOW)
        for line in (out.stdout or '').splitlines():
            m = re.search(r'([A-Za-z]:\\.*?python\.exe)', line, re.I)
            if m:
                add(m.group(1))
    except Exception:
        pass
    try:                                    # PATH 上的 python
        out = subprocess.run(['where', 'python'], capture_output=True,
                             text=True, timeout=15,
                             creationflags=CREATE_NO_WINDOW)
        for line in (out.stdout or '').splitlines():
            add(line.strip())
    except Exception:
        pass
    return cands


def _probe(py):
    """单候选探测 → {'torch':bool,'muscriptor':bool,'transkun':bool} 或 None"""
    try:
        out = subprocess.run([py, '-c', _PROBE], capture_output=True,
                             text=True, timeout=_PROBE_TIMEOUT,
                             creationflags=CREATE_NO_WINDOW)
        for line in reversed((out.stdout or '').splitlines()):
            line = line.strip()
            if line.startswith('{'):
                return json.loads(line)
    except Exception:
        pass
    return None


def find_bridge(force=False):
    """探测可借用的系统 Python (torch + 任一转录组件齐全); 结果进程内缓存。
       返回 {'python', 'torch', 'muscriptor', 'transkun'} 或 None"""
    global _CACHE
    if _CACHE is not None and not force:
        return _CACHE
    best, best_score = None, -1
    for py in _candidate_pythons():
        d = _probe(py)
        if not d or not (d.get('torch') and (d.get('muscriptor')
                                             or d.get('transkun'))):
            continue
        score = (1 if d.get('muscriptor') else 0) \
            + (1 if d.get('transkun') else 0)
        if score > best_score:
            best, best_score = {'python': py, 'torch': True,
                                'muscriptor': bool(d.get('muscriptor')),
                                'transkun': bool(d.get('transkun'))}, score
    _CACHE = best if best is not None else False
    return _CACHE


def bridge_summary():
    """自检报告用单行摘要; 无可借用环境 → None"""
    b = find_bridge()
    if not b:
        return None
    comps = '/'.join([c for c in ('muscriptor', 'transkun') if b.get(c)])
    return '%s (组件: %s)' % (b['python'], comps)


def cuda_ok(interp):
    """该解释器的 torch 是否可用 CUDA (导入 torch, 首次较慢, 结果缓存)"""
    if interp in _CUDA_CACHE:
        return _CUDA_CACHE[interp]
    ok = False
    try:
        r = subprocess.run(
            [interp, '-c',
             'import torch;print(1 if torch.cuda.is_available() else 0)'],
            capture_output=True, text=True, timeout=180,
            creationflags=CREATE_NO_WINDOW)
        ok = r.stdout.strip().endswith('1')
    except Exception:
        ok = False
    _CUDA_CACHE[interp] = ok
    return ok
