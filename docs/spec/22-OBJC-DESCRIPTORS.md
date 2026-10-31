# 22 — Metal descriptor 类的字段、默认值、校验与 snapshot 规则

文档版本：1.0
基线：macOS Tahoe 26.7.2 / build 25G325 / **x86_64**
职责（`00-OVERVIEW.md` 第 8 节）：全部 descriptor 类的字段、默认值、校验与 snapshot 规则
范围：按 `00-OVERVIEW.md` 第 4.7 节，**全量能力**，不裁剪成最小集

## 0. 样本、地址与标签约定

证据标签定义见 `00-OVERVIEW.md` 第 7 节（`KNOWN` / `INFERRED` / `BLOCKED` / `TESTED`）。本文全部证据均为 **x86_64**。

| 代号 | 文件 | 标识 | 说明 |
|---|---|---|---|
| `S-METAL` | `analysis/idb/macos26-25G325-x86_64-frameworks/raw/Metal` | UUID `FDB3FD2C-840A-3FC3-81FB-C524F891F642`，image base `0x7FF80B179000`，SHA-256 `9BAB47CD…598C9D` | BaseSystem dyld shared cache 抽出件 |
| `D-OBJC` | `analysis/idb/macos26-25G325-x86_64-frameworks/metal-objc.json` | SHA-256 `F3577E664A0E68A89F33691F483697C5738F3A7DE5DE936856F2C6ED14F01BC5`，1,946,692 B | 由 `S-METAL` 产出的 class-dump 式 ObjC 转储：424 个 `@interface`、144 个 `@protocol`、3,564 条 `@property` |

本文地址一律写作 `S-METAL +RVA`（RVA = 绝对 VA − `0x7FF80B179000`）。字段清单一律写作 `D-OBJC:<行号>`，行号指 `metal-objc.json` 中该 `@interface` 块的起始行。

抽取工具：`analysis/spec-work/dump-iface.ps1`（按类名切出 `@interface` 块）。默认值由 `S-METAL` 的 `init` 与 getter 反编译取得，不来自公开文档的转述。

### 0.1 `@property` 属性串的读法

`D-OBJC` 的属性串形如 `@property (T@"NSString",C,D,N) label;`。本文用到的标志位：

| 标志 | 含义 | 对 snapshot 的影响 |
|---|---|---|
| `T<encoding>` | 类型编码 | 决定 getter 的 x86_64 ABI，必须逐字匹配 |
| `C` | `copy` | **该字段是深拷贝语义**：descriptor 自己已经复制了一份，但那一份仍可被 descriptor 的后续 setter 替换，snapshot 仍须自取 |
| `&` | `retain` | **该字段是弱语义的对象句柄**：descriptor 只持引用，不复制内容 |
| `R` | `readonly` | 无 setter；通常是懒创建的子对象容器（见第 1.2 节） |
| `N` | `nonatomic` | **读写无锁**，跨线程读 descriptor 是数据竞争 |
| `D` | `@dynamic` | 实现在 `*Internal` 子类上；访问器直读 `_private` 结构 |
| `V_xxx` | 直接后备 ivar | 该字段在基类上就有实存 ivar |
| `G<name>` | 自定义 getter（如 `GisBlendingEnabled`） | **selector 名不是属性名**，shim 必须用 `isBlendingEnabled` 而不是 `blendingEnabled` |

常见类型编码：`Q` = `NSUInteger`(u64)、`q` = `NSInteger`(i64)、`I` = `uint32`、`i` = `int32`、`C`/`c` = `uint8`/`BOOL`、`S` = `uint16`、`f` = `float`、`d` = `double`、`@"X"` = 对象、`@?` = block、`#` = `Class`、`^v` = `void*`、`^Q` = `NSUInteger*`、`^f` = `float*`、`^{__IOSurface=}` = `IOSurfaceRef`、`{?=QQQ}` = `MTLSize`、`{?=dddd}` = `MTLClearColor`、`{?=CCCC}` = `MTLTextureSwizzleChannels`、`{_NSRange=QQ}` = `NSRange`。

### 0.2 两层类结构

`KNOWN`（`D-OBJC`，与 `20-OBJC-DEVICE.md` 第 2.1 节同构）：Metal 对 descriptor 也分两层。

- 公开层 `MTLFooDescriptor`：声明全部 `@property`，大多标 `D`（`@dynamic`），**没有实存 ivar**。
- 实现层 `MTLFooDescriptorInternal : MTLFooDescriptor`：持有一个 `_private` 结构（或指针），访问器直读该结构。

因此**公开类不能被直接实例化使用**：`+[MTLTextureDescriptor alloc]` 在 `D-OBJC:14918` 被显式覆写，用途是把 `alloc` 重定向到 `Internal` 子类。本项目的 shim 永远只接收 Metal 客户端传进来的对象，不构造 descriptor，所以这一层对我们只有一个后果：**所有字段都必须通过 selector 读，不得按偏移读 ivar**（`_private` 的布局是私有且版本相关的）。

本文的字段表给出 `_private` 结构编码，**仅用于解释默认值的来源与定位 getter**，不作为实现手段。

---

## 1. 为什么必须 snapshot

### 1.1 descriptor 是可变对象，调用返回后调用者可以改

`KNOWN`。全部 descriptor 类都声明 `<NSCopying>`（`D-OBJC`，424 个 `@interface` 中 descriptor 类无一例外），且绝大多数字段是 `N`（nonatomic）可写属性。Metal 的契约是：**`newXWithDescriptor:` 在返回之前读完 descriptor，之后 descriptor 与产物无关**。标准做法是客户端复用一个 descriptor 对象连续创建多个资源：

```objc
MTLTextureDescriptor *d = [MTLTextureDescriptor new];
d.width = 1024; d.height = 768;
id<MTLTexture> a = [dev newTextureWithDescriptor:d];
d.width = 512;                      // 合法，且立刻生效
id<MTLTexture> b = [dev newTextureWithDescriptor:d];
```

如果本项目的 ObjC 层把 descriptor 的 `id` 存起来、等到 Rust 侧需要时再读，`a` 的宽度会变成 512。因此规则是硬的：

> **R1**：任何接受 descriptor 的 selector，必须在该 ObjC 方法返回之前，把 descriptor 的全部相关字段读入一个不可变的 C 结构（snapshot），并且之后只使用 snapshot。`INFERRED`（实现选择，但由上述 Metal 语义强制）
>
> **R2**：snapshot 不得保存 descriptor 对象本身的指针，连作诊断也不行。descriptor 可能在下一行就被 `release`。

`40-RUNTIME-VULKAN.md` 第 3.1 节与第 5 节从上游侧给出同一结论：上游的 descriptor 是"带公开字段的纯值"，`setter` 就是字段写入，没有内部可变共享。把 ObjC 的可变对象直接接到上游的纯值上，中间必须有一次拷贝，这次拷贝就是 snapshot。

### 1.2 读 descriptor 有副作用 —— 懒创建

这是 snapshot 规则里最容易写错的一条，且与"只读一次"的直觉冲突。

`KNOWN`：`-[MTLRenderPassDescriptorInternal depthAttachment]`（`S-METAL +0x19BCD`）在字段为 `nullptr` 时 **`objc_alloc_init` 一个 `MTLRenderPassDepthAttachmentDescriptorInternal` 并用 `__sync_val_compare_and_swap` 装进 `_private.attachments->_depth_descriptor`**。`stencilAttachment`（`S-METAL +0x19D6D`）同构。

`KNOWN`：`-[MTLDepthStencilDescriptorInternal frontFaceStencil]`（`S-METAL +0x20BD6`）同样懒创建一个 `MTLStencilDescriptorInternal`，但**用的是普通赋值，没有 CAS**。

由此推出三条实现规则：

> **R3**：`depthAttachment` / `stencilAttachment` / `frontFaceStencil` / `backFaceStencil` 的 getter 会**修改调用者的 descriptor**。snapshot 代码必须接受这一点（没有别的访问路径），但必须在**客户端调用线程上**执行，不得挪到工作线程。`frontFaceStencil` 的懒创建不是原子的，两个线程同时读同一个 `MTLDepthStencilDescriptor` 会泄漏一个对象并可能返回两个不同指针。
>
> **R4**：**"attachment 存在"不等于"attachment 生效"。** 判定依据只能是 `texture != nil`。读过 `depthAttachment` 的 pass descriptor 一定有一个非 nil 的 depth attachment 对象，其 `loadAction` 还是 `MTLLoadActionClear`（第 4.4.3 节），如果按"对象非 nil 就当作有 depth attachment"处理，就会给一个没有 depth 纹理的 pass 配上 depth clear。
>
> **R5**：snapshot 过程本身不得对 descriptor 调用任何 setter。

### 1.3 `colorAttachments` 是下标容器，不是数组

`KNOWN`（`D-OBJC:13092`）：`MTLRenderPassColorAttachmentDescriptorArray` 只有三个方法：

```
-[MTLRenderPassColorAttachmentDescriptorArray objectAtIndexedSubscript:]
-[MTLRenderPassColorAttachmentDescriptorArray setObject:atIndexedSubscript:]
-[MTLRenderPassColorAttachmentDescriptorArray _descriptorAtIndex:]
```

它不是 `NSArray`：没有 `count`、不可枚举，`objectAtIndexedSubscript:` 对任何合法下标都返回一个对象（同样是懒创建）。同一形态出现在 `MTLRenderPipelineColorAttachmentDescriptorArray`、`MTLTileRenderPipelineColorAttachmentDescriptorArray`、`MTLVertexAttributeDescriptorArray`、`MTLVertexBufferLayoutDescriptorArray`、`MTLAttributeDescriptorArray`、`MTLBufferLayoutDescriptorArray`、`MTLPipelineBufferDescriptorArray`、`MTLRenderPassSampleBufferAttachmentDescriptorArray`、`MTLRasterizationRateLayerArray`、`MTLRasterizationRateSampleArray`、`MTLAccelerationStructurePassSampleBufferAttachmentDescriptorArray`、`MTLBlitPassSampleBufferAttachmentDescriptorArray`、`MTLComputePassSampleBufferAttachmentDescriptorArray`、`MTLResourceStatePassSampleBufferAttachmentDescriptorArray`（`D-OBJC`，14 个容器类）。

> **R6**：容器必须按**固定上界逐下标遍历**，上界取自 `20-OBJC-DEVICE.md` 第 5.2.1 节的 device limits（color attachment 取 `maxColorAttachments`；vertex buffer / attribute 取 `maxVertexBuffers` / `maxVertexAttributes`），并与上游常量取小（color 侧为 `metal2vulkan_runtime::MAX_COLOR_ATTACHMENTS`，见 `40-RUNTIME-VULKAN.md` 第 2.5 节）。不得试图枚举容器。
>
> **R7**：遍历时每个槽位都必须读，但**生效判定在槽位内容上**：color attachment 槽位生效 iff `texture != nil`；pipeline color attachment 槽位生效 iff `pixelFormat != MTLPixelFormatInvalid`；vertex buffer layout 槽位生效 iff `stride != 0`；vertex attribute 槽位生效 iff `format != MTLVertexFormatInvalid`。`INFERRED`（与 Metal 的通行判定一致，需在 Gate 3 用真实客户端 trace 核对）。

### 1.4 snapshot 的字段分类

每个字段落入三类之一，处理方式不同：

| 类 | 判定 | snapshot 存什么 | 生命周期 |
|---|---|---|---|
| **标量** | 编码为 `Q q I i C c S f d` 或定长 struct（`{?=QQQ}`、`{?=dddd}`、`{?=CCCC}`、`{_NSRange=QQ}`） | 值本身，已做 checked-convert | 无 |
| **深拷贝** | 属性标 `C`，且内容是本项目要解释的数据（`NSString` label、`NSDictionary` preprocessorMacros、嵌套 descriptor 如 `vertexDescriptor` / `frontFaceStencil`、`MTLFunctionConstantValues`） | **内容的副本**：字符串拷成有界 UTF-8 字节、字典拷成有界键值对、嵌套 descriptor 递归 snapshot | 归 snapshot 所有 |
| **对象句柄** | 属性标 `&`（retain），且对象是本项目自己的 proxy（`id<MTLTexture>`、`id<MTLBuffer>`、`id<MTLFunction>`、`id<MTLCounterSampleBuffer>`、`id<MTLRasterizationRateMap>`、`id<MTLLogState>`、`id<MTLCounterSet>`、`id<MTLLibrary>`） | **本项目的 object id（上游 `ObjectId`）**，不是指针 | 见下 |

> **R8**：对象句柄字段在 snapshot 里存 object id。snapshot 生成时必须对每个被引用的 proxy 做一次 `retain`，并把这些 retain 的所有权交给 snapshot；snapshot 释放时逐个 `release`。理由：descriptor 只 `retain` 到它自己被改写或析构为止，而我们的提交可能比它活得长。
>
> **R9**：object id 必须用上游的 `ObjectId`（终身唯一、永不复用，`40-RUNTIME-VULKAN.md` 第 3.2 节），不得用 ObjC 指针、不得自编号。指针会被复用，复用过的指针会让"这个 texture 还是不是刚才那个"变成无法判定的问题。
>
> **R10**：句柄字段必须做 **kind 校验与 namespace 校验**：`color[i].texture` 必须解析到一个 Texture、必须属于当前 client、必须属于当前 generation。三项任一不成立即拒绝（第 3 节）。

### 1.5 snapshot 的不可变性

> **R11**：snapshot 一旦生成即不可变（Rust 侧按值传递或 `Arc<Snapshot>`），不得在 Rust 侧回头补读 ObjC 字段。需要"晚一点才知道的信息"（例如 IOSurface 的真实行距）必须由 Rust 侧**自己重新测量**，不得用 descriptor 里客户端声明的值（`50-IPC-HELPER.md` 第 7 节）。

---

## 2. descriptor 类全量清单

`KNOWN`（`D-OBJC`）。下表是 25G325 x86_64 Metal.framework 中全部 descriptor / options / handle 类，按本文的处理分组。"字段"列只数公开 `@property`，不数 `_private` 里的私有字段。

### 2.1 Metal 2/3 API 面（本项目必须实现）

| # | 类 | 基类 | 字段 | `D-OBJC` 行 | 节 |
|---:|---|---|---:|---|---|
| 1 | `MTLTextureDescriptor` | `NSObject` | 19 | 14918 | 4.1 |
| 2 | `MTLBufferDescriptor`（SPI） | `NSObject` | 16 | 7082 | 4.2 |
| 3 | `MTLTextureViewDescriptor`（SPI） | `NSObject` | 9 | 15073 | 4.3 |
| 4 | `MTLRenderPassDescriptor` | `NSObject` | 17 | 13224 | 4.4.1 |
| 5 | `MTLRenderPassAttachmentDescriptor` | `NSObject` | 11 | 13063 | 4.4.2 |
| 6 | `MTLRenderPassColorAttachmentDescriptor` | ↑ | +1 | 13082 | 4.4.3 |
| 7 | `MTLRenderPassDepthAttachmentDescriptor` | ↑ | +2 | 13165 | 4.4.3 |
| 8 | `MTLRenderPassStencilAttachmentDescriptor` | ↑ | +2 | 13404 | 4.4.3 |
| 9 | `MTLRenderPassSampleBufferAttachmentDescriptor` | `NSObject` | 5 | 13337 | 4.4.4 |
| 10 | `MTLRenderPipelineDescriptor` | `NSObject` | 34 | 13551 | 4.5.1 |
| 11 | `MTLRenderPipelineColorAttachmentDescriptor` | `NSObject` | 9 | 13463 | 4.5.2 |
| 12 | `MTLPipelineBufferDescriptor` | `NSObject` | 1 | 12668 | 4.5.3 |
| 13 | `MTLComputePipelineDescriptor` | `NSObject` | 18 | 7945 | 4.6 |
| 14 | `MTLTileRenderPipelineDescriptor` | `NSObject` | 14 | 15214 | 4.7 |
| 15 | `MTLTileRenderPipelineColorAttachmentDescriptor` | `NSObject` | 1 | 15156 | 4.7 |
| 16 | `MTLMeshRenderPipelineDescriptor` | `NSObject` | 29 | 12257 | 4.8 |
| 17 | `MTLRenderPipelineFunctionsDescriptor`（SPI） | `NSObject` | 10 | 13858 | 4.9 |
| 18 | `MTLDepthStencilDescriptor` | `NSObject` | 7 | 8317 | 4.10 |
| 19 | `MTLStencilDescriptor` | `NSObject` | 7 | 14512 | 4.10 |
| 20 | `MTLSamplerDescriptor` | `NSObject` | 20 | 14237 | 4.11 |
| 21 | `MTLVertexDescriptor` | `NSObject` | 2 | 15511 | 4.12 |
| 22 | `MTLVertexAttributeDescriptor` | `NSObject` | 3 | 15367 | 4.12 |
| 23 | `MTLVertexBufferLayoutDescriptor` | `NSObject` | 3 | 15449 | 4.12 |
| 24 | `MTLStageInputOutputDescriptor` | `NSObject` | 4 | 14462 | 4.13 |
| 25 | `MTLAttributeDescriptor` | `NSObject` | 3 | 6329 | 4.13 |
| 26 | `MTLBufferLayoutDescriptor` | `NSObject` | 3 | 7157 | 4.13 |
| 27 | `MTLHeapDescriptor` | `NSObject` | 8 | 10315 | 4.14 |
| 28 | `MTLIndirectCommandBufferDescriptor` | `NSObject` | 29 | 11783 | 4.15 |
| 29 | `MTLArgumentDescriptor` | `NSObject` | 6 | 6185 | 4.16 |
| 30 | `MTLIndirectArgumentDescriptor`（SPI） | `MTLArgumentDescriptor` | 6（重声明） | 11734 | 4.16 |
| 31 | `MTLBinaryArchiveDescriptor` | `NSObject` | 3 | 6718 | 4.17 |
| 32 | `MTLCaptureDescriptor` | `NSObject` | 3 | 7284 | 4.18 |
| 33 | `MTLCounterSampleBufferDescriptor` | `NSObject` | 4 | 8168 | 4.19 |
| 34 | `MTLFunctionDescriptor` | `NSObject` | 5 | 9495 | 4.20 |
| 35 | `MTLIntersectionFunctionDescriptor` | `MTLFunctionDescriptor` | 0 | 12058 | 4.20 |
| 36 | `MTLStitchedLibraryDescriptor` | `NSObject` | 4 | 14561 | 4.20 |
| 37 | `MTLStitchedLibraryDescriptorSPI` | ↑ | 0 | — | 4.20 |
| 38 | `MTLDynamicLibraryDescriptorSPI` | `NSObject` | 4 | 9342 | 4.20 |
| 39 | `MTLLinkedFunctions` | `NSObject` | 4 | 12103 | 4.21 |
| 40 | `MTLCompileOptions` | `NSObject` | 21 | 7595 | 4.22 |
| 41 | `MTLRasterizationRateMapDescriptor` | `NSObject` | 4 | 12975 | 4.23 |
| 42 | `MTLRasterizationRateLayerDescriptor` | `NSObject` | 6 | 12926 | 4.23 |
| 43 | `MTLAccelerationStructureDescriptor` | `NSObject` | 1 | 5717 | 4.24 |
| 44 | `MTLAccelerationStructureGeometryDescriptor` | `NSObject` | 8 | 5735 | 4.24 |
| 45 | `MTLAccelerationStructureTriangleGeometryDescriptor` | ↑ | +11 | 6032 | 4.24 |
| 46 | `MTLAccelerationStructureBoundingBoxGeometryDescriptor` | ↑ | +4 | 5594 | 4.24 |
| 47 | `MTLAccelerationStructureCurveGeometryDescriptor` | ↑ | +18 | 5628 | 4.24 |
| 48 | `MTLAccelerationStructureMotionTriangleGeometryDescriptor` | ↑ | +10 | 5893 | 4.24 |
| 49 | `MTLAccelerationStructureMotionBoundingBoxGeometryDescriptor` | ↑ | +3 | 5782 | 4.24 |
| 50 | `MTLAccelerationStructureMotionCurveGeometryDescriptor` | ↑ | +16 | 5812 | 4.24 |
| 51 | `MTLPrimitiveAccelerationStructureDescriptor` | `MTLAccelerationStructureDescriptor` | +6 | 12825 | 4.24 |
| 52 | `MTLInstanceAccelerationStructureDescriptor` | ↑ | +12 | 11990 | 4.24 |
| 53 | `MTLIndirectInstanceAccelerationStructureDescriptor` | ↑ | +15 | 11910 | 4.24 |
| 54 | `MTLAccelerationStructureAllocationDescriptor`（SPI） | `NSObject` | 3 | 5569 | 4.24 |
| 55 | `MTLSharedTextureHandle` | `NSObject` | 2 | 14438 | 4.25 |
| 56 | `MTLResidencySetDescriptor` | `NSObject` | 2 | 14017 | 4.26 |
| 57 | `MTLIOCommandQueueDescriptor` | `NSObject` | 6 | 11592 | 4.27 |
| 58 | `MTLLogStateDescriptor` | `NSObject` | 2 | 12219 | 4.28 |
| 59 | `MTLCommandQueueDescriptor` | `NSObject` | 2 | 7389 | 4.29.1 |
| 60 | `MTLCommandBufferDescriptor` | `NSObject` | 3 | 7369 | 4.29.1 |
| 61 | `MTLComputePassDescriptor` | `NSObject` | 2 | 7838 | 4.29.2 |
| 62 | `MTLComputePassSampleBufferAttachmentDescriptor` | `NSObject` | 3 | 7884 | 4.29.2 |
| 63 | `MTLBlitPassDescriptor` | `NSObject` | 1 | 6939 | 4.29.2 |
| 64 | `MTLBlitPassSampleBufferAttachmentDescriptor` | `NSObject` | 3 | 6972 | 4.29.2 |
| 65 | `MTLResourceStatePassDescriptor` | `NSObject` | 1 | 14113 | 4.29.2 |
| 66 | `MTLResourceStatePassSampleBufferAttachmentDescriptor` | `NSObject` | 3 | 14146 | 4.29.2 |
| 67 | `MTLAccelerationStructurePassDescriptor` | `NSObject` | 1 | 5951 | 4.29.2 |
| 68 | `MTLAccelerationStructurePassSampleBufferAttachmentDescriptor` | `NSObject` | 3 | 5989 | 4.29.2 |
| 69 | `MTLVisibleFunctionTableDescriptor` | `NSObject` | 3 | 15553 | 4.29.3 |
| 70 | `MTLIntersectionFunctionTableDescriptor` | `NSObject` | 3 | 12062 | 4.29.3 |
| 71 | `MTLFunctionConstantValues` | `NSObject` | 0（纯方法） | 9456 | 4.29.4 |
| 72 | `MTLTensorDescriptor` | `NSObject` | 10 | 14784 | 4.29.5 |
| 73 | `MTLResourceViewPoolDescriptor`（SPI） | `NSObject` | 4 | 14207 | 4.29.5 |
| 74 | `MTLMotionEstimationPipelineDescriptor`（SPI） | `NSObject` | 2 | 12504 | 4.29.5 |
| 75 | `MTLBVHDescriptor`（SPI） | `NSObject` | — | 7049 | 4.29.5 |
| 76 | `MTLIOAccelServiceDescriptor`（内部） | `NSObject` | 2 | 11355 | 4.29.6 |

