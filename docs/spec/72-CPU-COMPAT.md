# 72 CPU 兼容性：macOS 26.7.2 (25G325) x86_64 在 Xeon 与 EPYC 上，以及 OpenCore 侧的补丁

文档版本：1.0
基线日期：2026-10-30
对应组件：无（基础设施分册）
上级文档：`docs/spec/00-OVERVIEW.md`
配套分册：`docs/spec/71-IMAGE-OPENCORE.md`、`docs/spec/70-BUILD-PACKAGE.md`、`docs/spec/80-TEST-HARNESS.md`

## 0. 本文作用与写作约束

本文回答一个问题：**当宿主 CPU 不由我们选择、`-cpu` 参数不由我们书写时，macOS 26.7.2 x86_64 能不能在云平台给的那颗 CPU 上起来，以及 OpenCore 侧要做什么。**

它是 `71-IMAGE-OPENCORE.md` 的 CPU 侧补充。职责边界：

- **`71` 第 5 节讨论的是"我们能写 `-cpu` 时选哪个模型"**，结论是 `Skylake-Server-v4`。那一节在本地 KVM（`80` 第 1.7 节的 L1 层）成立。本文讨论的是 L2 层：云平台自己创建 guest，`-cpu` 由它决定，CPUID 报什么 vendor、什么 family/model、暴露哪些 feature bit，我们**一个字节都改不了**。社区惯用的 `-cpu Penryn,vendor=GenuineIntel,kvm=on` 这类手段在 L2 上不可用。
- 本文不重复 `71` 第 4 节的 SMBIOS / board-id 结论。`MacPro7,1` 的选型、`PlatformSupport.plist` 的 8 个 board-id、`AppleIntelMCEReporter` 与 `AppleGraphicsDevicePolicy` 两个 board-id 门，全部以 `71` 第 4 节为准，本文只引用。
- 本文不重复 `70` 第 5 节的 SIP/AMFI 方案与 `71` 第 6.7 节的 NVRAM 写法。
- 本文不重复 `71` 第 9 节的串口配置。本文第 6 节只做"失败现象如何归因"这一件事，串口怎么配看 `71` 第 9 节。

**本文修正了 `71` 的三处内容**，依据是本轮对 25G325 x86_64 内核二进制的直接取证，逐条在第 2.6、2.7、5.3 节给出。

写作约束同 `70`、`71`、`80`：

- 每条结论带证据标签（`KNOWN` / `INFERRED` / `BLOCKED`）与来源。
- **本项目至今 `TESTED` 数量为零，本文没有 `TESTED`。**
- `KNOWN` 只给二进制、源码或官方文档直接证明的结论。社区经验一律 `INFERRED` 并注明出处与时效。
- 补丁条目给出 `Base` / `Find` / `Replace` / `Mask` 的实际字节时必须说明来源。拿不到就标 `BLOCKED`，不编。
- 对外部网页内容均为转述，不作连续摘录。**内容已转述以符合许可限制。**

---

## 1. 取证方法

本文的一手证据全部来自仓库内已有的 25G325 x86_64 样本，没有任何一条来自运行中的系统。

### 1.1 样本

`KNOWN`，来源 `analysis/binaries/macos26-25G325-x86_64/MANIFEST.md` 第 5 节与第 3 节。

| 样本 | 字节 | 架构 | `LC_UUID` | `LC_SOURCE_VERSION` |
|---|---:|---|---|---|
| `kernel/kernel.x86_64` | 19,008,056 | `x86_64` | `E514CEBA-9206-34D5-86C2-64E880FDDA2B` | `12377.161.15.701.48` |
| `kext/com.apple.iokit.IOPCIFamily` | 13,338,090 | `x86_64` | `81D9CF0C-0587-3EC8-B878-E0042113108B` | `726.100.6.0.0` |
| `payloadv2-full-index.tsv.zip` | 458,715 条路径 | 跨架构 | — | — |

内核来源层级是 **installed SystemOS payload**（`payload.024`，逻辑路径 `System/Library/Kernels/kernel`），不是 BaseSystem，不是运行时抓取。

**版本对齐**：`LC_SOURCE_VERSION` 的主版本是 `12377`，即 xnu-12377 一系，对应 Darwin 25。Apple 公开源码的 tag 是 `xnu-12377.121.6` 一系（`KNOWN`，<https://github.com/apple-oss-distributions/xnu/tags>），比本样本的 `12377.161.15` 略旧。**因此本文凡涉及具体字节与具体分支的结论一律直接取自样本，不取自公开源码**；公开源码只用于解释符号名的语义。

### 1.2 方法

三条独立手段，互相印证：

1. **符号表**：按 `LC_SYMTAB` 枚举 23,795 个 `N_SECT` 符号，得到函数地址与 `__TEXT` / `__DATA` 布局。
2. **Hex-Rays 反编译**：对 `_cpuid_set_info`、`_tsc_init`、`_xcpm_bootstrap`、`_xcpm_init`、`_mca_cpu_init`、`_i386_lbr_init`、`_x86_validate_topology`、`_cpu_topology_sort`、`_cpuid_vmm_info` 逐个反编译，读出实际分支与常量。
3. **字节级图样匹配**：把 `AMD_Vanilla` 的 25 条补丁按 OpenCore 的 `Find`/`Mask`/`Base`/`Count` 语义在本样本上实际跑一遍，统计命中数与命中位置。这一步把"社区说能用"变成"在这份二进制上命中/未命中"。

掩码比较按 OpenCore 的语义实现：`(data[i] & Mask[i]) == Find[i]`；`Base` 只作为搜索起点，不作为函数边界；`Count = 0` 表示全部命中都改。

**`__TEXT` 布局**（`KNOWN`，用于把下文的 VA 换成文件偏移）：

```text
__TEXT           vm=0xffffff8000200000 size=0xa00000 fileoff=0x0      filesize=0xa00000
__DATA           vm=0xffffff8000c00000 size=0x2da000 fileoff=0xa00000  filesize=0x2da000
__DATA_CONST     vm=0xffffff8000eda000 size=0xd7000  fileoff=0xcda000  filesize=0xd7000
__HIB            vm=0xffffff8000100000 size=0xb0000  fileoff=0xdf1000  filesize=0xb0000
__LINKEDIT       vm=0xffffff8001053000 size=0x240000 fileoff=0xfe1000  filesize=0x23fa38
```

即 `__TEXT` 的 VA 与文件偏移差为固定的 `0xffffff8000200000`。本文给出的 VA 都可以直接减掉这个常量得到文件偏移。

**一条对 `71` 第 11 节 I-015 的顺带确证**（`KNOWN`，本轮符号表查询）：`71` 第 9.5 节依赖的四个 early serial 补丁符号在 25G325 的 x86_64 内核中**全部存在**：

| 符号 | VA | section |
|---|---|---|
| `_disable_serial_output` | `0xffffff8000f79414` | 11（`__DATA_CONST` 域内的 bool） |
| `_kernel_debug_string_early` | `0xffffff80007803b0` | 1（`__TEXT`） |
| `_panic` | `0xffffff8000abbacc` | 1 |
| `_vstart` | `0xffffff80003de970` | 1 |

**I-015 可以关闭**，`71` 第 9.5 节的 early serial 兜底手段在 25G325 上可用。

---

## 2. A. macOS 26 原生支持哪些 CPU，门在哪

### 2.1 受支持机型的真实微架构

`71` 第 4.1、4.2 节已确证 25G325 的 `SupportedModelProperties` 只有 6 个机型。它们的 CPU 微架构：

| 机型 | CPU | 微架构 | CPUID family/model | 来源标签 |
|---|---|---|---|---|
| `MacPro7,1` | Xeon W-3223 / 3235 / 3245 / 3265M / 3275M | **Cascade Lake-W** | 6 / `0x55` | `INFERRED`，型号见下 |
| `MacBookPro16,1` | Core i7-9750H / i9-9880H / i9-9980HK | Coffee Lake-H（9 代） | 6 / `0x9E` | `INFERRED` |
| `MacBookPro16,4` | 同 16,1 | Coffee Lake-H | 6 / `0x9E` | `INFERRED` |
| `MacBookPro16,2` | Core i5-1038NG7 / i7-1068NG7 | Ice Lake-U（10 代） | 6 / `0x7E` | `INFERRED` |
| `iMac20,1` | Core i5-10500 / i7-10700K | Comet Lake-S（10 代） | 6 / `0xA5` | `INFERRED` |
| `iMac20,2` | Core i9-10910 | Comet Lake-S | 6 / `0xA5` | `INFERRED` |

`MacPro7,1` 的 CPU 型号来源：机型规格记录给出的处理器是 Xeon W 的 3223 / 3235 / 3245 / 3265M / 3275M 系列，分别为 8 / 12 / 16 / 24 / 28 核（转述自 <https://everymac.com/systems/apple/mac_pro/mac-pro-tower-faq/differences-between-mac-pro-tower-workstation-2019-models.html> 与 <https://everymac.com/systems/apple/mac_pro/specs/mac-pro-28-core-2.5-xeon-w-silver-tower-workstation-2019-specs.html>，`KNOWN` 对于"是 Xeon W-3200 系列"这一点）。Xeon W-3200 属 Cascade Lake-W，与 Xeon Scalable 第二代（Cascade Lake-SP）共用 CPUID `06_55H`。

**"Xeon 不被 macOS 支持"这个说法是错的，而且错得很彻底。** 两条理由，第二条是决定性的：

1. `MacPro7,1` 本身就是一台 Xeon 工作站，它的 board-id `Mac-27AD2F918AE68F61` 在 25G325 的 `SupportedBoardIds` 里（`71` 第 4.1 节，`KNOWN`）。
2. 更重要的是，**内核的 CPU 门不看机型，只看 CPUID family/model**，而它接受的 model 清单比 6 个机型宽得多。下一节给出全表。

### 2.2 `_cpuid_set_info` 的两道门

`KNOWN`，来源：本样本 `_cpuid_set_info` @ `0xffffff80003d3ce0`（函数长度 5,479 字节，`0xffffff80003d3ce0`..`0xffffff80003d5247`）的 Hex-Rays 反编译。`cpuid_set_generic_info()` 与 `cpuid_set_cpufamily()` 都被内联进这个函数。

两道门串在一起，走到同一个 panic：

```c
/* 门 1：厂商串 */
v144 = strlen("Unknown CPU Typ") + 1;        /* = 16 */
v145 = (v144 < 0x10) ? v144 : 16;            /* = 16 */
if (strncmp("GenuineIntel", cpuid_vendor, v145) != 0)
    goto LABEL_204;                          /* 直接 panic */

/* 门 2：family/model 必须映射出一个已知 CPUFAMILY */
v146 = 0;        /* cpufamily */
v147 = 1;        /* "未识别" 标志 */
if (cpuid_family == 6) {
    switch (cpuid_model) {
        ...                                  /* 见 2.3 的全表 */
        LABEL_172: v147 = 0; break;          /* 命中任一 model 才清零 */
        default: break;
    }
}
cpuid_cpufamily = v146;
if (cpuid_dbg) kprintf("cpuid_set_cpufamily(%p) returning 0x%x\n", info_p, v146);
if (v147 != 0)
LABEL_204:
    panic("Unsupported CPU @%s:%d", "cpuid.c", 1183);
```

三条可直接用于诊断的事实：

1. **panic 文本是 `Unsupported CPU`，源文件位置是 `cpuid.c:1183`。** `KNOWN`，字符串 `"Unsupported CPU @%s:%d"` 在 `__TEXT` 的 VA `0xffffff8000b7c8a2`，唯一 xref 来自 `_cpuid_set_info`。
2. **`AuthenticAMD` 在门 1 就死。** 不是"功能受限"，是启动期立刻 panic。厂商串比较长度是 16 字节、从 `"GenuineIntel"` 起算，所以任何非 `GenuineIntel` 的厂商串都不通过。
3. **`cpuid_family != 6` 也在门 2 死。** 整个 `switch` 包在 `if (family == 6)` 里面，family 15（P4）、family 0x17/0x19/0x1A（AMD Zen）一律落到 `v147 = 1`。

### 2.3 family/model → CPUFAMILY 全表

`KNOWN`，逐条来自上述反编译的 `switch` 常量。CPUFAMILY 常量的符号名按 `mach/machine.h` 的公开定义对齐（`INFERRED` 仅限于名字，数值是从二进制读出的）。

| `cpuid_model`（十进制 / 十六进制） | 返回的 CPUFAMILY（十进制 / 十六进制） | 符号名 | 典型产品 |
|---|---|---|---|
| 23 / `0x17` | 2028621756 / `0x78EA4FBC` | `CPUFAMILY_INTEL_PENRYN` | Penryn |
| 26 / `0x1A`、30 / `0x1E`、31 / `0x1F`、46 / `0x2E` | 1801080018 / `0x6B5A4CD2` | `CPUFAMILY_INTEL_NEHALEM` | Nehalem、Lynnfield、Nehalem-EX |
| 37 / `0x25`、44 / `0x2C`、47 / `0x2F` | 1463508716 / `0x573B5EEC` | `CPUFAMILY_INTEL_WESTMERE` | Westmere、Westmere-EP/EX |
| 42 / `0x2A`、45 / `0x2D` | 1418770316 / `0x5490B78C` | `CPUFAMILY_INTEL_SANDYBRIDGE` | Sandy Bridge、**Sandy Bridge-EP** |
| 58 / `0x3A`、62 / `0x3E` | 526772277 / `0x1F65E835` | `CPUFAMILY_INTEL_IVYBRIDGE` | Ivy Bridge、**Ivy Bridge-EP** |
| 60 / `0x3C`、63 / `0x3F`、69 / `0x45`、70 / `0x46` | 280134364 / `0x10B282DC` | `CPUFAMILY_INTEL_HASWELL` | Haswell、**Haswell-EP**、Haswell-ULT、Crystalwell |
| 61 / `0x3D`、71 / `0x47` | 1479463068 / `0x582ED09C` | `CPUFAMILY_INTEL_BROADWELL` | Broadwell、Brystalwell |
| 78 / `0x4E`、**85 / `0x55`**、94 / `0x5E` | 939270559 / `0x37FC219F` | `CPUFAMILY_INTEL_SKYLAKE` | Skylake-U/Y、**Skylake-SP / Cascade Lake-SP / Cascade Lake-W / Cooper Lake**、Skylake-S/H |
| 125 / `0x7D`、126 / `0x7E`、159 / `0x9F` | 943936839 / `0x38435547` | `CPUFAMILY_INTEL_ICELAKE` | Ice Lake-DT、Ice Lake-U/Y、Ice Lake-H |
| 142 / `0x8E`、158 / `0x9E` | 260141638 / `0x0F817246` | `CPUFAMILY_INTEL_KABYLAKE` | Kaby Lake-U、**Kaby Lake / Coffee Lake-S/H、Xeon E-2100/E-2200** |
| 165 / `0xA5` | 486055998 / `0x1CF8A03E` | `CPUFAMILY_INTEL_COMETLAKE` | Comet Lake-S/H |
| 其它一切 | 0 | `CPUFAMILY_UNKNOWN` | **panic** |

一共 30 个 model、11 个 CPUFAMILY。

**第 8 行是本文最重要的一行事实。** `model 0x55` 是 Intel 把 Skylake-SP、Cascade Lake-SP、Cascade Lake-W、Cooper Lake 全部塞进去的那一个 model 号（它们靠 stepping 区分），而 macOS 26 把它映射到 `CPUFAMILY_INTEL_SKYLAKE`。所以：

> **Xeon Scalable 第一代（Skylake-SP）与第二代（Cascade Lake-SP）在 macOS 26.7.2 上是原生受支持的 CPU，不需要任何 CPUID 伪装。** `KNOWN`。

`06_55H` 对应 Xeon Scalable 系列这一点有 Intel 自己的确认（转述自 <https://community.intel.com/t5/Processors/About-crystal-frequency-slow-down-in-Xeon-non-skylake/m-p/1204170>，文中以 `CPUID signature 06_55H` 指称 Xeon Scalable 家族）。

### 2.4 把 Xeon Scalable 各代套进这张表

| 代次 | 产品名 | CPUID DisplayFamily_DisplayModel | 在 2.3 的表里？ | 结果 |
|---|---|---|---|---|
| 第 1 代 | Xeon Scalable (Skylake-SP) | `06_55H` | **在** | **原生受支持** |
| 第 2 代 | Xeon Scalable (Cascade Lake-SP) | `06_55H` | **在** | **原生受支持**，与 `MacPro7,1` 同 model |
| 第 2 代 refresh | Cooper Lake-SP | `06_55H` | **在** | `INFERRED` 原生受支持 |
| 第 3 代 | Ice Lake-SP | `06_6AH` | **不在** | **panic `Unsupported CPU`** |
| 第 4 代 | Sapphire Rapids | `06_8FH` | **不在** | **panic** |
| 第 5 代 | Emerald Rapids | `06_CFH` | **不在** | **panic** |
| 第 6 代 | Granite Rapids / Sierra Forest | `06_ADH` / `06_AFH` | **不在** | **panic** |
| Xeon E-2100/E-2200 | Coffee Lake 服务器变体 | `06_9EH` | **在** | **原生受支持**（与 `MacBookPro16,1` 同 model） |
| Xeon E-2300 | Rocket Lake 服务器变体 | `06_A7H` | **不在** | **panic** |

`KNOWN` 对于"在不在 2.3 的表里"与"不在就 panic"；**`INFERRED` 对于各代次的 DisplayModel 取值**，依据是 Intel 公开的 CPUID 签名约定与型号表，查清方法见第 7 节 C-001。

注意第 3 代 Ice Lake-SP 的陷阱：macOS 26 支持 **Ice Lake 客户端**（model `0x7D`/`0x7E`/`0x9F`，`MacBookPro16,2` 就是 `0x7E`），但 **Ice Lake-SP 是 `0x6A`，不在表里**。"Ice Lake 被支持"这句话按 SKU 分叉，不能整代推断。这是整条 Xeon 路线上最容易判断错的一点。

### 2.5 指令集下限：三个不同的下限，不要混

社区的说法是"macOS 13 及以上需要 AVX2"（转述自 <https://dortania.github.io/OpenCore-Install-Guide/macos-limits>，该文同时给出 SSE3 / SSSE3 / SSE4 / SSE4.2 的逐版本下限）。本样本把这件事拆成三层，三层的后果完全不同。

#### 下限 1：内核启动。只要 family/model 过关，没有额外的指令集门

`KNOWN`。`_cpuid_set_info` 在门 2 之后不再对 feature bit 做任何会 panic 的检查。内核本体没有"没有 AVX2 就拒绝启动"的分支。

#### 下限 2：`cpu_subtype` 是否为 `x86_64h`。这一层才是 AVX2 的真实位置

`KNOWN`，来自同一反编译，紧接在门 2 之后：

```c
cpuid_cpu_type = 7;                                   /* CPU_TYPE_X86 */
if (!PE_parse_boot_argn(bootArgs, "-enable_x86_64h"))
    if (PE_parse_boot_argn(bootArgs, "-disable_x86_64h")) enable = 0;

if (enable == 0
 || (~cpuid_features       & 0x10D0100000000000ULL) != 0   /* leaf 1 ECX  */
 || ( cpuid_extfeatures    & 0x0000002000000000ULL) == 0   /* leaf 0x80000001 ECX */
 || (~cpuid_leaf7_features & 0x0000000000000128ULL) != 0)  /* leaf 7 EBX  */
        cpuid_cpu_subtype = 4;
else    cpuid_cpu_subtype = 8;                        /* CPU_SUBTYPE_X86_64_H */
```

把三个掩码展开（`KNOWN`，掩码值直接取自二进制；位到名字的映射按 Intel 的 CPUID 定义）：

| 掩码 | 来源寄存器 | 要求的位 | 对应特性 |
|---|---|---|---|
| `0x10D0100000000000` | leaf 1 ECX（在 64 位 features 的高 32 位） | 28、23、22、20、12 | **AVX**、POPCNT、MOVBE、**SSE4.2**、**FMA** |
| `0x2000000000` | leaf `0x80000001` ECX 位 5 | 37 | **LZCNT / ABM** |
| `0x128` | leaf 7 EBX | 3、5、8 | **BMI1**、**AVX2**、**BMI2** |

