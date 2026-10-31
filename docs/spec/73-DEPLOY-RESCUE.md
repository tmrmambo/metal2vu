# 73 无控制台云实例上的 macOS 镜像投放、rescueOS 与救砖路径

文档版本：1.0
基线日期：2026-11-01
对应组件：无（基础设施分册，服务于全部组件）
上级文档：`docs/spec/00-OVERVIEW.md`
配套分册：`docs/spec/71-IMAGE-OPENCORE.md`、`docs/spec/80-TEST-HARNESS.md`

## 0. 本文作用与写作约束

本文回答一个问题：**在一台既没有可编程控制台、也没有串口的公有云 KVM 实例上，怎么把 macOS 26.7.2 (25G325) x86_64 装进系统盘，并且在它起不来时还能把机器拿回来。**

它是 `71-IMAGE-OPENCORE.md` 第 8.3 节的后继。`71` 回答了"镜像长什么样"，本文回答"镜像怎么进到云上的那块盘里，以及进去之后万一不启动怎么办"。

### 0.1 职责边界

- **不重复 `80-TEST-HARNESS.md` 第 1 节的平台调研**，但本文**补齐了它漏掉的两条 Vultr 能力**：`ipxe_chain_url` 与 bootable Block Storage（见第 3.2、3.1.4 节），并据此修改它第 3.3.8 节的工具组（见第 6.1 节）。
- **不重复 `71` 第 6 节的 `config.plist`**。本文只增删它的两处：`UEFI/Drivers` 与 ESP 的文件布局（见第 5.3 节）。
- **不重复 `71` 第 8.2 节的 L1 命令行**。本文第 7 节处理的是"那条命令行根本跑不起来"的情况。

### 0.2 写作约束

- 每条结论带证据标签（`KNOWN` / `INFERRED` / `BLOCKED` / `TESTED`）与来源 URL。
- **本项目至今 `TESTED` 数量为零，本文同样没有 `TESTED`。** 本文全部内容在 E0-L2 通过之前都是待验证的设计。
- 脚本与 API 调用按可直接照抄编写。
- 对 `bin456789/reinstall` 与全部外部网页的内容均为**转述与机制说明**，不作连续摘录，引用处给文件路径与链接。**内容已转述以符合许可限制。**

### 0.3 五条结论先行

| # | 问题 | 结论 | 标签 | 依据 |
|---|---|---|---|---|
| 1 | Vultr 支不支持上传自定义镜像 | **没有直传接口**，但有两条"平台从公开 URL 拉"的路。几十 GB 的 macOS 系统盘走 `POST /v2/snapshots/create-from-url`，不走 ISO | `KNOWN` | 第 3 节 |
| 2 | 投放机制的最终形态 | 主路径是**本地装好 → 转 raw → 托管 → `create-from-url` → `POST /v2/instances` 带 `snapshot_id`**；Alpine + `dd` 作为第二条路径与全部改盘操作的通用底座 | `INFERRED` | 第 4 节 |
| 3 | 是否绕开 ISO 的 10 GB / 2 槽位限制 | **是，完全绕开。** 两条新路径都不占 ISO 槽位，也不受 10 GB 约束。ISO 只在"本地连 macOS 都装不起来、必须在云上手工装一次"这一种情况下还需要用一次 | `INFERRED` | 第 4.7 节 |
| 4 | 救砖的最后一道保险 | `PATCH /v2/instances/{id}` 带 `os_id` 换回原厂 Linux，或 `POST /v2/instances/{id}/reinstall`。两者都会抹盘，但都能把一台黑屏实例变回一台能 SSH 的机器，**纯 API，不需要控制台** | `KNOWN` | 第 5.5 节 |
| 5 | 本地没有 KVM 怎么办 | TCG 纯模拟不值得（第 7.3 节）。首选替代是**GitHub Actions 的 Linux runner**（官方声明支持 Android 模拟器硬件加速，即 `/dev/kvm` 可用），其次是 Vultr Bare Metal 自建 KVM | `INFERRED` | 第 7.4 节 |

---

## 1. 问题陈述：没有控制台的部署是一道单向门

### 1.1 平台事实（复述，不重新论证）

以下四条来自 `80-TEST-HARNESS.md` 第 1.2、1.3、1.4 节，本文直接当前提用：

| 事实 | 标签 | 本文用到它的地方 |
|---|---|---|
| Vultr 没有可编程 VNC/控制台端点，网页控制台是 noVNC + 门户会话态鉴权 | `KNOWN` | 整篇。它是"砖"这个概念存在的唯一原因 |
| Vultr 没有串口 | `KNOWN` | 第 5.4 节。它决定了救砖只能靠"换引导对象"，不能靠"看日志改参数" |
| 自定义 ISO 只能由 Vultr 从公开 URL 拉取；账户上限 2 个；单个 ≤10 GB | `KNOWN` | 第 3.1.1、4.7 节 |
| 快照创建最长约 30 分钟 | `KNOWN` | 第 4.2 节的耗时预算 |

补一条本轮新查到的、对整个方案成立至关重要的事实：

**Vultr 实例的公网 IPv4 由 DHCP 下发。** `KNOWN`，官方文档明确写了部署虚拟云服务器时 IP 地址是通过 DHCP 自动分配的，只有 BGP 或私有网络场景才需要手配静态（转述自 <https://docs.vultr.com/configure-a-vultr-server-to-use-dhcp-for-dynamic-ip>）；网络调试文档也说手改网络设置丢连通性后重启往往就恢复成默认的 DHCP 配置（转述自 <https://docs.vultr.com/support/products/compute/how-do-i-debug-my-vultr-compute-instance-network-configuration>）。

**为什么这一条决定成败**：macOS 不是 Vultr 支持的 OS，平台不可能往它里面注入网络配置。如果 Vultr 要求 guest 自己配静态 IP，那么一台装好 macOS 的实例起来之后拿不到地址、SSH 永远不通，**整个方案没有观测通道，直接作废**。DHCP 则意味着 macOS 开箱即能上网，不需要任何注入。`bin456789/reinstall` 为此准备了一整套"智能判断动静态"的逻辑（README 的功能描述里列了 `/32`、`/128`、网关不在子网内等情形，转述自 <https://github.com/bin456789/reinstall/blob/main/README.md>），**我们在 Vultr 上不需要这套逻辑**，但如果以后换平台，这是第一个要重查的点（D-004）。

### 1.2 体积事实（复述）

来自 `71` 第 1.1、1.5、8.3.2 节：

| 件 | 字节 | 与 ISO 10 GB 上限的关系 |
|---|---:|---|
| `InstallAssistant.pkg` | 18,384,411,815 | **184%，放不进去** |
| `SharedSupport.dmg` | 18,366,480,610 | **184%，放不进去** |
| `x86_64BaseSystem.dmg`（已还原） | 1,464,270,504 | 14.6%，在限内 |
| OpenCore EFI 树（DEBUG + 3 kext + 2 SSDT） | < 30 MB | 0.3% |
| 装好的 macOS 系统盘（`71` 第 8.1 节估计） | 20 到 40 GB 实占 | **200% 到 400%，放不进去** |

**最后一行是本文存在的理由。** `71` 第 8.3 节解决的是"把安装介质送上去"，而那只有 1.5 GB、确实能塞进 ISO。但 `80` 第 2.4.3 节的 golden snapshot 流程要求在云上**手工经网页控制台装一次系统**，而这一步既不可自动化、又在显示栈没修好的前提下极易失败。本文要做的是把"送上去"的对象从 1.5 GB 的安装介质换成几十 GB 的**已装好的系统盘**，从而把"在云上装系统"这件事整个删掉。

### 1.3 "砖"的定义与三种形态

本文把 guest 的可达性分成四级。只有 S0 是正常状态，S3 是砖。

| 状态 | 定义 | 还剩什么通道 | 本文对应的救砖层 |
|---|---|---|---|
| S0 | SSH 可达 | 全部 | 不需要救 |
| S1 | macOS 起来了但显示坏/WindowServer 死，SSH 仍可达 | SSH | R0（第 5.4 节） |
| S2 | macOS 不启动，但引导链还在我们手里（ESP 可被另一个 OS 改写，或平台还能换引导对象） | 平台 API + rescueOS | R1 到 R3 |
| S3 | 引导链也不在我们手里，且 rescueOS 进不去 | 只有平台 API 的抹盘类操作 | R4、R5 |

**设计目标：让 S2 覆盖掉绝大多数失败，并保证 S3 永远有出路。** 具体做法是第 5 节的持久 rescue 分区（让 S2 可达）与第 5.5 节的平台级重装（让 S3 有底）。

一条必须写死的规则：**任何一次投放都不得让实例在"没有任何第二引导对象"的状态下重启。** 这是本文全部流程的不变量，第 4.8 节的脚本里体现为"写 rescue 分区在写 macOS 系统分区之前"。

---

## 2. `bin456789/reinstall` 的机制

本节是用户给的起点。它解决的问题与我们的问题同构：**只有 SSH、没有控制台，要把系统盘换成另一个操作系统，并且换失败了还能回去。**

全部内容为转述，引用处给文件与链接。**内容已转述以符合许可限制。**

来源：
- README：<https://github.com/bin456789/reinstall/blob/main/README.md>
- 第一阶段脚本 `reinstall.sh`：<https://github.com/bin456789/reinstall/blob/main/reinstall.sh>
- 第二阶段脚本 `trans.sh`：<https://github.com/bin456789/reinstall/blob/main/trans.sh>

### 2.1 它是什么

`KNOWN`（README）。一个一键 VPS 重装脚本，支持约 20 种 Linux 发行版与 Windows，支持 Linux↔Windows 任意方向重装；自带四个功能：重装 Linux、DD raw 镜像到硬盘、重启进 Alpine Live OS（内存系统）、重启进 netboot.xyz。README 自称的三条设计取向与我们高度相关：专门适配低内存小机器（比官方 netboot 省内存）、**全程用分区表 ID 识别硬盘以确保不写错盘**、支持 BIOS 与 EFI 两种引导。

它对 Alpine 的内存要求记为 256 MB RAM / 1 GB 磁盘（README 的发行版表）。这与 Alpine 官方 netboot 服务器给出的"网络模式至少需要 256 MB 内存，因为 initramfs 与 modloop 有体积"一致（转述自 <https://boot.alpinelinux.org/>）。

### 2.2 两阶段结构

这是它最值得抄的架构决定。

```text
阶段 1：reinstall.sh          在【原系统】里跑（Linux 或 Windows/Cygwin）
  ├─ 探测：架构、是否 EFI、是否虚机、主硬盘是哪一块、磁盘 ID
  ├─ 下载：GRUB EFI 二进制、下一阶段 OS 的 vmlinuz/initramfs/modloop
  ├─ 改造：把 trans.sh 与网络配置脚本塞进 initramfs
  ├─ 落盘：把 grub + vmlinuz + initramfs 放到【第一个 FAT 分区】
  ├─ 挂钩：创建一个新的 EFI 启动项，并把它设成【一次性】下次启动
  └─ 重启

阶段 2：trans.sh              在【Alpine / debian-installer 的 initramfs】里跑
  ├─ 起网络、起 sshd（给人一个观察与救砖的入口）
  ├─ 真正的破坏性操作：分区、格式化、dd、装 bootloader
  └─ 重启进最终系统
```

**两阶段的意义**：阶段 1 完全不触碰系统盘的数据，它唯一的写操作是往 ESP 里加文件、往固件 NVRAM 里加一个启动项。所以**阶段 1 失败等于什么都没发生**，而且 README 给了一条显式的取消命令（`bash reinstall.sh reset`，必须在重启前跑），它删掉 BootNext 与自己创建的启动项。

对我们的直接后果：**破坏性操作必须全部发生在 rescueOS 里，不得发生在 macOS 里。** macOS 侧只许做"加文件、改引导选择"这两类可逆动作。

### 2.3 怎么在没有控制台的情况下切进 Alpine：EFI 一次性启动项，不是 kexec

这是本节最重要的机制，也是用户问题 B 第一条的答案。

`KNOWN`，来源 `reinstall.sh` 的 `add_efi_entry_in_linux()`。该函数的动作序列（转述）：

1. 找出原系统里第一个 FAT/vfat 分区当落脚点。注释里明确说了**不关心它是不是"正式"的 ESP，只要是 FAT 就能被加进引导**。
2. 把 GRUB 的 EFI 二进制复制到该分区的 `EFI/reinstall/` 目录下。目录名刻意不叫 `grub`，因为机器上可能已经有一个 GRUB。
3. 用 `findmnt -T <dir> -no SOURCE` 反查该目录所在的块设备，再拆成磁盘与分区号。
4. 调 `efibootmgr --create-only --disk <disk> --part <num> --label <name> --loader '\EFI\reinstall\<file>'` 创建启动项。`--create-only` 的作用是**只创建、不动 BootOrder**。
5. 取回新建项的编号，调 `efibootmgr --bootnext <id>`。

**`--bootnext` 是整个设计的安全阀。** UEFI 的 `BootNext` 是一次性变量：固件读取并尝试它一次，随后清除，下次启动回到原来的 `BootOrder`。因此：

- Alpine 起来了 → 继续走阶段 2。
- GRUB 加载失败、内核 panic、Alpine 起来但网络不通 → **只要让它再重启一次，就回到原系统**。我们不需要控制台去"改回来"，固件自己改回来了。

它没有用 `kexec`。`KNOWN`：全仓库对 kexec 的处理只有一处，而且是**反向**的。`reinstall.sh` 发现 `/etc/default/kexec` 存在时会把 `LOAD_KEXEC=true` 改成 `false`，注释说明某些厂商的 Debian 镜像默认开了 kexec，必须禁掉。

**为什么不用 kexec，以及我们为什么也不该用**：

| 维度 | `kexec` | EFI 一次性启动项 |
|---|---|---|
| 失败后果 | 新内核起不来就是**死机**，没有任何自动回退，必须靠控制台或平台强制重启 | 固件自动回到原 `BootOrder` |
| 对原系统的要求 | 原系统内核要编进 `CONFIG_KEXEC`，`kexec-tools` 可用，且云厂商的内核常裁掉它 | 只要是 EFI 机器、有 FAT 分区、`efibootmgr` 能写 NVRAM |
| 设备重置 | 跳过固件，设备处于上一个内核留下的状态，网卡/盘控制器可能起不来 | 走完整固件初始化，设备状态干净 |
| 对我们的额外问题 | **macOS 完全没有 kexec**。R0 层（macOS 存活时切进 rescue）无法用它 | macOS 能挂载并写 FAT ESP（`msdosfs` 在 System KC 内，`71` 第 8.4 节，`KNOWN`） |

**结论：抄 EFI 一次性启动项，不抄 kexec。** 但要注意它有一个我们必须回答的前置条件：`efibootmgr` 写 NVRAM 要能持久。在 Vultr 上这正是 `80` 的 H-002（`BLOCKED`）。本文第 5.3 节因此给出一个**不依赖固件 NVRAM**的等价机制（ESP 内文件交换），把 H-002 从阻塞项降级为优化项。

### 2.4 Alpine 怎么在内存里跑

`KNOWN`，来源 `reinstall.sh` 的 `setos_alpine()` 与 `build_nextos_cmdline()`。它从 Alpine 镜像站的 `releases/<arch>/netboot/` 取三个文件：`vmlinuz-<flavour>`、`initramfs-<flavour>`、`modloop-<flavour>`，并把内核命令行设成 `alpine_repo=<apk 仓库 URL> modloop=<modloop URL>`，外加 `console=ttyS0,115200n8 console=tty0`（`echo_tmp_ttys()`）。

机制（`KNOWN` 对于文件角色，来自 Alpine 官方 netboot 说明 <https://boot.alpinelinux.org/>）：initramfs 自带最小根文件系统并在内存中展开，内核模块不在 initramfs 里而在 `modloop`（一个 squashfs），由 init 通过 HTTP 取回并挂载；apk 仓库也走 HTTP。**结果是一个完全不依赖本地磁盘的系统，所以系统盘可以被整块覆盖。**

它对 initramfs 做了四处改造（`KNOWN`，`reinstall.sh` 的 `mod_initrd_alpine()`，转述）：

1. 若内核的 `modules.builtin` 里没有 ipv6，就从 modloop 里单独抽出 `ipv6.ko` 塞进 initramfs，否则纯 IPv6 机器起不来网。
2. 从 apk 包里取 `dhcpcd` 并调整其 `slaac` 配置。
3. 塞进一个网络配置脚本（`/initrd-network.sh`），在 init 早期按阶段 1 探测到的网络参数配好地址。
4. 塞进 `trans.sh` 并挂一个启动钩子去执行它。

**对我们的后果**：直接用 Alpine 官方 netboot 的 initramfs 是不够的，它不含我们的 SSH 公钥、不含我们的脚本。但我们**不必像它一样重打 initramfs**：Alpine 的 init 支持 `apkovl=<URL>` 内核参数，从 HTTP 取一个 overlay 配置包（`INFERRED`，该参数的存在有公开用例，例如 <https://stackoverflow.com/questions/79819653>，但本项目未实测；查清方法见 D-005）。把 `authorized_keys`、`sshd` 的 `local.d` 启动脚本、我们的投放脚本全部打进一个 `rescue.apkovl.tar.gz`，用 `apkovl=` 拉进来，比改 initramfs 简单得多，且产物是纯文本可审计的。

### 2.5 DD 阶段：流式直写，加一个"先留最后 1 MiB"的回滚保险

`KNOWN`，来源 `trans.sh` 的 `dd_raw_with_extract()` 与 `pipe_extract()`。

裸 raw 镜像的写入是一条管道：用 `wget <url> -O-` 取流（注释说明选官方 `wget` 而非 busybox 版是为了进度条与自动重试），经 `pipe_extract()` 按镜像类型解压（支持 `xz`/`gzip`/`zstd` 以及 `tar` 与 `tar.*` 组合，分别 `apk add` 对应解压器后以 `-dc` 或 `tar x -O` 的形式作为过滤器），直接重定向到 `/dev/<主盘>`。README 对应的说明是支持 raw 与固定大小 vhd，未压缩或压缩为 `.gz`/`.xz`/`.zst`/`.tar*`。

它还处理了一个实际会碰到的边界：写到盘尾报 `No space` 时，用 `parted` 读出最后一个分区的结束位置，若该位置仍在盘内就判定"镜像比盘大的那部分是无用尾巴"（vhd 结尾有 512 字节元数据），**安全忽略**；否则才真正报错。