**合计 76 个类，公开 `@property` 字段 522 个**（75 个类计数完整，`MTLBVHDescriptor` 的字段未逐项取）（含子类追加项；不含 `*Internal` 的重声明与 `_private` 私有字段）。

### 2.2 Metal 4 API 面（`MTL4*`，本项目第一版不实现，但必须登记）

`KNOWN`（`D-OBJC`）。25G325 的 Metal.framework 已带完整 Metal 4 对象族，共 35 个 `MTL4*` descriptor / options 类：

`MTL4AccelerationStructureDescriptor`、`MTL4AccelerationStructureGeometryDescriptor` 及其 6 个几何子类、`MTL4PrimitiveAccelerationStructureDescriptor`、`MTL4InstanceAccelerationStructureDescriptor`、`MTL4IndirectInstanceAccelerationStructureDescriptor`、`MTL4ArgumentTableDescriptor`、`MTL4BinaryFunctionDescriptor`、`MTL4CommandAllocatorDescriptor`、`MTL4CommandBufferOptions`、`MTL4CommandQueueDescriptor`、`MTL4CommitOptions`、`MTL4CompilerDescriptor`、`MTL4CompilerTaskOptions`、`MTL4ComputePipelineDescriptor`、`MTL4CounterHeapDescriptor`、`MTL4FunctionDescriptor`、`MTL4LibraryDescriptor`、`MTL4LibraryFunctionDescriptor`、`MTL4MachineLearningPipelineDescriptor`、`MTL4MeshRenderPipelineDescriptor`、`MTL4PipelineDataSetSerializerDescriptor`、`MTL4PipelineDescriptor`、`MTL4PipelineOptions`、`MTL4PipelineStageDynamicLinkingDescriptor`、`MTL4RenderPassDescriptor`、`MTL4RenderPipelineBinaryFunctionsDescriptor`、`MTL4RenderPipelineColorAttachmentDescriptor`(+Array)、`MTL4RenderPipelineDescriptor`、`MTL4RenderPipelineDynamicLinkingDescriptor`、`MTL4SpecializedFunctionDescriptor`、`MTL4StaticLinkingDescriptor`、`MTL4StitchedFunctionDescriptor`、`MTL4TileRenderPipelineDescriptor`。

**处置**：`INFERRED`。本项目的 Device 类不声明 `MTL4Device` 相关协议，因此 Metal 4 入口不会被选中。对应的 selector 一个都不注册（`bridge-runtime-contract.md` 第 1 节的"未列入的 selector 不注册"在此继续有效）。

`BLOCKED`：**WindowServer 在 26.7.2 上走 Metal 2/3 还是 Metal 4 入口未实测。** 这是本文最大的单点风险 —— 如果 WindowServer 用 `MTL4CommandQueue` 合成，则上表 2.1 的全部工作不足以出画面。关闭方式：在目标 guest 上对 WindowServer 做一次 selector trace（`80-TEST-HARNESS.md` 的 guest agent），统计 `MTL4*` 协议的调用计数。该项优先于 2.1 节的任何实现工作，成本是一次 trace。

### 2.3 不是 descriptor 的同名物

以下类名含 `Descriptor` 但不是输入 descriptor，**不在本文范围**：`MTLArgument` / `MTLAttribute` / `MTLVertexAttribute` / `MTLStructMember` / `MTLType` 族（反射输出）、`MTL4ArchiveReply`、`MTL4BinaryFunctionReflection`、`MTL4MachineLearningPipelineReflection`、`MTLRenderPipelineReflection`、`MTLComputePipelineReflection`、`MTLMotionEstimatorCapabilities`、`MTLLogicalToPhysicalColorAttachmentMap`。它们由 `21-OBJC-OBJECT-FAMILY.md` 负责（反射对象是**输出**，所有权与 snapshot 规则相反：由我们构造、交给客户端）。

---

## 3. 校验规则总则

本节定义全局规则；第 4 节的每个字段表给出该字段的具体合法域。`INFERRED`（实现选择），但第 3.6 节的"必须拒绝 / 可以忽略"分界线直接取自上游的错误模型（`40-RUNTIME-VULKAN.md` 第 2.9 节）。

### 3.1 校验发生的位置

```text
ObjC shim（编译为 .m，用 typed getter）
  │ ① 读字段 → 原始位型
  │ ② checked-convert：枚举、整数宽度、浮点有限性、flag bit
  ▼
不可变 snapshot（C 结构，全部字段已归一化）
  │ ③ 跨字段一致性校验（在 Rust 侧，因为需要 device limits 与对象表）
  ▼
上游值类型
```

> **R12**：②（逐字段）必须在 ObjC shim 里做，因为只有那里知道正确的类型；③（跨字段）必须在 Rust 侧做，因为只有那里有对象表与 limits。两者都不能省：②失败时 snapshot 不生成，③失败时 snapshot 生成但不被消费。
>
> **R13**：校验失败的后果按 Metal 的行为分三档，由字段表逐项指定：`abort`（Metal 自己也结束进程）、`nil+NSError`、`nil`（无 error）。**不得统一成一种。** 客户端（尤其是 WindowServer）对这三档的反应完全不同。

### 3.2 枚举：checked-convert，不得 transmute

> **R14**：每个枚举字段都必须经过一次"原始 `NSUInteger` → 已知取值"的受检转换。上游为大部分枚举提供了 `from_raw`（`LoadAction::from_raw`、`StoreAction::from_raw`、`DrawPrimitiveType::from_raw`、`ResourceOptions::from_raw` 等，见 `40-RUNTIME-VULKAN.md` 第 3.2 节），**必须用它，不得自己 `transmute`**。
>
> **R15**：上游没给 `from_raw` 的枚举（本项目自有的 flag word，如 `MTLIndirectCommandBufferDescriptor.commandTypes`）必须自建受检转换，且**默认拒绝未知取值**。

一个必须特殊处理的例子：`MTLPrimitiveType` 的私有取值 5–8 是合法的（line loop / triangle fan / quads / quad strip），**取值 9 不是合法值但 Metal 不拒绝它** —— Metal 会让命令缓冲以 GPU 方式失败。上游 `DrawPrimitiveType::from_raw` 已经编码了这个区分（`40-RUNTIME-VULKAN.md` 第 3.2 节）。同类"看起来越界但 Metal 接受"的取值在 `REFUSALS.md` 的 `metal-takes` basis 下共 28 条，本项目**不得在这 28 条上比 Metal 更严格**。

### 3.3 整数：宽度与溢出

ObjC 侧的 `NSUInteger` 是 64 位，上游的对应参数很多是 `u32`（索引、计数、offset 的一部分）。

> **R16**：每一次宽度收窄都是一次 `checked` 转换。失败返回该字段表指定的档位，**不得截断**。
>
> **R17**：每一次 `offset + size`、`bytes_per_row * (height - 1) + width * bpp`、`stride * count`、`level_count` 推导出的 mip 尺寸链，都必须用 checked 乘加。任一步溢出即拒绝。这些计算必须在**映射、分配、调用上游之前**完成（取自 `bridge-runtime-contract.md` 第 8.5 节，该条仍然成立）。
>
> **R18**：尺寸类字段（`width`/`height`/`depth`/`arrayLength`/`sampleCount`/`mipmapLevelCount`/`size`/`length`）必须同时过三道闸：本文固定上限、`DeviceProperties` 的实测上限、协议上限（`50-IPC-HELPER.md` 第 2.6 节）。取三者最小。

### 3.4 浮点：拒绝非有限值

> **R19**：全部 `f` / `d` 字段必须拒绝 NaN 与 ±Inf。涉及字段（`D-OBJC` 全量）：`clearColor.{red,green,blue,alpha}`（`d`×4）、`clearDepth`（`d`）、`lodMinClamp` / `lodMaxClamp` / `lodBias`（`f`）、`motionStartTime` / `motionEndTime`（`f`）、`MTLRasterizationRateLayerDescriptor.horizontal`/`vertical` 指向的 `float` 数组、`MTLSamplePosition.{x,y}`（`{?=ff}`）。

理由不是洁癖：`clearColor` 的 NaN 会被 Lavapipe 写进 attachment，之后每个读到该像素的 shader 的算术结果都不确定；`lodMaxClamp` 的 NaN 会让 `VkSamplerCreateInfo::maxLod` 进入未定义行为。

额外规则：

> **R20**：`lodMinClamp <= lodMaxClamp` 必须成立。默认值是 `0.0` 与 `FLT_MAX`（`S-METAL +0x23728`，见第 4.11 节），客户端可以把它们设反。
>
> **R21**：`motionStartTime <= motionEndTime` 必须成立。

### 3.5 Flag bit：按字段决定未知位的处置

Metal 的 flag word 有两类，处置相反：

| 类 | 字段 | 未知位处置 |
|---|---|---|
| **封闭集**：bit 的集合由 SDK 固定，新增 bit 意味着新功能 | `MTLTextureUsage`、`MTLResourceOptions`、`MTLColorWriteMask`、`MTLStoreActionOptions`、`MTLIndirectCommandType`、`MTLPipelineOption`、`MTLBinaryArchiveOption`、`MTLAccelerationStructureUsage`、`MTLTensorUsage`、`MTLResourceUsage` | **拒绝**。未知位意味着客户端要求一个我们不知道的语义，静默忽略会让客户端以为生效了 |
| **保留/填充**：bit 用于内部打包，SDK 从不让客户端设 | `MTLRenderPipelineDescriptor` `_private` 的 `private1/private5/private9`、`MTLComputePipelineDescriptorPrivate` 的 `reserved b29`、`MTLPipelineBufferDescriptorPrivate` 的 `mutability b2` 以外的位 | 这些不可从公开 API 到达，shim 根本不读 |

> **R22**：封闭集 flag 的校验方式是 `raw & !KNOWN_MASK != 0 → 拒绝`。`KNOWN_MASK` 必须由上游的类型化 flag 定义导出（`ResourceOptions`、`metal2vulkan::metal::TextureUsage`），不得在本项目手写常量。

一处例外，必须写明：`MTLTextureUsage` 的 `MTLTextureUsageUnknown` 是 **0**，不是一个 bit。`0` 是合法输入（意思是"不声明用途"），不能当成"空集所以非法"。`KNOWN`（`S-METAL +0xA38F`：`init` 把 usage 设为 `enableTextureUsageUnknownDefault() ^ 1`，即该函数为真时默认值就是 0）。

### 3.6 "必须拒绝"与"可以忽略"的分界

这是本节唯一不能靠直觉的部分。分界线是：**这个字段会不会改变客户端能观察到的结果。**

| 档 | 判定 | 处置 | 例 |
|---|---|---|---|
| **A. 必须拒绝（硬错）** | 字段值非法，或字段合法但我们无法给出 Metal 的答案，且**不给答案会让客户端拿到错的像素/错的数据** | 按 R13 的三档之一失败。**不得伪造成功**（`40-RUNTIME-VULKAN.md` 第 2.9 节 `NotImplemented` 行） | 未知枚举值；溢出；非有限浮点；`color[i].texture` 解析不到对象；pipeline 的 `colorAttachments[i].pixelFormat` 在上游无候选 |
| **B. 必须拒绝（能力错）** | 字段要求一个本栈没有的能力 | 返回 `Unsupported` 并把缺什么写进 wire error（`50-IPC-HELPER.md` 第 4 节）；capability 查询同步返回 false | sparse 相关的 `placementSparsePageSize` ≠ 0（Lavapipe 的 sparse 仅 Linux，`40-RUNTIME-VULKAN.md` 第 2.2 节）；`MTLAccelerationStructure*` 全族；`MTLDynamicLibrary` 的链接使用 |
| **C. 可以忽略（纯提示）** | 字段只影响性能、调试或诊断，不影响任何客户端可观察的数据 | 记录到 degradation 日志，继续 | `label`（全部类）；`allowGPUOptimizedContents`；`compressionType` / `compressionFootprint`（无损压缩是性能提示）；`MTLCompileOptions.compileTimeStatisticsEnabled`；`MTLHeapDescriptor.maxCompatiblePlacementSparsePageSize`（在不支持 sparse 时）；`MTLCommandBufferDescriptor.retainedReferences`（ObjC 侧的 retain 策略，由 shim 自己决定，`40-RUNTIME-VULKAN.md` 第 2 节指出这类簿记归 `_MTLCommandBuffer` 抽象层）；`hazardTrackingMode`（上游按 barrier 策略处理，见第 5 节） |
| **D. 可以忽略（已是默认）** | 字段非默认但其值与我们的实现恰好等价 | 继续，不记日志 | `storageMode == Managed` 与 `Shared` 在 Lavapipe（统一内存、单一 host-visible heap）上等价 —— **但仍必须按声明值回答 getter**，见 R24 |

> **R23**：第 C 档的"忽略"只允许忽略**行为**，不允许忽略**回答**。客户端把 `label` 设成 `"foo"` 之后读回来必须是 `"foo"`。
>
> **R24**：第 D 档同理：`storageMode` 的行为可以等价，但 `texture.storageMode` 必须返回客户端创建时给的值，不得返回我们实际用的值。snapshot 因此要同时保存"声明值"（用于回答 getter）与"归一化值"（用于调上游）。

### 3.7 两类必须拒绝但容易漏的组合约束

`KNOWN`（上游行为，`40-RUNTIME-VULKAN.md` 第 3.2 节）：

1. **`TextureDescriptor::rotation`（0–4，SPI）必须同时设 `framebuffer_only`**，否则按 Metal 的 assert 拒绝。ObjC 侧对应 `MTLTextureDescriptorInternal` 的 `rotation` 与 `framebufferOnly`（`D-OBJC:14957` 的 `_private` 结构）。
2. **pipeline descriptor 的 `setResourceIndex:`（SPI）→ `PipelineOptions::placement`**：取低 32 位，且必须 `< 16384`。涉及 `MTLRenderPipelineDescriptor.resourceIndex`（经 `_private.resourceIndex`）、`MTLComputePipelineDescriptor.resourceIndex`、`MTLTileRenderPipelineDescriptor`、`MTLMeshRenderPipelineDescriptor.resourceIndex`、`MTLSamplerDescriptor.resourceIndex`、`MTLDepthStencilDescriptor.resourceIndex`、`MTLTextureDescriptor.resourceIndex`、`MTLVisibleFunctionTableDescriptor.resourceIndex`、`MTLIntersectionFunctionTableDescriptor.resourceIndex`、`MTLIndirectCommandBufferDescriptor.resourceIndex`、`MTLAccelerationStructureAllocationDescriptor.resourceIndex`、`MTLTensorDescriptor.resourceIndex`、`MTLTextureViewDescriptor.resourceIndex`（13 处，`D-OBJC` 全量）。每处都配一个 `forceResourceIndex`（`c`）开关，**只有 `forceResourceIndex == YES` 时 `resourceIndex` 才有意义**。

> **R25**：13 个 `resourceIndex` 字段必须统一经过同一个校验函数，输出 `Option<IdPlacement>`：`forceResourceIndex == NO` → `None`；`YES` 且 `resourceIndex < 16384` → `Some`；`YES` 且 `>= 16384` → 拒绝（A 档）。

---

## 4. 逐类字段表

表列约定：

- **字段**：属性名。若有自定义 getter（`G` 标志），写作 `属性名`（getter: `selector`）。
- **编码**：`D-OBJC` 的类型编码，直接决定 shim 中 getter 的签名。
- **默认**：`init` 之后的值。标 `S-METAL +RVA` 的是反编译取得的 `KNOWN`；标 `alloc0` 的是 `init` 未显式写、由 `objc_alloc` 的零填充决定（也是 `KNOWN`，但来源是"init 中无写入"这一否定事实）。
- **域 / 处置**：合法域与越界档位（第 3.6 节的 A/B/C/D）。
- **类**：第 1.4 节的 snapshot 分类（标量 / 深拷贝 / 句柄）。

### 4.1 `MTLTextureDescriptor`

`D-OBJC:14918`（公开层）、`D-OBJC:14957`（`MTLTextureDescriptorInternal`，`_private` = `MTLTextureDescriptorPrivate`）。
默认值来源：`-[MTLTextureDescriptorInternal init]`，`S-METAL +0xA38F`。

`_private` 在对象偏移 16 处，字段顺序（`KNOWN`，`D-OBJC:14957` 的结构编码）：
`textureType`(+0) `pixelFormat`(+8) `width`(+16) `height`(+24) `depth`(+32) `mipmapLevelCount`(+40) `sampleCount`(+48) `arrayLength`(+56) `zeroFill`(+64) `rotation`(+72) `framebufferOnly`(+80) `isDrawable`(+81) `swizzle`(+84) `writeSwizzleEnabled`(+88) `compressionMode`(+96) `usage∪textureUsage`(+104) `resourceOptions`(+112) `sparseSurfaceDefaultValue`(+120) `allowGPUOptimizedContents`(+128) `forceResourceIndex`(+129) `resourceIndex`(+136) `protectionOptions`(+144) `compressionFootprint`(+152) `compressionType`(+160) `colorSpaceConversionMatrix`(+168) `writeAccessPattern`(+176) `placementSparsePageSize`(+184) `resolvedUsage`(+192) `cpuCacheMode`(+200) `storageMode`(+208)。

| 字段 | 编码 | 默认 | 域 / 处置 | 类 |
|---|---|---|---|---|
| `textureType` | `Q` | **2**（`MTLTextureType2D`）`S-METAL +0xA38F` | `{0,1,2,3,4,5,6,7,8}`；未知值 → A | 标量 |
| `pixelFormat` | `Q` | **70**（`RGBA8Unorm`）同上 | 301 个取值之一；`Invalid`(0) / `Unspecialized`(263) → A；上游无候选（`40-RUNTIME-VULKAN.md` 第 8.2.14 节）→ B | 标量 |
| `width` | `Q` | **1** 同上 | `1..=16384`，再与 `DeviceProperties` 的 `max_texture_2d` 等取小；0 或超限 → A | 标量 |
| `height` | `Q` | **1** | 同上；1D 纹理必须为 1 | 标量 |
| `depth` | `Q` | **1** | 同上；非 3D 纹理必须为 1 | 标量 |
| `mipmapLevelCount` | `Q` | **1** | `1..=floor(log2(max(w,h,d)))+1`；超限 → A | 标量 |
| `sampleCount` | `Q` | **1** | 必须是 `supportsTextureSampleCount:` 为真的值；MSAA 纹理必须 `mipmapLevelCount == 1` → A | 标量 |
| `arrayLength` | `Q` | **1** | `1..=2048`；非 array 类型必须为 1 | 标量 |
| `resourceOptions` | `Q` | **16**（`MTLResourceStorageModeManaged`）`S-METAL +0xA38F`：`cpuCacheMode | (16 * (platform != iOS))` | `ResourceOptions::from_raw` 必须接受；未知位 → A | 标量 |
| `cpuCacheMode` | `Q` | **0**（`DefaultCache`） | `{0,1}`；未知 → A | 标量 |
| `storageMode` | `Q` | **1**（`Managed`，macOS 路径）`S-METAL +0xA38F`：`dyld_get_active_platform() != 2` | `{0,1,2,3}`；`Memoryless`(3) → B（Lavapipe 无 lazily-allocated 内存）；`Managed`/`Shared` → D | 标量 |
| `hazardTrackingMode` | `Q` | 由 `resourceOptions` 位 8–9 推出，默认 **0**（Default） | `{0,1,2}`；→ C | 标量 |
| `usage` | `Q` | **1**（`ShaderRead`）或 **0**（`Unknown`），取决于 `enableTextureUsageUnknownDefault()`。`S-METAL +0xA38F` | `metal2vulkan::metal::TextureUsage` 的已知位并集；`0` 合法（第 3.5 节）；未知位 → A | 标量 |
| `allowGPUOptimizedContents` | `c` | **YES**（`S-METAL +0xA38F`：`_private+128` 被写 1） | 任意 → C | 标量 |
| `compressionType` | `q` | **0**（Lossless） | `{0,1}`；`Lossy`(1) → C（按无压缩处理，记 degradation） | 标量 |
| `swizzle` | `{?=CCCC}` | **`{2,3,4,5}`** = identity（`S-METAL +0xA38F`：`_private+84 = 0x05040302`） | 每通道 ∈ `{0,1,2,3,4,5}`（Zero/One/Red/Green/Blue/Alpha）；未知 → A | 标量 |
| `placementSparsePageSize` | `q` | **0** | `0` 或 `{101,102,103}`；非 0 → B（sparse 在 macOS Lavapipe 不可用） | 标量 |
| `forceResourceIndex` | `c` | **NO**（`_private+129`） | 见 R25 | 标量 |
| `resourceIndex` | `Q` | **0**（`_private+136`） | 见 R25 | 标量 |

SPI 字段（只在 `MTLTextureDescriptorInternal` 上有 selector，公开层无 `@property`。`KNOWN`，`D-OBJC:14957` 的方法列表）：

| 字段 | selector | 默认 | 域 / 处置 |
|---|---|---|---|
| `framebufferOnly` | `framebufferOnly` / `setFramebufferOnly:` | **NO**（`_private+80`） | 与 `rotation` 联动，见 R24/第 3.7 节 |
| `isDrawable` | `isDrawable` / `setIsDrawable:` | **NO**（`_private+81`） | 仅 `CAMetalDrawable` 路径用；本项目不走（`40-RUNTIME-VULKAN.md` 第 4 节第 4 项）→ 非 NO 则 B |
| `rotation` | `rotation` / `setRotation:` | **0**（`_private+72`） | `0..=4`；非 0 要求 `framebufferOnly == YES`，否则 A |
| `writeSwizzleEnabled` | `writeSwizzleEnabled` / `setWriteSwizzleEnabled:` | **NO** | 非 NO → B |
| `writeAccessPattern` | `writeAccessPattern` / `setWriteAccessPattern:` | **0** | 非 0 → B |
| `compressionMode` | `compressionMode` / `setCompressionMode:` | **0** | → C |
| `compressionFootprint` | `compressionFootprint` / `setCompressionFootprint:` | **0** | → C |
| `lossyCompressionMode` | `lossyCompressionMode` / `setLossyCompressionMode:` | **0** | → C |
| `sparseSurfaceDefaultValue` | `sparseSurfaceDefaultValue` / `setSparseSurfaceDefaultValue:` | **0** | 非 0 → B |
| `colorSpaceConversionMatrix` | `colorSpaceConversionMatrix` / `setColorSpaceConversionMatrix:` | **0** | 非 0 → B（`Degradation::DeviceColorConversion` 的触发点） |
| `protectionOptions` | `protectionOptions` / `setProtectionOptions:` | **0** | 非 0 → B，且**取值 1、3、7 在 Metal 会结束进程，上游明确拒绝**（`40-RUNTIME-VULKAN.md` 第 3.2 节）；未测值返回 `AppleOnly::ProtectedContent` |
| `resolvedUsage` | `resolvedUsage`（只读） | **0**（alloc0） | 只读派生值，shim 不读 |
| `zeroFill` | 无公开 selector | alloc0 | 不可达 |
| `swizzleKey` | `swizzleKey` / `setSwizzleKey:` | — | 派生缓存，不读 |
| `validateWithDevice:` | — | — | Metal 自己的校验入口，**本项目不调用**（它会打 device 的私有路径） |