即 `x86_64h` 要求 AVX + FMA + SSE4.2 + MOVBE + POPCNT + LZCNT + BMI1 + BMI2 + AVX2，和 Haswell 的特性集一致。

**缺任一项的后果不是 panic，是 `cpu_subtype` 退回 4 而不是 8。** 这会改变 dyld 选用哪一套 shared cache 与哪一个 fat slice。对本项目有一条直接影响：`libMTLIGCCompilerPlugin.dylib` 的架构是 **`x86_64h` / subtype 8**（`KNOWN`，`MANIFEST.md` 第 10.1 节），即 Metal compiler plugin 这条路上确实存在只给 `x86_64h` 的二进制。登记为 C-010。

#### 下限 3：用户态。AVX2 在这一层是事实上的硬性要求

`INFERRED`，来源是社区文档而非本样本：macOS 13 起用户态大量使用 AVX2，而 Apple 保留的那套不含 AVX2 指令的 dyld cache 默认不安装、需要 `CryptexFixup` 之类手段强制安装（转述自 <https://dortania.github.io/OpenCore-Install-Guide/macos-limits>）。

**本项目的下限结论**：2.1 节的 6 个受支持机型里最老的是 Coffee Lake-H 一代，全部有 AVX2，所以 Apple 在 26 里没有任何动机保留 pre-AVX2 路径。把 **AVX + AVX2 + FMA + BMI1/2 + LZCNT + SSE4.2 + MOVBE + POPCNT 当作硬性下限**。

**AVX-512 不是下限。** `KNOWN`：`x86_64h` 的三个掩码里没有任何 AVX-512 位；本样本中与 AVX-512 相关的符号是 `_fp_avx512_offset`、`_ml_fpu_avx512_enabled`、`_avx512_zero`、`_fpu_capability`，即 AVX-512 只影响 FPU save state 的大小与 XSAVE 布局，不参与任何启动门。Xeon Scalable 全系有 AVX-512，这既不帮忙也不添乱；它唯一的下游影响在 Lavapipe 的 LLVM 后端选路，那是 `71` 的 I-012。

### 2.6 `AppleIntelCPUPowerManagement` 已经不存在，XCPM 在虚机里被关掉

**本节修正 `71` 第 5.3 节与第 6.5.3 节的两处配置含义。**

#### 2.6.1 `AppleIntelCPUPowerManagement.kext` 不在 25G325 里

`KNOWN`，否定性证据，方法可复现：在 `payloadv2-full-index.tsv.zip` 的 **458,715 条路径**里检索子串，结果如下。

| 检索子串 | 命中数 |
|---|---:|
| `AppleIntelCPUPowerManagement` | **0** |
| `AppleIntelCPUPower` | **0** |
| `AppleTyMCEDriver` | **0** |
| `AppleIntelMCEReporter` | 8（bundle 目录 + `Info.plist` + `version.plist` + `CodeResources`） |
| `X86PlatformPlugin` | 67（含 50 份 per-board-id 的 `Resources/Mac-*.plist`） |
| `VMPlatformPlugin` | 3（bundle 目录条目） |

复现命令：

```powershell
py - <<'PY'
import zipfile, io
z = zipfile.ZipFile(r"analysis\binaries\macos26-25G325-x86_64\payloadv2-full-index.tsv.zip")
n = z.namelist()[0]
keys = ["AppleIntelCPUPowerManagement", "AppleTyMCEDriver", "AppleIntelMCEReporter",
        "X86PlatformPlugin", "VMPlatformPlugin"]
cnt = {k: 0 for k in keys}
with z.open(n) as f:
    for line in io.TextIOWrapper(f, encoding="utf-8", errors="replace"):
        for k in keys:
            if k in line: cnt[k] += 1
print(cnt)
PY
```

两条直接后果：

1. **`Kernel/Quirks/AppleCpuPmCfgLock` 在 25G325 上是空操作。** 它打的补丁对象是 `AppleIntelCPUPowerManagement`，那个 kext 不存在。`71` 第 6.5.3 节把它设为 `false` 是对的，但理由应该更新为"目标不存在"而不是"真机 MSR 锁定与我们无关"。
2. **`Kernel/Emulate/DummyPowerManagement` 在 25G325 上同样是空操作。** OpenCore 官方对它的描述是"禁用 `AppleIntelCpuPowerManagement`"，并把 `Requirement` 标为 **10.4-12**（转述自 <https://dortania.github.io/docs/latest/Configuration.html>）。macOS 26 的 Darwin 版本是 25，远超 12。`71` 第 5.3 节把它设为 `true` 无害，但它不提供任何保护，**不能把它当成"CPU 电源管理已经被安全地关掉了"的依据**。
3. **`Kernel/Block` 里针对 `com.apple.driver.AppleTyMCEDriver` 的那条（`71` 第 6.5.5 节提到参考配置里有、默认关）在 25G325 上没有目标。** 保持关闭，不需要再评估。

#### 2.6.2 XCPM 存在，但在任何报告了 hypervisor 位的 guest 里被整条关掉

`KNOWN`，来源：`_xcpm_bootstrap` @ `0xffffff800040b050` 的反编译。函数的第一个决策点：

```c
v5 = cpuid_features();
if ((int64_t)v5 < 0) {          /* 即 features 的 bit 63 */
LABEL_15:
    xcpm_mode = 0;              /* XCPM 整条关闭 */
} else {
    switch (cpuid_model) {      /* 只有命中下表才 xcpm_mode = 1 */
        ...
        default: goto LABEL_15;
    }
}
```

`cpuid_features()` 返回的是 `(leaf1.ECX << 32) | leaf1.EDX`，所以 **bit 63 就是 leaf 1 ECX 的 bit 31，即 hypervisor-present 位**。KVM、VMware、Hyper-V、Parallels 都无条件设置这一位。

> **结论：在任何 KVM guest 里 `xcpm_mode == 0`，XCPM 不初始化。** `KNOWN`。

配套确证：`_xcpm_init` @ `0xffffff800040bb40` 的整个函数体包在 `if (xcpm_mode != 0)` 里（`KNOWN`，反编译首行即是该判断）。`_xcpm_init` 的调用者是 `_i386_init`、`_acpi_sleep_kernel` 与一个静态包装，都在早期启动路径上。

由此，`71` 第 6.5.3 节里三个 `AppleXcpm*` quirk 的状态可以从"真机 MSR 相关，与本场景无关"升级为确定结论：

| Quirk | 本项目 | 升级后的理由 |
|---|---|---|
| `AppleXcpmCfgLock` | `false` | 它绕开 `MSR_PKG_CST_CONFIG_CONTROL`（`0xE2`）的写锁。`0xE2` 只在 `_xcpm_init`（读）与 `_xcpm_idle`（写）里被访问，而 XCPM 在 guest 里不初始化，所以这条路径不会被走到。`KNOWN` |
| `AppleXcpmExtraMsrs` | `false` | 它屏蔽一批 XCPM 相关 MSR 访问。同上，XCPM 不跑 |
| `AppleXcpmForceBoost` | `false` | 它改写 `MSR_IA32_HWP_REQUEST`。`_xcpm_hwp_enable` 读 `0x1AA`，同样在 XCPM 内 |

**这三项是"不需要开"，不是"开着没坏处"。** 它们都要在内核里找特定字节图样；在一个那段代码不会执行的配置上打补丁，只增加补丁失配的风险（第 3.3 节给出两个实例）。

供排错时参考，XCPM 的 model 白名单（`KNOWN`，`_xcpm_bootstrap` 的 switch 常量）：60 / 61 / 69 / 70 / 71 / 78 / **85** / 94 / 125 / 126 / 142 / 158 / 159 / 165。即 Haswell 到 Comet Lake，含 `0x55`。在真机上 Cascade Lake-W 走的正是 `case 85` 那一支（`xcpm_cpu_model = 0x4000`，`xcpm_hwp_enabled = 1`）。在虚机上这一支到不了。

**合起来的意思是：在云 guest 里 macOS 26 没有 CPU 电源管理。** 没有 P-state 控制、没有 HWP、没有 C-state 协商。对本项目不是问题（Lavapipe 的吞吐由 vCPU 数决定，`80` 第 1.6 节），但它解释了为什么 guest 里看不到 `X86PlatformPlugin` 的频率调节，也意味着**不要为"CPU 跑不满频"去调 XCPM 相关的任何东西**。

### 2.7 其余与 CPU 相关的 panic 点

除了 `cpuid.c:1183`，启动路径上还有四处会因 CPU 而 panic。逐一确证它们在我们的场景里是不是威胁。

#### 2.7.1 `_i386_lbr_init` 的 `Unknown CPU family`

`KNOWN`，`_i386_lbr_init` @ `0xffffff80003ea0e0`，panic 文本 `"Unknown CPU family @%s:%d"`（`pcb_native.c:276`，字符串 VA `0xffffff8000b7f37b`，唯一 xref 来自该函数）。

它被 `_cpuid_set_info` 的最后一行调用：`i386_lbr_init(info_p, 1)`。但整个函数的第一个判断是：

```c
if (last_branch_enabled_modes == 0) {
    wrmsr(0x1D9, rdmsr(0x1D9) & ~1);   /* 关掉 LBR，返回 */
    return;
}
```

`last_branch_enabled_modes` 默认 0（由 `lbr_mode` boot-arg 置位）。**所以默认配置下这个 panic 到不了。** 它识别的 cpufamily 清单比 2.3 的表少一个（没有 PENRYN），所以如果以后用了 `lbr_mode`，这里会成为第二道更窄的门。登记为 C-012 的一部分。

#### 2.7.2 `_mca_cpu_init` 的 `Haswell pre-C0 steppings are not supported`

`KNOWN`，`_mca_cpu_init` @ `0xffffff80003e6430`，panic 文本在 `machine_check.c:97`。条件：

```c
if (family == 6 &&
    ((stepping < 3 && model == 60) || (stepping == 0 && (model - 69) < 2)))
        panic("Haswell pre-C0 steppings are not supported");
```

只针对 model 60 / 69 / 70。Skylake-SP 与 Cascade Lake 不受影响。

同一函数的 MCA 初始化行为（`KNOWN`）：按 leaf 1 EDX 的 bit 14（MCA）与 bit 7（MCE）决定做不做；若 MCA 存在则读 `MSR 0x179`（`IA32_MCG_CAP`），按 `MCG_CTL_P` 写 `MSR 0x17B`，然后 **family == 6 时从 `MSR 0x404` 起写 bank CTL（跳过 bank 0）**，非 family 6 时从 `MSR 0x400` 起写；最后按 MCE 置 `CR4.MCE`。

**对本项目的用处**：如果 hypervisor 不暴露 MCA（leaf 1 EDX bit 14 清零），整段跳过，无风险。如果暴露了但 bank MSR 不可写，表现是 `#GP`。这是一个要观察的点，不是一个已知故障。

#### 2.7.3 `_x86_validate_topology` 的拓扑一致性 panic

`KNOWN`，`_x86_validate_topology` @ `0xffffff80003d8bf0`，被 `_cpu_topology_sort` @ `0xffffff80003d9400` 在最后调用。第一条检查就是最关键的那条：

```c
if ((uint32_t)nLThreadsPerPackage * nPackages != real_ncpus)
    panic("x86_validate_topology() %d threads but %d registered from MADT @%s:%d",
          nLThreadsPerPackage * nPackages, real_ncpus, "cpu_threads.c", 1041);
```

即 **由 CPUID 推出的"每 package 线程数 × package 数"必须等于 ACPI MADT 登记的 CPU 数**。之后还有十余条 panic 校验 die / core / lcpu 的双向指针与计数一致性（`cpu_threads.c` 的 1054 / 1058 / 1073 / 1077 / 1087 / 1099 / 1103 / 1113 / 1122 / 1133 / 1137 / 1151 行）。

这是 AMD 路线上 `cpuid_cores_per_package` 补丁真正要解决的问题（第 3.4 节），**也是 Intel 路线上 vCPU 拓扑可能翻车的地方**（第 4.3 节）。

#### 2.7.4 `_tsc_init` 的 `EFI not supported!` 与一条隐藏的除零

`KNOWN`，`_tsc_init` @ `0xffffff80003f0b00`。它分两条路，第一个判断就是 hypervisor 位：

```c
if ((cpuid_features() & 0x8000000000000000ULL) == 0           /* 没有 hypervisor 位 */
 || (kprintf("VMM vendor %s TSC frequency %u KHz bus frequency %u KHz\n", ...),
     vmm_info->tsc_frequency == 0 || vmm_info->bus_frequency == 0))
{
    /* --- 路 A：原生路径 --- */
    switch (cpuid_cpufamily) {
      case SKYLAKE: case KABYLAKE: case COMETLAKE: case ICELAKE:
          /* 走 ART 路径：读 CPUID leaf 0x15 的 N/M，再取 EFI "ARTFrequency"；
             若 EFI 没给，按 model 推：model 85 时查 PCI 0:31.3 reg 0x98 决定 25 MHz 还是 24 MHz，
             其它按 24 MHz */
      case PENRYN:
          /* 读 MSR 0x198，取 EFI "FSBFrequency" */
      default:
          flex       = rdmsr(0x194);          /* MSR_FLEX_RATIO   */
          platform   = rdmsr(0xCE);           /* MSR_PLATFORM_INFO */
          flex_ratio_min = bits(platform,47,40);
          flex_ratio_max = bits(platform,15,8);
          tscGranularity = flex_ratio_max;
          if (flex & bit(16)) { ...取较小者... }
          busFreq = EFI_get("FSBFrequency") ?: 133333333;
    }
    if (busFreq == 0) panic("tsc_init: EFI not supported! @%s:%d", "tsc.c", 261);
    ...
    tscFCvtt2n = busFCvtt2n / tscGranularity;      /* ←← 这里 */
    tscFreq    = 1e18 / tscFCvtt2n;
} else {
    /* --- 路 B：VMM 直接给频率 --- */
    busFreq = 1000ULL * vmm_info->bus_frequency;
    tscFreq = 1000ULL * vmm_info->tsc_frequency;
}
```

三条可操作的结论：

1. **路 B 是我们想走的那条，它的前提是 CPUID leaf `0x40000010` 存在且两个字段都非零。** `KNOWN`，来源：`_cpuid_vmm_info` @ `0xffffff80003d6f60` 的反编译，末尾处 `if (max_hv_leaf >= 0x40000010) { cpuid(0x40000010); tsc_frequency = EAX; bus_frequency = EBX; }`。单位是 KHz。
2. **路 B 走通的时候内核完全不碰 `MSR 0xCE` 与 `MSR 0x194`。** 这就是 `71` 第 5.2 节 `vmware-cpuid-freq=on` 的真实作用，现在有了二进制依据。**但 L2 上我们写不了这个 flag**，所以 leaf `0x40000010` 在不在，是云平台决定的。登记为 C-003。
3. **如果掉到路 A 的 `default` 分支，而 `MSR 0xCE` 的 bits 15:8 读出 0，`tscGranularity` 就是 0，随后那个除法是除零。** `KNOWN` 对于代码形状（`v40 = v39 / v38` 且 `v38 = tscGranularity`），`INFERRED` 对于"会触发 `#DE`"。注意 `cpuid_cpufamily == SKYLAKE` 时走的是 ART 路径而不是 `default`，所以这条除零只在 cpufamily 落到 `default`（即 Nehalem/Westmere/SandyBridge/IvyBridge/Haswell/Broadwell）时才可能发生。对我们的目标 model `0x55` 不适用，但它是"为什么要在意 `MSR 0xCE`"的具体答案。

路 A 的 ART 分支还有一个我们可以利用的点：它先取 EFI 的 `"ARTFrequency"` 属性，没有才按 model 推。`"FSBFrequency"` 同理。**这两个属性正是 OpenCore 的 `PlatformInfo/UpdateDataHub = true` 负责发布的**（`71` 第 6.8 节已设为 `true`），所以 OpenCore 侧已经为路 A 的最坏情况留了一条后路。`INFERRED`，OpenCore 实际写入的值是否被这个分支读到未验证，登记为 C-003 的一部分。

### 2.8 早期启动读写的 MSR 全表

这张表回答"哪些 MSR 不能缺"。做法：在 `__TEXT` / `__HIB` / `__KLD` 里扫 `mov ecx, imm32` 后 18 字节内跟 `rdmsr`（`0F 32`）或 `wrmsr`（`0F 30`）的图样，按所在函数归类。`KNOWN`，但**是静态扫描，不是执行轨迹**：表里出现不等于一定会执行。

| MSR | 名称 | 访问者 | 在云 guest 里会执行吗 |
|---|---|---|---|
| `0x17` | `IA32_PLATFORM_ID` | rd@`_cpuid_set_info` | **会**。读出 bits 52:50 存为 `cpuid_model_string` 索引 |
| `0x1B` | `IA32_APIC_BASE` | rd@`_lapic_*`、`_vstart`；wr@`_lapic_init` | **会** |
| `0x35` | `IA32_CORE_THREAD_COUNT` | rd@`_cpuid_set_info` | **会**，除非加 `-nomsr35h`（见下） |
| `0x8B` | `IA32_BIOS_SIGN_ID` | rd + wr@`_cpuid_set_info` | **会**。先写 0 再读，取微码版本 |
| `0xCE` | `MSR_PLATFORM_INFO` | rd@`_tsc_init`、`_xcpm_dvfs_configure` | 仅在 `_tsc_init` 落到路 A 的 `default` 分支时 |
| `0xE2` | `MSR_PKG_CST_CONFIG_CONTROL` | rd@`_xcpm_init`；wr@`_xcpm_idle` | **不会**（XCPM 关闭，2.6.2） |
| `0xFE` | `IA32_MTRRCAP` | rd@`_mtrr_init`、`_mtrr_update_cpu` | **会** |
| `0x10A` | `IA32_ARCH_CAPABILITIES` | rd@`_cpuid_set_info`、`_cpuid_wa_required` | **会** |
| `0x10F` | `IA32_TSX_FORCE_ABORT` | rd@`_cpuid_set_info` | 条件性 |
| `0x122` | `IA32_TSX_CTRL` | wr@`_cpuid_set_info` | 仅当 `cpuid_wa_required(3) == 2` |
| `0x123` | `IA32_MCU_OPT_CTRL` | rd@`_cpuid_set_info` | 条件性 |
| `0x174`/`0x175`/`0x176` | `IA32_SYSENTER_*` | wr@`_cpu_syscall_init` | **会** |
| `0x179` | `IA32_MCG_CAP` | rd@`_mca_cpu_init` | 仅当 leaf1.EDX bit 14 置位 |
| `0x17B` | `IA32_MCG_CTL` | wr@`_mca_cpu_init` | 同上 |
| `0x194` | `MSR_FLEX_RATIO` | rd@`_tsc_init` | 同 `0xCE` |
| `0x198` | `IA32_PERF_STATUS` | rd@**`_i386_init`**、`_tsc_init`、多个 `_xcpm_*` | **会**，`_i386_init` 这一处无条件 |
| `0x199` | `IA32_PERF_CTL` | rd@**`_i386_init`**、多个 `_xcpm_*` | **会**，同上 |
| `0x1A0` | `IA32_MISC_ENABLE` | rd@`_commpage_post_ucode_update` | **会** |
| `0x1AA` | `MSR_MISC_PWR_MGMT` | rd@`_xcpm_hwp_enable`、`_xcpm_init` | **不会**（XCPM 关闭） |
| `0x1C8`/`0x1C9`/`0x1D9`/`0x345` | LBR 相关 | `_i386_lbr_*`、`_act_machine_switch_pcb` | `0x1D9` **会**（即使 LBR 关闭也要清 bit 0） |
| `0x250`/`0x258`/`0x259`/`0x268`..`0x26F`/`0x2FF` | MTRR | rd@`_mtrr_init`；wr@`_mtrr_update_all_cpus` | **会** |
| `0x277` | `IA32_PAT` | rd@`_mtrr_update_all_cpus`、`_pat_init` | **会** |
| `0x38D`..`0x390` | PMU 固定计数器 | `_cpc_*` | 条件性 |
| `0x480`..`0x489` | VMX capability | rd@`_vmx_cpu_init`、`_vmx_hv_support` | 仅当向 guest 暴露 VMX。`71` 第 5.3 节已决定不暴露 |

