# 全量能力矩阵

文档版本：1.0
基线：macOS Tahoe 26.7.2 build 25G325，**x86_64**
上游锚定：metal2vulkan `219f01365dc4c8eb346816c405b5b17403793764`（2026-10-29，`Re-pin the runtime sources at the landing tip`）
状态：有效。按 `00-OVERVIEW.md` 第 4.7 节，本文按**全量能力**编写，能力分档只用于排期与报告，不用于裁剪规格。

## 0. 本文作用与读法

本文回答一个问题：**在纯 CPU、不依赖宿主的 macOS 26 guest 上提供"全量 Metal"，到底是多少工作量，上限由谁决定。**

每个特性给四列状态，外加证据列。

| 列 | 含义 | 取值 |
|---|---|---|
| **macOS 26** | 该特性在 26.7.2 x86_64 上是否存在，以及**谁实际依赖它**。这一列最重要：它决定"必须做"与"可以不做"的分界 | `WS` WindowServer / `CA` CoreAnimation、QuartzCore / `AK` AppKit / `APP` 常规 app / `SYS` 其他系统服务（CoreImage、VideoToolbox、RenderBox） / `—` 无人依赖 / `n/a` 该版本不存在 |
| **m2v** | metal2vulkan（translator + runtime）在锚定 commit 上是否支持 | `有` / `部分` / `缺` / `拒绝` / `不做` |
| **Lavapipe** | Mesa lavapipe 在 **macOS x86_64** 构建下是否提供所需 Vulkan 机制 | `有` / `受限` / `缺` / `仅 Linux` |
| **本项目** | 由前三列推出的动作 | `无需做` / `适配` / `自行实现` / `不可行` |

证据标签沿用 `00-OVERVIEW.md` 第 7 节：`KNOWN`（源码/二进制/公开 ABI 直接证明）、`INFERRED`（合理实现选择，未实测）、`BLOCKED`（缺样本或运行证据）、`TESTED`（目标 guest 已验收）。本文**没有任何 `TESTED` 行**——目标 guest 尚未跑过。

### 0.1 三方状态的组合语义

| m2v | Lavapipe | 结论 |
|---|---|---|
| 有 | 有 | **无需做**：接上去即可，只需适配层转发 |
| 有 | 缺 | **天花板由 Lavapipe 决定**（§4.1）。上游会在设备审计时拒绝，本项目只能诚实报 false |
| 缺 | 有 | **天花板由 m2v 决定**（§4.2）。纯工作量，可自行实现或向上游补 |
| 缺 | 缺 | 双缺，成本最高，一般应直接报 false |
| 不做 | 有/缺 | 上游明确划出范围（IOSurface、presentation、OS 服务）→ **自行实现**，这是本项目的本体工作 |

### 0.2 上游覆盖总量（`KNOWN`）

来源：metal2vulkan `docs/METAL-COVERAGE.md`（由 `scripts/metal-coverage/coverage.py` 从 `coverage.tsv` 生成，对照 Xcode 27.0 / 27A266a 的 Metal 头文件）。

| 状态 | 项数 | 其中已弃用 |
|---|---|---|
| implemented | 958 | 36 |
| missing | 828 | 27 |
| out of scope | 349 | 5 |
| 合计 | 2135 | 68 |

implemented 中 runtime 答 635 项、translator 的值类型答 323 项。missing 按工作量：S 145、M 147、L 160、XL 376。

**读法注意**：上游这张表对照的是 **macOS 27 SDK**，本项目基线是 macOS 26.7.2。27 SDK 新增项（`MTLTexture.minLOD`、persistent kernels、`MTLTextureViewDescriptor.minLOD`）在 26 上不存在，矩阵中标 `n/a`；26 引入项（Metal 4、tensors、pipeline specialization）在 27 SDK 中仍在，可直接沿用其状态。

---

## 1. macOS 26 的 Metal 表面到底有多大

### 1.1 Metal 3 与 Metal 4 并存，不是替代

`KNOWN`（架构：与架构无关的 SDK 事实；来源：metal2vulkan `docs/METAL-COVERAGE.md` 的 header 分节）

macOS 26 的 SDK 同时提供两套头文件族：

- 旧族：`MTLDevice.h`、`MTLCommandQueue.h`、`MTLCommandBuffer.h`、`MTLRenderCommandEncoder.h`、`MTLRenderPipeline.h` …
- 新族：`MTL4CommandQueue.h`、`MTL4CommandBuffer.h`、`MTL4CommandAllocator.h`、`MTL4ArgumentTable.h`、`MTL4Compiler.h`、`MTL4RenderPipeline.h`、`MTL4MachineLearningCommandEncoder.h`、`MTLTensor.h` …

