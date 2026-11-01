# 76 三卷磁盘布局、Apple 风格启动选择器、三次启动失败自动拉救援

文档版本：1.0
基线日期：2026-10-30
对应组件：无（基础设施分册）
上级文档：`docs/spec/00-OVERVIEW.md`
配套分册：`docs/spec/71-IMAGE-OPENCORE.md`、`docs/spec/73-DEPLOY-RESCUE.md`、`docs/spec/74-BOOT-CPU-DISPATCH.md`、`docs/spec/80-TEST-HARNESS.md`

## 0. 本文作用与写作约束

本文回答四个问题：

1. macOS 26 的 APFS 容器里到底有哪些卷，我们烘出来的镜像必须包含哪几个，Recovery 卷能不能自己做出来。
2. 怎么把 OpenCore 的选择器配成最接近 Apple Startup Manager（开机按 Option 的那个画面）的样子。
3. 三个启动项（macOS 系统 / macOS 恢复 / Alpine 救援）怎么在一块盘上共存，怎么在选择器里呈现。
4. 「三次启动不成功就把救援系统拉起来」怎么判定、怎么计数、救援侧怎么预配 SSH。

### 0.1 职责边界

本文接上已有结论，不重做：

- **`71` 第 3 节的驱动事实不复述。** 25G325 的 x86_64 Boot KC 自带 `AppleVirtIO`（含 `AppleVirtIOBlock`）、`IONVMeFamily`、`AppleAHCIPort`、`AppleVmxnet3Ethernet`、`AppleVirtIONetwork`、`ApplePVPanic`。**不需要第三方块设备 kext，不需要第三方网卡 kext。** 第 5 节只在此基础上判断 ACPI 与 Quirks 的增量。
- **`71` 第 4 节的 SMBIOS 选型不重议。** `MacPro7,1`，因为 `AppleGraphicsDevicePolicy` 的 `ConfigMap` 对它落 `Default = none`。kext 最小集是 Lilu / VirtualSMC / AppleMCEReporterDisabler 三个，显式排除 WhateverGreen。
- **`71` 第 6 节的 `config.plist` 是本文的基线。** 本文只给**增量 diff**，并逐处说明它改的是 71 的哪一个键、为什么。
- **`74` 第 4 节的状态文件阶梯是本文的实现载体。** 所有者要的「三次失败拉救援」**不另写一套**，它是在 `74` 的 `STATE.TXT` 上加两个键、在 `efi_main` 里加一个分支。第 4 节给出确切的代码替换块。
- **`73` 第 5 节的 rescueOS 与救砖阶梯是本文的上游。** 本文在 Alpine 的持久形态上**修正** `73` 第 5.1、5.2 节的选择（去掉独立 ext4 分区），修正理由与证据在第 3.3 节，并在第 6.2 节登记。
- **`75-IMAGE-PREBAKE.md` 与本文有三处交叉，必须一起读。** 它第 2.3.2 节关于 `asr restore` 会连带造出 Preboot 与 Recovery 卷的结论**直接修改本文第 1.5 节的一半答案**；它第 4.1 节的实占估算修改本文第 3.5 节的容量表；它第 4.2、4.3 节的分区布局需要按本文第 3.1 节更新。三处的处置集中在第 6.5 节。

本文产生的对既有分册的修正，集中登记在第 6 节。**本文不修改其他任何文件。**

### 0.2 写作约束

- 每条结论带证据标签（`KNOWN` / `INFERRED` / `BLOCKED` / `TESTED`）与来源 URL。
- OpenCore 的事实一律以 acidanthera 官方配置文档与 `OpenCorePkg` / `OcBinaryData` 仓库为准。社区做法一律 `INFERRED`，并注明时效与是否覆盖 macOS 26。
- **本项目至今 `TESTED` 数量为零，本文同样没有 `TESTED`。** 本文全部内容在 E0-L1 通过之前都是待验证的设计。
- 对外部网页内容均为转述，不作连续摘录。**内容已转述以符合许可限制。**
- 架构标注：本文全部结论针对 **x86_64**。arm64 的 APFS 布局多两个分区（见第 1.2 节末），与本项目无关。

### 0.3 七条结论先行

| # | 问题 | 结论 | 标签 |
|---|---|---|---|
| 1 | 「一个恢复盘一个系统盘」对不对 | **一半对。** 对的是「用户看得见两个卷」，错的是「它们是两个盘」与「只有两个」。macOS 10.15+ 的启动容器**至少五个卷**：Preboot、VM、Recovery、System、Data | `KNOWN` |
| 2 | 镜像必须烘出哪些卷 | **Preboot、System、Data 三个缺一不可**，VM 强烈建议带上。Update / xART / Hardware 全都可以不要 | `KNOWN` + `INFERRED` |
| 3 | Recovery 卷能不能预配 | **我们自己造不出来**（缺 chunklist、缺 `bless`、Linux/Windows 上没有 APFS 写工具）。**但走 `75` 的 R1 路径时 `asr` 会连带造出来**，不需要我们动手（`75` 第 2.3.2 节）。**而且没有 Recovery 卷的 macOS 能正常启动**，所以两条路都不阻塞。另外把已还原的 `x86_64BaseSystem.dmg` 做成一个独立分区，得到一个与容器隔离的恢复环境 | `INFERRED` |
| 4 | `PickerVariant` 选哪个 | **`Acidanthera\GoldenGate`**，官方描述是「macOS 11 风格图标集」，是三个内置集里唯一与 macOS 11 之后（含 26）视觉语言同代的 | `KNOWN` |
| 5 | 无头环境下风格对齐值多少 | **只值 L1 与人工排障的钱。** `73` 第 1.3 节已证明 Vultr 没有可编程控制台，选择器画面在 L2 上没人看得见。所以自动化路径必须靠 `Timeout` 自动走默认项，**任何一步都不许依赖有人按键** | `KNOWN` |
| 6 | 三次失败怎么判定 | 判定只能是「macOS 回写确认的缺失」。shim 在每次启动时若发现上一次的 `inflight` 没被清零就 `fails++`；`fails >= 3` 这一次直接拉 Alpine 并把 `fails` 清零。**阶梯前进只在未确认态发生，三次失败拉救援在两种态都发生** | 设计 |
| 7 | ACPI/SSDT 要不要 | 「KVM 平台好办」**这一半对**：没有厂商 ACPI 垃圾要补，`ACPI/Delete`、`ACPI/Patch`、`ACPI/Quirks` 全空。**必需的只有 `SSDT-EC`**（10.15 起要求存在 EC 设备）。`SSDT-PLUG` **不要加**，它与 `71` 的 `DummyPowerManagement = true` 方向相反 | `KNOWN` + `INFERRED` |

---

## 1. 澄清卷布局

### 1.1 所有者的认知来自哪里，以及它为什么过时

所有者的原话是「标准 macOS 我记得是一个恢复盘一个系统盘」。这个印象有确切的历史出处，而且在 2017 年之前是**完全正确**的。

| 时代 | 真实形态 | 「恢复盘」是什么 |
|---|---|---|
| macOS 10.7 到 10.12（HFS+） | GPT 上两个分区：`Apple_HFS` 系统分区 + `Apple_Boot` 恢复分区（名字就叫 `Recovery HD`，约 650 MB） | **一个独立 GPT 分区**。所以「一个恢复盘一个系统盘」是字面准确的 |
| macOS 10.13 到 10.14（APFS 初期） | GPT 上一个 `Apple_APFS` 分区，容器内 3 到 4 个卷：系统卷、Preboot、Recovery、VM | 变成了**容器内的一个卷**，不再是分区 |
| macOS 10.15（Catalina，卷组拆分） | 同上，但系统卷拆成 System + Data 两个卷并组成 volume group，**容器内至少五个卷** | 同上 |
| macOS 11 到 26（SSV） | 同上，且 System 卷被封进一个 snapshot，系统从 snapshot 启动而不是从可写卷启动 | 同上 |

**所以这个认知错在三处，每一处都影响我们怎么造镜像：**

1. **不是「盘」，是「卷」。** 10.13 之后 Recovery 不再占 GPT 分区，它是 APFS 容器内的一个卷。这意味着造它需要写 APFS 容器内部结构，而不是写一个分区。这件事的难度差了一个数量级，也是第 1.5 节结论的根源。
2. **不是两个，至少五个。** 另外三个（Preboot、VM，加上 Data）是隐藏的，Finder 和 Disk Utility 默认不显示，所以用户看不见。
3. **启动链真正依赖的那个卷恰好是用户看不见的那个。** `boot.efi` 不在 System 卷上，在 **Preboot** 卷上。漏掉 Preboot 的镜像根本不可引导，而漏掉 Recovery 的镜像能正常启动。这两件事的优先级与直觉相反。

### 1.2 macOS 26 的卷角色全表

`KNOWN`，来源：Apple 平台安全指南的 APFS 一节（转述自 <https://support.apple.com/en-nz/guide/security/seca6147599e/web>）。该页明确写了：**在 macOS 10.15 及之后，用于启动 Mac 的 APFS 容器必须至少包含五个卷**，其中前三个对用户隐藏，并逐个给出用途：Preboot 未加密且含启动容器内每个系统卷所需的数据；VM 未加密且用于存放加密的 swap 文件；Recovery 未加密且必须在不解锁系统卷的情况下就可用，以便进入 recoveryOS；System 含启动 Mac 所需的全部文件与 macOS 原生安装的全部 app；Data 含会变的数据。同一页还写明：Preboot、VM、Recovery 三个卷是**共享的、不随额外的系统卷复制**；macOS 11 及之后系统卷被捕获进一个 snapshot，操作系统从 snapshot 启动。

下表把官方的五个卷与实际会出现的其他角色合起来。「启动链依赖」一列是本文的核心判据。

| 角色 | `diskutil` 角色字母 | 作用 | 我们的镜像必需 | 启动链依赖 | 标签 |
|---|---|---|---|---|---|
| **System** | `S` | 封印的只读系统卷。macOS 11+ 从它的 snapshot 启动，不是从卷本身 | **必需** | **是。** snapshot 是内核与 `/System` 的来源 | `KNOWN` |
| **Data** | `D` | 可写卷。`/Users`、`/Library`、`/private`、`/usr/local`、用户装的 app，通过 firmlink 投射回根 | **必需** | **是。** 与 System 组成 volume group，缺它系统卷无处落可写状态 | `KNOWN` 对于作用；`INFERRED` 对于「缺它一定起不来」 |
| **Preboot** | `B` | 存放每个系统卷启动所需的数据。**`boot.efi` 与 per-volume 的启动资源在这里** | **必需** | **是，而且是第一环** | `KNOWN` |
| **VM** | `V` | 存放加密 swap 与 sleepimage | **强烈建议** | 否。启动不读它，运行期才用 | `KNOWN` 对于作用；`INFERRED` 对于「缺它能起来」 |
| **Recovery** | `R` | recoveryOS。必须在系统卷未解锁时就可用 | **可以省**，见 1.5 | 否 | `KNOWN` |
| **Update** | `U` | macOS 11 起的 OTA 更新暂存区 | 不要 | 否 | `INFERRED` |
| **xART** | `X` | Secure Enclave 的防重放计数器存储。**只在带 T2 或 Apple Silicon 的机器上存在** | 不要（我们没有 T2） | 否 | `INFERRED` |
| **Hardware** | `H` | Apple Silicon 的固件/iBoot 相关 | 不要（x86_64 无此物） | 否 | `INFERRED` |
| **Installer** / **Enterprise** / **Backup** | `I` / `E` / `T` | 安装器暂存、企业管理、备份 | 不要 | 否 | `INFERRED` |

角色字母的完整取值集是 `B|R|V|I|T|S|D|U|N|E|X|H|L|C|Y|G`（`KNOWN`，这是 `diskutil apfs addVolume` 自己打印的用法串，转述自 <https://apple.stackexchange.com/questions/434637/how-to-know-what-the-different-roles-do-in-diskutil-apfs-shell-command>）。**Apple 没有公开全部字母到角色名的映射**，上表只列出能确证的那些。`N`、`L`、`C`、`Y`、`G` 的含义未确证，登记为 L-001。**这不阻塞任何事**：我们只会用到 `S`、`D`、`B`、`V`、`R` 五个。

**一条 arm64 专属的差异，登记在这里以免以后被误用：** Apple Silicon 的内置盘上还有两个独立 GPT 分区 `Apple_APFS_ISC`（约 520 MB）与 `Apple_APFS_Recovery`（约 5 GB），而外接启动盘上没有它们，外接盘仍然是传统的 EFI 分区形态（`INFERRED`，转述自 <https://eclecticlight.co/2021/01/13/big-sur-boot-volume-layout/>）。**这两个分区与 x86_64 无关，不要在本项目里出现。** 按 `00-OVERVIEW` 第 7 节第 2 条，arm64 证据不得用于 x86 决策，此处列出只为防止别人照搬 Apple Silicon 的分区表。

### 1.3 启动链真正依赖的东西

从加电到内核，x86_64 + OpenCore 的路径是：

```text
固件（OVMF）
  └─ ESP:\EFI\BOOT\BOOTX64.EFI            ← 74 的 shim
      └─ ESP:\EFI\OC\OpenCore.efi
          ├─ UEFI/APFS/EnableJumpstart = true
          │     从 APFS 容器的 jumpstart 区域加载 apfs.efi
          │     ← 没有这一步，OpenCore 根本看不见容器里的任何卷（71 §6.9.2）
          ├─ 按 bless 模型扫描各分区，得到启动项
          └─ 选中 macOS 项之后加载：
                Preboot 卷 : /<VolumeGroupUUID>/System/Library/CoreServices/boot.efi
                    └─ 挂载 System 卷的 snapshot 作为根
                    └─ 挂载 Data 卷并建立 firmlink
                    └─ 加载 Boot KC（BootKernelExtensions.kc）
```

**`boot.efi` 位于 Preboot 卷的 per-volume-group 目录里，这一点有官方旁证。** `KNOWN`：OpenCore 官方文档在描述 `PickerAttributes` 的 `OC_ATTR_USE_VOLUME_ICON` 时，给出的卷图标搜索顺序第一条就是「APFS 的 Preboot 卷内 per-volume 目录（在 macOS 里挂载于默认位置时是 `/System/Volumes/Preboot/{GUID}/`）」，第二条是 Preboot 卷根（转述自 <https://dortania.github.io/docs/release/Configuration.html>）。同一文档在 `.contentVisibility` 的位置示例里给的是 `/System/Volumes/Preboot/{GUID}/System/Library/CoreServices/.contentVisibility`，**即它确认 `System/Library/CoreServices/` 这条路径是在 Preboot 卷上展开的**，而不是在 System 卷上。

由此得到三条可操作的判据：

1. **Preboot 坏了或缺了，表现是「选择器里没有 macOS 这一项」，而不是「选了之后起不来」。** 这是一个很容易误诊的失败模式：看起来像盘没被认出来，实际是卷内容不全。排查手段是 OpenCore DEBUG 日志里 `OCB:` 与 `OCJS:`（`OcApfsLib`）两组前缀（`KNOWN`，日志前缀表见同一文档）。
2. **`apfs.efi` 是从容器自己的 jumpstart 区域取的**，不是我们提供的。所以 APFS 驱动的版本永远与镜像里的 macOS 匹配，`UEFI/APFS/MinVersion = 0` 与 `MinDate = 0` 是安全的（`71` 第 6.9.2 节已这么设）。
3. **`bless` 这一步我们不执行。** OpenCore 的 bless 模型是「扫描预定义路径」，不是「读固件 NVRAM 里的 bless 记录」。所以造镜像时不需要跑 `bless` 命令，只需要让文件出现在预定义路径上。这一条对第 1.5 节很重要，因为 `bless` 是一个只有 macOS 才有的工具。

### 1.4 我们的镜像必须包含哪些卷

**结论：Preboot + System + Data + VM 四个卷，Recovery 不做。**

| 卷 | 带不带 | 省掉的后果 |
|---|---|---|
| Preboot | **带** | 不可引导。选择器里不出现 macOS 项。**这是硬阻断** |
| System | **带** | 不可引导。没有内核 |
| Data | **带** | `INFERRED`：System 卷是封印只读的，启动期 `launchd` 要写的东西（`/private/var`、`/Users`）全在 Data 卷上，经 firmlink 投射。缺它大概率停在早期用户态。**代价是零（它就是系统装出来的），所以不值得为「能不能省」花时间验证** |
| VM | **带** | `INFERRED`：swap 与 sleepimage 无处可放。`dynamic_pager` 可能在首启时自己创建它，也可能报错。Apple 把它列进「必须至少五个卷」，所以省它等于偏离官方形态。**它初始大小接近零，省它一点好处都没有** |
| Recovery | **不带** | 失去 recoveryOS。影响范围见 1.5.3。**用 Alpine 与独立的 BaseSystem 分区覆盖同一需求** |
| Update | 不带 | 失去 OTA 暂存。我们 `Misc/Security/BlacklistAppleUpdate = true`（`71` 第 6.6.2 节）且基线固定在 25G325（`00-OVERVIEW` 第 2.3 节），**本项目不做 OTA 更新**，所以这是零损失 |
| xART / Hardware | 不带 | 无影响。平台上不存在对应硬件 |

**实际操作上这四个卷不需要我们逐个创建。** 它们是 macOS 安装器的产物：按 `71` 第 2.4 节路 A 进 BaseSystem、在 Disk Utility 里把目标分区格式化成 APFS、跑安装器，出来的容器里自动就是这四个卷（加上 Recovery，如果走的是完整安装器）。本节的价值不在「怎么造」，而在**怎么判断一个瘦镜像被裁坏了**：`73` 第 4.6 节的瘦镜像流程会动分区与容器，而「卷还在不在」是那条流程唯一必须的完整性判据。

**可照抄的判据脚本**（guest 内执行，进 `71` 第 10 节首启探针）：

```bash
#!/bin/sh
# /usr/local/libexec/probe-volumes.sh
# 判定 APFS 容器的卷角色是否齐备。退出码 0 = 齐备，1 = 缺必需卷。
set -u
PLIST=$(diskutil apfs list -plist)

# 1. 人读的全表
echo "===== 容器与卷角色 ====="
diskutil apfs list

# 2. 机器判据：必需角色逐个检查
MISSING=""
for role in Preboot System Data VM; do
  if ! diskutil apfs list | grep -q "($role)"; then
    MISSING="$MISSING $role"
  fi
done

echo "===== 可选角色（缺了不报错）====="
for role in Recovery Update xART Hardware; do
  diskutil apfs list | grep -q "($role)" && echo "  有 $role" || echo "  无 $role"
done

# 3. 启动链的那一环：Preboot 上确实有 boot.efi
echo "===== Preboot 内的 boot.efi ====="
ls -l /System/Volumes/Preboot/*/System/Library/CoreServices/boot.efi 2>/dev/null \
  || echo "  !! Preboot 里没有 boot.efi"

# 4. 根卷是否来自 snapshot（macOS 11+ 的 SSV 形态）
echo "===== 根卷形态 ====="
mount | head -3
diskutil info / | grep -E 'Snapshot|Sealed|Read-Only|APFS Physical Store'

if [ -n "$MISSING" ]; then
  echo "FAIL 缺必需卷:$MISSING"
  exit 1
fi
echo "OK 四个必需卷齐备"
```

### 1.5 Recovery 卷三问

任务点名要查清三件事，逐个回答。

#### 1.5.1 它是 APFS 容器里的一个卷，还是独立分区

**是容器里的一个卷，角色 `R`。** `KNOWN`，依据是第 1.2 节的 Apple 官方页面把它列为容器内五个卷之一，并说明它「必须在不解锁系统卷的情况下可用」（所以它未加密，但它仍然在同一个容器里）。

独立分区形态的 Recovery（`Apple_Boot` 类型、卷名 `Recovery HD`）属于 HFS+ 时代，10.13 之后在新装的系统上不再产生。`INFERRED`：从 HFS+ 升级上来的老盘上可能两种都在，但我们是全新烘的镜像，不存在这种历史包袱。

#### 1.5.2 不走原生安装器，Recovery 卷能不能一起烘出来

**不能，而且理由是具体的，不是「太难」。** 三道墙，任何一道都足以否决：

1. **缺 `BaseSystem.chunklist`。** `KNOWN`，`71` 第 1.6 节已经登记：在 `payloadv2-full-index.tsv.zip` 的 458,715 条路径里检索 `chunklist` 零命中，检索 `com.apple.recovery.boot` 同样零命中。真实的 Recovery 卷里放的是 `BaseSystem.dmg` + `BaseSystem.chunklist` 这一对，缺后者意味着造出来的卷不符合 Apple 的形态。
2. **缺 `bless`。** 让一个卷成为可引导的 recovery，Apple 的工具链是 `bless --folder ... --bootefi`，而 `bless` 只在 macOS 上存在（同 `71` 第 2.3 节对 `createinstallmedia` 的判定）。我们的开发机是 Windows（`71` 第 2 节），构建机是 Linux。
3. **写 APFS 容器内部结构这件事在 Linux/Windows 上没有可用工具。** 读 APFS 有若干只读实现，**写**（创建一个带指定角色的卷并在容器超级块里登记）没有可用的第三方实现。`INFERRED`，但置信度很高：APFS 的写支持连 Linux 内核都没有。

**所以路径只剩一条：让 macOS 自己造。** 这件事有两种形态，第二种是在本文写作期间才出现的：

**形态一：跑一次完整安装器。** 即走 `71` 第 2.4 节路 A 进 BaseSystem，用完整安装器装一次，安装器会自己建 Recovery 卷（资产的 `ContainsSFRContent = True`，`71` 第 1.3 节，说明恢复内容随资产交付）。这条路可行，但代价是**每次重造镜像都要跑一次完整安装**，而 `73` 第 1.2 节的整个设计就是为了避免这件事。

**形态二：`asr restore` 连带造出来。这一条推翻了本节标题的一半答案，必须单独写清。**

`KNOWN`（依据是 `diskutil` / `asr` 的手册语义，转述见 `75` 第 2.3.2 节）：`75` 第 2.3.2 节引的三条里第 2、3 条正好回答本节的问题。第 2 条说一个卷要可引导，它所在的 container 里必须有 Preboot 卷与 Recovery 卷各一个且角色正确，两者存着与每个 system volume 绑定的信息；**第 3 条说目标是分区且带 `--erase` 时，如果被恢复的卷是一个有效系统，Preboot 与 Recovery 的相关内容会一并从源复制到目标，必要时在目标上创建这两个卷。**

**即在 `75` 选定的 R1 路径下，Recovery 卷是免费的，我们一行命令都不用写。** `75` 自己把这件事总结成一句「我们不需要自己造 Preboot 和 Recovery，`asr` 会造」。

**所以本节的准确结论是：**

| 造 Recovery 卷的途径 | 可行 | 代价 | 产出的是哪个 build |
|---|---|---|---|
| 我们自己在 Linux/Windows 上拼 | **不可行** | 三道墙 | — |
| 跑一次完整安装器（形态一） | 可行 | 一次完整安装，几十分钟且需要人 | 25G325 |
| `asr restore` 克隆运行器（形态二，`75` 的 R1） | **可行且零成本** | 无 | **运行器的 build，当前是 25G76，不是 25G325** |

**形态二有一条必须记住的代价：它产出的 Recovery 是运行器那一版的。** `75` 第 2.3 节把这件事登记为 `P-016`（25G76 与 25G325 在内核 collection 内容上的差异未比对）。对 Recovery 卷而言这个差距的影响小于对系统卷的影响（recoveryOS 的用途是 Disk Utility 与终端，不是跑我们的 kext），但它仍然意味着**容器内的 Recovery 与系统卷可能不同 build**。`INFERRED`，登记为 L-023。

#### 1.5.3 没有 Recovery 卷的 macOS 能不能正常启动

**能。** `INFERRED`，三条依据：

1. 第 1.3 节的启动链里没有任何一环读 Recovery 卷。Recovery 是一个**并列的启动目标**，不是主路径的一环。
2. Apple 那句「必须至少五个卷」描述的是安装器产出的形态，不是 `boot.efi` 的运行时要求。官方对 Recovery 卷的说明是「必须在不解锁系统卷的情况下可用，以便进入 recoveryOS」，即它的用途是进 recoveryOS，不是启动 macOS。
3. OpenCore 的启动算法把 recovery 当作 alternate option：官方描述是扫描时每个分区可以产生多个 primary 与 alternate 选项，alternate 代表该系统的 recovery，**「alternate 选项可以在没有 primary 选项的情况下存在，反之亦然」**（转述自 <https://dortania.github.io/docs/release/Configuration.html> 的 Boot Algorithm 一节）。即引导器这一侧明确支持「有系统但没有 recovery」。

**失去了什么，逐条评估：**

| recoveryOS 的能力 | 失去它的代价 | 我们的替代 |
|---|---|---|
| 图形 Disk Utility | **零代价**。无头环境里没人看得见（`73` 第 1.3 节），而且它要 WindowServer，正是本项目在改的东西 | Alpine 的 `fdisk`/`sgdisk`，走 SSH |
| 重装 macOS | 低。重装对我们等于重新投放一个镜像（`73` 第 4 节），比进 recoveryOS 点按钮快 | `73` 的 D1 / D2 投放路径 |
| `csrutil` 改 SIP | **零代价，而且本来就不生效**。`70` 第 5.3 节记录了一条已知副作用：把 `csr-active-config` 放进 `config.plist` 会让恢复环境里的 `csrutil` 改不动实际生效值。对本项目这是好事（配置唯一来源是镜像） | `NVRAM/Add` + `Delete`（`71` 第 6.7 节），或 picker 里的 `ToggleSipEntry.efi` |
| 终端 + `diskutil`（救砖） | **这是唯一有真实价值的一条** | 第 3 节的 BaseSystem 分区（有完整的 macOS 终端与 `diskutil`）+ Alpine（有网络与 SSH） |
| FileVault 解锁界面 | 零。研发期不用 FileVault（`71` 第 6.6.2 节 `AuthRestart = false`） |

**结论与处置：不为容器内的 Recovery 卷花力气，但如果 `asr` 顺手造了就留着。** 把「恢复」这个需求用一个**独立 GPT 分区**满足：里面装已经还原好的 `x86_64BaseSystem.dmg`（1,464,270,504 字节，SHA-256 `642E6148288527C51639D1B08C7F0B5A8CB4A68AEC2AC6DA3C78CF1723C5119A`，`KNOWN`，`71` 第 1.5 节）。

这个选择的四条好处：

1. **它不经过 DMG 加载，所以 `DmgLoading` 与 chunklist 都不相关**（`71` 第 6.6.3 节已论证路 A 的这个性质）。
2. **它是 Windows 上就能准备好的东西。** 还原已经做完了，剩下的只是 `dd` 进一个分区。
3. **它在选择器里是一个独立条目**，正好满足所有者「三个启动项」的要求，而且这一项用的是真正的 macOS 恢复环境（Disk Utility、终端、`diskutil` 全都在）。
4. **它与 macOS 容器完全隔离。** 一次把容器写坏的实验不会同时毁掉恢复环境。容器内的 Recovery 卷做不到这一点。

代价两条，都要写清：

- **它占 1.6 GiB 分区**，而容器内的 Recovery 卷只占容器内的几百 MB 共享空间。在 `73` 第 4.6.3 节的 16 到 24 GB 瘦镜像上，这把下限推到 20 GB 左右（第 3.5 节的容量表）。
- **它不是 Apple 形态的 recovery，所以 OpenCore 可能把它归类成普通的 Apple 系统项而不是 Apple Recovery 项。** 后果是它不会被 `HideAuxiliary` 隐藏、图标可能是 `Apple.icns` 而不是 `AppleRecv.icns`。`INFERRED`，这正好是我们想要的（三项都要可见），但分类结果要在 L1 用 DEBUG 日志确认。登记为 L-002，第 2.5 节给出两种修正手段。

**两个恢复环境会不会重复？会，而且这个重复是值得付的。** 走 `75` 的 R1 路径之后盘上会有两个恢复环境：容器内的 Recovery 卷（`asr` 造的，运行器那一版）与 p2 的 BaseSystem（25G325）。保留两个的理由，三条：

1. **它们的失败模式不重叠。** 容器内的 Recovery 与系统卷共享同一个 APFS 容器，一次把容器写坏的实验会同时毁掉两者。p2 是独立分区，容器坏掉时它完好。**这是整条救援阶梯里唯一一处「同一能力的两个独立实例」**，而 `73` 第 1.3 节的设计目标正是「让 S2 覆盖掉绝大多数失败」。
2. **它们的 build 不同（L-023）。** p2 是 25G325，与我们的系统卷同 build；容器内的那个是运行器的 build。要在恢复环境里做与版本相关的事（例如看 `PlatformSupport.plist`）时，p2 才是对的那个。
3. **代价是 1.6 GiB，而 3.3 节去掉 ext4 rescue 分区正好省出 1.5 GiB。** 净增约 0.1 GiB。

**什么时候可以砍掉 p2：** 如果 L-021 查出镜像容量有硬上限、必须压到 28 GB 以下，砍 p2 是正确的第一刀（第 3.5 节）。砍掉之后恢复能力退化为「容器内的 Recovery 卷 + Alpine」，仍然有两条路，只是其中一条与系统卷同生共死。

---

## 2. 把 OpenCanopy 配成 Apple Startup Manager 的样子

### 2.1 先把「Apple 风格」拆成可配置项

「和标准 macOS 系统选择器保持一致」不是一个开关，是六件独立的事。混在一起谈会导致改了三项就以为配好了。

| Apple Startup Manager 的行为 | OpenCore 侧对应什么 | 本文第几节 |
|---|---|---|
| 平时不出现，开机按住 Option 才出来 | `ShowPicker = false` + `PollAppleHotKeys` + `TakeoffDelay` + `KeySupport` | 2.4 |
| 图形界面，黑底、128×128 圆角卷图标、横向排列、下方文字标签 | `PickerMode = External` + `OpenCanopy.efi` + `PickerVariant` + `Resources/` | 2.2 / 2.3 / 2.4 |
| 每个卷显示它自己的名字与自定义图标 | `PickerAttributes` 的 `0x1` / `0x2` 位 + `.VolumeIcon.icns` + `.contentDetails` | 2.4 / 2.5 |
| 恢复项跟在对应系统项后面 | OpenCore 的 display order 规则，**不需要配置** | 2.5 |
| 鼠标/触控板可点 | `PickerAttributes` 的 `0x10` 位 + 固件的 pointer 协议 | 2.4 |
| 没选就自动走默认项 | `Timeout` | 2.4 / 2.6 |