**`_i386_init` 对 `MSR 0x198` 与 `0x199` 的那两次读是本表里最值得盯的一项。** 它无条件执行，发生在极早期（`_i386_init` 是 C 侧的第一个函数之一），而这两个 MSR 不是所有 hypervisor 都实现。这正是 `AMD_Vanilla` 第 15 条补丁（`_i386_init | Remove 3 rdmsr calls`）存在的原因，也是 `71` 第 5.4 节要求宿主 `kvm ignore_msrs=1` 的原因。**`ignore_msrs` 是宿主侧参数，L2 上我们设不了。** 登记为 C-004。

**`-nomsr35h` 这个 boot-arg 是本样本里一个没有被社区文档记录的逃生口。** `KNOWN`，字符串 `"-nomsr35h"` 在 VA `0xffffff8000b7c8e2`，唯一 xref 来自 `_cpuid_set_info`，代码：

```c
if ((int64_t)cpuid_features < 0                               /* hypervisor 位置位 */
 && PE_parse_boot_argn(bootArgs, "-nomsr35h")) {
        core_thread_count = 0x0000000100000001ULL;            /* core=1, thread=1 */
        goto skip_msr35;
}
if (cpuid_cpufamily == WESTMERE)      { v = rdmsr(0x35); core = bits(v,19,16); thread = bits(v,15,0); }
else if (cpuid_cpufamily != PENRYN)   { v = rdmsr(0x35); core = bits(v,31,16); thread = bits(v,15,0); }
else                                  { core_thread_count = logical_per_package_pair; }
```

即：**只在 hypervisor 位置位时才认这个 boot-arg**，认了之后完全不读 `MSR 0x35`，把 core/thread 直接定成 1/1。它是 Apple 为虚机留的，不是第三方补丁。

`INFERRED`：core_count = 1 会不会让第 2.7.3 节的拓扑校验失败，未验证。`nLThreadsPerPackage` 是 `_x86_set_logical_topology` 从别处推的，不一定直接取自这里。**这是一个值得优先查清的点，因为如果它成立，它就是 `ProvideCurrentCpuInfo` 的原生替代品，而且不需要打任何补丁。** 登记为 C-009。

### 2.9 一个免费的诊断开关：`-cpuid` boot-arg

`KNOWN`。`_cpuid_set_info` 以及 `_tsc_init`、`_xcpm_bootstrap`、`_mca_cpu_init` 调用的那个惰性初始化包装做的第一件事是：

```c
if (cpuid_cpu_infop == NULL) {
    PE_parse_boot_argn(bootArgs, "-cpuid", &cpuid_dbg, ...);
    cpuid_set_info();
    cpuid_cpu_infop = &cpuid_cpu_info;
}
```

`cpuid_dbg`（本样本 VA `0xffffff8000eb7360`）一旦非零，`cpuid_set_info` 会把**整个 CPUID 解码过程 kprintf 出来**。从反编译读出的输出行（`KNOWN`，格式串逐条取自二进制）：

```text
cpuid_set_generic_info(%p)
cpuid_fn(0x%08x) eax:0x%08x ebx:0x%08x ecx:0x%08x edx:0x%08x     ← 每个被读的 leaf 一行
 max_basic           : %d
 max_ext             : 0x%08x
 vendor              : %s
 brand_string        : %s
 signature           : 0x%08x
 stepping            : %d
 model               : %d
 family              : %d
 type                : %d
 extmodel            : %d
 extfamily           : %d
 brand               : %d
 features            : 0x%016llx
 extfeatures         : 0x%016llx
 logical_per_package : %d
 microcode_version   : 0x%08x
 Monitor/Mwait Leaf: / Thermal/Power Leaf: / Architectural Performance Monitoring Leaf:
 XSAVE Main leaf: / XSAVE Sub-leaf1: / XSAVE Sub-leaf%d:
 Feature Leaf7:  EBX / ECX / EDX
 TSC/CCC Information Leaf:  numerator / denominator
 vmm_vendor          : %s
 vmm_family          : %u
 vmm_bus_frequency   : %u
 vmm_tsc_frequency   : %u
cpuid_set_cpufamily(%p) returning 0x%x
cpuid_set_info():  core_count / thread_count / cpu_type / cpu_subtype
```

**`-cpuid` 应该加进研发期的 boot-args。** 它把"宿主给了我们什么 CPU"这个问题的答案直接打在串口上，包括 `signature`（leaf 1 EAX）、`family`、`model`、`stepping`、`features`、`extfeatures`、Leaf7、以及 `vmm_tsc_frequency` / `vmm_bus_frequency` 这两个决定第 2.7.4 节走路 A 还是路 B 的值。代价是启动日志变长。

与 `71` 第 6.7 节的 `boot-args` 合并后的研发期取值：

```text
amfi_get_out_of_my_way=1 -v -cpuid keepsyms=1 debug=0xa serial=7 msgbuf=1048576
```

**注意 `cpuid_set_cpufamily(...) returning 0x0` 这一行。** 返回 0 就是 `CPUFAMILY_UNKNOWN`，它出现在 panic 之前，所以这一行是"CPU 不被支持"最早、最明确的信号。做成 `80` 第 2.9 节 `Detector` 的一条正则。

`INFERRED`：`-cpuid` 的输出走的是 `kprintf`，而 `kprintf` 到串口需要 `debug` 的 `DB_KPRT`（`0x8`）位，`71` 第 9.4 节的 `debug=0xa` 已含。但 `cpuid_set_info` 发生在极早期，比 boot-args 解析之后、串口初始化之后到什么程度未验证；如果这一段看不到，走 `71` 第 9.5 节的 early serial 补丁。登记为 C-011。

---

## 3. B. AMD（EPYC）路线

### 3.1 `AMD_Vanilla` 的机制与时效

#### 3.1.1 机制

`AMD_Vanilla` 不是一个 kext，不是一个自定义内核。它是**一组 OpenCore `Kernel/Patch` 条目**，在 OpenCore 把内核载入内存之后、跳转之前，按字节图样原地改写内核代码。

`KNOWN`，来源 <https://github.com/AMD-OSX/AMD_Vanilla/blob/master/patches.plist>（本轮下载的版本，19,661 字节，25 个 `Kernel/Patch` 条目）与 <https://github.com/AMD-OSX/AMD_Vanilla/blob/master/README.md>。README 的关键声明，逐条转述：

- 补丁对 15h / 16h / 17h / 19h 四个 AMD family 通用，做法是依赖 OpenCore 的 `ProvideCurrentCpuInfo` quirk；需要 OpenCore 0.7.1 或更新；**不启用该 quirk 系统不启动**。
- 声明支持的 macOS 版本清单里**包含 macOS Tahoe (26)**。
- `Force cpuid_cores_per_package` 那四条补丁的 `Replace` 需要用户按自己的**物理核心数**改一个字节；13.3 及以后的形态是 `BA <核心数> 0000 00`。
- Zen 4（Ryzen 7000）另需一条 `IOPCIFamily` 补丁，默认启用。
- 已知缺陷清单里列出：依赖 `AppleHV` 的虚拟机软件、Adobe 与 Intel MKL/OneAPI、32 位支持、部分音频类应用的稳定性。

#### 3.1.2 它打在哪些函数上

`KNOWN`，从 `patches.plist` 逐条读出，并按 `MinKernel`/`MaxKernel` 过滤到 Darwin 25（macOS 26）。落在版本区间内的是 **15 条 `Identifier = kernel`**（其中第 24 条 `Enabled = false`，即 **14 条默认启用**）与 **2 条 `Identifier = com.apple.iokit.IOPCIFamily`**（其中第 18 条 `Enabled = false`，即 1 条默认启用）。

| # | `Base` / 目标 | 作用 | `MinKernel`..`MaxKernel` |
|---|---|---|---|
| 3 | `_cpuid_set_info` → 实际落在 `cpuid_set_cache_info` | 把 `cores_per_package` 的 CPUID 计算换成常量 | 22.4.0..25.99.99 |
| 4 | `_commpage_populate` 内联处 | 去掉一次 `rdmsr(0x1A0)` | 17.0.0..25.99.99 |
| 5 | `cpuid_set_cache_info` | 把 cache 枚举 leaf 从 `4` 改成 `0x8000001D`（AMD 的 cache leaf） | 17.0.0..25.99.99 |
| 6 | `cpuid_set_generic_info` | 去掉 `wrmsr(0x8B, 0)` | 17.0.0..25.99.99 |
| 7 | `cpuid_set_generic_info` | 把 `rdmsr(0x8B)` 换成常量 186 | 17.0.0..25.99.99 |
| 8 | `cpuid_set_generic_info` | 把 `rdmsr(0x17)` 的结果换成常量 1 | 17.0.0..25.99.99 |
| 10 | `cpuid_set_generic_info` | 放开 leaf 7 的 `max_basic` 下限检查 | 24.0.0..25.99.99 |
| 12 | `_cpuid_set_info` | **NOP 掉 `GenuineIntel` 比较后的那个 `jnz`**，即绕过门 1 | 21.0.0..25.99.99 |
| 14 | `_cpuid_set_info ` | **把 `cpuid_set_cpufamily` 强制成 `CPUFAMILY_INTEL_PENRYN`**，即绕过门 2 | 20.4.0..25.99.99 |
| 15 | `_i386_init` | 去掉 3 次 `rdmsr`（`0x199`、`0x198`） | 17.0.0..25.99.99 |
| 16 | `_lapic_init` | 去掉 LAPIC 版本检查与随后的 panic | 17.0.0..25.99.99 |
| 19 | `thread_quantum_expire` / `thread_unblock` / `thread_invoke` | 去掉 non-monotonic time panic（`ja` 形态，3 处） | 21.0.0..25.99.99 |
| 20 | `thread_invoke` / `thread_dispatch` | 去掉 non-monotonic time panic（`jb` 形态，2 处） | 21.0.0..25.99.99 |
| 23 | `_mtrr_update_action` / `_pat_init` | 修正 PAT 写入值 | 24.0.0..25.99.99 |
| 24 | 同上 | Shaneee 版 PAT，与 23 二选一，默认关 | 24.0.0..25.99.99 |
| 17 | `IOPCIBridge::probeBusGated` | Zen 4：关掉 PCIe 10-bit tag | 21.0.0..25.99.99 |
| 18 | `IOPCIConfigurator::IOPCIIsHotplugPort` | AM5 的 PCI 枚举修正，默认关 | 22.0.0..25.99.99 |

第 12 与第 14 条合起来就是绕过第 2.2 节两道门的全部内容。**注意第 14 条的 `Base` 字段是 `"_cpuid_set_info "`，末尾多一个空格**（`KNOWN`，本轮从 plist 读出的原始字符串）。它是否影响 OpenCore 的符号解析未验证，登记为 C-007。

#### 3.1.3 时效：这是本节最关键的一段

`KNOWN`，来源：GitHub API 对 `AMD-OSX/AMD_Vanilla` 的 commit 与 pull request 查询（本轮执行）。

| 事件 | 日期 | 说明 |
|---|---|---|
| commit `c735eded` "Add Tahoe beta patches" | **2025-06-10** | master 上**最后一次改动补丁内容**的提交 |
| commit `eaf52ef2` "Minor readme updates" | 2025-10-17 | 只改 README，不改 `patches.plist` |
| PR #212 "Add probeBusGated patch for macOS 26" | 2025-06-15 合入 | |
| PR #214 "Clover AMD Kernel Patches updated for macOS Tahoe" | 2025-12-05 合入 | Clover 侧，不是 OpenCore 的 `patches.plist` |
| **PR #215 "Fix thread_invoke and thread_dispatch TSC non-monotonic panic on Darwin 25.4.0+"** | **2026-03-29 提交，至今仍 open**（最后更新 2026-10-22） | 见第 3.3 节 |

**结论：Tahoe 支持的补丁内容是在 Tahoe 还处于 beta 阶段（2025-06）一次性加入的，此后 16 个月没有针对 Tahoe 正式版的内容更新；唯一一个针对 Darwin 25.4 之后内核变化的修正（PR #215）已经 open 了 7 个月。** `KNOWN`。

这不是"没人维护"，但也绝不是"跟得上"。README 声明支持 Tahoe，而仓库里针对 Tahoe 正式版的实际工作是一个未合入的 PR。下一节把这件事从时效推断变成在 25G325 上的实测结果。

### 3.2 25 条补丁对 25G325 的逐条匹配结果

这是本节的核心证据。方法见第 1.2 节第 3 条。对 Darwin 25 生效的每一条，在本样本上统计命中数、命中位置与命中位置的所属函数。下表只列**默认启用**的 15 条（14 条 kernel + 1 条 `IOPCIFamily`）；默认关闭的第 18、24 条不列。

`KNOWN`，全部数值为本轮实际扫描结果。"命中数"是在 `__TEXT`（或从 `Base` 符号起到 `__TEXT` 末尾）范围内满足掩码比较的位置总数；OpenCore 按 `Count` 取前 N 个。

| # | 作用 | `Count` | 命中数 | 首个命中位置 | 判定 |
|---|---|---:|---:|---|---|
| 3 | cores_per_package 常量化 | 1 | 15 | `0xffffff80003d5cc5`，字节 `C1EA1AFFC2` | **正确**。第一个命中落在 `cpuid_set_cache_info` 内，就是预期目标 |
| 4 | 去 `rdmsr(0x1A0)` | 1 | 1 | `0xffffff80003f15dc`，字节 `B9A00100000F32` | **正确** |
| 5 | cache leaf 改 `0x8000001D` | 1 | 1 | `0xffffff80003d5c73`，字节 `B8040000004489F14489` | **正确** |
| 6 | 去 `wrmsr(0x8B)` | 1 | 1 | `0xffffff80003d4155`（`_cpuid_set_info+0x475`） | **正确** |
| 7 | `rdmsr(0x8B)` 换常量 | 1 | 1 | `0xffffff80003d419d`（`+0x4BD`） | **正确** |
| 8 | `rdmsr(0x17)` 换常量 | 1 | 1 | `0xffffff80003d4215`（`+0x535`） | **正确** |
| 10 | 放开 leaf7 检查 | 1 | 2 | `0xffffff80003d4554`（`+0x874`） | **正确**，第一个命中在目标函数内 |
| 12 | 绕过 `GenuineIntel` 门 | 1 | 1 | `0xffffff80003d4f1e`（`+0x123E`），字节 `0F850403000031D2B301` | **正确**。被 NOP 的 6 字节正是 `jnz +0x304` |
| 14 | 强制 PENRYN | 1 | 1 | `0xffffff80003d4f28`（`+0x1248`），字节 `803D1D22AE000675` | **正确**（需先 trim `Base` 末尾空格） |
| 15 | 去 `_i386_init` 的 3 次 rdmsr | 0 | 3 | `0xffffff80003dfaf4`、`0xffffff8000ac961b`、`0xffffff8000ac9ae9` | **正确**，`Count = 0` 全改 |
| 16 | 去 LAPIC 版本检查 | 1 | 1 | `0xffffff80003f59ba`（`_lapic_init+0x20A`），字节 `25FC00000083F813` | **正确** |
| 19 | non-monotonic（`ja` 形态） | 3 | 3 | `_thread_quantum_expire+0xB6`、`_thread_unblock+0xBA`、`_thread_block_reason+0x184C` | **正确**，命中数恰好等于 `Count` |
| **20** | **non-monotonic（`jb` 形态）** | **2** | **33** | **`_kperf_lazy_wait_sample+0x20`、`_vmx_hv_support+0x2A`** | **失配。见 3.3.1** |
| 23 | PAT 修正 | 0 | 2 | `_mtrr_update_all_cpus+0x27C`、`_pat_init+0x6A`，字节 `89C081E2FFFF00FF81CA000001000F30` | **正确** |
| **17** | **Zen4 probeBusGated** | **1** | **0** | 无 | **失配。见 3.3.2** |

两条正确性佐证，用来说明这套扫描方法本身没问题：

- 第 19 条的命中数精确等于 `Count = 3`，且三个命中分别落在三个按注释应该命中的函数里。
- 第 12、14 条的命中字节与第 2.2 节反编译出的分支结构逐字对应：`0F 85 04 03 00 00` 是门 1 的 `jnz`，`80 3D xx xx xx xx 06` + `75` 是门 2 的 `cmp byte [cpuid_family], 6` + `jnz`。

### 3.3 两条在 25G325 上确证失效的补丁

#### 3.3.1 第 20 条：目标没打上，而且误打两处无关代码

`KNOWN`（命中统计与字节）+ `INFERRED`（误打的后果）。

补丁原文：`Find = 48 00 00 80 04 00 00 0F 00 00 00 00 00`，`Mask = 48 00 00 F0 FF FF FF FF 00 00 00 00 00`，`Replace` 只改后 6 字节为 `66 90 66 90 66 90`（三条 2 字节 NOP），`ReplaceMask = 00 00 00 00 00 00 00 FF FF FF FF FF FF`。

它的意图是找到 `cmp r?, [r? + 0x48x]` 后紧跟的 `jb rel32`，把那条 `jb` NOP 掉。掩码对第 4 个字节用 `0xF0`，所以只能匹配偏移 `0x480`..`0x48F`。

**在 25G325 里那个偏移已经是 `0x490`。** `KNOWN`，用正则 `[\x48-\x4f]\x3b.\x90\x04\x00\x00\x0f\x82` 扫 `__TEXT`，得到**唯一一个命中**：

```text
VA 0xffffff80002a7092   _thread_block_reason+0x18a2
bytes 4D 3B A6 90 04 00 00 0F 82 C8 04 00 00
      cmp r14, [r14+0x490]   jb +0x4C8
```

同时用 `...\x88\x04...`（`0x488`）扫同一范围，**零命中**。即结构偏移整体移动了 8 字节，与 PR #215 的分析一致（PR 正文说明 Darwin ≤ 25.3.x 用 `0x488`、Darwin 25.4.0 起用 `0x490`，并指出 `0xF0` 掩码只覆盖 `0x480`-`0x48F`，转述自 <https://github.com/AMD-OSX/AMD_Vanilla/pull/215>）。

后果有两层，第二层是社区讨论里没有的：

1. **预期的补丁没被打上。** `thread_invoke` 与 `thread_dispatch` 里的 non-monotonic time panic 仍在。
2. **因为掩码过松，这条补丁在 25G325 里仍然有 33 个命中，`Count = 2` 会改掉前两个。** 前两个是：

| 命中 | VA | 所属函数 | 被 NOP 的 6 字节 |
|---|---|---|---|
| 1 | `0xffffff80003aa550` | `_kperf_lazy_wait_sample+0x20` | `0F 82 A9 00 00 00`（一条 `jb`） |
| 2 | `0xffffff800040029a` | `_vmx_hv_support+0x2A` | `0F 32 F6 C2 02 74`（`rdmsr` + `test dl,2` + `je`） |

第 2 个命中尤其糟：它把 `_vmx_hv_support` 里读 `MSR 0x48B` 之后的判断整段变成 NOP，函数的返回值因此不可信。`INFERRED`：这两处误打的直接危害大概率不致命（`kperf` 是性能采样，`vmx_hv_support` 在我们不暴露 VMX 时无人关心），但它们是"补丁在错误的位置改了字节"的确定实例，而这类错误的下游表现完全不可预测。

**修法已经有了，而且在 25G325 上验证通过。** PR #215 提出的新条目：

```text
Identifier  kernel
Arch        x86_64
Base        （空）
MinKernel   25.4.0
MaxKernel   25.99.99
Count       2
Find        48 00 00 90 04 00 00 0F 00 00 00 00 00
Mask        48 00 00 F0 FF FF FF FF 00 00 00 00 00
Replace     00 00 00 00 00 00 00 66 90 66 90 66 90
ReplaceMask 00 00 00 00 00 00 00 FF FF FF FF FF FF
```

