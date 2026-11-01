# 20 — ObjC Device 层：`MTLIOAccelDevice` 继承契约

文档版本：1.0
基线：macOS Tahoe 26.7.2 / build 25G325 / **x86_64**
职责（见 `00-OVERVIEW.md` 第 8 节）：`_MTLIOAccelDevice` 继承契约；init 链对 user client 的真实依赖；必须覆写的方法集

## 0. 样本、地址与标签约定

所有地址写成 `样本代号 + RVA`。RVA = 绝对 VA − 该样本 image base。

| 代号 | 文件 | LC_UUID | arch | image base | 来源层 |
|---|---|---|---|---|---|
| `S-METAL` | `analysis/.../raw/Metal` | `FDB3FD2C-840A-3FC3-81FB-C524F891F642` | x86_64 | `0x7FF80B179000` | BaseSystem dyld shared cache |
| `S-IOACCEL` | `analysis/.../raw/IOAccelerator` | `4FDBB3F6-9AA3-352B-87ED-57161AA64D1F` | x86_64 | `0x7FF80B170000` | BaseSystem dyld shared cache |
| `S-AMD` | `metal_drivers/AMDRadeonX6000MTLDriver_decompressed` | `774E6DC1-A6B4-381B-AFD9-29C8E813DE95` | x86_64 | `0x0` | 安装包载荷解压 |
| `S-INTEL` | `metal_drivers/AppleIntelICLGraphicsMTLDriver_decompressed` | `251E3AE2-1396-3AD1-974A-422AE954B85A` | x86_64 | `0x0` | 安装包载荷解压 |

`S-METAL` 与 `S-IOACCEL` 的 base 与 UUID 已与 `analysis/idb/macos26-25G325-x86_64-frameworks/MANIFEST.md` 核对一致。

`S-AMD` / `S-INTEL` 的 SHA-256 与来源层**未登记在任何 MANIFEST 中**，需由 `90-EVIDENCE-INDEX.md` 补登。本文使用它们仅为"厂商如何继承基类"这一类结构性结论，不用于 ABI 常量。

证据标签：`KNOWN` / `INFERRED` / `BLOCKED` / `TESTED`，定义见 `00-OVERVIEW.md` 第 7 节。

### 0.1 一处命名修正

Apple 的类名是 **`MTLIOAccelDevice`**，没有前导下划线。`00-OVERVIEW.md` 第 4.4 节写作 `_MTLIOAccelDevice`，是笔误。

带下划线的 `_MTLDevice` 是它的**父类**，两者是不同的类，且本文最重要的结论正好落在这条边界上。`KNOWN`：`S-METAL` `__objc_classlist` 遍历得 `MTLIOAccelDevice <- _MTLDevice <- NSObject`。

## 1. 结论摘要

| 问题 | 结论 | 标签 |
|---|---|---|
| 三个 init 方法属于哪个类 | **`_MTLDevice`，不是 `MTLIOAccelDevice`** | `KNOWN` |
| 三个 init 方法是否打 user client | **完全不打**。零 IOKit 调用、零 IORegistry 读取 | `KNOWN` |
| `initLimits` 的输入 | `[self featureProfile]`、`[self argumentBuffersSupport]`、`[self maxBufferLength]`，仅此三者 | `KNOWN` |
| `initGPUFamilySupport` 的输入 | `[self featureProfile]`，仅此一个 | `KNOWN` |
| `initFeatureQueries` 的输入 | 纯 ObjC self-query，构造 `_MTLDeviceFeatureQueries` 表 | `KNOWN` |
| 内核侧规模 | **小工程**：type-5 两个必需 selector（0 与 2），共 664 字节固定结构 | `KNOWN` |
| ObjC 对象族 | **继承 Apple `MTLIOAccel*` 族**，AMD 与 Intel 都这么做 | `KNOWN` |
| 既有文档地址 | 第 8 问列的六个 RVA **全部正确**；type encoding 也正确 | `KNOWN` |

**本任务要查清的"最关键未知"的答案**：`_MTLDevice` 基类不向 user client 索要 GPU 拓扑或内存信息。整张 limits 表是 `featureProfile` 这一个枚举值的纯函数。AMD 的 `featureProfile` 实现是 `return 10002;`（`S-AMD` RVA `0x241E8`，整个方法体就这一行）。

因此 `00-OVERVIEW.md` 第 4.4 节"三个方法对 user client 的真实依赖是决定 ③ 规模的关键未知"可以结案：**它们不是风险项**。③ 的真实规模由 `IOAccelDeviceCreateWithAPIProperty` 的创建链决定，而那条链是封闭且完全可枚举的（第 7 节）。

## 2. 类继承决策

### 2.1 Metal 提供两层基类

`KNOWN`（`S-METAL` `__objc_classlist` 全量遍历，`class_t.superclass` 解析）。

Apple 对每类对象都备了两层：抽象层 `_MTL*`（纯 ObjC，不碰 IOKit）和 IOKit 后端层 `MTLIOAccel*`。

| `MTLIOAccel*` 类 | 父类 |
|---|---|
| `MTLIOAccelDevice` | `_MTLDevice` |
| `MTLIOAccelCommandQueue` | `_MTLCommandQueue` |
| `MTLIOAccelCommandBuffer` | `_MTLCommandBuffer` |
| `MTLIOAccelCommandEncoder` | `_MTLCommandEncoder` |
| `MTLIOAccelRenderCommandEncoder` | `MTLIOAccelCommandEncoder` |
| `MTLIOAccelComputeCommandEncoder` | `MTLIOAccelCommandEncoder` |
| `MTLIOAccelBlitCommandEncoder` | `MTLIOAccelCommandEncoder` |
| `MTLIOAccelResourceStateCommandEncoder` | `MTLIOAccelCommandEncoder` |
| `MTLIOAccelParallelRenderCommandEncoder` | `_MTLParallelRenderCommandEncoder` |
| `MTLIOAccelDebugCommandEncoder` | `_MTLDebugCommandEncoder` |
| `MTLIOAccelResource` | `_MTLResource` |
| `MTLIOAccelBuffer` | `MTLIOAccelResource` |
| `MTLIOAccelTexture` | `MTLIOAccelResource` |
| `MTLIOAccelPooledResource` | `MTLIOAccelResource` |
| `MTLIOAccelIndirectCommandBuffer` | `MTLIOAccelResource` |
| `MTLIOAccelAccelerationStructure` | `MTLIOAccelResource` |
| `MTLIOAccelIntersectionFunctionTable` | `MTLIOAccelResource` |
| `MTLIOAccelVisibleFunctionTable` | `MTLIOAccelResource` |
| `MTLIOAccelHeap` | `_MTLHeap` |
| `MTLIOAccelFence` | `_MTLFence` |
| `MTLIOAccelIndirectArgumentEncoder` | `_MTLIndirectArgumentEncoder` |
| `MTLIOAccelIndirectRenderCommand` | `_MTLIndirectRenderCommand` |
| `MTLIOAccelIndirectComputeCommand` | `_MTLIndirectComputeCommand` |
| `MTLIOAccelIOCommandQueue` | `_MTLIOCommandQueue` |
| `MTLIOAccelIOCommandBuffer` | `_MTLIOCommandBuffer` |
| `MTLIOAccelIOHandleRaw` / `...Compressed` | `_MTLIOHandleRaw` / `_MTLIOHandleCompressed` |
| `MTLIOAccelDeviceShmem` / `...ShmemPool` / `MTLIOAccelResourcePool` / `MTLIOAccelService` / `MTLIOAccelServiceDescriptor` / `MTLIOAccelServiceGlobalContext` / `MTLIOAccelTextureLayout` | `NSObject` |

注意 pipeline state、sampler、depth/stencil state、library、function **没有** `MTLIOAccel*` 版本 —— 只有抽象层。这些对象本来就与内核无关。

### 2.2 厂商实际怎么继承

`KNOWN`（`S-AMD`、`S-INTEL` classlist 遍历）。

Intel（`AppleIntelICLGraphicsMTLDriver`，`MTLIG*` 前缀）几乎一比一吃掉 `MTLIOAccel*` 层：

| Intel 类 | 父类 |
|---|---|
| `MTLIGAccelDevice` | `MTLIOAccelDevice` |
| `MTLIGAccelCommandQueue` | `MTLIOAccelCommandQueue` |
| `MTLIGAccelCommandBuffer` | `MTLIOAccelCommandBuffer` |
| `MTLIGAccelRenderCommandEncoder` | `MTLIOAccelRenderCommandEncoder` |
| `MTLIGAccelComputeCommandEncoder` | `MTLIOAccelComputeCommandEncoder` |
| `MTLIGAccelBlitCommandEncoder` | `MTLIOAccelBlitCommandEncoder` |
| `MTLIGAccelParallelRenderCommandEncoder` | `MTLIOAccelParallelRenderCommandEncoder` |
| `MTLIGAccelBuffer` / `MTLIGAccelTexture` | `MTLIOAccelBuffer` / `MTLIOAccelTexture` |
| `MTLIGAccelHeap` | `MTLIOAccelHeap` |
| `MTLIGAccelIndirectArgumentEncoder` / `MTLIGAccelIndirectCommandBuffer` / `MTLIGAccelVisibleFunctionTable` | 对应 `MTLIOAccel*` |
| `MTLIGComputePipelineState` / `MTLIGRenderPipelineState` / `MTLIGSampler` / `MTLIGDepthStencilState` / `MTLIGFunctionHandle` / `MTLIGIndirectArgumentBufferLayout` | 对应 `_MTL*` 抽象层 |

AMD（`AMDRadeonX6000MTLDriver`，`GFXAAMD_*` / `GFX10_*` 两级前缀）同样吃 `MTLIOAccel*` 层，但有两处差异：

- `GFXAAMD_MtlDevice <- MTLIOAccelDevice`，再 `GFX10_MtlDevice <- GFXAAMD_MtlDevice`（家族通用层 + 芯片代际层两级）。
- **AMD 不子类化 command queue**，直接用 Apple 的 `MTLIOAccelCommandQueue`（在 `S-AMD` 中以 extern class 引用存在）。Intel 则子类化了。说明 queue 层是否覆写由厂商自选，不是硬要求。
- `GFXAAMD_MTLLibrary <- NSObject`：library 完全自建，不走 Metal 的任何基类。

