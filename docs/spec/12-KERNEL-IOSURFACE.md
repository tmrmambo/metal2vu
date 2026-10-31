# 12 - 内核 IOSurface 侧与 accelerator resource 的关联

文档版本：1.0
基线日期：2026-10-31
锚文档：`00-OVERVIEW.md`（证据规则见其第 7 节）
配套分册：`11-KERNEL-DISPLAY.md`、`10-KERNEL-ACCELERATOR.md`、`41-IOSURFACE-USERSPACE.md`

## 0. 本文作用与结论摘要

本文回答：IOSurface 在**内核侧**的对象模型、它与 accelerator 的关联机制、`IOSurfaceRootParavirtMapperInterface` 在 x86 上到底有没有用、`IOFenceTransaction` 的位置，以及 scanout surface 的所有权与生命周期。

### 0.1 本轮确证的核心结论

| # | 结论 | 标签 |
|---|---|---|
| 1 | `IOSurface.kext` 的 x86_64 代码在 `BootKernelExtensions.kc` 内，**符号完整**（2767 条 nlist，1673 个函数），`IOSurfaceRootUserClient` 用 **IOUserClient2022** 调度模型，表长 **63 条 selector**，且有 **普通表 / restricted 表两份**。 | `KNOWN` |
| 2 | 一个 IOSurface 与一个 accelerator 的关联就是 **`IOSurface::deviceCacheForAccelerator(void *accelerator, …)` 维护的一条 `IOSurfaceDeviceCache` 链表**，key 是 accelerator 的裸指针。不涉及任何"在内核里为 surface 建 GPU 资源"的动作。 | `KNOWN` |
| 3 | selector 12 `s_bind_accel` 的全部作用是 `IOSurface::synchronize_device_caches()`，即**缓存一致性同步**，不创建资源。 | `KNOWN` |
| 4 | `IOAccelSurfaceMTL::attach_surface_at_index(int, IOSurface*)` 只做 `retain` + 记 surface ID，**不构造 accelerator 侧资源**。 | `KNOWN` |
| 5 | **本项目不需要在内核侧建 IOSurface↔accelerator 资源映射。** 渲染全在用户态，用户态拿到的是 IOSurface 的 CPU 映射；不建这层关联的唯一代价是失去 `IOSurfaceDeviceCache` 的缓存同步与 orphan 回收，而纯 CPU 路径上这两者都不需要。 | `INFERRED`（机制 `KNOWN`，无运行证据） |
| 6 | `IOSurfaceRootParavirtMapperInterface` **在 x86_64 上确实存在**（`[S]` 13 条符号、独立 vtable、恰好 2 个纯虚），但**没有任何已取得的 x86_64 二进制 import `IOSurfaceRoot::registerMapperInterface`**，因此 x86 路径上它从未被注册，相关代码分支从不执行。 | `KNOWN`（范围限于已抽取的 7 个 graphics kext + kernel） |
| 7 | `IOFenceTransaction` 是 IOSurface 自带的**跨 surface 依赖图**容器（`add_fence` / `remove_fence` / `addTransaction` / 死锁检测），`IOFence` 带 `acceleratorID` 与 `fenceDirection`。swap 完成路径上它是"等前一帧的写 fence 完成"的那一环。 | `KNOWN` |

### 0.2 样本与地址约定

与 `11-KERNEL-DISPLAY.md` §0.2 相同。本文主要用：

| 标签 | 样本 | `LC_UUID` | 镜像基址 |
|---|---|---|---|
| `[S]` | `kext/com.apple.iokit.IOSurface` | `766DF6D3-1EEC-34DB-A9AD-EF72A36FB2A8` | `0xFFFFFF8002B84000` |
| `[F2]` | `kext/com.apple.iokit.IOAcceleratorFamily2` | `6C4A16B1-66DC-3A8B-9F0B-D3E027B16EB1` | `0x14B65000` |
| `[A]` | `kext/com.apple.driver.AppleParavirtGPU` | `B88E1D48-71A2-3DC0-8D87-605DDB039B83` | `0x14898000` |
| `[K]` | `kernel/kernel.x86_64` | `E514CEBA-9206-34D5-86C2-64E880FDDA2B` | `0xFFFFFF8000200000` |

**`[S]` 的 chained-fixup 解码与其他三件不同**：加载后地址 = `0xFFFFFF8000100000 + (value & 0x3FFFFFFF)`。详见 `11-KERNEL-DISPLAY.md` §1.2。另外 `[S]` 也有 §1.1 的 segment 头字段错位问题，必须先修才能读到字节。

## 1. `IOSurfaceRoot` 的发布方式

### 1.1 personality `KNOWN`

`IOSurface.kext/Contents/Info.plist`（`plists/System__Library__Extensions__IOSurface.kext__Contents__Info.plist`，SHA-256 `4EE11D8571C78B8BF91B79E23F593A9938861F641E1755C4C863874C0B8E41AC`）：

```xml
<key>IOKitPersonalities</key>
<dict>
  <key>FirstPersonality</key>
  <dict>
    <key>IOClass</key>         <string>IOSurfaceRoot</string>
    <key>IOProviderClass</key> <string>IOResources</string>
    <key>IOMatchCategory</key> <string>IOSurfaceRoot</string>
    <key>IOResourceMatch</key> <string>IOBSD</string>     <!-- 既有文档未记录这一条 -->
  </dict>
</dict>
<key>OSBundleRequired</key> <string>Console</string>
<key>CFBundleVersion</key>  <string>393.5.11</string>
```

`IOResourceMatch = IOBSD` 的意思是必须等 BSD 子系统就绪才匹配，所以 `IOSurfaceRoot` 的出现时机晚于早期 IOKit 匹配。对本项目的意义：accelerator 在 `start()` 里引用 `gIOSurfaceRoot` 时不能假定它一定已经存在，必须用 `waitForMatchingService` / `IOService::copyMatchingService` 或等待通知。`INFERRED`

### 1.2 `IOSurfaceRoot::start` 做了什么 `KNOWN`

`[S]` `IOSurfaceRoot::start(IOService*)` RVA `0x14F76`（`init(OSDictionary*)` 在 `0x14D2A`）。要点（按执行顺序）：

1. `super::start()`（`off_…+186`）。
2. 建三把锁（`IOLockAlloc` 一类）、三条侵入式链表头（surface 表、client 表、memory-pool 表）。
3. 建 shared-event workloop + `IOInterruptEventSource(this, IOSurfaceRoot::signal_event_clients_callback)`，并起 `IOSurfaceRoot::signal_event_clients_thread`（`kernel_thread_start`）。
4. 建 `async_release_thread`（`IOSurfaceRoot::async_release_thread`）。
5. `sysctlbyname("hw.cachelinesize")` → 存 cacheline 与掩码（失败回落 32/31）。
6. 三个尺寸上限字段初始化为 `0x7FFFFFFF`。
7. `IOSurfaceRoot::alloc_handles()`、`IOSurfaceRoot::alloc_event_shared(0, &id, &ptr)`（失败只打日志 `"IOSurfaceRoot: Initial shared event memory alloc failed"`）。
8. 读 device tree：`IORegistryEntry::fromPath("/")` → `getProperty("non-coherent")` 命中则置非一致模式并 `setProperty("iosurface-non-coherent", 1)`；再读 `"display-carveout-inhibitcache"` / `"display-carveout-restricted"`；`IORegistryEntry::fromPath("/vram")` 存在时注册一个名为 `"vram"` / `"PurpleGfxMem"` 的 memory region（limit 1024 或 256 MiB）。**x86 的 device tree 没有 `/vram`，所以这块不生效。** `INFERRED`
9. 注册 `IOSurfaceRoot::installMemoryRegions` 为延迟任务。
10. 建 fence workloop + `IOInterruptEventSource(this, IOSurfaceRoot::fenceDispatch)` + 第二个事件源，加入 workloop 并 enable。
11. `PE_parse_boot_argn("iofence_ddd", …, 4)`（上限 16）、`PE_parse_boot_argn("iosurface_debug", …, 4)`（默认 `20`）。`bit1` = 禁止 pixel-size casting，`bit2` = 允许全局 lookup（默认开，带警告），`bit3` = 用 pageable shmem。
12. `setName("IOSurfaceRoot")`（`IORegistryEntry` 槽 120）。
13. `registerService(0)`（`IOService` 槽 184）。

**对本项目：** 这些全部由 Apple 的 kext 完成，本项目不碰 `IOSurfaceRoot`，只作为客户端使用它。

### 1.3 `IOSurfaceRoot::newUserClient` `KNOWN`

`[S]` RVA `0x1624A`：

```c
*handler = NULL;
if (type != 0) return 0xE00002C9;            // kIOReturnInternalError
uc = IOSurfaceRootUserClient::metaClass->alloc 路径（vptr+136 = OSMetaClass 的 alloc 包装）
if (!uc->vtable[307](this, owningTask, 0))   // vptr+2440 → __ZTV 槽 307 = IOSurfaceRootUserClient::init(IOSurfaceRoot*, task*, OSDictionary*)  RVA 0x1B228
    goto fail;
if (!uc->attach(this) || !uc->start(this)) goto fail;
*handler = uc;  return 0;
```

**只有 type 0。** 其他 type 一律 `kIOReturnInternalError`。

### 1.4 `IOSurfaceRootUserClient` 的调度模型与 selector 表 `KNOWN`

`[S]` `IOSurfaceRootUserClient::externalMethod(uint32_t, IOExternalMethodArgumentsOpaque*)` RVA `0x1E1E0`，全文：

```c
const IOExternalMethodDispatch2022 *tbl = IOSurfaceRootUserClient::sMethodDescs;
if (this->flags_at_0x127 & 1) tbl = IOSurfaceRootUserClient::sMethodDescsRestricted;
return IOUserClient2022::dispatchExternalMethod(selector, args, tbl, /*count=*/63, this, NULL);
```

两张表：

| 表 | `[S]` RVA | 条目 |
|---|---|---:|
| `sMethodDescs` | `0x30A00` | 63 |
| `sMethodDescsRestricted` | `0x313E0` | 63 |

条目类型 `IOExternalMethodDispatch2022`，**40 字节**（两表相距 `0x9E0` = 63×40 + 8 对齐）：

```c
struct IOExternalMethodDispatch2022 {   // 40 字节
    IOExternalMethodAction function;       // +0x00
    uint32_t checkScalarInputCount;        // +0x08
    uint32_t checkStructureInputSize;      // +0x0C
    uint32_t checkScalarOutputCount;       // +0x10
    uint32_t checkStructureOutputSize;     // +0x14
    uint8_t  allowAsync;                   // +0x18
    const char *checkEntitlement;          // +0x20   —— 63 条全部为 NULL
};
```