（字节来源：<https://github.com/AMD-OSX/AMD_Vanilla/pull/215> 的 diff，本轮从 `patches.plist` 的 base64 字段解码；原 PR 同时把第 20 条的 `MaxKernel` 收到 `25.3.99`。）

**本轮在 25G325 上实测这条新条目：命中 3 个，前两个正是预期目标。** `KNOWN`：

| 命中 | VA | 所属函数 | 字节 |
|---|---|---|---|
| 1 | `0xffffff80002a7092` | `_thread_block_reason+0x18A2`（`thread_invoke` 被内联进来） | `4D 3B A6 90 04 00 00 0F 82 C8 04 00 00` |
| 2 | `0xffffff80002a801a` | `_thread_dispatch+0x71A` | `4C 2B BB 90 04 00 00 0F 82 50 02 00 00` |
| 3 | `0xffffff80002fa73d` | `_host_priv_server_routine+0xEFD` | `48 0F 85 99 04 00 00 FB 72 2E C1 E2`（无关，但 `Count = 2` 不会走到） |

所以：**用 PR #215 的条目替换 master 的第 20 条，在 25G325 上是正确的。** 第 3 个命中落在 `Count` 之外，纯属运气，但这份运气可以验证：命中按地址升序，前两个的地址都小于第三个。`KNOWN`。

本项目的做法：**不直接引用 `AMD_Vanilla` master，而是 fork 并把第 20 条换成上面这一条，然后对每一条都跑一遍第 1.2 节的扫描作为构建期门禁。** 见第 5.3 节。

#### 3.3.2 第 17 条：Zen 4 的 `probeBusGated` 补丁在 25G325 上零命中

`KNOWN`。master 第 17 条：`Identifier = com.apple.iokit.IOPCIFamily`，`Base = __ZN11IOPCIBridge13probeBusGatedEP14probeBusParams`，`Find = E0 11 72 00`，`Mask = F0 FF FF F0`，`Count = 1`，`MinKernel 21.0.0`..`MaxKernel 25.99.99`。

在仓库已有的 `kext/com.apple.iokit.IOPCIFamily`（`LC_UUID` `81D9CF0C-0587-3EC8-B878-E0042113108B`）**整个文件**范围内扫描：

| 条目 | 命中数 | 命中字节 |
|---|---:|---|
| master 第 17 条（`E0 11 72 00` / `F0 FF FF F0`） | **0** | — |
| PR #215 新增的 `26.0+` 条目（`E0 11 73 40` / `F0 FF FF F0`） | **1** | `E3 11 73 4A` |

PR #215 同时把 master 第 17 条的 `MaxKernel` 收到 `24.99.99`，另加一条 `MinKernel 25.0.0` 的新条目，`Replace = 00 00 02 00`、`ReplaceMask = 00 00 0F 00`（字节来源同上）。

**所以 master 的 Zen 4 补丁在 macOS 26 上确定不生效，而 README 把它标为"默认启用、Zen 4 稳定性必需"。** 这是第二个确证的 Tahoe 失配。

两条限定，必须写清楚：

1. 命中位置给的是**仓库内重建件的文件偏移 `0xF9C5`，不是 VA**。原因是该重建件的段表 `fileoff` 保留了 kernel collection 内的原值（`MANIFEST.md` 第 3 节已声明这一点），不能直接换算 VA。要给 VA 必须重跑 `tools/kc.py`。登记为 C-013。
2. **这条补丁对本项目大概率不需要。** `INFERRED`：它关闭的是 PCIe 10-bit tag。guest 看到的是 hypervisor 合成的 PCIe 拓扑，不是宿主的；QEMU 的 `pcie-root-port` 不声明 10-Bit Tag Requester 能力。所以即使在 EPYC 宿主上，guest 内的 `IOPCIFamily` 也不会走到那条路径。保留为"若 EPYC 上出现 PCI 枚举异常时的第一候选"，默认不加。

### 3.4 `cpuid_cores_per_package` 在 26 上的形态

这是社区最常被问错的一条，因为它的目标函数在不同版本里被内联到不同地方。

`KNOWN`，本样本的事实：

- 补丁条目的 `Base` 是 `_cpuid_set_info`，但 **`Base` 在 OpenCore 里只是搜索起点，不是函数边界**（`KNOWN`，官方对 `Base` 的描述是"通过取给定符号的地址来选择符号匹配的补丁查找基址"，转述自 <https://dortania.github.io/docs/latest/Configuration.html>）。
- `_cpuid_set_info` 的范围是 `0xffffff80003d3ce0`..`0xffffff80003d5247`。**这个范围内没有任何 `shr eax/edx, 0x1A` 图样。**
- 从 `Base` 往后第一个命中在 `0xffffff80003d5cc5`，字节 `C1 EA 1A FF C2`（`shr edx, 0x1A` + `inc edx`）。这个地址落在一个没有导出符号的静态函数里（介于 `_cpuid_wa_required` @ `0xffffff80003d5750` 与 `_cpuid_info` @ `0xffffff80003d60c0` 之间），而 `_cpuid_set_info` 在结尾处调用了 `sub_FFFFFF80003D5490` 与 `sub_FFFFFF80003D5930`。**第 5 条补丁的注释自己把那个函数叫做 `cpuid_set_cache_info`，而它的命中（`0xffffff80003d5c73`）与第 3 条的命中（`0xffffff80003d5cc5`）相距 82 字节，在同一个函数里。** 所以：

> **在 25G325 上，`cpuid_cores_per_package` 的那条 CPUID 计算位于 `cpuid_set_cache_info`（一个无符号静态函数，约 `0xffffff80003d5930` 起），`_cpuid_set_info` 只是作为搜索锚点存在。** `KNOWN`。

被替换的 5 字节：

```text
原    C1 EA 1A    shr edx, 0x1A        ; bitfield32(leaf4.EAX, 31, 26)
      FF C2       inc edx              ; +1
替换  BA CC 00 00 00                   ; mov edx, <物理核心数>
```

补丁条目（`Find`/`Mask`/`Replace`/`ReplaceMask` 字节来源：<https://github.com/AMD-OSX/AMD_Vanilla/blob/master/patches.plist> 的第 4 条 `algrey | Force cpuid_cores_per_package ... | 13.3+`；`<CC>` 的填写规则来源 README）：

```text
Identifier   kernel
Arch         x86_64
Base         _cpuid_set_info
MinKernel    22.4.0
MaxKernel    25.99.99
Count        1
Find         C1 E8 1A 00 00
Mask         FF FD FF 00 00
Replace      BA <CC> 00 00 00
ReplaceMask  FF FF FF FF FF
```

`<CC>` 是**物理核心数的十六进制单字节**，不是线程数。README 给出的对照是 4 核 `04`、6 核 `06`、8 核 `08`、12 核 `0C`、16 核 `10`、24 核 `18`、32 核 `20`。

**对本项目而言这一个字节就是 AMD 路线最刺眼的问题：它是编译期常量，而 vCPU 数是实例规格决定的。** 推论：

- `voc` / `vx1` 这类 AMD 机型的 vCPU 数从 1 到 192 不等（第 7 节），每个规格都要一份不同的 `config.plist`。
- 更麻烦的是"物理核心数"在 guest 里的含义。云平台给的是 vCPU（`vcpu_type = thread`，第 7 节），guest 看到的拓扑由 hypervisor 合成。**`<CC>` 应该填 guest 看到的 socket 内物理 core 数，而这个值要先把实例起起来才知道。** `INFERRED`，登记为 C-002。
- `Mask = FF FD FF 00 00` 让 `C1 E8 1A`（`shr eax`）与 `C1 EA 1A`（`shr edx`）都能命中，所以同一条补丁能跨不同寄存器分配的内核版本复用。这是它为什么还能在 25G325 上命中的原因。

**与 `ProvideCurrentCpuInfo` 的关系要说清，这是另一个常见误解。** README 说"补丁靠 `ProvideCurrentCpuInfo` 实现跨 family 通用"，而 OpenCore 官方对这个 quirk 的描述分三种情况（转述自 <https://dortania.github.io/docs/latest/Configuration.html>）：Hyper-V 下提供正确的 TSC 与 FSB 值并禁用 CPU 拓扑校验；**KVM 与其它 hypervisor 下提供预先算好的 MSR 35h 值，解决使用 `-cpu host` 时的 kernel panic**；Intel CPU 下把 core count 补成 thread count 以支持非对称 SMP。

即在 KVM guest 上，`ProvideCurrentCpuInfo` 做的是 MSR 35h 那一件事，**不包含 Hyper-V 那条分支里的"禁用拓扑校验"**。所以第 2.7.3 节的 `x86_validate_topology` panic 在 KVM 上仍然是活的，仍然要靠第 3 条补丁把 cores_per_package 弄对。`KNOWN` 对于文档内容，`INFERRED` 对于"因此在 KVM 上两者都需要"。

### 3.5 EPYC 代次差异

`INFERRED`，依据是 AMD_Vanilla README 声明的 family 支持范围与各代 EPYC 的 CPUID family。

| 代次 | 产品 | CPUID family | 在 README 声明的 15h/16h/17h/19h 内？ |
|---|---|---|---|
| Naples | EPYC 7001 | `0x17` | 在 |
| Rome | EPYC 7002 | `0x17` | 在 |
| Milan | EPYC 7003 | `0x19` | 在 |
| Genoa / Bergamo / Siena | EPYC 9004 / 8004 | `0x19` | 在 |
| Raphael | EPYC 4004 | `0x19` | 在 |
| **Turin** | **EPYC 9005** | **`0x1A`** | **不在** |
| **Granite Ridge** | **EPYC 4005** | **`0x1A`** | **不在** |

**Zen 5（family 1Ah）落在 AMD_Vanilla 声明的支持范围之外。** 这不等于一定不工作：第 12 与第 14 条补丁绕过门 1 和门 2 的方式与 family 无关（它们改的是 Intel 侧的比较与赋值，不读 AMD 的 family）。真正与 family 相关的是第 5 条（cache leaf `0x8000001D`，Zen 全系都有）与 PAT 修正。

`INFERRED`：**Zen 5 大概率可用但没人验证过**，而 Vultr 的 `vbm-24c-384gb-amd5`（EPYC 9255）与 `vbm-*-mi3*x-gpu`（EPYC 9575F）已经是 Turin。登记为 C-008。

**代次差异对补丁适用性的真正影响只有一条，而且不在 family 上：第 3 条补丁的 `<CC>` 常量随实例规格变。** 其余补丁对 Rome / Milan / Genoa 形态相同。

### 3.6 AMD 上必须额外禁用或替换的东西

逐项核对本项目场景，而不是照抄通用清单。

| 对象 | 通用做法 | 本项目在 25G325 + 云 guest 下的结论 |
|---|---|---|
| **XCPM** | AMD 上必须关 | **不需要做任何事。** 第 2.6.2 节：hypervisor 位置位 → `xcpm_mode = 0`，XCPM 根本不初始化。`AppleXcpmCfgLock` / `AppleXcpmExtraMsrs` / `AppleXcpmForceBoost` 全部保持 `false` |
| **`AppleIntelCPUPowerManagement`** | AMD 上必须关（`DummyPowerManagement` 或 `NullCPUPowerManagement.kext`） | **不需要。** 第 2.6.1 节：该 kext 在 25G325 的 payload 里零命中，不存在 |
| **`AppleTyMCEDriver`** | 某些 SMBIOS 下要 `Kernel/Block` 掉 | **不需要。** 第 2.6.1 节：零命中，不存在 |
| **`AppleIntelMCEReporter`** | `MacPro6,1` / `iMacPro1,1` / `MacPro7,1` 三个 board-id 下要 `AppleMCEReporterDisabler.kext` | **仍然需要，而且与 CPU 厂商无关。** `71` 第 4.3 节门 1 已解出它的 `IOPropertyMatch` 就是这三个 board-id，而我们选了 `MacPro7,1`。**本文不改这个结论**，只补一条：该 kext 本体存在（8 条 payload 路径），且在 System KC 里（`71` 第 4.3 节，`vm=0x1484b000`），所以 disabler 是真有东西要挡 |
| `NullCPUPowerManagement.kext` | 老方案 | 不用。它针对的 `AppleIntelCPUPowerManagement` 不存在 |
| `_i386_init` 的 `rdmsr(0x198/0x199)` | AMD_Vanilla 第 15 条去掉 | **要。** 第 2.8 节确认这两次读无条件执行，AMD 上这两个 MSR 不存在 |
| `_lapic_init` 的版本检查 | AMD_Vanilla 第 16 条去掉 | **要。** 第 2.8 节确认 `_lapic_init` 读写 `MSR 0x1B` |
| PAT | AMD_Vanilla 第 23 条修正 | **要**（EPYC 上）。两个命中都在 25G325 里确认存在 |

**一条本文新增的纪律：在 Intel 路线上，上面所有 AMD 相关补丁一条都不要加。** 理由见第 5.2 节。

### 3.7 已知的硬坏点

本项目只关心"有没有"，但要知道哪些是真的坏。

`INFERRED`，来源是社区权威文档而非 Apple：macOS 在 AMD 上明确不支持或部分损坏的能力包括依赖 `AppleHV` 的虚拟机软件（VirtualBox、VMware、Parallels、Docker、Android Studio 等）、Adobe 套件（依赖 Intel 的 Memfast 指令集）与使用 Intel MKL/OneAPI 的程序、32 位支持（Vanilla 补丁不支持 32 位指令）、以及音频类应用与 DaVinci Resolve 的稳定性问题（转述自 <https://dortania.github.io/OpenCore-Install-Guide/macos-limits>）。同一来源另有一条总体建议：不推荐 AMD，因为它不是原生支持、还有不少遗留问题（转述自 <https://dortania.github.io/Anti-Hackintosh-Buyers-Guide/CPU.html>）。

逐条映射到本项目：

| 坏点 | 对本项目的影响 | 判定 |
|---|---|---|
| `AppleHV` 虚拟机不可用 | **无影响。** `00-OVERVIEW` 第 2.2 节明确不要求嵌套虚拟化，`71` 第 5.3 节已决定不向 guest 暴露 VMX | 可接受 |
| Adobe / Intel MKL / OneAPI | **需要确认一次。** 本项目的运行组件是 Vulkan loader + Mesa Lavapipe + LLVM（`00-OVERVIEW` 第 5 节组件 5），这条链上不含 MKL；metal2vulkan 是 Rust。`INFERRED`：无影响 | 低风险，登记为 C-014 |
| 32 位不支持 | 无影响。macOS 26 本身没有 32 位用户态 | 可接受 |
| 音频应用不稳定 | 无影响。`71` 第 6.9.1 节已关掉 `AudioSupport` | 可接受 |
| **第 2.5 节的 `x86_64h` 判定** | **需要确认。** 第 14 条补丁把 cpufamily 强制成 `CPUFAMILY_INTEL_PENRYN`，但 `cpu_subtype` 的判定看的是 feature bit 而不是 cpufamily（第 2.5 节的代码），EPYC 全系有 AVX2/FMA/BMI，所以 `cpu_subtype` 仍应为 8。`INFERRED` | 低风险 |
| **视频编解码** | 本项目没有硬件编解码能力可言。Lavapipe 是纯 CPU 渲染器，`VideoToolbox` 的硬件路径在没有 GPU 驱动的情况下本来就不存在。这一类"AMD 上编解码坏"的报告与本项目的失效模式无法区分 | 不作为判据 |
| **`CPUFAMILY_INTEL_PENRYN` 的下游影响** | **这是本项目独有的新风险，社区清单里没有。** 把 cpufamily 伪装成 Penryn 之后，用户态任何按 `sysctl machdep.cpu.cpufamily` 选路的代码都会拿到一个 2008 年的值。Metal.framework 与 `AppleParavirtGPUMetal.bundle` 是否按 cpufamily 分支未验证 | `BLOCKED`，登记为 C-005 |

最后一条值得强调。`00-OVERVIEW` 第 4.4 节已经确定本项目的 ObjC 侧要继承 `MTLIOAccelDevice` 并走 Apple 自己的 Metal 栈。**如果那条栈上任何一处按 cpufamily 做能力判定，AMD 路线会在一个与 CPU 完全无关的地方失败，而失败点在 Metal 框架内部。** 这是 AMD 路线对本项目的特有成本，不是通用的 hackintosh 成本。

---

## 4. C. Intel（Xeon Scalable）路线

### 4.1 逐代判定

第 2.3、2.4 节已经给出结论。这里把它变成一张决策表，加上"如果不在表里怎么办"。

| 宿主 CPU | CPUID model | 内核门 | 需要 CPUID 伪装吗 | 需要 AMD 补丁吗 |
|---|---|---|---|---|
| Xeon Scalable 第 1 代（Skylake-SP） | `0x55` | **通过** | **不需要** | 不需要 |
| Xeon Scalable 第 2 代（Cascade Lake-SP / Cooper Lake） | `0x55` | **通过** | **不需要** | 不需要 |
| Xeon E-2100 / E-2200（Coffee Lake） | `0x9E` | **通过** | 不需要 | 不需要 |
| Xeon E3-1200 v2..v6 | `0x3A`/`0x3C`/`0x4E`/`0x9E` 等 | 通过 | 不需要 | 不需要 |
| Xeon Scalable 第 3 代（Ice Lake-SP） | `0x6A` | **panic** | **需要** | 不需要 |
| Xeon Scalable 第 4 代（Sapphire Rapids） | `0x8F` | **panic** | **需要** | 不需要 |
| Xeon Scalable 第 5 代（Emerald Rapids） | `0xCF` | **panic** | **需要** | 不需要 |
| Xeon E-2300（Rocket Lake） | `0xA7` | **panic** | **需要** | 不需要 |
| 更新的（Granite Rapids、Sierra Forest 等） | — | **panic** | **需要** | 不需要 |

**"需要 CPUID 伪装"这一列是本节与 `71` 第 5.3 节的分歧所在。** `71` 第 5.3 节把 `Kernel/Emulate/Cpuid1Data` 与 `Cpuid1Mask` 留空，理由是"我们直接用 `-cpu` 选了一个 macOS 认识的型号"。**那个理由在 L2 上不成立，因为 L2 上我们写不了 `-cpu`。**

### 4.2 `Cpuid1Data` 是 L2 上替代 `-cpu` 的唯一手段

`KNOWN`，OpenCore 官方对这两个键的说明（转述自 <https://dortania.github.io/docs/latest/Configuration.html>）：

- `Cpuid1Data` 是 16 字节 plist data，内容是用来替换 XNU 内核中 CPUID(1) 调用结果的 EAX / EBX / ECX / EDX 序列。
- 它的三个主要用途之一是"让一个不被支持的 CPU 型号得到支持"。
- 通常只需要管 EAX，其余字节留零；字节序是小端。文档给的例子是 `C3 06 03 00` 表示 CPUID `0x0306C3`（Haswell）。
- `Cpuid1Mask` 是 `Cpuid1Data` 中有效位的位掩码：掩码位为 0 时用原始 CPU 的那一位，为 1 时取 `Cpuid1Data` 的值。
- 文档给出的四组推荐组合里有两组与我们相关：Rocket Lake（`0x0A0670`）伪装成 Comet Lake（`0x0A0655`）用 `Cpuid1Data = 55 06 0A 00 00...`、`Cpuid1Mask = FF FF FF FF 00...`；Alder Lake（`0x090672`）同样伪装成 Comet Lake。
- 文档同时提醒：XCPM 支持需要配套设置正确的频率向量。

**最后一条对我们不构成约束，因为第 2.6.2 节已确证 XCPM 在 guest 里不初始化。** 这反而让 `Cpuid1Data` 在我们的场景下比在真机上更安全：真机上伪装 CPUID 的主要风险是 XCPM 按错误的 model 去写频率向量，而这条风险在 guest 里不存在。

