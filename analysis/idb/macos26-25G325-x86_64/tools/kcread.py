"""Offline reader over the whole set of KC-rebuilt kexts.

Maps a kernel-collection VA to (file, file offset), reads qwords, decodes
DYLD_CHAINED_PTR_64_KERNEL_CACHE values (target = raw & 0x3FFFFFFF, cacheLevel =
bits 30..31) and resolves them against the merged symbol table.
"""
import struct, os, bisect, json, sys

ROOT = r'c:\Users\viola\Documents\KVM MacOS\analysis\binaries\macos26-25G325-x86_64'

class Img:
    def __init__(self, path):
        self.path = path
        self.data = open(path, 'rb').read()
        self.name = os.path.basename(path)
        self.sects = []   # (vmaddr, size, fileoff)
        self.syms = []
        d = self.data
        ncmds = struct.unpack_from('<I', d, 16)[0]
        off = 32
        for i in range(ncmds):
            cmd, sz = struct.unpack_from('<II', d, off)
            if cmd == 0x19:
                nsects = struct.unpack_from('<I', d, off+64)[0]
                so = off + 72
                for j in range(nsects):
                    addr, size = struct.unpack_from('<QQ', d, so+32)
                    fo = struct.unpack_from('<I', d, so+48)[0]
                    if fo and size:
                        self.sects.append((addr, size, fo))
                    so += 80
            elif cmd == 2:
                symoff, nsyms, stroff, strsize = struct.unpack_from('<IIII', d, off+8)
                for k in range(nsyms):
                    o = symoff + k*16
                    strx, ntype, sect, desc = struct.unpack_from('<IBBH', d, o)
                    value = struct.unpack_from('<Q', d, o+8)[0]
                    if (ntype & 0x0e) == 0x0e and value:
                        e = d.index(b'\x00', stroff+strx)
                        self.syms.append((value, d[stroff+strx:e].decode(errors='replace')))
            off += sz
    def fo(self, va):
        for a, s, f in self.sects:
            if a <= va < a+s:
                return f + (va-a)
        return None

IMGS = []
kd = os.path.join(ROOT, 'kext')
for f in sorted(os.listdir(kd)):
    if f.startswith('com.apple'):
        IMGS.append(Img(os.path.join(kd, f)))
IMGS.append(Img(os.path.join(ROOT, 'kernel', 'kernel.x86_64')))

SYM = {}
for im in IMGS:
    for v, n in im.syms:
        SYM.setdefault(v, n)
KEYS = sorted(SYM)

def sym(a, win=0x800):
    if a in SYM:
        return SYM[a]
    i = bisect.bisect_right(KEYS, a)-1
    if i >= 0 and 0 < a-KEYS[i] < win:
        return '%s+0x%x' % (SYM[KEYS[i]], a-KEYS[i])
    return None

def symea(name):
    for v, n in SYM.items():
        if n == name:
            return v
    return None

def raw_q(va):
    for im in IMGS:
        f = im.fo(va)
        if f is not None:
            return struct.unpack_from('<Q', im.data, f)[0], im.name
    return None, None

def ptr(va):
    """decode a chained-fixup pointer slot at va -> (target, cacheLevel, symbol)"""
    r, who = raw_q(va)
    if r is None:
        return None
    t = r & 0x3FFFFFFF
    lvl = (r >> 30) & 3
    return (t, lvl, sym(t), who)

def bytes_at(va, n):
    for im in IMGS:
        f = im.fo(va)
        if f is not None:
            return im.data[f:f+n]
    return None

def vtable(name, n=400, start=0):
    """dump a vtable symbol; slot i is at vtable_symbol + 16 + 8*i"""
    base = symea(name)
    if base is None:
        print('no symbol', name); return
    out = []
    for i in range(start, n):
        va = base + 16 + 8*i
        p = ptr(va)
        if p is None:
            break
        out.append((i, hex(16+8*i), hex(p[0]), p[2]))
    return out

if __name__ == '__main__':
    pass

# ---- resolution bases ------------------------------------------------------
# cacheLevel 1 targets are System KC VAs (resolve directly).
# cacheLevel 0 targets are boot-side; two deltas both produce exact hits:
#   +0xffffff8000018000 -> /System/Library/Kernels/kernel link address
#   +0xffffff8000100000 -> BootKernelExtensions.kc base (boot kexts)
KBASE = 0xffffff8000018000
BBASE = 0xffffff8000100000

def rsym(t, lvl=None):
    """Resolve a decoded chained-fixup target to a symbol, trying all bases."""
    for cand in (t, t + KBASE, t + BBASE):
        s = SYM.get(cand)
        if s:
            return s
    best = None
    for cand, tag in ((t, ''), (t + KBASE, 'K'), (t + BBASE, 'B')):
        s = sym(cand, 0x200)
        if s and (best is None):
            best = s
    return best

def rptr(va):
    p = ptr(va)
    if p is None:
        return None
    return (hex(p[0]), p[1], rsym(p[0], p[1]))

def vt(name, n=400, start=0):
    base = symea(name)
    if base is None:
        print('no symbol', name); return []
    out = []
    for i in range(start, n):
        va = base + 16 + 8*i
        p = ptr(va)
        if p is None:
            break
        out.append((i, '0x%x' % (16+8*i), hex(p[0]), p[1], rsym(p[0], p[1])))
    return out


def vt2(name, n=420):
    """vtable dump keyed by vptr offset (what `call [rax+off]` shows).
       slot i lives at symbol+0x10+8*i, i.e. vptr offset 8*i."""
    base = symea(name)
    if base is None:
        print('no symbol', name); return []
    out = []
    for i in range(n):
        p = ptr(base + 16 + 8*i)
        if p is None:
            break
        out.append({'i': i, 'vptr_off': '0x%x' % (8*i), 'sym_off': '0x%x' % (16+8*i),
                    'target': hex(p[0]), 'name': rsym(p[0], p[1])})
    return out

def slot(name, vptr_off):
    v = vt2(name)
    i = vptr_off // 8
    return v[i] if i < len(v) else None


# ---- per-segment delta learning -------------------------------------------
# The collection groups segments by kind, so each (image, segment) pair sits at
# its own delta from the stand-alone image's link address. Learn the delta set
# empirically from a sample of real fixup targets.
from collections import Counter
_DELTAS = None

def learn_deltas(targets, min_hits=3):
    global _DELTAS
    vals = list(SYM.keys())
    c = Counter()
    for t in targets:
        for v in vals:
            d = v - t
            if d >= 0 and (d & 0xFFF) == 0:
                c[d] += 1
    _DELTAS = [d for d, n in c.most_common() if n >= min_hits]
    return c.most_common(30)

def xsym(t):
    """Resolve a decoded target using the learned delta set; exact hits only."""
    if t in SYM:
        return SYM[t]
    if _DELTAS:
        for d in _DELTAS:
            if t + d in SYM:
                return SYM[t + d]
    return None

def xsym_near(t, win=0x400):
    s = xsym(t)
    if s:
        return s
    best = None
    for d in ([0] + (_DELTAS or [])):
        c = t + d
        i = bisect.bisect_right(KEYS, c) - 1
        if i >= 0 and 0 < c - KEYS[i] < win:
            cand = '%s+0x%x' % (SYM[KEYS[i]], c - KEYS[i])
            if best is None:
                best = cand
    return best
