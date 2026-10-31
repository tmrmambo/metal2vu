# 10 - 内核侧 accelerator service 实现契约

文档版本：1.0
基线：macOS Tahoe 26.7.2 / build 25G325 / **x86_64**
锚文档：`00-OVERVIEW.md`（证据规则见其第 7 节）
职责（见 `00-OVERVIEW.md` 第 8 节）：x86_64 25G325 上 `IOServiceMatching("IOAccelerator")` + type-5 背后是哪个内核家族；本项目 kext 必须发布什么、实现哪些 selector

读者目标：读完本文应能写出一个 kext，让 `MTLCopyAllDevices()` 在 guest 内看到一台设备。

## 0. 样本、地址与标签约定

### 0.1 样本标签

全部为 `x86_64` / cpusubtype 3。T2 = 从 25G325 installed SystemOS 的
`x86_64` kernel collection 重建的独立 Mach-O，T1 = 原生独立 Mach-O。
来源与哈希见 `90-EVIDENCE-INDEX.md` §2.1 / §2.2。

| 标签 | 件 | 层级 | `LC_UUID` | RVA 基址（= `__TEXT` `vmaddr`） |
|---|---|---|---|---|
| `S-APV` | `AppleParavirtGPU` | T2 | `B88E1D48-71A2-3DC0-8D87-605DDB039B83` | `0x14898000` |
| `S-IOAF2` | `IOAcceleratorFamily2` | T2 | `6C4A16B1-66DC-3A8B-9F0B-D3E027B16EB1` | `0x14B65000` |
| `S-IOGFX` | `IOGraphicsFamily` | T2 | `74AA6483-8AB4-3A94-8143-5E306C16D7DA` | `0x14CE4000` |
| `S-AGDC` | `AppleGraphicsDeviceControl` | T2 | `02FECF8A-3227-3BBB-B0EB-1DB31965ADB9` | `0x13D3F000` |
| `S-IOPCI` | `IOPCIFamily` | T2 | `81D9CF0C-0587-3EC8-B878-E0042113108B` | `0xFFFFFF80029E9000` |
| `S-KRNL` | `kernel` | T1 | `E514CEBA-9206-34D5-86C2-64E880FDDA2B` | `0xFFFFFF8000200000` |

用户态侧引用（T3 BaseSystem，见 `90-EVIDENCE-INDEX.md` §2.4，仅用于与
`20-OBJC-DEVICE.md` 核对）：

| 标签 | 件 | `LC_UUID` |
|---|---|---|
| `S-IOACCEL` | `IOAccelerator.framework` | `4FDBB3F6-9AA3-352B-87ED-57161AA64D1F` |
| `S-METAL` | `Metal.framework` | `FDB3FD2C-840A-3FC3-81FB-C524F891F642` |

**地址写法**：`S-XXX +0xRVA`，RVA = VA − 该件 `__TEXT` 段 `vmaddr`。该基址与
KC 内的 `vmaddr` 一致（`90-EVIDENCE-INDEX.md` §2.1 的 "KC 内 fileoff / vmaddr" 列）。

### 0.2 vtable 槽位写法

本文对 C++ 虚函数同时给两种坐标，因为反汇编里看到的是前者：

- **vptr 偏移**：`call qword ptr [rax+0x5C0]` 中的 `0x5C0`，即对象 `vptr` 起算的字节偏移。
- **槽号 i**：`i = vptr偏移 / 8`。符号 `__ZTV<Class>` 指向 vtable 结构头，
  槽 i 的存储地址是 `__ZTV<Class> + 0x10 + 8*i`（Itanium ABI：头两个 qword 是
  offset-to-top 与 typeinfo）。

**陷阱**：KC 优化过的 "super call" 形如
`mov rax, cs:<got槽>; call qword ptr [rax+0x5D0]`，此时 `rax` 是 **vtable 符号地址**
而不是 vptr，所以 `0x5D0` 要减 `0x10` 再除 8 才是槽号（= i 184）。本文已统一换算，
不会混用。

### 0.3 本轮的方法学（复现必读）

三件事必须先做对，否则读不出任何东西。

**(1) KC 重建件的段文件偏移是坏的，必须先修。** `KNOWN`

`analysis/binaries/macos26-25G325-x86_64/tools/kc.py` 重写了 section 的
`offset`，但 `LC_SEGMENT_64` 的 `fileoff` / `filesize` 仍是 KC 内的值
（例如 `S-APV` 的 `__TEXT.fileoff = 0x14898000`）。IDA 的 Mach-O 装载器用的是
段级 `fileoff`，于是它**建出了段但没装载任何字节**：`nfuncs == 0`，
`ida_bytes.is_loaded()` 全 False，但符号表照样生效（2,205 个名字），很容易误判成
"样本坏了"。

修法：按各 section 的真实 `offset` 反算段的 `fileoff` / `filesize` 并回写。
脚本见本轮新增的 `analysis/idb/macos26-25G325-x86_64/tools/fixseg.py`。修复后
`S-APV` 得到 844 个函数、`S-IOAF2` 3,028 个，Hex-Rays 正常工作。

**(2) `__DATA` 指针是 collection 级 chained fixup，解码规则已确定。** `KNOWN`

格式是 `DYLD_CHAINED_PTR_64_KERNEL_CACHE`：

```
target    = raw & 0x3FFFFFFF      // bits 0..29
cacheLevel= (raw >> 30) & 3       // 0 = boot 侧（kernel / BootKernelExtensions.kc）
                                  // 1 = 本 collection（SystemKernelExtensions.kc）
next      = (raw >> 51) & 0xFFF
```

验证：`S-APV +0x1A040`（`__ZTV24AppleParavirtAccelerator`）槽 0 的 raw 是
`0x0040000054899D86`，`& 0x3FFFFFFF = 0x14899D86`，正好是
`__ZN24AppleParavirtAcceleratorD1Ev`（`S-APV +0x1D86`）。

**(3) cacheLevel 1 的 target 就是 KC VA；cacheLevel 0 需要按段补偏移。** `KNOWN`

System KC 内各件的 `vmaddr` 本身就落在 30 位可表示范围内（`0x13D3F000` ~
`0x14D26000`），所以 cacheLevel 1 可直接用本文第 0.1 节的样本基址定位，跨件
解析完全可靠 —— 这正是任务要求的"改用符号名交叉定位"路径。

cacheLevel 0 的 target 不是单一线性基址，因为 collection 按段类别重排，
**每个 (件, 段) 有各自的偏移**。已经实测确定的三个：

| 目标 | 偏移 | 实证 |
|---|---|---|
| `S-KRNL` `__TEXT` | `+0xFFFFFF8000018000` | `target 0x91DF10` → `__ZNK8OSObject7releaseEi`，且其后连续 4 个槽（`getRetainCount`/`retain`/`release`/`serialize`）间距 `0x20/0x10/0x10/0x10` 全部吻合 |
| `S-KRNL` `__DATA_CONST` | `+0xFFFFFF8000DCA000` | `0x1ADD40/0x1ADD58/0x1ADD68/0x176E58` 分别命中 `OSNumber::metaClass` / `IOService::metaClass` / `OSData::metaClass` / `IORegistryEntry::metaClass`，**四点同一偏移** |
| `S-KRNL` `__DATA` | **`−0x450000`**（即 `S-KRNL` 低 30 位 VA `= target − 0x450000`） | 本轮新增，四点匹配：`0x10E8C58` → `_page_size`、`0x10EE040` → `___stack_chk_guard`、`0x12AA908` → `__os_log_default`、`0x12AA5C0` → `_gIOServicePlane`（查 `kernel-low30-symmap.json`，四点同一偏移且全为精确命中） |
| `S-IOPCI` `__DATA_CONST` | `+0xFFFFFF8000100000` | `0x2940C50` → `__ZN11IOPCIDevice9metaClassE`（`0xFFFFFF8002A40C50`） |

上表第二行是本文最关键结论（§2.3）的证据基础，所以用了四点匹配而不是单点。

第三行的**符号方向要注意**：`MANIFEST-display-iosurface.md` §2.2 把 `__DATA` 增量写成 `+0x450000`，实测为 `−0x450000`（`__TEXT` 与 `__DATA_CONST` 两行的符号与该文件一致，只有 `__DATA` 这一行方向相反）。本文以实测为准。`KNOWN`

**(4) 跨 collection 的直接 `call` 解析不出来，这是样本的硬限制。** `KNOWN`

System KC 调 kernel / Boot KC 的函数走 System KC 自己 `0x10000`–`0x11000` 的
stub 页（反汇编里表现为 `call near ptr 1019Eh` 之类）。那一页不属于任何
`LC_FILESET_ENTRY`，重建件里没有，**除非拿到 `SystemKernelExtensions.kc` 本体否则
无法解析**。本文凡涉及此类调用，一律按参数形状 + 日志字符串推断并标注。
受影响的只有 libkern / IOKit KPI（`IOLockLock`、`PE_parse_boot_argn`、
`os_log_internal`、`OSMetaClassBase::safeMetaCast` 等），不影响任何家族内部结论。

**本轮做了一次穷尽尝试，结论是确定的"不可能"，不是"没查"。** `KNOWN`

重建件的 `__LINKEDIT` 携带整个 collection 的 linkedit 大块，所以可以不经 `.kc`
直接读到**全 collection 的符号表**：`S-IOAF2` 原件的 `LC_SYMTAB` 给出
`symoff=0x5F9F80 / nsyms=4707 / stroff=0x6E5470 / strsize=0x601208`，而本件自己的
nlist 切片只是其中一段 —— 从 `__LINKEDIT` 真实 `fileoff 0x8C000` 起到 `0x6E2700`
连续 **415,344** 条 nlist 全部有效可解。对这 415,344 条做筛选：

- `n_value ∈ [0x10000, 0x12000)` 的条目：**0 条**。stub 页上没有任何符号。
- `_IOLockLock`（64 条）、`_PE_parse_boot_argn`（71）、`_sysctlbyname`（12）、
  `__os_log_internal`（37）、`__ZN15OSMetaClassBase12safeMetaCastEPKS_PK11OSMetaClass`（134）
  等 KPI 名**只以 `n_type == 0x01`（`N_UNDF | N_EXT`）、`n_value == 0` 出现**，
  即只有名字没有地址。

所以 stub 地址 → KPI 名的映射在本仓库材料内**不存在可解路径**，必须取
`SystemKernelExtensions.kc` 本体（369,213,440 bytes，SHA-256
`5EDE2BA5…D94421`）。本节以下的 stub 命名一律来自调用点形状 + 公开 ABI 锚点，
标签按锚点强度分别给出。

**本轮由公开 ABI 锚点钉死的 stub（跨 System KC 全件通用，因为 stub 页是 collection 级共享的）：**

| stub | 结论 | 锚点 | 标签 |
|---|---|---|---|
| `0x10360` | `sysctlbyname(name, oldp, oldlenp, newp, newlen)` | `S-IOAF2 +0x3B752` 处 `rdi = "hw.memsize"`、`rsi = &u64`、`rdx = &(size_t)8`、`rcx = r8 = 0`，返回 int；五参形状与名字字符串唯一吻合（§7.1） | `KNOWN`（公开 ABI + 唯一字符串） |
| `0x1031E` | `current_task()` | `S-IOGFX +0x19591 / +0x1E748 / +0x25FEE` 三处都是"取返回值 → 作为 `IOMemoryDescriptor::withAddressRange` 的第 4 参 `task_t`"；**零实参**（前一条指令刚好 clobber 了 `rdi`） | `KNOWN` |
| `0x1048C` | `IOMemoryDescriptor::withAddressRange(addr, len, options, task)` | 同上三处：`(rdi=addr, rsi=len, edx∈{3, 0x10002}, rcx=current_task())`，返回值随后被 `vtable[0x1F0](obj, 0)`（`prepare`）调用 | `KNOWN` |
| `0x10678` | `IOUserClient::clientHasPrivilege(void *securityToken, const char *privilegeName)` | `S-IOGFX +0x247B1`：`(rdi=current_task(), rsi="local")`，返回 `IOReturn` 并以 `== 0` 判成功；`"local"` 就是公开头文件 `iokit/IOKit/IOUserClient.h` 的 `kIOClientPrivilegeLocalUser`（见 `11-KERNEL-DISPLAY.md` §3.3） | `KNOWN`（公开 ABI 锚点） |
| `0x100B4` | `bzero` / `memset` 清零 | 与 Boot KC 侧同形调用对照（`IOSurface` 重建件里同一模式解析为 `___bzero`，见 `12-KERNEL-IOSURFACE.md` §1.5） | `KNOWN` |
| `0x1008A` / `0x10084` | `IOInterruptEventSource::interruptEventSource(owner, action, provider, index)` / `IOTimerEventSource::timerEventSource(owner, action)` | `S-IOAF2 +0x3B2FE…+0x3B709` 连续 9 对调用，每对的第二参都是本件内一个已具名的 `*_collector(IOInterruptEventSource*,int)` / `*_timer(IOTimerEventSource*)` 成员函数，返回值随后交给 `workLoop->vtable[0x140]`（`addEventSource`） | `KNOWN`（符号级锚点） |
| 其余（`0x1007E`、`0x100A2`、`0x1000C/0x10012/0x10018`、`0x10132/0x1012C`、`0x1019E`、`0x101D4`、`0x1024C`、`0x1030C`、`0x104BC`、`0x10690/0x10792`、`0x10B0A/0x10B40` 等） | 见 `analysis/idb/macos26-25G325-x86_64/MANIFEST-10-KERNEL-ACCELERATOR.md` §4.2 的对照表 | 仅参数形状与日志字符串 | `INFERRED`，要升级必须取 `.kc` |

### 0.4 标签

沿用 `00-OVERVIEW.md` §7 的 `KNOWN` / `INFERRED` / `BLOCKED` / `TESTED`。
本文**没有任何 `TESTED`**：全部结论是静态的。

## 1. 结论速览

| 问题 | 结论 | 标签 |
|---|---|---|
| x86 上 `IOServiceMatching("IOAccelerator")` 背后的家族 | `IOGraphicsAccelerator2`（`IOAcceleratorFamily2.kext`）→ 其父类 `IOAccelerator`（**`IOGraphicsFamily.kext`**）→ `IOService`。完全不经 `IOGPUFamily` | `KNOWN` |
| type-5 user client 的类 | `IOAccelDevice2`，由 `IOGraphicsAccelerator2::newDevice()` 提供，**家族自带、非纯虚**，本项目不需要自己写 | `KNOWN` |
| type-6 user client 的类 | `IOAccelSharedUserClient2`，同样家族自带 | `KNOWN` |
| `IOGraphicsAccelerator2::start` 对 provider 的硬性要求 | 只有 `OSDynamicCast(IOService, provider)`。**没有 PCI 要求** | `KNOWN` |
| 能否挂 `IOResources` | **能**。见 §2.3 的完整论证与残留风险 | `INFERRED`（机制 `KNOWN`，未实测） |
| `IOGraphicsAccelerator2` 纯虚函数 | **17 个**，全部已定名（APV 全部覆写） | `KNOWN` |
| type-5 selector 全集 | `0`–`9`，共 10 个，legacy `IOExternalMethod` 表 `IOAccelDevice2::sDeviceMethods` | `KNOWN` |
| selector 0（64 字节）字段 | **11 个字段全部解出**，且与 `20-OBJC-DEVICE.md` §7.4 的消费侧逐偏移吻合 | `KNOWN` |
| selector 2（600 字节）字段 | **全部解出**，含 `20-OBJC-DEVICE.md` 标为"未被读取"的 `+0x18..+0x57` 64 字节 | `KNOWN` |
| 这两个结构的数据来源 | 几乎全部来自子类 `populateAccelConfig(IOAccelConfig*)` 填的 `fConfig`（accel `+0xC88`），不是 user client 自己造 | `KNOWN` |
| 内核侧额外硬依赖（既有文档漏掉的） | ① `getStampMemory()` 必须返回真实 `IOMemoryDescriptor`，否则 type-5 建立失败；② `IOSurfaceRoot` 必须存在，否则 `start` 失败；③ event machine 必须存在，否则 selector 2 空指针 | `KNOWN` |
| restricted / 非 restricted 连接 | 家族**不区分**。没有 entitlement / privilege 门，只有 per-PID 客户端数量上限 | `KNOWN` |
| 内核侧规模 | 仍是小工程，但比 `00-OVERVIEW.md` §4.4 的估计多三件事（上一行）。骨架见 §6 | `INFERRED` |

## 2. A. 服务发布与匹配

### 2.1 APV 的匹配、`probe` 与 `start`（问题 A.1）

#### 2.1.1 继承链（先把前提钉死）

`KNOWN`，全部取自各类 `__ZN<C>10superClassE` 槽（按 §0.3 解码）：

