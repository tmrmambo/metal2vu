# 78 APFS 卷构建：一块能启动的 macOS 26 x86_64 盘的 on-disk 规格

文档版本：1.1
基线日期：2026-10-30（1.1 修订：2026-11-01）
上级文档：`docs/spec/00-OVERVIEW.md`
配套分册：`71-IMAGE-OPENCORE.md`（素材与引导器）、`75-IMAGE-PREBAKE.md`（装配形式）、`76-BOOT-LAYOUT-PICKER.md`（卷角色与分区）、`77-UPDATEBRAIN-ABI.md`（Apple 自己怎么做）、`80-TEST-HARNESS.md`（启动验收）
取证 workflow：`.github/workflows/forensics-boot-layout.yml`
自有工具：`tools/ci/mkgpt.py`（离线写 GPT）、`tools/ci/gptdump.py`（读 GPT 原始字节）

---

## 版本 1.1 修订说明：两轮取证把第 A 节从「机制已知」推到「命令已验」

1.0 把第 A 节的十层里八层写成了可照抄的命令，但那些命令**一条都没在真机上跑过**。
1.1 的全部内容来自两轮 CI 取证（run `41271530800` 与 run `41274204499`，运行器 25G76 /
x86_64 / SIP disabled / `Apple Paravirtual device`）。**结果是四条规格被证伪、十条待定项被关闭。**

**被证伪的四条（1.0 照着写一定会失败，按严重度排）：**

| # | 1.0 怎么写的 | 实测 | 后果 |
|---|---|---|---|
| 1 | 第 A.1 节：用 `gpt create -f` / `gpt add` 写分区表 | **`gpt` 的任何修改类子命令在 25G76 上一律 `operation not permitted`** —— 带不带 `sudo`、关不关 SIP、先不先 `unmountDisk` 都一样，而 `gpt -r show` 正常 | 装配链**第一条命令**就倒。改为离线写（`tools/ci/mkgpt.py`），见第 A.1 节 |
| 2 | 第 A.1 节约束 3：p2 的 APFS 类型 GUID「必须在建容器之前就写对」 | **恰好相反。** 事先把 p2 写成 `7C3457EF-…`，`diskutil apfs createContainer` 报 `Error: -69614: The disk is already in use by APFS`。把 p2 写成 `Apple_HFS`（`48465300-…`）则成功，且 `createContainer` **自己把类型改成了 APFS** | 第二条命令倒。约束 3 整条反写，见第 A.1 节 |
| 3 | 第 A.3.2 节的建卷顺序：System 第一个建，Data 再 `-groupWith` 它 | **顺序整条反了。** 内核日志：`apfs_newfs: A Non-sealed system sibling volume is not allowed` —— APFS 不许给一个未封印的系统卷建兄弟卷，而我们是最后才 bless 封印。**解法：先建 Data（不成组），再建 System（`-role S -groupWith <data>`）**，实测一次通过 | **`V-031` 已解决**，见第 A.3.3a 节。顺带定死「Preboot 的目录名 = Data 卷的 Volume UUID」 |
| 4 | 第 A.4.2 节规则 3 的退路：`chflags 0x80000` | **`chflags: invalid flags: 0x80000`，这个写法不存在。** 而助记符 `chflags restricted` 正常（回读 `flags=80000 restricted`） | 退路无效，但主路可用，所以不阻塞 |

| 5 | 第 A.3.2 节的 `vol_of`（按 `diskutil list` 的文本前缀匹配卷名） | `vol_of "Macintosh HD"` 命中 `Macintosh HD - Data` 那一行 —— 因为 Apple 的命名约定就是 `<名字>` 与 `<名字> - Data`，两者是前缀关系 | bless 实验被指向 Data 卷，回报 `Volume does not have system role`。改成逐卷读 `diskutil info` 的 `Volume Name` 精确比较 |

**被关闭的待定项：** `V-001`（见上）、`V-003`（`APFSContainerReference` 键名正确）、
`V-006`（`FilesystemName` = `APFS`，非大小写敏感）、`V-007`（role B/V 可设）、
`V-009`（`restricted` 可用、`0x80000` 不可）、`V-014`（Preboot 全树已取到，见第 A.6.7 节）、
`V-016`（Preboot 里**确实有** `com.apple.Boot.plist`）、`V-017`（三份 `boot.efi` 字节相同，
问题消失）、`V-021`（`bless --info` 直接给出 blessed 路径）、`V-029`（新增，ESP 可建）、
`V-030`（新增，`gpt` EPERM 的根因）。

**仍未关闭：** `V-002`、`V-004`、`V-005`、`V-008`、`V-011`…`V-013`、`V-015`（部分）、
`V-018`、`V-019`、`V-022`（部分）、`V-023`（部分）、`V-028`、`V-032`、`V-033`、
**`V-034`（新，现在的第一优先）**。逐条见第 E 节的表。

> [!CAUTION]
> **1.1 的最后一轮取证（run `41279550835`）发现了一条改变路径优先级的硬限制：**
> **`bless --create-snapshot` 要求目标卷已经是 ARV（Authenticated Root Volume），
> 所以 `bless` 封不了第一次印。**
>
> ```text
> Can't use snapshot options on non ARV volume
> Snapshot manipulation failed
>    退出码 = 2
> ```
>
> 不带快照选项的 `bless` 则**退出码 0**，并把三个文件正确铺进 Preboot
> （`boot.efi` + `.disk_label` + `.disk_label_2x`，第 A.10.2c 节有逐字节清单）。
>
> **即：第 A 节的十层里，现在只有「封印」这一层没有已验证的自建手段。**
> 三条候选解（`asr` 克隆 / 自己调 `fs_snapshot` / 干脆不要 ARV 靠
> `CSR_ALLOW_UNAUTHENTICATED_ROOT`）在第 A.10.2c 节逐条给出。
> 这也把 `75` 的 R1（`asr` 克隆运行器）从「先做的那条」升级为
> **「唯一已知能产出 ARV 的那条」**。

**三轮取证之间自己踩的坑，一并记在这里，因为它们各自浪费了一整轮：**

| 坑 | 表现 | 教训（已写进第 C 节纪律） |
|---|---|---|
| 护栏用 `${VAR%%s*}` 取「整盘标识」 | `disk3s1` 与 `disk1s5s1` 都被截成 `di`，于是「同一块物理盘」恒成立，bless 实验**连续两轮**被自己挡住 | 问 `diskutil` 的 `Part of Whole`，不要用 shell 的后缀删除 |
| 提前退出的分支不落文件 | 产物里既没有 `C0-bless-experiment.txt` 也没有任何解释，从 artifact 上分不清「没跑」与「跑了但被挡」 | **每一条 `exit` 路径都要写一个说明文件** |
| `diskutil apfs convert` 的参数顺序 | 写成 `convert -dryrun -prebootSource DIR DISK`，`diskutil` 把第一个非选项参数当磁盘，报 `Could not find disk for -dryrun`。这个实验**两轮都没真正跑过** | `diskutil` 的动词一律 `<动词> <磁盘> [选项…]` |
| `bless` 要求 `<UUID>/` 目录已存在 | `No valid group or volume UUID folder` + 退出码 2，而且**它一个文件都没写**（bless 前后 Preboot 全树 diff 为空） | 第 B 节步 11 必须在步 12 之前，而且 `mkdir -p` 是前置条件不是兜底 |
| `diskutil` 的 `-69854` | `convert` 与 `listSnapshots` 都对**未挂载**的卷返回 `A disk with a mount point is required` | 凡是要读卷内容的 `diskutil` 动词，先 `diskutil mount` |

## 0. 本文作用与前提

### 0.1 本文回答的那一个问题

项目所有者的原话转述：

> 「我不清楚这个 macOS 是怎么装进去的。我认为**不管 macOS 是怎么装进去的，它都不应该由原生的安装器安装**。那就得自己构建 APFS 卷了。我倒不是说要在本机构建，而是**我们是否知道应该如何构建一个符合苹果要求的磁盘镜像，令系统能启动**。」

所以本文**不是**「找哪个 Apple 工具能替我们干」。那件事前面三册已经干完：`75` 的 R1（`asr` 克隆）/ R2（直写）/ R6（UpdateBrain），`77` 的 UpdateBrain 接口逆向。

**本文写的是规格本身**：一块盘上必须有什么、各自什么内容、什么顺序建、怎么验。它是一份 on-disk 契约，不绑定任何一条实现路径 —— R1、R2、R6 产出的东西都必须满足本文第 A 节，否则起不来。

### 0.2 整份规格得以成立的那一条：目标不是「造一个封印正确的卷」

**目标是「造一个卷 + 一个快照 + bless + Preboot」。** 封印（SSV seal）本身不需要我们去匹配任何 Apple 签名的值。这一条已经**五路确证**，前四路是已有分册的结论，直接引用，不重新论证：

| # | 事实 | 来源 | 标签 |
|---|---|---|---|
| 1 | SSV 封印的实体就是 `-[LPStaticAPFSVolume createSnapshot:error:]`（RVA `0x145024`）里一条 **`fs_snapshot_create(2)` BSD syscall**。Merkle root hash 由 APFS 内核算，**不签名、不联网**。同一节还记录了 `skip-sealing` 开关与日志 `Skip sealing flag is set. System may not boot after update.` | `77` 第 D.1 节 | `KNOWN` |
| 2 | `csr-active-config = 0xFEF`，其 **bit 11 = `CSR_ALLOW_UNAUTHENTICATED_ROOT`**（`0x800`），即 `boot.efi` 不校验封印 | `70` 第 5.1、5.2 节 | `KNOWN` |
| 3 | `Misc/Security/SecureBootModel = Disabled`。Apple 官方安全文档说明 Intel Mac 的 `boot.efi` 校验 `immutablekernel` 签名**只在 secure boot 启用时**发生（转述自 <https://support.apple.com/en-nz/guide/security/boot-process-sec5d0fab7c6/web>） | `71` 第 6.6.2 节 | `KNOWN` |
| 4 | **LocalPolicy 是 Apple Silicon 独有**，存在内置存储的隐藏 `Apple_APFS_ISC` 容器的 `iSCPreboot` 卷里，而且**不在外置可启动盘上**（转述自 <https://eclecticlight.co/2022/11/21/booting-macos-on-apple-silicon-localpolicy/>）。**Intel 上没有逐机启动策略对象要伪造。** | `76` 第 1.2 节 | `KNOWN` |

**第 5 路（本文新增）：Apple 官方文档自己把封印校验的责任限定在 T2 上。** `KNOWN`，转述自 <https://support.apple.com/guide/security/secd698747c9/web>：该页说明安装与更新期间 seal 由设备本地重算并与 Apple 签过的测量值比对；随后分平台说明校验者 —— Apple silicon 上是 bootloader 在交给内核前校验 seal，**带 Apple T2 安全芯片的 Intel Mac 上是 bootloader 把测量值与签名转交内核、由内核在挂根文件系统之前校验**。同一页末尾另有一节专门讲「带 T2 的 Mac」，说明在那类机器上只有 macOS 自身受 SSV 保护、校验 macOS 的 T2 侧软件由 secure boot 保护。

**该页没有给出「非 T2 Intel Mac」的校验路径。** 我们的目标平台是 `VMM-x86_64`（`71` 第 4.1 节，该 board-id 在 25G325 的 `SupportedBoardIds` 里），一台 paravirtual KVM guest，**没有 T2**（`77` 第 E.3 节已据 `cryptex1 chips unavailable, skipping verification` 判定无 SEP/协处理器）。`INFERRED`：非 T2 Intel 上没有封印校验方。查清方法在本文第 C.2 节与 `80` 的 E0-L1：把一个**故意破封**的快照 bless 上去，看它起不起来。

**野外佐证（本轮核实，`KNOWN`）：OpenCore Legacy Patcher 的 root patch 流程在 Intel 上确实是「挂读写 system volume → 改文件（封印破）→ 建新快照 → bless」，而且能启动。** 核实方式是直接读它的源码，不是读文档：

- `opencore_legacy_patcher/sys_patch/mount/mount.py` 的 `_mount_root_volume()`：Big Sur 及以后走
  `mount -o nobrowse -t apfs /dev/<diskNsM> /System/Volumes/Update/mnt1`，
  其中 `<diskNsM>` 由 `diskutil info -plist /` 取 `DeviceIdentifier`、在 `APFSSnapshot == True` 时去掉末两个字符得到。**这与 `75` 第 2.3.3 节用 `sed` 剥快照后缀的做法是同一件事，两边互为印证。**
- `opencore_legacy_patcher/sys_patch/mount/snapshot.py` 的 `APFSSnapshot.create_snapshot()`：
  - `arm64`（或 Rosetta 下）走 `bless --mount <mnt> --create-snapshot`
  - **其余（即 Intel）走 `bless --folder <mnt>/System/Library/CoreServices --bootefi --create-snapshot`**
- 同一文件的 `revert_snapshot()` 走 `bless --mount <mnt> --bootefi --last-sealed-snapshot`，即「回到上一个 Apple 签过的封印快照」是一条独立的、可逆的操作。
- 它还记录了一条确定的失败字符串：`Can't use last-sealed-snapshot or create-snapshot on non system volume`。**这是 `bless --create-snapshot` 对目标卷 role 的硬门禁**，本文第 A.3 节与第 C.1 节都用到它。

来源：<https://github.com/dortania/OpenCore-Legacy-Patcher>（`opencore_legacy_patcher/sys_patch/mount/` 下的 `mount.py` 与 `snapshot.py`）。内容已转述以符合许可限制。

**OCLP 的 Intel 分支就是本文第 A.9 与 A.10 节要写的那两步。** 它每天在成千台 Intel Mac 上跑，所以「破封的自建快照在 Intel 上能启动」这件事不需要我们去赌。

### 0.3 必须在 macOS 上装配的四条真实理由

`75` 第 0.0 节已确立工具侧的事实（`mkapfs` 只建单个卷、`linux-apfs-rw` 自报 "expect data corruption"、`apfs-fuse` 只读且不支持 firmlink、Paragon 的快照只读）。本节把它收紧成四条**具体缺什么**：

| # | 缺的能力 | 为什么非它不可 | 标签 |
|---|---|---|---|
| 1 | **卷 role** | `diskutil apfs addVolume … -role <roles>`，`<roles>` 取值集是 `B\|R\|V\|I\|T\|S\|D\|U\|N\|E\|X\|H\|L\|C\|Y\|G`（`76` 第 1.2 节）。role 是容器超级块里的元数据位，不是文件内容。Linux 侧的 APFS 实现没有 role 这个概念，连读都不解释它 | `KNOWN` |
| 2 | **volume group** | System 与 Data 必须 `-groupWith` 成一个 APFS Volume Group。`diskutil(8)` 对 group 的定性：它的首要用途正是「实现 System-role 与 Data-role 两个卷在功能上关联（**叠加的文件命名空间**、共享 crypto 信息）而在安全/备份/软更上分离的 macOS 安装」（转述自 <https://keith.github.io/xcode-man-pages/diskutil.8.html>）。group ID 是一个 UUID，而**Preboot 的 per-volume-group 目录名就是它**（第 A.6 节） | `KNOWN` |
| 3 | **firmlink** | `/usr/share/firmlinks` 定义的那套双向目录绑定。`apfs-fuse` 的 README 明说不支持（`75` 第 0.0 节）。本文第 A.5 节给出该文件在 payload 里的确切形态 | `KNOWN` |
| 4 | **decmpfs / AppleFSCompression** | 见下。**这一条本轮做了全量核实，结论与通常的说法不同，必须单独写。** | `KNOWN` |

#### 0.3.1 第 4 条的核实结果：真正的杀手不是「丢了压缩」，是「标志与内容不一致」

任务点名要核实三件事：payload 里带 `AFT` 标记的条目有多少、`ditto` 是否真的保留、不保留的后果是什么。逐条回答，全部 `KNOWN`，依据是本轮对 `analysis/binaries/macos26-25G325-x86_64/payloadv2-full-index.tsv.zip` 的 **458,715 条**索引做的全量统计（该索引由 `tools/scan.py` 生成，列为 `logical_path / type / data_bytes / mode / bsd_flags / decmpfs_type / xattr_bytes / source_payload`，其中 `decmpfs_type` 一列就是 YAA 条目头的 `AFT` 字段）。

**（a）规模：约一半的文件、七成的字节。**

| 项 | 值 |
|---|---:|
| 索引总条目 | 458,715 |
| 其中常规文件（`type == F`） | 272,090 |
| **带 `AFT` 的文件** | **133,933** |
| 占常规文件数 | **49.22%** |
| 常规文件字节合计 | 19,259,872,224 |
| **带 `AFT` 的文件字节合计** | **13,841,156,735** |
| 占文件字节 | **71.87%** |
| `AFT` 取值直方图 | `8` → 105,020 个；`9` → 28,913 个（**只有这两个值**） |

对照 `75` 第 0.0 节已记录的资产字段：`_UnarchivedSize = 19,211,607,040`（与上表 19.26 GB 的文件字节合计吻合，说明索引覆盖了全部内容），而 **`InstallationSize-Snapshot = 5,553,249,931`**，即装完之后那个封印快照只有 5.55 GB。**19.26 GB 的内容压进 5.55 GB 的快照，压缩不是锦上添花。**

**（b）`FLG` 与 `AFT` 严格同步，全量零例外。** 这是本节最重要的一条，而它此前没有人写下来。

`UF_COMPRESSED = 0x00000020`，`SF_RESTRICTED = 0x00080000`（即 SIP 的 rootless 标志）。对 272,090 个常规文件逐条核对 `bsd_flags` 的 `0x20` 位与 `decmpfs_type` 是否同时存在：

| `UF_COMPRESSED` | 有 `AFT` | 条目数 |
|---|---|---:|
| 否 | 否 | 138,157 |
| **是** | **是** | **133,933** |
| 是 | 否 | **0** |
| 否 | 是 | **0** |

`bsd_flags` 直方图：

| 值 | 含义 | 条目数 |
|---|---|---:|
| `0x0` | 无标志 | 1,650 |
| `0x80000` | `SF_RESTRICTED` | 136,507 |
| `0x80020` | `SF_RESTRICTED \| UF_COMPRESSED` | 124,469 |
| `0x20` | `UF_COMPRESSED` | 9,464 |

顺带一个数：**260,976 个文件（95.92%）带 `SF_RESTRICTED`**。这一位也必须铺对，见第 A.4 节。

**（c）所以后果分成两种，严重程度差一个数量级。**

| 做法 | 结果 | 标签 |
|---|---|---|
| **完全不压缩**：写解压内容，**并且不置 `UF_COMPRESSED`** | **能读、能启动。** decmpfs 对 `read(2)` 是透明的，一个未压缩存储的 `/System` 文件与压缩存储的读出来一模一样。代价是**体积**：第 A.4 节的容量预算要按未压缩算 | `INFERRED`（机制层面确定；「能启动」待第 C.2 节实测） |
| **照抄 `FLG` 但没有有效的 `com.apple.decmpfs`**：写解压内容，却把 `0x80020` 原样 `chflags` 上去 | **133,933 个文件变成不可读**（内核按 `UF_COMPRESSED` 去找 decmpfs xattr，找不到就按 0 长度处理）。**这才是「装完起不来」** | `INFERRED`，但机制明确 |

**而这批文件里有什么，决定了第二种做法的后果有多硬：**

| 路径 | 字节 | `AFT` | 后果 |
|---|---:|---|---|
| `System/Library/KernelCollections/SystemKernelExtensions.kc` | 369,213,440 | **8** | System KC 读不出来。`71` 第 4.3 节的两个 board-id 门（`AppleIntelMCEReporter`、`AppleGraphicsDevicePolicy`）都在这个 KC 里 |
| `System/Library/Kernels/kernel` | 19,008,056 | **8** | 内核本体 |
| `usr/share/firmlinks` | 689 | **8** | firmlink 表读不出来，Data 卷绑不上（第 A.5 节） |

**（d）一条可以当判据用的规律：凡是内核起来之前要被读到的件，payload 里一律没有 `AFT`。** `KNOWN`，本轮逐条核对，零例外：

| 路径 | 字节 | `bsd_flags` | `AFT` | 源 payload |
|---|---:|---|---|---|
| `usr/standalone/i386/boot.efi` | 723,512 | `0x80000` | **无** | `payload.041` |
| `System/Library/CoreServices/boot.efi` | 723,512 | `0x80000` | **无** | `payload.038` |
| `usr/standalone/i386/apfs.efi` | 745,912 | — | **无** | — |
| `usr/standalone/i386/apfs_aligned.efi` | 751,108 | — | **无** | — |
| `System/Library/KernelCollections/BootKernelExtensions.kc` | 67,584,000 | — | **无** | — |
| `System/Library/CoreServices/SystemVersion.plist` | 604 | `0x80000` | **无** | `payload.050` |
| `System/Library/CoreServices/PlatformSupport.plist` | 790 | `0x80000` | **无** | `payload.050` |
| **`usr/standalone/` 整棵树（104 个文件）** | — | — | **全部无** | — |

而内核起来之后才读的件可以压缩：`System/Library/Kernels/kernel`（`AFT=8`）、`SystemKernelExtensions.kc`（`AFT=8`）、`usr/share/firmlinks`（`AFT=8`）。

**`System/Library/Kernels/kernel` 带 `AFT` 这件事看起来矛盾，其实是一条印证。** macOS 11+ 的 `boot.efi` 加载的是 `BootKernelExtensions.kc`（一个 `MH_FILESET`，内含内核本体与 204 条 fileset 条目，`71` 第 3.1 节），**不是** `System/Library/Kernels/kernel`。所以 Boot KC 必须未压缩（EFI 阶段的 `apfs.efi` 读不了 decmpfs），而 `Kernels/kernel` 只是给 `kmutil` 重建 KC 用的素材，可以压缩。`INFERRED`，但它让上面那条规律自洽。

**（e）`ditto` 的真实行为：它是对的工具，但不是因为「保留」。** 核实方式是读 `ditto(1)` 手册（转述自 <https://keith.github.io/xcode-man-pages/ditto.1.html>）：

| 选项 | 手册语义 | 对我们 |
|---|---|---|
| `--preserveHFSCompression` | **默认行为**。把**源文件本来就在用**文件系统压缩的那部分，在目标是支持压缩的 HFS+/APFS 卷时保留下来 | **用不上。** 我们的源是解出来的 payload 内容，归档里存的是**解压后**的字节（`AFT` 只是一个标志），源端没有压缩可供「保留」 |
| **`--hfsCompression`** | 拷贝文件或从归档解内容时，若目标是支持文件系统压缩的 HFS+ 或 APFS 卷，**则在适当时压缩全部内容**；手册明说它**只打算用于涉及系统文件的安装与备份场景** | **这才是我们要的那一个。** 它的用途描述与我们的场景逐字对上 |
| `--nohfsCompression` | 默认，不压缩 | 不要 |
| `--persistRootless` | 被替换的文件若带 `SF_RESTRICTED` 或 `com.apple.rootless` xattr，即使源文件没有也保留 | 第 A.4 节用它处理 95.92% 的 `SF_RESTRICTED` |
| `--rsrc` / `--extattr` / `--acl` / `--qtn` | 10.4/10.5 起全部是默认 | 默认即可，不要设 `--norsrc` |
| `--clone` / `--noclone` | 是否尝试 clone 拷贝 | 目标是另一个卷，clone 不跨卷，无影响 |

**所以第 4 条的正确表述是：`ditto` 会，`cp` 不会 —— 但「会」的是 `ditto --hfsCompression` 去「创建」压缩，不是 `ditto` 默认去「保留」压缩。** 照抄「`ditto` 默认就保留了」这句话会得到一块 19 GB 而不是 5.5 GB 的 System 卷，装得下就还能起来，装不下就连铺内容都失败。

**（f）`cp` 的危险在哪，说准一点。** macOS 的 `cp` 自 10.5 起默认拷贝 xattr（`-X` 才是「不拷」）。但 `com.apple.decmpfs` 是受保护的系统 xattr：不带 `XATTR_SHOWCOMPRESSION`（`0x0020`）标志时 `getxattr(2)` 看不见它，普通用户态也不能把它 `setxattr` 上去。所以 `cp` 既拿不到也写不回压缩，**它的产物是「解压内容 + 没有 `UF_COMPRESSED`」，即上表的第一种后果（能起来，变大），不是第二种。** `INFERRED`，查清方法见第 D 节与 `V-004`。

**真正能制造第二种后果的，是我们自己写的铺内容脚本：先 `ditto`（不带 `--hfsCompression`），再把索引里的 `FLG` 原样 `chflags` 回去。** 这是一个非常自然、而且会一次性毁掉 133,933 个文件的写法。第 A.4 节与第 B 节第 7 步把它列为明令禁止。

**（g）`AFT` 的 `8` 与 `9` 分别是哪种压缩，未确证。** `INFERRED`。常见的 decmpfs `compression_type` 编号里 7/8 一组、9/10 一组分别对应「xattr 内联」与「resource fork」两种存放位置，但本项目**没有**对 25G325 的 APFS 实现核对过这个映射，所以不写进规格。**这不阻塞任何事**：我们不自己构造 decmpfs xattr，压缩交给 `ditto --hfsCompression` 决定。查清方法在第 D 节（在运行器上对一组已安装的文件用 `XATTR_SHOWCOMPRESSION` 读出 `com.apple.decmpfs` 的前 16 字节，解出 magic `fpmc` 后面那个 u32），登记为 `V-005`。

### 0.4 与已有分册的分工

本文**不重复**以下内容，需要时按编号引用：

| 分册 | 已经写了什么 | 本文怎么用 |
|---|---|---|
| `71-IMAGE-OPENCORE.md` | 第 1 节素材形态（`SharedSupport.dmg` → HFS+ → zip → `payloadv2/payload.000…052`）、第 3 节 25G325 自带的驱动、第 4 节 SMBIOS 与 board-id 门、第 6 节 `config.plist` | 第 A.4 节的内容来源、第 A.6 节的 `PlatformSupport.plist` 门禁 |
| `75-IMAGE-PREBAKE.md` | **第 0.0.1 节（1.2 修订）已把装配定成单 job 全 CI、两分区、Alpine 住 ESP**，并给了 `gpt create`/`gpt add`/`newfs_msdos` 的序列 | **第 A.1 节直接接那个序列。本文不另造分区方案** |
| `76-BOOT-LAYOUT-PICKER.md` | 第 1.2 节卷角色全表、第 1.3 节启动链、**第 1.4 节「必需烘四个：Preboot + System + Data + VM」**、第 1.5 节 Recovery 三问 | 第 A.3、A.7、A.8 节的裁决直接沿用 |
| `77-UPDATEBRAIN-ABI.md` | UpdateBrain 的接口与 `MSUTargetController` / `LPStaticAPFSVolume` / `MSUBootObjectCopier` / `MSUMigrationHelper` 的方法 RVA | **第 B 节的步骤顺序按它的方法名反推**，见第 B.1 节的对照表 |
| `80-TEST-HARNESS.md` | 第 4.1 节 E0-L1 的定义与验收 | 第 C.2 节把只能启动才知道的事指过去 |
| `00-OVERVIEW.md` | 第 7 节证据标签规则 | 全文 |

### 0.5 结论先行

1. **「卷 + 快照 + bless + Preboot」这四件事里，前三件现在就能写出完整命令序列；第四件（Preboot）能写出机制与三条独立的生成途径，但写不出确切的文件清单。** 文件清单要一轮 CI 取证，见第 D 节与第 E 节。
2. **Preboot 此前被当成黑箱，这一轮它不再是。** 本轮从 `diskutil(8)` 手册里取到三条此前没人引用过的事实：`bless --bootefi` 在带 `--create-snapshot` 时的语义是「拷贝所需的 boot objects」；`diskutil apfs updatePreboot <vol>` 是一个专门用来**为指定卷更新其配套 Preboot 卷**的动词；`diskutil apfs convert -prebootSource <staging dir>` 把 Preboot 的内容定性为「**你自己的一个 macOS boot items 暂存目录**」，并会自动往里补「cryptographic 与 EFI rendering」两类件。见第 A.6 节。
3. **`boot.efi` 的来源已经确定，不需要取证。** payload 里只有两份 `boot.efi`，都是 723,512 字节：`System/Library/CoreServices/boot.efi`（`payload.038`）与 `usr/standalone/i386/boot.efi`（`payload.041`）。两者大小逐字节相同。`usr/standalone/i386/` 整棵树（104 个文件，含 `apfs.efi`、`apfs_aligned.efi`、`Firmware.scap`、`EfiLoginUI/*.efires`）是 Preboot 的 boot objects 的素材库，而且**全部未压缩**。
4. **`.disk_label` / `.disk_label_2x` 不在 payload 里，一条都没有。** `KNOWN`，在 458,715 条路径里检索 `disk_label` 零命中。它们是 `bless --label` / `--labelfile` **渲染**出来的，不是拷过去的。
5. **Data 卷的骨架在 payload 里，`System/Library/Templates/Data/**` 共 18,731 条。** 不需要我们编。
6. **`/usr/share/firmlinks` 在 payload 里（689 字节，`0444`，`FLG=0x80020`，`AFT=8`，`payload.052`）**，另有一份副本在 `System/Library/PrivateFrameworks/SystemMigration.framework/Versions/A/Resources/firmlinks`（680 字节，`payload.051`）—— 后者极可能就是 `-[MSUMigrationHelper createFirmlinks]`（RVA `0x11aade`）读的那一份。
7. **Recovery 卷不要，这一条已定且本文确认。** `76` 第 1.4、1.5.3 节已论证：启动链里没有一环读它；OpenCore 的 boot algorithm 明确支持「有 primary 没有 alternate」。本文第 A.7 节只补「不要它」的确切后果清单。
8. **`bless --setBoot` 在本项目里是禁止动作，不是「尽量避免」。** 它改的是**运行器自己的固件启动项**（`77` 第 E.1 节已记录 UpdateBrain 的 APPLY 相位就是这么干的）。第 A.10 节与第 B 节的脚本里都有显式护栏。
9. **第 4 条（decmpfs）的核实结论推翻了它原本的叙述方式**：丢掉压缩不会让系统起不来，只会让它变大三倍以上；让系统起不来的是把 `UF_COMPRESSED` 标志铺上去而内容没压。见第 0.3.1 节。
10. **裁决落在第二档：不够，但缺的全在第 D 节的取证范围内，一轮 CI 就能补齐。** 见第 E 节。

---
## A. 规格：一块能启动的盘上必须有什么

逐层给出。每层标明**必需 / 可选 / 不要**，并说明省掉的后果。

### A.0 全图

```text
macos-golden.raw                 GPT，虚拟容量 16 GB（下限见 A.4.5）
├─ p1  EFI System Partition      C12A7328-F81F-11D2-BA4B-00A0C93EC93B
│      FAT32，512 MiB，label OPENCORE
│      内容按 75 §0.0.1 + 76 §3.2 组装（本文不碰）
└─ p2  Apple APFS                7C3457EF-0000-11AA-AA11-00306543ECAC
       余下全部，一个 APFS Container
       │
       ├─ 卷 role S  "Macintosh HD"          ← 封印只读系统卷   【必需】
       │    └─ 快照 com.apple.os.update-*     ← 实际被引导的根  【必需】
       ├─ 卷 role D  "Macintosh HD - Data"   ← 可写卷           【必需】
       │    与 role S 同属一个 APFS Volume Group（UUID = VG_UUID）
       ├─ 卷 role B  "Preboot"               ← 启动链第一环     【必需】
       │    └─ <VG_UUID>/                     ← 见 A.6
       ├─ 卷 role V  "VM"                    ← swap            【必需，内容空】
       └─ 卷 role R  "Recovery"              ← 【不要】见 A.7
```

**四个必需卷里，只有 role S 和 role D 进 volume group。** `KNOWN`，依据是 `76` 第 1.2 节引的 Apple 官方页面：Preboot、VM、Recovery 三个卷是**共享的、不随额外的系统卷复制**。即它们是容器级的、每容器一份，不是每 volume group 一份。所以建它们时**不要**给 `-groupWith`。这一条很容易写错，写错的后果见第 A.3.4 节。

### A.1 GPT 层 【必需】

**几何接 `75` 第 0.0.1 节，一个数不改。工具换掉了：不能用 `gpt`。**