qcow2 路径（`dd_qcow()`）用的是另一套、而且更谨慎的写法（`KNOWN`，转述）：

1. `qemu-nbd -c /dev/nbd0 <qcow>` 把镜像挂成块设备。
2. 可选地在 nbd 设备上做 btrfs 回收与分区收缩，再 `qemu-img resize --shrink`，把要写的数据量压到最小。
3. **先把镜像的前 1 MiB 读到内存里的 `/first-1M`**。
4. 把 1 MiB 之后的全部内容写到目标盘的 1 MiB 之后（`dd ... bs=1M skip=1 seek=1`，或 `pv | dd`）。
5. 全部写完、断开 nbd 之后，**才把内存里的前 1 MiB 写到盘头**。
6. 若镜像的虚拟容量大于物理盘，用 `sgdisk` 修 GPT 备份表的位置，否则 `partprobe`/`parted` 都会失败。

**第 3、4、6 步是本文要抄的三个设计。** 前 1 MiB 里装的是保护性 MBR、GPT 主头与分区表、以及 BIOS 引导代码。把它**留到最后写**意味着：写入过程中断电、网络断流、进程被 OOM 杀掉，盘上仍然是**旧的分区表**，机器下次启动还是旧系统。这是在"没有控制台"的环境里唯一能做的事务性近似：把不可原子的整盘写入，变成"先写数据区，再用一次 1 MiB 的小写入翻转指针"。

### 2.6 失败之后还能回去：它的四层退路

`KNOWN`（README 与两个脚本），按从轻到重排：

1. **还没重启** → `bash reinstall.sh reset` 取消整次重装；它删掉 BootNext 并按标签删除自己创建的启动项（`reinstall.sh` 里的清理段）。
2. **`--hold 1`** → 只重启进安装环境、不执行安装，供 SSH 登录先验证网络通不通。README 对 Alpine Live OS 功能特别说明：它不删任何数据、不自动重装，若用户没手工破坏原系统，再次重启会回到原系统。
3. **装到一半失败** → README 明确写了即使安装过程出错也能连 SSH 手工救砖，并给了一条"自动救砖成 Alpine"的命令（在安装环境里跑 `/trans.sh alpine`）。
4. **`--hold 2`** → DD 结束后不自动重启，留着 SSH 进去改东西。

**第 2 条是本文第 4.8 节脚本的骨架**：先用一次"只进 rescueOS、不动盘"的演练确认通道可用，再执行破坏性步骤。在没有控制台的机器上，这个演练不是谨慎，是必需。

### 2.7 它对云厂商差异的处理，以及它自己留下的 Vultr 观察

`KNOWN`（`reinstall.sh` 的注释与 README 的兼容性表）。它的适配集中在三类问题：

- **主盘识别**：用 `lsblk -rn --inverse` 从 `/` 的挂载源反推物理盘，并处理跨盘 LVM / btrfs / 软 RAID 的情形；多盘时**拒绝猜测，要求人选**。随后用 `fdisk -l` 读 `Disk identifier` 当盘的指纹，传给阶段 2 去校验，防止写错盘。
- **固件与引导差异**：BIOS 与 EFI 两条路分别处理，EFI 走第 2.3 节的启动项，BIOS 走本机 GRUB/extlinux。
- **厂商个例**：注释里逐条记着具体厂商的坑（例如 GCP 上某些 Windows ISO 在 PE 阶段反复重启、腾讯云轻量 Debian 默认开 kexec 要禁掉、某厂商的 `/boot/grub` 是软链接要特殊处理）。

**其中有两条直接关于 Vultr**，`KNOWN` 对于"该项目作者如此记录"，`INFERRED` 对于"在 25G325 与当下的 Vultr 上同样成立"：

1. 注释记录：Vultr 官网在新建数据盘时写明**部分地区的实例不能从数据盘启动**；作者实测给数据盘写 NVRAM 启动项**不生效**，手动从固件里选该盘的 EFI 文件才能启动，**但 `BootNext` 指向数据盘的条目却是生效的**。
2. 注释记录：在 Vultr 的软 RAID 0 Debian 上，进入 GRUB EFI 后识别不出 `md1`，也少了 `hd1`；作者的推测是用 `BootNext` 时固件走"快速路径"，只初始化了存放 EFI 文件的那块盘。

**对我们的后果有三条**：

- 第 5.2 节的 rescue 分区**必须放在系统盘内**，不能放到一块 Block Storage 上。"从数据盘启动"在部分地区不成立，而我们不知道自己落在哪个地区。
- `BootNext` 可能是 Vultr 上唯一生效的 NVRAM 引导手段，所以第 5.3 节把它列为次选机制而不是删掉。
- **Vultr 的某些机型/地区可能用软 RAID 做系统盘。** 如果系统盘在 guest 眼里是 `md` 而不是单块盘，那么把一个 GPT raw 镜像整块 `dd` 上去的前提就不成立。这是一个本文之前没有登记过的风险，记为 **D-001**，必须在 E0-L2 的第一步查清。

### 2.8 能直接搬的 / 必须改的

| 机制 | 能否直接搬 | 为什么 |
|---|---|---|
| 两阶段结构（原系统内准备 + rescueOS 内执行破坏） | **直接搬** | 与原系统是什么无关 |
| EFI 一次性启动项 + `--create-only` + `--bootnext` | **搬思想，换实现** | macOS 没有 `efibootmgr`。macOS 侧改用"ESP 内交换 `BOOTX64.EFI`"（第 5.3 节），语义等价且不依赖 NVRAM 持久性 |
| Alpine netboot 三件套在内存里跑 | **直接搬** | 这是 Alpine 的通用能力，与目标 OS 无关 |
| 改造 initramfs 注入脚本与网络配置 | **换成 `apkovl=`** | 我们不需要适配二十种发行版，只要一份固定的 rescue 配置。少一步重打包就少一处可能坏 |
| 流式解压直写（`wget -O- \| 解压 \| > /dev/盘`） | **直接搬** | 第 4.5 节 |
| "前 1 MiB 留到最后写"的回滚保险 | **直接搬，并加强** | 第 4.5 节把它和分段校验合在一起 |
| `sgdisk` 修 GPT 备份表 | **直接搬** | 第 4.6 节的瘦镜像必然触发这个问题 |
| `--hold 1` 式的空跑演练 | **直接搬，并设为强制** | 第 4.8 节 |
| 智能动静态 IP 配置 | **不搬** | Vultr 是 DHCP（第 1.1 节）。搬进来是纯负债 |
| DD 之后自动扩展系统盘（它只对 Windows 做） | **必须自己写** | macOS 侧是 `diskutil apfs resizeContainer`，机制完全不同（第 4.6 节） |
| `trans.sh` 里的分区/格式化/装 bootloader | **不搬** | 它是为 Linux/Windows 写的。我们的目标盘布局由 `71` 与本文第 5.2 节定义 |
| netboot.xyz 功能 | **不搬，但记住它** | 它证明了 Vultr 的 iPXE 链能跑第三方脚本（第 3.2 节） |

---

## 3. Vultr 到底支不支持上传自定义镜像

### 3.0 结论先行

**Vultr 没有"上传自定义镜像"这个接口。它有两条"你把镜像放在公开 URL 上，平台来拉"的路，外加两条"从已有磁盘派生"的路。**

`KNOWN`，依据是 API 的形状本身：官方 Go 客户端里与镜像导入相关的请求体**只有 URL 字段，不存在任何 multipart 或分块上传端点**。`ISOReq` 的全部字段是 `{url}`，`SnapshotURLReq` 的全部字段是 `{url, description, uefi}`（来源：<https://github.com/vultr/govultr/blob/master/iso.go>、<https://github.com/vultr/govultr/blob/master/snapshot.go>）。

**我们该用哪条路，一句话**：把一块装好 macOS 的 raw 磁盘镜像托管到自有对象存储的公开 URL 上，用 `POST /v2/snapshots/create-from-url`（`uefi: true`）变成快照，再用 `POST /v2/instances` 带 `snapshot_id` 部署。

一个需要注意的措辞差异（`INFERRED`）：Cloud GPU 的开通文档在描述 ISO 选项时写的是"安装账户里已有的 ISO，或从你的工作站上传一个新的 ISO 镜像"（转述自 <https://docs.vultr.com/products/compute/cloud-gpu/provisioning>），即**网页门户可能支持直接传文件**，而 API 只收 URL。这不改变本节结论（我们要自动化，只能用 API），但它解释了用户"不确定是不是能上传"的来源。门户是否真能直传记为 D-002。

### 3.1 四条路逐条

#### 3.1.1 `POST /v2/iso`：公开 URL 拉 ISO

`KNOWN`（来源同上，以及 `80` 第 1.2 节）。

```bash
export VH="Authorization: Bearer ${VULTR_API_KEY}"
export VJ="Content-Type: application/json"

# 创建
curl -s -X POST "https://api.vultr.com/v2/iso" -H "$VH" -H "$VJ" \
  -d '{"url":"https://assets.example.net/macos-26.7.2-25G325-oc.iso"}'
# → {"iso":{"id":"...","filename":"...","size":...,"status":"pending"}}

# 轮询并取平台回报的哈希
curl -s "https://api.vultr.com/v2/iso/${ISO_ID}" -H "$VH" | jq '.iso|{status,size,md5sum,sha512sum}'

# 列出公共 ISO 库（不占账户槽位）
curl -s "https://api.vultr.com/v2/iso-public" -H "$VH" | jq '.public_isos[]|{id,name,description}'

# 挂载 / 卸载 / 查状态（挂载与卸载都会重启实例）
curl -s -X POST "https://api.vultr.com/v2/instances/${INST_ID}/iso/attach" -H "$VH" -H "$VJ" -d "{\"iso_id\":\"${ISO_ID}\"}"
curl -s -X POST "https://api.vultr.com/v2/instances/${INST_ID}/iso/detach" -H "$VH"
curl -s "https://api.vultr.com/v2/instances/${INST_ID}/iso" -H "$VH" | jq -r '.iso_status.state'
```

| 项 | 值 | 标签 |
|---|---|---|
| 体积上限 | 10 GB | `KNOWN`（<https://docs.vultr.com/how-to-upload-and-use-custom-isos-on-vultr>） |
| 账户槽位 | 2 | `KNOWN`（<https://docs.vultr.com/products/orchestration/isos/faq>） |
| 来源 | 只能公开 URL | `KNOWN` |
| 完整性校验 | 平台回报 `md5sum` + `sha512sum` | `KNOWN` |
| 同一实例可挂几张 | 1 | `INFERRED`（attach 请求体只有一个 `iso_id`，状态查询只回单个 `state`，`71` 第 8.3.1 节） |
| 公共 ISO 库 | 含 Finnix、GParted、Hiren's BootCD PE、SystemRescue | `KNOWN`（<https://docs.vultr.com/products/orchestration/isos/provisioning>、<https://docs.vultr.com/product-overviews/isos>） |
| 一个副作用 | 装自定义 ISO 会**停用实例管理页上的默认登录凭据** | `KNOWN`（转述自 <https://docs.vultr.com/public/doc-assets/pdfs/collection_item/products-compute-cloud-compute-management-custom-iso.pdf>） |

**结论：ISO 这条路不能承载 macOS 系统盘**（20 到 40 GB 超限 2 到 4 倍）。它只剩两个用途：承载 1.5 GB 的安装介质（`71` 第 8.3.3 节），以及当第 5.4 节 R3 层的救援介质。

#### 3.1.2 `POST /v2/snapshots/create-from-url`：关键的那一条

`KNOWN`（`govultr/snapshot.go`）。请求体三个字段，其中 `uefi` **没有 `omitempty`**，即它总是被序列化，必须显式给值：

```go
type SnapshotURLReq struct {
    URL         string `json:"url"`
    Description string `json:"description,omitempty"`
    UEFI        *bool  `json:"uefi"`
}
```

```bash
# 创建
SNAP_ID=$(curl -s -X POST "https://api.vultr.com/v2/snapshots/create-from-url" \
  -H "$VH" -H "$VJ" \
  -d '{"url":"https://assets.example.net/macos-26.7.2-25G325-golden.raw",
       "description":"macos-26.7.2-25G325 golden r1",
       "uefi":true}' | jq -r '.snapshot.id')

# 轮询。size 是解压后体积，compressed_size 是计费依据
until [ "$(curl -s "https://api.vultr.com/v2/snapshots/${SNAP_ID}" -H "$VH" | jq -r '.snapshot.status')" = "complete" ]; do
  sleep 60
done
curl -s "https://api.vultr.com/v2/snapshots/${SNAP_ID}" -H "$VH" | jq '.snapshot|{status,size,compressed_size,os_id}'

# 直接部署
curl -s -X POST "https://api.vultr.com/v2/instances" -H "$VH" -H "$VJ" \
  -d "{\"region\":\"ewr\",\"plan\":\"${PLAN}\",\"snapshot_id\":\"${SNAP_ID}\",
       \"label\":\"macos-e0-l2\",\"tags\":[\"harness\",\"e0\"],
       \"enable_ipv6\":false,\"backups\":\"disabled\"}"
```

逐项回答用户的问题：

| 问题 | 答案 | 标签 | 依据 |
|---|---|---|---|
| **接受什么格式** | **解压后的 raw。** 官方说明快照可以从 RAW 镜像 URL 创建；`vultr-cli` 的 `snapshot create-url` 描述为"从外部 URL 导入磁盘镜像" | `KNOWN` | <https://docs.vultr.com/product-overviews/snapshots>、<https://docs.vultr.com/reference/vultr-cli/snapshot/create-url> |
| **接受压缩吗** | **按现有公开证据：不要压缩。** Fedora CoreOS 的 Vultr 开通文档里，取镜像那一步显式带 `--decompress`，上传的是 `.raw` 本体，然后才 `vultr-cli snapshot create-url -u <URL>` | `INFERRED`（没有任何文档说它接受 `.gz`/`.xz`，而有一个权威第三方流程明确先解压） | <https://docs.fedoraproject.org/en-US/fedora-coreos/provisioning-vultr/> |
| **有没有体积上限** | **没有找到任何公开的上限数字。** ISO 的 10 GB 是 ISO 那条通道的限制，不适用于这里 | `BLOCKED` | 记为 D-003 |
| **`uefi` 字段的语义** | 声明这块镜像要以 UEFI 方式引导。它的存在本身就是 Vultr 支持 UEFI 的直接证据 | `KNOWN` 对于字段存在与类型；`INFERRED` 对于"置 `true` 后平台确实用 OVMF 一类固件引导" | `govultr/snapshot.go`；`80` 第 1.5 节 |
| **产物能否直接 `snapshot_id` 部署** | **能。** `InstanceCreateReq` 有 `snapshot_id` 字段，FCOS 流程就是这么用的（`vultr-cli instance create --snapshot <ID>`） | `KNOWN` | <https://github.com/vultr/govultr/blob/master/instance.go>、FCOS 文档同上 |

**三条伴随事实，都影响设计**：

1. **快照只能恢复到"等于或大于源盘"的盘。** `KNOWN`，官方支持文档两处都这么写，并补充说若目标盘只有单个分区，平台会自动把它扩展到占满可用空间（转述自 <https://docs.vultr.com/support/products/compute/can-i-downsize-a-vultr-instance-using-a-snapshot> 与 <https://docs.vultr.com/how-to-clone-a-vultr-cloud-compute-instance>）。
   - 后果一：**我们发布的 raw 的虚拟容量，就是我们能选的最小机型的盘容量下限。** 这是第 4.6 节要做瘦镜像的首要理由，比省带宽重要得多。
   - 后果二：那个"自动扩展单分区"的逻辑对 macOS **不适用**，我们的盘是 ESP + rescue + APFS 容器三个分区，而且 APFS 不是平台认识的文件系统。扩容必须自己做（第 4.6 节）。**同时这也是一处风险**：平台若无条件对导入镜像跑扩容逻辑，可能动到我们的 GPT。记为 D-006。
2. **恢复/用快照开机比常规操作多花 10 到 15 分钟。** `KNOWN`（转述自 <https://docs.vultr.com/products/orchestration/snapshots/management/restore>）。这要进 harness 的超时设定。
3. **快照按压缩后体积计费，公开价目为每 GB 每月 0.05 美元。** `KNOWN`（转述自 <https://docs.vultr.com/products/orchestration/snapshots/faq>）。一份 40 GB 的 macOS golden 压缩后若按 20 GB 计，约 1 美元/月。`80` 第 3.4 节的快照 GC 规则因此仍然必要，但成本不构成障碍。

#### 3.1.3 `POST /v2/snapshots`：从运行中实例建快照

`KNOWN`（`govultr/snapshot.go`，`80` 第 1.2 节）。请求体 `{"instance_id": "...", "description": "..."}`。

这就是用户说的"从已有磁盘创建镜像"。它与 3.1.2 的关系是**互补而非替代**：

- 3.1.2 解决"**把外面的盘搬进来**"。
- 3.1.3 解决"**把这台机器现在的状态存下来**"，是 `80` 第 2.4.3 节 golden snapshot 与 2.4.4 节 `restore` 回路的基础。
- 两者产出的是同一种对象（`snapshot_id`），所以一旦用 3.1.2 把 macOS 搬上去一次，之后的全部迭代都可以只用 3.1.3 + `restore`，再也不需要重传几十 GB。

**这条路也是第 5.4 节 R5 层取证的唯一手段**：一台黑屏实例，先 `halt` 再 `POST /v2/snapshots` 把盘存下来，然后才允许执行抹盘类恢复。否则现场就永久丢了。

#### 3.1.4 Block Storage 能不能当系统盘

**能，但有机型前提。** 这是本轮查出来的、`80` 第 2.5 节没有记录的能力。

`KNOWN`（`govultr/block_storage.go`，<https://github.com/vultr/govultr/blob/master/block_storage.go>）：`BlockStorage` 对象带 `bootable` 布尔字段；`BlockStorageCreate` 请求体除 `region`/`size_gb`/`label`/`block_type` 外，还有 `snapshot_id`、`os_id`、`bootable` 三个字段。即**API 层面可以直接创建一块"可引导、内容来自某个快照或某个原厂 OS"的卷**。

`KNOWN`（文档侧）：VX1 机型的开通界面里有"Bootable Block Volume: 从 Vultr Block Storage 引导"这一项，可以选已有的可引导卷或新建一个（转述自 <https://docs.vultr.com/products/compute/vx1-cloud-compute/provisioning>）；克隆文档说明从 Block Storage 快照克隆出来的卷是独立的 `high_perf` 卷、标记为 bootable、**可直接作为新 VX1 实例的引导设备**，并要求克隆卷的尺寸不小于快照（转述自 <https://docs.vultr.com/products/cloud-storage/block-storage/block-storage-snapshot/clone-volume>）。产品概览页也写了可以直接从卷引导（转述自 <https://docs.vultr.com/product-overviews/block-storage>）。

