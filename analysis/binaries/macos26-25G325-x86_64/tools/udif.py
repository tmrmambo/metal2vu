"""Random-access reader for an uncompressed UDIF (.dmg) image.

Only chunk types 0x0 (zero fill), 0x1 (raw) and 0x2 (ignore/free) are
supported; the 25G325 SharedSupport.dmg uses only those.
"""
import bisect
import os
import plistlib
import struct

SECTOR = 512


class UdifReader:
    def __init__(self, path):
        self.path = path
        self.f = open(path, 'rb')
        size = os.path.getsize(path)
        self.f.seek(size - 512)
        koly = self.f.read(512)
        if koly[:4] != b'koly':
            raise ValueError('no koly trailer')
        xml_off, xml_len = struct.unpack('>QQ', koly[0xD8:0xE8])
        self.sector_count = struct.unpack('>Q', koly[0x1EC:0x1F4])[0]
        self.f.seek(xml_off)
        pl = plistlib.loads(self.f.read(xml_len))

        # virtual sector -> (kind, file_offset)
        starts = []
        extents = []
        self.partitions = []
        for blk in pl['resource-fork']['blkx']:
            d = blk['Data']
            (_ver, sector_number, sector_count, data_offset,
             _bn, _bd) = struct.unpack('>IQQQII', d[4:40])
            self.partitions.append((blk['ID'], blk['Name'], sector_number, sector_count))
            n = struct.unpack('>I', d[200:204])[0]
            for i in range(n):
                et, _c, sstart, scount, coff, clen = struct.unpack(
                    '>IIQQQQ', d[204 + i * 40:244 + i * 40])
                if et == 0xFFFFFFFF:
                    continue
                if et not in (0x0, 0x1, 0x2):
                    raise ValueError('unsupported chunk type 0x%x' % et)
                vs = sector_number + sstart
                starts.append(vs)
                extents.append((vs, scount, et, data_offset + coff, clen))
        order = sorted(range(len(starts)), key=lambda i: starts[i])
        self.starts = [starts[i] for i in order]
        self.extents = [extents[i] for i in order]

    def read(self, offset, size):
        """Read `size` bytes from virtual byte `offset`."""
        out = bytearray()
        while size > 0:
            sec = offset // SECTOR
            i = bisect.bisect_right(self.starts, sec) - 1
            if i < 0:
                raise ValueError('offset before first extent')
            vs, scount, et, coff, clen = self.extents[i]
            if sec >= vs + scount:
                # hole between extents
                out += b'\0' * size
                break
            within = offset - vs * SECTOR
            avail = scount * SECTOR - within
            n = min(size, avail)
            if et == 0x1:
                self.f.seek(coff + within)
                chunk = self.f.read(n)
                if len(chunk) < n:
                    chunk += b'\0' * (n - len(chunk))
                out += chunk
            else:
                out += b'\0' * n
            offset += n
            size -= n
        return bytes(out)

    def find_partition(self, name_substr):
        for pid, name, sn, sc in self.partitions:
            if name_substr in name:
                return sn * SECTOR, sc * SECTOR
        raise KeyError(name_substr)