| 项 | 值 | 标签 |
|---|---|---|
| 分区表 | GPT。**用 `tools/ci/mkgpt.py` 离线写进镜像文件**，不用 `/usr/sbin/gpt`，也不用 `diskutil partitionDisk` | `TESTED(25G76)` |
| p1 起始扇区 | `2048`（1 MiB 对齐） | `TESTED(25G76)` |
| p1 长度 | `512 MiB / 512 = 1048576` 扇区 → 止于 LBA `1050623` | `TESTED(25G76)` |
| p1 类型 | `C12A7328-F81F-11D2-BA4B-00A0C93EC93B`（ESP）。`diskutil list` 回读显示 `EFI` | `TESTED(25G76)` |
| p2 起始扇区 | `2048 + 1048576 = 1050624` | `TESTED(25G76)` |
| p2 长度 | 吃到 last usable LBA，尾部按 1 MiB 向下取整 | `TESTED(25G76)` |
| **p2 写入时的类型** | **`48465300-0000-11AA-AA11-00306543ECAC`（Apple_HFS）** ← 见下面的约束 3 | `TESTED(25G76)` |
| **p2 建完容器后的类型** | `7C3457EF-0000-11AA-AA11-00306543ECAC`（Apple APFS），**由 `createContainer` 自己改** | `TESTED(25G76)` |
| 收尾 | **不需要** `gpt recover`：`mkgpt.py` 一次就把备份头与备份项数组写在真实盘尾 | `TESTED(25G76)` |

#### A.1.0 为什么不能用 `gpt`：`V-030` 的实测结果

run `41274204499` 的 `D0-rawdev-permission.txt` 把「到底什么被拒了」拆成七条逐个量，
运行器 `whoami = runner`、`sudo -n` 可用、`csrutil status = disabled`、
目标是 `hdiutil attach -nomount` 刚挂上的 4 GiB 空镜像（`Virtual: Yes`、`Media Read-Only: No`）：

| 探针 | 结果 |
|---|---|
| `sudo dd if=/dev/rdiskN` 读 1 扇区 | `rc=0` |
| `sudo dd if=/dev/diskN` 读 1 扇区 | `rc=0` |
| `sudo dd of=/dev/rdiskN` 写 1 扇区 | **`rc=0`** |
| `sudo dd of=/dev/diskN` 写 1 扇区 | **`rc=0`** |
| `sudo gpt -r show /dev/rdiskN` | `rc=0`，正常输出 |
| `sudo gpt create -f /dev/rdiskN` | `rc=1` `operation not permitted: create` |
| `sudo gpt create -f /dev/diskN` | `rc=1` 同上 |
| `diskutil unmountDisk force` 之后再 `gpt create` | `rc=1` 同上 |
| **不带** `sudo` 的 `dd` 写 | `rc=0` |
| **不带** `sudo` 的 `gpt create` | `rc=1` 同上 |

**结论（`TESTED(25G76)`）：这不是权限问题，是 `gpt(8)` 自己的护栏。**
裸设备写入在这台机器上是允许的 —— 所以 `newfs_msdos`、`asr`、`dd` 这些都不受影响
（`newfs_msdos` 在同一轮已实测成功，见第 A.1.2 节）。被禁的只有 `gpt` 的修改类子命令。
野外有同样的报告：Ventura 起 `gpt` 除 `show` 以外的子命令一律返回
`operation not permitted`，加 `sudo`、进 root shell、卸载磁盘、关 SIP 都无效
（<https://apple.stackexchange.com/questions/460191/gpt-operation-not-permitted-in-ventura>，
内容已改写以符合许可要求）。

**所以 `75` 第 0.0.1 节与本节的分区表一步改成离线写。** 分区表就是文件头部的几个扇区，
在 `hdiutil attach` **之前**以普通文件写入即可；普通文件不受这条护栏约束，也不需要 `sudo`。
`hdiutil attach` 之后 MediaKit 解析这张表并给出 `/dev/diskNs1`、`/dev/diskNs2` —— 这一步
run `41274204499` 已实测通过，`diskutil list` 的回读是：

```text
/dev/disk2 (disk image):
   #:                       TYPE NAME                    SIZE       IDENTIFIER
   0:      GUID_partition_scheme                        +4.3 GB     disk2
   1:                        EFI                         536.9 MB   disk2s1
   2:                  Apple_HFS                         3.8 GB     disk2s2
```

而 `gpt -r show` 对同一块盘的回读证实四套元数据都在规范位置上：

```text
    start     size  index  contents
        0        1         PMBR
        1        1         Pri GPT header
        2       32         Pri GPT table
       34     2014
     2048  1048576      1  GPT part - C12A7328-F81F-11D2-BA4B-00A0C93EC93B
  1050624  7337944      2  GPT part - 7C3457EF-0000-11AA-AA11-00306543ECAC
  8388568        7
  8388575       32         Sec GPT table
  8388607        1         Sec GPT header
```

（第 2 行的类型已经是 APFS，因为这份回读是在 `createContainer` 之后取的 —— 这同时就是
约束 3 的证据。）

#### A.1.1 可照抄的分区表一步

```bash
# 几何与 75 §0.0.1 相同；工具换成 mkgpt.py。IMG 是还没 attach 的普通文件。
python3 tools/ci/mkgpt.py create "$IMG" \
        --size "$TOTAL_BYTES" \
        --part "auto:$((512*1024*1024)):efi:EFI" \
        --part "auto:auto:hfs:Macintosh HD"      # ← 注意是 hfs 不是 apfs，见约束 3

# 独立复核（它会重新从字节解析，核对两个头的 CRC、项数组 CRC、几何、边界、重叠）
python3 tools/ci/mkgpt.py verify "$IMG"

# 之后才 attach。-nomount 是必须的：此刻 p2 还只是一个声称自己是 HFS+ 的空分区。
DEV=$(hdiutil attach -imagekey diskimage-class=CRawDiskImage -nomount "$IMG" \
      | awk '/^\/dev\/disk/{print $1; exit}')
```

`mkgpt.py` 的正确性由三层守住，全部在 `check.yml` 里是必过项：
UEFI 2.x 规范里已知的 GUID 混合字节序向量与 CRC32 向量、几何断言与 1 字节篡改必须被检出的
往返测试、以及 `gptdump.py` 的哑读复核（它不复用 `mkgpt.py` 的任何常量，所以不会和它犯同一个错）。
**最终判据仍然是 MediaKit 认不认**，而这一条已经实测通过。

**三条本文追加的约束：**

1. **APFS 分区必须是最后一个。** `73` 第 4.6.2 节的首启扩容是 `diskutil apfs resizeContainer <PHYS> 0`，`0` 的语义是吃到下一个分区或分区表末尾。p2 之后没有分区，所以它能一直扩到盘尾。`KNOWN`（`76` 第 3.1 节同一约束）。
2. **分区表离线写进文件；铺文件系统内容对 `disk`/`rdisk` 节点做。** 原先这一条说的是「写 GPT 必须对 `rdisk` 裸设备做」，已被第 A.1.0 节推翻。裸设备这一侧仍然有一条真实的区分：`newfs_msdos` 要 `rdisk` 的**分区**节点（`${DEV/disk/rdisk}s1`），`diskutil mount` 要缓冲设备。
3. **p2 在写分区表时必须写成 `Apple_HFS`，不能写成 APFS。** 这一条与 1.0 的写法完全相反，依据是实测：

   | p2 写入时的类型 | `diskutil apfs createContainer "${DEV}s2"` 的结果 |
   |---|---|
   | `7C3457EF-…`（Apple APFS） | **`Error: -69614: The disk is already in use by APFS`** |
   | `48465300-…`（Apple_HFS） | 成功。打印 `Switching disk2s2 to APFS` / `Created new APFS Container disk3`，并**自己把 GPT 里 p2 的类型改成 `7C3457EF-…`** |

   解释：`createContainer` 看见分区已经声称自己是 APFS，就去找那里的容器超级块；
   找不到（分区是空的）于是报「已被 APFS 占用」而拒绝覆盖。这是一条防误删的保护，
   不是缺陷。**所以 `V-001` 的答案是「`createContainer` 确实替我们改类型，而且必须由它改」。**
   `TESTED(25G76)`。

#### A.1.2 ESP 上的 FAT32：`V-029`，两条路都通，但只有一条能用

1.0 从没问过「ESP 的文件系统怎么建」。run `41274204499` 把两条路都试了，**两条都返回 0，
但其中一条会毁掉 ESP 的分区类型 GUID**：

| 路 | 命令 | 退出码 | 副作用 |
|---|---|---|---|
| **a（用这条）** | `sudo newfs_msdos -F 32 -v EFI "${DEV/disk/rdisk}s1"` | `0` | 无。GPT 里 p1 的类型仍是 `C12A7328-…` |
| b（不要用） | `sudo diskutil eraseVolume FAT32 EFI "${DEV}s1"` | `0` | **把 p1 的类型改成了 `Microsoft Basic Data`**（回读 `Partition Type: Microsoft Basic Data`） |

`newfs_msdos` 的回显（`TESTED(25G76)`，1 MiB 对齐的 512 MiB 分区）：

```text
512 bytes per physical sector
/dev/rdisk2s1: 1046496 sectors in 130812 FAT32 clusters (4096 bytes/cluster)
bps=512 spc=8 res=32 nft=2 mid=0xf8 spt=32 hds=128 hid=2048 drv=0x80
bsec=1048576 bspf=1022 rdcl=2 infs=1 bkbs=6
```

**为什么路 b 有害：** 固件只在分区类型是 `C12A7328-F81F-11D2-BA4B-00A0C93EC93B` 时才把
那个分区当 ESP 去找 `\EFI\BOOT\BOOTX64.EFI`（`74` 第 2 节的 shim 就放在那里）。
类型变成 MS Basic Data 之后，OpenCore 连被加载的机会都没有，而**症状是「固件直接跳过这块盘」**，
与 `76` 第 1.3 节判据 1 失败时的表现一样难归因。

**写进第 B 节的规则：ESP 一律用 `newfs_msdos -F 32`，禁止 `diskutil eraseVolume` 碰 p1。**
若一定要用 `diskutil`，必须在之后重写 p1 的类型 —— 而 `gpt` 又不能用（第 A.1.0 节），
那就只能 detach、用 `mkgpt.py` 重写整张表、再 attach。所以这条退路实际上不存在。

#### A.1.3 与 `76` 第 3.1 节的分区数差异，必须在这里说清

`76` 第 3.1 节写的是**三分区**（p1 ESP / p2 BaseSystem 1600 MiB / p3 APFS），`75` 第 0.0.1 节写的是**两分区**（p1 ESP 512 MiB / p2 APFS）。`76` 第 6.5 节的 `75-A` 条又建议把 `75` 改成三分区。**这两条修订是同一轮交叉产出的，时间上 `75` 的 1.2 修订在后。**

**本文按两分区走**，理由是任务明确要求「接 `75` 第 0.0.1 节的序列，不要另造分区方案」。

**这个选择对本文的其余部分零影响**，因为 BaseSystem 分区是一个**纯插入**：它插在 ESP 与 APFS 之间，APFS 仍然是最后一个，起始扇区从 `1050624` 变成 `1050624 + 1600 MiB/512`。本文第 A.2 节以后的一切都是容器内部的事，与分区序号无关。所以：

> **把 BaseSystem 分区加回来是一条两行改动**（多一次 `gpt add`、把 `APFS_START` 加上 `3276800`），而且本文第 B 节的脚本用 `${DEV}s${APFS_PART}` 变量而不是写死 `s2`，就是为了让这条改动不触碰别的地方。

两分册的最终分区数登记为 `V-002`，由 `75` 或 `76` 下一轮修订定版，**不由本文定**。

### A.2 APFS container 层 【必需】

```bash
sudo diskutil apfs createContainer "${DEV}s${APFS_PART}"
```

| 参数 | 我们给什么 | 理由 | 标签 |
|---|---|---|---|
| Physical Store | **单个分区**，`${DEV}s2` | `diskutil(8)`：指定的 device 成为 APFS Physical Stores。多 store（fusion）需要 `-main` / `-secondary` | `KNOWN` |
| fusion / 多物理存储 | **不要** | fusion 是「SSD + HDD 两块物理盘」的拼法。我们是一个磁盘镜像文件，只有一块。多给一个 store 等于要求目标机器也有两块盘 | `KNOWN` |
| 块大小 | **不指定** | `diskutil apfs createContainer` 没有块大小参数。APFS 的块大小由实现决定（在 4 KiB 量级），而且**没有任何已知的启动期依赖** | `KNOWN`（手册里无此参数）/ `INFERRED`（无启动依赖） |
| 容器大小 | **= 分区大小**，不指定 | 容器吃满它的 physical store | `KNOWN` |
| 加密 | **不要** | `71` 第 6.6.2 节 `AuthRestart = false`，研发期不用 FileVault。而且 Apple 官方说明 macOS 11+ 系统卷不再需要加密（SSV 提供等价的静态保护，转述自 <https://support.apple.com/guide/security/secd698747c9/web>） | `KNOWN` |
| defragment | **不动**（默认） | `diskutil apfs defragment` 是容器/卷级的后台整理开关。与启动无关 | `KNOWN` |

**省掉这一层的后果：没有容器就没有卷，不可引导。**

**拿到容器引用 disk 号的办法**（它是一个 APFS 合成的 whole-disk，号码是任意的）：

```bash
# 首选：从 physical store 分区的 info 里读
CNT=$(diskutil info -plist "${DEV}s${APFS_PART}" \
      | plutil -extract APFSContainerReference raw -o - - 2>/dev/null)
# 退路：createContainer 自己会打印 "Created new APFS Container with disk identifier diskN"
#       所以也可以把它的 stdout 抓下来 grep
```

**`V-003` 已关闭：`APFSContainerReference` 就是正确的键名。** `TESTED(25G76)`，两处独立取到：

```text
# 运行器自己的盘（volumes job，23-container-ref.txt）
== physical store candidate: disk0s2
  "APFSContainerReference" => "disk1"
  "Content" => "Apple_APFS"
  "DeviceIdentifier" => "disk0s2"

# scratch 镜像（tooling job，B4-scratch.txt）
  "APFSContainerReference" => "disk3"
  "DeviceIdentifier" => "disk2s2"
```

退路（抓 `createContainer` 的 stdout）仍然成立，实测回显是
`Created new APFS Container disk3` —— 注意**没有** "with disk identifier" 这几个字，
1.0 写的那个串对不上，所以退路的 grep 要按 `Created new APFS Container ([a-z0-9]+)` 写。

### A.3 卷层 【四个必需，一个不要】

#### A.3.1 四个卷的参数表

| # | 卷名 | role | filesystem | case | reserve | quota | volume group | 建完挂不挂 |
|---|---|---|---|---|---|---|---|---|
| 1 | `Macintosh HD` | **`S`** | `APFS` | **不敏感** | 无 | 无 | 本组的锚 | `-nomount` |
| 2 | `Macintosh HD - Data` | **`D`** | `APFS` | 不敏感 | 无 | 无 | **`-groupWith <卷1>`** | `-nomount` |
| 3 | `Preboot` | **`B`** | `APFS` | 不敏感 | 无 | 无 | **不进组** | `-nomount` |
| 4 | `VM` | **`V`** | `APFS` | 不敏感 | 无 | 无 | **不进组** | `-nomount` |

逐列的理由：

- **`filesystem` 必须是 `APFS` 而不是 `Case-sensitive APFS`。** `diskutil(8)` 说这个参数设定「该卷的**永久** APFS personality」，取值应当给 `APFS` 或 `Case-sensitive APFS`（转述自手册）。「永久」意味着建错了只能删卷重建。Apple 默认安装用的是**大小写不敏感**，而 macOS 的系统内容里存在只差大小写的路径依赖。`INFERRED`：敏感卷上装 macOS 虽然被支持，但偏离出厂形态，没有任何好处。查清方法在第 D 节（读运行器自己 `/` 的 case sensitivity）。登记为 `V-006`。
- **`reserve` 与 `quota` 一律不给。** `diskutil(8)` 对两者的定性：reserve 是「有保证的最小容量」，quota 是「最大容量上限」，两者都是为了在同一容器里的多个卷之间做公平性管理。我们容器里只有自己的四个卷，而且 `73` 第 4.6.2 节的首启扩容会把容器扩满 —— **给了 quota 反而会让扩容白做**。
- **`-nomount` 四个全给。** 建完立刻挂载是 `addVolume` 的默认行为，而我们要挂的位置是自己选的（第 B 节用 `/System/Volumes/Update/mnt1` 一类路径）。默认挂到 `/Volumes/<名字>` 会和运行器自己的卷名撞。

#### A.3.2 确切的命令序列

```bash
#!/usr/bin/env bash
# A.3 卷层。前提：A.2 已建好容器，$CNT 是容器引用 disk 号。
set -euo pipefail
CNT="${1:?container reference disk, e.g. disk8}"

vol_of() {   # vol_of <卷名> -> diskNsM
  diskutil apfs list -plist "$CNT" >/dev/null 2>&1 || true
  diskutil list "$CNT" | awk -v n="$1" '
    $0 ~ ("APFS Volume " n " ") { print $NF }' | head -1
}

# ---- 1. System。必须第一个建：后面 Data 要 -groupWith 它 ----
sudo diskutil apfs addVolume "$CNT" APFS "Macintosh HD" -role S -nomount
SYS=$(vol_of "Macintosh HD"); echo "System  = $SYS"

# ---- 2. Data，与 System 成组 ----
# !! 这一条在 25G76 上实测失败：Error: -69624（见 A.3.3a，V-031）。
#    下一轮取证会从 A.3.3a 的 D2..D7 里挑出可用的变体替换它。
#    在那之前这整个脚本不可照抄运行 —— 这是 1.1 唯一的一处「已知不通」。
sudo diskutil apfs addVolume "$CNT" APFS "Macintosh HD - Data" \
     -role D -groupWith "$SYS" -nomount
DATA=$(vol_of "Macintosh HD - Data"); echo "Data    = $DATA"

# ---- 2b. 立刻验组。1.0 把这一步放在第 6 步，太晚：中间还插两次 addVolume，
#          真出错时要回溯三条命令才知道哪条坏了。
GROUPS=$(diskutil apfs listVolumeGroups "$CNT" 2>&1)
printf '%s\n' "$GROUPS"
printf '%s\n' "$GROUPS" | grep -qF "$SYS" \
  || { echo "FATAL(V-031): System 卷不在任何 volume group 里，停"; exit 1; }
printf '%s\n' "$GROUPS" | grep -qF "$DATA" \
  || { echo "FATAL(V-031): Data 卷不在 System 的组里，停"; exit 1; }

# ---- 3. Preboot。不进组（容器级共享卷）----
sudo diskutil apfs addVolume "$CNT" APFS "Preboot" -role B -nomount
PRE=$(vol_of "Preboot"); echo "Preboot = $PRE"

# ---- 4. VM。不进组 ----
sudo diskutil apfs addVolume "$CNT" APFS "VM" -role V -nomount
VM=$(vol_of "VM"); echo "VM      = $VM"

# ---- 5. 取 volume group UUID。Preboot 的目录名就是它（A.6）----
VG=$(diskutil apfs listVolumeGroups -plist "$CNT" \
     | plutil -extract Containers.0.VolumeGroups.0.APFSVolumeGroupUUID raw -o - - 2>/dev/null \
     || diskutil info "$SYS" | awk -F': *' '/Volume Group UUID/{print $2}')
echo "VG_UUID = $VG"

# ---- 6. 立刻自检。这一组任何一条不过，后面全部白做 ----
diskutil apfs list "$CNT"
diskutil apfs listVolumeGroups "$CNT"
```

**`vol_of` 用 `diskutil list` 的文本输出而不是 plist**，理由与 `75` 第 2.3.3 节同：`diskutil info -plist` 没有「按卷名查设备」这样一个键，而 `apfs list -plist` 的数组下标会随卷的建立顺序变化。文本匹配在这里更稳。`INFERRED`，第 D 节会把两种输出都落盘，确定 plist 路径后可以换成 plist 版本。

#### A.3.3 四个 role 的实测结果：担心错了对象

1.0 写的是「`-role S` 与 `-role D` 肯定能设，`-role B`/`-role V` 是未知」。
run `41274204499` 在一个 4 GiB scratch 容器上把四条逐个跑了一遍，**结果与担心的方向相反**：

| 命令 | 退出码 | 回显 | 标签 |
|---|---|---|---|
| `addVolume disk3 APFS "Macintosh HD" -role S -nomount` | `0` | `Created new APFS Volume disk3s1` | `TESTED(25G76)` |
| `addVolume disk3 APFS "Macintosh HD - Data" -role D -groupWith disk3s1 -nomount` | **`1`** | **`Error: -69624: Unable to add a new APFS Volume to an APFS Container`** | `TESTED(25G76)` |
| `addVolume disk3 APFS "Preboot" -role B -nomount` | `0` | `Created new APFS Volume disk3s2` | `TESTED(25G76)` |
| `addVolume disk3 APFS "VM" -role V -nomount` | `0` | `Created new APFS Volume disk3s3` | `TESTED(25G76)` |

**`V-007` 关闭：`-role B` 与 `-role V` 都能由我们自己设，不需要任何退路。**

与此一致的还有 `diskutil apfs addVolume` 自己打印的用法串（`TESTED(25G76)`，
这比手册更贴近这个 build）：

```text
[-role <roles>]
      <roles> = "0" or one or more of B|R|V|I|T|S|D|E|X|H|C|Y
[-group[With] | -sibling <apfsVolumeDisk>]
```

`changeVolumeRole` 的用法串同时确认了退路 R-a 存在，而且语义比手册讲得细：

```text
Usage: diskutil apfs changeVolumeRole|chrole <apfsVolumeDisk> <roles>
      <roles> = "0" or "clear" or one or more of
                b|r|v|i|t|s|d|e|x|h|c|y
                B|R|V|I|T|S|D|E|X|H|C|Y
Unspecified flags are left alone; lower case clears a flag;
upper case sets a flag; clear clears all flags; 0 is ignored.
```

即：**大写置位、小写清位、`clear` 全清、`0` 忽略，未提到的位不动**，而且动词有别名 `chrole`。

#### A.3.3a `V-031` 已解决：**Data 卷必须先建，System 卷成组到它**

> [!IMPORTANT]
> **根因是一行内核日志，建卷顺序因此整条反过来。** `TESTED(25G76)`，run `41279126720`。
> 复现 `addVolume … -role D -groupWith <sysvol>` 的同时抓统一日志，apfs 内核扩展说：
>
> ```text
> (apfs) apfs_newfs:31899: disk3s1 A Non-sealed system sibling volume is not allowed, error = 0
> (apfs) volumeCreate:5104: disk3 apfs_newfs failed with error 1
> ```
>
> 往上一层是 `storagekitd` 把它翻译成 `IntErr=49153=0xc001` 再翻成 `DMErr=-69624`，
> 而 `diskutil` 只把最后那个码印出来 —— 这就是为什么前两轮只看到一个通用错误。
>
> **APFS 不允许给一个「未封印的系统卷」创建兄弟卷。** 而我们的装配顺序是
> 「建四个卷 → 铺内容 → 最后 bless 封印」，所以建 Data 卷的那一刻系统卷必然未封印。
> 这是一个**先鸡后蛋**，而且不能靠「先封印再建 Data」解决：封印需要内容，
> 内容需要 firmlink，firmlink 需要组。
>
> **解法是把顺序倒过来：先建 Data（`-role D`，不成组），再建 System
> （`-role S -groupWith <data>`）。** 这时 `-groupWith` 的 sibling 是 Data 卷，
> 不是系统卷，上面那条检查不会触发。实测一次通过：
>
> ```text
> addVolume disk3 APFS "Macintosh HD - Data" -role D -nomount
>     → Created new APFS Volume disk3s1
> addVolume disk3 APFS "Macintosh HD" -role S -groupWith disk3s1 -nomount
>     → Created new APFS Volume disk3s2      退出码 0
>
> +-> Volume Group 3B871442-CF1B-414F-98AB-289E20108111
>     disk3s1 (Data)    Macintosh HD - Data   Volume UUID 3B871442-…-289E20108111
>     disk3s2 (System)  Macintosh HD          Volume UUID 4A6F42A8-…-C1E59827801C
> ```
>
> 之后 `-role B`（Preboot）与 `-role V`（VM）照旧成功，四个卷全齐。

**这条还顺手定死了 Preboot 那个目录的名字怎么算出来（`TESTED(25G76)`，两处独立印证）：**

> **volume group UUID == Data 卷的 Volume UUID。**
>
> - scratch 容器上：组 UUID `3B871442-CF1B-414F-98AB-289E20108111` 与 Data 卷
>   `disk3s1` 的 Volume UUID **逐字符相同**。
> - 运行器自己那块盘上：Preboot 的目录名是 `0F9D8E91-834F-3213-9298-BA3FF72476FE`
>   （第 A.6.7 节），而 `diskutil apfs list` 回报 Data 卷 `disk1s1` 的 UUID
>   **就是** `0F9D8E91-834F-3213-9298-BA3FF72476FE`。
>
> **所以 `$VG` 在建完 Data 卷的那一刻就已知**，不必等到成组之后去 `listVolumeGroups`。
> 第 A.3.2 节第 5 步因此可以简化成一条 `diskutil info <data卷>` 读 `Volume UUID`，
> 而原来那条 `plutil -extract Containers.0.VolumeGroups.0.APFSVolumeGroupUUID` 的
> 数组下标依赖（第 A.3.2 节自己也提醒过它会随建卷顺序变）就不需要了。

**修正后的建卷顺序（替换第 A.3.2 节第 1、2 步）：**

```bash
# ---- 1. Data。必须第一个建（A.3.3a：APFS 不许给未封印的系统卷建兄弟卷）----
sudo diskutil apfs addVolume "$CNT" APFS "Macintosh HD - Data" -role D -nomount
DATA=$(vol_of "Macintosh HD - Data"); echo "Data    = $DATA"

# ---- 1b. volume group UUID 就是 Data 卷的 Volume UUID，这里直接取 ----
VG=$(diskutil info "$DATA" \
     | awk -F': *' '/^ *Volume UUID/{gsub(/[ \t]+$/,"",$2); print $2; exit}')
echo "VG_UUID = $VG"      # Preboot 里那个目录就叫这个名字

# ---- 2. System，成组到 Data ----
sudo diskutil apfs addVolume "$CNT" APFS "Macintosh HD" \
     -role S -groupWith "$DATA" -nomount
SYS=$(vol_of "Macintosh HD"); echo "System  = $SYS"
diskutil apfs listVolumeGroups "$CNT" | grep -qF "$SYS" \
  || { echo "FATAL: System 卷没和 Data 卷成组"; exit 1; }
```

**另有一条 `vol_of` 的陷阱，本轮实际踩到了：** 原来的实现是

```bash
vol_of() { diskutil list "$CNT" | awk -v n="$1" '$0 ~ ("APFS Volume " n " "){print $NF}'; }
```

它对 `n="Macintosh HD"` 会命中 `APFS Volume Macintosh HD - Data …` 那一行 ——
**因为 `"Macintosh HD "` 是 `"Macintosh HD - Data"` 的前缀。**
后果是第 A.10 节的 bless 实验拿着 Data 卷当系统卷跑，`bless` 回报
`Volume does not have system role` / `Snapshot options are only available for system volumes`。
**修法是逐卷读 `diskutil info` 的 `Volume Name` 做精确比较：**

```bash
vol_of() {   # vol_of <精确卷名> -> diskNsM
  local want="$1" v n
  for v in $(diskutil list "$CNT" 2>/dev/null | awk '/APFS Volume/{print $NF}'); do
    n=$(diskutil info "$v" 2>/dev/null \
        | awk -F': *' '/^ *Volume Name/{gsub(/[ \t]+$/,"",$2); print $2; exit}')
    [ "$n" = "$want" ] && { printf '%s' "$v"; return 0; }
  done
  return 1
}
```

**这条教训比它看起来重要：** 两个卷名之间是前缀关系不是巧合，而是 Apple 的命名约定
（`<名字>` 与 `<名字> - Data`）。任何按卷名查设备的代码都会撞上它。

---

**以下是第二轮写的分析过程，保留以便看清是怎么缩小到那一格的。**

`-69624` 是 `diskutil` 的通用错误，不指明原因。已排除的解释：

- **不是容器太小**：同一个容器上后续的 `-role B`、`-role V` 都成功了。
- **不是 role D 本身被禁**：用法串里 `D` 在允许集合内，而 `-role S` 在同一容器上成功。
- **不是卷名冲突**：容器里当时只有 `Macintosh HD` 一个卷。

**第二轮（run `41278014136`）把五条变体跑完了，结果把问题缩小了一格。** 全部 `TESTED(25G76)`：

| 变体 | 命令 | 结果 |
|---|---|---|
| D1 | `addVolume … -role D -groupWith $SYS -nomount` | `-69624` |
| D2 | `addVolume … -groupWith $SYS -nomount`（不给 role） | `-69624` |
| D3 | `addVolume … -role D -group $SYS -nomount` | `-69624` |
| D4 | `addVolume … -role D -sibling $SYS -nomount` | `-69624` |
| D5 | `addVolume … -role D -nomount`（**不成组**） | **成功**，`Created new APFS Volume disk3s2`，但 `listVolumeGroups` 回报 `No Volume Groups among 1 Volume` |

**结论：`-role D` 本身没问题，被拒的是「成组」这个动作。** 而且四种拼法
（`-groupWith` / `-group` / `-sibling` / 不给 role）全部同一个错误码，
说明拒绝发生在 `diskutil` 把请求交给 `apfsd` 之后，不是参数解析层面。
失败时容器的状态（`TESTED(25G76)`）：

```text
+-- Container disk3  3757027328 B (3.8 GB)，99.6% free
    +-< Physical Store disk2s2
    +-> Volume disk3s1  (Role: System)
        Name: Macintosh HD (Case-insensitive)      ← 顺带确认 V-006
        Mount Point: Not Mounted
        Sealed: No        FileVault: No
+-- Container disk3
    +-> No Volume Groups among 1 Volume
```

**容器剩余空间不是原因**（99.6% 空闲），**卷名不是原因**（容器里只有一个卷）。

**第三轮缩到两个假设 + 一条直接问 `apfsd` 的探针（已写进 workflow）：**

| # | 假设 / 探针 | 为什么 |
|---|---|---|
| **E0** | 复现 D1，然后 `log show --start <T0>` 捞 `apfsd` / `diskutil` 那一段 | `-69624` 是 `diskutil` 的通用错误码。**真正的原因只可能在 `apfsd` 那一侧**，而统一日志是唯一能看到它的地方。这是本轮最高价值的一条 |
| **H1**（E1/E2） | 成组要求 sibling 卷**已挂载**。前两轮一律给了 `-nomount` | 成组要写 firmlink 相关的卷元数据，`apfsd` 可能需要先能读到系统卷 |
| **H2**（E3） | **组的锚必须是 Data 那一侧**：先建 Data（`-role D`），再 `addVolume "Macintosh HD" -role S -groupWith <data>` | Apple 自己的卷组里 Data 卷是 `disk1s5s1` 的「Data Partition」（`bless --info` 的用词），语义上 System 是挂在 Data 组里的那一个 |
| **H3**（E4/E5） | 容器要用 `diskutil apfs create <分区> <卷名>`（容器 + 第一个卷一次建）而不是 `createContainer`（空容器）+ `addVolume` | `create` 是 Apple 文档里「建一个带一个卷的新容器」的那条路；它建出来的第一个卷可能带上了 `addVolume` 给不了的某种元数据 |

**六条原始变体（第二轮之前写的，D6/D7 当时没实现，已并入上表的 H2/E0）：**

| # | 变体 | 为什么可能 |
|---|---|---|
| D2 | `addVolume … -groupWith "$SYS"`，**不给 `-role D`** | 成组这个动作本身可能就隐含了 role D；显式再给一次可能构成「不合法的组合」 |
| D3 | `addVolume … -role D -group "$SYS"` | 用法串写的是 `-group[With]`，两种拼法都该接受，但 `-groupWith` 的解析可能有别的分支 |
| D4 | `addVolume … -role D -sibling "$SYS"` | 用法串把 `-sibling` 与 `-group[With]` 列为同一组互斥项，语义可能更宽松 |
| D5 | 先 `addVolume` 不带 role 也不成组，再 `changeVolumeRole <vol> D`，再想办法成组 | 把两件事拆开，定位到底是 role 还是 group 被拒 |
| D6 | 把顺序倒过来：先建 Data（`-role D`，不成组），再建 System（`-role S -groupWith <data>`） | 组的锚可能必须是 Data 那一侧 |
| D7 | `addVolume` 之后用 `diskutil apfs deleteVolumeGroup` / 重建，观察 `listVolumeGroups` 的中间态 | 纯诊断，用来读 `-69624` 的上下文 |

