# 43 - 上游覆盖面与拒绝面的全量矩阵

文档版本：1.0
基线：macOS Tahoe 26.7.2 build 25G325，**x86_64**
上游锚定：metal2vulkan commit `219f01365dc4c8eb346816c405b5b17403793764`
上游许可：`GPL-2.0-or-later OR LGPL-3.0-or-later`
上游工作副本：`upstream/m2v`（在 `.gitignore` 内，不进仓；本册只引用路径与符号名，不复制代码）
状态：有效。本文是 `60-CAPABILITY-MATRIX.md` 的一手数据底座与更正工单。

> 对上游文档只做转述与结构化。枚举名、计数、特性名、符号名是接口事实，照实记录；散文段落不连续摘录。**内容已转述以符合许可限制。**

## 0. 本文作用与读法

`60-CAPABILITY-MATRIX.md` 是在**没有上游一手数据**的情况下写的。本册拿到了上游工作副本，于是做三件事：

1. 用一手数据核实 `60` 引用的每个计数，错的逐条更正（§1、§7）；
2. 把上游的拒绝面做成**按处置分组的全量矩阵**，并给出「最严重缺口」的排序（§2、§3）；
3. 把 `60` §5 的 WindowServer 首帧 19 项与上游覆盖、上游拒绝、Lavapipe 做三方交叉，得出「第一版能不能出图」的结论性表（§4）。

另外两件由本册定案：`supportsFamily:` 的逐值答案（§5）与精度/快路径的配置（§6）。

### 0.1 数据来源的一手性

| 来源 | 性质 | 本册怎么用 |
|---|---|---|
| `upstream/m2v/scripts/metal-coverage/coverage.tsv` | 覆盖表的**生成源**（11 列、2135 行），`docs/METAL-COVERAGE.md` 由 `coverage.py` 从它生成 | §1 的全部计数直接从它统计，不从 Markdown 读 |
| `upstream/m2v/docs/METAL-COVERAGE.md` | 生成物，2135 行表格 + 总计 + 构建顺序分组 | 核对 §1 的统计与上游自报总计一致 |
| `upstream/m2v/docs/REFUSALS.md` | 生成物（`scripts/refusal-surface/refusal_surface.py` 从代码构造点生成），九节共 497 行表格 | §2、§3 的全部拒绝事实 |
| `upstream/m2v/crates/metal2vulkan-runtime/src/families/{mod,features,limits,formats}.rs` | family 审计的源码 | §5 的逐值答案 |
| `upstream/m2v/crates/metal2vulkan-runtime/src/driver_defects.rs` | 驱动缺陷表（按 `driverID` + `deviceID`） | §3.1 的 Lavapipe 缺陷全表 |
| `upstream/m2v/docs/FAST-PATHS.md` | 精度账本 | §6 |
| `upstream/m2v/crates/metal2vulkan{,-runtime}/src/**` 的模块文档 | 逐条机制说明 | §3.3、§4 的 Lavapipe 事实 |

### 0.2 标签与架构约定

沿用 `00-OVERVIEW.md` 第 7 节：

- `KNOWN`：上游源码、上游生成文档或公开 ABI 直接给出。本册的 `KNOWN` 一律写出 `upstream/m2v` 的文件路径加节名或符号名。
- `INFERRED`：由 `KNOWN` 输入推出的实现选择或算术结论，未实测。
- `BLOCKED`：缺运行证据。Lavapipe 侧凡是需要跑起来才知道的（实际 feature / format / limit 支持）一律标 `BLOCKED`，并注明「等 `build-lavapipe-macos` workflow 的产物」。
- `TESTED`：目标 guest 已验收。**本册没有 `TESTED` 行**；`91-RUNTIME-EVIDENCE.md` 的 `TESTED(25G76)` 行在本册中按其原标签引用。

架构标注：上游覆盖表对照 **macOS 27.0 SDK（Xcode 27.0 / 27A266a）**，与架构无关；Lavapipe 事实来自 Mesa 源码声明，与架构相关的部分（向量宽度、子组宽度）单独注明。

### 0.3 结论摘要

| # | 结论 | 标签 |
|---|---|---|
| 1 | `60` 的「2135 / 958 / 828 / 349」**全部正确**。单位是 macOS 27 SDK Metal 头文件的**公共条目**（class / protocol / category / property / method / class method / function），**不含 enum 值与常量**。`S 145 / M 147 / L 160 / XL 376` 也正确 | `KNOWN` §1.2、§1.3 |
| 2 | **XL 的 376 项 100% 是 Metal 4**（group `mtl4` 358 + `ml` 18）。L 的 160 项全部落在本项目已决定不做的范围。所以「不做 Metal 4 + 不做 tensor/IO queue/stitching」这一组决定，一次消掉 536 项中的 536 项，剩下要补的是 S+M = **292 项** | `KNOWN` §1.3 |
| 3 | `60` §1.1/§3.21/§4.3 的「Metal 4 合计 432 项」**错**。按 header 是 **519 项**（`MTL4*` 474 + `MTLTensor.h` 45），按上游工作分组的 missing 是 **455 项**（`mtl4` 369 + `ml` 18 + `tensor` 68） | `KNOWN` §1.6 |
| 4 | `60` §3.14 的 ray tracing「265 项」**不全**。out of scope 中注记为 ray tracing 的是 **303 项**；265 只是五个专属 header 的小计，另有 38 项散在 `MTLRenderCommandEncoder.h`、`MTLDevice.h`、`MTLHeap.h` 等 | `KNOWN` §1.5 |
| 5 | 拒绝面里 reach = `system` 的一共 **7 条**。`60` 只点了 3 条，漏了 `SamplerBicubicFilter`、`HostMemory`、`ExtendedRangeBlend`、`RuntimeGap::Render`。其中三条直接压在 WindowServer 首帧路径上 | `KNOWN` §2.3 |
| 6 | `60` §3.16/§4.2 的「tessellation 执行缺，every device not implemented」**错**。上游的 patch draw（直接与间接）**已建**：设备有 `tessellationShader` 时走设备阶段，没有时**模拟**。13 处拒绝是窄形式，reach = `rare` | `KNOWN` §7 R-05 |
| 7 | 本 commit 上 `Device::supports_family` 对 **20 个 `GpuFamily` 值全部返回 false**，在**任何** Vulkan 设备上都如此。原因不是 `PointSizeRange`，而是两条无条件 gap 行（`Linear textures`、`Fast resource loading`）。这与 `91` 观测到的 APV 全 false 一致 | `KNOWN` §5.2 |
| 8 | Lavapipe 的 framebuffer fetch 走 **input attachment 形式**（上游点名「both lavapipes of the venues」），是**精确**形式，不是降级。代价是每张 color render target 同时要 input attachment usage；**我们交给 runtime 的 image 若没有该 usage，fetch pass 会另开一张 scratch 并在 `Load`/`Store` 两侧各拷一次** | `KNOWN` §3.3、§4.4 |
| 9 | 上游点名 lavapipe 的 `RuntimeDriverDefect` 共 **5 条**，`60` 一条都没有。按 `40-RUNTIME-VULKAN.md` §7.4，它们必须进 capability manifest | `KNOWN` §3.1 |
| 10 | `60` §5.2 的 19 项里，**10 项**被 refusal 或 Lavapipe 挡住或强制降级，1 项（blend 的 `independentBlend`）`BLOCKED` 待 Lavapipe 构建。最致命的是第 7 项 `RGB10A8_2P_XR10` | `KNOWN` + `INFERRED` §4.2 |

---

## 1. 覆盖面：那张表的单位、分档与精确计数

### 1.1 行的单位

`KNOWN`（来源：`upstream/m2v/docs/METAL-COVERAGE.md` 开头的生成说明 + `scripts/metal-coverage/coverage.tsv` 的 `kind` 列）

上游表的每一行是 **macOS 27.0 SDK（Xcode 27.0 / 27A266a）Metal 头文件的一个公共条目，按名字计**。`coverage.tsv` 有 11 列：`header`、`container`、`kind`、`name`、`deprecated`、`status`、`crate`、`counterpart`、`note`、`size`、`group`。`kind` 的全量取值与计数：

| `kind` | 项数 |
|---|---|
| `property` | 1049 |
| `method` | 801 |
| `class` | 153 |
| `protocol` | 79 |
| `class method` | 30 |
| `function` | 21 |
| `category` | 2 |
| 合计 | **2135** |

三件事由此确定，三件都对读法有影响：

1. **不是 selector 数。** `method` 与 `class method` 合计 831，只占 39%；超过一半的行是 `property`。一个属性在 ObjC 里是一到两个 selector，所以「2135」比实际 selector 数**偏小**。
2. **不是特性数。** 一个特性（例如 tessellation）横跨多个 header 的多个 property/method，在表里是多行；反过来，一行也可能只是某个 descriptor 的一个字段。
3. **不含 enum 值与常量。** `kind` 里没有 `enum` / `constant`。所以 `MTLPixelFormat` 的 301 个取值**不是 301 行**（`MTLPixelFormat` 本身不在表内，格式能力落在 `MTLDevice.h` 与 `MTLTexture.h` 的若干行上）。`40-RUNTIME-VULKAN.md` §8 的 301 个格式与本表的 2135 项是**两个互不相干的计数系**，不得相加或相除。

**与「AIR 指令数」无关。** 上游的 AIR 指令集在 `crates/metal2vulkan-air` 内，与本表不共享任何计数。`60` 把这组数定为「macOS 27 SDK Metal 公共 API 条目数，不是 AIR 指令数」是对的。

### 1.2 状态三分与精确计数

`KNOWN`（来源：`coverage.tsv` 的 `status` 列，`I`/`M`/`O`；与 `METAL-COVERAGE.md` 的 Totals 表一致）

| 状态 | 含义（转述自上游生成说明） | 项数 | 其中 `deprecated` |
|---|---|---|---|
| implemented（`I`） | 对应物能答它。调用仍可能拒绝部分输入，拒绝面与设备条件在 `REFUSALS.md` | **958** | 36 |
| missing（`M`） | 还没有对应物。`size` 列给出建它的工作量。缺的调用**不会答错**：需要它的程序建不起来 | **828** | 27 |
| out of scope（`O`） | ray tracing、多 GPU、macOS 专属服务、IOSurface、drawable、源码编译（归消费者），以及 macOS 不提供的项 | **349** | 5 |
| 合计 | | **2135** | 68 |

implemented 的 958 项按 crate 拆分（`crate` 列）：**runtime 答 635 项**，**translator 的值类型答 323 项**。再按 kind 交叉的前几位：runtime 的 method 354、translator 的 property 223、runtime 的 property 216、translator 的 class 43 与 method 43。

**结论：`60` §0.2 引用的「2135 / 958 / 828 / 349」与「runtime 635 / translator 323」全部核实通过，无需更正。** 需要补的只是 §1.1 的单位说明。

### 1.3 分档 S/M/L/XL 的含义与精确计数

`KNOWN`（来源：`METAL-COVERAGE.md` 的 missing 定义 + `coverage.tsv` 的 `size` 列）

分档只挂在 **missing** 行上（`size` 列在 implemented 与 out of scope 行上为空，1307 行为空，828 行有值）。含义是**建它要多久**，不是「它有多重要」，也不是「它有多难」：

| 档 | 上游定义（转述） | 项数 |
|---|---|---|
| `S` | 一天或更少 | **145** |
| `M` | 若干天 | **147** |
| `L` | 一周或更多 | **160** |
| `XL` | 一个新子系统 | **376** |
| 合计 | | **828** |

`60` §0.2 的「S 145、M 147、L 160、XL 376」核实通过。但 `60` §4.4 把 L 与 XL 混在一起讲「明确不做」，丢掉了本册最有用的一个事实：

**XL 的 376 项全部是 Metal 4。** `KNOWN`（`coverage.tsv` 的 `group` × `size`）：

| `group` | `size` | 项数 |
|---|---|---|
| `mtl4` | XL | 358 |
| `ml` | XL | 18 |
| 合计 XL | | **376** |

**L 的 160 项也全部落在本项目已决定不做的范围内：**

| `group` | 项数 | 本项目的既有决定 |
|---|---|---|
| `tensor` | 68 | 不做（`60` §3.20） |
| `io`（`MTLIOCommandQueue`） | 44 | 不做（`60` §3.9） |
| `stitching` | 24 | 不做（`60` §3.13） |
| `mtl4`（counter heap） | 11 | 不做（`60` §1.3） |
| `shadervalidation` | 6 | 不做（`60` §3.3） |
| `persistent`（macOS 27 新增） | 5 | 基线无此 API |
| `access-counters`（上游标「未排期」） | 2 | 不做（`60` §3.5） |
| 合计 L | **160** | |

于是工作量分配可以给出精确数，不必说「约 300 项」：

| 分类 | 项数 | 对本项目的意义 |
|---|---|---|
| L + XL | **536** | 一次性全部划出：Metal 4 面 387（`mtl4` 369 + `ml` 18）、tensor 68、IO queue 44、stitching 24、shader validation 6、persistent kernel 5、access counter 2 |
| S + M | **292** | 这是本项目**真正要补的**上游缺口 |
| 其中 group `queries`（S、54 项） | 54 | `_MTLIOAccelDevice` 的 `initLimits` / `initFeatureQueries` 链会读。`60` §4.2 第 16 项的「54 项」核实通过 |

`INFERRED`：把 S+M 的 292 项当作「上游补缺」的工作量上界是安全的，因为其中 `capture` 25 项（GPU capture）、`logging` 20 项（shader logging）、`counters` 54 项（counter sample buffer）本项目已决定第一版不做。扣掉这三组后要补的是 **193 项**。

### 1.4 missing 的全量分组（38 组）

`KNOWN`（来源：`coverage.tsv` 的 `group` 列；上游 `METAL-COVERAGE.md` 的 "Missing, in build order" 节是同一分组的构建顺序视图）

| `group` | `size` | 项数 | 本项目处置 |
|---|---|---|---|
| `mtl4` | XL 358 + L 11 | 369 | 不做（`60` §1.3） |
| `tensor` | L | 68 | 不做 |
| `queries`（device / state / resource 查询） | S | 54 | **自行实现，最高优先级**：枚举链前置 |
| `counters`（counter sample buffer） | M | 54 | 第一版不做，`counterSets` 返回空 |
| `io` | L | 44 | 不做 |
| `capture`（GPU capture） | S | 25 | 不做 |
| `residency`（`MTLResidencySet`） | M | 25 | 向上游补或第一版报 false |
| `stitching` | L | 24 | 不做 |
| `logging`（shader logging） | M | 20 | 第一版不做 |
| `ml` | XL | 18 | 不做 |
| `labels`（label / debug group / signpost） | S | 17 | **自行实现，高优先级**：排障刚需 |
| `viewpool`（texture / resource view pool） | M | 14 | 第一版不做 |
| `cmdbuf`（command buffer descriptor 与编码器错误状态） | S 6 + M 6 | 12 | 自行实现（薄层） |
| `mesh-descriptor` | S | 12 | 自行实现（薄层） |
| `passdesc`（compute / blit / resource-state pass descriptor） | S | 10 | 自行实现（薄层） |
| `parallel`（parallel render encoding） | M | 9 | 向上游补 |
| `shadervalidation` | L | 6 | 不做 |
| `colormap`（color attachment mapping） | M | 6 | 第一版不做 |
| `persistent` | L | 5 | 基线无此 API |
| `archive`（更多 binary archive 条目） | S | 4 | 自行实现（薄层） |
| `function-handles` | S | 4 | 自行实现（薄层） |
| `queue`（command queue descriptor） | S | 3 | 自行实现（薄层） |
| `access-counters` | L | 2 | 不做 |
| `barriers`（`textureBarrier` 与 queue-stage barrier） | S 1 + M 1 | 2 | 自行实现 |
| `reflection`（创建后读 pipeline 的 `reflection`） | S | 2 | 自行实现 |
| `library`（从文件路径或 URL 建 library） | S | 2 | 自行实现（薄层） |
| `notifications`（设备热插拔） | M | 2 | 不做（单设备） |
| `sparse`（placement sparse page size） | S | 2 | 不可行（§3.2） |
| `compression`（有损纹理压缩） | M | 2 | 不做 |
| `min-lod`（macOS 27 新增） | M | 2 | 基线无此 API |
| `icb-depth-stencil` | M | 2 | 不做 |
| `sparsebuf`（placement sparse buffer） | M | 1 | 不可行 |
| `events`（`MTLSharedEventListener.sharedListener`） | S | 1 | 自行实现 |
| `functions`（`specializedName`） | S | 1 | 自行实现 |
| `depthbounds` | M | 1 | 向上游补 |
| `visibility`（累积 visibility result） | S | 1 | 自行实现 |
| `specialization`（macOS 26 的 pipeline specialization） | M | 1 | 第一版不做 |
| `lod-bias`（sampler 的 `lodBias`） | M | 1 | 向上游补 |

### 1.5 覆盖面按对象族的分布

`KNOWN`（来源：`coverage.tsv` 按 `header` 聚合，91 个 header）

**近全覆盖的族**（implemented 占绝对多数，missing 为 0 或个位数）：

| header | impl / miss / oos | 读法 |
|---|---|---|
| `MTLIndirectCommandEncoder.h` | 35 / 0 / 0 | **全覆盖** |
| `MTLVertexDescriptor.h` | 19 / 0 / 0 | 全覆盖 |
| `MTLStageInputOutputDescriptor.h` | 21 / 0 / 0 | 全覆盖 |
| `MTLResourceStateCommandEncoder.h` | 7 / 0 / 0 | 全覆盖（但 sparse 在 macOS 宿主上不可用，§3.2） |
| `MTLVisibleFunctionTable.h` | 7 / 0 / 0 | 对象全覆盖，**调用被拒绝**（`Feature::DynamicCall`） |
| `MTLLinkedFunctions.h` | 6 / 0 / 0 | 同上（`Feature::Linking`） |
| `MTLDynamicLibrary.h` | 5 / 0 / 0 | 同上 |
| `MTLFunctionConstantValues.h` | 5 / 0 / 0 | 全覆盖 |
| `MTLPipeline.h` | 5 / 0 / 0 | 全覆盖 |
| `MTLFence.h` | 3 / 0 / 0 | 全覆盖 |
| `MTLTypes.h` | 7 / 0 / 0 | 全覆盖 |
| `MTLRasterizationRate.h` | 37 / 0 / 1 | 37/38，`60` §3.18 核实通过 |
| `MTLRenderCommandEncoder.h` | 119 / 4 / 9 | 9 个 oos 全是 ray tracing |
| `MTLComputeCommandEncoder.h` | 36 / 1 / 3 | 3 个 oos 全是 ray tracing |
| `MTLIndirectCommandBuffer.h` | 26 / 0 / 1 | |
| `MTLHeap.h` | 25 / 1 / 4 | |
| `MTLRenderPipeline.h` | 114 / 30 / 1 | 30 个 missing 含 mesh descriptor 12 项 |
| `MTLArgument.h` | 77 / 17 / 0 | 17 个 missing 全是 tensor 反射 |
| `MTLTexture.h` | 57 / 12 / 4 | |
| `MTLLibrary.h` | 45 / 2 / 19 | 19 个 oos 是 MSL 源码编译 |

**完全空的族**（implemented = 0）：

