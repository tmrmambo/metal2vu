# 71 OpenCore 配置与最终可启动镜像的打包

文档版本：1.0
基线日期：2026-10-30
对应组件：无（基础设施分册，服务于全部组件）
上级文档：`docs/spec/00-OVERVIEW.md`
配套分册：`docs/spec/70-BUILD-PACKAGE.md`、`docs/spec/80-TEST-HARNESS.md`

## 0. 本文作用与写作约束

本文回答一个问题：**怎么从仓库里现有的素材造出一个能在 QEMU/KVM 上启动 macOS 26.7.2 (25G325) x86_64 的镜像，并把它交付到本地 KVM 与 Vultr 两层环境。**

它直接服务于 `80-TEST-HARNESS.md` 第 4.1 节的 **E0-L1**（macOS 在本地 KVM 上启动并 SSH 可达）。E0-L1 是本项目当前唯一的目标，而它的全部前置条件都在本文：引导器配置、磁盘控制器选择、SMBIOS 选择、串口通道、首启探针。

职责边界：

- **本文不重复 `70-BUILD-PACKAGE.md` 第 5 节。** SIP 位域的含义、`0xFEF` 的推导、`Add`/`Delete` 语义的坑、guest 内的四项验证，全部以那一节为准。本文做的是把那一节的 `NVRAM` 片段放回一份完整的 `config.plist` 里，并补上它没有涉及的其余八个顶层节。
- 本文也不重复 `80-TEST-HARNESS.md` 第 1 节的平台调研。但本文第 3 节**修正**了 80 分册第 1.5、4.3、5.1 节中关于 macOS VirtIO 支持的三条结论，依据是本轮从 25G325 x86_64 kernel collection 中取得的新证据。

写作约束同 `70`、`80` 两册：

- 每条结论带证据标签（`KNOWN` / `INFERRED` / `BLOCKED` / `TESTED`）与来源 URL。
- **本项目至今 `TESTED` 数量为零，本文同样没有 `TESTED`。** 本文的全部内容在 E0-L1 通过之前都是待验证的设计。
- 命令、`config.plist` 片段、脚本按可直接照抄编写。
- 对外部网页内容均为转述，不作连续摘录。**内容已转述以符合许可限制。**

---

## 1. 手头素材的实际形态

本节先把"我们到底有什么"钉死。后面每一条路径都依赖这个答案。

### 1.1 文件清单与一手校验

`KNOWN`，来源：本轮直接读取仓库文件。

| 路径 | 字节 | 容器类型（按文件头/尾判定） |
|---|---:|---|
| `SharedSupport.dmg`（仓库根） | 18,366,480,610 | UDIF（尾部 `koly` 存在），首扇区是 `BSD 4.4` 签名的 GPT protective MBR |
| `142-36613 - 26.7.2 macOS Tahoe (25G325)/InstallAssistant.pkg` | 18,384,411,815 | `xar!` 魔数，即 XAR 归档（macOS flat package） |
| `142-36613 - .../com_apple_MobileAsset_MacSoftwareUpdate.plist` | 1,522,841 | XML plist，MobileAsset 资产目录 |
| `142-36613 - .../InstallInfo.plist` | 181 | XML plist，**内容是一个空 dict** |
| `142-36613 - .../MajorOSInfo.pkg` | 1,365,805 | pkg |
| `142-36613 - .../UpdateBrain.zip` | 4,392,999 | zip |
| `AppleDiagnostics.dmg`（仓库根） | 2,889,199 | UDIF（尾部 `koly`），内层为 zlib 压缩块 |

`SharedSupport.dmg` 的 SHA-256 是 `521B8029FB15F2421FFEBEA9F06BE1B147B0EA067AAA2BB90AF552D8AE5F6D25`（`KNOWN`，来源 `analysis/binaries/macos26-25G325-x86_64/MANIFEST.md` 第 1 节，本轮未重算 18 GB 的哈希）。

### 1.2 `InstallInfo.plist` 是空字典，不能当信息源

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict/>
</plist>
```

`KNOWN`，这是文件全文。

在 macOS 10.x 时代，`Install macOS.app/Contents/SharedSupport/InstallInfo.plist` 描述 payload 的版本与包清单。**在这份 25G325 素材里它是空的**，所以版本信息必须从别处取。不要按旧教程去读它。

### 1.3 MobileAsset 资产目录：确认这是完整安装器而不是增量更新

`KNOWN`，来源：本轮用 `plistlib` 读 `com_apple_MobileAsset_MacSoftwareUpdate.plist`。

顶层三个键：`AssetType = com.apple.MobileAsset.MacSoftwareUpdate`、`FormatVersion = 1`、`Assets`（73 个条目）。

73 个条目的 `Build` 全部是 `25G325`，`OSVersion` 全部是 `26.7.2`。每个条目的 `SupportedDeviceModels` 是一个机型标识符，73 个条目覆盖 73 个机型，合起来就是 Apple 为 25G325 发货的全部机型。

第一个条目（`J152FAP`）的关键字段：

| 字段 | 值 |
|---|---|
| `Build` | `25G325` |
| `OSVersion` | `26.7.2` |
| `RestoreVersion` | `25.7.325.0.0,0` |
| `TrainName` | `CheerSecurityFizzB` |
| `InstallationSize` | 15,227,412,107 |
| `InstallationSize-Snapshot` | 5,553,249,931 |
| `_DownloadSize` | 18,356,470,215 |
| `_UnarchivedSize` | 19,211,607,040 |
| `ContainsSFRContent` | `True` |
| `CryptexSizeInfo` 的 tag | `cryptex-app`、`cryptex-system-x86_64`、`cryptex-system-arm64e` |
| `__RelativePath` | `com_apple_MobileAsset_MacSoftwareUpdate/d3cc6643f7010f6ec14cc728f4a47a7c7644e8a5.zip` |

三条判定，合起来说明**这是完整安装器资产，不是增量更新**：

1. `_DownloadSize = 18,356,470,215` 与 `SharedSupport.dmg` 内 HFS+ 卷里那个 zip 的大小**逐字节一致**（`MANIFEST.md` 第 1 节记录该 zip 为 18,356,470,215 字节）。即这份 `SharedSupport.dmg` 装的就是这个资产的完整下载体。
2. 资产里的 `AssetData/payloadv2/payload.NNN` 共 53 个，合计 458,715 个条目，其中包含完整的 `System/Library/Kernels/kernel`、两个 kernel collection、全部 `/System/Library/Extensions`。增量更新不会带这些。
3. `ContainsSFRContent = True` 表示包含 System Fallback Recovery 内容，即恢复环境随资产交付。

`KNOWN`。

同时登记一条**对本文第 4 节决定性的事实**：73 个 `SupportedDeviceModels` 中，x86 相关的只有 8 个，其余 65 个是 Apple Silicon 的 `JxxxAP` / `X589AMLUAP` / `VMA2MACOSAP` / `X86LEGACYAP` 一类标识符。8 个 x86 标识符是：

```text
Mac-112818653D3AABFC   Mac-27AD2F918AE68F61   Mac-5F9802EFE386AA28
Mac-A61BADE1FDAD7B05   Mac-AF89B6D9451A490B   Mac-CFF7D910A743CAAF
Mac-E1008331FDC96864   VMM-x86_64
```

### 1.4 `SharedSupport.dmg` 的容器层级

`KNOWN`，来源：`analysis/binaries/macos26-25G325-x86_64/MANIFEST.md` 第 1 节（上一轮已逐层解出并登记）。本文只引用，不重复推导。

```text
SharedSupport.dmg                      未压缩 UDIF，chunk 类型只有 0x0/0x1/0x2，可随机访问
  └─ GPT 分区 "disk image (Apple_HFS : 5)"     虚拟字节偏移 209,735,680
      └─ HFS+ 卷（81 files / 4 folders）
          └─ com_apple_MobileAsset_MacSoftwareUpdate/
                 d3cc6643f7010f6ec14cc728f4a47a7c7644e8a5.zip     18,356,470,215 字节
              ├─ AssetData/payloadv2/payload.000 … payload.052     53 个
              │     pbzx → XZ 分块 → Apple Archive（YAA1）流
              └─ AssetData/payloadv2/basesystem_patches/x86_64BaseSystem.dmg
                    zip header offset 6,867,904,670，891,864,876 字节
                    SHA-256 35745579C8FBC20ABBD98E5954B70BE22F329DF199D06429604A042F8765827E
```

**"UDIF 未压缩"这一点是本文全部 Windows 侧可行性的根基。** 它意味着不需要 `hdiutil`、不需要 `dmg2img`，用纯 Python 做随机访问读取就能取到里面任意文件。仓库已有的 `analysis/binaries/macos26-25G325-x86_64/tools/` 九个脚本就是干这件事的，本轮全部复用。

### 1.5 BaseSystem 已经可取，而且不需要 macOS

`KNOWN`，来源：`MANIFEST.md` 第 10.3 节。

`AssetData/payloadv2/basesystem_patches/x86_64BaseSystem.dmg` 是一个 **`BXDIFF50` 全量替换补丁**（不是依赖源文件的差分）。上一轮用 `ipsw 3.1.739` 的 `ota patch bxdiff` 子命令把它还原成了一个 DMG：

| 项 | 值 |
|---|---|
| 还原后字节 | 1,464,270,504 |
| SHA-256 | `642E6148288527C51639D1B08C7F0B5A8CB4A68AEC2AC6DA3C78CF1723C5119A` |
| 交叉校验 | 与 `analysis/spec-work/metal-registration-contract.md` 第 1.1 节既有记录逐位相同 |

`ipsw` 是 Go 写的单文件命令行工具，提供 Windows 二进制（<https://github.com/blacktop/ipsw>），所以这一步也在 Windows 上完成，没有 macOS 参与。

**1.46 GB 这个数字决定了整个 Vultr 交付方案。** 它远低于 Vultr ISO 的 10 GB 上限（`80` 第 1.2 节约束 3），而 `InstallAssistant.pkg` 的 18.38 GB 远超上限。详见第 8.3 节。

`INFERRED`：还原出的 DMG 是**带 GPT 分区表的磁盘镜像**而不是裸卷镜像。依据是 `MANIFEST.md` 第 10.3 节末句提到"该 DMG 与其 APFS 分区镜像"，即从 DMG 里又分出了一层分区。查清方法见第 8.2.3 节给的 `qemu-img info` 命令。这一点影响第 8 节里它是被当作 `com.apple.recovery.boot` 的 DMG 还是被当作一块 raw 盘挂上去。

### 1.6 素材充分性结论

| 要造的东西 | 素材够不够 | 缺什么 |
|---|---|---|
| OpenCore EFI 分区 | 够。OpenCore 与全部 kext 从 GitHub release 取，纯下载 | 无 |
| 恢复/安装环境（可启动） | **够**。`x86_64BaseSystem.dmg` 已还原，1.46 GB | `BaseSystem.chunklist` **不在素材里**，见下 |
| 离线完整安装（不联网装系统） | 够。`InstallAssistant.pkg` 在手，走 `70` 的 run_offline 式流程 | 需要一块能被 guest 读到的 18.4 GB 介质 |
| 用 `createinstallmedia` 造的标准安装盘 | **不够**。需要 macOS | 规避方案见第 2.4 节 |

**缺失项只有一个，`BaseSystem.chunklist`。** `KNOWN`：本轮在 `payloadv2-full-index.tsv.zip` 的 458,715 条路径里检索 `chunklist` 子串，**零命中**；检索 `com.apple.recovery.boot` 子串，**零命中**。即这份资产里既没有 chunklist，也没有现成的 recovery.boot 目录布局。

这个缺失的后果与绕法在第 6.6.3 节（`DmgLoading`）与第 8.2.3 节处理。一句话结论：把 BaseSystem 当成一块**普通磁盘**挂上去，而不是当成一个待校验的 DMG，chunklist 就不需要了。

---

## 2. 三类平台的工作划分

开发机是 Windows + PowerShell，已装 `git`、`curl`、`tar`、`py` 3.14、`cargo`/`rustc`；**没有** clang / cmake / meson / ninja / 7z / xcodebuild / hdiutil / dmg2img。这是 `70` 第 1.4 节记录的现状，本节在镜像打包这件事上把它落实。

### 2.1 Windows 上能做完的事

全部是只读解析与纯 Python 加工，`KNOWN`（本轮已实际执行）：

| 任务 | 工具 | 本轮是否已跑 |
|---|---|---|
| 读 `SharedSupport.dmg` 的 UDIF / GPT / HFS+ / zip / pbzx / YAA1 | `tools/udif.py` `hfsplus.py` `vfile.py` `yaa.py` | 是 |
| 按逻辑路径抽取任意文件 | `tools/extract_one.py` | 是，本轮抽了 15 个 plist |
| 重建 `MH_FILESET` kernel collection 并枚举 fileset 条目 | `tools/scan.py` `kc.py` | 是，本轮枚举了 204 + 172 条 |
| 还原 `BXDIFF50` 的 BaseSystem | `ipsw`（Windows 二进制） | 上一轮已跑 |
| 下载 OpenCore release 与 kext | `curl` | 可 |
| 生成 `config.plist` | `py` + `plistlib` | 可 |
| 计算全部产物哈希与清单 | `py` + `hashlib` | 可 |
| 驱动 Linux 构建机与 Vultr API | `curl` / `ssh` | 可 |

**EFI 分区的内容可以在 Windows 上完全准备好**，因为它只是一棵文件树加一个 plist。

### 2.2 必须在 Linux 上做的事

都是"把文件树变成块设备镜像"这一类，需要 `mkfs.vfat` / `mtools` / `xorriso` / `qemu-img` / `sgdisk`，Windows 上没有对应物。

| 任务 | 命令 | 为什么不能在 Windows 做 |
|---|---|---|
| 造 FAT32 的 EFI 镜像 | `mkfs.vfat` + `mcopy` | Windows 能格式化 FAT，但不能对**文件内的镜像**原地格式化与写入 |
| UDIF → raw 转换 | `qemu-img convert -f dmg -O raw` | 没有 `qemu-img`，也没有 `dmg2img` |
| 造 qcow2 与 overlay | `qemu-img create` | 同上 |
| 造 hybrid ISO | `xorriso -as mkisofs` | 没有 `xorriso` / `mkisofs` / `genisoimage` |
| 造 GPT raw 磁盘镜像 | `sgdisk` / `sfdisk` + `dd` | 没有对应工具 |
| 跑 QEMU/KVM | `qemu-system-x86_64` | 需要 KVM |

`INFERRED`：这些工具在任意主流发行版上都是一条 `apt install qemu-utils mtools dosfstools xorriso gdisk` 的事。用户的 KVM 机器默认是 Linux，所以这一类任务天然落在那台机器上，不构成额外成本。

### 2.3 真正需要 macOS 的只有一件事

**`createinstallmedia` 需要 macOS，没有任何替代实现。** `KNOWN`：Apple 的 `createinstallmedia` 是 `Install macOS.app` 内的可执行文件，只能在 macOS 上运行；社区造 macOS 安装 ISO 的工具链（`LongQT-sea/mkmaciso`）明确声明"只用 macOS 自带工具与命令"，并为没有 macOS 的用户提供的唯一替代是**跑在 Azure 托管 Mac mini 上的 GitHub Action**（转述自 <https://github.com/LongQT-sea/macos-iso-builder/blob/main/README.md>）。即它绕开的是"你自己没有 Mac"，不是"不需要 Mac"。

所以必须回答：**不走 `createinstallmedia`，能不能造出可启动介质。** 答案是能，见下一节。

顺带一个已知的时间与体积参数，对第 8.3 节有用：同一项目把产物分成两档，recovery 镜像小、构建 2 到 5 分钟；完整离线安装器 5 到 18 GB、构建 5 到 60 分钟（转述自同一来源）。**完整安装器这一档的体积区间上沿已经超过 Vultr 的 10 GB 限制**，而 25G325 恰好落在上沿（18.4 GB）。

### 2.4 不用 macOS 造可启动介质：两条路

社区在 KVM 上跑 macOS 的通行做法根本不用 `createinstallmedia`。它把 **BaseSystem 当成一块磁盘**挂进虚机，由 OpenCore 去引导它，进去之后在恢复环境里完成安装。

#### 路 A：recovery 盘（首选）

`KNOWN`，来源：`kholia/OSX-KVM` 的 `OpenCore-Boot.sh`（<https://github.com/kholia/OSX-KVM/blob/master/OpenCore-Boot.sh>）把 BaseSystem 以 **raw 格式、经 AHCI 当硬盘**挂上：

```bash
-device ich9-ahci,id=sata
-drive id=InstallMedia,if=none,file="$REPO_PATH/BaseSystem.img",format=raw
-device ide-hd,bus=sata.3,drive=InstallMedia
```

同一仓库的 README 说明 `fetch-macOS-v2.py` 的产出就是 `BaseSystem.dmg`，随后被转成 `BaseSystem.img`（转述自 <https://github.com/kholia/OSX-KVM/blob/master/README.md>）。

**我们手上的 `x86_64BaseSystem.dmg` 与 `fetch-macOS-v2.py` 下载的是同一类产物**（都是 25G325 的 x86_64 BaseSystem），所以这条路对我们成立且不需要联网下载。`INFERRED`，两者是否逐位相同未验证，也不需要相同。

这条路**不涉及 `com.apple.recovery.boot`，也不涉及 chunklist**，因为 OpenCore 看到的是一块带 APFS/HFS+ 卷的普通盘，走的是正常的 bless 扫描，不是 DMG 加载。这是它比路 B 好的唯一原因，而这个原因刚好正中我们缺 chunklist 的要害。

#### 路 B：`com.apple.recovery.boot` 布局

`KNOWN`，来源：OpenCore 官方文档的 Tips and Tricks 一节说明，最简单的装 macOS 的办法是把在线 recovery 镜像的 `*.dmg` 与 `*.chunklist` 两个文件放进 OpenCore 所在 FAT32 分区的 `com.apple.recovery.boot` 目录，OpenCore picker 里会出现带 `(dmg)` 后缀的条目；下载可用 `macrecovery.py`。同一节还指出**在线 recovery 镜像加载失败的常见原因是缺 HFS+ 驱动**，因为目前已知的 recovery 卷都是 HFS+ 文件系统（转述自 <https://dortania.github.io/docs/release/Configuration.html>）。

对我们的两个后果：

1. **必须加载 HFS+ 驱动**（`OpenHfsPlus.efi`），否则 DMG 挂上也读不出来。这一条对路 A 同样成立，因为 BaseSystem 卷同样可能是 HFS+。
2. **缺 chunklist 就必须把 `DmgLoading` 从默认的 `Signed` 改成 `Any`**。官方对 `Any` 的描述是强烈不建议，并且在 Apple Secure Boot 生效时会导致启动失败（转述自同一来源）。我们把 `SecureBootModel` 设为 `Disabled`，所以"Apple Secure Boot 生效"这个前提不成立，`Any` 在研发期可用，但它比路 A 多引入一条不必要的信任放宽。

**结论：用路 A，路 B 只作为路 A 失败时的备选。** 第 6 节的 `config.plist` 同时把两条路的前提都配好（`ScanPolicy = 0`、加载 `OpenHfsPlus.efi`），这样切换不需要改配置。

#### 完全离线安装（装系统时不联网）

路 A 进去之后，恢复环境默认会从 Apple 下载完整安装器。要避免这一步，把 `InstallAssistant.pkg` 作为**第三块介质**挂上，在恢复环境的终端里直接跑包内的安装器。`KNOWN`，来源：`OSX-KVM` 的 `run_offline.md`（<https://github.com/kholia/OSX-KVM/blob/master/run_offline.md>）给出的流程是把 `InstallAssistant.pkg` 与一个脚本打成 ISO、以 `ide-hd` 挂上、在恢复环境的 Disk Utility 里分区格式化、然后在终端执行介质上的脚本。

它给的 `mkisofs` 命令行里 `-allow-limited-size -iso-level 3` 两个开关是必须的，因为单个文件 18.4 GB 超过了 ISO9660 的 4 GB 单文件上限。

**这条路在 L1 可用，在 L2 不可用**（18.4 GB 超 Vultr ISO 上限）。L2 的离线方案见第 8.3.4 节。

### 2.5 本文用到的外部件与版本

写进 `70` 第 7 节的 `MANIFEST.json` 时，镜像侧也要有一份版本清单。本文要求记录的最小集：

| 件 | 取得方式 | 本文编写时的版本 |
|---|---|---|
| OpenCorePkg（RELEASE 与 **DEBUG 两套都要留**） | <https://github.com/acidanthera/OpenCorePkg/releases> | 查 release 页取最新，写死 tag |
| `OcBinaryData`（OpenCanopy 资源、`OpenHfsPlus.efi` 等） | <https://github.com/acidanthera/OcBinaryData> | 固定 commit |
| Lilu.kext | <https://github.com/acidanthera/Lilu/releases> | 固定 tag |
| VirtualSMC.kext | <https://github.com/acidanthera/VirtualSMC/releases> | 固定 tag |
| AppleMCEReporterDisabler.kext | 随 VirtualSMC release 分发 | 同上 |
| OVMF（`OVMF_CODE_4M.fd` + `OVMF_VARS.fd`） | 发行版 `ovmf` 包，或 `OSX-KVM` 仓库内的副本 | 记录来源与 SHA-256 |
| `ipsw` | <https://github.com/blacktop/ipsw/releases> | `3.1.739`（上一轮用的版本） |

**DEBUG 与 RELEASE 两套都要留**，理由是 `80` 第 1.4 节：L1 的串口是 panic 期唯一文本通道，而 OpenCore 的 RELEASE 构建几乎不输出日志。`KNOWN`，OpenCore 调试文档要求把 `BOOTx64.efi`、`OpenCore.efi`、`OpenRuntime.efi`、`OpenCanopy.efi` 四个文件换成 DEBUG 或 NOOPT 版本才能拿到有用的信息，并提示排错时最好先不用 OpenCanopy（转述自 <https://dortania.github.io/OpenCore-Install-Guide/troubleshooting/debug>）。

---

## 3. 25G325 x86_64 自带的虚拟化驱动

**本节是本文最重要的内容，它修正了 `80-TEST-HARNESS.md` 第 5.1 节"头号风险"的事实前提。**

`80` 第 1.5 节与第 5.1 节的推理链是：macOS 原生没有 VirtIO 块设备驱动 → 云平台如果把系统盘做成 virtio-blk，macOS 看不到启动盘 → 整个 L2 层乃至 `00-OVERVIEW` 第 2.1 节的部署形态不成立。那条链的第一环来自社区通行做法（大家都用 AHCI）与"网卡侧有 `virtio-net-osx`、块设备侧没有等价物"这个观察。

本轮直接查了 25G325 的 x86_64 内核二进制，**第一环是错的**。

### 3.1 取证方法

`KNOWN`。两个 kernel collection 从 `SharedSupport.dmg` 重建，然后按 `LC_FILESET_ENTRY` 枚举。复现命令（在 `tools/` 的副本目录里，不要在仓库内跑，中间产物 436 MB）：

```powershell
py scan.py payload.006 payload.005
# payload.006: 3 entries, 1 extracted, leftover=0
# payload.005: 2 entries, 1 extracted, leftover=0
py kc.py out\payload.006\System__Library__KernelCollections__BootKernelExtensions.kc
py kc.py out\payload.005\System__Library__KernelCollections__SystemKernelExtensions.kc
```

| collection | 字节 | 架构 | fileset 条目 | `LC_UUID` | SHA-256 |
|---|---:|---|---:|---|---|
| `BootKernelExtensions.kc` | 67,584,000 | x86_64 单架构 | **204** | `F6EB5100-67F3-FB2F-6706-BE6A8D30B730` | `AD6F93AF96071D10F7483D1E4268331E2346FE0EC641AC896E03527FC8FDEBF4` |
| `SystemKernelExtensions.kc` | 369,213,440 | x86_64 单架构 | **172** | `EAAB5F23-BA1B-DAF9-781D-6C22A45A9689` | `5EDE2BA5627482282E8964B00B6E17A0F7115F07D799E618DB806FBC60D94421` |

哈希与条目数与 `MANIFEST.md` 第 2 节既有记录一致，说明取的是同一来源。

**"在 x86_64 KC 的 fileset 条目里"这件事本身就是架构证据。** 资产里的 `payloadv2` 是跨架构共用的（同一棵 `/System/Library/Extensions` 同时服务 73 个机型，其中 65 个是 arm64），所以**一个 kext 的 `Info.plist` 存在不代表它有 x86_64 代码**。KC 的 fileset 条目则是逐条带 `LC_UUID` 与 `vmaddr` 的真实 Mach-O，不会骗人。本节所有"存在"的结论都建立在 KC 条目上，不建立在 `Info.plist` 的存在上。

### 3.2 `AppleVirtIO` 在 x86_64 Boot KC 里，而且带 virtio-blk

`KNOWN`。Boot KC 的 fileset 条目：

```text
com.apple.driver.AppleVirtIO     vm=0xffffff8001ed8000  off=0x1dd8000
                                 uuid=82ABA0E4-1BDD-3DDD-A89A-A077B24B8826
