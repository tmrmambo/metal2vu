#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""按 docs/spec/71-IMAGE-OPENCORE.md §6 生成 OpenCore 的 config.plist。

构造方式：以**固定版本**的 OpenCorePkg `Docs/Sample.plist` 为基，施加声明式 diff。
这是 `71` §6.1 定的纪律，原话是「不要手抄一份 1500 行的 plist」—— 手抄的副本会在
OpenCore 升级时静默过期，而缺键的表现是 OpenCore 直接拒绝启动并在串口上报一行键名。

本实现比 `71` §6.1 的草稿多一道门禁
----------------------------------
草稿用 `dict.update()`。`update()` 对不存在的键会**静默新增**，于是两类错误都查不出来：

  1. 我们把键名拼错了（`ProvideCurrentCpuinfo`）—— 多一个没人读的键，OpenCore 忽略它，
     而我们以为那个 quirk 开了。
  2. OpenCore 新版本删掉或改名了某个键 —— 我们还在写旧名字，同样静默失效。

两类的症状都是「配置看起来对，行为不对」，而这正是最贵的一类 bug：它在
`78` §C.2 的 L1-8 里表现为「选择器里没有 macOS 这一项」，而那条的排查顺序有四步。
所以本脚本对每一个要写的键**先确认它在 Sample.plist 里已经存在**，不存在就报错退出，
并把键路径打出来。想新增键必须显式走 `--allow-new`。

已登记的勘误（照 `71` §6 原文抄会失败）
--------------------------------------
`76` §6 修正表第 `71-A`/`L-003` 条：驱动文件名不是 `OpenHfsPlus.efi`，而是
**`HfsPlus.efi`**，且来源是 `OcBinaryData` 的 `Drivers/` 而不是 OpenCorePkg release。
本脚本写 `HfsPlus.efi`。

`76` §5 + `L-014`：`ACPI/Add` 里不要放 `SSDT-USBX.aml`（OSX-KVM 的参考配置启用了一个
它自己仓库里都不存在的文件）。本脚本默认只加 `SSDT-EC.aml`，并提供
`--acpi-dir` 做「每个 Path 都必须在磁盘上存在」的门禁。

用法
----
    make_oc_config.py generate <Sample.plist> <out config.plist> [选项]
        --picker builtin|canopy     见 76 §2.2，排查引导问题时切 builtin
        --acpi-dir <目录>           对 ACPI/Add 的每个 Path 做存在性门禁
        --serial / --mlb / --uuid   覆盖 PlatformInfo 的占位值（71 §6.8）
        --allow-new                 允许新增 Sample.plist 里没有的键（默认禁止）
    make_oc_config.py selftest      不需要网络，用合成的 Sample 骨架自检
    make_oc_config.py dump <config.plist>   回读关键键，供 CI 断言
