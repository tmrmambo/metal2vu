# 11 - 内核显示侧：IOFramebuffer provider 实现契约

文档版本：1.0
基线日期：2026-10-31
锚文档：`00-OVERVIEW.md`（证据规则见其第 7 节）
配套分册：`10-KERNEL-ACCELERATOR.md`、`12-KERNEL-IOSURFACE.md`

## 0. 本文作用与结论摘要

本文回答三件事：

1. 在 x86_64 25G325 上实现一个 `IOFramebuffer` 子类，**最少必须写什么**、每个方法的签名与语义、漏掉哪个会导致什么后果。
2. WindowServer 通过哪些 user client、哪些 selector、哪块共享内存与 framebuffer 交互（即原阻断项 **B-008** 想要的东西）。
3. 一个 display service 与一个 accelerator service 在内核侧**到底靠什么关联**，以及本项目能不能不发布自己的 framebuffer、直接挂到 guest 里已有的那一个。

### 0.1 本轮确证的核心结论

| # | 结论 | 标签 |
|---|---|---|
| 1 | `IOFramebuffer` 在 25G325 x86_64 上**恰好有 8 个纯虚方法**，其余全部有默认实现。可实例化的最小子类 = 覆写这 8 个。 | `KNOWN` |
| 2 | `AppleParavirtFramebuffer` 的 framebuffer 后备是 **64 MiB 的 `IOBufferMemoryDescriptor`**（普通内核内存），不是 `IODeviceMemory`。"纯内存 framebuffer" 是 Apple 自己在 x86 上用的模式。 | `KNOWN` |
| 3 | IOGraphicsFamily 对 `getApertureRange`/`getVRAMRange` 返回对象只调用 `getLength()`、`getPhysicalSegment()`、`map()`、`retain/release`，**不依赖 `IODeviceMemory` 的任何专有语义**。 | `KNOWN` |
| 4 | accelerator↔display 的关联是**双向属性写入 + 通知注册**：accelerator 侧由 `IOAccelDisplayPipe::init` 把 `IOAccelIndex` / `IOAccelTypes` / `IOAccelRevision` / `IOCFPlugInTypes` **写到 IOFramebuffer service 的属性表上**；display 侧由 `IOFramebuffer::assignGLIndex` 发布 `IOFramebufferOpenGLIndex`。两者都是普通 `setProperty`，没有私有 ABI。 | `KNOWN` |
| 5 | accelerator 找到 framebuffer 的途径是 `IOAccelDisplayMachine::start(IOPCIDevice*)` 在**同一个 IOPCIDevice 的子节点/客户端**里搜 `IOFramebuffer` 实例。因此"复用已有 framebuffer"在机制上是可行的，前提是两者挂在同一个 PCI 设备下（或自行覆写搜索逻辑）。 | `KNOWN` |
| 6 | `AppleParavirtGPU.kext` 只有**一个** personality。framebuffer 与 accelerator 都是在代码里 `new` 出来、`attach` 到**provider（IOPCIDevice）**、再 `start` 的，不靠 plist 匹配。 | `KNOWN` |
| 7 | 原 B-008（"显示用户 ABI 未取得"）**已实质关闭**：`IOFramebufferUserClient` 的 22 条 selector 全表、两个 user client 的 `clientMemoryForType` 内存类型、`StdFBShmem_t` 的 240 字节逐字段布局均已取得。 | `KNOWN` |

### 0.2 证据样本与地址约定

全部地址写作 `样本标签 + RVA`。RVA = `VA − 镜像基址`，镜像基址取重建件第一个 segment 的 `vmaddr`（IDA 加载后的 `minimum_ea`）。

| 标签 | 样本（`analysis/binaries/macos26-25G325-x86_64/`） | `LC_UUID` | 镜像基址 | 层级 |
|---|---|---|---|---|
| `[G]` | `kext/com.apple.iokit.IOGraphicsFamily` | `74AA6483-8AB4-3A94-8143-5E306C16D7DA` | `0x14CE4000` | T2 |
| `[A]` | `kext/com.apple.driver.AppleParavirtGPU` | `B88E1D48-71A2-3DC0-8D87-605DDB039B83` | `0x14898000` | T2 |
| `[F2]` | `kext/com.apple.iokit.IOAcceleratorFamily2` | `6C4A16B1-66DC-3A8B-9F0B-D3E027B16EB1` | `0x14B65000` | T2 |
| `[S]` | `kext/com.apple.iokit.IOSurface` | `766DF6D3-1EEC-34DB-A9AD-EF72A36FB2A8` | `0xFFFFFF8002B84000` | T2 |
| `[K]` | `kernel/kernel.x86_64` | `E514CEBA-9206-34D5-86C2-64E880FDDA2B` | `0xFFFFFF8000200000`（`__TEXT`） | T1 |

本轮新建的 IDB 在 `analysis/idb/macos26-25G325-x86_64/`（根下的 `*-kc-rebuild.i64` 四件 + `kernel-low30-symmap.json`），清单与建库前必做的两步修正见该目录 `MANIFEST-display-iosurface.md`。该目录的 `idb/*-segfixed.i64` 与 `tools/*.py` 属 `10-KERNEL-ACCELERATOR.md` 那一轮，不在本文范围。

## 1. 先修两个工具链坑（否则后续全部无法复现）

### 1.1 重建件的 `LC_SEGMENT_64` 文件偏移字段是错的 `KNOWN`

`analysis/binaries/macos26-25G325-x86_64/kext/` 下 7 个重建件的每个 `LC_SEGMENT_64` 里：

- `fileoff` 字段被写成了 `vmaddr`
- `filesize` 字段被写成了**真实的 `fileoff`**

而 **`section_64.offset` 是正确的**。例如 `[G]`：

```
SEG __TEXT       vmaddr 0x14CE4000 vmsize 0x2F000  fileoff(字段) 0x14CE4000  filesize(字段) 0x4000
  __TEXT.__text  addr   0x14CE4600 size   0x28F78  offset        0x4600
```

一致性检查 `section.offset − (section.addr − seg.vmaddr) = 真实 seg.fileoff` 对所有 section 成立（`[G]` 四个段分别是 `0x4000 / 0x34000 / 0x44000 / 0x48000`）。

**后果：** IDA 会把符号表（2114～4707 个符号）加载得完全正确，但**所有 segment 的字节都没有载入**（`is_loaded()` 全为 False、函数数为 0、任何 `get_qword` 返回 `0xFFFF...`）。极易被误判为"样本损坏"或"vtable 被剥离"。

**修法（本轮用的脚本逻辑，不改仓库原件，只在 `$env:TEMP` 下生成 `.fixed` 副本）：**

```python
true_fileoff = filesize_field                      # 写错位的真实值
true_filesize = max(sec.offset + sec.size
                    for sec in segment.sections if sec.offset != 0) - true_fileoff
# 纯 zero-fill 段（__common / __bss，offset==0）不参与
```

`[G]` 修正后：`__TEXT (0x4000, 0x2E24A)`、`__DATA (0x34000, 0xF9C0)`、`__DATA_CONST (0x44000, 0x1E50)`、`__LINKEDIT (0x48000, 0xC5A678)`。修正后 `[G]` 得到 1146 个函数，vtable、`__const` 里的 dispatch 表全部可读。

### 1.2 `__DATA` 指针是 chained-fixup 编码值，但可以在件内解码 `KNOWN`

编码按 `DYLD_CHAINED_PTR_64_KERNEL_CACHE` 风格排布：

```
target : 30, cacheLevel : 2, diversity : 16, addrDiv : 1, key : 2, next : 12, isAuth : 1
```

实测解码规则（`00-OVERVIEW.md` §4.1 "不要把 `__DATA` 原始 qword 当地址" 的具体可操作化）：

- `target = value & 0x3FFFFFFF`
- **SystemKernelExtensions.kc 重建件**（`[G]` `[A]` `[F2]`，基址 `0x14xxxxxx`）：`target` 直接等于 IDA 加载后的地址，不需要再加偏移。
- **BootKernelExtensions.kc 重建件**（`[S]`，基址 `0xFFFFFF8002B84000`）：加载后地址 `= 0xFFFFFF8000100000 + target`。
- 指向内核本体的 target，换算到 `[K]` 独立件地址的 per-segment 增量：`__TEXT −0x18000`、`__DATA +0x450000`、`__DATA_CONST +0xDCA000`。本轮用这组增量把 `[G]` 的 37 个 `__got` 槽全部解析成了具名内核符号，可作校验。

**校验锚点：** `[G]` `__ZTV` 槽 2 的原始值 `0x0040000054D0CDC4` → `target = 0x14D0CDC4` → RVA `0x28DC4` = `IOFramebuffer::~IOFramebuffer()` ✓。

### 1.3 vtable 槽号与 "+2" 规则 `KNOWN`

`vtable for'X` 符号指向 `__ZTVX`，其槽 0/1 是 offset-to-top 与 typeinfo（内核里都是 0）。对象里的 vptr 指向 `__ZTVX + 16`。因此反编译里出现的 `(*(void**)(*(void**)obj + N))` 对应的 `__ZTV` 槽号是 `N/8 + 2`。本文所有槽号均以 `__ZTV` 起点计。

### 1.4 一个 grep 陷阱 `KNOWN`

重建件的 `__LINKEDIT` 携带的是**整个 kernel collection 的 linkedit 大块**（`[G]` `[A]` `[F2]` 的 `__LINKEDIT` 长度都是 `0xC5A678`），所以**字符串表里有全部 kext 的 C++ mangled 名**。对重建件做 `strings | grep <mangled>` 来判断"哪个 kext 引用了某符号"会得到全假阳性。必须解析该件自己的 `LC_SYMTAB` nlist 并看 `n_type & N_TYPE == N_UNDF`。`__cstring` 是每件独立的，对普通字面量 grep 仍然有效。

## 2. A. `IOFramebuffer` 子类契约

### 2.1 vtable 全貌与纯虚方法全集 `KNOWN`

`[G]` `vtable for'IOFramebuffer` 在 RVA `0x35248`，到 `vtable for'IOFramebuffer::MetaClass`（RVA `0x35D50`）为止共 **353 槽**。

槽内只有 **8 个**指向内核 `___cxa_pure_virtual`（KC target `0xAB77D0`，即 `[K]` `0xACF7D0`）：槽 **311、314、315、316、317、318、319、320**。其余 345 槽全部指向具体实现（IOFramebuffer 自己的覆写或继承自 IOService/IORegistryEntry/OSObject 的实现）。

`[G]` 的 2114 条符号里，恰好这 8 个方法名**没有任何定义符号**；它们两侧的槽（305–310、312–313、321–351）全部解析为具名 `IOFramebuffer::*` 符号，因此槽→名的对应是唯一的。

**IOFramebuffer 自有虚方法区段（槽 305–351）完整对照表：**

| 槽 | 方法 | `[G]` RVA | 是否纯虚 |
|---:|---|---|---|
| 305 | `open()` | `0x19976` | |
| 306 | `close()` | `0x1C934` | |
| 307 | `isConsoleDevice()` | `0x1FFDE` | |
| 308 | `setupForCurrentConfig()` | `0x1D0F2` | |
| 309 | `serializeInfo(OSSerialize*)` | `0x1EF5E` | |
| 310 | `setNumber(OSDictionary*, const char*, UInt32)` | `0x1EF0C` | |
| **311** | **`getApertureRange(IOPixelAperture)`** | — | **纯虚** |
| 312 | `getVRAMRange()` | `0x1D0BC` | |
| 313 | `enableController()` | `0x1FFD6` | |
| **314** | **`getPixelFormats()`** | — | **纯虚** |
| **315** | **`getDisplayModeCount()`** | — | **纯虚** |
| **316** | **`getDisplayModes(IODisplayModeID*)`** | — | **纯虚** |
| **317** | **`getInformationForDisplayMode(IODisplayModeID, IODisplayModeInformation*)`** | — | **纯虚** |
| **318** | **`getPixelFormatsForDisplayMode(IODisplayModeID, IOIndex)`** | — | **纯虚** |
| **319** | **`getPixelInformation(IODisplayModeID, IOIndex, IOPixelAperture, IOPixelInformation*)`** | — | **纯虚** |
| **320** | **`getCurrentDisplayMode(IODisplayModeID*, IOIndex*)`** | — | **纯虚** |
| 321 | `setDisplayMode(IODisplayModeID, IOIndex)` | `0x1FFE6` | |
| 322 | `setApertureEnable(IOPixelAperture, IOOptionBits)` | `0x1FFF2` | |
| 323 | `setStartupDisplayMode(IODisplayModeID, IOIndex)` | `0x1FFFE` | |
| 324 | `getStartupDisplayMode(IODisplayModeID*, IOIndex*)` | `0x2000A` | |
| 325 | `setCLUTWithEntries(IOColorEntry*, UInt32, UInt32, IOOptionBits)` | `0x20016` | |
| 326 | `setGammaTable(UInt32, UInt32, UInt32, void*)` | `0x2002E` | |
| 327 | `setAttribute(IOSelect, uintptr_t)` | `0x1E938` | |
| 328 | `getAttribute(IOSelect, uintptr_t*)` | `0x1EE26` | |
| 329 | `getTimingInfoForDisplayMode(IODisplayModeID, IOTimingInformation*)` | `0x2003A` | |
| 330 | `validateDetailedTiming(void*, IOByteCount)` | `0x20046` | |
| 331 | `setDetailedTimings(OSArray*)` | `0x20052` | |
| 332 | `getConnectionCount()` | `0x2005E` | |
| 333 | `setAttributeForConnection(IOIndex, IOSelect, uintptr_t)` | `0x20478` | |
| 334 | `getAttributeForConnection(IOIndex, IOSelect, uintptr_t*)` | `0x206BA` | |
| 335 | `convertCursorImage(void*, IOHardwareCursorDescriptor*, IOHardwareCursorInfo*)` | `0x15130` | |
| 336 | `setCursorImage(void*)` | `0x20942` | |
| 337 | `setCursorState(SInt32, SInt32, bool)` | `0x2094E` | |
| 338 | `flushCursor()` | `0x2095A` | |
| 339 | `getAppleSense(IOIndex, UInt32*, UInt32*, UInt32*, UInt32*)` | `0x20A12` | |
| 340 | `connectFlags(IOIndex, IODisplayModeID, UInt32*)` | `0x20A1E` | |
| 341 | `setDDCClock(IOIndex, UInt32)` | `0x20A2A` | |
| 342 | `setDDCData(IOIndex, UInt32)` | `0x20A30` | |
| 343 | `readDDCClock(IOIndex)` | `0x20A36` | |
| 344 | `readDDCData(IOIndex)` | `0x20A3E` | |
| 345 | `enableDDCRaster(bool)` | `0x20A46` | |
| 346 | `hasDDCConnect(IOIndex)` | `0x20A52` | |
| 347 | `getDDCBlock(IOIndex, UInt32, IOSelect, IOOptionBits, UInt8*, IOByteCount*)` | `0x20A6A` | |
| 348 | `registerForInterruptType(IOSelect, IOFBInterruptProc, OSObject*, void*, void**)` | `0x20960` | |
| 349 | `unregisterInterrupt(void*)` | `0x209AE` | |
| 350 | `setInterruptState(void*, UInt32)` | `0x209E0` | |
| 351 | `getNotificationSemaphore(IOSelect, semaphore_t*)` | `0x14A3E` | |