#### 4.2.1 两个可直接照抄的取值

CPUID(1) EAX 的位域（`KNOWN`，来源 <https://edc.intel.com/content/www/us/en/design/ipla/software-development-platforms/client/platforms/alder-lake-desktop/12th-generation-intel-core-processors-datasheet-volume-1-of-2/004/cpuid/>，该页给出 EAX 的字段划分为 Extended Family [27:20]、Extended Model [19:16]、Processor Type [13:12]、Family Code [11:8]、Model Number [7:4]、Stepping ID [3:0]）：

```text
effective_model  = (ExtendedModel << 4) | ModelNumber      （Family Code 为 6 或 15 时）
effective_family = Family Code                              （Family Code 不为 15 时）
```

**取值 A：伪装成 Comet Lake（model `0xA5`），对应 `iMac20,x`。**

```text
目标 CPUID = 0x000A0655
  ExtendedModel = 0xA, Family = 6, Model = 0x5  →  effective model = 0xA5 = 165
  Stepping = 5

Cpuid1Data  55 06 0A 00 00 00 00 00 00 00 00 00 00 00 00 00
Cpuid1Mask  FF FF FF FF 00 00 00 00 00 00 00 00 00 00 00 00
```

`KNOWN`：这组字节与 OpenCore 官方文档给出的 "Rocket Lake to Comet Lake" 组合逐字节相同，可以直接照抄。

**取值 B：伪装成 Skylake-W / Cascade Lake（model `0x55`），对应 `MacPro7,1`。**

```text
目标 CPUID = 0x00050657
  ExtendedModel = 0x5, Family = 6, Model = 0x5  →  effective model = 0x55 = 85
  Stepping = 7

Cpuid1Data  57 06 05 00 00 00 00 00 00 00 00 00 00 00 00 00
Cpuid1Mask  FF FF FF FF 00 00 00 00 00 00 00 00 00 00 00 00
```

**标签必须分开：**

- `KNOWN`：把 EAX 改成 `0x00050657` 会让 `cpuid_set_info` 的门 2 命中 `case 85` 并返回 `CPUFAMILY_INTEL_SKYLAKE`。这一点由第 2.3 节的 switch 表直接证明。
- `KNOWN`：EAX 的编码方式与 `Cpuid1Data` 的小端字节序。
- **`INFERRED`：stepping 取 `7`。** 门 2 只看 family 与 model，不看 stepping，所以任何 stepping 都能过门。选 7 的理由是它落在 Cascade Lake 的 stepping 区间内，和真机 `MacPro7,1` 更接近，从而减少"某处按 stepping 分支"的意外。真机 `MacPro7,1` 的确切 stepping 本文未取得，登记为 C-001。

**取值 B 优于取值 A**，理由两条：

1. 与 `71` 第 4.4 节选定的 `MacPro7,1` SMBIOS 一致。真机 `MacPro7,1` 的 CPU 就是 model `0x55`，所以 `X86PlatformPlugin` 加载 `Mac-27AD2F918AE68F61.plist` 时拿到的 CPUID 与 plist 的预期一致（这正是 `71` 第 5.2 节选 `Skylake-Server-v4` 的同一个理由，在 L2 上用 `Cpuid1Data` 达到同样效果）。
2. 伪装成 Comet Lake 会和 `iMac20,x` 的组合产生错配，而 `71` 第 4.3 节门 2 已经明确不要选 `iMac20,x`。

#### 4.2.2 `Cpuid1Data` 的三条限制

1. **它只改内核看到的 CPUID(1)，不改 CPUID 指令本身。** 用户态程序直接执行 `cpuid` 看到的仍是真实 CPU。`INFERRED`，依据：社区有记录指出用 `Cpuid1Data` 伪装 CPU 会让 Docker 在拉取镜像时因哈希计算错误而出问题（转述自 <https://github.com/acidanthera/bugtracker/issues/1035>），这只有在"内核与用户态看到不同 CPUID"时才会发生。
2. **它不改 leaf 7、不改 `0x80000001`、不改 hypervisor leaf。** 所以第 2.5 节的 AVX2 / FMA / BMI 判定仍按真实 CPU 走。对 Ice Lake-SP、Sapphire Rapids 这些目标不是问题（它们的特性集是 Skylake-SP 的超集）。
3. **它不解决拓扑问题。** 第 2.7.3 节的 `x86_validate_topology` 看的是 `nLThreadsPerPackage × nPackages` 与 MADT 的一致性，与 CPUID(1) EAX 无关。

**因此 L2 上的 Intel 路线有两种配置，取决于宿主的 model：**

| 情形 | `Cpuid1Data` | `Cpuid1Mask` |
|---|---|---|
| 宿主 model 在第 2.3 节表内（`0x55`、`0x9E`、`0xA5`、`0x7E` 等） | **留空** | 留空 |
| 宿主 model 不在表内 | **取值 B** | `FF FF FF FF 00 …` |

**默认按"留空"构建，只在 C-001 查明宿主是表外 model 时才加。** 理由与 `71` 第 4.5 节不加 `-no_compat_check` 的理由一样：无条件加上去会掩盖配置错误，让排查变难。而且第 6 节的判别流程能在一次启动里给出宿主的真实 model。

### 4.3 与 Cascade Lake-W 的差距具体在哪

宿主是 Xeon Scalable（SP）、SMBIOS 是 `MacPro7,1`（真机是 Cascade Lake-W）时，三类差距。

#### 4.3.1 topology：唯一真正要紧的一项

真机 `MacPro7,1` 是单 socket、8 到 28 核、启用 HT。云 guest 看到的是 hypervisor 合成的拓扑。

`KNOWN`，第 2.7.3 节的 panic 条件是 `nLThreadsPerPackage × nPackages != real_ncpus`。两侧的来源不同：

- 左侧来自 CPUID（leaf 1 EBX 的 `logical_per_package`、leaf 4 的 `cores_per_package`、leaf 0xB 的拓扑枚举），经 `_x86_set_logical_topology` 整理。
- 右侧 `real_ncpus` 来自 **ACPI MADT**，由固件（OVMF）生成。

**不一致的典型来源是 hypervisor 把 vCPU 平铺成 N 个单核 socket，而 CPUID 仍报宿主的 `logical_per_package`。** 这正是 `71` 第 8.2.4 节的 L1 命令行写 `-smp 8,cores=4,sockets=1,threads=2` 而不是 `-smp 8` 的原因（`71` 没有给出这个理由，本文补上）。

**在 L2 上我们控制不了 `-smp`。** 可用的手段按优先级：

1. **`ProvideCurrentCpuInfo = true`**（`71` 第 6.5.3 节已设为 `true`）。官方描述里 Intel 分支做的是"把 core count 补成 thread count 以支持非对称 SMP"，`KNOWN`。
2. **`cpus=N` boot-arg**，把参与的 CPU 数限制到一个能对上的值。`INFERRED`，社区文档把它列为核心/线程数上限问题的 workaround（转述自 <https://dortania.github.io/OpenCore-Install-Guide/macos-limits>）。
3. **`-nomsr35h`**，见第 2.8 节。它把 core/thread 定成 1/1，可能让左侧变成一个确定值。`INFERRED`，副作用未知，登记为 C-009。

**判别方法**：串口上 `x86_validate_topology() %d threads but %d registered from MADT` 这一行会把两个数字都打出来。**这是整条 Intel 路线上最可能的失败点，而它的 panic 文本自带诊断信息。**

#### 4.3.2 MSR：差距存在但不构成障碍

真机 Cascade Lake-W 与 Skylake-SP 的 MSR 差异集中在 power management 与 uncore（`MSR 0x620` UNCORE_RATIO_LIMIT、`MSR 0x1AD` TURBO_RATIO_LIMIT、`MSR 0x610` PKG_POWER_LIMIT 等）。

`KNOWN`，第 2.8 节的全表显示：**这些 MSR 在 25G325 的内核里只被 `_xcpm_*` 系列访问**（`0x1AD` / `0x1AE` 在 `_xcpm_dvfs_configure`，`0x1FC` 在 `_xcpm_init` / `_xcpm_cpu_control` / `_xcpm_disable_rth`），而第 2.6.2 节确证 XCPM 在 guest 里不初始化。

> **结论：Cascade Lake-W 与 Skylake-SP 之间的 MSR 与 uncore 差异在云 guest 里不产生任何后果，因为唯一会读写它们的那套代码不运行。** `KNOWN`。

#### 4.3.3 `X86PlatformPlugin` 的 per-board-id plist

`KNOWN`，第 2.6.1 节的索引检索确认 `X86PlatformPlugin.kext/Contents/Resources/Mac-27AD2F918AE68F61.plist` 存在（14,878 字节，`payload.050`），共 50 份 per-board-id plist。另有一个 `VMPlatformPlugin.kext`（3 条路径）。

`INFERRED`：`X86PlatformPlugin` 的 plist 描述的是 P-state 表、温度门限与风扇曲线。在 XCPM 不运行、没有 SMC 温度源（`isa-applesmc` 是模拟的）的 guest 里，这些数据没有消费者。`VMPlatformPlugin` 的存在暗示 Apple 为虚机准备了一个专用 plugin，**但它是否有 x86_64 代码、在什么条件下匹配，本文未取得**。登记为 C-015。

**本项目的处置：不动。** 不注入、不 block、不替换。首启探针（`71` 第 10 节 G 段）里加一条 `ioreg -r -c X86PlatformPlugin -d 1` 与 `ioreg -r -c VMPlatformPlugin -d 1`，把现状记录为基线即可。

### 4.4 Kernel Quirks 逐项裁决

这是 `71` 第 6.5.3 节在"无法控制 CPUID 的云 guest"这一前提下的重新裁决。**与 `71` 的取值全部一致，但理由全部升级。**

| Quirk | 本项目 | 理由（按本文的一手证据） |
|---|---|---|
| `ProvideCurrentCpuInfo` | **`true`** | 官方描述里 KVM 分支提供预算的 MSR 35h 值（`KNOWN`，<https://dortania.github.io/docs/latest/Configuration.html>）。第 2.8 节确认 `_cpuid_set_info` 会无条件读 `MSR 0x35`（除非 `-nomsr35h`），而云平台是否服务这个 MSR 未知（C-004）。**这是全表里唯一必须开的一项。** 它在 AMD 路线上还是 AMD_Vanilla 的硬依赖（README 明确不开则不启动） |
| `AppleCpuPmCfgLock` | **`false`** | 第 2.6.1 节：目标 kext `AppleIntelCPUPowerManagement` 在 25G325 中不存在，补丁没有对象。开它只会增加一次失配的机会 |
| `AppleXcpmCfgLock` | **`false`** | 第 2.6.2 节：XCPM 在 guest 里不初始化，`MSR 0xE2` 的访问路径不执行 |
| `AppleXcpmExtraMsrs` | **`false`** | 同上 |
| `AppleXcpmForceBoost` | **`false`** | 同上。另外它本身的作用是把 HWP request 钉在最高性能，在没有 HWP 的 guest 里无意义 |
| `DummyPowerManagement`（在 `Kernel/Emulate` 下） | `true`（沿用 `71`），但**视为空操作** | 第 2.6.1 节：官方把它的 `Requirement` 标为 10.4-12，而目标 kext 不存在。保留是为了和 `71` 第 5.3 节的片段一致，不要把它当保护 |
| `LapicKernelPanic` | **`false`** | 官方描述是"禁用 LAPIC 中断导致的 kernel panic"（`KNOWN`，同一文档）。`71` 第 6.5.3 节已设 `false`。AMD 路线上对应的是 AMD_Vanilla 第 16 条补丁（去掉 `_lapic_init` 的版本检查），两者不是同一件事，不要互相替代 |
| `PanicNoKextDump` | `false` | 沿用 `71`。本文新增一条理由：CPU 相关 panic 发生在 kext 加载之前，这一项对 CPU 诊断没有帮助，但也没有坏处 |
| `Cpuid1Data` / `Cpuid1Mask`（在 `Kernel/Emulate` 下） | **默认留空，按第 4.2.2 节的表决定** | **这是本文对 `71` 第 5.3 节的修正**：`71` 的"永远留空"只适用于我们能写 `-cpu` 的 L1 |
| `Kernel/Scheme/KernelArch` | `x86_64` | 沿用 `71` 第 6.1 节。注意第 2.5 节的 `cpu_subtype` 判定与这一项无关，OpenCore 的 `KernelArch` 选的是 fat 内核的 slice |

### 4.5 `MSR 0xE2` / `0x1AA` 被拦截或不存在时的后果

这是任务里点名要回答的一项，答案比预期简单。

`KNOWN`，第 2.8 节的静态扫描结果：

| MSR | 全部访问点 |
|---|---|
| `0xE2`（`MSR_PKG_CST_CONFIG_CONTROL`） | `rdmsr` @ `_xcpm_init`；`wrmsr` @ `_xcpm_idle` |
| `0x1AA`（`MSR_MISC_PWR_MGMT`） | `rdmsr` @ `_xcpm_hwp_enable`、`_xcpm_init` |

两个 MSR **在 25G325 的内核里没有任何 XCPM 之外的访问点**。结合第 2.6.2 节：

> **在云 guest 里，`MSR 0xE2` 与 `0x1AA` 一次都不会被访问。它们被 hypervisor 拦截、返回 0、或触发 `#GP`，对 macOS 26 都没有后果。** `KNOWN`。

这推翻了"必须开 `AppleXcpmCfgLock` 才能在非 Apple 平台上启动"这条广为流传的说法在**本场景**下的适用性。那条说法对 macOS 10.11 到 10.15 时代的真机成立（那时 BIOS 会锁 `0xE2`，而 XCPM 会去写它），对 macOS 26 的虚机不成立。

真正值得担心的是另外几个 MSR，按风险排序：

| MSR | 风险 | 后果 | 缓解 |
|---|---|---|---|
| **`0x198` / `0x199`** | **最高。** `_i386_init` 无条件读，极早期 | 不被服务则 `#GP` → early panic，串口上在 `Darwin Kernel Version` 之后很快静默 | 宿主 `kvm ignore_msrs=1`（L2 不可控）；或 AMD_Vanilla 第 15 条补丁（但那是 AMD 配置）。登记为 C-004 |
| `0x35` | 中。`_cpuid_set_info` 读 | 返回 0 则 core/thread 全 0，随后拓扑校验失败 | `ProvideCurrentCpuInfo = true`；或 `-nomsr35h` |
| `0xCE` / `0x194` | 中。`_tsc_init` 在路 A 的 `default` 分支读 | `tscGranularity = 0` → 除零。**但 model `0x55` 走 ART 分支，不走 `default`** | CPUID leaf `0x40000010`（C-003）；或 DataHub 的 `ARTFrequency` / `FSBFrequency` |
| `0x8B` | 低。`_cpuid_set_info` 先写 0 再读 | 写被拦截通常无害，读返回 0 则微码版本显示为 0 | 无需处理 |
| `0x17` | 低 | 返回 0 则 `cpuid_model_string` 索引为 0 | 无需处理 |
| `0x277`（PAT） | 低（Intel）/ 中（AMD） | Intel 上 PAT 布局与 Apple 预期一致；AMD 上需要第 23 条补丁 | Intel 路线不动 |
| `0x1D9` | 低。即使 LBR 关闭也要清 bit 0 | 写被拦截无害 | 无需处理 |

**`0x198` / `0x199` 是 Intel 路线上第二大风险点，仅次于第 4.3.1 节的拓扑。** 它的特征是"看得到 `Darwin Kernel Version` 这一行，然后立刻静默"，与"看不到 `Darwin Kernel Version`"（CPU 门没过）和"看到大量驱动匹配行之后才停"（磁盘问题）都能区分。见第 6 节。

---

## 5. D. 两条路线的判别与自适应

### 5.1 在 guest 内判别宿主 CPU

前提：实例上先装一个 Linux（Vultr 的默认镜像即可），把 CPU 事实采完，再决定造哪一份 EFI。**这一步的成本是一次最小实例一小时，它把"抽卡"变成"已知"。**

#### 5.1.1 判别脚本

输出是一个 JSON，字段名直接对应第 5.3 节构建脚本的入参。全部只用标准库与内核自带的两个字符设备。