`KNOWN`：**Apple 原生的「按 Option 进选择器」这个行为在 OpenCore 里是有明确对应物的，而且不止 Option 一个键。** 官方文档的 `PickerMode` 一节说明，`ShowPicker` 这个 action 通常靠开机按住 OPT 键达成，并且在 `ShowPicker` 关闭时 OpenCore 还支持用 Escape 与 Zero 两个键进入选择器；Escape 的存在是为了与 Apple 自己的 picker 共存，以及应对某些固件读不到长按 OPT 的情况；在不需要 `KeySupport` 的系统上，从加电一直按住其中一个键到选择器出现应当总是有效（转述自 <https://dortania.github.io/docs/release/Configuration.html>）。同一节还有一条对我们直接相关的注意：**在非 Apple 固件上，按键处理需要 `KeySupport`、`OpenUsbKbDxe` 或类似驱动，而且不是所有按键功能都能在各种固件上实现。**

另有四个 Apple BDS 风格的 action hotkey 是 OpenCore 内置支持的（同一来源，`KNOWN`）：`X` 启动第一个找到的 Apple 系统；`CMD+R` 进 recovery；`CMD+V` verbose；`CMD+S` 单用户。**这四个在我们的三项布局上有现成价值**：`CMD+R` 就是「直接进恢复」，不需要先看选择器。

### 2.2 `UEFI/Drivers` 增量

接 `71` 第 6.9.1 节那张表。**只加两项、改一项**：

| 驱动 | 71 的状态 | 本文 | 取自哪里 | 理由 |
|---|---|---|---|---|
| `OpenCanopy.efi` | `false` | **`true`** | OpenCorePkg release 的 `X64/EFI/OC/Drivers/` | `KNOWN`，官方：OpenCanopy 是跑在 `External` `PickerMode` 下的图形界面，依赖 `OcBootManagementLib`，需要 `Resources` 目录里的图形资源 |
| `OpenRuntime.efi` | `true` | `true`（不变） | 同上 | `71` 第 6.9.1 节已论证必需 |
| `OpenHfsPlus.efi` | `true` | `true`（不变），**但来源要写清** | **`OcBinaryData` 的 `Drivers/`，文件名是 `HfsPlus.efi`** | `KNOWN`：`OcBinaryData/Drivers/` 下的 HFS+ 驱动叫 `HfsPlus.efi`（37,892 字节）、`HfsPlus32.efi`、`HfsPlusLegacy.efi`，**没有叫 `OpenHfsPlus.efi` 的文件**（本轮读取 <https://api.github.com/repos/acidanthera/OcBinaryData/contents/Drivers>）。`71` 第 6.9.1 节与第 8.2.1 节用的文件名 `OpenHfsPlus.efi` 在当前 `OcBinaryData` 里取不到，照抄那段 PowerShell 会在 `Copy-Item` 处失败。**修正：取 `HfsPlus.efi`，放进 `EFI\OC\Drivers\`，`config.plist` 里的 `Path` 写 `HfsPlus.efi`。** 登记为 L-003 |
| `ResetNvramEntry.efi` | `true` | `true`（不变） | OpenCorePkg | 它产生一个 picker 条目。注意它是 **system entry，属于 auxiliary**（2.4 节 `HideAuxiliary` 那一行） |
| `ToggleSipEntry.efi` | `true` | `true`（不变） | OpenCorePkg | 同上。**它的 `--show-csr` 参数与 `PickerAttributes` 的 `0x4` 位不兼容**（`KNOWN`，官方明确），这是 2.4 节不开 `0x4` 的一条附带理由 |
| `AudioDxe.efi` | `false` | **`false`（保持）** | — | 见 2.4 节「开机音」那一段。没有音频设备，开了只会多一类启动期失败 |
| `OpenLinuxBoot.efi` + `ext4_x64.efi` | 未提及 | **`false`，不用** | OpenCorePkg + OcBinaryData | 理由见 3.3.4 节。**它的官方用法要求 `LauncherOption` 打开，而 `74` 第 3.5 节已经论证 `LauncherOption` 必须保持 `Disabled`**，否则 shim 被从引导链上摘掉。两者直接冲突 |

**DEBUG 构建的纪律在这里要再强调一次。** `KNOWN`，`71` 第 2.5 节已引官方要求：`BOOTx64.efi`、`OpenCore.efi`、`OpenRuntime.efi`、`OpenCanopy.efi` **四个文件要同时换成 DEBUG 或 NOOPT 版本**才能拿到有用的信息，而且官方建议排错时先不要用 OpenCanopy（转述自 <https://dortania.github.io/OpenCore-Install-Guide/troubleshooting/debug>）。

**由此得到一条构建期规则：** 镜像要出两套 ESP 内容，`picker=canopy` 与 `picker=builtin`，差异只有 `Misc/Boot/PickerMode` 一个键与 `OpenCanopy.efi` 的 `Enabled`。排查引导问题时先切 `builtin`。这两套不是两个镜像，是同一个 `scripts/make-oc-config.py` 的一个参数（2.7 节给出）。

### 2.3 `Resources/` 要从 `OcBinaryData` 取什么

`KNOWN`，本轮读取 <https://api.github.com/repos/acidanthera/OcBinaryData/contents/Resources>：该目录下**恰好四个子目录**，`Audio`、`Font`、`Image`、`Label`。`Image` 下只有一个厂商目录 `Acidanthera`（本轮读取 <https://api.github.com/repos/acidanthera/OcBinaryData/contents/Resources/Image>），其内按官方文档是 `GoldenGate`、`Syrah`、`Chardonnay` 三个图标集。

| 子目录 | 取不取 | 用途 | 理由 |
|---|---|---|---|
| `Image/Acidanthera/GoldenGate/` | **取** | 全部 `.icns` 图标 | 2.4 节选定的 `PickerVariant` 指向它 |
| `Image/Acidanthera/Syrah/`、`Chardonnay/` | **不取** | 另外两套风格 | 省 ESP 空间。想对照时临时拷进去即可，改一个字符串就能切 |
| `Label/` | **取（整个）** | 预渲染的文字标签 `.lbl` / `.l2x` | `KNOWN`，官方：全部标签是 **mandatory**（`EFIBoot`、`Apple`、`AppleRecv`、`AppleTM`、`Windows`、`Other`、`ResetNVRAM`）。缺了会怎样文档没说，不要赌 |
| `Font/` | **取（整个）** | OpenCanopy 渲染文字用的位图字体 | 没有它 OpenCanopy 画不出条目名。官方把 fonts 与 images 并列为「所需的图形资源」 |
| `Audio/` | **不取** | 语音辅助与开机音的音频资源 | `UEFI/Audio/AudioSupport = false`（`71` 第 6.9.2 节），没有音频设备。取了是死重量 |

落盘后的目录形态（`EFI\OC\Resources\` 之下）：

```text
EFI\OC\Resources\
├─ Font\
│   └─ （OcBinaryData/Resources/Font 的全部内容）
├─ Image\
│   └─ Acidanthera\
│       └─ GoldenGate\
│           ├─ Cursor.icns      Selected.icns   Selector.icns   SetDefault.icns
│           ├─ Left.icns        Right.icns
│           ├─ HardDrive.icns   Apple.icns      AppleRecv.icns  AppleTM.icns
│           ├─ Windows.icns     OpticalDrive.icns
│           ├─ Other.icns       ResetNVRAM.icns Shell.icns      Tool.icns
│           ├─ Background.icns  （可选，居中背景图）
│           ├─ Ext*.icns        （外置盘变体）
│           └─ Alpine.icns      ← 本项目新增，见 2.5.3
└─ Label\
    └─ （OcBinaryData/Resources/Label 的全部内容）
```

`KNOWN` 对于强制图标清单与尺寸：`Cursor`（最大 144×144）、`Selected`（144×144）、`Selector`（最大 144×40）、`SetDefault`（最大 144×40，**必须与 `Selector` 同宽**）、`Left`/`Right`（40×40）、`HardDrive`（128×128）是 mandatory；`Apple`、`AppleRecv`、`AppleTM`、`Windows`、`OpticalDrive`、`Other`、`ResetNVRAM`、`Shell`、`Tool` 是 128×128；缺可选图标时会退到最接近的可用图标；外置项优先用 `Ext` 前缀的图标；全部尺寸是 1x 缩放级的规范值，其他缩放级按比例（转述自 <https://dortania.github.io/docs/release/Configuration.html>）。

**可照抄的取资源脚本**（Windows，接 `71` 第 8.2.1 节的 `stage-efi.ps1`，插在第 5 步之前）：

```powershell
# scripts/stage-canopy-resources.ps1
# 把 OcBinaryData 的选择器资源装进 build\efi\EFI\OC\Resources\
$ErrorActionPreference = 'Stop'
$OCBIN_COMMIT = '<pin-this>'      # 必须写死 commit，不要用 master
$STAGE  = 'build\efi\EFI\OC\Resources'
$VARIANT = 'Acidanthera\GoldenGate'

# 1. 取仓库快照（tar.gz 一个 commit，不做 git clone）
curl.exe -L -o build\ocbindata.tar.gz `
  "https://github.com/acidanthera/OcBinaryData/archive/$OCBIN_COMMIT.tar.gz"
New-Item -ItemType Directory -Force -Path build\ocbindata | Out-Null
tar.exe -xzf build\ocbindata.tar.gz -C build\ocbindata --strip-components=1

# 2. 只拷三类：Font 全部、Label 全部、Image 下选定的那一个变体
New-Item -ItemType Directory -Force -Path `
  "$STAGE\Font", "$STAGE\Label", "$STAGE\Image\$VARIANT" | Out-Null
Copy-Item "build\ocbindata\Resources\Font\*"  "$STAGE\Font\"  -Recurse -Force
Copy-Item "build\ocbindata\Resources\Label\*" "$STAGE\Label\" -Recurse -Force
Copy-Item "build\ocbindata\Resources\Image\$VARIANT\*" "$STAGE\Image\$VARIANT\" -Recurse -Force

# 3. HFS+ 驱动也在这个仓库里，文件名是 HfsPlus.efi（不是 OpenHfsPlus.efi，见 2.2 节）
Copy-Item "build\ocbindata\Drivers\HfsPlus.efi" 'build\efi\EFI\OC\Drivers\' -Force

# 4. 强制图标自检：少一个就在构建期失败，不要留到启动期
$mandatory = @('Cursor','Selected','Selector','SetDefault','Left','Right','HardDrive')
$missing = $mandatory | Where-Object { -not (Test-Path "$STAGE\Image\$VARIANT\$_.icns") }
if ($missing) { throw "缺强制图标: $($missing -join ', ')" }

# 5. 体积与清单
'{0:N1} MiB  Resources' -f ((Get-ChildItem -Recurse -File $STAGE |
  Measure-Object -Sum Length).Sum / 1MB)
Get-ChildItem -Recurse -File $STAGE | ForEach-Object {
  "$((Get-FileHash -Algorithm SHA256 $_.FullName).Hash)  $($_.FullName)"
} | Set-Content -Encoding ascii build\resources.sha256
```

**`$OCBIN_COMMIT` 必须写死。** `71` 第 2.5 节已经把 `OcBinaryData` 列为「固定 commit」的件，这里只是把它落到脚本里。理由：`OcBinaryData` 是一个没有 release tag 的仓库，`master` 会动，而图标集的变化会直接改变选择器外观。镜像的外观必须是可复现的。

### 2.4 `Misc/Boot` 的完整增量

下表是对 `71` 第 6.6.1 节那张表的替换。**「71 的值」一列保留下来，这样这张表本身就是 diff。**

| 键 | 71 的值 | 本文的值 | 理由 | 标签 |
|---|---|---|---|---|
| `PickerMode` | `Builtin` | **`External`** | `KNOWN`，官方：`External` 使用外部 boot management 协议（即 OpenCanopy），**不可用时自动退回 `Builtin`**。这个自动退回很重要：它意味着 `OpenCanopy.efi` 加载失败不会变成一次无法引导 | `KNOWN` |
| `PickerVariant` | 未设（Sample 的 `Auto`） | **`Acidanthera\GoldenGate`** | 见 2.4.1 | `KNOWN` |
| `PickerAttributes` | `17`（`0x11`） | **`211`（`0xD3`）** | 见 2.4.2 | `KNOWN` 位义；`INFERRED` 取值 |
| `ShowPicker` | `true` | **分两档，见 2.4.3** | L1 用 `true`，L2 用 `false` | 设计 |
| `Timeout` | `5` | **`5`（L1）/ `3`（L2）** | 见 2.4.3 与 2.6 | 设计 |
| `PollAppleHotKeys` | `true` | `true`（不变） | Apple 的 `CMD+R` / `CMD+V` / `X` 要靠它。`71` 已经设对了 | `KNOWN` |
| `TakeoffDelay` | `0` | **`10000`**（10 ms） | `KNOWN`，官方：某些平台由于键盘驱动的性质，**必须把它至少设到 5000 到 10000 微秒**才能用上 action hotkey；`ResetNvramEntry` 一节也点名说某些固件与驱动组合下必须配 `TakeoffDelay` 才能可靠检测内置热键。10 ms 对自动化路径的开机时间影响可忽略 | `KNOWN` |
| `HideAuxiliary` | `false` | **`false`（不变），但理由换了** | 见 2.4.4 | `KNOWN` |
| `HibernateMode` | `None` | `None`（不变） | `80` 第 2.4.2 节要求关休眠 | — |
| `HibernateSkipsPicker` | `false` | `false`（不变） | 官方对它的限制里有一条「只在 macOS 休眠唤醒可靠的系统上使用，否则用户可能看不到启动循环」。我们正是要看到启动循环 | `KNOWN` |
| `LauncherOption` | `Disabled` | **`Disabled`（不许改）** | `74` 第 3.5 节：一旦创建自定义启动项，`\EFI\BOOT\BOOTx64.efi` 就不再用于引导，**而那正是 shim 的位置** | `KNOWN` |
| `LauncherPath` | 未设 | 不设 | 同上，`LauncherOption = Disabled` 时它无意义 | — |
| `PickerAudioAssist` | 未设 | `false` | 没有音频设备 | — |
| `InstanceIdentifier` | 未设 | 不设 | `.contentVisibility` 的实例定向功能我们不用（2.5.4 节只用无实例列表的形式） | — |

#### 2.4.1 `PickerVariant` 选 `Acidanthera\GoldenGate`，依据是官方的风格代次标注

`KNOWN`，官方对三个内置图标集的描述逐字对应三个 macOS 代次（转述自 <https://dortania.github.io/docs/release/Configuration.html>）：

| 取值 | 官方描述 | 对我们的意义 |
|---|---|---|
| `Acidanthera\GoldenGate` | **macOS 11 风格图标集** | macOS 11 是 Big Sur，它确立了圆角方形图标 + 深色背景的启动选择器视觉语言，**macOS 12 到 26 沿用至今**。这是三个里唯一与我们的目标系统同代的 |
| `Acidanthera\Syrah` | OS X 10.10 风格 | 2014 年的扁平化风格。与 26 相差六代 |
| `Acidanthera\Chardonnay` | Mac OS X 10.4 风格 | 2005 年的拟物风格。与 26 相差二十年 |
| `Auto`（Sample 默认） | 按 `background-color` 与 `DefaultBackgroundColor` 自动选：Syrah Black 选 `GoldenGate`，Light Gray 选 `Chardonnay`；`background-color` 优先 | 在我们设定黑底的前提下它**也会选到 `GoldenGate`** |
| `Default` | 别名，等于 `Acidanthera\GoldenGate` | 同上 |

**三个取值都能落到 `GoldenGate`，但要显式写 `Acidanthera\GoldenGate`。** 两条理由：

1. `Auto` 的结果依赖 NVRAM 变量。那两个变量在 L2 上是否持久未知（`80` 的 H-002），变量没生效时 `Auto` 的结果就不确定。**镜像的外观不该依赖一个可能丢失的变量。**
2. `Default` 是一个别名，别名的指向是上游可以改的。显式写目录名把它钉死，与 `71` 第 2.5 节「固定 commit」的纪律一致。

**配套的两个 NVRAM 变量**，这是「黑底」这件事的落地。`KNOWN`，官方变量表（转述自同一来源）：`4D1EDE05-38C7-4A6A-9CC6-4BCCA8B38C14:DefaultBackgroundColor` 是四字节 BGRA，定义 `boot.efi` 的界面背景色，标准色含 `BF BF BF 00`（Light Gray）与 `00 00 00 00`（Syrah Black）；`4D1FDA02-38C7-4A6A-9CC6-4BCCA8B30102:background-color` 是 acidanthera 对前者的覆盖，用于 OS X 10.9 一类老系统；`4D1EDE05-38C7-4A6A-9CC6-4BCCA8B38C14:UIScale` 是一字节，普通屏填 `01`、HiDPI 屏填 `02`。

接 `71` 第 6.7 节的 `NVRAM` 段，**增量如下**（注意 GUID 与 `71` 现有的 `7C436110-...` 是两个不同的 GUID，是新增而不是修改）：

```xml
<key>NVRAM</key>
<dict>
  <key>Add</key>
  <dict>
    <!-- 71 §6.7 的 7C436110-AB2A-4BBB-A880-FE41995C9F82 整段保持不变 -->

    <!-- 本文新增：boot.efi 与 OpenCanopy 的界面参数 -->
    <key>4D1EDE05-38C7-4A6A-9CC6-4BCCA8B38C14</key>
    <dict>
      <!-- 00 00 00 00 = Syrah Black，与 GoldenGate 配套 -->
      <key>DefaultBackgroundColor</key>
      <data>AAAAAA==</data>
      <!-- 01 = 普通屏。QEMU 的 VGA/virtio-gpu 给的是普通 DPI -->
      <key>UIScale</key>
      <data>AQ==</data>
    </dict>
  </dict>

  <key>Delete</key>
  <dict>
    <!-- 71 §6.7 的那一段保持不变，另加本文这一段。
         Add 的语义是"不存在才写"，所以想让镜像的值每次生效就必须先 Delete。
         同 70 §5.3 路径 A 的警告。 -->
    <key>4D1EDE05-38C7-4A6A-9CC6-4BCCA8B38C14</key>
    <array>
      <string>DefaultBackgroundColor</string>
      <string>UIScale</string>
    </array>
  </dict>
</dict>
```

**不要去写 `4D1FDA02-...:background-color`。** 官方说明它的用途是给 10.9 一类老系统用的覆盖，而且在 `PickerVariant = Auto` 下它的优先级高于 `DefaultBackgroundColor`。我们显式写了 `PickerVariant`，所以不需要它；写了反而多一个会影响 `Auto` 判定的变量。`INFERRED`。

#### 2.4.2 `PickerAttributes` 的位含义与取值

`KNOWN`，官方给出的位定义全表（OpenCore 保留 BIT0 到 BIT15，OEM 用 BIT16 到 BIT31；转述自 <https://dortania.github.io/docs/release/Configuration.html>）：

| 位 | 常量名 | 官方含义 | 本项目 | 理由 |
|---|---|---|---|---|
| `0x0001` | `OC_ATTR_USE_VOLUME_ICON` | 为启动项提供自定义图标。搜索顺序：APFS 的 Preboot 卷 per-volume 目录下的 `.VolumeIcon.icns`；其次 Preboot 卷根；其他文件系统则取卷根。失败退回默认图标 | **开** | 这是让 macOS 项显示我们自己的图标的唯一途径。**附带一条官方注意：在任何盘上使用卷图标会覆盖 OpenCore 原本「按内置/外置选图标」的行为**，对我们无影响（全部是内置盘） |
| `0x0002` | `OC_ATTR_USE_DISK_LABEL_FILE` | 用 bootloader 旁边的 `.disk_label` / `.disk_label_2x` 预渲染标题；**预渲染标签被禁用或缺失时，改用 `.contentDetails`（或 `.disk_label.contentDetails`）里的标签文字；两者都没有才渲染条目名本身** | **开** | 这一位是 `.contentDetails` 生效的前提。`.contentDetails` 是纯文本，比 `disklabel` 工具生成的预渲染位图好做得多（后者需要 macOS） |
| `0x0004` | `OC_ATTR_USE_GENERIC_LABEL_IMAGE` | 为没有自定义条目的启动项提供预定义标签图像，**但可能丢失实际启动项的细节** | **关** | 两条理由：一是它会把三个条目的真实名字换成通用标签（「EFI Boot」一类），正好与所有者要的「合理的名字」相反；二是官方明确 `ToggleSipEntry` 的 `--show-csr` 在 OpenCanopy 里与这一位不兼容 |
| `0x0008` | `OC_ATTR_HIDE_THEMED_ICONS` | 某些类别优先用内置图标以匹配主题风格，依赖 `0x0001` | **关** | 它的方向与 `0x0001` 相反（优先主题而不是卷自带图标）。我们要的是卷自带图标生效 |
| `0x0010` | `OC_ATTR_USE_POINTER_CONTROL` | 可用时启用选择器的指针控制 | **开** | Apple 的 Startup Manager 可以用触控板点选。L1 上 `-device usb-tablet` 让 OVMF 发布绝对指针协议。**L2 上没有指针设备，这一位就是空操作，不造成失败** `INFERRED` |
| `0x0020` | `OC_ATTR_SHOW_DEBUG_DISPLAY` | 显示额外的计时与调试信息，**仅 Builtin picker、仅 DEBUG/NOOPT 构建** | **关（但排障时临时开）** | 它对 OpenCanopy 无效，所以只在切回 `Builtin` 排障时有用 |
| `0x0040` | `OC_ATTR_USE_MINIMAL_UI` | 最小 UI，没有关机与重启按钮，影响 OpenCanopy 与 builtin | **开** | Intel Mac 的 Startup Manager 是一排卷图标，不带关机/重启按钮。**这一条是 2.4.5 的视觉保真度判断里唯一我没有官方依据的一项**，登记为 L-004 |
| `0x0080` | `OC_ATTR_USE_FLAVOUR_ICON` | 按 content flavour 选图标与音效。来源优先级：Tool 读 `Flavour` 字段；自动发现的条目读 bootloader 旁的 `.contentFlavour`；自定义条目在 `Flavour` 为 `Auto` 时读 `.contentFlavour`，否则用 `Flavour` 本身；都没有则按条目类型选。`Flavour` 是冒号分隔的名字序列，最多约五个，前面的优先级高，缺图标就试下一个 | **开** | **这是让 Alpine 项有自己图标的唯一干净途径**，见 2.5.3。另有两条官方注意：`Ext<Flavour>.icns` 与 `<Flavour>.icns` 都支持，外置盘上只用前者；**`.VolumeIcon.icns` 的优先级高于 `.contentFlavour`** |
| `0x0100` | `OC_ATTR_USE_REVERSED_UI` | 交换关机与重启按钮的位置。**官方：反转后的设置匹配较老的 macOS**，而且它是 OpenCore 以前的默认值；仅在未设 `0x0040` 时有效 | **关** | 官方说它匹配老 macOS，我们的目标是 26。且我们开了 `0x0040`，它本来就无效 |
| `0x0200` | `OC_ATTR_REDUCE_MOTION` | 减少 OpenCanopy 的密码与菜单动画，只留传达信息的那些 | **关** | Apple 的选择器有动画。而且官方注明启用 `PickerAudioAssist` 时这些动画会自动关掉，我们不用那个 |

**取值：`0x0001 | 0x0002 | 0x0010 | 0x0040 | 0x0080 = 0xD3 = 211`。**

```xml
<key>PickerAttributes</key>
<integer>211</integer>
```

**与 `71` 第 6.6.1 节的 `17`（`0x11`）的关系：不是冲突，是扩展。** `17` = `0x1 | 0x10`，是在 `PickerMode = Builtin` 下的合理值（builtin picker 不消费 `0x2` 的 `.contentDetails` 与 `0x80` 的 flavour）。切到 OpenCanopy 之后那两位才有意义。**所以 `make-oc-config.py` 应该让这个值跟着 `picker` 参数走**（2.7 节）。

**如果要在 L1 上跑视觉对照实验**，另一个有用的取值是 `0xF3`（加上 `0x20` 的调试显示）配 `PickerMode = Builtin`，它会把每个阶段的耗时打出来，便于定位「选择器出现得太慢」这类问题。

#### 2.4.3 `ShowPicker` / `Timeout` 分两档，这是本节最重要的决定

Apple 的行为是「平时直接启动，按住 Option 才出选择器」。照搬它需要 `ShowPicker = false`。但 `ShowPicker = false` 在无头环境里有一个致命性质：**没人能按 Option，所以选择器永远不出现，所以永远只能启动默认项。**

这件事本身不是问题（自动化本来就该走默认项），**问题在于它让「默认项是哪个」变成一个不可观察的状态**。而默认项由 `BootNext` / `BootOrder` 与 `AllowSetDefault` 的历史共同决定（`KNOWN`，官方 Boot Algorithm：先查 `BootNext` 里第一个有效的 primary option，失败则查 `BootOrder`，标记为默认项，然后按 `ShowPicker` 决定是否经过选择器），而 `80` 的 H-002 说 L2 的 NVRAM 持久性未知。

**所以分两档，并且把它做成构建参数而不是运行期开关：**

| 档 | 用在哪 | `ShowPicker` | `Timeout` | 行为 |
|---|---|---|---|---|
| `picker=visible` | **L1、人工排障、第一次在新平台上开机** | `true` | `5` | 选择器总是出现，5 秒后自动走默认项。**能看见三个条目各自的名字与图标，所以能确认布局对不对** |
| `picker=apple` | **L2 的稳态运行** | `false` | `3` | 不出选择器，直接走默认项。按住 OPT / Escape / Zero 可强制进入（在固件支持的前提下）。这是 Apple 的行为 |

**默认交付 `picker=visible`。** 理由：`00-OVERVIEW` 第 2.5 节风险 2 与 `80` 第 1.3 节的结论是「L2 的唯一主通道是 SSH」。在一台看不见画面的机器上，把选择器藏起来省下的 5 秒，换来的是「启动链到底走到哪一步了」这个问题少一个可观察点（选择器出现这件事本身会被 `71` 第 9 节的串口日志记下来，在 L1 上是一个确定的里程碑）。`picker=apple` 只在风格对齐本身成为交付要求时才用。

**`Timeout` 绝对不许设 0。** `KNOWN`，官方：`Timeout` 是选择器自动启动默认项之前的秒数，**设 0 表示禁用超时**。禁用超时等于无限等待按键，在无头机器上等于永久挂起。`71` 第 6.6.1 节已经写了这条，本文再钉一次，因为切到 OpenCanopy 时很容易顺手把它调大或清零。

#### 2.4.4 `HideAuxiliary` 为什么仍然是 `false`

`KNOWN`，官方对 auxiliary 的定义是四条中任一成立：**条目是 macOS recovery；条目是 macOS Time Machine；条目被显式标为 `Auxiliary`；条目是 system 条目（例如 Reset NVRAM）。** 隐藏后可以在选择器里按空格进入「Extended Mode」显示全部，而且隐藏 auxiliary 可以提升多盘系统的启动性能（转述自 <https://dortania.github.io/docs/release/Configuration.html>）。

对我们三项布局的直接后果：

| 我们的条目 | 是不是 auxiliary | `HideAuxiliary = true` 的后果 |
|---|---|---|
| macOS（APFS 容器） | 否，primary | 可见 |
| macOS Base System（p2） | **未定**，取决于 OpenCore 把它分类成 Apple 还是 Apple Recovery（L-002） | 如果被分类成 recovery 就**看不见了** |
| Alpine Rescue（BlessOverride 发现） | 否 | 可见 |
| Reset NVRAM / Toggle SIP | **是**（system 条目） | 看不见 |

**所以 `HideAuxiliary` 保持 `false`。** 它换来的性能收益（官方说的多盘扫描）在一块盘上接近零，而它可能藏掉的恰好是我们最需要在排障时点的两个条目。`71` 第 6.6.1 节的理由是「要能看到 recovery 与工具条目」，这个理由在三项布局下更强了。

**一条配套事实，排障时有用：** 按空格进 Extended Mode 这个能力只在选择器可见时才有意义。在 `picker=apple` 档下要先按 OPT 再按空格，两次按键在无头机器上都做不到。这又是 2.6 节那条纪律的一个侧面。

#### 2.4.5 完整的 `Misc/Boot` 片段（可直接照抄）

```xml
<key>Boot</key>
<dict>
  <key>HibernateMode</key>        <string>None</string>
  <key>HibernateSkipsPicker</key> <false/>
  <key>HideAuxiliary</key>        <false/>
  <key>InstanceIdentifier</key>   <string></string>
  <key>LauncherOption</key>       <string>Disabled</string>
  <key>LauncherPath</key>         <string>Default</string>
  <key>PickerAttributes</key>     <integer>211</integer>
  <key>PickerAudioAssist</key>    <false/>
  <key>PickerMode</key>           <string>External</string>
  <key>PickerVariant</key>        <string>Acidanthera\GoldenGate</string>
  <key>PollAppleHotKeys</key>     <true/>
  <key>ShowPicker</key>           <true/>
  <key>TakeoffDelay</key>         <integer>10000</integer>
  <key>Timeout</key>              <integer>5</integer>
</dict>
```

### 2.5 三个条目的名字与图标

#### 2.5.1 条目怎么产生，以及显示顺序

`KNOWN`，官方的 display order 规则（转述自同一来源）：alternate 选项跟在对应的 primary 选项之后，即 **Apple recovery 选项会尽可能跟在相关的 macOS 选项后面**；选项按文件系统句柄的固件顺序排列，以便在重启之间保持稳定顺序，不受选了哪个系统影响；**自定义条目、工具、system 条目排在全部其他选项之后**；auxiliary 选项只在 Extended Mode 下显示。

把三个条目各自的产生途径与预期位置列清：

| 条目 | 产生途径 | 预期位置 | 名字从哪来 | 图标从哪来 |
|---|---|---|---|---|
| **macOS** | p3 的 APFS 容器，标准 bless 路径 | 第 1 位 | APFS volume group 的卷名 | Preboot per-volume 目录的 `.VolumeIcon.icns`，否则 `Apple.icns` |
| **macOS Base System** | p2 的标准 bless 路径 | 第 2 位（若被判为 alternate 则紧跟 macOS） | 卷名，或 `.contentDetails` | `.VolumeIcon.icns`，或 `AppleRecv.icns` / `Apple.icns` |
| **Rescue (Alpine)** | **`Misc/BlessOverride`**，见 2.5.3 | 第 3 位 | `.contentDetails` | `.contentFlavour` 选出的 `Alpine.icns` |

#### 2.5.2 macOS 与 Base System 两项的名字与图标

**名字：用卷名，不要用 `Misc/Entries`。** 卷名是 macOS 自己管理的，一条 `diskutil rename` 就能改，而且改完之后 Startup Disk 面板、Finder、选择器三处一致，这正是「和标准 macOS 一致」的实质内容。

```bash
# 在 guest 里跑一次，进 71 第 10 节的首启探针之后
sudo diskutil rename /                  macOS
sudo diskutil rename /System/Volumes/Data "macOS - Data"
```

**图标：放在 Preboot 卷的 per-volume 目录下。** `KNOWN`，官方在 `OC_ATTR_USE_VOLUME_ICON` 一节同时给出了做法与一条警告：Apple 自己的 picker 部分支持把卷图标放在 Data 卷根（`/System/Volumes/Data/`），**但这个做法有缺陷，因为启用 FileVault 2 之后那个文件对 OpenCanopy 与 Apple picker 都不可访问**；所以把卷图标文件放在 Preboot 卷根可同时兼容两者，而**用 Preboot 的 per-volume 位置是 OpenCanopy 下更好的选择**（转述自同一来源）。

```bash
#!/bin/sh
# /usr/local/libexec/install-volume-icon.sh <path-to-icns>
# 把卷图标装进 Preboot 的 per-volume 目录。研发期 SIP 已关（00-OVERVIEW §2.4）。
set -eu
ICNS="${1:?用法: install-volume-icon.sh /path/to/VolumeIcon.icns}"