```bash
# 建卷（普通数据卷）
BLK_ID=$(curl -s -X POST "https://api.vultr.com/v2/blocks" -H "$VH" -H "$VJ" \
  -d '{"region":"ewr","size_gb":64,"label":"macos-rescue","block_type":"storage_opt"}' \
  | jq -r '.block.id')

# 热挂 / 热卸
curl -s -X POST "https://api.vultr.com/v2/blocks/${BLK_ID}/attach" -H "$VH" -H "$VJ" \
  -d "{\"instance_id\":\"${INST_ID}\",\"live\":true}"
curl -s -X POST "https://api.vultr.com/v2/blocks/${BLK_ID}/detach" -H "$VH" -H "$VJ" -d '{"live":true}'

# 卷快照与"克隆成可引导卷"
curl -s -X POST "https://api.vultr.com/v2/blocks/snapshots" -H "$VH" -H "$VJ" \
  -d "{\"block_id\":\"${BLK_ID}\",\"description\":\"rescue r1\"}"
curl -s "https://api.vultr.com/v2/blocks/snapshots" -H "$VH" | jq '.snapshots[]|{id,state,size}'
```

**为什么它仍然不是我们的主路径**，三条理由：

1. **机型绑定。** 可引导卷的文档全部挂在 VX1 下。VX1 的计费口径与常规 Cloud Compute 不同（`80` 第 1.6 节记录 VX1 按实际月小时数计费、不封顶在 672 小时）。把 L2 从常规 Cloud Compute 换成 VX1，会同时改变成本模型和设备模型，而设备模型正是 `80` 的 H-001/H-003 要测的东西。
2. **第 2.7 节那条厂商观察**：部分地区的实例不能从数据盘启动。`bootable` 卷是另一套机制，不等于数据盘，但在未实测前不能假定它在所有地区可用。
3. **它不解决"把几十 GB 搬上去"这件事**。`BlockStorageCreate` 的 `snapshot_id` 指的是 Block Storage 自己的快照，源头还是得先有一块卷或一个实例快照。

**结论：Block Storage 在本文的角色是"第二块盘"，不是系统盘。** 它承载 `80` 第 2.5 节路径 B 的 payload 投放，以及第 5.4 节 R2 层的证据回传。可引导卷作为 L2 架构的备选路线登记为 D-007。

### 3.2 第五条路：`ipxe_chain_url`

**`80` 第 1 节完整漏掉了这条，而它是"无控制台环境里引导任意系统"的最强手段。**

`KNOWN`：`InstanceCreateReq` 含字段 `ipxe_chain_url`（<https://github.com/vultr/govultr/blob/master/instance.go>）。官方 iPXE 功能文档声明 Vultr 在 Cloud Compute、High Frequency Compute、Dedicated Cloud 与 Bare Metal 上支持 iPXE，而 iPXE 是用来从远端镜像与脚本引导的开源网络引导固件（转述自 <https://docs.vultr.com/ipxe-boot-feature>）。

`KNOWN`（第三方权威用例）：netboot.xyz 的 Vultr 页面给出两种用法。其中 iPXE 链的用法是：新建实例、OS 选 `Custom`、在 Virtual ISO 区选 `iPXE`、把 chain URL 设成他们的地址、下单；实例几分钟内启动，随后**有五分钟时间打开控制台从菜单里选项**。同一页还说明 Bare Metal 的 iPXE 选项在 Server Type 区的 iPXE 标签页里，并提醒 Bare Metal 要用 Legacy (PCBIOS) 镜像，因为它当时不支持 EFI（转述自 <https://netboot.xyz/docs/kb/providers/vultr>）。

`KNOWN`：Alpine 官方 netboot 服务器提供 `https://boot.alpinelinux.org/boot.ipxe` 作为默认引导脚本，并明确说一些云厂商支持加载自定义 iPXE 脚本或 payload 来装系统、可以从他们的 iPXE 引导器链载；同时提示用别的 iPXE 引导器会关掉镜像校验（转述自 <https://boot.alpinelinux.org/>）。

**它给了我们什么**：

- 一条**不占 ISO 槽位、不受 10 GB 限制、不需要原系统**的 rescueOS 引导路径。我们自己托管一份 iPXE 脚本，内容是"取 Alpine 的 `vmlinuz-lts` + `initramfs-lts`，内核参数带 `modloop=` 与 `apkovl=`，`boot`"，实例一开机就直接进我们配好的 Alpine，SSH 公钥已经在 `apkovl` 里。
- netboot.xyz 那条"有五分钟时间打开控制台选菜单"的说明同时暗示：**菜单是给人用的，脚本可以是非交互的。** 我们的脚本不出菜单，直接 `boot`，所以五分钟窗口对我们无意义。

**它的两个限制，必须写清楚**：

1. **`ipxe_chain_url` 只在 `InstanceCreateReq` 里，不在 `InstanceUpdateReq` 里**（`KNOWN`，`govultr/instance.go` 两个结构体的字段对比）。即它是**创建时一次性选项，不能对一台已有实例追加**。
   - 后果：它能用于**投放**（第 4.3 节），**不能用于救一台已经砖了的实例**。救砖只能用 ISO attach 或平台重装（第 5.4 节）。
2. iPXE 的链载会关掉 Alpine 的镜像签名校验（来源同上）。我们自己托管脚本与镜像并自己做 SHA-256 校验，这一点可以接受，但要在脚本里把校验补回来（第 4.3 节）。

### 3.3 五条路对照表与最终选择

| 路 | 端点 | 体积上限 | 占 ISO 槽位 | 能否全自动 | 适用于已有实例 | 我们用它做什么 |
|---|---|---|---|---|---|---|
| ISO from URL | `POST /v2/iso` | **10 GB** `KNOWN` | **是（2 个）** | 是 | 是（attach 会重启） | 1.5 GB 安装介质；R3 层救援 |
| 公共 ISO 库 | `GET /v2/iso-public` + attach | 不适用 | **否** `INFERRED` | 挂载能，**用不了**（要人看控制台） | 是 | R3 层的人工兜底 |
| **Snapshot from URL** | `POST /v2/snapshots/create-from-url` | **未查清** `BLOCKED` | 否 | **是** | 否（只能开新实例） | **主路径：投放 macOS 系统盘** |
| Snapshot from instance | `POST /v2/snapshots` | 受源盘约束 | 否 | 是 | 是 | golden 迭代；黑屏取证 |
| Bootable Block Storage | `POST /v2/blocks`（`bootable`） | 卷尺寸 | 否 | 是 | 否（要新 VX1 实例） | 备选架构 D-007 |
| **iPXE chain** | `POST /v2/instances`（`ipxe_chain_url`） | 不适用 | 否 | **是** | **否** | **主路径的 rescueOS 入口** |

**一句话结论：把几十 GB 的 macOS 系统盘搞上去，只有 `POST /v2/snapshots/create-from-url` 这一条路。** 其余四条各有各的用途，但没有一条能承载这个体积且全自动。

---

## 4. 投放机制设计

### 4.1 对用户初步想法的裁决

用户给的四步：

> 1. 用 Vultr API 开一台装着普通 Linux 的实例（有 SSH）
> 2. 在它上面引导进 Alpine live（内存里跑），使系统盘空出来
> 3. 把我们预制的 macOS raw 磁盘镜像流式写进系统盘
> 4. 重启，OpenCore 接管

逐条裁决：

| 步 | 裁决 | 理由 |
|---|---|---|
| 1 | **可行但多余**。保留为备用路径 D3 | `ipxe_chain_url` 让新实例可以直接开机进 Alpine，不需要先装一个 Linux 再切（第 3.2 节）。省掉一次装机、一次重启、以及"原系统的 ESP 在哪、是不是软 RAID"这一整类不确定性 |
| 2 | **机制正确**。Alpine 跑在内存里确实能把系统盘整块空出来 | 第 2.4 节 |
| 3 | **机制正确，但有三处必须加固**：写入顺序（前 1 MiB 留到最后）、分段校验、写完修 GPT 备份表 | 第 4.5 节 |
| 4 | **不成立，缺一步**。重启之后 OpenCore 要能接管，前提是**我们写进去的那块盘里本来就有一个能启动的 macOS**。所以第 3 步写的不是"安装介质"，而是"一块已经装好系统的盘"，这块盘必须先在别处造出来 | 第 4.2 节与第 7 节的依赖关系 |

**最关键的修正是第 4 步暴露的依赖**：这个流程本身**不安装 macOS，它只搬运一块装好的盘**。那块盘从哪来？

- 若 L1（本地 KVM）可用 → 在 L1 装好，`71` 第 8.2 节已经给了全套命令。
- 若 L1 不可用 → 必须在云上装一次，而云上装系统必须人工看网页控制台（`80` 第 2.4.3 节步骤 3）。这是整个方案里**唯一无法消除的人工环节**，也是第 7 节必须认真对待的原因。

**所以投放不是一条路径，是三条，按优先级排**：

```text
D1  本地装好 → 转 raw → 托管 → create-from-url → 带 snapshot_id 开实例
    ├─ 前提：L1 可用（第 7 节）
    ├─ 人工环节：0
    └─ 这是主路径

D2  iPXE chain → Alpine(RAM) → 流式写盘 → 重启
    ├─ 前提：有一块可写的 raw 源（同 D1），但不想等平台做快照，或镜像超出快照通道的未知上限
    ├─ 人工环节：0
    └─ 这是 D1 的替代与一切"改盘"操作的通用底座

D3  开一台 Linux 实例 → ESP 加引导项 → Alpine(RAM) → 流式写盘 → 重启
    ├─ 前提：ipxe_chain_url 不可用或被平台拒绝时
    ├─ 人工环节：0
    └─ reinstall 的原始形态，作为 D2 的降级

D0  ISO 装一次（人工看网页控制台）→ POST /v2/snapshots 存成 golden
    ├─ 前提：L1 完全不可用
    ├─ 人工环节：1 次，约 1 小时
    └─ 只做一次，之后回到 D1/D2 的全自动回路
```

### 4.2 主路径 D1：`create-from-url` 直接部署

#### 4.2.1 完整序列

```bash
#!/usr/bin/env bash
# scripts/deploy-l2-d1.sh  —— 把一块装好 macOS 的 raw 盘变成一台 Vultr 实例
set -euo pipefail
: "${VULTR_API_KEY:?}"
VH="Authorization: Bearer ${VULTR_API_KEY}"
VJ="Content-Type: application/json"

RAW="${1:?macos-golden.raw}"            # 本地 raw 路径
PUB_URL="${2:?https://.../macos-golden.raw}"   # 已托管的公开 URL
REGION="${REGION:-ewr}"

# ---- 0. 本地指纹。这是之后一切校验的基准 ----
RAW_BYTES=$(stat -c%s "$RAW")
RAW_SHA=$(sha256sum "$RAW" | awk '{print $1}')
echo "raw bytes=${RAW_BYTES} sha256=${RAW_SHA}"

# ---- 1. 选机型：盘必须 >= 镜像虚拟容量（3.1.2 伴随事实 1）----
NEED_GB=$(( (RAW_BYTES + 1073741823) / 1073741824 ))
PLAN=$(curl -s "https://api.vultr.com/v2/plans?type=vc2&per_page=100" -H "$VH" \
  | jq -r --argjson need "$NEED_GB" \
      '[.plans[] | select(.vcpu_count>=4 and .ram>=8192 and .disk>=$need)]
       | sort_by(.monthly_cost)[0] | .id')
[ -n "$PLAN" ] && [ "$PLAN" != null ] || { echo "no plan with disk >= ${NEED_GB}GB"; exit 1; }
echo "plan=${PLAN} (needs disk >= ${NEED_GB} GB)"

# ---- 2. 导入成快照 ----
SNAP_ID=$(curl -s -X POST "https://api.vultr.com/v2/snapshots/create-from-url" -H "$VH" -H "$VJ" \
  -d "{\"url\":\"${PUB_URL}\",\"description\":\"macos-26.7.2-25G325 golden ${RAW_SHA:0:12}\",\"uefi\":true}" \
  | jq -r '.snapshot.id')
echo "snapshot=${SNAP_ID}"

# 快照创建最长约 30 分钟（80 第 1.2 节）。给 60 分钟上限
for i in $(seq 1 120); do
  S=$(curl -s "https://api.vultr.com/v2/snapshots/${SNAP_ID}" -H "$VH" | jq -r '.snapshot.status')
  [ "$S" = complete ] && break
  [ "$S" = error ] && { echo "snapshot import failed"; exit 1; }
  sleep 30
done

# ---- 3. 体积核对。平台的 size 应与本地 raw 一致（这是导入完整性的唯一可得信号）----
curl -s "https://api.vultr.com/v2/snapshots/${SNAP_ID}" -H "$VH" \
  | jq --argjson want "$RAW_BYTES" '.snapshot|{status,size,compressed_size,
        size_matches_local: (.size == $want)}'

# ---- 4. 部署 ----
INST_JSON=$(curl -s -X POST "https://api.vultr.com/v2/instances" -H "$VH" -H "$VJ" \
  -d "{\"region\":\"${REGION}\",\"plan\":\"${PLAN}\",\"snapshot_id\":\"${SNAP_ID}\",
       \"label\":\"macos-e0-l2\",\"tags\":[\"harness\",\"e0\"],
       \"enable_ipv6\":false,\"backups\":\"disabled\"}")
INST_ID=$(jq -r '.instance.id' <<<"$INST_JSON")
# default_password 只在创建响应里出现（80 第 1.1 节），立刻落盘
jq -r '.instance|{id,default_password}' <<<"$INST_JSON" > "creds-${INST_ID}.json"
chmod 600 "creds-${INST_ID}.json"

# ---- 5. 等就绪。平台的 active 不等于 guest 就绪（80 第 2.4.4 节）----
IP=""
for i in $(seq 1 120); do
  IP=$(curl -s "https://api.vultr.com/v2/instances/${INST_ID}" -H "$VH" | jq -r '.instance.main_ip')
  [ "$IP" != "0.0.0.0" ] && [ -n "$IP" ] && break
  sleep 15
done
echo "ip=${IP}"
for i in $(seq 1 90); do
  ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ConnectTimeout=5 \
      -i "$HARNESS_KEY" "harness@${IP}" 'echo READY' && break
  sleep 20
done
```

#### 4.2.2 耗时预算

| 步 | 量级 | 标签 |
|---|---|---|
| 本地 qcow2 → raw 转换 | 与盘实占同量级，分钟级 | `INFERRED` |
| 上传到对象存储 | 取决于本地上行带宽，**可能是整个流程最慢的一步** | `INFERRED` |
| 平台拉取 + 建快照 | 最长约 30 分钟 | `KNOWN`（`80` 第 1.2 节） |
| 用快照开实例 | 常规操作 + 10 到 15 分钟 | `KNOWN`（<https://docs.vultr.com/products/orchestration/snapshots/management/restore>） |
| macOS 首次启动到 SSH | 未知，按数分钟预留 | `BLOCKED` |

**关键结论：这条路径的全部慢步骤都是一次性的。** 快照建好之后，每次实验只需 `POST /v2/instances/{id}/restore`（`80` 第 2.4.4 节），不再重传。

#### 4.2.3 托管端点

两条路，都要公开可读：

- **Vultr Object Storage**（S3 兼容）。FCOS 的 Vultr 流程就是把 raw 以 public ACL 放进桶里再给 URL（转述自 <https://docs.fedoraproject.org/en-US/fedora-coreos/provisioning-vultr/>）。优点是与平台同网，拉取快且出站费用可能更低（`INFERRED`，需核对计费口径）。
- **一台长驻小实例上的 HTTP 服务**，即 `80` 第 1.2 节约束 1 已经要求的那个端点。

**两条都必须考虑"公开可读意味着任何人可下载"。** macOS 系统盘镜像含 Apple 的二进制，公开托管是版权问题，也与仓库 `.gitignore` 顶部的发布边界冲突。因此：

**强制要求**：托管 URL 必须是**带签名的临时 URL**（预签名 GET，有效期按分钟计），或**按 IP 白名单限制到 Vultr 的拉取网段**。只有"平台能拉到"这一个需求，没有"公众能拉到"这个需求。`INFERRED`：`create-from-url` 是否接受带 query string 的预签名 URL 未验证，记为 D-008。**这是一个在花钱之前就必须查清的问题**，因为它决定我们能不能合法地走 D1。

### 4.3 主路径 D2：iPXE → Alpine → 流式写盘

当 D1 不可用（快照通道有未知上限、或预签名 URL 不被接受）时，这条路径只需要我们的 HTTP 服务能被**我们自己的实例**访问，而不需要被平台的导入服务访问。那就可以用普通的鉴权（Bearer token、mTLS），版权与保密问题随之消失。**这是 D2 相对 D1 的最大优势，不只是备用。**

#### 4.3.1 托管的三件东西

```text
https://assets.example.net/rescue/
├── boot.ipxe                 iPXE 脚本，非交互
├── vmlinuz-lts               Alpine netboot 内核（从官方镜像站取，记 SHA-256）
├── initramfs-lts             Alpine netboot initramfs
├── modloop-lts               Alpine 内核模块 squashfs
└── rescue.apkovl.tar.gz      我们的 Alpine 配置包（SSH 公钥 + 脚本）
```

`boot.ipxe`（可直接照抄，`INFERRED`：语法按 iPXE 脚本约定，未在 Vultr 上实测）：

```ipxe
#!ipxe
set base https://assets.example.net/rescue
set opts modloop=${base}/modloop-lts apkovl=${base}/rescue.apkovl.tar.gz
set opts ${opts} alpine_repo=https://dl-cdn.alpinelinux.org/alpine/v3.24/main
set opts ${opts} console=ttyS0,115200n8 console=tty0 ip=dhcp
kernel ${base}/vmlinuz-lts ${opts}
initrd ${base}/initramfs-lts
boot
```

`rescue.apkovl.tar.gz` 的内容（Alpine 的 overlay 结构，`INFERRED`，见 D-005）：