**这一条阻塞整条装配链**：没有成组的 Data 卷，firmlink 建不起来（第 A.5.2 节），
启动会停在早期用户态。所以它是第 E 节表里现在的**第一优先**。

**同时它给第 A.3.2 节的脚本加了一条硬门禁**：第 2 步之后必须立刻验
`diskutil apfs listVolumeGroups "$CNT"` 里有且只有一个组、成员恰好两个。
1.0 的脚本把自检放在第 6 步，太晚 —— 中间还插了两次 `addVolume`，
真出错时要回溯三条命令才知道哪条坏了。

#### A.3.3b 三条退路（原文保留，`V-007` 已不需要它们，但 `V-031` 可能需要 R-b）

**三条退路，按优先级：**

| 退路 | 做法 | 代价 | 标签 |
|---|---|---|---|
| R-a | 先用默认 role 建卷，再 `diskutil apfs changeVolumeRole <vol> B` 改。手册说该动词「改变已有卷的 role 元数据标志」，大写置位、小写清位 | 多一条命令 | `KNOWN` 动词存在；`INFERRED` 它允许设 B |
| R-b | 让 `asr restore --erase` 连带造。`75` 第 2.3.2 节已引手册：目标是分区且带 `--erase` 时，若被恢复的卷是有效系统，**Preboot 与 Recovery 的相关内容会一并从源复制到目标，必要时在目标上创建这两个卷** | 产出的 build 是源那一版（`75` 的 `P-016` / `76` 的 `L-023`） | `KNOWN` |
| R-c | `diskutil apfs convert -prebootSource <dir>` 对一个 HFS+ 源卷做转换，手册说**转换过程会自动创建一个带 UUID 目录的 Preboot role APFS 卷** | 要先有一个 HFS+ 卷，而且产出的是「单卷容器 + Preboot」，还要再 `addVolume` 补 Data/VM | `KNOWN` |

**R-c 的附带价值远大于它作为退路的价值**，见第 A.6.4 节。

#### A.3.4 这一层各条省掉或写错的后果

| 写错 | 表现 | 判据 |
|---|---|---|
| 没有 role `S` 的卷 | **`bless --create-snapshot` 直接报错**，错误串是 OCLP 记录的那句 `Can't use last-sealed-snapshot or create-snapshot on non system volume` | 第 C.1 节 L0-3 |
| System 与 Data 没成组 | `INFERRED`：firmlink 建不起来（firmlink 是 volume group 的机制，不是两个任意卷之间的机制）。表现是启动到早期用户态卡住，因为 `/private`、`/Users` 不存在 | 第 C.1 节 L0-2：`diskutil apfs listVolumeGroups` 里两个卷必须同组 |
| 给 Preboot 或 VM 加了 `-groupWith` | `INFERRED`：违反 Apple「Preboot/VM/Recovery 共享、不随系统卷复制」的形态。最坏情况是 `boot.efi` 在 Preboot 里找不到 per-volume-group 目录 | 第 C.1 节 L0-2：组成员必须恰好两个 |
| 缺 Preboot | **不可引导，而且表现是「选择器里没有 macOS 这一项」而不是「选了起不来」**。`76` 第 1.3 节已把这个误诊模式写清 | 第 C.1 节 L0-4 |
| 缺 Data | `INFERRED`：停在早期用户态。代价是零（它就是装出来的），不值得为「能不能省」花时间 | 第 C.1 节 L0-1 |
| 缺 VM | `INFERRED`：swap 与 sleepimage 无处可放，`dynamic_pager` 可能自建也可能报错。它初始大小接近零，省它一点好处都没有 | 第 C.1 节 L0-1 |
| 建了 Update 卷（role `E`/`U`） | 失去 OTA 暂存，而我们 `BlacklistAppleUpdate = true` 且基线固定在 25G325，**本项目不做 OTA**。零损失，但多一个卷等于多一处可写坏的地方 | — |
| 建了 xART（`X`）或 Hardware（`H`） | 无影响，平台上不存在对应硬件。不要建 | — |

**本轮顺带把 `76` 的 `L-001`（role 字母 `N`/`L`/`C`/`Y`/`G` 的含义未确证）推进了一半。** `KNOWN`，`diskutil(8)` 的 `APFS VOLUME ROLES` 一节给出的映射里可读出：`D` = Data、`E` = Update、`X` = XART（hardware security）、`H` = Hardware、**`C` = Sidecar（Time Machine）**、**`Y` = Enterprise（data）**（转述自 <https://keith.github.io/xcode-man-pages/diskutil.8.html>）。`N`、`L`、`G` 仍未确证。**这不阻塞任何事**：我们只用 `S`/`D`/`B`/`V`。把这三个字母的查清方法（在运行器上跑 `diskutil apfs addVolume` 不带参数看用法串，再 `man diskutil` 读全节）留在第 D 节，结果回填给 `76` 的 `L-001`。

### A.4 System volume 的内容 【必需】

#### A.4.1 内容从哪里来

**来源是 `payloadv2` 的 53 个 payload 里那 458,715 条条目中，`type == F`/`D`/`L` 的全部。** `71` 第 1.4 节已定清容器层级，`71` 第 2.1 节已证 Windows 侧就能按逻辑路径抽任意文件。本文只补**选择规则**。

**写进 System 卷的根（`/`）：payload 里**不以** `System/Library/Templates/Data/` 开头的全部条目。** 那一棵是 Data 卷的骨架，见第 A.5 节。

**可以剔掉的（x86_64-only 瘦身），`KNOWN`，本轮从索引算出：**

| 剔掉什么 | 条目/字节 | 理由 |
|---|---:|---|
| `System/Library/Kernels/kernel.release.*` | 13 个文件 / **218,213,696 字节** | 全部是 arm64 的 per-SoC 内核（`t6000`…`t8142`、`vmapple`）。x86_64 要的是 `System/Library/Kernels/kernel`（19,008,056 字节）那一个 |
| `usr/standalone/firmware/` | 87 个文件 / 129,947,926 字节 | iBridge / T2 / SEP / UARP / retimer / 配件固件。`77` 第 E.3 节已判非 T2 Intel VM 无 SEP，这些路径短路不跑 |
| `System/Library/Desktop Pictures/` | 261 个文件 / 715,589,235 字节 | 无头环境（`73` §1.3）。`INFERRED`：剔掉只影响壁纸，不影响启动。**但第一轮不要剔**，见下 |

**第一轮不要做任何瘦身。** 理由：本文的第一个目标是拿到一次「能启动」，而每一条剔除都是一条新的未知。瘦身属于第二轮，而且要一条一条加、一条一条验。唯一例外是 arm64 的 13 个内核 —— 它们按 `00-OVERVIEW` 第 7 节补充规则 2（arm64 证据不得用于 x86 决策）本来就不该出现在一块 x86 盘上，而且省 218 MB。

**按字节量最大的 18 个前缀（`KNOWN`，本轮算出，供第二轮瘦身排序）：**

| 字节 | 文件数 | 前缀 |
|---:|---:|---|
| 5,664,624,275 | 88,208 | `System/Library/PrivateFrameworks` |
| 1,558,666,434 | 23,672 | `System/Library/Frameworks` |
| 1,237,415,642 | 841 | `System/Library/LinguisticData` |
| 1,064,396,142 | 2,720 | `System/Library/Extensions` |
| 1,051,984,436 | 13,114 | `System/Library/Templates`（→ Data 卷，不在 System 上） |
| 854,642,350 | 8,864 | `System/Library/CoreServices` |
| 815,707,598 | 372 | `System/Library/Fonts` |
| 715,589,235 | 261 | `System/Library/Desktop Pictures` |
| 557,027,282 | 4,108 | `System/iOSSupport/System` |
| 436,798,844 | 4 | `System/Library/KernelCollections` |
| 432,846,645 | 3,482 | `System/Library/ExtensionKit` |
| 263,791,840 | 2,263 | `System/Library/Components` |
| 237,221,752 | 14 | `System/Library/Kernels` |
| 172,410,250 | 26 | `usr/share/tokenizer` |
| 147,290,840 | 2,513 | `System/Applications/Utilities` |
| 138,791,024 | 6,484 | `System/Library/Perl` |
| 129,947,926 | 87 | `usr/standalone/firmware` |
| 127,520,693 | 69,230 | `System/Library/Assistant` |

#### A.4.2 权限、所有者、标志、xattr：四件事，顺序有讲究

索引的四列直接对应要铺的四样东西：

| 索引列 | 是什么 | 怎么铺 |
|---|---|---|
| `mode` | POSIX mode，十进制。常见值 `493`=`0755`、`420`=`0644`、`292`=`0444` | `ditto` 已经按源文件的 mode 铺。**若源是我们自己解出来的文件，要先 `chmod` 对** |
| 所有者 | **索引里没有这一列**（`tools/scan.py` 没记 `UID`/`GID`） | `INFERRED`：系统内容应当是 `root:wheel`。做法：铺完对整棵树 `chown -R root:wheel`，再对已知例外（若有）单独改。查清方法在第 D 节（对运行器的 `/System` 抽样 `ls -n`）。登记为 `V-008` |
| `bsd_flags` | `UF_COMPRESSED`（`0x20`）与 `SF_RESTRICTED`（`0x80000`） | **见下，这是最容易出错的一格** |
| `xattr_bytes` | 该条目携带的 xattr 字节数 | `ditto` 默认 `--extattr`，自动铺 |

**`bsd_flags` 的正确做法，三条规则：**

> **规则 1：绝不把索引的 `bsd_flags` 原样 `chflags` 上去。**
>
> 133,933 个条目的 `FLG` 带 `UF_COMPRESSED`（`0x20`），而归档里存的是**解压后**的内容（第 0.3.1 节）。原样铺上去等于声明「这个文件是压缩的」而文件系统里没有对应的 `com.apple.decmpfs`，内核会把它当 0 长度。**这一条会一次命中 133,933 个文件，包括 `SystemKernelExtensions.kc` 与 `System/Library/Kernels/kernel`。**

> **规则 2：压缩交给 `ditto --hfsCompression` 去创建，不要自己造 decmpfs。**
>
> `ditto(1)`：带 `--hfsCompression` 时，若目标是支持文件系统压缩的 HFS+ 或 APFS 卷，**在适当时把全部内容压缩**，并明说该选项只打算用于涉及系统文件的安装与备份场景（转述自手册）。它会同时把 `UF_COMPRESSED` 与 `com.apple.decmpfs` 一致地设好。**这是唯一不会造成规则 1 那种不一致的做法。**

> **规则 3：`SF_RESTRICTED` 单独铺，而且放在最后。**
>
> 95.92% 的文件带它。它是 SIP 的 rootless 位，置上之后**连 root 都改不动那个文件**（SIP 已关的情况下可改，但 CI 里不要赌）。所以它必须是铺内容的最后一步。`ditto` 有 `--persistRootless`（被替换的文件带该标志时即使源文件没有也保留），但我们是往空卷写、没有「被替换的文件」，所以要自己置。

规则 3 的做法（可直接照抄，第 A.4.3 节第 3 步用的是同一段）：

```bash
# 按索引把带 SF_RESTRICTED 的路径喂给 chflags。不要用 -R 一刀切，
# 因为 1,650 个文件的 FLG 是 0x0、9,464 个只有 0x20（即只有 UF_COMPRESSED）。
# 路径里可能有空格，所以用 NUL 分隔喂给 xargs -0，不要用空白分隔。
awk -F'\t' 'NR>1 && ($5=="524288" || $5=="524320") { print $1 }' "$IDX" \
  | while IFS= read -r p; do printf '%s\0' "$SYSROOT/$p"; done \
  | sudo xargs -0 -n 200 chflags restricted
```

**`V-009` 已关闭，而 1.0 写的退路是错的。** `TESTED(25G76)`，run `41271530800` 的 `B3-chflags.txt`：

| 写法 | 结果 |
|---|---|
| `sudo chflags restricted <file>` | **成功**。回读 `stat -f 'flags=%Xf  %Sf'` → `flags=80000  restricted` |
| `sudo chflags 0x80000 <file>` | **`chflags: invalid flags: 0x80000`。这个写法不存在**，回读 `flags=0` |
| `sudo chflags compressed <file>` | 助记符被接受但**标志没置上**，回读 `flags=0`；文件内容照常读出（`cat` → `hello`，`stat -f %z` → `6`） |

两条连带结论：

1. **退路取消。** 只有助记符 `restricted` 可用。要用数字形式得查 `chflags(1)` 接受的八进制/十进制写法，但既然助记符通的，这件事没有继续查的价值。
2. **第 A.4.2 节规则 1 的那个灾难场景，用 `chflags` 触发不了。** APFS 上 `chflags compressed` 不会真的置 `UF_COMPRESSED`。所以「标志与内容不一致」这个杀手只能由**同时写 `com.apple.decmpfs` xattr 与标志**的工具制造（即 `cp -p`/`rsync -X` 一类按 xattr 原样搬运的路径），而不会由我们自己的 `chflags` 一步制造。**这把第 0.3.1 节那条风险的触发面缩小了，但没有消除** —— 规则 1（禁止照抄 `FLG`）仍然有效，因为真正的危险在 xattr 搬运那一侧。

#### A.4.3 可照抄的铺内容序列

```bash
#!/usr/bin/env bash
# A.4 铺 System 卷内容。
# 前提：$SYSROOT 是已挂载的 role S 卷的挂载点（第 B 节用 /System/Volumes/Update/mnt1）
#       $STAGE  是本地解出来的 payload 内容根（一棵与 payload 逻辑路径同构的树）
#       $IDX    是 payloadv2-full-index.tsv
set -euo pipefail
SYSROOT="${1:?}"; STAGE="${2:?}"; IDX="${3:?}"

# ---- 1. 主体。--hfsCompression 是本节的全部重点 ----
sudo ditto --hfsCompression --persistRootless "$STAGE" "$SYSROOT"

# ---- 2. 所有者。V-008 定版前先一刀切 ----
sudo chown -R root:wheel "$SYSROOT"

# ---- 3. SF_RESTRICTED。必须最后，而且必须按索引逐条，不能 -R ----
awk -F'\t' 'NR>1 && ($5=="524288" || $5=="524320") { print $1 }' "$IDX" \
  | while IFS= read -r p; do printf '%s\0' "$SYSROOT/$p"; done \
  | sudo xargs -0 -n 200 chflags restricted

# ---- 4. 绝对不要做的那一步（留在这里当警示，不要取消注释）----
# awk -F'\t' 'NR>1 {print $5, $1}' "$IDX" | while read -r f p; do
#   sudo chflags "$f" "$SYSROOT/$p"      # ← 这会把 UF_COMPRESSED 铺到 133,933 个
# done                                   #   未压缩的文件上，System 卷当场报废
```

**第 1 步用 `ditto` 而不是 `cp -a` / `rsync` / `tar`，四条理由：**

| 不用谁 | 为什么 |
|---|---|
| `cp` | 没有 `--hfsCompression` 等价物。产物是「解压 + 无压缩标志」，能起来但 System 卷从 5.5 GB 涨到 19 GB 量级（第 0.3.1 节） |
| `rsync` | macOS 自带的 `rsync` 版本对 xattr / ACL / 资源分叉的处理历来有坑，而且同样没有压缩创建能力 |
| `tar` | 它是归档格式，中间多一次落盘；而且 BSD `tar` 对 decmpfs 的处理未知 |
| `asr` | 它是**整卷**复制，不是文件级铺设。它属于 `75` 的 R1 路径，与本节（R2 式直写）是两条不同的路 |

**失败的表现：**

| 哪一步失败 | 表现 |
|---|---|
| `ditto` 报 `No space left on device` | 容器太小。按未压缩体积重算（第 A.4.5 节） |
| `ditto` 成功但 `du -sh "$SYSROOT"` 远大于 5.5 GB | `--hfsCompression` 没生效。核对目标卷是不是 APFS，核对 `ditto` 版本接受该选项 |
| 第 3 步之后 `ls` 某个文件报 `Operation not permitted` | `SF_RESTRICTED` 铺对了，SIP 没关。在运行器上 SIP 已关（`91` 第 1 节），所以这表示**铺到了错的地方**（例如铺到了 `/` 而不是 `$SYSROOT`）。**立刻停，不要尝试清标志** |
| 铺完某个文件 `cat` 出来是空的、而 `stat -f %z` 非零 | **规则 1 被违反了。** 整卷报废，重建 |

#### A.4.4 哪些内容不属于 System 卷

| 路径 | 实际归属 | 依据 |
|---|---|---|
| `System/Library/Templates/Data/**`（18,731 条） | 它是 **Data 卷的骨架模板**，留在 System 卷上，内容被拷到 Data 卷。两边都有 | 第 A.5 节 |
| `System/Volumes/*`（13 个目录：`Data`、`Preboot`、`VM`、`Recovery`、`Update`、`BaseSystem`、`Hardware`、`iSCPreboot`、`xarts`、`FieldService*`） | **全部是空挂载点目录**，payload 里 `type == D`、`data_bytes == 0`。建出目录即可，不要往里塞东西 | `KNOWN`，本轮从索引读出 |
| `System/Cryptexes/App`、`System/Cryptexes/ExclaveOS`、`System/Cryptexes/OS` | **三个都是符号链接**（`type == L`），`OS` 那个带 70 字节 xattr。`System/Cryptexes` 本身是目录 | `KNOWN`，本轮从索引读出。链接目标见第 A.6.5 节 |

### A.4.5 容量预算

| 项 | 压缩铺设 | 未压缩铺设 | 来源 |
|---|---:|---:|---|
| payload 常规文件字节合计（双架构） | — | 19,259,872,224 | 本轮算出 |
| 剔掉 arm64 的 13 个内核 | — | −218,213,696 | 本轮算出 |
| 剔掉 `System/Library/Templates/Data`（归 Data 卷） | — | −1,051,984,436 | 本轮算出 |
| **System 卷内容（未压缩，x86 粗瘦）** | — | **≈ 17.99 GB** | 算术 |
| **封印快照（Apple 装完的实际值）** | **5,553,249,931** | — | `75` §0.0 引的 `InstallationSize-Snapshot` |
| Data 卷骨架 | ≈ 1.05 GB 的上界（Templates 全量，实际装完远小） | 同 | 本轮算出 |
| Preboot | 350 MB 量级 | 同 | `76` §1.2 转述的 eclecticlight 数据 |
| VM | ≈ 0 | 同 | `76` §1.4 |

**两条结论：**

1. **按 `--hfsCompression` 走，`75` 第 0.0 节定的 12 到 16 GB 瘦镜像成立**（5.5 GB 快照 + Data + Preboot + APFS 余量 + 512 MiB ESP）。
2. **不压缩就不成立。** 17.99 GB 的 System 内容加上其余，容器要 20 GB 以上，整块盘要 22 GB 以上，直接把 `75` 的预算打穿。**这是第 0.3.1 节那条核实的实际后果，也是它值得单独写一节的理由。**

`INFERRED`：17.99 GB 这个数是「payload 未压缩字节」，不等于「铺到 APFS 上的实占」（APFS 有稀疏、clone、元数据开销，而且 payload 里有 hardlink）。它是一个上界。查清方法：第 B 节第 7 步铺完立刻 `diskutil info -plist <sysvol>` 读实占，与本表比对。登记为 `V-010`。

---
### A.5 Data volume 的内容 【必需】

#### A.5.1 骨架来自 payload，不需要我们编

`KNOWN`，本轮从索引读出：**`System/Library/Templates/Data/` 下共 18,731 条条目**，1.05 GB。它是 Apple 为 Data 卷准备的模板树。前几条：

```text
System/Library/Templates/Data                                    D  mode 0755
System/Library/Templates/Data/.TemporaryItems                    D  mode 1755
System/Library/Templates/Data/Applications                       D  mode 0775
System/Library/Templates/Data/Applications/.localized            F  0 字节  mode 0444
System/Library/Templates/Data/Applications/Utilities             D  mode 0755
System/Library/Templates/Data/Library                            D  mode 0755
System/Library/Templates/Data/Library/AppStore                   D  mode 0777
System/Library/Templates/Data/Library/Apple/Library/Bundles/…
```

两条可直接用的事实：

- 模板里的 mode 不是一刀切（`0755` / `0775` / `1755` / `0777` / `0444` 都有），所以**铺它同样要用 `ditto` 而不是 `mkdir -p` 手搓**。
- 模板里有 `System/Library/Templates/Data/Library/Preferences/SystemConfiguration/com.apple.Boot.plist`（232 字节）。**这是 payload 里唯一一个 `com.apple.Boot.plist`**（本轮检索 `com.apple.[Bb]oot` 共 16 条命中，其余是 Boot Camp 助理的无障碍 bundle、`com.apple.bootinstalld` 的 LaunchDaemon 与沙箱 profile、`com.apple.BootPolicy` 的日志配置、以及 `com.apple.Boot.plist` 的 man page）。**即 `com.apple.Boot.plist` 属于 Data 卷，不属于 Preboot。** 这一条推翻了一个常见的误解，见第 A.6.3 节。

`-[MSUMigrationHelper dataTemplatePath]`（RVA `0x11aae9`，`77` 第 A.1 节）就是在取这个路径。**我们要做的和 Apple 做的是同一件事。**

#### A.5.2 firmlink：格式、来源、消费者

`KNOWN`，本轮从索引读出两份：

| 路径 | 字节 | mode | `bsd_flags` | `AFT` | 源 |
|---|---:|---|---|---|---|
| `usr/share/firmlinks` | 689 | `0444`（292） | `0x80020` | **8** | `payload.052` |
| `System/Library/PrivateFrameworks/SystemMigration.framework/Versions/A/Resources/firmlinks` | 680 | `0644`（420） | `0x80020` | **8** | `payload.051` |

**两份差 9 字节。** `INFERRED`：`usr/share/firmlinks` 是系统运行期的那一份，`SystemMigration.framework` 里那份是迁移/安装期的模板，`-[MSUMigrationHelper createFirmlinks]`（RVA `0x11aade`）读的应当是后者。**9 字节的差异是什么，未确证**（最可能是 `/AppleInternal` 那一行的有无 —— 下面的公开清单里那一行标注为「只在 Apple 工程机上」）。查清方法在第 D 节（把运行器上两份都落盘逐行 diff）。登记为 **`V-011`**。

**格式与内容**（`KNOWN`，转述自 <https://eclecticlight.co/2021/01/13/big-sur-boot-volume-layout/>）：该文件是一张纯文本表，每行把 System 卷上的一个路径与 Data 卷上的一个路径绑在一起。公开记录的系统 firmlink 清单是 18 行，形如「System 卷路径 ⟷ Data 卷路径」：

```text
/Applications                                                    ⟷ Applications
/Library                                                         ⟷ Library
/System/Library/Caches                                           ⟷ System/Library/Caches
/System/Library/Assets                                           ⟷ System/Library/Assets
/System/Library/PreinstalledAssets                               ⟷ System/Library/PreinstalledAssets
/System/Library/AssetsV2                                         ⟷ System/Library/AssetsV2
/System/Library/PreinstalledAssetsV2                             ⟷ System/Library/PreinstalledAssetsV2
/System/Library/CoreServices/CoreTypes.bundle/Contents/Library    ⟷ System/Library/CoreServices/CoreTypes.bundle/Contents/Library
/System/Library/Speech                                           ⟷ System/Library/Speech
/Users                                                           ⟷ Users
/Volumes                                                         ⟷ Volumes
/cores                                                           ⟷ cores
/opt                                                             ⟷ opt
/private                                                         ⟷ private
/usr/local                                                        ⟷ usr/local
/usr/libexec/cups                                                ⟷ usr/libexec/cups
/usr/share/snmp                                                  ⟷ usr/share/snmp
/AppleInternal                                                   ⟷ AppleInternal   （只在 Apple 工程机上）
```

该文还说明这张表自 Catalina 起没有变过。**但本项目不照抄这张表**：真正要写进盘里的那 689 字节就在 payload 里，第 A.5.3 节的做法是把它原样铺过去，不是我们重新生成。上表只用来做第 C.1 节的逐项比对。

**firmlink 与 symlink 的差别，一句话（`KNOWN`，同一来源）**：firmlink 只在目录之间建立，**双向生效**，并且把两个被链接目录的内容实际合并（例如 System 卷上 `/Users` 里的 `Shared` 会与 Data 卷 `Users/Shared` 的内容合并）。这正是 `apfs-fuse` 不支持它的原因（`75` 第 0.0 节）。

**消费者是谁：** `INFERRED`。`/usr/share/firmlinks` 位于 System 卷，而 firmlink 的建立发生在挂根之后、Data 卷挂上之时。所以读它的是内核的 APFS 实现或 `launchd` 早期阶段，不是 `boot.efi`。**这件事的实际含义是：这张表不需要进 Preboot。** 查清方法在第 D 节（`fs_usage` / `sudo log stream` 抓谁 `open` 了它，或对该路径的 vnode 做 `dtrace`）。登记为 `V-012`。

**另一条做法上的事实：我们不需要自己调任何 API 去「建」firmlink。** `-[MSUMigrationHelper createFirmlinks]` 存在，说明 Apple 在安装期显式做了这一步。但那是因为 UpdateBrain 在**更新**一个已有系统时要重新建立绑定。对一块全新的盘，`INFERRED`：只要 (a) 两个卷成组、(b) System 卷上有 `/usr/share/firmlinks`、(c) Data 卷上有对应的目录存在，firmlink 就会在首次挂载时自动建立。**这是本文第二优先要查的一条**，登记为 **`V-013`**，因为如果它不成立，我们就必须找到 `createFirmlinks` 的等价用户态入口。查清方法在第 C.2 节与 `80` 的 E0-L1：启动一次，`mount` 看 Data 卷有没有挂上、`ls -la /private` 看是不是 Data 卷上的那个（用 `stat -f '%d'` 比设备号）。

#### A.5.3 可照抄的 Data 卷铺设序列

```bash
#!/usr/bin/env bash
# A.5 铺 Data 卷。前提：$SYSROOT 已铺好内容，$DATAROOT 是 role D 卷的挂载点
set -euo pipefail
SYSROOT="${1:?}"; DATAROOT="${2:?}"

# ---- 1. 骨架。源就是 System 卷上刚铺好的那棵模板树 ----
sudo ditto --hfsCompression --persistRootless \
     "$SYSROOT/System/Library/Templates/Data/" "$DATAROOT/"

# ---- 2. 所有者。模板树里有 1755 / 0777 这类 mode，ditto 已经铺对，只补 owner ----
sudo chown -R root:wheel "$DATAROOT"

# ---- 3. firmlinks 表不往 Data 卷写。它在 System 卷上（A.5.2），已由 A.4 铺好。
#         这里只做一条断言，缺了就停。
test -f "$SYSROOT/usr/share/firmlinks" || { echo "FATAL: System 卷上没有 firmlinks 表"; exit 1; }
wc -c < "$SYSROOT/usr/share/firmlinks"     # 期望 689

# ---- 4. 本项目的离线预配落在这里。清单见 75 §5.8（9 项）+ 76 §6.5 的 75-F（2 项 1 目录）----
#         全部在 Data 卷上，所以不碰封印。本文不重复那两份清单。
```

**第 1 步的源是 `$SYSROOT` 上的模板而不是 `$STAGE` 上的**，这是故意的：这样 Data 卷拿到的就是**已经铺好权限与压缩的那一份**，少一次「从索引重放 mode」的机会出错。

**第 4 步是 `76` 第 7 节 `L-024` 那条「漏了必然出错」的项所在的位置。** 本文不重复清单，但在第 C.1 节的 L0 门禁里加一条断言。

### A.6 Preboot volume 的内容 【必需，而且是启动链第一环】

**这一层是此前一直 `BLOCKED` 的那一层。本节把它从「黑箱」降级为「机制已知、文件清单待取证」。**

#### A.6.1 它为什么是第一环

`76` 第 1.3 节已给出启动链，这里只复述关键一跳：

```text
ESP:\EFI\OC\OpenCore.efi
  ├─ UEFI/APFS/EnableJumpstart = true
  │     从 APFS 容器的 jumpstart 区域加载 apfs.efi
  └─ 按 bless 模型扫描，选中 macOS 项之后加载：
        Preboot 卷 : /<VolumeGroupUUID>/System/Library/CoreServices/boot.efi
```

**`boot.efi` 在 Preboot 卷的 per-volume-group 目录里，不在 System 卷上。** `KNOWN`，`76` 第 1.3 节已给出 OpenCore 官方文档的两处旁证（卷图标搜索顺序的第一条是 Preboot 卷内 per-volume 目录，在 macOS 里挂载于 `/System/Volumes/Preboot/{GUID}/`；`.contentVisibility` 的位置示例是 `/System/Volumes/Preboot/{GUID}/System/Library/CoreServices/.contentVisibility`）。

**`<VolumeGroupUUID>` 就是第 A.3.2 节第 5 步取到的那个 `$VG`。** 这是 `diskutil(8)` 对 volume group 的定义（group 用一个 UUID 标识）与 OpenCore 文档对路径的描述两边对上的结果。`KNOWN`。

#### A.6.2 本轮新取到的三条机制事实

这三条都来自 `diskutil(8)` 与 `bless(8)` 的手册，此前本项目没有任何分册引用过。全部 `KNOWN`，转述自 <https://keith.github.io/xcode-man-pages/diskutil.8.html> 与 <https://keith.github.io/xcode-man-pages/bless.8.html>。

**事实 1：`bless --bootefi` 在带 `--create-snapshot` 时的语义就是「拷贝所需的 boot objects」。**

`bless(8)` 的 Mount Mode 一节对 `--bootefi` 的说明是一句话：**当给了 `--create-snapshot` 或 `--last-sealed-snapshot` 时，它启用「拷贝所需的 boot objects」**。Folder Mode 一节对同一选项的说明是另一件事：在被 bless 的目录里用给定的源文件创建一个 `boot.efi`，不给源文件时用默认源（**按相对于被 bless 的挂载点的路径**），并说明这是为了确保用的 `boot.efi` 与目标卷上的 OS 兼容。

> [!CAUTION]
> **1.1 实测：下面这条「一条命令做四件事」的结论只在目标卷已经是 ARV 时成立。**
> 在一块从零建出来的卷上，`--create-snapshot` 被直接拒绝
> （`Can't use snapshot options on non ARV volume`，退出码 2），
> 而**去掉快照选项的那一半照常工作**（退出码 0，三个文件正确铺进 Preboot）。
> 详见第 A.10.2c 节与 `V-034`。所以下面的第 3 项（封印）**要从这条命令里拆出去**。

**合起来读出的结论（`INFERRED`，但两段手册互相印证）：`bless --folder <sysvol>/System/Library/CoreServices --bootefi --create-snapshot` 这一条命令同时做四件事：**

1. 把 `boot.efi` 从默认源（相对挂载点的路径，即 `<sysvol>/usr/standalone/i386/boot.efi`，见第 A.6.4 节）拷到位；
2. 拷贝其余所需的 boot objects；
3. 建一个 APFS root snapshot 并把它设为系统卷的 root snapshot（`--create-snapshot` 的手册原意），即封印；
4. 把被 bless 的目录记进卷的 bootability 特征。

**这正是 OCLP 的 Intel 分支那一条命令**（第 0.2 节），而 OCLP 跑完它就能启动。所以「Preboot 的 boot objects 由谁铺」这个问题的答案是：**`bless` 自己铺。**

**事实 2：`diskutil apfs updatePreboot <volumeDevice> [-od <path>]` 是一个专门为此存在的动词。**

手册原意（转述）：检查给定 APFS 卷的加密用户（解锁）记录，与匹配的 macOS 用户元数据（头像、密码提示等）相关联，**用这些信息去更新该目标卷对应的 Preboot 卷**；并明确说明 **Preboot 卷是在 EFI 固件阶段用来呈现登录界面、以及加载并启动 macOS 的**。macOS 用户元数据从目标 `volumeDevice` 上搜到的 macOS 与 Open Directory 数据库文件取；`-od` 可以指定另一个 OD 数据库全路径（例如 `/Volumes/SomeOtherMacOSVolume/var/db/dslocal/nodes/Default`），或用 `/` 表示用当前运行的 macOS 的那一份。手册还说正常情况下不需要用这个动词，Preboot 卷在用「用户与群组」时会自动更新；并说某个用户登不进去或登录元数据过期时，`diskutil apfs updatePreboot /` 可以当修复用。

**对我们的三条含义：**

