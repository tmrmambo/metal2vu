# Metal 对象语义到 Vulkan 的映射契约

文档版本：1.0
基线：macOS Tahoe 26.7.2 build 25G325，**x86_64**
上游锚定：metal2vulkan `219f01365dc4c8eb346816c405b5b17403793764`（2026-10-29，`Re-pin the runtime sources at the landing tip`），产品版本 `0.2.0`，Rust 工具链锁定在 `rust-toolchain.toml`
许可证：`GPL-2.0-or-later OR LGPL-3.0-or-later`（分发前必须二选一，见 `METAL2VULKAN_INTEGRATION.md` §9）
状态：有效。本文是 `00-OVERVIEW.md` 第 3 节边界 ② 的实现契约。

## 0. 本文作用

本文回答三件事：

1. `metal2vulkan-runtime` 到底提供哪些对象与方法，每个对应哪个 Metal selector，在 Vulkan 侧落到什么；
2. 上游明确不做、必须由本项目补的事项清单；
3. 本项目创建 Vulkan device 的硬性要求：版本、feature、扩展、如何保证只选到 CPU 设备、loader 与 ICD 如何显式指定。

本文**不重复**上游已有的逐 selector 对照表。上游 `docs/RUNTIME-PORTING.md` 是机器可核对的全量表（约 400 行），`docs/METAL-COVERAGE.md` 是 2135 项的覆盖表，两者由脚本从 TSV 生成并有 CI 校验。把它们抄进本仓库只会腐烂。本文给的是**契约与规则**：对象清单（全量）、映射规则、不显然的行、以及上游不做的部分。

**读法**：实现者按本文建立 ObjC adapter 的转发表；每个 selector 的精确语义差异去读该 runtime 方法的 rustdoc（`cargo doc -p metal2vulkan-runtime --open`），每个 item 的 rustdoc 都注明其 Metal 对应物与差异。

---

## 1. 调用链与分层

```text
Metal 客户端（WindowServer / CoreAnimation / app）
  │  ObjC selector，x86_64 encoding
  ▼
Metal.framework
  │  class gate：principal class 必须是 _MTLDevice 子类
  ▼
本项目 Metal plugin bundle（ObjC 对象族）          ← 20 / 21 / 22
  │  窄 C ABI（descriptor snapshot、object id、typed error）
  ▼
本项目 runtime adapter（Rust）                     ← 本文 §3
  │  metal2vulkan-runtime 公开 API + metal2vulkan 的值类型
  ▼
metal2vulkan-runtime                               ← 本文 §2
  │  ash
  ▼
Vulkan loader
  │  ICD manifest
  ▼
Mesa Lavapipe                                      ← 本文 §6
```

三条规则（来自 `METAL2VULKAN_INTEGRATION.md` §4.3，本文重申并细化）：

1. **adapter 在 runtime 外侧**，不复制上游的 Device / Queue / Encoder，不自行推导 descriptor binding 或 push constant，不重算 Metal binding 编号。
2. **PipelineArtifact、BindingPlan、layout、interface、requirements 必须完整保留并原样消费**。adapter 只做 wire descriptor ↔ 上游类型的转换、对象 ID 映射、typed error ↔ 稳定 wire error。
3. **产品代码只从 `metal2vulkan-runtime` 与 `metal2vulkan` 的公开 API 进入**。`metal2vulkan-air` 只给分析工具用。三个 crate 必须同一 git revision。

### 1.1 两个 crate 的分工

`KNOWN`（来源：上游 `crates/metal2vulkan-runtime/README.md` "The crates" 节）

| crate | 提供 |
|---|---|
| `metal2vulkan-runtime` | Metal 的**对象与命令**：Device、CommandQueue、CommandBuffer、三个 encoder、Buffer、Texture、Heap、pipeline state、Event、Fence、Heap、ICB… |
| `metal2vulkan` | Metal 的**值类型与描述符**：`metal2vulkan::pipeline::RenderPipelineDescriptor`、`metal2vulkan::metal::PixelFormat`、`TextureUsage`、`bind::RateMapDescriptor` 等。runtime **不 re-export** 这些类型 |

因此本项目的 `Cargo.toml` 必须同时依赖两个 crate 的同一 revision，外加 `ash 0.38`（仅用于 Vulkan interop 调用）。

---

## 2. 对象清单（全量公开类型）

来源：上游 `crates/metal2vulkan-runtime/src/lib.rs` 的 `pub use` 全集（`KNOWN`）。标 `#[doc(hidden)]` 的项列在 §2.10，本项目**不得**依赖它们。

### 2.1 设备与队列

| runtime 类型 | Metal 对应 | Vulkan 落点 | 本项目 |
|---|---|---|---|
| `Device` | `id<MTLDevice>` | `VkInstance` + `VkPhysicalDevice` + `VkDevice` + queue family | 由 ObjC `_MTLIOAccelDevice` 子类持有，一对一 |
| `DeviceOptions` | 无（Vulkan 侧选择） | instance/device 创建参数 | **必须固定配置**，见 §6.6 |
| `DeviceKind` | 无 | `VkPhysicalDeviceType` | **必须只允许 `Cpu`**，见 §6.3 |
| `DeviceHandles`、`RawDevice` | 无 | 已有 instance/device 的接管 | 不用（本项目让 runtime 自己建设备） |
| `PhysicalDeviceIdentity` | 无（`registryID`、`deviceUUID` 的来源） | `VkPhysicalDeviceIDProperties` 等 | 用于在不建设备的情况下读身份 |
| `DeviceProperties` | `MTLDevice` 的公开属性全族 | 从 `VkPhysicalDeviceProperties`/`Features`/`Limits` 推出 | 转发给 `initLimits` / `initFeatureQueries` 链 |
| `Query` | 无（`Refusal::Query` 的来源） | 具体设备查询 | 用于"为什么 family 为 false"的解释 |
| `GpuFamily`、`FamilyRow`、`FeatureRow`、`LimitRow`、`FormatRow`、`FormatCapability`、`FormatCapabilities`、`RowState`、`RowAudit`、`Refusal`、`Framework` | `MTLGPUFamily` 与 Apple feature set 表的每一行 | 逐行在设备上判定 | **`supportsFamily:` 必须由此推出，不得硬编码**（`60-CAPABILITY-MATRIX.md` §1.4） |
| `CommandQueue` | `id<MTLCommandQueue>` | `VkQueue`（Lavapipe 只有一个 graphics queue） | 一对一；多 Metal 队列共享同一 `VkQueue` |
| `DriverFact`（re-export，来自 `metal2vulkan::device`） | 无 | 驱动实测偏差 | 进能力报告 |
| `MACOS_RELEASE` | 无 | 无 | runtime 统一按一个 macOS 版本回答格式/堆布局/私有属性（上游值为 macOS 27.0.1，在 M3 Max 上实测）。**本项目基线是 26.7.2，差异必须在 §10 验收中逐项核对** |
| `MessageSink`、`DebugMessage`、`MessageKind`、`MessageSeverity`、`LayerSetting`、`LayerSettingValue` | 无 | 验证层消息 + runtime 通告 | **必须接入**，见 §7 |

### 2.2 命令缓冲与编码器

| runtime 类型 | Metal 对应 | Vulkan 落点 | 本项目 |
|---|---|---|---|
| `CommandBuffer` | `id<MTLCommandBuffer>` | `VkCommandBuffer` 批次 + timeline semaphore | 一对一；状态机单向 |
| `CommandBufferStatus` | `MTLCommandBufferStatus` | — | 直接映射 |
| `Handler` | completion / scheduled block | — | ObjC block → 装箱 `FnOnce(&CommandBuffer) + Send` |
| `RenderCommandEncoder` | `id<MTLRenderCommandEncoder>` | 动态渲染（`VK_KHR_dynamic_rendering`）或 render pass + `VkPipeline` | 独占值，`end_encoding` 消费 |
| `ComputeCommandEncoder` | `id<MTLComputeCommandEncoder>` | `vkCmdDispatch*` | 同上 |
| `BlitCommandEncoder` | `id<MTLBlitCommandEncoder>` | `vkCmdCopy*`、`vkCmdBlitImage`、`vkCmdFillBuffer` | 同上 |
| `ResourceStateCommandEncoder` | `id<MTLResourceStateCommandEncoder>` | sparse 绑定 | **在 macOS 上不可用**（Lavapipe sparse 仅 Linux，`60-CAPABILITY-MATRIX.md` §4.1） |
| `EncoderKind`、`EndedEncoder`、`UsedResources` | 无（runtime 扩展） | — | 用于判断何时可以收回内存 |
| `Submission`、`SubmissionCheck`、`CommitFailure`、`FailedEncoders` | 无（runtime 扩展） | — | **guest 命令流校验与"按 Metal 方式失败"的注入点** |
| `ExecutedCommand`、`ExecutedCommands`、`ExecutedCommandsHandler`、`RecordsRead` | 无（runtime 扩展） | — | 读回间接命令记录 |

### 2.3 资源

| runtime 类型 | Metal 对应 | Vulkan 落点 | 本项目 |
|---|---|---|---|
| `Buffer` | `id<MTLBuffer>` | `VkBuffer` + `VkDeviceMemory`（或导入的 host 页） | 一对一 |
| `BufferDescriptor`、`BufferContents` | `newBufferWithDescriptor:`（SPI） | — | 值类型 |
| `Texture` | `id<MTLTexture>` | `VkImage` + view（或 buffer 上的 linear image / shadow 副本） | 一对一 |
| `TextureDescriptor`、`TextureProblem`、`TextureSwizzleChannels` | `MTLTextureDescriptor` | — | 值类型；`rotation` 为 IOSurface plane 专用 SPI |
| `VkImageLayouts`、`WrappedImageProblem`、`VkBufferMemory`、`WrappedBufferProblem` | 无 | 接管消费者自建的 `VkImage` / `VkBuffer` | **IOSurface 桥会用到** |
| `Heap`、`HeapDescriptor`、`HeapType`、`HeapProblem`、`SizeAndAlign` | `id<MTLHeap>`、`MTLHeapDescriptor` | 一块 `VkDeviceMemory` + 内部放置 | 一对一 |
| `HostMemory`、`HostBacking`、`HostBytes`、`Deallocator`、`KeepAlive`、`ImportGate`、`ImportRequest`、`RunResolver`、`HostRam`、`HostRamUse` | `newBufferWithBytesNoCopy:`（及其堆孪生） | `VK_EXT_external_memory_host`，失败时退到 dma-buf / guest RAM 整块 / 拷贝 | **IOSurface 桥的核心接口**，见 §5 |
| `DirtyPages`、`DirtyStamp` | 无（runtime 扩展） | 脏页日志驱动的增量拷入 | 可选优化 |
| `DmaBufChunk`、`DmaBufRequest`、`DmaBufSource`（`#[cfg(unix)]`） | 无 | `VK_EXT_external_memory_dma_buf` | macOS 上无 dma-buf，走指针导入路径 |
| `IoSurfacePlane`、`IoSurfaceYCbCr`、`SurfaceYCbCrMatrix` | IOSurface plane 上的纹理 | linear image / 转换后的 image | **仅 stand-in**；真实 IOSurface 由本项目提供 |
| `ResourceOptions`、`StorageMode`、`CpuCacheMode`、`HazardTrackingMode`、`PurgeableState` | `MTLResourceOptions` 系 | 内存属性与 barrier 策略 | 直接映射 |
| `ResourceRef`、`ObjectId`、`ResourceId`、`ResourceIdKind`、`IdPlacement` | `MTLResource`、`gpuResourceID`、`reserveResourceIndices:`（SPI） | 描述符编号 | **guest 自有编号由本项目维护并通过 `IdPlacement` 下压** |
| `GpuAddress`、`AddressRange`、`AddressPlacement`、`AddressPool`、`RangeToken`、`PlacementConflict` | `gpuAddress` | `bufferDeviceAddress` | 同上 |
| `SharedTextureHandle` | `MTLSharedTextureHandle` | — | **仅进程内**；跨进程由本项目实现 |
| `Residency`相关：`HostResidency`（`cfg(unix)`）、`host_shared_pointers` | `useResource:` / `useHeap:` 语义 | 驻留集 | 适配 |
| `PixelFormatInfo`、`TextureLevelInfo`、`TextureLevelQuery` | Apple 的格式/层级描述（部分为 SPI） | — | 值类型；Apple 的 flag word 由本项目补 |