工厂方法（`D-OBJC:14918`，`KNOWN`）：`+texture2DDescriptorWithPixelFormat:width:height:mipmapped:`、`+textureCubeDescriptorWithPixelFormat:size:mipmapped:`、`+textureBufferDescriptorWithPixelFormat:width:resourceOptions:usage:`。这三个是 Metal.framework 自己实现的，返回一个已配置好的 descriptor，**本项目无需实现**，但要知道客户端常用它们，因此 snapshot 收到的 `usage` 常常不是默认值。

### 4.2 `MTLBufferDescriptor`（SPI）

`D-OBJC:7082`。**本类的全部字段都有实存 ivar**（无 `D`、无 `_private`），因此偏移稳定但仍不得直读。

| 字段 | 编码 | 默认 | 域 / 处置 | 类 |
|---|---|---|---|---|
| `length` | `Q` | 0（`-[MTLBufferDescriptor init]` 未写，alloc0） | `1..=1 GiB`（协议上限，`50-IPC-HELPER.md` 第 2.6 节）∩ `DeviceProperties::max_buffer_length`；0 → A | 标量 |
| `resourceOptions` | `Q` | 0 | 同 4.1；未知位 → A | 标量 |
| `cpuCacheMode` | `Q` | 派生 | `{0,1}` | 标量 |
| `storageMode` | `Q` | 派生 | 同 4.1 | 标量 |
| `hazardTrackingMode` | `Q` | 派生 | → C | 标量 |
| `contents` | `^v` | `NULL` | 与 `noCopy` 联动：`noCopy == YES` 时必须非 `NULL` 且**页对齐**（`VK_EXT_external_memory_host` 的 `minImportedHostPointerAlignment`）；否则 A | **特殊：客户端指针** |
| `noCopy` | `c` | NO | 见上 | 标量 |
| `deallocator` | `@?` | nil | `noCopy == YES` 时的释放回调；必须 `_Block_copy` 并在上游 `KeepAlive` 释放时调用一次 | 深拷贝（block copy） |
| `alignment` | `Q` | 0 | 0 或 2 的幂；非幂 → A | 标量 |
| `iosurface` | `^{__IOSurface=}` | `NULL` | 非 `NULL` 时走 `41-IOSURFACE-USERSPACE.md` 的导入路径；`IOSurfaceRef` 必须 `CFRetain` 并交给 snapshot | **特殊：IOSurface 句柄** |
| `addressRanges` | `@"MTLResourceAddressRangeArray"` | nil | 分散后备（`replaceBackingWithRanges:`）。上游要求先重映射成连续区再 `rebind_bytes_no_copy`（`40-RUNTIME-VULKAN.md` 第 4 节第 2 项）→ 非 nil 时 B，直到 `41` 分册实现 | 深拷贝 |
| `pinnedGPUAddress` | `Q` | 0 | 非 0 → `AddressPlacement`；要求 `bufferDeviceAddress`；冲突 → A（上游 `PlacementConflict`） | 标量 |
| `parentGPUAddress` | `Q` | 0 | 子分配。非 0 要求 `parentGPUSize` 非 0 且 `pinnedGPUAddress ∈ [parent, parent+size)` → 否则 A | 标量 |
| `parentGPUSize` | `Q` | 0 | 同上 | 标量 |
| `pointerTag` | `Q` | 0 | 非 0 → B（指针标签无 Vulkan 形式） | 标量 |
| `placementSparsePageSize` | `q` | 0 | 同 4.1 | 标量 |

> **R26**：`contents` 是**客户端的原始指针**。snapshot 存它，但**不得在 ObjC 方法返回后解引用**，除非走的是 `noCopy` 路径（此时所有权语义由 `deallocator` + 上游 `KeepAlive` 约束）。非 `noCopy` 路径（`newBufferWithBytes:length:options:`）必须**在 ObjC 方法返回前完成复制**（`bridge-runtime-contract.md` 第 4.3 节的该条成立，保留）。

### 4.3 `MTLTextureViewDescriptor`（SPI）

`D-OBJC:15073`。`_private` = `MTLTextureViewDescriptorPrivate`，字段顺序：`pixelFormat`(+0) `textureType`(+8) `levels`(+16,`NSRange`) `slices`(+32,`NSRange`) `writeAccessPattern`(+48) `swizzle`(+56,`I`) `resourceIndex`(+64)。

| 字段 | 编码 | 默认 | 域 / 处置 |
|---|---|---|---|
| `pixelFormat` | `Q` | 0 | 必须与基纹理格式**位布局兼容**；上游用 `imageViewFormatSwizzle` / view reinterpretation（`DeviceOptions::withhold_view_reinterpretation` 可关），不兼容 → A |
| `textureType` | `Q` | 0 | 同 4.1，且必须是基纹理类型的合法 view |
| `levels` / `levelRange` | `{_NSRange=QQ}` | `{0,0}` | `location + length <= base.mipmapLevelCount`，checked；`length == 0` → A |
| `slices` / `sliceRange` | `{_NSRange=QQ}` | `{0,0}` | `location + length <= base.arrayLength * (cube?6:1)`，checked |
| `swizzle` | `{?=CCCC}` | 0 | 同 4.1 |
| `writeAccessPattern` | `q` | 0 | 非 0 → B |
| `resourceIndex` | `Q` | 0 | 见 R25 |

注意两组别名：`levels`/`levelRange` 与 `slices`/`sliceRange` 是同一个 `_private` 字段的两个 selector 对（`D-OBJC:15073`）。shim 只读 `levelRange` / `sliceRange`，并为另一对注册转发到同一实现。

### 4.4 `MTLRenderPassDescriptor` 全族

#### 4.4.1 `MTLRenderPassDescriptor`

`D-OBJC:13224`（公开层）、`D-OBJC:13272`（`Internal`）。默认值：`-[MTLRenderPassDescriptorInternal init]`，`S-METAL +0x19801`。

`_private` 在对象偏移 48（公开层自带 4 个 `Q` + 1 个 `c` 的实存 ivar）。`_private` = `MTLRenderPassDescriptorPrivate`，字段顺序（`D-OBJC:13272`）：
`attachments`(+0) `visibilityResultBuffer`(+8) `renderTargetWidth`(+16) `renderTargetHeight`(+24) `defaultColorSampleCount`(+32) `fineGrainedBackgroundVisibilityEnabled`(+40) `skipEmptyTilesOnClearEnabled`(+41) `ditherEnabled`(+42) `openGLModeEnabled`(+43) `renderTargetArrayLength`(+48) `tileWidth`(+56) `tileHeight`(+64) `defaultSampleCount∪defaultRasterSampleCount`(+72) `imageBlockSampleLength`(+80) `threadgroupMemoryLength`(+88) `customSamplePositions`(+96, `[8]{?=ff}`) `numCustomSamplePositions`(+160) `rasterizationRateMap`(+168) `sampleBufferAttachments`(+176) `pointCoordYFlipEnabled`(+184) `visibilityResultType`(+192) `supportColorAttachmentMapping`(+200)。

`init` 只做四件事（`S-METAL +0x19801`）：分配 `MTLRenderPassColorAttachmentDescriptorArrayInternal`、把 `+8 … +200` 全部清零、分配 `MTLRenderPassSampleBufferAttachmentDescriptorArrayInternal`、把 `supportColorAttachmentMapping` 置 0。**depth / stencil attachment 不在 init 里分配**（第 1.2 节）。

| 字段 | 编码 | 默认 | 域 / 处置 | 类 |
|---|---|---|---|---|
| `colorAttachments` | `@"MTLRenderPassColorAttachmentDescriptorArray"`，`R,D` | 非 nil 容器 | 按 R6 逐下标读 `0..maxColorAttachments`；上界与 `MAX_COLOR_ATTACHMENTS` 取小 | 容器 |
| `depthAttachment` | `@"MTLRenderPassDepthAttachmentDescriptor"`，`C,D,N` | **nil，首次 get 时懒创建**（`S-METAL +0x19BCD`） | 生效 iff `.texture != nil`（R4） | 深拷贝（递归 snapshot） |
| `stencilAttachment` | 同上 | 同上（`S-METAL +0x19D6D`） | 同上 | 深拷贝 |
| `visibilityResultBuffer` | `@"<MTLBuffer>"`，`&,D,N` | nil | 非 nil 时必须解析到 Buffer（R10）；`length >= 8 * 可见性查询数` → 否则 A | 句柄 |
| `visibilityResultType` | `q` | 0 | `VisibilityResultMode` 的 `from_raw`；未知 → A | 标量 |
| `renderTargetArrayLength` | `Q` | 0 | `0..=2048`；0 表示由 attachment 推导 | 标量 |
| `renderTargetWidth` | `Q` | 0 | `0..=16384`；非 0 时必须 `<=` 全部 attachment 的实际宽 → 否则 A | 标量 |
| `renderTargetHeight` | `Q` | 0 | 同上 | 标量 |
| `defaultRasterSampleCount` | `Q` | 0 | 0 或 `supportsTextureSampleCount:` 为真的值 | 标量 |
| `imageblockSampleLength` | `Q`（实存 ivar） | 0 | 非 0 → B（imageblock 是 Apple GPU 的 tile 内存，无 Vulkan 形式） | 标量 |
| `threadgroupMemoryLength` | `Q`（实存 ivar） | 0 | `0..=maxThreadgroupMemoryLength` | 标量 |
| `tileWidth` | `Q`（实存 ivar） | 0 | 与 tile shading 联动；非 0 时要求 tile pipeline | 标量 |
| `tileHeight` | `Q`（实存 ivar） | 0 | 同上 | 标量 |
| `rasterizationRateMap` | `@"<MTLRasterizationRateMap>"`，`&,D,N` | nil | 非 nil 时解析句柄；上游有 `RasterizationRateMap`，但编译层有不编译的情形（`Error::RateMap(UnpinnedCompile)`，5 个 variant）→ 命中则 B | 句柄 |
| `sampleBufferAttachments` | `@"…Array"`，`R,D` | 非 nil 容器 | 逐下标读 `0..maxSampleBufferAttachments`（Metal 固定 4）；见 4.4.4 | 容器 |
| `supportColorAttachmentMapping` | `c`（实存 ivar） | NO | 非 NO → B（逻辑→物理 attachment 重映射，无上游对应） | 标量 |

SPI 字段（`D-OBJC:13272` 的方法列表，公开层无 `@property`）：

| 字段 | 默认 | 处置 |
|---|---|---|
| `defaultColorSampleCount` | 0 | 与 `defaultRasterSampleCount` 同义的旧名，读其一即可 |
| `customSamplePositions` / `getSamplePositions:count:` / `setSamplePositions:count:` | 空（`numCustomSamplePositions == 0`） | 非空 → 需 `VK_EXT_sample_locations`（Lavapipe 有，`40-RUNTIME-VULKAN.md` 第 6.2 节）；每个 `MTLSamplePosition` 的 `x`/`y` 过 R19；`count <= 8`（`[8{?=ff}]`，`D-OBJC:13272`） |
| `fineGrainedBackgroundVisibilityEnabled` | NO | 非 NO → B |
| `skipEmptyTilesOnClearEnabled` | NO | → C（纯优化提示） |
| `ditherEnabled` | NO | 非 NO → B |
| `openGLModeEnabled` | NO | 非 NO → B |
| `pointCoordYFlipEnabled` | NO | 非 NO → B（上游在 pipeline 侧有 `pointCoordLowerLeft` 位，二者关系未核） |
| `validate:width:height:` | — | Metal 自己的校验，**不调用** |

#### 4.4.2 `MTLRenderPassAttachmentDescriptor`（三个 attachment 的共同基类）

`D-OBJC:13063`。三个子类共用同一个 `_private` 结构 `MTLRenderPassAttachmentDescriptorPrivate`（`KNOWN`：`D-OBJC` 中 color / depth / stencil 三个 `Internal` 的 `_private` 编码**逐字相同**），在对象偏移 8，字段顺序：
`texture`(+0) `level`(+8) `slice`(+16) `depthPlane`(+24) `loadAction`(+32) `storeAction`(+40) `storeActionOptions`(+48) `clearColor`(+56, `{dddd}`) `clearDepth`(+88) `clearStencil`(+96) `stencilResolveFilter`(+104) `resolveTexture`(+112) `resolveLevel`(+120) `resolveSlice`(+128) `resolveDepthPlane`(+136) `resolveFilter`(+144) `width`(+152) `height`(+160) `yInvert`(+168)。

共同字段：

| 字段 | 编码 | 域 / 处置 | 类 |
|---|---|---|---|
| `texture` | `@"<MTLTexture>"`，`&,D,N` | **唯一的"生效"判据**（R4/R7）。非 nil 必须解析到 Texture、同 client、同 generation | 句柄 |
| `level` | `Q` | `< texture.mipmapLevelCount`，checked；越界 → A | 标量 |
| `slice` | `Q` | `< texture.arrayLength * (cube?6:1)`，checked | 标量 |
| `depthPlane` | `Q` | `< texture.depth`（仅 3D）；非 3D 必须为 0 | 标量 |
| `loadAction` | `Q` | `LoadAction::from_raw`；未知 → A | 标量 |
| `storeAction` | `Q` | `StoreAction::from_raw`；`MultisampleResolve`/`StoreAndMultisampleResolve` 要求 `resolveTexture != nil` → 否则 A | 标量 |
| `storeActionOptions` | `Q` | `StoreActionOptions`，封闭集，未知位 → A | 标量 |
| `resolveTexture` | `@"<MTLTexture>"`，`&,D,N` | 同 `texture` | 句柄 |
| `resolveLevel` / `resolveSlice` / `resolveDepthPlane` | `Q`×3 | 同 `level`/`slice`/`depthPlane`，但对 `resolveTexture` 判定 | 标量 |

#### 4.4.3 三个 attachment 子类的追加字段与默认值

**`MTLRenderPassColorAttachmentDescriptor`**（`D-OBJC:13082`）。默认值：`S-METAL +0x199E0`。

| 字段 | 编码 | 默认 | 域 / 处置 |
|---|---|---|---|
| `clearColor` | `{?=dddd}` | **`{0.0, 0.0, 0.0, 1.0}`**。`S-METAL +0x199E0` 读两个 16 字节常量：`_defaultClearColor` @ `S-METAL +0x2867F0` = `(0.0, 0.0)`，`xmmword` @ `S-METAL +0x286800` = `(0.0, 1.0)` | 4 个有限 `f64`（R19）；非有限 → A |
| （继承）`loadAction` | `Q` | **0 = `DontCare`** | — |
| （继承）`storeAction` | `Q` | **1 = `Store`** | — |
| （继承）`storeActionOptions` | `Q` | **0** | — |
| （继承）`clearDepth` | `d` | 1.0（共享结构，色彩附件不用） | 不读 |
| （继承）`yInvert` | `c` | **NO** | 非 NO → B |

**`MTLRenderPassDepthAttachmentDescriptor`**（`D-OBJC:13165`）。默认值：`S-METAL +0x19C92`。

| 字段 | 编码 | 默认 | 域 / 处置 |
|---|---|---|---|
| `clearDepth` | `d` | **1.0**（`_private+88 = 0x3FF0000000000000`） | 有限 `f64`，且 Metal 不夹紧到 `[0,1]`；非有限 → A |
| `depthResolveFilter` | `Q`（映射到 `_private+144 resolveFilter`） | **0**（`Sample0`） | `MultisampleDepthResolveFilter::from_raw`；**Lavapipe 只有 `SAMPLE_ZERO`**，`Min`/`Max` 需走上游替代 pass，必然触发 degradation（`40-RUNTIME-VULKAN.md` 第 8.2.13 节）→ 非 0 时记 degradation 后继续（C），不拒绝 |
| （继承）`loadAction` | `Q` | **2 = `Clear`**（`_private+32 = 2`，`S-METAL +0x19C92`） | — |
| （继承）`storeAction` | `Q` | **0 = `DontCare`** | — |

> **更正与警示**：depth / stencil attachment 的 `loadAction` 默认是 **`Clear`(2)**，`storeAction` 默认是 **`DontCare`(0)**；color attachment 的是 `DontCare`(0) / `Store`(1)。四个默认值两两不同，且 depth 的 `Clear` 与"默认都是 DontCare"的常见假设相反。`KNOWN`：`S-METAL +0x199E0`（color）与 `+0x19C92` / `+0x19E32`（depth / stencil）。
>
> 与 R4 合起来的后果：**先读 `depthAttachment` 再判断"有没有 depth"的代码会拿到一个 loadAction=Clear 的 attachment。** 如果实现把它当生效的，pass 会尝试 clear 一个 nil 纹理。判据必须是 `texture != nil`。

**`MTLRenderPassStencilAttachmentDescriptor`**（`D-OBJC:13404`）。默认值：`S-METAL +0x19E32`（与 depth 的 init 逐指令同构）。

| 字段 | 编码 | 默认 | 域 / 处置 |
|---|---|---|---|
| `clearStencil` | `I` | **0**（`_private+96`） | `uint32` 全域；实际写入时按 attachment 的 stencil 位宽取低 8 位（Metal 行为） |
| `stencilResolveFilter` | `Q`（`_private+104`） | **0** | `MultisampleStencilResolveFilter::from_raw`；同 depth，非 0 记 degradation（C） |
| （继承）`loadAction` | `Q` | **2 = `Clear`** | — |
| （继承）`storeAction` | `Q` | **0 = `DontCare`** | — |

#### 4.4.4 `MTLRenderPassSampleBufferAttachmentDescriptor`

`D-OBJC:13337`。

| 字段 | 编码 | 默认 | 域 / 处置 | 类 |
|---|---|---|---|---|
| `sampleBuffer` | `@"<MTLCounterSampleBuffer>"`，`&,D,N` | nil | 非 nil → B（上游无 counter sample buffer 类型，第 5 节） | 句柄 |
| `startOfVertexSampleIndex` | `Q` | `MTLCounterDontSample` = `NSUIntegerMax` | 必须是 `NSUIntegerMax` 或 `< sampleBuffer.sampleCount` | 标量 |
| `endOfVertexSampleIndex` | `Q` | 同上 | 同上 | 标量 |
| `startOfFragmentSampleIndex` | `Q` | 同上 | 同上 | 标量 |
| `endOfFragmentSampleIndex` | `Q` | 同上 | 同上 | 标量 |

`BLOCKED`：四个默认值未从 `-[MTLRenderPassSampleBufferAttachmentDescriptorInternal init]`（`S-METAL +0x1AED88`，即该类的 init，`D-OBJC:13379`）反编译确认。关闭方式：反编译该 init，看 `_private` 的四个 `Q` 是否被写成 `-1`。本文按 `MTLCounterDontSample` 记为 `INFERRED`。

### 4.5 `MTLRenderPipelineDescriptor` 全族

#### 4.5.1 `MTLRenderPipelineDescriptor`

`D-OBJC:13551`（公开层，34 个 `@property`）、`D-OBJC:13618`（`Internal`）。默认值：`-[MTLRenderPipelineDescriptorInternal init]`，`S-METAL +0x1AD4C`。

`_private` 在对象偏移 48（公开层 6 个实存 ivar）。`MTLRenderPipelineDescriptorPrivate` 共 736 字节、约 70 个字段，其中一个 8 字节的位域 union（`miscHash` / 24 个 bit 字段）承载全部 BOOL 与窄枚举。完整编码见 `D-OBJC:13618`。本表给出全部可从公开 API 到达的字段。

| 字段 | 编码 | 默认 | 域 / 处置 | 类 |
|---|---|---|---|---|
| `label` | `@"NSString"`，`C,D,N` | nil | ≤ 256 B UTF-8（R23，`50-IPC-HELPER.md` 第 2.6 节）；超长截断并记 degradation（C） | 深拷贝 |
| `vertexFunction` | `@"<MTLFunction>"`，`&,D,N` | nil | 非 mesh 管线必须非 nil → 否则 A（Metal 返回 nil + NSError） | 句柄 |
| `fragmentFunction` | 同上 | nil | 可以为 nil（`rasterizationEnabled == NO` 的 vertex-only 管线） | 句柄 |
| `vertexDescriptor` | `@"MTLVertexDescriptor"`，`C,D,N` | nil | 非 nil 时递归 snapshot（4.12） | 深拷贝 |
| `sampleCount` / `rasterSampleCount` | `Q`×2（同一 union，`_private+184`） | **1**（`S-METAL +0x1AD4C`） | 两个 selector 读同一字段；必须与 pass 的 attachment sample count 一致 | 标量 |
| `alphaToCoverageEnabled`（getter: `isAlphaToCoverageEnabled`） | `c` | **NO**（位域 bit 0–1 = 0） | — | 标量 |
| `alphaToOneEnabled`（getter: `isAlphaToOneEnabled`） | `c` | **NO**（bit 2–3 = 0） | 非 NO 需 `alphaToOne` feature；Lavapipe 待实测 → 记 degradation | 标量 |
| `rasterizationEnabled`（getter: `isRasterizationEnabled`） | `c` | **YES**（bit 4 = 1，`_private+224 |= 0x01FE0010`） | — | 标量 |
| `maxVertexAmplificationCount` | `Q`（内部 `I`，`_private+476`） | **1** | `1..=supports_vertex_amplification_count` 接受的最大值（`40-RUNTIME-VULKAN.md` 第 3.2 节） | 标量 |
| `colorAttachments` | `@"…Array"`，`R,D` | 非 nil 容器 | 按 R6/R7 逐下标；生效 iff `pixelFormat != Invalid` | 容器 |
| `depthAttachmentPixelFormat` | `Q`（`_private+72`） | **0 = `Invalid`**（`S-METAL +0x1AD4C`） | `Invalid` 表示无 depth；非 `Invalid` 必须是 depth 格式 → 否则 A | 标量 |
| `stencilAttachmentPixelFormat` | `Q`（`_private+80`） | **0 = `Invalid`** | 同上 | 标量 |
| `inputPrimitiveTopology` | `Q`（位域 bit 5–6） | **0 = `Unspecified`** | `{0,1,2,3}`；未知 → A | 标量 |
| `tessellationPartitionMode` | `Q`（`_private+88`） | **0 = `Pow2`** | `{0,1,2,3}` | 标量 |
| `maxTessellationFactor` | `Q`（`_private+96`） | **16** | `1..=64`；越界 → A | 标量 |
| `tessellationFactorScaleEnabled`（getter: `isTessellationFactorScaleEnabled`） | `c`（`_private+104`） | **NO** | — | 标量 |
| `tessellationFactorFormat` | `Q`（`_private+112`） | **0 = `Half`** | `{0}` | 标量 |
| `tessellationControlPointIndexType` | `Q`（`_private+120`） | **0 = `None`** | `{0,1,2}` | 标量 |
| `tessellationFactorStepFunction` | `Q`（`_private+128`） | **0 = `Constant`** | `{0,1,2,3}` | 标量 |
| `tessellationOutputWindingOrder` | `Q`（`_private+136`） | **0 = `Clockwise`** | `{0,1}` | 标量 |
| `vertexBuffers` | `@"MTLPipelineBufferDescriptorArray"`，`R,D` | 非 nil 容器（`_private+408`） | 逐下标 `0..maxVertexBuffers`，见 4.5.3 | 容器 |
| `fragmentBuffers` | 同上（`_private+416`） | 非 nil 容器 | 同上 | 容器 |
| `supportIndirectCommandBuffers` | `c`（`_private+152`） | **NO** | — | 标量 |
| `binaryArchives` | `@"NSArray"`，`C,D,N` | **nil**（`_private+480`，init 不赋值） | 每项必须解析到 BinaryArchive；上游 `BinaryArchive` 对应 `VkPipelineCache` | 深拷贝（句柄数组） |
| `vertexPreloadedLibraries` | `@"NSArray"`，`C,N`（实存 ivar） | **空 `NSArray`**（`_private+528`，init 用 `objc_alloc_init` 建） | 每项必须解析到 DynamicLibrary；非空 → B（上游拒绝链接使用） | 深拷贝 |
| `fragmentPreloadedLibraries` | 同上（`_private+536`） | 空数组 | 同上 | 深拷贝 |
| `vertexLinkedFunctions` | `@"MTLLinkedFunctions"`，`C,D,N`（`_private+496`） | **nil** | 非 nil 递归 snapshot（4.21） | 深拷贝 |
| `fragmentLinkedFunctions` | 同上（`_private+504`） | **nil** | 同上 | 深拷贝 |
| `supportAddingVertexBinaryFunctions` | `c`（`_private+576`） | **NO** | — | 标量 |
| `supportAddingFragmentBinaryFunctions` | `c`（`_private+577`） | **NO** | — | 标量 |
| `maxVertexCallStackDepth` | `Q`（`_private+560`） | **1** | `1..=maxCallStackDepth` 的 device limit | 标量 |
| `maxFragmentCallStackDepth` | `Q`（`_private+568`） | **1** | 同上 | 标量 |
| `shaderValidation` | `q`（`_private+160`） | **0 = `Default`** | `{0,1,2}`；`Enabled`(2) → C（我们没有 shader validation 层，记 degradation） | 标量 |

