"""Index every AssetData/payloadv2/payload.NNN entry in the 25G325
SharedSupport.dmg MobileAsset zip and extract the entries we care about.

Usage:  py scan.py <payload-basename> [...]
Writes: idx/<name>.tsv  (path, type, datasize, mode, flags, afstype, xattrbytes)
        out/<name>/<flat-path>          DAT blob of wanted entries
        out/<name>/<flat-path>.XAT      concatenated xattr blob(s)
"""
import io
import lzma
import os
import struct
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from vfile import open_dmg_zip  # noqa: E402
import yaa  # noqa: E402

DMG = r'c:\Users\viola\Documents\KVM MacOS\SharedSupport.dmg'
HERE = os.path.dirname(os.path.abspath(__file__))
IDX = os.path.join(HERE, 'idx')
OUT = os.path.join(HERE, 'out')

WANT_SUBSTR = (
    'AppleParavirtGPU',
    'AppleParavirtIOSurface',
    'IOAcceleratorFamily2',
    'IOGraphicsFamily',
    'IOGPUFamily',
    'IOSurface.kext',
    'IOSurface.framework',
    'IOGPU.framework',
    'IOAccelerator.framework',
    'AppleGraphicsDeviceControl',
    'IOMobileGraphicsFamily',
    'IOPCIFamily.kext',
    'KernelCollections',
    'dyld_shared_cache_x86_64',
)
MAX_EXTRACT = 4096 * 1024 * 1024


def flat(p):
    return p.replace('/', '__')


def want(path, size):
    if size > MAX_EXTRACT:
        return False
    return any(s in path for s in WANT_SUBSTR)


def run(name):
    full = 'AssetData/payloadv2/' + name
    rf, _p, _s = open_dmg_zip(DMG)
    z = zipfile.ZipFile(io.BufferedReader(rf, 1 << 22))
    fh = z.open(full)

    os.makedirs(IDX, exist_ok=True)
    outdir = os.path.join(OUT, name)
    idxf = open(os.path.join(IDX, name + '.tsv'), 'w', encoding='utf-8', newline='\n')

    buf = bytearray()
    pending = []          # list of (key, size) still to consume for current entry
    sink = None
    remaining = 0
    nent = 0
    nextract = 0
    cur_path = ''
    if fh.read(4) != b'pbzx':
        raise ValueError('not pbzx')
    fh.read(8)

    def next_blob():
        nonlocal sink, remaining
        while pending:
            key, size = pending.pop(0)
            if size == 0:
                continue
            remaining = size
            if want(cur_path, size) and key in ('DAT', 'XAT'):
                os.makedirs(outdir, exist_ok=True)
                suffix = '' if key == 'DAT' else '.XAT'
                sink = open(os.path.join(outdir, flat(cur_path) + suffix), 'ab')
            else:
                sink = None
            return True
        remaining = 0
        sink = None
        return False

    while True:
        hd = fh.read(16)
        if len(hd) < 16:
            break
        ul, cl = struct.unpack('>QQ', hd)
        raw = fh.read(cl)
        buf += raw if cl == ul else lzma.decompress(raw)
        while True:
            if remaining:
                take = min(remaining, len(buf))
                if take == 0:
                    break
                if sink is not None:
                    sink.write(memoryview(buf)[:take])
                del buf[:take]
                remaining -= take
                if remaining == 0:
                    if sink is not None:
                        sink.close()
                        sink = None
                    next_blob()
                continue
            if pending:
                next_blob()
                continue
            if len(buf) < 6:
                break
            if buf[:4] != yaa.MAGIC:
                raise ValueError('%s: lost sync, saw %r' % (name, bytes(buf[:8])))
            hs = struct.unpack_from('<H', buf, 4)[0]
            if len(buf) < hs:
                break
            fields, blobs, _e = yaa.parse_header(bytes(buf[:hs]), 0)
            del buf[:hs]
            cur_path = yaa.path_of(fields) or ''
            typ = yaa.type_of(fields) or '?'
            dat = sum(sz for k, sz in blobs if k == 'DAT')
            xat = sum(sz for k, sz in blobs if k == 'XAT')
            idxf.write('%s\t%s\t%d\t%s\t%s\t%s\t%d\n' % (
                cur_path, typ, dat, fields.get('MOD', ''), fields.get('FLG', ''),
                fields.get('AFT', ''), xat))
            nent += 1
            if dat and want(cur_path, dat):
                nextract += 1
            pending = list(blobs)
            next_blob()
    if sink is not None:
        sink.close()
    idxf.close()
    print('%s: %d entries, %d extracted, leftover=%d' % (name, nent, nextract, len(buf)), flush=True)


if __name__ == '__main__':
    for n in sys.argv[1:]:
        run(n)