| 类 | 父类 | 父类所在件 |
|---|---|---|
| `AppleParavirtGPUControl` | **`AppleGraphicsDeviceControl`** | `S-AGDC` |
| `AppleParavirtAccelerator` | `IOGraphicsAccelerator2` | `S-IOAF2` |
| `IOGraphicsAccelerator2` | **`IOAccelerator`** | `S-IOGFX` |
| `IOAccelerator` | `IOService` | kernel |
| `AppleParavirtFramebuffer` | `IOFramebuffer` | `S-IOGFX` |
| `AppleParavirtShared` | `IOAccelShared2` | `S-IOAF2` |
| `AppleParavirtSharedUserClient` | `IOAccelSharedUserClient2` | `S-IOAF2` |
| `AppleParavirtResource` | `IOAccelResource2` | `S-IOAF2` |
| `AppleParavirtCommandQueue` | `IOAccelCommandQueue` | `S-IOAF2` |
| `AppleParavirtTask` | `IOAccelTask` | `S-IOAF2` |
| `AppleParavirtDisplayPipe` | `IOAccelDisplayPipe` | `S-IOAF2` |
| `AppleParavirtMemoryMap` | `IOAccelMemoryMap` | `S-IOAF2` |
| `AppleParavirtSysMemory` / `VidMemory` | `IOAccelSysMemory` / `IOAccelVidMemory` | `S-IOAF2` |
| `AppleParavirtEventMachine` | `IOAccelEventMachineFast2` | `S-IOAF2` |
| `AppleParavirt2DContext` | `IOAccel2DContext2` | `S-IOAF2` |
| `AppleParavirtDisplayMachine` | `IOAccelDisplayMachine` | `S-IOAF2` |
| `AppleParavirtSegmentResourceList` | `IOAccelSegmentResourceList` | `S-IOAF2` |
| `AppleParavirtDisplayPipeFence` | `IOAccelEventFence` | `S-IOAF2` |
| `AppleParavirtPageTable` / `ResourceHeap` / `ResourceHeapHandle` / `ResourceHeapNamespace` | `OSObject` | kernel |

**这一行是 `00-OVERVIEW.md` §4.1 没写到的重点**：`IOAccelerator` 这个类在
**`IOGraphicsFamily`** 里，而不是在 `IOAcceleratorFamily2` 里。它是个很薄的
`IOService` 子类，整件只有三个方法（`S-IOGFX +0x25558` `createAccelID`、
`+0x2556C` `retainAccelID`、`+0x25610` `releaseAccelID`），作用是全局分配
`IOAccelID`。

直接后果：**用户态 `IOServiceMatching("IOAccelerator")` 命中我们，靠的是类名
继承（IOKit 的 `IOProviderClass` / 服务匹配按类名匹配子类），不是
`IOMatchCategory` 字符串**。这两个"IOAccelerator"同名但是两回事，不要混。

#### 2.1.2 `probe`：不存在，是继承的默认实现

`KNOWN`。`AppleParavirtGPUControl` 的符号全集里**没有 `probe`**；
`AppleGraphicsDeviceControl` 的符号全集里也没有。
`__ZTV23AppleParavirtGPUControl` vptr `+0x5C8`（i 185）解出
`__ZN9IOService5probeEPS_Pi`。

所以 APV 的匹配完全由 personality 决定：`IOProviderClass=IOPCIDevice` +
`IOPCIMatch=0xEEEE106B` + `IOProbeScore=1000000`，`probe` 只是 `return this`。

**对本项目的含义**：不需要实现 `probe`。

#### 2.1.3 `AppleParavirtGPUControl::start`（`S-APV +0x102E`）

`KNOWN`，逐行：

```c
bool AppleParavirtGPUControl::start(IOService *provider)
{
    setupAPVLog();                                        // S-APV +0xFC03
    int v = 0;
    if (PE_parse_boot_argn("-x", &v, 4))                  // safe boot
        flagsMask &= 0xFD;                                // 清掉 bit1 → 不建 accelerator
    OSString *s = OSString::withCString("Apple Paravirtualized Graphics Device");
    provider->setProperty("model", s);                    // vptr +0x268 = setProperty(const char*, OSObject*)
    s->release();

    if (!this->setupMMIO())                               // S-APV +0xF64
        return false;

    uint32_t n = *(uint32_t *)(this->fMMIO /*+0x168*/ + 0x22C);   // DisplayPortCount
    this->fDisplayPortCount /*+0x114*/ = n;
    if (n == 0)      this->fDisplayPortCount = 1;
    else if (n >= 9) { log("DisplayPortCount configuration (%u) exceeds max (%u). Setting to %u");
                       this->fDisplayPortCount = 8; }

    return AppleGraphicsDeviceControl::start(provider);   // __ZTV26AppleGraphicsDeviceControl +0x5D0 (i 184)
}
```

`setupMMIO`（`S-APV +0xF64`）：

```c
bool AppleParavirtGPUControl::setupMMIO(void)
{
    IOService *p = this->getProvider();                   // vptr +0x680 = IOService::getProvider
    IOPCIDevice *pci = OSDynamicCast(IOPCIDevice, p);     // got 槽 S-APV +0xB0010 → IOPCIDevice::metaClass
    if (!pci) { log("%s: Provider is not an IOPCIDevice.\n", "setupMMIO"); return false; }

    this->fMap /*+0x160*/ = pci->mapDeviceMemoryWithRegister(0x10 /*BAR0*/, 0);  // IOPCIDevice vptr +0x908
    if (!this->fMap) { log("%s: Failed to map the MMIO bar.\n", "setupMMIO"); return false; }

    this->fMMIO /*+0x168*/ = this->fMap->getVirtualAddress() + 0x1000;           // IOMemoryMap vptr +0x118
    return true;
}
```

**`AppleParavirtGPUControl` 对 provider 的硬性要求（明确回答 A.1）**：

1. provider 必须能 `OSDynamicCast` 成 `IOPCIDevice`。`KNOWN`
2. 该 PCI 设备必须有 **BAR0 的内存资源**，且 `mapDeviceMemoryWithRegister(0x10, 0)`
   必须成功。`KNOWN`
3. BAR0 的第二个 4 KiB 页（`BAR0 + 0x1000`）是设备配置页；`+0x22C` 是
   `DisplayPortCount`。`KNOWN`
4. 它**不**注册任何中断，**不**读 PCI 配置空间，**不**要求 MSI。`KNOWN`

中断与 MSI 的要求在 **accelerator** 侧，不在 control 侧：
`AppleParavirtAccelerator::configureDevice`（`S-APV +0x2F38`）要求
`findPCICapability(5 /* kIOPCICapabilityMSI */, &off)` 成功、随后
`setMemoryEnable(true)`，再 `setupMMIO` / `setupVersion` / `setupRoot` / `setupFIFO`；
`AppleParavirtAccelerator::setupInterrupts`（`S-APV +0x2054`）才建中断源。
**这四步全在 APV 的子类实现里，不是家族要求**，所以本项目可以整段不做（§2.4）。

### 2.2 `AppleParavirtAccelerator` 的创建与发布，`AcceleratorProperties` 的提升（问题 A.2）

#### 2.2.1 它不是 IOKit 匹配出来的

`KNOWN`，三条事实：

1. `AppleParavirtGPU.kext/Contents/Info.plist` 只有**一个** personality
   （`AppleParavirtGPUControl`，`IOMatchCategory=IOFramebuffer`），
   没有任何 `IOClass=AppleParavirtAccelerator` 的 personality。
2. `IOAcceleratorFamily2.kext/Contents/Info.plist` **完全没有 `IOKitPersonalities` 键**。
3. 字符串 `"AcceleratorProperties"` 在 25G325 x86_64 的样本集中只出现在
   `S-APV` 的 `__cstring`（`S-APV +0x156F9`）与 APV 的 `Info.plist` 里。
   `S-IOAF2`、`S-IOGFX`、`S-AGDC`、`S-KRNL` 全部没有这个字符串（全文件字节扫描）。

所以没有任何代码"把嵌套字典提升成 personality"。真相是 APV 自己手工 new + attach + start。

#### 2.2.2 实际代码路径

`KNOWN`。创建点在 **AGDC 的 `doDeviceAttribute` 处理函数**里，不在 `start` 里。

该函数在符号表中没有独立符号，IDA 把它归入
`____ZN23AppleParavirtGPUControl24vendor_doDeviceAttributeEjPmmS0_S0_P25IOExternalMethodArguments_block_invoke`
（`S-APV +0x121A` .. `+0x16F1`）。它按 AGDC attribute code 分派
（`1`、`3`、`0x920`、`0x921`、`0x980`、`0x2001`，其余转发给每个 framebuffer 的
`AppleParavirtFramebuffer::doDeviceAttribute`）。

attribute `3`（"set enable flags"）的分支做两件事（`S-APV +0x14CA` 起）：

```c
uint32_t want = flagsMask & *(uint32_t *)in;      // flagsMask: boot-arg "-x" 会清掉 bit1
IOService *pci = this->getProvider();             // ← 注意：是 IOPCIDevice，不是 this

if (want & 1) {                                   // bit0: 建 framebuffer
    for (i = 0; i < this->fDisplayPortCount; i++) {
        fb = new AppleParavirtFramebuffer(0x2B0);
        if (fb && fb->initWithID(i)
               && fb->attach(pci)                 // vptr +0x670 = IOService::attach
               && fb->start(pci)) {               // vptr +0x5C0 = start
            this->fFramebuffers[i] /*+0x118+8i*/ = fb;
        } else { fb->detach(pci); fb->release(); }
    }
}

if (want & 2) {                                   // bit1: 建 accelerator
    accel = new AppleParavirtAccelerator(0xF88);           // S-APV +0x15BB..+0x15CB
    if (!accel) goto done;
    if (!accel->init(NULL))          goto fail;            // vptr +0x248 = IOService::init(OSDictionary*)
    if (!accel->attach(pci))         goto fail;            // vptr +0x670, provider = IOPCIDevice

    OSObject *props = this->getProperty("AcceleratorProperties");   // vptr +0x2B8
    if (props) {                                                     // ← 属性提升在这里
        OSCollectionIterator *it = <stub 0x10252>(props);            // withCollection(props)
        while ((k = it->getNextObject()) != NULL) {                  // iter vptr +0x128
            OSString *key = OSDynamicCast(OSString, k);              // got S-APV +0xB00B8
            if (!key) continue;
            OSObject *val = ((OSDictionary *)props)->getObject(key); // vptr +0x200
            accel->setProperty(key, val);                            // vptr +0x260
        }
        it->release();
    }

    if (accel->start(pci))                                 // vptr +0x5C0
        this->fAccelerator /*+0x158*/ = accel;
    else { accel->detach(pci); accel->release(); }
}
```

**结论（直接回答 A.2 的三问）**：

1. **`AppleParavirtAccelerator` 不是 control 的子节点，而是同一个 `IOPCIDevice`
   nub 的第二个 client。** `KNOWN` 两者都 `attach(pci)`，靠 `IOMatchCategory`
   区分：外层 personality 占 `IOFramebuffer`，`AcceleratorProperties` 里的
   `IOMatchCategory=IOAccelerator` 被拷到 accelerator 对象上，于是它占 `IOAccelerator`。
2. **`AcceleratorProperties` 的提升是一段显式的字典遍历 + `setProperty`**，
   发生在 `attach` 之后、`start` 之前。`MetalPluginName` 因此出现在 service 上，
   而不是停留在 bundle plist 里。`KNOWN`
3. **`registerService()` 不在这里**，在 `AppleParavirtAccelerator::start` 的末尾
   （`S-APV +0x1FDF`，vptr `+0x5B0` = `IOService::registerService`）。`KNOWN`

#### 2.2.3 Intel 的做法才是 x86 的"正常"做法，本项目照它抄

`KNOWN`。`AppleIntelKBLGraphics.kext/Contents/Info.plist`（样本见
`analysis/idb/macos26-25G325-x86_64-frameworks/plugin-plists/`，注意该目录的来源
标注问题见 `90-EVIDENCE-INDEX.md` §6.2）只有一个 personality，键如下（节选）：

```xml
<key>IOClass</key>            <string>IntelAccelerator</string>
<key>IOProviderClass</key>    <string>IOPCIDevice</string>
<key>IOMatchCategory</key>    <string>IOAccelerator</string>
<key>MetalPluginName</key>    <string>AppleIntelKBLGraphicsMTLDriver</string>
<key>IOAccelDisplayPipeCapabilities</key> <dict>…</dict>
<key>IOProbeScore</key>       <integer>1000</integer>
```

即：**accelerator 本身就是被匹配的那个 service，`MetalPluginName` 是 personality
的顶层键，由 IOKit 在匹配时并入 service 的属性表。** 没有任何代码参与。

APV 之所以要手工 new，是因为它要把 framebuffer 与 accelerator 的生命周期绑在
AGDC 的 enable 流程上（WindowServer 准备好才建）。**本项目没有这个需求，
应当走 Intel 的声明式路径**，省掉整个 AGDC 依赖。详见 §6。

### 2.3 本项目 kext 的 provider 选择（问题 A.3，本分册最重要的一条）

#### 2.3.1 `IOGraphicsAccelerator2::start` 对 provider 的全部要求

`KNOWN`，`S-IOAF2 +0x3A752`。按执行顺序列出**每一个可能失败的点**：

| # | 动作 | 失败后果 | 对 provider 的要求 |
|---|---|---|---|
| 1 | `initLog(this, provider->getName())` | — | 任何 `IORegistryEntry` 都有 `getName` |
| 2 | `IOAccelerator::start(provider)`（= `IOService::start`） | 返回 false | 无 |
| 3 | 清零约 60 个 ivar；`bzero(this+0x1A0, 408)` | — | 无 |
| 4 | `fWorkLoopLock = IOLockAlloc()` | `stop()` + false | 无 |
| 5 | **`this->fProvider (+0x368) = OSDynamicCast(IOService, provider)`** | 日志 `"provider is not the right device"` → 失败 | **provider 只需是 `IOService`** |
| 6 | `this->configureDevice(fProvider)`（纯虚，vptr `+0x9C0`，i 312） | 日志 `"configureDevice failed"` → 失败 | 由**子类**决定 |
| 7 | `OSDynamicCast(IORegistryEntry, fProvider)->getProperty("model")` → `OSDynamicCast(OSData, …)` → 拷成 `OSString` 存 `fModelName (+0x370)` | **不失败**，拿不到就留 NULL | `model` 属性可选，且必须是 `OSData` 才会被采纳 |
| 8 | `fProvider->getProperty("IOMemoryDescriptorOptions")` → `OSNumber` → `+0x1380` | 不失败 | 可选 |
| 9 | `waitForService(IOServiceMatching("GMUX"))`，有则置 `+0xC78` bit7 | 不失败 | 无 |
| 10 | `initializeConfigStructure()`（`S-IOAF2 +0x3A36A`） | — | 无 |
| 11 | **`this->populateAccelConfig(&fConfig)`（纯虚，vptr `+0x9B0`，i 310）** | 无返回值检查 | 由子类决定 |
| 12 | `this->getProperty("IOPCITunnelled", gIOServicePlane, kIORegistryIterateParents\|Recursively)`，有则置 `Removable` 属性 | 不失败 | 无（搜不到就跳过） |
| 13 | 读 boot-args `ioaccel_debug` / `panic_on_gpu_hang` / `panic_on_display_hang` / `spin_wait_for_gpu` / `gpu_no_zero_fill` / `prepare_throttling` | — | 无 |
| 14 | 若 `fConfig+0x64` bit6 置位：`createDMACommandPool()` | 日志 `"Failed to Create Command Pool"` → 失败 | 无（该位默认 0，APV 也不置） |
| 15 | **`fIOSurfaceRoot (+0x170) = waitForService(IOServiceMatching("IOSurfaceRoot"))`** | 日志 `"fail to get IOSurface root"` → 失败 | 无，但 **`IOSurface.kext` 必须已加载并发布了 `IOSurfaceRoot`** |
| 16 | `fIOSurfaceRoot->retain()`；`<stub 0x111A6>(root, cfg+0x4C, cfg+0x50, cfg+0x54, (u16)cfg+0x30, (u16)cfg+0x32)` | — | 无 |
| 17 | **`this->fAccelID (+0x178) = <stub 0x111BE>(fIOSurfaceRoot, this)`** | — | 无 |
| 18 | `initGlobalCommPage()`（`S-IOAF2 +0x3C0D4`）、`oneTimeSetup()`（`+0x3C17A`）、`new IOAccelNamespace(0x30)` | — | 无 |

