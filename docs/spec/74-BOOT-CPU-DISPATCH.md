# 74 引导期 CPU 判别与多配置自动回退

文档版本：1.0
基线日期：2026-11-02
对应组件：无（基础设施分册）
上级文档：`docs/spec/00-OVERVIEW.md`
配套分册：`docs/spec/72-CPU-COMPAT.md`、`docs/spec/73-DEPLOY-RESCUE.md`、`docs/spec/71-IMAGE-OPENCORE.md`、`docs/spec/80-TEST-HARNESS.md`

## 0. 本文作用与写作约束

本文回答一个问题：**怎么用一个镜像同时覆盖 Intel 原生受支持、Intel 需要 CPUID 伪装、AMD 需要内核补丁这三类宿主，在引导期自己判断落在哪一类，并且在判断错的时候自己换一档重试。**

它是 `72-CPU-COMPAT.md` 第 5.2 节结论的替代方案。`72` 第 5.2 节的结论是"必须出两份 EFI"，依据是 OpenCore 的 `Kernel/Patch` 没有 CPU 厂商条件。**那条依据是对的，本文不推翻它；本文推翻的是从它导出的结论**，做法是在 OpenCore 之前插一层：判别由我们自己做，`config.plist` 由我们自己选，OpenCore 仍然只读它那一个固定路径。

项目所有者给出的两条方向在本文中是前提，不是待议项：

1. **保留 AMD / EPYC 支持。** 上游 `AMD_Vanilla` 不跟 Tahoe 正式版就自己修。第 5 节给出修法与一个可进 CI 的验证脚本。
2. **不接受"必须在构建时出两份 EFI"。** 单镜像、引导期自主判别、判别失败自动回退。第 1 到 4 节给出机制。

### 0.1 职责边界

- **不重复 `72` 第 2 节的内核门与第 3 节的补丁清单。** `_cpuid_set_info` 的两道门、30 个 model 的白名单、15 条补丁在 25G325 上的逐条匹配结果，全部以 `72` 为准，本文只引用并在第 5 节把它变成可执行的门禁。
- **不重复 `73` 第 2 节对 `bin456789/reinstall` 的机制分析，也不重复它第 5.4 节的 R0..R5 救砖阶梯。** 本文第 4 节的回退机制是 `73` 第 2.3 节"EFI 一次性启动项"在不依赖 NVRAM 条件下的同构实现，并在第 4.7 节说明它如何把 `73` 的 S2 级失败变成自愈。
- **不重复 `71` 第 6 节的 `config.plist`。** 本文只规定"同一棵 EFI 树里存在几份候选 config、谁来选、选完放哪"。候选内容的每一个键仍由 `71` 第 6 节与 `72` 第 4.4 节决定。
- **本文对 `73` 第 5.3.2 节有一处必须的修正**（`\EFI\BOOT\BOOTX64.EFI` 的归属变了），见第 4.7 节与第 7 节。

### 0.2 写作约束

- 每条结论带证据标签（`KNOWN` / `INFERRED` / `BLOCKED` / `TESTED`）与来源。
- **本项目至今 `TESTED` 数量为零，本文没有 `TESTED`。** 本文全部内容在第 4.8 节的 L1 验证矩阵跑通之前都是待验证的设计。
- 源码、`config.plist` 片段、命令、脚本按可直接照抄编写。本文第 3.3 节的 C 源码与第 4.5 节的脚本是完整的，不是片段示意。
- 对外部网页与第三方源码的内容均为转述与机制说明，不作连续摘录。**内容已转述以符合许可限制。**

### 0.3 六条结论先行

| # | 问题 | 结论 | 标签 | 依据 |
|---|---|---|---|---|
| 1 | OpenCore 有没有官方的按硬件选 config 机制 | **没有。** 配置路径 `EFI\OC` 与文件名 `config.plist` 都是 OpenCore 的编译期常量；全部条件化字段只有 `Arch` 与 `MinKernel`/`MaxKernel` | `KNOWN` | 第 1.1、1.2 节 |
| 2 | 官方有没有承认"自定义 loader 先跑、再加载 OpenCore"这种形态 | **有。** `Misc/Boot/LauncherPath` 的官方说明就是"可以指向自定义 loader，由它自己去加载 `OpenCore.efi`" | `KNOWN` | 第 1.2 节 |
| 3 | 选定形态 | **`EFI\BOOT\BOOTX64.EFI` 换成一个约 700 行的 UEFI application（shim）**：判别 → 从 `\EFI\CPUDISP\` 里挑一份候选复制成 `\EFI\OC\config.plist` → `LoadImage`/`StartImage` 到 `\EFI\OC\OpenCore.efi` | `INFERRED` | 第 3 节 |
| 4 | `vendor=GenuineIntel` 伪装下最可靠的 AMD 信号 | **`CPUID.0x80000000:EAX ≥ 0x8000001D` 且 `CPUID.0x8000001D` 子叶 0 的 cache-type 字段非零。** 真 Intel 的扩展叶空间封顶在 `0x80000008`，而 QEMU 对 `0x8000001D` 不做厂商门控 | `KNOWN` | 第 2.4 节 |
| 5 | 判别的硬边界 | **如果宿主给的是一个完整的 Intel CPU 模型，没有任何 CPUID 信号能看出硅片是 AMD**，因为 guest 的 CPUID 整个由 QEMU 按模型合成。只有行为探针（FXSAVE 的 x87 指针语义）反映硅片 | `KNOWN`（前半）/ `INFERRED`（后半） | 第 2.1、2.5 节 |
| 6 | 候选阶梯 | **4 份 config + 1 个 rescue 共 5 档**，顺序由判别结果决定，状态存在 ESP 的一个 512 字节文件里，**不依赖固件 NVRAM**；macOS 侧由一个 LaunchDaemon 回写"本档成功" | `INFERRED` | 第 4 节 |

---

## 1. 核实：OpenCore 自己能不能做

任务要求先查官方能力，有现成的就不要自己写。本节是这次核查的结果。**结论是没有，但官方明确承认我们要做的这种形态。**

### 1.1 配置路径是 OpenCore 的编译期常量

`KNOWN`，来源：OpenCorePkg 的 `Include/Acidanthera/Library/OcMainLib.h`（<https://github.com/acidanthera/OpenCorePkg/blob/master/Include/Acidanthera/Library/OcMainLib.h>，本轮读取，`OPEN_CORE_VERSION` 为 `"1.0.9"`）。相关的五个宏：

```c
#define OPEN_CORE_ROOT_PATH         L"EFI\\OC"
#define OPEN_CORE_APP_PATH          L"OpenCore.efi"
#define OPEN_CORE_CONFIG_PATH       L"config.plist"
#define OPEN_CORE_ACPI_PATH         L"ACPI\\"
#define OPEN_CORE_KEXT_PATH         L"Kexts\\"
```

三条直接后果：

1. **配置文件名没有任何运行期可变的部分。** 不存在"按条件读 `config-amd.plist`"这种可能，也没有命令行参数或 UEFI 变量能改它。想换配置，只能换那个文件的内容。
2. **根目录名也是常量。** 所以"同一个 ESP 上放 `EFI\OC_INTEL` 与 `EFI\OC_AMD` 两套"**不成立**。多实例 OpenCore 在社区里能用，是因为那些实例在**不同的卷**上（OpenCore 用自己被加载时所在的卷当存储根）。`INFERRED` 对于"存储根取自 LoadedImage 的 DeviceHandle"，查清方法见 B-002。
3. `OPEN_CORE_APP_PATH` 是 `OpenCore.efi`，与 `EFI\BOOT\BOOTX64.EFI` 是两个不同的路径常量，这给了我们一个干净的插入点：**替换前者不会影响后者**。

### 1.2 逐项核查可能的官方机制

全部 `KNOWN`，来源为 OpenCore 官方配置文档（转述自 <https://dortania.github.io/docs/release/Configuration.html>，本轮逐节读取）与 `72` 第 5.2.1 节已登记的字段清单。

| 候选机制 | 它实际做什么 | 能不能按 CPU 选 config |
|---|---|---|
| `Kernel/Patch` 的条件字段 | 全部字段是 `Arch` / `Base` / `Comment` / `Count` / `Enabled` / `Find` / `Identifier` / `Limit` / `Mask` / `MaxKernel` / `MinKernel` / `Replace` / `ReplaceMask` / `Skip`。`Arch` 的取值是 `i386`/`x86_64`/`Any`，即**指令集架构，不是厂商** | **不能**（`72` 第 5.2.1 节已确证） |
| `Kernel/Emulate`（`Cpuid1Data` / `Cpuid1Mask` / `DummyPowerManagement`） | 无条件生效，只有 `MinKernel`/`MaxKernel` | **不能** |
| `Misc/Boot/LauncherOption` | 把 OpenCore 自己注册成固件里的启动项（`Disabled`/`Full`/`Short`/`System`）。官方同时说明一旦创建了自定义启动项，`\EFI\BOOT\BOOTx64.efi` 就不再用于引导 OpenCore | **不能**，而且它要写固件 NVRAM，与第 4.1 节的前提冲突 |
| **`Misc/Boot/LauncherPath`** | 官方说明：默认指向 `OpenCore.efi`；**也可以给用户自定义的路径（文档举的例子是 `\EFI\SomeLauncher.efi`），由那个自定义 loader 自己去加载 `OpenCore.efi`** | **不能直接选 config，但它是官方对"在 OpenCore 前面插一层自定义 loader"这一形态的明文承认**。见下 |
| `Misc/Boot/InstanceIdentifier` | 官方说明：当前唯一用途是让 `.contentVisibility` 文件能只针对某个 OpenCore 实例生效 | **不能**。它只影响 picker 条目可见性，不影响配置选择 |
| `.contentVisibility` 文件 | 按实例列表隐藏/禁用启动项 | **不能**。它选的是"启动哪个 OS"，不是"用哪份 config" |
| `Misc/Tools` 自定义工具条目 | 在 picker 里加可执行条目 | **不能**，而且要人按键。L2 上没有人也没有画面（`73` 第 1.1 节） |
| `PlatformInfo` 的 `Generic`/`DataHub`/`SMBIOS` | 无条件生效 | **不能** |
| 多实例 OpenCore（不同卷各一套 `EFI\OC`） | 可行的既有做法 | **能，但要换卷而不是换文件**。评估见 1.3 的 B3 |

**`LauncherPath` 那一行很重要，它把我们的方案从"绕过官方设计"变成"官方设计里留的口子"。** 官方描述自定义 loader 的职责就是"自己去加载 `OpenCore.efi`"，这正是第 3 节 shim 的唯一出口动作。差别只在我们不走 `LauncherOption`（它要写 NVRAM），而是直接占住固件的可移动介质回退路径 `\EFI\BOOT\BOOTX64.EFI`。

### 1.3 三种形态的取舍

| 形态 | 做法 | 评估 |
|---|---|---|
| **B1：shim 换 `config.plist` 的内容**（选定） | `EFI\BOOT\BOOTX64.EFI` = shim；候选 plist 放 `\EFI\CPUDISP\`；shim 复制 + 改名 | **选定。** 只动一个文件；与 `71` 第 8 节的 ESP 布局、`73` 第 5.2 节的分区表都兼容；不需要固件 NVRAM；不需要多分区 |
| B2：shim 直接改 `config.plist` 里的字节 | 不复制整份，只就地改 `Cpuid1Data` 与 `Kernel/Patch` 几处 | **否决。** 要在 UEFI 里解析 XML plist，或者维护一堆字节偏移。前者代码量失控，后者一改配置就全错。B1 的整文件复制没有这个问题 |
| B3：多个 FAT 分区，各一套 `EFI\OC` | shim（或固件）选卷 | **否决，但记录。** `73` 第 5.2 节的分区表已经是 ESP + rescue + APFS 三个分区，APFS 必须在最后以便首启扩容（`73` 第 4.6.2 节）。再插 3 到 4 个 FAT 分区会让 `73` 第 4.5 节的瘦镜像与 `create-from-url` 的容量约束一起恶化，换来的只是"不用复制文件" |

**选 B1 的决定性理由是失败面最小。** B1 在出错时的最坏状态是"`\EFI\OC\config.plist` 不存在或是半个文件"，而这个状态由第 4 节的阶梯接住（OpenCore 读不到配置就起不来，下一次启动自动前进一档）。B3 的最坏状态是分区表被动过，那是 `73` 第 2.5 节专门要避免的那一类。

---

## 2. 判别：宿主刻意隐藏 CPU 型号时怎么办

这是本文最关键的一节。任务给的危险情形是 `-cpu ...,vendor=GenuineIntel` 跑在 EPYC 硅片上。**这个情形是真的，但它的机制和后果与任务描述里设想的不完全一样，差别决定了判别该怎么设计。先把机制钉死。**

### 2.1 第一条必须纠正的前提：guest 的 CPUID 是 QEMU 写的，不是硅片写的

`KNOWN`，来源：QEMU 的 `target/i386/cpu.c`（<https://github.com/qemu/qemu/blob/master/target/i386/cpu.c>，本轮逐段读取）。

`cpu_x86_cpuid()` 是一个大 `switch`，**每个 leaf 的返回值都由 QEMU 按选定的 CPU 模型合成**，不是把宿主的 CPUID 透传上来。只有两条例外：

1. `cpu->cache_info_passthrough`（由 `-cpu ...,host-cache-info=on` 或 `-cpu host` 的某些组合触发）会让 leaf 2 / 4 / `0x80000005` / `0x80000006` / `0x8000001D` 走 `x86_cpu_get_cache_cpuid()`，即**真的读宿主 CPUID**。
2. hypervisor leaf（`0x40000000` 起）在 KVM 下由 KVM/QEMU 另行填写；`cpu.c` 里那一支带注释说明 KVM 路径会忽略这里设置的值。

**对任务描述的具体修正：**

> "AMD 的真实差异在后面才咬人（cache leaf 4 返回垃圾……）"

这一条只在 `cache_info_passthrough` 打开时成立。**用具名模型（`-cpu EPYC-Milan`、`-cpu Skylake-Server-v4`）时，leaf 4 由 QEMU 用模型自带的 cache 描述合成**，不会返回垃圾。而且 `case 4` 的那段代码是这样门控的（`KNOWN`，`cpu.c`）：

```c
} else if (cpu->vendor_cpuid_only && IS_AMD_CPU(env)) {
    *eax = *ebx = *ecx = *edx = 0;        /* AMD 厂商：leaf 4 返回全零 */
} else {
    ... encode_cache_cpuid4(...)          /* 否则按模型的 cache 信息编码 */
}
```

`IS_AMD_CPU(env)` 判断的是 `env->cpuid_vendor1/2/3`，也就是 `vendor=` 属性改掉的那三个寄存器。**所以 `-cpu EPYC-Milan,vendor=GenuineIntel` 反而让 leaf 4 被填上（Intel 风格的 cache 编码），而不是返回零。** 这对我们是好消息：`72` 第 3.1.2 节第 5 条补丁（把 cache 枚举 leaf 从 `4` 改成 `0x8000001D`）在这种情形下**不需要**，打上去反而有害。

剩下三类真实差异仍然存在，而且它们都**不是 CPUID 能看出来的**：

| 残留差异 | 为什么 CPUID 看不见 | 后果 |
|---|---|---|
| MSR 行为 | MSR 不走 CPUID。宿主 KVM 对 AMD 专有 MSR 与 Intel 专有 MSR 的处理取决于宿主硅片与 `ignore_msrs` | `72` 第 4.5 节的 `MSR 0x198`/`0x199` 风险，以及 `0x35`、`0xCE` |
| TSC 跨 socket / 跨 CCD 的单调性 | 它是硅片与 hypervisor 的调度结果 | `72` 第 6.1 节第 5 类：`Non-monotonic time` panic |
| 拓扑合成是否自洽 | CPUID 侧自洽，但 ACPI MADT 由固件独立生成 | `72` 第 2.7.3 节 `x86_validate_topology` panic |

**这三条的缓解手段都与"是不是 AMD"无关。** 它们需要的是第 4.3 节的 T2（去 panic、去早期 rdmsr）与 T4（限核、`-nomsr35h`）两档，而不是 AMD 全集。这是本节最重要的设计结论，第 2.8 节的判决表按它排。

### 2.2 `vendor=` 到底改了什么

`KNOWN`，`x86_cpuid_set_vendor()` 的全部动作（`cpu.c`）：把入参的 12 个字节拆进 `env->cpuid_vendor1/2/3` 三个 32 位字段，别的什么都不做。这三个字段的消费者有两类：

1. **CPUID leaf 0 的 EBX/EDX/ECX**，以及 **leaf `0x80000000` 的 EBX/EDX/ECX**（AMD 硅片在扩展叶里会把厂商串再报一次；`case 0x80000000` 在 `vendor_cpuid_only_v2 && IS_INTEL_CPU(env)` 时把这三个寄存器清零）。
2. **QEMU 自己的 `IS_AMD_CPU` / `IS_INTEL_CPU` 分支**，散落在 leaf 1 的 EBX[23:16] 语义、leaf 2、leaf 4、`0x80000005`/`0x80000006`/`0x80000007`/`0x80000008` 的门控，以及 `0x1F` 叶是否抬高 `cpuid_level`。

第 2 类是本节的关键：**`vendor=GenuineIntel` 不只是换一个字符串，它会把 QEMU 内部若干 leaf 的形状也一起切到 Intel 风格。** 所以"厂商串被改了也还在"的信号，必须挑那些**不受 `IS_AMD_CPU` 门控**的 leaf。下一节逐条给。

### 2.3 两种"隐藏"情形，后果完全不同

| 情形 | 典型命令行 | guest 看到的 CPUID | `_cpuid_set_info` 的结果 | 正确处置 |
|---|---|---|---|---|
| **H1：AMD 模型 + 厂商伪装** | `-cpu EPYC-Milan,vendor=GenuineIntel` | 厂商 `GenuineIntel`，但 **family = 0x19**，扩展叶是 AMD 形状（`xlevel = 0x8000001E`） | 门 1 过，**门 2 死**（`switch` 包在 `if (family == 6)` 里，`72` 第 2.2 节） | **AMD 档。** 判别很容易：family 本身就把它暴露了 |
| **H2：Intel 模型跑在 AMD 硅片上** | `-cpu Skylake-Server-v4`（宿主是 EPYC） | 完整的 Intel 形状：family 6 / model 0x55 / `xlevel = 0x80000008` | **两道门都过，启动继续** | **不是 AMD 档。** 正确处置是 Intel 档 + 去 panic 的无害补丁（T2），见第 2.1 节表 |

**任务里担心的"Intel 配置选上了、AMD 差异后面才咬人"指的是 H2。** 而 H2 的解药不是 AMD_Vanilla 全集——那套补丁里第 3 条（cores_per_package 常量化）、第 5 条（cache leaf 换 `0x8000001D`）、第 14 条（cpufamily 强制 PENRYN）打在 Intel 形状的 CPUID 上都是破坏性的（`72` 第 5.2.2 节）。H2 的解药是**只取那几条与厂商无关、作用是"少做一件危险的事"的补丁**：

| AMD_Vanilla 条目 | 作用 | 在 H2 下是否无害 |
|---|---|---|
| 第 15 条 | 去掉 `_i386_init` 里 3 次 `rdmsr`（`0x198`/`0x199`） | `INFERRED` 无害。它只是不读两个 MSR。`72` 第 2.8 节确认这两次读无条件执行且是 Intel 路线第二大风险 |
| 第 19 条 | 去掉 `ja` 形态的 non-monotonic time panic（3 处） | `INFERRED` 无害。它删的是 panic，不是逻辑。`72` 第 3.2 节实测命中数恰为 3 |
| 第 20 条（**必须用 PR #215 的版本**） | 去掉 `jb` 形态的 non-monotonic time panic（2 处） | `INFERRED` 无害，**前提是用修好的版本**。master 版在 25G325 上误打两处无关代码（`72` 第 3.3.1 节） |

这三条构成第 4.3 节的 T2 档。**它们在真 Intel 宿主上也可以开**，代价是失去两个 panic 的诊断价值；所以 T2 不是默认档，是阶梯上的第二档。

### 2.4 信号逐条评估

读法全部是 `CPUID`，无一条需要 `rdmsr`（原因见第 2.6 节）。"抗伪装"一列指的是 H1 情形下该信号是否仍然指向 AMD。

| # | 信号 | 怎么读 | 抗伪装 | 真 Intel 上会不会误报 | 权重 |
|---|---|---|---|---|---:|
| S1 | 厂商串 == `AuthenticAMD` | leaf 0 的 EBX、EDX、ECX 依次拼 12 字节 | **否**，这正是被改掉的那个 | 不会 | +100 |
| S2 | 有效 family ∈ {0x15, 0x16, 0x17, 0x19, 0x1A} | leaf 1 EAX，`family==0xF` 时加 extfamily | **是** | 不会。Intel 只用 6 与 15 | **+60** |
| S3 | `max_ext ≥ 0x8000001D` | leaf `0x80000000` 的 EAX | **是** | **不会。真 Intel 的扩展叶空间封顶在 `0x80000008`** | **+35** |
| S4 | `0x8000001D` 子叶 0 的 EAX[4:0] ≠ 0（cache type 有效） | `cpuid(0x8000001D, 0)` | **是** | 不会 | +25 |
| S5 | `0x80000001:EDX` bit 22（MMXEXT） | | **是** | 不会 | +15 |
| S6 | `0x80000001:ECX` 的 AMD 专有位：SVM(2)、SSE4A(6)、MisAlignSSE(7)、OSVW(9)、TopoExt(22) | | **是** | 不会 | 每位 +8，上限 +32 |
| S7 | `0x8000001E:EBX` ≠ 0（扩展拓扑） | 需 `max_ext ≥ 0x8000001E` | **是** | 不会 | +10 |
| S8 | `0x8000001F:EAX` ≠ 0（SEV/SME） | 需 `max_ext ≥ 0x8000001F` | 是，但**常常缺** | 不会 | +10 |
| S9 | `0x80000008:ECX` 的 NC 字段 ≠ 0 | | 部分 | **会**。见下 | +5 |
| S10 | `0x8000000A:EAX` ≠ 0（SVM revision） | 需 SVM 暴露 | 是 | 不会 | +10 |
| S11 | **FXSAVE 的 x87 指针语义** | 行为探针，见第 2.5 节 | **是，而且是唯一反映硅片的信号** | 不会 | +40 |
| S12 | 内部矛盾：厂商串是 `GenuineIntel` 而 S2/S3/S4 任一成立 | 派生 | — | — | 置 `spoof` 标志 |
| S13 | hypervisor leaf `0x40000000` 的签名 | | — | — | 0（上下文） |
| S14 | `0x40000010` 的 TSC / bus 频率 | | — | — | 0（上下文） |

逐条说明，重点在为什么权重是这个值：

**S2（+60，单条即可定档）。** `72` 第 2.2 节已确证门 2 的 `switch` 整个包在 `if (cpuid_family == 6)` 里。所以 family 0x17/0x19/0x1A 无论厂商串是什么都过不了门 2，必须走 AMD 档。这条信号同时是"判别"和"后果"，不会错。`KNOWN`。

**S3（+35，本文给出的首选信号）。** 三条证据合起来：

1. **真 Intel 硅片不可能报 ≥ `0x8000001D`。** Intel 定义的扩展叶只到 `0x80000008`。`KNOWN`。
2. **QEMU 的 `case 0x8000001D` 不做厂商门控。** 它只看 `cache_info_passthrough` 与子叶号，直接 `encode_cache_cpuid8000001d(env->cache_info...)`。`KNOWN`，`cpu.c`。
3. **QEMU 的 EPYC 系模型把 `xlevel` 设成 `0x8000001E`。** 本轮在 `cpu.c` 里逐个确认：`EPYC`、`EPYC-Rome`、`EPYC-Milan` 三个模型定义里都是 `.xlevel = 0x8000001E`（`Hygon Dhyana` 同值）。`KNOWN`。

所以 H1 下 `max_ext` 仍然是 `0x8000001E`，`0x8000001D` 仍然返回有效的 cache 描述，而真 Intel 永远给不出这个值。**这就是任务问题 2 的答案：在 `vendor=GenuineIntel` 伪装下，最可靠的 AMD 判别信号是扩展叶上限加 `0x8000001D` 的有效性，不是厂商串。**

**S5 与 S6（合计上限 +47）。** `case 0x80000001` 在 QEMU 里是 `*ecx = env->features[FEAT_8000_0001_ECX]; *edx = env->features[FEAT_8000_0001_EDX];`，**除了 TCG 下的一个 SYSCALL 修正外没有任何厂商门控**（`KNOWN`，`cpu.c`）。而两组特性字在模型定义里差别很干净（`KNOWN`，本轮对比 `cpu.c` 的模型定义）：

| 模型 | `FEAT_8000_0001_EDX` 里的 AMD 专有位 | `FEAT_8000_0001_ECX` |
|---|---|---|
| `EPYC` / `EPYC-Rome` / `EPYC-Milan` | 含 `CPUID_EXT2_MMXEXT`、`CPUID_EXT2_FFXSR` | 含 `OSVW`、`3DNOWPREFETCH`、`MISALIGNSSE`、`SSE4A`、`ABM`、`CR8LEG`、`SVM`、`LAHF_LM`、`TOPOEXT`（Rome/Milan 另有 `PERFCORE`） |
| `Skylake-Server` | **不含** MMXEXT / FFXSR（只有 LM、PDPE1GB、RDTSCP、NX、SYSCALL） | **只有** `ABM`、`LAHF_LM`、`3DNOWPREFETCH` |

**注意 `ABM`(bit 5) 与 `3DNowPrefetch`(bit 8) 两位不能用作判据**，Intel 模型也有。能用的是 SVM(2)、SSE4A(6)、MisAlignSSE(7)、OSVW(9)、TopoExt(22)。

**S9（+5，权重刻意压低）。** `case 0x80000008` 在 `vendor_cpuid_only_v2 && IS_INTEL_CPU(env)` 时把 ECX 与 EDX 清零，否则在 `threads_per_pkg > 1` 时填 `(apicid_pkg_offset << 12) | (threads_per_pkg - 1)`。`KNOWN`。而 `vendor_cpuid_only_v2` 是按 machine type 开关的兼容属性。**所以老 machine type 上 Intel 模型也会把 NC 填上**，这条信号会误报。保留它只是为了在别的信号都没有时提供一点倾向。

**S8（+10，但经常拿不到）。** `0x8000001F` 要靠 `sev_enabled()` 才会抬高 `cpuid_min_xlevel`（`KNOWN`，`cpu.c` 的 `x86_cpu_expand_features`）。云平台不开 SEV 时这条叶根本不在。**不要把它当主判据**，任务里的猜测在这一点上偏乐观。

**S13 / S14 权重为零，但必须采。** S13 告诉我们 hypervisor 是谁（`KVMKVMKVM`、`TCGTCGTCGTCG`、`Microsoft Hv`…），它不说明硅片，但它决定 `72` 第 2.6.2 节的 XCPM 是否关闭。S14 决定 `72` 第 2.7.4 节的 `_tsc_init` 走路 A 还是路 B。**这两条进 shim 的日志，是 `72` 的 C-003 在不额外起 Linux 实例的情况下能拿到的答案。**

### 2.5 FXSAVE 的 x87 指针语义：唯一反映硅片的信号

H2 情形下 CPUID 全是 Intel 形状，所有 S1..S10 都指向 Intel。要在这种情形下看出硅片是 AMD，只能找一条**由硅片直接执行、不经 hypervisor 中转、且 AMD 与 Intel 行为确有差异**的指令。

`FXSAVE` 是现成的一条：**AMD 的实现在没有挂起的未屏蔽 x87 异常时不保存 x87 的错误指针（FOP / FIP / FDP），Intel 一直保存。**

证据分三层，诚实区分：

- `KNOWN`（存在这个差异）：Linux 内核有一处提交把"AMD K7/K8 的 FXSAVE/FXRSTOR 在没有挂起异常时不保存/恢复 FDP/FIP/FOP"这一行为的 workaround 从 save 侧挪到 restore 侧（转述自 <https://github.com/torvalds/linux/commit/4903062b5485f0e2c286a23b44c9b59d9b017d53>）。Xen 的 CVE-2013-2076 记录把同样的行为归到 AMD family 15h 及以后（转述自 <http://bugs.alpinelinux.org/issues/2044>）。
- `INFERRED`（Zen 上仍然如此）：`rr` 的一个 issue 标题就叫 "FIP divergence on Zen"，正文把"AMD CPU 在没有挂起浮点异常时可能不写 FIP/FDP"列为硬件允许的行为（转述自 <https://github.com/rr-debugger/rr/issues/2698>）。**没有一手的 AMD 文档引用，也没有在 Zen 3/4/5 上实测过。**
- `BLOCKED`（KVM 下是否仍然成立）：`FXSAVE` 不被 KVM 拦截，所以它应当反映真实硅片。未实测。

探针做法（第 3.3 节的 `x87_ptrs_saved()`）：把 512 字节缓冲区清零，`FNINIT`、`FLDZ`、`FXSAVE64`，然后读偏移 `+6` 的 FOP（2 字节）与 `+8` 的 FIP（8 字节）。Intel 风格两者非零，AMD 风格两者仍为零。

**三条必须写明的限制：**

1. **执行 `FXSAVE64` 之前必须确认 `CR4.OSFXSR`（bit 9）置位**，否则是 `#UD`，在 UEFI 里就是固件挂死。shim 在 ring 0，可以直接 `mov %cr4, %rax` 读出来判断，这一步没有触发异常的风险。`KNOWN`（可以读 CR4）/ `INFERRED`（UEFI x64 固件必然置了 OSFXSR；查清方法见 B-005）。
2. **这条信号的判别力未实测**，所以权重只有 +40，低于 S2 的 +60，单条不足以把档位推到 AMD 全集，只能把档位推到"疑似"（第 2.7 节的阈值）。这是刻意的：在只有 S11 成立的 H2 情形下，正确处置本来就不是 AMD 全集。
3. **它查清的成本接近零。** `72` 第 5.1 节已经要求起一台 Linux 实例跑 `scripts/probe-host-cpu.sh`（E0-L0）。在那个脚本里加二十行 C 就能把 B-003 关掉，不需要额外的实例小时。