| 分类 | header（项数全为 missing，除注明） |
|---|---|
| Metal 4 命令模型 | `MTL4RenderCommandEncoder.h` 42、`MTL4RenderPipeline.h` 40、`MTL4ComputeCommandEncoder.h` 32（+6 oos）、`MTL4Compiler.h` 29、`MTL4MeshRenderPipeline.h` 27、`MTL4CommandQueue.h` 22、`MTL4CommandBuffer.h` 18、`MTL4RenderPass.h` 18、`MTL4ArgumentTable.h` 15、`MTL4LinkingDescriptor.h` 14、`MTL4MachineLearningPipeline.h` 14、`MTL4CommandEncoder.h` 12、`MTL4ComputePipeline.h` 12、`MTL4TileRenderPipeline.h` 10、`MTL4Counters.h` 9、`MTL4Archive.h` 7、`MTL4CommandAllocator.h` 7、`MTL4PipelineState.h` 6、`MTL4PipelineDataSetSerializer.h` 5、`MTL4BinaryFunctionDescriptor.h` 4、`MTL4CommitFeedback.h` 4、`MTL4CompilerTask.h` 4、`MTL4LibraryDescriptor.h` 4、`MTL4MachineLearningCommandEncoder.h` 4、`MTL4SpecializedFunctionDescriptor.h` 4、`MTL4BinaryFunction.h` 3、`MTL4LibraryFunctionDescriptor.h` 3、`MTL4StitchedFunctionDescriptor.h` 3、`MTL4BufferRange.h` 1、`MTL4FunctionDescriptor.h` 1 |
| ML / tensor | `MTLTensor.h` 45 |
| pass descriptor 薄层 | `MTLComputePass.h` 11、`MTLBlitPass.h` 10、`MTLResourceStatePass.h` 10 |
| 计数与调试 | `MTLCounters.h` 15、`MTLFunctionLog.h` 11、`MTLCaptureManager.h` 17（+1 oos）、`MTLCaptureScope.h` 7、`MTLLogState.h` 5 |
| 未建的 API 族 | `MTLFunctionStitching.h` 22、`MTLResidencySet.h` 18、`MTLIOCommandBuffer.h` 18、`MTLIOCommandQueue.h` 17、`MTLIOCompressor.h` 4、`MTLResourceViewPool.h` 9、`MTLTextureViewPool.h` 4、`MTLParallelRenderCommandEncoder.h` 8 |
| 全部 out of scope | `MTLAccelerationStructure.h` 129、`MTL4AccelerationStructure.h` 94、`MTLAccelerationStructureCommandEncoder.h` 25、`MTLIntersectionFunctionTable.h` 15、`MTLAccelerationStructureTypes.h` 2、`MTLDrawable.h` 7、`MTLDeviceCertification.h` 3 |

**out of scope 的 349 项按理由拆分**（`KNOWN`，`coverage.tsv` 的 `note` 列）：

| 理由 | 项数 | 对本项目的意义 |
|---|---|---|
| ray tracing | **303** | 不做（`60` §3.14） |
| MSL 源码编译（着色器以 metallib 或 AIR 进入） | 19 | 与 `RuntimeGap::LibrarySource` 是同一件事的两面（§2.5） |
| presentation（无 `CAMetalLayer`、无 drawable，由消费者 present） | 10 | **本项目本体**（`11-KERNEL-DISPLAY.md`） |
| 多 GPU 的 peer-group 视图 | 4 | 单设备，不做 |
| IOSurface 归消费者 | 3 | **本项目本体**（`41-IOSURFACE-USERSPACE.md`） |
| 进程与 device-certification 状态属 OS | 3 | 不做 |
| macOS 不提供 | 2 | n/a |
| app bundle 的 `default.metallib` | 2 | 本项目本体 |
| GCD dispatch queue 属 macOS | 2 | 本项目本体（`50-IPC-HELPER.md`） |
| 向另一个 task 记账内存 | 1 | 不做 |
| 合计 | **349** | |

**更正**：`60` §3.14 写「上游明确范围外，265 项」。265 是五个专属 header 的小计（`MTLAccelerationStructure.h` 129 + `MTL4AccelerationStructure.h` 94 + `MTLAccelerationStructureCommandEncoder.h` 25 + `MTLIntersectionFunctionTable.h` 15 + `MTLAccelerationStructureTypes.h` 2）。注记为 ray tracing 的 out of scope 行实际是 **303 项**，另外 38 项散在：`MTLRenderCommandEncoder.h` 9、`MTL4ComputeCommandEncoder.h` 6、`MTLDevice.h` 5、`MTLHeap.h` 4、`MTLArgumentEncoder.h` 3、`MTLComputeCommandEncoder.h` 3、`MTLCommandBuffer.h` 2、`MTLLibrary.h` 2、`MTLComputePipeline.h` 1、`MTLFunctionDescriptor.h` 1、`MTLIndirectCommandBuffer.h` 1、`MTLRenderPipeline.h` 1。`KNOWN`

这 38 项有实操意义：它们是**普通 encoder 与 device 上的 ray tracing 接缝**（`useResource:`、heap 的加速结构分配、argument encoder 的加速结构槽位等）。本项目报 false 时必须连这 38 项一起报，不能只报五个专属 header。

### 1.6 Metal 4 面的精确边界

`60` §1.1 写「上游表中 `MTL4*` 与 `MTLTensor` 合计约 **432 项**（Metal 4 命令模型 369 + ML encoding 18 + tensors 45）」，§3.21 与 §4.3 沿用了这个数。**这个数错了**，错在把两种不同的切法混用。`KNOWN`

两种切法各自的精确值：

| 切法 | 口径 | 项数 |
|---|---|---|
| **按 header** | `MTL4*` 的 31 个 header + `MTLTensor.h` | **519** = `MTL4*` 474（missing 374 + out of scope 100）+ `MTLTensor.h` 45 |
| **按上游工作分组** | `group` ∈ {`mtl4`, `ml`, `tensor`} 的 missing 行 | **455** = `mtl4` 369 + `ml` 18 + `tensor` 68 |

两者差在三处，每处都要说清：

1. `MTL4*` header 里有 **100 项 out of scope**，全部是 ray tracing（`MTL4AccelerationStructure.h` 94 + `MTL4ComputeCommandEncoder.h` 的 6 个加速结构命令）。按分组切时它们归 ray tracing，不归 Metal 4。
2. `group = mtl4` 里有 **13 项不在 `MTL4*` header 内**：它们是 `MTLDevice.h` 上的 Metal 4 入口（`newMTL4CommandQueue`、`newMTL4CommandQueueWithDescriptor:error:`、`newCommandBuffer`、`newCommandAllocator`、`newCommandAllocatorWithDescriptor:error:`、`newArgumentTableWithDescriptor:error:`、`newCompilerWithDescriptor:error:`、`newArchiveWithURL:error:`、`newPipelineDataSetSerializerWithDescriptor:`、`newCounterHeapWithDescriptor:error:`、`sizeOfCounterHeapEntry:`、`functionHandleWithFunction:`、`functionHandleWithBinaryFunction:`）。**这 13 个 selector 是本项目必须返回 nil 的那一批**，它们挂在 `MTLDevice` 上，不在 `MTL4*` 里，最容易被漏掉。
3. `group = tensor` 的 68 项里只有 45 项在 `MTLTensor.h`，另 23 项是反射侧：`MTLArgument.h` 17、`MTLDevice.h` 3、`MTLBlitCommandEncoder.h` 2、`MTLBuffer.h` 1。

**本册给 `60` 的替换文本**（`KNOWN`）：

> macOS 26 的 Metal 4 面，按 header 是 519 项（`MTL4*` 474 + `MTLTensor.h` 45）；去掉其中 100 项 ray tracing 后，上游要建而未建的 Metal 4 工作是 **455 项**：命令模型 369（XL 358 + L 11）、machine learning encoding 18（XL）、tensor 68（L）。命令模型的 369 项中有 13 项挂在 `MTLDevice` 上，不在 `MTL4*` header 内。

`60` §4.3 的「`MTLTensor` + ML encoding（63 项）」同样要改：63 = `MTLTensor.h` 45 + `ml` 18，混用了 header 与 group；按 group 是 **86 项**（`tensor` 68 + `ml` 18）。`KNOWN`

### 1.7 `60` 第 3 节逐 header 计数的核对结果

`KNOWN`。`60` 第 3 节的每个小节末尾都给了该功能域的 header 覆盖数。全部 56 处逐一核对，**结果全部一致**，包括 `MTLDevice.h` 73/71/10、`MTLRenderPipeline.h` 114/30/1、`MTLRenderCommandEncoder.h` 119/4/9、`MTLCommandBuffer.h` 21/21/5、`MTLTexture.h` 57/12/4、`MTLArgument.h` 77/17/0、`MTLResidencySet.h` 0/18/0、`MTLFunctionStitching.h` 0/22/0、`MTLRasterizationRate.h` 37/0/1。`60` §1.2 的 Metal 4 对象族分表（51 / 72 / 56 / 16 / 164 / 12 / 9 / 45 / 94）也逐项核对一致。

**这意味着 `60` 第 3 节不需要改计数，只需要改 §1.1/§3.14/§3.21/§4.3 的四处汇总数，以及 §3.16 的 tessellation 结论。**

---

## 2. 拒绝面：七类拒绝的全量矩阵

### 2.1 七类的规模与 basis 分布

`KNOWN`（来源：`upstream/m2v/docs/REFUSALS.md` 的 Totals 与 Totals by basis 两表；逐行重新统计一致）

`REFUSALS.md` 记的是「**Metal 接受而上游拒绝**」的每一处。九节的前七节是拒绝面，后两节（第 8、9 节）是「调用做错了什么」，即上游主张 **Metal 自己也拒绝**该输入。两者性质不同，处置也不同。

| 节 | 类别 | variant 数 | 有构造点 | reach `system` | `app` | `rare` | `none` |
|---|---|---|---|---|---|---|---|
| 1 | translator / 前端拒绝（`Unsupported`：一个 `Feature` 与它的 `Needs`） | 125 | 125 | **6** | 32 | 70 | 17 |
| 2 | runtime gap（`Error::NotImplemented(RuntimeGap)`） | 70 | 70 | **1** | 8 | 45 | 16 |
| 3 | Apple-only 调用（`Error::AppleOnly`） | 5 | 5 | 0 | 0 | 0 | 5 |
| 4 | binder 在设备限额上的拒绝（`BindError`） | 9 | 9 | 0 | 1 | 7 | 1 |
| 5 | 翻译上限（`Error::LimitExceeded(Limit)`） | 14 | 14 | 0 | 0 | 7 | 7 |
| 6 | rate map 编译层不编译的（`Error::RateMap(UnpinnedCompile)`） | 5 | 5 | 0 | 0 | 4 | 1 |
| 7 | 翻译期限（`Error::Budget`） | 1 | 1 | 0 | 0 | 0 | 1 |
| 8 | 「调用做错了什么」（`Error::Metal(MetalError)` 的 `Problem`） | 64 | 64 | — | — | — | — |
| 9 | 同上的细分 problem 枚举 | 164 | 149 | — | — | — | — |

basis 分布（`KNOWN`）：

| 类别 | `metal-measured` | `metal-documented` | `metal-takes` | `device` | `ours` | `unknown` | `delegated` | `-` |
|---|---|---|---|---|---|---|---|---|
| translator / 前端 | 0 | 0 | 0 | 48 | 54 | 0 | 0 | 23 |
| runtime gap | 0 | 0 | 0 | 0 | 70 | 0 | 0 | 0 |
| Apple-only | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 5 |
| binder 限额 | 0 | 0 | 0 | 9 | 0 | 0 | 0 | 0 |
| 翻译上限 | 0 | 0 | 0 | 0 | 14 | 0 | 0 | 0 |
| rate map | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 5 |
| 翻译期限 | 0 | 0 | 0 | 0 | 1 | 0 | 0 | 0 |
| 调用做错了什么 | 20 | 3 | 5 | 0 | 11 | 8 | 17 | 0 |
| 同上细分 | 57 | 27 | 23 | 0 | 31 | 26 | 0 | 0 |

**`60` §8.1 对 `REFUSALS.md` 的描述（125 + 70 + 5 + 9 + 14）核实通过**，`40-RUNTIME-VULKAN.md` §7.3 的表也核实通过（含第 8、9 节的 64 / 164 与 basis 分布）。

### 2.2 三列的读法与本项目的处置映射

`KNOWN`（来源：`REFUSALS.md` 的列定义，转述）

| 列 | 取值 | 本项目怎么用 |
|---|---|---|
| **Where** | `every device (not implemented)`、`every device (no Vulkan mechanism)`、`every device (runtime piece not built)`、`devices without <VkFeature/VkExtension/VkProperty/VkLimit>`、`devices short of a device limit the site names`、`devices without a capability the site computes`、`drivers with a defect <name>` | **这一列区分「Lavapipe 的问题」与「上游的问题」**。前三个取值与设备无关，换 ICD 也不会变；后四个要在目标设备上实测 |
| **Basis** | `device`（机制不存在）、`ours`（上游自己的缺口、上限或期限）、`metal-takes`（**纯 Metal 接受该输入，所以这个拒绝越过了 Metal**）、`metal-measured`、`metal-documented`、`unknown`、`delegated`、`-` | `metal-takes` 共 5 + 23 = 28 条，是上游自己记录的开放缺陷。**能力报告必须把这些点标为「比 Metal 严格」**（`40` §7.3 要求） |
| **Reach** | `system`（guest 的 CoreAnimation / CoreImage / VideoToolbox 可能碰到）、`app`、`rare`、`none` | **优先级排序的唯一依据** |

本项目的四种处置，按 Where + Reach 推出（`INFERRED`，这是实现选择）：

| 处置 | 适用条件 | 做法 |
|---|---|---|
| **descriptor 期拦** | 拒绝发生在 pipeline / texture / sampler descriptor 的某个字段上，且该字段在 `22-OBJC-DESCRIPTORS.md` 的反序列化路径上可见 | 在 ObjC descriptor setter 或反序列化时就返回确定错误，不要让它走到 translator。好处是错误点离调用点近，排障成本低 |
| **运行期降级** | 上游给出近似等价物并发 `DegradeNotice` | 按 `40` §7.1 消费：只用 `Degradation::code()` 与 `category()`，**禁止解析通告文本**。记进 capability manifest 的降级清单 |
| **向上报错** | Where 含 `every device`，且 Reach 为 `app` 或 `rare` | 把 `Unsupported::needs` 转成稳定 wire error（`50-IPC-HELPER.md`），capability 查询答 false 并能回答「缺什么」（`60` §6 第 7 条） |
| **我们自己补实现** | Reach = `system`，或 Reach = `app` 且命中 `60` §5 的 19 项 | 进 §2.7 的排序表 |

### 2.3 reach = `system` 的七条：真正的优先级表

`KNOWN`（来源：`REFUSALS.md` 第 1、2 节的 Reach 列全量筛选）

这是本册最该先看的一张表。`60` 点名了三条（`Lowering`、`FramebufferFetch`、`Format`），**漏了四条**，其中三条压在 WindowServer 首帧路径上。

| # | 变体 | 类 | 构造点数 | Where | Basis | 上游记录的触达证据（转述） | 本项目处置 |
|---|---|---|---|---|---|---|---|
| 1 | `Feature::Format` | translator | **120** | 多条设备条件 + `every device (no Vulkan mechanism)` + `every device (not implemented)` | `ours` | 设备对某个用途缺该像素格式；上游点名 CoreVideo 的 4:2:x 与 10 位格式在其中 | **按格式分治**：`40` §8 的候选表 + `Device::pixel_format_capabilities` 实测；不在候选集的报确定错误（`41` §3.4.1 已定）。descriptor 期拦 |
| 2 | `Feature::Lowering(LowerFamily)` | translator | **35** | `devices short of a device limit`、`devices without VkFeature::ShaderDemoteToHelperInvocation`、`every device (not implemented)` | `ours` | 尚未落地的 lowering family 的 catch-all：**任何着色器都可能撞上一条** | **只能向上报错并记录命中的 `LowerFamily`**。13 个 family：`Arith`、`Access`、`Texture`、`Sampler`、`Simd`、`Barrier`、`MemoryModel`、`Fragment`、`StageIo`、`Dispatch`、`Tessellation`、`RayTracing`、`Mesh`。排障时必须打印是哪个 family |
| 3 | `Feature::FramebufferFetch` | translator | **24** | 多条设备条件 + `drivers with a defect` + `every device (not implemented)` | `ours` | 可编程混合；**macOS 26.6.2 的登录流程命中它**（两条 WindowServer 与 RenderBox 管线 fetch `RGB10A8_2P_XR10` attachment） | Lavapipe 有 **input attachment 形式**（§3.3），走精确路径。但必须保证 image 带 input attachment usage（§4.4） |
| 4 | `Feature::ExtendedRangeBlend` | translator | **5** | `every device (not implemented)` | `ours` | XR10 attachment 被四个 `half`/`float` lane 之外的输出混合；16 位 float attachment 的 storage 形式下 second-source factor 或 fast math 下单通道写掩码的混合；**上游记明「消费者的 guest 在混合 `RGB10A8_2P_XR10` attachment」** | **最危险的一条**（§4.2）。descriptor 期拦 + 向上报错 |
| 5 | `Feature::SamplerBicubicFilter` | translator | **5** | `every device (not implemented)` | `ours` | 没有 Metal 读数支撑的 bicubic 形式；**macOS 26.6.2 建过一个 `MTLSamplerMinMagFilterCubic` 的 runtime sampler（消费者的启动路径）**，其 mip-filtered 形式被拒绝 | **`60` 完全漏掉**。descriptor 期拦：`MTLSamplerDescriptor` 的 cubic filter 组合在建 sampler 时就判，不要等到采样 |
| 6 | `Feature::HostMemory` | translator | **7** | `devices without VkExtension::ExtExternalMemoryHost`、`drivers with defect UnpinnablePagesBreakHostMemory`、`every device (no Vulkan mechanism)`、`every device (not implemented)` | `ours` | 设备无法导入该内存时的 `newBufferWithBytesNoCopy:` | **`60` §5.2 第 11 项正是它**。Lavapipe 导入指针（§3.3），但本项目必须按 `41` §2.3 的决策树处理每一条退路，并把 `import-gate-refused` 记进 `m2vu-surface-import` |
| 7 | `RuntimeGap::Render` | runtime gap | **26**（上游注「20 处见附录」） | `every device (runtime piece not built)` | `ours` | render pipeline、pass 与 draw 的若干形式未建：render pass、resolve 与 attachment 形式 | **`60` §5.2 第 3 项正是它**。向上报错 + 逐形式清单化。family 审计里 `Texture barriers`、`Visibility count accumulation`、`Depth bounds testing` 三行都落在这个 gap 上 |

`INFERRED`：这七条合起来就是「系统进程会撞上的全部上游拒绝」。第 1、2 条是面（任何着色器、任何格式都可能命中），第 3–6 条是点（可以逐个关掉），第 7 条是一组未建的 render 形式。**排期上先关点，再按 S3 的直方图（`60` §7）决定面要补到什么程度。**

### 2.4 translator / 前端拒绝（125 条）按处置分组

`KNOWN`（变体名、Where、构造点数、Reach 来自 `REFUSALS.md` 第 1 节；处置列为 `INFERRED`）

#### 2.4.1 组 A：与设备无关的上游缺口（Where 含 `every device`，Reach `app` 或 `system`）

**这一组是本项目可以自己补或必须向上游补的，换 ICD 无用。**

| 变体 | 构造点 | Reach | 本项目处置 |
|---|---|---|---|
| `Format` | 120 | system | 按格式分治（§2.3 #1） |
| `Lowering` | 35 | system | 向上报错 + 记 `LowerFamily`（§2.3 #2） |
| `FramebufferFetch` | 24 | system | Lavapipe 有精确形式（§3.3） |
| `HostMemory` | 7 | system | 按 `41` §2.3 决策树（§2.3 #6） |
| `ExtendedRangeBlend` | 5 | system | descriptor 期拦（§2.3 #4） |
| `SamplerBicubicFilter` | 5 | system | descriptor 期拦（§2.3 #5） |
| `ArgumentBufferTextures` | 16 | app | 适配：受设备限额。限额不足时诚实报 tier 1 |
| `TextureView` | 9 | app | 向上报错；按 `60` §3.6 的 view 规则逐形式补 |
| `TextureSwizzle` | 7 | app | **向上游补**：family 审计的 `Texture swizzle` 行无条件阻断（§5.2） |
| `MipmapGeneration` | 6 | app | 向上游补或走 compute 滤波 |
| `SamplerBorderColor` | 4 | app | Lavapipe 有 `VK_EXT_custom_border_color`；剩余形式向上报错 |
| `DivergentImplicitLod` | 1 | app | 第一版拒绝（`60` §3.7 已定） |
| `UndeclaredTextureUsage` | 2 | app | **basis 为 `ours` 且 Metal 会跑**：这是「比 Metal 严格」的一条。本项目在 descriptor 期把 usage 补齐，不要让它发生 |
| `SamplerAddressMode` | 2 | app | Lavapipe 有 `samplerMirrorClampToEdge`；剩余形式报错 |
| `ProgramScopeBinding` | 2 | app | MSL 3.2 的 program-scope buffer binding（macOS 15 起）。向上报错 |