### 2.4 管线与着色器

| runtime 类型 | Metal 对应 | Vulkan 落点 | 本项目 |
|---|---|---|---|
| `Library` | `id<MTLLibrary>` | 解析后的 AIR 容器 | 一对一；`new_library_with_data` 只接受 metallib，裸 AIR 需先过 `metal2vulkan::library::Library::from_air` |
| `Function`、`FunctionDescriptor` | `id<MTLFunction>`、`MTLFunctionDescriptor` | — | 一对一 |
| `RenderPipelineState` | `id<MTLRenderPipelineState>` | `VkPipeline`（创建时预测首个 draw 的 pipeline，其余按 draw key 现场建） | 一对一 |
| `ComputePipelineState` | `id<MTLComputePipelineState>` | `VkPipeline` | 一对一 |
| `PipelineOption`、`PipelineOptions` | `MTLPipelineOption` + `setResourceIndex:`（SPI） | — | 值类型 |
| `RenderPipelineFunctionsDescriptor`、`BinaryFunctionProblem`、`BinaryFunctionStage`、`RequiredThreadsProblem` | `*_with_additional_binary_functions` 系 | — | 值类型 |
| `DepthStencilState` | `id<MTLDepthStencilState>` | 动态/静态 depth-stencil 状态 | 一对一 |
| `SamplerState`、`SamplerStateOptions`、`sampler_border_color` | `id<MTLSamplerState>` | `VkSampler` | 一对一 |
| `BinaryArchive`、`BinaryArchiveDescriptor` | `id<MTLBinaryArchive>` | `VkPipelineCache` | 一对一 |
| `DynamicLibrary` | `id<MTLDynamicLibrary>` | — | 对象可建，**链接使用被拒绝**（`60-CAPABILITY-MATRIX.md` §3.13） |
| `VisibleFunctionTable`、`VisibleFunctionTableDescriptor`、`FunctionHandle`、`FunctionTableProblem` | `id<MTLVisibleFunctionTable>` 系 | — | 对象可建，**通过表调用被拒绝**（Vulkan 无函数指针） |
| `PipelineRecord`、`WarmStatistics` | 无（runtime 扩展，替代 Apple 的跨进程管线缓存） | `VkPipelineCache` 数据 + 着色器缓存目录 | **必须使用**，见 §6.6 与 `60-CAPABILITY-MATRIX.md` §7.1 |
| `ShaderCacheOptions`、`ShaderCacheStatistics`、`DEFAULT_CAPACITY`、`DEFAULT_MEMORY_CAPACITY` | 无 | 翻译结果的磁盘与内存缓存 | **缓存目录必须由本项目指定**，不得用默认的每用户目录 |

### 2.5 渲染通道与状态值

| runtime 类型 | Metal 对应 |
|---|---|
| `RenderPassDescriptor`、`RenderPassColorAttachmentDescriptor`、`RenderPassDepthAttachmentDescriptor`、`RenderPassStencilAttachmentDescriptor`、`Attachment`、`MAX_COLOR_ATTACHMENTS`、`RenderPassProblem` | `MTLRenderPassDescriptor` 全族 |
| `LoadAction`、`StoreAction`、`StoreActionOptions`、`ClearColor` | `MTLLoadAction`、`MTLStoreAction`、`MTLStoreActionOptions`、`MTLClearColor` |
| `Viewport`、`ScissorRect`、`DrawPrimitiveType`、`SamplePosition`、`Coordinate2D`、`Origin`、`Region`、`Size` | `MTLViewport`、`MTLScissorRect`、`MTLPrimitiveType`（含私有值 5–8）、`MTLSamplePosition`、`MTLCoordinate2D`、`MTLOrigin`、`MTLRegion`、`MTLSize` |
| `MultisampleDepthResolveFilter`、`MultisampleStencilResolveFilter` | 同名 Metal 枚举（**Lavapipe 只有 SAMPLE_ZERO**，§7 会产生降级通告） |
| `ResolveTarget`、`DrawProblem`、`RenderStateProblem` | `set*ResolveTarget:`（SPI）与状态问题 |
| `VisibilityResultMode`、`VisibilityProblem` | `MTLVisibilityResultMode` |
| `VertexAmplificationViewMapping` | `setVertexAmplificationCount:viewMappings:` |
| `RasterizationRateMap`、`RateMapProblem`、`RegionRefusal` | `MTLRasterizationRateMap` 全族 |

### 2.6 绑定与间接命令

| runtime 类型 | Metal 对应 |
|---|---|
| `ArgumentEncoder`、`ArgumentEncoderProblem` | `id<MTLArgumentEncoder>` |
| `IndirectCommandBuffer`、`IndirectCommandBufferDescriptor`、`IndirectCommandBufferProblem` | `id<MTLIndirectCommandBuffer>` 系 |
| `IndirectRenderCommand`、`IndirectComputeCommand`、`IndirectCommand`、`EncodedRenderCommand`、`EncodedComputeCommand`、`IndirectDraw`、`IndirectDispatch`、`IndirectBufferBinding`、`NIL_PATCH_BUFFER_ADDRESS` | `MTLIndirectRenderCommand` / `MTLIndirectComputeCommand` 及其 SPI getter |
| `IndirectCommandCheck`、`IndirectCommandCheckNeeds` | 无（runtime 扩展）：录制前逐命令校验 |
| `AddressModeMap`、`MappedSampling` | `TextureDescriptor::address_mode_map`（runtime 扩展） |
| `RebindProblem`、`BufferTextureProblem`、`ViewProblem`、`CopyProblem`、`BlitOption`、`MipmapProblem` | 各自路径的问题枚举 |
| `SparseFeatures`、`SparsePageSize`、`SparseProblem`、`SparseTextureRegionAlignmentMode` | sparse 全族（macOS 上不可用） |

### 2.7 同步

| runtime 类型 | Metal 对应 | Vulkan 落点 |
|---|---|---|
| `Fence` | `id<MTLFence>` | 编码器间的 barrier / 事件 |
| `Event`、`EventRef` | `id<MTLEvent>` | timeline semaphore |
| `SharedEvent`、`SharedEventHandle`、`SharedEventListener`、`SharedEventNotification` | `MTLSharedEvent` 全族 | timeline semaphore；**handle 仅进程内** |
| `SemaphoreProblem` | — | — |
| `host_time` | `MTLDevice` 的时间基准 | 主机时钟 |

### 2.8 可观测性

| runtime 类型 | 作用 |
|---|---|
| `Degradation`、`DegradationCategory`、`DegradeNotice`、`MisplacedNotice`、`NoticePlace` | 降级通告：给出 Metal 答案但代价不同，或给出有记录的近似等价物。`Degradation::code()` 是稳定字符串 `metal2vulkan-degrade-<kind>` |
| `WorkCounts`、`CopySite`、`MemoryFrees`、`ObjectChurn`、`ShadowKeeps` | 工作量计数：额外拷贝、丢弃的 draw / dispatch、shadow 保留、对象周转 |
| `Exactness` | 该路径是否精确 |
| `PrivateProperties`、`PrivateAnswer`、`PrivateCount`、`PrivateFlag` | Apple 私有属性的已测答案 |
| `AppleOnly`、`AppleOnlyCall`、`AppleOnlyGap`、`DEFAULT_PROTECTION_OPTIONS` | Apple 私有调用中无 Vulkan 形式或语义未测的部分 |

### 2.9 错误

全部失败都是 `metal2vulkan_runtime::Error` 的一个值。**必须按 variant 匹配，不得读消息文本**（上游明确要求）。

| variant | 含义 | 本项目应如何转成 ObjC |
|---|---|---|
| `Invalid(Invalid)` | 纯 Metal 自己也拒绝的误用（结束进程或调用失败）。`call` 给方法名，`problem` 给类型化 `Problem` | 按 Metal 行为：assert / abort / 返回 nil |
| `Nil(Nil)` | 纯 Metal 返回 nil 且进程继续 | 返回 nil |
| `MetalError(MetalError)` | 纯 Metal 返回 nil 并填 `NSError`：带 Metal 的 domain、code、描述 | 构造等价 `NSError` |
| `Unsupported(Unsupported)` | 设备缺少精确回答所需机制。`feature` 给 Metal 特性名，`needs` 给缺什么 | 进能力报告；capability 查询返回 false |
| `NotImplemented(RuntimeGap)` | 上游尚未构建的纯 Metal 功能 | 返回确定错误，**不得伪造成功** |
| `AppleOnly(AppleOnly)` | Apple 私有调用无 Vulkan 形式，或其在 Apple GPU 上的语义未测 | 返回确定错误 |
| `Unproven(Unproven)` | 无法证明纯 Metal 的答案 | **按上游建议：停止 guest 并命名问题**，不得猜 |
| `Compile(...)` | translator 拒绝、超预算或被取消 | 返回编译 `NSError` |
| `OutOfMemory`、`DeviceLost`、`Vulkan`、`NoDevice` | 设备自身失败 | `DeviceLost` → 命令缓冲进 `DeviceLost` |
| `LoaderNotFound(LoaderNotFound)` | Vulkan loader 未打开；`tried` 列出尝试过的路径 | **启动期致命**，见 §6.4 |
| `DriverSetting(DriverSetting)` | 驱动配置使 runtime 无法运行 | 启动期致命 |
| `WaitWouldDeadlock(DeadlockCause)` | 会死锁的等待被直接拒绝而非挂起 | 返回超时错误；**不得挂住 WindowServer** |
| `ShaderCache(...)` | 着色器缓存目录不可建或不可写 | 启动期致命 |
| `CommandBufferError`、`FailedPipeline`、`FailedState`、`PipelineCreationCause`、`BinaryArchiveError`、`BinaryArchiveMiss`、`ArchivedPipeline`、`MemoryKind`、`SamplerLimit`、`TimedOut`、`VkResultCode`、`FailureOrigin`、`InstanceApiVersion`、`InstanceExtensionRequired`、`ExtensionFeature`、`DynamicLibraryError`、`MeshRecordsOverflow`、`TessellationRecordsOverflow`、`EncoderCall`、`Problem`、`DriverSetting` | 细分类型 | 逐项映射到稳定 wire error（`50-IPC-HELPER.md`） |

### 2.10 `#[doc(hidden)]` 项 —— 禁止依赖

`Execution`、`ExecutedPipeline`、`exit_registrations` / `ExitRegistrations`、`generated_commands` 模块、`CommandsRecorded`、`set_making_budget_for_measurement` / `MakingBudgetStarted`、`makes_layouts_past_support`、`DynamicLibrary` 所在模块的隐藏部分。

`process_exiting` 不是 hidden，可用：进程退出时上游的清理钩子。

---

## 3. selector → 方法的映射规则

### 3.1 命名与形态规则（`KNOWN`，来源：上游 `docs/RUNTIME-PORTING.md` "Conventions"）

| Metal | runtime |
|---|---|
| `MTLFoo` 协议/类 | 去掉 `MTL` 前缀：`Foo` |
| selector `newBufferWithLength:options:` | 接收者上的 snake_case 方法：`Device::new_buffer(length, options)` |
| `retain` / `release` | `Clone` / `Drop`；对象 handle 是 `Send + Sync` 的廉价克隆值 |
| `id` 相等 | `PartialEq` / `Eq` / `Hash` 按身份 |
| nil 参数与结果 | `Option` |
| `NSError **` 出参、或失败返回 nil | `Result<_, Error>` |
| descriptor 对象 | 带公开字段的**纯值**；setter 就是字段写入 |
| 管线 descriptor | `metal2vulkan::pipeline` 的值类型（另一个 crate） |
| 编码器（由 `endEncoding` 关闭） | 独占值；`end_encoding(self)` 消费它 |
| completion / scheduled block | `Handler`：装箱 `FnOnce(&CommandBuffer) + Send` |
| `MTLSize` / `MTLOrigin` / `MTLRegion` | `Size` / `Origin` / `Region` |
| `MTLResourceOptions`、`MTLTextureUsage` | 类型化值（`ResourceOptions`；`metal2vulkan::metal::TextureUsage`） |
| Apple 私有 selector（SPI） | 同名方法（若上游有），否则 `Error::AppleOnly` |