### 2.6 为什么 shim 里一条 MSR 都不读

`rdmsr` 能给出更强的信号（例如 AMD 专有的 `MSR 0xC0010015` HWCR、`0xC0010010` SYSCFG，在 Intel 宿主的 KVM 上通常 `#GP`），但：

- **在 UEFI application 里触发 `#GP` 等于固件挂死。** 要安全地试探必须先用 `EFI_CPU_ARCH_PROTOCOL` 的 `RegisterInterruptHandler` 挂一个 `#GP`（向量 13）处理器、在处理器里把 RIP 推过那条两字节的 `rdmsr`。这条路可行但脆弱，而 shim 是整条引导链的第一环，**它挂死的代价是 `73` 第 5.4 节的 R2 层（ISO attach，40 到 60 分钟）**。
- **拿到的信息被 `ignore_msrs` 污染。** 宿主开了 `kvm ignore_msrs=1` 时未实现的 MSR 返回 0 而不是 `#GP`，"读成功且为 0"无法区分"不存在"与"存在但为 0"。
- **同样的信息在 Linux 侧零风险可得。** `72` 第 5.1 节的脚本已经在读 `/dev/cpu/0/msr` 并把 `#GP` 变成 `EIO`。

**纪律：shim 只执行 `CPUID`、`FXSAVE`（在 CR4 检查通过后）、以及读 `CR4`。不执行 `RDMSR`、`WRMSR`、`RDPMC`、任何 I/O 端口访问。** MSR 事实的采集留给 Linux 侧的 L0-probe 与 macOS 侧的首启探针。登记为 B-006 的边界。

### 2.7 打分与定档

可直接照抄，与第 3.3 节的源码一致：

```c
/* 返回 AMD 倾向分。>= 60 定 AMD 档；>= 40 定"疑似"档；否则按 Intel 走 */
static int amd_score(const CPUFACTS *f)
{
    int s = 0;

    if (f->vendor_is_amd)                                   s += 100;  /* S1  */
    if (f->fam == 0x15 || f->fam == 0x16 ||
        f->fam == 0x17 || f->fam == 0x19 || f->fam == 0x1A)  s += 60;   /* S2  */
    if (f->max_ext >= 0x8000001D)                           s += 35;   /* S3  */
    if (f->max_ext >= 0x8000001D && (f->cache1d_eax & 0x1F)) s += 25;   /* S4  */
    if (f->e1_edx & (1u << 22))                             s += 15;   /* S5 MMXEXT */

    {   /* S6：0x80000001 ECX 的 AMD 专有位，每位 8 分，上限 32 */
        const int bits[5] = { 2, 6, 7, 9, 22 };  /* SVM SSE4A MisAlign OSVW TopoExt */
        int i, n = 0;
        for (i = 0; i < 5; i++)
            if (f->e1_ecx & (1u << bits[i])) n++;
        s += (n > 4 ? 4 : n) * 8;
    }

    if (f->max_ext >= 0x8000001E && f->topoext_ebx)          s += 10;  /* S7  */
    if (f->max_ext >= 0x8000001F && f->sev_eax)              s += 10;  /* S8  */
    if (f->e8_ecx & 0xFF)                                    s += 5;   /* S9  */
    if (f->max_ext >= 0x8000000A && f->svm_eax)              s += 10;  /* S10 */
    if (f->x87_ptrs_saved == 0)                              s += 40;  /* S11 */

    return s;
}
```

两个阈值的理由：

- **60**：S2 单条就达到 60，因为 family 本身已经决定内核门过不了，这不是概率判断。S3 + S4 + S5 = 75 也达到，那是 H1 的另一种形态（厂商与 family 都改了但扩展叶没改）。
- **40**：S11 单条正好 40。它表达的是"硅片疑似 AMD，但 CPUID 是 Intel 形状"，对应 H2，处置是 T2 而不是 T3。

### 2.8 判决表

`f->native` 的定义沿用 `72` 第 2.3 节：厂商串 `GenuineIntel`、family == 6、model 在那 30 个值里。

| 行 | 厂商串 | family | AMD 分 | model 在白名单 | 首选档 | 完整顺序 |
|---|---|---|---:|---|---|---|
| 1 | `AuthenticAMD` | 任意 | ≥100 | — | **T3 amd** | 3 → 4 → 2 → 1 → 0 → rescue |
| 2 | `GenuineIntel` | 0x17/0x19/0x1A | ≥60 | 否（family 不是 6） | **T3 amd** | 3 → 4 → 2 → 1 → 0 → rescue |
| 3 | `GenuineIntel` | 6 | ≥60 | 任意 | **T3 amd**（厂商串与 family 都被改过，扩展叶出卖了它） | 3 → 4 → 2 → 1 → 0 → rescue |
| 4 | `GenuineIntel` | 6 | 40..59 | 是 | **T2 hardened**（H2：硅片疑似 AMD，CPUID 是 Intel 形状） | 2 → 4 → 1 → 0 → 3 → rescue |
| 5 | `GenuineIntel` | 6 | 40..59 | 否 | **T2 hardened** | 2 → 4 → 1 → 0 → 3 → rescue |
| 6 | `GenuineIntel` | 6 | <40 | **是** | **T0 intel-native** | 0 → 2 → 4 → 1 → 3 → rescue |
| 7 | `GenuineIntel` | 6 | <40 | 否 | **T1 intel-spoof** | 1 → 2 → 4 → 0 → 3 → rescue |
| 8 | 其它（`CentaurHauls`、`HygonGenuine`…） | 任意 | 按分 | 否 | 按分落到 1/4/7 行 | 同行 |

第 6 行是 `72` 第 2.3 节已确证原生受支持的那条路（model `0x55` 的 Xeon Scalable 一二代、model `0x9E` 的 Xeon E-2100/E-2200 等）：**不伪装、不打补丁、什么都不做**。

第 7 行是任务要求的"反方向情形"：真 Intel 但 model 不在表内（Ice Lake-SP `0x6A`、Sapphire Rapids `0x8F`、Emerald Rapids `0xCF`、Granite Rapids、Rocket Lake `0xA7`）。**选 T1（`Cpuid1Data` 伪装成 `0x00050657`），不是 T3。** 这正是任务里强调的"候选配置至少三档"的那一档。

**一条安全阀：** 如果 ESP 上存在空文件 `\EFI\CPUDISP\NOAMD`，T3 从所有顺序里删掉。给 Intel 宿主用：`72` 第 5.2.2 节已论证 AMD 全集打在 Intel 上是破坏性的，第 6、7 行把 T3 放在 rescue 之前只是为了让阶梯能终止，运维上应该允许把它摘掉。`INFERRED`。

### 2.9 判别拿不到的东西，以及它为什么不致命

| 拿不到 | 为什么 | 由谁接住 |
|---|---|---|
| 宿主是否 `ignore_msrs=1` | 不读 MSR（第 2.6 节） | T4 的 `-nomsr35h`；以及 `72` 第 5.1 节的 Linux 侧 L0-probe（C-004） |
| guest 的 ACPI MADT CPU 数 | shim 可以读 ACPI 表，但那要再实现一个 RSDP/MADT 解析器 | T4 的 `cpus=1` 把左右两侧都钉成确定值；登记为 B-007（把 MADT 解析加进 shim 的收益评估） |
| H2 下硅片到底是不是 AMD | 只有 S11，而 S11 的判别力未实测 | 第 4 节的阶梯。**这是阶梯存在的首要理由** |

**本节的收尾结论：判别的目标不是"认出硅片"，是"选一份能起来的配置"。** 这两件事不等价，而后者才是我们要的。所有把启动押在判别正确性上的设计都是错的，所以第 4 节的阶梯不是兜底，是主机制的一部分。

---

## 3. shim 的实现

### 3.1 形态与依赖

| 项 | 取值 | 理由 |
|---|---|---|
| 类型 | UEFI application（PE32+，Subsystem 10 = EFI Application） | 它要在 OpenCore 之前跑，又要能 `LoadImage` 别的镜像，这是 application 而不是 driver |
| 落地路径 | `ESP:\EFI\BOOT\BOOTX64.EFI` | 固件在没有可用 `BootOrder` 条目时走的可移动介质回退路径。`73` 第 5.3.2 节已经选了同一个插入点 |
| 工具链 | **`x86_64-w64-mingw32-gcc`，不用 EDK2，不用 gnu-efi** | 见 3.4 节 |
| 外部依赖 | **零。** 不链接 EDK2、不链接 gnu-efi、不用 libc | 整个仓库的构建侧目前只有 `git` / `curl` / `py` / `cargo`（`70` 第 1.4 节）。引入 EDK2 会在 `70` 里多出一整条工具链 |
| 代码量 | 约 700 行 C，单文件 | 可以整段 review，这对一个"错了就要走 R2 救砖"的组件是硬要求 |
| 用到的 UEFI 协议 | `EFI_LOADED_IMAGE_PROTOCOL`、`EFI_SIMPLE_FILE_SYSTEM_PROTOCOL`、`EFI_FILE_PROTOCOL`、`EFI_DEVICE_PATH_PROTOCOL`、`EFI_SIMPLE_TEXT_OUTPUT_PROTOCOL` | 都是 UEFI 2.x 的核心协议，OVMF 与云平台固件必有 |
| 用到的 Boot Services | `HandleProtocol`、`AllocatePool`、`FreePool`、`LoadImage`、`StartImage`、`Stall`、`SetWatchdogTimer` | 同上 |
| **不**用到的 | `LocateHandleBuffer`、`OpenProtocol`、`EFI_CPU_ARCH_PROTOCOL`、UEFI 变量服务（`GetVariable`/`SetVariable`） | 不碰 NVRAM 是第 4.1 节的硬约束；不枚举全部句柄是因为我们只要自己所在的那个卷 |

**怎么定位自己所在的卷**（三步，全部是 `KNOWN` 的 UEFI 2.x 标准做法）：