槽 276–304 是 `_RESERVEDIOFramebuffer3` … `_RESERVEDIOFramebuffer31`（RVA `0x22E3A`–`0x230A2`，每个 22 字节的 panic stub）。槽 268–275 是 `hideCursor / showCursor / moveCursor / getVBLTime / getBoundingRect / doI2CRequest / diagnoseReport / setGammaTable(5 参)`。

被 `IOFramebuffer` 覆写的基类槽（本项目通常不要再覆写，否则要记得链到 `super`）：186 `start`、187 `stop`、194 `terminate`、208 `attach`、211 `getWorkLoop`、217 `callPlatformFunction`、231 `requestProbe`、232 `message`、241 `newUserClient`、250/251 `set/getAggressiveness`、255 `setPowerState`、259/260 `powerStateWill/DidChangeTo`、129–131 `requestTerminate/willTerminate/didTerminate`、98 `setProperties`、20 `free`。

### 2.2 八个纯虚方法的语义与返回值契约

签名与参数名取自 vtable 位置 + `[A]` 的覆写实现 + `[G]` 调用点，三者互证。

#### 311 `IODeviceMemory * getApertureRange(IOPixelAperture aperture)`

返回当前配置下该 aperture 的内存描述符。**唯一硬约束来自 `[G]` `IOFramebuffer::getApertureRangeWithLength`（RVA `0x166C6`）：**

```c
IODeviceMemory *m = getApertureRange(kIOFBSystemAperture /* 0 */);   // 注意：传入常量 0，不是调用者给的 aperture
if (!m) return NULL;                                                  // → fVramMap / fFrameBuffer 都不建立
len = m->getLength();                                                 // IOMemoryDescriptor vtable 槽 59
if (len == 0)         → 打印 "VENDOR_BUG: getApertureRange(kIOFBSystemAperture) length is zero!!"，释放并返回 NULL
if (required > len)   → 打印 "VENDOR_BUG: ... length insufficient. Required: %llu Have: %llu!!"，释放并返回 NULL
```

`required` 由 `[G]` `IOFramebuffer::doSetup`（RVA `0xF7F8`）算出，等于 **`pixelInfo.bytesPerRow × pixelInfo.activeHeight`**（反编译里是 `__private+808`×`__private+968`，即 `IOPixelInformation` 偏移 `0x00` 与 `0xA0`）。

**调用者只用返回对象的这些方法**（`[K]` `__ZTV18IOMemoryDescriptor` 槽号已逐个核对）：

| 用途 | `__ZTV18IOMemoryDescriptor` 槽 | 符号 |
|---|---:|---|
| 取长度 | 59 | `IOMemoryDescriptor::getLength()` |
| 取物理段 | 41 | 纯虚（`getPhysicalSegment`，由具体子类实现） |
| 内核映射 | 66 | `IOMemoryDescriptor::map(IOOptionBits)`，`doSetup` 传 `0x400` |
| 引用计数 | 6/7 | `retain` / `release` |

`doSetup` 还会把该对象放进 `userAccessRanges[0]`，并以 `getPhysicalSegment(0, NULL, 0x800)` 的结果与 `getVRAMRange()` 的物理段相减，算出 `fVramMapOffset`，再 `setProperty("IOFBMemorySize", vramLength, 32)`。

#### 312 `IODeviceMemory * getVRAMRange()`（非纯虚，但必须覆写）

默认实现 `[G]` `0x1D0BC` 是返回 0 的 stub。它被两处用到：`doSetup` 里算 `fVramMapOffset` 与 `IOFBMemorySize`；以及两个 user client 的 `clientMemoryForType(110)`（见 §3.3）。**不覆写 → WindowServer 拿不到 framebuffer 内存映射。**

契约：返回**整块显存/后备内存**的描述符，长度 ≥ `getApertureRange` 返回的那块。约定是调用方取得所有权，所以实现里要 `retain` 后再返回（`[A]` 正是这么写的）。

#### 314 `const char * getPixelFormats()`

返回一个静态 C 字符串，形式为 `IOPixelEncoding`。`[A]` `0x583E` 返回 `"--------RRRRRRRRGGGGGGGGBBBBBBBB"`（32 位 XRGB8888，即公开常量 `IO32BitDirectPixels`）。本项目照抄。

#### 315 `IOItemCount getDisplayModeCount()`

返回 mode 数。`[A]` `0x584C`：取内部 detailed-timing 数组的元素数（`OSArray::getCount`，vtable 槽 40）；数组为空返回 0。

#### 316 `IOReturn getDisplayModes(IODisplayModeID * allDisplayModes)`

填入 `getDisplayModeCount()` 个 ID。`[A]` `0x5972`：`allDisplayModes[i] = i`（即 mode ID 就是下标，从 0 开始）；`allDisplayModes == NULL` 返回 `kIOReturnNoResources`（`0xE00002BE`）。

> 注意：`[A]` 用 0 做第一个合法 mode ID。IOGraphics 自身不要求 ID ≥ 1。

#### 317 `IOReturn getInformationForDisplayMode(IODisplayModeID, IODisplayModeInformation *)`

`IODisplayModeInformation` 共 36 字节（`[G]` 类型库）：

| 偏移 | 字段 | 类型 |
|---:|---|---|
| `0x00` | `nominalWidth` | `UInt32` |
| `0x04` | `nominalHeight` | `UInt32` |
| `0x08` | `refreshRate` | `IOFixed1616` |
| `0x0C` | `maxDepthIndex` | `IOIndex` |
| `0x10` | `flags` | `UInt32` |
| `0x14` | `imageWidth` | `UInt16` |
| `0x16` | `imageHeight` | `UInt16` |
| `0x18` | `reserved[3]` | `UInt32` |

`[A]` `0x5A30` 的填法（可直接照抄）：

```c
refreshRate  = (pixelClock << 16) / ((hActive + hBlanking) * (vActive + vBlanking));
nominalWidth = hActive;  nominalHeight = vActive;
maxDepthIndex = 2;
flags = 0x80000000;              // 最高位 = kDisplayModeValidFlag
imageWidth = <EDID 物理宽>; imageHeight = <EDID 物理高>;
reserved[] = 0;
// 非法 mode → return 0xE00002BC (kIOReturnError)
```

#### 318 `UInt64 getPixelFormatsForDisplayMode(IODisplayModeID, IOIndex depth)`

**`[A]` `0x71A8` 直接 `return 0`。** 该返回值在 25G325 的 IOGraphics 路径上没有被当成能力掩码使用。本项目同样返回 0。`KNOWN`

**消费点已逐一追完（原文此处为 `INFERRED`，现升级）：对 `[G]` 全件 1,146 个函数的每条
`call`/`jmp` 做间接调用位移匹配，vptr 偏移 `0x9E0`（= `__ZTV` 槽 318）的调用点数是 0。**
`IOGraphicsFamily` 里**没有任何代码调用这个槽**，`ext*` 外部方法里也没有，
所以它既不进用户 ABI 也不进 `serializeInfo` 的 IORegistry 序列化。
它纯粹是一个"编译期必须实现、运行期无人调用"的纯虚槽。

同一次扫描的对照数据（证明扫描本身有效，并顺带给出谁消费哪个槽）：

| `__ZTV` 槽 | vptr 偏移 | 方法 | `[G]` 内调用点数 | 调用者 |
|---:|---|---|---:|---|
| 311 | `0x9A8` | `getApertureRange` | 1 | `getApertureRangeWithLength` |
| 312 | `0x9B0` | `getVRAMRange` | 4 | `doSetup`、`restoreFramebuffer`、`IOFramebufferUserClient::clientMemoryForType`、`IOFramebufferSharedUserClient::clientMemoryForType` |
| 313 | `0x9B8` | `enableController` | 1 | `open` |
| **314** | `0x9C0` | **`getPixelFormats`** | **0** | — |
| 315 | `0x9C8` | `getDisplayModeCount` | 4 | `updateOnline`、`serializeInfo`、`extGetDisplayModes`、`extGetDisplayModeCount` |
| 316 | `0x9D0` | `getDisplayModes` | 3 | `updateOnline`、`serializeInfo`、`extGetDisplayModes` |
| 317 | `0x9D8` | `getInformationForDisplayMode` | 2 | `serializeInfo`、`extGetInformationForDisplayMode` |
| **318** | `0x9E0` | **`getPixelFormatsForDisplayMode`** | **0** | — |
| 319 | `0x9E8` | `getPixelInformation` | 8 | `doSetup`、`initFB`、`closestDepth`、`serializeInfo`、`extGetPixelInformation`、`IOBootFramebuffer::getApertureRange` |
| 320 | `0x9F0` | `getCurrentDisplayMode` | 4 | `doSetup`、`initFB`、`doSetDisplayMode`、`extGetCurrentDisplayMode` |

所以 **314 与 318 两个纯虚槽都可以写成 `return 0` / `return NULL` 而不做任何功能实现**
（314 的返回值类型是 `const char *`，为安全起见返回一个空字符串常量而不是 NULL）。
样本：`[G]` UUID `74AA6483-8AB4-3A94-8143-5E306C16D7DA`，`__ZTV13IOFramebuffer` RVA `0x35248`。

#### 319 `IOReturn getPixelInformation(IODisplayModeID, IOIndex depth, IOPixelAperture, IOPixelInformation *)`

`IOPixelInformation` 共 172 字节（= `extGetPixelInformation` 的 `checkStructureOutputSize = 0xAC`，互证）：

| 偏移 | 字段 | 类型 |
|---:|---|---|
| `0x00` | `bytesPerRow` | `UInt32` |
| `0x04` | `bytesPerPlane` | `UInt32` |
| `0x08` | `bitsPerPixel` | `UInt32` |
| `0x0C` | `pixelType` | `UInt32` |
| `0x10` | `componentCount` | `UInt32` |
| `0x14` | `bitsPerComponent` | `UInt32` |
| `0x18` | `componentMasks[16]` | `UInt32` |
| `0x58` | `pixelFormat` | `IOPixelEncoding`（64 字节字符数组） |
| `0x98` | `flags` | `UInt32` |
| `0x9C` | `activeWidth` | `UInt32` |
| `0xA0` | `activeHeight` | `UInt32` |
| `0xA4` | `reserved[2]` | `UInt32` |

`[A]` `0x5C6C` 的填法：

```c
if (depth > 2 || aperture != 0 /* kIOFBSystemAperture */ || 非法 mode)
    return 0xE00002C6;                       // kIOReturnBadMessageID
bzero(&info->bytesPerPlane, 168);            // 从 0x04 起清零
info->activeWidth      = hActive;
info->activeHeight     = vActive;
info->bytesPerRow      = 4 * hActive;
info->bitsPerPixel     = 32;
info->pixelType        = 2;                  // kIORGBDirectPixels
info->componentMasks[0]= 0x0000FF;           // B
info->componentMasks[1]= 0x00FF00;           // G
info->componentMasks[2]= 0xFF0000;           // R
info->componentCount   = 3;
info->bitsPerComponent = 8;
strlcpy(info->pixelFormat, "--------RRRRRRRRGGGGGGGGBBBBBBBB", 64);
```

注意 `[A]` 对 depth 0/1/2 返回**同一份** 32 位信息。

#### 320 `IOReturn getCurrentDisplayMode(IODisplayModeID * displayMode, IOIndex * depth)`

`[A]` `0x59BC`：`*displayMode = <当前 mode>`；`*depth = 2`；两个指针都容许为 NULL；永远返回 0。

### 2.3 哪些漏掉会"不注册"，哪些只是功能缺失