**adapter 的转发表因此是机械的**：selector 名 → snake_case → 接收者方法。不机械的只有下面几类，必须逐条处理。

### 3.2 需要特别处理的行（全量，`KNOWN`）

| 类别 | 具体项 | 处理方式 |
|---|---|---|
| **编码器所有权** | 三个 encoder 都是独占值，`end_encoding` 消费 | ObjC 侧的 encoder 对象必须持有 `Option<Encoder>`，`endEncoding` 后置 `None`；之后的任何调用按 Metal 行为（assert / 忽略）处理 |
| **descriptor 是值不是对象** | `MTLTextureDescriptor`、`MTLRenderPassDescriptor` 等 | ObjC descriptor 对象在提交点做 **snapshot**（`22-OBJC-DESCRIPTORS.md`），不得持引用 |
| **管线 descriptor 跨 crate** | `MTLRenderPipelineDescriptor` → `metal2vulkan::pipeline::RenderPipelineDescriptor` | adapter 必须依赖 translator crate |
| **没有单一调用的项** | `BlitOption` 的 `CopyTextureRegionOptions`（需经 buffer 中转）；`GpuDevice::new_buffer_on_surface` / `new_texture_on_surface`（`new_buffer_with_bytes_no_copy` + `Buffer::new_texture_with_iosurface_plane`）；`max_vertex_amplification_count`（取 `supports_vertex_amplification_count` 接受的最大值）；`max_rasterization_rate_layer_count`（同理）；`max_viewport_count`（`DeviceProperties::max_viewports`） | 按上游 `docs/RUNTIME-PORTING.md` "Composed from runtime calls" 一节组合 |
| **私有 primitive 类型** | `MTLPrimitiveType` 值 5–8（line loop、triangle fan、quads、quad strip）与值 9 | 必须用 `DrawPrimitiveType::from_raw`。5–8 按 Metal 的顶点序展开为 list draw，quads 与 quad strip 的 `[[primitive_id]]` 按 Metal 的每 quad 计一个；**值 9 什么也不画并让命令缓冲按 Metal GPU 的方式失败**（hang / page fault / recovery victim），不得当成合法值 |
| **SPI 的 `resourceIndex`** | render / compute pipeline descriptor 的 `setResourceIndex:` | → `PipelineOptions::placement`，取低 32 位，必须 < 16384 |
| **SPI 的 predication 系** | `encodeStartIf:` / `encodeStartElse` / `encodeStartWhile:` / `encodeStartDoWhile` / `encodeEndIf` / `encodeEndWhile` / `encodeEndDoWhile:` | 上游**有**完整实现（含 Metal 的循环展开策略与未闭合块的行为）。返回 `BOOL` 的三个必须按 Metal 返回 `NO` 而非报错 |
| **SPI 的 protection options** | `setProtectionOptions:` | 非 0 的 options 会让命令缓冲从该编码器起失败（按 Metal GPU 行为）；1、3、7 在 Metal 会结束进程，上游拒绝；未测值返回 `AppleOnly::ProtectedContent` |
| **SPI 的 resolve target** | `set{Color,Depth,Stencil}ResolveTarget:` | 上游有同名方法，最后设置的生效 |
| **SPI 的 texture rotation** | `TextureDescriptor::rotation` 0–4 | 必须同时设 `framebuffer_only`，否则按 Metal 的 assert 拒绝 |
| **`object_id` 与 `unique_identifier`** | Metal 用指针标识对象 | runtime 另给 `ObjectId`（终身唯一、永不复用）。本项目的 wire 对象表应用它，不用指针 |
| **错误文本** | — | 禁止读 `Error` 的消息文本做分支；只匹配 variant |

### 3.3 逐 selector 对照表的权威位置

| 对象 | 上游表位置（`docs/RUNTIME-PORTING.md` 节） |
|---|---|
| 所有对象的构造 | `Platform` |
| `MTLBlitCommandEncoder` 的 26 条命令 | `BlitCmd` / `BlitEncoder` |
| `MTLCommandQueue` / `MTLCommandBuffer` | `CommandQueue` / `CommandBuffer` |
| `MTLComputeCommandEncoder` 的 30 条命令 | `ComputeCmd` / `ComputeEncoder` |
| `MTLRenderCommandEncoder` 的约 80 条命令 | `RenderCmd` / `RenderEncoder` |
| `MTLTextureDescriptor` / `MTLRenderPassDescriptor` / 管线 descriptor | 同名节 |
| `MTLDevice` 的构造与查询 | `GpuDevice` / `DeviceCaps` |
| `MTLSharedEvent` | `SharedEvent` |
| `MTLIndirectCommandBuffer` 与两类间接命令 | `IndirectCommandBuffer` / `IcbRenderCmd` / `IndirectRenderCommand` / `IcbComputeCmd` / `IndirectComputeCommand` |
| `MTLRasterizationRateMap` 全族 | `RateMap` / `RateMapDescriptor` / `RateMapLayerDescriptor` |
| `MTLResource` / `MTLBuffer` / `MTLTexture` / `MTLHeap` | `GpuResource` / `Buffer` / `Texture` / `Heap` |
| `MTLSamplerState` / `MTLDepthStencilState` | 同名节 |
| 两类 pipeline state、`MTLLibrary` | `ComputePipeline` / `RenderPipeline` / `Library` |

**验收要求**：本项目必须为上述每一节建一条 adapter 单元测试 fixture，证明转发指向上游的精确调用，且 ObjC 侧 `class_copyMethodList` 的 selector 与 type encoding 与 `21-OBJC-OBJECT-FAMILY.md` 的清单逐项一致。

---

## 4. 上游明确不做、留给本项目的事项

`KNOWN`（来源：上游 `crates/metal2vulkan-runtime/README.md` "Out of scope" 与 `docs/RUNTIME-PORTING.md` "Not the runtime's"）

上游的划分规则原话大意是：**普通 Metal 程序需要的归 runtime，只因为工作来自半虚拟化 guest 才存在的归消费者。** 以下每一项都是本项目的本体工作。

| # | 事项 | 上游提供的替代/基元 | 本项目分册 |
|---|---|---|---|
| 1 | **真实 IOSurface 与 Mach VM** | `new_buffer_with_bytes_no_copy`（`HostMemory`）、buffer 上建纹理、接管 `VkBuffer` / `VkImage`；导入 fd 或 dma-buf 则是普通 Vulkan | `41-IOSURFACE-USERSPACE.md`、`12-KERNEL-IOSURFACE.md` |
| 2 | **分散后备**（`replaceBackingWithRanges:`、`detachBacking`） | 把内存重映射成连续区后用 `rebind_bytes_no_copy` | `41` |
| 3 | **Apple 的序列化管线 descriptor** 与 guest 可见标识（`resourceIndex`、`uniqueIdentifier`、私有 device 答案） | 已测的按 Metal 规则答；`IdPlacement` / `reserve_resource_ids` 让消费者 pin 编号 | `22`、`20` |
| 4 | **presentation**（`CAMetalLayer`、`MTLDrawable` 全族 7 项） | 渲染进一张建在 swapchain image 上的纹理，再用普通 Vulkan present | `11-KERNEL-DISPLAY.md`。**本项目不走 swapchain，走 IOSurface + display provider** |
| 5 | **OS 服务**：时钟、定时器、线程、偏好、HostVm、启动器 | 无 | `50-IPC-HELPER.md`、`70-BUILD-PACKAGE.md` |
| 6 | **跨进程 `MTLSharedEvent`** 与 `MTLSharedTextureHandle` | 进程内 handle | `50` |
| 7 | **Metal plugin 注册、IOGPU service、IOUserClient、display provider、display sink、签名/安装/启动** | 无 | `10`、`11`、`20`、`70` |
| 8 | **Apple 的格式与设备描述**：`pixel_format_info` 的 Apple flag word、`gpu_core_count`、无实测覆盖的私有 limit 与 flag | `metal2vulkan::metal::format` 给 block 事实；`gpu_core_count` 在 Lavapipe 上为 `None` | `22`、`60-CAPABILITY-MATRIX.md` §6 |
| 9 | **Vulkan loader 与 Lavapipe 的 macOS x86_64 构建与打包**（runtime 不链接 Vulkan，运行时才打开 loader） | 无 | `70` |
| 10 | **进程模型、wire protocol、对象表与 generation、崩溃恢复** | `ObjectId`（终身唯一）、`used_resources`、`commit_failed`、`set_submission_check` | `50` |

### 4.1 上游提供的"为消费者而设"的 runtime 扩展

这些是 Metal 没有的调用，上游专门为"模拟 Metal 设备的消费者"写的。本项目**应当使用**，它们正是上面十项的接缝。

| 扩展 | 用途 |
|---|---|
| `CommandBuffer::commit_failed(CommitFailure)` | 把命令缓冲按失败提交，仍运行 Metal 会运行的编码器并保留其信号 |
| `CommandBuffer::set_submission_check` | 在提交时跑一次检查，按 Metal 的方式让该次提交失败 |
| `CommandBuffer::add_submission_handler`、`add_executed_commands_handler` | 批次到达 `VkQueue` 时、间接记录被读时的回调 |
| `CommandBuffer::used_resources`、`ended_encoders` | 命令缓冲完成前它用到哪些内存 → `detachBacking` 的等待依据 |
| `execute_commands_in_buffer_checked`、`execute_commands_in_buffer_indirect_checked` | 录制前逐条校验间接命令（guest 命令流校验点） |
| `HostMemory::with_dma_buf` / `with_dirty_pages` / `with_import_gate` / `with_runs`、`HostRam`、`Device::use_host_ram` | 导入 guest 页的四条退路 |
| `HostBytes`、`Texture::replace_region_with_host_bytes`、`BufferContents::CopyHost` | 读取过程中可能变化的 guest 内存 |
| `Buffer::host_backing` | 现在 GPU 实际用的是哪种后备（指针导入 / dma-buf / guest RAM 块 / 拷贝） |
| `Device::reserve_resource_ids`、`IdPlacement`、`AddressPlacement`、`Device::reserve_address_pool` | guest 自有编号与地址 pin |
| `DeviceOptions::pipeline_records` + `Device::warm(records, byte_budget)` + `WarmStatistics` | 跨进程管线缓存，替代 Apple 自己的 |
| `Device::registry_ids_with`、`with_registry_id`、`system_default_identity_with` | 不建设备就读身份、按 ID 只建一个设备 |
| `TextureDescriptor::address_mode_map` | 把纹理按别的 address mode 呈现 |
| `Device::raw()`、`CommandQueue::with_vk_queue`、`Texture::vk_image`、`Buffer::vk_buffer`、`SharedEvent::vk_semaphore`、`CommandBuffer::encode_wait_for_vk_semaphore` / `encode_signal_vk_semaphore`、`Device::new_texture_with_vk_image` / `new_buffer_with_vk_buffer` | 直接触碰底层 Vulkan 对象（每个调用都是 `unsafe`） |

---

## 5. 线程、所有权与生命周期

`KNOWN`（来源：上游 `src/lib.rs` 模块文档与 README "Conventions"）

| 类别 | 规则 | 对 ObjC 侧的要求 |
|---|---|---|
| 对象 handle（`Device`、`CommandQueue`、`CommandBuffer`、`Buffer`、`Texture`、`Heap`、`Library`、`Function`、`ComputePipelineState`、`RenderPipelineState`、`Event`、`SharedEvent`…） | 廉价克隆值，`Send + Sync`；`Clone` = retain，`Drop` = release；相等即同一对象 | ObjC 对象持有一个 handle；`retain`/`release` 不必与 Rust 侧 1:1，但最后一个 ObjC 引用消失时必须 drop handle |
| 编码器（三类 + `ResourceStateCommandEncoder`） | 独占值，`Send` 但 **不是 `Sync`**；`end_encoding(self)` 消费 | 一个 ObjC encoder 对象只能在一个线程上用；`endEncoding` 后对象进入终态 |
| descriptor | 纯值，无内部可变共享 | 在调用点 snapshot |
| 同一物理设备 + 相同 options | 返回同一个 `Device`（与 Metal 每 GPU 一个 `MTLDevice` 一致） | 本项目只会有一个设备，必须保证 options 恒定，否则会意外建出第二个 |
| 环境变量 | 上游**只**读平台默认缓存目录，别的什么都不读 | 本项目必须显式给 `ShaderCacheOptions`，不要依赖环境 |
| 进程退出 | `process_exiting` + `exit_registrations` | helper 退出路径必须调用，避免把 Vulkan 对象泄给驱动 |
| 命令缓冲状态 | 单向推进；`Completed` 与 `Error` 互斥；completion handler 只调用一次 | `CAPABILITY_PROFILES.md` §2.5 的要求由上游保证，adapter 不得破坏 |
| 死锁等待 | 会死锁的 `waitUntilCompleted` 被直接拒绝（`WaitWouldDeadlock`） | 必须转成确定错误，**不得挂住 WindowServer** |