`VAR` = `0xFFFFFFFF` = `kIOUCVariableStructureSize`。**63 条没有任何一条带 entitlement 检查**，这对研发期（SIP/AMFI 关闭）和分发期都有意义：IOSurface 的 selector 不受 entitlement 门限制。

| sel | 处理函数（`[S]` RVA，均为 `IOSurfaceRootUserClient::s_*`） | sIn | stIn | sOut | stOut | async | restricted 表是否放行 |
|---:|---|---:|---:|---:|---:|:---:|:---:|
| 0 | `s_create_surface` `0x19ECA` | 1 | VAR | 0 | 3176 | | ✔ |
| 1 | `s_release_surface` `0x1A014` | 1 | 0 | 0 | 0 | | ✔ |
| 2 | `s_lock_surface` `0x1A024` | 0 | 12 | 0 | 3176 | | ✔ |
| 3 | `s_unlock_surface` `0x1A040` | 0 | 12 | 0 | 4 | | ✔ |
| 4 | `s_lookup_surface` `0x1A05C` | 1 | 0 | 0 | 3176 | | ✘ |
| 5 | `s_set_ycbcrmatrix` `0x1A070` | 2 | 0 | 0 | 0 | | ✘ |
| 6 | `s_create_surface_fast_path` `0x1A084` | 0 | 32 | 0 | 3176 | | ✘ |
| 7 | `s_create_surface_client_mem` `0x1A096` | 2 | 0 | 0 | 3176 | | ✘ |
| 8 | `s_get_ycbcrmatrix` | 1 | 0 | 1 | 0 | | ✘ |
| 9 | `s_set_value` | 0 | VAR | 0 | 4 | | ✔ |
| 10 | `s_get_value` | 0 | VAR | 0 | VAR | | ✔ |
| 11 | `s_remove_value` | 0 | VAR | 0 | 4 | | ✔ |
| 12 | **`s_bind_accel` `0x1A38E`** | 3 | 0 | 0 | 0 | | ✔ |
| 13 | `s_get_limits` | 0 | 0 | 0 | 40 | | ✔ |
| 14 | `s_inc_sfc_use_count_for_category` | 2 | 0 | 0 | 0 | | ✔ |
| 15 | `s_dec_sfc_use_count_for_category` | 2 | 0 | 0 | 0 | | ✔ |
| 16 | `s_get_surface_use_count` | 1 | 0 | 1 | 0 | | ✘ |
| 17 | `s_set_surface_notify` | 0 | 24 | 0 | 0 | ✔ | ✘ |
| 18 | `s_remove_surface_notify` | 0 | 24 | 0 | 0 | | ✘ |
| 19 | `s_log` | 0 | VAR | 0 | 0 | | ✘ |
| 20 | `s_set_purgeable` | 2 | 0 | 1 | 0 | | ✔ |
| 21 | `s_set_ownership` | 4 | 0 | 0 | 0 | | ✘ |
| 22 | `s_set_tiled` | 2 | 0 | 0 | 0 | | ✘ |
| 23 | `s_is_tiled` | 1 | 0 | 1 | 0 | | ✔ |
| 24 | `s_set_timestamp` | 0 | VAR | 0 | 0 | | ✘ |
| 25 | `s_get_tile_format` | 1 | 0 | 1 | 0 | | ✘ |
| 26 | `s_get_data_value` | 0 | VAR | 0 | VAR | | ✘ |
| 27 | `s_set_bulk_attachments` | 0 | 160 | 0 | 0 | | ✔ |
| 28 | `s_get_bulk_attachments` | 1 | 0 | 0 | 160 | | ✘ |
| 29 | `s_prefetch_pages` | 2 | 0 | 0 | 0 | | ✘ |
| 30 | `s_gather_iosurface_data` | 1 | 0 | 0 | VAR | | ✘ |
| 31 | `s_set_cmp_tile_data_used_of_plane` | 3 | 0 | 0 | 0 | | ✔ |
| 32 | `s_get_graphics_comm_page_address` | 0 | 0 | 1 | 0 | | ✔ |
| 33 | `s_set_indexed_timestamp` | 3 | 0 | 0 | 0 | | ✘ |
| 34 | `s_lookup_surface_from_port` | 1 | 0 | 0 | 3176 | | ✔ |
| 35 | `s_create_port_from_surface` | 2 | 0 | 1 | 0 | | ✔ |
| 36 | `s_create_shared_event` | 1 | 0 | 2 | 0 | | ✔ |
| 37 | `s_signal_shared_event` | 2 | 0 | 0 | 0 | | ✔ |
| 38 | `s_query_shared_event` | 1 | 0 | 4 | 0 | | ✔ |
| 39 | `s_notify_shared_event` | 5 | 0 | 0 | 0 | | ✔ |
| 40 | `s_add_shared_event_notify_port` | 0 | 0 | 0 | 0 | ✔ | ✔ |
| 41 | `s_remove_shared_event_notify_port` | 1 | 0 | 0 | 0 | | ✔ |
| 42 | `s_signal_shared_event_operation` | 4 | 0 | 0 | 0 | | ✔ |
| 43 | `s_set_gpu_policy_dict` | 0 | VAR | 0 | 0 | | ✘ |
| 44 | `s_get_pid_gpu_policy_dict` | 1 | 0 | 0 | VAR | | ✘ |
| 45 | `s_set_detach_mode_code` | 4 | 0 | 0 | 0 | | ✘ |
| 46 | `s_set_image_origin_and_extents` | 0 | 28 | 0 | 0 | | ✘ |
| 47 | `s_set_ownership_identity` | 4 | 0 | 0 | 0 | | ✔ |
| 48 | `s_wait_shared_event` | 3 | 0 | 0 | 0 | | ✔ |
| 49 | `s_create_memory_pool` | 0 | VAR | 2 | 0 | | ✘ |
| 50 | `s_ensure_memory_pool_memory` | 1 | VAR | 0 | 0 | | ✘ |
| 51 | `s_flush_memory_pool` | 1 | VAR | 0 | 0 | | ✘ |
| 52 | `s_gather_memory_pool_data` | 1 | 0 | 0 | VAR | | ✘ |
| 53 | `s_set_data_property` | 2 | VAR | 0 | 0 | | ✔ |
| 54 | `s_get_data_property` | 2 | 0 | 2 | VAR | | ✔ |
| 55 | `s_clear_data_properties` | 1 | 0 | 0 | 0 | | ✔ |
| 56 | `s_invalidate_surface` | 1 | 0 | 0 | 0 | | ✔ |
| 57 | `s_set_corevideo_bridged_keys` | 0 | VAR | 0 | 0 | | ✔ |
| 58 | `s_remove_corevideo_bridged_values` | 1 | 0 | 1 | 0 | | ✔ |
| 59 | `s_remove_bulk_attachments` | 2 | 0 | 0 | 0 | | ✔ |
| 60 | `s_append_transaction` | 4 | 0 | 0 | 0 | | ✔ |
| 61 | `s_query_transaction_list` | 5 | 0 | 3 | 0 | | ✔ |
| 62 | `s_prune_transaction_list` | 1 | 0 | 0 | 0 | | ✔ |

被 restricted 表屏蔽的 selector（25 条）指向 `IOSurfaceRootUserClient::s_restricted`，形参检查值保持不变。

**restricted 位（对象 `+0x127` bit0）的来源已查清 `KNOWN`：是 entitlement 判定，不是沙箱或平台二进制判定。**

`[S]` `IOSurfaceRootUserClient::init(IOSurfaceRoot*, task*, OSDictionary*)` RVA `0x1B228` 在
`super::init(properties)` 成功后，对打开连接的 task 连查四个 entitlement（每次都是
`f(task, "<名字>")` 返回一个 `OSObject*`，与 GOT 槽 `off_FFFFFF8002BB10A8` 解引用出的
`OSBoolean` 真值单例比较 —— 即标准的 `IOTaskHasEntitlement` 写法）：

| 对象偏移 | 赋值 | entitlement |
|---|---|---|
| `+0x122` | `= (值 == 真)` | `com.apple.private.iosurfaceinfo` |
| **`+0x127`** | `= (值 == 真)` | **`com.apple.private.gpu-restricted` 为真，或（前者不为真时）`com.apple.developer.gpu-restricted` 为真** |
| `+0x123` | `= 0`（无条件） | — |
| `+0x126` | `= (+0x122 & 1) \| (值 == 真)` | `com.apple.private.IOSurface.protected-access`（与 `+0x122` 取或） |

`+0x126` 随后作为 `IOSurfaceShared::withTask(task, root, <+0x126 & 1>)` 的第 3 参传下去。

**方向要看清：带 `gpu-restricted` entitlement 的 task 才落进 restricted 表。**
`externalMethod` 的选表条件是 `if (flags_at_0x127 & 1) tbl = sMethodDescsRestricted`，
所以这个 entitlement 是一个**降权标记**（给 WebContent / GPU 这类受限进程用的），
不是提权标记。

**对本项目确实没有影响，而且现在是有证据的：** 本项目的 helper 进程不会签上
`com.apple.private.gpu-restricted` 或 `com.apple.developer.gpu-restricted`，
因此永远走 63 条的完整表。研发期 SIP/AMFI 关闭也不会意外带上这两个 entitlement
（它们来自签名，不是来自 SIP 状态）。

证据：`[S]` UUID `766DF6D3-1EEC-34DB-A9AD-EF72A36FB2A8`，`init` RVA `0x1B228`；四个
entitlement 字符串与四次比较都在该函数体内；`externalMethod` 的选表在 RVA `0x1E1E0`。

### 1.5 `3176` 字节是什么 `KNOWN`

selector 0/2/4/6/7/34 的 `checkStructureOutputSize` 都是 **3176**。`[S]` 有 `IOSurfaceClient::getLockResult(IOSurfaceLockResult *)` RVA `0x11C0A`（外加 22 个 tail-merge clone），所以 **3176 = `sizeof(IOSurfaceLockResult)`**。

**逐字段布局已展开 `KNOWN`**（反编译 `getLockResult` 的全部写入点；`[S]` 的 IDA 类型库里确实没有这个结构，下面的偏移是从写入指令反推的）。

#### 1.5.1 总体形状：**136 字节头 + 20 × 152 字节 plane 记录 = 3176**

这个分解是自洽的、可独立验算的：函数开头 `___bzero(out, 3176)`
（`[S]` 调 `0xFFFFFF8000101100`，Boot KC 侧可直接解析为 `___bzero`），
随后 plane 数组的基址被算成 `out + 136`，步长 152，循环上界 `56 * min(planeCount, 20)`
对应的记录数上界是 20，而 `136 + 20 * 152 = 3176`。函数内还有一条显式的
越界检查 `if (out + 3176 < 当前plane指针) <trap>`，确认 3176 就是缓冲区总长。

记号：`clt` = `IOSurfaceClient *this`，`surf` = `*(IOSurface **)(clt + 64)`。

#### 1.5.2 头部（0..135）