#### 2.4.2 组 B：设备条件决定（Where 全是设备条件，Basis `device`）

**这一组的答案要等 Lavapipe 构建出来才知道，全部 `BLOCKED`（等 `build-lavapipe-macos` workflow 的产物）。**

| 变体 | 构造点 | Reach | 设备条件（Where 摘要） |
|---|---|---|---|
| `SimdWidth` | 2 | app | `VkProperty::MetalFragmentSimdgroups`，以及站点自算的 `width_needs(stage, st)` |
| `QuadOperations` | 2 | app | `VkLimit::MinSubgroupSize`、`VkProperty::SubgroupQuadOperationsInAllStages` |
| `SubgroupOperations` | 4 | app | `VkFeature::ShaderQuadControl`、`ShaderSubgroupExtendedTypes`、`VkProperty::SubgroupStage` |
| `DescriptorCount` | 3 | app | 站点点名的设备限额、`VkLimit::MaxUniformBufferRange` |
| `BufferRange` | 7 | app | 站点自算、buffer device address、`every device (no Vulkan mechanism)` |
| `TexelOffset` | 2 | app | 站点点名的设备限额 |
| `TexelBuffer` | 3 | app | 格式的 usage |
| `TextureSize` | 1 | app | 站点点名的设备限额 |
| `TextureSampleCount` | 3 | app | `VkProperty`、`VkFeature::MultisampleArrayImage` |
| `RasterSampleCount` | 2 | app | `framebuffer*SampleCounts` |
| `SamplerAnisotropy` | 1 | app | `VkFeature::SamplerAnisotropy` |
| `SamplerLodBias` | 3 | app | `VkLimit::MaxSamplerLodBias` |
| `SamplerCompare` | 1 | app | 站点点名的 Vulkan feature |
| `StageStoresAndAtomics` | 1 | app | `VkFeature::FragmentStoresAndAtomics` |
| `ArgumentBufferPointers` | 1 | app | buffer device address |
| `DereferenceLoadedPointer` | 4 | app | 站点点名的 feature、buffer device address |
| `LocalSize` | 1 | app | `every device (no Vulkan mechanism)` |
| `TriangleFillLines` | 1 | app | `fillModeNonSolid` |
| `DepthClipClamp` | 1 | app | `depthClamp` |
| `DepthBiasClamp` | 1 | app | `depthBiasClamp` |
| `ConstantAlphaBlendFactor` | 1 | app | `VkFeature::ConstantAlphaColorBlendFactors`（portability subset） |
| `ViewFormatReinterpretation` | 1 | app | `every device (no Vulkan mechanism)`（portability subset） |
| `HeapTextureTiling` | 1 | app | `every device (no Vulkan mechanism)` |

#### 2.4.3 组 C：本项目明确不做（Reach `rare`，且在 `60` 的「永不做」清单内）

`Tessellation` 13、`RayTracing` 12、`IntersectionFunctionTable` 9、`Imageblocks` 10、`MeshShading` 7、`TileShading` 5、`GpuEncodedIndirectCommands` 17、`DynamicCall` 9、`Linking` 3、`SimdgroupMatrix` 1、`ArgumentBufferObjects` 5、`Tensors` 2、`Reflection` 10、`RasterizationRateMap` 1、`VertexAmplification` 5、`LayeredRendering` 7、`Barycentrics` 5、`StencilExport` 6、`SampleRateShading` 3、`KernelStageIn` 3、`ImplicitLodOutsideFragment` 3、`MinLodClamp` 2、`ImageAtomics` 3、`Int64Atomics` 2、`CoherentMemory` 1、`GatherExtended` 1、`StorageImageMultisample` 1、`StorageTextureInVertexStage` 1、`CubeArray` 2、`DualSourceBlending` 5、`ClipDistance` 2、`IndependentBlending` 2、`PrimitiveId` 3、`PixelCoverage` 2、`PixelCoverageAtSampleRate` 3、`PostDepthCoverage` 2、`CentroidVarying` 1、`SeparateMultisampledDepthStencil` 6、`SamplePositions` 1、`AlphaToOne` 1、`SeqCstFence` 1、`GpuTimes` 1、`CountingVisibility` 1、`ViewportDepthRange` 1、`RenderTargetSize` 1、`IndirectRenderState` 1、`GlobalBuiltinInFragment` 1、`SparseTexture` 2、`SparseTextures` 2、`DirectCall` 1、`WideSwitchLiteral` 1、`PrivateMemory` 1、`FunctionConstantArgument` 2、`Recursion` 4、`UnknownIntrinsic` 2、`AgxUnmodeled` 1、`ThreadgroupMemorySize` 3、`GroupCount` 7、`ComputeDerivatives` 4、`ComputeDerivativesWithSimd` 1、`IrreducibleConvergent` 1、`HandleAsPointer` 6、`ConstantGlobalEscaping` 2、`PointerToInteger` 1、`PointerCompare` 2、`Int64Arithmetic` 2、`Float64Arithmetic` 2、`InterfaceComponents` 4、`PrivatePrimitives` 1。

`INFERRED`：这一组第一版全部「向上报错」。它们进 capability manifest 的 false 清单，并带上 `needs`。**注意三条例外**，它们 Reach 是 `rare` 但本项目仍然要管：

1. `UnknownIntrinsic`（2 处，`every device (not implemented)`）的 reach 注记是「来自更新编译器的 AIR（macOS 27 AIR 2.9）」。本项目基线是 macOS 26，但 guest 内的 Metal 编译器版本由 `32-COMPILER-PLUGIN.md` 控制，必须确认不会产出 2.9 的记录。
2. `AgxUnmodeled`（1 处）的 reach 是「Apple 自己库里的 AGX intrinsic」。**系统 metallib 正是 Apple 自己的库**，所以这条在 x86 guest 上是否真的 `rare`，要等 S3 的直方图。
3. `PrivateRenderState`（7 处，Reach `none`）涉及 Apple SPI 的私有固定功能属性。`22-OBJC-DESCRIPTORS.md` 的反序列化路径会碰到它们，不能当 `none` 忽略。

### 2.5 runtime gap（70 条）按处置分组

`KNOWN`（来源：`REFUSALS.md` 第 2 节。全部 70 条 Basis 均为 `ours`，Where 几乎全是 `every device (runtime piece not built)`，所以**换设备或换 ICD 对这一组毫无帮助**）

| 组 | 变体（构造点数） | Reach | 本项目处置 |
|---|---|---|---|
| **系统路径** | `Render`(26) | system | §2.3 #7。向上游补或自建 |
| **普通 app 会撞** | `HeapTextureMemory`(3)、`HiddenDepthStencil`(2)、`Metal4Api`(3)、`CounterSampleBuffers`(1)、`ResidencySets`(2)、`DecodedHeapTexture`(4)、`LibrarySource`(1)、`ColorAttachmentGroups`(1) | app | `Metal4Api` / `CounterSampleBuffers` / `ResidencySets` 报 false；`HiddenDepthStencil` 与 `ColorAttachmentGroups` 要补（见下）；**`LibrarySource` 必须专门处理** |
| **IOSurface 与 no-copy** | `OverlappingSurfaceRows`(4)、`MemorylessSurfacePlane`(1)、`SurfaceDepthStencil`(2)、`RebindTextures`(10)、`DetachTextures`(7)、`TexelsPastBufferLength`(2)、`DetachedTexelAccess`(1)、`MappedTextureSampling`(1)、`WriteSwizzle`(1) | rare / none | **这一组是 `41-IOSURFACE-USERSPACE.md` 的直接输入**（§4.4） |
| **间接命令** | `IndirectRenderCommands`(16)、`CommandReplay`(3)、`IndirectDrawArguments`(5)、`IndirectCommandBufferPastMaxBufferLength`(1)、`IndirectCommandPastSize`(1)、`IndirectImageblockSize`(1)、`ExecutionRangePastBuffer`(1)、`ExecutionRangeOffFour`(1)、`IndirectCommandUnstridedBuffer`(1)、`FunctionTablePastMaxBufferLength`(1) | rare / none | 第一版不做（`60` §5.3：无证据表明 WindowServer 用 indirect） |
| **sparse** | `SparseHeaps`(2)、`SparseTileMaps`(4)、`TextureAccessCounters`(2) | rare | 不可行（§3.2） |
| **depth / stencil 与 resolve** | `DepthStencilResolve`(7)、`DepthNeverWithoutAttachment`(1)、`NonFiniteDepthBias`(5)、`ViewportDepthRange`(7) | rare | 单采样首帧不受影响；MSAA 路径记为已知损失 |
| **imageblock 与 tile** | `TileAtSampleCount`(2)、`ImageblockMasters`(2)、`TileAndFragmentImageblocks`(3) | rare / none | 不做（Mac2 不列） |
| **纹理形式** | `Textures`(9)、`ResourceHeap`(1)、`HeapPastMaxBufferSize`(1)、`HeapTextureAlignment`(1)、`RotatedTexture`(8)、`TextureBufferLevels`(1)、`PvrtcBlockOrder`(1) | rare / app / none | **`Textures` 这条在 family 审计里是致命的**（§5.2） |
| **blit** | `MultisampledBufferCopy`(2)、`MultisampledBufferLayout`(1)、`OverlappingTextureCopies`(1)、`EmptyFillPattern`(1) | rare / none | 单采样首帧不受影响 |
| **draw 形式** | `RestartedStrip`(1)、`PrivatePrimitives`(2)、`ProvokingVertex`(1)、`PrimitiveIdIndices`(1)、`VertexFetchPast4GiB`(1)、`StageInFetchPast4GiB`(1)、`LayeredPass`(1)、`RateMapRegions`(1)、`SamplePositionsAtBegin`(3) | rare / none | 向上报错 |
| **同步与设备** | `SharedEventAcrossDevices`(1)、`FeatureEnable`(1)、`ExtensionEnable`(1) | rare / none | `FeatureEnable`/`ExtensionEnable` 必须在启动自检里当致命错误（`40` §6.5 同理） |
| **明确未排期** | `IoCommandQueues`(2)、`TextureViewPools`(2)、`ColorAttachmentMapping`(1)、`LossyTextureCompression`(1)、`ShaderValidation`(1)、`ShaderLogging`(1)、`DeviceNotifications`(1)、`AccelerationStructures`(1) | rare | 报 false |

**三条必须单独说：**

1. **`RuntimeGap::LibrarySource`**（1 处，Reach `app`）：从 MSL 源码编译 library。上游的输入是 metallib 与 AIR。这与覆盖表的 19 项 out of scope（MSL 源码编译）是同一件事。`60` 的矩阵里没有这一行。**对本项目的后果**：guest 里任何在运行期调 `newLibraryWithSource:` 的 app 都会失败。这需要 `32-COMPILER-PLUGIN.md` 的路径接住（把源码交给 guest 内的 Metal 编译器产出 metallib，再喂给 runtime），否则就是一整类 app 不可用。`INFERRED`：WindowServer 与 CoreAnimation 用预编译的系统 metallib，不走这条；但 Xcode 样例与一部分游戏会走。

2. **`RuntimeGap::HiddenDepthStencil`**（2 处，Reach `app`）：draw 的 depth/stencil state 用了 pass 没有的 depth 或 stencil。上游注明**纯 Metal 会按一个隐藏的 `float` 深度 1.0 测试**。这是「Metal 接受、上游拒绝」的一条，`app` 可达。`INFERRED`：本项目在 descriptor 期把这种组合归一化（pass 无 depth attachment 时把 depth test 置为 always），比向上报错安全。

3. **`RuntimeGap::ColorAttachmentGroups`**（1 处，Reach `app`）：设备一次画不了那么多 color attachment 时，pass 分组绘制，而分组路径有未建的形式（另一组的 attachment 被读、tile state、render command 的执行等）。`BLOCKED`：Lavapipe 的 `maxColorAttachments` 要等构建后实测；`00-OVERVIEW.md` §4.4 已记明 `initLimits` 对 `maxColorAttachments` 有 release 断言，必须非零。

### 2.6 其余五类

| 类 | 规模 | 关键事实 | 本项目处置 |
|---|---|---|---|
| Apple-only（`Error::AppleOnly`） | 5 条，Basis 全 `-`，Reach 全 `none` | Apple 私有调用中无 Vulkan 形式或语义未测的部分 | `40` §2.8 已要求接入 `AppleOnly`/`AppleOnlyCall`/`AppleOnlyGap`。本项目**必须自己答**这 5 条，因为它们正是 `20`/`21` 分册的私有属性面 |
| binder 限额（`BindError`） | 9 条，Basis 全 `device`，Reach app 1 / rare 7 / none 1 | 全部是设备限额 | `BLOCKED` 等 Lavapipe 实测限额 |
| 翻译上限（`Error::LimitExceeded(Limit)`） | 14 条，Basis 全 `ours`，Reach rare 7 / none 7 | 上游自己的翻译上限 | 向上报错。**但 macOS 26 最大的 CoreAnimation fragment 是 210,033 words（§6.1），必须确认它不触上限** |
| rate map 不编译（`Error::RateMap(UnpinnedCompile)`） | 5 条，Basis 全 `-` | `60` §3.18 已记 | 报 false |
| 翻译期限（`Error::Budget`） | 1 条，Basis `ours`，Reach `none` | 翻译自身的时间预算 | **必须显式设定并与 §6.2 的管线等待预算、display provider 的超时对齐** |

### 2.7 「最严重缺口」的完整排序

排序规则（`INFERRED`，本册定义）：权重 = Reach 等级 × 是否命中 `60` §5.2 的 19 项 × Where 是否与设备无关。命中 19 项且 Where 含 `every device` 的排最前。

| 名次 | 缺口 | 构造点 | Reach | 命中 19 项的第几条 | Where 与设备无关？ | 为什么排这个位置 |
|---|---|---|---|---|---|---|
| 1 | `Feature::ExtendedRangeBlend` | 5 | system | **第 6、7 项** | **是**（`every device (not implemented)`） | 上游自己记明「消费者的 guest 在混合 `RGB10A8_2P_XR10` attachment」，而这正是登录屏的 attachment。换任何设备都不会变。见 §4.2 |
| 2 | `RuntimeGap::Render` | 26 | system | **第 3 项** | **是**（`runtime piece not built`） | render pass / resolve / attachment 的若干形式未建，且是 `system`。合成 pass 的形状由 WindowServer 决定，我们不能选 |
| 3 | `Feature::Format` | 120 | system | **第 7、8、19 项** | 部分 | 面最大的一条。但可按格式分治，且 `40` §8 已有候选表 + `pixel_format_capabilities` 的实测出路 |
| 4 | `Feature::FramebufferFetch` | 24 | system | **第 6 项** | 部分 | 登录流程命中，但 Lavapipe 恰好有**精确**形式（§3.3）。真实代价是 scratch image，不是不可行 |
| 5 | `Feature::HostMemory` | 7 | system | **第 11 项** | 部分 | Lavapipe 导入指针（§3.3），所以第一候选可行；但 `41` 的三条退路要全部实现 |
| 6 | `Feature::Lowering` | 35 | system | 不定（任何 shader） | 部分 | 面最大但不可预测。**它的严重性取决于 S3 的直方图，在此之前无法排得更准** |
| 7 | `Feature::SamplerBicubicFilter` | 5 | system | 不在 19 项内，但在**启动路径**上 | **是** | 上游记明 macOS 26.6.2 在消费者的启动路径上建过 cubic filter 的 runtime sampler。`60` §5.2 应新增一项（§4.3） |
| 8 | Metal 4 零覆盖 | 387 项 missing | `app`（`RuntimeGap::Metal4Api` 的 reach） | 不在 19 项内 | 是 | **排在第 8 而不是第 1**：项数最大，但 Reach 只是 `app`，且本项目已决定不做，Intel Mac 上本来不可用（`60` §1.3）。`91` 已测得 APV 对 `Metal4` 答 false |
| 9 | `Feature::TextureSwizzle` | 7 | app | 不在 19 项内 | 是 | 唯一理由：它是 `supportsFamily:Mac2` 与 `Metal3` 的一条无条件阻断行（§5.2）。要声明家族就必须补 |
| 10 | `RuntimeGap::LibrarySource` | 1 | app | 不在 19 项内 | 是 | 一整类 app（运行期编译 MSL）不可用，但不影响首帧 |

**对 `60` 的更正**：`60` 把「Metal 4 零覆盖 + `Feature::Format`（120 处）」并列为三大缺口之一。按一手数据，Metal 4 与 `Format` 的严重性相差很远：`Format` 是 `system` 且命中 19 项中的三条，Metal 4 是 `app` 且本项目已划出范围。两者不应并列。`KNOWN` + `INFERRED`

---

## 3. Lavapipe 相关的拒绝、限制与驱动缺陷

`60` §2 的 Lavapipe 事实全部来自 Mesa 源码（`lvp_device.c` 的 feature 表与扩展表）。本节换一个角度：**上游自己对 lavapipe 测过什么、点名了什么**。这是一手数据，比读 Mesa 源码声明强一级，因为上游的每条都带测量版本号与测量用的 lane 名。

### 3.1 上游点名 lavapipe 的 `RuntimeDriverDefect` 全表

`KNOWN`（来源：`upstream/m2v/crates/metal2vulkan-runtime/src/driver_defects.rs` 的模块文档与 `DEFECTS` 表；每条的 `driver` 为 `DriverId::MESA_LLVMPIPE`）

驱动缺陷的键是 `VkPhysicalDeviceDriverProperties::driverID` 加 `VkPhysicalDeviceProperties::deviceID`，**不是驱动版本号**。上游的规则（转述）：没被探测过的 GPU 一律按「有缺陷」处理；被探测干净的 GPU 只需把它的 `deviceID` 加进 clean 列表。缺陷破坏的东西能走精确替代路径就走，否则类型化拒绝（`Needs::RuntimeDriverDefect`），只有在「拒绝会撤回设备已声明家族的某一行」时才带降级通告跑。

`MESA_LLVMPIPE` 的缺陷共 **5 条**：