```

对应 bundle 为 `System/Library/Extensions/AppleVirtIO.kext`，`CFBundleVersion = 248.160.1`，`OSBundleRequired = Local-Root`，`CFBundleSupportedPlatforms = ["MacOSX"]`，`DTSDKName = macosx26.7.internal`。`Info.plist` 取自 `payload.050`，3 个来源交叉一致。

`OSBundleLibraries` 全文：

```text
com.apple.iokit.IOHIDFamily        1.5
com.apple.iokit.IONetworkingFamily 1.4.3
com.apple.iokit.IOPCIFamily        2.9
com.apple.iokit.IOSerialFamily     11.0
com.apple.iokit.IOStorageFamily    2.1
com.apple.kpi.bsd / iokit / libkern / mach / private   15.5
```

**没有任何 ARM 平台依赖。** 这与第 3.3 节的 `AppleVirtIOStorage` 形成对照。

18 个 personality，按 `IOVirtIOPrimaryMatch` 排列（`KNOWN`，全文从 `Info.plist` 读出）：

| personality | `IOClass` | provider | 匹配值 | VirtIO device type |
|---|---|---|---|---|
| `AppleVirtIOPCITransport` | `AppleVirtIOPCITransport` | `IOPCIDevice` | `IOPCIPrimaryMatch = 0x00001af4&0x0000FFFF` | 任意 vendor `0x1af4` 设备 |
| `AppleVirtIONetwork` | `AppleVirtIONetwork` | `AppleVirtIOTransport` | `0x00011af4` | 1 = net |
| **`AppleVirtIOBlock`** | **`AppleVirtIOBlockStorageDevice`** | `AppleVirtIOTransport` | **`0x00021af4`** | **2 = block** |
| `AppleVirtIOConsole` | `AppleVirtIOConsole` | `AppleVirtIOTransport` | `0x00031af4` | 3 = console |
| `AppleVirtIOEntropy` | `AppleVirtIOEntropy` | `AppleVirtIOTransport` | `0x00041af4` | 4 = rng |
| `AppleVirtIOBalloon` | `AppleVirtIOBalloon` | `AppleVirtIOTransport` | `0x00051af4` | 5 = balloon |
| `AppleVirtIO9P` | `AppleVirtIO9P` | `AppleVirtIOTransport` | `0x00091af4` | 9 = 9p |
| `AppleVirtIOInput` | `AppleVirtIOInput` | `AppleVirtIOTransport` | `0x00121af4` | 18 = input |
| `AppleVirtIOInputKeyboard` / `Mouse` / `Trackpad` | 同名 | `AppleVirtIOInput` | `IOPropertyMatch` on `AppleVirtIOInputType` | — |
| `AppleVirtIOSocket` | `AppleVirtIOSocket` | `AppleVirtIOTransport` | `0x00131af4` | 19 = vsock |
| `AppleVirtIOIOMMU` | `AppleVirtIOIOMMU` | `AppleVirtIOTransport` | `0x00171af4` | 23 = iommu |
| `AppleVirtIOSound` | `AppleVirtIOSound` | `AppleVirtIOTransport` | `0x00191af4` | 25 = sound |
| `AppleVirtIOFS` | `AppleVirtIOFS` | `AppleVirtIOTransport` | `0x001a1af4` | 26 = fs |
| `AppleVirtIOSocketPrivate(Transport)` | — | — | `0x1a0d106b` | Apple 私有 |

两个关键点：

1. **transport 匹配的是厂商号而不是设备号。** `IOPCIPrimaryMatch` 比较的是 `(device<<16)|vendor` 这个 32 位值，掩码 `0x0000FFFF` 只保留低 16 位，即只比较 vendor。`0x1af4` 是 Red Hat / VirtIO 的 PCI 厂商号，QEMU 的全部 `virtio-*-pci` 设备都是这个厂商号。所以 transport 会匹配上 QEMU 的 virtio-blk、virtio-net、virtio-serial、virtio-rng。`KNOWN`（匹配语义按 `IOPCIFamily` 的既有约定，掩码行为见 `analysis/binaries/macos26-25G325-x86_64/plists/` 下 `IOPCIFamily.kext` 的 `Info.plist` 与 `IOPCIFamily.exports`）。
2. **第二层匹配的是 VirtIO device type 而不是 PCI device id。** `IOVirtIOPrimaryMatch` 是 `AppleVirtIOTransport` 自己发布的属性，值形如 `0x00021af4`，低 16 位是厂商号、高 16 位是 VirtIO 设备类型号。这意味着 legacy/transitional（PCI device id `0x1001`）与 modern（`0x1042`）两种 virtio-blk 应该都会被归一化成类型 2。

`INFERRED`，第 2 点的"应该"是未实测的部分：`AppleVirtIOPCITransport` 从哪里读出设备类型（modern 的 `0x1040+N` device id、还是 legacy 的 subsystem device id、还是 modern capability 结构）没有反编译确认。**保守做法是在 QEMU 侧强制 modern-only**（`disable-legacy=on,disable-modern=off`），因为 Apple 自己的 VirtIO 实现（Apple Silicon 的 Virtualization.framework）只用 modern。查清方法见第 11 节 I-003。

### 3.3 `AppleVirtIOStorage` 确证是 ARM 专用，不要被它误导

`KNOWN`，两条独立证据：

1. **它不在任何一个 x86_64 KC 里。** 本轮对 204 + 172 条 fileset 条目做了子串检索，`AppleVirtIOStorage` 零命中。
2. **它的 `OSBundleLibraries` 要求 `com.apple.driver.AppleARMPlatform`。** 全文：

```text
com.apple.driver.AppleARMPlatform  1.0.0     ← ARM 平台 kext，x86 上不存在
com.apple.driver.AppleVirtIO       1.0.0
com.apple.iokit.IOPCIFamily        1.0.0
com.apple.iokit.IOStorageFamily    1.7.0
com.apple.kpi.*
```

它的两个 personality 也只匹配 Apple 自家的 VirtIO PCI 设备，不匹配 QEMU：

```text
AppleVirtIOStorageDevice     IOClass=AppleVirtIOStorageDevice
                             provider=AppleVirtIOTransport
                             IOVirtIOPrimaryMatch=0x1a00106b      ← vendor 0x106b = Apple
AppleVirtIOUtilPCITransport  IOClass=AppleVirtIOPCITransport
                             provider=IOPCIDevice
                             IOPCIPrimaryMatch=0x1a00106b&0xFFFFFFFF
```

**所以"macOS 有一个叫 AppleVirtIOStorage 的 kext"不是好消息，它跟我们无关。** 好消息是上一节的 `AppleVirtIO` 里那条 `AppleVirtIOBlock` personality。这两件事很容易混起来，分册之间引用时必须指名道姓。

### 3.4 NVMe 与 AHCI 的匹配条件

两者都在 **Boot KC** 里，即都能在启动期提供根设备。

```text
com.apple.iokit.IONVMeFamily        vm=0xffffff80026bc000 uuid=B9B4F6B6-8158-33FE-ABB8-09B8672040A6
com.apple.driver.AppleAHCIPort      vm=0xffffff800150c000 uuid=0D19E48E-8515-37E5-89CB-8190EF0D69D2
com.apple.iokit.IOAHCIBlockStorage  vm=0xffffff80024be000 uuid=442E14DA-4959-3610-BBF4-56414753E04B
com.apple.iokit.IOSCSIParallelFamily vm=0xffffff8002ad8000 uuid=9A67BBD9-91FB-3D15-9F54-1251917C4603
com.apple.driver.AppleLSIFusionMPT  vm=0xffffff8001b30000 uuid=2ED6EBC2-E7AE-3615-9C31-3CBB7CD3E897
```

`KNOWN`，`Info.plist` 里对我们有用的 personality：

**`IONVMeFamily` 的 `GenericNVMeSSD`**：

```text
IOClass              = IONVMeController
IOProviderClass      = IOPCIDevice
IOPCIClassMatch      = 0x01080200&0xffffff00
IOPCIPauseCompatible = true
IOPCITunnelCompatible= true
Chipset Name         = SSD Controller
```

类码 `01 08 02` 就是 PCI 的 mass storage / NVM / NVMHCI。QEMU 的 `-device nvme` 正是这个类码。**这是一条纯类码匹配，不挑厂商号和设备号**，所以 QEMU 的模拟 NVMe 会被 `IONVMeController` 接上。`KNOWN` 对于匹配条件本身，`INFERRED` 对于"因此一定能启动"。

同一个 `Info.plist` 里另有 6 个 `AppleANS*` personality，provider 是 `RTBuddyService`、`IOPropertyMatch = {role: ANS2}`，那是 Apple Silicon 的内置 SSD 控制器，与我们无关。注意 `IONVMeFamily` 的 `OSBundleLibraries` 里含 `AppleARMPlatform`、`AppleA7IOP`、`RTBuddy` 等 ARM 件，**但它本体确实在 x86_64 Boot KC 里**，所以这些依赖在 x86 上的解析方式不影响结论。`INFERRED`：这是 Apple 单一 `Info.plist` 服务双架构的产物；KC 条目是更强的证据，以 KC 为准。

**`AppleAHCIPort` 的 `GenericAHCI`**：

```text
IOClass              = AppleAHCI
IOProviderClass      = IOPCIDevice
IOPCIClassMatch      = 0x01060100&0xffffff00
IOProbeScore         = 800
```

类码 `01 06 01` = mass storage / SATA / AHCI 1.0。QEMU 的 `ich9-ahci` 是这个类码。同一文件里还有 `ICH10AHCI`（`IOPCIPrimaryMatch = 0x3a228086`，`IOProbeScore = 2000`）等具名 personality，但 QEMU 的 `ich9-ahci` 设备号是 `0x2922`，走的是通用类码那条。`KNOWN`。

**`AppleLSIFusionMPT` + `IOSCSIParallelFamily` 在 Boot KC 里**，这给了第三条路（QEMU 的 `-device mptsas1068`）。`INFERRED`，未展开评估，登记为 I-008。

### 3.5 网卡

Boot KC 里的以太网驱动（`KNOWN`）：

```text
com.apple.driver.AppleVmxnet3Ethernet   vm=0xffffff80029d6000 uuid=74B74CC4-242E-3F1A-8391-BCBD60AD2514
com.apple.iokit.AppleBCM5701Ethernet    （Boot KC 条目存在）
com.apple.driver.AppleEthernetAquantiaAqtion
com.apple.driver.AppleEthernetRL        vm=0xffffff800293e000 uuid=DE23F9F0-73EA-3CAE-B1AC-2D013C116388
com.apple.iokit.IONetworkingFamily      （Boot KC 条目存在）
```

加上第 3.2 节的 `AppleVirtIONetwork`，在 KVM 上有两个可用选择：

| QEMU 设备 | guest 侧驱动 | 匹配条件 | 标签 |
|---|---|---|---|
| `-device vmxnet3` | `AppleVMXNETController`（`AppleVmxnet3Ethernet.kext` v1.0.10） | `IOPCIPrimaryMatch = 0x07b015ad&0xffffffff`，`IOPCIClassMatch = 0x02000000&0xffff0000`，`OSBundleRequired = Network-Root` | `KNOWN` 驱动存在且在 Boot KC |
| `-device virtio-net-pci` | `AppleVirtIONetwork` | `IOVirtIOPrimaryMatch = 0x00011af4` | `KNOWN` 驱动存在且在 Boot KC |

`0x15ad` 是 VMware 的厂商号，`0x07b0` 是 vmxnet3。`Info.plist` 里的 `Product Name` 就是 `VMXNet3 Ethernet`。

**社区的现状已经从 vmxnet3 转向 virtio-net。** `KNOWN`：`OSX-KVM` 的 `OpenCore-Boot.sh` 默认那一行用的是 `-device virtio-net-pci`，而 `vmxnet3` 那一行被注释掉并标注"用于 High Sierra"（转述自 <https://github.com/kholia/OSX-KVM/blob/master/OpenCore-Boot.sh>）。这与本节的二进制证据一致。

**后果：`80` 第 1.5 节说"网卡侧存在第三方驱动 `virtio-net-osx`"这句话在 25G325 上不再需要。** 不要装第三方网卡 kext，系统自带的更可靠。

`80` 第 2.4.2 节的 QEMU 命令行用的是 `-device vmxnet3`。本文第 8.2 节给出的替换行改用 `virtio-net-pci`，理由见第 7 节（统一走 virtio 可以让 L1 的设备模型更接近 Vultr 可能的设备模型，从而让 L1 的绿灯更有参考价值）。

### 3.6 `ApplePVPanic` 存在，并且匹配 QEMU 的 ACPI 设备

`KNOWN`。Boot KC 条目：

```text
com.apple.driver.ApplePVPanic   vm=0xffffff8001c03000 uuid=97F60345-235A-388F-B2D7-79557A667A0F
```

`Info.plist` 两个 personality：

```text
ApplePVPanicISA   IOClass=ApplePVPanicISA   IOProviderClass=IOACPIPlatformDevice
                  IONameMatch="QEMU0001"   IOProbeScore=2000  IOPlatformPanicAction=0
ApplePVPanicMMIO  IOClass=ApplePVPanicMMIO  IOProviderClass=AppleARMIODevice
                  IONameMatch="qemu,pvpanic-mmio"  IOProbeScore=2000  IOPlatformPanicAction=0
```

`QEMU0001` 是 QEMU 为 `-device pvpanic` 生成的 ACPI `_HID`。`OSBundleLibraries` 只要 `kpi.iokit` 与 `kpi.libkern`，没有架构依赖。

**这直接推进了 `80` 第 4.3 节的 H-010**（"macOS guest 是否响应 `pvpanic`"）。原本的查清方法是在 E0-L1 时故意触发 panic 观察；现在可以先把状态从"完全未知"收窄为"驱动存在、匹配条件已知、`IOPlatformPanicAction` 默认 0"。仍需实测的是 `IOPlatformPanicAction = 0` 对应的具体行为（是否向 host 发 panic 事件、还是只记录）。登记为 I-009。

实用价值：加上 `-device pvpanic` 之后，host 侧可以通过 QMP 的 `GUEST_PANICKED` 事件立即知道 guest panic 了，不必靠"串口静默 + 超时"去推断。这让 `80` 第 2.9 节的 `Detector` 多一条确定信号。

### 3.7 对 `80-TEST-HARNESS.md` 三处结论的修正

| 位置 | 原结论 | 本文结论 | 依据 |
|---|---|---|---|
| `80` 1.5 节表格注与 5.1 节 | macOS 原生不含 VirtIO 块设备驱动，块设备侧没有可用的第三方等价物 | **25G325 x86_64 Boot KC 内含 `AppleVirtIO`，其 `AppleVirtIOBlock` personality 把 VirtIO 设备类型 2 绑到 `AppleVirtIOBlockStorageDevice`；transport 匹配任意 vendor `0x1af4` 的 PCI 设备** | 本文 3.2，`KNOWN` |
| `80` 1.5 节 | 网卡侧需要第三方 `virtio-net-osx` | **系统自带 `AppleVirtIONetwork`，无需第三方 kext** | 本文 3.5，`KNOWN` |
| `80` 4.3 节 H-010 | macOS guest 是否响应 pvpanic，`INFERRED`，靠实测 | **驱动存在、匹配 `QEMU0001`、在 Boot KC 内**；待测的只剩行为细节 | 本文 3.6，`KNOWN` |

**头号风险的性质因此改变，但没有消失。** 修正后的风险陈述是：

> macOS 26.7.2 x86_64 具备 VirtIO 块设备驱动，所以"Vultr 的系统盘是 virtio-blk"不再等于"装不上"。真正未确证的是三件事：(a) `AppleVirtIOPCITransport` 能否认出 QEMU 的 virtio-blk-pci 并发布正确的设备类型属性；(b) UEFI 固件侧能否从该盘读出 OpenCore 与 `boot.efi`；(c) Vultr 的固件是否允许自定义引导链。(a) 与 (b) 在 L1 上可以完全测清，只有 (c) 必须在 L2 测。

这是一个重要的变化：**原来的头号风险在 L1 上测不出来（`80` 第 1.7 节末行"本地绿灯不能推断 Vultr 绿灯"），修正后它的大部分在 L1 上可测。** 第 7 节把这件事做成了三条并行的 L1 实验。

`BLOCKED` 仍然成立的部分：Vultr 系统盘的实际控制器型号（`80` 的 H-001）、NVRAM 持久性（H-002）、固件是否拾取 `EFI/BOOT/BOOTX64.EFI`（`80` 1.5 节的"自定义引导链"行）。这三条只能由 E0-L2 关闭。

---

## 4. SMBIOS 与 board-id

这是"装不上"的头号单点原因。macOS 26 Tahoe 是 Intel 的最后一版，受支持的 Intel 机型清单非常窄，而 SMBIOS 写错的表现是安装器直接拒绝，不是报错信息友好的那种失败。

### 4.1 `PlatformSupport.plist` 原文

`KNOWN`。本轮从 `payload.050` 抽出 `System/Library/CoreServices/PlatformSupport.plist`（790 字节，`AFT = 8` 即目标卷上以 AppleFSCompression 存储、归档内是解压后内容）。全文：

```xml
<plist version="1.0">
<dict>
  <key>SupportedBoardIds</key>
  <array>
    <string>Mac-E1008331FDC96864</string>
    <string>Mac-27AD2F918AE68F61</string>
    <string>Mac-CFF7D910A743CAAF</string>
    <string>Mac-AF89B6D9451A490B</string>
    <string>Mac-5F9802EFE386AA28</string>
    <string>Mac-A61BADE1FDAD7B05</string>
    <string>Mac-112818653D3AABFC</string>
    <string>VMM-x86_64</string>
  </array>
  <key>SupportedModelProperties</key>
  <array>
    <string>MacBookPro16,1</string>
    <string>MacPro7,1</string>
    <string>iMac20,1</string>
    <string>iMac20,2</string>
    <string>MacBookPro16,2</string>
    <string>MacBookPro16,4</string>
  </array>
</dict>
</plist>
```

抽取命令（可照抄）：

```powershell
py extract_one.py payload.050 "System/Library/CoreServices/PlatformSupport.plist"
```

**这 8 个 board-id 与第 1.3 节 MobileAsset 目录里的 8 个 x86 `SupportedDeviceModels` 完全相同**，两个独立来源互相印证。`KNOWN`。

两条立即可用的结论：

1. **`VMM-x86_64` 在受支持清单里。** 这是 Apple 给虚拟机用的 board-id。它的存在说明 25G325 的 x86_64 分支明确支持在虚机里跑。
2. **`iMacPro1,1` 不在清单里。** 它的 board-id 是 `Mac-7BA5B2D9E42DDD94`（见 4.2），不在上面 8 个之中。很多 KVM 上跑 macOS 的现成配置默认用 `iMacPro1,1`，**那些配置直接搬到 25G325 上会被安装器拒绝。**

### 4.2 board-id 到机型的映射

`KNOWN`，来源：OpenCorePkg 的 `AppleModels` 数据库，每个机型一个 YAML，`BoardProduct` 字段即 board-id。逐个取自 <https://github.com/acidanthera/OpenCorePkg/tree/master/AppleModels/DataBase>。

| board-id | `SystemProductName` | `AppleModelId` | 数据库声明的 `MaximumOSVersion` | 在 25G325 `SupportedBoardIds` 中 |
|---|---|---|---|---|
| `Mac-E1008331FDC96864` | `MacBookPro16,1` | `J152F` | `26.7.1` | 是 |
| `Mac-27AD2F918AE68F61` | `MacPro7,1` | `J160` | `26.7.1` | 是 |
| `Mac-CFF7D910A743CAAF` | `iMac20,1` | `J185` | `26.7.1` | 是 |
| `Mac-AF89B6D9451A490B` | `iMac20,2` | `J185F` | `26.7.1` | 是 |
| `Mac-5F9802EFE386AA28` | `MacBookPro16,2` | `J214K` | `26.7.1` | 是 |
| `Mac-A61BADE1FDAD7B05` | `MacBookPro16,4` | `J215` | `26.7.1` | 是 |
| `Mac-112818653D3AABFC` | **未知** | — | — | 是 |
| `Mac-7BA5B2D9E42DDD94` | `iMacPro1,1` | `J137` | `15.8.1` | **否** |
| `Mac-F60DEB81FF30ACF6` | `MacPro6,1` | — | `12.7.6` | **否** |
| `Mac-0CFF9C7C2B63DF8D` | `MacBookAir9,1` | `J230K` | `15.8.1` | **否** |
| `Mac-E7203C0F68AA0004` | `MacBookPro16,3` | `J223` | `15.8.1` | **否** |

`AppleModelId` 一列与第 1.3 节 MobileAsset 的 `SupportedDeviceModels` 对得上（`J152FAP`、`J160AP`、`J185AP`、`J185FAP`、`J214KAP`、`J215AP`），这是第三条独立印证。

`Mac-112818653D3AABFC` 没有公开的机型映射。它在 payload 里确实有配套资源（`System/Library/Extensions/IOPlatformPluginFamily.kext/Contents/PlugIns/X86PlatformPlugin.kext/Contents/Resources/Mac-112818653D3AABFC.plist`，17,436 字节，`KNOWN`），所以不是打字错误，大概是某个未公开或内部变体。**不要用它**，登记为 I-011。

社区的独立确认：有第三方 patcher 项目把 Tahoe 的原生机型定义为 `iMac20,x` / `MacBookPro16,x` / `MacPro7,1`（转述自 <https://github.com/YBronst/OCLP-Plus/blob/main/CHANGELOG.md>），与上表一致。

### 4.3 两个 board-id 门，决定选哪一个机型

board-id 不只被安装器用来判断"能不能装"，还被两个内核驱动用来决定行为。这两个门直接影响本项目。

#### 门 1：`AppleIntelMCEReporter`

`KNOWN`，`System/Library/Extensions/AppleIntelMCEReporter.kext/Contents/Info.plist`（3,237 字节，`payload.050`）。它在 **System KC** 里：

```text
com.apple.driver.AppleIntelMCEReporter  vm=0x1484b000 uuid=35D5393C-734C-3ACF-8574-DFBFB1775C4B
```

`AppleIntelMCEInterruptController` personality：

```text
IOClass         = AppleIntelMCEInterruptController
IOProviderClass = IOPlatformExpertDevice
IOMatchCategory = AppleIntelMCEInterruptController
IOPropertyMatch = [ {board-id: Mac-F60DEB81FF30ACF6},    ← MacPro6,1
                    {board-id: Mac-7BA5B2D9E42DDD94},    ← iMacPro1,1
                    {board-id: Mac-27AD2F918AE68F61} ]   ← MacPro7,1