### 2.3 本项目的决策

**采纳 `00-OVERVIEW.md` 第 4.4 节：Device 类继承 `MTLIOAccelDevice`。本文追加一条：整个对象族都继承 `MTLIOAccel*` 层，与 AMD/Intel 一致。** `INFERRED`

理由不是"厂商这么做所以照抄"，而是三条可验证的收益：

1. `MTLIOAccelDevice` 以外的 `MTLIOAccel*` 类**绝大多数只用 trace API**（第 8 节逐条列出），trace 关闭时是空操作。继承它们几乎不带来内核依赖，却白拿到全部 `MTLDevice` / `MTLDeviceSPI` / `MTLCommandBuffer` 等协议的基类填充。
2. 真正打 user client 的只有三处：queue 创建与提交、resource 创建、`lazyInitialize`。这三处**本来就必须覆写**，因为它们要接 Vulkan。
3. `_MTLCommandBuffer` / `_MTLCommandEncoder` 等抽象层负责 label、debug group、encoder 状态机、retained-references 语义等大量与后端无关的簿记。放弃它们等于白写几千行。

反向约束：继承 `MTLIOAccelDevice` 意味着必须让 `initWithAcceleratorPort:` 走通（第 4 节），即必须有一个 type-5 user client 返回第 7 节那两个结构。这是本决策唯一的真实代价，且该代价是小的。

## 3. 创建链全序列

`KNOWN`。从 Metal 发现服务到设备进入 `MTLCopyAllDevices` 的完整顺序。

```
MTLRegisterDevices()                                S-METAL +0x1D980D
  └─ [[MTLIOAccelServiceGlobalContext alloc] init]
       └─ IOServiceMatching("IOAccelerator") 匹配通知（分册 10 负责）
            └─ getMetalPluginClassForService(service)     S-METAL +0x1D89FB
            └─ [[MTLIOAccelService alloc] initWithAcceleratorPort:service
                                          deviceClass:cls]   S-METAL +0x1D9395
                 ├─ IOObjectConformsTo(port,"IOServiceCompatibility") 必须为 false
                 ├─ IOObjectRetain(port)
                 ├─ IORegistryEntryGetRegistryEntryID(port, &svc->registryID)
                 ├─ IOServiceAddInterestNotification(..,"IOGeneralInterest",..) 必须成功
                 ├─ 若 mtlAvoidRemovable() 且存在 "Removable" 属性 → 放弃
                 ├─ 若存在 "SafeEjectRequested" 属性 → 不创建 device
                 ├─ device = [[deviceClass alloc] initWithAcceleratorPort:port]   ← 第 4 节
                 ├─ objc_storeWeak(&svc->_device, device)
                 ├─ [device _setAcceleratorService:svc]
                 └─ MTLAddDevice(device)                 S-METAL +0x23B0
                      ├─ assert(_deviceArray != NULL)
                      ├─ assert([device conformsToProtocol:@protocol(MTLDevice)])
                      ├─ assert([device conformsToProtocol:@protocol(MTLDeviceSPI)])
                      ├─ [device initLimits]              ← 第 5 节
                      ├─ [device initFeatureQueries]
                      ├─ [device initGPUFamilySupport]
                      ├─ 若 _CFMZEnabled() 再发一条 selector（MacCatalyst 路径）
                      └─ dispatch_sync(_deviceArrayQueue, ^{ 追加到 _deviceArray })
```

### 3.1 plugin class gate

`getMetalPluginClassForService` （`S-METAL` +0x1D89FB）`KNOWN`：

1. 读 IORegistry 属性 `MetalPluginName`（必须是 `CFString`）。
2. `gpu_bundle_find_trusted(name, pathOut, 1024)` 必须返回 0。这是 trust gate，对应既有文档的 B-009。**本轮已反编译到底，`B-009` 关闭，机制如下（`KNOWN`，`libsystem_sandbox-BaseSystem-analysis.i64`）：**

   **它不在 `Metal` 里。** `Metal` 的 `_gpu_bundle_find_trusted` 只是一条
   `jmp qword ptr cs:…` 的 stub，导入自 `/usr/lib/libSystem.B.dylib`；真实现是
   `libsystem_sandbox.dylib` 的 `_gpu_bundle_find_trusted`（`0x7ff80c4d0270`）。

   ```c
   // 遍历 GPU_STANDARD_BUNDLE_PATHS（0x7ff8412168d0），循环 v6 += 8 到 v6 == 16，
   // 所以表恰好两项；第三项读出来是 NULL。
   //   [0] "/Library/GPUBundles"          ← Data 卷，先搜这个
   //   [1] "/System/Library/Extensions"   ← 系统卷
   snprintf(buf, 1024, "%s/%s.bundle", GPU_STANDARD_BUNDLE_PATHS[i], name);
   if (stat(buf, &st) != 0) { if (errno != ENOENT) return -1; continue; }
   if ((st.st_mode & S_IFMT) != S_IFDIR) continue;          // 必须是目录
   if (gpu_bundle_is_path_trusted(buf) == -1) return -1;
   if (gpu_bundle_is_path_trusted(buf) != 0)   continue;    // ← 注意：非 0 = 不可用
   strlcpy(pathOut, buf, size);  return 0;                  // ← 0 = 可用
   ```

   **`gpu_bundle_is_path_trusted` 的语义与名字相反：返回 0 才算可用。** 它是：

   ```c
   // 0x7ff80c4d043b
   result = rootless_check_trusted_class(path, "KernelExtensionManagement");
   if (result == 1) return !_dyld_shared_cache_contains_path(path);
   return result;
   ```

   而 `rootless_check_trusted_class` → `rootless_check_trusted_internal`
   （`0x7ff80c4cf8cb`）的**第一条语句**决定一切：

   ```c
   v6 = 0;
   if (csr_check(2) == 0)   // 2 = CSR_ALLOW_UNRESTRICTED_FS
       return v6;           // 返回 0 → 调用方判定「可用」
   ```

   **所以 SIP 关闭时 trust gate 直接放行，一条 sandbox 规则都不查。**
   `00-OVERVIEW.md` 第 4.5 节那句「研发期 SIP/AMFI 关闭下不构成阻断」因此从
   `INFERRED` 升为 `KNOWN`，而且依据是机制不是经验。

   同一函数的第二条放行分支顺带定义了 ARV 的语义：

   ```c
   if (path != NULL && is_path_on_authenticated_root_volume(path) != 0)
       return 0;            // 在 ARV 上 → 也放行
   ```

   **路径在 ARV 上就不查 rootless 规则，因为 ARV 已经用 seal 保证了完整性。
   两套机制是互替的：ARV 上靠 seal，非 ARV 上靠 sandbox 规则。**
   `/Library/GPUBundles` 在 Data 卷（非 ARV），走第二套，而第二套在 SIP 关闭时整条让过。
3. `[NSBundle bundleWithPath:path]` 必须非 nil。
4. 读 `MetalPluginClassName`：是 `CFString` 则 `[bundle classNamed:]`；**属性缺失或类型不对则退回 `[bundle principalClass]`**。
5. `[cls isSubclassOfClass:[_MTLDevice class]]` 必须为真，否则返回 nil。

第 5 点只要求 `_MTLDevice` 子类，与 `00-OVERVIEW.md` 第 4.4 节描述一致。`MTLIOAccelDevice` 子类自动满足。

### 3.2 对 kext 的隐含要求

从 3 和 3.1 直接推出，本项目 kext 的 accelerator service 必须：

| 要求 | 来源 | 标签 |
|---|---|---|
| 能被 `IOServiceMatching("IOAccelerator")` 命中 | 分册 10 | — |
| 发布 `MetalPluginName`（CFString） | `S-METAL` +0x1D89FB | `KNOWN` |
| 发布 `MetalPluginClassName`（CFString，可省，省则用 principalClass） | 同上 | `KNOWN` |
| **不**继承/声明 `IOServiceCompatibility` | `S-METAL` +0x1D9395 | `KNOWN` |
| **不**发布 `Removable` 属性 | 同上 | `KNOWN` |
| **不**发布 `SafeEjectRequested` 属性 | 同上 | `KNOWN` |
| 支持 `IOGeneralInterest` 兴趣通知（`IOService` 默认即可） | 同上 | `KNOWN` |

## 4. `-[MTLIOAccelDevice initWithAcceleratorPort:]`

`S-METAL` RVA `0x17CF`。`KNOWN`，Hex-Rays 全函数反编译。

### 4.1 Type encoding（第 9 问核对）

| 项 | 值 |
|---|---|
| type encoding | **`@20@0:8I16`** —— 与既有文档一致，**正确** |
| method record | `S-METAL` +0x217F1C（`__objc_methlist`，relative method list，12 字节条目） |
| types 字符串 | `S-METAL` +0x2D4A2E（`__objc_methtype`） |
| imp | `S-METAL` +0x17CF |

即 `- (id)initWithAcceleratorPort:(unsigned int)port`，参数是 `io_service_t`（`mach_port_t`，4 字节）。

### 4.2 实现体（按执行顺序）

```objc
self = [super init];                       // -> -[_MTLDevice init]  S-METAL +0x19EA
if (self) {
    _deviceRef = IOAccelDeviceCreateWithAPIProperty(port, "Metal");
    if (_deviceRef == NULL) goto fail;                      // ← 失败点 1

    IORegistryEntryGetRegistryEntryID(port, &_registryID);
    _acceleratorPort = port;
    IOObjectRetain(port);
    _storageCreateParams.<+0x10> = 0;
    _storageCreateParams.<+0x18> = 0;

    IOAccelDeviceGetConfig64(_deviceRef, &_configBits, &_deviceBits,
                             &_textureRam, &_videoRam, &_accelID);
    IOAccelDeviceGetPeerInfo(_deviceRef, &_peerGroupID, &_peerIndex, &_peerCount);
    if (_peerGroupID != 0) _peerConnections = [[NSMutableDictionary alloc] init];
    IOAccelDeviceGetSharedMemorySize(_deviceRef, &_sharedMemorySize);

    if (_configBits & 0x1000) {            // byte 0x321 bit 0x10
        if (_videoRam != 0 && _sharedMemorySize > _videoRam)
            _sharedMemorySize = _videoRam;
        _videoRam   = 0;
        _textureRam = 0;
    }

    _globalTraceObjectID = IOAccelDeviceGetGlobalTraceObjectID(_deviceRef);
    if (trace enabled) IOAccelDeviceTraceEvent(0, 1, 11, _globalTraceObjectID, 0, 0, 0);
    [self <selA>];                         // void，返回值忽略，未解析出名字
}
if (![self supportLazyInitialization] && ![self lazyInitialize])
    goto fail;                                                // ← 失败点 2
return self;

fail:
    objc_release(self);  // 经 __objc_stubs
    return nil;
```