---

## 6. Vulkan device 创建要求

### 6.1 版本与 feature 下限

`KNOWN`（来源：上游 README "Depending on it"）

| 项 | 要求 | Lavapipe |
|---|---|---|
| Vulkan API 版本 | **1.2 或更高** | 实现 1.4 面 ✓ |
| `timelineSemaphore` | **必需** | true ✓ |
| instance `apiVersion` | 默认 1.2；`DeviceOptions::instance_api_version` 可改。**超出 [1.2, loader 版本] 的值会被拒绝，不会被夹紧** | 由 loader 决定 |
| 构建期链接 | **无**。runtime 在建设备时打开 loader，或接管消费者给的 `vkGetInstanceProcAddr` | — |
| Rust | 1.98 或更高 | — |

### 6.2 扩展

runtime 自己会启用一组"推荐 enable"集合（translator 据实际启用项编译着色器）。本项目需要显式关心的只有三类：

| 类别 | 项 | 说明 |
|---|---|---|
| **必需（本项目功能依赖）** | `VK_EXT_external_memory_host` | IOSurface no-copy 导入的唯一路径。Lavapipe：`EXT_external_memory_host = true` ✓ |
| **强烈建议** | `VK_EXT_host_image_copy`、`VK_EXT_fragment_shader_interlock`、`VK_EXT_rasterization_order_attachment_access`、`VK_EXT_shader_stencil_export`、`VK_EXT_custom_border_color`、`VK_EXT_image_view_min_lod`、`VK_EXT_descriptor_indexing`、`VK_KHR_buffer_device_address`、`VK_KHR_dynamic_rendering`、`VK_EXT_sample_locations`、`VK_KHR_compute_shader_derivatives` | 分别对应 §8 与 `60-CAPABILITY-MATRIX.md` §2.2 的能力。Lavapipe 全部为 true |
| **必须不要** | swapchain / surface 全族（`VK_KHR_surface`、`VK_KHR_swapchain`、`VK_EXT_metal_surface`） | 本项目不走 Vulkan presentation，走 IOSurface + display provider。建设备时不要加，减少对 WSI 的依赖与崩溃面 |

`DeviceOptions` 的相关字段：

- `instance_extensions` / `device_extensions`：在 runtime 推荐集之外**额外**要求的扩展（缺则失败）。
- `optional_device_extensions`：列出但只在设备能启用时启用，永不因此失败；`Device::enables_extension` 查询实际结果。
- `withheld_features` / `withheld_extensions` / `withhold_generated_commands` / `withhold_view_reinterpretation`：从推荐集里**去掉**某些项，translator 随之按实际启用项编译。**调试用**：怀疑某扩展在 Lavapipe 上有缺陷时，用它二分定位。

### 6.3 强制只选 CPU device

Lavapipe 是本栈里唯一的 ICD，但**不能依赖"只有一个 ICD"**：loader 可能被别的 ICD 污染（用户装了 MoltenVK、或镜像里残留别的 manifest）。必须三重保险。

**第一重：`DeviceOptions::kinds` 只允许 `DeviceKind::Cpu`。**

`Device::system_default` 的默认顺序是 discrete → integrated → virtual → CPU；`kinds` 为空表示接受所有种类。本项目必须把 `kinds` 设为只含 `DeviceKind::Cpu` 的集合。效果：任何非 CPU 的 `VkPhysicalDeviceType` 都不合格，若无合格设备则返回 `Error::NoDevice`（**失败而不是回退**，这正是需要的）。

**第二重：按 registry ID 固定设备。**

1. 启动期用 `Device::registry_ids_with(&options)` 列出全部合格物理设备的 `registryID`（不建任何设备）；
2. 用 `Device::system_default_identity_with(&options)` 读身份（name、kind、IDs、`deviceUUID`、`registryID`、Vulkan 版本）；
3. 校验 kind 为 CPU、name 符合预期（llvmpipe 会把自己的名字写进 `deviceName`，形如 `llvmpipe (LLVM <ver>, <bits> bits)`）；
4. 用 `Device::with_registry_id(id, &options)` **只**建那一个设备。

这样即使 loader 枚举出多个设备，本项目也只会用确定的那一个，并且把它的身份写进 capability manifest。

**第三重：loader 与 ICD 显式指定（§6.4）。**

### 6.4 loader 与 ICD 的显式指定

**loader 的指定**：`DeviceOptions::loader` 给出要打开的 loader 库路径，替代默认搜索。上游默认搜索顺序是：平台默认名，然后在 macOS 上依次 `$VULKAN_SDK/lib`、`/opt/homebrew/lib`、`/usr/local/lib`。全部打不开时返回 `Error::LoaderNotFound`，其 `tried` 字段列出每条尝试过的路径。

**本项目必须显式给 `loader`**，指向随 guest 交付的那一份 loader（安装布局见 `70-BUILD-PACKAGE.md`）。理由：`/usr/local/lib` 与 Homebrew 路径是用户可写的，依赖默认搜索等于把渲染栈的完整性交给环境。

**ICD 的指定**：这部分不在 runtime 的 API 里，由 Vulkan loader 自己决定。本项目必须在 helper 进程启动时设定环境，**在加载 loader 之前**：

| 变量 | 作用 | 本项目取值 |
|---|---|---|
| `VK_DRIVER_FILES` | 显式列出 ICD manifest 的完整路径，**完全替代**默认搜索（loader ≥ 1.3.207 的现行名称） | 随包 `lvp_icd.x86_64.json` 的绝对路径 |
| `VK_ICD_FILENAMES` | 上者已弃用的旧名 | **显式 unset**，避免与新名并存时的歧义 |
| `VK_ADD_DRIVER_FILES` | **追加**而非替代 | **显式 unset**（设了 `VK_DRIVER_FILES` 时它本就失效，清掉是为了语义可预测） |
| `VK_LOADER_DRIVERS_SELECT` | 按**清单文件名** glob 过滤已找到的驱动 | `lvp_icd.*`，第二道保险。注意匹配不到时结果是"无驱动可用"，应用直接失败——这是有意的 fail-closed |
| `VK_LOADER_SEARCH_ONLY_IN_BUNDLE` | 只在 `(bundle)/Contents/Resources/` 下找清单 | 渲染核心以 bundle 交付时设置 |
| `VK_LAYER_PATH` / `VK_INSTANCE_LAYERS` | 层路径与自动启用的层 | 发布配置下清空；研发配置下指向随包的验证层 |

精确的取值、设定顺序与安装布局由 `70-BUILD-PACKAGE.md` 规定（它给出 helper 启动时的 `setenv` 序列）；`80-TEST-HARNESS.md` 规定测试环境下的同一组变量。本文只规定**契约**：runtime 在建设备时打开 loader，所以这些变量必须在**打开 loader 之前**设定好。

`INFERRED`：以上是 Vulkan loader 的标准行为，本项目的取值是实现选择。`BLOCKED`：**这些变量在目标 guest 的 helper 启动环境里是否生效（launchd 传递、SIP 关闭后的 `DYLD_*` 交互）未实测**，由 `70-BUILD-PACKAGE.md` 的 Gate 1 关闭。

**不要静态链接 ICD**：按 `METAL2VULKAN_INTEGRATION.md` §8，首选标准 loader 动态加载 ICD；只有在目标 guest 上证明该方式失败，才评估静态链接。

**关于 `VK_LUNARG_direct_driver_loading`**（`70-BUILD-PACKAGE.md` 提出、要求本文评估）：该扩展让应用在 `vkCreateInstance` 时直接把 ICD 的 `vk_icdGetInstanceProcAddr` 交给 loader，完全绕开文件系统发现。对本项目确实更干净——渲染核心与 Lavapipe 同进程、同交付包。**但当前不采用**，两条理由：

1. `metal2vulkan-runtime` 的 `DeviceOptions` 没有暴露该路径。能走它的只有 `Device::from_raw(RawDevice, DevicePolicy)`，即由本项目自己建 instance 与 device 再交给 runtime。那会把 instance/device 创建的全部正确性责任（推荐 enable 集合、`EnableSet` 的精确填写、portability 处理）从上游移到本项目，违反 §1 的第一条规则。
2. 三重保险（§6.3 + `VK_DRIVER_FILES` + `VK_LOADER_DRIVERS_SELECT`）已经把污染风险压到可接受。

`INFERRED`。重新评估的触发条件：Gate 1 证明环境变量在 launchd 下不可靠，或出现无法通过变量排除的 ICD 污染。届时方案是让本项目用 `ash` 自建 instance/device 并走 `Device::from_raw`，代价与收益在 `70-BUILD-PACKAGE.md` 重新讨论。

### 6.5 驱动配置的硬性拒绝

`Error::DriverSetting(DriverSetting)` 表示 runtime 无法在该驱动配置下运行。上游举的例子是 MoltenVK 关掉了 Metal argument buffer。本项目在启动期必须把这个错误当致命错误上报，而不是降级继续。

### 6.6 本项目的固定 `DeviceOptions`

这是一张**必须固定、必须进 capability manifest** 的配置表。`INFERRED`（实现选择）。

| 字段 | 取值 | 理由 |
|---|---|---|
| `kinds` | 仅 `DeviceKind::Cpu` | §6.3 |
| `loader` | 随包 loader 的绝对路径 | §6.4 |
| `instance_api_version` | 1.2 | 下限即可；更高版本不带来需要的能力，且放宽了对 loader 的要求 |
| `instance_extensions` / `device_extensions` | 空（只用推荐集）+ 显式要求 `VK_EXT_external_memory_host` | §6.2 |
| `optional_device_extensions` | §6.2 "强烈建议" 一行的全部 | 能启就启，不因此失败 |
| `withheld_*` | 空（发布）；研发期按需二分 | §6.2 |
| `layers` / `layer_settings` | 发布：空。研发：验证层 + 同步验证 | 同步验证会在共享未追踪资源上报告 Metal 允许的 hazard（上游明确说明），不能把它的报告直接当缺陷 |
| `messages` | **必须给 `MessageSink`**，接到本项目日志 | §7。不给的话通告走 stderr，在 helper 里会丢 |
| `shader_cache` | 本项目控制的目录（随镜像预置，绑定 guest build + 组件哈希） | 不能用默认的每用户缓存目录 |
| `gpu_times_from_host` | true | 省掉每个命令缓冲两次 timestamp；Lavapipe 的 calibrated timestamp 未实测 |
| `announce_each` | 发布：空（每种降级只报一次）。研发：关键种类设为每次都报 | 控制日志量 |
| `lowering_refuses` | **空** | 非空会让 render 编码器在遇到特定降级时直接让命令缓冲失败。对 WindowServer 来说"降级但出画面"远好于"失败" |
| `record_executions` | 发布：false。研发：true | 记录每个 draw/dispatch 跑的是哪个管线，排障用 |
| `pipeline_records` | **必须给回调**，把 `PipelineRecord` 持久化 | 跨进程管线预热的前提，见下 |
| `policy`（translator 的 `DevicePolicy`） | 见下 | |

**`DevicePolicy` 的三个关键值**（`KNOWN`：上游默认值；`INFERRED`：本项目取值）：

| 项 | 上游默认 | 本项目 | 理由 |
|---|---|---|---|
| `pipeline_creation_wait` | 4.5 s | **必须显式设定并与显示超时对齐** | 一个 host step 若既建状态又提交，最坏等 9 s，而 guest 的 FIFO 检查是 10 s（上游 README 明确指出这个关系）。本项目的 display provider 超时必须大于两者之和，否则 WindowServer 会先超时 |
| `pipeline_commit_wait` | 4.5 s | 同上 | 同上 |
| 精确性开关（`FAST-PATHS.md` 的 fast / exact 形式） | 按 policy | 发布：倾向 exact；对合成热路径按实测放 fast | 先正确后快 |