```

**只有这三个 board-id 会让 `AppleIntelMCEReporter` 匹配上。** 这就是"用 iMacPro1,1 或 MacPro7,1 SMBIOS 需要 `AppleMCEReporterDisabler.kext`"这条社区常识的二进制依据。`KNOWN` 对于匹配条件；`INFERRED` 对于"不加 disabler 就一定 panic"（panic 的具体触发条件在驱动代码里，未反编译）。

反过来说：**选 `MacBookPro16,x` 或 `iMac20,x` 时不需要 `AppleMCEReporterDisabler`**，因为它们的 board-id 不在这个 `IOPropertyMatch` 列表里，驱动根本不会被实例化。

#### 门 2：`AppleGraphicsDevicePolicy`

这个门对本项目尤其重要，因为我们要自己发布一个显卡服务。

`KNOWN`，`System/Library/Extensions/AppleGraphicsControl.kext/Contents/PlugIns/AppleGraphicsDevicePolicy.kext/Contents/Info.plist`（5,821 字节，`payload.050`）。在 **System KC** 里：

```text
com.apple.driver.AppleGraphicsDevicePolicy  vm=0x13d48000 uuid=CEA4C73B-358B-3E8E-951E-9E39F44D02D6
com.apple.driver.AppleGraphicsControl        vm=0x13d27000 uuid=2123B373-097D-3029-9063-2E6821D16B10
com.apple.AppleGPUWrangler                   （System KC 条目存在）
```

personality 的关键结构：

```text
IOClass         = AppleGraphicsDevicePolicy
IOProviderClass = AppleGraphicsDeviceControl
Default         = { none: "" }
ConfigMap       = { <board-id> : <"Config1"|"Config2"|"Config3"|"Config4"|"none"> }
Config1         = { GFX1: {unload: true} }
Config2         = { GFX0: {EDID:{index:0}, FeatureControl:12, unload:false} }
Config3         = Config2 + { IGPU: {unload: true} }
Config4         = Config3 + { display: {EDID:{index:0}, FeatureControl:12, unload:false} }
```

`ConfigMap` 全文 22 条。与本文第 4.2 节的候选机型相关的部分：

| board-id | 机型 | `ConfigMap` 取值 | 对我们的含义 |
|---|---|---|---|
| `Mac-27AD2F918AE68F61` | MacPro7,1 | **不在 `ConfigMap` 中** → 落到 `Default = {none}` | **无任何图形策略限制** |
| `Mac-E1008331FDC96864` | MacBookPro16,1 | 不在 `ConfigMap` 中 → `none` | 无限制 |
| `Mac-5F9802EFE386AA28` | MacBookPro16,2 | 不在 `ConfigMap` 中 → `none` | 无限制 |
| `Mac-A61BADE1FDAD7B05` | MacBookPro16,4 | 不在 `ConfigMap` 中 → `none` | 无限制 |
| `Mac-CFF7D910A743CAAF` | iMac20,1 | **`Config3`** | 要求存在名为 `GFX0` 的设备并带 EDID，且会 unload `IGPU` |
| `Mac-AF89B6D9451A490B` | iMac20,2 | **`Config3`** | 同上 |
| `Mac-7BA5B2D9E42DDD94` | iMacPro1,1 | `Config4` | 更严，且该机型本来就不受 25G325 支持 |
| `Mac-F60DEB81FF30ACF6` | MacPro6,1 | `Config1` | 不受支持 |

**这解释了社区"换个 SMBIOS 就黑屏"的现象，也给了本项目一条硬约束：不要选 `iMac20,x`。** `Config3` 要求 ACPI 路径上有名为 `GFX0` 的设备并能读出 EDID，而我们的显卡是自己写的、挂在一个自定义 provider 上、第一版未必有 EDID。踩这个门没有任何收益。

`KNOWN` 对于 `ConfigMap` 内容与 `Config3` 的键；`INFERRED` 对于"`Config3` 会导致我们的 device 被 unload"（`unload` 键的消费逻辑在 `AppleGraphicsDevicePolicy` 的代码里，未反编译；本文只论证"选 none 更安全"）。

### 4.4 选型结论

| 候选 | PlatformSupport | AGDP | MCEReporter | 平台语义 | 结论 |
|---|---|---|---|---|---|
| **`MacPro7,1`** | 在 | `none` | **匹配，需 disabler** | 台式、无 iGPU、无电池/背光/光感假设 | **首选** |
| `MacBookPro16,1` | 在 | `none` | 不匹配 | 笔记本，有电池/背光/lid sleep 假设 | 备选 |
| `iMac20,1` / `iMac20,2` | 在 | **`Config3`** | 不匹配 | 一体机，iGPU + dGPU | **不用** |
| `iMacPro1,1` | **不在** | `Config4` | 匹配 | — | **不用** |
| `VMM-x86_64` | 在 | 不在 ConfigMap | 不匹配 | 非真实机型，SMBIOS 其余字段无参考值 | 见下 |

**选 `MacPro7,1`。** 理由按权重排序：

1. AGDP 落到 `none`，我们自己写的 accelerator 与 framebuffer 不受任何 board-id 相关的图形策略干预。这是一个会直接导致"黑屏且无从归因"的坑，优先避开。
2. 台式机语义。本项目要写 `IOFramebuffer` provider（`11-KERNEL-DISPLAY.md`），笔记本 SMBIOS 会把背光、lid、环境光传感器一并带进期望集，多一类噪声。
3. board-id 在 `SupportedBoardIds` 里，安装器不需要绕过。
4. `AppleMCEReporterDisabler.kext` 是 acidanthera 随 VirtualSMC 分发的一个仅含 `Info.plist` 的空 kext，用来占掉 `AppleIntelMCEReporter` 的 bundle id。它的代价是配置里多一行。`KNOWN`：参考配置里它的注入项是 `BundlePath = AppleMCEReporterDisabler.kext`、`ExecutablePath` 为空、`MinKernel = 21.0.0`、注释写明"Fix kernel panic MacPro SMBIOS"（转述自 <https://github.com/kholia/OSX-KVM/blob/master/OpenCore/config.plist>）。

**不选 `VMM-x86_64` 的理由**：它是一个 board-id，不是一个机型。选它意味着 SMBIOS 的 `SystemProductName`、`SmcPlatform`、`FirmwareFeatures` 等字段没有参考值可抄，而 OpenCore 的 `PlatformInfo/Automatic = true` 正是按机型名去查 `AppleModels` 数据库填这些字段的。自己编一组值会引入一批未知。`INFERRED`。

`MacPro7,1` 的 SMBIOS 关键字段（`KNOWN`，来源 <https://github.com/acidanthera/OpenCorePkg/blob/master/AppleModels/DataBase/MacPro/MP71.yaml>，供核对 OpenCore 自动填充结果）：

```text
SystemProductName   MacPro7,1
BoardProduct        Mac-27AD2F918AE68F61
BoardVersion        MacPro7,1
BoardRevision       0x9
ChassisType         0x7 (Tower)
SystemFamily        MacPro
PlatformFeature     0x0
FirmwareFeatures    0xFDAFF066 / Mask 0xFFFFFF7F
MemoryFormFactor    0x9
ProcessorType       0x0F02
SmcGeneration       3
MinimumOSVersion    10.15.1
AppleModelId        J160
```

一条相关注意：OpenCore 文档列出的 macOS NVRAM GUID 里有一个 `5EDDA193-A070-416A-85EB-2A1181F45B18`，注明是 **MacPro7,1 专用的 Apple Hardware Configuration Storage**（转述自 <https://dortania.github.io/docs/release/Configuration.html>）。我们不往这个 GUID 写任何东西，但排查 NVRAM 时会看到它。`KNOWN`。

### 4.5 如果必须用不在清单里的 SMBIOS

研发期可能出于别的原因需要一个不受支持的机型（例如为了对照某个 AMD/Intel 驱动的行为）。这时用 `-no_compat_check` boot-arg 绕过模型兼容性检查。

`INFERRED`，来源是社区实践而非 Apple 文档：OCLP 的讨论里明确建议即使伪造了受支持的 board-id 也加上 `-no_compat_check`，因为某些情况下伪造会被忽略而仍然使用系统自带的 `PlatformSupport.plist`（转述自 <https://github.com/dortania/OpenCore-Legacy-Patcher/issues/6>）；另有记录说明设置该 boot-arg 后系统会忽略 board-id 不在 `PlatformSupport.plist` 中的问题并正常启动（转述自 <https://forums.macrumors.com/threads/2415320>）。

**本项目默认不加 `-no_compat_check`。** 理由：我们选的 `MacPro7,1` 本来就在清单里，加上它只会掩盖"board-id 其实没生效"这类配置错误，让排查变难。只在第 11 节 I-002 的排查流程里临时加。

---

## 5. CPU 配置

### 5.1 不能用 `Penryn`

大量 KVM 上跑 macOS 的教程以 `-cpu Penryn,...` 开头。**对 macOS 26 这是错的。**

`KNOWN`，来源 `OSX-KVM` 的 README 与 `OpenCore-Boot.sh`：README 列出的 CPU 要求是 macOS Sierra 及以上需要 SSE4.1、**macOS Ventura 及以上需要 AVX2**；`OpenCore-Boot.sh` 里 `Penryn` 那一行被注释掉，启用的那一行是 `Skylake-Client` 并带注释"ATTENTION: Enable this line for macOS Sequoia and Tahoe"，脚本顶部另有一句提示把 `Penryn` 换成 `Haswell-noTSX` 用于 Sonoma（转述自 <https://github.com/kholia/OSX-KVM/blob/master/README.md> 与 <https://github.com/kholia/OSX-KVM/blob/master/OpenCore-Boot.sh>）。

`Penryn` 是 Core 2 一代，没有 AVX，更没有 AVX2。第 4.2 节表里 Tahoe 支持的 6 个 Intel 机型分别是 Coffee Lake（MacBookPro16,1/16,4）、Ice Lake（MacBookPro16,2）、Comet Lake（iMac20,x）、Cascade Lake（MacPro7,1），全部有 AVX2。**Apple 没有任何理由在 26 里保留 pre-AVX2 的代码路径。** `INFERRED`，但风险极低。

独立确认：另一个明确支持到 macOS 26 的项目给出的 CPU 型号表是 macOS 10.11 到 macOS 26 用 `Skylake-Client-v4` 或 `Skylake-Server-v4`，macOS 10.4 到 10.10 用 `Nehalem`，并加了"CPU 配置错误会导致启动失败"的警告（转述自 <https://github.com/LongQT-sea/OpenCore-ISO/blob/main/README.md>）。

### 5.2 推荐的 `-cpu` 行

与第 4.4 节选定的 `MacPro7,1` 配对，首选 `Skylake-Server-v4`：

```bash
-cpu Skylake-Server-v4,-hle,-rtm,kvm=on,vendor=GenuineIntel,+invtsc,vmware-cpuid-freq=on,+ssse3,+sse4.2,+popcnt,+avx,+aes,+xsave,+xsaveopt,check
```

备选（若 `Skylake-Server-v4` 在宿主上不可用或引起问题）：

```bash
-cpu Skylake-Client-v4,-hle,-rtm,kvm=on,vendor=GenuineIntel,+invtsc,vmware-cpuid-freq=on,+ssse3,+sse4.2,+popcnt,+avx,+aes,+xsave,+xsaveopt,check
```

逐项理由：

| 片段 | 作用 | 标签 |
|---|---|---|
| `Skylake-Server-v4` | CPUID family/model 落在 Skylake-SP / Cascade Lake（model 85），与 `MacPro7,1` 真机的 Xeon W-3245M 同族。让 `X86PlatformPlugin` 加载 `Mac-27AD2F918AE68F61.plist` 时拿到的 CPUID 与 plist 的预期一致 | `INFERRED` |
| `Skylake-Client-v4`（备选） | 社区实测在 Sequoia/Tahoe 可用的型号 | `KNOWN`（OSX-KVM 注释） |
| `-hle,-rtm` | 关掉 TSX。多数宿主的微码已禁用 TSX，若 CPU 模型声明有而宿主没有，末尾的 `check` 会让 QEMU 拒绝启动 | `KNOWN`（参考配置照此写） |
| `kvm=on` | 暴露 KVM paravirt CPUID 叶 | `INFERRED` |
| `vendor=GenuineIntel` | 把 CPUID leaf 0 的厂商串钉成 GenuineIntel。在 AMD 宿主上必需 | `INFERRED` |
| `+invtsc` | 声明 invariant TSC。macOS 的计时依赖它 | `INFERRED` |
| `vmware-cpuid-freq=on` | 通过 VMware 的 CPUID 叶暴露 TSC 频率，省掉 macOS 读 MSR 去标定 | `INFERRED` |
| `+avx` 等显式特征位 | 参考配置的 `MY_OPTIONS`，照抄 | `KNOWN` |
| `check` | 任一声明的特征宿主不支持就报错退出，而不是静默降级 | `KNOWN` |

**AMD 宿主额外注意**：`KNOWN`，有记录说明在 macOS 13 到 26 上跑 AMD 处理器时，`enforce,+kvm_pv_eoi,+kvm_pv_unhalt` 这组 flag（某些管理平台的默认值）会让 macOS 无法启动，必须用自定义 `-cpu` 参数覆盖；同时 `pcid` 与 `spec-ctrl` 是 Intel 专属特征（转述自 <https://github.com/LongQT-sea/OpenCore-ISO/blob/main/README.md> 的脚注）。

### 5.3 `Kernel/Emulate` 怎么填

```xml
<key>Emulate</key>
<dict>
  <key>Cpuid1Data</key>
  <data></data>
  <key>Cpuid1Mask</key>
  <data></data>
  <key>DummyPowerManagement</key>
  <true/>
  <key>MaxKernel</key>
  <string></string>
  <key>MinKernel</key>
  <string></string>
</dict>
```

**`Cpuid1Data` / `Cpuid1Mask` 留空。** 理由：这两个键的用途是在真机上把一个 macOS 不认识的 CPU 伪装成认识的。在 QEMU 上我们直接用 `-cpu` 选了一个 macOS 认识的型号，没有需要伪装的东西。参考配置同样留空（`KNOWN`，OSX-KVM 的 `config.plist`）。

**什么时候才需要填**：如果决定用 `-cpu host` 把宿主 CPU 直接透传（例如宿主是 Alder Lake 这类 macOS 26 不认识的型号），就需要用 `Cpuid1Data`/`Cpuid1Mask` 把 leaf 1 的 EAX 改成一个受支持的 family/model/stepping。本项目**不走 `-cpu host`**，理由是 Lavapipe 的性能由 vCPU 数而非单核特性决定（`80` 第 1.6 节），而 `-cpu host` 带来的 CPUID 不确定性会污染每一次实验。`INFERRED`。

**`DummyPowerManagement = true`。** 它让 OpenCore 阻止 `X86PlatformPlugin` 一类 CPU 电源管理驱动按真机预期去写 MSR。在 QEMU 上这些 MSR 要么不存在要么语义不同。参考配置设为 `true`（`KNOWN`）。

一条相关的 `Kernel/Quirks`，**在 KVM 上是必需的**：

```xml
<key>ProvideCurrentCpuInfo</key>
<true/>
```

`KNOWN`，OpenCore 官方文档对这个 quirk 的描述分三种 CPU，其中明确写到：**对 KVM 与其它 hypervisor，它提供预先算好的 MSR 0x35 值，解决使用 `-cpu host` 时的 kernel panic**（转述自 <https://dortania.github.io/docs/release/Configuration.html>）。参考配置设为 `true`（`KNOWN`，OSX-KVM `config.plist`）。即使我们不用 `-cpu host`，开着它没有已知副作用，而关着它在换 CPU 模型时会多一类 panic。

关于 `vmx`：**不要向 guest 暴露 VMX。** `00-OVERVIEW` 第 2.2 节明确不要求嵌套虚拟化，而 `UEFI/Quirks/EnableVmx` 默认 `false`（`KNOWN`，Sample.plist）。保持默认。

关于 `avx512`：`Skylake-Server-v4` 带 AVX-512。`INFERRED`：保留它没有已知坏处（真机 `MacPro7,1` 的 Xeon-W 也有），但它会让 Lavapipe 的 LLVM 后端选择 AVX-512 代码路径，而那条路径在 `70` 第 3.4 节的构建里尚未验证。登记为 I-012：如果 Lavapipe 在 AVX-512 下出问题，用 `-avx512f` 一类的减法 flag 关掉，而不是换 CPU 模型。

### 5.4 宿主侧前置条件

```bash
# 两条都必须做，否则 macOS 在读 MSR 时会收到 #GP 并 panic
sudo modprobe kvm
echo 1 | sudo tee /sys/module/kvm/parameters/ignore_msrs

# 持久化（Intel 宿主）
# /etc/modprobe.d/kvm.conf:  options kvm ignore_msrs=1
```

`KNOWN`，`OSX-KVM` 的 README 把 `ignore_msrs=1` 列为 KVM 的必需调整，并给出持久化方式（转述自 <https://github.com/kholia/OSX-KVM/blob/master/README.md>）。同一文件要求 QEMU ≥ 8.2.2。

---

## 6. 完整 config.plist

### 6.1 构造方式：以官方 Sample.plist 为基，施加声明式 diff

**不要手抄一份 1500 行的 plist。** OpenCore 每个版本都会增删键，手抄的副本会在升级时静默过期，而缺键的表现是 OpenCore 直接拒绝启动并在串口上报一行键名。

正确做法是：以**固定版本的 `Docs/Sample.plist`** 为基，用脚本施加本文声明的 diff。这样做有三个好处：键集永远与 OpenCore 版本一致、diff 本身就是可审阅的文档、整个过程在 Windows 上用 `py` 完成。

```python
#!/usr/bin/env python3
"""scripts/make-oc-config.py
以 OpenCorePkg 的 Docs/Sample.plist 为基生成本项目的 config.plist。
用法:  py make-oc-config.py <Sample.plist> <out config.plist>
平台:  Windows / Linux / macOS 均可，只用标准库
"""
import plistlib
import sys

SRC, DST = sys.argv[1], sys.argv[2]
c = plistlib.load(open(SRC, 'rb'))

APPLE_BOOT_GUID = '7C436110-AB2A-4BBB-A880-FE41995C9F82'

# csr-active-config = 0xFEF，小端 4 字节 EF 0F 00 00。见 70 分册第 5.2 节
CSR = (0xFEF).to_bytes(4, 'little')

BOOT_ARGS = ' '.join([
    'amfi_get_out_of_my_way=1',   # 70 第 5.5 节：必需，组件 1/2/3 的前提
    '-v',                          # 详细启动
    'keepsyms=1',                  # 保留内核符号，panic backtrace 可读
    'debug=0xa',                   # DB_PRT|DB_KPRT，见本文 9.4
    'serial=7',                    # OUTPUT|INPUT|SYNCDRAIN，见本文 9.4
    'msgbuf=1048576',              # 1 MiB 内核消息缓冲
])

# ---------------- ACPI ----------------
c['ACPI']['Add'] = [
    {'Comment': 'Fake embedded controller, required since 10.15',
     'Enabled': True, 'Path': 'SSDT-EC.aml'},
    {'Comment': 'USB power properties',
     'Enabled': True, 'Path': 'SSDT-USBX.aml'},
]
c['ACPI']['Delete'] = []
c['ACPI']['Patch'] = []
c['ACPI']['Quirks'] = {k: False for k in c['ACPI']['Quirks']}

# ---------------- Booter ----------------
c['Booter']['MmioWhitelist'] = []
c['Booter']['Patch'] = []
c['Booter']['Quirks'].update({
    'AvoidRuntimeDefrag':      True,   # OVMF 上必需，见 6.3
    'EnableWriteUnprotector':  True,   # 需要 OpenRuntime.efi
    'FixupAppleEfiImages':     True,   # SecureBootModel=Disabled 时严格 PE loader 需要
    'SyncRuntimePermissions':  True,
    # 以下在 OVMF 上明确保持 false，理由见 6.3
    'AllowRelocationBlock':    False,
    'DevirtualiseMmio':        False,
    'DisableSingleUser':       False,
    'DisableVariableWrite':    False,
    'DiscardHibernateMap':     False,
    'EnableSafeModeSlide':     False,
    'ForceBooterSignature':    False,
    'ForceExitBootServices':   False,
    'ProtectMemoryRegions':    False,
    'ProtectSecureBoot':       False,
    'ProtectUefiServices':     False,
    'ProvideCustomSlide':      False,
    'ProvideMaxSlide':         0,
    'RebuildAppleMemoryMap':   False,
    'ResizeAppleGpuBars':      0,
    'SetupVirtualMap':         False,
    'SignalAppleOS':           False,
    'ClearTaskSwitchBit':      False,
})

# ---------------- DeviceProperties ----------------
# 不注入任何显卡/声卡/网卡属性。见 6.4
c['DeviceProperties'] = {'Add': {}, 'Delete': {}}

# ---------------- Kernel ----------------
def kext(bundle, exe, *, min_k='', max_k='', comment='', enabled=True):
    return {'Arch': 'x86_64', 'BundlePath': bundle, 'Comment': comment,
            'Enabled': enabled, 'ExecutablePath': exe,
            'MaxKernel': max_k, 'MinKernel': min_k,
            'PlistPath': 'Contents/Info.plist'}

c['Kernel']['Add'] = [
    kext('Lilu.kext', 'Contents/MacOS/Lilu',
         comment='patch engine; must be first'),
    kext('VirtualSMC.kext', 'Contents/MacOS/VirtualSMC',
         comment='SMC emulation; depends on Lilu'),
    kext('AppleMCEReporterDisabler.kext', '',
         min_k='21.0.0',
         comment='block AppleIntelMCEReporter under MacPro7,1 board-id'),
]
c['Kernel']['Block'] = []
c['Kernel']['Emulate'] = {
    'Cpuid1Data': b'', 'Cpuid1Mask': b'',
    'DummyPowerManagement': True, 'MaxKernel': '', 'MinKernel': '',
}
c['Kernel']['Force'] = []
c['Kernel']['Patch'] = []          # 见 6.5.4，默认空
c['Kernel']['Quirks'].update({
    'DisableLinkeditJettison': True,
    'ProvideCurrentCpuInfo':   True,   # KVM 必需，见 5.3
    'PanicNoKextDump':         False,  # 我们要看 kext dump
    'PowerTimeoutKernelPanic': True,   # 显示栈 setPowerState 超时不要 panic
    'CustomPciSerialDevice':   False,  # 用 ISA COM1，不是 PCI 串口卡
    'ForceSecureBootScheme':   False,  # SecureBootModel=Disabled 时无意义
    'DisableIoMapper':         False,
    'AppleCpuPmCfgLock':       False,
    'AppleXcpmCfgLock':        False,
    'AppleXcpmExtraMsrs':      False,
    'AppleXcpmForceBoost':     False,
    'SetApfsTrimTimeout':      -1,
    'XhciPortLimit':           False,
})
c['Kernel']['Scheme'] = {'CustomKernel': False, 'FuzzyMatch': True,
                         'KernelArch': 'x86_64', 'KernelCache': 'Auto'}

# ---------------- Misc ----------------
c['Misc']['BlessOverride'] = []
c['Misc']['Entries'] = []
c['Misc']['Tools'] = []
c['Misc']['Boot'].update({
    'HibernateMode': 'None',
    'HibernateSkipsPicker': False,
    'HideAuxiliary': False,         # 要能看到 recovery 条目
    'LauncherOption': 'Disabled',
    'PickerAttributes': 17,
    'PickerMode': 'Builtin',        # 不用 OpenCanopy，见 2.5
    'PollAppleHotKeys': True,
    'ShowPicker': True,
    'TakeoffDelay': 0,
    'Timeout': 5,
})
c['Misc']['Debug'].update({
    'AppleDebug':      True,        # boot.efi 的日志
    'ApplePanic':      True,        # panic 落盘到 ESP
    'DisableWatchDog': True,        # 卡住时不要自动重启
    'DisplayDelay':    0,
    'DisplayLevel':    0x80000042,  # ERROR|INFO|WARN
    'LogModules':      '*',
    'SysReport':       False,       # 首次取 ACPI/SMBIOS 快照时临时开
    'Target':          0x4B,        # 见 9.2
})
c['Misc']['Security'].update({
    'AllowSetDefault':     True,
    'ApECID':              0,
    'AuthRestart':         False,
    'BlacklistAppleUpdate': True,
    'DmgLoading':          'Signed',   # 见 6.6.3
    'EnablePassword':      False,
    'ExposeSensitiveData': 0x6,
    'HaltLevel':           0x80000000,
    'ScanPolicy':          0,          # 见 7.3
    'SecureBootModel':     'Disabled', # 见 6.6.2
    'Vault':               'Optional',
})
c['Misc']['Serial'] = {'Init': True, 'Override': False}   # 见 9.2

# ---------------- NVRAM ----------------
c['NVRAM']['Add'] = {
    APPLE_BOOT_GUID: {
        'csr-active-config': CSR,
        'boot-args': BOOT_ARGS,
        'prev-lang:kbd': b'en-US:0',
        'run-efi-updater': 'No',
        'SystemAudioVolume': b'\x46',
    },
}
# Add 的语义是"不存在才写"。必须先 Delete 才能保证每次启动都是配置里的值。
# 见 70 分册第 5.3 节路径 A 的警告。
c['NVRAM']['Delete'] = {
    APPLE_BOOT_GUID: ['csr-active-config', 'boot-args',
                      'prev-lang:kbd', 'run-efi-updater'],
}
c['NVRAM']['LegacyOverwrite'] = False
c['NVRAM']['WriteFlash'] = True

# ---------------- PlatformInfo ----------------
c['PlatformInfo']['Automatic'] = True
c['PlatformInfo']['CustomMemory'] = False
c['PlatformInfo']['UpdateDataHub'] = True
c['PlatformInfo']['UpdateNVRAM'] = True
c['PlatformInfo']['UpdateSMBIOS'] = True
c['PlatformInfo']['UpdateSMBIOSMode'] = 'Create'
c['PlatformInfo']['UseRawUuidEncoding'] = False
c['PlatformInfo']['Generic'].update({
    'AdviseFeatures':      False,
    'MLB':                 'M0000000000000001',   # 占位，见 6.8
    'MaxBIOSVersion':      False,
    'ProcessorType':       0,
    'ROM':                 bytes.fromhex('112233445566'),
    'SpoofVendor':         True,
    'SystemMemoryStatus':  'Auto',
    'SystemProductName':   'MacPro7,1',           # 见 4.4
    'SystemSerialNumber':  'F5KZN00HP7QM',        # 占位，见 6.8
    'SystemUUID':          '00000000-0000-0000-0000-000000000000',
})

# ---------------- UEFI ----------------
c['UEFI']['ConnectDrivers'] = True
c['UEFI']['Unload'] = []
c['UEFI']['APFS'].update({'EnableJumpstart': True, 'GlobalConnect': False,
                          'HideVerbose': False, 'JumpstartHotPlug': False,
                          'MinDate': 0, 'MinVersion': 0})
c['UEFI']['Audio']['AudioSupport'] = False
c['UEFI']['Input'].update({'KeySupport': True, 'KeySupportMode': 'Auto',
                           'PointerSupport': False, 'TimerResolution': 50000})
c['UEFI']['Output'].update({'ProvideConsoleGop': True,
                            'TextRenderer': 'BuiltinGraphics',
                            'ConsoleMode': '', 'Resolution': '',
                            'DirectGopRendering': False,
                            'GopPassThrough': 'Disabled',
                            'UgaPassThrough': False})
c['UEFI']['ProtocolOverrides'] = {k: False for k in c['UEFI']['ProtocolOverrides']}
c['UEFI']['ProtocolOverrides']['FirmwareVolume'] = True
c['UEFI']['Quirks'].update({
    'EnableVectorAcceleration': True,
    'EnableVmx':                False,
    'RequestBootVarRouting':    True,   # 需要 OpenRuntime.efi
    'DisableSecurityPolicy':    False,
    'ForgeUefiSupport':         False,
    'IgnoreInvalidFlexRatio':   False,
    'ReleaseUsbOwnership':      False,
    'ResizeGpuBars':            -1,
    'TscSyncTimeout':           0,
    'UnblockFsConnect':         False,
    'ActivateHpetSupport':      False,
    'ExitBootServicesDelay':    0,
})
c['UEFI']['ReservedMemory'] = []

DRIVERS = [
    ('OpenRuntime.efi',     True,  'required by Booter quirks + NVRAM routing'),
    ('OpenHfsPlus.efi',     True,  'recovery volumes are HFS+'),
    ('ResetNvramEntry.efi', True,  'picker entry to clear NVRAM'),
    ('ToggleSipEntry.efi',  True,  'picker entry to flip csr-active-config'),
    # 仅当固件缺 virtio 支持时才开，见 7.3
    ('VirtioPciDeviceDxe.efi', False, 'virtio PCI transport'),
    ('Virtio10.efi',           False, 'virtio 1.0 device support'),
    ('VirtioBlkDxe.efi',       False, 'virtio-blk block io'),
    ('VirtioSerialDxe.efi',    False, 'virtio-serial'),
]
c['UEFI']['Drivers'] = [
    {'Arguments': '', 'Comment': cm, 'Enabled': en,
     'LoadEarly': False, 'Path': p} for p, en, cm in DRIVERS
]

plistlib.dump(c, open(DST, 'wb'), sort_keys=True)
print('wrote', DST)
```

运行：

```powershell
curl.exe -L -o OpenCore.zip https://github.com/acidanthera/OpenCorePkg/releases/download/<TAG>/OpenCore-<TAG>-DEBUG.zip
tar -xf OpenCore.zip -C oc
py scripts\make-oc-config.py oc\Docs\Sample.plist build\EFI\OC\config.plist
```

**脚本故意只用 `dict.update()` 而不整段替换 Quirks 字典**，这样 OpenCore 新增一个 quirk 时它会以 Sample 的 failsafe 值进入我们的配置，而不是缺键。唯一整段替换的是 `ACPI/Quirks` 与 `UEFI/ProtocolOverrides`，因为那两处我们要的就是"全部关掉"。

### 6.2 `ACPI`

| 键 | 值 | 理由 | 标签 |
|---|---|---|---|
| `Add` | `SSDT-EC.aml`、`SSDT-USBX.aml` | macOS 10.15 起要求存在一个 embedded controller 设备；`USBX` 提供 USB 供电属性 | `KNOWN`，参考配置两项都启用（<https://github.com/kholia/OSX-KVM/blob/master/OpenCore/config.plist>） |
| `Delete` | 空 | OVMF 的 ACPI 表是我们自己这边生成的，没有需要删的厂商表 | `INFERRED` |
| `Patch` | 空 | 同上 | `INFERRED` |
| `Quirks` | 全 `false` | 这些 quirk 针对真机固件的 ACPI 缺陷。OVMF 没有那些缺陷 | `INFERRED`，参考配置同样全关（`KNOWN`） |

两个 `.aml` 不要自己写，用现成的预编译件。`INFERRED`：`OSX-KVM` 仓库的 `OpenCore/EFI/OC/ACPI/` 下有副本；dortania 的指南也提供预编译 SSDT。两处的 `SSDT-EC` 都是"假 EC"版本（给虚机/无 EC 的平台用），不是"EC 重命名"版本。**选错版本的表现是 `AppleACPIEC` 匹配不上，而不是报错**，所以要在首启探针里确认（第 10 节）。

### 6.3 `Booter`

OVMF 不是真机固件，大半 Booter quirk 是为真机固件的缺陷准备的。参考配置在 OVMF 上只开两个（`KNOWN`，OSX-KVM `config.plist`：`AvoidRuntimeDefrag` 与 `EnableWriteUnprotector` 为 `true`，其余 20 个全 `false`）。本文在此基础上多开两个，并说明每一项。

| Quirk | 本项目 | 理由 |
|---|---|---|
| `AvoidRuntimeDefrag` | **`true`** | `KNOWN`，参考配置开。这是 AptioMemoryFix 系列里最基础的一项，OpenCore 文档把它列在"要得到 AptioMemoryFix 等价行为"的集合里（转述自 <https://dortania.github.io/docs/release/Configuration.html>） |
| `EnableWriteUnprotector` | **`true`** | `KNOWN`，参考配置开。它通过在 UEFI runtime services 执行期清掉 CR0 的 WP 位来绕过 W^X。文档提示若固件支持 memory attributes table（MAT）则应改用 `RebuildAppleMemoryMap`，并说明可从日志里的 `OCABC: MAT support is 1/0` 判断（转述自同一来源）。**OVMF 的 MAT 支持情况要看串口日志那一行**，见 I-004 |
| `SyncRuntimePermissions` | **`true`** | `INFERRED`。它修正 runtime 区域权限，与 `EnableWriteUnprotector` 配套。参考配置关着；本文开它的理由是 OVMF 的内存图会随版本变化，而这一项的副作用面很小 |
| `FixupAppleEfiImages` | **`true`** | `KNOWN` 的依据，`INFERRED` 的必要性（**I-023**）。文档明确："在具备现代严格 PE loader 的系统上，当 `SecureBootModel` 设为 `Disabled` 时，所有较新的 macOS 都需要这个 quirk"，并指出会强制这些规则的 loader 包括 OpenDuet 当前版本与**由 audk 编译的 OVMF**（转述自同一来源）。我们正是 `SecureBootModel = Disabled` + OVMF，所以开。文档的 Note 3 说它与 UEFI Secure Boot 不兼容，而我们禁用 Secure Boot，不冲突 |
| `RebuildAppleMemoryMap` | `false` | 与 `EnableWriteUnprotector` 二者择一。先按参考配置走，若日志显示 MAT 支持为 1 则换过来（I-004） |
| `SetupVirtualMap` | `false` | `KNOWN`，参考配置关。针对特定真机固件的 SetVirtualAddresses 行为缺陷 |
| `ProvideCustomSlide` / `ProvideMaxSlide` / `EnableSafeModeSlide` | `false` / `0` / `false` | KASLR slide 相关，针对真机固件保留内存区域导致的 slide 失败。OVMF 无此问题 |
| `DevirtualiseMmio` | `false` | 真机为省 runtime 内存而设。OVMF 的 MMIO 区域不大 |
| `ProtectMemoryRegions` | `false` | 文档说明这个 quirk 针对把 CSM 区域标成 boot services、或把 MMIO 标成 reserved 的错误固件，并明确"通常只有非常老的固件才需要"（转述自同一来源） |
| `ForceExitBootServices` | `false` | 文档明确"不要在不完全理解后果时使用" |
| `DisableVariableWrite` | `false` | 开了会让 macOS 无法写 NVRAM，而我们需要 `nvram` 命令在 guest 内可用（`70` 第 5.3 节路径 B 的排查手段） |
| `DisableSingleUser` | `false` | 研发期要保留 `-s` |
| `AllowRelocationBlock` / `DiscardHibernateMap` / `ForceBooterSignature` / `ProtectSecureBoot` / `ProtectUefiServices` / `SignalAppleOS` / `ResizeAppleGpuBars` / `ClearTaskSwitchBit` | 全关 | 分别针对休眠、Mac EFI 签名校验、真机 Secure Boot、特定固件的服务指针被改、GPU BAR 尺寸、32 位引导。与本场景无关 |

`MmioWhitelist` 与 `Patch` 都置空。参考配置里的两条 `MmioWhitelist` 条目是 Haswell 与通用 PCI root 的，且都 `Enabled = false`。

### 6.4 `DeviceProperties`

**全空。**

```xml
<key>DeviceProperties</key>
<dict>
  <key>Add</key>
  <dict/>
  <key>Delete</key>
  <dict/>