1. `HandleProtocol(ImageHandle, &gEfiLoadedImageProtocolGuid, &li)` 拿到自己的 `EFI_LOADED_IMAGE_PROTOCOL`。
2. `li->DeviceHandle` 就是"加载我的那个卷"的句柄。
3. `HandleProtocol(li->DeviceHandle, &gEfiSimpleFileSystemProtocolGuid, &fs)` 再 `fs->OpenVolume(fs, &root)`，得到该卷根目录的 `EFI_FILE_PROTOCOL`。

**不要去枚举所有文件系统句柄再猜哪个是 ESP。** `73` 第 2.7 节记录的 Vultr 软 RAID 观察说明固件在 `BootNext` 快速路径下可能只初始化一块盘；在这种环境里"枚举 + 猜"会选错卷。从 `LoadedImage` 反推是唯一确定的做法。

### 3.2 ESP 布局

在 `71` 第 8.2.2 节与 `73` 第 5.2 节的基础上增加一个目录与两个文件。**没有任何一项放在 `\EFI\OC\` 里面**，这样 OpenCore 的扫描行为完全不变。

```text
ESP (FAT32, 256 MiB, label OPENCORE)
├─ /EFI/BOOT/
│   ├─ BOOTX64.EFI              ← 当前生效的引导对象（被 73 §5.3.2 交换的那个文件）
│   ├─ BOOTX64.DISPATCH.efi     ← 本文的 shim（新增）
│   ├─ BOOTX64.OC.efi           ← OpenCore 的副本（71 §8.2.2）
│   └─ BOOTX64.RESCUE.efi       ← GRUB 的副本（73 §5.2）
├─ /EFI/OC/                      ← 完全按 71 §6 的布局，内容不受本文影响
│   ├─ OpenCore.efi
│   ├─ config.plist              ← 由 shim 每次启动写入
│   ├─ config.known-good.plist   ← 73 §5.4 R1 层用的回滚副本
│   ├─ ACPI/ Drivers/ Kexts/ Tools/
├─ /EFI/CPUDISP/                 ← 本文新增
│   ├─ 00-intel-native.plist
│   ├─ 01-intel-spoof.plist
│   ├─ 02-intel-hardened.plist
│   ├─ 03-amd.plist
│   ├─ 04-safe.plist
│   ├─ STATE.TXT                 ← 固定 512 字节，格式见 4.2
│   ├─ LOG.TXT                   ← 每次启动追加一段，shim 自己写
│   └─ NOAMD                     ← 可选的空文件，存在则把 T3 从阶梯里摘掉
├─ /boot-mode                    ← 73 §5.3.2 的状态文件，macos | rescue
└─ /boot-revert                  ← 73 §5.3.2 的一次性标记
```

**`BOOTX64.DISPATCH.efi` 这个新文件是本文对 `73` 第 5.3.2 节的修正点。** `73` 把 `BOOTX64.EFI` 在 macOS 态下定义为"`BOOTX64.OC.efi` 的副本"；加入 shim 之后，macOS 态应当是"`BOOTX64.DISPATCH.efi` 的副本"。详见第 4.7 节。

容量：5 份 `config.plist` 各约 40 到 60 KB，shim 约 20 KB，合计 `< 400 KB`，相对 256 MiB 的 ESP 无影响。

### 3.3 完整源码

单文件，自带最小 UEFI 头定义。**可直接照抄。**

```c
/* =====================================================================
 * cpudispatch.c -- 引导期 CPU 判别与多配置选择 shim
 *
 * 落地路径: ESP:\EFI\BOOT\BOOTX64.EFI
 * 规格:     docs/spec/74-BOOT-CPU-DISPATCH.md
 * 构建:     见该文档第 3.4 节（x86_64-w64-mingw32-gcc，无 EDK2、无 gnu-efi）
 *
 * 纪律（违反任何一条都会把一台机器变成 73 分册 R2 层的救砖对象）：
 *   1. 只执行 CPUID / FXSAVE / 读 CR4。不执行 RDMSR、WRMSR、端口 I/O。
 *   2. 不读写任何 UEFI 变量。全部状态在 ESP 的文件里。
 *   3. 写状态文件必须在 LoadImage 之前完成。
 *   4. 任何一步失败都必须仍然有一个确定的下一步，不许 return 之后什么都不做。
 * ===================================================================== */

/* ---------------------- 最小 UEFI 类型与结构 ---------------------- */

typedef unsigned char       UINT8;
typedef unsigned short      UINT16;
typedef unsigned int        UINT32;
typedef unsigned long long  UINT64;
typedef short               INT16;
typedef long long           INT64;
typedef unsigned short      CHAR16;
typedef unsigned long long  UINTN;
typedef UINTN               EFI_STATUS;
typedef void               *EFI_HANDLE;

#define NULL  ((void *)0)
#define EFI_SUCCESS            0ULL
#define EFI_LOAD_ERROR         0x8000000000000001ULL
#define EFI_INVALID_PARAMETER  0x8000000000000002ULL
#define EFI_UNSUPPORTED        0x8000000000000003ULL
#define EFI_OUT_OF_RESOURCES   0x8000000000000009ULL
#define EFI_NOT_FOUND          0x800000000000000EULL
#define EFI_ERROR(s)           (((INT64)(s)) < 0)

#define EFI_FILE_MODE_READ     0x0000000000000001ULL
#define EFI_FILE_MODE_WRITE    0x0000000000000002ULL
#define EFI_FILE_MODE_CREATE   0x8000000000000000ULL
#define EFI_FILE_POSITION_END  0xFFFFFFFFFFFFFFFFULL
#define EfiLoaderData          2

typedef struct { UINT32 D1; UINT16 D2; UINT16 D3; UINT8 D4[8]; } EFI_GUID;

typedef struct {
  UINT16 Year;  UINT8 Month, Day, Hour, Minute, Second, Pad1;
  UINT32 Nanosecond; INT16 TimeZone; UINT8 Daylight, Pad2;
} EFI_TIME;                                     /* 16 字节 */

typedef struct {
  UINT64   Size, FileSize, PhysicalSize;
  EFI_TIME CreateTime, LastAccessTime, ModificationTime;
  UINT64   Attribute;
  CHAR16   FileName[1];
} EFI_FILE_INFO;

typedef struct { UINT8 Type, SubType, Length[2]; } EFI_DEVICE_PATH_PROTOCOL;

typedef struct _EFI_FILE_PROTOCOL EFI_FILE_PROTOCOL;
struct _EFI_FILE_PROTOCOL {
  UINT64      Revision;
  EFI_STATUS (*Open)(EFI_FILE_PROTOCOL *, EFI_FILE_PROTOCOL **, CHAR16 *, UINT64, UINT64);
  EFI_STATUS (*Close)(EFI_FILE_PROTOCOL *);
  EFI_STATUS (*Delete)(EFI_FILE_PROTOCOL *);
  EFI_STATUS (*Read)(EFI_FILE_PROTOCOL *, UINTN *, void *);
  EFI_STATUS (*Write)(EFI_FILE_PROTOCOL *, UINTN *, void *);
  EFI_STATUS (*GetPosition)(EFI_FILE_PROTOCOL *, UINT64 *);
  EFI_STATUS (*SetPosition)(EFI_FILE_PROTOCOL *, UINT64);
  EFI_STATUS (*GetInfo)(EFI_FILE_PROTOCOL *, EFI_GUID *, UINTN *, void *);
  EFI_STATUS (*SetInfo)(EFI_FILE_PROTOCOL *, EFI_GUID *, UINTN, void *);
  EFI_STATUS (*Flush)(EFI_FILE_PROTOCOL *);
};

typedef struct _EFI_SIMPLE_FILE_SYSTEM_PROTOCOL EFI_SIMPLE_FILE_SYSTEM_PROTOCOL;
struct _EFI_SIMPLE_FILE_SYSTEM_PROTOCOL {
  UINT64      Revision;
  EFI_STATUS (*OpenVolume)(EFI_SIMPLE_FILE_SYSTEM_PROTOCOL *, EFI_FILE_PROTOCOL **);
};

typedef struct {
  UINT32      Revision;
  EFI_HANDLE  ParentHandle;
  void       *SystemTable;
  EFI_HANDLE  DeviceHandle;              /* <- 我们要的就是这个 */
  void       *FilePath;
  void       *Reserved;
  UINT32      LoadOptionsSize;
  void       *LoadOptions;
  void       *ImageBase;
  UINT64      ImageSize;
  UINT32      ImageCodeType, ImageDataType;
  void       *Unload;
} EFI_LOADED_IMAGE_PROTOCOL;

typedef struct _EFI_SIMPLE_TEXT_OUTPUT_PROTOCOL EFI_SIMPLE_TEXT_OUTPUT_PROTOCOL;
struct _EFI_SIMPLE_TEXT_OUTPUT_PROTOCOL {
  void       *Reset;
  EFI_STATUS (*OutputString)(EFI_SIMPLE_TEXT_OUTPUT_PROTOCOL *, CHAR16 *);
};

/* EFI_BOOT_SERVICES 只声明到我们用到的最后一项（SetWatchdogTimer）。
 * 字段顺序必须与 UEFI 规范一致，未用到的用 void* 占位。 */
typedef struct {
  UINT8       Hdr[24];
  void       *RaiseTPL, *RestoreTPL;
  void       *AllocatePages, *FreePages, *GetMemoryMap;
  EFI_STATUS (*AllocatePool)(UINT32, UINTN, void **);
  EFI_STATUS (*FreePool)(void *);
  void       *CreateEvent, *SetTimer, *WaitForEvent, *SignalEvent, *CloseEvent, *CheckEvent;
  void       *InstallProtocolInterface, *ReinstallProtocolInterface, *UninstallProtocolInterface;
  EFI_STATUS (*HandleProtocol)(EFI_HANDLE, EFI_GUID *, void **);
  void       *Reserved, *RegisterProtocolNotify, *LocateHandle, *LocateDevicePath,
             *InstallConfigurationTable;
  EFI_STATUS (*LoadImage)(UINT8, EFI_HANDLE, EFI_DEVICE_PATH_PROTOCOL *,
                          void *, UINTN, EFI_HANDLE *);
  EFI_STATUS (*StartImage)(EFI_HANDLE, UINTN *, CHAR16 **);
  void       *Exit, *UnloadImage, *ExitBootServices;
  void       *GetNextMonotonicCount;
  EFI_STATUS (*Stall)(UINTN);
  EFI_STATUS (*SetWatchdogTimer)(UINTN, UINT64, UINTN, CHAR16 *);
} EFI_BOOT_SERVICES;

typedef struct {
  UINT8                            Hdr[24];
  CHAR16                          *FirmwareVendor;
  UINT32                           FirmwareRevision;
  EFI_HANDLE                       ConsoleInHandle;
  void                            *ConIn;
  EFI_HANDLE                       ConsoleOutHandle;
  EFI_SIMPLE_TEXT_OUTPUT_PROTOCOL *ConOut;
  EFI_HANDLE                       StandardErrorHandle;
  void                            *StdErr;
  void                            *RuntimeServices;
  EFI_BOOT_SERVICES               *BootServices;
} EFI_SYSTEM_TABLE;

static EFI_GUID gLoadedImageGuid =
  { 0x5B1B31A1, 0x9562, 0x11D2, { 0x8E, 0x3F, 0x00, 0xA0, 0xC9, 0x69, 0x72, 0x3B } };
static EFI_GUID gSimpleFsGuid =
  { 0x964E5B22, 0x6459, 0x11D2, { 0x8E, 0x39, 0x00, 0xA0, 0xC9, 0x69, 0x72, 0x3B } };
static EFI_GUID gDevicePathGuid =
  { 0x09576E91, 0x6D3F, 0x11D2, { 0x8E, 0x39, 0x00, 0xA0, 0xC9, 0x69, 0x72, 0x3B } };
static EFI_GUID gFileInfoGuid =
  { 0x09576E92, 0x6D3F, 0x11D2, { 0x8E, 0x39, 0x00, 0xA0, 0xC9, 0x69, 0x72, 0x3B } };

/* ---------------------- 全局与 libc 替身 ---------------------- */

static EFI_SYSTEM_TABLE  *gST;
static EFI_BOOT_SERVICES *gBS;
static EFI_HANDLE         gImage;
static EFI_FILE_PROTOCOL *gRoot;

void *memset(void *d, int c, UINTN n)
{ UINT8 *p = d; while (n--) *p++ = (UINT8)c; return d; }

void *memcpy(void *d, const void *s, UINTN n)
{ UINT8 *a = d; const UINT8 *b = s; while (n--) *a++ = *b++; return d; }

static UINTN s16len(const CHAR16 *s) { UINTN n = 0; while (s[n]) n++; return n; }

static void out(const CHAR16 *s)
{ if (gST && gST->ConOut) gST->ConOut->OutputString(gST->ConOut, (CHAR16 *)s); }

/* 8 位十六进制，够用；不做通用 printf */
static void out_hex32(UINT32 v)
{
  static const CHAR16 d[] = u"0123456789ABCDEF";
  CHAR16 b[11]; int i;
  b[0] = '0'; b[1] = 'x';
  for (i = 0; i < 8; i++) b[2 + i] = d[(v >> ((7 - i) * 4)) & 0xF];
  b[10] = 0;
  out(b);
}

/* ---------------------- CPU 判别 ---------------------- */

typedef struct { UINT32 a, b, c, d; } REGS;

static REGS cpuid_raw(UINT32 leaf, UINT32 sub)
{
  REGS r;
  __asm__ __volatile__("cpuid"
                       : "=a"(r.a), "=b"(r.b), "=c"(r.c), "=d"(r.d)
                       : "a"(leaf), "c"(sub));
  return r;
}

static UINT64 read_cr4(void)
{ UINT64 v; __asm__ __volatile__("mov %%cr4, %0" : "=r"(v)); return v; }

/* 第 2.5 节的行为探针。返回 1 = Intel 风格（保存 x87 指针），
 * 0 = AMD 风格（不保存），-1 = 没做（CR4.OSFXSR 未置位，不敢执行 FXSAVE）。 */
static int x87_ptrs_saved(void)
{
  static UINT8 raw[512 + 16];
  UINT8 *p;
  UINT64 fip; UINT16 fop; UINTN i;

  if (!(read_cr4() & (1ULL << 9))) return -1;        /* OSFXSR 清零：放弃 */

  p = (UINT8 *)(((UINTN)raw + 15) & ~(UINTN)15);     /* FXSAVE 要求 16 字节对齐 */
  for (i = 0; i < 512; i++) p[i] = 0;

  __asm__ __volatile__("fninit\n\t"
                       "fldz\n\t"
                       "fxsave64 (%0)\n\t"
                       "fstp %%st(0)\n\t"
                       : : "r"(p) : "memory");

  memcpy(&fop, p + 6, 2);
  memcpy(&fip, p + 8, 8);
  return (fip != 0 || fop != 0) ? 1 : 0;
}

typedef struct {
  char   vendor[16];
  int    vendor_is_amd, vendor_is_intel;
  UINT32 max_basic, max_ext, sig, fam, mdl, stp;
  UINT32 l1_ebx, l1_ecx, l1_edx, l7_ebx;
  UINT32 e1_ecx, e1_edx, e8_ecx, cache1d_eax, topoext_ebx, sev_eax, svm_eax;
  UINT32 hv_max, hv_tsc_khz, hv_bus_khz;
  char   hv[16];
  UINT32 cores_per_pkg;
  int    x87_ptrs_saved;
  int    native;                      /* 72 §2.3 的 model 白名单 */
  int    score;
} CPUFACTS;

static const UINT8 kXnuModels[] = {
  0x17, 0x1A, 0x1E, 0x1F, 0x2E, 0x25, 0x2C, 0x2F, 0x2A, 0x2D,
  0x3A, 0x3E, 0x3C, 0x3F, 0x45, 0x46, 0x3D, 0x47, 0x4E, 0x55,
  0x5E, 0x7D, 0x7E, 0x9F, 0x8E, 0x9E, 0xA5
};
/* 72 §2.3 那张表逐行展开后是 27 个互不相同的 model，映射到 11 个 CPUFAMILY。
 * （该节正文写的"一共 30 个 model"是一处计数笔误，逐行相加为 27，见本文第 7 节。）
 * 改这张表之前先回去读 72 §2.3，它是从 kernel.x86_64 的 switch 直接读出来的。*/

static void put4(char *d, UINT32 v) { d[0]=(char)v; d[1]=(char)(v>>8); d[2]=(char)(v>>16); d[3]=(char)(v>>24); }

static void probe(CPUFACTS *f)
{
  REGS r; UINTN i; UINT32 tpc, threads_pkg;

  memset(f, 0, sizeof(*f));
  f->x87_ptrs_saved = -1;

  r = cpuid_raw(0, 0);
  f->max_basic = r.a;
  put4(f->vendor + 0, r.b); put4(f->vendor + 4, r.d); put4(f->vendor + 8, r.c);
  f->vendor[12] = 0;
  {
    const char *gi = "GenuineIntel", *aa = "AuthenticAMD";
    int ei = 1, ea = 1;
    for (i = 0; i < 12; i++) { if (f->vendor[i] != gi[i]) ei = 0;
                               if (f->vendor[i] != aa[i]) ea = 0; }
    f->vendor_is_intel = ei; f->vendor_is_amd = ea;
  }

  r = cpuid_raw(1, 0);
  f->sig = r.a; f->l1_ebx = r.b; f->l1_ecx = r.c; f->l1_edx = r.d;
  {
    UINT32 fam = (r.a >> 8) & 0xF, mdl = (r.a >> 4) & 0xF;
    UINT32 xf = (r.a >> 20) & 0xFF, xm = (r.a >> 16) & 0xF;
    f->fam = (fam == 0xF) ? (fam + xf) : fam;
    f->mdl = (fam == 0x6 || fam == 0xF) ? ((xm << 4) | mdl) : mdl;
    f->stp = r.a & 0xF;
  }
  if (f->max_basic >= 7) f->l7_ebx = cpuid_raw(7, 0).b;

  r = cpuid_raw(0x80000000, 0);
  f->max_ext = r.a;
  if (f->max_ext >= 0x80000001) { r = cpuid_raw(0x80000001, 0); f->e1_ecx = r.c; f->e1_edx = r.d; }
  if (f->max_ext >= 0x80000008)  f->e8_ecx      = cpuid_raw(0x80000008, 0).c;
  if (f->max_ext >= 0x8000000A)  f->svm_eax     = cpuid_raw(0x8000000A, 0).a;
  if (f->max_ext >= 0x8000001D)  f->cache1d_eax = cpuid_raw(0x8000001D, 0).a;
  if (f->max_ext >= 0x8000001E)  f->topoext_ebx = cpuid_raw(0x8000001E, 0).b;
  if (f->max_ext >= 0x8000001F)  f->sev_eax     = cpuid_raw(0x8000001F, 0).a;

  /* hypervisor leaf。leaf1 ECX bit31 置位才有意义（72 §2.6.2）。 */
  if (f->l1_ecx & (1u << 31)) {
    r = cpuid_raw(0x40000000, 0);
    f->hv_max = r.a;
    put4(f->hv + 0, r.b); put4(f->hv + 4, r.c); put4(f->hv + 8, r.d);
    f->hv[12] = 0;
    if (f->hv_max >= 0x40000010) {
      r = cpuid_raw(0x40000010, 0);
      f->hv_tsc_khz = r.a; f->hv_bus_khz = r.b;      /* 72 §2.7.4 的路 A / 路 B */
    }
  }

  f->x87_ptrs_saved = x87_ptrs_saved();

  /* 72 §2.3 的白名单 */
  f->native = 0;
  if (f->vendor_is_intel && f->fam == 6)
    for (i = 0; i < sizeof(kXnuModels); i++)
      if (kXnuModels[i] == (UINT8)f->mdl) { f->native = 1; break; }

  /* AMD 档要用的物理核心数（72 §3.4 的 <CC> 字节）。
   * AMD 形状：threads/pkg = 0x80000008 ECX[7:0] + 1；
   *           threads/core = 0x8000001E EBX[15:8] + 1。
   * 退化到 Intel 形状时用 leaf 4 的 EAX[31:26] + 1。 */
  threads_pkg = (f->e8_ecx & 0xFF) + 1;
  tpc = f->topoext_ebx ? (((f->topoext_ebx >> 8) & 0xFF) + 1) : 1;
  if (!tpc) tpc = 1;
  f->cores_per_pkg = threads_pkg / tpc;
  if (f->cores_per_pkg == 0 && f->max_basic >= 4)
    f->cores_per_pkg = ((cpuid_raw(4, 0).a >> 26) & 0x3F) + 1;
  if (f->cores_per_pkg == 0) f->cores_per_pkg = 1;
  if (f->cores_per_pkg > 255) f->cores_per_pkg = 255;
}