```text
etc/
├── ssh/sshd_config                 PermitRootLogin prohibit-password / PasswordAuthentication no
├── runlevels/default/sshd  → 软链到 /etc/init.d/sshd
├── runlevels/default/networking
├── local.d/10-rescue.start         开机自动跑我们的投放脚本（见 4.8）
├── runlevels/default/local
└── apk/world                       需要的包清单：openssh zstd pv sgdisk e2fsprogs
root/.ssh/authorized_keys            harness 公钥
usr/local/bin/deploy-macos.sh        投放脚本
usr/local/bin/verify-disk.sh         分段校验脚本
```

**`apkovl` 里不放任何密码。** SSH 只许公钥。`reinstall` 的 README 里有一条很值得抄的告警：如果用户在 Alpine Live 里直接打包硬盘镜像，而镜像里带了 netboot initrd，明文密码就会泄漏。我们从一开始就不引入明文密码，这类问题就不存在。

#### 4.3.2 创建实例并进 Alpine

```bash
INST_JSON=$(curl -s -X POST "https://api.vultr.com/v2/instances" -H "$VH" -H "$VJ" \
  -d "{\"region\":\"${REGION}\",\"plan\":\"${PLAN}\",
       \"ipxe_chain_url\":\"https://assets.example.net/rescue/boot.ipxe\",
       \"label\":\"macos-deploy\",\"tags\":[\"harness\",\"deploy\"],
       \"enable_ipv6\":false,\"backups\":\"disabled\"}")
INST_ID=$(jq -r '.instance.id' <<<"$INST_JSON")
```

`INFERRED`：`ipxe_chain_url` 是否需要同时指定某个"Custom"类型的 `os_id` 未确证。netboot.xyz 的门户流程是"OS 选 Custom，再在 Virtual ISO 区选 iPXE"（来源同第 3.2 节），暗示 API 侧可能也要给 `os_id`。查清方法：先只给 `ipxe_chain_url` 试一次，报 `400` 则加 `os_id`，候选值从 `GET /v2/os` 里找名字含 `Custom` 的那一项。记为 **D-009**。

就绪判定：SSH 到 Alpine。**在这一步必须做空跑演练**（抄 `reinstall` 的 `--hold 1`）：

```bash
ssh -i "$HARNESS_KEY" "root@${IP}" 'set -e
  uname -a; free -m
  lsblk -o NAME,SIZE,TYPE,FSTYPE,LABEL
  # 1. 主盘是单块盘还是 md/dm？这是 D-001
  lsblk -rn -o NAME,TYPE | awk "\$2==\"disk\"{print \$1}"
  cat /proc/mdstat 2>/dev/null || echo "no md"
  # 2. 能不能拉到我们的镜像源（只取前 1 MiB 验证鉴权与带宽）
  curl -sS -r 0-1048575 -o /dev/null -w "first1M %{speed_download} B/s\n" \
       -H "Authorization: Bearer ${ASSET_TOKEN}" "$IMG_URL"
  # 3. 盘容量够不够
  blockdev --getsize64 /dev/vda 2>/dev/null || blockdev --getsize64 /dev/sda'
```

**三条检查全绿才允许进入破坏性步骤。** 任何一条红，销毁实例重来，代价是 1 小时计费（`80` 第 1.6 节）。

### 4.4 备用路径 D3：reinstall 的原始形态

仅在 D-009 判定 `ipxe_chain_url` 不可用时启用。流程就是第 2.2 节那张图，差异只在最后一步写的是 macOS 盘而不是 Linux：

```bash
# 1. 开一台普通 Debian 实例（os_id 从 GET /v2/os 查）
# 2. SSH 进去，照 reinstall 的 add_efi_entry_in_linux 机制挂钩
ssh root@$IP 'set -e
  apt-get update && apt-get install -y efibootmgr findmnt curl
  ESP=$(findmnt -n -o TARGET -t vfat | head -1)
  mkdir -p "$ESP/EFI/rescue"
  curl -fsSL -o "$ESP/EFI/rescue/grubx64.efi" "$GRUB_URL"
  curl -fsSL -o "$ESP/rescue-vmlinuz"  "$BASE/vmlinuz-lts"
  curl -fsSL -o "$ESP/rescue-initramfs" "$BASE/initramfs-lts"
  cat > "$ESP/EFI/rescue/grub.cfg" <<EOF
set timeout=1
menuentry "rescue" {
  linux /rescue-vmlinuz modloop=$BASE/modloop-lts apkovl=$BASE/rescue.apkovl.tar.gz ip=dhcp console=ttyS0,115200n8 console=tty0
  initrd /rescue-initramfs
}
EOF
  DEV=$(findmnt -T "$ESP" -no SOURCE)
  DISK=$(lsblk -no pkname "$DEV"); PART=$(cat /sys/class/block/$(basename $DEV)/partition)
  efibootmgr --create-only --disk "/dev/$DISK" --part "$PART" \
             --label "rescue" --loader "\\EFI\\rescue\\grubx64.efi"
  ID=$(efibootmgr | awk "/rescue/{gsub(/[^0-9]/,\"\",\$1); print \$1; exit}")
  efibootmgr --bootnext "$ID"     # 一次性，失败自动回原系统
  reboot'
```

**`--create-only` + `--bootnext` 两个开关缺一不可。** 前者保证不动 `BootOrder`（即不改变"失败后回哪"），后者保证这次切换是一次性的。抄这段代码时不要把它们简化成 `efibootmgr --create`。

### 4.5 几十 GB 怎么传：可行性、量级、校验

#### 4.5.1 流式直写可行

`curl | zstd -d | dd` 可行，这是 `reinstall` 的 `dd_raw_with_extract()` 已在大量厂商上使用的形态（第 2.5 节）。三处必须改进：

```bash
#!/bin/sh
# /usr/local/bin/deploy-macos.sh  —— 在 Alpine(RAM) 里执行
set -eu
IMG_URL="${IMG_URL:?}"          # 带鉴权的镜像 URL，内容为 .raw.zst
XDA="${XDA:?}"                  # 目标盘，例如 /dev/vda
TOK="${ASSET_TOKEN:?}"

apk add --no-cache curl zstd pv sgdisk coreutils

DISK_BYTES=$(blockdev --getsize64 "$XDA")
# 镜像的解压后体积从分段清单的 #total_bytes 取，不要靠 HTTP 头猜
curl -fsS -H "Authorization: Bearer $TOK" "$IMG_URL.chunks.tsv" -o /chunks.tsv
IMG_BYTES=$(awk -F'\t' '$1=="#total_bytes"{print $2}' /chunks.tsv)
[ -n "$IMG_BYTES" ] || { echo "no #total_bytes in chunk manifest"; exit 1; }
[ "$IMG_BYTES" -le "$DISK_BYTES" ] || { echo "image larger than disk"; exit 1; }
echo "image=${IMG_BYTES} disk=${DISK_BYTES}"

# ---- 加固 1：先把镜像头 1 MiB 单独取到内存，最后再写 ----
curl -fsS -H "Authorization: Bearer $TOK" -r 0-1048575 "$IMG_URL.head" -o /first-1M
[ "$(stat -c%s /first-1M)" = 1048576 ] || { echo "bad head blob"; exit 1; }

# ---- 主体：跳过头 1 MiB，流式解压直写 ----
# 服务端提供两个对象：<img>.head（未压缩的前 1 MiB）与 <img>.body.zst（1 MiB 之后的压缩流）
curl -fsS --retry 5 --retry-all-errors -H "Authorization: Bearer $TOK" "$IMG_URL.body.zst" \
  | zstd -d -c \
  | pv -f -s "$((IMG_BYTES - 1048576))" \
  | dd of="$XDA" bs=1M seek=1 iflag=fullblock oflag=direct conv=notrunc status=none
sync

# ---- 加固 2：分段校验（见 4.5.3）----
/usr/local/bin/verify-disk.sh "$XDA" "$IMG_URL" "$TOK" || { echo "VERIFY FAILED"; exit 1; }

# ---- 加固 3：翻转指针。只有校验过了才写盘头 ----
dd if=/first-1M of="$XDA" bs=1M count=1 conv=notrunc oflag=direct status=none
sync

# ---- 加固 4：把 GPT 备份表挪到真实盘尾（瘦镜像必然需要）----
sgdisk -e "$XDA"
sgdisk -v "$XDA"
partprobe "$XDA" || true
sgdisk -p "$XDA"
```

**为什么把镜像拆成 `.head` 与 `.body.zst` 两个对象**：第 2.5 节的 `dd_qcow()` 能做到"先读前 1 MiB 到内存"是因为它有一个可随机访问的 nbd 设备。我们是单向 HTTP 流，没法先读头再从头开始流。拆成两个对象是最简单的等价做法，拆分在构建期完成，零运行期成本。

`oflag=direct` 的作用是绕过 page cache，避免"`dd` 返回了但数据还在内存里"的假完成；`sync` 是第二道保险。

#### 4.5.2 带宽与耗时量级

**本节全部是算术，不是平台承诺。** 实际吞吐必须在第 4.3.2 节的空跑演练里测出来再代入。

| 镜像实体积 | @50 MB/s | @100 MB/s | @200 MB/s |
|---:|---:|---:|---:|
| 8 GB | 2.7 min | 1.4 min | 0.7 min |
| 20 GB | 6.8 min | 3.4 min | 1.7 min |
| 40 GB | 13.7 min | 6.8 min | 3.4 min |
| 128 GB | 43.7 min | 21.8 min | 10.9 min |

zstd 把 macOS 系统盘压到 40% 到 50% 是合理预期（`INFERRED`），所以网络侧传输量约为实体积的一半，而解压后的写入量是全量。瓶颈通常在网络而不是在盘。

**出站计费提醒**：镜像从我们的托管端点流出要计费（`80` 第 1.6 节）。把托管端点放在同一家、同一区域可以压低这笔成本（`INFERRED`，口径需核对）。

#### 4.5.3 校验怎么做

**流式写完无法整盘回读比对**这个前提是错的。在 Alpine 里**可以**整盘回读：盘是本地 NVMe/VirtIO，读几十 GB 是分钟级，而且不耗网络。所以校验分两层：

**层 1：分段清单（构建期生成，必须有）**

```bash
# 构建期：按 64 MiB 切块算 SHA-256，生成清单
# scripts/mk-chunk-manifest.sh <raw> <out.tsv>
set -euo pipefail
RAW="${1:?}"; OUT="${2:?}"
CHUNK=$((64*1024*1024))
BYTES=$(stat -c%s "$RAW")
N=$(( (BYTES + CHUNK - 1) / CHUNK ))
: > "$OUT"
printf '#total_bytes\t%d\n#chunk_bytes\t%d\n' "$BYTES" "$CHUNK" >> "$OUT"
for i in $(seq 0 $((N-1))); do
  # 最后一块通常是不满的。必须记下【实际字节数】，否则回读时会把盘上
  # 紧随其后的旧数据一起算进哈希，导致最后一块永远不匹配。
  LEN=$CHUNK
  [ "$i" -eq "$((N-1))" ] && LEN=$(( BYTES - i * CHUNK ))
  H=$(dd if="$RAW" bs=64M skip="$i" count=1 status=none \
      | head -c "$LEN" | sha256sum | awk '{print $1}')
  printf '%d\t%d\t%s\n' "$i" "$LEN" "$H" >> "$OUT"
done
sha256sum "$OUT"
```

**层 2：写后回读（Alpine 内执行）**

```bash
#!/bin/sh
# /usr/local/bin/verify-disk.sh <dev> <img-url> <token>
set -eu
DEV="${1:?}"; URL="${2:?}"; TOK="${3:?}"
curl -fsS -H "Authorization: Bearer $TOK" "$URL.chunks.tsv" -o /chunks.tsv
BAD=0; OK=0
while IFS="$(printf '\t')" read -r idx size want; do
  case "$idx" in \#*|'') continue ;; esac
  # head -c "$size" 让最后一块只取有效字节，见构建期脚本里的同一条注释
  got=$(dd if="$DEV" bs=64M skip="$idx" count=1 iflag=direct status=none \
        | head -c "$size" | sha256sum | awk '{print $1}')
  if [ "$got" != "$want" ]; then
    echo "CHUNK $idx MISMATCH size=$size want=$want got=$got"
    BAD=$((BAD+1))
  else
    OK=$((OK+1))
  fi
done < /chunks.tsv
echo "ok_chunks=$OK bad_chunks=$BAD"
[ "$BAD" -eq 0 ]
```

**三条设计理由**：

1. **分段而不是整盘单哈希**：整盘单哈希只能告诉你"坏了"，分段能告诉你"第 417 块坏了"，于是可以只重传那一块（`curl -r`）而不是重来一遍几十 GB。
2. **最后一块要特殊处理**：盘比镜像大时，最后一个 chunk 之后的内容是盘上的旧数据，不参与校验。清单里的 `#total_bytes` 用来算出哪些块是有效块。
3. **校验在"翻转指针"之前**：这是第 4.5.1 节脚本里顺序的全部意义。校验失败时盘头还是旧的，实例重启回到旧系统，我们还有 SSH。**这条顺序不许调整。**

### 4.6 镜像要多大：瘦镜像 + 首启自扩展

#### 4.6.1 为什么必须做瘦镜像

不是为了省带宽，而是因为第 3.1.2 节的伴随事实 1：**快照只能恢复到等于或大于源盘的盘**。镜像的虚拟容量直接决定了我们能选的最小机型。一个 128 GB 的 raw 把我们钉死在大盘机型上，而实验机本来按 `80` 第 1.6 节只需要 4 vCPU / 8 GB RAM。

#### 4.6.2 能不能做"最小可启动 + 首启自扩展"

**能，分三件事，各自的可行性不同。**

| 件 | 做法 | 标签 |
|---|---|---|
| 把 APFS 容器缩到接近实占 | 在 L1 的 macOS guest 内 `diskutil apfs resizeContainer disk0s3 <目标字节>` | `INFERRED`，命令形态来自 `diskutil` 手册（<https://keith.github.io/xcode-man-pages/diskutil.8.html>），但缩容受 APFS 快照与 tidemark 影响，可能缩不到预期值 |
| 把 raw 截断到最后一个分区结束处 | `truncate -s <末分区结束+1>` + `sgdisk -e` 修备份表 | `KNOWN`（`sgdisk -e` 的语义是把 GPT 备份结构移到盘尾，来源 <https://manpages.debian.org/bookworm/gdisk/sgdisk.8.en.html>） |
| 首启把容器扩回整盘 | macOS 内 `diskutil apfs resizeContainer <物理存储> 0` | `KNOWN` 对于"0 表示扩满到下一个分区或分区表可用空间末尾"这一语义，来自 `diskutil` 手册（同上） |

**首启自扩展的落地形态**：一个只跑一次的 LaunchDaemon。

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>            <string>net.metal2vu.firstboot-expand</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/local/libexec/firstboot-expand.sh</string>
  </array>
  <key>RunAtLoad</key>        <true/>
  <key>StandardOutPath</key>  <string>/var/log/firstboot-expand.log</string>
  <key>StandardErrorPath</key><string>/var/log/firstboot-expand.log</string>
</dict>
</plist>
```

```bash
#!/bin/bash
# /usr/local/libexec/firstboot-expand.sh
set -euo pipefail
STAMP=/var/db/.metal2vu-expanded
[ -e "$STAMP" ] && exit 0

# 1. 找出根卷所在的 APFS 容器的物理存储分区
PHYS=$(diskutil info -plist / \
       | plutil -extract APFSPhysicalStores.0.APFSPhysicalStore raw -o - - 2>/dev/null \
       || true)
[ -n "$PHYS" ] || { echo "cannot resolve physical store"; exit 1; }
echo "physical store: $PHYS"

# 2. GPT 备份表应已由 Alpine 侧 sgdisk -e 修好。若没修，这一步会失败而不是损坏数据
diskutil list
# 3. 扩满。0 = 吃掉到下一个分区或分区表末尾之间的全部空间
diskutil apfs resizeContainer "$PHYS" 0

diskutil list
touch "$STAMP"
```

**两个必须注意的点**：

1. **GPT 修复要在 Linux 侧做，不要指望 macOS 做。** `sgdisk -e` 是一条确定的、非交互的命令；macOS 侧的等价物是 `diskutil repairDisk`，它交互且行为不如前者可预测。第 4.5.1 节的脚本已经在 Alpine 里做了这件事，macOS 首启只需要扩容器。
2. **瘦镜像的下限不是"实占"而是"实占 + APFS 元数据余量"。** 一个塞满到 99% 的 APFS 容器开机即出问题。建议目标容量 = 实占 × 1.3，且不小于 16 GB（`INFERRED`）。

#### 4.6.3 推荐尺寸

| 用途 | 虚拟容量 | 理由 |
|---|---:|---|
| 发布用瘦镜像（走 `create-from-url`） | **16 到 24 GB** | 落在最便宜的、盘 ≥25 GB 的常规机型上 |
| L1 的 golden qcow2 | 128 GB 稀疏 | 本地没有这个约束，留空间给实验 |
| 部署后扩展目标 | 整盘 | 由首启 LaunchDaemon 完成 |

### 4.7 是否绕开了 ISO 的 10 GB / 2 槽位限制

**是，完全绕开。这是本文最重要的结论之一，明确写出来。**

| 约束 | D1（`create-from-url`） | D2（iPXE + dd） | 原 ISO 方案 |
|---|---|---|---|
| 10 GB 单件上限 | **不适用**。快照通道没有公开上限（D-003） | **不适用**。流式写盘的上限是目标盘容量 | 适用，且 macOS 系统盘超限 2 到 4 倍 |
| 2 个槽位 | **占 0 个** | **占 0 个** | 占 1 到 2 个 |
| "一个实例同时只能挂一张 ISO"（`71` 第 8.3.1 节） | **不适用**。没有光驱概念 | **不适用** | 适用，这是 `71` 为什么必须把 OpenCore 与 BaseSystem 合并成一张镜像的原因 |
| 必须公开 URL | 适用（见第 4.2.3 节的签名 URL 要求） | **不适用**，可用带鉴权的私有端点 | 适用 |

**两个槽位因此被释放出来。** 新的槽位分配：

- 槽 0：**空着**。留给计划外的救援（第 5.4 节 R3）。
- 槽 1：**空着**，或放一张自制的 Alpine rescue ISO（见第 5.1 节的取舍）。

`71` 第 8.3.3 节的 hybrid ISO 配方（配方 A）在新方案下**降级为只在 D0 场景使用**，即"本地完全装不了、必须在云上人工装一次"。它仍然要保留在 `71` 里，但不再是 L2 的主交付形态。相应地，`71` 的 I-021（固件能否从 ISO9660/UDF 读出 `com.apple.recovery.boot/BaseSystem.dmg`）与 I-007（`DmgLoading = Any`）的优先级从"阻塞 L2"降为"仅阻塞 D0"。

### 4.8 完整可执行形态

把前面各节串成一条带门禁的流水线。**每一步都有一个"失败则回到上一个可观测状态"的保证**。

```text
阶段 A  构建（Windows + Linux 构建机，71 第 8 节）
  A1  造 EFI 树与 opencore.img                        [71 §8.2.1/8.2.2]
  A2  L1 安装 macOS 并武装                            [71 §8.2.4 + 80 §2.4.2 步骤 4/5]
  A3  装 firstboot-expand LaunchDaemon                [本文 §4.6.2]
  A4  装 rescue 分区与 ESP 双 BOOTX64                 [本文 §5.2/§5.3]
  A5  缩容器 → 转 raw → 截断 → sgdisk -e              [本文 §4.6.2]
  A6  拆成 .head / .body.zst / .chunks.tsv            [本文 §4.5]
  A7  托管并记 image-manifest.json                     [71 §8.5]
  门禁：A2 产出的 qcow2 必须在 L1 上重启三次都能 SSH 通，否则不进阶段 B

