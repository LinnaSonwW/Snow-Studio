# -*- coding: utf-8 -*-
"""标尺右键标记冒烟测试: BPM 标记(曲中/撤销) + 调性标注(联动/持久化) + 右键路由"""
import os, sys, faulthandler
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'app'))

from PySide6.QtWidgets import QApplication, QFileDialog, QMenu
from PySide6.QtCore import QPointF, Qt, QEvent
from PySide6.QtGui import QMouseEvent
app = QApplication([])
QFileDialog.getOpenFileName = staticmethod(
    lambda *a, **k: (os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                  '_smoke.mid'), ''))

from mainwindow import MainWindow
import settings_store as store
_side = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     '_smoke.mid.snowproj.json')
if os.path.isfile(_side):
    os.remove(_side)               # (工程轮) 清陈旧伴生: 擦洗断言要求从 0 前进
mw = MainWindow(); mw.resize(1200, 800); mw.show()
mw.open_midi()
mw._ui_timer.stop()
mw._open_editor()
ed = mw.edit_roll
import project_session as _ps   # (工程轮) 断言用
tmap = mw.tmap
tpb = tmap.tpb

# 1. 开关属性 + 调性归 1=C (存档可能有残留, 先归零保证确定性)
mw._set_key_label('1=C')
assert mw.key_label == '1=C'
assert hasattr(ed, '_show_ruler_menu'), '标尺右键菜单方法应存在'

# 2. BPM 标记 (曲中插入): tick 960 无速度事件 → 插入新速度段
bpm0 = tmap.bpm_at_tick(960)
ed._apply_mark_bpm(960, 96.0)
assert abs(tmap.bpm_at_tick(960) - 96.0) < 0.01, \
    f'标记后应 96, 实得 {tmap.bpm_at_tick(960)}'
assert abs(tmap.bpm_at_tick(0) - bpm0) < 0.01, '前段速度不应受影响'

# 3. 撤销一步还原 (tempo 撤销栈现成)
mw._edit_undo()
assert abs(tmap.bpm_at_tick(960) - bpm0) < 0.01, '撤销应还原 BPM'

# 4. 原地修改: tick 0 已有速度事件 → 原地改不新增
n_events = len(tmap.events())
ed._apply_mark_bpm(0, 96.0)
assert len(tmap.events()) == n_events, '原地修改不应新增速度事件'
assert abs(tmap.bpm_at_tick(0) - 96.0) < 0.01
ed._apply_mark_bpm(0, bpm0)
assert abs(tmap.bpm_at_tick(0) - bpm0) < 0.01

# 5. 调性标注: 属性 + 悬浮谱标签 + 持久化 三处一致
mw._toggle_score_float(True)
sf = mw.score_float
ed._apply_mark_key('1=G')
assert mw.key_label == '1=G' and sf.lb_key.text() == '1=G'
mw._save_cfg()
_, _, params = store.load_settings()
assert params['key_label'] == '1=G', '调性应持久化'
ed._apply_mark_key('1=C')
assert mw.key_label == '1=C' and sf.lb_key.text() == '1=C'

# 6. 标尺右键路由 (popup + triggered): 右键标尺 → 菜单 3 项 → 用户选项分发
before_notes = len(mw.raw_notes)
record = []
ed._mark_bpm = lambda tick: record.append(('bpm', tick))
ed._mark_meter = lambda tick: record.append(('meter', tick))
ed._mark_key = lambda: record.append('key')
class _FakeSignal:
    def __init__(self):
        self._slots = []
    def connect(self, fn):
        self._slots.append(fn)
    def emit(self, *a):
        for fn in list(self._slots):
            fn(*a)
class _FakeAction:
    def __init__(self, tag):
        self.tag = tag
        self.triggered = _FakeSignal()
    def setEnabled(self, on): pass
    def trigger(self):
        self.triggered.emit()
actions = []
def _fake_addAction(self, *a, **k):
    act = _FakeAction('item%d' % len(actions))
    actions.append(act)
    return act
QMenu.addAction = _fake_addAction
from PySide6.QtCore import QPointF, Qt, QEvent
from PySide6.QtGui import QMouseEvent

# 6a. 右键标尺 → popup 菜单 3 项, 不触发任何标记
ev = QMouseEvent(QEvent.MouseButtonPress, QPointF(300, 10),
                 Qt.RightButton, Qt.RightButton, Qt.NoModifier)
ed.mousePressEvent(ev)
assert len(actions) == 3, f'菜单应弹出 3 项, 实得 {len(actions)}'
assert record == [], '弹出菜单不应直接触发标记'

# 6b. 选第一项 (标记 BPM): tick = 点击位置换算
actions[0].trigger()
expect_tick = max(0, int(round(ed.tick_of_x(300))))
assert record and record[0][0] == 'bpm' and record[0][1] == expect_tick,     f'选 BPM 应标记 {expect_tick} ticks, 实得 {record[-1:]}'

# 6c. 选第二项 (标记节拍): 全曲拍号变更 (曲中分段二期)
actions[1].trigger()
assert record[-1] == ('meter', expect_tick), f'选节拍应调 _mark_meter({expect_tick}), 实得 {record[-1:]}'

# 6d. 选第三项 (标记调性)
actions[2].trigger()
assert record[-1] == 'key', f'选调性应调 _mark_key, 实得 {record[-1:]}'

# 6e. 误删防护: 标尺右键不删音符
assert len(mw.raw_notes) == before_notes, '标尺右键不应删除音符'

# 7. 擦洗全链: 左键标尺 press → move → release → 播放头/cur_sec 跟随
sec0 = mw.cur_sec
ph_roll0 = ed.playhead_tick if hasattr(ed, 'playhead_tick') else None
ev = QMouseEvent(QEvent.MouseButtonPress, QPointF(120, 10),
                 Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
ed.mousePressEvent(ev)
assert ed._drag and ed._drag[0] == 'scrub', '左键标尺应进入擦洗'
ev = QMouseEvent(QEvent.MouseMove, QPointF(420, 10),
                 Qt.NoButton, Qt.LeftButton, Qt.NoModifier)
ed.mouseMoveEvent(ev)
ev = QMouseEvent(QEvent.MouseButtonRelease, QPointF(420, 10),
                 Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
ed.mouseReleaseEvent(ev)
assert mw.cur_sec > sec0, f'擦洗后 cur_sec 应前进, {sec0} → {mw.cur_sec}'
assert ed._drag is None, '释放后擦洗手势应结束'
# 悬浮谱指针跟随 (同一 playhead 数据源)
ph_float = sf.strip.roll.playhead_tick
assert ph_float and ph_float > 0, f'悬浮谱指针应跟随, 实得 {ph_float}'

print('RULER-MARK OK: 标尺标记冒烟 7 组全部通过')
mw.edit_session.mark_saved()                      # 免 close 确认弹窗挂起
mw.close()