| # | `RuntimeDriverDefect` | 上游记的机制（转述） | 测量情况 | 上游的处置 | 对本项目的后果 |
|---|---|---|---|---|---|
| 1 | `MultisampledDepthStencilColourCopies` | `lvp_execute.c` 的 `handle_copy_image` 在 depth/stencil 与不同 texel 尺寸的 colour 格式之间经 `texture_map` 拷贝，而它只映射 sample 0，其余 sample 从不被写 | 读过 Mesa 26.0.8 源码与 main 的 2026-10-05，并在 26.0.8 上实测（`runtime_lane::separate_samples`）；记为「26.2.x 之前已知损坏」 | 不拒绝，走替代路径 | 只影响 MSAA 的 depth/stencil ↔ colour 拷贝。**单采样首帧不受影响** |
| 2 | `DepthStencilResolveFirstSubresource` | `resolve_ds` 的 blit 把 `box.z` 与 `level` 留在 0（`resolve_color` 会从 view 的 `base_array_layer`/`base_mip_level` 取），所以从多采样数组的 slice 1 resolve 会取 slice 0 的样本，往 slice/level 1 resolve 会写 slice/level 0 | 读过 25.2.0 / 26.0.8 / 26.2.4 / main(2026-10-07) 源码，并在 26.0.8 与 26.2.4 上实测（`runtime_lane::layered_passes`）；26.2.4 之前已知损坏 | 除「另一层的 memoryless attachment」外不拒绝 | **分层 + MSAA resolve 的组合在 Lavapipe 上会静默取错层**。本项目若用分层合成必须规避 |
| 3 | `ExplicitPlaneRowsPastHeight` | 为 host allocation 建的 `DRM_FORMAT_MOD_LINEAR` image，带显式 plane 落在纹理的紧凑行上，subresource 与内存需求都报 `rows × rowPitch` 字节，但**它按 4 行一块渲染**：一个 load/blend/store 的 pass 在 658×126 的 `RGBA16Float` tile（行 5264 字节）上重写了越界的第 126、127 行；在 1308×510 的 `BGRA8Unorm` tile（行 5232 字节）上写到了 no-copy buffer 映射之外的第 510、511 行，**进程吃了 `SIGSEGV`** | 在 26.2.4 实测（llvmpipe、LLVM 23.1.1、256 位、gem10）；26.2.4 之前已知损坏，26.0.8 未探测 | 不拒绝：那里不建高度非 4 倍数的此类 image，纹理走 shadow | **这是对 `41-IOSURFACE-USERSPACE.md` 最直接的一条**。两个被测格式正是 `60` §5.2 第 8 项的 `RGBA16Float` 与 `BGRA8Unorm`。1920×1080 的 1080 是 4 的倍数，首帧安全；**任何高度非 4 倍数的 IOSurface plane 一律 shadow**，并且上游会替我们挡住，不会崩 |
| 4 | `ImmutableSamplersLostAfterCopies` | 同一个 `VkCommandBuffer` 里，记在一次 copy 之后的 compute dispatch，采样一个 pipeline layout 烘焙了 immutable sampler 的 combined image sampler binding 时，把该 sampler 当成 Repeat。上游测的正是一个 4:2:0 纹理的 kernel 变体（layout 烘焙 clamp-to-edge） | 26.0.8 实测损坏（LLVM 21.1.8）；26.2.4 实测干净（LLVM 23.1.1）。Mesa 26.1.0 的 release notes 列了「lavapipe: rework immutable samplers」，很可能是修复，但上游未读其改动。**上游注明每个 lavapipe release 都按有缺陷处理**：26.2.4 虽测干净但没有 committed profile 可作为 measured identity | 不拒绝：烘焙了 sampler 的变体的 dispatch 记在自己的 `VkCommandBuffer` 里 | **命中 `60` §5.2 第 5 项**：CoreAnimation 的 blur 用 kernel，若该 kernel 带 constexpr sampler，每次 dispatch 会被单独记进一个 `VkCommandBuffer`。这是额外的 command buffer 开销，算在性能预算里。graphics draw 未被测量 |
| 5 | `TenBitCodesReadAsWords` | sampler 的 Y′CbCr 转换把 `G10X6_B10X6R10X6_2PLANE_420_UNORM_3PACK16` 及其 4:4:4 形式的每个 code 的 16 位字当成 16 位归一化值读（`word / 65535`，含低 6 位未用位），而 Vulkan 规定按 10 位 code 算 `c / (2^10 - 1)` | 26.0.8 实测（LLVM 21.1.8）；26.0.8 之前已知损坏。RADV 与 NVIDIA 也有同一条 | 不拒绝：10 位两 plane 纹理在那里走 Metal 的算术转换 | **命中 `60` §5.2 第 19 项**。但注意 `'b3a8'` 不是 YCbCr（§4.1 第 19 行），所以登录路径不走这条；真正的 YCbCr 视频路径会走 |

> **R43-1**：按 `40-RUNTIME-VULKAN.md` §7.4，`DeviceProperties::driver_defects` 的内容必须进 capability manifest。**上面 5 条是本项目必须预期看到的集合**；启动自检时实测到的集合与这 5 条不一致，要当成「Mesa 版本或构建配置与上游测量的不是同一个」处理，并记进 `90-EVIDENCE-INDEX.md`，不要静默继续。`INFERRED`（规则来自 `40` §7.4，集合来自 §3.1）

### 3.2 逐条核实 `60` §2 的 Lavapipe 结论

| `60` 的结论 | 一手核实 | 判定 |
|---|---|---|
| §2.3「sparse 全族在非 Linux 上关闭」 | Mesa 侧的 `DETECT_OS_LINUX` 不在上游副本内，无法用一手数据核实（Mesa 不在 `upstream/m2v`）。但上游侧有补充事实：family 审计的 `SparseTextures` / `SparseDepthStencilTextures` 行的判定链是「格式的 Sparse 能力 → `gap(RuntimeGap::SparseHeaps)` → `gap(RuntimeGap::TextureAccessCounters)`」，**即使设备有 sparse，上游这两个 gap 也会阻断该行** | `60` 的方向对，但**理由不全**：sparse 在本栈上不可行有两个独立原因，Lavapipe 一个，上游两个 gap 一个。`KNOWN`（上游侧）+ `BLOCKED`（Mesa 侧，等构建） |
| §2.3「`Refusal::PointSizeRange` 点名 lavapipe 为 256」 | **核实通过**。`families/mod.rs` 的 `Refusal::PointSizeRange` 文档：Metal 最大的点是 511 像素，设备按 `pointSizeRange` 夹紧，上界在它之下（ANV 255.875，**lavapipe 256**），所以更大的点在那里画得比 Metal 小 | `KNOWN` |
| §2.3 + §4.1「`PointSizeRange` 会阻断 family 声明」 | **核实通过但权重要降**。`families/limits.rs` 的 `LimitRow::PointSize`（打印名 "Maximum size of a point primitive"）的 cells 是 `apple: [(2, AtLeast(511))]`、`mac2: Some(AtLeast(511))`，判定为 `Need::AtLeast(n)` 且 `l.max_point_size < n` 时 `RowState::Refused(Refusal::PointSizeRange)`。所以它确实阻断 Mac2 与 Metal3（Metal3 取 Apple7 的 limits）。**但 Common1/2/3 不受影响**：2023 版表没有 Common 的 limits 列，Common 家族只判 feature 行。而且在它之前已有两条无条件 gap 阻断同一批家族（§5.2） | `KNOWN`，`60` §4.1 把它排在「真正的能力上限」第 2 位过高 |
| §2.3「subgroup 宽 4/8 vs Metal 的 32」 | Mesa 侧数值无法一手核实。上游侧的对应物核实通过：`Feature::SimdWidth`（2 处，Reach `app`，Basis `device`，Where 为 `VkProperty::MetalFragmentSimdgroups` 与站点自算的 `width_needs(stage, st)`）、`Feature::QuadOperations`（2 处，Where 为 `VkLimit::MinSubgroupSize` 与 `VkProperty::SubgroupQuadOperationsInAllStages`）、`Feature::SubgroupOperations`（4 处） | `60` 方向对。`BLOCKED`（实际宽度等 `build-lavapipe-macos` workflow 的产物） |
| §2.3「单一 `VkQueue`」 | **核实通过**。`degradation.rs` 的 `Degradation::SharedPresentQueue`（稳定串 `shared-present-queue`，category `Performance`）文档点名「MoltenVK 的四个单队列族，**RADV 与 lavapipe 的单一 graphics 队列**」；`queue.rs` 的模块文档与 `Device::new_command_queue_for_presenting` 文档同样点名。通告文本记明：present 在它的锁下阻塞时会压住其他 command queue 的提交，而 Metal 的 present 不压任何队列 | `KNOWN` |
| §2.3「tessellation 上游 13 处构造点全拒绝」 | **错**。`REFUSALS.md` 的 `Tessellation` 行：13 处构造点，Where 为 `devices without VkLimit::MaxPushConstantsSize`、`MaxStorageBufferRange`、`MaxTessellationGenerationLevel`、`every device (not implemented)`，**Reach 是 `rare`**。`families/features.rs` 的 `F::Tessellation` 处有一段明确说明（转述）：runtime 的 patch draw（直接与间接）**已建**（`tessellation.rs`），设备启用 `tessellationShader` 时走设备的 tessellation 阶段，**没有时走模拟**（`render/tessellation_scan.rs`）；编译层仍拒绝两种窄形式：patch 未声明 control-point 数（`[[patch(kind)]]`）的 post-tessellation vertex function，以及在设备阶段下 fragment function 读 `[[primitive_id]]` | **需更正**，见 §7 R-05 |
| §2.3 的其余条目（整数格式无 MSAA、depth/stencil resolve 只有 SAMPLE_ZERO、ASTC HDR 关闭、16 位 varying 关闭、mesh multiview 关闭与 `maxMeshOutputLayers = 9`、`inheritedQueries = false`、sample location 网格 1×1 与上界 0.9375、无原生 barycentric、`gpuCoreCount` 无来源、CPU 执行速度） | `gpuCoreCount` 核实通过（`capabilities.rs` 与 `private_properties.rs` 都把 lavapipe 列入「不列任何厂商 core-count 扩展」）；depth/stencil resolve 核实通过（`resolve.rs` 的模块文档：**`Min` 或 `Max` 在没有该模式的设备上，lavapipe 两者都没有**）；其余为 Mesa 源码声明 | 部分 `KNOWN`，部分 `BLOCKED` |

### 3.3 `60` 漏掉的 Lavapipe 事实（上游一手）

`KNOWN`。这一节是本册给 `60` §2 的增补。

| # | 事实 | 上游出处 | 对本项目的意义 |
|---|---|---|---|
| 1 | **framebuffer fetch 在 lavapipe 上走 input attachment 形式，是精确形式。** 上游有两种精确形式：带 rasterization-order attachment access 的 input attachment（**「both lavapipes of the venues」有 `rasterizationOrderColorAttachmentAccess`**），以及只有 `fragmentShaderPixelInterlock` 时的 storage attachment 形式（RADV、ANV、NVIDIA、MoltenVK）。两者都没有时**拒绝管线** | `crates/metal2vulkan-runtime/src/framebuffer_fetch.rs` 模块文档 | `60` §2.2 写的是「interlock + rasterization order attachment access」，把两条并列了。实际 lavapipe 走的是**前者**，而且是上游测量过的 venue。**这是 `60` §5.2 第 6 项可行性的最强证据** |
| 2 | **input attachment 形式的代价**：pass 无法预知哪个 draw 会 fetch，所以在这类设备上**每张 color render target 同时也是 input attachment**（`image_plan.rs`）；**调用方自己建的 image 若没有该 usage 就不是**（`texture/wrapped.rs`），于是 fetch 它的 pass 会把它渲进一张**有该 usage 的 scratch image**（`attachment_stand_in.rs`），并在 Metal 会 `Load` 时把 level/layer 拷进 scratch、在 Metal 会 `Store` 时拷回；`DontCare` 的 store 不拷回 | `framebuffer_fetch.rs`、`attachment_stand_in.rs` 模块文档 | **直接决定首帧成本**。见 §4.4 的 R43-2 |
| 3 | **XR attachment 的混合在 lavapipe 上在 input attachment 上做。** 上游的精度账本写明：混进 extended-range attachment（`BGR10_XR`、`BGRA10_XR`、`RGB10A8_2P_XR10` 及其 sRGB 双生）的颜色在 shader 里混合，**在 pixel interlock 内（在 lavapipe 上则在它的 input attachment 上）**，用设备的算术 | `docs/FAST-PATHS.md`「Not speed choices: device gaps」表 | 登录屏的混合在 Lavapipe 上有明确路径。精度记为 `ExtendedRangeBlendSource`（`extended-range-blend-source`）与 `ExtendedRangeFloatBlendSource` |
| 4 | **lavapipe 的 timeline semaphore 是模拟的。** 上游记明：已 signal 的 fence 所在 batch 一定到达了它的值，但驱动可能比 fence 更晚显示该值；**lavapipe 的模拟 timeline 要等提交该 batch 的线程装好它的 point 才显示，而那在 batch 跑完之后，负载高的宿主可以把它压到 fence 之后** | `crates/metal2vulkan-runtime/src/command_buffer/completion.rs` 的 `poll` 文档 | `60` §2.1 只写「`timelineSemaphore = true`，满足」。语义更弱：**跨进程 `MTLSharedEvent` 的值可见性与 present fence 的时序不能假定 timeline 与 fence 同步**。`50-IPC-HELPER.md` 的事件语义要按这条写 |
| 5 | **lavapipe 的 `sampleLocationSampleCounts` 只有 `{4}`。** 上游明确不用这个属性去卡 `setSamplePositions:count:` 的 count：那样做会在 lavapipe 上拒掉「4 采样 pass 里给 2 个位置」这种 Metal 会跑的 pass，并把它说成调用方的错误 | `crates/metal2vulkan-runtime/src/sample_positions.rs`（含同名测试 `fewer_positions_than_samples_are_taken_at_the_passs_count`） | 比 `60` §2.3 的「网格 1×1」更精确的一条。本项目**不要**自己再加一层 count 校验 |
| 6 | **lavapipe 实测的最大 linear-image 对齐是 64 字节**（RADV 256、NVIDIA 128、MoltenVK 16）。runtime 对所有设备统一用 `LINEAR_IMAGE_ALIGNMENT = 256`；导入的 host 内存从 host page 起，不需要额外对齐 | `crates/metal2vulkan-runtime/src/buffer.rs` 的 `LINEAR_IMAGE_ALIGNMENT` | `41` §3.1 的三个对齐约束里，「Vulkan 侧要求」这一项在 Lavapipe 上是 64；但 runtime 会按 256 放置，所以本项目不要按 64 规划 |
| 7 | **lavapipe 导入 host 指针，且导入「跟随地址」。** 上游记明 NVIDIA 与 lavapipe 导入了同样的 shared memory（RADV 拒绝任何文件 / `memfd` / 共享内存映射，含 QEMU 的 `memory-backend-memfd,share=on` guest RAM）。另外 `DriverFact::PointerImportsFollowTheirAddress` 包含 lavapipe：**那里的活导入在每次提交时读该指针当时映射的页**。`HostMemory::new` 的合同禁止在活 buffer 下 remap | `crates/metal2vulkan-runtime/src/host_memory.rs`、`host_residency.rs`、`buffer_descriptor.rs` | **`60` §5.2 第 11 项的可行性由这条支撑。** 同时它给 `41` R41-3（base address 必须每次 lock 后重读、变了要走 `rebind_bytes_no_copy`）提供了第二个理由：在 lavapipe 上 remap 会被导入看见 |
| 8 | **lavapipe 读了只读页。** 上游的导入门控规则在 lavapipe 上「拒得比驱动本身更多一点」（Linux 驱动为写入 pin 用户页；NVIDIA 把只读页报成设备内存不足，RADV 拒绝，ANV 导入后在 GPU 首读时丢设备，而 lavapipe 读了它）。macOS 上 MoltenVK 把范围交给 Metal，没有这个检查 | `host_memory.rs` 模块文档 | `41` §2.3 决策树里 `import-gate-refused` 这一支在 Lavapipe 上会比必要更保守。可用 `HostMemory::assume_writable` 规避，但要有 `41` 的权限依据 |
| 9 | **lavapipe 的 `R8_SRGB` 不能采样**，上游把它作为 UNORM 双生持有，shader 读原始 code 再按 Metal 解码（ANV 与 NVIDIA 是 `R8G8_SRGB`） | `crates/metal2vulkan-runtime/src/image_plan.rs`「sRGB twins」 | `40` §8 的格式表要给 `R8Unorm_sRGB` 加这条 Lavapipe 注记 |
| 10 | **lavapipe 的 BC7 解码与 Metal 差一个 `float` ulp**，BC6H 另有 `Bc6hBlockDecodeIsMetals` 的判定 | `crates/metal2vulkan-runtime/src/texture.rs`、`degradation.rs` | `60` §3.6「压缩格式 BC1–BC7 适配 + 精度降级记录」的精度数有了出处 |
| 11 | **lavapipe 的 shadow stencil 只写 sample 0** | `crates/metal2vulkan-runtime/src/shadow_stencil.rs` | MSAA + shader 写 stencil 的组合在 Lavapipe 上是已知损失 |
| 12 | **CPU ICD 的进程退出要等。** 队列在本进程里跑的设备（`DeviceKind::Cpu`：lavapipe、SwiftShader）把提交给它的工作跑在本进程线程上。上游实测：带在途工作退出时，lavapipe 的队列线程在析构函数运行期间还在编译某个 dispatch 的 shader（LLVM 的 `MCJIT::finalizeObject`），进程死在 `free()` 的堆检查里（300 次退出中 host step 等待时 5 次、普通 dispatch 在途时 1 次）；在校验层 1.4.357 下带活设备退出会在 `vkWaitSemaphores` 内 `SIGABRT`。另一处记明带工作的 lavapipe 进程退出耗时 2 s | `crates/metal2vulkan-runtime/src/exit_guard.rs` | **对 `50-IPC-HELPER.md` 的崩溃恢复与 helper 退出路径是硬约束**：helper 退出必须等本进程队列的在途工作，不能直接 `exit()`；`73-DEPLOY-RESCUE.md` 的超时预算要含这 2 s |
| 13 | **在 lavapipe 上，image 绑定进已被在途命令缓冲采样过的内存块时，等的是队列锁（在建 image 的 view 时），不是 ioctl**（NVIDIA 在 `vkBindImageMemory` 里等到那批工作结束，上游探针测得 490 ms） | `crates/metal2vulkan-runtime/src/memory.rs` 的 `binds_wait` 文档 | heap placement 的时序在 Lavapipe 上与独显不同，`60` §3.9 的 heap 行要加这条注记 |
| 14 | **lavapipe 的 `NaN` 与 clear 值行为**：小浮点通道的 NaN 由设备自行转换，RADV 与 lavapipe 写出别的值；lavapipe 的 average 保留 `half` NaN | `crates/metal2vulkan-runtime/src/clear_value.rs`、`degradation.rs` | **命中 `60` §5.1 的 `half_slice_nans` 证据**：CoreAnimation 的 blur 把 kernel 的 `half4` NaN 写进 16 位 float 纹理。Lavapipe 的 NaN 处理与 Metal 不同，这是首帧路径上的一条精度差异，必须进降级清单 |
| 15 | **lavapipe 把 linear image 的行数向上取整**（上游在 `linear_plan.rs` 记明），这是 §3.1 第 3 条缺陷的同一现象在另一处的描述 | `crates/metal2vulkan-runtime/src/linear_plan.rs` | 同 §3.1 #3 |
| 16 | **lavapipe 的向量宽度随宿主**：arm64 上 128 位、带 AVX2 的 x86 上 256 位；`LP_NATIVE_VECTOR_WIDTH=256` 可强制较宽的那个。上游的 CI 用 `LP_NUM_THREADS=1` | `upstream/m2v/docs/VALIDATION.md` | **直接决定 `60` §2.3 的子组宽度**：子组宽 = 向量宽 / 32，x86_64 + AVX2 → 256/32 = 8。`70-BUILD-PACKAGE.md` 必须把 `LP_NATIVE_VECTOR_WIDTH` 固定并进 capability manifest |
| 17 | **lavapipe 在 128 位向量宽度下有会杀进程的故障** | `crates/metal2vulkan-validation/src/worker/device.rs` 模块文档首行 | 再一条「必须固定 `LP_NATIVE_VECTOR_WIDTH=256`」的理由。`INFERRED`：x86_64 上默认就是 256，但不能依赖默认 |
| 18 | **lavapipe 是上游 CI 的 CPU ICD**，并且上游在 lavapipe（arm64 与 x86 两个 venue）上跑公开用例的双 robustness leg 比对 Metal 行；`cutover/c3-venues.json` 列出 lavapipe 的两个 venue | `upstream/m2v/docs/VALIDATION.md`、`.github/workflows/ci.yml` | **本项目最重要的一条背景事实**：上游已经在 lavapipe 上跑过完整一致性比对。`80-TEST-HARNESS.md` 应直接复用 `scripts/qualify-public-cases` 与 `conformance replay --cpu` 两条路径，不要另写 |

### 3.4 Lavapipe 侧的 `BLOCKED` 清单

`BLOCKED`，全部等 `build-lavapipe-macos` workflow 的产物（`.github/workflows/build-lavapipe-macos.yml`）。在产物到手前，`60` 第三列与本册的任何 Lavapipe 数值都不得当作事实使用。