**字段名的依据**：`IOSurface` 的 surface 级 ivar 偏移可以由
`IOSurface::setLayoutFromDescriptor`（`[S]` RVA `0x102CA`）逐条读出 —— 该函数就是
"`IOSurfaceDescriptor` 的 getter → `IOSurface` 的 ivar"的一对一搬运，而 descriptor
侧的 getter 全部具名。本轮读出的映射（`[S] +0x102E4 … +0x103C7`）：

```
surf+0x58 = getWidth()          surf+0x60 = getHeight()        surf+0x68 = getBytesPerRow()
surf+0x70 = getBytesPerElement()(u16)   surf+0x72 = getElementWidth()(u8)
surf+0x73 = getElementHeight()(u8)      surf+0x78 = getBufferOffset()
surf+0x80 = getPixelFormat()(u32)       surf+0x90 = getAllocSize()
surf+0x98 = getPlaneCount()(u32)        surf+0x3C0 = getSliceCount()(u32)
```

下表的"字段名"列就是把这张映射代入 `getLockResult` 的写入点得到的，**不是猜的**。

| 偏移 | 宽度 | 来源 | 字段名 / 备注 |
|---:|---:|---|---|
| `+0x00` | 8 | `clt+0x50` | 本 (surface, task) 对的用户态映射基址一类，`41` 分册要对齐这个字段 |
| `+0x08` | 8 | `clt+0x58` | 同组（per-client，非 per-surface） |
| `+0x10` | 8 | `clt+0x60` | 同组 |
| `+0x18` | 4 | `clt+0x38` | 同组 |
| `+0x20` | 8 | `surf+0x90` | **allocSize** |
| `+0x28` | 8 | `surf+0x58` | **width** |
| `+0x30` | 8 | `surf+0x60` | **height** |
| `+0x38` | 8 | `surf+0x68` | **bytesPerRow** |
| `+0x40` | 8 | `surf+0x78` | **bufferOffset** |
| `+0x48` | 4 | `surf+0x80` | **pixelFormat** |
| `+0x50` | 8 | `surf+0x90` | **allocSize**（与 `+0x20` 同源，重复写了两次） |
| `+0x58` | 4 | `min(surf+0x98, 20)` | **planeCount，被硬截到 20** |
| `+0x5C` | 4 | `(u8)(*(void**)(surf+0x178))[110]` | 取自 `surf+0x178` 指向的共享 RO 页 |
| `+0x60` | 2 | `surf+0x70` | **bytesPerElement** |
| `+0x62` | 1 | `surf+0x72` | **elementWidth** |
| `+0x63` | 1 | `surf+0x73` | **elementHeight** |
| `+0x64` | 4 | `surf+0x9C` | 紧邻 planeCount 之后的 u32，descriptor 侧无对应 setter |
| `+0x68` | 4 | `*(u32*)(surf+0x178 指向页 + 12)` | 共享 RO 页里的一个计数（`processorDataUpdated` 会 `inc` 它） |
| `+0x6C` | 1 | `surf+0x3B4` | |
| `+0x6D` | 1 | `(surf+0x3D8 & 0x00200000) != 0` | 布尔，取自 §2.2 的 32 位标志字 bit 21 |
| `+0x6E` | 1 | `(surf+0x3D8 & 0x02000000) != 0` | 布尔，bit 25 |
| `+0x70` | 4 | `surf+0x368 ? *(u32*)(surf+0x368 + 16) : 0` | 来自 `IOSurfaceDescriptorContext`（memory pool 路径，§2.4 分支①） |
| `+0x74` | 4 | `surf+0x3C0`，或 0（当压缩参数数组 `surf+0x2F8` 为 NULL） | **sliceCount** |
| `+0x78` | 8 | `surf+0x370` | |
| `+0x80` | 8 | `IOSurface::getProtectionOptions()` | 唯一一个经函数调用取的字段 |
| `+0x88` | — | plane 数组起点 | 20 条 × 152 |

#### 1.5.3 每条 plane 记录（152 字节，`i = 0..19`）

三个源数组，每条记录从三处拼起来（每处都有独立的"数组长度够不够"检查，不够就走 trap）：

| 源 | 基址 / 步长 / 条数 | 填进记录的字节 |
|---|---|---|
| plane 描述符 | `surf+0x180`，步长 **56**，条数 `surf+0x188` | `rec+0x00..0x27`（5 个 qword，直拷）、`rec+0x28`（8，源 `+40`）、`rec+0x30`（2，源 `+48`）、`rec+0x32`（1，源 `+52`）、`rec+0x33`（1，源 `+53`）、`rec+0x35`（1，源 `+54`）；`rec+0x36/0x37` 显式清零 |
| 「additional plane info」 | `surf+0x308`，步长 **24**，条数 `surf+0x310`，且受 `surf+0x318 > i` 门控 | 由 `[S]` `fillAdditionalPlaneInfo(dst, src, src[0], 0)` 填（本轮未展开该函数内部） |
| 压缩/分块参数 | `surf+0x2F8`，步长 **60**，条数 `surf+0x300`（为 NULL 时全部写 0） | `rec+0x4C`(8)、`+0x54`(8)、`+0x5C`(8)、`+0x64`(8)、`+0x6C`(8)、`+0x74`(8)、`+0x7C`(8)、`+0x84`(4) —— 共 60 字节，**非对齐连续拷贝**，与源的 60 字节一一对应 |
| 4 个 u32 | `surf+0x340`，步长 **32**，条数 `surf+0x348`，且受 `(surf+0x338 >> 5) > i` 门控 | `rec+0x88`、`+0x8C`、`+0x90`、`+0x94`（源 `[0] [1] [2] [3]`） |

记录长度 `0x94 + 4 = 0x98 = 152` ✓。

`planeCount == 0` 的特殊路径（函数尾部）直接把 `fillAdditionalPlaneInfo` 写到
`out+136`、把那 4 个 u32 写到 `out+272/276/280/284`（= 第 0 条记录内的
`+0x88..+0x94`），与主循环一致。

#### 1.5.4 对 `41-IOSURFACE-USERSPACE.md` 的交接

- **20 是硬上限**：`planeCount > 20` 的 surface 在 `getLockResult` 里会被静默截断成 20，用户态拿不到第 21 个 plane 的描述。本项目的 surface 用 1 个 plane，不受影响。
- **头部 136 字节里有名字的 13 个字段**（allocSize ×2、width、height、bytesPerRow、bufferOffset、pixelFormat、planeCount、bytesPerElement、elementWidth、elementHeight、sliceCount、protectionOptions）全部由 `setLayoutFromDescriptor` 的 ivar 映射确证，可以直接照着写 `41` 分册的结构体。剩下 8 个（`+0x00/+0x08/+0x10/+0x18` 的 per-client 四个，`+0x5C/+0x64/+0x68/+0x6C/+0x78`）本文只给偏移与来源 ivar，**不编造名字**；要命名需要用户态侧的消费点（`IOSurface.framework` x86_64，T3 样本本轮未取）。
- `s_get_limits` 的 40 字节 / `s_set_bulk_attachments` 的 160 字节同理（后者对应 `IOSurface::setBulkAttachments(IOSurfaceColorAndSpatialKeysStruct*, size_t)` RVA `0xD0EA`，即 160 = `sizeof(IOSurfaceColorAndSpatialKeysStruct)`）。

`s_get_limits` 的 40 字节 / `s_set_bulk_attachments` 的 160 字节同理（后者对应 `IOSurface::setBulkAttachments(IOSurfaceColorAndSpatialKeysStruct*, size_t)` RVA `0xD0EA`，即 160 = `sizeof(IOSurfaceColorAndSpatialKeysStruct)`）。

### 1.6 没有 `clientMemoryForType` 覆写 `KNOWN`

`[S]` 的 `IOSurfaceRootUserClient` **没有覆写 `clientMemoryForType`**（`[S]` 符号表里 `clientMemoryForType` 只有 `IOUserClient::clientMemoryForType` 的 UNDEF 引用，RVA `0x356C8`）。它只覆写了 `getTargetAndTrapForIndex`（`0x1E21E`）。

**后果：IOSurface 的内存不是通过 `IOConnectMapMemory` 拿的**，而是通过 `s_create_surface` / `s_lock_surface` 返回的 `IOSurfaceLockResult`（内含用户态地址）以及 `IOSurfaceClient::mapInTask(task*, uint, bool)`（RVA `0x1197A`）在内核里直接映射进调用者 task。`s_create_port_from_surface`（sel 35）/ `s_lookup_surface_from_port`（sel 34）提供跨进程传递。

## 2. 一个 IOSurface 在内核侧的对象模型 `KNOWN`

`[S]` 的类规模（nlist 统计）：`IOSurface` 233、`IOSurfaceRootUserClient` 206、`IOSurfaceRoot` 199、`IOSurfaceDescriptor` 57(+26 clone)、`IOFenceTransaction` 55、`IOSurfaceClient` 51、`IOSurfaceDeviceCache` 36、`IOSurfaceSharedEvent` 35、`IOSurfaceMemoryPool` 31、`IOSurfaceMemoryRegion` 29、`IOSurfaceMemoryPoolBunch` 29、`IOSurfaceDeviceMemoryRegion` 28、`IOSurfaceSharedEventListener` 27、`IOSurfaceTransaction` 26、`IOFence` 24、`IOSurfaceShared` 21、`IOSurfaceDescriptorComponent` 21、`IOSurfaceSendRight` 21、`IOSurfaceWiredSendRight` 19、`IOSurfaceDescriptorContext` 19、`IOSurfaceRootParavirtMapperInterface` 13。

### 2.1 各类职责

