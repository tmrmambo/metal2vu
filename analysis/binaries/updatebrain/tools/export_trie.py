#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Parse the Mach-O export trie (the ground truth for `nm -gU`) of a thin
x86_64 Mach-O. Used to enumerate the full exported-symbol surface of
UpdateBrainLibrary's x86_64 slice.
"""
import struct
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

LC_DYLD_INFO = 0x22
LC_DYLD_INFO_ONLY = 0x80000022
LC_DYLD_EXPORTS_TRIE = 0x80000033
LC_SYMTAB = 0x02


def uleb(b, o):
    r = 0
    s = 0
    while True:
        c = b[o]
        o += 1
        r |= (c & 0x7F) << s
        if not (c & 0x80):
            break
        s += 7
    return r, o


def read_trie(data, base, out, prefix=""):
    # iterative to avoid recursion limits
    stack = [(base, prefix)]
    while stack:
        off, pfx = stack.pop()
        o = off
        term_size, o = uleb(data, o)
        if term_size:
            flags, o2 = uleb(data, o)
            addr, o2 = uleb(data, o2)
            out.append((pfx, flags, addr))
        o = off + 1 + term_size
        nchild = data[o]
        o += 1
        for _ in range(nchild):
            end = data.index(0, o)
            edge = data[o:end].decode("utf-8", "replace")
            o = end + 1
            child_off, o = uleb(data, o)
            stack.append((base + child_off, pfx + edge))


def main(path):
    data = open(path, "rb").read()
    magic = struct.unpack_from("<I", data, 0)[0]
    assert magic == 0xFEEDFACF, f"not thin 64-bit macho: {magic:#x}"
    ncmds = struct.unpack_from("<I", data, 16)[0]
    p = 32
    exp_off = exp_size = 0
    for _ in range(ncmds):
        cmd, cmdsize = struct.unpack_from("<II", data, p)
        if cmd in (LC_DYLD_INFO, LC_DYLD_INFO_ONLY):
            # export off/size are last two u32 of the 48-byte cmd
            exp_off, exp_size = struct.unpack_from("<II", data, p + 40)
        elif cmd == LC_DYLD_EXPORTS_TRIE:
            exp_off, exp_size = struct.unpack_from("<II", data, p + 8)
        p += cmdsize
    print(f"export trie: off={exp_off} size={exp_size}")
    if not exp_off:
        print("no export trie")
        return
    trie = data[exp_off:exp_off + exp_size]
    out = []
    read_trie(trie, 0, out)
    out.sort()
    print(f"exported symbols: {len(out)}")
    objc_cls = [s for s in out if s[0].startswith("_OBJC_CLASS_$")]
    objc_meta = [s for s in out if s[0].startswith("_OBJC_METACLASS_$")]
    objc_ivar = [s for s in out if s[0].startswith("_OBJC_IVAR_$")]
    cfn = [s for s in out if not s[0].startswith("_OBJC_")]
    print(f"  _OBJC_CLASS_$:     {len(objc_cls)}")
    print(f"  _OBJC_METACLASS_$: {len(objc_meta)}")
    print(f"  _OBJC_IVAR_$:      {len(objc_ivar)}")
    print(f"  other (C etc):     {len(cfn)}")
    print("=== non-ObjC exports ===")
    for name, flags, addr in cfn:
        print(f"  {addr:#010x}  flags={flags:#x}  {name}")
    print("=== _OBJC_CLASS_$ exports (first 60) ===")
    for name, flags, addr in objc_cls[:60]:
        print(f"  {addr:#010x}  {name}")
    if len(objc_cls) > 60:
        print(f"  ... (+{len(objc_cls)-60})")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else
         "analysis/binaries/updatebrain/UpdateBrainLibrary.x86_64.dylib")