| 项 | 要测什么 | 阻塞谁 |
|---|---|---|
| L-01 | `apiVersion`、`VkPhysicalDeviceDriverProperties::driverID` 是否为 `MESA_LLVMPIPE`、`deviceID` | `40` §6.1 的版本下限、§3.1 的缺陷键 |
| L-02 | `lvp_get_features` 的实际 feature 全表（macOS x86_64 构建） | `60` §2.2、§2.3 的每一行 |
| L-03 | `VkPhysicalDeviceSubgroupProperties`：`minSubgroupSize`、`maxSubgroupSize`、`subgroupSupportedStages`、quad 支持 | `60` C-03、本册 §2.4.2 |
| L-04 | `pointSizeRange[1]` 的实测值 | §5.2 的 `PointSizeRange` 行 |
| L-05 | 全部 301 个 `MTLPixelFormat` 的 `Device::pixel_format_capabilities` | `40` §8 的 Lavapipe 列、`Feature::Format` 的 120 处 |
| L-06 | `VkPhysicalDeviceExternalMemoryHostPropertiesEXT::minImportedHostPointerAlignment` | `41` R41-8 |
| L-07 | `maxColorAttachments`、`maxFramebufferWidth/Height/Layers`、`maxComputeSharedMemorySize`、`maxBufferSize` | `00-OVERVIEW.md` §4.4 的 `initLimits` 断言、§2.5 的 `ColorAttachmentGroups` |
| L-08 | `rasterizationOrderColorAttachmentAccess` 在 macOS 构建下是否仍为 true | §3.3 #1，首帧可行性的单点 |
| L-09 | `driver_defects` 的实测集合是否就是 §3.1 的 5 条 | R43-1 |
| L-10 | sparse 六个 feature 在 macOS 构建下是否确为 false | §3.2 |

---

## 4. WindowServer 首帧最小集 × 上游覆盖 × Lavapipe

这是本册的结论性输出。`60` §5.2 列了 19 项必需特性。下表对每一项给出三方状态。

### 4.1 三方交叉全表

列的含义：

- **上游覆盖**：`METAL-COVERAGE.md` 的 header 计数或 out of scope 理由。
- **上游拒绝**：命中的 `REFUSALS.md` 条目，括号内为构造点数与 Reach。
- **Lavapipe**：一手数据（上游点名）优先；只有 Mesa 源码声明的标 `BLOCKED`。
- **判定**：`通`（三方齐备）/ `有代价`（可做但付额外成本）/ `挡`（被 refusal 或 Lavapipe 挡住或强制降级）/ `本体`（上游零覆盖，本项目自己做）。

| # | 19 项 | 上游覆盖 | 上游拒绝 | Lavapipe | 判定 |
|---|---|---|---|---|---|
| 1 | 设备枚举 + `registryID` + `supportsFamily:` + limits/feature 查询链 | `MTLDevice.h` 73/71/10。**缺口：group `queries` 54 项（S）**、`MTLArchitecture` | 无直接 refusal；但 `supportsFamily:` 在本 commit 上**全 20 个值答 false**（§5.2） | n/a（答案由设备推出） | **挡**（上游缺 54 项查询，枚举链会读；`supportsFamily` 全 false 改变 `60` §5 的前置条件） |
| 2 | 单队列 + command buffer + `commit` + `addCompletedHandler:` | `MTLCommandQueue.h` 4/10/0、`MTLCommandBuffer.h` 21/21/5。核心路径 implemented | 无。`RuntimeGap::Render`(26, system) 影响其中的 draw | **单一 graphics queue**（上游点名）→ `shared-present-queue` 降级；**timeline 是模拟的**，值可能比 fence 晚可见（§3.3 #4） | **有代价**（两项降级，不阻断） |
| 3 | render pass：color attachment、Load/Store/Clear/DontCare | `MTLRenderPass.h` 41/12/0、`MTLRenderCommandEncoder.h` 119/4/9 | **`RuntimeGap::Render`(26, system)**：render pass / resolve / attachment 的若干形式未建 | 有；但 `DepthStencilResolveFirstSubresource` 影响分层 resolve（§3.1 #2） | **挡**（窄形式未建，形状由 WindowServer 决定） |
| 4 | blend state（含 color write mask） | `MTLRenderPipeline.h` 114/30/1，blend 字段 implemented | `IndependentBlending`(2, rare, `device`：`VkFeature::IndependentBlend`) | `independentBlend` 为 Mesa 源码声明，未实测 | **`BLOCKED`**（等 L-02） |
| 5 | compute（pipeline、threadgroup、buffer/texture binding、barrier） | `MTLComputeCommandEncoder.h` 36/1/3、`MTLComputePipeline.h` 34/9/1、`MTLComputePass.h` 0/11/0 | `SimdWidth`(2, app)、`QuadOperations`(2, app)、`SubgroupOperations`(4, app)、`Feature::Lowering`(35, system) | 子组宽 = 向量宽/32 = **8**（x86_64 + AVX2，§3.3 #16）→ 32 宽走模拟；**`ImmutableSamplersLostAfterCopies`**：带 constexpr sampler 的 dispatch 要单独记一个 `VkCommandBuffer`（§3.1 #4）；**NaN 转换与 Metal 不同**（§3.3 #14，命中 `half_slice_nans` 证据） | **挡**（性能降级 + 一条缺陷 + 一条精度差异，全在 blur 路径上） |
| 6 | framebuffer fetch / 可编程混合 | 由 translator 的 color input 与 runtime 的 `framebuffer_fetch` 承担，implemented | **`Feature::FramebufferFetch`(24, system)**：macOS 26.6.2 登录流程命中 | **有 `rasterizationOrderColorAttachmentAccess`，走 input attachment 的精确形式**（上游点名两个 lavapipe venue，§3.3 #1） | **有代价**（精确形式可用；代价是每张 color 目标要 input attachment usage，否则另开 scratch + 两次拷贝，§4.4） |
| 7 | `RGB10A8_2P_XR10` 格式 | `40` §8.2.4 的候选落 `VK_FORMAT_R32G32_UINT`，implemented | **`Feature::Format`(120, system)** + **`Feature::ExtendedRangeBlend`(5, system, `every device (not implemented)`)**。后者的三个被拒形式：`Output`（输出不是四个 `half`/`float` lane，或第二输出不是混合读的那些）、`DualSource`（16 位 float attachment 的 storage 形式下的 second-source factor）、`OneColorChannel`（同上 + fast math + 恰好一个颜色通道的写掩码） | XR attachment 的混合**在 lavapipe 的 input attachment 上做**（§3.3 #3）。精度记 `ExtendedRangeBlendSource`、`ExtendedRangeBitsKept`、`DevicePackConversion` | **挡（最致命）**：§4.2 |
| 8 | `BGRA8Unorm` + `RGBA16Float` 纹理与 attachment | 核心格式，implemented | `Feature::Format`(120, system) 的一部分 | **`ExplicitPlaneRowsPastHeight` 实测用的正是这两个格式**：658×126 `RGBA16Float` 与 1308×510 `BGRA8Unorm` 都越界写，后者 `SIGSEGV`（§3.1 #3） | **挡**（高度非 4 倍数一律 shadow；1920×1080 的 1080 是 4 的倍数，首帧安全） |
| 9 | Apple 私有 texture usage 位（`BlockWritesOnly` `0x10000`） | 不在覆盖表内（SPI，表只收 SDK 公共条目，§1.1） | 无 | n/a | **本体**（`21-OBJC-OBJECT-FAMILY.md` + `22-OBJC-DESCRIPTORS.md`） |
| 10 | 真实 IOSurface：创建、plane/stride/alloc size、no-copy 导入、三态判定、完成后可见性 | **out of scope 3 项**（「IOSurface 归消费者」2 项 + 「runtime 把 plane 架在 no-copy buffer 上」1 项） | `RuntimeGap::OverlappingSurfaceRows`(4, rare)、`MemorylessSurfacePlane`(1, rare)、`SurfaceDepthStencil`(2, rare) | `ExplicitPlaneRowsPastHeight`（§3.1 #3）；指针导入跟随地址（§3.3 #7） | **挡 + 本体**（`41-IOSURFACE-USERSPACE.md`） |
| 11 | no-copy `Shared` buffer（经 `VK_EXT_external_memory_host`） | `MTLBuffer.h` 6/4/2，`newBufferWithBytesNoCopy:` implemented | **`Feature::HostMemory`(7, system)** | **lavapipe 导入指针，并与 NVIDIA 一样导入了同样的 shared memory**（§3.3 #7）；只读页处会拒得略多（§3.3 #8）；macOS 无 dma-buf，只剩三条退路（`41` §3.3） | **挡**（system refusal，但第一候选在 Lavapipe 上可行） |
| 12 | texture over buffer（IOSurface plane 上建纹理） | `MTLTexture.h` 57/12/4，implemented（含 in-place / shadow / copy 三态与设备自检） | `Feature::Format`、`RuntimeGap::Textures`(9, rare) | 最大 linear-image 对齐 64（runtime 统一用 256，§3.3 #6）；`ExplicitPlaneRowsPastHeight` | **挡**（`'b3a8'` 被算术强制为 shadow，`41` §3.5.3） |
| 13 | blit：buffer↔texture、texture↔texture、`synchronizeResource:` | `MTLBlitCommandEncoder.h` 22/6/0 | `MultisampledBufferCopy`(2, rare)、`MultisampledBufferLayout`(1, rare)、`OverlappingTextureCopies`(1, rare) | `MultisampledDepthStencilColourCopies`（§3.1 #1）只影响 MSAA | **通**（单采样首帧不受影响） |
| 14 | `MTLFence` + `MTLEvent` + CPU 等待 | `MTLEvent.h` 12/1/2、`MTLFence.h` 3/0/0 | `RuntimeGap::SharedEventAcrossDevices`(1, rare) | **模拟 timeline，值可能比 fence 晚可见**（§3.3 #4） | **有代价**（时序语义更弱） |
| 15 | 跨进程 `MTLSharedEvent` | 上游仅进程内；`MTLSharedEventListener.sharedListener` 在 group `events`（S，1 项）缺 | `SharedEventAcrossDevices`(1, rare) | 同 #14 | **本体**（`50-IPC-HELPER.md`） |
| 16 | display provider：mode 枚举、scanout 提交、swap completion、present fence | **out of scope 10 项**（presentation：无 `CAMetalLayer`、无 drawable） | 无 | 有 `VK_EXT_metal_surface`，但本项目不用它 | **本体**（`11-KERNEL-DISPLAY.md` + `12-KERNEL-IOSURFACE.md`） |
| 17 | 跨进程管线缓存（`PipelineRecord` + `Device::warm`） | runtime 扩展，implemented | 不是 refusal。是**超时风险**：`pipeline_creation_wait` 与 `pipeline_commit_wait` 各 4.5 s，一个 guest FIFO step 最多等 9 s，guest 的检查是 10 s | CPU + LLVM JIT，比独显慢（§6.1 的实测数） | **有代价（最致命的非 refusal 风险）**：§6.1 |
| 18 | depth / stencil（至少 `Depth32Float`） | `MTLDepthStencil.h` 15/2/0 | `RuntimeGap::DepthStencilResolve`(7, rare)、`HiddenDepthStencil`(2, app)、`SeparateMultisampledDepthStencil`(6, rare)、`DepthNeverWithoutAttachment`(1, rare) | 无 `Min`/`Max` depth resolve 模式（上游点名「lavapipe 两者都没有」）；`DepthStencilResolveFirstSubresource` | **通**（单采样首帧不走 resolve；`HiddenDepthStencil` 在 descriptor 期归一化，§2.5） |
| 19 | 两 plane 纹理 | `texture/surface_two_planes.rs`，implemented（同时承载 YCbCr 与 RGB 两个两 plane 族） | `Feature::Format`(120, system) | `TenBitCodesReadAsWords`（§3.1 #5）影响真正的 10 位两 plane **YCbCr**；`TwoPlaneChromaMisplaced` 在 lavapipe/RADV/NVIDIA 的 4:2:0 与 4:2:2 上色度错位 | **挡**（**并且 `60` 的归类是错的**：`'b3a8'` 是两 plane **RGB + A8**，不是 YCbCr，见 §7 R-08） |

### 4.2 被挡住的项与最致命的一项

`KNOWN` + `INFERRED`

**统计：19 项中 10 项判定为「挡」**（第 1、3、5、6、7、8、10、11、12、19 项；第 6 项虽有精确形式但强制额外 scratch 成本，计入），**1 项 `BLOCKED`**（第 4 项 blend 的 `independentBlend`），**3 项「有代价」**（第 2、14、17 项），**3 项「本体」**（第 9、15、16 项），**2 项「通」**（第 13、18 项）。

**最致命的是第 7 项 `RGB10A8_2P_XR10`。** 三条独立的成本叠在同一张登录屏 attachment 上：

1. **`Feature::ExtendedRangeBlend` 在每台设备上都拒绝它的三个形式之一**（Where 为 `every device (not implemented)`，Basis `ours`），而上游自己的 reach 注记写明「消费者的 guest 在混合 `RGB10A8_2P_XR10` attachment」。换设备、换 ICD、改 Mesa 都没用，只能补上游或在 descriptor 期拦住。
2. **`41-IOSURFACE-USERSPACE.md` §3.5.3 的算术已把它强制为 shadow**：上游候选 `R32G32_UINT` 是 8 字节/texel，而 surface 侧 plane 0 是 4 字节、plane 1 是 1 字节，合计 5，`8 ≠ 5`、`8 ≠ 4`、`8 ≠ 1`，任何单张 linear 的 `R32G32_UINT` image 的行距与 texel 跨距都对不上。1920×1080 时每帧 shadow 是 16.6 MB，拆分 pass 读 16.6 MB 写 10.4 MB。
3. **Lavapipe 的 framebuffer fetch 走 input attachment 形式**，所以这张 shadow image 必须带 input attachment usage，否则 fetch 它的 pass 会再开一张 scratch 并在 `Load`/`Store` 两侧各拷一次（§3.3 #2）。

三者相乘：登录屏每帧的固定成本是「一张 16.6 MB 的 shadow + 一个拆分 pass + 可能的第二张 scratch 与两次全屏拷贝」，而这一切之上还压着 `Feature::ExtendedRangeBlend` 的拒绝。**第一版能不能出图，这一项的权重最大。**

第二致命的是第 17 项，但它不是 refusal，是超时（§6.1）。按「能不能出图」排：第 7 项先，第 17 项次之。按「出图后能不能稳定」排：第 17 项先。

### 4.3 `60` §5.2 应新增的两项

`KNOWN`（证据来自上游的 reach 注记与模块文档）

| 新增项 | 为什么必需 | 证据 |
|---|---|---|
| **20. cubic filter 的 sampler 必须有确定答案** | `Feature::SamplerBicubicFilter`（5 处，Reach `system`）的 reach 注记写明：**macOS 26.6.2 建过一个 `MTLSamplerMinMagFilterCubic` 的 runtime sampler（消费者的启动路径）**，而它的 mip-filtered 形式被上游在每台设备上拒绝。这是启动路径上的一个 sampler，不是 app 的可选项 | `REFUSALS.md` 第 1 节 `SamplerBicubicFilter` 行 |
| **21. 交给 runtime 的每张 color 目标都要带 input attachment usage** | 见 §4.4 的 R43-2。它不是一个「Metal 特性」，而是一条实现约束，但它决定首帧是否多付两次全屏拷贝，所以应与 19 项并列 | `framebuffer_fetch.rs`、`attachment_stand_in.rs`、`texture/wrapped.rs` |

`INFERRED`：另外三项建议从「必需」降为「有条件必需」，理由是上游的 reach 都不是 `system`，且首帧单采样路径不走：第 13 项的 MSAA 组合、第 18 项的 depth/stencil resolve、第 19 项里真正的 YCbCr 路径（`'b3a8'` 是 RGB，见 §7 R-08）。

### 4.4 本节产出的实现规则

> **R43-2（input attachment usage）**：**本项目交给 `metal2vulkan-runtime` 的每一张可能成为 color attachment 的 image，都必须带 input attachment usage。** 包括：`41` R41-14 建的 `'b3a8'` shadow image、IOSurface plane 上的 in-place linear image、以及任何经 `Device::adopt_*` / wrapped 路径交进去的 image。依据：在 Lavapipe 这类有 `rasterizationOrderColorAttachmentAccess` 的设备上，runtime 自己建的 color render target 都带该 usage，但**调用方的 image 可能没有**，于是 fetch 它的 pass 会渲进一张 scratch 并在 `Load` 前拷进、`Store` 后拷回。`KNOWN`（机制）+ `INFERRED`（本项目的处置）
>
> **R43-3（IOSurface plane 高度）**：**本项目自己创建的 IOSurface，plane 高度一律取 4 的倍数**（不够就向上取整并在 attachment 里记真实高度）。依据：`ExplicitPlaneRowsPastHeight`（§3.1 #3）在 lavapipe 上会按 4 行一块渲染并越界写，上游的规避是「那里不建高度非 4 倍数的此类 image，纹理走 shadow」。我们自己建的 surface 不该把自己逼进 shadow。导入的 surface 若高度非 4 倍数，接受 shadow 并记 `shadowed-texture`。`INFERRED`（输入为 `KNOWN`）
>
> **R43-4（refusal 落日志的字段）**：每个被拒绝的调用记四个字段：`variant` 名、`Feature` 或 `RuntimeGap`、`Unsupported::needs` 转成的稳定 wire 值、以及**该条在 `REFUSALS.md` 里的 Reach**。第四个字段是本册新增的要求：它让排障时能立刻判断「这是系统路径还是某个 app 的罕见用法」。`INFERRED`
>
> **R43-5（`metal-takes` 单独统计）**：Basis 为 `metal-takes` 的 28 条（第 8 节 5 条 + 第 9 节 23 条）是上游自己记录的「比 Metal 严格」的开放缺陷。capability manifest 必须单列这一组，命中时按**上游缺陷**上报，不要当成 guest 的错误。`INFERRED`（规则来自 `40` §7.3）
>
> **R43-6（禁止解析通告与拒绝文本）**：沿用 `40` §7.1 与 `41` §2.4：只用 `Degradation::code()`（稳定串 `metal2vulkan-degrade-<kind>`）与 `category()`，只按 `Error` 的 variant 匹配。**本册的全部表格都按 variant 名索引，不按文本。** `KNOWN`（上游要求）

---

## 5. `supportsFamily:` 该怎么答

### 5.1 审计机制回顾

`KNOWN`（来源：`upstream/m2v/crates/metal2vulkan-runtime/src/families/mod.rs` 模块文档与 `GpuFamily`、`FamilyRow`、`RowState`、`Refusal` 四个枚举）

上游把 Apple 两版 feature set 表的**每一个条目**编码成一行：

| 行类型 | 变体数 | 说明 |
|---|---|---|
| feature 行 | `FeatureRow` **144** 个变体 | 两版表按名字匹配（含改名的）；2023 版的 "Argument buffers tier" 按 tier 单元格读到 2026 版的两个 tier 行上 |
| limit 行 | `LimitRow` **62** 个变体 | |
| format 行 | `FormatRow` **69** 个变体 × 一个 `FormatCapability` | 压缩族（如 "ASTC pixel formats"）整族算一个条目 |
| 三个单行家族 | `FamilyRow::Metal4Api`、`MacCatalystProcess`、`NoPublishedColumn` | 分别对应 Metal4、MacCatalyst1/2、Apple11 |

家族取哪一列（转述上游的 orchestrator 规则，日期 2026-10-05）：

- Apple2–Apple10 取 2026 版的 Apple 列，只取 Metal 3 编程模型的行；只属 Metal 4 模型的行就是 `MTL4` API 本身，由 Metal4 家族的单行代表。
- **Common1–Common3 只取 2023 版的 feature 列。那一版没有 Common 的 limits 列，也没有 formats 列。**
- Mac2 取 2023 版的 Mac2 列（含 limits 与 formats）。
- Metal3 取：2023 版 Metal3 的 feature 列（该版有的行）、2026 版其余行中 Metal 3 模型且首个家族不晚于 Apple7 的、以及 **2026 版 Apple7 的 limits 与 formats**。
- Apple1 按 Apple2 答，Mac1 按 Mac2 答。

