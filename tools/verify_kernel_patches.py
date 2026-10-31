#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""tools/verify_kernel_patches.py

把 OpenCore 的 `Kernel/Patch` 条目按官方的 Find / Mask / Base / Skip / Count /
Limit 语义在一份目标 Mach-O 上实跑一遍，报告每条条目的命中总数、实际会被改写的
命中、命中位置的 VA 与所属函数，并可对照一份"已核验"的期望清单做 CI 门禁。

它要回答的是两个问题，不是一个：

  1. 目标命中了吗？          （命中数是否等于 Count，首个命中是否落在预期函数里）
  2. 有没有误伤？            （会被改写的命中里有没有落在禁止名单里的函数）

`docs/spec/72-CPU-COMPAT.md` 第 3.3.1 节记录的 AMD_Vanilla 第 20 条就是第 2 类
问题：目标未命中，而掩码过松导致 `_kperf_lazy_wait_sample` 与 `_vmx_hv_support`
被 NOP。只看"命中数 >= 1"的门禁挡不住它。

只用标准库，Windows / Linux / macOS 都能跑。不修改任何输入文件。

用法
----
  # 1) 看一遍过滤后的补丁集与命中情况
  py tools/verify_kernel_patches.py \
      --binary analysis/binaries/macos26-25G325-x86_64/kernel/kernel.x86_64 \
      --patches vendor/AMD_Vanilla/patches.plist \
      --darwin 25.7.2

  # 2) 把当前结果固化成期望清单（人工核对后提交进仓库）
  py tools/verify_kernel_patches.py ... --emit-expect tools/expect/amd-vanilla-25G325.json

  # 3) CI 门禁：拿已提交的期望清单比对
  py tools/verify_kernel_patches.py ... \
      --expect tools/expect/amd-vanilla-25G325.json --json out/patch-report.json

退出码
  0  通过
  1  门禁不通过（命中与期望不符 / 误伤 / 期望里的条目消失 / 出现未登记的条目）
  2  用法或解析错误