公开层的 6 个实存 ivar（`D-OBJC:13551`）：`_supportAddingVertexBinaryFunctions`、`_supportAddingFragmentBinaryFunctions`、`_vertexPreloadedLibraries`、`_fragmentPreloadedLibraries`、`_maxVertexCallStackDepth`、`_maxFragmentCallStackDepth`。注意**这些 ivar 与 `_private` 中的同名字段并存**，访问器走 `Internal` 的实现（读 `_private`），公开层的 ivar 在 `Internal` 对象上是死的。shim 只用 selector，不受影响。

init 中可从公开 API 观察到的其余默认值（`S-METAL +0x1AD4C`，`KNOWN`）：`sampleMask` = `0xFFFF_FFFF_FFFF_FFFF`（`_private+192`，SPI）、`sampleCoverage` = `1.0f`（`_private+200`，SPI）、`clipDistanceEnableMask` = `0xFF`（位域 bit 17–24，SPI）、`explicitVisibilityGroupID` = `0xFFFF_FFFF`（`_private+616`，SPI）、`textureWriteRoundingMode` = 0、`colorSampleCount` = 0、`postVertexDumpBufferIndex` = 0、`compilerTimeoutInSeconds` = 0、`maxAccelerationStructureTraversalDepth` = 0、`maxMeshStackCallDepth` / `maxObjectStackCallDepth` = 1、`profileControl` = nil、四组 `*GlobalConstantsTag` = 0。

#### 4.5.2 `MTLRenderPipelineColorAttachmentDescriptor`

`D-OBJC:13463`。`_private` = `MTLRenderPipelineAttachmentDescriptorPrivate`，**全部字段打包进一个 64 位位域**（`D-OBJC:13513`）：
`blendingEnabled` b2、`rgbBlendOperation` b3、`alphaBlendOperation` b3、`sourceRGBBlendFactor` b5、`sourceAlphaBlendFactor` b5、`destinationRGBBlendFactor` b5、`destinationAlphaBlendFactor` b5、`writeMask` b5、`logicOpEnabled` b1、`logicOp` b4、`pixelFormat` b22。

| 字段 | 编码 | 默认 | 域 / 处置 |
|---|---|---|---|
| `pixelFormat` | `Q` | **0 = `Invalid`** | 生效判据（R7）。非 `Invalid` 必须是 color 可渲染格式，且上游 `vk_format(pf, [Attachment, Blend?], profile)` 必须有候选 → 否则 A/B |
| `blendingEnabled`（getter: `isBlendingEnabled`） | `c` | **NO** | 位宽 2 位，但只有 0/1 有意义 |
| `sourceRGBBlendFactor` | `Q` | **1 = `One`** | `0..=17`（位宽 5 位，最大 31）；`> 17` → A |
| `destinationRGBBlendFactor` | `Q` | **0 = `Zero`** | 同上 |
| `rgbBlendOperation` | `Q` | **0 = `Add`** | `0..=4`（位宽 3 位） |
| `sourceAlphaBlendFactor` | `Q` | **1 = `One`** | 同 RGB |
| `destinationAlphaBlendFactor` | `Q` | **0 = `Zero`** | 同 RGB |
| `alphaBlendOperation` | `Q` | **0 = `Add`** | 同 RGB |
| `writeMask` | `Q` | **0xF = `All`** | 封闭 flag（R/G/B/A = 8/4/2/1）；位宽 5 位，`> 0xF` → A |

`BLOCKED`：上述默认值取自 Metal 的公开 API 契约与位域宽度，**未从 `init` 反编译确认** —— `-[MTLRenderPipelineColorAttachmentDescriptorInternal init]`（`S-METAL +0x1CFD1`）的函数体只有 `objc_msgSendSuper2` 加一次 `objc_msgSend(self, <sel@0x7FF841013B00>)`，默认值在那个被转发的 selector 里。关闭方式：解出 `0x7FF841013B00` 指向的 selector 名并反编译其实现（一次 IDA 操作）。位域的三个默认值（`sourceRGBBlendFactor=One`、`writeMask=All`、`blendingEnabled=NO`）与上游 `ColorAttachmentDescriptor::new` 的默认一致（`bridge-runtime-contract.md` 第 4.3 节已记录该一致性，该条成立）。

SPI 字段：`logicOpEnabled`（b1）与 `logicOp`（b4）无公开 `@property`，且 Vulkan 侧需 `logicOp` feature（Lavapipe 待实测）→ 非默认时 B。

#### 4.5.3 `MTLPipelineBufferDescriptor`

`D-OBJC:12668`。`_private` 只含一个 `mutability b2` 位域（`D-OBJC:12707`）。

| 字段 | 编码 | 默认 | 域 / 处置 |
|---|---|---|---|
| `mutability` | `Q` | **0 = `Default`** | `{0,1,2}`（Default / Mutable / Immutable）；`> 2` → A。`Immutable` 允许上游把该 buffer 烘进 layout；`Default` 等价于 `Mutable` | 标量 |

### 4.6 `MTLComputePipelineDescriptor`

`D-OBJC:7945`。默认值：`-[MTLComputePipelineDescriptorInternal init]`，`S-METAL +0x24FE7`。`_private` 在对象偏移 16（公开层一个 `_insertLibraries` ivar），240 字节，字段顺序见 `D-OBJC:7981`。

| 字段 | 编码 | 默认 | 域 / 处置 | 类 |
|---|---|---|---|---|
| `label` | `@"NSString"`，`C,D,N` | nil（`_private+0`） | ≤ 256 B；→ C | 深拷贝 |
| `computeFunction` | `@"<MTLFunction>"`，`&,D,N` | nil（`_private+8`） | 必须非 nil → 否则 A | 句柄 |
| `threadGroupSizeIsMultipleOfThreadExecutionWidth` | `c` | **NO**（`_private+16`，alloc0） | — | 标量 |
| `maxTotalThreadsPerThreadgroup` | `Q` | **0**（`_private+18`，**内部只有 16 位**，`S` 编码） | `0..=65535`；> 65535 → A（内部字段会截断，必须在 shim 拒绝）；再与 `maxThreadsPerThreadgroup` 取小 | 标量 |
| `stageInputDescriptor` | `@"MTLStageInputOutputDescriptor"`，`C,D,N` | nil（`_private+24`） | 非 nil 递归 snapshot（4.13） | 深拷贝 |
| `buffers` | `@"MTLPipelineBufferDescriptorArray"`，`R,D` | 非 nil 容器（`_private+48`，`S-METAL +0x24FE7` 分配） | 逐下标 `0..maxKernelBuffers` | 容器 |
| `supportIndirectCommandBuffers` | `c`（`_private+80`） | **NO** | — | 标量 |
| `insertLibraries` | `@"NSArray"`，`C,N`（与 `preloadedLibraries` 共用 `_private+64` 的 union） | **空数组** | 非空 → B | 深拷贝 |
| `preloadedLibraries` | `@"NSArray"`，`C,D,N`（同一 union） | **空数组**（`S-METAL +0x24FE7` 用 `objc_alloc_init` 建） | 非空 → B。**与 `insertLibraries` 是同一存储**：设其一会覆盖另一，snapshot 只读一次 | 深拷贝 |
| `binaryArchives` | `@"NSArray"`，`C,D,N`（`_private+56`） | nil | 同 4.5.1 | 深拷贝 |
| `linkedFunctions` | `@"MTLLinkedFunctions"`，`C,D,N`（`_private+160`） | **nil** | 递归 snapshot（4.21） | 深拷贝 |
| `supportAddingBinaryFunctions` | `c`（`_private+176`） | **NO** | — | 标量 |
| `maxCallStackDepth` | `Q`（`_private+168`） | **1** | `1..=` device limit | 标量 |
| `shaderValidation` | `q`（`_private+88`） | **0** | 同 4.5.1 | 标量 |
| `requiredThreadsPerThreadgroup` | `{?=QQQ}`（`_private+208`） | **`{0,0,0}`** | 非零时三维都必须 `>= 1`，乘积 `<= maxTotalThreadsPerThreadgroup`，checked；上游有 `RequiredThreadsProblem` → 违反时 A | 标量 |
| `forceResourceIndex` | `c`（`_private+112`） | **NO** | 见 R25 | 标量 |
| `resourceIndex` | `Q`（`_private+120`） | **0** | 见 R25 | 标量 |
| `globalConstantsTag` | `Q`（`_private+128`） | **0** | 非 0 → B（Apple 私有全局常量机制） | 标量 |

### 4.7 `MTLTileRenderPipelineDescriptor` 与其 color attachment

`D-OBJC:15214`。默认值：`-[MTLTileRenderPipelineDescriptorInternal init]`，`S-METAL +0x362B3`。`_private` 在对象偏移 56，200 字节（`D-OBJC:15255`）。

| 字段 | 编码 | 默认 | 域 / 处置 | 类 |
|---|---|---|---|---|
| `label` | `@"NSString"`，`C,D,N`（`_private+16`） | nil | → C | 深拷贝 |
| `tileFunction` | `@"<MTLFunction>"`，`&,D,N`（`_private+24`） | nil | 必须非 nil → 否则 A | 句柄 |
| `rasterSampleCount` | `Q`（`_private+8`） | **1**（`S-METAL +0x362B3`） | 同 4.5.1 | 标量 |
| `colorAttachments` | `@"MTLTileRenderPipelineColorAttachmentDescriptorArray"`，`R,D`（`_private+0`） | 非 nil 容器 | 逐下标，每项只有 `pixelFormat`（`D-OBJC:15156`） | 容器 |
| `threadgroupSizeMatchesTileSize` | `c`（`_private+32`，编码 `B`） | **NO** | — | 标量 |
| `tileBuffers` | `@"MTLPipelineBufferDescriptorArray"`，`R,D`（`_private+56`） | 非 nil 容器 | 逐下标 | 容器 |
| `maxTotalThreadsPerThreadgroup` | `Q`（`_private+64`，**内部 16 位**） | **0** | 同 4.6 | 标量 |
| `binaryArchives` | `@"NSArray"`，`C,D,N`（`_private+88`） | nil | 同 4.5.1 | 深拷贝 |
| `preloadedLibraries` | `@"NSArray"`，`C,N`（`_private+104`） | **空数组** | 非空 → B | 深拷贝 |
| `linkedFunctions` | `@"MTLLinkedFunctions"`，`C,D,N`（`_private+96`） | **nil** | 4.21 | 深拷贝 |
| `supportAddingBinaryFunctions` | `c`（`_private+120`） | **NO** | — | 标量 |
| `maxCallStackDepth` | `Q`（`_private+112`） | **1** | — | 标量 |
| `shaderValidation` | `q`（`_private+152`） | **0** | — | 标量 |
| `requiredThreadsPerThreadgroup` | `{?=QQQ}`（`_private+168`） | **`{0,0,0}`** | 同 4.6 | 标量 |

**整类处置**：tile shading（imageblock + tile memory）是 Apple GPU 的架构特性，Vulkan 无对应形式。**全类 → B**：`newRenderPipelineStateWithTileDescriptor:…` 返回 `Unsupported`，`supportsFamily:` 对 Apple 系 family 已经是 false。本节仍给全量字段，理由是 snapshot 代码必须能把 descriptor 读完才能在错误里说清"缺什么"（第 3.6 节 B 档要求）。

### 4.8 `MTLMeshRenderPipelineDescriptor`

`D-OBJC:12257`，29 个 `@property`。默认值：`-[MTLMeshRenderPipelineDescriptor init]`（`S-METAL +0x2BFB0`）—— 注意**本类没有 `Internal` 子类**，`_private` 直接在公开类上（`D-OBJC:12257`），且 `init` 把默认值设置转发给另一个 selector（`0x7FF8410137E0`），因此本表的默认值标 `BLOCKED`，关闭方式与 4.5.2 相同。

| 字段 | 编码 | 默认 | 域 / 处置 | 类 |
|---|---|---|---|---|
| `label` | `@"NSString"`，`C,N` | nil | → C | 深拷贝 |
| `objectFunction` | `@"<MTLFunction>"`，`&,N` | nil | 可 nil（mesh-only 管线） | 句柄 |
| `meshFunction` | 同上 | nil | 必须非 nil → 否则 A | 句柄 |
| `fragmentFunction` | 同上 | nil | 可 nil | 句柄 |
| `maxTotalThreadsPerObjectThreadgroup` | `Q` | 0 | 同 4.6 | 标量 |
| `maxTotalThreadsPerMeshThreadgroup` | `Q` | 0 | 同上 | 标量 |
| `objectThreadgroupSizeIsMultipleOfThreadExecutionWidth` | `c` | NO | — | 标量 |
| `meshThreadgroupSizeIsMultipleOfThreadExecutionWidth` | `c` | NO | — | 标量 |
| `payloadMemoryLength` | `Q` | 0 | `<= maxThreadgroupMemoryLength` | 标量 |
| `maxTotalThreadgroupsPerMeshGrid` | `Q` | 0 | checked | 标量 |
| `objectBuffers` / `meshBuffers` / `fragmentBuffers` | `@"MTLPipelineBufferDescriptorArray"`，`R` ×3 | 非 nil 容器 | 逐下标 | 容器 |
| `rasterSampleCount` | `Q` | 1 | 同 4.5.1 | 标量 |
| `alphaToCoverageEnabled`（getter: `isAlphaToCoverageEnabled`） | `c` | NO | — | 标量 |
| `alphaToOneEnabled`（getter: `isAlphaToOneEnabled`） | `c` | NO | — | 标量 |
| `rasterizationEnabled`（getter: `isRasterizationEnabled`） | `c` | YES | — | 标量 |
| `maxVertexAmplificationCount` | `Q`（内部位域 b4） | 1 | `1..=15`（位宽 4 位）→ 更大值 A | 标量 |
| `colorAttachments` | `@"MTLRenderPipelineColorAttachmentDescriptorArray"`，`R` | 非 nil 容器 | 同 4.5.2 | 容器 |
| `depthAttachmentPixelFormat` / `stencilAttachmentPixelFormat` | `Q`×2 | `Invalid` | 同 4.5.1 | 标量 |
| `supportIndirectCommandBuffers` | `c`（位域） | NO | — | 标量 |
| `binaryArchives` | `@"NSArray"`，`C,N` | nil | 同 4.5.1 | 深拷贝 |
| `objectLinkedFunctions` / `meshLinkedFunctions` / `fragmentLinkedFunctions` | `@"MTLLinkedFunctions"`，`C,N` ×3 | nil | 4.21 | 深拷贝 |
| `shaderValidation` | `q` | 0 | — | 标量 |
| `requiredThreadsPerObjectThreadgroup` | `{?=QQQ}` | `{0,0,0}` | 同 4.6 | 标量 |
| `requiredThreadsPerMeshThreadgroup` | `{?=QQQ}` | `{0,0,0}` | 同上 | 标量 |

**整类处置**：上游**不为 mesh 管线产生 `PipelineRecord`**（`40-RUNTIME-VULKAN.md` 第 6.6 节的 `warm` 安全性质），说明上游对 mesh 的支持不完整。Vulkan 侧需 `VK_EXT_mesh_shader`，Lavapipe 未声明 → **全类 B**，处置同 4.7。

### 4.9 `MTLRenderPipelineFunctionsDescriptor`（SPI）

`D-OBJC:13858`。用于 `newRenderPipelineStateWithDescriptor:additionalBinaryFunctions:…` 系。

| 字段 | 编码 | 默认 | 域 / 处置 | 类 |
|---|---|---|---|---|
| `vertexAdditionalBinaryFunctions` | `@"NSArray"`，`C,N` | nil | 每项解析到 Function | 深拷贝 |
| `fragmentAdditionalBinaryFunctions` | 同上 | nil | 同上 | 深拷贝 |
| `tileAdditionalBinaryFunctions` | 同上 | nil | 同上（tile → B） | 深拷贝 |
| `objectAdditionalBinaryFunctions` | 同上 | nil | 同上（mesh → B） | 深拷贝 |
| `meshAdditionalBinaryFunctions` | 同上 | nil | 同上 | 深拷贝 |
| `vertexAdditionalBinaryFunctionResourceIndices` | `^Q` | `NULL` | **裸 `NSUInteger*`，长度由对应数组的 `count` 决定。必须在 ObjC 方法返回前复制 `count * 8` 字节**，并 checked 乘法；每个值过 R25 的 `< 16384` | 深拷贝（原始内存） |
| `fragmentAdditionalBinaryFunctionResourceIndices` | `^Q` | `NULL` | 同上 | 深拷贝 |
| `tileAdditionalBinaryFunctionResourceIndices` | `^Q` | `NULL` | 同上 | 深拷贝 |
| `objectAdditionalBinaryFunctionResourceIndices` | `^Q` | `NULL` | 同上 | 深拷贝 |
| `meshAdditionalBinaryFunctionResourceIndices` | `^Q` | `NULL` | 同上 | 深拷贝 |

> **R27**：五个 `^Q` 字段是本文件里唯一的"裸指针 + 外部长度"输入。长度只能来自同名数组的 `count`，不得来自客户端的另一个字段。若数组为 nil 而指针非 `NULL`，直接拒绝（A）—— 没有可信长度。

上游对应：`RenderPipelineFunctionsDescriptor`、`BinaryFunctionProblem`、`BinaryFunctionStage`（`40-RUNTIME-VULKAN.md` 第 2.4 节），因此这一族**有上游落点**，不是 gap。

### 4.10 `MTLDepthStencilDescriptor` + `MTLStencilDescriptor`

`D-OBJC:8317` / `D-OBJC:14512`。默认值：`S-METAL +0x205C6`（depth-stencil）、`S-METAL +0x206BB`（stencil）。

`MTLDepthStencilDescriptorPrivate` 在对象偏移 8：`frontFaceStencil`(+0) `backFaceStencil`(+8) `depthCompareFunction`(+16) `depthWriteEnabled`(+24) `label`(+32) `resourceIndex`(+40)。

| 字段 | 编码 | 默认 | 域 / 处置 | 类 |
|---|---|---|---|---|
| `depthCompareFunction` | `Q` | **7 = `Always`**（`S-METAL +0x205C6`） | `0..=7`；`> 7` → A | 标量 |
| `depthWriteEnabled`（getter: `isDepthWriteEnabled`） | `c` | **NO** | — | 标量 |
| `frontFaceStencil` | `@"MTLStencilDescriptor"`，`C,D,N` | **nil，首次 get 时懒创建**（`S-METAL +0x20BD6`，**非原子**） | 递归 snapshot；读之前必须判断 `stencilAttachmentPixelFormat != Invalid`，避免无谓的懒创建 | 深拷贝 |
| `backFaceStencil` | 同上 | 同上 | 同上 | 深拷贝 |
| `label` | `@"NSString"`，`C,D,N` | nil | → C | 深拷贝 |
| `resourceIndex` | `Q` | **0** | 见 R25。注意本类**没有** `forceResourceIndex`，因此 `resourceIndex != 0` 即视为客户端要求 pin | 标量 |
| `depthStencilPrivate` | `r^{MTLDepthStencilDescriptorPrivate=@@Qc@Q}`，`R,D` | — | **公开层直接导出了 `_private` 的 const 指针**。shim **不得使用它**（布局是版本相关的，且这是我们自己要仿的类，返回它意味着暴露我们自己的内部结构）。若客户端调用它，返回指向 snapshot 内一块布局兼容的只读区域 —— `BLOCKED`：是否有客户端真的调用它未实测，关闭方式是 guest trace |

`MTLStencilDescriptorPrivate` 在对象偏移 8：`stencilCompareFunction`(+0) `stencilFailureOperation`(+8) `depthFailureOperation`(+16) `depthStencilPassOperation`(+24) `readMask`(+32,`I`) `writeMask`(+36,`I`)。

| 字段 | 编码 | 默认 | 域 / 处置 |
|---|---|---|---|
| `stencilCompareFunction` | `Q` | **7 = `Always`**（`S-METAL +0x206BB`） | `0..=7` |
| `stencilFailureOperation` | `Q` | **0 = `Keep`** | `0..=7` |
| `depthFailureOperation` | `Q` | **0 = `Keep`** | `0..=7` |
| `depthStencilPassOperation` | `Q` | **0 = `Keep`** | `0..=7` |
| `readMask` | `I` | **0xFFFFFFFF**（`_private+32..39` 被写 `-1`） | `uint32` 全域 |
| `writeMask` | `I` | **0xFFFFFFFF** | 同上 |
| `stencilPrivate` | `r^{MTLStencilDescriptorPrivate=QQQQII}`，`R,D` | — | 同 `depthStencilPrivate` 的处置 |