</dict>
```

参考配置里有 7 个条目：`PciRoot(0x0)/Pci(0x2,0x0)` 的 `AAPL,ig-platform-id`（空值）、`Pci(0x1b,0x0)` 的 `layout-id`（声卡）、以及 5 个 `built-in` 标记（`KNOWN`，OSX-KVM `config.plist`）。本项目逐条排除：

| 参考配置里的条目 | 本项目 | 理由 |
|---|---|---|
| `AAPL,ig-platform-id` | **不注入** | 这是 Intel iGPU framebuffer 选择用的。我们没有 iGPU，而且**我们自己要写显卡驱动**。注入它会让 `AppleIntel*GraphicsFramebuffer` 去尝试匹配，多出一个与我们竞争的显示 provider |
| `layout-id` | 不注入 | 声卡布局。`UEFI/Audio/AudioSupport = false`，不需要声音 |
| `built-in` 标记 | 不注入 | 用来让 macOS 把某个 PCI 网卡当内置网卡（影响 iServices 与 `en0` 编号）。研发期不需要，而且 QEMU 的 PCI 拓扑与参考配置不同，照抄路径一定是错的 |

**一条纪律：在第 11 节 I-005 关闭之前，`DeviceProperties` 保持全空。** 本项目的显示栈是自己写的，任何向 PCI 设备注入图形相关属性的动作都可能把 Apple 自带的驱动引进匹配竞争，而那正是"WindowServer 选错 device"这一类最难归因的故障源。等到 `11-KERNEL-DISPLAY.md` 确定了我们 provider 的 ACPI/PCI 路径之后，再决定要不要往那个路径上注入属性。

### 6.5 `Kernel`

#### 6.5.1 `Add`：必需 kext 的最小集与顺序

```xml
<key>Add</key>
<array>
  <dict>
    <key>Arch</key>            <string>x86_64</string>
    <key>BundlePath</key>      <string>Lilu.kext</string>
    <key>Comment</key>         <string>patch engine; must be first</string>
    <key>Enabled</key>         <true/>
    <key>ExecutablePath</key>  <string>Contents/MacOS/Lilu</string>
    <key>MaxKernel</key>       <string></string>
    <key>MinKernel</key>       <string></string>
    <key>PlistPath</key>       <string>Contents/Info.plist</string>
  </dict>
  <dict>
    <key>Arch</key>            <string>x86_64</string>
    <key>BundlePath</key>      <string>VirtualSMC.kext</string>
    <key>Comment</key>         <string>SMC emulation; depends on Lilu</string>
    <key>Enabled</key>         <true/>
    <key>ExecutablePath</key>  <string>Contents/MacOS/VirtualSMC</string>
    <key>MaxKernel</key>       <string></string>
    <key>MinKernel</key>       <string></string>
    <key>PlistPath</key>       <string>Contents/Info.plist</string>
  </dict>
  <dict>
    <key>Arch</key>            <string>x86_64</string>
    <key>BundlePath</key>      <string>AppleMCEReporterDisabler.kext</string>
    <key>Comment</key>         <string>block AppleIntelMCEReporter under MacPro7,1 board-id</string>
    <key>Enabled</key>         <true/>
    <key>ExecutablePath</key>  <string></string>
    <key>MaxKernel</key>       <string></string>
    <key>MinKernel</key>       <string>21.0.0</string>
    <key>PlistPath</key>       <string>Contents/Info.plist</string>
  </dict>
</array>
```

**三个，就这三个。** 顺序有意义：OpenCore 按数组顺序注入，依赖必须排在使用者之前。`Lilu` 是 patch engine，`VirtualSMC` 依赖它，所以 `Lilu` 必须第一。

逐项说明，以及**为什么参考配置里的另外五个一个都不要**：

| kext | 本项目 | 理由 |
|---|---|---|
| **`Lilu.kext`** | 要 | `VirtualSMC` 的依赖。单独它什么也不做 |
| **`VirtualSMC.kext`** | 要，但**与 QEMU 的 `isa-applesmc` 二选一**，见下 |
| **`AppleMCEReporterDisabler.kext`** | 要 | 第 4.3 节门 1：`MacPro7,1` 的 board-id 在 `AppleIntelMCEReporter` 的 `IOPropertyMatch` 里。`ExecutablePath` 为空是对的，它是一个只有 `Info.plist` 的占位 kext |
| `WhateverGreen.kext` | **排除**，见 6.10 | 本项目自己写显卡驱动 |
| `VoodooPS2Controller.kext`（+ `VoodooPS2Keyboard`） | 排除 | 它给 PS/2 键鼠用。我们用 `qemu-xhci` + `usb-kbd`/`usb-tablet`（或 virtio-input），走系统自带的 `IOUSBHostHIDDevice` / `AppleVirtIOInput`。第 3.2 节已确证 `AppleVirtIOInput*` 三个 personality 在 Boot KC 的 `AppleVirtIO` 里 |
| `USBToolBox.kext` + `UTBMap.kext` | 排除 | 它们解决真机的 USB 端口映射与 15 端口上限。QEMU 的 xhci 端口数由我们自己决定，不需要映射表。`Kernel/Quirks/XhciPortLimit` 同样保持 `false` |
| `AppleALC.kext` | 排除 | 声卡。不需要 |
| `BlueToolFixup` / `Brcm*` | 排除 | 蓝牙。不需要 |
| `CryptexFixup.kext` | 排除 | `INFERRED`。它针对 OCLP 场景下的 cryptex 问题。我们用的是受支持的 board-id，不打根卷补丁。如果 25G325 的 cryptex 挂载在虚机上出问题，再评估（I-013） |
| `AGPMInjector` / `USBPorts` | 排除 | 真机专用注入 |

**`VirtualSMC` 还是 `isa-applesmc`**，这是一个必须明确做出的选择：

`KNOWN`：QEMU 自带 AppleSMC 设备模型，参考配置用的就是它：

```bash
-device isa-applesmc,osk="ourhardworkbythesewordsguardedpleasedontsteal(c)AppleComputerInc"
```

（转述自 <https://github.com/kholia/OSX-KVM/blob/master/OpenCore-Boot.sh>）同一份 `config.plist` 里**同时**注入了 `VirtualSMC.kext`。两个并存是参考配置的现状。

本项目的决定：**两个都保留**，但把 `isa-applesmc` 当主、`VirtualSMC` 当兜底。理由：

1. `isa-applesmc` 由 QEMU 实现，在 host 侧，不占 guest 的 kext 槽位，也不参与 aux collection 重建（`70` 第 4 节）。研发期每改一次 kext 就要重启一次，少一个注入 kext 就少一类干扰。
2. `VirtualSMC` 另有一项我们可能用到的能力：OpenCore 的 `Misc/Security/AuthRestart` 需要它。研发期不用 FileVault，所以这项能力暂时没用，`AuthRestart` 保持 `false`。
3. 两者并存的风险是 `VirtualSMC` 与真实的 `isa-applesmc` 竞争匹配。`INFERRED`，参考配置长期这样用没有报告冲突。**如果首启时 `ioreg -c AppleSMC` 出现两个服务或 `VirtualSMC` 的 `start` 失败，就把 `VirtualSMC` 的 `Enabled` 改成 `false`。** 登记为 I-006。

#### 6.5.2 `Emulate`

见第 5.3 节。

#### 6.5.3 `Quirks`

| Quirk | 本项目 | 理由 |
|---|---|---|
| `ProvideCurrentCpuInfo` | **`true`** | **KVM 必需。** 见 5.3，官方文档明确它为 KVM 提供预算的 MSR 0x35 值 |
| `DisableLinkeditJettison` | **`true`** | `KNOWN`，官方文档：让 `Lilu.kext` 等在 Big Sur 及之后不依赖 `keepsyms=1` 就能达到最佳性能（转述自 <https://dortania.github.io/docs/release/Configuration.html>）。我们同时也设了 `keepsyms=1`，两者不冲突 |
| `PowerTimeoutKernelPanic` | **`true`** | `KNOWN` 的依据：官方文档说明 macOS 10.15 起 Apple 驱动的 `setPowerState` 超时会直接 panic，在配置不当的硬件上会出问题，并说明 debug 内核可用 `setpowerstate_panic=0` 达到等价效果（转述自同一来源）。**本项目正在写一个显示驱动，`setPowerState` 的实现一开始必然不完善**，让它超时变成日志而不是 panic，能把一类 panic 降级成可诊断的失败 |
| `PanicNoKextDump` | **`false`** | 官方描述是"阻止内核在 panic log 里打印 kext dump"。我们恰恰需要那份 dump 来确认自己的 kext 的加载地址 |
| `CustomPciSerialDevice` | `false` | 官方 FAQ 说明：当安装了 PCI 串口卡时可以启用这个 quirk，以便 macOS 正确识别与设置串口（转述自同一来源）。我们用 ISA COM1（`0x3F8`），不是 PCI 卡。若改用 `pci-serial` 则要开，见 9.6 |
| `ForceSecureBootScheme` | `false` | 官方说明：在虚机上使用**非 `x86legacy`** 的 `SecureBootModel` 时需要此项。我们用 `Disabled`，不需要。（参考配置设为 `true`，那是冗余而非必需） |
| `DisableIoMapper` | `false` | 针对真机 VT-d / DMAR 表问题。OVMF 默认不暴露 DMAR |
| `AppleCpuPmCfgLock` / `AppleXcpm*` | 全 `false` | 真机 MSR 锁定与 XCPM 相关。配合 `DummyPowerManagement = true` 使用 |
| `SetApfsTrimTimeout` | `-1`（默认） | 官方说明它设置 APFS 在 SSD 上的 trim 超时。QEMU 的盘的 trim 行为由 host 决定，先用默认 |
| `ExternalDiskIcons` | `false` | 官方明确"应尽可能避免" |
| `XhciPortLimit` | `false` | 见 6.5.1，我们控制端口数 |
| `LapicKernelPanic` / `LegacyCommpage` / `IncreasePciBarSize` / `ExtendBTFeatureFlags` / `ForceAquantiaEthernet` / `DisableRtcChecksum` / `CustomSMBIOSGuid` / `ThirdPartyDrives` / `DisableIoMapperMapping` | 全 `false` | 与本场景无关 |

#### 6.5.4 `Patch`：默认空，两组按需启用

```xml
<key>Patch</key>
<array/>
```

参考配置里默认启用一条（`KNOWN`，OSX-KVM `config.plist`）：

```text
Identifier  com.apple.iokit.IOAHCIBlockStorage
Comment     Enable TRIM/discard on QEMU SATA SSD - 10.7+
MinKernel   11.0.0
Find        00 "APPLE SSD" 00        （11 字节）
Replace     00 00 00 00 00 00 00 00 00 00 00
```

它把 `IOAHCIBlockStorage` 里"只给 Apple SSD 开 TRIM"的字符串比较打掉，从而在 QEMU 的 AHCI 盘上启用 TRIM。

**本项目默认不启用它。** 理由：第 7 节选的主路径不是 AHCI；而且 `80` 第 2.4.2 节的实验回路用 qcow2 overlay，每次实验结束就丢，TRIM 没有价值。如果最终定在 AHCI 上且长期保留 golden 盘，再打开它。

第二组是**串口相关的内核补丁**，见第 9.5 节。它们同样默认关闭，只在"内核在串口初始化之前就死了"这一种情况下启用。

#### 6.5.5 `Block` 与 `Force`

两者都置空。

参考配置里有两条 `Block`（都 `Enabled = false`）：`com.apple.driver.AppleTyMCEDriver`（Strategy `Disable`）与 `com.apple.iokit.IOSkywalkFamily`（Strategy `Exclude`，`MinKernel 23.0.0`）。`INFERRED`：前者是另一种 MCE 驱动的处理方式，我们用 `AppleMCEReporterDisabler` 走的是占 bundle id 那条路；后者与网络栈有关，默认关着就不动。

**一条可能会用到的 `Block`**：如果第 7 节最终确定用 NVMe 或 AHCI，而 `AppleVirtIO` 又在抢某个设备，可以用 `Block` 把 `com.apple.driver.AppleVirtIO` 排除掉。`INFERRED`，目前没有证据表明需要，不预先加。

### 6.6 `Misc`

#### 6.6.1 `Boot`

| 键 | 值 | 理由 |
|---|---|---|
| `ShowPicker` | `true` | 研发期要能手动选 recovery / 安装介质 |
| `Timeout` | `5` | 无人值守时 5 秒后自动进默认项。`0` 表示无限等待，那会让 `80` 的自动化卡死 |
| `PickerMode` | `Builtin` | 不用 OpenCanopy。`KNOWN`，OpenCore 调试文档建议排错时不用 OpenCanopy，必须用的话要确保那个 `.efi` 也是 DEBUG 版，否则几乎没有调试信息（转述自 <https://dortania.github.io/OpenCore-Install-Guide/troubleshooting/debug>） |
| `HideAuxiliary` | `false` | 要能看到 recovery 与工具条目。参考配置设 `true`，那是日用配置 |
| `HibernateMode` | `None` | `80` 第 2.4.2 节要求 `pmset -a sleep 0`，休眠一律不要 |
| `PollAppleHotKeys` | `true` | 允许在 picker 里按组合键（例如进 verbose） |
| `LauncherOption` | `Disabled` | 不往固件 NVRAM 里注册 boot option。在 Vultr 上 NVRAM 是否持久未知（`80` 的 H-002），注册了反而制造不确定性 |
| `TakeoffDelay` | `0` | 不延迟 |

#### 6.6.2 `Security`

| 键 | 值 | 理由 |
|---|---|---|
| **`SecureBootModel`** | **`Disabled`** | **必需。** 官方文档说明自 macOS 12 起 `SecureBootModel` 必须与 SMBIOS 的 Mac 型号匹配，且启用 Apple Secure Boot 后"所有未签名的 kext 以及若干已签名的 kext 都无法安装"（转述自 <https://dortania.github.io/docs/release/Configuration.html>）。本项目的全部交付物是 ad-hoc 签名的 kext 与 bundle（`70` 第 3.3、5.4 节），Apple Secure Boot 与之直接冲突。**这一项设错，组件 2 和 3 永远装不上。** 顺带一提，`MacPro7,1` 对应的合法取值是 `j160`，但我们不用它 |
| `ScanPolicy` | `0` | 见 7.3 |
| `Vault` | `Optional` | 研发期不做 vault。`Secure`（Sample 的默认）会要求签名的 `vault.sig`，每次改配置都要重算 |
| `DmgLoading` | `Signed` | 见 6.6.3 |
| `ExposeSensitiveData` | `0x6` | `0x2` 把 OpenCore 版本写进 UEFI 变量、`0x4` 在 picker 标题里显示版本。前者让首启探针能读到引导器版本（第 10 节），这对"guest 上跑的到底是哪个镜像"这个问题有直接价值。`KNOWN`，官方给出的读取命令是 `nvram 4D1FDA02-38C7-4A6A-9CC6-4BCCA8B30102:opencore-version` |
| `HaltLevel` | `0x80000000` | `DEBUG_ERROR` 级消息停住启动。调试期这是对的：宁可停在报错处让串口留下现场，也不要带着错误继续走 |
| `AllowSetDefault` | `true` | 允许 Ctrl+Enter 设默认项 |
| `BlacklistAppleUpdate` | `true` | 忽略试图更新 Apple 外设固件的启动项。虚机里没有要更新的固件 |
| `ApECID` | `0` | 不用个性化 Secure Boot |
| `AuthRestart` | `false` | 不用 FileVault |

#### 6.6.3 `DmgLoading` 与缺失的 chunklist

`DmgLoading = Signed` 是官方默认，含义是只加载 Apple 签名的 DMG。官方对三个取值的说明：`Disabled` 下 DMG 加载会失败，但由于通常存在兼容 Apple Secure Boot 的 `boot.efi`，recovery 多数情况下仍能起来，**手工下载放进 `com.apple.recovery.boot` 的 DMG 则不会加载**；`Signed` 只加载 Apple 签名的镜像；`Any` 把任意 DMG 当普通文件系统挂载，官方强烈不建议并指出在 Apple Secure Boot 生效时会导致启动失败（转述自 <https://dortania.github.io/docs/release/Configuration.html>）。

我们手上的 BaseSystem **没有 chunklist**（第 1.6 节）。因此：

- **第 2.4 节的路 A（把 BaseSystem 当一块盘挂上）完全不经过 DMG 加载**，`DmgLoading` 的取值对它没有影响。这是选路 A 的决定性理由。
- 只有退到路 B（`com.apple.recovery.boot` 布局）时才需要把它改成 `Any`，并接受官方的警告。

所以配置里保持 `Signed`，并在第 11 节 I-007 记下"若必须走路 B 则改 `Any`"。

#### 6.6.4 `Debug` 与 `Serial`

见第 9 节。这里只给值：

```xml
<key>Debug</key>
<dict>
  <key>AppleDebug</key>      <true/>
  <key>ApplePanic</key>      <true/>
  <key>DisableWatchDog</key> <true/>
  <key>DisplayDelay</key>    <integer>0</integer>
  <key>DisplayLevel</key>    <integer>2147483714</integer>
  <key>LogModules</key>      <string>*</string>
  <key>SysReport</key>       <false/>
  <key>Target</key>          <integer>75</integer>
</dict>
<key>Serial</key>
<dict>
  <key>Init</key>     <true/>
  <key>Override</key> <false/>
</dict>
```

`2147483714` = `0x80000042`。`75` = `0x4B`。推导见 9.2。

### 6.7 `NVRAM`

```xml
<key>NVRAM</key>
<dict>
  <key>Add</key>
  <dict>
    <key>7C436110-AB2A-4BBB-A880-FE41995C9F82</key>
    <dict>
      <!-- csr-active-config = 0xFEF。位域含义与 0xFEF 的推导见 70 分册 5.1/5.2 -->
      <key>csr-active-config</key>
      <data>7w8AAA==</data>

      <key>boot-args</key>
      <string>amfi_get_out_of_my_way=1 -v keepsyms=1 debug=0xa serial=7 msgbuf=1048576</string>

      <key>prev-lang:kbd</key>
      <data>ZW4tVVM6MA==</data>

      <key>run-efi-updater</key>
      <string>No</string>

      <key>SystemAudioVolume</key>
      <data>Rg==</data>
    </dict>
  </dict>

  <key>Delete</key>
  <dict>
    <!-- Add 的语义是"读一下，不存在才写"。不 Delete 就无法保证每次启动都是配置里的值。
         见 70 分册第 5.3 节路径 A 的警告。-->
    <key>7C436110-AB2A-4BBB-A880-FE41995C9F82</key>
    <array>
      <string>csr-active-config</string>
      <string>boot-args</string>
      <string>prev-lang:kbd</string>
      <string>run-efi-updater</string>
    </array>
  </dict>

  <key>LegacyOverwrite</key> <false/>
  <key>WriteFlash</key>      <true/>
</dict>
```

**`Delete` 里必须同时列 `csr-active-config` 与 `boot-args`。** 这是 `70` 第 5.3 节路径 A 的硬性要求，本文照办并再强调一次原因：`Add` 不覆盖已存在的变量，所以一旦 NVRAM 里留了旧值，改配置不生效，而症状是"明明写了 `0xFEF`，`csrutil status` 还说 enabled"。

**注意参考配置在这一点上是不对的**：`KNOWN`，OSX-KVM 的 `config.plist` 的 `Delete` 段只列了 `boot-args` 与 `ForceDisplayRotationInEFI`，**没有列 `csr-active-config`**，而它的 `Add` 里 `csr-active-config` 是 `00000000`（SIP 开启）。那份配置通过 picker 里的 `ToggleSipEntry.efi` 条目来改 SIP，是另一套工作方式。我们走镜像固化那一套，所以必须 `Delete`。

`70` 第 5.3 节还记录了一条已知副作用：把 `csr-active-config` 放进 `config.plist` 会让恢复环境里的 `csrutil` 改不动实际生效值。对本项目是好事，它保证配置的唯一来源是镜像。

`WriteFlash = true` 把变量真正写进固件 NVRAM。在 L1 上这会写进 `OVMF_VARS.fd`，所以**每台实验机要有自己的 `OVMF_VARS.fd` 副本**，不要让多个并发实验共用一份（第 8.2 节的脚本据此为每次实验拷一份）。在 L2 上它是否生效取决于实例 NVRAM 的持久性（`80` 的 H-002）；即使不持久，OpenCore 每次启动都会重新注入，guest 内看到的值仍正确。

`boot-args` 逐项见第 9.4 节。注意**本文对 `70` 第 5.5 节的两处修正**：`debug` 由 `0x100` 改为 `0xa`，`serial` 由 `3` 改为 `7`，依据是 XNU 源码里的位定义，详见 9.4。

### 6.8 `PlatformInfo`

```xml
<key>PlatformInfo</key>
<dict>
  <key>Automatic</key>           <true/>
  <key>CustomMemory</key>        <false/>
  <key>UpdateDataHub</key>       <true/>
  <key>UpdateNVRAM</key>         <true/>
  <key>UpdateSMBIOS</key>        <true/>
  <key>UpdateSMBIOSMode</key>    <string>Create</string>
  <key>UseRawUuidEncoding</key>  <false/>
  <key>Generic</key>
  <dict>
    <key>AdviseFeatures</key>      <false/>
    <key>MLB</key>                 <string>M0000000000000001</string>
    <key>MaxBIOSVersion</key>      <false/>
    <key>ProcessorType</key>       <integer>0</integer>
    <key>ROM</key>                 <data>ESIzRFVm</data>
    <key>SpoofVendor</key>         <true/>
    <key>SystemMemoryStatus</key>  <string>Auto</string>
    <key>SystemProductName</key>   <string>MacPro7,1</string>
    <key>SystemSerialNumber</key>  <string>F5KZN00HP7QM</string>
    <key>SystemUUID</key>          <string>00000000-0000-0000-0000-000000000000</string>
  </dict>