| 类 | 职责 | 关键方法（`[S]` RVA） |
|---|---|---|
| `IOSurfaceRoot` | 单例服务。surface ID 空间、memory region 注册、shared event、fence 调度、全局上限 | `start 0x14F76`、`newUserClient 0x1624A`、`fenceDispatch 0x15CF8`、`registerMapperInterface 0x199F8`、`installMemoryRegions` |
| `IOSurface` | **一块 surface 本身**。布局、内存描述符、属性字典、per-accelerator device cache 链、fence 队列、transaction 列表、use count | `init(IOSurfaceRoot*, task*, OSDictionary*) 0x3D58`、`parse_properties 0x42B0`、`allocate 0x7AB8`、`deallocate 0x890A`、`register_surface 0x89C0`、`setLayoutFromDescriptor 0x102CA`、`getMemoryDescriptor 0xA63C`、`lockSurface 0x9164` / `unlockSurface 0x969E`、`prepare 0xB6CC` / `complete 0xB864` |
| `IOSurfaceDescriptor` | **纯描述器**（无内存）。width/height/pixelFormat/allocSize/plane 的全套 setter/getter，由 `parse_properties` 从用户传入的字典构造，再 `IOSurface::setLayoutFromDescriptor` 应用 | `newSurfaceDescriptor 0x132B6`、`init 0x132FE`，setter/getter 见 §2.3 |
| `IOSurfaceClient` | **一个 (surface, task) 对**。per-task 映射、per-category use count、lock 结果 | `withBuffer(IOSurfaceShared*, IOSurface*, bool) 0x171E`、`mapInTask 0x1197A`、`unmap 0x11BE2`、`getLockResult 0x11C0A`、`increment/decrement_use_count_for_category 0x123C4/0x1243A` |
| `IOSurfaceShared` | 一个 task 的共享状态页（surface 句柄表） | `init(task*, IOSurfaceRoot*, bool) 0x1FEC2` |
| `IOSurfaceMemoryPool` / `…PoolBunch` | 用户显式创建的内存池（selector 49–52）。wired 内存描述符工厂 + 按 size bucket 的复用 | `init 0x21318`、`newWiredMemoryDescriptorWithLength 0x2197E`、`ensureMemory 0x22862`、`getComponentsFromBucket 0x22CA4`、`flush 0x2312C`、`taskCanUsePool 0x217BC` |
| `IOSurfaceMemoryRegion` / `IOSurfaceDeviceMemoryRegion` | 命名内存区（device tree 里的 `/vram` 这类）。x86 上基本为空 | `init 0x1458C` / `0x13E2C` |
| `IOSurfaceDescriptorComponent` / `IOSurfaceDescriptorContext` | memory-pool 分配出的内存块与其 `IOMultiMemoryDescriptor` 上下文 | `init(uint, uint64) 0x20E7C`、`zeroFill 0x20FA8`；`IOSurfaceDescriptorContext::init(IOMultiMemoryDescriptor*, OSSharedPtr<OSArray>, uint64, OSSharedPtr<IOSurfaceMemoryPoolBunch>) 0x205BA` |
| `IOSurfaceDeviceCache` | **per-accelerator 的 surface 侧状态**（见 §3） | `init(IOSurface*, void*, uint, uint, uint, bool, IOSurfaceDeviceCacheList*) 0x12C1A`、`withSurfaceBufferOnAccelerator` |
| `IOSurfaceSharedEvent` / `…Listener` / `…Notification` / `…NotificationPort` / `…Reference` | shared event（Metal 的 `MTLSharedEvent` 内核侧） | `IOSurfaceSharedEvent::init(IOSurfaceRoot*, uint64) 0x17B4`、`IOSurfaceSharedEventListener::init(thread_call_priority_t, IOWorkLoop*, bool) 0x88A` |
| `IOFence` / `IOFenceTransaction` | 见 §5 | |
| `IOSurfaceSendRight` / `IOSurfaceWiredSendRight` | mach port 右值包装（selector 34/35） | `init 0x23846` / `0x23C10` |
| `IOSurfaceMemoryTag` | 内存会计标签 | `init(IOSurface*) 0x127D4` |
| `IOSurfaceTransaction` | 见 §5.3 | `init(IOSurfaceSharedEventReference*, uint64, bool) 0x23FBC` |

### 2.2 `IOSurface` 对象里的关键字段偏移 `KNOWN`

反编译里直接出现的（以 qword 索引 × 8 给出）：

| 偏移 | 内容 |
|---:|---|
| `+0x30` (`[6]`) | `IOMemoryDescriptor *`，`getMemoryDescriptor()` 与 `getMemoryDescriptor(IOService*)` 都返回它 |
| `+0x30`–`+0x37` | 上者的 `intrusive_shared_ptr` 包装（`reset` 作用在 `this+48`） |
| `+0x40` (`[8]`) | device cache 链表头 |
| `+0x48` (`[9]`) | device cache 链表尾指针 |
| `+0x50` (`[10]`) | surface 自己的锁（`IOSurface::lock()` `0x10A70` / `unlock()` `0x10A7E` 操作它） |
| `+0x368` (`[109]`) | `IOSurfaceDescriptorContext *`（来自 memory pool 时非 NULL，此时 `allocate()` 直接取 `ctx+48` 的 MD） |
| `+0x3A8` (`[117]`) | paravirt 映射请求标记（非 0 时走 mapper interface，见 §4） |
| `+0x3C8` (`[121]`) | paravirt mapper 产出的对象 |
| `+0x3D8` (`984`) | **32 位标志字**。`+0x3D9`/`+0x3DA`/`+0x3DB` 是它的第 1/2/3 字节，下面三行都是它的别名 |
| `+0x3DA` (`986`) | 标志字节；bit `0x10`（= 标志字 bit 20）= `isDisplayable()`（`[S]` `0x109F4`）；bit `0x01`（bit 16）= `isPixelCastingAllowed` / `isPixelSizeCastingAllowed` |
| `+0x3DB` (`987`) | 标志字节；bit `0x01`（bit 24）触发 paravirt 映射路径；另有 `isMetalSharedTexture` `0x10DD8` / `isGPUGlobalRO` `0x10DE8` 读它 |

**surface 级布局 ivar（本轮由 `IOSurface::setLayoutFromDescriptor` `[S] 0x102CA` 逐条读出）** `KNOWN`：

| 偏移 | 内容 | 偏移 | 内容 |
|---:|---|---:|---|
| `+0x58` | `width` | `+0x60` | `height` |
| `+0x68` | `bytesPerRow` | `+0x70` (u16) | `bytesPerElement` |
| `+0x72` (u8) | `elementWidth` | `+0x73` (u8) | `elementHeight` |
| `+0x78` | `bufferOffset` | `+0x80` (u32) | `pixelFormat` |
| `+0x90` | `allocSize` | `+0x98` (u32) | `planeCount` |
| `+0x3C0` (u32) | `sliceCount` | `+0x10` (u32) | `surfaceID`（见 §3.4 `find_surface` 的一致性检查） |
| `+0x170` | `fClientTask`（拥有者 task，§3.4） | `+0x178` | 共享 RO 页指针 |
| `+0x180` / `+0x188` | plane 描述符数组（步长 56）/ 条数 | `+0x2F8` / `+0x300` | 压缩参数数组（步长 60）/ 条数 |
| `+0x308` / `+0x310` / `+0x318` | additional plane info 数组（步长 24）/ 条数 / 有效上界 | `+0x340` / `+0x348` | 4×u32 数组（步长 32）/ 条数 |

这张表是 §1.5 的 `IOSurfaceLockResult` 布局与 `41-IOSURFACE-USERSPACE.md` 的共同基础。

`IOSurface::isDisplayable()` 的实现就是 `return (flags986 & 0x10) >> 4`（`[S] 0x109F4`：
`mov al, [rdi+3DAh]; and al, 10h; shr al, 4`）。

> **更正。** 原文此处写作"由 `parse_properties` 根据用户传入字典设置。`INFERRED`（置位点未逐一追）"。
> 本轮把置位点逐一追完了，**原文的归属是错的，而且更强的结论是这一位在本构建上根本没有置位点**。`KNOWN`
>
> 口径：`surf+0x3D8`（32 位标志字，`+0x3DA` 是它的第 2 字节、`+0x3DB` 是第 3 字节）上的
> **全部**内存操作数，在 `[S]` 全件 1,673 个函数的每条指令上按位移匹配（不限基址寄存器），
> 共 71 + 8 + 13 + 4 处。筛出写入点后逐条读掩码：
>
> | 位 | 写入点 | 语义 |
> |---|---|---|
> | bit 0 | `register_surface +0x89F4` 置、`unregister_surface +0x8494` 清 | 已注册 |
> | bit 2/3 | `allocate +0x7F8C`、`lockSurface +0x9254`、`deviceUnlockSurface +0xCC74`（`\| 0x1C`）、`append_transaction +0x10E61`、`processorDataUpdated +0x9107`（`\| 0x0C`） | 数据有效性（`isDataValid` 读 `+0x3D8`） |
> | bit 4 | `invalidateProcessorCaches +0x915A` 置；`processorDataUpdated` 按参数置 | 缓存失效 |
> | bit 5 | `allocate +0x7F7B`、`unlockSurface +0x96FD`、`dirtyProcessorCaches +0x9792` 置；`flushProcessorCaches +0x8F70`、`prepare +0xB7FE` 清 | 处理器缓存脏 |
> | bit 8 | `init +0x41D8`（`= (allocate() == 0) << 8`） | 分配成功 |
> | bit 9 | `setLayoutFromDescriptor +0x10318`（`= getIsTiled() << 9`）、`setTiled/isTiled +0xC216/+0xC249` | **isTiled** |
> | bit 15 | `init +0x4011`（`= (old & 0xFFFF5FFF) \| 0x8000`） | 固定置 1 |
> | bit 16 | `init +0x4063`（`or byte [rbx+3DAh], 1`，无条件） | `isPixelCastingAllowed` / `isPixelSizeCastingAllowed` 都读这一位 |
> | **bit 20** | **没有任何写入点。** `init +0x3F83` 的 `and dword [rbx+3D8h], 0FFEDB3FDh` 把它**清零**（该掩码清 bit 1/10/11/14/17/20），此后全件再无置位 | **`isDisplayable()`** |
> | bit 22 | `setLayoutFromDescriptor +0x1034B`（`= getDisableMapping() << 22`） | **disableMapping** |
> | bit 26 | `allocate +0x7BB3`（`and 0xFBFFFFFF` 清） | |
>
> 另一组被原文归给 `parse_properties` 的位也不在那里：`parse_properties`（RVA `0x42B0`）
> **对 `surf+0x3D8` 没有任何访问**；它只构造 `IOSurfaceDescriptor`，再由
> `IOSurface::setLayoutFromDescriptor`（RVA `0x102CA`）把 descriptor 的
> `getIsTiled()` / `getDisableMapping()` 翻译成 bit 9 / bit 22。所以**用户字典 → 标志位的
> 路径是 `parse_properties → IOSurfaceDescriptor → setLayoutFromDescriptor`，中间隔了一层。**
>
> **结论：在 x86_64 25G325 的 `IOSurface.kext` 上，`IOSurface::isDisplayable()` 恒返回 0。**
> 这与 `11-KERNEL-DISPLAY.md` §4.1 的结论方向一致（x86 路径上事务型 scanout 整条链不活跃），
> 也意味着本项目**不可能**靠"把某个 surface 标成 displayable"去参与上屏 —— 没有那个开关。
> 上屏只能走 framebuffer 内存（`11` 分册 §6.1）。
>
> 该位可能由 `IOSurface.kext` 以外的代码置位吗？不可能：`surf+0x3D8` 是私有 ivar，
> 没有 setter 导出，且本节的扫描覆盖了定义该类的那唯一一个 kext 的全部指令。

### 2.3 plane / stride / allocSize 在内核侧怎么表达 `KNOWN`

**表达在 `IOSurfaceDescriptor` 上**（`[S]` RVA `0x132B6`–`0x13AF2`，83 条符号），然后由 `IOSurface::setLayoutFromDescriptor(const IOSurfaceDescriptor*)`（RVA `0x102CA`）拷进 `IOSurface`。

