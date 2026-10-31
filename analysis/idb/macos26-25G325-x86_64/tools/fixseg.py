import struct, sys, os

# Repair the segment fileoff/filesize fields of a KC-rebuilt kext Mach-O.
# tools/kc.py rewrote section offsets but left segment fileoff at the KC vmaddr,
# so IDA's Mach-O loader maps no bytes. We recompute each segment's fileoff /
# filesize from its sections (which have correct offsets).

def fix(src, dst):
    d = bytearray(open(src, 'rb').read())
    magic, cputype, cpusub, ftype, ncmds, szcmds, flags, res = struct.unpack_from('<IiiIIIII', d, 0)
    assert magic == 0xfeedfacf
    off = 32
    segs = []
    for i in range(ncmds):
        cmd, sz = struct.unpack_from('<II', d, off)
        if cmd == 0x19:  # LC_SEGMENT_64
            name = d[off+8:off+24].rstrip(b'\x00').decode()
            vmaddr, vmsize, fileoff, filesize = struct.unpack_from('<QQQQ', d, off+24)
            nsects = struct.unpack_from('<I', d, off+64)[0]
            # gather sections with nonzero file offset
            lo = None; hi = None
            so = off + 72
            for j in range(nsects):
                addr, size = struct.unpack_from('<QQ', d, so+32)
                fo = struct.unpack_from('<I', d, so+48)[0]
                if fo != 0 and size != 0:
                    # file offset corresponding to segment vmaddr
                    base = fo - (addr - vmaddr)
                    lo = base if lo is None else min(lo, base)
                    hi = (fo + size) if hi is None else max(hi, fo + size)
                so += 80
            if lo is None:
                # no file-backed section (e.g. pure zerofill or __LINKEDIT): leave alone
                segs.append((name, vmaddr, vmsize, fileoff, filesize, 'skipped'))
            else:
                newoff = lo
                newsize = hi - lo
                if newsize > vmsize:
                    newsize = vmsize
                struct.pack_into('<QQ', d, off+40, newoff, newsize)
                segs.append((name, vmaddr, vmsize, newoff, newsize, 'fixed'))
        off += sz
    open(dst, 'wb').write(bytes(d))
    for s in segs:
        print('%-14s vmaddr %016x vmsize %08x -> fileoff %08x filesize %08x [%s]' % (
            s[0], s[1], s[2], s[3], s[4], s[5]))

if __name__ == '__main__':
    fix(sys.argv[1], sys.argv[2])