**第 5 行是答案**：`off_14BCF078`（`S-IOAF2 +0x6A078` 的 `__got` 槽）解码 target
`0x1ADD58`，按 §0.3(3) 的 `S-KRNL` `__DATA_CONST` 偏移命中
**`__ZN9IOService9metaClassE`**。该槽在 `S-IOAF2` 全件只有两个引用点：
`IOGraphicsAccelerator2::start`（`S-IOAF2 +0x3A9D4`）与
`IOAccelDisplayMachine::start(IOPCIDevice*)`（`S-IOAF2 +0xDCCE`）。

注意反直觉之处：**纯虚 `configureDevice` 的声明形参类型是 `IOPCIDevice*`，
但家族传进去的是一个只做过 `OSDynamicCast(IOService, …)` 的指针。** 家族自己
从不在 provider 上调用任何 `IOPCIDevice` 方法；是不是 PCI 设备、要不要映射 BAR，
全部由子类的 `configureDevice` 自己决定。APV 的实现恰好把它当 PCI 用，
Intel/AMD 也一样，于是形参类型沿用了 `IOPCIDevice*`。

第 17 行顺带解决了 `accelID` 的来源：**`accelID` 不是我们填的，是
`IOSurfaceRoot` 在 accelerator 注册时分配的。** `KNOWN`

#### 2.3.2 `IOAccelDevice2`（type-5）对 provider 的要求

`KNOWN`，`S-IOAF2 +0xCC5A`：

```c
bool IOAccelDevice2::start(IOService *provider)
{
    if (!IOUserClient::start(provider)) return false;          // __ZTV12IOUserClient +0x5D0 (i 184)
    this->fAccel /*+0x108*/ = OSDynamicCast(IOGraphicsAccelerator2, provider);
    if (!this->fAccel) return false;
    acceleratorLock(fAccel); fAccel->acceleratorDidLock("", 0);
    this->fStarted /*+0x111*/ = this->deviceStart();           // vptr +0x960 (i 300)
    this->fTerminated /*+0x110*/ = 0;
    fAccel->acceleratorWillUnlock("", 0); acceleratorUnlock(fAccel);
    return this->fStarted;
}
```

即 user client 的 provider 必须是 `IOGraphicsAccelerator2` 子类 —— 这是我们自己，
没有额外约束。

#### 2.3.3 裁决：能挂 `IOResources`

**结论：可以。** `INFERRED`（机制全部 `KNOWN`，未在 guest 内实测）

依据：

1. §2.3.1 第 5 行，家族对 provider 的类型要求只到 `IOService`。`IOResources`
   是 `IOService` 子类，`OSDynamicCast` 成立。`KNOWN`
2. §2.3.1 的 18 步里**没有任何一步**读 provider 的 PCI 资源、配置空间、中断或
   内存描述符。唯一两个属性读（`model`、`IOMemoryDescriptorOptions`）都是可选的。`KNOWN`
3. 两个纯虚 `configureDevice` / `teardownDevice` 是我们自己实现的，可以直接
   `return true` / `return`。`KNOWN`（纯虚集合见 §2.4）
4. 先例：`IOSurface.kext` 自己的 personality 就是 `IOProviderClass=IOResources`
   （`90-EVIDENCE-INDEX.md` §2.3 登记了该 plist）。`IOResources` 作为合成
   provider 在 IOKit 中是常规手法。`KNOWN`

推荐的 personality（本项目 kext）：

```xml
<key>IOKitPersonalities</key>
<dict>
  <key>LavapipeAccelerator</key>
  <dict>
    <key>CFBundleIdentifier</key>  <string>…</string>
    <key>IOClass</key>             <string>LPAccelerator</string>   <!-- : IOGraphicsAccelerator2 -->
    <key>IOProviderClass</key>     <string>IOResources</string>
    <key>IOResourceMatch</key>     <string>IOKit</string>
    <key>IOMatchCategory</key>     <string>IOAccelerator</string>
    <key>IOProbeScore</key>        <integer>1000</integer>
    <key>MetalPluginName</key>     <string>LavapipeMetal</string>
    <key>MetalPluginClassName</key><string>LPDevice</string>
    <key>IOAccelDisplayPipeCapabilities</key>
    <dict>
      <key>DisplayPipeSupported</key>  <false/>
      <key>TransactionsSupported</key> <false/>
    </dict>
  </dict>
</dict>
```

要点与风险：

- `IOResourceMatch=IOKit` 是让 `IOResources` 在 IOKit 就绪后才匹配的惯用写法。
  **本条是 `INFERRED`**：没有在 25G325 上实测过 `IOResources` + 这个 match
  category 的组合。
- `IOSurface.kext` 必须先起来（§2.3.1 第 15 行是 `waitForService`，会阻塞而不是
  失败，所以顺序上安全）。应在 `OSBundleLibraries` 里声明
  `com.apple.iokit.IOSurface`、`com.apple.iokit.IOAcceleratorFamily2`、
  `com.apple.iokit.IOGraphicsFamily`，**不要**声明 `IOPCIFamily`、
  **不要**声明 `AppleGraphicsDeviceControl`。`INFERRED`
- `IOMatchCategory=IOAccelerator` 在 `IOResources` 上没有竞争对手，纯粹是给
  用户态看的惯例值。
- **真正需要提防的不是 accelerator，而是 display（分册 `11`）**：
  WindowServer 选哪个 Metal device 取决于 display 挂在哪个 accelerator 上
  （`00-OVERVIEW.md` §5 已指出组件 2 与 3 耦合）。`IOFramebuffer` 对 provider
  的要求本文不负责，留给 `11-KERNEL-DISPLAY.md`。如果 framebuffer 侧被迫要
  一个 PCI nub，那么把 accelerator 也挂到同一个 nub 上会更一致。
- 备选方案（若实测发现 `IOResources` 路径有问题）：写一个自有的
  `IOService` nub 子类挂在 `IOResources` 上，`registerService()`，再让
  accelerator 以 `IOProviderClass=<我们的 nub 类名>` 匹配它。这完全在
  §2.3.1 的允许范围内（nub 是 `IOService`），而且顺带给 display 侧提供了同一个
  父节点。**推荐把这个作为第一版实现**，因为它同时满足 accelerator 与 display
  的共同父节点需求，代价只是多一个 20 行的类。`INFERRED`

### 2.4 `IOGraphicsAccelerator2` 的纯虚与必须覆写方法全集（问题 A.4）

#### 2.4.1 纯虚函数：恰好 17 个

`KNOWN`。判定方法：逐槽解码 `__ZTV22IOGraphicsAccelerator2`
（`S-IOAF2 +0x7B8E0`），凡 target 命中 `___cxa_pure_virtual` 即纯虚；再用
`__ZTV24AppleParavirtAccelerator`（`S-APV +0x1A040`）同槽取名 —— APV **把 17 个
全部覆写了**，所以每一个都有确切签名。

| vptr 偏移 | i | 方法（APV 的覆写符号） | 返回值语义 | 不实现的后果 |
|---|---|---|---|---|
| `0x878` | 271 | `getStampMemory(uint32_t *outOffset)` → `IOMemoryDescriptor*` | 事件戳页的内存描述符 + 页内偏移 | **type-5 建立失败**，见 §4.3 |
| `0x888` | 273 | `newEventMachine()` → `IOAccelEventMachine2*` | 新建事件机 | selector 2 空指针，见 §4.4 |
| `0x998` | 307 | `createUserGPUTask()` → `IOAccelTask*` | 用户态 GPU 任务对象 | 任何 user client 建立时失败 |
| `0x9B0` | 310 | `populateAccelConfig(IOAccelConfig *cfg)` | 无返回值 | `fConfig` 保持默认，`accelName` 为 NULL |
| `0x9C0` | 312 | `configureDevice(IOPCIDevice *provider)` → `bool` | false ⇒ `start` 失败 | `start` 失败 |
| `0x9C8` | 313 | `teardownDevice(IOPCIDevice *provider)` | 无返回值 | `stop` 路径崩 |
| `0x9D0` | 314 | `createKernelGPUTask()` → `IOAccelTask*` | 内核 GPU 任务对象 | 同 307 |
| `0xA00` | 320 | `newDisplayMachine()` → `IOAccelDisplayMachine*` | — | display pipe 路径崩 |
| `0xA20` | 324 | `newGLContext()` → `IOAccelContext2*` | **APV 直接 `return 0`** | 无（type 1/3/7 会失败，可接受） |
| `0xA28` | 325 | `newCLContext()` → `IOAccelContext2*` | **APV 直接 `return 0`** | 同上 |
| `0xA30` | 326 | `newSurface()` → `IOAccelSurface*` | **APV 直接 `return 0`** | type-0 client 失败，可接受 |
| `0xA38` | 327 | `new2DContext()` → `IOAccel2DContext2*` | APV: `new AppleParavirt2DContext(0x1100)` | type-2 client 失败 |
| `0xA40` | 328 | `newVideoContext()` → `IOAccelContext2*` | — | — |
| `0xA60` | 332 | `newSysMemory()` → `IOAccelSysMemory*` | APV: `new AppleParavirtSysMemory(0x198)` | 任何系统内存分配崩 |
| `0xA68` | 333 | `newVidMemory()` → `IOAccelVidMemory*` | APV: `new AppleParavirtVidMemory(0x110)` | 显存分配崩 |
| `0xA70` | 334 | `newResource()` → `IOAccelResource2*` | APV: `new AppleParavirtResource(0x1F0)` | type-6 selector 0 崩 |
| `0xA88` | 337 | `newMemoryMap()` → `IOAccelMemoryMap*` | APV: `new AppleParavirtMemoryMap(0x118)` | 任何映射崩 |

**三条必须注意的**：

1. `newGLContext` / `newCLContext` / `newSurface` 在 APV 里**就是
   `xor eax,eax; ret`**（`S-APV +0x311C` / `+0x3124` / `+0x312C`）。
   **所以"纯虚 ⇒ 必须返回有效对象"是错的**：返回 NULL 是家族容忍的，
   对应的 user client type 创建会以 `kIOReturnNoResources` 失败而已。
   这给本项目省掉一大片。`KNOWN`
2. 其余的工厂在 APV 里全是一行 `new <具体子类>(size)`（`S-APV +0x31D4`、
   `+0x31FA`、`+0x3220`、`+0x3246`、`+0x326C`、`+0x3292`、`+0x3162`、
   `+0x3188`、`+0x31AE`、`+0x2826`、`+0x284C`、`+0x28A0`、`+0x3134`）。
   家族负责随后的 `init`，工厂只管分配。`KNOWN`
3. `___cxa_pure_virtual` 在 xnu 里是**立即 panic**，不是返回错误。不实现等于
   在第一次调用处挂掉内核。

#### 2.4.2 非纯虚但建议覆写

`KNOWN`（机制），`INFERRED`（建议）：

| vptr 偏移 | i | 方法 | 为什么要覆写 |
|---|---|---|---|
| `0x5C0` | 184 | `start(IOService*)` | 调 `super::start` 后做自己的初始化；**必须先调 super** |
| `0x5C8` | 185 | `stop(IOService*)` | 对偶 |
| `0x990` | 306 | `getMaxWiredSysMemorySize()` | **这是 selector 0 的 `sharedMemorySize` 唯一来源**，基类返回 ivar `+0x348`，该 ivar 在 `S-IOAF2 +0x3BA87`（`mov [r14+348h], rax`）被赋值。**来源已查清（§7.1）：`= calcMaxGPUPhysicalMemoryBytes(sysctl "hw.memsize")`，即 `max(物理内存/3, 64 MiB)` 向上页对齐。** 覆写最省事 |
| `0xA90` | 338 | `getMaxResourceSize()` | 基类实现已够用（见下） |
| `0x868` | 269 | `totalTextureMemory()` | 基类返回 `fConfig+0x20`，够用 |
| `0x688` | 209 | `getWorkLoop()` | 基类有实现，APV 不覆写 |
| `0x850` / `0x858` | 266 / 267 | `acceleratorDidLock` / `acceleratorWillUnlock` | 基类有实现，APV 不覆写 |

`getMaxResourceSize` 基类实现（`S-IOAF2 +0x4017C`）：

```c
uint64_t v = this->getMaxSingleSysMemorySize();        // vptr +0x988 (i 305)
if (fConfig.videoRam /*+0x20*/ != 0)
    v = min(v, (3 * fConfig.videoRam / 4) & ~(page_size - 1));
return (v > 0x40000000) ? v : 0x40000000;              // 下限 1 GiB
```

**它有 1 GiB 硬下限**，所以 `20-OBJC-DEVICE.md` §5.2.1 要求的
`_limits.maxBufferLength > 0` 自动满足，不用操心。`KNOWN`

#### 2.4.3 APV 覆写全集（对照用）

`KNOWN`，`__ZTV24AppleParavirtAccelerator` 与 `__ZTV22IOGraphicsAccelerator2`
逐槽比对，差异槽只有：

- 0/1（`D1Ev`/`D0Ev`）、7（`getMetaClass`）、18（`free`）
- 184（`start`）、185（`stop`）
- 17 个纯虚（§2.4.1 全部）
- 321（`newShared`）、322（`newSharedUserClient`）、329（`newDisplayPipe`）、
  348（`newCommandQueue`）—— 这四个基类**有**实现，APV 仍覆写成自己的子类
- 353/354/370（MetaClass 的 `D1`/`D0`/`alloc`）

**反过来说：`newUserClient`、`newDevice`、`newContext`、`newDrawable`、
`newStatistics`、`newCommandDescriptor`、`createRemoteMemory`、`triage`、
`describeDriverAllocations`、`terminate`、`finalize`、`setProperties`
全部是纯继承的，APV 一行没改。** 本项目同样不该改。`KNOWN`

#### 2.4.4 `AppleParavirtAccelerator::start` 的结构（照抄模板）

`KNOWN`，`S-APV +0x1EDE`：

```c
bool AppleParavirtAccelerator::start(IOService *provider)
{
    void *alloc = new <TaskIDAllocator>(0x30);
    this->fTaskIDAllocator /*+0xE60*/ = alloc;
    if (!alloc || !alloc->init(256 /*capacity*/, 1, 32, 0)) {
        log("Failed to allocate task ID allocator\n");
        goto fail;
    }
    alloc->reserve(0, 1);                                   // 预留 ID 0

    if (!IOGraphicsAccelerator2::start(provider)) goto fail;   // ← super 先行

    acceleratorLock(this);
    IOGraphicsAccelerator2::lock_busy(this);                   // S-IOAF2 +0x41DA2
    this->acceleratorDidLock("", 0);

    if (setupInterrupts() && setupChannels() && setupDeviceInfo()) {
        IOGraphicsAccelerator2::acceleratorUnlock(this);
        this->registerService(0);                              // vptr +0x5B0
        return true;
    }

    this->acceleratorWillUnlock("", 0);
    IOGraphicsAccelerator2::unlock_busy(this);
    acceleratorUnlock(this);
fail:
    this->stop(provider);                                      // vptr +0x5C8
    return false;
}
```

两个必须照抄的点：`super::start` 在自有初始化**之前**；成功路径末尾
**显式 `registerService(0)`**。`KNOWN`


## 3. B. user client

### 3.1 `newUserClient` 的 type 映射全集（问题 B.5）

`KNOWN`，`IOGraphicsAccelerator2::newUserClient(task*, void*, UInt32 type, IOUserClient**)`，
`S-IOAF2 +0x3DEAE`。**APV 不覆写它**（§2.4.3），所以这就是本项目将会得到的行为。

前置流程（对所有 type 一样）：

1. `task == NULL` → 返回 `0xE00002C2`（`kIOReturnBadArgument`）。
2. `*handle = NULL`；`this+0x9BC = 1`。
3. 取 accelerator lock + `lock_busy` + `acceleratorDidLock("", 0)`。
4. 统计调用进程 PID 在四张表里的现存客户端数：
   `IOAccelContextList`(`this+0xA58`) + `IOAccelCommandQueueList`(`this+0xA68`)
   + `IOAccelDeviceList`(`this+0xA78`) + `IOAccelSharedUserClientList`(`this+0xA98`)。
   - 总数 > **软上限** `fConfig+0x70`（默认 256）→ 打警告
     `"… has too many contexts (…) + queues (…) + device (…) + shared (…) created. Possibly leaking?"`，
     **仍然继续**。
   - 总数 > **硬上限** `fConfig+0x74`（默认 512）**且** `fConfig.debugBits`(`+0x14`) bit3 置位
     → 返回 `0xE0078001` 并放锁。debugBits 默认 0，所以默认配置下这条**永远不触发**。
5. `acceleratorWillUnlock` + `unlock_busy` + 放锁，然后进 `switch(type)`（跳转表
   `S-IOAF2 +0x3E162`）。

