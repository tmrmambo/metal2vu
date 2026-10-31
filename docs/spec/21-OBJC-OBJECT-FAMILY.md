# 21 — ObjC 对象族：APV Metal plugin 的实测实现边界

文档版本：1.1

> [!IMPORTANT]
> **1.1 更正：本文有四处类名是编的，已被运行期证伪。**
>
> `91-RUNTIME-EVIDENCE.md` 第 2.2 节在真实 macOS 26 x86_64 上做了
> `objc_getClass` 全量核对（`TESTED(25G76)`）：
>
> | 本文写的类名 | 实际 | 正确做法 |
> |---|---|---|
> | `_MTLRenderCommandEncoder` | **不存在** | encoder 宿主类由本项目自建，父类取 `NSObject`。`_MTLParallelRenderCommandEncoder` **存在**（size 232 / im 28 / ivar 20），parallel 路径可继承它 |
> | `_MTLComputeCommandEncoder` | **不存在** | 同上 |
> | `_MTLBlitCommandEncoder` | **不存在** | 同上 |
> | `_MTLBuffer` / `_MTLTexture` / `_MTLEvent` | **不存在** | 资源链真实形态是 `MTLIOAccelBuffer -> MTLIOAccelResource -> _MTLResource -> _MTLAllocation -> _MTLObjectWithLabel`，比本文画的多两层 |
> | `MTLLibraryBuilder` / `MTLLibraryDataWithArchive` | **不存在** | 本文与 `32` 分册都说 metallib 解析在这两个类里，名字是错的 |
>
> **直接后果**：encoder 宿主类**没有 Apple 抽象基类可继承**，所以
> 「`endEncoding` 之后对象进入什么状态」完全由本项目定义，没有既有行为可抄。
> 处置见 `42-RUNTIME-MAPPING.md` 第 3.2 节的四态状态机。
>
> **本文通过的部分**（同一轮核对，22 条断言过 20 条）：`MTLIOAccelDevice`
> 无前导下划线且 `_MTLDevice` 是其父类、七个 `MTLIOAccel*` 节点全在、
> `MTLDeviceSPI` 的 427 + 80 = 507、5 个协议外虚方法在 `_MTLDevice` 上且
> 25 个协议零泄漏、`AppleParavirtDevice` 71 个 IMP、`featureProfile = 10000`、
> `argumentBuffersSupport = 0`。
>
> **第 8.2 节「507 条不逐条抄」已被补齐。** 逐条处置见
> `23-DEVICE-SPI-DISPOSITION.md`（由运行期转储机械生成）。624 条不同
> selector 里，第一版必须自己写的只有 **49 条**（必须覆写 20 + 必须实现 29），
> 507 条可继承基类。

基线：macOS Tahoe 26.7.2 / build 25G325 / **x86_64**
职责（见 `00-OVERVIEW.md` 第 8 节）：全量 Metal 协议与 selector 清单、required/optional、精确 x86_64 encoding、所有权与线程规则

本文的主证据是 **`AppleParavirtGPUMetal.bundle` 的 x86_64 可执行码**。按 `00-OVERVIEW.md` 第 4.3 节，APV 是 Apple 自己为虚拟机写的 Metal driver plugin，不操作硬件寄存器，因此它实现了什么就是"一个非硬件 Metal 驱动最少要实现什么"的权威答案。AMD/Intel 驱动只用于对照。

## 0. 样本、地址与标签约定

所有地址写成 `样本代号 + RVA`。RVA = 绝对 VA − 该样本 image base。

| 代号 | 文件 | LC_UUID | arch | filetype | image base | 来源层 |
|---|---|---|---|---|---|---|
| `S-APV` | `analysis/binaries/macos26-25G325-x86_64/metal-bundle/AppleParavirtGPUMetal.x86_64` | `15DB02D8-D7E6-30A1-979C-DFD657E47F19` | x86_64 | `MH_BUNDLE` (0x8) | `0x0` | 安装资产 payload 解出的原生独立 Mach-O |
| `S-METAL` | `analysis/idb/macos26-25G325-x86_64-frameworks/idb/Metal-BaseSystem-analysis.i64` | `FDB3FD2C-840A-3FC3-81FB-C524F891F642` | x86_64 | `MH_DYLIB` (0x6) | `0x7FF80B179000` | BaseSystem dyld shared cache |
| `S-DUMP` | `analysis/idb/macos26-25G325-x86_64-frameworks/metal-objc.json` | — | x86_64 | UTF-16LE 文本 | — | `S-METAL` 的 `__objc_protolist` class-dump 式转储 |
| `S-INTEL` | `metal_drivers/AppleIntelICLGraphicsMTLDriver_decompressed` | `251E3AE2-1396-3AD1-974A-422AE954B85A` | x86_64 | — | `0x0` | 安装包载荷解压 |

`S-APV` 的 UUID 与 `MH_BUNDLE` 类型由本文实读 `LC_UUID` / `mach_header.filetype` 确证，与任务给定值一致。`S-METAL` 的 UUID 与 base 与 `20-OBJC-DEVICE.md` 第 0 节一致。

本文新增的 IDB：`analysis/idb/macos26-25G325-x86_64/AppleParavirtGPUMetal-apvmetal.i64`（仅新增，未改动 `analysis/idb/` 下任何既有文件）。

证据标签：`KNOWN` / `INFERRED` / `BLOCKED` / `TESTED`，定义见 `00-OVERVIEW.md` 第 7 节。

### 0.1 `S-APV` 的 ObjC 段布局

`KNOWN`。全部 ObjC 元数据段（RVA，base = 0）：

| 段 | 起 | 止 | 内容 |
|---|---|---|---|
| `__objc_classlist` | `0x416E0` | `0x417C0` | **28 个类** |
| `__objc_protolist` | `0x417C0` | `0x41950` | **50 个协议定义副本** |
| `__objc_methlist` | `0x1C578` | `0x22D68` | relative method list（entsize `0x8000000C`，12 字节条目） |
| `__objc_methname` | `0x22D68` | `0x314F0` | selector 字符串，**在镜像内，可直接读** |
| `__objc_methtype` | `0x324B5` | `0x3A8D8` | type encoding 字符串 |
| `__objc_selrefs` | `0x4CE90` | `0x50258` | — |
| `__objc_ivar` | `0x50258` | `0x50698` | — |

**这一点很重要**：`S-APV` 是独立 Mach-O，不是 dyld shared cache 抽出的单镜像，因此它的 relative method list 的 name 偏移指向镜像内的 selref 槽，selector 名字**全部可解析**。`20-OBJC-DEVICE.md` 第 11.1 节记录的"selector 名字解析不出来"在 `S-METAL` 上成立，在 `S-APV` 上**不成立**。

### 0.2 三源交叉校验（本文全部 encoding 的可信度依据）

`KNOWN`。`S-APV` 的 `__objc_protolist` 带 50 份协议定义副本；`S-METAL` 带 144 份；`S-DUMP` 是 `S-METAL` 那 144 份的文本转储（带方法名、`@required` / `@optional` 分界、property 属性串，但不带 encoding）。

三项已实测的一致性结论：

1. **`S-DUMP` 的方法顺序 == `S-METAL` 协议元数据顺序。** 验证方法：把 `S-DUMP` 的方法名按序与 `S-METAL` 协议 method record 的 encoding 逐一配对，再用"selector 冒号数 == encoding 中参数偏移组数 − 3"做 arity 校验。16 个协议、约 800 个方法，仅 2 处 arity "异常"，均因 encoding 内含结构体位宽数字（`{IndirectArgumentBufferCapabilities=b1b1b1b29}`、`[4I]`），不是错配。**因此"`S-DUMP` 取名 + `S-METAL` 取 encoding"的拼接是合法的。**
2. **`S-APV` 与 `S-METAL` 的协议 encoding 完全一致。** 20 个共有协议、按名字建表逐项比对，**差异 0 项**，含 `MTLDeviceSPI` 全部 507 项、`MTLDevice` 全部 139 项、`MTLTexture` 39 项、`MTLCommandBuffer` 39 项。两个镜像内协议方法的**排列顺序不同**，但 name→encoding 映射相同。
3. **`MTLDeviceSPI` = 427 required + 80 optional = 507**，在 `S-APV`、`S-METAL`、`S-INTEL` 三个独立样本上一致，与 `docs/CAPABILITY_PROFILES.md` 第 4 节的声称一致。本文直接引用此结论，不重算。
   同批确证：`MTLDevice` = **137 required + 2 optional = 139**。

因此本文的 encoding 一律是**实际读到的字符串**，并且有两个独立来源。

### 0.3 `S-METAL` 与 `S-APV` 的互补关系

`KNOWN`。`S-METAL` 的 `__objc_protolist` 只含 Metal **自己发射了定义**的那 144 个协议。被 dyld cache 去重到其它镜像的协议不在其中，具体缺失的有：`MTLCommandQueue`、`MTLCommandQueueSPI`、`MTLCommandBufferSPI`、`MTLBufferSPI`、`MTLRenderCommandEncoder`、`MTLRenderCommandEncoderSPI`、`MTLComputeCommandEncoder`、`MTLComputeCommandEncoderSPI`、`MTLBlitCommandEncoder`、`MTLBlitCommandEncoderSPI`、`MTLParallelRenderCommandEncoderSPI`、`MTLHeap`、`MTLRenderPipelineStateSPI`、`MTLComputePipelineStateSPI`、`MTLPipelineStateWithProgramAddressTable`。

**这 15 个协议的定义副本恰好全在 `S-APV` 里**（因为 APV 的类适配它们）。两个样本合起来覆盖本项目第一版需要的全部协议，无缺口。

## 1. 结论摘要

| # | 问题 | 结论 | 标签 |
|---|---|---|---|
| 1 | APV 是否自己实现 `newLibraryWithData:error:` | **否，零 IMP。** 整个 library 创建与 metallib/AIR 解析全在 Metal.framework | `KNOWN` |
| 2 | APV 是否自己实现 `newRenderPipelineStateWithDescriptor:error:` | **否，零 IMP。** 它实现的是下游的 `newRenderPipelineWithDescriptor:vertexVariant:fragmentVariant:errorMessage:` | `KNOWN` |
| 3 | `newFunctionWithName:` / `newLibraryWithSource:options:error:` | **都没有 IMP。** 前者属 `_MTLLibrary`，后者属 `_MTLDevice` | `KNOWN` |
| 4 | `newComputePipelineStateWithDescriptor:options:reflection:error:` | **没有 IMP。** APV 实现 `newComputePipelineWithDescriptor:variant:errorMessage:` | `KNOWN` |
| 5 | shader 接入点一共几个 selector | **5 个**（3 个 variant 工厂 + 2 个 pipeline 工厂）+ 3 个辅助（`compiler`、`llvmVersion`、`setupCompiler`） | `KNOWN` |
| 6 | 驱动是否看见 AIR/metallib 字节 | **不看见。** 它收到的是 `MTLCompiler` + 厂商 compiler plugin 产出的不透明 `dispatch_data_t`，整块 memcpy 进共享缓冲就交给宿主 | `KNOWN` |
| 7 | `featureProfile` | **`return 10000;`**（`S-APV` +0xACC3，整个方法体一条 `mov eax, 2710h`）。AMD 是 10002 | `KNOWN` |
| 8 | `argumentBuffersSupport` | **0 = `MTLArgumentBuffersTier1`**。APV 不覆写，由 `_MTLDevice` 从 `indirectArgumentBufferCapabilities`（基类 `return 0`）推出 | `KNOWN` |
| 9 | APV `AppleParavirtDevice` 的 IMP 数 | **71 个实例方法、0 个类方法**，其中 49 个落在 `MTLDeviceSPI` 协议闭包内，22 个是 APV 私有 | `KNOWN` |
| 10 | 是否整族继承 `MTLIOAccel*` | **部分。** device / command queue / command buffer / buffer / texture / heap / pooled-resource 继承 `MTLIOAccel*`；pipeline state / sampler / depth-stencil / fence / parallel-encoder / command-encoder 继承 `_MTL*` 抽象层；**library 与 function 没有自己的类**（function 另有一个 `NSObject` 直系的容器类） | `KNOWN` |
| 11 | APV 的类总数 | **28 个**，其中 `AppleParavirt*` 22 个、`PGSerializer*` 6 个 | `KNOWN` |
| 12 | APV 的用户态 IOKit 调用面 | 仅 7 个符号：`IOAccelSharedGetConnect`、`IOConnectCallMethod`、`IOAccelResourceGetClientSharedPrivate`、`IOAccelResourceListAddResource`、`IOAccelResourceListMergeLists`、`IOAccelDeviceGetNextGlobalTraceID`、`IOSurfaceCopyValue`/`IOSurfaceGetID` | `KNOWN` |
| 13 | APV 的厂商私有 selector 号 | **`0x102`**（注册 function IR）、**`0x105`**（读 deviceInfo，284 字节）。落在 `20-OBJC-DEVICE.md` 第 6.3 节预测的 `0x100+` 区间 | `KNOWN` |

**对本项目最关键的一条**：`00-OVERVIEW.md` 第 3 节把 ① Shader 边界标为"查漏补缺"。本文把这条边界的 ObjC 侧收口到**5 个 selector**，并确证 Metal.framework 不要求驱动理解 AIR —— 驱动只需要能消费"自己的 compiler plugin 产出的不透明二进制"。即 `30-SHADER-AIR.md` 的 AIR→SPIR-V 工作可以整体搬到一个 compiler plugin dylib 里，也可以留在 driver plugin 内，**Metal 的 ABI 对此不设约束**。

## 2. 优先级 1：library 与 pipeline 创建的真实分工

### 2.1 APV 没有实现的（零 IMP，实测）

`KNOWN`。方法：遍历 `S-APV` `__objc_classlist` 全部 28 个类的 `baseMethods` 与 metaclass `baseMethods`（共 71 + 0 条属于 `AppleParavirtDevice`），按 selector 名精确匹配。

| selector | `AppleParavirtDevice` 是否有 IMP | 实际由谁实现 |
|---|---|---|
| `newLibraryWithData:error:` | **无** | `-[_MTLDevice newLibraryWithData:error:]` `S-METAL` +0x276A6 |
| `newLibraryWithFile:error:` | **无** | `-[_MTLDevice ...]` `S-METAL` +0x2863B |
| `newLibraryWithURL:error:` | **无** | `-[_MTLDevice ...]` `S-METAL` +0x23CBA |
| `newDefaultLibraryWithBundle:error:` | **无** | `-[_MTLDevice ...]` `S-METAL` +0x1B65C |
| `newLibraryWithSource:options:error:` | **无** | `-[_MTLDevice ...]` `S-METAL` +0x115E75 |
| `newLibraryWithSource:options:completionHandler:` | **无** | `-[_MTLDevice ...]` `S-METAL` +0x115F37 |
| `newLibraryWithStitchedDescriptor:error:` | **无** | `-[_MTLDevice ...]` `S-METAL` +0x1176B7 |
| `newFunctionWithName:` | **无** | `-[_MTLLibrary newFunctionWithName:]` `S-METAL` +0x1C6D3 |
| `newFunctionWithName:constantValues:error:` | **无** | `-[_MTLLibrary ...]` `S-METAL` +0x248FF |
| `newRenderPipelineStateWithDescriptor:error:` | **无** | `-[_MTLDevice ...]` `S-METAL` +0x1D185 |
| `newRenderPipelineStateWithDescriptor:options:reflection:error:` | **无** | `-[_MTLDevice ...]` `S-METAL` +0x1198A5 |
| `newRenderPipelineStateWithDescriptor:completionHandler:` | **无** | `-[_MTLDevice ...]` `S-METAL` +0x119900 |
| `newComputePipelineStateWithDescriptor:error:` | **无** | `-[_MTLDevice ...]` `S-METAL` +0x25095 |
| `newComputePipelineStateWithDescriptor:options:reflection:error:` | **无** | `-[_MTLDevice ...]` `S-METAL` +0x1199E1 |
| `newComputePipelineStateWithFunction:error:` | **无** | `-[_MTLDevice ...]` `S-METAL` +0x24F03 |
| `newComputePipelineStateWithFunction:options:reflection:error:` | **无** | `-[_MTLDevice ...]` `S-METAL` +0x117332 |
| `newBinaryArchiveWithDescriptor:error:` | **无** | Metal（`supportsBinaryArchives` 返回 0，整条路径不走） |

**这条结论与既有分析对 AMD/Intel 的观察一致，并把原因讲清楚了**：那些 selector 在厂商驱动里只有 selRef 引用、没有本地 IMP，不是因为被 Metal.framework "先编译再交付"而绕过，而是因为**它们本来就不在驱动的职责里**。`_MTLDevice` 是这些 selector 的唯一实现者，驱动不需要、也不应该覆写它们。

### 2.2 Metal.framework 实际做的事（完整调用链）

`KNOWN`，`S-METAL` 反编译。

```
[device newLibraryWithData:dispatchData error:&err]        S-METAL +0x276A6
  └─ MTLLibraryBuilder::newLibraryWithData(_libraryBuilder, device, data, &err)   +0x2770A
       ├─ MTLUINT256_t 哈希 -> MTLLibraryCache::findLibraryData / newLibraryData   +0x2419A / +0x1BFC2
       ├─ LibraryWithData::{getFileSize,readBytes,setPosition,getPosition}         +0x2778E/+0x27748/+0x27720/+0x277A4
       ├─ MTLLibraryContainer::init(libraryData, dict, array, err)                 +0x1C1A6
       └─ [[_MTLLibrary alloc] initWithLibraryContainer:device:]                   +0x1C448
  └─ 若 _librariesOutputDirectory != NULL: MTLPipelineCollection::addLibrary

[library newFunctionWithName:@"vs"]                        S-METAL +0x1C6D3
  └─ -[_MTLLibrary newFunctionWithNameInternal:]                                   +0x1C726
       ├─ os_unfair_lock(MTLLibraryData::mutex(_libraryData))
       ├─ 查 _functionDictionary 缓存
       ├─ MTLLibraryContainer::functionWithName(_cacheEntry, name, _device)         +0x1C832
       │    └─ MTLLibraryDataWithArchive::newFunction(name, device)                +0x1C88E
       │         └─ readFunctionMetadata / readFunctionPublicOrPrivateMetadata     +0x1D7B2 / +0x1D7D2
       └─ MTLPipelineCollection::addFunction

[device newRenderPipelineStateWithDescriptor:d error:&err] S-METAL +0x1D185
  └─ c = [self compiler]                      ← selref 槽 S-METAL +0x35E9C2B0
  └─ [c <5 参 selector>:d :0 :0 :&err :0]      ← selref 槽 S-METAL +0x35E9D770
       == -[MTLCompiler newRenderPipelineStateWithDescriptor:options:reflection:error:completionHandler:]  +0x1D534
            └─ -[MTLCompiler newRenderPipelineStateWithDescriptorInternal:options:reflection:
                              destinationBinaryArchive:error:compilerTask:completionHandler:]             +0x18F8A6
                 ├─ 编译 AIR -> 目标码（经 MTLCompiler 的 plugin，见 2.4）
                 ├─ [device newVertexVariantWithCompilerOutput:  pipelineStatisticsOutput:]   ← 驱动
                 ├─ [device newFragmentVariantWithCompilerOutput:pipelineStatisticsOutput:]   ← 驱动
                 └─ [device newRenderPipelineWithDescriptor:vertexVariant:fragmentVariant:
                                                     errorMessage:]                           ← 驱动
```

两处地址归属的证据：

- `[self compiler]` 的 selref 槽 `S-METAL` +0x35E9C2B0 被 **33 个函数**引用，全部是取 compiler 的场景（`newRenderPipelineStateWithDescriptor:error:` +0x1D195、`newComputePipelineStateWithDescriptor:error:` +0x250A5、`-[_MTLBinaryArchive addRenderPipelineFunctionsWithDescriptor:options:error:]` +0xB06A2、`-[_MTLDevice libraryCacheStats]` +0x115B5E 等）。`KNOWN`
- 5 参 selector 的 selref 槽 `S-METAL` +0x35E9D770 只被 **4 个函数**引用，正好是 render pipeline 的四个入口（+0x1D1A6、+0x1198D0、+0x119955、+0x1199B7）。唯一与之签名吻合的 Metal 方法是 `-[MTLCompiler newRenderPipelineStateWithDescriptor:options:reflection:error:completionHandler:]`（+0x1D534）。`KNOWN`
- 最后三跳（`MTLCompiler` → 驱动的 variant / pipeline SPI）的**调用点行号无法在 `S-METAL` 上按名字确证**，原因见第 11.1 节（dyld cache selector 外置）。但结论本身是 `KNOWN` 的，依据见 2.3：基类对这组 selector 的实现全部 `return nil`，所以任何能成功创建 pipeline 的路径都必须经过 plugin 的覆写。`INFERRED`（调用点）/ `KNOWN`（必经性）

### 2.3 基类对这组 SPI 的实现：全部 `return nil`

`KNOWN`，`S-METAL` 逐一反编译。这是本节最有力的证据。

| `_MTLDevice` 方法 | RVA | 方法体 |
|---|---|---|
| `vertexVariantWithCompilerOutput:pipelineStatisticsOutput:` | `0x11A20C` | `return nil;` |
| `fragmentVariantWithCompilerOutput:pipelineStatisticsOutput:` | `0x11A204` | （同组，紧邻） |
| `computeVariantWithCompilerOutput:pipelineStatisticsOutput:` | `0x11A1FC` | （同组，紧邻） |
| `newTileVariantWithCompilerOutput:pipelineStatisticsOutput:functionType:` | `0x11A216` | `return nil;` |
| `newObjectVariantWithCompilerOutput:pipelineStatisticsOutput:` | `0x11A35E` | （同组） |
| `newMeshVariantWithCompilerOutput:pipelineStatisticsOutput:` | `0x11A366` | （同组） |
| `newRenderPipelineWithDescriptor:vertexVariant:fragmentVariant:` | `0x11A21E` | `return nil;` |
| `newComputePipelineWithDescriptor:variant:` | `0x11A230` | `return nil;` |
| `newRenderPipelineWithDescriptor:objectVariant:meshVariant:fragmentVariant:errorMessage:` | `0x11A36E` | `return nil;` |
| `compiler` | `0x119DF4` | `return nil;` |
| `indirectArgumentBufferCapabilities` | `0x11AB48` | `return 0;` |

而带 `new` 前缀的那三个是薄包装，基类**有**实现，只是转发到上面那组空实现：

```objc
// -[_MTLDevice newVertexVariantWithCompilerOutput:pipelineStatisticsOutput:]   S-METAL +0x1FE5C
void *pool = objc_autoreleasePoolPush();
id v = [self <selref +0x35E9D7D8>:a3];     // == vertexVariantWithCompilerOutput:pipelineStatisticsOutput:
v = objc_retain(v);
objc_autoreleasePoolPop(pool);
return v;

// -[_MTLDevice newRenderPipelineWithDescriptor:vertexVariant:fragmentVariant:errorMessage:]  S-METAL +0x1FEBE
return [self <selref +0x35E9D7E0>:...];    // == newRenderPipelineWithDescriptor:vertexVariant:fragmentVariant:

// -[_MTLDevice newComputePipelineWithDescriptor:variant:errorMessage:]         S-METAL +0x25598
if (errorMessage) *errorMessage = nil;
id v = [self <selref +0x35E9D7E8>:...];    // == newComputePipelineWithDescriptor:variant:
if (errorMessage && !v) *errorMessage = [NSString stringWithFormat/stringWithString:
                                            @"Error creating compute variant"];
return v;
```

两条 selref 槽（+0x35E9D7D8、+0x35E9D7E0）各只有 1 个引用点，即上面这两个包装方法本身。`KNOWN`

**实现结论（硬约束）**：本项目的 Device 类**必须覆写** `newVertexVariantWithCompilerOutput:pipelineStatisticsOutput:`、`newFragmentVariantWithCompilerOutput:pipelineStatisticsOutput:`、`newComputeVariantWithCompilerOutput:pipelineStatisticsOutput:`、`newRenderPipelineWithDescriptor:vertexVariant:fragmentVariant:errorMessage:`、`newComputePipelineWithDescriptor:variant:errorMessage:`、`compiler`。不覆写则所有 pipeline 创建返回 nil，且 compute 路径会给出 `@"Error creating compute variant"`。**不要覆写 `newLibraryWith*` / `newFunctionWith*` / `newRenderPipelineStateWith*` / `newComputePipelineStateWith*`。** `KNOWN`

注意 `newRenderPipelineWithDescriptor:vertexVariant:fragmentVariant:errorMessage:` 的最后一个参数是 **`NSString **errorMessage`，不是 `NSError **`**（基类在 nil 时往里塞的是 `CFSTR`）。驱动层只报字符串，`NSError` 的包装由 `MTLCompiler` 做。详见第 9.4 节。

### 2.4 APV 实际实现的 8 个 selector

`KNOWN`，`S-APV` 反编译。

| selector | RVA | type encoding | 作用 |
|---|---|---|---|
| `setupCompiler` | `0xA459` | `B16@0:8` | 建 `MTLCompiler`，见 2.4.1 |
| `compiler` | `0xA607` | `@16@0:8` | `return _apvCompiler;`（ivar `0xD418`） |
| `llvmVersion` | `0xB04F` | `i16@0:8` | `return 32023;`（`mov eax, 7D17h`） |
| `newVertexVariantWithCompilerOutput:pipelineStatisticsOutput:` | `0xAF05` | `@32@0:8@16@24` | `functionType = 1` |
| `newFragmentVariantWithCompilerOutput:pipelineStatisticsOutput:` | `0xAF3E` | `@32@0:8@16@24` | `functionType = 2` |
| `newComputeVariantWithCompilerOutput:pipelineStatisticsOutput:` | `0xAF77` | `@32@0:8@16@24` | `functionType = 3` |
| `newRenderPipelineWithDescriptor:vertexVariant:fragmentVariant:errorMessage:` | `0xAFB0` | `@48@0:8@16@24@32^@40` | alloc + init `AppleParavirtRenderPipelineState` |
| `newComputePipelineWithDescriptor:variant:errorMessage:` | `0xB008` | `@40@0:8@16@24^@32` | alloc + init `AppleParavirtComputePipelineState` |

三个 variant 工厂的方法体完全同形，只差最后一个常量：

```objc
// -[AppleParavirtDevice newVertexVariantWithCompilerOutput:pipelineStatisticsOutput:]  S-APV +0xAF05
id v = objc_alloc([AppleParavirtFunctionVariant class]);
return [v initWithCompilerOutput:a3 device:self functionType:1];   // fragment=2, compute=3
```

**`pipelineStatisticsOutput:`（第二个参数）被完整丢弃**，三个方法里都没有它的任何引用。`KNOWN`

两个 pipeline 工厂同样是纯转发：

```objc
// S-APV +0xAFB0
id p = objc_alloc([AppleParavirtRenderPipelineState class]);
return [p initWithDevice:self pipelineStateDescriptor:a3
            vertexVariant:a4 fragmentVariant:a5 errorMessage:a6];   // S-APV +0x14763

// S-APV +0xB008
id p = objc_alloc([AppleParavirtComputePipelineState class]);
return [p initWithDevice:self pipelineStateDescriptor:a3
           computeVariant:a4 errorMessage:a5];                      // S-APV +0x14E3B
```

#### 2.4.1 `setupCompiler`：驱动怎么把自己的编译器插进 Metal

`KNOWN`，`S-APV` +0xA459 全函数反编译。**这是本项目 shader 侧的核心模板。**

```objc
// -[AppleParavirtDevice setupCompiler]
void *pool = objc_autoreleasePoolPush();
uint8_t md[32] = {0};

NSBundle *b = [NSBundle bundleForClass:[self class]];
NSString *pluginPath = [NSString pathWithComponents:
                          @[[b resourcePath], @"libAppleParavirtCompilerPlugin.dylib"]];

CC_SHA256_CTX c;
CC_SHA256_Init(&c);
CC_SHA256_Update(&c, "Sep 22 2026", 8);      // __DATE__ 前 8 字节
CC_SHA256_Update(&c, "21:55:22",    8);      // __TIME__ 全 8 字节
CC_SHA256_Final(md, &c);                      // -> 32 字节 cacheUUID

uint64_t targetData = *(uint64_t *)&_deviceInfo.MaxMetalShaderVersionMajor;   // {u32 major, u32 minor}
if ((uint32_t)targetData <= 1)                // major <= 1
    sub_1ADED();                              // cold：致命，不返回

dispatch_data_t td = dispatch_data_create(&targetData, 8, NULL, NULL);
_apvCompiler = [[MTLCompiler alloc] initWithTargetData:td
                                             cacheUUID:md
                                            pluginPath:pluginPath
                                                device:self
                                         compilerFlags:32];
dispatch_release(td);
BOOL ok = (_apvCompiler != nil);
objc_autoreleasePoolPop(pool);
return ok;
```

逐项含义：

| 参数 | 值 | 对本项目的要求 |
|---|---|---|
| `targetData` | 8 字节 `dispatch_data_t`，内容 = `{uint32 MaxMetalShaderVersionMajor, uint32 MaxMetalShaderVersionMinor}`，取自宿主返回的 `deviceInfo`（私有 selector `0x105`） | 自行选定一对版本号即可；`major` 必须 > 1，否则 `setupCompiler` 走 cold 块 |
| `cacheUUID` | 32 字节，= `SHA256(__DATE__[0..8) ‖ __TIME__[0..8))`，即**编译时间戳的哈希** | 作用是 shader 缓存失效键：插件一重编译，全部缓存条目作废。本项目应照此做（用构建 ID 或版本哈希） |
| `pluginPath` | `<bundle>/Contents/Resources/libAppleParavirtCompilerPlugin.dylib` | **编译器是一个随 bundle 交付的独立 dylib，由 `MTLCompiler` 加载。**本项目的 AIR→SPIR-V 可以放在这里 |
| `device` | `self` | `MTLCompiler` 回头向 device 查能力（`featureProfile`、`llvmVersion`、`targetDeviceArchitecture` 等） |
| `compilerFlags` | `32`（`0x20`） | 语义未查清，见第 11.3 节 |

`MTLCompiler` 是 **Metal.framework 的类**（`S-APV` 以 `_OBJC_CLASS_$_MTLCompiler` 外部引用存在），不是 APV 自建的。`KNOWN`

`setupCompiler` 返回 NO 会让 `-[AppleParavirtDevice initWithAcceleratorPort:]` 整体返回 nil（`S-APV` +0xA30F）：

```objc
self = [super initWithAcceleratorPort:port];          // -> MTLIOAccelDevice, S-METAL +0x17CF
if (!self) return nil;
*(uint64 *)((char *)self + OBJC_IVAR_$_MTLIOAccelDevice._segmentByteThreshold) = 0x40000000;
[self setupDeviceInfo];                               // 私有 selector 0x105
if (![self setupCompiler]) { objc_release(self); return nil; }      // ← 失败点
[self setupResourcePools];
_objectRefAllocator = [AppleParavirtObjectRefAllocator new];
if (!_objectRefAllocator) { objc_release(self); return nil; }
_serializer = _deviceInfo.DeserializerVersionDefined
    ? [[PGSerializer alloc] initWithDevice:self objectRefAllocator:_objectRefAllocator
                      deserializerVersion:_deviceInfo.DeserializerVersion.u]
    : [[PGSerializer alloc] initWithDevice:self objectRefAllocator:_objectRefAllocator];
if (!_serializer) { objc_release(self); return nil; }
_descriptorHeaps = [NSMutableArray new];
_descriptor_heaps_lock = OS_UNFAIR_LOCK_INIT;
return self;
```

注意 `[super initWithAcceleratorPort:]` 走的是 `MTLIOAccelDevice` 的完整实现，含 `lazyInitialize`（APV **不**覆写 `supportLazyInitialization`），所以 APV 真的开了 type-6 user client 并要求 `IOAccelSharedSetupDirtyRing` 成功。`20-OBJC-DEVICE.md` 第 5.5.1 节的"把 `supportLazyInitialization` 覆写为 YES"是**本项目独有的捷径，APV 不走**。`KNOWN`

#### 2.4.2 编译产物在驱动里走到哪：`AppleParavirtFunctionVariant`

`KNOWN`，`S-APV` +0x30CF 全函数反编译。**这是"驱动是否解析 metallib"的直接答案：不解析。**

```objc
// -[AppleParavirtFunctionVariant initWithCompilerOutput:(dispatch_data_t)out
//                                           device:(AppleParavirtDevice *)dev
//                                     functionType:(uint64_t)type]        encoding @40@0:8@16@24Q32
self = [super initWithCompilerOutput:];                 // -[MTLFunctionVariant initWithCompilerOutput:] S-METAL +0x1FC8D
if (!self) return nil;
_device = objc_retain(dev);
void *pool = objc_autoreleasePoolPush();

size_t size = dispatch_data_get_size(out);
_descriptorBuffer = [dev newDescriptorBuffer:size];     // AppleParavirtDescriptorBuffer, S-APV +0xAD09
if (!_descriptorBuffer)            { os_log FAULT; goto fail; }
if (![_descriptorBuffer contents])  { os_log FAULT; goto fail; }

const void *p; size_t n;
dispatch_data_t map = dispatch_data_create_map(out, &p, &n);
memcpy([_descriptorBuffer contents], p, size);          // ← 整块不透明拷贝，零解析
dispatch_release(map);

AppleParavirtAllocator *alloc = objc_autorelease([AppleParavirtAllocator new]);
uint8_t *rec = [alloc allocateOperationBytes:24];
if (!alloc) { os_log ERROR; goto fail; }

// 24 字节操作记录
//   +0x00 u32 functionRef        （下一步填）
//   +0x04 u32 resourceID         = [_descriptorBuffer resourceID]
//   +0x08 u64 gpuVirtualAddress  = *(u64 *)((char *)_descriptorBuffer + IVAR(MTLIOAccelResource._res) + 224)
//   +0x10 u64 size
*(uint32_t *)(rec + 4)  = [_descriptorBuffer resourceID];
*(uint64_t *)(rec + 8)  = *(uint64_t *)((char *)_descriptorBuffer
                              + OBJC_IVAR_$_MTLIOAccelResource._res + 224);
*(uint64_t *)(rec + 16) = size;

_functionRef = [[dev serializer] newFunctionWithIR:alloc];
*(uint32_t *)rec = _functionRef;

mach_port_t conn = IOAccelSharedGetConnect([dev sharedRef]);
uint32_t outCnt = 1;
_objectIndex = 0xFFFFFFFF;
kern_return_t kr = IOConnectCallMethod(conn, /*selector*/ 0x102,
                                       NULL, 0,                  // scalar in
                                       rec, [alloc length],      // struct in
                                       &_objectIndex, &outCnt,   // scalar out (1 x u64 槽)
                                       NULL, NULL);
if (kr != 0) { os_log FAULT(kr); goto fail; }

function = [[AppleParavirtContainerFunction alloc] initWithDevice:dev
                                                     functionType:type
                                                      functionRef:_functionRef];
objc_autoreleasePoolPop(pool);
return self;

fail:
    objc_release(self);
    objc_autoreleasePoolPop(pool);
    return nil;
```

`AppleParavirtFunctionVariant` 的 ivar 布局（`S-APV`，`inst_start = 0x18`，父类 `MTLFunctionVariant`）：

| 偏移 | 名称 | 类型 |
|---|---|---|
| `0x18` | `_descriptorBuffer` | `AppleParavirtDescriptorBuffer *` |
| `0x20` | `_functionRef` | `uint32_t`（serializer 的对象 ref） |
| `0x28` | `_device` | `AppleParavirtDevice *`（强引用） |
| `0x30` | `_objectIndex` | `uint64_t`（宿主侧句柄；失败哨兵 `0xFFFFFFFF`） |
| `0x38` | `function` | `AppleParavirtContainerFunction *` |

四个方法：`initWithCompilerOutput:device:functionType:` (+0x30CF)、`dealloc` (+0x33E7)、`function` (+0x358C)、`descriptorBuffer` (+0x359D)。不适配任何协议。

**结论**：驱动对编译产物的全部操作是「量大小 → 申请一块 GPU 可见缓冲 → memcpy → 把 (ref, resourceID, GPU VA, size) 交给宿主」。字节格式由**驱动自己的 compiler plugin** 定义，Metal 不参与，宿主与 plugin 私下约定。`KNOWN`

### 2.5 对本项目的实现契约

`INFERRED`（基于上面全部 `KNOWN` 证据的设计决定）

1. **不碰 library/function 层。** 继承 `MTLIOAccelDevice` 后 `newLibraryWith*` / `newFunctionWith*` 全部由 `_MTLDevice` / `_MTLLibrary` 免费提供，并且它们已经做了 metallib 解析、函数名索引、常量特化、缓存与哈希。本项目不实现 `MTLLibrary` 协议，也不实现 `MTLFunction` 协议（APV 实现了后者，但那是为了自己的容器对象，见第 6.4 节）。
2. **AIR→SPIR-V 放在一个 compiler plugin dylib 里**，路径 `<bundle>/Contents/Resources/lib<Name>CompilerPlugin.dylib`，由 `[[MTLCompiler alloc] initWithTargetData:cacheUUID:pluginPath:device:compilerFlags:]` 加载。`cacheUUID` 用构建哈希。这样 `30-SHADER-AIR.md` 的产物就是一个 dylib，与 ObjC 对象族解耦。
3. **第一版的 shader 接入面就是 5 个 selector**：三个 `new*VariantWithCompilerOutput:pipelineStatisticsOutput:` 加两个 `new*PipelineWithDescriptor:...errorMessage:`。`pipelineStatisticsOutput:` 可以忽略（APV 就忽略）。
4. **Variant 对象可以很薄。** APV 的 variant 只持有一块缓冲 + 两个整数句柄。本项目的 variant 应持有 `31-PIPELINE-ARTIFACT.md` 定义的 `PipelineArtifact` 句柄。
5. **tile / mesh / object / 可见函数表路径直接拒绝。** APV 对 `newRenderPipelineStateWithTileDescriptor:options:reflection:error:`（+0xB384）、`...completionHandler:`（+0xB36F）、`newVisibleFunctionTableWithDescriptor:`（+0xB404）调用 `doesNotRecognizeSelector:` 然后返回 nil；对 `newIndirectCommandBufferWithDescriptor:maxCount:options:`（+0xAC57）、`newIndirectComputeCommandEncoderWithBuffer:`（+0xAC5F）、`newIndirectRenderCommandEncoderWithBuffer:`（+0xAC67）、`newHeapWithDescriptor:`（+0xAABF）直接 `return nil`。两种做法都在 release 版可用；**`return nil` 更安全**，`doesNotRecognizeSelector:` 会抛 `NSInvalidArgumentException`。`KNOWN`（APV 行为）/ `INFERRED`（选择建议）

## 3. 优先级 2.1：`AppleParavirtGPUMetal` 的类继承树全量

`KNOWN`。`S-APV` `__objc_classlist`（`0x416E0`..`0x417C0`，28 项）全量遍历，父类名取自 `class_t.superclass` 的 bind 符号（`_OBJC_CLASS_$_*`）或镜像内 `class_t` 地址。`inst_start` = 编译期父类 `instanceSize`，`inst_size` = 本类 `instanceSize`。

| # | 类 | 父类 | `inst_start` | `inst_size` | 新增 ivar 字节 | 适配协议 | 实例方法 IMP 数 |
|---|---|---|---|---|---|---|---|
| 1 | `AppleParavirtDevice` | `MTLIOAccelDevice` | `0xD400` | `0xD568` | 360 | `MTLDeviceSPI` | 71 |
| 2 | `AppleParavirtCommandQueue` | `MTLIOAccelCommandQueue` | `0x2C8` | `0x2C8` | **0** | `MTLCommandQueueSPI` | 7 |
| 3 | `AppleParavirtCommandBuffer` | `MTLIOAccelCommandBuffer` | `0x2F8` | `0x370` | 120 | `MTLCommandBufferSPI`, `PGSerializerCommandStream` | 29 |
| 4 | `AppleParavirtBuffer` | `MTLIOAccelBuffer` | `0x178` | `0x188` | 16 | `MTLBufferSPI`, `PGSerializerBuffer` | 18 |
| 5 | `AppleParavirtPooledBuffer` | `MTLIOAccelPooledResource` | `0x168` | `0x178` | 16 | `PGSerializerBuffer` | 22 |
| 6 | `AppleParavirtTexture` | `MTLIOAccelTexture` | `0x214` | `0x228` | 20 | `MTLTextureSPI`, `PGSerializerTexture`, `MTLTextureImplementation` | 25 |
| 7 | `AppleParavirtHeap` | `MTLIOAccelHeap` | `0xB0` | `0xB4` | 4 | `MTLHeap`, `PGSerializerHeap` | 5 |
| 8 | `AppleParavirtDescriptorHeap` | `MTLIOAccelHeap` | `0xB0` | `0xB0` | **0** | — | 2 |
| 9 | `AppleParavirtDescriptorBuffer` | `MTLIOAccelBuffer` | `0x178` | `0x178` | **0** | — | 1 |
| 10 | `AppleParavirtRenderPipelineState` | `_MTLRenderPipelineState` | `0x78` | `0xD0` | 88 | `MTLRenderPipelineStateSPI`, `PGSerializerRenderPipelineState`, `AppleParavirtState` | 8 |
| 11 | `AppleParavirtComputePipelineState` | `_MTLComputePipelineState` | `0x50` | `0x98` | 72 | `MTLComputePipelineStateSPI`, `PGSerializerComputePipelineState`, `AppleParavirtState` | 9 |
| 12 | `AppleParavirtDepthStencilState` | `_MTLDepthStencilState` | `0x18` | `0x28` | 16 | `MTLDepthStencilState`, `PGSerializerDepthStencilState`, `AppleParavirtState` | 4 |
| 13 | `AppleParavirtSamplerState` | `_MTLSamplerState` | `0x30` | `0x40` | 16 | `MTLSamplerState`, `PGSerializerSamplerState` | 4 |
| 14 | `AppleParavirtFence` | `_MTLObjectWithLabel` | `0x14` | `0x28` | 20 | `MTLFence`, `PGSerializerFence`, `AppleParavirtState` | 5 |
| 15 | `AppleParavirtFunctionVariant` | `MTLFunctionVariant` | `0x18` | `0x40` | 40 | — | 4 |
| 16 | `AppleParavirtContainerFunction` | `NSObject` | `0x8` | `0x60` | 88 | `MTLFunction`, `PGSerializerFunction` | 16 |
| 17 | `AppleParavirtBlitCommandEncoder` | `PGSerializerBlitCommandEncoder` | `0x91` | `0x91` | **0** | — | 2 |
| 18 | `AppleParavirtParallelRenderCommandEncoder` | `PGSerializerParallelRenderCommandEncoder` | `0x109` | `0x111` | 8 | — | 3 |
| 19 | `AppleParavirtAllocator` | `NSObject` | `0x8` | `0x100C` | 4100 | `PGSerializerAllocator` | 3 |
| 20 | `AppleParavirtObjectRefAllocator` | `NSObject` | `0x8` | `0x48` | 64 | `PGSerializerObjectRefAllocator` | 6 |
| 21 | `AppleParavirtTextureDimension` | `NSObject` | `0x8` | `0x8` | **0** | — | 0（+3 类方法） |
| 22 | `AppleParavirtState`（协议，非类） | — | — | — | — | — | — |
| 23 | `PGSerializer` | `NSObject` | `0x8` | `0x3D` | 53 | — | 95 |
| 24 | `PGSerializerCommandEncoder` | `_MTLCommandEncoder` | `0x78` | `0x90` | 24 | `MTLCommandEncoder` | 21 |
| 25 | `PGSerializerRenderCommandEncoder` | `PGSerializerCommandEncoder` | `0x90` | `0x1468` | 5080 | `MTLRenderCommandEncoderSPI` | 152 |
| 26 | `PGSerializerComputeCommandEncoder` | `PGSerializerCommandEncoder` | `0x90` | `0x769` | 1753 | `MTLComputeCommandEncoderSPI` | 58 |
| 27 | `PGSerializerBlitCommandEncoder` | `PGSerializerCommandEncoder` | `0x90` | `0x91` | 1 | `MTLBlitCommandEncoderSPI` | 38 |
| 28 | `PGSerializerInfoCommandEncoder` | `PGSerializerCommandEncoder` | `0x90` | `0x98` | 8 | — | 21（+1 类方法） |
| 29 | `PGSerializerParallelRenderCommandEncoder` | `_MTLParallelRenderCommandEncoder` | `0xE8` | `0x109` | 33 | `MTLParallelRenderCommandEncoderSPI` | 15 |

（表内第 22 行是协议名，为对照保留；类计数仍是 28。）

### 3.1 与 Apple `MTLIOAccel*` 类表的逐条比对

拿 `20-OBJC-DEVICE.md` 第 2.1 节的 `MTLIOAccel*` 表做底，标出 APV 取了哪些、跳过了哪些。`KNOWN`

| Apple 基类 | 父类 | APV 子类 | 判定 |
|---|---|---|---|
| `MTLIOAccelDevice` | `_MTLDevice` | `AppleParavirtDevice` | **取** |
| `MTLIOAccelCommandQueue` | `_MTLCommandQueue` | `AppleParavirtCommandQueue` | **取**（且零新增 ivar，纯转发 super） |
| `MTLIOAccelCommandBuffer` | `_MTLCommandBuffer` | `AppleParavirtCommandBuffer` | **取** |
| `MTLIOAccelCommandEncoder` | `_MTLCommandEncoder` | — | **跳过**，APV 的 encoder 基类是自建的 `PGSerializerCommandEncoder <- _MTLCommandEncoder` |
| `MTLIOAccelRenderCommandEncoder` | `MTLIOAccelCommandEncoder` | — | **跳过** |
| `MTLIOAccelComputeCommandEncoder` | `MTLIOAccelCommandEncoder` | — | **跳过** |
| `MTLIOAccelBlitCommandEncoder` | `MTLIOAccelCommandEncoder` | — | **跳过** |
| `MTLIOAccelResourceStateCommandEncoder` | `MTLIOAccelCommandEncoder` | — | **跳过**（`resourceStateCommandEncoder` 另有实现，见 6.3） |
| `MTLIOAccelParallelRenderCommandEncoder` | `_MTLParallelRenderCommandEncoder` | — | **跳过**，直接从 `_MTLParallelRenderCommandEncoder` 派生 |
| `MTLIOAccelDebugCommandEncoder` | `_MTLDebugCommandEncoder` | — | 跳过 |
| `MTLIOAccelResource` | `_MTLResource` | （经 Buffer/Texture 间接继承） | 间接取 |
| `MTLIOAccelBuffer` | `MTLIOAccelResource` | `AppleParavirtBuffer`, `AppleParavirtDescriptorBuffer` | **取** |
| `MTLIOAccelTexture` | `MTLIOAccelResource` | `AppleParavirtTexture` | **取** |
| `MTLIOAccelPooledResource` | `MTLIOAccelResource` | `AppleParavirtPooledBuffer` | **取** |
| `MTLIOAccelIndirectCommandBuffer` | `MTLIOAccelResource` | — | 跳过（ICB 不支持） |
| `MTLIOAccelAccelerationStructure` | `MTLIOAccelResource` | — | 跳过（无光追） |
| `MTLIOAccelIntersectionFunctionTable` | `MTLIOAccelResource` | — | 跳过 |
| `MTLIOAccelVisibleFunctionTable` | `MTLIOAccelResource` | — | 跳过 |
| `MTLIOAccelHeap` | `_MTLHeap` | `AppleParavirtHeap`, `AppleParavirtDescriptorHeap` | **取** |
| `MTLIOAccelFence` | `_MTLFence` | — | **跳过**，`AppleParavirtFence <- _MTLObjectWithLabel` |
| `MTLIOAccelIndirectArgumentEncoder` | `_MTLIndirectArgumentEncoder` | — | 跳过 |
| `MTLIOAccelIndirectRenderCommand` / `...ComputeCommand` | `_MTLIndirect*Command` | — | 跳过 |
| `MTLIOAccelIOCommandQueue` / `...IOCommandBuffer` / `...IOHandle*` | `_MTLIO*` | — | 跳过（MTLIO 不支持） |
| `MTLIOAccelResourcePool` | `NSObject` | 直接使用（`_OBJC_CLASS_$_MTLIOAccelResourcePool` 外部引用，不子类化） | 直接用 |
| `MTLIOAccelDeviceShmem` / `...ShmemPool` / `MTLIOAccelService` / `...TextureLayout` | `NSObject` | — | 由基类 `lazyInitialize` 内部使用，APV 不碰 |

**对"是否整族继承 `MTLIOAccel*`"的答复：不是整族。** APV 取的是 `MTLIOAccel*` 的 **device + queue + command buffer + resource（buffer/texture/pooled）+ heap** 这 7 个节点；**全部 encoder 与全部 state 对象走 `_MTL*` 抽象层**；fence 甚至退到 `_MTLObjectWithLabel`（比 `_MTLFence` 还低一层）。

这与 `20-OBJC-DEVICE.md` 第 2.2 节观察到的 Intel（几乎一比一吃掉 `MTLIOAccel*` 层）明显不同，与 AMD（不子类化 queue、library 自建）部分相同。**APV 的划分对本项目更有参考价值**，因为它的理由和本项目一样：encoder 里没有硬件寄存器可写，`MTLIOAccel*` encoder 基类提供的 shmem 命令缓冲簿记对一个"把命令序列化给另一端"的驱动毫无用处。

### 3.2 `PGSerializer` 这一层的意义

`KNOWN`。`PGSerializer`（`S-APV` `0x50918`，95 个方法）是 APV 自己的**命令序列化器**：encoder 的全部 `set*` / `draw*` / `dispatch*` 把参数写成 FIFO 命令，由 `PGSerializer` 统一编码。四个 `PGSerializer*CommandEncoder` 是"协议适配 + 参数打包"，`AppleParavirt*CommandEncoder` 只在其上加极少的东西（blit 加 2 个方法、parallel 加 3 个），render 与 compute 甚至**没有 `AppleParavirt*` 子类**，直接用 `PGSerializer*CommandEncoder`。

`PGSerializerCommandEncoder` 的 21 个方法里只有 1 个（`endEncoding`）属于 `MTLCommandEncoder` 协议，其余 20 个是序列化器内部 API（`setBuffers:offsets:withRange:withCommand:bindings:`、`getCommandBytes:forCommand:`、`beginSegment:protectionOptions:`、`writeSegmentHeader:continuation:protectionOptions:`、`split` 等）。

**本项目的对应物**：`PGSerializer` 的位置就是本项目"窄 C ABI → Rust 渲染核心"的边界（`00-OVERVIEW.md` 第 6 节）。APV 证明了这个分层在 Metal 的 ObjC ABI 下是可行的：**encoder 类只负责把 Metal 调用翻成自己的中间表示，不需要继承任何 IOKit 相关基类。** `INFERRED`

## 4. 优先级 2.2：`AppleParavirtDevice` 的 IMP 全集与继承划分

`KNOWN`。`S-APV` `class_ro_t`（`0x492A0`）`baseMethods` = `0x1CA68`，relative method list，**71 条实例方法，0 条类方法**。`baseProtocols` 只列 **`MTLDeviceSPI`** 一个（`MTLDeviceSPI <- MTLDevice`，所以 `MTLAddDevice` 的两条 `conformsToProtocol:` 断言同时满足，见 `20-OBJC-DEVICE.md` 第 3 节）。

协议归属统计：**49 条落在 `MTLDevice` / `MTLDeviceSPI` 协议闭包内，22 条不在任何协议里**。"不在任何协议里"分两种：APV 自建的内部方法，和 **`_MTLDevice` 的非协议虚方法契约**（`compiler`、三个 variant 工厂、两个 pipeline 工厂、`supportsOpenGL`、`supportsComputeCoalescing`、`supportsCorrectTextureUsageBits`、`tileSizeWithTextureType:pixelFormat:sampleCount:`、`getSharedTextureAllocSize:`）。

> **这是一条容易踩的坑**：本文第 2 节确定的 shader 接入点那 5 个 selector **都不在 `MTLDevice` 也不在 `MTLDeviceSPI` 里**。只按协议清单实现方法会漏掉整条 pipeline 创建路径。它们是 `_MTLDevice` 的虚方法，只能靠反编译基类才能发现。`KNOWN`

### 4.1 按类别分组（全 71 条）

#### 4.1.1 identity 与生命周期（6 条，全部 APV 私有或继承覆写）

| selector | RVA | encoding | 协议 | 实现摘要 |
|---|---|---|---|---|
| `initWithAcceleratorPort:` | `0xA30F` | `@20@0:8I16` | — | 调 super 后做 5 步初始化，见 2.4.1 |
| `dealloc` | `0xA8B3` | `v16@0:8` | — | — |
| `setupDeviceInfo` | `0xA7CA` | `v16@0:8` | — | 私有 selector `0x105`，out 284 字节 |
| `setupResourcePools` | `0xA618` | `v16@0:8` | — | — |
| `setupCompiler` | `0xA459` | `B16@0:8` | — | 见 2.4.1 |
| `releaseObjectRef:` | `0xB090` | `v20@0:8I16` | — | 尾调 `[_objectRefAllocator releaseRef:]` |

身份字符串（3 条，全部 `req:MTLDeviceSPI`）：

| selector | RVA | encoding | 返回值 |
|---|---|---|---|
| `vendorName` | `0xACA8` | `@16@0:8` | `@"Apple"` |
| `productName` | `0xAC6F` | `@16@0:8` | `@"Paravirtual device"` |
| `familyName` | `0xAC4A` | `@16@0:8` | `S-APV` 的 `__cfstring` 项 `0x41560` |

**`name`、`architecture`、`registryID`、`maxBufferLength`、`recommendedMaxWorkingSetSize`、`hasUnifiedMemory`、`isLowPower`、`isHeadless`、`isRemovable`、`location*`、`peerGroupID`/`peerIndex`/`peerCount`、`currentAllocatedSize`、`sharedMemorySize`、`dedicatedMemorySize`、`acceleratorPort`、`deviceRef`、`sharedRef`、`supportLazyInitialization`、`lazyInitialize`、`initLimits`、`initFeatureQueries`、`initGPUFamilySupport`、`supportsFamily:`、`targetDeviceArchitecture`、`counterSets`、`newEvent`、`newSharedEvent`、`newArgumentEncoderWithLayout:`、`newCommandQueue`、`newCommandQueueWithMaxCommandBufferCount:` 全部不覆写**，由 `MTLIOAccelDevice` / `_MTLDevice` 提供。`KNOWN`（即 `20-OBJC-DEVICE.md` 第 6.2 节"两家都不覆写"的清单在 APV 上同样成立，并且 APV 比 AMD/Intel 覆写得更少 —— 71 对 181/175。）

#### 4.1.2 编译器接口（8 条）

见第 2.4 节表格，不重复。对照 `20-OBJC-DEVICE.md` 第 6.2 节：AMD 的编译器接口约 30 个 selector（含 `get*FunctionId:compilerOptions:compilerOptionsSize:`、`*FunctionKeyWithRenderPipelineDescriptor:...`、`free*FunctionKey:*`、`targetDeviceArchitecture`），**APV 只要 8 个，且不含任何 FunctionKey / FunctionId 族**。本项目按 APV 的 8 个实现即可。`KNOWN`

#### 4.1.3 资源与对象工厂（18 条）

| selector | RVA | encoding | 协议 | 实现 |
|---|---|---|---|---|
| `newBufferWithLength:options:` | `0xAA3E` | `@32@0:8Q16Q24` | `req:MTLDevice` | → `AppleParavirtBuffer initWithDevice:withLength:withOptions:withPointer:withDeallocator:`（ptr=0, dealloc=0） |
| `newBufferWithBytes:length:options:` | `0xA943` | `@40@0:8r^v16Q24Q32` | `req:MTLDevice` | 同上 + memcpy |
| `newBufferWithBytesNoCopy:length:options:deallocator:` | `0xA9E6` | `@48@0:8^v16Q24Q32@?40` | `req:MTLDevice` | 同上，带 block |
| `newTextureWithDescriptor:` | `0xAAFA` | `@24@0:8@16` | `req:MTLDevice` | 先 `[desc validateWithDevice:self]`，失败返回 nil |
| `newTextureWithDescriptor:iosurface:plane:` | `0xAB4B` | `@40@0:8@16^{__IOSurface=}24Q32` | `req:MTLDeviceSPI` | — |
| `newSharedTextureWithDescriptor:` | `0xB166` | `@24@0:8@16` | `req:MTLDevice` | — |
| `newSharedTextureWithHandle:` | `0xB1B6` | `@24@0:8@16` | `req:MTLDevice` | — |
| `newSamplerStateWithDescriptor:` | `0xAAC7` | `@24@0:8@16` | `req:MTLDevice` | → `AppleParavirtSamplerState` |
| `newDepthStencilStateWithDescriptor:` | `0xAA8C` | `@24@0:8@16` | `req:MTLDevice` | → `AppleParavirtDepthStencilState` |
| `newFence` | `0xB05A` | `@16@0:8` | `req:MTLDevice` | → `AppleParavirtFence initWithDevice:` |
| `newCommandQueueWithDescriptor:` | `0xACCE` | `@24@0:8@16` | `req:MTLDeviceSPI` | → `AppleParavirtCommandQueue initWithDevice:descriptor:` |
| `newHeapWithDescriptor:` | `0xAABF` | `@24@0:8@16` | `req:MTLDevice` | **`return nil;`** |
| `newIndirectCommandBufferWithDescriptor:maxCount:options:` | `0xAC57` | `@40@0:8@16Q24Q32` | `req:MTLDeviceSPI` | **`return nil;`** |
| `newIndirectComputeCommandEncoderWithBuffer:` | `0xAC5F` | `@24@0:8@16` | `req:MTLDeviceSPI` | **`return nil;`** |
| `newIndirectRenderCommandEncoderWithBuffer:` | `0xAC67` | `@24@0:8@16` | `req:MTLDeviceSPI` | **`return nil;`** |
| `newVisibleFunctionTableWithDescriptor:` | `0xB404` | `@24@0:8@16` | `req:MTLDeviceSPI` | `doesNotRecognizeSelector:` + nil |
| `newRenderPipelineStateWithTileDescriptor:options:reflection:error:` | `0xB384` | `@48@0:8@16Q24^@32^@40` | `req:MTLDevice` | `doesNotRecognizeSelector:` + nil |
| `newRenderPipelineStateWithTileDescriptor:options:completionHandler:` | `0xB36F` | `v40@0:8@16Q24@?32` | `req:MTLDevice` | `doesNotRecognizeSelector:` |
| `newDescriptorBuffer:` | `0xAD09` | `@24@0:8Q16` | — | APV 私有；见 2.4.2 |
| `allocateDescriptorForTexture:heap:offset:` | `0xAD01` | `c40@0:8@16^@24^Q32` | — | APV 私有 |

**注意 `newCommandQueue`（无参版）不被覆写**：`_MTLDevice` / `MTLIOAccelDevice` 的无参版会构造一个默认 descriptor 再转发到 `newCommandQueueWithDescriptor:`，因此只覆写带 descriptor 的那一个就够。`INFERRED`（由"APV 不覆写 `newCommandQueue` 而 queue 确实能建出来"推出）

#### 4.1.4 对齐与尺寸计算（7 条）

| selector | RVA | encoding | 协议 |
|---|---|---|---|
| `heapBufferSizeAndAlignWithLength:options:` | `0xA927` | `{?=QQ}32@0:8Q16Q24` | `req:MTLDevice` |
| `heapTextureSizeAndAlignWithDescriptor:` | `0xA931` | `{?=QQ}24@0:8@16` | `req:MTLDevice` |
| `minimumTextureBufferAlignmentForPixelFormat:` | `0xA93B` | `Q24@0:8Q16` | `req:MTLDevice` |
| `tileSizeWithTextureType:pixelFormat:sampleCount:` | `0xAC31` | `{?=QQQ}40@0:8Q16Q24Q32` | — |
| `sparseTileSizeWithTextureType:pixelFormat:sampleCount:` | `0xB39C` | `{?=QQQ}40@0:8Q16Q24Q32` | `req:MTLDevice` |
| `sparseTileSizeWithTextureType:pixelFormat:sampleCount:sparsePageSize:` | `0xB3D0` | `{?=QQQ}48@0:8Q16Q24Q32q40` | `req:MTLDevice` |
| `getSharedTextureAllocSize:` | `0xB2A3` | `Q24@0:8@16` | — |

`{?=QQ}` 是 `MTLSizeAndAlign`，`{?=QQQ}` 是 `MTLSize`。两者都是**间接返回（结构体 > 16 字节走 sret 的只有后者）**：`{?=QQ}` 16 字节在 x86_64 SysV 下走 `rax:rdx` 寄存器对，`{?=QQQ}` 24 字节走隐藏 sret 指针。encoding 里的 `32@0:8Q16Q24` 已经把 self/sel 偏移算在 0/8，**不含 sret 指针**，所以不能直接按 encoding 推 ABI 寄存器分配。`KNOWN`（encoding）/ `INFERRED`（ABI 解释，依据 x86_64 SysV）

#### 4.1.5 能力查询（29 条）

常量返回的（实测方法体）：

| selector | RVA | encoding | 返回 |
|---|---|---|---|
| `featureProfile` | `0xACC3` | `Q16@0:8` | **`10000`** |
| `llvmVersion` | `0xB04F` | `i16@0:8` | **`32023`** |
| `metalAssertionsEnabled` | `0xACB5` | `c16@0:8` | `0` |
| `areProgrammableSamplePositionsSupported` | `0xB088` | `c16@0:8` | `0` |
| `supportsOpenGL` | `0xB0F8` | `c16@0:8` | `0` |
| `supportsDynamicLibraries` | `0xB41C` | `c16@0:8` | `0` |
| `supportsStatefulDynamicLibraries` | `0xB424` | `c16@0:8` | `0` |
| `supportsRenderDynamicLibraries` | `0xB42C` | `c16@0:8` | `0` |
| `supportsFunctionPointers` | `0xB434` | `c16@0:8` | `0` |
| `supportsFunctionPointersFromRender` | `0xB43C` | `c16@0:8` | `0` |
| `supportsBinaryArchives` | `0xB444` | `c16@0:8` | `0` |
| `supportsArgumentBuffers` | `0xB44C` | `c16@0:8` | `0` |
| `supportsResourceHeaps` | `0xB454` | `c16@0:8` | `0` |
| `supportsComputeCoalescing` | `0xB45C` | `c16@0:8` | `0` |
| `supportsCorrectTextureUsageBits` | `0xB464` | `c16@0:8` | `0` |

ivar 直读的（值在 `setupDeviceInfo` 之后由宿主数据决定，静态分析不可知）：

| selector | RVA | encoding | 来源 |
|---|---|---|---|
| `doubleFPConfig` | `0xB46C` | `Q16@0:8` | ivar `0xD548` |
| `singleFPConfig` | `0xB47D` | `Q16@0:8` | ivar `0xD550` |
| `halfFPConfig` | `0xB48E` | `Q16@0:8` | ivar `0xD558` |
| `isMagicMipmapSupported` | `0xB49F` | `c16@0:8` | ivar `0xD544` |

`deviceInfo` 字段派生的：

| selector | RVA | encoding | 表达式 |
|---|---|---|---|
| `isDepth24Stencil8PixelFormatSupported` | `0xB0AD` | `c16@0:8` | `_deviceInfo.D24S8Supported.u != 0` |
| `maxThreadgroupMemoryLength` | `0xB0E7` | `Q16@0:8` | `_deviceInfo.MaxThreadgroupMemoryLength.u` |
| `maxThreadsPerThreadgroup` | `0xB0C4` | `{?=QQQ}16@0:8` | `{MaxThreadsPerThreadgroupW/H/D}` |
| `supportsSampleCount:` | `0xAC7C` | `c24@0:8Q16` | `n <= 16 && (0x10116 >> n) & 1 && n <= _deviceInfo.MSAASamples.u`，即允许集合 `{1,2,4,8,16}` 再被宿主上限夹住 |
| `supportsSharedTextureHandles` | `0xB120` | `c16@0:8` | `_deviceInfo.SupportsSharedTextures.u != 0 && _features.supportsSharedTextures && [_serializer supportsSharedTextures]` |
| `copyIOSurfaceSharedTextureProperties:` | `0xB206` | `@24@0:8@16` | `opt:MTLDeviceSPI` |

APV 私有访问器（3 条）：

| selector | RVA | encoding |
|---|---|---|
| `deviceInfo` | `0xB100` | `r^{?=(?=If)×43 C×43 II}16@0:8`（见 5.3） |
| `features` | `0xB110` | `r^{APVFeatures=B×17 II B×34}16@0:8` |
| `serializer` | `0xB4B0` | `@16@0:8` |

> `0x10116` 这个掩码的来源：反编译为 `v4 = 65814; _bittest64(&v4, n)`，`65814 = 0x10116 = bit1|bit2|bit4|bit8|bit16`。`KNOWN`

### 4.2 `supportsResourceHeaps` 与 `newHeapWithDescriptor:` 的一致性

`KNOWN`。两者都是"关"：`supportsResourceHeaps` 返回 0，`newHeapWithDescriptor:` 返回 nil。`AppleParavirtHeap` / `AppleParavirtDescriptorHeap` 两个类仍然存在，但 `AppleParavirtDescriptorHeap` 是给 2.4.2 的 descriptor buffer 池用的内部对象，不是 `MTLHeap` 的对外实现路径。

同理 `supportsArgumentBuffers` 返回 0，而 `_deviceInfo` 里明明有 `ArgumentBuffersTier` / `ArgumentBuffersMaxSamplerCount` 字段、`_features` 里有 `supportsArgumentBuffers` 位 —— **x86 的 APV Metal plugin 把 argument buffer 与 heap 整条关掉了**，没有接宿主的能力位。

**本项目的取舍**：`00-OVERVIEW.md` 第 4.7 节要求按全量能力编写，所以这两项最终要打开；但 APV 证明了"关掉它们设备仍然可用、WindowServer 仍然能合成"，所以第一版可以照 APV 关闭，把它们排到后面。`INFERRED`

## 5. 优先级 2.3 / 2.4：`featureProfile` 与 `argumentBuffersSupport`

### 5.1 `featureProfile` = 10000

`KNOWN`。`-[AppleParavirtDevice featureProfile]`，`S-APV` +0xACC3，encoding `Q16@0:8`，全部 5 条指令：

```asm
ACC3  push rbp
ACC4  mov  rbp, rsp
ACC7  mov  eax, 2710h          ; 10000
ACCC  pop  rbp
ACCD  retn
```

类里确实有一个名为 `featureProfile` 的 ivar（`S-APV` `0xD560`，`Q`，来自 `MTLDeviceSPI` 的 `featureProfile` property 的 `V` 后备字段声明），但 **getter 完全忽略它，返回硬编码常量**。

对照：

| 驱动 | `featureProfile` | 出处 |
|---|---|---|
| **APV（本项目参照）** | **`10000`** | `S-APV` +0xACC3 |
| AMD `GFXAAMD_MtlDevice` / `GFX10_MtlDevice` | `10002` | `20-OBJC-DEVICE.md` 第 5.2.2 节 |
| Intel `MTLIGAccelDevice` | 运行期缓存 ivar，未查清 | 同上，第 11.2 节 |

`20-OBJC-DEVICE.md` 第 5.2 节已确证 `initLimits` 对 `featureProfile ∈ {10000, 10001, 10002}` 给出同一组现代取值，因此 10000 与 10002 对 limits 表没有差别。

**本项目的决定：改用 `featureProfile = 10000`，与 APV 一致，取代 `20-OBJC-DEVICE.md` 第 5.2.2 节建议的 10002。** `INFERRED`

理由：10000 是 Apple 自己给"无硬件的半虚拟化设备"选的档位，而 10002 是独显档位。两者在 `initLimits` 里等价，但 `featureProfile` 还会流向 `getSupportedFamilies(MTLDeviceFeatureProfile)`（`S-METAL` +0x11362C，决定 `supportsFamily:` 的返回集合）、`MTLCompiler compileFunctionRequestInternal:...` 与 `_MTLGetMTLCompilerLLVMVersionForDevice`。选 Apple 为同类设备选的值，落在"已被 Apple 自己测过"的组合里。

**未查清**：`getSupportedFamilies(10000)` 与 `getSupportedFamilies(10002)` 返回的 family 集合是否不同。见第 11.2 节。

### 5.2 `argumentBuffersSupport` = 0（Tier1）

`KNOWN`。**APV 不覆写 `argumentBuffersSupport`**（71 条 IMP 里没有它）。基类实现：

```asm
; -[_MTLDevice argumentBuffersSupport]   S-METAL +0x3A82   encoding Q16@0:8
3A82  push rbp
3A83  mov  rbp, rsp
3A86  mov  rsi, cs:off_7FF841016588     ; selref 槽 S-METAL +0x35E9D588
3A8D  call qword ptr cs:[objc_msgSend]
3A93  not  eax
3A95  xor  ecx, ecx
3A97  test al, 7
3A99  setz cl
3A9C  mov  rax, rcx
3A9F  pop  rbp
3AA0  retn
```

即 `return ((cap & 7) == 7) ? 1 : 0;`。

被查询的 getter 是 **`indirectArgumentBufferCapabilities`**：

- 它的 `MTLDeviceSPI` encoding 实读为 **`{IndirectArgumentBufferCapabilities=b1b1b1b29}16@0:8`** —— 一个 4 字节结构体，正好 3 个 1-bit 位域 + 29 bit 保留。`argumentBuffersSupport` 测的就是低 3 位。`MTLDeviceSPI` 的 507 个方法里**只有这一个**返回 3×1-bit 结构体。`KNOWN`（encoding）/ `INFERRED`（身份；selector 字符串在 `S-METAL` 上不可解析，见第 11.1 节）
- selref 槽 `S-METAL` +0x35E9D588 在整个镜像里**只有 1 个引用点**，就是 `argumentBuffersSupport` 自己 —— 与"一个只在这一处被用的能力 getter"吻合。`KNOWN`
- `-[_MTLDevice indirectArgumentBufferCapabilities]`（`S-METAL` +0x11AB48）方法体是 **`return 0;`**。`KNOWN`

于是：APV 既不覆写 `argumentBuffersSupport` 也不覆写 `indirectArgumentBufferCapabilities`（71 条里都没有），所以链路是 `0` → `(~0)&7 = 7 ≠ 0` → **`argumentBuffersSupport` 返回 0 = `MTLArgumentBuffersTier1`**。

这满足 `20-OBJC-DEVICE.md` 第 5.2.1 节的硬约束（必须是 0 或 1，否则 `initLimits` 触发 `MTLReleaseAssertionFailure` 终止进程），**且满足方式是"什么都不做"**。

**本项目的决定：第一版同样不覆写这两个方法，接受 Tier1。** 要升到 Tier2 时覆写 `indirectArgumentBufferCapabilities` 让低 3 位全置 1 即可，不要直接覆写 `argumentBuffersSupport`（那样会和 `_MTLDeviceFeatureQueries familySupportsArgumentBuffersTier2` 的推导脱节）。`INFERRED`

与 APV 的 `supportsArgumentBuffers`（`S-APV` +0xB44C，`return 0;`）一致：整条 argument buffer 路线在 x86 APV 上是关的。

### 5.3 宿主能力结构：私有 selector `0x105`

`KNOWN`，`-[AppleParavirtDevice setupDeviceInfo]` `S-APV` +0xA7CA 全函数反编译。APV 把全部硬件能力一次性从宿主取回，不走任何 `IOAccel*` 包装：

```objc
mach_port_t conn = IOAccelSharedGetConnect([self sharedRef]);   // type-6 user client
size_t outCnt = 284;
uint32_t buf[71];
kern_return_t kr = IOConnectCallMethod(conn, 0x105,
                                       NULL, 0, NULL, 0,        // 无输入
                                       NULL, NULL,              // 无 scalar out
                                       buf, &outCnt);           // struct out 284 字节
if (kr) os_log_error(...);          // 失败被容忍，结构保持栈上未初始化值
memcpy(&_deviceInfo, buf, 224);                     // 前 224 字节
_features = *(APVFeatures *)((char *)buf + 224);    // 后 60 字节（四次 16 字节搬运）
```

两个 ivar 在类里**物理连续**：`_deviceInfo` @ `0xD428` 长 224，`_features` @ `0xD508` 长 60，`0xD428 + 224 = 0xD508`。所以宿主的 284 字节回复就是 `struct { APVDeviceInfo info; APVFeatures features; }` 的原样映像。`KNOWN`

`APVDeviceInfo`（224 字节）的布局，从 ivar type encoding 的字段名实读：

- `+0x00`..`+0xAB`：**43 个 4 字节字段**，每个是 `union { uint32_t u; float f; }`（encoding `(?="u"I"f"f)`），依次为
  `MSAASamples`, `D24S8Supported`, `MaxThreadsPerThreadgroupW`, `MaxThreadsPerThreadgroupH`, `MaxThreadsPerThreadgroupD`, `MaxThreadgroupMemoryLength`, `IsFramebufferReadSupported`, `IsRGB10A2GammaSupported`, `SupportsNativeHardwareFP16`, `DeserializerVersion`, `PrimtiveTypeSupport`（Apple 原样拼写）, `SupportsMultiplaneTextures`, `LinearTextureAlignment`, `HeapBuffers`, `HeapBufferAlignment`, `HeapTextures`, `BufferFromIOSurface`, `MaxMetalShaderVersion`, `SupportsSharedTextures`, `MaxVertexAmplificationCount`, `SupportsProgrammableSamplePositions`, `RasterizationRateLayerCount`, `TileShaders`, `ImageBlocks`, `RasterOrderGroups`, `MemoryOrderAtomics`, `LargeMRT`, `SupportFlags2023`, `MaxTotalComputeThreadsPerThreadgroup`, `MaxComputeLocalMemorySizes`, `MaxComputeThreadgroupMemory`, `MaxComputeThreadgroupMemoryAlignmentBytes`, `SupportFlags2024`, `GpuCoreCount`, `MaxTextureLayers`, `MaxPredicatedNestingDepth`, `HostGPUFamilyClamped`, `ArgumentBuffersTier`, `ArgumentBuffersMaxSamplerCount`, `MinimumLinearTextureAlignment`, `SupportedTextureWriteRoundingModes`, `SupportFlags2025`, `HostGPUFamilies`
- `+0xAC`..`+0xD6`：**43 个 `uint8_t` 的 `<字段名>Defined` 标志**，与上面一一对应
- `+0xD8`：`uint32_t MaxMetalShaderVersionMajor`
- `+0xDC`：`uint32_t MaxMetalShaderVersionMinor`

三个 `SupportFlags*` 与 `HostGPUFamilies` 自己是位域结构体：

| 字段 | 位域（按序） |
|---|---|
| `SupportFlags2023` | `SupportsApple5`, `SupportsDynamicAttributeStride`, `SupportsTexture2DMultisampleArray`, `Reserved:29` |
| `SupportFlags2024` | `SupportsLargeUserTasks`, `SupportsLargeKernelTasks`, `SupportsCommandBufferJump`, `SupportsRangeBuffer`, `SupportsSharedMemoryHeap`, `SupportsArgumentBuffers`, `SupportsSIMDReduction`, `SupportsFloat16BCubicFiltering`, `SupportsSIMDShuffleAndFill`, `SupportsConditionalLoadStore`, `SupportsComputeCompressedTextureWrite`, `SupportsSharedTexturePlacement`, `Reserved:20` |
| `SupportFlags2025` | `SupportsIndirectCommandBuffers`, `SupportsArgumentBuffers2025`, `SupportsEnhancedRenderICBs`, `Reserved:29` |
| `HostGPUFamilies` | `supportsFamily5`..`supportsFamily9`, `supportsFamily9b`, `supportsFamily10`, `supportsFamily11`, `reserved:24` |

`APVFeatures`（60 字节），字段名实读（`B` = `_Bool` 1 字节，`I` = `uint32_t`）：

- `+0x00`..`+0x10`：17 个 `_Bool`：`valid`, `unsupported`, `objectTables`, `efiDisplay`, `displayDoorbell`, `mapperIOSurfaces`, `synchronizeAndDiscardResources`, `displayMapperSurface`, `discardResources`, `displaySleep`, `supportsRGhAPresents`, `synchronizeDiscardChildResources`, `dualPlaneTextures`, `displaySetProperties`, `displayDimensionFloats`, `metalHeaps`, `bufferFromIOSurface`
- `+0x14`：`uint32_t maxFIFOCount`
- `+0x18`：`uint32_t s8ByteCountForD32S8`
- `+0x1C`..`+0x3B`：32 个 `_Bool`：`supportsSharedTextures`, `supportsInfoEncoder`, `supportsDefaultRasterSampleCount`, `supportsVertexAmplification`, `supportsSunburstDisplay`, `supportsProgrammableSamplePositions`, `supportsVariableRasterizationRateMaps`, `supportsTileShadersImageBlocks`, `supportsDisplayCompositorParameters`, `supportsCmdExecIndirect3`, `supportsSwizzledTextures`, `supportsDynamicAttributeStride`, `supportsBlitEncoderSPI`, `supportsMultiplaneMippedBlitTextures`, `supportsComputePassDescriptorDispatchType`, `supportsObjectUniqueIdentifier`, `supportsCommandBufferJump`, `supportsSharedStorageHeaps`, `supportsHeapHazardTracking`, `supportsProtectionOptionsEnvelope`, `supportsInsertCompressedTextureReinterpretationFlush`, `supportsArgumentBuffers`, `supportsDisplaySetGuestICCProfile`, `supportsCorrect2pXR10A8`, `supportsCPUBuffers`, `supportsIndirectCommandBuffers`, `supportsProtectedTextureOptions`, `supportsDispatchThreadsIndirect`, `supportsInfoIndirect`, `supportsDisplayPortConnectionType`, `supportsTextureDescriptor2`, `supportsMultipleDisplays`

**对本项目的用法**：这张表是"一个非硬件 Metal 设备需要知道的能力全集"的现成清单，直接对应 `60-CAPABILITY-MATRIX.md` 的行。本项目没有宿主，这些值是**自己选的常量**，不需要任何 user client selector —— 即 `20-OBJC-DEVICE.md` 第 7.5 节的 type-5 selector 集合不必扩充。`INFERRED`

注意 `setupCompiler` 对 `MaxMetalShaderVersionMajor <= 1` 走 cold 块（`S-APV` +0x1ADED，不返回），所以这张表里 **`MaxMetalShaderVersionMajor` 必须 ≥ 2**。`KNOWN`

## 6. 优先级 2.5：其余对象类的实现 / 继承划分

统计口径：`impl` = 该类自己的 IMP 数；`proto` = 它适配的协议闭包（含继承的协议与 `NSObject` 协议）的方法总数；`inProto` = `impl` 落在闭包内的条数；`private` = 落在闭包外的条数（APV 私有或基类非协议虚方法）。`KNOWN`

| 对象 | 类 | 继承自 | impl | proto | inProto | private | 覆盖率 |
|---|---|---|---|---|---|---|---|
| device | `AppleParavirtDevice` | `MTLIOAccelDevice` | 71 | 644 | 49 | 22 | 7.6% |
| command queue | `AppleParavirtCommandQueue` | `MTLIOAccelCommandQueue` | 7 | 78 | 6 | 1 | 7.7% |
| command buffer | `AppleParavirtCommandBuffer` | `MTLIOAccelCommandBuffer` | 29 | 125 | 20 | 9 | 16% |
| render encoder | `PGSerializerRenderCommandEncoder` | `PGSerializerCommandEncoder` | 152 | 207 | 136 | 16 | **66%** |
| compute encoder | `PGSerializerComputeCommandEncoder` | `PGSerializerCommandEncoder` | 58 | 95 | 46 | 12 | 48% |
| blit encoder | `PGSerializerBlitCommandEncoder` (+`AppleParavirtBlitCommandEncoder`) | `PGSerializerCommandEncoder` | 38 (+2) | 66 | 32 | 6 | 48% |
| parallel render encoder | `PGSerializerParallelRenderCommandEncoder` (+`AppleParavirt…`) | `_MTLParallelRenderCommandEncoder` | 15 (+3) | 40 | 10 | 5 | 25% |
| encoder 基类 | `PGSerializerCommandEncoder` | `_MTLCommandEncoder` | 21 | 28 | 1 | 20 | — |
| buffer | `AppleParavirtBuffer` | `MTLIOAccelBuffer` | 18 | 73 | 15 | 3 | 21% |
| pooled buffer | `AppleParavirtPooledBuffer` | `MTLIOAccelPooledResource` | 22 | — | 3 | 19 | — |
| texture | `AppleParavirtTexture` | `MTLIOAccelTexture` | 25 | 110 | 15 | 10 | 14% |
| **library** | **无类** | — | **0** | — | — | — | **全继承 `_MTLLibrary`** |
| function | `AppleParavirtContainerFunction` | `NSObject` | 16 | 34 | 14 | 2 | 41% |
| function variant | `AppleParavirtFunctionVariant` | `MTLFunctionVariant` | 4 | 0 | 0 | 4 | — |
| render pipeline state | `AppleParavirtRenderPipelineState` | `_MTLRenderPipelineState` | 8 | 133 | 5 | 3 | 3.8% |
| compute pipeline state | `AppleParavirtComputePipelineState` | `_MTLComputePipelineState` | 9 | 57 | 6 | 3 | 11% |
| sampler state | `AppleParavirtSamplerState` | `_MTLSamplerState` | 4 | 24 | 1 | 3 | 4.2% |
| depth-stencil state | `AppleParavirtDepthStencilState` | `_MTLDepthStencilState` | 4 | 25 | 2 | 2 | 8% |
| heap | `AppleParavirtHeap` | `MTLIOAccelHeap` | 5 | 45 | 5 | 0 | 11% |
| fence | `AppleParavirtFence` | `_MTLObjectWithLabel` | 5 | 25 | 3 | 2 | 12% |
| **event / shared event** | **无类** | — | **0** | — | — | — | **全继承 `_MTLIOAccelMTLEvent` / `_MTLSharedEvent`** |

**这张表是本文最有决策价值的东西**：真正要大量写代码的只有 **render encoder（136 条协议方法）** 和 **compute encoder（46 条）**。所有 state 对象、library、function、event、queue 的协议方法几乎全部由 Metal 的抽象基类免费提供，驱动只需要补 3–6 个"把自己的句柄暴露给序列化器"的方法。

### 6.1 state 对象的共同骨架

`KNOWN`。四个 state 类（render pipeline / compute pipeline / depth-stencil / sampler）加 fence 的实现形状完全一致：

```
-init…WithDevice:<descriptor>:           ← 自建，把 descriptor 序列化给另一端，拿回一个 uint32 ref
-dealloc                                 ← 自建，释放 ref
-<kind>Ref                 I16@0:8       ← PGSerializer* 协议要求，返回那个 uint32
-addResourcesToList:                     ← AppleParavirtState 协议要求，把自己挂进 IOAccelResourceList
```

| 类 | init | dealloc | ref getter | `addResourcesToList:` |
|---|---|---|---|---|
| `AppleParavirtRenderPipelineState` | `0x145CD`（2 参）/ `0x14763`（5 参带 variant） | `0x14A8C` | `pipelineRef` `0x14C56` | `0x14CE4` |
| `AppleParavirtComputePipelineState` | `0x14E3B` | `0x15211` | `pipelineRef` `0x153BB` | `0x153FD` |
| `AppleParavirtDepthStencilState` | `0x142B2` | `0x1442E` | `depthStencilRef` `0x145B2` | `0x145C2` |
| `AppleParavirtSamplerState` | `0x702D` | `0x71A9` | `samplerRef` `0x732D` | `0x733D` |
| `AppleParavirtFence` | `0xF1C` | `0x109D` | `fenceRef` `0x1232` | `0x1242` |

`addResourcesToList:` 的 encoding（五个类完全相同，这是一条很有用的内核结构定义）：

```
c24@0:8^{IOAccelResourceList=[256S]^{IOAccelSegmentResourceDescriptorGroup}QQIIIIIII^?^v}16
```

即 `- (BOOL)addResourcesToList:(IOAccelResourceList *)list`，其中
`IOAccelResourceList = { uint16_t[256]; IOAccelSegmentResourceDescriptorGroup *; uint64_t; uint64_t; uint32_t ×7; void (*)(); void *; }`。`KNOWN`

`AppleParavirtState` 协议只有这 1 个必需方法（`S-APV` `__objc_protolist`），`PGSerializerState` 协议有 0 个（纯标记协议）。

额外的方法：

| 类 | 额外 selector | RVA | encoding | 协议 |
|---|---|---|---|---|
| `AppleParavirtRenderPipelineState` | `newVertexShaderDebugInfo` | `0x14CA5` | `@16@0:8` | `req:MTLRenderPipelineStateSPI` |
| | `newFragmentShaderDebugInfo` | `0x14C66` | `@16@0:8` | `req:MTLRenderPipelineStateSPI` |
| | `getWritableInfo:vtxBuffers:vtxTexturesArrayLength:vtxTextures:frgBuffersLength:frgBuffers:frgTexturesArrayLength:frgTextures:tileBuffersArrayLength:tileBuffers:tileTexturesArrayLength:tileTextures:` | `0x14DA8` | `v88@0:8I16^I20I28^I32I40^I44I52^I56I64^I68I76^I80` | `req:PGSerializerRenderPipelineState` |
| `AppleParavirtComputePipelineState` | `threadExecutionWidth` | `0x153CB` | `Q16@0:8` | `req:MTLComputePipelineState` |
| | `staticThreadgroupMemoryLength` | `0x153DC` | `Q16@0:8` | `req:MTLComputePipelineState` |
| | `maxTotalThreadsPerThreadgroup` | `0x153ED` | `Q16@0:8` | `req:MTLComputePipelineState` |
| | `parseReply:` | `0x151D8` | `B24@0:8@16` | — |
| | `getWritableInfo:buffers:texturesArrayLength:textures:` | `0x15441` | `v40@0:8I16^I20I28^I32` | `req:PGSerializerComputePipelineState` |
| `AppleParavirtFence` | `device` | `0x124D` | `@16@0:8` | `req:MTLFence` |

**注意 `label` / `setLabel:` / `gpuResourceID` 三个 `MTLDepthStencilState` / `MTLSamplerState` 的必需方法 APV 一个都没实现** —— 全部由 `_MTLDepthStencilState` / `_MTLSamplerState` 提供。`_MTLObjectWithLabel` 这个父类的存在就是为了这件事。`KNOWN`

### 6.2 command queue：7 条，几乎全继承

`KNOWN`。

| selector | RVA | encoding | 协议 | 实现 |
|---|---|---|---|---|
| `initWithDevice:descriptor:` | `0xA22B` | `@32@0:8@16@24` | — | **纯转发 `[super initWithDevice:descriptor:]`，方法体只有 objc_super 构造 + msgSendSuper2** |
| `commandBuffer` | `0xA25A` | `@16@0:8` | `req:MTLCommandQueue` | `objc_autorelease([[AppleParavirtCommandBuffer alloc] initWithQueue:self retainedReferences:YES])` |
| `commandBufferWithUnretainedReferences` | `0xA295` | `@16@0:8` | `req:MTLCommandQueue` | 同上，`retainedReferences:NO` |
| `availableCounters` | `0xA2CD` | `@16@0:8` | `opt:MTLCommandQueueSPI` | — |
| `requestCounters:` | `0xA2D5` | `i24@0:8@16` | `opt:MTLCommandQueueSPI` | — |
| `getRequestedCounters` | `0xA2DD` | `@16@0:8` | `opt:MTLCommandQueueSPI` | — |
| `counterInfo` | `0xA2F6` | `@16@0:8` | `opt:MTLCommandQueueSPI` | — |

**`submitCommandBuffers:count:`、`setLabel:`、`insertDebugCaptureBoundary`、`_setGPUPriority:backgroundPriority:`、`setCompletionQueue:`、`dealloc` 全部不覆写。** 即 APV 确实走 `MTLIOAccelCommandQueue` 的 type-8 user client 与 `IOAccelCommandQueueSubmitCommandBuffers` 提交路径（`20-OBJC-DEVICE.md` 第 8.3 节的 A 档五个方法 APV 一个都没换）。

**本项目在这一点上必须与 APV 分道**：本项目没有宿主可提交，必须替换提交路径。`20-OBJC-DEVICE.md` 第 8.7 节的决定（queue 继承 `_MTLCommandQueue`、覆写 `newCommandQueueWithDescriptor:`）保持有效。`INFERRED`

`AppleParavirtCommandQueue` **零新增 ivar**（`inst_start == inst_size == 0x2C8`），所有状态都在基类里。

### 6.3 command buffer：29 条

`KNOWN`。

| selector | RVA | encoding | 协议 |
|---|---|---|---|
| `initWithQueue:retainedReferences:` | `0x17C48` | `@28@0:8@16c24` | — |
| `dealloc` | `0x17C77` | `v16@0:8` | — |
| `renderCommandEncoderWithDescriptor:` | `0x17FB6` | `@24@0:8@16` | `req:MTLCommandBuffer` |
| `computeCommandEncoder` | `0x17D8C` | `@16@0:8` | `req:MTLCommandBuffer` |
| `computeCommandEncoderWithDispatchType:` | `0x17E0D` | `@24@0:8Q16` | `req:MTLCommandBuffer` |
| `computeCommandEncoderWithDescriptor:` | `0x17EA1` | `@24@0:8@16` | `req:MTLCommandBuffer` |
| `blitCommandEncoder` | `0x17CA6` | `@16@0:8` | `req:MTLCommandBuffer` |
| `blitCommandEncoderWithDescriptor:` | `0x17D27` | `@24@0:8@16` | `req:MTLCommandBuffer` |
| `parallelRenderCommandEncoderWithDescriptor:` | `0x17F06` | `@24@0:8@16` | `req:MTLCommandBuffer` |
| `resourceStateCommandEncoder` | `0x18066` | `@16@0:8` | `req:MTLCommandBuffer` |
| `endEncoding` | `0x18346` | `v16@0:8` | — |
| `addResourceReference:isWrite:` | `0x1807E` | `c28@0:8@16c24` | `req:MTLCommandBufferSPI` |
| `addResourcePageOff:` | `0x18114` | `c24@0:8@16` | — |
| `addHeapReference:` | `0x1816C` | `c24@0:8@16` | — |
| `addResourceMetadataReference:` | `0x18184` | `c24@0:8@16` | — |
| `addStateReference:` | `0x1819C` | `c24@0:8@16` | — |
| `addFenceReference:` | `0x1821C` | `c24@0:8@16` | — |
| `endCurrentChunk` | `0x182E1` | `v16@0:8` | — |
| `getBufferBytes:alignment:poolType:buffer:offset:` | `0x183BA` | `^v52@0:8Q16Q24i32^@36^Q44` | — |
| `getBufferBytes:alignment:buffer:offset:` | `0x183D3` | `^v48@0:8Q16Q24^@32^Q40` | — |
| `split` | `0x184EE` | `v16@0:8` | — |
| `allocKernelCommand:` | `0x18590` | `^v24@0:8Q16` | — |
| `insertCommandExec` | `0x1868F` | `v16@0:8` | — |
| `getCommandBufferBytes:` | `0x18783` | `^v24@0:8Q16` | — |
| `beginContinuation` | `0x189F2` | `v16@0:8` | — |
| `merge:` | `0x18A10` | `v24@0:8@16` | — |
| `getNextTraceID` | `0x18C20` | `Q16@0:8` | — |
| `.cxx_destruct` / `.cxx_construct` | `0x18C48` / `0x18C6C` | `v16@0:8` / `@16@0:8` | — |

**`commit`、`waitUntilCompleted`、`waitUntilScheduled`、`addCompletedHandler:`、`addScheduledHandler:`、`enqueue`、`presentDrawable:`、`status`、`error`、`label`/`setLabel:`、`pushDebugGroup:`/`popDebugGroup` 全部不覆写**，由 `MTLIOAccelCommandBuffer` / `_MTLCommandBuffer` 提供。与 `20-OBJC-DEVICE.md` 第 8.4 节的判定一致：这些方法在基类里只打 trace，不碰 user client。`KNOWN`

APV 覆写的是**后端行为**（encoder 工厂、resource 引用登记、命令字节分配、chunk 切分），不是生命周期。这正是 `20-OBJC-DEVICE.md` 第 8.4 节预测的形状。

### 6.4 function 层：没有 library 类，function 是个"容器"

`KNOWN`。`AppleParavirtContainerFunction <- NSObject`，适配 `MTLFunction` + `PGSerializerFunction`。

| selector | RVA | encoding | 协议 |
|---|---|---|---|
| `initWithDevice:functionType:functionRef:` | `0x2F66` | `@36@0:8@16Q24I32` | — |
| `dealloc` | `0x2FCF` | `v16@0:8` | — |
| `functionRef` | `0x3049` | `I16@0:8` | `req:PGSerializerFunction` |
| `device` | `0x3052` | `@16@0:8` | `req:MTLFunction` |
| `functionType` | `0x305C` | `Q16@0:8` | `req:MTLFunction` |
| `label` | `0x3066` | `@16@0:8` | `req:MTLFunction` |
| `setLabel:` | `0x307A` | `v24@0:8@16` | `req:MTLFunction` |
| `name` | `0x30BB` | `@16@0:8` | `req:MTLFunction` |
| `options` | `0x3089` | `Q16@0:8` | `req:MTLFunction` |
| `vertexAttributes` | `0x3093` | `@16@0:8` | `req:MTLFunction` |
| `stageInputAttributes` | `0x309D` | `@16@0:8` | `req:MTLFunction` |
| `patchType` | `0x30A7` | `Q16@0:8` | `req:MTLFunction` |
| `patchControlPointCount` | `0x30B1` | `q16@0:8` | `req:MTLFunction` |
| `functionConstantsDictionary` | `0x30C5` | `@16@0:8` | `req:MTLFunction` |
| `newArgumentEncoderWithBufferIndex:` | `0x3019` | `@24@0:8Q16` | `req:MTLFunction` |
| `newArgumentEncoderWithBufferIndex:reflection:` | `0x3031` | `@32@0:8Q16^@24` | `req:MTLFunction` |

14 / 13 required 已覆盖（`MTLFunction` 13 required，此处 14 条带协议标记是因为含 `NSObject` 协议的 `device` 重名计入一次）。

**关键区分**：这个类**不是** Metal 交给应用的 `MTLFunction`。应用拿到的是 `_MTLFunction`（Metal.framework 从 metallib 解析出来的那个）。`AppleParavirtContainerFunction` 是驱动内部的"编译后函数"句柄，由 `AppleParavirtFunctionVariant.function` 持有，适配 `MTLFunction` 只是为了能被 pipeline descriptor 当成 function 使用。

**本项目对应的决定**：和 APV 一样建一个内部 function 容器类即可，**不要试图替换 `_MTLLibrary` / `_MTLFunction`**。`INFERRED`

### 6.5 resource 层：APV 走 `MTLIOAccelResource`，本项目不能照抄

`KNOWN`。`AppleParavirtBuffer` / `AppleParavirtTexture` / `AppleParavirtPooledBuffer` 全部继承 `MTLIOAccel*`，并通过导入的 ivar 偏移符号访问基类字段：`_OBJC_IVAR_$_MTLIOAccelResource._res`、`_OBJC_IVAR_$_MTLIOAccelTexture._buffer` / `._parentRelativeLevel` / `._sampleCount`、`_OBJC_IVAR_$_MTLIOAccelHeap._resource`。即 **APV 真的用 `IOAccelResourceCreate` 建资源**（调用点在基类里，`S-APV` 自己只导入了 `IOAccelResourceGetClientSharedPrivate` / `IOAccelResourceListAddResource` / `IOAccelResourceListMergeLists`）。

`AppleParavirtPooledBuffer` 的 init 把这条路径暴露得最清楚：

```
-[AppleParavirtPooledBuffer initWithDevice:options:args:argsSize:]   S-APV +0x1900D
encoding: @44@0:8@16Q24^{IOAccelNewResourceArgs={IOAccelNewResourceData=
            IISSSSQQCCCCIQQQ(?={?=QQQQI}{?=II[3Q]}{?=IIII[2Q]}{?=II[3Q]})}}32I40
```

这给出了 `IOAccelNewResourceArgs` / `IOAccelNewResourceData` 的精确字段序列（`20-OBJC-DEVICE.md` 第 7.6 节的 type-6 selector `0` 入参），由 `12-KERNEL-IOSURFACE.md` 接手。`KNOWN`

**本项目保持 `20-OBJC-DEVICE.md` 第 8.5 节的决定不变：resource 类继承 `_MTLResource` 子树，不走 `MTLIOAccelResource`。** APV 在这里不是正确参照，因为它真有一个宿主来分配显存。`INFERRED`

`AppleParavirtBuffer` 的 18 条与 `AppleParavirtTexture` 的 25 条见附录 A.4 / A.5。两者的 `serializerResourceRef` + `shouldSyncInBlit` + `bufferRef`/`textureRef` 是 `PGSerializerResource` / `PGSerializerBuffer` / `PGSerializerTexture` 协议的全部要求（各 2 条 required），其余是 `MTLBuffer` / `MTLTexture` / `MTLResourceSPI` 的方法与 APV 私有的 `init*`。

## 7. 优先级 3.6：全量协议表（144 个）

`KNOWN`。协议名与继承关系取自 `S-DUMP` 的 `@protocol` 头行；required / optional / property 计数取自 `S-METAL` `__objc_protolist` 的 `protocol_t` 四个 method list 与 `instanceProperties`。两者的方法总数逐协议一致（见第 0.2 节）。

`S-DUMP` 行号可直接定位到 `analysis/idb/macos26-25G325-x86_64-frameworks/metal-objc.json`（UTF-16LE）。该文件只含 `S-METAL` 自己发射定义的 144 个协议；第 0.3 节列出的 15 个协议不在其中，它们的定义副本在 `S-APV` 里，计数见第 7.1 节。

| 协议 | 继承 | req 实例 | req 类 | opt 实例 | opt 类 | property | `S-DUMP` 行 |
|---|---|---|---|---|---|---|---|
| `MTL4Archive` | `NSObject` | 7 | 0 | 0 | 0 | 1 | 1 |
| `MTL4ArchiveGGDSPI` | `MTL4ArchiveSPI` | 4 | 0 | 0 | 0 | 0 | 20 |
| `MTL4ArchiveSPI` | `MTL4Archive` | 0 | 0 | 0 | 0 | 0 | 34 |
| `MTL4ArgumentTable` | `NSObject` | 7 | 0 | 0 | 0 | 2 | 42 |
| `MTL4ArgumentTableGGDSPI` | `MTL4ArgumentTableSPI` | 5 | 0 | 0 | 0 | 0 | 62 |
| `MTL4ArgumentTableSPI` | `MTL4ArgumentTable` | 0 | 0 | 0 | 0 | 0 | 77 |
| `MTL4BinaryFunction` | `NSObject` | 2 | 0 | 0 | 0 | 2 | 85 |
| `MTL4BinaryFunctionGGDSPI` | `MTL4BinaryFunctionSPI` | 0 | 0 | 0 | 0 | 0 | 100 |
| `MTL4BinaryFunctionSPI` | `MTL4BinaryFunction` | 4 | 0 | 0 | 0 | 3 | 108 |
| `MTL4CommandAllocator` | `NSObject` | 4 | 0 | 0 | 0 | 2 | 126 |
| `MTL4CommandAllocatorGGDSPI` | `MTL4CommandAllocatorSPI` | 1 | 0 | 0 | 0 | 0 | 143 |
| `MTL4CommandAllocatorSPI` | `MTL4CommandAllocator` | 0 | 0 | 0 | 0 | 0 | 154 |
| `MTL4CommandBuffer` | `NSObject` | 16 | 0 | 0 | 0 | 2 | 162 |
| `MTL4CommandBufferGGDSPI` | `MTL4CommandBufferSPI` | 7 | 0 | 0 | 0 | 3 | 191 |
| `MTL4CommandBufferSPI` | `MTL4CommandBuffer` | 4 | 0 | 0 | 0 | 1 | 212 |
| `MTL4CommandEncoder` | `NSObject` | 12 | 0 | 0 | 0 | 2 | 228 |
| `MTL4CommandEncoderGGDSPI` | `MTL4CommandEncoderSPI` | 4 | 0 | 0 | 0 | 1 | 253 |
| `MTL4CommandEncoderSPI` | `MTL4CommandEncoder` | 4 | 0 | 0 | 0 | 0 | 269 |
| `MTL4CommandQueue` | `NSObject` | 16 | 0 | 0 | 0 | 2 | 283 |
| `MTL4CommandQueueGGDSPI` | `MTL4CommandQueueSPI` | 3 | 0 | 0 | 0 | 0 | 312 |
| `MTL4CommandQueueSPI` | `MTL4CommandQueue` | 2 | 0 | 0 | 0 | 2 | 325 |
| `MTL4CommitFeedback` | `NSObject` | 3 | 0 | 0 | 0 | 3 | 340 |
| `MTL4CommitFeedbackGGDPrivate` | `MTL4CommitFeedback` | 1 | 0 | 0 | 0 | 1 | 357 |
| `MTL4Compiler` | `NSObject` | 23 | 0 | 0 | 0 | 3 | 370 |
| `MTL4CompilerGGDSPI` | `MTL4CompilerSPI` | 4 | 0 | 0 | 0 | 2 | 407 |
| `MTL4CompilerSPI` | `MTL4Compiler` | 1 | 0 | 0 | 0 | 0 | 424 |
| `MTL4CompilerTask` | `NSObject` | 3 | 0 | 0 | 0 | 2 | 435 |
| `MTL4CompilerTaskGGDSPI` | `MTL4CompilerTaskSPI` | 1 | 0 | 0 | 0 | 0 | 451 |
| `MTL4CompilerTaskSPI` | `MTL4CompilerTask` | 0 | 0 | 0 | 0 | 0 | 462 |
| `MTL4ComputeCommandEncoder` | `MTL4CommandEncoder` | 36 | 0 | 0 | 0 | 0 | 470 |
| `MTL4ComputeCommandEncoderGGDSPI` | `MTL4ComputeCommandEncoderSPI`, `MTL4CommandEncoderGGDSPI` | 21 | 0 | 0 | 0 | 0 | 516 |
| `MTL4ComputeCommandEncoderSPI` | `MTL4ComputeCommandEncoder`, `MTL4CommandEncoderSPI` | 16 | 0 | 0 | 0 | 0 | 547 |
| `MTL4CounterHeap` | `NSObject` | 6 | 0 | 0 | 0 | 3 | 573 |
| `MTL4CounterHeapGGDSPI` | `MTL4CounterHeap` | 1 | 0 | 0 | 0 | 0 | 593 |
| `MTL4MachineLearningCommandEncoder` | `MTL4CommandEncoder` | 3 | 0 | 0 | 0 | 0 | 604 |
| `MTL4MachineLearningCommandEncoderGGDSPI` | `MTL4MachineLearningCommandEncoder`, `MTL4CommandEncoderGGDSPI` | 3 | 0 | 0 | 0 | 0 | 617 |
| `MTL4MachineLearningPipelineState` | `MTLAllocation`, `NSObject` | 4 | 0 | 0 | 0 | 4 | 630 |
| `MTL4MachineLearningPipelineStateGGDSPI` | `MTL4MachineLearningPipelineStateSPI` | 3 | 0 | 0 | 0 | 0 | 649 |
| `MTL4MachineLearningPipelineStateSPI` | `MTL4MachineLearningPipelineState` | 0 | 0 | 0 | 0 | 0 | 662 |
| `MTL4PipelineDataSetSerializer` | `NSObject` | 2 | 0 | 0 | 0 | 0 | 670 |
| `MTL4PipelineDataSetSerializerGGDSPI` | `MTL4PipelineDataSetSerializerSPI` | 2 | 0 | 0 | 0 | 0 | 682 |
| `MTL4PipelineDataSetSerializerSPI` | `MTL4PipelineDataSetSerializer` | 0 | 0 | 0 | 0 | 0 | 694 |
| `MTL4RenderCommandEncoder` | `MTL4CommandEncoder` | 41 | 0 | 0 | 0 | 2 | 702 |
| `MTL4RenderCommandEncoderGGDSPI` | `MTL4RenderCommandEncoderSPI`, `MTL4CommandEncoderGGDSPI` | 6 | 0 | 0 | 0 | 0 | 756 |
| `MTL4RenderCommandEncoderSPI` | `MTL4RenderCommandEncoder`, `MTL4CommandEncoderSPI` | 2 | 0 | 0 | 0 | 0 | 772 |
| `MTLAccelerationStructure` | `MTLResource` | 2 | 0 | 0 | 0 | 2 | 784 |
| `MTLAccelerationStructureCommandEncoder` | `MTLCommandEncoder` | 14 | 0 | 0 | 0 | 0 | 799 |
| `MTLAccelerationStructureCommandEncoderSPI` | `MTLCommandEncoderSPI`, `MTLAccelerationStructureCommandEncoder` | 12 | 0 | 8 | 0 | 0 | 823 |
| `MTLAccelerationStructureSPI` | `MTLAccelerationStructure` | 6 | 0 | 2 | 0 | 7 | 855 |
| `MTLAllocation` | `NSObject` | 1 | 0 | 0 | 0 | 1 | 883 |
| `MTLArgumentCompat` | `NSObject` | 18 | 0 | 0 | 0 | 18 | 896 |
| `MTLArgumentEncoder` | `NSObject` | 28 | 0 | 0 | 0 | 4 | 943 |
| `MTLBinaryArchive` | `NSObject` | 10 | 0 | 0 | 0 | 2 | 986 |
| `MTLBinaryArchiveSPI` | `MTLBinaryArchive` | 17 | 0 | 0 | 0 | 2 | 1009 |
| `MTLBinding` | `NSObject` | 6 | 0 | 0 | 0 | 6 | 1039 |
| `MTLBuffer` | `MTLResource` | 11 | 0 | 0 | 0 | 4 | 1062 |
| `MTLBufferBinding` | `MTLBinding` | 5 | 0 | 0 | 0 | 5 | 1088 |
| `MTLCaptureScope` | `NSObject` | 7 | 0 | 0 | 0 | 4 | 1109 |
| `MTLCommandBuffer` | `NSObject` | 39 | 0 | 0 | 0 | 12 | 1131 |
| `MTLCommandBufferEncoderInfo` | `NSObject` | 3 | 0 | 0 | 0 | 3 | 1193 |
| `MTLCommandEncoder` | `NSObject` | 8 | 0 | 0 | 0 | 2 | 1210 |
| `MTLCommandEncoderSPI` | `MTLCommandEncoder` | 2 | 0 | 0 | 0 | 0 | 1231 |
| `MTLComputePipelineState` | `MTLAllocation`, `NSObject` | 18 | 0 | 0 | 0 | 10 | 1243 |
| `MTLCounter` | `NSObject` | 1 | 0 | 0 | 0 | 1 | 1282 |
| `MTLCounterSet` | `NSObject` | 2 | 0 | 0 | 0 | 2 | 1295 |
| `MTLDebugCommandEncoder` | `MTLCommandEncoderSPI` | 4 | 0 | 13 | 0 | 0 | 1310 |
| `MTLDepthStencilState` | `NSObject` | 3 | 0 | 0 | 0 | 3 | 1339 |
| `MTLDepthStencilStateSPI` | `MTLDepthStencilState` | 6 | 0 | 0 | 0 | 6 | 1356 |
| `MTLDevice` | `NSObject` | 137 | 0 | 2 | 0 | 43 | 1379 |
| `MTLDeviceSPI` | `MTLDevice` | 427 | 0 | 80 | 0 | 347 | 1574 |
| `MTLDrawable` | `NSObject` | 6 | 0 | 0 | 0 | 2 | 2441 |
| `MTLDrawableSPI` | `MTLDrawable` | 2 | 0 | 3 | 0 | 1 | 2460 |
| `MTLDynamicLibrary` | `NSObject` | 5 | 0 | 0 | 0 | 3 | 2479 |
| `MTLDynamicLibrarySPI` | `MTLDynamicLibrary` | 19 | 0 | 0 | 0 | 13 | 2498 |
| `MTLEvent` | `NSObject` | 3 | 0 | 0 | 0 | 2 | 2541 |
| `MTLEventSPI` | `MTLEvent` | 3 | 0 | 0 | 0 | 2 | 2557 |
| `MTLFence` | `NSObject` | 3 | 0 | 0 | 0 | 2 | 2573 |
| `MTLFenceSPI` | `MTLFence` | 0 | 0 | 0 | 0 | 0 | 2589 |
| `MTLFunction` | `NSObject` | 13 | 0 | 0 | 0 | 10 | 2597 |
| `MTLFunctionConstantSPI` | — | 2 | 0 | 0 | 0 | 0 | 2631 |
| `MTLFunctionHandle` | `NSObject` | 4 | 0 | 0 | 0 | 4 | 2643 |
| `MTLFunctionHandleSPI` | `MTLFunctionHandle` | 1 | 0 | 0 | 0 | 1 | 2662 |
| `MTLFunctionLogDebugLocation` | `NSObject` | 4 | 0 | 0 | 0 | 4 | 2675 |
| `MTLFunctionSPI` | `MTLFunction` | 23 | 0 | 0 | 0 | 12 | 2694 |
| `MTLFunctionStitchingAttribute` | `NSObject` | 0 | 0 | 0 | 0 | 0 | 2740 |
| `MTLFunctionStitchingInputBuiltin` | `MTLFunctionStitchingNode` | 0 | 0 | 0 | 0 | 0 | 2748 |
| `MTLFunctionStitchingInputNodeSPI` | `MTLFunctionStitchingNode` | 3 | 0 | 0 | 0 | 1 | 2756 |
| `MTLFunctionStitchingNode` | `NSObject`, `NSCopying` | 0 | 0 | 0 | 0 | 0 | 2771 |
| `MTLIOCommandBuffer` | `NSObject` | 18 | 0 | 0 | 0 | 3 | 2779 |
| `MTLIOCommandBufferSPI` | `MTLIOCommandBuffer` | 4 | 0 | 0 | 0 | 1 | 2811 |
| `MTLIOCommandQueue` | `NSObject` | 5 | 0 | 0 | 0 | 1 | 2827 |
| `MTLIOCommandQueueSPI` | `MTLIOCommandQueue` | 3 | 0 | 0 | 0 | 2 | 2844 |
| `MTLIOFileHandle` | `NSObject` | 2 | 0 | 0 | 0 | 1 | 2860 |
| `MTLIOHandleSPI` | `MTLIOFileHandle` | 8 | 0 | 1 | 0 | 2 | 2874 |
| `MTLIOScratchBuffer` | `NSObject` | 1 | 0 | 0 | 0 | 1 | 2898 |
| `MTLIOScratchBufferAllocator` | `NSObject` | 1 | 0 | 0 | 0 | 0 | 2911 |
| `MTLIndirectComputeCommand` | `NSObject` | 11 | 0 | 0 | 0 | 0 | 2922 |
| `MTLIndirectComputeCommandSPI` | `MTLIndirectComputeCommand` | 12 | 0 | 1 | 0 | 0 | 2943 |
| `MTLIndirectRenderCommand` | `NSObject` | 22 | 0 | 0 | 0 | 0 | 2968 |
| `MTLIndirectRenderCommandSPI` | `MTLIndirectRenderCommand` | 45 | 0 | 1 | 0 | 0 | 3000 |
| `MTLIntersectionFunctionTable` | `MTLResource` | 11 | 0 | 0 | 0 | 1 | 3058 |
| `MTLIntersectionFunctionTableSPI` | `MTLIntersectionFunctionTable` | 2 | 0 | 6 | 0 | 5 | 3081 |
| `MTLLibrary` | `NSObject` | 14 | 0 | 0 | 0 | 5 | 3107 |
| `MTLLibrarySPI` | `MTLLibrary` | 13 | 0 | 0 | 0 | 5 | 3137 |
| `MTLLogState` | `NSObject` | 1 | 0 | 0 | 0 | 0 | 3166 |
| `MTLObjectPayloadBinding` | `MTLBinding` | 2 | 0 | 0 | 0 | 2 | 3177 |
| `MTLParallelRenderCommandEncoder` | `MTLCommandEncoder` | 7 | 0 | 0 | 0 | 0 | 3192 |
| `MTLPipelineCache` | `NSObject` | 0 | 0 | 0 | 0 | 0 | 3209 |
| `MTLPipelineLibrary` | `NSObject` | 0 | 0 | 0 | 0 | 0 | 3217 |
| `MTLPipelineLibrarySPI` | `MTLPipelineLibrary` | 13 | 0 | 0 | 0 | 7 | 3225 |
| `MTLPipelineStateBinary` | — | 2 | 0 | 1 | 0 | 3 | 3256 |
| `MTLProgramAddressTable` | — | 3 | 0 | 0 | 0 | 3 | 3275 |
| `MTLProgramAddressTableMappedBinary` | — | 4 | 0 | 0 | 0 | 4 | 3292 |
| `MTLRasterizationRateMap` | `NSObject` | 10 | 0 | 0 | 0 | 6 | 3311 |
| `MTLRasterizationRateMapDescriptorSPI` | — | 11 | 0 | 0 | 0 | 4 | 3338 |
| `MTLRasterizationRateMapSPI` | `MTLRasterizationRateMap` | 4 | 0 | 0 | 0 | 2 | 3364 |
| `MTLRelocation` | `NSObject` | 1 | 0 | 0 | 0 | 1 | 3381 |
| `MTLRenderPipelineState` | `MTLAllocation`, `NSObject` | 26 | 0 | 0 | 0 | 17 | 3394 |
| `MTLResource` | `MTLAllocation` | 14 | 0 | 0 | 0 | 9 | 3448 |
| `MTLResourceSPI` | `MTLResource` | 12 | 0 | 1 | 0 | 4 | 3482 |
| `MTLResourceViewPool` | `NSObject` | 5 | 0 | 0 | 0 | 4 | 3512 |
| `MTLResourceViewPoolGGDSPI` | `MTLResourceViewPoolSPI` | 0 | 0 | 0 | 0 | 0 | 3532 |
| `MTLResourceViewPoolSPI` | `MTLResourceViewPool` | 0 | 0 | 0 | 0 | 0 | 3540 |
| `MTLSamplerState` | `NSObject` | 3 | 0 | 0 | 0 | 3 | 3548 |
| `MTLSamplerStateSPI` | `MTLSamplerState` | 1 | 0 | 4 | 0 | 5 | 3565 |
| `MTLSharedEvent` | `MTLEvent` | 5 | 0 | 0 | 0 | 1 | 3588 |
| `MTLSharedEventSPI` | `MTLSharedEvent` | 2 | 0 | 0 | 0 | 2 | 3605 |
| `MTLTensor` | `MTLResource` | 9 | 0 | 0 | 0 | 7 | 3620 |
| `MTLTensorBinding` | `MTLBinding` | 3 | 0 | 0 | 0 | 3 | 3647 |
| `MTLTensorSPI` | `MTLTensor`, `MTLResourceSPI` | 9 | 0 | 0 | 0 | 3 | 3664 |
| `MTLTexture` | `MTLResource` | 36 | 0 | 3 | 0 | 29 | 3687 |
| `MTLTextureBinding` | `MTLBinding` | 4 | 0 | 0 | 0 | 4 | 3768 |
| `MTLTextureImplementation` | `MTLTextureSPI` | 1 | 0 | 0 | 0 | 0 | 3787 |
| `MTLTextureSPI` | `MTLTexture`, `MTLResourceSPI` | 13 | 0 | 10 | 0 | 16 | 3798 |
| `MTLTextureViewPool` | `MTLResourceViewPool` | 3 | 0 | 0 | 0 | 0 | 3850 |
| `MTLTextureViewPoolGGDSPI` | `MTLTextureViewPoolSPI` | 0 | 0 | 0 | 0 | 0 | 3863 |
| `MTLTextureViewPoolSPI` | `MTLTextureViewPool` | 0 | 0 | 0 | 0 | 0 | 3871 |
| `MTLThreadgroupBinding` | `MTLBinding` | 2 | 0 | 0 | 0 | 2 | 3879 |
| `MTLVisibleFunctionTable` | `MTLResource` | 3 | 0 | 0 | 0 | 1 | 3894 |
| `MTLVisibleFunctionTableSPI` | `MTLVisibleFunctionTable` | 9 | 0 | 6 | 0 | 6 | 3909 |
| `NSCoding` | — | 2 | 0 | 0 | 0 | 0 | 3943 |
| `NSCopying` | — | 1 | 0 | 0 | 0 | 0 | 3955 |
| `NSObject` | — | 19 | 0 | 1 | 0 | 4 | 3966 |
| `NSSecureCoding` | `NSCoding` | 0 | 1 | 0 | 0 | 0 | 4003 |

### 7.1 `S-METAL` 不拥有、由 `S-APV` 提供定义的 15 个协议

`KNOWN`。计数取自 `S-APV` `__objc_protolist`。这些协议在 `S-DUMP` 里没有条目。

| 协议 | 继承 | req 实例 | opt 实例 |
|---|---|---|---|
| `MTLBlitCommandEncoder` | `MTLCommandEncoder` | 24 | 2 |
| `MTLBlitCommandEncoderSPI` | `MTLCommandEncoderSPI`, `MTLBlitCommandEncoder` | 10 | 0 |
| `MTLBufferSPI` | `MTLResourceSPI`, `MTLBuffer` | 5 | 8 |
| `MTLCommandBufferSPI` | `MTLCommandBuffer` | 21 | 36 |
| `MTLCommandQueue` | `NSObject` | 11 | 0 |
| `MTLCommandQueueSPI` | `MTLCommandQueue` | 25 | 22 |
| `MTLComputeCommandEncoder` | `MTLCommandEncoder` | 39 | 0 |
| `MTLComputeCommandEncoderSPI` | `MTLCommandEncoderSPI`, `MTLComputeCommandEncoder` | 7 | 19 |
| `MTLComputePipelineStateSPI` | `MTLComputePipelineState`, `MTLPipelineStateWithProgramAddressTable` | 17 | 2 |
| `MTLHeap` | `MTLAllocation` | 21 | 0 |
| `MTLParallelRenderCommandEncoderSPI` | `MTLCommandEncoderSPI`, `MTLParallelRenderCommandEncoder` | 2 | 1 |
| `MTLPipelineStateWithProgramAddressTable` | — | 1 | 0 |
| `MTLRenderCommandEncoder` | `MTLCommandEncoder` | 131 | 0 |
| `MTLRenderCommandEncoderSPI` | `MTLCommandEncoderSPI`, `MTLRenderCommandEncoder` | 37 | 33 |
| `MTLRenderPipelineStateSPI` | `MTLRenderPipelineState`, `MTLPipelineStateWithProgramAddressTable` | 85 | 5 |

### 7.2 APV 自建协议（`PGSerializer*` 14 个 + `AppleParavirtState`）

`KNOWN`。`S-APV` 私有协议，本项目不需要实现，列出仅为解释第 3 节的继承树。

| 协议 | 继承 | req 实例 | opt 实例 |
|---|---|---|---|
| `AppleParavirtState` | `NSObject` | 1 | 0 |
| `PGSerializerAllocator` | `NSObject` | 1 | 0 |
| `PGSerializerBuffer` | `PGSerializerResource` | 2 | 0 |
| `PGSerializerCommandStream` | `NSObject` | 11 | 2 |
| `PGSerializerComputePipelineState` | `PGSerializerState` | 1 | 1 |
| `PGSerializerDepthStencilState` | `PGSerializerState` | 1 | 0 |
| `PGSerializerFence` | `PGSerializerState` | 1 | 0 |
| `PGSerializerFunction` | `PGSerializerState` | 1 | 0 |
| `PGSerializerHeap` | `PGSerializerResource` | 1 | 0 |
| `PGSerializerObjectRefAllocator` | `NSObject` | 1 | 0 |
| `PGSerializerRenderPipelineState` | `PGSerializerState` | 1 | 1 |
| `PGSerializerResource` | `NSObject` | 2 | 0 |
| `PGSerializerSamplerState` | `PGSerializerState` | 1 | 0 |
| `PGSerializerState` | `NSObject` | 0 | 0 |
| `PGSerializerTexture` | `PGSerializerResource` | 2 | 0 |


## 8. 优先级 3.6 / 3.7：第一版必须实现的协议逐方法清单

### 8.0 本节的范围与取法

第一版必须实现的协议（任务给定）：`MTLDevice`、`MTLDeviceSPI`、`MTLCommandQueue`、`MTLCommandBuffer`、`MTLRenderCommandEncoder`、`MTLBuffer`、`MTLTexture`、`MTLLibrary`、`MTLFunction`、`MTLRenderPipelineState`、`MTLDepthStencilState`、`MTLSamplerState`。它们的继承闭包还拉进 `MTLResource`、`MTLResourceSPI`、`MTLAllocation`、`MTLCommandEncoder`、`NSObject`。

encoding 来源与可信度：

- 协议在 `S-METAL` `__objc_protolist` 里的 → 方法名取 `S-DUMP`、encoding 取 `S-METAL` 的 `protocol_t.instanceMethods` / `optionalInstanceMethods`，按第 0.2 节验证过的同序配对。
- 协议只在 `S-APV` 里的（`MTLCommandQueue`、`MTLRenderCommandEncoder` 等 15 个，见第 0.3 节）→ 方法名与 encoding 同时取 `S-APV`，两者在同一条 method record 里，无需配对。
- 两类来源在 20 个共有协议上**逐项一致，差异 0 项**（第 0.2 节）。

本节按任务要求分两层：

- **8.1 是交集层**（优先级 3.7）：APV 实际实现了的那些协议方法，带精确 encoding 与 APV 的 RVA。这是"最少要实现什么"的直接答案。
- **8.2 起是全量层**（优先级 3.6）：各协议自己声明的全部方法与 encoding。`MTLDeviceSPI` 的 507 条不逐条抄进本文（`S-DUMP` 第 1574–2440 行已有逐条方法名，本文给出分类普查与交集），其余协议全量列出。

> 注意第 4 节开头的提醒：**pipeline 创建链的 5 个 selector 不在任何协议里**，按本节清单实现会漏。必须另外照第 2.4 节实现。

### 8.1 交集：APV 实际实现了的协议方法（优先级 3.7）

`KNOWN`。取法：对每个协议 P，先找出 `S-APV` 中协议闭包含 P 的类，再把这些类的 IMP 集与 **P 自己声明的**（不含继承来的）方法集相交。RVA 是 `S-APV` 的 IMP 地址。

| 协议 | 自己声明的方法数 | APV 实现 | 适配该协议的 APV 类 |
|---|---|---|---|
| `MTLDevice` | 139 | **27** | `AppleParavirtDevice` |
| `MTLDeviceSPI` | 507 | **28** | `AppleParavirtDevice` |
| `MTLCommandQueue` | 11 | **2** | `AppleParavirtCommandQueue` |
| `MTLCommandBuffer` | 39 | **8** | `AppleParavirtCommandBuffer` |
| `MTLCommandEncoder` | 8 | **1** | `PGSerializerBlitCommandEncoder`, `PGSerializerParallelRenderCommandEncoder`, `PGSerializerCommandEncoder`, `PGSerializerRenderCommandEncoder`, `PGSerializerComputeCommandEncoder` |
| `MTLRenderCommandEncoder` | 131 | **102** | `PGSerializerRenderCommandEncoder` |
| `MTLBuffer` | 11 | **2** | `AppleParavirtBuffer` |
| `MTLResource` | 14 | **2** | `AppleParavirtTexture`, `AppleParavirtBuffer` |
| `MTLResourceSPI` | 13 | **6** | `AppleParavirtTexture`, `AppleParavirtBuffer` |
| `MTLAllocation` | 1 | **0** | `AppleParavirtTexture`, `AppleParavirtRenderPipelineState`, `AppleParavirtComputePipelineState`, `AppleParavirtBuffer`, `AppleParavirtHeap` |
| `MTLTexture` | 39 | **5** | `AppleParavirtTexture` |
| `MTLLibrary` | 14 | **0** | **无** |
| `MTLFunction` | 13 | **13** | `AppleParavirtContainerFunction` |
| `MTLRenderPipelineState` | 26 | **0** | `AppleParavirtRenderPipelineState` |
| `MTLDepthStencilState` | 3 | **0** | `AppleParavirtDepthStencilState` |
| `MTLSamplerState` | 3 | **0** | `AppleParavirtSamplerState` |

三条读法：

1. **`MTLLibrary` 的适配者数为 0**。`S-APV` 的 28 个类里没有任何一个声明 `MTLLibrary`，14 条 required 一条未实现。这是第 2 节结论的第二道独立证据。
2. **`MTLRenderPipelineState`、`MTLDepthStencilState`、`MTLSamplerState` 的实现数均为 0**。所有 state 对象的对外协议方法全部由 `_MTL*` 抽象基类提供；驱动只提供 SPI 层与自建方法（第 6.1 节）。
3. **`MTLRenderCommandEncoder` 实现 102 / 131**。这是全家族里唯一需要大量写代码的协议。
4. `MTLDevice` 的 27 与 `MTLDeviceSPI` 的 28 **不能相加**：`MTLDeviceSPI` 重复声明了 `MTLDevice` 的 22 个方法（其中 APV 实现了 6 个：`newCommandQueueWithDescriptor:`、`newTextureWithDescriptor:iosurface:plane:`、`supportsDynamicLibraries`、`supportsRenderDynamicLibraries`、`supportsFunctionPointers`、`supportsFunctionPointersFromRender`）。去重后是 **27 + 28 − 6 = 49**，与第 4 节的数字一致。`KNOWN`

#### 8.1.1 `MTLDevice` — APV 实现 27 条

| selector | req/opt | x86_64 type encoding | APV |
|---|---|---|---|
| `newBufferWithBytes:length:options:` | req | `@40@0:8r^v16Q24Q32` | `AppleParavirtDevice` +0xA943 |
| `newBufferWithLength:options:` | req | `@32@0:8Q16Q24` | `AppleParavirtDevice` +0xAA3E |
| `newSamplerStateWithDescriptor:` | req | `@24@0:8@16` | `AppleParavirtDevice` +0xAAC7 |
| `newTextureWithDescriptor:` | req | `@24@0:8@16` | `AppleParavirtDevice` +0xAAFA |
| `newTextureWithDescriptor:iosurface:plane:` | req | `@40@0:8@16^{__IOSurface=}24Q32` | `AppleParavirtDevice` +0xAB4B |
| `newSharedTextureWithDescriptor:` | req | `@24@0:8@16` | `AppleParavirtDevice` +0xB166 |
| `areProgrammableSamplePositionsSupported` | req | `c16@0:8` | `AppleParavirtDevice` +0xB088 |
| `heapBufferSizeAndAlignWithLength:options:` | req | `{?=QQ}32@0:8Q16Q24` | `AppleParavirtDevice` +0xA927 |
| `heapTextureSizeAndAlignWithDescriptor:` | req | `{?=QQ}24@0:8@16` | `AppleParavirtDevice` +0xA931 |
| `isDepth24Stencil8PixelFormatSupported` | req | `c16@0:8` | `AppleParavirtDevice` +0xB0AD |
| `maxThreadgroupMemoryLength` | req | `Q16@0:8` | `AppleParavirtDevice` +0xB0E7 |
| `maxThreadsPerThreadgroup` | req | `{?=QQQ}16@0:8` | `AppleParavirtDevice` +0xB0C4 |
| `minimumTextureBufferAlignmentForPixelFormat:` | req | `Q24@0:8Q16` | `AppleParavirtDevice` +0xA93B |
| `newBufferWithBytesNoCopy:length:options:deallocator:` | req | `@48@0:8^v16Q24Q32@?40` | `AppleParavirtDevice` +0xA9E6 |
| `newCommandQueueWithDescriptor:` | req | `@24@0:8@16` | `AppleParavirtDevice` +0xACCE |
| `newDepthStencilStateWithDescriptor:` | req | `@24@0:8@16` | `AppleParavirtDevice` +0xAA8C |
| `newFence` | req | `@16@0:8` | `AppleParavirtDevice` +0xB05A |
| `newHeapWithDescriptor:` | req | `@24@0:8@16` | `AppleParavirtDevice` +0xAABF |
| `newRenderPipelineStateWithTileDescriptor:options:completionHandler:` | req | `v40@0:8@16Q24@?32` | `AppleParavirtDevice` +0xB36F |
| `newRenderPipelineStateWithTileDescriptor:options:reflection:error:` | req | `@48@0:8@16Q24^@32^@40` | `AppleParavirtDevice` +0xB384 |
| `newSharedTextureWithHandle:` | req | `@24@0:8@16` | `AppleParavirtDevice` +0xB1B6 |
| `sparseTileSizeWithTextureType:pixelFormat:sampleCount:` | req | `{?=QQQ}40@0:8Q16Q24Q32` | `AppleParavirtDevice` +0xB39C |
| `sparseTileSizeWithTextureType:pixelFormat:sampleCount:sparsePageSize:` | req | `{?=QQQ}48@0:8Q16Q24Q32q40` | `AppleParavirtDevice` +0xB3D0 |
| `supportsDynamicLibraries` | req | `c16@0:8` | `AppleParavirtDevice` +0xB41C |
| `supportsFunctionPointers` | req | `c16@0:8` | `AppleParavirtDevice` +0xB434 |
| `supportsFunctionPointersFromRender` | req | `c16@0:8` | `AppleParavirtDevice` +0xB43C |
| `supportsRenderDynamicLibraries` | req | `c16@0:8` | `AppleParavirtDevice` +0xB42C |

#### 8.1.2 `MTLDeviceSPI` — APV 实现 28 条

| selector | req/opt | x86_64 type encoding | APV |
|---|---|---|---|
| `vendorName` | req | `@16@0:8` | `AppleParavirtDevice` +0xACA8 |
| `familyName` | req | `@16@0:8` | `AppleParavirtDevice` +0xAC4A |
| `newTextureWithDescriptor:iosurface:plane:` | req | `@40@0:8@16^{__IOSurface=}24Q32` | `AppleParavirtDevice` +0xAB4B |
| `productName` | req | `@16@0:8` | `AppleParavirtDevice` +0xAC6F |
| `doubleFPConfig` | req | `Q16@0:8` | `AppleParavirtDevice` +0xB46C |
| `featureProfile` | req | `Q16@0:8` | `AppleParavirtDevice` +0xACC3 |
| `halfFPConfig` | req | `Q16@0:8` | `AppleParavirtDevice` +0xB48E |
| `isMagicMipmapSupported` | req | `c16@0:8` | `AppleParavirtDevice` +0xB49F |
| `llvmVersion` | req | `i16@0:8` | `AppleParavirtDevice` +0xB04F |
| `metalAssertionsEnabled` | req | `c16@0:8` | `AppleParavirtDevice` +0xACB5 |
| `newCommandQueueWithDescriptor:` | req | `@24@0:8@16` | `AppleParavirtDevice` +0xACCE |
| `newIndirectCommandBufferWithDescriptor:maxCount:options:` | req | `@40@0:8@16Q24Q32` | `AppleParavirtDevice` +0xAC57 |
| `newIndirectComputeCommandEncoderWithBuffer:` | req | `@24@0:8@16` | `AppleParavirtDevice` +0xAC5F |
| `newIndirectRenderCommandEncoderWithBuffer:` | req | `@24@0:8@16` | `AppleParavirtDevice` +0xAC67 |
| `newVisibleFunctionTableWithDescriptor:` | req | `@24@0:8@16` | `AppleParavirtDevice` +0xB404 |
| `setMetalAssertionsEnabled:` | req | `v20@0:8c16` | `AppleParavirtDevice` +0xACBD |
| `singleFPConfig` | req | `Q16@0:8` | `AppleParavirtDevice` +0xB47D |
| `supportsArgumentBuffers` | req | `c16@0:8` | `AppleParavirtDevice` +0xB44C |
| `supportsBinaryArchives` | req | `c16@0:8` | `AppleParavirtDevice` +0xB444 |
| `supportsDynamicLibraries` | req | `c16@0:8` | `AppleParavirtDevice` +0xB41C |
| `supportsFunctionPointers` | req | `c16@0:8` | `AppleParavirtDevice` +0xB434 |
| `supportsFunctionPointersFromRender` | req | `c16@0:8` | `AppleParavirtDevice` +0xB43C |
| `supportsRenderDynamicLibraries` | req | `c16@0:8` | `AppleParavirtDevice` +0xB42C |
| `supportsResourceHeaps` | req | `c16@0:8` | `AppleParavirtDevice` +0xB454 |
| `supportsSampleCount:` | req | `c24@0:8Q16` | `AppleParavirtDevice` +0xAC7C |
| `supportsSharedTextureHandles` | req | `c16@0:8` | `AppleParavirtDevice` +0xB120 |
| `supportsStatefulDynamicLibraries` | req | `c16@0:8` | `AppleParavirtDevice` +0xB424 |
| `copyIOSurfaceSharedTextureProperties:` | opt | `@24@0:8@16` | `AppleParavirtDevice` +0xB206 |

#### 8.1.3 `MTLCommandQueue` — APV 实现 2 条

| selector | req/opt | x86_64 type encoding | APV |
|---|---|---|---|
| `commandBuffer` | req | `@16@0:8` | `AppleParavirtCommandQueue` +0xA25A |
| `commandBufferWithUnretainedReferences` | req | `@16@0:8` | `AppleParavirtCommandQueue` +0xA295 |

#### 8.1.4 `MTLCommandBuffer` — APV 实现 8 条

| selector | req/opt | x86_64 type encoding | APV |
|---|---|---|---|
| `blitCommandEncoder` | req | `@16@0:8` | `AppleParavirtCommandBuffer` +0x17CA6 |
| `renderCommandEncoderWithDescriptor:` | req | `@24@0:8@16` | `AppleParavirtCommandBuffer` +0x17FB6 |
| `computeCommandEncoderWithDispatchType:` | req | `@24@0:8Q16` | `AppleParavirtCommandBuffer` +0x17E0D |
| `blitCommandEncoderWithDescriptor:` | req | `@24@0:8@16` | `AppleParavirtCommandBuffer` +0x17D27 |
| `computeCommandEncoder` | req | `@16@0:8` | `AppleParavirtCommandBuffer` +0x17D8C |
| `computeCommandEncoderWithDescriptor:` | req | `@24@0:8@16` | `AppleParavirtCommandBuffer` +0x17EA1 |
| `parallelRenderCommandEncoderWithDescriptor:` | req | `@24@0:8@16` | `AppleParavirtCommandBuffer` +0x17F06 |
| `resourceStateCommandEncoder` | req | `@16@0:8` | `AppleParavirtCommandBuffer` +0x18066 |

#### 8.1.5 `MTLCommandEncoder` — APV 实现 1 条

| selector | req/opt | x86_64 type encoding | APV |
|---|---|---|---|
| `endEncoding` | req | `v16@0:8` | `PGSerializerParallelRenderCommandEncoder` +0x676F, `PGSerializerCommandEncoder` +0x9F53, `PGSerializerComputeCommandEncoder` +0x159EF |

#### 8.1.6 `MTLBuffer` — APV 实现 2 条

| selector | req/opt | x86_64 type encoding | APV |
|---|---|---|---|
| `contents` | req | `^v16@0:8` | `AppleParavirtBuffer` +0x157A0 |
| `newTextureWithDescriptor:offset:bytesPerRow:` | req | `@40@0:8@16Q24Q32` | `AppleParavirtBuffer` +0x1562B |

#### 8.1.7 `MTLResource` — APV 实现 2 条

| selector | req/opt | x86_64 type encoding | APV |
|---|---|---|---|
| `isAliasable` | req | `c16@0:8` | `AppleParavirtTexture` +0x8266, `AppleParavirtBuffer` +0x1561D |
| `makeAliasable` | req | `v16@0:8` | `AppleParavirtTexture` +0x826E, `AppleParavirtBuffer` +0x15625 |

#### 8.1.8 `MTLResourceSPI` — APV 实现 6 条

| selector | req/opt | x86_64 type encoding | APV |
|---|---|---|---|
| `doesAliasAllResources:count:` | req | `c32@0:8r^@16Q24` | `AppleParavirtTexture` +0x89A5, `AppleParavirtBuffer` +0x15750 |
| `doesAliasAnyResources:count:` | req | `c32@0:8r^@16Q24` | `AppleParavirtTexture` +0x89AD, `AppleParavirtBuffer` +0x15758 |
| `doesAliasResource:` | req | `c24@0:8@16` | `AppleParavirtTexture` +0x89B5, `AppleParavirtBuffer` +0x15760 |
| `isComplete` | req | `c16@0:8` | `AppleParavirtBuffer` +0x15768 |
| `isPurgeable` | req | `c16@0:8` | `AppleParavirtBuffer` +0x15770 |
| `waitUntilComplete` | req | `v16@0:8` | `AppleParavirtBuffer` +0x15778 |

#### 8.1.9 `MTLTexture` — APV 实现 5 条

| selector | req/opt | x86_64 type encoding | APV |
|---|---|---|---|
| `replaceRegion:mipmapLevel:slice:withBytes:bytesPerRow:bytesPerImage:` | req | `v104@0:8{?={?=QQQ}{?=QQQ}}16Q64Q72r^v80Q88Q96` | `AppleParavirtTexture` +0x8626 |
| `getBytes:bytesPerRow:bytesPerImage:fromRegion:mipmapLevel:slice:` | req | `v104@0:8^v16Q24Q32{?={?=QQQ}{?=QQQ}}40Q88Q96` | `AppleParavirtTexture` +0x8274 |
| `newTextureViewWithPixelFormat:` | req | `@24@0:8Q16` | `AppleParavirtTexture` +0x89BD |
| `newTextureViewWithPixelFormat:textureType:levels:slices:` | req | `@64@0:8Q16Q24{_NSRange=QQ}32{_NSRange=QQ}48` | `AppleParavirtTexture` +0x8A5A |
| `newTextureViewWithPixelFormat:textureType:levels:slices:swizzle:` | req | `@68@0:8Q16Q24{_NSRange=QQ}32{_NSRange=QQ}48{?=CCCC}64` | `AppleParavirtTexture` +0x8A85 |

#### 8.1.10 `MTLFunction` — APV 实现 13 条

| selector | req/opt | x86_64 type encoding | APV |
|---|---|---|---|
| `name` | req | `@16@0:8` | `AppleParavirtContainerFunction` +0x30BB |
| `label` | req | `@16@0:8` | `AppleParavirtContainerFunction` +0x3066 |
| `options` | req | `Q16@0:8` | `AppleParavirtContainerFunction` +0x3089 |
| `setLabel:` | req | `v24@0:8@16` | `AppleParavirtContainerFunction` +0x307A |
| `device` | req | `@16@0:8` | `AppleParavirtContainerFunction` +0x3052 |
| `functionConstantsDictionary` | req | `@16@0:8` | `AppleParavirtContainerFunction` +0x30C5 |
| `functionType` | req | `Q16@0:8` | `AppleParavirtContainerFunction` +0x305C |
| `newArgumentEncoderWithBufferIndex:` | req | `@24@0:8Q16` | `AppleParavirtContainerFunction` +0x3019 |
| `newArgumentEncoderWithBufferIndex:reflection:` | req | `@32@0:8Q16^@24` | `AppleParavirtContainerFunction` +0x3031 |
| `patchControlPointCount` | req | `q16@0:8` | `AppleParavirtContainerFunction` +0x30B1 |
| `patchType` | req | `Q16@0:8` | `AppleParavirtContainerFunction` +0x30A7 |
| `stageInputAttributes` | req | `@16@0:8` | `AppleParavirtContainerFunction` +0x309D |
| `vertexAttributes` | req | `@16@0:8` | `AppleParavirtContainerFunction` +0x3093 |


### 8.2 `MTLDevice` 全量（137 req + 2 opt）

`KNOWN`。`APV` 列标 “— 继承” 的条目全部由 `MTLIOAccelDevice` / `_MTLDevice` 提供，APV 不覆写。

**`MTLDevice`** — 自己声明 139 条（req 137 / opt 2），继承 `NSObject`，encoding 源 `S-METAL+S-DUMP`

| selector | req/opt | x86_64 type encoding | APV |
|---|---|---|---|
| `name` | req | `@16@0:8` | — 继承 |
| `newCommandQueue` | req | `@16@0:8` | — 继承 |
| `isLowPower` | req | `c16@0:8` | — 继承 |
| `isRemovable` | req | `c16@0:8` | — 继承 |
| `newBufferWithBytes:length:options:` | req | `@40@0:8r^v16Q24Q32` | `AppleParavirtDevice` +0xA943 |
| `newBufferWithLength:options:` | req | `@32@0:8Q16Q24` | `AppleParavirtDevice` +0xAA3E |
| `newLibraryWithFile:error:` | req | `@32@0:8@16^@24` | — 继承 |
| `newRenderPipelineStateWithDescriptor:error:` | req | `@32@0:8@16^@24` | — 继承 |
| `newSamplerStateWithDescriptor:` | req | `@24@0:8@16` | `AppleParavirtDevice` +0xAAC7 |
| `newTextureWithDescriptor:` | req | `@24@0:8@16` | `AppleParavirtDevice` +0xAAFA |
| `newTextureWithDescriptor:iosurface:plane:` | req | `@40@0:8@16^{__IOSurface=}24Q32` | `AppleParavirtDevice` +0xAB4B |
| `registryID` | req | `Q16@0:8` | — 继承 |
| `location` | req | `Q16@0:8` | — 继承 |
| `architecture` | req | `@16@0:8` | — 继承 |
| `hasUnifiedMemory` | req | `c16@0:8` | — 继承 |
| `maxTransferRate` | req | `Q16@0:8` | — 继承 |
| `newComputePipelineStateWithDescriptor:options:reflection:error:` | req | `@48@0:8@16Q24^@32^@40` | — 继承 |
| `newDynamicLibraryWithURL:error:` | req | `@32@0:8@16^@24` | — 继承 |
| `newSharedTextureWithDescriptor:` | req | `@24@0:8@16` | `AppleParavirtDevice` +0xB166 |
| `maxBufferLength` | req | `Q16@0:8` | — 继承 |
| `newIndirectCommandBufferWithDescriptor:maxCommandCount:options:` | req | `@40@0:8@16Q24Q32` | — 继承 |
| `newRenderPipelineStateWithDescriptor:options:completionHandler:` | req | `v40@0:8@16Q24@?32` | — 继承 |
| `supportsFamily:` | req | `c24@0:8q16` | — 继承 |
| `accelerationStructureSizesWithDescriptor:` | req | `{?=QQQ}24@0:8@16` | — 继承 |
| `areBarycentricCoordsSupported` | req | `c16@0:8` | — 继承 |
| `areProgrammableSamplePositionsSupported` | req | `c16@0:8` | `AppleParavirtDevice` +0xB088 |
| `areRasterOrderGroupsSupported` | req | `c16@0:8` | — 继承 |
| `argumentBuffersSupport` | req | `Q16@0:8` | — 继承 |
| `counterSets` | req | `@16@0:8` | — 继承 |
| `currentAllocatedSize` | req | `Q16@0:8` | — 继承 |
| `functionHandleWithBinaryFunction:` | req | `@24@0:8@16` | — 继承 |
| `functionHandleWithFunction:` | req | `@24@0:8@16` | — 继承 |
| `getDefaultSamplePositions:count:` | req | `v32@0:8^{?=ff}16Q24` | — 继承 |
| `heapAccelerationStructureSizeAndAlignWithDescriptor:` | req | `{?=QQ}24@0:8@16` | — 继承 |
| `heapAccelerationStructureSizeAndAlignWithSize:` | req | `{?=QQ}24@0:8Q16` | — 继承 |
| `heapBufferSizeAndAlignWithLength:options:` | req | `{?=QQ}32@0:8Q16Q24` | `AppleParavirtDevice` +0xA927 |
| `heapTextureSizeAndAlignWithDescriptor:` | req | `{?=QQ}24@0:8@16` | `AppleParavirtDevice` +0xA931 |
| `isDepth24Stencil8PixelFormatSupported` | req | `c16@0:8` | `AppleParavirtDevice` +0xB0AD |
| `isHeadless` | req | `c16@0:8` | — 继承 |
| `locationNumber` | req | `Q16@0:8` | — 继承 |
| `maxArgumentBufferSamplerCount` | req | `Q16@0:8` | — 继承 |
| `maxThreadgroupMemoryLength` | req | `Q16@0:8` | `AppleParavirtDevice` +0xB0E7 |
| `maxThreadsPerThreadgroup` | req | `{?=QQQ}16@0:8` | `AppleParavirtDevice` +0xB0C4 |
| `maximumConcurrentCompilationTaskCount` | req | `Q16@0:8` | — 继承 |
| `minimumLinearTextureAlignmentForPixelFormat:` | req | `Q24@0:8Q16` | — 继承 |
| `minimumTextureBufferAlignmentForPixelFormat:` | req | `Q24@0:8Q16` | `AppleParavirtDevice` +0xA93B |
| `newAccelerationStructureWithDescriptor:` | req | `@24@0:8@16` | — 继承 |
| `newAccelerationStructureWithSize:` | req | `@24@0:8Q16` | — 继承 |
| `newArchiveWithURL:error:` | req | `@32@0:8@16^@24` | — 继承 |
| `newArgumentEncoderWithArguments:` | req | `@24@0:8@16` | — 继承 |
| `newArgumentEncoderWithBufferBinding:` | req | `@24@0:8@16` | — 继承 |
| `newArgumentTableWithDescriptor:error:` | req | `@32@0:8@16^@24` | — 继承 |
| `newBinaryArchiveWithDescriptor:error:` | req | `@32@0:8@16^@24` | — 继承 |
| `newBufferWithBytesNoCopy:length:options:deallocator:` | req | `@48@0:8^v16Q24Q32@?40` | `AppleParavirtDevice` +0xA9E6 |
| `newBufferWithLength:options:placementSparsePageSize:` | req | `@40@0:8Q16Q24q32` | — 继承 |
| `newCommandAllocator` | req | `@16@0:8` | — 继承 |
| `newCommandAllocatorWithDescriptor:error:` | req | `@32@0:8@16^@24` | — 继承 |
| `newCommandBuffer` | req | `@16@0:8` | — 继承 |
| `newCommandQueueWithDescriptor:` | req | `@24@0:8@16` | `AppleParavirtDevice` +0xACCE |
| `newCommandQueueWithMaxCommandBufferCount:` | req | `@24@0:8Q16` | — 继承 |
| `newCompilerWithDescriptor:error:` | req | `@32@0:8@16^@24` | — 继承 |
| `newComputePipelineStateWithDescriptor:options:completionHandler:` | req | `v40@0:8@16Q24@?32` | — 继承 |
| `newComputePipelineStateWithFunction:completionHandler:` | req | `v32@0:8@16@?24` | — 继承 |
| `newComputePipelineStateWithFunction:error:` | req | `@32@0:8@16^@24` | — 继承 |
| `newComputePipelineStateWithFunction:options:completionHandler:` | req | `v40@0:8@16Q24@?32` | — 继承 |
| `newComputePipelineStateWithFunction:options:reflection:error:` | req | `@48@0:8@16Q24^@32^@40` | — 继承 |
| `newCounterHeapWithDescriptor:error:` | req | `@32@0:8@16^@24` | — 继承 |
| `newCounterSampleBufferWithDescriptor:error:` | req | `@32@0:8@16^@24` | — 继承 |
| `newDefaultLibrary` | req | `@16@0:8` | — 继承 |
| `newDefaultLibraryWithBundle:error:` | req | `@32@0:8@16^@24` | — 继承 |
| `newDepthStencilStateWithDescriptor:` | req | `@24@0:8@16` | `AppleParavirtDevice` +0xAA8C |
| `newDynamicLibrary:error:` | req | `@32@0:8@16^@24` | — 继承 |
| `newEvent` | req | `@16@0:8` | — 继承 |
| `newFence` | req | `@16@0:8` | `AppleParavirtDevice` +0xB05A |
| `newHeapWithDescriptor:` | req | `@24@0:8@16` | `AppleParavirtDevice` +0xAABF |
| `newIOCommandQueueWithDescriptor:error:` | req | `@32@0:8@16^@24` | — 继承 |
| `newIOFileHandleWithURL:compressionMethod:error:` | req | `@40@0:8@16q24^@32` | — 继承 |
| `newIOFileHandleWithURL:error:` | req | `@32@0:8@16^@24` | — 继承 |
| `newIOHandleWithURL:compressionMethod:error:` | req | `@40@0:8@16q24^@32` | — 继承 |
| `newIOHandleWithURL:error:` | req | `@32@0:8@16^@24` | — 继承 |
| `newLibraryWithData:error:` | req | `@32@0:8@16^@24` | — 继承 |
| `newLibraryWithSource:options:completionHandler:` | req | `v40@0:8@16@24@?32` | — 继承 |
| `newLibraryWithSource:options:error:` | req | `@40@0:8@16@24^@32` | — 继承 |
| `newLibraryWithStitchedDescriptor:completionHandler:` | req | `v32@0:8@16@?24` | — 继承 |
| `newLibraryWithStitchedDescriptor:error:` | req | `@32@0:8@16^@24` | — 继承 |
| `newLibraryWithURL:error:` | req | `@32@0:8@16^@24` | — 继承 |
| `newLogStateWithDescriptor:error:` | req | `@32@0:8@16^@24` | — 继承 |
| `newMTL4CommandQueue` | req | `@16@0:8` | — 继承 |
| `newMTL4CommandQueueWithDescriptor:error:` | req | `@32@0:8@16^@24` | — 继承 |
| `newPipelineDataSetSerializerWithDescriptor:` | req | `@24@0:8@16` | — 继承 |
| `newRasterizationRateMapWithDescriptor:` | req | `@24@0:8@16` | — 继承 |
| `newRenderPipelineStateWithDescriptor:completionHandler:` | req | `v32@0:8@16@?24` | — 继承 |
| `newRenderPipelineStateWithDescriptor:options:reflection:error:` | req | `@48@0:8@16Q24^@32^@40` | — 继承 |
| `newRenderPipelineStateWithMeshDescriptor:options:completionHandler:` | req | `v40@0:8@16Q24@?32` | — 继承 |
| `newRenderPipelineStateWithMeshDescriptor:options:reflection:error:` | req | `@48@0:8@16Q24^@32^@40` | — 继承 |
| `newRenderPipelineStateWithTileDescriptor:options:completionHandler:` | req | `v40@0:8@16Q24@?32` | `AppleParavirtDevice` +0xB36F |
| `newRenderPipelineStateWithTileDescriptor:options:reflection:error:` | req | `@48@0:8@16Q24^@32^@40` | `AppleParavirtDevice` +0xB384 |
| `newResidencySetWithDescriptor:error:` | req | `@32@0:8@16^@24` | — 继承 |
| `newSharedEvent` | req | `@16@0:8` | — 继承 |
| `newSharedEventWithHandle:` | req | `@24@0:8@16` | — 继承 |
| `newSharedTextureWithHandle:` | req | `@24@0:8@16` | `AppleParavirtDevice` +0xB1B6 |
| `newTensorWithDescriptor:error:` | req | `@32@0:8@16^@24` | — 继承 |
| `newTextureViewPoolWithDescriptor:error:` | req | `@32@0:8@16^@24` | — 继承 |
| `peerCount` | req | `I16@0:8` | — 继承 |
| `peerGroupID` | req | `Q16@0:8` | — 继承 |
| `peerIndex` | req | `I16@0:8` | — 继承 |
| `queryTimestampFrequency` | req | `Q16@0:8` | — 继承 |
| `readWriteTextureSupport` | req | `Q16@0:8` | — 继承 |
| `recommendedMaxWorkingSetSize` | req | `Q16@0:8` | — 继承 |
| `sampleTimestamps:gpuTimestamp:` | req | `v32@0:8^Q16^Q24` | — 继承 |
| `setShouldMaximizeConcurrentCompilation:` | req | `v20@0:8c16` | — 继承 |
| `shouldMaximizeConcurrentCompilation` | req | `c16@0:8` | — 继承 |
| `sizeOfCounterHeapEntry:` | req | `Q24@0:8q16` | — 继承 |
| `sparseTileSizeInBytes` | req | `Q16@0:8` | — 继承 |
| `sparseTileSizeInBytesForSparsePageSize:` | req | `Q24@0:8q16` | — 继承 |
| `sparseTileSizeWithTextureType:pixelFormat:sampleCount:` | req | `{?=QQQ}40@0:8Q16Q24Q32` | `AppleParavirtDevice` +0xB39C |
| `sparseTileSizeWithTextureType:pixelFormat:sampleCount:sparsePageSize:` | req | `{?=QQQ}48@0:8Q16Q24Q32q40` | `AppleParavirtDevice` +0xB3D0 |
| `supports32BitFloatFiltering` | req | `c16@0:8` | — 继承 |
| `supports32BitMSAA` | req | `c16@0:8` | — 继承 |
| `supportsBCTextureCompression` | req | `c16@0:8` | — 继承 |
| `supportsCounterSampling:` | req | `c24@0:8Q16` | — 继承 |
| `supportsDynamicLibraries` | req | `c16@0:8` | `AppleParavirtDevice` +0xB41C |
| `supportsFeatureSet:` | req | `c24@0:8Q16` | — 继承 |
| `supportsFunctionPointers` | req | `c16@0:8` | `AppleParavirtDevice` +0xB434 |
| `supportsFunctionPointersFromRender` | req | `c16@0:8` | `AppleParavirtDevice` +0xB43C |
| `supportsPlacementSparse` | req | `c16@0:8` | — 继承 |
| `supportsPrimitiveMotionBlur` | req | `c16@0:8` | — 继承 |
| `supportsPullModelInterpolation` | req | `c16@0:8` | — 继承 |
| `supportsQueryTextureLOD` | req | `c16@0:8` | — 继承 |
| `supportsRasterizationRateMapWithLayerCount:` | req | `c24@0:8Q16` | — 继承 |
| `supportsRaytracing` | req | `c16@0:8` | — 继承 |
| `supportsRaytracingFromRender` | req | `c16@0:8` | — 继承 |
| `supportsRenderDynamicLibraries` | req | `c16@0:8` | `AppleParavirtDevice` +0xB42C |
| `supportsShaderBarycentricCoordinates` | req | `c16@0:8` | — 继承 |
| `supportsTextureSampleCount:` | req | `c24@0:8Q16` | — 继承 |
| `supportsVertexAmplificationCount:` | req | `c24@0:8Q16` | — 继承 |
| `tensorSizeAndAlignWithDescriptor:` | req | `{?=QQ}24@0:8@16` | — 继承 |
| `convertSparsePixelRegions:toTileRegions:withTileSize:alignmentMode:numRegions:` | opt | `v72@0:8r^{?={?=QQQ}{?=QQQ}}16^{?={?=QQQ}{?=QQQ}}24{?=QQQ}32Q56Q64` | — 继承 |
| `convertSparseTileRegions:toPixelRegions:withTileSize:numRegions:` | opt | `v64@0:8r^{?={?=QQQ}{?=QQQ}}16^{?={?=QQQ}{?=QQQ}}24{?=QQQ}32Q56` | — 继承 |


### 8.3 `MTLDeviceSPI` 全量（427 req + 80 opt = 507）

`KNOWN`。计数三样本一致（第 0.2 节）。**逐条方法名不在本文重拄**：`S-DUMP` 第 **1574–2440** 行已经是按元数据顺序的逐条清单（带 `@required` / `@optional` 分界与 property 属性串），第 i 个方法名对应 `S-METAL` `protocol_t` 第 i 条 method record 的 encoding。本文给出分类普查与交集（第 8.1.2 节）。

| 类别 | 方法数 | APV 实现 |
|---|---|---|
| 能力布尔查询 | 255 | 11 |
| new* 工厂 | 78 | 6 |
| 其它 | 69 | 9 |
| 限值 / 对齐 | 64 | 0 |
| 编译器接口 | 12 | 1 |
| setter | 11 | 1 |
| 尺寸 / 对齐计算 | 10 | 0 |
| pipeline / variant | 6 | 0 |
| counter / 采样 | 2 | 0 |
| **合计** | **507** | **28** |

分类规则是按 selector 名前缀的机械划分（`new*` / `supports*`、`is*`、`are*`、`has*` / `max*`、`min*` / `set*` / 含 `Size`、`Align` / 含 `ompil`、`llvm`、`targetDevice` / 含 `ounter` / 其它），用于估算规模，不是语义分类。`INFERRED`

两条对本项目有用的观察：`INFERRED`

1. 能力布尔查询占了 `MTLDeviceSPI` 的大头，而 `_MTLDevice` 对它们**全部有默认实现**（APV 只覆写了 15 个常量返回的，第 4.1.5 节）。本项目同样只需覆写与默认值不同的那些，具体哪些由 `60-CAPABILITY-MATRIX.md` 定。
2. `new*` 工厂是真正的必须面，但 APV 证明其中大半可以 `return nil`（第 4.1.3 节）。


### 8.4 command queue / command buffer / command encoder 全量

`KNOWN`。`MTLCommandQueue` 与 `MTLCommandEncoder` 的 encoding 源在下表注出；`MTLCommandQueue` 不在 `S-METAL` `__objc_protolist` 里（第 0.3 节），取自 `S-APV`。

**`MTLCommandQueue`** — 自己声明 11 条（req 11 / opt 0），继承 `NSObject`，encoding 源 `S-APV`

| selector | req/opt | x86_64 type encoding | APV |
|---|---|---|---|
| `commandBuffer` | req | `@16@0:8` | `AppleParavirtCommandQueue` +0xA25A |
| `commandBufferWithDescriptor:` | req | `@24@0:8@16` | — 继承 |
| `commandBufferWithUnretainedReferences` | req | `@16@0:8` | `AppleParavirtCommandQueue` +0xA295 |
| `insertDebugCaptureBoundary` | req | `v16@0:8` | — 继承 |
| `addResidencySet:` | req | `v24@0:8@16` | — 继承 |
| `addResidencySets:count:` | req | `v32@0:8r^@16Q24` | — 继承 |
| `removeResidencySet:` | req | `v24@0:8@16` | — 继承 |
| `removeResidencySets:count:` | req | `v32@0:8r^@16Q24` | — 继承 |
| `label` | req | `@16@0:8` | — 继承 |
| `setLabel:` | req | `v24@0:8@16` | — 继承 |
| `device` | req | `@16@0:8` | — 继承 |

**`MTLCommandEncoder`** — 自己声明 8 条（req 8 / opt 0），继承 `NSObject`，encoding 源 `S-METAL+S-DUMP`

| selector | req/opt | x86_64 type encoding | APV |
|---|---|---|---|
| `label` | req | `@16@0:8` | — 继承 |
| `endEncoding` | req | `v16@0:8` | `PGSerializerParallelRenderCommandEncoder` +0x676F, `PGSerializerCommandEncoder` +0x9F53, `PGSerializerComputeCommandEncoder` +0x159EF |
| `setLabel:` | req | `v24@0:8@16` | — 继承 |
| `device` | req | `@16@0:8` | — 继承 |
| `pushDebugGroup:` | req | `v24@0:8@16` | — 继承 |
| `insertDebugSignpost:` | req | `v24@0:8@16` | — 继承 |
| `popDebugGroup` | req | `v16@0:8` | — 继承 |
| `barrierAfterQueueStages:beforeStages:` | req | `v32@0:8Q16Q24` | — 继承 |

**`MTLCommandBuffer`** — 自己声明 39 条（req 39 / opt 0），继承 `NSObject`，encoding 源 `S-METAL+S-DUMP`

| selector | req/opt | x86_64 type encoding | APV |
|---|---|---|---|
| `error` | req | `@16@0:8` | — 继承 |
| `label` | req | `@16@0:8` | — 继承 |
| `status` | req | `Q16@0:8` | — 继承 |
| `blitCommandEncoder` | req | `@16@0:8` | `AppleParavirtCommandBuffer` +0x17CA6 |
| `commit` | req | `v16@0:8` | — 继承 |
| `renderCommandEncoderWithDescriptor:` | req | `@24@0:8@16` | `AppleParavirtCommandBuffer` +0x17FB6 |
| `setLabel:` | req | `v24@0:8@16` | — 继承 |
| `waitUntilScheduled` | req | `v16@0:8` | — 继承 |
| `device` | req | `@16@0:8` | — 继承 |
| `GPUEndTime` | req | `d16@0:8` | — 继承 |
| `GPUStartTime` | req | `d16@0:8` | — 继承 |
| `enqueue` | req | `v16@0:8` | — 继承 |
| `addCompletedHandler:` | req | `v24@0:8@?16` | — 继承 |
| `addScheduledHandler:` | req | `v24@0:8@?16` | — 继承 |
| `encodeSignalEvent:value:` | req | `v32@0:8@16Q24` | — 继承 |
| `encodeWaitForEvent:value:` | req | `v32@0:8@16Q24` | — 继承 |
| `waitUntilCompleted` | req | `v16@0:8` | — 继承 |
| `kernelStartTime` | req | `d16@0:8` | — 继承 |
| `pushDebugGroup:` | req | `v24@0:8@16` | — 继承 |
| `computeCommandEncoderWithDispatchType:` | req | `@24@0:8Q16` | `AppleParavirtCommandBuffer` +0x17E0D |
| `kernelEndTime` | req | `d16@0:8` | — 继承 |
| `popDebugGroup` | req | `v16@0:8` | — 继承 |
| `accelerationStructureCommandEncoder` | req | `@16@0:8` | — 继承 |
| `accelerationStructureCommandEncoderWithDescriptor:` | req | `@24@0:8@16` | — 继承 |
| `blitCommandEncoderWithDescriptor:` | req | `@24@0:8@16` | `AppleParavirtCommandBuffer` +0x17D27 |
| `commandQueue` | req | `@16@0:8` | — 继承 |
| `computeCommandEncoder` | req | `@16@0:8` | `AppleParavirtCommandBuffer` +0x17D8C |
| `computeCommandEncoderWithDescriptor:` | req | `@24@0:8@16` | `AppleParavirtCommandBuffer` +0x17EA1 |
| `errorOptions` | req | `Q16@0:8` | — 继承 |
| `logs` | req | `@16@0:8` | — 继承 |
| `parallelRenderCommandEncoderWithDescriptor:` | req | `@24@0:8@16` | `AppleParavirtCommandBuffer` +0x17F06 |
| `presentDrawable:` | req | `v24@0:8@16` | — 继承 |
| `presentDrawable:afterMinimumDuration:` | req | `v32@0:8@16d24` | — 继承 |
| `presentDrawable:atTime:` | req | `v32@0:8@16d24` | — 继承 |
| `resourceStateCommandEncoder` | req | `@16@0:8` | `AppleParavirtCommandBuffer` +0x18066 |
| `resourceStateCommandEncoderWithDescriptor:` | req | `@24@0:8@16` | — 继承 |
| `retainedReferences` | req | `c16@0:8` | — 继承 |
| `useResidencySet:` | req | `v24@0:8@16` | — 继承 |
| `useResidencySets:count:` | req | `v32@0:8r^@16Q24` | — 继承 |


### 8.5 `MTLRenderCommandEncoder` 全量（131 req）

`KNOWN`。encoding 与方法名同源于 `S-APV` 的协议定义副本（该协议不在 `S-METAL` `__objc_protolist`，也不在 `S-DUMP`）。**这是全家族里工作量最大的一张表，APV 实现了 102 / 131。** 没实现的 29 条按 Apple 的做法由 `_MTLCommandEncoder` / `_MTLRenderCommandEncoder` 抽象层兑掉或索性不支持。

**`MTLRenderCommandEncoder`** — 自己声明 131 条（req 131 / opt 0），继承 `MTLCommandEncoder`，encoding 源 `S-APV`

| selector | req/opt | x86_64 type encoding | APV |
|---|---|---|---|
| `setRenderPipelineState:` | req | `v24@0:8@16` | `PGSerializerRenderCommandEncoder` +0x11CB3 |
| `setVertexBytes:length:atIndex:` | req | `v40@0:8r^v16Q24Q32` | `PGSerializerRenderCommandEncoder` +0x12117 |
| `setVertexBuffer:offset:atIndex:` | req | `v40@0:8@16Q24Q32` | `PGSerializerRenderCommandEncoder` +0x12087 |
| `setVertexBufferOffset:atIndex:` | req | `v32@0:8Q16Q24` | `PGSerializerRenderCommandEncoder` +0x12012 |
| `setVertexBuffers:offsets:withRange:` | req | `v48@0:8r^@16r^Q24{_NSRange=QQ}32` | `PGSerializerRenderCommandEncoder` +0x120DE |
| `setVertexBuffer:offset:attributeStride:atIndex:` | req | `v48@0:8@16Q24Q32Q40` | `PGSerializerRenderCommandEncoder` +0x12153 |
| `setVertexBuffers:offsets:attributeStrides:withRange:` | req | `v56@0:8r^@16r^Q24r^Q32{_NSRange=QQ}40` | `PGSerializerRenderCommandEncoder` +0x121CC |
| `setVertexBufferOffset:attributeStride:atIndex:` | req | `v40@0:8Q16Q24Q32` | `PGSerializerRenderCommandEncoder` +0x12227 |
| `setVertexBytes:length:attributeStride:atIndex:` | req | `v48@0:8r^v16Q24Q32Q40` | `PGSerializerRenderCommandEncoder` +0x12279 |
| `setVertexTexture:atIndex:` | req | `v32@0:8@16Q24` | `PGSerializerRenderCommandEncoder` +0x123CB |
| `setVertexTextures:withRange:` | req | `v40@0:8r^@16{_NSRange=QQ}24` | `PGSerializerRenderCommandEncoder` +0x1241A |
| `setVertexSamplerState:atIndex:` | req | `v32@0:8@16Q24` | `PGSerializerRenderCommandEncoder` +0x122C2 |
| `setVertexSamplerStates:withRange:` | req | `v40@0:8r^@16{_NSRange=QQ}24` | `PGSerializerRenderCommandEncoder` +0x12301 |
| `setVertexSamplerState:lodMinClamp:lodMaxClamp:atIndex:` | req | `v40@0:8@16f24f28Q32` | `PGSerializerRenderCommandEncoder` +0x12330 |
| `setVertexSamplerStates:lodMinClamps:lodMaxClamps:withRange:` | req | `v56@0:8r^@16r^f24r^f32{_NSRange=QQ}40` | `PGSerializerRenderCommandEncoder` +0x12393 |
| `setVertexVisibleFunctionTable:atBufferIndex:` | req | `v32@0:8@16Q24` | `PGSerializerRenderCommandEncoder` +0x132CA |
| `setVertexVisibleFunctionTables:withBufferRange:` | req | `v40@0:8r^@16{_NSRange=QQ}24` | `PGSerializerRenderCommandEncoder` +0x132EB |
| `setVertexIntersectionFunctionTable:atBufferIndex:` | req | `v32@0:8@16Q24` | `PGSerializerRenderCommandEncoder` +0x13414 |
| `setVertexIntersectionFunctionTables:withBufferRange:` | req | `v40@0:8r^@16{_NSRange=QQ}24` | `PGSerializerRenderCommandEncoder` +0x13435 |
| `setVertexAccelerationStructure:atBufferIndex:` | req | `v32@0:8@16Q24` | `PGSerializerRenderCommandEncoder` +0x134DA |
| `setViewport:` | req | `v64@0:8{?=dddddd}16` | `PGSerializerRenderCommandEncoder` +0x12456 |
| `setViewports:count:` | req | `v32@0:8r^{?=dddddd}16Q24` | `PGSerializerRenderCommandEncoder` +0x12492 |
| `setFrontFacingWinding:` | req | `v24@0:8Q16` | `PGSerializerRenderCommandEncoder` +0x11C84 |
| `setVertexAmplificationCount:viewMappings:` | req | `v32@0:8Q16r^{?=II}24` | `PGSerializerRenderCommandEncoder` +0x12F2B |
| `setCullMode:` | req | `v24@0:8Q16` | `PGSerializerRenderCommandEncoder` +0x117AC |
| `setDepthClipMode:` | req | `v24@0:8Q16` | `PGSerializerRenderCommandEncoder` +0x11831 |
| `setDepthBias:slopeScale:clamp:` | req | `v28@0:8f16f20f24` | `PGSerializerRenderCommandEncoder` +0x117DB |
| `setDepthTestMinBound:maxBound:` | req | `v24@0:8f16f20` | `PGSerializerRenderCommandEncoder` +0x141A3 |
| `setScissorRect:` | req | `v48@0:8{?=QQQQ}16` | `PGSerializerRenderCommandEncoder` +0x11D8B |
| `setScissorRects:count:` | req | `v32@0:8r^{?=QQQQ}16Q24` | `PGSerializerRenderCommandEncoder` +0x11DBF |
| `setTriangleFillMode:` | req | `v24@0:8Q16` | `PGSerializerRenderCommandEncoder` +0x11FE3 |
| `setFragmentBytes:length:atIndex:` | req | `v40@0:8r^v16Q24Q32` | `PGSerializerRenderCommandEncoder` +0x11AB4 |
| `setFragmentBuffer:offset:atIndex:` | req | `v40@0:8@16Q24Q32` | `PGSerializerRenderCommandEncoder` +0x11A24 |
| `setFragmentBufferOffset:atIndex:` | req | `v32@0:8Q16Q24` | `PGSerializerRenderCommandEncoder` +0x119AF |
| `setFragmentBuffers:offsets:withRange:` | req | `v48@0:8r^@16r^Q24{_NSRange=QQ}32` | `PGSerializerRenderCommandEncoder` +0x11A7B |
| `setFragmentTexture:atIndex:` | req | `v32@0:8@16Q24` | `PGSerializerRenderCommandEncoder` +0x11BF9 |
| `setFragmentTextures:withRange:` | req | `v40@0:8r^@16{_NSRange=QQ}24` | `PGSerializerRenderCommandEncoder` +0x11C48 |
| `setFragmentSamplerState:atIndex:` | req | `v32@0:8@16Q24` | `PGSerializerRenderCommandEncoder` +0x11AF0 |
| `setFragmentSamplerStates:withRange:` | req | `v40@0:8r^@16{_NSRange=QQ}24` | `PGSerializerRenderCommandEncoder` +0x11B2F |
| `setFragmentSamplerState:lodMinClamp:lodMaxClamp:atIndex:` | req | `v40@0:8@16f24f28Q32` | `PGSerializerRenderCommandEncoder` +0x11B5E |
| `setFragmentSamplerStates:lodMinClamps:lodMaxClamps:withRange:` | req | `v56@0:8r^@16r^f24r^f32{_NSRange=QQ}40` | `PGSerializerRenderCommandEncoder` +0x11BC1 |
| `setFragmentVisibleFunctionTable:atBufferIndex:` | req | `v32@0:8@16Q24` | `PGSerializerRenderCommandEncoder` +0x1330C |
| `setFragmentVisibleFunctionTables:withBufferRange:` | req | `v40@0:8r^@16{_NSRange=QQ}24` | `PGSerializerRenderCommandEncoder` +0x1332D |
| `setFragmentIntersectionFunctionTable:atBufferIndex:` | req | `v32@0:8@16Q24` | `PGSerializerRenderCommandEncoder` +0x13456 |
| `setFragmentIntersectionFunctionTables:withBufferRange:` | req | `v40@0:8r^@16{_NSRange=QQ}24` | `PGSerializerRenderCommandEncoder` +0x13477 |
| `setFragmentAccelerationStructure:atBufferIndex:` | req | `v32@0:8@16Q24` | `PGSerializerRenderCommandEncoder` +0x134FB |
| `setBlendColorRed:green:blue:alpha:` | req | `v32@0:8f16f20f24f28` | `PGSerializerRenderCommandEncoder` +0x116DF |
| `setDepthStencilState:` | req | `v24@0:8@16` | `PGSerializerRenderCommandEncoder` +0x11860 |
| `setStencilReferenceValue:` | req | `v20@0:8I16` | `PGSerializerRenderCommandEncoder` +0x11E51 |
| `setStencilFrontReferenceValue:backReferenceValue:` | req | `v24@0:8I16I20` | `PGSerializerRenderCommandEncoder` +0x11E1E |
| `setVisibilityResultMode:offset:` | req | `v32@0:8Q16Q24` | `PGSerializerRenderCommandEncoder` +0x12519 |
| `setColorStoreAction:atIndex:` | req | `v32@0:8Q16Q24` | `PGSerializerRenderCommandEncoder` +0x11744 |
| `setDepthStoreAction:` | req | `v24@0:8Q16` | `PGSerializerRenderCommandEncoder` +0x11951 |
| `setStencilStoreAction:` | req | `v24@0:8Q16` | `PGSerializerRenderCommandEncoder` +0x11E65 |
| `setColorStoreActionOptions:atIndex:` | req | `v32@0:8Q16Q24` | `PGSerializerRenderCommandEncoder` +0x11778 |
| `setDepthStoreActionOptions:` | req | `v24@0:8Q16` | `PGSerializerRenderCommandEncoder` +0x11980 |
| `setStencilStoreActionOptions:` | req | `v24@0:8Q16` | `PGSerializerRenderCommandEncoder` +0x11E94 |
| `setObjectBytes:length:atIndex:` | req | `v40@0:8r^v16Q24Q32` | — 继承 |
| `setObjectBuffer:offset:atIndex:` | req | `v40@0:8@16Q24Q32` | — 继承 |
| `setObjectBufferOffset:atIndex:` | req | `v32@0:8Q16Q24` | — 继承 |
| `setObjectBuffers:offsets:withRange:` | req | `v48@0:8r^@16r^Q24{_NSRange=QQ}32` | — 继承 |
| `setObjectTexture:atIndex:` | req | `v32@0:8@16Q24` | — 继承 |
| `setObjectTextures:withRange:` | req | `v40@0:8r^@16{_NSRange=QQ}24` | — 继承 |
| `setObjectSamplerState:atIndex:` | req | `v32@0:8@16Q24` | — 继承 |
| `setObjectSamplerStates:withRange:` | req | `v40@0:8r^@16{_NSRange=QQ}24` | — 继承 |
| `setObjectSamplerState:lodMinClamp:lodMaxClamp:atIndex:` | req | `v40@0:8@16f24f28Q32` | — 继承 |
| `setObjectSamplerStates:lodMinClamps:lodMaxClamps:withRange:` | req | `v56@0:8r^@16r^f24r^f32{_NSRange=QQ}40` | — 继承 |
| `setObjectThreadgroupMemoryLength:atIndex:` | req | `v32@0:8Q16Q24` | — 继承 |
| `setMeshBytes:length:atIndex:` | req | `v40@0:8r^v16Q24Q32` | — 继承 |
| `setMeshBuffer:offset:atIndex:` | req | `v40@0:8@16Q24Q32` | — 继承 |
| `setMeshBufferOffset:atIndex:` | req | `v32@0:8Q16Q24` | — 继承 |
| `setMeshBuffers:offsets:withRange:` | req | `v48@0:8r^@16r^Q24{_NSRange=QQ}32` | — 继承 |
| `setMeshTexture:atIndex:` | req | `v32@0:8@16Q24` | — 继承 |
| `setMeshTextures:withRange:` | req | `v40@0:8r^@16{_NSRange=QQ}24` | — 继承 |
| `setMeshSamplerState:atIndex:` | req | `v32@0:8@16Q24` | — 继承 |
| `setMeshSamplerStates:withRange:` | req | `v40@0:8r^@16{_NSRange=QQ}24` | — 继承 |
| `setMeshSamplerState:lodMinClamp:lodMaxClamp:atIndex:` | req | `v40@0:8@16f24f28Q32` | — 继承 |
| `setMeshSamplerStates:lodMinClamps:lodMaxClamps:withRange:` | req | `v56@0:8r^@16r^f24r^f32{_NSRange=QQ}40` | — 继承 |
| `drawMeshThreadgroups:threadsPerObjectThreadgroup:threadsPerMeshThreadgroup:` | req | `v88@0:8{?=QQQ}16{?=QQQ}40{?=QQQ}64` | — 继承 |
| `drawMeshThreads:threadsPerObjectThreadgroup:threadsPerMeshThreadgroup:` | req | `v88@0:8{?=QQQ}16{?=QQQ}40{?=QQQ}64` | — 继承 |
| `drawMeshThreadgroupsWithIndirectBuffer:indirectBufferOffset:threadsPerObjectThreadgroup:threadsPerMeshThreadgroup:` | req | `v80@0:8@16Q24{?=QQQ}32{?=QQQ}56` | — 继承 |
| `drawPrimitives:vertexStart:vertexCount:instanceCount:` | req | `v48@0:8Q16Q24Q32Q40` | `PGSerializerRenderCommandEncoder` +0xFE1F |
| `drawPrimitives:vertexStart:vertexCount:` | req | `v40@0:8Q16Q24Q32` | `PGSerializerRenderCommandEncoder` +0xFF2F |
| `drawIndexedPrimitives:indexCount:indexType:indexBuffer:indexBufferOffset:instanceCount:` | req | `v64@0:8Q16Q24Q32@40Q48Q56` | `PGSerializerRenderCommandEncoder` +0x1014E |
| `drawIndexedPrimitives:indexCount:indexType:indexBuffer:indexBufferOffset:` | req | `v56@0:8Q16Q24Q32@40Q48` | `PGSerializerRenderCommandEncoder` +0x10302 |
| `drawPrimitives:vertexStart:vertexCount:instanceCount:baseInstance:` | req | `v56@0:8Q16Q24Q32Q40Q48` | `PGSerializerRenderCommandEncoder` +0x10023 |
| `drawIndexedPrimitives:indexCount:indexType:indexBuffer:indexBufferOffset:instanceCount:baseVertex:baseInstance:` | req | `v80@0:8Q16Q24Q32@40Q48Q56q64Q72` | `PGSerializerRenderCommandEncoder` +0x1049A |
| `drawPrimitives:indirectBuffer:indirectBufferOffset:` | req | `v40@0:8Q16@24Q32` | `PGSerializerRenderCommandEncoder` +0x10BC9 |
| `drawIndexedPrimitives:indexType:indexBuffer:indexBufferOffset:indirectBuffer:indirectBufferOffset:` | req | `v64@0:8Q16Q24@32Q40@48Q56` | `PGSerializerRenderCommandEncoder` +0x10CD8 |
| `textureBarrier` | req | `v16@0:8` | `PGSerializerRenderCommandEncoder` +0x1254E |
| `updateFence:afterStages:` | req | `v32@0:8@16Q24` | `PGSerializerRenderCommandEncoder` +0x11573 |
| `waitForFence:beforeStages:` | req | `v32@0:8@16Q24` | `PGSerializerRenderCommandEncoder` +0x11629 |
| `setTessellationFactorBuffer:offset:instanceStride:` | req | `v40@0:8@16Q24Q32` | `PGSerializerRenderCommandEncoder` +0x11EC3 |
| `setTessellationFactorScale:` | req | `v20@0:8f16` | `PGSerializerRenderCommandEncoder` +0x11FAB |
| `drawPatches:patchStart:patchCount:patchIndexBuffer:patchIndexBufferOffset:instanceCount:baseInstance:` | req | `v72@0:8Q16Q24Q32@40Q48Q56Q64` | `PGSerializerRenderCommandEncoder` +0x10773 |
| `drawPatches:patchIndexBuffer:patchIndexBufferOffset:indirectBuffer:indirectBufferOffset:` | req | `v56@0:8Q16@24Q32@40Q48` | `PGSerializerRenderCommandEncoder` +0x10E6B |
| `drawIndexedPatches:patchStart:patchCount:patchIndexBuffer:patchIndexBufferOffset:controlPointIndexBuffer:controlPointIndexBufferOffset:instanceCount:baseInstance:` | req | `v88@0:8Q16Q24Q32@40Q48@56Q64Q72Q80` | `PGSerializerRenderCommandEncoder` +0x10962 |
| `drawIndexedPatches:patchIndexBuffer:patchIndexBufferOffset:controlPointIndexBuffer:controlPointIndexBufferOffset:indirectBuffer:indirectBufferOffset:` | req | `v72@0:8Q16@24Q32@40Q48@56Q64` | `PGSerializerRenderCommandEncoder` +0x10FEB |
| `setTileBytes:length:atIndex:` | req | `v40@0:8r^v16Q24Q32` | `PGSerializerRenderCommandEncoder` +0x12B20 |
| `setTileBuffer:offset:atIndex:` | req | `v40@0:8@16Q24Q32` | `PGSerializerRenderCommandEncoder` +0x129F2 |
| `setTileBufferOffset:atIndex:` | req | `v32@0:8Q16Q24` | `PGSerializerRenderCommandEncoder` +0x12A54 |
| `setTileBuffers:offsets:withRange:` | req | `v48@0:8r^@16r^Q24{_NSRange=QQ}32` | `PGSerializerRenderCommandEncoder` +0x12AD7 |
| `setTileTexture:atIndex:` | req | `v32@0:8@16Q24` | `PGSerializerRenderCommandEncoder` +0x12CA2 |
| `setTileTextures:withRange:` | req | `v40@0:8r^@16{_NSRange=QQ}24` | `PGSerializerRenderCommandEncoder` +0x12CFC |
| `setTileSamplerState:atIndex:` | req | `v32@0:8@16Q24` | `PGSerializerRenderCommandEncoder` +0x12B69 |
| `setTileSamplerStates:withRange:` | req | `v40@0:8r^@16{_NSRange=QQ}24` | `PGSerializerRenderCommandEncoder` +0x12BB3 |
| `setTileSamplerState:lodMinClamp:lodMaxClamp:atIndex:` | req | `v40@0:8@16f24f28Q32` | `PGSerializerRenderCommandEncoder` +0x12BEF |
| `setTileSamplerStates:lodMinClamps:lodMaxClamps:withRange:` | req | `v56@0:8r^@16r^f24r^f32{_NSRange=QQ}40` | `PGSerializerRenderCommandEncoder` +0x12C5A |
| `setTileVisibleFunctionTable:atBufferIndex:` | req | `v32@0:8@16Q24` | `PGSerializerRenderCommandEncoder` +0x1334E |
| `setTileVisibleFunctionTables:withBufferRange:` | req | `v40@0:8r^@16{_NSRange=QQ}24` | `PGSerializerRenderCommandEncoder` +0x1336F |
| `setTileIntersectionFunctionTable:atBufferIndex:` | req | `v32@0:8@16Q24` | `PGSerializerRenderCommandEncoder` +0x13498 |
| `setTileIntersectionFunctionTables:withBufferRange:` | req | `v40@0:8r^@16{_NSRange=QQ}24` | `PGSerializerRenderCommandEncoder` +0x134B9 |
| `setTileAccelerationStructure:atBufferIndex:` | req | `v32@0:8@16Q24` | `PGSerializerRenderCommandEncoder` +0x1351C |
| `dispatchThreadsPerTile:` | req | `v40@0:8{?=QQQ}16` | `PGSerializerRenderCommandEncoder` +0x128EE |
| `setThreadgroupMemoryLength:offset:atIndex:` | req | `v40@0:8Q16Q24Q32` | `PGSerializerRenderCommandEncoder` +0x129A1 |
| `useResource:usage:` | req | `v32@0:8@16Q24` | — 继承 |
| `useResources:count:usage:` | req | `v40@0:8r^@16Q24Q32` | — 继承 |
| `useResource:usage:stages:` | req | `v40@0:8@16Q24Q32` | `PGSerializerRenderCommandEncoder` +0x1275E |
| `useResources:count:usage:stages:` | req | `v48@0:8r^@16Q24Q32Q40` | `PGSerializerRenderCommandEncoder` +0x1278E |
| `useHeap:` | req | `v24@0:8@16` | — 继承 |
| `useHeaps:count:` | req | `v32@0:8r^@16Q24` | — 继承 |
| `useHeap:stages:` | req | `v32@0:8@16Q24` | `PGSerializerRenderCommandEncoder` +0x125EE |
| `useHeaps:count:stages:` | req | `v40@0:8r^@16Q24Q32` | `PGSerializerRenderCommandEncoder` +0x1261B |
| `executeCommandsInBuffer:withRange:` | req | `v40@0:8@16{_NSRange=QQ}24` | `PGSerializerRenderCommandEncoder` +0x112E5 |
| `executeCommandsInBuffer:indirectBuffer:indirectBufferOffset:` | req | `v40@0:8@16@24Q32` | `PGSerializerRenderCommandEncoder` +0x11181 |
| `memoryBarrierWithScope:afterStages:beforeStages:` | req | `v40@0:8Q16Q24Q32` | `PGSerializerRenderCommandEncoder` +0x1152E |
| `memoryBarrierWithResources:count:afterStages:beforeStages:` | req | `v48@0:8r^@16Q24Q32Q40` | `PGSerializerRenderCommandEncoder` +0x113E9 |
| `sampleCountersInBuffer:atSampleIndex:withBarrier:` | req | `v36@0:8@16Q24c32` | `PGSerializerRenderCommandEncoder` +0x1B105 |
| `setColorAttachmentMap:` | req | `v24@0:8@16` | — 继承 |
| `tileWidth` | req | `Q16@0:8` | `PGSerializerRenderCommandEncoder` +0x141C4 |
| `tileHeight` | req | `Q16@0:8` | `PGSerializerRenderCommandEncoder` +0x141D5 |


### 8.6 resource 家族全量（`MTLAllocation` / `MTLResource` / `MTLResourceSPI` / `MTLBuffer` / `MTLTexture`）

`KNOWN`。`MTLBuffer` 与 `MTLTexture` 的继承链是 `MTLBuffer <- MTLResource <- MTLAllocation <- NSObject`；SPI 层是 `MTLBufferSPI <- (MTLResourceSPI, MTLBuffer)`。本节只列公开层与 `MTLResourceSPI`；`MTLBufferSPI`（5 req + 8 opt）与 `MTLTextureSPI`（13 req + 10 opt）见附录 A。

**`MTLAllocation`** — 自己声明 1 条（req 1 / opt 0），继承 `NSObject`，encoding 源 `S-METAL+S-DUMP`

| selector | req/opt | x86_64 type encoding | APV |
|---|---|---|---|
| `allocatedSize` | req | `Q16@0:8` | — 继承 |

**`MTLResource`** — 自己声明 14 条（req 14 / opt 0），继承 `MTLAllocation`，encoding 源 `S-METAL+S-DUMP`

| selector | req/opt | x86_64 type encoding | APV |
|---|---|---|---|
| `label` | req | `@16@0:8` | — 继承 |
| `setLabel:` | req | `v24@0:8@16` | — 继承 |
| `device` | req | `@16@0:8` | — 继承 |
| `resourceOptions` | req | `Q16@0:8` | — 继承 |
| `allocatedSize` | req | `Q16@0:8` | — 继承 |
| `cpuCacheMode` | req | `Q16@0:8` | — 继承 |
| `hazardTrackingMode` | req | `Q16@0:8` | — 继承 |
| `heap` | req | `@16@0:8` | — 继承 |
| `heapOffset` | req | `Q16@0:8` | — 继承 |
| `isAliasable` | req | `c16@0:8` | `AppleParavirtTexture` +0x8266, `AppleParavirtBuffer` +0x1561D |
| `makeAliasable` | req | `v16@0:8` | `AppleParavirtTexture` +0x826E, `AppleParavirtBuffer` +0x15625 |
| `setOwnerWithIdentity:` | req | `i20@0:8I16` | — 继承 |
| `setPurgeableState:` | req | `Q24@0:8Q16` | — 继承 |
| `storageMode` | req | `Q16@0:8` | — 继承 |

**`MTLResourceSPI`** — 自己声明 13 条（req 12 / opt 1），继承 `MTLResource`，encoding 源 `S-METAL+S-DUMP`

| selector | req/opt | x86_64 type encoding | APV |
|---|---|---|---|
| `isWriteComplete` | req | `c16@0:8` | — 继承 |
| `allocationID` | req | `Q16@0:8` | — 继承 |
| `doesAliasAllResources:count:` | req | `c32@0:8r^@16Q24` | `AppleParavirtTexture` +0x89A5, `AppleParavirtBuffer` +0x15750 |
| `doesAliasAnyResources:count:` | req | `c32@0:8r^@16Q24` | `AppleParavirtTexture` +0x89AD, `AppleParavirtBuffer` +0x15758 |
| `doesAliasResource:` | req | `c24@0:8@16` | `AppleParavirtTexture` +0x89B5, `AppleParavirtBuffer` +0x15760 |
| `isComplete` | req | `c16@0:8` | `AppleParavirtBuffer` +0x15768 |
| `isPurgeable` | req | `c16@0:8` | `AppleParavirtBuffer` +0x15770 |
| `protectionOptions` | req | `Q16@0:8` | — 继承 |
| `responsibleProcess` | req | `i16@0:8` | — 继承 |
| `setResponsibleProcess:` | req | `v20@0:8i16` | — 继承 |
| `unfilteredResourceOptions` | req | `Q16@0:8` | — 继承 |
| `waitUntilComplete` | req | `v16@0:8` | `AppleParavirtBuffer` +0x15778 |
| `setOwnerWithIdentity:` | opt | `i20@0:8I16` | — 继承 |

**`MTLBuffer`** — 自己声明 11 条（req 11 / opt 0），继承 `MTLResource`，encoding 源 `S-METAL+S-DUMP`

| selector | req/opt | x86_64 type encoding | APV |
|---|---|---|---|
| `length` | req | `Q16@0:8` | — 继承 |
| `contents` | req | `^v16@0:8` | `AppleParavirtBuffer` +0x157A0 |
| `didModifyRange:` | req | `v32@0:8{_NSRange=QQ}16` | — 继承 |
| `addDebugMarker:range:` | req | `v40@0:8@16{_NSRange=QQ}24` | — 继承 |
| `gpuAddress` | req | `Q16@0:8` | — 继承 |
| `newRemoteBufferViewForDevice:` | req | `@24@0:8@16` | — 继承 |
| `newTensorWithDescriptor:offset:error:` | req | `@40@0:8@16Q24^@32` | — 继承 |
| `newTextureWithDescriptor:offset:bytesPerRow:` | req | `@40@0:8@16Q24Q32` | `AppleParavirtBuffer` +0x1562B |
| `remoteStorageBuffer` | req | `@16@0:8` | — 继承 |
| `removeAllDebugMarkers` | req | `v16@0:8` | — 继承 |
| `sparseBufferTier` | req | `q16@0:8` | — 继承 |

**`MTLTexture`** — 自己声明 39 条（req 36 / opt 3），继承 `MTLResource`，encoding 源 `S-METAL+S-DUMP`

| selector | req/opt | x86_64 type encoding | APV |
|---|---|---|---|
| `width` | req | `Q16@0:8` | — 继承 |
| `depth` | req | `Q16@0:8` | — 继承 |
| `height` | req | `Q16@0:8` | — 继承 |
| `pixelFormat` | req | `Q16@0:8` | — 继承 |
| `getBytes:bytesPerRow:fromRegion:mipmapLevel:` | req | `v88@0:8^v16Q24{?={?=QQQ}{?=QQQ}}32Q80` | — 继承 |
| `iosurface` | req | `^{__IOSurface=}16@0:8` | — 继承 |
| `mipmapLevelCount` | req | `Q16@0:8` | — 继承 |
| `newRemoteTextureViewForDevice:` | req | `@24@0:8@16` | — 继承 |
| `replaceRegion:mipmapLevel:slice:withBytes:bytesPerRow:bytesPerImage:` | req | `v104@0:8{?={?=QQQ}{?=QQQ}}16Q64Q72r^v80Q88Q96` | `AppleParavirtTexture` +0x8626 |
| `replaceRegion:mipmapLevel:withBytes:bytesPerRow:` | req | `v88@0:8{?={?=QQQ}{?=QQQ}}16Q64r^v72Q80` | — 继承 |
| `usage` | req | `Q16@0:8` | — 继承 |
| `bufferOffset` | req | `Q16@0:8` | — 继承 |
| `swizzle` | req | `{?=CCCC}16@0:8` | — 继承 |
| `compressionType` | req | `q16@0:8` | — 继承 |
| `allowGPUOptimizedContents` | req | `c16@0:8` | — 继承 |
| `arrayLength` | req | `Q16@0:8` | — 继承 |
| `buffer` | req | `@16@0:8` | — 继承 |
| `bufferBytesPerRow` | req | `Q16@0:8` | — 继承 |
| `getBytes:bytesPerRow:bytesPerImage:fromRegion:mipmapLevel:slice:` | req | `v104@0:8^v16Q24Q32{?={?=QQQ}{?=QQQ}}40Q88Q96` | `AppleParavirtTexture` +0x8274 |
| `gpuResourceID` | req | `{MTLResourceID=Q}16@0:8` | — 继承 |
| `iosurfacePlane` | req | `Q16@0:8` | — 继承 |
| `isFramebufferOnly` | req | `c16@0:8` | — 继承 |
| `isShareable` | req | `c16@0:8` | — 继承 |
| `newSharedTextureHandle` | req | `@16@0:8` | — 继承 |
| `newTextureViewWithDescriptor:` | req | `@24@0:8@16` | — 继承 |
| `newTextureViewWithPixelFormat:` | req | `@24@0:8Q16` | `AppleParavirtTexture` +0x89BD |
| `newTextureViewWithPixelFormat:textureType:levels:slices:` | req | `@64@0:8Q16Q24{_NSRange=QQ}32{_NSRange=QQ}48` | `AppleParavirtTexture` +0x8A5A |
| `newTextureViewWithPixelFormat:textureType:levels:slices:swizzle:` | req | `@68@0:8Q16Q24{_NSRange=QQ}32{_NSRange=QQ}48{?=CCCC}64` | `AppleParavirtTexture` +0x8A85 |
| `parentRelativeLevel` | req | `Q16@0:8` | — 继承 |
| `parentRelativeSlice` | req | `Q16@0:8` | — 继承 |
| `parentTexture` | req | `@16@0:8` | — 继承 |
| `remoteStorageTexture` | req | `@16@0:8` | — 继承 |
| `rootResource` | req | `@16@0:8` | — 继承 |
| `sampleCount` | req | `Q16@0:8` | — 继承 |
| `sparseTextureTier` | req | `q16@0:8` | — 继承 |
| `textureType` | req | `Q16@0:8` | — 继承 |
| `tailSizeInBytes` | opt | `Q16@0:8` | — 继承 |
| `firstMipmapInTail` | opt | `Q16@0:8` | — 继承 |
| `isSparse` | opt | `c16@0:8` | — 继承 |


### 8.7 state 对象全量（`MTLRenderPipelineState` / `MTLDepthStencilState` / `MTLSamplerState`）

`KNOWN`。三者的 APV 实现数**均为 0**。`MTLRenderPipelineState` 的 26 条全由 `_MTLRenderPipelineState` 提供，`MTLDepthStencilState` / `MTLSamplerState` 的 3 条（`label`、`device`、`gpuResourceID`）全由 `_MTLDepthStencilState` / `_MTLSamplerState` 提供。驱动只实现 SPI 层与自建方法（第 6.1 节）。

**`MTLRenderPipelineState`** — 自己声明 26 条（req 26 / opt 0），继承 `MTLAllocation`, `NSObject`，encoding 源 `S-METAL+S-DUMP`

| selector | req/opt | x86_64 type encoding | APV |
|---|---|---|---|
| `label` | req | `@16@0:8` | — 继承 |
| `device` | req | `@16@0:8` | — 继承 |
| `gpuResourceID` | req | `{MTLResourceID=Q}16@0:8` | — 继承 |
| `maxTotalThreadsPerThreadgroup` | req | `Q16@0:8` | — 继承 |
| `maxTotalThreadgroupsPerMeshGrid` | req | `Q16@0:8` | — 继承 |
| `functionHandleWithBinaryFunction:stage:` | req | `@32@0:8@16Q24` | — 继承 |
| `functionHandleWithFunction:stage:` | req | `@32@0:8@16Q24` | — 继承 |
| `functionHandleWithName:stage:` | req | `@32@0:8@16Q24` | — 继承 |
| `imageblockMemoryLengthForDimensions:` | req | `Q40@0:8{?=QQQ}16` | — 继承 |
| `imageblockSampleLength` | req | `Q16@0:8` | — 继承 |
| `maxTotalThreadsPerMeshThreadgroup` | req | `Q16@0:8` | — 继承 |
| `maxTotalThreadsPerObjectThreadgroup` | req | `Q16@0:8` | — 继承 |
| `meshThreadExecutionWidth` | req | `Q16@0:8` | — 继承 |
| `newIntersectionFunctionTableWithDescriptor:stage:` | req | `@32@0:8@16Q24` | — 继承 |
| `newRenderPipelineDescriptorForSpecialization` | req | `@16@0:8` | — 继承 |
| `newRenderPipelineStateWithAdditionalBinaryFunctions:error:` | req | `@32@0:8@16^@24` | — 继承 |
| `newRenderPipelineStateWithBinaryFunctions:error:` | req | `@32@0:8@16^@24` | — 继承 |
| `newVisibleFunctionTableWithDescriptor:stage:` | req | `@32@0:8@16Q24` | — 继承 |
| `objectThreadExecutionWidth` | req | `Q16@0:8` | — 继承 |
| `reflection` | req | `@16@0:8` | — 继承 |
| `requiredThreadsPerMeshThreadgroup` | req | `{?=QQQ}16@0:8` | — 继承 |
| `requiredThreadsPerObjectThreadgroup` | req | `{?=QQQ}16@0:8` | — 继承 |
| `requiredThreadsPerTileThreadgroup` | req | `{?=QQQ}16@0:8` | — 继承 |
| `shaderValidation` | req | `q16@0:8` | — 继承 |
| `supportIndirectCommandBuffers` | req | `c16@0:8` | — 继承 |
| `threadgroupSizeMatchesTileSize` | req | `c16@0:8` | — 继承 |

**`MTLDepthStencilState`** — 自己声明 3 条（req 3 / opt 0），继承 `NSObject`，encoding 源 `S-METAL+S-DUMP`

| selector | req/opt | x86_64 type encoding | APV |
|---|---|---|---|
| `label` | req | `@16@0:8` | — 继承 |
| `device` | req | `@16@0:8` | — 继承 |
| `gpuResourceID` | req | `{MTLResourceID=Q}16@0:8` | — 继承 |

**`MTLSamplerState`** — 自己声明 3 条（req 3 / opt 0），继承 `NSObject`，encoding 源 `S-METAL+S-DUMP`

| selector | req/opt | x86_64 type encoding | APV |
|---|---|---|---|
| `label` | req | `@16@0:8` | — 继承 |
| `device` | req | `@16@0:8` | — 继承 |
| `gpuResourceID` | req | `{MTLResourceID=Q}16@0:8` | — 继承 |


### 8.8 `MTLLibrary` 与 `MTLFunction` 全量

`KNOWN`。`MTLLibrary` 的 14 条 **APV 全部未实现**（无适配类），它们全由 `_MTLLibrary` 提供；`MTLFunction` 的 13 条 **APV 全部实现**，但实现者是驱动内部的容器对象 `AppleParavirtContainerFunction`，不是交给应用的 `_MTLFunction`（第 6.4 节）。

这两张表放在一起就是优先级 1 结论的全貌：**涉及 metallib 解析、函数名索引、常量特化、反射的那 14 条在 library 侧，驱动一条不碰；驱动只需要能回答“我这个函数是什么类型、叫什么名字”。**

**`MTLLibrary`** — 自己声明 14 条（req 14 / opt 0），继承 `NSObject`，encoding 源 `S-METAL+S-DUMP`

| selector | req/opt | x86_64 type encoding | APV |
|---|---|---|---|
| `type` | req | `q16@0:8` | — 继承 |
| `label` | req | `@16@0:8` | — 继承 |
| `newFunctionWithName:` | req | `@24@0:8@16` | — 继承 |
| `newFunctionWithName:constantValues:error:` | req | `@40@0:8@16@24^@32` | — 继承 |
| `setLabel:` | req | `v24@0:8@16` | — 继承 |
| `device` | req | `@16@0:8` | — 继承 |
| `newFunctionWithDescriptor:error:` | req | `@32@0:8@16^@24` | — 继承 |
| `functionNames` | req | `@16@0:8` | — 继承 |
| `installName` | req | `@16@0:8` | — 继承 |
| `newFunctionWithDescriptor:completionHandler:` | req | `v32@0:8@16@?24` | — 继承 |
| `newFunctionWithName:constantValues:completionHandler:` | req | `v40@0:8@16@24@?32` | — 继承 |
| `newIntersectionFunctionWithDescriptor:completionHandler:` | req | `v32@0:8@16@?24` | — 继承 |
| `newIntersectionFunctionWithDescriptor:error:` | req | `@32@0:8@16^@24` | — 继承 |
| `reflectionForFunctionWithName:` | req | `@24@0:8@16` | — 继承 |

**`MTLFunction`** — 自己声明 13 条（req 13 / opt 0），继承 `NSObject`，encoding 源 `S-METAL+S-DUMP`

| selector | req/opt | x86_64 type encoding | APV |
|---|---|---|---|
| `name` | req | `@16@0:8` | `AppleParavirtContainerFunction` +0x30BB |
| `label` | req | `@16@0:8` | `AppleParavirtContainerFunction` +0x3066 |
| `options` | req | `Q16@0:8` | `AppleParavirtContainerFunction` +0x3089 |
| `setLabel:` | req | `v24@0:8@16` | `AppleParavirtContainerFunction` +0x307A |
| `device` | req | `@16@0:8` | `AppleParavirtContainerFunction` +0x3052 |
| `functionConstantsDictionary` | req | `@16@0:8` | `AppleParavirtContainerFunction` +0x30C5 |
| `functionType` | req | `Q16@0:8` | `AppleParavirtContainerFunction` +0x305C |
| `newArgumentEncoderWithBufferIndex:` | req | `@24@0:8Q16` | `AppleParavirtContainerFunction` +0x3019 |
| `newArgumentEncoderWithBufferIndex:reflection:` | req | `@32@0:8Q16^@24` | `AppleParavirtContainerFunction` +0x3031 |
| `patchControlPointCount` | req | `q16@0:8` | `AppleParavirtContainerFunction` +0x30B1 |
| `patchType` | req | `Q16@0:8` | `AppleParavirtContainerFunction` +0x30A7 |
| `stageInputAttributes` | req | `@16@0:8` | `AppleParavirtContainerFunction` +0x309D |
| `vertexAttributes` | req | `@16@0:8` | `AppleParavirtContainerFunction` +0x3093 |


## 9. 优先级 3.8：所有权、线程与 ABI 规则

本节的每一条都有 `S-APV` 或 `S-METAL` 的实测依据。没有实测依据的不写。

### 9.1 `new*` 返回 +1，其余工厂返回 autoreleased

`KNOWN`。两组实测对照：

| 方法 | RVA | 尾部处理 | 所有权 |
|---|---|---|---|
| `-[AppleParavirtDevice newCommandQueueWithDescriptor:]` | `0xACCE` | 直接 `return [alloc init…]` | **+1，调用方负责 release** |
| `-[AppleParavirtDevice newBufferWithLength:options:]` | `0xAA3E` | 同上 | **+1** |
| `-[AppleParavirtDevice newFence]` | `0xB05A` | 同上 | **+1** |
| `-[AppleParavirtDevice newVertexVariantWithCompilerOutput:pipelineStatisticsOutput:]` | `0xAF05` | 同上 | **+1** |
| `-[AppleParavirtCommandQueue commandBuffer]` | `0xA25A` | `objc_autorelease(...)` | **autoreleased** |
| `-[AppleParavirtCommandQueue commandBufferWithUnretainedReferences]` | `0xA295` | `objc_autorelease(...)` | **autoreleased** |
| `-[AppleParavirtCommandBuffer renderCommandEncoderWithDescriptor:]` | `0x17FB6` | `objc_autorelease(...)` | **autoreleased** |
| `-[AppleParavirtCommandBuffer computeCommandEncoder]` | `0x17D8C` | `objc_autorelease(...)`，并 `objc_release` 掉自建的临时 `MTLComputePassDescriptor` | **autoreleased** |
| `-[PGSerializerParallelRenderCommandEncoder renderCommandEncoder]` | `0x666C` | — | autoreleased（同族） |

即标准 ObjC 内存管理约定，没有例外。**本项目照此，不要在 `new*` 里 autorelease，也不要在非 `new*` 工厂里返回 +1。**

### 9.1.1 一条容易出 bug 的细节：覆写 `new*` 还是裸形式

`KNOWN`。`_MTLDevice` 对 variant 工厂同时有两套：`newVertexVariantWithCompilerOutput:pipelineStatisticsOutput:`（`S-METAL` +0x1FE5C）与 `vertexVariantWithCompilerOutput:pipelineStatisticsOutput:`（+0x11A20C）。基类的 `new*` 版本是

```objc
pool push; id v = [self vertexVariantWithCompilerOutput:…]; v = objc_retain(v); pool pop; return v;
```

**APV 覆写的是 `new*` 版本**，于是基类那层 autoreleasepool + retain 不再执行，APV 直接返回 +1。

如果本项目改成只覆写裸形式（`vertexVariantWithCompilerOutput:`）并在里面返回 +1，基类会再 retain 一次 → **泄漏**。所以：**覆写 `new*` 版本，裸形式不要动。** `INFERRED`（基于上面的 `KNOWN` 代码形状）

### 9.2 对象图的强 / 弱引用

`KNOWN`。

| 持有者 | 被持有 | 强度 | 证据 |
|---|---|---|---|
| `AppleParavirtFunctionVariant._device` | device | **强**（`objc_retain`） | `S-APV` +0x30CF |
| `AppleParavirtContainerFunction` → device | device | 强 | `S-APV` +0x2F66 |
| `AppleParavirtDevice._serializer` / `._apvCompiler` / `._objectRefAllocator` / `._descriptorHeaps` | — | 强（`alloc`/`new` 后直接存 ivar） | `S-APV` +0xA30F |
| `MTLIOAccelDevice._acceleratorService` | `MTLIOAccelService` | **强** | `20-OBJC-DEVICE.md` 第 9 节 |
| `MTLIOAccelService._device` | device | **弱**（`objc_storeWeak`） | 同上 |
| `_MTLCommandBuffer._queue` | queue | 强 | ivar 被 `S-APV` 导入并解引用（+0x17FB6） |
| `_MTLCommandEncoder._commandBuffer` / `._device` | — | 强 | ivar 被 `S-APV` 导入 |
| `_MTLParallelRenderCommandEncoder._commandBuffers` | 子 command buffer 数组 | 强 | ivar 被 `S-APV` 导入 |

**device ↔ service 之间靠一条 weak 断环**，这是整个对象族唯一的弱引用。本项目照此即可。

### 9.3 `dealloc` 顺序约束（实测有坑）

`KNOWN`。`-[AppleParavirtBuffer dealloc]`（`S-APV` +0x155A2）：

```objc
uint32_t hostResourceID = self->_hostResourceID;   // 1. 先把要用的标量抄出来
id dev = objc_retain([self device]);               // 2. 先把 device 抓住一个强引用
[super dealloc];                                   // 3. 再调 super（可能放掉最后一个 device 引用）
if (hostResourceID) [dev releaseObjectRef:hostResourceID];   // 4. 用刚抓住的 device 释放句柄
objc_release(dev);                                 // 5. 放掉
```

**为什么必须这样**：`[super dealloc]` 会释放基类对 device 的引用；如果本对象是最后一个持有者，`super dealloc` 返回后 `[self device]` 已是悬垂指针。所以凡是"dealloc 时需要回头通知 device 释放某个 ID"的类，都必须**在 `[super dealloc]` 之前 retain device，在之后使用，最后 release**。

本项目的所有持有后端句柄的对象（buffer / texture / pipeline state / sampler / depth-stencil / fence / function variant）都适用这条。`INFERRED`（规则）/ `KNOWN`（APV 实现形状）

### 9.4 错误报告：两种约定并存

`KNOWN`。

| 层 | 约定 | 实测 |
|---|---|---|
| 应用 ↔ Metal.framework | `NSError **error`，encoding 尾部 `^@` | `newLibraryWithData:error:` = `@32@0:8@16^@24`；`newRenderPipelineStateWithDescriptor:error:` 同形 |
| Metal.framework ↔ 驱动 plugin | **`NSString **errorMessage`**，encoding 同样是 `^@` | `newRenderPipelineWithDescriptor:vertexVariant:fragmentVariant:errorMessage:` = `@48@0:8@16@24@32^@40`；基类在失败时往里塞 `CFSTR("Error creating compute variant")`（`S-METAL` +0x25598） |

两条硬规则，都由基类代码直接证明：

1. **进入时把 out 参数写 nil。** `-[_MTLDevice newComputePipelineWithDescriptor:variant:errorMessage:]` 的第一条语句是 `if (a5) *a5 = nil;`。`KNOWN`
2. **失败时放 `NSString *`，不是 `NSError *`。** 由 `MTLCompiler` 负责包装成 `NSError`（domain / code / userInfo）。驱动不构造 `NSError`。`KNOWN`

`S-APV` 中没有任何 `NSError` 类引用（`__objc_classlist` 外部引用只有 `NSArray`、`NSBundle`、`NSData`、`NSDictionary`、`NSMutableArray`、`NSMutableDictionary`、`NSNumber`、`NSObject`、`NSString`），这是上面第 2 条的旁证。`KNOWN`

### 9.5 block 的 copy / release 时机：驱动不负责

`KNOWN`。`S-APV` 的导入表里**没有 `_Block_copy` / `_Block_release`**，只有 `__Block_object_assign` / `__Block_object_dispose` / `__NSConcreteStackBlock`（这三个是"本模块自己创建带捕获变量的 block"所需，不是拷贝外来 block 所需）。

带 block 参数的方法，APV 一律**原样透传给基类**：

```objc
// -[AppleParavirtDevice newBufferWithBytesNoCopy:length:options:deallocator:]  S-APV +0xA9E6
//   encoding @48@0:8^v16Q24Q32@?40
id b = objc_alloc([AppleParavirtBuffer class]);
return [b initWithDevice:self withLength:len withOptions:opt withPointer:ptr withDeallocator:block];
//        ^ S-APV +0x15488 -> [super initWithDevice:pointer:length:options:sysMemSize:vidMemSize:
//                                    args:argsSize:deallocator:]  (MTLIOAccelBuffer)
```

**结论**：`@?` 形参的 block 由 Metal 的基类（`MTLIOAccelBuffer` / `_MTLCommandBuffer`）负责 `Block_copy` 与持有周期。驱动只需按值传递，不要自己 copy（会双重持有），也不要在栈上保存后跨越调用返回点使用。`KNOWN`（APV 行为）/ `INFERRED`（基类负责的推论）

本项目若自建 resource 类（不继承 `MTLIOAccelBuffer`，见第 6.5 节），**则这份责任落到自己头上**：`deallocator` 必须 `Block_copy` 存起来，`dealloc` 时调用再 `Block_release`。这是脱离 `MTLIOAccelResource` 的一项额外成本，必须记在 `41-IOSURFACE-USERSPACE.md` 的实现清单里。`INFERRED`

### 9.6 线程与队列

`KNOWN`。`S-APV` 的同步原语导入只有四个：`os_unfair_lock_lock` / `os_unfair_lock_unlock` / `pthread_mutex_lock` / `pthread_mutex_unlock`，加 `dispatch_queue_create` / `dispatch_sync` / `dispatch_release`。

| 范围 | 保护方式 | 证据 |
|---|---|---|
| `AppleParavirtDevice._descriptorHeaps` | `_descriptor_heaps_lock`（`os_unfair_lock`，ivar `0xD410`） | `S-APV` ivar 表 + `newDescriptorBuffer:` |
| `_MTLLibrary` 的 function 缓存 | `os_unfair_lock(MTLLibraryData::mutex(...))` | `S-METAL` +0x1C726 |
| `_MTLDevice._gpuFamiliyInitLock` | `os_unfair_lock` | `20-OBJC-DEVICE.md` 第 5.4 节 |
| `_MTLParallelRenderCommandEncoder._lock` | ivar 被 `S-APV` 导入 | `S-APV` 导入表 |
| device 级异步工作 | `com.Metal.DeviceDispatchQueue` / `com.Metal.DeviceCleaupQueue`（Apple 原样拼写） | `20-OBJC-DEVICE.md` 第 5.5 节 |
| command buffer 完成回调 | `-[MTLIOAccelCommandQueue setCompletionQueue:]` → `IOAccelCommandQueueSetDispatchQueue` | `20-OBJC-DEVICE.md` 第 8.3 节 |

由此得到的线程契约，`INFERRED`（除标注外）：

1. **device 必须线程安全。** 它的工厂方法会被任意线程并发调用。APV 只用一把 `os_unfair_lock` 保 descriptor heap 列表，其余状态在 init 后只读（`_deviceInfo`、`_features`、`_serializer`、`_apvCompiler` 都是 init 期一次写入、之后只读）。**把可变状态压到最少是这里的关键做法。**
2. **command buffer 与 encoder 不要求线程安全。** `_MTLCommandBuffer._currentCommandEncoder` 是单槽（由 `setCurrentCommandEncoder:` 写），一个 command buffer 同一时刻只能有一个活动 encoder。Metal 的公开契约就是"一个 command buffer 只能被一个线程编码"，APV 没有为 encoder 加任何锁。
3. **parallel render encoder 是唯一的例外**：它的子 encoder 可以并发编码，基类用 `_MTLParallelRenderCommandEncoder._lock` 保护子 encoder 数组。`PGSerializerParallelRenderCommandEncoder` 自己也带 `.cxx_construct` / `.cxx_destruct`（+0x6AD9 / +0x6AB5），说明它有 C++ 成员（很可能是子 encoder 容器）。
4. **完成回调在 queue 指定的 dispatch queue 上**，不在提交线程上。本项目的渲染核心若要在回调里碰 Vulkan 对象，必须自己做同步。
5. `pthread_mutex_*` 在 `S-APV` 中被导入，使用点在 `PGSerializer`（95 个方法那层）。即**命令序列化器自己是加锁的**。本项目在同一位置（窄 C ABI 之下的 Rust 侧）同样需要内部同步。

### 9.7 异常与断言边界

`KNOWN`。三种"失败就终止"的机制同时存在，必须分清：

| 机制 | 触发者 | 行为 | 实测点 |
|---|---|---|---|
| `MTLReleaseAssertionFailure` | `-[_MTLDevice initLimits]` 的 5 条 limits 断言 | **release 版也终止进程** | `20-OBJC-DEVICE.md` 第 5.2.1 节 |
| `doesNotRecognizeSelector:` | APV 对不支持的 SPI | 抛 `NSInvalidArgumentException` | `S-APV` +0xB36F / +0xB384 / +0xB404 |
| `__assert_rtn` | `S-APV` 导入表里有 | 条件编译的调试断言 | `S-APV` 导入表 |
| 自定义 cold 块 | `setupCompiler` 的 `MaxMetalShaderVersionMajor <= 1`（+0x1ADED）、`newBufferWith*` 的 `resourceID == 0`（+0x1BC7C）、`renderCommandEncoderWithDescriptor:` 的 OpenGL 模式不匹配（+0x1BFB8） | 不返回 | `S-APV` 反编译 |

另外 `S-APV` 导入 `__cxa_free_exception`，说明有 C++ 异常路径（在 `PGSerializer` 的 C++ 成员里）。**ObjC 边界上不要让 C++ 异常逃出**。

**本项目的边界规则**：`INFERRED`

1. ObjC 方法**不得**让 Rust panic 穿出。渲染核心的窄 C ABI 必须 `catch_unwind`，把 panic 转成返回码。
2. 不支持的能力用"返回 nil + 能力 getter 返回 NO"，**不要**用 `doesNotRecognizeSelector:`。APV 用了，但那是 Apple 知道自己的客户端不会走那条路；本项目面对的是任意第三方 Metal 客户端。
3. `initLimits` 的 5 条断言是唯一必须严格满足的硬条件，由 `featureProfile` + `argumentBuffersSupport` 决定（第 5 节），与本文其它内容无关。

### 9.8 encoding 与 x86_64 ABI 的两处陷阱

`KNOWN`（encoding）/ `INFERRED`（ABI 解释，依据 x86_64 System V + Apple ObjC runtime）

1. **大于 16 字节的结构体返回走隐藏 sret 指针，但 encoding 不显示它。** 例：`maxThreadsPerThreadgroup` 的 encoding 是 `{?=QQQ}16@0:8` —— 看起来 self 在 0、sel 在 8、总长 16，但实际 ABI 是 `objc_msgSend_stret(ret, self, sel)`。`S-APV` 导入了 `__imp__objc_msgSend_stret` 即为此。16 字节及以下的（如 `{?=QQ}` = `MTLSizeAndAlign`）走 `rax:rdx`，用普通 `objc_msgSend`。**照 encoding 直接推寄存器分配会错。**
2. **`_Bool`（`B`）与 `char`（`c`）在 encoding 里是两个不同类型，但 ABI 上都是 1 字节。** `MTLDevice` 的能力 getter 多数是 `c16@0:8`（`BOOL` = `signed char`），而 APV 自建的 `setupCompiler` 是 `B16@0:8`（C++ `bool`）、`APVFeatures` 的字段也是 `B`。协议方法必须严格按协议给的那个字母声明，否则 `conformsToProtocol:` 虽然仍过，但 `method_getTypeEncoding` 对不上，会影响 NSInvocation / 转发路径与某些工具链校验。

### 9.9 label 的所有权

`KNOWN`。`MTLDeviceSPI` 的 `label` property 属性串是 `T@"NSString",C`（copy），`setLabel:` encoding `v24@0:8@16`。`S-APV` 导入 `__imp__objc_setProperty_atomic_copy`，即 **label 的 setter 是原子 copy 语义**。`AppleParavirtContainerFunction` 自己实现了 `label`（+0x3066）/ `setLabel:`（+0x307A）；其它类的 label 由 `_MTLObjectWithLabel` 提供。

## 10. 优先级 3.9：本项目必须覆写 vs 可以继承

本节合并三份输入：`20-OBJC-DEVICE.md` 第 6 节（厂商覆写全集）、同文第 8 节（IOKit 依赖分档 A/B）、本文第 2 / 4 / 5 / 6 / 8 节（APV 实测）。

判定口径：

- **必须覆写**：不覆写则功能不可用（返回 nil / 走空指针 / 触发断言 / 打到不存在的宿主）。
- **应当覆写**：基类能跑通，但语义对本项目不对（会去打 user client 或假定有真 GPU）。
- **可以继承**：基类实现对本项目正确，一行不改。

### 10.1 继承基类选择（最终表）

修订 `20-OBJC-DEVICE.md` 第 8.7 节，依据本文第 3 节的 APV 实测。`INFERRED`

| 对象 | `20-OBJC-DEVICE.md` 第 8.7 节 | 本文的修订 | 理由 |
|---|---|---|---|
| Device | `MTLIOAccelDevice` | **不变** | APV 也是，且三个 init 方法零 IOKit 依赖 |
| CommandQueue | `_MTLCommandQueue` | **不变**（与 APV 不同） | APV 走 `MTLIOAccelCommandQueue` 的 type-8 提交路径，本项目没有宿主可提交 |
| CommandBuffer | `MTLIOAccelCommandBuffer` | **改为 `_MTLCommandBuffer`** | `MTLIOAccelCommandBuffer` 的命令字节分配全部来自 `lazyInitialize` 建的 shmem 池与 `MTLIOAccelCommandBufferStoragePool`；本项目要整体替换（第 6.3 节 APV 覆写的 10 个 `get*Bytes` / `allocKernelCommand:` / `split` / `merge:` 正是这些）。继承它只会得到一堆指向不存在池子的空指针 |
| Encoder（render / compute / blit） | `MTLIOAccelCommandEncoder` 或对应 `MTLIOAccel*` | **改为自建基类 `<Proj>CommandEncoder <- _MTLCommandEncoder`** | **直接照 APV 的 `PGSerializerCommandEncoder` 布局。** `MTLIOAccel*` encoder 对一个序列化型驱动零价值（第 3.1 节） |
| ParallelRenderEncoder | 对应 `MTLIOAccel*` | **改为 `_MTLParallelRenderCommandEncoder`** | APV 就是这么做的；基类提供子 encoder 数组与锁 |
| Buffer / Texture | `_MTLResource` 子树 | **不变**（与 APV 不同） | APV 走 `MTLIOAccelResource`（真打 `IOAccelResourceCreate`）。代价见第 9.5 节：`deallocator` block 的持有责任要自己接 |
| Heap | `_MTLHeap` | **不变**，且第一版可整条返回 nil | APV 的 `newHeapWithDescriptor:` 就返回 nil（第 4.2 节） |
| Fence | `_MTLFence` | **改为 `_MTLObjectWithLabel`** | APV 用更低一层，说明 `_MTLFence` 没提供什么必需的东西；但 `_MTLFence` 也无害，两者皆可 |
| Event / SharedEvent | `_MTLFence` / `_MTLSharedEvent` | **可以整个不建类** | APV 零实现，全继承 |
| Library / Function（对外） | `_MTL*` 抽象层 | **不建类** | 第 2 节与第 8.8 节：14 条 `MTLLibrary` 方法 APV 一条不碰 |
| Function（驱动内部容器） | 未提 | **新增：`<Proj>ContainerFunction <- NSObject`，适配 `MTLFunction`** | 照 APV 第 6.4 节 |
| FunctionVariant | 未提 | **新增：`<Proj>FunctionVariant <- MTLFunctionVariant`** | 照 APV 第 2.4.2 节，持 `PipelineArtifact` 句柄 |
| PipelineState / Sampler / DepthStencil | `_MTL*` 抽象层 | **不变** | 本来就没有 IOAccel 版；且协议方法 APV 零实现（第 8.7 节） |
| GLDrawable | 不实现 | **不变**，`supportsOpenGL` 返回 NO | APV 的 `supportsOpenGL` = `return 0`（`S-APV` +0xB0F8） |

### 10.2 Device 类：必须覆写的方法（分档）

`INFERRED`（档位判定）/ `KNOWN`（每条的 APV 实测状态）

#### A 档 — 必须覆写，不覆写则不可用

| selector | 不覆写的后果 | APV 实现 |
|---|---|---|
| `featureProfile` | 基类无实现 → 崩 | +0xACC3，`return 10000` |
| `initWithAcceleratorPort:` | 无法做自己的初始化（可调 super 后扩展） | +0xA30F |
| `compiler` | 基类 `return nil` → 全部 pipeline 创建失败 | +0xA607 |
| `newVertexVariantWithCompilerOutput:pipelineStatisticsOutput:` | 基类 `return nil` | +0xAF05 |
| `newFragmentVariantWithCompilerOutput:pipelineStatisticsOutput:` | 同上 | +0xAF3E |
| `newComputeVariantWithCompilerOutput:pipelineStatisticsOutput:` | 同上 | +0xAF77 |
| `newRenderPipelineWithDescriptor:vertexVariant:fragmentVariant:errorMessage:` | 基类 `return nil` | +0xAFB0 |
| `newComputePipelineWithDescriptor:variant:errorMessage:` | 基类 `return nil` + 填 `@"Error creating compute variant"` | +0xB008 |
| `newBufferWithLength:options:` / `newBufferWithBytes:length:options:` / `newBufferWithBytesNoCopy:length:options:deallocator:` | 基类会去打 `IOAccelResourceCreate` | +0xAA3E / +0xA943 / +0xA9E6 |
| `newTextureWithDescriptor:` / `newTextureWithDescriptor:iosurface:plane:` | 同上 | +0xAAFA / +0xAB4B |
| `newCommandQueueWithDescriptor:` | 基类会开 type-8 user client | +0xACCE |
| `newSamplerStateWithDescriptor:` / `newDepthStencilStateWithDescriptor:` | 基类无后端 | +0xAAC7 / +0xAA8C |
| `newFence` | 同上 | +0xB05A |
| `llvmVersion` | `MTLCompiler` 要用来选 AIR 版本 | +0xB04F，`return 32023` |

#### B 档 — 应当覆写（基类能跑但语义不对，或要报真实能力）

`vendorName`、`productName`、`familyName`、`name`、`architecture`、`maxThreadsPerThreadgroup`、`maxThreadgroupMemoryLength`、`supportsSampleCount:`、`isDepth24Stencil8PixelFormatSupported`、`singleFPConfig`/`halfFPConfig`/`doubleFPConfig`、`heapBufferSizeAndAlignWithLength:options:`、`heapTextureSizeAndAlignWithDescriptor:`、`minimumTextureBufferAlignmentForPixelFormat:`、`sparseTileSizeWithTextureType:pixelFormat:sampleCount:`（两个重载）、`tileSizeWithTextureType:pixelFormat:sampleCount:`，以及 `60-CAPABILITY-MATRIX.md` 判定与基类默认值不同的那些 `supports*` getter。

APV 对这一档的处理是"要么常量、要么从 `deviceInfo` 取"，两种都适用于本项目（本项目的"宿主"就是自己的常量表，见第 5.3 节）。

#### C 档 — 必须明确关闭（返回 nil / NO）

`newHeapWithDescriptor:`、`newIndirectCommandBufferWithDescriptor:maxCount:options:`、`newIndirectComputeCommandEncoderWithBuffer:`、`newIndirectRenderCommandEncoderWithBuffer:`、`newVisibleFunctionTableWithDescriptor:`、`newRenderPipelineStateWithTileDescriptor:options:reflection:error:`（含 completionHandler 版）、`supportsOpenGL`、`supportsDynamicLibraries`、`supportsStatefulDynamicLibraries`、`supportsRenderDynamicLibraries`、`supportsFunctionPointers`、`supportsFunctionPointersFromRender`、`supportsBinaryArchives`、`supportsArgumentBuffers`、`supportsResourceHeaps`、`areProgrammableSamplePositionsSupported`。

**全部按 APV 的取值照抄即可**（第 4.1.5 节），但第 2.5 节第 5 条：用 `return nil` 而不是 `doesNotRecognizeSelector:`。

#### D 档 — 可以继承，一行不写

`initLimits`、`initFeatureQueries`、`initGPUFamilySupport`、`argumentBuffersSupport`、`indirectArgumentBufferCapabilities`、`registryID`、`acceleratorPort`、`deviceRef`、`sharedRef`、`_setAcceleratorService:`、`maxBufferLength`、`recommendedMaxWorkingSetSize`、`hasUnifiedMemory`、`isLowPower`、`isHeadless`、`isRemovable`、`isSlotted`、`isBuiltIn`、`location`、`locationNumber`、`maxTransferRate`、`dedicatedMemorySize`、`sharedMemorySize`、`currentAllocatedSize`、`updateGPUSelectionProperties`、`supportsFamily:`、`counterSets`、`newEvent`、`newSharedEvent`、`newSharedTextureWithDescriptor:`（走真 IOSurface）、`newSharedTextureWithHandle:`、`newArgumentEncoderWithLayout:`、`newCommandQueue`（无参版）、`featureQueries`、`limits` 及 `limits` 的全部 60+ 个标量 getter、`targetDeviceArchitecture`、`newLibraryWith*` 全族、`newFunctionWith*` 全族、`newRenderPipelineStateWith*` 全族、`newComputePipelineStateWith*` 全族。

**这一档里有两条与 `20-OBJC-DEVICE.md` 不同的决定：**

1. `argumentBuffersSupport` 从"必须返回 0 或 1"降级为"不用管"——基类的默认链路已经稳定返回 0（本文第 5.2 节）。原文第 11.5 节把它列为第一个验收点要覆写的三个方法之一，可以去掉。
2. `maxBufferLength` 可以继承（selector 0 的 `maxResourceSize` 字段已经给值）。AMD 覆写只是为了缓存。

`lazyInitialize` / `supportLazyInitialization` 的取舍不变，按 `20-OBJC-DEVICE.md` 第 5.5.1 节。本文补一条实测事实：**APV 两个都不覆写**，即 Apple 自己的虚拟化驱动也走完整的 type-6 + dirty ring 路径。所以第一版按原文建议"老实实现 type-6 selector 9 / 0xA"是有先例的做法。`KNOWN`

### 10.3 其它对象类：必须覆写的最小集

`INFERRED`，依据第 6 节的 APV 实测。

| 对象 | 必须覆写 | 可以继承 |
|---|---|---|
| CommandQueue | `initWithDevice:descriptor:`、`commandBuffer`、`commandBufferWithUnretainedReferences`、`submitCommandBuffers:count:`（或等价提交点）、`dealloc` | `label`/`setLabel:`、`insertDebugCaptureBoundary`、counter 族（opt，可不实现） |
| CommandBuffer | 6 个 encoder 工厂、`endEncoding`、resource 引用登记（`addResourceReference:isWrite:` 等）、命令字节分配、`commit` 路径的后端钩子 | `commit`/`enqueue`/`waitUntilCompleted`/`waitUntilScheduled`/`addScheduledHandler:`/`addCompletedHandler:`/`status`/`error`/`label`/debug group（全部在 `_MTLCommandBuffer`） |
| RenderCommandEncoder | **131 条 `MTLRenderCommandEncoder` 里 APV 实现了 102 条**（第 8.5 节），这是本项目最大的一块 | 29 条未实现项 + `MTLCommandEncoder` 的 7 / 8 条 |
| ComputeCommandEncoder | 46 / 95（第 6 节表） | 其余 |
| BlitCommandEncoder | 32 / 66 | 其余 |
| ParallelRenderEncoder | `initWithCommandBuffer:renderPassDescriptor:`、`renderCommandEncoder`、`endEncoding`、6 个 store-action setter | 其余 |
| Buffer | `contents`、`didModifyRange:`、`newTextureWithDescriptor:offset:bytesPerRow:`、`length`/`dealloc`，加 `deallocator` block 的持有（第 9.5 节） | `label`、debug marker、`allocatedSize`、`heap`/`heapOffset`（第一版可返回 nil/0） |
| Texture | `init*` 全族（6 个）、`getBytes:…`、`replaceRegion:…`、`newTextureView*`（3 个）、`didModifyData` | `width`/`height`/`depth`/`mipmapLevelCount`/`arrayLength`/`sampleCount`/`pixelFormat`/`textureType`/`usage` 等 descriptor 回读（`_MTLTexture` 从 descriptor 填） |
| RenderPipelineState | `init…WithDevice:pipelineStateDescriptor:vertexVariant:fragmentVariant:errorMessage:`、`dealloc`，加 `31-PIPELINE-ARTIFACT.md` 要求的句柄 getter | **全部 26 条 `MTLRenderPipelineState` 协议方法** |
| ComputePipelineState | `init…`、`dealloc`、`threadExecutionWidth`、`staticThreadgroupMemoryLength`、`maxTotalThreadsPerThreadgroup` | 其余 15 条 |
| SamplerState / DepthStencilState | `init…`、`dealloc` | **全部 3 条协议方法** |
| Fence | `initWithDevice:`、`dealloc`、`device` | `label`/`setLabel:` |
| Library / Function（对外） | — | **全部** |

**这张表就是本项目 ObjC 侧的工作量分布：render encoder 约 102 个方法，compute encoder 约 46 个，blit encoder 约 32 个，device 约 60 个（A+B+C 档），其余全部对象合起来不到 50 个。总量约 290 个方法，其中 180 个是 encoder 的参数打包。**

## 11. 附带确证：APV 的厂商私有 selector 全集

`KNOWN`。方法：在 `S-APV` 中取 `IOConnectCallMethod` 的 stub（+0x1C43E）的全部代码交叉引用（**17 处**），对每个调用点回扫 `mov esi, imm`（第二参即 selector）。全部调用点的 connection 都来自 `IOAccelSharedGetConnect([device sharedRef])`，即 **type-6（shared）user client**。

| selector | 用途 | 调用点（`S-APV` RVA） |
|---|---|---|
| `0x100` | **创建"状态对象"**：把序列化好的 descriptor 交给宿主，拿回一个 object index | `-[AppleParavirtFence initWithDevice:]` +0x1048；`-[AppleParavirtSamplerState initWithDevice:samplerDescriptor:]` +0x7154；`-[AppleParavirtDepthStencilState initWithDevice:depthStencilDescriptor:]` +0x143D9；`-[AppleParavirtRenderPipelineState initWithDevice:pipelineStateDescriptor:]` +0x1470E 与 `…vertexVariant:fragmentVariant:errorMessage:]` +0x149C1 |
| `0x101` | **销毁"状态对象"**（与 `0x100` 对偶，全部 dealloc 共用一条） | Fence +0x119C；FunctionVariant +0x34F6；SamplerState +0x72A8；DepthStencilState +0x1452D；RenderPipelineState +0x14B8B；ComputePipelineState +0x15310 |
| `0x102` | **注册 function IR**（第 2.4.2 节，in = 24 字节记录，out = 1 个 scalar） | `-[AppleParavirtFunctionVariant initWithCompilerOutput:device:functionType:]` +0x32F4 |
| `0x103` | **创建 texture** | `-[AppleParavirtTexture initWithBuffer:descriptor:offset:bytesPerRow:]` +0x77A1；`…initWithTexture:pixelFormat:textureType:levels:slices:swizzle:]` +0x7AC7 |
| `0x104` | **销毁 texture** | `-[AppleParavirtTexture dealloc]` +0x81E3 |
| `0x105` | **读设备能力表**（out = 284 字节 = `APVDeviceInfo` + `APVFeatures`，第 5.3 节） | `-[AppleParavirtDevice setupDeviceInfo]` +0xA824 |
| `0x106` | **创建 compute pipeline** | `-[AppleParavirtComputePipelineState initWithDevice:pipelineStateDescriptor:computeVariant:errorMessage:]` +0x150C9 |

三条可以直接用的结论：

1. **厂商私有 selector 挂在 type-6（shared）user client 上，不是 type-5。** `20-OBJC-DEVICE.md` 第 6.3 节记的 AMD 用 `0x100` 是在**另一条链**上（`-[GFXAAMD_MtlDevice initWithAcceleratorPort:]` 用 `IOAccelDeviceGetConnect(_deviceRef)`，即 **type-5**）。两家都从 `0x100` 起，但挂在不同的 client 上，因此不冲突。原文"本项目若需要私有通道，用 `0x200` 以上更安全"的建议仍然成立，但理由应改成"避开 Apple 在两种 client 上都已占用的 `0x100`..`0x106`"。`KNOWN`
2. **只有 7 个私有 selector，就把一个完整 Metal 驱动的对象生命周期撑起来了。** 创建/销毁各一对（通用 state、texture）、function IR 注册一个、compute pipeline 一个、能力表一个。本项目没有宿主，这 7 个全部不需要 —— 它们的对端在本项目里就是进程内的 Rust 渲染核心（`00-OVERVIEW.md` 第 6 节的窄 C ABI）。**这正好说明窄 C ABI 的函数数量级也在个位数到十位数，不是几百个。** `INFERRED`
3. `AppleParavirtBuffer` / `AppleParavirtPooledBuffer` / `AppleParavirtHeap` **不在上表里** —— buffer 与 heap 的创建走 `MTLIOAccelResource` 基类的 `IOAccelResourceCreate`（type-6 selector `0`），不走私有通道。即 Apple 把"有真实内存的东西"交给标准 IOAccel 路径，把"只是一组参数的东西"（state、pipeline、function）走私有通道。`KNOWN`

## 12. 未查清事项

### 12.1 `S-METAL` 的 selector 名字不可解析（已被绕开，但仍有一处留白）

`BLOCKED`。沿用并细化 `20-OBJC-DEVICE.md` 第 11.1 节。实测两类地址空间都在镜像外：

| 结构 | name 字段指向 | 是否可读 |
|---|---|---|
| 类 / 分类的 relative method list | `S-METAL` RVA `0x3B0000`..`0x450000` 区间（`__objc_methtype` 结束 +0x2EB26A 与 `__got` 起始 +0x35E34F40 之间的段空洞） | **否** |
| `__objc_selrefs` 槽的值 | 绝对 `0x7FF81F……` / `0x7FF820……`（另一镜像） | **否** |
| **协议的 method record 的 types 字段** | `__objc_methtype`（镜像内） | **是** |

所以：**encoding 全部可读，selector 名字全部不可读**。本文用 `S-DUMP`（已验证同序）补名字，用 `S-APV`（独立 Mach-O，名字在镜像内）补协议定义，两条路把这个缺口填满了。

**唯一剩下的留白**：`MTLCompiler` 的 pipeline 创建内部函数（`-[MTLCompiler newRenderPipelineStateWithDescriptorInternal:options:reflection:destinationBinaryArchive:error:compilerTask:completionHandler:]`，`S-METAL` +0x18F8A6，及其 5 个 `_block_invoke`）里，**哪一条 `objc_msgSend` 对应 `newVertexVariantWithCompilerOutput:`、哪一条对应 `newRenderPipelineWithDescriptor:vertexVariant:fragmentVariant:errorMessage:`，按名字确证不了**。本文第 2.2 节把这一跳标为 `INFERRED`。

这不影响任何实现决策：第 2.3 节已经用"基类对这 5 个 selector 的实现全部 `return nil`"把**必经性**确证为 `KNOWN`，调用点的行号只是叙述细节。

取得方法，按代价排序：

1. 用整条 dyld shared cache（而非单镜像）建 IDB，或 `dyld_shared_cache_util -extract` 把持有 selector 字符串的那个镜像按同一 base 一起加载。
2. 仓库已有 `metal_drivers/dyld_shared_cache_x86_64.map`；若它含字符串区映射，可把 `0x7FF820076A7B` 这类地址归属到具体镜像。
3. 在目标 guest 上 `class_copyMethodList([_MTLDevice class], &n)` 打印全部 selector 名，与本文 RVA 对齐。属 `TESTED` 级，最可靠。

### 12.2 `getSupportedFamilies(10000)` 与 `(10002)` 的返回集合是否不同

`BLOCKED`（中优先）。本文第 5.1 节把 `featureProfile` 定为 10000，依据是"`initLimits` 对 10000/10001/10002 等价"。但 `featureProfile` 还喂给 `getSupportedFamilies(MTLDeviceFeatureProfile)`（`S-METAL` +0x11362C），它决定 `-[_MTLDevice supportsFamily:]` 的答案，而 WindowServer 与 AppKit 会查 `supportsFamily:`。

取得方法：反编译 `S-METAL` +0x11362C，枚举它对 10000 / 10001 / 10002 分别 push 进 `std::vector<int64_t>` 的 family 常量。代价是一个函数的反编译。**应在第一版实现前关闭。**

### 12.3 `MTLCompiler initWithTargetData:cacheUUID:pluginPath:device:compilerFlags:` 的 `compilerFlags` 语义

`BLOCKED`（中优先）。APV 传 `32`（`0x20`）。取得方法：在 `S-METAL` 中反编译 `-[MTLCompiler initWithTargetData:cacheUUID:pluginPath:device:compilerFlags:]`，枚举它对各个 bit 的分支。**本项目要自建 compiler plugin，这个值直接影响插件被怎么调用，必须查清。**

### 12.4 `libAppleParavirtCompilerPlugin.dylib` 未取得

`BLOCKED`（高优先，对分册 `30` / `31`）。该 dylib 是 `AppleParavirtGPUMetal.bundle/Contents/Resources/` 下的文件，仓库中**不存在**（全盘搜索 `*CompilerPlugin*` 零命中）。

它是本文第 2 节结论的另一半：驱动侧只收不透明字节，字节格式由这个 dylib 定义。**不拿到它就不知道 `MTLCompiler` 与 compiler plugin 之间的 C/ObjC 接口长什么样**，而本项目要自己写一个同位置的插件。

取得方法：从 `142-36613 - 26.7.2 macOS Tahoe (25G325)/InstallAssistant.pkg` 的 payload 里按路径 `System/Library/Extensions/AppleParavirtGPUMetal.bundle/Contents/Resources/` 抽取。`analysis/binaries/macos26-25G325-x86_64/payloadv2-full-index.tsv.zip` 应能定位。**这是 `30-SHADER-AIR.md` 的前置条件。**

备选路径：`MTLCompiler` 侧的插件加载代码（`S-METAL`）本身就定义了接口，反编译它可以在不拿到插件的情况下得到 ABI。

### 12.5 `AppleParavirtDevice` 的 `inst_start` 与 `S-METAL` 的 `MTLIOAccelDevice` 不一致

`KNOWN`（事实）/ `BLOCKED`（影响未评估）。`S-APV` 记录的父类 `instanceSize` 是 `0xD400`，而 `S-METAL` 的 `MTLIOAccelDevice` ivar 一直排到 `0xD490`（`20-OBJC-DEVICE.md` 第 4.3 节的 `_deviceWrapper`）。

这不是错误 —— ObjC runtime 在加载时会按真实父类大小滑动子类 ivar 偏移，这正是 `20-OBJC-DEVICE.md` 第 4.3 节"子类绝不能假定 `instanceSize`、必须通过 `_OBJC_IVAR_$_*` 符号访问"的原因。`S-APV` 确实全程这么做（导入了 7 个 `_OBJC_IVAR_$_MTLIOAccel*` / `_OBJC_IVAR_$__MTL*` 符号，第 6.5 节）。

但两个数字不一致也说明：**`S-APV`（安装资产）与 `S-METAL`（BaseSystem dyld cache）不是同一轮构建**。两者的 UUID 不同源，差异范围未评估。与 `20-OBJC-DEVICE.md` 第 11.4 节同属"BaseSystem 与 installed SystemOS 未比对"这一类。

取得方法：装机后取 `/System/Library/dyld/dyld_shared_cache_x86_64*` 重抽 Metal，比对 `MTLIOAccelDevice` 的 `instanceSize` 与本文全部 RVA。

### 12.6 `MTLDeviceSPI` 的 507 条未逐条抄入本文

不是 `BLOCKED`，是**刻意的取舍**（第 8.3 节）。逐条方法名在 `S-DUMP` 第 1574–2440 行，encoding 在 `S-METAL` `__objc_protolist` 的 `MTLDeviceSPI` method record 里，按同序配对（第 0.2 节已验证）。需要全表时用第 0.2 节的方法重新生成，不需要新证据。

### 12.7 全链路未实测

本文全部结论是静态分析（`KNOWN` / `INFERRED`），没有一条是 `TESTED`。

与 `20-OBJC-DEVICE.md` 第 11.5 节的第一个验收点合并后，验收条件修订为：kext 发布 `MetalPluginName`、实现 type-5 selector `0`/`2` 与 type-6 selector `9`/`0xA`；plugin 的 device 类继承 `MTLIOAccelDevice`，**只覆写 `featureProfile`（返回 10000）与 `name`**（`argumentBuffersSupport` 不必覆写，见第 5.2 节）；然后看 `MTLCopyAllDevices()` 是否返回该设备且不触发 `initLimits` 的五条断言。

第二个验收点（本文新增）：实现第 2.4 节的 8 个编译器接口 selector 与一个最小 compiler plugin，看 `newRenderPipelineStateWithDescriptor:error:` 是否能返回非 nil。由 `80-TEST-HARNESS.md` 定义。

## 附录 A — `S-APV` 的大表

`KNOWN`。全部取自 `S-APV` `__objc_classlist` / `__objc_protolist`，encoding 是实读字符串，RVA 是 IMP 地址（image base = 0）。“协议归属”列的 `req:P` / `opt:P` 表示该 selector 是协议 P 声明的必需 / 可选方法，`—` 表示不在任何已适配协议的闭包里（APV 私有，或基类的非协议虚方法）。

### A.1 `PGSerializerRenderCommandEncoder`（152 条，适配 `MTLRenderCommandEncoderSPI`）

| selector | x86_64 type encoding | `S-APV` RVA | 协议归属 |
|---|---|---|---|
| `split` | `v16@0:8` | `+0xE2D2` | — |
| `initWithCommandBuffer:descriptor:serializer:` | `@40@0:8@16@24@32` | `+0xE3F7` | — |
| `dealloc` | `v16@0:8` | `+0xE5EE` | — |
| `writeDescriptor` | `c16@0:8` | `+0xE664` | — |
| `beginSegment:protectionOptions:` | `v28@0:8c16Q20` | `+0xF367` | — |
| `addRenderTargetReferences` | `c16@0:8` | `+0xF380` | — |
| `handleSplits` | `c16@0:8` | `+0xF729` | — |
| `flushWrites` | `v16@0:8` | `+0xFAC4` | — |
| `drawPrimitives:vertexStart:vertexCount:instanceCount:` | `v48@0:8Q16Q24Q32Q40` | `+0xFE1F` | `req:MTLRenderCommandEncoder` |
| `drawPrimitives:vertexStart:vertexCount:` | `v40@0:8Q16Q24Q32` | `+0xFF2F` | `req:MTLRenderCommandEncoder` |
| `drawPrimitives:vertexStart:vertexCount:instanceCount:baseInstance:` | `v56@0:8Q16Q24Q32Q40Q48` | `+0x10023` | `req:MTLRenderCommandEncoder` |
| `drawIndexedPrimitives:indexCount:indexType:indexBuffer:indexBufferOffset:instanceCount:` | `v64@0:8Q16Q24Q32@40Q48Q56` | `+0x1014E` | `req:MTLRenderCommandEncoder` |
| `drawIndexedPrimitives:indexCount:indexType:indexBuffer:indexBufferOffset:` | `v56@0:8Q16Q24Q32@40Q48` | `+0x10302` | `req:MTLRenderCommandEncoder` |
| `drawIndexedPrimitives:indexCount:indexType:indexBuffer:indexBufferOffset:instanceCount:baseVertex:baseInstance:` | `v80@0:8Q16Q24Q32@40Q48Q56q64Q72` | `+0x1049A` | `req:MTLRenderCommandEncoder` |
| `drawPatches:patchStart:patchCount:patchIndexBuffer:patchIndexBufferOffset:instanceCount:baseInstance:` | `v72@0:8Q16Q24Q32@40Q48Q56Q64` | `+0x10773` | `req:MTLRenderCommandEncoder` |
| `drawIndexedPatches:patchStart:patchCount:patchIndexBuffer:patchIndexBufferOffset:controlPointIndexBuffer:controlPointIndexBufferOffset:instanceCount:baseInstance:` | `v88@0:8Q16Q24Q32@40Q48@56Q64Q72Q80` | `+0x10962` | `req:MTLRenderCommandEncoder` |
| `drawPrimitives:indirectBuffer:indirectBufferOffset:` | `v40@0:8Q16@24Q32` | `+0x10BC9` | `req:MTLRenderCommandEncoder` |
| `drawIndexedPrimitives:indexType:indexBuffer:indexBufferOffset:indirectBuffer:indirectBufferOffset:` | `v64@0:8Q16Q24@32Q40@48Q56` | `+0x10CD8` | `req:MTLRenderCommandEncoder` |
| `drawPatches:patchIndexBuffer:patchIndexBufferOffset:indirectBuffer:indirectBufferOffset:` | `v56@0:8Q16@24Q32@40Q48` | `+0x10E6B` | `req:MTLRenderCommandEncoder` |
| `drawIndexedPatches:patchIndexBuffer:patchIndexBufferOffset:controlPointIndexBuffer:controlPointIndexBufferOffset:indirectBuffer:indirectBufferOffset:` | `v72@0:8Q16@24Q32@40Q48@56Q64` | `+0x10FEB` | `req:MTLRenderCommandEncoder` |
| `executeCommandsInBuffer:indirectBuffer:indirectBufferOffset:` | `v40@0:8@16@24Q32` | `+0x11181` | `req:MTLRenderCommandEncoder` |
| `executeCommandsInBuffer:withRange:` | `v40@0:8@16{_NSRange=QQ}24` | `+0x112E5` | `req:MTLRenderCommandEncoder` |
| `memoryBarrierWithResources:count:afterStages:beforeStages:` | `v48@0:8r^@16Q24Q32Q40` | `+0x113E9` | `req:MTLRenderCommandEncoder` |
| `memoryBarrierWithScope:afterStages:beforeStages:` | `v40@0:8Q16Q24Q32` | `+0x1152E` | `req:MTLRenderCommandEncoder` |
| `updateFence:afterStages:` | `v32@0:8@16Q24` | `+0x11573` | `req:MTLRenderCommandEncoder` |
| `waitForFence:beforeStages:` | `v32@0:8@16Q24` | `+0x11629` | `req:MTLRenderCommandEncoder` |
| `setBlendColorRed:green:blue:alpha:` | `v32@0:8f16f20f24f28` | `+0x116DF` | `req:MTLRenderCommandEncoder` |
| `setColorStoreAction:atIndex:` | `v32@0:8Q16Q24` | `+0x11744` | `req:MTLRenderCommandEncoder` |
| `setColorStoreActionOptions:atIndex:` | `v32@0:8Q16Q24` | `+0x11778` | `req:MTLRenderCommandEncoder` |
| `setCullMode:` | `v24@0:8Q16` | `+0x117AC` | `req:MTLRenderCommandEncoder` |
| `setDepthBias:slopeScale:clamp:` | `v28@0:8f16f20f24` | `+0x117DB` | `req:MTLRenderCommandEncoder` |
| `setDepthClipMode:` | `v24@0:8Q16` | `+0x11831` | `req:MTLRenderCommandEncoder` |
| `setDepthStencilState:` | `v24@0:8@16` | `+0x11860` | `req:MTLRenderCommandEncoder` |
| `setDepthStoreAction:` | `v24@0:8Q16` | `+0x11951` | `req:MTLRenderCommandEncoder` |
| `setDepthStoreActionOptions:` | `v24@0:8Q16` | `+0x11980` | `req:MTLRenderCommandEncoder` |
| `setFragmentBufferOffset:atIndex:` | `v32@0:8Q16Q24` | `+0x119AF` | `req:MTLRenderCommandEncoder` |
| `setFragmentBuffer:offset:atIndex:` | `v40@0:8@16Q24Q32` | `+0x11A24` | `req:MTLRenderCommandEncoder` |
| `setFragmentBuffers:offsets:withRange:` | `v48@0:8r^@16r^Q24{_NSRange=QQ}32` | `+0x11A7B` | `req:MTLRenderCommandEncoder` |
| `setFragmentBytes:length:atIndex:` | `v40@0:8r^v16Q24Q32` | `+0x11AB4` | `req:MTLRenderCommandEncoder` |
| `setFragmentSamplerState:atIndex:` | `v32@0:8@16Q24` | `+0x11AF0` | `req:MTLRenderCommandEncoder` |
| `setFragmentSamplerStates:withRange:` | `v40@0:8r^@16{_NSRange=QQ}24` | `+0x11B2F` | `req:MTLRenderCommandEncoder` |
| `setFragmentSamplerState:lodMinClamp:lodMaxClamp:atIndex:` | `v40@0:8@16f24f28Q32` | `+0x11B5E` | `req:MTLRenderCommandEncoder` |
| `setFragmentSamplerStates:lodMinClamps:lodMaxClamps:withRange:` | `v56@0:8r^@16r^f24r^f32{_NSRange=QQ}40` | `+0x11BC1` | `req:MTLRenderCommandEncoder` |
| `setFragmentTexture:atIndex:` | `v32@0:8@16Q24` | `+0x11BF9` | `req:MTLRenderCommandEncoder` |
| `setFragmentTextures:withRange:` | `v40@0:8r^@16{_NSRange=QQ}24` | `+0x11C48` | `req:MTLRenderCommandEncoder` |
| `setFrontFacingWinding:` | `v24@0:8Q16` | `+0x11C84` | `req:MTLRenderCommandEncoder` |
| `setRenderPipelineState:` | `v24@0:8@16` | `+0x11CB3` | `req:MTLRenderCommandEncoder` |
| `setScissorRect:` | `v48@0:8{?=QQQQ}16` | `+0x11D8B` | `req:MTLRenderCommandEncoder` |
| `setScissorRects:count:` | `v32@0:8r^{?=QQQQ}16Q24` | `+0x11DBF` | `req:MTLRenderCommandEncoder` |
| `setStencilFrontReferenceValue:backReferenceValue:` | `v24@0:8I16I20` | `+0x11E1E` | `req:MTLRenderCommandEncoder` |
| `setStencilReferenceValue:` | `v20@0:8I16` | `+0x11E51` | `req:MTLRenderCommandEncoder` |
| `setStencilStoreAction:` | `v24@0:8Q16` | `+0x11E65` | `req:MTLRenderCommandEncoder` |
| `setStencilStoreActionOptions:` | `v24@0:8Q16` | `+0x11E94` | `req:MTLRenderCommandEncoder` |
| `setTessellationFactorBuffer:offset:instanceStride:` | `v40@0:8@16Q24Q32` | `+0x11EC3` | `req:MTLRenderCommandEncoder` |
| `setTessellationFactorScale:` | `v20@0:8f16` | `+0x11FAB` | `req:MTLRenderCommandEncoder` |
| `setTriangleFillMode:` | `v24@0:8Q16` | `+0x11FE3` | `req:MTLRenderCommandEncoder` |
| `setVertexBufferOffset:atIndex:` | `v32@0:8Q16Q24` | `+0x12012` | `req:MTLRenderCommandEncoder` |
| `setVertexBuffer:offset:atIndex:` | `v40@0:8@16Q24Q32` | `+0x12087` | `req:MTLRenderCommandEncoder` |
| `setVertexBuffers:offsets:withRange:` | `v48@0:8r^@16r^Q24{_NSRange=QQ}32` | `+0x120DE` | `req:MTLRenderCommandEncoder` |
| `setVertexBytes:length:atIndex:` | `v40@0:8r^v16Q24Q32` | `+0x12117` | `req:MTLRenderCommandEncoder` |
| `setVertexBuffer:offset:attributeStride:atIndex:` | `v48@0:8@16Q24Q32Q40` | `+0x12153` | `req:MTLRenderCommandEncoder` |
| `setVertexBuffers:offsets:attributeStrides:withRange:` | `v56@0:8r^@16r^Q24r^Q32{_NSRange=QQ}40` | `+0x121CC` | `req:MTLRenderCommandEncoder` |
| `setVertexBufferOffset:attributeStride:atIndex:` | `v40@0:8Q16Q24Q32` | `+0x12227` | `req:MTLRenderCommandEncoder` |
| `setVertexBytes:length:attributeStride:atIndex:` | `v48@0:8r^v16Q24Q32Q40` | `+0x12279` | `req:MTLRenderCommandEncoder` |
| `setVertexSamplerState:atIndex:` | `v32@0:8@16Q24` | `+0x122C2` | `req:MTLRenderCommandEncoder` |
| `setVertexSamplerStates:withRange:` | `v40@0:8r^@16{_NSRange=QQ}24` | `+0x12301` | `req:MTLRenderCommandEncoder` |
| `setVertexSamplerState:lodMinClamp:lodMaxClamp:atIndex:` | `v40@0:8@16f24f28Q32` | `+0x12330` | `req:MTLRenderCommandEncoder` |
| `setVertexSamplerStates:lodMinClamps:lodMaxClamps:withRange:` | `v56@0:8r^@16r^f24r^f32{_NSRange=QQ}40` | `+0x12393` | `req:MTLRenderCommandEncoder` |
| `setVertexTexture:atIndex:` | `v32@0:8@16Q24` | `+0x123CB` | `req:MTLRenderCommandEncoder` |
| `setVertexTextures:withRange:` | `v40@0:8r^@16{_NSRange=QQ}24` | `+0x1241A` | `req:MTLRenderCommandEncoder` |
| `setViewport:` | `v64@0:8{?=dddddd}16` | `+0x12456` | `req:MTLRenderCommandEncoder` |
| `setViewports:count:` | `v32@0:8r^{?=dddddd}16Q24` | `+0x12492` | `req:MTLRenderCommandEncoder` |
| `setVisibilityResultMode:offset:` | `v32@0:8Q16Q24` | `+0x12519` | `req:MTLRenderCommandEncoder` |
| `textureBarrier` | `v16@0:8` | `+0x1254E` | `req:MTLRenderCommandEncoder` |
| `addSplitHandler:` | `v24@0:8@?16` | `+0x12567` | `req:MTLRenderCommandEncoderSPI` |
| `setDepthClipModeSPI:` | `v24@0:8Q16` | `+0x1256D` | `req:MTLRenderCommandEncoderSPI` |
| `isMemorylessRender` | `c16@0:8` | `+0x1B0E1` | `req:MTLRenderCommandEncoderSPI` |
| `setFragmentTexture:atTextureIndex:samplerState:atSamplerIndex:` | `v48@0:8@16Q24@32Q40` | `+0x12574` | `req:MTLRenderCommandEncoderSPI` |
| `setLineWidth:` | `v20@0:8f16` | `+0x125B6` | `req:MTLRenderCommandEncoderSPI` |
| `useHeap:stages:` | `v32@0:8@16Q24` | `+0x125EE` | `req:MTLRenderCommandEncoder` |
| `useHeaps:count:stages:` | `v40@0:8r^@16Q24Q32` | `+0x1261B` | `req:MTLRenderCommandEncoder` |
| `useResource:usage:stages:` | `v40@0:8@16Q24Q32` | `+0x1275E` | `req:MTLRenderCommandEncoder` |
| `useResources:count:usage:stages:` | `v48@0:8r^@16Q24Q32Q40` | `+0x1278E` | `req:MTLRenderCommandEncoder` |
| `dispatchThreadsPerTile:` | `v40@0:8{?=QQQ}16` | `+0x128EE` | `req:MTLRenderCommandEncoder` |
| `setThreadgroupMemoryLength:offset:atIndex:` | `v40@0:8Q16Q24Q32` | `+0x129A1` | `req:MTLRenderCommandEncoder` |
| `setTileBuffer:offset:atIndex:` | `v40@0:8@16Q24Q32` | `+0x129F2` | `req:MTLRenderCommandEncoder` |
| `setTileBufferOffset:atIndex:` | `v32@0:8Q16Q24` | `+0x12A54` | `req:MTLRenderCommandEncoder` |
| `setTileBuffers:offsets:withRange:` | `v48@0:8r^@16r^Q24{_NSRange=QQ}32` | `+0x12AD7` | `req:MTLRenderCommandEncoder` |
| `setTileBytes:length:atIndex:` | `v40@0:8r^v16Q24Q32` | `+0x12B20` | `req:MTLRenderCommandEncoder` |
| `setTileSamplerState:atIndex:` | `v32@0:8@16Q24` | `+0x12B69` | `req:MTLRenderCommandEncoder` |
| `setTileSamplerStates:withRange:` | `v40@0:8r^@16{_NSRange=QQ}24` | `+0x12BB3` | `req:MTLRenderCommandEncoder` |
| `setTileSamplerState:lodMinClamp:lodMaxClamp:atIndex:` | `v40@0:8@16f24f28Q32` | `+0x12BEF` | `req:MTLRenderCommandEncoder` |
| `setTileSamplerStates:lodMinClamps:lodMaxClamps:withRange:` | `v56@0:8r^@16r^f24r^f32{_NSRange=QQ}40` | `+0x12C5A` | `req:MTLRenderCommandEncoder` |
| `setTileTexture:atIndex:` | `v32@0:8@16Q24` | `+0x12CA2` | `req:MTLRenderCommandEncoder` |
| `setTileTextures:withRange:` | `v40@0:8r^@16{_NSRange=QQ}24` | `+0x12CFC` | `req:MTLRenderCommandEncoder` |
| `dispatchThreadsPerTile:inRegion:` | `v88@0:8{?=QQQ}16{?={?=QQQ}{?=QQQ}}40` | `+0x12D45` | `opt:MTLRenderCommandEncoderSPI` |
| `dispatchThreadsPerTile:inRegion:withRenderTargetArrayIndex:` | `v92@0:8{?=QQQ}16{?={?=QQQ}{?=QQQ}}40I88` | `+0x12E13` | `opt:MTLRenderCommandEncoderSPI` |
| `setVertexAmplificationMode:value:` | `v32@0:8Q16Q24` | `+0x12EEA` | `req:MTLRenderCommandEncoderSPI` |
| `setVertexAmplificationCount:viewMappings:` | `v32@0:8Q16r^{?=II}24` | `+0x12F2B` | `req:MTLRenderCommandEncoder` |
| `sampleCountersInBuffer:atSampleIndex:withBarrier:` | `v36@0:8@16Q24c32` | `+0x1B105` | `req:MTLRenderCommandEncoder` |
| `getType` | `Q16@0:8` | `+0x12FC0` | — |
| `fixStoreActions:` | `v24@0:8@16` | `+0x12FC8` | — |
| `forceStoreActionsForPosition:` | `v24@0:8Q16` | `+0x1315D` | — |
| `forceLoadActions` | `v16@0:8` | `+0x1320D` | — |
| `setEncoderPosition:` | `v24@0:8Q16` | `+0x13254` | — |
| `setVertexVisibleFunctionTable:atBufferIndex:` | `v32@0:8@16Q24` | `+0x132CA` | `req:MTLRenderCommandEncoder` |
| `setVertexVisibleFunctionTables:withBufferRange:` | `v40@0:8r^@16{_NSRange=QQ}24` | `+0x132EB` | `req:MTLRenderCommandEncoder` |
| `setFragmentVisibleFunctionTable:atBufferIndex:` | `v32@0:8@16Q24` | `+0x1330C` | `req:MTLRenderCommandEncoder` |
| `setFragmentVisibleFunctionTables:withBufferRange:` | `v40@0:8r^@16{_NSRange=QQ}24` | `+0x1332D` | `req:MTLRenderCommandEncoder` |
| `setTileVisibleFunctionTable:atBufferIndex:` | `v32@0:8@16Q24` | `+0x1334E` | `req:MTLRenderCommandEncoder` |
| `setTileVisibleFunctionTables:withBufferRange:` | `v40@0:8r^@16{_NSRange=QQ}24` | `+0x1336F` | `req:MTLRenderCommandEncoder` |
| `setObjectVisibleFunctionTable:atBufferIndex:` | `v32@0:8@16Q24` | `+0x13390` | `req:MTLRenderCommandEncoderSPI` |
| `setObjectVisibleFunctionTables:withBufferRange:` | `v40@0:8r^@16{_NSRange=QQ}24` | `+0x133B1` | `req:MTLRenderCommandEncoderSPI` |
| `setMeshVisibleFunctionTable:atBufferIndex:` | `v32@0:8@16Q24` | `+0x133D2` | `req:MTLRenderCommandEncoderSPI` |
| `setMeshVisibleFunctionTables:withBufferRange:` | `v40@0:8r^@16{_NSRange=QQ}24` | `+0x133F3` | `req:MTLRenderCommandEncoderSPI` |
| `setVertexIntersectionFunctionTable:atBufferIndex:` | `v32@0:8@16Q24` | `+0x13414` | `req:MTLRenderCommandEncoder` |
| `setVertexIntersectionFunctionTables:withBufferRange:` | `v40@0:8r^@16{_NSRange=QQ}24` | `+0x13435` | `req:MTLRenderCommandEncoder` |
| `setFragmentIntersectionFunctionTable:atBufferIndex:` | `v32@0:8@16Q24` | `+0x13456` | `req:MTLRenderCommandEncoder` |
| `setFragmentIntersectionFunctionTables:withBufferRange:` | `v40@0:8r^@16{_NSRange=QQ}24` | `+0x13477` | `req:MTLRenderCommandEncoder` |
| `setTileIntersectionFunctionTable:atBufferIndex:` | `v32@0:8@16Q24` | `+0x13498` | `req:MTLRenderCommandEncoder` |
| `setTileIntersectionFunctionTables:withBufferRange:` | `v40@0:8r^@16{_NSRange=QQ}24` | `+0x134B9` | `req:MTLRenderCommandEncoder` |
| `setVertexAccelerationStructure:atBufferIndex:` | `v32@0:8@16Q24` | `+0x134DA` | `req:MTLRenderCommandEncoder` |
| `setFragmentAccelerationStructure:atBufferIndex:` | `v32@0:8@16Q24` | `+0x134FB` | `req:MTLRenderCommandEncoder` |
| `setTileAccelerationStructure:atBufferIndex:` | `v32@0:8@16Q24` | `+0x1351C` | `req:MTLRenderCommandEncoder` |
| `setObjectIntersectionFunctionTable:atBufferIndex:` | `v32@0:8@16Q24` | `+0x1353D` | `opt:MTLRenderCommandEncoderSPI` |
| `setObjectIntersectionFunctionTables:withBufferRange:` | `v40@0:8r^@16{_NSRange=QQ}24` | `+0x1355E` | `opt:MTLRenderCommandEncoderSPI` |
| `setObjectAccelerationStructure:atBufferIndex:` | `v32@0:8@16Q24` | `+0x1357F` | `opt:MTLRenderCommandEncoderSPI` |
| `setMeshIntersectionFunctionTable:atBufferIndex:` | `v32@0:8@16Q24` | `+0x135A0` | `opt:MTLRenderCommandEncoderSPI` |
| `setMeshIntersectionFunctionTables:withBufferRange:` | `v40@0:8r^@16{_NSRange=QQ}24` | `+0x135C1` | `opt:MTLRenderCommandEncoderSPI` |
| `setMeshAccelerationStructure:atBufferIndex:` | `v32@0:8@16Q24` | `+0x135E2` | `opt:MTLRenderCommandEncoderSPI` |
| `setAlphaTestReferenceValue:` | `v20@0:8f16` | `+0x13603` | `opt:MTLRenderCommandEncoderSPI` |
| `setPointSize:` | `v20@0:8f16` | `+0x13670` | `opt:MTLRenderCommandEncoderSPI` |
| `setClipPlane:p2:p3:p4:atIndex:` | `v40@0:8f16f20f24f28Q32` | `+0x136DD` | `opt:MTLRenderCommandEncoderSPI` |
| `setVertexSamplerState:lodMinClamp:lodMaxClamp:lodBias:atIndex:` | `v44@0:8@16f24f28f32Q36` | `+0x13781` | `opt:MTLRenderCommandEncoderSPI` |
| `setFragmentSamplerState:lodMinClamp:lodMaxClamp:lodBias:atIndex:` | `v44@0:8@16f24f28f32Q36` | `+0x138B5` | `opt:MTLRenderCommandEncoderSPI` |
| `setViewportTransformEnabled:` | `v20@0:8c16` | `+0x139E9` | `opt:MTLRenderCommandEncoderSPI` |
| `setProvokingVertexMode:` | `v24@0:8Q16` | `+0x13A50` | `opt:MTLRenderCommandEncoderSPI` |
| `setPrimitiveRestartEnabled:` | `v20@0:8c16` | `+0x13AB5` | `opt:MTLRenderCommandEncoderSPI` |
| `setPrimitiveRestartEnabled:index:` | `v28@0:8c16Q20` | `+0x13B11` | `opt:MTLRenderCommandEncoderSPI` |
| `setTriangleFrontFillMode:backFillMode:` | `v32@0:8Q16Q24` | `+0x13B83` | `opt:MTLRenderCommandEncoderSPI` |
| `setTransformFeedbackState:` | `v24@0:8Q16` | `+0x13BF0` | `opt:MTLRenderCommandEncoderSPI` |
| `setDepthCleared` | `v16@0:8` | `+0x13C55` | `opt:MTLRenderCommandEncoderSPI` |
| `setStencilCleared` | `v16@0:8` | `+0x13CA3` | `opt:MTLRenderCommandEncoderSPI` |
| `setColorResolveTexture:slice:depthPlane:level:yInvert:atIndex:` | `v60@0:8@16Q24Q32Q40c48Q52` | `+0x13CF1` | `opt:MTLRenderCommandEncoderSPI` |
| `setDepthResolveTexture:slice:depthPlane:level:yInvert:` | `v52@0:8@16Q24Q32Q40c48` | `+0x13E00` | `opt:MTLRenderCommandEncoderSPI` |
| `setStencilResolveTexture:slice:depthPlane:level:yInvert:` | `v52@0:8@16Q24Q32Q40c48` | `+0x13F06` | `opt:MTLRenderCommandEncoderSPI` |
| `getTileDimensions:` | `v24@0:8^{?=SS}16` | `+0x1400C` | — |
| `setDepthTestMinBound:maxBound:` | `v24@0:8f16f20` | `+0x141A3` | `req:MTLRenderCommandEncoder` |
| `tileWidth` | `Q16@0:8` | `+0x141C4` | `req:MTLRenderCommandEncoder` |
| `tileHeight` | `Q16@0:8` | `+0x141D5` | `req:MTLRenderCommandEncoder` |
| `.cxx_destruct` | `v16@0:8` | `+0x141E6` | — |
| `.cxx_construct` | `@16@0:8` | `+0x14235` | — |

### A.2 `PGSerializerComputeCommandEncoder`（58 条，适配 `MTLComputeCommandEncoderSPI`）

| selector | x86_64 type encoding | `S-APV` RVA | 协议归属 |
|---|---|---|---|
| `setCurrentDispatchType:` | `v24@0:8Q16` | `+0x15802` | — |
| `initWithCommandBuffer:descriptor:serializer:` | `@40@0:8@16@24@32` | `+0x15813` | — |
| `reattachToCommandStream:` | `v24@0:8@16` | `+0x15983` | — |
| `endEncoding` | `v16@0:8` | `+0x159EF` | `req:MTLCommandEncoder` |
| `beginSegment:protectionOptions:` | `v28@0:8c16Q20` | `+0x15A4B` | — |
| `writeDescriptor` | `c16@0:8` | `+0x15A67` | — |
| `handleSplits` | `c16@0:8` | `+0x15AB7` | — |
| `flushWrites` | `v16@0:8` | `+0x15C0B` | — |
| `maybeEmitSerialBarrier` | `v16@0:8` | `+0x15D70` | — |
| `dispatchThreadgroups:threadsPerThreadgroup:` | `v64@0:8{?=QQQ}16{?=QQQ}40` | `+0x15DB3` | `req:MTLComputeCommandEncoder` |
| `dispatchThreadgroupsWithIndirectBuffer:indirectBufferOffset:threadsPerThreadgroup:` | `v56@0:8@16Q24{?=QQQ}32` | `+0x15E7C` | `req:MTLComputeCommandEncoder` |
| `dispatchThreads:threadsPerThreadgroup:` | `v64@0:8{?=QQQ}16{?=QQQ}40` | `+0x15FA3` | `req:MTLComputeCommandEncoder` |
| `dispatchThreadsWithIndirectBuffer:indirectBufferOffset:` | `v32@0:8@16Q24` | `+0x1606C` | `opt:MTLComputeCommandEncoderSPI` |
| `setBuffer:offset:atIndex:` | `v40@0:8@16Q24Q32` | `+0x1619A` | `req:MTLComputeCommandEncoder` |
| `setBufferOffset:atIndex:` | `v32@0:8Q16Q24` | `+0x161F4` | `req:MTLComputeCommandEncoder` |
| `setBuffers:offsets:withRange:` | `v48@0:8r^@16r^Q24{_NSRange=QQ}32` | `+0x16269` | `req:MTLComputeCommandEncoder` |
| `setBytes:length:atIndex:` | `v40@0:8r^v16Q24Q32` | `+0x162A5` | `req:MTLComputeCommandEncoder` |
| `setBuffer:offset:attributeStride:atIndex:` | `v48@0:8@16Q24Q32Q40` | `+0x162E1` | `req:MTLComputeCommandEncoder` |
| `setBuffers:offsets:attributeStrides:withRange:` | `v56@0:8r^@16r^Q24r^Q32{_NSRange=QQ}40` | `+0x1635A` | `req:MTLComputeCommandEncoder` |
| `setBufferOffset:attributeStride:atIndex:` | `v40@0:8Q16Q24Q32` | `+0x163B5` | `req:MTLComputeCommandEncoder` |
| `setBytes:length:attributeStride:atIndex:` | `v48@0:8r^v16Q24Q32Q40` | `+0x16445` | `req:MTLComputeCommandEncoder` |
| `setComputePipelineState:` | `v24@0:8@16` | `+0x1648E` | `req:MTLComputeCommandEncoder` |
| `setSamplerState:atIndex:` | `v32@0:8@16Q24` | `+0x1656B` | `req:MTLComputeCommandEncoder` |
| `setSamplerState:lodMinClamp:lodMaxClamp:atIndex:` | `v40@0:8@16f24f28Q32` | `+0x165AA` | `req:MTLComputeCommandEncoder` |
| `setSamplerStates:lodMinClamps:lodMaxClamps:withRange:` | `v56@0:8r^@16r^f24r^f32{_NSRange=QQ}40` | `+0x1660D` | `req:MTLComputeCommandEncoder` |
| `setSamplerStates:withRange:` | `v40@0:8r^@16{_NSRange=QQ}24` | `+0x16645` | `req:MTLComputeCommandEncoder` |
| `setStageInRegion:` | `v64@0:8{?={?=QQQ}{?=QQQ}}16` | `+0x16674` | `req:MTLComputeCommandEncoder` |
| `setStageInRegionWithIndirectBuffer:indirectBufferOffset:` | `v32@0:8@16Q24` | `+0x166B8` | `req:MTLComputeCommandEncoder` |
| `setTexture:atIndex:` | `v32@0:8@16Q24` | `+0x1677E` | `req:MTLComputeCommandEncoder` |
| `setTextures:withRange:` | `v40@0:8r^@16{_NSRange=QQ}24` | `+0x167CD` | `req:MTLComputeCommandEncoder` |
| `setThreadgroupMemoryLength:atIndex:` | `v32@0:8Q16Q24` | `+0x16809` | `req:MTLComputeCommandEncoder` |
| `updateFence:` | `v24@0:8@16` | `+0x1683D` | `req:MTLComputeCommandEncoder` |
| `waitForFence:` | `v24@0:8@16` | `+0x168F7` | `req:MTLComputeCommandEncoder` |
| `newKernelDebugInfo` | `@16@0:8` | `+0x169A6` | `req:MTLComputeCommandEncoderSPI` |
| `memoryBarrierWithResources:count:` | `v32@0:8r^@16Q24` | `+0x169AE` | `req:MTLComputeCommandEncoder` |
| `memoryBarrierWithScope:` | `v24@0:8Q16` | `+0x16ABE` | `req:MTLComputeCommandEncoder` |
| `getType` | `Q16@0:8` | `+0x16B36` | — |
| `sampleCountersInBuffer:atSampleIndex:withBarrier:` | `v36@0:8@16Q24c32` | `+0x1BCBF` | `req:MTLComputeCommandEncoder` |
| `setImageblockWidth:height:` | `v32@0:8Q16Q24` | `+0x16B42` | `req:MTLComputeCommandEncoder` |
| `executeCommandsInBuffer:withRange:` | `v40@0:8@16{_NSRange=QQ}24` | `+0x16B83` | `req:MTLComputeCommandEncoder` |
| `executeCommandsInBuffer:indirectBuffer:indirectBufferOffset:` | `v40@0:8@16@24Q32` | `+0x16C94` | `req:MTLComputeCommandEncoder` |
| `setAccelerationStructure:atBufferIndex:` | `v32@0:8@16Q24` | `+0x16E08` | `req:MTLComputeCommandEncoder` |
| `setVisibleFunctionTable:atBufferIndex:` | `v32@0:8@16Q24` | `+0x16E29` | `req:MTLComputeCommandEncoder` |
| `setVisibleFunctionTables:withBufferRange:` | `v40@0:8r^@16{_NSRange=QQ}24` | `+0x16E4A` | `req:MTLComputeCommandEncoder` |
| `setIntersectionFunctionTable:atBufferIndex:` | `v32@0:8@16Q24` | `+0x16E6B` | `req:MTLComputeCommandEncoder` |
| `setIntersectionFunctionTables:withBufferRange:` | `v40@0:8r^@16{_NSRange=QQ}24` | `+0x16E8C` | `req:MTLComputeCommandEncoder` |
| `encodeStartDoWhile` | `v16@0:8` | `+0x16EAD` | `opt:MTLComputeCommandEncoderSPI` |
| `encodeEndDoWhile:offset:comparison:referenceValue:` | `c44@0:8@16Q24Q32I40` | `+0x16EF7` | `opt:MTLComputeCommandEncoderSPI` |
| `encodeStartWhile:offset:comparison:referenceValue:` | `v44@0:8@16Q24Q32I40` | `+0x1706F` | `opt:MTLComputeCommandEncoderSPI` |
| `encodeEndWhile` | `c16@0:8` | `+0x1717D` | `opt:MTLComputeCommandEncoderSPI` |
| `encodeStartIf:offset:comparison:referenceValue:` | `v44@0:8@16Q24Q32I40` | `+0x17235` | `opt:MTLComputeCommandEncoderSPI` |
| `encodeStartElse` | `v16@0:8` | `+0x17343` | `opt:MTLComputeCommandEncoderSPI` |
| `encodeEndIf` | `c16@0:8` | `+0x1740E` | `opt:MTLComputeCommandEncoderSPI` |
| `insertCompressedTextureReinterpretationFlush` | `v16@0:8` | `+0x174CC` | `opt:MTLComputeCommandEncoderSPI` |
| `dispatchType` | `Q16@0:8` | `+0x17506` | `req:MTLComputeCommandEncoder` |
| `shouldAllowReattach` | `c16@0:8` | `+0x17517` | — |
| `.cxx_destruct` | `v16@0:8` | `+0x17528` | — |
| `.cxx_construct` | `@16@0:8` | `+0x17560` | — |

### A.3 `PGSerializerBlitCommandEncoder`（38 条，适配 `MTLBlitCommandEncoderSPI`）

| selector | x86_64 type encoding | `S-APV` RVA | 协议归属 |
|---|---|---|---|
| `initWithCommandBuffer:descriptor:serializer:` | `@40@0:8@16@24@32` | `+0x1417` | — |
| `beginSegment:protectionOptions:` | `v28@0:8c16Q20` | `+0x14AB` | — |
| `copyFromBuffer:sourceOffset:sourceBytesPerRow:sourceBytesPerImage:sourceSize:toTexture:destinationSlice:destinationLevel:destinationOrigin:` | `v120@0:8@16Q24Q32Q40{?=QQQ}48@72Q80Q88{?=QQQ}96` | `+0x14C7` | `req:MTLBlitCommandEncoder` |
| `copyFromBuffer:sourceOffset:sourceBytesPerRow:sourceBytesPerImage:sourceSize:toTexture:destinationSlice:destinationLevel:destinationOrigin:options:` | `v128@0:8@16Q24Q32Q40{?=QQQ}48@72Q80Q88{?=QQQ}96Q120` | `+0x152B` | `req:MTLBlitCommandEncoder` |
| `copyFromBuffer:sourceOffset:toBuffer:destinationOffset:size:` | `v56@0:8@16Q24@32Q40Q48` | `+0x1694` | `req:MTLBlitCommandEncoder` |
| `copyFromTexture:sourceSlice:sourceLevel:sourceOrigin:sourceSize:toBuffer:destinationOffset:destinationBytesPerRow:destinationBytesPerImage:` | `v120@0:8@16Q24Q32{?=QQQ}40{?=QQQ}64@88Q96Q104Q112` | `+0x17B5` | `req:MTLBlitCommandEncoder` |
| `copyFromTexture:sourceSlice:sourceLevel:sourceOrigin:sourceSize:toBuffer:destinationOffset:destinationBytesPerRow:destinationBytesPerImage:options:` | `v128@0:8@16Q24Q32{?=QQQ}40{?=QQQ}64@88Q96Q104Q112Q120` | `+0x180E` | `req:MTLBlitCommandEncoder` |
| `copyFromTexture:sourceSlice:sourceLevel:sourceOrigin:sourceSize:toTexture:destinationSlice:destinationLevel:destinationOrigin:` | `v136@0:8@16Q24Q32{?=QQQ}40{?=QQQ}64@88Q96Q104{?=QQQ}112` | `+0x196C` | `req:MTLBlitCommandEncoder` |
| `copyFromTexture:sourceSlice:sourceLevel:sourceOrigin:sourceSize:toTexture:destinationSlice:destinationLevel:destinationOrigin:options:` | `v144@0:8@16Q24Q32{?=QQQ}40{?=QQQ}64@88Q96Q104{?=QQQ}112Q136` | `+0x1AC7` | `req:MTLBlitCommandEncoderSPI` |
| `fillBuffer:range:value:` | `v44@0:8@16{_NSRange=QQ}24C40` | `+0x1C2A` | `req:MTLBlitCommandEncoder` |
| `generateMipmapsForTexture:` | `v24@0:8@16` | `+0x1D09` | `req:MTLBlitCommandEncoder` |
| `optimize:withCommand:` | `v28@0:8@16I24` | `+0x1DB9` | — |
| `optimize:slice:level:withCommand:` | `v44@0:8@16Q24Q32I40` | `+0x1E6E` | — |
| `optimizeContentsForCPUAccess:` | `v24@0:8@16` | `+0x1F39` | `req:MTLBlitCommandEncoder` |
| `optimizeContentsForCPUAccess:slice:level:` | `v40@0:8@16Q24Q32` | `+0x1F50` | `req:MTLBlitCommandEncoder` |
| `optimizeContentsForGPUAccess:` | `v24@0:8@16` | `+0x1F68` | `req:MTLBlitCommandEncoder` |
| `optimizeContentsForGPUAccess:slice:level:` | `v40@0:8@16Q24Q32` | `+0x1F7F` | `req:MTLBlitCommandEncoder` |
| `copyIndirectCommandBuffer:sourceRange:destination:destinationIndex:` | `v56@0:8@16{_NSRange=QQ}24@40Q48` | `+0x1F97` | `req:MTLBlitCommandEncoder` |
| `optimizeReset:withRange:withCommand:` | `v44@0:8@16{_NSRange=QQ}24I40` | `+0x20A6` | — |
| `resetCommandsInBuffer:withRange:` | `v40@0:8@16{_NSRange=QQ}24` | `+0x2171` | `req:MTLBlitCommandEncoder` |
| `optimizeIndirectCommandBuffer:withRange:` | `v40@0:8@16{_NSRange=QQ}24` | `+0x2189` | `req:MTLBlitCommandEncoder` |
| `synchronizeResource:` | `v24@0:8@16` | `+0x21A1` | `req:MTLBlitCommandEncoder` |
| `synchronizeTexture:slice:level:` | `v40@0:8@16Q24Q32` | `+0x2251` | `req:MTLBlitCommandEncoder` |
| `updateFence:` | `v24@0:8@16` | `+0x2319` | `req:MTLBlitCommandEncoder` |
| `waitForFence:` | `v24@0:8@16` | `+0x23C8` | `req:MTLBlitCommandEncoder` |
| `fillBuffer:range:pattern4:` | `v44@0:8@16{_NSRange=QQ}24I40` | `+0x2477` | `req:MTLBlitCommandEncoderSPI` |
| `fillTexture:level:slice:region:bytes:length:` | `v104@0:8@16Q24Q32{?={?=QQQ}{?=QQQ}}40r^v88Q96` | `+0x2567` | `req:MTLBlitCommandEncoderSPI` |
| `fillTexture:level:slice:region:color:` | `v120@0:8@16Q24Q32{?={?=QQQ}{?=QQQ}}40{?=dddd}88` | `+0x26DE` | `req:MTLBlitCommandEncoderSPI` |
| `fillTexture:level:slice:region:color:pixelFormat:` | `v128@0:8@16Q24Q32{?={?=QQQ}{?=QQQ}}40{?=dddd}88Q120` | `+0x2735` | `req:MTLBlitCommandEncoderSPI` |
| `invalidateCompressedTexture:` | `v24@0:8@16` | `+0x2868` | `req:MTLBlitCommandEncoderSPI` |
| `invalidateCompressedTexture:slice:level:` | `v40@0:8@16Q24Q32` | `+0x2929` | `req:MTLBlitCommandEncoderSPI` |
| `getType` | `Q16@0:8` | `+0x2A02` | — |
| `copyFromTexture:sourceSlice:sourceLevel:toTexture:destinationSlice:destinationLevel:sliceCount:levelCount:` | `v80@0:8@16Q24Q32@40Q48Q56Q64Q72` | `+0x2A0D` | `req:MTLBlitCommandEncoder` |
| `copyFromTexture:toTexture:` | `v32@0:8@16@24` | `+0x2B8C` | `req:MTLBlitCommandEncoder` |
| `getTextureAccessCounters:region:mipLevel:slice:resetCounters:countersBuffer:countersBufferOffset:` | `v108@0:8@16{?={?=QQQ}{?=QQQ}}24Q72Q80c88@92Q100` | `+0x2E95` | `opt:MTLBlitCommandEncoder` |
| `resetTextureAccessCounters:region:mipLevel:slice:` | `v88@0:8@16{?={?=QQQ}{?=QQQ}}24Q72Q80` | `+0x2EB6` | `opt:MTLBlitCommandEncoder` |
| `resolveCounters:inRange:destinationBuffer:destinationOffset:` | `v56@0:8@16{_NSRange=QQ}24@40Q48` | `+0x19412` | `req:MTLBlitCommandEncoder` |
| `sampleCountersInBuffer:atSampleIndex:withBarrier:` | `v36@0:8@16Q24c32` | `+0x19435` | `req:MTLBlitCommandEncoder` |

### A.4 `AppleParavirtBuffer`（18 条）

| selector | x86_64 type encoding | `S-APV` RVA | 协议归属 |
|---|---|---|---|
| `initWithDevice:withLength:withOptions:withPointer:withDeallocator:` | `@56@0:8@16Q24Q32^v40@?48` | `+0x15488` | — |
| `dealloc` | `v16@0:8` | `+0x155A2` | — |
| `isAliasable` | `c16@0:8` | `+0x1561D` | `req:MTLResource` |
| `makeAliasable` | `v16@0:8` | `+0x15625` | `req:MTLResource` |
| `newTextureWithDescriptor:offset:bytesPerRow:` | `@40@0:8@16Q24Q32` | `+0x1562B` | `req:MTLBuffer` |
| `newTiledTextureWithDescriptor:offset:bytesPerRow:` | `@40@0:8@16Q24Q32` | `+0x156CA` | `req:MTLBufferSPI` |
| `doesAliasAllResources:count:` | `c32@0:8r^@16Q24` | `+0x15750` | `req:MTLResourceSPI` |
| `doesAliasAnyResources:count:` | `c32@0:8r^@16Q24` | `+0x15758` | `req:MTLResourceSPI` |
| `doesAliasResource:` | `c24@0:8@16` | `+0x15760` | `req:MTLResourceSPI` |
| `isComplete` | `c16@0:8` | `+0x15768` | `req:MTLResourceSPI` |
| `isPurgeable` | `c16@0:8` | `+0x15770` | `req:MTLResourceSPI` |
| `waitUntilComplete` | `v16@0:8` | `+0x15778` | `req:MTLResourceSPI` |
| `bufferRef` | `I16@0:8` | `+0x1577E` | `req:PGSerializerBuffer` |
| `serializerResourceRef` | `I16@0:8` | `+0x1578E` | `req:PGSerializerResource` |
| `contents` | `^v16@0:8` | `+0x157A0` | `req:MTLBuffer` |
| `virtualAddress` | `^v16@0:8` | `+0x157B2` | — |
| `parentResourceOffset` | `Q16@0:8` | `+0x157D5` | `req:PGSerializerBuffer` |
| `shouldSyncInBlit` | `c16@0:8` | `+0x157E6` | `req:PGSerializerResource` |

### A.5 `AppleParavirtTexture`（25 条）

| selector | x86_64 type encoding | `S-APV` RVA | 协议归属 |
|---|---|---|---|
| `textureRef` | `I16@0:8` | `+0x7348` | `req:PGSerializerTexture` |
| `serializerResourceRef` | `I16@0:8` | `+0x7358` | `req:PGSerializerResource` |
| `initWithDevice:descriptor:` | `@32@0:8@16@24` | `+0x7368` | — |
| `initWithBuffer:descriptor:offset:bytesPerRow:` | `@48@0:8@16@24Q32Q40` | `+0x75D5` | — |
| `initWithTexture:pixelFormat:textureType:levels:slices:swizzle:` | `@76@0:8@16Q24Q32{_NSRange=QQ}40{_NSRange=QQ}56{?=CCCC}72` | `+0x7878` | — |
| `initTiledWithBuffer:descriptor:offset:bytesPerRow:` | `@48@0:8@16@24Q32Q40` | `+0x7BA7` | — |
| `initWithDevice:descriptor:iosurface:plane:field:` | `@56@0:8@16@24^{__IOSurface=}32Q40Q48` | `+0x7EBE` | — |
| `dealloc` | `v16@0:8` | `+0x8153` | — |
| `isAliasable` | `c16@0:8` | `+0x8266` | `req:MTLResource` |
| `makeAliasable` | `v16@0:8` | `+0x826E` | `req:MTLResource` |
| `getBytes:bytesPerRow:bytesPerImage:fromRegion:mipmapLevel:slice:` | `v104@0:8^v16Q24Q32{?={?=QQQ}{?=QQQ}}40Q88Q96` | `+0x8274` | `req:MTLTexture` |
| `modifiedImageLevel:slice:` | `v32@0:8Q16Q24` | `+0x85AF` | — |
| `replaceRegion:mipmapLevel:slice:withBytes:bytesPerRow:bytesPerImage:` | `v104@0:8{?={?=QQQ}{?=QQQ}}16Q64Q72r^v80Q88Q96` | `+0x8626` | `req:MTLTexture` |
| `doesAliasAllResources:count:` | `c32@0:8r^@16Q24` | `+0x89A5` | `req:MTLResourceSPI` |
| `doesAliasAnyResources:count:` | `c32@0:8r^@16Q24` | `+0x89AD` | `req:MTLResourceSPI` |
| `doesAliasResource:` | `c24@0:8@16` | `+0x89B5` | `req:MTLResourceSPI` |
| `newTextureViewWithPixelFormat:` | `@24@0:8Q16` | `+0x89BD` | `req:MTLTexture` |
| `newTextureViewWithPixelFormat:textureType:levels:slices:` | `@64@0:8Q16Q24{_NSRange=QQ}32{_NSRange=QQ}48` | `+0x8A5A` | `req:MTLTexture` |
| `newTextureViewWithPixelFormat:textureType:levels:slices:swizzle:` | `@68@0:8Q16Q24{_NSRange=QQ}32{_NSRange=QQ}48{?=CCCC}64` | `+0x8A85` | `req:MTLTexture` |
| `decompressPlaceholder:expandedTex:srcFormat:destFormat:width:height:destRowBytes:srcRowBytes:` | `v80@0:8r*16*24Q32Q40Q48Q56Q64Q72` | `+0x8AEF` | — |
| `decompressedPixelFormat` | `Q16@0:8` | `+0x8B04` | — |
| `didModifyData` | `v16@0:8` | `+0x8B1C` | `req:MTLTextureSPI` |
| `initWithSharedTextureHandle:device:descriptor:plane:` | `@48@0:8^{__IOSurface=}16@24@32Q40` | `+0x8B4C` | — |
| `shouldSyncInBlit` | `c16@0:8` | `+0x8EDC` | `req:PGSerializerResource` |
| `sparseSurfaceDefaultValue` | `Q16@0:8` | `+0x8EF7` | `req:MTLTextureSPI` |

### A.6 `PGSerializer`（95 条，APV 自建序列化器，对应本项目的窄 C ABI 边界）

| selector | x86_64 type encoding | `S-APV` RVA | 协议归属 |
|---|---|---|---|
| `initWithDevice:objectRefAllocator:deserializerVersion:` | `@36@0:8@16@24I32` | `+0x3BD4` | — |
| `initWithDevice:objectRefAllocator:` | `@32@0:8@16@24` | `+0x3C80` | — |
| `dealloc` | `v16@0:8` | `+0x3C95` | — |
| `newBufferRef` | `I16@0:8` | `+0x3CD8` | — |
| `releaseBufferRef:` | `v20@0:8I16` | `+0x3CEE` | — |
| `deleteBufferRef:allocator:` | `v28@0:8I16@20` | `+0x3CF4` | — |
| `newTextureRef` | `I16@0:8` | `+0x3D28` | — |
| `releaseTextureRef:` | `v20@0:8I16` | `+0x3D3E` | — |
| `deleteTextureRef:allocator:` | `v28@0:8I16@20` | `+0x3D44` | — |
| `newDepthStencilStateRef` | `I16@0:8` | `+0x3D78` | — |
| `releaseDepthStencilStateRef:` | `v20@0:8I16` | `+0x3D8E` | — |
| `deleteDepthStencilStateRef:allocator:` | `v28@0:8I16@20` | `+0x3D94` | — |
| `newSamplerStateRef` | `I16@0:8` | `+0x3DC8` | — |
| `releaseSamplerStateRef:` | `v20@0:8I16` | `+0x3DDE` | — |
| `deleteSamplerStateRef:allocator:` | `v28@0:8I16@20` | `+0x3DE4` | — |
| `newFunctionRef` | `I16@0:8` | `+0x3E18` | — |
| `releaseFunctionRef:` | `v20@0:8I16` | `+0x3E2E` | — |
| `deleteFunctionRef:allocator:` | `v28@0:8I16@20` | `+0x3E34` | — |
| `newComputePipelineStateRef` | `I16@0:8` | `+0x3E68` | — |
| `releaseComputePipelineStateRef:` | `v20@0:8I16` | `+0x3E7E` | — |
| `deleteComputePipelineStateRef:allocator:` | `v28@0:8I16@20` | `+0x3E84` | — |
| `newRenderPipelineStateRef` | `I16@0:8` | `+0x3EB8` | — |
| `releaseRenderPipelineStateRef:` | `v20@0:8I16` | `+0x3ECE` | — |
| `deleteRenderPipelineStateRef:allocator:` | `v28@0:8I16@20` | `+0x3ED4` | — |
| `newFenceRef` | `I16@0:8` | `+0x3F08` | — |
| `releaseFenceRef:` | `v20@0:8I16` | `+0x3F1E` | — |
| `deleteFenceRef:allocator:` | `v28@0:8I16@20` | `+0x3F24` | — |
| `newHeapRef` | `I16@0:8` | `+0x3F58` | — |
| `releaseHeapRef:` | `v20@0:8I16` | `+0x3F6E` | — |
| `deleteHeapRef:allocator:` | `v28@0:8I16@20` | `+0x3F74` | — |
| `newRasterizationRateMapRef` | `I16@0:8` | `+0x3FA8` | — |
| `releaseRasterizationRateMapRef:` | `v20@0:8I16` | `+0x3FBE` | — |
| `deleteRasterizationRateMapRef:allocator:` | `v28@0:8I16@20` | `+0x3FC4` | — |
| `newIndirectCommandBufferRef` | `I16@0:8` | `+0x3FF8` | — |
| `releaseIndirectCommandBufferRef:` | `v20@0:8I16` | `+0x400E` | — |
| `deleteIndirectCommandBufferRef:allocator:` | `v28@0:8I16@20` | `+0x4014` | — |
| `serializeTextureDescriptor:textureDescriptor:` | `v32@0:8^{?=b4b1b1b1b1b8b16IIISSSSQ}16@24` | `+0x4048` | — |
| `serializeTextureDescriptor2:textureDescriptor:` | `v32@0:8^{?=b4b1b1b1b1b16IIIISSSSQCCCC}16@24` | `+0x41DE` | — |
| `dataSizeForRegion:pixelFormat:bytesPerRow:bytesPerImage:` | `Q88@0:8{?={?=QQQ}{?=QQQ}}16Q64Q72Q80` | `+0x43F1` | — |
| `copyImageBytesFromSource:toDestination:dataSize:region:bytesPerRow:bytesPerImage:mipmapLevel:slice:texture:` | `v128@0:8*16*24Q32{?={?=QQQ}{?=QQQ}}40Q88Q96Q104Q112@120` | `+0x447B` | — |
| `newTextureViewWithPixelFormat:baseTexture:allocator:` | `I40@0:8Q16@24@32` | `+0x4647` | — |
| `newTextureWithDescriptor:heap:offset:useOffset:allocator:` | `I52@0:8@16@24Q32c40@44` | `+0x46C6` | — |
| `newTextureViewWithPixelFormat:textureType:levels:slices:baseTexture:allocator:` | `I80@0:8Q16Q24{_NSRange=QQ}32{_NSRange=QQ}48@64@72` | `+0x486A` | — |
| `newTextureViewWithPixelFormat:textureType:levels:slices:swizzle:baseTexture:allocator:` | `I84@0:8Q16Q24{_NSRange=QQ}32{_NSRange=QQ}48{?=CCCC}64@68@76` | `+0x490B` | — |
| `newFenceWithAllocator:` | `I24@0:8@16` | `+0x49D4` | — |
| `heapTextureSizeAndAlignWithDescriptor:allocator:` | `v32@0:8@16@24` | `+0x4A29` | — |
| `newTextureWithBuffer:descriptor:offset:bytesPerRow:allocator:` | `I56@0:8@16@24Q32Q40@48` | `+0x4A7F` | — |
| `newFunctionWithIR:` | `I24@0:8@16` | `+0x4BBC` | — |
| `newRenderPipelineStateWithSerializedDescriptor:allocator:` | `I32@0:8@16@24` | `+0x4C11` | — |
| `newComputePipelineStateWithSerializedDescriptor:allocator:` | `I32@0:8@16@24` | `+0x4CEF` | — |
| `newIOSurfaceTextureWithDescriptor:plane:allocator:` | `I40@0:8@16Q24@32` | `+0x4DCD` | — |
| `newTextureWithDescriptor:allocator:` | `I32@0:8@16@24` | `+0x4FC7` | — |
| `newDepthStencilStateWithDescriptor:allocator:` | `I32@0:8@16@24` | `+0x50CD` | — |
| `newSamplerStateWithDescriptor:allocator:` | `I32@0:8@16@24` | `+0x51B8` | — |
| `newRasterizationRateMapWithDescriptor:allocator:` | `I32@0:8@16@24` | `+0x54B6` | — |
| `resetRasterizationRateMapWithDescriptor:existingID:allocator:` | `v36@0:8@16I24@28` | `+0x59CF` | — |
| `supportsOpenGL` | `c16@0:8` | `+0x5A56` | — |
| `supportsCorrectBaseVertex` | `c16@0:8` | `+0x5A60` | — |
| `supportsSharedTextures` | `c16@0:8` | `+0x5A6A` | — |
| `newSharedTextureWithDescriptor:newTextureRef:allocator:` | `B36@0:8@16I24@28` | `+0x5A74` | — |
| `newSharedTextureWithHandle:allocator:` | `I28@0:8I16@20` | `+0x5B80` | — |
| `newRenderPipelineStateWithSerializedTileDescriptor:allocator:` | `I32@0:8@16@24` | `+0x5BDF` | — |
| `newIndirectCommandBufferWithDescriptor:layout:maxCommandCount:options:allocator:` | `I56@0:8@16^{?=SSSSIIIIIIIIIII}24Q32Q40@48` | `+0x5CBD` | — |
| `supportsDefaultRasterSampleCount` | `c16@0:8` | `+0x6405` | — |
| `setSupportsDefaultRasterSampleCount:` | `v20@0:8c16` | `+0x640F` | — |
| `supportsProgrammableSamplePositions` | `c16@0:8` | `+0x6418` | — |
| `setSupportsProgrammableSamplePositions:` | `v20@0:8c16` | `+0x6422` | — |
| `supportsRasterizationRateMap` | `c16@0:8` | `+0x642B` | — |
| `setSupportsRasterizationRateMap:` | `v20@0:8c16` | `+0x6435` | — |
| `supportsTileShaders` | `c16@0:8` | `+0x643E` | — |
| `setSupportsTileShaders:` | `v20@0:8c16` | `+0x6448` | — |
| `supportsImageBlocks` | `c16@0:8` | `+0x6451` | — |
| `setSupportsImageBlocks:` | `v20@0:8c16` | `+0x645B` | — |
| `supportsSwizzledTextures` | `c16@0:8` | `+0x6464` | — |
| `setSupportsSwizzledTextures:` | `v20@0:8c16` | `+0x646E` | — |
| `supportsTextureDescriptor2` | `c16@0:8` | `+0x6477` | — |
| `setSupportsTextureDescriptor2:` | `v20@0:8c16` | `+0x6481` | — |
| `supportsVertexAmplification` | `c16@0:8` | `+0x648A` | — |
| `setSupportsVertexAmplification:` | `v20@0:8c16` | `+0x6494` | — |
| `supportsDynamicAttributeStride` | `c16@0:8` | `+0x649D` | — |
| `setSupportsDynamicAttributeStride:` | `v20@0:8c16` | `+0x64A7` | — |
| `supportsBlitEncoderSPI` | `c16@0:8` | `+0x64B0` | — |
| `setSupportsBlitEncoderSPI:` | `v20@0:8c16` | `+0x64BA` | — |
| `supportsComputePassDescriptorDispatchType` | `c16@0:8` | `+0x64C3` | — |
| `setSupportsComputePassDescriptorDispatchType:` | `v20@0:8c16` | `+0x64CD` | — |
| `supportsCommandBufferJump` | `c16@0:8` | `+0x64D6` | — |
| `setSupportsCommandBufferJump:` | `v20@0:8c16` | `+0x64E0` | — |
| `supportsProtectionOptionsEnvelope` | `c16@0:8` | `+0x64E9` | — |
| `setSupportsProtectionOptionsEnvelope:` | `v20@0:8c16` | `+0x64F3` | — |
| `supportsInsertCompressedTextureReinterpretationFlush` | `c16@0:8` | `+0x64FC` | — |
| `setSupportsInsertCompressedTextureReinterpretationFlush:` | `v20@0:8c16` | `+0x6506` | — |
| `supportsDispatchThreadsIndirect` | `c16@0:8` | `+0x650F` | — |
| `setSupportsDispatchThreadsIndirect:` | `v20@0:8c16` | `+0x6519` | — |
| `supportsInfoIndirect` | `c16@0:8` | `+0x6522` | — |
| `setSupportsInfoIndirect:` | `v20@0:8c16` | `+0x652C` | — |

### A.7 `MTLBufferSPI` 与 `MTLTextureSPI` 全量（encoding 源 `S-APV`）

**`MTLBufferSPI`** — req 5 / opt 8，继承 `MTLResourceSPI`, `MTLBuffer`

| selector | req/opt | x86_64 type encoding |
|---|---|---|
| `didModifyRange:` | req | `v32@0:8{_NSRange=QQ}16` |
| `newTiledTextureWithDescriptor:offset:bytesPerRow:` | req | `@40@0:8@16Q24Q32` |
| `newLinearTextureWithDescriptor:offset:bytesPerRow:bytesPerImage:` | req | `@48@0:8@16Q24Q32Q40` |
| `_aneIOSurface` | req | `^{__IOSurface=}16@0:8` |
| `iosurface` | req | `^{__IOSurface=}16@0:8` |
| `detachBacking` | opt | `c16@0:8` |
| `replaceBackingWithBytesNoCopy:length:deallocator:` | opt | `c40@0:8^v16Q24@?32` |
| `replaceBackingWithRanges:readOnly:` | opt | `c28@0:8@16c24` |
| `resourceIndex` | opt | `Q16@0:8` |
| `parentGPUAddress` | opt | `Q16@0:8` |
| `setParentGPUAddress:` | opt | `v24@0:8Q16` |
| `parentGPUSize` | opt | `Q16@0:8` |
| `setParentGPUSize:` | opt | `v24@0:8Q16` |

**`MTLTextureSPI`** — req 13 / opt 10，继承 `MTLTexture`, `MTLResourceSPI`

| selector | req/opt | x86_64 type encoding |
|---|---|---|
| `didModifyData` | req | `v16@0:8` |
| `iosurface` | req | `^{__IOSurface=}16@0:8` |
| `iosurfacePlane` | req | `Q16@0:8` |
| `rotation` | req | `Q16@0:8` |
| `isCompressed` | req | `c16@0:8` |
| `compressionFeedback` | req | `q16@0:8` |
| `swizzleKey` | req | `I16@0:8` |
| `numFaces` | req | `Q16@0:8` |
| `isDrawable` | req | `c16@0:8` |
| `sparseSurfaceDefaultValue` | req | `Q16@0:8` |
| `compressionFootprint` | req | `Q16@0:8` |
| `colorSpaceConversionMatrix` | req | `Q16@0:8` |
| `gpuHandle` | req | `Q16@0:8` |
| `newCompressedTextureViewWithPixelFormat:textureType:level:slice:` | opt | `@48@0:8Q16Q24Q32Q40` |
| `canGenerateMipmapLevels` | opt | `c16@0:8` |
| `generateMipmapLevel:slice:` | opt | `v32@0:8Q16Q24` |
| `newTextureViewWithPixelFormat:resourceIndex:` | opt | `@32@0:8Q16Q24` |
| `newTextureViewWithPixelFormat:textureType:levels:slices:resourceIndex:` | opt | `@72@0:8Q16Q24{_NSRange=QQ}32{_NSRange=QQ}48Q64` |
| `newTextureViewWithPixelFormat:textureType:levels:slices:swizzle:resourceIndex:` | opt | `@76@0:8Q16Q24{_NSRange=QQ}32{_NSRange=QQ}48{?=CCCC}64Q68` |
| `uniqueIdentifier` | opt | `Q16@0:8` |
| `resourceIndex` | opt | `Q16@0:8` |
| `gpuAddress` | opt | `Q16@0:8` |
| `writeAccessPattern` | opt | `q16@0:8` |


### A.8 其它小类

**`AppleParavirtBlitCommandEncoder`（2 条，在 `PGSerializerBlitCommandEncoder` 之上只加同步语义）**

| selector | x86_64 type encoding | `S-APV` RVA | 协议归属 |
|---|---|---|---|
| `synchronizeResource:` | `v24@0:8@16` | `+0x2ED7` | — |
| `synchronizeTexture:slice:level:` | `v40@0:8@16Q24Q32` | `+0x2F54` | — |

**`AppleParavirtParallelRenderCommandEncoder`（3 条）**

| selector | x86_64 type encoding | `S-APV` RVA | 协议归属 |
|---|---|---|---|
| `initWithCommandBuffer:renderPassDescriptor:serializer:` | `@40@0:8@16@24@32` | `+0x6F39` | — |
| `dealloc` | `v16@0:8` | `+0x6F93` | — |
| `endEncoding` | `v16@0:8` | `+0x6FE1` | — |

**`PGSerializerParallelRenderCommandEncoder`（15 条）**

| selector | x86_64 type encoding | `S-APV` RVA | 协议归属 |
|---|---|---|---|
| `initWithCommandBuffer:renderPassDescriptor:serializer:` | `@40@0:8@16@24@32` | `+0x65EC` | — |
| `renderCommandEncoder` | `@16@0:8` | `+0x666C` | `req:MTLParallelRenderCommandEncoder` |
| `dealloc` | `v16@0:8` | `+0x6721` | — |
| `endEncoding` | `v16@0:8` | `+0x676F` | `req:MTLCommandEncoder` |
| `setColorStoreAction:atIndex:` | `v32@0:8Q16Q24` | `+0x68D1` | `req:MTLParallelRenderCommandEncoder` |
| `setColorStoreActionOptions:atIndex:` | `v32@0:8Q16Q24` | `+0x692C` | `req:MTLParallelRenderCommandEncoder` |
| `setDepthStoreAction:` | `v24@0:8Q16` | `+0x6987` | `req:MTLParallelRenderCommandEncoder` |
| `setDepthStoreActionOptions:` | `v24@0:8Q16` | `+0x69C6` | `req:MTLParallelRenderCommandEncoder` |
| `setStencilStoreAction:` | `v24@0:8Q16` | `+0x6A05` | `req:MTLParallelRenderCommandEncoder` |
| `setStencilStoreActionOptions:` | `v24@0:8Q16` | `+0x6A44` | `req:MTLParallelRenderCommandEncoder` |
| `separateCommits` | `c16@0:8` | `+0x6A83` | `req:MTLParallelRenderCommandEncoderSPI` |
| `setSeparateCommits:` | `v20@0:8c16` | `+0x6A94` | `req:MTLParallelRenderCommandEncoderSPI` |
| `serializer` | `@16@0:8` | `+0x6AA4` | — |
| `.cxx_destruct` | `v16@0:8` | `+0x6AB5` | — |
| `.cxx_construct` | `@16@0:8` | `+0x6AD9` | — |

**`PGSerializerCommandEncoder`（21 条，encoder 自建基类）**

| selector | x86_64 type encoding | `S-APV` RVA | 协议归属 |
|---|---|---|---|
| `initWithCommandBuffer:serializer:` | `@32@0:8@16@24` | `+0x9095` | — |
| `dealloc` | `v16@0:8` | `+0x9118` | — |
| `setBuffers:offsets:withRange:withCommand:bindings:` | `v60@0:8r^@16r^Q24{_NSRange=QQ}32I48^{PGSerializerBindings=[31@][31Q][128@][16@]III}52` | `+0x9183` | — |
| `setBuffers:offsets:attributeStrides:withRange:withCommand:bindings:` | `v68@0:8r^@16r^Q24r^Q32{_NSRange=QQ}40I56^{PGSerializerBindings=[31@][31Q][128@][16@]III}60` | `+0x9387` | — |
| `setBytes:length:atIndex:withCommand:bindings:` | `v52@0:8r^v16Q24Q32I40^{PGSerializerBindings=[31@][31Q][128@][16@]III}44` | `+0x95C2` | — |
| `setBytes:length:attributeStride:atIndex:withCommand:bindings:` | `v60@0:8r^v16Q24Q32Q40I48^{PGSerializerBindings=[31@][31Q][128@][16@]III}52` | `+0x96B9` | — |
| `setSamplerStates:withRange:withCommand:bindings:` | `v52@0:8r^@16{_NSRange=QQ}24I40^{PGSerializerBindings=[31@][31Q][128@][16@]III}44` | `+0x97C7` | — |
| `setSamplerStates:lodMinClamps:lodMaxClamps:withRange:withCommand:bindings:` | `v68@0:8r^@16r^f24r^f32{_NSRange=QQ}40I56^{PGSerializerBindings=[31@][31Q][128@][16@]III}60` | `+0x995F` | — |
| `setTextures:withRange:withCommand:bindings:` | `v52@0:8r^@16{_NSRange=QQ}24I40^{PGSerializerBindings=[31@][31Q][128@][16@]III}44` | `+0x9B35` | — |
| `useHeaps:count:` | `v32@0:8r^@16Q24` | `+0x9CBF` | — |
| `useResources:count:usage:` | `v40@0:8r^@16Q24Q32` | `+0x9DB6` | — |
| `useHeap:` | `v24@0:8@16` | `+0x9EFC` | — |
| `useResource:usage:` | `v32@0:8@16Q24` | `+0x9F26` | — |
| `endEncoding` | `v16@0:8` | `+0x9F53` | `req:MTLCommandEncoder` |
| `beginSegment:protectionOptions:` | `v28@0:8c16Q20` | `+0x9FE4` | — |
| `writeSegmentHeader:continuation:protectionOptions:` | `v32@0:8C16c20Q24` | `+0x9FEA` | — |
| `getCommandBytes:forCommand:` | `^v28@0:8Q16I24` | `+0xA129` | — |
| `getCommandBytesRetry:forCommand:` | `^v28@0:8Q16I24` | `+0xA17E` | — |
| `split` | `v16@0:8` | `+0xA1C8` | — |
| `globalTraceObjectID` | `Q16@0:8` | `+0xA1D9` | — |
| `serializer` | `@16@0:8` | `+0xA21A` | — |

**`AppleParavirtFunctionVariant`（4 条）**

| selector | x86_64 type encoding | `S-APV` RVA | 协议归属 |
|---|---|---|---|
| `initWithCompilerOutput:device:functionType:` | `@40@0:8@16@24Q32` | `+0x30CF` | — |
| `dealloc` | `v16@0:8` | `+0x33E7` | — |
| `function` | `@16@0:8` | `+0x358C` | — |
| `descriptorBuffer` | `@16@0:8` | `+0x359D` | — |

**`AppleParavirtContainerFunction`（16 条）**

| selector | x86_64 type encoding | `S-APV` RVA | 协议归属 |
|---|---|---|---|
| `initWithDevice:functionType:functionRef:` | `@36@0:8@16Q24I32` | `+0x2F66` | — |
| `dealloc` | `v16@0:8` | `+0x2FCF` | — |
| `newArgumentEncoderWithBufferIndex:` | `@24@0:8Q16` | `+0x3019` | `req:MTLFunction` |
| `newArgumentEncoderWithBufferIndex:reflection:` | `@32@0:8Q16^@24` | `+0x3031` | `req:MTLFunction` |
| `functionRef` | `I16@0:8` | `+0x3049` | `req:PGSerializerFunction` |
| `device` | `@16@0:8` | `+0x3052` | `req:MTLFunction` |
| `functionType` | `Q16@0:8` | `+0x305C` | `req:MTLFunction` |
| `label` | `@16@0:8` | `+0x3066` | `req:MTLFunction` |
| `setLabel:` | `v24@0:8@16` | `+0x307A` | `req:MTLFunction` |
| `options` | `Q16@0:8` | `+0x3089` | `req:MTLFunction` |
| `vertexAttributes` | `@16@0:8` | `+0x3093` | `req:MTLFunction` |
| `stageInputAttributes` | `@16@0:8` | `+0x309D` | `req:MTLFunction` |
| `patchType` | `Q16@0:8` | `+0x30A7` | `req:MTLFunction` |
| `patchControlPointCount` | `q16@0:8` | `+0x30B1` | `req:MTLFunction` |
| `name` | `@16@0:8` | `+0x30BB` | `req:MTLFunction` |
| `functionConstantsDictionary` | `@16@0:8` | `+0x30C5` | `req:MTLFunction` |

**`AppleParavirtDescriptorHeap`（2 条）**

| selector | x86_64 type encoding | `S-APV` RVA | 协议归属 |
|---|---|---|---|
| `initWithDevice:size:` | `@32@0:8@16Q24` | `+0x125E` | — |
| `newDescriptorBufferWithLength:` | `@24@0:8Q16` | `+0x1356` | — |

**`AppleParavirtDescriptorBuffer`（1 条）**

| selector | x86_64 type encoding | `S-APV` RVA | 协议归属 |
|---|---|---|---|
| `initWithHeap:resource:offset:length:` | `@48@0:8@16@24Q32Q40` | `+0x13CB` | — |

**`AppleParavirtAllocator`（3 条）**

| selector | x86_64 type encoding | `S-APV` RVA | 协议归属 |
|---|---|---|---|
| `allocateOperationBytes:` | `*24@0:8Q16` | `+0xD755` | `req:PGSerializerAllocator` |
| `contents` | `^v16@0:8` | `+0xD7AD` | — |
| `length` | `I16@0:8` | `+0xD7B7` | — |

**`AppleParavirtObjectRefAllocator`（6 条）**

| selector | x86_64 type encoding | `S-APV` RVA | 协议归属 |
|---|---|---|---|
| `init` | `@16@0:8` | `+0xD7C4` | — |
| `dealloc` | `v16@0:8` | `+0xD814` | — |
| `allocateObjectRef` | `I16@0:8` | `+0xD853` | `req:PGSerializerObjectRefAllocator` |
| `releaseRef:` | `v20@0:8I16` | `+0xD9FA` | — |
| `.cxx_destruct` | `v16@0:8` | `+0xDAAE` | — |
| `.cxx_construct` | `@16@0:8` | `+0xDABC` | — |

**`AppleParavirtPooledBuffer`（22 条）**

| selector | x86_64 type encoding | `S-APV` RVA | 协议归属 |
|---|---|---|---|
| `bufferRef` | `I16@0:8` | `+0x18FE5` | `req:PGSerializerBuffer` |
| `serializerResourceRef` | `I16@0:8` | `+0x18FF5` | `req:PGSerializerResource` |
| `remoteStorageBuffer` | `@16@0:8` | `+0x19005` | — |
| `initWithDevice:options:args:argsSize:` | `@44@0:8@16Q24^{IOAccelNewResourceArgs={IOAccelNewResourceData=IISSSSQQCCCCIQQQ(?={?=QQQQI}{?=II[3Q]}{?=IIII[2Q]}{?=II[3Q]})}}32I40` | `+0x1900D` | — |
| `dealloc` | `v16@0:8` | `+0x1910F` | — |
| `isAliasable` | `c16@0:8` | `+0x1918D` | — |
| `makeAliasable` | `v16@0:8` | `+0x19195` | — |
| `setPurgeableState:` | `Q24@0:8Q16` | `+0x191AA` | — |
| `newRemoteBufferViewForDevice:` | `@24@0:8@16` | `+0x191D9` | — |
| `newTextureWithDescriptor:offset:bytesPerRow:` | `@40@0:8@16Q24Q32` | `+0x191F1` | — |
| `addDebugMarker:range:` | `v40@0:8@16{_NSRange=QQ}24` | `+0x19209` | — |
| `contents` | `^v16@0:8` | `+0x1921E` | — |
| `didModifyRange:` | `v32@0:8{_NSRange=QQ}16` | `+0x19230` | — |
| `removeAllDebugMarkers` | `v16@0:8` | `+0x19245` | — |
| `newLinearTextureWithDescriptor:offset:bytesPerRow:bytesPerImage:` | `@48@0:8@16Q24Q32Q40` | `+0x1925A` | — |
| `newTiledTextureWithDescriptor:offset:bytesPerRow:` | `@40@0:8@16Q24Q32` | `+0x19272` | — |
| `doesAliasAllResources:count:` | `c32@0:8r^@16Q24` | `+0x1928A` | — |
| `doesAliasAnyResources:count:` | `c32@0:8r^@16Q24` | `+0x19292` | — |
| `doesAliasResource:` | `c24@0:8@16` | `+0x1929A` | — |
| `iosurface` | `^{__IOSurface=}16@0:8` | `+0x192A2` | — |
| `parentResourceOffset` | `Q16@0:8` | `+0x192AA` | `req:PGSerializerBuffer` |
| `shouldSyncInBlit` | `c16@0:8` | `+0x192B2` | `req:PGSerializerResource` |

**`AppleParavirtHeap`（5 条）**

| selector | x86_64 type encoding | `S-APV` RVA | 协议归属 |
|---|---|---|---|
| `newBufferWithLength:options:` | `@32@0:8Q16Q24` | `+0x192CD` | `req:MTLHeap` |
| `newTextureWithDescriptor:` | `@24@0:8@16` | `+0x192D5` | `req:MTLHeap` |
| `heapRef` | `I16@0:8` | `+0x192DD` | `req:PGSerializerHeap` |
| `serializerResourceRef` | `I16@0:8` | `+0x192ED` | `req:PGSerializerResource` |
| `shouldSyncInBlit` | `c16@0:8` | `+0x192FD` | `req:PGSerializerResource` |

**`AppleParavirtFence`（5 条）**

| selector | x86_64 type encoding | `S-APV` RVA | 协议归属 |
|---|---|---|---|
| `initWithDevice:` | `@24@0:8@16` | `+0xF1C` | — |
| `dealloc` | `v16@0:8` | `+0x109D` | — |
| `fenceRef` | `I16@0:8` | `+0x1232` | `req:PGSerializerFence` |
| `addResourcesToList:` | `c24@0:8^{IOAccelResourceList=[256S]^{IOAccelSegmentResourceDescriptorGroup}QQIIIIIII^?^v}16` | `+0x1242` | `req:AppleParavirtState` |
| `device` | `@16@0:8` | `+0x124D` | `req:MTLFence` |

**`AppleParavirtSamplerState`（4 条）**

| selector | x86_64 type encoding | `S-APV` RVA | 协议归属 |
|---|---|---|---|
| `initWithDevice:samplerDescriptor:` | `@32@0:8@16@24` | `+0x702D` | — |
| `dealloc` | `v16@0:8` | `+0x71A9` | — |
| `samplerRef` | `I16@0:8` | `+0x732D` | `req:PGSerializerSamplerState` |
| `addResourcesToList:` | `c24@0:8^{IOAccelResourceList=[256S]^{IOAccelSegmentResourceDescriptorGroup}QQIIIIIII^?^v}16` | `+0x733D` | — |

**`AppleParavirtDepthStencilState`（4 条）**

| selector | x86_64 type encoding | `S-APV` RVA | 协议归属 |
|---|---|---|---|
| `initWithDevice:depthStencilDescriptor:` | `@32@0:8@16@24` | `+0x142B2` | — |
| `dealloc` | `v16@0:8` | `+0x1442E` | — |
| `depthStencilRef` | `I16@0:8` | `+0x145B2` | `req:PGSerializerDepthStencilState` |
| `addResourcesToList:` | `c24@0:8^{IOAccelResourceList=[256S]^{IOAccelSegmentResourceDescriptorGroup}QQIIIIIII^?^v}16` | `+0x145C2` | `req:AppleParavirtState` |

**`AppleParavirtRenderPipelineState`（8 条）**

| selector | x86_64 type encoding | `S-APV` RVA | 协议归属 |
|---|---|---|---|
| `initWithDevice:pipelineStateDescriptor:` | `@32@0:8@16@24` | `+0x145CD` | — |
| `initWithDevice:pipelineStateDescriptor:vertexVariant:fragmentVariant:errorMessage:` | `@56@0:8@16@24@32@40^@48` | `+0x14763` | — |
| `dealloc` | `v16@0:8` | `+0x14A8C` | — |
| `pipelineRef` | `I16@0:8` | `+0x14C56` | `req:PGSerializerRenderPipelineState` |
| `newFragmentShaderDebugInfo` | `@16@0:8` | `+0x14C66` | `req:MTLRenderPipelineStateSPI` |
| `newVertexShaderDebugInfo` | `@16@0:8` | `+0x14CA5` | `req:MTLRenderPipelineStateSPI` |
| `addResourcesToList:` | `c24@0:8^{IOAccelResourceList=[256S]^{IOAccelSegmentResourceDescriptorGroup}QQIIIIIII^?^v}16` | `+0x14CE4` | `req:AppleParavirtState` |
| `getWritableInfo:vtxBuffers:vtxTexturesArrayLength:vtxTextures:frgBuffersLength:frgBuffers:frgTexturesArrayLength:frgTextures:tileBuffersArrayLength:tileBuffers:tileTexturesArrayLength:tileTextures:` | `v88@0:8I16^I20I28^I32I40^I44I52^I56I64^I68I76^I80` | `+0x14DA8` | `opt:PGSerializerRenderPipelineState` |

**`AppleParavirtComputePipelineState`（9 条）**

| selector | x86_64 type encoding | `S-APV` RVA | 协议归属 |
|---|---|---|---|
| `initWithDevice:pipelineStateDescriptor:computeVariant:errorMessage:` | `@48@0:8@16@24@32^@40` | `+0x14E3B` | — |
| `parseReply:` | `B24@0:8@16` | `+0x151D8` | — |
| `dealloc` | `v16@0:8` | `+0x15211` | — |
| `pipelineRef` | `I16@0:8` | `+0x153BB` | `req:PGSerializerComputePipelineState` |
| `threadExecutionWidth` | `Q16@0:8` | `+0x153CB` | `req:MTLComputePipelineState` |
| `staticThreadgroupMemoryLength` | `Q16@0:8` | `+0x153DC` | `req:MTLComputePipelineStateSPI` |
| `maxTotalThreadsPerThreadgroup` | `Q16@0:8` | `+0x153ED` | `req:MTLComputePipelineState` |
| `addResourcesToList:` | `c24@0:8^{IOAccelResourceList=[256S]^{IOAccelSegmentResourceDescriptorGroup}QQIIIIIII^?^v}16` | `+0x153FD` | `req:AppleParavirtState` |
| `getWritableInfo:buffers:texturesArrayLength:textures:` | `v40@0:8I16^I20I28^I32` | `+0x15441` | `opt:PGSerializerComputePipelineState` |

**`AppleParavirtCommandQueue`（7 条）**

| selector | x86_64 type encoding | `S-APV` RVA | 协议归属 |
|---|---|---|---|
| `initWithDevice:descriptor:` | `@32@0:8@16@24` | `+0xA22B` | — |
| `commandBuffer` | `@16@0:8` | `+0xA25A` | `req:MTLCommandQueue` |
| `commandBufferWithUnretainedReferences` | `@16@0:8` | `+0xA295` | `req:MTLCommandQueue` |
| `availableCounters` | `@16@0:8` | `+0xA2CD` | `opt:MTLCommandQueueSPI` |
| `requestCounters:` | `i24@0:8@16` | `+0xA2D5` | `opt:MTLCommandQueueSPI` |
| `getRequestedCounters` | `@16@0:8` | `+0xA2DD` | `opt:MTLCommandQueueSPI` |
| `counterInfo` | `@16@0:8` | `+0xA2F6` | `opt:MTLCommandQueueSPI` |

**`AppleParavirtCommandBuffer`（29 条）**

| selector | x86_64 type encoding | `S-APV` RVA | 协议归属 |
|---|---|---|---|
| `initWithQueue:retainedReferences:` | `@28@0:8@16c24` | `+0x17C48` | — |
| `dealloc` | `v16@0:8` | `+0x17C77` | — |
| `blitCommandEncoder` | `@16@0:8` | `+0x17CA6` | `req:MTLCommandBuffer` |
| `blitCommandEncoderWithDescriptor:` | `@24@0:8@16` | `+0x17D27` | `req:MTLCommandBuffer` |
| `computeCommandEncoder` | `@16@0:8` | `+0x17D8C` | `req:MTLCommandBuffer` |
| `computeCommandEncoderWithDispatchType:` | `@24@0:8Q16` | `+0x17E0D` | `req:MTLCommandBuffer` |
| `computeCommandEncoderWithDescriptor:` | `@24@0:8@16` | `+0x17EA1` | `req:MTLCommandBuffer` |
| `parallelRenderCommandEncoderWithDescriptor:` | `@24@0:8@16` | `+0x17F06` | `req:MTLCommandBuffer` |
| `renderCommandEncoderWithDescriptor:` | `@24@0:8@16` | `+0x17FB6` | `req:MTLCommandBuffer` |
| `resourceStateCommandEncoder` | `@16@0:8` | `+0x18066` | `req:MTLCommandBuffer` |
| `addResourceReference:isWrite:` | `c28@0:8@16c24` | `+0x1807E` | `req:PGSerializerCommandStream` |
| `addResourcePageOff:` | `c24@0:8@16` | `+0x18114` | — |
| `addHeapReference:` | `c24@0:8@16` | `+0x1816C` | `req:PGSerializerCommandStream` |
| `addResourceMetadataReference:` | `c24@0:8@16` | `+0x18184` | `opt:PGSerializerCommandStream` |
| `addStateReference:` | `c24@0:8@16` | `+0x1819C` | `req:PGSerializerCommandStream` |
| `addFenceReference:` | `c24@0:8@16` | `+0x1821C` | `req:PGSerializerCommandStream` |
| `endCurrentChunk` | `v16@0:8` | `+0x182E1` | — |
| `endEncoding` | `v16@0:8` | `+0x18346` | `req:PGSerializerCommandStream` |
| `getBufferBytes:alignment:poolType:buffer:offset:` | `^v52@0:8Q16Q24i32^@36^Q44` | `+0x183BA` | `req:PGSerializerCommandStream` |
| `getBufferBytes:alignment:buffer:offset:` | `^v48@0:8Q16Q24^@32^Q40` | `+0x183D3` | `req:PGSerializerCommandStream` |
| `split` | `v16@0:8` | `+0x184EE` | — |
| `allocKernelCommand:` | `^v24@0:8Q16` | `+0x18590` | — |
| `insertCommandExec` | `v16@0:8` | `+0x1868F` | — |
| `getCommandBufferBytes:` | `^v24@0:8Q16` | `+0x18783` | `req:PGSerializerCommandStream` |
| `beginContinuation` | `v16@0:8` | `+0x189F2` | `req:PGSerializerCommandStream` |
| `merge:` | `v24@0:8@16` | `+0x18A10` | `req:PGSerializerCommandStream` |
| `getNextTraceID` | `Q16@0:8` | `+0x18C20` | `req:PGSerializerCommandStream` |
| `.cxx_destruct` | `v16@0:8` | `+0x18C48` | — |
| `.cxx_construct` | `@16@0:8` | `+0x18C6C` | — |

**`PGSerializerInfoCommandEncoder`（21 条，APV 私有 info encoder）**

| selector | x86_64 type encoding | `S-APV` RVA | 协议归属 |
|---|---|---|---|
| `initWithCommandBuffer:serializer:` | `@32@0:8@16@24` | `+0xB4C1` | — |
| `beginSegment:protectionOptions:` | `v28@0:8c16Q20` | `+0xB548` | — |
| `computePipelineStateInfo:info:` | `v32@0:8@16^{?=QQQC}24` | `+0xB564` | — |
| `heapTextureDescriptorSizeAndAlign:sizeAndAlign:` | `v32@0:8@16^{?=QQ}24` | `+0xB72E` | — |
| `getRasterizationRateMapInfo:layerCount:info:` | `v36@0:8@16I24^{?={?=QQ}{?=SS}[0{?=SS}]}28` | `+0xB96C` | — |
| `copyRasterizationRateParameterBuffer:buffer:bufferOffset:` | `v40@0:8@16@24Q32` | `+0xBB9B` | — |
| `mapCoordinateInternal:fromCoordinate:forLayer:toCoordinate:command:` | `v52@0:8@16{?=ff}24Q32^{?=ff}40I48` | `+0xBC8A` | — |
| `mapScreenToPhysicalCoordinates:forScreenCoordinate:forLayer:toPhysicalCoordinate:` | `v48@0:8@16{?=ff}24Q32^{?=ff}40` | `+0xBE8C` | — |
| `mapPhysicalToScreenCoordinates:forPhysicalCoordinate:forLayer:toScreenCoordinate:` | `v48@0:8@16{?=ff}24Q32^{?=ff}40` | `+0xBEA7` | — |
| `mapPhysicalToScreenCoordinateMultiple:forPhysicalCoordinates:forLayer:toScreenCoordinates:count:` | `v56@0:8@16^{?=ff}24Q32^{?=ff}40Q48` | `+0xBEC2` | — |
| `renderPipelineStateInfo:info:` | `v32@0:8@16^{?=IICC}24` | `+0xC120` | — |
| `renderPipelineStateImageBlockMemoryLength:imageblockDimensions:info:` | `v56@0:8@16{?=QQQ}24^{?=I}48` | `+0xC2E8` | — |
| `computePipelineStateImageBlockMemoryLength:imageblockDimensions:info:` | `v56@0:8@16{?=QQQ}24^{?=I}48` | `+0xC4C7` | — |
| `bufferHostResourceInfo:info:` | `v32@0:8@16^{?=Q}24` | `+0xC6A6` | — |
| `heapHostResourceInfo:info:` | `v32@0:8@16^{?=Q}24` | `+0xC867` | — |
| `textureHostResourceInfo:info:` | `v32@0:8@16^{?=QQ}24` | `+0xCA28` | — |
| `samplerStateHostResourceInfo:info:` | `v32@0:8@16^{?=QQ}24` | `+0xCBE9` | — |
| `icbHostResourceInfo:info:` | `v32@0:8@16^{?=QQ}24` | `+0xCDAA` | — |
| `renderPipelineHostResourceInfo:info:` | `v32@0:8@16^{?=QQ}24` | `+0xCF61` | — |
| `computePipelineHostResourceInfo:info:` | `v32@0:8@16^{?=QQ}24` | `+0xD122` | — |
| `depthStencilHostResourceInfo:info:` | `v32@0:8@16^{?=QQ}24` | `+0xD2E3` | — |

**`AppleParavirtTextureDimension`（实例方法 0 条，只有 3 个类方法）**

| 类方法 | x86_64 type encoding | `S-APV` RVA |
|---|---|---|
| `+allocDimensionCompressed:descriptor:dimension:bytesPerRow:totalBytes:baseOffset:isClientStorage:formatInfo:` | `B76@0:8@16r^{MTLTextureDescriptorPrivate=QQQQQQQQcQccIcQ(?=QQ)QQccQQQqQqqQQQ}24^{?=b14b1b1SQQCCCC[0{?=QQQIII}]}32^Q40^Q48Q56c64r^{PixelFormatInfo=IiI(?={MTLCompressedPixelFormatInfo=QQQQ}[2{MTLNormalPixelFormatInfo=QCCQQ}])}68` | `+0x35AE` |
| `+allocDimensionNormal:descriptor:dimension:bytesPerRow:totalBytes:baseOffset:isClientStorage:formatInfo:minRowAlignment:` | `B80@0:8@16r^{MTLTextureDescriptorPrivate=QQQQQQQQcQccIcQ(?=QQ)QQccQQQqQqqQQQ}24^{?=b14b1b1SQQCCCC[0{?=QQQIII}]}32^Q40^Q48Q56c64r^{PixelFormatInfo=IiI(?={MTLCompressedPixelFormatInfo=QQQQ}[2{MTLNormalPixelFormatInfo=QCCQQ}])}68I76` | `+0x3809` |
| `+allocDimension:descriptor:dimension:dimensionLength:bytesPerRow:totalBytes:baseOffset:isClientStorage:minRowAlignment:features:` | `c88@0:8@16@24^^{?}32^Q40^Q48^Q56Q64c72I76r^{APVFeatures=BBBBBBBBBBBBBBBBBIIBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB}80` | `+0x3AB4` |