三处要点：

1. **`[super init]` 是 `-[_MTLDevice init]`**（`S-METAL` +0x19EA）。该方法完全是用户态：建三条 dispatch queue、`MTLLoader`、`MTLResourceListPool`、读 `MTL_FORCE_COMMAND_BUFFER_ENHANCED_ERRORS` / `MTL_DISABLE_UPGRADER_DAEMON` / `MTL_LOG_LEVEL` / `MTL_LOG_BUFFER_SIZE` 等环境变量、`dyld_program_sdk_at_least` 判定。**零 IOKit 调用。** `KNOWN`
2. 两个返回 `nil` 的失败点只有两处，且都可枚举：`IOAccelDeviceCreateWithAPIProperty` 返回 NULL，或 lazy-init 对偶双双返回假。
3. `selA`（`S-METAL` 的 selref 槽 +0x35E9DD88）**未解析出名字**。该 selref 在整个 `S-METAL` 中只被本函数引用一次，而 Metal 在 dyld shared cache 中的 selector 字符串被 unique 到了镜像外的地址（`__objc_selrefs` 内容指向 `0x7FF820076A7B`，超出本镜像 `__objc_methname` 范围 `+0x299CBF..+0x2D2975`）。见第 12.1 节的查清方法。它返回 void 且返回值被忽略，故不构成失败点。

### 4.3 实例变量布局

`KNOWN`：偏移全部取自 `_OBJC_IVAR_$_*` 符号的值，并与反编译出的访问一致。

`_MTLDevice` 的 `instanceSize` 止于 `0x2C8`；`0x2C8` 起为 `MTLIOAccelDevice` 自己的 ivar。

`_MTLDevice`（父类，节选出与本分册相关的）：

| 偏移 | 名称 | 写入者 |
|---|---|---|
| `0x008` | `_limits` | `-[_MTLDevice initLimits]` |
| `0x198` | `_globalTraceObjectID` | `initWithAcceleratorPort:` |
| `0x228` | `_gpuFamiliyInitLock` | `initGPUFamilySupport`（`os_unfair_lock`，拼写是 Apple 原样） |
| `0x268` | `_architecture` | `-[_MTLDevice architecture]` 懒构造 |
| `0x288` | `_supportedGPUFamilies` | `initGPUFamilySupport`（`std::vector<int64>`，16 字节 begin/end + 8 字节 cap） |
| `0x2A8` | `_featureQueries` | `initFeatureQueries` |
| `0x2C0` | `_commandBufferErrorOptions` | `-[_MTLDevice init]` |

`MTLIOAccelDevice`：

| 偏移 | 名称 | 类型 | 来源 |
|---|---|---|---|
| `0x2C8` | `_deviceRef` | `IOAccelDeviceRef` | `IOAccelDeviceCreateWithAPIProperty` |
| `0x2D0` | `_sharedRef` | `IOAccelSharedRef` | `IOAccelSharedCreate`（在 `lazyInitialize` 中） |
| `0x2D8` | `_acceleratorPort` | `io_service_t` (u32) | 入参 |
| `0x2E0` | `_acceleratorService` | `MTLIOAccelService *` | `_setAcceleratorService:` |
| `0x2E8` | `_storageCreateParams` | struct，0x30 字节 | `lazyInitialize` |
| `0x318` | `_commandBufferStoragePool` | ptr | `lazyInitialize` |
| `0x320` | `_configBits` | u32 | selector 0 `+0x00` |
| `0x324` | `_deviceBits` | u32 | selector 0 `+0x04` |
| `0x328` | `_textureRam` | u64 | selector 0 `+0x08` |
| `0x330` | `_videoRam` | u64 | selector 0 `+0x10` |
| `0x338` | `_sharedMemorySize` | u64 | selector 0 `+0x20` |
| `0x340` | `_accelID` | u32 | selector 0 `+0x18` |
| `0x344` | `_numCommandBuffers` | u32 | 运行期 |
| `0x348` | `_segmentByteThreshold` | u64 | `lazyInitialize` 置 0 |
| `0x350` | `_peerGroupID` | u64 | selector 0 `+0x30` |
| `0x358` | `_peerIndex` | u32 | selector 0 `+0x38` |
| `0x35C` | `_peerCount` | u32 | selector 0 `+0x3C` |
| `0x360` | `_peerMask` | u64 | 运行期 |
| `0x368` | `_peerConnectionsLock` | lock | — |
| `0x370` | `_peerConnections` | `NSMutableDictionary *` | 仅当 `_peerGroupID != 0` |
| `0x3B0` | `_bufferHeaps` | 大数组，延伸至 `0xD430` | 运行期 |
| `0xD430` | `_device_dispatch_queue` | ptr | `lazyInitialize` |
| `0xD438` | `_device_pool_cleanup_queue` | ptr | `lazyInitialize` |
| `0xD440` | `_device_pool_cleanup_source` | ptr | `lazyInitialize` |
| `0xD44C`–`0xD460` | `_fenceAllocatedCount` / `_fenceMaximumCount` / `_fenceBitmapSearchStart` / `_fenceBitmapCount` / `_fenceAllocationBitmap` | — | 运行期 |
| `0xD468` | `_bufferClass` | Class | 运行期 |
| `0xD470` | `_registryID` | u64 | `IORegistryEntryGetRegistryEntryID` |
| `0xD478` | `_location` / `0xD480` `_locationNumber` / `0xD488` `_maxTransferRate` | — | `updateGPUSelectionProperties` |
| `0xD490` | `_deviceWrapper` | ptr | — |

**实现约束**：子类绝不能假定 `MTLIOAccelDevice` 的 `instanceSize`，它超过 54 KB 且跨版本会变。AMD 的做法是通过导入 `_OBJC_IVAR_$_MTLIOAccelDevice._deviceRef` 符号间接访问（`S-AMD` RVA `0x2338A` 内可见），本项目应照此，或只用 `-deviceRef` / `-sharedRef` getter。`KNOWN`

### 4.4 `_configBits` bit 12 的语义

`KNOWN`：bit 12 置位 ⇒ `_videoRam` 与 `_textureRam` 被清零，`_sharedMemorySize` 被 clamp 到 `_videoRam`。即"统一内存 / 无独立显存"语义。

本项目是纯 CPU 软件渲染器，**应置该位**，并在 selector 0 中令 `videoRam = textureRam = 0`、`sharedMemorySize = 实际可用上限`。`INFERRED`（语义 KNOWN，取值选择未实测）

注意置位后 `_videoRam == 0`，于是 `_sharedMemorySize` 的 clamp 分支不触发（条件是 `_videoRam != 0`），`_sharedMemorySize` 保持 selector 0 给的值。

## 5. 三个 init 方法（本任务核心）

### 5.0 先修正一个前提

这三个方法**不在 `MTLIOAccelDevice` 上，而在 `_MTLDevice` 上**。`KNOWN`

| 方法 | 所属类 | RVA（`S-METAL`） | type encoding |
|---|---|---|---|
| `initLimits` | `_MTLDevice` | `0x257C`（长度 `0x1506`，另有 5 个 cold 块 `0x203BAA`/`0x203BCA`/`0x203BEA`/`0x203C0A`/`0x203C2A`） | `v16@0:8` |
| `initFeatureQueries` | `_MTLDevice` | `0x3AA3` | `v16@0:8` |
| `initGPUFamilySupport` | `_MTLDevice` | `0x3AF7` | `v16@0:8` |

三者都是 `- (void)`、无参数。由 `MTLAddDevice`（`S-METAL` +0x23B0）在协议断言之后按序发出，选择器引用槽为 `S-METAL` +0x35E9DEB0 / +0x35E9DEB8 / +0x35E9DEC0。

### 5.1 共同结论：零 IOKit 依赖

`KNOWN`。对 `0x257C`、`0x3AA3`、`0x3AF7` 以及 `-[_MTLDeviceFeatureQueries initWithDevice:]`（`0x3BF5`）逐一枚举全部跨函数调用目标：

| 函数 | 外部被调用者全集 |
|---|---|
| `initLimits` | 仅自身 5 个 cold 块（断言失败处理） |
| `initFeatureQueries` | `objc_alloc` |
| `initGPUFamilySupport` | `os_unfair_lock_lock` / `os_unfair_lock_unlock` / `getSupportedFamilies(MTLDeviceFeatureProfile)` / `operator delete` |
| `_MTLDeviceFeatureQueries initWithDevice:` | `objc_msgSendSuper2` |

**没有 `IOConnectCall*`、没有 `IOAccel*`、没有 `IORegistryEntry*`、没有 `IOSurface*`。** 对比：同一镜像内 `initWithAcceleratorPort:` 的调用集合里这些符号清晰可见，说明命名导入在本 IDB 中是可解析的，上表的"空"是真的空，不是解析缺失。

所有数据都来自 `objc_msgSend(self, ...)` 加纯计算。

### 5.2 `initLimits`

`KNOWN`。全部 `self` 消息如下，没有第四个：

| selref（`S-METAL` RVA） | 选择器 | 判定依据 | 用途 |
|---|---|---|---|
| `0x35E9D3E0` | `featureProfile` | 同一 selref 的结果被传入 `getSupportedFamilies(MTLDeviceFeatureProfile)`（`S-METAL` +0x11362C，C++ mangled 名含参数类型）；另被 `MTLCompiler compileFunctionRequestInternal:...`、`_MTLGetMTLCompilerLLVMVersionForDevice`、`_MTLDeviceFeatureQueries initWithDevice:` 使用 | 驱动整张 limits 表 |
| `0x35E9B808` | `argumentBuffersSupport` | 同一 selref 被 `deviceSupportsArgumentBuffersTier2`（`S-METAL` +…，C++ mangled）与 `-[_MTLDeviceFeatureQueries familySupportsArgumentBuffersTier2]` 使用；返回值与 0、1 比较 | 门控 `maxIndirect*` |
| `0x35E9D750` | `maxBufferLength` | 结果直接赋给 `_limits.maxBufferLength`；同一 selref 被 `-[_MTLIOScratchBufferAllocator newScratchBufferWithMinimumSize:]` 使用 | `_limits.maxBufferLength` |