阶段 B  投放（harness）
  B1  空跑演练：开一台 iPXE→Alpine 实例，三条检查     [本文 §4.3.2]
       红 → 销毁，不进 B2
  B2  流式写盘（头留到最后）                           [本文 §4.5.1]
  B3  分段回读校验                                     [本文 §4.5.3]
       红 → 只重传坏块，再校验；仍红 → 保留实例、取证、人工介入
  B4  写盘头（翻转指针）+ sgdisk -e                     [本文 §4.5.1]
  B5  在 Alpine 里**先**确认 rescue 分区可引导          [本文 §5.3.3]
       红 → 不许重启。此时盘头已翻转，但 Alpine 还在内存里，仍可重写
  B6  reboot
  B7  等 SSH（上限 15 分钟）
       红 → 走第 5.4 节的 R 阶梯

阶段 C  固化
  C1  halt → POST /v2/snapshots 建 L2 golden            [本文 §3.1.3]
  C2  之后每次实验只 restore，不再重传                   [80 §2.4.4]
```

**B5 是整条流水线里最容易被省掉、也最不该省的一步。** 盘头翻转之后、重启之前，我们手里还有一个在内存里跑的、能写任意扇区的 Alpine。这是最后一次"免费修复"的机会。一旦重启，修复成本就跳到第 5.4 节的阶梯上去了。

---

## 5. rescueOS

### 5.1 持久形态：三个候选的取舍

问题：Alpine live 跑在内存里，重启就没了。macOS 一旦把引导搞坏，我们需要一个**不依赖网络选项、不依赖人工点击**的回路。

| 候选 | 持久性 | 能否全自动进入 | 占什么资源 | 评估 |
|---|---|---|---|---|
| **A. 纯内存（iPXE 每次重新拉）** | 无 | **否**。`ipxe_chain_url` 只能在创建实例时给（第 3.2 节限制 1） | 0 | **不能作为救砖形态**。只能用于投放 |
| **B. 系统盘内的独立 rescue 分区** | 有 | **是**，靠 ESP 内的引导对象交换（第 5.3 节） | 系统盘 1.5 到 2 GB | **选定** |
| C. 自制 Alpine rescue ISO 占一个槽位 | 有（在平台侧） | 是，`iso/attach` 是纯 API | 1 个 ISO 槽位 | **作为 B 的后备**，见第 5.4 节 R3 |
| D. 平台公共 ISO（Finnix / SystemRescue） | 有 | **否**。能挂载，但进去之后要在控制台里敲命令 | 0 | **只能人工**，第 5.4 节 R3b |

**选 B 的三条理由**：

1. 它是唯一一个"失败模式不依赖平台特性"的方案。引导对象在我们自己的盘上，我们在 macOS 里有 root，能改。
2. 它绕开了 `ipxe_chain_url` 不能用于已有实例这个限制。
3. 它让 ISO 槽位保持空闲（第 4.7 节）。

**B 的代价与它的边界条件**：rescue 分区活在系统盘上，所以"系统盘整块写坏"这一种失败它救不了。那一种只能靠 C 或第 5.5 节。因此 B 和 C 不是二选一，是阶梯上相邻的两级。

**rescue 分区放什么**：一个最小 Alpine 的"磁盘安装"，不是 netboot。用 Alpine 的 `sys` 模式装到一个小分区上，配好 sshd 与公钥，再把第 4.3.1 节的脚本装进去。**内核模块必须本地化**（不能依赖 `modloop=` 的 HTTP），否则网络一出问题 rescue 自己就起不来。

### 5.2 分区布局

在 `71` 的基础上插入一个分区。目标盘（瘦镜像，16 到 24 GB 虚拟容量）的 GPT：

```text
/dev/vda
├─ p1  EFI System Partition            C12A7328-F81F-11D2-BA4B-00A0C93EC93B
│      FAT32, 256 MiB, label OPENCORE
│      ├─ /EFI/BOOT/BOOTX64.EFI            ← 当前生效的引导对象（被交换的那个文件）
│      ├─ /EFI/BOOT/BOOTX64.OC.efi         ← OpenCore 的副本
│      ├─ /EFI/BOOT/BOOTX64.RESCUE.efi     ← GRUB 的副本
│      ├─ /EFI/OC/…                        ← 71 §6 的 OpenCore 配置、kext、SSDT
│      ├─ /EFI/rescue/grub.cfg
│      └─ /boot-mode                       ← 单行文本：macos | rescue（给人和脚本看的状态）
├─ p2  Linux filesystem                0FC63DAF-8483-4772-8E79-3D69D8477DE4
│      ext4, 1.5 GiB, label RESCUE
│      最小 Alpine（sys 模式），本地内核与模块，sshd + harness 公钥
└─ p3  Apple APFS                      7C3457EF-0000-11AA-AA11-00306543ECAC
       剩余全部，macOS 26.7.2 的 APFS 容器
       首启由 firstboot-expand LaunchDaemon 扩满（§4.6.2）
```

**ESP 从 `71` 第 8.2.2 节的 64 MiB 放大到 256 MiB**，三个理由：要容纳两份 EFI 引导器 + 一份 GRUB 内核与 initramfs 的备份；OpenCore 的 DEBUG 构建会往 ESP 写日志（`71` 第 9 节）；留出 ApplePanic 落盘空间。

**rescue 分区放在 p2 而不是最后**，理由：p3 的 APFS 容器要在首启时向后扩展到盘尾（第 4.6.2 节的 `resizeContainer ... 0`），它后面不能有别的分区。

**分区类型 GUID 必须写对**。macOS 的 `diskutil` 会对不认识的分区类型显示为 unknown，这是正常的，但如果把 rescue 分区标成 Apple 的类型，macOS 可能试图挂载甚至"修复"它。用 Linux 的通用类型 GUID 让 macOS 完全无视它。`INFERRED`，macOS 对 ext4 分区的实际行为未实测（D-010）。

### 5.3 OpenCore 与 Alpine 引导项如何共存

#### 5.3.1 为什么不用固件 NVRAM

最直觉的做法是 `efibootmgr` 风格的 `BootNext`（第 2.3 节）。在 Vultr 上它有两个问题：

- **NVRAM 持久性未确证**，这是 `80` 的 H-002（`BLOCKED`）。
- **从 macOS 里写全局 EFI 变量未确证**。macOS 的 `nvram` 工具支持 `GUID:name=value` 形式，理论上可以写 `8BE4DF61-93CA-11D2-AA0D-00E098032B8C:BootNext`，但 OpenCore 自己也在管 NVRAM（`71` 第 6.7 节的 `WriteFlash = true`、`RequestBootVarRouting`），两者的交互未知。`INFERRED`，记为 D-011。

**所以主机制必须是"状态在盘上"而不是"状态在 NVRAM 里"。**

#### 5.3.2 主机制：交换 ESP 里的 `BOOTX64.EFI`

UEFI 固件在没有可用的 `BootOrder` 条目时，会去找 ESP 上的 `\EFI\BOOT\BOOTX64.EFI`（可移动介质回退路径）。Vultr 的实例每次开机都从这个路径起（`INFERRED`，这是 `71` 第 8.3.4 节 I-024 的同一个未确证点）。于是：

| 想启动谁 | `\EFI\BOOT\BOOTX64.EFI` 的内容 | 谁来改它 |
|---|---|---|
| macOS | `BOOTX64.OC.efi` 的副本（OpenCore） | 默认状态；rescue 退出时恢复 |
| rescue | `BOOTX64.RESCUE.efi` 的副本（GRUB） | macOS 侧的 `arm-rescue` 脚本，或 Alpine 侧 |

**macOS 侧的武装脚本**（可直接照抄）：

```bash
#!/bin/bash
# /usr/local/libexec/arm-rescue.sh [--oneshot]
# 把下次启动切到 rescue。--oneshot 让 rescue 启动后自动切回 macOS。
set -euo pipefail

ESP_DEV=$(diskutil list -plist \
  | plutil -extract AllDisksAndPartitions.0.Partitions.0.DeviceIdentifier raw -o - -)
MNT=/Volumes/EFI
diskutil mount -mountPoint "$MNT" "$ESP_DEV"

cd "$MNT/EFI/BOOT"
[ -f BOOTX64.OC.efi ]     || { echo "missing BOOTX64.OC.efi"; exit 1; }
[ -f BOOTX64.RESCUE.efi ] || { echo "missing BOOTX64.RESCUE.efi"; exit 1; }

# 原子性：先写临时名，再 mv。FAT 上 mv 是目录项改写，比整文件复制安全
cp -f BOOTX64.RESCUE.efi BOOTX64.NEW.efi
sync
mv -f BOOTX64.NEW.efi BOOTX64.EFI
printf 'rescue\n' > "$MNT/boot-mode"
if [ "${1:-}" = --oneshot ]; then
  printf 'oneshot\n' > "$MNT/boot-revert"
fi
sync
diskutil unmount "$MNT"
echo "armed: next boot = rescue"
```

**Alpine 侧（rescue 内）的恢复脚本**，由 `local.d` 在开机时自动跑：

```bash
#!/bin/sh
# /etc/local.d/00-revert-boot.start   —— rescue 一起来就先把下次启动还给 macOS
set -eu
mkdir -p /mnt/esp
ESP=$(blkid -L OPENCORE || true)
[ -n "$ESP" ] || exit 0
mount -t vfat "$ESP" /mnt/esp
if [ -f /mnt/esp/boot-revert ]; then
  cp -f /mnt/esp/EFI/BOOT/BOOTX64.OC.efi /mnt/esp/EFI/BOOT/BOOTX64.NEW.efi
  sync
  mv -f /mnt/esp/EFI/BOOT/BOOTX64.NEW.efi /mnt/esp/EFI/BOOT/BOOTX64.EFI
  printf 'macos\n' > /mnt/esp/boot-mode
  rm -f /mnt/esp/boot-revert
  sync
fi
umount /mnt/esp
```

**这两段脚本合起来复刻了 `BootNext` 的一次性语义**，但状态存在 FAT 文件系统里而不是固件 NVRAM 里。它比 `BootNext` 多一个好处：**rescue 自己能看到并修改这个状态**，所以"进 rescue 之后把下次启动改回 macOS"是 rescue 的第一个动作，不依赖固件行为。

**它比 `BootNext` 差的地方**：如果 rescue 起不来（GRUB 坏了、ext4 分区坏了），下次启动还是 rescue，会死循环。两道防线：

1. GRUB 的 `grub.cfg` 里**第一个条目是 rescue，第二个条目是"chainload OpenCore"**，超时 5 秒自动落到第二个。即 GRUB 能起但 Alpine 起不来时，自己会把控制权交回 OpenCore：

```text
# /EFI/rescue/grub.cfg
set default=0
set timeout=5
set timeout_style=menu

menuentry "Alpine rescue" {
    search --no-floppy --label --set=root RESCUE
    linux  /boot/vmlinuz-lts root=LABEL=RESCUE modules=sd-mod,usb-storage,ext4 quiet
    initrd /boot/initramfs-lts
}

menuentry "Chainload OpenCore (macOS)" {
    search --no-floppy --label --set=root OPENCORE
    chainloader /EFI/BOOT/BOOTX64.OC.efi
}
```

2. 死循环的最终出口是第 5.5 节的平台级重装。

#### 5.3.3 次机制：让 OpenCore 自己能列出 rescue

有控制台时（L1），更舒服的形态是让 OpenCore 的 picker 直接显示 Alpine。

`KNOWN`：OpenCore 自带 `OpenLinuxBoot.efi` 驱动，用法是把它与 `ext4_x64.efi` 一起加到 `config.plist` 的 `UEFI/Drivers`，并确保 `RequestBootVarRouting` 与 `LauncherOption` 已启用，建议同时开 `HideAuxiliary` 把旧内核条目藏起来（转述自 <https://dortania.github.io/OpenCore-Multiboot/oc/linux.html>）。

对 `71` 第 6 节 `config.plist` 的增量（**这是本文对 `71` 的唯一配置修改要求**）：

```text
UEFI/Drivers 追加两项：
  + OpenLinuxBoot.efi      （OpenCorePkg 自带）
  + ext4_x64.efi           （来自 acidanthera/OcBinaryData，commit 要固定）
Misc/Boot/HideAuxiliary = true     （可选，减少 picker 噪声）
```

**它不替代 5.3.2，只是补充。** 理由：`OpenLinuxBoot` 需要有人在 picker 前按键选择，而 L2 上没有人也没有画面。5.3.2 的文件交换才是无人环境下的机制。

#### 5.3.4 默认启动谁

**默认永远是 macOS。** 判据很简单：实验的常态是跑 macOS，rescue 是异常路径。让异常路径成为默认，等于每次开机都多一次失败机会。

`71` 第 6 节已把 `Misc/Boot/Timeout` 与 picker 行为定下来，本文不改。rescue 的进入只通过 5.3.2 的显式武装。

#### 5.3.5 构建期要做的验证

**在阶段 A 结束、镜像发布之前，必须在 L1 上把这四条跑一遍**（`INFERRED`，这是我们能在零成本下关掉最多风险的地方）：

```text
V1  默认启动进 macOS，SSH 通
V2  macOS 内跑 arm-rescue.sh --oneshot，重启，进 Alpine，SSH 通
V3  Alpine 内确认 /mnt/esp/boot-mode 已被改回 macos，重启，进 macOS，SSH 通
V4  故意破坏 rescue 分区（dd 覆盖 p2 前 1 MiB），武装 rescue，重启
    → 应落到 GRUB 的第二个条目，最终进 macOS
```

V4 是最重要的一条，它验证的是"救援机制本身坏掉时不会把机器变成砖"。

### 5.4 救砖路径清单

按从轻到重排。**每一层给出触发条件、确切操作序列、代价、以及它依赖的未确证前提。**

#### R0：SSH 还活着（S1 状态）

**触发条件**：`harness.env_wait_ready {signal:"ssh"}` 返回 `ready: true`，但显示相关判据失败（WindowServer 不在、`screencapture` 超时、`metal-probe` 报无设备）。

**这不是救砖，这是正常的实验失败。** 操作序列就是 `80` 第 2.8 / 2.9.4 节的取证流程，然后 `restore` 回 golden。本层列在这里只为把阶梯补全。

```bash
# 取证
harness.collect { env_id, experiment_id, profile: "failure" }
# 回滚
curl -s -X POST "https://api.vultr.com/v2/instances/${INST_ID}/restore" -H "$VH" -H "$VJ" \
  -d "{\"snapshot_id\":\"${GOLDEN_SNAP}\"}"
```

**代价**：一次 restore，分钟级 + 10 到 15 分钟（第 3.1.2 节伴随事实 2）。
**前提**：无。

#### R1：macOS 起不来，但上一次 macOS 存活时已武装过 rescue

**触发条件**：重启后 SSH 在 `boot_timeout`（建议 900 秒）内不可达，且**本次实验在重启前执行过 `arm-rescue.sh --oneshot`**。

**这是唯一"零成本"的救砖层，前提是预先武装。** 因此写进强制规则：

> **凡是会改动引导链、kext 集合、NVRAM 或 ESP 的实验，必须在重启前武装 rescue。** 这条规则写进 `80` 第 2.1 节的提升门槛，和"内核改动先过 L1"同级。

**操作序列**：

```bash
# 1. 等。oneshot 武装过的话，这次启动进的就是 Alpine
for i in $(seq 1 60); do
  ssh -o BatchMode=yes -o ConnectTimeout=5 -i "$HARNESS_KEY" "root@${IP}" 'echo RESCUE_UP' && break
  sleep 15