# Preboot 在 macOS 里默认挂在 /System/Volumes/Preboot
PB=/System/Volumes/Preboot
[ -d "$PB" ] || { echo "Preboot 没挂上"; exit 1; }

# per-volume 目录名是 volume group 的 UUID，正常情况下只有一个
N=$(ls -1 "$PB" | grep -Ec '^[0-9A-F]{8}-' || true)
[ "$N" = 1 ] || { echo "Preboot 下有 $N 个 per-volume 目录，手工确认后再跑"; ls -1 "$PB"; exit 1; }
VG=$(ls -1 "$PB" | grep -E '^[0-9A-F]{8}-')

install -m 0644 "$ICNS" "$PB/$VG/.VolumeIcon.icns"
# 同时放一份在 Preboot 根，兼容 Apple 自己的 picker
install -m 0644 "$ICNS" "$PB/.VolumeIcon.icns"
sync
ls -l "$PB/$VG/.VolumeIcon.icns" "$PB/.VolumeIcon.icns"
```

**对 p2（Base System 分区）的处理不一样**，因为它不是一个 volume group，没有 Preboot。它是单个卷，所以按官方搜索顺序的第三条：**其他文件系统取卷根**。即把 `.VolumeIcon.icns` 放在 p2 卷的根目录。这一步在构建期做（Linux 上挂载那个分区写进去），不需要 guest 参与。

**`.contentDetails` 的用法**（给 p2 一个比卷名更合适的显示名）：

```bash
# 构建期，Linux 上。p2 挂在 /mnt/basesystem
printf 'Recovery' > /mnt/basesystem/System/Library/CoreServices/.contentDetails
printf 'AppleRecv:Apple' > /mnt/basesystem/System/Library/CoreServices/.contentFlavour
```

两个文件都放在 **bootloader 旁边**，即 `boot.efi` 所在的目录。`KNOWN` 对于位置（官方 `0x0002` 位的描述写明 `.contentDetails` 在 bootloader 旁；`0x0080` 位的描述写明 `.contentFlavour` 同样在 bootloader 旁）；`INFERRED` 对于「写了之后 p2 就会显示成 Recovery 并用 `AppleRecv.icns`」，这是 L-002 的验证内容。

**`AppleRecv:Apple` 这个 flavour 串是刻意的两级**：第一优先级 `AppleRecv.icns`（GoldenGate 里有），缺失时退到 `Apple.icns`（也有）。按官方的 flavour 算法，缺一个就试下一个，全缺才按条目类型选。这样即使以后换图标集也不会变成通用硬盘图标。

#### 2.5.3 Alpine 这一项：用 `BlessOverride`，不要用 `Misc/Entries`

这是一个容易做错的选择，两种做法的差别是决定性的。

`KNOWN`，官方对两者的描述（转述自同一来源）：

- **`Misc/Entries`**：「条目指定外部启动选项，因此 `Path` 键取的是 device path。应当小心，因为这些值不会被检查。」给的示例是 `PciRoot(0x0)/Pci(0x1,0x1)/.../\EFI\COOL.EFI`。
- **`Misc/BlessOverride`**：「通过 bless 模型添加自定义扫描路径。」填入含**绝对 UEFI 路径**的字符串，例如 Debian 的 `\EFI\debian\grubx64.efi`。「这让非标准的启动路径能被 OpenCore picker 自动发现。设计上它们等价于预定义的 blessed 路径，例如 `\System\Library\CoreServices\boot.efi` 或 `\EFI\Microsoft\Boot\bootmgfw.efi`，但与预定义 bless 路径不同，它们优先级最高。」

**`Misc/Entries` 在本项目上是错的，理由是 device path 不稳定。** `71` 第 7 节要在 L1 上把 AHCI、NVMe、virtio-blk 三个控制器各跑一遍，而 `71` 第 7.5 节说 Vultr 的控制器型号未知（`80` 的 H-001）。device path 里含 `Sata(...)` / `NVMe(...)` / `Pci(...)` 段，**换一个控制器它就全变了**。一个写死 device path 的条目在控制器变化时会静默消失，而消失的表现是「选择器里少一项」，在无头机器上无法归因。

**`BlessOverride` 只写卷内相对路径，与控制器、与分区号、与盘的呈现方式全部无关。** 这是它在本项目上压倒性胜出的唯一理由。

```xml
<key>BlessOverride</key>
<array>
  <string>\EFI\rescue\grubx64.efi</string>
</array>
<key>Entries</key>
<array/>
```

配套的三个文件放在 ESP 的 `\EFI\rescue\` 里（第 3.2 节的布局）：

```text
ESP:\EFI\rescue\
├─ grubx64.efi          ← GRUB，与 \EFI\BOOT\BOOTX64.RESCUE.efi 逐字节相同
├─ grub.cfg             ← 第 4.6 节的版本
├─ .contentDetails      ← 文本 "Rescue"，无换行
└─ .contentFlavour      ← 文本 "Alpine:Linux:HardDrive"，无换行
```

**`Alpine:Linux:HardDrive` 这个三级 flavour 串的每一级都有用**：`Alpine.icns` 是我们自己加的（2.3 节目录树的最后一行）；`Linux.icns` 是将来换用第三方图标集时大概率会有的名字；`HardDrive.icns` 是 GoldenGate 里的强制图标，保证最差情况也有图标而不是空白。

**`Alpine.icns` 怎么来**：`.icns` 是 Apple 的图标容器格式，Windows 上用 `py` + 标准库拼不出来。三条路，按成本排：

1. **最省事：不要它。** flavour 串的第三级 `HardDrive.icns` 保证有图标。代价是 Alpine 项的图标和一块普通硬盘一样。
2. **用 Alpine 官方的 PNG 转。** 需要一个 `png2icns` 一类的工具，Linux 上 `libicns` 的 `png2icns` 可用（构建机上一条 `apt install icnsutils`）。`INFERRED`，未实测 OpenCanopy 对 `png2icns` 产物的兼容性。
3. 从社区图标包里取一个。`INFERRED`，官方文档只说「自定义图标可以在网上找到」，没有指名来源；引入第三方美术资源要单独做许可核查。**不要在没做核查的情况下把别人的图标打进我们的镜像。**

**选 1 作为默认，2 作为可选步骤。** 登记为 L-005。

#### 2.5.4 必须加一个 `.contentVisibility`，否则选择器里会多出第四项

**这是本节唯一的一个「不加就会出错」的项，而且它不显眼。**

`KNOWN`，官方 Boot Algorithm 里有一句关键：「**在 OpenCore 的启动分区上，用 header 检查排除 OpenCore 的 bootstrap 文件。**」（转述自同一来源）即 OpenCore 知道不要把自己的 `\EFI\BOOT\BOOTX64.EFI` 显示成一个启动项，判据是**文件头检查**。

而 `74` 第 3.2 节把 `\EFI\BOOT\BOOTX64.EFI` 换成了我们自己写的 shim（`cpudispatch.c`，mingw-w64 编译的 PE）。**它的文件头不是 OpenCore 的 bootstrap 头。** 所以 `INFERRED`：OpenCore 的 header 检查认不出它，于是它会作为 ESP 上的一个标准 removable-media 启动项出现在选择器里。选中它会重入 shim，而 shim 会再 `boots++` 一次。

官方给的解法正好覆盖这个位置。`KNOWN`：`.contentVisibility` 文件可以放在 bootloader 旁边，官方给出的示例位置之一**逐字就是 `/Volumes/{ESP}/EFI/BOOT/.contentVisibility`**；文件内容是 ASCII 的 `Disabled` 或 `Auxiliary`（可带实例列表前缀），`Disabled` 表示排除该条目。同一段还有一条警告：**不建议把 `.contentVisibility` 放在非 macOS 的卷根位置（例如 ESP 根），因为那会隐藏该盘上的全部条目。** 还有一条格式注意：**文件里不要有多余空格，空格会被当成 token 的一部分而不是空白。**

所以：

```bash
# 构建期，放进 ESP。注意：不带换行、不带空格、不带 BOM
printf 'Disabled' > "$STAGE/EFI/BOOT/.contentVisibility"
```

**放在 `\EFI\BOOT\` 里，不是 ESP 根。** 前者只影响这个目录里的 bootloader（即 shim），后者会把 Alpine 那一项也一起藏掉。

**顺带确认 `\EFI\BOOT\` 里另外三个文件不会产生条目**：`BOOTX64.DISPATCH.efi`、`BOOTX64.OC.efi`、`BOOTX64.RESCUE.efi` 都不在预定义 bless 路径上（预定义的只有 `BOOTX64.EFI` 这个名字），也不在 `BlessOverride` 列表里，所以不会被扫到。`INFERRED`。这也是 2.5.3 节要在 `\EFI\rescue\` 另放一份 GRUB 的原因：`\EFI\BOOT\BOOTX64.RESCUE.efi` 那一份是给 `73` 第 5.3.2 节的文件交换机制用的，不是给选择器用的。

**两份 GRUB 必须一致，这要做成构建期门禁：**

```powershell
# 接 stage-efi.ps1 末尾
$a = (Get-FileHash -Algorithm SHA256 "$STAGE\EFI\BOOT\BOOTX64.RESCUE.efi").Hash
$b = (Get-FileHash -Algorithm SHA256 "$STAGE\EFI\rescue\grubx64.efi").Hash
if ($a -ne $b) { throw "两份 GRUB 不一致: $a vs $b" }
```

### 2.6 无头环境下风格对齐的真实价值

**这一节必须写清，否则会做出一个需要有人看屏幕的引导链。**

`73` 第 1.3 节与 `80` 第 1.3 节的平台事实（`KNOWN`，不重新论证）：Vultr 的控制台是网页 noVNC，API 不提供可编程的 VNC 端点，所以云侧**不能程序化截图或注入输入**；也没有串口。`80` 第 2.2 节的能力对照表里，「host 层截图」与「host 层输入注入」两行在 Vultr 一列都是空的。

**直接推论，三条，按重要性：**

1. **选择器的视觉效果在 L2 上没有任何观察者。** 它渲染得像 Apple 还是像 2005 年的 Mac OS X，在一台没有可编程画面的机器上是同一件事。风格对齐的收益**完全落在 L1 与人工排障**：L1 有 QMP `screendump`（`80` 第 2.3 节），人工排障有网页控制台。
2. **自动化路径必须是「`Timeout` 到了自动走默认项」，不许有任何一步依赖按键。** 这条是硬纪律，具体包括：
   - `Timeout` 不许为 0（2.4.3 节）。
   - 不许把「进 recovery」设计成「按 `CMD+R`」。要进恢复必须有一条不按键的途径，那就是第 4 节的状态文件机制。
   - 不许把「跳过某个坏的启动项」设计成「手工在选择器里选另一个」。`AllowSetDefault` 留着是给人用的，不是给流水线用的。
   - 不许依赖 `HideAuxiliary` 的「按空格进 Extended Mode」。
3. **把「选择器出现了」当作一个日志事件而不是一个画面事件。** OpenCore 的 DEBUG 构建会把条目扫描结果写进日志（`OCB:` 前缀），而 `71` 第 9 节已经把日志同时送到串口（L1）与 ESP 文件（两层都有）。所以「三个条目都在、名字对、默认项是哪个」这些问题全部可以**读文本**回答，不需要看图。这是本节最有用的一条：**风格对齐的验证手段是截图，布局正确性的验证手段是日志，两者不要混。**

**一条给所有者的直话：** 「OpenCore 的配置风格和标准 macOS 选择器保持一致」这个要求是合理的，但它的收益在本地开发体验与人工排障，不在云上部署。第 2 节给出的配置让它在**有人看的时候**像 Apple，同时第 2.4.3 节的分档保证**没人看的时候**它不会卡住。这两件事必须同时成立，只做前者会造出一台需要有人按键才能启动的服务器。

### 2.7 与 `74` 的 shim 的兼容性，以及 `make-oc-config.py` 的增量

**兼容性结论：OpenCanopy 与 shim 完全不冲突，因为两者在引导链上的位置不重叠。**

```text
固件 → \EFI\BOOT\BOOTX64.EFI（shim）
          ├─ 只读 CPUID / FXSAVE / CR4，不读 NVRAM（74 §2.6 的纪律）
          ├─ 写 \EFI\CPUDISP\STATE.TXT 与 LOG.TXT
          ├─ 把选定的候选 plist 复制成 \EFI\OC\config.plist
          └─ LoadImage/StartImage \EFI\OC\OpenCore.efi
                  └─ 读它刚被写好的 config.plist
                      └─ PickerMode = External → 加载 OpenCanopy.efi
                          └─ 读 \EFI\OC\Resources\
```

三条必须保持的约束：

1. **`74` 第 3.2 节「没有任何一项放在 `\EFI\OC\` 里面」的纪律不被破坏。** 本文新增的东西分两类：`\EFI\OC\Resources\` 与 `\EFI\OC\Drivers\OpenCanopy.efi` 属于 OpenCore 自己的目录结构（shim 不碰）；`\EFI\rescue\` 与 `\EFI\BOOT\.contentVisibility` 在 `\EFI\OC\` 外面。**shim 唯一写进 `\EFI\OC\` 的文件仍然只有 `config.plist`。**
2. **五份候选 plist 必须都带 OpenCanopy 配置。** `74` 第 4.4 节的 `make-oc-config.py` 产 5 份 plist，差异只在 `Cpuid1Data` / `Kernel/Patch` / boot-args。**选择器配置是五份共有的基底**，不能只改一份。下面的增量就是加在那个共有基底上的。
3. **`LauncherOption` 保持 `Disabled`。** 2.2 节已经说明这是放弃 `OpenLinuxBoot` 的原因；这里再记一次它也是 shim 存活的前提。

**`scripts/make-oc-config.py` 的增量**（接 `74` 第 4.4 节那一版，只给新增的函数与调用）：

```python
# ---- 接 74 §4.4 的 make-oc-config.py。新增一个与 tier 无关的共有基底 ----

PICKER_PROFILES = {
    # picker 档位 -> (PickerMode, ShowPicker, Timeout, PickerAttributes, canopy_enabled)
    'visible': ('External', True,  5, 0xD3, True),   # 默认交付档（76 §2.4.3）
    'apple':   ('External', False, 3, 0xD3, True),   # Apple 行为，按 OPT 才出
    'builtin': ('Builtin',  True,  5, 0x11, False),  # 排障档（71 §6.6.1 的原值）
}

OC_VENDOR_GUID   = '4D1FDA02-38C7-4A6A-9CC6-4BCCA8B30102'
APPLE_VENDOR_GUID = '4D1EDE05-38C7-4A6A-9CC6-4BCCA8B38C14'


def apply_picker(c, profile='visible'):
    """把 76 分册第 2 节的选择器配置施加到一份 config 上。与 tier 无关。"""
    mode, show, timeout, attrs, canopy = PICKER_PROFILES[profile]

    c['Misc']['Boot'].update({
        'HideAuxiliary':        False,   # 76 §2.4.4
        'HibernateMode':        'None',
        'HibernateSkipsPicker': False,
        'InstanceIdentifier':   '',
        'LauncherOption':       'Disabled',   # 74 §3.5，不许改
        'LauncherPath':         'Default',
        'PickerAttributes':     attrs,
        'PickerAudioAssist':    False,
        'PickerMode':           mode,
        'PickerVariant':        'Acidanthera\\GoldenGate',   # 76 §2.4.1
        'PollAppleHotKeys':     True,
        'ShowPicker':           show,
        'TakeoffDelay':         10000,   # 76 §2.4，官方建议下限
        'Timeout':              timeout, # 绝对不许为 0
    })

    # Alpine 这一项靠 BlessOverride，不靠 Entries（76 §2.5.3）
    c['Misc']['BlessOverride'] = ['\\EFI\\rescue\\grubx64.efi']
    c['Misc']['Entries'] = []

    # 界面背景与缩放。GUID 与 71 §6.7 的 7C436110 是不同的 GUID，是新增
    c['NVRAM']['Add'].setdefault(APPLE_VENDOR_GUID, {}).update({
        'DefaultBackgroundColor': bytes.fromhex('00000000'),  # Syrah Black
        'UIScale':                bytes.fromhex('01'),        # 普通 DPI
    })
    c['NVRAM']['Delete'].setdefault(APPLE_VENDOR_GUID, [])
    for k in ('DefaultBackgroundColor', 'UIScale'):
        if k not in c['NVRAM']['Delete'][APPLE_VENDOR_GUID]:
            c['NVRAM']['Delete'][APPLE_VENDOR_GUID].append(k)

    # 驱动表：OpenCanopy 跟着档位开关；HfsPlus.efi 的文件名修正见 76 §2.2
    want = {
        'OpenRuntime.efi':     True,
        'HfsPlus.efi':         True,
        'OpenCanopy.efi':      canopy,
        'ResetNvramEntry.efi': True,
        'ToggleSipEntry.efi':  True,
    }
    for d in c['UEFI']['Drivers']:
        if d['Path'] in want:
            d['Enabled'] = want.pop(d['Path'])
    for path, en in want.items():       # Sample 里没有的条目补进去
        c['UEFI']['Drivers'].append(
            {'Arguments': '', 'Comment': 'added by 76', 'Enabled': en,
             'LoadEarly': False, 'Path': path})

    # OpenCanopy 需要图形输出与键盘；指针由固件提供，AMI 专用的那条保持关闭
    c['UEFI']['Output'].update({'ProvideConsoleGop': True,
                                'TextRenderer': 'BuiltinGraphics'})
    c['UEFI']['Input'].update({'KeySupport': True, 'KeySupportMode': 'Auto',
                               'PointerSupport': False})
    return c
```

**`UEFI/Input/PointerSupport` 保持 `false` 是刻意的，不是遗漏。** `71` 第 6.9.2 节设它为 `false` 的理由是「`Builtin` 不用鼠标」，切到 OpenCanopy 之后理由变了但结论不变：这个键打开的是 OpenCore 自己实现的指针驱动（针对缺少标准指针协议的固件），而 OVMF 在挂了 `-device usb-tablet` 时自己就发布绝对指针协议，OpenCanopy 直接用它。**打开 `PointerSupport` 会多出一层与固件驱动竞争同一设备的可能。** `INFERRED`，登记为 L-006：若 L1 上 OpenCanopy 的鼠标不动，先试把 `PointerSupport` 打开，而不是先去改 QEMU 的输入设备。

---

## 3. 三卷与三启动项的共存

### 3.0 先把「卷」「分区」「启动项」三个词对齐

所有者说的「三卷」是三个**启动项**。本文把三个词分开用，混用会把第 1 节的结论重新搅乱：

| 所有者的说法 | 本文的术语 | 物理形态 |
|---|---|---|
| macOS 系统盘 | 启动项 1 | p3 的 APFS **容器**，容器内 4 个**卷**（System / Data / Preboot / VM） |
| macOS 恢复盘 | 启动项 2 | p2 这一个 GPT **分区**，里面一个卷（BaseSystem） |
| Alpine 救援系统 | 启动项 3 | **没有自己的分区**，kernel 与 initramfs 在 ESP 上，根文件系统在 RAM 里 |

**所以最终的 GPT 上只有三个分区，而启动项是三个，而 APFS 卷是四个。** 三个数字恰好有两个相等，这是巧合，不要当成对应关系。

### 3.1 GPT 分区表

接 `73` 第 5.2 节。**本文对它有一处结构性修改：去掉 p2 的 ext4 `RESCUE` 分区。** 修改理由在 3.3 节，修正登记在第 6 节。

```text
/dev/vda   瘦镜像，虚拟容量 24 GB（下限 20 GB，见 3.5 节）
├─ p1  EFI System Partition         C12A7328-F81F-11D2-BA4B-00A0C93EC93B
│      FAT32, 512 MiB, label OPENCORE
│      OpenCore + 74 的 shim 与 5 份候选 config + 73 的状态文件
│      + 选择器资源 + Alpine 的 kernel/initramfs/modloop/apkovl
│      详见 3.2
├─ p2  Apple APFS  7C3457EF-0000-11AA-AA11-00306543ECAC   ← L-007 已关闭，见第 7 节
│      1600 MiB, 卷名 "macOS Base System"
│      内容取自 DMG 的**第 3 个分区**（Apple_APFS，1,396,506,624 字节），不是整个 DMG
│      内容 = 71 §1.5 还原出的 x86_64BaseSystem.dmg 的卷镜像
│      1,464,270,504 字节, SHA-256 642E6148288527C51639D1B08C7F0B5A8CB4A68AEC2AC6DA3C78CF1723C5119A
└─ p3  Apple APFS                   7C3457EF-0000-11AA-AA11-00306543ECAC
       剩余全部，macOS 26.7.2 的 APFS 容器
       容器内 4 个卷：System / Data / Preboot / VM（第 1.4 节）
       首启由 firstboot-expand LaunchDaemon 扩满（73 §4.6.2）
```

**顺序约束，三条，全部满足：**

1. **APFS 必须在最后。** `73` 第 4.6.2 节的首启扩容是 `diskutil apfs resizeContainer <PHYS> 0`，`0` 的含义是吃掉到下一个分区或分区表末尾之间的全部空间。p3 之后没有分区，所以它能一直扩到盘尾。`KNOWN`（`73` 第 5.2 节的同一约束，本文沿用）。
2. **ESP 必须是第一个 FAT 分区。** `73` 第 2.3 节记录了 `reinstall` 的做法是「找出第一个 FAT/vfat 分区当落脚点，不关心它是不是正式的 ESP」。我们只有一个 FAT 分区，所以不存在选错的可能。
3. **p2 在 p1 与 p3 之间，不在最后。** 理由与 `73` 把 rescue 放 p2 相同：它后面必须留给 APFS。

**类型 GUID 怎么定：取决于 BaseSystem 卷的实际文件系统，必须先判定再写。** `71` 第 8.2.3 节已经给了判定命令（`dd if=... bs=1 skip=32 count=4 | xxd`，看是 APFS 的 `NXSB` 还是 HFS+ 的 `H+`）。两种情况的 GUID：

| 判定结果 | 分区类型 GUID | 需要的 UEFI 文件系统驱动 |
|---|---|---|
| APFS（`NXSB`） | `7C3457EF-0000-11AA-AA11-00306543ECAC` | 容器自带的 `apfs.efi`，靠 `UEFI/APFS/EnableJumpstart` |
| HFS+（`H+`，即 `0x482B`） | `48465300-0000-11AA-AA11-00306543ECAC` | **`HfsPlus.efi`**（2.2 节），这正是 `71` 第 2.4 节路 B 那条官方说明的理由：已知的 recovery 卷都是 HFS+ 文件系统 |

**两种情况我们都已经配好驱动**（`EnableJumpstart = true` 且 `HfsPlus.efi` 启用），所以判定结果不影响配置，只影响这一个 GUID。登记为 L-007：判定必须在造第一个镜像之前做掉，它是一条 15 秒的命令。

**可照抄的建表命令**（Linux，接 `73` 第 4.5.1 节的投放脚本；在空白盘或镜像文件上执行）：

```bash
#!/usr/bin/env bash
# scripts/mk-gpt.sh <target: /dev/vdX 或 image.raw> <basesystem-fs: apfs|hfs>
# 造 76 §3.1 的三分区 GPT。不写任何数据，只建表。
set -euo pipefail
T="${1:?target}"; FS="${2:?apfs|hfs}"

case "$FS" in
  apfs) P2TYPE=7C3457EF-0000-11AA-AA11-00306543ECAC ;;
  hfs)  P2TYPE=48465300-0000-11AA-AA11-00306543ECAC ;;
  *) echo "第二个参数只能是 apfs 或 hfs"; exit 2 ;;
esac

# 这一步会毁掉目标盘上的一切。73 §2.2 的纪律：破坏性操作只在 rescueOS 里做
sgdisk --zap-all "$T"
sgdisk -o \
  -n 1:2048:+512M -t 1:C12A7328-F81F-11D2-BA4B-00A0C93EC93B -c 1:"EFI System Partition" \
  -n 2:0:+1600M   -t "2:$P2TYPE"                            -c 2:"macOS Base System" \
  -n 3:0:0        -t 3:7C3457EF-0000-11AA-AA11-00306543ECAC -c 3:"macOS" \
  "$T"