| type | 工厂（vptr 偏移 / i） | 对象类（尺寸） | `init` 调用 | 工厂返回 NULL 时 |
|---:|---|---|---|---|
| `0` | `newSurface` `0xA30` / 326（**纯虚**） | `IOAccelSurface` | `init(NULL, task)` | `0xE00002BE` `kIOReturnNoResources` |
| `1` | `newContext(type)` `0xA58` / 331 | `IOAccelContext2` | `init(NULL, task)` | `0xE00002C2` |
| `2` | `new2DContext` `0xA38` / 327（**纯虚**） | `IOAccel2DContext2` | `IOAccelContext2::init(NULL, task)` | `0xE00002BE` |
| `3` | `newContext(type)` `0xA58` / 331 | `IOAccelContext2` | 同上 | `0xE00002C2` |
| `4` | 内联 `new IOAccelDisplayPipeUserClient2(0x1A8)`，**且仅当 `fConfig+0x47 != 0`** | `IOAccelDisplayPipeUserClient2` | — | 条件不满足 → `0xE00002C7` `kIOReturnUnsupported` |
| **`5`** | **`newDevice` `0xA18` / 323（基类已实现）** | **`IOAccelDevice2`（0x188 字节）** | `init(NULL, task)` | `0xE00002BE` |
| **`6`** | **`newSharedUserClient` `0xA10` / 322（基类已实现）** | **`IOAccelSharedUserClient2`（0x168 字节）** | `init(NULL, task)` | `0xE00002BE` |
| `7` | `newContext(type)` `0xA58` / 331 | `IOAccelContext2` | 同上 | `0xE00002C2` |
| `8` | `newCommandQueue` `0xAE0` / 348（基类已实现） | `IOAccelCommandQueue` | `init(NULL, task)` | `0xE00002BE` |
| `9` | `IOAccelGLDrawableUserClient`（0x670 字节） | 同 | — | — |
| `32` | `IOAccelSurfaceMTL`（0x340 字节） | 同 | — | — |
| `33` | `IOAccelMemoryInfoUserClient`（0xE8 字节） | 同 | — | — |
| 其他 | `newContext(type)` `0xA58` / 331 | `IOAccelContext2` | 同上 | `0xE00002C2` |

**明确回答"type 5 与 type 6 分别是什么类"**：

- **type 5 → `IOAccelDevice2`**，由 `IOGraphicsAccelerator2::newDevice()`
  （`S-IOAF2 +0x3E77C`，整函数就是 `new IOAccelDevice2(0x188)`）创建。`KNOWN`
- **type 6 → `IOAccelSharedUserClient2`**，由
  `IOGraphicsAccelerator2::newSharedUserClient()`（`S-IOAF2 +0x3E756`，
  `new IOAccelSharedUserClient2(0x168)`）创建。`KNOWN`

两者**都是 `IOAcceleratorFamily2` 自带的具体类，不是纯虚**。本项目可以完全
不覆写，直接继承 —— 这是本分册最省力的一条：**type-5 / type-6 的 user client
代码一行都不用写**，只需要让它们能取到数据（§3.3、§3.4）。

创建后的公共尾部（`type` 0/2/5/6/8 路径）：

```
if (!uc->init(NULL, task))       { uc->release(); return 0xE00002BE; }
if (!uc->attach(this))           { uc->release(); return 0xE00002C9; }   // kIOReturnInternalError
if (!uc->start(this))            { …从各 List 中摘除…; uc->detach(this); uc->release(); return 0xE00002C9; }
*handle = uc; uc->retain(); return 0;
```

非法 type 的最终表现：落到 `newContext(type)`；该函数对未知 type 返回 NULL
（`INFERRED` —— 未反编译 `IOGraphicsAccelerator2::newContext`），于是
`newUserClient` 返回 **`0xE00002C2` `kIOReturnBadArgument`**。`INFERRED`

### 3.2 type-5 `externalMethod` 调度表全量（问题 B.6）

#### 3.2.1 调度机制：legacy `IOExternalMethod` 表

`KNOWN`。`IOAccelDevice2` 继承自 **`IOUserClient`**（不是 `IOUserClient2022`；
依据：`init` / `start` / `externalMethod` 三处 super 调用都走
`S-IOAF2 +0x6A088` 的 `__got` 槽，该槽解码为 `__ZTV12IOUserClient`）。

分派走 `getTargetAndMethodForIndex`（`S-IOAF2 +0xD9F2`），整函数是：

```c
IOExternalMethod *IOAccelDevice2::getTargetAndMethodForIndex(IOService **target, UInt32 index)
{
    *target = this;
    if (index < 0xA)
        return &IOAccelDevice2::sDeviceMethods[index];   // 48 字节步长
    return NULL;
}
```

**selector 上界是 10（`0`..`9`）**。越界返回 NULL，`IOUserClient::externalMethod`
的默认实现据此返回 `kIOReturnBadArgument`（`INFERRED`，xnu 侧未反编译）。

`IOAccelDevice2::externalMethod`（`S-IOAF2 +0xD894`）在转给
`IOUserClient::externalMethod` 之前加了一道闸：

```c
IOLockLock(this + 0x180);
ret = kIOReturnOffline /*0xE00002D7*/;
if ((this->fTerminated /*+0x112, bit0*/ & 1) == 0)
    ret = IOUserClient::externalMethod(selector, args, dispatch, target, ref);
… 解锁、若已终止则做延迟清理 …
return ret;
```

即**设备已终止的连接上任何 selector 都返回 `0xE00002D7`**。`KNOWN`

#### 3.2.2 `IOAccelDevice2::sDeviceMethods` 全表

`KNOWN`。表基址 `S-IOAF2 +0x6FBB0`（VA `0x14BD4BB0`），**步长 48 字节**，
结构是经典 `IOExternalMethod`：

```c
struct IOExternalMethod {       // x86_64 下 48 字节
    IOService   *object;        // +0x00   全表皆 NULL ⇒ target = user client 自身
    IOMethod     func;          // +0x08   成员函数指针（函数地址 8 + this 调整 8）
    IOOptionBits flags;         // +0x18   (IOByteCount 对齐到 8)
    IOByteCount  count0;        // +0x20
    IOByteCount  count1;        // +0x28
};
```

`flags` 取值：`0 = kIOUCScalarIScalarO`、`2 = kIOUCScalarIStructO`、
`3 = kIOUCStructIStructO`；`count1 == 0xFFFFFFFF` 即 `kIOUCVariableStructureSize`。

| sel | flags | count0 | count1 | 内核方法（`S-IOAF2` RVA） | 用户态包装（`S-IOACCEL`） | 本项目 |
|---:|---|---|---|---|---|---|
| `0` | 2 `ScalarI_StructO` | 0 scalar in | **0x40 = 64 B out** | `get_config(IOAccelDeviceConfigData*)` `+0xD080` | `IOAccelDeviceGetConfig64` / `GetPeerInfo` / `GetSharedMemorySize` / `GetMaxResourceSize` | **必须** |
| `1` | 2 | 0 | 0x40 = 64 B out | `get_name(char*)` `+0xD1A4` | `IOAccelDeviceGetName` | 建议 |
| `2` | 2 | 0 | **0x258 = 600 B out** | `get_event_machine(IOAccelDeviceEventMachineData*)` `+0xD1DC` | （创建链步 4） | **必须** |
| `3` | 2 | **1 scalar in** | 0x18 = 24 B out | `get_surface_info(uint32_t, IOAccelDeviceSurfaceData*)` `+0xD322` | `IOAccelDeviceGetSurfaceInfo` | 不必须 |
| `4` | 0 `ScalarI_ScalarO` | **2 scalar in** | 0 scalar out | `set_stereo(uint32_t, uint32_t)` `+0xD4EA` | `IOAccelDeviceSetFramebufferStereo` | 不必须 |
| `5` | 2 | 0 | 0x08 = 8 B out | `get_next_global_object_id(IOAccelDeviceGlobalObjectIDData*)` `+0xD4F6` | `IOAccelDeviceGetNextGlobalTraceID`（trace） | 不必须 |
| `6` | 2 | 0 | 0x08 = 8 B out | `get_current_trace_filter(IOAccelDeviceTraceFilterData*)` `+0xD51C` | `IOAccelDeviceGetCurrentTraceFilter` | 不必须 |
| `7` | 2 | 0 | 0x18 = 24 B out | `get_device_info(IOAccelDeviceInfoReturnData*)` `+0xD52C` | （创建链步 7，失败被容忍） | 可选 |
| `8` | 2 | 0 | 0x10 = 16 B out | `get_next_gid_group(IOAccelDeviceGIDGroupData*)` `+0xD5AC` | — | 不必须 |
| `9` | 3 `StructI_StructO` | **0x10 = 16 B in** | `VARIABLE` | `set_api_property(IOAccelDeviceAPIProperty*)` `+0xD5F0` | （创建链步 2，返回值被丢弃） | 可选 |

**三条重要修正/补充**，相对 `20-OBJC-DEVICE.md` §7.5：

1. 该节把 selector `5` 记作 `IOAccelDeviceGetNextGlobalTraceID` 对应 `8`。
   内核侧的事实是：**`5` = `get_next_global_object_id`（8 字节），
   `6` = `get_current_trace_filter`（8 字节），`7` = `get_device_info`（24 字节），
   `8` = `get_next_gid_group`（16 字节）**。用户态包装函数名与内核方法名不是
   一一对应的，以内核为准。`KNOWN`
2. selector `3` 需要 **1 个 scalar 输入**（surface id），`4` 需要 **2 个 scalar
   输入**。不是纯 struct 接口。`KNOWN`
3. **一个重要的好消息**：`sDeviceMethods` 全表的 `object` 字段都是 NULL，
   `IOUserClient` 会把 target 设成 user client 自身。因为整表是家族提供的，
   本项目**不需要提供任何 selector 实现** —— 需要提供的是它们读取的**数据源**。

### 3.3 selector 0 与 selector 2 返回结构的逐字段定义（问题 B.7，核心交付物）

#### 3.3.1 selector 0：`IOAccelDeviceConfigData`，64 字节

`KNOWN`。`IOAccelDevice2::get_config`（`S-IOAF2 +0xD080`）。令
`A = this->fAccel`（`uc+0x108`），`cfg = A + 0xC88`（= `IOAccelConfig`，§3.3.3），
`out` = 输出缓冲：

| 偏移 | 宽度 | 字段名（取自 `20-OBJC-DEVICE.md` §7.4 的消费侧） | 内核侧表达式 | 指令 RVA |
|---|---|---|---|---|
| `+0x00` | u32 | `configBits` | `(cfg->flags & 0xFFFF) \| ((cfg->flags >> 9) & 0x1000)` | `+0xD0E5`..`+0xD0F8` |
| `+0x04` | u32 | `deviceBits` | `cfg->deviceBits`（`A+0xC98` = `cfg+0x10`） | `+0xD0FA` |
| `+0x08` | u64 | `textureRam` | `A->totalTextureMemory()`（vptr `+0x868`）= `cfg->videoRam`（`cfg+0x20`） | `+0xD10E`..`+0xD117` |
| `+0x10` | u64 | `videoRam` | `cfg->videoRam`（`A+0xCA8` = `cfg+0x20`） | `+0xD103` |
| `+0x18` | u32 | `accelID` | `A->fAccelID`（`A+0x178`，由 `IOSurfaceRoot` 分配，见 §2.3.1 第 17 行） | `+0xD122` |
| `+0x1C` | u32 | 填充 | **未写入** | — |
| `+0x20` | u64 | `sharedMemorySize` | `A->getMaxWiredSysMemorySize()`（vptr `+0x990`）= `A+0x348` | `+0xD12B`..`+0xD134` |
| `+0x28` | u64 | `maxResourceSize` | `A->getMaxResourceSize()`（vptr `+0xA90`），**有 1 GiB 硬下限** | `+0xD13F`..`+0xD148` |
| `+0x30` | u64 | `peerGroupID` | `cfg->peerGroupID`（`A+0xD10` = `cfg+0x88`） | `+0xD153` |
| `+0x38` | u32 | `peerIndex` | `(u16)*(A+0xD18)` = `cfg+0x90`，零扩展 | `+0xD15E` |
| `+0x3C` | u32 | `peerCount` | `(u16)*(A+0xD1A)` = `cfg+0x92`，零扩展 | `+0xD169` |

返回 `0`（`kIOReturnSuccess`），无失败路径。`KNOWN`

**与用户态的交叉确证**：`20-OBJC-DEVICE.md` §7.4 的 11 行偏移表与本表**逐项一致**
（`+0x00`/`+0x04`/`+0x08`/`+0x10`/`+0x18`/`+0x1C`/`+0x20`/`+0x28`/`+0x30`/`+0x38`/`+0x3C`）。
两侧独立导出、完全吻合，这个结构可以认为是**完全解出**的。`KNOWN`

**`+0x1C` 从未被内核写入**。`get_config` 不先清零输出缓冲。虽然用户态把它当填充
不读（`20-OBJC-DEVICE.md` §7.4），本项目若自己实现该 selector 应显式清零整个结构。

**`configBits` 的位语义（本文新增）** `KNOWN`：

```
configBits[15:0]  = cfg->flags[15:0]           // 原样透传
configBits[12]    = cfg->flags[21]             // (flags >> 9) & 0x1000
```

`cfg->flags` bit 21 在 `IOGraphicsAccelerator2::start` 内还另有两处作用
（`S-IOAF2 +0x3A752` 内）：置位时 `cfg+0x64 |= 0x0A`，且 `debugBits &= ~4`。
按 `20-OBJC-DEVICE.md` §4.4，`configBits` bit 12 的用户态语义是
"统一内存 / 无独立显存"。

**本项目的取值建议** `INFERRED`：`cfg->flags = 0x00200000`（只置 bit 21）
⇒ `configBits = 0x1000`，于是 `_MTLDevice` 走统一内存分支，`_videoRam` 与
`_textureRam` 被清零，`_sharedMemorySize` 保留。
对照：**APV 自己填 `cfg->flags = 0x00480000`（bit 19 + bit 22），bit 21 不置，
所以 APV 报告的 `configBits == 0`，不是统一内存。** 它有宿主显存，我们没有。

#### 3.3.2 selector 2：`IOAccelDeviceEventMachineData`，600 字节

`KNOWN`。`IOAccelDevice2::get_event_machine`（`S-IOAF2 +0xD1DC`）。令
`uc` = user client，`A = uc+0x108`，`em = A+0x380`（event machine），`out` = 输出：

| 偏移 | 宽度 | 内核侧表达式 | 指令 RVA | 语义 |
|---|---|---|---|---|
| `+0x00` | u64 | `uc->fStampMap->getAddress() + (u32)uc->fStampOffset` <br>（`uc+0x120` 的 `IOMemoryMap`，`uc+0x128` 的偏移） | `+0xD234`..`+0xD24D` | **事件戳计数器区在调用进程地址空间中的基地址** |
| `+0x08` | u32 | `cfg+0x58`（`A+0xCE0`） | `+0xD257` | 用户态：`dev+52`，非 0 则 resource 的 clientShared 私有区 = `resource[9]+264` |
| `+0x0C` | u32 | `cfg+0x5C`（`A+0xCE4`） | `+0xD261` | 用户态：`dev+56`，第二块私有区 |
| `+0x10` | u32 | `cfg+0x60`（`A+0xCE8`） | `+0xD26B` | 用户态：`dev+60`，**厂商 per-resource 私有数据字节数** |
| `+0x14` | s32 | `em->getNumStamps()`（`IOAccelEventMachine2` vptr `+0x128`） | `+0xD2A0`..`+0xD2B0` | **计数器通道数 count** |
| `+0x18` | 64 B | `memcpy(out+0x18, em->getClientTestEventFunc(), 0x40)` <br>（`IOAccelEventMachineFast2` vptr `+0x120`） | `+0xD275`..`+0xD294` | **`20-OBJC-DEVICE.md` §7.3 标为"未被读取"的那 64 字节。内核侧确实填了：它是 event machine 导出给客户端的 "test event" 内联代码/数据块。** 用户态 `IOAccelerator.framework` 不读它 |
| `+0x58` | u32 × count | `for (i=0;i<count;i++) out[0x58+4*i] = em->getStampOffset(i)`（vptr `+0x138`） | `+0xD2BB`..`+0xD2E4` | `uint32 offsets[128]`，仅前 count 项被写 |

返回 `0`，无失败路径（但见下文的空指针风险）。`KNOWN`

总长 `0x18 + 0x40 + 128*4 = 0x258 = 600` ✓ 与 `count1` 吻合。

**与用户态的交叉确证**：`20-OBJC-DEVICE.md` §7.3 的 7 行偏移表与本表逐项一致，
并且本文补齐了该节的 `+0x18..+0x57`。这个结构也可以认为是**完全解出**的。`KNOWN`

**但这里有两个 `20-OBJC-DEVICE.md` 没发现的硬依赖**：

**(a) `uc+0x120` 必须非空，否则 type-5 根本建不起来。** `KNOWN`

`IOAccelDevice2::deviceStart`（`S-IOAF2 +0xD66A`，由 `IOAccelDevice2::start` 经
vptr `+0x960` 调用）：

