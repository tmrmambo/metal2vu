# MANIFEST - `10-KERNEL-ACCELERATOR.md` 本轮产物

生成日期：2026-10-30
产出任务：`docs/spec/10-KERNEL-ACCELERATOR.md`（accelerator 侧实现契约）
架构：`x86_64`　构建：macOS Tahoe 26.7.2 / 25G325　层级：T2（KC 重建件）

本文只登记**本轮新增**的文件（`idb/` 与 `tools/` 两个子目录）。
本目录根下的 `*-kc-rebuild.i64` 与 `kernel-low30-symmap.json` 来自另一轮工作，
本轮未读取、未改写。

## 1. 为什么需要"段偏移修复"

`analysis/binaries/macos26-25G325-x86_64/tools/kc.py` 从
`SystemKernelExtensions.kc` 的 `LC_FILESET_ENTRY` 重建独立 Mach-O 时，
重写了每个 **section** 的 `offset`，但 `LC_SEGMENT_64` 的 `fileoff` / `filesize`
仍保留 KC 内的值（例如 `AppleParavirtGPU` 的 `__TEXT.fileoff = 0x14898000`）。

IDA 的 Mach-O 装载器按**段级** `fileoff` 读取字节，于是它会建出正确的段和地址、
正确应用符号表（2,114–4,707 个名字），但**不装载任何字节**：

- `len(list(idautils.Functions())) == 0`
- `ida_bytes.is_loaded(ea) == False`，`get_bytes()` 返回全 `0xFF`
- Hex-Rays 报 `Failed to decompile function at …`

这很容易被误判成"样本损坏"。`tools/fixseg.py` 按各 section 的真实 `offset`
反算并回写段的 `fileoff` / `filesize`，修复后：

| 件 | 修复前函数数 | 修复后函数数 |
|---|---:|---:|
| `AppleParavirtGPU` | 0 | 844 |
| `IOAcceleratorFamily2` | 0 | 3,028 |
| `IOGraphicsFamily` | 0 | 1,147 |

修复**不触碰**段 `vmaddr`、section `addr` / `offset`、`LC_SYMTAB`、`LC_UUID`，
因此 RVA 与符号全部与仓库原件一致，本轮文档里的地址对原件同样成立。
`__LINKEDIT` 段不修（没有 file-backed section 可反算），符号读取不受影响。

## 2. 修复件（中间产物，未入库）

这三件只存在于 `$env:TEMP\kvmmacos-apv-x86\`，可用 `fixseg.py` 确定性重建。

| 名字 | 源（仓库内原件） | 字节 | SHA-256 |
|---|---|---:|---|
| `APV-fixed` | `analysis/binaries/macos26-25G325-x86_64/kext/com.apple.driver.AppleParavirtGPU` | 13,133,432 | `97DBA3E3BEED20B6796ACF3A8731B204C5844996C004D78DE5BCDFD39D81B5EE` |
| `IOAF2-fixed` | `…/kext/com.apple.iokit.IOAcceleratorFamily2` | 13,526,648 | `2A2264DAA95D1A1DAB74AFEC82A08E3E5ED7599F326BC8297CE122F7735F09A8` |
| `IOGFX-fixed` | `…/kext/com.apple.iokit.IOGraphicsFamily` | 13,248,120 | `7C47C02656C55B9EB5568D498A151CC82BB54A21E7446D74E419796DD5EA8D6F` |

重建命令：

```powershell
py tools\fixseg.py <原件路径> <修复件路径>
```

段偏移修复结果（供校验）：

```
AppleParavirtGPU
  __TEXT        vmaddr 0x14898000 vmsize 0x18000 -> fileoff 0x04000 filesize 0x17b97
  __DATA        vmaddr 0x148b0000 vmsize 0x0a000 -> fileoff 0x1c000 filesize 0x09080
  __DATA_CONST  vmaddr 0x148ba000 vmsize 0x01000 -> fileoff 0x28000 filesize 0x00c30
IOAcceleratorFamily2
  __TEXT        vmaddr 0x14b65000 vmsize 0x6a000 -> fileoff 0x04000 filesize 0x6978c
  __DATA        vmaddr 0x14bcf000 vmsize 0x18000 -> fileoff 0x70000 filesize 0x16ec8
  __DATA_CONST  vmaddr 0x14be7000 vmsize 0x03000 -> fileoff 0x88000 filesize 0x025c0