每行在设备上判一个 `RowState`：`Exact` / `Refused(Refusal)` / `Gap(RuntimeGap)` / `NotADeviceFeature(Framework)`。`RowState::blocks()` 对 `Refused` 与 `Gap` 为 true。**`Device::supports_family` 只在该家族列出的每一行都 `Exact`（或 `NotADeviceFeature`）时返回 true**；`Device::family_blockers` 给出阻断行清单。

`Refusal` 的五个变体：`Unsupported(Unsupported)`、`NotACatalystProcess`、`NoPublishedColumn`、`Query(Query)`、`PointSizeRange`。

本册统计的每列条目数（`KNOWN`，从 `features.rs` 的 `listing()` 与 `limits.rs` 的 `cells()` 逐行统计）：

| 家族列 | feature 行 | limit 行 | format 行 |
|---|---|---|---|
| Common1 | 18 | 0 | 0 |
| Common2 | 37 | 0 | 0 |
| Common3 | 49 | 0 | 0 |
| Mac2（含 Mac1） | 67 | 43 | 有（2023 版 Mac2 的 format 列，排除 Sparse） |
| Metal3 | 84 | 47（取 Apple7） | 有（取 Apple7） |

### 5.2 两条在任何设备上都阻断的行

`KNOWN`（来源：`families/features.rs` 的 `listing()` 与 `state()`，以及 `gap()` / `not_implemented()` 两个辅助函数）

`gap(g)` 返回 `Some(RowState::Gap(g))`，`not_implemented(f)` 返回 `Some(RowState::Refused(Refusal::Unsupported(Unsupported::not_implemented(f))))`。两者**都不看设备**。`first([...])` 取第一个 `Some`。于是只要某行的判定链第一项就是它们之一，该行在**任何** Vulkan 设备上都阻断。

有两行同时满足「在 Common1/2/3、Mac2、Metal3 与 Apple2+ 全部列出」和「判定链第一项无条件阻断」：

| 行（Apple 表的打印名） | `FeatureRow` | 列出于 | 判定 | 后果 |
|---|---|---|---|---|
| **"Linear textures"** | `LinearTextures`，`listing = l(2, 0b111, true, true)` | Apple2+、Common1、Common2、Common3、Mac2、Metal3 | `first([gap(RuntimeGap::Textures)])` | **阻断上述每一个家族** |
| **"Fast resource loading"** | `FastResourceLoading`，`listing = l(2, 0b111, true, true)` | 同上 | `first([gap(RuntimeGap::IoCommandQueues)])` | 同上。上游模块文档明确说明：fast resource loading 是 Metal.framework 标题下但归 runtime 自己的一行，**在建成之前是 gap**，不是 `Framework` 的非阻断行 |

于是结论是确定的：

> **在锚定 commit `219f0136` 上，`Device::supports_family` 对全部 20 个 `GpuFamily` 值、在任何 Vulkan 设备上都返回 false。** `KNOWN`

其余家族各有自己的阻断理由，列出来便于排障：

| 家族 | 阻断理由 |
|---|---|
| Apple1–Apple10 | 上两行 + 另有大量无条件阻断行（Apple7 列统计到 26 条，含 `Imageblocks`、`TileShading`、`SimdgroupMatrix`、`ProgrammableBlending` 的 word-attachment 分支等） |
| Apple11 | `FamilyRow::NoPublishedColumn` → `Refusal::NoPublishedColumn`：两版表都没有它的列 |
| Mac1 / Mac2 | 上两行；另有 `Tessellation`、`IndirectTessellationArguments`、`TextureSwizzle`、`MeshShading`、`PrimitiveId`、`StencilResolve`、`IndirectDrawDispatchArguments`、`DeviceNotifications`；**以及 limit 行 "Maximum size of a point primitive"（`mac2: AtLeast(511)`）在 lavapipe 的 256 上判 `Refused(PointSizeRange)`** |
| Common1 | 上两行 |
| Common2 / Common3 | 上两行 + `Tessellation` + `IndirectDrawDispatchArguments`（+ Common3 的 `StencilResolve`） |
| Metal3 | 上两行 + 另外 17 条（`CoherentMemory`、`BlockTextureReads`、`IntegerCoordinateOffsets`、`GlobalBuiltinsAndBindings`、`SeparateDepthStencilAttachments`、`ResidencySets`、`ShaderLogging`、`ShaderValidation`、`TextureViewPools`、`ColorAttachmentMapping` 等）+ Apple7 的 limits（含 511 像素点） |
| MacCatalyst1 / MacCatalyst2 | `FamilyRow::MacCatalystProcess` → `Refusal::NotACatalystProcess`：runtime 从不在 Catalyst 进程里跑 |
| Metal4 | `FamilyRow::Metal4Api` → `Gap(RuntimeGap::Metal4Api)`：`MTL4` API 未建 |

**这把 `PointSizeRange` 的地位改了。** 它确实是一条阻断行，但它不是第一条，也不是唯一一条，而且它只影响有 limits 列的家族（Mac1/Mac2/Metal3/Apple*），对 Common 无效。`60` §4.1 把它排在「真正的能力上限」第 2 位，高估了。`KNOWN`

### 5.3 本项目的逐值答案

`91-RUNTIME-EVIDENCE.md` 的 `TESTED(25G76)` 行给出参考实现的答案：**APV 不声明任何 GPU family**（`supportsFamily(Mac2)` = False、`Apple9` = False、`Metal3` = False、`Metal4` = False）。这与 §5.2 的上游推论**完全一致**。两条独立证据指向同一个答案。

> **R43-7（`supportsFamily:` 的答案）**：**本项目对全部 20 个 `MTLGPUFamily` 值答 false**，并且**不硬编码**：实现是转发 `Device::supports_family`，启动自检时把 `Device::family_blockers` 对 20 个值的结果全量落盘（`40` §9.5 第 23 条已要求）。`KNOWN`（依据 §5.2 与 `91`）

| 家族 | raw | 本项目答 | 理由 | 标签 |
|---|---|---|---|---|
| `Apple1`…`Apple11` | 1001–1011 | **false** | 非 Apple GPU；且上游在 Apple7 列上统计到 26 条无条件阻断行 | `KNOWN` |
| `Mac1` | 2001 | **false** | 按 Mac2 答 | `KNOWN` |
| `Mac2` | 2002 | **false** | §5.2 的两条无条件 gap；另加 `PointSizeRange`（lavapipe 256 < 511）。**与 APV 的实测一致** | `KNOWN`（上游源码 + `91` `TESTED(25G76)`） |
| `Common1` | 3001 | **false** | `Linear textures` + `Fast resource loading` 两条 gap | `KNOWN` |
| `Common2` | 3002 | **false** | 上两条 + `Tessellation` + `IndirectDrawDispatchArguments` | `KNOWN` |
| `Common3` | 3003 | **false** | 上四条 + `StencilResolve` | `KNOWN` |
| `MacCatalyst1` / `MacCatalyst2` | 4001 / 4002 | **false** | 不在 Catalyst 进程中 | `KNOWN` |
| `Metal3` | 5001 | **false** | 19 条无条件阻断行 + Apple7 的 limits | `KNOWN` |
| `Metal4` | 5002 | **false** | `MTL4` API 未建；`00-OVERVIEW.md` 第 7 节与本项目「不实现 Metal 4」的决定；**`91` 已 `TESTED(25G76)` 确证 APV 也答 false** | `KNOWN` + `TESTED(25G76)` |

**`60` §1.4 要改三处**：`Mac2` 的「目标：true」、`Common1/2/3` 的「目标：true」、`Mac1` 的「true（若 Mac2 为 true）」。见 §7 R-06。

`60` C-01（真机 Intel Mac 在 macOS 26 上 `supportsFamily:` 的全量答案）**不再阻塞本项目的声明决定**：`91` 已经给出同代 x86_64 上参考实现 APV 的答案（全 false），而上游源码给出我们自己栈的答案（全 false）。C-01 仍然有价值，但只作为「Apple 真硬件会答什么」的参照，不是我们的输入。`INFERRED`

### 5.4 全部答 false 的后果

`INFERRED`（这是本节必须回答的，`91` R-007 把它交给了 `60`）

| 对象 | 后果 | 依据 |
|---|---|---|
| **WindowServer** | **不阻断。** 参考实现 APV 在 `macos-26-intel` 运行器上就是这么答的，而那台机器上 WindowServer 正常合成。`supportsFamily:` 全 false 说明系统合成路径不靠它做能力门控 | `91` 第 1 节与 2.3 节（`TESTED(25G76)`）。**这是本项目最重要的一条减压事实** |
| **`_MTLIOAccelDevice` 的 init 链** | **不阻断，但另有硬约束。** 真正会把设备挡掉的是 `initLimits` 的五条 release 断言（`maxColorAttachments`、`maxIndirectBuffers`、`maxIndirectTextures`、`maxIndirectSamplers`、`maxIndirectSamplersPerDevice` 必须非零）与 `argumentBuffersSupport` 必须返回 0 或 1，不是 `supportsFamily:` | `00-OVERVIEW.md` §4.4、`20-OBJC-DEVICE.md` §5.2.1。`91` 实测 APV 的 `argumentBuffersSupport` = 0（Tier 1）、`maxBufferLength` = 1 GiB |
| **普通 app** | **分三类。** ① 不问 family 的（大多数 2D/UI app，用 `MTLDevice` 的具体 limit 与 feature 查询）：不受影响。② 问 family 做分支的：会走它的最低路径，通常是 Metal 2 风格的代码，这对本项目有利。③ **把 family 当硬前置条件、答 false 就退出的**：不可用。第三类的占比未知 | `INFERRED`。关闭方法：`60` C-02 的 selector 直方图加一个 `supportsFamily:` 的参数维度 |
| **`MTLDevice` 的其他能力查询** | **必须独立于 family 正确作答。** family 全 false 不等于能力全 false：`areRasterOrderGroupsSupported`、`supportsTextureSampleCount:`、`argumentBuffersSupport`、`readWriteTextureSupport`、`supports32BitFloatFiltering` 等各自有独立答案，由 `DeviceProperties` 与 `pixel_format_capabilities` 推出 | `40` §7.5 的 capability manifest 生成规则 |
| **能力报告** | **必须能回答「为什么 false」。** 对每个家族落盘 `family_blockers` 的行清单（`FamilyRow::label()` 给出 Apple 表的打印名），并把 §5.2 的两条列为「burn-down 的第一项」 | `60` §6 第 7 条；上游模块文档把 `family_blockers` 称为「剩余 runtime 工作排期所依据的 burn-down」 |

`INFERRED`：如果将来要让某个家族变 true，最省的路径是 Common1：它只有 18 个 feature 行、没有 limits 行、没有 format 行，阻断它的只有两条（`Linear textures` 的 `RuntimeGap::Textures` 与 `Fast resource loading` 的 `RuntimeGap::IoCommandQueues`）。而 `Fast resource loading` 是 group `io` 的 44 项（L），本项目已决定不做。**所以即使补了 `Textures`，Common1 仍然是 false，除非连 `MTLIOCommandQueue` 一起做。** 这个结论应该让「声明家族」从排期里彻底去掉。

---

## 6. 精度与快路径

`KNOWN`（来源：`upstream/m2v/docs/FAST-PATHS.md`）

上游的规则（转述）有两条，先立住，否则这一节会被误读：

1. **设备的原生算术就是合同。** 设备有原生形式的运算（`float`/`half` 算术与函数、NaN 位、min/max、舍入、texel 与颜色转换、sampler 与滤波、resolve），那个形式就是唯一的形式，**没有任何路径去模拟 Metal 的位**。设备没有的仍然实现或模拟，那属于能力。
2. **精度记录永不致命。** 每条与 Metal 的差异记进管线 artifact 的 `PrecisionNote`，并在 runtime 建管线状态时以 `metal2vulkan-degrade-<code>` 通告。工作照跑；只有 Metal 自己拒绝的才终止。

所以 `60` §6 的能力报告规则要加一句：**「支持」这一列的语义是能力，不是位级一致。** 位级差异由 degradation code 清单承担。

### 6.1 七个 fast default 与本项目的配置

`KNOWN`（开关名、默认值、accurate 形式、通告 code 来自 `FAST-PATHS.md` 的 "Fast defaults" 表；`DevicePolicy::exact_answers()` 一次设全）

| # | 默认（快） | accurate 开关 | 通告 code | 本项目取值 | 理由 |
|---|---|---|---|---|---|
| 1 | packed 16 位 attachment（`A1BGR5Unorm`、`ABGR4Unorm`）的 in-shader 混合，读 attachment 的 code | **没有开关**：accurate 形式（extended-range attachment 的 `half` shadow 被 word attachment 复用）**尚未建** | `DeviceColorConversion`（`device-color-conversion`） | **只能取默认** | 无选择。上游估算 accurate 形式的代价：每个这类 color 一张 pass 尺寸的 `R16G16B16A16_SFLOAT` image，每像素 8 字节，1920×1080 为 16.6 MB。本项目的首帧不用这两个格式，影响为零 |
| 2 | `heap_compression = HeapCompressionPolicy::Compressed` | `Uncompressed` | `HeapTextureCompressed`（`heap-texture-compressed`） | **`Compressed`（默认）** | 该缺陷键是 `DriverFact::CompressedImagesHideAliasedWrites`，上游只点名 **ANV**，lavapipe 不在其中。`INFERRED`：Lavapipe 上这条不触发，取默认零代价。启动自检要确认 `driver_facts` 里没有它 |
| 3 | `completion = CompletionPolicy::Grouped`（就绪的 batch 合并提交，最多四个，只有最后一个 signal 队列 timeline） | `Exact`（每个 batch 一次提交，各自 signal） | `GroupedCompletion`（`grouped-completion`） | **`Exact`** | 该默认只在 `DriverFact::SubmissionsWithoutSignalsMerge` 的驱动上生效，上游点名含 **llvmpipe**，所以在本栈上会生效。但它的代价是「一组里除最后一个外，每个 command buffer 的完成被晚看到，晚的量是后面最多三个 batch 的 GPU 时间」。**WindowServer 的帧同步与 present fence 不能接受不确定的完成延迟**（`11-KERNEL-DISPLAY.md` 的 swap completion 直接挂在 command buffer 完成上），而 Lavapipe 的 timeline 本来就是模拟的、可能比 fence 晚（§3.3 #4），两者叠加风险过高。`INFERRED` |
| 4 | `batch_order = BatchOrderPolicy::Ends` | `Exact` | 不通告 | **`Ends`（默认）** | 该默认只在「队列的某次 kernel 提交不等上一次完成就不开始」的驱动上生效，上游点名 ANV、RADV、NVIDIA，**不含 lavapipe**。那里两个值行为相同，上游写明「代价：无」。`INFERRED` |
| 5 | `half_chains = HalfChainPolicy::AtExits`（`half` 加减乘链在 `float` 精度上保持，只在值离开链时舍入一次） | `EachOperation` | `FastMathRewrites`（`fast-math-rewrites`） | **`AtExits`（默认）** | 只在没有 `shaderFloat16` 的设备上有区别。`60` §2.2 记 Lavapipe 的 `shaderFloat16` 随 llvmpipe cap，x86_64 上为 true → **两个值行为相同**。`BLOCKED`（等 L-02 确认 `shaderFloat16`）；若实测为 false，改取 `EachOperation`，因为 CoreAnimation 的 blur 走 `half4`（`60` §5.1 的 `half_slice_nans`），精度差异会直接落在合成结果上 |
| 6 | `host_page_textures = HostPageTexturePolicy::InPlace`（只采样/只读的纹理在 host 页上原地做 linear image，由设备自检放行） | `Shadow`（每张都是影子，每个用它的命令缓冲前拷入、每次写后合并回） | 走影子时发 `shadowed-texture`；自检通过时不通告 | **`InPlace`（默认）** | **这是 `41` 全册的基础**，改成 `Shadow` 等于放弃 no-copy 路径。上游的自检覆盖 texel、行间字节与 image 之后的字节，1/2/4/8/16 字节 texel 与 3840×2160 surface，各三轮，判定结果按驱动+release+runtime+页类别存在着色器缓存目录里。代价对比：`Shadow` 下一张被采样的 3840×2160 surface 每个命令缓冲整张拷贝。`INFERRED`。**注意自检本身是一条「有意的、受限的、越过 Vulkan 文档行为」的例外（上游自称 owner's ruling）**，所以它产出的 degradation 属 `Validity` 类，按 `40` §7.1 第 3 条必须单独统计 |
| 7 | `pipeline_waits = PipelineWaitPolicy::Bounded`、`pipeline_creation_wait = 4.5 s`、`pipeline_commit_wait = 4.5 s` | `Exact`（创建在返回前把预测管线建完；命令缓冲等每个 draw/dispatch 的管线建完） | `DrawDroppedStillMaking`（`draw-dropped-still-making`）、`DispatchDroppedStillMaking`（`dispatch-dropped-still-making`） | **`Bounded`，但两个时限必须重算**（见 §6.2） | **本项目最危险的一个开关**，理由全在 §6.2 的实测数里 |

### 6.2 管线等待：本项目必须重算的那一条

`KNOWN`（实测数全部来自 `FAST-PATHS.md` 的同一行与 "Costs of matching Metal" 节）

上游记录的事实，按对本项目的杀伤力排序：

| # | 事实 | 杀伤力 |
|---|---|---|
| 1 | **在命令缓冲编码过程中创建管线状态的宿主（上游写明：消费者在某次 execution 第一次查到 guest 的状态时创建它）会把那次 execution 卡住整个编译时长：在 M2 Pro 上一次 execution 内 11.59 s（MoltenVK 1.4.2、冷的 Metal 编译服务），超过 guest 的 10 s FIFO 检查，于是 guest 的 task 被结束** | **这是「guest 被杀」而不是「画面少东西」。本项目的 type-5 user client 路径正是这个形状** |
| 2 | 两个时限各取 4.5 s 的理由：一次创建与一次 commit 可能落在 guest FIFO 的同一个 step 里（一个 task 的 job 顺序跑，而 draw 自己的变体在它的命令缓冲时限下等），且没有任何 runtime 调用同时等两者，**所以一个 step 最多等 9 s，压在那 10 s 检查之下** | 这是上游为「有 10 s 看门狗的 guest」专门算的余量，只有 1 s |
| 3 | M2 Pro 冷启动的 2,483 次 render state 创建（含翻译）：300 次超过 16 ms、151 次超过 100 ms、14 次超过 250 ms、3 次超过 1 s，最长三个是 11.59 s、5.82 s、1.17 s。默认下其中 **2 次超过 4.5 s**，它们的 draw 在落地前提交的命令缓冲里被丢掉 | 冷启动的长尾很长，而且是双峰：绝大多数很快，少数极慢 |
| 4 | 把时限改成 1 s：冷启动丢了 39 个 draw，**guest 的菜单栏只画了一次，于是一直是半张** | 时限不能随便往下调 |
| 5 | macOS 26 最大的 CoreAnimation fragment 是 **210,033 words**。NVIDIA 的编译器冷缓存下约 1 s；**共享该模块的其他状态随后 13 到 16 ms，热缓存 2 ms**。该模块把几个采样 helper 各内联了五到六次，去重能降下来，但上游没做 | 热缓存与共享模块的两个数是本项目预热策略的目标值 |
| 6 | `WorkCounts::creations_left_making` 记「创建在时限到了还在建」的次数；`WorkCounts::draws_dropped_still_making` 与 `dispatches_dropped_still_making` 记被丢的 draw/dispatch；`CommandBuffer::dropped_draw` 给第一个被丢的 draw 并带 `VK_TIMEOUT` | 这三个计数是唯一的「画面静默少了东西」的信号 |

