#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""看一眼 UpdateBrain.zip 里那个 XPC service 的接口面。

UpdateBrain 是 Apple 自己用来 apply `payloadv2` 资产的东西。它知道怎么写
system volume、怎么造封印、怎么布 Preboot 与 cryptex —— 也就是我们自己
造不出来的那几样。所以它的接口面决定了「能不能让 Apple 的工具替我们干
这件事」这个问题的答案。
"""
import io
import plistlib
import re
import sys
import zipfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

Z = "142-36613 - 26.7.2 macOS Tahoe (25G325)/UpdateBrain.zip"
B = "AssetData/com.apple.MobileSoftwareUpdate.UpdateBrainService.xpc/Contents/"

z = zipfile.ZipFile(Z)


def show_plist(name: str, limit: int = 2500) -> None:
    print("=" * 72)
    print(name)
    print("=" * 72)
    try:
        d = plistlib.load(io.BytesIO(z.read(name)))
    except Exception as exc:                      # noqa: BLE001
        print(f"  ERROR: {exc}")
        return
    txt = plistlib.dumps(d).decode("utf-8", "replace")
    print(txt[:limit])
    if len(txt) > limit:
        print(f"  ... (+{len(txt) - limit} bytes)")


for n in (B + "Info.plist",
          B + "Resources/com.apple.MobileSoftwareUpdate.plist",
          "Info.plist",
          "System/Library/CoreServices/RestoreVersion.plist"):
    show_plist(n)

print("=" * 72)
print(B + "Resources/UpdateBrainService.sb  （沙箱 profile，决定它能碰什么）")
print("=" * 72)
print(z.read(B + "Resources/UpdateBrainService.sb").decode("utf-8", "replace"))

# dylib 里的字符串能说明它调哪些工具、认哪些路径
print("=" * 72)
print("UpdateBrainLibrary.dylib 里与封印 / Preboot / cryptex / APFS 相关的字符串")
print("=" * 72)
blob = z.read(B + "MacOS/UpdateBrainLibrary.dylib")
pats = (rb"[\x20-\x7e]{6,120}")
hits = {}
keys = ("seal", "Seal", "snapshot", "Snapshot", "cryptex", "Cryptex",
        "Preboot", "preboot", "apfs", "APFS", "bless", "authenticated",
        "payloadv2", "mount", "volume group", "VolumeGroup", "SystemVolume",
        "createSnapshot", "sealVolume", "root_hash", "RootHash")
for m in re.finditer(pats, blob):
    s = m.group().decode("ascii", "replace")
    for k in keys:
        if k in s:
            hits.setdefault(k, []).append(s)
            break
for k in keys:
    v = hits.get(k)
    if not v:
        continue
    uniq = sorted(set(v))
    print(f"\n---- {k}  ({len(uniq)} 条) ----")
    for s in uniq[:14]:
        print("   ", s)
    if len(uniq) > 14:
        print(f"    ... (+{len(uniq) - 14})")
