# 75 在 GitHub Actions 运行器上预烘完整 macOS 磁盘镜像

文档版本：1.0
基线日期：2026-10-30
对应组件：无（基础设施分册）
上级文档：`docs/spec/00-OVERVIEW.md`
配套分册：`docs/spec/71-IMAGE-OPENCORE.md`、`docs/spec/73-DEPLOY-RESCUE.md`、`docs/spec/74-BOOT-CPU-DISPATCH.md`

## 0. 本文作用与写作约束

本文回答一个问题：**在 GitHub Actions 的 `macos-26-intel` 运行器上，不运行原生安装器，怎么烘出一块已经配好 SSH 与 VNC 的完整 macOS 系统盘，并让它被 `73-DEPLOY-RESCUE.md` 第 3、4 节的投放通道接受。**

职责边界：

- 本文不重复 `71` 第 6 节的 `config.plist`、不重复 `70` 第 5 节的 SIP 位域推导、不重复 `73` 第 3 节的 Vultr API 形状、不重复 `74` 第 3.3 节的 shim 源码。本文只做一件 `71` 没做的事：**`71` 假定"在 L1 的 KVM 里装一次系统"这一步存在，本文在没有 KVM 也没有可交互 Mac 的前提下替换掉那一步。**
- ESP 的内容归 `71` 第 8.2.1 节与 `74` 第 3.2 节，本文只负责**给它留出分区并把它拼进镜像**。
- Alpine rescue 分区的内容归 `73` 第 5.1 节，本文只负责**留出 1.5 GiB 并把它拼进镜像**。

写作约束同 `70`/`71`/`73`/`74`：

- 每条结论带 `KNOWN` / `INFERRED` / `BLOCKED` / `TESTED` 标签与来源 URL。凡"应该可以"一律 `INFERRED` 并给查清方法。
- **本文没有任何 `TESTED`。** 本文的 workflow 一次都没跑过。`91-RUNTIME-EVIDENCE.md` 第 0.1 节的 `TESTED(25G76)` 级别在本文里也没有，因为本文没有新的运行证据，只有对既有运行证据的引用。
- 命令与 plist 片段按可直接照抄编写。
- 外部网页内容均为转述，不作连续摘录。**内容已转述以符合许可限制。**

### 0.1 八条结论先行

1. **`startosinstall --volume` 这条路不存在了。** 从 macOS 11 起，在一个完整运行的 macOS 上执行安装器里的 `startosinstall`，`--usage` 里**没有** `--volume`（`KNOWN`，见第 2.1 节）。所以"它算不算走原生安装器"这个问题是空的：它不可用。退一步说，就算可用，它的收尾动作是重启本机进安装环境，而 CI job 一重启就结束。
2. **选定路径是克隆运行器自己。** `asr restore` 把运行器自身那套已装好、封印完好的 macOS 复制进一个挂载着的磁盘镜像。代价是得到的 build 是运行器的 **25G76**，不是项目目标的 **25G325**（第 2.3 节）。
3. **SSV 封印这一关不用过，因为选定路径不碰 System volume。** 全部预配（用户、SSH、VNC、Setup Assistant 标记）落在 **Data volume**，封印不破（第 5.1 节）。退路也有：`70` 第 5.2 节定下的 `csr-active-config = 0xFEF` 的 bit 11 正是 `CSR_ALLOW_UNAUTHENTICATED_ROOT`，即未封印的 system volume 本来就被允许启动（第 2.2 节）。
4. **不要把 18.4 GB 的素材搬上运行器。** 官方对 `macos-26-intel` 的存储口径是 14 GB，而 GitHub 自己的说法是"镜像至少保证 14 GB 空闲"（`KNOWN`，第 3.1 节）。18.4 GB 的 `InstallAssistant.pkg` 装不下，运行器自己从 Apple 拉完整安装器同样装不下。选定路径的素材就是运行器自身，下载量为零。
5. **产物运不出去是一个独立的硬约束。** artifact 存储配额按账户计：Free 500 MB / Pro 1 GB / Team 2 GB / Enterprise Cloud 50 GB（`KNOWN`，第 3.4 节）。一块 20 到 30 GB 的镜像**不能走 artifact**，只能从 job 里直接流式 PUT 到我们自己的对象存储。
6. **镜像虚拟容量的现实值是 28 到 32 GB，不是 `73` 第 4.6.3 节写的 16 到 24 GB。** 一个完整安装的 System volume 自身就 11 到 15 GB，加 Preboot、Recovery 与 APFS 余量压不到 24 GB 以下（第 4.1 节）。这是对 `73` 的一条修订建议。
7. **跳过 Setup Assistant 与预开 SSH/VNC 的文件清单是确定的**，共 9 项，全在 Data volume 上（第 5.8 节）。其中 VNC 这一项在 macOS 26.6.x 上有一个已被第三方报告的回归（第 5.5 节），必须实测。
8. **整条路的成立与否压在三个数字上**：运行器 APFS 容器的真实空闲空间（`P-001`）、`asr` 能不能把克隆落到一块从未装过 macOS 的空盘上（`P-002`）、运行器的 system volume 封印是否完好（`P-003`）。这三条没关之前，本文的 workflow 预期**跑不绿**。

---

## 1. 前提复述

本节只复述，不重新论证。每一条都给出处，后面各节直接引用编号。

### 1.1 项目所有者给的四条硬约束

1. 没有可交互的 Mac，本地 Debian 不一定支持嵌套虚拟化（`73` 第 7 节已把这件事做成判定矩阵）。唯一的 macOS 执行环境是 `macos-26-intel` 运行器。
2. 不运行原生安装器：不走"启动安装介质 → GUI 或交互式 `startosinstall` → 装完做快照"。
3. 产物必须被重装器接受，即 `73` 第 3.1.2 节的 `POST /v2/snapshots/create-from-url`（未压缩 raw）或第 4.3 节的 iPXE + 流式写盘。
4. SSH 与 VNC 在镜像里就是开的。

### 1.2 运行器的事实（全部 `TESTED(25G76)`，来源 `91` 第 1 节）

| 项 | 值 |
|---|---|
| OS | macOS 26.6.1 / 25G76 / x86_64 |
| kernel | Darwin 25.6.0，xnu-12377.161.13~4，`RELEASE_X86_64` |
| CPU | Intel Core i7-8700B，CPUID model `0x9E` |
| **SIP** | **disabled**（`csrutil status`） |
| GPU | `Apple Paravirtual device`，即运行器本身是虚机 guest |
| Xcode | 26.0.1 / 26.1.1 / 26.4.1 / 26.6 多版本在位 |
| brew | 有 bottle 的包装得上；**从源码编 LLVM 会让 job 超时**（`91` 第 5.7.1 节坑 1） |

补充两条来自 GitHub 官方的规格（`KNOWN`，转述自 <https://docs.github.com/en/actions/reference/runners/github-hosted-runners>）：`macos-26-intel` 是 4 CPU / 14 GB RAM / 14 GB 存储 / Intel 架构；同一张表里 arm64 macOS 一行下面另有一句说明，因 Apple 的 Virtualization 框架限制，arm64 macOS 运行器不支持嵌套虚拟化。

**`macos-15-intel` 与 `macos-26-intel` 是 Actions 上最后两个 x86_64 镜像，落日是 2027 年 8 月**（`KNOWN`，转述自 <https://github.com/actions/runner-images/issues/13045>）。这与 `70` 第 2.2 节的时效性提示一致：本文的 workflow 必须把产物与清单归档到仓库外，不能假定 CI 一直在。

### 1.3 手头素材（`KNOWN`，来源 `71` 第 1 节）

| 件 | 字节 | 位置 |
|---|---:|---|
| `SharedSupport.dmg` | 18,366,480,610 | 开发机（Windows） |
| `InstallAssistant.pkg` | 18,384,411,815 | 开发机（Windows） |
| `x86_64BaseSystem.dmg`（已还原） | 1,464,270,504 | 开发机（Windows） |

`x86_64BaseSystem.dmg` 的 SHA-256 是 `642E6148288527C51639D1B08C7F0B5A8CB4A68AEC2AC6DA3C78CF1723C5119A`。

**这三件都在开发机上，不在运行器上，而且本文选定的路径一件都不用。** 它们在第 2.4 节的备选路径里才派上用场。

### 1.4 投放通道与分区布局（来源 `73` 第 3.1.2、4.6、5.2 节，`74` 第 3.2 节）

- 几十 GB 的系统盘只有 `POST /v2/snapshots/create-from-url` 一条路，格式是**解压后的 raw**，`uefi: true`。
- 快照只能恢复到**等于或大于源盘**的盘，所以镜像虚拟容量就是能选的最小机型的盘容量下限。
- 分区布局：p1 ESP（FAT32，256 MiB，label `OPENCORE`）+ p2 rescue（ext4，1.5 GiB，label `RESCUE`）+ p3 Apple APFS（余下全部）。**APFS 必须是最后一个分区**，因为首启要靠 `diskutil apfs resizeContainer ... 0` 向盘尾扩展。
- ESP 里除 `71` 第 6 节的 OpenCore 布局外，还要容纳 `74` 第 3.2 节的 `/EFI/CPUDISP/`（5 份候选 plist + `STATE.TXT` + `LOG.TXT`），合计 400 KB 以内。

### 1.5 SIP 的固化位置（来源 `70` 第 5.2、5.3 节）

`csr-active-config = 0xFEF`，固化在 **OpenCore 的 `config.plist` 的 `NVRAM` 节**，不在镜像里。所以**镜像本身不需要为 SIP 做任何事**。这一点对本文很重要：它意味着烘制期不需要在目标卷上留任何 SIP 相关状态。

`0xFEF` 的位分解里与本文直接相关的是最高那一位：

```text
0xFEF = 0x800 | 0x400 | 0x200 | 0x100 | 0x080 | 0x040 | 0x020 | 0x008 | 0x004 | 0x002 | 0x001
        ^^^^^
        bit 11 = CSR_ALLOW_UNAUTHENTICATED_ROOT
```

`KNOWN` 对于位值与名称（`70` 第 5.1 节引的 `csr.h` 定义，<https://khronokernel.com/macos/2022/12/09/SIP.html>）；该位的运行期含义见第 2.2 节。

---

## 2. 不跑原生安装器：五条路的裁决

这是本文的核心。先给结论表，再逐条展开。

### 2.0 结论表

| # | 路 | 在运行器上能跑 | 需要下载 | 产物 build | 封印 | 裁决 |
|---|---|---|---|---|---|---|
| **R1** | `asr restore` 克隆运行器自身的 system volume | **能**（待 `P-002`/`P-003`） | 0 | **25G76** | Apple 原封，不破 | **选定** |
| R2 | 解包 `payloadv2` 直写自建 APFS 卷 | 能（纯文件操作） | 18.4 GB 素材，**装不下** | 25G325 | 自建，未封印，依赖 bit 11 | 备选，为 build 保真 |
| R3 | `startosinstall --volume` | **不能**，选项不存在 | 18.4 GB | 25G325 | Apple 封印 | **不可用** |
| R4 | 嵌套虚机里跑安装器 | 不能 | 18.4 GB | 25G325 | Apple 封印 | 不可用，且违反约束 2 |
| R5 | `73` 第 4.1 节的 D0：云上人工装一次 | 不在运行器上 | 1.5 GB ISO | 25G325 | Apple 封印 | 最后兜底，1 次人工 |

**权限这条也先一次性说清。** SIP 在运行器上已经关闭（第 1.2 节），而 GitHub 托管运行器的 `runner` 账号有免密 `sudo`。所以：

| 需要的权限 | 谁给 | 还缺什么 |
|---|---|---|
| `hdiutil attach` / `diskutil` / `asr` / `bless` 要 root | 免密 `sudo` | 无 |
| 改 `/Library`、`/private/var/db`、`dslocal`（在**目标卷**上） | root + 目标卷是普通可写卷，不是封印卷 | 无 |
| 读源 system volume 的全部内容 | **可能要完全磁盘访问（FDA）**，而运行器没有 GUI 可授权 | `P-004`。SIP 已关意味着 `TCC.db` 可写，可在烘制期自己插一条 |
| 写源 system volume | **不需要，而且不要做**。R1 全程只读源 | 无 |
| 改固件 NVRAM（`bless --setBoot`、`nvram`） | 不需要，**而且禁止**：那是运行器自己的固件 | 无 |

**架构一致性这条先一次性说清：运行器是 x86_64，目标也是 x86_64，所以 R1 到 R4 都不涉及跨架构。** 这不是想当然：`asr` 的克隆**明确不跨平台**，不能把 Intel Mac 的 macOS 克隆去 Apple Silicon 启动，反向亦然（`KNOWN`，转述自 <https://discussions.apple.com/docs/DOC-250005828>）。我们两端都是 Intel，这条限制刚好不咬人。R2 的 `payloadv2` 是跨架构共用资产，`71` 第 3.1 节已经确立"`Info.plist` 存在不代表有 x86_64 代码，KC 的 fileset 条目才是证据"这条纪律，R2 必须沿用。

### 2.1 R3：`startosinstall --volume` 不可用，而且这个结论有两层

#### 第一层：选项在 macOS 11+ 的 full-OS 变体里消失了

`KNOWN`。两个独立来源拼出一条时间线：

- **Sierra / High Sierra era**：同一个 `startosinstall` 二进制，`--usage` 的输出**取决于当前引导的是哪个 OS 环境**。从完整 macOS 里跑，用法行是 `startosinstall --applicationpath <...>`，参数表里没有 `--volume`；从安装器 / 恢复环境里跑，用法行变成 `startosinstall --applicationpath <...> --volume <target volume path>`，参数表末尾多出 `--volume, path to the target volume`（转述自 <https://gist.github.com/gregneagle/d2a889ba31a8771364db03e2b689bef2>，该 gist 的标题就是"按引导 OS 环境对比 startosinstall 的可用选项"）。
- **Catalina era**：社区问答里确实有人在完整 macOS 上用 `--agreetolicense --nointeraction --volume /Volumes/External Macintosh HD` 装到外置盘（转述自 <https://apple.stackexchange.com/questions/413772/use-startosinstall-to-install-macos-catalina-on-external-drive>）。
- **Big Sur era**：同一条 `startosinstall --usage` 的完整输出被逐字记录下来，参数只有 `--license`、`--agreetolicense`、`--rebootdelay`、`--pidtosignal`、`--installpackage`、`--eraseinstall`、`--newvolumename`、`--preservecontainer`、`--forcequitapps`、`--usage`、`--user`、`--passprompt`、`--stdinpass`。**`--volume` 不在里面**（转述自 <https://www.jamf.com/blog/streamlining-your-macos-upgrade-process/>）。