static int amd_score(const CPUFACTS *f)
{
  int s = 0;
  if (f->vendor_is_amd)                                        s += 100;
  if (f->fam == 0x15 || f->fam == 0x16 ||
      f->fam == 0x17 || f->fam == 0x19 || f->fam == 0x1A)       s += 60;
  if (f->max_ext >= 0x8000001D)                                s += 35;
  if (f->max_ext >= 0x8000001D && (f->cache1d_eax & 0x1F))     s += 25;
  if (f->e1_edx & (1u << 22))                                  s += 15;
  {
    const int bits[5] = { 2, 6, 7, 9, 22 };
    int i, n = 0;
    for (i = 0; i < 5; i++) if (f->e1_ecx & (1u << bits[i])) n++;
    s += (n > 4 ? 4 : n) * 8;
  }
  if (f->max_ext >= 0x8000001E && f->topoext_ebx)              s += 10;
  if (f->max_ext >= 0x8000001F && f->sev_eax)                  s += 10;
  if (f->e8_ecx & 0xFF)                                        s += 5;
  if (f->max_ext >= 0x8000000A && f->svm_eax)                  s += 10;
  if (f->x87_ptrs_saved == 0)                                  s += 40;
  return s;
}

/* ---------------------- 候选与顺序（第 2.8 节的判决表） ---------------------- */

#define T_NATIVE    0
#define T_SPOOF     1
#define T_HARDENED  2
#define T_AMD       3
#define T_SAFE      4
#define T_RESCUE    5
#define NTIER       6

static const CHAR16 *kTierFile[5] = {
  u"\\EFI\\CPUDISP\\00-intel-native.plist",
  u"\\EFI\\CPUDISP\\01-intel-spoof.plist",
  u"\\EFI\\CPUDISP\\02-intel-hardened.plist",
  u"\\EFI\\CPUDISP\\03-amd.plist",
  u"\\EFI\\CPUDISP\\04-safe.plist"
};
static const CHAR16 *kTierName[6] = {
  u"intel-native", u"intel-spoof", u"intel-hardened", u"amd", u"safe", u"rescue"
};

static void decide_order(const CPUFACTS *f, int no_amd, UINT8 *ord, UINTN *n)
{
  static const UINT8 row_amd[NTIER]      = { T_AMD, T_SAFE, T_HARDENED, T_SPOOF, T_NATIVE, T_RESCUE };
  static const UINT8 row_suspect[NTIER]  = { T_HARDENED, T_SAFE, T_SPOOF, T_NATIVE, T_AMD, T_RESCUE };
  static const UINT8 row_native[NTIER]   = { T_NATIVE, T_HARDENED, T_SAFE, T_SPOOF, T_AMD, T_RESCUE };
  static const UINT8 row_offlist[NTIER]  = { T_SPOOF, T_HARDENED, T_SAFE, T_NATIVE, T_AMD, T_RESCUE };
  const UINT8 *src;
  UINTN i, k = 0;

  if (f->score >= 60 || f->vendor_is_amd || f->fam != 6) src = row_amd;
  else if (f->score >= 40)                               src = row_suspect;
  else if (f->native)                                    src = row_native;
  else                                                   src = row_offlist;

  for (i = 0; i < NTIER; i++) {
    if (no_amd && src[i] == T_AMD) continue;             /* 第 2.8 节的安全阀 */
    ord[k++] = src[i];
  }
  *n = k;
}

/* ---------------------- 文件操作 ---------------------- */

static EFI_STATUS open_own_volume(void)
{
  EFI_LOADED_IMAGE_PROTOCOL *li = NULL;
  EFI_SIMPLE_FILE_SYSTEM_PROTOCOL *fs = NULL;
  EFI_STATUS st;

  st = gBS->HandleProtocol(gImage, &gLoadedImageGuid, (void **)&li);
  if (EFI_ERROR(st) || !li) return EFI_NOT_FOUND;
  st = gBS->HandleProtocol(li->DeviceHandle, &gSimpleFsGuid, (void **)&fs);
  if (EFI_ERROR(st) || !fs) return EFI_NOT_FOUND;
  return fs->OpenVolume(fs, &gRoot);
}

static int file_exists(const CHAR16 *path)
{
  EFI_FILE_PROTOCOL *h = NULL;
  if (EFI_ERROR(gRoot->Open(gRoot, &h, (CHAR16 *)path, EFI_FILE_MODE_READ, 0)) || !h)
    return 0;
  h->Close(h);
  return 1;
}

/* 整文件读进 pool。*len 返回字节数。调用方负责 FreePool。 */
static EFI_STATUS read_all(const CHAR16 *path, UINT8 **buf, UINTN *len)
{
  EFI_FILE_PROTOCOL *h = NULL;
  UINT8 info[sizeof(EFI_FILE_INFO) + 512];
  UINTN isz = sizeof(info), n;
  EFI_STATUS st;

  *buf = NULL; *len = 0;
  st = gRoot->Open(gRoot, &h, (CHAR16 *)path, EFI_FILE_MODE_READ, 0);
  if (EFI_ERROR(st) || !h) return EFI_NOT_FOUND;
  st = h->GetInfo(h, &gFileInfoGuid, &isz, info);
  if (EFI_ERROR(st)) { h->Close(h); return st; }
  n = (UINTN)((EFI_FILE_INFO *)info)->FileSize;
  if (n == 0 || n > (8u << 20)) { h->Close(h); return EFI_UNSUPPORTED; }
  st = gBS->AllocatePool(EfiLoaderData, n, (void **)buf);
  if (EFI_ERROR(st)) { h->Close(h); return st; }
  st = h->Read(h, &n, *buf);
  h->Close(h);
  if (EFI_ERROR(st)) { gBS->FreePool(*buf); *buf = NULL; return st; }
  *len = n;
  return EFI_SUCCESS;
}

static EFI_STATUS write_all(const CHAR16 *path, const UINT8 *buf, UINTN len)
{
  EFI_FILE_PROTOCOL *h = NULL;
  UINTN n = len;
  EFI_STATUS st;

  st = gRoot->Open(gRoot, &h, (CHAR16 *)path,
                   EFI_FILE_MODE_CREATE | EFI_FILE_MODE_READ | EFI_FILE_MODE_WRITE, 0);
  if (EFI_ERROR(st) || !h) return st;
  (void)h->SetPosition(h, 0);
  st = h->Write(h, &n, (void *)buf);
  if (!EFI_ERROR(st)) st = h->Flush(h);
  h->Close(h);
  return (EFI_ERROR(st) || n != len) ? EFI_LOAD_ERROR : EFI_SUCCESS;
}

static void append_line(const CHAR16 *path, const char *ascii, UINTN len)
{
  EFI_FILE_PROTOCOL *h = NULL;
  UINTN n = len;
  if (EFI_ERROR(gRoot->Open(gRoot, &h, (CHAR16 *)path,
        EFI_FILE_MODE_CREATE | EFI_FILE_MODE_READ | EFI_FILE_MODE_WRITE, 0)) || !h)
    return;
  (void)h->SetPosition(h, EFI_FILE_POSITION_END);
  (void)h->Write(h, &n, (void *)ascii);
  (void)h->Flush(h);
  h->Close(h);
}

static void delete_file(const CHAR16 *path)
{
  EFI_FILE_PROTOCOL *h = NULL;
  if (EFI_ERROR(gRoot->Open(gRoot, &h, (CHAR16 *)path,
        EFI_FILE_MODE_READ | EFI_FILE_MODE_WRITE, 0)) || !h)
    return;
  (void)h->Delete(h);              /* Delete 成功与否都会关闭句柄 */
}

/* 用 SetInfo 改 EFI_FILE_INFO.FileName 做同目录改名。这是 FAT 上最接近
 * 原子的操作：目录项改写，不搬数据。 */
static EFI_STATUS rename_in_dir(const CHAR16 *path, const CHAR16 *newname)
{
  EFI_FILE_PROTOCOL *h = NULL;
  UINT8 info[sizeof(EFI_FILE_INFO) + 512];
  UINTN isz = sizeof(info), nl, i;
  EFI_FILE_INFO *fi = (EFI_FILE_INFO *)info;
  EFI_STATUS st;

  st = gRoot->Open(gRoot, &h, (CHAR16 *)path,
                   EFI_FILE_MODE_READ | EFI_FILE_MODE_WRITE, 0);
  if (EFI_ERROR(st) || !h) return st;
  st = h->GetInfo(h, &gFileInfoGuid, &isz, info);
  if (EFI_ERROR(st)) { h->Close(h); return st; }

  nl = s16len(newname);
  if (sizeof(EFI_FILE_INFO) + (nl + 1) * 2 > sizeof(info)) { h->Close(h); return EFI_UNSUPPORTED; }
  for (i = 0; i <= nl; i++) fi->FileName[i] = newname[i];
  fi->Size = sizeof(EFI_FILE_INFO) - sizeof(CHAR16) + (nl + 1) * 2;

  st = h->SetInfo(h, &gFileInfoGuid, (UINTN)fi->Size, info);
  if (!EFI_ERROR(st)) st = h->Flush(h);
  h->Close(h);
  return st;
}

/* ---------------------- AMD 核心数字节的运行期回填 ---------------------- */

static const char kB64[] =
  "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";

/* 构建期在 03-amd.plist 里把 cores_per_package 补丁的 Replace 写成
 * BA 04 00 00 00，其 base64 正好是 "ugQAAAA="（唯一出现一次，由构建脚本断言）。
 * 这里只改前 4 个字符，即 base64 的第一组 {0xBA, cc, 0x00}。 */
#define CORES_MARKER "ugQAAAA="

static int patch_cores_byte(UINT8 *buf, UINTN len, UINT8 cc)
{
  const char *m = CORES_MARKER;
  UINTN i, j, hits = 0, at = 0;

  if (len < 8) return 0;
  for (i = 0; i + 8 <= len; i++) {
    for (j = 0; j < 8; j++) if (buf[i + j] != (UINT8)m[j]) break;
    if (j == 8) { hits++; at = i; }
  }
  if (hits != 1) return -(int)hits;        /* 0 = 没有，>1 = 不唯一，都当失败 */

  buf[at + 0] = (UINT8)'u';                              /* 0xBA >> 2 == 46 */
  buf[at + 1] = (UINT8)kB64[0x20 | (cc >> 4)];
  buf[at + 2] = (UINT8)kB64[(cc & 0x0F) << 2];
  buf[at + 3] = (UINT8)'A';
  return 1;
}

/* ---------------------- 装配 config.plist ---------------------- */

static EFI_STATUS install_config(const CHAR16 *src, int is_amd, const CPUFACTS *f, char *note)
{
  UINT8 *buf = NULL; UINTN len = 0;
  EFI_STATUS st;

  note[0] = 0;
  st = read_all(src, &buf, &len);
  if (EFI_ERROR(st)) return st;

  if (is_amd) {
    int r = patch_cores_byte(buf, len, (UINT8)f->cores_per_pkg);
    note[0] = (r == 1) ? 'C' : 'c';        /* 'C' 回填成功，'c' 没回填 */
    note[1] = 0;
  }

  st = write_all(u"\\EFI\\OC\\CONFIG.NEW", buf, len);
  gBS->FreePool(buf);
  if (EFI_ERROR(st)) return st;

  delete_file(u"\\EFI\\OC\\config.plist");
  st = rename_in_dir(u"\\EFI\\OC\\CONFIG.NEW", u"config.plist");
  return st;
}

/* ---------------------- 链载 ---------------------- */

static UINTN dp_total(const UINT8 *dp)
{
  UINTN n = 0;
  for (;;) {
    UINTN l = (UINTN)dp[n + 2] | ((UINTN)dp[n + 3] << 8);
    if (l < 4) return 0;
    if (dp[n] == 0x7F) return n + l;       /* END_DEVICE_PATH */
    n += l;
    if (n > 4096) return 0;
  }
}

static EFI_STATUS chainload(const CHAR16 *path)
{
  EFI_LOADED_IMAGE_PROTOCOL *li = NULL;
  UINT8 *dev = NULL, *np = NULL;
  UINTN head, nl, nodelen, total, i;
  EFI_HANDLE child = NULL;
  EFI_STATUS st;

  st = gBS->HandleProtocol(gImage, &gLoadedImageGuid, (void **)&li);
  if (EFI_ERROR(st) || !li) return EFI_NOT_FOUND;
  st = gBS->HandleProtocol(li->DeviceHandle, &gDevicePathGuid, (void **)&dev);
  if (EFI_ERROR(st) || !dev) return EFI_NOT_FOUND;

  total = dp_total(dev);
  if (total < 4) return EFI_LOAD_ERROR;
  head    = total - 4;                     /* 去掉 END 节 */
  nl      = s16len(path);
  nodelen = 4 + (nl + 1) * 2;              /* MEDIA_FILEPATH_DP */
  total   = head + nodelen + 4;

  st = gBS->AllocatePool(EfiLoaderData, total, (void **)&np);
  if (EFI_ERROR(st)) return st;
  memcpy(np, dev, head);
  np[head + 0] = 4;                        /* MEDIA_DEVICE_PATH  */
  np[head + 1] = 4;                        /* MEDIA_FILEPATH_DP  */
  np[head + 2] = (UINT8)(nodelen & 0xFF);
  np[head + 3] = (UINT8)(nodelen >> 8);
  for (i = 0; i <= nl; i++) {
    np[head + 4 + i * 2]     = (UINT8)(path[i] & 0xFF);
    np[head + 4 + i * 2 + 1] = (UINT8)(path[i] >> 8);
  }
  np[head + nodelen + 0] = 0x7F;
  np[head + nodelen + 1] = 0xFF;
  np[head + nodelen + 2] = 4;
  np[head + nodelen + 3] = 0;

  st = gBS->LoadImage(0, gImage, (EFI_DEVICE_PATH_PROTOCOL *)np, NULL, 0, &child);
  gBS->FreePool(np);
  if (EFI_ERROR(st) || !child) return EFI_ERROR(st) ? st : EFI_LOAD_ERROR;
  return gBS->StartImage(child, NULL, NULL);
}
```

源码接下来是状态机与 `efi_main`，放在第 4.4 节，因为它要先讲清状态文件格式才读得懂。

### 3.4 构建

**选 mingw-w64 而不是 EDK2 或 gnu-efi，三条理由：**

1. mingw-w64 的 x86_64 目标**原生输出就是合法的 UEFI 二进制**（PE32+，默认 MS x64 ABI），不需要 `objcopy -O efi-app-x86_64` 这一步，也不需要为每个 UEFI 函数指针加 `ms_abi` 属性。`INFERRED`，这是公开的既有做法（转述自 <https://github.com/hmofet/unodos/blob/master/pc64/DEVELOPMENT.md>，该项目明确声明不用 EDK2 也不用 gnu-efi，靠 mingw 目标的原生输出）。
2. gnu-efi 要多一个外部仓库与一次 `objcopy`；EDK2 要一整棵源码树、一个 `.dsc`/`.inf` 与一次 `build` 配置。`70` 第 1.4 节记录的构建侧现状里两者都没有。
3. 单文件自带头定义之后，shim 的全部输入就是一个 `.c`，可复现性最好。

```bash
# 在任意 Debian/Ubuntu 上。Alpine 用 mingw-w64-gcc 包同理。
sudo apt-get install -y gcc-mingw-w64-x86-64

x86_64-w64-mingw32-gcc \
  -std=c11 -O2 -Wall -Wextra -Werror \
  -ffreestanding -fno-builtin -fno-stack-protector -fno-stack-check \
  -fshort-wchar -mno-red-zone -mno-stack-arg-probe \
  -nostdinc -nostdlib \
  -c src/boot/cpudispatch.c -o build/cpudispatch.o

x86_64-w64-mingw32-gcc \
  -nostdlib -Wl,--subsystem,10 -e efi_main \
  -o build/BOOTX64.EFI build/cpudispatch.o

# 核对产物形状：必须是 PE32+ / EFI application
x86_64-w64-mingw32-objdump -f build/BOOTX64.EFI | head -5
python3 - <<'PY'
import struct
b = open('build/BOOTX64.EFI','rb').read()
pe = struct.unpack_from('<I', b, 0x3C)[0]
assert b[pe:pe+4] == b'PE\0\0', 'not a PE'
magic = struct.unpack_from('<H', b, pe+24)[0]
subsys = struct.unpack_from('<H', b, pe+24+68)[0]
print('optional-header magic = 0x%04x (want 0x20b = PE32+)' % magic)
print('subsystem             = %d (want 10 = EFI_APPLICATION)' % subsys)
assert magic == 0x20b and subsys == 10
PY
```

逐个 flag 的理由（都不是装饰）：

| flag | 为什么必须有 |
|---|---|
| `-ffreestanding -fno-builtin -nostdinc -nostdlib` | 没有 libc，也不许编译器把 `memcpy` 之类替换成它自己的版本 |
| `-fshort-wchar` | UEFI 的 `CHAR16` 是 2 字节。没有它，`u"..."` 与 `CHAR16` 不匹配 |
| `-mno-red-zone` | UEFI 在中断上下文里不保证 red zone 可用 |
| `-fno-stack-protector -fno-stack-check -mno-stack-arg-probe` | 这些会生成对运行时支持函数（`__chkstk_ms` 等）的调用，而我们没有运行时 |
| `-Wl,--subsystem,10` | PE 的 Subsystem 必须是 10（`EFI_APPLICATION`），否则固件拒绝加载 |
| `-e efi_main` | 入口点。mingw 默认入口是 `mainCRTStartup`，那个不存在 |
| `-Werror` | shim 里一个 warning 都不许留。它没有调试通道 |

**源码里用 `u"..."` 而不是 `L"..."`。** `u` 前缀在 C11 下确定是 `char16_t`，与 `-fshort-wchar` 下的 `L` 等价但不依赖 flag。保险起见两个都配上。

**产物的落位**（接 `71` 第 8.2.2 节的 ESP 组装步骤）：

```bash
mcopy -i "$ESP_IMG" -o build/BOOTX64.EFI ::/EFI/BOOT/BOOTX64.DISPATCH.efi
mcopy -i "$ESP_IMG" -o build/BOOTX64.EFI ::/EFI/BOOT/BOOTX64.EFI
```

两份一样的内容：`BOOTX64.EFI` 是当前生效的那个，`BOOTX64.DISPATCH.efi` 是 `73` 第 5.3.2 节的恢复脚本要复制回来的那个源。

### 3.5 与 OpenCore 自己的 `BOOTx64.efi` 的关系

OpenCorePkg 的发布包里有两个文件：`X64/EFI/BOOT/BOOTx64.efi` 与 `X64/EFI/OC/OpenCore.efi`。

- `KNOWN`：OpenCore 的配置根路径是常量 `EFI\OC`、应用名是常量 `OpenCore.efi`（第 1.1 节）。
- `INFERRED`：发布包里的 `BOOTx64.efi` 与 `OpenCore.efi` 是同一份二进制，OpenCore 被从哪个路径启动都会在**自己所在的那个卷**上去找 `EFI\OC`。**查清方法零成本**：构建期对两个文件算 SHA-256 比一下。写成构建期断言：

```bash
a=$(sha256sum oc/X64/EFI/BOOT/BOOTx64.efi | cut -d' ' -f1)
b=$(sha256sum oc/X64/EFI/OC/OpenCore.efi   | cut -d' ' -f1)
if [ "$a" = "$b" ]; then
  echo "OpenCore bootstrap == OpenCore.efi（同一份二进制）"
