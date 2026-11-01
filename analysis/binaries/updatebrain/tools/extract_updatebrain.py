#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Extract UpdateBrain's XPC service payload from UpdateBrain.zip and report
Mach-O metadata (arch, LC_UUID, LC_SOURCE_VERSION, LC_BUILD_VERSION, SHA-256).

Pure read-only parsing on Windows; no macOS tooling involved. The zip is an
ordinary zip, read with the stdlib. Extracted files land under
analysis/binaries/updatebrain/ which is inside the .gitignore publish boundary
(*.dylib and the service binary never enter the repo); evidence is reproducible
from the SHA-256 recorded in MANIFEST.md.

Usage:
    py extract_updatebrain.py            # extract + report
    py extract_updatebrain.py --report   # report on already-extracted files
"""
import hashlib
import io
import os
import plistlib
import struct
import sys
import zipfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.dirname(HERE)  # analysis/binaries/updatebrain
REPO = os.path.abspath(os.path.join(OUT, "..", "..", ".."))
ZIP = os.path.join(REPO, "142-36613 - 26.7.2 macOS Tahoe (25G325)", "UpdateBrain.zip")

XPC = "AssetData/com.apple.MobileSoftwareUpdate.UpdateBrainService.xpc/Contents/"
MEMBERS = {
    "UpdateBrainLibrary.dylib": XPC + "MacOS/UpdateBrainLibrary.dylib",
    "com.apple.MobileSoftwareUpdate.UpdateBrainService": XPC + "MacOS/com.apple.MobileSoftwareUpdate.UpdateBrainService",
    "UpdateBrainService.sb": XPC + "Resources/UpdateBrainService.sb",
    "xpc-Info.plist": XPC + "Info.plist",
    "top-Info.plist": "Info.plist",
    "TrustCache.bin": "AssetData/.TrustCache",
}

# ---- Mach-O constants ----
FAT_MAGIC = 0xCAFEBABE
FAT_CIGAM = 0xBEBAFECA
FAT_MAGIC_64 = 0xCAFEBABF
FAT_CIGAM_64 = 0xBFBAFECA
MH_MAGIC_64 = 0xFEEDFACF
MH_CIGAM_64 = 0xCFFAEDFE
MH_MAGIC = 0xFEEDFACE
MH_CIGAM = 0xECFAEDFE

LC_UUID = 0x1B
LC_SOURCE_VERSION = 0x2A
LC_BUILD_VERSION = 0x32
LC_VERSION_MIN_MACOSX = 0x24
LC_ID_DYLIB = 0xD

CPU_ARCH_ABI64 = 0x01000000
CPU_TYPE_X86 = 7
CPU_TYPE_X86_64 = CPU_TYPE_X86 | CPU_ARCH_ABI64
CPU_TYPE_ARM = 12
CPU_TYPE_ARM64 = CPU_TYPE_ARM | CPU_ARCH_ABI64

MH_TYPES = {1: "MH_OBJECT", 2: "MH_EXECUTE", 6: "MH_DYLIB", 7: "MH_DYLINKER",
            8: "MH_BUNDLE", 0xB: "MH_KEXT_BUNDLE", 0xC: "MH_FILESET"}
PLATFORMS = {1: "macOS", 2: "iOS", 3: "tvOS", 4: "watchOS", 6: "bridgeOS",
             7: "macCatalyst", 8: "iOSSim", 9: "tvOSSim", 10: "watchOSSim"}


def arch_name(cputype, cpusub):
    base = {CPU_TYPE_X86_64: "x86_64", CPU_TYPE_X86: "i386",
            CPU_TYPE_ARM64: "arm64", CPU_TYPE_ARM: "arm"}.get(cputype, f"cpu{cputype:#x}")
    sub = cpusub & 0x00FFFFFF
    if cputype == CPU_TYPE_X86_64 and sub == 8:
        base = "x86_64h"
    if cputype == CPU_TYPE_ARM64 and sub == 2:
        base = "arm64e"
    return base, sub


def ver32(v):  # nibble.nibble.nibble form used by source/dylib versions (A.B.C.D.E)
    return f"{(v >> 40) & 0xFFFFFF}.{(v >> 30) & 0x3FF}.{(v >> 20) & 0x3FF}.{(v >> 10) & 0x3FF}.{v & 0x3FF}"


def ver_xyz(v):  # 32-bit X.Y.Z
    return f"{(v >> 16) & 0xFFFF}.{(v >> 8) & 0xFF}.{v & 0xFF}"


def parse_thin(buf, off):
    magic = struct.unpack_from("<I", buf, off)[0]
    be = magic in (MH_CIGAM_64, MH_CIGAM)
    end = ">" if be else "<"
    is64 = magic in (MH_MAGIC_64, MH_CIGAM_64)
    if is64:
        cputype, cpusub, filetype, ncmds, sizeofcmds, flags, _ = struct.unpack_from(end + "IIIIIII", buf, off + 4)
        lc = off + 32
    else:
        cputype, cpusub, filetype, ncmds, sizeofcmds, flags = struct.unpack_from(end + "IIIIII", buf, off + 4)
        lc = off + 28
    info = {"cputype": cputype, "cpusub": cpusub, "filetype": filetype,
            "ncmds": ncmds, "uuid": None, "source_version": None,
            "build": None, "id_dylib": None}
    p = lc
    for _ in range(ncmds):
        cmd, cmdsize = struct.unpack_from(end + "II", buf, p)
        if cmd == LC_UUID:
            info["uuid"] = struct.unpack_from("16s", buf, p + 8)[0].hex().upper()
            info["uuid"] = "-".join([info["uuid"][0:8], info["uuid"][8:12],
                                     info["uuid"][12:16], info["uuid"][16:20], info["uuid"][20:32]])
        elif cmd == LC_SOURCE_VERSION:
            info["source_version"] = ver32(struct.unpack_from(end + "Q", buf, p + 8)[0])
        elif cmd == LC_BUILD_VERSION:
            platform, minos, sdk = struct.unpack_from(end + "III", buf, p + 8)
            info["build"] = f"{PLATFORMS.get(platform, platform)} minos {ver_xyz(minos)} sdk {ver_xyz(sdk)}"
        elif cmd == LC_VERSION_MIN_MACOSX and not info["build"]:
            minos, sdk = struct.unpack_from(end + "II", buf, p + 8)
            info["build"] = f"macOS(min) minos {ver_xyz(minos)} sdk {ver_xyz(sdk)}"
        elif cmd == LC_ID_DYLIB:
            name_off = struct.unpack_from(end + "I", buf, p + 8)[0]
            raw = buf[p + name_off:p + cmdsize].split(b"\x00")[0]
            info["id_dylib"] = raw.decode("utf-8", "replace")
        p += cmdsize
    return info


def parse_macho(buf):
    magic = struct.unpack_from(">I", buf, 0)[0]
    slices = []
    if magic in (FAT_MAGIC, FAT_CIGAM, FAT_MAGIC_64, FAT_CIGAM_64):
        is64 = magic in (FAT_MAGIC_64, FAT_CIGAM_64)
        nfat = struct.unpack_from(">I", buf, 4)[0]
        p = 8
        for _ in range(nfat):
            if is64:
                cputype, cpusub, offset, size, align = struct.unpack_from(">IIQQI", buf, p)
                p += 32
            else:
                cputype, cpusub, offset, size, align = struct.unpack_from(">IIIII", buf, p)
                p += 20
            slices.append((offset, size, parse_thin(buf, offset)))
        return "fat", slices
    elif magic in (MH_MAGIC_64, MH_CIGAM_64, MH_MAGIC, MH_CIGAM):
        return "thin", [(0, len(buf), parse_thin(buf, 0))]
    return "notmacho", []


def sha256(b):
    return hashlib.sha256(b).hexdigest().upper()


def describe(name, data):
    print("=" * 76)
    print(f"{name}   {len(data):,} bytes")
    print(f"  SHA-256 {sha256(data)}")
    kind, slices = parse_macho(data)
    if kind == "notmacho":
        # maybe plist / text
        head = data[:16]
        print(f"  (not Mach-O) head={head!r}")
        return
    print(f"  container: {kind}, {len(slices)} slice(s)")
    for off, size, info in slices:
        base, sub = arch_name(info["cputype"], info["cpusub"])
        print(f"  [{base} / subtype {sub}] off={off} size={size:,}")
        print(f"       type    {MH_TYPES.get(info['filetype'], info['filetype'])}  ({info['ncmds']} load cmds)")
        print(f"       UUID    {info['uuid']}")
        print(f"       srcver  LC_SOURCE_VERSION {info['source_version']}")
        print(f"       build   {info['build']}")
        if info["id_dylib"]:
            print(f"       id      {info['id_dylib']}")
        if base.startswith("x86_64"):
            slice_bytes = data[off:off + size]
            print(f"       x86_64 slice SHA-256 {sha256(slice_bytes)}")


def main():
    report_only = "--report" in sys.argv
    os.makedirs(OUT, exist_ok=True)
    extracted = {}
    if not report_only:
        z = zipfile.ZipFile(ZIP)
        print(f"zip: {ZIP}")
        print(f"zip SHA-256 {sha256(open(ZIP, 'rb').read())}\n")
        for local, member in MEMBERS.items():
            try:
                data = z.read(member)
            except KeyError:
                print(f"  MISSING in zip: {member}")
                continue
            dst = os.path.join(OUT, local)
            with open(dst, "wb") as f:
                f.write(data)
            extracted[local] = data
    else:
        for local in MEMBERS:
            dst = os.path.join(OUT, local)
            if os.path.exists(dst):
                extracted[local] = open(dst, "rb").read()

    for local in ("UpdateBrainLibrary.dylib",
                  "com.apple.MobileSoftwareUpdate.UpdateBrainService"):
        if local in extracted:
            describe(local, extracted[local])

    # plists as readable summary
    for local in ("top-Info.plist", "xpc-Info.plist"):
        if local in extracted:
            print("=" * 76)
            print(f"{local}  ({len(extracted[local]):,} bytes)")
            try:
                d = plistlib.load(io.BytesIO(extracted[local]))
                txt = plistlib.dumps(d).decode("utf-8", "replace")
                print(txt)
            except Exception as exc:  # noqa: BLE001
                print(f"  plist parse error: {exc}")

    for local in ("UpdateBrainService.sb", "TrustCache.bin"):
        if local in extracted:
            print("=" * 76)
            print(f"{local}  ({len(extracted[local]):,} bytes)  SHA-256 {sha256(extracted[local])}")


if __name__ == "__main__":
    main()