> **R43-8（管线等待预算）**：`pipeline_creation_wait` 与 `pipeline_commit_wait` **不得沿用上游默认的 4.5 s + 4.5 s**，必须按本项目的看门狗预算重算，并与 `11-KERNEL-DISPLAY.md` 的 scanout 超时、`50-IPC-HELPER.md` D66 的超时预算表一起定。约束是三条：
> 1. 两者之和必须严格小于 guest FIFO 检查窗口（上游按 10 s 算）；
> 2. 时限太短会丢 draw 且**不报错**（上游实测 1 s 丢 39 个 draw、菜单栏半张），所以不能用「调小时限」换安全；
> 3. 真正的出路是**让长编译不发生在首帧**：`Device::warm` + `PipelineRecord` 的跨进程预热必须随镜像预置缓存（`60` §7.1 已定），把 210,033 words 那条从「冷缓存 1 s（独显）」变成「热缓存 2 ms」。
>
> `INFERRED`（取值待定）。**这是 Gate 4 之后第一个必须有数的量**，`80-TEST-HARNESS.md` 要为它单列一个测量项：在目标 guest 上统计一次冷启动的 render state 创建次数与时长分布，对照上游 M2 Pro 的 2,483 / 300 / 151 / 14 / 3 分布。
>
> **R43-9**：`WorkCounts::draws_dropped_still_making` 与 `dispatches_dropped_still_making` 非零必须报警并打印 `CommandBuffer::dropped_draw`（`40` §7.2 第 1、3 条已要求）。本册补一条：**这两个计数要进 display provider 的每帧日志**，因为对 WindowServer 来说它是静默损坏，而 display provider 是唯一能把它和「这一帧画面不对」对上的地方。`INFERRED`

### 6.3 默认就是 Metal 的开关

`KNOWN`

- `render_lowering = RenderLoweringPolicy::AtCall`（默认）在调用内做 lowering，调用返回每个拒绝。`Worker` 把 lowering 推到设备的 lowering 线程（32 个调用一批），于是只有 lowering 才发现的拒绝变成「命令缓冲失败并点名那个调用」（`CommandBufferError::CallRefused`），而不是从调用返回。
  **本项目取 `AtCall`（默认）。** 理由：ObjC shim 的错误要在 selector 返回时给出，否则 `21`/`22` 分册的错误映射无从下手；而且 `AtCall` 是 Metal 的形状。`INFERRED`
- `pointer_domain`、`handle_domain`、`containment`、`isolation` 不是精度选择，它们决定资源怎么解析、guest 怎么被容纳。**本项目的取值归 `40` §6.6 的固定 `DeviceOptions` 表**，本册不重复。

### 6.4 没有开关的设备缺口

`KNOWN`（来源：`FAST-PATHS.md` 的 "Not speed choices: device gaps" 表）。这些不是速度选择，是设备没有精确形式，**本项目无从配置**，只能记进能力报告的降级清单：

| 缺口 | 通告 code | 与本项目的关系 |
|---|---|---|
| 数学库（`sin`/`exp`/`log`/`pow`/`sinh`/`cosh`/`tanh`/`atan2` 等）、快除法与快倒数、`half` 的 fma、无 `OpFmaKHR` 的 `float` fma，在每台「`float` 函数不是 Metal 自己的」设备上都是设备指令 | `NativeTranscendentals`、`NativeDivision`、`NativeFma` | **Lavapipe 属于这类**（只有 MoltenVK 在 Apple GPU 上是 Metal 自己的）。合成着色器里的任何超越函数都落这条 |
| `dot`、`mix`、`fast::sqrt` 是设备的 `OpDot`、`FMix`、`Sqrt`，不是 Metal 的融合链 | `NativeDot`、`NativeMix`、`NativeTranscendentals` | 同上 |
| 用 fetch 模拟的滤波按设备算术求和：Metal 的 bicubic 在每种格式上，以及 **extended-range 纹理的 linear、3D 与 linear-mip-filter 采样** | `BicubicFilterArithmetic` | **直接命中 `RGB10A8_2P_XR10`**：上游写明「没有格式持有 extended-range 的 code」，所以 XR 纹理的线性采样一律走解码后的 `FMix`。另有「mipmap 的两 plane 3D 纹理的读（`RGB10A8_2P_XR10` 及其 sRGB 双生）」单列为已知缺口 |
| fast-math 的和、差、积按设备编译器分组与融合 | `FastMathRewrites` | 相对结果无界（混合符号的和被另一种方式分组时） |
| `air.pack` / `air.unpack` 的归一化格式转换是设备的转换；**每一种 extended-range、padded 10 位或 bfloat texel 的转换都在 shader 里做**（`BGR10_XR`、`BGRA10_XR`、`RGB10A8_2P_XR10`、`R10Unorm_X6`、`RG10Unorm_X12`、它们的 sRGB 双生、`RGB10A2Unorm_sRGB`、bfloat 系），因为没有 Vulkan 格式持有这些 code：读是 `float(c - 384)` 乘以最接近 `1/510` 的 `f32`，写是夹紧后乘积的 `RoundEven` 加 384 | `DevicePackConversion` | **登录屏 attachment 的编解码就是这条**。误差界上游给到位：pack 的 code 在 Metal 的一个 code 内，unpack 的值在正确舍入商的 2.5 ulp 内，sRGB 双生解码在 Metal 表 `k/4095` 步长的半个 12 位步（`1/8190`）内 |
| 加载并存储 extended-range / padded 10 位 / bfloat color attachment 的 pass **保留 draw 没写的字节**（每台设备，含 MoltenVK），而 Metal 的 pass 把 draw 触及的每个 32×32 tile 整块写回（未用位规范化、`BGRA10_XR` 的 alpha code 夹到 `[384, 894]`） | `ExtendedRangeBitsKept`、`SnormMinimumKept`、`SharedExponentKept` | 对本项目是**好消息**：`'b3a8'` 的 shadow 拆分 pass 只需管 draw 写过的区域；非 Metal 写入（上传、拷贝）留下的字节在 draw 触及的 tile 里会不同，但 extended-range texel 两种读法得到同一个值 |
| 混进 extended-range attachment 的颜色在 shader 里混合，**在 pixel interlock 内（lavapipe 上在它的 input attachment 上）**，用设备算术；**未与 Metal 比对过** | `ExtendedRangeBlendSource`、`ExtendedRangeFloatBlendSource` | 「未与 Metal 比对过」是本册要标出的：登录屏混合结果的正确性**没有上游参照**，必须由 `80-TEST-HARNESS.md` 的像素比对自己建基线 |

### 6.5 对 `60` §6 能力报告规则的增补

> **R43-10**：`60` §6 的七条规则之上加三条。`INFERRED`（输入全为 `KNOWN`）
>
> 8. **每个「支持」的能力要附三样东西**，不是一样：它会触发的 `Degradation` code 清单（`60` §6 第 6 条已有）、它命中的 `PrecisionNote` 清单（§6.4，`FAST-PATHS.md` 的 code）、以及**它所依赖的 `DevicePolicy` 开关取值**（§6.1）。开关一改，前两样都变，所以三者必须绑在一起进 manifest。
> 9. **`DevicePolicy` 的七个取值必须进 capability manifest 并有变更记录。** 依据：`exact_answers()` 一次设全，任何人改一个值就改变了本项目报告的精度语义。
> 10. **「未与 Metal 比对过」的路径单列一节。** 目前已知至少一条（extended-range attachment 的 shader 混合）。这类路径的正确性只能由本项目自建基线，不能引用上游的界。

---

## 7. 对 `60-CAPABILITY-MATRIX.md` 的更正清单

这是本册交给 `60` 的工单。28 条，按 `60` 的节序排列。

| # | `60` 的节 | 原结论 | 更正后结论 | 依据 |
|---|---|---|---|---|
| R-01 | §0.2 | 给了 2135 / 958 / 828 / 349 与 S/M/L/XL，但**没说行的单位** | 行的单位是 macOS 27.0 SDK Metal 头文件的**公共条目**（`property` 1049、`method` 801、`class` 153、`protocol` 79、`class method` 30、`function` 21、`category` 2）。**不含 enum 值与常量**，所以与 `40` §8 的 301 个 `MTLPixelFormat` 是两个互不相干的计数系。计数本身**全部核实通过，不用改** | 本册 §1.1、§1.2（`coverage.tsv`） |
| R-02 | §1.1 | 「上游表中 `MTL4*` 与 `MTLTensor` 合计约 **432 项**（369 + 18 + 45）」 | 按 header 是 **519 项**（`MTL4*` 474 = missing 374 + out of scope 100；`MTLTensor.h` 45）。按上游工作分组的 missing 是 **455 项**（`mtl4` 369 + `ml` 18 + `tensor` 68）。**另注明 `mtl4` 的 369 项里有 13 项挂在 `MTLDevice` 上，不在 `MTL4*` header 内**（§1.6 给出全部 13 个 selector 名） | 本册 §1.6 |
| R-03 | §3.21 | 「`MTL4*` 全族（§1.2 的 **432 项**）」 | 同 R-02 | 同上 |
| R-04 | §4.3 | 「Metal 4 全族（**432 项**）」「`MTLTensor` + ML encoding（**63 项**）」 | Metal 4 全族 519（header 口径）/ 455（group 口径，missing）。`MTLTensor` + ML encoding 按 group 是 **86 项**（`tensor` 68 + `ml` 18）；63 是 header 口径（`MTLTensor.h` 45 + `ml` 18），两种口径不要混用 | 同上 |
| R-05 | §3.16、§4.2 第 1 项、§2.3 最后一行 | 「tessellation 执行**缺**（`Tessellation` 拒绝，13 处构造点，basis `ours`：every device (not implemented)）」「tessellation 是 Lavapipe 有、上游缺的典型项，纯工作量 L」 | **上游的 patch draw（直接与间接）已建**（`tessellation.rs`）：设备启用 `tessellationShader` 时走设备的 tessellation 阶段，**没有时走模拟**（`render/tessellation_scan.rs`）。13 处拒绝是两类窄形式：patch 未声明 control-point 数（`[[patch(kind)]]`）的 post-tessellation vertex function，以及设备阶段下 fragment function 读 `[[primitive_id]]`。**Reach 是 `rare`，不是「全拒绝」。** 但 family 审计行 `FeatureRow::Tessellation` 仍无条件 `not_implemented`，所以它仍是家族声明的阻断行 | `families/features.rs` 的 `F::Tessellation` 说明；`REFUSALS.md` 的 `Tessellation` 行 |
| R-06 | §1.4 | `Mac2`「目标：true」、`Common1/2/3`「目标：true」、`Mac1`「true（若 Mac2 为 true）」、`Metal3`「待定，倾向 false」 | **全部 20 个 `GpuFamily` 值答 false**，在任何 Vulkan 设备上都如此。根本原因是两条在 Common1/2/3、Mac2、Metal3、Apple2+ 全部列出且判定链第一项就无条件阻断的行：`"Linear textures"` → `Gap(RuntimeGap::Textures)`、`"Fast resource loading"` → `Gap(RuntimeGap::IoCommandQueues)`。与 `91` 实测的 APV 全 false 一致。**「不硬编码、转发 `Device::supports_family`」的决定不变** | 本册 §5.2、§5.3；`91` §2.3 `TESTED(25G76)` |
| R-07 | §4.1 第 2 项 | 「Metal 的 511 像素大点」排在「真正的能力上限」第 **2** 位，「这是一行会直接阻断 `supportsFamily:` 的硬项」 | 它确实阻断（`LimitRow::PointSize` 的 `mac2: AtLeast(511)`，lavapipe 上界 256 → `Refused(PointSizeRange)`），**但它不是第一条也不是唯一一条**，而且**对 Common1/2/3 完全无效**（2023 版表没有 Common 的 limits 列）。在它之前已有两条无条件 gap 阻断同一批家族。权重应从「真正的能力上限第 2 位」降为「Mac2/Metal3/Apple* 的若干阻断行之一」 | 本册 §5.2；`families/{mod,limits}.rs` |
| R-08 | §3.6 的格式表、§5.1 的证据表 | 「两 plane YCbCr 纹理（`YCBCR8_420_2P` 系）｜**SYS**（RenderBox 在 26.6.2 guest 上对 `'b3a8'` surface 建过）」 | **`'b3a8'` 不是 YCbCr。** 它 `ContainsYCbCr = 0`、`ContainsRGB = 1`、`ContainsAlpha = 1`、`BitsPerComponent = 10`、`ComponentRange = WideRange`、两个 plane（plane 0 每块 32 位、plane 1 每块 8 位且 `BlackBlock = 0xFF`）。正确说法：**RenderBox 在 26.6.2 guest 上对一张两 plane 的 10 位宽色域 RGB + A8 surface 建过纹理**，而那正是登录路径那个 `RGB10A8_2P_XR10` attachment 的 surface 侧形态。于是 §5.1 原本看起来不相干的第 1 条与最后一条是**同一条事实的两端** | `41` §3.5.1、§3.5.2 |
| R-09 | §3.14 | ray tracing「上游明确范围外，**265 项**」 | out of scope 中注记为 ray tracing 的是 **303 项**。265 只是五个专属 header 的小计；另 38 项散在 `MTLRenderCommandEncoder.h` 9、`MTL4ComputeCommandEncoder.h` 6、`MTLDevice.h` 5、`MTLHeap.h` 4、`MTLArgumentEncoder.h` 3、`MTLComputeCommandEncoder.h` 3、`MTLCommandBuffer.h` 2、`MTLLibrary.h` 2、`MTLComputePipeline.h` 1、`MTLFunctionDescriptor.h` 1、`MTLIndirectCommandBuffer.h` 1、`MTLRenderPipeline.h` 1。**这 38 项是普通 encoder 与 device 上的 ray tracing 接缝，报 false 时不能漏** | 本册 §1.5 |
| R-10 | §5.2 | 19 项必需 | **新增两项**：20. cubic filter 的 sampler 必须有确定答案（`Feature::SamplerBicubicFilter` 5 处、Reach `system`，上游记明 macOS 26.6.2 在启动路径上建过 `MTLSamplerMinMagFilterCubic` 的 runtime sampler，其 mip-filtered 形式被每台设备拒绝）；21. 交给 runtime 的每张可能成为 color attachment 的 image 都要带 input attachment usage（R43-2） | 本册 §4.3 |
| R-11 | §5.2 第 3 项 | 「render pass：color attachment、Load/Store/Clear/DontCare｜CoreAnimation 合成 pass｜`KNOWN`」 | 加标注：**命中 `RuntimeGap::Render`（26 处构造点，Reach `system`，Where 为 `every device (runtime piece not built)`）**，上游注「render pass、resolve 与 attachment 的若干形式未建（20 处见附录）」。换设备无用 | 本册 §2.3 #7 |
| R-12 | §5.2 第 11 项 | 「no-copy `Shared` buffer（经 `VK_EXT_external_memory_host`）」 | 加标注：**命中 `Feature::HostMemory`（7 处，Reach `system`）**。好消息是上游实测 lavapipe 导入指针、且与 NVIDIA 一样导入了同样的共享内存；但 `DriverFact::PointerImportsFollowTheirAddress` 含 lavapipe，**活导入在每次提交时读该指针当时映射的页**，这给 `41` R41-3 加了第二个理由 | 本册 §2.3 #6、§3.3 #7 |
| R-13 | §5.2 第 5 项 | 「compute（pipeline、threadgroup、buffer/texture binding、barrier）｜blur 用 kernel」 | 加三条标注：① Lavapipe 子组宽 = 向量宽/32，x86_64 + AVX2 下为 **8**，32 宽走模拟；② `RuntimeDriverDefect::ImmutableSamplersLostAfterCopies` 对每个 lavapipe release 都生效，烘焙了 immutable sampler 的 dispatch 要单独记一个 `VkCommandBuffer`；③ **lavapipe 的 NaN 转换与 Metal 不同**，而 `60` §5.1 的 `half_slice_nans` 证据正是「blur 把 kernel 的 `half4` NaN 写进 16 位 float 纹理」 | 本册 §3.1 #4、§3.3 #14、#16 |
| R-14 | §2.1 | 「Lavapipe `timelineSemaphore = true`，满足」 | 加注：**lavapipe 的 timeline 是模拟的**。上游记明已 signal 的 fence 所在 batch 一定到达了它的值，但驱动可能比 fence 更晚显示该值；lavapipe 要等提交该 batch 的线程装好它的 point（在 batch 跑完之后），负载高的宿主可以把它压到 fence 之后。**`50-IPC-HELPER.md` 的事件语义与 present fence 时序不得假定 timeline 与 fence 同步** | `command_buffer/completion.rs` |
| R-15 | §2.3 | 「sample location 网格 1×1、坐标上界 0.9375、`sampleLocationSubPixelBits = 4`」 | 加注：lavapipe 的 `sampleLocationSampleCounts` **只有 `{4}`**；上游明确**不用**这个属性去卡 `setSamplePositions:count:` 的 count，因为那样会拒掉「4 采样 pass 里给 2 个位置」这种 Metal 会跑的 pass。**本项目不要自己再加一层 count 校验** | `sample_positions.rs` |
| R-16 | §2.3、§8.1 | 没有任何 `RuntimeDriverDefect` 条目 | **新增一节**：上游点名 `DriverId::MESA_LLVMPIPE` 的驱动缺陷共 5 条（`MultisampledDepthStencilColourCopies`、`DepthStencilResolveFirstSubresource`、`ExplicitPlaneRowsPastHeight`、`ImmutableSamplersLostAfterCopies`、`TenBitCodesReadAsWords`），每条带上游的测量版本与规避方式。按 `40` §7.4，它们必须进 capability manifest | 本册 §3.1（`driver_defects.rs`） |
| R-17 | §2.2 | 「`VK_EXT_fragment_shader_interlock` + `VK_EXT_rasterization_order_attachment_access`（color/depth/stencil 三者皆 true）｜framebuffer fetch 与 raster order group 有落点」 | 明确化：上游有两种**精确**形式，lavapipe 走的是 **input attachment + `rasterizationOrderColorAttachmentAccess`** 那一种（上游点名「both lavapipes of the venues」）。代价是在这类设备上每张 color render target 同时也是 input attachment，而**调用方的 image 可能没有该 usage**，于是 fetch 它的 pass 会渲进 scratch 并在 `Load`/`Store` 两侧各拷一次 | `framebuffer_fetch.rs`、`attachment_stand_in.rs`、`texture/wrapped.rs` |
| R-18 | §4.4 | 「上游缺 828 项，其中 376 项是 XL」「补上游的 S/M 级缺口（**约 300 项**）」 | 给精确数：**XL 的 376 项 100% 是 Metal 4**（`mtl4` 358 + `ml` 18）。**L 的 160 项全部落在本项目已决定不做的范围**（`tensor` 68、`io` 44、`stitching` 24、`mtl4` counter heap 11、`shadervalidation` 6、`persistent` 5、`access-counters` 2）。于是 L+XL = **536 项一次性全部划出**；S+M = **292 项**是真正要补的，扣掉已决定不做的 `capture` 25、`logging` 20、`counters` 54 后是 **193 项**。**这条比原文有力得多：「不做 Metal 4」这一个决定消掉了全部 XL** | 本册 §1.3 |
| R-19 | §7.1 | 性能风险表只有「210,033 words，RTX 5080 上约 1 s」与「4.5 s × 2 vs 10 s FIFO」 | 补上游实测的硬数：① 在命令缓冲编码中创建管线会把那次 execution 卡住整个编译时长，**M2 Pro 上 11.59 s，超过 guest 的 10 s FIFO 检查并结束了 guest 的 task**；② 冷启动 2,483 次 render state 创建的分布（>16 ms 300 次、>100 ms 151 次、>250 ms 14 次、>1 s 3 次，最长 11.59 / 5.82 / 1.17 s），默认下 2 次超 4.5 s 并丢了它们的 draw；③ 把时限改成 1 s 丢了 39 个 draw，**菜单栏一直是半张**；④ 210,033 words 那个模块的后续数：共享该模块的状态 13 到 16 ms，热缓存 2 ms。**于是「预热」不是优化而是首帧的前置条件，而且有明确目标值** | `FAST-PATHS.md`；本册 §6.2 |
| R-20 | §3.9 的 sparse 行、§4.1 第 1 项 | 「sparse 全族｜m2v 有｜Lavapipe 仅 Linux｜不可行」 | 补一个独立原因：即使设备有 sparse，上游 family 审计的 `SparseTextures` / `SparseDepthStencilTextures` 行的判定链里还有 `Gap(RuntimeGap::SparseHeaps)` 与 `Gap(RuntimeGap::TextureAccessCounters)`，**两者无条件阻断**。所以 sparse 不可行有上游与 Lavapipe 两个独立理由，不止一个 | `families/features.rs` 的 `F::SparseTextures` |
| R-21 | §3（矩阵）缺行 | 没有 `newLibraryWithSource:` 这一行 | **新增一行**：从 MSL 源码编译 library。覆盖表里是 19 项 out of scope（「着色器以 metallib 或 AIR 进入」），runtime 侧是 `RuntimeGap::LibrarySource`（1 处，**Reach `app`**）。后果：guest 里运行期调 `newLibraryWithSource:` 的 app 全部失败，除非 `32-COMPILER-PLUGIN.md` 的路径接住（源码交给 guest 内的 Metal 编译器产出 metallib 再喂给 runtime） | 本册 §2.5 |
| R-22 | §3.3 | 没有 `HiddenDepthStencil` 与 `ColorAttachmentGroups` | **新增两行**：① `RuntimeGap::HiddenDepthStencil`（2 处，Reach `app`）：draw 的 depth/stencil state 用了 pass 没有的 depth 或 stencil，**纯 Metal 会按隐藏的 `float` 深度 1.0 测试**。建议在 descriptor 期归一化，不要向上报错。② `RuntimeGap::ColorAttachmentGroups`（1 处，Reach `app`）：设备一次画不了那么多 color attachment 时分组绘制，而分组路径有未建的形式。与 `00-OVERVIEW.md` §4.4 的 `maxColorAttachments` 非零断言相关 | 本册 §2.5 |
| R-23 | §2.3 的 subgroup 行 | 「`minSubgroupSize = maxSubgroupSize = lp_native_vector_width / 32`（128 位向量 → 4；256 位 → 8）」 | 定值：上游记明 **lavapipe 的向量宽度随宿主，带 AVX2 的 x86 上是 256 位**，`LP_NATIVE_VECTOR_WIDTH=256` 可强制较宽的那个；另有一处记明 lavapipe 在 128 位宽度下有会杀进程的故障。**所以 x86_64 上子组宽是 8，并且 `70-BUILD-PACKAGE.md` 必须显式固定 `LP_NATIVE_VECTOR_WIDTH=256` 并把它写进 capability manifest** | `docs/VALIDATION.md`、`metal2vulkan-validation/src/worker/device.rs` |
| R-24 | §2.3 | 没有进程退出的条目 | **新增一行**：队列在本进程里跑的设备（`DeviceKind::Cpu`：lavapipe、SwiftShader）把工作跑在本进程线程上，所以**退出必须等本进程队列的在途工作**。上游实测：带在途工作退出时，lavapipe 的队列线程还在编译 dispatch 的 shader（LLVM 的 `MCJIT::finalizeObject`），进程死在 `free()` 的堆检查里（300 次中 5 次 + 1 次）；带工作的 lavapipe 进程退出耗 2 s；校验层 1.4.357 下带活设备退出会在 `vkWaitSemaphores` 内 `SIGABRT`。**`50-IPC-HELPER.md` 的 helper 退出路径与 `73-DEPLOY-RESCUE.md` 的超时预算要含这 2 s** | `exit_guard.rs` |
| R-25 | §9 的 C-01 | 「Intel Mac 在 macOS 26 上 `supportsFamily:` 的全量答案｜`BLOCKED`｜阻塞 §1.4 的声明决定」 | **降级为参照，不再阻塞声明决定。** §1.4 的声明决定由两条独立证据定案：上游源码推出我们自己栈的答案（全 false，§5.2），`91` 实测参考实现 APV 的答案（全 false，`TESTED(25G76)`）。C-01 仍有价值，但只用来回答「Apple 真硬件会答什么」 | 本册 §5.3 |
| R-26 | §8.1 | 上游证据清单只列了 13 个路径 | 增补本册引用的上游路径（本册 §8 给出全表），至少要加：`scripts/metal-coverage/coverage.tsv`、`crates/metal2vulkan-runtime/src/driver_defects.rs`、`framebuffer_fetch.rs`、`attachment_stand_in.rs`、`host_memory.rs`、`exit_guard.rs`、`command_buffer/completion.rs`、`sample_positions.rs`、`families/limits.rs`、`families/formats.rs`、`crates/metal2vulkan/src/error/mod.rs`、`docs/VALIDATION.md` | 本册 §8 |
| R-27 | §2.3 的 `gpuCoreCount` 行、§3.1 的 `gpuCoreCount` 行 | 「上游 `capabilities.rs`：驱动未列厂商 core-count 扩展时返回 `None`，并明确把 lavapipe 列入此类」 | **核实通过，无需更正。** `capabilities.rs` 与 `private_properties.rs` 两处都把 lavapipe 列入「不列任何厂商 core-count 扩展」。保留原文 | `capabilities.rs`、`private_properties.rs` |
| R-28 | §3.6 的两 plane YCbCr 行 | 「Lavapipe 有（`samplerYcbcrConversion`、`VK_EXT_ycbcr_2plane_444_formats`）｜适配」 | 加注两条上游缺陷：① `TenBitCodesReadAsWords`（lavapipe、RADV、NVIDIA）把 10 位 code 的 16 位字当 16 位归一化值读；② `TwoPlaneChromaMisplaced` 使 lavapipe/RADV/NVIDIA 的 4:2:0 与 4:2:2 色度位置错。上游在这些设备上一律走 Metal 的算术转换，不拒绝，但精度与位置都要记 | 本册 §3.1 #5、§3.3 |