IOGraphicsFamily
  __TEXT        vmaddr 0x14ce4000 vmsize 0x2f000 -> fileoff 0x04000 filesize 0x2e24a
  __DATA        vmaddr 0x14d13000 vmsize 0x11000 -> fileoff 0x34000 filesize 0x0f9c0
  __DATA_CONST  vmaddr 0x14d24000 vmsize 0x02000 -> fileoff 0x44000 filesize 0x01e50
```

## 3. IDB

IDA Professional 9.5，headless（`idat`）。每个库在分析中做过：
对 `__text` 段内全部符号地址 `add_func`，并对 Hex-Rays 失败处手工
`create_insn` + `reanalyze_function`（Mach-O 重建件缺 `LC_DYSYMTAB`，
IDA 的自动分析会在若干跨 collection 调用处断掉）。库内留有这些修正。

| 文件 | 对应修复件 | 源件 `LC_UUID` | `__TEXT` vmaddr（= RVA 基址） | 字节 | SHA-256 |
|---|---|---|---|---:|---|
| `idb/AppleParavirtGPU-x86_64-segfixed.i64` | `APV-fixed` | `B88E1D48-71A2-3DC0-8D87-605DDB039B83` | `0x14898000` | 2,788,058 | `6B7DD2C5FF683282C6050B1FF3118935F540534D075310481C76C519B520427A` |
| `idb/IOAcceleratorFamily2-x86_64-segfixed.i64` | `IOAF2-fixed` | `6C4A16B1-66DC-3A8B-9F0B-D3E027B16EB1` | `0x14B65000` | 8,769,796 | `AE11E531AC56097E70763F3AA0708E4A22AA7AC99FF9BC8E56E342AA8516029A` |
| `idb/IOGraphicsFamily-x86_64-segfixed.i64` | `IOGFX-fixed` | `74AA6483-8AB4-3A94-8143-5E306C16D7DA` | `0x14CE4000` | 4,630,623 | `874452DE17432B672E39587D907753043EA1A86A1A50F6DA0EF588A7EB0E597F` |

**IDA 里的 `input file` 名是 `APV-fixed` / `IOAF2-fixed` / `IOGFX-fixed`**，
不是仓库原件名。这是有意的，用来提醒"这不是原件"。

每个库的关键标注（本轮文档引用的入口）：

| 库 | 关键 RVA |
|---|---|
| APV | `0xF64` `setupMMIO`、`0x102E` `GPUControl::start`、`0x121A..0x16F1` AGDC attribute 处理（含 accelerator 创建与 `AcceleratorProperties` 提升，`0x15BB` 起）、`0x1EDE` `Accelerator::start`、`0x28F4` `populateAccelConfig`、`0x2F38` `configureDevice`、`0x1A040` `__ZTV24AppleParavirtAccelerator` |
| IOAF2 | `0x3A36A` `initializeConfigStructure`、`0x3A4BC` `validateConfigStructure`（无调用点）、`0x3A752` `IOGraphicsAccelerator2::start`、`0x3DEAE` `newUserClient`、`0xCC5A` `IOAccelDevice2::start`、`0xD080` `get_config`、`0xD1DC` `get_event_machine`、`0xD52C` `get_device_info`、`0xD66A` `deviceStart`、`0xD894` `externalMethod`、`0xD9F2` `getTargetAndMethodForIndex`、`0x6FBB0` `sDeviceMethods`、`0x77CB0` `sSharedMethods`、`0x7C770` `sCommandQueueMethods`、`0x2D032` `setup_dirty_ring`、`0x2A51C` `getDirtyRingAddresses`、`0x7B8E0` `__ZTV22IOGraphicsAccelerator2` |
| IOGFX | `0x25558` `IOAccelerator::createAccelID`、`0x2556C` `retainAccelID`、`0x25610` `releaseAccelID`、`0x39440` `__ZTV13IOAccelerator` |

## 4. 工具

| 文件 | 作用 |
|---|---|
| `tools/fixseg.py` | 段 `fileoff` / `filesize` 修复（§1）。`py fixseg.py <in> <out>` |
| `tools/kcsyms.py` | 把 `analysis/binaries/macos26-25G325-x86_64/kext/*` 与 `kernel/kernel.x86_64` 的 `LC_SYMTAB` 合并成 `{VA: 名字}` JSON（37,367 条），供 IDAPython 内跨件解析 |
| `tools/kcread.py` | 离线读取器：KC VA → (件, 文件偏移)；解码 `DYLD_CHAINED_PTR_64_KERNEL_CACHE`；`vt2(classVTableSymbol)` 按 **vptr 偏移**导出 vtable；`learn_deltas()` 经验学习 cacheLevel-0 的分段偏移 |

### 4.1 chained fixup 解码规则（本轮确定）

```
target     = raw & 0x3FFFFFFF        // bits 0..29
cacheLevel = (raw >> 30) & 3         // 0 = boot 侧, 1 = SystemKernelExtensions.kc
next       = (raw >> 51) & 0xFFF
```

- cacheLevel **1**：`target` 直接就是 System KC 的 VA，可用本目录各件的
  `__TEXT` vmaddr 定位，跨件符号解析 100% 可靠。
- cacheLevel **0**：collection 按段类别重排，**每个 (件, 段) 有各自偏移**。
  本轮实测确定的三个：

  | 目标 | 偏移 | 实证 |
  |---|---|---|
  | `kernel.x86_64` `__TEXT` | `+0xFFFFFF8000018000` | `0x91DF10` → `__ZNK8OSObject7releaseEi`，其后 4 槽间距全吻合 |
  | `kernel.x86_64` `__DATA_CONST` | `+0xFFFFFF8000DCA000` | `0x1ADD40`/`0x1ADD58`/`0x1ADD68`/`0x176E58` → `OSNumber`/`IOService`/`OSData`/`IORegistryEntry` 的 `metaClass`，四点同偏移 |
  | `IOPCIFamily` `__DATA_CONST` | `+0xFFFFFF8000100000` | `0x2940C50` → `__ZN11IOPCIDevice9metaClassE` |

### 4.2 已知限制

跨 collection 的**直接 `call`** 解析不出来：System KC 调 kernel / Boot KC 的函数
走 System KC 自己 `0x10000`–`0x11000` 的 stub 页，反汇编里表现为
`call near ptr 1019Eh` 之类。该页不属于任何 `LC_FILESET_ENTRY`，重建件里没有。
**要解析它必须拿到 `SystemKernelExtensions.kc` 本体**（369,213,440 bytes，
SHA-256 `5EDE2BA5627482282E8964B00B6E17A0F7115F07D799E618DB806FBC60D94421`，
不在仓库内）。

受影响的只有 libkern / IOKit KPI 调用（`IOLockLock`、`PE_parse_boot_argn`、
`os_log_internal`、`OSMetaClassBase::safeMetaCast`、`IOMallocType` 等）；
家族内部的调用、虚函数表与 `__DATA` 指针全部可解。常见 stub 的经验对照（按
参数形状与日志字符串推断，`INFERRED`）：

| stub | 推断 |
|---|---|
| `0x1007E` | `OSMetaClassBase::safeMetaCast` |
| `0x100A2` | `OSString::withCString` |
| `0x100B4` | `bzero` / `memset` 清零包装 |
| `0x1000C` / `0x10012` / `0x10018` | `IORecursiveLockAlloc` / `Lock` / `Unlock` |
| `0x10132` / `0x1012C` | `IOLockLock` / `IOLockUnlock` |
| `0x1019E` | `PE_parse_boot_argn` |
| `0x101D4` | `memcpy` / `strlcpy` 包装 |
| `0x1024C` | `IOMemoryDescriptor::createMappingInTask` |
| `0x1030C` | `os_log_internal` |
| `0x104BC` | `IOServiceMatching` |
| `0x10690` / `0x10792` | `IOService::waitForService` 系 |
| `0x10B0A` / `0x10B40` | `get_bsdtask_info` / `proc_pid` |

## 5. 覆盖范围声明

本轮**没有**打开、读取或改写：

- `analysis/idb/macos26-25G325-arm64/` 下任何文件
- `analysis/idb/macos26-25G325-x86_64-frameworks/` 下任何 `.i64`
- `analysis/idb/metal_drivers/` 下任何文件
- 本目录根下的 `*-kc-rebuild.i64`、`kernel-low30-symmap.json`

本轮**没有**使用任何 arm64 样本做 x86 实现决策（`00-OVERVIEW.md` §7 规则 2）。
`IOSurface` 与 `IOPCIFamily` 只用于符号解析，没有对它们建库。