| 类别 | 方法 | 不实现的后果 |
|---|---|---|
| **编译期强制** | 311 / 314–320 共 8 个纯虚 | 类是抽象类，`OSDefineMetaClassAndStructors` 生成的 `alloc()` 无法编译/实例化。连 kext 都装不起来。 |
| **注册必需（运行期）** | 312 `getVRAMRange` | `doSetup` 得不到 VRAM 描述符 → 不设 `IOFBMemorySize`、`fVramMapOffset` 为 0；`clientMemoryForType(110)` 返回 `kIOReturnBadArgument` → **WindowServer 映射不到 framebuffer**。 |
| | 311 返回长度不足 | `getApertureRangeWithLength` 打 `VENDOR_BUG` 并返回 NULL → `fVramMap`/`fFrameBuffer` 为空 → 控制台与 WindowServer 都没有可写内存。 |
| | 319/320 失败 | `doSetup` 会把 `__private` 里的 `IOPixelInformation` 整块清零（RVA `0xF7F8` 内 `bzero(..., 172)`），于是 `required = 0`、`bytesPerRow = 0`，后续一切尺寸计算都错。 |
| **功能缺失（仍然注册）** | 313 `enableController` | 默认返回 `kIOReturnSuccess`。`[A]` 也只是 `return 0`。可以不覆写。 |
| | 321 `setDisplayMode` | 默认 stub。只会导致改分辨率失败，不影响注册。 |
| | 329 `getTimingInfoForDisplayMode` | `doSetup` 失败时 `bzero(timingInfo, 168)`，`setVBLTiming` 拿不到 pixelClock → VBL 周期算不出来。**本项目用软件 VBL，必须实现**（见 §3.5）。 |
| | 325/326 CLUT/Gamma | 默认 stub。32 位直通像素下 WindowServer 自己做 gamma，可缺。 |
| | 335–338 cursor | 不覆写 → `getAttribute('crsr')` 不报硬件光标 → IOGraphics 走软件光标（`StdFBDisplayCursor32Axxx` 等，`[G]` `0xCA90`），直接画进 `fFrameBuffer`。**这是本项目推荐路径**。 |
| | 339–347 DDC/EDID | 默认 stub。没有 EDID → `IODisplayWrangler` 会挂一个 generic `IODisplay`。`[A]` 实现了 `hasDDCConnect`/`getDDCBlock`（`0x654A`/`0x6552`）来提供合成 EDID，建议照做。 |
| | 348–350 中断 | 默认 stub。**不实现 → 没有 VBL，WindowServer 会退化到定时轮询**；详见 §3.5。 |
| | 351 `getNotificationSemaphore` | `[G]` 有实现（`0x14A3E`），返回 `vblSemaphore`。不要覆写。 |
| | 333 `setAttributeForConnection` | `[A]` 不覆写。 |

### 2.4 `AppleParavirtFramebuffer` 实际覆写了什么 `KNOWN`

`[A]` 中 `AppleParavirtFramebuffer` 共 43 条符号。按类别：

**IOFramebuffer 虚方法覆写（27 个）：**
`enableController 0x5836`、`getPixelFormats 0x583E`、`getDisplayModeCount 0x584C`、`setStartupDisplayMode 0x586A`、`getStartupDisplayMode 0x5918`、`getDisplayModes 0x5972`、`getCurrentDisplayMode 0x59BC`、`setDisplayMode 0x59DC`、`getInformationForDisplayMode 0x5A30`、`getTimingInfoForDisplayMode 0x5B0E`、`setDetailedTimings 0x5B42`、`validateDetailedTiming 0x5B8A`、`getApertureRange 0x5C2C`、`getVRAMRange 0x5C3A`、`getPixelInformation 0x5C6C`、`setAttribute 0x5D28`、`getAttribute 0x5DA2`、`getAttributeForConnection 0x5DDC`、`setCursorImage 0x63C2`、`setCursorState 0x64FC`、`hasDDCConnect 0x654A`、`getDDCBlock 0x6552`、`registerForInterruptType 0x6CE8`、`unregisterInterrupt 0x6F5C`、`setInterruptState 0x7128`、`getPixelFormatsForDisplayMode 0x71A8`、`getConnectionCount 0x71B0`。

**IOService 覆写：** `probe 0x52E0`、`start 0x53D4`、`free 0x51CC`。

**AGDC 协议：** `doDeviceAttribute 0x65F4`。

**自有方法：** `initWithID(uint) 0x510C`、`setDisplayPipe(AppleParavirtDisplayPipe*, uint) 0x52F2`、`setupMMIO 0x5602`、`setVBLTimer(bool) 0x5714`、`getFramebufferMemoryDescriptor 0x5C5E`、`connectionChange(...) 0x5E1C`、`processCursorImage(...) 0x63EE`。

**没有覆写：** `isConsoleDevice`、`setupForCurrentConfig`、`serializeInfo`、`setApertureEnable`、`setCLUTWithEntries`、`setGammaTable`、`setAttributeForConnection`、`convertCursorImage`、`flushCursor`、`getAppleSense`、`connectFlags`、DDC clock/data 四件、`enableDDCRaster`、`getNotificationSemaphore`。

**属性/attribute 处理（`[A]` 实测常量）：**

| 方法 | 常量 | fourcc | 行为 |
|---|---|---|---|
| `getAttribute` | `1668445042` | `'crsr'` | `*value = 1` |
| `getAttribute` | `2004054646` | `'wsrv'` | 回读保存的 WindowServer-active 值 |
| `setAttribute` | `1685090167` | `'dpow'` | 存到对象 `+0x208` |
| `setAttribute` | `1886876275` | `'pwrs'` | 同上 |
| `setAttribute` | `2004054646` | `'wsrv'` | 存到 `+0x210`；按 `value & 0xF` 对 framebuffer 的 `IOBufferMemoryDescriptor` 调 vtable `+288`（= `IOMemoryDescriptor` 槽 38，`prepare`/`complete` 一类）参数 2 或 4 |
| `getAttributeForConnection` | `1667591777` / `1701732706` | `'cena'` / `'enab'` | `*value = (online bit)` |
| `getAttributeForConnection` | `1751409763` | `'hddc'` | 直接 `return 0`（声明支持高层 DDC） |

> `getAttribute('crsr')` 的返回值被 `[G]` `doSetup`（RVA `0xF7F8`）用来置 `haveHWCursor`：**只有 bit `0x10000` 置位才算有硬件光标**。`[A]` 返回 1，所以 **APV 实际走软件光标**，`setCursorImage`/`setCursorState` 只是把 glyph 转给 display pipe。

### 2.5 VRAM / aperture 从哪来：纯内存 framebuffer 的可行性 `KNOWN`

**`[A]` `AppleParavirtFramebuffer::initWithID(uint id)`（RVA `0x510C`）核心两行：**

```c
size = (id == 0) ? 0x4000000 /* 64 MiB */ : 0x1000 /* 4 KiB */;
fbMemory = IOBufferMemoryDescriptor::withOptions(/*options=*/0x803, /*capacity=*/size, /*alignment=*/1);
this->fbMemory /* +0x1D8 */ = fbMemory;
```

`options = 0x803` = `kIODirectionOutIn (3) | kIOMemoryKernelUserShared (0x800)`。

**`getVRAMRange()`（RVA `0x5C3A`）：**

```c
fbMemory->retain();        // vtable 槽 6
return fbMemory;
```

**`getApertureRange(aperture)`（RVA `0x5C2C`）：**

```c
return this->getVRAMRange();   // vptr + 2480 == __ZTV 槽 312
```

即：**整个 aperture 就是那块 `IOBufferMemoryDescriptor`，aperture 参数被忽略。**

**`getFramebufferMemoryDescriptor()`（RVA `0x5C5E`）** 返回同一对象（不 retain），供 display pipe 使用。

**结论（Q3）：纯内存 framebuffer 可行，而且这正是 Apple 自己在 x86 上的做法。** 依据三条：

1. `[A]` 返回的是 `IOBufferMemoryDescriptor*`，虽然方法签名写的是 `IODeviceMemory*`。C++ 层面是不安全向下转型，但运行期成立，因为——
2. `[G]` 对该对象只调用 `getLength()`（`[K]` 槽 59）、`getPhysicalSegment()`（槽 41，`IOMemoryDescriptor` 里是纯虚、`IOBufferMemoryDescriptor` 有实现）、`map(0x400)`（槽 66）、`retain`/`release`。`IODeviceMemory` 的专有静态构造器（`withRange` / `withSubRange` / `arrayFromList`）在这条路径上一次都没有被调用。
3. `IOBufferMemoryDescriptor` 的内存是 wired 的内核内存，`getPhysicalSegment()` 有效，`map()` 可建立用户/内核映射，`kIOMemoryKernelUserShared` 让它能被映射进用户任务。`doSetup` 用 `map(0x400)`（write-combine 缓存属性）取内核虚地址存入 `fFrameBuffer`，软件光标与 `fillFramebufferBlack`（`[G]` `0x1C71E`）直接写它。

**本项目的落法：** 让 Lavapipe 的渲染目标就是这块 `IOBufferMemoryDescriptor` 的 `getBytesNoCopy()` 返回区（或者反过来：先分配 framebuffer 内存，再用 `IOBufferMemoryDescriptor::withOptions` 包装）。大小按 `maxWidth × maxHeight × 4` 向上取整到页，并留出 `0x4000000` 这样的余量以便切换分辨率时不重新分配。

一个实现细节值得照抄：`[A]` 给 **id == 0 的那一个** framebuffer 分 64 MiB，其余只分 4 KiB —— 即只有主显示有真后备内存。

### 2.6 本项目 framebuffer personality 怎么写 `KNOWN` + `INFERRED`

#### 2.6.1 APV 的事实（`[A]` + plist）

`AppleParavirtGPU.kext/Contents/Info.plist` 里 **只有一个 personality**：

```xml
<key>AppleParavirtGPUControl</key>
<dict>
  <key>IOClass</key>          <string>AppleParavirtGPUControl</string>
  <key>IOProviderClass</key>  <string>IOPCIDevice</string>
  <key>IOPCIMatch</key>       <string>0xEEEE106B</string>
  <key>IOMatchCategory</key>  <string>IOFramebuffer</string>
  <key>IOProbeScore</key>     <integer>1000000</integer>
  <key>FramebufferCount</key> <integer>0</integer>
  <key>AcceleratorProperties</key>
  <dict>
    <key>IOMatchCategory</key>       <string>IOAccelerator</string>
    <key>MetalPluginName</key>       <string>AppleParavirtGPUMetal</string>
    <key>MetalPluginClassName</key>  <string>AppleParavirtDevice</string>
    <key>IOAccelDisplayPipeCapabilities</key>
    <dict><key>DisplayPipeSupported</key><true/><key>TransactionsSupported</key><true/></dict>
  </dict>
</dict>
```

**没有 framebuffer personality，也没有 accelerator personality。** `AppleParavirtGPUControl` 继承 `AppleGraphicsDeviceControl`（`[A]` `AppleParavirtGPUControl::superClass` 解码后落在 `AppleGraphicsDeviceControl` kext 内）。

#### 2.6.2 framebuffer 与 accelerator 是在代码里造出来的 `KNOWN`

`[A]` `AppleParavirtGPUControl::vendor_doDeviceAttribute`（RVA `0x116A`）把工作丢进 workloop 的 gated block（block 函数 RVA `0x121A`）。该 block 的 **AGDC attribute 3** 分支反汇编（RVA `0x14DD`–`0x16CD`）如下：

```
provider = control->getProvider();        // vtable +0x680 → __ZTV 槽 210 = IOService::getProvider  →  IOPCIDevice
flags    = *inStruct & gFlagsMask;

if (flags & 1) for (i = 0; i < control->displayPortCount; ++i) {
    fb = new AppleParavirtFramebuffer;            // 对象大小 0x2B0 = 688 字节
    if (!fb->initWithID(i))            goto fail;
    if (!fb->attach(provider))         goto fail;   // +0x670 → 槽 208 = attach
    if (!fb->start(provider))          { fb->detach(provider); fb->release(); fb = NULL; }   // +0x5C0 → 槽 186
    control->framebuffers[i] = fb;                 // control + 0x118 + 8*i
}
if (flags & 2) {
    accel = new AppleParavirtAccelerator;          // 对象大小 0xF88 = 3976 字节
    ...
    if (accel->start(provider))  control->accelerator = accel;   // control + 0x158
}
```

**关键事实：`attach`/`start` 的参数是 `provider`，即 `IOPCIDevice` 本身，不是 control service。** 因此 `AppleParavirtFramebuffer` 与 `AppleParavirtAccelerator` 在 IOService plane 上是 **`IOPCIDevice` 的直接子节点、互为兄弟**。§4 的两套发现逻辑（`IOFramebuffer::probeAccelerator` 与 `IOAccelDisplayMachine::start`）都依赖这个拓扑。

`displayPortCount` 来自 MMIO（`[A]` `AppleParavirtGPUControl::start` RVA `0x102E` 读 `BAR + 0x22C`，0 时取 1，>8 时夹到 8）。

#### 2.6.3 本项目推荐的 plist 形状 `INFERRED`

本项目没有自己的 PCI 设备（云平台设备模型不可改，见 `00-OVERVIEW.md` §2.2），所以不能照抄 `IOPCIMatch`。两种形状：

**形状 A（推荐，与 APV 同构）——挂到 guest 已有的显卡 PCI 设备上：**