```c
bool IOAccelDevice2::deviceStart(void)
{
    this->fStampMD /*+0x118*/ = fAccel->getStampMemory(&this->fStampOffset /*+0x128*/);
                                                       // vptr +0x878 = 纯虚 getStampMemory
    if (!this->fStampMD) return false;                 // ← 失败点
    this->fStampMD->retain();
    this->fStampMap /*+0x120*/ =
        this->fStampMD->createMappingInTask(this->fTask /*+0xE8*/, 0,
                                            0x04000001 /* kIOMapAnywhere | 0x04000000 */, 0, 0);
    if (!this->fStampMap) { fStampMD->release(); fStampMD = NULL; return false; }   // ← 失败点
    this->fGlobalObjectID /*+0xF8*/ = OSIncrementAtomic64(&__globalObjectIDCounter) + 1;
    fAccel->fDeviceList.addDevice(this);
    return true;
}
```

`deviceStart` 返回 false ⇒ `IOAccelDevice2::start` 返回 false ⇒
`newUserClient` 返回 `0xE00002C9` ⇒ `IOServiceOpen(svc, task, 5, &c)` 失败 ⇒
`IOAccelDeviceCreateWithAPIProperty` 返回 NULL ⇒
`-[MTLIOAccelDevice initWithAcceleratorPort:]` 返回 nil ⇒
**`MTLCopyAllDevices()` 看不到设备**。

所以：**`getStampMemory()` 必须返回一个真实的、可映射进调用进程的
`IOMemoryDescriptor`。** 最小实现：一页 `IOBufferMemoryDescriptor`，
`*outOffset = 0`。对照 APV（`S-APV +0x280E`）：

```c
IOMemoryDescriptor *AppleParavirtAccelerator::getStampMemory(uint32_t *off)
{
    if (off) *off = 0;
    return this->fStampMD /*+0x6F8*/;
}
```

**(b) `A+0x380` 的 event machine 必须存在，否则 selector 2 空指针解引用。** `KNOWN`

`get_event_machine` 对 `em` 无 NULL 检查，直接 `em->vt[...]()` 三次。该 ivar 由
家族在某处用 `newEventMachine()`（纯虚，vptr `+0x888`）填充；**填充点已查清（§7.2）：
`IOGraphicsAccelerator2::createEventMachine()`（vptr `+0x880`，i 272，`S-IOAF2 +0x3E82E`）**，
它在 `start` 里于 `S-IOAF2 +0x3B098` 被调用，返回值直接写进 `accel+0x380`；
返回 NULL ⇒ 打 `"%s: failed to create event machine\n"` 且 `start` 失败。
所以**不能不实现 `newEventMachine`**。最小实现：
`return new IOAccelEventMachineFast2(...)`，随后家族会调
`IOAccelEventMachineFast2::init(IOGraphicsAccelerator2*, uint32_t, int32_t)`
（`S-IOAF2`，vptr `+0x118`）。

**count = 0 的捷径仍然成立**：`20-OBJC-DEVICE.md` §7.3.1 说用户态在
`count == 0` 时跳过整个解引用循环 —— 内核侧相应地也不写 `offsets[]`。所以
"event machine 存在但报告 0 个 stamp" 是一个合法且最省事的组合。`INFERRED`

#### 3.3.3 数据源：`IOAccelConfig`（accel `+0xC88`）

这是本节真正的实现要点：**selector 0 与 selector 2 的大部分字段不是 user client
造的，而是子类在 `populateAccelConfig()` 里填的。** `KNOWN`

两段代码确定了这个结构：
`IOGraphicsAccelerator2::initializeConfigStructure`（`S-IOAF2 +0x3A36A`，
在 `start` 中于 `S-IOAF2 +0x3ACCF` 被调用）给默认值；
`AppleParavirtAccelerator::populateAccelConfig`（`S-APV +0x28F4`）覆盖。

| cfg 偏移 | accel 偏移 | 宽度 | 默认值 | APV 值 | 用途 / 证据 |
|---|---|---|---|---|---|
| `+0x00` | `0xC88` | u64 | `NULL` | `"Apple Paravirt Accelerator"` | `accelName`。`validateConfigStructure` 要求非 NULL；`triage` 打印它 |
| `+0x08` | `0xC90` | u32 | 0 | `0x00480000` | **`flags`** → selector 0 `configBits`（§3.3.1）。bit 21 = 统一内存 |
| `+0x0C` | `0xC94` | u32 | 0 | `7` | **`accelCaps`**：全件唯一读取点 `S-IOAF2 +0x3BDC2`，取值后立刻 `setProperty("AccelCaps", v, 32)`（`start` 内，紧跟 `setProperty("IOAccelRevision", 2, 32)`）。即它只是一个**透给用户态的能力位图**，内核侧不解释 |
| `+0x10` | `0xC98` | u32 | 0 | 0 | → selector 0 `deviceBits` |
| `+0x14` | `0xC9C` | u32 | 0 | 0 | **`debugBits`**；boot-arg `ioaccel_debug` 写这里；bit3 启用客户端硬上限；bit1/bit0/bit2 由 `panic_on_gpu_hang` / `spin_wait_for_gpu` / `gpu_no_zero_fill` 置 |
| `+0x18` | `0xCA0` | u32 | **1** | `0x20` = 32 | **`numEventChannels`**；`validateConfigStructure` 要求 ≥ 1 |
| `+0x20` | `0xCA8` | u64 | 0 | `0x40000000` = 1 GiB | **`videoRam`** → selector 0 `videoRam` **与** `textureRam`（同一字段，经 `totalTextureMemory()`）；也参与 `getMaxResourceSize` 的 3/4 上限 |
| `+0x28` | `0xCB0` | u32 | 1 | `8` | **framebuffer / display pipe 条数上限**。唯一读取点 `S-IOAF2 +0xE041`（`IOAccelDisplayMachine::found_framebuffer`）：`if (fbCount >= cfg[0x28]) 拒绝`，否则 `accel->vtable[0x908](fb)` 建一条 pipe 并存入 `displayMachine + 0x88 + 8*fbCount` |
| `+0x2C` | `0xCB4` | u32 | 1 | `0x100000` = 1 MiB | **`S-IOAF2` 内无任何读取点**（全件按位移扫描；它与 `+0x28` 由 `initializeConfigStructure +0x3A39F` 的同一条 qword 存储一起写入默认值 `1/1`）。消费者不在本家族内 |
| `+0x30` | `0xCB8` | u16 | 4096 | `0x4000` | 传给 `IOSurfaceRoot` 注册调用（`start` 第 16 步）第 5 参 |
| `+0x32` | `0xCBA` | u16 | 4096 | `0x4000` | 同上第 6 参 |
| `+0x34` | `0xCBC` | u32 | `0x4000` | 默认 | **`sidebandBufferSizeMin`**，必须页对齐 |
| `+0x38` | `0xCC0` | u32 | `0x40000` | 默认 | **`sidebandBufferSizeMax`**，必须页对齐 |
| `+0x3C` | `0xCC4` | u32 | `0x200` | 默认 | **`S-IOAF2` 内无读取点**（与 `+0x40` 由 `+0x3A3D3` 的同一条 qword 存储写入 `0x200 / 0x10000`） |
| `+0x40` | `0xCC8` | u32 | `0x10000` | 默认 | 同上，**无读取点** |
| `+0x44` | `0xCCC` | u8 | 1 | 默认 | **"用 CPU 做 page-off" 开关**。唯一读取点 `S-IOAF2 +0x25598`（`IOAccelResource2::pageoffIfNeeded(uint,uint)`）：非 0 ⇒ 走 `IOAccelResource2::pageoffWithCPU()` 并标记已换出；为 0 ⇒ 走下面的 `flags & 0x40` 分支 |
| `+0x45` | `0xCCD` | u8 | 0 | 默认 | **resource 创建时的额外 shared 回调开关**。两个读取点 `S-IOAF2 +0x21F6C`（`IOAccelResource2::newResourceWithOptions`）与 `+0x22810`（`…newResourceWithIOSurfaceDeviceCache`）：非 0 且 `options/flags & 0x40 == 0` ⇒ 调 `shared->vtable[0x148]()` |
| `+0x47` | `0xCCF` | u8 | 0 | **1** | **`displayPipeSupported`**：`newUserClient` 的 type-4 闸门（§3.1）。对应 plist 的 `IOAccelDisplayPipeCapabilities.DisplayPipeSupported` |
| `+0x48` | `0xCD0` | u32 | `0xC` | 默认 | **`S-IOAF2` 内无读取点**（与 `+0x4C` 由 `+0x3A3F2` 的同一条 qword 存储写入 `0xC / 3`） |
| `+0x4C` | `0xCD4` | u32 | 3 | 默认 | `IOSurfaceRoot` 注册第 2 参 |
| `+0x50` | `0xCD8` | u32 | 3 | 默认 | `IOSurfaceRoot` 注册第 3 参 |
| `+0x54` | `0xCDC` | u32 | `0x7FFF` | 默认 | `IOSurfaceRoot` 注册第 4 参 |
| `+0x58` | `0xCE0` | u32 | 0 | 默认 0 | → selector 2 `+0x08` |
| `+0x5C` | `0xCE4` | u32 | 0 | **4** | → selector 2 `+0x0C` |
| `+0x60` | `0xCE8` | u32 | 0 | 默认 0 | → selector 2 `+0x10`（厂商 per-resource 私有字节数） |
| `+0x64` | `0xCEC` | u32 | 0 | **2** | bit6 置位则 `start` 要求 `createDMACommandPool()` 成功；`flags` bit21 置位时家族会 `\|= 0x0A` |
| `+0x68` | `0xCF0` | u32 | **5** | `0xA` | **`waitForGPUTimeoutSeconds`**；`validateConfigStructure` 要求非 0 |
| `+0x6C` | `0xCF4` | u32 | 1 | 1 | **每个 fence 槽的 64 字节块数**。`S-IOAF2 +0x2A864`（`IOAccelShared2::allocate_fence_memory(uint64 count, uint64*)`）：分配长度 `= cfg[0x6C] * count`（符号溢出会被判掉并返回 `0xE00002BC`）；`+0x29880`（`IOAccelShared2::free`）：`IOFree(ptr, (cfg[0x6C] * shared[0x70]) << 6)` —— `<< 6` 即单位是 64 字节 |
| `+0x70` | `0xCF8` | u32 | `0x100` = 256 | 默认 | per-PID 客户端**软**上限（§3.1） |
| `+0x74` | `0xCFC` | u32 | `0x200` = 512 | 默认 | per-PID 客户端**硬**上限（§3.1） |
| `+0x78` | `0xD00` | u32 | `0x186A0` = 100000 | 默认 | **per-client resource 条数"告警"线**。`S-IOAF2 +0x2B93C`（`IOAccelSharedUserClient2::new_resource`）：`IOAccelResourceList::getCount() > cfg[0x78]` ⇒ 按一个哈希节流条件打日志 `"%s: PID %d likely leaking IOAccelResource2…"`，**不失败** |
| `+0x7C` | `0xD04` | u32 | `0x30D40` = 200000 | 默认 | **per-client resource 条数"刹车"线**。同一函数 `+0x2B99D`：数量再超过 `cfg[0x7C]` ⇒ 调 stub `0x1002A(0x3E80)`（延时/让出，16 秒级）后才继续。仍不返回错误，只是强制减速 |
| `+0x80` | `0xD08` | u32 | `0x10` | 默认 | **command buffer 的 segment 批大小**。`S-IOAF2 +0x45DA0`（`IOAccelCommandQueue::coalesceSegment`）：当已累积 segment 数 `== cfg[0x80]` 就 `processAndSubmitCoalescedSegments`；`+0x45ED2`（`processCommandBuffer`）：`cfg[0x80] >= 0x11` 时按 `cfg[0x80] * 32` 字节另行 `kalloc` 一张 segment 表，否则用栈上的 |
| `+0x88` | `0xD10` | u64 | 0 | 0 | → selector 0 `peerGroupID` |
| `+0x90` | `0xD18` | u16 | 0 | 0 | → selector 0 `peerIndex` |
| `+0x92` | `0xD1A` | u16 | 0 | 0 | → selector 0 `peerCount` |
| `+0x94` | `0xD1C` | u32 | **128** | 默认 | **`IODMACommand` 池的条数**。`S-IOAF2 +0x3C019`/`+0x3C07A`（`createDMACommandPool`）：先建 1 个，`cfg[0x94] >= 2` 时循环补到 `cfg[0x94]` 个，池计数在 `accel+0xDA0`；`+0x43347`（`returnDMACommand`）：仅当 `accel+0xDA0 < cfg[0x94]` 才把命令还池，否则直接释放。只有 `cfg+0x64` bit6 置位时这条路径才被 `start` 走到 |
| `+0x98`..`+0xF0` | `0xD20`..`0xD78` | — | 0 | 默认 | `initializeConfigStructure` 逐 qword 清零 |

**`validateConfigStructure`（`S-IOAF2 +0x3A4BC`）的四条不变量**：`accelName != NULL`、
`numEventChannels >= 1`、`sidebandBufferSizeMin` 页对齐、`sidebandBufferSizeMax`
页对齐、`waitForGPUTimeoutSeconds != 0`。

**重要限定**：全件扫描 `E8 rel32` 直接调用，**`validateConfigStructure` 没有任何
调用点**（`initializeConfigStructure` 的唯一调用点是 `S-IOAF2 +0x3ACCF`，在 `start`
内）。所以它是死代码，`start` **不**对这些不变量设闸。`KNOWN` 本项目仍应满足
它们 —— 它们是家族自己写下的意图声明，也是未来版本可能启用的闸。`INFERRED`

#### 3.3.4 本项目 `populateAccelConfig` 的最小实现

`INFERRED`（每个取值的机制都 `KNOWN`，取值选择未实测）

```c
void LPAccelerator::populateAccelConfig(IOAccelConfig *cfg)
{
    // initializeConfigStructure() 已经跑过，这里只覆盖必要项
    *(const char **)((char *)cfg + 0x00) = "Lavapipe Software Accelerator";
    *(uint32_t   *)((char *)cfg + 0x08) = 0x00200000;   // flags: bit21 -> configBits bit12 统一内存
                                                        // 下一步应改 0x00280000，加 bit19 关硬件 GPU
                                                        // 看门狗（§7.4，APV 也置这一位）
    *(uint32_t   *)((char *)cfg + 0x10) = 0;            // deviceBits
    *(uint32_t   *)((char *)cfg + 0x18) = 1;            // numEventChannels（>=1）
    *(uint64_t   *)((char *)cfg + 0x20) = 0;            // videoRam = 0（统一内存；见下）
    *(uint8_t    *)((char *)cfg + 0x47) = 0;            // 不支持 display pipe（type-4 返回 unsupported）
    *(uint32_t   *)((char *)cfg + 0x58) = 0;
    *(uint32_t   *)((char *)cfg + 0x5C) = 0;
    *(uint32_t   *)((char *)cfg + 0x60) = 0;            // 无厂商 per-resource 私有数据
    *(uint32_t   *)((char *)cfg + 0x68) = 10;           // waitForGPUTimeoutSeconds
    *(uint64_t   *)((char *)cfg + 0x88) = 0;            // peerGroupID = 0（单卡）
    // +0x90 / +0x92 保持 0
}
```

注意 `videoRam = 0` 的连带效果，三者都是**期望**的：
① selector 0 的 `textureRam` 与 `videoRam` 都变 0，与 `configBits` bit12
（统一内存）语义一致（`20-OBJC-DEVICE.md` §4.4）；
② `getMaxResourceSize()` 的 3/4 上限分支不触发，于是返回 1 GiB 硬下限，
`maxBufferLength = 1 GiB > 0`，满足 `20-OBJC-DEVICE.md` §5.2.1 的断言；
③ `20-OBJC-DEVICE.md` §4.4 指出 `_sharedMemorySize` 的 clamp 条件是
`_videoRam != 0`，所以 clamp 不触发，`sharedMemorySize` 保持我们给的值。

`sharedMemorySize` 不在 `fConfig` 里，要通过**覆写 `getMaxWiredSysMemorySize()`**
（vptr `+0x990`，i 306）给。

**Apple 自己的默认策略已查清（§7.1），建议直接照抄而不是自创：**

```c
uint64_t LPAccelerator::getMaxWiredSysMemorySize() {
    uint64_t mem = <hw.memsize>;                       // 见 §7.1；取不到时 Apple 用 0x20000000
    uint64_t v = mem / 3;
    if (v < 0x4000000) v = 0x4000000;                  // 64 MiB 下限
    return round_page(v);
}
```

照抄的好处是 `getMaxSingleSysMemorySize()`（基类 = `3/4 × 本值`）与 `getMaxResourceSize()`
的比例关系保持与家族一致，不用再单独验证。`KNOWN`（Apple 策略）+ `INFERRED`（本项目照抄的选择）

