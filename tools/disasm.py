import struct, sys, capstone

PATH = r"F:\Download\Gekkou no Carnevale\system.dll"
d = open(PATH, "rb").read()

pe = struct.unpack_from("<I", d, 0x3c)[0]
nsec = struct.unpack_from("<H", d, pe + 6)[0]
optsz = struct.unpack_from("<H", d, pe + 20)[0]
opt = pe + 24
magic = struct.unpack_from("<H", d, opt)[0]
imgbase = struct.unpack_from("<I", d, opt + 28)[0]
ddoff = opt + (96 if magic == 0x10b else 112)
imp_rva, imp_sz = struct.unpack_from("<II", d, ddoff + 8)

secs = []
so = opt + optsz
for i in range(nsec):
    b = so + i * 40
    name = d[b:b + 8].rstrip(b'\0').decode('latin1')
    vs, va, rs, ra = struct.unpack_from("<IIII", d, b + 8)
    secs.append((name, va, vs, ra, rs))


def r2o(rva):
    for nm, va, vs, ra, rs in secs:
        if va <= rva < va + max(vs, rs):
            return ra + (rva - va)
    return None


# ---- imports: IAT slot VA -> name
iat = {}
o = r2o(imp_rva)
while True:
    ilt, ts, fc, nm, iat_rva = struct.unpack_from("<IIIII", d, o)
    if nm == 0:
        break
    dll = d[r2o(nm):].split(b'\0')[0].decode()
    t = r2o(ilt or iat_rva)
    slot = iat_rva
    while True:
        v = struct.unpack_from("<I", d, t)[0]
        if v == 0:
            break
        if v & 0x80000000:
            fn = "ord#%d" % (v & 0xffff)
        else:
            fn = d[r2o(v) + 2:].split(b'\0')[0].decode()
        iat[imgbase + slot] = "%s!%s" % (dll, fn)
        t += 4
        slot += 4
    o += 20

md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_32)
md.detail = True

start_rva = int(sys.argv[1], 16) if len(sys.argv) > 1 else 0x48900
count = int(sys.argv[2]) if len(sys.argv) > 2 else 400
start_off = r2o(start_rva)
code = d[start_off:start_off + count * 8 + 64]

labels = set()
insns = list(md.disasm(code, imgbase + start_rva))
out = []
for ins in insns[:count]:
    text = ins.mnemonic + " " + ins.op_str
    ann = ""
    # resolve memory operand that hits the IAT
    for op in ins.operands:
        if op.type == capstone.x86.X86_OP_MEM and op.mem.base == 0 and op.mem.index == 0:
            va = op.mem.disp
            if va in iat:
                ann = "   ; " + iat[va]
    # note direct call/jmp targets inside the module
    if ins.mnemonic in ("call", "jmp") and ins.op_str.startswith("0x"):
        tgt = int(ins.op_str, 16)
        if imgbase <= tgt < imgbase + 0x104000:
            ann = (ann + "  ->rva 0x%x" % (tgt - imgbase)) if ann else ("   ; ->rva 0x%x" % (tgt - imgbase))
    out.append("0x%08x  %-42s%s" % (ins.address, text, ann))

print("\n".join(out))