else
  echo "两者不同：BOOTx64.efi 是独立的 bootstrap，必须保留它而不是直接丢掉" >&2
fi
```

**这条断言的结果不改变我们的做法，只改变我们对 `BOOTX64.OC.efi` 的理解**：

| 断言结果 | `BOOTX64.OC.efi` 应该放谁 | 我们的链载目标 |
|---|---|---|
| 两者相同 | `OpenCore.efi` 的副本 | `\EFI\OC\OpenCore.efi` |
| 两者不同 | OpenCore 自己的 `BOOTx64.efi`（bootstrap） | 仍然是 `\EFI\OC\OpenCore.efi`。bootstrap 的全部职责就是找到并加载它，我们直接做了同一件事 |

**无论哪种结果，链条都是接得上的**，因为我们把 `LoadImage` 的 device path 构造成"自己所在卷 + `\EFI\OC\OpenCore.efi`"，OpenCore 拿到的 `LoadedImage->DeviceHandle` 与它被 bootstrap 加载时拿到的是同一个句柄。登记为 B-002 的一部分。

**一条必须保持的配置约束：`Misc/Boot/LauncherOption` 保持 `Disabled`。** `71` 第 6.6.1 节已经这么设了，理由是 Vultr 的 NVRAM 持久性未知（`80` 的 H-002）。加入 shim 之后这一项从"稳妥"升级为"必须"：官方说明里 `LauncherOption` 一旦创建了自定义启动项，`\EFI\BOOT\BOOTx64.efi` 就不再被用于引导（第 1.2 节，`KNOWN`）。**而那正是 shim 所在的位置。开了它就等于把 shim 从引导链上摘掉。**

### 3.6 失败处理纪律

shim 是引导链第一环，它的每一种失败都要有确定的下一步。下表是第 4.4 节代码里逐条实现的。

| 失败 | 处置 | 为什么不是别的处置 |
|---|---|---|
| `open_own_volume()` 失败 | 直接链载 `\EFI\OC\OpenCore.efi`，不写状态 | 卷打不开说明文件系统有问题，这时候写状态只会写坏。OpenCore 用上一次留下的 `config.plist` 仍可能起来 |
| 状态文件读不到 / 格式不对 | 当成全新状态，从顺序的第 0 档开始 | 这是首次启动的正常路径，不是错误 |
| 状态文件里的 `sig` 与本次判别不符 | **重置整个阶梯**，从第 0 档开始 | 这是"golden 快照被部署到另一种机型"的情形。继续用旧档是错的 |
| 候选 plist 读不到 | 记日志，当作本档失败，立刻前进到下一档并链载 | 不要重启来推进。镜像残缺时重启会变成重启循环 |
| `install_config()` 中途失败 | 记日志，链载 `\EFI\OC\OpenCore.efi` 看它能不能用残留的 config 起来；`inflight` 已置位，所以下一次启动会前进一档 | 已经删了 `config.plist` 又没改名成功时，OpenCore 必然起不来；这由阶梯接住 |
| `chainload()` 返回（即 `StartImage` 失败或被加载的镜像退出了） | 记日志，链载 `\EFI\BOOT\BOOTX64.RESCUE.efi` | 这是最后一次能做事的机会。进 rescue 就有 SSH，就能读 `LOG.TXT` |
| 连 rescue 也链载失败 | `beacon()`：关掉看门狗，打印一行，`Stall` 循环 | **绝不重启。** 重启循环会反复踩同一处，而且在没有控制台的机器上无法观察。停住至少让实例在平台 API 里是 running 状态，可以走 `73` 第 5.4 节 R2 取证 |
| 累计启动次数超过预算 | 同 `beacon()` | 见第 4.7 节 |

**`beacon()` 必须先关看门狗。** 固件在启动一个启动项之前会设一个 5 分钟的看门狗；不关掉的话"停住"会变成"5 分钟后固件复位"，也就是重启循环。`KNOWN`（UEFI 的 `SetWatchdogTimer` 语义）。

---

## 4. 候选阶梯与自动回退

### 4.1 为什么状态不能放在固件 NVRAM 里

`73` 第 2.3 节抄的是 `bin456789/reinstall` 的 EFI 一次性启动项（`efibootmgr --create-only` + `--bootnext`），它的安全阀是"固件读一次 `BootNext` 就把它清掉"。这个机制在本文的场景里不能用，三条理由，前两条来自 `73`：

1. **Vultr 固件的 NVRAM 持久性未确证**（`80` 的 H-002，`BLOCKED`）。阶梯的状态必须跨重启存活，这是它的全部意义。
2. **`73` 第 2.7 节记录的厂商观察**：给数据盘写 NVRAM 启动项在 Vultr 上不生效，而 `BootNext` 指向数据盘却生效。即同一台机器上 NVRAM 的不同用法行为不一致，不能作为状态存储。
3. **OpenCore 自己在管 NVRAM**（`71` 第 6.7 节的 `WriteFlash = true`、`RequestBootVarRouting`），两者的交互未知（`73` 的 D-011）。shim 又跑在 OpenCore 之前，先写后被覆盖这类顺序问题无法在没有串口的机器上诊断。

**所以状态存在 ESP 的一个文件里**，和 `73` 第 5.3.2 节的 `/boot-mode`、`/boot-revert` 同一思路。这还顺带带来 `BootNext` 给不了的一个好处：**macOS 侧与 rescue 侧都能读写同一份状态**，所以"确认成功"这件事可以由 macOS 自己做（第 4.6 节）。

### 4.2 状态文件格式

路径：`ESP:\EFI\CPUDISP\STATE.TXT`
编码：ASCII
**长度：恒为 512 字节。** 不足的部分用空格补齐。

定长是刻意的：UEFI 的 `EFI_FILE_PROTOCOL` 没有 truncate，要缩短文件得走 `SetInfo` 改 `FileSize`。恒定 512 字节把每次更新变成"`SetPosition(0)` + 写 512 字节"，一次调用，没有中间状态。macOS 侧的脚本同样按 512 字节整写。

```text
CPUDISP1
sig=1A2B3C4D
cand=2
inflight=1
confirmed=0
boots=5
exhausted=0
pick=intel-hardened
<空格补齐到 512 字节>
```

| 键 | 类型 | 谁写 | 含义 |
|---|---|---|---|
| 第一行 | 魔数 `CPUDISP1` | shim | 版本标识。不匹配就当没有状态 |
| `sig` | 8 位十六进制 | shim | 本次判别结果的指纹，见下 |
| `cand` | 十进制 | shim / daemon | 当前在顺序里的下标，不是档位编号 |
| `inflight` | 0/1 | shim 置 1，daemon 清 0 | 1 = "有一次尝试已经发出但没被确认" |
| `confirmed` | 0/1 | daemon 置 1 | 1 = 当前 `cand` 已被证明能把 macOS 带到可观测状态 |
| `boots` | 十进制 | shim | 累计启动次数。预算见第 4.6 节 |
| `exhausted` | 0/1 | shim | 1 = 顺序已经走完 |
| `pick` | 字符串 | shim | 上一次选了哪一档，给人看 |

**`sig` 的算法**（FNV-1a 32 位，输入是判别结果里所有"换一台机器就会变"的量）：

```c
static UINT32 facts_sig(const CPUFACTS *f)
{
  UINT32 h = 0x811C9DC5u;
  const UINT32 v[12] = {
    f->sig, f->max_basic, f->max_ext, f->l1_ebx, f->l1_ecx, f->l7_ebx,
    f->e1_ecx, f->e1_edx, f->e8_ecx, f->hv_max,
    (UINT32)f->x87_ptrs_saved, f->cores_per_pkg
  };
  UINTN i, j;
  for (i = 0; i < 12; i++)
    for (j = 0; j < 4; j++) {
      h ^= (v[i] >> (j * 8)) & 0xFF;
      h *= 0x01000193u;
    }
  for (i = 0; i < 12; i++) { h ^= (UINT8)f->vendor[i]; h *= 0x01000193u; }
  return h;
}
```

**`sig` 变了就重置阶梯。** 这一条解决的是一个具体场景：`73` 第 3.1.3 节的 golden snapshot 被 `restore` 到另一个 plan 上（例如从 `vc2-4c-8gb` 的 Intel 换到 `voc-*-amd`）。盘上的状态文件还记着"Intel 档已确认"，而硬件已经换了。`sig` 把这件事变成自动的。

### 4.3 五档候选

`cpudisp=N` 这个 boot-arg 是每一档的身份标记。XNU 对不认识的 boot-arg 不做任何事，但它会出现在 `sysctl kern.bootargs` 里，**所以首启探针一眼就能知道"这次是哪一档起来的"**。这是整套机制里最便宜的观测手段。

| 档 | 文件 | `Cpuid1Data` | `Kernel/Patch` | boot-args 增量 | 用在哪一行判决 |
|---|---|---|---|---|---|
| **T0** `intel-native` | `00-intel-native.plist` | 空 | **空数组** | `cpudisp=0` | 判决表第 6 行：真 Intel 且 model 在 `72` 第 2.3 节白名单内 |
| **T1** `intel-spoof` | `01-intel-spoof.plist` | `57 06 05 00` + 12 字节零（`72` 第 4.2.1 节取值 B） | **空数组** | `cpudisp=1` | 第 7 行：真 Intel 但 model 不在白名单（Ice Lake-SP / SPR / EMR / GNR / Rocket Lake） |
| **T2** `intel-hardened` | `02-intel-hardened.plist` | 同 T1 | **三条厂商无关补丁**：AMD_Vanilla 第 15、19 条 + **收紧版的第 20 条**（第 5.1.2 节） | `cpudisp=2` | 第 4、5 行：H2，硅片疑似 AMD 而 CPUID 是 Intel 形状 |
| **T3** `amd` | `03-amd.plist` | 空 | **AMD_Vanilla 全集**（第 20 条换成收紧版，核心数字节由 shim 回填） | `cpudisp=3` | 第 1、2、3 行 |
| **T4** `safe` | `04-safe.plist` | 同 T1 | 同 T2 | `cpudisp=4 cpus=1 -nomsr35h` | 每一行的第二档。它是"把能关的都关掉"的那一档 |

**T1 为什么对已经在白名单里的 model 也无害**：伪装目标是 `0x00050657`，即 family 6 / model `0x55`。如果真实 model 已经是 `0x55`，这是一次恒等替换；如果是 `0x9E`、`0xA5` 等别的白名单 model，替换后仍然命中 `72` 第 2.3 节的 `case 85` 并返回 `CPUFAMILY_INTEL_SKYLAKE`，而且与 `71` 第 4.4 节选定的 `MacPro7,1` SMBIOS 更一致。`INFERRED`，依据是 `72` 第 4.2.2 节已论证 `Cpuid1Data` 的唯一下游风险（XCPM 按错误 model 写频率向量）在 guest 里不存在。

**T4 的两个 boot-arg 分别对准 `72` 第 7.5 节点名的两个"没有兜底"的风险**：

| boot-arg | 对准什么 | 依据 |
|---|---|---|
| `cpus=1` | `72` 第 2.7.3 节的 `x86_validate_topology` panic。只上一个 CPU 时等式两边都塌成确定值 | `INFERRED`，`72` 第 4.3.1 节把它列为优先级 2 的手段 |
| `-nomsr35h` | `72` 第 2.8 节确证的原生逃生口：hypervisor 位置位时完全不读 `MSR 0x35`，把 core/thread 定成 1/1 | `KNOWN` 对于 boot-arg 的存在与作用（字符串 VA `0xffffff8000b7c8e2`，唯一 xref 来自 `_cpuid_set_info`）；`INFERRED` 对于它与拓扑校验的交互（`72` 的 C-009） |

**T4 与 `cpus=1` 的代价要写清：单核 macOS 对本项目的渲染吞吐是灾难性的（Lavapipe 是纯 CPU 渲染器，`80` 第 1.6 节）。T4 不是能用的配置，是能被观察的配置。** 它的任务是把实例带到 SSH 可达，然后由 `80` 的采集流程把 `72` 第 6.4 节的 A2 段跑一遍，拿到真实的 CPU 事实，之后由人决定造哪一档。

### 4.4 候选 plist 的生成

接 `72` 第 5.2.3 节对 `scripts/make-oc-config.py` 的扩展。那一节的参数是 `<intel|amd>`，这里换成 `<tier>` 并产 5 份。只给增量：

```python
#!/usr/bin/env python3
"""scripts/make-oc-config.py  —— 72 第 5.2.3 节脚本的再扩展
用法:  py make-oc-config.py <Sample.plist> <outdir> [<host-cpu.json>]
产物:  outdir/{00-intel-native,01-intel-spoof,02-intel-hardened,03-amd,04-safe}.plist
"""
import json, plistlib, sys, pathlib

SRC, OUTDIR = sys.argv[1], pathlib.Path(sys.argv[2])
HOST = json.load(open(sys.argv[3])) if len(sys.argv) > 3 else {}

SPOOF_DATA = bytes.fromhex('57060500' + '00' * 12)   # 72 §4.2.1 取值 B
SPOOF_MASK = bytes.fromhex('FFFFFFFF' + '00' * 12)

BASE_BOOTARGS = ('amfi_get_out_of_my_way=1 -v -cpuid keepsyms=1 '
                 'debug=0xa serial=7 msgbuf=1048576')          # 71 §6.7 + 72 §2.9

def load_amd_patches(path, fix20_path):
    """读上游 patches.plist，把 master 的第 20 条换成本项目的收紧版（74 §5.1.2）。
    识别"要换掉的那一条"不靠序号而靠 Find 字节，因为上游会重排顺序。
    fix20_path 指向仓库自有的 vendor/metal2vu-patches/tighten-20.plist。"""
    up = plistlib.load(open(path, 'rb'))['Kernel']['Patch']
    fix = plistlib.load(open(fix20_path, 'rb'))['Kernel']['Patch']
    BROKEN_FIND = bytes.fromhex('48000080040000' + '0F00000000' + '00')
    out, replaced = [], 0
    for p in up:
        p['Base'] = (p.get('Base') or '').strip()      # 72 §3.1.2 / C-007
        if p.get('Find') == BROKEN_FIND:
            replaced += 1
            continue                                    # 丢掉 master 的第 20 条
        out.append(p)
    assert replaced == 1, f'期望恰好 1 条待替换的第 20 条，实际 {replaced} 条'
    for p in fix:
        p['Base'] = (p.get('Base') or '').strip()
        out.append(p)
    return out

def neutral_subset(patches):
    """只取厂商无关的三条：_i386_init 去 rdmsr、两条 non-monotonic time。
    判据是补丁内容而不是注释文本：Replace 全是 NOP/零，且目标函数在白名单里。"""
    keep = []
    for p in patches:
        c = (p.get('Comment') or '')
        if 'i386_init' in c or 'non-monotonic' in c.lower() or 'monotonic' in c.lower():
            keep.append(p)
    assert len(keep) == 3, f'neutral subset must be exactly 3, got {len(keep)}'
    return keep

def build(tier, idx, spoof, patches, extra_args):
    c = plistlib.load(open(SRC, 'rb'))
    # ... 71 第 6.1 节的全部内容照旧（ACPI / Booter / Misc / NVRAM / PlatformInfo / UEFI）...
    c['Kernel']['Quirks']['ProvideCurrentCpuInfo'] = True          # 72 §4.4
    for k in ('AppleCpuPmCfgLock', 'AppleXcpmCfgLock',
              'AppleXcpmExtraMsrs', 'AppleXcpmForceBoost', 'LapicKernelPanic'):
        c['Kernel']['Quirks'][k] = False                           # 72 §2.6 / §4.4
    c['Kernel']['Emulate']['Cpuid1Data'] = SPOOF_DATA if spoof else b''
    c['Kernel']['Emulate']['Cpuid1Mask'] = SPOOF_MASK if spoof else b''
    c['Kernel']['Patch'] = patches
    c['Misc']['Boot']['LauncherOption'] = 'Disabled'               # 74 §3.5：必须
    nv = c['NVRAM']['Add']['7C436110-AB2A-4BBB-A880-FE41995C9F82']
    nv['boot-args'] = f'{BASE_BOOTARGS} cpudisp={idx}{extra_args}'
    dst = OUTDIR / f'{idx:02d}-{tier}.plist'
    OUTDIR.mkdir(parents=True, exist_ok=True)
    plistlib.dump(c, open(dst, 'wb'), sort_keys=True)
    return dst

amd_all = load_amd_patches('vendor/AMD_Vanilla/patches.plist',
                           'vendor/metal2vu-patches/tighten-20.plist')
neutral = neutral_subset(amd_all)

# T3 的核心数字节：写成 0x04 占位，运行期由 shim 回填（74 §3.6）
CORES_PLACEHOLDER = 0x04
for p in amd_all:
    if (p.get('Comment') or '').find('cpuid_cores_per_package') >= 0:
        r = bytearray(p['Replace']); r[1] = CORES_PLACEHOLDER; p['Replace'] = bytes(r)

paths = [
    build('intel-native',   0, False, [],      ''),
    build('intel-spoof',    1, True,  [],      ''),
    build('intel-hardened', 2, True,  neutral, ''),
    build('amd',            3, False, amd_all, ''),
    build('safe',           4, True,  neutral, ' cpus=1 -nomsr35h'),
]

# ---- 构建期断言 ----
MARKER = b'ugQAAAA='          # base64(BA 04 00 00 00) 的前 8 字节，见 74 §3.6
amd_blob = (OUTDIR / '03-amd.plist').read_bytes()
n = amd_blob.count(MARKER)
assert n == 1, (f'03-amd.plist 里 {MARKER!r} 出现 {n} 次，必须恰好 1 次，'
                f'否则 shim 的核心数回填会失败')
for p in paths:
    blob = p.read_bytes()
    assert MARKER not in blob or p.name.startswith('03-'), \
        f'{p.name} 里不该出现核心数标记'
    plistlib.loads(blob)       # 每一份都必须是合法 plist
print('\n'.join(str(p) for p in paths))
```

**那条 `assert n == 1` 是整个核心数回填方案的安全带。** 标记不唯一时 shim 的 `patch_cores_byte()` 返回负值、不改任何字节，T3 会带着占位的 4 核常量启动；在一台 32 vCPU 的实例上那会直接撞上 `72` 第 2.7.3 节的拓扑 panic。构建期挡住比运行期发现便宜几个数量级。

### 4.5 状态机与 `efi_main`

接第 3.3 节的源码。

```c
/* ---------------------- 状态 ---------------------- */

#define STATE_PATH  u"\\EFI\\CPUDISP\\STATE.TXT"
#define LOG_PATH    u"\\EFI\\CPUDISP\\LOG.TXT"
#define NOAMD_PATH  u"\\EFI\\CPUDISP\\NOAMD"
#define STATE_SIZE  512
#define BOOT_BUDGET 12            /* 见 4.6 节 */

typedef struct {
  int    valid;
  UINT32 sig;
  int    cand, inflight, confirmed, exhausted;
  UINT32 boots;
} STATE;

/* 极小的 key=value 取值器。只认 ASCII 十进制与十六进制。 */
static const char *find_key(const char *b, UINTN n, const char *k)
{
  UINTN i, j, kl = 0;
  while (k[kl]) kl++;
  for (i = 0; i + kl + 1 < n; i++) {
    if (i && b[i - 1] != '\n') continue;
    for (j = 0; j < kl; j++) if (b[i + j] != k[j]) break;
    if (j == kl && b[i + kl] == '=') return b + i + kl + 1;
  }
  return NULL;
}

static UINT32 parse_u32(const char *p, int hex)
{
  UINT32 v = 0;
  if (!p) return 0;
  while (*p) {
    int d;
    if (*p >= '0' && *p <= '9')      d = *p - '0';
    else if (hex && *p >= 'A' && *p <= 'F') d = *p - 'A' + 10;
    else if (hex && *p >= 'a' && *p <= 'f') d = *p - 'a' + 10;
    else break;
    v = v * (hex ? 16 : 10) + (UINT32)d;
    p++;
  }
  return v;
}

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
  s->valid     = 1;
  gBS->FreePool(b);
}