# GPT 备份表必须在盘尾。73 §4.6.2 要求这一步在 Linux 侧做，不要指望 macOS
sgdisk -e "$T"
sgdisk -p "$T"
sgdisk -v "$T"      # 校验。任何 problem 都必须在写数据之前解决
```

**`sgdisk -e` 这一行不许省。** `73` 第 4.6.2 节的注意点 1 已经论证过：它是一条确定的非交互命令，而 macOS 侧的等价物 `diskutil repairDisk` 交互且行为不可预测。首启扩容依赖备份表位置正确。

### 3.2 ESP 内布局

合并四处来源：`71` 第 8.2.2 节（OpenCore 骨架）、`73` 第 5.2 节与第 5.3.2 节（引导对象交换与状态文件）、`74` 第 3.2 节（shim 与候选 config）、本文（选择器资源、Alpine、可见性控制）。

```text
ESP (FAT32, 512 MiB, label OPENCORE)
│
├─ /EFI/BOOT/
│   ├─ BOOTX64.EFI                  ← 当前生效的引导对象（73 §5.3.2 交换的那个文件）
│   ├─ BOOTX64.DISPATCH.efi         ← 74 的 shim（macOS 态下 BOOTX64.EFI 的来源）
│   ├─ BOOTX64.OC.efi               ← OpenCore 自带 BOOTx64.efi 的副本（人工逃生口）
│   ├─ BOOTX64.RESCUE.efi           ← GRUB 的副本（shim 在 rescue 档链载它）
│   └─ .contentVisibility           ← 文本 "Disabled"，本文新增，见 2.5.4
│
├─ /EFI/OC/                          ← 完全按 71 §6 的布局，shim 只写其中的 config.plist
│   ├─ OpenCore.efi
│   ├─ config.plist                  ← 由 shim 每次启动写入
│   ├─ config.known-good.plist       ← 73 §5.4 R1 层的回滚副本
│   ├─ ACPI/
│   │   └─ SSDT-EC.aml               ← 第 5 节：唯一必需的 SSDT
│   ├─ Drivers/
│   │   ├─ OpenRuntime.efi
│   │   ├─ HfsPlus.efi               ← 文件名修正，见 2.2
│   │   ├─ OpenCanopy.efi            ← 本文新增
│   │   ├─ ResetNvramEntry.efi
│   │   ├─ ToggleSipEntry.efi
│   │   └─ Virtio*.efi               ← 四个，Enabled=false，L2 兜底用（71 §7.3）
│   ├─ Kexts/
│   │   ├─ Lilu.kext
│   │   ├─ VirtualSMC.kext
│   │   └─ AppleMCEReporterDisabler.kext
│   ├─ Resources/                    ← 本文新增，见 2.3
│   │   ├─ Font/
│   │   ├─ Image/Acidanthera/GoldenGate/
│   │   └─ Label/
│   └─ Tools/
│       └─ OpenShell.efi             ← 文件留着，Misc/Tools 里不启用（71 §6.9.1）
│
├─ /EFI/CPUDISP/                      ← 74 §3.2 新增的目录
│   ├─ 00-intel-native.plist          ← 五份候选，每一份都带第 2 节的选择器配置
│   ├─ 01-intel-spoof.plist
│   ├─ 02-intel-hardened.plist
│   ├─ 03-amd.plist
│   ├─ 04-safe.plist
│   ├─ STATE.TXT                      ← 512 字节定长，格式见 4.3（本文加两个键）
│   ├─ LOG.TXT                        ← shim 每次启动追加一段
│   ├─ ALIVE.TXT                      ← 本文新增：macOS 侧的活着面包屑，见 4.5
│   ├─ REPORT.TXT                     ← 本文新增：Alpine 侧写的诊断报告，见 4.6
│   ├─ FAILMAX                        ← 本文新增，可选：覆盖「三次」这个阈值，见 4.3
│   ├─ STICKY                         ← 本文新增，可选：预算耗尽后钉在 rescue，见 4.4
│   ├─ NOAMD                          ← 74 §2.8 的安全阀，可选
│   └─ PANIC/                         ← 73 §5.4 R1 要求的 panic 信箱，macOS 侧写入
│
├─ /EFI/rescue/
│   ├─ grubx64.efi                    ← 与 BOOTX64.RESCUE.efi 逐字节相同（2.5.4 门禁）
│   ├─ grub.cfg                       ← 第 4.6 节的版本
│   ├─ .contentDetails                ← 文本 "Rescue"
│   └─ .contentFlavour                ← 文本 "Alpine:Linux:HardDrive"
│
├─ /boot/                             ← 本文新增：Alpine 的三件套，按 Alpine 启动介质布局
│   ├─ vmlinuz-virt                   ← 11 MB
│   ├─ initramfs-virt                 ← 9 MB
│   └─ modloop-virt                   ← 20 MB
│
├─ /apks/x86_64/                       ← 本文新增：本地 apk 仓库，见 4.6.3
│   ├─ APKINDEX.tar.gz
│   └─ *.apk                           ← openssh 及其依赖，约 10 MiB
│
├─ /rescue.apkovl.tar.gz               ← 本文新增：SSH 预配包，见 4.6.2
├─ /.alpine-release                    ← 本文新增：启动介质标记，见 4.6.1
├─ /boot-mode                          ← 73 §5.3.2：单行文本 macos | rescue
├─ /boot-revert                        ← 73 §5.3.2：一次性标记
└─ /panic-YYYY-MM-DD-HHMMSS.txt        ← OpenCore 的 ApplePanic 落盘（71 §6.6.4）
```

**三条关于这个布局的纪律：**

1. **`/boot/` 这个目录名与 `/boot-mode` 这个文件名不冲突**（一个是目录，一个是文件，FAT 上是两个不同的目录项）。但它们挨得太近，容易在脚本里写错。**纪律：凡是操作这两者的脚本都用完整路径，不许用通配。**
2. **`/EFI/CPUDISP/` 下的五个新文件里有三个是「存在即生效」的开关**（`FAILMAX`、`STICKY`、`NOAMD`）。构建期的 ESP **必须一个都不带**，它们只能由运行期的 shim、Alpine 或运维手工创建。构建脚本里要有一条断言。
3. **`/apks/` 与 `/boot/` 是 Alpine 的东西，放在 ESP 根而不是 `/EFI/` 下面。** 这是刻意的：Alpine 的 init 在启动介质上找这两个路径时用的是介质根的相对路径（4.6.1 节），放进 `/EFI/` 要额外的内核参数。

### 3.3 Alpine 的两种形态：独立分区 vs ESP + RAM

任务要求评估两种方案。先把两种方案的确切形态写清，再给数据，再给结论。

#### 3.3.1 两种方案的确切形态

**方案 A（ESP + RAM）**：Alpine 的 `vmlinuz-virt` / `initramfs-virt` / `modloop-virt` 三个文件放在 ESP 的 `/boot/` 下，GRUB 从 ESP（FAT，GRUB 原生支持）读它们，Alpine 的根文件系统在 RAM 里展开，配置由 ESP 根的 `rescue.apkovl.tar.gz` 提供。**不占独立分区。**

**方案 B（独立 ext4 分区）**：即 `73` 第 5.1 节选定的候选 B。一个 1.5 GiB 的 ext4 分区，装 Alpine 的 `sys` 模式（真正的磁盘安装），内核与模块本地化，sshd 与公钥预配好。

#### 3.3.2 决定性的数据：`virt` flavour 把体积问题消掉了

`KNOWN`，本轮直接读取 Alpine 官方镜像站的 netboot 目录索引（<https://dl-cdn.alpinelinux.org/alpine/v3.22/releases/x86_64/netboot/>，索引时间戳 2026-10-21，内核版本 `6.12.114-0`）：

| 文件 | 体积 | 用途 |
|---|---:|---|
| `vmlinuz-lts` | 13M | 通用内核 |
| `initramfs-lts` | 25M | 通用 initramfs |
| **`modloop-lts`** | **209M** | 通用内核模块 squashfs |
| `vmlinuz-virt` | **11M** | **虚拟机专用内核** |
| `initramfs-virt` | **9M** | 虚拟机专用 initramfs |
| **`modloop-virt`** | **20M** | **虚拟机专用模块 squashfs** |

**`lts` 与 `virt` 两套三件套的合计是 247 MB 对 40 MB，差 6 倍，而差额几乎全在 modloop。** 原因是 `virt` flavour 只编进虚拟化平台需要的驱动。

这一条数据直接改变了方案 A 的可行性判断。`73` 第 2.4 节讨论 netboot 时隐含的是 `lts` 那一套（`reinstall` 取的是 `vmlinuz-<flavour>` / `initramfs-<flavour>` / `modloop-<flavour>`，而它的通用做法是 `lts`），247 MB 装不进一个 256 MiB 的 ESP。**40 MB 可以，而且绰绰有余。**

**我们完全有资格用 `virt`**：`00-OVERVIEW` 第 2.1 节的部署形态就是 KVM guest，`73` 第 5.1 节对 rescue 的全部要求是「能起网络、能跑 sshd、能读 FAT」，这些驱动在 `virt` 里都有。`INFERRED`（未逐个核对 `virt` 的内核配置里有 `CONFIG_VIRTIO_BLK` / `CONFIG_VFAT_FS` / `CONFIG_SQUASHFS`），登记为 L-008，查清方法是下载 `config-6.12.114-0-virt`（146 KB，同一目录）并 grep 那几个符号。**这是一条不需要任何实验、现在就能做掉的检查。**

#### 3.3.3 两种方案逐项对照

| 维度 | 方案 A（ESP + RAM） | 方案 B（独立 ext4 分区） |
|---|---|---|
| 占盘 | **0 个分区**，ESP 内 +50 MiB（含 apks） | 1 个分区，1.5 GiB |
| 持久性 | 根在 RAM，重启丢。**配置由 ESP 上的 apkovl 恢复，所以每次都是同一个已知状态** | 根在盘上，改动持久 |
| 进入方式 | shim 链载 `BOOTX64.RESCUE.efi`（GRUB），GRUB 从 FAT 读三件套 | 同样，但 GRUB 要读 ext4 |
| 需要的文件系统驱动 | **一个都不多要。** GRUB 原生读 FAT；OpenCore 不需要读它 | GRUB 需要 ext4 模块（GRUB 自带）；若想让 OpenCore 直接发现它则需要 OcBinaryData 的 `ext4_x64.efi` |
| macOS 会不会动它 | **不会。** ESP 是 macOS 自己也要用的 FAT 卷，`msdosfs` 在 System KC 内（`71` 第 8.4 节，`KNOWN`） | **未确证。** `73` 第 5.2 节的 D-010：macOS 对 ext4 分区的实际行为未实测，可能显示 unknown 甚至试图「修复」 |
| 升级 Alpine | 换三个文件 | 重装一个分区 |
| 能不能预装额外工具 | **不能直接装**，要靠 ESP 上的本地 apk 仓库（4.6.3） | 能，装进分区即可 |
| 内存占用 | `73` 第 2.4 节记录的下限是 256 MB RAM。我们的实例 ≥8 GB | 更低 |
| 「系统盘整块写坏」时能不能救 | **不能**（与 B 相同，两者都在系统盘上） | 不能 |
| 与 `73` 第 2.7 节的 Vultr 软 RAID 观察的关系 | **更安全。** 那条观察说固件在 `BootNext` 快速路径下可能只初始化存放 EFI 文件的那块盘。方案 A 的全部文件都在 ESP 上，即「那块盘」上 | 略差。ext4 分区在同一块盘上，但 GRUB 要再做一次设备发现 |
| 失败模式 | GRUB 读不到 FAT 上的内核 → GRUB 菜单超时落到第二条，回 shim（`74` 第 4.7 节的 grub.cfg） | 同上，另加 ext4 损坏这一类 |

#### 3.3.4 结论：选 A，并把 B 留在台面上

**选方案 A。** 四条理由，按权重：

1. **它去掉了一整类未确证前提。** `73` 的 D-010（macOS 对 ext4 分区的行为）与「GRUB 能不能读这块 ext4」两条在方案 A 下不存在。本项目的 `BLOCKED` / `INFERRED` 已经很多，能用一个设计决定消掉两条就该消掉。
2. **「每次都是同一个已知状态」是救援系统最该有的性质。** 方案 B 的持久性是双刃的：一次失败的救援操作会留在盘上，下一次救援从一个被改过的状态开始。方案 A 的 RAM 根 + ESP 上的 apkovl 让每次救援都从同一个起点开始，而这个起点是构建期就定好、可审计的纯文本（`73` 第 2.4 节末句对 apkovl 的评价就是「产物是纯文本可审计的」）。
3. **ESP 是两边都能读写的唯一卷。** `73` 第 5.3.3 节的全部状态交换、`74` 第 4.6 节的确认回写、第 4.5 节的面包屑、第 4.6 节的报告，全部落在 ESP 上。把 Alpine 也放上去之后，**整条救援链路只依赖一个文件系统**，而那个文件系统 macOS、Alpine、GRUB、OpenCore、OVMF 五方都能读。这个性质的价值很难高估。
4. **`virt` flavour 的 40 MB 让体积不再是理由。** 这是 3.3.2 节的数据。

**B 保留在台面上的两个具体触发条件**（不是「以后再说」，是可判定的条件）：

- **L-008 查出 `virt` 缺某个必需驱动。** 那时第一选择是换回 `lts`（247 MB，ESP 要扩到 1 GiB），第二选择才是方案 B。
- **救援侧需要 `apfs-fuse` 一类不在 Alpine 官方仓库里的东西。** `73` 的 D-012 已经登记「Alpine 仓库里是否有可用的 APFS 只读驱动未确认」。如果答案是「没有，要自己编译」，那么一个能预装自编译二进制的持久分区就有了真实价值。**但 `73` 第 5.4 节 R1 层已经给了不依赖 APFS 读取的替代方案**（ESP 上的 panic 信箱，即 3.2 节布局里的 `/EFI/CPUDISP/PANIC/`），所以这个触发条件大概率不会成立。

### 3.4 ESP 从 256 MiB 扩到 512 MiB

`73` 第 5.2 节把 ESP 定在 256 MiB，理由是容纳两份 EFI 引导器、一份 GRUB 内核与 initramfs 的备份、OpenCore DEBUG 日志、ApplePanic 落盘。本文在它上面又加了三样东西（选择器资源、Alpine 三件套、本地 apk 仓库），所以要重算。

| 项 | 预算 | 依据 |
|---|---:|---|
| OpenCore DEBUG（`BOOTx64.efi` + `OpenCore.efi` + 5 个 Drivers + OpenShell） | 8 MiB | `INFERRED`，按 release 包的量级估 |
| shim 两份（`BOOTX64.EFI` + `BOOTX64.DISPATCH.efi`） | 0.1 MiB | `74` 第 3.2 节：shim 约 20 KB |
| GRUB 两份（`BOOTX64.RESCUE.efi` + `EFI/rescue/grubx64.efi`） | 2 MiB | `INFERRED` |
| kext 三个 | 2 MiB | `INFERRED` |
| `SSDT-EC.aml` | <1 KiB | 第 5 节 |
| `config.plist` × 7（生效 1 + 候选 5 + known-good 1） | 0.5 MiB | `74` 第 3.2 节：每份 40 到 60 KB |
| **选择器资源（Font + Label + GoldenGate）** | **20 MiB** | `INFERRED`，2.3 节脚本第 5 步会打印实测值。登记为 L-009 |
| **Alpine 三件套（`virt`）** | **40 MiB** | `KNOWN`，3.3.2 节 |
| **本地 apk 仓库** | **10 MiB** | `INFERRED`，4.6.3 节会给实测方法 |
| `rescue.apkovl.tar.gz` | 0.1 MiB | `INFERRED`，纯文本打包 |
| 状态与日志（`STATE.TXT` / `LOG.TXT` / `ALIVE.TXT` / `REPORT.TXT`） | 1 MiB | 需要轮转，见 4.3.4 |
| **OpenCore DEBUG 日志 + ApplePanic 落盘余量** | **64 MiB** | `71` 第 9 节。panic 文本可以很大，这是必须留的空间 |
| 合计 | **约 148 MiB** | |

**256 MiB 够用但只剩 42% 余量，512 MiB 剩 71%。** 选 512 MiB，三条理由：

1. **panic 落盘是不可预测的开销。** `ApplePanic = true` 会为每次 panic 写一个 `panic-YYYY-MM-DD-HHMMSS.txt`，而研发期的 panic 次数就是实验次数。ESP 满了之后 OpenCore 写不进日志，而「日志突然没了」在无头机器上是最坏的失败。
2. **512 MiB 的成本是 256 MiB 的盘空间，在一个 24 GB 的镜像上是 1%。** 这是本项目里性价比最高的一次预留。
3. **如果 L-008 迫使换回 `lts` flavour（+207 MiB），512 MiB 刚好还装得下**（148 - 40 + 247 = 355 MiB）。256 MiB 则直接不够。**这一条让 512 MiB 同时是一个风险缓解。**

### 3.5 容量预算与镜像下限

**容量这件事以 `75` 第 4.1 节为准，不以 `73` 第 4.6.3 节为准。** `73` 写那一节时还没有「完整安装的 System volume 自身就 11 到 15 GB」这个数，`75` 第 4.1 节已经把实占逐卷算过并给出修订建议（把「16 到 24 GB」改成「28 到 32 GB」，机型要求从「盘 ≥ 25 GB」改成「盘 ≥ 40 GB」）。本文沿用它的数，只换分区构成。

| 项 | `75` 第 4.1 节的值 | 本文的值 | 差异来源 |
|---|---:|---:|---|
| p1 ESP | 0.27 GB（256 MiB） | **0.54 GB（512 MiB）** | 本文 3.4 节：多了选择器资源、Alpine 三件套、本地 apk 仓库 |
| p2 | 1.6 GB（ext4 rescue） | **1.6 GB（BaseSystem 恢复环境）** | 本文 3.3 节：用途换了，尺寸几乎相同 |
| p3 APFS：System volume | 11 到 15 | 同 | — |
| p3 APFS：Preboot | 2 到 6 | 同 | — |
| p3 APFS：Recovery | 约 1 | **0 或约 1** | 本文 1.5.3 节：`asr` 造了就有，没造就没有 |
| p3 APFS：Data | 2 到 4 | 同 | — |
| p3 APFS：VM | 0 | 同 | — |
| **实占合计** | **18 到 28** | **18 到 28** | **几乎相同**：ESP 多 0.27，p2 的 1.6 GB 从 ext4 换成 BaseSystem，净增约 0.3 GB |
| **推荐虚拟容量** | **32 GB** | **32 GB** | 按 `73` 第 4.6.2 节的「实占 × 1.3」 |
| **下限** | **28 GB** | **28 GB** | |

**结论：本文的分区构成变化不改变 `75` 第 4.1 节算出的镜像尺寸。** 这是一个有用的巧合：去掉 1.5 GiB 的 ext4 rescue 分区省出的空间，刚好被 1.6 GiB 的 BaseSystem 分区与 0.27 GB 的 ESP 扩容吃掉。**所以 `75` 的 32 GB 推荐值与 workflow 里的 `SIZE_GB=32` 不需要改。**

**如果 L-021 查出必须压到 28 GB 以下，砍的顺序是：** 先砍 p2（省 1.6 GB，后果见 1.5.3 节末段），再把 ESP 退回 256 MiB（省 0.27 GB，后果是 panic 落盘余量从 64 MiB 降到个位数 MiB，3.4 节理由 1）。**绝不要砍 APFS 容器**，`73` 第 4.6.2 节已经论证过一个塞满到 99% 的 APFS 容器开机即出问题。

### 3.6 完整的落盘序列

把 3.1 到 3.5 串成一条带门禁的序列。**它插在 `73` 第 4.8 节流水线的「写 macOS 系统分区」之前**，并且遵守 `73` 第 1.3 节那条不变量：任何一次投放都不得让实例在「没有任何第二引导对象」的状态下重启。

```bash
#!/usr/bin/env bash
# scripts/lay-out-disk.sh <target> <efi-stage-dir> <basesystem.img> <macos.img>
# 按 76 §3.1 的布局落盘。顺序是刻意的：先救援能力，后系统。
set -euo pipefail
T="${1:?target}"; STAGE="${2:?efi stage dir}"
BS="${3:?basesystem volume image}"; OS="${4:?macos container image}"

# ---- 0. 判定 BaseSystem 的文件系统（71 §8.2.3），决定 p2 的类型 GUID ----
SIG=$(dd if="$BS" bs=1 skip=32 count=4 2>/dev/null | tr -d '\0')
case "$SIG" in
  NXSB*) FS=apfs ;;
  H+*|HX*) FS=hfs ;;
  *) echo "认不出 BaseSystem 卷签名: $(printf %s "$SIG" | xxd)"; exit 1 ;;
esac
echo "BaseSystem 文件系统 = $FS"

# ---- 1. 建表 ----
./scripts/mk-gpt.sh "$T" "$FS"
partprobe "$T" 2>/dev/null || true

# ---- 2. ESP。这一步建立"第二引导对象"，必须在写系统分区之前完成 ----
mkfs.vfat -F 32 -n OPENCORE "${T}1"
mkdir -p /mnt/esp && mount -t vfat "${T}1" /mnt/esp
cp -a "$STAGE"/. /mnt/esp/

# 构建期断言：三个"存在即生效"的开关一个都不许带（3.2 节纪律 3）
for f in FAILMAX STICKY NOAMD; do
  [ -e "/mnt/esp/EFI/CPUDISP/$f" ] && { echo "构建产物里不许有 $f"; exit 1; }
done
# 构建期断言：两份 GRUB 必须一致（2.5.4 节）
cmp /mnt/esp/EFI/BOOT/BOOTX64.RESCUE.efi /mnt/esp/EFI/rescue/grubx64.efi
# 构建期断言：shim 已经就位（74 §4.7 的修正）
cmp /mnt/esp/EFI/BOOT/BOOTX64.EFI /mnt/esp/EFI/BOOT/BOOTX64.DISPATCH.efi
# 初始状态：macOS 态
printf 'macos\n' > /mnt/esp/boot-mode
rm -f /mnt/esp/boot-revert
mkdir -p /mnt/esp/EFI/CPUDISP/PANIC
sync; umount /mnt/esp

# ---- 3. p2 恢复环境。第二个可引导目标，同样在系统分区之前 ----
dd if="$BS" of="${T}2" bs=1M status=progress conv=fsync

# ---- 4. p3 macOS 容器。最后写，因为它最大、最慢、最可能被打断 ----
#       73 §2.5 的"先留最后 1 MiB"保险在这一层仍然适用，见 73 §4.5.1
dd if="$OS" of="${T}3" bs=1M status=progress conv=fsync

# ---- 5. 盘尾备份表。扩容的前提 ----
sgdisk -e "$T"
sgdisk -v "$T"
echo "布局完成。三个启动项：p3 macOS / p2 Base System / ESP 内的 Alpine"
```

**第 2、3、4 步的顺序不许调整。** 理由是 `73` 第 1.3 节的不变量：ESP（含 shim 与 GRUB 与 Alpine）与 p2（恢复环境）是两个独立的第二引导对象，它们在 p3 被写之前就必须可用。如果先写 p3 再写 ESP，那么在 p3 写完到 ESP 写完之间的那段时间里，盘上有一个系统但没有任何引导器，一次意外重启就得到 `73` 的 S3 状态。

---

## 4. 三次启动失败自动拉救援

### 4.1 「启动失败」怎么判定：只有「确认的缺失」

这是本文最难的一点，所有者的直觉也在这里。先把不能用的办法排掉，因为每一个都看起来可行。

| 候选判据 | 为什么不行 | 标签 |
|---|---|---|
| 固件报告启动失败 | UEFI 固件只知道「`LoadImage` / `StartImage` 返回了错误」。`boot.efi` 成功启动了内核、内核三秒后 panic，在固件看来是**成功** | `KNOWN`，这是 UEFI 的启动语义 |
| OpenCore 报告失败 | OpenCore 在 `StartImage` 之后就不再拥有控制权。它同样看不到内核的任何状态 | `KNOWN`，`74` 第 4.6 节已有同一结论 |
| 看门狗定时器 | UEFI 看门狗在 `ExitBootServices` 时被解除。内核起来之后没有固件级看门狗 | `KNOWN` |
| `pvpanic` | 它**能**告诉 host「guest panic 了」（`71` 第 3.6 节，驱动在 Boot KC 内，匹配 `QEMU0001`）。但 host 在 L2 是云平台，我们拿不到 QMP 事件（`80` 第 1.3 节）。**在 L1 有用，在 L2 没有** | `KNOWN` |
| macOS 自己报告失败 | 一台起不来的 macOS 不会报告任何东西 | — |

**所以判据只能反过来写：不是「检测到失败」，而是「没有检测到成功」。**

```text
失败的定义 := 上一次启动发出去了（shim 写了 inflight=1），
              但在那次启动的生命周期里没有任何人把 inflight 清零。
```

这个定义有三个重要性质，每一个都要写清：

1. **它是一个「下一次启动时才能做出的判定」。** shim 在启动期读到 `inflight=1` 的那一刻，就知道上一次失败了。这意味着**失败的检测总是滞后一次重启**，而这正是「三次失败」这件事需要三次重启的原因。
2. **它把「失败」的范围定成了「没能走到可观测状态」，而不是「没能启动」。** 一台 panic 的机器和一台起来了但 sshd 没起来的机器，在这个定义下是同一类。**这是刻意的**，理由在 4.7 节。
3. **它依赖「谁来重启」这个外部动作。** 一台卡死但没有重启的机器不会前进到下一次判定。所以必须有人或有什么东西去重启它。L2 上这件事由 `80` 的 `Detector` 在 `boot_timeout`（`73` 第 5.4 节 R1 建议 900 秒）之后调平台 API 的 `reboot` 完成；L1 上由 harness 做。**这一条是本机制的外部依赖，必须写进 `80` 的状态机，登记为 L-010。**

### 4.2 计数与重置规则

**这张表是第 4 节的核心，其余各节都是它的实现。**

| # | 事件 | 谁执行 | 确切时间点 | 对状态的动作 |
|---|---|---|---|---|
| 1 | shim 启动，读 `STATE.TXT` | shim | `efi_main` 里，`probe()` 之后，任何 `LoadImage` 之前 | 只读 |
| 2 | `sig` 与本机不符（换了硬件/换了 plan） | shim | 读完之后立刻 | **全部归零**，含 `fails`、`cand`、`confirmed`、`boots`、`rescues`。然后 `sig` 写成本机的 |
| 3 | 每一次 shim 运行 | shim | 同上 | `boots++` |
| 4 | 读到 `inflight == 1` | shim | 同上 | **`fails++`**（这是唯一的加一点）。并且**仅当 `confirmed == 0` 时** `cand++` |
| 5 | 读到 `inflight == 0` | shim | 同上 | `fails` 不变。这覆盖两种情形：上一次被确认了，或者这是第一次启动 |
| 6 | `fails >= FAILMAX`（默认 3） | shim | 决定 tier 的那一步 | 本次 `tier = T_RESCUE`；`rescues++`；**`fails = 0`**；**`inflight = 0`** |
| 7 | 候选顺序走完（`cand >= nord`） | shim | 同上 | 本次 `tier = T_RESCUE`；`exhausted = 1`；`rescues++`；`inflight = 0` |
| 8 | 正常选中一个 CPU 档 | shim | 同上 | `inflight = 1` |
| 9 | 状态落盘 | shim | **`LoadImage` 之前**（`74` 第 3.6 节纪律 3） | 整写 512 字节 |
| 10 | macOS 起来、`launchd` 跑到 `RunAtLoad` | macOS daemon | 开机早期 | 向 `ALIVE.TXT` 追加一行 `A <ts> ...`。**不动 `STATE.TXT`** |
| 11 | sshd 在 127.0.0.1:22 上监听 | macOS daemon | 第 10 步之后最多 300 秒内 | 向 `ALIVE.TXT` 追加一行 `S <ts>`；然后整写 `STATE.TXT`：**`inflight = 0`、`confirmed = 1`、`fails = 0`、`boots = 0`**，`cand` / `sig` / `rescues` 原样保留 |
| 12 | 300 秒内 sshd 没起来 | macOS daemon | 超时 | **什么都不写**。于是下一次启动的第 4 步会 `fails++`。这是 4.7 节那个边界情形的入口 |
| 13 | Alpine 起来 | Alpine `local.d` | rescue 启动早期 | 读 `STATE.TXT` + `LOG.TXT` + `ALIVE.TXT`，写 `REPORT.TXT`；把 `\EFI\BOOT\BOOTX64.EFI` 恢复成 shim；`boot-mode` 写回 `macos`。**不动 `fails`（shim 已经清零过了），不动 `cand`** |
| 14 | `boots > BOOT_BUDGET` | shim | 第 3 步之后 | 见 4.4.3：**不再 `beacon()` 停住，改为钉在 rescue** |

**四条需要单独解释的设计决定：**

**(a) 为什么 `fails++` 与 `cand++` 分开，而且 `cand++` 多一个条件。**

`74` 第 4.8 节有一条明确的设计意图：「`confirmed` 一旦置位，阶梯就不动了。实验期的失败必须可归因，所以不许阶梯在底下偷偷换配置。」这条意图必须保住：如果一次 kext 实验把系统弄坏了，而机制偷偷把 CPU 档位也换了，那么下一次启动失败就有两个可能原因，排障成本翻倍。

同时所有者要的「三次失败拉救援」在**已确认的机器上同样必须生效**，因为那才是常见情形（一台好机器被一次实验弄坏）。

两者的结合就是第 4 行那条规则：

```text
fails++        无条件
cand++         仅当 confirmed == 0
rescue          fails >= FAILMAX 时无条件，不管 confirmed 是 0 还是 1
```

**一句话：阶梯前进只在未确认态发生，三次失败拉救援在两种态都发生。**

**(b) 为什么 rescue 这一次要把 `inflight` 清零。**

`74` 第 4.5 节的 `efi_main` 里 `s.inflight = 1` 是无条件的，包括选 rescue 的那一次。照搬会出一个具体的 bug：rescue 启动成功、Alpine 跑起来、SSH 可达，这是一次**成功**，但没有人清 `inflight`（Alpine 不是 macOS，它不该去置 `confirmed`）。于是下一次启动时 shim 看到 `inflight=1`，又 `fails++` 一次。**救援成功被记成一次失败。**

后果是阶梯推进速度翻倍：实际上是「两次 macOS 失败 + 一次 rescue」就触发下一次 rescue。

修法是选 rescue 的分支里 `inflight = 0`。**语义是「rescue 这一次不参与 macOS 的成败统计」**，这与 rescue 的角色一致：它不是候选之一，它是观测手段。

**(c) 为什么 `fails` 在拉起 rescue 的同一次就清零，而不是等 Alpine 来清。**

两条理由：

1. **Alpine 可能起不来。** GRUB 坏了、内核读不出来、`virt` 缺驱动。这时如果 `fails` 还是 3，下一次启动又会去拉 rescue，形成「拉 rescue 失败 → 再拉 rescue」的循环，而每次循环只消耗 `boots` 预算，不产生任何新信息。清零之后，Alpine 起不来的那一次之后机器会回到 macOS 档继续试，至少还在前进。
2. **状态写入必须在 `LoadImage` 之前完成**（`74` 第 3.6 节纪律 3）。所以 shim 没有「等 Alpine 的结果再决定写什么」这个选项。它必须在不知道 rescue 会不会成功的前提下把状态写完。**在这个约束下，清零是唯一不会死锁的选择。**

**(d) `FAILMAX` 为什么要可配置。**

默认 3，来自所有者的要求。但「3」这个数字对两种场景不合适：

- **长时间无人值守的实验跑批。** 一台机器可能因为网络抖动连续三次 sshd 没及时起来，然后被切到 Alpine。`FAILMAX = 8` 更合适。
- **第一次在新平台上开机。** 这时希望尽早看到 Alpine 的报告，`FAILMAX = 1` 更合适（第一次失败就切）。

实现是 ESP 上一个可选文件 `\EFI\CPUDISP\FAILMAX`，内容是一个十进制数。**存在即生效，不存在就是 3。** 这与 `74` 第 2.8 节的 `NOAMD` 安全阀同一形态，运维上一致。

### 4.3 状态文件的扩展

#### 4.3.1 格式：加两个键，不改魔数

```text
CPUDISP1
sig=1A2B3C4D
cand=2
inflight=1
confirmed=0
boots=5
exhausted=0
fails=1
rescues=0
pick=intel-hardened
<空格补齐到 512 字节>
```

**魔数保持 `CPUDISP1`，不升到 `CPUDISP2`。** 理由是 `74` 第 4.5 节的 `find_key()` 解析器对未知键是忽略的，而 `parse_u32(NULL)` 返回 0。所以：

- 新 shim 读旧文件：`fails` 与 `rescues` 解析成 0，等价于「还没失败过」，行为正确。
- 旧 shim 读新文件：忽略两个新键，退化成 `74` 的原始行为，仍然可引导。
- macOS 侧的脚本是整写 512 字节，它必须知道全部键（4.5 节给出新版）。

**升魔数会让旧 shim 把整个文件当成「没有状态」从而重置阶梯**，那是一次无谓的回退。保持魔数是更安全的选择。

#### 4.3.2 两个新键的语义

| 键 | 类型 | 谁写 | 含义 |
|---|---|---|---|
| `fails` | 十进制 | shim 加一、shim 在拉 rescue 时清零、daemon 确认时清零 | **连续未被确认的启动次数。** 这是「三次」里的那个计数 |
| `rescues` | 十进制 | shim | **累计拉起 rescue 的次数。** 只给人看与给 `80` 的采集流程看，不参与任何判定 |

`rescues` 不参与判定是刻意的：任何参与判定的计数器都要有重置规则，而 `rescues` 的用途是「这台机器一共被救过几次」，它应该是单调的。

#### 4.3.3 对 `74` 第 4.5 节源码的确切替换

**三处替换，可直接照抄。** 每一处都标了它在 `74` 原文里的位置。

**替换 1：`STATE` 结构与常量**（`74` 第 4.5 节开头）

```c
/* ---------------------- 状态 ---------------------- */

#define STATE_PATH   u"\\EFI\\CPUDISP\\STATE.TXT"
#define LOG_PATH     u"\\EFI\\CPUDISP\\LOG.TXT"
#define NOAMD_PATH   u"\\EFI\\CPUDISP\\NOAMD"
#define FAILMAX_PATH u"\\EFI\\CPUDISP\\FAILMAX"    /* 76 §4.2(d) 新增 */
#define STICKY_PATH  u"\\EFI\\CPUDISP\\STICKY"     /* 76 §4.4.3 新增 */
#define STATE_SIZE   512
#define BOOT_BUDGET  16            /* 74 §4.7 是 12。76 §4.4.3 改成 16 */
#define FAILMAX_DEF  3             /* 所有者要求的"三次" */
#define FAILMAX_CAP  32            /* 上限，挡住把文件写成天文数字 */

typedef struct {
  int    valid;
  UINT32 sig;
  int    cand, inflight, confirmed, exhausted;
  int    fails, rescues;           /* 76 §4.3.2 新增 */
  UINT32 boots;
} STATE;
```

**替换 2：`state_read` 与 `state_write` 各加两行**

```c
static void state_read(STATE *s)
{
  UINT8 *b = NULL; UINTN n = 0;
  memset(s, 0, sizeof(*s));
  if (EFI_ERROR(read_all(STATE_PATH, &b, &n)) || n < 16) return;
  if (b[0] != 'C' || b[1] != 'P' || b[2] != 'U' || b[3] != 'D' ||
      b[4] != 'I' || b[5] != 'S' || b[6] != 'P' || b[7] != '1') {
    gBS->FreePool(b); return;
  }
  s->sig       = parse_u32(find_key((char *)b, n, "sig"), 1);
  s->cand      = (int)parse_u32(find_key((char *)b, n, "cand"), 0);
  s->inflight  = (int)parse_u32(find_key((char *)b, n, "inflight"), 0);
  s->confirmed = (int)parse_u32(find_key((char *)b, n, "confirmed"), 0);
  s->exhausted = (int)parse_u32(find_key((char *)b, n, "exhausted"), 0);
  s->boots     = parse_u32(find_key((char *)b, n, "boots"), 0);
  /* 76 新增。旧文件里没有这两个键时 find_key 返回 NULL，parse_u32 给 0。 */
  s->fails     = (int)parse_u32(find_key((char *)b, n, "fails"), 0);
  s->rescues   = (int)parse_u32(find_key((char *)b, n, "rescues"), 0);
  s->valid     = 1;
  gBS->FreePool(b);
}