结构是一长串 `if (profile == K) acc += V;` 的无分支化累加，`featureProfile` 的取值在反编译中可见 `0`、`1`、`7`、`8`、`9`、`10`、`12`、`10000`、`10001`、`10002`。

写入 `_limits` 的字段（节选，全部可见于 `S-METAL` +0x257C 反编译）：`maxFramebufferStorageBits`、`linearTextureArrayAlignmentBytes/Slice`、`maxTileBuffers/Textures/Samplers/InlineDataSize`、`minTilePixels`、`maxColorAttachments`、`maxVertexAttributes/Buffers/Textures/Samplers/InlineDataSize`、`maxInterpolants`、`maxFragment*`、`maxCompute*`、`maxTotalComputeThreadsPerThreadgroup`、`maxComputeThreadgroupMemory`、`maxLineWidth`、`maxVisibilityQueryOffset`、`minConstantBufferAlignmentBytes`、`minBufferNoCopyAlignmentBytes`、`maxTextureWidth1D/2D/3D`、`maxTextureHeight2D/3D`、`maxTextureDepth3D`、`maxTextureDimensionCube`、`maxTextureLayers`、`linearTextureAlignmentBytes`、`iosurfaceTextureAlignmentBytes`、`iosurfaceReadOnlyTextureAlignmentBytes`、`deviceLinearTextureAlignmentBytes`、`maxFunctionConstantIndices`、`maxComputeThreadgroupMemoryAlignmentBytes`、`maxInterpolatedComponents`、`maxTessellationFactor`、`maxIndirectBuffers/Textures/Samplers`、`maxIndirectSamplersPerDevice`、`maxFenceInstances`、`maxViewportCount`、`maxCustomSamplePositions`、`maxVertexAmplificationFactor/Count`、`maxTextureBufferWidth`、`maxComputeAttributes`、`maxIOCommandsInFlight`、`maxPredicatedNestingDepth`、`maxAccelerationStructureLevels`、`maxConstantBufferArguments`、`maxBufferLength`。

#### 5.2.1 硬断言：哪些字段为 0 会被判死

`KNOWN`。5 个 cold 块各自引用一条断言字符串，调用 `MTLReleaseAssertionFailure`（**release 版也生效**，不是 `NSAssert`）：

| cold 块 RVA | 断言 |
|---|---|
| `0x203C2A` | `_limits.maxColorAttachments > 0` |
| `0x203C0A` | `_limits.maxIndirectBuffers > 0` |
| `0x203BEA` | `_limits.maxIndirectTextures > 0` |
| `0x203BCA` | `_limits.maxIndirectSamplers > 0` |
| `0x203BAA` | `_limits.maxIndirectSamplersPerDevice > 0` |

这五个字段全部由 `featureProfile` 与 `argumentBuffersSupport` 推导。`maxIndirect*` 四项的代码形状是：

```
if ([self argumentBuffersSupport] != 0) {         // 非 Tier1
    if ([self argumentBuffersSupport] != 1)       // 也非 Tier2
        _limits.maxIndirectBuffers = 0;           // → 断言失败
    else
        ... 按 featureProfile 累加 Tier2 取值 ...
}
_limits.maxIndirectBuffers = v;
if (v == 0) assertion_failure;
```

**实现约束（这是本节最可操作的一条）**：`argumentBuffersSupport` 必须返回 `MTLArgumentBuffersTier1(0)` 或 `Tier2(1)`，返回其它值直接触发 release 断言、进程终止。`featureProfile` 必须选一个能让上述五项非零的值。`KNOWN`

#### 5.2.2 `featureProfile` 取值

`KNOWN`：

| 驱动 | 实现 | 值 |
|---|---|---|
| `-[GFXAAMD_MtlDevice featureProfile]` | `S-AMD` +0x241E8，方法体 = `return 10002;` | `10002` |
| `-[GFX10_MtlDevice featureProfile]` | `S-AMD` +0x1178C5，方法体 = `return 10002;` | `10002` |
| `-[MTLIGAccelDevice featureProfile]` | `S-INTEL` +0x35AFA，返回一个在 init 期缓存的 ivar | 运行期决定，未查清具体值 |

`_MTLDevice` **没有** `featureProfile` 的实现（`S-METAL` 中无 `-[_MTLDevice featureProfile]` 符号）。它是 `MTLDeviceSPI` 要求、由 plugin 必须提供的方法。`KNOWN`

**本项目起点取 `featureProfile = 10002`**，与 AMD 完全一致，理由是 AMD 是 x86 独显路径上最接近"通用 Metal 3 设备"的实现，且 `initLimits` 对 `10000/10001/10002` 三者给出同一组现代取值。`INFERRED`

### 5.3 `initFeatureQueries`

`S-METAL` +0x3AA3。`KNOWN`，全文如下：

```objc
[self <sel +0x35E9D3D0>];                                  // void，名字未解析
_featureQueries = [[_MTLDeviceFeatureQueries alloc] initWithDevice:self];
[_featureQueries <sel +0x35E9BF20>];                       // 名字未解析
```

`-[_MTLDeviceFeatureQueries initWithDevice:]`（`S-METAL` +0x3BF5）是一个 2445 行的大表构造器：对 `self` 发出约 190 条 `familySupports*` 自查询，再对 device 发出约 40 条查询，把结果连同 CFSTR 特性名（如 `@"Conditional Tile Dispatch"`、`@"Texture Access Patterns"`、`@"Device scoped memory coherency for buffers and textures"`）写进一张步长 24 字节的记录数组。

它向 device 查询的选择器包括 `featureProfile`（+0x35E9D3E0）、`argumentBuffersSupport`（+0x35E9B808）、以及 `supportsFamily:` / `supportsRaytracing` / `areBarycentricCoordsSupported` / `bufferRobustnessSupport` 等公开或 SPI getter 的 selref。**全部是 ObjC 自查询，无一条走内核。** `KNOWN`

`_MTLDeviceFeatureQueries <- MTLDeviceFeatureQueries <- NSObject`。`KNOWN`

**实现约束**：没有任何硬断言。真正的要求是设备必须老实回答 `MTLDeviceSPI` 的全部能力 getter —— 清单与精确 encoding 由 `21-OBJC-OBJECT-FAMILY.md` 负责。本分册只负责声明：**此处不需要内核数据**。

### 5.4 `initGPUFamilySupport`

`S-METAL` +0x3AF7。`KNOWN`，全文如下：

```objc
os_unfair_lock_lock(&_gpuFamiliyInitLock);
MTLDeviceFeatureProfile p = [self featureProfile];        // selref +0x35E9D3E0
if (_supportedGPUFamilies.empty()) {
    std::vector<int64_t> v = getSupportedFamilies(p);     // S-METAL +0x11362C
    delete 旧 begin;
    _supportedGPUFamilies = std::move(v);
}
os_unfair_lock_unlock(&_gpuFamiliyInitLock);
```

**唯一输入是 `featureProfile`。** 无断言、无内核调用。被调函数的 C++ mangled 名 `__Z20getSupportedFamilies23MTLDeviceFeatureProfile` 直接证明了入参类型。

`_supportedGPUFamilies` 随后由 `-[_MTLDevice supportsFamily:]`（+0x83D9）与 `-[_MTLDevice supportsFamily:withFamilyArray:count:]`（+0x113D3C）消费。

### 5.5 `supportLazyInitialization` 与 `lazyInitialize`

`KNOWN`。

| 方法 | RVA（`S-METAL`） | encoding | 实现 |
|---|---|---|---|
| `-[MTLIOAccelDevice supportLazyInitialization]` | `0x12D043` | `c16@0:8` | 方法体 = `return 0;` |
| `-[MTLIOAccelDevice lazyInitialize]` | `0x12CD9A` | `c16@0:8` | 做全部重活，见下 |

`initWithAcceleratorPort:` 里的用法是短路与：

```
if (![self supportLazyInitialization] && ![self lazyInitialize]) → nil
```

基类 `supportLazyInitialization` 返回 NO，于是 `lazyInitialize` 在 `initWithAcceleratorPort:` 内**立即同步执行**，失败即整个设备创建失败。"lazy" 这个名字描述的是子类可选的行为，不是基类的默认行为。

`lazyInitialize` 做的事：

```objc
_sharedRef = IOAccelSharedCreate(_deviceRef);                     // type-6 user client
if (!_sharedRef || IOAccelSharedSetupDirtyRing(_sharedRef) != 0) return NO;   // ← 失败点
_storageCreateParams.akResourceListPool        = [[MTLResourceListPool alloc] initWithResourceListCapacity:1024];
_storageCreateParams.akPrivateResourceListPool = [[MTLResourceListPool alloc] initWithResourceListCapacity:256];
_storageCreateParams.kernelCommandShmemPool =
    [[MTLIOAccelDeviceShmemPool alloc] initWithDevice:self
                                        resourceClass:[MTLIOAccelDeviceShmem class]
                                            shmemSize:[self initialKernelCommandShmemSize]
                                              options:0];
_storageCreateParams.segmentListShmemPool =
    [[MTLIOAccelDeviceShmemPool alloc] initWithDevice:self
                                        resourceClass:[MTLIOAccelDeviceShmem class]
                                            shmemSize:[self initialSegmentListShmemSize]
                                              options:0];
_segmentByteThreshold = 0;
_device_dispatch_queue = dispatch_queue_create("com.Metal.DeviceDispatchQueue", NULL);
_commandBufferStoragePool = MTLIOAccelCommandBufferStoragePoolCreate(self);
if (!_commandBufferStoragePool) return NO;                        // ← 失败点
_device_pool_cleanup_queue  = dispatch_queue_create("com.Metal.DeviceCleaupQueue", NULL);   // 拼写是 Apple 原样
_device_pool_cleanup_source = dispatch_source_create(DISPATCH_SOURCE_TYPE_DATA_OR, ...);
dispatch_source_set_event_handler(...);
return YES;
```

