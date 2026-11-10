# -*- coding: utf-8 -*-
"""物理键盘输出层: Windows SendInput(扫描码, DirectInput 游戏可识别)
   非 Windows 平台为空实现。"""
import string
from common import IS_WIN
if IS_WIN:
    import ctypes
    from ctypes import wintypes
    _user32 = ctypes.WinDLL('user32', use_last_error=True)
    _KEYUP, _SCAN = 0x0002, 0x0008
    class _MOUSEINPUT(ctypes.Structure):
        # union 的最大成员, 决定 union 尺寸: 缺了它 sizeof(INPUT) 偏小,
        # 而 SendInput 要求 cbSize 严格等于系统 sizeof(INPUT), 否则拒绝调用
        _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG),
                    ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                    ("time", wintypes.DWORD),
                    ("dwExtraInfo", ctypes.c_void_p)]
    class _KI(ctypes.Structure):
        _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
                    ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                    ("dwExtraInfo", ctypes.c_void_p)]
    class _IN(ctypes.Structure):
        class _U(ctypes.Union):
            _fields_ = [("mi", _MOUSEINPUT), ("ki", _KI)]
        _anonymous_ = ("_u",)
        _fields_ = [("type", wintypes.DWORD), ("_u", _U)]
    _user32.SendInput.restype = wintypes.UINT
    _user32.SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(_IN), wintypes.INT)
    _VK_CACHE = {}
    def scancode_of(ch):
        """字符 → 扫描码。仅接受无需修饰键的单键。"""
        ch = ch.upper()
        if ch in _VK_CACHE: return _VK_CACHE[ch]
        vk = None
        if len(ch) == 1 and ch in string.ascii_uppercase + string.digits:
            vk = ord(ch)
        elif len(ch) == 1:
            r = _user32.VkKeyScanW(ord(ch))
            if r != -1 and not (r >> 8): vk = r & 0xFF
        sc = _user32.MapVirtualKeyW(vk, 0) if vk else 0
        _VK_CACHE[ch] = sc or None
        return _VK_CACHE[ch]
    _send_ok_last = [True]   # SendInput 失败只报一次(避免演奏中刷屏), 恢复后不再重复报
    def send_key_events(ops):
        """ops=[(扫描码,是否按下)] 一次 SendInput 原子发送, 和弦不散"""
        if not ops: return
        arr = (_IN * len(ops))()
        for i, (sc, dn) in enumerate(ops):
            a = arr[i]; a.type = 1
            a.ki.wVk = 0; a.ki.wScan = sc
            a.ki.dwFlags = _SCAN | (0 if dn else _KEYUP)
        ok = _user32.SendInput(len(ops), arr, ctypes.sizeof(_IN)) == len(ops)
        if _send_ok_last[0] and not ok:
            print(f"[keyout] SendInput 失败 {len(ops)} 事件, err={ctypes.get_last_error()}"
                  " (游戏以管理员运行时, 请以管理员身份重启本程序)")
        _send_ok_last[0] = ok
else:
    def scancode_of(ch): return None
    def send_key_events(ops): pass
class KeyboardOut:
    def __init__(self, enabled):
        self.enabled = enabled and IS_WIN
        self.down = set()
    def send(self, ops):
        if not self.enabled or not ops: return
        for sc, dn in ops:
            (self.down.add if dn else self.down.discard)(sc)
        send_key_events(ops)
    def panic(self):
        if self.enabled and self.down:
            self.send([(sc, False) for sc in list(self.down)])