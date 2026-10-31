"""Extract exact paths from one payload: py extract_one.py payload.024 <path> ..."""
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
OUT = 'one'


def main():
    name = sys.argv[1]
    wanted = set(sys.argv[2:])
    os.makedirs(OUT, exist_ok=True)
    rf, _p, _s = open_dmg_zip(DMG)
    z = zipfile.ZipFile(io.BufferedReader(rf, 1 << 22))
    fh = z.open('AssetData/payloadv2/' + name)
    if fh.read(4) != b'pbzx':
        raise SystemExit('not pbzx')
    fh.read(8)
    buf = bytearray()
    pending = []
    remaining = 0
    sink = None
    cur = ''
    done = set()

    def nxt():
        nonlocal sink, remaining
        while pending:
            key, size = pending.pop(0)
            if not size:
                continue
            remaining = size
            if key == 'DAT' and cur in wanted:
                sink = open(os.path.join(OUT, cur.replace('/', '__')), 'wb')
                done.add(cur)
            else:
                sink = None
            return
        remaining = 0
        sink = None

    while not (len(done) == len(wanted) and remaining == 0 and sink is None
               and not pending):
        hd = fh.read(16)
        if len(hd) < 16:
            break
        ul, cl = struct.unpack('>QQ', hd)
        raw = fh.read(cl)
        buf += raw if cl == ul else lzma.decompress(raw)
        while True:
            if remaining:
                take = min(remaining, len(buf))
                if not take:
                    break
                if sink:
                    sink.write(memoryview(buf)[:take])
                del buf[:take]
                remaining -= take
                if not remaining:
                    if sink:
                        sink.close()
                        sink = None
                    nxt()
                continue
            if pending:
                nxt()
                continue
            if len(buf) < 6:
                break
            hs = struct.unpack_from('<H', buf, 4)[0]
            if len(buf) < hs:
                break
            fields, blobs, _e = yaa.parse_header(bytes(buf[:hs]), 0)
            del buf[:hs]
            cur = yaa.path_of(fields) or ''
            pending = list(blobs)
            nxt()
    if sink:
        sink.close()
    print('extracted', sorted(done))
    print('missing', sorted(wanted - done))


main()