#### 5.5.1 这是本项目最有价值的一个开关

`INFERRED`（机制 `KNOWN`，取舍未实测）

把 `supportLazyInitialization` 覆写为返回 `YES`，`initWithAcceleratorPort:` 就**完全跳过** `lazyInitialize`，于是以下内核面全部变成不必要：

- type-6 user client（`IOAccelSharedCreate` 的 `IOServiceOpen(.., 6, ..)`）
- shared selector `9`（16 字节）
- shared selector `0xA`（`IOAccelSharedSetupDirtyRing`，24 字节，**原本是硬性必须成功**）
- shared selector `7` / `8`（`IOAccelSharedCreateDeviceShmem` / `Destroy`）
- `MTLIOAccelDeviceShmemPool` 与 `MTLIOAccelCommandBufferStoragePool` 两套 shmem 池

代价是 `_sharedRef` 保持 `NULL`、`_storageCreateParams` 与 `_commandBufferStoragePool` 保持零。任何继承来的、会用到它们的路径都会空指针。清单见第 8 节 —— 全部落在 resource 创建与 command buffer 提交上，而这些**本项目无论如何都要覆写**（它们要接 Vulkan）。

AMD 与 Intel 都**没有**覆写这两个方法（第 6.2 节的覆写全集可证），因为它们真有 GPU。本项目没有，所以这是一条它们不会走、但对我们成立的捷径。

**排期建议**：第一版先按基类走（实现 type-6 与 selector `9`/`0xA`，让 `lazyInitialize` 真正成功），因为那只是再加两个返回固定结构的 selector，代价很小，而换来的是"继承路径不留空指针地雷"。把 `supportLazyInitialization = YES` 留作 fallback。

## 6. 厂商覆写全集对照

### 6.1 为什么看这个

AMD 与 Intel 的 device 类是"继承 `MTLIOAccelDevice` 之后到底要补多少"的现成答案。它们覆写了什么，就是基类没给够的；它们没覆写什么，就是基类给够了的。

### 6.2 覆写与未覆写

`KNOWN`：枚举 `S-AMD` 中 `-[GFXAAMD_MtlDevice *]` 与 `-[GFX10_MtlDevice *]` 的全部符号（181 个去重选择器），`S-INTEL` 中 `-[MTLIGAccelDevice *]`（175 个）。

**两家都覆写**（init 链相关）：

| 选择器 | AMD | Intel | 说明 |
|---|---|---|---|
| `initWithAcceleratorPort:` | ✓ `S-AMD` +0x2338A | ✓ `S-INTEL` +0x2E87D | 调 super 后做厂商初始化 |
| `featureProfile` | ✓ | ✓ | **必须**，基类无实现 |
| `maxBufferLength` | ✓ `S-AMD` +0x2474D | — | AMD 返回 init 期缓存的 ivar |
| `name` / `vendorName` / `productName` / `familyName` / `architecture` | ✓ | ✓ | — |
| `deviceRef` | ✓ | — | AMD 缓存一份 |
| `initialKernelCommandShmemSize` / `initialSegmentListShmemSize` | — | ✓ | 调整 `lazyInitialize` 的 shmem 池大小 |
| `newFence` | — | ✓ | — |

**两家都不覆写**（这是本节的关键结论）：

`initLimits`、`initFeatureQueries`、`initGPUFamilySupport`、`supportLazyInitialization`、`lazyInitialize`、`registryID`、`acceleratorPort`、`_setAcceleratorService:`、`sharedRef`、`recommendedMaxWorkingSetSize`、`hasUnifiedMemory`、`isLowPower`、`isHeadless`、`isRemovable`、`isSlotted`、`isBuiltIn`、`location`、`dedicatedMemorySize`、`sharedMemorySize`、`updateGPUSelectionProperties`、`currentAllocatedSize`。

即：**init 链三件套与 lazy-init 对偶是纯继承的，一行不改。** 系统属性类 getter 也全部由基类从 selector 0 的数据与 IORegistry 属性推导。

**覆写的主体是工厂与能力查询**，不是初始化。AMD 覆写集的分布：

| 类别 | 数量级 | 例 |
|---|---|---|
| 资源与对象工厂 `new*` | ~40 | `newBufferWithLength:options:`、`newTextureWithDescriptor:`、`newCommandQueue`、`newHeapWithDescriptor:`、`newSamplerStateWithDescriptor:`、`newDepthStencilStateWithDescriptor:`、`newIndirectCommandBufferWithDescriptor:maxCommandCount:options:`、`newArgumentEncoderWithLayout:`、`newCounterSampleBufferWithDescriptor:error:`、`newAccelerationStructureWithSize:` |
| 编译器接口 | ~30 | `get*FunctionId:compilerOptions:compilerOptionsSize:`、`*FunctionKeyWithRenderPipelineDescriptor:...`、`*VariantWithCompilerOutput:pipelineStatisticsOutput:`、`free*FunctionKey:*`、`targetDeviceArchitecture`、`llvmVersion`、`compiler` |
| 能力查询 | ~50 | `supportsRaytracing`、`supportsMeshShaders`、`supportsFunctionPointers`、`supportsInt64`、`isDepth24Stencil8PixelFormatSupported`、`isFloat32FilteringSupported`、`singleFPConfig`/`halfFPConfig`/`doubleFPConfig`、`maxThreadsPerThreadgroup`、`maxThreadgroupMemoryLength` |
| 对齐与尺寸计算 | ~12 | `heapBufferSizeAndAlignWithLength:options:`、`heapTextureSizeAndAlignWithDescriptor:`、`minLinearTextureAlignmentForPixelFormat:`、`sparseTileSizeWithTextureType:pixelFormat:sampleCount:`、`tileSizeWithTextureType:pixelFormat:sampleCount:` |
| 厂商私有 | ~25 | `amdMtl_*`、`queryInfinityCacheSetting`、`setAMDMtlClk:`、`readSPMTrace` |
| MPS 内核工厂 | ~10 | `newCNNConvolutionWithDescriptor:convolutionData:`、`newMatrixMultiplicationWithTransposeLeft:...` |

**结论**：本项目 Device 类的工作量落在工厂方法、能力查询、对齐计算、编译器接口四块，和"让基类 init 走通"几乎无关。具体清单由 `21-OBJC-OBJECT-FAMILY.md` 与 `60-CAPABILITY-MATRIX.md` 负责；本分册只定边界。`KNOWN`

### 6.3 AMD `initWithAcceleratorPort:` 的形状

`KNOWN`（`S-AMD` +0x2338A，160 行）。可作为本项目的实现模板：

```objc
self = [super initWithAcceleratorPort:port];
if (!self) return nil;
io_connect_t c = IOAccelDeviceGetConnect(self->_deviceRef);
if (IOConnectCallMethod(c, 0x100 /* 厂商私有 selector */, ...) == 0) {
    amdMtldeviceRef = *(IOAccelDeviceRef *)((char *)self + OBJC_IVAR_$_MTLIOAccelDevice._deviceRef);
    IOAccelDeviceGetMaxResourceSize(amdMtldeviceRef, &maxBufferLength);
    ... 解析 0x100 返回的硬件信息，建 register registry 等 ...
    return self;
}
return nil;
```

两点可直接照搬：

1. **厂商私有 selector 从 `0x100` 起**。Apple 自己占 `0`..`0x14`（第 7.4 节），GL drawable 另占 `0x100`..`0x105`。本项目若需要私有通道，用 `0x200` 以上更安全。`INFERRED`
2. 通过导入的 ivar 偏移符号访问基类 ivar，不硬编码偏移。

## 7. 内核侧契约

### 7.1 user client 类型全集

`KNOWN`（`S-IOACCEL` 全部 `IOServiceOpen` 调用点）：

| type | 创建函数 | RVA（`S-IOACCEL`） | 本项目是否必须 |
|---|---|---|---|
| `5` | `IOAccelDeviceCreateWithAPIProperty` | `0xF60` | **必须** |
| `6` | `IOAccelSharedCreate` | `0x1431` | 必须，除非覆写 `supportLazyInitialization`（第 5.5.1 节） |
| `8` | `IOAccelCommandQueueCreateWithQoS` | `0x23C4` | 不必须（覆写 `newCommandQueue`） |
| `9` | `IOAccelGLDrawableCreate` | `0x4E50` | 不必须（OpenGL 路径） |
| `4` | `IOAccelDisplayPipeCreate` | `0x5930` | 不必须（见分册 11） |
| 调用方指定 | `IOAccelContextCreate` | `0x1554` | 不必须（OpenGL 路径） |

`MANIFEST.md` 记的 "UserClient type 5 / Required selectors 2, 0 / Optional 7, 9" **全部正确**。本节把它细化到字段级。

### 7.2 type-5 创建序列

`KNOWN`，`IOAccelDeviceCreateWithAPIProperty(io_service_t svc, const char *api)`，`S-IOACCEL` +0xF60：

| 步 | 动作 | 失败后果 |
|---|---|---|
| 1 | `IOServiceOpen(svc, mach_task_self(), 5, &connect)` | 返回 NULL（并打 `OS_LOG_TYPE_FAULT`） |
| 2 | 若 `api != NULL`：`strncpy(buf, api, 16)`；`IOConnectCallStructMethod(connect, 9, buf, 16, NULL, NULL)` | **返回值被丢弃** → selector 9 可不实现 |
| 3 | `_CFRuntimeCreateInstance(alloc, kIOAccelDeviceID, 672, 0)` | 返回 NULL |
| 4 | `outCnt = 600; IOConnectCallStructMethod(connect, 2, NULL, 0, buf600, &outCnt)` | **≠0 → CFRelease + 返回 NULL** |
| 5 | 解析 selector 2 的结构，见 7.3 | — |
| 6 | `outCnt = 64; IOConnectCallStructMethod(connect, 0, NULL, 0, obj+624, &outCnt)` | **≠0 → CFRelease + 返回 NULL** |
| 7 | `outCnt = 24; IOConnectCallStructMethod(connect, 7, NULL, 0, buf24, &outCnt)` | 失败被容忍，相关字段留 0 |
| 8 | commpage 初始化，清零 obj+600..620 | — |

