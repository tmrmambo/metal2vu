"""Minimal reader for Apple Archive ('YAA1') streams as used by
macOS installer AssetData/payloadv2/payload.NNN files.

Framing (reverse engineered from 25G325 payload.050):
    per entry:  b'YAA1' | uint16 LE header_size (counts magic + this field
                + all fields) | fields... | blob data for A/B/C-typed fields
Field: 3-char key + 1-char type code.
    '*' 0 bytes          '1'/'2'/'4'/'8' little-endian uint of that width
    'A' uint16 blob size, blob stored after the header
    'B' uint32 blob size, blob stored after the header
    'C' uint64 blob size, blob stored after the header
    'P' uint16 size + that many bytes stored inline in the header
    'S' 8-byte value stored inline (timestamps)
    'T' 12-byte value stored inline (timespec)
"""
import struct

MAGIC = b'YAA1'

INLINE = {'*': 0, '1': 1, '2': 2, '4': 4, '8': 8, 'S': 8, 'T': 12}
BLOBSZ = {'A': 2, 'B': 4, 'C': 8}


def parse_header(buf, off):
    """Return (fields, blobs, header_end) or raise ValueError.

    fields: dict key -> int/bytes
    blobs:  list of (key, size)  -- payload stored after the header, in order
    """
    if buf[off:off + 4] != MAGIC:
        raise ValueError('bad magic at %d: %r' % (off, buf[off:off + 4]))
    hs = struct.unpack_from('<H', buf, off + 4)[0]
    end = off + hs
    p = off + 6
    fields = {}
    blobs = []
    while p < end:
        key = buf[p:p + 3].decode('ascii', 'replace')
        tc = chr(buf[p + 3])
        p += 4
        if tc in INLINE:
            n = INLINE[tc]
            raw = buf[p:p + n]
            p += n
            fields[key] = int.from_bytes(raw, 'little') if n else True
        elif tc in BLOBSZ:
            n = BLOBSZ[tc]
            size = int.from_bytes(buf[p:p + n], 'little')
            p += n
            blobs.append((key, size))
            fields[key] = size
        elif tc == 'P':
            n = struct.unpack_from('<H', buf, p)[0]
            p += 2
            fields[key] = buf[p:p + n]
            p += n
        else:
            raise ValueError('unknown field type %r for key %r at %d' % (tc, key, p - 4))
    if p != end:
        raise ValueError('header overrun: p=%d end=%d' % (p, end))
    return fields, blobs, end


def iter_entries(buf, start=0, limit=None):
    """Yield (fields, blobs, header_end, data_end)."""
    off = start
    n = 0
    total = len(buf)
    while off + 6 <= total:
        if buf[off:off + 4] != MAGIC:
            break
        fields, blobs, hend = parse_header(buf, off)
        dsize = sum(sz for _k, sz in blobs)
        yield fields, blobs, hend, hend + dsize
        off = hend + dsize
        n += 1
        if limit and n >= limit:
            return


def path_of(fields):
    p = fields.get('PAT')
    return p.decode('utf-8', 'replace') if isinstance(p, bytes) else None


def type_of(fields):
    t = fields.get('TYP')
    if isinstance(t, int):
        return chr(t)
    return None