补丁身份（key）
--------------
条目用内容寻址：`key = sha256(Identifier|Arch|Base|MinKernel|MaxKernel|Count|Skip|
Limit|Find|Mask|Replace|ReplaceMask)[:16]`。上游一旦改了任何一个字节，key 就变，
门禁会报"未登记的条目"而不是静默接受。这是有意的：补丁内容的变化必须是一次人工
复核事件。`Comment` 不参与 key，它只是给人看的。
"""

from __future__ import annotations

import argparse
import bisect
import hashlib
import json
import os
import plistlib
import struct
import sys

SCHEMA = "metal2vu.patchreport/1"
EXPECT_SCHEMA = "metal2vu.patchexpect/1"

# 本脚本的输出含中文。Windows 控制台默认是 cp1252/cp936，不改编码时连 --help
# 都会抛 UnicodeEncodeError。放在模块级，因为 argparse 的 --help 在 main() 里
# 解析参数时就要打印。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError, OSError):
        pass

# ---------------------------------------------------------------------------
# Mach-O
# ---------------------------------------------------------------------------

FAT_MAGIC = 0xCAFEBABE
FAT_MAGIC_64 = 0xCAFEBABF
MH_MAGIC_64 = 0xFEEDFACF
MH_CIGAM_64 = 0xCFFAEDFE

LC_SEGMENT_64 = 0x19
LC_SYMTAB = 0x02
LC_UUID = 0x1B

CPU_TYPE = {0x01000007: "x86_64", 0x0100000C: "arm64", 7: "i386"}

N_TYPE = 0x0E
N_SECT = 0x0E


class MachOError(Exception):
    pass


class Segment:
    __slots__ = ("name", "vmaddr", "vmsize", "fileoff", "filesize", "sections")

    def __init__(self, name, vmaddr, vmsize, fileoff, filesize):
        self.name = name
        self.vmaddr = vmaddr
        self.vmsize = vmsize
        self.fileoff = fileoff
        self.filesize = filesize
        self.sections = []

    def __repr__(self):  # pragma: no cover - debug aid
        return "<Segment %s vm=0x%x size=0x%x off=0x%x>" % (
            self.name, self.vmaddr, self.vmsize, self.fileoff)


class MachO:
    """足够用的 Mach-O 读取器：段表、节表、符号表、VA <-> 文件偏移。

    刻意不处理 dyld chained fixups、不处理 LC_FILESET_ENTRY 的递归展开。本脚本
    的输入是单个可执行件（内核本体或 `tools/kc.py` 重建出的单个 kext）。
    """

    def __init__(self, data: bytes, want_arch: str = "x86_64"):
        self.want_arch = want_arch
        self.slice_off = 0
        self.data = data
        self.arch = None
        self.uuid = None
        self.segments = []
        self._sym_names = []
        self._sym_vas = []
        self._parse(data, want_arch)

    # -- parsing ----------------------------------------------------------
    def _parse(self, data, want_arch):
        if len(data) < 8:
            raise MachOError("file too small")
        be_magic = struct.unpack_from(">I", data, 0)[0]
        if be_magic in (FAT_MAGIC, FAT_MAGIC_64):
            self.slice_off = self._pick_fat_slice(data, be_magic, want_arch)
        magic = struct.unpack_from("<I", data, self.slice_off)[0]
        if magic not in (MH_MAGIC_64, MH_CIGAM_64):
            raise MachOError("not a 64-bit Mach-O (magic=0x%08x)" % magic)
        if magic == MH_CIGAM_64:
            raise MachOError("big-endian Mach-O is out of scope")
        cputype, _cpusub, _ftype, ncmds, _szcmds, _flags = struct.unpack_from(
            "<iiIIII", data, self.slice_off + 4)
        self.arch = CPU_TYPE.get(cputype & 0xFFFFFFFF, hex(cputype))
        if want_arch and self.arch != want_arch:
            raise MachOError("slice arch is %s, wanted %s" % (self.arch, want_arch))
        p = self.slice_off + 32
        for _ in range(ncmds):
            if p + 8 > len(data):
                break
            cmd, cmdsize = struct.unpack_from("<II", data, p)
            if cmdsize == 0:
                break
            if cmd == LC_SEGMENT_64:
                self._parse_segment(data, p)
            elif cmd == LC_SYMTAB:
                self._parse_symtab(data, p)
            elif cmd == LC_UUID:
                u = data[p + 8:p + 24]
                self.uuid = ("%02X%02X%02X%02X-%02X%02X-%02X%02X-%02X%02X-"
                             "%02X%02X%02X%02X%02X%02X") % tuple(u)
            p += cmdsize
        if not self.segments:
            raise MachOError("no LC_SEGMENT_64 found")

    @staticmethod
    def _pick_fat_slice(data, magic, want_arch):
        nfat = struct.unpack_from(">I", data, 4)[0]
        wide = magic == FAT_MAGIC_64
        recsz = 32 if wide else 20
        for i in range(nfat):
            base = 8 + i * recsz
            if wide:
                ct, _cs, off, _sz, _al = struct.unpack_from(">iiQQI", data, base)
            else:
                ct, _cs, off, _sz, _al = struct.unpack_from(">iiIII", data, base)
            if CPU_TYPE.get(ct & 0xFFFFFFFF) == want_arch:
                return off
        raise MachOError("FAT container has no %s slice" % want_arch)

    def _parse_segment(self, data, p):
        name = data[p + 8:p + 24].split(b"\0")[0].decode("ascii", "replace")
        vmaddr, vmsize, fileoff, filesize = struct.unpack_from("<QQQQ", data, p + 24)
        nsects = struct.unpack_from("<I", data, p + 64)[0]
        seg = Segment(name, vmaddr, vmsize, fileoff, filesize)
        sp = p + 72
        for _ in range(nsects):
            sect = data[sp:sp + 16].split(b"\0")[0].decode("ascii", "replace")
            addr, size = struct.unpack_from("<QQ", data, sp + 32)
            off = struct.unpack_from("<I", data, sp + 48)[0]
            seg.sections.append((sect, addr, size, off))
            sp += 80
        self.segments.append(seg)

    def _parse_symtab(self, data, p):
        symoff, nsyms, stroff, strsize = struct.unpack_from("<IIII", data, p + 8)
        symoff += self.slice_off
        stroff += self.slice_off
        strs = data[stroff:stroff + strsize]
        pairs = []
        for i in range(nsyms):
            e = symoff + i * 16
            if e + 16 > len(data):
                break
            n_strx, n_type, _n_sect, _n_desc = struct.unpack_from("<IBBH", data, e)
            n_value = struct.unpack_from("<Q", data, e + 8)[0]
            if (n_type & N_TYPE) != N_SECT or n_value == 0:
                continue
            end = strs.find(b"\0", n_strx)
            nm = strs[n_strx:end if end >= 0 else None].decode("utf-8", "replace")
            if nm:
                pairs.append((n_value, nm))
        pairs.sort()
        self._sym_vas = [v for v, _ in pairs]
        self._sym_names = [n for _, n in pairs]

    # -- lookups ----------------------------------------------------------
    def segment(self, name):
        for s in self.segments:
            if s.name == name:
                return s
        return None

    def va_to_off(self, va):
        for s in self.segments:
            if s.filesize and s.vmaddr <= va < s.vmaddr + s.filesize:
                return self.slice_off + s.fileoff + (va - s.vmaddr)
        return None

    def off_to_va(self, off):
        off -= self.slice_off
        for s in self.segments:
            if s.filesize and s.fileoff <= off < s.fileoff + s.filesize:
                return s.vmaddr + (off - s.fileoff)
        return None

    def symbol_va(self, name):
        try:
            i = self._sym_names.index(name)
        except ValueError:
            return None
        return self._sym_vas[i]

    def nearest_symbol(self, va):
        """返回 (name, delta)，即 va 落在哪个符号之后多少字节。"""
        if not self._sym_vas:
            return (None, None)
        i = bisect.bisect_right(self._sym_vas, va) - 1
        if i < 0:
            return (None, None)
        return (self._sym_names[i], va - self._sym_vas[i])

    def describe_va(self, va):
        name, delta = self.nearest_symbol(va)
        if name is None:
            return "0x%x" % va
        if delta == 0:
            return name
        return "%s+0x%X" % (name, delta)


# ---------------------------------------------------------------------------
# Darwin 版本比较
# ---------------------------------------------------------------------------

def parse_kver(s, default=None):
    """'25.4.0' -> (25, 4, 0)。空串或 None 返回 default。"""
    if s is None or s == "":
        return default
    parts = str(s).split(".")
    out = []
    for i in range(3):
        try:
            out.append(int(parts[i]))
        except (IndexError, ValueError):
            out.append(0)
    return tuple(out)


def kver_in_range(target, minv, maxv):
    if target is None:
        return True
    if minv is not None and target < minv:
        return False
    if maxv is not None and target > maxv:
        return False
    return True


# ---------------------------------------------------------------------------
# 补丁条目
# ---------------------------------------------------------------------------

def _b(v):
    if v is None:
        return b""
    if isinstance(v, (bytes, bytearray)):
        return bytes(v)
    raise MachOError("expected plist <data>, got %r" % type(v))


class Patch:
    def __init__(self, raw, ordinal):
        self.ordinal = ordinal
        self.raw = raw
        self.comment = str(raw.get("Comment", "") or "")
        self.identifier = str(raw.get("Identifier", "kernel") or "kernel")
        self.arch = str(raw.get("Arch", "Any") or "Any")
        base = raw.get("Base", "") or ""
        self.base_raw = str(base)
        self.base = self.base_raw.strip()
        self.base_had_space = self.base != self.base_raw
        self.enabled = bool(raw.get("Enabled", False))
        self.count = int(raw.get("Count", 0) or 0)
        self.skip = int(raw.get("Skip", 0) or 0)
        self.limit = int(raw.get("Limit", 0) or 0)
        self.find = _b(raw.get("Find"))
        self.mask = _b(raw.get("Mask"))
        self.replace = _b(raw.get("Replace"))
        self.replace_mask = _b(raw.get("ReplaceMask"))
        self.minkernel = parse_kver(raw.get("MinKernel"), None)
        self.maxkernel = parse_kver(raw.get("MaxKernel"), None)
        self.size = max(len(self.find), len(self.replace))
        if self.find and self.replace and len(self.find) != len(self.replace):
            # OpenCore 要求 Find 与 Replace 同长（任一可为空）。长度不等是配置错误。
            self.size = max(len(self.find), len(self.replace))
            self.length_mismatch = True
        else:
            self.length_mismatch = False

    @property
    def key(self):
        h = hashlib.sha256()
        for part in (self.identifier, self.arch, self.base,
                     "%s" % (self.minkernel,), "%s" % (self.maxkernel,),
                     "%d" % self.count, "%d" % self.skip, "%d" % self.limit):
            h.update(part.encode("utf-8"))
            h.update(b"\x1f")
        for part in (self.find, self.mask, self.replace, self.replace_mask):
            h.update(part)
            h.update(b"\x1f")
        return h.hexdigest()[:16]

    def effective_mask(self):
        if self.mask:
            if len(self.mask) != len(self.find):
                raise MachOError(
                    "patch #%d: Mask is %d bytes but Find is %d bytes"
                    % (self.ordinal, len(self.mask), len(self.find)))
            return self.mask
        return b"\xFF" * len(self.find)

    def applies_to(self, arch, darwin):
        if self.arch not in ("Any", arch):
            return False, "arch=%s" % self.arch
        if not kver_in_range(darwin, self.minkernel, self.maxkernel):
            return False, "kernel range %s..%s" % (self.minkernel, self.maxkernel)
        return True, None


def load_patches(path):
    with open(path, "rb") as f:
        root = plistlib.load(f)
    arr = None
    if isinstance(root, list):
        arr = root
    elif isinstance(root, dict):
        if isinstance(root.get("Kernel"), dict):
            arr = root["Kernel"].get("Patch")
        if arr is None:
            arr = root.get("Patch")
    if not isinstance(arr, list):
        raise MachOError("%s: cannot find a Kernel/Patch array" % path)
    return [Patch(d, i) for i, d in enumerate(arr)]


# ---------------------------------------------------------------------------
# 扫描：OpenCore 的 Find / Mask / Skip / Count / Limit 语义
# ---------------------------------------------------------------------------

def scan(data, start, end, find, mask):
    """返回 [offset, ...]，掩码比较 (data[i] & mask[i]) == find[i]。

    与 OpenCore 一致的点：逐字节步进（不是按 pattern 长度跳跃），所以重叠命中都算。
    """
    n = len(find)
    if n == 0:
        return []
    hits = []
    limit = end - n
    i = start
    while i <= limit:
        j = 0
        while j < n:
            if (data[i + j] & mask[j]) != find[j]:
                break
            j += 1
        if j == n:
            hits.append(i)
        i += 1
    return hits


def apply_replace(orig, replace, replace_mask):
    """算出改写后的字节，供报告展示。ReplaceMask 为空视为全 FF。"""
    out = bytearray(orig)
    n = min(len(replace), len(out))
    for i in range(n):
        m = replace_mask[i] if i < len(replace_mask) else 0xFF
        if m == 0:
            continue
        out[i] = (out[i] & (~m & 0xFF)) | (replace[i] & m)
    return bytes(out)


def hexs(b):
    return " ".join("%02X" % x for x in b)


# ---------------------------------------------------------------------------
# 单条条目的核对
# ---------------------------------------------------------------------------

def verify_patch(mo, data, patch, darwin, arch, range_mode, context):
    rec = {
        "ordinal": patch.ordinal,
        "key": patch.key,
        "comment": patch.comment,
        "identifier": patch.identifier,
        "arch": patch.arch,
        "base": patch.base,
        "base_had_whitespace": patch.base_had_space,
        "enabled": patch.enabled,
        "min_kernel": ".".join(map(str, patch.minkernel)) if patch.minkernel else "",
        "max_kernel": ".".join(map(str, patch.maxkernel)) if patch.maxkernel else "",
        "count": patch.count,
        "skip": patch.skip,
        "limit": patch.limit,
        "find": hexs(patch.find),
        "mask": hexs(patch.mask),
        "replace": hexs(patch.replace),
        "replace_mask": hexs(patch.replace_mask),
        "selected": False,
        "skip_reason": None,
        "warnings": [],
        "search_start_off": None,
        "search_end_off": None,
        "total_hits": 0,
        "used_hits": 0,
        "hits": [],
    }

    ok, why = patch.applies_to(arch, darwin)
    if not ok:
        rec["skip_reason"] = why
        return rec
    if not patch.enabled:
        rec["skip_reason"] = "Enabled=false"
        return rec
    if not patch.find:
        rec["skip_reason"] = "Find is empty (byte-offset style patch, out of scope)"
        rec["warnings"].append("Find 为空的条目本脚本不处理，需要人工核对")
        return rec
    if patch.length_mismatch:
        rec["warnings"].append("Find 与 Replace 长度不等，OpenCore 会拒绝该条目")
    if patch.base_had_space:
        rec["warnings"].append(
            "Base 字段首尾有空白（%r），已 strip 后解析；构建脚本必须同样 strip"
            % patch.base_raw)

    # 搜索范围
    text = mo.segment("__TEXT")
    if text is None:
        raise MachOError("target has no __TEXT segment")
    if range_mode == "file":
        start = mo.slice_off
        end = len(data)
    else:
        start = mo.slice_off + text.fileoff
        end = start + text.filesize

    if patch.base:
        va = mo.symbol_va(patch.base)
        if va is None:
            rec["skip_reason"] = "Base symbol %r not found in target" % patch.base
            rec["warnings"].append("Base 符号不存在，OpenCore 会跳过这条补丁")
            return rec
        off = mo.va_to_off(va)
        if off is None:
            rec["skip_reason"] = "Base symbol VA 0x%x is outside mapped file" % va
            return rec
        rec["base_va"] = "0x%x" % va
        start = off
    if patch.limit:
        end = min(end, start + patch.limit)

    rec["selected"] = True
    rec["search_start_off"] = "0x%x" % start
    rec["search_end_off"] = "0x%x" % end

    mask = patch.effective_mask()
    hits = scan(data, start, end, patch.find, mask)
    rec["total_hits"] = len(hits)

    used = hits[patch.skip:]
    if patch.count:
        used = used[:patch.count]
    rec["used_hits"] = len(used)

    if patch.count and len(hits) - patch.skip < patch.count:
        rec["warnings"].append(
            "命中数不足：Skip=%d Count=%d，但只有 %d 个命中。OpenCore 会报失败"
            % (patch.skip, patch.count, len(hits)))
    if patch.count and len(hits) - patch.skip > patch.count:
        rec["warnings"].append(
            "命中数多于 Count：共 %d 个命中，只改前 %d 个。掩码可能过松"
            % (len(hits) - patch.skip, patch.count))

    used_set = set(used)
    for off in hits:
        va = mo.off_to_va(off)
        orig = bytes(data[off:off + patch.size])
        entry = {
            "file_off": "0x%x" % off,
            "va": ("0x%x" % va) if va is not None else None,
            "symbol": mo.describe_va(va) if va is not None else None,
            "orig": hexs(orig),
            "will_change": off in used_set,
            "context": hexs(data[max(start, off - context):off + patch.size + context]),
        }
        if off in used_set and patch.replace:
            entry["patched"] = hexs(apply_replace(orig, patch.replace, patch.replace_mask))
        rec["hits"].append(entry)
    return rec


# ---------------------------------------------------------------------------
# 期望清单
# ---------------------------------------------------------------------------

def emit_expect(report, path):
    entries = []
    for r in report["patches"]:
        if not r["selected"]:
            continue
        first = r["hits"][0] if r["hits"] else None
        entries.append({
            "key": r["key"],
            "comment": r["comment"],
            "expect_total_hits": r["total_hits"],
            "expect_used_hits": r["used_hits"],
            "expect_first_va": first["va"] if first else None,
            "expect_used_symbols": sorted({
                h["symbol"].split("+")[0] for h in r["hits"]
                if h["will_change"] and h["symbol"]}),
        })
    doc = {
        "schema": EXPECT_SCHEMA,
        "note": "由 --emit-expect 生成。提交前必须人工核对，参见 docs/spec/74-BOOT-CPU-DISPATCH.md 第 5 节。",
        "binary": report["binary"],
        "binary_uuid": report["binary_uuid"],
        "binary_sha256": report["binary_sha256"],
        "darwin": report["darwin"],
        "range_mode": report["range_mode"],
        "forbid_symbols": [],
        "entries": entries,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(doc, f, indent=2, ensure_ascii=False)
        f.write("\n")
    return doc


def check_expect(report, expect):
    """返回 (failures, notes)。failures 非空即门禁不通过。"""
    failures = []
    notes = []
    if expect.get("schema") != EXPECT_SCHEMA:
        failures.append("expect 文件 schema 不是 %s" % EXPECT_SCHEMA)
        return failures, notes
    if expect.get("binary_uuid") and report["binary_uuid"] \
            and expect["binary_uuid"] != report["binary_uuid"]:
        failures.append(
            "目标二进制 LC_UUID 不符：期望 %s，实际 %s。基线变了就必须重新核验期望清单"
            % (expect["binary_uuid"], report["binary_uuid"]))
    if expect.get("range_mode") and expect["range_mode"] != report["range_mode"]:
        failures.append("range_mode 不符：期望 %s，实际 %s"
                        % (expect["range_mode"], report["range_mode"]))

    forbid = set(expect.get("forbid_symbols") or [])
    by_key = {e["key"]: e for e in expect.get("entries", [])}
    seen = set()

    for r in report["patches"]:
        if not r["selected"]:
            continue
        seen.add(r["key"])
        e = by_key.get(r["key"])
        if e is None:
            failures.append(
                "未登记的条目 key=%s（%s）。上游补丁内容变了，需要人工复核后重新 --emit-expect"
                % (r["key"], r["comment"][:70]))
            continue
        if r["total_hits"] != e["expect_total_hits"]:
            failures.append("key=%s 命中总数 %d != 期望 %d（%s）"
                            % (r["key"], r["total_hits"], e["expect_total_hits"],
                               r["comment"][:50]))
        if r["used_hits"] != e["expect_used_hits"]:
            failures.append("key=%s 会被改写的命中数 %d != 期望 %d"
                            % (r["key"], r["used_hits"], e["expect_used_hits"]))
        first = r["hits"][0]["va"] if r["hits"] else None
        if e.get("expect_first_va") and first != e["expect_first_va"]:
            failures.append("key=%s 首个命中 VA %s != 期望 %s"
                            % (r["key"], first, e["expect_first_va"]))
        got_syms = sorted({h["symbol"].split("+")[0] for h in r["hits"]
                           if h["will_change"] and h["symbol"]})
        want_syms = sorted(e.get("expect_used_symbols") or [])
        if want_syms and got_syms != want_syms:
            failures.append("key=%s 改写位置所属函数 %s != 期望 %s"
                            % (r["key"], got_syms, want_syms))
        bad = [s for s in got_syms if s in forbid]
        if bad:
            failures.append("key=%s 误伤禁止名单中的函数：%s" % (r["key"], bad))

    for k, e in by_key.items():
        if k not in seen:
            failures.append(
                "期望清单里的条目 key=%s（%s）在本次过滤后没有出现。"
                "上游删改了条目，或 --darwin / --arch 给错了"
                % (k, (e.get("comment") or "")[:70]))

    # 全局误伤检查。这一条是硬失败，而且不依赖条目是否已登记：禁止名单的意义就是
    # "无论哪条补丁、无论是否已 bless，都不许动这些函数"。
    if forbid:
        for r in report["patches"]:
            if not r["selected"]:
                continue
            for h in r["hits"]:
                if h["will_change"] and h["symbol"] \
                        and h["symbol"].split("+")[0] in forbid:
                    failures.append(
                        "误伤：key=%s 会改写 %s（在 forbid_symbols 名单里）"
                        % (r["key"], h["symbol"]))
    return failures, notes


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def sha256_file(path, bufsize=1 << 22):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(bufsize)
            if not b:
                break
            h.update(b)
    return h.hexdigest().upper()


def build_parser():
    p = argparse.ArgumentParser(
        description="在目标 Mach-O 上实跑 OpenCore Kernel/Patch 条目并做门禁核对")
    p.add_argument("--binary", required=True,
                   help="目标 Mach-O（内核本体，或重建出的单个 kext）")
    p.add_argument("--patches", required=True,
                   help="patches.plist 或 config.plist（取 Kernel/Patch 数组）")
    p.add_argument("--identifier", default="kernel",
                   help="只核对该 Identifier 的条目，默认 kernel。给 '*' 表示全部")
    p.add_argument("--arch", default="x86_64", choices=["x86_64", "i386", "arm64"])
    p.add_argument("--darwin", default=None,
                   help="目标 Darwin 版本，例如 25.7.2。不给则不按 Min/MaxKernel 过滤")
    p.add_argument("--range", dest="range_mode", default="text",
                   choices=["text", "file"],
                   help="搜索范围：text = __TEXT 段（默认，与 72 分册第 1.2 节一致）；"
                        "file = 整个 slice")
    p.add_argument("--context", type=int, default=8,
                   help="每个命中前后各打印多少字节上下文，默认 8")
    p.add_argument("--expect", default=None, help="期望清单 JSON，用于门禁")
    p.add_argument("--emit-expect", default=None, help="把本次结果写成期望清单 JSON")
    p.add_argument("--json", dest="json_out", default=None, help="报告写到这个 JSON")
    p.add_argument("--quiet", action="store_true", help="只打印结论行")
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        with open(args.binary, "rb") as f:
            data = f.read()
        mo = MachO(data, args.arch)
        patches = load_patches(args.patches)
    except (OSError, MachOError, plistlib.InvalidFileException) as exc:
        sys.stderr.write("error: %s\n" % exc)
        return 2

    darwin = parse_kver(args.darwin, None)
    wanted_id = args.identifier

    report = {
        "schema": SCHEMA,
        "binary": os.path.basename(args.binary),
        "binary_path": args.binary,
        "binary_size": len(data),
        "binary_uuid": mo.uuid,
        "binary_sha256": sha256_file(args.binary),
        "binary_arch": mo.arch,
        "patches_file": os.path.basename(args.patches),
        "patches_sha256": sha256_file(args.patches),
        "darwin": args.darwin or "",
        "identifier_filter": wanted_id,
        "range_mode": args.range_mode,
        "segments": [
            {"name": s.name, "vmaddr": "0x%x" % s.vmaddr, "vmsize": "0x%x" % s.vmsize,
             "fileoff": "0x%x" % s.fileoff, "filesize": "0x%x" % s.filesize}
            for s in mo.segments],
        "patches": [],
    }

    try:
        for patch in patches:
            if wanted_id != "*" and patch.identifier != wanted_id:
                continue
            report["patches"].append(
                verify_patch(mo, data, patch, darwin, args.arch,
                             args.range_mode, args.context))
    except MachOError as exc:
        sys.stderr.write("error: %s\n" % exc)
        return 2

    selected = [r for r in report["patches"] if r["selected"]]
    report["selected_count"] = len(selected)

    if not args.quiet:
        print("target  : %s  (%s, %d bytes)" % (report["binary"], mo.arch, len(data)))
        print("LC_UUID : %s" % mo.uuid)
        print("sha256  : %s" % report["binary_sha256"])
        print("patches : %s  (sha256 %s)" % (report["patches_file"],
                                             report["patches_sha256"][:16]))
        print("filter  : Identifier=%s Arch=%s Darwin=%s range=%s"
              % (wanted_id, args.arch, args.darwin or "(any)", args.range_mode))
        print("selected: %d / %d entries" % (len(selected), len(report["patches"])))
        print("")
        for r in report["patches"]:
            head = "#%-3d key=%s  %s" % (r["ordinal"], r["key"], r["comment"][:72])
            if not r["selected"]:
                print("[skip] %s\n       -> %s" % (head, r["skip_reason"]))
                continue
            flag = "ok  " if not r["warnings"] else "WARN"
            print("[%s] %s" % (flag, head))
            print("       Base=%s  Count=%d Skip=%d Limit=%d  size=%d"
                  % (r["base"] or "(none)", r["count"], r["skip"], r["limit"],
                     len(r["find"].split()) if r["find"] else 0))
            print("       hits=%d  will-change=%d  range=[%s,%s)"
                  % (r["total_hits"], r["used_hits"],
                     r["search_start_off"], r["search_end_off"]))
            for h in r["hits"]:
                print("         %s %-20s %-34s %s"
                      % ("*" if h["will_change"] else " ",
                         h["va"] or h["file_off"], h["symbol"] or "?", h["orig"]))
                if h.get("patched"):
                    print("           %-20s %-34s %s" % ("", "-> patched", h["patched"]))
            for w in r["warnings"]:
                print("       ! %s" % w)
            print("")

    rc = 0
    if args.emit_expect:
        emit_expect(report, args.emit_expect)
        print("wrote expectations -> %s" % args.emit_expect)
        print("REVIEW IT BY HAND before committing. See 74-BOOT-CPU-DISPATCH.md §5.2.")

    if args.expect:
        try:
            with open(args.expect, "r", encoding="utf-8") as f:
                expect = json.load(f)
        except (OSError, ValueError) as exc:
            sys.stderr.write("error: cannot read --expect: %s\n" % exc)
            return 2
        failures, notes = check_expect(report, expect)
        report["gate"] = {"failures": failures, "notes": notes,
                          "passed": not failures}
        for n in notes:
            print("note : %s" % n)
        for fmsg in failures:
            print("FAIL : %s" % fmsg)
        if failures:
            print("\nGATE FAILED: %d problem(s)" % len(failures))
            rc = 1
        else:
            print("\nGATE PASSED: %d entries match the blessed expectations"
                  % len(selected))

    if args.json_out:
        d = os.path.dirname(os.path.abspath(args.json_out))
        if d and not os.path.isdir(d):
            os.makedirs(d, exist_ok=True)
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, ensure_ascii=False)
            f.write("\n")
        print("wrote report -> %s" % args.json_out)

    return rc


if __name__ == "__main__":
    sys.exit(main())