Metal 侧把返回 NULL 直接翻成 `initWithAcceleratorPort:` 返回 nil（第 4.2 节失败点 1）。

**所以 type-5 只有 selector `0` 与 `2` 是必须的。** `KNOWN`

### 7.3 selector 2：600 字节（`0x258`）

`KNOWN`，字段偏移由反编译的栈布局精确导出（`__dst` 在 `rbp-0x280`，`v27[128]` 在 `rbp-0x228`，差 `0x58`）。

| 偏移 | 大小 | 去向 | 读取者与语义 |
|---|---|---|---|
| `+0x00` | 8 | `dev+32` | **计数器区基地址（客户端可读的用户态地址）**。当 `+0x14` 的 count > 0 时会被解引用 |
| `+0x08` | 4 | `dev+52` | `IOAccelResourceGetClientSharedPrivate`（`S-IOACCEL` +0x3975）：非 0 则 resource 的 clientShared 私有区 = `resource[9] + 264` |
| `+0x0C` | 4 | `dev+56` | 同上，第二块：非 0 则 `resource[10] + 32` |
| `+0x10` | 4 | `dev+60` | **厂商 per-resource 私有数据字节数**。`IOAccelResourceCreate` 用它算输出结构大小（`size + 88`）；`IOAccelResourceGetPrivate`（+0x4B38）非 0 才返回 `resource+128` |
| `+0x14` | 4 | `dev+48` | **计数器通道数 count**，取值 0..128 |
| `+0x18`..`+0x57` | 64 | — | 未被读取 |
| `+0x58`..`+0x257` | 512 | — | `uint32 offsets[128]`，仅前 `count` 项被用；`ptr[i] = base + offsets[i]` |

解析逻辑（`S-IOACCEL` +0xF60）：

```c
dev[32] = buf[0x00];  dev[48] = count = buf[0x14];
if (count < 2) {
    dev[40] = &dev[32];
    if (count != 1) goto done;        // count == 0：下面的解引用整段跳过
    n = 1;
} else {
    p = malloc(8 * count);
    for (i = 0; i < count; i++) p[i] = buf[0x00] + buf[0x58 + 4*i];
    dev[40] = p;  n = count;
}
for (j = 0; j < n; j++) dev[68 + 4*j] = *(uint32 *)(dev[40])[j];   // ← 解引用
done:
dev[52] = buf[0x08]; dev[56] = buf[0x0C]; dev[60] = buf[0x10];
dev[24] = IOAccelDeviceTestEventFast;
```

#### 7.3.1 count = 0 的捷径

`KNOWN`：`count == 0` 时 `goto done` 跳过整个解引用循环。于是 **selector 2 可以返回 600 字节全零** 而创建仍然成功。

唯一的后续风险是 `IOAccelDeviceTestEventFast`（`S-IOACCEL` +0x2FE3），它会解引用 `dev[40][index]`；但该函数只从 `IOAccelResourceTestEvent` / `-[MTLIOAccelResource isComplete]` / `isWriteComplete` 路径到达，而这些路径依赖 `IOAccelResourceCreate` 产生的 resource —— 本项目覆写全部 resource 工厂（第 8 节），因此不可达。`INFERRED`

**实现建议**：selector 2 返回 600 字节、`count = 0`、`+0x08`/`+0x0C`/`+0x10` 全 0。必须返回满 600 字节（调用方不检查 `outputStructCnt`，短返回会让后续字段读到未初始化的栈内容）。`INFERRED`

如果后续决定让 `IOAccelResourceCreate` 真正走通，则需要一个映射进客户端的页，count 设为实际通道数，`offsets[i]` 指向各通道的 `uint32` 进度计数器。

### 7.4 selector 0：64 字节（`0x40`）—— 全部字段都被读

`KNOWN`。写入 `obj+624`，而对象总长 = `16 + 672 = 688`，即这 64 字节正好是对象末尾。四个 getter 把它完整读干：

| 偏移 | 大小 | getter（`S-IOACCEL`） | → `MTLIOAccelDevice` ivar |
|---|---|---|---|
| `+0x00` | u32 | `IOAccelDeviceGetConfig64` 第 2 参（+0x1264） | `_configBits` `0x320` |
| `+0x04` | u32 | 同上第 3 参 | `_deviceBits` `0x324` |
| `+0x08` | u64 | 同上第 4 参 | `_textureRam` `0x328` |
| `+0x10` | u64 | 同上第 5 参 | `_videoRam` `0x330` |
| `+0x18` | u32 | 同上第 6 参 | `_accelID` `0x340` |
| `+0x1C` | u32 | — | 填充 |
| `+0x20` | u64 | `IOAccelDeviceGetSharedMemorySize`（+0x1F93） | `_sharedMemorySize` `0x338` |
| `+0x28` | u64 | `IOAccelDeviceGetMaxResourceSize`（+0x31D9） | 经 `-[MTLIOAccelDevice maxBufferLength]`（`S-METAL` +0x2AD26）→ `_limits.maxBufferLength` |
| `+0x30` | u64 | `IOAccelDeviceGetPeerInfo` 第 2 参（+0x1F73） | `_peerGroupID` `0x350` |
| `+0x38` | u32 | 同上第 3 参 | `_peerIndex` `0x358` |
| `+0x3C` | u32 | 同上第 4 参 | `_peerCount` `0x35C` |

C 结构（本项目 kext 照此返回）：

```c
struct IOAccelDeviceConfigOut {   // selector 0，64 字节
    uint32_t configBits;          // bit 12 置位 = 统一内存，见 4.4
    uint32_t deviceBits;
    uint64_t textureRam;          // 统一内存时置 0
    uint64_t videoRam;            // 统一内存时置 0
    uint32_t accelID;
    uint32_t _pad;
    uint64_t sharedMemorySize;
    uint64_t maxResourceSize;     // → maxBufferLength，必须 > 0
    uint64_t peerGroupID;         // 单卡置 0，否则基类会建 peerConnections 字典
    uint32_t peerIndex;           // 置 0
    uint32_t peerCount;           // 置 0
};
```

`IOAccelDeviceGetConfig`（32 位旧接口，+0x3226）读的是同一批字节的低 32 位，与 Config64 一致，无需额外数据。`KNOWN`

### 7.5 type-5 的其余 selector

`KNOWN`，`S-IOACCEL` 全量 `IOConnectCall*` 调用点扫描：

| selector | 包装函数 | 大小 | 本项目 |
|---|---|---|---|
| `0` | （见 7.4） | out 64 | **必须** |
| `1` | `IOAccelDeviceGetName`（+0x354E） | out 64，C 字符串 | 建议实现；否则覆写 `-name` |
| `2` | （见 7.3） | out 600 | **必须** |
| `3` | `IOAccelDeviceGetSurfaceInfo`（+0x3A37） | — | 不必须，`getSurfaceMode:width:height:forId:` 才用 |
| `4` | `IOAccelDeviceSetFramebufferStereo`（+0x3C51） | scalar | 不必须 |
| `6` | `IOAccelDeviceGetCurrentTraceFilter`（+0x3D2E） | — | 不必须 |
| `7` | `IOAccelDeviceCreateWithAPIProperty` 步 7 | out 24 | 可选。`{u64 → dev+584 = globalTraceObjectID, u64 → dev+592（仅当第三个 u32 ≥ 4）, u32 版本}` |
| `8` | `IOAccelDeviceGetNextGlobalTraceID`（+0x2962） | — | 不必须（trace） |
| `9` | `IOAccelDeviceCreateWithAPIProperty` 步 2 | in 16 | 可选，返回值被丢弃。入参是 `"Metal"` 的 16 字节定长拷贝 |

### 7.6 type-6（shared）selector

`KNOWN`。仅在不覆写 `supportLazyInitialization` 时相关。

| selector | 包装函数 | 大小 | 必须性 |
|---|---|---|---|
| `9` | `IOAccelSharedCreate`（+0x1431） | out 16 | 失败被容忍（字段留 0） |
| `0xA` | `IOAccelSharedSetupDirtyRing`（+0x1F11） | out 24 | **必须成功**，否则 `lazyInitialize` 返回 NO → 设备创建失败 |
| `0xB` | `IOAccelSharedFlushDirtyRing` / `WriteDirtyResourceCommand` | scalar | 运行期 |
| `0xC` | `IOAccelSharedAllocateFenceMemory` | — | 运行期 |
| `0xD`/`0xE` | `IOAccelMTLEvent` 创建/销毁 | — | 运行期 |
| `0xF` | `IOAccelSharedGetMemoryData` | — | 运行期 |
| `0x10` | `IOAccelSharedDisconnectPeer` | scalar | 不必须 |
| `0x12` | `IOAccelSurfaceSignalEvent` / `IOAccelResourceGetPhysicalOffset` | — | 不必须 |
| `0x13` | `IOAccelSharedGetAllocatedSize` | — | `currentAllocatedSize` 才用 |
| `0x14` | `IOAccelResourceSetOwnerIdentity` | — | 不必须 |
| `0` | `IOAccelResourceCreate`（+0x1FE7） | in 变长，out `dev[60] + 88` | 覆写 resource 工厂后不必须 |

selector `0xA` 的 24 字节结构：`{u32 @+0, u32 count @+4, u64 @+8, u64 @+0x10}`。`count - 1` 被存为环形掩码（`shared+80`），**因此 count 必须是 2 的幂**。`KNOWN`

`IOAccelCommandQueueCreateWithQoS` 额外做 `IOConnectAddClient(cmdQueueConnect, sharedConnect)`，即 type-8 client 必须能接受 type-6 client 作为关联客户端。`KNOWN`，但覆写 `newCommandQueue` 后不必须。

## 8. 必须覆写的方法集

### 8.1 判定方法

`KNOWN`。在 `S-METAL` 中枚举全部名字匹配 `IOAccel*` / `IOConnectCall*` / `IOServiceOpen` / `IODataQueue*` / `IOSurface*` / `IORegistryEntry*` 的导入符号（77 个），再反向求代码交叉引用，得到 98 个调用者函数，按类归组。

**判定标准分两档**：