### 4.11 `MTLSamplerDescriptor`

`D-OBJC:14237`。默认值：`-[MTLSamplerDescriptorInternal init]`，`S-METAL +0x23728`。

`MTLSamplerDescriptorPrivate` 在对象偏移 16，**64 字节，前 4 字节是全部窄字段的位域**（`D-OBJC:14277`）：
bit 0–1 `minFilter`、2–3 `magFilter`、4–5 `mipFilter`、6–8 `sAddressMode`、9–11 `tAddressMode`、12–14 `rAddressMode`、15 `normalizedCoords`、16–17 `borderColor`、18 `lodAverage`、19–21 `compareFunction`、22 `supportArgumentBuffers`、23–24 `reductionMode`、25 `forceResourceIndex`、26 `forceSeamsOnCubemapFiltering`。
其后：`lodMinClamp`(+4,`f`) `lodMaxClamp`(+8,`f`) `lodBias`(+12,`f`) `maxAnisotropy`(+16,`Q`) `label`(+24) `resourceIndex`(+32) `customBorderColorValue`(+40,`[4]I`) `pixelFormat`(+56,`Q`)。

`init` 把位域置为 `(old & 0xF8000000) | 0x8000`（`S-METAL +0x23728`），即**只有 bit 15 置位**。

| 字段 | 编码 | 默认 | 域 / 处置 | 类 |
|---|---|---|---|---|
| `minFilter` | `Q` | **0 = `Nearest`** | `{0,1}`（位宽 2）；`> 1` → A | 标量 |
| `magFilter` | `Q` | **0 = `Nearest`** | 同上 | 标量 |
| `mipFilter` | `Q` | **0 = `NotMipmapped`** | `{0,1,2}` | 标量 |
| `sAddressMode` | `Q` | **0 = `ClampToEdge`** | `{0,1,2,3,4,5}`（位宽 3）；`ClampToBorderColor`(5) 需 `VK_EXT_custom_border_color`（Lavapipe 有） | 标量 |
| `tAddressMode` | `Q` | **0** | 同上 | 标量 |
| `rAddressMode` | `Q` | **0** | 同上 | 标量 |
| `normalizedCoordinates` | `c` | **YES**（bit 15 = 1） | `NO` 时要求 `mipFilter == NotMipmapped`、`arrayLength == 1`、address mode ∈ `{ClampToEdge, ClampToZero}` → 否则 A（Metal 行为） | 标量 |
| `borderColor` | `Q` | **0 = `TransparentBlack`** | `{0,1,2}`（位宽 2）；上游有 `sampler_border_color`（第 2.4 节）；需 `VK_EXT_custom_border_color` | 标量 |
| `maxAnisotropy` | `Q` | **1**（`_private+16`） | `1..=16`；`0` 或 `> 16` → A（Metal assert） | 标量 |
| `lodMinClamp` | `f` | **0.0f**（`_private+4`） | 有限；见 R19/R20 | 标量 |
| `lodMaxClamp` | `f` | **`FLT_MAX`** = `0x7F7FFFFF`（`_private+8`，init 写 `0x7F7FFFFF00000000` 覆盖 `+4..+11`） | 同上 | 标量 |
| `lodBias` | `f` | **0.0f**（`_private+12`） | 有限；Metal 的 SPI；Vulkan 侧是 `mipLodBias` | 标量 |
| `lodAverage` | `c` | **NO**（bit 18） | 非 NO → B（Apple 的 LOD 平均无 Vulkan 形式） | 标量 |
| `compareFunction` | `Q` | **0 = `Never`**（bit 19–21） | `0..=7`（位宽 3 → 全域可表示） | 标量 |
| `reductionMode` | `Q` | **0**（bit 23–24） | `{0,1,2}`；非 0 需 `VK_EXT_sampler_filter_minmax`，Lavapipe 待实测 → B | 标量 |
| `supportArgumentBuffers` | `c` | **NO**（bit 22） | — | 标量 |
| `pixelFormat` | `Q` | **0 = `Invalid`**（`_private+56`） | SPI：给 border color 与 YCbCr 转换用。非 `Invalid` 时必须与被采样纹理格式一致 | 标量 |
| `label` | `@"NSString"`，`C,D,N` | nil（`_private+24`） | → C | 深拷贝 |
| `forceResourceIndex` | `c` | **NO**（bit 25） | 见 R25 | 标量 |
| `resourceIndex` | `Q` | **0**（`_private+32`） | 见 R25 | 标量 |

SPI：`customBorderColorValue`（`[4]I`，`_private+40`，init 清零）与 `forceSeamsOnCubemapFiltering`（bit 26）。前者非零时走 `VK_EXT_custom_border_color` 的 `customBorderColor`；后者非默认 → B。

**关键上限**：上游有 `Error::SamplerLimit`（`40-RUNTIME-VULKAN.md` 第 2.9 节）。Vulkan 的 `maxSamplerAllocationCount` 远小于 Metal 的实际用量，`60-CAPABILITY-MATRIX.md` 必须登记 Lavapipe 的实测值；sampler 的创建路径必须把这个错误转成 `OutOfMemory` 而不是 `Unsupported`。

### 4.12 `MTLVertexDescriptor` + attribute / layout

`D-OBJC:15511` / `15367` / `15449`。默认值：`S-METAL +0x1B0CB`（vertex descriptor）、`S-METAL +0x1B2D6`（buffer layout）。

`MTLVertexDescriptor` 自身只有两个只读容器，`init` 各分配一个（`S-METAL +0x1B0CB`）：

| 字段 | 编码 | 默认 | 处置 |
|---|---|---|---|
| `layouts` | `@"MTLVertexBufferLayoutDescriptorArray"`，`R,D` | 非 nil 容器 | 按 R6 逐下标 `0..maxVertexBuffers` |
| `attributes` | `@"MTLVertexAttributeDescriptorArray"`，`R,D` | 非 nil 容器 | 逐下标 `0..maxVertexAttributes`（Metal 固定 31） |

`MTLVertexAttributeDescriptor`（`_private` 为三个实存 ivar：`_vertexFormat` `_offset` `_bufferIndex`）：

| 字段 | 编码 | 默认 | 域 / 处置 |
|---|---|---|---|
| `format` | `Q`（ivar 名 `_vertexFormat`） | **0 = `Invalid`**（alloc0） | 生效判据（R7）。`MTLVertexFormat` 的已知取值；上游必须有对应 `VkFormat` → 无则 B |
| `offset` | `Q` | **0** | `< layouts[bufferIndex].stride`（若 stride != 0），checked；且必须满足该格式的对齐 → 否则 A |
| `bufferIndex` | `Q` | **0** | `< maxVertexBuffers`；越界 → A | 

`MTLVertexBufferLayoutDescriptor`（ivar：`_stride` `_stepFunction` `_instanceStepRate`）：

| 字段 | 编码 | 默认 | 域 / 处置 |
|---|---|---|---|
| `stride` | `Q` | **0**（`S-METAL +0x1B2D6`） | 生效判据（R7）。`0` = 该槽位未用；非 0 时必须 `<= maxVertexBufferStride`（通常 2048）且 4 字节对齐（Metal assert） |
| `stepFunction` | `Q` | **1 = `PerVertex`**（`S-METAL +0x1B2D6`） | `{0,1,2,3,4,5}`；`PerPatch`/`PerPatchControlPoint` 需 tessellation → B；`Constant`(0) 要求 `stepRate == 0`（Metal assert） |
| `stepRate` | `Q`（ivar 名 `_instanceStepRate`） | **1**（`S-METAL +0x1B2D6`） | `PerVertex`/`PerInstance` 时必须为 1（Vulkan 无 divisor，除非 `VK_EXT_vertex_attribute_divisor`，Lavapipe 待实测）→ 其他值 B |

> 注意属性名与 ivar 名不一致（`format` ↔ `_vertexFormat`、`stepRate` ↔ `_instanceStepRate`）。这不影响 selector，但读 `D-OBJC` 时容易对错字段。

### 4.13 `MTLStageInputOutputDescriptor` + `MTLAttributeDescriptor` + `MTLBufferLayoutDescriptor`

`D-OBJC:14462` / `6329` / `7157`。默认值：`S-METAL +0x3E6C1`。

这三个类与 4.12 的三个**字段完全同构、类不同**（`D-OBJC` 中 `MTLAttributeDescriptorInternal` 与 `MTLVertexAttributeDescriptorInternal` 的 ivar 列表逐字相同，`MTLBufferLayoutDescriptorInternal` 与 `MTLVertexBufferLayoutDescriptorInternal` 同理）。用途是 compute 的 stage-in：

| 字段 | 编码 | 默认 | 域 / 处置 |
|---|---|---|---|
| `layouts` | `@"MTLBufferLayoutDescriptorArray"`，`R,D` | 非 nil 容器（`S-METAL +0x3E6C1` 分配） | 逐下标 |
| `attributes` | `@"MTLAttributeDescriptorArray"`，`R,D` | 非 nil 容器 | 逐下标 |
| `indexType` | `Q` | **0 = `UInt16`**（alloc0） | `{0,1}` |
| `indexBufferIndex` | `Q` | **0** | `< maxKernelBuffers` |

`MTLAttributeDescriptor` 的 `format` 是 `MTLAttributeFormat`（与 `MTLVertexFormat` 取值表相同），`MTLBufferLayoutDescriptor` 的 `stepFunction` 是 `MTLStepFunction`（多两个 `ThreadPositionInGrid*` 取值）。两者的校验规则同 4.12，但 **stage-in 的整体处置是 B**：Vulkan 的 compute 没有顶点抓取硬件，上游需要把 stage-in 翻译成 shader 内的手工抓取。`BLOCKED`：上游是否实现了 compute stage-in 未核，关闭方式是读 `metal2vulkan-runtime` 的 `ComputePipelineDescriptor` rustdoc。

### 4.14 `MTLHeapDescriptor`

`D-OBJC:10315`。默认值：`-[MTLHeapDescriptorInternal init]`，`S-METAL +0x1580D9`。

`_private` 是一个 **`malloc_type_calloc(1, 0x58)` 得到的堆指针**（88 字节，编码 `^{MTLHeapDescriptorPrivate=QQQqcqQQQQq}`，`D-OBJC:10343`）。字段映射由 getter 反编译确定（`KNOWN`）：

| `_private` 偏移 | getter | RVA | 默认 |
|---:|---|---|---|
| +0 | `size` | `S-METAL +0x158347` | **0** |
| +8 | `storageMode` | `S-METAL +0x15838C` | **2 = `Private`** |
| +16 | `cpuCacheMode` | `S-METAL +0x158361` | **0 = `DefaultCache`** |
| +24 | `sparsePageSize` | `S-METAL +0x1583BE` | **101 = `MTLSparsePageSize16`** |
| +32 | （未识别 `c`） | — | **1** |
| +40 | `type` | `S-METAL +0x1583F5` | **0 = `Automatic`** |
| +48 | `resourceOptions` | `S-METAL +0x15872E` | **32 = `MTLResourceStorageModePrivate`** |
| +48 bit 8–9 | `hazardTrackingMode` | `S-METAL +0x1586FB`（`(var6 >> 8) & 3`） | **0 = `Default`** |
| +80 | `maxCompatiblePlacementSparsePageSize` | `S-METAL +0x158411` | **0** |

`BLOCKED`：`_private+32`（`c`，init 写 1）与 `+56`/`+64`/`+72` 三个 `Q` 未识别。关闭方式：枚举 `MTLHeapDescriptorInternal` 的全部 getter（`D-OBJC:10343` 的方法列表）并逐个反编译。本文不为它们编造名字。

| 字段 | 编码 | 默认 | 域 / 处置 | 类 |
|---|---|---|---|---|
| `size` | `Q` | **0** | `1..=` 协议上限 ∩ `DeviceProperties` 可用内存；0 → A | 标量 |
| `storageMode` | `Q` | **2 = `Private`** | `{0,1,2}`；`Memoryless` → B | 标量 |
| `cpuCacheMode` | `Q` | **0** | `{0,1}` | 标量 |
| `hazardTrackingMode` | `Q` | **0** | `{0,1,2}`；→ C（上游按 barrier 策略处理） | 标量 |
| `resourceOptions` | `Q` | **32** | 同 4.1；与前三者互为别名，setter 互相覆盖 → snapshot 读 `resourceOptions` 一次即够，但要按 R24 同时保存三个分量的声明值 | 标量 |
| `type` | `q` | **0 = `Automatic`** | `{0,1}`（Automatic / Placement）；上游有 `HeapType`（第 2.3 节） | 标量 |
| `sparsePageSize` | `q` | **101** | `{101,102,103}`；**仅在 `type == Placement` 且 sparse 可用时有意义**，否则 → C | 标量 |
| `maxCompatiblePlacementSparsePageSize` | `q` | **0** | 同上 → C | 标量 |

### 4.15 `MTLIndirectCommandBufferDescriptor`

`D-OBJC:11783`，29 个 `@property`。**本类没有 `Internal` 子类**，`_private` 名为 `_state`（`MTLIndirectCommandBufferDescriptorState`，`D-OBJC:11783`）直接在公开类上。默认值：`-[MTLIndirectCommandBufferDescriptor init]`，`S-METAL +0x124D8A`（`BLOCKED`：未反编译；下表默认值按 `calloc` 零填充与 Metal 的公开契约记为 `INFERRED`，关闭方式是反编译该 init）。

`_state` 字段顺序（`KNOWN`，`D-OBJC:11783`）：
`commandTypes`(Q) `inheritPipelineState`(c) `inheritBuffers`(c) `maxVertexBufferBindCount`(Q) `maxFragmentBufferBindCount`(Q) `maxKernelBufferBindCount`(Q) `maxKernelThreadgroupMemoryBindCount`(Q) `maxObjectBufferBindCount`(Q) `maxMeshBufferBindCount`(Q) `maxObjectThreadgroupMemoryBindCount`(Q) `supportRayTracing`(c) `supportDynamicAttributeStride`(c) **`maxScissorRectCount`(C)** **`maxViewportCount`(C)** `inheritDepthStencilState`(c) `inheritDepthBias`(c) `inheritStencilReferenceValues`(c) `inheritDepthClipMode`(c) `inheritCullMode`(c) `inheritFrontFacingWinding`(c) `inheritTriangleFillMode`(c) `inheritDepthTestBounds`(c) `inheritScissorRects`(c) `inheritViewports`(c) `inheritBlendColor`(c) `allowOverrideRenderStates`(q) `resourceIndex`(Q) **`maxToolsDispatchBindings`(I)** `supportColorAttachmentMapping`(c)。

| 字段 | 编码 | 默认 | 域 / 处置 |
|---|---|---|---|
| `commandTypes` | `Q` | **0** | 封闭 flag（`MTLIndirectCommandType`）；未知位 → A；**`0` → A**（一个什么命令都不许录的 ICB 没有意义，Metal 自己 assert） |
| `maxVertexBufferBindCount` | `Q` | **0** | `0..=maxVertexBuffers` |
| `maxFragmentBufferBindCount` | `Q` | **0** | `0..=maxFragmentBuffers` |
| `maxKernelBufferBindCount` | `Q` | **0** | `0..=maxKernelBuffers` |
| `maxKernelThreadgroupMemoryBindCount` | `Q` | **0** | `0..=maxThreadgroupMemoryBindings` |
| `maxObjectBufferBindCount` / `maxMeshBufferBindCount` / `maxObjectThreadgroupMemoryBindCount` | `Q`×3 | **0** | mesh 相关，非 0 → B |
| `maxScissorRectCount` | `Q`（**内部只有 8 位**） | **0** | `0..=255`；`> 255` → A（内部会截断） |
| `maxViewportCount` | `Q`（**内部 8 位**） | **0** | `0..=min(255, DeviceProperties::max_viewports)` |
| `maxToolsDispatchBindings` | `Q`（**内部 32 位**） | **0** | `0..=u32::MAX`；→ C（调试工具用） |
| `inheritPipelineState` | `c` | **NO** | — |
| `inheritBuffers` | `c` | **NO** | — |
| `inheritDepthStencilState` / `inheritDepthBias` / `inheritStencilReferenceValues` / `inheritDepthClipMode` / `inheritCullMode` / `inheritFrontFacingWinding` / `inheritTriangleFillMode` / `inheritDepthTestBounds` / `inheritScissorRects` / `inheritViewports` / `inheritBlendColor` | `c`×11 | **NO** | 这 11 个是 SPI；每一项为 YES 表示该状态由外层 encoder 继承而非 ICB 自带。上游有 `IndirectCommandBufferDescriptor` 与 `IndirectCommandBufferProblem`（第 2.6 节）→ 逐项映射，上游不认的项 B |
| `allowOverrideRenderStates` | `q` | **0** | SPI；`{0,1,…}` 未知 → A |
| `supportRayTracing` | `c` | **NO** | 非 NO → B |
| `supportDynamicAttributeStride` | `c` | **NO** | 非 NO → B（上游有 `AddressModeMap` 但不是这个） |
| `supportColorAttachmentMapping` | `c` | **NO** | 非 NO → B |
| `resourceIndex` | `Q` | **0** | 见 R25。本类**无** `forceResourceIndex` |

### 4.16 `MTLArgumentDescriptor` / `MTLIndirectArgumentDescriptor`（SPI）

`D-OBJC:6185` / `11734`。默认值：`-[MTLArgumentDescriptorInternal init]`，`S-METAL +0x1116C9`。`_private` = `MTLArgumentDescriptorPrivate` 在对象偏移 8，六个 `Q` 顺序与属性声明一致。

| 字段 | 编码 | 默认 | 域 / 处置 |
|---|---|---|---|
| `dataType` | `Q` | **0 = `None`**（`_private+0`） | `MTLDataType` 的已知取值；`None` → A（必须指定类型） |
| `index` | `Q` | **0**（`_private+8`） | `0..=` argument buffer 的槽位上限，checked |
| `arrayLength` | `Q` | **0**（`_private+16`） | `0` = 非数组；非 0 时 `index + arrayLength` 不得溢出槽位上限，checked |
| `access` | `Q` | **0 = `ReadOnly`**（`_private+24`） | `{0,1,2,3}`（ReadOnly/ReadWrite/WriteOnly/…）；未知 → A |
| `textureType` | `Q` | **2 = `Type2D`**（`_private+32`，`S-METAL +0x1116C9`） | 同 4.1；仅当 `dataType == Texture` 时有意义 |
| `constantBlockAlignment` | `Q` | **0**（`_private+40`） | `0` 或 2 的幂；非幂 → A |

`MTLIndirectArgumentDescriptor` 重声明了同样 6 个属性（`D-OBJC:11734`），`MTLIndirectArgumentDescriptorInternal` 的 init 在 `S-METAL +0x1107EA`。两者 snapshot 结构相同。

**上游状况**：`40-RUNTIME-VULKAN.md` 第 2.6 节只列出 `ArgumentEncoder` 与 `ArgumentEncoderProblem`，**没有 argument descriptor 的值类型**。因此 `newArgumentEncoderWithArguments:` 的 descriptor 数组需要本项目自己转成上游 `ArgumentEncoder` 的构造参数。`BLOCKED`：上游 `ArgumentEncoder` 的构造签名未核，关闭方式是 `cargo doc -p metal2vulkan-runtime`。

### 4.17 `MTLBinaryArchiveDescriptor`

`D-OBJC:6718`。默认值：`-[MTLBinaryArchiveDescriptor init]`，`S-METAL +0xAA984`（`BLOCKED`：未反编译；下表按 ivar 零填充记 `INFERRED`）。ivar：`_url` `_options`（`D-OBJC:6718`）。

| 字段 | 编码 | 默认 | 域 / 处置 | 类 |
|---|---|---|---|---|
| `url` | `@"NSURL"`，`C,N` | nil | **客户端给的任意路径。必须拒绝（见 R28）** | 深拷贝（受限） |
| `options` | `Q` | 0 | 封闭 flag；未知位 → A | 标量 |
| `writingOptions` | `Q` | 0 | SPI；同上 | 标量 |

> **R28**：`url` 是本文件中**唯一让客户端指定文件系统路径的 descriptor 字段**（与之同类的还有 `MTLCaptureDescriptor.outputURL`、`MTLDynamicLibraryDescriptorSPI.url`，共三处）。处置：
>
> 1. **不得把客户端路径传给 helper 或任何文件 API。** 理由见 `50-IPC-HELPER.md` 第 7 节。
> 2. `newBinaryArchiveWithDescriptor:` 在 `url == nil`（内存归档）时正常工作，映射到上游 `BinaryArchive`（`VkPipelineCache`）。
> 3. `url != nil` 时：读/写都改到**本项目自己的缓存目录**下一个由 `url` 的内容哈希命名的文件，并在返回的 `NSError` 的 `userInfo` 里说明路径被重定向；或者直接返回 `Unsupported`。**选前者**，因为 `serializeToURL:error:` 是 Xcode 工具链的常规用法，直接拒绝会让客户端认为 binary archive 完全不可用。`INFERRED`。
> 4. 三处的实现必须共用同一个重定向函数。

### 4.18 `MTLCaptureDescriptor`

`D-OBJC:7284`。默认值：`-[MTLCaptureDescriptor init]`，`S-METAL +0x132400`（`BLOCKED`，同 4.17）。ivar：`_captureObject` `_destination` `_outputURL`。

| 字段 | 编码 | 默认 | 域 / 处置 | 类 |
|---|---|---|---|---|
| `captureObject` | `@`（无类型约束！），`&,N` | nil | **可以是 `id<MTLDevice>`、`id<MTLCommandQueue>` 或 `MTLCaptureScope`**。shim 必须用 `isKindOfClass:` / `conformsToProtocol:` 三选一判定，不得假定类型 → 不匹配时 A | 句柄 |
| `destination` | `q` | 0 = `DeveloperTools` | `{0,1}`；`GPUTraceDocument`(1) 要求 `outputURL` 非 nil | 标量 |
| `outputURL` | `@"NSURL"`，`C,N` | nil | 见 R28 | 深拷贝（受限） |

**整类处置**：GPU frame capture 需要一个完整的命令流序列化器与 Xcode 侧的 reader。上游无对应（`40-RUNTIME-VULKAN.md` 第 2 节无 capture 类型）。**全类 B**：`MTLCaptureManager` 的 `supportsDestination:` 对两个取值都返回 NO，`startCaptureWithDescriptor:error:` 返回 `Unsupported`。
`INFERRED`：这是安全的答案，因为 `MTLCaptureManager` 的公开契约允许实现不支持任何 destination。

### 4.19 `MTLCounterSampleBufferDescriptor`

`D-OBJC:8168`。`MTLCounterSampleBufferDescriptorInternal` 的 ivar（`D-OBJC:8184`）：`_counterSet` `_storageMode` `_label` `_sampleCount`。

