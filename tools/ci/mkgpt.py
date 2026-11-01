#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
mkgpt.py —— 离线把 GPT 分区表写进一个普通文件。

为什么要有这个东西
------------------
`78` 第 A.1 节与 `75` 第 0.0.1 节原先的序列是：
    hdiutil attach -nomount <raw>   →  sudo gpt create -f /dev/rdiskN
                                    →  sudo gpt add ... /dev/rdiskN
取证 run 41271530800 的 `tooling` job 实测这条路在 GitHub macOS 运行器上**走不通**：

    gpt create: operation not permitted: create
    gpt add:    operation not permitted: add

而且运行器上 SIP 已经是 disabled、命令带 sudo、磁盘是刚 attach 的空镜像（无可卸载的卷）。
也就是说「关 SIP」「加 sudo」「先 unmount」这三条常规解释全部不成立。剩下的解释是
TCC（Full Disk Access）对裸设备节点 `/dev/rdiskN` 的写入做了拦截 —— 这一条对 root 也生效，
因为 TCC 归属的是发起进程而不是 euid。

结论：**不要往裸设备节点写分区表。** 分区表是文件头部的几个扇区，完全可以在
`hdiutil attach` 之前，以普通文件写入的方式放进镜像文件里。普通文件在
`$RUNNER_TEMP` 下，不受 TCC 约束，也不需要 sudo。`hdiutil attach` 之后
MediaKit 会解析这张表并给出 `/dev/diskNs1`、`/dev/diskNs2`，后续的
`diskutil apfs createContainer` / `newfs_msdos` 走的是 diskarbitrationd / apfsd
这些本身就有完整磁盘权限的系统守护进程，不受同一条限制。

这样整条装配链里就只剩这一个工具是我们自己写的，而它写的是 UEFI 2.x 规范里
完全确定的结构，没有任何需要猜的地方。

规范依据（UEFI Spec 2.10 第 5.3 节 "GUID Partition Table (GPT) Disk Layout"）
-----------------------------------------------------------------------------
LBA 0                      保护性 MBR（一个 0xEE 类型的分区项覆盖整盘）
LBA 1                      主 GPT 头（92 字节有效，余下扇区填零）
LBA 2 .. 33                主分区项数组（128 项 × 128 字节 = 16384 字节 = 32 扇区）
LBA 34                     first usable LBA
...
LBA last-33 .. last-1      备份分区项数组
LBA last                   备份 GPT 头
last usable LBA            = total_sectors - 34

GPT 头字段（偏移/长度）：
     0  / 8   签名 "EFI PART"
     8  / 4   revision 0x00010000
    12  / 4   header size = 92
    16  / 4   header CRC32（算的时候这 4 字节当零）
    20  / 4   reserved = 0
    24  / 8   my LBA
    32  / 8   alternate LBA
    40  / 8   first usable LBA
    48  / 8   last usable LBA
    56  / 16  disk GUID
    72  / 8   partition entry array LBA
    80  / 4   number of partition entries
    84  / 4   size of one partition entry
    88  / 4   partition entry array CRC32
分区项字段：
     0  / 16  partition type GUID
    16  / 16  unique partition GUID
    32  / 8   starting LBA
    40  / 8   ending LBA（含）
    48  / 8   attributes
    56  / 72  partition name，UTF-16LE，不足补零

GUID 的 on-disk 字节序是混合序：前三段小端、后两段大端。Python 的
`uuid.UUID(...).bytes_le` 正好就是这个序。自检里有一条已知向量钉住它。

用法
----
    # 我们的标准布局：ESP 512 MiB（type EFI）+ 其余全给 APFS 容器
    python3 mkgpt.py create disk.raw --size 20GiB --esp 512MiB

    # 任意布局。--part 可重复，START 与 SIZE 支持 auto
    python3 mkgpt.py create disk.raw --size 20GiB \
        --part auto:512MiB:efi:EFI \
        --part auto:auto:apfs:Container

    # 独立复核一张已经写好的表（不依赖写入时的中间状态，重新从字节解析）
    python3 mkgpt.py verify disk.raw

    # 不碰磁盘的自检：已知 GUID 字节序向量 + CRC32 向量 + 往返一致性
    python3 mkgpt.py selftest