done
# 2. 进去之后：取证（这是 panic 期证据的唯一回捞机会，见下）
ssh -i "$HARNESS_KEY" "root@${IP}" 'set -eu
  mkdir -p /mnt/esp && mount -t vfat "$(blkid -L OPENCORE)" /mnt/esp
  # OpenCore DEBUG 构建的日志在 ESP 上（71 §9）
  ls -l /mnt/esp/*.txt /mnt/esp/EFI/OC/*.log 2>/dev/null || true
  tar czf /tmp/esp-evidence.tgz -C /mnt/esp . 2>/dev/null || true
  # macOS 的 panic 报告在 APFS 上。Alpine 读 APFS 需要 apfs-fuse，默认没有
  apk add --no-cache apfs-fuse 2>/dev/null || echo "NO_APFS_READER"'
scp -i "$HARNESS_KEY" "root@${IP}:/tmp/esp-evidence.tgz" ./
# 3. 修：把 ESP 恢复到已知可引导状态
ssh -i "$HARNESS_KEY" "root@${IP}" '
  cp -f /mnt/esp/EFI/BOOT/BOOTX64.OC.efi /mnt/esp/EFI/BOOT/BOOTX64.EFI
  # 若本次实验改了 config.plist，回滚到构建期的备份
  [ -f /mnt/esp/EFI/OC/config.known-good.plist ] && \
    cp -f /mnt/esp/EFI/OC/config.known-good.plist /mnt/esp/EFI/OC/config.plist
  sync; umount /mnt/esp; reboot'
```

**`apfs-fuse` 这一行是本层最大的不确定性**：Alpine 的仓库里是否有可用的 APFS 只读驱动未确认（`INFERRED`，记为 D-012）。如果没有，R1 层能救引导但**拿不到 macOS 侧的 panic 报告**，而那正是 `80` 第 1.4 节说的"重启后回捞"的对象。两条缓解：

- 把 panic 报告的回捞留给 R0（即 macOS 能起来时再捞上一次的报告）。macOS 的 panic 报告在重启后仍在 `/Library/Logs/DiagnosticReports/`（`80` 第 2.8.5 节），不要求当场捞。
- 构建期在 ESP 上放一个 FAT 的"信箱"目录，让 macOS 侧的 agent 在每次关机前把最近的 panic 报告复制一份进去。FAT 两边都能读。**这是本文对 `80` 第 2.6 节 agent 的一条新增要求**（第 6.1 节）。

**代价**：两次重启，约 10 到 20 分钟。无额外计费。
**前提**：第 5.3.2 节的 ESP 文件交换机制有效（依赖 I-024：Vultr 固件确实走 `\EFI\BOOT\BOOTX64.EFI`）。

#### R2：macOS 起不来，且没有预先武装

**触发条件**：SSH 不可达，`boot-mode` 是 `macos`，没有任何办法让下次启动落到 rescue。

**这一层是 R1 规则被违反的后果，它比 R1 贵一个数量级。** 唯一的入口是平台侧换引导对象，即 ISO attach：

```bash
# 1. 先取证：把当前盘存成快照。抹盘之前必须做这一步
curl -s -X POST "https://api.vultr.com/v2/instances/${INST_ID}/halt" -H "$VH"
until [ "$(curl -s "https://api.vultr.com/v2/instances/${INST_ID}" -H "$VH" | jq -r '.instance.power_status')" = stopped ]; do sleep 10; done
FORENSIC=$(curl -s -X POST "https://api.vultr.com/v2/snapshots" -H "$VH" -H "$VJ" \
  -d "{\"instance_id\":\"${INST_ID}\",\"description\":\"forensic ${INST_ID} $(date -u +%Y%m%dT%H%M%SZ)\"}" \
  | jq -r '.snapshot.id')
# 等 complete（最长约 30 分钟）

# 2. 挂我们的 Alpine rescue ISO（槽 1）。attach 会重启实例
curl -s -X POST "https://api.vultr.com/v2/instances/${INST_ID}/iso/attach" -H "$VH" -H "$VJ" \
  -d "{\"iso_id\":\"${RESCUE_ISO_ID}\"}"
until [ "$(curl -s "https://api.vultr.com/v2/instances/${INST_ID}/iso" -H "$VH" | jq -r '.iso_status.state')" = isomounted ]; do sleep 10; done

# 3. SSH 进 ISO 里的 Alpine，修 ESP（同 R1 第 3 步）
# 4. 卸 ISO（同样会重启）
curl -s -X POST "https://api.vultr.com/v2/instances/${INST_ID}/iso/detach" -H "$VH"
```

**这条路要求我们自制的 rescue ISO 是"开机即 SSH 可达"的**，即 ISO 里的 Alpine 必须自带公钥与 sshd 自启。公共 ISO 库里的 Finnix / SystemRescue 做不到这一点（它们开机进一个需要人敲命令的 shell），所以槽 1 应当放我们自己的 ISO。

**是否为此占掉一个槽位，是一个取舍**：

- 占：R2 全自动，恢复时间约 40 到 60 分钟（主要是取证快照）。
- 不占：R2 退化为 R3b（人工），恢复时间取决于人。

**建议占掉槽 1。** 第 4.7 节释放了两个槽位，花掉一个买"无人值守的 R2"是值得的。

**代价**：两次重启 + 一次快照（最长 30 分钟）+ 快照存储费。
**前提**：`iso/attach` 对一台"系统盘不可引导"的实例仍然有效（`INFERRED`，D-013）。

#### R3：rescue 分区与自制 ISO 都不行

**R3a：换一张 ISO。** 槽 0 空着就是为了这个。挂一张不同的介质（另一版 Alpine、或 `71` 第 8.3.3 节那张带 BaseSystem 的 macOS 恢复 ISO，用来跑 macOS 自己的磁盘工具）。

**R3b：公共 ISO + 人工。** `GET /v2/iso-public` 里有 Finnix、GParted、Hiren's BootCD PE、SystemRescue（`KNOWN`，第 3.1.1 节）。挂上之后必须有人打开网页控制台操作。证据按 `80` 第 1.3 节的规定标 `capture_method: "manual-portal"`。

```bash
curl -s "https://api.vultr.com/v2/iso-public" -H "$VH" \
  | jq -r '.public_isos[] | select(.name|test("Finnix|SystemRescue|GParted";"i")) | "\(.id)\t\(.name)"'
```

**代价**：R3a 同 R2；R3b 需要人，时间不可估。
**前提**：公共 ISO 的 id 能被 `iso/attach` 接受（`INFERRED`，门户明确支持从 ISO Library 选，API 侧未确证，D-014）。

#### R4：换回原厂 OS（抹盘，保 IP）

**触发条件**：以上全部失败，或判定"修不如重装"。

**这是第一道"确定能成"的保险。** 它不依赖任何我们控制的引导对象，只依赖平台自己的装机流程。

```bash
# 取证快照（若 R2 已做过就跳过）
# ...

# 方式 1：PATCH 换 OS。保留实例与 IP
DEBIAN_ID=$(curl -s "https://api.vultr.com/v2/os?per_page=200" -H "$VH" \
  | jq -r '.os[] | select(.family=="debian" and (.name|test("13"))) | .id' | head -1)
curl -s -X PATCH "https://api.vultr.com/v2/instances/${INST_ID}" -H "$VH" -H "$VJ" \
  -d "{\"os_id\":${DEBIAN_ID}}"

# 方式 2：原地重装当前 OS
curl -s -X POST "https://api.vultr.com/v2/instances/${INST_ID}/reinstall" -H "$VH" -H "$VJ" \
  -d '{"hostname":"macos-e0-l2"}'
```

两者的证据与语义（`KNOWN`）：

- `PATCH /v2/instances/{id}` 的请求体含 `os_id` / `app_id` / `image_id`（来源：`govultr/instance.go` 的 `InstanceUpdateReq`）。官方的"更换操作系统"文档说明换 OS 会抹掉服务器上的全部数据并装一个新文件系统，同时**保留实例的 IP 网络信息**（转述自 <https://docs.vultr.com/products/compute/bare-metal/management/change-os>）。
- `POST /v2/instances/{id}/reinstall` 的请求体只有可选的 `hostname`（来源：同上的 `ReinstallReq`）。官方文档说明重装会抹掉文件系统、重置全部配置并重新安装操作系统，数据不可恢复除非有备份或快照（转述自 <https://docs.vultr.com/products/compute/cloud-compute/management/reinstall-instance>）。`vultr-cli` 的 `instance reinstall` 描述一致（转述自 <https://docs.vultr.com/reference/vultr-cli/instance/reinstall>）。

**一个必须知道的副作用**：改 hostname 也会触发重装（官方文档明确写了改 hostname 会重装操作系统并可能导致数据丢失，转述自 <https://docs.vultr.com/products/compute/cloud-compute/management/change-hostname>）。所以 **harness 不得为了"整理标签"去 PATCH hostname**。这条写进第 6.1 节的工具约束。

**代价**：macOS 系统盘内容全失（已由取证快照保住）；一次装机时间。实例与 IP 保留。
**前提**：无。这是本阶梯上第一条不含 `INFERRED` 前提的路。

#### R5：销毁重建

**触发条件**：R4 之后实例仍不可达（即平台自己的装机也失败，属于平台故障）。

```bash
# 取证快照已在 R2/R4 之前做过
curl -s -X DELETE "https://api.vultr.com/v2/instances/${INST_ID}" -H "$VH"
# 用 golden 快照重建
curl -s -X POST "https://api.vultr.com/v2/instances" -H "$VH" -H "$VJ" \
  -d "{\"region\":\"${REGION}\",\"plan\":\"${PLAN}\",\"snapshot_id\":\"${GOLDEN_SNAP}\",\"label\":\"macos-e0-l2\"}"
```

**代价**：IP 变更（要更新 harness 的凭据与 known_hosts）；新实例至少 1 小时计费（`80` 第 1.6 节）。
**前提**：无。

#### 阶梯总表

| 层 | 触发条件 | 入口 | 自动化 | 恢复时间量级 | 依赖的未确证前提 |
|---|---|---|---|---|---|
| R0 | SSH 通，显示失败 | SSH | 全自动 | 10 到 20 min | 无 |
| R1 | SSH 断 + 已武装 rescue | 盘内 rescue 分区 | 全自动 | 10 到 20 min | I-024、D-010 |
| R2 | SSH 断 + 未武装 | 自制 rescue ISO（槽 1） | 全自动 | 40 到 60 min | D-013 |
| R3a | R2 失败 | 另一张 ISO（槽 0） | 全自动 | 40 到 60 min | 同上 |
| R3b | R3a 失败 | 公共 ISO + 人工控制台 | **人工** | 不可估 | D-014 |
| R4 | 以上全败 | `PATCH os_id` 或 `reinstall` | 全自动 | 20 到 40 min | **无** |
| R5 | R4 也失败（平台故障） | `DELETE` + 重建 | 全自动 | 1 h+ | **无** |

**R1 到 R3 全部依赖未确证前提，R4 与 R5 不依赖。** 这就是为什么 R4 是"最后一道保险"而不是"又一个可能失败的选项"。

### 5.5 最后一道保险：明确结论

**`POST /v2/instances/{id}/reinstall` 与 `PATCH /v2/instances/{id}` 带 `os_id` 这两个端点，是无控制台环境下把一台黑屏实例变回一台可 SSH 机器的最终手段。** 两者都抹盘、都纯 API、都不需要控制台、都保留实例与 IP。

**因此"砖"这个词在 Vultr 上严格来说不成立**：我们可能永久失去盘上的 macOS，但不会永久失去这台机器。这把本项目的风险从"可能损失一台实例"降级为"可能损失一次实验的盘内容"，而盘内容已经由 golden 快照覆盖。

**唯一真正不可恢复的东西是"没有被快照保护的实验现场"。** 所以第 5.4 节每一层在执行抹盘前都先做取证快照，这不是可选步骤。

### 5.6 harness 侧的状态机

把 R 阶梯做成可被 `80` 的 `Detector` 与 `Runner` 调用的状态机。

```text
                  ┌──────────────┐
                  │  ssh_ready?  │
                  └──┬────────┬──┘
                 yes │        │ no
                     v        v
              ┌──────────┐  ┌───────────────────────┐
              │ verdict  │  │ wait boot_timeout=900 │
              │ 按 80 §2.9│  └──────────┬────────────┘
              └──────────┘             │ still no ssh
                                        v
                             ┌──────────────────────┐
                             │ platform power_status│
                             └───┬──────────────┬───┘
                      running    │              │  stopped / error
                                 v              v
                   ┌──────────────────┐   ┌──────────────────┐
                   │ boot-mode armed? │   │ infra_error      │
                   └──┬───────────┬───┘   │ 重试 start，不计失败│
                  yes │           │ no    └──────────────────┘
                      v           v
                  ┌───────┐  ┌───────────────┐
                  │  R1   │  │ forensic snap │
                  └───┬───┘  └───────┬───────┘
                 ok   │ fail         v
                      │          ┌───────┐
                      │          │  R2   │
                      v          └───┬───┘
                 ┌─────────┐  ok     │ fail
                 │ collect │◄────────┤
                 │ + verdict│         v
                 └─────────┘     ┌───────┐   fail    ┌───────┐  fail  ┌────┐
                                 │  R3a  │──────────►│  R4   │───────►│ R5 │
                                 └───────┘           └───────┘        └────┘
```

**两条实现约束**：

1. **每一层的进入都要落一条 `detections[]`**（`80` 第 2.10.3 节），`kind` 取值新增：`rescue_r1_entered`、`rescue_r2_entered`、`rescue_r3_entered`、`platform_reimage`、`instance_replaced`。没有这个，事后无法区分"实验失败一次"和"实验失败并且把机器重装了三遍"。
2. **R4 与 R5 必须要求 `confirm: true`**，与 `80` 第 3.3.2 节的 `env_destroy` 同级。它们是抹盘动作，不许被一次参数笔误触发。

---

## 6. 与现有设计的接口

### 6.1 对 `80` 第 3.3.8 节工具组的修改

`80` 第 3.3.8 节的 `harness.image_publish` / `image_register` / `image_attach` 三件套是**围绕 ISO 这一条通道设计的**。本文的主路径不走 ISO，所以这组工具**需要改**。下面明确说改成什么。

#### 6.1.1 保留且不变的部分

`publish` 与 `register` 分开这个决定是对的，而且在新方案下更对：`create-from-url` 同样是"我们托管、平台来拉"，同样会出现"托管成功但平台拉取失败"这类必须能定位到具体步骤的失败。保留。

`iso_slots_full` 不自动腾位、`hash_mismatch` 阻断且清理、`image_attach` 强制 `confirm`，三条全部保留。

#### 6.1.2 必须改的部分

| 现状 | 问题 | 改成什么 |
|---|---|---|
| `image_publish` 对 >10 GB 返回 `permanent/image_too_large` | **这是把 ISO 的限制错误地提升成了工具层的通用约束。** 新方案的主路径产物是 20 GB 以上的 raw，会被自己的工具挡住 | 体积检查下移到 `image_register`，并**按目标通道判定**：`channel: "iso"` 时查 10 GB，`channel: "snapshot"` 时不查（上限未知，D-003），`channel: "stream"` 时查目标盘容量 |
| `image_publish` 的 `kind` 只有 `install`/`rescue`/`payload` | 缺了最重要的一类 | `kind` 增加 `system_disk`（整块装好的系统盘） |
| `image_register` 的返回只有 `platform_iso_id` | 快照通道的产物是 `snapshot_id`，不是 `iso_id` | 返回改为 `{platform_ref, platform_ref_kind: "iso"\|"snapshot", hash_verified, slot?}` |
| 没有任何工具能用 `ipxe_chain_url` | 第 3.2 节的能力在工具层完全缺失 | 新增 `harness.env_create` 的入参 `from_ipxe: {chain_url}` |
| 没有任何工具表达"流式写盘" | 第 4.5 节的主要动作无法被调用 | 新增 `harness.image_stream_write` |
| 没有任何工具表达救砖阶梯 | 第 5.4 节无法被自动化 | 新增 `harness.rescue_*` 一组 |

#### 6.1.3 修改后的完整工具表

```text
【改】harness.image_publish
  入参  local_path, label, kind: "install"|"rescue"|"payload"|"system_disk",
        split: bool (default false)        ← true 时按 §4.5 拆成 .head/.body.zst/.chunks.tsv
        access: "signed_url"|"bearer"      ← §4.2.3 的版权边界要求
  返回  { image_id, published_url, head_url?, body_url?, chunks_url?,
          sha256, size_bytes, access, expires_at? }
  失败  permanent/no_publish_endpoint
        permanent/public_url_required_for_snapshot_channel   ← 新增，见 D-008

【改】harness.image_register
  入参  image_id, layer, channel: "iso"|"snapshot", slot?: 0|1, uefi?: bool (default true),
        confirm: bool
  返回  async → { platform_ref, platform_ref_kind, hash_verified, size_matches_local, slot? }
  失败  permanent/image_too_large_for_channel   ← 只在 channel="iso" 且 >10 GB 时
        permanent/iso_slots_full
        permanent/hash_mismatch
        permanent/snapshot_import_failed

【新】harness.image_stream_write
  入参  env_id (必须是一个 rescueOS 环境), image_id, target_device?: string,
        verify: bool (default true), flip_head_last: bool (default true, 不许设 false),
        confirm: bool
  返回  async → { bytes_written, duration_ms, throughput_bps,
                  chunks_total, chunks_bad, head_flipped, gpt_fixed }
  失败  permanent/target_smaller_than_image
        permanent/verify_failed       ← 此时 head 未翻转，盘仍是旧系统
        transient/download_stalled

【新】harness.env_create 增补入参
  from_ipxe: { chain_url: string }
  约束：与 from_snapshot / from_iso / from_os 四者互斥

【新】harness.rescue_arm
  入参  env_id, mode: "oneshot"|"sticky" (default oneshot)
  返回  { armed: true, boot_mode: "rescue", mechanism: "esp_swap"|"boot_next" }
  失败  permanent/esp_not_writable, unsupported/no_rescue_partition
  说明：在 macOS 存活时调用。§5.3.2

【新】harness.rescue_status
  入参  env_id
  返回  { boot_mode: "macos"|"rescue"|"unknown", revert_pending: bool,
          rescue_partition_present: bool, rescue_last_boot_at? }

【新】harness.rescue_escalate
  入参  env_id, max_layer: "R1"|"R2"|"R3a"|"R3b"|"R4"|"R5",
        forensic_snapshot: bool (default true), confirm: bool
  返回  async → { layers_attempted: [...], final_layer, recovered: bool,
                  forensic_snapshot_id?, new_env_id?, new_ip? }
  失败  permanent/confirmation_required
        permanent/manual_intervention_required   ← 走到 R3b 时返回这个，不假装自动化
  说明：按 §5.6 的状态机逐层尝试，到 max_layer 为止
```

**`flip_head_last` 不许设 `false` 这一点要写进实现**：参数存在只是为了让意图显式，不是为了让它可关。工具层对 `false` 直接返回 `permanent/unsafe_parameter`。

#### 6.1.4 对 `80` 其他两处的新增要求

1. **第 2.6 节的 guest agent 增加一个任务 `kind`：`esp_mailbox_sync`。** 职责是把 `/Library/Logs/DiagnosticReports/*.panic` 的最近 N 份复制到 ESP 的 `/evidence/` 目录（FAT，两边都能读）。它必须在每次 `reboot` / `shutdown` 任务之前自动执行一次。理由见第 5.4 节 R1 层的 `apfs-fuse` 不确定性：这是让 panic 证据在"macOS 再也起不来"时仍可取回的唯一确定手段。
2. **第 2.10.3 节的 `result.json` 增加一段 `recovery`**：

```json
"recovery": {
  "rescue_armed_before_reboot": true,
  "rescue_mechanism": "esp_swap",
  "layers_attempted": ["R1"],
  "final_layer": "R1",
  "recovered": true,
  "forensic_snapshot_id": null,
  "platform_reimaged": false,
  "instance_replaced": false
}
```

`verdict_reason` 的封闭枚举增加三项：`rescue_recovered`、`platform_reimaged`、`unrecoverable`。

### 6.2 与 `80` 第 2.5 节三条 payload 路径的关系

`80` 第 2.5 节定义的是**实验期投放 payload**（一个 tarball、几十 MB），本文定义的是**部署期投放系统盘**（几十 GB）。两者是不同的问题，不要混。

| `80` 第 2.5 节 | 本文的对应物 | 关系 |
|---|---|---|
| 路径 A：SSH（`scp` + 校验 + `agent install`） | 无对应 | **不变，仍是实验期的默认路径** |
| 路径 B：附加块设备（L2 用 Block Storage，L1 用 FAT raw） | 第 3.1.4 节 | **本文强化了它**：Block Storage 的角色被明确为"第二块盘"，并新增了它作为 R2 层证据回传通道的用途。`80` 的 H-004（热插在 macOS guest 内是否可见）仍然是它的阻塞项 |
| 路径 C：ISO（仅救援，须人确认） | 第 5.4 节 R2/R3 | **本文把它具体化了**：从"仅救援、须人确认"变成"槽 1 放自制 Alpine rescue ISO，R2 层全自动；槽 0 留给 R3a；公共 ISO 是 R3b 的人工兜底" |
| 无 | 第 4.5 节的流式写盘 | **新增的第四条路径**，只用于部署期，不进实验回路 |

**一条重要的纠正**：`80` 第 2.5 节说"在路径 B 被确证之前，L2 的唯一投放路径是 SSH"。这句话在**实验期**仍然成立，但在**部署期**不成立：部署期根本没有 SSH，因为 macOS 还不存在。本文的 D1/D2 填的正是这个空白。

### 6.3 ISO 槽位结论

**新方案下，ISO 槽位不再被部署占用。** 第 4.7 节已经论证。最终分配：

| 槽 | 内容 | 谁用 | 可否为空 |
|---|---|---|---|
| 0 | 空 | R3a 的临时介质 | **保持为空** |
| 1 | 自制 Alpine rescue ISO（≈200 MB），开机即 SSH 可达 | R2 | 建议占用，见第 5.4 节 R2 的取舍 |

**这是一个可以向上游释放的约束**：`80` 第 1.2 节的"约束 2：必须把 ISO 当稀缺槽位管理，一个放安装介质一个放救援"在本文之后变成"两个槽位都是救援用途，安装介质不占槽位"。建议把 `80` 第 1.2 节那一段改写，并把 3.3.8 节 `iso_slots_full` 的文字说明从"槽 0 放安装介质、槽 1 放救援"改为"两槽均为救援，分工见 `73` 第 6.3 节"。

### 6.4 对 `71` 的修订建议

| `71` 的位置 | 建议 | 理由 |
|---|---|---|
| 第 8.1 节产物总表 | 新增两行：`macos-thin-<build>.raw`（16 到 24 GB，用于 `create-from-url`）与 `rescue-alpine-<ver>.iso`（≈200 MB，槽 1） | 第 4.6.3、6.3 节 |
| 第 8.2.1 节 EFI 树 | ESP 从 64 MiB 改为 256 MiB；`EFI/BOOT/` 下放三个文件（`BOOTX64.EFI`、`BOOTX64.OC.efi`、`BOOTX64.RESCUE.efi`）；`UEFI/Drivers` 追加 `OpenLinuxBoot.efi` 与 `ext4_x64.efi` | 第 5.2、5.3.3 节 |
| 第 8.3.3 节配方 A（hybrid ISO） | 降级为"仅 D0 场景使用"，并把 I-021 / I-007 的阻塞范围从"L2"改为"D0" | 第 4.7 节 |
| 第 8.3.4 节配方 B | **升级为主路径**，并把内容从"OpenCore + BaseSystem 的引导介质"改为"装好系统的瘦镜像"。原有的"引导介质"形态保留为 D0 的备选 | 第 4.2 节 |
| 第 8.3.5 节"L2 上的完整安装器怎么办" | 结论从"推荐顺序 3 → 1 → 2"改为"**只走路 3**"，即把安装器整个排除在 L2 之外 | 第 4.1 节的裁决：L2 永不安装系统，只接收装好的盘 |
| 第 8.5 节 `image-manifest.json` | 新增字段：`partition_layout`（第 5.2 节的三分区描述）、`thin`（布尔）、`virtual_bytes`、`chunk_manifest_sha256`、`rescue: {alpine_version, apkovl_sha256}` | 第 4.5.3、4.6 节 |
| 第 11 节未解决项 | I-014（`create-from-url` 的体积上限与格式）**部分关闭**：格式已查清为未压缩 raw（`INFERRED`，第 3.1.2 节），体积上限仍 `BLOCKED` → 转为本文 D-003 | 第 3.1.2 节 |

---

## 7. 本地层（L1）：Debian 13 上的 KVM 可用性

### 7.1 检测命令

**六步，全部可直接照抄。** 按从快到慢排，任何一步给出否定结论就可以停。

```bash
#!/usr/bin/env bash
# scripts/check-kvm.sh —— 在 Debian 13 上判定 KVM 可用性
set -u
echo "=== 1. 自己是不是虚机 ==="
systemd-detect-virt || true                 # none = 裸机；kvm/vmware/microsoft/xen = 虚机
sudo dmidecode -s system-manufacturer 2>/dev/null || true
sudo dmidecode -s system-product-name 2>/dev/null || true

echo "=== 2. CPU 是否暴露虚拟化扩展 ==="
grep -E -c '(vmx|svm)' /proc/cpuinfo        # 0 = 没有，直接判负
grep -o -m1 -E '(vmx|svm)' /proc/cpuinfo || echo "NO vmx/svm"
lscpu | grep -i -E 'virtual|hypervisor|model name'

echo "=== 3. /dev/kvm 是否存在且可用 ==="
ls -l /dev/kvm 2>&1
[ -w /dev/kvm ] && echo "/dev/kvm WRITABLE" || echo "/dev/kvm NOT writable by $(id -un)"
id -nG | tr ' ' '\n' | grep -x kvm || echo "current user not in group kvm"

echo "=== 4. kvm-ok ==="
# 包名是 cpu-checker
sudo apt-get install -y cpu-checker >/dev/null 2>&1 || true
sudo kvm-ok 2>&1 || true

echo "=== 5. 模块与嵌套开关 ==="
lsmod | grep -E '^kvm' || echo "no kvm modules loaded"
for f in /sys/module/kvm_intel/parameters/nested /sys/module/kvm_amd/parameters/nested; do
  [ -r "$f" ] && echo "$f = $(cat "$f")"
done
# 这两个文件描述的是【本机能否再给它的 guest 开 vmx】，不是【本机自己有没有 vmx】。
# 对 L1 来说决定性的是第 2、3 步。

echo "=== 6. QEMU 看到哪些加速器 ==="
qemu-system-x86_64 -accel help 2>&1 || true
qemu-system-x86_64 --version 2>&1 | head -1 || true

echo "=== 7. 实测一次（最终判据）==="
timeout 20 qemu-system-x86_64 -machine q35,accel=kvm -m 256 -nographic \
  -kernel /dev/null 2>&1 | head -5 || true
# 看到 "Could not access KVM kernel module" / "failed to initialize kvm" = 不可用
```

证据与标签：

- `/sys/module/kvm_intel/parameters/nested` / `kvm_amd` 为嵌套开关，输出 `1`/`Y` 表示已启用（`KNOWN`，转述自 <https://docs.fedoraproject.org/en-US/quick-docs/using-nested-virtualization-in-kvm/> 与 <https://ubuntu.com/server/docs/how-to/virtualisation/enable-nested-virtualisation/>）。Ubuntu 的文档还指出这项在现代内核上通常默认已开。
- `kvm-ok` 来自 `cpu-checker` 包，用于判断本机能否跑硬件加速的 KVM 虚机（`KNOWN`，转述自 <https://www.cyberciti.biz/faq/installing-kvm-ok-command-on-debian-ubuntu-linux/>）。
- `/dev/kvm` 存在是嵌套可用的直接验证手段（`KNOWN`，转述自 <https://docs.openstack.org/devstack/2023.2/guides/devstack-with-nested-kvm.html>）。

### 7.2 判定矩阵

| 第 2 步（vmx/svm） | 第 3 步（/dev/kvm） | 判定 | 下一步 |
|---|---|---|---|
| >0 | 存在且可写 | **KVM 可用** | 直接用 `71` 第 8.2.4 节的命令行 |
| >0 | 不存在 | 模块没装/没加载 | `sudo apt install qemu-system-x86 qemu-utils`，`sudo modprobe kvm_intel`（或 `kvm_amd`） |
| >0 | 存在但不可写 | 权限问题 | `sudo usermod -aG kvm $USER`，重新登录 |
| 0 | 不存在 | **宿主没给我们虚拟化扩展** | 若第 1 步显示我们是虚机：请上层宿主开嵌套；否则 BIOS 里开 VT-x/AMD-V |
| 0 | 存在 | 异常组合 | 以第 7 步的实测为准 |

**关键区分**：如果第 1 步显示 `systemd-detect-virt` 返回 `kvm`/`vmware`/`microsoft` 之一，而第 2 步是 0，那么**问题不在这台 Debian 上，在它的宿主上**，本机任何配置都改不了它。这正是用户担心的情形。

### 7.3 KVM 不可用时：TCG 纯模拟值不值得

**结论：不值得。** 三条理由，前两条是硬阻塞。

**理由 1：指令集覆盖不够，而我们的 CPU 配置依赖它。**

`KNOWN`：QEMU 7.2 给 x86 的 TCG 加上了 AVX、AVX2、F16C、FMA3、VAES 的支持（转述自 <https://qemu.org/2022/12/14/qemu-7-2-0>）。`INFERRED`：**AVX-512 不在其中**，而且上游讨论里明确说 TCG 目前只能覆盖基线与 `x86-64-v2`，到 `x86-64-v3` 就有空缺（转述自 <https://gitlab.com/qemu-project/qemu/-/work_items/844>）。

`71` 第 5 节选定的 `-cpu Skylake-Server-v4` **含 AVX-512**。在 TCG 下这个型号要么被拒，要么被静默降级，两种都让 L1 的结果失去参考价值（`71` 的 I-012 本来就在问 AVX-512 对 Lavapipe 的影响）。验证方法一条命令：

```bash
qemu-system-x86_64 -accel tcg -cpu Skylake-Server-v4,enforce -machine q35 -m 512 -nographic 2>&1 | head
# enforce 会在任何请求的特性无法提供时报错而不是静默丢弃
```

**理由 2：macOS 对 TCG 的可启动性本身未知。**

`INFERRED`：没有找到任何"macOS 26 在 TCG 下启动成功"的公开记录。社区在 Apple Silicon 上跑 x86 macOS 的尝试里，对 TCG 的评价是效率极低，而对 HVF 的评价是可能触发 bug（转述自 <https://github.com/13garth/macos-qemu-virtualization/blob/main/README.md>）。QEMU 自己的文档也说没有加速器时它完全跑在用户态的二进制翻译器里，效率相对低（转述自 <https://wiki.gentoo.org/wiki/QEMU>）。

**理由 3：量级。**

`INFERRED`，这是数量级估计不是实测：同架构 TCG 相对 KVM 的减速通常在 10 到 50 倍。代入 macOS 的安装耗时（KVM 下几十分钟）：

| 场景 | KVM | TCG @10x | TCG @30x |
|---|---|---|---|
| macOS 安装一次 | 40 min | 7 h | 20 h |
| 冷启动到 SSH | 2 min | 20 min | 1 h |
| 一次 T1 实验（启动 + kextload + 重启） | 8 min | 1.3 h | 4 h |

**第三行是致命的。** `80` 第 5.5 节已经警告"花六周把 harness 做漂亮而 guest 上什么都没跑过"是最可能的失败模式。把单次实验从 8 分钟拉到 1 到 4 小时，迭代节奏就断了，L1 作为"快速迭代层"的全部价值消失。

**唯一值得用 TCG 的一件事**：验证 `71` 第 9 节的串口通道与 OpenCore 的早期日志格式。那只需要启动到 OpenCore picker，不需要进 macOS，几分钟的 TCG 还能忍。记为可选项，不进主路径。

### 7.4 本地完全不可行时的替代方案

按推荐顺序。

#### 替代 A：GitHub Actions 的 Linux runner（首选）

`KNOWN`：GitHub 官方的 runner 参考文档说明**GitHub 托管的 Linux runner 支持 Android SDK 工具的硬件加速**，并指向 Android 官方的模拟器硬件加速文档（转述自 <https://docs.github.com/en/actions/reference/runners/github-hosted-runners>）。Android 模拟器的硬件加速在 Linux 上就是 KVM，即 `/dev/kvm` 在这些 runner 上可用。

**为什么它最适合本项目**：

1. **仓库已经在用 GitHub Actions 跑证据采集**（`.github/workflows/evidence-macos26-intel.yml`，用的是 `macos-26-intel` runner）。工程习惯、发布边界规则、artifact 纪律全都已经建立。
2. 公开仓库的标准 runner 免费（`80` 的 H-013 在核对这一点）。
3. Linux runner 上可以 `apt install qemu-system-x86 qemu-utils mtools dosfstools xorriso gdisk`，即 `71` 第 2.2 节列的"必须在 Linux 上做的事"**全部可以在 CI 里做**，不需要用户自己有 Linux 机器。

**三个必须正面处理的限制**：

| 限制 | 后果 | 对策 |
|---|---|---|
| **单 job 上限 6 小时** | macOS 安装（约 40 min）能装完，但不能把一台长驻实验机放在 CI 里 | CI 只做"一次性构建 golden"与"单次短实验"。长驻回路仍需 L2 |
| **每个 job 从干净状态开始** | golden qcow2 不能留在 runner 上 | golden 必须存到外部（对象存储），每次 job 拉下来。拉 20 GB 要算进 job 时间 |
| **公开仓库的 artifact 对所有人可见** | **绝不能把含 Apple 二进制的镜像上传成 artifact** | 这与现有 workflow 顶部的发布边界规则是同一条。golden 走带鉴权的私有对象存储，`secrets` 存凭据；artifact 只放文本证据 |

**第三条是硬性合规要求，不是工程偏好。** 现有 workflow 的注释已经把这条规则写得很清楚（只上传派生的文本分析结果，绝不上传 Apple 的二进制本体），本文的 CI 方案必须继承它。

**可行性验证**（一条 workflow，几分钟，零成本）：

```yaml
# .github/workflows/probe-kvm.yml
name: probe-kvm
on: workflow_dispatch
jobs:
  probe:
    runs-on: ubuntu-latest
    timeout-minutes: 10
    steps:
      - name: KVM 可用性
        run: |
          set -x
          ls -l /dev/kvm || echo "NO /dev/kvm"
          grep -E -c '(vmx|svm)' /proc/cpuinfo || true
          sudo apt-get update -qq
          sudo apt-get install -y -qq cpu-checker qemu-system-x86
          sudo kvm-ok || true
          qemu-system-x86_64 -accel help
          nproc; free -g; df -h /
```

**这是本文建议最先做的三件事之一**（D-015）。它零成本、几分钟出结果，而且直接决定第 7 节的全部后续选择。

#### 替代 B：Vultr Bare Metal 自建 KVM

`KNOWN`：Vultr 官方文档明确说**Cloud Compute 实例上不能用 KVM 虚拟化，因为它们本身已经是虚机**；要用 KVM 虚拟化就得上 Vultr Bare Metal 或别的独立服务器（转述自 <https://docs.vultr.com/how-to-install-proxmox-virtual-environment-on-debian-11>）。

**这一句同时关掉两个幻想**：不能在 L2 的实例里再跑一层 KVM；L1 也不能"临时开一台 Vultr Cloud Compute 当构建机"。

`KNOWN`：Vultr 有官方的"在 Bare Metal 上装 Proxmox VE"文档（<https://docs.vultr.com/how-to-install-proxmox-ve-on-a-vultr-bare-metal-server>），以及"在 Bare Metal 上用自定义 ISO"文档（<https://docs.vultr.com/custom-iso-on-bare-metal>）。

`INFERRED`：netboot.xyz 的 Vultr 页面提醒 Bare Metal 要用 Legacy (PCBIOS) 的 iPXE 镜像，因为它当时不支持 EFI（来源见第 3.2 节）。**这对我们不构成问题**，因为 macOS 在这个方案里是我们自己 QEMU 里的 guest，用的是我们自己提供的 OVMF，宿主固件类型不相关。

**评估**：

| 维度 | 评价 |
|---|---|
| 能力 | 最强。设备模型完全可控，串口、host 截图、host 输入注入全部可用（`80` 第 1.7 节的全部 L1 独有能力） |
| 成本 | 按小时计费的裸金属，显著贵于 Cloud Compute。**不适合长期开着**，适合"开半天装好 golden 就关掉" |
| 复杂度 | 要装一遍 Proxmox 或裸 Debian + QEMU，官方文档齐全 |
| 与 L2 的关系 | 它**不是** L2 的替代。L2 的价值是"真实不可控宿主"，裸金属上的 KVM 是第二个 L1 |

#### 替代 C：允许嵌套虚拟化的第三方 VPS

`INFERRED`：部分厂商在普通 VPS 上开放嵌套虚拟化。第三方 CI 服务商也提供带嵌套虚拟化的 runner（例如把 `/dev/kvm` 作为一个 runner label 暴露，转述自 <https://warpbuild.com/runners/nested-virtualization>）。

**评估**：成本可能低于裸金属，但引入一个新厂商就引入一套新的未知（固件、设备模型、是否有控制台）。**只在替代 A 与 B 都不可行时考虑**，并且要先用第 7.1 节的脚本验一遍。

#### 替代 D：把 E0-L1 整个跳过，直接做 E0-L2

**这是最后的选择，代价明确。** 流程退化为第 4.1 节的 D0：开一台实例、挂 `71` 第 8.3.3 节那张 1.5 GB 的 hybrid ISO、人工经网页控制台装一次 macOS、装好后 `POST /v2/snapshots` 固化成 L2 golden。之后全部自动化。

**它付出的三样东西**：

1. **失去串口。** `80` 第 1.4 节已经论证：没有串口，early panic 不可诊断。E0 第一次就撞上黑屏的概率不低（`71` 第 7.5 节列了三个 `BLOCKED` 的固件侧未知），而黑屏之后我们只能销毁重建，拿不到任何说明原因的证据。
2. **失去 `80` 第 2.1 节提升门槛的第 1 条**（内核改动必须先过 L1）。这条规则之所以存在就是因为 L2 没有诊断能力。跳过 L1 等于把这条规则删掉。
3. **人工环节固化。** 每次需要重建 golden（换 macOS 版本、改 OpenCore 配置、换 SMBIOS）都要人再点一遍控制台。

**所以替代 D 不是"也可以"，是"只在替代 A 失败后才考虑"。** 而替代 A 的验证成本是几分钟一次 CI 运行。

### 7.5 E0-L1 的重新定义

按上面的结论，`80` 第 4.1 节的 E0-L1 验收标准不变，但**执行环境从"开发机"改为"一个有 `/dev/kvm` 的 Linux 环境，优先 GitHub Actions 的 Linux runner"**。

```text
E0-L1 的环境优先级（本文的结论）
  1. 用户的 Debian 13，若 §7.1 的检测全绿                   ← 最快的迭代循环
  2. GitHub Actions 的 ubuntu-latest runner                ← 零成本，先用 D-015 验证
  3. Vultr Bare Metal（按需开机，装完 golden 就关）          ← 有成本，能力最强
  4. 第三方带嵌套虚拟化的 VPS / CI
  5. 跳过 L1，走 D0（人工在 L2 装一次）                      ← 明确记为能力降级
```

**一条写给 harness 的要求**：`result.json` 的 `platform` 段（`80` 第 2.10.3 节）必须能表达这五种环境，而不只是 `local-qemu` / `vultr` 两个值。建议 `platform.kind` 的封闭枚举扩为 `local-qemu` / `ci-qemu` / `baremetal-qemu` / `vultr`。理由与 `80` 第 2.1 节第 4 条同源：**不同环境产出的证据不可互相冒充**，一次在 CI runner 上跑出的绿灯和一次在用户机器上跑出的绿灯，CPU 型号与内核版本都不同。

---

## 8. 未解决项清单

编号 `D-` 代表 deploy。与 `70` 的 `P-`、`71` 的 `I-`、`80` 的 `H-` 并列，互不重叠。

"查清成本"一列区分四档：**现在就能做**（读文档或跑一条本地命令）、**CI**（一次 GitHub Actions 运行，零成本）、**E0-L1**、**E0-L2**（要花钱）。

| 编号 | 事项 | 标签 | 查清方法 | 成本 | 阻塞什么 |
|---|---|---|---|---|---|
| **D-001** | Vultr 实例的系统盘在 guest 眼里是单块盘，还是 md/dm 之类的聚合设备 | `BLOCKED` | 第 4.3.2 节空跑演练的第 1 条检查：进 Alpine 后 `lsblk -rn -o NAME,TYPE`、`cat /proc/mdstat`、`dmsetup ls`。`reinstall` 的注释记录过 Vultr 上存在软 RAID 0 的 Debian 配置（第 2.7 节） | **E0-L2**，可与 D-009 同一次实例完成 | **整块 dd 的前提。** 若是聚合设备，第 4.5 节的流式写盘不成立，D1 也可能受影响 |
| **D-002** | Vultr 网页门户是否支持直接上传 ISO 文件（而非给 URL） | `INFERRED` | 读 Cloud GPU 开通文档的 ISO 段落措辞（<https://docs.vultr.com/products/compute/cloud-gpu/provisioning>），再在门户里实际看一眼有没有文件选择框 | **现在就能做** | 不阻塞任何事。只影响"要不要自建托管端点"这个判断，以及 `80` 第 1.2 节约束 1 的措辞 |
| **D-003** | `POST /v2/snapshots/create-from-url` 的体积上限 | `BLOCKED` | 两步：先查 Vultr 的 API 变更日志与快照文档有无数字；没有就上传一个 2 GB 的测试 raw，成功后再上传目标体积的真件。**不要第一次就传 24 GB** | 文档**现在就能做**；行为需 **E0-L2** | **D1 主路径的可行性。** 这是本清单里最该先查的一条 |
| **D-004** | 换平台后 guest 是否仍能靠 DHCP 拿到公网 IP | `KNOWN`（Vultr 为 DHCP）/ `BLOCKED`（其他平台） | 在目标平台开一台普通 Linux，看 `ip a` 与 `journalctl -u systemd-networkd` 是不是 DHCP 获得的地址 | 换平台时 | 换平台的可行性。在 Vultr 上已关闭 |
| **D-005** | Alpine 的 `apkovl=<HTTP URL>` 内核参数是否按预期工作，以及 overlay 内 `local.d` 脚本的执行时机 | `INFERRED` | 本地 QEMU 启一次 Alpine netboot，带 `apkovl=http://.../t.tar.gz`，overlay 里只放一个往 `/tmp` 写时间戳的 `local.d` 脚本，看它跑没跑 | **E0-L1**（或任何能跑 QEMU 的地方，不需要 macOS） | 第 4.3.1 节与第 5.1 节的 rescueOS 配置方式。失败则退回 `reinstall` 式重打 initramfs |
| **D-006** | 平台对导入的快照是否跑"单分区自动扩展"一类后处理，会不会动我们的 GPT | `BLOCKED` | 第一次 D1 部署成功后，进 macOS 或 rescue 读 GPT，与发布时的 `sgdisk -p` 输出逐项比对；特别看分区数、各分区起止 LBA、备份表位置 | **E0-L2** | 第 4.6 节瘦镜像 + 首启扩展方案的安全性。若平台会动 GPT，首启脚本可能面对一个被改过的分区表 |
| **D-007** | bootable Block Storage + VX1 是否是比常规 Cloud Compute 更好的 L2 架构 | `INFERRED` | 读 VX1 开通与克隆卷文档（第 3.1.4 节的三个链接），确认 API 侧完整流程；再开一台最小 VX1 看 `ioreg` 里的盘控制器型号（即 `80` 的 H-001 在 VX1 上的答案） | **E0-L2**，低优先级 | 只影响 L2 的架构选择。常规 Cloud Compute 跑通之后再评估 |
| **D-008** | `create-from-url` 是否接受带 query string 的预签名 URL（而非完全公开的 URL） | `INFERRED` | 用一个 2 GB 测试 raw 的预签名 URL 调一次 `create-from-url`，看 `status` 会不会变 `error`。**这是 D1 在版权上能否成立的关键** | **E0-L2**，可与 D-003 同一次完成 | **D1 的合规性。** 若只接受完全公开的 URL，D1 不能用于含 Apple 二进制的镜像，主路径必须改为 D2 |
| **D-009** | `POST /v2/instances` 只给 `ipxe_chain_url` 够不够，是否还要配某个 `os_id` | `INFERRED` | 先只给 `ipxe_chain_url` 建一台最小实例；若 400 则 `GET /v2/os` 找名字含 `Custom` 的 id 再试。用最便宜机型，1 小时计费 | **E0-L2** | 第 4.3 节 D2 路径与第 3.2 节 rescueOS 入口 |
| **D-010** | macOS 26 对一个 Linux 类型 GUID 的 ext4 分区的行为（是否试图挂载、是否提示初始化、`diskutil` 如何显示） | `INFERRED` | **E0-L1 时顺手测**：在 L1 的 golden 盘上按第 5.2 节加一个 ext4 分区，进 macOS 跑 `diskutil list`、`diskutil info disk0s2`，看有没有弹"此电脑无法读取您插入的磁盘" | **E0-L1** | 第 5.2 节的分区布局。若 macOS 反复弹窗或试图修复它，要换成一个 macOS 完全无视的类型 GUID |
| **D-011** | 能否从 macOS 里写 UEFI 全局变量 `BootNext`，以及它与 OpenCore 的 NVRAM 管理是否冲突 | `INFERRED` | L1 上在 macOS 内 `sudo nvram 8BE4DF61-93CA-11D2-AA0D-00E098032B8C:BootNext=%00%00`，重启看是否生效；同时读 `nvram -p` 确认 OpenCore 有没有把它清掉 | **E0-L1** | 第 5.3 节的次选机制。主机制（ESP 文件交换）不依赖它，所以这是优化项不是阻塞项 |
| **D-012** | Alpine 仓库里是否有可用的 APFS 只读驱动（`apfs-fuse` 一类），能否在 rescue 里读出 macOS 的 panic 报告 | `INFERRED` | `apk search apfs`；有的话在 L1 的 rescue 分区里挂一次 golden 的 APFS 容器试读 | **E0-L1** | 第 5.4 节 R1 层的取证能力。失败则第 6.1.4 节的 ESP 信箱机制成为**必需**而不是冗余 |
| **D-013** | `POST /v2/instances/{id}/iso/attach` 对一台"系统盘不可引导"的实例是否仍然有效 | `INFERRED` | 故意把一台实例的盘头写坏（dd 覆盖前 1 MiB），确认它起不来，然后 attach rescue ISO 看能不能进去 | **E0-L2**，**强烈建议在真正需要之前先演练一次** | 第 5.4 节 R2 层。这是"救砖能力"本身的验收 |
| **D-014** | 公共 ISO 库的 id 能否被 `iso/attach` 接受 | `INFERRED` | `GET /v2/iso-public` 取一个 id，对一台测试实例 attach，看返回码与 `iso_status.state` | **E0-L2**，与 D-013 同一次 | 第 5.4 节 R3b 层 |
| **D-015** | GitHub Actions 的 `ubuntu-latest` runner 上 `/dev/kvm` 是否可用、`nproc`/内存/磁盘够不够跑 macOS | `INFERRED` | 跑第 7.4 节替代 A 给的 `probe-kvm.yml`，十分钟内出结果 | **CI，零成本** | **整个第 7 节的选择。** 这是本清单里第二该先查的一条 |
| **D-016** | 托管端点的实际拉取吞吐（我们的桶 → Vultr 实例） | `BLOCKED` | 第 4.3.2 节空跑演练的第 2 条检查，`curl -r 0-1048575 -w %{speed_download}`，再用 1 GB 范围测一次稳态 | **E0-L2** | 第 4.5.2 节的耗时预算与 harness 的超时设定 |
| **D-017** | `diskutil apfs resizeContainer <phys> 0` 在 25G325 的 KVM guest 内是否可靠扩满；缩容方向能缩到多小 | `INFERRED` | L1 上对 golden 盘先缩后扩各一次，记录 `diskutil list` 的前后差异与耗时 | **E0-L1** | 第 4.6 节瘦镜像的可行性。失败则只能发布全尺寸镜像，并被钉在大盘机型上 |
| **D-018** | macOS 侧能否稳定挂载并写 ESP（`diskutil mount` + 写文件 + 卸载），SIP 关闭下是否有额外限制 | `INFERRED` | L1 上跑第 5.3.2 节的 `arm-rescue.sh`，确认文件确实落盘（重启后进 rescue 读回） | **E0-L1** | 第 5.3.2 节主机制的全部有效性。**这是 R1 层的根** |
| **D-019** | OpenCore 的 `OpenLinuxBoot.efi` + `ext4_x64.efi` 能否认出我们的 Alpine rescue 分区 | `INFERRED` | L1 上按第 5.3.3 节加两个驱动，看 OpenCore picker 里出不出 Alpine 条目 | **E0-L1**，低优先级 | 只影响 L1 的操作舒适度，不影响 L2 |
| **D-020** | 自制 Alpine rescue ISO（≈200 MB，开机即 SSH）的构建方式与实际可引导性 | `INFERRED` | 用 Alpine 官方的 `mkimage`/`alpine-make-vm-image` 一类工具造一张，先在 L1 上用 `-device ide-cd` 挂着启一次 | **E0-L1** | 第 5.4 节 R2 层与第 6.3 节的槽位分配 |
| **D-021** | TCG 下 `-cpu Skylake-Server-v4,enforce` 会不会因 AVX-512 被拒 | `INFERRED` | 一条命令：`qemu-system-x86_64 -accel tcg -cpu Skylake-Server-v4,enforce -machine q35 -m 512 -nographic`（见第 7.3 节） | **现在就能做**（任何有 QEMU 的机器） | 第 7.3 节的结论强度。不阻塞主路径 |

**优先级：先做 D-015（CI 零成本）与 D-003 + D-008（一次 E0-L2 实例就能同时回答，用最便宜机型）。** 这三条分别决定"L1 在哪跑"与"D1 主路径是否成立"。在它们出结果之前，第 4 节与第 7 节的方案选择都只是推断。

第三优先是 D-001 + D-009 + D-013 + D-014，它们可以在**同一台**最便宜的实例上一次测完：开机进 Alpine（D-009）→ 看盘的形态（D-001）→ 故意写坏盘头 → attach 自制 ISO（D-013）→ attach 公共 ISO（D-014）→ 销毁。一次 1 小时计费，关掉四条。

---

## 9. 相关分册

- **`71-IMAGE-OPENCORE.md`**：本文是它第 8.3 节的后继。本文**把它第 8.3.4 节的配方 B 从"引导介质"升级为"装好系统的瘦镜像"并定为主路径**，把第 8.3.3 节的配方 A 降级为仅用于 D0，把第 8.3.5 节的"推荐顺序 3 → 1 → 2"收紧为"只走路 3"。本文第 5.2 节要求它的 ESP 从 64 MiB 放大到 256 MiB 并容纳三个 EFI 引导器文件；第 5.3.3 节要求它的 `UEFI/Drivers` 追加 `OpenLinuxBoot.efi` 与 `ext4_x64.efi`。本文第 6.4 节给出逐项修订建议。它的 I-014 被本文第 3.1.2 节部分关闭（格式已确定为未压缩 raw），余下的体积上限转为本文 D-003。
- **`80-TEST-HARNESS.md`**：本文**补齐了它第 1 节漏掉的两条 Vultr 能力**（`ipxe_chain_url`、bootable Block Storage）与一条关键平台事实（公网 IP 由 DHCP 下发）。本文第 6.1 节明确要求修改它第 3.3.8 节的工具组（体积检查按通道判定、`kind` 增加 `system_disk`、新增 `image_stream_write` 与 `rescue_*` 工具组、`env_create` 增加 `from_ipxe`），第 6.1.4 节要求它第 2.6 节的 agent 增加 `esp_mailbox_sync` 任务、第 2.10.3 节的 `result.json` 增加 `recovery` 段。本文第 6.3 节建议改写它第 1.2 节关于 ISO 槽位分工的结论。本文第 7.5 节建议把它第 2.10.3 节的 `platform.kind` 枚举从两个值扩为四个值。本文第 5.4 节 R1 层新增的"武装 rescue"规则应写进它第 2.1 节的提升门槛。
- **`70-BUILD-PACKAGE.md`**：本文第 4.6.2 节的 `firstboot-expand` LaunchDaemon 与第 5.3.2 节的 `arm-rescue.sh` 是两个新的安装件，应进它第 6 节的安装布局与第 7 节的版本清单。
- **`00-OVERVIEW.md` 第 7 节**：本文的标签用法遵从它的四级规则。特别注意本文对 `bin456789/reinstall` 的全部结论都标在"该项目如此实现"这一层（`KNOWN`），而"因此在 25G325 + Vultr 上同样成立"始终是 `INFERRED`，这是它"标注证据来源"规则在跨项目引用上的落地方式。

### 外部来源索引

本文引用的外部内容均为转述，不作连续摘录。**内容已转述以符合许可限制。**

- `bin456789/reinstall`：<https://github.com/bin456789/reinstall>（README、`reinstall.sh`、`trans.sh`）
- Vultr Go 客户端 `govultr`：<https://github.com/vultr/govultr>（`instance.go`、`snapshot.go`、`iso.go`、`block_storage.go`）
- Vultr 快照：<https://docs.vultr.com/product-overviews/snapshots>、<https://docs.vultr.com/products/orchestration/snapshots/faq>、<https://docs.vultr.com/products/orchestration/snapshots/management/restore>、<https://docs.vultr.com/support/products/compute/can-i-downsize-a-vultr-instance-using-a-snapshot>、<https://docs.vultr.com/how-to-clone-a-vultr-cloud-compute-instance>
- Vultr ISO：<https://docs.vultr.com/products/orchestration/isos/provisioning>、<https://docs.vultr.com/product-overviews/isos>、<https://docs.vultr.com/support/products/orchestration/which-iso-files-does-vultr-support-apart-from-custom-iso>、<https://docs.vultr.com/how-to-upload-and-use-custom-isos-on-vultr>
- Vultr 重装与换 OS：<https://docs.vultr.com/products/compute/cloud-compute/management/reinstall-instance>、<https://docs.vultr.com/products/compute/bare-metal/management/change-os>、<https://docs.vultr.com/products/compute/cloud-compute/management/change-hostname>、<https://docs.vultr.com/reference/vultr-cli/instance/reinstall>
- Vultr iPXE 与 Block Storage：<https://docs.vultr.com/ipxe-boot-feature>、<https://netboot.xyz/docs/kb/providers/vultr>、<https://docs.vultr.com/products/compute/vx1-cloud-compute/provisioning>、<https://docs.vultr.com/products/cloud-storage/block-storage/block-storage-snapshot/clone-volume>、<https://docs.vultr.com/product-overviews/block-storage>
- Vultr 网络与虚拟化限制：<https://docs.vultr.com/configure-a-vultr-server-to-use-dhcp-for-dynamic-ip>、<https://docs.vultr.com/how-to-install-proxmox-virtual-environment-on-debian-11>、<https://docs.vultr.com/how-to-install-proxmox-ve-on-a-vultr-bare-metal-server>、<https://docs.vultr.com/custom-iso-on-bare-metal>
- Fedora CoreOS 在 Vultr 上的开通流程：<https://docs.fedoraproject.org/en-US/fedora-coreos/provisioning-vultr/>
- Alpine netboot：<https://boot.alpinelinux.org/>
- OpenCore 多引导：<https://dortania.github.io/OpenCore-Multiboot/oc/linux.html>
- `sgdisk` 手册：<https://manpages.debian.org/bookworm/gdisk/sgdisk.8.en.html>
- `diskutil` 手册：<https://keith.github.io/xcode-man-pages/diskutil.8.html>
- KVM 与嵌套虚拟化：<https://docs.fedoraproject.org/en-US/quick-docs/using-nested-virtualization-in-kvm/>、<https://ubuntu.com/server/docs/how-to/virtualisation/enable-nested-virtualisation/>、<https://docs.openstack.org/devstack/2023.2/guides/devstack-with-nested-kvm.html>、<https://www.cyberciti.biz/faq/installing-kvm-ok-command-on-debian-ubuntu-linux/>
- QEMU TCG：<https://qemu.org/2022/12/14/qemu-7-2-0>、<https://gitlab.com/qemu-project/qemu/-/work_items/844>、<https://wiki.gentoo.org/wiki/QEMU>
- GitHub 托管 runner：<https://docs.github.com/en/actions/reference/runners/github-hosted-runners>