即：**`--volume` 从 Big Sur 起只在恢复/安装环境里出现，在完整 macOS 上已经没有了。** 运行器是完整 macOS，不能引导恢复环境（没有控制台、没有重启后继续执行的能力），所以这条路在运行器上不存在。

**查清方法**（`P-009`，workflow 第一个 job 已经包含）：把 `InstallAssistant.pkg` 装到 `/Applications` 后执行

```bash
'/Applications/Install macOS Tahoe.app/Contents/Resources/startosinstall' --usage 2>&1 | sed -n '1,60p'
```

看参数表里有没有 `--volume`。这是一条两分钟能做完的实测，它把本节从 `KNOWN`（来自三个外部来源的时间线）升级为对 25G325 这份二进制的直接证据。

#### 第二层：即使它存在，也不符合 CI 的形状

退一步假设 25G325 的二进制里还留着 `--volume`。它仍然不能用，两个理由：

1. **`startosinstall` 的收尾是重启。** Big Sur 的参数表里 `--rebootdelay` 的描述是"推迟准备阶段结束时的那次重启"，`--pidtosignal` 的描述是"准备阶段完成时向指定 PID 发 SIGUSR1，用来绕过 rebootdelay"（来源同上）。即它的工作模型是"准备 → 重启 → 在安装环境里完成"。GitHub 托管运行器一重启，job 就结束了。
2. **它要检查本机硬件资格。** 安装器拿 `PlatformSupport.plist` 的 `SupportedBoardIds` 对本机 board-id 做门禁（`71` 第 4.1 节已取出该文件全文，8 个 x86 board-id）。运行器的 board-id 未实测（`P-007`）。有理由猜它是 `VMM-x86_64`：那是 Apple 给虚机用的 board-id，而且它**在 25G325 的受支持清单里**（`71` 第 4.1 节，`KNOWN`）。`INFERRED`，查清方法：

```bash
ioreg -l -p IODeviceTree -n / -r -d 1 | grep -i board-id
nvram 4D1EDE05-38C7-4A6A-9CC6-4BCCA8B38C14:HW_BID 2>/dev/null || true
```

#### 对"算不算符合约束"的明确裁决

所有者的原话是「不要走它原生的安装器，我们给它把镜像预配好」。按意图拆，这句话禁止的是**启动安装介质并在安装器环境里走流程**，不是禁止调用 Apple 的任何二进制。所以：

> **如果 `startosinstall --volume` 可用，它是符合约束的**：它跑在宿主 OS 的命令行里，`--nointeraction --agreetolicense` 是非交互的，不启动安装介质，产物是一个已经装好的卷而不是一张安装盘。按这个判断它本该是首选。
>
> **它不可用，所以这个判断不产生任何后果。** 本节花笔墨写这一条，是为了让后面的人不要再回头来问"要不要试试 startosinstall"。要试的话，试的是 `P-009` 那一条命令，而不是整条路径。

### 2.2 SSV 封印：三件事必须分清

社区把三件不同的事混成一句"SSV 过不去"。它们各自的开关不同，对本文的影响也不同。

| 件 | 是什么 | 开关 | 对本文 |
|---|---|---|---|
| **封印本身（seal）** | system volume 的内容哈希树，封在一个 `com.apple.os.update-*` 快照里 | 没有开关。改了 system volume 的内容，封印就破 | **R1 不改 system volume，所以不涉及** |
| **authenticated-root** | 启动时是否校验封印 | `csrutil authenticated-root disable`，落到 NVRAM 的 `csr-active-config` bit 11 | `0xFEF` 已含该位（第 1.5 节），**R2 靠它成立** |
| **blessed snapshot** | 固件/引导器到底引导哪个快照 | `bless --folder <vol>/System/Library/CoreServices --bootefi [--create-snapshot]` | R1 要用它把克隆卷做成可引导；R2 要用它引导自建的未封印快照 |

三条支撑证据：

1. **`csrutil authenticated-root` 是一个与 SIP 并列的独立状态查询。** 一篇 2026 年的操作说明把三条查询并排列出：`csrutil status`、`csrutil authenticated-root status`、`csrutil allow-research-guests status`，并指出 Authenticated Root 是其中真正起作用的那一条（转述自 <https://osxhub.com/disable-sip-mac/>）。
2. **社区的既有做法确证"关掉 authenticated-root + 自建快照 + bless"这条链在 Intel 上成立。** 非官方 Mac 上给系统打补丁的通行步骤就是 `csrutil authenticated-root disable` → 重启 → 跑 OpenCore Legacy Patcher（转述自 <https://github.com/Nishit-Chauhan/Ventura-Hackintosh-Haswell-EFI>），而 OCLP 的 root patch 正是"挂读写 system volume、改文件、建新快照并 bless"。
3. **`0xFEF` 的 bit 11 就是 `CSR_ALLOW_UNAUTHENTICATED_ROOT`**（第 1.5 节）。所以 `70` 第 5.2 节当初为了别的目的选的那个值，顺带已经把 R2 的前置条件满足了。

**本文对"SSV 封印过不过得去"的回答是两句**：

> **选定路径不需要过这一关**，因为预配全部落在 Data volume（第 5.1 节），封印完好无损。
>
> **备选路径需要过，而且过得去**：`csr-active-config = 0xFEF` 已经放开 authenticated-root。但"放开了校验"不等于"自建的卷一定能起来"，剩下的难点不是封印，是 **Preboot 卷与 cryptex 的布局**（第 2.4 节）。把失败原因记在正确的地方，比笼统地说"SSV 过不去"有用。

### 2.3 R1：`asr restore` 克隆运行器自身（选定）

#### 2.3.1 为什么是它

运行器上已经有一套东西，是前面四条路都在费力制造的：**一个完整安装、封印完好、Apple 自己装的 macOS 26 x86_64。** 它就在 `/`。下载量为零，不需要安装器，不需要重建 Preboot，不需要动封印。

`asr` 是唯一能做这件事的工具。`KNOWN`，Apple 支持社区的那篇克隆指引开篇就点明：Big Sur 之后因为 SSV，克隆变难了，**能成功复制 Signed System Volume 的工具只有一个，就是 Apple Software Restore**（转述自 <https://discussions.apple.com/docs/DOC-250005828>）。

#### 2.3.2 `asr` 对 APFS 的确切语义（`KNOWN`，来源 `asr(8)` 手册 <https://keith.github.io/xcode-man-pages/asr.8.html>）

手册 `RESTORING WITH APFS FILESYSTEMS` 一节给出三条本文直接依赖的规则：

1. **单个 APFS 卷不能直接恢复**，因为它的设备节点不接受普通进程的 I/O；`asr` 恢复的是整个 APFS container，或者恢复"一个有效系统"。
2. **"有效系统"的定义**：一个卷要可引导，必须装着一套正确安装的 macOS，并且所在 container 里还要有 **Preboot 卷与 Recovery 卷各一个**，且各自的 APFS volume role 正确；Preboot 与 Recovery 里存着与每个 system volume 绑定的信息。
3. **目标是分区且带 `--erase` 时**，`asr` 会抹掉该分区、新建 container 与新卷，再做卷恢复；**如果被恢复的卷是一个有效系统，Preboot 与 Recovery 的相关内容会一并从源复制到目标，必要时在目标上创建这两个卷。**

第 3 条是整条路径的技术基础：**我们不需要自己造 Preboot 和 Recovery，`asr` 会造。**

#### 2.3.3 可照抄的命令序列

分四步。`<IMG>` 是宿主上的目标镜像文件，`<N>` 是它 attach 后的 disk 号。

```bash
# ---- 1. 造一个稀疏的 raw 文件并以裸盘形式 attach ----
#    APFS 上这样建出来的文件是稀疏的：只占实际写入的块。
#    CRawDiskImage 让 hdiutil 把任意扩展名的文件当作裸磁盘镜像处理。
IMG=/Users/runner/work/bake/macos.raw
SIZE_GB=32
mkdir -p "$(dirname "$IMG")"
dd if=/dev/zero of="$IMG" bs=1 count=0 seek=$((SIZE_GB * 1024 * 1024 * 1024))
DEV=$(hdiutil attach -imagekey diskimage-class=CRawDiskImage -nomount "$IMG" | head -1 | awk '{print $1}')
echo "attached raw image at $DEV"
```

`hdiutil attach -imagekey diskimage-class=CRawDiskImage -nomount <file>` 是把裸镜像当块设备挂起来的标准形式，扩展名不是 `.dmg`/`.img` 时这个 imagekey 是必须的（`KNOWN`，转述自 <https://apple.stackexchange.com/questions/375170/how-do-you-create-an-apfs-volume-inside-an-ordinary-file> 与 <https://apple.stackexchange.com/questions/463693/mounting-a-bit-by-bit-copy-of-a-partition-in-macos>）。

```bash
# ---- 2. 找到源 system volume 与它的封印快照 ----
#    根在运行中的系统上是以【快照】形式挂在 / 的，所以 / 的 DeviceIdentifier
#    形如 diskNsMsK，最后一段 sK 是快照。要的是它的宿主卷 diskNsM。
ROOTDEV=$(diskutil info -plist / | plutil -extract DeviceIdentifier raw -o - -)
echo "root device: $ROOTDEV"
SRC_VOL=$(echo "$ROOTDEV" | sed -E 's/^(disk[0-9]+s[0-9]+)s[0-9]+$/\1/')
echo "system volume: $SRC_VOL"
diskutil info "$SRC_VOL" | sed -n '1,40p'

# 封印快照的 UUID。只应该有一个 com.apple.os.update-* 快照；不是一个就停。
diskutil apfs listsnapshots "$SRC_VOL"
SNAP_UUID=$(diskutil apfs listsnapshots -plist "$SRC_VOL" \
  | plutil -extract Snapshots.0.SnapshotUUID raw -o - -)
echo "sealed snapshot: $SNAP_UUID"
```

**不要用 `diskutil info -plist /` 去找"宿主卷"的键，没有这样一个键。** 上面的 `sed` 是按设备名的结构去掉快照后缀，然后用 `diskutil info` 回头核对拿到的确实是一个 APFS Volume 而不是快照。这一点 workflow 的 `gate 2` 步骤实现方式相同。

取封印快照 UUID 的做法（`diskutil mount <sysvol>` 后 `diskutil apfs listsnapshots <sysvol>`，输出里 UUID 在 `Name:` 上面一行）直接来自那篇克隆指引，并明确说明：Big Sur 之后 SSV 是 system volume 上的一个封印快照，**克隆要能启动，这个快照必须原样复制过去，而 `asr` 做得到，它只需要知道快照的名字或 UUID**（`KNOWN`，转述自 <https://discussions.apple.com/docs/DOC-250005828>）。

```bash
# ---- 3. 克隆 ----
#    Intel 上不要加 --no-personalization（那是 Apple Silicon 专用）。
sudo asr restore \
  --source "/dev/$SRC_VOL" \
  --target "$DEV" \
  --toSnapshot "$SNAP_UUID" \
  --erase --noprompt --verbose
```

`--toSnapshot` 接快照名或 UUID；Intel 上要**排除** `--no-personalization`；目标给整块盘加 `--erase` 时 `asr` 自建 container 与卷，这三条都来自上面两个来源。`--noprompt` 用来免掉那句 `Erase contents of ...? [ny]:` 的交互确认（`INFERRED`，手册里有 `--noprompt`，但它对 APFS erase 确认是否生效未实测，记为 `P-002` 的一部分；若无效，改用 `printf 'y\n' | sudo asr restore ...`）。

```bash
# ---- 4. 补 Data volume，并把它和克隆出来的 system volume 组成一个 volume group ----
CNT=$(diskutil list -plist "$DEV" | plutil -extract AllDisksAndPartitions.0.APFSVolumes raw -o - - >/dev/null 2>&1; \
      diskutil list "$DEV" | awk '/APFS Container Scheme/{print $NF}')
TGT_SYS=$(diskutil list "$DEV" | awk '/APFS Volume Macintosh HD /{print $NF}')

diskutil apfs addVolume "$CNT" APFS "Macintosh HD - Data" \
  -role D -groupWith "$TGT_SYS" -nomount
```

`diskutil apfs addVolume` 的 `-groupWith` 的语义是：新卷成为指定卷所属 APFS Volume Group 的成员，若指定卷还没有 group，则在适当时候自动创建（`KNOWN`，`diskutil(8)` 手册 <https://keith.github.io/xcode-man-pages/diskutil.8.html>）。`-role D` 的取值来自同一手册的 `APFS VOLUME ROLES` 一节。

**第 4 步是否必要，取决于 `asr` 有没有连带把配对的 Data volume 造出来。** 手册只说 Preboot 与 Recovery，没提 volume group；那篇克隆指引在失败清理那一段提到要用 Disk Utility 的"Erase Volume Group"去掉失败的克隆，这暗示 `asr` 在目标上建的是一个 **group**。两条证据不足以定论。记为 `P-005`，查清方法是克隆完立刻跑

```bash
diskutil apfs list "$DEV"
diskutil apfs listVolumeGroups
```

看目标 container 里有几个卷、role 分别是什么、group 成员是谁。若已有配对 Data volume，第 4 步跳过。

#### 2.3.4 空 Data volume 的骨架问题

新建的 Data volume 是空的，而 macOS 的 firmlink 机制要求 Data volume 上存在一棵目录骨架（`/private/var`、`/Users`、`/Library`、`/Applications`、`/usr/local` 等），否则 firmlink 解析不到东西。

`INFERRED`：system volume 上有 `/System/Library/Templates/Data/`，装机时由安装器用它来播种 Data volume 的骨架。查清方法：

```bash
ls -la /System/Library/Templates/Data
```

若存在，烘制期照抄：