两族挂在**同一个 `MTLDevice` 上**：Metal 4 的队列由 `MTLDevice` 创建，Metal 4 不是新的设备族，也不取代 `MTLCommandQueue`。Apple 自己把 Metal 4 描述为"全新的命令结构 + 显式内存管理 + 新的资源管理方式"，定位是在既有 Metal 之上并行提供的新编码模型（[Discover Metal 4, WWDC25 session 205](https://developer.apple.com/videos/play/wwdc2025/205/)；[Apple Developer – Metal](https://developer.apple.com/metal/)）。**内容已转述以符合许可限制。**

因此 macOS 26 的 Metal API 面 = Metal 3 面（完整保留）+ Metal 4 面（新增）。上游表中 `MTL4*` 与 `MTLTensor` 合计约 **432 项**（Metal 4 命令模型 369 + ML encoding 18 + tensors 45，三者有少量重叠计入各自 header），全部为 missing 或 out of scope。

### 1.2 Metal 4 的新增对象族（全量枚举）

`KNOWN`（来源：上游 coverage 表按 header 统计；每行括号内为 missing 项数）

| Metal 4 对象族 | header | 项数 | 作用 |
|---|---|---|---|
| 命令队列与提交 | `MTL4CommandQueue.h` (22)、`MTL4CommandBuffer.h` (18)、`MTL4CommandAllocator.h` (7)、`MTL4CommitFeedback.h` (4) | 51 | 显式分配器 + 显式提交反馈，取消 `addCompletedHandler:` 式回调 |
| 编码器基类与 render | `MTL4CommandEncoder.h` (12)、`MTL4RenderCommandEncoder.h` (42)、`MTL4RenderPass.h` (18) | 72 | 新 render pass 与编码器语义 |
| compute 与 ML | `MTL4ComputeCommandEncoder.h` (32 missing + 6 oos)、`MTL4MachineLearningCommandEncoder.h` (4)、`MTL4MachineLearningPipeline.h` (14) | 56 | GPU 时间线上的 ML 推理编码 |
| 资源绑定 | `MTL4ArgumentTable.h` (15)、`MTL4BufferRange.h` (1) | 16 | argument table 取代 argument buffer 的绑定路径 |
| 管线与编译 | `MTL4Compiler.h` (29)、`MTL4CompilerTask.h` (4)、`MTL4PipelineState.h` (6)、`MTL4RenderPipeline.h` (40)、`MTL4ComputePipeline.h` (12)、`MTL4MeshRenderPipeline.h` (27)、`MTL4TileRenderPipeline.h` (10)、`MTL4LinkingDescriptor.h` (14)、`MTL4FunctionDescriptor.h` (1)、`MTL4LibraryDescriptor.h` (4)、`MTL4LibraryFunctionDescriptor.h` (3)、`MTL4SpecializedFunctionDescriptor.h` (4)、`MTL4StitchedFunctionDescriptor.h` (3)、`MTL4BinaryFunction.h` (3)、`MTL4BinaryFunctionDescriptor.h` (4) | 164 | 显式 compiler 对象 + 任务化编译 |
| 归档与序列化 | `MTL4Archive.h` (7)、`MTL4PipelineDataSetSerializer.h` (5) | 12 | 新的管线归档格式 |
| 计数器 | `MTL4Counters.h` (9) | 9 | 新计数器堆 |
| 张量 | `MTLTensor.h` (45) | 45 | ML 的一等资源类型，与 Metal 3 的 buffer/texture 并列 |
| 加速结构 | `MTL4AccelerationStructure.h` (94，全部 out of scope) | 94 | ray tracing，上游范围外 |

### 1.3 结论：本项目不实现 Metal 4

**决定：只实现 Metal 3 兼容面。Metal 4 对象族全部不实现，相关 selector 返回 nil 并让 `supportsFamily:MTLGPUFamilyMetal4`（5002）为 false。**

四条理由，按强度排序：

1. **Metal 4 的 feature 行在 Apple 的 feature set 表里只有 Apple 列，没有 Mac 列。** `KNOWN`（来源：metal2vulkan `crates/metal2vulkan-runtime/src/families/mod.rs` 模块文档；该文档引用 [Metal Feature Set Tables, 2026-05-21 版](https://developer.apple.com/metal/Metal-Feature-Set-Tables.pdf)，SHA-256 `9f31df15dd6827545702c5a0845f6e36e1889878cd0e534123bd70211e5c00a8`）。2026 版表的特性列为 Apple2…Apple10，每行注明编程模型是 "Metal 3 & 4" / "Metal 3" / "Metal 4"；**只属于 Metal 4 编程模型的行就是 `MTL4` API 本身**，而 Mac2 列来自 2023 版表，根本没有 Metal 4 行。换言之：Apple 没有为任何 Mac（非 Apple silicon）家族描述 Metal 4 能力。
2. **Metal 4 的硬件门槛在 Apple silicon。** `INFERRED`。Apple 的设备支持页是权威出处（[Support for Metal on Apple devices](https://support.apple.com/en-us/102894)）；二手汇总指出门槛为 M1 / A14 及更新（[Low End Mac, Metal 4 overview](https://lowendmac.com/2025/metal-4-an-overview/)）。**内容已转述以符合许可限制。** 本项目目标是 Intel x86_64 Mac，因此真机上 Metal 4 本来就不可用，guest 中的 Metal 客户端不会走这条路。验证方法：在目标 guest 上对任一真实设备调 `supportsFamily:5002`，并抓 `MTLDevice` 的 `supportsFamily` trace。
3. **上游零覆盖，工作量为 L/XL。** `KNOWN`。上游 coverage 表把 "Metal 4's command model" 标为 L/XL、369 项，"machine learning encoding" 标为 XL、18 项，"tensors" 标为 L、68 项（含反射侧）。`metal2vulkan-runtime` 的 family 审计里，`GpuFamily::Metal4` 只有一行 `FamilyRow::Metal4Api`，状态恒为 `RowState::Gap(RuntimeGap::Metal4Api)`。实现 Metal 4 等于自己从零写一个与现有 runtime 平行的第二套命令系统。
4. **WindowServer 与常规 app 不需要它。** `INFERRED`。macOS 26 是 Intel 平台最终版本，系统合成路径的 metallib 与管线仍是 Metal 3 形态（上游对 x86 guest 采样的 CoreAnimation / WindowServer / RenderBox 管线全部走 `MTLRenderPipelineDescriptor` 路径，见 §5）。要把这条升级为 `KNOWN`，在目标 guest 上对 `WindowServer`、`SkyLight`、`CoreAnimation`、`QuartzCore` 做一次 `MTL4*` 符号引用扫描即可（`nm -u` + dyld 缓存解包），工作量 < 1 天。

**不实现不等于可以装作不存在**：`00-OVERVIEW.md` 第 7 节与 `CAPABILITY_PROFILES.md` 第 5 节要求未实现能力返回 false 或确定错误。Metal 4 的 selector 必须真实返回 nil / `MTLGPUFamilyMetal4` 必须 false，不得用统一默认 IMP 伪造。

### 1.4 Intel Mac 上 macOS 26 的 GPU family，与本项目应声明什么

`MTLGPUFamily` 全量取值（`KNOWN`，来源：上游 `families/mod.rs` 的 `GpuFamily::raw()`，对照 macOS 27 SDK）：

| 家族 | 值 | 2026/2023 表是否有列 | 本项目应声明 | 理由 |
|---|---|---|---|---|
| `Apple1`…`Apple11` | 1001–1011 | Apple2–Apple10 有列；Apple1 按 Apple2 回答；Apple11 无任何版本的列 | **false** | Apple GPU 家族。本设备不是 Apple GPU，且 imageblock / tile shading / sparse 等 Apple 行无法满足 |
| `Mac1` | 2001 | 按 Mac2 回答（SDK 自 macOS 13 起弃用） | **true**（若 Mac2 为 true） | Metal 在真机上对 Mac1 与 Mac2 同答 |
| `Mac2` | 2002 | 2023 版表的 Mac2 列 | **目标：true** | 这是 Intel Mac 的家族。Mac2 列不含 sparse texture、不含 imageblock，正好避开 Lavapipe 在 macOS 上的 sparse 缺口（§4.1） |
| `Common1`/`2`/`3` | 3001/3002/3003 | 2023 版表的 Common 列（无 limits、无 format 列） | **目标：true** | 跨平台最小公共面，门槛低于 Mac2 |
| `MacCatalyst1`/`2` | 4001/4002 | 只有"运行在 Mac Catalyst 进程中"一行 | **false** | 本项目不在 Catalyst 进程中运行 |
| `Metal3` | 5001 | 2023 版 Metal3 特性列 + 2026 版 Apple7 的 limits 与 format | **待定，倾向 false** | Metal3 继承 Apple7 的 limits 与 pixel format 能力。这是本矩阵中最贵的一行，必须用实测决定（见下） |
| `Metal4` | 5002 | 只有 `MTL4` API 一行 | **false** | §1.3 |

`BLOCKED`：**真机 Intel Mac 在 macOS 26 上究竟答 true 的家族集合未取样。** 缺的是一台 26.7.2 Intel Mac 上 `supportsFamily:` 的全量扫描结果。取得方法：写一个 20 行的 ObjC 程序遍历 `GpuFamily::ALL` 的 20 个值打印结果，在真机或任一已跑起来的 26 Intel 安装上跑一次。在取得之前，不得把"Intel Mac 答 Metal3"当成事实使用。

**关键设计决定（`INFERRED`，强烈建议）**：本项目**不硬编码** `supportsFamily:` 的答案，而是转发 `metal2vulkan-runtime` 的 `Device::supports_family`。理由：

- 上游已经把 Apple 两版 feature set 表的**每一行**（feature / limit / pixel-format capability）编码为 `FamilyRow`，并在真实 Vulkan 设备上逐行判定 `RowState`：`Exact` / `Refused(Refusal)` / `Gap(RuntimeGap)` / `NotADeviceFeature(Framework)`。
- `Device::supports_family` 只在该家族列出的每一行都 `Exact` 时返回 true；`Device::family_blockers` 直接给出阻断行清单。
- 这正好是 `00-OVERVIEW.md` 第 7 节"模拟对象与假完成不是运行证据"的机器化实现：声明的能力由设备本身推出，而不是由文档断言。

本项目要做的是：在目标 guest 上跑一次 `family_blockers(Mac2)`、`family_blockers(Metal3)`、`family_blockers(Common3)`，把结果写进 `90-EVIDENCE-INDEX.md`，并据此决定声明哪些家族。这是 Gate 4 之后的第一件事。

---

## 2. Lavapipe 基线事实

本节是矩阵第三列的依据。全部来自 Mesa 主干源码，`KNOWN`（架构：与架构无关的驱动声明；来源：[`src/gallium/frontends/lavapipe/lvp_device.c`](https://gitlab.freedesktop.org/mesa/mesa/-/blob/main/src/gallium/frontends/lavapipe/lvp_device.c)）。

### 2.1 版本与一致性

- Lavapipe 实现 **Vulkan 1.4** API 面（Mesa 26.x 系列整体宣称 1.4；实际 `apiVersion` 由驱动决定，见 [Mesa 26.0.5 release notes](https://docs.mesa3d.org/relnotes/26.0.5.html)）。**内容已转述以符合许可限制。**
- Lavapipe **不是** conformant 实现，驱动自己在实例创建时打印非一致性警告。对本项目的含义：不能把"Vulkan 规范允许"直接当成"Lavapipe 行为正确"，每条路径都要像素级验证（`80-TEST-HARNESS.md`）。
- `metal2vulkan-runtime` 要求 **Vulkan 1.2 + `timelineSemaphore`** 作为设备下限（来源：runtime `README.md`"Depending on it"节）。Lavapipe `timelineSemaphore = true`，满足。

### 2.2 Lavapipe 在 macOS 上关键的"有"

这些是让本项目可行的前提，逐条都来自 `lvp_device.c` 的扩展表或 feature 表：

| Vulkan 机制 | Lavapipe | 对 Metal 的意义 |
|---|---|---|
| `tessellationShader` | true | Metal tessellation 有落点（但上游未建，§4.2） |
| `geometryShader` | true | 上游生成 geometry stage 的路径可用 → `[[barycentric_coord]]`、layer/viewport 选择、private primitive 的拉取形式都有路 |
| `multiview`、`multiviewGeometryShader`、`multiviewTessellationShader` | true | vertex amplification 有落点 |
| `VK_EXT_mesh_shader`（`taskShader`、`meshShader`、`meshShaderQueries`） | true | Metal mesh / object shader 有落点 |
| `descriptorIndexing` 全套 + `runtimeDescriptorArray` + 全部 `UpdateAfterBind` | true | argument buffer tier 2（bindless，纹理与 sampler 入 argument buffer）有落点 |
| `bufferDeviceAddress` | true | Metal 的 `gpuAddress` 与 argument buffer 里的 buffer 指针有落点 |
| `VK_EXT_external_memory_host` | true | **真实 IOSurface 的 no-copy 导入有落点**，是 `41-IOSURFACE-USERSPACE.md` 的基础 |
| `VK_EXT_host_image_copy`（`hostImageCopy`） | true | CPU 侧直接读写 image，省一次 staging |
| `VK_EXT_fragment_shader_interlock` + `VK_EXT_rasterization_order_attachment_access`（color/depth/stencil 三者皆 true） | true | **framebuffer fetch 与 raster order group 有落点** — WindowServer 的可编程混合不是死路（§5） |
| `VK_EXT_shader_stencil_export` | true | Metal 的 shader 写 stencil 有落点 |
| `VK_EXT_custom_border_color`、`borderColorSwizzle` | true | Metal sampler border color 有落点 |
| `samplerYcbcrConversion`、`VK_EXT_ycbcr_2plane_444_formats`、`ycbcrImageArrays` | true | 两 plane YCbCr 纹理有落点 |
| `shaderResourceMinLod` + `VK_EXT_image_view_min_lod` | true | `min_lod_clamp` 有落点 |
| `textureCompressionBC`、`ETC2`、`ASTC_LDR` | true | BC/ETC/EAC/ASTC-LDR 全系格式有落点 |
| `VK_KHR_compute_shader_derivatives`（含 `meshAndTaskShaderDerivatives`） | true | kernel 内求导有落点 |
| `VK_EXT_device_generated_commands` | true | indirect command buffer 的 GPU 侧执行有落点 |
| `VK_EXT_sample_locations` | true | 可编程 sample position 有落点（但网格受限，§2.3） |
| `shaderFloat64`、`shaderInt64`、`shaderInt16`、`shaderFloat16` | 跟随 llvmpipe caps（x86_64 上均为 true） | 64 位算术与 half 有落点 |
| `vulkanMemoryModel` + `DeviceScope` + `AvailabilityVisibilityChains` | true | `coherent(device)` 访问有落点 |
| `shaderMaximalReconvergence` | true | simdgroup 收敛语义有落点 |
| `VK_KHR_acceleration_structure` + `VK_KHR_ray_tracing_pipeline` | true（软件实现） | ray tracing 在 Lavapipe 侧**有**，但上游划为范围外（§4.2） |
| `VK_EXT_metal_surface` | 在 `VK_USE_PLATFORM_METAL_EXT` 下 true | macOS 上可建 surface；本项目走 IOSurface，不用它 |

### 2.3 Lavapipe 的硬限制（天花板来源）

| 限制 | 源码事实 | 对 Metal 的后果 |
|---|---|---|
| **sparse 全族在非 Linux 上关闭** | `sparseBinding`、`sparseResidencyBuffer`、`sparseResidencyImage2D`、`sparseResidencyImage3D`、`sparseResidencyAliased`、`shaderResourceResidency` 均为 `DETECT_OS_LINUX`；`VK_EXT_pageable_device_local_memory`、`VK_EXT_memory_priority` 同样只在 Linux 编入 | **macOS 宿主上 sparse texture / placement sparse / sparse buffer 不可行**。幸运的是 Mac2 列本来不含 sparse（上游 `families/mod.rs`：Apple2–Apple5 与 Mac2 的 format 单元格里排除 Sparse 能力），所以不阻断 Mac2 声明 |
| **subgroup 宽度远小于 32** | `minSubgroupSize = maxSubgroupSize = lp_native_vector_width / 32`（128 位向量 → 4；256 位 → 8）；`requiredSubgroupSizeStages` 只含 FRAGMENT 与 COMPUTE | Metal simdgroup 恒为 32 宽。无法 pin 32 → 上游走 `Tier::Emulated`（线性线程 `[32k, 32k+32)` 经 workgroup 内存 + barrier 模拟）或 `Tier::PartialFragment`。**正确性可保，代价是性能与额外 barrier**；`quad` 操作与 `SimdgroupMatrix` 另有拒绝路径 |
| **point 大小上界 256 < Metal 的 511** | 上游 `families::Refusal::PointSizeRange` 的文档**直接点名 lavapipe 为 256** | 大于 256 的点在设备上被 clamp，画得比 Metal 小 → 这是一个 **family 声明的阻断行**，由 Lavapipe 决定 |
| **整数格式不支持 MSAA** | `framebufferIntegerColorSampleCounts = VK_SAMPLE_COUNT_1_BIT` | uint/sint 像素格式的 `supportsTextureSampleCount:` 只能答 1 |
| **depth/stencil resolve 只有 SAMPLE_ZERO** | `supportedDepthResolveModes` / `supportedStencilResolveModes` 均为 `VK_RESOLVE_MODE_SAMPLE_ZERO_BIT` | `MTLMultisampleDepthResolveFilter` 的 Min/Max 与 stencil 的非零模式需上游的 `depth_stencil_resolve` 替代路径（手写 resolve pass），属降级 |
| **ASTC HDR 关闭** | `textureCompressionASTC_HDR = VK_FALSE` | ASTC HDR 像素格式不可行（Mac2 不列 ASTC，影响局限于 Apple 家族声明） |
| **16 位 varying 关闭** | `storageInputOutput16 = false` | stage 间 `half` 插值需 widen 到 float，精度记为降级 |
| **mesh 的 multiview 关闭、输出层上限 9** | `multiviewMeshShader = false`、`maxMeshMultiviewViewCount = 1`、`maxMeshOutputLayers = 9` | mesh + vertex amplification 组合不可行；mesh 分层渲染层数受限 |
| **`inheritedQueries = false`** | feature 表显式 false | 次级 command buffer 中继承 query 不可行 → parallel render encoder + visibility result 的组合受限 |
| **单一 graphics queue** | 上游 degradation `shared-present-queue` 的文档点名"RADV 与 lavapipe 的单一 graphics 队列" | Metal 多 `MTLCommandQueue` 并行只能在一个 `VkQueue` 上串行化；present 持锁会挡住其他队列的提交 |
| **sample location 网格 1×1、坐标上界 0.9375** | `maxSampleLocationGridSize = 1×1`、`sampleLocationCoordinateRange[1] = 0.9375f`、`sampleLocationSubPixelBits = 4` | `setSamplePositions:count:` 可用但精度与网格受限 |
| **无 `VK_KHR_fragment_shader_barycentric`** | 扩展表中不存在 `barycentric` 任何条目 | `[[barycentric_coord]]` 没有原生扩展路径；但上游的 `Barycentrics` 拒绝接受 `geometryShader` 作为替代机制，而 Lavapipe 有 geometry shader → **可行但走生成的 geometry stage，成本在性能** |
| **`gpuCoreCount` 无来源** | 上游 `capabilities.rs`：驱动未列 `VK_NV_shader_sm_builtins` / `VK_AMD_shader_core_properties*` / `VK_ARM_shader_core_builtins` 时返回 `None`，并明确把 lavapipe 列入此类 | Apple 私有 `gpuCoreCount` 必须由本项目自己给值或报缺（属 §6 的诚实报告范畴） |
| **CPU 执行速度** | 上游 `docs/FAST-PATHS.md`：macOS 26 最大的 CoreAnimation fragment 着色器为 **210,033 words**，在 RTX 5080 Laptop 驱动上编译约 1 秒 | 在 LLVM JIT 上这会显著更慢。管线创建等待策略（`pipeline_creation_wait` / `pipeline_commit_wait`，默认各 4.5 s）与 guest 的 10 s FIFO 看门狗直接冲突，必须作为一等风险管理（§7） |

---

## 3. 全量矩阵

每节末尾给该功能域的上游 header 覆盖数（implemented / missing / out of scope），来自 §0.2 的同一张表。

### 3.1 设备、枚举与能力查询

上游 `MTLDevice.h`：73 / 71 / 10。`MTLDeviceCertification.h`：0 / 0 / 3。

| 特性 | macOS 26 | m2v | Lavapipe | 本项目 | 证据 |
|---|---|---|---|---|---|
| `MTLCreateSystemDefaultDevice` / `MTLCopyAllDevices` | WS CA AK APP | 有（`Device::system_default`、`Device::all`） | 有 | 适配 | `KNOWN` runtime README "Opening a device" |
| 设备排序（discrete→integrated→virtual→CPU） | — | 有 | n/a（只有一个 CPU 设备） | 适配：必须用 `DeviceOptions::kinds` 只允许 `DeviceKind::Cpu` | `KNOWN` 同上。见 `40-RUNTIME-VULKAN.md` §6.3 |
| `registryID` | WS APP | 有（由 `deviceUUID` 折叠） | 有 | 适配；但 kext 侧的 registryID 必须与之一致 | `KNOWN` runtime `Device::registry_id`；`20-OBJC-DEVICE.md` 负责一致性 |
| `name`、`location`、`locationNumber`、`peerGroupID` | APP | 部分 | n/a | 自行实现（返回本项目设备名与单设备常量） | `INFERRED` |
| `supportsFamily:` | **WS CA AK APP** | 有（逐行审计，`family_blockers`） | 有（结果由设备推出） | 适配，**不得硬编码** | `KNOWN` §1.4 |
| `maxThreadsPerThreadgroup`、`maxThreadgroupMemoryLength` | APP | 有 | 有 | 适配 | `KNOWN` `DeviceProperties` |
| `maxBufferLength` | APP | 有 | 有（`maxBufferSize = UINT32_MAX`） | 适配 + 按协议上限夹紧 | `KNOWN` |
| `hasUnifiedMemory` | WS CA APP | 有（CPU 实现答 true） | 有 | 无需做 | `KNOWN` runtime README "The memory model" |
| `areProgrammableSamplePositionsSupported` | SYS | 有 | 受限（1×1 网格） | 适配 + 诚实降级 | `KNOWN` §2.3 |
| `areRasterOrderGroupsSupported` | WS（见 §5） | 有（映射到 `fragmentShaderPixelInterlock`） | 有 | 无需做 | `KNOWN` |
| `isDepth24Stencil8PixelFormatSupported` | APP | 有 | 有（`D24_UNORM_S8_UINT`，需查 format 表） | 适配 | `KNOWN` |
| `supports32BitFloatFiltering` | APP | 有 | 需实测 format feature | 适配 | `INFERRED` |
| `supportsTextureSampleCount:` | CA APP | 有 | 受限（整数格式只有 1） | 适配 | `KNOWN` §2.3 |
| `readWriteTextureSupport`（tier） | APP | 有 | 需实测 | 适配 | `INFERRED` |
| `argumentBuffersSupport`（tier） | APP | 有 | tier 2 有落点 | 适配 | `KNOWN` §2.2 |
| `maxArgumentBufferSamplerCount` | APP | 有 | 有 | 适配 | `KNOWN` |
| `gpuCoreCount`（SPI） | SYS | 有但答 `None` | 无来源 | 自行实现（给常量或报缺） | `KNOWN` §2.3 |
| `architecture`（`MTLArchitecture`） | APP | 缺（S） | n/a | 自行实现 | `KNOWN` coverage "device, state and resource queries" S / 54 项 |
| 设备热插拔通知（`MTLCopyAllDevicesWithObserver`） | — | 缺（M，2 项） | n/a | 不实现（单设备，永不变） | `KNOWN` |
| `MTLDeviceCertification` | — | 不做 | n/a | 不实现 | `KNOWN` out of scope |

### 3.2 命令提交

上游 `MTLCommandQueue.h`：4 / 10 / 0。`MTLCommandBuffer.h`：21 / 21 / 5。`MTLCommandEncoder.h`：2 / 6 / 0。`MTLParallelRenderCommandEncoder.h`：0 / 8 / 0。

| 特性 | macOS 26 | m2v | Lavapipe | 本项目 | 证据 |
|---|---|---|---|---|---|
| `newCommandQueue` + `commandBuffer` + `commit` + `waitUntilCompleted` | **WS CA AK APP** | 有 | 有 | 适配 | `KNOWN` runtime README 首例 |
| `addCompletedHandler:` / `addScheduledHandler:` | **WS CA APP** | 有（`Handler`） | 有 | 适配（block → `Handler`） | `KNOWN` RUNTIME-PORTING `CommandBuffer` 节 |
| command buffer 状态机与 `error`、`metal_code`、`origin` | **WS APP** | 有 | 有 | 适配 | `KNOWN` runtime README "Errors" |
| `enqueue`、`MTLCommandBufferDescriptor`、`retainedReferences`、`errorOptions` | APP | 缺（S/M，12 项） | n/a | 自行实现（薄层） | `KNOWN` coverage |
| `newCommandQueueWithDescriptor:`、`maxCommandBufferCount` | APP | 缺（S，3 项） | n/a | 自行实现（薄层） | `KNOWN` |
| 多队列并行 | CA APP | 有 | **受限：单一 `VkQueue`** | 适配 + 诚实降级（`shared-present-queue`） | `KNOWN` §2.3 |
| `MTLParallelRenderCommandEncoder` | SYS | 缺（M，9 项） | 有机制，但 `inheritedQueries = false` 影响 query 组合 | 自行实现或向上游补 | `KNOWN` coverage + §2.3 |
| `label`、`pushDebugGroup:`、`addDebugMarker:`、signpost | APP | 缺（S，17 项） | 有（`VK_EXT_debug_utils` 由 loader 提供） | 自行实现（薄层，优先做，便于排障） | `KNOWN` coverage |
| GPU 时间（`GPUStartTime`/`GPUEndTime`） | APP | 有（可选从 host 时钟答，`gpu_times_from_host`） | 有（calibrated timestamps 需实测） | 适配 | `KNOWN` runtime `DeviceOptions` |
| `MTLCommandBuffer.logs`、`MTLLogState`、`MTLFunctionLog` | APP | 缺（M/L，20+11+5 项） | n/a | 不实现（第一版），返回空 | `KNOWN` coverage |
| GPU capture（`MTLCaptureManager`、`MTLCaptureScope`） | — | 缺（S，25+7 项） | n/a | 不实现 | `KNOWN` coverage |
| `commit_failed`、`set_submission_check`、`add_submission_handler` | n/a（Metal 无此 API） | 有（runtime 扩展，专为模拟 Metal 设备的消费者提供） | 有 | **适配并使用**：这正是本项目需要的注入点 | `KNOWN` runtime README "Runtime extensions" |

### 3.3 Render

上游 `MTLRenderCommandEncoder.h`：119 / 4 / 9。`MTLRenderPipeline.h`：114 / 30 / 1。`MTLRenderPass.h`：41 / 12 / 0。`MTLDepthStencil.h`：15 / 2 / 0。`MTLVertexDescriptor.h`：19 / 0 / 0。`MTLStageInputOutputDescriptor.h`：21 / 0 / 0。

| 特性 | macOS 26 | m2v | Lavapipe | 本项目 | 证据 |
|---|---|---|---|---|---|
| render pass：多 color attachment（上限 8） | **WS CA** | 有（`MAX_COLOR_ATTACHMENTS`） | 有 | 适配 | `KNOWN` |
| load/store action 全集（含 `MultisampleResolve`、`StoreActionOptions`） | **WS CA** | 有 | 有 | 适配 | `KNOWN` |
| depth / stencil attachment、`MTLDepthStencilState` 全字段 | **CA** APP | 有 | 有 | 适配 | `KNOWN` |
| blend state 全集 + color write mask + `independentBlend` | **WS CA AK** | 有 | 有（`independentBlend = true`） | 适配 | `KNOWN` |
| dual-source blending | APP | 有 | 有（`dualSrcBlend` 随 llvmpipe cap） | 适配 | `KNOWN` |
| 非索引 / 索引 / 实例化 / `baseVertex` / `baseInstance` draw | **WS CA AK APP** | 有 | 有（`drawIndirectFirstInstance`、`fullDrawIndexUint32`） | 适配 | `KNOWN` |
| indirect draw（`drawPrimitives:indirectBuffer:`） | APP | 有 | 有（`multiDrawIndirect`、`drawIndirectCount`） | 适配 | `KNOWN` |
| 多 vertex buffer、`MTLVertexDescriptor` 全集、`StrideDynamic` | **WS CA APP** | 有 | 有（`VK_EXT_vertex_input_dynamic_state`、`legacyVertexAttributes`） | 适配 | `KNOWN` |
| primitive restart | APP | 组合实现（`set_primitive_restart_enabled`） | 有（`VK_EXT_primitive_restart_index`、`primitive_topology_list_restart`） | 适配 | `KNOWN` RUNTIME-PORTING "Composed from runtime calls" |
| Metal 私有 primitive（line loop、triangle fan、quads、quad strip，值 5–8） | SYS | 有（`DrawPrimitiveType::from_raw`，按 Metal 顶点序展开为 list） | 有 | 适配 | `KNOWN` runtime README "Runtime extensions" |
| viewport / scissor 数组 | **WS CA** | 有 | 有（`multiViewport`、`shaderOutputViewportIndex`） | 适配 | `KNOWN` |
| depth clip mode、depth bias、`setDepthClipMode:`(SPI) | CA APP | 有 | 有（`depthClamp` 随 cap、`depthBiasClamp`、`VK_EXT_depth_clip_enable`/`control`、`depth_range_unrestricted`） | 适配 | `KNOWN` |
| depth bounds（`setDepthTestMinBound:maxBound:`） | APP | 缺（M，1 项） | 有（`depthBounds` 随 cap） | 自行实现或向上游补 | `KNOWN` coverage |
| MSAA + resolve（color） | CA | 有 | 有 | 适配 | `KNOWN` |
| MSAA depth/stencil resolve filter（Min/Max/非零 stencil） | APP | 有 | **受限：只有 SAMPLE_ZERO** | 适配 + 降级（上游 `depth_stencil_resolve` 走手写 pass） | `KNOWN` §2.3 |
| 可编程 sample position | SYS | 有 | 受限（1×1 网格、坐标上界 0.9375） | 适配 + 降级 | `KNOWN` §2.3 |
| layered rendering（`render_target_array_index`、`viewport_array_index`） | CA | 有 | 有（`shaderOutputLayer`、`VK_EXT_shader_viewport_index_layer`、`image_2d_view_of_3d`） | 适配 | `KNOWN` |
| vertex amplification | — | 有 | 有（multiview 系）；但与 mesh 组合不可行 | 适配 | `KNOWN` §2.3 |
| clip / cull distance | APP | 有 | 有（`shaderClipDistance`、`shaderCullDistance` 随 cap） | 适配 | `KNOWN` |
| stencil export（shader 写 stencil） | APP | 有 | 有（`VK_EXT_shader_stencil_export`） | 适配 | `KNOWN` |
| per-sample shading（`[[sample_id]]`、sample rate） | CA | 有 | 有（`sampleRateShading` 随 cap） | 适配 | `KNOWN` |
| `[[primitive_id]]` in fragment | APP | 有（需 geometry 或 tessellation，或 mesh 后） | 有（geometryShader = true） | 适配 | `KNOWN` REFUSALS `PrimitiveId` |
| barycentric coordinates | APP | 有（可经生成的 geometry stage） | **无原生扩展**，经 geometry 可行 | 适配 + 性能降级 | `KNOWN` §2.3 |
| framebuffer fetch（可编程混合） | **WS SYS** | 有 | 有（interlock + rasterization order attachment access） | **适配（必须做，见 §5）** | `KNOWN` REFUSALS `FramebufferFetch` |
| raster order groups | WS | 有 | 有 | 适配 | `KNOWN` |
| visibility result（occlusion query） | APP | 有 | 有（`occlusionQueryPrecise`） | 适配 | `KNOWN` |
| `visibilityResultType`（累积） | APP | 缺（S，1 项） | 有 | 自行实现 | `KNOWN` coverage |
| `textureBarrier`、queue-stage barrier | APP | 缺（S/M，2 项） | 有（barrier 原语齐备） | 自行实现 | `KNOWN` coverage |
| color attachment mapping（逻辑↔物理） | — | 缺（M，6 项） | n/a | 不实现（第一版） | `KNOWN` coverage |
| pipeline 反射（创建后读 `reflection`） | APP | 缺（S，2 项） | n/a | 自行实现（translator 侧有 reflection 模块可用） | `KNOWN` coverage |
| pipeline specialization（macOS 26 新增，`newRenderPipelineDescriptorForSpecialization`） | APP | 缺（M，1 项） | n/a | 不实现（第一版） | `KNOWN` coverage |
| shader validation（`shaderValidation` 系） | — | 缺（L，6 项） | n/a | 不实现 | `KNOWN` coverage |

### 3.4 Compute

上游 `MTLComputeCommandEncoder.h`：36 / 1 / 3。`MTLComputePipeline.h`：34 / 9 / 1。`MTLComputePass.h`：0 / 11 / 0。

| 特性 | macOS 26 | m2v | Lavapipe | 本项目 | 证据 |
|---|---|---|---|---|---|
| `MTLComputePipelineState` + `dispatchThreadgroups:` + `dispatchThreads:` | **CA** APP | 有 | 有 | 适配 | `KNOWN` runtime 首例 |
| threadgroup memory（`setThreadgroupMemoryLength:atIndex:`） | CA APP | 有 | 有（`maxComputeSharedMemorySize` 需查限） | 适配 | `KNOWN` |
| buffer / texture / sampler binding、`setBytes:` | **CA** APP | 有 | 有 | 适配 | `KNOWN` |
| indirect dispatch | APP | 有 | 有 | 适配 | `KNOWN` |
| `memoryBarrierWithScope:`、`memoryBarrierWithResources:` | CA APP | 有 | 有（`synchronization2`） | 适配 | `KNOWN` |
| simdgroup 函数（shuffle、ballot、vote、reduce、prefix） | APP | 有 | **宽度受限：4 或 8，走 `Tier::Emulated`** | 适配 + 性能降级 | `KNOWN` §2.3 |
| quad 操作 | APP | 有（需 `subgroupQuadOperationsInAllStages` 或最小子组宽度） | 需实测 | 适配；实测不满足时诚实拒绝 | `BLOCKED` 缺目标设备的 `VkPhysicalDeviceSubgroupProperties` 采样 |
| simdgroup matrix（`simdgroup_matrix`） | APP | **缺（未实现）** | 有 `VK_KHR_cooperative_matrix`（仅 COMPUTE stage）+ `VK_NV_cooperative_matrix2` | 自行实现或向上游补；第一版拒绝 | `KNOWN` REFUSALS `SimdgroupMatrix` |
| kernel 内求导（`dfdx`/`dfdy`） | APP | 部分（需 `computeDerivativeGroupLinear`） | 有（`VK_KHR_compute_shader_derivatives`） | 适配 | `KNOWN` §2.2 |
| 64 位原子 | APP | 有（需 `shaderBufferInt64Atomics`） | 有 | 适配 | `KNOWN` |
| texture 原子（超出 32 位整数） | APP | 部分 | 有（`VK_EXT_shader_image_atomic_int64`、`shaderImageInt64Atomics`） | 适配 | `KNOWN` |
| float 原子 | APP | 有 | 有（`VK_EXT_shader_atomic_float`/`float2`，min/max 需 LLVM ≥ 15） | 适配 | `KNOWN` |
| `MTLComputePassDescriptor` | APP | 缺（S，11 项） | n/a | 自行实现（薄层） | `KNOWN` coverage |
| persistent kernel（macOS 27 新增） | n/a | 缺（L，5 项） | n/a | 不实现（基线无此 API） | `KNOWN` coverage |

### 3.5 Blit

上游 `MTLBlitCommandEncoder.h`：22 / 6 / 0。`MTLBlitPass.h`：0 / 10 / 0。

| 特性 | macOS 26 | m2v | Lavapipe | 本项目 | 证据 |
|---|---|---|---|---|---|
| buffer↔buffer、buffer↔texture、texture↔texture 全组合 | **WS CA** APP | 有 | 有（`VK_KHR_copy_commands2`） | 适配 | `KNOWN` RUNTIME-PORTING `BlitCmd` 节 |
| `fillBuffer:range:value:` | CA APP | 有 | 有 | 适配 | `KNOWN` |
| `fillBuffer:range:pattern4:`（SPI）、`fillTexture:`（SPI）、`fillTextureColor:`（SPI） | SYS | 有（含 Metal 的打包规则与越界行为复刻） | 有 | 适配 | `KNOWN` RUNTIME-PORTING |
| `generateMipmapsForTexture:` | CA APP | 有 | 有（需 format 的 blit src/dst + linear filter） | 适配 | `KNOWN` |
| `synchronizeResource:`、`synchronizeTexture:slice:level:` | APP | 有 | 有 | 适配 | `KNOWN` |
| `copyIndirectCommandBuffer:`、`optimizeIndirectCommandBuffer:`、`resetCommandsInBuffer:` | APP | 有 | 有 | 适配 | `KNOWN` |
| `optimizeContentsForCPU/GPUAccess:` | APP | 有（no-op，Vulkan 无压缩可见性） | n/a | 无需做 | `KNOWN` |
| `invalidateCompressedTexture:`（SPI） | SYS | 有（no-op） | n/a | 无需做 | `KNOWN` |
| `BlitOption`（depth/stencil 单一面、PVRTC） | APP | 部分（`CopyTextureRegionOptions` 需经 buffer 中转） | 有 | 适配 | `KNOWN` RUNTIME-PORTING "Composed from runtime calls" |
| counter 采样（`sampleCountersInBuffer:`、`resolveCounters:`） | — | 缺（M，54 项含各 pass 的 attachment descriptor） | 有（`pipelineStatisticsQuery`、timestamp） | 不实现（第一版） | `KNOWN` coverage |
| texture access counter（`getTextureAccessCounters:`） | — | 缺（L，2 项，上游标"未排期"） | n/a | 不实现 | `KNOWN` coverage |
| `MTLBlitPassDescriptor` | APP | 缺（S，10 项） | n/a | 自行实现（薄层） | `KNOWN` coverage |

### 3.6 纹理与像素格式

上游 `MTLTexture.h`：57 / 12 / 4。`MTLTextureViewPool.h`：0 / 4 / 0。`MTLResourceViewPool.h`：0 / 9 / 0。

| 特性 | macOS 26 | m2v | Lavapipe | 本项目 | 证据 |
|---|---|---|---|---|---|
| texture type 1D / 1DArray / 2D / 2DArray / 2DMultisample / 2DMultisampleArray / Cube / CubeArray / 3D / TextureBuffer | **WS CA** APP | 有 | 有（`imageCubeArray` 随 cap、texel buffer 有限额） | 适配 | `KNOWN` |
| 多 mip、多 slice、texture view（`newTextureViewWithPixelFormat:`） | **CA** APP | 有 | 有（`VK_KHR_maintenance*`、`blockTexelViewCompatibleMultipleLayers`） | 适配 | `KNOWN` |
| texture swizzle（`MTLTextureSwizzleChannels`） | CA APP | 有 | 有 | 适配 | `KNOWN` |
| `replaceRegion:` / `getBytes:` | **WS CA** APP | 有（含 `replace_region_with_host_bytes`，专为 guest 内存指针） | 有（`VK_EXT_host_image_copy` 可免 staging） | 适配 | `KNOWN` runtime README |
| texture over buffer（`newTextureWithDescriptor:offset:bytesPerRow:`） | **WS** | 有（含 in-place / shadow / copy 三态与设备自检） | 有（linear image、`DRM_FORMAT_MOD_LINEAR`） | 适配；IOSurface plane 的 pitch 规则由本项目负责 | `KNOWN` runtime README "The memory model" |
| IOSurface plane 纹理 | **WS CA SYS** | 仅 stand-in（`IoSurfacePlane`，上游不碰真实 IOSurface） | 有（`VK_EXT_external_memory_host`） | **自行实现**（`41-IOSURFACE-USERSPACE.md`） | `KNOWN` runtime README "Out of scope" |
| 两 plane YCbCr 纹理（`YCBCR8_420_2P` 系） | **SYS**（RenderBox 在 26.6.2 guest 上对 `'b3a8'` surface 建过） | 有（转换为 image；统一内存下可在 plane 原地采样） | 有（`samplerYcbcrConversion`、`VK_EXT_ycbcr_2plane_444_formats`） | 适配 | `KNOWN` 上游 `texture/surface_two_planes.rs` 文档 |
| 压缩格式 BC1–BC7 | APP | 有 | 有（`textureCompressionBC`） | 适配 + 精度降级记录 | `KNOWN` |
| 压缩格式 ETC2 / EAC | APP | 有 | 有（`textureCompressionETC2`） | 适配 | `KNOWN` |
| 压缩格式 ASTC LDR / sRGB | APP | 有 | 有（`textureCompressionASTC_LDR`） | 适配 | `KNOWN` |
| 压缩格式 ASTC HDR | APP | 有 | **缺（`textureCompressionASTC_HDR = false`）** | 不可行 → 报 false | `KNOWN` §2.3 |
| ASTC 4×2 与 8×4 footprint | APP | **缺（Vulkan 无对应 block，上游未建解码）** | 缺 | 不可行 → 报 false | `KNOWN` 上游 `format/mod.rs` `astc_without_a_vulkan_block!()` |
| PVRTC | APP（已弃用） | 有（RGBA 形式直接映射；RGB 形式经 RGBA8 解码） | 需 `VK_IMG_format_pvrtc`，Lavapipe 未列 | RGB 形式可行，RGBA 形式不可行 → 分格式报 | `KNOWN` 上游 candidate 表 |
| 三通道格式（`RGB8Unorm`、`RGB16*`、`RGB32*`） | — | **缺（`formats_named_not_held!()` → NotImplemented）** | Vulkan 有 `R8G8B8*` 但驱动普遍不支持 | 不可行 → 报 false | `KNOWN` 同上 |
| XR 与扩展 sRGB 格式（`BGR10XR`、`BGRA10XR`、`RGB10A8_2P_XR10`、`RGBA16FloatXR`） | **WS SYS** | 部分：`BGR10XR`/`BGRA10XR`/`RGB10A8_2P_XR10` **有**（分别落到 `R32_UINT`、`R16G16B16A16_UINT`、`R32G32_UINT` 并在 shader 内编解码）；`RGBA16FloatXR` **缺** | 有（整数格式） | 适配；`RGBA16FloatXR` 报 false | `KNOWN` 上游 candidate 表。**`RGB10A8_2P_XR10` 是 WindowServer 登录路径实际用到的格式（§5）** |
| 其余 Apple 私有格式族（1P、12 位、PQ/HLG、`R10*`/`R12*`/`BGRA10*` packed 系，约 100 个值） | SYS（部分由 VideoToolbox / CoreVideo 路径使用） | **缺（`formats_named_not_held!()`）** | 多数有整数落点，但无上游实现 | 第一版报 false；按实测需求逐个补 | `KNOWN` 同上 |
| depth / stencil 格式（`Depth16Unorm`、`Depth32Float`、`Stencil8`、`Depth24UnormStencil8`、`Depth32FloatStencil8`、`X24Stencil8`、`X32Stencil8`） | **CA** APP | 有（含 combined 回退与 `DepthWidened` 降级） | 有 | 适配 | `KNOWN` 上游 candidate 表 |
| `AnyDepth` / `AnyStencil` 占位值 | — | 缺（NotImplemented） | n/a | 报无效 | `KNOWN` |
| 有损纹理压缩（`compressionType`） | — | 缺（M，2 项） | n/a | 不实现 | `KNOWN` coverage |
| texture view pool / resource view pool | — | 缺（M，14+9 项） | 有（descriptor buffer / heap） | 不实现（第一版） | `KNOWN` coverage |
| `minLOD`（macOS 27 新增） | n/a | 缺（M，2 项） | 有（`VK_EXT_image_view_min_lod`） | 不实现（基线无此 API） | `KNOWN` coverage |

完整的 `MTLPixelFormat ↔ VkFormat ↔ Lavapipe` 全量表在 `40-RUNTIME-VULKAN.md` §8。

### 3.7 采样

上游 `MTLSampler.h`：19 / 3 / 0。

| 特性 | macOS 26 | m2v | Lavapipe | 本项目 | 证据 |
|---|---|---|---|---|---|
| min/mag/mip filter、address mode 全集、`normalizedCoordinates` | **WS CA AK APP** | 有 | 有（`samplerMirrorClampToEdge`） | 适配 | `KNOWN` |
| LOD clamp（`lodMinClamp`/`lodMaxClamp`） | CA APP | 有 | 有 | 适配 | `KNOWN` |
| `maxAnisotropy` | APP | 有 | 有（`samplerAnisotropy = true`） | 适配 | `KNOWN` |
| `compareFunction`（shadow sampler） | APP | 有 | 有 | 适配 | `KNOWN` |
| border color（`MTLSamplerBorderColor`） | APP | 有 | 有（`VK_EXT_custom_border_color`、`borderColorSwizzle`） | 适配 | `KNOWN` |
| `supportArgumentBuffers`（sampler 入 argument buffer） | APP | 有 | 有（descriptor indexing） | 适配 | `KNOWN` |
| `min_lod_clamp`（shader 侧） | APP | 有（需 `shaderResourceMinLod`） | 有 | 适配 | `KNOWN` |
| `lodBias`（descriptor 侧） | APP | **缺（M，1 项）** | 有（`maxSamplerLodBias`） | 自行实现或向上游补 | `KNOWN` coverage |
| constexpr sampler 的 LOD bias（shader 侧） | APP | 部分 | 有 | 适配 | `KNOWN` REFUSALS `SamplerLodBias` |
| `gather` 带常量 offset | APP | 有 | 有（`shaderImageGatherExtended`） | 适配 | `KNOWN` |
| `gather` 带动态 offset / 动态 component | APP | 缺 | n/a（Vulkan 要求常量） | 不可行 → 拒绝 | `KNOWN` REFUSALS `GatherExtended` |
| filter min/max（`MTLSamplerDescriptor` 的 min/max 归约） | APP | 有 | 有（`samplerFilterMinmax`、`VK_EXT_sampler_filter_minmax`） | 适配 | `KNOWN` |
| 动态选择纹理后的隐式 LOD 采样 | APP | **缺（未实现）** | 有（`quadDivergentImplicitLod = true`） | 自行实现或向上游补；第一版拒绝 | `KNOWN` REFUSALS `DivergentImplicitLod` |
| fragment 之外的隐式 LOD 采样 | APP | 缺（未实现） | 有 | 第一版拒绝 | `KNOWN` REFUSALS `ImplicitLodOutsideFragment` |

### 3.8 同步

上游 `MTLEvent.h`：12 / 1 / 2。`MTLFence.h`：3 / 0 / 0。

| 特性 | macOS 26 | m2v | Lavapipe | 本项目 | 证据 |
|---|---|---|---|---|---|
| `MTLFence`（encoder 间 `updateFence:` / `waitForFence:`） | CA APP | 有 | 有 | 适配 | `KNOWN` |
| `MTLEvent`（队列内 `encodeSignalEvent:` / `encodeWaitForEvent:`） | CA APP | 有 | 有（timeline semaphore） | 适配 | `KNOWN` |
| `MTLSharedEvent` + `MTLSharedEventListener` + 通知 | **WS SYS** APP | 有，**但 handle 仅进程内** | 有 | **自行实现跨进程部分**（Mach port 导出 + helper 侧映射） | `KNOWN` RUNTIME-PORTING `Platform` 节标 *(partial)*："in one process only" |
| `MTLSharedEventHandle` 跨进程重建 | WS SYS | **不做（上游明确范围外）** | n/a | **自行实现** | `KNOWN` 同上 |
| 跨队列顺序 | CA APP | 有 | 受限（单一 `VkQueue`，顺序退化为提交序） | 适配 + 降级 | `KNOWN` §2.3 |
| CPU 等待 + 回调 | **WS CA APP** | 有（`wait_until_completed`，并对会死锁的等待直接拒绝 `WaitWouldDeadlock`） | 有 | 适配 | `KNOWN` runtime README "Errors" |
| display present fence | **WS** | 不做（无 presentation） | n/a | **自行实现**（`11-KERNEL-DISPLAY.md` + `12-KERNEL-IOSURFACE.md`） | `KNOWN` runtime README "Out of scope" |
| 与消费者自有 Vulkan 工作排序（`encode_wait_for_vk_semaphore` / `encode_signal_vk_semaphore`） | n/a | 有（runtime 扩展） | 有 | 适配并使用 | `KNOWN` runtime README |
| `textureBarrier` / queue-stage barrier | APP | 缺（S/M，2 项） | 有 | 自行实现 | `KNOWN` coverage |

### 3.9 Heap 与资源内存

上游 `MTLHeap.h`：25 / 1 / 4。`MTLResource.h`：12 / 1 / 1。`MTLBuffer.h`：6 / 4 / 2。`MTLAllocation.h`：1 / 1 / 0。`MTLResourceStateCommandEncoder.h`：7 / 0 / 0。`MTLResourceStatePass.h`：0 / 10 / 0。`MTLResidencySet.h`：0 / 18 / 0。

| 特性 | macOS 26 | m2v | Lavapipe | 本项目 | 证据 |
|---|---|---|---|---|---|
| storage mode `Shared` / `Managed` / `Private` / `Memoryless` | **WS CA AK APP** | 有（`Managed` 在无统一内存时双份；CPU 设备答统一内存） | 有 | 适配 | `KNOWN` runtime README "The memory model" |
| CPU cache mode、hazard tracking mode | APP | 有 | 有 | 适配 | `KNOWN` |
| `MTLHeap`（automatic 与 placement 两类） | CA APP | 有（`HeapType`、`heap_texture_size_and_align`） | 有 | 适配 | `KNOWN` |
| heap 内 alias + fence 排序 | CA APP | 有 | 有 | 适配 | `KNOWN` 上游 `examples/heap_placement.rs` |
| `gpuAddress`（buffer / heap） | APP | 有（可由消费者 pin，`AddressPlacement`） | 有（`bufferDeviceAddress`） | 适配 | `KNOWN` |
| `gpuResourceID`（texture / sampler / pipeline / ICB） | APP | 有（可由消费者 pin，`IdPlacement`、`reserve_resource_ids`） | 有 | 适配；guest 自有编号由本项目维护 | `KNOWN` runtime README "The Metal address space" |
| `newBufferWithBytesNoCopy:` | **WS** | 有（`HostMemory`，经 `VK_EXT_external_memory_host`；含 import gate、dirty page log、dma-buf、guest RAM 整块导入等多条退路） | 有 | 适配；真实 IOSurface 页由本项目提供 | `KNOWN` runtime README |
| `purgeableState:` | APP | 有 | 有 | 适配 | `KNOWN` |
| residency / 预算（`recommendedMaxWorkingSetSize`、`currentAllocatedSize`） | APP | 部分 | 有（`VK_EXT_memory_budget`） | 适配 | `KNOWN` |
| `MTLResidencySet`（macOS 15 引入） | APP | **缺（M，18 + 7 项）** | 有（descriptor indexing + 显式驻留无直接等价，可用 `use_resource` 语义模拟） | 自行实现或向上游补；第一版报 false | `KNOWN` coverage |
| sparse texture / placement sparse / sparse buffer | APP（Apple 家族与较新 Mac） | 有（`SparseFeatures`、`ResourceStateCommandEncoder`） | **仅 Linux** | **不可行（macOS 宿主）** → 报 false。Mac2 列不含 sparse，不阻断家族声明 | `KNOWN` §2.3 |
| placement sparse page size 查询 | APP | 缺（S，2 项） | 仅 Linux | 不可行 | `KNOWN` coverage |
| `replaceBackingWithRanges:` / `detachBacking`（SPI，分散后备） | SYS | **不做（上游明确范围外）** | n/a | **自行实现**（把内存重映射成连续区） | `KNOWN` RUNTIME-PORTING "Not the runtime's" |
| 快速资源加载（`MTLIOCommandQueue`、`MTLIOCommandBuffer`、`MTLIOCompressor`） | APP | **缺（L，44 项）** | n/a | 不实现（第一版） | `KNOWN` coverage |

### 3.10 Argument buffer 与 bindless

上游 `MTLArgumentEncoder.h`：23 / 2 / 3。`MTLArgument.h`：77 / 17 / 0。

| 特性 | macOS 26 | m2v | Lavapipe | 本项目 | 证据 |
|---|---|---|---|---|---|
| argument buffer tier 1（buffer / 常量） | CA APP | 有 | 有 | 适配 | `KNOWN` |
| argument buffer tier 2（纹理与 sampler 入 argument buffer，bindless） | APP | 有（受设备限额） | 有（descriptor indexing 全套 + `runtimeDescriptorArray`） | 适配 | `KNOWN` §2.2 |
| argument buffer 内含 buffer 指针（动态根） | APP | 有（需 buffer device address） | 有 | 适配 | `KNOWN` REFUSALS `ArgumentBufferPointers` |
| argument buffer 内含 pipeline state / ICB / function table / 加速结构 | APP | **缺（未实现）** | 部分有（descriptor buffer / device generated commands） | 第一版拒绝 | `KNOWN` REFUSALS `ArgumentBufferObjects` |
| `setDepthStencilState:atIndex:`（argument encoder） | — | 缺（M，2 项） | n/a | 不实现 | `KNOWN` coverage |
| 从内存载入的指针再解引用 | APP | 部分（需 device address） | 有 | 适配 | `KNOWN` REFUSALS `DereferenceLoadedPointer` |
| `MTLArgument` / `MTLType` 反射全族 | APP | 有（77 项，translator 的值类型） | n/a | 适配 | `KNOWN` coverage |
| `MTLFunctionConstantValues` | **CA** APP | 有 | n/a（编译期烘焙） | 适配 | `KNOWN` |

### 3.11 Indirect command buffer

上游 `MTLIndirectCommandBuffer.h`：26 / 0 / 1。`MTLIndirectCommandEncoder.h`：35 / 0 / 0。

| 特性 | macOS 26 | m2v | Lavapipe | 本项目 | 证据 |
|---|---|---|---|---|---|
| ICB 创建、render / compute 命令编码、`executeCommandsInBuffer:` | APP | **有（全覆盖，61/61）** | 有（`VK_EXT_device_generated_commands`，也可由 runtime 自带 helper kernel 回放） | 适配 | `KNOWN` coverage + 上游 `examples/indirect_command_buffer.rs` |
| GPU 侧写 ICB 后执行 | APP | 有 | 有 | 适配 | `KNOWN` |
| `execute_commands_in_buffer_checked`（带命令检查回调） | n/a | 有（runtime 扩展） | 有 | 适配并使用（guest 命令流校验的注入点） | `KNOWN` runtime README |
| ICB 的私有 getter（读回已编码命令） | SYS | 有 | n/a | 适配 | `KNOWN` RUNTIME-PORTING |

### 3.12 Binary archive 与管线缓存

上游 `MTLBinaryArchive.h`：9 / 3 / 0。`MTLPipeline.h`：5 / 0 / 0。

| 特性 | macOS 26 | m2v | Lavapipe | 本项目 | 证据 |
|---|---|---|---|---|---|
| `MTLBinaryArchive` 创建、加入 compute / render 管线、序列化 | APP | 有（9 项） | 有（`VK_EXT_pipeline_creation_cache_control`、pipeline cache） | 适配 | `KNOWN` coverage |
| 加入 mesh 管线 / library / function descriptor | APP | 缺（S，3 项） | 有 | 自行实现（薄层） | `KNOWN` coverage |
| 跨进程管线缓存 | **CA**（会释放并重建同一管线状态） | 有（runtime 扩展 `PipelineRecord` + `Device::warm`，后台线程预热，受字节预算约束） | 有 | **适配并必须使用**：CPU 上管线创建昂贵，这是性能可行性的关键 | `KNOWN` runtime README "Runtime extensions"；上游 `pipeline/kept.rs` 文档点名 CoreAnimation 的释放–重建行为 |
| 着色器翻译缓存 | — | 有（`ShaderCacheOptions`，默认落每用户缓存目录） | n/a | 适配：目录必须落在本项目控制的路径，且绑定 guest build 与组件哈希 | `KNOWN` runtime README |

### 3.13 Dynamic library、函数指针、函数表

上游 `MTLDynamicLibrary.h`：5 / 0 / 0。`MTLLinkedFunctions.h`：6 / 0 / 0。`MTLFunctionHandle.h`：3 / 2 / 0。`MTLVisibleFunctionTable.h`：7 / 0 / 0。`MTLFunctionStitching.h`：0 / 22 / 0。

| 特性 | macOS 26 | m2v | Lavapipe | 本项目 | 证据 |
|---|---|---|---|---|---|
| `MTLDynamicLibrary` 对象与属性 | APP | 对象**有**（5/5），但**使用被拒绝**（`Linking` 拒绝：动态库 / stitching / 链接签名未实现） | 有（`VK_EXT_shader_object`、`VK_EXT_graphics_pipeline_library`，但语义不同） | 自行实现或向上游补；第一版：对象可建，链接时报确定错误 | `KNOWN` coverage + REFUSALS `Linking` |
| `MTLLinkedFunctions` | APP | 对象有（6/6），链接拒绝 | 同上 | 同上 | `KNOWN` |
| `MTLVisibleFunctionTable` | APP | 对象有（7/7），**通过表的调用被拒绝**（`DynamicCall`：间接调用 / 函数指针 / visible 与 intersection function table 未实现） | 无直接等价（Vulkan 无函数指针） | **不可行（近期）** → 对象可建，调用报确定错误 | `KNOWN` REFUSALS `DynamicCall`："every device (no Vulkan mechanism)" |
| 按名取 function handle、handle 的类型与 ID | APP | 缺（S，4 项） | n/a | 自行实现（薄层） | `KNOWN` coverage |
| function stitching（`newLibraryWithStitchedDescriptor:`） | APP | **缺（L，22–24 项）** | n/a | 不实现（第一版） | `KNOWN` coverage |
| specialized function 的 `specializedName` | APP | 缺（S，1 项） | n/a | 自行实现 | `KNOWN` coverage |

### 3.14 Ray tracing

上游 `MTLAccelerationStructure.h`：0 / 0 / 129。`MTLAccelerationStructureCommandEncoder.h`：0 / 0 / 25。`MTLIntersectionFunctionTable.h`：0 / 0 / 15。`MTLAccelerationStructureTypes.h`：0 / 0 / 2。`MTL4AccelerationStructure.h`：0 / 0 / 94。

| 特性 | macOS 26 | m2v | Lavapipe | 本项目 | 证据 |
|---|---|---|---|---|---|
| 全部加速结构、intersection function、ray query | APP | **不做（上游明确范围外，265 项）** | **有**（`VK_KHR_acceleration_structure` + `VK_KHR_ray_tracing_pipeline` 的软件实现，`maxRayRecursionDepth = 31`） | **自行实现或不实现**。天花板由 **m2v 决定**，不是 Lavapipe | `KNOWN` coverage + §2.2 |

**判断**：这是矩阵中最反直觉的一行。Lavapipe 有完整的软件 ray tracing，而上游把 ray tracing 整族划在范围外。要支持 Metal ray tracing，必须在本项目或上游新写 AIR ray tracing intrinsic 的 lowering（上游 `lower/raytracing` 模块存在但 `RayTracing` 拒绝为 "no Vulkan mechanism / not implemented"）。考虑到 WindowServer 与常规桌面 app 不用 ray tracing，**第一版不实现，报 false**。

### 3.15 Mesh / object shader

上游 `MTLRenderPipeline.h` 中的 mesh 字段：部分 implemented，12 项 missing（S）。`MTL4MeshRenderPipeline.h`：0 / 27 / 0。

| 特性 | macOS 26 | m2v | Lavapipe | 本项目 | 证据 |
|---|---|---|---|---|---|
| mesh render pipeline、object / mesh function、`drawMeshThreadgroups:` | APP | 部分（`MeshShading` 在若干形式上 "not implemented"；mesh 管线不参与 `PipelineRecord` 预热） | 有（`VK_EXT_mesh_shader`，`taskShader` + `meshShader` + `meshShaderQueries`） | 适配 + 补齐上游缺口；第一版拒绝未建形式 | `KNOWN` REFUSALS `MeshShading` + §2.2 |
| mesh pipeline descriptor 字段（`maxTotalThreadsPerObjectThreadgroup` 等 12 项） | APP | 缺（S） | 有 | 自行实现（薄层） | `KNOWN` coverage |
| mesh + 分层渲染 | APP | 部分 | **受限：`maxMeshOutputLayers = 9`** | 适配 + 限额诚实上报 | `KNOWN` §2.3 |
| mesh + vertex amplification | APP | 部分 | **不可行（`multiviewMeshShader = false`）** | 不可行 → 拒绝 | `KNOWN` §2.3 |
| mesh / task shader 内求导 | APP | 部分 | 有（`meshAndTaskShaderDerivatives`） | 适配 | `KNOWN` §2.2 |

### 3.16 Tessellation

上游 `MTLRenderPipeline.h` 中的 tessellation 字段为 implemented（descriptor 侧），但**执行侧是拒绝**。

| 特性 | macOS 26 | m2v | Lavapipe | 本项目 | 证据 |
|---|---|---|---|---|---|
| tessellation descriptor 字段（partition mode、factor scale、output windings、step function） | APP | 有（值类型） | — | 适配 | `KNOWN` coverage |
| tessellation 执行（post-tessellation vertex function、tessellation factor buffer、`drawPatches:`） | APP | **缺（`Tessellation` 拒绝，13 处构造点，basis `ours`："every device (not implemented)"）** | **有（`tessellationShader = true`，`maxTessellationGenerationLevel` 需查限）** | **天花板由 m2v 决定。自行实现或向上游补**；第一版拒绝 | `KNOWN` REFUSALS `Tessellation` + §2.2 |
| `MTLTessellationFactorStepFunction` / compute 驱动的 tessellation factor | APP | 部分 | 有 | 同上 | `KNOWN` |

**判断**：tessellation 是"Lavapipe 有、上游缺"的典型项（§4.2），属纯工作量。WindowServer 与 CoreAnimation 不用 tessellation，常规 2D app 也不用；3D app 与游戏会用。排期上放在 `FULL-1` 之后。

### 3.17 Tile shading、imageblock、可编程混合

| 特性 | macOS 26 | m2v | Lavapipe | 本项目 | 证据 |
|---|---|---|---|---|---|
| tile render pipeline、`dispatchThreadsPerTile:`（Apple 家族特性） | —（Mac2 不列） | 缺（`TileShading` 拒绝："not implemented"） | 部分（无 tile memory 概念，需以 storage buffer 模拟） | 不实现 → 报 false（Mac2 不需要） | `KNOWN` REFUSALS `TileShading` |
| imageblock（`imageblock_data`、explicit / implicit layout） | —（Mac2 不列） | 缺（`Imageblocks` 拒绝） | 部分 | 不实现 → 报 false | `KNOWN` REFUSALS `Imageblocks`；上游 `families/mod.rs`："Metal3's Mac devices have no imageblocks" |
| framebuffer fetch（`[[color(n)]]` 作为 fragment 输入） | **WS SYS** | 有 | 有 | **必须做**（§5） | `KNOWN` REFUSALS `FramebufferFetch` |
| raster order group | WS | 有 | 有 | 适配 | `KNOWN` |

### 3.18 可变光栅化率

上游 `MTLRasterizationRate.h`：37 / 0 / 1。

| 特性 | macOS 26 | m2v | Lavapipe | 本项目 | 证据 |
|---|---|---|---|---|---|
| `MTLRasterizationRateMap` 全族（descriptor、layer、screen/physical 坐标换算、parameter buffer） | APP | **有（37/38）** | 需实测（上游另有 5 条 "rate map the compile layer does not compile" 拒绝） | 适配 | `KNOWN` coverage + REFUSALS §6 |
| `supportsRasterizationRateMapWithLayerCount:` | APP | 有（组合查询） | 需实测 | 适配 | `KNOWN` RUNTIME-PORTING |

### 3.19 性能计数器与调试

上游 `MTLCounters.h`：0 / 15 / 0。`MTL4Counters.h`：0 / 9 / 0。`MTLCaptureManager.h`：0 / 17 / 1。`MTLCaptureScope.h`：0 / 7 / 0。`MTLFunctionLog.h`：0 / 11 / 0。`MTLLogState.h`：0 / 5 / 0。

| 特性 | macOS 26 | m2v | Lavapipe | 本项目 | 证据 |
|---|---|---|---|---|---|
| `MTLCounterSampleBuffer`、counter set、timestamp / statistic / stage utilization | — | **缺（M，54 项合计）** | 部分有（`pipelineStatisticsQuery`、`hostQueryReset`、timestamp query） | 不实现（第一版），`counterSets` 返回空数组 | `KNOWN` coverage |
| shader logging | — | 缺（M，20 项） | n/a | 不实现 | `KNOWN` coverage |
| GPU capture | — | 缺（S，25 项） | n/a | 不实现 | `KNOWN` coverage |
| `label` / debug group / signpost | APP | 缺（S，17 项） | 有 | **自行实现（优先）**：排障刚需 | `KNOWN` coverage |

### 3.20 视频与 ML

上游 `MTLTensor.h`：0 / 45 / 0。`MTL4MachineLearning*`：0 / 18 / 0。

| 特性 | macOS 26 | m2v | Lavapipe | 本项目 | 证据 |
|---|---|---|---|---|---|
| `MTLTensor` 及其反射 | APP | **缺（L，45–68 项）** | n/a | 不实现 → 报 false | `KNOWN` coverage |
| Metal 4 ML encoder / ML pipeline | APP | **缺（XL，18 项）** | n/a | 不实现 → 报 false | `KNOWN` coverage |
| 视频格式纹理（两 plane YCbCr、4:2:0 / 4:2:2 / 4:4:4） | **SYS** | 有（两 plane 族） | 有 | 适配 | `KNOWN` §3.6 |
| 硬件视频解码 | n/a（不属 Metal） | 不做 | 不做 | 不承诺 | `KNOWN` `CAPABILITY_PROFILES.md` §3.9 已声明"不含硬件解码承诺" |

### 3.21 Metal 4 对象族

| 特性 | macOS 26 | m2v | Lavapipe | 本项目 | 证据 |
|---|---|---|---|---|---|
| `MTL4*` 全族（§1.2 的 432 项） | 存在但 Intel Mac 上不可用（§1.3） | **缺（L/XL，369 + 18 项）** | n/a（Vulkan 侧无对应模型，但机制大多存在） | **不实现**：`supportsFamily:5002` → false，相关 selector 返回 nil | `KNOWN` §1.3 |

### 3.22 OS 集成（本项目本体，上游零覆盖）

这一节是 `00-OVERVIEW.md` 第 3 节的边界 ③。上游对每一项都明确"不做"。

| 特性 | macOS 26 | m2v | Lavapipe | 本项目 | 分册 |
|---|---|---|---|---|---|
| accelerator service + type-5 user client（让 Metal.framework 枚举到设备） | **WS CA AK APP** | 不做 | n/a | **自行实现** | `10-KERNEL-ACCELERATOR.md` |
| IOFramebuffer display provider（让 WindowServer 认为有显示器） | **WS** | 不做 | n/a | **自行实现** | `11-KERNEL-DISPLAY.md` |
| 内核侧 IOSurface 与 accelerator resource 关联 | **WS** | 不做 | n/a | **自行实现** | `12-KERNEL-IOSURFACE.md` |
| 用户态真实 IOSurface（创建、导入 Vulkan、plane/stride/alloc size、in-place/shadow/copy） | **WS CA SYS** | 仅 stand-in | 有（`VK_EXT_external_memory_host`） | **自行实现** | `41-IOSURFACE-USERSPACE.md` |
| `CAMetalLayer` presentation / `MTLDrawable` | AK APP | 不做（7 项 out of scope） | 有 surface 扩展但本项目不用 | **自行实现**（走 IOSurface + display provider） | `11` + `41` |
| 跨进程 `MTLSharedEvent` / `MTLSharedTextureHandle` | WS SYS | 仅进程内 | n/a | **自行实现** | `50-IPC-HELPER.md` |
| 分散后备（`replaceBackingWithRanges:` / `detachBacking`） | SYS | 不做 | n/a | **自行实现** | `41` |
| Apple 序列化管线 descriptor（`deserialize_*_pipeline_descriptor`） | SYS | 不做 | n/a | **自行实现** | `22-OBJC-DESCRIPTORS.md` |
| guest 自有编号（`resourceIndex`、`uniqueIdentifier`、私有 device 属性） | SYS | 部分（已测的按 Metal 规则答；其余留给消费者） | n/a | **自行实现** | `20` + `21` |
| OS 服务（时钟、线程、偏好、启动） | — | 不做 | n/a | **自行实现** | `50` + `70` |
| Vulkan loader + Lavapipe 的 macOS x86_64 构建与打包 | — | 不随上游交付 | — | **自行实现** | `70-BUILD-PACKAGE.md` |

---

## 4. 功能天花板：谁决定上限

### 4.1 Lavapipe 缺而上游需要 —— 真正的天花板

这些项上游有实现，Vulkan 规范也有机制，但 **macOS x86_64 上的 Lavapipe 给不出来**。本项目无论投入多少工作量都无法在当前栈上提供；唯一出路是改 Mesa 或换 ICD。按影响排序：

| # | 项 | Lavapipe 事实 | 上游反应 | 后果 |
|---|---|---|---|---|
| 1 | **sparse 全族**（sparse texture、placement sparse、sparse buffer、`shaderResourceResidency`） | `sparseBinding` 等六个 feature 为 `DETECT_OS_LINUX`，macOS 构建全为 false | `SparseFeatures` 查询答 false；相关调用拒绝 | sparse 整族不可行。**但 Mac2 与 Common 列本来不含 sparse，不阻断目标家族声明**。真实损失限于声明 Apple6+ 或 Metal3 时 |
| 2 | **Metal 的 511 像素大点** | `pointSizeRange` 上界 256（上游 `Refusal::PointSizeRange` 直接点名 lavapipe） | 该 family 行判为 `Refused` | **这是一行会直接阻断 `supportsFamily:` 的硬项**。必须在实测后决定：要么放弃该家族声明，要么接受 Metal 行为差异（大点画小）并在能力报告里写明 |
| 3 | **整数格式 MSAA** | `framebufferIntegerColorSampleCounts = VK_SAMPLE_COUNT_1_BIT` | format 能力行判为缺 | uint/sint 格式的 `supportsTextureSampleCount:` 只能答 1 |
| 4 | **depth/stencil resolve 的 Min/Max 滤波** | `supportedDepthResolveModes`/`supportedStencilResolveModes` 只有 `SAMPLE_ZERO` | 走上游的手写 resolve pass | 可用但是降级（额外 pass，性能与精度记录在案） |
| 5 | **ASTC HDR** | `textureCompressionASTC_HDR = VK_FALSE` | format 行判为缺 | ASTC HDR 格式不可行 |
| 6 | **16 位 varying** | `storageInputOutput16 = false` | `half` 插值 widen 到 float | 精度降级 |
| 7 | **mesh + multiview** | `multiviewMeshShader = false`、`maxMeshMultiviewViewCount = 1` | 组合拒绝 | mesh + vertex amplification 不可行 |
| 8 | **次级 command buffer 继承 query** | `inheritedQueries = false` | 组合受限 | parallel render encoder 内的 visibility result 受限 |
| 9 | **多队列真并行** | 单一 graphics queue（上游 degradation 点名） | `shared-present-queue` 降级通告 | Metal 多队列退化为串行；present 持锁会挡别的队列 |
| 10 | **原生 barycentric 扩展** | 扩展表无 `VK_KHR_fragment_shader_barycentric` | 改走生成的 geometry stage（`geometryShader = true`） | 可行但多一个 stage，性能降级 |
| 11 | **32 宽 simdgroup** | `minSubgroupSize = maxSubgroupSize = lp_native_vector_width/32`（4 或 8） | kernel 走 `Tier::Emulated`（workgroup 内存 + barrier 模拟），fragment 走 `PartialFragment` | 正确性可保，性能显著降级；`quad` 操作与 `SimdgroupMatrix` 另有拒绝 |
| 12 | **`gpuCoreCount` 的来源** | 不列任何厂商 core-count 扩展（上游明确把 lavapipe 列入此类） | 答 `None` | Apple 私有属性必须本项目自给或报缺 |

**结论**：第 1、2 项是真正的能力上限；第 3–8 项是窄面上限，影响具体格式与组合；第 9–11 项是性能上限而非能力上限；第 12 项是报告问题。**没有一项阻断"桌面能不能跑起来"。**

### 4.2 Lavapipe 有而上游缺 —— 纯工作量

这些项 Lavapipe 已经提供机制，只缺上游实现。可自行实现或向上游提补丁（按 `METAL2VULKAN_INTEGRATION.md` §6 的补缺规则）。

| # | 项 | Lavapipe 提供 | 上游状态 | 工作量 | 优先级 |
|---|---|---|---|---|---|
| 1 | **tessellation 执行** | `tessellationShader = true`、`multiviewTessellationShader = true` | `Tessellation` 拒绝，13 处构造点 | L | 低（桌面不用） |
| 2 | **ray tracing 全族** | `VK_KHR_acceleration_structure` + `ray_tracing_pipeline` 软件实现 | 整族 out of scope（265 项） | XL | 低 |
| 3 | **simdgroup matrix** | `VK_KHR_cooperative_matrix`（COMPUTE）+ `VK_NV_cooperative_matrix2` | 未实现 | M | 低 |
| 4 | **mesh shading 的未建形式** | `VK_EXT_mesh_shader` 全套 | 部分未实现 | M | 低 |
| 5 | **`MTLResidencySet`** | memory budget + 驻留语义 | 缺（18 + 7 项） | M | 中（较新 app 会用） |
| 6 | **counter sample buffer** | `pipelineStatisticsQuery`、timestamp、`hostQueryReset` | 缺（54 项） | M | 低 |
| 7 | **parallel render encoder** | 次级 command buffer（`VK_EXT_nested_command_buffer`，嵌套层数 `UINT32_MAX`） | 缺（9 项） | M | 中 |
| 8 | **sampler `lodBias`（descriptor 侧）** | `maxSamplerLodBias` | 缺（1 项） | M | 中 |
| 9 | **depth bounds test** | `depthBounds` 随 llvmpipe cap | 缺（1 项） | M | 低 |
| 10 | **动态选择纹理后的隐式 LOD 采样** | `quadDivergentImplicitLod = true` | 未实现 | M | 中（bindless app 会用） |
| 11 | **argument buffer 内含对象（pipeline state / ICB）** | descriptor buffer / device generated commands | 未实现 | L | 低 |
| 12 | **dynamic library / function pointer / visible function table 的调用** | 无直接等价（函数指针在 Vulkan 侧也缺） | 拒绝 | XL | 低，且**不只是上游问题**（见 §4.3） |
| 13 | **label / debug group** | `VK_EXT_debug_utils`（loader 侧） | 缺（17 项） | S | **高**（排障刚需） |
| 14 | **各 pass descriptor（blit / compute / resource state）** | n/a（纯 API 薄层） | 缺（31 项） | S | 中 |
| 15 | **command buffer / queue descriptor** | n/a（纯 API 薄层） | 缺（15 项） | S | 中 |
| 16 | **device / resource 查询 54 项** | n/a | 缺（S） | S | **高**（`initLimits` / `initFeatureQueries` 链会读） |

### 4.3 macOS 26 有而三方都给不出 —— 直接报 false

| 项 | 为什么 |
|---|---|
| Metal 4 全族（432 项） | 上游 L/XL 零覆盖；Intel Mac 上本来不可用（§1.3） |
| `MTLTensor` + ML encoding（63 项） | Metal 4 的一部分 |
| 函数指针与 visible function table 的**调用** | Vulkan 没有函数指针机制（上游拒绝基线为 "no Vulkan mechanism"）。对象可建，调用必须报确定错误 |
| 三通道像素格式（`RGB8*`、`RGB16*`、`RGB32*`） | 上游 `formats_named_not_held!()`，且 Vulkan 驱动普遍不支持 3 通道 |
| ASTC 4×2 与 8×4 footprint | Vulkan 没有对应 block，解码未建 |
| `RGBA16FloatXR` | 上游 NotImplemented（Metal 也只在 IOSurface plane 上建这种纹理） |
| Apple 私有格式族的大部分（约 100 个值） | 上游未持有；按实测需求逐个补 |
| 有损纹理压缩、texture/resource view pool、function stitching、`MTLIOCommandQueue`、shader logging、GPU capture、shader validation | 上游缺且本项目无需求 |

### 4.4 一句话结论

**功能天花板主要由 metal2vulkan 决定，不由 Lavapipe 决定。**

Lavapipe 在 macOS 上真正拿不出来的只有 sparse 与 511 像素大点两项硬能力，加上一组窄面格式/组合限制和若干性能限制。相比之下上游缺 828 项，其中 376 项是 XL。本项目的工作量分配因此是：

1. OS 集成（上游零覆盖，`00-OVERVIEW.md` 边界 ③）—— 可行性风险所在；
2. 补上游的 S/M 级缺口（约 300 项，大多是薄层 API）—— 体力活，但直接决定 `initLimits` / `initFeatureQueries` 能不能过；
3. Lavapipe 的两项硬缺口 —— 只能诚实上报；
4. L/XL 级缺口（Metal 4、tensor、ray tracing、tessellation、stitching、IO queue）—— 明确不做，报 false。

---

## 5. WindowServer / CoreAnimation / AppKit 实际依赖的最小特性集

这是矩阵第一列最重要的部分。`CAPABILITY_PROFILES.md` 的 `MVP-1` 之所以内部矛盾（`00-OVERVIEW.md` §4.7），根源是它凭直觉猜了这个集合。本节用证据替代直觉。

### 5.1 证据来源

全部来自上游针对 **x86 macOS guest** 的实测与采样（`KNOWN`，架构：x86_64；样本来源：上游消费者的 macOS 26.6.2 guest 与 26 系统 metallib）：

| 证据 | 来源 | 说明 |
|---|---|---|
| WindowServer 与 RenderBox 的两条管线在登录路径上做 framebuffer fetch，attachment 格式为 `RGB10A8_2P_XR10` | 上游 `docs/REFUSALS.md` 的 `FramebufferFetch` 行 reach 列："macOS 26.6.2's login reaches it" | **这条最关键**：登录屏就用可编程混合，而且用的是 Apple 私有 XR 格式 |
| WindowServer 向 IOSurface plane 的 1920×1080 `RGBA16Float` 纹理写入 | 上游 `crates/metal2vulkan-validation/src/runtime_lane/surface_aliases.rs` 文档 | 合成目标不是 `BGRA8Unorm` |
| WindowServer 使用默认 options 的 no-copy buffer，`Shared` 存储 | 上游 `runtime_lane/buffer_texture_blits.rs:1951` | 需要 `VK_EXT_external_memory_host` 路径 |
| CoreAnimation 合成：`BGRA8Unorm` layer 的 load + store，旁边一张 scratch 用 `DontCare` | 上游 `runtime_lane/frame_costs.rs:111`、`:637` | 典型合成 pass 形状 |
| CoreAnimation 的 blur 纹理 usage 为 `ShaderRead \| RenderTarget \| BlockWritesOnly`（`BlockWritesOnly` = Apple 私有 `0x10000`） | 上游 `runtime_lane/level_writes_by_usage.rs:9`、`texture/ycbcr_image.rs`、`image_plan.rs:630` | 需要支持 Apple 私有 usage 位 |
| CoreAnimation 的 blur 写路径把 kernel 的 `half4` NaN 写进 16 位 float 纹理 | 上游 `runtime_lane/half_slice_nans.rs` | **合成要用 compute** |
| CoreAnimation 会释放一个管线状态再重建同一个 | 上游 `crates/metal2vulkan-runtime/src/pipeline/kept.rs:3` | 跨进程管线缓存不是优化，是必需 |
| macOS 26 最大的 CoreAnimation fragment 着色器为 210,033 words | 上游 `docs/FAST-PATHS.md:701` | 编译时间风险 |
| RenderBox 在 26.6.2 guest 上对 `'b3a8'` surface 建两 plane 纹理 | 上游 `crates/metal2vulkan-runtime/src/texture/surface_two_planes.rs:3` | 两 plane YCbCr 是系统路径，不是 app 可选项 |
| 上游的着色器语料采集把 `WindowServer`、`SkyLight`、`CoreDisplay`、`CoreAnimation`、`QuartzCore` 列为最高优先级 band | 上游 `crates/metal2vulkan-validation/src/bin/corpus-harvest.rs:950` 附近的 `priority_key` | 这五个进程是系统显示路径的 Metal 客户端 |

### 5.2 WindowServer 首帧的最小 Metal 特性集

`KNOWN` 部分来自 §5.1；`INFERRED` 部分注明。

**必需（缺一不可）**

| # | 特性 | 为什么 | 标签 |
|---|---|---|---|
| 1 | 设备枚举 + `registryID` + `supportsFamily:` + 完整 limits/feature 查询链 | Metal.framework 的 `_MTLIOAccelDevice` init 链会读；读不到就不会发布设备 | `KNOWN` §3.1 |
| 2 | 单队列 + command buffer + `commit` + `addCompletedHandler:` | 合成帧的基本结构 | `KNOWN` |
| 3 | render pass：color attachment、Load/Store/Clear/DontCare | CoreAnimation 合成 pass | `KNOWN` §5.1 |
| 4 | **blend state**（含 color write mask） | 桌面合成必然混合。`MVP-1` 原文要求报 false，这是错的 | `KNOWN` §3.3 |
| 5 | **compute**（pipeline、threadgroup、buffer/texture binding、barrier） | blur 用 kernel。`MVP-1` 原文要求报 false，这是错的 | `KNOWN` §5.1 half_slice_nans |
| 6 | **framebuffer fetch / 可编程混合** | 登录路径就用。Lavapipe 侧有 `fragment_shader_interlock` + `rasterization_order_attachment_access`，可行 | `KNOWN` §5.1 |
| 7 | **`RGB10A8_2P_XR10` 格式**（上游落到 `R32G32_UINT` 并在 shader 内编解码） | 登录路径的 attachment 格式 | `KNOWN` §5.1 |
| 8 | `BGRA8Unorm` + `RGBA16Float` 纹理与 attachment | layer 与 scanout 目标 | `KNOWN` §5.1 |
| 9 | Apple 私有 texture usage 位（`BlockWritesOnly` `0x10000`） | blur 纹理 | `KNOWN` §5.1 |
| 10 | 真实 IOSurface：创建、plane/stride/alloc size、no-copy 导入、in-place/shadow/copy 判定、完成后可见性 | 没有它就没有 scanout | `KNOWN` 上游范围外 → 本项目 §3.22 |
| 11 | no-copy `Shared` buffer（经 `VK_EXT_external_memory_host`） | WindowServer 的 buffer 形态 | `KNOWN` §5.1 |
| 12 | texture over buffer（IOSurface plane 上建纹理） | scanout 纹理的构造方式 | `KNOWN` §3.6 |
| 13 | blit：buffer↔texture、texture↔texture、`synchronizeResource:` | 回读与跨存储移动 | `KNOWN` |
| 14 | `MTLFence` + `MTLEvent` + CPU 等待 | 帧内与帧间排序 | `KNOWN` |
| 15 | **跨进程 `MTLSharedEvent`** | WindowServer 与客户端进程之间的帧同步 | `KNOWN` 上游仅进程内 → 本项目 §3.22 |
| 16 | display provider：mode 枚举、scanout 提交、swap completion、present fence | WindowServer 认不认这块"显卡" | `KNOWN` 上游不做 → 本项目 |
| 17 | **跨进程管线缓存**（`PipelineRecord` + `Device::warm`） | CoreAnimation 释放后重建同一管线；CPU 上重编译 210k words 的着色器不可接受 | `KNOWN` §5.1 |
| 18 | depth / stencil（`Depth32Float` 至少） | 合成有深度排序路径 | `INFERRED`：需在 guest 上抓 WindowServer 的 render pass descriptor 确认 |
| 19 | 两 plane YCbCr 纹理 | RenderBox 实测用到 | `KNOWN` §5.1（严格说属 SYS 而非 WS，但在同一首帧路径上） |

**非必需（首帧可后置）**

sparse、tessellation、mesh、ray tracing、tile shading、imageblock、argument buffer tier 2、ICB、binary archive 的归档形式、rasterization rate map、counter、residency set、function pointer、Metal 4 全族、tensor、MSAA（首帧单采样即可，`INFERRED`）、多显示、cursor、ICC/gamma。

### 5.3 对既有 `MVP-1` 的修正

`docs/CAPABILITY_PROFILES.md` 的 `MVP-1` 要求 blend、depth/stencil、compute、indirect 全部报 false。按 §5.2，**blend 与 compute 是 WindowServer 必需**，depth/stencil 很可能必需。该档位作废（`00-OVERVIEW.md` §4.7 已声明），本文第 7 节给替代的排期视图。

`indirect` 确实可以首帧后置：没有证据表明 WindowServer 或 CoreAnimation 用 indirect draw 或 ICB。

### 5.4 常规 app 与 AppKit

| 层 | 增量需求（相对 §5.2） | 标签 |
|---|---|---|
| AppKit 基础窗口 | 不增加 Metal 特性，增加的是 `CAMetalLayer` → drawable → present 的路径（上游不做，本项目实现为 IOSurface + display provider） | `INFERRED` |
| 常规 2D / UI app | 多 color attachment、索引与实例化 draw、多 vertex buffer、mip 与 texture view、sampler 全集、压缩格式（BC/ASTC-LDR）、argument buffer tier 1 | `INFERRED` |
| 浏览器基础合成 | 上述 + argument buffer tier 2、MSAA + resolve、多队列 | `INFERRED` |
| 3D app / 游戏 | 上述 + tessellation（§4.2 缺）、mesh（部分缺）、ICB、binary archive、ray tracing（不做） | `INFERRED` |
| ML / 视频 app | tensor（不做）、Metal 4（不做） | `KNOWN` |

`BLOCKED`：**上述四行都是推断，没有在目标 guest 上对真实 app 做过 Metal 调用 trace。** 取得方法：`80-TEST-HARNESS.md` 的 guest agent 加一个 `MTLDeviceSPI` 调用计数器，跑 Safari、Finder、预览、一个 Metal 样例，导出 selector 命中直方图。这是把第一列从 `INFERRED` 升到 `KNOWN` 的唯一途径，优先级应高于补任何 L/XL 缺口。

---

## 6. 能力报告规则

沿用 `CAPABILITY_PROFILES.md` §5 并加强：

1. 未实现能力返回 false 或确定错误，不得返回"看起来成功"的默认值。
2. `INFERRED` 能力不得向 Metal 客户端报告为可用。
3. 只有 `TESTED` 能力可以进入发布 profile。
4. 每次发布保存 capability manifest，绑定 guest build（25G325）、Mesa/LLVM 版本、metal2vulkan commit SHA 与补丁哈希。
5. **`supportsFamily:` 必须由 `Device::family_blockers` 推出，不得硬编码**（§1.4）。
6. **能力报告必须消费上游的三个可观测通道**（详见 `40-RUNTIME-VULKAN.md` §7）：
   - `DegradeNotice` / `Degradation::code()`：给出 Metal 答案但代价不同的点；
   - `WorkCounts`：额外拷贝、丢弃的 draw、shadow 保留等计数；
   - 类型化 `Error`（`Unsupported` / `NotImplemented(RuntimeGap)` / `AppleOnly` / `Unproven`）：拒绝面。
   能力报告不得只写"支持/不支持"，必须同时写出该能力在本栈上的降级清单。
7. 本项目自己的 capability 查询实现必须能回答"为什么 false"。只答 false 的实现会让排障成本翻倍。

---

## 7. 排期视图（替代 `MVP-1` / `FULL-1` / `API-COMPLETE`）

分档只用于排期与报告，不裁剪规格（`00-OVERVIEW.md` §4.7）。

| 阶段 | 内容 | 对应 Gate | 工作量重心 |
|---|---|---|---|
| **S0 栈可用** | Vulkan loader + Lavapipe 在目标 guest 跑起来；只选 CPU device；清屏到真实 IOSurface | Gate 1–4 | `70` + `41` |
| **S1 翻译可用** | 真实 metallib 三角形；PipelineArtifact / BindingPlan 全量消费；像素比对 | Gate 4 | `30` + `31` + `40` |
| **S2 枚举可用** | kext accelerator + type-5 user client；`_MTLIOAccelDevice` init 链过关（**这里需要 §4.2 第 16 项的 54 个查询**）；Metal.framework 枚举到设备 | Gate 5 | `10` + `20` + `21` |
| **S3 测清第一列** | guest agent 的 selector 直方图；把 §5.4 从 `INFERRED` 升到 `KNOWN`；`family_blockers` 全量扫描 | — | `80` |
| **S4 首帧** | display provider；scanout；WindowServer 首帧（需 §5.2 全部 19 项） | Gate 6 | `11` + `12` |
| **S5 隔离与恢复** | helper 进程；跨进程 SharedEvent；崩溃恢复 | Gate 7 | `50` |
| **S6 补 S/M 缺口** | §4.2 的 S/M 级项（label/debug 优先，然后 pass descriptor、queue descriptor、residency set、parallel encoder、sampler lodBias） | — | 向上游提补丁 |
| **S7 补 L 缺口** | tessellation、simdgroup matrix、mesh 未建形式、counter | — | 按实测需求决定做不做 |
| **永不做** | Metal 4 全族、tensor、ML encoding、ray tracing、function stitching、`MTLIOCommandQueue`、tile shading、imageblock | — | 报 false |

**S3 的位置是本文最重要的排期判断**：在不知道系统实际调用什么之前，补任何 L/XL 缺口都是赌博。S3 的成本是几天，收益是让 S6/S7 的取舍有依据。

### 7.1 性能风险（非功能上限，但会决定"能不能用"）

| 风险 | 事实 | 缓解 |
|---|---|---|
| 着色器编译时间 | macOS 26 最大 CoreAnimation fragment 着色器 210,033 words；上游在独显驱动上测得约 1 s | 必须用 `Device::warm` + `PipelineRecord` 做跨进程预热；缓存目录随镜像预置 |
| 管线创建等待 vs guest 看门狗 | 上游默认 `pipeline_creation_wait` 与 `pipeline_commit_wait` 各 4.5 s，一个 host step 最多等 9 s；guest FIFO 检查为 10 s | 必须显式设定这两个值，并与 display provider 的超时策略对齐（`11-KERNEL-DISPLAY.md`） |
| simdgroup 模拟开销 | Lavapipe 子组宽 4 或 8，Metal 需要 32 → workgroup 内存 + barrier 模拟 | 合成路径的 kernel 尽量避免 simdgroup 函数；在 S3 的直方图里确认系统 kernel 是否用到 |
| 单队列串行化 | Lavapipe 单 `VkQueue` | present 队列与渲染队列的锁竞争要在 `50-IPC-HELPER.md` 里设计 |
| CPU 光栅化吞吐 | 1920×1080 `RGBA16Float` 合成，每帧全屏 | 分辨率与刷新率必须可配；首版可固定低分辨率 |

---

## 8. 证据来源清单

### 8.1 上游（metal2vulkan，commit `219f01365dc4c8eb346816c405b5b17403793764`）

| 文件 | 本文用到的内容 |
|---|---|
| `docs/METAL-COVERAGE.md` | 2135 项全量覆盖表，按 header 的 implemented / missing / out of scope 统计，missing 的工作量分级与构建顺序 |
| `docs/REFUSALS.md` | 125 条 translator 拒绝 + 70 条 runtime gap + 5 条 Apple-only + 9 条 binder 限额 + 14 条翻译上限，每条带设备条件、构造点、basis 与 reach；`FramebufferFetch` 行给出 WindowServer 登录路径证据 |
| `docs/RUNTIME-PORTING.md` | Metal selector ↔ runtime 方法的全量对照，"Composed from runtime calls" 与 "Not the runtime's" 两节给出边界 |
| `docs/ARCHITECTURE.md` | 翻译流水线各阶段与模块职责；设备 profile 的决定方式 |
| `docs/FAST-PATHS.md` | macOS 26 最大 CoreAnimation 着色器规模与编译时间 |
| `crates/metal2vulkan-runtime/README.md` | 公开 API 概览、设备创建选项、内存模型、降级通告、GPU family、范围外清单 |
| `crates/metal2vulkan-runtime/src/lib.rs` | 公开符号全集（`pub use` 列表） |
| `crates/metal2vulkan-runtime/src/families/mod.rs` | `GpuFamily` 全量取值与 raw 值；Apple feature set 表两版的列与行判定规则；`Refusal::PointSizeRange` 点名 lavapipe |
| `crates/metal2vulkan-runtime/src/capabilities.rs` | `DeviceProperties` 字段；`gpuCoreCount` 在 lavapipe 上无来源 |
| `crates/metal2vulkan-runtime/src/degradation.rs` | 降级种类全集；`shared-present-queue` 点名 lavapipe 单队列 |
| `crates/metal2vulkan/src/metal/format/mod.rs` | `MTLPixelFormat → VkFormat` 候选表（按位布局选择，不看设备名）；`formats_named_not_held!()`、`astc_without_a_vulkan_block!()`、`two_plane_ycbcr!()` 三个分组 |
| `crates/metal2vulkan/src/metal/generated.rs` | `PixelFormat` 全量 301 个取值与 raw 值 |
| `crates/metal2vulkan/src/device/subgroup.rs` | `Tier` 枚举（`Direct` / `Cluster32` / `PartialFragment` / `Emulated`）与 32 宽 simdgroup 的实现策略 |
| `crates/metal2vulkan-validation/src/runtime_lane/*.rs`、`src/bin/corpus-harvest.rs` | WindowServer / CoreAnimation / RenderBox 的实测形状与进程优先级 |

### 8.2 Mesa / Lavapipe

- [`src/gallium/frontends/lavapipe/lvp_device.c`](https://gitlab.freedesktop.org/mesa/mesa/-/blob/main/src/gallium/frontends/lavapipe/lvp_device.c)：`lvp_get_features`、`lvp_instance_extensions_supported`、`lvp_device_extensions_supported`、`lvp_get_properties`。本文 §2 的每一条都出自此文件。
- [Mesa 26.0.5 release notes](https://docs.mesa3d.org/relnotes/26.0.5.html)：Mesa 26.x 的 Vulkan API 版本声明。

### 8.3 Apple 官方

- [Discover Metal 4 (WWDC25 session 205)](https://developer.apple.com/videos/play/wwdc2025/205/)：Metal 4 的新命令结构、显式内存管理、资源管理变化。
- [Apple Developer – Metal](https://developer.apple.com/metal/)：Metal 4 的机器学习集成与编译效率定位。
- [Combine Metal 4 machine learning and graphics (WWDC25 session 262)](https://developer.apple.com/videos/play/wwdc2025/262)：tensor 资源与 ML encoder。
- [Support for Metal on Apple devices](https://support.apple.com/en-us/102894)：Metal 与 Metal 4 的设备支持清单（权威出处）。
- [Metal Feature Set Tables](https://developer.apple.com/metal/Metal-Feature-Set-Tables.pdf)：family 的逐行能力（2026-05-21 版 SHA-256 `9f31df15dd6827545702c5a0845f6e36e1889878cd0e534123bd70211e5c00a8`；2023-10-31 版的 archive 副本 SHA-256 `618a2f5d4ea92fdf58f8d7cc8daf525e0aad0000f96ccc1302424600e620c243`，两者的哈希由上游记录）。

引用 Apple 文档的段落均为转述，未连续摘录超过 30 词。**内容已转述以符合许可限制。**

### 8.4 本项目

- `docs/spec/00-OVERVIEW.md`：目标、边界、证据规则、被取代的结论。
- `docs/METAL2VULKAN_INTEGRATION.md`：上游接入合同与补缺规则。
- `docs/CAPABILITY_PROFILES.md`：旧档位定义（`MVP-1` 已按 `00-OVERVIEW.md` §4.7 作废，本文 §5.3 给出修正理由）。
- `analysis/macos26-iogpu-display-registration.md`、`analysis/macos26-guest-metal-driver-spec.md`：OS 集成侧的既有调查（注意其中 arm64 证据不适用于 x86 实现，见 `00-OVERVIEW.md` §4.1）。

---

## 9. 待关闭项

| ID | 内容 | 标签 | 关闭方法 | 阻塞谁 |
|---|---|---|---|---|
| C-01 | Intel Mac 在 macOS 26 上 `supportsFamily:` 的全量答案 | `BLOCKED` | 真机或已装 26 的 Intel 安装上跑 20 个家族值的扫描 | §1.4 的声明决定 |
| C-02 | WindowServer / CoreAnimation 的 selector 命中直方图 | `BLOCKED` | S3：guest agent 加调用计数器 | §5.2、§5.4 全部 `INFERRED` 行 |
| C-03 | 目标设备的 `VkPhysicalDeviceSubgroupProperties`（`subgroupSupportedStages`、quad 支持） | `BLOCKED` | guest 上跑 `vulkaninfo` 或上游的设备 dump | §3.4 的 quad 行 |
| C-04 | `family_blockers(Mac2)` / `(Metal3)` / `(Common3)` 在目标设备上的实际阻断行 | `BLOCKED` | S0 之后立即跑 | §1.4、§4.1 第 2 项 |
| C-05 | WindowServer 是否使用 depth/stencil attachment | `INFERRED` | C-02 的同一次 trace | §5.2 第 18 项 |
| C-06 | Lavapipe 在 macOS x86_64 上的实际构建可行性与 `apiVersion` | `BLOCKED` | `70-BUILD-PACKAGE.md` 的 Gate 1 | 本文第三列全部（现基于源码声明，非实测） |
| C-07 | Apple 私有格式族中系统实际用到哪些 | `BLOCKED` | C-02 的 trace 加 format 维度 | §3.6 最后一行的取舍 |
