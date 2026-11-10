# -*- coding: utf-8 -*-
"""模型压缩包导入:
   MODEL_PACKS         规范模型包注册表 (SHA-256 唯一哈希 → 模型名/安装目录)
   sha256_of_file      流式分块哈希
   ModelImportWorker   后台导入: ①整包哈希校验 (不匹配拒绝) → ②安全解压到
                       models/<目录> (防越界; 单层顶层目录自动剥离)
   设置弹窗「导入模型压缩包…」入口, 替代手填权重路径/模型目录。"""
import hashlib
import os
import re
import shutil
import zipfile

from PySide6.QtCore import Qt, QThread, Signal

from i18n import t
import paths

APP_ROOT = paths.APP_ROOT                     # 程序根 (便捷版 = 便捷版根目录)
MODELS_DIR = paths.models_dir()               # 模块全局, 测试可覆写

# 规范模型包: 哈希即身份 —— 选择压缩包后先校验唯一哈希, 通过才安装
MODEL_PACKS = (
    {'id': 'muscriptor_small',
     'label': 'MuScriptor 多乐器模型 (small)',
     'sha256': '8fe90eaa62c9b5e83e39c5e42ba02a1afcb19d690ab62535866e11baf18aa73b',
     'target': 'muscriptor_small'},
    {'id': 'transkun',
     'label': 'Transkun 钢琴转录模型',
     'sha256': 'de777fd8dcbd7b360bdfdf972cffbadc1791af41a371e24c5ecc627cc06c4f1a',
     'target': 'transkun'},
    {'id': 'bs_roformer_sw',
     'label': 'BS-Roformer-SW 六轨分离模型',
     'sha256': 'b597fb52285bd6f5399eaba3b31e150d3d4254c6a466a901ea441f5945489ae9',
     'target': 'separation/sw'},
    {'id': 'bs_roformer_inst',
     'label': 'BS-Roformer 人声/伴奏分离模型',
     'sha256': 'f37763f56e8c759c0355b70ab567662273f361c05d326bbdab536a9d10fbd745',
     'target': 'separation/inst'},
)

_CHUNK = 262144


def _sha256_matches(path, progress_cb=None):
    """流式计算 SHA-256 (progress_cb(已完成, 总量) 可选) → 十六进制串"""
    total = os.path.getsize(path)
    done = 0
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        while True:
            b = f.read(_CHUNK)
            if not b:
                break
            h.update(b)
            done += len(b)
            if progress_cb:
                progress_cb(done, total)
    return h.hexdigest()


# 兼容旧名 (测试/外部调用)
def sha256_of_file(path, progress_cb=None):
    return _sha256_matches(path, progress_cb)


def identify(zip_path, progress_cb=None):
    """哈希 → 注册表条目; 不匹配 → _BadPack"""
    got = _sha256_matches(zip_path, progress_cb)
    for pk in MODEL_PACKS:
        if got.lower() == pk['sha256'].lower():
            return pk
    raise _BadPack(t('哈希不匹配, 不是可识别的模型压缩包: %s…' % got[:16]))


def model_status():
    """当前已安装模型 → {id: bool} (目录存在且非空)"""
    out = {}
    for pk in MODEL_PACKS:
        d = os.path.join(MODELS_DIR, pk['target'])
        out[pk['id']] = os.path.isdir(d) and bool(os.listdir(d))
    return out


def _strip_top(names):
    """全部成员同属一个顶层目录时剥离它; 返回 (归一化相对路径列表, 是否剥离)"""
    rels = [n.replace('\\', '/').lstrip('/') for n in names]
    tops = set(r.split('/')[0] for r in rels)
    if len(tops) == 1 and all('/' in r for r in rels):
        return [r.split('/', 1)[1] for r in rels], True
    return rels, False


class _BadPack(Exception):
    """哈希不匹配 —— 不是可识别的模型压缩包"""


class ModelImportWorker(QThread):
    """导入模型压缩包 (两段式: pack 未定时先识别, 已存在时发 need_confirm 等确认)
       tick(阶段, 已完成, 总量, 附言) → done(模型id) / failed(原因) / need_confirm(id)"""
    tick = Signal(str, int, int, str)
    done = Signal(str)
    failed = Signal(str)
    need_confirm = Signal(str)

    def __init__(self, zip_path, pack=None, overwrite=False, parent=None):
        super().__init__(parent)
        self.zip_path = zip_path
        self.pack = pack
        self.overwrite = overwrite
        self._abort = False

    def stop(self):
        self._abort = True

    def run(self):
        try:
            if self.pack is None:                     # 阶段① 哈希识别身份
                self.tick.emit(t('校验'), 0, 0, os.path.basename(self.zip_path))
                self.pack = identify(self.zip_path, lambda d, tt: (
                    self._abort_check(),
                    self.tick.emit(t('校验'), d, tt,
                                   os.path.basename(self.zip_path))))
            tgt = os.path.join(MODELS_DIR, self.pack['target'])
            if os.path.isdir(tgt) and os.listdir(tgt) and not self.overwrite:
                self.need_confirm.emit(self.pack['id'])
                return
            self._extract()
            self.done.emit(self.pack['id'])
        except _BadPack as e:
            self.failed.emit(str(e))
        except Exception as e:                        # 中止/磁盘/损坏 zip
            self.failed.emit(str(e))

    def _abort_check(self):
        if self._abort:
            raise KeyboardInterrupt(t('已取消'))

    def _extract(self):
        """安全解压到 models/<target>: 拒绝越界成员, 单层顶层目录剥离"""
        tgt = os.path.join(MODELS_DIR, self.pack['target'])
        tmp = tgt + '.importing'
        if os.path.isdir(tmp):
            shutil.rmtree(tmp, ignore_errors=True)
        os.makedirs(tmp, exist_ok=True)
        try:
            with zipfile.ZipFile(self.zip_path) as zf:
                members = [i for i in zf.infolist() if not i.is_dir()]
                rels, _strip = _strip_top([i.filename for i in members])
                for n, (info, rel) in enumerate(zip(members, rels)):
                    self._abort_check()
                    if rel.startswith('/') or re.match(r'^[A-Za-z]:', rel) \
                            or '..' in rel.split('/') or not rel:
                        continue
                    dst = os.path.join(tmp, *rel.split('/'))
                    d = os.path.dirname(dst)
                    if d:
                        os.makedirs(d, exist_ok=True)
                    with zf.open(info) as src, open(dst, 'wb') as out:
                        shutil.copyfileobj(src, out, _CHUNK)
                    if n % 4 == 0 or n == len(members) - 1:
                        self.tick.emit(t('安装'), n + 1, len(members),
                                       self.pack['target'])
            if os.path.isdir(tgt):                    # 旧目录原子替换
                old = tgt + '.old'
                if os.path.isdir(old):
                    shutil.rmtree(old, ignore_errors=True)
                os.rename(tgt, old)
            os.rename(tmp, tgt)
        finally:
            if os.path.isdir(tmp):
                shutil.rmtree(tmp, ignore_errors=True)
            old = tgt + '.old'
            if os.path.isdir(old):
                shutil.rmtree(old, ignore_errors=True)