```bash
sudo diskutil mount -mountPoint /Volumes/TGTDATA "$TGT_DATA"
sudo ditto /System/Library/Templates/Data /Volumes/TGTDATA
```

**若 `P-005` 的答案是"`asr` 已经建好了配对 Data volume"，本节整段不需要**，骨架由 `asr` 从源 Data volume 带过来。这是一条二选一，不是两条都做。

#### 2.3.5 把克隆卷做成可引导

```bash
sudo bless --folder "/Volumes/TGTSYS/System/Library/CoreServices" --bootefi --verbose
```

**不要加 `--setBoot`。** `--setBoot` 会改固件的启动偏好，而我们在改的是运行器自己的固件，不是目标机的。目标机上的引导由 OpenCore 接管（`71` 第 6 节），OpenCore 自己扫描 APFS container 里的引导候选，不依赖固件偏好。

`INFERRED` 对于"`bless --bootefi` 是这一步的充分条件"。来源是 `bless(8)` 手册（<https://keith.github.io/xcode-man-pages/bless.8.html>）与第 2.2 节那条 OCLP 做法。对立证据必须一起记下：那篇克隆指引明确警告 **ASR 适合"克隆"而不是"做镜像"，不要用 ASR 把一套 macOS 克隆到一台完全没装过 macOS 的空机上，在 Intel 上"大概不会成"，在 Apple Silicon 上"肯定不成"**（转述自 <https://discussions.apple.com/docs/DOC-250005828>）。

**我们的目标恰恰就是一块从未装过 macOS 的空盘，所以这条警告正中要害。** 它是 `P-002`，也是本文最该先查的一条。三条可以分辨的解释，查法不同：

| 解释 | 若成立，表现 | 怎么分辨 |
|---|---|---|
| 限制只对 Apple Silicon 实质成立（LocalPolicy 必须由一套已存在的 macOS 来签） | Intel 上克隆完 + `bless` 就能起 | 在 L1 的 QEMU 里直接启动产物（`71` 第 8.2.4 节的 `boot-l1.sh`） |
| Intel 上缺的是固件侧的 bless 记录 | 固件列不出启动项，但 OpenCore 能列出 | 看 OpenCore picker 有没有候选，DEBUG 构建的日志会打出扫描结果（`71` 第 9.2 节） |
| Intel 上缺的是 Preboot 里的某项内容 | OpenCore 列出候选但 `boot.efi` 起不来 | 比对源容器与目标容器的 `Preboot/<UUID>/` 目录树 |

**三条解释里只有第一条成立时 R1 才真正成立。** 另两条成立时 R1 需要补步骤，补什么由比对结果决定。

#### 2.3.6 R1 的代价：build 不是 25G325

克隆出来的是运行器的 **25G76**，而项目目标是 **25G325**。后果要写明：

1. **证据标签。** `00-OVERVIEW.md` 第 7 节补充规则 2、3 要求标注架构与样本来源。镜像是 25G76，而 `90-EVIDENCE-INDEX.md` 第 2 节的全部 x86_64 样本是 25G325。在这块镜像上测出来的东西只能标 `TESTED(25G76)`，**不能标 `TESTED`**，和 `91` 第 0.1 节的口径一致。
2. **两条收敛办法**，择一：
   - **首启后自升级**：镜像起来、SSH 通了之后 `softwareupdate -i -a -R`，或 `softwareupdate --fetch-full-installer --full-installer-version 26.7.2`。前者走增量更新，不需要 18 GB 落盘。这把"拿到目标 build"从烘制期挪到部署期，`INFERRED`，前置条件是目标机能连 Apple 的更新服务器。
   - **把分析基线改成 25G76**：代价是 `90` 第 2 节的样本全部要重取，不划算。
3. **不要假装这是小事。** `91` 第 0.1 节已经把 25G76 与 25G325 的差距量化为"同一 `12377.161` 系、补丁号差 2"，对 ABI 与类布局是强证据；但对**内核 collection 的内容**（`71` 第 3 节的 204 + 172 条 fileset）没有做过比对。记为 `P-016`。

### 2.4 R2：解包 `payloadv2` 直写自建 APFS 卷（备选）

这是最"不走安装器"的一条，也是唯一能在烘制期就拿到 25G325 的一条。

能做的部分（`KNOWN`，`71` 第 2.1 节已实际执行过）：`SharedSupport.dmg` → GPT → HFS+ → zip → `payloadv2/payload.NNN` → pbzx → XZ → Apple Archive，然后按逻辑路径抽任意文件。仓库里 `analysis/binaries/macos26-25G325-x86_64/tools/` 的九个脚本就是干这个的，纯 Python，不需要 macOS。

做不动的部分，按风险从高到低：

| 障碍 | 为什么难 | 标签 |
|---|---|---|
| **cryptex** | 25G325 的资产带三个 cryptex（`cryptex-app`、`cryptex-system-x86_64`、`cryptex-system-arm64e`，见 `71` 第 1.3 节的 `CryptexSizeInfo`）。macOS 13 之后系统的一部分以 cryptex 形式交付，装在 `Preboot/<UUID>/cryptex1/` 下，由引导链挂载。它们的安装布局没有公开规格 | `BLOCKED`。缺的是 cryptex 在 Preboot 下的目录结构与 manifest 格式。取得方式：在运行器上读 `/System/Volumes/Preboot/<UUID>/` 的实际布局，这是现成可做的 |
| **Preboot 卷内容** | 每个 system volume 在 Preboot 里有一份以其 volume UUID 命名的目录，含 `System/Library/CoreServices/boot.efi`、`.disk_label`、`SystemVersion.plist`、以及 cryptex | `BLOCKED`，同上，可由运行器实测取得 |
| **封印** | 自建卷没有封印。靠 `0xFEF` 的 bit 11 放开校验（第 2.2 节），再用 `bless --create-snapshot` 造一个可引导快照 | `INFERRED`，机制有社区先例（OCLP），但"从零造"没有先例 |
| **素材上不去** | 18.4 GB 装不进运行器（第 3.1 节） | `KNOWN`。所以 R2 **不在运行器上做**，要在 Linux 构建机上做，而 Linux 上没有 `diskutil`/`bless`/APFS 写支持 |

**最后一行是 R2 的真正杀手，不是封印。** R2 需要一台能写 APFS 的 macOS，而唯一的 macOS 又装不下素材。两个绕法：

- **把素材流式喂进去**：只抽需要的 payload 条目，不落地完整 18.4 GB。`71` 第 1.4 节确证 `SharedSupport.dmg` 是未压缩 UDIF、可随机访问，所以可以用 HTTP Range 请求从我们自己的对象存储上按需取块。总传输量仍是 15 GB 级（`InstallationSize = 15,227,412,107`），但**峰值磁盘占用等于产物本身**，不需要额外 18.4 GB。`INFERRED`，没实现过。
- **把 Preboot/cryptex 的布局从运行器上抄过来**：这是把 R2 的两条 `BLOCKED` 变成 `KNOWN` 的办法，而且便宜。本文的 workflow 的第一个 job 已经包含这次取证（第 6 节的 `probe` job），**不管最终走 R1 还是 R2 都该做**。

**R2 的定位：不是现在就做，而是现在就把它的两条 `BLOCKED` 关掉。** 关掉之后它才是一条真备选。

### 2.5 R4 与 R5

**R4（嵌套虚机里跑安装器）：不可用。** 两条理由各自独立：

1. 它违反约束 2。在虚机里启动 BaseSystem 走安装流程，就是"走原生安装器"。
2. 能力上也不成立。运行器自己是虚机 guest（`91` 第 1 节，GPU 是 `AppleParavirtGPU`），GitHub 对 arm64 macOS 运行器明确说明不支持嵌套虚拟化（第 1.2 节）。Intel 侧没有对应声明，所以这是一条可查项（`P-xxx` 不单列，并入 `P-001` 的同一次探测）：

```bash
sysctl -n kern.hv_support 2>/dev/null || echo "kern.hv_support absent"
```

`kern.hv_support = 0` 或该 sysctl 不存在，就定论了。

**R5（`73` 第 4.1 节的 D0）：保留为最后兜底。** 它是全套方案里唯一无法消除的人工环节，约 1 小时，只做一次，之后回到 `73` 第 3.1.3 节的 `POST /v2/snapshots` 全自动回路。本文不改 `73` 对它的描述。

### 2.6 官方工具在 x86 上的角色

| 工具 | 在本文里的角色 | 标签 |
|---|---|---|
| `hdiutil attach -imagekey diskimage-class=CRawDiskImage` | 把稀疏 raw 文件当块设备挂起来。整条路径的容器 | `KNOWN`（第 2.3.3 节的两个来源） |
| `diskutil apfs addVolume / changeVolumeRole / list / listVolumeGroups` | 建 Data volume、设 role、组 group、验结果 | `KNOWN`（`diskutil(8)`） |
| `diskutil apfs resizeContainer <phys> 0` | 首启扩容。`0` 的语义是吃掉到下一个分区或分区表末尾之间的全部空间 | `KNOWN`（`73` 第 4.6.2 节已确立，来源 `diskutil(8)`） |
| `asr restore --toSnapshot ... --erase` | 唯一能复制 SSV 的工具 | `KNOWN`（`asr(8)` + Apple 克隆指引） |
| `bless --folder ... --bootefi` | 把目标卷做成可引导。**不要 `--setBoot`** | `INFERRED`（`bless(8)`，充分性未实测，`P-002`） |
| `bless --create-snapshot` / `--last-sealed-snapshot` | 只在 R2 需要：为未封印的 system volume 造一个可引导快照 / 回滚到上一个封印快照 | `INFERRED`（`bless(8)`） |
| `bputil` | **x86 上无角色。** 它管的是 Apple Silicon 的 LocalPolicy 与 owner | `KNOWN`（工具用途） |
| `kmutil configure-boot` | 只在需要给某个卷指定非默认 boot kernel collection 时用（`-c <kc> -v <volume>`）。E0 不需要 | `INFERRED`（`kmutil(8)` <https://keith.github.io/xcode-man-pages/kmutil.8.html>，`70` 第 4 节已引过该手册） |
| `createinstallmedia` | **本文完全不用。** `71` 第 2.3 节已确立它需要 macOS 且无替代实现 | `KNOWN` |

一条前瞻性提示（`INFERRED`，来源是一篇二手博客，可信度低，仅作备忘）：有说法称 `hdiutil` 在 macOS 27 被标记为弃用，替代界面是 `diskutil image`（转述自 <https://sesamedisk.com/hdiutil-deprecated-macos-how-to-use/>）。本文的 workflow 固定跑在 macOS 26 上，暂不受影响；但若将来迁到更新的运行器，第 2.3.3 节第 1 步要重写。

---

## 3. 素材与产物的进出

### 3.1 运行器的磁盘空间：官方数字、真实数字、以及为什么要自己量

**官方数字：14 GB。** `KNOWN`，`macos-26-intel` 与 `macos-15-intel` 同一行，4 CPU / 14 GB RAM / 14 GB 存储 / Intel（转述自 <https://docs.github.com/en/actions/reference/runners/github-hosted-runners>）。

**这 14 GB 是"保证的空闲空间"下限，不是卷的总容量。** `KNOWN`，GitHub 在一条关于磁盘不足的 issue 里直接说明：不保证每个项目都有足够磁盘，只保证镜像里至少有 14 GB 空闲（转述自 <https://github.com/actions/runner-images/issues/13528>）。

**一条旁证说明真实容量远大于 14 GB**：`91` 第 1 节记录运行器上同时在位 Xcode 26.0.1 / 26.1.1 / 26.4.1 / 26.6 四套。四套 Xcode 加 simulator runtime 不可能装进一个 14 GB 的卷。所以卷是大的，空闲是小的，而**被 Xcode 占住的那几十 GB 是可以删掉换成空闲的**（它们和我们的输出文件在同一个 APFS container 里，删除即释放）。`INFERRED`。

**所以必须自己量，而且要量四个数，不是一个。** 这是 `P-001`，workflow 的第一个诊断步骤：

```bash
# 四个数，缺一不可
df -h /                                   # 根卷视角的可用空间（会被 purgeable 误导）
diskutil apfs list                        # container 的 Size / Capacity In Use / Free
diskutil info -plist / | plutil -p -       # 根卷的 APFSContainerFree / APFSContainerSize
du -sh /Applications/Xcode*.app 2>/dev/null # 删掉能换回多少
```

**判定线**：第 4.1 节算出的实占估算是 16 到 26 GB，加上 APFS 自身的工作余量，**container 的可用空间至少要有 30 GB**。低于这个数，R1 在运行器上不成立，走第 7 节的替代。

### 3.2 选定路径的素材上传量是零

R1 的源就是运行器自己的 `/`。**不需要上传任何素材。** 这是选 R1 的第二个理由，和第 2.3.1 节的理由同等重要。

下面三小节只在走 R2，或者 R1 被 `P-002` 否掉之后才相关。

### 3.3 若必须把 25G325 的素材弄上去：三条路与体积账

| 路 | 做法 | 体积 | 裁决 |
|---|---|---|---|
| **A. 运行器自己从 Apple 拉** | `softwareupdate --fetch-full-installer --full-installer-version 26.7.2` | 完整安装器 app，15 到 18 GB 落在 `/Applications` | **装不下**（第 3.1 节）。而且它按**版本号**而不是 build 号取，钉不住 `25G325` |
| B. 我们这边上传 | 分片 + 校验，见下 | 18.4 GB，或按需 Range 取 15 GB | 可行但贵，且仍要落地 |
| C. 第三方工具按 build 取 | `mist` / `gibMacOS` 一类 | 同 A | 体积同 A，**装不下**；但它们能按 build 过滤，这一点优于 A |

**A 的两条确切语义，先钉死再谈体积**（`KNOWN`，`softwareupdate` 的 `help` 输出被逐字记录，转述自 <https://www.jamf.com/blog/streamlining-your-macos-upgrade-process/>）：

- `--list-full-installers`：列出可用的 macOS 完整安装器。
- `--fetch-full-installer`：下载最新的推荐安装器。
- `--full-installer-version`：指定要装的 macOS **版本**，示例给的是 `10.15` 这种版本号。