- **它接受「目标卷」而不是只能作用于当前启动卷。** 这正是我们需要的形状（装到非启动盘）。
- **它处理的是 Preboot 里的「登录 UI 与用户元数据」那一部分**，不是 boot objects 那一部分。两部分由两个不同的工具铺（事实 1 铺 boot objects，事实 2 铺用户元数据）。
- **`-od` 的存在告诉我们 Preboot 的用户元数据来源是 `var/db/dslocal/nodes/Default`**，而 `75` 第 5 节的离线预配正是在往那里写用户。**所以预配用户必须在 `updatePreboot` 之前做完**，否则 Preboot 里没有那个用户，登录界面上就没有可选的账户。这是一条顺序约束，写进第 B 节第 10 步。

**事实 3：`diskutil apfs convert -prebootSource <yourStagingDirectory> [-noPrebootAdditions]` 把 Preboot 的内容定性了。**

手册原意（转述）：对于当前是、或计划成为「承载 macOS 且可启动」的卷，可以指定 `-prebootSource` 给出**你自己的一个 macOS boot items 暂存目录**；转换过程中会**自动创建一个带 UUID 目录的 Preboot role APFS 卷**来促成 macOS 的 bootstrap。你的目录通常应当可写，因为**在转换之前会自动往里加入额外的（cryptographic 与 EFI rendering 两类）件，而且转换完不会把它们删掉**；可以用 `-noPrebootAdditions` 关掉自动添加。

**这是本节最有价值的一条，三个理由：**

1. **它确认 Preboot 的 per-UUID 目录内容就是一个「boot items 的暂存目录」**，不是某种带签名的容器。可以用普通文件操作构造。
2. **它把自动添加的件分成两类具名的东西：cryptographic 与 EFI rendering。** 对上第 A.6.3 节的两组文件：`.im4*`（cryptographic）与 `.disk_label*`（EFI rendering，即渲染给固件选择器看的那张图）。
3. **它给了一条可以在 CI 里跑的取证实验：** 在一块 scratch 磁盘镜像上造一个 HFS+ 卷，给一个空的暂存目录，跑 `diskutil apfs convert -prebootSource <dir>`，然后看 `diskutil` 往我们的目录里加了什么。**那就是 Apple 自己认为的 Preboot 必需件清单。** 而 `-dryrun` 还能让我们不真的转换。这条实验写进第 D 节的 `preboot-probe` job。

#### A.6.3 `<VG_UUID>/` 下面有什么：从 payload 推出来的那一份

> **1.1 注：这一节是 1.0 从 payload 索引与手册推出来的预测。实测清单在第 A.6.7 节，
> 那里逐条与本节对账。本节保留，因为「哪些件来自 payload、哪些件不来自」这个
> 区分只有本节有，而它决定我们要不要自己准备那个文件。**

**路径骨架（`KNOWN`，多个独立来源一致）：**

```text
Preboot 卷根
└─ <VG_UUID>/
   └─ System/
      └─ Library/
         └─ CoreServices/
            ├─ boot.efi                 ← 启动链加载的那个
            ├─ SystemVersion.plist
            ├─ PlatformSupport.plist
            ├─ .disk_label              ← 固件选择器的文字标签（低分辨率）
            ├─ .disk_label_2x           ← 同上（高分辨率）
            └─ .contentDetails          ← 选择器里显示的名字
```

逐条的来源与标签：

| 件 | 来源 | 谁写 | 标签 |
|---|---|---|---|
| `boot.efi` | **payload 的 `usr/standalone/i386/boot.efi`（723,512 字节，`0644`，`FLG=0x80000`，未压缩，`payload.041`）** | `bless --bootefi`（事实 1） | `KNOWN` 来源与字节数；`INFERRED` 它取的是 `i386` 那一份而不是 `CoreServices` 那一份（两份大小相同，所以这个区别**不影响结果**） |
| `SystemVersion.plist` | payload 的 `System/Library/CoreServices/SystemVersion.plist`（604 字节，`0444`，未压缩，`payload.050`） | `INFERRED`：`bless` 或 `updatePreboot` | `KNOWN` 它必须在 Preboot 里 |
| `PlatformSupport.plist` | payload 的 `System/Library/CoreServices/PlatformSupport.plist`（790 字节，`0644`，未压缩，`payload.050`，全文在 `71` 第 4.1 节） | 同上 | `KNOWN` 它必须在 Preboot 里 |
| `.disk_label` / `.disk_label_2x` | **不在 payload 里。** 本轮在 458,715 条路径里检索 `disk_label` **零命中** | `bless --label <name>` 渲染，或 `--labelfile <预渲染文件>` | `KNOWN` |
| `.contentDetails` | 不在 payload 里 | `INFERRED`：`bless` 写，或我们自己写（它是一个纯文本文件） | `INFERRED` |
| `.im4*`（3 个） | 不在 payload 里。只对带 T2 的机器相关 | `INFERRED`：`bless --personalize` 或 `updatePreboot` 的 cryptographic additions | `INFERRED`；**我们无 T2，大概率不需要** |

**`SystemVersion.plist` 与 `PlatformSupport.plist` 必须在 Preboot 里，而且写错会让系统起不来 —— 这一条有一份很具体的野外证据。** `KNOWN`，转述自 <https://github.com/Macschrauber/Macschrauber-s-Rom-Dump/blob/main/Rename_and_repair_preboot.md>。该项目记录了一个真实缺陷：在同一台机器上原生启动 High Sierra（且 SIP 关闭）会**把另一个已挂载的新系统的 Preboot 卷里的 `SystemVersion.plist` 与 `PlatformSupport.plist` 换成 High Sierra 自己那一份旧版**，同时还会把 `.contentDetails` 与 `.disk_label*` 改成该系统 Data 卷的名字，并对带 T2 的机器替换 3 个 `.im4` 文件。后果分两级：

- **错的 `PlatformSupport.plist` → 不可启动。** 表现是禁止符号；verbose 模式下给出「不受支持的 board ID」的提示，30 秒后硬关机。该文还给出一个可观测的具体例子：被换掉之后 `Mac-27AD2F918AE68F61`（即 MacPro7,1）这个 board-id 不在 High Sierra 的清单里，于是被挡住。
- **错的 `SystemVersion.plist` → 能启动，但选择器里显示成 High Sierra 的图标，而且可能阻止该系统更新或安装。**
- 该文还记录了一条逃生门：在 OpenCore 的 `config.plist` 里加 boot-arg **`-no_compat_check`**，系统会忽略这些问题并启动。

**这给本项目三条可直接用的结论：**

1. **Preboot 里的 `PlatformSupport.plist` 是一道真实的 board-id 门，而且它的判据与 `71` 第 4.1 节那 8 个 board-id 是同一张表。** 我们铺进 Preboot 的那一份必须是 25G325 的（790 字节，含 `VMM-x86_64`）。
2. **`-no_compat_check` 是这道门的旁路，而且它是一个 boot-arg，可以预先写进 `71` 第 6.7 节的 `NVRAM/Add`。** 本文**不建议默认开它**（开了会掩盖一类真实故障），但建议把它写进 `74` 第 3.2 节 `04-safe.plist` 那份候选 config。登记为给 `74` 的修订工单，见第 F 节。
3. **该文另给一条独立印证：这两个 plist「也存在于 System 卷的 CoreServices 目录与 Preboot 卷的 i386 目录里」。** 即 Preboot 卷里**除了** `<UUID>/System/Library/CoreServices/`，**还有一个 `i386` 目录**。`INFERRED`，这是本文此前完全没有的一条路径。它的确切位置（Preboot 卷根下、还是 `<UUID>/` 下）与内容待第 D 节取证。登记为 **`V-014`，这是本文第三优先要查的一条**。

**所以本层的现状，说清楚：**

| 子项 | 现在能写出规格吗 | 缺什么 |
|---|---|---|
| per-UUID 目录名 = volume group UUID | **能** | 无 |
| `System/Library/CoreServices/` 这条相对路径 | **能** | 无 |
| `boot.efi` 的字节来源与大小 | **能** | 无 |
| `SystemVersion.plist` / `PlatformSupport.plist` 的字节来源与大小 | **能** | 无 |
| 由哪条命令把它们铺进去 | **能给出机制与三条途径**（事实 1/2/3） | 哪一条实际生效、各自铺了哪些文件 → 第 D 节 |
| `.disk_label*` / `.contentDetails` 的生成 | **能给出生成者（`bless --label`）** | 渲染出来的字节格式、`--label` 该给什么字符串 → 第 D 节 |
| Preboot 卷根下还有什么（`i386/`？`Cryptexes/`？） | **不能** | → 第 D 节（`V-014`、`V-015`） |
| cryptex 的目录与 manifest | **不能**，见第 A.6.5 节 | → 第 D 节（`V-015`） |
| `com.apple.boot.*` 的 plist | **能给出一条否定结论**，见下 | — |

**关于 `com.apple.boot.*` 的 plist：payload 里没有任何一个属于 Preboot。** `KNOWN`，本轮检索 `com.apple.[Bb]oot` 共 16 条命中，逐条看过，其中与启动配置相关的只有两条：`System/Library/Templates/Data/Library/Preferences/SystemConfiguration/com.apple.Boot.plist`（232 字节，**在 Data 模板里**）与 `usr/share/man/man5/com.apple.Boot.plist.5`（它的 man page）。

**所以「Preboot 里有哪些 `com.apple.boot.*` plist」这个问题的回答是：payload 不提供任何一个；若 Preboot 里存在这类文件，它们是 `bless` / `updatePreboot` 生成的。** 本项目**不需要**往 Preboot 写 `com.apple.Boot.plist`：boot-args 由 OpenCore 的 `NVRAM/Add` 固化（`70` 第 5.3 节路径 A，`71` 第 6.7 节），不走这个文件。`INFERRED`，查清方法在第 D 节（Preboot 全树清单）。登记为 `V-016`。

#### A.6.4 `boot.efi` 的默认源路径

`bless(8)` 的 FILES 一节（转述）：用于 `--bootefi` 的 EFI 系统 booter；省略 `--bootefi` 的参数时用这个文件作为默认输入；另列出 macOS 与 Darwin 的典型 blessed folder。手册的在线渲染把这两条的具体路径留空（`keith.github.io` 的镜像丢了那两个路径常量），但 Folder Mode 一节明说默认源是「**相对于你正在 bless 的挂载点的路径**」。

**结合 payload 的事实，默认源只可能是 `<mount>/usr/standalone/i386/boot.efi`。** `INFERRED`，三条依据：

1. payload 里只有两份 `boot.efi`，另一份在 `System/Library/CoreServices/`，而那个目录正是 `--folder` 的参数本身 —— 让 `--bootefi` 的默认源等于目标目录里的同名文件没有意义。
2. `usr/standalone/i386/` 这个目录名的含义就是「独立于已启动系统的 i386 启动件」，而且**它整棵树（104 个文件）全部未压缩**（第 0.3.1 节 (d)），正是 EFI 阶段读得了的形态。
3. 该目录里的其余件也全是 EFI 阶段的东西：`apfs.efi`（745,912）、`apfs_aligned.efi`（751,108）、`Firmware.scap`（15,729,264）、`EfiLoginUI/` 下 13 个 `.efires`（登录界面的图形资源，合计约 11 MB）。**`EfiLoginUI` 的存在与事实 2 里「Preboot 卷用来在 EFI 固件阶段呈现登录界面」逐字对应。**

查清方法：在运行器上 `man bless` 读 FILES 一节的真实路径常量（本地 man page 不丢常量），并 `ls -la /usr/standalone/i386/`。第 D 节已包含。登记为 `V-017`。

**`apfs.efi` 的那一条附带结论：`71` 第 6.9.2 节说 OpenCore 的 `UEFI/APFS/EnableJumpstart` 是从容器自己的 jumpstart 区域取 `apfs.efi`，而不是我们提供。本节确认了那份 `apfs.efi` 的字节来源是 payload 的 `usr/standalone/i386/apfs.efi`（745,912 字节）。** `INFERRED`：是谁把它写进容器的 jumpstart 区域未确证（最可能是 `diskutil apfs createContainer` 或 `bless`）。**这是一条可能致命的空白**：若没有任何一步把 `apfs.efi` 放进 jumpstart 区域，OpenCore 根本看不见容器里的任何卷（`76` 第 1.3 节判据 1）。登记为 **`V-018`，第 C.1 节有对应的离线判据**（读容器头部看 jumpstart 区域是否非空）。

#### A.6.5 cryptex：位置、形态、挂载方式

**现在能确定的三条（`KNOWN`）：**

1. **payload 里 `System/Cryptexes` 是一个目录，其下 `App`、`ExclaveOS`、`OS` 三项都是符号链接**（`type == L`），`OS` 那个带 70 字节 xattr。本轮从索引读出。
2. **运行器上 cryptex 的实际挂载位置之一是 `/System/Volumes/Preboot/Cryptexes/OS/`。** `KNOWN`，`.github/workflows/evidence-macos26-intel.yml` 的「dyld shared cache 的位置与清单」步骤就在探 `/System/Volumes/Preboot/Cryptexes/OS/System/Library/dyld`，而 `91` 第 1 节记录该 workflow 在 25G76 上跑过。**注意路径里的 `Cryptexes` 是在 Preboot 卷根下，不在 `<VG_UUID>/` 下。**
3. **资产里 cryptex 的体积是已知的**（`75` 第 0.0 节引的 `CryptexSizeInfo`）：`cryptex-system-x86_64` 2,406 MB、`cryptex-app` 50 MB、`cryptex-system-arm64e` 6,770 MB（**我们不需要它**）。

**现在不能确定的（`BLOCKED`，待第 D 节）：**

| 问题 | 为什么重要 |
|---|---|
| Preboot 卷根下 `Cryptexes/` 的完整目录结构 | 它是 2.4 GB 量级的内容，占 Preboot 卷的绝大部分。`76` 第 1.2 节引的「Preboot 约 350 MB」是 Big Sur 时代的数，**macOS 26 上它要大一个数量级 —— 已实测：2,809,421,824 B（2.8 GB）**，见下 |

**1.1 实测的三个卷实占（`TESTED(25G76)`，`diskutil apfs list` 在运行器自己的容器上）：**

| 卷 | role | 实占 | 对我们的意义 |
|---|---|---|---|
| `Preboot` | B | **2,809,421,824 B（2.8 GB）** | 把 `76` 第 1.2 节的 350 MB 这个数废掉。**容器尺寸预算要给 Preboot 留 3 GB**，第 A.4.5 节按这个数改 |
| `Recovery` | R | 1,460,121,600 B（1.5 GB） | 我们**不建**它（第 A.7 节），所以这 1.5 GB 是省下来的 |
| `Macintosh HD - Data` | D | 185,662,193,664 B（185.7 GB） | 这是运行器被 CI 塞满的结果，不是基线。我们自己那块盘上 Data 卷初始只有模板树（第 A.5.1 节的 1.05 GB） |

容器层面：`Size (Capacity Ceiling) 348,622,118,912 B`，`Capacity In Use By Volumes 202.7 GB (58.1%)`。
| cryptex 是以什么形态存在：目录树、还是 sealed DMG | `INFERRED`：是 sealed DMG。转述自 <https://eclecticlight.co/2022/11/16/cryptex-how-a-custom-iphone-is-changing-macos-updates/>：实践中一个 cryptex 是一个**封印的磁盘镜像**，内含自己的文件系统，在启动过程中被挂载到根文件系统内一个**随机选定的位置** |
| manifest / ticket 的文件名与格式 | `77` 第 D.3 节已记录 `writing cryptex1 ticket to %@`（RVA `0x2d2cec`）在 `_ramrod_splat_write_personalized_ticket`（RVA `0x12473c`）里把 ticket 写到目标。**ticket 的来源是 `AMAuthInstallBundlePersonalize`，那一步可能联网**（`77` 的 `U-001`） |
| 「随机选定的位置」如何在我们自建的盘上成立 | 若挂载点是启动期随机选的，那它不是我们要铺的东西；若它记在某个 plist 里，那它是 |

**Apple 官方对 cryptex 的定性（`KNOWN`，转述自 <https://support.apple.com/en-ca/guide/security/sec87fc038c2/web>）：cryptex 的内容在内核启动之后才被 bootstrap；各 cryptex 的测量值、它们的文件系统 seal 以及配套的 trust cache 都表示在一个独立的 Image4 ticket 里，而该 ticket 在密码学上绑定到它所在的那台设备。**

**这段话是 cryptex 这一层的全部风险所在，必须原封不动地记下来：**「在密码学上绑定到它所在的那台设备」= 逐机个性化 = `77` 第 D.3 节那个命门。两处证据指向同一件事，而 `77` 已经把裁决写清：x86/VMM 的 PREPARE 会不会被迫向 `gs.apple.com` 签 cryptex1 ticket，静态定不死，只有在运行器上实跑才知道（`77` 的 `U-001`）。

**本文对这一层的裁决：cryptex 层待第 D 节取证后补，并且它与 `77` 的 `U-001` 是同一条未知的两面。** 登记为 **`V-015`**。

**但有一条可以现在就写下来的缓解事实：** `77` 第 D.3 节记录 `_personalize_boot_bundle`（RVA `0x27a5f`）开头有一条逃生门 —— `if (ctx[+12056] != 0)` 就只 `symlink target/boot` 然后成功返回，完全不进 AuthInstall。配合本节事实 1（payload 里 `System/Cryptexes/{App,ExclaveOS,OS}` **本来就是符号链接**），`INFERRED`：**存在一条「cryptex 只是三个符号链接 + 被链接的内容在 Preboot 卷上」的形态，而建立符号链接不需要任何签名。** 如果取证确认这三个链接的目标是 `/System/Volumes/Preboot/Cryptexes/{App,ExclaveOS,OS}`，那我们要做的就是把 2.4 GB 的 x86_64 cryptex 内容铺到 Preboot 卷的那个位置、建好三个链接，**而 ticket 这一步靠 `csr-active-config` 的 bit 11 与 `SecureBootModel = Disabled` 跳过**。这条推测的查清方法就是第 D 节的 `readlink /System/Cryptexes/*` 加 Preboot 全树清单，**一轮 CI 就能定死**。

#### A.6.6 Preboot 层可照抄的部分

> [!IMPORTANT]
> **一条硬顺序约束，1.1 实测得出：`bless` 不会自己建 `<UUID>/` 目录，它要求那个目录已经在。**
> 在一个 Preboot 卷只有 `.fseventsd/` 的空容器上跑
> `bless --folder <sysvol>/System/Library/CoreServices --bootefi --create-snapshot --label … --verbose`
> 的输出是（`TESTED(25G76)`，run `41278014136`）：
>
> ```text
> No valid group or volume UUID folder for disk3s1
> Error looking up UUID folder in preboot
> Couldn't check if volume /…/ms is ARV
>    退出码 = 2
> ```
>
> 而 bless 之后 Preboot 全树与之前**逐字节相同**（diff 为空）—— 它一个文件都没写。
>
> **所以本节这段脚本（第 B 节第 11 步）必须在 `bless`（第 12 步）之前跑，而且它的
> 第一条 `mkdir -p "$PBCS"` 不是「兜底」，是 `bless` 的前置条件。**
> 1.0 的步骤顺序本来就是 11 在 12 之前，所以顺序不用改；要改的是注释里对
> `mkdir` 的定性，以及第 C.1 节要加一条门禁：**第 12 步之前断言
> `$PREROOT/$VG/System/Library/CoreServices` 存在。**
>
> 顺带读出 `bless` 的两个内部概念（对排障有用）：**ARV = Authenticated Root Volume**；
> 它还会判断是不是「Pre-SSV to SSV」的迁移情形（我们不是，日志里是
> `Non-Data-role volume, so not considered Data-Given-Pre-SSV-to-SSV case`）。

**现在能写出的部分（第 B 节第 11 步）：**

```bash
#!/usr/bin/env bash
# A.6 铺 Preboot。前提：$SYSROOT 已铺好，$VG 是 volume group UUID
#      $PREROOT 是 role B 卷的挂载点
# 注意：本节只做「bless 之外」的补充。boot objects 由 bless 自己铺（事实 1）。
set -euo pipefail
SYSROOT="${1:?}"; PREROOT="${2:?}"; VG="${3:?}"

PBCS="$PREROOT/$VG/System/Library/CoreServices"
sudo mkdir -p "$PBCS"

# ---- 1. 四个 plist / bin。bless 可能已经铺了，这里做幂等的兜底 ----
#      BridgeVersion.{bin,plist} 是 1.1 从实测清单补上的（A.6.7）：
#      运行器同样没有 T2，这两项照样在，说明它们是无条件铺的。
for f in SystemVersion.plist PlatformSupport.plist BridgeVersion.plist BridgeVersion.bin; do
  [ -f "$SYSROOT/System/Library/CoreServices/$f" ] || continue
  sudo ditto "$SYSROOT/System/Library/CoreServices/$f" "$PBCS/$f"
done
# 断言字节数。790 来自 71 §4.1 与实测双向确认；SystemVersion 随版本浮动
# （25G325 payload = 604，25G76 实测 = 603），所以只断言区间。
test "$(stat -f%z "$PBCS/PlatformSupport.plist")" = "790" \
  || echo "WARN: PlatformSupport.plist 字节数不是 790"
SV=$(stat -f%z "$PBCS/SystemVersion.plist")
[ "$SV" -ge 590 ] && [ "$SV" -le 620 ] \
  || echo "WARN: SystemVersion.plist 字节数 $SV 不在 590..620"

# ---- 2. boot.efi 的兜底。bless --bootefi 正常会铺，没铺就从 i386 拷 ----
#      实测（A.6.7）：三份 boot.efi（Preboot / System CoreServices / usr/standalone/i386）
#      SHA-256 完全相同，所以拷哪一份都一样 —— V-017 这一问因此消失。
if [ ! -f "$PBCS/boot.efi" ]; then
  sudo ditto "$SYSROOT/usr/standalone/i386/boot.efi" "$PBCS/boot.efi"
fi
test "$(stat -f%z "$PBCS/boot.efi")" = "723512" || echo "WARN: boot.efi 字节数不符 723512"

# ---- 3. 选择器名字。.disk_label*、.disk_label.contentDetails、.root_uuid
#         四个件全部由 bless 生成（A.6.7 的 A 类），这里什么都不写。
#         1.0 在这里手写了一个 .contentDetails —— 文件名本身就是错的
#         （实际是 .disk_label.contentDetails），而且不该由我们写。

# ---- 4. 启动用的 BKC 副本。1.1 从实测清单补上（A.6.7 的 B 类）----
BKC="$PREROOT/$VG/boot/System/Library/KernelCollections"
sudo mkdir -p "$BKC"
sudo ditto "$SYSROOT/System/Library/KernelCollections/BootKernelExtensions.kc" \
           "$BKC/BootKernelExtensions.kc"
test "$(stat -f%z "$BKC/BootKernelExtensions.kc")" = "67584000" \
  || echo "WARN: BootKernelExtensions.kc 字节数不符 67584000"

# ---- 5. EFI 登录界面的渲染资源。1.1 从实测清单补上（A.6.7 的 B 类）----
#      实测路径是 <VG>/System/Library/Caches/com.apple.corestorage/EFILoginLocalizations/
#      源是 payload 的 usr/standalone/i386/EfiLoginUI/（13 个 .efires，A.6.4）。
#      注意两边的文件名集合不完全相同（实测约 20 个），差额由 updatePreboot 生成，
#      所以这一步尽力拷，缺的交给第 10 步。
EFIL="$PREROOT/$VG/System/Library/Caches/com.apple.corestorage/EFILoginLocalizations"
sudo mkdir -p "$EFIL"
sudo ditto "$SYSROOT/usr/standalone/i386/EfiLoginUI/" "$EFIL/" || \
  echo "WARN: EfiLoginUI 拷贝不完整，交给 updatePreboot"

# ---- 6. 所有者。实测（A.6.7）Preboot 上的件是 root:staff / runner:staff 混合、
#         flags 一律为 0（没有 SF_RESTRICTED）。我们一刀切 root:wheel，
#         因为「谁拥有它」在 EFI 阶段没有消费者（那时还没有 BSD 层）。
sudo chown -R root:wheel "$PREROOT/$VG"

# ---- 7. 不要铺的：全部 *.im4m（实测是 8 个 board 各一份的票据）、Firmware/、
#         restore/、PreLoginData/、var/db/*Info.plist、Preboot 卷根的
#         com.apple.BootInfo xattr。理由见 A.6.7 的 C 类。

# ---- 8. cryptex：V-015 关掉之前这里是空的。不要猜着铺。 ----
echo "TODO V-015: Preboot 卷根下的 Cryptexes/ 与 <VG>/cryptex1/current/ 待取证后补"
```

**第 5 步留空是故意的，而不是遗漏。** 猜着铺 2.4 GB 的 cryptex 内容，错了的表现是「启动到某个点卡住」而不是报错，在无头环境里无法归因（`76` 第 1.3 节同一个误诊模式）。**先取证，再铺。**

#### A.6.7 实测清单（`V-014` 关闭）：一台活着的 macOS 26 x86_64 的 Preboot 卷长什么样

全部 `TESTED(25G76)`，来自 run `41271530800` 的 `preboot` job。
运行器是 26.6.1 / 25G76 / x86_64 / `Apple Paravirtual device`，SIP 已关，
封印完好（`/` 挂的是系统卷的 root snapshot）。**Preboot 卷全树共 679 条**（不含 `Cryptexes/`）。

**第一层（Preboot 卷根）：**

```text
/System/Volumes/Preboot/            drwxr-xr-x root:staff   xattr com.apple.BootInfo (16 B)
├─ .TemporaryItems/folders.0/TemporaryItems       d-wx--x--t root:wheel
├─ 0F9D8E91-834F-3213-9298-BA3FF72476FE/          drwxr-xr-x runner:staff  ← volume group UUID
├─ com.apple.security.cryptexd/                   drwx---r-x root:staff（读不到，权限）
└─ Cryptexes/                                     drwxrwxrwx root:staff
```

三条立刻可用的事实：

1. **per-UUID 目录名确实就是 volume group UUID**，格式是标准 36 字符 UUID。第 A.3.2 节第 5 步取的那个 `$VG` 直接用。
2. **`Cryptexes/` 与 per-UUID 目录是同级的，不在它下面。** 1.0 第 A.6.5 节把它的位置标成未知，现在定死：**Preboot 卷根下**。
3. **Preboot 卷根上有一个 16 字节的 `com.apple.BootInfo` xattr**，而整棵树里**只有这一处**有值得注意的 xattr（另一处是 `com.apple.loginwindow.plist` 上的 `com.apple.quarantine`）。谁写的、内容是什么都未知 —— 登记为 **`V-032`**。它只有 16 字节，很可能是一个 UUID（指向当前 blessed 的 volume group）。**不阻塞**：我们自己铺的时候不写它，看启动是否受影响即可。

**`<VG_UUID>/System/Library/CoreServices/` —— 启动链真正读的那个目录（10 类件）：**

| 件 | 1.0 预测 | 实测 |
|---|---|---|
| `boot.efi` | 有 | **有**，723,512 字节，`0644 root:wheel`，`flags=0` |
| `boot.efi.<board>.im4m` × 8 | 1.0 猜「3 个 `.im4*`，我们无 T2 大概率不需要」 | **有，而且是每个 board 一份，8 份**。board 标识符：`j152fap` `j160ap` `j185ap` `j185fap` `j214ap` `j214kap` `j215ap` **`x86legacyap`** |
| `SystemVersion.plist` | 有，604 字节 | **有**，**603** 字节（1.0 的 604 是 25G325 payload 的值，运行器是 25G76，差 1 字节是版本串长度）；`0644 root:staff`，`flags=0` |
| `PlatformSupport.plist` | 有，790 字节 | **有，790 字节，与 System 卷上那份 SHA-256 完全相同**（`06ffc188ff2bccd233b594e3e43ba4e6a9b57a168e27489839b7a3b0d2f28107`）；顶层键 `SupportedBoardIds` / `SupportedModelProperties`，16 条 |
| `.disk_label` | 有 | **有** |
| `.disk_label_2x` | 有 | **有** |
| `.contentDetails` | 1.0 写的文件名 | **文件名错了。实际是 `.disk_label.contentDetails`** |
| `.root_uuid` | 1.0 完全没有这一项 | **有。** 名字自明：blessed 系统卷的 UUID |
| `BridgeVersion.bin` / `BridgeVersion.plist` | 1.0 完全没有这两项 | **有。** T2/Bridge 固件版本。我们没有 T2，但它们存在于一台同样没有 T2 的虚机上 → 说明它们是无条件铺的 |

**`<VG_UUID>/` 下的其余八棵子树：**

| 子树 | 内容 | 对我们的意义 |
|---|---|---|
| `boot/System/Library/KernelCollections/` | `BootKernelExtensions.kc`、`BootKernelExtensions.kc.elides`、`BootKernelExtensions.kc.<board>.im4m` × 8 | **这是启动用的那份 BKC 的副本，在 Preboot 上。** 第 0.3.1 节已核实 payload 里的 `BootKernelExtensions.kc` 是 67,584,000 字节且**不带 `AFT`**（未压缩）—— 两边对得上 |
| `System/Library/KernelCollections/` | `BootKernelExtensions.kc.<board>.im4m` × 8（**只有 im4m，没有 `.kc` 本体**） | 第二份 ticket 副本。为什么要两份未知，不阻塞 |
| `cryptex1/current/` | `app.dmg` `app.dmg.root_hash` `app.dmg.trustcache`、`os.dmg` `os.clone.dmg` `os.dmg.root_hash` `os.dmg.trustcache`、`apticket.<board>.im4m` × 8、`BuildManifest.plist` `RestoreVersion.plist` `SystemVersion.plist` | **见下面单独一段，这是本节最重要的发现** |
| `Firmware/` | 74 条，全是 `.im4m`：`094-96883-090.dmg.{root_hash,trustcache}`、`094-96899-090.dmg.{root_hash,trustcache}`、`094-96884-089.dmg.aea.x86.{mtree,root_hash,trustcache}`、`BaseSystem.dmg.x86.trustcache`、`x86_64SURamDisk.dmg.x86.trustcache`，**每一项 × 8 个 board** | 全是票据，没有本体。`094-*` 是 Apple 的件号 |
| `Library/Preferences/` | `com.apple.loginwindow.plist`；`SystemConfiguration/{com.apple.Boot.plist, NetworkInterfaces.plist, preferences.plist}` | **`V-016` 的答案：Preboot 里确实有 `com.apple.Boot.plist`**，见下 |
| `System/Library/Caches/com.apple.corestorage/` | `EFILoginLocalizations/*.efires`（约 20 个）、`EncryptedRoot.plist.wipekey` | 这就是第 A.6.2 节事实 3 里 Apple 自己说的「EFI rendering」那一类，也对上第 A.6.4 节 payload 里 `usr/standalone/i386/EfiLoginUI/` 的 13 个 `.efires` |
| `PreLoginData/` | `diagnostics/`（logd 的早期日志）+ `uuidtext/`（约 200 个日志符号文件） | **运行期产物，不是我们要铺的东西。** 679 条里绝大多数是这一棵 |
| `restore/BuildManifest.plist`、`usr/standalone/OS.dmg.root_hash.<board>.im4m` × 8、`var/db/{AdminUserRecoveryInfo,AllUsersInfo}.plist` | 安装/恢复与用户元数据 | `var/db/*Info.plist` 两份就是第 A.6.2 节事实 2（`updatePreboot`）写的那一部分 |

**`V-016` 的答案，以及它为什么不改变我们的做法。**
`<VG_UUID>/Library/Preferences/SystemConfiguration/com.apple.Boot.plist` **存在**。
它的字节来源就是第 A.6.3 节找到的那一条：payload 的
`System/Library/Templates/Data/Library/Preferences/SystemConfiguration/com.apple.Boot.plist`（232 字节）。
但本项目的 boot-args 由 OpenCore 的 `NVRAM/Add` 固化（`70` §5.3 路径 A、`71` §6.7），
**不走这个文件**，所以第 A.6.6 节的脚本不往这里写。
**它的存在只改变一件事：它在，不代表启动链读它。** `V-016` 从「它存不存在」关闭，
「它影不影响我们」这一问的答案是「不影响」，依据是 OpenCore 自己注入 boot-args。

**`cryptex1/current/` —— `V-015` 与 `77` 的 `U-001` 都因为这一棵发生了变化。**

```text
<VG_UUID>/cryptex1/current/
├─ os.dmg                os.dmg.root_hash   os.dmg.trustcache
├─ os.clone.dmg
├─ app.dmg               app.dmg.root_hash  app.dmg.trustcache
├─ apticket.j152fap.im4m      apticket.j160ap.im4m
├─ apticket.j185ap.im4m       apticket.j185fap.im4m
├─ apticket.j214ap.im4m       apticket.j214kap.im4m
├─ apticket.j215ap.im4m       apticket.x86legacyap.im4m
└─ BuildManifest.plist   RestoreVersion.plist   SystemVersion.plist
```