"""
from __future__ import annotations

import plistlib
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
except Exception:
    pass

APPLE_BOOT_GUID = "7C436110-AB2A-4BBB-A880-FE41995C9F82"

# SIP：0xFFF 全开减去 0x10（AppleInternal）。`70` §5.2 的两条理由：量产机上
# boot.efi 会在传给内核前剥掉 0x10，设了没用；而它会把系统带进 Apple 内部代码路径。
CSR_ACTIVE_CONFIG = 0xFEF

# `71` §6.7 的 boot-args。每一项的作用都写在旁边，因为这一行里有四项是取证用的，
# 删掉任何一项都会让 panic 期失去文本通道（`80` §1.4：串口是 panic 期唯一通道）。
BOOT_ARGS_PARTS = [
    "amfi_get_out_of_my_way=1",  # 70 §5.5：组件 1/2/3 的前提
    "-v",  # verbose，内核日志进屏幕与串口
    "keepsyms=1",  # 保留内核符号，panic backtrace 才可读
    "debug=0xa",  # DB_PRT|DB_KPRT，见 71 §9.4
    "serial=7",  # OUTPUT|INPUT|SYNCDRAIN，见 71 §9.4
    "msgbuf=1048576",  # 1 MiB 内核消息缓冲
]


class KeyGate:
    """逐键写入，并记录「这个键在 Sample 里本来存不存在」。"""

    def __init__(self, root: dict, allow_new: bool) -> None:
        self.root = root
        self.allow_new = allow_new
        self.missing: list[str] = []
        self.written = 0

    def _walk(self, path: str) -> dict:
        node = self.root
        parts = path.split("/")
        for i, p in enumerate(parts):
            if not isinstance(node, dict) or p not in node:
                raise KeyError("/".join(parts[: i + 1]))
            node = node[p]
        if not isinstance(node, dict):
            raise TypeError(f"{path} 不是字典")
        return node

    def update(self, path: str, values: dict) -> None:
        """对 path 指向的字典施加 values，逐键检查存在性。"""
        try:
            node = self._walk(path)
        except KeyError as e:
            self.missing.append(f"{e.args[0]}  （整个子节都不在）")
            return
        for k, v in values.items():
            if k not in node:
                self.missing.append(f"{path}/{k}")
                if not self.allow_new:
                    continue
            node[k] = v
            self.written += 1

    def set(self, path: str, key: str, value: object) -> None:
        self.update(path, {key: value})

    def replace(self, path: str, key: str, value: object) -> None:
        """整段替换一个子节（数组或我们完全重写的字典）。仍检查 key 是否存在。"""
        self.set(path, key, value)

    def all_false(self, path: str) -> dict:
        """把一个 Quirks 字典里所有布尔键置 False，保留非布尔键原值。

        用于 `ACPI/Quirks` 这类「全部关掉」的子节。不写死键名，因为键名随版本变 ——
        这正是以 Sample.plist 为基的好处。
        """
        node = self._walk(path)
        return {k: (False if isinstance(v, bool) else v) for k, v in node.items()}


def kext(bundle: str, exe: str, *, min_k: str = "", max_k: str = "", comment: str = "") -> dict:
    return {
        "Arch": "x86_64",
        "BundlePath": bundle,
        "Comment": comment,
        "Enabled": True,
        "ExecutablePath": exe,
        "MaxKernel": max_k,
        "MinKernel": min_k,
        "PlistPath": "Contents/Info.plist",
    }


def driver(path: str, enabled: bool, comment: str) -> dict:
    return {
        "Arguments": "",
        "Comment": comment,
        "Enabled": enabled,
        "LoadEarly": False,
        "Path": path,
    }


def build(
    sample: dict,
    *,
    picker: str = "builtin",
    serial: str = "F5KZN00HP7QM",
    mlb: str = "M0000000000000001",
    uuid: str = "00000000-0000-0000-0000-000000000000",
    allow_new: bool = False,
) -> tuple[dict, list[str], int]:
    """返回 (config, 缺失键清单, 写入键数)。"""
    c = sample
    g = KeyGate(c, allow_new)

    # ---------------- ACPI（76 §5：必需的 SSDT 只有 SSDT-EC）----------------
    g.replace(
        "ACPI",
        "Add",
        [
            {
                "Comment": "fake EC for QEMU; parent path is \\_SB.PCI0, not LPCB (76 §5.3.1)",
                "Enabled": True,
                "Path": "SSDT-EC.aml",
            }
        ],
    )
    g.replace("ACPI", "Delete", [])
    g.replace("ACPI", "Patch", [])
    g.replace("ACPI", "Quirks", g.all_false("ACPI/Quirks"))

    # ---------------- Booter（71 §6.3）----------------
    g.replace("Booter", "MmioWhitelist", [])
    g.replace("Booter", "Patch", [])
    g.update(
        "Booter/Quirks",
        {
            "AvoidRuntimeDefrag": True,  # OVMF 上必需
            "EnableWriteUnprotector": True,  # 需要 OpenRuntime.efi
            "FixupAppleEfiImages": True,  # SecureBootModel=Disabled 时严格 PE loader 要
            "SyncRuntimePermissions": True,
            "AllowRelocationBlock": False,
            "DevirtualiseMmio": False,
            "DisableSingleUser": False,
            "DisableVariableWrite": False,
            "DiscardHibernateMap": False,
            "EnableSafeModeSlide": False,
            "ForceBooterSignature": False,
            "ForceExitBootServices": False,
            "ProtectMemoryRegions": False,
            "ProtectSecureBoot": False,
            "ProtectUefiServices": False,
            "ProvideCustomSlide": False,
            "ProvideMaxSlide": 0,
            "RebuildAppleMemoryMap": False,
            "ResizeAppleGpuBars": 0,
            "SetupVirtualMap": False,
            "SignalAppleOS": False,
            "ClearTaskSwitchBit": False,
        },
    )

    # ---------------- DeviceProperties（71 §6.4：保持全空）----------------
    g.replace("DeviceProperties", "Add", {})
    g.replace("DeviceProperties", "Delete", {})

    # ---------------- Kernel（71 §6.5 / 76 §5.4：最小集三件，一个不多一个不少）----
    g.replace(
        "Kernel",
        "Add",
        [
            kext("Lilu.kext", "Contents/MacOS/Lilu", comment="patch engine; must be first"),
            kext(
                "VirtualSMC.kext",
                "Contents/MacOS/VirtualSMC",
                comment="SMC emulation; depends on Lilu",
            ),
            kext(
                "AppleMCEReporterDisabler.kext",
                "",
                min_k="21.0.0",
                comment="block AppleIntelMCEReporter under MacPro7,1 board-id",
            ),
        ],
    )
    g.replace("Kernel", "Block", [])
    g.update(
        "Kernel/Emulate",
        {
            # 71 §5.3：在 QEMU 上我们直接用 -cpu 选了一个 macOS 认识的型号，
            # 没有需要伪装的东西，所以这两个留空。
            "Cpuid1Data": b"",
            "Cpuid1Mask": b"",
            "DummyPowerManagement": True,
            "MaxKernel": "",
            "MinKernel": "",
        },
    )
    g.replace("Kernel", "Force", [])
    g.replace("Kernel", "Patch", [])  # 71 §6.5.4 默认空
    g.update(
        "Kernel/Quirks",
        {
            "DisableLinkeditJettison": True,
            # 71 §5.3：官方文档说它对 KVM 与其它 hypervisor 提供预先算好的 MSR 0x35。
            # 另一条独立理由：AMD_Vanilla 把这个 quirk 列为强制前提，万一哪天要打补丁
            # 也不用改这里。
            "ProvideCurrentCpuInfo": True,
            "PanicNoKextDump": False,  # 我们要看 kext dump
            "PowerTimeoutKernelPanic": True,  # 显示栈 setPowerState 超时不要 panic
            "CustomPciSerialDevice": False,  # 用 ISA COM1，不是 PCI 串口卡
            "ForceSecureBootScheme": False,
            "DisableIoMapper": False,
            "AppleCpuPmCfgLock": False,
            "AppleXcpmCfgLock": False,
            "AppleXcpmExtraMsrs": False,
            "AppleXcpmForceBoost": False,
            "SetApfsTrimTimeout": -1,
            "XhciPortLimit": False,
        },
    )
    g.update(
        "Kernel/Scheme",
        {
            "CustomKernel": False,
            "FuzzyMatch": True,
            "KernelArch": "x86_64",
            "KernelCache": "Auto",
        },
    )

    # ---------------- Misc ----------------
    g.replace("Misc", "BlessOverride", [])
    g.replace("Misc", "Entries", [])
    g.replace("Misc", "Tools", [])
    g.update(
        "Misc/Boot",
        {
            "HibernateMode": "None",
            "HibernateSkipsPicker": False,
            "HideAuxiliary": False,  # 要能看到 recovery 条目
            "LauncherOption": "Disabled",  # 74 §3.5：打开会把 shim 从引导链摘掉
            "PickerAttributes": 17,
            "PickerMode": "External" if picker == "canopy" else "Builtin",
            "PollAppleHotKeys": True,
            "ShowPicker": True,
            "TakeoffDelay": 0,
            "Timeout": 5,
        },
    )
    g.update(
        "Misc/Debug",
        {
            "AppleDebug": True,  # boot.efi 的日志
            "ApplePanic": True,  # panic 落盘到 ESP
            "DisableWatchDog": True,  # 卡住时不要自动重启
            "DisplayDelay": 0,
            "DisplayLevel": 0x80000042,  # ERROR|INFO|WARN
            "LogModules": "*",
            "SysReport": False,
            "Target": 0x4B,  # 71 §9.2：同时写屏幕、串口与文件
        },
    )
    g.update(
        "Misc/Security",
        {
            "AllowSetDefault": True,
            "ApECID": 0,
            "AuthRestart": False,
            "BlacklistAppleUpdate": True,
            "DmgLoading": "Signed",  # 71 §6.6.3
            "EnablePassword": False,
            "ExposeSensitiveData": 0x6,
            "HaltLevel": 0x80000000,
            "ScanPolicy": 0,  # 71 §7.3：研发期全扫
            "SecureBootModel": "Disabled",
            "Vault": "Optional",
        },
    )
    g.update("Misc/Serial", {"Init": True, "Override": False})

    # ---------------- NVRAM ----------------
    # Add 的语义是「不存在才写」，所以必须先 Delete 才能保证每次启动都是配置里的值。
    # 70 §5.3 路径 A 的警告。
    g.replace(
        "NVRAM",
        "Add",
        {
            APPLE_BOOT_GUID: {
                "csr-active-config": CSR_ACTIVE_CONFIG.to_bytes(4, "little"),
                "boot-args": " ".join(BOOT_ARGS_PARTS),
                "prev-lang:kbd": b"en-US:0",
                "run-efi-updater": "No",
                "SystemAudioVolume": b"\x46",
            }
        },
    )
    g.replace(
        "NVRAM",
        "Delete",
        {
            APPLE_BOOT_GUID: [
                "csr-active-config",
                "boot-args",
                "prev-lang:kbd",
                "run-efi-updater",
            ]
        },
    )
    g.set("NVRAM", "LegacyOverwrite", False)
    g.set("NVRAM", "WriteFlash", True)

    # ---------------- PlatformInfo（71 §4.4：MacPro7,1）----------------
    g.update(
        "PlatformInfo",
        {
            "Automatic": True,
            "CustomMemory": False,
            "UpdateDataHub": True,
            "UpdateNVRAM": True,
            "UpdateSMBIOS": True,
            "UpdateSMBIOSMode": "Create",
            "UseRawUuidEncoding": False,
        },
    )
    g.update(
        "PlatformInfo/Generic",
        {
            "AdviseFeatures": False,
            "MLB": mlb,
            "MaxBIOSVersion": False,
            "ProcessorType": 0,
            "ROM": bytes.fromhex("112233445566"),
            "SpoofVendor": True,
            "SystemMemoryStatus": "Auto",
            "SystemProductName": "MacPro7,1",
            "SystemSerialNumber": serial,
            "SystemUUID": uuid,
        },
    )

    # ---------------- UEFI ----------------
    g.set("UEFI", "ConnectDrivers", True)
    g.replace("UEFI", "Unload", [])
    g.update(
        "UEFI/APFS",
        {
            # 71 §6.9.2：这是能不能启动已装系统的前提。78 §C.2 的 L1-8 就是它没生效。
            "EnableJumpstart": True,
            "GlobalConnect": False,
            # 故意与参考配置相反：要让 apfs.efi 的 verbose 进串口，
            # 那是「卷有没有被认出来」的直接证据。
            "HideVerbose": False,
            "JumpstartHotPlug": False,
            "MinDate": 0,
            "MinVersion": 0,
        },
    )
    g.set("UEFI/Audio", "AudioSupport", False)
    g.update(
        "UEFI/Input",
        {
            "KeySupport": True,
            "KeySupportMode": "Auto",
            "PointerSupport": picker == "canopy",
            "TimerResolution": 50000,
        },
    )
    g.update(
        "UEFI/Output",
        {
            "ProvideConsoleGop": True,  # 必需
            "TextRenderer": "BuiltinGraphics",
            "ConsoleMode": "",
            "Resolution": "",
            "DirectGopRendering": False,
            "GopPassThrough": "Disabled",
            "UgaPassThrough": False,
        },
    )
    g.replace("UEFI", "ProtocolOverrides", {
        **{k: False for k in g.all_false("UEFI/ProtocolOverrides")},
        "FirmwareVolume": True,
    })
    g.update(
        "UEFI/Quirks",
        {
            "EnableVectorAcceleration": True,
            "EnableVmx": False,  # 00-OVERVIEW §2.2 不要求嵌套虚拟化
            "RequestBootVarRouting": True,  # 需要 OpenRuntime.efi
            "DisableSecurityPolicy": False,
            "ForgeUefiSupport": False,
            "IgnoreInvalidFlexRatio": False,
            # 76 §5：打开会害了 OpenCanopy 的键盘
            "ReleaseUsbOwnership": False,
            "ResizeGpuBars": -1,
            "TscSyncTimeout": 0,
            "UnblockFsConnect": False,
            "ActivateHpetSupport": False,
            "ExitBootServicesDelay": 0,
        },
    )
    g.replace("UEFI", "ReservedMemory", [])

    drivers = [
        driver("OpenRuntime.efi", True, "required by Booter quirks + NVRAM routing"),
        # 76 §6 的 71-A / L-003：文件名是 HfsPlus.efi，来源是 OcBinaryData/Drivers/。
        # 写成 OpenHfsPlus.efi 会在装配 ESP 时 copy 不到文件。
        driver("HfsPlus.efi", True, "recovery volumes are HFS+ (OcBinaryData)"),
        driver("ResetNvramEntry.efi", True, "picker entry to clear NVRAM"),
        driver("ToggleSipEntry.efi", True, "picker entry to flip csr-active-config"),
        driver("OpenCanopy.efi", picker == "canopy", "graphical picker (76 §2)"),
        # 71 §6.9.1：OVMF 自带 virtio 驱动，L1 上不需要。它们的价值在 L2。
        driver("VirtioPciDeviceDxe.efi", False, "virtio PCI transport"),
        driver("Virtio10.efi", False, "virtio 1.0 device support"),
        driver("VirtioBlkDxe.efi", False, "virtio-blk block io"),
        driver("VirtioSerialDxe.efi", False, "virtio-serial"),
    ]
    g.replace("UEFI", "Drivers", drivers)

    return c, g.missing, g.written


# ---------------------------------------------------------------------------
# 子命令
# ---------------------------------------------------------------------------
def acpi_gate(config: dict, acpi_dir: str) -> list[str]:
    """76 §5.3.5 的构建期门禁：ACPI/Add 里每个 Path 都必须在磁盘上存在。

    由来是 L-014：OSX-KVM 的参考配置启用了一个它自己仓库里都不存在的
    SSDT-USBX.aml。OpenCore 对缺文件的反应是在串口上报一行然后继续，
    于是「少了一个 SSDT」这件事在没有串口的环境里完全不可见。
    """
    import os

    bad = []
    for item in config["ACPI"]["Add"]:
        if not item.get("Enabled"):
            continue
        p = os.path.join(acpi_dir, item["Path"])
        if not os.path.isfile(p):
            bad.append(item["Path"])
    return bad


def cmd_generate(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    src, dst = argv[0], argv[1]
    opts = {
        "picker": "builtin",
        "serial": "F5KZN00HP7QM",
        "mlb": "M0000000000000001",
        "uuid": "00000000-0000-0000-0000-000000000000",
    }
    acpi_dir = None
    allow_new = False
    i = 2
    while i < len(argv):
        a = argv[i]
        if a == "--allow-new":
            allow_new = True
            i += 1
        elif a == "--acpi-dir":
            acpi_dir = argv[i + 1]
            i += 2
        elif a.startswith("--") and a[2:] in opts:
            opts[a[2:]] = argv[i + 1]
            i += 2
        else:
            print(f"不认识的参数 {a}")
            return 2
    if opts["picker"] not in ("builtin", "canopy"):
        print("--picker 只能是 builtin 或 canopy")
        return 2

    with open(src, "rb") as fh:
        sample = plistlib.load(fh)

    config, missing, written = build(sample, allow_new=allow_new, **opts)  # type: ignore[arg-type]

    print(f"基准 Sample.plist : {src}")
    print(f"picker            : {opts['picker']}")
    print(f"写入键数          : {written}")

    if missing:
        print(f"\n!! {len(missing)} 个键在 Sample.plist 里不存在：")
        for m in missing:
            print(f"     {m}")
        if not allow_new:
            print(
                "\n这通常意味着两件事之一：键名拼错了，或者 OpenCore 这个版本"
                "改了键集。\n两者的症状都是「配置看起来对、行为不对」，所以这里"
                "硬失败。\n确认要新增就加 --allow-new。"
            )
            return 1
        print("（--allow-new 已给，仍然写入）")

    if acpi_dir:
        bad = acpi_gate(config, acpi_dir)
        print(f"\nACPI 门禁（{acpi_dir}）：", end="")
        if bad:
            print(f"缺 {len(bad)} 个文件：{', '.join(bad)}")
            return 1
        print("ACPI/Add 的每个 Path 都在磁盘上")

    with open(dst, "wb") as fh:
        plistlib.dump(config, fh, sort_keys=True)
    print(f"\n写出 {dst}")
    return cmd_dump([dst])


def cmd_dump(argv: list[str]) -> int:
    if not argv:
        print("用法: make_oc_config.py dump <config.plist>")
        return 2
    with open(argv[0], "rb") as fh:
        c = plistlib.load(fh)
    nv = c["NVRAM"]["Add"][APPLE_BOOT_GUID]
    csr = int.from_bytes(nv["csr-active-config"], "little")
    print("---- 关键键回读（CI 断言用）----")
    rows = [
        ("PlatformInfo/Generic/SystemProductName", c["PlatformInfo"]["Generic"]["SystemProductName"]),
        ("Misc/Security/ScanPolicy", c["Misc"]["Security"]["ScanPolicy"]),
        ("Misc/Security/SecureBootModel", c["Misc"]["Security"]["SecureBootModel"]),
        ("Misc/Boot/PickerMode", c["Misc"]["Boot"]["PickerMode"]),
        ("Misc/Debug/Target", hex(c["Misc"]["Debug"]["Target"])),
        ("Misc/Serial/Init", c["Misc"]["Serial"]["Init"]),
        ("UEFI/APFS/EnableJumpstart", c["UEFI"]["APFS"]["EnableJumpstart"]),
        ("UEFI/APFS/HideVerbose", c["UEFI"]["APFS"]["HideVerbose"]),
        ("UEFI/Output/ProvideConsoleGop", c["UEFI"]["Output"]["ProvideConsoleGop"]),
        ("Kernel/Quirks/ProvideCurrentCpuInfo", c["Kernel"]["Quirks"]["ProvideCurrentCpuInfo"]),
        ("Kernel/Emulate/DummyPowerManagement", c["Kernel"]["Emulate"]["DummyPowerManagement"]),
        ("csr-active-config", f"0x{csr:03X}"),
    ]
    for k, v in rows:
        print(f"  {k:46s} = {v}")
    print(f"  {'boot-args':46s} = {nv['boot-args']}")
    print("  注入的 kext：")
    for k in c["Kernel"]["Add"]:
        print(f"      {k['BundlePath']:38s} Enabled={k['Enabled']} MinKernel={k['MinKernel']!r}")
    print("  启用的 .efi driver：")
    for d in c["UEFI"]["Drivers"]:
        if d["Enabled"]:
            print(f"      {d['Path']}")
    print("  ACPI/Add：")
    for a in c["ACPI"]["Add"]:
        print(f"      {a['Path']:38s} Enabled={a['Enabled']}")
    return 0


def _synthetic_sample() -> dict:
    """自检用的 Sample.plist 骨架。

    不 vendor OpenCore 的文件（公开仓库的发布边界只放行本项目自有文本），
    也不在自检里联网。所以这里按 OpenCore 的键结构合成一份**键名齐全、值随意**
    的骨架：自检要验的是「门禁认不认得出缺键」与「diff 施加得对不对」，
    而不是 OpenCore 某个版本的具体默认值。
    """
    quirks = lambda ks: {k: False for k in ks}  # noqa: E731
    return {
        "ACPI": {"Add": [], "Delete": [], "Patch": [], "Quirks": quirks(
            ["FadtEnableReset", "NormalizeHeaders", "RebaseRegions",
             "ResetHwSig", "ResetLogoStatus", "SyncTableIds"])},
        "Booter": {"MmioWhitelist": [], "Patch": [], "Quirks": {
            **quirks(["AllowRelocationBlock", "AvoidRuntimeDefrag", "DevirtualiseMmio",
                      "DisableSingleUser", "DisableVariableWrite", "DiscardHibernateMap",
                      "EnableSafeModeSlide", "EnableWriteUnprotector", "FixupAppleEfiImages",
                      "ForceBooterSignature", "ForceExitBootServices", "ProtectMemoryRegions",
                      "ProtectSecureBoot", "ProtectUefiServices", "ProvideCustomSlide",
                      "RebuildAppleMemoryMap", "SetupVirtualMap", "SignalAppleOS",
                      "SyncRuntimePermissions", "ClearTaskSwitchBit"]),
            "ProvideMaxSlide": 0, "ResizeAppleGpuBars": -1}},
        "DeviceProperties": {"Add": {}, "Delete": {}},
        "Kernel": {
            "Add": [], "Block": [], "Force": [], "Patch": [],
            "Emulate": {"Cpuid1Data": b"", "Cpuid1Mask": b"",
                        "DummyPowerManagement": False, "MaxKernel": "", "MinKernel": ""},
            "Quirks": {**quirks(
                ["AppleCpuPmCfgLock", "AppleXcpmCfgLock", "AppleXcpmExtraMsrs",
                 "AppleXcpmForceBoost", "CustomPciSerialDevice", "CustomSMBIOSGuid",
                 "DisableIoMapper", "DisableIoMapperMapping", "DisableLinkeditJettison",
                 "DisableRtcChecksum", "ExtendBTFeatureFlags", "ExternalDiskIcons",
                 "ForceAquantiaEthernet", "ForceSecureBootScheme", "IncreasePciBarSize",
                 "LapicKernelPanic", "LegacyCommpage", "PanicNoKextDump",
                 "PowerTimeoutKernelPanic", "ProvideCurrentCpuInfo", "SetApfsTrimTimeout",
                 "ThirdPartyDrives", "XhciPortLimit"]), "SetApfsTrimTimeout": -1},
            "Scheme": {"CustomKernel": False, "FuzzyMatch": False,
                       "KernelArch": "Auto", "KernelCache": "Auto"},
        },
        "Misc": {
            "BlessOverride": [], "Entries": [], "Tools": [],
            "Boot": {"HibernateMode": "None", "HibernateSkipsPicker": False,
                     "HideAuxiliary": False, "InstanceIdentifier": "",
                     "LauncherOption": "Disabled", "LauncherPath": "Default",
                     "PickerAttributes": 0, "PickerAudioAssist": False,
                     "PickerMode": "Builtin", "PickerVariant": "Auto",
                     "PollAppleHotKeys": False, "ShowPicker": True,
                     "TakeoffDelay": 0, "Timeout": 0},
            "Debug": {"AppleDebug": False, "ApplePanic": False, "DisableWatchDog": False,
                      "DisplayDelay": 0, "DisplayLevel": 0, "LogModules": "",
                      "SysReport": False, "Target": 0},
            "Security": {"AllowSetDefault": False, "ApECID": 0, "AuthRestart": False,
                         "BlacklistAppleUpdate": False, "DmgLoading": "Signed",
                         "EnablePassword": False, "ExposeSensitiveData": 6,
                         "HaltLevel": 2147483648, "PasswordHash": b"", "PasswordSalt": b"",
                         "ScanPolicy": 17760515, "SecureBootModel": "Default",
                         "Vault": "Secure"},
            "Serial": {"Custom": {}, "Init": False, "Override": False},
        },
        "NVRAM": {"Add": {}, "Delete": {}, "LegacyOverwrite": False,
                  "LegacySchema": {}, "WriteFlash": False},
        "PlatformInfo": {
            "Automatic": False, "CustomMemory": False, "UpdateDataHub": False,
            "UpdateNVRAM": False, "UpdateSMBIOS": False, "UpdateSMBIOSMode": "Create",
            "UseRawUuidEncoding": False,
            "Generic": {"AdviseFeatures": False, "MLB": "", "MaxBIOSVersion": False,
                        "ProcessorType": 0, "ROM": b"", "SpoofVendor": False,
                        "SystemMemoryStatus": "Auto", "SystemProductName": "",
                        "SystemSerialNumber": "", "SystemUUID": ""},
        },
        "UEFI": {
            "ConnectDrivers": False, "Drivers": [], "Unload": [], "ReservedMemory": [],
            "APFS": {"EnableJumpstart": False, "GlobalConnect": False,
                     "HideVerbose": False, "JumpstartHotPlug": False,
                     "MinDate": 0, "MinVersion": 0},
            "AppleInput": {"AppleEvent": "Builtin"},
            "Audio": {"AudioSupport": False},
            "Input": {"KeyFiltering": False, "KeyForgetThreshold": 0,
                      "KeySupport": False, "KeySupportMode": "Auto",
                      "PointerSupport": False, "PointerSupportMode": "",
                      "TimerResolution": 0},
            "Output": {"ClearScreenOnModeSwitch": False, "ConsoleMode": "",
                       "DirectGopRendering": False, "ForceResolution": False,
                       "GopBurstMode": False, "GopPassThrough": "Disabled",
                       "IgnoreTextInGraphics": False, "ProvideConsoleGop": False,
                       "ReconnectGraphicsOnConnect": False, "ReconnectOnResChange": False,
                       "ReplaceTabWithSpace": False, "Resolution": "",
                       "SanitiseClearScreen": False, "TextRenderer": "BuiltinGraphics",
                       "UIScale": 0, "UgaPassThrough": False},
            "ProtocolOverrides": quirks(
                ["AppleAudio", "AppleBootPolicy", "AppleDebugLog", "AppleEg2Info",
                 "AppleFramebufferInfo", "AppleImageConversion", "AppleImg4Verification",
                 "AppleKeyMap", "AppleRtcRam", "AppleSecureBoot", "AppleSmcIo",
                 "AppleUserInterfaceTheme", "DataHub", "DeviceProperties",
                 "FirmwareVolume", "HashServices", "OSInfo", "UnicodeCollation"]),
            "Quirks": {**quirks(
                ["ActivateHpetSupport", "DisableSecurityPolicy", "EnableVectorAcceleration",
                 "EnableVmx", "ForceOcWriteFlash", "ForgeUefiSupport",
                 "IgnoreInvalidFlexRatio", "ReleaseUsbOwnership", "ReloadOptionRoms",
                 "RequestBootVarRouting", "ResizeUsePciRbIo", "ShimRetainProtocol",
                 "TscSyncTimeout", "UnblockFsConnect"]),
                "ExitBootServicesDelay": 0, "ResizeGpuBars": -1, "TscSyncTimeout": 0},
        },
    }


def cmd_selftest(_argv: list[str]) -> int:
    import copy
    import io

    fails: list[str] = []

    def check(name: str, cond: bool, detail: str = "") -> None:
        print(f"  [{'ok' if cond else 'FAIL'}] {name}{('  ' + detail) if detail else ''}")
        if not cond:
            fails.append(name)

    print("== 正常生成 ==")
    cfg, missing, written = build(copy.deepcopy(_synthetic_sample()))
    check("骨架齐全时没有缺键", missing == [], f"缺 {missing}")
    check("写入键数 > 100", written > 100, str(written))

    print("== 规格里点名的那些值 ==")
    nv = cfg["NVRAM"]["Add"][APPLE_BOOT_GUID]
    check("SystemProductName = MacPro7,1（71 §4.4）",
          cfg["PlatformInfo"]["Generic"]["SystemProductName"] == "MacPro7,1")
    check("ScanPolicy = 0（71 §7.3）", cfg["Misc"]["Security"]["ScanPolicy"] == 0)
    check("SecureBootModel = Disabled", cfg["Misc"]["Security"]["SecureBootModel"] == "Disabled")
    check("APFS/EnableJumpstart = true（78 L1-8 的前提）",
          cfg["UEFI"]["APFS"]["EnableJumpstart"] is True)
    check("APFS/HideVerbose = false（故意与参考配置相反）",
          cfg["UEFI"]["APFS"]["HideVerbose"] is False)
    check("ProvideConsoleGop = true", cfg["UEFI"]["Output"]["ProvideConsoleGop"] is True)
    check("ProvideCurrentCpuInfo = true（71 §5.3）",
          cfg["Kernel"]["Quirks"]["ProvideCurrentCpuInfo"] is True)
    check("DummyPowerManagement = true", cfg["Kernel"]["Emulate"]["DummyPowerManagement"] is True)
    check("Cpuid1Data 留空（71 §5.3）", cfg["Kernel"]["Emulate"]["Cpuid1Data"] == b"")
    check("csr-active-config = 0xFEF 小端（70 §5.2）",
          nv["csr-active-config"] == b"\xef\x0f\x00\x00", nv["csr-active-config"].hex())
    check("Misc/Debug/Target = 0x4B（71 §9.2）", cfg["Misc"]["Debug"]["Target"] == 0x4B)
    check("Misc/Serial/Init = true", cfg["Misc"]["Serial"]["Init"] is True)
    check("EnableVmx = false（00 §2.2）", cfg["UEFI"]["Quirks"]["EnableVmx"] is False)
    check("LauncherOption = Disabled（74 §3.5）",
          cfg["Misc"]["Boot"]["LauncherOption"] == "Disabled")

    print("== boot-args 的六项（80 §1.4：串口是 panic 期唯一通道）==")
    for part in BOOT_ARGS_PARTS:
        check(f"boot-args 含 {part}", part in nv["boot-args"])

    print("== kext 最小集：一个不多、一个不少（76 §5.4）==")
    names = [k["BundlePath"] for k in cfg["Kernel"]["Add"]]
    check("恰好三个", len(names) == 3, str(names))
    check("顺序是 Lilu 在最前", names[0] == "Lilu.kext")
    check("没有 WhateverGreen（71 §6.10 整节论证）",
          not any("WhateverGreen" in n for n in names))
    check("AppleMCEReporterDisabler 的 MinKernel = 21.0.0",
          cfg["Kernel"]["Add"][2]["MinKernel"] == "21.0.0")

    print("== 驱动名的勘误（76 §6 的 71-A / L-003）==")
    enabled = [d["Path"] for d in cfg["UEFI"]["Drivers"] if d["Enabled"]]
    check("用 HfsPlus.efi", "HfsPlus.efi" in enabled)
    check("不用 OpenHfsPlus.efi（OcBinaryData 里没这个文件）",
          not any(d["Path"] == "OpenHfsPlus.efi" for d in cfg["UEFI"]["Drivers"]))
    check("OpenRuntime.efi 启用", "OpenRuntime.efi" in enabled)
    check("四个 virtio 驱动默认关（71 §6.9.1：OVMF 自带）",
          all(not d["Enabled"] for d in cfg["UEFI"]["Drivers"] if "irtio" in d["Path"]))
    check("builtin picker 下 OpenCanopy 关", "OpenCanopy.efi" not in enabled)

    print("== ACPI 最小集（76 §5）==")
    paths = [a["Path"] for a in cfg["ACPI"]["Add"]]
    check("只有 SSDT-EC.aml", paths == ["SSDT-EC.aml"], str(paths))
    check("没有 SSDT-USBX.aml（L-014：参考配置引用了不存在的文件）",
          "SSDT-USBX.aml" not in paths)
    check("没有 SSDT-PLUG.aml（与 DummyPowerManagement 方向相反）",
          "SSDT-PLUG.aml" not in paths)

    print("== canopy 变体（76 §2.2）==")
    cfg2, _, _ = build(copy.deepcopy(_synthetic_sample()), picker="canopy")
    check("PickerMode = External", cfg2["Misc"]["Boot"]["PickerMode"] == "External")
    check("OpenCanopy.efi 启用",
          any(d["Path"] == "OpenCanopy.efi" and d["Enabled"] for d in cfg2["UEFI"]["Drivers"]))
    check("两个变体只差 picker 相关键",
          cfg2["Misc"]["Security"] == cfg["Misc"]["Security"])

    print("== 缺键门禁：这是本脚本存在的主要理由 ==")
    broken = copy.deepcopy(_synthetic_sample())
    del broken["Kernel"]["Quirks"]["ProvideCurrentCpuInfo"]
    _, missing2, _ = build(broken)
    check("删掉一个键之后被报出来",
          "Kernel/Quirks/ProvideCurrentCpuInfo" in missing2, str(missing2))
    broken2 = copy.deepcopy(_synthetic_sample())
    del broken2["UEFI"]["APFS"]
    _, missing3, _ = build(broken2)
    check("删掉整个子节之后被报出来",
          any("UEFI/APFS" in m for m in missing3), str(missing3))
    broken3 = copy.deepcopy(_synthetic_sample())
    del broken3["Misc"]["Security"]["ScanPolicy"]
    _, missing4, _ = build(broken3)
    check("缺键时默认不写入（allow_new=False）",
          "ScanPolicy" not in broken3["Misc"]["Security"])
    check("--allow-new 时写入",
          build(copy.deepcopy(broken3), allow_new=True)[0]["Misc"]["Security"]["ScanPolicy"] == 0)
    check("缺键清单非空即调用方应当失败", len(missing4) > 0)

    print("== plist 往返（CI 要把它写成文件再被 OpenCore 读）==")
    buf = io.BytesIO()
    plistlib.dump(cfg, buf, sort_keys=True)
    buf.seek(0)
    back = plistlib.load(buf)
    check("往返后完全相同", back == cfg)
    check("csr 字段往返后仍是 4 字节 bytes",
          isinstance(back["NVRAM"]["Add"][APPLE_BOOT_GUID]["csr-active-config"], bytes)
          and len(back["NVRAM"]["Add"][APPLE_BOOT_GUID]["csr-active-config"]) == 4)

    print()
    if fails:
        print(f"自检失败 {len(fails)} 项: {', '.join(fails)}")
        return 1
    print("自检全过")
    return 0


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    table = {"generate": cmd_generate, "dump": cmd_dump, "selftest": cmd_selftest}
    fn = table.get(argv[1])
    if fn is None:
        print(f"不认识的子命令 {argv[1]!r}；有 {', '.join(table)}")
        return 2
    return fn(argv[2:])


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