**所以它钉的是版本不是 build。** 对我们是一个实质问题：`26.7.2` 这个版本号目前只对应 `25G325`，但 Apple 可以用同一版本号发不同 build。`INFERRED`，`--list-full-installers` 的输出里是否带 build 列未在本轮确证（有二手来源提到该列表给出版本与 build，未核实）。记为 `P-010`，查清方法是在运行器上直接跑：

```bash
softwareupdate --list-full-installers 2>&1 | sed -n '1,40p'
```

一条实用提示（`KNOWN`，转述自 <https://community.jamf.com/general-discussions-2/softwareupdate-fetch-full-installer-25597>）：`--full-installer-version` 的参数写错时，这个参数会被**静默忽略**，二进制退回去下载最新可下载的版本。即"钉死 build"这件事如果写错，**表现不是报错，是悄悄给你另一个版本**。所以任何用到它的脚本都必须在下载后核对 `sw_vers` 风格的产物版本，不能只看退出码。

**B 的分片与校验方案**（若非得从我们这边传）：沿用 `73` 第 4.5.3 节已经定下的格式，不另造一套。

```bash
# 构建期（开发机或 Linux 构建机）：按 64 MiB 切块算 SHA-256
# 这与 73 §4.5.3 的 scripts/mk-chunk-manifest.sh 是同一个清单格式
python - "$SRC" "$SRC.chunks.tsv" <<'PY'
import hashlib, sys
src, out = sys.argv[1], sys.argv[2]
CH = 64 * 1024 * 1024
total = 0
with open(src, 'rb') as f, open(out, 'w', newline='\n') as m:
    i = 0
    while True:
        b = f.read(CH)
        if not b:
            break
        m.write("%d\t%d\t%d\t%s\n" % (i, total, len(b), hashlib.sha256(b).hexdigest()))
        total += len(b); i += 1
    m.write("#total_bytes\t%d\n" % total)
    m.write("#chunk_bytes\t%d\n" % CH)
PY
```

```bash
# 运行器侧：按 Range 取块并逐块校验，坏块只重取那一块
# 不要用 curl -C -：断点续传在对象存储上行为不一致，分块显式取更可诊断
while IFS=$'\t' read -r idx off len want; do
  case "$idx" in \#*) continue ;; esac
  curl -fsSL -H "Range: bytes=${off}-$((off + len - 1))" "$URL" -o "/tmp/c.$idx"
  got=$(shasum -a 256 "/tmp/c.$idx" | awk '{print $1}')
  [ "$got" = "$want" ] || { echo "::error::chunk $idx mismatch want=$want got=$got"; exit 1; }
  cat "/tmp/c.$idx" >> "$DST"; rm -f "/tmp/c.$idx"
done < chunks.tsv
```

### 3.4 产物怎么运出去：artifact 不够，只有对象存储

**这是一条独立的硬约束，和磁盘空间同等重要。**

`KNOWN`（转述自 <https://docs.github.com/en/actions/reference/limits>）：

| 项 | 值 |
|---|---|
| Artifact 存储配额 | GitHub Free 500 MB，Pro 1 GB，Free for organizations 500 MB，Team 2 GB，Enterprise Cloud 50 GB |
| 单个 job 执行时长上限 | **6 小时** |
| 单个 job 的 artifact 数量上限 | 500 |
| workflow 文件大小上限 | 500 KB |
| macOS 并发 job 上限 | Free/Pro/Team 5 个 |

**一块 20 到 30 GB 的镜像不能走 artifact，分片也不行**，因为配额是按总存储算的，不是按单件。结论只有一个：**从 job 里直接把镜像流式推到我们自己的对象存储。**

可照抄的形态（预签名 PUT，URL 放在仓库 secret 里）：

```bash
# 流式：读 attach 后的裸设备，压缩，直接 PUT。中间不落第二份文件。
# 读的是整块虚拟容量，但零块经 zstd 之后几乎不占带宽。
#   注意：zstd 不是运行器预装的，brew 有 bottle，装它不会触发源码构建（91 §5.7.1 坑 1）。
sudo dd if="$DEV" bs=1m status=none \
  | zstd -T0 -3 -c \
  | curl -fsS -X PUT --upload-file - \
      -H 'Content-Type: application/zstd' \
      "$IMAGE_PUT_URL"
```

**为什么读裸设备而不是传那个稀疏文件**：稀疏文件在 APFS 上只占实际块，但 `curl --upload-file` 读它时读到的是完整虚拟长度；而读裸设备同样是完整虚拟长度。两者带宽相同，但读裸设备免掉了"文件 attach 状态与文件内容是否一致"这一类问题。代价是必须先 `hdiutil detach` 再读，或者接受读到的是 attach 期间的一致快照（`INFERRED`，未实测；稳妥做法是先 detach 再直接读文件）。

**Linux 侧收到之后**（这一步在 `73` 的投放流水线里，不在本文的 workflow 里）：

```bash
# 解压回未压缩 raw。73 §3.1.2 确证 create-from-url 要的是解压后的 raw
zstd -d -o macos-apfs.raw macos-apfs.raw.zst
qemu-img info macos-apfs.raw        # 核对虚拟容量与格式
```

**备用通道，排序**：

1. 预签名 PUT 到对象存储（上面那条）。**首选。**
2. `rclone`/`mc` 推到 S3 兼容端点。比 1 多一个依赖，但支持分片与重试。
3. 挂一个远端文件系统当输出盘（`mount_smbfs` 或 `rclone mount`），让 `hdiutil` 直接在上面建镜像。**这条同时解决第 3.1 节的磁盘问题**，是 `P-001` 判定为"空间不够"时的主要替代（第 7 节）。代价：20 GB 级的随机写跑在网络文件系统上，6 小时的 job 上限会变成真约束。`INFERRED`，吞吐未实测。
4. 只上传一份"清单 + 日志"的小 artifact，镜像本体放弃本次运行。**这是失败路径，不是交付路径**，但 workflow 必须永远至少做到这一条，否则一次失败就什么都看不到。

---

## 4. 产物形态与尺寸

### 4.1 实占估算

逐项，单位 GB（十进制）。

| 卷 / 分区 | 估算 | 依据 | 标签 |
|---|---:|---|---|
| ESP（OpenCore + `74` 的 CPUDISP） | 0.27 | `73` 第 5.2 节定的 256 MiB；`74` 第 3.2 节算出内容 < 400 KB | `KNOWN` |
| rescue（Alpine sys 模式） | 1.6 | `73` 第 5.2 节定的 1.5 GiB | `KNOWN` |
| APFS：System volume | 11 到 15 | `71` 第 1.3 节的 `InstallationSize = 15,227,412,107`；Apple 克隆指引的实例里 system volume 是 10.3 GB（那是别的版本/架构） | `INFERRED` |
| APFS：Preboot | 2 到 6 | 同一实例里 Preboot 是 5.4 GB，因为它装着 cryptex | `INFERRED` |
| APFS：Recovery | 约 1 | 同一实例里 923.1 MB | `INFERRED` |
| APFS：Data（预配后，几乎空） | 2 到 4 | 骨架 + 一个用户 + 日志 | `INFERRED` |
| APFS：VM（swap） | 0 | 同一实例里 20.5 KB。首启后才长大 | `INFERRED` |
| **实占合计** | **18 到 28** | | |

**虚拟容量的推荐值：32 GB，下限 28 GB。**

推导：`73` 第 4.6.2 节定下的规则是"目标容量 = 实占 × 1.3，且不小于 16 GB"，并给出理由"一个塞满到 99% 的 APFS 容器开机即出问题"。按实占 18 到 28 GB 算，1.3 倍是 23 到 36 GB。取 32 GB 能覆盖估算区间的大部分，且仍落在"盘 ≥ 40 GB 的常规机型"上。

**这与 `73` 第 4.6.3 节写的"发布用瘦镜像 16 到 24 GB"冲突。** 冲突的原因是 `73` 写那一节时还没有"System volume 自身就 11 到 15 GB"这个数。**本文的修订建议**（本文不改 `73`）：

> `73` 第 4.6.3 节的"发布用瘦镜像 16 到 24 GB"应改为 **28 到 32 GB**，并把"落在最便宜的、盘 ≥ 25 GB 的常规机型上"改为"盘 ≥ 40 GB"。真实实占由 `P-001` 的同一次测量给出，测到之后这个数应当钉死而不是继续估。

### 4.2 分区布局

完全沿用 `73` 第 5.2 节与 `74` 第 3.2 节，只把尺寸填成本文的值：

```text
macos-golden.raw        32 GB 虚拟容量，未压缩 raw，GPT
├─ p1  EFI System Partition     C12A7328-F81F-11D2-BA4B-00A0C93EC93B
│      FAT32，256 MiB，label OPENCORE
│      内容按 71 §8.2.1 + 74 §3.2 组装（本文不重复）
├─ p2  Linux filesystem         0FC63DAF-8483-4772-8E79-3D69D8477DE4
│      ext4，1.5 GiB，label RESCUE
│      内容按 73 §5.1 组装（本文不重复）
└─ p3  Apple APFS               7C3457EF-0000-11AA-AA11-00306543ECAC
       余下全部（约 30 GB），本文第 2.3 节产出的 APFS container
       首启由 firstboot-expand LaunchDaemon 扩满（73 §4.6.2）
```

### 4.3 为什么 macOS 侧只产 APFS container，GPT 在 Linux 侧拼

**运行器上不要造 GPT。** 三个理由：

1. `diskutil partitionDisk` 在 GPT 上会自动生成一个它自己选定大小的 EFI 分区（约 200 MiB），而我们要的是 256 MiB 且 label 为 `OPENCORE`。改不了就得事后改，不如不做。
2. ESP 的内容在 Windows 上准备、在 Linux 上封装（`71` 第 2.1、2.2 节），运行器上既没有 OpenCore 的文件树也没有 `mkfs.vfat`。
3. rescue 分区是 ext4，macOS 造不出来。

**所以职责切成三段**，和 `71` 第 2 节的划分一致：

| 段 | 机器 | 产物 |
|---|---|---|
| 1 | Windows 开发机 | EFI 文件树、5 份候选 `config.plist`、清单 |
| 2 | **`macos-26-intel` 运行器（本文）** | `macos-apfs.raw.zst`：**一个裸 APFS container 镜像**，无分区表 |
| 3 | Linux 构建机 | `sgdisk` 建 GPT，`mkfs.vfat` + `mcopy` 写 ESP，装 Alpine 到 p2，`dd` 把段 2 的 container 写进 p3，`truncate` + `sgdisk -e` 收尾 |

段 3 可照抄的核心几行（放在 `73` 的 `scripts/` 下，不在本文的 workflow 里）：

```bash
#!/usr/bin/env bash
# scripts/assemble-golden.sh <efi.img> <rescue.img> <macos-apfs.raw> <out.raw>
set -euo pipefail
EFI="${1:?}"; RES="${2:?}"; APFS="${3:?}"; OUT="${4:?}"

ESP_MIB=256
RES_MIB=1536
APFS_BYTES=$(stat -c%s "$APFS")
# 1 MiB 对齐的起始扇区 + 盘尾留 1 MiB 给 GPT 备份表
TOTAL=$(( (1 + ESP_MIB + RES_MIB) * 1024 * 1024 + APFS_BYTES + 1024 * 1024 ))

truncate -s "$TOTAL" "$OUT"
sgdisk --zap-all "$OUT"
sgdisk -n 1:1MiB:+${ESP_MIB}MiB -t 1:EF00 -c 1:OPENCORE "$OUT"
sgdisk -n 2:0:+${RES_MIB}MiB   -t 2:8300 -c 2:RESCUE   "$OUT"
sgdisk -n 3:0:0 -t 3:7C3457EF-0000-11AA-AA11-00306543ECAC -c 3:macOS "$OUT"
sgdisk -p "$OUT"

off1=$(( 1 * 1024 * 1024 ))
off2=$(( (1 + ESP_MIB) * 1024 * 1024 ))
off3=$(( (1 + ESP_MIB + RES_MIB) * 1024 * 1024 ))
dd if="$EFI"  of="$OUT" bs=1M seek=$((off1 / 1048576)) conv=notrunc status=none
dd if="$RES"  of="$OUT" bs=1M seek=$((off2 / 1048576)) conv=notrunc status=none
dd if="$APFS" of="$OUT" bs=1M seek=$((off3 / 1048576)) conv=notrunc status=none

# 瘦镜像必然需要：把 GPT 备份表挪到真实盘尾（73 §4.5.1 加固 4）
sgdisk -e "$OUT"
sgdisk -v "$OUT"
```

**`sgdisk -e` 这一步不能省。** `73` 第 4.5.1 节把它列为加固 4，第 4.6.2 节又强调"GPT 修复要在 Linux 侧做，不要指望 macOS 做"。

### 4.4 首启自扩容

命令与 LaunchDaemon 完全沿用 `73` 第 4.6.2 节，本文不重抄。本节只补它在 macOS 26 上的三条前置条件：

| 前置 | 内容 | 标签 |
|---|---|---|
| APFS container 必须是 GPT 里的**最后一个分区** | 否则 `resizeContainer ... 0` 只能扩到下一个分区之前 | `KNOWN`（`diskutil(8)` 对 `0` 的语义；`73` 第 5.2 节已据此把 rescue 放在 p2） |
| GPT 备份表必须在真实盘尾 | 由 Linux 侧 `sgdisk -e` 保证（第 4.3 节）。若 Vultr 的导入逻辑动过 GPT（`73` 的 D-006），这一条会在首启时暴露 | `KNOWN` |
| 根卷的 physical store 必须能解析出来 | `73` 第 4.6.2 节的脚本把 `diskutil info -plist /` 的输出喂给 `plutil -extract APFSPhysicalStores.0.APFSPhysicalStore raw`。**在"根是封印快照"的情况下这个键路径是否仍然成立未实测** | `INFERRED`，记为 `P-011` |

`P-011` 的查清方法（在运行器上就能做，因为运行器的根也是封印快照）：

```bash
diskutil info -plist / | plutil -p - | grep -A3 APFSPhysicalStores
```

**烘制期必须安装的 LaunchDaemon 一共三个**，都落在 Data volume 的 `/Library/LaunchDaemons/`：