</dict>
```

| 键 | 值 | 理由 |
|---|---|---|
| `Automatic` | `true` | 让 OpenCore 按 `SystemProductName` 去 `AppleModels` 数据库查全部 SMBIOS 字段。这正是第 4.4 节列出那张字段表的来源 |
| `SystemProductName` | **`MacPro7,1`** | 第 4.4 节的结论。**这一个字符串决定了 board-id，进而决定第 4.3 节两个门的行为** |
| `UpdateSMBIOSMode` | `Create` | 新建 SMBIOS 表而不是改原表。OVMF 的原表是 QEMU 生成的通用表，没有需要保留的内容 |
| `SpoofVendor` | `true` | 把厂商串写成 `Acidanthera` 之类的非 Apple 值，避免某些软件把虚机当真 Mac。研发期无害 |
| `SystemSerialNumber` / `MLB` / `SystemUUID` / `ROM` | **占位值** | 研发期**故意不用真实或生成的序列号**。本项目不需要 iServices（iCloud / iMessage / App Store），而一个能通过校验的序列号组合会把 guest 关联到 Apple 账户体系，带来不必要的外部交互。`F5KZN00HP7QM` 是 OpenCore 数据库里 `MacPro7,1` 条目的示例序列号（`KNOWN`，<https://github.com/acidanthera/OpenCorePkg/blob/master/AppleModels/DataBase/MacPro/MP71.yaml> 的 `SystemSerialNumber`），不是一个真机序列号 |
| `ProcessorType` | `0` | 让 OpenCore 自动推导。手填会与 `-cpu` 不一致 |
| `AdviseFeatures` | `false` | 它改 `FirmwareFeatures`，针对真机 Windows 双启动场景 |
| `CustomMemory` | `false` | 不伪造内存条拓扑。"关于本机"里内存显示为未知，不影响任何功能 |

**一条纪律：序列号占位值不要改成"看起来真"的值。** 如果以后需要 iServices，那是分发阶段的事，单独处理（`00-OVERVIEW` 第 2.4 节末句）。

### 6.9 `UEFI`

#### 6.9.1 `Drivers`

| 驱动 | 启用 | 理由 |
|---|---|---|
| `OpenRuntime.efi` | **是** | **必需。** `Booter/Quirks/EnableWriteUnprotector` 需要它实现的 `OC_FIRMWARE_RUNTIME` 协议（`KNOWN`，官方文档在 `EnableWriteUnprotector` 的描述里明确这一点）；`UEFI/Quirks/RequestBootVarRouting` 也需要单独的驱动（同一来源） |
| `OpenHfsPlus.efi` | **是** | **必需。** 第 2.4 节路 B 的官方说明：recovery 卷都是 HFS+，缺 HFS+ 驱动是在线 recovery 加载失败的常见原因。路 A 同样需要它来读 BaseSystem 卷 |
| `ResetNvramEntry.efi` | 是 | 在 picker 里给一个"清 NVRAM"条目。NVRAM 写坏时这是唯一的自救手段，而 Vultr 上没有串口也没有键盘以外的通道 |
| `ToggleSipEntry.efi` | 是 | 在 picker 里翻 SIP。**不是我们改 SIP 的手段**（那是 `NVRAM/Add` + `Delete`），它的价值是"排查时快速对照 SIP 开/关的行为差异" |
| `VirtioPciDeviceDxe.efi` / `Virtio10.efi` / `VirtioBlkDxe.efi` / `VirtioSerialDxe.efi` | **否**（先关） | `KNOWN`：这四个驱动确实随 OpenCore 分发，在 `Docs/Sample.plist` 的 `UEFI/Drivers` 数组里，默认 `Enabled = false`（转述自 <https://github.com/acidanthera/OpenCorePkg/blob/master/Docs/Sample.plist>）。OVMF 自带 virtio 驱动，所以 L1 上不需要。**它们的价值在 L2**：如果 Vultr 的固件不带 virtio-blk 支持，开这几个就能让 OpenCore 自己读到启动盘。见 7.3 |
| `OpenCanopy.efi` | 否 | 见 6.6.1 |
| `AudioDxe.efi` | 否 | 不要声音 |
| `OpenShell.efi` | 否（但**留在 `Tools` 目录里**） | 官方 FAQ 提到 OpenCore menu 不出现时，用随包的 UEFI Shell 可以看早期调试消息（转述自 <https://dortania.github.io/docs/release/Configuration.html>）。文件留着，`Misc/Tools` 里不启用，需要时改一个布尔 |

#### 6.9.2 其余子节

| 子节 / 键 | 值 | 理由 |
|---|---|---|
| `APFS/EnableJumpstart` | `true` | 从容器里加载 `apfs.efi`，否则 OpenCore 看不到 APFS 卷。**这是能不能启动已装系统的前提** |
| `APFS/MinDate` / `MinVersion` | `0` / `0` | `0` 的含义是只允许加载不受已知漏洞影响的新版本驱动。官方在 UEFI Secure Boot 一节要求把这两项设为 `0`（转述自同一来源）。研发期也用 `0`，因为我们的 APFS 驱动来自 25G325 本身，必然满足 |
| `APFS/HideVerbose` | **`false`** | 参考配置设 `true`。我们要让 `apfs.efi` 的 verbose 输出进串口，这是"卷有没有被认出来"的直接证据 |
| `ConnectDrivers` | `true` | 必需 |
| `Input/KeySupport` | `true`，`KeySupportMode = Auto` | picker 要能响应键盘 |
| `Input/PointerSupport` | `false` | `PickerMode = Builtin` 不用鼠标 |
| `Output/ProvideConsoleGop` | `true` | 必需。官方把它列在 AptioMemoryFix 等价集合里 |
| `Output/TextRenderer` | `BuiltinGraphics` | OpenCore 自己画字，不依赖固件的文本模式 |
| `Output/Resolution` / `ConsoleMode` | 空 | 跟随固件。`80` 第 2.3 节的 `ScreenIO` 要知道帧缓冲尺寸，固定分辨率反而要在两处维护 |
| `Quirks/EnableVectorAcceleration` | `true` | 加速 OpenCore 自己的哈希运算，缩短启动时间 |
| `Quirks/RequestBootVarRouting` | `true` | 官方强烈建议，把 `Boot####` 变量隔进 OpenCore 的命名空间，避免固件删掉 macOS 建的启动项 |
| `Quirks/EnableVmx` | `false` | `00-OVERVIEW` 第 2.2 节不要求嵌套虚拟化 |
| `Quirks/UnblockFsConnect` / `ForgeUefiSupport` / `ReloadOptionRoms` / `ReleaseUsbOwnership` / `ActivateHpetSupport` / `IgnoreInvalidFlexRatio` / `DisableSecurityPolicy` | 全 `false` | 针对特定真机固件缺陷 |
| `ProtocolOverrides` | 全 `false`，仅 `FirmwareVolume = true` | 参考配置同此。`FirmwareVolume` 覆盖让 OpenCore 提供自己的 cursor/文本资源 |
| `ReservedMemory` | 空 | 没有需要保留的真机缺陷区域 |

### 6.10 为什么必须排除 WhateverGreen

**本项目自己写显卡驱动（`00-OVERVIEW` 第 5 节组件 2、3），所以任何显卡补丁 kext 都必须排除。** 参考配置注入 `WhateverGreen.kext`（`MinKernel 10.0.0`，`Enabled = true`），本项目**显式关闭**。

排除理由，三条，按严重度：

1. **WhateverGreen 的本职是在运行期改写别的显卡驱动与 framebuffer 的行为**：patch connector、改 framebuffer 属性、注入 `AAPL,ig-platform-id`、处理 board-id 相关的 AGDP 行为（例如社区常用的 `agdpmod=pikera` 就是它的 boot-arg）。它的作用对象是 Apple 的 AMD/Intel/NVIDIA 驱动。本项目的显示 provider 不是那三个里的任何一个，**WhateverGreen 对它的任何动作都是未定义行为**。
2. **它会参与 AGDP 这一侧的决策。** 第 4.3 节门 2 已经通过选 `MacPro7,1` 把 AGDP 置于 `none`。再叠一个会去改 AGDP 行为的 kext，等于把一个已经确定的变量变回不确定。
3. **归因成本。** `80` 第 5.3 节指出"一张黑图无法区分没渲染与捕获坏了"。如果链路里还有一个会改写显示栈的第三方 kext，就变成三种可能而不是两种。研发期的每一个可选件都要为"出问题时能不能排除它"付费。

**排除的副作用：启动期可能没有显示输出。**

真机上 WhateverGreen 常常是"让屏幕亮起来"的那一个。没有它，加上我们自己的驱动还没写好，**启动期的画面可能是黑的或者停在 OpenCore 之后**。处理办法，按顺序：

1. **主通道是串口，不是画面。** 这正是第 9 节存在的原因，也是 `80` 第 2.1 节把 T3/T4 钉在 L1 的原因。E0-L1 的验收是"SSH 可达"，不是"桌面出图"（`80` 第 4.1 节），所以黑屏不阻塞 E0-L1。
2. **L1 上保留一个 QEMU 侧的显示设备** 作对照：`-device VGA,vgamem_mb=128`（`80` 第 2.4.2 节用的）或 `-device vmware-svga`（参考配置用的）。它让 OpenCore 的 picker 与 `boot.efi` 的 verbose 文字能被 `screendump` 抓到，与串口互为旁证。**注意这个设备会被 macOS 的哪个驱动接上是一个独立问题**：System KC 里有 `com.apple.driver.AppleVirtualGraphics`（`vm=0x14a24000`，`uuid=E80D3753-B895-3248-9480-65B9E31A4E37`，`KNOWN`），它可能会匹配上去并抢走显示。这件事与 `11-KERNEL-DISPLAY.md` 的核心问题直接相关，登记为 I-010。
3. **不要用 `-vga none` 来"确保我们的驱动被选中"。** 没有任何显示设备时 OpenCore 的 GOP 不存在，`ProvideConsoleGop` 会失败，连 picker 都看不到。研发期把 QEMU 显示设备留着，靠 `IOProbeScore` 与 `11-KERNEL-DISPLAY.md` 的关联机制去决定谁被选中。

---

## 7. 磁盘控制器与启动盘

这是 `80` 第 5.1 节头号风险的技术核心。第 3 节已经把事实基础换掉，本节给出三个候选的完整命令行与评估。

### 7.1 三个候选的 QEMU 命令行

三段都假设已有 `/srv/harness/macos.qcow2`，并且 OpenCore EFI 在 `/srv/harness/opencore.img`（raw，FAT32，见第 8 节）。

#### 候选 A：AHCI（`ich9-ahci`）

```bash
-device ich9-ahci,id=sata \
-drive id=oc,if=none,format=raw,file=/srv/harness/opencore.img \
-device ide-hd,bus=sata.0,drive=oc,bootindex=0 \
-drive id=disk0,if=none,format=qcow2,file=/srv/harness/macos.qcow2,cache=writeback,discard=unmap \
-device ide-hd,bus=sata.1,drive=disk0 \
-drive id=inst,if=none,format=raw,file=/srv/harness/BaseSystem.img,readonly=on \
-device ide-hd,bus=sata.2,drive=inst
```

#### 候选 B：NVMe

```bash
-device ich9-ahci,id=sata \
-drive id=oc,if=none,format=raw,file=/srv/harness/opencore.img \
-device ide-hd,bus=sata.0,drive=oc,bootindex=0 \
-drive id=disk0,if=none,format=qcow2,file=/srv/harness/macos.qcow2,cache=writeback,discard=unmap \
-device nvme,drive=disk0,serial=HARNESS0001,logical_block_size=4096,physical_block_size=4096 \
-drive id=inst,if=none,format=raw,file=/srv/harness/BaseSystem.img,readonly=on \
-device ide-hd,bus=sata.2,drive=inst
```

#### 候选 C：virtio-blk

```bash
-device ich9-ahci,id=sata \
-drive id=oc,if=none,format=raw,file=/srv/harness/opencore.img \
-device ide-hd,bus=sata.0,drive=oc,bootindex=0 \
-drive id=disk0,if=none,format=qcow2,file=/srv/harness/macos.qcow2,cache=writeback,discard=unmap \
-device virtio-blk-pci,drive=disk0,disable-legacy=on,disable-modern=off,num-queues=4 \
-drive id=inst,if=none,format=raw,file=/srv/harness/BaseSystem.img,readonly=on \
-device ide-hd,bus=sata.2,drive=inst
```

**三段都把 OpenCore 与安装介质留在 AHCI 上，只换系统盘。** 这是故意的：它把"macOS 能不能从这个控制器上看到系统盘"这一个变量单独隔出来。如果把 OpenCore 也搬到被测控制器上，失败时分不清是固件读不出 OpenCore 还是 XNU 认不出盘。

`disable-legacy=on,disable-modern=off` 强制 modern virtio（PCI device id `0x1042`，revision 1）。理由见 3.2 第 2 点。

### 7.2 逐一评估

| 候选 | guest 侧驱动是否存在 | 固件侧（OVMF）能否读 | macOS 26 能否看到系统盘 | Vultr 上可选吗 |
|---|---|---|---|---|
| **A AHCI** | **是。** `AppleAHCIPort` + `IOAHCIFamily` + `IOAHCIBlockStorage` 都在 x86_64 Boot KC；`GenericAHCI` 按类码 `0x010601` 匹配，覆盖 `ich9-ahci`（`KNOWN`，3.4） | 是，OVMF 自带 AHCI 驱动 | **`INFERRED`，几乎确定能**。这是社区通行配置，参考实现用的就是它（`KNOWN`，OSX-KVM `OpenCore-Boot.sh`） | **不可选**（`80` 1.7 节末行：设备模型固定） |
| **B NVMe** | **是。** `IONVMeFamily` 在 x86_64 Boot KC；`GenericNVMeSSD` 按类码 `0x010802` 匹配，覆盖 QEMU 的 `-device nvme`（`KNOWN`，3.4） | 是，OVMF 自带 NVMe 驱动 | **`INFERRED`，很可能能**。Apple 自己的 Intel 机器就用 NVMe SSD（`80` 1.5 节），类码匹配成立 | 不可选，但**Vultr 的盘有可能本来就是 NVMe**（`80` 1.5 节：块存储文档提到 NVMe 卷在 guest 内呈现为 `nda`） |
| **C virtio-blk** | **是。** `AppleVirtIO` 在 x86_64 Boot KC，`AppleVirtIOBlock` → `AppleVirtIOBlockStorageDevice`，transport 匹配任意 vendor `0x1af4`（`KNOWN`，3.2）。**这与 `80` 5.1 节的假设相反** | 是，OVMF 自带 virtio-blk 驱动；OpenCore 另带 `VirtioBlkDxe.efi` 作兜底 | **`INFERRED`**。独立佐证：有明确支持到 macOS 26 的项目给出的磁盘总线表是"macOS 10.15 到 macOS 26 支持 `SATA` 或 `VirtIO Block`"（转述自 <https://github.com/LongQT-sea/OpenCore-ISO/blob/main/README.md>） | 不可选，但**Vultr 的盘有可能本来就是 virtio**（`80` 1.5 节：VirtIO 卷呈现为 `vtbd`） |

**本项目的选择：L1 的 golden snapshot 用候选 C（virtio-blk），并在 E0-L1 里把 A 与 B 作为两个对照实验跑一遍。**

这与 `80` 第 2.4.2 节现有的 AHCI 配置不同，理由是分层设计的直接推论：

- `80` 第 1.7 节末行的结论是"本地绿灯不能推断 Vultr 绿灯"，因为本地的设备模型可控、Vultr 的固定。
- 但那条结论的强度取决于**本地的设备模型与 Vultr 的差距**。如果 L1 用 AHCI、Vultr 用 virtio，差距最大；如果 L1 用 virtio，差距只剩固件与拓扑。
- 第 3 节证明 virtio-blk 在 guest 侧有原生驱动，所以"L1 用 virtio"不再是明知会失败的选择。
- 把 A、B、C 三条都在 L1 跑一遍，成本是三次启动，收益是**在花钱开 L2 实例之前就知道三种控制器各自的 guest 侧表现**。这把 `80` 的 H-001（Vultr 盘的控制器型号）从"决定成败的未知"降级为"决定走哪条已验证路径的参数"。

`INFERRED`，整个 7.2 节在 E0-L1 跑完之前都是设计而非事实。

### 7.3 `ScanPolicy` 与 OpenCore 侧的 virtio 支持

**`ScanPolicy` 必须允许 PCI 设备，否则 OpenCore 根本不去扫 virtio 盘。**

`KNOWN`，官方文档给出的 `ScanPolicy` 位定义里，与我们相关的几条：

| 位 | 名称 | 含义 |
|---|---|---|
| `0x00000001` | `OC_SCAN_FILE_SYSTEM_LOCK` | 启用文件系统白名单 |
| `0x00000002` | `OC_SCAN_DEVICE_LOCK` | 启用设备白名单 |
| `0x00000100` | `OC_SCAN_ALLOW_FS_APFS` | 允许扫 APFS |
| `0x00000200` | `OC_SCAN_ALLOW_FS_HFS` | 允许扫 HFS |
| `0x00000400` | `OC_SCAN_ALLOW_FS_ESP` | 允许扫 EFI System Partition |
| `0x00010000` | `OC_SCAN_ALLOW_DEVICE_SATA` | 允许扫 SATA |
| `0x00020000` | `OC_SCAN_ALLOW_DEVICE_SASEX` | 允许扫 SAS 与 **Mac NVMe** |
| `0x00080000` | `OC_SCAN_ALLOW_DEVICE_NVME` | 允许扫 NVMe |
| `0x00100000` | `OC_SCAN_ALLOW_DEVICE_ATAPI` | 允许扫 CD/DVD 与老 SATA |
| `0x01000000` | `OC_SCAN_ALLOW_DEVICE_PCI` | 允许扫**直接挂在 PCI 总线上的设备（例如 VIRTIO）** |

（转述自 <https://dortania.github.io/docs/release/Configuration.html>，最后一条的括号注释"e.g. VIRTIO"是官方原文的说明。）

两个可用取值：

```text
ScanPolicy = 0           ← 本项目研发期用这个
ScanPolicy = 0x010F0103  ← Sample.plist 的默认值（十进制 17760515）
```

`0` 的含义是不启用任何白名单，全扫。研发期这是对的：我们要同时看到 ESP 上的 OpenCore、HFS+ 的 BaseSystem 卷、APFS 的系统卷、以及可能挂在 ATAPI 上的离线安装介质。参考配置也用 `0`（`KNOWN`，OSX-KVM `config.plist`）。

`0x010F0103` 拆开是 `LOCK(0x3) + APFS(0x100) + SATA + SASEX + SCSI + NVME + PCI`。**注意它包含 `0x01000000`**，即 OpenCore 官方的默认示例已经把 virtio 盘纳入扫描范围。这是第 3 节结论的一个侧面印证：OpenCore 上游认为从 virtio 盘启动 macOS 是一个正常场景。

**OpenCore 自带的四个 virtio UEFI 驱动**（`VirtioPciDeviceDxe.efi`、`Virtio10.efi`、`VirtioBlkDxe.efi`、`VirtioSerialDxe.efi`，`KNOWN`，见 `Docs/Sample.plist` 的 `UEFI/Drivers`）的用途要说清，否则容易误用：

- 它们是**固件侧**的驱动，让 OpenCore 自己能读到 virtio 设备。
- OVMF 已经自带这些，所以 **L1 上不要开**，开了会和固件的驱动重复绑定同一设备。
- **它们的价值在 L2**：如果 Vultr 的固件不是 OVMF 或裁掉了 virtio 支持，OpenCore 会看不到盘。这时开这四个（`VirtioPciDeviceDxe` + `Virtio10` 是 transport，`VirtioBlkDxe` 是块设备）就能自救。
- 它们**不影响** XNU 能不能认出盘。XNU 那一侧靠的是第 3.2 节的 `AppleVirtIO`。两件事要分开记。

### 7.4 在 guest 内确认控制器型号的确切命令

这是 `80` 第 1.5 节三个 `BLOCKED` 项（H-001 盘控制器、H-001 网卡、以及间接的 H-004）的关闭手段。全部在 guest 内执行，不需要 GUI。

```bash
#!/usr/bin/env bash
# /usr/local/bin/probe-storage.sh : 确认启动盘走的是哪个控制器
set -u

echo "===== 1. PCI 设备全表（vendor/device ID 在这里）====="
ioreg -l -p IODeviceTree -c IOPCIDevice -w 0 \
  | grep -E '"(vendor-id|device-id|class-code|IOName|model|revision-id|subsystem-vendor-id|subsystem-id)"'

echo "===== 2. 更可读的 PCI 列表 ====="
ioreg -r -c IOPCIDevice -d 1 -w 0 | grep -E '^\+-o|"IOName"|"model"'

echo "===== 3. 块设备与它们的物理互连类型 ====="
# "Physical Interconnect" 的取值直接区分 SATA / PCI-Express / Apple Fabric
ioreg -r -c IOBlockStorageDevice -l -w 0 \
  | grep -E '"(Physical Interconnect|Physical Interconnect Location|Product Name|Vendor Name|Device Characteristics|Protocol Characteristics)"'

echo "===== 4. 哪个驱动类接住了启动盘 ====="
# 四个互斥的答案：AppleAHCI / IONVMeController / AppleVirtIOBlockStorageDevice / 其它
for cls in AppleAHCI IONVMeController AppleVirtIOBlockStorageDevice AppleVirtIOPCITransport AppleLSIFusionMPT; do
  n=$(ioreg -r -c "$cls" -d 1 -w 0 2>/dev/null | grep -c '^+-o')
  echo "  $cls : $n 个实例"
done

echo "===== 5. 服务树里启动盘的完整路径 ====="
diskutil info -plist / | plutil -p - | grep -E 'DeviceNode|BusProtocol|MediaName|Internal|SolidState'
ioreg -r -n "$(diskutil info / | awk -F': *' '/Device Node/{print $2}' | xargs basename)" -l -w 0 2>/dev/null | head -60

echo "===== 6. 系统侧摘要（与 ioreg 互为旁证）====="
system_profiler SPNVMeDataType SPSerialATADataType SPStorageDataType SPPCIDataType 2>/dev/null

echo "===== 7. 网卡 ====="
ioreg -r -c IOEthernetController -l -w 0 | grep -E '"(IOClass|IOProviderClass|IOModel|BSD Name|Product Name|vendor-id|device-id)"'
networksetup -listallhardwareports
ifconfig -a | grep -E '^[a-z]'
```

**判定表**（每一行对应一个确定的答案）：

| `ioreg -r -c <X>` 有实例 | 结论 |
|---|---|
| `AppleAHCI` | 盘走模拟 AHCI。`Physical Interconnect` 会是 `SATA` |
| `IONVMeController` | 盘走 NVMe。`Physical Interconnect` 会是 `PCI-Express` |
| `AppleVirtIOPCITransport` **且** `AppleVirtIOBlockStorageDevice` | **virtio-blk 成立**，第 3.2 节的推断得到运行证据 |
| `AppleVirtIOPCITransport` 有、`AppleVirtIOBlockStorageDevice` 没有 | transport 认出了 PCI 设备但**没有发布正确的 `IOVirtIOPrimaryMatch`**，即 3.2 节第 2 点的 `INFERRED` 被否定。这时看 transport 节点上有什么属性，那就是 I-003 的答案 |
| 三个都没有 | 盘根本没被任何驱动接住。查 `ioreg -c IOPCIDevice` 里那个设备的 `class-code` |

### 7.5 在 Vultr 上无法选择设备模型的后果

`KNOWN`（`80` 第 1.7 节能力对照表末行）：Vultr 的设备模型固定不可改。所以上面三个候选在 L2 上**不是选项，是赌注**。修正后的后果分析：

| Vultr 系统盘实际是 | 后果 | 需要做什么 |
|---|---|---|
| NVMe（`nda`） | **可行。** `IONVMeFamily` 在 Boot KC，类码匹配 | `ScanPolicy` 含 NVMe 位（我们用 `0`，已覆盖） |
| virtio-blk（`vtbd`） | **很可能可行。** 第 3.2 节 | `ScanPolicy` 含 PCI 位（已覆盖）；若固件缺 virtio 支持则开 7.3 的四个 UEFI 驱动 |
| AHCI | 可行 | 无 |
| 别的（例如 SCSI/SAS） | Boot KC 里有 `IOSCSIParallelFamily` 与 `AppleLSIFusionMPT`，**也许**可行 | 先在 L1 用 `-device mptsas1068` 试，见 I-008 |
| 固件不拾取 `EFI/BOOT/BOOTX64.EFI` | **完全不可行，且与盘无关** | 这是 `80` 1.5 节"自定义引导链"那一行的 `INFERRED`，必须由 E0-L2 验证。登记为 **I-024** |

**关键的认知更新：现在"Vultr 上装不上"的最大可能原因已经不是盘，而是固件是否允许自定义引导链。** 前者有三条 guest 侧驱动覆盖，后者一条也没有。`80` 第 5.1 节的缓解路径第 3 条（"若盘是 VirtIO，评估为 macOS 写一个 VirtIO-blk 驱动的代价"）**可以从计划里删掉**，那个驱动 Apple 已经写好了。

E0-L2 的首启探针因此要把重点放在：实例能不能从我们的介质引导（看得到 OpenCore picker 就算成立），而不是盘能不能被看到。

---

## 8. 镜像打包与交付形态

### 8.1 产物总表

| 产物 | 形态 | 体积量级 | 用在哪 | 在哪台机器上造 |
|---|---|---|---|---|
| `opencore.img` | raw，单 FAT32 分区（或裸 FAT32） | 64 MiB | L1 + L2，EFI 引导分区 | 内容在 Windows 准备，镜像在 Linux 封装 |
| `BaseSystem.img` | raw，从 `x86_64BaseSystem.dmg` 转换 | 1.46 GB | L1 + L2，恢复/安装介质 | Linux（`qemu-img`） |
| `macos-golden.qcow2` | qcow2 | 128 GB 稀疏，实占 20 到 40 GB | L1，golden snapshot | Linux |
| `macos-oc-<build>.iso` | hybrid ISO | ~1.6 GB | L2，Vultr ISO 槽位 | Linux（`xorriso`） |
| `macos-oc-<build>.raw` | raw GPT 磁盘镜像 | ~1.6 GB（可压缩） | L2，`snapshots/create-from-url` | Linux |
| `payload-<exp>.img` | raw，FAT32 | 512 MiB | L1，`80` 第 2.5 节路径 B | Linux |
| `InstallAssistant.iso` | ISO9660 level 3 | 18.4 GB | L1 离线安装 | Linux |

### 8.2 形态 1：本地 KVM 用的 qcow2

#### 8.2.1 准备 EFI 树（Windows 上完成）

```powershell
# scripts/stage-efi.ps1
$ErrorActionPreference = 'Stop'
$OC_TAG   = '<pin-this>'          # 写死 OpenCorePkg 的 release tag
$STAGE    = 'build\efi'

New-Item -ItemType Directory -Force -Path $STAGE | Out-Null

# 1. OpenCore DEBUG 包（研发期一律用 DEBUG，理由见 2.5）
curl.exe -L -o build\OpenCore-DEBUG.zip `
  "https://github.com/acidanthera/OpenCorePkg/releases/download/$OC_TAG/OpenCore-$OC_TAG-DEBUG.zip"
tar.exe -xf build\OpenCore-DEBUG.zip -C build\oc

# 2. 骨架
New-Item -ItemType Directory -Force -Path `
  "$STAGE\EFI\BOOT","$STAGE\EFI\OC\ACPI","$STAGE\EFI\OC\Drivers", `
  "$STAGE\EFI\OC\Kexts","$STAGE\EFI\OC\Tools","$STAGE\EFI\OC\Resources" | Out-Null

Copy-Item build\oc\X64\EFI\BOOT\BOOTx64.efi    "$STAGE\EFI\BOOT\"
Copy-Item build\oc\X64\EFI\OC\OpenCore.efi     "$STAGE\EFI\OC\"
foreach ($d in 'OpenRuntime.efi','OpenHfsPlus.efi','ResetNvramEntry.efi','ToggleSipEntry.efi',
               'VirtioPciDeviceDxe.efi','Virtio10.efi','VirtioBlkDxe.efi','VirtioSerialDxe.efi') {
  Copy-Item "build\oc\X64\EFI\OC\Drivers\$d" "$STAGE\EFI\OC\Drivers\"
}
Copy-Item build\oc\X64\EFI\OC\Tools\OpenShell.efi "$STAGE\EFI\OC\Tools\"

# 3. kext（三个，见 6.5.1）
#    Lilu / VirtualSMC / AppleMCEReporterDisabler 从各自 release 取，解压到 Kexts\
#    AppleMCEReporterDisabler 随 VirtualSMC 的 release 分发

# 4. SSDT（见 6.2）
#    SSDT-EC.aml 与 SSDT-USBX.aml 放进 ACPI\

# 5. config.plist
py scripts\make-oc-config.py build\oc\Docs\Sample.plist "$STAGE\EFI\OC\config.plist"

# 6. 清单与哈希
Get-ChildItem -Recurse -File $STAGE |
  ForEach-Object {
    $h = (Get-FileHash -Algorithm SHA256 $_.FullName).Hash
    $rel = $_.FullName.Substring((Resolve-Path $STAGE).Path.Length + 1)
    "$h  $rel"
  } | Set-Content -Encoding ascii build\efi.sha256
```

**`EFI/OC/Resources` 留空是对的**（`PickerMode = Builtin`，不用 OpenCanopy，见 6.6.1）。如果以后要用 OpenCanopy，资源来自 `acidanthera/OcBinaryData`，那时才需要固定它的 commit。

#### 8.2.2 封成 raw EFI 镜像（Linux）

```bash
#!/usr/bin/env bash
# scripts/mk-opencore-img.sh <efi-stage-dir> <out.img>
set -euo pipefail
STAGE="${1:?}"; OUT="${2:?}"

# 64 MiB 足够装 OpenCore + 三个 kext + 两个 SSDT，留足余量给 ApplePanic 落盘
truncate -s 64M "$OUT"
mkfs.vfat -F 32 -n OPENCORE "$OUT"