surface 级：

```
setPixelFormat(uint) 0x133B0      setWidth(uint) 0x133BE        setHeight(uint) 0x133CA
setElementWidth 0x133D8           setElementHeight 0x133E6      setAllocSize(uint) 0x133F4
setIsTiled(bool) 0x13402          setDisableMapping(bool) 0x13410
setPlaneCount(uint) 0x1341E       setBufferOffset(uint) 0x1342C
setBytesPerRow(uint) 0x1343A      setBytesPerElement(uint) 0x13448
setSliceCount(uint) 0x136F2
```

plane 级（全部是 `(uint plane, uint value)` 形式，plane 索引在前）：

```
setPlaneWidth 0x13456              setPlaneHeight 0x13474
setPlaneElementWidth 0x13492       setPlaneElementHeight 0x134B0
setPlaneBase 0x134CE               setPlaneOffset 0x134EC
setPlaneBytesPerRow 0x1350A        setPlaneBytesPerElement 0x13528
setPlaneSize 0x13546               setPlaneAddressFormat 0x13564
```

压缩/分块相关 plane 级字段（Apple Silicon 的 lossless compression 用，x86 上一般保持 0）：

```
setPlaneCompressionType 0x13582                       setPlaneCompressionFootprint(uint, uchar) 0x135A0
setPlaneCompressedTileDataRegionOffset 0x135C4        setPlaneCompressedTileHeaderRegionOffset 0x135E2
setPlaneCompressedTileWidth 0x13600                   setPlaneCompressedTileHeight 0x1361E
setPlaneWidthInCompressedTiles 0x1363C                setPlaneHeightInCompressedTiles 0x1365A
setPlaneBytesPerCompressedTileHeader 0x13678          setPlaneBytesPerTileData 0x13696
setPlaneBytesPerRowOfTileData 0x136B4                 setPlaneBytesPerRowOfCompressedTileHeaderGroups 0x136D4
setPlaneDataRegionBytesPerSliceForPlane 0x13708       setPlaneHeaderRegionBytesPerSliceForPlane 0x13728
```

getter 一一对应（`getPixelFormat 0x13748` … `getPlaneHeaderRegionBytesPerSliceForPlane 0x13AF2`）。

`IOSurface` 侧的同名 getter 也齐全（`getPlaneBase 0xA7D8`、`getPlaneOffset 0xA878`、`getPlaneSize 0xA918`、`getPlaneBytesPerRow 0xAC40`、`getPlaneExtendedPixelsLeft/Top/Right/Bottom 0xAE1C/0xAEA6/0xAF30/0xAFB8`、`planeSize(uint) 0xA646` …）。

**对本项目（`41-IOSURFACE-USERSPACE.md` 配套）：** 内核侧把 plane 表达为"每 plane 独立的 offset + bytesPerRow + size + elementWidth/Height"，base 与 offset 分开。因此 Vulkan 侧导入时不能假定 plane 连续或 tightly packed，必须逐 plane 用 `getPlaneOffset`/`getPlaneBytesPerRow`。单 plane BGRA8 的常规情况里 `planeCount = 1`、`planeOffset[0] = bufferOffset`。

### 2.4 内存从哪来 `KNOWN`

`[S]` `IOSurface::allocate()` RVA `0x7AB8` 的三条分支：

```c
if (this->descriptorContext /* +0x368 */) {
    /* ① 来自用户显式创建的 memory pool：直接复用 ctx 里的 IOMultiMemoryDescriptor */
    intrusive_shared_ptr<IOMemoryDescriptor>::reset(&this->md, ctx->md /* ctx+48 */);
    goto done;
}
if ((this->flags987 & 1) || this->paravirtReq /* +0x3A8 */) {
    /* ② paravirt 映射路径 —— 见 §4，x86 上永不生效 */
    ...
}
if (this->clientAddress /* +0x150 */) {
    /* ③ create_surface_client_mem：包装调用者已有的用户内存。
       逐页用 vm_map_region_recurse 校验地址区间，失败打
       "error - invalid address range (0x%llx - 0x%llx) : (0x%llx - 0x%llx)" 并返回 0xE00002C8 (kIOReturnVMError) */
}
/* ④ 默认：自行分配 wired 内存 */
```

## 3. IOSurface 与 accelerator resource 的关联机制

### 3.1 关联的载体是 `IOSurfaceDeviceCache` `KNOWN`

`[S]` `IOSurface::deviceCacheForAccelerator(void *accelerator, uint32_t a3, uint32_t a4)` RVA `0x8A14`：

```c
IOLockLock(this->lock /* +0x50 */);
for (c = this->deviceCacheHead /* +0x40 */; c; c = c->next /* c+48 */) {
    if (c->accelerator /* c+24 */ == accelerator && c->key /* c+84 */ == a4) {
        if (c->orphaned /* c+89, bit0 */) { this->retain(); c->orphaned = 0; }
        else                              { c->retain(); }
        goto out;                                   /* 命中既有 cache */
    }
}
c = IOSurfaceDeviceCache::withSurfaceBufferOnAccelerator(this, accelerator, a3, a4, &this->deviceCacheHead);
if (c) { /* 头插进双向链表；若链表非空且尾指针异常则触发 event_notification_internal */ }
out:
IOLockUnlock(this->lock);
return c;
```

配套方法：`IOSurface::set_current_device_cache 0x98FE`、`getCurrentDeviceCache 0xA6E6`、`orphan_device_cache 0x8B6C`、`unorphan_device_cache 0x8AF0`、`remove_device_cache 0x8AFA`、`prune_orphaned_device_caches 0xB436`、`gatherOrphanedDeviceCachesWithAccelerator(void*, IOSurfaceDeviceCacheList*) 0xB598`。

**关键点：**

- key 是 **accelerator 的裸 `void *` 指针**，IOSurface 不知道 accelerator 的类型，也不对它调任何虚方法。关联是**单向弱引用**：surface 记着"某个 accelerator 在我身上留了一份 cache"。
- `IOSurfaceDeviceCache` 里存的是 accelerator 侧自己塞进来的东西（`init` 的签名是 `init(IOSurface*, void *accelerator, uint, uint, uint, bool, IOSurfaceDeviceCacheList*)`，RVA `0x12C1A`），IOSurface 只负责生命周期与链表。
- accelerator 消失时用 `gatherOrphanedDeviceCachesWithAccelerator` + `prune_orphaned_device_caches` 回收。

### 3.2 `s_bind_accel` 实际做什么 `KNOWN`

```c
// [S] IOSurfaceRootUserClient::bind_accel(uint surfaceID, uint a3, uint a4)   RVA 0x1CE44
IOSurface *s = this->retainSurface(surfaceID);
if (!s) return 0xE0000002;                       // kIOReturnError 系
IOSurface::wait_on_transaction_list(s, false);   // RVA 0x11170
ret = IOSurface::bind_accel(s, a3, a4);
s->release();
return ret;

// [S] IOSurface::bind_accel(uint a2, char a3)   RVA 0x97DA
IOLockLock(this->lock);
IOSurface::synchronize_device_caches(this, a2, a3 & 7, /*flush=*/false);   // RVA 0x92B4
IOLockUnlock(this->lock);
return 0;
```

**即 selector 12 只是缓存一致性同步，不创建任何资源。** 名字容易误导。

### 3.3 `IOAccelSurface` / `IOAccelSurfaceMTL` 怎么从 IOSurface 建 accelerator 侧资源 `KNOWN`

`[F2]` 里 `IOAccelSurface` 91 条、`IOAccelSurfaceMTL` 75 条、`IOAccelLegacySurface` 51 条符号。它们是 **user client**（`IOAccelSurfaceMTL::externalMethod` RVA `0x10A12`，表 `sSurfaceMethods` RVA `0x71260`），代表 "一个 drawable / 一组 buffer"。

与 IOSurface 的接口是两个方法：

```c
// [F2] IOAccelSurfaceMTL::attach_surface_at_index(int index, IOSurface *surf)   RVA 0x11068
if (this->surfaces[index] != surf) {
    if (this->surfaces[index]) { this->surfaces[index] = NULL; <release 旧的 use count>; }
    surf->retain();                       // vptr+32 → OSObject 槽 6
    <对 surf 递增 client/use count>;       // 一次外部调用
    this->surfaces[index] = surf;
    this->surfaceIDs[index] = surf->getSurfaceID();   // 存 ID
}
// [F2] IOAccelSurfaceMTL::detach_surface_at_index(int)   RVA 0x110E0
```

**就这么多。** 没有 `IOAccelResource2` 构造、没有 GPU 页表映射、没有 `deviceCacheForAccelerator` 调用。

辅助：`IOAccelSurfaceMTL::getSurfaceBuffer(eIOAccelGLDrawableClientBufferType) 0x10CC8`、`shape_buffers 0x11204`、`flip_buffers 0x11028`、`prune_buffers 0x101D2`、`isSurfaceSizeSupported(short,short) 0x11110`。另有 `IOSurfaceMTLSharedEventFence`（`[F2]`，20 条符号）把 IOSurface shared event 接到 accel fence 机器上。

### 3.4 本项目要不要在内核侧建这层关联 `INFERRED`

**不要建。** 理由：

| 关联的用途 | 本项目是否需要 |
|---|---|
| `IOSurfaceDeviceCache` 的 CPU↔GPU 缓存一致性（`synchronize_device_caches` / `flushProcessorCaches` / `cleanProcessorCaches` / `invalidateProcessorCaches`） | **不需要。** 渲染器是 Lavapipe，GPU 就是 CPU，同一份一致的内存。 |
| GPU 虚拟地址空间映射（真实 GPU 需要把 surface 页映射进 GPU 页表） | **不需要。** 没有 GPU 页表。 |
| `IOAccelSurfaceMTL` 的 drawable buffer 管理 | **不需要。** 本项目的 Metal drawable 由用户态 ObjC 层（`20`/`21` 分册）直接管到 IOSurface。 |
| accelerator 消失时的 orphan 回收 | 不需要；没有建 cache 就没有 orphan。 |

**不建的后果（已逐条核对，都不致命）：**

1. `IOSurface::bind_accel`（selector 12）如果被用户态某层调用，会在没有 device cache 的 surface 上走 `synchronize_device_caches`，该函数对空链表是 no-op。不会报错。
2. `IOSurface::getCurrentDeviceCache()` 返回 NULL。调用方是 `[F2]`/驱动自己，本项目不调用。
3. `[F2]` `IOAccelDisplayMachine::is_current_display_resource(IOAccelResource2*)`（RVA `0xEEF0`）这类"这块资源是不是正在 scanout"的判定会失效 —— 只在走事务型 display pipe 时才需要，与 `11-KERNEL-DISPLAY.md` §4.1 的建议（第一版不开 `DisplayPipeSupported`）一致。
4. `ioclassview` / `IOSurface` 调试字典（`write_debug_info_with_options`）里少一段 device-cache 信息。无功能影响。