| Label | 来源 | 作用 |
|---|---|---|
| `net.metal2vu.firstboot-expand` | `73` 第 4.6.2 节 | 把 APFS container 扩满整盘 |
| `net.metal2vu.cpudisp-confirm` | `74` 第 4.6 节 | sshd 在听 22 之后，向 ESP 回写"当前候选已确认" |
| `net.metal2vu.firstboot-probe` | `71` 第 10.1 节 | 首启探针，产出证据目录 |

三个都是 `RunAtLoad`，都带自己的一次性标记文件，顺序无关。**`net.metal2vu.cpudisp-confirm` 必须在，否则 `74` 第 4 节的候选阶梯会把每一次成功的启动都当成失败并往下掉一档。**

---

## 5. SSH、VNC 与 Setup Assistant 的离线预配

### 5.1 最重要的一条：全部预配都落在 Data volume

这一条决定了第 2.2 节的"封印不用过"。

macOS 11 之后根文件系统由两个卷拼成，若干目录通过 firmlink 从 system volume 映到 Data volume（`KNOWN`，firmlink 清单在 `/usr/share/firmlinks`，转述自 <https://superuser.com/questions/1490834/how-to-find-firmlinks>）。本文要写的每一个路径，按卷归属分类：

| 路径 | 卷 | 标签 |
|---|---|---|
| `/private/var/db/...` | **Data**（`/private/var` 是 firmlink） | `KNOWN` |
| `/Users/...` | **Data** | `KNOWN` |
| `/Library/...`（含 `/Library/Preferences`、`/Library/LaunchDaemons`） | **Data** | `KNOWN` |
| `/usr/local/...` | **Data** | `KNOWN` |
| `/Applications/...` | **Data**（与 `/System/Applications` 合并显示） | `KNOWN` |
| `/private/etc/...`（即 `/etc`） | **未确证** | `INFERRED`，记为 `P-006` |

`P-006` 的查清方法是一条命令，比较 `st_dev`：

```bash
# 同一个 device 号 = 同一个卷。拿 /System/Library 做 system volume 的基准，
# /private/var 做 Data volume 的基准。
stat -f '%d %N' /System/Library /private/var /private/etc /private/etc/ssh
```

**本文的预配方案刻意不依赖 `P-006` 的答案**：第 5.4 节不改 `sshd_config`，只放 `authorized_keys`（在 `/Users/...`，确定在 Data 上）。只有在必须改 `sshd_config` 时才需要先关掉 `P-006`。

### 5.2 跳过 Setup Assistant

**这一条没有的话，镜像起来就是一个卡在设置助理的屏幕。** 分两层：标记文件，以及"已看过各个面板"的偏好键。

#### 第一层：标记文件

```bash
VOL=/Volumes/TGTDATA          # 挂载着的目标 Data volume

sudo mkdir -p "$VOL/private/var/db"
sudo touch "$VOL/private/var/db/.AppleSetupDone"
sudo touch "$VOL/private/var/db/.AppleDiagnosticsSetupDone"
sudo chown root:wheel "$VOL/private/var/db/.AppleSetupDone" \
                      "$VOL/private/var/db/.AppleDiagnosticsSetupDone"
sudo chmod 644 "$VOL/private/var/db/.AppleSetupDone" \
               "$VOL/private/var/db/.AppleDiagnosticsSetupDone"
```

`.AppleSetupDone` 的语义：它是一个空文件，Setup Assistant 跑完之后被创建；全新开箱的 Mac 上没有，刚干净装完的 macOS 上也没有（`KNOWN`，转述自 <https://discussions.apple.com/thread/250996371>）。

**在一个挂载着的目标卷上 `touch` 它是既有做法**，不是本文发明的：绕过 MDM 的那类脚本正是对着 Recovery 里挂载的 Data 卷执行 `touch /Volumes/Data/private/var/db/.AppleSetupDone`（`KNOWN`，转述自 <https://github.com/assafdori/bypass-mdm/blob/main/bypass-mdm.sh>）。

**注意：`.AppleSetupDone` 只在系统里已经存在一个用户账号时才有意义。** 没有账号又跳过设置助理，得到的是一个谁也登不进去的登录窗。所以第 5.3 节是本节的前置，不是可选项。

#### 第二层：各面板的"已看过"标记

即使 `.AppleSetupDone` 在位，首次登录时还会弹 iCloud、Siri、隐私、外观一类面板。压掉它们的办法是往 **user template** 写偏好键，这样每个新建用户都继承（`KNOWN`，机制与键名来自 <https://gist.github.com/tperfitt/7bcf0e282dd3772bacaa10a09a23481a>，该脚本还给出了键名的自证方法：对 `Setup Assistant` 二进制跑 `strings | grep '^DidSee'`）。

macOS 11 及以后的键集（上面那份脚本按 Darwin 主版本累加，这里展开成 macOS 11+ 的全集）：

```text
DidSeeApplePaySetup   DidSeeAvatarSetup   DidSeeCloudSetup
DidSeeiCloudLoginForStorageServices        DidSeePrivacy
DidSeeSiriSetup       DidSeeSyncSetup     DidSeeSyncSetup2
DidSeeTouchIDSetup    DidSeeAppearanceSetup                DidSeeTrueTone
DidSeeActivationLock  DidSeeScreenTime    DidSeeAccessibility   DidSeeAppStore
```

另有三个字符串型键（同一来源，自证方法是 `strings | grep '^LastSeen'`）：`LastSeenBuddyBuildVersion` 填 build 号，`LastSeenCloudProductVersion` / `LastSeeniCloudStorageServicesProductVersion` / `LastSeenSyncProductVersion` / `LastSeenDiagnosticsProductVersion` / `LastSeenSiriProductVersion` 填版本号。

可照抄：

```bash
VOL=/Volumes/TGTDATA
BUILD=$(sw_vers -buildVersion)      # 烘制期宿主的 build，就是镜像的 build（R1 下成立）
OSVER=$(sw_vers -productVersion)

# user template 在 system volume 上，但我们要写的是【目标用户的实际偏好文件】，
# 在 Data volume 上，所以不碰封印。
for HOME_DIR in "$VOL/Users/"*; do
  [ -d "$HOME_DIR" ] || continue
  P="$HOME_DIR/Library/Preferences/com.apple.SetupAssistant"
  sudo mkdir -p "$(dirname "$P")"
  for K in DidSeeApplePaySetup DidSeeAvatarSetup DidSeeCloudSetup \
           DidSeeiCloudLoginForStorageServices DidSeePrivacy DidSeeSiriSetup \
           DidSeeSyncSetup DidSeeSyncSetup2 DidSeeTouchIDSetup \
           DidSeeAppearanceSetup DidSeeTrueTone DidSeeActivationLock \
           DidSeeScreenTime DidSeeAccessibility DidSeeAppStore; do
    sudo defaults write "$P" "$K" -bool true
  done
  sudo defaults write "$P" LastSeenBuddyBuildVersion -string "$BUILD"
  for K in LastSeenCloudProductVersion LastSeeniCloudStorageServicesProductVersion \
           LastSeenSyncProductVersion LastSeenDiagnosticsProductVersion \
           LastSeenSiriProductVersion; do
    sudo defaults write "$P" "$K" -string "$OSVER"
  done
  OWNER=$(basename "$HOME_DIR")
  sudo chown -R "${OWNER}:staff" "$HOME_DIR/Library/Preferences"
done
```

**`defaults write` 对着一个绝对路径（不带 `.plist` 后缀）写文件是支持的用法**，上面那份脚本就是这么用的（写到 `${folder}/Library/Preferences/com.apple.SetupAssistant`）。

**一条必须记下的风险**：`defaults` 在宿主上运行时会走 `cfprefsd`，对**目标卷上的文件**写入可能被缓存或被改写路径。更稳的做法是用 `plutil` 或直接写 XML。`INFERRED`，记为 `P-013` 的一部分。保险写法：

```bash
sudo /usr/libexec/PlistBuddy -c "Add :DidSeeCloudSetup bool true" "$P.plist" 2>/dev/null \
  || sudo /usr/libexec/PlistBuddy -c "Set :DidSeeCloudSetup true" "$P.plist"
```

### 5.3 预建一个管理员账号

**做法：对着目标卷上的 dslocal 节点直接操作，用 `dscl -f`。**

`dscl -f <node-path> localhost -create ...` 是对一个**离线的 Directory Service 节点**做增删改的标准形式。既有做法对着 Recovery 里挂载的 Data 卷执行，节点路径是 `<Data>/private/var/db/dslocal/nodes/Default`（`KNOWN`，转述自 <https://github.com/assafdori/bypass-mdm/blob/main/bypass-mdm.sh>）。

可照抄（把 `73`/`80` 的 harness 公钥与一个随机密码填进去）：

```bash
VOL=/Volumes/TGTDATA
NODE="$VOL/private/var/db/dslocal/nodes/Default"
U=harness
FULLNAME="Harness"
UID_N=501
PW="$(openssl rand -base64 24)"       # 立刻落盘到 creds 文件，见下

sudo dscl -f "$NODE" localhost -create "/Local/Default/Users/$U"
sudo dscl -f "$NODE" localhost -create "/Local/Default/Users/$U" UserShell      /bin/zsh
sudo dscl -f "$NODE" localhost -create "/Local/Default/Users/$U" RealName       "$FULLNAME"
sudo dscl -f "$NODE" localhost -create "/Local/Default/Users/$U" UniqueID       "$UID_N"
sudo dscl -f "$NODE" localhost -create "/Local/Default/Users/$U" PrimaryGroupID 20
sudo dscl -f "$NODE" localhost -create "/Local/Default/Users/$U" NFSHomeDirectory "/Users/$U"
sudo dscl -f "$NODE" localhost -passwd "/Local/Default/Users/$U" "$PW"
sudo dscl -f "$NODE" localhost -append "/Local/Default/Groups/admin" GroupMembership "$U"

# 家目录。权限必须对，否则 sshd 会拒绝 pubkey 认证
sudo mkdir -p "$VOL/Users/$U/.ssh"
sudo chown -R "${UID_N}:20" "$VOL/Users/$U"
sudo chmod 700 "$VOL/Users/$U" "$VOL/Users/$U/.ssh"
```

四条说明：

1. **`-passwd` 会生成正确的 `ShadowHashData`**（`SALTED-SHA512-PBKDF2`），不需要我们自己算。这是用 `dscl -f` 而不是手写 `users/<name>.plist` 的全部理由。手写那条路要自己造 PBKDF2 的 entropy/salt/iterations 三元组，可行但没必要（既有实现可参考 `macadmins/pycreateuserpkg`）。
2. **`UniqueID` 不要用 501 以外的值，除非你确认没冲突。** R1 克隆来的 Data volume（若 `P-005` 的答案是"`asr` 带 Data 过来"）里本来就有运行器的 `runner` 账号，很可能占着 501。先列一遍：`sudo dscl -f "$NODE" localhost -list /Local/Default/Users UniqueID`。
3. **把密码立刻落盘并限权**，和 `73` 第 4.2.1 节对 `default_password` 的处理同一纪律：

```bash
umask 077
printf '{"user":"%s","password":"%s"}\n' "$U" "$PW" > "$RUNNER_TEMP/creds.json"
```

   这份文件**不能进 artifact**（artifact 对仓库可读）。它要走第 3.4 节的同一条预签名上传通道，或者干脆不要密码：只配公钥，`-passwd` 设一个一次性随机值并丢弃。**推荐后者。**
4. **R1 下有一条更省事的路**：如果 `asr` 把运行器自己的 Data volume 一起克隆过来了，那么 `.AppleSetupDone` 已经在位、`runner` 账号已经存在且有免密 sudo，第 5.2、5.3 两节**只需要改密码和加公钥**。`INFERRED`，取决于 `P-005`。

### 5.4 SSH

`systemsetup -setremotelogin on` 需要一个运行中的系统，离线用不了。离线的等价物是**写 launchd 的 override**。

#### 机制

`/System/Library/LaunchDaemons/ssh.plist` 里的 `Disabled` 键被一个 override 文件压过去；`launchctl -w` 不再改原 plist，而是把状态记在别处（`KNOWN`，转述自 <https://serverfault.com/questions/218402/how-does-one-check-whether-the-os-x-disabled-flag-for-launchd-services-is-set> 与 <https://keith.github.io/xcode-man-pages/launchd.plist.5.html>）。

override 的位置与格式（`KNOWN`，转述自 <https://apple.stackexchange.com/questions/207854/restoring-yosemite-server-after-unloading-launch-daemons> 与 <https://developer.apple.com/forums/thread/8489>）：

- 系统域（daemon）：`/private/var/db/com.apple.xpc.launchd/disabled.plist`
- 用户域（agent）：同目录下 `disabled.<UID>.plist`，例如 `disabled.0.plist`
- 格式：一个 plist 字典，**key 是服务的 Label，value 是布尔**；`true` = 禁用，`false` = 启用。`disabled.plist` 压过各个 LaunchDaemon plist 里的设置，而那些 plist 本身不会被改。

#### 可照抄

```bash
VOL=/Volumes/TGTDATA
D="$VOL/private/var/db/com.apple.xpc.launchd/disabled.plist"
sudo mkdir -p "$(dirname "$D")"
[ -f "$D" ] || sudo /usr/libexec/PlistBuddy -c "Save" "$D" 2>/dev/null \
            || printf '%s\n' '<?xml version="1.0" encoding="UTF-8"?>' \
               '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">' \
               '<plist version="1.0"><dict/></plist>' | sudo tee "$D" >/dev/null

# sshd。Label 取自 /System/Library/LaunchDaemons/ssh.plist
for L in com.openssh.sshd; do
  sudo /usr/libexec/PlistBuddy -c "Delete :$L"            "$D" 2>/dev/null || true
  sudo /usr/libexec/PlistBuddy -c "Add :$L bool false"    "$D"
done
sudo plutil -convert binary1 "$D"
sudo chown root:wheel "$D"; sudo chmod 644 "$D"
sudo plutil -p "$D"
```

**`com.openssh.sshd` 这个 Label 必须用烘制期的实际值核对，不要照抄。** `INFERRED`，查清方法：

```bash
/usr/libexec/PlistBuddy -c 'Print :Label' /System/Library/LaunchDaemons/ssh.plist
/usr/libexec/PlistBuddy -c 'Print :Disabled' /System/Library/LaunchDaemons/ssh.plist 2>/dev/null
```

