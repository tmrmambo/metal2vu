"""Write the x86_64 slice of a universal Mach-O to its own file."""
import struct
import sys


def thin(src, dst, want=0x01000007, want_sub=None):
    data = open(src, 'rb').read()
    magic = struct.unpack('>I', data[:4])[0]
    if magic not in (0xCAFEBABE, 0xCAFEBABF):
        raise SystemExit('%s is not a universal binary' % src)
    wide = magic == 0xCAFEBABF
    n = struct.unpack('>I', data[4:8])[0]
    recsz = 32 if wide else 20
    for i in range(n):
        r = data[8 + i * recsz: 8 + (i + 1) * recsz]
        if wide:
            ct, cs, off, size, _al = struct.unpack('>iiQQI', r[:28])
        else:
            ct, cs, off, size, _al = struct.unpack('>iiIII', r)
        if (ct & 0xFFFFFFFF) == want and (want_sub is None or (cs & 0xFFFFFF) == want_sub):
            open(dst, 'wb').write(data[off:off + size])
            print('%s -> %s  slice off=%d size=%d cpusubtype=%d' % (src, dst, off, size, cs & 0xFFFFFF))
            return
    raise SystemExit('no matching slice in %s' % src)


if __name__ == '__main__':
    thin(sys.argv[1], sys.argv[2])