| 字段 | 编码 | 默认 | 域 / 处置 | 类 |
|---|---|---|---|---|
| `counterSet` | `@"<MTLCounterSet>"`，`&,D` | nil | 必须非 nil 且是本 device 的 counter set → 否则 A | 句柄 |
| `label` | `@"NSString"`，`C,D` | nil | → C | 深拷贝 |
| `storageMode` | `Q`，`D` | 0 | 必须 ∈ `{Shared, Private}`（Metal 要求），`Managed` → A | 标量 |
| `sampleCount` | `Q`，`D` | 0 | `1..=` 协议上限；0 → A | 标量 |

**整类处置**：本项目**不发布任何 counter set**（`device.counterSets` 返回空数组），因此 `counterSet` 永远解析不到对象，`newCounterSampleBufferWithDescriptor:error:` 恒返回 `Unsupported`。`INFERRED`，理由：Vulkan 的查询池不能表达 Apple 的 counter set 模型，而 `MTLDevice.counterSets` 返回空数组是 Metal 允许的合法答案（没有性能计数器的设备就是这样）。连带后果：第 4.4.4 与 4.29.2 的全部 sample buffer attachment 的 `sampleBuffer` 永远是 nil。

### 4.20 Function descriptor 系

#### `MTLFunctionDescriptor`

`D-OBJC:9495`。默认值：`-[MTLFunctionDescriptor init]`，`S-METAL +0x1E4FC0`（`BLOCKED`）。

| 字段 | 编码 | 默认 | 域 / 处置 | 类 |
|---|---|---|---|---|
| `name` | `@"NSString"`，`C,D,N` | nil | 必须非 nil；**UTF-8 化后 ≤ 1024 B**；必须能在目标 library 中找到同名 function → 否则 `nil + NSError` | 深拷贝 |
| `specializedName` | `@"NSString"`，`C,D,N` | nil | 同长度限制；只影响反射里的名字 → C | 深拷贝 |
| `constantValues` | `@"MTLFunctionConstantValues"`，`C,D,N` | nil | 递归 snapshot（4.29.4） | 深拷贝 |
| `options` | `Q` | 0 | 封闭 flag（`MTLFunctionOptions`：`CompileToBinary`、`StoreFunctionInMetalScript`…）；未知位 → A | 标量 |
| `binaryArchives` | `@"NSArray"`，`C,N` | nil | 同 4.5.1 | 深拷贝 |

上游对应：`FunctionDescriptor`（`40-RUNTIME-VULKAN.md` 第 2.4 节），以及 `Function::function_descriptor` 与 `metal2vulkan::pipeline::StageSource::Function`。**有落点。**

#### `MTLIntersectionFunctionDescriptor`

`D-OBJC:12058`，字段与基类相同（无追加）。整类 B（ray tracing，见 4.24）。

#### `MTLStitchedLibraryDescriptor` / `MTLStitchedLibraryDescriptorSPI`

`D-OBJC:14561` / `14591`。ivar：`_functionGraphs` `_functions` `_binaryArchives` `_options`。

| 字段 | 编码 | 默认 | 域 / 处置 | 类 |
|---|---|---|---|---|
| `functionGraphs` | `@"NSArray"`，`C,N` | nil | 每项是 `MTLFunctionStitchingGraph`（`D-OBJC:9712` 族，另有 12 个 node/input 类）；非 nil → B | 深拷贝 |
| `functions` | `@"NSArray"`，`C,N` | nil | 每项解析到 Function | 深拷贝 |
| `binaryArchives` | `@"NSArray"`，`C,N` | nil | 同 4.5.1 | 深拷贝 |
| `options` | `Q` | 0 | 封闭 flag；未知位 → A | 标量 |

**整类 B**：function stitching 在 AIR 层面拼接函数图，上游的 translator 没有对应入口（`40-RUNTIME-VULKAN.md` 第 2.4 节无 stitching 类型）。`newLibraryWithStitchedDescriptor:error:` 返回 `Unsupported`，`needs` 写明 "function stitching"。

#### `MTLDynamicLibraryDescriptorSPI`

`D-OBJC:9342`。ivar：`_library` `_url` `_options` `_globalConstantsTag`。

| 字段 | 编码 | 默认 | 域 / 处置 | 类 |
|---|---|---|---|---|
| `library` | `@"<MTLLibrary>"`，`&,N` | nil | 解析到 Library | 句柄 |
| `url` | `@"NSURL"`，`C,N` | nil | 见 R28 | 深拷贝（受限） |
| `options` | `Q` | 0 | 封闭 flag | 标量 |
| `globalConstantsTag` | `Q` | 0 | 非 0 → B | 标量 |

**整类 B**：上游**可以创建** `DynamicLibrary` 对象但**拒绝链接使用**（`40-RUNTIME-VULKAN.md` 第 2.4 节）。因此 `newDynamicLibrary:error:` 可以成功，但把结果放进任何 `preloadedLibraries` / `insertLibraries` 必须返回 `Unsupported`。

### 4.21 `MTLLinkedFunctions`

`D-OBJC:12103`。`MTLLinkedFunctionsInternal` 的 `_private` = `MTLLinkedFunctionsPrivate`（`D-OBJC:12126`）：`functions`(@) `privateFunctions`(@) `binaryFunctions`(@) `functionResourceIndices`(^Q) `privateFunctionResourceIndices`(^Q) `binaryFunctionResourceIndices`(^Q) `groups`(@)。

| 字段 | 编码 | 默认 | 域 / 处置 | 类 |
|---|---|---|---|---|
| `functions` | `@"NSArray"`，`C,D,N` | nil | 每项解析到 Function | 深拷贝 |
| `binaryFunctions` | `@"NSArray"`，`C,D,N` | nil | 同上 | 深拷贝 |
| `groups` | `@"NSDictionary"`，`C,D,N` | nil | **键是 `NSString`、值是 `NSArray<id<MTLFunction>>`**。键 ≤ 1024 B；每组 ≤ 协议上限；键值类型必须逐个校验（`isKindOfClass:`）→ 不匹配 A | 深拷贝 |
| `privateFunctions` | `@"NSArray"`，`C,N`（SPI） | nil | 同 `functions` | 深拷贝 |

三个 `^Q` 的 resource-index 数组是 SPI，无公开 `@property`，处置同 R27。

**整类处置**：linked functions 要求 Vulkan 侧有函数指针或 pipeline library（`VK_EXT_graphics_pipeline_library` / `VK_KHR_pipeline_library` + ray tracing）。上游明确：`VisibleFunctionTable` 对象可建但**通过表调用被拒绝**（`40-RUNTIME-VULKAN.md` 第 2.4 节）。因此：
- `linkedFunctions` 非 nil 且其中任何数组非空 → **B**；
- 非 nil 但三个数组都为空、`groups` 为 nil → 等价于 nil，**按 D 档忽略**。

### 4.22 `MTLCompileOptions`

`D-OBJC:7595`，21 个 `@property`。`MTLCompileOptionsInternal`（`D-OBJC:7628`）用 21 个独立实存 ivar，无打包结构。默认值：`BLOCKED`（未反编译 `-[MTLCompileOptionsInternal init]`，`D-OBJC:7628` 的方法列表中可定位）。

| 字段 | 编码 | 默认（`INFERRED`） | 域 / 处置 | 类 |
|---|---|---|---|---|
| `sourceLanguage` | `C`（**8 位！**） | 0 = MSL | `{0,1}`（MSL / MSL-C++）；`> 1` → A。注意宽度是 `unsigned char` | 标量 |
| `languageVersion` | `Q` | 由 `_userSetLanguageVersion` 决定 | 已知 MSL 版本号；未知 → A | 标量 |
| `preprocessorMacros` | `@"NSDictionary"`，`C,D,N` | nil | 键 `NSString` ≤ 256 B、值 `NSString`/`NSNumber` ≤ 4096 B；条目 ≤ 256；类型不匹配 → A | 深拷贝 |
| `fastMathEnabled` | `c` | YES | 与 `mathMode` 是同一语义的两个 selector（旧/新） | 标量 |
| `mathMode` | `q` | 对应 `fastMathEnabled` | `{0,1,2}`（Safe/Relaxed/Fast）；未知 → A | 标量 |
| `mathFloatingPointFunctions` | `q` | 0 | `{0,1}`（Fast/Precise） | 标量 |
| `libraryType` | `q` | 0 = `Executable` | `{0,1}`；`Dynamic`(1) → B（见 4.20） | 标量 |
| `installName` | `@"NSString"`，`C,D,N` | nil | 仅 `Dynamic` 用；≤ 1024 B | 深拷贝 |
| `libraries` | `@"NSArray"`，`C,D,N` | nil | 每项解析到 DynamicLibrary；非空 → B | 深拷贝 |
| `preserveInvariance` | `c` | NO | → C（上游 translator 的精确性由 `DevicePolicy` 控制） | 标量 |
| `optimizationLevel` | `q` | 0 = `Default` | `{0,1,2}`；→ C | 标量 |
| `compileSymbolVisibility` | `q` | 0 = `Default` | `{0,1}`；→ C | 标量 |
| `allowReferencingUndefinedSymbols` | `c` | NO | 非 NO → B | 标量 |
| `maxTotalThreadsPerThreadgroup` | `Q` | 0 | 同 4.6 | 标量 |
| `requiredThreadsPerThreadgroup` | `{?=QQQ}` | `{0,0,0}` | 同 4.6 | 标量 |
| `enableLogging` | `c` | NO | 非 NO → 与 `MTLLogState`（4.28）联动；未实现时 C | 标量 |
| `tracingEnabled` | `c`（SPI） | NO | → C | 标量 |
| `framebufferReadEnabled` | `c`（SPI） | NO | 非 NO 要求 framebuffer fetch；Vulkan 侧需 input attachment 或 `VK_EXT_rasterization_order_attachment_access`（Lavapipe 有）→ 传递给 translator | 标量 |
| `debuggingEnabled` | `c`（SPI） | NO | → C | 标量 |
| `compileTimeStatisticsEnabled` | `c`（SPI） | NO | → C | 标量 |
| `additionalCompilerArguments` | `@"NSString"`，`C,D,N`（SPI） | nil | **必须忽略内容，不得转发给任何编译器命令行。** ≤ 4096 B，只记日志 → C。理由：这是客户端可控的任意字符串，转发等于命令注入面 | 深拷贝（只记日志） |

**整类处置**：`MTLCompileOptions` 只在 **MSL 源码编译**路径（`newLibraryWithSource:options:error:`）上有意义。本项目**不实现源码编译** —— 上游是 AIR → SPIR-V，没有 MSL 前端（`00-OVERVIEW.md` 第 3 节边界 ①）。因此：
- `newLibraryWithSource:…` / `newLibraryWithURL:…` → **B**，`needs` 写 "MSL front end"；
- `newLibraryWithData:error:` **不接受 options**，这条路径不受本节影响；
- 本节的字段表仍是必需的：返回 `Unsupported` 时要说清"缺什么"，并且 `MTLFunctionConstantValues`（4.29.4）在 `newFunctionWithDescriptor:` 路径上是真的要用的。

### 4.23 `MTLRasterizationRateMapDescriptor` 系

`D-OBJC:12975` / `12926`。三个类 + 两个容器。

`MTLRasterizationRateMapDescriptor`（默认值：`-[MTLRasterizationRateMapDescriptorInternal init]`，`S-METAL +0xC8E55`；`initWithScreenSize:` 在 `S-METAL +0xC8ED8`）：

| 字段 | 编码 | 默认 | 域 / 处置 | 类 |
|---|---|---|---|---|
| `screenSize` | `{?=QQQ}` | `{0,0,0}` | `width`/`height` ∈ `1..=16384`，`depth` = 层数；全部 checked | 标量 |
| `layers` | `@"MTLRasterizationRateLayerArray"`，`R,D,N` | 非 nil 容器（`D-OBJC:12905`） | 逐下标 `0..layerCount` | 容器 |
| `layerCount` | `Q`，**`R`（只读）** | 0 | 由 `layers` 的最高已设下标推出；`<= max_rasterization_rate_layer_count`（上游用 `supports_rasterization_rate_layer_count` 的最大接受值推出，`40-RUNTIME-VULKAN.md` 第 3.2 节） | 标量 |
| `label` | `@"NSString"`，`C,D,N` | nil | → C | 深拷贝 |

`MTLRasterizationRateLayerDescriptor`（默认值：`S-METAL +0xC867C`；`initWithSampleCount:` 在 `S-METAL +0xC86B6`，`initWithSampleCount:horizontal:vertical:` 在 `S-METAL +0xC87FC`）：

| 字段 | 编码 | 默认 | 域 / 处置 | 类 |
|---|---|---|---|---|
| `sampleCount` | `{?=QQQ}`（ivar `_size`） | `{0,0,0}` | `width`/`height` 是 rate 网格的格数；checked | 标量 |
| `maxSampleCount` | `{?=QQQ}`，`R` | — | 只读派生 | 标量 |
| `horizontal` | `@"MTLRasterizationRateSampleArray"`，`R,D,N`（`D-OBJC:13041`） | 非 nil 容器 | 逐下标 `0..sampleCount.width`，每项是 `float` | 容器 |
| `vertical` | 同上 | 非 nil 容器 | 逐下标 `0..sampleCount.height` | 容器 |
| `horizontalSampleStorage` | `^f`，`R,D,N` | — | **裸 `float*`，长度 = `sampleCount.width`。必须在 ObjC 方法返回前复制，并逐个过 R19（有限、`> 0`、`<= 1.0`）** | 深拷贝（原始内存） |
| `verticalSampleStorage` | `^f`，`R,D,N` | — | 同上，长度 = `sampleCount.height` | 深拷贝 |

上游对应：`metal2vulkan::bind::RateMapDescriptor`、`RasterizationRateMap`、`RateMapProblem`、`RegionRefusal`（`40-RUNTIME-VULKAN.md` 第 2.5 节）。**有落点**，但编译层有 5 个 `UnpinnedCompile` 拒绝 variant → 命中则 B。Vulkan 侧需 `VK_EXT_fragment_density_map` 或上游自己的多 pass 方案，`60-CAPABILITY-MATRIX.md` 负责登记 Lavapipe 的实际情况。

### 4.24 `MTLAccelerationStructureDescriptor` 全族

11 个类（`D-OBJC` 行号见第 2.1 节表的 #43–#54）。**全族处置：B。** 理由：Vulkan 侧需 `VK_KHR_acceleration_structure` + `VK_KHR_ray_query`/`VK_KHR_ray_tracing_pipeline`，Lavapipe 不提供；上游侧也没有 acceleration-structure 的值类型（`40-RUNTIME-VULKAN.md` 第 2 节全量清单中没有）。

本节仍给全量字段，因为 B 档要求能说清"缺什么"，且 `MTLDevice.accelerationStructureSizesWithDescriptor:` 要能在不建对象的情况下回答（返回全 0 + `Unsupported`）。

**`MTLAccelerationStructureDescriptor`**（基类，`D-OBJC:5717`）：`usage`（`Q`，默认 0 = `None`，封闭 flag：`Refit`/`PreferFastBuild`/`ExtendedLimits`）。

**`MTLAccelerationStructureGeometryDescriptor`**（几何基类，`D-OBJC:5735`，8 字段）：`intersectionFunctionTableOffset`(Q)、`opaque`(c，默认 YES)、`allowDuplicateIntersectionFunctionInvocation`(c)、`label`(@NSString,C)、`primitiveDataBuffer`(@<MTLBuffer>,&)、`primitiveDataBufferOffset`(Q)、`primitiveDataStride`(Q)、`primitiveDataElementSize`(Q)。
校验：`primitiveDataBufferOffset + primitiveDataStride * primitiveCount <= buffer.length`，checked；`primitiveDataElementSize <= primitiveDataStride`。

**六个几何子类的追加字段**（`KNOWN`，`D-OBJC`）：

| 类 | 追加字段 |
|---|---|
| `…TriangleGeometryDescriptor`（+11） | `vertexBuffer`(&)、`vertexBufferOffset`、`vertexFormat`、`vertexStride`、`indexBuffer`(&)、`indexBufferOffset`、`indexType`、`triangleCount`、`transformationMatrixBuffer`(&)、`transformationMatrixBufferOffset`、`transformationMatrixLayout`(q) |
| `…BoundingBoxGeometryDescriptor`（+4） | `boundingBoxBuffer`(&)、`boundingBoxBufferOffset`、`boundingBoxStride`、`boundingBoxCount` |
| `…CurveGeometryDescriptor`（+18） | `controlPointBuffer`(&)、`controlPointBufferOffset`、`controlPointCount`、`controlPointStride`、`controlPointFormat`、`radiusBuffer`(&)、`radiusBufferOffset`、`radiusFormat`、`radiusStride`、`indexBuffer`(&)、`indexBufferOffset`、`indexType`、`segmentCount`、`segmentControlPointCount`、`curveType`(q)、`curveBasis`(q)、`curveEndCaps`(q)、`endCaps`(q，旧名，同一 ivar `_endCaps`) |
| `…MotionTriangleGeometryDescriptor`（+10） | `vertexBuffers`(@NSArray,C)、`vertexFormat`、`vertexStride`、`indexBuffer`(&)、`indexBufferOffset`、`indexType`、`triangleCount`、`transformationMatrixBuffer`(&)、`transformationMatrixBufferOffset`、`transformationMatrixLayout`(q) |
| `…MotionBoundingBoxGeometryDescriptor`（+3） | `boundingBoxBuffers`(@NSArray,C)、`boundingBoxStride`、`boundingBoxCount` |
| `…MotionCurveGeometryDescriptor`（+16） | 与 Curve 同，但 `controlPointBuffers` / `radiusBuffers` 是 `NSArray`，无 `*BufferOffset` |

**三个顶层 descriptor**：

| 类 | 追加字段 |
|---|---|
| `MTLPrimitiveAccelerationStructureDescriptor`（+6，`D-OBJC:12825`） | `geometryDescriptors`(@NSArray,**&** 不是 C)、`motionStartBorderMode`(I)、`motionEndBorderMode`(I)、`motionStartTime`(f)、`motionEndTime`(f)、`motionKeyframeCount`(Q) |
| `MTLInstanceAccelerationStructureDescriptor`（+12，`D-OBJC:11990`） | `instanceDescriptorBuffer`(&)、`instanceDescriptorBufferOffset`、`instanceDescriptorStride`、`instanceCount`、`instancedAccelerationStructures`(@NSArray,**&**)、`instanceDescriptorType`、`motionTransformBuffer`(&)、`motionTransformBufferOffset`、`motionTransformCount`、`instanceTransformationMatrixLayout`(q)、`motionTransformType`(q)、`motionTransformStride` |
| `MTLIndirectInstanceAccelerationStructureDescriptor`（+15，`D-OBJC:11910`） | 同上，但 `maxInstanceCount` 取代 `instanceCount`，并加 `instanceCountBuffer`(&)、`instanceCountBufferOffset`、`motionTransformCountBuffer`(&)、`motionTransformCountBufferOffset`、`maxMotionTransformCount` |

> **R29**：`geometryDescriptors` 与 `instancedAccelerationStructures` 的属性标志是 **`&`（retain）而不是 `C`（copy）**（`D-OBJC:12825` / `11990`）。这意味着 descriptor 只持数组引用，**数组的内容（每个 geometry descriptor）仍是可变的、且数组本身可以是 `NSMutableArray`**。snapshot 必须对数组做一次浅拷贝（固定 count），再对每个元素递归 snapshot。只 retain 数组是不够的。

校验（全族共同，`INFERRED`）：全部 `*Count` × `*Stride` + `*Offset` 必须 checked 且 `<= buffer.length`；`motionStartTime <= motionEndTime`（R21）；`motionKeyframeCount == vertexBuffers.count`；`instanceDescriptorStride` 必须 `>=` 对应 `instanceDescriptorType` 的结构大小。

**`MTLAccelerationStructureAllocationDescriptor`**（SPI，`D-OBJC:5569`）：`storageMode`(Q)、`forceResourceIndex`(c)、`resourceIndex`(Q)。默认值：`S-METAL +0xCF8D5`。处置同族。

### 4.25 `MTLSharedTextureHandle`

`D-OBJC:14438`。**本类不是输入 descriptor，而是一个可序列化的跨进程句柄**，且它是 descriptor 族里唯一声明 `<NSSecureCoding>`（不是 `<NSCopying>`）的类。

ivar：`_priv`，类型 `^{MTLSharedTextureHandlePrivate=^{__IOSurface}@@}`（`KNOWN`，`D-OBJC:14438`）。即 **Apple 的 shared texture handle 内部就是一个 `IOSurfaceRef` 加两个对象指针**。

| 字段 | 编码 | 域 / 处置 | 类 |
|---|---|---|---|
| `device` | `@"<MTLDevice>"`，`R` | 只读；返回创建它的 Device proxy | 句柄 |
| `label` | `@"NSString"`，`R` | 只读 | 深拷贝 |

实现要点：

1. **两个方向都要实现**：`-[MTLTexture newSharedTextureHandle]` 产出，`-[MTLDevice newSharedTextureWithHandle:]` 消费。
2. `<NSSecureCoding>` 意味着客户端会把它 `NSKeyedArchiver` 之后通过 XPC 发给另一个进程。**`initWithCoder:` 必须按 secure coding 的规则实现**：逐键 `decodeObjectOfClass:forKey:`，拒绝未知键，不得 `decodeObjectForKey:`（会反序列化任意类）。
3. 上游的 `SharedTextureHandle` **仅进程内**（`40-RUNTIME-VULKAN.md` 第 2.3 节与第 4 节第 6 项），因此跨进程部分是本项目的工作：序列化的内容是**我们自己的 IOSurface 全局 ID + 一个 nonce**，解码侧用 `IOSurfaceLookup` 取回。详见 `41-IOSURFACE-USERSPACE.md`。
4. **`IOSurface` 的全局 ID 不是授权凭据**（`bridge-runtime-contract.md` 第 9 节的该条成立并在 `50-IPC-HELPER.md` 第 7 节加强）。`initWithCoder:` 解出 ID 之后仍必须验证调用者有权访问该 surface。

### 4.26 `MTLResidencySetDescriptor`

`D-OBJC:14017`。默认值：`-[MTLResidencySetDescriptor init]`，`S-METAL +0xDECD6`（`BLOCKED`，未反编译）。ivar：`_label` `_initialCapacity` **`_evictsImmediately`**（第三个 ivar 没有对应 `@property`，是 SPI 或未暴露字段）。

| 字段 | 编码 | 默认 | 域 / 处置 | 类 |
|---|---|---|---|---|
| `label` | `@"NSString"`，`C,N` | nil | → C | 深拷贝 |
| `initialCapacity` | `Q` | 0 | `0..=` 协议上限（对象数）；只是容量提示 → C | 标量 |

**整类处置**：residency set 是 Metal 4 之前引入的显式驻留管理。上游有 `Residency` / `HostResidency` / `host_shared_pointers` 与 `useResource:` / `useHeap:` 语义，但**没有 residency set 对象**（`40-RUNTIME-VULKAN.md` 第 2.3 节）。在 Lavapipe（统一内存、无显式驻留）上，驻留集的语义是**空操作**：