**管线预热流程**（必须实现，`60-CAPABILITY-MATRIX.md` §7.1 的缓解措施）：

1. `DeviceOptions::pipeline_records` 的回调在每次管线状态创建时被调一次，拿到 `PipelineRecord`（创建用的 descriptor 全字段 + 按内容哈希命名的 library，library 本体留在着色器缓存目录）；
2. `PipelineRecord::to_bytes` 持久化；
3. 下次进程启动时 `from_bytes` 读回（格式不符的记录返回 `None`，直接丢弃——这正是跨系统更新后的正确行为）；
4. `Device::warm(records, byte_budget)` 立即返回，在设备自己的一条后台线程上按序重建：翻译结果进着色器缓存，预测的 `VkPipeline` 数据进驱动记录。驱动管线缓存增量达到 `byte_budget` 字节就停；
5. `Device::warm_statistics` 读回成功/失败/丢弃计数，进能力报告。

`warm` 的安全性质（`KNOWN`）：不取标识符、不取 resource ID、不取 sampler 编号，不建 neutral，不报降级，不为程序的 kept variant 留东西，不读别的 translator 的翻译结果，也不读别的 `RUNTIME_VERSION` 的记录——**所以它不会改变程序拿到的任何答案**。mesh 管线不产生记录；烘焙了 immutable sampler 的 layout 只做翻译。

### 6.7 启动期自检清单

helper 进程建设备后、对外发布设备前必须完成并记录：

1. loader 打开成功，路径与预期一致（否则 `LoaderNotFound.tried` 进日志并致命退出）；
2. `registry_ids_with` 恰好返回一个 ID；多于一个则日志记录全部并按策略取第一个 CPU 设备；零个则致命；
3. `system_default_identity_with` 的 kind 为 CPU、`deviceName` 匹配 llvmpipe 模式、Vulkan 版本 ≥ 1.2；
4. `DeviceProperties` 快照落盘（进 `90-EVIDENCE-INDEX.md`）；
5. `family_blockers(Mac2)`、`family_blockers(Common3)`、`family_blockers(Metal3)` 全量落盘（`60-CAPABILITY-MATRIX.md` C-04）；
6. `Device::enables_extension` 对 §6.2 的每一项落盘；
7. 着色器缓存目录可写；
8. `warm` 完成后的 `WarmStatistics` 落盘。

---

## 7. 可观测性：degradation / work counts / refusal → 诚实的能力报告

上游提供三个互补的通道。本项目的能力报告**必须同时消费三者**，否则报告就只是"支持/不支持"两个字，排障成本会翻倍。

### 7.1 Degradation（降级通告）

`KNOWN`（来源：上游 `src/degradation.rs` 与 README "Degrade notices"）

- 语义：runtime 给出了 Metal 的答案，但代价与 Metal 不同；或给出一个**有记录的近似等价物**。
- 投递：通过 `DeviceOptions::messages` 的 `MessageSink`，作为 `DebugMessage` 的 `degradation` 字段（`DegradeNotice`）；未给 sink 时落 stderr。
- **通告永不致命。**
- 默认每种 kind 只报一次；`DeviceOptions::announce_each` 可让指定 kind 每次都报。
- 解码方式：**只用 `Degradation` 枚举值与 `Degradation::code()`**（稳定字符串 `metal2vulkan-degrade-<kind>`），`category()` 说明代价性质。**禁止解析通告文本。**
- 分类：`Performance`（给出 Metal 的答案但付了额外拷贝 / staging / scratch / 多一趟 pass / 更慢的变体）、`Precision`（有记录的近似等价物，不是 Metal 的精确答案）、`Validity`（给出 Metal 的精确答案，方式是用了驱动未声明但实测按 Metal 行为运行的能力——Vulkan 规范不允许这样用，所以验证层会报）。
- 规模：`degradation.rs` 的宏定义中约 150 个 kind（runtime 自有的 + 每个 precision note 一个）。

本项目的要求：

1. `MessageSink` 必须接到结构化日志，每条记录 `Degradation::code()`、`category()`、涉及的对象与原因字段；
2. capability manifest 中，**每个声明为"支持"的能力都要附上它在本栈上会触发的 degradation code 列表**；
3. `Validity` 类通告必须单独统计。它意味着依赖了未声明的驱动行为，升级 Mesa 时这些点最先坏；
4. 关键 kind 举例（与本项目强相关，`KNOWN`）：`shared-present-queue`（Lavapipe 单队列）、`shadowed-texture`（host 页上的纹理保留了副本）、`copied-host-pages`（no-copy 导入退化为拷贝）、`device-color-conversion`、`texture-buffer-fill-leftover`、`unpacked-fill-color`、`draw-dropped-still-making`、`dispatch-dropped-still-making`、`pass-bound-clear-reach`、`decoded-texel-precision`、`shared-in-system-memory`。

### 7.2 Work counts（工作量计数）

`KNOWN`（来源：上游 `src/work_counts.rs`，`WorkCounts`、`CopySite`、`MemoryFrees`、`ObjectChurn`、`ShadowKeeps`）

这些是"做了多少 Metal 不会做的事"的量化值。README 直接点名的几个：

| 计数 | 含义 |
|---|---|
| `draws_dropped_unmade` | 管线在 draw 返回后仍未建好 → 该 draw 什么也没画，但命令缓冲**不报错** |
| `draws_dropped_still_making`、`dispatches_dropped_still_making` | 等到 commit 的管线等待上限仍未建好 → 同上（dispatch 的情况会让命令缓冲失败） |
| `device_copy_textures` | 为了避免跨总线采样而把纹理拷进设备内存的次数 |
| `ycbcr_textures_in_place`、`ycbcr_planes_bound`、`ycbcr_images_kept_*` | 两 plane YCbCr 走了原地路径还是保留了转换后的 image |

本项目的要求：

1. **`draws_dropped_*` 非零必须报警**。这是"画面少了东西但没有任何错误"的唯一信号，对 WindowServer 来说是静默损坏；
2. 每帧或每 N 帧采样一次 `WorkCounts` 的差值，进性能日志；
3. `CommandBuffer::dropped_draw` 给出第一个被丢弃的 draw，排障时必须打印。

### 7.3 Refusal（拒绝面）

`KNOWN`（来源：上游 `docs/REFUSALS.md`，由 `scripts/refusal-surface/refusal_surface.py` 从代码的构造点生成）

| 类别 | variant 数 | 构造点 | basis 分布 |
|---|---|---|---|
| translator / 前端拒绝（`Unsupported`，带 `Feature` 与 `Needs`） | 125 | 125 全部有构造点 | device 48、ours 54、未声明 23 |
| runtime gap（`Error::NotImplemented(RuntimeGap)`） | 70 | 70 | ours 70 |
| Apple-only（`Error::AppleOnly`） | 5 | 5 | 未声明 5 |
| binder 在设备限额上的拒绝（`BindError`） | 9 | 9 | device 9 |
| 翻译上限（`Error::LimitExceeded(Limit)`） | 14 | 14 | ours 14 |
| rate map 编译层不编译的（`Error::RateMap(UnpinnedCompile)`） | 5 | 5 | 未声明 5 |
| 翻译期限（`Error::Budget`） | 1 | 1 | ours 1 |
| "调用做错了什么"（`Error::Metal(MetalError)` 的 `Problem`） | 64 | 64 | metal-measured 20、metal-documented 3、metal-takes 5、ours 11、unknown 8、delegated 17 |
| 同上的细分 problem 枚举 | 164 | 149 | metal-measured 57、metal-documented 27、metal-takes 23、ours 31、unknown 26 |

`REFUSALS.md` 的三个列对本项目特别有用：

- **Where**：拒绝的设备条件。`NotImplemented` / `NotRepresentable` 在**任何**设备上都拒绝；`needs` 列出设备缺的 Vulkan feature / 扩展 / 属性 / 限额。本项目据此区分"Lavapipe 的问题"与"上游的问题"。
- **Basis**：为什么相信这个输入必须被拒绝。`metal-takes` 尤其重要：它表示**纯 Metal 接受该输入，所以这个拒绝越过了 Metal** —— 这是上游自己记录的开放缺陷，共 5 + 23 = 28 条。本项目的能力报告必须把这些点标为"比 Metal 严格"。
- **Reach**：谁会碰到。`system`（guest 的 CoreAnimation / CoreImage / VideoToolbox 可能碰到）、`app`、`rare`、`none`。`system` 的条目是本项目的优先级排序依据：translator 拒绝里有 6 条、runtime gap 里有 1 条标 `system`。

本项目的要求：

1. 每个被拒绝的调用都要落日志，记录 variant、`feature`、`needs`；
2. capability 查询在返回 false 时必须能回答"缺什么"（把 `Unsupported::needs` 转成稳定 wire 值）；
3. 把 `REFUSALS.md` 中 reach = `system` 的条目列成一张待办表，与 `60-CAPABILITY-MATRIX.md` §5 的 WindowServer 最小集对照；
4. `Error::Unproven` 必须按上游建议处理：**停止 guest 并命名问题**，不得猜测 Metal 的答案。

### 7.4 其他可观测项

| 项 | 用途 |
|---|---|
| `CommandBuffer::execution_report` | 翻译后的着色器在运行中报告的事实（如 resident set miss）。**这是运行事实，不是错误**，只能在命令缓冲完成后读 |
| `CommandBuffer::executions`（需 `record_executions`） | 每个 dispatch / draw 实际跑了哪个管线 |
| `ShaderCacheStatistics`、`WarmStatistics` | 缓存命中与预热结果 |
| `DriverFact`、`driver_defects`（`DeviceProperties` 字段） | runtime 已知的该驱动缺陷集合。**Lavapipe 的条目必须进 capability manifest** |
| `Exactness` | 某条路径是否精确 |
| `PrivateProperties` / `PrivateAnswer` / `PrivateFlag` / `PrivateCount` | Apple 私有属性的已测答案，其余由本项目补 |

### 7.5 能力报告的生成规则

本项目的 capability manifest 必须是**生成物**，不是手写文档。生成输入：

1. `DeviceProperties` 全字段快照；
2. `Device::family_blockers` 对全部 20 个 `GpuFamily` 的结果；
3. `Device::pixel_format_capabilities` 对全部 301 个 `PixelFormat` 的结果；
4. `Device::enables_extension` 对 §6.2 全部项的结果；
5. 一次完整测试套（`80-TEST-HARNESS.md`）中累积的 degradation code 集合、`WorkCounts` 终值、refusal 命中集合；
6. 组件版本：guest build（25G325）、metal2vulkan commit SHA + 本地补丁哈希、Mesa 版本、LLVM 版本、loader 版本。

只有在第 5 项中实际跑过并通过的能力才可标 `TESTED` 并进入发布 profile（`00-OVERVIEW.md` §7、`CAPABILITY_PROFILES.md` §5）。

---

## 8. 像素格式全量对应表

### 8.1 映射机制

`KNOWN`（来源：上游 `crates/metal2vulkan/src/metal/format/mod.rs` 模块文档与 `make_repr`）

1. 每个 `MTLPixelFormat` 有一份**固定有序的候选表**，候选只由该格式的**位布局**决定，**从不看设备名**。
2. `vk_format(pf, usages, profile)` 返回第一个对所请求的全部 `FormatUsage` 都合法、且设备 profile 的 format 表支持的候选；都不满足时返回类型化拒绝，逐候选说明缺什么。
3. 每个候选对它接受的 usage 都是**精确**的，唯一例外是 `FormatEmulation::DepthWidened`（会被报告，由调用方决定）。
4. Metal 的 packed 格式**从最低位命名**（`B5G6R5Unorm` 的 blue 在第 0–4 位），Vulkan 的 packed 格式**从最高位命名**，所以两者按布局配对（`B5G6R5Unorm` ↔ `R5G6B5_UNORM_PACK16`）。
5. 候选的 Vulkan format 枚举值若由某个核心版本或扩展定义（`A8_UNORM`、ASTC HDR 与 PVRTC 的 block），只有在 profile 暴露该值时可用；`Device::new` 只把已暴露的格式留在 profile 表里，拒绝信息会指明"哪个版本或扩展会暴露它"。