**唯一需要在内核侧为 IOSurface 做的事**：本项目的 accelerator 的 shared user client 需要能把一个 surface ID 解析成 `IOSurface*`，以便（若将来需要）参与 scanout。

**具体 KPI 入口已查清 `KNOWN`：**

| 入口 | `[S]` RVA | 说明 |
|---|---|---|
| `IOSurfaceRoot::lookupSurface(uint32_t surfaceID, task *owner)` | `0x16612` | **这是给驱动用的那个**。两参，内部转 `find_surface(id, owner, NULL)` |
| `IOSurfaceRoot::lookupSurfaceFromClient(uint32_t, task*, IOSurfaceRootUserClient*)` | `0x16774` | 带 user client 的版本，多一条"该 client 认识这个 surface"的放行路径 |
| `IOSurfaceRoot::find_surface(uint32_t, task*, IOSurfaceRootUserClient*)` | `0x164B8` | 上面两者的共同实现（私有） |
| `IOSurface::getSurfaceID() const` | `0xA720` | 反向 |

`find_surface` 的逻辑（本轮反编译，对本项目有直接用处）：

```c
if (id == 0 || id >= root->tableCount /* root+0xD8，u32 */) goto not_found;
IOSurface *s = ((IOSurface **)root->table /* root+0xD0 */)[id];   // surface ID 就是表下标
if (!s) goto not_found;
if (s->surfaceID /* s+0x10 */ != id) panic("IOSurface in slot %08x has a mismatched surface ID of %08x");
/* 三条放行条件，任一成立即返回 s */
if (owner == s->fClientTask /* s+0x170 */) return s;              // ① 本就是拥有者
if (uc && uc->knows_surface(s))          return s;                // ② 该 user client 已持有
if ((s->flags /* s+0x3D8 */ & 0x80002) == 2) return s;            // ③ 全局可见（bit1 置、bit19 清）
os_log("SID: 0x%X task: %p buffer: %p  buffer->fClientTask = %p not found\n", …);
return NULL;
```

**对本项目：** 第一版不需要它；但如果将来要在内核侧按 ID 取 surface，
条件③（`flags bit1` 置、`bit19` 清）就是"任何 task 都能查到这个 surface"的那个开关，
比给每个 task 建 user client 简单得多。注意这三个符号都是 `IOSurface.kext` 内部的
C++ 方法，**要确认它们是否作为 KPI 导出**（即在 `IOSurface.kext` 的
`Contents/Resources/.../IOSurface.exports` 里）才能从第三方 kext 直接调；
该 exports 文件不在仓库内（仓库里只有 `IOPCIFamily.exports`）。
这一条是**要上游材料**，不是未查。

## 4. `IOSurfaceRootParavirtMapperInterface`

### 4.1 它是什么 `KNOWN`

`[S]` 里的一个**抽象接口类**，13 条符号，直接继承 `OSObject`：

| 项 | `[S]` RVA |
|---|---|
| `vtable for'IOSurfaceRootParavirtMapperInterface` | `0x2F350`（到 `0x2F490`，共 40 槽） |
| `metaClass` / `superClass` | `0x2F340` / `0x2F348` |
| `gMetaClass` | `0x33800` |
| `IOSurfaceRootParavirtMapperInterface(OSMetaClass const*)` | `0x14768` |
| `~IOSurfaceRootParavirtMapperInterface()` | `0x14788` / `0x257C6` / `0x257CC` |
| `getMetaClass()` | `0x14792` |
| `operator new / delete` | `0x147DA` / `0x147EE` |

vtable 40 槽里：槽 0/1 为 0，槽 2/3 析构，槽 4–36 全是 OSObject 的继承实现，**槽 37 与槽 38 指向内核 `___cxa_pure_virtual`**，槽 39 为 0。

**即：恰好 2 个纯虚方法，没有任何自己的非虚方法。** 这是一个"给 paravirt GPU 驱动实现的 2 方法回调接口"。

### 4.2 注册与消费 `KNOWN`

```c
// [S] IOSurfaceRoot::registerMapperInterface(IOSurfaceRootParavirtMapperInterface *iface)   RVA 0x199F8
old = this->mapper /* this + 0x448 */;
this->mapper = iface;
if (iface) iface->retain();                  // vptr+32 → 槽 6
if (old)   old->release();                   // vptr+40 → 槽 7
if (iface) {
    IOLog("IOSurfaceRoot using IOSurfaceRootParavirtMapperInterface %p", iface);
    os_log(..., "IOSurfaceRoot using IOSurfaceRootParavirtMapperInterface");
}
```

**唯一消费点是 `[S]` `IOSurface::allocate()` RVA `0x7AB8`**（整个 kext 里只有 5 个函数引用偏移 `0x448`：两个 ctor、两个 dtor、`registerMapperInterface`，加上 `allocate` 通过 `gIOSurfaceRoot` 间接引用）：

```c
if ((this->flags987 & 1) || this->paravirtReq /* +0x3A8 */) {
    m = gIOSurfaceRoot->mapper;                      // +0x448
    if (m && m->vtable[38](m)) {                     // vptr+288 → __ZTV 槽 38，纯虚 #2，返回 bool（"可用/应当映射"门）
        this->retain();                              // vptr+32
        obj = m->vtable[37](m, this);                // vptr+280 → __ZTV 槽 37，纯虚 #1，参数是 IOSurface*
        if (this->paravirtMapping /* +0x3C8 */) this->paravirtMapping->release();
        this->paravirtMapping = obj;
        ret = 0;
        if (!obj) { os_log("%s error - can't prepare mapping", "allocate"); ret = 0xE00002BE; }  // kIOReturnNoResources
        this->release();                             // vptr+40
        return ret;
    }
    /* mapper 为 NULL 或门返回 false → 落到下面的普通分配路径 */
}
```

**两个纯虚方法的签名（形状部分 `KNOWN`，名字部分见下面的架构警告）：**

| 槽 | 调用形式（x86 `[S]` 侧，`KNOWN`） | 签名 | 语义 |
|---:|---|---|---|
| 37 | `(ret = f(iface, surface))`，返回值被 retain 式存入 `IOSurface+0x3C8`，失败串是 `"can't prepare mapping"` | `virtual OSObject * preparedMappingForHostOnlySurface(IOSurface *surface) = 0;` | 为该 surface 建立 paravirt 侧映射，返回一个需要被持有的对象（失败返回 NULL） |
| 38 | `(bool) f(iface)`，无参 | `virtual bool supportsHostOnlySurfaces() const = 0;` | 门：false 则走普通分配路径 |

#### 名字的来源与适用范围 —— 必读 `KNOWN`（名字）+ 架构限制

名字**无法从 x86_64 样本取得**（纯虚槽没有符号）。上表的两个名字取自 **arm64 实现件**
`analysis/idb/macos26-25G325-arm64/AppleParavirtIOSurface.i64`（本轮只读 `$env:TEMP` 副本，
未改写仓库原件），其中实现类是 `IOSurfaceParavirtMapperInterface`，两个覆写符号是：

- `__ZN32IOSurfaceParavirtMapperInterface33preparedMappingForHostOnlySurfaceEP9IOSurface`
- `__ZNK32IOSurfaceParavirtMapperInterface24supportsHostOnlySurfacesEv`

**槽号对应关系是按"签名形状 + 相对顺序"推出来的，不是直接对上的，必须说清：**
在该 arm64 件里这两个方法落在 `__ZTV32IOSurfaceParavirtMapperInterface` 的**槽 39 与槽 40**
（用 vtable 槽 0/1/7 分别命中 `D1Ev` / `D0Ev` / `getMetaClass` 学出该件的 arm64e
chained-pointer 增量 `+0x07004000`，再代入槽 39/40 得到 `0x08503C1C` / `0x08503E74`，
与两个函数的符号地址精确相等）。而 x86 `[S]` 的基类 vtable 里纯虚槽在 **37/38**。
两边的**相对顺序一致**（先"收 `IOSurface *`、返回对象"的那个，后"无参、返回 bool"的那个），
且与 x86 侧 `IOSurface::allocate` 的调用形状（§4.2 的伪代码：先用无参 bool 当门，
再用收 surface 的那个建映射）一一吻合，错误串 `"can't prepare mapping"` 也与
`preparedMapping…` 同源。

**三条架构与样本警告（`00-OVERVIEW.md` §7 规则 2、规则 3）：**

1. **arm64 样本只能当命名参考。** 本条只用它取**名字**，不用它取槽号、不用它取 ABI、
   也不据它做任何 x86 实现决策。槽号 37/38 全部来自 x86 `[S]` 自己。
2. **该 arm64 样本并非 25G325。** 按 `90-EVIDENCE-INDEX.md` §3.2，这批 arm64 件的
   `LC_SOURCE_VERSION` 与 25G325 不符，目录名的构建标注不可信。槽号在两边不同
   （39/40 vs 37/38）正好是这件事的直接体现 —— 所以**不要**把 arm64 的槽号搬过来。
3. 名字可能在版本间改过。如果将来要写一个真实现，签名应以 x86 `[S]` 的调用形状为准，
   名字只用于可读性。

**对本项目：** 本项目不实现这个接口（§4.3 已证 x86 上没有注册者，mapper 恒为 NULL），
所以这两个名字只是让 §4.2 的伪代码读起来不再是 `vtable[37]`。顺带记下 arm64 侧的
完整栈形状供将来参考（**arm64-only，x86 上这些类全部不存在**）：
`IOSurfaceParavirtMapperDevice`（`IOService`，`probe`/`start`、ring、page-table
descriptor、wire/unwire host mapping）→ `IOSurfaceParavirtMapperService`
（`createMapping` / `mappingForSurface` / `prepared_mapping_for_host_only_surface`）
→ `IOSurfaceParavirtMapperInterface`（注册给 `IOSurfaceRoot` 的那一层），
外加 `IOSurfaceParavirtMapping` / `IOSurfaceParavirtMappingInternal` 两个载体类。

### 4.3 x86 路径上是否被使用：否 `KNOWN`

逐件解析每个样本**自己的** `LC_SYMTAB` nlist（不是共享字符串表 —— 见 `11-KERNEL-DISPLAY.md` §1.4），查找 `n_type & N_TYPE == N_UNDF` 且名字含 `registerMapperInterface` 或 `ParavirtMapper` 的条目：