# mtools 不需要 root，也不需要 loop 设备
mmd  -i "$OUT" ::/EFI ::/EFI/BOOT ::/EFI/OC
mcopy -i "$OUT" -s "$STAGE/EFI/BOOT/."* ::/EFI/BOOT/ 2>/dev/null || true
mcopy -i "$OUT" -s "$STAGE/EFI/BOOT" ::/EFI/
mcopy -i "$OUT" -s "$STAGE/EFI/OC"   ::/EFI/

mdir -i "$OUT" -/ ::/EFI
sha256sum "$OUT" | tee "$OUT.sha256"
```

**为什么是裸 FAT32 而不是带 GPT 的磁盘镜像**：OVMF 会把任何含 FAT 文件系统的块设备当成可引导候选，不要求有分区表。少一层分区表就少一处可能写错的偏移。参考实现用的也是一个单独的小盘（`OSX-KVM` 的 `OpenCore.qcow2`，`KNOWN`）。

#### 8.2.3 BaseSystem 转 raw（Linux）

```bash
#!/usr/bin/env bash
# scripts/mk-basesystem-img.sh <x86_64BaseSystem.dmg> <out.img>
set -euo pipefail
DMG="${1:?}"; OUT="${2:?}"

# 先确认它是磁盘镜像还是裸卷镜像（见本文 1.5 的 INFERRED）
qemu-img info -f dmg "$DMG"

# UDIF -> raw。qemu 的 dmg 块驱动支持 zlib / bzip2 / lzfse 分块
qemu-img convert -p -f dmg -O raw "$DMG" "$OUT"

# 判定：有 GPT 的话这里能看到分区
sfdisk -l "$OUT" || true
# 没有 GPT 的话这一句能看出卷签名（APFS 的 NXSB 或 HFS+ 的 H+）
dd if="$OUT" bs=1 skip=32 count=4 2>/dev/null | xxd

sha256sum "$OUT" | tee "$OUT.sha256"
```

**两种结果对应两种挂载方式**：

- **有 GPT**（即它是磁盘镜像）：直接 `-device ide-hd` 当盘挂，OpenCore 会扫到里面的卷。这是第 2.4 节路 A。
- **无 GPT**（裸卷镜像）：需要先包一层。用 `sgdisk` 造一个单分区的 GPT 容器再把卷内容 `dd` 进去：

```bash
# 仅在上一步判定为裸卷镜像时执行
SZ=$(stat -c%s "$OUT")
truncate -s $(( SZ + 2*1024*1024 )) basesystem-disk.img
sgdisk -o -n 1:2048:0 -t 1:7C3457EF-0000-11AA-AA11-00306543ECAC basesystem-disk.img  # APFS
#      HFS+ 用 -t 1:48465300-0000-11AA-AA11-00306543ECAC
dd if="$OUT" of=basesystem-disk.img bs=1M seek=1 conv=notrunc
```

`INFERRED`，分区类型 GUID 取决于 BaseSystem 卷的实际文件系统，上一步的 `xxd` 能判定。

#### 8.2.4 造 qcow2 并启动

`80` 第 2.4.2 节的 QEMU 命令行在本文的配置下需要五处改动。改动后的完整命令行（可直接照抄）：

```bash
#!/usr/bin/env bash
# scripts/boot-l1.sh <mode: install|run> <exp-id>
set -euo pipefail
MODE="${1:?install|run}"; EXP="${2:-manual}"
H=/srv/harness
R=/run/harness; mkdir -p "$R"

# 每次实验一份独立的 NVRAM，理由见 6.7
cp -f "$H/OVMF_VARS.fd" "$R/OVMF_VARS-$EXP.fd"

if [ "$MODE" = install ]; then
  DISK="$H/macos-golden.qcow2"
  [ -f "$DISK" ] || qemu-img create -f qcow2 "$DISK" 128G
  INSTALL_ARGS=(
    -drive id=inst,if=none,format=raw,readonly=on,file="$H/BaseSystem.img"
    -device ide-hd,bus=sata.2,drive=inst
    # 离线安装介质，见 2.4。联网装系统时去掉这两行
    -drive id=iainst,if=none,format=raw,readonly=on,file="$H/InstallAssistant.iso"
    -device ide-hd,bus=sata.3,drive=iainst
  )
else
  # 实验用 overlay，基准盘永不被写。80 第 2.4.2 节步骤 7
  DISK="$R/exp-$EXP.qcow2"
  qemu-img create -f qcow2 -b "$H/golden/macos-26.7.2-25G325-golden.qcow2" \
                  -F qcow2 "$DISK"
  INSTALL_ARGS=()
fi

exec qemu-system-x86_64 \
  -enable-kvm \
  -machine q35,accel=kvm \
  -cpu Skylake-Server-v4,-hle,-rtm,kvm=on,vendor=GenuineIntel,+invtsc,vmware-cpuid-freq=on,+ssse3,+sse4.2,+popcnt,+avx,+aes,+xsave,+xsaveopt,check \
  -smp 8,cores=4,sockets=1,threads=2 \
  -m 16384 \
  -global ICH9-LPC.acpi-pci-hotplug-with-bridge-support=off \
  \
  -drive if=pflash,format=raw,readonly=on,file="$H/OVMF_CODE_4M.fd" \
  -drive if=pflash,format=raw,file="$R/OVMF_VARS-$EXP.fd" \
  \
  -device isa-applesmc,osk="ourhardworkbythesewordsguardedpleasedontsteal(c)AppleComputerInc" \
  -device pvpanic \
  -smbios type=2 \
  \
  -device ich9-ahci,id=sata \
  -drive id=oc,if=none,format=raw,file="$H/opencore.img" \
  -device ide-hd,bus=sata.0,drive=oc,bootindex=0 \
  \
  -drive id=disk0,if=none,format=qcow2,cache=writeback,discard=unmap,file="$DISK" \
  -device virtio-blk-pci,drive=disk0,disable-legacy=on,disable-modern=off,num-queues=4 \
  "${INSTALL_ARGS[@]}" \
  \
  -netdev user,id=n0,hostfwd=tcp::2222-:22 \
  -device virtio-net-pci,netdev=n0,mac=52:54:00:c9:18:27 \
  \
  -device qemu-xhci,id=xhci \
  -device usb-kbd,bus=xhci.0 \
  -device virtio-tablet-pci \
  \
  -device VGA,vgamem_mb=128 \
  -vnc 127.0.0.1:1,password=on \
  \
  -chardev socket,id=ser0,host=127.0.0.1,port=4555,server=on,wait=off,logfile="$R/serial-$EXP.log",logappend=on \
  -serial chardev:ser0 \
  \
  -qmp unix:"$R/qmp-$EXP.sock",server=on,wait=off \
  -name "macos-$EXP"
```

与 `80` 第 2.4.2 节的差异，逐条给理由：

| 改动 | 原值 | 新值 | 理由 |
|---|---|---|---|
| CPU | `-cpu host,vendor=GenuineIntel` | `Skylake-Server-v4,...` | 第 5 节。`-cpu host` 在 macOS 26 上要依赖 `ProvideCurrentCpuInfo` 兜住 MSR 0x35，且 CPUID 随宿主变化，实验不可复现 |
| 系统盘 | `ich9-ahci` + `ide-hd` | `virtio-blk-pci` | 第 7.2 节。AHCI 作为对照实验保留 |
| 网卡 | `vmxnet3` | `virtio-net-pci` | 第 3.5 节。系统自带 `AppleVirtIONetwork`，且与可能的 Vultr 设备模型更接近 |
| SMC | 无 | `isa-applesmc` | 第 6.5.1 节 |
| panic 通道 | 无 | `pvpanic` | 第 3.6 节。给 QMP 一个 `GUEST_PANICKED` 事件 |
| 指针设备 | 无 | `virtio-tablet-pci` | `KNOWN`：macOS 26 上光标可能随机卡住，改用 `virtio-tablet-pci` 是给出的更好修法，代价是中键变右键（转述自 <https://github.com/LongQT-sea/OpenCore-ISO/blob/main/README.md>） |
| PCI hotplug | 无 | `-global ICH9-LPC.acpi-pci-hotplug-with-bridge-support=off` | `KNOWN`，同一来源给出的 q35 配置建议。它让 PCI 回到原生 PCIe hotplug，避免 ACPI hotplug 带来的设备树差异 |
| NVRAM | 共用 `OVMF_VARS.fd` | 每实验一份 | 第 6.7 节 `WriteFlash = true` 的直接后果 |
| 串口 | `logfile=...` | 加 `logappend=on` | 跨重启累积日志。一次实验里 guest 会重启多次（`70` 第 4.1 节：kext 生效需要重启），不加会被截断 |

`INFERRED`：`-chardev socket` 是否支持 `logfile=` 是 `80` 的 H-007，未实测。失败时退回 `-serial file:"$R/serial-$EXP.log"`，代价是失去交互能力，而交互能力是 `serial=7` 里 `SERIALMODE_INPUT` 那一位的用途（第 9.4 节）。

#### 8.2.5 golden snapshot 与哈希

照 `80` 第 2.4.2 节步骤 6 和 7，不重复。本文只补一条：**golden 盘的哈希必须包含 `opencore.img` 与 `OVMF_VARS.fd` 的哈希**，否则"同一个 golden"可能配不同的引导配置。

```bash
cd /srv/harness/golden
for f in macos-26.7.2-25G325-golden.qcow2 opencore.img OVMF_VARS.fd OVMF_CODE_4M.fd; do
  sha256sum "$f"
done > golden-26.7.2-25G325.sha256
chmod a-w macos-26.7.2-25G325-golden.qcow2
cat golden-26.7.2-25G325.sha256
```

这四个哈希写进 `80` 的 `result.json`，与 `70` 第 7 节 `MANIFEST.json` 的 `build` 字段并列。建议的字段名：`env.image.{golden_qcow2,opencore_img,ovmf_vars,ovmf_code}_sha256`。

### 8.3 形态 2：Vultr 用的可启动介质

#### 8.3.1 约束与一个常被忽略的冲突

`80` 第 1.2 节的三条硬约束：ISO 只能由 Vultr 从公开 URL 拉取（无直传接口）、单账户最多 2 个 ISO、单 ISO ≤ 10 GB。

**还有第四条，`80` 没有明说但从 API 形状可以推出**：`POST /v2/instances/{id}/iso/attach` 的请求体只有一个 `iso_id`，而 `GET /v2/instances/{id}/iso` 返回单个 `state`。即**一个实例同一时刻只能挂一张 ISO**。`INFERRED`，依据是 `80` 第 1.2 节引用的 `govultr/iso.go` 的接口形状。

这一条很关键：Proxmox/QEMU 上的通行做法是**两个光驱**，一个放 OpenCore ISO、一个放 macOS 安装 ISO（`KNOWN`，`LongQT-sea/OpenCore-ISO` 的流程就是这样，它还特别警告这些是真正的 CD/DVD ISO、必须以 CD/DVD 方式添加、不要把 `media=cdrom` 改成 `media=disk`，转述自 <https://github.com/LongQT-sea/OpenCore-ISO/blob/main/README.md>）。**那套流程在 Vultr 上直接用不了**，因为只有一个槽。

所以 Vultr 的介质必须是**一张同时含 OpenCore 与恢复环境的镜像**。

#### 8.3.2 体积账

| 内容 | 字节 | 占 10 GB 预算 |
|---|---:|---|
| OpenCore EFI 树（DEBUG + 3 kext + 2 SSDT） | < 30 MB | 0.3% |
| `x86_64BaseSystem.dmg`（还原后） | 1,464,270,504 | 14.6% |
| 合计 | ≈ 1.5 GB | **15%** |
| 对比：`InstallAssistant.pkg` | 18,384,411,815 | **184%，放不进去** |
| 对比：`SharedSupport.dmg` | 18,366,480,610 | **184%，放不进去** |

**结论：Vultr 的 ISO 里只放 OpenCore + BaseSystem，完整安装器不进 ISO。** 完整安装器的投送见 8.3.4。

#### 8.3.3 配方 A：单张 hybrid ISO

布局决策：**OpenCore 放进 El Torito 的 EFI 启动镜像（一个小 FAT32），BaseSystem 放在 ISO9660/UDF 的文件树里。**

不把 BaseSystem 也塞进 FAT 启动镜像的理由：El Torito 启动目录项里的扇区计数是 16 位字段，`no-emulation` 模式下理论上限是 65535 × 512 ≈ 32 MB。一个 1.5 GB 的启动镜像超出规范，能不能被固件接受取决于实现。`INFERRED`，不赌。

```bash
#!/usr/bin/env bash
# scripts/mk-vultr-iso.sh <efi-stage-dir> <BaseSystem.dmg> <out.iso>
set -euo pipefail
STAGE="${1:?}"; BS="${2:?}"; OUT="${3:?}"
W=$(mktemp -d); trap 'rm -rf "$W"' EXIT

# ---- 1. El Torito 的 EFI 启动镜像：只放 OpenCore ----
truncate -s 48M "$W/efiboot.img"
mkfs.vfat -F 32 -n OCBOOT "$W/efiboot.img"
mmd   -i "$W/efiboot.img" ::/EFI
mcopy -i "$W/efiboot.img" -s "$STAGE/EFI/BOOT" ::/EFI/
mcopy -i "$W/efiboot.img" -s "$STAGE/EFI/OC"   ::/EFI/

# ---- 2. ISO 的文件树 ----
mkdir -p "$W/iso/com.apple.recovery.boot" "$W/iso/EFI"
cp "$BS" "$W/iso/com.apple.recovery.boot/BaseSystem.dmg"
# 冗余副本：有些固件只认 ISO 里的 /EFI/BOOT/BOOTX64.EFI 而不走 El Torito
cp -r "$STAGE/EFI/BOOT" "$W/iso/EFI/"
cp -r "$STAGE/EFI/OC"   "$W/iso/EFI/"
cp    "$W/efiboot.img"  "$W/iso/efiboot.img"

# ---- 3. 打成 hybrid ISO ----
# -udf 很重要：UEFI 固件对 UDF 的 SimpleFileSystem 支持比对 ISO9660 更一致
xorriso -as mkisofs \
  -iso-level 3 -full-iso9660-filenames -allow-limited-size \
  -volid "MACOS25G325" \
  -udf \
  -eltorito-alt-boot \
  -e efiboot.img -no-emul-boot \
  -isohybrid-gpt-basdat \
  -o "$OUT" "$W/iso"

sha256sum "$OUT" | tee "$OUT.sha256"
md5sum    "$OUT" | tee "$OUT.md5"
ls -l "$OUT"
```

**`md5sum` 与 `sha256sum` 都要算**，因为 Vultr 上传完成后在 `GET /v2/iso/{id}` 里回报的是 `md5sum` 与 `sha512sum`（`80` 第 1.2 节）。为了能和平台回报的值比对，再加一条：

```bash
sha512sum "$OUT" | tee "$OUT.sha512"
```

然后按 `80` 第 2.4.3 节步骤 1 的 API 序列上传并比对。

`INFERRED`，这个配方里有两处未验证：

1. **固件能否从 ISO9660/UDF 的文件树里读到 `com.apple.recovery.boot/BaseSystem.dmg`**。OpenCore 要通过固件的 `EFI_SIMPLE_FILE_SYSTEM_PROTOCOL` 去读它。`-udf` 是为了提高这件事的成功率。查清方法：在 L1 上把这张 ISO 以 `-device ide-cd` 挂上，看 OpenCore picker 里是否出现带 `(dmg)` 后缀的条目。登记为 **I-021**。
2. **走到这一步必须把 `DmgLoading` 改成 `Any`**（没有 chunklist，见 6.6.3），即落回 **I-007**。

#### 8.3.4 配方 B：`snapshots/create-from-url`，更优

`KNOWN`（`80` 第 1.2 节）：Vultr 提供 `POST /v2/snapshots/create-from-url`，请求体为 `{"url": "...", "description": "...", "uefi": true}`，官方文档说明快照可从 RAW 镜像 URL 创建且跨区域可用。`uefi` 这个布尔字段是 Vultr 支持 UEFI 引导的直接证据。

**这条路比 ISO 好，三个理由**：

1. **不占 ISO 槽位。** 两个 ISO 槽位可以完整留给救援用途（`80` 第 2.5 节路径 C）。
2. **不受 10 GB 的 ISO 上限约束。** ISO 的上限是 ISO 这条通道的，快照是另一条通道。`INFERRED`：快照自己的上限未查清，登记为 I-014。
3. **产物是磁盘而不是光盘**，所以第 2.4 节的路 A（BaseSystem 当盘挂）天然成立，不需要 DMG 加载，也就不需要把 `DmgLoading` 放宽到 `Any`。

```bash
#!/usr/bin/env bash
# scripts/mk-vultr-raw.sh <efi-stage-dir> <BaseSystem.img> <out.raw>
# 产物：GPT 磁盘镜像，p1 = ESP(OpenCore)，p2 = BaseSystem 卷
set -euo pipefail
STAGE="${1:?}"; BSIMG="${2:?}"; OUT="${3:?}"

ESP_MB=64
BS_BYTES=$(stat -c%s "$BSIMG")
BS_MB=$(( (BS_BYTES + 1048575) / 1048576 ))
TOTAL_MB=$(( 1 + ESP_MB + BS_MB + 1 ))

truncate -s "${TOTAL_MB}M" "$OUT"

# p1: EFI System Partition；p2: Apple APFS（类型 GUID 按 8.2.3 的判定结果选）
sgdisk -o \
  -n 1:2048:+${ESP_MB}M -t 1:C12A7328-F81F-11D2-BA4B-00A0C93EC93B -c 1:"EFI" \
  -n 2:0:+${BS_MB}M     -t 2:7C3457EF-0000-11AA-AA11-00306543ECAC -c 2:"BaseSystem" \
  "$OUT"
sgdisk -p "$OUT"

# 往 p1 写 OpenCore
P1_START=$(sgdisk -i 1 "$OUT" | awk '/First sector/{print $3}')
dd if=/dev/zero of="$OUT" bs=512 seek="$P1_START" count=$(( ESP_MB * 2048 )) conv=notrunc status=none
truncate -s ${ESP_MB}M /tmp/esp.img
mkfs.vfat -F 32 -n OPENCORE /tmp/esp.img
mmd   -i /tmp/esp.img ::/EFI
mcopy -i /tmp/esp.img -s "$STAGE/EFI/BOOT" ::/EFI/
mcopy -i /tmp/esp.img -s "$STAGE/EFI/OC"   ::/EFI/
dd if=/tmp/esp.img of="$OUT" bs=512 seek="$P1_START" conv=notrunc status=none

# 往 p2 写 BaseSystem 卷内容
P2_START=$(sgdisk -i 2 "$OUT" | awk '/First sector/{print $3}')
dd if="$BSIMG" of="$OUT" bs=1M seek=$(( P2_START / 2048 )) conv=notrunc status=progress

sha256sum "$OUT" | tee "$OUT.sha256"
# 托管前压缩可以省带宽，但要确认 Vultr 接受的格式。登记为 I-014
```

上传序列（在 `80` 第 2.4.3 节的 API 风格上）：

```bash
export VH="Authorization: Bearer ${VULTR_API_KEY}"
export VJ="Content-Type: application/json"

SNAP_ID=$(curl -s -X POST "https://api.vultr.com/v2/snapshots/create-from-url" \
  -H "$VH" -H "$VJ" \
  -d '{"url":"https://assets.example.net/macos-26.7.2-25G325-oc.raw",
       "description":"macos-26.7.2-25G325 oc boot media r1",
       "uefi":true}' | jq -r '.snapshot.id')

until [ "$(curl -s "https://api.vultr.com/v2/snapshots/${SNAP_ID}" -H "$VH" \
          | jq -r '.snapshot.status')" = "complete" ]; do sleep 60; done

INST_ID=$(curl -s -X POST "https://api.vultr.com/v2/instances" -H "$VH" -H "$VJ" \
  -d "{\"region\":\"ewr\",\"plan\":\"${PLAN}\",\"snapshot_id\":\"${SNAP_ID}\",
       \"label\":\"macos-e0-l2\",\"tags\":[\"harness\",\"e0\"],
       \"enable_ipv6\":false,\"backups\":\"disabled\"}" | jq -r '.instance.id')
# 创建响应里的 default_password 必须立刻落盘（80 第 1.1 节）
```

**这个序列同时就是 E0-L2 的实验本体。** 它一次性回答 `80` 1.5 节"自定义引导链"那一行（**I-024**）：如果实例起来之后网页控制台里能看到 OpenCore 的 picker，这条 `INFERRED` 就变成已知可行；如果看不到，整个 L2 层要按 `80` 第 5.1 节的缓解路径 4 处理。

#### 8.3.5 L2 上的完整安装器怎么办

18.4 GB 放不进 ISO，也不该放进引导镜像。三条路：

| 路 | 做法 | 依赖 | 评估 |
|---|---|---|---|
| **1. 联网恢复安装**（首选） | 从 BaseSystem 进恢复环境，让它从 Apple 下载 | guest 的网卡必须工作 | 第 3.5 节证明 `AppleVirtIONetwork` 与 `AppleVmxnet3Ethernet` 都在 Boot KC。**如果 Vultr 用 virtio-net，这条路直接成立** |
| 2. Block Storage 投送 | 建一个 20 GB 卷，`attach` 后在 guest 内读 `InstallAssistant.pkg` | 热插拔要被 guest 看到 | `80` 的 H-004。**第 3.2 节让它的前景大幅改善**：若 Vultr 的 Block Storage 是 virtio-blk，`AppleVirtIO` 就能接上 |
| 3. 把安装器放进 golden snapshot | 在 L1 装好系统、`80` 第 2.4.3 节那样做成 L2 快照 | 快照体积上限 | **实际上是最省事的一条**，因为 L2 的 golden 本来就要从一个装好的系统做出来 |

**推荐顺序：3 → 1 → 2。** 路 3 把"在 L2 上装系统"这件事整个绕开：先在 L1 装好并武装（`80` 第 2.4.2 节步骤 4、5），再把 qcow2 转成 raw、托管、`create-from-url` 成 L2 的 golden 快照。

```bash
# L1 的 golden 转成 L2 可用的 raw
qemu-img convert -p -f qcow2 -O raw \
  /srv/harness/golden/macos-26.7.2-25G325-golden.qcow2 \
  /srv/publish/macos-26.7.2-25G325-golden.raw
sha256sum /srv/publish/macos-26.7.2-25G325-golden.raw
```

`INFERRED`：这条路要求 L1 装好的系统在 L2 的设备模型下还能启动。**这正是第 7 节把 L1 的系统盘定成 virtio-blk 的另一个收益**：如果 Vultr 也是 virtio，盘的呈现一致，迁移风险最小。如果 Vultr 是 NVMe，由于 `IONVMeFamily` 同样在 Boot KC 且 APFS 容器与控制器无关，`INFERRED` 仍可启动，但要在 E0-L2 验证。

### 8.4 形态 3：payload 投放介质

对应 `80` 第 2.5 节路径 B。

```bash
#!/usr/bin/env bash
# scripts/mk-payload-img.sh <payload-dir> <exp-id>
set -euo pipefail
PKG="${1:?}"; EXP="${2:?}"
OUT="/run/harness/payload-${EXP}.img"

# 先在 host 侧生成清单，guest 内校验后才安装。70 第 7.3 节
( cd "$PKG" && find . -type f -print0 | sort -z | xargs -0 sha256sum > ../MANIFEST.sha256 )

truncate -s 512M "$OUT"
mkfs.vfat -F 32 -n PAYLOAD "$OUT"
mcopy -i "$OUT" -s "$PKG" ::/
mcopy -i "$OUT" "$PKG/../MANIFEST.sha256" ::/
mdir -i "$OUT" -/ ::

sha256sum "$OUT" | tee "$OUT.sha256"
```

挂载（追加到 8.2.4 的命令行，或运行时用 QMP `blockdev-add` 热插）：

```bash
-drive id=payload,if=none,format=raw,file=/run/harness/payload-${EXP}.img \
-device ide-hd,bus=sata.4,drive=payload
```

**FAT32 而不是 HFS+**，理由同 `80` 第 2.5 节：macOS 必然能读 FAT（`msdosfs.kext` 在 System KC 里，`KNOWN`，第 3.1 节的条目清单含 `com.apple.filesystems.msdosfs`），而 Linux 侧用 `mtools` 不需要特权。

**挂在 AHCI 而不是 virtio**：投放介质的可靠性优先于一致性。AHCI 是三个候选里最确定的那个（第 7.2 节），把它留给"实验失败时还要能把证据带出来"这个用途。

guest 内的消费：

```bash
# 挂载点由 macOS 自动分配到 /Volumes/PAYLOAD
cd /Volumes/PAYLOAD
shasum -a 256 -c MANIFEST.sha256
sudo /usr/local/libexec/harness-agent install /Volumes/PAYLOAD
```

### 8.5 哈希与清单的统一约定

本文产出的每一个镜像都要有三样东西，与 `70` 第 7.3 节共用一套约定：

1. `<产物>.sha256`：产物自身的 SHA-256。
2. `<产物>.md5` 与 `<产物>.sha512`：**仅 Vultr ISO 需要**，用于与平台回报值比对（`80` 第 1.2 节）。
3. 一份 `image-manifest.json`，记录构成这个镜像的每一个输入件：

```json
{
  "schema": "metal2vu.image.manifest/1",
  "image_id": "img-20261030-0914-oc<OC_TAG>",
  "built_at": "2026-10-30T09:14:52Z",
  "target_os": { "product": "macOS", "version": "26.7.2", "build": "25G325",
                 "arch": "x86_64" },
  "platform_profile": {
    "smbios": "MacPro7,1",
    "board_id": "Mac-27AD2F918AE68F61",
    "secure_boot_model": "Disabled",
    "cpu_model": "Skylake-Server-v4",
    "system_disk_bus": "virtio-blk",
    "nic": "virtio-net-pci",
    "smc": "isa-applesmc"
  },
  "bootloader": {
    "opencore_tag": "<pin>",
    "build_variant": "DEBUG",
    "config_sha256": "…",
    "drivers": ["OpenRuntime.efi", "OpenHfsPlus.efi",
                "ResetNvramEntry.efi", "ToggleSipEntry.efi"],
    "kexts": [
      { "name": "Lilu.kext",   "version": "<pin>", "sha256": "…" },
      { "name": "VirtualSMC.kext", "version": "<pin>", "sha256": "…" },
      { "name": "AppleMCEReporterDisabler.kext", "version": "<pin>", "sha256": "…" }
    ],
    "acpi": ["SSDT-EC.aml", "SSDT-USBX.aml"]
  },
  "firmware": {
    "ovmf_code_sha256": "…",
    "ovmf_vars_template_sha256": "…"
  },
  "installer_source": {
    "shared_support_dmg_sha256":
      "521B8029FB15F2421FFEBEA9F06BE1B147B0EA067AAA2BB90AF552D8AE5F6D25",
    "basesystem_dmg_sha256":
      "642E6148288527C51639D1B08C7F0B5A8CB4A68AEC2AC6DA3C78CF1723C5119A",
    "basesystem_dmg_bytes": 1464270504,
    "basesystem_origin":
      "AssetData/payloadv2/basesystem_patches/x86_64BaseSystem.dmg (BXDIFF50)",
    "reconstruct_tool": "ipsw 3.1.739 ota patch bxdiff"
  },
  "expected_runtime_config": {
    "csr_active_config": "0xfef",
    "boot_args": "amfi_get_out_of_my_way=1 -v keepsyms=1 debug=0xa serial=7 msgbuf=1048576"
  },
  "artifacts": [
    { "name": "opencore.img", "sha256": "…", "bytes": 67108864 },
    { "name": "BaseSystem.img", "sha256": "…", "bytes": 0 },
    { "name": "macos-26.7.2-25G325-golden.qcow2", "sha256": "…", "bytes": 0 },
    { "name": "macos-oc-25G325.iso", "sha256": "…", "md5": "…", "sha512": "…" }
  ]
}
```

`platform_profile` 这一段是本文对 `80` 的 `result.json` 的新增要求。理由：**一次实验失败时，"用的是哪个 SMBIOS、哪个盘总线、SIP 是什么值"这三个问题必须能从证据包里直接读出来**，而不是回去翻当时的脚本。这三项任一不同，结果就不可比。

---

## 9. 串口与 early boot 可观测性

`80` 第 1.4 节的结论是：串口是 panic 期唯一可靠的文本通道，而 Vultr 没有串口，所以 L1 的串口是整条管线唯一的内核级诊断手段。**E0-L1 失败时，能不能查清原因完全取决于这一节配得对不对。**

### 9.1 三段日志，三套互不相同的机制

从加电到桌面，日志分三段，每一段的输出机制与配置项都不同。混在一起谈是这件事最常见的出错方式。

| 段 | 产生者 | 输出机制 | 配置在哪 |
|---|---|---|---|
| ① 固件 + OpenCore | OVMF、OpenCore.efi | `EFI_SERIAL_IO_PROTOCOL` / `SerialPortLib`，写 I/O 端口 `0x3F8` | `Misc/Debug/Target` 的 `0x08` 位 + `Misc/Serial` |
| ② `boot.efi` | Apple 的 `boot.efi` | 由 OpenCore 代为落盘与转发 | `Misc/Debug/AppleDebug` |
| ③ XNU | 内核 `kprintf` / panic | 内核自己的 16550 驱动写 `0x3F8` | boot-args `debug=` 与 `serial=` |

**三段必须各自配通，少一段就会出现"日志突然断掉"而看不出断在哪。** 端到端验收见 9.6。

### 9.2 ① OpenCore 侧

```xml
<key>Misc</key>
<dict>
  <key>Debug</key>
  <dict>
    <key>Target</key>          <integer>75</integer>
    <key>DisplayLevel</key>    <integer>2147483714</integer>
    <key>AppleDebug</key>      <true/>
    <key>ApplePanic</key>      <true/>
    <key>DisableWatchDog</key> <true/>
    <key>DisplayDelay</key>    <integer>0</integer>
    <key>LogModules</key>      <string>*</string>
    <key>SysReport</key>       <false/>
  </dict>
  <key>Serial</key>
  <dict>
    <key>Init</key>     <true/>
    <key>Override</key> <false/>
  </dict>