**本表第二列给出第一候选**（即"直接形式"）。回退候选与它们的 `FormatEmulation`（`AlphaInRed`、`StencilInCombined`、`DepthInCombined`、`DepthWidened` 等）列在 §8.3。

**权威答案在设备上**：`Device::pixel_format_capabilities(format)` 返回该格式在**当前设备**上的 Apple 能力集（Filter / Write / Color / Blend / MSAA / Resolve / Sparse / Atomic 等）。本表的 Lavapipe 列是**源码推断**，必须用这个调用在目标 guest 上逐格式实测替换（`60-CAPABILITY-MATRIX.md` C-06）。

Lavapipe 列取值含义：

| 取值 | 含义 |
|---|---|
| `核心·预期有` | Vulkan 1.0 核心格式，llvmpipe 的 format 表预期覆盖。**usage 维度（filter / storage / attachment / blend / MSAA）仍需实测** |
| `有（能力位已声明）` | Lavapipe 的 feature 或扩展显式声明（如 `textureCompressionBC`） |
| `需扩展暴露·Lavapipe 有` | 枚举值由扩展/较新核心定义，而 Lavapipe 提供该扩展 |
| `缺` | Lavapipe 明确不提供 |
| `待实测` | 可选格式，必须实测 |

### 8.2 全量表

#### 8.2.1 单通道与双通道

| MTLPixelFormat | raw | VkFormat（第一候选） | Lavapipe |
|---|---|---|---|
| `A8Unorm` | 1 | `A8_UNORM` | 需扩展暴露·Lavapipe 有（`maintenance5`） |
| `R8Unorm` | 10 | `R8_UNORM` | 核心·预期有 |
| `R8Unorm_sRGB` | 11 | `R8_SRGB` | 核心·预期有 |
| `R8Snorm` | 12 | `R8_SNORM` | 核心·预期有 |
| `R8Uint` | 13 | `R8_UINT` | 核心·预期有 |
| `R8Sint` | 14 | `R8_SINT` | 核心·预期有 |
| `R16Unorm` | 20 | `R16_UNORM` | 核心·预期有 |
| `R16Snorm` | 22 | `R16_SNORM` | 核心·预期有 |
| `R16Uint` | 23 | `R16_UINT` | 核心·预期有 |
| `R16Sint` | 24 | `R16_SINT` | 核心·预期有 |
| `R16Float` | 25 | `R16_SFLOAT` | 核心·预期有 |
| `R32Uint` | 53 | `R32_UINT` | 核心·预期有 |
| `R32Sint` | 54 | `R32_SINT` | 核心·预期有 |
| `R32Float` | 55 | `R32_SFLOAT` | 核心·预期有（线性过滤需 `supports32BitFloatFiltering` 实测） |
| `RG8Unorm` | 30 | `R8G8_UNORM` | 核心·预期有 |
| `RG8Unorm_sRGB` | 31 | `R8G8_SRGB` | 核心·预期有 |
| `RG8Snorm` | 32 | `R8G8_SNORM` | 核心·预期有 |
| `RG8Uint` | 33 | `R8G8_UINT` | 核心·预期有 |
| `RG8Sint` | 34 | `R8G8_SINT` | 核心·预期有 |
| `RG16Unorm` | 60 | `R16G16_UNORM` | 核心·预期有 |
| `RG16Snorm` | 62 | `R16G16_SNORM` | 核心·预期有 |
| `RG16Uint` | 63 | `R16G16_UINT` | 核心·预期有 |
| `RG16Sint` | 64 | `R16G16_SINT` | 核心·预期有 |
| `RG16Float` | 65 | `R16G16_SFLOAT` | 核心·预期有 |
| `RG32Uint` | 103 | `R32G32_UINT` | 核心·预期有 |
| `RG32Sint` | 104 | `R32G32_SINT` | 核心·预期有 |
| `RG32Float` | 105 | `R32G32_SFLOAT` | 核心·预期有 |

#### 8.2.2 四通道

| MTLPixelFormat | raw | VkFormat | Lavapipe |
|---|---|---|---|
| `RGBA8Unorm` | 70 | `R8G8B8A8_UNORM` | 核心·预期有 |
| `RGBA8Unorm_sRGB` | 71 | `R8G8B8A8_SRGB` | 核心·预期有 |
| `RGBA8Snorm` | 72 | `R8G8B8A8_SNORM` | 核心·预期有 |
| `RGBA8Uint` | 73 | `R8G8B8A8_UINT` | 核心·预期有（MSAA 仅 1 采样，§2.3） |
| `RGBA8Sint` | 74 | `R8G8B8A8_SINT` | 核心·预期有（同上） |
| `BGRA8Unorm` | 80 | `B8G8R8A8_UNORM` | 核心·预期有 —— **合成主格式** |
| `BGRA8Unorm_sRGB` | 81 | `B8G8R8A8_SRGB` | 核心·预期有 |
| `ARGB8Unorm` | 84 | `R8G8B8A8_UNORM` + swizzle | 核心·预期有（字节序经 view 的 component mapping 呈现） |
| `RGBA16Unorm` | 110 | `R16G16B16A16_UNORM` | 核心·预期有 |
| `RGBA16Snorm` | 112 | `R16G16B16A16_SNORM` | 核心·预期有 |
| `RGBA16Uint` | 113 | `R16G16B16A16_UINT` | 核心·预期有 |
| `RGBA16Sint` | 114 | `R16G16B16A16_SINT` | 核心·预期有 |
| `RGBA16Float` | 115 | `R16G16B16A16_SFLOAT` | 核心·预期有 —— **WindowServer 的 scanout 纹理格式** |
| `RGBA32Uint` | 123 | `R32G32B32A32_UINT` | 核心·预期有 |
| `RGBA32Sint` | 124 | `R32G32B32A32_SINT` | 核心·预期有 |
| `RGBA32Float` | 125 | `R32G32B32A32_SFLOAT` | 核心·预期有 |

#### 8.2.3 Packed

| MTLPixelFormat | raw | VkFormat | Lavapipe |
|---|---|---|---|
| `B5G6R5Unorm` | 40 | `R5G6B5_UNORM_PACK16` | 核心·预期有 |
| `A1BGR5Unorm` | 41 | `R5G5B5A1_UNORM_PACK16` | 核心·预期有 |
| `ABGR4Unorm` | 42 | `R4G4B4A4_UNORM_PACK16` | 核心·预期有 |
| `BGRA4Unorm` | 44 | `A4R4G4B4_UNORM_PACK16` | 需扩展暴露（`VK_EXT_4444_formats` 或 1.3 核心）·**待实测** |
| `BGR5A1Unorm` | 43 | `A1R5G5B5_UNORM_PACK16` | 核心·预期有 |
| `RGB10A2Unorm` | 90 | `A2B10G10R10_UNORM_PACK32` | 核心·预期有 |
| `RGB10A2Uint` | 91 | `A2B10G10R10_UINT_PACK32` | 核心·预期有 |
| `BGR10A2Unorm` | 94 | `A2R10G10B10_UNORM_PACK32` | 核心·预期有 |
| `RG11B10Float` | 92 | `B10G11R11_UFLOAT_PACK32` | 核心·预期有 |
| `RGB9E5Float` | 93 | `E5B9G9R9_UFLOAT_PACK32` | 核心·预期有 |

#### 8.2.4 XR 与扩展 sRGB（Apple 私有，shader 内编解码）

这些格式在 Vulkan 侧落到**整数**格式，由翻译后的着色器自己做编解码。

| MTLPixelFormat | raw | VkFormat | Lavapipe |
|---|---|---|---|
| `BGR10XR` | 554 | `R32_UINT` | 核心·预期有 |
| `BGR10XR_sRGB` | 555 | `R32_UINT` | 核心·预期有 |
| `BGRA10XR` | 552 | `R16G16B16A16_UINT` | 核心·预期有 |
| `BGRA10XR_sRGB` | 553 | `R16G16B16A16_UINT` | 核心·预期有 |
| `RGB10A8_2P_XR10` | 550 | `R32G32_UINT` | 核心·预期有 —— **WindowServer 登录路径的 framebuffer-fetch attachment 格式**（`60-CAPABILITY-MATRIX.md` §5.1） |
| `RGB10A8_2P_XR10_sRGB` | 551 | `R32G32_UINT` | 核心·预期有 |
| `RGB10A2Unorm_sRGB` | 586 | `R32_UINT` | 核心·预期有 |
| `R10Unorm_X6` | 576 | `R16_UINT` | 核心·预期有 |
| `R10Unorm_X6_sRGB` | 577 | `R16_UINT` | 核心·预期有 |
| `RG10Unorm_X12` | 578 | `R16G16_UINT` | 核心·预期有 |
| `RG10Unorm_X12_sRGB` | 579 | `R16G16_UINT` | 核心·预期有 |
| `RGBA16FloatXR` | 556 | **无候选（NotImplemented）** | — |

#### 8.2.5 bfloat（Apple 私有）

| MTLPixelFormat | raw | VkFormat | Lavapipe |
|---|---|---|---|
| `R16Bfloat` | 26 | `R16_UINT` | 核心·预期有 |
| `RG16Bfloat` | 66 | `R16G16_UINT` | 核心·预期有 |
| `RGBA16Bfloat` | 116 | `R16G16B16A16_UINT` | 核心·预期有 |

#### 8.2.6 RGBX（Apple 私有，alpha 位不参与）

| MTLPixelFormat | raw | VkFormat | Lavapipe |
|---|---|---|---|
| `RGBX8Unorm` | 300 | `R8G8B8A8_UNORM` | 核心·预期有 |
| `RGBX8Unorm_sRGB` | 301 | `R8G8B8A8_SRGB` | 核心·预期有 |
| `RGBX8Snorm` | 302 | `R8G8B8A8_SNORM` | 核心·预期有 |
| `RGBX8Uint` | 303 | `R8G8B8A8_UINT` | 核心·预期有 |
| `RGBX8Sint` | 304 | `R8G8B8A8_SINT` | 核心·预期有 |
| `RGBX16Uint` | 313 | `R16G16B16A16_UINT` | 核心·预期有 |
| `RGBX16Sint` | 314 | `R16G16B16A16_SINT` | 核心·预期有 |
| `RGBX16Float` | 315 | `R16G16B16A16_SFLOAT` | 核心·预期有 |
| `RGBX32Uint` | 323 | `R32G32B32A32_UINT` | 核心·预期有 |
| `RGBX32Sint` | 324 | `R32G32B32A32_SINT` | 核心·预期有 |
| `RGBX32Float` | 325 | `R32G32B32A32_SFLOAT` | 核心·预期有 |

#### 8.2.7 BC（Lavapipe `textureCompressionBC = true`）

| MTLPixelFormat | raw | VkFormat | Lavapipe |
|---|---|---|---|
| `BC1_RGBA` | 130 | `BC1_RGBA_UNORM_BLOCK` | 有（能力位已声明） |
| `BC1_RGBA_sRGB` | 131 | `BC1_RGBA_SRGB_BLOCK` | 有 |
| `BC2_RGBA` | 132 | `BC2_UNORM_BLOCK` | 有 |
| `BC2_RGBA_sRGB` | 133 | `BC2_SRGB_BLOCK` | 有 |
| `BC3_RGBA` | 134 | `BC3_UNORM_BLOCK` | 有 |
| `BC3_RGBA_sRGB` | 135 | `BC3_SRGB_BLOCK` | 有 |
| `BC4_RUnorm` | 140 | `BC4_UNORM_BLOCK` | 有 |
| `BC4_RSnorm` | 141 | `BC4_SNORM_BLOCK` | 有 |
| `BC5_RGUnorm` | 142 | `BC5_UNORM_BLOCK` | 有 |
| `BC5_RGSnorm` | 143 | `BC5_SNORM_BLOCK` | 有 |
| `BC6H_RGBFloat` | 150 | `BC6H_SFLOAT_BLOCK` | 有（上游记录 Lavapipe 的 BC6H 有精度差异，属 `Precision` 降级） |
| `BC6H_RGBUfloat` | 151 | `BC6H_UFLOAT_BLOCK` | 有（同上） |
| `BC7_RGBAUnorm` | 152 | `BC7_UNORM_BLOCK` | 有 |
| `BC7_RGBAUnorm_sRGB` | 153 | `BC7_SRGB_BLOCK` | 有 |