- **A 档（必须覆写）**：调用了真正的 user-client 方法或要求存在真实 GPU 资源。
- **B 档（可以继承）**：只调用 trace API（`IOAccelDeviceTraceEvent`、`IOAccelDeviceTraceObjectLabel`、`IOAccelDeviceGetNextGlobalTraceID`、`IOAccelDeviceGetGlobalTraceObjectID`）。这些在 trace 关闭时是空操作，且只需要 `_globalTraceObjectID` 这个标量，基类已从 selector 7 或 0 拿到。

### 8.2 device（`MTLIOAccelDevice`）

| 方法 | RVA（`S-METAL`） | IOKit 调用 | 档 |
|---|---|---|---|
| `initWithAcceleratorPort:` | `0x17CF` | `IOAccelDeviceCreateWithAPIProperty`、`GetConfig64`、`GetPeerInfo`、`GetSharedMemorySize`、`GetGlobalTraceObjectID`、`IORegistryEntryGetRegistryEntryID` | **A**（调 super 后扩展，不替换） |
| `lazyInitialize` | `0x12CD9A` | `IOAccelSharedCreate`、`IOAccelSharedSetupDirtyRing` | **A**（或用 `supportLazyInitialization` 绕开） |
| `maxBufferLength` | `0x2AD26` | `IOAccelDeviceGetMaxResourceSize` | B（selector 0 已给值；AMD 仍覆写以缓存） |
| `currentAllocatedSize` | — | `IOAccelSharedGetAllocatedSize` | **A** 若 `_sharedRef` 为 NULL |
| `getSurfaceMode:width:height:forId:` | `0x12D1AB` | `IOAccelDeviceGetSurfaceInfo` | **A** |
| `retainPeerConnection:` / `releasePeerConnection:` | — | `IOAccelSharedConnectPeer` / `Disconnect` | B（`peerCount = 0` 时不可达） |
| `isBuiltIn` / `isSlotted` / `isRemovable` / `getExternalGPUProperties:transferRate:` / `getSlottedGPUProperties:transferRate:` | `0x12D210` / `0x1FDA` / `0x1FB7` / `0x12D2E6` / `0x2023` | `IORegistryEntrySearchCFProperty`、`IORegistryEntryCopyFromPath`、`IORegistryEntryCreateIterator` | B（只读 IORegistry 属性；属性缺失即返回默认） |

### 8.3 command queue

| 类/方法 | IOKit 调用 | 档 |
|---|---|---|
| `-[MTLIOAccelCommandQueue initWithDevice:descriptor:]` | `IOAccelCommandQueueCreateWithQoS`（type-8 open）、`SetDispatchQueue`、`GetGlobalTraceObjectID` | **A** |
| `-[MTLIOAccelCommandQueue submitCommandBuffers:count:]` | `IOAccelCommandQueueSubmitCommandBuffers` | **A** |
| `-[MTLIOAccelCommandQueue _setGPUPriority:backgroundPriority:]` | `IOAccelCommandQueueSetPriorityAndBackground` | **A** |
| `-[MTLIOAccelCommandQueue setCompletionQueue:]` | `IOAccelCommandQueueSetDispatchQueue` | **A** |
| `-[MTLIOAccelCommandQueue dealloc]` | `IOAccelCommandQueueRelease` | **A** |
| `-[MTLIOAccelCommandQueue setLabel:]` | trace only | B |

整个 queue 类只有 6 个方法碰 IOKit，其中 5 个是 A 档。**结论：覆写 `-[Device newCommandQueue*]` 返回自建 queue 类，比子类化 `MTLIOAccelCommandQueue` 更省。AMD 正是这么做的（它不子类化 queue，但覆写 `newCommandQueue`）。** 本项目的 queue 可继承 `_MTLCommandQueue` 抽象层。`INFERRED`

### 8.4 command buffer 与 encoder —— 全部 B 档

| 类 | 碰 IOKit 的方法 | 全部调用 |
|---|---|---|
| `MTLIOAccelCommandBuffer` | `initWithQueue:retainedReferences:synchronousDebugMode:`、`commit`、`setCurrentCommandEncoder:`、`pushDebugGroup:`、`popDebugGroup`、`setLabel:` | 仅 `IOAccelDeviceTraceEvent` / `TraceObjectLabel` / `GetNextGlobalTraceID` |
| `MTLIOAccelCommandEncoder` | `initWithCommandBuffer:`、`endEncoding`、`globalTraceObjectID`、`pushDebugGroup:`、`popDebugGroup`、`setLabel:` | 同上 |
| `MTLIOAccelParallelRenderCommandEncoder` | `initWithCommandBuffer:renderPassDescriptor:`、`endEncoding`、`pushDebugGroup:`、`popDebugGroup`、`setLabel:` | 同上 |
| `MTLIOAccelDebugCommandEncoder` | 1 个方法 | 同上 |
| `MTLIOAccelIOCommandQueue` / `MTLIOAccelIOCommandBuffer` | `setLabel:` | 同上 |
| `_MTLIOAccelMTLEvent` / `_MTLSharedEvent` | `setLabel:` | 同上 |

**这是本分册最有分量的一条**：command buffer 与所有 encoder 的 `MTLIOAccel*` 基类**完全没有 user-client 交互**，只有 trace。它们的真实工作（命令记录）走 `_storageCreateParams` 里的 shmem 池与 `MTLIOAccelCommandBufferStoragePool`，而那是本项目要整体替换的部分 —— 所以仍然要覆写**行为**方法（`setVertexBuffer:offset:atIndex:` 等），但**不是因为 IOKit**，而是因为后端换了。`KNOWN`

### 8.5 resource（buffer / texture）—— A 档

| 方法 | IOKit 调用 |
|---|---|
| `-[MTLIOAccelResource initWithDevice:remoteStorageResource:options:args:argsSize:]` | `IOAccelResourceCreate`、`CreateAllocationIdentifierSet`、`GetClientShared`、`GetDataBytes`、`GetGPUVirtualAddress`、`GetGlobalTraceObjectID`、`GetResidentDataSize` |
| `-[MTLIOAccelResource initWithResource:]` | `IOAccelResourceGetClientShared`、`GetGPUVirtualAddress` |
| `-[MTLIOAccelResource dealloc]` | `IOAccelResourceRelease` |
| `-[MTLIOAccelResource isComplete]` / `isWriteComplete]` | `IOAccelResourceTestEvent` |
| `-[MTLIOAccelResource waitUntilComplete]` | `IOAccelResourceFinishEvent` |
| `-[MTLIOAccelResource setPurgeableState:]` | `IOAccelResourceSetPurgeable`、`IOSurfaceSetPurgeable` |
| `-[MTLIOAccelResource protectionOptions]` | `IOAccelResourceGetProtectionOptions` |
| `-[MTLIOAccelResource setOwnerWithIdentity:]` | `IOAccelResourceSetOwnerIdentity` |
| `-[MTLIOAccelBuffer didModifyRange:]` | `IOAccelResourceDirtyBufferRange` |
| `-[MTLIOAccelBuffer initWithDevice:iosurface:args:argsSize:]` | `IOSurfaceGetAllocSize`、`IOSurfaceGetID` |
| `-[MTLIOAccelTexture initWithDevice:descriptor:iosurface:plane:field:args:argsSize:]` | `IOSurfaceCopyValue`、`GetBaseAddress`、`GetBytesPerElement/Row`、`GetElementHeight`、`GetHeight`、`GetID`、`GetPlaneCount`、`AllowsPixelSizeCasting`、`GetAllocSize` |
| `-[MTLIOAccelTexture initWithDevice:surface:buffer:args:argsSize:returnData:returnDataSize:]` | `IOAccelResourceGetInfo` |
| `_MTLIOAccelCommandBufferStorage*`（C 函数） | `IOAccelResourceListInit/Reset/Destroy` |

resource 层的每一个 `init*` 都真打内核。**全部必须覆写**；或者 resource 类不继承 `MTLIOAccelResource` 而继承 `_MTLResource`。

IOSurface 相关调用是个例外：那些是 IOSurface 框架的公开 API，本项目**可以而且应该**真的用（见 `41-IOSURFACE-USERSPACE.md`）。`INFERRED`

### 8.6 其余

| 类/方法 | IOKit 调用 | 档 |
|---|---|---|
| `-[_MTLDevice newSharedTextureWithDescriptor:]` | `IOSurfaceCreate` | 可继承（真 IOSurface） |
| `-[_MTLDevice _newDescriptorForSharedTexture:]` | `IOSurfaceCopyValue` | 可继承 |
| `MTLSharedTextureHandle createMachPort` / `initWithMachPort:` | `IOSurfaceCreateMachPort` / `LookupFromMachPort` | 可继承 |
| `MTLSharedEventListenerInternal init` / `initWithDispatchQueue:` / `dealloc` / `_notifyEventPort:event:atValue:block:` | `IOSurfaceSharedEvent*` | 可继承（IOSurface 公开 API） |
| `MTLIOAccelGLDrawable`（6 个方法） | `IOAccelGLDrawable*`（type-9） | 不实现；覆写 `-[Device newGLDrawable]` 返回 nil |
| `MTLIOMemoryInfo addDataSource:` / `removeDataSource:` | `IOAccelMemoryInfoRegisterAPICollectionBlock` | 不必须 |
| `MTLIOAccelDeviceShmem initWithDevice:shmemSize:` / `dealloc` | `IOAccelSharedCreateDeviceShmem` / `Destroy`（type-6 selector 7/8） | **A** 若走 `lazyInitialize` |

### 8.7 覆写决策汇总

| 对象类型 | 继承自 | 需覆写的原因 |
|---|---|---|
| Device | `MTLIOAccelDevice` | 工厂方法 + 能力查询；init 链纯继承 |
| CommandQueue | `_MTLCommandQueue` | IOKit（type-8）+ 提交路径 |
| CommandBuffer | `MTLIOAccelCommandBuffer` | 仅后端行为，非 IOKit |
| Encoder（render/compute/blit/parallel/accel-struct/resource-state） | `MTLIOAccelCommandEncoder` 或对应 `MTLIOAccel*` | 仅后端行为，非 IOKit |
| Buffer / Texture / 其它 resource | `_MTLResource` 子树（**不**走 `MTLIOAccelResource`） | 每个 init 都打内核 |
| Heap | `_MTLHeap` | 分配语义自管 |
| Fence / Event | `_MTLFence` / `_MTLSharedEvent` | 可继承大部分 |
| Library / Function / PipelineState / Sampler / DepthStencilState | `_MTL*` 抽象层（本来就没有 IOAccel 版） | 与内核无关 |
| GLDrawable | 不实现 | — |