三条结论：

1. **cryptex 的形态确认是 sealed DMG + root hash + trust cache，不是目录树。** 第 A.6.5 节的 `INFERRED` 转为 `TESTED(25G76)`。
2. **三个符号链接的目标确认，第 A.6.5 节的推测成立。** `TESTED(25G76)`：

   ```text
   /System/Cryptexes/OS        -> ../../System/Volumes/Preboot/Cryptexes/OS
   /System/Cryptexes/App       -> ../../System/Volumes/Preboot/Cryptexes/App
   /System/Cryptexes/ExclaveOS -> ../../System/Volumes/Preboot/Cryptexes/ExclaveOS
   ```

   三条链接自身在 System 卷上、带 `restricted`；`/System/Cryptexes` 目录自己带
   `com.apple.rootless`（0 字节）与 `restricted`；`OS` 那条额外带 45 字节的
   `com.apple.fs.altlink`（1.0 从 payload 索引读出的「70 字节 xattr」是 25G325 的值，
   运行器上是 45 字节，差异不影响结论）。`st_dev` 对照证实
   `/System/Volumes/Preboot/Cryptexes/OS` 在 Preboot 卷上（`16777220`），
   而 `/` 与 Data 卷同为 `16777225`。
3. **`apticket.<board>.im4m` 是 8 个 board 各一份，全部预置。** 这是本轮最有分量的一条新证据，
   因为它与「ticket 在密码学上绑定到它所在的那台设备」这句官方说法**不相容**：
   如果票据是逐机签的，盘上只会有本机那一份。**8 份按 board-id 预发的票据说明
   这一层是按 board 粒度签的，不是按机器粒度。** 这对 `77` 的 `U-001`
   （UpdateBrain 的 PREPARE 相位是否必须向 `gs.apple.com` 签 cryptex1 ticket）
   构成强烈的否定方向证据，但**还不足以判死**：也可能是安装介质里自带这 8 份、
   而 APPLY 相位另有一次逐机签。查清方法在 `77` 第 D.3 节已写的实跑。

**顺带解决了 run `41271530800` 留下的那个「待解释」：`/` 的 `st_dev` 为什么和 Data 卷一样。**
因为 volume group 的两个卷对外呈现为**同一个文件系统**，这正是 firmlink 存在的理由 ——
`/private`、`/Users` 这些路径要在 `/` 下看起来像本地目录。所以 `16777225` 是
volume group 的 fsid，`16777220` 是 Preboot 的。`TESTED(25G76)`，
这同时给第 A.5.2 节 `V-013` 的验证方法加了一条约束：**不能用 `st_dev` 区分
System 与 Data**（它们相同），只能用 `stat -f '%Sd'` 看具体设备名，或比 `diskutil info`。

**`bless --info /` 的实测输出（关闭 `V-021` 的一半）。** `TESTED(25G76)`：

```text
Mount point for / is /
No auxiliary booter partition required
System partition found
Preferred system partition found: disk0s1
Returning booter information dictionary:
{
    "Auxiliary Partitions" = ( );
    "Data Partitions"      = ( disk1s5s1 );
    "Preboot Volumes"      = ( disk1s2 );
    "System Partitions"    = ( disk0s1 );
}
 12884902278 => Blessed System File   is /System/Volumes/Preboot/<VG>/System/Library/CoreServices/boot.efi
 12884902198 => Blessed System Folder is /System/Volumes/Preboot/<VG>/System/Library/CoreServices
The blessed volume in this APFS container is /dev/disk1s5, which is not mounted.
```

四条读出来的事实：

1. **blessed 的目录与文件都在 Preboot 卷上**，不在 System 卷上。所以第 A.10 节那条
   `bless --folder <sysvol>/System/Library/CoreServices --bootefi --create-snapshot`
   里给的是**源**路径，`bless` 内部把结果记到 Preboot 的对应路径 —— 两者不矛盾，
   但第 A.10 节必须把这件事写明，否则照抄的人会以为 blessed 目录是 System 卷上那个。
2. **`"System Partitions" = ( disk0s1 )` 就是 ESP**，而 `disk0s1` 正是第 A.1 节的 p1。
   `bless` 自己把 ESP 叫 "System Partition"，与 UEFI 术语一致。
3. **`"Data Partitions" = ( disk1s5s1 )` 是一个快照设备**：`disk1s5` 是系统卷，
   `disk1s5s1` 是它的 root snapshot，而 `/` 就挂在那上面。这是 SSV 从快照启动的形状，
   与第 A.9 节的规格一致。
4. **blessed 目录/文件被记成两个 APFS 文件 ID**（`12884902198` / `12884902278`），
   不是路径字符串。所以 `V-022`（「具体是哪些 APFS 字段」）的答案方向是
   「卷的 bootability 记录里存的是 inode 号」。完整字段仍需 `bless --info --plist` 的
   全文，那一份本轮取到了（`43-bless-info-root.plist`）但还没逐键消化，`V-022` 保持开启。

**`V-018` 本轮没关，而且原因本身是一条证据。** 读容器 jumpstart 区域那一步
（`sudo dd if=/dev/rdisk0s2 bs=1m count=8 | strings`）**产出为空**。
结合第 A.1.0 节的实测（裸设备读在**磁盘镜像**设备上正常），
最可能的解释是**运行器自己那块物理盘的裸节点读被拦**，而镜像设备不受限。
下一轮取证把这条探针的 stderr 留下来即可定死。

**一张「我们要自己铺什么」的净表。** 把上面全部合起来，按「谁来铺」分三类：

| 类 | 件 | 谁铺 |
|---|---|---|
| **A. `bless` 铺** | **只有三个**：`boot.efi`、`.disk_label`（941 B、`UF_HIDDEN`）、`.disk_label_2x`（3773 B、`UF_HIDDEN`），外加 blessed 记录。**`TESTED(25G76)`，见第 A.10.2c 节** | `bless --folder … --bootefi --label …`（**不带** `--create-snapshot`，理由见 A.10.2c） |
| **B. 我们铺** | `SystemVersion.plist`、`PlatformSupport.plist`、`BridgeVersion.{bin,plist}`、`boot/System/Library/KernelCollections/BootKernelExtensions.kc`、`System/Library/Caches/com.apple.corestorage/EFILoginLocalizations/`、**`.disk_label.contentDetails`**、**`.root_uuid`** | 第 A.6.6 节的脚本。**1.0 漏了 `BridgeVersion.*` 与 BKC 副本；1.1 第一版又错把后两项算进 A 类** |
| **C. 不铺** | 全部 `*.im4m`（8×N 份票据）、`Firmware/`、`restore/`、`PreLoginData/`、`var/db/*Info.plist`、`com.apple.BootInfo` xattr | 票据在 SIP/AMFI 全关 + `SecureBootModel = Disabled` 下不被校验（第 0.2 节）；`PreLoginData` 是运行期产物；`var/db/*Info.plist` 由 `updatePreboot` 生成 |
| **D. 待定** | `Cryptexes/`（Preboot 卷根下）、`cryptex1/current/` | `V-015`。**第 A.6.6 节第 5 步继续留空** |

---
### A.7 Recovery volume 【不要】

`76` 第 1.4、1.5 节已定：**不带，而且「我们造不出来但不要也能启动」。** 本文只做两件事：确认，并给出「不要它」的确切后果。

**确认它不在启动链上（`KNOWN`，三条，`76` 第 1.5.3 节已论证，本文复述）：**

1. `76` 第 1.3 节的启动链里没有任何一环读 Recovery 卷。它是一个**并列的启动目标**，不是主路径的一环。
2. Apple 官方对 Recovery 卷的说明是「必须在不解锁系统卷的情况下可用，**以便进入 recoveryOS**」，即它的用途是进 recoveryOS，不是启动 macOS。
3. OpenCore 的 boot algorithm 把 recovery 当 alternate option，官方明说「**alternate 选项可以在没有 primary 选项的情况下存在，反之亦然**」（`76` 第 1.5.3 节引的 dortania 文档）。

**不要它的确切后果，逐条（本节的新增内容）：**

| 失去什么 | 确切表现 | 本项目的替代 |
|---|---|---|
| `Cmd+R` 进 recoveryOS | 该热键按下去没有可引导的目标。`INFERRED`：OpenCore 的四个 Apple BDS 风格 hotkey 里 `CMD+R` 会落空（`76` 第 2.1 节记录它是 OpenCore 内置支持的） | `76` 第 3.1 节的 p2 BaseSystem 分区（若按 `76` 的三分区方案）；或 Alpine（`75` §0.0.1 把它放在 ESP 的 `/EFI/RESCUE/`） |
| 固件选择器里少一个条目 | 选择器里只有 macOS 与 Alpine 两项，不是三项 | 同上 |
| `csrutil` 改 SIP | **零代价，而且本来就不生效。** `70` 第 5.3 节记录：把 `csr-active-config` 放进 `config.plist` 会让恢复环境里的 `csrutil` 改不动实际生效值 | `NVRAM/Add` + `Delete`（`71` §6.7），或 `ToggleSipEntry.efi` |
| `bless --last-sealed-snapshot` 的回退目标 | **这一条是本节新发现的，而且它不是零代价。** OCLP 用 `bless --mount <mnt> --bootefi --last-sealed-snapshot` 回到上一个 Apple 签过的封印快照（第 0.2 节）。**我们的盘上从来没有过 Apple 签过的快照**，所以这条回退路径对我们不存在 | `73` 的 D1/D2 投放路径：重新投放一个镜像比回退快。`74` 第 3.2 节的五份候选 config + 三次失败机制是真正的回退层 |
| 磁盘工具修容器 | 无 GUI 可用（`73` §1.3），而且它要 WindowServer，正是本项目在改的那一层 | Alpine 的 `fdisk`/`sgdisk`，走 SSH |

**另记一条：如果走 `75` 的 R1 路径（`asr restore`），Recovery 卷是免费附带的，那就留着。** `76` 第 1.5.2 节形态二已论证。本文的规格**不要求**它存在，也**不禁止**它存在。唯一要记住的代价是 `76` 的 `L-023`：`asr` 造出的 Recovery 是源那一版的 build。

### A.8 VM volume 【必需，内容空】

**建，空的就行。** 理由与后果：

| 问题 | 答案 | 标签 |
|---|---|---|
| 建不建 | **建。** Apple 把它列进「用于启动 Mac 的 APFS 容器必须至少包含五个卷」（`76` §1.2 引的官方页面），省它等于偏离官方形态，而**它初始大小接近零，省它一点好处都没有** | `KNOWN` 官方形态；`INFERRED` 省它的后果 |
| 空的行不行 | **行。** 它的内容是 `dynamic_pager` 在运行期创建的 swapfile 与 sleepimage。`76` §1.2 对它的启动链依赖判定是「否：启动不读它，运行期才用」 | `INFERRED` |
| 要不要 reserve/quota | **不要。** 给 quota 会在内存压力下让 swap 写失败，那是一类极难归因的故障 | `INFERRED` |
| 要不要进 volume group | **不要**（第 A.0 节） | `KNOWN` |
| 省掉它的表现 | `INFERRED`：`dynamic_pager` 可能自建它，也可能在日志里报错然后不提供 swap。无头环境里后者等于「跑着跑着 OOM」 | `INFERRED` |

**本项目的 VM 卷上唯一需要确认的一件事：`sleepimage` 要禁掉。** `INFERRED`，理由：云 KVM guest 不休眠，而 `sleepimage` 的大小等于 RAM 大小，会白占容器空间。做法是在 Data 卷的预配里 `pmset -a hibernatemode 0` 的等价配置（落到 `/Library/Preferences/com.apple.PowerManagement.plist`）。**这属于 `75` 第 5 节的预配清单，不属于本文。** 登记为给 `75` 的修订工单，见第 F 节。

### A.9 快照 【必需，这是实际被引导的那个根】

#### A.9.1 名字规范

| 候选 | 是什么 | 用不用 |
|---|---|---|
| `com.apple.os.update-<UUID>` | eclecticlight 记录 Big Sur 的封印快照名形如 `com.apple.os-update-` 后接 UUID（转述自 <https://eclecticlight.co/2021/01/13/big-sur-boot-volume-layout/>）；`75` 第 2.3.3 节的脚本按 `com.apple.os.update-*` 通配去找运行器的封印快照 | 我们**不自己起这个名字** |
| `com.apple.os.update-MSUPrepareUpdate` | UpdateBrain 自己用的常量，`77` 第 D.1 节记录 `_prepare_snapshot`（RVA `0x5574e`）调 `createSnapshot:@"com.apple.os.update-MSUPrepareUpdate"` | 只在走 R6 时出现 |
| **`bless --create-snapshot` 自己取名** | `bless(8)`：它「尝试创建目标 APFS 系统卷的一个 APFS root snapshot 并把它设为该系统卷的 root snapshot；目标系统下次启动将从这个快照启动」。**手册没有给出命名参数** | **用这一条** |

**裁决：名字交给 `bless --create-snapshot` 决定，我们不指定。** `KNOWN`（手册里没有命名参数）。三条理由：

1. `bless` 同时要把快照**设成 root snapshot**，那一步写的是卷的元数据字段。自己建快照（`fs_snapshot_create` 或 `diskutil apfs createSnapshot`）再让 `bless --snapshotname <名字>` 去指它，多一个环节、多一处可写错。
2. OCLP 在成千台 Intel Mac 上跑的就是不指定名字的那一条（第 0.2 节）。
3. `bless(8)` 明说这组快照选项**一次只能激活一个**（`--create-snapshot` / `--snapshot` / `--snapshotname` / `--last-sealed-snapshot` 四者互斥）。混用会被拒。

`INFERRED`：`bless --create-snapshot` 取的名字是什么格式未确证。查清方法在第 D 节（运行器上 `diskutil apfs listSnapshots <sysvol>` 的全文）与第 C.1 节（建完立刻列出来）。登记为 `V-019`。**这不阻塞**：我们不需要知道名字，只需要知道「恰好有一个快照、而且它是 root snapshot」。

#### A.9.2 建在哪个卷上

**role `S` 的那个卷，不是别的。** `KNOWN`，两条独立依据：

1. `bless(8)` 对 `--create-snapshot` 的措辞是「目标 **APFS 系统卷**」。
2. OCLP 记录的失败字符串 `Can't use last-sealed-snapshot or create-snapshot on non system volume`（第 0.2 节）。**这是一道运行期的硬门禁，而且它的错误信息是明确的** —— 这在无头环境里是好事。

OCLP 在同一处还记录了一条诊断建议：遇到这个错误时，它判定为「Monterey 及更新版本的一个 APFS 缺陷」，并建议做一次干净安装以确保 APFS 卷被正确构建。**对本项目的含义是：这个错误不一定意味着我们的 role 设错了，也可能意味着容器本身被建坏了。** 所以第 C.1 节的 L0 门禁要在 bless 之前就把 role 验一遍，不要指望 bless 的错误信息来定位。

#### A.9.3 与 bless 的先后

**不分先后 —— 它们是同一条命令。** 这是本节的全部要点。

```bash
sudo bless --folder "$SYSROOT/System/Library/CoreServices" --bootefi --create-snapshot
```

第 A.6.2 节事实 1 已论证这一条同时做四件事：拷 `boot.efi`、拷其余 boot objects、建快照并设为 root snapshot、记 bootability。

**所以「快照」与「bless」这两层在实现上不是两步。** 把它们拆成两步（先 `diskutil apfs createSnapshot`、再 `bless --snapshotname`）在手册上是可行的，但：

- 多一处可错；
- `bless --bootefi` 的「拷贝 boot objects」语义只在带 `--create-snapshot` 或 `--last-sealed-snapshot` 时启用（Mount Mode 的手册原文），**用 `--snapshotname` 时它铺不铺 boot objects 未确证**。

`INFERRED`，登记为 `V-020`。**本文的规格是用合并的那一条。**

#### A.9.4 快照一层写错的后果

| 写错 | 表现 |
|---|---|
| 没有任何快照 | `INFERRED`：`boot.efi` 找不到 root snapshot。macOS 11+ 从快照启动，不从卷本身启动（`76` §1.2 引的官方页面）。表现大概率是「选中了 macOS 但起不来」，而不是「选择器里没有」 |
| 有快照但没设成 root snapshot | 同上。**`diskutil apfs listSnapshots` 看得见它，所以这是一个容易误判成「做对了」的状态** |
| 有多个快照 | `INFERRED`：root snapshot 唯一，多余的只占空间。但 `75` 第 2.3.3 节的做法是「只应该有一个 `com.apple.os.update-*` 快照；不是一个就停」—— **沿用这条纪律** |
| 快照建在 role `D` 或 role `B` 的卷上 | `bless` 直接报 `Can't use … on non system volume` |
| 建快照之后又改了 System 卷的内容 | **快照不变，改动不进快照，所以改了等于没改。** 这是最隐蔽的一类错：脚本里顺序颠倒了，一切命令都成功，启动起来却是改之前的内容。第 B 节用显式的「封印线」把这件事标出来 |

### A.10 bless 【必需】

#### A.10.1 确切参数

```bash
sudo bless --folder "$SYSROOT/System/Library/CoreServices" \
           --bootefi \
           --create-snapshot \
           --label "macOS 26.7.2" \
           --verbose
```

逐个参数：

| 参数 | 手册语义（转述自 <https://keith.github.io/xcode-man-pages/bless.8.html>） | 我们为什么给它 |
|---|---|---|
| `--folder <dir>` | 把该目录设为 macOS/Darwin 的 blessed 目录，即系统固件去那里找 boot code 的目录。**在 HFS+ 卷上会更新卷头，在换机器或清 NVRAM 之后依然有效** | 必需。目标是 `<sysvol>/System/Library/CoreServices` |
| `--bootefi [file]` | 在系统文件夹里用 `file` 作源创建一个 `boot.efi`；不给 `file` 时用默认源（按相对挂载点的路径）。**带 `--create-snapshot` 时它启用「拷贝所需的 boot objects」** | 必需。不给参数，用默认源（第 A.6.4 节） |
| `--create-snapshot` | 尝试创建目标 APFS 系统卷的 root snapshot 并设为该卷的 root snapshot；目标系统下次启动从这个快照启动 | 必需。即第 A.9 节 |
| `--label <name>` | **为固件的 OS 选择器渲染一个文字标签** | 可选但建议。这是 `.disk_label` / `.disk_label_2x` 的生成者（第 A.6.3 节）。不给它，选择器里的名字由别的来源决定（`.contentDetails` 或卷名） |
| `--verbose` | 打印详细输出 | 建议。CI 里我们要知道它到底拷了哪些文件 —— **这同时是第 D 节之外的一个免费取证来源** |

#### A.10.2 禁止的参数

| 参数 | 为什么禁止 |
|---|---|
| **`--setBoot`** | 手册：**让系统从指定分区启动；EFI 系统上它改 `efi-boot-device` 变量**。在 CI 运行器上这等于改运行器自己的固件启动项。`77` 第 E.1 节已记录 UpdateBrain 的 APPLY 相位就是跑 `bless … --setBoot` 并写 NVRAM fallback，并判定「在 CI runner 上让 APPLY 跑 = 改 runner 自己的引导 = 灾难」。**而且我们根本不需要它**：`76` 第 1.3 节判据 3 已论证 OpenCore 的 bless 模型是「扫描预定义路径」，不读固件 NVRAM 里的 bless 记录 |
| **`--mount`** | Mount Mode **不对文件系统做持久修改**，它只设固件的启动卷。我们要的恰好是持久修改（Folder Mode） |
| **`--personalize`** | 手册：尝试对目标做个性化操作，校验 SecureBoot bundle、确保相关启动文件已签名且对**这台特定机器**有效；**可能需要网络访问以校验签名**。这正是 `77` 第 D.3 节那个命门。我们 `SecureBootModel = Disabled`，不需要它，而且 CI 里不该联网签名 |
| `--netboot` / `--legacy` / `--legacydrivehint` | 与本项目无关 |
| `--options` | 手册自己建议避免，改用 `nvram` 设 `boot-args`。我们走 OpenCore 的 `NVRAM/Add`（`70` §5.3 路径 A） |
| `--nextonly` | 只改下一次启动。我们不改本机启动，所以无意义 |

**`--setBoot` 的护栏写进第 B 节的脚本里，而且是一条主动检查而不是一句注释：**

```bash
# bless 之前，确认我们不是在对 / 动手
case "$SYSROOT" in
  /|"") echo "FATAL: SYSROOT 是 / 或空，拒绝执行"; exit 1 ;;
esac
# 确认 SYSROOT 在我们 attach 的那块盘上，而不是运行器的根盘。
# 取整盘标识用 diskutil 自己的「Part of Whole」那一行，不要自己截字符串 ——
# 1.0 写的是 ${SYS_DISK%%s*}，而 ${var%%s*} 删的是**最长**的 s* 后缀：
# 对 disk3s1 它从 "disk" 里那个 s 就开始删，结果是 "di"；对 disk1s5s1 也是 "di"。
# 两边恒等 → 这道护栏每次都误判成「同一块盘」。CI 上实测如此（见本节末）。
whole_of() {
  diskutil info "$1" 2>/dev/null \
    | awk -F': *' '/^ *Part of Whole/{gsub(/[ \t]+$/,"",$2); print $2; exit}'
}
SYS_DISK=$(whole_of "$SYSROOT"); ROOT_DISK=$(whole_of /)
[ -n "$SYS_DISK" ] && [ -n "$ROOT_DISK" ] \
  || { echo "FATAL: 取不到整盘标识，未确定就不 bless"; exit 1; }
[ "$SYS_DISK" != "$ROOT_DISK" ] \
  || { echo "FATAL: SYSROOT 和 / 在同一块物理盘上（都是 $SYS_DISK）"; exit 1; }
```

> **1.1 实测注记（`TESTED(25G76)`）。** 1.0 的那个写法在 CI 上把护栏变成了无条件触发：
> 日志里是 `护栏：SYS_DISK=di  ROOT_DISK=di` → `FATAL` → `exit 0`。
> 连带后果是 run `41271530800` 与 `41274204499` 两轮都没产出 bless 实验的输出文件，
> 于是 `V-020`/`V-021`/`V-023` 看起来像「没跑」而其实是「被自己的护栏挡住了」。
> **两条教训都写进第 C 节的纪律：**（1）判断「同一块物理盘」要问 `diskutil`，
> 不要用 shell 的后缀删除；（2）**任何提前退出的分支都必须留下一个说明文件**，
> 否则从产物上分不清「没跑」与「跑了但被挡」。

`77` 第 E.2 节记录 UpdateBrain 自己也有同类护栏（`should_prepare_to_snapshot`，RVA `0x3dc7b`，目标 `mountPoint == "/"` 直接报错 1127）。**Apple 自己都加了这道检查，我们没有理由不加。**

#### A.10.2a 1.1 实测：`bless --info` 的字段名，以及 `updatePreboot` 在空卷上的表现

`TESTED(25G76)`，run `41278014136` 的 `C0-bless-experiment.txt`。

**（1）`bless --info <卷> --plist` 的结构（`V-022` 的字段名部分关闭）：**

```xml
<dict>
  <key>Auxiliary Partitions</key> <array/>
  <key>Bless Info</key>
  <array>
    <dict><key>Directory ID</key><integer>0</integer>
          <key>Path</key><string></string>
          <key>Relative Path</key><string></string></dict>
    <dict>… 同构的第二项 …</dict>
  </array>
  <key>Data Partitions</key>  <array><string>disk3s1</string></array>
  <key>Preboot Volumes</key>  <array><string>disk3s2</string></array>
  <key>System Partitions</key><array><string>disk0s1</string></array>
</dict>
```

四条读出来的事实：

1. **blessed 信息存在 `Bless Info` 这个两元数组里**，两项分别对应
   blessed folder 与 blessed file，各自三个键：**`Directory ID`（APFS inode 号）、
   `Path`、`Relative Path`**。一块没 bless 过的盘上三者分别是 `0` / 空串 / 空串，
   而运行器自己那块盘上是 `12884902198` / `12884902278` 加完整路径（第 A.6.7 节）。
   **所以第 C.1 节「这块盘 bless 过没有」的离线判据就是 `Directory ID != 0`。**
2. `"System Partitions"` 这一项给的是 **ESP**（`disk0s1`），而且在对一块 scratch 盘
   做 `--info` 时它仍然报运行器自己的 ESP —— 说明这一项来自**固件/系统层面**，
   不是被问的那个卷的属性。**离线判据不能用它。**
3. `"Data Partitions"` 这一项给的是**被问的那个卷本身**（我们的 role S 卷 `disk3s1`），
   不是 Data role 的卷。`bless` 的用词和 `diskutil` 的 role 命名不是一套。
4. 一个刚建出来的 role S 卷：`"Sealed" => "No"`、`"APFSSnapshot" => false`、
   `No snapshots for disk3s1`。这是第 A.9 节封印前的基线。

**（2）`diskutil apfs updatePreboot <空的非启动卷>` 失败，错误码已知（`V-023` 部分关闭）：**

```text
Started APFS operation
Error: -69808: Some information was unavailable during an internal lookup
   退出码 = 1
```

**这个失败是预期的，而且它印证了第 A.6.2 节事实 2 的那条顺序约束。**
`updatePreboot` 的工作是「把目标卷的 APFS 加密用户与 Open Directory 用户对应起来，
再用这些信息更新 Preboot」。一块只有三个文件、没有 `var/db/dslocal` 的卷上
没有任何可对应的东西，所以它在内部查找阶段就返回了。

**对第 B 节的含义：第 10 步（`updatePreboot`）必须在预配用户（`75` 第 5 节往
Data 卷的 `dslocal` 写用户）之后，而且要带 `-od <DATA挂载点>/private/var/db/dslocal/nodes/Default`。**
1.0 的脚本本来就是这个顺序、也本来就带 `-od`，所以不用改；要改的是把它从
「best-effort，失败打 WARN」升级为**「在用户已预配的前提下失败就是真错误」**：
现在我们知道「没有用户时它一定失败」，所以如果用户已经写进去了它还失败，
那就是别的问题，不该被 WARN 吞掉。

#### A.10.2b 1.1 实测：`bless --verbose` 逐条说出它写了什么

`TESTED(25G76)`，run `41279126720`。这一轮 Preboot 的 `<UUID>/System/Library/CoreServices`
目录事先建好了，`bless` 于是真的开始干活（虽然最后还是失败，原因见下）。
`--verbose` 的输出是本项目第一次看到 `bless` 自述它的动作：

```text
Among the APFS volumes in /dev/disk3s1's volume group exists a System-roled volume
  which is compatible with the currently-running macOS
A System volume is reachable, so not considered Data-Given-Pre-SSV-to-SSV
boot.efi unchanged at <sysvol>/System/Library/CoreServices/boot.efi. Skipping update...
Refitting to width 78
Refitting to width 157
Scale 1 label data is valid: YES
Putting scale 1 label bitmap in <sysvol>/System/Library/CoreServices/.disk_label
0x000003AD bytes preallocated for …/.disk_label
Invisibility set for …/.disk_label
Putting scale 2 label bitmap in <sysvol>/System/Library/CoreServices/.disk_label_2x
0x00000EBD bytes preallocated for …/.disk_label_2x
Invisibility set for …/.disk_label_2x
Found system volume UUID path in preboot for disk3s1
Putting scale 1 label bitmap in <preboot>/<UUID>/System/Library/CoreServices/.disk_label
Putting scale 2 label bitmap in <preboot>/<UUID>/System/Library/CoreServices/.disk_label_2x
```

**六条事实：**

1. **`.disk_label` 与 `.disk_label_2x` 各写两份：一份在系统卷的
   `System/Library/CoreServices/`，一份在 Preboot 的 `<UUID>/System/Library/CoreServices/`。**
   1.0 与 1.1 此前都只盯 Preboot 那一侧，**漏了系统卷这一侧**。
   第 A.6.7 节那张「谁铺什么」净表的 A 类因此要补一句：`bless` 在两处都写。
2. **确切字节数**：`.disk_label` = `0x3AD` = **941 字节**；`.disk_label_2x` = `0xEBD` = **3773 字节**
   （标签文本是 `forensics-scratch`，17 个字符）。两张位图的宽度分别 refit 到 **78** 与 **157** 像素。
   所以字节数随标签文本长度变，不是常量 —— 第 C.1 节不要拿它做等值判据。
3. **两个 label 文件被设成不可见**（`Invisibility set`，即 `UF_HIDDEN`）。我们自己若要预生成它们，
   这个标志也要带上。
4. **`--bootefi` 会先比较再决定写不写**：`boot.efi unchanged … Skipping update`。
   这解释了第 A.6.7 节为什么 Preboot 里那份 `boot.efi` 与系统卷上那份 SHA-256 相同 ——
   不是巧合，是 `bless` 的幂等逻辑。
5. **`bless` 用「volume group 里有没有一个与当前运行的 macOS 兼容的 System role 卷」
   来定位目标。** 即它**依赖 volume group 已经建好**（`V-031`），而且**依赖当前运行的
   macOS 与目标版本兼容** —— 这是一条本项目此前完全没有的约束：
   **在 25G76 的运行器上 bless 一块 25G325 的盘，这条检查会怎么判，未知。**
   登记为 **`V-033`**。（缓解：我们的第一块盘走 R1 路径，源就是运行器自己，版本必然一致。）
6. **`Found system volume UUID path in preboot for disk3s1`** —— 再一次印证
   Preboot 里那个目录名就是 volume group / Data 卷的 UUID（第 A.3.3a 节）。

**这一轮最后还是失败了，但失败原因是我们自己的脚本 bug，不是 `bless` 的限制：**

```text
Volume does not have system role
Snapshot options are only available for system volumes
Snapshot manipulation failed
Couldn't bless the APFS preboot volume for volume mounted at …: No such file or directory
   退出码 = 2
```

`vol_of "Macintosh HD"` 的前缀匹配把 **Data 卷**当成了系统卷（第 A.3.3a 节末段），
所以 `bless` 被指向一个没有 system role 的卷。`vol_of` 已修成精确匹配，
**下一轮才是 `V-021` 的最终答案**。

#### A.10.2c `V-021` 的最终答案，以及一条新的硬限制：`bless` 封不了第一次印

`TESTED(25G76)`，run `41279550835`。这一轮四个卷的 role 与分组都对、Preboot 的
`<VG_UUID>/System/Library/CoreServices` 事先建好、`boot.efi` 事先铺好。两个结果：

**（1）不带快照选项的 `bless` 成功（退出码 0），而且它写进 Preboot 的东西**
**只有三个文件**（`V-021` 关闭）：

```text
<VG_UUID>/System/Library/CoreServices/.disk_label       941 字节  0644 root:wheel  flags=0x8000
<VG_UUID>/System/Library/CoreServices/.disk_label_2x   3773 字节  0644 root:wheel  flags=0x8000
<VG_UUID>/System/Library/CoreServices/boot.efi       723512 字节  0644 root:wheel  flags=0
```

`0x8000` = `UF_HIDDEN`。两个 label 文件在系统卷那一侧还额外带一个 32 字节的
`com.apple.FinderInfo` xattr（`ls -lahO@` 可见），Preboot 那一侧没有。

**`bless` 没有写的（这一条比写了什么更重要）：**

| 第 A.6.7 节清单里的件 | `bless` 写吗 | 那谁写 |
|---|---|---|
| `.disk_label`、`.disk_label_2x`、`boot.efi` | **写** | — |
| **`.disk_label.contentDetails`** | **不写** | 待查。最可能是 `updatePreboot`，否则就得我们自己写（它是纯文本） |
| **`.root_uuid`** | **不写** | 同上。名字自明，内容应当是系统卷的 Volume UUID，**我们自己写得出来** |
| `SystemVersion.plist`、`PlatformSupport.plist` | **不写** | **我们自己铺**（第 A.6.6 节第 1 步，本来就是这么写的） |
| `BridgeVersion.bin`、`BridgeVersion.plist` | **不写** | 我们自己铺 |
| `boot/System/Library/KernelCollections/BootKernelExtensions.kc` | **不写** | 我们自己铺 |
| `System/Library/Caches/com.apple.corestorage/EFILoginLocalizations/` | **不写** | 我们自己铺，或 `updatePreboot` |

**所以第 A.6.7 节那张「谁铺什么」净表要改一处：A 类从 6 项缩到 3 项，
`.disk_label.contentDetails` 与 `.root_uuid` 移到 B 类（我们铺）。**

`bless --info --plist` 在成功之后的回读（`V-022` 的字段语义进一步明确）：

