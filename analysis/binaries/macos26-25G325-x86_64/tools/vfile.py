"""A seekable read-only file-like view over a byte range of a reader."""
import io


class RangeFile(io.RawIOBase):
    def __init__(self, reader, offset, size):
        self._r = reader
        self._off = offset
        self._size = size
        self._pos = 0

    def readable(self):
        return True

    def seekable(self):
        return True

    def tell(self):
        return self._pos

    def seek(self, pos, whence=0):
        if whence == 0:
            self._pos = pos
        elif whence == 1:
            self._pos += pos
        else:
            self._pos = self._size + pos
        return self._pos

    def read(self, n=-1):
        if n is None or n < 0:
            n = self._size - self._pos
        n = max(0, min(n, self._size - self._pos))
        if n == 0:
            return b''
        data = self._r.read(self._off + self._pos, n)
        self._pos += n
        return data

    def readinto(self, b):
        data = self.read(len(b))
        b[:len(data)] = data
        return len(data)


def open_dmg_zip(dmg_path, zip_name_suffix='d3cc6643f7010f6ec14cc728f4a47a7c7644e8a5.zip'):
    from udif import UdifReader
    from hfsplus import HfsPlus
    r = UdifReader(dmg_path)
    base, _ = r.find_partition('Apple_HFS')
    h = HfsPlus(r, base)
    for path, kind, size, ext in h.listing():
        if kind == 'file' and path.endswith(zip_name_suffix):
            if len(ext) != 1:
                raise ValueError('fork not contiguous: %r' % (ext,))
            sb, bc = ext[0]
            return RangeFile(r, base + sb * h.block_size, size), path, size
    raise KeyError(zip_name_suffix)