static EFI_STATUS state_write(const STATE *s, const CHAR16 *pick)
{
  static char buf[STATE_SIZE];
  char *p = buf; UINTN i;
  memset(buf, ' ', STATE_SIZE);
  p = put_str(p, "CPUDISP1\nsig=");   p = put_u32(p, s->sig, 1);
  p = put_str(p, "\ncand=");          p = put_u32(p, (UINT32)s->cand, 0);
  p = put_str(p, "\ninflight=");      p = put_u32(p, (UINT32)s->inflight, 0);
  p = put_str(p, "\nconfirmed=");     p = put_u32(p, (UINT32)s->confirmed, 0);
  p = put_str(p, "\nboots=");         p = put_u32(p, s->boots, 0);
  p = put_str(p, "\nexhausted=");     p = put_u32(p, (UINT32)s->exhausted, 0);
  p = put_str(p, "\nfails=");         p = put_u32(p, (UINT32)s->fails, 0);
  p = put_str(p, "\nrescues=");       p = put_u32(p, (UINT32)s->rescues, 0);
  p = put_str(p, "\npick=");          p = put_w(p, pick);
  *p++ = '\n';
  i = (UINTN)(p - buf);
  if (i > STATE_SIZE) return EFI_UNSUPPORTED;
  return write_all(STATE_PATH, (UINT8 *)buf, STATE_SIZE);
}
```

**替换 3：读 `FAILMAX` 的小函数**（新增，放在 `state_write` 之后）

```c
/* 读 ESP 上可选的 FAILMAX 文件。不存在、读不出、或值非法时返回默认 3。
 * 只认开头的十进制数字，后面的垃圾一律忽略（允许文件里有换行与注释）。 */
static int read_failmax(void)
{
  UINT8 *b = NULL; UINTN n = 0; UINT32 v;
  if (EFI_ERROR(read_all(FAILMAX_PATH, &b, &n)) || n == 0) return FAILMAX_DEF;
  v = parse_u32((const char *)b, 0);
  gBS->FreePool(b);
  if (v < 1 || v > FAILMAX_CAP) return FAILMAX_DEF;
  return (int)v;
}
```

#### 4.3.4 日志文件的轮转

`74` 第 4.5 节的 `log_boot()` 每次启动往 `LOG.TXT` 追加约 600 字节。本文又加了 `ALIVE.TXT`（每次启动一到两行，约 200 字节）。在一台跑了几百次实验的机器上这两个文件会长到几 MB，不致命但没必要。

**规则：两个文件各自在超过 256 KiB 时由 macOS 侧的 daemon 截断为「保留最后 64 KiB」。** 放在 macOS 侧而不是 shim 里，理由是 shim 没有 `truncate`（`74` 第 4.2 节已说明 `EFI_FILE_PROTOCOL` 的这个限制），而 macOS 侧有完整的 shell 工具。4.5 节的脚本里有这一段。

### 4.4 计数到 3 之后的动作序列

#### 4.4.1 `efi_main` 的替换块

**替换 `74` 第 4.5 节 `efi_main` 里从 `state_read(&s)` 到 `state_write` 之前的那一段。** 可直接照抄。

```c
EFI_STATUS efi_main(EFI_HANDLE image, EFI_SYSTEM_TABLE *st)
{
  CPUFACTS f;
  STATE s;
  UINT8 ord[NTIER];
  UINTN nord = 0;
  int tier, no_amd, failmax, sticky;
  char note[8];

  gImage = image; gST = st; gBS = st->BootServices;
  out(u"cpudispatch 1.1\r\n");          /* 版本号跟着行为变，便于在日志里认出来 */

  probe(&f);
  f.score = amd_score(&f);

  if (EFI_ERROR(open_own_volume()) || !gRoot) {
    out(u"cpudispatch: 卷打不开，直接链载 OpenCore\r\n");
    chainload(u"\\EFI\\OC\\OpenCore.efi");
    beacon(u"volume unavailable and OpenCore did not take over");
  }

  no_amd  = file_exists(NOAMD_PATH);
  sticky  = file_exists(STICKY_PATH);
  failmax = read_failmax();
  decide_order(&f, no_amd, ord, &nord);

  state_read(&s);
  if (!s.valid || s.sig != facts_sig(&f)) {   /* 新盘，或硬件换了（74 §4.2） */
    memset(&s, 0, sizeof(s));
    s.valid = 1;
    s.sig = facts_sig(&f);
  }
  s.boots++;
  note[0] = 0;

  /* ---- 76 §4.2 第 4 行：上一次发出去了但没人确认 ---- */
  if (s.inflight) {
    s.fails++;
    /* 阶梯前进只在未确认态发生。74 §4.8 的归因纪律。 */
    if (!s.confirmed) s.cand++;
  }

  /* ---- 决定 tier。四个分支，顺序就是优先级 ---- */
  if (sticky) {
    /* 76 §4.4.3：预算耗尽之后钉在 rescue，直到有人删掉 STICKY */
    tier = T_RESCUE; s.inflight = 0; s.fails = 0;
    note[0] = 'K'; note[1] = 0;
  } else if (s.boots > BOOT_BUDGET) {
    /* 74 §4.7 第二层。76 §4.4.3 把它的动作从 beacon 改成钉死在 rescue */
    (void)create_empty(STICKY_PATH);
    tier = T_RESCUE; s.inflight = 0; s.fails = 0; s.rescues++;
    note[0] = 'B'; note[1] = 0;
  } else if (s.fails >= failmax) {
    /* 所有者要的"三次失败拉救援"。与 confirmed 无关 */
    tier = T_RESCUE; s.inflight = 0; s.fails = 0; s.rescues++;
    note[0] = 'F'; note[1] = (char)('0' + (failmax % 10)); note[2] = 0;
  } else if (s.confirmed && (UINTN)s.cand < nord) {
    /* 稳态：已确认过的档不许再动（74 §4.5 原有分支） */
    tier = ord[s.cand];
    s.inflight = 1;
  } else if ((UINTN)s.cand >= nord) {
    /* 候选顺序走完（74 §4.7 第一层） */
    s.exhausted = 1;
    tier = T_RESCUE; s.inflight = 0; s.rescues++;
    note[0] = 'X'; note[1] = 0;
  } else {
    tier = ord[s.cand];
    s.inflight = 1;
  }

  if (tier != T_RESCUE) {
    EFI_STATUS r = install_config(kTierFile[tier], tier == T_AMD, &f, note);
    if (EFI_ERROR(r)) {
      note[0] = 'E'; note[1] = 0;
      out(u"cpudispatch: install_config 失败\r\n");
    }
  }

  /* 状态必须在 LoadImage 之前落盘（74 §3.6 纪律 3） */
  (void)state_write(&s, kTierName[tier]);
  log_boot(&f, &s, kTierName[tier], note);

  out(u"cpudispatch: tier="); out(kTierName[tier]);
  out(u" fails=");            out_hex32((UINT32)s.fails);
  out(u" failmax=");          out_hex32((UINT32)failmax);
  out(u"\r\n");

  if (tier == T_RESCUE) {
    chainload(u"\\EFI\\BOOT\\BOOTX64.RESCUE.efi");
    /* GRUB 没接住。最后一次机会：直接用当前 config 起 macOS。
     * 这一条比 74 原文的 beacon 好：一台能起 macOS 的机器比一台停住的机器有用。 */
    out(u"cpudispatch: rescue 未接管，回退到 OpenCore\r\n");
    chainload(u"\\EFI\\OC\\OpenCore.efi");
    beacon(u"rescue and OpenCore both failed to start");
  }

  chainload(u"\\EFI\\OC\\OpenCore.efi");
  out(u"cpudispatch: OpenCore 未接管，转 rescue\r\n");
  chainload(u"\\EFI\\BOOT\\BOOTX64.RESCUE.efi");
  beacon(u"both OpenCore and rescue failed to start");
}
```

**`create_empty()` 是一个新增的三行辅助函数**，用 `74` 第 3.3 节已有的 `write_all()` 实现：

```c
static EFI_STATUS create_empty(const CHAR16 *path)
{
  static UINT8 one = '\n';
  return write_all(path, &one, 1);
}
```

#### 4.4.2 `note` 的取值表

`note` 进 `LOG.TXT`，是「这一次为什么走了 rescue」的唯一机器可读记录。**它必须能区分四种 rescue 原因**，因为四种的处置完全不同：

| `note` | 含义 | 运维处置 |
|---|---|---|
| `F3` | 连续 3 次（或 `FAILMAX` 次）未被确认 | 读 `REPORT.TXT` 与 `ALIVE.TXT`，按 4.7 节分类 |
| `X` | 候选阶梯走完 | `72` / `74` 的 CPU 判别全错。读 `LOG.TXT` 里每一次的 CPUID 记录 |
| `B` | 启动预算耗尽，已创建 `STICKY` | 机器被钉在 rescue。排查完之后手工删 `STICKY` |
| `K` | `STICKY` 存在，被钉住 | 同上。**这不是一次新的失败** |
| `E` | `install_config` 失败 | ESP 残缺。按 `73` 第 5.4 节 R1 修 ESP |
| `C` | AMD 核心数回填成功（`74` 第 4.5 节原有） | 正常 |

#### 4.4.3 对 `74` 第 4.7 节第三层的修正：预算耗尽不许停住

**这是本文对 `74` 唯一一处行为性修正，必须单独论证。**

`74` 第 4.7 节第三层写的是：`BOOT_BUDGET` 超了就 `beacon()`，即关看门狗、打印一行、`Stall` 死循环。它给的理由是：「在没有控制台的机器上，重启循环既观察不到又会反复踩同一处；停住至少让实例在平台 API 里保持 `running`，可以按 `73` 第 5.4 节的 R2 做取证快照。」

**这个理由在 `74` 的语境下成立，在本文的语境下不再成立。** 差别是：`74` 写作时，rescue 只是阶梯末端的一档；本文把 Alpine 做成了一个**预期会被频繁使用的、SSH 可达的常驻目标**。于是两个选项的对比变了：

| | `beacon()` 停住 | 钉在 rescue |
|---|---|---|
| 实例在平台 API 里的状态 | `running` | `running` |
| 能不能取证快照 | 能（R2，`73` 第 5.4 节：40 到 60 分钟、一个 ISO 槽位、全程平台 API） | 能，而且**不需要 R2**，Alpine 自己就能打包 ESP 并经 SSH 回传 |
| 能不能 SSH | **不能** | **能** |
| 能不能读 `LOG.TXT` | 不能（要先走 R2 把盘挂到别的 OS 上） | 能，直接 `cat` |
| 能不能修 ESP | 不能 | 能 |
| 会不会反复踩同一处 | 不会 | **不会**，因为 `STICKY` 存在时每次都进 rescue，不再尝试 macOS |

**钉在 rescue 在每一列上都不差于 `beacon()`，在三列上明显更好。** `beacon()` 保留给唯一一种情形：**rescue 自己也起不来**（`efi_main` 最后那两行）。那时确实没有任何通道，停住保现场是对的。

**配套的 `BOOT_BUDGET` 从 12 调到 16。** `74` 取 12 的算式是「最长顺序 6 档 × 每档允许一次重试」。现在要加上 rescue 启动本身消耗的预算：最坏情况是每 4 次启动里有 1 次 rescue（3 次失败 + 1 次 rescue），6 档走完需要 6 到 12 次 macOS 尝试，期间插入 2 到 3 次 rescue，合计 15。取 16。`INFERRED`。

#### 4.4.4 完整的启动序列（一台全新机器，macOS 一直起不来）

```text
boot 1  shim: inflight=0 → fails 不变; cand=0, tier=T0, inflight=1, boots=1
        OpenCore → boot.efi → 内核起来了但 sshd 没起来
        daemon: 写了 ALIVE.TXT 的 A 行，没写 S 行，没动 STATE.TXT
        外部: 80 的 Detector 在 900 秒后 reboot

boot 2  shim: inflight=1 → fails=1, cand=1（未确认，前进一档）
        tier=T1, inflight=1, boots=2
        同样失败

boot 3  shim: inflight=1 → fails=2, cand=2
        tier=T2, inflight=1, boots=3
        同样失败

boot 4  shim: inflight=1 → fails=3, cand=3
        fails >= 3 → tier=T_RESCUE, rescues=1, fails=0, inflight=0, boots=4
        note=F3
        GRUB → Alpine → sshd 起来，SSH 可达
        Alpine: 写 REPORT.TXT（里面写明"3 次都有 A 行没有 S 行 → 疑似 sshd/网络"）
                把 BOOTX64.EFI 恢复成 shim，boot-mode=macos

boot 5  shim: inflight=0 → fails 不变; cand=3, tier=T3, inflight=1, boots=5
        ...
```

**注意 boot 4 之后 `cand` 停在 3。** rescue 这一次既不前进阶梯也不回退，下一次从 T3 继续。这是 4.2(b) 那条规则的效果：**rescue 是观测，不是候选。**

### 4.5 macOS 侧的确认 daemon：扩展，不新增

**结论：扩展 `74` 第 4.6 节已有的那一个 daemon，不新增第二个。**

理由是具体的，不是「少一个好」：

1. **`STATE.TXT` 是整写 512 字节的。** 两个 daemon 各写一次会互相覆盖。`74` 第 4.6 节的脚本构造完整记录再一次性写入，这个形态不支持并发写。
2. **两个 daemon 会有两套「找 ESP」的逻辑**，而那段逻辑（遍历 `diskutil list` 里的 EFI 分区、靠状态文件存在性确认选对了）是整个脚本里最容易出错的部分。
3. `74` 第 4.6 节末尾已经有一条明确的纪律：daemon 必须是 `RunAtLoad` + `KeepAlive = false`，每次启动只跑一次，并且不许改成周期触发，否则它会把 `73` 的 `arm-rescue.sh --oneshot` 武装撤掉。**新增一个 daemon 会重新打开这个坑。**

**扩展的内容，四项：**

| 新增 | 为什么 | 在 4.2 表里的行 |
|---|---|---|
| 开机即写 `ALIVE.TXT` 的 `A` 行 | 让「macOS 到过用户态」这件事可以被 Alpine 事后看到。**这是 4.7 节那个边界情形能被正确分类的唯一依据** | 第 10 行 |
| sshd 起来后写 `S` 行 | 配对判据 | 第 11 行 |
| 记录里加 `fails=0` 与 `rescues=<保留>` | 4.3.1 节的格式 | 第 11 行 |
| panic 报告搬进 ESP 信箱 + 日志轮转 | `73` 第 5.4 节 R1 对 `80` 第 2.6 节 agent 的新增要求；4.3.4 节的轮转 | — |

**完整替换版脚本**（替换 `74` 第 4.6 节的 `/usr/local/libexec/cpudisp-confirm.sh`，可直接照抄；只用 macOS 自带的 `sh` / `diskutil` / `awk` / `sed` / `nc` / `tail`）：

```sh
#!/bin/sh
# /usr/local/libexec/cpudisp-confirm.sh
# 向 ESP 回写"当前候选已确认成功"，并留下"macOS 到过用户态"的面包屑。
# 规格: docs/spec/76-BOOT-LAYOUT-PICKER.md 第 4.5 节
#       （替换 docs/spec/74-BOOT-CPU-DISPATCH.md 第 4.6 节的同名脚本）
set -u

MNT=/private/var/run/cpudisp-esp
REL=EFI/CPUDISP/STATE.TXT
ALIVE=EFI/CPUDISP/ALIVE.TXT
LOGF=EFI/CPUDISP/LOG.TXT
PANICDIR=EFI/CPUDISP/PANIC
HEALTH_TRIES=60          # 60 x 5s = 300s
ROTATE_AT=262144         # 256 KiB，见 76 §4.3.4
ROTATE_KEEP=65536        # 保留最后 64 KiB

log() { echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) cpudisp: $*"; }
TS=$(date -u +%Y-%m-%dT%H:%M:%SZ)

# ---- 1. 先挂 ESP。这一步提前到健康检查之前，因为 A 行要尽早写 ----
mkdir -p "$MNT"
FOUND=""
for dev in $(/usr/sbin/diskutil list | /usr/bin/awk '$2=="EFI" {print $NF}'); do
  /usr/sbin/diskutil mount -mountPoint "$MNT" "$dev" >/dev/null 2>&1 || continue
  if [ -f "$MNT/$REL" ]; then FOUND="$dev"; break; fi
  /usr/sbin/diskutil unmount "$MNT" >/dev/null 2>&1 || true
done
if [ -z "$FOUND" ]; then log "没找到带 $REL 的 ESP，放弃"; exit 0; fi
log "ESP = $FOUND"

F="$MNT/$REL"
get() { /usr/bin/sed -n "s/^$1=//p" "$F" | head -1 | tr -d ' \r'; }
SIG=$(get sig); CAND=$(get cand); BOOTS=$(get boots)
PICK=$(get pick); RESCUES=$(get rescues); FAILS=$(get fails)
[ -n "$RESCUES" ] || RESCUES=0
[ -n "$SIG" ] || { log "状态文件没有 sig，放弃"; /usr/sbin/diskutil unmount "$MNT"; exit 0; }

BARGS=$(/usr/sbin/sysctl -n kern.bootargs 2>/dev/null | cut -c1-160)
OSV=$(/usr/bin/sw_vers -buildVersion 2>/dev/null || echo unknown)

# ---- 2. A 行：macOS 到过用户态。76 §4.2 第 10 行 ----
#    这一行必须在等 sshd 之前写。它是 4.7 节分类的唯一依据。
#    注意它不动 STATE.TXT，所以不影响 shim 的任何判定。
printf 'A %s cand=%s boots=%s fails=%s pick=%s build=%s args=%s\n' \
  "$TS" "$CAND" "$BOOTS" "${FAILS:-0}" "$PICK" "$OSV" "$BARGS" \
  >> "$MNT/$ALIVE" 2>/dev/null || log "写 A 行失败（ESP 满了？）"
sync

# ---- 3. 等真实的健康信号：sshd 在监听 22 ----
i=0
while [ "$i" -lt "$HEALTH_TRIES" ]; do
  if /usr/bin/nc -z 127.0.0.1 22 >/dev/null 2>&1; then break; fi
  i=$((i + 1)); sleep 5
done
if [ "$i" -ge "$HEALTH_TRIES" ]; then
  # 76 §4.2 第 12 行：什么都不写。下一次启动 shim 会 fails++。
  # 这正是 4.7 节那个边界情形的入口，所以要把原因留在 ALIVE.TXT 里。
  log "sshd 在 ${HEALTH_TRIES}x5s 内没有监听 22，不确认本档"
  printf 'N %s reason=sshd-timeout if=%s route=%s\n' \
    "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    "$(/sbin/ifconfig -a 2>/dev/null | /usr/bin/awk '/^[a-z]/{printf "%s,",$1}')" \
    "$(/usr/sbin/netstat -rn 2>/dev/null | /usr/bin/awk '/^default/{print $2; exit}')" \
    >> "$MNT/$ALIVE" 2>/dev/null || true
  sync
  /usr/sbin/diskutil unmount "$MNT" >/dev/null 2>&1 || true
  exit 0
fi
log "健康信号成立（sshd:22）"
printf 'S %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$MNT/$ALIVE" 2>/dev/null || true

# ---- 4. 整写 512 字节。inflight=0, confirmed=1, fails=0, boots=0 ----
#    rescues 原样保留（它是单调计数器，76 §4.3.2）
make_rec() {
  printf 'CPUDISP1\nsig=%s\ncand=%s\ninflight=0\nconfirmed=1\nboots=0\nexhausted=0\nfails=0\nrescues=%s\npick=%s\n' \
         "$SIG" "$CAND" "$RESCUES" "$PICK"
  [ "${1:-}" = full ] && printf 'at=%s\nbootargs=%s\n' \
         "$(date -u +%Y%m%dT%H%M%SZ)" "$BARGS"
  return 0
}
REC=$(make_rec full)
if [ "${#REC}" -gt 500 ]; then
  log "带注释字段的记录 ${#REC} 字节偏大，退回精简形式"
  REC=$(make_rec)