```xml
<key>Bless Info</key>
<array>
  <dict><key>Directory ID</key><integer>24</integer>
        <key>Path</key><string>/…/mp/9BF59C23-…/System/Library/CoreServices/boot.efi</string>
        <key>Relative Path</key><string>/9BF59C23-…/System/Library/CoreServices/boot.efi</string></dict>
  <dict><key>Directory ID</key><integer>21</integer>
        <key>Path</key><string>/…/mp/9BF59C23-…/System/Library/CoreServices</string>
        <key>Relative Path</key><string>/9BF59C23-…/System/Library/CoreServices</string></dict>
</array>
```

**`Relative Path` 是相对 Preboot 卷根的路径** —— 这是第 C.1 节最好用的那条离线判据：
`Bless Info` 的两项 `Directory ID` 都非 0，且 `Relative Path` 以 `/<VG_UUID>/` 开头。
另外 `diskutil info -plist <系统卷>` 里的键名是 **`APFSVolumeGroupID`**，值与 Data 卷的
Volume UUID 相同（第 A.3.3a 节）。

**（2）带 `--create-snapshot` 的 `bless` 失败，而且失败原因是一条此前完全没有的限制：**

```text
Can't use snapshot options on non ARV volume
Snapshot manipulation failed
Couldn't bless the APFS preboot volume for volume mounted at …: No such file or directory
   退出码 = 2
```

> [!CAUTION]
> **`bless --create-snapshot` 要求目标卷**已经**是 ARV（Authenticated Root Volume）。
> 一个刚建出来、从未封印过的 APFS 卷不是 ARV，所以 `bless` 封不了第一次印。**
>
> 这解释了为什么第 0.2 节引的 OCLP 那条命令能用：**OCLP 操作的是一块已经是 ARV 的盘**
> —— 它只是在一个已封印的卷上**再**造一个（破封的）快照。
> 「从零建卷 → 铺内容 → `bless --create-snapshot` 封印」这条路**在 `bless` 这一层走不通**。
>
> 登记为 **`V-034`，它取代 `V-031` 成为现在的第一优先。**

**`V-034` 的三条候选解，按可行性：**

| # | 做法 | 为什么可能 | 代价 |
|---|---|---|---|
| **S1** | **`asr restore --toSnapshot <源的封印快照 UUID> --erase`**，即 `75` 的 R1 路径 | `75` 第 2.3.2 节已引手册：目标是分区且带 `--erase` 时，**被恢复的卷连同 Preboot/Recovery 一起从源复制**。源是一块已封印的 ARV 卷，**ARV 这个属性随块级复制一起过来** —— 这正是「第一次印」的来源 | 产出的 build 是源那一版（运行器的 25G76，不是 25G325）。**但它不需要我们自己封印** |
| **S2** | 自己调 `fs_snapshot` 系统调用：`fs_snapshot_create` 之后 `fs_snapshot_root` | `77` 第 D.3 节已证 UpdateBrain 的封印就是 `-[LPStaticAPFSVolume createSnapshot:error:]`（RVA `0x145024`）里一条 `fs_snapshot_create(2)`，**不签名不联网**。`fs_snapshot` 的 op 里有 `SNAPSHOT_OP_ROOT`，正是「把某个快照设成卷的 root snapshot」 | 要写一个几十行的 C 程序。**而且 `fs_snapshot_create` 能不能在一个非 ARV 卷上把它变成 ARV，未知** —— 这是 S2 的核心风险 |
| **S3** | 不要 ARV：让 `boot.efi` 直接从卷（而不是快照）启动，靠 `csr-active-config` 的 bit 11（`CSR_ALLOW_UNAUTHENTICATED_ROOT`）放行 | 第 0.2 节的研发期设定本来就是 SIP/AMFI 全关。而 bit 11 的用途正是「允许启动一个未经认证的根」。Catalina 之前的 macOS 本来就是从卷启动的 | **只能启动才知道**，与 `V-025` 同级。若成立，整条封印问题消失；若不成立，表现是禁止符号 |

**三条之间不互斥，而且第一块盘的正解很可能是 S1 + S3 并行验证：**
走 R1（`asr`）拿到一块必然能启动的盘作为基线，同时在同一轮里造一块 S3 形态（无快照）的盘，
对照启动结果。这把「ARV 到底是不是必须的」这个问题用一次 E0-L1 同时答掉。

**这一条对 `75`/`77` 的影响，必须写清：**

- **`75` 的 R1（`asr` 克隆运行器）从「先做的那条」升级为「唯一已知能产出 ARV 的那条」。**
  它不再只是「简单」，而是**承载了第一次封印**。
- **`77` 的 R6（UpdateBrain）价值上升：** 它是唯一能既产出 25G325、又自带封印的路径。
  原来的判断是「R6 的价值只在 build 保真」，现在要加一句「以及它自己会封印」。
- **`78` 第 A.9 节（快照层）的规格不变**（它描述的是封印后的状态），
  但第 A.10.1 节那条「`bless --folder … --bootefi --create-snapshot` 一条命令做四件事」
  要加限定：**只在目标已是 ARV 时成立。**

#### A.10.3 它到底写了什么

**这是第 D 节最想回答的问题之一。现在能说的：**

| 层 | 写了什么 | 标签 |
|---|---|---|
| **Preboot 卷** | **恰好三个文件**：`<VG_UUID>/System/Library/CoreServices/` 下的 `boot.efi`（723,512 B、flags 0）、`.disk_label`（941 B、`UF_HIDDEN`）、`.disk_label_2x`（3773 B、`UF_HIDDEN`），全部 `0644 root:wheel` | **`TESTED(25G76)`**，`V-021` 已关闭，逐项 stat 见第 A.10.2c 节 |
| **System 卷的 `CoreServices`** | **同样的两个 label 文件**（941 / 3773 字节，`UF_HIDDEN`，另带 32 字节 `com.apple.FinderInfo` xattr）。1.0 完全没有这一行 | `TESTED(25G76)` |
| **System 卷的 APFS 字段** | blessed 目录/文件各记成一个 `Directory ID`（APFS inode）+ `Path` + `Relative Path`，后者相对 **Preboot 卷根**。本次的值是 `24`（`boot.efi`）与 `21`（`CoreServices`）。**root snapshot 指针没写** —— `--create-snapshot` 在非 ARV 卷上被拒 | `TESTED(25G76)`，字段名已关闭；root snapshot 那一半 → `V-034` |
| **HFS+ 卷头** | 手册明说 Folder Mode 在 HFS+ 卷上更新卷头。**我们是 APFS，这一条不适用** | `KNOWN` |
| **固件 NVRAM** | **不写。** 只有 `--setBoot` 才写，而我们禁止它 | `KNOWN` |

**取证方法是现成的，而且不需要写新工具：`bless --verbose` 的输出本身就是清单。** 第 D 节的 `preboot-probe` job 在一块 scratch 磁盘镜像上跑一次完整的 `bless --folder … --bootefi --create-snapshot --label … --verbose`，把输出与「跑之前 / 跑之后的 Preboot 全树 diff」一起落盘。**那两样东西合起来就是第 A.10.3 节这张表的确定答案。**

#### A.10.4 `bless --info` 是离线验证的主要手段

```bash
sudo bless --info "$SYSROOT" --plist
```

手册：Info Mode 打印挂载在给定目录的卷的 blessed system folder；不给目录时打印当前选定的启动设备（**这一条在 Apple Silicon 上不支持，在 Intel 上支持**）。`--plist` 让输出变成可被 CoreFoundation 解析的 property list，手册明说这是从别的程序里调 `bless` 并要解析其标准输出时最有用的形式。

**所以 `bless --info <目标挂载点> --plist` 是第 C.1 节 L0 门禁的核心命令。** 注意必须给挂载点参数：**不给参数时它读的是运行器自己的启动设备**，那不是我们要验的东西。

---
## B. 从零构建的完整步骤

### B.1 顺序的依据：对照 UpdateBrain 自己的步骤

`77` 第 A.3 与 C.5 节给出了 `MSUTargetController` 的方法清单与一份调用骨架。**把它的方法名按语义排序，就得到 Apple 自己的步骤顺序。** 本节逐条对照，并标明我们做、跳过、还是换工具。

| # | UpdateBrain 的那一步（RVA 见 `77` §A.3） | 我们做吗 | 用什么 |
|---|---|---|---|
| 1 | `-setSystemTargetWithVolumeGroupUUID:`（`0xf34d`）指定目标 | **自己记下 VG UUID** | 第 A.3.2 节第 5 步 |
| 2 | `-configureTargetVolumeForInstallWithError:`（`0x1078b`）配置目标卷 | **做** | `diskutil apfs createContainer` + 四次 `addVolume`（第 A.2、A.3 节） |
| 3 | `-configureUpdateVolumeInContainer:reserveSize:erase:error:`（`0xfa1e`） | **跳过** | 不要 Update 卷（`76` §1.4） |
| 4 | `-configureXARTPartitionWithError:`（`0x102eb`） | **跳过** | 无 T2，无 SEP（`77` §E.3） |
| 5 | `-validateTargetVolumeConfiguration:`（`0x1067f`）校验 | **做，换成我们自己的** | 第 C.1 节 L0 门禁第 1 组 |
| 6 | `-prepareTargetVolumeForInstallRevertingToSnapshot:error:`（`0x12d54`）准备/挂载目标卷 | **做**（空卷无快照可回滚，等价于传 `nil`） | `mount -o nobrowse -t apfs`（与 OCLP 同形，第 0.2 节） |
| 7 | `_prepare_snapshot`（`0x5574e`）内的 `copy_patched_files` / `copy_archived_files` / `set_hardlinks` / `verify_postbom` 铺内容 | **做。这一步是我们必须自己写的那一块** | `ditto --hfsCompression` + `chown` + `chflags`（第 A.4.3 节） |
| 8 | `-[MSUMigrationHelper dataTemplatePath]`（`0x11aae9`）+ `-createFirmlinks`（`0x11aade`） | **做前半（Data 模板），后半待 `V-013`** | 第 A.5.3 节 |
| 9 | `_personalize_boot_bundle`（`0x27a5f`）的 cryptex1 个性化 | **跳过**（`77` §D.3 的逃生门：无 boot bundle 时只 `symlink target/boot`） | — |
| 10 | `-populateSystemPrebootWithVariant:withError:`（`0x13a39`）+ `MSUBootObjectCopier`（`0x125c2b` 等） | **做，换成两条 macOS 自带命令** | `bless --bootefi`（事实 1）+ `diskutil apfs updatePreboot`（事实 2） |
| 11 | `-populatePairedRecoveryWithVariant:…`（`0x1499a`） | **跳过** | 不要 Recovery 卷（第 A.7 节） |
| 12 | `-[LPStaticAPFSVolume createSnapshot:error:]`（`0x145024`）→ `fs_snapshot_create` 封印 | **做，由 `bless --create-snapshot` 顺带完成** | 第 A.9、A.10 节 |
| 13 | `_prepare_boot_environment`（`0x852d`）的 `bless … --setBoot` + 写 NVRAM fallback | **绝对跳过** | 第 A.10.2 节的护栏 |

**从这张表读出三件事：**

1. **13 步里我们跳过 5 步（#3、#4、#9、#11、#13），全部有具体理由，没有一条是「太难所以不做」。**
2. **必须我们自己做、没有 Apple 工具可替的，只有 #7 一步**（铺 payload 内容）。#5 和 #8 是「有 Apple 的做法但我们换了等价手段」。
3. **#12（封印）不是单独一步，它被 #10 的 `bless` 吃掉了。** 这是第 A.9.3 节的结论。

**顺序上有一条不可调换的：#7 必须在 #12 之前，而且 #12 之后不能再碰 System 卷。** 第 B.2 节的脚本用一条显式的「封印线」把它标出来。

### B.2 可照抄的完整脚本

```bash
#!/usr/bin/env bash
# scripts/build-apfs-volumes.sh
#
# 从一个空的 raw 文件造出一块能被 OpenCore 引导的盘。
# 执行环境：macos-26-intel 运行器（SIP 已关，runner 有免密 sudo）。
# 全程 macOS 自带工具。不经 Linux。不碰运行器自己的引导。
#
# 用法：  build-apfs-volumes.sh <out.raw> <size_gb> <payload_stage_dir> <index.tsv>
#
# 前置：$3 是一棵与 payload 逻辑路径同构的已解出内容树（71 §2.1 的 extract 产物）
#       $4 是 analysis/binaries/macos26-25G325-x86_64/payloadv2-full-index.tsv
set -euo pipefail

IMG="${1:?out.raw}"; SIZE_GB="${2:-16}"
STAGE="${3:?payload stage dir}"; IDX="${4:?index tsv}"

REPO="${REPO:-$(cd "$(dirname "$0")/.." && pwd)}"   # 仓库根，用来找 tools/ci/mkgpt.py
ESP_MIB=512
SECT=512
APFS_PART=2            # A.1.3：加回 BaseSystem 分区时改成 3
MNT_SYS=/System/Volumes/Update/mnt1          # 与 OCLP 同一个位置（0.2 节）
MNT_DATA=$(mktemp -d /tmp/d8data.XXXXXX)
MNT_PRE=$(mktemp -d /tmp/d8pre.XXXXXX)
VOLNAME_SYS="Macintosh HD"
VOLNAME_DATA="Macintosh HD - Data"
LABEL="macOS 26.7.2"

log() { printf '\n=== [%s] %s\n' "$(date -u +%H:%M:%S)" "$*"; }

# ───────────────────────── 步 1：只造空 raw，**先不 attach** ─────────────────────────
# 1.1 改动：attach 挪到步 2 之后。理由是分区表现在离线写进这个普通文件（A.1.0），
# 而 hdiutil 一旦 attach，MediaKit 就按它当时看到的（空）分区表建设备节点，
# 之后在文件里改表它不会重新解析。顺序必须是 建文件 → 写表 → attach。
# 工具：mkgpt.py 自己会 truncate 到指定大小，所以连 dd 都不需要。
log "1  造稀疏 raw"
mkdir -p "$(dirname "$IMG")"
: > "$IMG"
trap 'sudo diskutil unmount force "$MNT_PRE" 2>/dev/null || true;
      sudo diskutil unmount force "$MNT_DATA" 2>/dev/null || true;
      sudo diskutil unmount force "$MNT_SYS" 2>/dev/null || true;
      [ -n "${DEV:-}" ] && hdiutil detach "$DEV" 2>/dev/null || true' EXIT

# ──────────────────── 步 2：GPT 两分区（A.1，1.1 已改工具）────────────────────
# 工具：tools/ci/mkgpt.py（自有，纯 Python）。
#   换不了 gpt(8)：它的修改类子命令在 25G76 上一律 operation not permitted（A.1.0）。
#   换不了 diskutil partitionDisk：它会自己决定 ESP 大小。
# 注意两件事（都是 1.1 的实测结论）：
#   (a) 这一步必须在 hdiutil attach **之前**做 —— 它写的是普通文件。
#       所以步 1 的 attach 要挪到这一步之后。
#   (b) p2 写成 hfs 而不是 apfs，让步 3 的 createContainer 自己改类型（A.1 约束 3）。
# 失败表现：mkgpt.py verify 报边界/重叠 → 扇区算术错了，它会指出是哪一条。
log "2  GPT"
python3 "$REPO/tools/ci/mkgpt.py" create "$IMG" \
        --size "$(( SIZE_GB * 1024 * 1024 * 1024 ))" \
        --part "auto:$(( ESP_MIB * 1024 * 1024 )):efi:EFI" \
        --part "auto:auto:hfs:$VOLNAME_SYS"
python3 "$REPO/tools/ci/mkgpt.py" verify "$IMG"

# 现在才 attach。-nomount 是必须的：此刻 p2 只是一个声称自己是 HFS+ 的空分区。
# 失败表现：报 "image not recognized" 说明漏了 CRawDiskImage imagekey；
#           "no mountable file systems" 是正常的（我们给了 -nomount）。
DEV=$(hdiutil attach -imagekey diskimage-class=CRawDiskImage -nomount "$IMG" \
      | awk '/^\/dev\/disk/{print $1; exit}')
RAW="${DEV/disk/rdisk}"
echo "DEV=$DEV  RAW=$RAW"
diskutil list "$DEV"     # 这里必须看到 s1=EFI、s2=Apple_HFS

# ESP 的内容不是本文的事（75 §0.0.1 + 76 §3.2）。这里只建文件系统占位。
# 必须用 newfs_msdos，不能用 diskutil eraseVolume FAT32 —— 后者会把 p1 的
# 类型 GUID 改成 Microsoft Basic Data，固件就不再把它当 ESP（A.1.2）。
sudo newfs_msdos -F 32 -v OPENCORE "${RAW}s1"

# ───────────────────── 步 3：APFS container（A.2）─────────────────────
# 工具：diskutil apfs（自带）。换不了：Linux 侧没有能建带 role 的多卷容器的实现（75 §0.0）。
# 失败表现：报 -69614 "The disk is already in use by APFS" → 步 2 把 p2 写成了
#           APFS 类型。它必须是 Apple_HFS（A.1 约束 3）。
log "3  APFS container"
sudo diskutil apfs createContainer "${DEV}s${APFS_PART}"
CNT=$(diskutil info -plist "${DEV}s${APFS_PART}" \
      | plutil -extract APFSContainerReference raw -o - - 2>/dev/null \
      || diskutil list "${DEV}" | awk '/APFS Container Scheme/{print $NF}')
echo "CNT=$CNT"
# createContainer 会自己把 p2 的类型改成 7C3457EF-…。确认一下（只读，gpt show 可用）。
sudo gpt -r show "$RAW" | grep -F 7C3457EF-0000-11AA-AA11-00306543ECAC \
  || { echo "FATAL(V-001): 建完容器后 p2 的类型 GUID 不是 APFS"; exit 1; }

# ─────────────────────── 步 4：四个卷（A.3）───────────────────────
# 工具：diskutil apfs addVolume（自带）。四个 role 实测全部可设（A.3.3）。
# !! 顺序：**Data 第一个建**，System 再成组到它。反过来会被内核拒：
#    apfs_newfs: A Non-sealed system sibling volume is not allowed（A.3.3a / V-031）。
log "4  四个卷"
# vol_of 必须精确匹配：$VOLNAME_SYS 是 $VOLNAME_DATA 的前缀（A.3.3a 末段）。
vol_of() {
  local want="$1" v n
  for v in $(diskutil list "$CNT" 2>/dev/null | awk '/APFS Volume/{print $NF}'); do
    n=$(diskutil info "$v" 2>/dev/null \
        | awk -F': *' '/^ *Volume Name/{gsub(/[ \t]+$/,"",$2); print $2; exit}')
    [ "$n" = "$want" ] && { printf '%s' "$v"; return 0; }
  done
  return 1
}

sudo diskutil apfs addVolume "$CNT" APFS "$VOLNAME_DATA" -role D -nomount
DATA=$(vol_of "$VOLNAME_DATA")
sudo diskutil apfs addVolume "$CNT" APFS "$VOLNAME_SYS" \
     -role S -groupWith "$DATA" -nomount
SYS=$(vol_of "$VOLNAME_SYS")
diskutil apfs listVolumeGroups "$CNT" | grep -qF "$SYS" \
  || { echo "FATAL(V-031): System 卷没和 Data 卷成组"; exit 1; }
sudo diskutil apfs addVolume "$CNT" APFS "Preboot" -role B -nomount
PRE=$(vol_of "Preboot")
sudo diskutil apfs addVolume "$CNT" APFS "VM"      -role V -nomount
VM=$(vol_of "VM")
echo "SYS=$SYS DATA=$DATA PRE=$PRE VM=$VM"

VG=$(diskutil apfs listVolumeGroups -plist "$CNT" \
     | plutil -extract Containers.0.VolumeGroups.0.APFSVolumeGroupUUID raw -o - - 2>/dev/null \
     || diskutil info "$SYS" | awk -F': *' '/Volume Group UUID/{print $2}')
echo "VG=$VG"
[ -n "$VG" ] || { echo "FATAL: 取不到 volume group UUID，Preboot 的目录名无从得知"; exit 1; }

# ─────────────────── 步 5：L0 门禁第 1 组（C.1）在铺内容之前 ───────────────────
log "5  门禁：role 与 volume group"
diskutil apfs list "$CNT"
diskutil apfs listVolumeGroups "$CNT"
for want in "(System)" "(Data)" "(Preboot)" "(VM)"; do
  diskutil apfs list "$CNT" | grep -qF "$want" \
    || { echo "FATAL: 缺 role $want"; exit 1; }
done

# ─────────────────────── 步 6：挂载目标三个卷 ───────────────────────
# 工具：mount(8) -t apfs（自带）。-o nobrowse 与 OCLP 同形（0.2 节）。
log "6  挂载"
sudo mkdir -p "$MNT_SYS"
sudo mount -o nobrowse -t apfs "/dev/$SYS"  "$MNT_SYS"
sudo mount -o nobrowse -t apfs "/dev/$DATA" "$MNT_DATA"
sudo mount -o nobrowse -t apfs "/dev/$PRE"  "$MNT_PRE"

# 护栏（A.10.2）：确认我们不是在对运行器的根盘动手。
# 取整盘标识读 diskutil 的「Part of Whole」，不要用 ${var%%s*}（A.10.2 的 1.1 注记）。
whole_of() {
  diskutil info "$1" 2>/dev/null \
    | awk -F': *' '/^ *Part of Whole/{gsub(/[ \t]+$/,"",$2); print $2; exit}'
}
SYS_DISK=$(whole_of "$MNT_SYS"); ROOT_DISK=$(whole_of /)
[ -n "$SYS_DISK" ] && [ -n "$ROOT_DISK" ] \
  || { echo "FATAL: 取不到整盘标识，未确定就不动手"; exit 1; }
[ "$SYS_DISK" != "$ROOT_DISK" ] \
  || { echo "FATAL: 目标与 / 在同一块物理盘上（都是 $SYS_DISK）"; exit 1; }

# ───────────────── 步 7：铺 System 卷内容（A.4）—— 唯一必须自己写的一步 ─────────────────
# 工具：ditto --hfsCompression（自带）。换不了 cp/rsync/tar：见 A.4.3 的四条理由。
# 失败表现：No space left → 容器太小；du 远大于 5.5 GB → --hfsCompression 没生效。
log "7  铺 System 卷内容"
# 7a. 剔掉 arm64 的 13 个内核（A.4.1）。第一轮只做这一条瘦身。
rm -f "$STAGE"/System/Library/Kernels/kernel.release.* 2>/dev/null || true
# 7b. 主体
sudo ditto --hfsCompression --persistRootless "$STAGE" "$MNT_SYS"
# 7c. 所有者（V-008 定版前一刀切）
sudo chown -R root:wheel "$MNT_SYS"
# 7d. SF_RESTRICTED。必须最后，必须逐条，不能 -R，不能把 FLG 原样铺（A.4.2 规则 1）
awk -F'\t' 'NR>1 && ($5=="524288" || $5=="524320"){print $1}' "$IDX" \
  | while IFS= read -r p; do printf '%s\0' "$MNT_SYS/$p"; done \
  | sudo xargs -0 -n 200 chflags restricted
# 7e. 实占，与 A.4.5 的预算比对（V-010）
df -h "$MNT_SYS"; diskutil info "$SYS" | grep -iE 'Volume Used Space|Capacity'

# ──────────────────── 步 8：铺 Data 卷（A.5）────────────────────
log "8  铺 Data 卷"
sudo ditto --hfsCompression --persistRootless \
     "$MNT_SYS/System/Library/Templates/Data/" "$MNT_DATA/"
sudo chown -R root:wheel "$MNT_DATA"
test -f "$MNT_SYS/usr/share/firmlinks" || { echo "FATAL: System 卷上没有 firmlinks 表"; exit 1; }
echo "firmlinks 字节数: $(stat -f%z "$MNT_SYS/usr/share/firmlinks")   期望 689"

# ──────── 步 9：离线预配（75 §5.8 的 9 项 + 76 §6.5 的 75-F 的 2 项 1 目录）────────
# 全部落在 Data 卷上，所以不碰封印。本文不重复清单，只调用它们的脚本并断言。
log "9  离线预配"
if [ -x scripts/preconfigure-data-volume.sh ]; then
  sudo scripts/preconfigure-data-volume.sh "$MNT_DATA"
else
  echo "WARN: 预配脚本不在，跳过。L-024：漏了确认 daemon 会让每台新实例三次启动后被切到 Alpine"
fi
test -f "$MNT_DATA/Library/LaunchDaemons/net.metal2vu.cpudisp-confirm.plist" \
  || echo "WARN(L-024): 确认 daemon 缺失"

# ────────── 步 10：Preboot 的用户元数据（A.6.2 事实 2）—— 必须在预配用户之后 ──────────
# 工具：diskutil apfs updatePreboot（自带）。
# 失败表现：报 "An APFS crypto user was not found in the Open Directory user database"
#           说明步 9 的用户还没写进 dslocal。
log "10  updatePreboot"
sudo diskutil apfs updatePreboot "$SYS" \
     -od "$MNT_DATA/private/var/db/dslocal/nodes/Default" || \
sudo diskutil apfs updatePreboot "$SYS" || \
echo "WARN(V-023): updatePreboot 失败。bless 仍可能铺齐 boot objects，继续"

# ──────────── 步 11：Preboot 的补充件（A.6.6）。boot objects 交给步 12 的 bless ────────────
log "11  Preboot 补充件"
PBCS="$MNT_PRE/$VG/System/Library/CoreServices"
sudo mkdir -p "$PBCS"
for f in SystemVersion.plist PlatformSupport.plist; do
  sudo ditto "$MNT_SYS/System/Library/CoreServices/$f" "$PBCS/$f"
done
printf '%s' "$LABEL" | sudo tee "$PBCS/.contentDetails" >/dev/null
sudo chown -R root:wheel "$MNT_PRE/$VG"
# V-015：Preboot 卷根下的 Cryptexes/ 待第 D 节取证后补。不要猜着铺。

# ══════════════════════════ 封印线 ══════════════════════════
# 1.1 注：在 S3 形态（无快照，V-034）下这条线不再有技术约束 —— 没有快照，
# 也就不存在「改了不进快照」的问题。但**纪律上仍然保留它**：一旦 V-034 走通
# S1 或 S2，这条线立刻又变成硬约束，而那时才发现脚本里有越线的写操作就太晚了。
# 这一行以下不得再写 System 卷。步 12 的快照一旦建成，
# 后续对 System 卷的任何改动都不进快照 = 改了等于没改（A.9.4 末行）。
# ═══════════════════════════════════════════════════════════

# ───────── 步 12：bless（A.10）。封印拆出去成了步 12b ─────────
# 工具：bless(8)（自带）。禁止 --setBoot / --mount / --personalize（A.10.2）。
# 前置条件（A.6.6 的 IMPORTANT 块）：$MNT_PRE/$VG/System/Library/CoreServices 必须已存在，
#   否则 bless 报 "No valid group or volume UUID folder" 并且一个文件都不写。
# !! 1.1 实测：**不要带 --create-snapshot**。一块从零建出来的卷不是 ARV，
#    带上它会被拒（"Can't use snapshot options on non ARV volume"，退出码 2），
#    而且连前面那些该写的文件也一起不写。去掉之后退出码 0（A.10.2c / V-034）。
log "12  bless --bootefi（不带快照选项）"
test -d "$MNT_PRE/$VG/System/Library/CoreServices" \
  || { echo "FATAL: Preboot 里没有 $VG/System/Library/CoreServices，bless 会失败"; exit 1; }
sudo bless --folder "$MNT_SYS/System/Library/CoreServices" \
           --bootefi \
           --label "$LABEL" \
           --verbose
# 立刻验 bless 真的写进去了（A.10.2c 的三个文件）
for f in boot.efi .disk_label .disk_label_2x; do
  test -f "$MNT_PRE/$VG/System/Library/CoreServices/$f" \
    || { echo "FATAL: bless 没在 Preboot 里写出 $f"; exit 1; }
done

# ───────── 步 12b：封印（A.9）—— 这一层目前没有已验证的自建手段 ─────────
# V-034：bless 封不了第一次印。三条候选解在 A.10.2c：
#   S1  走 75 的 R1（asr restore --toSnapshot … --erase），ARV 随块级复制过来。
#       这条路下，本脚本的步 2..12 都不用跑 —— asr 把整个卷组连 Preboot 一起复制。
#   S2  自己写一个调 fs_snapshot_create + fs_snapshot_root 的小程序。
#   S3  干脆不要 ARV，靠 csr-active-config 的 bit 11 放行从卷（非快照）启动。
# 本脚本按 S3 走：**什么都不做**，并把这个事实打出来，让 80 的 E0-L1 去判。
log "12b 封印（V-034：按 S3 形态，不建快照）"
echo "NOTE(V-034): 本块盘没有 root snapshot，按 S3 形态启动。"
echo "             需要 csr-active-config bit 11 (CSR_ALLOW_UNAUTHENTICATED_ROOT)，"
echo "             71 §6.7 的 NVRAM/Add 里 0xFEF 已包含它。"
diskutil apfs listSnapshots "$MNT_SYS" 2>&1 || true
diskutil info "$SYS" | grep -iE 'Sealed|Snapshot' || true

# ───────────────── 步 13：离线验证（C.1 的 verify-image.sh）─────────────────
log "13  离线验证"
sudo bless --info "$MNT_SYS" --plist || true
diskutil apfs listSnapshots "$SYS"
sudo find "$MNT_PRE" -maxdepth 6 | sort

# ───────────────── 步 14：卸载、收尾、detach ─────────────────
log "14  收尾"
sudo diskutil unmount "$MNT_PRE"  || sudo diskutil unmount force "$MNT_PRE"
sudo diskutil unmount "$MNT_DATA" || sudo diskutil unmount force "$MNT_DATA"
sudo diskutil unmount "$MNT_SYS"  || sudo diskutil unmount force "$MNT_SYS"
# 1.1：不再需要 `gpt recover` —— 一则它和 gpt 的其余修改类子命令一样被拒（A.1.0），
# 二则 mkgpt.py 一次就把备份头与备份项数组写在真实盘尾，本来就不需要事后搬。
# 只做一次只读复核：mkgpt.py verify 会重新从字节核对两个头的 CRC 与几何。
python3 "$REPO/tools/ci/mkgpt.py" verify "$IMG"
trap - EXIT
hdiutil detach "$DEV"
echo "DONE: $IMG"
```

### B.3 这 14 步里哪几步是我们必须自己做的

| 步 | 性质 | 有没有 Apple 工具替我们做 |
|---|---|---|
| 1、2 | 机械 | 有（`hdiutil`、`gpt`），`75` §0.0.1 已定 |
| 3、4 | 机械 | 有（`diskutil apfs`） |
| 5、13 | **我们自己写** | 无。Apple 的等价物是 `-validateTargetVolumeConfiguration:`，我们换成第 C.1 节的门禁 |
| 6 | 机械 | 有（`mount`），与 OCLP 同形 |
| **7** | **我们自己写，而且是本文最重的一步** | **无。** Apple 的等价物是 `_prepare_snapshot`（RVA `0x5574e`）里的四个 C 函数，`77` 第 C.5 节已判「自己编排等于重写它，工作量不小」 |
| **8** | **我们自己写** | 半有。模板在 payload 里，铺它是机械的；但 `createFirmlinks` 的等价入口未知（`V-013`） |
| 9 | 我们自己写 | 无，但清单已在 `75` §5.8 与 `76` §6.5 |
| 10、12 | 机械 | **有，而且这是本轮最大的收获**（`updatePreboot` 与 `bless --bootefi --create-snapshot`） |
| **11** | **部分我们自己写，部分待取证** | boot objects 有（`bless`）；cryptex 未知（`V-015`） |
| 14 | 机械 | 有 |

**一句话：14 步里真正需要我们写代码的是 4 步（5/13 的验证、7 的铺内容、8 的 Data 骨架、9 的预配），其中只有第 7 步有工程量。** 第 11 步的 cryptex 子项是唯一一处「不知道要写什么」的地方。

---
## C. 验证：怎么知道造对了

分两级。**L0 是在运行器上、不启动就能跑完的；L1 是只有启动才知道的。** 两级之间没有中间档：L0 全绿不蕴含能启动，但 L0 有红必定起不来。

### C.1 L0：离线可验的

#### C.1.1 门禁清单