```bash
#!/usr/bin/env bash
# scripts/probe-host-cpu.sh  —— 在 Linux guest 内执行，输出 host-cpu.json
set -euo pipefail

# cpuid / msr 两个字符设备需要先加载模块。probe 失败不致命，脚本会在 JSON 里标注。
sudo modprobe cpuid 2>/dev/null || true
sudo modprobe msr   2>/dev/null || true

sudo python3 - <<'PY'
import json, os, struct, subprocess, sys

CPUID = "/dev/cpu/0/cpuid"
MSR   = "/dev/cpu/0/msr"

def cpuid(leaf, subleaf=0):
    """读 CPUID。位置 = leaf | (subleaf << 32)，一次读 16 字节 = eax,ebx,ecx,edx。"""
    try:
        with open(CPUID, "rb", buffering=0) as f:
            f.seek(leaf | (subleaf << 32))
            b = f.read(16)
        if len(b) != 16:
            return None
        return dict(zip("eax ebx ecx edx".split(), struct.unpack("<4I", b)))
    except OSError:
        return None

def rdmsr(idx):
    """读 MSR。返回 int，或 None 表示该 MSR 不被服务（#GP -> EIO）。"""
    try:
        with open(MSR, "rb", buffering=0) as f:
            f.seek(idx)
            b = f.read(8)
        return struct.unpack("<Q", b)[0] if len(b) == 8 else None
    except OSError:
        return None

def regstr(*vals):
    return b"".join(struct.pack("<I", v) for v in vals).rstrip(b"\x00").decode("ascii", "replace")

out = {"schema": "metal2vu.hostcpu/1"}

# ---------- 1. 厂商与签名 ----------
l0 = cpuid(0)
if l0 is None:
    sys.exit("cannot read %s; is the 'cpuid' module loaded and are you root?" % CPUID)
out["max_basic_leaf"] = l0["eax"]
out["vendor_id"]      = regstr(l0["ebx"], l0["edx"], l0["ecx"])   # 注意 EBX,EDX,ECX 的顺序

l1 = cpuid(1)
sig = l1["eax"]
fam  = (sig >> 8) & 0xF
mdl  = (sig >> 4) & 0xF
extf = (sig >> 20) & 0xFF
extm = (sig >> 16) & 0xF
eff_family = fam + extf if fam == 0xF else fam
eff_model  = (extm << 4) | mdl if fam in (6, 0xF) else mdl
out["cpuid1_eax"]      = "0x%08X" % sig
out["family"]          = eff_family
out["model"]           = eff_model
out["model_hex"]       = "0x%02X" % eff_model
out["stepping"]        = sig & 0xF
out["logical_per_pkg"] = (l1["ebx"] >> 16) & 0xFF
out["hypervisor_bit"]  = bool(l1["ecx"] & (1 << 31))

# ---------- 2. 第 2.3 节的 model 白名单 ----------
XNU_CPUFAMILY = {
    0x17: "PENRYN",
    0x1A: "NEHALEM", 0x1E: "NEHALEM", 0x1F: "NEHALEM", 0x2E: "NEHALEM",
    0x25: "WESTMERE", 0x2C: "WESTMERE", 0x2F: "WESTMERE",
    0x2A: "SANDYBRIDGE", 0x2D: "SANDYBRIDGE",
    0x3A: "IVYBRIDGE", 0x3E: "IVYBRIDGE",
    0x3C: "HASWELL", 0x3F: "HASWELL", 0x45: "HASWELL", 0x46: "HASWELL",
    0x3D: "BROADWELL", 0x47: "BROADWELL",
    0x4E: "SKYLAKE", 0x55: "SKYLAKE", 0x5E: "SKYLAKE",
    0x7D: "ICELAKE", 0x7E: "ICELAKE", 0x9F: "ICELAKE",
    0x8E: "KABYLAKE", 0x9E: "KABYLAKE",
    0xA5: "COMETLAKE",
}
native = (out["vendor_id"] == "GenuineIntel"
          and eff_family == 6
          and eff_model in XNU_CPUFAMILY)
out["xnu_cpufamily"]         = XNU_CPUFAMILY.get(eff_model) if eff_family == 6 else None
out["natively_supported"]    = native
out["needs_cpuid_spoof"]     = (out["vendor_id"] == "GenuineIntel") and not native
out["needs_amd_patches"]     = (out["vendor_id"] == "AuthenticAMD")

# ---------- 3. 第 2.5 节的 x86_64h 特性门 ----------
l7   = cpuid(7, 0) or {"ebx": 0, "ecx": 0, "edx": 0}
l81  = cpuid(0x80000001) or {"ecx": 0, "edx": 0}
feat = {
    "sse4_2": bool(l1["ecx"] & (1 << 20)),
    "movbe":  bool(l1["ecx"] & (1 << 22)),
    "popcnt": bool(l1["ecx"] & (1 << 23)),
    "avx":    bool(l1["ecx"] & (1 << 28)),
    "fma":    bool(l1["ecx"] & (1 << 12)),
    "lzcnt":  bool(l81["ecx"] & (1 << 5)),
    "bmi1":   bool(l7["ebx"] & (1 << 3)),
    "avx2":   bool(l7["ebx"] & (1 << 5)),
    "bmi2":   bool(l7["ebx"] & (1 << 8)),
    "avx512f": bool(l7["ebx"] & (1 << 16)),
}
out["features"]      = feat
out["x86_64h_ok"]    = all(feat[k] for k in
                           ("sse4_2","movbe","popcnt","avx","fma","lzcnt","bmi1","avx2","bmi2"))
out["cpuid1_ecx"]    = "0x%08X" % l1["ecx"]
out["cpuid1_edx"]    = "0x%08X" % l1["edx"]
out["leaf7_ebx"]     = "0x%08X" % l7["ebx"]

# ---------- 4. hypervisor leaf 与第 2.7.4 节的 TSC 路径 ----------
hv = {}
lh = cpuid(0x40000000)
if lh:
    hv["max_hv_leaf"] = "0x%08X" % lh["eax"]
    hv["hv_vendor"]   = regstr(lh["ebx"], lh["ecx"], lh["edx"])
    if lh["eax"] >= 0x40000010:
        t = cpuid(0x40000010)
        hv["leaf_40000010_present"] = True
        hv["tsc_khz"] = t["eax"]
        hv["bus_khz"] = t["ebx"]
        hv["tsc_init_path"] = "B (VMM provides frequencies)" if (t["eax"] and t["ebx"]) else "A"
    else:
        hv["leaf_40000010_present"] = False
        hv["tsc_init_path"] = "A (kernel must read MSR 0xCE / 0x194 or EFI DataHub)"
out["hypervisor"] = hv

# ---------- 5. 第 4.5 节的 MSR 可用性探测 ----------
probe = {}
for name, idx in [("IA32_PLATFORM_ID",0x17), ("IA32_CORE_THREAD_COUNT",0x35),
                  ("IA32_BIOS_SIGN_ID",0x8B), ("MSR_PLATFORM_INFO",0xCE),
                  ("MSR_FLEX_RATIO",0x194), ("IA32_PERF_STATUS",0x198),
                  ("IA32_PERF_CTL",0x199), ("IA32_MISC_ENABLE",0x1A0),
                  ("IA32_MTRRCAP",0xFE), ("IA32_PAT",0x277),
                  ("IA32_MCG_CAP",0x179), ("IA32_APIC_BASE",0x1B)]:
    v = rdmsr(idx)
    probe[name] = {"index": "0x%X" % idx,
                   "served": v is not None,
                   "value": ("0x%016X" % v) if v is not None else None}
# MSR 0x35 的解码，用来和 x86_validate_topology 的左侧对账
m35 = rdmsr(0x35)
if m35:
    probe["IA32_CORE_THREAD_COUNT"]["core_count"]   = (m35 >> 16) & 0xFFFF
    probe["IA32_CORE_THREAD_COUNT"]["thread_count"] = m35 & 0xFFFF
# MSR 0xCE 的 max non-turbo ratio，第 2.7.4 节的除零源
if probe["MSR_PLATFORM_INFO"]["served"]:
    pi = rdmsr(0xCE)
    probe["MSR_PLATFORM_INFO"]["max_non_turbo_ratio"] = (pi >> 8) & 0xFF
    probe["MSR_PLATFORM_INFO"]["tsc_granularity_would_be_zero"] = ((pi >> 8) & 0xFF) == 0
out["msr_probe"] = probe

# ---------- 6. 拓扑，用来估第 4.3.1 节的两侧 ----------
def sh(c):
    try: return subprocess.run(c, shell=True, capture_output=True, text=True).stdout.strip()
    except Exception: return ""
out["topology"] = {
    "nproc":            sh("nproc"),
    "sockets":          sh("lscpu | awk -F: '/^Socket/{gsub(/ /,\"\",$2);print $2}'"),
    "cores_per_socket": sh("lscpu | awk -F: '/^Core\\(s\\) per socket/{gsub(/ /,\"\",$2);print $2}'"),
    "threads_per_core": sh("lscpu | awk -F: '/^Thread\\(s\\) per core/{gsub(/ /,\"\",$2);print $2}'"),
    "model_name":       sh("lscpu | sed -n 's/^Model name: *//p'"),
    "hypervisor":       sh("lscpu | sed -n 's/^Hypervisor vendor: *//p'"),
}
out["dmi_processor"] = sh("dmidecode -t 4 2>/dev/null | sed -n '1,40p'")

# ---------- 7. 第 4.2 节的 Cpuid1Data 建议值 ----------
if out["needs_cpuid_spoof"]:
    # 目标 0x00050657 = family 6 / model 0x55 / stepping 7，见 4.2.1 取值 B
    out["recommend"] = {
        "Cpuid1Data": "57 06 05 00 00 00 00 00 00 00 00 00 00 00 00 00",
        "Cpuid1Mask": "FF FF FF FF 00 00 00 00 00 00 00 00 00 00 00 00",
        "note": "spoof to CPUID 0x00050657 (Skylake-W / Cascade Lake), matches MacPro7,1 SMBIOS",
    }
elif out["needs_amd_patches"]:
    out["recommend"] = {
        "efi_variant": "amd",
        "cores_per_package_byte": "0x%02X" % int(out["topology"]["cores_per_socket"] or 0),
        "note": "AMD_Vanilla patch set required; see 72-CPU-COMPAT.md section 3",
    }
else:
    out["recommend"] = {"efi_variant": "intel", "Cpuid1Data": "", "Cpuid1Mask": ""}

print(json.dumps(out, indent=2))
PY
```

运行与归档：

```bash
sudo bash scripts/probe-host-cpu.sh | tee host-cpu-$(hostname)-$(date -u +%Y%m%dT%H%M%SZ).json
```

#### 5.1.2 四个字段决定一切

脚本输出里只有四个字段会改变构建决策：

| 字段 | 取值 | 决策 |
|---|---|---|
| `vendor_id` | `GenuineIntel` | 走 Intel EFI |
| | `AuthenticAMD` | 走 AMD EFI |
| `natively_supported` | `true` | `Cpuid1Data` 留空 |
| | `false` | 按 `recommend.Cpuid1Data` 填 |
| `hypervisor.leaf_40000010_present` | `false` | `_tsc_init` 走路 A，必须确认 `msr_probe.MSR_PLATFORM_INFO.served` 与 `max_non_turbo_ratio != 0`，或依赖 DataHub |
| `msr_probe.IA32_PERF_STATUS.served` 与 `IA32_PERF_CTL.served` | 任一 `false` | **Intel 路线上这是一个阻断项**（第 4.5 节），因为 `_i386_init` 无条件读它们而我们没有宿主侧 `ignore_msrs` |

**`msr_probe` 的那一段是整个脚本里最有价值的部分，因为它用 Linux 把 `#GP` 探出来了。** Linux 读 MSR 走的是同一条 KVM 路径，所以 `served: false` 等于"macOS 读这个 MSR 也会 `#GP`"。`INFERRED`，依据是两者都经过同一个 `rdmsr` 退出路径；差别只在 Linux 把 `#GP` 变成 `EIO` 返回用户态，而 macOS 内核里的 `rdmsr` 没有异常处理，直接 panic。

### 5.2 一份镜像能不能同时支持 Intel 与 AMD

**不能。结论是必须出两份 EFI。**

#### 5.2.1 OpenCore 没有按 CPU 厂商生效的机制

`KNOWN`，来源：OpenCore 官方文档的 `Kernel/Patch` 属性清单（转述自 <https://dortania.github.io/docs/latest/Configuration.html>，第 7.7 节 Patch Properties）。`Kernel/Patch` 条目的全部字段是：

```text
Arch   Base   Comment   Count   Enabled   Find   Identifier   Limit
Mask   MaxKernel   MinKernel   Replace   ReplaceMask   Skip
```

`Arch` 的取值是 `i386` / `x86_64` / `Any`，即 CPU **架构**，不是厂商、不是 family、不是 model。`MinKernel` / `MaxKernel` 按 Darwin 版本过滤。**没有任何一个字段能表达"仅当 CPUID 厂商串为 AuthenticAMD 时生效"。**

`Kernel/Add`、`Kernel/Block`、`Kernel/Force`、`Kernel/Emulate` 同样只有 `Arch` + `MinKernel` / `MaxKernel`。`ACPI/Patch`、`Booter/Patch`、`DeviceProperties` 也没有厂商条件。

本轮实测的一个侧面印证：`AMD_Vanilla` 的 25 条补丁全部靠 `MinKernel` / `MaxKernel` + `Arch` 区分，没有任何一条带厂商条件（`KNOWN`，`patches.plist` 的字段集与上表完全一致）。社区如果有这个机制，一定会用。

#### 5.2.2 把 AMD 补丁打在 Intel 上是破坏性的

`INFERRED`，依据是第 2.2、2.3 节的反编译结果加上补丁语义，不是实测。

| 补丁 | 在 Intel 上的效果 |
|---|---|
| 第 12 条（NOP 掉 `GenuineIntel` 的 `jnz`） | 无害。Intel 上那个 `jnz` 本来不跳 |
| **第 14 条（强制 `CPUFAMILY_INTEL_PENRYN`）** | **破坏性。** 它把 `cpuid_cpufamily` 从真实值改成 `0x78EA4FBC`。直接后果：`_cpuid_set_info` 的 MSR 0x35 分支从"读 MSR 0x35"切到"用 `logical_per_package`"；`_tsc_init` 从 ART 分支切到 PENRYN 分支（读 `MSR 0x198` 的 bus ratio）；`_i386_lbr_init` 的 cpufamily 白名单里没有 PENRYN，一旦用了 `lbr_mode` 就 panic。再加上第 3.7 节末尾那条未知：用户态按 cpufamily 选路的代码全部拿到错值 |
| **第 3 条（cores_per_package 常量化）** | **破坏性。** Intel 上这个值本来是对的，改成常量后若与实例 vCPU 数不符，第 2.7.3 节的拓扑校验直接 panic |
| 第 15 条（去 `_i386_init` 的 rdmsr） | 在 KVM 上**可能有益**（规避 C-004），但它同时抹掉了 `busFreq` 相关的一次读取，副作用未评估 |
| 第 5 条（cache leaf 改 `0x8000001D`） | **破坏性。** Intel 不实现 leaf `0x8000001D`，cache 信息会全零 |
| 第 23 条（PAT 修正） | Intel 上 PAT 布局与 Apple 预期一致，改它是无意义的风险 |
| 第 19、20 条（non-monotonic time panic） | 在 Intel 上也许有益（规避 TSC 不同步），但第 20 条在 25G325 上会误打两处无关代码（第 3.3.1 节） |

**没有人测过"AMD_Vanilla 全集打在 Intel 上"，因为没有人会这么做。** 把它当作未定义行为处理。

#### 5.2.3 两份 EFI 的切换方案

`71` 第 8 节的产物表新增一列"CPU 变体"。两份 EFI 共用同一条构建管线，只在 `config.plist` 生成时分叉。

对 `71` 第 6.1 节 `scripts/make-oc-config.py` 的改造（新增一个参数，其余不动）：

```python
#!/usr/bin/env python3
"""scripts/make-oc-config.py  （对 71 第 6.1 节脚本的扩展）
用法:  py make-oc-config.py <Sample.plist> <out config.plist> <intel|amd> [<host-cpu.json>]
"""
import json, plistlib, sys

SRC, DST, VARIANT = sys.argv[1], sys.argv[2], sys.argv[3]
HOST = json.load(open(sys.argv[4])) if len(sys.argv) > 4 else {}
assert VARIANT in ("intel", "amd")

c = plistlib.load(open(SRC, 'rb'))
# ... 71 第 6.1 节的全部内容照旧 ...

# ========== 72 分册新增：CPU 变体分叉 ==========
def hexb(s):
    return bytes.fromhex(s.replace(' ', ''))

# 1) Kernel/Quirks：两条路线共同的唯一必需项
c['Kernel']['Quirks']['ProvideCurrentCpuInfo'] = True       # 见 72 第 4.4 节
for k in ('AppleCpuPmCfgLock', 'AppleXcpmCfgLock',
          'AppleXcpmExtraMsrs', 'AppleXcpmForceBoost', 'LapicKernelPanic'):
    c['Kernel']['Quirks'][k] = False                        # 见 72 第 2.6、4.4 节

# 2) Kernel/Emulate：CPUID 伪装只在 Intel 且宿主 model 不在白名单时才填
c['Kernel']['Emulate']['Cpuid1Data'] = b''
c['Kernel']['Emulate']['Cpuid1Mask'] = b''
if VARIANT == 'intel' and HOST.get('needs_cpuid_spoof'):
    # 72 第 4.2.1 节取值 B：0x00050657 = Skylake-W / Cascade Lake
    c['Kernel']['Emulate']['Cpuid1Data'] = hexb('57060500' + '00'*12)
    c['Kernel']['Emulate']['Cpuid1Mask'] = hexb('FFFFFFFF' + '00'*12)

# 3) Kernel/Patch：只有 amd 变体带补丁。intel 变体必须是空数组
if VARIANT == 'amd':
    patches = plistlib.load(open('vendor/AMD_Vanilla/patches.plist', 'rb'))['Kernel']['Patch']
    cores = int(HOST['recommend']['cores_per_package_byte'], 16)
    assert 1 <= cores <= 255, 'bad physical core count'
    for p in patches:
        p['Base'] = (p.get('Base') or '').strip()           # 见 72 第 3.1.2 节：第 14 条末尾有空格
        if p.get('Comment', '').startswith('algrey | Force cpuid_cores_per_package'):
            # Replace = BA <CC> 00 00 00，见 72 第 3.4 节
            r = bytearray(p['Replace'])
            r[1] = cores
            p['Replace'] = bytes(r)
    c['Kernel']['Patch'] = patches
else:
    c['Kernel']['Patch'] = []

plistlib.dump(c, open(DST, 'wb'), sort_keys=True)
print('wrote', DST, 'variant', VARIANT)
```

构建两份 EFI：

```powershell
# Intel 变体（默认）
py scripts\make-oc-config.py oc\Docs\Sample.plist build\efi-intel\EFI\OC\config.plist intel host-cpu.json
# AMD 变体
py scripts\make-oc-config.py oc\Docs\Sample.plist build\efi-amd\EFI\OC\config.plist   amd   host-cpu.json
```

然后按 `71` 第 8.2.2、8.3.3、8.3.4 节各封一份镜像，产物名加 `-intel` / `-amd` 后缀，`image-manifest.json` 的 `platform_profile` 一段新增三个字段：

```json
"platform_profile": {
  "cpu_variant": "intel",
  "cpu_spoof": { "cpuid1_data": "", "cpuid1_mask": "" },
  "amd_patch_source": null,
  "host_cpu_probe": "host-cpu-20261030T091452Z.json"
}
```

**三条纪律：**

1. **`Kernel/Patch` 在 Intel 变体里必须是空数组，不是"条目存在但 `Enabled = false`"。** 空数组在首启探针里可以直接验证（`nvram` 读不到补丁，但 OpenCore 的 DEBUG 日志会列出应用了几条补丁）。留着禁用的条目等于把一个一键踩雷的开关留在镜像里。
2. **不要试图在运行时切 `config.plist`。** OpenCore 只读 `EFI/OC/config.plist` 一个路径，想切就得在 ESP 上改文件，而改文件要先启动起来，循环依赖。
3. **构建期必须跑补丁匹配门禁。** 把第 1.2 节第 3 条的扫描做成一个脚本，对 AMD 变体的每一条补丁核对"命中数是否等于 `Count`，且前 `Count` 个命中是否落在注释声明的函数里"。第 3.3 节的两个失配就是这个门禁要挡住的东西。门禁的输入是目标版本的 `kernel.x86_64`，仓库里已经有了。

### 5.3 如果 CPUID 是 `AuthenticAMD`，AMD 补丁是唯一出路

**这个推理成立，而且比表述得更硬。** 逐步：

1. **门 1 必须过。** 第 2.2 节：`strncmp("GenuineIntel", cpuid_vendor, 16) != 0` 直接 `panic("Unsupported CPU @cpuid.c:1183")`。不是降级，不是警告，是启动期 panic。`KNOWN`。
2. **我们改不了 CPUID 的厂商串。** `-cpu ...,vendor=GenuineIntel` 是 QEMU 侧参数，L2 上不可写。`KNOWN`（`80` 第 1.7 节：设备模型与实例参数固定不可改）。
3. **`Cpuid1Data` 改不了厂商串。** 官方描述它替换的是 **CPUID(1)** 的 EAX/EBX/ECX/EDX，而厂商串在 **CPUID(0)** 的 EBX/EDX/ECX。`KNOWN`（<https://dortania.github.io/docs/latest/Configuration.html>）。OpenCore 没有 `Cpuid0Data` 这个键。
4. **因此唯一剩下的手段是改内核里那条比较。** 这正是 `AMD_Vanilla` 第 12 条（NOP 掉 `jnz`）与第 14 条（强制 cpufamily）做的事。
5. 门 2 同理：AMD 的 family 是 `0x17` / `0x19` / `0x1A`，而第 2.3 节的 switch 整个包在 `if (family == 6)` 里。`Cpuid1Data` **理论上**可以把 EAX 的 family 字段也改成 6（掩码位全开就会一起改），但那样 model 字段也要一起编，而且随之而来的 cache leaf、`logical_per_package`、拓扑枚举全部仍是 AMD 的真实值，没有任何社区实践走这条路。**不要尝试。**

> **结论：`AuthenticAMD` 宿主上，`AMD_Vanilla` 风格的内核字节补丁是唯一出路，没有替代方案。** `KNOWN`（步骤 1、3、5）+ `INFERRED`（步骤 4 的"唯一"）。

### 5.4 它在 Tahoe 上的成熟度评估

把第 3.1.3 与 3.2、3.3 节合起来打分。

| 维度 | 状态 | 证据等级 |
|---|---|---|
| 官方声明 | README 列出 macOS Tahoe (26) 为支持版本 | `KNOWN`（文档） |
| 补丁内容的最后一次更新 | 2025-06-10，Tahoe 还在 beta 阶段 | `KNOWN`（commit 历史） |
| 对 Darwin 25.4+ 的适配 | PR #215，2026-03-29 提交，**至今未合入** | `KNOWN`（PR 状态） |
| 对 25G325 的实测匹配率 | 14 条默认启用的 kernel 补丁里 **13 条正确**，第 20 条**目标未命中且误打两处**；唯一一条默认启用的 `IOPCIFamily` 补丁（第 17 条）**零命中** | `KNOWN`（本轮扫描） |
| 修复可得性 | PR #215 的替换条目在 25G325 上**实测正确**（命中 3，前 2 为目标） | `KNOWN`（本轮扫描） |
| Zen 5（family 1Ah） | 不在 README 声明的 family 范围内 | `KNOWN`（文档）+ `INFERRED`（后果） |
| 核心数常量 | 必须按实例 vCPU 拓扑逐规格手填一个字节 | `KNOWN`（README + 本轮匹配） |
| 对本项目特有的风险 | `CPUFAMILY_INTEL_PENRYN` 伪装对 Metal 栈的影响未知 | `BLOCKED` |