- `newResidencySetWithDescriptor:error:` **成功**，返回一个只做簿记的对象；
- `addAllocation:` / `commit` / `requestResidency` / `endResidency` 都是本地簿记 + 一次上游 `use_resource` 等价调用；
- `allocatedSize` 返回集合内对象的 size 之和。

`INFERRED`。这是"按 Metal 语义给出正确答案、代价不同"的典型，必须发一条 degradation（`Performance` 类）。**不能返回 `Unsupported`**：macOS 26 的 CoreAnimation 可能已经在用它，而驻留集失败会让客户端认为资源不可用。`BLOCKED`：WindowServer / CoreAnimation 在 26.7.2 上是否使用 residency set 未实测，与第 2.2 节的 trace 一并关闭。

### 4.27 `MTLIOCommandQueueDescriptor`

`D-OBJC:11592`。默认值：`-[MTLIOCommandQueueDescriptor init]`，`S-METAL +0x15FD69`（`BLOCKED`）。

| 字段 | 编码 | 默认 | 域 / 处置 | 类 |
|---|---|---|---|---|
| `maxCommandBufferCount` | `Q` | 0 | `0..=` 协议上限；0 = 实现决定 | 标量 |
| `priority` | `q` | 0 = `Normal` | `{0,1,2}` | 标量 |
| `type` | `q` | 0 = `Concurrent` | `{0,1}` | 标量 |
| `maxCommandsInFlight` | `Q` | 0 | checked | 标量 |
| `maxWorkerThreads` | `Q`（无 `N`，atomic！） | 0 | `0..=` 本机 CPU 数 | 标量 |
| `scratchBufferAllocator` | `@"<MTLIOScratchBufferAllocator>"`，`&`（无 `N`，atomic！） | nil | 非 nil 时是**客户端实现的协议对象**，我们要回调它 → 见下 | 句柄（客户端回调） |

注意 `maxWorkerThreads` 与 `scratchBufferAllocator` 的属性串**没有 `N`**（`D-OBJC:11592`），即它们是 atomic 属性。这是本文件里唯一的两个 atomic 字段。对 snapshot 无影响（我们只读），但说明 Apple 预期它们会被跨线程设置。

**整类处置**：`MTLIOCommandQueue`（fast resource loading）需要一个异步文件加载 + 解压流水线。上游无对应（`40-RUNTIME-VULKAN.md` 第 2 节无 MTLIO 类型）。**全类 B**：`newIOCommandQueueWithDescriptor:error:` 返回 `Unsupported`，`needs` 写 "MTLIO fast resource loading"。

`scratchBufferAllocator` 是**客户端实现的协议**（`id<MTLIOScratchBufferAllocator>`），我们要调它的方法。既然整类 B，就不会调；但如果将来实现，**它是本文件里唯一的"descriptor 字段是客户端代码入口"的情形**，必须按不可信代码对待：在 shim 的线程上调用、捕获 ObjC 异常、不持任何锁（与第 6.5 节的 block 规则相同）。

### 4.28 `MTLLogStateDescriptor`

`D-OBJC:12219`。默认值：`-[MTLLogStateDescriptor init]`，`S-METAL +0x7CB67`（`BLOCKED`）。

| 字段 | 编码 | 默认 | 域 / 处置 | 类 |
|---|---|---|---|---|
| `level` | `q`（无 `N`，atomic） | 0 | `MTLLogLevel`：`{0,1,2,3,4}`（Undefined/Debug/Info/Notice/Error/Fault）；未知 → A | 标量 |
| `bufferSize` | `q`（无 `N`，atomic） | 0 | `>= 1024`（Metal 的最小值）且 `<=` 协议上限；越界 → `nil + NSError` | 标量 |

**整类处置**：shader logging（`os_log` from MSL）需要 translator 把 `log` 调用编译成写入一个环形缓冲，再由 runtime 解码。上游有 `MessageSink` / `DebugMessage` / `MessageKind` / `MessageSeverity`（`40-RUNTIME-VULKAN.md` 第 2.1 节），但那是**驱动与 runtime 自己的通告通道**，不是 shader 侧的 `os_log`。

处置：`newLogStateWithDescriptor:error:` **成功**，返回一个对象；`addLogHandler:` 登记的 block **可能永远不被调用**（如果 translator 不支持 shader log）。`INFERRED`。理由同 4.26：失败会让客户端以为设备坏了，而"登记了处理器但没有日志"是完全合法的运行状态。必须发一条 degradation。
`BLOCKED`：上游 translator 对 MSL `os_log` 的支持情况未核，关闭方式是 `30-SHADER-AIR.md` 的覆盖率审计。

### 4.29 其余类

#### 4.29.1 `MTLCommandQueueDescriptor` / `MTLCommandBufferDescriptor`

`D-OBJC:7389` / `7369`。

| 类 | 字段 | 编码 | 默认 | 处置 |
|---|---|---|---|---|
| `MTLCommandQueueDescriptor` | `maxCommandBufferCount` | `Q` | 0 | `0` = 用上游默认（**上游每队列默认最多 64 个未完成 CB**，`bridge-runtime-contract.md` 第 5 节已记录，该条成立）；非 0 时与协议上限取小 |
| | `logState` | `@"<MTLLogState>"`，`&,N` | nil | 解析句柄；见 4.28 |
| `MTLCommandBufferDescriptor` | `retainedReferences` | `c` | **YES**（Metal 契约；`BLOCKED`：未从 `-[_MTLCommandBufferDescriptor init]`（`S-METAL +0x1EBFBC`）反编译确认） | → C。ObjC 侧的 retain 策略由 `_MTLCommandBuffer` 抽象层负责（`20-OBJC-DEVICE.md` 第 2.3 节第 3 条） |
| | `errorOptions` | `Q` | 0 = `None` | 封闭 flag（`EncoderExecutionStatus`）；未知位 → A；非 0 时要求我们能填 `MTLCommandBufferEncoderInfo` → 上游有 `ExecutedCommands` / `execution_report` 可部分支撑，不足部分 C |
| | `logState` | `@"<MTLLogState>"`，`&,N` | nil | 同上 |

注意 `_MTLCommandBufferDescriptor : MTLCommandBufferDescriptor`（`D-OBJC`）—— 这里的实现层前缀是 `_MTL` 而不是 `MTL…Internal`，是全族唯一的例外。

#### 4.29.2 四个 pass descriptor 与四个 sample buffer attachment

`MTLComputePassDescriptor`（`D-OBJC:7838`）：`dispatchType`（`Q`，默认 0 = `Serial`，`{0,1}`，`Concurrent`(1) 映射到上游的并发 dispatch 语义）+ `sampleBufferAttachments`（容器）。
`MTLBlitPassDescriptor`（`D-OBJC:6939`）、`MTLResourceStatePassDescriptor`（`D-OBJC:14113`）、`MTLAccelerationStructurePassDescriptor`（`D-OBJC:5951`）：各只有 `sampleBufferAttachments`。

四个 sample buffer attachment 类（`D-OBJC:7884` / `6972` / `14146` / `5989`）字段完全相同：`sampleBuffer`(@<MTLCounterSampleBuffer>,&)、`startOfEncoderSampleIndex`(Q)、`endOfEncoderSampleIndex`(Q)。处置同 4.4.4 / 4.19：`sampleBuffer` 恒 nil，三个字段读完即丢。

`MTLResourceStatePassDescriptor` 的整体处置是 **B**（`ResourceStateCommandEncoder` 在 macOS 上不可用，`40-RUNTIME-VULKAN.md` 第 2.2 节）。

#### 4.29.3 `MTLVisibleFunctionTableDescriptor` / `MTLIntersectionFunctionTableDescriptor`

`D-OBJC:15553` / `12062`。两类字段相同：

| 字段 | 编码 | 默认 | 域 / 处置 |
|---|---|---|---|
| `functionCount` | `Q` | 0 | `0..=` 协议上限；checked |
| `forceResourceIndex` | `c` | NO | 见 R25 |
| `resourceIndex` | `Q` | 0 | 见 R25 |

上游有 `VisibleFunctionTableDescriptor` 与 `FunctionTableProblem`（`40-RUNTIME-VULKAN.md` 第 2.4 节）。**对象可建，通过表调用被拒绝**：`newVisibleFunctionTableWithDescriptor:` 成功，`setFunctions:withRange:` 成功，但任何使用该表的 pipeline 创建或 draw → B。`MTLIntersectionFunctionTableDescriptor` 整类 B（ray tracing）。

#### 4.29.4 `MTLFunctionConstantValues`

`D-OBJC:9456`。**没有任何 `@property`**，只有三个 setter（`KNOWN`，`D-OBJC:9456` 的方法列表）：`setConstantValue:type:atIndex:`、`setConstantValues:type:withRange:`、`setConstantValue:type:withName:`，加一个 `reset`。因此它是一个**只能写、不能读**的容器。

> **R30**：`MTLFunctionConstantValues` 无法从外部读出内容。本项目必须**自己实现这个类**（它是 `MTLFunctionConstantValues` 而不是 `MTLFunctionConstantValuesInternal` 被客户端 `new` 出来的 —— `D-OBJC` 中两个类都存在，公开层的 `+alloc` 同样被重定向），因此客户端写进去的值我们本来就持有，snapshot 是对我们自己结构的拷贝，不是读 Apple 的对象。
>
> `BLOCKED`：**客户端拿到的 `MTLFunctionConstantValues` 到底是 Metal.framework 的类还是驱动的类，未确证。** 如果是 Metal.framework 自己的类（很可能，因为它不碰硬件），那我们必须通过它的私有 selector 或 `description` 读出内容 —— 这是本文最难的一处。关闭方式：反编译 `-[MTLFunctionConstantValuesInternal …]` 的全部方法（`D-OBJC` 中该类的方法列表），找出一个可读的访问器；若没有，则只能在 `newFunctionWithDescriptor:` 路径上返回 `Unsupported` 并把 `newFunctionWithName:constantValues:error:` 一并降级。
>
> 影响范围：function constant（`[[function_constant(n)]]`）是 MSL 的常规特性，CoreImage 的 kernel 大量使用。这一项不关闭，`60-CAPABILITY-MATRIX.md` 的 CoreImage 行就不能标绿。

#### 4.29.5 Metal 新特性与 SPI 的其余 descriptor

| 类 | 字段 | 处置 |
|---|---|---|
| `MTLTensorDescriptor`（`D-OBJC:14784`，10 字段） | `dimensions`(@MTLTensorExtents,C)、`strides`(@MTLTensorExtents,C)、`dataType`(q)、`usage`(Q)、`resourceOptions`(Q)、`cpuCacheMode`/`storageMode`/`hazardTrackingMode`(Q)、`forceResourceIndex`(c)、`resourceIndex`(Q) | **B**（ML tensor，无上游类型）。`dimensions`/`strides` 是 `MTLTensorExtents` 对象，递归 snapshot 时注意其 rank 上界 |
| `MTLResourceViewPoolDescriptor`（SPI，`D-OBJC:14207`） | `resourceViewCount`(Q)、`label`(@,C)、`forceBaseResourceID`(c)、`baseResourceID`(Q) | **B**。`baseResourceID` 与 R25 的 `resourceIndex` 同类，走 `IdPlacement` |
| `MTLMotionEstimationPipelineDescriptor`（SPI，`D-OBJC:12504`） | `textureWidth`(Q)、`textureHeight`(Q) | **B**（视频运动估计，无上游类型） |
| `MTLBVHDescriptor`（SPI，`D-OBJC:6509`） + `MTLBVHGeometryDescriptor` 族（`MTLBVHBoundingBoxGeometryDescriptor` / `MTLBVHCurveGeometryDescriptor` / `MTLBVHPolygonGeometryDescriptor`） | 与 4.24 的几何族平行的新一代 BVH 构建 API | **B**，与 4.24 同处置 |
| `MTLShaderValidationConfiguration`（`D-OBJC`） | — | **B** |

#### 4.29.6 `MTLIOAccelServiceDescriptor`（内部）

`D-OBJC:11355`：`acceleratorPort`(`I`，只读)、`deviceClass`(`#`，只读)。这是 Metal.framework **自己内部**用来把 `io_service_t` 与 plugin class 传给 `MTLIOAccelService` 的载体（见 `20-OBJC-DEVICE.md` 第 3 节的创建链）。**本项目不实现、不读、不构造**，列在此处只为说明它为何在 descriptor 清单里出现。

---

## 5. 到上游类型的字段级映射

上游类型清单取自 `40-RUNTIME-VULKAN.md` 第 2.1–2.9 节（`KNOWN`，来源是上游 `crates/metal2vulkan-runtime/src/lib.rs` 的 `pub use` 全集）。值类型在 `metal2vulkan` crate，对象在 `metal2vulkan-runtime`，runtime **不 re-export** 值类型（第 1.1 节），因此 adapter 必须同时依赖两个 crate 的同一 revision。

> **本节的"精确名以 rustdoc 为准"**：`40-RUNTIME-VULKAN.md` 第 2 节给的是类型名清单，不是字段清单。凡本节标 `BLOCKED(字段名)` 的，关闭方式统一是 `cargo doc -p metal2vulkan -p metal2vulkan-runtime --open` 读该类型的 rustdoc（每个 item 的 rustdoc 都注明其 Metal 对应物与差异，`40-RUNTIME-VULKAN.md` 第 0 节）。**不得按字段名猜。**

### 5.1 有上游值类型的 descriptor（直接映射）

| Metal descriptor | 上游类型 | crate | 映射性质 |
|---|---|---|---|
| `MTLTextureDescriptor` | `TextureDescriptor`（+ `TextureSwizzleChannels`、`TextureProblem`） | runtime §2.3 | **逐字段**。`swizzle` → `TextureSwizzleChannels`；`rotation` 是 IOSurface plane 专用 SPI，上游有同名字段 |
| `MTLBufferDescriptor` | `BufferDescriptor` + `BufferContents` | runtime §2.3 | **逐字段**。`contents`/`noCopy`/`deallocator` → `BufferContents::NoCopy` + `HostMemory` + `KeepAlive` |
| `MTLRenderPassDescriptor` | `RenderPassDescriptor`、`MAX_COLOR_ATTACHMENTS`、`RenderPassProblem` | runtime §2.5 | **逐字段** |
| `MTLRenderPassColorAttachmentDescriptor` | `RenderPassColorAttachmentDescriptor` + `Attachment` + `ClearColor` | runtime §2.5 | **逐字段** |
| `MTLRenderPassDepthAttachmentDescriptor` | `RenderPassDepthAttachmentDescriptor` + `MultisampleDepthResolveFilter` | runtime §2.5 | **逐字段** |
| `MTLRenderPassStencilAttachmentDescriptor` | `RenderPassStencilAttachmentDescriptor` + `MultisampleStencilResolveFilter` | runtime §2.5 | **逐字段** |
| `MTLRenderPipelineDescriptor` | `metal2vulkan::pipeline::RenderPipelineDescriptor` | **metal2vulkan** | **跨 crate**。`40-RUNTIME-VULKAN.md` 第 3.2 节明确这一条 |
| `MTLRenderPipelineColorAttachmentDescriptor` | `metal2vulkan::pipeline::ColorAttachmentDescriptor` | metal2vulkan | **逐字段**。`ColorAttachmentDescriptor::new` 的默认与 4.5.2 一致 |
| `MTLComputePipelineDescriptor` | `metal2vulkan::pipeline` 的 compute descriptor | metal2vulkan | `BLOCKED(类型名)` |
| `MTLDepthStencilDescriptor` + `MTLStencilDescriptor` | `DepthStencilState` 的构造参数 | runtime §2.4 | `BLOCKED(descriptor 值类型名)`。上游只列出 `DepthStencilState` 对象 |
| `MTLSamplerDescriptor` | `SamplerStateOptions` + `sampler_border_color` | runtime §2.4 | **逐字段** |
| `MTLHeapDescriptor` | `HeapDescriptor` + `HeapType` + `SizeAndAlign` + `HeapProblem` | runtime §2.3 | **逐字段** |
| `MTLIndirectCommandBufferDescriptor` | `IndirectCommandBufferDescriptor` + `IndirectCommandBufferProblem` | runtime §2.6 | **逐字段** |
| `MTLBinaryArchiveDescriptor` | `BinaryArchiveDescriptor` | runtime §2.4 | **逐字段**（`url` 按 R28 重定向） |
| `MTLFunctionDescriptor` | `FunctionDescriptor` + `metal2vulkan::pipeline::StageSource::Function` | runtime §2.4 / metal2vulkan | **逐字段** |
| `MTLVisibleFunctionTableDescriptor` | `VisibleFunctionTableDescriptor` + `FunctionHandle` + `FunctionTableProblem` | runtime §2.4 | **逐字段**（表调用仍 B） |
| `MTLRasterizationRateMapDescriptor` + `…LayerDescriptor` | `metal2vulkan::bind::RateMapDescriptor` + `RasterizationRateMap` + `RateMapProblem` + `RegionRefusal` | metal2vulkan / runtime §2.5 | **逐字段**。上游还有 `RateMapLayerDescriptor` 一节（`40-RUNTIME-VULKAN.md` 第 3.3 节） |
| `MTLRenderPipelineFunctionsDescriptor` | `RenderPipelineFunctionsDescriptor` + `BinaryFunctionProblem` + `BinaryFunctionStage` | runtime §2.4 | **逐字段** |
| `MTLSharedTextureHandle` | `SharedTextureHandle`（仅进程内） | runtime §2.3 | **部分**：进程内句柄用上游；序列化是本项目的（§4.25） |
| `MTLVertexDescriptor` + attribute/layout | `metal2vulkan::pipeline` 下的 vertex 描述 | metal2vulkan | `BLOCKED(类型名)` |
| `MTLStageInputOutputDescriptor` + attribute/layout | 同上 | metal2vulkan | `BLOCKED(类型名与是否实现)` |
| `MTLLinkedFunctions` | `metal2vulkan::pipeline` 的 linked-function 字段 | metal2vulkan | `BLOCKED(类型名)`；使用仍 B |
| `MTLTileRenderPipelineDescriptor` | 上游无 tile pipeline 类型 | — | **gap → B** |
| `MTLMeshRenderPipelineDescriptor` | 上游有 mesh 路径（`MeshRecordsOverflow` 错误、mesh 管线不产生 `PipelineRecord`）但未在 §2 列出 descriptor 值类型 | — | `BLOCKED`；当前 **B** |

### 5.2 跨字段共享的三类映射

这三类不是某个 descriptor 的字段，而是贯穿多个 descriptor 的同一机制，必须用同一个转换函数。

| Metal 字段群 | 上游类型 | 规则 |
|---|---|---|
| `resourceOptions` / `storageMode` / `cpuCacheMode` / `hazardTrackingMode`（出现在 `MTLTextureDescriptor`、`MTLBufferDescriptor`、`MTLHeapDescriptor`、`MTLTensorDescriptor`，4 处） | `ResourceOptions`、`StorageMode`、`CpuCacheMode`、`HazardTrackingMode`（runtime §2.3） | 用 `ResourceOptions::from_raw` 一次解析整个 word；三个分量不要分别解析（它们是同一 word 的位段，分别解析会在客户端只设其一时得到不一致结果）。**按 R24 同时保存声明值** |
| `forceResourceIndex` + `resourceIndex`（13 处，见第 3.7 节） | `IdPlacement`、`ResourceId`、`ResourceIdKind`、`Device::reserve_resource_ids`（runtime §2.3 / §4.1） | 统一经 R25 的校验函数产出 `Option<IdPlacement>` |
| `pinnedGPUAddress` / `parentGPUAddress` / `parentGPUSize`（仅 `MTLBufferDescriptor`） | `GpuAddress`、`AddressRange`、`AddressPlacement`、`AddressPool`、`RangeToken`、`PlacementConflict`、`Device::reserve_address_pool`（runtime §2.3 / §4.1） | 启动期建一个 `AddressPool`；每个 pinned 请求换一个 `RangeToken`；`PlacementConflict` → A |
| `pixelFormat`（出现在 `MTLTextureDescriptor`、`MTLRenderPipelineColorAttachmentDescriptor`、`MTLTileRenderPipelineColorAttachmentDescriptor`、`MTLMeshRenderPipelineDescriptor` 的 depth/stencil、`MTLSamplerDescriptor`、`MTLTextureViewDescriptor`，6 处） | `metal2vulkan::metal::PixelFormat` + `vk_format(pf, usages, profile)` + `FormatEmulation` | **必须同时传该次使用的 `FormatUsage` 集合**。同一格式在 `Attachment` 与 `Sample` 下的候选不同（`40-RUNTIME-VULKAN.md` 第 8.1 节）。把 usage 省掉是本节最容易犯的错 |
| `usage`（`MTLTextureDescriptor`） | `metal2vulkan::metal::TextureUsage` | 封闭 flag，`KNOWN_MASK` 由该类型导出（R22） |
| `label`（出现在 11 个 descriptor 上） | 各对象的 `set_label`；**`CommandBuffer` 没有上游 label 方法** | `bridge-runtime-contract.md` 第 5 节已记录该 gap，该条成立：command buffer 的 label 只存 proxy |

### 5.3 上游没有对应的 descriptor —— 处置表

每一项都给出"为什么没有"与"我们怎么回答"，不留空白。

| Metal descriptor | 上游状况 | 本项目的回答 | 档 |
|---|---|---|---|
| `MTLArgumentDescriptor` / `MTLIndirectArgumentDescriptor` | 上游只有 `ArgumentEncoder` 对象，无 descriptor 值类型（§2.6） | 自己把 descriptor 数组转成 `ArgumentEncoder` 的构造参数。`BLOCKED(构造签名)` | — |
| `MTLCompileOptions` | 上游无 MSL 前端（边界 ①） | 源码编译路径 `Unsupported`，`needs = "MSL front end"` | B |
| `MTLCounterSampleBufferDescriptor` | 上游无 counter set / sample buffer | `device.counterSets` 返回空数组 → descriptor 永远无效 | B |
| `MTLCaptureDescriptor` | 上游无 capture | `supportsDestination:` 全 NO | B |
| `MTLAccelerationStructure*`（11 个类） | 上游无 AS 值类型；Lavapipe 无 `VK_KHR_acceleration_structure` | `Unsupported`，`needs = "ray tracing"`；`accelerationStructureSizesWithDescriptor:` 返回全 0 | B |
| `MTLBVHDescriptor` 族（4 个类） | 同上 | 同上 | B |
| `MTLResidencySetDescriptor` | 上游有 `Residency` 语义但无 set 对象 | **成功**，本地簿记 + `use_resource` 等价调用 + `Performance` degradation | — |
| `MTLIOCommandQueueDescriptor` | 上游无 MTLIO | `Unsupported`，`needs = "MTLIO fast resource loading"` | B |
| `MTLLogStateDescriptor` | 上游有 `MessageSink` 但那是驱动通告，不是 shader log | **成功**，handler 可能永不触发 + degradation | — |
| `MTLTensorDescriptor` | 上游无 tensor | `Unsupported` | B |
| `MTLResourceViewPoolDescriptor` | 上游无 view pool；`IdPlacement` 可部分替代 | `Unsupported` | B |
| `MTLMotionEstimationPipelineDescriptor` | 上游无 | `Unsupported` | B |
| `MTLStitchedLibraryDescriptor` | 上游无 stitching | `Unsupported`，`needs = "function stitching"` | B |
| `MTLDynamicLibraryDescriptorSPI` | 上游 `DynamicLibrary` 可建、链接被拒 | 创建成功，使用 `Unsupported` | B |
| `MTLTextureViewDescriptor` | 上游有 `ViewProblem`（§2.6）但无 view descriptor 值类型 | 自己转成 `Texture` 的 view 创建调用。`BLOCKED(调用名)` | — |
| `MTLCommandBufferDescriptor` 的 `errorOptions` | 上游有 `ExecutedCommands` / `execution_report` 部分支撑 | 能填的填，填不了的留空并记 degradation | C |
| `MTLSharedTextureHandle` 的跨进程序列化 | 上游句柄仅进程内（§4 第 6 项） | 本项目实现（§4.25 + `41`） | — |
| `MTLFunctionConstantValues` 的**读出** | 不是上游 gap，是 Apple 的类无读接口 | 见 R30，`BLOCKED` | — |