| # | 判据 | 怎么验 | 红了说明什么 |
|---|---|---|---|
| **L0-1** | 容器里恰好有 4 个卷，role 分别是 System / Data / Preboot / VM | `diskutil apfs list "$CNT"` 逐个 grep `(System)` `(Data)` `(Preboot)` `(VM)` | 第 A.3.4 节对应行 |
| **L0-2** | volume group 恰好 1 个，成员恰好 2 个（role S 与 role D）。**Preboot 与 VM 不在组里** | `diskutil apfs listVolumeGroups "$CNT"` | 第 A.3.4 节第 2、3 行 |
| **L0-3** | System 卷上恰好 1 个快照，而且它是 root snapshot | `diskutil apfs listSnapshots "$SYS"` | 第 A.9.4 节 |
| **L0-4** | `<PRE>/<VG>/System/Library/CoreServices/boot.efi` 存在，**且字节数 = 723,512** | `stat -f%z` | 第 A.6.3 节。字节数不对说明 `--bootefi` 取了别的源 |
| **L0-5** | 同目录下 `PlatformSupport.plist` = 790 字节、`SystemVersion.plist` = 604 字节 | `stat -f%z` | 第 A.6.3 节。**字节数不对是「板卡 ID 门」会挡住启动的那一类** |
| **L0-6** | 同目录下 `.disk_label` 与 `.disk_label_2x` 存在且非空 | `test -s` | `bless --label` 没生效 |
| **L0-7** | `bless --info <MNT_SYS> --plist` 能输出，且 blessed folder 指向 `<MNT_SYS>/System/Library/CoreServices` | `bless --info … --plist` + `plutil` | 第 A.10.4 节 |
| **L0-8** | System 卷上 `usr/share/firmlinks` 存在且 = 689 字节 | `stat -f%z` | 第 A.5.2 节 |
| **L0-9** | System 卷上存在且可读 `System/Library/KernelCollections/BootKernelExtensions.kc`（67,584,000）与 `SystemKernelExtensions.kc`（369,213,440） | `stat -f%z` + `head -c 4096 > /dev/null` | **`head` 失败 = 第 0.3.1 节规则 1 被违反** |
| **L0-10** | 抽 200 个带 `AFT` 的路径，逐个确认「`stat -f%z` 非零 **且** `head -c 1` 读得出字节」 | 见下的 `verify-image.sh` | 同上。**这一条是 decmpfs 一致性的实际判据** |
| **L0-11** | 容器的 APFS jumpstart 区域非空（`apfs.efi` 在里面） | 见下，`V-018` | 空的话 OpenCore 看不见容器里任何卷 |
| **L0-12** | Data 卷上 `Library/LaunchDaemons/net.metal2vu.cpudisp-confirm.plist` 存在 | `test -f` | `76` 的 `L-024`：漏了它每台新实例三次启动后会被误切到 Alpine |
| **L0-13** | System 卷与源系统的逐项比对：抽 2,000 个路径核对「存在 + 字节数 + mode」 | 见下 | 铺内容漏了或权限错 |
| **L0-14** | 没有任何一处的所有者不是 `root:wheel`（已知例外清单为空，`V-008`） | `find … ! -user root -o ! -group wheel` | 第 A.4.2 节 |

#### C.1.2 可照抄的 `verify-image.sh`

```bash
#!/usr/bin/env bash
# scripts/verify-image.sh
#
# L0 离线验证。在 macos-26-intel 运行器上对一块已造好、已挂载的镜像跑。
# 不启动、不修改任何东西、不碰运行器自己的盘。
#
# 用法： verify-image.sh <container-ref-disk> <sys-mnt> <data-mnt> <preboot-mnt> <vg-uuid> <index.tsv>
# 退出码： 0 = 全绿；1 = 有红（逐条打印）
set -uo pipefail

CNT="${1:?}"; MS="${2:?}"; MD="${3:?}"; MP="${4:?}"; VG="${5:?}"; IDX="${6:?}"
FAIL=0
ok()   { printf '  OK   %s\n' "$*"; }
bad()  { printf '  FAIL %s\n' "$*"; FAIL=1; }
head_() { printf '\n--- %s ---\n' "$*"; }

sz() { stat -f%z "$1" 2>/dev/null || echo -1; }

# ───────── L0-1 四个卷与 role ─────────
head_ "L0-1  卷与 role"
diskutil apfs list "$CNT"
for r in System Data Preboot VM; do
  diskutil apfs list "$CNT" | grep -qF "($r)" && ok "role $r 在位" || bad "缺 role $r"
done
for r in Recovery Update XART Hardware; do
  diskutil apfs list "$CNT" | grep -qF "($r)" && echo "  note 有可选卷 $r" || true
done

# ───────── L0-2 volume group ─────────
head_ "L0-2  volume group"
diskutil apfs listVolumeGroups "$CNT"
NGRP=$(diskutil apfs listVolumeGroups "$CNT" | grep -c 'Volume Group' || true)
NMEM=$(diskutil apfs listVolumeGroups "$CNT" | grep -cE '^\s+\|?\s*(APFS Volume Disk|Disk)' || true)
echo "  groups=$NGRP  members(粗计)=$NMEM"
[ "$NGRP" -ge 1 ] && ok "至少一个 volume group" || bad "没有 volume group"
# 精确判据：组里不得出现 Preboot 或 VM
diskutil apfs listVolumeGroups "$CNT" | grep -qE '\(Preboot\)|\(VM\)' \
  && bad "Preboot 或 VM 被放进了 volume group（A.3.4）" \
  || ok "Preboot 与 VM 不在 volume group 里"

# ───────── L0-3 快照 ─────────
head_ "L0-3  快照"
SYSDEV=$(diskutil info -plist "$MS" | plutil -extract DeviceIdentifier raw -o - - 2>/dev/null)
diskutil apfs listSnapshots "$SYSDEV" || true
NSNAP=$(diskutil apfs listSnapshots -plist "$SYSDEV" 2>/dev/null \
        | plutil -extract Snapshots raw -o - - 2>/dev/null | grep -c . || true)
echo "  snapshots=$NSNAP"
[ "${NSNAP:-0}" = "1" ] && ok "恰好一个快照" || bad "快照数不是 1（是 ${NSNAP:-0}）"

# ───────── L0-4/5/6 Preboot 三件 + 标签 ─────────
head_ "L0-4/5/6  Preboot"
PBCS="$MP/$VG/System/Library/CoreServices"
[ -d "$PBCS" ] && ok "per-VG 目录在位: $PBCS" || bad "per-VG 目录不存在: $PBCS"
check_sz() { local p="$1" want="$2"; local g; g=$(sz "$p")
  [ "$g" = "$want" ] && ok "$(basename "$p") = $want" || bad "$(basename "$p") = $g，期望 $want"; }
check_sz "$PBCS/boot.efi"             723512
check_sz "$PBCS/PlatformSupport.plist" 790
check_sz "$PBCS/SystemVersion.plist"   604
for f in .disk_label .disk_label_2x; do
  [ -s "$PBCS/$f" ] && ok "$f 非空（$(sz "$PBCS/$f") 字节）" || bad "$f 缺失或为空"
done
# boot.efi 的哈希与签名状态（只记录，不作判据 —— 25G325 的期望值见 D 节回填）
shasum -a 256 "$PBCS/boot.efi" 2>/dev/null || true
codesign -dvvv "$PBCS/boot.efi" 2>&1 | sed -n '1,12p' || true

# ───────── L0-7 bless --info ─────────
head_ "L0-7  bless --info"
sudo bless --info "$MS" --plist 2>&1 | tee /tmp/bless-info.plist | sed -n '1,40p'
grep -q 'System/Library/CoreServices' /tmp/bless-info.plist \
  && ok "blessed folder 指向 CoreServices" || bad "blessed folder 不对"

# ───────── L0-8 firmlinks ─────────
head_ "L0-8  firmlinks"
check_sz "$MS/usr/share/firmlinks" 689
echo "  --- 全文 ---"; cat "$MS/usr/share/firmlinks" 2>/dev/null || bad "读不出 firmlinks"

# ───────── L0-9 两个 KC ─────────
head_ "L0-9  kernel collections"
check_sz "$MS/System/Library/KernelCollections/BootKernelExtensions.kc"   67584000
check_sz "$MS/System/Library/KernelCollections/SystemKernelExtensions.kc" 369213440
for k in BootKernelExtensions SystemKernelExtensions; do
  head -c 4096 "$MS/System/Library/KernelCollections/$k.kc" >/dev/null 2>&1 \
    && ok "$k.kc 可读" || bad "$k.kc 读不出内容（decmpfs 不一致？A.4.2 规则 1）"
done

# ───────── L0-10 decmpfs 一致性抽样 ─────────
# 判据写进文件再判，不靠管道里的计数器：管道的每一段跑在子 shell 里，
# 在里面累加的变量回不到父 shell。
head_ "L0-10  decmpfs 一致性（抽 200 个带 AFT 的路径）"
awk -F'\t' 'NR>1 && $2=="F" && $6!="" {print $1}' "$IDX" \
  | awk 'NR % 100 == 1' | head -200 > /tmp/decmpfs-paths.txt
: > /tmp/decmpfs-bad.txt
NCHK=0
while IFS= read -r p; do
  f="$MS/$p"; [ -f "$f" ] || continue
  NCHK=$((NCHK + 1))
  head -c 1 "$f" >/dev/null 2>&1 || echo "  !! 读不出:  $p" >> /tmp/decmpfs-bad.txt
  [ "$(sz "$f")" = "0" ]         && echo "  !! 0 长度:  $p" >> /tmp/decmpfs-bad.txt
done < /tmp/decmpfs-paths.txt
echo "  实际检查 $NCHK 个"
cat /tmp/decmpfs-bad.txt
if [ -s /tmp/decmpfs-bad.txt ]; then
  bad "decmpfs 抽样有异常，见上（A.4.2 规则 1 很可能被违反）"
else
  ok "decmpfs 抽样 $NCHK 个全部可读且非 0 长度"
fi

# ───────── L0-11 APFS jumpstart ─────────
head_ "L0-11  APFS jumpstart（V-018）"
PHYS=$(diskutil apfs list -plist "$CNT" \
       | plutil -p - 2>/dev/null | grep -A2 PhysicalStores | grep DeviceIdentifier | head -1 \
       | sed -E 's/.*"([^"]+)".*/\1/')
echo "  physical store = ${PHYS:-未取到}"
# jumpstart 的 EFI driver 区域在容器超级块指向的位置。离线判据用一条弱但有效的替代：
# 在容器的前 1 MiB 里找 PE/COFF 的 "MZ" 与 "PE\0\0"，apfs.efi 是一个 PE 映像。
if [ -n "${PHYS:-}" ]; then
  sudo dd if="/dev/r$PHYS" bs=1m count=8 2>/dev/null | strings -a | grep -m3 -iE 'apfs|EFI' \
    && ok "容器前 8 MiB 里有 EFI 相关字符串（弱证据）" \
    || bad "容器前 8 MiB 里找不到 EFI 相关字符串，jumpstart 可能是空的"
fi

# ───────── L0-12 预配 daemon ─────────
head_ "L0-12  预配（L-024）"
[ -f "$MD/Library/LaunchDaemons/net.metal2vu.cpudisp-confirm.plist" ] \
  && ok "cpudisp-confirm daemon 在位" || bad "cpudisp-confirm daemon 缺失（76 的 L-024）"

# ───────── L0-13 与源逐项比对 ─────────
head_ "L0-13  与 payload 索引逐项比对（抽 2000 条）"
MISS=0; SZBAD=0; MODEBAD=0; CHK=0
awk -F'\t' 'NR>1 && $2=="F" && $1 !~ /^System\/Library\/Templates\/Data\// {print $1"\t"$3"\t"$4}' "$IDX" \
  | awk 'NR % 130 == 1' | head -2000 > /tmp/cmp.tsv
while IFS=$'\t' read -r p want_sz want_mode; do
  f="$MS/$p"; CHK=$((CHK+1))
  if [ ! -e "$f" ]; then MISS=$((MISS+1)); [ "$MISS" -le 20 ] && echo "  missing: $p"; continue; fi
  g=$(sz "$f"); [ "$g" = "$want_sz" ] || { SZBAD=$((SZBAD+1)); [ "$SZBAD" -le 20 ] && echo "  size $g != $want_sz : $p"; }
  gm=$(stat -f%p "$f" 2>/dev/null); gm=$(( 8#${gm: -4} ))
  [ "$gm" = "$want_mode" ] || { MODEBAD=$((MODEBAD+1)); [ "$MODEBAD" -le 20 ] && echo "  mode $gm != $want_mode : $p"; }
done < /tmp/cmp.tsv
echo "  抽查 $CHK 条：缺失 $MISS，字节不符 $SZBAD，mode 不符 $MODEBAD"
[ "$MISS" = "0" ]    && ok "无缺失"      || bad "$MISS 条缺失"
[ "$SZBAD" = "0" ]   && ok "字节全对"    || bad "$SZBAD 条字节不符"
[ "$MODEBAD" = "0" ] && ok "mode 全对"   || bad "$MODEBAD 条 mode 不符"

# ───────── L0-14 所有者 ─────────
head_ "L0-14  所有者"
NBAD=$(sudo find "$MS/System/Library/CoreServices" \( ! -user root -o ! -group wheel \) 2>/dev/null | wc -l | tr -d ' ')
[ "$NBAD" = "0" ] && ok "CoreServices 全部 root:wheel" || bad "$NBAD 项所有者不对"

# ───────── 汇总 ─────────
printf '\n================ %s ================\n' \
  "$([ "$FAIL" = "0" ] && echo 'L0 全绿' || echo 'L0 有红')"
exit "$FAIL"
```

**三条关于这个脚本的说明：**

1. **`set -e` 故意不开。** 验证脚本的目的是把**全部**红项列出来，不是在第一条红的地方停。`set -uo pipefail` 保留。
2. **L0-11 的判据是弱的**，它只能证明「容器前 8 MiB 里有 EFI 相关字符串」。确切的 jumpstart 结构读法未知（`V-018`），第 D 节会在运行器自己的容器上取一份已知良好的样本来对照。
3. **L0-13 的 mode 比对用 `stat -f%p` 取后 4 位再按八进制转十进制**，这是为了与索引里的十进制 mode 对齐。`INFERRED`：`stat -f%p` 在 25G325 上的输出格式未实测（它应当是 6 位八进制，如 `100644`）。退路是 `stat -f%Sp` 的符号形式再自己转。登记为 `V-024`。

### C.2 L1：只能启动才知道的

**这些项 L0 一条都测不出来。它们全部指向 `80-TEST-HARNESS.md` 第 4.1 节的 E0-L1**（macOS 在本地 KVM 上启动并 SSH 可达，验收是 `harness.env_wait_ready { signal: "ssh" }` 返回 `ready: true`）。

| # | 只能启动才知道的事 | 失败的表现 | 对应的未解决项 |
|---|---|---|---|
| **L1-1** | 自建的、未经 Apple 签名的封印快照在非 T2 Intel（`VMM-x86_64`）上能不能被引导 | 选中 macOS 之后不动，或禁止符号 | 第 0.2 节末；`V-025` |
| **L1-2** | firmlink 会不会在首次挂载时自动建立（不需要 `createFirmlinks`） | 停在早期用户态。判据：`stat -f '%d' /private` 与 `stat -f '%d' /System/Volumes/Data` 的设备号是否相同 | `V-013` |
| **L1-3** | 不压缩铺设（若走那条）的系统能不能启动 | 若能，`V-026` 关掉；若不能，第 0.3.1 节的「丢压缩不致命」这条判断要改 | `V-026` |
| **L1-4** | cryptex 缺失或铺错时的表现 | `INFERRED`：`dyld` 找不到 shared cache，启动到 `launchd` 之前就停 | `V-015` |
| **L1-5** | 没有 Recovery 卷时 OpenCore 的选择器实际长什么样 | 纯外观。`76` 的 `L-002`、`L-020` 同源 | `76` `L-002` |
| **L1-6** | `bless --create-snapshot` 产的快照是否真的被设成 root snapshot | L0-3 只能看到「有一个快照」，看不到「它是 root」 | `V-022` |
| **L1-7** | VM 卷为空时 `dynamic_pager` 的行为 | 日志里有无报错；运行期有无 swap | 第 A.8 节 |
| **L1-8** | 容器的 jumpstart 区域是否真的让 OpenCore 看见了卷 | **选择器里没有 macOS 这一项**（`76` §1.3 判据 1）。排查手段是 OpenCore DEBUG 日志的 `OCJS:` 前缀（`OcApfsLib`） | `V-018` |
| **L1-9** | `PlatformSupport.plist` 的 board-id 门是否被 `VMM-x86_64` 通过 | 禁止符号；verbose 下「不受支持的 board ID」+ 30 秒硬关机（第 A.6.3 节的野外证据） | `71` §4.1 已给 8 个 board-id；`V-027` |

**L1-1 是整份规格的承重项。** 第 0.2 节用五路证据加 OCLP 的野外佐证把它压到了「几乎肯定能」，但它仍然是 `INFERRED`。**在 E0-L1 跑出绿灯之前，本文第 A、B 两节全部是 `INFERRED` 级的规格。**

**L1-8 的排查顺序值得单独写，因为它最容易误诊。** 若选择器里没有 macOS 项，依次查：

1. L0-4（Preboot 里有没有 `boot.efi`）→ 没有就是第 A.6 节的问题；
2. L0-11（jumpstart）→ 空的就是 `V-018`；
3. `71` 第 6.9.2 节的 `UEFI/APFS/EnableJumpstart` 是不是 `true`；
4. `71` 第 6.6.2 节的 `ScanPolicy = 0`（不限制扫描）。

---
## D. 取证 workflow：`.github/workflows/forensics-boot-layout.yml`

### D.1 它要产出什么

**它要产出的是可直接写进第 A 节的事实，不是一堆原始 dump。** 运行器自己那块盘是一套**装好的、封印完好的、能启动的** macOS 26 x86_64（`91` 第 1 节：25G76、SIP 已关、`Apple Paravirtual device`），即它就是第 A 节那份规格的一个活实例。把它读透，第 A 节里标 `BLOCKED` 的那几格就能填上。

六个 job，每个对准第 A 节的一层：

| job | 对准 | 回填哪些 `V-xxx` |
|---|---|---|
| `volumes` | 第 A.2、A.3 节 | `V-003`、`V-006`、`V-007`、`V-019` |
| `preboot` | **第 A.6 节（本文的重点）** | `V-014`、`V-016`、`V-021`、`V-022` |
| `cryptex` | 第 A.6.5 节 | `V-015` |
| `compression` | 第 0.3.1 节 | `V-004`、`V-005` |
| `firmlinks-data` | 第 A.5 节 | `V-011`、`V-012` |
| `tooling` | 第 A.3.3、A.6.2、A.9.1 节 | `V-007`、`V-009`、`V-017`、`V-018`、`V-020`、`V-024` |

### D.2 纪律

四条，全部写进 workflow 的注释里：

1. **全部只读。** 对运行器自己那块盘只有 `ls` / `stat` / `shasum` / `codesign -d` / `diskutil … list|info` / `bless --info` / `readlink` / `cat`。**没有一处写、没有一处 `--setBoot`、没有一处 `nvram`、没有一处 `chflags`。**
2. **`tooling` job 里的写操作全部落在 `$RUNNER_TEMP` 下的一个磁盘镜像里**，而且 `bless` 的目标是那个镜像里的卷，不是 `/`。`A.10.2` 节的「同一块物理盘」护栏在那个 job 里也要跑。
3. **每个纯诊断步骤末尾 `exit 0`。** 依据是 `91` 第 5.4、5.5 节的 `R-004`：`set +e` 只关 errexit，**步骤退出码仍取最后一条命令**，所以 `find /System` 碰到权限错误返回非零会让整个 job 报 failure，而 artifact 已经产出。
4. **只上传文本清单与哈希，不上传任何 Apple 二进制本体。** 本仓库是公开仓库，artifact 同样公开。这条边界与 `.gitignore` 顶部是同一条规则（该文件顶部的发布边界一节明确：从 Apple 的 macOS 安装介质里解出的二进制、plist 及基于它们建立的 IDA 数据库不得进入公开仓库，证据的可复现性由 MANIFEST 里的 SHA-256 保证）。

**第 4 条在本 workflow 里有一处需要特别注意：`boot.efi` 是 Apple 的二进制。** 我们上传它的**路径、字节数、SHA-256、`codesign -dvvv` 的输出**，不上传它本身。同理 `.disk_label` / `.disk_label_2x` 是 Apple 渲染出来的位图，**上传它们的字节数与哈希，不上传内容**。plist 类（`SystemVersion.plist`、`PlatformSupport.plist`）是 Apple 的内容而非代码，但按同一条边界，**只上传它们的键名结构与哈希，不上传全文** —— `71` 第 4.1 节已经把 `PlatformSupport.plist` 的全文写进分册了，那是一次经过判断的例外（790 字节、8 个 board-id、是本项目的承重事实），本 workflow 不重复它。

### D.3 采集清单

逐条对应任务点名要的东西：

| # | 采什么 | 命令 | 落到哪 |
|---|---|---|---|
| 1 | `diskutil apfs list` / `listVolumeGroups` 全文，以及每个卷的 role | `diskutil apfs list`、`diskutil apfs list -plist`、`diskutil apfs listVolumeGroups [-plist]`、对每个卷 `diskutil info -plist` | `volumes/` |
| 2 | **`/System/Volumes/Preboot/<UUID>/` 的完整文件清单（含大小、权限、xattr）** | `find` + `ls -lhO@` + `stat -f` + 逐文件 `xattr -l` | `preboot/tree.txt`、`preboot/stat.tsv`、`preboot/xattr.txt` |
| 3 | cryptex 的位置、形态、挂载方式 | `mount \| grep -i cryptex`、`readlink /System/Cryptexes/*`、`find /System/Volumes/Preboot/Cryptexes -maxdepth 4`、`hdiutil info` | `cryptex/` |
| 4 | `/usr/share/firmlinks` 全文 | `cat`，并与 `SystemMigration.framework` 那一份 `diff` | `firmlinks/` |
| 5 | `/System/Library/Templates/Data` 的完整树 | `find … -print0 \| xargs -0 stat -f` | `datatemplate/` |
| 6 | `stat -f '%d'` 对一组路径（判定哪些路径在哪个卷上） | 见 D.4 的路径清单 | `volumes/devno.tsv` |
| 7 | 带 decmpfs/AppleFSCompression 的文件占比 | `ls -lO` 的 `compressed` 标志 + `stat -f '%z %b %Xf'` + 用 `XATTR_SHOWCOMPRESSION` 读 `com.apple.decmpfs` 的 type code | `compression/` |
| 8 | `bless --info` 的输出 | `bless --info --plist`、`bless --info --getBoot`、`bless --version` | `bless/` |
| 9 | 当前快照清单与封印状态 | `diskutil apfs listSnapshots [-plist]`、`diskutil info /`、`csrutil authenticated-root status`、`csrutil status` | `volumes/snapshots.txt` |
| 10 | `boot.efi` 的位置、大小、哈希、签名状态 | `find` + `stat -f%z` + `shasum -a 256` + `codesign -dvvv` | `preboot/bootefi.txt` |

**追加五项（本文认为同等重要，任务没点但必须采）：**

| # | 采什么 | 为什么 |
|---|---|---|
| 11 | `man bless` 的 FILES 一节真实路径常量；`man diskutil` 的 `APFS VOLUME ROLES` 全节 | 关 `V-017`（`--bootefi` 的默认源）与 `76` 的 `L-001`（role 字母）。**在线手册镜像把那两个路径常量丢了，本地 man page 不丢** |
| 12 | `diskutil apfs addVolume` / `changeVolumeRole` / `updatePreboot` / `convert` 不带参数的用法串 | 关 `V-007`（role B/V 能不能设）。用法串是 `diskutil` 自己打印的，比手册更贴近这个 build |
| 13 | `diskutil listFilesystems`；`which newfs_hfs newfs_apfs chflags` | 决定第 D.5 节 `-prebootSource` 实验能不能做（它要一个 HFS+ 源卷） |
| 14 | `/` 的 case sensitivity、所有者抽样、`SF_RESTRICTED` 抽样 | 关 `V-006`、`V-008`、`V-009` |
| 15 | 运行器自己容器的前 8 MiB 的 `strings`（只取与 EFI/APFS 相关的行） | 给 `V-018`（jumpstart）一个**已知良好**的对照样本，这样第 C.1 节 L0-11 的弱判据才有参照 |

### D.4 设备号探针的路径清单

`stat -f '%d'` 给出的是 `st_dev`，即该路径所在的文件系统的设备号。**对一个 volume group，System 与 Data 的 `st_dev` 在启动时是否相同，是 firmlink 到底生效没生效的直接判据。**

要探的路径，按预期归属分组：

```text
预期在 System 卷（SSV 快照）上：
  /  /System  /System/Library  /System/Library/CoreServices  /System/Library/Extensions
  /System/Library/KernelCollections  /System/Library/Kernels  /usr  /usr/share/firmlinks
  /usr/standalone  /usr/standalone/i386  /bin  /sbin  /System/Library/Templates/Data

预期在 Data 卷上（经 firmlink 投射）：
  /Users  /Library  /private  /private/var  /private/var/db  /opt  /cores  /Volumes
  /usr/local  /usr/libexec/cups  /usr/share/snmp  /Applications
  /System/Library/Caches  /System/Library/Assets  /System/Library/AssetsV2
  /System/Library/PreinstalledAssets  /System/Library/PreinstalledAssetsV2
  /System/Library/Speech
  /System/Library/CoreServices/CoreTypes.bundle/Contents/Library
  /System/Volumes/Data

预期在各自的独立卷上：
  /System/Volumes/Preboot  /System/Volumes/VM  /System/Volumes/Update  /System/Volumes/Recovery

预期在 cryptex 里（随机挂载点，所以 st_dev 应当都不同于以上）：
  /System/Cryptexes/OS  /System/Cryptexes/App  /System/Volumes/Preboot/Cryptexes/OS
```

**上面「预期在 Data 卷上」那一组的前 17 条，正好是第 A.5.2 节那张 firmlink 表的左列。** 所以这一组的 `st_dev` 全部等于 `/System/Volumes/Data` 的 `st_dev`，就证明了那张表在运行器上**逐条生效**，而且证明了第 A.5.2 节 `V-013` 的判据方式是对的。

### D.5 `-prebootSource` 实验：一条能直接问 Apple 的工具「Preboot 里该有什么」的路

第 A.6.2 节事实 3 已论证它的价值。实验设计：

```text
1. 在 $RUNNER_TEMP 下造一个 2 GB 的 raw
2. mkgpt.py create --part auto:1800MiB:hfs:ScratchHFS   ← 离线写表，然后才 attach
                     （1.1：原先写的 gpt create + gpt add 在 25G76 上被拒，A.1.0）
3. newfs_hfs 建一个 HFS+ 卷（若 newfs_hfs 不在，用 diskutil eraseVolume JHFS+）
4. mkdir 一个空的暂存目录 $STAGE_PB
5. sudo diskutil apfs convert <hfs-dev> -dryrun -prebootSource "$STAGE_PB"
                     ↑ disk 在前。1.1：前两轮把它写在选项后面，diskutil 报
                       "Could not find disk for -dryrun"，这个实验从未真正跑过。
                       用法串原文：convert <disk> [-dryrun] [-prebootSource <dir>]
6. ls -lhO@R "$STAGE_PB"    ← diskutil 往里加了什么，就是答案
7. 若 -dryrun 下不加件，去掉 -dryrun 重跑（目标是我们自己的 scratch 镜像，不是运行器的盘）
8. 转换完 diskutil apfs list <新容器>：看它建出来的 Preboot role 卷里有什么
9. detach，删 raw
```

**`diskutil apfs convert` 的用法串在 25G76 上实测取到了，它比手册更具体（`TESTED(25G76)`）：**
指定 `-prebootSource` 并给自己的暂存目录时，**会建出一个带 UUID 目录的 Preboot role APFS 卷**
以促成 macOS 的 bootstrap；那个目录通常要可写，因为**转换之前会自动往里加入额外的件，
而且转换完不会删掉它们**；`-noPrebootAdditions` 可以关掉自动添加。
这正是第 A.6.2 节事实 3 的来源，现在有了这个 build 自己的原话。

**这个实验的产出是本 workflow 最值得期待的一项**，因为它不是「观察一个已经装好的系统」，而是「让 Apple 的工具在一块空盘上从零做一次 Preboot」。两者的差别正是第 A.6.3 节那张表里「现在能写出规格吗」一列的全部缺口。

**1.1 进展：参数顺序修好之后 `convert` 正确解析了，但还差一步。** `TESTED(25G76)`，
run `41278014136`。它回显了自己的完整意图 —— 这一句本身就是一条证据：

```text
Rehearsing the conversion of the volume on disk4s1 to an APFS Volume on an APFS
Container with the addition of a new APFS Preboot Volume based on items at
/…/preboot-stage plus DiskManagement-gathered crypto items
Started APFS operation on disk4s1
Dry run of HFS Volume conversion to an APFS Container with a single APFS Volume
Exiting conversion operations with error code -69854
Error: -69854: A disk with a mount point is required
```

两条读出来的事实：

1. **`-prebootSource` 的语义被 `diskutil` 自己说清了：我们给的件 + 「DiskManagement
   自己搜集的 crypto 件」。** 这与第 A.6.2 节事实 3 里「自动添加 cryptographic 与
   EFI rendering 两类件」对上，而且点明了 crypto 那一类是 **DiskManagement 框架**
   自己凑的，不需要我们提供。
2. **`-69854`（`A disk with a mount point is required`）：`convert` 要求源 HFS+ 卷
   处于已挂载状态。** 同一个错误码在同一轮里还出现过一次 —— `diskutil apfs
   listSnapshots <未挂载的卷>`。**所以这是 `diskutil` 的一类通用前置条件，
   不是这个动词特有的**，第 C 节的纪律里加一条：凡是要读卷内容的 `diskutil`
   动词，先 `diskutil mount`。修法就是在 `newfs_hfs` 之后加一条
   `sudo diskutil mount -mountPoint "$HM" "${DEV2}s1"`，已写进 workflow。

`INFERRED`，三条风险（workflow 里对它们都做 `continue-on-error`）：

| 风险 | 表现 | 退路 |
|---|---|---|
| `newfs_hfs` 在 25G325 上不在了 | `command not found` | `diskutil eraseVolume JHFS+ …`；都不行就跳过本 job，`V-028` |
| `-dryrun` 下不往暂存目录加件 | `$STAGE_PB` 仍然是空的 | 去掉 `-dryrun`。目标是 scratch 镜像，没有风险 |
| `convert` 拒绝一个空的、不含 macOS 的 HFS+ 卷 | 报「不是 macOS 卷」一类错误 | 先往 HFS+ 卷里铺一个最小的 `System/Library/CoreServices`（含 `SystemVersion.plist` + `boot.efi`，从运行器的 `/` 只读拷到 scratch 镜像里，**不上传**），再转换 |

### D.6 decmpfs type code 的读法

第 0.3.1 节 (g) 的 `V-005` 需要读出 `com.apple.decmpfs` 的 `compression_type`。该 xattr 受保护，普通 `getxattr(2)` 看不见它，必须带 `XATTR_SHOWCOMPRESSION`（`0x0020`，见 `<sys/xattr.h>`）。workflow 里用 `python3` + `ctypes` 直调：

```python
# tools/ci/read_decmpfs.py 的等价内联版本（workflow 里用 heredoc）
# com.apple.decmpfs 的头 16 字节： magic 'fpmc'(LE u32) | compression_type(u32) | uncompressed_size(u64)
import ctypes, ctypes.util, struct, sys
libc = ctypes.CDLL(ctypes.util.find_library("c"), use_errno=True)
libc.getxattr.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_void_p,
                          ctypes.c_size_t, ctypes.c_uint32, ctypes.c_int]
XATTR_SHOWCOMPRESSION = 0x0020
buf = ctypes.create_string_buffer(64)
for path in sys.argv[1:]:
    n = libc.getxattr(path.encode(), b"com.apple.decmpfs",
                      buf, 64, 0, XATTR_SHOWCOMPRESSION)
    if n < 16:
        print("-\t-\t-\t%s" % path); continue
    magic, ctype, usize = struct.unpack_from("<4sIQ", buf.raw, 0)
    print("%s\t%d\t%d\t%s" % (magic.decode("latin1"), ctype, usize, path))
```

**产出是一张 `magic / compression_type / uncompressed_size / path` 的表。** 把它按 `compression_type` 做直方图，与第 0.3.1 节 (a) 的 `AFT` 直方图（`8` → 105,020、`9` → 28,913）对照，就知道 `AFT` 是不是就是 `compression_type`。**若两张直方图的取值集合相同（只有 8 与 9），`V-005` 当场关掉。**