**评级：可用但不成熟，构成必须上报的重大风险，理由不是"补丁不存在"而是"补丁的正确性没有维护者在跟 Tahoe 正式版"。**

具体地说，风险的形状是这样的：

- **当前这一刻**，用 master 的 `patches.plist` 直接上 25G325 的 AMD 宿主，大概率在 `thread_invoke` / `thread_dispatch` 的 non-monotonic time panic 上死，因为那条补丁没打上（第 3.3.1 节）。
- **这个具体问题有确定的修法**，而且本文已经在目标二进制上验证过。所以它不是阻断项。
- **真正的风险是结构性的**：每一次 macOS 26.x 点版本更新都可能再次移动结构偏移，而上游没有在跟。本项目的基线固定在 25G325（`00-OVERVIEW` 第 2.3 节），所以**对本项目而言这个风险可以被"固定基线 + 构建期匹配门禁"完全消化**。门禁见第 5.2.3 节纪律 3。
- **不可消化的部分只有一条**：第 3.7 节末尾的 `CPUFAMILY_INTEL_PENRYN` 对 Metal 栈的影响。它不是启动问题，而是"启动成功之后 Metal 栈行为可能不同"，而本项目的全部价值在 Metal 栈上。

**因此本文的建议是：把 Intel 作为 L2 的主路线，AMD 作为备用路线，而不是反过来。** 第 7 节会说明这个建议在 Vultr 上为什么是可执行的而不只是愿望。

---

## 6. E. 失败表现与诊断

`71` 第 9.6 节给出了串口日志的六个阶段标记。本节在那六个标记上加一层 CPU 维度，目标是让 E0-L1 / E0-L2 失败时**一眼区分"CPU 不兼容"、"磁盘找不到"、"board-id 不对"这三类**。

### 6.1 五类 CPU 失败的串口特征

全部 panic 文本与源码位置为 `KNOWN`，逐条取自第 2 节的反编译；"停在哪个阶段"为 `INFERRED`，依据是各函数在启动序列中的位置。

| # | 失败 | 串口上的特征行 | 出现位置（相对 `71` 9.6 的阶段） | 根因 |
|---|---|---|---|---|
| **1** | CPU 厂商或 family/model 不被支持 | `panic(cpu 0 caller ...): Unsupported CPU @/.../cpuid.c:1183` | **阶段 ③ 之前**。`Darwin Kernel Version` 可能已经打出，紧随其后就是这条 panic。若加了 `-cpuid`，前面会有 `cpuid_set_cpufamily(0x...) returning 0x0` | 第 2.2 节两道门。`AuthenticAMD` 或 model 不在第 2.3 节表内 |
| **2** | 早期 MSR 不被服务 | **没有 panic 文本，直接静默。** 最后一行通常是 `Darwin Kernel Version 25.x.x` 或紧随其后的几行 | 阶段 ③ 刚开始 | `_i386_init` 读 `MSR 0x198` / `0x199` 收到 `#GP`，而那个阶段还没有 panic 基础设施能把文本送出去。第 4.5 节 |
| **3** | 拓扑不一致 | `panic(...): x86_validate_topology() N threads but M registered from MADT @/.../cpu_threads.c:1041`。**两个数字都在行里** | 阶段 ③，在 `AppleACPIPlatform` 之前 | 第 2.7.3 节。CPUID 推出的线程数与 MADT 不符 |
| **4** | TSC 频率拿不到 | `panic(...): tsc_init: EFI not supported! @/.../tsc.c:261`；或**无文本的 `#DE`**（除零） | 阶段 ③ 早期 | 第 2.7.4 节路 A。`busFreq == 0`，或 `tscGranularity == 0` |
| **5** | TSC 非单调（AMD，补丁未生效） | `panic(...): Non-monotonic time: invoke at 0x..., runnable at 0x...` 或 `Non-monotonic time: dispatch at ...` 或 `Non-monotonic time: last_dispatch at ..., ctime 0x...` | 阶段 ③ 之后，可能已经进入用户态 | 第 3.3.1 节。`AMD_Vanilla` 第 19 / 20 条补丁未命中 |

三条 `Non-monotonic time` 格式串在本样本中的位置（`KNOWN`，用于做 `Detector` 的正则）：

```text
0x0096b6cd  Non-monotonic time: last_dispatch at 0x%llx, ctime 0x%llx @%s:%d
0x0096b844  Non-monotonic time: dispatch at 0x%llx, runnable at 0x%llx @%s:%d
0x0096bbe7  Non-monotonic time: invoke at 0x%llx, runnable at 0x%llx @%s:%d
```

（这是文件偏移；对应 VA 为偏移 + `0xffffff8000200000`。）

**注意第 2 类的识别方式是"没有特征行"。** 这是最难归因的一类，因为它和"内核在串口初始化之前就死了"看起来一样。区分办法：第 1 类到第 5 类都发生在 `_i386_init` 之后，所以**只要串口上出现过 `Darwin Kernel Version` 这一行，就说明串口通路本身是好的**，静默一定是内核死了而不是日志丢了。如果连那一行都没有，走 `71` 第 9.5 节的 early serial 补丁。

### 6.2 三类失败的判别矩阵

把 CPU 失败放回 `71` 第 9.6 节的六个标记里，得到一张不需要读日志全文的判别表。

| 串口上最后看到的内容 | CPU 不兼容 | 磁盘找不到 | board-id 不对 |
|---|---|---|---|
| 连 `OC:` 前缀的行都没有 | — | — | — |
| 有 `OC:` / `OCABC:`，但没有 `OCB:` 的卷列表 | 不是 | **是**（固件或 `ScanPolicy` 层面） | 不是 |
| 有 `OCB:` 的卷列表，但没有 `boot.efi` 的输出 | 不是 | **是**（卷能看到但引导项不对） | 不是 |
| 有 `boot.efi` 输出，**没有** `Darwin Kernel Version` | **可能是**（第 2 类，早期 MSR） | 不是 | 不是 |
| 有 `Darwin Kernel Version`，紧随 `Unsupported CPU @...cpuid.c:1183` | **确定是**（第 1 类） | 不是 | 不是 |
| 有 `Darwin Kernel Version`，紧随 `x86_validate_topology() ...` | **确定是**（第 3 类） | 不是 | 不是 |
| 有 `Darwin Kernel Version`，紧随 `tsc_init: EFI not supported!` | **确定是**（第 4 类） | 不是 | 不是 |
| 有 `Darwin Kernel Version`，之后立刻静默 | **可能是**（第 2 类） | 不是 | 不是 |
| 有大量驱动匹配行，**没有** `BSD root: diskXsY` | 不是 | **确定是**（`71` 9.6 的阶段 ③b） | 不是 |
| 有 `BSD root:`，之后停在安装器或登录前 | 不是 | 不是 | **可能是**（安装器拒绝机型） |
| 安装器直接报"此版本不能安装在这台电脑上" | 不是 | 不是 | **确定是**（`71` 第 4.1 节的 `PlatformSupport.plist`） |
| 有 `Non-monotonic time: ...` | **确定是**（第 5 类，仅 AMD） | 不是 | 不是 |

**关键的分界线是 `Darwin Kernel Version` 这一行。** 它之前的失败是引导与磁盘问题，它之后到 `BSD root:` 之间的失败几乎全是 CPU 问题，`BSD root:` 之后的失败才可能是 board-id 问题。这条分界线使得三类失败在**一条串口日志的最后十行里**就能区分开。

### 6.3 给 `Detector` 的正则

接在 `71` 第 9.6 节的六个标记之后，`80` 第 2.9 节的 `Detector` 新增七条 CPU 维度的正则。每条命中都要把时间戳与捕获组写进 `result.json`。

```text
cpu.gate.fail        ^panic\(.*\): Unsupported CPU @
cpu.cpufamily.zero   cpuid_set_cpufamily\(0x[0-9a-f]+\) returning 0x0\b
cpu.topology.fail    x86_validate_topology\(\) (\d+) threads but (\d+) registered from MADT
cpu.tsc.fail         tsc_init: EFI not supported!
cpu.tsc.nonmono      Non-monotonic time: (invoke|dispatch|last_dispatch) at
cpu.vmm.detect       VMM vendor (\S+) TSC frequency (\d+) KHz bus frequency (\d+) KHz
cpu.signature        ^\s*signature\s+:\s+(0x[0-9a-fA-F]{8})$
```

最后两条不是失败标记，是**事实采集标记**，需要 `-cpuid` boot-arg 才会出现：

- `cpu.vmm.detect` 直接给出第 2.7.4 节走路 A 还是路 B。两个频率任一为 0 就是路 A。`KNOWN`，格式串在 `_tsc_init` 内，VA 由 `"VMM vendor %s TSC frequency %u KHz bus frequency %u KHz\n"` 定位。
- `cpu.signature` 给出宿主真实的 CPUID(1) EAX，可以和第 5.1 节 Linux 侧采到的 `cpuid1_eax` 对账。**两者不一致就说明 `Cpuid1Data` 生效了**，这是验证伪装是否被应用的唯一直接手段。

**一条纪律：`cpu.cpufamily.zero` 比 `cpu.gate.fail` 更早出现，优先用它。** 它在 panic 之前，所以即使 panic 文本因为某种原因没出来（例如 `71` 第 9.4 节的 `SERIALMODE_SYNCDRAIN` 没设而尾部消息被丢），这一行仍然在。

### 6.4 `71` 第 10 节首启探针的 CPU 段补充

`71` 第 10.1 节探针脚本的 A 段已经采了 `machdep.cpu.brand_string`、`machdep.cpu.features`、`machdep.cpu.leaf7_features`、`machdep.cpu.extfeatures` 与 `kern.hv_vmm_present`。本文补三条，**补在 A 段末尾，不改其它段**：

```bash
# ========== A2. CPU 门的运行期确认（72 分册第 2 节）==========
{
  echo "### 内核看到的 CPUID 与 cpufamily（与 72 第 2.3 节的表对账）"
  run sysctl -n machdep.cpu.family machdep.cpu.model machdep.cpu.stepping
  run sysctl -n machdep.cpu.extfamily machdep.cpu.extmodel
  run sysctl -n machdep.cpu.signature
  run sysctl -n machdep.cpu.vendor
  run sysctl -n machdep.cpu.cpufamily    # 期望值见 72 第 2.3 节；0 不可能出现（否则已 panic）
  run sysctl -n machdep.cpu.cpusubfamily
  run sysctl -n machdep.cpu.microcode_version

  echo "### 拓扑（与 72 第 2.7.3 节 panic 的两侧对账）"
  run sysctl -n machdep.cpu.core_count machdep.cpu.thread_count
  run sysctl -n machdep.cpu.cores_per_package machdep.cpu.logical_per_package
  run sysctl -n hw.packages hw.physicalcpu hw.logicalcpu hw.physicalcpu_max hw.logicalcpu_max

  echo "### cpu_subtype：8 = x86_64h，4 = 退化。见 72 第 2.5 节"
  run sysctl -n hw.cputype hw.cpusubtype hw.cpu64bit_capable
  run sysctl -n hw.optional.avx2_0 hw.optional.avx1_0 hw.optional.fma
  run sysctl -n hw.optional.bmi1 hw.optional.bmi2 hw.optional.sse4_2
  run sysctl -n hw.optional.avx512f hw.optional.avx512dq hw.optional.avx512vl

  echo "### TSC / 总线频率：确认 72 第 2.7.4 节走的是路 A 还是路 B"
  run sysctl -n hw.tbfrequency hw.busfrequency hw.cpufrequency
  run sysctl -n machdep.tsc.frequency machdep.tsc.nanotime.generation
  run sysctl -n machdep.tsc.deep_idle_rebase machdep.tsc.at_boot

  echo "### XCPM 是否真的没起来（见 72 第 2.6.2 节；期望：全部不存在或为 0）"
  run sysctl -a machdep.xcpm
  run ioreg -r -c X86PlatformPlugin -d 1 -w 0
  run ioreg -r -c VMPlatformPlugin  -d 1 -w 0
  run ioreg -r -c IOPlatformPluginFamily -d 1 -w 0
} > "$OUT/A2-cpu.txt"
```

与 `71` 第 10.2 节同形的判定表：

| 命令 / 字段 | 关闭或推进的编号 | 判据 |
|---|---|---|
| `sysctl -n machdep.cpu.signature` | 本文 **C-001** | 与第 5.1 节 Linux 侧的 `cpuid1_eax` 比对。相同说明没有伪装生效；不同说明 `Cpuid1Data` 被应用 |
| `sysctl -n machdep.cpu.cpufamily` | 本文第 2.3 节的运行确认 | 必须是第 2.3 节表里的某个值。`0x37FC219F` 即 `SKYLAKE`，是 Intel 路线的期望值；`0x78EA4FBC` 即 `PENRYN`，是 AMD 路线伪装生效的证据 |
| `sysctl -n machdep.cpu.vendor` | 本文 **C-001** | `GenuineIntel` 或 `AuthenticAMD`。AMD 路线上这一项仍会报 `AuthenticAMD`（第 12 条补丁只 NOP 了比较，没改字符串） |
| `sysctl -n hw.cpusubtype` | 本文 **C-010** | `8` = `x86_64h`，`4` = 退化。退化时要查 `hw.optional.avx2_0` 等 |
| `machdep.cpu.core_count` / `thread_count` 与 `hw.packages` | 本文 **C-002**、第 4.3.1 节 | `thread_count × hw.packages` 必须等于 `hw.logicalcpu_max`，否则下次启动的拓扑校验就是定时炸弹 |
| `machdep.tsc.frequency` 与 `hw.busfrequency` | 本文 **C-003** | 与第 5.1 节 Linux 侧的 `hypervisor.tsc_khz` / `bus_khz` 比对。相等（换算后）说明走了路 B |
| `sysctl -a machdep.xcpm` | 本文第 2.6.2 节的运行确认 | **期望：没有任何输出，或全部为 0。** 有非零值说明第 2.6.2 节的 hypervisor 位判断没有生效，整节结论要重审 |
| `ioreg -r -c VMPlatformPlugin` | 本文 **C-015** | 有实例就说明 Apple 的 VM platform plugin 在 x86_64 上存在并匹配上了 |

---

## 7. F. Vultr 的实际 CPU

### 7.1 关键发现：CPU 厂商是可选的，不是抽卡

**`GET /v2/plans` 是一个无需鉴权的公开端点，而且每个 plan 都带 `cpu_vendor` 字段。** `KNOWN`，本轮直接请求取得（2026-10-30）：

```bash
curl -s "https://api.vultr.com/v2/plans?per_page=500" -o plans.json          # 无 Authorization 头
curl -s "https://api.vultr.com/v2/plans-metal?per_page=500" -o plans-metal.json
```

`plans.json` 返回 `meta.total = 139`，每条 plan 的字段集是：

```text
id  type  vcpu_count  ram  disk  disk_type  disk_count  bandwidth
monthly_cost  hourly_cost  monthly_cost_preemptible  hourly_cost_preemptible
invoice_type  locations  cpu_vendor  storage_type  vcpu_type
deploy_ondemand  deploy_preemptible  location_cost  gpu_brand
```

**这推翻了任务前提里"宿主 CPU 是抽卡"的一半。** 厂商不是抽卡，代次才是。

### 7.2 按产品线的厂商分布

`KNOWN`，本轮对 139 条 plan 按 `(type, cpu_vendor, vcpu_type, gpu_brand)` 聚合的结果（时效：2026-10-30 的 API 响应）：

| `type` | 产品线 | `cpu_vendor` | plan 数 | `vcpu_type` | 对本项目 |
|---|---|---|---:|---|---|
| `vc2` | Cloud Compute（Regular Performance，共享 CPU） | **Intel** | 12 | `thread` | **可用，厂商确定** |
| `vhf` | High Frequency | **Intel** | 10 | `thread` | **可用，厂商确定** |
| `vhp` | High Performance | **Intel** | 8 | `thread` | **可用**，plan id 以 `-intel` 结尾 |
| `vhp` | High Performance | AMD | 8 | `thread` | plan id 以 `-amd` 结尾 |
| `voc` | Optimized Cloud Compute | **AMD** | 51 | `thread` | **全是 AMD，没有 Intel 选项** |
| `vx1` | VX1 Cloud Compute | **AMD** | 36 | `thread` | **全是 AMD** |
| `vcg` | Cloud GPU | Intel | 3 | `thread` | 带 GPU，与本项目目标形态不符 |
| `vdm` | GPU 机型 | Intel / AMD / 空 | 11 | `thread` | 同上 |

**两条可直接用于规划的结论：**

1. **`vc2`、`vhf` 与 `vhp-*-intel` 三条线能把 CPU 厂商钉成 Intel。** 第 5.4 节建议"把 Intel 作为 L2 主路线"因此是可执行的，不是愿望。
2. **`voc` 与 `vx1` 没有 Intel 选项。** 这两条线是 Vultr 的"专用 vCPU"与新一代产品线，性价比更好（`80` 第 1.6 节关心成本）。要用它们就必须走 AMD 路线，即必须吃下第 5.4 节的全部风险。

**满足 `80` 第 1.6 节门槛（≥ 4 vCPU、≥ 8 GB）且无 GPU 的最便宜候选**（`KNOWN`，本轮 API 数据，价格为 2026-10-30 的 `monthly_cost`）：

| plan id | type | vCPU | RAM | 盘 | 厂商 | 月费 |
|---|---|---:|---:|---:|---|---:|
| `vc2-4c-8gb` | `vc2` | 4 | 8 GB | 160 GB | Intel | $40 |
| `vhp-4c-8gb-intel` | `vhp` | 4 | 8 GB | 180 GB | **Intel** | $48 |
| `vhp-4c-8gb-amd` | `vhp` | 4 | 8 GB | 180 GB | AMD | $48 |
| `vhf-4c-16gb` | `vhf` | 4 | 16 GB | 384 GB | Intel | $96 |
| `voc-c-4c-8gb-75s-amd` | `voc` | 4 | 8 GB | 75 GB | AMD | $80 |
| `vx1-g-4c-16g` | `vx1` | 4 | 16 GB | 网络盘 | AMD | $87.6 |

**E0-L2 的推荐机型是 `vc2-4c-8gb`。** 三个理由：厂商确定为 Intel、月费最低、`type = vc2` 与 `80` 第 1.6 节已经写好的 plan 查询（`?type=vc2`）一致。注意 `80` 第 1.6 节的查询条件 `vcpu_count>=4 and ram>=8192` 会把 `vc2-4c-8gb` 选出来，所以那段脚本不需要改。

### 7.3 代次仍然未知，这才是真正的抽卡

`BLOCKED`。`/v2/plans` 只给 `cpu_vendor`，**不给 CPU 型号或微架构**。所以：

| 产品线 | 厂商 | 代次 | 对第 2.3 节白名单的后果 |
|---|---|---|---|
| `vc2` / `vhf` / `vhp-intel` | Intel（确定） | **未知** | 若是 Skylake-SP / Cascade Lake-SP（model `0x55`）→ 原生通过；若是 Ice Lake-SP / Sapphire Rapids → 需要 `Cpuid1Data`（第 4.2 节） |
| `voc` / `vx1` / `vhp-amd` | AMD（确定） | **未知** | 若是 Zen 2/3/4（family 17h/19h）→ 在 AMD_Vanilla 声明范围内；若是 Zen 5（1Ah）→ 超出声明范围（第 3.5 节） |

社区与第三方评测给出的说法是 High Performance 跑在"较新一代的 AMD EPYC 或 Intel Xeon"上、High Frequency 针对 3 GHz 以上的 Xeon（转述自 <https://docs.vultr.com/products/compute/cloud-compute/provisioning> 与 <https://hostingengines.com/vultr-high-performance/>，`INFERRED`，这类描述不含具体型号，不能用于判定 CPUID model）。