| 样本 | 定义 | 未定义引用 |
|---|---|---|
| `com.apple.iokit.IOSurface` | 20 条（全部是基类自身的 ctor/dtor/metaclass/vtable + `registerMapperInterface` 本体） | 0 |
| `com.apple.iokit.IOPCIFamily` | 0 | **0** |
| `com.apple.iokit.IOAcceleratorFamily2` | 0 | 0 |
| `com.apple.driver.AppleParavirtGPU` | 0 | 0 |
| `com.apple.iokit.IOGraphicsFamily` | 0 | 0 |
| `com.apple.iokit.IOGPUFamily` | 0 | 0 |
| `com.apple.AppleGraphicsDeviceControl` | 0 | 0 |
| `kernel.x86_64` | 0 | 0 |

**结论：在已取得的 x86_64 二进制里，没有任何模块调用 `registerMapperInterface`，也没有任何类继承 `IOSurfaceRootParavirtMapperInterface`。** 因此 `IOSurfaceRoot` 的 `mapper` 字段恒为 NULL，`IOSurface::allocate` 的 paravirt 分支恒不执行。这与 `90-EVIDENCE-INDEX.md` §5.2 的事实（`AppleParavirtIOSurface.kext` 的 x86_64 可执行码确证不存在）一致 —— 这个接口的 x86 实现者本来就不存在。

**证据范围说明：** 两个 kernel collection 共 376 个 fileset 条目，本仓库只抽取了 7 个 graphics 相关 kext。严格说法是"在已抽取的 graphics 集合 + kernel 里没有注册者"。要做到全集闭合，需对两个 `.kc` 的全部条目做一次 nlist 扫描。

> **更正（第 4 轮）：** 原文此处写作"材料已在仓库内：`SystemKernelExtensions.kc` / `BootKernelExtensions.kc`"。**两个 `.kc` 本体都不在仓库内** —— `analysis/binaries/macos26-25G325-x86_64/` 下只有 7 个重建出来的 kext、`kernel.x86_64`、两个 Metal bundle 和若干 plist（含两个 `*.kc.elides`，那只是 elide 清单，不是 KC 本体）。所以这条属于**要上游材料**，不是"脚本化成本低"。
>
> **不过本轮发现了一条成本更低的替代路径，下一轮应该先试它：** 重建件的 `__LINKEDIT` 携带的是**整个 collection 的 linkedit 大块**，其中包含**全 collection 的 nlist 数组**。以 `com.apple.iokit.IOAcceleratorFamily2` 原件为例，它自己的 `LC_SYMTAB` 是 `symoff=0x5F9F80 / nsyms=4707 / stroff=0x6E5470 / strsize=0x601208`，而从 `__LINKEDIT` 真实 `fileoff 0x8C000` 一路到 `0x6E2700` 共 **415,344** 条 nlist 全部有效可解（本轮已实际解过，用于 `10-KERNEL-ACCELERATOR.md` §0.3(4) 的 stub 页否定证明）。对这 415,344 条按名字筛 `ParavirtMapper` / `registerMapperInterface`，就能在**不取 `.kc`** 的前提下把 System KC 侧做到全集闭合（Boot KC 侧同理，用 `IOSurface` 重建件）。唯一的限制是 nlist 不带"属于哪个 fileset 条目"的归属信息，所以能回答"全 collection 里有没有这个符号"，不能回答"是哪个 kext"。对本条（只问有无注册者）这已经够了。`KNOWN`（材料与口径）

**对本项目：** 完全无关。本项目不实现这个接口，也不受它影响。

## 5. `IOFenceTransaction` 与 swap 完成路径

### 5.1 `IOFence` `KNOWN`

`[S]` 24 条符号，继承 `OSObject`（自管引用计数，覆写了 `getRetainCount/tryRetain/retain/release/taggedRetain/taggedRelease/finalize`）：

| 方法 | `[S]` RVA | 说明 |
|---|---|---|
| `init()` | `0x1F8D4` | |
| `complete(int)` / `complete_locked(int)` | `0x1FA6A` / `0x1FA90` | 标记完成 |
| `getAcceleratorID()` | `0x1FAB6` | `return *(uint32_t*)(this + 32)` |
| `getFenceDirection()` | `0x1FAC0` | 读/写方向 |
| `getSurface()` | `0x1FB98` | 它守护的 surface |
| `writeTraceData(IOFenceTraceData*)` | `0x1FACA` | |
| `finalize()` | `0x1FB6C` | |

**`getAcceleratorID()` 的存在说明 fence 是按 accelerator 标识的** —— 多 GPU 时要知道是哪块卡的 fence。本项目只有一个 accelerator。

### 5.2 `IOFenceTransaction` `KNOWN`

`[S]` 55 条符号（含大量 tail-merge clone），继承 `OSObject`：

| 方法 | `[S]` RVA | 说明 |
|---|---|---|
| `fenceTransaction(IOService*)` | `0x2A9A` | 工厂 |
| `init(IOService*)` | `0x2AE6` | 绑到一个 service（accelerator / display machine） |
| `lock()` / `unlock()` | `0x2BE2` / `0x2BF0` | |
| `add_fence(IOFence*)` | `0x2CE8` | 把一个 fence 加入本事务 |
| `remove_fence(IOFence*)` | `0x2F7C` | |
| `copy_fences()` | `0x31AA` | 快照 |
| `addTransaction(IOFenceTransaction*)` | `0x32DE` | **事务可以嵌套/依赖另一个事务** |
| `runTransactionDeadlockCheck(IOFenceTransaction*, IOFenceTransaction*, uint)` | `0x3372` | **显式死锁检测** |
| `dump()` | `0x2BFE` | |

即 `IOFenceTransaction` 是一张 **fence 依赖图**，带环检测。

### 5.3 IOSurface 侧的 fence 队列 `KNOWN`

`[S]` `IOSurface` 的 fence 相关方法：

```
createFence(uint, uint)                                                   0xDF7A
createFence(IOFence**, uint, uint, void(*)(void*,void*,IOSurface*,int),
            void*, void*, uint)                                           0xDFE0
createFenceWithTransaction(IOFenceTransaction*, IOFence**, uint, uint,
            void(*)(void*,void*,IOSurface*,int), void*, void*, uint)       0xE648
fence_completed(IOFence*)              0xD976      fence_completed_locked  0xDA80
fence_completed_dispatch()             0xDC28      fence_track_time        0xDA4C
can_fence_be_coalesced_with_earlier_fence(IOFence*, IOFence*, bool)        0xDB44
can_fence_be_coalesced_with_current_q(IOFence*, bool)                     0xDB88
gather_dependent_transactions(IOFence*, OSSharedPtr<OSSet>)               0xE85A
trace_current_fence / fence_print / fence_debug / dumpQ / createFenceDebugDictionary
isTearingAllowed()                     0xE7C4
getLastReadFenceTime() / getLastWriteFenceTime()                      0x10A42 / 0x10A50
append_transaction(OSSharedPtr<IOSurfaceTransaction>)                     0x10DF6
query_transaction_list(task*, uint64, size_t, IOSurfaceTransactionFilter,
                       bool, size_t*, size_t*, size_t*)                   0x10E8E
prune_transaction_list() / _locked                 0x11146 / 0x11096
wait_on_transaction_list(bool)                     0x11170
```

调度侧：`IOSurfaceRoot::fenceDispatch(IOInterruptEventSource*, int)` RVA `0x15CF8`，挂在 `IOSurfaceRoot::start` 建立的 fence workloop 上（`11` 分册 §1.2 第 10 步）。

### 5.4 它在 swap 完成路径上的位置 `KNOWN`（机制）+ `INFERRED`（时序）

把 `11-KERNEL-DISPLAY.md` §4 与本节拼起来，加速 scanout 的一帧是这样走的：

```
WindowServer（用户态）
  └─ 向 IOAccelDisplayPipeUserClient2 提交一个 IOAccelDisplayPipeTransaction2
       [F2] IOAccelDisplayPipe::validateTransaction → beginTransaction(IOAccelEvent*)
            → submitTransaction(...)    （APV 覆写：[A] 0xBE24）
       事务里带着这一帧的 IOAccelResource2（其后备是一个 IOSurface）
  └─ 驱动侧为 "前一帧的写 fence" 建依赖：
       IOSurface::createFenceWithTransaction(txn, &fence, ...)      [S] 0xE648
       IOFenceTransaction::add_fence(fence)                         [S] 0x2CE8
       （跨 surface 依赖用 IOFenceTransaction::addTransaction + runTransactionDeadlockCheck）
  └─ 扫出完成（VBL 或 pipe 完成中断）
       [A] AppleParavirtDisplayPipe::signalTransactionComplete(IOAccelEvent*)  0xC388
       [A] AppleParavirtDisplayPipeFence::notifyClient()                       0xCDE0
       → IOFence::complete()                                        [S] 0x1FA6A
       → IOSurface::fence_completed(fence)                          [S] 0xD976
       → IOSurfaceRoot::fenceDispatch 在 workloop 上派发完成回调
       → [F2] IOAccelDisplayMachine::finish_transaction_queue(uint) / get_finished_transactions(...)
       → 用户态通过 shared event / notify port 得知该帧已上屏
```

`AppleParavirtDisplayPipeFence : IOAccelEventFence`（`[A]` `superClass` → `[F2]` RVA `0x81250` = `IOAccelEventFence::gMetaClass`），`init(IOGraphicsAccelerator2*, AppleParavirtDisplayPipe*)` 在 `[A]` RVA `0xC2C0`。

**`IOFenceTransaction` 的作用一句话：** 它是"这一帧上屏前必须等哪些 surface 的读/写完成"的那张依赖图，以及"这些依赖有没有成环"的检查器。它**不是**提交通道，也不是内存同步原语。

**对本项目：** 第一版不走事务型 scanout（`11` 分册 §4.1），所以这整条链不需要实现。IOSurface 的 fence 只在用户态需要 `MTLSharedEvent` 语义时才用到，走的是 selector 36–42/48 的 shared-event 路径，与 `IOFenceTransaction` 是两套东西。`INFERRED`

## 6. scanout surface 的所有权与生命周期

### 6.1 已确证的事实 `KNOWN`

