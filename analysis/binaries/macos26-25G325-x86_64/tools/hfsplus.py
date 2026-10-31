"""Minimal read-only HFS+ catalog walker on top of a byte-range reader."""
import struct

kHFSRootFolderID = 2


def _fork(buf, off):
    logical, clump, total = struct.unpack('>QII', buf[off:off + 16])
    extents = []
    for i in range(8):
        sb, bc = struct.unpack('>II', buf[off + 16 + i * 8: off + 24 + i * 8])
        if bc:
            extents.append((sb, bc))
    return logical, extents


class HfsPlus:
    def __init__(self, reader, part_base):
        self.r = reader
        self.base = part_base
        vh = reader.read(part_base + 1024, 1024)
        if vh[:2] not in (b'H+', b'HX'):
            raise ValueError('not HFS+: %r' % vh[:2])
        self.case_sensitive = vh[:2] == b'HX'
        self.block_size = struct.unpack('>I', vh[0x28:0x2C])[0]
        self.extents_fork = _fork(vh, 0xC0)
        self.catalog_fork = _fork(vh, 0x110)
        # overflow extents for the catalog file are not handled; assert not needed
        self.cat_logical, self.cat_extents = self.catalog_fork
        self._read_btree_header()

    # ---- fork I/O -------------------------------------------------------
    def read_fork(self, extents, offset, size):
        out = bytearray()
        pos = 0
        for sb, bc in extents:
            ext_len = bc * self.block_size
            if offset < pos + ext_len and size > 0:
                skip = max(0, offset - pos)
                n = min(size, ext_len - skip)
                out += self.r.read(self.base + sb * self.block_size + skip, n)
                offset += n
                size -= n
            pos += ext_len
            if size <= 0:
                break
        if size > 0:
            out += b'\0' * size
        return bytes(out)

    # ---- catalog B-tree -------------------------------------------------
    def _read_btree_header(self):
        node0 = self.read_fork(self.cat_extents, 0, 512)
        # BTNodeDescriptor is 14 bytes, then BTHeaderRec
        hdr = node0[14:14 + 106]
        (tree_depth, root_node, leaf_records, first_leaf, last_leaf,
         node_size, max_key_len, total_nodes, free_nodes) = struct.unpack(
            '>HIIIIHHII', hdr[:30])
        self.node_size = node_size
        self.root_node = root_node
        self.first_leaf = first_leaf
        self.leaf_records = leaf_records
        self.tree_depth = tree_depth

    def node(self, idx):
        return self.read_fork(self.cat_extents, idx * self.node_size, self.node_size)

    def node_records(self, buf):
        f_link, b_link, kind, height, num_recs = struct.unpack('>IIbbH', buf[:12])
        offs = []
        for i in range(num_recs + 1):
            o = struct.unpack('>H', buf[len(buf) - 2 * (i + 1):len(buf) - 2 * i])[0]
            offs.append(o)
        recs = []
        for i in range(num_recs):
            recs.append(buf[offs[i]:offs[i + 1]])
        return f_link, kind, height, recs

    def iter_leaves(self):
        idx = self.first_leaf
        while idx:
            buf = self.node(idx)
            f_link, kind, height, recs = self.node_records(buf)
            yield recs
            idx = f_link

    @staticmethod
    def parse_key(rec):
        key_len = struct.unpack('>H', rec[:2])[0]
        parent_id = struct.unpack('>I', rec[2:6])[0]
        name_len = struct.unpack('>H', rec[6:8])[0]
        name = rec[8:8 + name_len * 2].decode('utf-16-be', 'replace')
        data_off = 2 + key_len
        if data_off & 1:
            data_off += 1
        return parent_id, name, rec[data_off:]

    def walk(self):
        """Yield (parent_id, name, kind, cnid, logical_size, extents)."""
        for recs in self.iter_leaves():
            for rec in recs:
                try:
                    parent_id, name, data = self.parse_key(rec)
                except Exception:
                    continue
                if len(data) < 2:
                    continue
                kind = struct.unpack('>h', data[:2])[0]
                if kind == 1:  # folder
                    cnid = struct.unpack('>I', data[8:12])[0]
                    yield (parent_id, name, 'dir', cnid, 0, None)
                elif kind == 2:  # file
                    cnid = struct.unpack('>I', data[8:12])[0]
                    logical, extents = _fork(data, 88)
                    yield (parent_id, name, 'file', cnid, logical, extents)

    def tree(self):
        kids = {}
        meta = {}
        for parent_id, name, kind, cnid, size, extents in self.walk():
            kids.setdefault(parent_id, []).append((name, kind, cnid))
            meta[cnid] = (name, kind, size, extents)
        return kids, meta

    def listing(self):
        kids, meta = self.tree()
        out = []

        def rec(cnid, prefix):
            for name, kind, child in sorted(kids.get(cnid, [])):
                path = prefix + '/' + name
                if kind == 'dir':
                    out.append((path, 'dir', 0, None))
                    rec(child, path)
                else:
                    _n, _k, size, extents = meta[child]
                    out.append((path, 'file', size, extents))
        rec(kHFSRootFolderID, '')
        return out