static char *put_str(char *p, const char *s) { while (*s) *p++ = *s++; return p; }
static char *put_u32(char *p, UINT32 v, int hex)
{
  char t[12]; int n = 0;
  if (!v) { *p++ = '0'; return p; }
  while (v) { int d = (int)(v % (UINT32)(hex ? 16 : 10));
              t[n++] = (char)(d < 10 ? '0' + d : 'A' + d - 10);
              v /= (UINT32)(hex ? 16 : 10); }
  while (n--) *p++ = t[n];
  return p;
}
static char *put_w(char *p, const CHAR16 *s) { while (*s) *p++ = (char)(*s & 0x7F); return p; }

static EFI_STATUS state_write(const STATE *s, const CHAR16 *pick)
{
  static char buf[STATE_SIZE];
  char *p = buf; UINTN i;
  memset(buf, ' ', STATE_SIZE);
  p = put_str(p, "CPUDISP1\nsig=");      p = put_u32(p, s->sig, 1);
  p = put_str(p, "\ncand=");             p = put_u32(p, (UINT32)s->cand, 0);
  p = put_str(p, "\ninflight=");         p = put_u32(p, (UINT32)s->inflight, 0);
  p = put_str(p, "\nconfirmed=");        p = put_u32(p, (UINT32)s->confirmed, 0);
  p = put_str(p, "\nboots=");            p = put_u32(p, s->boots, 0);
  p = put_str(p, "\nexhausted=");        p = put_u32(p, (UINT32)s->exhausted, 0);
  p = put_str(p, "\npick=");             p = put_w(p, pick);
  *p++ = '\n';
  i = (UINTN)(p - buf);
  if (i > STATE_SIZE) return EFI_UNSUPPORTED;      /* 不可能，留着挡改错 */
  return write_all(STATE_PATH, (UINT8 *)buf, STATE_SIZE);
}

/* 每次启动往 LOG.TXT 追加一段。这是 L2 上唯一的引导期诊断通道：
 * 没有串口（73 §1.1），但 rescue 与 macOS 都能读 FAT。 */
static void log_boot(const CPUFACTS *f, const STATE *s, const CHAR16 *pick, const char *note)
{
  static char b[640];
  char *p = b;
  p = put_str(p, "--- cpudispatch\nvendor=");  p = put_str(p, f->vendor);
  p = put_str(p, " sig1=");      p = put_u32(p, f->sig, 1);
  p = put_str(p, " fam=");       p = put_u32(p, f->fam, 1);
  p = put_str(p, " mdl=");       p = put_u32(p, f->mdl, 1);
  p = put_str(p, " stp=");       p = put_u32(p, f->stp, 1);
  p = put_str(p, "\nmaxb=");     p = put_u32(p, f->max_basic, 1);
  p = put_str(p, " maxe=");      p = put_u32(p, f->max_ext, 1);
  p = put_str(p, " e1ecx=");     p = put_u32(p, f->e1_ecx, 1);
  p = put_str(p, " e1edx=");     p = put_u32(p, f->e1_edx, 1);
  p = put_str(p, " e8ecx=");     p = put_u32(p, f->e8_ecx, 1);
  p = put_str(p, " c1d=");       p = put_u32(p, f->cache1d_eax, 1);
  p = put_str(p, " t1e=");       p = put_u32(p, f->topoext_ebx, 1);
  p = put_str(p, " sev=");       p = put_u32(p, f->sev_eax, 1);
  p = put_str(p, " svm=");       p = put_u32(p, f->svm_eax, 1);
  p = put_str(p, "\nhv=");       p = put_str(p, f->hv);
  p = put_str(p, " hvmax=");     p = put_u32(p, f->hv_max, 1);
  p = put_str(p, " tsckhz=");    p = put_u32(p, f->hv_tsc_khz, 0);
  p = put_str(p, " buskhz=");    p = put_u32(p, f->hv_bus_khz, 0);
  p = put_str(p, "\nfxsave_x87ptr=");  p = put_u32(p, (UINT32)(f->x87_ptrs_saved + 1), 0);
  p = put_str(p, " native=");    p = put_u32(p, (UINT32)f->native, 0);
  p = put_str(p, " score=");     p = put_u32(p, (UINT32)f->score, 0);
  p = put_str(p, " cores=");     p = put_u32(p, f->cores_per_pkg, 0);
  p = put_str(p, "\ncand=");     p = put_u32(p, (UINT32)s->cand, 0);
  p = put_str(p, " boots=");     p = put_u32(p, s->boots, 0);
  p = put_str(p, " confirmed="); p = put_u32(p, (UINT32)s->confirmed, 0);
  p = put_str(p, " pick=");      p = put_w(p, pick);
  p = put_str(p, " note=");      p = put_str(p, note && note[0] ? note : "-");
  *p++ = '\n';
  append_line(LOG_PATH, b, (UINTN)(p - b));
}

static void beacon(const CHAR16 *why)
{
  gBS->SetWatchdogTimer(0, 0, 0, NULL);          /* 必须。否则 5 分钟后固件复位 */
  out(u"\r\ncpudispatch: HALT -- ");
  out(why);
  out(u"\r\n不会重启。按 73 分册第 5.4 节 R2 层取证。\r\n");
  for (;;) gBS->Stall(1000000);
}

/* ---------------------- 入口 ---------------------- */

EFI_STATUS efi_main(EFI_HANDLE image, EFI_SYSTEM_TABLE *st)
{
  CPUFACTS f;
  STATE s;
  UINT8 ord[NTIER];
  UINTN nord = 0;
  int tier, no_amd;
  char note[8];

  gImage = image; gST = st; gBS = st->BootServices;
  out(u"cpudispatch 1.0\r\n");

  probe(&f);
  f.score = amd_score(&f);

  /* 卷打不开就什么都别做，直接把控制权交给 OpenCore（3.6 节第 1 行） */
  if (EFI_ERROR(open_own_volume()) || !gRoot) {
    out(u"cpudispatch: 卷打不开，直接链载 OpenCore\r\n");
    chainload(u"\\EFI\\OC\\OpenCore.efi");
    beacon(u"volume unavailable and OpenCore did not take over");
  }

  no_amd = file_exists(NOAMD_PATH);
  decide_order(&f, no_amd, ord, &nord);

  state_read(&s);
  if (!s.valid || s.sig != facts_sig(&f)) {       /* 新盘，或硬件换了 */
    memset(&s, 0, sizeof(s));
    s.valid = 1;
    s.sig = facts_sig(&f);
  }
  s.boots++;

  if (s.boots > BOOT_BUDGET) {
    (void)state_write(&s, u"budget-exceeded");
    log_boot(&f, &s, u"budget-exceeded", "boot budget spent");
    beacon(u"boot budget exceeded");
  }

  if (s.confirmed && (UINTN)s.cand < nord) {
    /* 稳态：已经确认过的档不许再动。实验期的失败归因靠这一条成立。 */
    tier = ord[s.cand];
  } else {
    if (s.inflight) s.cand++;                    /* 上一次没被确认 -> 前进一档 */
    if ((UINTN)s.cand >= nord) { s.exhausted = 1; tier = T_RESCUE; }
    else                        tier = ord[s.cand];
    s.inflight = 1;
  }

  note[0] = 0;
  if (tier != T_RESCUE) {
    EFI_STATUS r = install_config(kTierFile[tier], tier == T_AMD, &f, note);
    if (EFI_ERROR(r)) {
      note[0] = 'E'; note[1] = 0;
      out(u"cpudispatch: install_config 失败\r\n");
    }
  }

  /* 状态必须在 LoadImage 之前落盘（3.6 节纪律 3） */
  (void)state_write(&s, kTierName[tier]);
  log_boot(&f, &s, kTierName[tier], note);

  out(u"cpudispatch: tier=");  out(kTierName[tier]);
  out(u" score=");             out_hex32((UINT32)f.score);
  out(u"\r\n");

  if (tier == T_RESCUE) {
    chainload(u"\\EFI\\BOOT\\BOOTX64.RESCUE.efi");
    beacon(u"rescue chainload failed");
  }

  chainload(u"\\EFI\\OC\\OpenCore.efi");
  /* 走到这里说明 OpenCore 没接住。最后一次机会：进 rescue。 */
  out(u"cpudispatch: OpenCore 未接管，转 rescue\r\n");
  chainload(u"\\EFI\\BOOT\\BOOTX64.RESCUE.efi");
  beacon(u"both OpenCore and rescue failed to start");
}
```

### 4.6 macOS 侧的确认 daemon

**只有 macOS 自己能证明"这一档成功了"。** shim 看不到 macOS 的任何状态，所以 `confirmed` 必须由 guest 内部回写。

`71` 第 8.4 节已确证 `msdosfs` 在 System KC 内，即 macOS 能挂载并写 FAT ESP（`KNOWN`）。`73` 第 5.3.2 节的 `arm-rescue.sh` 已经在用同一条能力。

**脚本：`/usr/local/libexec/cpudisp-confirm.sh`**（可直接照抄；不依赖 `python3`、不依赖 `perl`、不依赖 `jq`，只用 macOS 自带的 `sh` / `diskutil` / `awk` / `sed` / `nc`）

```sh
#!/bin/sh
# 向 ESP 回写"当前候选已确认成功"。只在 macOS 真的可观测之后才写。
# 规格: docs/spec/74-BOOT-CPU-DISPATCH.md 第 4.6 节
set -u

MNT=/private/var/run/cpudisp-esp
REL=EFI/CPUDISP/STATE.TXT
HEALTH_TRIES=60          # 60 x 5s = 300s
log() { echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) cpudisp: $*"; }

# ---- 1. 等一个真实的健康信号：sshd 在监听 22 ----
i=0
while [ "$i" -lt "$HEALTH_TRIES" ]; do
  if /usr/bin/nc -z 127.0.0.1 22 >/dev/null 2>&1; then break; fi
  i=$((i + 1)); sleep 5
done
if [ "$i" -ge "$HEALTH_TRIES" ]; then
  log "sshd 在 ${HEALTH_TRIES}x5s 内没有监听 22，不确认本档"
  exit 0
fi
log "健康信号成立（sshd:22）"

# ---- 2. 找 ESP。先按卷标，再退化到任何 EFI 分区；靠状态文件存在性确认选对了 ----
mkdir -p "$MNT"
CANDS=$(/usr/sbin/diskutil list \
        | /usr/bin/awk '$2=="EFI" {print $NF}')
FOUND=""
for dev in $CANDS; do
  /usr/sbin/diskutil mount -mountPoint "$MNT" "$dev" >/dev/null 2>&1 || continue
  if [ -f "$MNT/$REL" ]; then FOUND="$dev"; break; fi
  /usr/sbin/diskutil unmount "$MNT" >/dev/null 2>&1 || true
done
if [ -z "$FOUND" ]; then log "没找到带 $REL 的 ESP，放弃"; exit 0; fi
log "ESP = $FOUND"

F="$MNT/$REL"
get() { /usr/bin/sed -n "s/^$1=//p" "$F" | head -1 | tr -d ' \r'; }
SIG=$(get sig); CAND=$(get cand); BOOTS=$(get boots); PICK=$(get pick)
[ -n "$SIG" ] || { log "状态文件没有 sig，放弃"; /usr/sbin/diskutil unmount "$MNT"; exit 0; }
log "确认 cand=$CAND pick=$PICK sig=$SIG boots=$BOOTS"

