import ctypes as C
from ctypes import wintypes as W

u = C.WinDLL('user32', use_last_error=True)
k = C.WinDLL('kernel32')
u.SetProcessDpiAwarenessContext(C.c_void_p(-4))

class RECT(C.Structure):
    _fields_ = [("L", C.c_long), ("T", C.c_long), ("R", C.c_long), ("B", C.c_long)]

class GUITHREADINFO(C.Structure):
    _fields_ = [("cbSize", C.c_uint), ("flags", C.c_uint), ("hwndActive", C.c_void_p),
                ("hwndFocus", C.c_void_p), ("hwndCapture", C.c_void_p), ("hwndMenuOwner", C.c_void_p),
                ("hwndMoveSize", C.c_void_p), ("hwndCaret", C.c_void_p), ("rcCaret", RECT)]

u.GetWindowThreadProcessId.argtypes = [C.c_void_p, C.POINTER(C.c_uint)]
u.GetGUIThreadInfo.argtypes = [C.c_uint, C.POINTER(GUITHREADINFO)]
u.SendMessageW.restype = C.c_ssize_t
u.SendMessageW.argtypes = [C.c_void_p, C.c_uint, C.c_size_t, C.c_size_t]
u.GetCursorPos.argtypes = [C.POINTER(W.POINT)]
u.WindowFromPoint.restype = C.c_void_p
u.WindowFromPoint.argtypes = [W.POINT]
u.GetClassNameW.argtypes = [C.c_void_p, C.c_wchar_p, C.c_int]
u.GetWindowRect.argtypes = [C.c_void_p, C.POINTER(RECT)]
u.GetForegroundWindow.restype = C.c_void_p
u.GetCapture.restype = C.c_void_p
u.GetFocus.restype = C.c_void_p
u.GetActiveWindow.restype = C.c_void_p
u.GetClassNameW.restype = C.c_int

EN = C.WINFUNCTYPE(C.c_bool, C.c_void_p, C.c_void_p)
found = []
def cb(w, l):
    b = C.create_unicode_buffer(64); u.GetClassNameW(w, b, 64)
    if b.value == "OCGameApplicationWindow" and u.IsWindowVisible(w):
        found.append(int(w))
    return True
u.EnumWindows(EN(cb), None)

def cname(h):
    if not h: return "-"
    b = C.create_unicode_buffer(64); u.GetClassNameW(C.c_void_p(h), b, 64)
    return b.value

FL = {0x1: "GUI_INMOVESIZE", 0x2: "GUI_INMENUMODE", 0x4: "GUI_SYSTEMMENUMODE",
      0x8: "GUI_POPUPMENUMODE", 0x10: "GUI_16BITTASK", 0x20: "GUI_NOFLAGS"}

for w in found:
    h = C.c_void_p(w)
    tid = u.GetWindowThreadProcessId(h, None)
    gti = GUITHREADINFO(); gti.cbSize = C.sizeof(GUITHREADINFO)
    ok = u.GetGUIThreadInfo(tid, C.byref(gti))
    r = RECT(); u.GetWindowRect(h, C.byref(r))
    p = W.POINT(); u.GetCursorPos(C.byref(p))
    print("hwnd 0x%X  tid %d  rect (%d,%d)-(%d,%d)  cursor (%d,%d)" % (w, tid, r.L, r.T, r.R, r.B, p.x, p.y))
    print("  foreground   : 0x%X  (%s)" % (u.GetForegroundWindow() or 0, cname(u.GetForegroundWindow())))
    print("  GetGUIThreadInfo ok=%s" % bool(ok))
    if ok:
        f = gti.flags
        names = [v for kk, v in FL.items() if f & kk] or ["(none)"]
        print("  flags        : 0x%X  %s" % (f, " | ".join(names)))
        for fld in ("hwndActive", "hwndFocus", "hwndCapture", "hwndMenuOwner", "hwndMoveSize", "hwndCaret"):
            v = getattr(gti, fld) or 0
            print("  %-13s: 0x%08X  %s" % (fld, v, cname(v) if v else "-"))
    print("  this-thread  : GetCapture=0x%X  GetFocus=0x%X  GetActiveWindow=0x%X" %
          (u.GetCapture() or 0, u.GetFocus() or 0, u.GetActiveWindow() or 0))
    print("  WindowFromPoint(cursor) : 0x%X  %s" % (u.WindowFromPoint(p) or 0, cname(u.WindowFromPoint(p))))
    print("  IsWindowEnabled=%s IsWindowVisible=%s IsHung=%s" %
          (bool(u.IsWindowEnabled(h)), bool(u.IsWindowVisible(h)), bool(u.IsHungAppWindow(h))))
    cx = (r.L + r.R) // 2
    for lbl, x, y in [("caption", cx, r.T + 8), ("client", cx, (r.T + r.B) // 2)]:
        v = u.SendMessageW(h, 0x0084, 0, ((y << 16) | (x & 0xffff)) & 0xffffffff)
        print("  NCHITTEST %-8s (%4d,%4d) -> %d" % (lbl, x, y, v))