</dict>
```

#### `Target = 75`

`KNOWN`，位定义来自 OpenCore 调试文档：

| 位 | 含义 |
|---|---|
| `0x01` | 启用日志 |
| `0x02` | 屏幕上的 debug 输出 |
| `0x04` | 写到 Data Hub |
| **`0x08`** | **启用串口日志** |
| `0x10` | 写 UEFI 变量 |
| `0x20` | 写非易失 UEFI 变量 |
| `0x40` | 写到文件 |

（转述自 <https://dortania.github.io/OpenCore-Install-Guide/troubleshooting/debug>。同一页给的常用组合是 `0x01 + 0x02 + 0x40 = 0x43 = 67`。）

本项目要 `0x01 + 0x02 + 0x08 + 0x40 = 0x4B = 75`：

- `0x01` 不开则其余位无意义。
- `0x02` 让日志同时上屏，这样 `80` 第 2.3 节的 `screendump` 与串口互为旁证。**代价是在 GOP 实现差的固件上会显著拖慢启动**（官方原话的要点），OVMF 上可接受。
- **`0x08` 是本节的核心。** 没有它串口上不会有任何 OpenCore 输出。
- `0x40` 把同一份日志写进 ESP 上的 `EFI/OC/opencore-<时间戳>.txt`。串口丢包或 chardev 配错时它是第二份证据。它要求 ESP 可写，所以 8.2.2 节把 EFI 镜像做成 64 MiB 而不是刚好够装。

有记录明确指出 `0x08` 正是配串口控制台时想要的那一位（转述自 <https://github.com/kholia/OSX-KVM/pull/252>）。

#### `DisplayLevel = 2147483714`

`KNOWN`，= `0x80000042` = `DEBUG_ERROR(0x80000000) | DEBUG_INFO(0x40) | DEBUG_WARN(0x02)`，是官方调试文档给出的推荐组合（同一来源）。

#### `Misc/Serial/Init = true`

`KNOWN`，`Misc/Serial` 的键是 `Init`、`Override`、`Custom`（见 `Docs/Sample.plist` 的 `Misc/Serial` 字典，<https://github.com/acidanthera/OpenCorePkg/blob/master/Docs/Sample.plist>）。

**命名变更要记一笔**：`Misc/Debug/SerialInit` 是 OpenCore 0.8.0 之前的键名，之后拆成了 `Misc/Serial/Init`（串口硬件初始化）与 `Misc/Serial/Override` + `Misc/Serial/Custom`（覆盖串口参数）。有记录说明 0.8.0 起默认不开串口日志，要让相关补丁正确生效必须启用新的 `Misc/Serial/Override` 并把 `Misc/Serial/Custom` 字典的键全部填好（转述自 <https://www.insanelymac.com/forum/topic/351477-how-to-opencore-079-080-differences/>）。按旧键名写会被 OpenCore 当成未知键而拒绝加载配置。

`Init = true` 让 OpenCore 自己去初始化 16550，不依赖固件已经初始化好。在 OVMF 上固件通常已经初始化过，但重复初始化无害，而漏初始化的表现是串口全静默。

#### `Override = false`，为什么不需要 `Custom`

`KNOWN`，`Misc/Serial/Custom` 的键与 failsafe 值（官方文档，<https://dortania.github.io/docs/release/Configuration.html>）：

| 键 | failsafe | 覆盖的 PCD |
|---|---:|---|
| `RegisterBase` | **`0x03F8`** | `PcdSerialRegisterBase` |
| `BaudRate` | `115200` | `PcdSerialBaudRate` |
| `ClockRate` | `1843200` | `PcdSerialClockRate` |
| `RegisterStride` | `1` | `PcdSerialRegisterStride` |
| `RegisterAccessWidth` | `8` | `PcdSerialRegisterAccessWidth` |
| `UseMmio` | `false` | `PcdSerialUseMmio` |
| `FifoControl` | `0x07` | `PcdSerialFifoControl` |
| `LineControl` | `0x07` | `PcdSerialLineControl` |
| `UseHardwareFlowControl` | `false` | `PcdSerialUseHardwareFlowControl` |
| `DetectCable` | `false` | `PcdSerialDetectCable` |
| `ExtendedTxFifoSize` | `64` | `PcdSerialExtendedTxFifoSize` |
| `PciDeviceInfo` | `0xFF` | `PcdSerialPciDeviceInfo`，最大 41 字节 |

**`RegisterBase` 的 failsafe 就是 `0x03F8`，`BaudRate` 的 failsafe 就是 `115200`，`UseMmio` 的 failsafe 就是 `false`。** QEMU 的 `-serial` 默认创建的是 ISA COM1，端口 `0x3F8`、IRQ 4。两边天然对上，所以 **`Override = false` 即可，不需要填 `Custom`。**

**什么时候才要填**：改用 `-device pci-serial` 的时候。那时串口在 PCI BAR 里，`RegisterBase` 变成 MMIO 地址、`UseMmio` 要置 `true`、`PciDeviceInfo` 要填，并且 `Kernel/Quirks/CustomPciSerialDevice` 也要开（第 6.5.3 节）。官方文档提示 `PciDeviceInfo` 可以用随包的 `FindSerialPort` 工具生成。**本项目不走 PCI 串口**，理由是 ISA COM1 的地址是固定常量，而 PCI BAR 地址随 PCI 枚举变化，后者在镜像里写不死。

### 9.3 ② `boot.efi` 侧

`AppleDebug = true`。`KNOWN`，官方调试文档对它的说明是提供更多与 `boot.efi` 相关的调试信息，并会把日志存盘（转述自 <https://dortania.github.io/OpenCore-Install-Guide/troubleshooting/debug>）。

`ApplePanic = true` 把内核 panic 存到 EFI 分区，同一来源并建议配合 boot-args 的 `keepsyms=1` 以尽量保留信息。

**这两项与 `80` 第 1.4 节的 panic 回捞流程互补**：`80` 的流程是"检测无响应 → 强制重启 → 等 SSH → 回捞 `/Library/Logs/DiagnosticReports/*.panic`"，前提是**根分区在 panic 后仍可挂载且 panic 报告确实写成功了**。`ApplePanic` 把 panic 写进 ESP（FAT32，OpenCore 自己能写），**绕开了根分区**。这给 L2 多了一条证据路径：即使系统盘坏了，只要能把 ESP 读出来就有 panic 文本。

`DisableWatchDog = true`。官方说明是关掉 UEFI watchdog,用于 OpenCore 在某些非关键环节上卡住时。对自动化的意义是：**卡住就卡住，别重启**。重启会让串口日志里出现第二次启动的输出，把现场冲掉。`80` 第 2.9 节的 `Detector` 靠超时判定无响应，由它来决定什么时候重启，而不是由固件 watchdog 决定。

`SysReport = false`，但**首次搭建时应该开一次**。它把 ACPI 表、SMBIOS 表、音频设备信息导到 ESP 上。这份导出是第 10 节首启探针的一个旁证来源，而且对 `11-KERNEL-DISPLAY.md` 判断 ACPI 设备树形状有直接价值。开一次、取走、关掉。

### 9.4 ③ XNU 侧：`debug` 与 `serial` 的实际语义

**本节修正 `70-BUILD-PACKAGE.md` 第 5.5 节的两个值。** `70` 第 5.5 节把这几项标为 `INFERRED` 并说"查清方法是在 L1 上逐项开关"。实际上 XNU 的源码是公开的，不需要靠实测反推。

#### `serial=` 的位域

`KNOWN`，来源：XNU 的 `osfmk/console/serial_protos.h`（<https://raw.githubusercontent.com/apple-oss-distributions/xnu/main/osfmk/console/serial_protos.h>）：

```c
#define SERIALMODE_OUTPUT     0x01
#define SERIALMODE_INPUT      0x02
#define SERIALMODE_SYNCDRAIN  0x04
#define SERIALMODE_BASE_TTY   0x08
#define SERIALMODE_NO_IOLOG   0x10
#define SERIALMODE_DKLOG      0x20
#define SERIALMODE_ON_DEMAND  0x40   /* 需要 SERIALMODE_INPUT，否则被忽略 */
#define SERIALMODE_NO_EXCLAVE 0x80
```

同一棵源码树的 `osfmk/console/serial_general.c` 里能看到 `SERIALMODE_INPUT` 与 `SERIALMODE_SYNCDRAIN` 的实际分支，证明这些名字是生效的而非历史遗留。

**版本对齐**：本项目基线的内核 `LC_SOURCE_VERSION` 是 `12377.161.15.701.48`（`KNOWN`，`MANIFEST.md` 第 5 节），而 Apple 公开的 XNU 源码 tag 是 `xnu-12377.121.6` 一系（`KNOWN`，<https://github.com/apple-oss-distributions/xnu/tags>）。**同一个 major train（12377），点版本略旧。** 所以这些位定义对 25G325 成立的置信度很高，但严格说是 `INFERRED`（差了几个点版本）。

| 取值 | 组合 | 适用 |
|---|---|---|
| `serial=1` | OUTPUT | 只要日志 |
| **`serial=3`**（`70` 第 5.5 节的值） | OUTPUT \| INPUT | 有交互控制台，**但没有 SYNCDRAIN，panic 时尾部消息可能丢** |
| `serial=5`（OpenCore FAQ 的值） | OUTPUT \| SYNCDRAIN | 日志完整，**但没有输入** |
| **`serial=7`（本文采用）** | OUTPUT \| INPUT \| SYNCDRAIN | 既有交互又不丢消息 |
| `serial=0xf` | 再加 BASE_TTY | 把串口当系统 base tty。`INFERRED`，未评估对 launchd 的影响，不用 |

**选 `serial=7` 的理由直接来自 `80` 的架构**：`80` 第 2.2 节的组件图里有一个 `SerialLine` 实现 `trait Shell`（"串口交互，仅 L1"）。那个实现需要**向串口写入**的能力，即 `SERIALMODE_INPUT`。而 panic 期不丢消息需要 `SERIALMODE_SYNCDRAIN`。两者都要，就是 `7`。

**代价**：`SYNCDRAIN` 让内核的串口写入变成同步的，启动会变慢。`INFERRED`，在 115200 波特下、`msgbuf=1048576` 的日志量级上，这个代价是秒级而不是分钟级。如果实测发现启动显著变慢，先去掉 `0x04` 而不是去掉 `0x02`（丢几行尾部日志比失去交互通道损失小）。

#### `debug=` 的位域，以及 `0x100` 已经作废

`KNOWN`，来源：XNU 的 `osfmk/kern/debug.h`（<https://raw.githubusercontent.com/apple-oss-distributions/xnu/main/osfmk/kern/debug.h>）的 `/* Debug boot-args */` 段：

```c
#define DB_HALT         0x1
#define DB_PRT          0x2      // enable always-on panic print to serial
#define DB_NMI          0x4
#define DB_KPRT         0x8
#define DB_KDB          0x10
#define DB_ARP          0x40
#define DB_KDP_BP_DIS   0x80
//#define DB_LOG_PI_SCRN  0x100 -- obsolete
#define DB_KDP_GETC_ENA 0x200
#define DB_KERN_DUMP_ON_PANIC  0x400
#define DB_KERN_DUMP_ON_NMI    0x800
#define DB_DBG_POST_CORE       0x1000
#define DB_PANICLOG_DUMP       0x2000
#define DB_REBOOT_POST_CORE    0x4000
#define DB_NMI_BTN_ENA         0x8000
#define DB_DISABLE_LOCAL_CORE  0x20000
#define DB_DISABLE_GZIP_CORE   0x40000
#define DB_DISABLE_CROSS_PANIC 0x80000
#define DB_REBOOT_ALWAYS       0x100000   /* Don't wait for debugger connection */
#define DB_DISABLE_STACKSHOT_TO_DISK 0x200000
```

**`0x100`（`DB_LOG_PI_SCRN`）在源码里被注释掉并标注 obsolete。** 社区长期流传的 `debug=0x100`（"panic 时输出文字而不是图形 panic 界面"）在这一代内核上**不再有作用**。`70` 第 5.5 节写的 `debug=0x100` 因此是一个空操作。

修正后的取值：

| 位 | 名称 | 本项目 | 理由 |
|---|---|---|---|
| `0x2` | `DB_PRT` | **要** | 源码注释原文的意思是"始终把 panic 打印到串口"。这正是 panic 期要的 |
| `0x8` | `DB_KPRT` | **要** | 让 `kprintf` 走串口。这是 early boot 日志的来源 |
| `0x100000` | `DB_REBOOT_ALWAYS` | **可选，无人值守时要** | 不等调试器连接。不设它的话 panic 后内核会停在等 KDP 的状态，自动化会一直超时 |
| `0x2000` | `DB_PANICLOG_DUMP` | 可选 | panic 时发 paniclog 而不是 core。没有 KDP 服务器接收时不影响 |
| `0x1`、`0x4`、`0x10`、`0x200`、`0x400`、`0x800` | halt / NMI / KDB / KDP getc / core dump | 不要 | 都需要外部调试器配合，本项目第一阶段没有 KDP 链路 |
| `0x100` | 已作废 | 不要 | 见上 |

**本项目的值**：

```text
交互排查用：  debug=0xa          # DB_PRT | DB_KPRT
无人值守用：  debug=0x10000a     # 再加 DB_REBOOT_ALWAYS
```

第 6.7 节的 `config.plist` 写 `debug=0xa`。`80` 的 harness 在无人值守批量跑时，用 `70` 第 5.3 节路径 B 临时改成 `0x10000a`，或者在镜像里做两个 `config.plist` 变体。

**对比**：OpenCore 官方 FAQ 给的组合是 `debug=0x108`、`serial=5`、`msgbuf=1048576`，并提示"在串口初始化之前就死掉时，参考 Sample.plist 里的补丁"（转述自 <https://dortania.github.io/docs/release/Configuration.html>）。`0x108` = `0x100`（已作废）+ `0x8`，所以实际生效的只有 `DB_KPRT`。本文的 `0xa` 多了一个 `DB_PRT`，是严格更强的组合。

#### 其余 boot-args

| 参数 | 作用 | 标签 | 本项目 |
|---|---|---|---|
| `amfi_get_out_of_my_way=1` | 关 AMFI 代码签名强制 | `KNOWN`（`00-OVERVIEW` 2.4、`70` 5.5） | **必需** |
| `-v` | verbose 启动 | `KNOWN` | **必需**，文字启动过程 |
| `keepsyms=1` | 保留内核符号，panic backtrace 可读 | `INFERRED`（`70` 5.5） | **必需** |
| `msgbuf=1048576` | 内核消息缓冲扩到 1 MiB | `INFERRED`，OpenCore FAQ 与本文一致采用这个值 | 建议。显示栈日志量大 |
| `kextlog=0xfff` | kext 加载详细日志 | `INFERRED`（`70` 5.5） | 排查 `70` 第 4.4 节问题时临时加 |
| `-no_compat_check` | 跳过机型兼容性检查 | `INFERRED`（本文 4.5） | **默认不加** |
| `setpowerstate_panic=0` | setPowerState 超时不 panic（仅 debug 内核） | `INFERRED` | 不用，改用 `Kernel/Quirks/PowerTimeoutKernelPanic`（6.5.3） |

### 9.5 RELEASE 内核的 early serial 补丁

有一类失败是"内核在串口初始化之前就死了"，表现是串口上有 OpenCore 的日志、有 `boot.efi` 的几行，然后完全静默。这时 boot-args 帮不上，因为解析 boot-args 本身发生在那之后。

`KNOWN`，OpenCore 的 `Docs/Sample.plist` 的 `Kernel/Patch` 数组里带四条现成补丁，全部 `Enabled = false`（来源 <https://github.com/acidanthera/OpenCorePkg/blob/master/Docs/Sample.plist>）：

| `Base` 符号 | `Comment` | `Arch` | `Replace`（base64） |
|---|---|---|---|
| `_disable_serial_output` | Enable early serial output on RELEASE kernel | `Any` | `AA==` |
| `_kernel_debug_string_early` | Send early prints to serial port | `x86_64` | `MfaKD4TJdQT/xrEKZrr9A+yoIHT7Zrr4A4jI7kj/x4X2dN/D` |
| `_panic` | Send panic string to serial port | `x86_64` | `MfaKD4TJdQT/xrEKZrr9A+yoIHT7Zrr4A4jI7kj/x4X2dN/r/g==` |
| `_vstart` | Print K and dead loop | `Any` | （见 Sample.plist） |

**启用顺序与用法**：

1. 先只启用 `_disable_serial_output`。它把一个控制变量置零，是四条里最轻的一条（`Replace` 只有一个 `0x00` 字节），`Identifier = kernel`、`Count = 1`、`Find` 为空（按符号定位而非按字节查找）。它的作用是让 RELEASE 内核不要抑制早期串口输出。多数情况下这一条就够。
2. 还是静默，再加 `_kernel_debug_string_early`。它把那个函数整体替换成一段直接写 `0x3F8` 的代码。
3. panic 文本不出现在串口上，加 `_panic`。
4. **`_vstart` 是最后手段**，它让内核在入口处打一个 `K` 然后死循环。它只回答一个问题："内核有没有被执行到。" 回答完就要关掉。

照抄方式（把这一条加进 6.1 脚本的 `c['Kernel']['Patch']`）：

```python
c['Kernel']['Patch'] = [
    {'Arch': 'Any', 'Base': '_disable_serial_output',
     'Comment': 'Enable early serial output on RELEASE kernel',
     'Count': 1, 'Enabled': False,          # 默认关，只在串口静默时打开
     'Find': b'', 'Identifier': 'kernel', 'Limit': 0, 'Mask': b'',
     'MaxKernel': '', 'MinKernel': '',
     'Replace': bytes([0x00]), 'ReplaceMask': b'', 'Skip': 0},
]
```

**这些补丁按符号名定位，而符号名跨版本可能变。** `INFERRED`：`_disable_serial_output` 在 25G325 的内核里是否存在未验证。查清方法：仓库里已有 `analysis/binaries/macos26-25G325-x86_64/kernel/kernel.x86_64`（19,008,056 字节，`LC_UUID` `E514CEBA-9206-34D5-86C2-64E880FDDA2B`），直接在它的符号表里查这四个名字。登记为 I-015。这是一个不需要任何实验、现在就能做掉的检查。

### 9.6 QEMU 侧与端到端验收

`80` 第 2.2 节给的 chardev 配置加上 `logappend`：

```bash
-chardev socket,id=ser0,host=127.0.0.1,port=4555,server=on,wait=off,logfile=/run/harness/serial-$EXP.log,logappend=on \
-serial chardev:ser0
```

**端到端验收：一份合格的 `serial-$EXP.log` 必须按顺序出现四类行。** 这是本节的判据，`80` 的 `Detector` 可以直接按它做阶段判定：

| 阶段 | 期望在日志里看到 | 看不到说明 |
|---|---|---|
| ① OpenCore 启动 | `OC:` 前缀的行，含 `OC: OpenCore DBG-<ver>` 与 `OCABC:` 开头的内存图行 | `Target` 的 `0x08` 位没开，或 chardev 没通 |
| ①b 内存图能力 | `OCABC: MAT support is 1` 或 `0` | 这一行决定 6.3 节 `EnableWriteUnprotector` 与 `RebuildAppleMemoryMap` 该用哪个（I-004） |
| ①c 条目扫描 | `OCB:` 开头的行，列出扫到的卷与 `.contentDetails` 名字 | `ScanPolicy` 挡住了；或 `OpenHfsPlus.efi` 没加载 |
| ② boot.efi | OpenCore 转发的 Apple boot 日志 | `AppleDebug` 没开 |
| ③ XNU early | `Darwin Kernel Version 2x.x.x` 一行，以及之后的 `AppleACPIPlatform`、`AppleAHCI`/`IONVMeController`/`AppleVirtIO*` 匹配行 | `debug` 的 `0x8` 位或 `serial` 的 `0x1` 位没设；若连 `Darwin Kernel Version` 都没有，走 9.5 的补丁 |
| ③b 根设备 | `BSD root: diskXsY` 一行 | **这一行是第 7 节成败的直接判据。** 没有它就是 macOS 没认出启动盘 |

一条实用的采集约定：**把这六个标记做成 `Detector` 的六个正则，并在 `result.json` 里记录每个标记首次出现的时间戳**。失败时"走到了哪一步"就是一次查表，不需要人读日志。这比在 `80` 第 2.9 节的"无输出检测"上做超时判断精确得多。

---

## 10. 首启探针

guest 第一次起来之后要立刻采集的东西。目标是**用一次 SSH 会话关掉 `80` 第 1.5 节与第 4.3 节里尽可能多的 `BLOCKED` / `INFERRED` 项**。

### 10.1 探针脚本

```bash
#!/usr/bin/env bash
# /usr/local/bin/first-boot-probe.sh
# 首启探针。以普通用户运行，需要 sudo 的部分单独标注。
# 输出：一个目录，每个 .txt 对应一类证据；再加一个 summary.json
set -u
OUT="${1:-/tmp/probe-$(date -u +%Y%m%dT%H%M%SZ)}"
mkdir -p "$OUT"
run() { echo "### $*" ; "$@" 2>&1 ; echo ; }

# ========== A. 身份与基线：这是哪个系统、哪个镜像 ==========
{
  run sw_vers
  run uname -a
  run sysctl -n kern.osproductversion kern.osversion kern.osrelease kern.version
  run sysctl -n hw.model machdep.cpu.brand_string
  run sysctl -n hw.ncpu hw.physicalcpu hw.logicalcpu hw.memsize
  run sysctl -n machdep.cpu.features machdep.cpu.leaf7_features machdep.cpu.extfeatures
  run sysctl -n kern.hv_vmm_present
} > "$OUT/A-identity.txt"

# ========== B. 平台与 SMBIOS：board-id 是否真的生效 ==========
{
  run ioreg -l -p IODeviceTree -d 2 -w 0
  echo "### board-id (权威读法)"
  ioreg -arc IOPlatformExpertDevice -d 1 \
    | plutil -extract 0.board-id raw -o - - 2>&1
  echo
  echo "### model / product-name"
  ioreg -arc IOPlatformExpertDevice -d 1 | plutil -p - \
    | grep -Ei 'board-id|model|product-name|manufacturer|version|IOPlatformUUID|IOPlatformSerialNumber'
  echo
  run system_profiler SPHardwareDataType
} > "$OUT/B-platform.txt"

# ========== C. SIP / AMFI：70 第 5.4 节的前三项 ==========
{
  run csrutil status
  run csrutil authenticated-root status
  run nvram csr-active-config
  run nvram boot-args
  run nvram -p
  echo "### OpenCore 自述（ExposeSensitiveData 的产物，见 6.6.2）"
  run nvram 4D1FDA02-38C7-4A6A-9CC6-4BCCA8B30102:opencore-version
  run nvram 4D1FDA02-38C7-4A6A-9CC6-4BCCA8B30102:boot-path
  run nvram 4D1FDA02-38C7-4A6A-9CC6-4BCCA8B30102:oem-product
  run nvram 4D1FDA02-38C7-4A6A-9CC6-4BCCA8B30102:oem-board
} > "$OUT/C-sip.txt"

# ========== D. 存储：第 7.4 节 ==========
{
  run bash /usr/local/bin/probe-storage.sh
  run diskutil list
  run diskutil apfs list
  run mount
} > "$OUT/D-storage.txt"

# ========== E. 网络 ==========
{
  run ioreg -r -c IOEthernetController -l -w 0
  run networksetup -listallhardwareports
  run ifconfig -a
  run netstat -rn
  run system_profiler SPNetworkDataType
} > "$OUT/E-network.txt"