---

## E. 可行性裁决

### E.1 裁决

**第二档：不够，但缺的全在第 D 节的取证范围内，一轮 CI 就能补齐。**

不含糊地说清三件事：

**（1）十层规格里，八层现在就能写出可照抄的命令，两层不能。**

| 层 | 现在能写出规格吗 | 缺什么 |
|---|---|---|
| A.1 GPT | **能**（接 `75` §0.0.1） | 无 |
| A.2 容器 | **能** | 容器引用 disk 号的 plist 键名（`V-003`，有确定退路） |
| A.3 卷与 role | **能，含完整命令序列** | `-role B`/`-role V` 会不会被拒（`V-007`），有三条退路 |
| A.4 System 内容 | **能，含 `ditto --hfsCompression` 的确切用法** | 所有者（`V-008`）、`chflags` 助记符（`V-009`），都有退路 |
| A.5 Data 内容 + firmlink | **能** | firmlink 是否自动建立（`V-013`），这一条要启动才知道 |
| **A.6 Preboot** | **机制能，文件清单不能** | 见下 |
| A.7 Recovery | **能**（不要，后果已列全） | 无 |
| A.8 VM | **能**（建，空的） | 无 |
| A.9 快照 | **能** | 快照名格式（`V-019`），不影响实现 |
| A.10 bless | **能，含确切参数与禁止清单** | 它写了哪些文件（`V-021`/`V-022`），`bless --verbose` 一跑就知道 |

**（2）Preboot 层现在能写出多少。**

能写出的：

- per-UUID 目录名 = volume group UUID，这条确定；
- `<UUID>/System/Library/CoreServices/` 这条相对路径，确定；
- `boot.efi` 的来源（`usr/standalone/i386/boot.efi`，723,512 字节，未压缩，`payload.041`）与两个 plist 的来源与字节数（790 / 604），确定；
- `.disk_label` / `.disk_label_2x` **不在 payload 里、由 `bless --label` 渲染**，确定（零命中是硬证据）；
- `com.apple.Boot.plist` **属于 Data 模板、不属于 Preboot**，确定；
- **三条独立的、全部由 macOS 自带命令实现的生成途径**：`bless --bootefi --create-snapshot`（boot objects + 封印）、`diskutil apfs updatePreboot`（用户元数据与登录 UI）、`diskutil apfs convert -prebootSource`（从零建 Preboot role 卷与 UUID 目录）。**这三条是本轮把 Preboot 从「黑箱」拉出来的那一步。**

缺的，三项：

| 缺什么 | 为什么现在拿不到 | 第 D 节哪个 job 拿 |
|---|---|---|
| **Preboot 卷**根下**还有什么**（`i386/`？`Cryptexes/`？）与 `<UUID>/` 下的完整清单 | payload 里 `Preboot` 只有一个空挂载点目录（第 A.4.4 节）。Preboot 的内容是**派生的**，素材里不存在 | `preboot` |
| **cryptex 的目录结构、形态、manifest/ticket** | 同上，而且它牵着 `77` 的 `U-001`（逐机个性化是否联网） | `cryptex` |
| **`bless` 到底写了哪些文件、哪些 APFS 字段** | 要实跑一次才知道 | `tooling`（`-prebootSource` 实验 + `bless --verbose`） |

**这三项全部在一台免费的 `macos-26-intel` 运行器上、用只读命令加一个 scratch 磁盘镜像就能拿到。没有一项需要买硬件、需要人工、需要 Apple 的签名服务。** 这就是裁决落在第二档而不是第三档的理由。

**（3）第三档（CI 也拿不到）里只有一项，而且它不属于本文。**

`77` 的 `U-001`：**x86/VMM 的 PREPARE 相位会不会被迫向 `gs.apple.com` 签 cryptex1/boot ticket。** 它拿不到的部分不是「观察」（观察能做，`77` 已给方法），是「如果答案是会联网，那我们就签不出来」。

**但这一条不阻塞本文**，两条理由：

1. 本文的构建路径（R2 式直写 + `bless` + `diskutil`）**从不调用 `AMAuthInstallBundlePersonalize`**，所以它根本不进那条代码路径。`bless --personalize` 是进那条路的唯一入口，而第 A.10.2 节已把它列进禁止清单。
2. cryptex 的 ticket 校验由 `csr-active-config` 的 bit 11 与 `SecureBootModel = Disabled` 旁路（第 0.2 节的事实 2、3）。`INFERRED`，这是 `V-015` 的一半。

**所以本文的裁决不依赖 `77` 的 `U-001`。** 两者的交集只在「cryptex 的内容怎么铺」这一格，而那一格的第一选择是「把 x86_64 cryptex 的内容铺到 Preboot 卷上、建三个符号链接、不要 ticket」（第 A.6.5 节末段），**不是**「让 UpdateBrain 替我们签」。

### E.1a 1.1 对裁决的修正：档位不变，但「唯一真正缺的那一层」换了

**1.0 的裁决是第二档（「不够，但缺的全在取证范围内」），1.1 维持这个档位。**
四轮取证把第 A 节的十层里九层从「机制已知」推到「命令已验」。
**但它同时发现缺口不在原来认为的地方。**

| 1.0 认为缺的 | 1.1 的结果 |
|---|---|
| Preboot 卷根下还有什么、`<UUID>/` 下的完整清单 | **拿到了**，679 条逐项（第 A.6.7 节）。连 `bless` 写哪三个、我们写哪七个都分清了 |
| `bless` 到底写了哪些文件、哪些 APFS 字段 | **拿到了**（第 A.10.2c 节）。文件三个、字段是 `Bless Info` 的 `Directory ID`/`Path`/`Relative Path` |
| cryptex 的结构与形态 | **形态拿到了**（sealed DMG + root_hash + trustcache + 8 个 board 的 apticket），**内容怎么铺仍缺**（`V-015`） |

**1.1 新发现的那一层，是 1.0 整节都当成「已解决」的那一层：封印。**

> **`bless --create-snapshot` 要求目标卷已经是 ARV。一块从零建出来的卷不是，
> 所以 `bless` 封不了第一次印（`V-034`，第 A.10.2c 节）。**

**这不改变档位，因为三条候选解里有两条在 CI 范围内**（S1 走 `asr`、S2 写一个调
`fs_snapshot` 的小程序），**第三条（S3：干脆不要 ARV）本来就属于「只能启动才知道」
的那一类，和 `V-025` 是同一级。**

**它改变的是路径优先级：**

1. **第一块盘走 `75` 的 R1（`asr restore --toSnapshot … --erase`）。**
   它从「先做的那条」升级为「唯一已知能产出 ARV 的那条」。
2. **同一轮里并行造一块 S3 形态（无快照）的盘**，用同一次 E0-L1 把
   「ARV 到底是不是必须的」答掉。这两块盘的差别只有一个快照，
   所以它是一次干净的对照实验。
3. **本文第 B 节那段从零装配的脚本仍然全部有用** —— 它产出的就是 S3 形态那一块。
   步 12b 已经把「这块盘没有 root snapshot」显式打出来，不是悄悄跳过。

### E.2 不要绕的三个弯

**（1）不要等 R6（UpdateBrain）。** `77` 第 F 节的裁决是「在 `U-001` 关掉之前，R6 既不能排期也不能宣布可行」。本文的路径与 R6 并行、不依赖它。**R6 的价值在 build 保真（25G325 而不是运行器的 25G76），不在「只有它能造出可启动的卷」。** 本文的路径同样产出 25G325，因为它的素材是 payload 本身。

**（2）不要先做瘦身。** 第 A.4.1 节已说清：第一轮只剔 arm64 的 13 个内核（218 MB，而且按 `00-OVERVIEW` 第 7 节规则 2 它们本来就不该在 x86 盘上）。其余每一条剔除都是一条新的未知，而未知在无头环境里的代价是无法归因的启动故障。

**（3）不要把 `-no_compat_check` 设成默认。** 第 A.6.3 节的野外证据说明它能旁路 `PlatformSupport.plist` 的 board-id 门。**但它旁路的恰好是我们最需要的那条诊断信息。** 正确做法是把它放进 `74` 第 3.2 节 `04-safe.plist` 那份候选 config，让三次失败机制在前三次失败之后自己用上它。见第 F 节。

---

## F. 给其他分册的修订工单

本文不改任何其他文件。以下是本轮发现的、应当由各自分册下一轮吸收的条目。

| # | 给哪册 | 内容 |
|---|---|---|
| **F-1** | `74-BOOT-CPU-DISPATCH.md` 第 3.2 节 | **把 boot-arg `-no_compat_check` 加进 `04-safe.plist`**（且只加进那一份）。依据是本文第 A.6.3 节的野外证据：错的 `PlatformSupport.plist` 会让系统显示禁止符号、verbose 下报「不受支持的 board ID」并在 30 秒后硬关机，而该 boot-arg 让系统忽略这类问题并启动。它是三次失败机制的最后一级兜底，不是默认值 |
| **F-2** | `75-IMAGE-PREBAKE.md` 第 5 节预配清单 | **新增一项：禁 hibernate（`/Library/Preferences/com.apple.PowerManagement.plist` 的 `hibernatemode = 0`）。** 依据是本文第 A.8 节：`sleepimage` 的大小等于 RAM 大小，云 KVM guest 不休眠，它白占容器空间。该项在 Data 卷上，不破封印 |
| **F-3** | `75-IMAGE-PREBAKE.md` 第 0.0 节第 4 行 | 该行把「必须在 macOS 上装配」的理由之一记作 Paragon 的快照只读等工具侧事实。**建议补上本文第 0.3 节那四条具体缺什么**（role / volume group / firmlink / decmpfs），并特别补上第 0.3.1 节的核实结论：`ditto` 要的是 `--hfsCompression`（创建压缩），不是默认的 `--preserveHFSCompression`（保留压缩）；照抄「`ditto` 默认就保留了」会得到一块 19 GB 而不是 5.5 GB 的 System 卷 |
| **F-4** | `76-BOOT-LAYOUT-PICKER.md` 第 7 节 `L-001` | **部分关闭。** `diskutil(8)` 的 `APFS VOLUME ROLES` 一节可读出：`D` = Data、`E` = Update、`X` = XART（hardware security）、`H` = Hardware、`C` = Sidecar（Time Machine）、`Y` = Enterprise（data）。`N`、`L`、`G` 仍未确证。（转述自 <https://keith.github.io/xcode-man-pages/diskutil.8.html>） |
| **F-5** | `75` 第 0.0.1 节 与 `76` 第 3.1 节 | **两册的分区数仍不一致**（`75` 两分区 / `76` 三分区，而 `76` 第 6.5 节的 `75-A` 又建议把 `75` 改成三分区）。本文按 `75` §0.0.1 走，并在第 A.1.1 节论证这个选择对本文零影响。**定版不由本文做**，登记为 `V-002` |
| **F-6** | `80-TEST-HARNESS.md` 第 4.1 节 E0-L1 | 本文第 C.2 节的 L1-1 到 L1-9 共 9 项只能靠启动关闭。建议把它们列进 E0-L1 的验收清单，特别是 **L1-1**（自建封印快照在非 T2 Intel 上能不能引导）与 **L1-2**（firmlink 的 `stat -f '%d'` 判据） |
| **F-7** | `90-EVIDENCE-INDEX.md` | 本轮对 `payloadv2-full-index.tsv.zip` 做了全量统计（458,715 条 / 272,090 个常规文件 / 133,933 个带 `AFT` / `FLG` 与 `AFT` 零例外同步）。建议把这几个数登记进证据索引，它们是第 0.3.1 节的全部依据 |

---

## 未解决项清单

编号 `V-` 代表 volume construction。与 `70` 的 `P-`、`71` 的 `I-`、`72` 的 `C-`、`73` 的 `D-`、`76` 的 `L-`、`77` 的 `U-`、`80` 的 `H-`、`91` 的 `R-` 并列，互不重叠。

按 `00-OVERVIEW` 第 7 节补充规则第 4 条：「没查」不等于「被阻断」，能用现有材料查清的一律不标 `BLOCKED`。

#### E.3.0 已关闭的（1.1，两轮 CI 取证）

**这张表是权威的。下面那张原表里同编号的行已被它取代，保留只为看得见「原来以为是什么」。**

| # | 答案 | 标签 | 证据 |
|---|---|---|---|
| **V-001** | **会，而且必须由它改。** 事先把 p2 写成 APFS 类型反而让 `createContainer` 报 `-69614 The disk is already in use by APFS`；写成 `Apple_HFS` 则成功，并由它把类型改成 `7C3457EF-…` | `TESTED(25G76)` | `B4-scratch.txt`（P0 对照 vs P1），第 A.1 节约束 3 |
| **V-003** | **是 `APFSContainerReference`。** 退路的 grep 串要按 `Created new APFS Container ([a-z0-9]+)` 写（1.0 写的 "with disk identifier" 对不上） | `TESTED(25G76)` | `23-container-ref.txt` + `B4-scratch.txt`，第 A.2 节 |
| **V-006** | **`FilesystemName = APFS`**（非大小写敏感），与规格一致 | `TESTED(25G76)` | `24-case-sensitivity.txt` |
| **V-007** | **`-role B` 与 `-role V` 都能设，不需要退路。** `addVolume` 的用法串列出的允许集是 `B\|R\|V\|I\|T\|S\|D\|E\|X\|H\|C\|Y` | `TESTED(25G76)` | `B0-tool-usage.txt` + `B4-scratch.txt`，第 A.3.3 节 |
| **V-009** | **`chflags restricted` 可用**（回读 `flags=80000 restricted`）；**`chflags 0x80000` 不存在**（`invalid flags`）；`chflags compressed` 在 APFS 上置不上 `UF_COMPRESSED` | `TESTED(25G76)` | `B3-chflags.txt`，第 A.4.2 节 |
| **V-014** | **Preboot 全树已取到，679 条。** 卷根下四项：`.TemporaryItems/`、`<VG_UUID>/`、`com.apple.security.cryptexd/`、**`Cryptexes/`**（与 per-UUID 目录同级）。**没有 `i386/` 这一项**（1.0 从野外文档推测的那一条不成立） | `TESTED(25G76)` | 第 A.6.7 节 |
| **V-016** | **有。** `<VG_UUID>/Library/Preferences/SystemConfiguration/com.apple.Boot.plist`，来源是 payload 的 Data 模板里那份 232 字节的。**但本项目不往那里写**：boot-args 走 OpenCore `NVRAM/Add` | `TESTED(25G76)` | 第 A.6.7 节 |
| **V-017** | **问题消失。** 三份 `boot.efi`（Preboot、System `CoreServices`、`usr/standalone/i386`）SHA-256 完全相同（`5783955a…c64060`，723,512 字节），所以默认源取哪一份都一样。三份都**未经代码签名**，`file` 报 `PE32+ executable (EFI application) x86-64` | `TESTED(25G76)` | `76-bootefi.txt`，第 A.6.6 节 |
| **V-021** | **一半关闭。** `bless --info /` 直接给出：blessed folder = `/System/Volumes/Preboot/<VG>/System/Library/CoreServices`，blessed file = 同目录下的 `boot.efi`，两者记成 APFS 文件 ID（`12884902198` / `12884902278`）。**文件清单也已拿到**（第 A.6.7 节的 10 类件）。**仍缺的只是「bless 这一条命令在一块空盘上会不会把这些都铺出来」** | `TESTED(25G76)` 清单；`INFERRED` 生成 | `44-bless-info-root.txt`，第 A.6.7 节 |
| **V-029**（新） | **ESP 建得出来，但只能用 `newfs_msdos -F 32`。** `diskutil eraseVolume FAT32` 虽然也返回 0，却会把 p1 的类型 GUID 改成 `Microsoft Basic Data`，固件就不再把它当 ESP | `TESTED(25G76)` | 第 A.1.2 节 |
| **V-030**（新） | **`gpt(8)` 的修改类子命令被它自己的护栏拒掉，与权限无关。** `dd` 对同一裸设备读写都 `rc=0`（**不带 sudo 也是**），`gpt -r show` 正常，`gpt create -f` 一律 `operation not permitted`。连带结论：`newfs_msdos` / `asr` / `dd` 这些不受影响 | `TESTED(25G76)` | 第 A.1.0 节的七条探针表 |

#### E.3.1 仍未关闭的（原表，1.0 的措辞保留）

| # | 问题 | 标签 | 查清方法 | 在 D 节范围内 | 阻塞什么 |
|---|---|---|---|---|---|
| **V-034**（新，**现在的第一优先**） | 一个从零建出来的卷怎么变成 ARV。`bless --create-snapshot` 明确拒绝（`Can't use snapshot options on non ARV volume`） | `TESTED(25G76)` 现象；`BLOCKED` 解法 | 第 A.10.2c 节的三条候选：S1 `asr restore --toSnapshot --erase`（最可行，`75` 的 R1）／S2 自己调 `fs_snapshot_create` + `fs_snapshot_root`／S3 不要 ARV，靠 `csr-active-config` bit 11 | S1 **是**（`bake` job）；S2 **是**（写个小 C 程序）；S3 **否**（只能启动才知道） | **第 A.9 节整层。** 这是现在唯一没有已验证自建手段的一层 |
| **V-033**（新） | `bless` 判断「volume group 里有没有一个与**当前运行的 macOS** 兼容的 System role 卷」。在 25G76 的运行器上 bless 一块 25G325 的盘，这条检查怎么判 | `BLOCKED` | 下一轮：对一块铺了 25G325 payload 的 scratch 卷跑 `bless --verbose`，看这一行的措辞 | **是**（`tooling`） | 若它拒绝跨版本，`75` 的 R6（UpdateBrain 产 25G325）就必须自己完成 bless，不能靠运行器的 `bless`。**R1 路径不受影响**（源就是运行器自己） |
| ~~**V-031**~~ | ~~`-role D -groupWith` 被拒~~ | **已解决**，见第 A.3.3a 节 | 根因：`apfs_newfs: A Non-sealed system sibling volume is not allowed`。解法：先建 Data，再建 System 并 `-groupWith` 它 | — | — |
| **V-032**（新） | Preboot 卷根上那个 16 字节的 `com.apple.BootInfo` xattr 是什么、谁写的 | `BLOCKED` | `xattr -px com.apple.BootInfo /System/Volumes/Preboot` 的 16 字节原文；与 volume group UUID 比对 | **是**（`preboot`，下一轮加一条） | 不阻塞（我们不写它）。若它是启动链的输入，缺它的表现会是「选择器里没有 macOS」 |
| **V-020** | `--bootefi` 的「拷贝 boot objects」语义在 `--snapshotname` 下是否同样启用 | `BLOCKED` | 前两轮都没跑到（护栏 bug + 缺 `<UUID>/` 目录）。第三轮的 workflow 里已经是「建目录 → bless → 若失败去掉 `--create-snapshot` → 再试 `--snapshotname`」三段 | **是**（`tooling`） | 不阻塞（第 A.9.3 节用合并的那一条） |
| **V-021** | `bless` 确切往 Preboot 写了哪些**文件** | **部分关闭**（清单已由第 A.6.7 节给出）；生成行为仍 `BLOCKED` | 已知的新前置条件：`<UUID>/` 目录必须先存在（第 A.6.6 节的 IMPORTANT 块）。第三轮据此重跑 | **是**（`tooling`） | 它决定第 A.6.7 节那张「谁铺什么」净表里 A 类与 B 类的分界线对不对 |
| **V-023** | `updatePreboot` 在非启动卷上能不能成功 | **部分关闭**：空卷上必然失败（`-69808`，见第 A.10.2a 节）。**预配用户之后能不能成功仍未知** | 第 B 节步 10 的顺序已确认正确；要在一块已预配用户的盘上再跑一次 | 否（要先铺完 Data 卷） | 它决定 Preboot 的登录 UI 与用户元数据那一半能不能铺 |
| **V-001** | `diskutil apfs createContainer` 会不会替我们把分区类型 GUID 改成 `7C3457EF-…` | ~~`INFERRED`~~ **已关闭，见 E.3.0** | 建完容器 `gpt show <rdisk>` 看 p2 类型。不一致就 `gpt remove` + `gpt add -t …` 重写 | **是**（`tooling`） | 类型不对 OpenCore 可能扫不到 p2。表现是「选择器里没有 macOS」 |
| **V-002** | `75` §0.0.1（两分区）与 `76` §3.1（三分区）的最终分区数 | 设计冲突 | 由 `75` 或 `76` 下一轮修订定版。**本文第 A.1.1 节已论证这个选择对本文零影响** | 否（文档工作） | 不阻塞本文。影响的是 BaseSystem 恢复环境在不在盘上 |
| **V-003** | `diskutil info -plist <分区>` 里取容器引用 disk 号的键名是不是 `APFSContainerReference` | `INFERRED` | `diskutil info -plist` 全文落盘后读键名 | **是**（`volumes`） | 不阻塞。第 A.2 节已给确定可用的退路（抓 `createContainer` 的 stdout） |
| **V-004** | macOS 的 `cp` 在跨卷拷一个 decmpfs 文件时的实际产物（是否带 `UF_COMPRESSED`） | `INFERRED` | 在运行器上对一个已知压缩的系统文件 `cp` 到 scratch 卷，`ls -lO` + `stat -f '%z %b %Xf'` 看结果 | **是**（`compression`） | 不阻塞（我们用 `ditto`）。它决定第 0.3.1 节 (f) 的那句判断对不对 |
| **V-005** | `AFT` 的 `8` 与 `9` 是不是就是 decmpfs 的 `compression_type` | `INFERRED` | 第 D.6 节的 `XATTR_SHOWCOMPRESSION` 读法，产出 type code 直方图，与 `8`→105,020 / `9`→28,913 对照 | **是**（`compression`） | 不阻塞（压缩交给 `ditto` 决定）。它决定我们能否在 L0 阶段按 type code 做更强的一致性校验 |
| **V-006** | 系统卷必须是大小写不敏感 APFS（`APFS` 而非 `Case-sensitive APFS`） | `INFERRED` | `diskutil info -plist /` 读 case sensitivity 字段 | **是**（`volumes`） | **建错了只能删卷重建**（`diskutil(8)`：personality 是永久的）。第 A.3.1 节 |
| **V-007** | `diskutil apfs addVolume -role B` 与 `-role V` 会不会被拒 | `INFERRED` | 两步：(a) 跑 `diskutil apfs addVolume` 不带参数取用法串；(b) 在 scratch 容器上实际建一个 `-role B` 的卷 | **是**（`tooling`） | **第 A.3 节的命令序列成不成立。** 三条退路已在 A.3.3。**第一优先** |
| **V-008** | System 卷内容的所有者是否一律 `root:wheel`，有没有已知例外 | `INFERRED` | 对运行器的 `/System` 抽样 `ls -n` 并统计 uid/gid 直方图 | **是**（`volumes`） | 不阻塞（第一轮一刀切 `root:wheel`）。例外清单若非空，第 A.4.3 节第 2 步要加例外处理 |
| **V-009** | `chflags restricted` 这个助记符是否被 25G325 的 `chflags` 接受 | `INFERRED` | `chflags` 用法串 + 对 scratch 文件实测，`stat -f '%Xf'` 回读 | **是**（`tooling`） | 不阻塞（退路是 `chflags 0x80000`）。第 A.4.2 节规则 3 |
| **V-010** | 17.99 GB 的「payload 未压缩字节」与 APFS 上的实占差多少（hardlink、稀疏、元数据） | `INFERRED` | 第 B 节步 7e：铺完 `diskutil info -plist <sysvol>` 读实占 | 否（要先造一次） | 决定容器尺寸下限。第 A.4.5 节 |
| **V-011** | `usr/share/firmlinks`（689 字节）与 `SystemMigration.framework/…/firmlinks`（680 字节）差的那 9 字节是什么 | `INFERRED` | 运行器上两份都落盘逐行 `diff` | **是**（`firmlinks-data`） | 不阻塞（我们铺的是 payload 里那两份原件）。它决定哪一份是「运行期生效的那张表」 |
| **V-012** | 谁读 `/usr/share/firmlinks`（内核 APFS 实现 / `launchd` 早期 / 别的） | `INFERRED` | `sudo fs_usage -f filesys \| grep firmlinks`；或 `sudo log stream --predicate` 抓 firmlink 相关子系统 | **是**（`firmlinks-data`） | 不阻塞。它决定这张表要不要进 Preboot（第 A.5.2 节判断是不要） |
| **V-013** | firmlink 会不会在「两卷成组 + System 卷上有 firmlinks 表 + Data 卷上有对应目录」时自动建立，不需要 `createFirmlinks` | `INFERRED` | 两段：(a) 第 D.4 节的 `stat -f '%d'` 探针在运行器上验证表逐条生效；(b) 启动一次自建盘，同一探针验证我们的盘 | **一半**（(a) 在 `firmlinks-data`，(b) 要 E0-L1） | **若不成立，必须找到 `-[MSUMigrationHelper createFirmlinks]`（RVA `0x11aade`）的等价用户态入口。** 第二优先 |
| **V-014** | Preboot 卷根下除 `<UUID>/` 之外还有什么（`i386/`？`Cryptexes/`？） | `BLOCKED` | 第 D.3 节第 2 项：`/System/Volumes/Preboot/` 的完整树 | **是**（`preboot`） | **第 A.6 节那张表最后三行。第三优先** |
| **V-015** | cryptex 的目录结构、形态（sealed DMG？）、manifest/ticket 的文件名与格式；以及「三个符号链接 + Preboot 卷上的内容」这条形态是否成立 | `BLOCKED` | 第 D.3 节第 3 项：`mount \| grep cryptex`、`readlink /System/Cryptexes/*`、`hdiutil info`、Preboot 卷根的 `Cryptexes/` 全树 | **是**（`cryptex`） | **第 A.6.5 节整节。** 与 `77` 的 `U-001` 是同一条未知的两面 |
| **V-016** | Preboot 里到底有没有 `com.apple.boot.*` 类的 plist；若有，谁写、内容是什么 | `INFERRED` | 第 D.3 节第 2 项的全树清单里 grep | **是**（`preboot`） | 不阻塞（boot-args 走 OpenCore `NVRAM/Add`）。第 A.6.3 节末段 |
| **V-017** | `bless --bootefi` 不给参数时的默认源路径常量 | `INFERRED` | 运行器上 `man bless`，读 FILES 一节的真实路径常量（**在线镜像把它丢了，本地 man page 不丢**） | **是**（`tooling`） | 不阻塞（第 A.6.4 节的三条依据已把答案压到 `usr/standalone/i386/boot.efi`）。但它是一条 10 秒就能关掉的项 |
| **V-018** | 谁把 `apfs.efi` 写进容器的 APFS jumpstart 区域；怎么离线验证它非空 | `INFERRED` | 两段：(a) 在运行器自己的容器上取一份已知良好的 jumpstart 样本（第 D.3 节追加项 15）；(b) 第 C.1 节 L0-11 的判据按样本收紧 | **是**（`tooling`） | **空的话 OpenCore 看不见容器里任何卷**（`76` §1.3 判据 1）。表现是「选择器里没有 macOS」，是最难归因的一类 |
| **V-019** | `bless --create-snapshot` 取的快照名格式 | `INFERRED` | `diskutil apfs listSnapshots <sysvol>` 在运行器上的全文 | **是**（`volumes`） | 不阻塞（我们不需要知道名字）。第 A.9.1 节 |
| **V-020** | `bless --bootefi` 的「拷贝 boot objects」语义在带 `--snapshotname`（而非 `--create-snapshot`）时是否同样启用 | `INFERRED` | `tooling` job 的 scratch 镜像上两种都跑一次，diff Preboot 全树 | **是**（`tooling`） | 不阻塞（第 A.9.3 节用合并的那一条）。它决定「拆成两步」这条备选路可不可行 |
| **V-021** | `bless --folder … --bootefi --create-snapshot --label … --verbose` 确切往 Preboot 写了哪些文件 | `BLOCKED` | `tooling` job：scratch 镜像上跑前后各做一次 Preboot 全树清单，diff；同时留 `--verbose` 的全文 | **是**（`tooling`） | **第 A.10.3 节第一行。** 它是第 A.6 节能不能从「机制」升级到「清单」的那一项 |
| **V-022** | `--create-snapshot` 写了 System 卷的哪些 APFS 字段；怎么离线确认「这个快照是 root snapshot」 | `BLOCKED` | `diskutil apfs listSnapshots -plist` 的全部键；`diskutil info -plist <sysvol>` 的全部键；两者在 bless 前后 diff | **是**（`volumes` + `tooling`） | 第 C.1 节 L0-3 目前只能验「有一个快照」，验不了「它是 root」。补上之后 L0-3 才是真判据 |
| **V-023** | `diskutil apfs updatePreboot <目标卷>` 在目标卷不是当前启动卷时能不能成功；`-od` 指向目标卷的 dslocal 是否可行 | `INFERRED` | `tooling` job：对 scratch 镜像里的卷跑一次，看退出码与输出 | **是**（`tooling`） | 不阻塞（第 B 节步 10 已做成 best-effort）。它决定 Preboot 的登录 UI 与用户元数据那一半能不能铺 |
| **V-024** | `stat -f%p` 在 25G325 上的输出格式（是否 6 位八进制） | `INFERRED` | 运行器上 `stat -f '%p %Sp' /etc/hosts` | **是**（`volumes`） | 不阻塞（退路是 `%Sp` 符号形式自己转）。影响第 C.1 节 L0-13 的 mode 比对 |
| **V-025** | 自建的、未经 Apple 签名的封印快照在 `VMM-x86_64`（非 T2 Intel）上能不能被引导 | `INFERRED` | **只能启动才知道。** `80` 的 E0-L1 | **否** | **整份规格的承重项。** 第 0.2 节的五路证据 + OCLP 的野外佐证把它压到了「几乎肯定能」，但它仍是 `INFERRED` |
| **V-026** | 完全不压缩铺设（丢掉全部 decmpfs）的系统能不能启动 | `INFERRED` | 只能启动才知道。造一块不带 `--hfsCompression` 的镜像跑 E0-L1 | **否** | 不阻塞主路径（主路径用 `--hfsCompression`）。它验证第 0.3.1 节「丢压缩不致命、只是变大」这条判断 |
| **V-027** | `PlatformSupport.plist` 的 board-id 门是否被 `VMM-x86_64` 实际通过 | `INFERRED` | 只能启动才知道。`71` §4.1 已证该 board-id 在清单里；verbose 启动看有无「不受支持的 board ID」 | **否** | 第 C.2 节 L1-9。失败的旁路是 F-1 的 `-no_compat_check` |
| **V-028** | `newfs_hfs` 在 25G325 上还在不在；`diskutil listFilesystems` 里 HFS+ 还能不能建 | `INFERRED` | `which newfs_hfs`；`diskutil listFilesystems` | **是**（`tooling`） | 决定第 D.5 节的 `-prebootSource` 实验能不能做。做不了就靠 `preboot` job 的观察法，证据弱一级 |

### 必须在造第一块镜像之前做掉的三条

从上表挑出「在 D 节范围内」且「阻塞下游」的，按优先级：

> **1.1 更新：原来列的三条（`V-007`、`V-014`、`V-021`）已全部关闭。** 换上来的三条如下。

| # | 为什么必须先做 | 成本 |
|---|---|---|
| **V-031** | **它决定第 A.3 节那段命令序列成不成立，而且现在是已知不通而不是未知。** 没有成组的 Data 卷，整块盘启动不到用户态。第 A.3.3a 节已写出六条待试变体 | 一个 job，六次 `addVolume` |
| **V-020 / V-023** | 前两轮它们都因为自家护栏的一个 shell 写法错误而从未真正跑过（第 A.10.2 节的 1.1 注记）。护栏已修，这两条现在是「跑一次就知道」 | 一个 job，一块 4 GB 的 scratch 镜像 |
| **V-028** | 前两轮 `diskutil apfs convert` 的参数顺序写反（`disk` 必须在前），所以**Apple 自己认为的 Preboot 必需件清单**一次都没取到。参数已修。它的价值是把第 A.6.7 节的「谁铺什么」净表从推断变成 Apple 的自述 | 一个 job，一块 2 GB 的 HFS+ scratch |

**`V-015`（cryptex）排第四而不是前三**，理由：它的体量最大（2.4 GB），但它与 `77` 的 `U-001` 共享同一条未知，而 `77` 已经把那条未知排了期。先把前三条关掉、造出一块「除 cryptex 之外都对」的镜像跑一次 E0-L1，**cryptex 缺失的表现（第 C.2 节 L1-4）本身就是关于它的最强证据**。