**查清方法是第 5.1 节的脚本，成本是一小时实例费。** 登记为 C-001 与 C-002。**这一步必须在造 EFI 之前做**，否则 `Cpuid1Data` 与 AMD 变体的核心数常量都没有依据。

### 7.4 Bare Metal：型号是公开的

`KNOWN`，`GET /v2/plans-metal` 同样公开，而且**带 `cpu_model` 与 `cpu_manufacturer` 两个字段**。本轮取得 23 条，与本文相关的部分（时效 2026-10-30）：

| plan id | 厂商 | `cpu_model` | 微架构 | 第 2.3 节 model | 判定 | 月费 |
|---|---|---|---|---|---|---:|
| `vbm-6c-32gb` | Intel | `E-2286G` | Coffee Lake | `0x9E` | **原生通过** | $185 |
| `vbm-8c-132gb` | Intel | `E-2288G` | Coffee Lake | `0x9E` | **原生通过** | $350 |
| `vbm-4c-32gb` | Intel | `E3-1270` | Sandy/Ivy Bridge（按版本） | `0x2A` / `0x3A` | **原生通过** | $120 |
| `vbm-6c-128gb` | Intel | `E-2386G` | Rocket Lake | `0xA7` | **需要 `Cpuid1Data`** | $225 |
| `vbm-8c-132gb-v2` | Intel | `E-2388G` | Rocket Lake | `0xA7` | **需要 `Cpuid1Data`** | $350 |
| `vbm-48c-1024gb-4-a100-gpu` | Intel | `Gold 6342` | Ice Lake-SP | `0x6A` | 需要 `Cpuid1Data` | $7000 |
| `vbm-112c-2048gb-8-*-gpu` | Intel | `Platinum 8480+` | Sapphire Rapids | `0x8F` | 需要 `Cpuid1Data` | $15052+ |
| `vbm-24c-256gb-amd` | AMD | `EPYC 7443P` | Milan（Zen 3，19h） | — | AMD 路线，在声明范围内 | $725 |
| `vbm-128c-2048gb-amd` | AMD | `EPYC 7713` | Milan（Zen 3，19h） | — | 同上 | $5500 |
| `vbm-24c-384gb-amd` | AMD | `EPYC 9254` | Genoa（Zen 4，19h） | — | 同上 | $825 |
| `vbm-32c-755gb-amd` | AMD | `EPYC 9354P` | Genoa（Zen 4，19h） | — | 同上 | $1450 |
| `vbm-6c-32gb-amd` | AMD | `EPYC 4245P` | Raphael（Zen 4，19h） | — | 同上 | $295 |
| `vbm-24c-384gb-amd5` | AMD | `EPYC 9255` | **Turin（Zen 5，1Ah）** | — | **超出 AMD_Vanilla 声明范围** | $995 |
| `vbm-8c-64gb-amd` | AMD | `EPYC 4345P` | **Granite Ridge（Zen 5，1Ah）** | — | **超出声明范围** | $365 |

`KNOWN` 对于 `cpu_model` 字符串与价格；**`INFERRED` 对于微架构与 CPUID model 的映射**（由型号名推断，未查 Intel/AMD 的官方型号表逐条核对）。

**对本项目的两条用处：**

1. **`vbm-6c-32gb`（Xeon E-2286G，Coffee Lake）是整个 Vultr 产品目录里唯一一个"CPU 型号公开、且与某个受支持 Mac 机型同微架构"的选项。** 它的 model `0x9E` 与 `MacBookPro16,1` 完全相同。代价是 $185/月、最小计费单位仍是小时，而且 bare metal 的设备模型是真硬件而不是 KVM（即 `00-OVERVIEW` 第 2.1 节"作为云平台自己的 KVM guest"这个前提不成立）。**所以它不是目标形态，但它是"CPU 侧绝对不会是瓶颈"的对照实验机型。** `INFERRED` 的价值评估。
2. **Zen 5 已经进入 Vultr 的 bare metal 目录。** 云侧的 `voc` / `vx1` 迟早会跟上，这让第 3.5 节的 Zen 5 问题从"理论"变成"排期问题"。登记为 C-008。

### 7.5 抽卡的概率分布

把前四节合起来：

| 决策 | 我们能不能控制 | 控制方式 |
|---|---|---|
| CPU 厂商（Intel / AMD） | **能** | 选 `vc2` / `vhf` / `vhp-*-intel` → Intel；选 `voc` / `vx1` / `vhp-*-amd` → AMD |
| CPU 微架构代次 | **不能** | 只能先起一台实例探测（第 5.1 节） |
| 同一 plan 内不同机房的代次是否一致 | **不知道** | `locations` 字段列出每个 plan 可用的机房，但不保证同型号。登记为 C-016 |
| vCPU 拓扑（socket / core / thread） | **不能** | `vcpu_type = thread` 说明卖的是线程。拓扑由 hypervisor 合成 |
| CPUID 伪装 | **能**，但只能在 OpenCore 侧 | `Kernel/Emulate/Cpuid1Data`（第 4.2 节） |
| 宿主的 `kvm ignore_msrs` | **不能** | 只能探测后果（第 5.1 节的 `msr_probe`） |

**所以"抽卡"的准确说法是：厂商可选，代次抽卡，而代次抽卡的后果已经被第 4.2 节的 `Cpuid1Data` 兜住了（Intel 侧）或被第 3 节的补丁集兜住了（AMD 侧）。** 真正没有兜底的只有两件：第 4.3.1 节的拓扑，与第 4.5 节的 `MSR 0x198`/`0x199`。这两件都要靠第 5.1 节的 Linux 侧探测提前知道。

---

## 8. 未解决项清单

编号 `C-` 代表 CPU。与 `70` 的 `P-`、`71` 的 `I-`、`80` 的 `H-` 并列，互不重叠。

"成本"一列区分四类：**现在就能做**（只需读现有样本或跑一条本地命令）、**L0-probe**（起一台最小 Vultr 实例装 Linux 跑第 5.1 节的脚本，约一小时实例费）、**E0-L1**（本地起一次 macOS 虚机）、**E0-L2**（Vultr 上起 macOS 实例）。

| 编号 | 事项 | 标签 | 查清方法 | 成本 | 阻塞什么 |
|---|---|---|---|---|---|
| **C-001** | Vultr `vc2` / `vhf` / `vhp-*-intel` 的宿主 CPU 真实 CPUID(1) EAX、family、model、stepping | `BLOCKED` | 第 5.1 节脚本，读 `cpuid1_eax` / `model_hex` / `natively_supported`。同一 plan 在多个机房各起一台以覆盖 C-016 | **L0-probe** | **整条 Intel 路线。** 决定 `Cpuid1Data` 填不填、填什么（第 4.2.2 节） |
| **C-002** | Vultr `voc` / `vx1` / `vhp-*-amd` 的 EPYC 代次与 family；以及 guest 内可见的 socket/core/thread 拓扑 | `BLOCKED` | 第 5.1 节脚本，读 `family`、`topology.*`、`recommend.cores_per_package_byte` | **L0-probe** | AMD 变体的 `cpuid_cores_per_package` 常量（第 3.4 节）与 Zen 5 判定（C-008） |
| **C-003** | 云平台是否暴露 CPUID leaf `0x40000010`；若否，OpenCore 的 DataHub `FSBFrequency` / `ARTFrequency` 能否被 `_tsc_init` 的路 A 读到 | `BLOCKED` | 前半：第 5.1 节脚本的 `hypervisor.leaf_40000010_present`。后半：E0 时看串口的 `VMM vendor ... TSC frequency ... bus frequency ...` 一行，再查 `sysctl -n machdep.tsc.frequency hw.busfrequency`（第 6.4 节） | 前半 **L0-probe**，后半 E0-L1/L2 | 第 2.7.4 节。路 A 下的除零与 `tsc_init: EFI not supported!` panic |
| **C-004** | 宿主是否设置 `kvm ignore_msrs=1`；`MSR 0x198`、`0x199`、`0xCE`、`0x194`、`0x35` 在 guest 内的实际行为 | `BLOCKED` | 第 5.1 节脚本的 `msr_probe` 段。`served: false` 即该 MSR 会 `#GP` | **L0-probe** | **Intel 路线第二大风险（第 4.5 节）。** `0x198`/`0x199` 任一不被服务，`_i386_init` 会在早期静默死掉 |
| **C-005** | 把 `cpuid_cpufamily` 伪装成 `CPUFAMILY_INTEL_PENRYN`（AMD_Vanilla 第 14 条）之后，Metal.framework 与 `AppleParavirtGPUMetal.bundle` 是否按 cpufamily 分支 | `BLOCKED` | 在仓库已有的 `metal-bundle/AppleParavirtGPUMetal.x86_64`（`LC_UUID` `15DB02D8-D7E6-30A1-979C-DFD657E47F19`）里检索对 `cpuid_cpufamily` / `sysctlbyname("machdep.cpu.cpufamily")` / `CPUFAMILY_` 常量的引用；对 dyld shared cache 内的 `Metal` 做同样检索 | **现在就能做**（前半） | **AMD 路线对本项目的特有风险（第 3.7 节）。** 这是"启动成功但 Metal 行为不同"这一类问题，比启动失败难查得多 |
| **C-006** | OpenCore 的 `ProvideCurrentCpuInfo` 在 Darwin 25 上是否仍能正确定位它要打的图样 | `INFERRED` | 按第 1.2 节第 3 条的方法，把 OpenCorePkg 源码 `Library/OcAppleKernelLib/CpuInfoPatches.c` 里的图样对 `kernel.x86_64` 跑一遍匹配；或启用该 quirk 后在 OpenCore 的 DEBUG 串口日志里看补丁应用结果 | **现在就能做** | **第 4.4 节唯一必须开的 quirk。** 它同时是 AMD_Vanilla 的硬依赖（README 明确不开则不启动） |
| **C-007** | AMD_Vanilla PR #215 的合入状态；以及 master 第 14 条 `Base = "_cpuid_set_info "` 末尾空格是否影响 OpenCore 的符号解析 | `BLOCKED`（前半）/ `INFERRED`（后半） | 前半：定期查 <https://github.com/AMD-OSX/AMD_Vanilla/pull/215>。后半：读 OpenCorePkg 的 `OcAppleKernelLib` 对 `Base` 字符串的处理，看有没有 trim；或直接在构建脚本里 `.strip()`（第 5.2.3 节脚本已这么做） | **现在就能做** | AMD 变体是否能直接引用上游。结论若为"不能"，就按第 5.2.3 节 fork 并自带门禁 |
| **C-008** | Zen 5（family `0x1A`）是否被 AMD_Vanilla 的补丁集覆盖 | `INFERRED` | README 声明的范围是 15h/16h/17h/19h。实际需要逐条判断哪些补丁与 family 相关（第 3.5 节分析了第 5 条与 PAT 两处）。确证需要一台 Zen 5 宿主，Vultr 侧目前只有 bare metal（`vbm-24c-384gb-amd5`、`vbm-8c-64gb-amd`） | E0-L2 或 bare metal | 若 Vultr 的 `voc` / `vx1` 换代到 Turin，AMD 路线的可用性要重评 |
| **C-009** | `-nomsr35h` boot-arg 把 core/thread 定成 1/1 之后，第 2.7.3 节的 `x86_validate_topology` 是否仍通过；SMP 是否正常 | `INFERRED` | 反编译 `_x86_set_logical_topology` @ `0xffffff80003d7560`，确认 `nLThreadsPerPackage` 的来源是不是 `core_thread_count`。然后在 L1 上加这个 boot-arg 启一次，查 `hw.logicalcpu` 与 `machdep.cpu.thread_count` | **现在就能做**（反编译部分） | 若成立，它是 `ProvideCurrentCpuInfo` 的**原生替代品**，不需要打任何补丁，适用于两条路线。这是本清单里性价比最高的一项 |
| **C-010** | 25G325 是否同时提供 `x86_64` 与 `x86_64h` 两套 dyld shared cache；`cpu_subtype` 退回 4 时 `libMTLIGCCompilerPlugin.dylib`（`x86_64h` 单一架构）如何加载 | `INFERRED` | 在 `payloadv2-full-index.tsv.zip` 里检索 `dyld_shared_cache_x86_64` 与 `dyld_shared_cache_x86_64h` 两个路径；用 `tools/extract_one.py` 取其 header 核对 | **现在就能做** | 第 2.5 节下限 2。影响 `32-COMPILER-PLUGIN.md` 的 compiler plugin 能否加载 |
| **C-011** | `-cpuid` boot-arg 的 kprintf 输出在串口上能否被看到（即 `cpuid_set_info` 发生在串口可用之后） | `INFERRED` | E0-L1 时加上 `-cpuid`，看串口上有没有 `cpuid_fn(0x00000000) eax:...` 一行。看不到就走 `71` 第 9.5 节的 early serial 补丁 | E0-L1，零额外成本 | 第 2.9 节与第 6.3 节的两条事实采集正则。它们是"宿主给了什么 CPU"的唯一运行期答案 |
| **C-012** | `_i386_lbr_init` 与 `_cpuid_wa_required` 在虚机里的行为：`lbr_mode` 不设时是否真的完全跳过；`cpuid_wa_required(3)` 返回 2 时写 `MSR 0x122` 会不会 `#GP` | `INFERRED` | 反编译 `_cpuid_wa_required` @ `0xffffff80003d5750`，读出它对 `MSR 0x10A`（`IA32_ARCH_CAPABILITIES`）的判断条件；再比对第 5.1 节 `msr_probe` 里 `0x10A` 的实际值 | **现在就能做** | 第 2.7.1 节。默认配置下判定为不威胁，但这个判定要有依据 |
| **C-013** | `kext/com.apple.iokit.IOPCIFamily` 重建件里 `probeBusGated` 补丁命中处（文件偏移 `0xF9C5`）对应的 VA 与所属函数 | `INFERRED` | 按 `MANIFEST.md` 第 8 节重跑 `tools/kc.py` 并记录 `__TEXT` 的实际 fileoff，或把该件导入 IDA 后查 `__ZN11IOPCIBridge13probeBusGatedEP14probeBusParams` | **现在就能做** | 第 3.3.2 节。只影响证据完整性，不影响结论（该补丁判定为本项目不需要） |
| **C-014** | 本项目的运行组件（Vulkan loader、Mesa Lavapipe、LLVM、metal2vulkan）是否间接依赖 Intel MKL / OneAPI | `INFERRED` | `70` 第 3 节构建完成后对产物跑 `otool -L` 与符号检索，查 `mkl`、`libiomp`、`svml` | 归 `70` 分册 | 第 3.7 节。AMD 路线上 MKL 依赖会导致崩溃 |
| **C-015** | `VMPlatformPlugin.kext` 是否有 x86_64 可执行码；它的 personality 匹配条件；`X86PlatformPlugin` 与它在 guest 内谁被实例化 | `BLOCKED` | 用 `71` 第 4.1 节的方法抽 `System/Library/Extensions/IOPlatformPluginFamily.kext/Contents/PlugIns/VMPlatformPlugin.kext/Contents/Info.plist`；再按 `71` 第 3.1 节重建两个 KC 并在 fileset 条目里检索 `VMPlatformPlugin` | **现在就能做** | 第 4.3.3 节。若 Apple 为虚机准备了专用 plugin，第 2.6.2 节"guest 里没有电源管理"的结论要修正 |
| **C-016** | 同一 Vultr plan 在不同机房（`locations` 字段）的宿主 CPU 代次是否一致 | `BLOCKED` | 对选定 plan 在 3 到 4 个机房各起一台最小实例跑第 5.1 节脚本，比对 `cpuid1_eax` | **L0-probe** ×N | 若不一致，`Cpuid1Data` 不能在镜像里写死，必须按机房出变体，或统一填第 4.2.1 节取值 B |

**优先级，按"先做什么"排序：**

1. **C-009、C-006、C-005、C-010、C-015、C-012、C-013 现在就能做完，不需要任何实验。** 其中 C-009 与 C-006 直接决定第 4.4 节那张 quirk 表对不对，应当在写任何构建脚本之前做掉。
2. **C-001、C-002、C-003、C-004、C-016 构成一次 L0-probe，一台最小实例、一小时、一个脚本就能全部采完。** 这一步应当排在 `80` 第 4.1 节 E0-L2 之前，甚至可以排在 E0-L1 之前，因为它决定造哪一份 EFI。
3. C-007、C-008、C-014 是跟踪项，不阻塞当前工作。

**一条额外建议：把 L0-probe 作为 `80` 第 4.1 节的新增前置实验。** `80` 现在的顺序是 E0-L1 → E0-L2。本文的材料说明中间应该插一步：**E0-L0（在 Vultr 上起一台 Linux，采完 CPU 事实，不装 macOS）**。它的验收是产出一份通过 schema 校验的 `host-cpu.json`，成本比 E0-L2 低一个量级，而它的输出是 E0-L2 镜像的必要输入。

---

## 9. 相关分册

- **`71-IMAGE-OPENCORE.md`**：本文是它第 5 节的 L2 侧对应物。**本文修正它三处**：(1) 第 5.3 节"`Cpuid1Data` / `Cpuid1Mask` 永远留空"只适用于能写 `-cpu` 的 L1，L2 上它是替代 `-cpu` 的唯一手段（本文 4.2 节）；(2) 第 5.3 节的 `DummyPowerManagement = true` 在 25G325 上是空操作，因为 `AppleIntelCPUPowerManagement.kext` 不存在（本文 2.6.1 节）；(3) 第 6.5.3 节三个 `AppleXcpm*` quirk 保持 `false` 的理由应从"真机相关"升级为"XCPM 在 guest 里不初始化"（本文 2.6.2 节）。**本文同时关闭它的 I-015**（四个 early serial 符号在 25G325 中全部存在，本文 1.2 节）。本文第 6.4 节的 A2 段追加进它第 10.1 节的探针脚本；第 6.3 节的七条正则接在它第 9.6 节六个标记之后；第 5.2.3 节的 `make-oc-config.py` 扩展基于它第 6.1 节的脚本。
- **`70-BUILD-PACKAGE.md`**：本文第 2.9 节建议在它第 5.5 节的 boot-args 清单里加 `-cpuid`。本文不改它的 SIP 方案。
- **`80-TEST-HARNESS.md`**：本文第 7 节用公开的 `/v2/plans` 数据补全了它第 1.6 节的机型调研，新增 `cpu_vendor` 这一维度；它第 1.6 节的 plan 查询脚本不需要改。本文第 8 节建议在它第 4.1 节的 E0 之前插入 E0-L0。本文第 6.3 节的正则扩展它第 2.9 节的 `Detector`。
- **`20-OBJC-DEVICE.md`、`21-OBJC-OBJECT-FAMILY.md`、`32-COMPILER-PLUGIN.md`**：本文 C-005（cpufamily 伪装对 Metal 栈的影响）与 C-010（`x86_64h` 与 compiler plugin）是它们的输入。C-005 的检索对象 `AppleParavirtGPUMetal.x86_64` 正是 `00-OVERVIEW` 第 4.1 节指定的 ObjC 侧首选参考实现。
- **`90-EVIDENCE-INDEX.md`**：本文新取得的证据应登记进它的样本索引。全部来自 `kernel/kernel.x86_64`（`LC_UUID` `E514CEBA-9206-34D5-86C2-64E880FDDA2B`）与 `kext/com.apple.iokit.IOPCIFamily`（`LC_UUID` `81D9CF0C-0587-3EC8-B878-E0042113108B`），没有新增样本文件。新增的派生结论包括：第 2.3 节的 30 个 model → 11 个 CPUFAMILY 映射表、第 2.5 节的三个 `x86_64h` 特性掩码、第 2.6.2 节的 XCPM hypervisor 门、第 2.8 节的 MSR 访问点表、第 3.2 节的 25 条补丁匹配结果。
- **`00-OVERVIEW.md` 第 7 节**：本文的标签用法遵从它的四级规则。特别是第 2 节与第 3 节的全部结论都建立在 **x86_64 内核二进制**上，不建立在社区说法或 arm64 证据上，这是它"标注证据的架构"与"没查不等于被阻断"两条规则在本场景下的落地方式。