```xml
<key>IOKitPersonalities</key>
<dict>
  <key>ReimsGPUControl</key>
  <dict>
    <key>IOClass</key>          <string>ReimsGPUControl</string>
    <key>IOProviderClass</key>  <string>IOPCIDevice</string>
    <!-- 按实测的云平台 VGA/display 控制器填；也可以用 IOPCIClassMatch 匹配 class 0x030000 -->
    <key>IOPCIPrimaryMatch</key><string>0x????????</string>
    <key>IOMatchCategory</key>  <string>ReimsGPUControl</string>
    <key>IOProbeScore</key>     <integer>0</integer>
    <key>AcceleratorProperties</key>
    <dict>
      <key>IOMatchCategory</key>      <string>IOAccelerator</string>
      <key>MetalPluginName</key>      <string>ReimsGPUMetal</string>
      <key>MetalPluginClassName</key> <string>ReimsDevice</string>
      <key>IOAccelDisplayPipeCapabilities</key>
      <dict><key>DisplayPipeSupported</key><false/><key>TransactionsSupported</key><false/></dict>
    </dict>
  </dict>
</dict>
```

要点与依据：

- **`IOMatchCategory` 不要写 `IOFramebuffer`**，除非打算抢占已有 framebuffer 驱动。写 `IOFramebuffer` + 高 `IOProbeScore` 的效果是在该 match category 内独占该 provider（APV 就是这么做的，因为它要自己提供 framebuffer）。本项目若走"复用已有 framebuffer"（§4.4），必须用一个**自定义的 match category**，这样才能和已有的 framebuffer 驱动在同一个 `IOPCIDevice` 上共存。`KNOWN`（IOKit match category 语义）
- `FramebufferCount` 是 AGDC 的属性，只在继承 `AppleGraphicsDeviceControl` 时才有意义。本项目若不继承 AGDC（推荐不继承，AGDC 的 x86_64 ABI 本轮未分析），就不要写。`INFERRED`
- framebuffer 与 accelerator 都在 `ReimsGPUControl::start()` 里 `new` + `attach(getProvider())` + `start(getProvider())`，**绝不 attach 到 control 自身**。`KNOWN`（依据 §2.6.2）
- 若确实要发布自己的 framebuffer，它的 service 需要让 `IOAccelDisplayMachine` 找得到。三条可被找到的路径见 §4.2；最省事的是"直接 attach 到同一个 `IOPCIDevice`"。

**形状 B（不推荐）——`IOProviderClass = IOResources`：**
可以保证加载，但这样 framebuffer/accelerator 就不在任何 `IOPCIDevice` 的子树里，`IOAccelDisplayMachine::start` 和 `IOFramebuffer::probeAccelerator` 全部失配，必须自己覆写两边的发现逻辑。只在"guest 里连显卡 PCI 设备都没有"时才考虑。`INFERRED`

## 3. B. WindowServer 的用户 ABI（原 B-008）

### 3.1 `IOFramebuffer::newUserClient` 的 type 映射 `KNOWN`

`[G]` `IOFramebuffer::newUserClient(task_t, void*, UInt32 type, IOUserClient**)`，RVA `0x100CE`（vtable 槽 241）。

流程与返回码：

```c
if (waitQuietController() != 0) return <该错误>;      // 打印 "newUserClient waitQuietController failed"
gIOFBSystemWorkLoop->closeGate();

switch (type) {
case 0:                                              // IOFramebufferUserClient —— "server" 连接
    if (fServerConnect != NULL) { ret = 0xE00002C5; break; }      // kIOReturnExclusiveAccess，独占
    if (gIOFBConsoleFramebuffer == NULL || this == gIOFBConsoleFramebuffer)
        setPlatformConsole(NULL, 5, 0xB);
    if ((ret = this->open()) != 0) break;            // IOFramebuffer::open()，槽 305
    uc = IOFramebufferUserClient::withTask(owningTask);
    break;
case 1:                                              // IOFramebufferSharedUserClient —— "shared" 连接
    if (fSharedConnect != NULL) { uc = fSharedConnect; retain; goto done; }   // 已有则复用
    if (fServerConnect == NULL)  { ret = 0xE00002CD; break; }      // kIOReturnNotOpen
    uc = IOFramebufferSharedUserClient::withTask(owningTask);
    break;
default:
    ret = 0xE00002C2;                                // kIOReturnBadArgument
}
// 公共尾部：uc->attach(this)（槽 208）→ uc->start(this)（槽 186）；
// 失败则 uc->detach(this)（槽 209）+ uc->release()（槽 7），ret = 0xE00002D9 (kIOReturnNotAttached)
gIOFBSystemWorkLoop->openGate();
```

**用途区分：**

| type | 类 | 谁打开 | 用途 |
|---:|---|---|---|
| 0 | `IOFramebufferUserClient` | WindowServer（独占一个） | 全部控制面：改 mode、设 gamma/CLUT、设 cursor、取 pixel info、收/应答通知、映射 framebuffer 与 cursor 共享页 |
| 1 | `IOFramebufferSharedUserClient` | 其他进程（登录窗口、辅助功能、屏幕捕获等），**必须在 server 连接已存在之后** | 只读取共享态：cursor 共享页 + framebuffer 内存映射，没有 `externalMethod` 调度表 |

`IOFramebufferSharedUserClient` 的符号集（`[G]`，29 条）确实只有 `clientMemoryForType 0x2472C`、`getService 0x246BA`、`start 0x245F2`、`stop 0x24690`、生命周期与 `RpcGuard`，**没有 `externalMethod`、没有 `getTargetAndMethodForIndex`**。

### 3.2 `IOFramebufferUserClient::externalMethod` 调度表全量 `KNOWN`

`[G]` `IOFramebufferUserClient::externalMethod(uint32_t, IOExternalMethodArguments*, IOExternalMethodDispatch*, OSObject*, void*)`，RVA `0x2418C`。
静态表 `…::methodTemplate` 在 **RVA `0x37E20`**，跨度 `0x210` = **22 条 × 24 字节**，元素类型 `IOExternalMethodDispatch`：

```c
struct IOExternalMethodDispatch {   // 24 字节
    IOExternalMethodAction function;         // +0x00
    uint32_t checkScalarInputCount;          // +0x08
    uint32_t checkStructureInputSize;        // +0x0C
    uint32_t checkScalarOutputCount;         // +0x10
    uint32_t checkStructureOutputSize;       // +0x14
};
```

`0xFFFFFFFF` = `kIOUCVariableStructureSize`（下表记作 `VAR`）。

| sel | 处理函数（`[G]` RVA） | scalarIn | structIn | scalarOut | structOut | 语义 |
|---:|---|---:|---:|---:|---:|---|
| 0 | `extCreateSharedCursor` `0xCFAA` | 3 | 0 | 0 | 0 | `(shmemVersion, maxWidth, maxHeight)` → 建 `StdFBShmem_t` 共享页，见 §3.4 |
| 1 | `extGetPixelInformation` `0xD772` | 3 | 0 | 0 | `0xAC` | `(displayMode, depth, aperture)` → `IOPixelInformation`（172 B） |
| 2 | `extGetCurrentDisplayMode` `0xD80C` | 0 | 0 | 2 | 0 | → `(displayMode, depth)` |
| 3 | `extSetStartupDisplayMode` `0xD916` | 2 | 0 | 0 | 0 | `(displayMode, depth)` |
| 4 | `extSetDisplayMode` `0x1D7C4` | 2 | 0 | 0 | 0 | `(displayMode, depth)`，内部走 `doSetDisplayMode` `0x1D8CE` |
| 5 | `extGetInformationForDisplayMode` `0x1E17A` | 1 | 0 | 0 | `VAR` | `(displayMode)` → `IODisplayModeInformation`（36 B）或其扩展 |
| 6 | `extGetDisplayModeCount` `0x10402` | 0 | 0 | 1 | 0 | → `count` |
| 7 | `extGetDisplayModes` `0x1048C` | 0 | 0 | 0 | `VAR` | → `IODisplayModeID[]` |
| 8 | `extGetVRAMMapOffset` `0x10530` | 1 | 0 | 1 | 0 | `(aperture)` → `fVramMapOffset` |
| 9 | `extSetBounds` `0x105BC` | 0 | `VAR` | 0 | 0 | structIn 为 8（一个 `IOGBounds`）或 16（两个）；写 `StdFBShmem_t.screenBounds`，见 §3.4.2 |
| 10 | `extSetNewCursor` `0x14FD6` | 3 | 0 | 0 | 0 | `(cursorHandle, frame, options)` |
| 11 | `extSetGammaTable` `0xE34C` | 5 | `VAR` | 0 | 0 | `(channelCount, dataCount, dataWidth, ...)` + 数据块 |
| 12 | `extSetCursorVisible` `0x14A4A` | 1 | 0 | 0 | 0 | `(visible)` |
| 13 | `extSetCursorPosition` `0x14BB8` | 3 | 0 | 0 | 0 | `(x, y, options)` |
| 14 | `extAcknowledgeNotification` `0x195FA` | `VAR` | 0 | 0 | 0 | WindowServer 对 §3.5 通知的应答；实现在 `extAcknowledgeNotificationImpl` `0x194C6` |
| 15 | `extSetColorConvertTable` `0x10862` | 1 | `VAR` | 0 | 0 | `(index)` + 表 |
| 16 | `extSetCLUTWithEntries` `0xED6A` | 2 | `VAR` | 0 | 0 | `(index, options)` + `IOColorEntry[]` |
| 17 | `extValidateDetailedTiming` `0x107B4` | 0 | `VAR` | 0 | `VAR` | in/out 都是 `IODetailedTimingInformationV2`（160 B） |
| 18 | `extGetAttribute` `0x1DCE0` | 1 | 0 | 1 | 0 | `(attribute)` → `value` |
| 19 | `extSetAttribute` `0x1DB1A` | 2 | 0 | 0 | 0 | `(attribute, value)` |
| 20 | `extSetHibernateGammaTable` `0xE172` | 3 | `VAR` | 0 | 0 | |
| 21 | `extRestoreCDBlob` `0x1E6EC` | 4 | 0 | 0 | 0 | 走 `restoreCDBlob(int, IOMemoryDescriptor*)` `0x1E806` |

另外两个**不在表里**的 `IOUserClient` 覆写（`[G]`）：

- `IOFramebufferUserClient::registerNotificationPort(ipc_port*, UInt32, UInt32)` RVA `0x23E66` → 转给 `IOFramebuffer::extRegisterNotificationPort` `0x19676`。WindowServer 用它注册接收 §3.5 通知的 mach port。
- `IOFramebufferUserClient::setProperties(OSObject*)` RVA `0x240EA` → `IOFramebuffer::extSetProperties(OSDictionary*)` `0x1E288`。
- `IOFramebufferUserClient::connectClient(IOUserClient*)` RVA `0x2425A`（把 shared 连接挂上来）。

**对本项目的意义：** 这 22 条全部由 `IOFramebuffer` 基类实现，并转调 §2 的虚方法。**本项目一条都不需要自己写。** 只要 §2 的虚方法行为正确，整张用户 ABI 自动可用。这就是原 B-008 实质关闭的原因。

> 对照：`[G]` 里另外两张表走的是**旧式** `getTargetAndMethodForIndex` + `IOExternalMethod`（64 位下 48 字节/条，因为 `IOMethod` 是 16 字节的成员函数指针）：`IOI2CInterfaceUserClient::…::methodTemplate` RVA `0x2E0B0`（条数本轮未数），与 `IOAccelerationUserClient::…::methodTemplate` RVA `0x3A800`（跨度 `0x60` = 2 条：`extCreate 0x251B2` / `extDestroy 0x2528E`）。后者是 IOGraphicsFamily 自带的 `IOAccelerator` 基类的 surface-ID 分配器，与 IOAcceleratorFamily2 的 `IOAccelerator` 概念不同，不要混。

### 3.3 两个 user client 的 `clientMemoryForType` 内存类型 `KNOWN`

**`IOFramebufferUserClient::clientMemoryForType(UInt32 type, ...)`，`[G]` RVA `0x23FDE`：**

| type | 返回 | 备注 |
|---:|---|---|
| `100` | `IOFramebuffer::extCopySharedCursor()` `0xD588` → `sharedCursor`（`IOBufferMemoryDescriptor`） | 首次调用时执行 `publishResource("WindowServer", NULL)` —— 这是 WindowServer 已启动的全局信号 |
| `110` | `fb->getVRAMRange()`（vptr `+2480` = `__ZTV` 槽 312） | framebuffer 内存 |
| 其他 | `IOFramebuffer::extCopyUserMemory(type, …)` `0xD5F4` → `userAccessRanges->getObject(type)`，再 `OSDynamicCast(IOMemoryDescriptor, …)` | `userAccessRanges[0]` 由 `doSetup` 设为 aperture；更多项由 `setUserRanges()`（默认 stub，RVA `0x1D0DA`）添加 |

对象已 terminate 或 rpc 计数为 `-1` → `0xE00002D7`（`kIOReturnOffline`）。返回 NULL → `0xE00002C2`。

**`IOFramebufferSharedUserClient::clientMemoryForType`，`[G]` RVA `0x2472C`：**

| type | 返回 | 备注 |
|---:|---|---|
| `100` | `extCopySharedCursor()`，并把 `*size` **硬编码为 4096** | 共享方只看到一页 |
| `110` | `fb->getVRAMRange()`，但**前面有一道权限闸**：`IOUserClient::clientHasPrivilege(current_task(), kIOClientPrivilegeLocalUser) == kIOReturnSuccess` 才放行，否则返回 NULL → `0xE00002C2` | 见下 |
| 其他 | NULL → `0xE00002C2` | 共享连接拿不到任意 user range |

**那道 `"local"` 闸的真身 `KNOWN`**（原文此处记为"名字判定门 / 名字来源未查清"，现更正）：

`[G]` `+0x2472C` 的 type-110 分支逐指令是

