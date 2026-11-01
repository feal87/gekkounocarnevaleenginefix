import ctypes as C
from ctypes import wintypes as W
import sys, time

u = C.WinDLL('user32')
k = C.WinDLL('kernel32')
u.SetProcessDpiAwarenessContext(C.c_void_p(-4))

class RECT(C.Structure):
    _fields_ = [("L", C.c_long), ("T", C.c_long), ("R", C.c_long), ("B", C.c_long)]

class GTI(C.Structure):
    _fields_ = [("cbSize", C.c_uint), ("flags", C.c_uint), ("hwndActive", C.c_void_p), ("hwndFocus", C.c_void_p),
                ("hwndCapture", C.c_void_p), ("hwndMenuOwner", C.c_void_p), ("hwndMoveSize", C.c_void_p),
                ("hwndCaret", C.c_void_p), ("rcCaret", RECT)]

class TE32(C.Structure):
    _fields_ = [("dwSize", C.c_uint), ("cntUsage", C.c_uint), ("th32ThreadID", C.c_uint),
                ("th32OwnerProcessID", C.c_uint), ("tpBasePri", C.c_long), ("tpDeltaPri", C.c_long),
                ("dwFlags", C.c_uint)]

u.GetGUIThreadInfo.argtypes = [C.c_uint, C.POINTER(GTI)]
u.GetClassNameW.argtypes = [C.c_void_p, C.c_wchar_p, C.c_int]
u.GetWindowThreadProcessId.argtypes = [C.c_void_p, C.POINTER(C.c_uint)]
EN = C.WINFUNCTYPE(C.c_bool, C.c_void_p, C.c_void_p)

def cls(h):
    if not h:
        return "-"
    b = C.create_unicode_buffer(100); u.GetClassNameW(C.c_void_p(h), b, 100); return b.value

def snapshot(pid, main_tid):
    snap = k.CreateToolhelp32Snapshot(0x4, 0)
    te = TE32(); te.dwSize = C.sizeof(TE32)
    tids = []
    if k.Thread32First(snap, C.byref(te)):
        while True:
            if te.th32OwnerProcessID == pid:
                tids.append(te.th32ThreadID)
            if not k.Thread32Next(snap, C.byref(te)):
                break
    k.CloseHandle(snap)
    rows = []
    for t in tids:
        g = GTI(); g.cbSize = C.sizeof(GTI)
        if not u.GetGUIThreadInfo(t, C.byref(g)):
            continue
        if (g.hwndActive or g.hwndFocus or g.hwndCapture or g.hwndMenuOwner or g.hwndMoveSize or g.flags):
            rows.append((t, int(g.hwndActive or 0), int(g.hwndFocus or 0), int(g.hwndCapture or 0), g.flags,
                         t == main_tid))
    return rows

main = [0]
def cb(w, l):
    if cls(w) == "OCGameApplicationWindow" and u.IsWindowVisible(w):
        main[0] = int(w)
    return True
u.EnumWindows(EN(cb), None)
if not main[0]:
    print("game not running"); sys.exit(1)
pid = C.c_uint()
main_tid = u.GetWindowThreadProcessId(C.c_void_p(main[0]), C.byref(pid))
print("watching pid %d main tid %d main hwnd 0x%X" % (pid.value, main_tid, main[0]))
print("click the game, open settings, close it  (120s)")
sys.stdout.flush()

last = None
t0 = time.time()
while time.time() - t0 < 120:
    rows = snapshot(pid.value, main_tid)
    sig = tuple((r[0], r[1], r[2], r[3], r[4]) for r in rows)
    if sig != last:
        last = sig
        ts = time.time() - t0
        sharing = {}
        for r in rows:
            if r[1]:
                sharing.setdefault(r[1], []).append(r[0])
        attached = {kk: v for kk, v in sharing.items() if len(v) > 1}
        print("%7.2fs  threads_state:" % ts)
        for t, act, foc, cap, fl, ismain in rows:
            print("            tid %-6d%s active=0x%-8X[%s] focus=0x%-8X capture=0x%X flags=0x%X" %
                  (t, " (MAIN)" if ismain else "       ", act, cls(act), foc, cap, fl))
        print("            => %s" % ("ATTACHED! " + str(attached) if attached
                                     else ("single thread" if rows else "no focus (game not foreground)")))
        sys.stdout.flush()
    time.sleep(0.1)
print("done")
