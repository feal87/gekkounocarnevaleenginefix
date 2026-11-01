import struct, ctypes as C
from ctypes import wintypes as W
import sys

PID = int(sys.argv[1])
dlls = [r"F:\Download\Gekkou no Carnevale\system.dll",
        r"F:\Download\Gekkou no Carnevale\GekkounoCarnevale.exe"]

k = C.WinDLL('kernel32')
k.OpenProcess.restype = C.c_void_p
k.OpenProcess.argtypes = [C.c_uint, C.c_int, C.c_uint]
k.ReadProcessMemory.argtypes = [C.c_void_p, C.c_void_p, C.c_void_p, C.c_size_t, C.POINTER(C.c_size_t)]
h = k.OpenProcess(0x1F0FFF, 0, PID)
if not h:
    print("OpenProcess failed", C.get_last_error()); sys.exit(1)

def rd(addr, n):
    buf = C.create_string_buffer(n)
    got = C.c_size_t(0)
    if not k.ReadProcessMemory(h, C.c_void_p(addr), buf, n, C.byref(got)):
        return None
    return buf.raw[:got.value]

rows = []
for path in dlls:
    d = open(path, "rb").read()
    pe = struct.unpack_from("<I", d, 0x3c)[0]
    nsec = struct.unpack_from("<H", d, pe + 6)[0]
    optsz = struct.unpack_from("<H", d, pe + 20)[0]
    opt = pe + 24
    imgbase = struct.unpack_from("<I", d, opt + 28)[0]
    magic = struct.unpack_from("<H", d, opt)[0]
    ddoff = opt + (96 if magic == 0x10b else 112)
    imp_rva = struct.unpack_from("<I", d, ddoff + 8)[0]
    secs = []
    so = opt + optsz
    for i in range(nsec):
        b = so + i * 40
        vs, va, rs, ra = struct.unpack_from("<IIII", d, b + 8)
        secs.append((va, vs, ra, rs))

    def r2o(rva):
        for va, vs, ra, rs in secs:
            if va <= rva < va + max(vs, rs):
                return ra + (rva - va)
        return None

    o = r2o(imp_rva)
    while True:
        ilt, ts, fc, nm, iat_rva = struct.unpack_from("<IIIII", d, o)
        if nm == 0:
            break
        dll = d[r2o(nm):].split(b'\0')[0].decode().lower()
        t = r2o(ilt or iat_rva)
        slot = imgbase + iat_rva
        while True:
            v = struct.unpack_from("<I", d, t)[0]
            if v == 0:
                break
            if not (v & 0x80000000):
                fn = d[r2o(v) + 2:].split(b'\0')[0].decode()
                raw = rd(slot, 4)
                addr = struct.unpack("<I", raw)[0] if raw else 0
                rows.append((dll, fn, addr))
            t += 4; slot += 4
        o += 20

want = ("SetCapture Capture ClipCursor CursorPos ShowWindow EnableWindow SetForegroundWindow "
        "SetActiveWindow SetFocus SetWindowPos SetWindowLong CreateWindowEx DestroyWindow TrackPopup "
        "DialogBoxParam CreateDialogParam EndDialog MessageBox SetTimer KillTimer BlockInput "
        "ShowCursor SetCooperativeLevel SetThreadDesktop SetWindowRgn SetMenu").split()

seen = set()
for dll, fn, addr in rows:
    if any(w.lower() in fn.lower() for w in want) and (dll, fn) not in seen:
        seen.add((dll, fn))
        print("%-14s %-24s 0x%08X" % (dll, fn, addr))
print("\ntotal imports scanned:", len(rows))