精确清单与 encoding 交由 `21-OBJC-OBJECT-FAMILY.md`。`INFERRED`

## 9. `_setAcceleratorService:`、`acceleratorPort`、`registryID`

`KNOWN`，三者都是平凡实现，无需覆写：

| 方法 | RVA（`S-METAL`） | encoding | 实现 |
|---|---|---|---|
| `-[MTLIOAccelDevice _setAcceleratorService:]` | `0x238B` | `v24@0:8@16` | `_acceleratorService = objc_retain(svc)`（0x2E0，强引用，非 weak） |
| `-[MTLIOAccelDevice acceleratorPort]` | `0x874C` | `I16@0:8` | `return _acceleratorPort`（0x2D8） |
| `-[MTLIOAccelDevice registryID]` | `0x8644` | `Q16@0:8` | `return _registryID`（0xD470） |
| `-[MTLIOAccelDevice deviceRef]` | `0x2232` | — | `return _deviceRef`（0x2C8） |
| `-[MTLIOAccelDevice sharedRef]` | `0x8CD3` | — | `return _sharedRef`（0x2D0） |

来源：

- `_acceleratorPort`：`initWithAcceleratorPort:` 的入参，并 `IOObjectRetain`。
- `_registryID`：`IORegistryEntryGetRegistryEntryID(port, &_registryID)`，**不是** selector 返回的，所以 kext 无需提供。
- `_acceleratorService`：由 `-[MTLIOAccelService initWithAcceleratorPort:deviceClass:]`（`S-METAL` +0x1D9395）在 `MTLAddDevice` 之前调用 `_setAcceleratorService:` 注入。device 对 service 持强引用，service 对 device 持 weak 引用（`objc_storeWeak`）—— 避免环。

同一条 `registryID` 路径上还有 `-[_MTLDevice acceleratorPort]`（`S-METAL` +0x1197F5）与 `-[MTLIOAccelService acceleratorPort]`（+0x17B8）/ `-[MTLIOAccelServiceDescriptor acceleratorPort]`（+0x1D8C4E），都是 ivar 直读。

**实现结论**：`registryID` 只要 kext 的 service 正常注册进 IORegistry 就自动有值，无需任何额外工作。`KNOWN`

## 10. 地址核对

### 10.1 第 8 问：六个 RVA

`KNOWN`。方法：在 `S-METAL` 中按名字查符号地址，再反查给定 RVA 处的符号与所属函数，双向一致。

| 既有文档 | 核对结果 |
|---|---|
| `_MTLCopyAllDevices +0x1632` | **正确** |
| `_MTLCreateSystemDefaultDevice +0x17A91` | **正确** |
| `_MTLAddDevice +0x23B0` | **正确** |
| `_MTLRegisterDevices +0x1D980D` | **正确** |
| `_getMetalPluginClassForService +0x1D89FB` | **正确** |
| `-[MTLIOAccelDevice initWithAcceleratorPort:] +0x17CF` | **正确** |

六个全对，无需修正。既有文档这部分可信。

附带核对：`MANIFEST.md` 的 `IOAccelDeviceCreateWithAPIProperty = 0x7FF80B170F60` 也**正确**（`S-IOACCEL` base `0x7FF80B170000` + RVA `0xF60`）。注意它低于 `S-METAL` 的 base，属于 IOAccelerator 镜像，不要误当作 Metal 的 RVA。

### 10.2 第 9 问：type encoding

`KNOWN`。`-[MTLIOAccelDevice initWithAcceleratorPort:]` 的 type encoding 实读为 **`@20@0:8I16`** —— 与既有文档一致。

| 项 | 值 |
|---|---|
| 实读字符串 | `@20@0:8I16` |
| method record 位置 | `S-METAL` +0x217F1C（`__objc_methlist`） |
| types 字符串位置 | `S-METAL` +0x2D4A2E（`__objc_methtype`） |
| imp | `S-METAL` +0x17CF |

同批核对的其它 encoding（均 `KNOWN`）：

| 选择器 | encoding | types RVA |
|---|---|---|
| `_setAcceleratorService:` | `v24@0:8@16` | `+0x2D2991` |
| `registryID` | `Q16@0:8` | `+0x2D2A12` |
| `acceleratorPort` | `I16@0:8` | `+0x2D2BDD` |
| `supportLazyInitialization` | `c16@0:8` | `+0x2D2A68` |
| `lazyInitialize` | `c16@0:8` | `+0x2D2A68` |
| `initLimits` / `initFeatureQueries` / `initGPUFamilySupport` | `v16@0:8` | `+0x2D29E1` |

`__objc_methlist` 在本样本中是 relative method list：条目 12 字节、三个 `int32` 自相对偏移（name / types / imp）。types 偏移指向镜像内的 `__objc_methtype`，可直接读；**name 偏移指向镜像外**（见 11.1）。

### 10.3 既有文档需要修正的地方

| 位置 | 问题 | 修正 |
|---|---|---|
| `00-OVERVIEW.md` 4.4 | 类名写作 `_MTLIOAccelDevice` | 应为 `MTLIOAccelDevice`（无前导下划线）；`_MTLDevice` 是其父类 |
| `00-OVERVIEW.md` 4.4 | 称三个 init 方法属于该基类 | 它们属于 `_MTLDevice` |
| `00-OVERVIEW.md` 4.4 | 把三者对 user client 的依赖列为关键未知 | 已查清：零依赖。结案 |
| `MANIFEST.md` | "Required selectors: 2, 0" 未给大小与字段 | 大小确为 600 / 64；字段级契约见本文 7.3、7.4 |
| `metal_drivers/` | 两个厂商样本无 MANIFEST 登记 | 由 `90-EVIDENCE-INDEX.md` 补 UUID 与 SHA-256（UUID 见本文第 0 节） |

## 11. 未查清事项

### 11.1 三个 selector 名字未解析

`BLOCKED`（缺口明确，有可行解法）。

未解析的 selref：

| selref RVA（`S-METAL`） | 使用点 | 返回 | 影响 |
|---|---|---|---|
| `+0x35E9DD88` | `initWithAcceleratorPort:` 第三条自发消息 | void，丢弃 | 无（不构成失败点） |
| `+0x35E9D3D0` | `initFeatureQueries` 第一条 | void | 低 |
| `+0x35E9BF20` | `initFeatureQueries` 对 `_featureQueries` 的收尾调用 | — | 低 |

**缺什么**：`S-METAL` 是从 dyld shared cache 抽出的单镜像，selector 字符串被 unique 到了其它镜像。`__objc_selrefs` 槽的内容指向 `0x7FF81F..0x7FF82.` 区间，而本镜像的 `__objc_methname` 只覆盖 `+0x299CBF..+0x2D2975`；relative method list 的 name 偏移同样落在段空洞（如 `initLimits` 的 name 目标是 `+0x43F762`，在 `__objc_methtype` 结束 `+0x2EB26A` 与 `__got` 起始 `+0x35E34F40` 之间的未映射区）。

**怎么取得**，按代价排序：

1. 仓库里已有 `metal_drivers/dyld_shared_cache_x86_64.map`。若它含符号/字符串区映射，可把 `0x7FF820076A7B` 等地址归属到具体镜像，再从该镜像读字符串。**成本最低，先试这个。**
2. 用整条 dyld shared cache（而非单镜像）建一个 IDB，或用 `dyld_shared_cache_util -extract` 把持有该字符串的镜像也抽出来并按同一 base 加载。
3. 在目标 guest 上 `class_copyMethodList([MTLIOAccelDevice class], &n)` 打印全部选择器名，与本文的 RVA/encoding 对齐。属 `TESTED` 级证据，最可靠。

**不要**在这三个名字上编造默认值。`initWithAcceleratorPort:` 的第三条消息按 TU 内相邻函数判断可能是 `updateGPUSelectionProperties`（`S-METAL` +0x1EDE，同一编译单元且紧随其后），但这只是位置推测，**未证实，不得写进实现**。

### 11.2 Intel 的 `featureProfile` 具体值

`BLOCKED`（低优先）。`-[MTLIGAccelDevice featureProfile]`（`S-INTEL` +0x35AFA）返回一个 init 期缓存的 ivar，值由硬件代际表决定。取得方法：反编译 `-[MTLIGAccelDevice initWithAcceleratorPort:]`（`S-INTEL` +0x2E87D）追该 ivar 的写入点。对本项目决策无影响 —— AMD 的 `10002` 已是明确可用值。

### 11.3 `MTLDeviceSPI` 必需方法全集

交由 `21-OBJC-OBJECT-FAMILY.md`。本分册只确立：`MTLAddDevice` 用 `conformsToProtocol:` 做 release 级断言，所以 `MTLDevice` 与 `MTLDeviceSPI` 两个协议**必须在类声明里显式列出**，而不只是"实现了方法"。`KNOWN`

### 11.4 BaseSystem 与 installed SystemOS 的差异

`BLOCKED`，与 `MANIFEST.md` 的 "Missing evidence" 一致。`S-METAL` / `S-IOACCEL` 来自 BaseSystem dyld shared cache，**未证明与装机后的 SystemOS 镜像字节一致**。本文所有 RVA 在换样本后必须重新核对；结构性结论（类继承、selector 编号、结构字段顺序）跨样本稳定的可能性高，但未实测。

取得方法：在目标 guest 装好后取 `/System/Library/dyld/dyld_shared_cache_x86_64*`，按同法重抽，比对 UUID 与本文全部 RVA。

### 11.5 全链路未实测

本文全部结论是静态分析（`KNOWN` / `INFERRED`），没有一条是 `TESTED`。第一个验收点应是：kext 发布 `MetalPluginName`，实现 type-5 selector `0`/`2`（按 7.3、7.4 的结构）与 type-6 selector `9`/`0xA`，plugin 的 device 类继承 `MTLIOAccelDevice` 并只覆写 `featureProfile`（返回 10002）、`argumentBuffersSupport`（返回 0 或 1）、`name`，然后看 `MTLCopyAllDevices()` 是否返回该设备且不触发 `initLimits` 的五条断言。该验收由 `80-TEST-HARNESS.md` 定义。