#### 8.2.8 PVRTC（已弃用）

| MTLPixelFormat | raw | VkFormat | Lavapipe |
|---|---|---|---|
| `PVRTC_RGBA_2BPP` | 164 | `PVRTC1_2BPP_UNORM_BLOCK_IMG` | **缺**（需 `VK_IMG_format_pvrtc`） |
| `PVRTC_RGBA_2BPP_sRGB` | 165 | `PVRTC1_2BPP_SRGB_BLOCK_IMG` | 缺 |
| `PVRTC_RGBA_4BPP` | 166 | `PVRTC1_4BPP_UNORM_BLOCK_IMG` | 缺 |
| `PVRTC_RGBA_4BPP_sRGB` | 167 | `PVRTC1_4BPP_SRGB_BLOCK_IMG` | 缺 |
| `PVRTC_RGB_2BPP` | 160 | `R8G8B8A8_UNORM`（解码） | 核心·预期有 |
| `PVRTC_RGB_4BPP` | 162 | `R8G8B8A8_UNORM`（解码） | 核心·预期有 |
| `PVRTC_RGB_2BPP_sRGB` | 161 | `R8G8B8A8_SRGB`（解码） | 核心·预期有 |
| `PVRTC_RGB_4BPP_sRGB` | 163 | `R8G8B8A8_SRGB`（解码） | 核心·预期有 |

#### 8.2.9 ETC2 / EAC（Lavapipe `textureCompressionETC2 = true`）

| MTLPixelFormat | raw | VkFormat | Lavapipe |
|---|---|---|---|
| `EAC_R11Unorm` | 170 | `EAC_R11_UNORM_BLOCK` | 有 |
| `EAC_R11Snorm` | 172 | `EAC_R11_SNORM_BLOCK` | 有 |
| `EAC_RG11Unorm` | 174 | `EAC_R11G11_UNORM_BLOCK` | 有 |
| `EAC_RG11Snorm` | 176 | `EAC_R11G11_SNORM_BLOCK` | 有 |
| `EAC_RGBA8` | 178 | `ETC2_R8G8B8A8_UNORM_BLOCK` | 有 |
| `EAC_RGBA8_sRGB` | 179 | `ETC2_R8G8B8A8_SRGB_BLOCK` | 有 |
| `ETC2_RGB8` | 180 | `ETC2_R8G8B8_UNORM_BLOCK` | 有 |
| `ETC2_RGB8_sRGB` | 181 | `ETC2_R8G8B8_SRGB_BLOCK` | 有 |
| `ETC2_RGB8A1` | 182 | `ETC2_R8G8B8A1_UNORM_BLOCK` | 有 |
| `ETC2_RGB8A1_sRGB` | 183 | `ETC2_R8G8B8A1_SRGB_BLOCK` | 有 |

#### 8.2.10 ASTC

Vulkan 的 ASTC block 与 Metal 的 footprint 一一对应，命名规则：`ASTC_<W>X<H>_{SRGB,UNORM,SFLOAT}_BLOCK`。

| Metal 族 | raw 范围 | VkFormat 族 | Lavapipe |
|---|---|---|---|
| `ASTC_<f>_sRGB`（4x4, 5x4, 5x5, 6x5, 6x6, 8x5, 8x6, 8x8, 10x5, 10x6, 10x8, 10x10, 12x10, 12x12） | 186–200 | `ASTC_<f>_SRGB_BLOCK` | 有（`textureCompressionASTC_LDR`） |
| `ASTC_<f>_LDR`（同 14 个 footprint） | 204–218 | `ASTC_<f>_UNORM_BLOCK` | 有 |
| `ASTC_<f>_HDR`（同 14 个 footprint） | 222–236 | `ASTC_<f>_SFLOAT_BLOCK` | **缺**（`textureCompressionASTC_HDR = VK_FALSE`） |
| `ASTC_4x2_{sRGB,LDR,HDR}` | 185 / 203 / 221 | **无**（Vulkan 无该 block） | 缺 |
| `ASTC_8x4_{sRGB,LDR,HDR}` | 191 / 209 / 227 | **无** | 缺 |

逐个 footprint 的 raw 值（sRGB / LDR / HDR）：4x4 = 186/204/222，5x4 = 187/205/223，5x5 = 188/206/224，6x5 = 189/207/225，6x6 = 190/208/226，8x5 = 192/210/228，8x6 = 193/211/229，8x8 = 194/212/230，10x5 = 195/213/231，10x6 = 196/214/232，10x8 = 197/215/233，10x10 = 198/216/234，12x10 = 199/217/235，12x12 = 200/218/236。

#### 8.2.11 4:2:2 打包（单 plane）

| MTLPixelFormat | raw | VkFormat | Lavapipe |
|---|---|---|---|
| `GBGR422` | 240 | `R8G8B8A8_UNORM` + `FormatEmulation::Decoded`（上游在 shader 内解 chroma） | 核心·预期有 |
| `BGRG422` | 241 | 同上 | 核心·预期有 |

#### 8.2.12 两 plane YCbCr / RGB 族

上游用 `two_plane_ycbcr!()` 统一处理这一族（约 100 个取值，覆盖 `YCBCR{8,10,12}_{420,422,444}_2P[_PACKED][_sRGB|_PQ|_HLG|_XR]` 与 `RGB{8,10}_{420,422,444}_2P[_PACKED]`）。

| 项 | 内容 |
|---|---|
| 表示方式 | `FormatEmulation::YCbCr`：保存一张**Metal 所读 texel 的 image**，在命令缓冲首次使用且 plane 有变化时从 plane 转换得到 |
| 原地优化 | 统一内存设备上，若函数**只采样** `YCBCR8_420_2P` 或 `YCBCR10_420_2P`，则直接读 plane 的码值并在 shader 内转换（计数 `ycbcr_textures_in_place`、`ycbcr_planes_bound`） |
| 可写性 | 只允许采样；`ycbcr_writes_stored` 列出的少数可写；`ycbcr_renders` 列出的可作为 render target（`FormatEmulation::YCbCrRendered`，attachment 用 `R32G32B32A32_SFLOAT`） |
| packed 10 位的 pass | `ycbcr_pass_refused` 列出的：管线可建，pass 被拒绝（`FormatEmulation::YCbCrPassRefused`） |
| Lavapipe | `samplerYcbcrConversion = true`、`VK_EXT_ycbcr_2plane_444_formats = true`、`ycbcrImageArrays = true`、`samplerYcbcrConversionCount = 3` → **有落点** |
| 本项目 | 适配。**RenderBox 在 26.6.2 guest 上实测对 `'b3a8'` surface 建过两 plane 纹理**，这条路径不是可选项 |

逐取值清单（raw）：`YCBCR8_420_2P` 500、`YCBCR8_422_2P` 502、`YCBCR8_444_2P` 503、`YCBCR10_420_2P` 505、`YCBCR10_422_2P` 506、`YCBCR10_444_2P` 507、各 `_PACKED` 508–510、各 `_sRGB` 520–530、`RGB8_420_2P` 540–542、`RGB10_*_2P` 543–548、`_PQ` 564–569、12 位族 570–585、`_XR` 591–602、`_HLG` 607–620。1 plane 族（`YCBCR8_422_1P` 501、`YCBCR10_444_1P` 504 等）与 `RGB10A8_2P` 系（624–627）、`BGRA10*` 系（628–641）、`R10*`/`R12*`/`RG10*`/`RG12*` 系（588–589、603–606、621–622、642–649）、`RGB10A8Uint2P` 650 属 §8.2.14（上游不持有）。

#### 8.2.13 Depth / Stencil

| MTLPixelFormat | raw | VkFormat（第一候选） | 回退候选 | Lavapipe |
|---|---|---|---|---|
| `Depth16Unorm` | 250 | `D16_UNORM` | 无 | 核心·预期有 |
| `Depth32Float` | 252 | `D32_SFLOAT` | `D32_SFLOAT_S8_UINT` + `DepthInCombined` | 核心·预期有 |
| `Stencil8` | 253 | `S8_UINT` | `D32_SFLOAT_S8_UINT` 或 `D24_UNORM_S8_UINT` + `StencilInCombined` | 待实测（`S8_UINT` 是可选格式） |
| `Depth24Unorm_Stencil8` | 255 | `D24_UNORM_S8_UINT` | `D32_SFLOAT_S8_UINT` + **`DepthWidened`（降级，会被报告）** | 待实测 |
| `Depth32Float_Stencil8` | 260 | `D32_SFLOAT_S8_UINT` | 无 | 核心·预期有 |
| `X32_Stencil8` | 261 | `D32_SFLOAT_S8_UINT`（stencil 面视图） | 无 | 同上 |
| `X24_Stencil8` | 262 | `D24_UNORM_S8_UINT`（stencil 面视图） | `D32_SFLOAT_S8_UINT` + `StencilInCombined` | 待实测 |
| `AnyDepth` | 651 | **无候选（NotImplemented）** | — | — |
| `AnyStencil` | 652 | **无候选（NotImplemented）** | — | — |

**Lavapipe 的 depth/stencil resolve 只有 SAMPLE_ZERO**（§6.2 与 `60-CAPABILITY-MATRIX.md` §2.3），MSAA depth/stencil 的 Min/Max 滤波必须走上游的替代 pass。

#### 8.2.14 无候选的格式（`Repr::NotImplemented`）

这些格式 `MTLPixelFormat` 有取值，上游**不持有**表示（`formats_named_not_held!()` 等三个分组），调用会得到 `Error::Unsupported(Format)`：

| 组 | 取值 |
|---|---|
| 三通道格式 | `RGB8Unorm` 45、`RGB8Snorm` 46、`RGB8Uint` 47、`RGB8Sint` 48、`RGB16Unorm` 95、`RGB16Snorm` 96、`RGB16Uint` 97、`RGB16Sint` 98、`RGB16Float` 99、`RGB16Bfloat` 100、`RGB32Uint` 120、`RGB32Sint` 121、`RGB32Float` 122 |
| ASTC 无 Vulkan block 的 footprint | 4x2 与 8x4 的 sRGB/LDR/HDR 六个（185、191、203、209、221、227） |
| IOSurface plane 专属 | `RGBA16FloatXR` 556 |
| 占位值 | `Invalid` 0、`Unspecialized` 263（按 `InvalidDescriptor` 拒绝）、`AnyDepth` 651、`AnyStencil` 652 |
| 1 plane YCbCr 族 | `YCBCR8_422_1P` 501、`YCBCR10_444_1P` 504、`YCBCR8_422_1P_sRGB` 521、`YCBCR10_444_1P_sRGB` 524、`YCBCRA8_444_1P` 560、`YCBCR8_422_1P_REV` 562、`YCBCR10_444_1P_PQ` 563、`YCBCR10_444_1P_XR` 590、`YCBCR10_444_1P_HLG` 607 |
| 10/12 位单双通道私有族 | `R10Unorm_PACKED` 588、`RG10Unorm_PACKED` 589、`R12Unorm_X4` 603、`R12Unorm_X4_PQ` 604、`RG12Unorm_X8` 605、`R10Unorm_X6_PQ` 606、`R10Unorm_X6_HLG` 621、`R12Unorm_X4_HLG` 622、`R10Uint_X6` 642、`R10Uint_PACKED` 643、`RG10Uint_X12` 644、`RG10Uint_PACKED` 645、`R12Uint_X4` 646、`R12Uint_PACKED` 647、`RG12Uint_X8` 648、`RG12Uint_PACKED` 649 |
| PQ/HLG 的 10 位 RGB | `RGB10A2Unorm_PQ` 587、`RGB10A2Unorm_HLG` 623 |
| `RGB10A8_2P` 系（非 XR） | 624、625、626、627 |
| `BGR10A2` 的 sRGB/PQ | 628、629 |
| `BGRA10*` 系 | 630–641 |
| `RGB10A8Uint2P` | 650 |

**本项目的处置**：第一版全部报 false / 返回确定错误。要补哪些，由 `60-CAPABILITY-MATRIX.md` C-07（系统实际用到哪些格式的 trace）决定，而不是按清单顺序补。

### 8.3 `FormatEmulation` 全集

`KNOWN`（来源：上游 `format/mod.rs` 的 `FormatEmulation` 枚举与 `admits` 实现）