1. **分配方是 WindowServer（用户态）。** `IOSurfaceRootUserClient` 的 `s_create_surface`（sel 0）/ `s_create_surface_fast_path`（sel 6）/ `s_create_surface_client_mem`（sel 7）是唯一的创建入口；内核里没有任何"驱动自己创建 IOSurface"的 API 被 `[F2]`/`[A]` 引用（`[F2]` 对 `IOSurface` 类只有 6 条符号引用，`[A]` 没有）。
2. **framebuffer 的后备内存与 scanout surface 是两件不同的东西。** `[A]` 的 framebuffer 后备是 kext 自己 `IOBufferMemoryDescriptor::withOptions` 分配的 64 MiB（`11` 分册 §2.5），不是 IOSurface。`[A]` `AppleParavirtDisplayPipe::initFramebufferResource(uint, IOAccelResource2*)` / `destroyFramebufferResource`（RVA `0xB924` / `0xB954`）与 `[F2]` `IOAccelDisplayMachine::initFramebufferResource(uint, uint, IOFramebuffer*, IOAccelResource2*)`（RVA `0xED68`）表明：**framebuffer 内存被包装成一个 `IOAccelResource2`** 才进入 display pipe 的世界。
3. **accelerator 侧对 surface 只持引用。** `IOAccelSurfaceMTL::attach_surface_at_index` 做 `retain()` + 递增 use count（§3.3），`detach_surface_at_index` 反向。
4. **surface 侧有三层计数**：OSObject 引用计数（`retain`/`release`）、client 计数（`IOSurface::clientRetain 0xB3E6` / `clientRelease 0xB3F8` / `getClientRetainCount 0xB42A`）、per-category use count（`increment_use_count_for_category 0xB05A` / `decrement_use_count_for_category 0xB162`，以及 `IOSurfaceClient::get_client_use_count_for_category 0x11BC2`）。`s_release_surface`（sel 1）走 client 计数，不是直接 `release`。
5. **回收是异步的。** `IOSurfaceRoot::start` 起了 `async_release_thread`；`IOSurface::unregister_surface 0x8460`、`deallocate 0x890A`、`finalize 0x8392`、`free 0x85E4` 分层。`IOSurfaceRoot` 还有 `prune_transaction_list` 与 orphan device cache 清理。
6. **"正在扫出"的判定在 accelerator 侧**：`[F2]` `IOAccelDisplayMachine::is_current_display_resource(IOAccelResource2*)` RVA `0xEEF0`、`IOAccelLegacyDisplayMachine::audit_freed_resource(IOAccelResource2*)` RVA `0x13A2`。即防止"正在扫出的 buffer 被释放"是 accelerator 的职责，IOSurface 不管。

### 6.2 对本项目的落法 `INFERRED`

既然第一版不开 `DisplayPipeSupported`（`11` 分册 §4.1），**就没有"scanout surface"这个对象**：

```
Lavapipe 渲染目标  ==  本项目 framebuffer 的 IOBufferMemoryDescriptor
WindowServer 的 backing store  ==  同一块内存（通过 clientMemoryForType(110) 映射）
IOSurface 只用于 Metal 客户端自己的 texture/drawable，与上屏无关
```

所有权：那块 `IOBufferMemoryDescriptor` 由**本项目的 framebuffer 对象持有**，在 `initWithID` 分配、在 `free()` 释放，生命周期 == framebuffer service 的生命周期。WindowServer 的映射由 `IOFramebufferUserClient` 的 `clientMemoryForType` 建立、随 user client 销毁而失效，不影响内核侧的所有权。

如果将来要上事务型 scanout，需要额外确证的点（本轮**未查清**）：

| 项 | 查清方法 |
|---|---|
| `IOAccelResource2` 怎么从一个 IOSurface 构造（`[F2]` `IOAccelResource2` 110 条符号） | 反编译 `[F2]` `IOAccelResource2` 的 `init*` 族与 `IOGraphicsAccelerator2` 的 resource 工厂（`[A]` 对应 `newResource 0x3246`） |
| `IOAccelDisplayPipeTransaction2` 的结构（`[F2]` 38 条符号） | 反编译 `IOAccelDisplayPipe::validateTransaction` / `submitTransaction` |
| WindowServer 用哪个 user client 提交事务 | `[F2]` `IOAccelDisplayPipeUserClient2`（57 条符号）的 dispatch 表 |
| scanout buffer 数量与翻页策略 | `[F2]` `IOAccelLegacyDisplayMachine::getScanoutSurface / getFullScreenSurface / getWindowServerFullScreenAssemblySurface` 的语义 |

## 7. 本分册遗留的未查清项

| 项 | 状态 | 需要什么 | 怎么查 |
|---|---|---|---|
| ~~`IOSurfaceLockResult`（3176 字节）逐字段~~ | **已关闭（§1.5）** | — | — |
| ~~`IOSurfaceRootUserClient` 的 restricted 位由什么决定~~ | **已关闭（§1.4）** | — | — |
| ~~两个 paravirt mapper 纯虚方法的真实名字~~ | **已关闭（§4.2），并标明只是 arm64 命名参考** | — | — |
| ~~内核侧 surface ID → `IOSurface*` 的 KPI 入口~~ | **已关闭（§3.4）** | — | — |
| ~~`IOSurface::isDisplayable()` 的置位点~~ | **已关闭（§2.2）：本构建无置位点，恒为 0；原文归属有误，已更正** | — | — |
| `IOSurfaceRoot::lookupSurface` 是否作为 KPI 导出 | 未关闭 | **要上游材料** | 需 `IOSurface.kext/Contents/Resources/.../IOSurface.exports`（仓库里只有 `IOPCIFamily.exports`） |
| 全集确认"没有 x86 注册者"（§4.3 的证据范围限制） | 未关闭，但**降级为"可关"** | — | §4.3 已更正：原文说两个 `.kc` 在仓库内是错的（不在），但本轮找到替代路径 —— 直接解重建件 `__LINKEDIT` 里的全 collection nlist（415,344 条，口径与证据见 §4.3 的更正框）。**可关，本轮因时间未做** |
| `fillAdditionalPlaneInfo` 的内部填法（§1.5.3 第 2 行） | 未关闭 | — | 反编译 `[S]` `fillAdditionalPlaneInfo`。**可关**，本轮因时间未做；只影响 `41` 分册对 plane 记录中那一段的命名 |
| `IOSurfaceLockResult` 各字段的**语义名** | 未关闭 | 用户态样本 | 偏移与来源 ivar 已全部给出（§1.5.2/§1.5.3）；要命名需 `IOSurface.framework` 的 x86_64 消费点（T3，本轮未取）。**可关** |
| 事务型 scanout 全链（见 §6.2 表） | 未关闭 | — | 四条全部**可关**（`[F2]` IDB 在仓库内），本轮判定为低优先：第一版不走事务型 scanout，且 `11` 分册 §4.1 已证该链在本构建上没有用户态观察者 |
| 本分册全部结论都是静态的，无 `TESTED` | 未关闭 | **要开机** | 见 `80-TEST-HARNESS.md` |

## 8. 本轮关闭的未查项（第 4 轮，2026-10-31）

本轮**只读既有 IDB 的 `$env:TEMP` 副本**（含一次对 arm64 件的只读引用，见 §4.2 的
架构警告），没有新建 `.i64`，没有改写 `analysis/` 下任何文件。

| # | 原条目 | 结论 | 证据（样本 UUID + RVA） | 新标签 |
|---|---|---|---|---|
| 1 | §1.5「`IOSurfaceLockResult` 的逐字段布局本轮未展开」 | **136 字节头 + 20 × 152 字节 plane 记录 = 3176**，头部 24 个字段与 plane 记录的四段来源全部给出（§1.5.2 / §1.5.3）。附带确证 planeCount 被硬截到 20 | `[S]` `766DF6D3-1EEC-34DB-A9AD-EF72A36FB2A8`：`IOSurfaceClient::getLockResult` `+0x11C0A`（含起始 `___bzero(out, 3176)` 与越界检查 `out + 3176`） | `KNOWN` |
| 2 | §1.4「哪个条件置 restricted 位本轮未查清」 | `obj+0x127 bit0 = task 持有 com.apple.private.gpu-restricted 或 com.apple.developer.gpu-restricted`。方向是**降权**而非提权；连带给出 `+0x122` / `+0x123` / `+0x126` 三个相邻标志的 entitlement 来源 | `[S]`：`IOSurfaceRootUserClient::init` `+0x1B228`（四个 entitlement 字面量与四次 `OSBoolean` 真值比较均在函数体内）；选表点 `externalMethod +0x1E1E0` | `KNOWN` |
| 3 | §4.2「两个纯虚方法的方法名无法从二进制取得」 | 槽 37 = `preparedMappingForHostOnlySurface(IOSurface *)`、槽 38 = `supportsHostOnlySurfaces() const`。**名字来自 arm64 实现件，仅作命名参考**；槽号仍来自 x86 `[S]`，两边槽号不同（arm64 为 39/40），已在 §4.2 明确标注 | x86 槽号：`[S]` `__ZTV…ParavirtMapperInterface` `+0x2F350`、消费点 `IOSurface::allocate +0x7AB8`。arm64 命名：`analysis/idb/macos26-25G325-arm64/AppleParavirtIOSurface.i64`，类 `IOSurfaceParavirtMapperInterface`，chained-pointer 增量 `+0x07004000`（由槽 0/1/7 学出） | `INFERRED` → `KNOWN`（形状）+ 命名参考（arm64，非 25G325） |
| 4 | §3.4「内核侧 surface ID → `IOSurface*` 的 KPI 入口未查清」 | `IOSurfaceRoot::lookupSurface(uint32_t, task*)` `+0x16612`；另有 `lookupSurfaceFromClient +0x16774` 与私有 `find_surface +0x164B8`。给出 `find_surface` 的表结构（surface ID 就是下标）与三条放行条件，其中 `flags bit1 置 / bit19 清` 是"全局可见"开关 | `[S]`：`+0x16612` / `+0x16774` / `+0x164B8`；`IOSurface::getSurfaceID +0xA720` | `KNOWN` |
| 5 | §4.3「材料已在仓库内：`SystemKernelExtensions.kc` / `BootKernelExtensions.kc`」 | **原陈述有误，已更正。** 两个 `.kc` 本体都不在仓库内。但本条因此**没有变成 `BLOCKED`** —— 本轮找到替代路径：解重建件 `__LINKEDIT` 里的全 collection nlist（415,344 条），可在不取 `.kc` 的前提下做全集闭合 | `com.apple.iokit.IOAcceleratorFamily2` 原件 `LC_SYMTAB symoff=0x5F9F80 / nsyms=4707 / stroff=0x6E5470 / strsize=0x601208`，nlist 区 `0x8C000..0x6E2700`；仓库内容清点见 `analysis/binaries/macos26-25G325-x86_64/` | **更正**，并由"要上游材料"降为"可关" |
| 6 | §2.2「`isDisplayable()` 由 `parse_properties` 设置。`INFERRED`（置位点未逐一追）」 | **原结论有误，已更正。** `parse_properties`（`+0x42B0`）对 `surf+0x3D8` 没有任何访问；该标志字只由 `IOSurface::init` 与 `setLayoutFromDescriptor` 等写。**bit 20（`isDisplayable`）在全件没有置位点，只有 `init +0x3F83` 的清零**，故 `isDisplayable()` 在本构建上恒返回 0。顺带把该标志字的 11 个已知位的写入点全部列出 | `[S]`：读取 `+0x109F4`；清零 `+0x3F83`（`and 0xFFEDB3FD`）；全件扫描口径 = 1,673 函数 × 全部 `surf+0x3D8/0x3D9/0x3DA/0x3DB` 内存操作数（71/8/13/4 处） | `INFERRED` → `KNOWN`，**并更正原结论** |