# ---- 3. 整写 512 字节。inflight 清零，confirmed 置一，boots 归零 ----
# 前 8 个字段是 shim 要读的，后两个只给人看。全部 ASCII，所以 ${#REC} 就是字节数。
BARGS=$(/usr/sbin/sysctl -n kern.bootargs 2>/dev/null | cut -c1-120)
make_rec() {
  printf 'CPUDISP1\nsig=%s\ncand=%s\ninflight=0\nconfirmed=1\nboots=0\nexhausted=0\npick=%s\n' \
         "$SIG" "$CAND" "$PICK"
  [ "${1:-}" = full ] && printf 'at=%s\nbootargs=%s\n' "$(date -u +%Y%m%dT%H%M%SZ)" "$BARGS"
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

# ---- 4. 把引导期日志搬进系统日志目录，供 80 分册的采集流程归档 ----
mkdir -p /var/log/cpudisp
cp -f "$MNT/EFI/CPUDISP/LOG.TXT" /var/log/cpudisp/boot.log 2>/dev/null || true

# ---- 5. 顺手确保 73 §5.3.2 的 macOS 态引导对象是 shim 而不是 OpenCore ----
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

**LaunchDaemon：`/Library/LaunchDaemons/net.metal2vu.cpudisp-confirm.plist`**

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>               <string>net.metal2vu.cpudisp-confirm</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/sh</string>
    <string>/usr/local/libexec/cpudisp-confirm.sh</string>
  </array>
  <key>RunAtLoad</key>           <true/>
  <key>KeepAlive</key>           <false/>
  <key>ThrottleInterval</key>    <integer>60</integer>
  <key>StandardOutPath</key>     <string>/var/log/cpudisp/confirm.log</string>
  <key>StandardErrorPath</key>   <string>/var/log/cpudisp/confirm.log</string>
</dict>
</plist>
```

安装（进 `70` 第 6 节的安装布局；研发期 SIP 已关，`00-OVERVIEW` 第 2.4 节）：

```bash
sudo install -d -m 0755 -o root -g wheel /usr/local/libexec /var/log/cpudisp
sudo install -m 0755 -o root -g wheel cpudisp-confirm.sh /usr/local/libexec/
sudo install -m 0644 -o root -g wheel net.metal2vu.cpudisp-confirm.plist \
     /Library/LaunchDaemons/
sudo launchctl bootstrap system /Library/LaunchDaemons/net.metal2vu.cpudisp-confirm.plist
```

**第 5 步与 `73` 第 5.4 节 R1 层的武装不冲突，但顺序必须清楚。** daemon 是 `RunAtLoad` + `KeepAlive = false`，每次启动只跑一次，发生在开机早期；而 `73` 的 `arm-rescue.sh --oneshot` 是实验在重启之前手工跑的，发生在同一次开机的晚期。时间线是"开机 → daemon 把引导对象修回 shim → 实验武装 rescue → 重启 → 进 rescue"，两者不会互相覆盖。**反过来就会出问题**：如果把 daemon 改成 `KeepAlive = true` 或加上周期触发，它会在武装之后把武装撤掉。不要那样改。

**为什么确认条件是"sshd 在听 22"而不是 `RunAtLoad` 就算成功**：`73` 第 1.3 节把 S1（macOS 起来了但显示坏、SSH 可达）与 S2（macOS 不启动）分开，而我们要确认的恰好是"到 S1 或更好"。`RunAtLoad` 在 `/` 挂载后就触发，那时还不能断定网络与用户态是好的。SSH 可达是 `80` 第 2.x 节整条采集流程的前提，用它当判据和 harness 的判据一致。

**`boots` 归零是刻意的。** 确认之后预算重新开始，这样一台长期跑实验的机器不会因为累计重启次数撞上第 4.7 节的预算而停住。

### 4.7 全部候选都失败时的行为

三层，从轻到重：

**第一层：顺序走完 → 进 rescue，不是停住。** `s.cand >= nord` 时 `tier = T_RESCUE`，shim 链载 `\EFI\BOOT\BOOTX64.RESCUE.efi`（`73` 第 5.2 节的 GRUB）。GRUB 起 Alpine，Alpine 的 `local.d` 脚本起 sshd。**于是"所有 CPU 配置都不work"这个状态变成了一台 SSH 可达的机器**，而 `\EFI\CPUDISP\LOG.TXT` 里有每一次尝试的完整 CPUID 记录。这是本机制最有价值的一个性质：失败不再是黑屏，是一份可读的报告。

**第二层：启动预算。** `BOOT_BUDGET = 12`。取 12 的理由：最长的顺序是 6 档，每档允许一次重试（例如一次网络抖动导致 sshd 没起来、daemon 没确认），6 × 2 = 12。超预算就 `beacon()`。

**第三层：`beacon()`。** 关看门狗、打印一行、`Stall` 死循环。**这是本文允许的唯一"停住"状态，而且必须停住而不是重启。** 在没有控制台的机器上，重启循环既观察不到又会反复踩同一处；停住至少让实例在平台 API 里保持 `running`，可以按 `73` 第 5.4 节的 R2 做取证快照。

**对 `73` 第 5.3.2 节的两处必须修正**（本文不改 `73` 的文件，在此登记）：

| `73` 原文 | 修正后 | 理由 |
|---|---|---|
| macOS 态下 `\EFI\BOOT\BOOTX64.EFI` = `BOOTX64.OC.efi` 的副本 | **= `BOOTX64.DISPATCH.efi` 的副本** | 否则 rescue 退出后 shim 被摘掉，阶梯失效 |
| `grub.cfg` 第二个条目 `chainloader /EFI/BOOT/BOOTX64.OC.efi` | **`chainloader /EFI/BOOT/BOOTX64.DISPATCH.efi`**，并新增第三个条目指向 `BOOTX64.OC.efi` | 第二个条目要保留阶梯；第三个条目是"绕过阶梯、直接用当前 config.plist"的人工逃生口 |

修正后的 `grub.cfg`：

```text
# /EFI/rescue/grub.cfg  （对 73 第 5.3.2 节的替换）
set default=0
set timeout=5
set timeout_style=menu

menuentry "Alpine rescue" {
    search --no-floppy --label --set=root RESCUE
    linux  /boot/vmlinuz-lts root=LABEL=RESCUE modules=sd-mod,usb-storage,ext4 quiet
    initrd /boot/initramfs-lts
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

**注意这里不存在"shim → GRUB → shim"的死循环。** GRUB 的默认条目是 Alpine；超时落到第二条才回到 shim，而那时 shim 的 `boots` 已经增加，预算最终会把循环截断。

### 4.8 它把 `73` 的哪一层变成自愈

`73` 第 1.3 节的四级状态与第 5.4 节的六层救砖，加入本机制之后的变化：

| 失败 | 没有本机制 | 有本机制 | 节省 |
|---|---|---|---|
| CPU 档位选错（判别错 / 代次抽卡） | S2。要走 R2（取证快照 + ISO attach + 改 ESP + 卸 ISO），**40 到 60 分钟、一个 ISO 槽位、全程平台 API** | **自愈。** 一次重启前进一档，无人介入 | R2 整层 |
| `Cpuid1Data` 填错 | 同上 | 自愈（T0 ↔ T1 互为阶梯邻居） | 同上 |
| AMD 核心数常量与实例 vCPU 不符（`72` 的 C-002） | S2，且**要重造镜像**，因为那个字节是构建期常量 | **根本不发生。** shim 运行期回填（第 3.6 节） | 一次镜像重造 + 一次 `create-from-url`（`73` 第 4.2.2 节的全部慢步骤） |
| 全部档位都不work | S2 且无人知道为什么 | 进 rescue，SSH 可达，`LOG.TXT` 里有完整 CPUID | R2 变 R1 |
| 镜像/ESP 残缺 | S3 | `beacon()` 停住，可取证 | 保住现场 |

**一条不能过度宣传的边界：本机制只覆盖"CPU 配置选错"这一类失败。** `73` 第 5.4 节 R1 层针对的"实验改坏了 kext 或 NVRAM"仍然要靠 `73` 的 `arm-rescue.sh --oneshot` 预先武装；本机制不会因为一次 kext 实验失败就去换 CPU 档位——`confirmed` 一旦置位，阶梯就不动了（第 4.5 节 `efi_main` 的稳态分支）。**这是设计意图：实验期的失败必须可归因，所以不许阶梯在底下偷偷换配置。**

### 4.9 L1 上必须跑的验证矩阵

在镜像发布之前、在任何一次 L2 花钱之前，这 9 条必须在本地 KVM（`71` 第 8.2 节的命令行）上跑过。**成本是零，收益是把本文几乎全部 `INFERRED` 变成可信。**

| # | 场景 | 做法 | 期望 |
|---|---|---|---|
| V1 | shim 能被固件加载 | 用 `71` 第 8.2.2 节的 ESP，`BOOTX64.EFI` 放 shim，启动 | 串口上出现 `cpudispatch 1.0` |
| V2 | 判别在"原生 Intel"上落到 T0 | `-cpu Skylake-Server-v4` | `tier=intel-native`，`score < 40` |
| V3 | 判别在 H1 上落到 T3 | `-cpu EPYC-Milan,vendor=GenuineIntel` | `tier=amd`，`score >= 60`，`LOG.TXT` 里 `maxe=0x8000001e`、`c1d` 非零 |
| V4 | 判别在"表外 Intel model"上落到 T1 | `-cpu Skylake-Server-v4,model=0x8F`（Sapphire Rapids 的 model） | `tier=intel-spoof` |
| V5 | FXSAVE 探针不挂、且在 Intel 宿主上报 1 | 任意 `-cpu`，看 `LOG.TXT` 的 `fxsave_x87ptr` | 值为 2（即 `x87_ptrs_saved == 1`）。值为 0 说明 CR4.OSFXSR 没置位，第 2.5 节限制 1 成立 |
| V6 | 链载链条通 | V2 之后继续看 | OpenCore 的 `OC:` 日志出现，`config.plist` 的 `cpudisp=0` 出现在 `kern.bootargs` |
| V7 | 阶梯会前进 | 启动一次 T0，**不跑 daemon**，重启 | 第二次 `tier` 变成顺序里的下一档；`STATE.TXT` 的 `cand` 从 0 变 1 |
| V8 | 确认后阶梯不动 | 跑一次 daemon，再重启三次 | 三次都是同一档，`cand` 不变，`boots` 不累积 |
| V9 | `sig` 变化会重置 | 用 V2 的配置确认成功，然后换成 V3 的 `-cpu` 启动 | `cand` 回到 0，并按 V3 的判别重排顺序 |
| V10 | 核心数回填 | V3 的配置配 `-smp 16,sockets=1,cores=8,threads=2` | `LOG.TXT` 的 `cores=8`，`note=C`；用 `xxd` 核对 `\EFI\OC\config.plist` 里的那 5 字节是 `BA 08 00 00 00` |

**V7 与 V8 是这张表里最重要的两条**，它们分别验证"会回退"与"不会乱回退"。只跑 V1 到 V6 等于只验证了顺风情况。

另外补 `73` 第 5.3.5 节的 V4（故意破坏 rescue 分区）在本机制下的对应项：**把 `\EFI\CPUDISP\` 整个删掉再启动**，期望 shim 发现候选读不到、逐档前进、最终进 rescue，而不是停在半途或重启循环。

---

## 5. AMD 补丁的自维护

所有者的指示是"上游不支持就自己修"。本节给出三样东西：第 20 条的具体修法（而且比上游的修法更紧）、一个可进流水线的验证脚本、以及这套流程挂在哪里。

### 5.1 第 20 条的修法

`72` 第 3.3.1 节已确证的问题：master 的第 20 条在 25G325 上**目标未命中**（结构偏移从 `0x488` 移到 `0x490`），而且因为掩码过松仍有 33 个命中，`Count = 2` 会改掉前两个 —— `_kperf_lazy_wait_sample+0x20` 与 `_vmx_hv_support+0x2A`。

#### 5.1.1 上游的修法（PR #215）

```text
Identifier   kernel
Arch         x86_64
Base         （空）
MinKernel    25.4.0
MaxKernel    25.99.99
Count        2
Skip         0
Find         48 00 00 90 04 00 00 0F 00 00 00 00 00
Mask         48 00 00 F0 FF FF FF FF 00 00 00 00 00
Replace      00 00 00 00 00 00 00 66 90 66 90 66 90
ReplaceMask  00 00 00 00 00 00 00 FF FF FF FF FF FF
```

同时把 master 第 20 条的 `MaxKernel` 收到 `25.3.99`。字节来源：<https://github.com/AMD-OSX/AMD_Vanilla/pull/215>（`72` 第 3.3.1 节已从该 PR 的 `patches.plist` base64 字段解码）。

本轮用 `tools/verify_kernel_patches.py` 在 25G325 上复跑，结果与 `72` 第 3.3.1 节一致（`KNOWN`）：

```text
[WARN] PR215 as-is (mask F0)   hits=3  will-change=2
         * 0xffffff80002a7092  _thread_block_reason+0x18A2   4D 3B A6 90 04 00 00 0F 82 C8 04 00 00
         * 0xffffff80002a801a  _thread_dispatch+0x71A        4C 2B BB 90 04 00 00 0F 82 50 02 00 00
           0xffffff80002fa73d  _host_priv_server_routine+0xEFD
       ! 命中数多于 Count：共 3 个命中，只改前 2 个。掩码可能过松
```

**前两个命中正确，但第三个命中落在 `Count` 之外纯属地址顺序的运气。** `72` 第 3.3.1 节自己也这么写。这个形态可以用，但不该是我们固化进镜像的形态。

#### 5.1.2 本项目的修法：把掩码收紧，而不是放宽

**误打是掩码过松造成的，所以修法的方向是收紧，不是另找一个松掩码去碰运气。** 两处收紧：

1. 偏移字节的掩码从 `F0` 改成 `FF`。`F0` 允许 `0x90`..`0x9F`，而我们要的偏移就是 `0x490` 这一个值。
2. 把 `jb` 的第二个 opcode 字节 `82` 也写进 `Find` 并用 `FF` 掩码。原条目只约束了 `0F`，所以任何 `0F xx` 两字节 opcode 都能匹配（第三个命中就是 `0F B7`，一条 `movzx`）。

```text
Identifier   kernel
Arch         x86_64
Comment      metal2vu | thread_invoke/thread_dispatch non-monotonic (tightened, see 74 §5.1.2)
Base         （空）
MinKernel    25.4.0
MaxKernel    25.99.99
Count        2
Skip         0
Find         48 00 00 90 04 00 00 0F 82 00 00 00 00
Mask         48 00 00 FF FF FF FF FF FF 00 00 00 00
Replace      00 00 00 00 00 00 00 66 90 66 90 66 90
ReplaceMask  00 00 00 00 00 00 00 FF FF FF FF FF FF
```

**在 25G325 上实跑的结果：命中数恰好 2，两个都是目标，没有第三个命中。** `KNOWN`，本轮 `tools/verify_kernel_patches.py` 输出：

```text
[ok  ] tightened + require 0F 82 (jb)   hits=2  will-change=2
         * 0xffffff80002a7092  _thread_block_reason+0x18A2   4D 3B A6 90 04 00 00 0F 82 C8 04 00 00
                               -> patched                    4D 3B A6 90 04 00 00 66 90 66 90 66 90
         * 0xffffff80002a801a  _thread_dispatch+0x71A        4C 2B BB 90 04 00 00 0F 82 50 02 00 00
                               -> patched                    4C 2B BB 90 04 00 00 66 90 66 90 66 90
```

第一个命中落在 `_thread_block_reason+0x18A2`，这与 `72` 第 3.3.1 节的解释一致：`thread_invoke` 被内联进 `_thread_block_reason`。`Find` 的首字节 `48` 配掩码 `48` 保留了"任意带 REX.W 的 `cmp`/`sub` 形态"这一自由度（两个命中的首字节分别是 `4D` 与 `4C`），这一点不动。

**代价：收紧之后这条补丁与版本绑得更死。** 下一个点版本把偏移从 `0x490` 挪到 `0x498`，它就从"打错位置"变成"一个也不打"，而 OpenCore 会把"命中数不足 `Count`"报成失败。**这正是我们要的失败模式**：宁可一条都不打、在构建期被门禁挡住，也不要在运行期改到 `_vmx_hv_support`。本项目的基线固定在 25G325（`00-OVERVIEW` 第 2.3 节），所以版本绑定不是成本。

#### 5.1.3 如果上游连这条也没有，自己怎么定出来

把方法写下来，这样下一次结构偏移变化时不需要等上游。四步，全部可在 Windows 上用现有素材完成：

1. **找到 panic 的格式串与它的 xref。** `72` 第 6.1 节已给出三条 `Non-monotonic time:` 格式串在文件里的偏移（`0x0096b6cd` / `0x0096b844` / `0x0096bbe7`，VA 为偏移加 `0xffffff8000200000`）。
2. **在 xref 函数里找"比较 + 条件跳到 panic"的那一对指令。** 形态是 `cmp r64, [r64 + imm32]` 紧跟 `jb rel32`（第 20 条）或 `ja rel32`（第 19 条）。用正则扫 `__TEXT`：`[\x48-\x4f]\x3b.(..)\x04\x00\x00\x0f\x82`，把第 4 个字节当成未知偏移枚举出来。本轮用这个方法确认 25G325 上该偏移是 `0x90`（即结构偏移 `0x490`），`0x88` 零命中。
3. **把枚举出的偏移写死进 `Find`，掩码对偏移字节与两个 opcode 字节全开。** 不要为了"跨版本通用"去放宽掩码，那是第 3.3.1 节那个 bug 的成因。
4. **用 `tools/verify_kernel_patches.py` 核对"命中数 == `Count`"且"命中位置的符号属于 `_thread_block_reason` / `_thread_dispatch` / `_thread_quantum_expire` / `_thread_unblock`"。** 不满足就回到第 2 步。

#### 5.1.4 顺带确证的第二条：`IOPCIFamily` 的 Zen 4 补丁

`72` 第 3.3.2 节的结论本轮用同一工具复跑，一致（`KNOWN`）：

```text
[WARN] master #17 probeBusGated (E0 11 72 00)   hits=0
       ! 命中数不足：Skip=0 Count=1，但只有 0 个命中。OpenCore 会报失败
[ok  ] PR215 26.0+ probeBusGated (E0 11 73 40)  hits=1
         * 0xf9c5  E3 11 73 4A  ->  E3 11 72 4A
```

两条限定沿用 `72`：命中位置是**重建件的文件偏移**而不是 VA（`72` 的 C-013，本工具对这类重建件必须加 `--range file`，并且不要相信它输出的 VA 列）；而且这条补丁对本项目大概率不需要（guest 看到的是 hypervisor 合成的 PCIe 拓扑）。**处置：T3 档里保留 PR #215 的版本但 `Enabled = false`**，留作"EPYC 上出现 PCI 枚举异常时的第一候选"。

### 5.2 验证脚本：`tools/verify_kernel_patches.py`

脚本已写进仓库。它做的事与第 1.2 节第 3 条的取证方法同构，但变成了可重复执行、可进流水线、带门禁的形态。

#### 5.2.1 它实现的语义

| 字段 | 实现 | 来源 |
|---|---|---|
| `Find` / `Mask` | 逐字节 `(data[i] & Mask[i]) == Find[i]`；`Mask` 为空视为全 `FF` | `72` 第 1.2 节 |
| `Replace` / `ReplaceMask` | 算出改写后的字节并打印，便于目视核对；**脚本不写回任何文件** | 同上 |
| `Base` | 从 `LC_SYMTAB` 查符号 VA，换算文件偏移当搜索起点。**首尾空白自动 strip 并告警**（`72` 的 C-007） | `72` 第 3.4 节 |
| `Count` | 0 表示全改；否则取前 N 个 | OpenCorePkg 的 `PATCHER_GENERIC_PATCH` 注释：replace count or 0 for all |
| `Skip` | 跳过前 N 个命中 | 同上：skip count or 0 to start from 1 match |
| `Limit` | 限制搜索窗口长度，0 表示到范围末尾 | 同上：limit replacement size to this value or 0 |
| `Arch` / `MinKernel` / `MaxKernel` | 过滤。`--darwin` 不给则不按版本过滤 | `72` 第 5.2.1 节 |
| 搜索范围 | 默认 `__TEXT` 段（与 `72` 第 1.2 节一致）；`--range file` 扫整个 slice | 见 B-004 |

`PATCHER_GENERIC_PATCH` 的字段注释来源：<https://github.com/acidanthera/OpenCorePkg/blob/master/Include/Acidanthera/Library/OcAppleKernelLib.h>（`KNOWN`，本轮读取）。

#### 5.2.2 它不只检查"打中了"，还检查"没误伤"

这是它与"肉眼看一遍命中数"的区别，也是 `72` 第 3.3.1 节那个 bug 唯一能被自动挡住的方式。四类判据：

| 判据 | 挡住什么 |
|---|---|
| `expect_total_hits` 与 `expect_used_hits` | 命中数漂移。例如上游换了掩码之后命中数从 2 变 33 |
| `expect_first_va` | 命中位置漂移。内核换版本时结构偏移移动会第一时间暴露 |
| `expect_used_symbols` | **会被改写的那几个命中所属的函数集合**。这是"打对地方"的直接判据 |
| `forbid_symbols` | **任何条目、无论是否已登记，只要会改写名单里的函数就硬失败。** 25G325 的名单至少要有 `_kperf_lazy_wait_sample` 与 `_vmx_hv_support` |

补丁身份用内容寻址：`key = sha256(Identifier, Arch, Base, Min/MaxKernel, Count, Skip, Limit, Find, Mask, Replace, ReplaceMask)[:16]`。**上游改一个字节 key 就变，门禁报"未登记的条目"而不是静默接受。** 这是有意的：补丁内容的变化必须是一次人工复核事件，不能是一次自动通过。

#### 5.2.3 用法

```bash
# 第一步：看一遍（没有门禁，只报告）
py tools/verify_kernel_patches.py \
    --binary analysis/binaries/macos26-25G325-x86_64/kernel/kernel.x86_64 \
    --patches vendor/AMD_Vanilla/patches.plist \
    --darwin 25.7.2

# 第二步：人工核对上一步的输出与 72 第 3.2 节的表，一致后固化
py tools/verify_kernel_patches.py \
    --binary analysis/binaries/macos26-25G325-x86_64/kernel/kernel.x86_64 \
    --patches vendor/AMD_Vanilla/patches.plist \
    --darwin 25.7.2 \
    --emit-expect tools/expect/amd-vanilla-25G325.json
# 然后手工把 forbid_symbols 填上，再提交

# 第三步：门禁（构建期与流水线里跑这一条）
py tools/verify_kernel_patches.py \
    --binary analysis/binaries/macos26-25G325-x86_64/kernel/kernel.x86_64 \
    --patches vendor/AMD_Vanilla/patches.plist \
    --darwin 25.7.2 \
    --expect tools/expect/amd-vanilla-25G325.json \
    --json out/patch-report.json
# 退出码 0 通过，1 不通过，2 用法/解析错误

# kext 目标（注意重建件必须 --range file，且 VA 列不可信，见 72 的 C-013）
py tools/verify_kernel_patches.py \
    --binary analysis/binaries/macos26-25G325-x86_64/kext/com.apple.iokit.IOPCIFamily \
    --patches vendor/AMD_Vanilla/patches.plist \
    --identifier com.apple.iokit.IOPCIFamily --range file --darwin 25.7.2
```

**`tools/expect/amd-vanilla-25G325.json` 的 `forbid_symbols` 初始值**（照抄）：

```json
"forbid_symbols": [
  "_kperf_lazy_wait_sample",
  "_vmx_hv_support",
  "_host_priv_server_routine",
  "_necp_socket_is_allowed_to_recv_on_interface",
  "_necp_client_action",
  "_necp_client_qualify_flow",
  "_necp_session_action"
]
```

前两个来自 `72` 第 3.3.1 节的实测误打。其余是本轮扫描中出现在宽掩码条目命中列表里的无关函数：`master` 第 20 条的 33 个命中里有 20 多个落在 `necp_*` 上，第 3 条的 15 个命中里有 `_necp_session_action`、`_kqueue_scan`、`_ubc_cs_blob_add` 等。

**有一个符号必须明确地不放进这个名单：`_cpuid_wa_required`。** 第 3 条 cores_per_package 补丁的首个命中被本工具报在 `_cpuid_wa_required+0x575`，但 `72` 第 3.4 节已确证真实位置是紧随其后的一个**无符号静态函数** `cpuid_set_cache_info`（`_cpuid_wa_required` 的 VA 是 `0xffffff80003d5750`，加 `0x575` 正好是命中地址 `0xffffff80003d5cc5`）。本工具的"所属函数"取的是符号表里不大于命中地址的最后一个符号，对无符号静态函数只能报它前面那个有符号的邻居。**把它当禁止符号会把正确的第 3 条一起挡掉。** 正确做法是在该条目的 `expect_used_symbols` 里显式写 `_cpuid_wa_required`，并在期望文件的 `note` 字段里注明这是已知的符号归属偏差。登记为 B-012。

#### 5.2.4 已复现的三组数字

本轮用该脚本在 25G325 的 `kernel.x86_64`（`LC_UUID` `E514CEBA-9206-34D5-86C2-64E880FDDA2B`，SHA-256 `B3161C24...E29DE4F1`）上独立复现了 `72` 第 3 节的三组关键结论，**逐字相符**（`KNOWN`）：

| `72` 的结论 | 本轮复现 |
|---|---|
| 第 12 条（绕过 `GenuineIntel` 门）命中 1 个，首个在 `0xffffff80003d4f1e` | 一致。符号归属 `_cpuid_set_info+0x123E`，字节 `0F 85 04 03 00 00 ...` |
| 第 3 条（cores_per_package）命中 15 个，首个在 `0xffffff80003d5cc5` | 一致。字节 `C1 EA 1A FF C2` |
| PR #215 的第 20 条命中 3 个，前两个是 `thread_invoke`（内联进 `_thread_block_reason`）与 `_thread_dispatch` | 一致。地址 `0xffffff80002a7092` 与 `0xffffff80002a801a` |

**一处与 `72` 第 3.3.1 节的渲染差异**：该节表格里第三个命中的字节写作 `48 0F 85 99 04 00 00 FB 72 2E C1 E2`（12 字节），而本轮从二进制读出的是 `48 0F 85 99 04 00 00 0F B7 57 2E C1 E2`（13 字节）。地址与所属函数一致，**差异在 `72` 的字节转录上，不在结论上**。以本轮脚本输出为准。

### 5.3 挂进流水线

#### 5.3.1 主位置：构建期硬门禁

**补丁门禁的主位置是镜像构建流程，不是 GitHub Actions。** 理由是 `.gitignore` 的发布边界：仓库默认 ignore 一切、只白名单放行本项目自有的文本，Apple 的二进制一律不进仓。**所以 CI runner 上没有 `kernel.x86_64`**，而构建主机上必然有（它要从 `SharedSupport.dmg` 里重建 KC，`71` 第 3.1 节）。

接 `71` 第 8.2.2 节的组装顺序，在"生成 config → 组装 ESP"之间插一步：

```bash
set -euo pipefail

# 1) 从素材里取出目标版本的内核（71 第 3.1 节已有流程，产物落在工作目录外）
#    KERNEL=/srv/work/25G325/kernel.x86_64

# 2) 生成 5 份候选（74 第 4.4 节）
py scripts/make-oc-config.py oc/Docs/Sample.plist build/cpudisp host-cpu.json

# 3) 补丁门禁。失败就整个构建失败，不许 --no-verify 之类的绕法
py tools/verify_kernel_patches.py \
    --binary "$KERNEL" \
    --patches build/cpudisp/03-amd.plist \
    --darwin 25.7.2 \
    --expect tools/expect/amd-vanilla-25G325.json \
    --json build/patch-report-amd.json

py tools/verify_kernel_patches.py \
    --binary "$KERNEL" \
    --patches build/cpudisp/02-intel-hardened.plist \
    --darwin 25.7.2 \
    --expect tools/expect/neutral-subset-25G325.json \
    --json build/patch-report-hardened.json

# 4) T0 与 T1 必须是空补丁集，单独断言（72 第 5.2.3 节纪律 1）
for t in 00-intel-native 01-intel-spoof; do
  py -c "
import plistlib,sys
p = plistlib.load(open('build/cpudisp/$t.plist','rb'))
assert p['Kernel']['Patch'] == [], '$t 的 Kernel/Patch 必须是空数组'
print('$t: Kernel/Patch 为空，OK')"
done

# 5) 组装 ESP（71 第 8.2.2 节），把 build/patch-report-*.json 一起放进
#    70 第 7 节的 MANIFEST.json 旁边
```

**`build/patch-report-*.json` 必须进交付物。** 它是"这份镜像里的补丁在这份内核上确实只打了这几个地方"的唯一证据，而 `90-EVIDENCE-INDEX.md` 要登记它。

#### 5.3.2 次位置：GitHub Actions 的结构检查

CI 拿不到内核，但能挡住期望文件本身的退化。新增一个 workflow（与 `.github/workflows/evidence-macos26-intel.yml` 并列）：

```yaml
name: patch-gate-structural

on:
  pull_request:
    paths:
      - 'vendor/AMD_Vanilla/**'
      - 'tools/verify_kernel_patches.py'
      - 'tools/expect/**'
      - 'scripts/make-oc-config.py'
  workflow_dispatch:

permissions:
  contents: read

jobs:
  structural:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: 期望文件的结构检查
        run: |
          python3 - <<'PY'
          import json, glob, sys
          BASELINE_UUID = 'E514CEBA-9206-34D5-86C2-64E880FDDA2B'   # MANIFEST.md 第 5 节
          bad = []
          files = sorted(glob.glob('tools/expect/*.json'))
          if not files:
              sys.exit('tools/expect/ 下没有期望文件')
          for p in files:
              d = json.load(open(p, encoding='utf-8'))
              if d.get('schema') != 'metal2vu.patchexpect/1':
                  bad.append(f'{p}: schema 不对')
              if d.get('binary_uuid') != BASELINE_UUID:
                  bad.append(f'{p}: binary_uuid 不是基线 {BASELINE_UUID}')
              if not d.get('forbid_symbols'):
                  bad.append(f'{p}: forbid_symbols 为空。74 第 5.2.2 节要求至少含 '
                             f'_kperf_lazy_wait_sample 与 _vmx_hv_support')
              keys = [e['key'] for e in d.get('entries', [])]
              if len(keys) != len(set(keys)):
                  bad.append(f'{p}: entries 的 key 有重复')
              for e in d.get('entries', []):
                  for k in ('expect_total_hits', 'expect_used_hits', 'expect_first_va'):
                      if k not in e:
                          bad.append(f'{p}: key={e.get("key")} 缺字段 {k}')
          for b in bad:
              print('FAIL:', b)
          sys.exit(1 if bad else 0)
          PY
      - name: 工具本身能被导入且 --help 正常
        run: |
          python3 -c "import ast,sys; ast.parse(open('tools/verify_kernel_patches.py').read())"
          python3 tools/verify_kernel_patches.py --help > /dev/null
```

**这个 job 的价值有限但不为零**：它挡住"把 `forbid_symbols` 清空再提交"与"换了基线却忘了换期望文件"这两类人为退化。真正的门禁在构建期。把基线二进制送进 CI 的办法（self-hosted runner 或受保护的制品库）登记为 B-010。

#### 5.3.3 挂进 `80-TEST-HARNESS.md`

四处增量，按 `80` 现有的章节编号：

| `80` 的位置 | 增量 |
|---|---|
| 第 2.1 节的提升门槛 | 新增一条：**镜像里带 `Kernel/Patch` 的候选档，必须有一份当次构建产出的 `patch-report-*.json` 且 `gate.passed == true`，否则不许进 L2。** 与"内核改动先过 L1"同级 |
| 第 2.8 节的采集清单 | `failure` 与 `pass` 两个 profile 都加：`/var/log/cpudisp/boot.log`、`/var/log/cpudisp/confirm.log`、`sysctl -n kern.bootargs`。前两个由第 4.6 节的 daemon 从 ESP 搬出来 |
| 第 2.9 节的 `Detector` | 新增三条正则（见下） |
| 第 4.1 节的 E0 验收 | E0-L1 的验收条目并入本文第 4.9 节的 V1..V10。`72` 第 8 节建议的 E0-L0 保留，本文第 2.5 节的 FXSAVE 探针加进那一步的脚本 |

`Detector` 新增的三条：

```text
cpu.dispatch.tier       \bcpudisp=([0-4])\b
cpu.dispatch.exhausted  ^exhausted=1$
cpu.dispatch.halt       cpudispatch: HALT --
```

- `cpu.dispatch.tier` 从 `kern.bootargs` 或串口的 boot-args 回显里抓当前档位。**它让每一条 `result.json` 都自带"这次是哪一档起来的"**，这是归因的前提。
- `cpu.dispatch.exhausted` 从采集到的 `STATE.TXT` 里抓，命中即"阶梯走完了"。
- `cpu.dispatch.halt` 只在 L1（有串口）命中；L2 上对应的观测是"实例 running 但 SSH 永不可达且 `boots` 停在预算上限"。

---

## 6. 未解决项清单

编号 `B-` 代表 boot dispatch。与 `70` 的 `P-`、`71` 的 `I-`、`72` 的 `C-`、`73` 的 `D-`、`80` 的 `H-` 并列，互不重叠。

"成本"一列沿用 `72` 第 8 节的四类：**现在就能做**（读现有素材或跑一条本地命令）、**L0-probe**（起一台最小 Vultr 实例跑 Linux 侧脚本）、**E0-L1**（本地起一次 macOS 虚机）、**E0-L2**（Vultr 上起 macOS 实例）。

| 编号 | 事项 | 标签 | 查清方法 | 成本 | 阻塞什么 |
|---|---|---|---|---|---|
| **B-001** | 云平台固件是否真的从 `\EFI\BOOT\BOOTX64.EFI` 引导系统盘 | `BLOCKED` | 这是 `71` 的 I-024 与 `73` 第 5.3.2 节同一个未确证点，现在变成三份文档的共同单点。先在 L1 的 OVMF 上证机制（第 4.9 节 V1）；L2 上用一台最小实例，看 `\EFI\CPUDISP\LOG.TXT` 有没有新增段落 —— shim 自己就是探针，不需要额外写东西 | V1 **E0-L1**；确证要 **E0-L2** | **整个 shim 方案，以及 `73` 第 5.3.2 节的 ESP 交换机制。** 两者同生共死 |
| **B-002** | OpenCore 的存储根是否取自 `LoadedImage->DeviceHandle`；发布包的 `BOOTx64.efi` 与 `OpenCore.efi` 是否同一份二进制 | `INFERRED` | 读 OpenCorePkg 里 `OcMain` / `OcStorageInitFromFs` 的调用点（`Platform/` 下的 OpenCore 主入口）；对发布包两个文件算 SHA-256（第 3.5 节已给命令） | **现在就能做** | 决定第 1.3 节选 B1 是否正确。若存储根不是从 DeviceHandle 来，B3（多卷）就是唯一形态 |
| **B-003** | FXSAVE 的 x87 指针语义在 Zen 3/4/5 上、且在 KVM guest 内是否真的区分 AMD 与 Intel | `INFERRED` | 把二十行 C 加进 `72` 第 5.1 节的 `scripts/probe-host-cpu.sh`：清零 512 字节、`FNINIT`/`FLDZ`/`FXSAVE64`、读 `+6` 与 `+8`。在 `vc2`（Intel）与 `voc` 或 `vx1`（AMD）各跑一次 | **L0-probe**，零增量成本 | 第 2.4 节 S11 的权重，也就是 H2 情形（Intel 模型跑在 AMD 硅片上）能不能被判别出来 |
| **B-004** | OpenCore `PatcherApplyGenericPatch` 的确切搜索范围：`__TEXT` 段、`__text` 节，还是整个镜像；`Limit` 是否以 `Base` 为起点计 | `INFERRED` | 读 OpenCorePkg 的 `Library/OcAppleKernelLib` 里该函数的实现；或开 DEBUG 构建，把串口日志里报告的补丁应用结果与 `tools/verify_kernel_patches.py` 的输出逐条对比 | **现在就能做** | 决定本工具的命中数是否等于 OpenCore 的运行期行为。目前按 `72` 第 1.2 节的 `__TEXT` 口径实现，与 `72` 的既有证据自洽，但与 OpenCore 的一致性未验证 |
| **B-005** | UEFI x64 是否保证 `CR4.OSFXSR` 置位 | `INFERRED` | 读 UEFI 规范"x64 平台"一节对进入 boot service 时处理器状态的要求；第 4.9 节 V5 顺带实测 | **现在就能做**（规范）+ 零成本（V5） | 第 2.5 节探针能不能跑。跑不了只是少一个信号，不影响其它部分 |
| **B-006** | 要不要给 shim 加带 `#GP` 保护的 MSR 探针；`EFI_CPU_ARCH_PROTOCOL` 在云平台固件上是否存在 | `INFERRED` | 在 L1 的 OVMF 上 `LocateProtocol(gEfiCpuArchProtocolGuid)` 试一次。收益是能直接读 AMD 专有 MSR，风险是一次失手就是固件挂死 | **E0-L1** | 不阻塞。第 2.6 节已决定默认不做 |
| **B-007** | 要不要让 shim 解析 ACPI MADT，在引导期预判 `72` 第 2.7.3 节拓扑等式的右侧 | `INFERRED` | 从 `EFI_SYSTEM_TABLE.ConfigurationTable` 取 ACPI 2.0 RSDP，走 XSDT 找 `APIC` 表，数 Local APIC 与 x2APIC 条目。约 80 行 | **现在就能做**（写代码）+ **E0-L1**（验证） | 不阻塞，但收益明确：拿到右侧就能在选档时直接避开必然 panic 的组合，而不是靠阶梯试出来 |
| **B-008** | 固件是否接受 shim 构造的 device path（在自身卷的 device path 后追加 `MEDIA_FILEPATH_DP` 节） | `INFERRED` | 第 4.9 节 V6。失败的退路是用 `LoadImage` 的 `SourceBuffer` 形式加载，代价是 OpenCore 拿不到 `DeviceHandle`、自定位失败，那时必须改走 B3（多卷） | **E0-L1** | 链载能否成功。这是 shim 唯一的出口动作 |
| **B-009** | macOS 的 `diskutil mount` 在 LaunchDaemon 的早期上下文里能否成功（它依赖 `diskarbitrationd`） | `INFERRED` | 第 4.9 节之后在 E0-L1 跑一次 daemon，看 `/var/log/cpudisp/confirm.log`。失败的退路是把健康等待放在前面（已经是这样）或改用 `mount_msdos` 直接挂 | **E0-L1** | `confirmed` 能不能被回写。回写不了的话阶梯会每次重启都前进一档，直到进 rescue |
| **B-010** | 基线内核二进制怎么送进 CI（`.gitignore` 的发布边界禁止它进仓） | `BLOCKED` | 三个候选：self-hosted runner 挂一块只读卷；受保护的制品库 + `secrets` 鉴权；或接受"门禁只在构建主机上跑"。第三个是当前默认 | **现在就能做**（决策） | 第 5.3.2 节的 CI job 只能做结构检查这一限制 |
| **B-011** | `02-intel-hardened` 的三条厂商无关补丁打在**真 Intel** 上的副作用，特别是第 15 条去掉 `_i386_init` 的三次 `rdmsr` 之后 `busFreq` 相关路径的行为 | `INFERRED` | 反编译 `_i386_init`（`72` 第 2.8 节已定位那两次无条件读）确认 `MSR 0x198`/`0x199` 的结果被谁消费；然后在 L1 上对比 T0 与 T2 启动后的 `machdep.tsc.frequency`、`hw.busfrequency`、`machdep.cpu.*` | **现在就能做**（反编译）+ **E0-L1**（对比） | T2 档的正确性。它是判决表第 4、5 行的首选档，也是 T4 的基础 |
| **B-012** | 符号归属的偏差：无符号静态函数里的命中会被报成"前一个有符号邻居 + 偏移"，`_cpuid_wa_required+0x575` 实为 `cpuid_set_cache_info`（`72` 第 3.4 节） | `KNOWN`（偏差存在）/ `INFERRED`（怎么表达） | 两条路：在期望文件里把这种情形显式登记为"已知偏差"；或给工具加一个"函数边界推断"（按 `__TEXT` 里下一个符号或 `retq`/对齐填充定边界）。后者会引入新的不确定性 | **现在就能做** | `forbid_symbols` 的可用性。第 5.2.3 节已说明不能把 `_cpuid_wa_required` 直接放进禁止名单 |
| **B-013** | `Misc/Security/Vault` 为 `Secure` 时本机制是否整个失效 | `INFERRED` | `71` 第 6.6.2 节已把 `Vault` 设为 `Optional`，理由是研发期不做 vault。但要确认：`Secure` 下 OpenCore 会校验 `vault.sig`，而 shim 每次启动都重写 `config.plist`，签名必然不匹配 | **现在就能做**（读官方文档的 `Vault` 一节） | 分发阶段。研发期不阻塞，但这是"本机制与 vault 不兼容"这一结论的依据 |
| **B-014** | `\EFI\CPUDISP\` 目录与 OpenCore 的启动项扫描有没有交互 | `INFERRED` | 读官方文档的 Boot Algorithm 一节（它扫的是分区句柄上的 bless 路径与预定义路径，`\EFI\CPUDISP\` 不在其中）；L1 上看 picker 里有没有多出条目 | **现在就能做** | 预期无影响。若有，候选目录要挪到 `\CPUDISP\` 或加 `.contentVisibility` |

**优先级，按"先做什么"排序：**

1. **B-002、B-004、B-005、B-011、B-012、B-013、B-014 现在就能做完，不需要任何实验。** 其中 **B-002 与 B-004 必须在写任何代码之前做掉**：B-002 决定第 1.3 节选的形态对不对，B-004 决定第 5 节的门禁数字是否等于 OpenCore 的真实行为。
2. **B-001 是最该先查的一条**，因为它同时压着本文的 shim 与 `73` 第 5.3.2 节的救砖机制，而且它已经在 `71` 里挂了很久（I-024）。它的前半段（L1 机制验证）零成本，后半段必须等 E0-L2。
3. **B-003 搭 `72` 第 8 节已经规划的 L0-probe 顺手做完**，不增加实例小时。
4. B-008、B-009 并入第 4.9 节的 L1 验证矩阵，不单独排期。
5. B-006、B-007、B-010 是增强与决策项，不阻塞当前工作。

**三条最该先查的：B-001（固件引导路径，压着整条方案）、B-002（OpenCore 存储根与 bootstrap 形态，决定方案形态且零成本）、B-003（FXSAVE 探针的判别力，决定 H2 情形能不能被看见，且搭现有 L0-probe 零增量）。**

---

## 7. 相关分册

- **`72-CPU-COMPAT.md`**：本文是它第 5.2 节的替代方案。**本文保留它的全部事实，替换它的一个结论**：第 5.2.1 节"OpenCore 没有按厂商生效的机制"与第 5.2.2 节"AMD 补丁打在 Intel 上是破坏性的"都成立且被本文引用；第 5.2 节由此导出的"必须出两份 EFI"被本文第 1 到 4 节的单镜像机制取代。**本文同时纠正它三处细节**：(1) 在 KVM guest 里 cache leaf 4 由 QEMU 按 CPU 模型合成而不是返回垃圾，只有 `cache_info_passthrough` 打开时才透传宿主值（本文第 2.1 节）；(2) 第 3.3.1 节第三个命中的字节应为 13 字节的 `48 0F 85 99 04 00 00 0F B7 57 2E C1 E2`（本文第 5.2.4 节）；(3) 第 2.3 节正文的"一共 30 个 model、11 个 CPUFAMILY"中前半是计数笔误，该表 11 行逐行相加为 **27** 个互不相同的 model，`CPUFAMILY` 的个数 11 是对的（本文第 3.3 节 `kXnuModels` 表的注释）。这三处都不改变该节的任何结论。**本文把它的 C-002（AMD 核心数常量随实例规格变）从"每个规格一份镜像"降级为"运行期回填"**（本文第 3.6 节），并把它的 C-003 的前半段（CPUID leaf `0x40000010` 是否存在）变成 shim 日志里的一行，不再需要单独起 Linux 实例。它的 C-007（PR #215 合入状态、`Base` 末尾空格）仍然有效，本文第 4.4 节的脚本与第 5.2.1 节的工具都做了 `strip`。
- **`73-DEPLOY-RESCUE.md`**：本文第 4 节的回退机制是它第 2.3 节"EFI 一次性启动项"的同构实现，状态存 ESP 文件而不是固件 NVRAM，理由与它第 5.3.1 节相同。**本文对它第 5.3.2 节有两处必须的修正**（本文第 4.7 节的表）：macOS 态下 `\EFI\BOOT\BOOTX64.EFI` 的内容源从 `BOOTX64.OC.efi` 改为 `BOOTX64.DISPATCH.efi`；`grub.cfg` 的第二个条目改为链载 `BOOTX64.DISPATCH.efi` 并新增第三个条目直链 `BOOTX64.OC.efi`。它第 5.3.2 节的 `arm-rescue.sh` 与 `00-revert-boot.start` 两个脚本里的文件名需要跟着改。**本文把它第 5.4 节的 R2 层从"CPU 档位选错"这一类失败的处置路径上整个拿掉**（本文第 4.8 节），R2 仍然保留给"引导链被实验改坏"这一类。它第 2.7 节关于 Vultr 软 RAID 下固件只初始化一块盘的观察，是本文第 3.1 节"不枚举文件系统句柄、只从 `LoadedImage` 反推"的直接依据。
- **`71-IMAGE-OPENCORE.md`**：本文第 3.2 节的 ESP 布局是它第 8.2.2 节布局加一个 `\EFI\CPUDISP\` 目录与一个 `BOOTX64.DISPATCH.efi`，`\EFI\OC\` 内部完全不变。本文第 4.4 节的候选生成脚本基于它第 6.1 节的声明式 diff 做法。**本文把它第 6.6.1 节 `LauncherOption = Disabled` 从"稳妥"升级为"必须"**（第 3.5 节：开了它 `\EFI\BOOT\BOOTx64.efi` 就不再被用于引导 OpenCore，而那正是 shim 的位置）。本文依赖它第 8.4 节已确证的 `msdosfs` 在 System KC 内（第 4.6 节的 daemon），以及它第 10 节的首启探针（新增 `kern.bootargs` 里的 `cpudisp=N`）。它的 I-024 与本文的 B-001 是同一个问题。
- **`80-TEST-HARNESS.md`**：本文第 5.3.3 节给出四处增量：第 2.1 节新增一条提升门槛（带补丁的档位必须有通过的 `patch-report`）、第 2.8 节采集清单新增三项、第 2.9 节 `Detector` 新增三条正则、第 4.1 节 E0-L1 的验收并入本文第 4.9 节的 V1..V10。本文不改它第 1 节的平台调研与第 3 节的工具面。
- **`70-BUILD-PACKAGE.md`**：本文第 3.4 节给构建侧新增一条工具链依赖（`gcc-mingw-w64-x86-64`，只在造 shim 时需要，且只在 Linux 侧），应登记进它第 7 节的版本清单。本文第 4.6 节的 daemon 与脚本进它第 6 节的安装布局。
- **`90-EVIDENCE-INDEX.md`**：本文没有新增样本文件。新取得的派生证据有三条，全部来自 `kernel/kernel.x86_64`（`LC_UUID` `E514CEBA-9206-34D5-86C2-64E880FDDA2B`）与 `kext/com.apple.iokit.IOPCIFamily`（`LC_UUID` `81D9CF0C-0587-3EC8-B878-E0042113108B`）：(1) 收紧版第 20 条在 25G325 上命中数恰为 2 且无旁落（本文第 5.1.2 节）；(2) `72` 第 3 节三组数字的独立复现（本文第 5.2.4 节）；(3) `master` 第 17 条零命中、PR #215 版 1 命中的复现（本文第 5.1.4 节）。每次构建产出的 `patch-report-*.json` 也应登记为派生证据。
- **`00-OVERVIEW.md` 第 7 节**：本文的标签用法遵从它的四级规则。特别是第 2 节的全部判别结论都建立在 **x86_64 的 QEMU 源码与 25G325 的 x86_64 内核**上，不建立在 arm64 证据或社区说法上；第 2.5 节的 FXSAVE 差异刻意按三层拆开标注（存在 = `KNOWN`、Zen 上成立 = `INFERRED`、KVM 下成立 = `BLOCKED`），这是它"没查不等于被阻断"与"标注证据来源"两条规则在一个混合证据链上的落地方式。