### 5.4 上游提供而 Metal 没有的 descriptor 侧扩展

这些是上游专为"模拟 Metal 设备的消费者"写的（`40-RUNTIME-VULKAN.md` 第 4.1 节）。descriptor 层要用到的三项：

| 扩展 | 在 descriptor 层的用法 |
|---|---|
| `TextureDescriptor::address_mode_map`（+ `AddressModeMap`、`MappedSampling`） | 把纹理按别的 address mode 呈现。**本项目不从 Metal descriptor 填它**（Metal 没有对应字段），但 YCbCr 两 plane 路径可能需要（`41`） |
| `HostMemory::with_dirty_pages` / `with_import_gate` / `with_runs` / `with_dma_buf` | `MTLBufferDescriptor` 的 `noCopy` 路径的四条退路（macOS 上 dma-buf 不可用，走指针导入） |
| `Device::reserve_resource_ids` / `IdPlacement` | 13 个 `resourceIndex` 字段的落点（§5.2） |

---

## 6. ObjC 实现约定

### 6.1 descriptor 解码必须在编译为 Objective-C 的 shim 里

> **R31**：**全部 descriptor getter 必须在 `.m` 文件里用目标 SDK 的 typed 声明调用，由编译器生成调用约定。Rust 侧不得用无类型 `objc_msgSend` 猜 getter ABI。**

这条取自 `bridge-runtime-contract.md` 第 4 节，**成立并加强**。加强的理由是本文第 4 节新取得的事实：

1. **返回 struct 的 getter 走的不是 `objc_msgSend`。** `swizzle` 返回 `{?=CCCC}`（4 字节）、`clearColor` 返回 `{?=dddd}`（32 字节）、`requiredThreadsPerThreadgroup` 返回 `{?=QQQ}`（24 字节）、`levelRange` 返回 `{_NSRange=QQ}`（16 字节）。在 x86_64 SysV ABI 下，4 字节结构在 `eax` 返回、16 字节在 `rax:rdx`、24 与 32 字节走 **隐藏的 sret 指针参数**，调用的是 `objc_msgSend_stret`。用 `objc_msgSend` 读 32 字节的 `clearColor` 会读到垃圾并破坏栈。
2. **窄整数字段的内部宽度不等于属性宽度。** `maxTotalThreadsPerThreadgroup` 的属性是 `Q`（64 位）但 `_private` 里是 `S`（16 位）；`maxScissorRectCount` / `maxViewportCount` 的属性是 `Q` 但内部是 `C`（8 位）；`maxToolsDispatchBindings` 属性 `Q` 内部 `I`。**必须按属性宽度调用**（编译器会做），但**必须按内部宽度校验**（我们在第 4 节逐项给了上限）。
3. **自定义 getter 的 selector 名与属性名不同。** 七处：`isAlphaToCoverageEnabled`、`isAlphaToOneEnabled`、`isRasterizationEnabled`、`isTessellationFactorScaleEnabled`、`isBlendingEnabled`、`isDepthWriteEnabled`，以及 `MTLMeshRenderPipelineDescriptor` 上同名的三个（`D-OBJC` 的 `G` 标志全量）。手写 selector 名会得到 `doesNotRecognizeSelector:`。
4. **`BOOL` 在 x86_64 上是 `signed char`**，编码 `c`。把它当 `int` 读会带上高位垃圾。

实现形态（`INFERRED`）：

```objc
// src/objc/m2v_snapshot_texture.m —— 编译为 .m，-fobjc-arc 关闭（我们自己管 retain）
#import <Metal/Metal.h>
#include "m2v_snapshot.h"          // 纯 C 结构，Rust 用 bindgen 读同一头

bool m2v_snapshot_texture_descriptor(MTLTextureDescriptor *d,
                                     m2v_texture_snapshot *out)
{
    if (d == nil) return false;
    out->texture_type       = (uint64_t)d.textureType;      // typed，编译器生成 ABI
    out->pixel_format       = (uint64_t)d.pixelFormat;
    out->width              = (uint64_t)d.width;
    /* … */
    MTLTextureSwizzleChannels sw = d.swizzle;               // 4 字节结构，编译器选对返回方式
    out->swizzle[0] = (uint8_t)sw.red;   out->swizzle[1] = (uint8_t)sw.green;
    out->swizzle[2] = (uint8_t)sw.blue;  out->swizzle[3] = (uint8_t)sw.alpha;
    return m2v_validate_texture_snapshot(out);              // 第 3 节的 ② 层
}
```

> **R32**：`m2v_snapshot.h` 是 ObjC 侧与 Rust 侧的唯一共享契约。它只含 `#include <stdint.h>` 级别的纯 C 定义，不含任何 ObjC 类型。Rust 侧用 `bindgen` 生成，**不手写**，否则两边会漂移。
>
> **R33**：SPI 字段没有公开头。做法是在 shim 里对每个 SPI selector 写一个 `@interface MTLTextureDescriptor (M2VPrivate) - (NSUInteger)rotation; @end` 形式的类别声明，**逐个声明、带精确类型**。禁止用 `performSelector:`（它的返回类型是 `id`）或 `objc_msgSend` 强转。
>
> **R34**：每个 SPI selector 在调用前必须 `respondsToSelector:` 一次，结果缓存在一个一次性初始化的静态表里。SPI 在次要版本间可能消失；缺失时按该字段的默认值处理并记一条 degradation，不得崩。

### 6.2 `copyWithZone:` 语义

`KNOWN`（`D-OBJC`）：全部 descriptor 类都声明 `<NSCopying>` 并实现 `copyWithZone:`。

对本项目的后果分两面：

**我们要消费的 descriptor**：

> **R35**：**不要用 `[descriptor copy]` 代替 snapshot。** 三条理由：
> 1. `copy` 得到的仍是一个**可变**的 `MTLFooDescriptor`（Metal 的 descriptor 没有不可变孪生类），只是客户端拿不到它；
> 2. `copy` 是浅/深混合的 —— `C` 字段深拷、`&` 字段只 retain（第 0.1 节）。`MTLRenderPassDescriptor.colorAttachments` 里的 texture 只被 retain，而我们恰恰需要在那一刻把它解析成 `ObjectId`；
> 3. `copy` 会把 Apple 内部结构（`_private`）整块拷过来，我们并不理解其中的私有字段，等于把不理解的状态带进了提交路径。
>
> snapshot 比 `copy` 更贵吗？不。snapshot 只读我们理解的字段，`copy` 要拷整个 `_private`（`MTLRenderPipelineDescriptorPrivate` 是 736 字节）。

**我们要提供的 descriptor**：本项目自己实现的 descriptor 类只有一个 —— `MTLFunctionConstantValues`（R30）。它的 `copyWithZone:` 必须深拷常量值存储区，并且**返回的对象必须与原对象独立**（客户端会 `copy` 之后改原件）。

### 6.3 `MTLRenderPassDescriptor` 的 attachment 数组访问方式

把第 1.2、1.3 节的规则写成可直接实现的形态：

```objc
// 读 color attachments：按固定上界逐下标，不枚举
const NSUInteger cap = m2v_max_color_attachments();   // min(device.maxColorAttachments,
                                                      //     M2V_MAX_COLOR_ATTACHMENTS)
MTLRenderPassColorAttachmentDescriptorArray *arr = rp.colorAttachments;
for (NSUInteger i = 0; i < cap; i++) {
    MTLRenderPassColorAttachmentDescriptor *a = arr[i];   // objectAtIndexedSubscript:
    if (a == nil) continue;                                // 防御；实测恒非 nil
    id<MTLTexture> tex = a.texture;
    if (tex == nil) { out->color[i].active = false; continue; }   // R4/R7
    out->color[i].active = true;
    out->color[i].texture_id = m2v_resolve_texture(tex);   // → ObjectId，含 kind/ns/gen 校验
    /* level / slice / depthPlane / loadAction / storeAction / storeActionOptions */
    MTLClearColor c = a.clearColor;                        // 32 字节 → sret，必须 typed
    out->color[i].clear[0] = c.red;  /* … */
}

// 读 depth / stencil：先判断"有没有必要读"，因为 getter 有副作用（R3）
// 判据不能是 rp.depthAttachment != nil（它永远非 nil，一读就被懒创建）
MTLRenderPassDepthAttachmentDescriptor *dep = rp.depthAttachment;   // 懒创建发生在这里
out->depth.active = (dep != nil && dep.texture != nil);
if (out->depth.active) { /* 读 clearDepth / depthResolveFilter / … */ }
```

> **R36**：不得缓存 `rp.colorAttachments` 返回的容器对象跨调用使用 —— 它归 `rp` 所有，`rp` 析构时它一起走。
>
> **R37**：`arr[i]` 的下标**不能越过 `cap`**。Apple 的实现对越界下标的行为未测（`BLOCKED`；关闭方式是在目标 guest 上用 `metal-probe` 试一次 `arr[255]`），而我们也没有理由去试。
>
> **R38**：`sampleBufferAttachments` 同构，上界是 Metal 固定的 4。由于第 4.19 节的结论（无 counter set），这一层读完即丢，但**仍必须读** —— 不读就无法在 `errorOptions` 非 0 时解释为什么没有采样数据。

同一形态适用于另外 13 个容器（第 1.3 节清单），上界分别是：`MTLRenderPipelineColorAttachmentDescriptorArray` → `maxColorAttachments`；`MTLVertexAttributeDescriptorArray` / `MTLAttributeDescriptorArray` → 31；`MTLVertexBufferLayoutDescriptorArray` / `MTLBufferLayoutDescriptorArray` → `maxVertexBuffers`；`MTLPipelineBufferDescriptorArray` → 对应阶段的 buffer 上限；`MTLRasterizationRateLayerArray` → `layerCount`；`MTLRasterizationRateSampleArray` → 对应维度的 `sampleCount`；四个 sample buffer attachment array → 4。

### 6.4 snapshot 的所有权与错误返回

> **R39**：snapshot 函数的签名形如 `bool m2v_snapshot_X(X *desc, m2v_X_snapshot *out, m2v_error *err)`。失败时 `out` 不被写入任何句柄 retain（否则泄漏），`err` 填第 3.6 节的档位 + 字段名 + 原始值。字段名与原始值进日志，**不进 `NSError` 的 `userInfo`**（后者有大小与内容约束，见 `50-IPC-HELPER.md` 第 7 节）。
>
> **R40**：snapshot 成功后，对象句柄的 retain 已转移给 snapshot。释放路径只有一条：`m2v_release_X_snapshot(out)`。ObjC 方法在把 snapshot 交给 Rust 之后**不再拥有它**。

### 6.5 用户 block 与客户端回调

descriptor 层涉及两处客户端代码入口：`MTLBufferDescriptor.deallocator`（`@?`）与 `MTLIOCommandQueueDescriptor.scratchBufferAllocator`（协议对象）。

> **R41**：`deallocator` 必须 `_Block_copy` 一次、恰好调用一次、调用后 `_Block_release`。调用时不得持有任何锁（对象表、连接状态、命令缓冲状态、回调表）。ObjC 异常必须在 shim 边界捕获，不得穿过 Rust/FFI（`bridge-runtime-contract.md` 第 10.3 节的该条成立）。
>
> **R42**：`deallocator` 的调用点是上游 `KeepAlive` 被释放之时，不是 `MTLBuffer` 的 `dealloc` 之时。两者可能相差数帧（在途命令缓冲仍持有后备）。

---

## 7. 验收与剩余未知

### 7.1 必须建立的测试

| # | 测试 | 判据 |
|---|---|---|
| T-01 | **默认值回归**：对第 4 节每个有 `KNOWN` 默认值的字段，在目标 guest 上 `new` 一个 descriptor 并读回全部 getter，与本文的表逐项比对 | 全等。任何不等说明 25G325 installed SystemOS 与 BaseSystem 样本有差异（第 0 节已声明本文样本来自 BaseSystem），必须改本文 |
| T-02 | **懒创建副作用**：对一个新建的 `MTLRenderPassDescriptor`，先 `assert(rp.depthAttachment.texture == nil)`，再读 `rp.depthAttachment.loadAction` | 等于 2（`Clear`）。这同时验证 R4 与第 4.4.3 节的更正 |
| T-03 | **snapshot 隔离**：创建资源后立刻改 descriptor 的每一个字段，再读资源的 getter | 资源的 getter 不变 |
| T-04 | **容器上界**：对每个容器读 `cap-1` 与 `cap`（后者在我们自己的实现里，不是 Apple 的） | 前者成功，后者按 R37 拒绝 |
| T-05 | **struct 返回 ABI**：对 `swizzle`(4B)、`levelRange`(16B)、`requiredThreadsPerThreadgroup`(24B)、`clearColor`(32B) 四个宽度各写一个 round-trip | 读回等于写入。这一条专门钉 R31 的第 1 点 |
| T-06 | **自定义 getter**：对七个 `G` 标志字段，用 `class_getInstanceMethod` 确认 getter selector 名 | 与 `D-OBJC` 的 `G` 值一致 |
| T-07 | **校验矩阵**：对每个字段各构造一个越界值，确认返回的档位（A/B/C/D）与第 4 节一致 | 逐项一致；A 档不得静默成功，C 档不得失败 |
| T-08 | **非有限浮点**：对 R19 的 8 组字段分别写 NaN、+Inf、−Inf | 全部按 A 档拒绝 |
| T-09 | **`resourceIndex` 统一校验**：对 13 个字段各写 `forceResourceIndex=YES, resourceIndex=16384` | 全部拒绝，且错误里的字段名正确 |
| T-10 | **selector / encoding 对账**：对本项目实现的每个 descriptor 相关 selector，枚举 `class_copyMethodList` 并与 `21-OBJC-OBJECT-FAMILY.md` 的清单逐项比 `method_getTypeEncoding` | 全等；未知 selector 的 `respondsToSelector:` 为 false |

T-01、T-02、T-05、T-06 可以在**不实现任何渲染**的情况下跑，只需要 Metal.framework 与一个 `metal-probe`（`70-BUILD-PACKAGE.md` 第 6.1 节）。**它们应当是本项目在目标 guest 上跑的第一批测试**，因为它们验证的是本文全部字段表的前提。

### 7.2 剩余未知（按影响排序）

| # | 未知 | 影响 | 关闭方式 | 标签 |
|---|---|---|---|---|
| U-01 | **WindowServer 在 26.7.2 上走 Metal 2/3 还是 Metal 4 入口**（第 2.2 节） | 若是 Metal 4，本文第 2.1 节的 76 个类全部不够用，要换成第 2.2 节的 35 个 `MTL4*` 类 | 目标 guest 上对 WindowServer 做一次 selector trace，统计 `MTL4*` 协议命中 | `BLOCKED` |
| U-02 | **`MTLFunctionConstantValues` 能否读出内容**（R30） | 决定 function constant 能否支持，进而决定 CoreImage 能否工作 | 反编译 `MTLFunctionConstantValuesInternal` 的全部方法找可读访问器 | `BLOCKED` |
| U-03 | **BaseSystem 样本与 installed SystemOS 的默认值是否一致** | 本文全部 `KNOWN` 默认值的有效性 | T-01 | `BLOCKED` |
| U-04 | **上游 5 个值类型的精确字段名**（compute pipeline descriptor、depth-stencil descriptor、vertex descriptor、stage-input-output descriptor、linked functions，见第 5.1 节） | adapter 的转换代码写不出来 | `cargo doc -p metal2vulkan -p metal2vulkan-runtime` | `BLOCKED` |
| U-05 | **上游 `ArgumentEncoder` 的构造签名**（第 5.3 节） | argument buffer 路径 | 同上 | `BLOCKED` |
| U-06 | **8 个 descriptor 的 `init` 默认值未反编译**（`MTLRenderPipelineColorAttachmentDescriptorInternal`、`MTLMeshRenderPipelineDescriptor`、`MTLIndirectCommandBufferDescriptor`、`MTLCompileOptionsInternal`、`MTLBinaryArchiveDescriptor`、`MTLCaptureDescriptor`、`MTLFunctionDescriptor`、`MTLResidencySetDescriptor` / `MTLIOCommandQueueDescriptor` / `MTLLogStateDescriptor` / `_MTLCommandBufferDescriptor` / `MTLRenderPassSampleBufferAttachmentDescriptorInternal`） | 这些类的默认值现为 `INFERRED` | 各反编译一个 `init`（RVA 已在第 4 节逐处给出），约一次 IDA 会话 | `BLOCKED` |
| U-07 | **`MTLHeapDescriptorPrivate` 的 4 个未识别字段**（第 4.14 节） | 低；它们从公开 API 不可达 | 枚举 `MTLHeapDescriptorInternal` 的 getter 并逐个反编译 | `BLOCKED` |
| U-08 | **`depthStencilPrivate` / `stencilPrivate` 是否有客户端真的调用**（第 4.10 节） | 若有，我们必须导出一个布局兼容的只读结构 | guest trace | `BLOCKED` |
| U-09 | **Apple 实现对越界容器下标的行为**（R37） | 低；我们不会越界 | `metal-probe` 试一次 | `BLOCKED` |
| U-10 | **compute stage-in 是否被上游实现**（第 4.13 节） | 决定 `MTLStageInputOutputDescriptor` 是 B 还是可支持 | 读上游 rustdoc | `BLOCKED` |
| U-11 | **residency set / log state 是否被 26.7.2 的系统组件使用**（4.26 / 4.28） | 决定这两类的"成功但空操作"是否够 | 与 U-01 的同一次 trace | `BLOCKED` |

### 7.3 本文与 `bridge-runtime-contract.md` 第 4 节的关系

`bridge-runtime-contract.md` 第 4 节是本文的前身，内容是"v1 profile"（只接受 BGRA8 单 plane clear 与三角形所需的字段，其余一律 `Unsupported`）。按 `00-OVERVIEW.md` 第 4.7 节，**最小集规格作废**，因此：

| 原稿条目 | 本文处置 |
|---|---|
| 第 4 节"Descriptor 解码必须位于编译为 Objective-C 的 shim 中，通过 typed declarations 调 getter；Rust 不得用无类型 `objc_msgSend` 猜测 descriptor getter ABI" | **成立并加强**（R31，加了四条具体理由与 struct 返回 ABI 的证据） |
| 第 4 节"每次创建/encoder 调用在返回前生成不可变 snapshot；调用返回后不再读取调用者的 mutable descriptor" | **成立**（R1/R2） |
| 第 4 节"Snapshot 只允许下面的 v1 profile；任何非默认、未列出的值都返回 `Unsupported`" | **作废**。本文按全量字段编写，处置分 A/B/C/D 四档（第 3.6 节）而不是"非 v1 即拒绝" |
| 第 4.1 节 IOSurface texture snapshot v1（12 行限制） | **作废**。全量字段见第 4.1 节；IOSurface 的几何校验移到 `41-IOSURFACE-USERSPACE.md` 与 `50-IPC-HELPER.md` 第 7 节 |
| 第 4.2 节 Render pass snapshot v1（"`color[1..7]` texture 为 nil"、"depth/stencil 均无 attachment"） | **作废**。见第 4.4 节全量；但原稿的"`clear_color` 必须是 4 个有限 `f64`" **成立**（R19） |
| 第 4.3 节 Render pipeline snapshot v1（"`vertex_descriptor` 必须 nil"、"`color_attachments[1..7]` Invalid"） | **作废**。见第 4.5 节全量；原稿对 `ColorAttachmentDescriptor::new` 默认值的记录 **成立**（第 4.5.2 节） |
| 第 4 节"`NSError **` 在成功时不写；失败且指针非空时写入 autoreleased `NSError`，对象返回 `nil`" | **成立**，移入 `50-IPC-HELPER.md` 第 4 节（错误映射归那一册） |
| 第 4 节"`newLibraryWithData:error:` 必须把 `dispatch_data_t` 映射或分段复制到受限 blob；不得假定参数是 `NSData *`" | **成立**，移入 `50-IPC-HELPER.md` 第 2.5 节 |
| 第 4 节"`newBufferWithBytes:length:options:` 必须在 Objective-C 方法返回前完成字节复制" | **成立**（R26） |
| 第 12 节"§6.5 所有 descriptor 字段逐项读取 → v1 必须逐项读取与当前 profile 相关的字段，并显式拒绝其他非默认字段" | **再次修正**：按全量读取全部字段，按 A/B/C/D 分档处置。"显式拒绝其他非默认字段"在全量规格下过严 —— 它会让 `label`、`allowGPUOptimizedContents` 这类纯提示字段变成创建失败 |

**本文发现并更正的两处事实性错误**（原稿没有写错，但做了与事实不符的隐含假设）：

1. 原稿第 4.2 节按"depth/stencil 均无 attachment/resource"描述 v1，隐含"默认就是没有 attachment"。**现更正为**：`depthAttachment` / `stencilAttachment` 的 getter 会懒创建对象（`S-METAL +0x19BCD` / `+0x19D6D`），因此"有没有 attachment"只能看 `texture != nil`；且懒创建出来的 depth attachment 的 `loadAction` 默认是 `Clear`(2)、`storeAction` 默认是 `DontCare`(0)，与 color attachment 的 `DontCare`/`Store` 不同（`S-METAL +0x199E0` / `+0x19C92`）。
2. 原稿第 4.2 节把 `color[1..7]` 写成上界 7，隐含 `maxColorAttachments == 8`。**现更正为**：上界必须取 `min(device.maxColorAttachments, metal2vulkan_runtime::MAX_COLOR_ATTACHMENTS)` 并由 `20-OBJC-DEVICE.md` 第 5.2.1 节的 limits 表提供 —— 该节同时指出 `maxColorAttachments` 是 `initLimits` 的五条 release 断言之一（必须非零），所以它是一个我们自己选定并必须自洽的值，不是常量 8。