| 取值 | 含义 | 是否精确 |
|---|---|---|
| `Direct` | image 就是该 Vulkan format，identity component mapping | 精确 |
| `SwizzledView` | 经 view 的 component mapping 呈现 Metal 的通道（需 `imageViewFormatSwizzle`，portability subset 可能扣留） | 精确 |
| `AlphaInRed` | `A8Unorm` 在无 `A8_UNORM` 的设备上落到 `R8_UNORM`，alpha 在 red | 精确 |
| `Decoded` | 在 shader 内解码（4:2:2 打包、PVRTC RGB 形式） | 精确 |
| `DepthInCombined` / `StencilInCombined` | 用 combined depth-stencil 格式承载单一面 | 精确 |
| `DepthWidened` | `D24_UNORM_S8_UINT` 落到 `D32_SFLOAT_S8_UINT` | **不精确，会被报告** |
| `YCbCr` | 两 plane YCbCr：保存转换后的 image，只许采样 | 精确（滤波在原地路径下为 Metal 的） |
| `YCbCrRendered` | 可渲染的两 plane YCbCr：attachment 用 `R32G32B32A32_SFLOAT`，store 由 encode kernel 做 | 精确（仅对 `ycbcr_renders` 列出的） |
| `YCbCrPassRefused` | packed 10 位两 plane：管线可建，pass 拒绝 | — |

### 8.4 本项目的格式表生成要求

**禁止手写维护本表。** 实现要求：

1. 启动自检中对全部 301 个 `PixelFormat` 调 `Device::pixel_format_capabilities`，把结果（Apple 的能力位集合）落盘；
2. 对每个格式 × 每个 `FormatUsage` 调 `metal2vulkan::metal::format::vk_format`，记录第一候选、`FormatEmulation` 与拒绝原因；
3. 用这两份数据生成本项目的 capability manifest 格式节；
4. 把生成结果与本表 diff，差异进 `90-EVIDENCE-INDEX.md`。本表是**源码推断的预期值**，实测值优先。

---

## 9. 接入验收

扩展 `METAL2VULKAN_INTEGRATION.md` §10，加上本文的要求。全部通过才算边界 ② 完成。

### 9.1 隔离性

1. 本项目没有调用旧 `compiler/air.rs`，没有调用旧 Gallium ABI（`deprecated/MyVirtualMTLDriver` 下的代码只作为失败样本保留）。
2. 本项目没有 metallib parser、bitcode reader、AIR metadata parser、AIR intrinsic 表、AIR canonicalizer、AIR→SPIR-V lowering、SPIR-V builder、SPIR-V 修补层。
3. 本项目没有自行推导 Metal binding 编号、descriptor binding 或 push constant。
4. 本项目没有复制上游的 Device / Queue / Encoder。
5. 产品代码没有直接调用 `metal2vulkan-air`；三个 crate 来自同一 git revision。
6. 本项目没有依赖任何 `#[doc(hidden)]` 项（§2.10）。
7. 本项目没有读取 `Error` 的消息文本做分支。

### 9.2 翻译与消费

8. 真实 metallib 由锚定 commit 编译；每个 stage 的 SPIR-V 有哈希与 verifier 结果。
9. PipelineArtifact、BindingPlan、layout、interface、requirements 被**完整**消费，指纹落盘。
10. 不支持的 AIR 返回明确错误（按 variant，不是通用失败）。
11. triangle 像素与参考结果一致。

### 9.3 设备创建（本文 §6）

12. `DeviceOptions` 与 `DevicePolicy` 的全部字段按 §6.6 固定，并进 capability manifest。
13. `kinds` 只允许 `DeviceKind::Cpu`；注入一个非 CPU 的 ICD 后，设备创建返回 `Error::NoDevice` 而**不是**回退到它。
14. `loader` 显式指向随包 loader；把随包 loader 改名后，启动失败并在日志中给出 `LoaderNotFound.tried` 的完整路径列表。
15. `VK_DRIVER_FILES` 显式指向随包 ICD manifest；清空该变量后，启动自检能检测到设备身份与预期不符并拒绝发布设备。
16. 启动自检 §6.7 的八项全部落盘。
17. 着色器缓存目录由本项目指定；目录不可写时启动失败而非静默降级。

### 9.4 可观测性（本文 §7）

18. `MessageSink` 已接入结构化日志；一次完整测试套后能导出 degradation code 集合。
19. `draws_dropped_unmade` 与 `draws_dropped_still_making` 非零时有报警，并能定位到 `CommandBuffer::dropped_draw`。
20. capability 查询返回 false 时能给出"缺什么"（`Unsupported::needs` 的稳定 wire 形式）。
21. `Error::Unproven` 的处理是停止 guest 并命名问题，不是猜答案。
22. capability manifest 是生成物，输入为 §7.5 的六项。

### 9.5 格式与家族（本文 §8、`60-CAPABILITY-MATRIX.md` §1.4）

23. `supportsFamily:` 由 `Device::family_blockers` 推出；全部 20 个家族的审计结果落盘。
24. 全部 301 个 `PixelFormat` 的 `pixel_format_capabilities` 结果落盘，并与 §8.2 diff。
25. §8.2.14 列出的格式返回确定错误，不返回"看起来成功"的默认值。

### 9.6 超时与看门狗（本文 §6.6）

26. `pipeline_creation_wait` 与 `pipeline_commit_wait` 显式设定，且与 display provider 的超时预算有文档化的关系（和值 < WindowServer 的容忍窗口）。
27. 管线预热链路（`pipeline_records` → 持久化 → `warm` → `warm_statistics`）端到端通过，重启后同一 descriptor 的创建命中缓存。
28. 死锁等待返回确定错误，不挂住调用方。

---

## 10. 证据来源

### 10.1 上游（metal2vulkan，commit `219f01365dc4c8eb346816c405b5b17403793764`）

| 路径 | 本文用到的内容 |
|---|---|
| `crates/metal2vulkan-runtime/src/lib.rs` | 公开符号全集（§2 的对象清单逐条出自此处的 `pub use` 列表），`#[doc(hidden)]` 标记 |
| `crates/metal2vulkan-runtime/README.md` | 设备创建（`DeviceOptions` 全字段、loader 搜索顺序、`registry_ids_with` / `with_registry_id` / `system_default_identity_with`）、内存模型、runtime 扩展全集、错误表、降级通告、GPU family、范围外清单、管线等待与 guest FIFO 的关系、`Device::warm` 的安全性质 |
| `docs/RUNTIME-PORTING.md` | selector ↔ 方法的命名规则（"Conventions"）、逐对象对照表（§3.3 的索引）、"Composed from runtime calls"（§3.2 的组合项）、"Not the runtime's"（§4 的清单） |
| `docs/METAL-COVERAGE.md` | 覆盖总量与按 header 的分布；`MTLDrawable` 全族的 out-of-scope 理由 |
| `docs/REFUSALS.md` | §7.3 的拒绝面统计、列语义（Where / Basis / Reach）、`metal-takes` 的含义 |
| `docs/ARCHITECTURE.md` | §1 调用链的翻译侧阶段划分 |
| `docs/FAST-PATHS.md` | 精确性开关；macOS 26 最大 CoreAnimation 着色器规模 |
| `docs/HOWTO.md` | 着色器缓存、host 内存被驱动拒绝时的退路、拷贝 host buffer |
| `docs/VALIDATION.md` | 验证梯度 |
| `crates/metal2vulkan-runtime/src/degradation.rs` | §7.1 的分类定义与 kind 规模；`shared-present-queue` 等具体 kind 的文档 |
| `crates/metal2vulkan-runtime/src/work_counts.rs` | §7.2 的计数项 |
| `crates/metal2vulkan-runtime/src/capabilities.rs` | `DeviceProperties` 字段、`gpu_core_count` 的来源与 Lavapipe 的缺失 |
| `crates/metal2vulkan-runtime/src/families/mod.rs` | `GpuFamily` 全量与 raw 值、逐行审计机制、`Refusal` 枚举 |
| `crates/metal2vulkan-runtime/src/error.rs` | §2.9 的错误 variant 全集 |
| `crates/metal2vulkan/src/metal/format/mod.rs` | §8 的候选机制、`FormatEmulation` 全集、`make_repr` 的逐格式候选、三个未持有分组 |
| `crates/metal2vulkan/src/metal/generated.rs` | `PixelFormat` 全量 301 个取值与 raw 值 |
| `crates/metal2vulkan/src/device/subgroup.rs` | simdgroup 的 `Tier` 策略（本文 §6 的性能约束背景） |
| `crates/metal2vulkan-runtime/examples/*.rs` | 五个公开 API 用例（compute dispatch、render to texture、ICB、heap placement、adopted buffer） |

### 10.2 Mesa / Lavapipe

- [`src/gallium/frontends/lavapipe/lvp_device.c`](https://gitlab.freedesktop.org/mesa/mesa/-/blob/main/src/gallium/frontends/lavapipe/lvp_device.c)：`lvp_get_features`（feature 全表）、`lvp_instance_extensions_supported`、`lvp_device_extensions_supported`、`lvp_get_properties`（限额与扩展属性）。§6.2 与 §8 的 Lavapipe 列出自此处。
- [Mesa 26.0.5 release notes](https://docs.mesa3d.org/relnotes/26.0.5.html)：Mesa 26.x 的 Vulkan API 版本。
- Vulkan loader 的 `VK_DRIVER_FILES` / `VK_ICD_FILENAMES` / `VK_ADD_DRIVER_FILES` / `VK_LOADER_DRIVERS_SELECT` 语义见 Khronos 的 loader 文档（`LoaderInterfaceArchitecture.md`）。本文对取值的选择为 `INFERRED`。

### 10.3 本项目

- `docs/spec/00-OVERVIEW.md`：目标、三条边界、组件划分、证据规则。
- `docs/spec/60-CAPABILITY-MATRIX.md`：全量能力矩阵；§2 的 Lavapipe 基线事实、§4 的天花板、§5 的 WindowServer 最小集。本文多处引用。
- `docs/METAL2VULKAN_INTEGRATION.md`：上游接入合同、禁止的重复实现、补缺规则、vendor 方式、许可证边界。
- `analysis/spec-work/bridge-runtime-contract.md`：既有的 ObjC ↔ runtime 映射调查（注意其中标 `BLOCKED` 的项按 `00-OVERVIEW.md` §4.4 与 §4.5 重新判定）。

引用 Apple 与第三方文档的段落均为转述，未连续摘录超过 30 词。**内容已转述以符合许可限制。**

---

## 11. 待关闭项

| ID | 内容 | 标签 | 关闭方法 |
|---|---|---|---|
| R-01 | Lavapipe 在 macOS x86_64 上的实际 `apiVersion`、`deviceName`、format feature 全表 | `BLOCKED` | `70-BUILD-PACKAGE.md` Gate 1 后跑 §6.7 自检 |
| R-02 | `VK_DRIVER_FILES` 等环境变量在 helper 的 launchd 启动环境下是否生效 | `BLOCKED` | Gate 1 |
| R-03 | `MACOS_RELEASE`（上游按 macOS 27.0.1 的规则回答格式/堆布局/私有属性）与本项目 26.7.2 基线的逐项差异 | `BLOCKED` | 对 `heap_texture_size_and_align`、`pixel_format_capabilities`、`PrivateProperties` 三组答案做 26 vs 27 比对；需要一台 26 Intel 参照机 |
| R-04 | `Stencil8`、`D24_UNORM_S8_UINT`、`A4R4G4B4_UNORM_PACK16` 在 Lavapipe 上的实际支持 | `BLOCKED` | §8.4 的格式表生成 |
| R-05 | `pipeline_creation_wait` / `pipeline_commit_wait` 的合适取值 | `INFERRED` | 用 macOS 26 最大的 CoreAnimation 着色器在目标 guest 上实测编译耗时 |
| R-06 | Lavapipe 的 `driver_defects` 集合（上游已知该驱动的哪些缺陷） | `BLOCKED` | 启动自检落盘 `DeviceProperties::driver_defects` |
| R-07 | ObjC 侧每个 selector 的 x86_64 encoding 与本文映射表的对应 | `BLOCKED` | `21-OBJC-OBJECT-FAMILY.md` 负责；本文只给语义契约 |