### 3.4 type-6 `IOAccelSharedUserClient2` 的 selector 表（问题 B.8）

#### 3.4.1 分派机制与上界

`KNOWN`。同样是 legacy `IOExternalMethod` 表。
`IOAccelSharedUserClient2::getTargetAndMethodForIndex`（`S-IOAF2 +0x2DBEC`）：

```c
*target = this;
return (index < 0x15) ? &IOAccelSharedUserClient2::sSharedMethods[index] : NULL;
```

**selector 上界 0x15（`0`..`0x14`），共 21 个。** 表基址 `S-IOAF2 +0x77CB0`
（VA `0x14BDCCB0`），步长 48 字节。

#### 3.4.2 `sSharedMethods` 全表

`KNOWN`：

| sel | flags | count0 | count1 | 内核方法 | 用户态包装（`20-OBJC-DEVICE.md` §7.6） |
|---:|---|---|---|---|---|
| `0x00` | 3 | `VARIABLE` in | `VARIABLE` out | `new_resource(IOAccelNewResourceArgs*, IOAccelNewResourceReturnData*, uint64_t, uint32_t*)` | `IOAccelResourceCreate` |
| `0x01` | 0 | 1 scalar | 0 | `delete_resource(uint32_t)` | — |
| `0x02` | 4 | 0 | 8 B | `page_off_resource(IOAccelSharedPageoffResourceArgs*)` | — |
| `0x03` | 0 | 2 scalar | 0 | `finish_object_event(uint32_t, uint32_t)` | — |
| `0x04` | 0 | 2 scalar | 1 scalar | `set_resource_purgeable(uint32_t, eIOAccelResourcePurgeable, eIOAccelResourcePurgeable*)` | — |
| `0x05` | 0 | 1 scalar | 5 scalar | `get_surface_info(uint32_t, uint32_t*, …×4)` | — |
| `0x06` | 2 | 1 scalar | `VARIABLE` | `get_resource_info(uint32_t, IOAccelGetResourceInfoReturnData*, uint32_t*)` | — |
| `0x07` | 2 | 1 scalar | 0x10 = 16 B | `create_shmem(uint32_t, IOAccelDeviceShmemData*)` | `IOAccelSharedCreateDeviceShmem` |
| `0x08` | 0 | 1 scalar | 0 | `destroy_shmem(uint32_t)` | `…DestroyDeviceShmem` |
| `0x09` | 2 | 0 | 0x10 = 16 B | `get_shared_info(IOAccelSharedGetInfoReturnData*)` | `IOAccelSharedCreate` 步内，失败被容忍 |
| **`0x0A`** | 2 | 0 | **0x18 = 24 B** | **`setup_dirty_ring(IOAccelSharedSetupDirtyRingReturnData*)`** | **`IOAccelSharedSetupDirtyRing`，必须成功** |
| `0x0B` | 0 | 0 | 0 | `process_dirty_commands()` | `…FlushDirtyRing` / `WriteDirtyResourceCommand` |
| `0x0C` | 3 | 8 B in | 8 B out | `allocate_fence_memory(uint64_t*, uint64_t*)` | `IOAccelSharedAllocateFenceMemory` |
| `0x0D` | 3 | 8 B in | 0x18 = 24 B out | `create_mtlevent(uint64_t*, IOAccelCreateMTLEventResult*)` | `IOAccelMTLEvent` 创建 |
| `0x0E` | 0 | 1 scalar | 0 | `destroy_mtlevent(uint32_t)` | `IOAccelMTLEvent` 销毁 |
| `0x0F` | 2 | 0 | 0x30 = 48 B | `get_memory_data(IOAccelMemoryData*)` | `IOAccelSharedGetMemoryData` |
| `0x10` | 0 | 1 scalar | 0 | `disconnect_peer(uint32_t)` | `IOAccelSharedDisconnectPeer` |
| `0x11` | 3 | `VARIABLE` in | `VARIABLE` out | `set_resources_purgeable(const uint32_t*, eIOAccelResourcePurgeable, eIOAccelResourcePurgeable*, int)` | — |
| `0x12` | 3 | 0x10 = 16 B in | 8 B out | `get_resource_offset(uint64_t*, uint64_t*)` | `IOAccelResourceGetPhysicalOffset` |
| `0x13` | 2 | 0 | 8 B | `get_allocated_size(IOAccelAllocatedSize*)` | `IOAccelSharedGetAllocatedSize` |
| `0x14` | 3 | 0x10 = 16 B in | 0 | `set_resource_owner_identity(IOAccelResourceSetResourceOwnerIdentityData*)` | `IOAccelResourceSetOwnerIdentity` |

**与 `20-OBJC-DEVICE.md` §7.6 的差异**：该节把 `IOAccelResourceCreate` 记为
selector `0`、`IOAccelSharedCreate` 用 selector `9`、`SetupDirtyRing` 用 `0xA`，
这三条与内核侧**完全一致**。该节未列出 `0x02`、`0x04`、`0x05`、`0x06`、`0x08`、
`0x0B`、`0x11`，本表补齐。`KNOWN`

`sel 0x02` 的 `flags = 4` 不是标准的四个方向常量之一（0/1/2/3）。不要照抄，
本项目不实现该 selector。`KNOWN`（值），`BLOCKED`（语义，需 xnu 源码侧确认）

#### 3.4.3 `setup_dirty_ring` 的最小实现所需结构

按 `20-OBJC-DEVICE.md` §5.5.1，把 `supportLazyInitialization` 覆写为 `YES`
可以整条绕开 type-6；但该节的排期建议是第一版仍然实现它。内核侧要做的事如下。

`IOAccelSharedUserClient2::setup_dirty_ring`（`S-IOAF2 +0x2D032`）本体极短：

```c
IOReturn IOAccelSharedUserClient2::setup_dirty_ring(void *out /* 24 B */)
{
    acceleratorLock(fAccel); lock_busy(fAccel); fAccel->acceleratorDidLock("", 0);
    IOReturn r = this->fShared /*+0x100*/ ->getDirtyRingAddresses(
                     (uint64_t *)out + 0, (uint64_t *)out + 1, (uint64_t *)out + 2);
    fAccel->acceleratorWillUnlock("", 0); unlock_busy(fAccel); acceleratorUnlock(fAccel);
    return r;
}
```

**所以 24 字节结构是三个 u64**，由 `IOAccelShared2::getDirtyRingAddresses`
（`S-IOAF2 +0x2A51C`）填：

| 偏移 | 宽度 | 内容 |
|---|---|---|
| `+0x00` | u64 | 第一块 client-shared 区在调用进程中的地址（`IOAccelClientSharedMachine`（`fAccel->?+0x50`）的 id 0） |
| `+0x08` | u64 | 第二块 client-shared 区地址（同机器 `+0x90` 的 id 0） |
| `+0x10` | u64 | dirty ring 缓冲区在调用进程中的地址（`fRingMap->getAddress()`） |

首次调用时的懒初始化（全部 `KNOWN`）：

1. `mapClientSharedForId(machineA, 0, &fClientSharedA /*+0x38*/)`；
   `mapClientSharedForId(machineB, 0, &fClientSharedB /*+0x40*/)`。
   任一失败 → 返回 `0xE00002BD` `kIOReturnNoMemory`。
2. `fRingMD /*+0x48*/ = fAccel->createBufferMemoryDescriptorInTaskWithOptions(
   0, 0x10023, 0x4000, page_size)`（accel vptr `+0x918`）。
   即 **16 KiB** 缓冲。失败 → `kIOReturnNoMemory`。
3. `<stub 0x111FA>(fRingMD, fTask /*+0x80*/, 4, 0)`；
   `fRingMap /*+0x58*/ = fRingMD->createMappingInTask(fTask, 0, 1 /*kIOMapAnywhere*/, 0, 0)`。
4. `fRingKernelMap /*+0x50*/ = fRingMD->map(1)`；
   `fRingKernelAddr /*+0x60*/ = fRingKernelMap->getAddress()`。
5. **`*(uint64_t *)fClientSharedA = 0x0000040000000001`**，即
   `u32 @+0 = 1`、`u32 @+4 = 0x400 = 1024`；
   **`*(uint32_t *)fClientSharedB = 1`**。

第 5 步解释了 `20-OBJC-DEVICE.md` §7.6 的 "`count - 1` 被存为环形掩码，
因此 count 必须是 2 的幂"：**ring 容量就是 1024**（2 的幂 ✓），而
`{u32 head=1, u32 count=1024}` 这一对**位于 client-shared 区里**，不是位于
selector 0xA 返回的 24 字节里。该节把两层弄混了，以本节为准。`KNOWN`

**最小实现路线** `INFERRED`：如果走 `supportLazyInitialization = YES`，内核侧
这一整节都不需要。如果走基类路径，由于 `IOAccelShared2`、
`IOAccelClientSharedMachine`、`createBufferMemoryDescriptorInTaskWithOptions`
全部是家族实现，本项目只需：
① `newShared()`（**非纯虚**，基类返回 `new IOAccelShared2`，可不覆写）；
② `newSharedUserClient()`（非纯虚，同上）；
③ `createUserGPUTask()` / `createKernelGPUTask()`（纯虚，必须实现）。
`getDirtyRingAddresses` 不需要我们写一行。

### 3.5 restricted / 非 restricted 连接（问题 B.9）

**结论：`IOAcceleratorFamily2` 不区分 restricted 与非 restricted 连接，没有任何
selector 因连接类别被禁。** `KNOWN`

证据：

1. `S-IOAF2` 全件字符串扫描：没有任何含 `restrict` / `privile` / `entitle` /
   `sandbox` 的字符串。
2. `IOGraphicsAccelerator2::newUserClient` 的全部前置检查只有：
   `task != NULL`、per-PID 客户端计数（§3.1 第 4 步）。**没有
   `clientHasPrivilege`、没有 `copyClientEntitlement`、没有 `IOTaskHasEntitlement`。**
3. `IOAccelDevice2::init(OSDictionary*, task_t)`（`S-IOAF2 +0xCBEA`）只做
   `IOUserClient::init(dict)` + 建锁 + 记 `task` 与 PID，没有授权判定。
4. type-5 的唯一动态闸是 `IOAccelDevice2::externalMethod` 的终止位检查
   （`uc+0x112` bit0），命中返回 `0xE00002D7` `kIOReturnOffline`（§3.2.1）。
   这是生命周期闸，不是权限闸。

对照：**授权检查确实存在，但在 AGDC 侧而不是 accelerator 侧** ——
`AppleGraphicsDeviceControlClient::authorizeTask(AppleGraphicsDeviceControl*, task*, uint32_t)`
（`S-AGDC +0x7FE`）与 `AppleGraphicsDeviceControl::newUserClient`
（`S-AGDC +0x2CBE`）。`AppleGraphicsDeviceControlClient` 是 AGDC 自己的
user client，与 `IOAccelDevice2` / `IOAccelSharedUserClient2` 无关。`KNOWN`

**对本项目的含义**：按 §2.3.3 的方案（不继承 AGDC）就完全不涉及授权。研发期
SIP/AMFI 关闭（`00-OVERVIEW.md` §2.4）亦无影响。进程侧真正的门是 sandbox 对
`/Library/GPUBundles` 的 trust gate，那属于分册 `70`。

## 4. C. 命令与资源的边界

本节按任务要求只定边界，不求穷尽；细节留给后续分册。

### 4.1 `IOAccelResource2` / `IOAccelCommandQueue` 的最小对象模型（问题 C.10）

#### 4.1.1 resource（走 type-6）

`KNOWN`（selector 映射），`INFERRED`（流程归纳）：

| 阶段 | 入口 | 备注 |
|---|---|---|
| 创建 | type-6 selector `0x00` `new_resource` | 变长 in / 变长 out。out 结构大小 = `fConfig+0x60 + 88`（`20-OBJC-DEVICE.md` §7.3 已记录用户态侧的 `size + 88`） |
| 绑定到 channel | `IOAccelResource2::addToChannel` / `removeFromChannel`（vptr `+0x198`，APV 覆写） | 内核内部，无 selector |
| 分页 | selector `0x02` `page_off_resource`；内核侧 `pageon`/`pageoff`（vptr `+0x1B8` / `+0x1C8`） | — |
| 完成通知 | selector `0x03` `finish_object_event`；用户态 `IOAccelResourceTestEvent` 走 **commpage + 事件戳**，不走 selector | 这是 selector 2（event machine）那块共享页的用途 |
| 销毁 | type-6 selector `0x01` `delete_resource` | — |

`IOAccelResource2` 的纯虚（必须覆写，7 个）`KNOWN`，由
`__ZTV16IOAccelResource2` 与 `__ZTV21AppleParavirtResource` 逐槽比对得出：

| vptr 偏移 | i | 方法 |
|---|---|---|
| `0x1D0` | 58 | `rebuildPagingBuffer()` |
| `0x1E0` | 60 | `getLevelOffset(uint8_t, uint8_t, int*)` |
| `0x1E8` | 61 | `getBackingLevelOffset(uint8_t, uint8_t, int*)` |
| `0x1F0` | 62 | `calculateIOSurfaceDeviceCacheVRAMBytes(uint64_t*, uint64_t*)` |
| `0x1F8` | 63 | `addToAperture()` |
| `0x200` | 64 | `removeFromAperture()` |
| `0x208` | 65 | `getApertureMemoryDescriptor(uint64_t*)` |

APV 另外覆写（非纯虚）：`free`(18)、`initialize`(40)、`prepare`(46)、
`complete`(47)、`removeFromChannel`(51)、`pageon`(55)、`pageoff`(57)、
`dirtyFaceLevels`(66)、`dirtyBufferRange`(67)。`KNOWN`

#### 4.1.2 command queue（走 type-8）

`KNOWN`。`IOAccelCommandQueue : IOAccelSubmitter2`，并且**它用的是现代
`IOExternalMethodDispatch` 表，不是 legacy 表**。表
`IOAccelCommandQueue::sCommandQueueMethods` 在 `S-IOAF2 +0x7C770`
（VA `0x14BE1770`），步长 **24 字节**，结构
`{ IOExternalMethodAction fn; u32 scalarIn; u32 structIn; u32 scalarOut; u32 structOut; }`，
共 **6 条**：

| sel | fn | scalarIn | structIn | scalarOut | structOut |
|---:|---|---|---|---|---|
| `0` | `s_set_notification_port` | 0 | 0 | 0 | 0 |
| `1` | `s_submit_command_buffers` | 0 | `VARIABLE` | 0 | 0 |
| `2` | `s_set_priority_and_background` | 0 | 0x0C = 12 | 0 | 0 |
| `3` | `s_get_command_queue_info` | 0 | 0 | 0 | 0x08 |
| `4` | `s_set_quality_of_service` | 0 | 0x04 | 0 | 0 |
| `5` | `s_set_get_info` | 0 | 0x404 | 0 | 0x08 |

`20-OBJC-DEVICE.md` §7.6 末尾记的
"`IOAccelCommandQueueCreateWithQoS` 额外做 `IOConnectAddClient(cmdQueueConnect, sharedConnect)`"
与此一致：type-8 client 要接受 type-6 client 作为关联客户端。`KNOWN`

APV 覆写的 queue 方法只有三个（非纯虚）：`commandQueueStart`(316)、
`processSegmentKernelCommand`(321)、`parseSegmentList`(326)。`KNOWN`

### 4.2 不实现 FIFO 时，内核侧的最少工作量（问题 C.11）

`00-OVERVIEW.md` §4.3 已定下"不实现 APV 的 FIFO 命令流"。渲染在用户态
Lavapipe 完成，提交路径不经内核。那么内核侧的分界线如下。

#### 4.2.1 必须真做（否则 `MTLCopyAllDevices` 看不到设备）

`KNOWN`，每一条都对应 §2.3.1 / §3.3 里一个明确的失败点：

1. **personality 把 `MetalPluginName` / `MetalPluginClassName` 发布到 service 上**
   （§2.2.3）。
2. **`populateAccelConfig()`**：至少 `accelName`、`flags`、`numEventChannels >= 1`、
   `waitForGPUTimeoutSeconds != 0`，以及 selector 0 / 2 要用到的那几项（§3.3.4）。
3. **`configureDevice()` 返回 true**。可以是空实现。
4. **`getStampMemory()` 返回真实可映射的 `IOMemoryDescriptor`**（§3.3.2(a)）。
   一页 `IOBufferMemoryDescriptor` 即可。
5. **`newEventMachine()` 返回真实对象**（§3.3.2(b)）。可以报告 0 个 stamp。
6. **`createUserGPUTask()` / `createKernelGPUTask()` 返回真实 `IOAccelTask`**。
   `IOAccelTask::init(IOGraphicsAccelerator2*, uint32_t, IORangeAllocator**)` 是
   家族实现，直接用。