退出码：0 正常；1 校验失败或参数错误。
"""

from __future__ import annotations

import argparse
import os
import struct
import sys
import uuid
import zlib

# 本文件的输出里有中文与 √/× 记号。macOS/Linux 的默认 locale 下没问题，
# Windows 控制台默认 cp1252 会在 print 时抛 UnicodeEncodeError，所以显式切 UTF-8。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
    except (AttributeError, ValueError):
        pass

# ───────────────────────────── 常量 ─────────────────────────────

GPT_SIGNATURE = b"EFI PART"
GPT_REVISION = 0x00010000
GPT_HEADER_SIZE = 92
GPT_ENTRY_SIZE = 128
GPT_ENTRY_COUNT = 128

DEFAULT_SECTOR = 512
DEFAULT_ALIGN_BYTES = 1024 * 1024  # 1 MiB，与 Apple 自己的布局一致

ZERO_GUID = uuid.UUID(int=0)

# 分区类型 GUID 别名。全部取自 Apple 的 `diskutil list` 实际输出与 UEFI 规范。
TYPE_ALIASES: dict[str, str] = {
    "efi": "C12A7328-F81F-11D2-BA4B-00A0C93EC93B",
    "esp": "C12A7328-F81F-11D2-BA4B-00A0C93EC93B",
    "apfs": "7C3457EF-0000-11AA-AA11-00306543ECAC",
    "hfs": "48465300-0000-11AA-AA11-00306543ECAC",
    "hfs+": "48465300-0000-11AA-AA11-00306543ECAC",
    "apple_boot": "426F6F74-0000-11AA-AA11-00306543ECAC",
    "recovery": "426F6F74-0000-11AA-AA11-00306543ECAC",
    "apple_core_storage": "53746F72-6167-11AA-AA11-00306543ECAC",
    "msdos": "EBD0A0A2-B9E5-4433-87C0-68B6B72699C7",
    "fat": "EBD0A0A2-B9E5-4433-87C0-68B6B72699C7",
    "basic_data": "EBD0A0A2-B9E5-4433-87C0-68B6B72699C7",
    "linux": "0FC63DAF-8483-4772-8E79-3D69D8477DE4",
}

# 反查表，verify 的输出里把 GUID 还原成人能读的名字
TYPE_NAMES: dict[str, str] = {}
for _alias, _guid in TYPE_ALIASES.items():
    TYPE_NAMES.setdefault(_guid.upper(), _alias)

_SIZE_UNITS = {
    "": 1,
    "B": 1,
    "K": 1000,
    "KB": 1000,
    "M": 1000**2,
    "MB": 1000**2,
    "G": 1000**3,
    "GB": 1000**3,
    "T": 1000**4,
    "TB": 1000**4,
    "KIB": 1024,
    "MIB": 1024**2,
    "GIB": 1024**3,
    "TIB": 1024**4,
}


class MkGptError(Exception):
    """参数或校验错误。main 捕获它并以退出码 1 退出。"""


# ───────────────────────────── 小工具 ─────────────────────────────


def parse_size(text: str) -> int:
    """把 '512MiB' / '20GiB' / '4294967296' / '0x100000' 解析成字节数。"""
    s = str(text).strip().replace("_", "")
    if not s:
        raise MkGptError("空的大小")
    if s.lower().startswith("0x"):
        return int(s, 16)
    i = 0
    while i < len(s) and (s[i].isdigit() or s[i] == "."):
        i += 1
    num_part, unit_part = s[:i], s[i:].strip().upper()
    if not num_part:
        raise MkGptError(f"大小 {text!r} 里没有数字")
    if unit_part not in _SIZE_UNITS:
        raise MkGptError(f"不认识的单位 {unit_part!r}（来自 {text!r}）")
    value = float(num_part) * _SIZE_UNITS[unit_part]
    if value != int(value):
        raise MkGptError(f"大小 {text!r} 不是整字节")
    return int(value)


def parse_type_guid(text: str) -> uuid.UUID:
    """别名或 GUID 字符串 → UUID。"""
    key = text.strip().lower()
    if key in TYPE_ALIASES:
        return uuid.UUID(TYPE_ALIASES[key])
    try:
        return uuid.UUID(text.strip())
    except ValueError as exc:
        known = ", ".join(sorted(set(TYPE_ALIASES)))
        raise MkGptError(
            f"分区类型 {text!r} 既不是已知别名也不是合法 GUID。已知别名：{known}"
        ) from exc


def align_up(value: int, align: int) -> int:
    if align <= 1:
        return value
    return ((value + align - 1) // align) * align


def align_down(value: int, align: int) -> int:
    if align <= 1:
        return value
    return (value // align) * align


def human(nbytes: int) -> str:
    for unit, scale in (("GiB", 1024**3), ("MiB", 1024**2), ("KiB", 1024)):
        if nbytes >= scale:
            return f"{nbytes / scale:.2f} {unit}"
    return f"{nbytes} B"


# ───────────────────────────── 结构体编解码 ─────────────────────────────


class Partition:
    """一个分区项。start/end 以 LBA 计，end 含在内。"""

    __slots__ = ("type_guid", "part_guid", "start_lba", "end_lba", "attributes", "name")

    def __init__(
        self,
        type_guid: uuid.UUID,
        start_lba: int,
        end_lba: int,
        name: str = "",
        part_guid: uuid.UUID | None = None,
        attributes: int = 0,
    ) -> None:
        self.type_guid = type_guid
        self.part_guid = part_guid if part_guid is not None else uuid.uuid4()
        self.start_lba = start_lba
        self.end_lba = end_lba
        self.attributes = attributes
        self.name = name

    @property
    def sectors(self) -> int:
        return self.end_lba - self.start_lba + 1

    def pack(self) -> bytes:
        name_utf16 = self.name.encode("utf-16-le")
        if len(name_utf16) > 72:
            raise MkGptError(f"分区名 {self.name!r} 超过 36 个 UTF-16 码元")
        return (
            self.type_guid.bytes_le
            + self.part_guid.bytes_le
            + struct.pack("<QQQ", self.start_lba, self.end_lba, self.attributes)
            + name_utf16.ljust(72, b"\x00")
        )

    @classmethod
    def unpack(cls, raw: bytes) -> "Partition":
        if len(raw) != GPT_ENTRY_SIZE:
            raise MkGptError(f"分区项长度 {len(raw)} != {GPT_ENTRY_SIZE}")
        type_guid = uuid.UUID(bytes_le=raw[0:16])
        part_guid = uuid.UUID(bytes_le=raw[16:32])
        start, end, attrs = struct.unpack("<QQQ", raw[32:56])
        name = raw[56:128].decode("utf-16-le", errors="replace").rstrip("\x00")
        return cls(type_guid, start, end, name, part_guid, attrs)

    def is_used(self) -> bool:
        return self.type_guid != ZERO_GUID

    def type_label(self) -> str:
        return TYPE_NAMES.get(str(self.type_guid).upper(), "（未知类型）")


def pack_entry_array(parts: list[Partition]) -> bytes:
    """128 项定长数组。用掉的排在前面，其余填零项。"""
    if len(parts) > GPT_ENTRY_COUNT:
        raise MkGptError(f"分区数 {len(parts)} 超过 {GPT_ENTRY_COUNT}")
    blob = b"".join(p.pack() for p in parts)
    return blob.ljust(GPT_ENTRY_COUNT * GPT_ENTRY_SIZE, b"\x00")


def pack_header(
    *,
    my_lba: int,
    alt_lba: int,
    first_usable: int,
    last_usable: int,
    disk_guid: uuid.UUID,
    entry_lba: int,
    entry_count: int,
    entry_size: int,
    entry_crc: int,
) -> bytes:
    """算出 header CRC 并返回 92 字节的头。CRC 字段先当零参与计算。"""
    body = (
        GPT_SIGNATURE
        + struct.pack("<II", GPT_REVISION, GPT_HEADER_SIZE)
        + struct.pack("<I", 0)  # header CRC 占位
        + struct.pack("<I", 0)  # reserved
        + struct.pack("<QQQQ", my_lba, alt_lba, first_usable, last_usable)
        + disk_guid.bytes_le
        + struct.pack("<QIII", entry_lba, entry_count, entry_size, entry_crc)
    )
    if len(body) != GPT_HEADER_SIZE:
        raise MkGptError(f"头长度算错了：{len(body)} != {GPT_HEADER_SIZE}")
    crc = zlib.crc32(body) & 0xFFFFFFFF
    return body[:16] + struct.pack("<I", crc) + body[20:]


def unpack_header(raw: bytes) -> dict:
    """解析一个 GPT 头并自验 CRC。返回字段字典，多一个 crc_ok 键。"""
    if len(raw) < GPT_HEADER_SIZE:
        raise MkGptError("头扇区太短")
    head = raw[:GPT_HEADER_SIZE]
    sig = head[0:8]
    revision, header_size = struct.unpack("<II", head[8:16])
    stored_crc = struct.unpack("<I", head[16:20])[0]
    reserved = struct.unpack("<I", head[20:24])[0]
    my_lba, alt_lba, first_usable, last_usable = struct.unpack("<QQQQ", head[24:56])
    disk_guid = uuid.UUID(bytes_le=head[56:72])
    entry_lba, entry_count, entry_size, entry_crc = struct.unpack("<QIII", head[72:92])

    zeroed = head[:16] + b"\x00\x00\x00\x00" + head[20:GPT_HEADER_SIZE]
    computed = zlib.crc32(zeroed) & 0xFFFFFFFF

    return {
        "signature": sig,
        "revision": revision,
        "header_size": header_size,
        "header_crc": stored_crc,
        "header_crc_computed": computed,
        "crc_ok": computed == stored_crc,
        "reserved": reserved,
        "my_lba": my_lba,
        "alternate_lba": alt_lba,
        "first_usable_lba": first_usable,
        "last_usable_lba": last_usable,
        "disk_guid": disk_guid,
        "entry_lba": entry_lba,
        "entry_count": entry_count,
        "entry_size": entry_size,
        "entry_crc": entry_crc,
    }


def pack_protective_mbr(total_sectors: int) -> bytes:
    """
    保护性 MBR。一个 0xEE 类型的分区项从 LBA 1 覆盖到盘尾（上限 0xFFFFFFFF）。
    CHS 字段按规范填「最大值」形式，让旧工具不敢动它。
    """
    mbr = bytearray(DEFAULT_SECTOR)
    span = min(total_sectors - 1, 0xFFFFFFFF)
    entry = bytes(
        [
            0x00,  # boot indicator：非活动
            0x00,
            0x02,
            0x00,  # 起始 CHS = 0/0/2
            0xEE,  # 类型：GPT protective
            0xFF,
            0xFF,
            0xFF,  # 结束 CHS = 最大
        ]
    ) + struct.pack("<II", 1, span)
    assert len(entry) == 16
    mbr[446:462] = entry
    mbr[510:512] = b"\x55\xAA"
    return bytes(mbr)


# ───────────────────────────── 布局计算 ─────────────────────────────


class Layout:
    """一块盘的几何与分区清单。"""

    def __init__(self, total_bytes: int, sector: int = DEFAULT_SECTOR) -> None:
        if sector not in (512, 1024, 2048, 4096):
            raise MkGptError(f"扇区大小 {sector} 不受支持")
        if total_bytes % sector:
            raise MkGptError(f"镜像大小 {total_bytes} 不是扇区大小 {sector} 的整数倍")
        self.sector = sector
        self.total_bytes = total_bytes
        self.total_sectors = total_bytes // sector
        self.entry_array_sectors = (
            GPT_ENTRY_COUNT * GPT_ENTRY_SIZE + sector - 1
        ) // sector
        # LBA 0 = MBR，LBA 1 = 主头，主项数组紧随其后
        self.primary_entry_lba = 2
        self.first_usable = 2 + self.entry_array_sectors
        self.backup_header_lba = self.total_sectors - 1
        self.backup_entry_lba = self.backup_header_lba - self.entry_array_sectors
        self.last_usable = self.backup_entry_lba - 1
        if self.last_usable <= self.first_usable:
            raise MkGptError(f"镜像太小（{human(total_bytes)}），放不下一张 GPT")
        self.parts: list[Partition] = []

    # — 规范要求 first_usable/last_usable 恰好夹住两套元数据，这里再断言一次 —
    def assert_geometry(self) -> None:
        expect_first = 2 + self.entry_array_sectors
        expect_last = self.total_sectors - self.entry_array_sectors - 2
        if self.first_usable != expect_first:
            raise MkGptError(f"first usable 应为 {expect_first}，实为 {self.first_usable}")
        if self.last_usable != expect_last:
            raise MkGptError(f"last usable 应为 {expect_last}，实为 {self.last_usable}")

    def next_free_lba(self, align_bytes: int) -> int:
        cursor = self.first_usable
        for p in self.parts:
            cursor = max(cursor, p.end_lba + 1)
        return align_up(cursor, max(1, align_bytes // self.sector))

    def add(
        self,
        type_guid: uuid.UUID,
        name: str,
        start_lba: int | None,
        size_bytes: int | None,
        align_bytes: int,
        part_guid: uuid.UUID | None = None,
    ) -> Partition:
        align_sectors = max(1, align_bytes // self.sector)
        start = self.next_free_lba(align_bytes) if start_lba is None else start_lba
        if size_bytes is None:
            # 吃到盘尾，尾部按对齐向下取整，留出的零头不用
            end = align_down(self.last_usable + 1, align_sectors) - 1
            if end > self.last_usable:
                end = self.last_usable
        else:
            if size_bytes % self.sector:
                raise MkGptError(
                    f"分区 {name!r} 的大小 {size_bytes} 不是扇区 {self.sector} 的整数倍"
                )
            end = start + size_bytes // self.sector - 1
        if start < self.first_usable:
            raise MkGptError(
                f"分区 {name!r} 起始 LBA {start} 在 first usable {self.first_usable} 之前"
            )
        if end > self.last_usable:
            raise MkGptError(
                f"分区 {name!r} 结束 LBA {end} 越过 last usable {self.last_usable}"
                f"（缺 {human((end - self.last_usable) * self.sector)}）"
            )
        if end < start:
            raise MkGptError(f"分区 {name!r} 大小为零或为负")
        for other in self.parts:
            if not (end < other.start_lba or start > other.end_lba):
                raise MkGptError(
                    f"分区 {name!r}（{start}..{end}）与 {other.name!r}"
                    f"（{other.start_lba}..{other.end_lba}）重叠"
                )
        p = Partition(type_guid, start, end, name, part_guid)
        self.parts.append(p)
        self.parts.sort(key=lambda x: x.start_lba)
        return p


def write_gpt(path: str, layout: Layout, disk_guid: uuid.UUID) -> None:
    """把 MBR + 主/备头 + 主/备项数组写进 path。文件先被 truncate 到 layout 的大小。"""
    layout.assert_geometry()
    sector = layout.sector
    entries = pack_entry_array(layout.parts)
    entry_crc = zlib.crc32(entries) & 0xFFFFFFFF

    primary = pack_header(
        my_lba=1,
        alt_lba=layout.backup_header_lba,
        first_usable=layout.first_usable,
        last_usable=layout.last_usable,
        disk_guid=disk_guid,
        entry_lba=layout.primary_entry_lba,
        entry_count=GPT_ENTRY_COUNT,
        entry_size=GPT_ENTRY_SIZE,
        entry_crc=entry_crc,
    )
    backup = pack_header(
        my_lba=layout.backup_header_lba,
        alt_lba=1,
        first_usable=layout.first_usable,
        last_usable=layout.last_usable,
        disk_guid=disk_guid,
        entry_lba=layout.backup_entry_lba,
        entry_count=GPT_ENTRY_COUNT,
        entry_size=GPT_ENTRY_SIZE,
        entry_crc=entry_crc,
    )

    # 不存在就建；存在就保留内容，只重写元数据区。镜像大小以 layout 为准。
    if not os.path.exists(path):
        with open(path, "wb"):
            pass
    with open(path, "r+b") as fh:
        fh.truncate(layout.total_bytes)
        fh.seek(0)
        fh.write(pack_protective_mbr(layout.total_sectors))
        fh.seek(1 * sector)
        fh.write(primary.ljust(sector, b"\x00"))
        fh.seek(layout.primary_entry_lba * sector)
        fh.write(entries)
        fh.seek(layout.backup_entry_lba * sector)
        fh.write(entries)
        fh.seek(layout.backup_header_lba * sector)
        fh.write(backup.ljust(sector, b"\x00"))
        fh.flush()
        os.fsync(fh.fileno())


# ───────────────────────────── verify ─────────────────────────────


def verify(path: str, sector: int = DEFAULT_SECTOR, quiet: bool = False) -> list[str]:
    """
    从字节重新解析一张 GPT，逐条核对。返回问题清单（空表示全过）。
    刻意不复用 write_gpt 的中间结果：这是独立复核，不是回显。
    """
    problems: list[str] = []

    def say(*a: object) -> None:
        if not quiet:
            print(*a)

    size = os.path.getsize(path)
    total_sectors = size // sector
    say(f"镜像      : {path}")
    say(f"大小      : {size} 字节（{human(size)}），{total_sectors} 个 {sector} 字节扇区")
    if size % sector:
        problems.append(f"文件大小 {size} 不是扇区 {sector} 的整数倍")

    with open(path, "rb") as fh:
        mbr = fh.read(sector)

        # —— 保护性 MBR ——
        if mbr[510:512] != b"\x55\xAA":
            problems.append("保护性 MBR 缺少 0x55AA 签名")
        if mbr[446 + 4] != 0xEE:
            problems.append(f"MBR 第一项类型是 0x{mbr[446 + 4]:02X}，不是 0xEE")
        mbr_start, mbr_span = struct.unpack("<II", mbr[446 + 8 : 446 + 16])
        if mbr_start != 1:
            problems.append(f"MBR 保护项起始 LBA 是 {mbr_start}，应为 1")
        expect_span = min(total_sectors - 1, 0xFFFFFFFF)
        if mbr_span != expect_span:
            problems.append(f"MBR 保护项长度 {mbr_span}，应为 {expect_span}")
        say(f"保护性 MBR: 类型 0x{mbr[446 + 4]:02X}，LBA {mbr_start}，{mbr_span} 扇区")

        # —— 主头 ——
        fh.seek(1 * sector)
        ph = unpack_header(fh.read(sector))
        if ph["signature"] != GPT_SIGNATURE:
            problems.append(f"主头签名是 {ph['signature']!r}，不是 {GPT_SIGNATURE!r}")
        if not ph["crc_ok"]:
            problems.append(
                f"主头 CRC 不符：盘上 0x{ph['header_crc']:08X}，"
                f"算出 0x{ph['header_crc_computed']:08X}"
            )
        if ph["header_size"] != GPT_HEADER_SIZE:
            problems.append(f"主头声明长度 {ph['header_size']}，应为 {GPT_HEADER_SIZE}")
        if ph["revision"] != GPT_REVISION:
            problems.append(f"主头 revision 0x{ph['revision']:08X}")
        if ph["my_lba"] != 1:
            problems.append(f"主头 my LBA = {ph['my_lba']}，应为 1")

        say(
            f"主头      : LBA 1，备份在 {ph['alternate_lba']}，"
            f"可用 {ph['first_usable_lba']}..{ph['last_usable_lba']}，"
            f"disk GUID {ph['disk_guid']}"
        )
        say(
            f"            项数组 LBA {ph['entry_lba']}，{ph['entry_count']} × "
            f"{ph['entry_size']} 字节，CRC 0x{ph['entry_crc']:08X}"
        )

        # —— 几何 ——
        entry_sectors = (
            ph["entry_count"] * ph["entry_size"] + sector - 1
        ) // sector
        if ph["first_usable_lba"] != 2 + entry_sectors:
            problems.append(
                f"first usable {ph['first_usable_lba']} != 2+{entry_sectors}"
            )
        if ph["last_usable_lba"] != total_sectors - entry_sectors - 2:
            problems.append(
                f"last usable {ph['last_usable_lba']} != "
                f"{total_sectors - entry_sectors - 2}"
            )
        if ph["alternate_lba"] != total_sectors - 1:
            problems.append(
                f"alternate LBA {ph['alternate_lba']} != {total_sectors - 1}"
            )

        # —— 主项数组 ——
        fh.seek(ph["entry_lba"] * sector)
        primary_entries = fh.read(ph["entry_count"] * ph["entry_size"])
        computed = zlib.crc32(primary_entries) & 0xFFFFFFFF
        if computed != ph["entry_crc"]:
            problems.append(
                f"主项数组 CRC 不符：头里 0x{ph['entry_crc']:08X}，算出 0x{computed:08X}"
            )

        # —— 备份头 ——
        fh.seek((total_sectors - 1) * sector)
        bh = unpack_header(fh.read(sector))
        if bh["signature"] != GPT_SIGNATURE:
            problems.append("备份头签名不对")
        if not bh["crc_ok"]:
            problems.append("备份头 CRC 不符")
        if bh["my_lba"] != total_sectors - 1:
            problems.append(f"备份头 my LBA = {bh['my_lba']}")
        if bh["alternate_lba"] != 1:
            problems.append(f"备份头 alternate LBA = {bh['alternate_lba']}，应为 1")
        for key in ("first_usable_lba", "last_usable_lba", "disk_guid", "entry_crc"):
            if ph[key] != bh[key]:
                problems.append(f"主/备头字段 {key} 不一致：{ph[key]} vs {bh[key]}")
        say(f"备份头    : LBA {bh['my_lba']}，项数组 LBA {bh['entry_lba']}")

        # —— 备份项数组必须与主项数组逐字节相同 ——
        fh.seek(bh["entry_lba"] * sector)
        backup_entries = fh.read(bh["entry_count"] * bh["entry_size"])
        if backup_entries != primary_entries:
            problems.append("备份项数组与主项数组不是逐字节相同")

    # —— 分区项 ——
    parts: list[tuple[int, Partition]] = []
    for idx in range(ph["entry_count"]):
        raw = primary_entries[idx * ph["entry_size"] : (idx + 1) * ph["entry_size"]]
        if len(raw) != GPT_ENTRY_SIZE:
            break
        p = Partition.unpack(raw)
        if p.is_used():
            parts.append((idx + 1, p))

    say(f"分区       : {len(parts)} 个在用")
    for num, p in parts:
        say(
            f"  s{num}  LBA {p.start_lba}..{p.end_lba}  "
            f"{p.sectors} 扇区 = {human(p.sectors * sector)}"
        )
        say(f"       类型 {p.type_guid}  ({p.type_label()})")
        say(f"       唯一 {p.part_guid}  名称 {p.name!r}  属性 0x{p.attributes:016X}")

    for num, p in parts:
        if p.start_lba < ph["first_usable_lba"]:
            problems.append(f"s{num} 起始越过 first usable")
        if p.end_lba > ph["last_usable_lba"]:
            problems.append(f"s{num} 结束越过 last usable")
        if p.end_lba < p.start_lba:
            problems.append(f"s{num} 大小非正")
        if p.part_guid == ZERO_GUID:
            problems.append(f"s{num} 的唯一 GUID 是全零")
    for i in range(len(parts) - 1):
        (na, a), (nb, b) = parts[i], parts[i + 1]
        if a.end_lba >= b.start_lba:
            problems.append(f"s{na} 与 s{nb} 重叠")

    if problems:
        say("")
        say(f"×  {len(problems)} 条问题：")
        for msg in problems:
            say(f"   - {msg}")
    else:
        say("")
        say("√  全部校验通过（MBR、主/备头 CRC、项数组 CRC、几何、边界、重叠）")
    return problems


# ───────────────────────────── selftest ─────────────────────────────


def selftest() -> int:
    """不碰磁盘设备的自检。任何一条不过就返回非零。"""
    failures: list[str] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        print(f"  [{'√' if ok else '×'}] {name}" + (f"  {detail}" if detail else ""))
        if not ok:
            failures.append(name)

    print("1. GUID 混合字节序（UEFI 5.3.3 的 on-disk 形式）")
    esp = uuid.UUID(TYPE_ALIASES["efi"])
    want = bytes(
        [
            0x28, 0x73, 0x2A, 0xC1,
            0x1F, 0xF8,
            0xD2, 0x11,
            0xBA, 0x4B,
            0x00, 0xA0, 0xC9, 0x3E, 0xC9, 0x3B,
        ]
    )
    check(
        "ESP GUID C12A7328-F81F-11D2-BA4B-00A0C93EC93B 的 16 字节",
        esp.bytes_le == want,
        esp.bytes_le.hex(),
    )
    apfs = uuid.UUID(TYPE_ALIASES["apfs"])
    want_apfs = bytes(
        [
            0xEF, 0x57, 0x34, 0x7C,
            0x00, 0x00,
            0xAA, 0x11,
            0xAA, 0x11,
            0x00, 0x30, 0x65, 0x43, 0xEC, 0xAC,
        ]
    )
    check(
        "APFS GUID 7C3457EF-0000-11AA-AA11-00306543ECAC 的 16 字节",
        apfs.bytes_le == want_apfs,
        apfs.bytes_le.hex(),
    )
    check("bytes_le 往返", uuid.UUID(bytes_le=esp.bytes_le) == esp)

    print("2. CRC32 已知向量（GPT 用的就是 zlib 的那一支）")
    check('crc32("123456789") == 0xCBF43926', zlib.crc32(b"123456789") == 0xCBF43926,
          f"0x{zlib.crc32(b'123456789'):08X}")
    check("crc32(b'') == 0", zlib.crc32(b"") == 0)

    print("3. 结构体长度")
    p = Partition(esp, 2048, 4095, "EFI", uuid.UUID(int=1))
    check("分区项 128 字节", len(p.pack()) == GPT_ENTRY_SIZE, str(len(p.pack())))
    check("项数组 16384 字节", len(pack_entry_array([p])) == 16384)
    hdr = pack_header(
        my_lba=1, alt_lba=100, first_usable=34, last_usable=66,
        disk_guid=uuid.UUID(int=2), entry_lba=2,
        entry_count=GPT_ENTRY_COUNT, entry_size=GPT_ENTRY_SIZE, entry_crc=0,
    )
    check("GPT 头 92 字节", len(hdr) == GPT_HEADER_SIZE, str(len(hdr)))
    check("保护性 MBR 512 字节", len(pack_protective_mbr(1000)) == 512)

    print("4. 头 CRC 的算法：把 16..20 当零、只算前 92 字节")
    parsed = unpack_header(hdr.ljust(512, b"\x00"))
    check("自解自验 CRC 对得上", parsed["crc_ok"],
          f"0x{parsed['header_crc']:08X}")
    tampered = bytearray(hdr)
    tampered[24] ^= 0xFF  # 改 my_lba
    check("改一个字节后 CRC 必须失配",
          not unpack_header(bytes(tampered).ljust(512, b"\x00"))["crc_ok"])

    print("5. 分区项解包是编包的逆")
    back = Partition.unpack(p.pack())
    check(
        "往返一致",
        (back.type_guid, back.part_guid, back.start_lba, back.end_lba, back.name)
        == (p.type_guid, p.part_guid, p.start_lba, p.end_lba, p.name),
    )

    print("6. 布局算术（20 GiB，ESP 512 MiB，其余 APFS）")
    lay = Layout(20 * 1024**3)
    lay.assert_geometry()
    check("first usable == 34", lay.first_usable == 34, str(lay.first_usable))
    check("last usable == total-34",
          lay.last_usable == lay.total_sectors - 34, str(lay.last_usable))
    e = lay.add(esp, "EFI", None, 512 * 1024**2, DEFAULT_ALIGN_BYTES)
    c = lay.add(apfs, "Container", None, None, DEFAULT_ALIGN_BYTES)
    check("ESP 起始 LBA 2048（1 MiB 对齐）", e.start_lba == 2048, str(e.start_lba))
    check("ESP 恰好 512 MiB", e.sectors * 512 == 512 * 1024**2)
    check("APFS 紧接 ESP 之后", c.start_lba == e.end_lba + 1, str(c.start_lba))
    check("APFS 不越过 last usable", c.end_lba <= lay.last_usable)
    check("两分区不重叠", e.end_lba < c.start_lba)

    print("7. 越界与重叠必须被拒")
    try:
        bad = Layout(1 * 1024**2)
        bad.add(apfs, "X", None, 900 * 1024**2, DEFAULT_ALIGN_BYTES)
        check("超出盘尾被拒", False, "没报错")
    except MkGptError:
        check("超出盘尾被拒", True)
    try:
        bad2 = Layout(1024**3)
        bad2.add(apfs, "A", 2048, 16 * 1024**2, DEFAULT_ALIGN_BYTES)
        bad2.add(apfs, "B", 4096, 16 * 1024**2, DEFAULT_ALIGN_BYTES)
        check("重叠被拒", False, "没报错")
    except MkGptError:
        check("重叠被拒", True)

    print("8. 写一张真表到临时文件再独立复核（含 1 字节篡改必须被抓到）")
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        img = os.path.join(td, "selftest.raw")
        lay2 = Layout(64 * 1024**2)
        lay2.add(esp, "EFI", None, 16 * 1024**2, DEFAULT_ALIGN_BYTES,
                 part_guid=uuid.UUID(int=0x1111))
        lay2.add(apfs, "Container", None, None, DEFAULT_ALIGN_BYTES,
                 part_guid=uuid.UUID(int=0x2222))
        write_gpt(img, lay2, uuid.UUID(int=0x3333))
        probs = verify(img, quiet=True)
        check("刚写出的表零问题", not probs, "；".join(probs))
        check("文件大小正好 64 MiB", os.path.getsize(img) == 64 * 1024**2)
        with open(img, "r+b") as fh:  # 篡改主项数组里 ESP 的起始 LBA
            fh.seek(2 * 512 + 32)
            fh.write(b"\x99")
        probs2 = verify(img, quiet=True)
        check("篡改主项数组后被抓到", bool(probs2), f"{len(probs2)} 条")

    print("")
    if failures:
        print(f"×  自检失败 {len(failures)} 条：" + "；".join(failures))
        return 1
    print("√  自检全过")
    return 0


# ───────────────────────────── CLI ─────────────────────────────


def cmd_create(args: argparse.Namespace) -> int:
    total = parse_size(args.size)
    layout = Layout(total, args.sector)
    align = parse_size(args.align)

    specs: list[str] = list(args.part or [])
    if not specs:
        # 默认就是 75 §0.0.1 / 78 §A.1 的两分区布局
        specs = [f"auto:{args.esp}:efi:EFI", "auto:auto:apfs:Container"]

    for spec in specs:
        bits = spec.split(":")
        if len(bits) != 4:
            raise MkGptError(
                f"--part {spec!r} 格式应为 START:SIZE:TYPE:NAME"
                "（START 与 SIZE 可写 auto）"
            )
        start_s, size_s, type_s, name = bits
        start = None if start_s.lower() in ("auto", "") else parse_size(start_s) // layout.sector
        size = None if size_s.lower() in ("auto", "rest", "") else parse_size(size_s)
        layout.add(parse_type_guid(type_s), name, start, size, align)

    disk_guid = uuid.UUID(args.disk_guid) if args.disk_guid else uuid.uuid4()
    write_gpt(args.image, layout, disk_guid)
    print(f"已写入 GPT：{args.image}")
    print(
        f"  几何：{layout.total_sectors} 扇区 × {layout.sector} 字节 = "
        f"{human(layout.total_bytes)}；可用 "
        f"{layout.first_usable}..{layout.last_usable}"
    )
    for i, p in enumerate(layout.parts, 1):
        print(
            f"  s{i}  {p.name:<12} {p.type_label():<6} "
            f"LBA {p.start_lba}..{p.end_lba}  {human(p.sectors * layout.sector)}"
        )
    print("")
    print("—— 独立复核 ——")
    problems = verify(args.image, layout.sector)
    return 1 if problems else 0


def cmd_verify(args: argparse.Namespace) -> int:
    return 1 if verify(args.image, args.sector) else 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="mkgpt.py",
        description="离线把 GPT 分区表写进一个普通文件（不碰 /dev，不需要 sudo）",
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("create", help="建立/重写一张 GPT")
    c.add_argument("image", help="目标镜像文件路径（不存在则创建）")
    c.add_argument("--size", required=True, help="镜像总大小，如 20GiB")
    c.add_argument("--esp", default="512MiB", help="默认布局里 ESP 的大小（默认 512MiB）")
    c.add_argument(
        "--part",
        action="append",
        metavar="START:SIZE:TYPE:NAME",
        help="显式分区项，可重复。给了就不用默认布局。START/SIZE 可写 auto",
    )
    c.add_argument("--sector", type=int, default=DEFAULT_SECTOR, help="扇区大小（默认 512）")
    c.add_argument("--align", default=str(DEFAULT_ALIGN_BYTES), help="分区对齐（默认 1MiB）")
    c.add_argument("--disk-guid", default=None, help="固定 disk GUID，便于复现")
    c.set_defaults(func=cmd_create)

    v = sub.add_parser("verify", help="独立复核一张已写好的 GPT")
    v.add_argument("image")
    v.add_argument("--sector", type=int, default=DEFAULT_SECTOR)
    v.set_defaults(func=cmd_verify)

    s = sub.add_parser("selftest", help="不碰磁盘的自检")
    s.set_defaults(func=lambda _a: selftest())

    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args))
    except MkGptError as exc:
        print(f"mkgpt: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