# ========== F. 图形栈现状：本项目的起点基线 ==========
{
  echo "### 有没有任何 IOAccelerator"
  run ioreg -r -c IOAccelerator -l -w 0
  echo "### 有没有任何 framebuffer"
  run ioreg -r -c IOFramebuffer -l -w 0
  run ioreg -r -c IOMobileFramebuffer -l -w 0
  echo "### 谁接了 QEMU 的显示设备（见 6.10 的 I-010）"
  run ioreg -r -c AppleVirtualGraphics -l -w 0
  run ioreg -r -c IOBootFramebuffer -l -w 0
  run ioreg -r -c IONDRVFramebuffer -l -w 0
  echo "### AGDP / GPUWrangler 是否实例化（见 4.3 门 2）"
  run ioreg -r -c AppleGraphicsDevicePolicy -l -w 0
  run ioreg -r -c AppleGPUWrangler -l -w 0
  run ioreg -r -c AppleGraphicsDeviceControl -l -w 0
  echo "### Metal 侧"
  run system_profiler SPDisplaysDataType
} > "$OUT/F-graphics.txt"

# ========== G. kext 现状 ==========
{
  run kmutil showloaded
  run kextstat
  echo "### 关键驱动是否加载（逐个对照本文第 3 节）"
  for b in com.apple.driver.AppleVirtIO com.apple.iokit.IONVMeFamily \
           com.apple.driver.AppleAHCIPort com.apple.driver.AppleVmxnet3Ethernet \
           com.apple.driver.ApplePVPanic com.apple.driver.AppleIntelMCEReporter \
           com.apple.driver.AppleGraphicsDevicePolicy com.apple.driver.AppleSMC \
           as.vit9696.VirtualSMC as.vit9696.Lilu ; do
    printf '%-48s ' "$b"
    kmutil showloaded --bundle-identifier "$b" >/dev/null 2>&1 \
      && echo LOADED || echo "not-loaded"
  done
  echo
  run kmutil showloaded --collection-kind auxiliary
  run kmutil check
} > "$OUT/G-kext.txt"

# ========== H. ACPI：SSDT 是否生效（见 6.2） ==========
{
  echo "### EC 设备（SSDT-EC 的目的）"
  run ioreg -r -c AppleACPIEC -l -w 0
  run ioreg -rn EC -l -w 0
  echo "### USBX（SSDT-USBX 的目的）"
  run ioreg -rn USBX -l -w 0
  run ioreg -r -c AppleACPIPlatformExpert -d 1 -l -w 0
} > "$OUT/H-acpi.txt"

# ========== I. panic / 崩溃报告的位置与格式（80 的 H-009） ==========
{
  run ls -la /Library/Logs/DiagnosticReports/
  run ls -la "$HOME/Library/Logs/DiagnosticReports/"
  run ls -la /System/Volumes/Preboot
} > "$OUT/I-reports.txt"

# ========== J. 串口在 guest 内的呈现（见 9.4 的 BASE_TTY 讨论） ==========
{
  run ls -la /dev/tty.* /dev/cu.*
  run ioreg -r -c IOSerialBSDClient -l -w 0
  run ioreg -r -c com_apple_driver_16X50PCI -l -w 0
} > "$OUT/J-serial.txt"

# ========== 汇总 ==========
py3=$(command -v python3 || echo /usr/bin/python3)
"$py3" - "$OUT" <<'PY'
import json, os, re, subprocess, sys
out = sys.argv[1]
def sh(c):
    try: return subprocess.run(c, shell=True, capture_output=True, text=True).stdout.strip()
    except Exception: return ""
def has(cls):
    return bool(sh(f'ioreg -r -c {cls} -d 1 -w 0').strip())
s = {
  "os_build":      sh("sysctl -n kern.osversion"),
  "os_version":    sh("sysctl -n kern.osproductversion"),
  "hw_model":      sh("sysctl -n hw.model"),
  "cpu":           sh("sysctl -n machdep.cpu.brand_string"),
  "ncpu":          sh("sysctl -n hw.ncpu"),
  "memsize":       sh("sysctl -n hw.memsize"),
  "hv_vmm_present":sh("sysctl -n kern.hv_vmm_present"),
  "board_id":      sh("ioreg -arc IOPlatformExpertDevice -d 1 "
                      "| plutil -extract 0.board-id raw -o - -"),
  "csr_text":      sh("csrutil status"),
  "csr_nvram":     sh("nvram csr-active-config"),
  "boot_args":     sh("nvram boot-args"),
  "opencore_version": sh("nvram 4D1FDA02-38C7-4A6A-9CC6-4BCCA8B30102:opencore-version"),
  "storage_driver": {
      "AppleAHCI":                     has("AppleAHCI"),
      "IONVMeController":              has("IONVMeController"),
      "AppleVirtIOPCITransport":       has("AppleVirtIOPCITransport"),
      "AppleVirtIOBlockStorageDevice": has("AppleVirtIOBlockStorageDevice"),
  },
  "graphics": {
      "IOAccelerator":               has("IOAccelerator"),
      "IOFramebuffer":               has("IOFramebuffer"),
      "AppleVirtualGraphics":        has("AppleVirtualGraphics"),
      "AppleGraphicsDevicePolicy":   has("AppleGraphicsDevicePolicy"),
      "AppleGPUWrangler":            has("AppleGPUWrangler"),
  },
  "acpi": { "AppleACPIEC": has("AppleACPIEC") },
  "mce":  { "AppleIntelMCEReporter": has("AppleIntelMCEReporter") },
  "smc":  { "AppleSMC": has("AppleSMC") },
}
json.dump(s, open(os.path.join(out, "summary.json"), "w"), indent=2)
print(json.dumps(s, indent=2))
PY

echo "probe output: $OUT"
```

**需要 `sudo` 的补充项**（单独跑，因为它们会改状态或需要权限）：

```bash
# 70 第 5.4 节第 3 项：内核实际生效的 SIP 位域（权威检查）
# 需要 clang。guest 上没有 Xcode CLT 时跳过，用 nvram 值 + csrutil 文本代替
sudo /usr/local/bin/sipcheck     # 由 70 第 5.4 节的 sipcheck.c 编出

# ACPI / SMBIOS 原表（与 OpenCore 的 SysReport 互为旁证）
sudo ioreg -l -p IOACPIPlane -w 0 > "$OUT/H-acpi-plane.txt"

# aux collection 状态
sudo kmutil dumpstate > "$OUT/G-kmutil-dumpstate.txt" 2>&1
sudo kmutil log        > "$OUT/G-kmutil-log.txt"        2>&1
```

### 10.2 每条命令关闭哪个编号

| 命令 / 字段 | 关闭或推进的编号 | 判据 |
|---|---|---|
| `sysctl -n kern.osversion` | 全部实验的前置校验 | 必须是 `25G325`。不是就说明装的不是基线版本，整个实验作废 |
| `ioreg -arc IOPlatformExpertDevice \| plutil -extract 0.board-id` | 本文 **I-002** | 必须是 `Mac-27AD2F918AE68F61`。不是说明 `PlatformInfo` 没生效 |
| `sysctl -n hw.model` | 本文 I-002 的旁证 | 应为 `MacPro7,1` |
| `sysctl -n kern.hv_vmm_present` | 本文 **I-016** | 为 `1` 说明 macOS 自知在虚机里。这一位会影响软件更新等路径的行为 |
| `csrutil status` + `nvram csr-active-config` + `sipcheck` | `70` 的 **P-011**，`70` 第 5.4 节第 1 到 3 项 | `csr-active-config` 必须是 `%ef%0f%00%00` |
| `nvram boot-args` | 本文 **I-017** | 必须与 6.7 节写的那一串逐字相同。不同说明 `Delete` 段没起作用 |
| `nvram 4D1FDA02-…:opencore-version` | 镜像溯源 | 与 `image-manifest.json` 的 `bootloader.opencore_tag` 对照 |
| `probe-storage.sh` 第 4 步的五个类名 | `80` 的 **H-001**（L2）；本文 **I-001**（L1 三候选） | 按 7.4 节的判定表读 |
| `ioreg -r -c AppleVirtIOBlockStorageDevice` | 本文 **I-003** | 有实例就证明 3.2 节第 2 点的推断成立 |
| `ioreg -r -c IOEthernetController` + `networksetup -listallhardwareports` | `80` 的 **H-001**（网卡部分） | `IOClass` 是 `AppleVirtIONetwork` 还是 `AppleVMXNETController` |
| `diskutil list` 在 Block Storage `attach` 之后 | `80` 的 **H-004** | 新卷出现即成立 |
| `ioreg -r -c AppleACPIEC` / `ioreg -rn EC` | 本文 **I-018** | 有 EC 设备说明 `SSDT-EC.aml` 是对的那一版 |
| `ioreg -r -c AppleSMC` 的实例数 | 本文 **I-006** | 大于 1 或 `VirtualSMC` 报错，就关掉 `VirtualSMC` |
| `ioreg -r -c AppleIntelMCEReporter` | 本文 **I-019** | **应为 0 个实例。** 有实例说明 `AppleMCEReporterDisabler` 没生效 |
| `ioreg -r -c AppleGraphicsDevicePolicy` | 本文 4.3 门 2 的验证 | 实例存在但不该施加策略（board-id 不在 `ConfigMap`）。记录它的属性作为基线 |
| `ioreg -r -c AppleVirtualGraphics` / `IOBootFramebuffer` / `IONDRVFramebuffer` | 本文 **I-010** | 谁接了 QEMU 的 VGA。这决定我们的 framebuffer provider 要不要和它竞争 |
| `ioreg -r -c IOAccelerator` + `IOFramebuffer`（本项目组件未安装时） | `10`/`11` 分册的起点基线 | **期望都是 0 个实例。** 这是"干净"状态的定义，`80` 第 2.4.1 节的 golden snapshot 要在这个状态下制作 |
| `system_profiler SPDisplaysDataType` | `60-CAPABILITY-MATRIX.md` 的基线 | 记录未装本项目时 macOS 对显示的自述 |
| `kmutil showloaded` 的逐项对照 | 本文第 3 节全部结论的运行确认 | 把 `KNOWN`（在 KC 里）升级为真正加载 |
| `ls -la /Library/Logs/DiagnosticReports/` | `80` 的 **H-009** | 文件后缀是 `.ips` 还是 `.crash` |
| `ls /dev/tty.* /dev/cu.*` + `ioreg -r -c IOSerialBSDClient` | 本文 **I-020** | 串口在 guest 内是否有 BSD 节点。有的话 `80` 的 `SerialLine` 可以双向用 |
| `kmutil check` / `dumpstate` | `70` 的 **P-007** | aux collection 能否在无 KDK 下构建 |

**一条纪律**：这个脚本的输出要**原样**进 `80` 第 2.10 节的归档，不要在 guest 内做筛选。`summary.json` 是给 `Detector` 用的结构化摘要，`*.txt` 是给人和模型事后查的原始证据。两者都留。

---

## 11. 未解决项清单

编号 `I-` 代表 image。与 `70` 的 `P-`、`80` 的 `H-` 并列，互不重叠。

"查清方法"一列区分三类成本：**现在就能做**（不需要任何实验，只需读现有样本或跑一条命令）、**E0-L1**（需要本地起一次虚机）、**E0-L2**（需要花钱开 Vultr 实例）。

| 编号 | 事项 | 标签 | 查清方法 | 成本 | 阻塞什么 |
|---|---|---|---|---|---|
| **I-015** | `_disable_serial_output`、`_kernel_debug_string_early`、`_panic` 三个符号是否存在于 25G325 的 x86_64 内核 | `INFERRED` | 在仓库已有的 `analysis/binaries/macos26-25G325-x86_64/kernel/kernel.x86_64`（`LC_UUID` `E514CEBA-9206-34D5-86C2-64E880FDDA2B`）的符号表里直接查这三个名字。用 `tools/macho.py` 读 `LC_SYMTAB` 即可 | **现在就能做** | 第 9.5 节的 early serial 兜底手段是否可用。串口静默时这是唯一的下一步 |
| ~~**I-022**~~ | 还原出的 `x86_64BaseSystem.dmg`（1,464,270,504 字节）是带 GPT 的磁盘镜像还是裸卷镜像；卷是 APFS 还是 HFS+ | **`TESTED`，已关闭** | **`32-COMPILER-PLUGIN.md` 第 3 节已经实跑过**：`ipsw disk dmg -p 3` 取出其 **`Apple_APFS`** 分区原始镜像，**1,396,506,624 字节**。即它**是带 GPT 的磁盘镜像**（有第 3 个分区），**那个分区是 Apple_APFS**。`32` 第 1 节的样本表把 `S-BASESYS` 的容器类型记作 `UDIF / Apple_APFS`，两处一致 | 已完成 | 第 8.2.3、8.3.4 节的分区类型 GUID 定为 `7C3457EF-0000-11AA-AA11-00306543ECAC`；写进 `76` 的 p2 时要取**第 3 个分区**的内容，不是整个 DMG。连带关掉 `76` 的 `L-007` |
| **I-011** | `Mac-112818653D3AABFC` 对应哪个机型 | `BLOCKED` | 三条路：抽取 `X86PlatformPlugin.kext/Contents/Resources/Mac-112818653D3AABFC.plist`（17,436 字节，`payload.050`）看 CPU 与平台参数；在 `payloadv2-full-index.tsv.zip` 里检索该 board-id 的其它配套资源（`System/Library/Audio/Tunings/` 下有没有它，有则是带扬声器的整机）；查 OpenCorePkg `AppleModels` 是否有新增条目 | **现在就能做** | 只影响完整性。本项目不用它（4.2 节） |
| **I-012** | Lavapipe 在 AVX-512 可用的 vCPU 上是否正常；是否需要在 `-cpu` 里减掉 `avx512*` | `INFERRED` | `70` 的 P-001 通过之后，在 `Skylake-Server-v4` 与 `Skylake-Client-v4` 两种 vCPU 下各跑一次 `metal-probe --offscreen-render`，比对 | E0-L1 之后 | 第 5.2 节的 CPU 型号选择；`70` 第 3.4 节的 LLVM 后端行为 |
| **I-001** | AHCI / NVMe / virtio-blk 三个候选在 L1 上各自能否让 macOS 26 看到并从中启动 | `INFERRED`（7.2 节） | 用 7.1 节三段命令行各启一次，每次跑 7.4 节的 `probe-storage.sh`，并检查 9.6 节的 `BSD root: diskXsY` 标记 | **E0-L1**，三次启动 | 第 7 节的主路径选择；`80` 第 2.4.2 节 golden snapshot 的设备模型 |
| **I-003** | `AppleVirtIOPCITransport` 从哪里读出 VirtIO 设备类型；legacy（PCI id `0x1001`）与 modern（`0x1042`）是否都能归一化成类型 2 | `INFERRED`（3.2 节第 2 点） | 先按 7.1 候选 C 用 `disable-legacy=on` 启一次；成功后再用 `disable-legacy=off,disable-modern=on` 启一次，对比 `ioreg -r -c AppleVirtIOPCITransport -l` 上的属性。若两者都不行，反编译 `AppleVirtIO` 的 x86_64 代码（需先从 Boot KC 用 `tools/kc.py` 重建，`vm=0xffffff8001ed8000`，`uuid=82ABA0E4-1BDD-3DDD-A89A-A077B24B8826`） | E0-L1 | 第 7 节候选 C 的可行性；第 8.3.5 节路 2 的可行性 |
| **I-004** | OVMF 是否提供 memory attributes table（MAT）；因此该用 `EnableWriteUnprotector` 还是 `RebuildAppleMemoryMap` | `INFERRED`（6.3 节） | 看串口日志里 `OCABC: MAT support is 1/0` 那一行（9.6 节阶段 ①b）。为 1 则改用 `RebuildAppleMemoryMap = true` + `EnableWriteUnprotector = false` | E0-L1，零额外成本（启动日志里就有） | 第 6.3 节 Booter quirk 的正确组合。配错的表现是早期 panic 或 NVRAM 写入失败 |
| **I-023** | `Booter/Quirks/FixupAppleEfiImages` 在本项目用的 OVMF 构建上是否真的必需 | `INFERRED`（6.3 节） | 分别以 `true` 与 `false` 各启一次。官方文档说明它在严格 PE loader 上、且 `SecureBootModel = Disabled` 时为新版 macOS 所必需，而"严格"取决于 OVMF 是否由 audk 编译 | E0-L1，两次启动 | 第 6.3 节。为 `false` 可行则少一个会改写内存中镜像的环节 |
| **I-019** | `AppleMCEReporterDisabler.kext` 在 25G325 上是否真的挡住了 `AppleIntelMCEReporter` | `INFERRED`（4.3 门 1） | 首启探针 G 段与 F 段：`ioreg -r -c AppleIntelMCEReporter` 必须是 0 个实例，`kmutil showloaded --bundle-identifier com.apple.driver.AppleIntelMCEReporter` 必须 not-loaded | E0-L1 | `MacPro7,1` SMBIOS 能否用。失败则退到 `MacBookPro16,1`（4.4 节备选） |
| **I-002** | `PlatformInfo/Automatic = true` + `SystemProductName = MacPro7,1` 是否真的产生了 board-id `Mac-27AD2F918AE68F61` | `INFERRED` | 首启探针 B 段：`ioreg -arc IOPlatformExpertDevice -d 1 \| plutil -extract 0.board-id raw -o - -`。不符则检查 `UpdateSMBIOSMode`，并临时加 `-no_compat_check`（4.5 节）以区分"board-id 没生效"与"board-id 生效但被拒" | E0-L1 | 第 4 节全部结论；安装器会不会拒绝 |
| **I-006** | `VirtualSMC.kext` 与 QEMU 的 `isa-applesmc` 并存是否冲突 | `INFERRED`（6.5.1 节） | 首启探针 F/G 段：`ioreg -r -c AppleSMC -d 1` 的实例数；`kmutil showloaded --bundle-identifier as.vit9696.VirtualSMC`。实例数 > 1 或 VirtualSMC 未加载，就把它 `Enabled = false` | E0-L1 | 第 6.5.1 节的 kext 最小集。影响每次实验要注入几个 kext |
| **I-018** | 用的是哪一版 `SSDT-EC.aml`（假 EC 还是 EC 重命名），以及它在 25G325 + q35 上是否产生了 EC 设备 | `INFERRED`（6.2 节） | 首启探针 H 段：`ioreg -r -c AppleACPIEC -l` 与 `ioreg -rn EC -l` 至少一个要有结果。同时用 `Misc/Debug/SysReport = true` 导出一次 ACPI 表自查 | E0-L1 | 第 6.2 节。EC 缺失的后果是电源管理与若干 Apple 驱动的 `start` 失败，而症状不指向 EC |
| **I-010** | QEMU 的 `-device VGA` 被 macOS 的哪个驱动接住（`AppleVirtualGraphics` / `IOBootFramebuffer` / `IONDRVFramebuffer` / 无） | `BLOCKED` | 首启探针 F 段三条 `ioreg -r -c` 命令。若 `AppleVirtualGraphics` 接住了，进一步读它的 `IOKitPersonalities`（从 System KC 重建该 kext，`vm=0x14a24000`，`uuid=E80D3753-B895-3248-9480-65B9E31A4E37`） | E0-L1 | **这是 `11-KERNEL-DISPLAY.md` 的直接输入**：我们的 framebuffer provider 要不要和一个已存在的 provider 竞争，以及 `IOProbeScore` 该设多少 |
| **I-005** | `DeviceProperties` 是否需要向本项目的 provider 注入属性 | `INFERRED`（6.4 节） | 依赖 `11-KERNEL-DISPLAY.md` 先确定 provider 的 PCI/ACPI 路径。在那之前保持全空 | 归 `11` 分册 | 第 6.4 节 |
| **I-009** | `ApplePVPanic` 的 `IOPlatformPanicAction = 0` 对应什么行为；host 侧 QMP 能否收到 `GUEST_PANICKED` | `INFERRED`（3.6 节） | 加 `-device pvpanic`，监听 QMP 事件流，然后用 `sudo dtrace -w -n "BEGIN{panic();}"`（需 SIP 的 `0x20` 位，`0xFEF` 已含）主动触发 | E0-L1 | `80` 的 H-010 与第 2.9 节 `Detector` 的 panic 判定精度 |
| **I-020** | 串口在 guest 内是否有 BSD 节点（`/dev/tty.*`），`80` 的 `SerialLine` 能否双向使用 | `INFERRED`（9.4 节） | 首启探针 J 段。无节点时考虑把 `serial=7` 改成 `serial=0xf`（加 `SERIALMODE_BASE_TTY`）再试，但要评估对 launchd 的影响 | E0-L1 | `80` 第 2.2 节 `SerialLine` 实现的可行性 |
| **I-017** | `NVRAM/Delete` 段是否真的让 `boot-args` 与 `csr-active-config` 每次启动都被重置为配置里的值 | `INFERRED`（6.7 节） | 首启探针 C 段读一次；然后在 guest 内 `sudo nvram boot-args="bogus"` 并重启，再读一次。两次必须相同 | E0-L1 | `70` 第 5.3 节路径 A 的有效性。这是"SIP 真的关了吗"的根因之一 |
| **I-016** | `kern.hv_vmm_present` 的值，以及它是否影响安装器与软件更新路径 | `INFERRED` | 首启探针 A 段。为 `1` 时留意 `softwareupdate` 行为差异 | E0-L1 | 只影响理解，不阻塞 E0 |
| **I-007** | 若必须走第 2.4 节路 B（`com.apple.recovery.boot`），缺 chunklist 下 `DmgLoading = Any` 能否加载我们的 BaseSystem | `INFERRED`（6.6.3 节） | 把 BaseSystem.dmg 放进 `EFI` 分区的 `com.apple.recovery.boot/`，`DmgLoading` 改 `Any`，看 OpenCore picker 里是否出现带 `(dmg)` 后缀的条目 | E0-L1 | 路 A 失败时的备选路径 |
| **I-021** | 8.3.3 节的 hybrid ISO 里，固件能否从 ISO9660/UDF 文件树读出 `com.apple.recovery.boot/BaseSystem.dmg` | `INFERRED` | 在 L1 上把那张 ISO 以 `-device ide-cd` 挂上（而不是 `ide-hd`），看 picker 里是否出现 dmg 条目。失败则改走 8.3.4 的配方 B | E0-L1 | 第 8.3.3 节配方 A 的可行性。配方 B 不依赖它 |
| **I-008** | QEMU 的 `-device mptsas1068` 能否被 `AppleLSIFusionMPT` + `IOSCSIParallelFamily` 接住 | `INFERRED`（3.4、7.5 节） | 加一块 `-device mptsas1068` 挂的盘，看 `ioreg -r -c AppleLSIFusionMPT -d 1` 与 `diskutil list` | E0-L1，低优先级 | 只在 Vultr 的盘既不是 AHCI/NVMe/virtio 时才需要 |
| **I-013** | 25G325 的 cryptex 在 KVM guest 内是否正常挂载；是否需要 `CryptexFixup.kext` | `INFERRED`（6.5.1 节） | 首启后 `mount \| grep -i cryptex` 与 `ls /System/Volumes/Preboot`；`log show --predicate 'subsystem == "com.apple.cryptex"'` | E0-L1 | 第 6.5.1 节的 kext 集。失败的表现是系统起不来或 `/System/Cryptexes` 为空 |
| **I-014** | Vultr `snapshots/create-from-url` 的体积上限、接受的镜像格式（raw / 是否接受压缩） | `BLOCKED` | 查 Vultr 官方快照文档与 `govultr/snapshot.go` 的 `SnapshotURLReq` 字段；或直接上传一个小 raw 试一次 | 文档可**现在就查**，行为需 **E0-L2** | 第 8.3.4 节配方 B 的可行性。它是 Vultr 交付的首选路径 |
| **I-024** | Vultr 的固件是否拾取我们镜像里的 `EFI/BOOT/BOOTX64.EFI`（即能否自定义引导链） | `BLOCKED`，与 `80` 第 1.5 节同一行 | **E0-L2 本体。** 按 8.3.4 节的 API 序列建实例，在网页控制台里看有没有 OpenCore picker | **E0-L2** | **整个 L2 层。** 修正后这是"Vultr 上跑不起来"的最大单点原因（7.5 节） |

**优先级：前三项（I-015、I-022、I-011）现在就能做完，不需要任何实验。** 其中 I-015 与 I-022 直接决定第 8、9 两节的脚本能不能跑通，应当在写任何代码之前先做掉。

---

## 12. 相关分册

- **`70-BUILD-PACKAGE.md`**：第 5 节是本文第 6.7 节 `NVRAM` 段的唯一来源，`csr-active-config = 0xFEF` 与 `Add`/`Delete` 语义以它为准。**本文修正了它第 5.5 节的两个 boot-arg 值**（`debug` 由 `0x100` 改 `0xa`，`serial` 由 `3` 改 `7`），依据见本文 9.4，建议把 `70` 的 P-009 标记为已由源码关闭。本文第 8.5 节的 `image-manifest.json` 与它第 7 节的 `MANIFEST.json` 并列，两者合起来描述一次实验的全部输入。
- **`80-TEST-HARNESS.md`**：本文整篇服务于它第 4.1 节的 E0-L1。**本文修正了它第 1.5 节与第 5.1 节的事实前提**（macOS VirtIO 块设备与网卡驱动的存在性），并推进了它的 H-010。本文第 8.2.4 节的 QEMU 命令行取代它第 2.4.2 节步骤 2 的那一段；第 9.6 节的六个日志标记可直接做成它第 2.9 节 `Detector` 的阶段判定;第 10 节的探针是它第 2.8 节 `collect` 清单在首启场景下的具体化。本文第 8.5 节要求它的 `result.json` 新增 `platform_profile` 一段。
- **`11-KERNEL-DISPLAY.md`**：本文 I-010（谁接住 QEMU 的显示设备）与 4.3 门 2（`AppleGraphicsDevicePolicy` 的 `ConfigMap`）是它的直接输入。本文第 6.10 节排除 WhateverGreen 的决定，意味着"让屏幕亮起来"这件事完全由它负责。
- **`10-KERNEL-ACCELERATOR.md`**：本文第 10 节探针 F 段里"未装本项目组件时 `IOAccelerator` 为 0 个实例"是它的起点基线。
- **`90-EVIDENCE-INDEX.md`**：本文第 3、4 节新取得的证据（两个 KC 的 fileset 清单、`PlatformSupport.plist`、`AppleVirtIO` / `AppleVirtIOStorage` / `IONVMeFamily` / `AppleAHCIPort` / `AppleVmxnet3Ethernet` / `ApplePVPanic` / `AppleIntelMCEReporter` / `AppleGraphicsDevicePolicy` / `AppleGPUWrangler` / `AppleSMBIOS` / `AppleHV` / `Apple16X50Serial` / `AppleACPIPlatform` / `AppleBCM5701Ethernet` 共 15 个 `Info.plist`）应登记进它的样本索引。全部取自 `payload.050`，抽取命令见本文 4.1 节。
- **`00-OVERVIEW.md` 第 7 节**：本文的标签用法遵从它的四级规则。特别是第 3 节的全部"存在"结论都建立在 x86_64 kernel collection 的 fileset 条目上，而不是跨架构共用的 `Info.plist`，这是它"标注证据的架构"这条规则在本场景下的落地方式。