7. **`newSysMemory()` / `newVidMemory()` / `newMemoryMap()` / `newResource()`
   返回家族基类对象**（`new IOAccelSysMemory` 等）。这几个在任何内存路径上都会
   被调用，返回 NULL 会崩。
8. **`IOSurface.kext` 可用**（`IOSurfaceRoot` 存在）。这不是我们写代码，是依赖声明
   与加载顺序。
9. **`teardownDevice()`、`stop()`** 要能安全走完，否则卸载 kext 直接 panic
   （研发期会频繁卸载重装）。

#### 4.2.2 可以返回成功但实际为空操作

`INFERRED`（每条都有 APV 或家族侧的先例，见括号）：

| 项 | 做法 | 先例 |
|---|---|---|
| `configureDevice` / `teardownDevice` | `return true` / `{}` | 无 PCI 可配 |
| `newGLContext` / `newCLContext` / `newSurface` | **`return NULL`** | APV 自己就是 `return 0`（§2.4.1 注 1） |
| `new2DContext` / `newVideoContext` / `newDisplayMachine` | 可 `return NULL`（代价：type-2 / type-4 client 建不起来） | 同上模式；type-2 是 OpenGL/QuartzGL 路径，Metal 不用 |
| `getStampMemory` 的页内容 | 全零即可；若 event machine 报 0 个 stamp，用户态根本不读 | `20-OBJC-DEVICE.md` §7.3.1 的 count=0 捷径 |
| selector 2 的 `offsets[]` | count = 0 时一项都不写 | 同上 |
| selector 1 `get_name` | 家族实现已够（从 `fConfig.accelName` / `fModelName` 取）；或在 ObjC 侧覆写 `-name` | `20-OBJC-DEVICE.md` §7.5 |
| selector 3 / 4 / 5 / 6 / 8 | 不碰，家族实现照跑 | — |
| type-8 command queue | 不覆写 `newCommandQueue`，但**ObjC 侧覆写 `newCommandQueue`** 使其根本不开 type-8 连接 | `20-OBJC-DEVICE.md` §7.1 "不必须（覆写 `newCommandQueue`）" |
| type-6 的 resource 工厂 | ObjC 侧覆写全部 resource 工厂后 selector `0x00` 不可达 | `20-OBJC-DEVICE.md` §7.3.1 |
| FIFO / channel / doorbell / MMIO | **一行不写**。APV 的 `setupMMIO` / `setupVersion` / `setupRoot` / `setupFIFO` / `setupChannels` / `writeFifo` / `handleFaultInterrupt` 全部是 APV 自有方法，不是家族要求 | §2.1.3 |
| 中断 | 不注册。`setupInterrupts` 是 APV 自有方法 | §2.1.3 |

#### 4.2.3 用户态拿到的 handle 实际是什么

`KNOWN`：

- **queue handle**：若 ObjC 侧覆写 `newCommandQueue`，`MTLCommandQueue` 完全是
  用户态对象，内核里没有对应物。无需任何内核支持。
- **resource handle**：若 ObjC 侧覆写 resource 工厂（`20-OBJC-DEVICE.md` §8），
  `MTLBuffer` / `MTLTexture` 的后备存储由我们在用户态分配（最终是 IOSurface 或
  匿名内存，见分册 `41`），内核里也没有 `IOAccelResource2`。
- 内核里**唯一真实存在的对象**是：accelerator service、type-5 `IOAccelDevice2`、
  事件戳页、（若不走 lazy-init 捷径）type-6 `IOAccelSharedUserClient2` +
  `IOAccelShared2` + 16 KiB dirty ring。**仅此而已。**

## 5. D. 与既有文档的核对（问题 D.12）

核对对象：`analysis/spec-work/metal-registration-contract.md` §3 第 12–14 条
（来源是 T3 BaseSystem 的用户态 `IOAccelerator.framework` / `Metal.framework`）。

| 条 | 该文的描述 | 内核侧读到的 | 裁决 |
|---|---|---|---|
| 12 | API property 非空时 `IOConnectCallStructMethod(connection, 9, api, 16, NULL, NULL)`，call site `0x7FF80B170FCD..0x7FF80B170FFD`，该 selector 的错误被忽略 | selector `9` = `set_api_property(IOAccelDeviceAPIProperty*)`，`flags = 3 (kIOUCStructIStructO)`，`count0 = 0x10 = 16` 字节 struct in，`count1 = kIOUCVariableStructureSize` | **一致**。补充：内核声明的输出大小是 `VARIABLE` 而不是 0，所以调用方传 `NULL, NULL` 合法 |
| 13 | "selector 2 成功返回**至多** `0x258` bytes、selector 0 成功返回 `0x40` bytes"；selector 7 的 `0x18` 字节输出可选，失败不致命 | selector `2` `count1 = 0x258` **固定**（非 `VARIABLE`）；selector `0` `count1 = 0x40` 固定；selector `7` `count1 = 0x18` 固定 | **基本一致，一处需收紧**：`0x258` 不是"至多"而是**精确值**。内核的 `kIOUCScalarIStructO` 配固定 `count1` 时，`IOUserClient` 要求输出结构尺寸恰好匹配。`20-OBJC-DEVICE.md` §7.3 的实现建议"必须返回满 600 字节"因此是对的，理由比它写的更强 |
| 14 | base init 保存 `IOAccelDeviceRef`、registry ID、原 service port 并 `IOObjectRetain`；真正的 connection 存在 `IOAccelDeviceRef+0x14`，由 `_IOAccelDeviceGetConnect @ IOAccelerator+0x12EF` 读取 | 纯用户态行为，内核侧无对应物可核对 | **无冲突**。内核侧唯一相关事实：`IOAccelDevice2` 自己也记了一个 64 位 `fGlobalObjectID`（`uc+0xF8`，`deviceStart` 里由 `OSIncrementAtomic64(&__globalObjectIDCounter)+1` 得到），它通过 selector 7 的 `+0x00` 返回给用户态，被 Metal 存成 `_globalTraceObjectID` |

**结论：§3 第 12–14 条与内核侧没有实质冲突，只需把第 13 条的"至多 0x258"
改成"恰好 0x258"。** `KNOWN`

顺带核对 `20-OBJC-DEVICE.md`（本文已逐条标注，汇总）：

| 该文位置 | 裁决 |
|---|---|
| §7.1 user client type 表（5/6/8/9/4） | **全部正确**。本文补齐 type 0/1/2/3/7/32/33 与各自的类 |
| §7.2 type-5 创建序列 8 步 | **全部正确** |
| §7.3 selector 2 的 7 行偏移 | **全部正确**，并补齐 `+0x18..+0x57` 的 64 字节（内核确实写，用户态不读） |
| §7.3.1 count = 0 捷径 | **成立**，内核侧对称（count=0 时不写 `offsets[]`） |
| §7.4 selector 0 的 11 行偏移 | **逐项正确** |
| §7.5 type-5 其余 selector | selector `5`/`6`/`7`/`8` 的方法归属需按 §3.2.2 修正 |
| §7.6 type-6 表 | selector `0`/`9`/`0xA` 正确；`0xA` 的 24 字节结构**需改**为三个 u64（§3.4.3）；"count 必须是 2 的幂"成立但位置在 client-shared 区 |
| §7.6 "selector `0xA` 必须成功否则 `lazyInitialize` 返回 NO" | **成立**，且内核侧的失败条件已枚举（§3.4.3） |
| §4.4 `configBits` bit 12 语义 | **成立**，本文给出内核侧的产生式：`cfg->flags` bit 21 |
| §1 表"内核侧规模：小工程，type-5 两个必需 selector 共 664 字节" | **方向正确，但不完整**：还需 `getStampMemory`、`newEventMachine`、两个 GPU task 工厂、四个内存工厂与 `IOSurfaceRoot` 依赖（§4.2.1）。规模仍是小工程，但不是"只填两个结构" |

## 6. 本项目 kext 的实现清单

`INFERRED`（每条的机制都 `KNOWN`，组合未实测）

### 6.1 类与文件

```
LPAcceleratorNub   : IOService                 // 挂 IOResources，给 accelerator 与 display 当共同父节点
LPAccelerator      : IOGraphicsAccelerator2    // 本分册的主体
LPFramebuffer      : IOFramebuffer             // 分册 11
```

### 6.2 `LPAccelerator` 必须写的方法（最小集）

```c
// --- 生命周期 ---
bool  start(IOService *provider) override;     // 调 super::start，成功后 registerService(0)
void  stop(IOService *provider) override;

// --- 17 个纯虚 ---
bool  configureDevice(IOPCIDevice *p) override            { return true; }
void  teardownDevice(IOPCIDevice *p) override             { }
void  populateAccelConfig(IOAccelConfig *cfg) override;   // §3.3.4
IOMemoryDescriptor *getStampMemory(uint32_t *off) override;   // 必须真做，§3.3.2(a)
IOAccelEventMachine2 *newEventMachine(void) override;         // 必须真做，§3.3.2(b)
IOAccelTask *createUserGPUTask(void) override;
IOAccelTask *createKernelGPUTask(void) override;
IOAccelSysMemory *newSysMemory(void) override;
IOAccelVidMemory *newVidMemory(void) override;
IOAccelMemoryMap *newMemoryMap(void) override;
IOAccelResource2 *newResource(void) override;
IOAccelContext2  *newGLContext(void) override             { return NULL; }
IOAccelContext2  *newCLContext(void) override            { return NULL; }
IOAccelSurface   *newSurface(void) override              { return NULL; }
IOAccel2DContext2 *new2DContext(void) override           { return NULL; }
IOAccelContext2  *newVideoContext(void) override         { return NULL; }
IOAccelDisplayMachine *newDisplayMachine(void) override  { return NULL; }

// --- 非纯虚但要覆写 ---
uint64_t getMaxWiredSysMemorySize(void) override;   // selector 0 的 sharedMemorySize
```

**不要覆写**：`newUserClient`、`newDevice`、`newSharedUserClient`、`newShared`、
`newCommandQueue`、`newContext`、`getMaxResourceSize`、`totalTextureMemory`、
`getWorkLoop`、`acceleratorDidLock` / `acceleratorWillUnlock`、
`terminate` / `finalize` / `setProperties`。全部有可用的基类实现（§2.4.3）。

### 6.3 `OSBundleLibraries`

```
com.apple.iokit.IOAcceleratorFamily2   2.0.0
com.apple.iokit.IOGraphicsFamily       515.3
com.apple.iokit.IOSurface              87.0
com.apple.kpi.iokit                    16.7
com.apple.kpi.libkern                  16.7
com.apple.kpi.mach                     9.0.0b1
com.apple.kpi.private                  10.0.0d3
```

**不要**声明 `com.apple.iokit.IOPCIFamily`、**不要**声明
`com.apple.AppleGraphicsDeviceControl`。APV 声明它们是因为它真的用；我们不用。

### 6.4 验收顺序（给分册 `80` 的钩子）

1. `kextload` 成功，`ioreg -c IOAccelerator` 能看到我们的 service。
2. 该 service 的属性表里有 `MetalPluginName`、`MetalPluginClassName`、
   `IOAccelIndex`（由 `IOSurfaceRoot` 注册产生）。
3. `IOServiceOpen(svc, task, 5, &c)` 返回 0（这一步验证 `getStampMemory`）。
4. `IOConnectCallStructMethod(c, 2, NULL, 0, buf600, &600)` 返回 0（验证 event machine）。
5. `IOConnectCallStructMethod(c, 0, NULL, 0, buf64, &64)` 返回 0。
6. `MTLCopyAllDevices()` 返回非空数组。

第 3–5 步可以用一个 60 行的 C 小程序完成，**不依赖任何 ObjC 侧代码**。
强烈建议把它作为内核侧的独立验收工具，把内核 bug 与 ObjC bug 分开。

## 7. 未查清项与查清方法

> **第 4 轮（2026-10-31）后的状态：7.1–7.4 四条已关闭，结论就写在各条下面
> （原问题描述保留，便于复核）；7.5 要上游源码、7.6 要开机，维持不变。
> 逐条索引见 §9。**

### 7.1 `getMaxWiredSysMemorySize` 的 ivar 来源 —— **已关闭** `KNOWN`

**原问题：** `IOGraphicsAccelerator2::getMaxWiredSysMemorySize`（`S-IOAF2 +0x401D2`）
只是 `return this[105]`（accel `+0x348`）。全件扫描发现该 ivar 的唯一写入点是
`S-IOAF2 +0x3BA87`（`mov [r14+348h], rax`，在 `IOGraphicsAccelerator2::start` 内），
右值来自一次调用。

**答案：** 右值是 `IOGraphicsAccelerator2::calcMaxGPUPhysicalMemoryBytes(uint64_t)`
（`S-IOAF2 +0x40E5C`，vtable `__ZTV22IOGraphicsAccelerator2` 槽 311 / vptr `+0x9B8`，
在 `+0x3BA81` 以虚调用形式进入），实参是 **`sysctlbyname("hw.memsize")` 读到的物理内存字节数**。

`start` 里的完整序列（`S-IOAF2 +0x3B73C … +0x3BA92`）：

```c
uint64_t memsize = 0; size_t len = 8;
if (sysctlbyname("hw.memsize", &memsize, &len, NULL, 0) != 0) {   // stub 0x10360，见 §0.3(4)
    this->f338 /* accel+0x338 */ = 0x800000;        // 8 MiB
    memsize                      = 0x20000000;      // 取不到就假定 512 MiB
    goto have_sizes;
}
this->f338 /* accel+0x338 */ = 0x2000000;           // 32 MiB
if (fConfig.flags & (1u << 21)) {                    // 统一内存（§3.3.1）
    this->f340 /* accel+0x340 */ =
        min((memsize * 3) >> 5, 0x30000000);         // 3/32 物理内存，上限 768 MiB
}
have_sizes:
...
this->fMaxWiredSysMemory /* accel+0x348 */ = calcMaxGPUPhysicalMemoryBytes(memsize);
this->fPhysMemSize       /* accel+0xDC0 */ = memsize;
```

`calcMaxGPUPhysicalMemoryBytes` 本体（`S-IOAF2 +0x40E5C`）：

```c
uint64_t v = a2 / 3;
if (v < 0x4000000) v = 0x4000000;              // 64 MiB 下限
return (page_size + v - 1) & ~(page_size - 1); // 向上页对齐；page_size 经 off_14BCF108 取内核 _page_size
```

即 **`sharedMemorySize` 的 Apple 默认值 = `round_page(max(物理内存 / 3, 64 MiB))`**。
顺带确证 `getMaxSingleSysMemorySize()`（`S-IOAF2 +0x40158`）= `(3 × accel+0x348) >> 2`
再页对齐，也就是本值的 3/4。本项目的取法见 §3.3.4 末尾。

### 7.2 `fEventMachine`（accel `+0x380`）的填充点 —— **已关闭** `KNOWN`

**原问题：** `get_event_machine` 直接用 `accel+0x380`，而 `newEventMachine()` 是
纯虚工厂；两者之间的 `init` + 赋值发生在家族内某处。

**答案：填充点是 `IOGraphicsAccelerator2::createEventMachine()`**
（`S-IOAF2 +0x3E82E`，vtable 槽 **272** / vptr `+0x880` —— 它是家族**自带的非纯虚**方法，
不要和槽 273 / vptr `+0x888` 的纯虚 `newEventMachine()` 混。`start` 在
`S-IOAF2 +0x3B098` 调它，`+0x3B09E` 把返回值写进 `accel+0x380`，为 NULL 则打
`"%s: failed to create event machine\n"` 并整个 `start` 失败）：

```c
IOAccelEventMachine2 *em = this->newEventMachine();      // vptr+0x888，纯虚，由子类提供
uint64_t timeout = 1000;
if (fConfig.flags & (1u << 19))                          // 见 §7.4
    timeout = 1000 * fConfig.waitForGPUTimeoutSeconds;   // accel+0xCF0 = cfg+0x68
if (!em) return NULL;
if (!em->init(this, timeout, fConfig.numEventChannels /* accel+0xCA0 = cfg+0x18 */))
    { em->release(); return NULL; }                      // init 是 em 的 vptr+0x118
return em;
```

**对本项目的落法不变，但现在是确定的**：只实现 `newEventMachine()` 返回
`new IOAccelEventMachineFast2(size)`，`init` 由 `createEventMachine` 代劳，
参数也由它按 `fConfig` 算好。

同一段还确证了另两个工厂的填充点（本文 §2.4.1 的"不实现的后果"由此变成实测）：
`accel+0x378 = newDisplayMachine()`（vptr `+0xA00`，`+0x3B15F`，失败 ⇒
`"%s: fDisplayMachine alloc failed\n"`）、`accel+0x388 = newStatistics()`
（vptr `+0xA80`，`+0x3B286`，失败 ⇒ `"%s: statistics object alloc fail\n"`）。

