"""Inspect and extract fileset entries (kexts) from an MH_FILESET kernel
collection, e.g. /System/Library/KernelCollections/BootKernelExtensions.kc.

Extraction keeps the entry's own load commands and vmaddrs intact and
rewrites every LC_SEGMENT_64 / LC_SYMTAB / LC_DYSYMTAB file offset so the
result is a self-contained Mach-O whose RVAs match the collection.
"""
import struct
import sys

LC_SEGMENT_64 = 0x19
LC_SYMTAB = 0x02
LC_DYSYMTAB = 0x0B
LC_UUID = 0x1B
LC_FILESET_ENTRY = 0x80000035
LC_DYLD_CHAINED_FIXUPS = 0x80000034
LC_FUNCTION_STARTS = 0x26
LC_DATA_IN_CODE = 0x29
LC_CODE_SIGNATURE = 0x1D


def mach_header(buf, off):
    magic, cputype, cpusub, filetype, ncmds, sizeofcmds, flags, _r = \
        struct.unpack_from('<IiiIIIII', buf, off)
    return dict(magic=magic, cputype=cputype, cpusub=cpusub, filetype=filetype,
                ncmds=ncmds, sizeofcmds=sizeofcmds, flags=flags, hdrsize=32)


def load_commands(buf, off):
    h = mach_header(buf, off)
    p = off + h['hdrsize']
    for _ in range(h['ncmds']):
        cmd, cmdsize = struct.unpack_from('<II', buf, p)
        yield p, cmd, cmdsize
        p += cmdsize


def uuid_str(b):
    return ('%02X%02X%02X%02X-%02X%02X-%02X%02X-%02X%02X-%02X%02X%02X%02X%02X%02X'
            % tuple(b))


def fileset_entries(buf):
    out = []
    for p, cmd, cmdsize in load_commands(buf, 0):
        if cmd == LC_FILESET_ENTRY:
            vmaddr, fileoff, idoff = struct.unpack_from('<QQI', buf, p + 8)
            name = buf[p + idoff:p + cmdsize].split(b'\0')[0].decode()
            out.append((name, vmaddr, fileoff))
    return out


def entry_info(buf, fileoff):
    h = mach_header(buf, fileoff)
    info = dict(h)
    info['segments'] = []
    info['uuid'] = None
    for p, cmd, cmdsize in load_commands(buf, fileoff):
        if cmd == LC_SEGMENT_64:
            segname = buf[p + 8:p + 24].split(b'\0')[0].decode()
            vmaddr, vmsize, foff, fsize = struct.unpack_from('<QQQQ', buf, p + 24)
            nsects = struct.unpack_from('<I', buf, p + 64)[0]
            info['segments'].append((segname, vmaddr, vmsize, foff, fsize, nsects))
        elif cmd == LC_UUID:
            info['uuid'] = uuid_str(buf[p + 8:p + 24])
        elif cmd == LC_SYMTAB:
            symoff, nsyms, stroff, strsize = struct.unpack_from('<IIII', buf, p + 8)
            info['symtab'] = (symoff, nsyms, stroff, strsize)
    return info


def extract(buf, fileoff, out_path):
    """Build a standalone Mach-O for the fileset entry at `fileoff`."""
    h = mach_header(buf, fileoff)
    hdr_len = h['hdrsize'] + h['sizeofcmds']
    cmds = bytearray(buf[fileoff:fileoff + hdr_len])

    segs = []
    for p, cmd, cmdsize in load_commands(buf, fileoff):
        rel = p - fileoff
        if cmd == LC_SEGMENT_64:
            segname = buf[p + 8:p + 24].split(b'\0')[0].decode()
            vmaddr, vmsize, foff, fsize = struct.unpack_from('<QQQQ', buf, p + 24)
            nsects = struct.unpack_from('<I', buf, p + 64)[0]
            segs.append(dict(rel=rel, name=segname, vmaddr=vmaddr, vmsize=vmsize,
                             foff=foff, fsize=fsize, nsects=nsects, cmdoff=p))

    # lay out: header+cmds, then each segment with file content, page aligned
    page = 0x4000
    cursor = (hdr_len + page - 1) // page * page
    body = bytearray()
    layout = {}
    for s in segs:
        if s['fsize'] == 0:
            layout[s['rel']] = 0
            continue
        pad = cursor - (hdr_len + len(body))
        if pad < 0:
            pad = 0
        body += b'\0' * pad
        newoff = hdr_len + len(body)
        body += buf[s['foff']:s['foff'] + s['fsize']]
        layout[s['rel']] = newoff
        cursor = (hdr_len + len(body) + page - 1) // page * page
        s['newoff'] = newoff

    # patch segment file offsets and section offsets
    for s in segs:
        rel = s['rel']
        newoff = layout[rel]
        delta = newoff - s['foff'] if s['fsize'] else 0
        struct.pack_into('<Q', cmds, rel + 24 + 24, newoff)
        # sections follow the 72-byte segment command
        for i in range(s['nsects']):
            so = rel + 72 + i * 80
            soff = struct.unpack_from('<I', cmds, so + 48)[0]
            if soff:
                struct.pack_into('<I', cmds, so + 48, soff + delta)
            reloff = struct.unpack_from('<I', cmds, so + 56)[0]
            if reloff:
                struct.pack_into('<I', cmds, so + 56, 0)
                struct.pack_into('<I', cmds, so + 60, 0)

    # LINKEDIT-relative commands: the collection shares one __LINKEDIT, so
    # zero out anything we did not copy rather than leave a dangling offset.
    le = next((s for s in segs if s['name'] == '__LINKEDIT'), None)
    for p, cmd, cmdsize in load_commands(buf, fileoff):
        rel = p - fileoff
        if cmd in (LC_SYMTAB,):
            symoff, nsyms, stroff, strsize = struct.unpack_from('<IIII', cmds, rel + 8)
            if le and le['fsize'] and le['foff'] <= symoff < le['foff'] + le['fsize']:
                d = layout[le['rel']] - le['foff']
                struct.pack_into('<IIII', cmds, rel + 8,
                                 symoff + d, nsyms, stroff + d, strsize)
            else:
                struct.pack_into('<IIII', cmds, rel + 8, 0, 0, 0, 0)
        elif cmd in (LC_FUNCTION_STARTS, LC_DATA_IN_CODE, LC_CODE_SIGNATURE,
                     LC_DYLD_CHAINED_FIXUPS):
            off, size = struct.unpack_from('<II', cmds, rel + 8)
            if le and le['fsize'] and off and le['foff'] <= off < le['foff'] + le['fsize']:
                d = layout[le['rel']] - le['foff']
                struct.pack_into('<II', cmds, rel + 8, off + d, size)
            else:
                struct.pack_into('<II', cmds, rel + 8, 0, 0)
        elif cmd == LC_DYSYMTAB:
            struct.pack_into('<' + 'I' * 18, cmds, rel + 8, *([0] * 18))

    with open(out_path, 'wb') as f:
        f.write(cmds)
        f.write(body)
    return hdr_len + len(body)


if __name__ == '__main__':
    path = sys.argv[1]
    buf = open(path, 'rb').read()
    ents = fileset_entries(buf)
    print(path, len(ents), 'fileset entries')
    for name, vmaddr, foff in ents:
        info = entry_info(buf, foff)
        segs = ','.join('%s:%#x/%#x' % (s[0], s[1], s[2]) for s in info['segments'])
        print('%-60s vm=%#x off=%#x uuid=%s' % (name, vmaddr, foff, info['uuid']))