#### `authorized_keys`

```bash
VOL=/Volumes/TGTDATA; U=harness; UID_N=501
sudo tee "$VOL/Users/$U/.ssh/authorized_keys" >/dev/null <<'EOF'
ssh-ed25519 AAAA...harness-public-key... harness@metal2vu
EOF
sudo chown -R "${UID_N}:20" "$VOL/Users/$U/.ssh"
sudo chmod 700 "$VOL/Users/$U/.ssh"
sudo chmod 600 "$VOL/Users/$U/.ssh/authorized_keys"
```

**权限必须正好是 700 / 600，而且家目录不能是 group-writable**，否则 sshd 的 `StrictModes` 会静默拒绝 pubkey 认证。这是最常见的"镜像起来了但登不进去"的原因。

#### `sshd_config` 的改法，以及为什么默认不改

不改。macOS 自带的 `sshd_config` 默认已经 `PubkeyAuthentication yes`，而我们不需要密码登录、不需要改端口。**少改一个在 system volume 上可能存在的文件，就少一条破封印的风险**（见 `P-006`）。

真要改时的正确形态是 drop-in 而不是改主文件：

```bash
# 仅在 P-006 确认 /private/etc 在 Data volume 上之后才做
sudo mkdir -p "$VOL/private/etc/ssh/sshd_config.d"
sudo tee "$VOL/private/etc/ssh/sshd_config.d/10-harness.conf" >/dev/null <<'EOF'
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin no
ClientAliveInterval 30
ClientAliveCountMax 6
EOF
```

#### TCC / 完全磁盘访问会不会挡住 sshd

**会，但挡的不是连接，是 sshd 会话里能读到的东西。** 分三层说清：

1. **连接本身不受 TCC 约束。** sshd 是 launchd 启动的系统 daemon，建立连接、认证、起 shell 都不碰 TCC 保护的路径。`INFERRED`，没有反例，但也没有一手证据。
2. **SSH 会话里的进程默认没有完全磁盘访问。** 后果是通过 SSH 跑的命令读不到 TCC 保护的位置（用户的 Desktop/Documents/Downloads、Mail、`/Library/Application Support/com.apple.TCC`）。这对 `71` 第 10.1 节的首启探针**有实际影响**：探针里读 panic 报告、读 `log show` 都可能受限。
3. **研发期有一个简单结论：SIP 已关（`70` 第 5.2 节的 `0xFEF`），所以 TCC 的数据库本身是可写的**，可以在烘制期直接给 shell 授权。`INFERRED`，`TCC.db` 的 schema 跨版本变化，必须先读 schema 再插：

```bash
# P-004。先看 schema，不要照抄别处的 INSERT 语句
sqlite3 "$VOL/Library/Application Support/com.apple.TCC/TCC.db" '.schema access'
```

**本文的立场**：不把 TCC 授权写进必做清单。它属于"首启探针拿不全证据时才需要处理"的一类，记为 `P-004`，并在 `71` 第 10.1 节的探针里加一条"记录当前是否有 FDA"的检查即可。

### 5.5 VNC / Screen Sharing

`80` 第 2.3.5 节已给 `kickstart` 的命令行与 `VNCOnlyLocalConnections`，那是**运行时**做法。离线要写四处。

#### 四处要写什么

| # | 路径 | 内容 | 标签 |
|---|---|---|---|
| 1 | `<Data>/private/etc/RemoteManagement.launchd` | 单行文本 `enabled` | `KNOWN`（转述自 <https://discussions.apple.com/thread/1312397>：该文件只需含 `enabled` 一词，用来让 VNC server 的 daemon 在登录时启动）。**路径受 `P-006` 影响** |
| 2 | `<Data>/Library/Preferences/com.apple.RemoteManagement.plist` | `ARD_AllLocalUsers`、`ARD_AllLocalUsersPrivs`、`VNCLegacyConnectionsEnabled`、`VNCOnlyLocalConnections` | `INFERRED`（键名来自 `kickstart` 的行为描述：`-configure -allowAccessFor -allUsers -privs -all` 会设 `ARD_AllLocalUsers` 与全用户权限掩码，转述自 <https://loobins.io/binaries/kickstart/>；`VNCOnlyLocalConnections` 的写法来自 <https://gist.github.com/remrearas/a3f300635b02f2587a134882a51f7114>） |
| 3 | `<Data>/Library/Preferences/com.apple.VNCSettings.txt` | 8 字节口令与固定 XOR 密钥逐字节异或后的大写十六进制，**不带换行** | `KNOWN`（XOR 密钥 `1734516E8BA8C5E2FF1C39567390ADCA`，口令先截断到 8 字节，转述自 <https://gist.github.com/852485>；该文件是"用 VNC 控制 GUI"的那个口令，转述自 <https://discussions.apple.com/thread/1312397>） |
| 4 | `<Data>/private/var/db/com.apple.xpc.launchd/disabled.plist` | `com.apple.screensharing` → `false` | `KNOWN`（override 机制同第 5.4 节；把 `com.apple.screensharing` 的 `Disabled` 置 false 是既有做法，转述自 <https://gist.github.com/remrearas/a3f300635b02f2587a134882a51f7114>） |

#### 可照抄

```bash
VOL=/Volumes/TGTDATA
VNC_PW='changeme'          # 最多 8 个字节会被用到

# 1. RemoteManagement.launchd
printf 'enabled' | sudo tee "$VOL/private/etc/RemoteManagement.launchd" >/dev/null
sudo chown root:wheel "$VOL/private/etc/RemoteManagement.launchd"
sudo chmod 644        "$VOL/private/etc/RemoteManagement.launchd"

# 2. com.apple.RemoteManagement.plist
RM="$VOL/Library/Preferences/com.apple.RemoteManagement.plist"
sudo mkdir -p "$(dirname "$RM")"
sudo tee "$RM" >/dev/null <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>ARD_AllLocalUsers</key>             <true/>
  <key>ARD_AllLocalUsersPrivs</key>        <integer>-1073741569</integer>
  <key>VNCLegacyConnectionsEnabled</key>   <true/>
  <key>VNCOnlyLocalConnections</key>       <true/>
  <key>ScreenSharingReqPermEnabled</key>   <false/>
  <key>LoadRemoteManagementMenuExtra</key> <false/>
</dict>
</plist>
EOF
sudo chown root:wheel "$RM"; sudo chmod 644 "$RM"
sudo plutil -lint "$RM"

# 3. VNC 口令。XOR 密钥是固定的，口令截断到 8 字节
python3 - "$VNC_PW" <<'PY' | sudo tee "$VOL/Library/Preferences/com.apple.VNCSettings.txt" >/dev/null
import sys
key = bytes.fromhex('1734516E8BA8C5E2FF1C39567390ADCA')
pw  = sys.argv[1].encode()[:8].ljust(8, b'\x00')
sys.stdout.write(''.join('%02X' % (p ^ k) for p, k in zip(pw, key)))
PY
sudo chown root:wheel "$VOL/Library/Preferences/com.apple.VNCSettings.txt"
sudo chmod 600        "$VOL/Library/Preferences/com.apple.VNCSettings.txt"

# 4. 启用 screensharing 的 launchd job
D="$VOL/private/var/db/com.apple.xpc.launchd/disabled.plist"
sudo /usr/libexec/PlistBuddy -c "Delete :com.apple.screensharing"         "$D" 2>/dev/null || true
sudo /usr/libexec/PlistBuddy -c "Add :com.apple.screensharing bool false" "$D"
sudo plutil -p "$D"
```

两条说明：

- **`ARD_AllLocalUsersPrivs` 的那个负数是权限掩码，不是随便填的。** `INFERRED`：`-1073741569` 对应"全部控制权限"的一种常见取值，但本轮没有一手来源确证 macOS 26 上的确切位义。查清方法：在运行器上先跑一次 `kickstart -configure -allowAccessFor -allUsers -privs -all`，然后 `plutil -p /Library/Preferences/com.apple.RemoteManagement.plist` 把它写出来的值抄下来。**这是最便宜、最可靠的做法：让 Apple 的工具自己生成一份，我们照抄。** 第 6 节的 `probe` job 已包含这一步。
- **`VNCOnlyLocalConnections = true` 是刻意的。** 它把 VNC 限制在 localhost，外部只能经 SSH 隧道进来（`80` 第 2.3.5 节与上面那份 gist 的做法一致）。在一台公网实例上开裸 VNC 是不可接受的。

#### macOS 26.6.x 的一个回归，必须实测

`INFERRED`，但来源的时间与版本都对得上，优先级高：有用户报告在 **macOS 26.6.1** 上 VNC 坏掉，而把 Remote Management 关掉、改成显式启用 Screen Sharing 并勾上"允许 VNC 查看者用口令控制屏幕"之后，传统 VNC server 行为恢复（转述自 <https://discussions.apple.com/thread/256337577>）。

**运行器正是 26.6.1。** 所以这件事可以在运行器上直接验证，不需要等镜像起来。两条后果：

1. 上面的四处写入里，"Remote Management"与"Screen Sharing"是**两套可能互斥的机制**。如果那条报告成立，正确的离线配置是**只配 Screen Sharing（第 1、3、4 处）并把第 2 处里的 `ARD_AllLocalUsers` 一类 ARD 键去掉**。
2. 记为 `P-008`。查清方法：在运行器上分别用两套配置跑一次，然后 `nc -z localhost 5900` 加 `log show --predicate 'process == "screensharingd"' --last 5m` 看 server 有没有起来、有没有认证失败。后一条命令形态来自上面那份 gist（它还提示每次 VNC DES 认证失败会累加约 2 秒延迟）。

### 5.6 VNC 要有 GUI session：自动登录

**一台没人登录的 Mac，VNC 连上去看到的是登录窗。** 对 `80` 第 2.3 节的截图与输入管线来说，登录窗等于什么都做不了。

离线预配自动登录要两处：

```bash
VOL=/Volumes/TGTDATA; U=harness
# 1. 指定自动登录的用户
sudo /usr/libexec/PlistBuddy -c "Delete :autoLoginUser" \
     "$VOL/Library/Preferences/com.apple.loginwindow.plist" 2>/dev/null || true
sudo /usr/libexec/PlistBuddy -c "Add :autoLoginUser string $U" \
     "$VOL/Library/Preferences/com.apple.loginwindow.plist"

# 2. /etc/kcpassword：口令按固定密钥做异或混淆
#    路径受 P-006 影响；kcpassword 的确切混淆算法记为 P-014
```

`INFERRED` 两处都是。`kcpassword` 的存在与用途有来源（转述自 <https://gist.github.com/remrearas/a3f300635b02f2587a134882a51f7114>），但本轮**没有确证 macOS 26 上的字节格式**，也没有确证 `autoLoginUser` 在 26 上是否仍然够用（Apple 多次改过自动登录与 FileVault 的交互）。记为 `P-014`。

**便宜的绕法，推荐优先用**：不做自动登录，改为在首启后由 `net.metal2vu.firstboot-probe` 之外再加一个 LaunchDaemon，SSH 进去之后用 `launchctl` 在 loginwindow 上下文里拉起一个 session；或者干脆接受"VNC 只用来看启动过程与登录窗"，把真正的 GUI 操作留到 `80` 的管线通过 SSH 启动。**E0-L1 的验收是"启动并 SSH 可达"（`73` 第 7.5 节），不包含 GUI 登录**，所以自动登录不是 E0 的阻塞项。

### 5.7 必须写的文件清单

一张表收口。全部路径相对于**目标 Data volume 的挂载点**。

| # | 路径 | 内容 | 为什么 | 标签 |
|---|---|---|---|---|
| 1 | `private/var/db/.AppleSetupDone` | 空文件 | 跳过 Setup Assistant | `KNOWN` |
| 2 | `private/var/db/.AppleDiagnosticsSetupDone` | 空文件 | 跳过诊断与用量面板 | `INFERRED` |
| 3 | `private/var/db/dslocal/nodes/Default/users/harness.plist` | 由 `dscl -f` 生成 | 预建管理员，#1 的前置 | `KNOWN` |
| 4 | `private/var/db/dslocal/nodes/Default/groups/admin.plist` | 追加 `GroupMembership` | 让 #3 是管理员 | `KNOWN` |
| 5 | `Users/harness/.ssh/authorized_keys` | harness 公钥，700/600 | SSH 登录 | `KNOWN` |
| 6 | `private/var/db/com.apple.xpc.launchd/disabled.plist` | `com.openssh.sshd` → `false`，`com.apple.screensharing` → `false` | 开 SSH 与 VNC | `KNOWN` |
| 7 | `private/etc/RemoteManagement.launchd` | `enabled` | 让 VNC server 起来。**路径见 `P-006`** | `KNOWN` |
| 8 | `Library/Preferences/com.apple.RemoteManagement.plist` | 见第 5.5 节 | VNC 访问策略 + 只听 localhost | `INFERRED` |
| 9 | `Library/Preferences/com.apple.VNCSettings.txt` | XOR 后的大写十六进制，无换行，600 | VNC 口令 | `KNOWN` |
| 10 | `Users/*/Library/Preferences/com.apple.SetupAssistant.plist` | 15 个 `DidSee*` + 5 个 `LastSeen*` | 压掉首次登录的面板 | `KNOWN` |
| 11 | `Library/LaunchDaemons/net.metal2vu.firstboot-expand.plist` + `usr/local/libexec/firstboot-expand.sh` | `73` 第 4.6.2 节 | 首启扩容 | `KNOWN` |
| 12 | `Library/LaunchDaemons/net.metal2vu.cpudisp-confirm.plist` + 脚本 | `74` 第 4.6 节 | 向 ESP 回写候选已确认 | `KNOWN` |
| 13 | `Library/LaunchDaemons/net.metal2vu.firstboot-probe.plist` + 脚本 | `71` 第 10.1 节 | 首启证据 | `KNOWN` |

**#1 到 #10 是"镜像起来能登进去"的最小集，#11 到 #13 是"镜像起来之后能被观测和自愈"的最小集。两组都不能省。**

---

## 6. CI workflow

文件：`.github/workflows/bake-macos-image.yml`。本节解释它的结构、每一步的失败点，以及**哪些步骤预期跑不绿**。

### 6.1 两个 job，不是一个