**更正清单共 28 条**：其中 **9 条是事实性错误**（R-02、R-03、R-04、R-05、R-06、R-07、R-08、R-09、R-18），**17 条是缺失的一手事实**（R-10 到 R-17、R-19 到 R-24、R-26、R-28），**2 条是核实通过的确认**（R-01 的计数部分、R-27）。

---

## 8. 证据来源

### 8.1 上游（metal2vulkan，commit `219f01365dc4c8eb346816c405b5b17403793764`，许可 `GPL-2.0-or-later OR LGPL-3.0-or-later`）

| 路径 | 本册用到的内容 |
|---|---|
| `scripts/metal-coverage/coverage.tsv` | 覆盖表的生成源（11 列 × 2135 行）。§1 的全部计数从它统计 |
| `scripts/metal-coverage/coverage.py` | 生成规则与 `--sdk` 校验方式 |
| `docs/METAL-COVERAGE.md` | 行的单位定义、implemented / missing / out of scope 三分的定义、S/M/L/XL 的定义、Totals、Missing in build order |
| `docs/REFUSALS.md` | 九节共 497 行；§2、§3 的全部拒绝事实。列定义（Where / Basis / Sites / Reach）、Totals、Totals by basis |
| `scripts/refusal-surface/refusal_surface.py`、`reach.tsv` | 拒绝面的生成方式与 Reach 的维护位置 |
| `docs/FAST-PATHS.md` | §6 全节：七个 fast default 与开关、默认就是 Metal 的开关、设备缺口表、匹配 Metal 的代价（含 210,033 words、2,483 次创建的分布、11.59 s、39 个 draw、菜单栏半张） |
| `docs/VALIDATION.md` | lavapipe 作为 CPU ICD 的角色、`LP_NUM_THREADS=1`、向量宽度随宿主与 `LP_NATIVE_VECTOR_WIDTH`、`cutover/c3-venues.json` 的两个 lavapipe venue |
| `docs/HOWTO.md` | host 内存导入在各驱动上的实际结果（含 lavapipe 与 QEMU 的 `memory-backend-memfd,share=on`） |
| `docs/API.md` | §9 的精度注记目录；`MetalGpuFamily` 的拒绝语义 |
| `crates/metal2vulkan-runtime/src/families/mod.rs` | `GpuFamily` 20 个值、两版 feature set 表的列规则、`FamilyRow`、`RowState`、`RowState::blocks()`、`Refusal` 五个变体（含 `PointSizeRange` 点名 lavapipe 256）、`Framework` |
| `crates/metal2vulkan-runtime/src/families/features.rs` | `FeatureRow` 144 个变体、`listing()` 的列编码、`state()` 的判定链、`gap()` 与 `not_implemented()` 的无条件性、`F::Tessellation` / `F::LinearTextures` / `F::FastResourceLoading` / `F::ProgrammableBlending` / `F::PrimitiveId` / `F::SparseTextures` 的具体判定 |
| `crates/metal2vulkan-runtime/src/families/limits.rs` | `LimitRow` 62 个变体、`LimitRow::PointSize` 的 cells（`mac2: AtLeast(511)`）与 `Refused(PointSizeRange)` 的触发条件、Mac2 列出 43 条 limit |
| `crates/metal2vulkan-runtime/src/families/formats.rs` | `FormatRow` 69 个变体、`FormatCapability` |
| `crates/metal2vulkan-runtime/src/driver_defects.rs` | 驱动缺陷的键（`driverID` + `deviceID`）、处置规则、`MESA_LLVMPIPE` 的 5 条缺陷全文 |
| `crates/metal2vulkan-runtime/src/framebuffer_fetch.rs` | 两种精确形式；lavapipe 走 input attachment 形式；两者都没有时拒绝管线 |
| `crates/metal2vulkan-runtime/src/attachment_stand_in.rs` | fetched texture 的 scratch 规则、memoryless attachment 的 backing、`Load`/`Store`/`DontCare` 的拷贝时机 |
| `crates/metal2vulkan-runtime/src/image_plan.rs` | 每张 color render target 也带 input attachment usage；sRGB 双生（lavapipe 的 `R8_SRGB`）；sample location 兼容的 depth |
| `crates/metal2vulkan-runtime/src/texture/wrapped.rs`（经 `framebuffer_fetch.rs` 与 `attachment_stand_in.rs` 引用） | 调用方的 image 可能没有 input attachment usage |
| `crates/metal2vulkan-runtime/src/host_memory.rs`、`host_residency.rs`、`host_shared_pointers.rs`、`buffer_descriptor.rs` | 导入门控、各驱动的导入结果、`DriverFact::PointerImportsFollowTheirAddress` 含 lavapipe、只读页的差异 |
| `crates/metal2vulkan-runtime/src/buffer.rs` | `LINEAR_IMAGE_ALIGNMENT = 256`；实测最大 linear-image 对齐（lavapipe 64） |
| `crates/metal2vulkan-runtime/src/command_buffer/completion.rs` | lavapipe 的模拟 timeline 可能比 fence 晚显示值 |
| `crates/metal2vulkan-runtime/src/exit_guard.rs` | CPU ICD 的退出等待、lavapipe 的实测退出故障与 2 s |
| `crates/metal2vulkan-runtime/src/queue.rs`、`degradation.rs` | `Degradation::SharedPresentQueue`（`shared-present-queue`）点名 lavapipe 单队列；约 150 个 degradation kind；各条精度注记里点名 lavapipe 的部分 |
| `crates/metal2vulkan-runtime/src/resolve.rs`、`depth_stencil_resolve.rs`、`depth_copy.rs`、`depth_stand_in.rs` | lavapipe 没有 `Min`/`Max` depth resolve 模式；替代路径 |
| `crates/metal2vulkan-runtime/src/sample_positions.rs` | lavapipe 的 `sampleLocationSampleCounts` 只有 `{4}`；不要用该属性卡 count |
| `crates/metal2vulkan-runtime/src/memory.rs` | lavapipe 上 image 绑定等队列锁而非 ioctl |
| `crates/metal2vulkan-runtime/src/capabilities.rs`、`private_properties.rs` | `gpuCoreCount` 在 lavapipe 上无来源 |
| `crates/metal2vulkan-runtime/src/clear_value.rs`、`shadow_stencil.rs`、`sample_copy.rs`、`texture.rs`、`linear_plan.rs`、`ycbcr.rs`、`ycbcr_device.rs`、`work_counts.rs` | 各条 lavapipe 精度与缺陷注记 |
| `crates/metal2vulkan/src/error/mod.rs` | `Feature` 枚举、`ExtendedRangeBlend` 三个变体（`DualSource` / `OneColorChannel` / `Output`）与「只拒绝 `Output`」的说明、`LowerFamily` 13 个变体、`PrivateRenderField` |
| `crates/metal2vulkan/src/metal/format/mod.rs` | 格式候选表的机制（由位布局决定，不看设备名） |
| `.github/workflows/ci.yml`、`AGENTS.md` | lavapipe 在上游 CI 中的位置；`qualify-public-cases` 与 `conformance replay --cpu` |

### 8.2 本项目

- `docs/spec/00-OVERVIEW.md` 第 7 节：证据标签规则；§4.7 最小集规格作废；§4.4 `initLimits` 的五条 release 断言。
- `docs/spec/40-RUNTIME-VULKAN.md` §7：degradation / work counts / refusal 的消费规则（只用 `code()` 与 `category()`，禁止解析通告文本，只按 `Error` variant 匹配）；§7.5 capability manifest 的六项生成输入；§8 像素格式全量对应表与 `FormatEmulation`；§6.6 固定 `DeviceOptions`；§9.5 家族审计落盘要求。
- `docs/spec/41-IOSURFACE-USERSPACE.md` §3.5：`'b3a8'` 的九项判别属性与归类更正；§3.5.3 由算术推出的 shadow 强制与每帧 16.6 MB 成本；§2.3 三种导入模式的决策树；§3.3 macOS 无 dma-buf 故只剩三条退路；R41-3、R41-8、R41-14。
- `docs/spec/60-CAPABILITY-MATRIX.md`：本册的更正对象，全文。
- `docs/spec/91-RUNTIME-EVIDENCE.md`：`TESTED(25G76)` 的运行证据，特别是 APV 不声明任何 GPU family、`argumentBuffersSupport = 0`、`maxBufferLength = 1 GiB`、运行器本身跑着 AppleParavirtGPU；R-007 由本册 §5.3/§5.4 结案。
- `.github/workflows/build-lavapipe-macos.yml`：§3.4 全部 `BLOCKED` 项的解除通道。

### 8.3 引用与许可说明

上游文档的内容全部为转述与结构化，未连续摘录超过 30 词。枚举名、符号名、计数、特性名、稳定 code 串按接口事实原样记录。**内容已转述以符合许可限制。**

`upstream/m2v` 在 `.gitignore` 内，不进仓；本册只引用路径、节名与符号名，不复制上游代码或文档正文。

---

## 9. 未解决项清单

| 编号 | 事项 | 标签 | 查清方法 | 阻塞谁 |
|---|---|---|---|---|
| K-001 | Lavapipe 在 macOS x86_64 上的实际 feature / limit / format / 扩展全表 | `BLOCKED` | `build-lavapipe-macos` workflow 的产物 + `vulkaninfo` + `Device::pixel_format_capabilities` 全量扫描 | §3.4 的 L-01 到 L-10；`60` 第三列全部 |
| K-002 | `rasterizationOrderColorAttachmentAccess` 在 macOS 构建下是否仍为 true | `BLOCKED` | 同 K-001 | **首帧可行性的单点**。false 时 framebuffer fetch 退到 storage attachment 形式，`RGB10A8_2P_XR10` 的混合会多一层代价；两者都没有则管线被拒 |
| K-003 | `DeviceProperties::driver_defects` 的实测集合是否就是 §3.1 的 5 条 | `BLOCKED` | 启动自检落盘 + 与 §3.1 比对（R43-1） | capability manifest；§4.1 的第 5、8、10、12、19 行 |
| K-004 | 目标 guest 上一次冷启动的 render state 创建次数与时长分布 | `BLOCKED` | `80-TEST-HARNESS.md` 新增测量项，对照上游 M2 Pro 的 2,483 / 300 / 151 / 14 / 3 分布 | R43-8 的两个时限取值；`60` §7.1 |
| K-005 | `pipeline_creation_wait` 与 `pipeline_commit_wait` 的最终取值，以及它与 display provider 超时、`50` D66 超时预算表的关系 | `INFERRED` | K-004 的数据 + `11-KERNEL-DISPLAY.md` 的超时预算一起定 | `40` §6.6、§9.6 第 26 条 |
| K-006 | guest FIFO 检查窗口在 25G325 x86_64 上是否确为 10 s | `BLOCKED` | 上游按 10 s 算（出处是消费者的 guest）。本项目要在目标 guest 上自己测一次 | R43-8 的第一条约束 |
| K-007 | `Feature::Lowering` 的 13 个 `LowerFamily` 中，系统合成路径实际命中哪几个 | `BLOCKED` | `60` C-02 的 selector 直方图加一个维度：翻译失败时记 `LowerFamily` | §2.7 第 6 名的真实权重；S6/S7 的取舍 |
| K-008 | `Feature::ExtendedRangeBlend` 的三个被拒形式中，WindowServer 与 RenderBox 的登录管线实际落哪一个 | `BLOCKED` | 在目标 guest 上抓那两条管线的 fragment function 输出签名（是否四个 `half`/`float` lane）与 blend state | **§4.2 认定的最致命项**。若落 `Output`，必须补上游或在 descriptor 期拦 |
| K-009 | `Feature::SamplerBicubicFilter` 在启动路径上建的那个 sampler，是否真的走 mip-filtered 形式 | `BLOCKED` | 同 K-008 的 trace 加 sampler 维度 | `60` §5.2 新增的第 20 项（R-10） |
| K-010 | `AgxUnmodeled`（Apple 自己库里的 AGX intrinsic）在 x86 guest 的系统 metallib 上是否真的 `rare` | `BLOCKED` | 用 `30-SHADER-AIR.md` 的解析工具扫系统 metallib 的 intrinsic 直方图 | §2.4.3 的例外 2；它若不 `rare`，翻译面要重估 |
| K-011 | `'b3a8'` 的 `CVPixelFormatDescription` 九项属性在 25G325 本机上的复核 | `BLOCKED` | `41` S-003：`91` 分册的 CI 通道一次性关掉 | R-08 的证据等级（现为 `INFERRED`，关掉后升 `KNOWN`） |
| K-012 | guest 内 app 调 `newLibraryWithSource:` 的占比 | `BLOCKED` | `60` C-02 的直方图加 `newLibraryWithSource:` 计数 | R-21；`32-COMPILER-PLUGIN.md` 要不要接这条路 |
| K-013 | 把某个家族变 true 的最省路径是否真的需要连 `MTLIOCommandQueue` 一起做 | `INFERRED` | 读 `RuntimeGap::IoCommandQueues` 在 family 审计里的全部出现位置；确认 `Fast resource loading` 这一行是否可以用 `Framework` 语义绕过 | §5.4 末段的结论；若能绕过，Common1 只差一条 `RuntimeGap::Textures` |
| K-014 | Lavapipe 的 `shaderFloat16` 在 macOS x86_64 构建下是否为 true | `BLOCKED` | K-001 的同一次扫描 | §6.1 第 5 行 `half_chains` 的取值；blur 的 `half4` 精度 |
| K-015 | `completion = CompletionPolicy::Exact` 的实际代价（提交数与 CPU 时间）在 Lavapipe 上有多大 | `BLOCKED` | K-001 之后用上游的 `frame_costs` lane 在目标栈上跑一次 | §6.1 第 3 行的取值。若 `Exact` 代价过高，需要为 present 队列单独开一条不分组的路径 |
| K-016 | `DriverFact::CompressedImagesHideAliasedWrites` 在 Lavapipe 上是否确实不触发 | `BLOCKED` | 启动自检落盘 `driver_facts` | §6.1 第 2 行 `heap_compression` 的取值 |
| K-017 | extended-range attachment 的 shader 混合结果，本项目的像素基线 | `BLOCKED` | 上游写明这条「未与 Metal 比对过」。`80-TEST-HARNESS.md` 必须自建基线：在真机 Intel Mac 或 `91` 的 CI 运行器上抓同一组 blend state 的 Metal 结果 | R43-10 第 10 条；登录屏像素正确性 |
| K-018 | `LP_NATIVE_VECTOR_WIDTH` 固定为 256 后，子组宽是否确为 8，以及 `subgroupSupportedStages` 的内容 | `BLOCKED` | K-001 的同一次扫描 | R-23；`60` C-03 |