fi
LEN=${#REC}
if [ "$LEN" -gt 512 ]; then
  log "记录 $LEN 字节仍超 512，放弃写入以免破坏状态文件"
else
  PAD=$(printf '%*s' $((512 - LEN)) '')
  printf '%s%s' "$REC" "$PAD" > "$F" || log "写状态失败"
fi

# ---- 5. 把引导期日志搬进系统日志目录，供 80 的采集流程归档 ----
mkdir -p /var/log/cpudisp
cp -f "$MNT/$LOGF"   /var/log/cpudisp/boot.log   2>/dev/null || true
cp -f "$MNT/$ALIVE"  /var/log/cpudisp/alive.log  2>/dev/null || true
cp -f "$MNT/EFI/CPUDISP/REPORT.TXT" /var/log/cpudisp/rescue-report.txt 2>/dev/null || true

# ---- 6. panic 报告信箱。73 §5.4 R1 对 80 §2.6 agent 的新增要求 ----
#    FAT 两边都能读，所以 Alpine 在 macOS 起不来时也能拿到上一次的 panic。
mkdir -p "$MNT/$PANICDIR"
for p in /Library/Logs/DiagnosticReports/*.panic /Library/Logs/DiagnosticReports/*.ips; do
  [ -f "$p" ] || continue
  b=$(basename "$p" | tr -c 'A-Za-z0-9._-' '_' | cut -c1-60)
  [ -f "$MNT/$PANICDIR/$b" ] || cp -f "$p" "$MNT/$PANICDIR/$b" 2>/dev/null || true
done
# 信箱只留最近 10 个，避免吃掉 ESP
ls -1t "$MNT/$PANICDIR" 2>/dev/null | tail -n +11 | while read -r old; do
  rm -f "$MNT/$PANICDIR/$old"
done

# ---- 7. 日志轮转。76 §4.3.4：shim 没有 truncate，所以这件事在 macOS 侧做 ----
for rel in "$LOGF" "$ALIVE"; do
  f="$MNT/$rel"
  [ -f "$f" ] || continue
  sz=$(stat -f%z "$f" 2>/dev/null || echo 0)
  if [ "$sz" -gt "$ROTATE_AT" ]; then
    tail -c "$ROTATE_KEEP" "$f" > "$f.new" 2>/dev/null &&
      mv -f "$f.new" "$f" && log "轮转 $rel（原 $sz 字节）"
  fi
done

# ---- 8. 确保 73 §5.3.2 的 macOS 态引导对象是 shim 而不是 OpenCore ----
#    这是 74 §4.7 对 73 的修正，原样保留。
if [ -f "$MNT/EFI/BOOT/BOOTX64.DISPATCH.efi" ]; then
  if ! /usr/bin/cmp -s "$MNT/EFI/BOOT/BOOTX64.DISPATCH.efi" "$MNT/EFI/BOOT/BOOTX64.EFI"; then
    log "BOOTX64.EFI 不是 shim，修回"
    cp -f "$MNT/EFI/BOOT/BOOTX64.DISPATCH.efi" "$MNT/EFI/BOOT/BOOTX64.NEW.efi"
    sync
    mv -f "$MNT/EFI/BOOT/BOOTX64.NEW.efi" "$MNT/EFI/BOOT/BOOTX64.EFI"
  fi
fi

sync
/usr/sbin/diskutil unmount "$MNT" >/dev/null 2>&1 || true
log "完成"
```

**LaunchDaemon plist 不变**，即 `74` 第 4.6 节的 `/Library/LaunchDaemons/net.metal2vu.cpudisp-confirm.plist` 原样使用（`RunAtLoad = true`、`KeepAlive = false`、`ThrottleInterval = 60`）。**不要加 `StartInterval` 或 `WatchPaths`**，理由见 `74` 第 4.6 节末段（会把 `arm-rescue.sh --oneshot` 的武装撤掉）。

**一条新增的安装期检查**（接 `74` 第 4.6 节的安装命令）：

```bash
# 确认只有一个 cpudisp 相关的 daemon，防止"新增第二个"这件事偷偷发生
launchctl list | grep -c cpudisp     # 必须是 1
ls /Library/LaunchDaemons/ | grep cpudisp   # 必须只有一个文件
```

### 4.6 Alpine 侧：从 ESP 启动并预配 SSH

#### 4.6.1 启动路径与 `grub.cfg`

Alpine 从 ESP 的 `/boot/` 启动，GRUB 读 FAT（原生支持，不需要额外模块）。**这替换 `74` 第 4.7 节给出的 `grub.cfg`**，差异是 `linux` 那一行：`74` 的版本假设 Alpine 装在一个 ext4 `RESCUE` 分区上（`root=LABEL=RESCUE`），本文的方案 A 里没有那个分区。

```text
# /EFI/rescue/grub.cfg
# 替换 74 §4.7 的版本。差异：Alpine 改成从 ESP 的 /boot 以 diskless 模式启动。
set default=0
set timeout=5
set timeout_style=menu

menuentry "Alpine rescue (diskless, from ESP)" {
    search --no-floppy --label --set=root OPENCORE
    linux  /boot/vmlinuz-virt \
           modules=loop,squashfs,sd-mod,usb-storage,vfat \
           alpine_dev=LABEL=OPENCORE \
           modloop=/boot/modloop-virt \
           apkovl=/rescue.apkovl.tar.gz \
           console=ttyS0,115200n8 console=tty0 \
           quiet
    initrd /boot/initramfs-virt
}

menuentry "Chainload cpudispatch (ladder keeps working)" {
    search --no-floppy --label --set=root OPENCORE
    chainloader /EFI/BOOT/BOOTX64.DISPATCH.efi
}

menuentry "Chainload OpenCore directly (bypass ladder)" {
    search --no-floppy --label --set=root OPENCORE
    chainloader /EFI/BOOT/BOOTX64.OC.efi
}
```

**逐项说明内核命令行：**

| 参数 | 作用 | 标签 |
|---|---|---|
| `modules=loop,squashfs,sd-mod,usb-storage,vfat` | initramfs 里要加载的模块。`loop` + `squashfs` 是挂 modloop 的前提，`vfat` 是读 ESP 的前提 | `INFERRED`，`73` 第 5.3.2 节的 `grub.cfg` 用的是 `sd-mod,usb-storage,ext4`，本文把 `ext4` 换成 `vfat` 并加上 modloop 需要的两个 |
| `alpine_dev=LABEL=OPENCORE` | 告诉 init 启动介质是哪个卷。init 随后在这个卷上找 modloop、apkovl 与本地 apk 仓库 | `INFERRED`，参数名与取值语法未实测，**登记为 L-011** |
| `modloop=/boot/modloop-virt` | modloop 的位置。`73` 第 2.4 节记录 `reinstall` 把它设成一个 HTTP URL；这里是介质上的本地路径 | `INFERRED`，「本地路径形式是否被接受」未实测，同 L-011 |
| `apkovl=/rescue.apkovl.tar.gz` | 配置覆盖包。`73` 第 2.4 节已经登记这个参数的存在为 `INFERRED`（D-005） | `INFERRED` |
| `console=ttyS0,115200n8 console=tty0` | 两个控制台都开。`73` 第 2.4 节记录 `reinstall` 的 `echo_tmp_ttys()` 就是这么做的。**L1 上这一行让 Alpine 的启动过程进串口，是整条救援链路在 L1 上唯一的文本证据** | `KNOWN` |
| `quiet` | 少刷屏。**L1 上第一次调试时要去掉它** | — |

**L-011 的降级方案要一起给出，因为它是本节唯一的真未知。** 如果 `alpine_dev=` / 本地 `modloop=` 两条路都不通，有两个退路：

1. **把 apkovl 与 modloop 的位置改成 HTTP。** 即回到 `73` 第 2.4 节 `reinstall` 的原始形态（`alpine_repo=<URL> modloop=<URL>`）。代价是救援依赖网络，而「网络坏了」正是我们要救的情形之一。**所以这是降级，不是等价替换。**
2. **回到方案 B（独立 ext4 分区 + sys 模式安装）。** 那时 `73` 第 5.1、5.2 节原样成立，本文第 3 节的修正撤回。

**L-011 在 L1 上零成本可测**，而且必须在任何 L2 花钱之前测掉。测法在 4.8 节的 V 矩阵里（V5）。

**`/.alpine-release` 这个文件**：3.2 节的 ESP 布局里有它。它是 Alpine 启动介质的标记文件，init 用它判断「这个卷是不是我的启动介质」。`INFERRED`，内容写成版本串即可：

```bash
printf '3.22.0\n' > "$STAGE/.alpine-release"
```

#### 4.6.2 `rescue.apkovl.tar.gz` 的确切内容清单

`73` 第 2.4 节的结论是：把 `authorized_keys`、sshd 的启动脚本、我们的脚本全部打进一个 apkovl，用 `apkovl=` 拉进来，比改 initramfs 简单得多，且产物是纯文本可审计的。本节把「全部」展开成确切清单。

apkovl 是一个 tar.gz，解包时以 `/` 为根展开。**完整文件清单，十一个文件：**

```text
rescue.apkovl.tar.gz
├─ etc/
│  ├─ hostname                                  "rescue"
│  ├─ .default_boot_services                    空文件（抑制默认服务集，见下）
│  ├─ apk/
│  │  ├─ world                                  要装的包清单
│  │  └─ repositories                           指向 ESP 上的本地仓库
│  ├─ network/
│  │  └─ interfaces                             lo + eth0 dhcp
│  ├─ ssh/
│  │  ├─ sshd_config                            只允许公钥
│  │  ├─ ssh_host_ed25519_key                   预置主机密钥（0600）
│  │  └─ ssh_host_ed25519_key.pub
│  ├─ runlevels/
│  │  ├─ boot/                                  符号链接集，见下
│  │  ├─ default/networking   -> /etc/init.d/networking
│  │  ├─ default/sshd         -> /etc/init.d/sshd
│  │  └─ default/local        -> /etc/init.d/local
│  └─ local.d/
│     └─ 00-rescue.start                         本文的救援脚本（0755）
└─ root/
   └─ .ssh/
      └─ authorized_keys                         harness 公钥（0600，目录 0700）
```

**逐个文件的内容（可直接照抄）：**

```text
# etc/apk/world  —— 要装哪些包。每行一个。
# 只列真正需要的。每多一个包就多一份 ESP 上本地仓库的体积。
openssh-server
openssh-keygen
dosfstools
e2fsprogs-extra
util-linux
```

```text
# etc/apk/repositories  —— 本地优先。
# 第一行是 ESP 上的本地仓库，它让"网络坏了也能起 sshd"成立。
# 第二行注释掉的是官方源，排障时手工取消注释再 apk update。
/media/OPENCORE/apks
#https://dl-cdn.alpinelinux.org/alpine/v3.22/main
```

```text
# etc/network/interfaces
auto lo
iface lo inet loopback

auto eth0
iface eth0 inet dhcp
    hostname rescue
```

`73` 第 1.1 节已经把「Vultr 是 DHCP 还是要求静态 IP」列为前提事实，并指出如果是 DHCP 就不需要 `reinstall` 那一整套动静态判断逻辑。**这里按 DHCP 写。** 如果 `73` 的 D-004 查出要静态 IP，这个文件要换成带地址的版本，而那时也要同时改 macOS 侧，不是 Alpine 独有的问题。

```text
# etc/ssh/sshd_config  —— 只允许公钥，且不开端口转发
Port 22
PermitRootLogin prohibit-password
PasswordAuthentication no
ChallengeResponseAuthentication no
KbdInteractiveAuthentication no
PubkeyAuthentication yes
AuthorizedKeysFile .ssh/authorized_keys
AllowTcpForwarding no
X11Forwarding no
PrintMotd yes
Subsystem sftp /usr/lib/ssh/sftp-server
```

**`etc/runlevels/` 下的符号链接是 OpenRC 的服务启用方式**，等价于在运行的系统上跑 `rc-update add <svc> <runlevel>`。在 apkovl 里必须以符号链接的形态打进 tar（`tar` 默认保留符号链接）。**`boot` runlevel 的那一组不要自己造**，Alpine 的 initramfs 根里已经有一套默认值；只加 `default` runlevel 的三个。

**`etc/.default_boot_services` 这个空文件**：`INFERRED`，Alpine 的 init 在 apkovl 里看到它时会跳过「添加默认启动服务」这一步，避免我们的 runlevel 配置被默认值覆盖。来源是社区的 apkovl 构建实践（转述自 <https://github.com/macmpi/alpine-linux-headless-bootstrap>，该项目的做法是把 apkovl 放在 Alpine 启动介质根目录直接生效）。**如果它反而导致必要的 boot 服务缺失，去掉它即可**，代价是我们的三个链接可能和默认集重复（重复是无害的）。登记为 L-012。

**`etc/ssh/ssh_host_ed25519_key` 为什么要预置。** 不预置的话每次救援启动都会生成新主机密钥，harness 每次都要 `StrictHostKeyChecking=no`，而那等于关掉中间人防护。预置之后 harness 可以把这个主机密钥钉死在 `known_hosts` 里。

**代价必须写清**：这个私钥存在 ESP 上的明文 tar.gz 里，任何能读那块盘的人都能拿到。**它只用于 rescue，不用于 macOS。** 判断：研发期的 L1 是本地机器，L2 是我们自己的实例，而 ESP 上已经有 `authorized_keys`（公钥，无所谓）与全部配置。真正的风险是「有人用这个主机密钥冒充我们的 rescue 做中间人」，而要做到这一点需要先能改我们的网络路由。**结论：接受，但 rescue 的主机密钥必须与 macOS 的主机密钥不同，而且不许复用到任何其他用途。** 分发阶段再处理（同 `00-OVERVIEW` 第 2.4 节末句的处理原则）。

**`etc/local.d/00-rescue.start`**，这是救援侧的全部逻辑（可直接照抄）：

```sh
#!/bin/sh
# /etc/local.d/00-rescue.start
# rescue 一起来就做四件事：交还下次启动、读状态、写报告、打包证据。
# 规格: docs/spec/76-BOOT-LAYOUT-PICKER.md 第 4.6.2 节
# 它合并并替换 73 §5.3.2 的 /etc/local.d/00-revert-boot.start
set -u

ESPDIR=/media/OPENCORE          # Alpine 的 init 会把启动介质挂在这里
CPU="$ESPDIR/EFI/CPUDISP"
TS=$(date -u +%Y-%m-%dT%H:%M:%SZ)

# 介质没挂上就自己挂一次，不要静默退出
if [ ! -d "$CPU" ]; then
  mkdir -p "$ESPDIR"
  DEV=$(blkid -L OPENCORE 2>/dev/null || true)
  [ -n "$DEV" ] && mount -t vfat "$DEV" "$ESPDIR" 2>/dev/null || true
fi
[ -d "$CPU" ] || { echo "rescue: 找不到 ESP，只起 sshd"; exit 0; }
mount -o remount,rw "$ESPDIR" 2>/dev/null || true

# ---- 1. 第一个动作：把下次启动交还给 macOS ----
#    74 §4.7 对 73 §5.3.2 的修正：macOS 态的引导对象是 shim，不是 OpenCore。
#    STICKY 存在时不交还（76 §4.4.3：预算耗尽，钉在 rescue）。
if [ -f "$CPU/STICKY" ]; then
  echo "rescue: STICKY 存在，不交还下次启动"
  printf 'rescue\n' > "$ESPDIR/boot-mode"
else
  if [ -f "$ESPDIR/EFI/BOOT/BOOTX64.DISPATCH.efi" ]; then
    cp -f "$ESPDIR/EFI/BOOT/BOOTX64.DISPATCH.efi" "$ESPDIR/EFI/BOOT/BOOTX64.NEW.efi"
    sync
    mv -f "$ESPDIR/EFI/BOOT/BOOTX64.NEW.efi" "$ESPDIR/EFI/BOOT/BOOTX64.EFI"
  fi
  printf 'macos\n' > "$ESPDIR/boot-mode"
  rm -f "$ESPDIR/boot-revert"
fi
sync

# ---- 2. 读状态 ----
S="$CPU/STATE.TXT"
get() { sed -n "s/^$1=//p" "$S" 2>/dev/null | head -1 | tr -d ' \r'; }
CAND=$(get cand); PICK=$(get pick); CONF=$(get confirmed)
BOOTS=$(get boots); RESC=$(get rescues); SIG=$(get sig)

# ---- 3. 分类。76 §4.7 的判据：最近三次启动有没有 A 行 ----
A3=$(grep -c '^A ' "$CPU/ALIVE.TXT" 2>/dev/null || echo 0)
ALAST=$(grep '^A ' "$CPU/ALIVE.TXT" 2>/dev/null | tail -3 | wc -l | tr -d ' ')
SLAST=$(grep '^S ' "$CPU/ALIVE.TXT" 2>/dev/null | tail -3 | wc -l | tr -d ' ')
NLAST=$(grep -c '^N ' "$CPU/ALIVE.TXT" 2>/dev/null || echo 0)

if [ "${ALAST:-0}" -ge 3 ] && [ "${NLAST:-0}" -ge 1 ]; then
  VERDICT="S1.5-macos-alive-no-ssh"
  ACTION="macOS 到过用户态但 sshd 没起来。查网络与 sshd，不要怀疑 CPU 档位。"
elif [ "${ALAST:-0}" -ge 1 ]; then
  VERDICT="mixed-some-boots-reached-userspace"
  ACTION="部分启动到过用户态。比对 ALIVE.TXT 的 cand 与 LOG.TXT 的 tier。"
else
  VERDICT="S2-never-reached-userspace"
  ACTION="从未到过用户态。看 LOG.TXT 的 CPUID 与 PANIC/ 下的报告。"
fi

# ---- 4. 写报告。这是无头机器上唯一的人类可读产出 ----
{
  echo "=== rescue report $TS ==="
  echo "verdict  : $VERDICT"
  echo "action   : $ACTION"
  echo "state    : cand=$CAND pick=$PICK confirmed=$CONF boots=$BOOTS rescues=$RESC sig=$SIG"
  echo "alive    : A-total=$A3 A-last3=$ALAST S-last3=$SLAST N-total=$NLAST"
  echo "sticky   : $([ -f "$CPU/STICKY" ] && echo yes || echo no)"
  echo "failmax  : $(cat "$CPU/FAILMAX" 2>/dev/null || echo '3 (default)')"
  echo "--- 分区表 ---"
  fdisk -l 2>/dev/null | sed -n '1,40p'
  echo "--- 块设备 ---"
  lsblk -o NAME,SIZE,FSTYPE,LABEL,PARTTYPE 2>/dev/null || true
  echo "--- 网络 ---"
  ip -brief addr 2>/dev/null || ifconfig -a
  ip route 2>/dev/null || route -n
  echo "--- ESP 占用 ---"
  df -h "$ESPDIR"
  echo "--- LOG.TXT 末尾 40 行 ---"
  tail -40 "$CPU/LOG.TXT" 2>/dev/null || echo "(无)"
  echo "--- ALIVE.TXT 末尾 20 行 ---"
  tail -20 "$CPU/ALIVE.TXT" 2>/dev/null || echo "(无)"
  echo "--- panic 信箱 ---"
  ls -l "$CPU/PANIC" 2>/dev/null || echo "(空)"
} > "$CPU/REPORT.TXT" 2>&1
sync

# ---- 5. 打包一份证据到 /tmp，供 harness 一条 scp 取走 ----
#    不往 ESP 写这个包，ESP 的空间要留给日志与 panic。
tar czf /tmp/rescue-evidence.tgz \
    -C "$ESPDIR" EFI/CPUDISP boot-mode 2>/dev/null || true

# ---- 6. 纪律：rescue 对 APFS 容器只读。本脚本不挂载、不 fsck、不写 p2/p3 ----
echo "rescue: ready. verdict=$VERDICT  报告在 $CPU/REPORT.TXT"
exit 0
```

**第 6 步那条纪律是 4.7 节结论的实现基础，必须在代码里以「什么都不做」的形式存在。** 救援侧一行都不碰 APFS，所以一次误判的切换不可能损坏数据。

**打包脚本**（Linux 构建机，可直接照抄）：

```bash
#!/usr/bin/env bash
# scripts/mk-rescue-apkovl.sh <harness-pubkey-file> <out.tar.gz>
# 造 76 §4.6.2 的 apkovl。纯文本输入，产物可审计。
set -euo pipefail
PUB="${1:?harness 公钥文件}"; OUT="${2:?输出 tar.gz}"
W=$(mktemp -d); trap 'rm -rf "$W"' EXIT

mkdir -p "$W/etc/apk" "$W/etc/network" "$W/etc/ssh" "$W/etc/local.d" \
         "$W/etc/runlevels/default" "$W/root/.ssh"

printf 'rescue\n' > "$W/etc/hostname"
: > "$W/etc/.default_boot_services"          # 见 76 §4.6.2 与 L-012

cat > "$W/etc/apk/world" <<'EOF'
openssh-server
openssh-keygen
dosfstools
e2fsprogs-extra
util-linux
EOF

cat > "$W/etc/apk/repositories" <<'EOF'
/media/OPENCORE/apks
#https://dl-cdn.alpinelinux.org/alpine/v3.22/main
EOF

cat > "$W/etc/network/interfaces" <<'EOF'
auto lo
iface lo inet loopback

auto eth0
iface eth0 inet dhcp
    hostname rescue
EOF

cat > "$W/etc/ssh/sshd_config" <<'EOF'
Port 22
PermitRootLogin prohibit-password
PasswordAuthentication no
ChallengeResponseAuthentication no
KbdInteractiveAuthentication no
PubkeyAuthentication yes
AuthorizedKeysFile .ssh/authorized_keys
AllowTcpForwarding no
X11Forwarding no
PrintMotd yes
Subsystem sftp /usr/lib/ssh/sftp-server
EOF

# 预置主机密钥。只用于 rescue，不复用（76 §4.6.2 的代价说明）
ssh-keygen -t ed25519 -N '' -C 'metal2vu-rescue-hostkey' \
           -f "$W/etc/ssh/ssh_host_ed25519_key" >/dev/null
chmod 600 "$W/etc/ssh/ssh_host_ed25519_key"
chmod 644 "$W/etc/ssh/ssh_host_ed25519_key.pub"

install -m 0600 "$PUB" "$W/root/.ssh/authorized_keys"
chmod 700 "$W/root/.ssh"

install -m 0755 scripts/rescue/00-rescue.start "$W/etc/local.d/00-rescue.start"

# OpenRC 服务启用 = runlevel 目录里的符号链接
ln -s /etc/init.d/networking "$W/etc/runlevels/default/networking"
ln -s /etc/init.d/sshd       "$W/etc/runlevels/default/sshd"
ln -s /etc/init.d/local      "$W/etc/runlevels/default/local"

# 打包。-p 保权限，符号链接按默认不解引用
tar czf "$OUT" -C "$W" --owner=0 --group=0 .
echo "--- 产物内容（必须与 76 §4.6.2 的清单逐行一致）---"
tar tzvf "$OUT"
sha256sum "$OUT"
echo "--- rescue 主机公钥，写进 harness 的 known_hosts ---"
cat "$W/etc/ssh/ssh_host_ed25519_key.pub"
```

#### 4.6.3 ESP 上的本地 apk 仓库：一个容易漏掉的前置条件

**这一条是本节最可能被漏掉的东西，漏掉的表现是「Alpine 起来了但没有 sshd」。**

`KNOWN`（机制）：Alpine 的 netboot initramfs 只带最小根文件系统与 busybox，内核模块在 modloop 里（`73` 第 2.4 节已引官方说明）。**`openssh` 既不在 initramfs 里也不在 modloop 里。** diskless 模式下 `/etc/apk/world` 里列的包要由 `apk` 在启动期安装，而 `apk` 的包源由 `/etc/apk/repositories` 决定。

所以：**如果 `repositories` 只指向 HTTP，那么网络不通时 sshd 装不上，救援系统就没有入口。** 而「网络不通」正是我们要救的情形之一。

**解法：把需要的 apk 预取到 ESP 上，让 `repositories` 的第一行指向它。**

```bash
#!/usr/bin/env bash
# scripts/mk-local-apks.sh <stage-dir>
# 把 76 §4.6.2 的 etc/apk/world 里那几个包及其全部依赖预取到 ESP 的 /apks。
# 要在一台有 apk 的机器上跑（Alpine 容器最省事）：
#   docker run --rm -v "$PWD:/w" alpine:3.22 sh /w/scripts/mk-local-apks.sh /w/build/efi
set -euo pipefail
STAGE="${1:?stage dir}"
ARCH=x86_64
DEST="$STAGE/apks/$ARCH"
mkdir -p "$DEST"

apk update
# --recursive 把依赖一并取下来。这是"离线也能装"的关键开关
apk fetch --recursive --output "$DEST" \
    openssh-server openssh-keygen dosfstools e2fsprogs-extra util-linux

# 造索引。没有索引 apk 不认这个目录
apk index --output "$DEST/APKINDEX.unsigned.tar.gz" "$DEST"/*.apk
mv -f "$DEST/APKINDEX.unsigned.tar.gz" "$DEST/APKINDEX.tar.gz"

echo "--- 体积（76 §3.4 的预算是 10 MiB）---"
du -sh "$STAGE/apks"
ls -1 "$DEST" | wc -l
```

**两条必须记住的后果：**

1. **这个本地仓库没有签名**，所以 Alpine 侧要么用 `--allow-untrusted`，要么我们自己签。`INFERRED`，`apk index` 产出的是 unsigned 索引，而 Alpine 默认校验签名。**查清方法与两种处置**：L1 上先试不加任何开关，若 `apk` 报签名错误，则在 `world` 之外加一个 `etc/apk/repositories` 的注释说明并在 `local.d` 脚本里改用 `apk add --allow-untrusted`。登记为 L-013。
2. **本地仓库的版本必须与 `vmlinuz-virt` / `modloop-virt` 同一个 Alpine 版本。** 混版本会出现「模块 ABI 不匹配」这一类难查的问题。**构建期门禁**：三件套与 apks 必须来自同一个 `v3.22` 目录，脚本里把版本号做成一个变量，不许在两处分别写。

#### 4.6.4 harness 侧怎么连 rescue

```bash
# 两套密钥、两套 known_hosts。rescue 与 macOS 不共用主机身份（76 §4.6.2）
ssh -i "$HARNESS_KEY" \
    -o UserKnownHostsFile="$HARNESS_DIR/known_hosts.rescue" \
    -o StrictHostKeyChecking=yes \
    "root@${IP}" 'cat /media/OPENCORE/EFI/CPUDISP/REPORT.TXT'

# 一条命令取走全部证据
scp -i "$HARNESS_KEY" \
    -o UserKnownHostsFile="$HARNESS_DIR/known_hosts.rescue" \
    "root@${IP}:/tmp/rescue-evidence.tgz" "./evidence-$(date -u +%Y%m%dT%H%M%SZ).tgz"
```

**`StrictHostKeyChecking=yes` 能开，是因为 4.6.2 节预置了主机密钥。** 这是预置它的全部收益。

### 4.7 边界情形：macOS 起来了但 SSH 不通

任务点名这个情形，并指出它「可能是我们想要的，也可能不是」。**先把它拆成两个不同的情形，因为处置不同。**

| 情形 | 现象 | 在 `73` 第 1.3 节的分级里 | SSH 通不通 | 本机制的行为 |
|---|---|---|---|---|
| **E1：显示坏了，网络正常** | WindowServer 死、黑屏、`metal-probe` 报无设备 | **S1** | **通** | daemon 确认成功，`fails = 0`，**不切换**。完全正确 |
| **E2：网络或 sshd 坏了** | 系统到了用户态，但 22 端口起不来 | `73` 的分级里**没有这一格**，它比 S1 差、比 S2 好 | **不通** | 三次之后切到 Alpine |

**E1 根本不触发切换，所以「显示坏了被切走」这个担心不成立。** 这是 `74` 第 4.6 节选「sshd 在听 22」作为健康信号时就已经处理好的：那一节的理由是「`73` 第 1.3 节把 S1（macOS 起来了但显示坏、SSH 可达）与 S2（macOS 不启动）分开，而我们要确认的恰好是到 S1 或更好」。本项目的整个显示栈都在改，**S1 是研发期的常态**，一个会在 S1 上切走机器的机制一天都用不了。

**所以真正要裁决的只有 E2。处置：保持 SSH 作为唯一确认信号，即让 E2 触发切换。** 五条理由，按权重：

1. **在本项目的定义下，E2 与 S2 没有可操作的区别。** `00-OVERVIEW` 第 2.5 节风险 2 与 `80` 第 1.3 节的结论是「L2 的唯一主通道是 SSH」。一台 SSH 不通的 macOS，我们**不能登录、不能取日志、不能跑 `metal-probe`、不能截图**（`80` 第 2.3.5 节的 ARD/VNC 通道同样要经 SSH 隧道）。它在 API 里是 `running`，但对我们产生零信息。把它留在那里不启动救援，等于放弃这一次实验的全部产出。
2. **切过去的收益是确定的：拿到诊断。** Alpine 起来之后 `REPORT.TXT` 里会写明 `verdict=S1.5-macos-alive-no-ssh` 并附上 macOS 自己留的 `N` 行（里面有 `ifconfig` 的接口列表与默认路由）。**这恰好是诊断 E2 需要的两件事**，而在 macOS 里拿不到它们（登不进去）。换句话说：**切到 Alpine 是把 E2 变成可诊断的唯一办法。**
3. **切过去的代价是有界的，而且很小。** 一次重启，加上 Alpine 起来的时间。4.6.2 节的 `local.d` 脚本第 1 步就是把下次启动交还给 macOS，所以**误判的最大代价是一次额外重启**，量级是两到五分钟。不是「机器被切走了」。
4. **切过去不可能损坏任何东西。** 4.6.2 节第 6 步那条纪律：rescue 对 APFS 容器只读，脚本里一行都不碰 p2 与 p3。所有者担心的「把一台其实活着的机器切走了」，在数据层面是零风险；它损失的只是那台机器在那一刻正在跑的东西，而那个东西我们本来也拿不到结果（理由 1）。
5. **不切换的那条路会掩盖一类真实故障。** 如果 E2 不触发切换，那么「sshd 配置被实验改坏了」这类问题的表现就是「机器永远不确认、阶梯永远不前进、没有任何报告」。**一个不产生信号的失败是最贵的失败。**

**但是「保持 SSH 作为唯一信号」不等于什么都不做。三条配套措施，它们把这个决定从「可以接受」变成「对」：**

**措施 1：面包屑。** 4.5 节脚本第 2 步的 `A` 行与超时后的 `N` 行。它们让 E2 与 S2 **事后可区分**，而区分它们是决定下一步该查什么的前提。没有面包屑的话，Alpine 看到的只是「三次没确认」，分不清是 panic 还是 sshd。**这是整个 4.7 节的技术核心：切换本身不需要区分 E2 与 S2，但报告必须区分。**

**措施 2：`FAILMAX` 可调。** 4.2(d) 节。一台已知网络不稳的机器可以把阈值调到 8；一台第一次开机的机器可以调到 1。**阈值是运维参数，不是设计常量。** 所有者的「3」是默认值，不是唯一值。

**措施 3：交还下次启动。** 4.6.2 节第 1 步。Alpine 不霸占机器。运维在 Alpine 里有无限时间（它不会自己重启），但一旦有人或有什么东西重启了它，下一次就回到 macOS 继续试下一档。**这让「切过去」是一个可逆动作而不是一个状态迁移。**

**明确拒绝的两个替代方案，以及拒绝理由：**

| 替代方案 | 为什么不采用 |
|---|---|
| 加一个更弱的确认信号（例如「`launchd` 跑到了 `RunAtLoad` 就算成功」） | 它会让 E2 永远确认成功，于是**三次失败机制在 E2 上失效**，而 E2 是最需要它的情形。更糟的是它也会让「起来了但立刻 kernel panic」这种情形确认成功（`RunAtLoad` 可能在 panic 之前就跑到了），而那是真正的启动失败 |
| 让 Alpine 自动修 macOS 的网络 | 需要写 APFS（改 `/Library/Preferences/SystemConfiguration/`），违反 4.6.2 节第 6 步的只读纪律，而且「自动修」这件事本身不可验证。**救援系统的职责是让人能进去，不是替人做决定** |

**一句话总结给所有者：** 这个情形里机器被切到 Alpine **是我们想要的**，因为一台 SSH 不通的 macOS 对这个项目等于一台关机的机器，而切过去之后我们**反而**能拿到它为什么不通的证据。代价是一次额外重启，风险是零（救援侧不写 macOS 的盘），而且阈值随时可调。

### 4.8 L1 上必须跑的验证矩阵

接 `74` 第 4.9 节那张 V1 到 V10 的表。**本文新增的部分另起编号 W1 到 W12，全部在本地 KVM 上跑，成本是零。**

| # | 场景 | 做法 | 期望 |
|---|---|---|---|
| **W1** | 三个启动项都出现 | 按第 3 节造盘，`picker=visible` 启动 | 选择器里三项：`macOS`、`Recovery`（或 `macOS Base System`）、`Rescue` |
| **W2** | shim 不出现在选择器里 | 同 W1，数条目 | **恰好三项**。多出第四项说明 2.5.4 节的 `.contentVisibility` 没生效 |
| **W3** | 名字与图标 | `screendump` 抓一帧（`80` 第 2.3 节） | 三项的名字分别是 2.5 节设定的值；macOS 项用我们放的 `.VolumeIcon.icns` |
| **W4** | `GoldenGate` 真的被加载 | OpenCore DEBUG 日志 | 日志里出现 Resources 路径与 `GoldenGate`；没有「找不到图标」一类错误 |
| **W5** | Alpine 从 ESP 起得来（**L-011 的判据**） | 手工在 GRUB 里选第一项 | Alpine 到 login，`local.d` 跑过，`REPORT.TXT` 存在。**`alpine_dev=` / 本地 `modloop=` 两条都成立** |
| **W6** | 离线也能起 sshd（**L-013 的判据**） | QEMU 侧去掉 `-netdev`，重跑 W5 | sshd 仍然在 22 上监听（证明本地 apk 仓库生效） |
| **W7** | SSH 预配可用 | 从 host 连 guest 的 22 | 用 `StrictHostKeyChecking=yes` + 4.6.2 节产出的主机公钥能连上 |
| **W8** | 三次失败拉救援 | 启动 macOS 三次，**每次都 `launchctl unload` 掉 daemon**（模拟 E2），第四次观察 | 第四次 `tier=rescue`，`note=F3`，`STATE.TXT` 的 `rescues=1`、`fails=0` |
| **W9** | 救援不算一次失败 | W8 之后再启动一次 | `fails` 从 0 开始，`cand` 与 W8 结束时相同（**不前进**） |
| **W10** | 已确认的机器也会被救 | 先跑一次完整确认（`confirmed=1`），再连续三次 unload daemon | 第四次 `tier=rescue`；且 `cand` **全程不变**（4.2(a) 的归因纪律） |
| **W11** | E2 被正确分类 | W8 的 `REPORT.TXT` | `verdict=S1.5-macos-alive-no-ssh`，且 `A-last3=3` |
| **W12** | S2 被正确分类 | 故意把 `\EFI\OC\OpenCore.efi` 改名，连续三次 | `verdict=S2-never-reached-userspace`，`A-last3=0` |
| **W13** | `FAILMAX` 生效 | `printf 1 > ESP:/EFI/CPUDISP/FAILMAX`，失败一次 | 第二次就进 rescue，`note=F1` |
| **W14** | 预算耗尽钉在 rescue 而不是停住 | 把 `BOOT_BUDGET` 临时改成 2 重编 shim，启动三次 | 第三次创建 `STICKY` 并进 rescue；**串口上没有 `HALT`**；之后每次都进 rescue |
| **W15** | 交还下次启动 | W8 的 rescue 之后不删 `STICKY`（它不该存在）直接重启 | 回到 macOS（`BOOTX64.EFI` 已被 Alpine 换回 shim） |

**W8 到 W12 这五条是本文的核心机制的全部判据。** 它们不需要一台坏机器，只需要 `launchctl unload` 掉 daemon，这是一条命令。**在任何 L2 花钱之前必须全绿。**

---

## 5. ACPI / SSDT / kext 在 KVM 上的最小集

### 5.1 「KVM 平台应该好办吧」：确认一半，推翻一半

所有者的判断是对的，但对的那一半不是通常以为的那一半。

**确认的部分：真机 hackintosh 的绝大多数工作量在 KVM 上确实不存在。** 逐条对照 dortania 指南里桌面机要做的事：

| 真机上的常规工作 | 在 QEMU/OVMF 上 | 依据 |
|---|---|---|
| 反编译厂商 DSDT、找设备路径、改名 | **不需要。** ACPI 表由 QEMU 生成，是一份干净的、规范的表 | `71` 第 6.2 节：`ACPI/Delete` 与 `ACPI/Patch` 置空，因为「OVMF 的 ACPI 表是我们自己这边生成的，没有需要删的厂商表」 |
| `ACPI/Quirks` 的八个开关 | **全部 `false`。** 它们针对真机固件的 ACPI 缺陷 | `71` 第 6.2 节，`INFERRED`，参考配置同样全关（`KNOWN`） |
| USB 端口映射（`USBToolBox` / `UTBMap`） | **不需要。** 端口数由我们自己的 `-device qemu-xhci` 决定 | `71` 第 6.5.1 节 |
| `XhciPortLimit` 的 15 端口上限 | **不需要**，保持 `false` | 同上 |
| 网卡 kext | **不需要。** `AppleVirtIONetwork` 与 `AppleVmxnet3Ethernet` 都在 x86_64 Boot KC | `71` 第 3.5 节，`KNOWN` |
| 块设备 kext | **不需要。** `AppleVirtIOBlock`、`IONVMeFamily`、`AppleAHCIPort` 三条路都在 Boot KC | `71` 第 3.2、3.4 节，`KNOWN` |
| 声卡（`AppleALC` + `layout-id`） | **不需要**，不要声音 | `71` 第 6.4、6.9.2 节 |
| 蓝牙、WiFi | 不需要 | `71` 第 6.5.1 节 |
| CFG Lock / MSR 0xE2 解锁 | 不需要，配 `DummyPowerManagement = true` | `71` 第 5.3 节 |
| 电池、背光、lid、环境光 | 不需要，`MacPro7,1` 是台式机语义 | `71` 第 4.4 节理由 2 |
| 显卡 kext（`WhateverGreen`） | **显式排除**，本项目自己写显卡驱动 | `71` 第 6.10 节 |

**推翻的部分：难的地方不在 ACPI，所以「ACPI 好办」不等于「平台好办」。** 本项目真正的三个难点，一个都不是 ACPI：

1. **CPUID 与机型门。** `72` 第 2 节的两道内核门、30 个 model 白名单、15 条补丁，加上 `74` 整册的判别与五档阶梯。这是本项目在引导层花掉最多设计量的地方，而它与 ACPI 无关。
2. **无控制台的引导链。** `73` 整册。这同样与 ACPI 无关。
3. **显示栈。** 这是项目本身（`00-OVERVIEW` 第 3 节边界 ③）。

**一句话给所有者：ACPI/SSDT 这一项在 KVM 上确实接近零成本，必需的只有一个文件、一百多字节。但它在总工作量里的占比本来就很小，所以「KVM 平台好办」这个结论不能从它推广出去。**

### 5.2 QEMU/OVMF 生成的 ACPI 表里有什么、缺什么

`INFERRED`（基于 QEMU 的 q35 机型行为与社区配置的交叉印证，未在本项目实测；查清方法见 5.3.1 节末）。

| 表 | QEMU 生成 | macOS 需要 | 结论 |
|---|---|---|---|
| `DSDT` | 有。含 `\_SB.PCI0` 与各 PCI 设备、ISA 桥、RTC、COM1、键鼠 | 需要 | 够用 |
| `FACP`（FADT） | 有 | 需要 | 够用 |
| `APIC`（MADT） | 有 | 需要 | 够用 |
| `MCFG` | 有 | 需要（PCIe 配置空间） | 够用 |
| `HPET` | 有 | 可选 | `UEFI/Quirks/ActivateHpetSupport` 保持 `false`（`71` 第 6.9.2 节） |
| `SSDT`（QEMU 自带的若干） | 有（CPU 热插拔、PCI 热插拔相关） | 不冲突 | 不删。`71` 第 6.2 节 `ACPI/Delete` 置空 |
| `DMAR` | **默认不生成**（除非 `-device intel-iommu`） | 不需要 | 所以 `Kernel/Quirks/DisableIoMapper` 保持 `false`（`71` 第 6.5.3 节） |
| **EC（embedded controller）设备** | **没有** | **macOS 10.15 起要求存在** | **这是唯一的缺口**，见 5.3.1 |
| `USBX` 设备（USB 供电属性） | 没有 | 不是启动必需 | 见 5.3.2 |

**所以缺口只有一个：EC。** 下一节逐个判定社区常用的 SSDT。

### 5.3 逐个 SSDT 判定

**判定口径：在 25G325 + `MacPro7,1` + QEMU q35 + OVMF 这个确切组合下，这个 SSDT 是不是必需。** 不是「社区常不常用」。

| SSDT | 真机上的用途 | 本组合下 | 理由 | 标签 |
|---|---|---|---|---|
| **`SSDT-EC`** | 提供一个假的 embedded controller 设备 | **必需** | 见 5.3.1 | `KNOWN` 对于「10.15 起要求」；`INFERRED` 对于「不加的具体后果」 |
| `SSDT-USBX` | 给 `AppleUSBHostPort` 一组供电属性（`kUSBSleepPortCurrentLimit` 等） | **不必需，但保留** | 见 5.3.2 | `INFERRED` |
| **`SSDT-PLUG`** | 在 CPU0 上注入 `plugin-type = 1`，让 `X86PlatformPlugin` 接管 CPU 电源管理（XCPM） | **不要加** | 见 5.3.3 | `INFERRED`，理由很强 |
| `SSDT-AWAC` | 300 系列及之后的主板上，`AWAC` 时钟取代了 legacy RTC，需要强制启用 `RTC0` | 不需要 | QEMU 暴露的是标准 MC146818 RTC（I/O 0x70/0x71），DSDT 里就是 `RTC`，`_STA` 正常。没有 AWAC 这个东西 | `INFERRED` |
| `SSDT-RTC0` / RTC MMIO 修正 | 修某些主板上 RTC 的内存区域冲突 | 不需要 | 同上。`Kernel/Quirks/DisableRtcChecksum` 也保持 `false`（`71` 第 6.5.3 节） | `INFERRED` |
| `SSDT-PMC` | 300 系列上让 `AppleIntelPCHPMC` 匹配，从而让原生 NVRAM 可用 | 不需要 | 我们的 NVRAM 是 OVMF 的 pflash，由 `OpenRuntime.efi` + `WriteFlash = true` 管（`71` 第 6.7 节），不走 PCH PMC 那条路 | `INFERRED` |
| `SSDT-HPET` / IRQ 修正 | 修真机 DSDT 里 HPET / RTC / TIMR 的 IRQ 冲突 | 不需要 | QEMU 的表没有这类冲突。`ACPI/Patch` 置空（`71` 第 6.2 节） | `INFERRED` |
| `SSDT-XOSI` | 把 `_OSI` 查询伪装成 Windows，用于笔记本的 ACPI 分支 | 不需要 | QEMU 的 DSDT 没有 Windows 专属分支 | `INFERRED` |
| `SSDT-PNLF` | 笔记本背光 | 不需要 | 没有背光。`MacPro7,1` 是台式机（`71` 第 4.4 节理由 2） | `INFERRED` |
| `SSDT-GPRW` / `UPRW` / `SSDT-SLPB` | 修 instant wake | 不需要 | `HibernateMode = None`，`pmset -a sleep 0`（`80` 第 2.4.2 节），不睡就没有唤醒问题 | `INFERRED` |
| `SSDT-IMEI` | 给 Intel ME 的设备补一个 ACPI 条目 | 不需要 | QEMU 不暴露 ME | `INFERRED` |
| `SSDT-SBUS` / `SMBUS` | 让 `AppleSMBusPCI` 匹配，供 `AppleSMBusController` | 不需要 | 它影响的是「关于本机」里的内存信息与某些传感器。`CustomMemory = false`，内存显示为未知不影响功能（`71` 第 6.8 节） | `INFERRED` |
| `SSDT-DTGP` | 一个 helper 方法，被别的 SSDT 调用 | **只在别的 SSDT 需要它时才要** | `KNOWN`：OSX-KVM 的 ACPI 目录里有 `SSDT-DTGP.aml`（100 字节），但它的 `config.plist` 的 `ACPI/Add` 里**没有**启用它（本轮读取 <https://api.github.com/repos/kholia/OSX-KVM/contents/OpenCore/EFI/OC/ACPI> 与 <https://raw.githubusercontent.com/kholia/OSX-KVM/master/OpenCore/config.plist>）。我们的两个 SSDT 都不调用 `DTGP` | `KNOWN` |
| `SSDT-EHCI` | 给 EHCI 控制器补条目 | 不需要 | `KNOWN`：OSX-KVM 的 ACPI 目录里有它但同样**未在 `ACPI/Add` 里启用**。我们用 `qemu-xhci`，没有 EHCI | `KNOWN` |
| `SSDT-USB-Reset` | 真机上重置 USB 控制器以便做端口映射 | 不需要 | 不做端口映射（`71` 第 6.5.1 节） | `INFERRED` |
| `SSDT-SMC`（给 `isa-applesmc` 补 ACPI 条目） | 让 `AppleSMC` 匹配到 `APP0001` | **条件性**，见 5.3.4 | | `INFERRED` |

**一条关于参考配置的具体发现，照抄它会踩到。** `KNOWN`，本轮交叉读取两处：OSX-KVM 的 `config.plist` 的 `ACPI/Add` 里**恰好两个条目且都 `Enabled = true`**，分别是 `SSDT-EC.aml` 与 `SSDT-USBX.aml`；而该仓库的 `OpenCore/EFI/OC/ACPI/` 目录里**只有四个文件**：`SSDT-DTGP.aml`（100 字节）、`SSDT-EC.aml`（267 字节）、`SSDT-EHCI.aml`（163 字节）、`SSDT-PLUG.aml`（177 字节）。

**即参考配置启用了一个仓库里不存在的文件（`SSDT-USBX.aml`），同时仓库里有两个不被启用的文件。** `INFERRED`：OpenCore 对 `ACPI/Add` 里找不到的文件的处理是记一条日志并跳过，不是致命错误（所以那份配置能用）。但对我们有两条实际后果：

1. **`71` 第 6.2 节说「参考配置两项都启用」是准确的，但「从 OSX-KVM 仓库的 `ACPI/` 取现成件」这个取法拿不到 `SSDT-USBX.aml`。** 必须从 dortania 的预编译 SSDT 取，或者自己从 ASL 编译。登记为 L-014。
2. **构建期必须有一条「`ACPI/Add` 里的每个 `Path` 都要在 `ACPI/` 目录里存在」的门禁**，否则这类静默跳过会一直留在镜像里。脚本在 5.3.5 节。

#### 5.3.1 `SSDT-EC`：唯一必需的那一个

`KNOWN` 对于需求本身：`71` 第 6.2 节已经引过，macOS 10.15 起要求存在一个 embedded controller 设备，而参考配置启用 `SSDT-EC.aml` 用的是**假 EC**版本（给虚机或无 EC 平台用），不是「EC 重命名」版本。`71` 同一节还留了一条警告：**选错版本的表现是 `AppleACPIEC` 匹配不上，而不是报错。**

**父设备路径是这里唯一需要想清楚的事。** dortania 的桌面版假 EC SSDT 把 `Device (EC)` 放在 `\_SB.PCI0.LPCB` 下面，因为真机的 DSDT 里 LPC 桥叫 `LPCB`。**QEMU 的 DSDT 里没有叫 `LPCB` 的设备**（`INFERRED`，QEMU 给 q35 的 ISA/LPC 桥用的是另一个名字）。而 `External` 声明的路径不存在时，OpenCore 加载这张表会失败或者这个 `Scope` 不生效。

**处置：把它挂在 `\_SB.PCI0` 下面。** `PCI0` 是 QEMU 的 DSDT 里确定存在的根 PCI 总线设备（`INFERRED`，这是 QEMU 全部 x86 机型的惯例）。`AppleACPIEC` 匹配的是 `IOACPIPlatformDevice` 且名字/HID 符合，**它不要求 EC 在 LPC 桥下面**（`INFERRED`，这是本节最需要实测确认的一条，验证方法见下）。

**可直接照抄的 ASL 源码：**

```asl
/*
 * SSDT-EC-QEMU.dsl
 * 给 QEMU/OVMF 的 macOS guest 提供一个假的 embedded controller。
 * macOS 10.15 起要求容器内存在一个 EC 设备。
 * 规格: docs/spec/76-BOOT-LAYOUT-PICKER.md 第 5.3.1 节
 *
 * 与 dortania 的桌面版差异：父设备用 \_SB.PCI0 而不是 \_SB.PCI0.LPCB，
 * 因为 QEMU 的 DSDT 里没有名为 LPCB 的 LPC 桥（76 §5.3.1，INFERRED）。
 *
 * 编译（Linux 构建机，一条命令）:
 *   iasl -ve SSDT-EC-QEMU.dsl        # 产出 SSDT-EC-QEMU.aml
 *   mv SSDT-EC-QEMU.aml <stage>/EFI/OC/ACPI/SSDT-EC.aml
 */
DefinitionBlock ("", "SSDT", 2, "M2VU", "ECQEMU", 0x00000000)
{
    External (_SB_.PCI0, DeviceObj)

    Scope (\_SB.PCI0)
    {
        Device (EC)
        {
            /* ACID0001 是社区约定的假 EC 的 _HID，不与任何真实硬件冲突 */
            Name (_HID, "ACID0001")

            /* 只在 macOS 下存在。_OSI("Darwin") 为假时返回 0，
             * 这样同一块盘拿去装别的系统时这个设备不出现。 */
            Method (_STA, 0, NotSerialized)
            {
                If (_OSI ("Darwin"))
                {
                    Return (0x0F)
                }
                Else
                {
                    Return (Zero)
                }
            }
        }
    }
}
```

**三条验证方法，按成本从低到高。第一条现在就能做，不需要 macOS：**

1. **用 Alpine 或任意 Linux guest 把 QEMU 的 DSDT 导出来，看 LPC 桥到底叫什么。** 这正好是第 3 节的救援系统的一个副产品：

```sh
# 在 Alpine rescue 里（4.6.2 节的 world 里加一个 acpica 包即可）
apk add --allow-untrusted acpica          # 或从 ESP 的本地仓库装
acpidump -b                                # 产出 dsdt.dat 等
iasl -d dsdt.dat                           # 反编译成 dsdt.dsl
grep -nE 'Device \((ISA|LPC|LPCB|SBRG)\)' dsdt.dsl
grep -n '_ADR, 0x001F0000' dsdt.dsl        # LPC 桥的 PCI 地址
```

2. **OpenCore 的 `SysReport`。** `71` 第 9.3 节已经说了首次搭建时应该开一次 `Misc/Debug/SysReport = true`，它会把 ACPI 表与 SMBIOS 表导到 ESP 上。**那份导出就是答案**，而且不需要 guest 起来。
3. **macOS 里 `ioreg`。** 进 guest 之后：

```bash
ioreg -c AppleACPIEC -d 2 -w 0            # 有实例 = 匹配成功
ioreg -p IODeviceTree -n EC -r -w 0       # 看 EC 挂在哪
```

**如果第 1 条查出 LPC 桥确实存在且有名字（例如 `ISA`），要不要改成挂它下面？** `INFERRED`：挂在 `PCI0` 下面与挂在 LPC 桥下面，对 `AppleACPIEC` 的匹配应该都成立，因为它匹配的是设备本身而不是父设备。**但如果第 3 条发现匹配不上，第一个要试的改动就是把父设备换成第 1 条查出来的那个名字。** 登记为 L-015。

#### 5.3.2 `SSDT-USBX`：不必需，但保留

它给 `_SB` 下的一个 `USBX` 设备挂四个供电属性。真机上它影响 USB 端口的供电上限与睡眠行为。

**本组合下不必需，三条理由：** 我们不做端口映射；不睡眠；USB 上只有键鼠（`usb-kbd` / `usb-tablet`）或 virtio-input，没有需要大电流的设备。

**但保留它，两条理由：**

1. **与 `71` 第 6.2 节一致。** `71` 已经把它写进 `ACPI/Add`，而它是参考配置里启用的两项之一。改掉一个「无害且与参考配置一致」的项，收益是省 100 多字节，成本是两份文档不一致。
2. **它是一条「不加也不报错、加了也不报错」的配置**，所以它不构成任何归因风险。

**附带一条动作：L-014 说它不在 OSX-KVM 仓库里。** 要么从 dortania 的预编译 SSDT 取，要么用下面的 ASL 自己编译一份（`INFERRED`，属性值取自社区通行的台式机版本）：

```asl
/*
 * SSDT-USBX.dsl  —— USB 供电属性。76 §5.3.2：不必需，与 71 §6.2 保持一致而保留。
 * iasl -ve SSDT-USBX.dsl
 */
DefinitionBlock ("", "SSDT", 2, "M2VU", "USBX", 0x00000000)
{
    Scope (\_SB)
    {
        Device (USBX)
        {
            Name (_ADR, Zero)
            Method (_DSM, 4, NotSerialized)
            {
                If (!Arg2) { Return (Buffer (One) { 0x03 }) }
                Return (Package (0x08)
                {
                    "kUSBSleepPortCurrentLimit", 0x0834,
                    "kUSBSleepPowerSupply",      0x13EC,
                    "kUSBWakePortCurrentLimit",  0x0834,
                    "kUSBWakePowerSupply",       0x13EC
                })
            }
            Method (_STA, 0, NotSerialized)
            {
                If (_OSI ("Darwin")) { Return (0x0F) } Else { Return (Zero) }
            }
        }
    }
}
```

#### 5.3.3 `SSDT-PLUG`：不要加，它与 `71` 的决定方向相反

**这是本节唯一一个「社区常用但我们必须拒绝」的项，所以要说清。**

`SSDT-PLUG` 的作用是在第一个 CPU 对象上注入 `plugin-type = 1`，让 `X86PlatformPlugin` 接管 CPU 的电源管理（即启用 XCPM）。在 Haswell 及之后的真机上这是原生 CPU 电源管理的前提（`KNOWN`，dortania 的各代配置指南都把它列为 required SSDT，转述自 <https://dortania.github.io/OpenCore-Install-Guide/config.plist/skylake.html> 一类页面）。

**在我们这里它的方向是反的。** `71` 第 5.3 节已经设了：

```xml
<key>DummyPowerManagement</key>
<true/>
```

`71` 对它的说明是：「它让 OpenCore 阻止 `X86PlatformPlugin` 一类 CPU 电源管理驱动按真机预期去写 MSR。在 QEMU 上这些 MSR 要么不存在要么语义不同。」

**所以 `SSDT-PLUG` 要做的事（让 `X86PlatformPlugin` 接管）正是 `DummyPowerManagement` 要阻止的事。** 两个一起开，最好的情况是其中一个赢、另一个白做；最坏的情况是在一台宿主没开 `ignore_msrs` 的机器上（`71` 第 5.4 节要求 `ignore_msrs=1`）出现 `#GP` 并 panic。

**另有一条独立的理由：`X86PlatformPlugin` 会按 board-id 去加载 `Mac-27AD2F918AE68F61.plist`**（`71` 第 4.2 节已记录这个 plist 在 payload 里存在，17,436 字节）。那份 plist 描述的是真实 Xeon W-3245M 的频率与功耗向量，而我们的 vCPU 是 QEMU 合成的。**让它按那份表去调频是一个纯粹的风险，没有任何收益**：虚机的频率由宿主决定，guest 调不动。

**结论：`ACPI/Add` 里不要 `SSDT-PLUG.aml`，`DummyPowerManagement` 保持 `true`。** `INFERRED`，但两条理由都是机制性的。

**OSX-KVM 的做法与这个结论一致**：`KNOWN`，它的 ACPI 目录里有 `SSDT-PLUG.aml`，但它的 `config.plist` 的 `ACPI/Add` 里**没有**它（本轮读取的两处来源）。即参考配置也没有启用它。

#### 5.3.4 条件性的 `SSDT-SMC`

`71` 第 6.5.1 节决定了「`isa-applesmc` 当主、`VirtualSMC.kext` 当兜底」，并把两者的匹配竞争登记为 I-006。

**如果 I-006 的结论是「`isa-applesmc` 没被 `AppleSMC` 匹配上」**，一个可能的原因是 QEMU 没有为它生成 ACPI 设备条目，于是 macOS 的 `AppleSMC`（匹配 `IOACPIPlatformDevice` 上的 `APP0001`）找不到它。这时候补一张 SSDT：

```asl
/*
 * SSDT-SMC.dsl  —— 条件性。只在 71 的 I-006 判定"isa-applesmc 未被匹配"时启用。
 * 它为 QEMU 的 isa-applesmc（I/O 端口 0x300，6 字节）补一个 ACPI 设备条目。
 * 76 §5.3.4，INFERRED，端口与长度需用 QEMU 侧的设备属性核对。
 */
DefinitionBlock ("", "SSDT", 2, "M2VU", "SMCQEMU", 0x00000000)
{
    External (_SB_.PCI0, DeviceObj)

    Scope (\_SB.PCI0)
    {
        Device (SMC)
        {
            Name (_HID, EisaId ("APP0001"))
            Name (_CRS, ResourceTemplate ()
            {
                IO (Decode16, 0x0300, 0x0300, 0x01, 0x20)
                IRQNoFlags () { 6 }
            })
            Method (_STA, 0, NotSerialized)
            {
                If (_OSI ("Darwin")) { Return (0x0F) } Else { Return (Zero) }
            }
        }
    }
}
```

**默认不启用。** 它只有在 I-006 的具体结论出来之后才有意义，而在 `VirtualSMC.kext` 已经注入的情况下大概率根本不需要（kext 不依赖 ACPI 条目）。登记为 L-016。

#### 5.3.5 `ACPI/Add` 的最终形态与构建期门禁

```python
# 接 71 §6.1 的 make-oc-config.py。替换它的 ACPI 段。
c['ACPI']['Add'] = [
    {'Comment': 'Fake EC, required since 10.15. QEMU parent = _SB.PCI0 (76 §5.3.1)',
     'Enabled': True, 'Path': 'SSDT-EC.aml'},
    {'Comment': 'USB power properties. Not required on QEMU, kept per 71 §6.2',
     'Enabled': True, 'Path': 'SSDT-USBX.aml'},
    # 以下两项默认关闭，只在对应的未解决项被判定为"需要"时打开
    {'Comment': 'ACPI node for isa-applesmc. Enable only if 71 I-006 says so (76 §5.3.4)',
     'Enabled': False, 'Path': 'SSDT-SMC.aml'},
]
c['ACPI']['Delete'] = []        # QEMU 的表没有要删的（71 §6.2）
c['ACPI']['Patch']  = []        # 同上
c['ACPI']['Quirks'] = {k: False for k in c['ACPI']['Quirks']}
```

**构建期门禁，挡住 L-014 那一类静默跳过：**

```python
#!/usr/bin/env python3
"""scripts/check-oc-tree.py
核对 config.plist 里启用的每一项都在磁盘上存在。
用法:  py scripts\\check-oc-tree.py build\\efi\\EFI\\OC
平台:  Windows / Linux / macOS 均可，只用标准库
"""
import plistlib
import pathlib
import sys

OC = pathlib.Path(sys.argv[1])
c = plistlib.load(open(OC / 'config.plist', 'rb'))
bad = []

for e in c['ACPI']['Add']:
    if e.get('Enabled') and not (OC / 'ACPI' / e['Path']).is_file():
        bad.append(f"ACPI/Add -> ACPI/{e['Path']}")

for e in c['Kernel']['Add']:
    if e.get('Enabled') and not (OC / 'Kexts' / e['BundlePath']).is_dir():
        bad.append(f"Kernel/Add -> Kexts/{e['BundlePath']}")

for e in c['UEFI']['Drivers']:
    if e.get('Enabled') and not (OC / 'Drivers' / e['Path']).is_file():
        bad.append(f"UEFI/Drivers -> Drivers/{e['Path']}")

for t in c['Misc']['Tools']:
    if t.get('Enabled') and not (OC / 'Tools' / t['Path']).is_file():
        bad.append(f"Misc/Tools -> Tools/{t['Path']}")

# OpenCanopy 的强制资源（76 §2.3）
if any(d['Path'] == 'OpenCanopy.efi' and d.get('Enabled')
       for d in c['UEFI']['Drivers']):
    variant = c['Misc']['Boot'].get('PickerVariant', 'Auto')
    if variant not in ('Auto', 'Default'):
        img = OC / 'Resources' / 'Image' / pathlib.PurePath(variant)
        for icns in ('Cursor', 'Selected', 'Selector', 'SetDefault',
                     'Left', 'Right', 'HardDrive'):
            if not (img / f'{icns}.icns').is_file():
                bad.append(f'PickerVariant {variant} 缺 {icns}.icns')
    for sub in ('Font', 'Label'):
        if not (OC / 'Resources' / sub).is_dir():
            bad.append(f'OpenCanopy 启用但缺 Resources/{sub}/')

if bad:
    sys.exit('config.plist 引用了不存在的件:\n  ' + '\n  '.join(bad))
print('ACPI / Kexts / Drivers / Tools / Resources 五张表与磁盘一致')
```

```powershell
# 接 stage-efi.ps1 末尾。失败就让整个构建失败，不要只打印警告。
py scripts\check-oc-tree.py build\efi\EFI\OC
if ($LASTEXITCODE -ne 0) { throw 'EFI 树与 config.plist 不一致' }
```

**这条门禁覆盖五张表**（ACPI、Kexts、Drivers、Tools、OpenCanopy 的 Resources），所以它同时挡住本文发现的三类错误：`SSDT-USBX.aml` 不在参考仓库里（L-014）、`OpenHfsPlus.efi` 对 `HfsPlus.efi` 的文件名错误（L-003）、以及「启用了 OpenCanopy 但忘了装资源」。**三类错误里有两类是本轮在真实仓库里实际碰到的，所以这个脚本不是预防性的，是修复性的。**

### 5.4 kext 最小集：三卷布局与 Alpine 共存下不变

**结论：`71` 第 4 节与第 6.5.1 节定的三个 kext（Lilu / VirtualSMC / AppleMCEReporterDisabler）在本文的布局下一个不多、一个不少。**

逐条确认为什么三卷布局与 Alpine 的加入不改变它：

| 可能的疑问 | 回答 | 依据 |
|---|---|---|
| 多了一个 BaseSystem 分区，要不要额外的文件系统 kext | **不要。** p2 是 APFS 或 HFS+，两者的内核侧驱动都在系统自带的 KC 里。**而且引导期读它的是 UEFI 驱动（`apfs.efi` 或 `HfsPlus.efi`），不是 kext** | 3.1 节的类型 GUID 表 |
| ESP 上有 Alpine 的文件，macOS 要不要读 ext4 | **不要。** 方案 A 没有 ext4 分区（3.3.4 节）。macOS 只需要读 FAT，而 `msdosfs` 在 System KC 内 | `71` 第 8.4 节，`KNOWN` |
| 确认 daemon 要写 ESP，要不要额外 kext | **不要。** 同上，`msdosfs` 自带，`74` 第 4.6 节已确认 | `KNOWN` |
| OpenCanopy 要不要 guest 侧的东西 | **不要。** 它是 UEFI 阶段的程序，`ExitBootServices` 之后就不存在了 | — |
| 为什么不需要 USB map | QEMU 的 xhci 端口数由我们决定，不存在真机的 15 端口上限问题；`XhciPortLimit` 保持 `false` | `71` 第 6.5.1 节，`KNOWN` |
| 为什么不需要网卡 kext | `AppleVirtIONetwork`（匹配 `IOVirtIOPrimaryMatch = 0x00011af4`）与 `AppleVmxnet3Ethernet`（匹配 `0x07b015ad`）都在 x86_64 **Boot KC** 内，即启动期就可用 | `71` 第 3.5 节，`KNOWN` |
| 为什么不需要显卡 kext | 本项目自己写显卡驱动（`00-OVERVIEW` 第 5 节组件 2、3）。`WhateverGreen` 的作用对象是 Apple 的 AMD/Intel/NVIDIA 驱动，对我们自己的 provider 是未定义行为；而且它会参与 AGDP 决策，把 `71` 第 4.3 节门 2 已经确定的变量变回不确定 | `71` 第 6.10 节 |
| 三卷布局会不会影响 `AppleMCEReporterDisabler` | 不会。它只与 board-id 有关（`MacPro7,1` 的 board-id 在 `AppleIntelMCEReporter` 的 `IOPropertyMatch` 里），与磁盘布局无关 | `71` 第 4.3 节门 1，`KNOWN` |

**一条本文新增的 kext 侧注意：`ApplePVPanic` 在 Boot KC 里且匹配 `QEMU0001`（`71` 第 3.6 节，`KNOWN`）。** 它不需要注入（系统自带），但它对第 4 节的机制有价值：**在 L1 上加 `-device pvpanic` 之后，host 能通过 QMP 的 `GUEST_PANICKED` 事件立即知道 guest panic 了**，于是 4.8 节 W12 那条「S2 被正确分类」的验证可以同时用两条独立信号核对（ESP 上没有 `A` 行 + QMP 报了 panic）。**L2 上拿不到这条信号**（`80` 第 1.3 节），所以 ESP 面包屑仍然是唯一依据。

### 5.5 Booter / Kernel / UEFI Quirks 的增量

`71` 第 6.3、6.5.3、6.9.2 节已经逐项给了值。**本节只指出三卷布局与 OpenCanopy 引入的新增项与需要复核的项。**

| Quirk | `71` 的值 | 本文 | 理由 |
|---|---|---|---|
| `UEFI/Quirks/RequestBootVarRouting` | **`true`** | **`true`（不变）** | `71` 第 6.9.2 节的理由是官方强烈建议，把 `Boot####` 变量隔进 OpenCore 的命名空间，避免固件删掉 macOS 建的启动项。**本文加一条它在三项布局下更重要的理由**：官方 Boot Algorithm 的 Note 1 明确，启动顺序的查找「只在启用 `RequestBootVarRouting` 或固件不控制 UEFI 启动选项时才可靠工作」，而我们有三个启动项要排序（`KNOWN`，转述自 <https://dortania.github.io/docs/release/Configuration.html>）。**它需要 `OpenRuntime.efi`，我们已经启用** |
| `UEFI/Quirks/ReleaseUsbOwnership` | `false` | **`false`（不变）** | 它解决的是固件在把控制权交给 OS 之前不释放 USB 控制器所有权的真机缺陷。**OVMF 没有这个缺陷**（`INFERRED`，OVMF 的 USB 栈在 `ExitBootServices` 时正常释放）。**而且它有一个具体的坏处：提前释放 USB 所有权会让 OpenCanopy 的键盘与指针在 picker 还在显示时失效。** 在一个要靠键盘进选择器的配置里，打开它是直接有害的。`INFERRED`，登记为 L-017 |
| `Booter/Quirks/SyncRuntimePermissions` | `true` | **`true`（不变），但理由多一条** | `71` 第 6.3 节开它的理由是「OVMF 的内存图会随版本变化，副作用面很小」。**本文补一条官方依据**：`OpenLinuxBoot` 一节明确提到 `SyncRuntimePermissions` 这个 quirk「可能需要开启，以避免 Linux 内核早期启动失败（典型表现是停在黑屏），原因是 2017 年之后某些固件的一个 bug；存在且未被这个 quirk 缓解时，无论用不用 `OpenLinuxBoot`，经 OpenCore 启动都会受影响」（转述自同一来源）。**我们要经 GRUB 启动一个 Linux 内核，所以这条依据对本文直接适用**（`KNOWN`） |
| `Booter/Quirks/FixupAppleEfiImages` | `true` | `true`（不变） | `71` 第 6.3 节的 I-023。`SecureBootModel = Disabled` + OVMF 的组合需要它 |
| `UEFI/Output/ProvideConsoleGop` | `true` | **`true`（OpenCanopy 的硬前提）** | 没有 GOP 就没有图形选择器。`71` 第 6.10 节处理办法 3 已经警告过不要用 `-vga none` |
| `UEFI/Output/TextRenderer` | `BuiltinGraphics` | `BuiltinGraphics`（不变） | OpenCanopy 自己画，这一项影响的是退回 `Builtin` 时的渲染 |
| `UEFI/Output/UIScale` | 未提及 | **不设这个键**，改用 NVRAM 的 `UIScale`（2.4.1 节） | 两者是不同的东西：`config.plist` 的 `UEFI/Output` 下没有 `UIScale`，缩放是靠 NVRAM 变量 `4D1EDE05-...:UIScale` 传给 `boot.efi` 与 OpenCanopy 的 |
| `UEFI/Input/KeySupport` | `true` | **`true`（硬前提）** | `KNOWN`，官方 `PickerMode` Note 1：**非 Apple 固件上按键处理需要 `KeySupport`、`OpenUsbKbDxe` 或类似驱动。** 不开就按不了 OPT，也按不了 `CMD+R` |
| `UEFI/Input/KeySupportMode` | `Auto` | `Auto`（不变） | |
| `UEFI/Input/PointerSupport` | `false` | **`false`（不变）** | 2.7 节末段，L-006 |
| `UEFI/Input/TimerResolution` | `50000` | `50000`（不变） | |
| `UEFI/Audio/AudioSupport` | `false` | **`false`（不变）** | 没有音频设备。**代价要写清：没有开机音，所以 2.4 节 `TakeoffDelay` 不能用官方说的「用开机音当按键时机信号」那条办法**，只能用 10 ms 的下限值 |
| `Misc/Security/ScanPolicy` | `0` | **`0`（不变，而且三项布局让它更必要）** | `71` 第 7.3 节：`0` 是全扫。三项布局要同时扫到 ESP（FAT，Alpine 的 GRUB）、p2（APFS 或 HFS+）、p3（APFS），而三者可能挂在不同控制器类型上（`71` 第 7 节的三个候选）。**任何白名单都可能在换控制器时漏掉一项** |
| `Misc/Security/DmgLoading` | `Signed` | **`Signed`（不变）** | 第 1.5.3 节选的是独立分区形态，**完全不经过 DMG 加载**，所以 `71` 第 6.6.3 节的 I-007（是否要改 `Any`）在本文的布局下**不再需要被关闭**。这是三卷布局的一个附带收益 |
| `Misc/Security/AllowSetDefault` | `true` | `true`（不变） | 给人用的，不给流水线用（2.6 节纪律 2） |
| `Misc/Security/Vault` | `Optional` | **`Optional`（不许改成 `Secure`）** | 本文往 ESP 加了 Resources、Alpine 三件套、apk 仓库、若干状态文件。`Secure` 要求一份覆盖全部文件的签名 `vault.sig`，而其中若干文件是**运行期会变的**（`STATE.TXT`、`LOG.TXT`、`config.plist`）。**Vault 与 `74` 的 shim 机制从根本上不兼容** |

---

## 6. 本文对既有分册的修正登记

**本文不修改其他任何文件。** 下表是本文产生的、需要在那些分册下一次修订时合并的修正。每一条给出原文位置、修正内容、理由所在的本文章节。

### 6.1 对 `71-IMAGE-OPENCORE.md`

| # | 原文位置 | 原文 | 修正 | 理由 |
|---|---|---|---|---|
| 71-A | 第 6.9.1 节表格、第 8.2.1 节 `stage-efi.ps1` 的驱动列表 | 驱动文件名 `OpenHfsPlus.efi` | **`HfsPlus.efi`**，且来源是 `OcBinaryData` 的 `Drivers/` 而不是 OpenCorePkg release | 本文 2.2 节。`KNOWN`：`OcBinaryData/Drivers/` 下没有这个文件名。照抄会在 `Copy-Item` 处失败 |
| 71-B | 第 6.6.1 节 | `PickerMode = Builtin`、`PickerAttributes = 17` | 做成 `picker` 档位参数：`visible` / `apple` 用 `External` + `211`，`builtin` 保留原值 | 本文 2.4、2.7 节。不是推翻，是把原值降级为排障档 |
| 71-C | 第 6.2 节 | 「两个 `.aml` 不要自己写，用现成的预编译件…`OSX-KVM` 仓库的 `OpenCore/EFI/OC/ACPI/` 下有副本」 | **`SSDT-USBX.aml` 不在那个目录里。** 该目录只有 `SSDT-DTGP.aml`、`SSDT-EC.aml`、`SSDT-EHCI.aml`、`SSDT-PLUG.aml` 四个文件 | 本文 5.3 节，`KNOWN`，本轮读取仓库目录。处置见 L-014 |
| 71-D | 第 6.2 节 | 两个 SSDT 的来源与版本 | **`SSDT-EC` 的父设备路径在 QEMU 上与 dortania 桌面版不同。** 本文 5.3.1 节给出针对 `\_SB.PCI0` 的 ASL 源码 | 本文 5.3.1 节。`71` 自己留的警告「选错版本的表现是匹配不上而不是报错」正是这一条 |
| 71-E | 第 6.6.3 节的 I-007 | 「若必须走路 B 则改 `DmgLoading = Any`」 | **在三卷布局下 I-007 不再需要被关闭。** p2 是一个普通分区，完全不经过 DMG 加载，`DmgLoading` 保持 `Signed` | 本文 1.5.3、5.5 节。这是三卷布局的一个附带收益 |
| 71-F | 第 8.2.2 节 | ESP 为 64 MiB 的裸 FAT32 | **512 MiB，且在 GPT 内**（三分区布局的 p1） | 本文 3.1、3.4 节。`73` 第 5.2 节已经把它改到 256 MiB 并放进 GPT，本文再扩一倍 |
| 71-G | 第 8.2.1 节 | 「`EFI/OC/Resources` 留空是对的」 | **不再留空。** 本文 2.3 节给出要装的三个子目录与取资源脚本 | 本文 2.3 节。`71` 自己留了后半句「如果以后要用 OpenCanopy，资源来自 `OcBinaryData`，那时才需要固定它的 commit」，本文就是那个「以后」 |

### 6.2 对 `73-DEPLOY-RESCUE.md`

| # | 原文位置 | 原文 | 修正 | 理由 |
|---|---|---|---|---|
| 73-A | 第 5.1 节 | 选候选 B（系统盘内的独立 rescue 分区，Alpine 的 `sys` 模式磁盘安装） | **改选「ESP + RAM」**，即一个 `73` 当时没有列出的第五个候选。它同时具备 B 的持久性（文件在我们自己的 ESP 上）与 A 的零分区占用 | 本文 3.3 节。决定性的新数据是 Alpine `virt` flavour 的三件套只有 40 MB（`KNOWN`，`lts` 是 247 MB） |
| 73-B | 第 5.2 节分区布局 | p1 ESP 256 MiB / **p2 ext4 1.5 GiB RESCUE** / p3 APFS | **p1 ESP 512 MiB / p2 BaseSystem 1600 MiB / p3 APFS** | 本文 3.1 节。ext4 分区去掉，恢复环境分区加进来 |
| 73-C | 第 5.2 节末段的 D-010 | 「macOS 对 ext4 分区的实际行为未实测」 | **D-010 可以关闭**，因为布局里不再有 ext4 分区 | 本文 3.3.3 节 |
| 73-D | 第 5.3.2 节 `/etc/local.d/00-revert-boot.start` | 只做一件事（把下次启动还给 macOS） | **并入本文 4.6.2 节的 `/etc/local.d/00-rescue.start`**，它做四件事（交还、读状态、写报告、打包证据），第一件与原脚本等价 | 本文 4.6.2 节。两个脚本做同一件事会竞争同一个文件 |
| 73-E | 第 5.3.2 节的 `grub.cfg` | `linux /boot/vmlinuz-lts root=LABEL=RESCUE modules=sd-mod,usb-storage,ext4` | **本文 4.6.1 节的 diskless 版本**（`virt` flavour、`alpine_dev=LABEL=OPENCORE`、本地 `modloop=`、`apkovl=`） | 本文 4.6.1 节。`74` 第 4.7 节已经改过这个文件的 menuentry 列表，本文再改 `linux` 那一行 |
| 73-F | 第 5.4 节 R1 层 | 「构建期在 ESP 上放一个 FAT 的信箱目录，让 macOS 侧的 agent 在每次关机前把最近的 panic 报告复制一份进去」 | **已落地**：路径是 `\EFI\CPUDISP\PANIC\`，写入动作在本文 4.5 节脚本的第 6 步，**而且是开机时写而不是关机前写** | 本文 3.2、4.5 节。开机写比关机写可靠：一台会 panic 的机器未必有机会执行关机钩子 |
| 73-G | 第 5.4 节 R1 层的 D-012 | 「Alpine 的仓库里是否有可用的 APFS 只读驱动未确认」 | **优先级下调。** 本文 4.6.2 节第 6 步把「rescue 对 APFS 只读」变成一条纪律（一行都不碰），而 panic 报告改由 73-F 的信箱提供。**D-012 从「影响 R1 能否取证」降为「nice to have」** | 本文 4.6.2、4.7 节 |

### 6.3 对 `74-BOOT-CPU-DISPATCH.md`

| # | 原文位置 | 原文 | 修正 | 理由 |
|---|---|---|---|---|
| 74-A | 第 4.2 节状态文件格式 | 八个键 | **加 `fails` 与 `rescues` 两个键，魔数仍是 `CPUDISP1`** | 本文 4.3 节。保持魔数是为了新旧 shim 双向兼容 |
| 74-B | 第 4.5 节 `STATE` 结构与 `state_read` / `state_write` | — | **本文 4.3.3 节的三处替换** | 同上 |
| 74-C | 第 4.5 节 `efi_main` 的状态机 | `s.inflight = 1` 无条件；无 `fails` 分支 | **本文 4.4.1 节的完整替换块。** 四个要点：`fails++` 无条件；`cand++` 仅在未确认态；`fails >= FAILMAX` 时进 rescue 且 `inflight = 0`；`STICKY` 分支 | 本文 4.2、4.4 节。**其中 `inflight = 0` 那一条是修一个 bug**：照原文，一次成功的 rescue 会被下一次启动记成一次 macOS 失败 |
| 74-D | 第 4.5 节 `BOOT_BUDGET 12` | 12 | **16** | 本文 4.4.3 节。rescue 启动现在也消耗预算 |
| 74-E | 第 4.7 节第三层 | 预算耗尽 → `beacon()` 停住 | **预算耗尽 → 创建 `STICKY` 并钉在 rescue。`beacon()` 只保留给「rescue 自己也起不来」** | 本文 4.4.3 节。逐列对比表显示钉在 rescue 在每一列上都不差，在「能不能 SSH」「能不能读日志」「能不能修 ESP」三列上明显更好 |
| 74-F | 第 4.6 节的 `cpudisp-confirm.sh` | 四步（等 sshd、找 ESP、写状态、搬日志、修引导对象） | **本文 4.5 节的替换版，八步。** 新增：开机即写 `ALIVE.TXT` 的 `A` 行、超时写 `N` 行、记录里带 `fails` 与 `rescues`、panic 信箱、日志轮转 | 本文 4.5、4.7 节。`A` / `N` 行是 4.7 节边界情形能被正确分类的唯一依据 |
| 74-G | 第 4.7 节的 `grub.cfg` | 三个 menuentry，第一个用 `root=LABEL=RESCUE` | **本文 4.6.1 节的版本。** menuentry 列表与顺序不变，只改第一个的 `linux` 行 | 本文 4.6.1 节 |
| 74-H | 第 4.9 节验证矩阵 V1 到 V10 | — | **新增 W1 到 W15**（本文 4.8 节）。V 系列继续有效 | 本文 4.8 节 |

### 6.4 对 `80-TEST-HARNESS.md`

| # | 原文位置 | 修正 | 理由 |
|---|---|---|---|
| 80-A | 第 2.9 节 `Detector` / 第 5.6 节的状态机 | **新增一条规则：SSH 在 `boot_timeout`（建议 900 秒）内不可达时，调平台 API `reboot`，而不是直接升级到救砖流程。** 本文第 4 节的三次失败机制依赖「有人去重启它」这个外部动作 | 本文 4.1 节性质 3，L-010。**这是本文对 `80` 唯一的硬依赖** |
| 80-B | 第 2.8 节取证流程 | **新增一个采集项**：rescue 的 `REPORT.TXT` 与 `/tmp/rescue-evidence.tgz`（本文 4.6.2 节第 4、5 步），以及 macOS 侧 `/var/log/cpudisp/` 下的三个文件（本文 4.5 节第 5 步） | 本文 4.5、4.6 节 |
| 80-C | 第 2.3.5 节 guest 内 ARD/VNC | **无需修改，但要记一条交叉结论**：该节的三条告警里第一条（黑屏不可归因）与本文 2.6 节的结论同源。**ARD/VNC 这条通道同样要经 SSH 隧道，所以本文 4.7 节的 E2 情形（SSH 不通）会让它一起失效。** 即 E2 下 L2 的全部观测通道同时为零，这正是把 E2 判为失败的理由 | 本文 4.7 节理由 1 |
| 80-D | 第 2.1 节的提升门槛 | **新增一条**：凡是改动 ESP 内容（含 `config.plist`、候选 plist、Alpine 三件套、apkovl）的实验，必须先在 L1 跑过本文 4.8 节的 W2、W8、W15 三条 | 本文 4.8 节 |

### 6.5 对 `75-IMAGE-PREBAKE.md`

`75` 与本文是同一轮产出的两册，交叉点集中在分区布局与 Recovery 卷。**两边的结论不冲突，但 `75` 第 4.2、4.3 节的具体尺寸与分区用途要按本文第 3 节更新。**

| # | 原文位置 | 原文 | 修正 | 理由 |
|---|---|---|---|---|
| 75-A | 第 4.2 节分区布局 | p1 ESP 256 MiB / **p2 ext4 1.5 GiB RESCUE** / p3 APFS 约 30 GB | **p1 ESP 512 MiB / p2 BaseSystem 1600 MiB / p3 APFS 剩余** | 本文 3.1、3.3、3.4 节。**镜像总容量仍是 32 GB，不需要改**（本文 3.5 节的对照表） |
| 75-B | 第 4.3 节 `assemble-golden.sh` | `ESP_MIB` 与 `RES_MIB=1536`；段 3 的职责里有「装 Alpine 到 p2」 | `ESP_MIB=512`；p2 改成 `dd` 已还原的 BaseSystem 卷镜像；**段 3 不再需要「装 Alpine 到 p2」这一步**，Alpine 变成 ESP 内的四样文件（三件套 + apkovl） | 同上。**这让段 3 的 Linux 侧工作量下降**：不再需要在构建机上做一次 Alpine 的 `sys` 模式安装 |
| 75-C | 第 4.3 节「运行器上不要造 GPT」的理由 3 | 「rescue 分区是 ext4，macOS 造不出来」 | **这条理由作废**（布局里没有 ext4 分区了），但**理由 1 与 2 仍然成立**，所以「运行器上不要造 GPT」这个结论不变 | 本文 3.3.4 节 |
| 75-D | 第 2.3.2 节 | 「我们不需要自己造 Preboot 和 Recovery，`asr` 会造」 | **无需修改。本文第 1.5.2 节形态二引用它作为结论依据。** 但要加一条交叉注记：它造出的 Recovery 是**运行器那一版的 build**，与我们的系统卷可能不同 build（本文 L-023，与 `75` 自己的 `P-016` 同源） | 本文 1.5.2 节 |
| 75-E | 第 4.1 节实占表 | 「rescue（Alpine sys 模式）1.6 GB」一行 | 改成「p2 BaseSystem 恢复环境 1.6 GB」；ESP 一行从 0.27 改成 0.54 | 本文 3.5 节。**实占合计 18 到 28 GB 与推荐值 32 GB 均不变** |
| 75-F | 第 5 节的离线预配清单（9 项，全在 Data volume 上） | — | **新增两项**，都在 Data volume 上，所以不破坏它「封印不用过」的结论：`/usr/local/libexec/cpudisp-confirm.sh`（本文 4.5 节）与 `/Library/LaunchDaemons/net.metal2vu.cpudisp-confirm.plist`（`74` 第 4.6 节）。**另加一项目录**：`/var/log/cpudisp/` | 本文 4.5 节。**没有这两项，第 4 节的三次失败机制在预烘出来的镜像里不存在**，于是第一次启动就会被判成失败 |

**75-F 是这一组里最要紧的一条。** `75` 的产物是一块「开箱即 SSH 与 VNC 可用」的系统盘，而本文的确认 daemon 必须在那块盘里就位。**如果预烘镜像漏了它，机器会在三次启动之后被切到 Alpine，而 macOS 其实一直是好的** —— 这正是本文 4.7 节那个边界情形的一个人为制造版本，而且它会在每一台新部署的实例上发生。登记为 L-024。

---

## 7. 未解决项清单

编号 `L-` 代表 layout 与 picker。与 `70` 的 `P-`、`71` 的 `I-`、`72` 的 `C-`、`73` 的 `D-`、`80` 的 `H-` 并列，互不重叠。

**「现在能做」一列是本清单最重要的一列。** 按 `00-OVERVIEW` 第 7 节补充规则第 4 条，「没查」不等于「被阻断」，所以能用现有材料查清的一律不标 `BLOCKED`。

| # | 问题 | 标签 | 查清方法 | 现在能做 | 阻塞什么 |
|---|---|---|---|---|---|
| **L-001** | APFS 角色字母 `N` / `L` / `C` / `Y` / `G` 分别是什么角色 | `INFERRED` | guest 里跑 `diskutil apfs addVolume` 看用法串；或 `strings /usr/sbin/diskutil \| grep -i role` | 否（要 guest） | 不阻塞任何事。我们只用 `S`/`D`/`B`/`V`/`R` |
| **L-002** | OpenCore 把 p2（BaseSystem 分区）归类成 Apple 还是 Apple Recovery | `INFERRED` | L1 上看 OpenCore DEBUG 日志的 `OCB:` 条目类型；或看它在 `HideAuxiliary = true` 下是否消失 | **否**（要 L1 启动） | 影响条目的图标、名字、是否被 `HideAuxiliary` 隐藏。**不影响可引导性**。两种修正手段在 2.5.2 节 |
| **L-003** | `HfsPlus.efi` 是否就是 `71` 所说的 `OpenHfsPlus.efi` 的等价物 | `KNOWN`（文件名）/ `INFERRED`（功能等价） | 下载 `OcBinaryData/Drivers/HfsPlus.efi`（37,892 字节），在 L1 上确认它能让 OpenCore 读出 HFS+ 卷 | **是**（下载 + 看 L1 日志） | 若 p2 判定为 HFS+（L-007），它是读出 p2 的前提 |
| **L-004** | `OC_ATTR_USE_MINIMAL_UI`（去掉关机/重启按钮）是否更接近 Intel Mac 的 Startup Manager | `INFERRED` | L1 上 `screendump` 两张图（`0xD3` 与 `0x93`），与真机 Startup Manager 的截图对比 | 否（要 L1） | 纯视觉保真度。两个取值都能正常启动 |
| **L-005** | `Alpine.icns` 怎么产出 | `INFERRED` | 构建机上 `apt install icnsutils` 后用 `png2icns`，在 L1 上看 OpenCanopy 能不能解析 | **是** | 纯外观。缺它时 flavour 串退到 `HardDrive.icns`，功能不受影响 |
| **L-006** | OpenCanopy 的指针在 OVMF + `usb-tablet` 下能不能用，要不要开 `UEFI/Input/PointerSupport` | `INFERRED` | L1 上先试 `PointerSupport = false`，鼠标不动再改 `true` | 否（要 L1） | 纯交互便利。自动化路径不用指针 |
| ~~**L-007**~~ | 还原出的 `x86_64BaseSystem.dmg` 的卷是 APFS 还是 HFS+ | **`TESTED`，已关闭** | **`32-COMPILER-PLUGIN.md` 第 1 节与第 3 节早就答过了，本册没引到。** 那一轮实际跑了 `ipsw disk dmg -p 3`，取出的是一个 **`Apple_APFS`** 分区原始镜像，**1,396,506,624 字节**；样本表里 `S-BASESYS` 的容器类型一栏记的就是 `UDIF / Apple_APFS` | 已完成 | **p2 的类型 GUID = `7C3457EF-0000-11AA-AA11-00306543ECAC`。** 连带关掉 `71` 的 `I-022`：那个 DMG **是带 GPT 的磁盘镜像**，不是裸卷镜像，要写进 p2 的是它**第 3 个分区**的内容 |
| **L-008** | Alpine `virt` flavour 的内核是否含 `VIRTIO_BLK` / `VFAT_FS` / `SQUASHFS` / `EFI_STUB` | `INFERRED` | 下载 `config-6.12.114-0-virt`（146 KB，与三件套同目录）并 grep 这四个符号 | **是，纯下载** | 决定方案 A 可行性。不行就换 `lts`（ESP 要 1 GiB）或退方案 B（3.3.4 节） |
| **L-009** | `OcBinaryData` 的 Font + Label + GoldenGate 实际占多少 | `INFERRED`（预算 20 MiB） | 2.3 节脚本第 5 步会打印 | **是，跑一次脚本** | 只影响 ESP 容量预算。512 MiB 有足够余量 |
| **L-010** | 谁在 SSH 不可达时去重启机器 | 设计缺口 | 在 `80` 的 `Detector` 里加一条规则（6.4 节 80-A） | **是，写进 `80`** | **这是本文第 4 节机制的唯一硬外部依赖。** 没有它，一台卡住的机器永远不会前进到下一次判定 |
| **L-011** | `alpine_dev=LABEL=OPENCORE` 与本地路径形式的 `modloop=` / `apkovl=` 是否被 Alpine 的 init 接受 | `INFERRED` | L1 上手工在 GRUB 里选第一项（4.8 节 W5）。失败时把 `quiet` 去掉看 init 的输出 | 否（要 L1，但零成本） | **方案 A 的核心前提。** 两条降级方案在 4.6.1 节 |
| **L-012** | `etc/.default_boot_services` 空文件的实际效果 | `INFERRED` | 跑 W5，`rc-status` 看 default runlevel 里有哪些服务 | 否（要 L1） | 若它导致必要服务缺失，删掉即可（4.6.2 节） |
| **L-013** | 未签名的本地 apk 仓库能不能直接用，还是必须 `--allow-untrusted` | `INFERRED` | 4.8 节 W6（断网起 Alpine，看 sshd 有没有起来） | 否（要 L1，零成本） | **若两者都不行，「断网也能救援」这个性质就没了**，救援退化成依赖网络 |
| **L-014** | `SSDT-USBX.aml` 从哪里取 | `KNOWN`（它不在 OSX-KVM 的 ACPI 目录里） | 从 dortania 的预编译 SSDT 取，或用 5.3.2 节的 ASL 用 `iasl` 编译 | **是** | 不阻塞启动（它不必需）。但 5.3.5 节的门禁会在它缺失时让构建失败，所以要么取到要么把条目关掉 |
| **L-015** | 假 EC 挂在 `\_SB.PCI0` 下面能不能被 `AppleACPIEC` 匹配；QEMU 的 LPC 桥叫什么名字 | `INFERRED` | 5.3.1 节三条方法。**第一条用 Alpine 的 `acpidump` + `iasl`，不需要 macOS** | **是**（起一次 Alpine 或任意 Linux guest） | **这是第 5 节唯一真正需要确认的事。** 匹配不上的表现是「不报错但 EC 不存在」，而 10.15 起要求它存在 |
| **L-016** | `isa-applesmc` 是否需要一张 SSDT 才能被 `AppleSMC` 匹配 | `INFERRED` | 它依赖 `71` 的 I-006（`ioreg -c AppleSMC` 看有几个实例） | 否（要 guest） | 默认不启用 `SSDT-SMC.aml`。`VirtualSMC.kext` 已注入，大概率不需要 |
| **L-017** | `ReleaseUsbOwnership` 在 OVMF 上是否影响 OpenCanopy 的键盘与指针 | `INFERRED` | L1 上对照两次启动，看 picker 里的按键是否仍然响应 | 否（要 L1） | 我们保持 `false`，所以这是一条「不要误开」的记录而不是待办 |
| **L-018** | `.contentDetails` 与 `.contentFlavour` 对 `BlessOverride` 发现的条目是否生效 | `INFERRED` | 4.8 节 W3（看 Alpine 项的名字是不是 `Rescue`） | 否（要 L1） | 纯外观。不生效时 Alpine 项显示成 `grubx64.efi` 一类默认名 |
| **L-019** | Alpine 的 `vmlinuz-virt` 能否直接作为 EFI 应用被加载（EFI stub），从而去掉 GRUB 这一环 | `INFERRED` | 先做 L-008 的 `EFI_STUB` 检查；再用 OpenCore 的 `Misc/Entries` 或 shim 直接 `LoadImage` 它，`Arguments` 里给 `initrd=` | **一半能做**（配置检查能做，实测要 L1） | **纯简化，不做也没问题。** 去掉 GRUB 能省 2 MB 与一整个组件，但 GRUB 同时承担 `74` 第 4.7 节的「超时落回 shim」这个安全阀，**去掉它要先给那个安全阀找一个替代** |
| **L-020** | 三个条目在选择器里的实际顺序 | `INFERRED` | 4.8 节 W1 | 否（要 L1） | 影响默认项是哪个。**默认项错了的后果在无头环境里是「每次都启动错的系统」**，所以这一条比它看起来重要 |
| **L-021** | 512 MiB 的 ESP 与 24 GB 的瘦镜像是否仍然满足 `73` 第 4.2 节 `create-from-url` 的全部约束 | `INFERRED` | 复核 `73` 的 D-003（快照通道是否有未公开上限） | **是**（读 `73` 并算一遍） | 若有上限，要砍的是 p2 而不是 ESP（3.5 节） |
| **L-022** | 从「第一次失败」到「拉起 Alpine」的实际墙上时间 | 设计 | `3 × (boot_timeout + 启动时间)`。按 `boot_timeout = 900` 秒算约 50 到 60 分钟 | **是**（算术） | **影响 `FAILMAX` 默认值是否合适。** 如果 50 分钟太久，正确的调整是降 `boot_timeout` 而不是降 `FAILMAX`，因为降 `FAILMAX` 会提高误判率 |
| **L-023** | `75` 的 R1 路径下 `asr` 造出的 Recovery 卷是运行器的 build（当前 25G76）而不是 25G325，这个差距有没有实际影响 | `INFERRED` | 进那个 recoveryOS 看 `sw_vers`；或在它里面读 `/System/Library/CoreServices/SystemVersion.plist` | 否（要 L1 启动到 recovery） | **不阻塞启动。** 影响的是「在恢复环境里做与版本相关的判断」是否可信。与 `75` 的 `P-016` 同源 |
| **L-024** | 预烘镜像里有没有本文第 4 节的确认 daemon（6.5 节 75-F） | 设计缺口 | 在 `75` 第 5 节的预配清单里加两项一目录，并在它的 workflow 里加一条断言：镜像挂载后 `/Library/LaunchDaemons/net.metal2vu.cpudisp-confirm.plist` 必须存在 | **是，写进 `75`** | **漏了它的后果是每一台新部署的实例都会在三次启动后被切到 Alpine，而 macOS 其实是好的。** 这是本清单里唯一一条「漏了必然出错」的项 |

### 7.1 必须在任何 L2 花钱之前做掉的五条

从上表里挑出「现在能做」且「阻塞下游」的：

| # | 为什么必须先做 | 成本 |
|---|---|---|
| **L-007** | 它决定 p2 的分区类型 GUID。错了的表现是 OpenCore 扫不到 p2，而那在无头机器上无法归因 | 一条命令，15 秒 |
| **L-008** | 它决定第 3 节的整个 Alpine 方案成不成立 | 一次下载 + 四次 grep |
| **L-015** | 它决定唯一那个必需的 SSDT 对不对 | 起一次 Linux guest 跑 `acpidump` |
| **L-010** | 它是第 4 节机制的外部依赖，而且它要改的是 `80` 而不是本文 | 写进 `80` 的状态机 |
| **L-024** | 预烘镜像漏了确认 daemon 的话，**每一台新实例都会被误判成失败并切到 Alpine**。这是唯一一条「漏了必然出错」的项 | 在 `75` 的预配清单里加两项并加一条断言 |

**L-011 与 L-013 虽然要 L1，但同样必须在 L2 之前。** 它们是 4.8 节 W5 与 W6 两条，加起来是两次本地启动。

---

## 8. 对所有者四条任务的逐条回答

本节把前七节压缩成所有者能直接读的形态。每条给出结论与它在本文的出处。

**任务 1：启动选择器的风格对齐 Apple 的 Startup Manager。**

对应物是 **OpenCanopy**，配法在第 2 节，可以直接照抄 2.4.5 节的 `Misc/Boot` 片段与 2.7 节的脚本。关键三项：`PickerMode = External`、`PickerVariant = Acidanthera\GoldenGate`（官方描述为 macOS 11 风格，是三个内置集里唯一与 macOS 26 同代的）、`PickerAttributes = 211`。资源从 `OcBinaryData` 取 `Font` / `Label` / `Image/Acidanthera/GoldenGate` 三个目录，固定 commit。

**但 2.6 节那条提醒必须一起接受**：`73` 第 1.3 节已证明 Vultr 没有可编程控制台，所以选择器画面在 L2 上没有观察者。风格对齐的价值在本地 L1 与人工排障；自动化路径必须靠 `Timeout` 自动走默认项。本文为此把选择器做成 `visible` / `apple` / `builtin` 三档构建参数，**默认交付 `visible`**，即选择器总是出现并在 5 秒后自动走默认项。

**任务 2：澄清「一个恢复盘一个系统盘」。**

这个认知在 macOS 10.12 之前字面正确（那时 Recovery 确实是一个独立的 `Apple_Boot` GPT 分区），10.13 之后过时。macOS 26 的真实形态是**一个 APFS 容器内至少五个卷**：System、Data、Preboot、VM、Recovery（`KNOWN`，Apple 平台安全指南）。全表在 1.2 节。

启动链真正依赖的是 **Preboot**（`boot.efi` 在它的 per-volume 目录里）、**System**（snapshot 提供内核与 `/System`）、**Data**（可写状态）。**我们的镜像必须有这三个加 VM；Recovery 卷我们不花力气去造。** 1.4 节给出判据脚本。

**Recovery 卷这一问有两个答案，取决于走哪条烘制路径**（1.5.2 节）：我们自己在 Linux/Windows 上造不出来（缺 chunklist、缺 `bless`、没有 APFS 写工具）；但走 `75` 的 `asr restore` 路径时它是**免费附带**的，代价是它的 build 跟运行器而不是跟我们的系统卷（L-023）。**两条路都不阻塞，因为没有 Recovery 卷的 macOS 能正常启动。** 独立的 p2 BaseSystem 分区与它不重复：p2 与容器隔离，容器被写坏时它完好（1.5.3 节末段）。

**任务 3：三卷布局。**

最终是**三个 GPT 分区、三个启动项、四个 APFS 卷**（3.0 节的对齐表）。分区是 ESP 512 MiB / BaseSystem 1600 MiB / APFS 剩余；启动项是 macOS / Recovery / Rescue；Alpine **不占独立分区**，它的三件套（`virt` flavour，合计 40 MB）放在 ESP 的 `/boot/` 下，根文件系统在 RAM 里。

**这一条修正了 `73` 第 5.1、5.2 节的选择**（去掉 ext4 分区），理由与数据在 3.3 节，关键新数据是 `virt` 的 modloop 只有 20 MB 而 `lts` 是 209 MB。

选择器里的呈现靠三样东西：macOS 项用 Preboot 里的 `.VolumeIcon.icns`，Recovery 项用卷根的 `.VolumeIcon.icns` 加 `.contentDetails`，Alpine 项用 `Misc/BlessOverride` 发现加 `.contentFlavour`。**2.5.4 节那个 `.contentVisibility` 不加就会多出第四项（shim 自己），而选中它会重入 shim。**

**任务 4：三次启动失败自动拉救援 + SSH 预配。**

机制是 `74` 第 4 节状态文件阶梯的扩展，不是另一套：加 `fails` 与 `rescues` 两个键（4.3 节），在 `efi_main` 里加一个分支（4.4.1 节的替换块）。计数规则的全表在 4.2 节，一句话是「shim 发现上一次的 `inflight` 没被清零就 `fails++`；`fails >= 3` 这一次直接拉 Alpine 并把 `fails` 清零；阶梯前进只在未确认态发生，三次失败拉救援在两种态都发生」。

macOS 侧**扩展 `74` 已有的那一个 daemon，不新增**（4.5 节给出完整替换版）。Alpine 侧的 SSH 预配是一个十一文件的 apkovl（4.6.2 节的清单与打包脚本），**加上一个容易漏掉的前置条件**：`openssh` 不在 Alpine 的 netboot initramfs 里，所以要在 ESP 上放一个本地 apk 仓库（4.6.3 节），否则网络一坏救援系统自己就没有入口。

**「macOS 活着但 SSH 不通」这个边界情形：让它触发切换。** 完整论证在 4.7 节，核心是三点：在本项目的定义下一台 SSH 不通的 macOS 产生零信息（所有观测通道都经 SSH，包括 `80` 第 2.3.5 节的 ARD/VNC）；切过去之后反而能拿到它为什么不通的证据；误判的代价是一次额外重启而不是一台机器，因为救援侧对 APFS 容器只读并且第一个动作就是把下次启动交还给 macOS。配套三条措施是 ESP 面包屑（让 E2 与 S2 事后可区分）、`FAILMAX` 可调、交还下次启动。

**「老生常谈」的那一组：ACPI / SSDT / kext。**

在 KVM 上确实接近零成本，但不要把这个结论推广到整个平台（5.1 节）。**必需的 SSDT 只有一个：`SSDT-EC`**，而且它的父设备路径在 QEMU 上与社区的桌面版不同，5.3.1 节给出针对 `\_SB.PCI0` 的 ASL 源码与三条验证方法。**`SSDT-PLUG` 明确不要加**，它与 `71` 第 5.3 节的 `DummyPowerManagement = true` 方向相反。其余十四个常见 SSDT 逐个判定为不需要（5.3 节的表）。

kext 最小集仍然是 `71` 定的三个（Lilu / VirtualSMC / AppleMCEReporterDisabler），三卷布局与 Alpine 的加入**一个都不增加**（5.4 节逐条确认）。Quirks 的增量只有三条值得注意：`RequestBootVarRouting` 保持 `true` 且在三项布局下更重要；`ReleaseUsbOwnership` 保持 `false` 且打开会害了 OpenCanopy 的键盘；`SyncRuntimePermissions` 保持 `true` 现在有了一条官方依据（它影响经 OpenCore 启动 Linux 内核）。