| job | runner | 作用 | 预期结果 |
|---|---|---|---|
| `probe` | `macos-26-intel` | 把第 8 节清单里**能在运行器上一次测清的事项**全部测掉，产出一个小 artifact | **预期通过。** 它全是只读检查，末尾 `exit 0` |
| `bake` | `macos-26-intel` | 真正烘镜像 | **预期失败**，直到 `P-001`/`P-002`/`P-003` 关闭。默认不运行，要显式传 `run_bake=true` |

**把 `probe` 和 `bake` 分开是本文最重要的一条 workflow 设计决定。** 理由来自 `91` 第 5.4 节记的 `R-004`：上一轮两个 job 报 failure 但 artifact 全有，失败来自某个步骤的非零退出码。诊断与执行混在一个 job 里，结果就是"失败了但不知道是哪一类失败"。分开之后，`probe` 绿 + `bake` 红 是一个有信息量的状态：说明环境查清了，是执行逻辑的问题。

### 6.2 `probe` 关掉哪些编号

| 步骤 | 关掉 | 命令要点 |
|---|---|---|
| disk | `P-001` | `df -h /`、`diskutil apfs list`、`du -sh /Applications/Xcode*.app`、`sysctl kern.hv_support` |
| seal | `P-003` | `csrutil status`、`csrutil authenticated-root status`、`diskutil apfs listsnapshots <sysvol>` |
| firmlink | `P-006` | `cat /usr/share/firmlinks`、`stat -f '%d %N' /System/Library /private/var /private/etc` |
| platform | `P-007` | `ioreg` 取 board-id、`sw_vers`、`uname -a` |
| installer | `P-009` `P-010` | `softwareupdate --list-full-installers`、若 `/Applications` 里有安装器则跑 `startosinstall --usage` |
| labels | 第 5.4 节的 Label | `PlistBuddy -c 'Print :Label'` 对 `ssh.plist` 与 `com.apple.screensharing.plist` |
| ard | 第 5.5 节的权限掩码 | 跑一次 `kickstart -configure -allowAccessFor -allUsers -privs -all`，再 `plutil -p` 把它生成的 plist 抄下来 |
| preboot | 第 2.4 节 R2 的两条 `BLOCKED` | `find /System/Volumes/Preboot -maxdepth 4`、`ls -la .../cryptex1` |
| physstore | `P-011` | 把 `diskutil info -plist /` 喂给 `plutil -p -`，看 `APFSPhysicalStores` |

**`probe` 的每一个步骤都以 `exit 0` 结尾。** 原因是 `91` 的 `R-004`：`set +e` 只关 errexit，步骤的退出码仍然取最后一条命令。一个 `grep` 没匹配上就能把整个诊断 job 判成失败，而 artifact 里明明有数据。

### 6.3 `bake` 的失败点清单

按发生顺序。每一条都对应 workflow 里一个独立的步骤与一条 `::error::` 输出。

| # | 步骤 | 失败表现 | 真实原因 / 处置 |
|---|---|---|---|
| 1 | 空间门禁 | 自己 `exit 1`，打印四个数字 | container 可用 < 30 GB。走第 7 节替代 |
| 2 | 封印门禁 | `exit 1` | `csrutil authenticated-root status` 不是 enabled，或 `listsnapshots` 不是恰好一个 `com.apple.os.update-*`。源封印不完好，`asr` 会以 broken seal 拒绝 |
| 3 | 腾空间 | `rm -rf` 报错 | Xcode 路径名变了。**这一步必须允许部分失败**，每条 `rm` 后面都接一个 `true` 兜住，然后重新量空间 |
| 4 | 建镜像并 attach | `hdiutil attach` 失败 | 缺 `-imagekey diskimage-class=CRawDiskImage`（扩展名不是 `.dmg`/`.img` 时必须给），或文件系统不支持稀疏 |
| 5 | 解析源卷与快照 | `plutil -extract` 返回空 | 键路径不对。根卷是快照，`DeviceIdentifier` 可能形如 `diskNsMsK`。**这一步是 `P-003` 的实际消费点** |
| 6 | `asr restore` | `exit 1`，日志里有 `broken seal` 或权限错 | 要么封印问题（#2 没拦住），要么缺 Full Disk Access（`P-004`）。**也可能卡在交互确认**，所以必须给 `--noprompt` 或喂 `y` |
| 7 | 验证目标容器 | `diskutil apfs list` 里没有 Preboot / Recovery | `asr` 没把源识别为"有效系统"。这是 `P-002` 的实际消费点 |
| 8 | 建 / 核对 Data volume | `addVolume` 报 role 冲突 | `asr` 已经建了配对 Data volume（`P-005` 的答案是"会"），这一步应当跳过而不是报错 |
| 9 | 预配 | `PlistBuddy` / `dscl -f` 报错 | `dscl -f` 对离线节点的路径写错，或 `UniqueID` 冲突（第 5.3 节说明 2） |
| 9b | 首启三件套 | 只告警，不终止 | `scripts/` 里没有 `firstboot-expand` / `cpudisp-confirm` / `firstboot-probe` 的脚本与 plist。**本步骤刻意不终止流水线**，缺件记进 manifest 的 `missing_firstboot_daemons`，`deployable` 置 false。让流水线走到底，产出一块可检查但不可部署的镜像，比在中途断掉更有信息量 |
| 10 | `bless` | 无报错但产物起不来 | **这一步不会在 CI 里暴露**，只有在 L1 的 QEMU 里启动才知道。所以 workflow 的最后一步只能是"产出镜像"，验收在别处 |
| 11 | detach + 导出 | `hdiutil detach` 说 busy | 有进程还占着挂载点。`sudo hdiutil detach -force`，并在之前 `diskutil unmountDisk` |
| 12 | 上传 | `curl` 403 / 413 | 预签名 URL 过期或对象存储有单件上限。**没有 `IMAGE_PUT_URL` 时这一步跳过而不是失败**，并只上传清单 |

### 6.4 三个必须避开的坑（来自 `91` 第 5.7.1 节）

逐条对照本文的 workflow 做了什么：

| `91` 记的坑 | 本文怎么避 |
|---|---|
| 坑 1：`brew install llvm@19` 没 bottle，转去编源码，job 卡一小时 | 本文只需要 `zstd` 一个包，而且**先用 `command -v` 探测，探不到就退回预装的 `gzip`**，压缩比差一点而已。**绝不 `brew install` 任何带版本号的 formula** |
| 坑 2：缺依赖导致 `meson setup` 失败 | 本文不构建任何东西，依赖只有系统自带的 `hdiutil`/`diskutil`/`asr`/`bless`/`plutil`/`PlistBuddy`/`dscl`/`python3`。**第一个步骤逐个 `command -v` 检查并打印版本**，缺哪个立刻失败 |
| 坑 3：两步式结构里 PATH 不一致，`ninja` 跑到 758/786 才挂 | 本文不跨步骤传 PATH。跨步骤传的只有 `$GITHUB_ENV` 里的几个绝对路径（`IMG`、`DEV`、`TGT_SYS`、`TGT_DATA`），而且每一步开头都重新 `echo` 一遍做自检 |

### 6.5 哪些步骤必然失败或未验证

**不要期待这个 workflow 第一次就绿。** 逐条标注：

| 步骤 | 状态 |
|---|---|
| `probe` 的全部步骤 | **未验证，但预期通过。** 全是只读命令 |
| `bake` 的 #1 空间门禁 | **预期失败的头号候选。** 官方口径只有 14 GB（第 3.1 节） |
| `bake` 的 #6 `asr restore` | **未验证。** `--noprompt` 对 APFS erase 确认是否生效未实测 |
| `bake` 的 #7 验证目标容器 | **未验证，且有一条明确的反面来源**（第 2.3.5 节的"不要用 ASR 做镜像"警告） |
| `bake` 的 #8 Data volume | **未验证。** `P-005` 决定它是必做还是必跳 |
| `bake` 的 #9 预配 | 其中第 5.2 节的 `defaults write` 对目标卷的行为未验证（`P-013`）。workflow 里实际用的是 `PlistBuddy` 而不是 `defaults`，正是为了绕开这一条；其余有既有做法支撑 |
| `bake` 的 #9b 首启三件套 | **必然只告警**，因为 `scripts/` 下那 6 个文件现在不存在（第 6.7 节）。后果是 manifest 的 `deployable` 为 false |
| `bake` 的 #10 `bless` | **在 CI 里不可验证。** 只能在 L1 的 QEMU 里验 |
| `bake` 的 #12 上传 | 未验证，依赖仓库 secret `IMAGE_PUT_URL` 是否配置 |

### 6.6 产物与体积

| 产物 | 走哪条通道 | 体积 |
|---|---|---|
| `probe-report`（文本 + plist dump） | artifact | < 1 MB |
| `bake-logs`（含失败时的全部诊断） | artifact，`if: always()` | < 5 MB |
| `image-manifest.json`（尺寸、SHA-256、源 build、快照 UUID） | artifact | < 4 KB |
| `macos-apfs.raw.zst` | **只走 `IMAGE_PUT_URL`，不走 artifact** | 8 到 20 GB（压缩后） |

**最后一行是第 3.4 节那条配额约束的直接结果。** workflow 里不存在任何把镜像塞进 artifact 的路径，这是刻意的，不是遗漏。

`image-manifest.json` 里有两个字段专门用来表达"这块镜像能不能用"：

```json
{
  "missing_firstboot_daemons": ["cpudisp-confirm"],
  "deployable": false,
  "evidence_label": "TESTED(25G76) only; NOT 25G325 (see 75 section 2.3.6)"
}
```

**`deployable: false` 的镜像不许进 `73` 的投放流水线。** 这是把第 4.4 节"三个 LaunchDaemon 都不能省"做成机器可判的形式。

### 6.7 输入、secret 与前置文件

| 项 | 类型 | 缺了会怎样 |
|---|---|---|
| `run_bake` | workflow 输入，默认 false | 只跑 `probe` |
| `image_size_gb` | 输入，默认 32 | 见第 4.1 节 |
| `min_free_gb` | 输入，默认 30 | 空间门禁的判定线，见第 3.1 节 |
| `free_xcode` | 输入，默认 true | 不删 Xcode 时空间门禁几乎必然失败 |
| `vnc_password` | 输入，默认空 | 空则跳过第 5.5 节的全部四处写入 |
| `HARNESS_SSH_PUBKEY` | repo secret | **缺了镜像起来登不进去。** workflow 只告警不失败，`authorized_keys` 写成空文件 |
| `IMAGE_PUT_URL` | repo secret，预签名 PUT | 缺了跳过导出，只留 manifest 与日志 |
| `scripts/firstboot-expand.sh` 等 6 个文件 | 仓库文件 | 见第 6.3 节的 #9b |

**`scripts/` 下那 6 个文件的正文分别在 `73` 第 4.6.2 节、`74` 第 4.6 节、`71` 第 10.1 节。** 本文不复制它们，也不要求本次提交创建它们；workflow 的 #9b 步骤就是为"它们还不存在"这个现状设计的。

---

## 7. 风险与替代

按"如果第 2 节的全部路径在运行器上都不可行"排序。每一条给出触发条件、代价、与它关掉哪个前提。

### 替代 A：输出盘放在远端，运行器只做计算（首选）

**触发条件**：`P-001` 测出 container 可用空间 < 30 GB，但其余一切正常。

做法：在 `bake` 开头挂一个远端文件系统，把第 2.3.3 节第 1 步的 `$IMG` 放到上面。

```bash
# 两条路，二选一
sudo mkdir -p /Volumes/remote
mount_smbfs "//user:pass@host/share" /Volumes/remote         # 1) SMB
rclone mount r2:bucket /Volumes/remote --vfs-cache-mode writes &   # 2) rclone
IMG=/Volumes/remote/macos.raw
```

**代价与风险**：20 GB 级的随机写跑在网络文件系统上；job 上限是 6 小时（第 3.4 节）。`hdiutil attach` 能不能在 SMB 上建稳定的块设备未实测。`INFERRED`。

**它关掉的是磁盘空间这一个前提，不解决 `P-002`。**

### 替代 B：不做完整镜像，只做"BaseSystem + 预配好的 Data volume"

**触发条件**：`P-002` 否定，即 `asr` 的克隆在空盘上起不来。

做法：回到 `71` 第 2.4 节的路 A。`x86_64BaseSystem.dmg` 已经在手（1.46 GB，第 1.3 节），把它当一块普通盘挂给 OpenCore，**同时**在镜像里预置一个已经预配好的空 APFS container。首启进恢复环境，由一个放在 ESP 上的脚本自动完成安装。

**代价**：这是"半个安装器"，违反约束 2 的字面意思（它确实启动了安装介质），但它**不要求交互**。需要所有者重新裁决。体积上 1.46 GB 的 BaseSystem 远低于 Vultr ISO 的 10 GB 上限（`73` 第 3.1.1 节），所以它可以走 ISO 槽位而不占快照通道。

**它关掉的是"必须有一块装好的盘"这个前提，代价是放弃"完全不走安装器"。**

### 替代 C：R2，在 Linux 上自建 APFS 卷

**触发条件**：`P-002` 否定，且替代 B 被所有者拒绝。

做法见第 2.4 节。它需要先把那两条 `BLOCKED`（cryptex 与 Preboot 布局）关掉，而关掉它们只需要运行器上的一次 `find`，`probe` job 已经包含。

**代价**：Linux 上没有 APFS 写支持。需要 `apfs-fuse` 一类只读实现之外的东西，或者把"写 APFS"这一步仍然放回运行器（那就回到 `P-001`）。**这是本节里最贵的一条，但它是唯一能在烘制期拿到 25G325 的。**

### 替代 D：`73` 第 4.1 节的 D0，云上人工装一次

**触发条件**：A、B、C 都不成立。

做法不变：ISO 装一次，看一次网页控制台，约 1 小时，然后 `POST /v2/snapshots` 存成 golden，之后全自动。

**代价**：1 次人工。**收益**：它是唯一一条已经被 `73` 完整写过、不依赖任何本文未验证项的路。

### 替代 E：接受 25G76 并在部署后自升级

