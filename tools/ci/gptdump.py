#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把一张 GPT 的原始字节按 UEFI 规范的字段表逐条打出来。

两个用处：
  1. 开发期核对 `mkgpt.py` 写出来的字段偏移对不对（人工对账一次即可）。
  2. CI 里做 A/B：先让 `diskutil partitionDisk` 往一个 scratch 镜像文件写它自己的 GPT，
     再用本脚本读那个**普通文件**（不是 /dev 节点，所以不受 TCC 约束）把 Apple 的表
     逐字段打出来，与 `mkgpt.py` 的输出并排比。差异就是我们要对齐的地方
     （项数、对齐、分区名、属性位）。

本脚本只读，不写，不解释语义，也不做任何校验 —— 校验是 `mkgpt.py verify` 的事。
这里刻意保持「哑读」，这样它永远不会和 mkgpt.py 犯同一个错。

用法: python3 tools/ci/gptdump.py <image-file> [sector-size]
"""
from __future__ import annotations

import os
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
except Exception:
    pass

HDR = [
    (0, 8, "signature"), (8, 4, "revision"), (12, 4, "header_size"),
    (16, 4, "header_crc"), (20, 4, "reserved"), (24, 8, "my_lba"),
    (32, 8, "alternate_lba"), (40, 8, "first_usable"), (48, 8, "last_usable"),
    (56, 16, "disk_guid"), (72, 8, "entry_array_lba"), (80, 4, "num_entries"),
    (84, 4, "entry_size"), (88, 4, "entry_array_crc"),
]
ENT = [
    (0, 16, "type_guid"), (16, 16, "unique_guid"), (32, 8, "first_lba"),
    (40, 8, "last_lba"), (48, 8, "attributes"),
]


def le(b: bytes) -> int:
    return int.from_bytes(b, "little")


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 1
    path = argv[1]
    sector = int(argv[2]) if len(argv) > 2 else 512

    size = os.path.getsize(path)
    nsec = size // sector
    print(f"file      : {path}")
    print(f"size      : {size} ({size / 1024 ** 3:.3f} GiB), {nsec} sectors of {sector}")

    with open(path, "rb") as f:
        f.seek(446)
        mbr_e1 = f.read(16)
        f.seek(510)
        mbr_sig = f.read(2)
        print(f"MBR e1    : {mbr_e1.hex(' ')}")
        print(
            f"            type=0x{mbr_e1[4]:02X} first_lba={le(mbr_e1[8:12])} "
            f"sectors={le(mbr_e1[12:16])}"
        )
        print(f"MBR sig   : {mbr_sig.hex(' ')}")

        # 主头先读出来，项数组的位置/项数/项长全部按它说的走，不假定 2/128/128
        f.seek(1 * sector)
        ph = f.read(92)
        entry_lba = le(ph[72:80])
        n_entries = le(ph[80:84])
        entry_size = le(ph[84:88])

        for label, lba in (("PRIMARY", 1), ("BACKUP", nsec - 1)):
            f.seek(lba * sector)
            h = f.read(92)
            print(f"\n== {label} HEADER @ LBA {lba} ==")
            print(h.hex(" "))
            for off, ln, name in HDR:
                raw = h[off:off + ln]
                extra = ""
                if ln in (4, 8) and name not in ("signature", "disk_guid"):
                    extra = f"= {le(raw)}"
                print(f"  {off:3d} +{ln:2d}  {name:<16} {raw.hex(' '):<48}{extra}")

        if not (0 < n_entries <= 1024 and entry_size in (128, 256, 512)):
            print(f"\n主头声明的项数组参数不合常理（{n_entries} × {entry_size}），停在这里")
            return 0

        arr_bytes = n_entries * entry_size
        print(
            f"\n== PRIMARY ENTRY ARRAY @ LBA {entry_lba}，"
            f"{n_entries} × {entry_size} = {arr_bytes} 字节 =="
        )
        f.seek(entry_lba * sector)
        primary = f.read(arr_bytes)

        used = 0
        for n in range(n_entries):
            e = primary[n * entry_size:(n + 1) * entry_size]
            if len(e) < 128 or e[0:16] == b"\x00" * 16:
                continue
            used += 1
            name_raw = e[56:128]
            label = name_raw.decode("utf-16-le", errors="replace").rstrip("\x00")
            first, last = le(e[32:40]), le(e[40:48])
            print(f"\n  -- entry {n + 1} (s{used}) --")
            for off, ln, nm in ENT:
                print(f"    {off:3d} +{ln:2d}  {nm:<14} {e[off:off + ln].hex(' ')}")
            print(f"     56 +72  name           {label!r}")
            print(
                f"            → LBA {first}..{last} = {last - first + 1} 扇区"
                f" = {(last - first + 1) * sector / 1024 ** 2:.2f} MiB"
            )
        print(f"\n在用项数: {used}")

        # 备份项数组逐字节比对（位置取备份头自己说的，不假定）
        f.seek((nsec - 1) * sector)
        bh = f.read(92)
        f.seek(le(bh[72:80]) * sector)
        backup = f.read(arr_bytes)
        print(f"primary vs backup entry array identical: {primary == backup}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
