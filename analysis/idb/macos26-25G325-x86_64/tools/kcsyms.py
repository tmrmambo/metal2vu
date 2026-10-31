import struct, os, sys, json

def macho_info(path):
    d = open(path, 'rb').read()
    magic = struct.unpack_from('<I', d, 0)[0]
    if magic != 0xfeedfacf:
        return None
    ncmds = struct.unpack_from('<I', d, 16)[0]
    off = 32
    segs = []
    syms = []
    for i in range(ncmds):
        cmd, sz = struct.unpack_from('<II', d, off)
        if cmd == 0x19:
            name = d[off+8:off+24].rstrip(b'\x00').decode(errors='replace')
            vmaddr, vmsize, fileoff, filesize = struct.unpack_from('<QQQQ', d, off+24)
            segs.append((name, vmaddr, vmsize))
        elif cmd == 2:
            symoff, nsyms, stroff, strsize = struct.unpack_from('<IIII', d, off+8)
            for k in range(nsyms):
                o = symoff + k*16
                strx, ntype, sect, desc = struct.unpack_from('<IBBH', d, o)
                value = struct.unpack_from('<Q', d, o+8)[0]
                if (ntype & 0x0e) == 0x0e and value:   # N_SECT
                    e = d.index(b'\x00', stroff+strx)
                    syms.append((value, d[stroff+strx:e].decode(errors='replace')))
        off += sz
    return segs, syms

ROOT = r'c:\Users\viola\Documents\KVM MacOS\analysis\binaries\macos26-25G325-x86_64'
files = []
kd = os.path.join(ROOT, 'kext')
for f in sorted(os.listdir(kd)):
    if f.startswith('com.apple'):
        files.append(os.path.join(kd, f))
files.append(os.path.join(ROOT, 'kernel', 'kernel.x86_64'))

allsyms = {}
for p in files:
    r = macho_info(p)
    if not r:
        print('skip', p); continue
    segs, syms = r
    print('%-44s %s' % (os.path.basename(p), ' '.join('%s@%x+%x' % s for s in segs)))
    print('   nsyms %d  minval %x  maxval %x' % (len(syms), min(s[0] for s in syms), max(s[0] for s in syms)))
    for v, n in syms:
        allsyms.setdefault(v, n)

json.dump({'%x' % k: v for k, v in allsyms.items()},
          open(os.path.join(os.environ['TEMP'], 'kvmmacos-apv-x86', 'kcsyms.json'), 'w'))
print('total symbols', len(allsyms))