这不是"替代 A 到 D"的同级项，而是**和它们正交**的一个决定（第 2.3.6 节）。单独列出来是因为它常被忘掉：如果 R1 成立，镜像就是 25G76，而把它变成 25G325 的最省事办法是首启之后 `softwareupdate -i -a -R`，走增量更新，不需要 18 GB 落盘。

### 排序总结

```text
P-001 绿 + P-002 绿  →  R1（第 2.3 节）。本文的 workflow 就是这条
P-001 红 + P-002 绿  →  替代 A（远端输出盘）
P-002 红             →  替代 B（BaseSystem + 预配容器），需所有者重新裁决约束 2
B 被拒               →  替代 C（R2 自建），先关掉 cryptex/Preboot 两条 BLOCKED
全不成立             →  替代 D（D0，一次人工）
以上任一成立         →  叠加替代 E（部署后自升级到目标 build）
```

---

## 8. 未解决项清单

| 编号 | 事项 | 标签 | 查清方法 | 阻塞什么 |
|---|---|---|---|---|
| **`P-001`** | `macos-26-intel` 的 APFS container 真实可用空间；删掉 Xcode 能换回多少 | `BLOCKED` | `probe` job 的 disk 步骤：`df -h /`、`diskutil apfs list`、`diskutil info -plist /`、`du -sh /Applications/Xcode*.app`、`sysctl kern.hv_support` | 整条 R1。< 30 GB 则走替代 A |
| **`P-002`** | `asr` 能否把克隆落到一块从未装过 macOS 的空盘并在 OpenCore 下起来。Apple 的克隆指引明确警告 Intel 上"大概不成" | `BLOCKED` | 先在 `bake` 里产出镜像，再在 L1 的 QEMU 里按 `71` 第 8.2.4 节启动；按第 2.3.5 节的三条解释分辨失败层级 | R1 的成立性。否定则走替代 B/C |
| **`P-003`** | 运行器的 system volume 封印是否完好；`csrutil authenticated-root status` 的值 | `BLOCKED` | `probe` job 的 seal 步骤。`diskutil apfs listsnapshots` 必须恰好一个 `com.apple.os.update-*` | `asr` 能否以该卷为源 |
| `P-004` | `asr` 是否需要 Full Disk Access；无 GUI 时怎么授权 | `INFERRED` | 直接跑 `asr`，失败则读 `TCC.db` 的 `.schema access` 再决定插法。SIP 已关，库可写 | `bake` #6 |
| `P-005` | 克隆完目标容器里是否已有配对的 Data volume 与 volume group | `INFERRED` | 克隆后 `diskutil apfs list "$DEV"` + `diskutil apfs listVolumeGroups` | 第 2.3.3 节第 4 步与第 2.3.4 节是必做还是必跳 |
| `P-006` | `/private/etc` 在 system volume 还是 Data volume | `INFERRED` | `stat -f '%d %N' /System/Library /private/var /private/etc`，比 device 号 | 第 5.5 节的 #7、第 5.4 节的 `sshd_config` 改法、第 5.6 节的 `kcpassword` |
| `P-007` | 运行器的 board-id 是不是 `VMM-x86_64` | `INFERRED` | `probe` job 的 platform 步骤 | 只影响第 2.1 节第二层的推理，不阻塞 R1 |
| `P-008` | macOS 26.6.x 上 Remote Management 与 Screen Sharing 是否互斥，离线该配哪一套 | `INFERRED` | 在运行器上分别配两套，`nc -z localhost 5900` + `log show --predicate 'process == "screensharingd"'` | 第 5.5 节的四处写入内容 |
| `P-009` | 25G325 的 `startosinstall --usage` 实际输出里有没有 `--volume` | `INFERRED` | `probe` job 的 installer 步骤 | 只为把第 2.1 节的结论钉死，不阻塞任何路径 |
| `P-010` | `softwareupdate --list-full-installers` 是否给出 build 列；能不能钉死 `25G325` | `INFERRED` | `probe` job 的 installer 步骤 | 替代 C 与替代 E 的可操作性 |
| `P-011` | 根是封印快照时，`diskutil info -plist /` 的 `APFSPhysicalStores.0.APFSPhysicalStore` 键路径是否仍成立 | `INFERRED` | 在运行器上直接 `plutil -p` | `73` 第 4.6.2 节的首启扩容脚本 |
| `P-012` | Vultr 的 `create-from-url` 能否接受 28 到 32 GB；接 `73` 的 D-003 | `BLOCKED` | 实际 POST 一次，看 `status` 与 `size` | 第 4.1 节的尺寸决定是否可交付 |
| `P-013` | 预配后首启是否仍跑一次"完成安装"阶段；`defaults write` 对目标卷的写入是否被 `cfprefsd` 干扰 | `INFERRED` | 首启探针（`71` 第 10.1 节）记录 `/var/log/install.log` 与 `com.apple.SetupAssistant.plist` 的实际内容 | 第 5.2 节第二层的有效性 |
| `P-014` | `kcpassword` 在 macOS 26 上的字节格式；`autoLoginUser` 是否仍够用 | `INFERRED` | 在运行器上用 GUI 之外的方式设一次自动登录，然后 `xxd /etc/kcpassword` | 第 5.6 节。**不阻塞 E0** |
| `P-015` | 镜像从运行器运出去的通道：对象存储单件上限、6 小时 job 内能传多少 | `INFERRED` | 先用一个 1 GB 的假文件跑一遍第 3.4 节的流式 PUT，量吞吐 | `bake` #12 |
| `P-016` | 25G76 与 25G325 的 kernel collection 内容差异（`71` 第 3 节的 204 + 172 条 fileset 是否同构） | `BLOCKED` | 在运行器上重建两个 KC 并枚举，与 `90` 第 2.1 节的 25G325 清单逐条比对 | 替代 E 是否必要；本项目全部 `TESTED(25G76)` 结论对 25G325 的外推强度 |

**最该先查的三条是 `P-001`、`P-002`、`P-003`**，而且它们有依赖顺序：`P-001` 和 `P-003` 由 `probe` job 一次跑完，`P-002` 必须等 `bake` 产出镜像并在 L1 上启动过才能关。**`P-002` 是本文唯一一条无法在 GitHub Actions 内部关闭的项**，它需要 `73` 第 7 节判定 KVM 可用，或者走 `73` 第 7.4 节的替代 A（Linux runner 上跑 QEMU）。

---

## 9. 相关分册

- `71-IMAGE-OPENCORE.md`：本文产出的 APFS container 要被拼进 `71` 第 8 节的交付形态；ESP 的内容、`config.plist`、SMBIOS 选型、串口可观测性全部以 `71` 为准。本文第 4.1 节对 `73` 第 4.6.3 节的修订建议会连带影响 `71` 第 8.1 节产物总表里 `macos-oc-<build>.raw` 的体积一栏。
- `73-DEPLOY-RESCUE.md`：本文产出的镜像走 `73` 第 3.1.2 节的 `create-from-url` 或第 4.3 节的 iPXE 通道；分区布局、首启扩容、rescue 分区、救砖阶梯全部以 `73` 为准。本文给 `73` 留下一条修订建议（第 4.1 节）与一个新编号 `P-012`（并入 `73` 的 D-003）。
- `74-BOOT-CPU-DISPATCH.md`：本文的 ESP 要容纳 `74` 第 3.2 节的 `/EFI/CPUDISP/`；第 4.4 节的三个 LaunchDaemon 里有一个是 `74` 第 4.6 节的确认 daemon，**不装它会让候选阶梯把每次成功都判成失败**。
- `70-BUILD-PACKAGE.md`：第 5 节的 `csr-active-config = 0xFEF` 固化在 OpenCore 而不是镜像里，所以本文的镜像不为 SIP 做任何事；该值的 bit 11 顺带满足了本文第 2.2 节备选路径的前置条件。
- `91-RUNTIME-EVIDENCE.md`：本文全部关于运行器的事实引自它第 1 节；本文的 workflow 避开的三个坑引自它第 5.7.1 节；`exit 0` 的纪律来自它的 `R-004`。本文的 `probe` job 一旦跑过，结果应当作为新的 `TESTED(25G76)` 条目补进 `91`。
- `80-TEST-HARNESS.md`：第 2.3.5 节的 `kickstart` 与 `VNCOnlyLocalConnections` 是本文第 5.5 节的运行时对照物；本文给的是它的离线等价形态。

---

## 外部来源索引

本文引用的全部外部来源，按出现顺序。**内容均为转述以符合许可限制。**

| # | 用途 | URL |
|---|---|---|
| 1 | SIP 位域定义（`csr.h`） | <https://khronokernel.com/macos/2022/12/09/SIP.html> |
| 2 | `macos-26-intel` 的 CPU/RAM/存储规格；arm64 macOS 不支持嵌套虚拟化 | <https://docs.github.com/en/actions/reference/runners/github-hosted-runners> |
| 3 | GitHub 只保证镜像至少 14 GB 空闲 | <https://github.com/actions/runner-images/issues/13528> |
| 4 | x86_64 Actions 镜像的落日（2027 年 8 月） | <https://github.com/actions/runner-images/issues/13045> |
| 5 | `startosinstall` 的可用选项随引导 OS 环境变化；`--volume` 只在安装器/恢复环境出现 | <https://gist.github.com/gregneagle/d2a889ba31a8771364db03e2b689bef2> |
| 6 | Catalina 上从完整 OS 用 `--volume` 装外置盘 | <https://apple.stackexchange.com/questions/413772/use-startosinstall-to-install-macos-catalina-on-external-drive> |
| 7 | Big Sur 的 `startosinstall --usage` 全文（无 `--volume`）；`softwareupdate help` 全文 | <https://www.jamf.com/blog/streamlining-your-macos-upgrade-process/> |
| 8 | `--full-installer-version` 写错会被静默忽略 | <https://community.jamf.com/general-discussions-2/softwareupdate-fetch-full-installer-25597> |
| 9 | `csrutil authenticated-root status` 是与 SIP 并列的独立状态 | <https://osxhub.com/disable-sip-mac/> |
| 10 | `csrutil authenticated-root disable` + OCLP root patch 的既有做法 | <https://github.com/Nishit-Chauhan/Ventura-Hackintosh-Haswell-EFI> |
| 11 | ASR 是唯一能复制 SSV 的工具；完整克隆命令序列；`--toSnapshot`；Intel 要排除 `--no-personalization`；**不要用 ASR 做镜像**；克隆不跨平台 | <https://discussions.apple.com/docs/DOC-250005828> |
| 12 | `asr(8)`：APFS 容器恢复规则、"有效系统"定义、Preboot/Recovery 的连带复制 | <https://keith.github.io/xcode-man-pages/asr.8.html> |
| 13 | `diskutil(8)`：`addVolume -role -groupWith`、volume roles、`resizeContainer` | <https://keith.github.io/xcode-man-pages/diskutil.8.html> |
| 14 | `bless(8)` | <https://keith.github.io/xcode-man-pages/bless.8.html> |
| 15 | `kmutil(8)` | <https://keith.github.io/xcode-man-pages/kmutil.8.html> |
| 16 | `hdiutil(1)` | <https://keith.github.io/xcode-man-pages/hdiutil.1.html> |
| 17 | `CRawDiskImage` imagekey 的用法 | <https://apple.stackexchange.com/questions/375170/how-do-you-create-an-apfs-volume-inside-an-ordinary-file> |
| 18 | 同上，非 `.dmg`/`.img` 扩展名时该 imagekey 是必须的 | <https://apple.stackexchange.com/questions/463693/mounting-a-bit-by-bit-copy-of-a-partition-in-macos> |
| 19 | Actions 的全部限额：artifact 存储配额、6 小时 job 上限、500 KB workflow 上限 | <https://docs.github.com/en/actions/reference/limits> |
| 20 | firmlink 清单在 `/usr/share/firmlinks` | <https://superuser.com/questions/1490834/how-to-find-firmlinks> |
| 21 | `.AppleSetupDone` 的语义 | <https://discussions.apple.com/thread/250996371> |
| 22 | 对挂载卷执行 `dscl -f` 建用户、`touch .AppleSetupDone` 的既有做法 | <https://github.com/assafdori/bypass-mdm/blob/main/bypass-mdm.sh> |
| 23 | Setup Assistant 的 `DidSee*` / `LastSeen*` 键集与自证方法 | <https://gist.github.com/tperfitt/7bcf0e282dd3772bacaa10a09a23481a> |
| 24 | launchd override 的位置与格式（`disabled.plist` 覆盖各 plist 的 `Disabled`） | <https://apple.stackexchange.com/questions/207854/restoring-yosemite-server-after-unloading-launch-daemons> |
| 25 | `launchctl -w` 不再改原 plist，状态记在别处 | <https://serverfault.com/questions/218402/how-does-one-check-whether-the-os-x-disabled-flag-for-launchd-services-is-set> |
| 26 | `disabled.<UID>.plist` 的实例输出 | <https://developer.apple.com/forums/thread/8489> |
| 27 | `launchd.plist(5)` | <https://keith.github.io/xcode-man-pages/launchd.plist.5.html> |
| 28 | `/private/etc/RemoteManagement.launchd` 只需含 `enabled`；`com.apple.VNCSettings.txt` 是 VNC 控制口令 | <https://discussions.apple.com/thread/1312397> |
| 29 | `kickstart` 的 `-configure -allowAccessFor -allUsers -privs -all` 会设 `ARD_AllLocalUsers` 与全用户权限掩码 | <https://loobins.io/binaries/kickstart/> |
| 30 | VNC 口令的 XOR 密钥与 8 字节截断 | <https://gist.github.com/852485> |
| 31 | `com.apple.screensharing` 的 override 写法、`VNCOnlyLocalConnections`、`screensharingd` 日志查法、SSH 隧道形态 | <https://gist.github.com/remrearas/a3f300635b02f2587a134882a51f7114> |
| 32 | macOS 26.6.1 上 VNC 的回归与绕法 | <https://discussions.apple.com/thread/256337577> |
| 33 | `kickstart` 的完整命令行形态 | <https://digitash.com/apple/macos/how-to-enable-and-configure-macos-screen-sharing-via-terminal-command-line/> |
| 34 | `hdiutil` 在 macOS 27 被标记弃用的说法（二手来源，可信度低） | <https://sesamedisk.com/hdiutil-deprecated-macos-how-to-use/> |