```
0247A0  jnz   <other>                  ; type != 110
0247A2  call  near ptr 1031Eh          ; rax = current_task()      —— 零实参
0247A7  lea   rsi, aLocal              ; rsi = "local"             —— [G] __cstring RVA 0x2B878
0247AE  mov   rdi, rax
0247B1  call  near ptr 10678h          ; = IOUserClient::clientHasPrivilege(securityToken, name)
0247B6  test  eax, eax
0247B8  jz    loc_14D08810             ; == kIOReturnSuccess 才继续
024810  mov   rdi, [r14+0D8h]
02481A  call  qword ptr [rax+9B0h]     ; fb->getVRAMRange()
```

它**不是字符串比较**，而是 `clientHasPrivilege` 的 `IOReturn` 与 0 比较。`"local"`
就是公开头文件 `xnu/iokit/IOKit/IOUserClient.h` 里的
`#define kIOClientPrivilegeLocalUser "local"`（同一组还有
`kIOClientPrivilegeAdministrator "root"`、`kIOClientPrivilegeForeground "foreground"`）。
来源：[apple-oss-distributions/xnu `iokit/IOKit/IOUserClient.h`](https://github.com/apple-oss-distributions/xnu/blob/main/iokit/IOKit/IOUserClient.h)。
（内容已改写以符合许可限制。）

两条 stub 由此同时锚定（stub 页是 System KC 级共享的，对 `[F2]` / `[A]` 同样成立）：
`0x1031E = current_task()`、`0x10678 = IOUserClient::clientHasPrivilege`。旁证：
`0x1031E` 在 `[G]` 的另外三个调用点（`extAcknowledgeNotificationImpl +0x19591`、
`extRestoreCDBlob +0x1E748`、`IOGDiagnosticGTraceClient::makeUser +0x25FEE`）都是
把返回值当作 `IOMemoryDescriptor::withAddressRange(addr, len, options, task)`
（stub `0x1048C`）的第 4 个 `task_t` 实参。

**对本项目的后果：** `IOFramebufferSharedUserClient` 的 framebuffer 映射只对
**本地登录用户的进程**开放。研发期 SSH 进去跑的测试程序**不是** local user，
拿 type 110 会被这道闸挡掉并返回 `0xE00002C2`；要测 framebuffer 映射必须走
`IOFramebufferUserClient`（它的 type 110 没有这道闸），或者在 VNC 控制台的
图形会话里跑。这是本项目在 `80-TEST-HARNESS.md` 侧需要注意的一条。`KNOWN`

**实现要求：** 本项目只要正确实现 `getVRAMRange()`（§2.2）就同时满足两个 client 的 type 110。type 100 完全由基类管理，不需要介入。

### 3.4 cursor 共享页：`StdFBShmem_t` `KNOWN`

#### 3.4.1 分配与尺寸

`[G]` `IOFramebuffer::createSharedCursor(int version, int maxWidth, int maxHeight)`，RVA `0xD1A8`（由 selector 0 调用）：

```c
if (maxWidth > 0x100 || maxHeight > 0x100)      return 0xE00002BD;   // kIOReturnNoMemory 路径上的尺寸上限：256
if (maxWidth == 0   || maxHeight == 0)          return 0xE00002C2;
if ((version & 0xFF) == 2)        numFrames = 4;
else if ((version & 0xFF) == 3) { numFrames = (version >> 16) & 0xFF;   // 1..32
                                  if (numFrames > 32) return 0xE00002BD;
                                  if (numFrames == 0) return 0xE00002C2;
                                  setProperty("IOFBWaitCursorFrames", numFrames - 1, 32);
                                  setProperty("IOFBWaitCursorPeriod", 33333333, 32); }   // ns，= 30 Hz
else                                            return 0xE00002C7;   // kIOReturnUnsupported

size = 4*maxWidth*maxWidth
     + max(4*maxWidth*maxWidth, 4*maxHeight*maxHeight)
     + 4*maxHeight*maxHeight*(numFrames - 1)
     + 240;                                      // 240 = sizeof(StdFBShmem_t)

if (sharedCursor && sharedCursor->getLength() != size) { sharedCursor->release(); sharedCursor = NULL; }
if (!sharedCursor) sharedCursor = IOBufferMemoryDescriptor::withOptions(0x10000, size, 1);
priv = (StdFBShmem_t *) sharedCursor->getBytesNoCopy();
bzero(priv, size);
priv->version               = version & 0xFF;
priv->structSize            = size;
priv->cursorShow            = 1;
priv->hardwareCursorCapable = this->haveHWCursor;
maxCursorSize = { maxWidth, maxWidth };
```

`options = 0x10000`：**`kIOMemoryKernelUserShared`**。`KNOWN`

（原文此处推断为 `kIOMemoryPersistent`，**现更正**。`kIOMemoryPersistent` 确实是
`0x00010000`，但它属于 `IOMemoryDescriptor.h` 的 `withOptions` 位组，而这里调用的是
`IOBufferMemoryDescriptor::withOptions(options, capacity, alignment)`，它用的是
`IOBufferMemoryDescriptor.h` 自己那一组：`kIOMemorySharingTypeMask = 0x000F0000`、
`kIOMemoryUnshared = 0`、**`kIOMemoryKernelUserShared = 0x00010000`**。头文件原文对
该位的说明是"要求这块内存同时映射进内核与客户端应用"—— 对一个要和 WindowServer
共享的游标页来说这正是唯一说得通的语义，而 `kIOMemoryPersistent` 在 Buffer MD 的
合法位组里根本不存在。来源：[apple-oss-distributions/xnu `iokit/IOKit/IOBufferMemoryDescriptor.h`](https://github.com/apple-oss-distributions/xnu/blob/main/iokit/IOKit/IOBufferMemoryDescriptor.h)
与 [同仓库 `iokit/IOKit/IOMemoryDescriptor.h`](https://github.com/apple-oss-distributions/xnu/blob/main/iokit/IOKit/IOMemoryDescriptor.h)。内容已改写以符合许可限制。）

**对本项目：** 自己建 framebuffer 后备内存时，凡是要让用户态映射到的
`IOBufferMemoryDescriptor` 都必须带 `kIOMemoryKernelUserShared`，否则
`clientMemoryForType` 返回的描述符在 `createMappingInTask` 时拿不到用户态视图。

#### 3.4.2 字段布局（240 字节，取自 `[G]` IDA 类型库 `StdFBShmem_t`）

| 偏移 | 字段 | 类型 | 写者 | 说明 |
|---:|---|---|---|---|
| `0x00` | `cursorSema` | `OSSpinLock`（4 B） | 双方 | 保护整页的自旋锁 |
| `0x04` | `frame` | `int` | 双方 | 当前动画帧号 |
| `0x08` | `cursorShow` | `char` | 内核 | 0 = 显示；>0 = 隐藏计数 |
| `0x09` | `cursorObscured` | `char` | 内核 | |
| `0x0A` | `shieldFlag` | `char` | WS | 置 1 表示有 shield 矩形 |
| `0x0B` | `shielded` | `char` | 内核 | |
| `0x0C` | `saveRect` | `IOGBounds`（8 B） | 内核 | 软件光标下保存的背景矩形 |
| `0x14` | `shieldRect` | `IOGBounds` | WS | |
| `0x1C` | `cursorLoc` | `IOGPoint`（4 B） | 双方 | 全局坐标 |
| `0x20` | `cursorRect` | `IOGBounds` | 内核 | |
| `0x28` | `oldCursorRect` | `IOGBounds` | 内核 | |
| `0x30` | `screenBounds` | `IOGBounds` | WS（selector 9） | 该 framebuffer 在全局坐标里的矩形 |
| `0x38` | `version` | `int` | 内核 | 2 或 3 |
| `0x3C` | `structSize` | `int` | 内核 | 整页实际字节数 |
| `0x40` | `vblTime` | `AbsoluteTime` | 内核 | 最近一次 VBL 的绝对时间 |
| `0x48` | `vblDelta` | `AbsoluteTime` | 内核 | |
| `0x50` | `vblCount` | `uint64_t` | 内核 | **WindowServer 的帧计数来源** |
| `0x58` | `vblDrift` | `uint64_t` | 内核 | |
| `0x60` | `vblDeltaMeasured` | `uint64_t` | 内核 | |
| `0x68` | `vblDeltaReal` | `AbsoluteTime` | 内核 | 由 `setVBLTiming` 从 timing 算出的理论周期 |
| `0x70` | `reservedC[22]` | `unsigned int` | — | 88 字节 |
| `0xC8` | `hardwareCursorCapable` | `uint8_t` | 内核 | |
| `0xC9` | `hardwareCursorActive` | `uint8_t` | 内核 | |
| `0xCA` | `hardwareCursorShields` | `uint8_t` | 内核 | |
| `0xCB` | `reservedB[1]` | `uint8_t` | — | |
| `0xCC` | `cursorSize[4]` | `IOGSize`（4×4 B） | WS | 每帧尺寸 |
| `0xDC` | `hotSpot[4]` | `IOGPoint`（4×4 B） | WS | 每帧热点 |
| `0xF0` | — | — | — | 之后是 cursor 图像数据区，按 §3.4.1 公式排布 |

`IOGBounds` = `{SInt16 minx, maxx, miny, maxy}`；`IOGPoint` = `{SInt16 x, y}`；`IOGSize` = `{SInt16 width, height}`。

**WindowServer 拿它干什么：** ① 把 `screenBounds` 告诉内核（selector 9 → `extSetBounds` `0x105BC`，它会同时按新旧 `screenBounds` 的差量平移 `saveRect`，并在硬件光标激活时重新 `setCursorState`）；② 上传 cursor glyph 与 hotSpot/size；③ **轮询 `vblCount` / `vblTime` / `vblDeltaReal` 做帧节奏**；④ 用 `cursorSema` 与内核互斥。

### 3.5 swap / flush / vblank / 通知 `KNOWN`

#### 3.5.1 没有 "swap" selector

`IOFramebufferUserClient` 的 22 条 selector 里**没有任何提交帧 / flip / swap 的调用**。IOFramebuffer 这一层的模型是：WindowServer 把 framebuffer 内存（type 110）映射进自己的地址空间后**直接写像素**，不存在"提交"动作。加速合成路径（scanout 换 buffer）走的是 accelerator 侧的 `IOAccelDisplayPipe` 事务，不走 framebuffer user client，详见 §4.1 与 `12-KERNEL-IOSURFACE.md` §5。

**对本项目的直接后果：** 如果本项目**不**声明 `DisplayPipeSupported`，那么 WindowServer 的输出就是直接写我们那块 `IOBufferMemoryDescriptor`。这对"Lavapipe 渲染目标 = framebuffer 内存"的设计是最简路径：不需要实现任何提交协议。`INFERRED`（基于本节与 §4.1 的机制，尚无 `TESTED` 运行证据）

#### 3.5.2 VBL 通路

```
硬件/定时器 → 驱动调用注册的 IOFBInterruptProc
            → [G] IOFramebuffer::handleVBL(IOFramebuffer*, void*)   RVA 0x1470A
               ├─ priv->vblCount += n;  priv->vblTime = now;
               ├─ priv->vblDelta / vblDeltaReal / vblDrift / vblDeltaMeasured 更新
               └─ semaphore_signal(vblSemaphore)
```

- 驱动侧只需在 §2.1 槽 348 `registerForInterruptType(kIOFBVBLInterruptType, proc, target, ref, &handle)` 里登记 `proc`，然后在每个 vblank 周期调用它。`handleVBL` 会被 IOGraphics 作为 `proc` 注册进来。
- WindowServer 侧通过 `getNotificationSemaphore(interruptType, &sema)`（槽 351，`[G]` `0x14A3E`，基类已实现）拿到 `vblSemaphore`，在上面 `semaphore_wait`。另有 `[G]` `IOFramebuffer::getVBLTime`（槽 271，`0x149B4`）与 `getTimeOfVBL`（`0xEC6C`）。
- VBL 理论周期由 `[G]` `IOFramebuffer::setVBLTiming`（RVA `0x173EC`）从 `getTimingInfoForDisplayMode` 返回的 `IODetailedTimingInformationV2` 算出，写入 `priv->vblDeltaReal`。

**APV 的 VBL 是纯软件定时器 `KNOWN`：** `[A]` `AppleParavirtFramebuffer::setVBLTimer(bool)` RVA `0x5714`：

```c
rate_fixed1616 = (pixelClock << 16) / ((hActive + hBlanking) * (vActive + vBlanking));
period_ns      = 0x3B9ACA000000 / rate_fixed1616;      // 1e9 << 16 / rate
vblTimer->wakeAtTime(deadline, leeway, ...);           // IOTimerEventSource，vtable +528
```
VBL 事件源在 `[A]` `AppleParavirtFramebuffer::start` RVA `0x53D4` 里创建（`IOTimerEventSource::timerEventSource(1, this)`），加入 `getWorkLoop()`。

**本项目照抄即可：** 用一个 `IOTimerEventSource` 按 mode 的刷新率周期性调用注册的 `IOFBInterruptProc`。不需要任何真实中断源。

#### 3.5.3 通知与应答（电源/模式切换的握手）

`[G]` `IOFramebuffer::notifyServer(uint8_t state)` RVA `0x1698E`：

```c
serverMsg->msgh_id_field /* serverMsg[7] */ = state;         // state ∈ {0,1,2} 一组，{3,4} 另一组
// state 1 时若 fbWSAA 相关位置位，追加 getAttribute(0x64737379 /* 'dsyt'? 见下 */) 的返回值到低 12 位
// 若启用 seq，追加 ((seq+1) << 16) & 0x7FFF0000
mach_msg_send_from_kernel(serverMsg, size);                  // 发到 extRegisterNotificationPort 注册的 port
if (发送成功 && state <= 2)
    gIOFBServerAckTimer->setTimeout(25, 1000000000);          // 25 秒超时
if (state == 1) 对 fServerConnect 发 message
```

- 注册 port：selector 之外的 `registerNotificationPort` → `[G]` `IOFramebuffer::extRegisterNotificationPort(ipc_port*, UInt32 type, UInt32 ref)` RVA `0x19676`。
- 应答：selector **14** `extAcknowledgeNotification`（可变 scalar 个数）→ `extAcknowledgeNotificationImpl` `0x194C6` → `[G]` `IOFramebuffer::serverAcknowledgeNotification(int)` `0x179EC`。
- 超时处理：`[G]` `IOFramebuffer::serverPowerTimeout` `0x1337E`。
**state 0–4 的逐值语义已查清 `KNOWN`**（原文只有分组与 25 秒超时）。方法：
`notifyServer` 在 `[G]` 只有 **4 个调用点**，每个调用点的实参都能直接读出来。

| state | 谁发 | 什么时候 | 记在哪 |
|---:|---|---|---|
| **0** | `IOFramebuffer::systemWork` `[G] +0x12653` | `gIOFBCurrentWSPowerOn` 由真变假时。判定式是 `wsOn = !(events & 0x10) && (gIOFBIsMuxSwitching \|\| gIOFBSystemPower)`（`+0x125C6..+0x125E8`），变化时先 `gIOFBDimEngineState \|= 1`、`gIOFBGlobalEvents \|= 0x80000000`，再对 `gAllFramebuffers` 的每一个发 `notifyServer(wsOn)` | `__private+0x4F0`（已发）/ `+0x4F4`（已应答） |
| **1** | 同上 | `gIOFBCurrentWSPowerOn` 由假变真时（同一处，实参就是 `wsOn`）；此时还会额外置 `gIOFBPostWakeNeeded = 1`，并在 `notifyServer` 内部对 `fServerConnect` 单独投一条消息（`+0x16A4x` 的 `LABEL_39` 分支） | 同上 |
| **2** | **本构建内无发送点** | `notifyServer` 的 `state <= 2` 分支能处理它（同一对槽、同一 25 秒 ack 定时器），但 `[G]` 里没有任何代码传 2 | 同上 |
| **3** | `IOFramebuffer::dimEngine` `[G] +0x17824` | **退出 dim**：先 `state &= ~0x10`（`+0x177ED` 的 `and al, 0EFh`），再 `and 0x57` 收敛状态位，然后遍历 `gAllFramebuffers` 发 3 | `__private+0x4F8` / `+0x4FC` |
| **4** | `IOFramebuffer::dimEngine` `[G] +0x176A8` | **进入 dim**：`state` 的 `0x20` 位为 0 且 `0x08` 位为 1 时，取消 `sIOFBDimDisplayTimer`、置 `state = 0x18 \| (old & 4)`，然后遍历 `gAllFramebuffers` 发 4 | 同上 |
| —（重放） | `extRegisterNotificationPort` `[G] +0x1974B` | 新注册通知 port 时，把 `__private+0x4F0` 的**低字节**（即上次已发的 {0,1,2} 组状态）原样重发一次，并把 `__private+0x4F0` 复位为 1 | `+0x4F0` |

两条独立的去重/应答规则（`notifyServer` 内）：

- 去重：`state <= 2` 时比 `__private+0x4F0 & 0xF`，`state ∈ {3,4}` 时比 `__private+0x4F8 & 0xF`，相同则整个函数空转。
- **25 秒 ack 定时器只对 {0,1,2} 组装**（`gIOFBServerAckTimer->setTimeout(25, 1e9)`）；{3,4} 组发完即忘，不等应答。
- state 0 时在 `/chosen` 节点上 `removeProperty("IOScreenLockState")`；state 非 0 时（且本 framebuffer 是 `gIOFBConsoleFramebuffer` 或 `gIOFBSetPreviewImage` 置位）在 `/chosen` 上 `removeProperty("IOPreviewBuffer")`、在 provider 上 `removeProperty("IOHibernatePreviewActive")`，然后 `setProperty("IOScreenRestoreState", __private+596, 4)`。
- state 1 且 `__private+1258 & 1` 时，把 `getAttribute('dstt' = 0x64737474)` 的返回值并进消息的低 12 位（原文此处把 fourcc 记作 `0x64737379 /* 'dsyt'? */`，**现更正为 `0x64737474` = `'dstt'`**，由 `[G] +0x16A2x` 的立即数读出）。

**对本项目不变：整条链都在基类里，不需要碰。** 新增的一条实现提示：如果本项目的
framebuffer 不是 `gIOFBConsoleFramebuffer`、也不设 preview image，那么 state 1/2 的
`/chosen` 属性清理分支根本不执行，state 的全部可观察效果就只剩"给 WindowServer
投一条 mach message"。`KNOWN`

notifyServer 的调用点集中在 `[G]` `IOFramebuffer::systemWork` `0x12402`、`checkPowerWork` `0xB2F8`、`postWake` `0x16D78`、`processConnectChange` `0xAA2C`。**本项目不需要碰这条链**：它完全在基类里，只要 `setPowerState`/`powerStateWillChangeTo` 不被覆写，默认行为即可。

#### 3.5.4 WindowServer "accelerated access" 握手

`[G]` `IOFramebuffer::setWSAAAttribute(uint32_t, uint32_t)` RVA `0x1CD64`（另有 clone `0x294C7`），由 `setAttribute('wsrv')` 路径进入。`[A]` 的 `setAttribute('wsrv')` 处理见 §2.4：按 `value & 0xF` 对 framebuffer 内存描述符调 `prepare`/`complete` 一类的方法。

accelerator 侧的对偶是 `[F2]` `IOAccelDisplayMachine::wsaa_will_enter_defer / wsaa_did_enter_defer / wsaa_will_exit_defer / wsaa_did_exit_defer`（RVA `0xE464` / `0xE52C` / `0xE5F4` / `0xE6BC`）与 `IOAccelDisplayPipe::wsaa*Defer`（`[A]` 的 APV 覆写在 `0xC3AC`–`0xC3F4`）。

`'wsrv'` 的位域逐位语义本轮**未查清**。查清方法：在 `[F2]` 对 `IOAccelDisplayMachine::wsaa_*` 的四个入口做 xref 回溯到 `[G]` 的 `setWSAAAttribute`，并对照 `IOGraphicsTypes.h` 的 `kIOWSAA*` 枚举（公开头文件里有 `kIOWSAA_Unaccelerated / Accelerated / DeferStart / DeferEnd / Transactional / Hibernate` 等）。本项目第一版建议：`getAttribute('wsrv')` 回读、`setAttribute('wsrv')` 只记录不动作（APV 的动作只是对 framebuffer 内存 prepare/complete，纯内存后备下可省）。

## 4. C. accelerator 与 display 的关联

### 4.1 `IOAccelDisplayPipe` / `IOAccelLegacyDisplayPipe` / `IOAccelDisplayMachine` 的作用 `KNOWN`

`[F2]` 里这三组类的分工：

| 类 | 符号数 | 职责 |
|---|---:|---|
| `IOAccelDisplayMachine` | 49 | **每个 accelerator 一个。** 枚举 framebuffer、为每个 framebuffer 建一条 pipe、聚合 mode change / power / WSAA / 事务完成事件。关键方法：`start(IOPCIDevice*) 0xDC52`、`found_framebuffer(IOFramebuffer*) 0xDFFA`、`getFramebufferCount 0xDE8E`、`getIOFramebuffer(uint) 0xDFC0`、`getDisplayPipe(uint) 0xDFEA`、`getFramebufferResource(uint,uint) 0xDFD4`、`display_mode_will_change(uint) 0xE0B0` / `did_change 0xE280`、`framebuffer_will_power_off 0xE784` / `did_power_on 0xE82A`、`framebuffer_terminated 0xE8D0`、`finish_transaction_queue 0xE99A`、`get_finished_transactions 0xE9AE`、`is_current_display_resource(IOAccelResource2*) 0xEEF0` |
| `IOAccelDisplayPipe` | 126 | **每个 framebuffer 一条。** 事务型 scanout：`newDisplayPipeTransaction`、`validateTransaction`、`beginTransaction(IOAccelEvent*)`、`submitTransaction(IOAccelDisplayPipeTransaction2*)`、`isTransactionComplete`、gamma/scaler/游标、VBL 中断开关。`init(IOGraphicsAccelerator2*, IOAccelDisplayMachine*, IOFramebuffer*, uint32_t)` 在 RVA `0x49358` |
| `IOAccelLegacyDisplayPipe` / `IOAccelLegacyDisplayMachine` | 54 / 45 | **旧式 scanout**：`setup_scanout(IOAccelLegacySurface*)`、`reset_scanout`、`setup_fullscreen`、`submit_scanout_flip(IOAccelEvent*, uint, uint)`、`submit_flip`、`getScanoutSurface(uint)`、`getFullScreenSurface(uint)`、`getWindowServerFullScreenAssemblySurface(uint)`、`enableFlipInterrupt/disableFlipInterrupt`、`setStereo`。这是 "一个 surface 当 scanout buffer、翻页" 的模型 |

`AppleParavirtGPU` 走**新式**（事务）路径：`AppleParavirtDisplayPipe : IOAccelDisplayPipe`、`AppleParavirtDisplayMachine : IOAccelDisplayMachine`（`[A]` 的 `superClass` 槽解码后分别指向 `[F2]` RVA `0x816D8` = `IOAccelDisplayPipe::gMetaClass` 与 `0x810C0` = `IOAccelDisplayMachine::gMetaClass`）。

#### `IOAccelDisplayPipeCapabilities` 对应的代码路径 `KNOWN`

`[F2]` `IOAccelDisplayPipe::copyCapabilities()` RVA `0x4A38D` 全文只有一句：

```c
return accelerator->copyProperty("IOAccelDisplayPipeCapabilities");   // vptr+744 = IORegistryEntry 槽 95
```

即 **capabilities 字典是从 accelerator service 的属性表上读的**，键名字符串在 `[F2]` RVA `0x6097D`。

`DisplayPipeSupported` / `TransactionsSupported` 这两个**内层键名的字符串在 `[F2]` 与 `[G]` 的 `__cstring` 里都不存在**，所以这两个布尔不是在这两个 kext 里消费的。

**"谁读这两个布尔"已查清：在已取得的 x86_64 样本里没有任何人读。** `KNOWN`（否定结论）

本轮把这两个字面量（以及外层键 `IOAccelDisplayPipeCapabilities`）在下列样本上做了
全文件字节搜索：

| 样本 | 层级 | `DisplayPipeSupported` | `TransactionsSupported` | `IOAccelDisplayPipeCapabilities` |
|---|---|:---:|:---:|:---:|
| `com.apple.iokit.IOAcceleratorFamily2` | T2 | 0 | 0 | **1（`__cstring`）** |
| `com.apple.iokit.IOGraphicsFamily` / `IOSurface` / `IOPCIFamily` / `IOGPUFamily` / `AppleGraphicsDeviceControl` / `AppleParavirtGPU` | T2 | 0 | 0 | 0 |
| `IOAccelerator.framework`（`…-frameworks/analysis-input/IOAccelerator`） | T3 | 0 | 0 | 0 |
| `Metal.framework`（同上 `Metal`） | T3 | 0 | 0 | 0 |
| `SkyLight`（同上 `SkyLight`） | T3 | 0 | 0 | 0 |
| `libsystem_sandbox.dylib`（同上） | T3 | 0 | 0 | 0 |

唯一引用外层键的代码就是本节上面那句 `IOAccelDisplayPipe::copyCapabilities()`
（`[F2] +0x4A378`，字面量在 `[F2] +0x6097D`），而**它在 `[F2]` 内没有任何调用点**
（全件 `call`/`jmp` 扫描）。所以整条链到此为止：字典被读出来以后，在我们手上的样本里
没有人去看它的内层布尔。

**结论改写：** 原文建议"把 `IOAccelDisplayPipeCapabilities` 设成两个 false"是安全的，
但理由不是"让 WindowServer 走非加速路径"，而是**它在本构建上根本没有观察者**。
真正决定 type-4（display pipe）user client 能不能建立的闸是**内核侧的
`IOAccelConfig cfg+0x47`**（`10-KERNEL-ACCELERATOR.md` §3.1 / §3.3.3），由
`populateAccelConfig()` 代码写入；APV 在那里硬编码 `1`，**而不是从 plist 的
`IOAccelDisplayPipeCapabilities.DisplayPipeSupported` 读**（该字面量在 `[A]` 的
`__cstring` 里为 0 次）。所以 plist 这一项写不写都不影响 type-4 闸门。`KNOWN`

**对本项目的实际建议：** 先把 `IOAccelDisplayPipeCapabilities` 设成 `{DisplayPipeSupported=false, TransactionsSupported=false}`（或干脆不设），让 WindowServer 走非加速 scanout（直接写 framebuffer 内存）。等基本桌面跑起来再考虑事务路径。`INFERRED`

而且注意：`AcceleratorProperties` 这个字面量在 7 个 x86_64 kext 的 `__cstring` 里**只出现在 `AppleParavirtGPU` 自己**（`[F2]`、`[G]`、AGDC 都没有）。说明"把 plist 里的 `AcceleratorProperties` 子字典合并到 accelerator service 的属性表上"这件事是 **APV 自己做的**，不是框架行为。本项目要么照做（在 accelerator 的 `start()` 里读本 kext personality 的 `AcceleratorProperties` 再 `setProperty` 逐条展开），要么直接在 accelerator 的 `start()` 里硬编码 `setProperty("IOAccelDisplayPipeCapabilities", dict)` 等。`KNOWN`（字符串归属）+ `INFERRED`（合并代码位置未逐指令确认）

### 4.2 `IOAccelDisplayMachine` 怎么找到 framebuffer `KNOWN`

`[F2]` `IOAccelDisplayMachine::start(IOPCIDevice *pci)` RVA `0xDC52`，逐句还原：

```c
OSIterator *it   = pci->getChildIterator(gIOServicePlane);
const OSSymbol *fbCat = OSSymbol::withCString("IOFramebuffer");      // [F2] __cstring RVA 0x59922

/* 路径 ①：PCI 设备的每个子节点，看它在 "IOFramebuffer" match category 下的 client */
while ((IOService *child = OSDynamicCast(IOService, it->getNextObject()))) {
    IOFramebuffer *fb = OSDynamicCast(IOFramebuffer,
                            child->copyClientWithCategory(fbCat));   // vptr+1056 = IOService 槽 134
    if (fb) { this->found_framebuffer(fb);  fb->release(); }          // vptr+2264 = 槽 285
}
it->release();

/* 路径 ②③：PCI 设备的直接 client，以及这些 client 的 client（再下一层） */
OSIterator *it2 = pci->getClientIterator();                          // IOService 槽 215
while ((OSObject *c = it2->getNextObject())) {
    if (IOFramebuffer *fb = OSDynamicCast(IOFramebuffer, c))         // ② 直接命中
        this->found_framebuffer(fb);
    else {                                                            // ③ 下一层
        OSIterator *it3 = ((IOService*)c)->getClientIterator();        // vptr+1704 = 槽 215
        while ((OSObject *x = it3->getNextObject()))
            if (IOFramebuffer *fb2 = OSDynamicCast(IOFramebuffer, x))
                this->found_framebuffer(fb2);
        it3->release();
    }
}
it2->release();
return true;    /* 返回 (framebufferCount == 0) 取反的那个布尔，见下 */
```

`IOService` 槽 134 / 215 的身份已用 `[K]` `__ZTV9IOService` 逐槽核对：134 = `copyClientWithCategory(const OSSymbol*)`，215 = `getClientIterator()`。

`[F2]` `IOAccelDisplayMachine::found_framebuffer(IOFramebuffer *fb)` RVA `0xDFFA`：

```c
for (i = 0; i < this->pipeCount; ++i)
    if (fb == this->pipes[i]->getFramebuffer()) return true;          // 已有则幂等
if (this->pipeCount >= accelerator->maxFramebuffers /* accel + 0xCB0 */) {
    log("trying to init too many framebuffers");  return false;
}
this->pipes[this->pipeCount] = accelerator->vtable[291](fb);          // 新建并 init 一条 display pipe
IOGraphicsAccelerator2::find_vram_descriptor(accelerator);
++this->pipeCount;
return true;
```

`pipes[]` 在对象 `+ (17 + n) * 8`；`pipeCount` 在 `+0x108`。

### 4.3 `_SLSAcceleratorForDisplayNumber` 在内核侧依赖什么 `KNOWN`

**答案：依赖写在 IOFramebuffer service 属性表上的四个属性，以及 framebuffer 自己发布的 OpenGL index。它们由双方各写一半。**

#### accelerator → framebuffer：`IOAccelDisplayPipe::init` 写属性

`[F2]` `IOAccelDisplayPipe::init(IOGraphicsAccelerator2 *accel, IOAccelDisplayMachine *dm, IOFramebuffer *fb, uint32_t index)` RVA `0x49358`，关键段：

```c
this->accel = accel;  this->displayMachine = dm;  this->framebuffer = fb;  this->index = index;
...
/* 注册 framebuffer 通知 —— 直接调用 IOGraphicsFamily 的导出函数 */
this->fbNotifier = IOFramebuffer::addFramebufferNotificationWithOptions(
        fb,                                     /* 目标 framebuffer           */
        IOAccelDisplayPipe::display_change_handler,
        this,                                   /* OSObject *target           */
        index,                                  /* void *ref                  */
        368, 0, 6223);                          /* options / groupIdx / prio  */
        /* 调用地址 0x14D0374A → [G] RVA 0x1F74A
           = IOFramebuffer::addFramebufferNotificationWithOptions(...)  */
if (!this->fbNotifier) { log("failed to add display change notification"); return false; }

/* 把 accelerator 的身份写到 framebuffer 的属性表上 */
OSObject *types = accel->copyProperty("IOCFPlugInTypes");           // vptr+696 = IORegistryEntry 槽 89
fb->setProperty("IOCFPlugInTypes", types);
if (accel->vtable[125](buf /*512 B*/, &len, <OSSymbol>)) {          // 生成 IOAccelTypes blob
    fb->setProperty("IOAccelTypes",    buf, len);                    // OSData
    fb->setProperty("IOAccelIndex",    index, 32);                   // OSNumber，32 bit
    fb->setProperty("IOAccelRevision", 2,     32);                   // OSNumber，32 bit
    return true;
}
return false;
```

字符串位置：`[F2]` `"IOAccelIndex"` RVA `0x60970`、`"IOAccelDisplayPipeCapabilities"` `0x6097D`、`"IOAccelTypes"` `0x60963`、`"IOAccelRevision"` `0x5F45D`。

#### framebuffer → 自己：`IOFramebuffer::assignGLIndex`

`[G]` `IOFramebuffer::assignGLIndex()` RVA `0x1987A`：沿 `nextDependent` 链数出这组相关 framebuffer 的个数 n（上限 32），在全局位图 `gIOFBOpenGLMask` 里找一段连续 n 位，然后对链上每个 framebuffer：

```c
fb->__private->glIndexBit = (1 << bit);
fb->setProperty("IOFramebufferOpenGLIndex", bit, 64);     // OSNumber，64 bit
```

`"IOFramebufferOpenGLIndex"` 这个字面量在 7 个 x86_64 kext 的 `__cstring` 里**只出现在 `[G]`**。

#### 另一个方向：framebuffer 主动找 accelerator

`[G]` `IOFramebuffer::probeAccelerator()` RVA `0x114E2`：

```c
if (__private->flags & 4) return 0;   /* 只做一次 */
__private->flags |= 4;

IORegistryEntry *p = this;
do { p = p->getProvider(); if (!p) return 0xE00002C0 /* kIOReturnNoDevice */; }
while (!OSDynamicCast(IOPCIDevice, p));                  /* 向上走到 IOPCIDevice */

OSIterator *it = p->getChildIterator(gIOServicePlane);
while ((IORegistryEntry *e = OSDynamicCast(IORegistryEntry, it->getNextObject()))) {
    if (e->metaCast("IOAccelerator")) {                   /* 按类名字符串匹配继承链 */
        IOService *svc = OSDynamicCast(IOService, e);
        ret = svc->requestProbe(1);                       /* vptr+1832 = IOService 槽 231 */
        break;
    }
}
if (未找到) ret = 0xE00002F0;                             /* kIOReturnNotFound */
it->release();
return ret;
```

注意两点：① 它用 `metaCast("IOAccelerator")` —— **按类名字符串**在继承链里找名叫 `IOAccelerator` 的类，所以本项目的 accelerator 必须真正继承自 `IOAccelerator`（`IOGraphicsAccelerator2` 就在这条链上）。② 它要求 accelerator 是**那个 `IOPCIDevice` 的直接子节点**。

#### 用户态那一半

`_SLSAcceleratorForDisplayNumber` 的具体读取**顺序**仍未查清，但本轮用字面量普查
**排除掉了大半候选**，把下一轮的工作量压到很小。`KNOWN`（否定部分）

在 T3 BaseSystem 样本上做全文件字节搜索的结果：

| 字面量 | `SkyLight` | `IOAccelerator.framework` | `Metal.framework` |
|---|:---:|:---:|:---:|
| `IOAccelIndex` | **0** | 0 | 0 |
| `IOAccelRevision` | **0** | 0 | 0 |
| `IOAccelTypes` | **0** | 0 | 0 |
| `IOFramebufferOpenGLIndex` | **0** | 0 | 0 |
| `IOAccelerator` | 2 | 5 | 9 |
| `AccelID` | **2** | 0 | 0 |
| `IOAccelDeviceID` | 0 | **1** | 0 |
| `MetalPluginName` / `MetalPluginClassName` | 0 | 0 | **各 1** |
| `SLSAcceleratorForDisplayNumber` | 1 | 0 | 0 |

**由此确定的三件事：**

1. SkyLight **不按名字读** `IOAccelIndex` / `IOAccelRevision` / `IOAccelTypes` /
   `IOFramebufferOpenGLIndex` 这四个 framebuffer 侧属性中的任何一个。下面那张
   "内核侧输入集"表仍然正确（它说的是谁写），但其中前 5 行**不是 SkyLight 的输入**。
2. SkyLight 侧用的键是 **`AccelID`**（2 次）加类名 **`IOAccelerator`**（2 次）。
   注意 `AccelID` 与 `[F2]` 写的 `IOAccelIndex` 不同名，也与
   `[G]` `IOAccelerator::createAccelID`（`11` 分册 §3.2 的 `IOAccelerationUserClient`
   那条线）同名 —— 下一轮应先假设 SkyLight 走的是**后者**。
3. `MetalPluginName` / `MetalPluginClassName` 只在 `Metal.framework` 出现，
   `IOAccelDeviceID` 只在 `IOAccelerator.framework` 出现。这与
   `10-KERNEL-ACCELERATOR.md` 的分工一致：Metal 选 device 看 plugin 名，
   IOAccelerator.framework 做 device 标识。

**剩下的工作（下一轮，代价很低）：** 只需在
`SkyLight-BaseSystem-analysis.i64` 里对那 2 处 `AccelID` 与 1 处
`SLSAcceleratorForDisplayNumber` 做 xref，就能定出顺序。本轮没做的原因是时间，
**不是材料缺失** —— 按 `00-OVERVIEW.md` §7 补充规则 4，这条不标 `BLOCKED`。

下表是**内核侧写入方**的确定集合（谁写、写在哪），与上面的"谁读"相互独立：

| 属性 | 位置 | 写者 |
|---|---|---|
| `IOAccelIndex`（OSNumber 32） | IOFramebuffer service | `IOAccelDisplayPipe::init` |
| `IOAccelRevision`（OSNumber 32，值 2） | IOFramebuffer service | 同上 |
| `IOAccelTypes`（OSData，≤512 B） | IOFramebuffer service | 同上 |
| `IOCFPlugInTypes`（字典，从 accelerator 拷来） | IOFramebuffer service | 同上 |
| `IOFramebufferOpenGLIndex`（OSNumber 64） | IOFramebuffer service | `IOFramebuffer::assignGLIndex` |
| `MetalPluginName` / `MetalPluginClassName` / `IOAccelDisplayPipeCapabilities` | accelerator service | 驱动自己（APV 从 `AcceleratorProperties` 展开） |

**查清方法（下一轮，代价低）：** 在 `IOAccelerator-BaseSystem-analysis.i64`（UUID `4FDBB3F6-9AA3-352B-87ED-57161AA64D1F`）里搜 `IOAccelIndex` / `IOFramebufferOpenGLIndex` 的字面量引用，追 `IOAcceleratorFindAccelerator*` 一类导出；再在 `SkyLight-BaseSystem-analysis.i64`（UUID `0900DFAB-ABDA-3500-AA65-806935F7AF44`）里追 `_SLSAcceleratorForDisplayNumber` 的被调用链。两者都是 T3，用于 ABI 判定可接受。

### 4.4 能不能不发布自己的 framebuffer，直接关联到已有的那个？`KNOWN`（机制）+ `BLOCKED`（目标环境事实）

**结论：机制上可以，而且这条路比自己写 framebuffer 更省事；但有四个硬前提，其中第一个在目标云平台上尚未确证。**

#### 机制依据（全部 `KNOWN`）

1. `IOAccelDisplayPipe::init` 对 framebuffer 做的全部事情是：`addFramebufferNotificationWithOptions` + 四次 `setProperty`。**没有一处要求那个 `IOFramebuffer` 属于同一个 kext、同一个 provider 实例或同一个厂商**。`setProperty` 是 `IORegistryEntry` 的公开方法，`addFramebufferNotificationWithOptions` 是 `IOFramebuffer` 的公开（非 KPI 导出但在 KC 内可链）方法。
2. `IOAccelDisplayMachine::start` 的三条搜索路径（§4.2）都只检查"是不是 `IOFramebuffer` 的实例"与"在不在这个 `IOPCIDevice` 的子树/客户端里"。
3. `found_framebuffer` 是虚方法（`__ZTV` 槽 285），子类可以覆写；`IOAccelDisplayMachine::start` 也是虚方法，可以整个替换成自己的搜索逻辑（例如 `IOService::waitForMatchingService(IOServiceMatching("IOFramebuffer"))` 或对 `IOFramebuffer` 类做 `addMatchingNotification`，再直接 `found_framebuffer(fb)`）。
4. `IOFramebuffer::probeAccelerator` 不是必须成功的：它返回 `kIOReturnNotFound` 只是让 framebuffer 不去主动 probe accelerator；真正建立关联的是 accelerator 侧（第 1、2 条）。

#### 四个前提

| # | 前提 | 状态 |
|---|---|---|
| 1 | guest 里确实存在一个已注册的 `IOFramebuffer` 子类实例 | **`BLOCKED`**。候选是 `[G]` 自带的 `IOBootFramebuffer`（28 条符号，RVA 区 `0x1BDAE` 附近的 `IOFramebufferBootInitFB`），它由 EFI GOP 建立；或云平台模拟显卡的厂商驱动（macOS 原生没有 QXL/Bochs/virtio-gpu 驱动，所以大概率只有 `IOBootFramebuffer`）。必须在目标 guest 内 `ioreg -c IOFramebuffer -l` 实测。与 `00-OVERVIEW.md` §2.5 风险 1 同一次实验即可闭合。 |
| 2 | 该 framebuffer 与我们的 accelerator 在同一个 `IOPCIDevice` 子树下（否则要覆写搜索逻辑） | `INFERRED`。`IOBootFramebuffer` 的 provider 本轮未查清；它可能挂在 `IOPCIDevice` 下，也可能挂在 platform device 下。查清方法同上（`ioreg -c IOBootFramebuffer -r -w0`）。 |
| 3 | 那个 framebuffer 的 `getVRAMRange()` 返回的内存可以被我们的渲染器写 | `INFERRED`。`IOBootFramebuffer` 的后备是 EFI 给的线性 framebuffer（MMIO/预留物理内存），我们可以 `map()` 它然后让 Lavapipe 把结果 blit 进去。这比"自己当 framebuffer"多一次拷贝，但省掉整个 §2 的实现工作。 |
| 4 | 第三方 kext 在 SIP/AMFI 关闭下能对别人的 service 调 `setProperty` 并注册 framebuffer notification | `KNOWN`（IOKit 无权限检查）+ 研发期 `00-OVERVIEW.md` §2.4 已放开签名门 |

#### 两条路线的取舍

| | 路线 A：自己发布 framebuffer | 路线 B：复用已有 framebuffer |
|---|---|---|
| 实现量 | §2 的 8 个纯虚 + `getVRAMRange` + timing/EDID/VBL，约 600–900 行 C++ | 0 行 framebuffer 代码；只需在 accelerator 里覆写 display machine 的发现逻辑 |
| 像素路径 | Lavapipe 直接渲进 framebuffer 内存（零拷贝） | Lavapipe 渲进自己的内存，再 blit 到已有 framebuffer（一次拷贝） |
| 模式控制 | 完全自主（可以声明任意分辨率列表） | 受限于已有 framebuffer 支持的 mode（`IOBootFramebuffer` 通常只有 EFI 设定的那一个） |
| 风险 | 需要实测 `doSetup` 全链；分辨率/timing 错一处就黑屏 | 依赖前提 1–3，其中 1、2 未确证 |
| 建议 | **作为主线。** 它和 `IOAccelDisplayMachine` 的默认发现逻辑天然契合（§2.6.2 的 attach-to-provider 拓扑），不需要覆写任何框架方法 | **作为回退方案与第一次点亮的捷径。** 如果云平台只给一个 EFI framebuffer 且分辨率够用，路线 B 能最快拿到"WindowServer 选中我们的 Metal device"这个里程碑 |

**推荐做法：两条都保留一个开关。** accelerator 侧的 `found_framebuffer` 无论对自家还是别家的 framebuffer 都走同一段代码（§4.3 的四次 `setProperty`），所以路线 A/B 的差异只在"framebuffer 从哪来"，上层完全共用。

## 5. 实现清单（照此写代码）

```
ReimsGPUControl : AppleGraphicsDeviceControl 或 IOService        // 匹配 IOPCIDevice
  start(provider):
      setupMMIO 可选（纯软件实现可以完全不碰 MMIO）
      for i in 0..N-1:   fb[i] = new ReimsFramebuffer;
                         fb[i]->initWithID(i);
                         fb[i]->attach(getProvider());           // ← provider，不是 this
                         fb[i]->start(getProvider());
      accel = new ReimsAccelerator;                              // : IOGraphicsAccelerator2
      accel->attach(getProvider());  accel->start(getProvider());

ReimsFramebuffer : IOFramebuffer
  initWithID(id):
      super::init(NULL);
      fbMemory = IOBufferMemoryDescriptor::withOptions(
                     kIODirectionOutIn | kIOMemoryKernelUserShared,
                     (id == 0) ? FB_BYTES : PAGE_SIZE, 1);
      vblTimer = IOTimerEventSource::timerEventSource(1, this);
  start(provider):
      setProperty("IOFBDependentID", (uint64_t)provider, 64);
      super::start(provider);
      registerService(kIOServiceAsynchronous /* 2 */);
      setProperty("IOFBDependentID", OSNumber(ptr, 64));
      setProperty("IOFBDependentIndex", OSNumber(0, 32));
      getWorkLoop()->addEventSource(vblTimer);
      setProperty("IOFBTimingRange", <312 字节 IODisplayTimingRange>, 312);   // 照 [A] start 0x53D4

  // 8 个纯虚（必须）
  getApertureRange(ap)                 -> getVRAMRange()
  getVRAMRange()                       -> fbMemory->retain(), return fbMemory
  getPixelFormats()                    -> "--------RRRRRRRRGGGGGGGGBBBBBBBB"
  getDisplayModeCount()                -> modes.count
  getDisplayModes(ids)                 -> ids[i] = i
  getInformationForDisplayMode(m, i)   -> 见 §2.2/317
  getPixelFormatsForDisplayMode(m, d)  -> 0
  getPixelInformation(m, d, ap, pi)    -> 见 §2.2/319
  getCurrentDisplayMode(&m, &d)        -> *m = cur, *d = 2

  // 强烈建议
  getTimingInfoForDisplayMode(m, ti)   -> 填 IODetailedTimingInformationV2（VBL 周期要用 pixelClock）
  setDisplayMode(m, d)                 -> 切 mode，必要时重算 fbMemory 需求
  getAttribute('crsr')                 -> 1                     // 不置 0x10000 ⇒ 软件光标
  getConnectionCount()                 -> 1
  getAttributeForConnection('enab'/'cena') -> *v = 1
  getAttributeForConnection('hddc')    -> return 0
  hasDDCConnect / getDDCBlock          -> 合成 EDID
  registerForInterruptType / unregisterInterrupt / setInterruptState
                                       -> 记录 proc/target/ref；vblTimer 到期时调用 proc
```

## 6. 本分册遗留的未查清项

| 项 | 状态 | 需要什么 | 怎么查 |
|---|---|---|---|
| ~~`notifyServer` 的 state 0–4 逐值语义~~ | **已关闭（§3.5.3）** | — | — |
| ~~`clientMemoryForType(110)` 的 `"local"` 判定来源~~ | **已关闭（§3.3）** | — | — |
| ~~`DisplayPipeSupported` / `TransactionsSupported` 的消费者~~ | **已关闭（§4.1）：全部样本内无人读** | — | — |
| ~~`getPixelFormatsForDisplayMode`（槽 318）的消费点~~ | **已关闭（§2.2）：`[G]` 内零调用点** | — | — |
| ~~`createSharedCursor` 的 `options = 0x10000`~~ | **已关闭（§3.4.1）：`kIOMemoryKernelUserShared`** | — | — |
| `'wsrv'`（`kIOWindowServerActiveAttribute`）位域 | 未关闭 | — | `[G] setWSAAAttribute` RVA `0x1CD64` 在本轮的 IDB 里尚未被 IDA 识别为函数（`get_func_attr` 返回无效），需要先在该 RVA 做 `create_insn` + `add_func` 再反编译；另一条路是对 `[F2]` `IOAccelDisplayMachine::wsaa_*` 四个入口做 xref 回溯。**可关，本轮因时间未做** |
| `_SLSAcceleratorForDisplayNumber` 的属性读取顺序 | **部分关闭（§4.3）** | T3 framework IDB | 已排除 `IOAccelIndex`/`IOAccelRevision`/`IOAccelTypes`/`IOFramebufferOpenGLIndex`；剩下只需 xref `SkyLight` 里 2 处 `AccelID` 与 1 处 `SLSAcceleratorForDisplayNumber`。**可关，本轮因时间未做** |
| `IOAccelDisplayPipe::init` 里 `accel->vtable[125]` 生成的 `IOAccelTypes` blob 格式 | 未关闭 | — | 反编译 `[F2]` `IOGraphicsAccelerator2` 槽 125 的实现。**可关**；本轮判定为低优先（本项目第一版不发布 display pipe，这个 blob 只进 framebuffer 的属性表） |
| `AppleGraphicsDeviceControl` 的 x86_64 ABI（§2.6.3 关于 `FramebufferCount` 的那条 `INFERRED`） | 未关闭 | 需对 `kext/com.apple.AppleGraphicsDeviceControl` 建库 | **可关**（二进制在仓库内，只是本轮没建 `.i64`）；但本项目推荐不继承 AGDC，所以优先级低 |
| guest 里已有 framebuffer 的身份与 provider（§4.4 前提 1–3） | 未关闭 | **要开机** | 目标 guest `ioreg -c IOFramebuffer -r -w0` 与 `ioreg -c IOBootFramebuffer -r -w0`，与 `00-OVERVIEW.md` §2.5 风险 1 同一次实验 |
| `DisplayPipeSupported` 不声明时 WindowServer 的实际行为（§4.1 末） | 未关闭 | **要开机** | 机制已 `KNOWN`，缺的是运行证据 |
| 本分册全部结论都是静态的，无 `TESTED` | 未关闭 | **要开机** | 见 `80-TEST-HARNESS.md` |

## 7. 本轮关闭的未查项（第 4 轮，2026-10-31）

本轮**只读既有 IDB 的 `$env:TEMP` 副本**，没有新建 `.i64`，没有改写 `analysis/` 下任何文件。

| # | 原条目 | 结论 | 证据（样本 UUID + RVA） | 新标签 |
|---|---|---|---|---|
| 1 | §2.2「318 `getPixelFormatsForDisplayMode` 返回 0 的消费点未逐一追」 | **`[G]` 内对该 vtable 槽的调用点数 = 0**；槽 314 `getPixelFormats` 同样为 0。两者都是"编译期必须实现、运行期无人调用"。附带给出 311–320 全部 10 个槽的调用点数与调用者 | `[G]` `74AA6483-8AB4-3A94-8143-5E306C16D7DA`：`__ZTV13IOFramebuffer` `+0x35248`；扫描口径 = 全件 1,146 函数的每条 `call`/`jmp` 间接位移（槽 318 ⇒ vptr 偏移 `0x9E0`） | `INFERRED` → `KNOWN` |
| 2 | §3.3「type 110 的 `strcmp(<某个名字>, "local")`，该名字的来源未查清」 | 不是字符串比较，是 `IOUserClient::clientHasPrivilege(current_task(), kIOClientPrivilegeLocalUser)` 与 `kIOReturnSuccess` 比较。**更正了原文对这条指令序列的解读**，并由此锚定三个 stub：`0x1031E` `current_task`、`0x10678` `clientHasPrivilege`、`0x1048C` `IOMemoryDescriptor::withAddressRange` | `[G]`：`+0x2472C` 函数体（关键指令 `+0x247A2/+0x247A7/+0x247B1/+0x247B8`），`"local"` 字面量 `+0x2B878`；`0x1031E` 的三个旁证调用点 `+0x19591` `+0x1E748` `+0x25FEE`。公开 ABI 锚点：xnu `iokit/IOKit/IOUserClient.h` | `KNOWN` |
| 3 | §3.4.1「`options = 0x10000` 按 `IOMemoryDescriptor.h` 对应 `kIOMemoryPersistent`」 | **更正为 `kIOMemoryKernelUserShared`**（`IOBufferMemoryDescriptor::withOptions` 用的是 `IOBufferMemoryDescriptor.h` 的位组，`kIOMemorySharingTypeMask = 0x000F0000`） | `[G]`：`createSharedCursor` `+0xD1A8`。公开 ABI 锚点：xnu `iokit/IOKit/IOBufferMemoryDescriptor.h` | `INFERRED` → `KNOWN`（并更正） |
| 4 | §3.5.3「state 语义逐值未查清」 | 0 = WS 掉电、1 = WS 上电（都由 `systemWork` 按 `gIOFBCurrentWSPowerOn` 的翻转发出）、**2 本构建内无发送点**、3 = 退出 dim、4 = 进入 dim（都由 `dimEngine` 发出）。另确证 25 秒 ack 定时器只对 {0,1,2} 组装，以及 state 1 并入的 fourcc 是 `'dstt'`（原文写作 `0x64737379 'dsyt'?`，**现更正为 `0x64737474`**） | `[G]`：`notifyServer` `+0x1698E`；4 个调用点 `+0x12653`（0/1）、`+0x176A8`（4）、`+0x17824`（3）、`+0x1974B`（重放）；判定式 `+0x125C6..+0x125E8`；dim 位操作 `+0x17654`/`+0x177ED` | `KNOWN` |
| 5 | §4.1「未查清：谁读 `DisplayPipeSupported` / `TransactionsSupported`」 | **已取得的 x86_64 样本里没有任何人读**（7 个 T2 kext + 4 个 T3 用户态件全部 0 次命中）。唯一引用外层键的 `IOAccelDisplayPipe::copyCapabilities()` 在 `[F2]` 内零调用点。连带澄清：type-4 闸门来自 `IOAccelConfig cfg+0x47` 的代码赋值，不是 plist | `[F2]` `6C4A16B1-66DC-3A8B-9F0B-D3E027B16EB1`：`copyCapabilities` `+0x4A378`，键字面量 `+0x6097D`；普查口径见 §4.1 的表 | `KNOWN`（否定结论） |
| 6 | §4.3「`_SLSAcceleratorForDisplayNumber` 的读取顺序未查清」 | **部分关闭**：排除了 framebuffer 侧四个属性名（SkyLight 里 0 次命中），SkyLight 用的是 `AccelID` + 类名 `IOAccelerator`。剩余只差 3 处 xref | T3：`…-frameworks/analysis-input/{SkyLight,IOAccelerator,Metal}`，字节级普查，结果表见 §4.3 | 部分 `KNOWN` |