### 7.3 `IOAccelConfig` 的 13 个字段语义 —— **已关闭** `KNOWN`

**原问题：** `cfg+0x0C`、`+0x28`、`+0x2C`、`+0x3C`、`+0x40`、`+0x44`、`+0x45`、
`+0x48`、`+0x6C`、`+0x78`、`+0x7C`、`+0x80`、`+0x94` 的语义。

**答案全部写回 §3.3.3 的表里。** 方法：对这 13 个 accel ivar 位移在 `S-IOAF2`
**全件 3,028 个函数的每条指令**上做内存操作数位移匹配（不限基址寄存器），
逐个读取点读反编译。结果归三类：

| 类 | 字段 | 结论 |
|---|---|---|
| 有明确消费者（9 个） | `+0x0C` `+0x28` `+0x44` `+0x45` `+0x6C` `+0x78` `+0x7C` `+0x80` `+0x94` | 见 §3.3.3 |
| **本家族内零读取点**（4 个） | `+0x2C` `+0x3C` `+0x40` `+0x48` | 只被 `initializeConfigStructure` 的三条 qword 存储连带写入默认值（`+0x28/+0x2C` 一条、`+0x3C/+0x40` 一条、`+0x48/+0x4C` 一条）。**在 `S-IOAF2` 内没有任何代码读它们**，所以本项目填什么都无所谓；保持 `initializeConfigStructure` 的默认值即可 |

**对本项目的净影响：** 这 13 个里只有 `+0x28`（display pipe 条数上限，默认 1）
值得关心 —— 如果将来要挂多于 1 个 framebuffer，必须把它调大，否则
`IOAccelDisplayMachine::found_framebuffer` 从第 2 个开始静默拒绝。其余 12 个
保持默认。

### 7.4 `cfg->flags`（`+0x08`）除 bit 21 以外的位 —— **已关闭（APV 置的两位）** `KNOWN`

**原问题：** 已知 bit 21 = 统一内存（§3.3.1）；bit 13（`cfg+0x09` bit5）被
`IOPCITunnelled` 分支置位并伴随 `Removable` 属性；低 16 位原样成为
`configBits[15:0]`。**APV 置 bit 19 与 bit 22，语义未查清。**

**答案（对 accel `+0xC90..+0xC93` 四个字节别名做全件读取点扫描，共 59 处）：**

**bit 19（`+0xC92 & 0x08`，14 处读取点）= "本 GPU 没有硬件进度指示，不要做硬件挂起看门狗"。**
这是本项目最该照抄的一位：

| 读取点 | 行为（bit 19 **置位**时） |
|---|---|
| `createEventMachine` `+0x3E849` | event machine 的超时取 `1000 × waitForGPUTimeoutSeconds` 而不是固定 `1000`（§7.2） |
| `IOAccelFIFOChannel2::submitCommands` `+0x4F24` | **跳过** `IOAccelEventMachine2::startHardwareProgressTimer()` |
| `IOGraphicsAccelerator2::enableAccelerator` `+0x42169` | **跳过** `startHardwareProgressTimerUnlocked()` |
| `IOGraphicsAccelerator2::disableAccelerator` `+0x42195` | 同上，对偶 |
| `IOGraphicsAccelerator2::enable_gart_collector` `+0x408FA` | **跳过** `startHardwareProgressTimer()` |
| `IOAccelEventMachine2::gpu_progress_check` `+0x12362` | **跳过**挂起处理（`vtable[0x210]` + `IOGraphicsAccelerator2::sendAGCStatusMessage`） |
| `IOAccelEventMachine2::signalStamp` `+0x1303F`、`IOAccelEventMachineFast2::checkGPUProgress` `+0x318E0`、`system_will_sleep` `+0x41243` | 同系的进度/挂起判定分支 |

APV 置它是因为 paravirt 设备没有可读的 GPU 进度计数器。**本项目同理必须置位**
（纯 CPU 渲染根本没有 GPU 挂起这回事），否则家族会起一堆看门狗定时器，
在超时后走 AGC 挂起上报路径。

**bit 22（`+0xC92 & 0x40`，2 处读取点）= 切换两条内存/资源路径：**

| 读取点 | 行为（bit 22 置位时） |
|---|---|
| `IOAccelMemory::createMappingInTaskAtAddressLength` `+0x02509` | 映射失败后走 `IOAccelTask::prune_orphaned_mappings()` 再重试；bit 22 清零时走 `task->vtable[0x120](mapping)` 那条旧路径 |
| `IOAccelResource2::initialize` `+0x23C1D` | 对 `IOAccelNewResourceArgs` 的消费加类型闸：**只有 `eIOAccelResType == 1` 才用用户给的 args 填 resource 的像素/布局描述**（`args+0x20/0x21/0x22`→`res+0xAC/0xAD/0xAE` 等），type 10 且 args 为 NULL 时走 `res+0x108 \|= 4` 分支，其余类型统一改为从后备 IOSurface（`res+0xE0`）反推描述。bit 22 清零时只要 args 非 NULL 就无条件采用 |

**其余位（本轮同时扫到，列出以免下一轮重做）** `KNOWN`（读取点）+ `INFERRED`（语义命名）：

| 位 | 读取点数 | 消费者 |
|---|---:|---|
| bit 7（`+0xC90 & 0x80`） | 3 | `IOAccelResource2::setBackingMemory` / `pageoffIfNeeded` / `lockForCPUAccess` |
| 低 16 位整体 | 6 | 以 `and reg, [accel+0xC90]` 形式与 resource/mapping 的 option 掩码相与（`bindResource`、`newResourceWithOptions`、`allocMemory`、`IOAccelMemoryMap::init`、`IOAccelSysMemory::wire`、`unlockForCPUAccess`）—— 这正是 `configBits[15:0]` 透给用户态的那一半 |
| bit 13（`+0xC91 & 0x20`） | 5 | `start`（唯一置位点 `+0x3AD45`，`IOPCITunnelled` 分支）、`IOAccelDisplayMachine::display_mode_did_change`、`systemWillSleep`、`systemDidWake`、`setProperties` |
| bit 16 / 17 / 18（`+0xC92 & 0x01/0x02/0x04`） | 1 / 2 / 3 | `IOAccelLegacySurface::surfaceStop` / `system_will_sleep`+`system_did_wake` / `process_token_BindDataBuffer`+`processDataBuffers`×2 |
| bit 21（`+0xC92 & 0x20`） | 11 | 统一内存，已在 §3.3.1 |
| bit 25 / 27 / 28 / 29（`+0xC93 & 0x02/0x08/0x10/0x20`） | 1 / 2 / 2 / 1 | `IOAccelContext2::contextStart` / `newResourceWithOptions`+`allocMemory` / `allocMemory`+`IOAccelVidMemory::init` / `IOAccelVidMemory::init` |

**对本项目的建议因此从 `0x00200000` 改为 `0x00280000`**（bit 21 统一内存 + bit 19
关硬件看门狗）。§3.3.4 的代码块保留原值未改 —— 那是"最小可跑"的取值；
真正要跑起来再调时，加上 bit 19 是下一步。`INFERRED`（取值选择）

### 7.5 type-6 selector `0x02` 的 `flags = 4`

**BLOCKED**（需 xnu 的 `IOUserClient.cpp` 源码或 `IOKitKeys.h` 侧确认）。
值是 `KNOWN`，语义不在标准四个方向常量内。不影响本项目（不实现该 selector）。

### 7.6 全部结论仍是静态的

**BLOCKED**：本文没有任何 `TESTED`。§6.4 的六步验收必须在 25G325 x86_64 guest
内跑过，并且按 `00-OVERVIEW.md` §2.5 风险 2 的纪律，先在本地串口环境跑通再推云端。
特别是 §2.3.3 的 `IOResources` provider 方案，**整条是 `INFERRED`**，第一次
`kextload` 就能证伪或确认。

## 8. 本轮新增产物

全部为新增文件，没有改写 `analysis/idb/` 下任何既有文件。

| 路径 | 字节 | SHA-256 |
|---|---:|---|
| `analysis/idb/macos26-25G325-x86_64/idb/AppleParavirtGPU-x86_64-segfixed.i64` | 2,788,058 | `6B7DD2C5FF683282C6050B1FF3118935F540534D075310481C76C519B520427A` |
| `analysis/idb/macos26-25G325-x86_64/idb/IOAcceleratorFamily2-x86_64-segfixed.i64` | 8,769,796 | `AE11E531AC56097E70763F3AA0708E4A22AA7AC99FF9BC8E56E342AA8516029A` |
| `analysis/idb/macos26-25G325-x86_64/idb/IOGraphicsFamily-x86_64-segfixed.i64` | 4,630,623 | `874452DE17432B672E39587D907753043EA1A86A1A50F6DA0EF588A7EB0E597F` |
| `analysis/idb/macos26-25G325-x86_64/tools/fixseg.py` | 2,225 | `0F81EAB93CA1F29267FED8BAF83A4EF1B234D531729030CD9300352426ADD5BB` |
| `analysis/idb/macos26-25G325-x86_64/tools/kcread.py` | 6,738 | `652EADF202237EBFF9DAF1B5AE088331BDDF23721711CA64277C57A9FE186266` |
| `analysis/idb/macos26-25G325-x86_64/tools/kcsyms.py` | 1,984 | `33DF66331AA5B99A193402706F42C87995A9576FC54B3616EEB83EE93E8A492A` |
| `analysis/idb/macos26-25G325-x86_64/MANIFEST-10-KERNEL-ACCELERATOR.md` | — | 见该文件 |

三个 `.i64` 是对**段偏移修复后的副本**建的库（§0.3(1)），不是对仓库原件直接
建的库，因此 IDA 里的 `input file` 名是 `APV-fixed` / `IOAF2-fixed` / `IOGFX-fixed`。
修复是确定性的：`fixseg.py <原件> <修复件>`。修复件的 SHA-256 见
`MANIFEST-10-KERNEL-ACCELERATOR.md`。段 `vmaddr`、section 偏移、符号表与 RVA
均未改动，所以本文的全部地址对仓库原件同样成立。

## 9. 本轮关闭的未查项（第 4 轮，2026-10-31）

本节是复核入口。本轮**只读既有 IDB**（`$env:TEMP` 下的副本），没有新建 `.i64`，
没有改写 `analysis/` 下任何文件。地址一律 `样本标签 +0xRVA`，样本 UUID 见 §0.1。

### 9.1 已关闭

| # | 原条目 | 结论 | 证据（样本 UUID + RVA） | 新标签 |
|---|---|---|---|---|
| 1 | §2.4.2 / §7.1 `getMaxWiredSysMemorySize` 的 ivar（accel `+0x348`）来源 | `= round_page(max(hw.memsize / 3, 64 MiB))`；`hw.memsize` 由 `start` 用 `sysctlbyname` 取，取不到时回退常量 `0x20000000`（512 MiB） | `S-IOAF2` `6C4A16B1-66DC-3A8B-9F0B-D3E027B16EB1`：赋值 `+0x3BA81/+0x3BA87`；被调方 `calcMaxGPUPhysicalMemoryBytes` `+0x40E5C`（vtable 槽 311）；sysctl `+0x3B73C..+0x3B783`；回退路径 `+0x3B76B/+0x3B776` | `KNOWN` |
| 2 | §3.3.2 / §7.2 `fEventMachine`（accel `+0x380`）的填充点 | `IOGraphicsAccelerator2::createEventMachine()`（家族自带非纯虚，vtable 槽 **272**），它调纯虚 `newEventMachine()`（槽 273）再 `init(this, timeout, numEventChannels)`；`timeout` 受 flags bit 19 影响 | `S-IOAF2`：`createEventMachine` `+0x3E82E`；调用与赋值 `+0x3B092/+0x3B098/+0x3B09E`；失败日志 `+0x3B837`。附带确证 `accel+0x378 = newDisplayMachine()` `+0x3B15F`、`accel+0x388 = newStatistics()` `+0x3B286` | `KNOWN` |
| 3 | §3.3.3 / §7.3 `IOAccelConfig` 13 个字段语义 | 9 个有明确消费者（逐条写回 §3.3.3），4 个（`+0x2C` `+0x3C` `+0x40` `+0x48`）在 `S-IOAF2` 内**零读取点** | `S-IOAF2`：`+0x3BDC2`（`AccelCaps`）、`+0x0E041`、`+0x25598`、`+0x21F6C`、`+0x22810`、`+0x29880`、`+0x2A864`、`+0x2B93C`、`+0x2B99D`、`+0x45DA0`、`+0x45ED2`、`+0x3C019`、`+0x3C07A`、`+0x43347` | `KNOWN` |
| 4 | §7.4 `cfg->flags` 除 bit 21 外的位，特别是 APV 置的 bit 19 / bit 22 | bit 19 = 关硬件 GPU 进度看门狗（并把 event machine 超时改为 `1000 × waitForGPUTimeout`）；bit 22 = orphaned mapping 回收 + resource descriptor 的类型闸。另列出 bit 7 / 低 16 位 / 13 / 16 / 17 / 18 / 25 / 27 / 28 / 29 的读取点 | `S-IOAF2`：bit19 共 14 点（`+0x3E849` `+0x04F24` `+0x42169` `+0x42195` `+0x408FA` `+0x12362` `+0x1303F` `+0x318E0` `+0x41243` …）；bit22 `+0x02509` `+0x23C1D`；bit13 置位点 `+0x3AD45` | `KNOWN`（读取点）+ `INFERRED`（命名） |
| 5 | §0.3(3) cacheLevel-0 的 `S-KRNL` `__DATA` 增量缺失 | `= −0x450000`（四点精确命中 `_page_size` / `___stack_chk_guard` / `__os_log_default` / `_gIOServicePlane`）。顺带指出 `MANIFEST-display-iosurface.md` §2.2 把这一行的符号写反了 | `S-IOAF2` GOT 槽 `+0x6A108`、`+0x6A0B0`、`+0x6A0B8`、`+0x6A0C8`（VA `0x14BCF108/0B0/0B8/0C8`）× `kernel-low30-symmap.json` | `KNOWN` |
| 6 | §0.3(4) stub 页 13 条推断表能否转 `KNOWN` | **用仓库材料不可能**（见 §0.3(4) 的穷尽论证：全 collection 415,344 条 nlist 中 `n_value ∈ [0x10000,0x12000)` 为 0 条，KPI 名只有 `N_UNDF` 零地址条目）。但其中 6 条由公开 ABI 锚点转为 `KNOWN`：`0x10360` `sysctlbyname`、`0x1031E` `current_task`、`0x1048C` `IOMemoryDescriptor::withAddressRange`、`0x10678` `IOUserClient::clientHasPrivilege`、`0x100B4` `bzero`、`0x1008A`/`0x10084` 两个 event source 工厂 | 否定结论：`com.apple.iokit.IOAcceleratorFamily2` 原件 `LC_SYMTAB symoff=0x5F9F80/nsyms=4707/stroff=0x6E5470`，nlist 区 `0x8C000..0x6E2700`。正面锚点见 §0.3(4) 表 | 部分 `KNOWN`，余下仍 `INFERRED` |

### 9.2 本轮未关闭，按原因归类

| 原条目 | 归类 | 说明 |
|---|---|---|
| §7.5 type-6 selector `0x02` 的 `flags = 4` 语义 | **要上游源码**（xnu `IOUserClient.cpp`） | 原文已标 `BLOCKED`，维持 |
| §0.3(4) 其余 stub 的真名 | **要上游材料** | 需 `SystemKernelExtensions.kc` 本体（369,213,440 B，SHA-256 `5EDE2BA5…D94421`），不在仓库内。§0.3(4) 已把"为什么不是没查"写成可复核的否定证明 |
| §1 / §2.3.3 / §7.6 `IOResources` provider 方案可行性 | **要开机** | 第一次 `kextload` + `ioreg` 即可证伪或确认 |
| §3.3.1 / §3.3.4 取值选择（`flags`、`videoRam = 0`、`sharedMemorySize`）是否可用 | **要开机** | 机制全部 `KNOWN`，剩下的是运行验收（§6.4 六步） |
| §3.2 / §3.4 "event machine 报告 0 个 stamp" 这条捷径是否成立 | **要开机** | 消费侧逻辑在 `20-OBJC-DEVICE.md` §7.3.1 已 `KNOWN`，组合未实测 |
| §3.1 `IOGraphicsAccelerator2::newContext` / xnu 侧 `newUserClient` 默认实现 | **要上游源码**（xnu） | 返回码 `kIOReturnBadArgument` 的来源在 xnu 而非本家族；对本项目无影响（type 1/3/7 不实现） |
| §4.2.2 / §6 的实现清单 | **要开机** | 本质是"照此写代码后能否通过 §6.4" |
