"""Mach-O header / LC_UUID / arch reporting, plus SHA-256, with no guessing."""
import hashlib
import os
import struct

FAT_MAGIC = 0xCAFEBABE
FAT_MAGIC_64 = 0xCAFEBABF
MH_MAGIC = 0xFEEDFACE
MH_MAGIC_64 = 0xFEEDFACF
MH_CIGAM = 0xCEFAEDFE
MH_CIGAM_64 = 0xCFFAEDFE

CPU = {
    7: 'i386',
    0x01000007: 'x86_64',
    12: 'arm',
    0x0100000C: 'arm64',
    0x0200000C: 'arm64_32',
}
X86_SUB = {3: 'ALL', 4: 'ARCH1/486SX', 8: 'H (Haswell, x86_64h)'}
ARM64_SUB = {0: 'ALL', 1: 'V8', 2: 'E (arm64e)'}
FILETYPE = {
    1: 'MH_OBJECT', 2: 'MH_EXECUTE', 3: 'MH_FVMLIB', 4: 'MH_CORE',
    5: 'MH_PRELOAD', 6: 'MH_DYLIB', 7: 'MH_DYLINKER', 8: 'MH_BUNDLE',
    9: 'MH_DYLIB_STUB', 10: 'MH_DSYM', 11: 'MH_KEXT_BUNDLE',
    12: 'MH_FILESET', 13: 'MH_GPU_EXECUTE', 14: 'MH_GPU_DYLIB',
}

LC_UUID = 0x1B
LC_ID_DYLIB = 0x0D
LC_SOURCE_VERSION = 0x2A
LC_BUILD_VERSION = 0x32
LC_VERSION_MIN_MACOSX = 0x24
LC_FILESET_ENTRY = 0x80000035
PLATFORM = {1: 'macOS', 2: 'iOS', 3: 'tvOS', 4: 'watchOS', 6: 'macCatalyst',
            8: 'iOSSim', 9: 'tvOSSim', 10: 'watchOSSim', 11: 'DriverKit'}


def sha256(path, bufsize=1 << 22):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        while True:
            b = f.read(bufsize)
            if not b:
                break
            h.update(b)
    return h.hexdigest().upper()


def _ver32(v):
    return '%d.%d.%d' % (v >> 16, (v >> 8) & 0xFF, v & 0xFF)


def _srcver(v):
    return '%d.%d.%d.%d.%d' % (v >> 40, (v >> 30) & 0x3FF, (v >> 20) & 0x3FF,
                               (v >> 10) & 0x3FF, v & 0x3FF)


def parse_slice(data, off=0):
    magic = struct.unpack_from('<I', data, off)[0]
    be = False
    if magic in (MH_CIGAM, MH_CIGAM_64):
        be = True
    elif magic not in (MH_MAGIC, MH_MAGIC_64):
        return None
    e = '>' if be else '<'
    is64 = magic in (MH_MAGIC_64, MH_CIGAM_64) or (be and magic == MH_CIGAM_64)
    magic_r = struct.unpack_from(e + 'I', data, off)[0]
    is64 = magic_r in (MH_MAGIC_64,) or magic in (MH_MAGIC_64, MH_CIGAM_64)
    cputype, cpusub, filetype, ncmds, sizeofcmds, flags = struct.unpack_from(
        e + 'iiIIII', data, off + 4)
    hdrsize = 32 if is64 else 28
    info = {
        'cputype': CPU.get(cputype & 0xFFFFFFFF, hex(cputype)),
        'cpusubtype_raw': cpusub & 0x00FFFFFF,
        'cpusubtype_caps': (cpusub >> 24) & 0xFF,
        'filetype': FILETYPE.get(filetype, filetype),
        'ncmds': ncmds,
        'flags': hex(flags),
        'uuid': None,
        'source_version': None,
        'build': None,
        'id_dylib': None,
        'fileset_entries': [],
    }
    key = cputype & 0xFFFFFFFF
    sub = cpusub & 0x00FFFFFF
    if key == 0x01000007:
        info['cpusubtype'] = X86_SUB.get(sub, str(sub))
    elif key == 0x0100000C:
        info['cpusubtype'] = ARM64_SUB.get(sub, str(sub))
    else:
        info['cpusubtype'] = str(sub)
    p = off + hdrsize
    for _ in range(ncmds):
        if p + 8 > len(data):
            break
        cmd, cmdsize = struct.unpack_from(e + 'II', data, p)
        if cmdsize == 0:
            break
        if cmd == LC_UUID:
            u = data[p + 8:p + 24]
            info['uuid'] = ('%02X%02X%02X%02X-%02X%02X-%02X%02X-%02X%02X-'
                            '%02X%02X%02X%02X%02X%02X') % tuple(u)
        elif cmd == LC_SOURCE_VERSION:
            info['source_version'] = _srcver(struct.unpack_from(e + 'Q', data, p + 8)[0])
        elif cmd == LC_BUILD_VERSION:
            plat, minos, sdk = struct.unpack_from(e + 'III', data, p + 8)
            info['build'] = '%s minos=%s sdk=%s' % (
                PLATFORM.get(plat, plat), _ver32(minos), _ver32(sdk))
        elif cmd == LC_ID_DYLIB:
            noff = struct.unpack_from(e + 'I', data, p + 8)[0]
            s = data[p + noff:p + cmdsize].split(b'\0')[0]
            info['id_dylib'] = s.decode('utf-8', 'replace')
        elif cmd == LC_FILESET_ENTRY:
            vmaddr, fileoff, entry_id_off = struct.unpack_from(e + 'QQI', data, p + 8)
            s = data[p + entry_id_off:p + cmdsize].split(b'\0')[0]
            info['fileset_entries'].append((s.decode('utf-8', 'replace'), vmaddr, fileoff))
        p += cmdsize
    return info


def describe(path, read_limit=None):
    size = os.path.getsize(path)
    with open(path, 'rb') as f:
        head = f.read(4)
        f.seek(0)
        magic = struct.unpack('>I', head)[0] if len(head) == 4 else 0
        if magic in (FAT_MAGIC, FAT_MAGIC_64):
            nfat = struct.unpack('>I', f.read(8)[4:])[0]
            f.seek(8)
            slices = []
            wide = magic == FAT_MAGIC_64
            recsz = 32 if wide else 20
            recs = f.read(nfat * recsz)
            for i in range(nfat):
                r = recs[i * recsz:(i + 1) * recsz]
                if wide:
                    ct, cs, o, sz, al = struct.unpack('>iiQQI', r[:28])
                else:
                    ct, cs, o, sz, al = struct.unpack('>iiIII', r)
                f.seek(o)
                blob = f.read(min(sz, 1 << 20))
                info = parse_slice(blob, 0) or {}
                info['fat_offset'] = o
                info['fat_size'] = sz
                slices.append(info)
            return {'path': path, 'size': size, 'container': 'FAT', 'slices': slices}
        f.seek(0)
        blob = f.read(min(size, 8 << 20))
        info = parse_slice(blob, 0)
        if info is None:
            return {'path': path, 'size': size, 'container': 'not-macho',
                    'magic': head.hex().upper(), 'slices': []}
        return {'path': path, 'size': size, 'container': 'thin', 'slices': [info]}


def report(path):
    d = describe(path)
    d['sha256'] = sha256(path)
    return d
