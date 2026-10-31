# Metal selector → metal2vulkan 调用的全量映射

文档版本：1.0
基线：macOS Tahoe 26.7.2 build 25G325，**x86_64**
上游锚定：metal2vulkan `219f01365dc4c8eb346816c405b5b17403793764`，产品版本 `0.2.0`
上游许可：`GPL-2.0-or-later OR LGPL-3.0-or-later`（分发前二选一，见 `docs/METAL2VULKAN_INTEGRATION.md` §9）
上游工作副本：`upstream/m2v`（在 `.gitignore` 里，**不进仓**。本文是它的规格化转述，不含上游代码）
状态：有效。本文是 `40-RUNTIME-VULKAN.md` 第 3.3 节的兑现。

---

## 0. 本文作用

`40-RUNTIME-VULKAN.md` 第 3.3 节标题是「逐 selector 对照表的权威位置」，内容却只是一张指向上游 `docs/RUNTIME-PORTING.md` 各节的索引表。索引不是映射：实现者照着它写不出一行转发代码。本文把那张索引兑成本仓库自己的规格。

本文回答四件事：

1. **左侧**（Metal selector，`91-RUNTIME-EVIDENCE.md` §2.4 确证的 25 个协议）**逐条落在上游哪个 `crate::path::item` 上**，签名是什么，参数怎么转，返回怎么转，错误怎么处置；
2. 没有落点的条目**属于 `40` 第 4 节十项里的哪一项**，还是 `40` 第 4 节**没登记的新 gap**（第 7 节，本文最有价值的输出）；
3. selector → Rust 的**机械转换规则集**（第 2 节），以及上游「encoder 被消费」与 ObjC「`endEncoding` 之后对象还在」的**所有权错配处置**（第 3 节）；
4. 上游 typed error → 我们的 `NSError` 的**完整穿透规则**（第 4 节）与 adapter fixture 的**验收形状**（第 9 节）。

### 0.1 本文不重复什么

| 不重复 | 在哪 |
|---|---|
| 上游明确不做、留给本项目的十项 | `40` 第 4 节。本文第 8 节只给**交界表**：每一项在映射表里表现为什么 |
| Vulkan device 创建要求、固定 `DeviceOptions`、`DevicePolicy` | `40` 第 6 节。本文一行不抄 |
| descriptor 的字段级处置（A/B/C/D 四档） | `22-OBJC-DESCRIPTORS.md`。本文第 6 节只给**交界点**与对 `22` 的三处修正 |
| 像素格式全量对应 | `40` 第 8 节 |
| 对象清单（上游公开类型全集） | `40` 第 2 节。本文用它的类型名，不重列 |
| 线程与所有权总则 | `40` 第 5 节。本文第 3 节只细化「消费」这一条 |
| selector 的 x86_64 type encoding 与 APV 的 RVA | `21-OBJC-OBJECT-FAMILY.md` 第 8 节与附录 A。本文的 encoding 列是**引用**，不是新证据 |

### 0.2 读法

实现者按本文第 5 节建 ObjC adapter 的转发表：**一行一个 selector，照「上游调用」列写一次调用，照「参数转换」「返回转换」「错误处置」三列写胶水**。某条的精确语义差异（上游标 `*(partial)*` 的 46 行）去读该 item 的 rustdoc；本文在「备注」里注明哪些行是 `*(partial)*`。

### 0.3 证据标签

按 `00-OVERVIEW.md` 第 7 节。本文的额外约定：

- **`KNOWN`**：上游源码或上游文档直接给出。来源写 `upstream/m2v` 的文件路径 + 行号或符号名。本文全部上游签名均取自**源码**（`pub fn` 抽取，857 条），不取自文档，因为 `40` §0 要求「文档与源码冲突时信源码」。
- **`KNOWN`（本项目）**：`21` / `91` 的实测。
- **`INFERRED`**：本文的适配决策。
- **`BLOCKED`**：左侧 selector 本仓库尚未逐条枚举，或上游语义未查清。每条进第 11 节。
- **`TESTED(25G76)`**：`91` 的运行器实测，按 `91` §0.1 的限定。

### 0.4 以 `91` 为准的四处改名

`91` §2.2 证伪了 `21` 的四个类名。**本文左侧一律用 `91` 的真实链，不沿用 `21` 里那四个编出来的名字。** `TESTED(25G76)`

| `21` 写的 | 真实情况 | 本文怎么写 |
|---|---|---|
| `_MTLRenderCommandEncoder` | **不存在** | 渲染编码器的 ObjC 宿主类由本项目自建（照 APV 的 `PGSerializerRenderCommandEncoder` 形态，`21` §3），父类取 `NSObject`；`_MTLParallelRenderCommandEncoder` **存在**（size 232 / im 28 / ivar 20），parallel 路径可继承它 |
| `_MTLComputeCommandEncoder` | **不存在** | 同上 |
| `_MTLBlitCommandEncoder` | **不存在** | 同上 |
| `_MTLBuffer` / `_MTLTexture` / `_MTLEvent` | **不存在** | 资源链是 `MTLIOAccelBuffer -> MTLIOAccelResource -> _MTLResource -> _MTLAllocation -> _MTLObjectWithLabel`。本文第 5.7–5.9 节的「本地可答」列据此定位：`label` / `setLabel:` 由 `_MTLObjectWithLabel` 提供，`allocatedSize` 由 `_MTLAllocation` 提供 |
| `MTLLibraryBuilder` / `MTLLibraryDataWithArchive` | **不存在** | 第 5.11 节不提这两个名字 |

这条改名有一个直接后果写在第 3.2 节：**encoder 宿主类没有 Apple 抽象基类可继承**，所以「`endEncoding` 之后对象进入什么状态」完全由本项目定义，没有 Apple 的既有行为可抄。

---

## 1. 口径：左侧、右侧与计数

### 1.1 左侧：Metal selector 的来源

`KNOWN`（本项目）。协议条目数取 `91` §2.4（运行期确证，25 个协议），逐条 selector 名与 x86_64 encoding 取 `21` 第 8 节与附录 A。两者的关系：

| 协议 | 条目数（`91` §2.4） | `21` 是否逐条枚举 | 本文处理 |
|---|---:|---|---|
| `MTLDevice` | 137 req + 2 opt | ✅ §8.2 全量 | 逐条 |
| `MTLDeviceSPI` | 427 req + 80 opt | ❌ 只给 9 类普查（§8.3）与 28 条交集（§8.1.2） | **按语义分组给表 + 每组规则**（第 5.20 节）；逐条枚举记 `M-002` |
| `MTLCommandQueue` | 11 | ✅ §8.4 | 逐条 |
| `MTLCommandQueueSPI` | 25 req + 22 opt | ❌ | 分组 + 规则（第 5.2.2 节），记 `M-004` |
| `MTLCommandBuffer` | 39 | ✅ §8.4 | 逐条 |
| `MTLCommandBufferSPI` | 21 req + 36 opt | ❌ | 分组 + 规则（第 5.3.2 节），记 `M-004` |
| `MTLCommandEncoder` | 8 | ✅ §8.4 | 逐条 |
| `MTLRenderCommandEncoder` | 131 | ✅ §8.5 全量 | 逐条 |
| `MTLComputeCommandEncoder` | 39 | 部分：附录 A.2 给 35 条（APV 自实现的），4 条继承未列 | 逐条（35 带 encoding，4 条标来源） |
| `MTLBlitCommandEncoder` | 24 req + 2 opt | 部分：附录 A.3 给 23 req + 2 opt | 逐条（25 带 encoding，1 req 记 `M-005`） |
| `MTLBuffer` | 11 | ✅ §8.6 | 逐条 |
| `MTLTexture` | 36 req + 3 opt | ✅ §8.6 | 逐条 |
| `MTLResource` | 14 | ✅ §8.6 | 逐条 |
| `MTLResourceSPI` | 12 req + 1 opt | ✅ §8.6 | 逐条 |
| `MTLHeap` | 21 | ❌（`21` §0.3 说该协议定义副本在 `S-APV` 里，但 §8 未展开） | 按 Metal 公开 API 名逐条，encoding 记 `M-006` |
| `MTLLibrary` | 14 | ✅ §8.8 | 逐条 |
| `MTLFunction` | 13 | ✅ §8.8 | 逐条 |
| `MTLFunctionSPI` | 23 | ❌ | 分组 + 规则（第 5.12.2 节），记 `M-004` |
| `MTLRenderPipelineState` | 26 | ✅ §8.7 | 逐条 |
| `MTLComputePipelineState` | 18 | ❌ | 按 Metal 公开 API 名逐条，encoding 记 `M-006` |
| `MTLDepthStencilState` | 3 | ✅ §8.7 | 逐条 |
| `MTLSamplerState` | 3 | ✅ §8.7 | 逐条 |
| `MTLFence` | 3 | ❌ | 逐条（3 条即 `label` / `setLabel:` / `device`） |
| `MTLEvent` | 3 | ❌ | 逐条（同上） |
| `MTLSharedEvent` | 5 | ❌ | 逐条 |
| `MTLDrawable` | 6 | ❌ | 逐条（整族归 `40` §4 第 4 项） |
| `MTLIOCommandQueue` | 5 | ❌ | 逐条（整族新 gap） |

### 1.2 右侧：上游 item 的来源

`KNOWN`。方法：对 `upstream/m2v/crates/metal2vulkan-runtime/src/**/*.rs`（排除 `tests/`）做 `impl` 块归属的 `pub fn` / `pub unsafe fn` 抽取，得 **857 条**公开方法。按接收者分布（前 25）：

| 上游类型 | 公开方法数 | 定义处（`crates/metal2vulkan-runtime/src/`） |
|---|---:|---|
| `RenderCommandEncoder` | 116 | `render.rs:1313` |
| `Device` | 95 | `device/mod.rs:102`（`DeviceOptions` 在 `device/create.rs:61`） |
| `Texture` | 50 | `texture.rs:393` |
| `ComputeCommandEncoder` | 47 | `compute.rs:154` |
| `CommandBuffer` | 40 | `command_buffer/mod.rs:155` |
| `IndirectRenderCommand` | 32 | `indirect_command_buffer.rs` |
| `RenderPipelineState` | 30 | `pipeline/render.rs:100` |
| `BlitCommandEncoder` | 25 | `blit.rs:157` |
| `Buffer` | 25 | `buffer.rs:63` |
| `IndirectCommandBuffer` | 25 | `indirect_command_buffer.rs:966` |
| `ArgumentEncoder` | 24 | `argument_encoder.rs:168` |
| `Heap` | 21 | `heap.rs:274` |
| `IndirectComputeCommand` | 21 | `indirect_command_buffer.rs` |
| `ComputePipelineState` | 18 | `pipeline/mod.rs:204` |
| `VisibleFunctionTable` | 15 | `function_table.rs:640` |
| `Function` | 12 | `library.rs:55` |
| `RasterizationRateMap` | 12 | `rate_map.rs:160` |
| `DeviceProperties` | 11 方法 + **20 公开字段** | `capabilities.rs:61` |
| `SharedEvent` | 9 | `event.rs:65` |
| `Library` | 8 | `library.rs:33` |
| `ResourceStateCommandEncoder` | 7 | `sparse/encoder.rs:60` |
| `BinaryArchive` | 7 | `binary_archive/mod.rs:70` |
| `DynamicLibrary` | 6 | `dynamic_library.rs:32` |
| `CommandQueue` | 5 | `queue.rs:72` |
| `Fence` / `Event` / `DepthStencilState` | 3 / 3 / 3 | `fence.rs:79` / `event.rs:60` / `depth_stencil.rs:30` |
| `SamplerState` | 2 | `sampler.rs:464` |

上游文档侧的对照（`upstream/m2v/docs/RUNTIME-PORTING.md`）共 **34 个小节、396 行表格、365 行点名了一个 Metal selector 或类型**，其中 **47 行标 `(SPI)`**、**46 行标 `*(partial)*`**。`KNOWN`

**三处文档与源码的差异，本文一律信源码**（`40` §0 的要求）：

1. 上游文档的 `RenderCmd` 一节**不列 mesh / object 阶段的行**（它跟的是某个消费者的接缝），但源码的 `RenderCommandEncoder` **有** `set_object_*`（9 个）、`set_mesh_*`（9 个）、`draw_mesh_threadgroups` / `draw_mesh_threads` / `draw_mesh_threadgroups_indirect`。`40` §3.3 的索引表因此低估了 render encoder 的落点数 21 条。`KNOWN`（`render.rs` 的 `pub fn set_object_buffer` 等符号）
2. 上游文档的 `Platform` 一节不列 `TileRenderPipelineDescriptor` / `MeshPipelineDescriptor` 以外的 tile/mesh 构造，但 `Device::new_tile_render_pipeline_state` / `new_mesh_render_pipeline_state`（含 `_with_reflection`）**存在**。这直接推翻 `22` §5.1 的两行登记，见第 6.2 节。`KNOWN`
3. `40` §7.3 提到的 `Error::LimitExceeded(Limit)` **不在** `metal2vulkan_runtime::Error` 的 27 个 variant 里（它在翻译器 crate 的错误类型里）。本文第 4.1 节按源码的 27 个 variant 给表。`KNOWN`（`crates/metal2vulkan-runtime/src/error.rs:64` 的 `pub enum Error`）

### 1.3 落点分类标记

本文每行用一个标记说明落点性质。`INFERRED`（分类法是本文的实现决策）。

| 标记 | 含义 | 实现动作 |
|---|---|---|
| **`U`** | 有**单一**上游调用。「上游调用」列给 `crate::path::item` 全名，「上游签名」列给精确签名 | 直接转发 |
| **`C`** | 无单一调用，由两个或更多上游调用**组合**而成，或由同一调用的退化参数覆盖 | 照「参数转换」列组合 |
| **`L`** | **本地可答**，不碰上游：纯 getter、常量、limits、声明值回放、debug 簿记 | 在 ObjC 层或 snapshot 里答；limits 查 `20-OBJC-DEVICE.md` 的 limits 表 |
| **`S4-n`** | 无上游落点，属 `40` 第 4 节第 n 项（上游明确不做、留给本项目） | 按该项所属分册实现 |
| **`N-nn`** | 无上游落点，且 **`40` 第 4 节没登记**。第 7 节逐项定义 | 按第 7 节的处置 |
| **`B`** | 左侧或右侧有未查清项 | 进第 11 节 |

### 1.4 覆盖计数（本文主结论之一）

`KNOWN`（计数口径：第 1.1 节的协议条目数 × 第 1.2 节的上游方法集，逐条交叉）。

#### 1.4.1 逐条给出的部分

| 协议 | 条目 | `U` | `C` | `L` | `S4-n` | `N-nn` |
|---|---:|---:|---:|---:|---:|---:|
| `MTLDevice` | 139 | 55 | 15 | 40 | 2 | 27 |
| `MTLCommandQueue` | 11 | 4 | 2 | 5 | 0 | 0 |
| `MTLCommandBuffer` | 39 | 20 | 3 | 10 | 3 | 3 |
| `MTLCommandEncoder` | 8 | 2 | 0 | 5 | 0 | 1 |
| `MTLRenderCommandEncoder` | 131 | 105 | 13 | 0 | 0 | 13 |
| `MTLComputeCommandEncoder` | 39 | 35 | 0 | 0 | 0 | 4 |
| `MTLBlitCommandEncoder` | 26 | 21 | 0 | 0 | 0 | 4 + 1`B` |
| `MTLBuffer` | 11 | 5 | 0 | 5 | 0 | 1 |
| `MTLTexture` | 39 | 26 | 3 | 8 | 2 | 0 |
| `MTLResource` | 14 | 12 | 1 | 0 | 0 | 1 |
| `MTLResourceSPI` | 13 | 1 | 0 | 4 | 0 | 8 |
| `MTLHeap` | 21 | 17 | 0 | 0 | 0 | 4 |
| `MTLLibrary` | 14 | 8 | 2 | 2 | 0 | 2 |
| `MTLFunction` | 13 | 10 | 1 | 2 | 0 | 0 |
| `MTLRenderPipelineState` | 26 | 13 | 0 | 1 | 1 | 11 |
| `MTLComputePipelineState` | 18 | 14 | 0 | 1 | 0 | 3 |
| `MTLDepthStencilState` | 3 | 2 | 0 | 1 | 0 | 0 |
| `MTLSamplerState` | 3 | 2 | 0 | 1 | 0 | 0 |
| `MTLFence` | 3 | 3 | 0 | 0 | 0 | 0 |
| `MTLEvent` | 3 | 3 | 0 | 0 | 0 | 0 |
| `MTLSharedEvent` | 5 | 5 | 0 | 0 | 0 | 0 |
| `MTLDrawable` | 6 | 0 | 0 | 0 | 6 | 0 |
| `MTLIOCommandQueue` | 5 | 0 | 0 | 0 | 0 | 5 |
| **合计** | **590** | **363** | **40** | **85** | **14** | **87 + 1`B`** |

**363 条有单一精确上游落点，40 条由上游调用组合而成，合计 403 条（68.3%）可以直接照本文写转发代码。** 另有 85 条本地可答（`L`）：它们不是缺口，是本来就不该碰上游的纯 getter、常量与 limits。剩下 102 条（87 `N` + 14 `S4` + 1 `B`）里，只有 87 条是真正的缺口，其中 14 个语义簇见第 7 节。

#### 1.4.2 按组给出的部分

| 协议 | 条目 | 处理 | 本文节 |
|---|---:|---|---|
| `MTLDeviceSPI` | 507 | 9 个语义组 × 每组规则 + 承重行逐条（约 20 条 `U`） | 5.20 |
| `MTLCommandBufferSPI` | 57 | 4 组 + 承重行逐条（5 条 `U`，含上游**有**完整实现的 `set_protection_options`、`encode_signal_event_scheduled`） | 5.3.2 |
| `MTLCommandQueueSPI` | 47 | 3 组，`U` = 0 | 5.2.2 |
| `MTLFunctionSPI` | 23 | 2 组，`U` ≈ 4 | 5.12.2 |
| **合计** | **634** | | |

#### 1.4.3 总量

590 逐条 + 634 按组 = **1224 条协议声明条目**。去掉 `MTLDeviceSPI` 对 `MTLDevice` 的 22 条重复声明（`21` §8.1 读法 4，`KNOWN`），**1202 条不同 selector**。

对照上游 `docs/METAL-COVERAGE.md` 的 2135 项：差额是本文范围外的协议（`MTLArgumentEncoder`、`MTLIndirectCommandBuffer` 全族、`MTLRasterizationRateMap` 全族、`MTLBinaryArchive`、`MTLVisibleFunctionTable`、各 `*SPI` 的其余部分、`MTL4*`、加速结构族、tensor 族）。这些协议的上游落点**在本文第 10 节给出速查表**，但不逐条展开：按 `21` §8.0，它们不在第一版必须实现的集合里。

---

## 2. 命名与形态的机械规则集

`40` §3.1 给了一张 15 行的对应表。本节把它扩成**可执行**的规则：每条给判定、正例、反例。规则编号 `K-nn`，实现时按编号引用。

规则的事实基础是上游 `docs/RUNTIME-PORTING.md` 的 "Conventions" 表（`KNOWN`）与第 1.2 节抽取的 857 条签名（`KNOWN`）；正例反例的选取与「反例为什么错」的判断是 `INFERRED`。

### 2.1 K-01 类型名：去 `MTL` 前缀

判定：Metal 的协议名 / 类名 `MTLFoo` → 上游 `Foo`。

| 正例 | 反例（不要这样） |
|---|---|
| `MTLBlitCommandEncoder` → `BlitCommandEncoder` | `MTLBlitCommandEncoder` → `BlitEncoder`。`BlitEncoder` 是上游**文档**里那个消费者接缝的 `Item` 名，不是上游类型名。查类型名只看 `src/lib.rs` 的 `pub use`，不看文档的 `Item` 列 |
| `MTLRasterizationRateMap` → `RasterizationRateMap` | → `RateMap`。同上，`RateMap` 是文档的节名 |
| `MTLIndirectCommandBuffer` → `IndirectCommandBuffer` | → `Icb` |

**例外（必须记住的三个）**：

| Metal | 上游 | 为什么不机械 |
|---|---|---|
| `MTLRenderPipelineDescriptor` | `metal2vulkan::pipeline::RenderPipelineDescriptor` | **在另一个 crate**。runtime 不 re-export（`40` §1.1） |
| `MTLRasterizationRateMapDescriptor` | `metal2vulkan::bind::RateMapDescriptor` | 跨 crate **且** 名字也变了（去掉了 `Rasterization`） |
| `MTLDepthStencilDescriptor` | `metal2vulkan::metal::state::DepthStencilDescriptor` | 跨 crate。`crates/metal2vulkan/src/metal/state.rs:256`。**本文新查清，`22` §5.1 原记 `BLOCKED(descriptor 值类型名)`** |

### 2.2 K-02 方法名：selector → snake_case

判定：取 selector 的第一段（第一个冒号之前，或无冒号时全名），驼峰转下划线，去掉 Metal 的冗余限定词。

```
setVertexBuffer:offset:atIndex:      → set_vertex_buffer
dispatchThreadgroups:threadsPerThreadgroup: → dispatch_threadgroups
newBufferWithLength:options:         → Device::new_buffer
heapTextureSizeAndAlignWithDescriptor: → Device::heap_texture_size_and_align
```

去掉的限定词有固定模式：`WithDescriptor` / `WithLength` / `WithName` / `ForPixelFormat` 之类**描述第一个参数类型**的后缀被删，因为 Rust 的签名已经说明了类型。

| 正例 | 反例 |
|---|---|
| `newTextureWithDescriptor:` → `Device::new_texture` | → `Device::new_texture_with_descriptor`（上游没有这个名字） |
| `newLibraryWithData:error:` → `Device::new_library_with_data` | → `Device::new_library`。**这里后缀留着**，因为上游另有 `new_library_with_source` 与 `new_library_with_compile_library`，`data` 是区分项 |
| `minimumLinearTextureAlignmentForPixelFormat:` → `DeviceProperties::minimum_linear_texture_alignment_for_pixel_format` | → `...::minimum_linear_texture_alignment`。后缀留着 |

**所以 K-02 不能机械套用到名字去重的那几处。** 第 5 节的「上游调用」列是逐条查过源码的结果，**不是按 K-02 推的**。实现时以第 5 节为准，K-02 只用于本文未覆盖的协议（第 10 节速查表之外的部分）的首次猜测，猜完必须回源码核对。`INFERRED`

### 2.3 K-03 多形态 selector 族 → 一个带全参数的上游方法

判定：Metal 为同一操作提供 2–4 个参数数量递增的 selector；上游通常**只有最全的那个**，短形态由调用方补 Metal 的默认值。

```
drawPrimitives:vertexStart:vertexCount:                        ┐
drawPrimitives:vertexStart:vertexCount:instanceCount:          ├→ RenderCommandEncoder::draw_primitives(
drawPrimitives:vertexStart:vertexCount:instanceCount:baseInstance: ┘      primitive_type, vertex_start, vertex_count,
                                                                          instance_count, base_instance)
```

补默认值的表（`KNOWN`：Metal 的文档默认值；标 `C` 的行在第 5 节逐条标出）：

| 缺的参数 | 补什么 |
|---|---|
| `instanceCount` | 1 |
| `baseInstance` | 0 |
| `baseVertex` | 0 |

| 正例 | 反例 |
|---|---|
| `drawPrimitives:vertexStart:vertexCount:` → `draw_primitives(ty, start, count, **1**, **0**)` | → `draw_primitives(ty, start, count, 0, 0)`。`instance_count = 0` 画不出东西，而 Metal 的短形态画一个实例 |
| `useResource:usage:` → `use_resource(res, usage, **RenderStages::all()**)` | 传 `RenderStages::empty()`。上游的 render 版本**总是**点名 stages（`KNOWN`：`RUNTIME-PORTING.md` 的 `RenderCmd::UseResources` 行），Metal 的无 stages 形态等价于全 stages |

### 2.4 K-04 `NSError **` 出参 → `Result<_, Error>`

判定：selector 以 `error:` 结尾，或失败时返回 nil。上游一律 `Result<T, metal2vulkan_runtime::Error>`。

转换方向是**双向的**，两边都有陷阱：

```objc
// 正例
- (id<MTLRenderPipelineState>)newRenderPipelineStateWithDescriptor:(MTLRenderPipelineDescriptor *)d
                                                             error:(NSError **)error
{
    switch (adapter_new_render_pipeline(self->_dev, snapshot, &out)) {
      case OK:        return out;                     // +1 所有权（K-12）
      case FAILED:    if (error) *error = mapped;     // ① error 可以是 NULL
                      return nil;                     // ② 返回 nil 且 *error 已填
    }
}
```

| 规则 | 正例 | 反例 |
|---|---|---|
| `error` 出参可以是 `NULL` | 先判 `if (error)` | 无条件 `*error = ...`，客户端传 `NULL` 时崩 |
| 失败必须同时做两件事 | 返回 nil **且** 填 `*error` | 返回 nil 不填 error（客户端拿到 `nil` + 未初始化的 `NSError *`）；或填 error 却返回非 nil |
| 成功时不碰 `*error` | 原样不动 | 写 `*error = nil`。Metal 不保证清零，客户端可能复用变量，但**也不能**依赖它被清；不碰是唯一安全做法 |
| `Error` 的分支**只匹配 variant** | `match err { Error::Nil(_) => ..., Error::MetalError(e) => ... }` | 读 `err.to_string()` 做 `contains("...")` 判断。`40` §2.9 与上游 README 都明确禁止；第 4.7 节重申 |

**反向陷阱**：上游有些方法返回 `Result` 而对应的 Metal selector **不带 error 出参、也不返回对象**。例如 `RenderCommandEncoder::set_cull_mode` 不返回 `Result`（无错），但 `set_depth_bias` / `set_viewport` / `set_scissor_rect` **返回 `Result<(), Error>`**，而 ObjC 的 `setDepthBias:slopeScale:clamp:` 是 `void`。这类的处置见第 4.3 节：`Err` 必须按 Metal 对该误用的行为分档（assert / 忽略 / 让命令缓冲失败），**不能静默丢弃**。

### 2.5 K-05 nil 参数与 nil 结果 → `Option`

判定：能接受 nil 的参数 → `Option<&T>`；能返回 nil 的结果 → `Option<T>`（与 `Result` 并存时是 `Result<Option<T>, Error>`）。

| 正例 | 反例 |
|---|---|
| `setFragmentTexture:nil atIndex:3` → `set_fragment_texture(**None**, 3)` | 跳过这次调用。Metal 的 nil 绑定**清除**该槽位，跳过会留着上一次的纹理 |
| `setDepthStencilState:nil` → `set_depth_stencil_state(**None**)`（上游签名 `impl Into<Option<&'a DepthStencilState>>`，Metal 的默认状态） | 传一个「全通过」的自建 state。那不是 Metal 的默认状态 |
| `Buffer::contents() -> Option<NonNull<u8>>` → `contents` 返回 `NULL` | `unwrap()`。private storage 的 buffer 没有 contents，Metal 返回 `NULL` |
| `Function::patch_control_point_count() -> Result<Option<u32>, Error>`；`None` → Metal 的 `-1` | `None` → `0`。`patchControlPointCount` 的 encoding 是 `q`（有符号），非 patch 函数答 `-1` |

### 2.6 K-06 `id<MTLxxx>` → 上游 handle

判定：对象参数走本项目的对象表，查出上游 handle 的引用再传。

```
id<MTLBuffer>  →  对象表查 ObjectId  →  &Buffer
```

| 规则 | 说明 |
|---|---|
| 对象表的键是 `ObjectId`，**不是指针** | `40` §3.2 的要求。`Buffer::object_id` / `Texture::object_id` / `Heap::object_id` 是终身唯一、永不复用的（`KNOWN`：`buffer.rs`、`texture.rs`、`heap.rs` 的 `pub fn object_id`）。指针会被复用，generation 机制（`50-IPC-HELPER.md`）因此必须挂在 `ObjectId` 上 |
| 解析不到对象 → **A 档硬错** | `22` §3.6。不得当成 nil |
| 异构资源参数用 `ResourceRef<'_>` | `useResource:`、`synchronizeResource:`、`memoryBarrierWithResources:` 的参数是 `id<MTLResource>`，可能是 buffer 也可能是 texture。上游用 `ResourceRef<'_>`，由 `Buffer::as_resource()` / `Texture::as_resource()` / `IndirectCommandBuffer::as_resource()` 产生（`KNOWN`：三者各有 `pub fn as_resource`） |
| **`MTLHeap` 不是 `ResourceRef`** | `use_heaps` 收 `&[&Heap]`，与 `use_resources` 的 `&[ResourceRef]` 是两个不同签名。Metal 侧 `useHeaps:count:` 与 `useResources:count:usage:` 也是两个 selector，不要合并 |

### 2.7 K-07 C 数组 + count / `NSArray` → slice

判定：`(const id *objs, NSUInteger count)` 或 `withRange:(NSRange)r` → `&[Option<&T>]` + 一个 `first: u32`。

上游的**两种**形态必须分清（`KNOWN`，取自签名）：

| 上游形态 | 出现在 | 签名 |
|---|---|---|
| `(&[Option<&T>], first: u32)` | render / compute encoder 的 `set_*_buffers` / `set_*_textures` / `set_*_sampler_states` | `set_fragment_textures(&mut self, textures: &[Option<&Texture>], first: u32)` |
| `(&[&T], ...)` 不带 `Option` | `use_heaps` | `use_heaps(&mut self, heaps: &[&Heap], stages: RenderStages)` |

`NSRange` → `(first, len)` 的拆法：**`range.location` 给 `first`，`range.length` 必须等于 slice 长度**。

| 正例 | 反例 |
|---|---|
| `setFragmentTextures:ts withRange:{3, 4}` → `set_fragment_textures(&[t0,t1,t2,t3], **3**)`，slice 长度 4 | 传整个 128 槽位的数组再指望上游按 range 取。上游按 slice 长度算，会写 128 个槽位 |
| 数组里的 nil 项 → slice 里的 `None` | 过滤掉 nil 项再传。**会错位**：Metal 的 nil 项清除对应槽位，过滤会让后面的对象左移 |
| `count == 0` → 空 slice，照样调用 | 跳过调用。Metal 的 0 长度绑定是合法无操作，但有些路径靠它触发状态推进 |

**三条带 clamps 的采样器 selector 是 `C` 不是 `U`**，形态在 render 与 compute 之间不同，这是本文最容易踩错的一处：

| selector | render encoder | compute encoder |
|---|---|---|
| `set*SamplerState:atIndex:` | `set_fragment_sampler_state(Option<&SamplerState>, u32)` → `U` | `set_sampler_state(Option<&SamplerState>, u32)` → `U` |
| `set*SamplerState:lodMinClamp:lodMaxClamp:atIndex:` | **上游无单项带 clamps 的方法** → `C`：用 `set_fragment_sampler_states(&[s], Some((&[min], &[max])), index)` | **上游有** `set_sampler_state_with_lod_clamps(Option<&SamplerState>, f32, f32, u32)` → `U` |
| `set*SamplerStates:withRange:` | `set_fragment_sampler_states(&[..], **None**, first)` → `U` | `set_sampler_states(&[..], first)` → `U` |
| `set*SamplerStates:lodMinClamps:lodMaxClamps:withRange:` | `set_fragment_sampler_states(&[..], **Some((mins, maxs))**, first)` → `U` | `set_sampler_states_with_lod_clamps(&[..], &[f32], &[f32], first)` → `U` |

`KNOWN`（`render.rs` 与 `compute.rs` 的签名）。render 侧用一个带 `Option<(&[f32], &[f32])>` 的方法覆盖四个 selector，compute 侧用四个独立方法。**render 的单项带 clamps 形态在 4 个阶段（vertex / fragment / tile / object / mesh，共 5 个阶段）各有一条，合计 5 条 `C`。**

### 2.8 K-08 `NSRange` → `Range<u64>`

判定：`NSRange{location, length}` → `location..(location + length)`。

| 正例 | 反例 |
|---|---|
| `fillBuffer:b range:{16, 32} value:0` → `fill_buffer(&b, **16..48**, 0)` | `fill_buffer(&b, 16..32, 0)`。`NSRange` 的第二个字段是**长度**不是终点 |
| `location + length` 必须 checked 加（`22` R17） | 直接加。`{u64::MAX, 1}` 会回绕成空区间，上游看不出异常 |

**K-07 与 K-08 的分界**：绑定类 selector 的 `withRange:` 走 K-07（拆成 `first` + slice 长度），内存区间类的 `range:` 走 K-08（变成 `Range<u64>`）。判定依据是上游签名：收 `first: u32` 的是 K-07，收 `Range<u64>` 的是 K-08。涉及 K-08 的上游方法：`fill_buffer`、`fill_buffer_pattern4`、`did_modify_range`、`execute_commands_in_buffer`、`reset_commands_in_buffer`、`optimize_indirect_command_buffer`、`copy_indirect_command_buffer`、`reset_with_range`、`IndirectCommandBuffer::commands`、`new_texture_view_with_levels_slices` 的 `levels` / `slices`。`KNOWN`

### 2.9 K-09 block → `Handler` / 回调类型

判定：completion / scheduled block → `Handler`，即装箱 `FnOnce(&CommandBuffer) + Send`（`KNOWN`：`40` §2.2 与 `CommandBuffer::add_completed_handler(&self, handler: Handler)`）。

| 上游回调类型 | 对应 Metal | 签名 |
|---|---|---|
| `Handler` | `addCompletedHandler:` / `addScheduledHandler:` / `add_submission_handler` | `add_completed_handler(&self, handler: Handler) -> Result<(), Error>` |
| `ExecutedCommandsHandler` | 无（runtime 扩展） | `add_executed_commands_handler(&self, handler: ExecutedCommandsHandler) -> Result<(), Error>` |
| `SharedEventNotification` | `MTLSharedEvent` 的 `notifyListener:atValue:block:` | `notify_listener(&self, listener: &SharedEventListener, value: u64, block: SharedEventNotification)` |
| `Deallocator` | `newBufferWithBytesNoCopy:...deallocator:` 的 block | `new_buffer_with_bytes_no_copy(..., deallocator: Option<Deallocator>)` |
| `SubmissionCheck` | 无（runtime 扩展） | `set_submission_check(&self, check: SubmissionCheck) -> Result<(), Error>` |
| `IndirectCommandCheck` | 无（runtime 扩展） | `execute_commands_in_buffer_checked(..., check: IndirectCommandCheck, needs: IndirectCommandCheckNeeds)` |

ObjC block → Rust 闭包的四条硬规则。`INFERRED`（实现决策），理由在右列。

| 规则 | 理由 |
|---|---|
| block 必须 `Block_copy` 到堆上，闭包里 `Block_release` | 客户端传的是栈 block 的常见情形；不 copy 则回调时已失效 |
| 闭包必须捕获 ObjC command buffer 的**弱引用或 `ObjectId`**，不捕获强引用 | 强引用会让 command buffer 在 handler 注册后永不释放（handler 存在 Rust 侧，ObjC 侧的 retain 计数看不到它） |
| handler 在上游的设备线程上跑，**不是**客户端线程 | `CommandBuffer::add_submission_handler` 的 handler 跑在设备的 scheduler 线程上（`KNOWN`：`command_buffer/mod.rs` 的该方法 rustdoc 点明）。handler 里调 ObjC 必须自带 autorelease pool，且不得再调 `waitUntilCompleted`（会触发 `Error::WaitWouldDeadlock`，见第 4.1 节） |
| completion handler 只调用一次 | `40` §5 的既有约束，上游保证。adapter 不得重复投递 |

### 2.10 K-10 结构体按值

判定：`MTLSize` / `MTLOrigin` / `MTLRegion` / `MTLViewport` / `MTLScissorRect` / `MTLClearColor` / `MTLCoordinate2D` / `MTLSamplePosition` → 上游同名值类型 `Size` / `Origin` / `Region` / `Viewport` / `ScissorRect` / `ClearColor` / `Coordinate2D` / `SamplePosition`，按值传。

| 正例 | 反例 |
|---|---|
| `dispatchThreadgroups:{g,1,1} threadsPerThreadgroup:{t,1,1}` → `dispatch_threadgroups(Size{..}, Size{..})` | 把两个 `MTLSize` 展开成 6 个 `u64` 传过窄 C ABI 再在 Rust 侧重组。能跑，但 `MTLRegion` 是 `{MTLOrigin, MTLSize}` 的嵌套（encoding `{?={?=QQQ}{?=QQQ}}`，9 个字段），展开容易错位 |
| `MTLViewport` 的 6 个字段是 `double`（encoding `{?=dddddd}`） | 当成 `float`。`setViewport:` 的 encoding `v64@0:8{?=dddddd}16` 明确 48 字节 |
| `MTLScissorRect` 是 4 个 `NSUInteger`（encoding `{?=QQQQ}`） | 当成 `int`。`setScissorRect:` 的 encoding `v48@0:8{?=QQQQ}16` |
| `MTLClearColor` 是 4 个 `double`（encoding `{?=dddd}`） | 当成 `float4`。`fillTexture:level:slice:region:color:` 的 encoding `...{?=dddd}88` |

全部浮点字段必须过 `22` R19 的非有限值拒绝。

### 2.11 K-11 枚举与 flag word

判定：**一律用上游的 `from_raw`，不得 `transmute`**（`22` R14）。上游提供 `from_raw` 的类型（`KNOWN`，逐个从签名抽出，共 16 个）：

| 类型 | 签名 |
|---|---|
| `ResourceOptions` | `from_raw(raw: u64) -> Result<ResourceOptions, Error>` |
| `StorageMode` | `from_raw(raw: u64) -> Result<StorageMode, Error>` |
| `CpuCacheMode` | `from_raw(raw: u64) -> Result<CpuCacheMode, Error>` |
| `HazardTrackingMode` | `from_raw(raw: u64) -> Result<HazardTrackingMode, Error>` |
| `PurgeableState` | `from_raw(raw: u64) -> Result<PurgeableState, Error>` |
| `LoadAction` | `from_raw(raw: u64) -> Result<LoadAction, Error>` |
| `StoreAction` | `from_raw(raw: u64) -> Result<StoreAction, Error>` |
| `StoreActionOptions` | `from_raw(raw: u64) -> Result<StoreActionOptions, Error>` |
| `DrawPrimitiveType` | `from_raw(raw: u64) -> Result<DrawPrimitiveType, Error>` |
| `VisibilityResultMode` | `from_raw(raw: u64) -> Result<VisibilityResultMode, Error>` |
| `MultisampleDepthResolveFilter` | `from_raw(raw: u64) -> Result<..., Error>` |
| `MultisampleStencilResolveFilter` | `from_raw(raw: u64) -> Result<..., Error>` |
| `HeapType` | `from_raw(raw: u64) -> Result<HeapType, Error>` |
| `SparsePageSize` | `from_raw(raw: u64) -> Result<SparsePageSize, Error>` |
| `SparseTextureRegionAlignmentMode` | `from_raw(raw: u64) -> Result<..., Error>` |
| `GpuFamily` | `from_raw(raw: i64) -> **Option**<GpuFamily>` |

注意最后一个的返回类型是 `Option` 不是 `Result`。`INFERRED`：`supportsFamily:` 收到未知 family 时应答 `NO`（Metal 的行为），不是报错。

**没有 `from_raw` 的枚举**走 `22` R15（自建受检转换，默认拒绝未知值）。重要的几个：

| Metal 类型 | 上游 | 处置 |
|---|---|---|
| `MTLTextureUsage` | `metal2vulkan::metal::TextureUsage` | 封闭 flag，`KNOWN_MASK` 由该类型导出（`22` R22）。`MTLTextureUsageUnknown == 0` 是合法值 |
| `MTLPixelFormat` | `metal2vulkan::metal::PixelFormat` | 301 个取值（`40` §8）；必须同时传该次使用的 `FormatUsage` 集合（`22` §5.2） |
| `MTLDispatchType` | `DispatchType` | 上游另给 `compute_command_encoder_with_raw_dispatch_type(raw: u64)`：**除 1 之外的每个值都按 serial 处理，与 Metal 一致**（`KNOWN`：`RUNTIME-PORTING.md` 的 `CommandBuffer::compute_encoder_for_pass` 行）。所以未知 `MTLDispatchType` 走 raw 路径，不拒绝 |
| `MTLRenderStages` | `RenderStages` | 位域 |
| `MTLBarrierScope` | `BarrierScope` | 位域 |
| `MTLResourceUsage` | `ResourceUsage` | 位域 |
| `MTLIndexType` | `IndexType` | 两个取值 |
| `MTLCullMode` / `MTLWinding` / `MTLDepthClipMode` / `MTLTriangleFillMode` | `CullMode` / `Winding` / `DepthClipMode` / `TriangleFillMode` | 小枚举 |
| `MTLPrimitiveType` 的私有取值 | `DrawPrimitiveType::from_raw` | **值 5–8 合法**（line loop / triangle fan / quads / quad strip），**值 9 不是合法值但 Metal 不拒绝**，让命令缓冲以 GPU 方式失败。`40` §3.2 已记；`22` §3.2 重申「不得比 Metal 更严格」 |

`DeviceProperties::supports_primitive_type(raw: u64) -> bool` 是另一条相关入口（`KNOWN`）：它回答某个 raw primitive 值在本设备上能不能画，用于 pipeline 创建期的预检。

### 2.12 K-12 ObjC 内存管理与 handle 的生命周期

`KNOWN`（`21` §9.1 的实测：`new*` 返回 +1，其余工厂返回 autoreleased）+ `40` §5（handle 是廉价克隆值，`Clone` = retain，`Drop` = release）。

| 规则 | 内容 |
|---|---|
| `new*` selector 返回 **+1** | ObjC 对象的 `dealloc` 里 drop 上游 handle |
| 非 `new*` 工厂（`commandBuffer`、`blitCommandEncoder`、`renderCommandEncoderWithDescriptor:` 等）返回 **autoreleased** | 同上，只是 retain 计数的来源不同 |
| ObjC 的 retain / release 与 Rust 侧**不必 1:1** | 一个 ObjC 对象持有一个 handle；中间的 retain/release 不触碰 Rust |
| 最后一个 ObjC 引用消失时**必须** drop handle | 否则上游对象泄漏，Vulkan 对象也跟着泄漏 |
| `id` 相等 → handle 的 `PartialEq`（按身份） | 但对象表的键用 `ObjectId`（K-06） |
| `deallocator` block 的持有责任在本项目 | `21` §9.5 与 `40` §4 第 1 项。`new_buffer_with_bytes_no_copy` 的 `Option<Deallocator>` 由 adapter 构造，block 要 `Block_copy` |

### 2.13 K-13 `completionHandler:` 变体 → 自建线程 + 同步调用

判定：Metal 的 `...completionHandler:` 形态在上游**没有**对应方法。上游只有同步形态。

| Metal | 上游 | 组合方式 |
|---|---|---|
| `newRenderPipelineStateWithDescriptor:options:completionHandler:` | `Device::new_render_pipeline_state(&descriptor, &options)` | 在本项目的编译线程池上跑同步调用，完成后在同一线程投递 block |
| `newComputePipelineStateWithFunction:completionHandler:` | `Device::new_compute_pipeline_state_with_function` | 同上 |
| `newRenderPipelineStateWithMeshDescriptor:options:completionHandler:` | `Device::new_mesh_render_pipeline_state` | 同上 |
| `newRenderPipelineStateWithTileDescriptor:options:completionHandler:` | `Device::new_tile_render_pipeline_state` | 同上 |
| `newLibraryWithSource:options:completionHandler:` | **无**（上游无 MSL 前端） | `N-13`，见第 7 节 |
| `newFunctionWithName:constantValues:completionHandler:` | `Library::new_function_with_name_constant_values` | 同上 |

`INFERRED`。两条约束：

1. 线程池的并发度必须与 `MTLDeviceSPI` 的 `maximumConcurrentCompilationTaskCount` / `shouldMaximizeConcurrentCompilation` 的回答一致（`L`，`20` 分册定值），否则客户端的并发预期与实际不符；
2. 这条路径的超时必须纳入 `40` §6.6 的 `pipeline_creation_wait` 预算。异步形态不改变总等待上限。

### 2.14 K-14 property vs 方法

判定：ObjC property 的 getter 是零参 selector，上游对应 `pub fn x(&self) -> T`；**但上游有相当一部分「属性」是 `DeviceProperties` 的公开字段，不是方法**。

`DeviceProperties` 的 20 个公开字段（`KNOWN`：`capabilities.rs:61`）：

```
name, kind, has_unified_memory, vendor_id, device_id, device_uuid, pci_bus,
drm_render, api_version, max_buffer_length, max_threads_per_threadgroup,
max_threadgroup_memory_length, argument_buffers_support, read_write_texture_support,
supports_32bit_float_filtering, max_viewports, gpu_core_count, description,
driver_defects, driver_facts
```

`DeviceProperties` 的 11 个方法（`KNOWN`，全部返回 `Result`，因为「这个设备上答不出来」是可能的）：

```
are_programmable_sample_positions_supported() -> Result<bool, RuntimeGap>
are_raster_order_groups_supported()           -> Result<bool, RuntimeGap>
is_depth24_stencil8_pixel_format_supported()  -> Result<bool, RuntimeGap>
supports_texture_sample_count(count: u64)     -> Result<bool, RuntimeGap>
supports_vertex_amplification_count(count: u64) -> Result<bool, RuntimeGap>
supports_rasterization_rate_map_with_layer_count(count: u64) -> Result<bool, RuntimeGap>
supports_sampler_reduction_mode()             -> Result<bool, RuntimeGap>
minimum_linear_texture_alignment_for_pixel_format(format: PixelFormat) -> Result<u64, Error>
supports_primitive_type(raw: u64)             -> bool
supports_texture_write_rounding_mode(mode: u64) -> bool
drops_gpu_writes_to_read_only_memory()        -> bool
```

| 正例 | 反例 |
|---|---|
| `maxBufferLength` → `device.properties().max_buffer_length`（**字段**） | `device.properties().max_buffer_length()`。不是方法 |
| `areRasterOrderGroupsSupported` → `properties().are_raster_order_groups_supported()?`（**方法，返回 `Result<bool, RuntimeGap>`**） | 当成 `bool` 字段。`Err(RuntimeGap)` 的含义是「上游没建这个判定」，必须按第 4.4 节处置，不能当 `false` |
| `gpu_core_count: Option<u32>`，Lavapipe 上为 `None` | `unwrap_or(0)` 当答案。`40` §4 第 8 项把它划给本项目，必须给一个有依据的值 |

### 2.15 K-15 整数宽度

`22` R16 的落地：上游的索引与计数多为 `u32`，offset / length / size 为 `u64`，ObjC 侧一律 `NSUInteger`（64 位）。

逐类对照（`KNOWN`，从签名归纳）：

| 语义 | 上游宽度 | 例 |
|---|---|---|
| 绑定索引 / 槽位 / `first` | `u32` | `set_fragment_buffer(.., index: u32)` |
| byte offset / length / size | `u64` | `set_fragment_buffer(.., offset: u64, ..)` |
| draw 的 vertex/index/instance 计数与 base | **render encoder 用 `u32`**（`base_vertex: i32`），**`IndirectRenderCommand` 用 `u64`**（`base_vertex: i64`） | `RenderCommandEncoder::draw_indexed_primitives(.., index_count: u32, .., base_vertex: i32, base_instance: u32)` vs `IndirectRenderCommand::draw_indexed_primitives(.., index_count: u64, .., base_vertex: i64, base_instance: u64)` |
| threadgroup memory length | `u32`（compute）/ `u64`（render，带 offset） | `ComputeCommandEncoder::set_threadgroup_memory_length(length: u32, index: u32)` vs `RenderCommandEncoder::set_threadgroup_memory_length(length: u64, offset: u64, index: u32)` |
| mip level / slice / plane | `u64` | `Texture::replace_region(.., level: u64, slice: u64, ..)` |
| sample / layer count | `u64` | `RasterizationRateMap::physical_size_for_layer(layer: u64)` |

**render encoder 与 indirect render command 的宽度不同是真实差异，不是笔误。** 同一条 draw 在直接编码与 ICB 录制两条路上要做两套 checked 收窄。`KNOWN`

| 正例 | 反例 |
|---|---|
| `u64 → u32` 用 `u32::try_from(x)`，失败按字段表档位拒绝 | `x as u32`。截断后的索引会写到错误的槽位，而且没有任何信号 |
| `baseVertex` 是 `NSInteger`（有符号），收窄到 `i32` | 收窄到 `u32`。负 base vertex 是合法的 |

---

## 3. 消费 vs 借用：上游对象的所有权错配

这是实现期一定会踩的坑，所以给完整处置而不是一句提醒。

### 3.1 错配的精确形状

`KNOWN`。上游三个编码器的 `end_encoding` 的接收者是 `self`，**不是 `&self` 也不是 `&mut self`**：

```
RenderCommandEncoder::end_encoding(self)         -> Result<(), Error>     // render.rs
ComputeCommandEncoder::end_encoding(mut self)    -> Result<(), Error>     // compute.rs
BlitCommandEncoder::end_encoding(self)           -> Result<(), Error>     // blit.rs
ResourceStateCommandEncoder::end_encoding(self)  -> Result<(), Error>     // sparse/encoder.rs
```

其余编码命令的接收者一律 `&mut self`（`KNOWN`：第 1.2 节抽取的 116 + 47 + 25 + 7 条签名里，除四个 `end_encoding` 与少数 getter 外全是 `&mut self`）。编码器是独占值，`Send` 但**不是 `Sync`**（`40` §5）。

ObjC 侧的事实（`KNOWN`，`91` §2.2 + `21` §9）：

1. `endEncoding` 是 `void`，encoding `v16@0:8`，**不返回错误**；
2. `endEncoding` 之后 encoder 对象仍然存在，客户端可以 `retain` 它、读它的 `label`、读它的 `device`，甚至再调一次编码命令；
3. encoder 宿主类**没有 Apple 抽象基类**（第 0.4 节：`_MTLRenderCommandEncoder` / `_MTLComputeCommandEncoder` / `_MTLBlitCommandEncoder` 都不存在），所以终态行为没有 Apple 实现可抄，必须自己定义；
4. `MTLCommandEncoder` 的 `label` / `setLabel:` / `device` / `pushDebugGroup:` / `popDebugGroup` / `insertDebugSignpost:` 这 6 条**在 `endEncoding` 之后仍然必须能答**，因为它们是 `_MTLObjectWithLabel` 级的簿记，与编码状态无关。

错配因此有三层，不是一层：

| 层 | 错配 | 后果 |
|---|---|---|
| ① 消费 | Rust `end_encoding(self)` 吃掉值 | adapter 之后手里没有 handle |
| ② 独占 | 编码命令要 `&mut self` | 同一 encoder 不能在两个 ObjC 调用之间共享不可变引用，也不能跨线程并发用 |
| ③ 返回值 | `end_encoding` 返回 `Result` | ObjC 的 `endEncoding` 是 `void`，错误无处可去 |

### 3.2 ObjC encoder 对象的内部状态机

`INFERRED`（实现决策）。四态，单向：

```text
          renderCommandEncoderWithDescriptor:
                      │
                      ▼
              ┌───────────────┐
              │   Encoding    │  inner: Some(RenderCommandEncoder)
              └───────┬───────┘
                      │ endEncoding → end_encoding(inner.take().unwrap())
          ┌───────────┴───────────┐
          │ Ok                    │ Err(e)
          ▼                       ▼
   ┌─────────────┐        ┌─────────────────┐
   │   Ended     │        │  EndedFailed(e) │   inner: None
   └─────────────┘        └─────────────────┘
          │                       │
          │  再调编码命令          │  再调编码命令
          ▼                       ▼
   ┌──────────────────────────────────────┐
   │  按第 3.3 节的档位回答（不进新状态） │
   └──────────────────────────────────────┘

   任一状态 + dealloc → Dropped（若 inner 仍 Some，先 drop handle，
                                 等价于「未 endEncoding 就释放 encoder」，
                                 见第 3.4 节）
```

实现约束：

| 约束 | 内容 |
|---|---|
| `inner` 的类型 | `Option<RenderCommandEncoder>`（或对应编码器类型）。`40` §3.2 已要求，本节细化 |
| `endEncoding` 的实现 | `match self->_inner.take() { Some(e) => ..., None => 第 3.3 节的「重复 endEncoding」档 }` |
| `&mut` 的取得 | `inner.as_mut()`。ObjC 对象在一个线程上独占使用（见第 3.4 节），所以 `as_mut` 不需要锁；**但必须有一个 debug 断言检查调用线程与创建线程一致**，否则 ② 层错配会在 release 版变成数据竞争 |
| `EndedFailed(e)` 必须保留 `e` | 因为 `endEncoding` 吞掉了它，唯一能把它交出去的地方是命令缓冲的 `error`（第 3.3 节） |
| **不得**把 `Ended` 的 encoder 复用 | Metal 不允许一个 encoder 被重新打开，上游的消费语义也排除了它 |

### 3.3 消费之后再调用：逐类回答表

`INFERRED`。档位取自 `22` R13 的三档（`abort` / `nil+NSError` / `nil`）加上两档编码器特有的（`忽略` / `失败命令缓冲`）。判定原则：**照 Metal 的行为**；Metal 的行为未实测的，取「不让 WindowServer 崩、也不假装成功」的那一侧，并记入第 11 节。

| 在 `Ended` / `EndedFailed` 状态下调用 | 回答 | 理由 | 标签 |
|---|---|---|---|
| `endEncoding`（第二次） | **忽略**，不报错，不改状态 | Metal 对重复 `endEncoding` 的行为是 validation layer 报告 + release 版无操作。我们没有 validation layer，所以只记一条 degradation 日志 | `INFERRED`；Metal 实测记 `M-007` |
| 任何编码命令（`set*` / `draw*` / `dispatch*` / `copy*` / `fill*` / `use*` / `memoryBarrier*` / `updateFence:` / `waitForFence:` / `executeCommandsInBuffer:*`） | **让所属命令缓冲从此失败**，调用本身返回（`void` selector 无处返回） | Metal 在这个误用上的行为是 assert（debug）/ 未定义（release）。「让命令缓冲失败」是唯一既不崩进程又不产生错画面的选择，而且上游**专门为此提供了入口**：`CommandBuffer::commit_failed(CommitFailure { code, encoders, signals })`（`KNOWN`：`command_buffer/mod.rs:308`） | `INFERRED` |
| `tileWidth` / `tileHeight` | 返回 `Ended` 之前最后一次的值（snapshot） | 上游的 `tile_width()` / `tile_height()` 要 `&self`，handle 已没了。两个值在 pass 期间不变，所以 `Encoding` 期间缓存一份即可 | `INFERRED` |
| `label` / `setLabel:` / `device` | **正常答**，与编码状态无关 | 第 3.1 节事实 4 | `KNOWN` |
| `pushDebugGroup:` / `popDebugGroup` / `insertDebugSignpost:` | **正常答**（本地簿记，`L`） | 同上。上游无对应调用（`N-06` 的一部分） | `KNOWN` |
| `dealloc` | 若 `inner` 仍 `Some`：drop handle | 见第 3.4 节 | `INFERRED` |

**`CommitFailure` 的三个字段怎么填**（`KNOWN`：字段名与语义取自 `command_buffer/mod.rs:308` 的定义与 rustdoc）：

| 字段 | 填什么 |
|---|---|
| `code: u64` | `MTLCommandBufferError` 的码。上游 rustdoc 点名了几个：2 = GPU hang（`Timeout`）、8 = out of memory、1 或 16 = protection fault、0 = 无码（只让它失败） |
| `encoders: FailedEncoders` | 哪些编码器算失败。`FailedEncoders::Set` 的用法在 `40` §4.1 已记（配 `ended_encoders`） |
| `signals: bool` | 失败的提交是否仍然发出它的信号。Metal 的失败提交仍然发信号，否则等它的一方会挂住 → **一律 `true`**，除非实测证明相反 |

### 3.4 ② 层错配：`&mut self` 与 ObjC 的线程

`KNOWN`（上游：编码器 `Send` 不 `Sync`）+ `KNOWN`（`21` §9：Metal 的 encoder 本身也要求单线程使用）。

| 规则 | 内容 | 标签 |
|---|---|---|
| 一个 ObjC encoder 对象只能在一个线程上用 | Metal 的既有约束，与上游一致。**不需要**在 adapter 里加锁 | `KNOWN` |
| 但必须**检测**违约 | `Encoding` 状态里记创建线程的 `pthread_t`；每条编码命令在 debug 版断言一致，release 版计数并记 degradation。理由：违约在 release 版的表现是上游数据结构损坏，排障成本极高，而一次 `pthread_self()` 比较的开销可以忽略 | `INFERRED` |
| 未 `endEncoding` 就释放 encoder | drop handle。上游的 `Drop` 会做它该做的清理；**但这个命令缓冲里该编码器的命令不会出现**。必须记一条 degradation 并在 `CommandBuffer::ended_encoders` 的对照中体现（该编码器不在列表里） | `INFERRED` |
| 同一命令缓冲上开第二个编码器而第一个未结束 | 上游直接拒绝：`Error::Invalid` 带 `Problem`，`problem.rs` 的第一个 variant 就是「本命令缓冲已有编码器打开」（`KNOWN`：`error.rs:498` 的 `pub enum Problem` 第一项的 rustdoc 点明 Metal 也 assert）。按 `22` R13 的 `abort` 档处理，与 Metal 一致 | `KNOWN` |

### 3.5 parallel render encoder：② 层错配的无解情形

`MTLCommandBuffer` 的 `parallelRenderCommandEncoderWithDescriptor:` 要求：一个 pass、N 个子编码器、子编码器可以**并发**编码、命令按子编码器的创建顺序出现在 pass 里。

上游**没有任何** `ParallelRenderCommandEncoder` 类型（`KNOWN`：对 `upstream/m2v/crates/**/*.rs` 全文检索 `ParallelRender`，零命中）。`40` 第 4 节也没登记它。

因此这条路上 ② 层错配是**结构性**的，不是接口差异：

| 要素 | Metal 要求 | 上游能提供的 | 差距 |
|---|---|---|---|
| 一个 pass | `renderCommandEncoderWithDescriptor:` 开一个 | `CommandBuffer::render_command_encoder(&descriptor)` 开一个 | 一致 |
| N 个子编码器 | 各自独立编码 | 一个 `RenderCommandEncoder`，`&mut self` | **没有第二个可写入口** |
| 并发编码 | 允许多线程 | 编码器不 `Sync` | **不允许** |
| 创建顺序定序 | 按创建顺序 | 无排序入口 | **无** |

唯一的填法是在 ObjC 侧建一层「录制 + 按创建顺序重放」：每个子编码器把调用录进自己的缓冲，`endEncoding` 后按创建序重放到唯一的上游 `RenderCommandEncoder`。**这条路违反 `40` §1 的第一条规则**（adapter 不得复制上游的 Encoder、不得自行推导绑定），因为「录制每条编码命令并重放」本质上就是重建一个编码器状态机。

处置：登记为 `N-01`，**第一版返回 nil**（照 APV 对 heap 与 ICB 的做法，`21` §2 结论：`return nil` 比 `doesNotRecognizeSelector:` 安全），并把「客户端是否真的取这个编码器」作为 `M-001` 优先查清。`INFERRED`

### 3.6 其他消费点（不止编码器）

`KNOWN`。上游还有三处 `self` 消费或等价的一次性语义，adapter 都要对应到 ObjC 的「调用后对象还在」：

| 上游 | 一次性在哪 | ObjC 侧处置 |
|---|---|---|
| `HostMemory::with_dirty_pages(self, ..)` / `with_import_gate(self, ..)` / `with_runs(self, ..)` / `assume_writable(self)` | 消费并返回新的 `HostMemory`（builder 链） | 在 `newBufferWithBytesNoCopy:` 的实现里一次性建完整条链再调用，不把中间值存起来 |
| `Device::warm(&self, records: Vec<PipelineRecord>, byte_budget: u64)` | 消费 `Vec` | 启动自检里调一次（`40` §6.6），不保留 records |
| `SharedEventListener::new()` 产生的 listener + `notify_listener(.., block: SharedEventNotification)` | block 一次性 | `MTLSharedEventListener` 的 ObjC 对象持有 listener；每次 `notifyListener:atValue:block:` 新建一个 `SharedEventNotification` |

还有一处**反向**的：`Buffer::detach_backing(&self) -> Result<bool, Error>` 与 `Heap::detach_backing` 取 `&self` 而不消费（`KNOWN`），所以 ObjC 的 `detachBacking`（`40` §4 第 2 项）可以反复调；返回的 `bool` 是「这次真的分离了吗」，必须原样答给客户端，不要吞掉。

---

## 4. 错误与 refusal 的穿透

上游承诺 typed refusal：跑不了的输入以一个点名 Metal 特性的错误失败，绝不返回算错的模块。本节把这个承诺穿透到 `NSError`。

### 4.1 `Error` 的 27 个 variant → 我们的处置

`KNOWN`（`crates/metal2vulkan-runtime/src/error.rs:64`，`pub enum Error`，逐条抄录 variant 名与载荷类型，顺序即源码顺序）。「处置」列 `INFERRED`。

| # | variant | 载荷 | ObjC 侧处置 | NSError |
|---:|---|---|---|---|
| 1 | `Invalid` | `Invalid { call: &'static str, problem: Problem }` | 按 Metal 对该误用的行为：assert / abort / 返回 nil。**`call` 与 `problem` 必须进日志** | 多数不构造（进程已结束或无 error 出参） |
| 2 | `Unsupported` | `metal2vulkan::error::Unsupported { feature: Feature, needs: Needs }` | 能力查询同步返回 false；调用返回 nil + `NSError` | domain `<Proj>MetalUnsupportedErrorDomain`，`userInfo` 带 `feature` 与 `needs` 的稳定 wire 值 |
| 3 | `Bind` | `BindError` | 设备限额上的拒绝（`40` §7.3：9 个 variant，basis 全是 device） | `MTLBinaryArchiveDomain` 不适用；用 `MTLCommandBufferErrorDomain` 的 `Internal` 或自有 domain，见第 4.4 节 |
| 4 | `Compile` | `CompileError` | 编译 `NSError` | `MTLLibraryErrorDomain`，code 按 §4.2.2 |
| 5 | `NotImplemented` | `RuntimeGap` | **返回确定错误，不得伪造成功**（`40` §2.9） | 自有 domain + `RuntimeGap` 的 variant 名进 `userInfo` |
| 6 | `PlacementConflict` | `PlacementConflict` | `22` §5.2 的 A 档：地址 pin 冲突 | 自有 domain |
| 7 | `OutOfMemory` | `MemoryKind` | 返回 nil + `NSError`；`MemoryKind` 说明是哪种内存 | `MTLCommandBufferErrorDomain` code 8（`MTLCommandBufferErrorOutOfMemory`）或创建期的自有 domain |
| 8 | `DeviceLost` | — | 命令缓冲进 `DeviceLost`；设备级事件，必须上报 helper 监督者 | `MTLCommandBufferErrorDomain` code 4 |
| 9 | `Vulkan` | `VkResultCode` | 内部错误。**`VkResultCode` 必须进日志，不进 `NSError` 的 description**（客户端不该看到 Vulkan 的码） | `MTLCommandBufferErrorDomain` code 1（`Internal`） |
| 10 | `NoDevice` | — | **启动期致命**（`40` §6.3：这正是需要的失败而非回退） | 不构造；helper 退出 |
| 11 | `AppleOnly` | `AppleOnly`（5 个 variant，见下） | 返回确定错误 | 自有 domain + variant 名 |
| 12 | `ShaderCache` | `ShaderCacheError` | **启动期致命**（`40` §2.9） | 不构造 |
| 13 | `BinaryArchive` | `BinaryArchiveError` | 归档操作失败 | `MTLBinaryArchiveDomain` |
| 14 | `BinaryArchiveMiss` | `BinaryArchiveMiss` | 归档未命中。Metal 的 `MTLBinaryArchiveErrorInvalidFile` 等 | `MTLBinaryArchiveDomain` |
| 15 | `RateMap` | `UnpinnedCompile` | rate map 编译层不编译（`40` §7.3：5 个 variant） | 自有 domain |
| 16 | `WaitWouldDeadlock` | `DeadlockCause` | **返回超时错误，不得挂住 WindowServer**（`40` §5） | `MTLCommandBufferErrorDomain` code 2（`Timeout`） |
| 17 | `InstanceApiVersion` | `InstanceApiVersion` | 启动期致命（`DeviceOptions::instance_api_version` 越界，`40` §6.1：**不夹紧，直接拒绝**） | 不构造 |
| 18 | `SamplerLimit` | `SamplerLimit` | `newSamplerStateWithDescriptor:` 返回 nil | 无 error 出参 → 返回 nil，记日志 |
| 19 | `DynamicLibrary` | `DynamicLibraryError` | `MTLDynamicLibrary` 的链接使用被拒（`40` §2.4） | `MTLDynamicLibraryDomain` |
| 20 | `LoaderNotFound` | `LoaderNotFound { tried: ... }` | **启动期致命**，`tried` 的全部路径进日志（`40` §6.4 与 §9.3 第 14 项） | 不构造 |
| 21 | `DriverSetting` | `DriverSetting` | **启动期致命**，不降级继续（`40` §6.5） | 不构造 |
| 22 | `Nil` | `Nil { call, problem }` | **返回 nil，不填 error**（纯 Metal 也返回 nil 且进程继续） | 不构造 |
| 23 | `MetalError` | `MetalError { call, problem, domain: &'static str, code: i64, localized_description: Box<str> }` | **直通**，见第 4.2 节 | 用上游给的 domain / code / description 原样构造 |
| 24 | `Unproven` | `Unproven { call, problem }` | **停止 guest 并命名问题**，不得猜（`40` §2.9 / §9.4 第 21 项） | 不构造；helper 上报并停 |
| 25 | `ExtensionFeature` | `ExtensionFeature` | 启动期：缺扩展的 feature | 不构造（启动期） |
| 26 | `InstanceExtensionRequired` | `InstanceExtensionRequired` | 启动期致命 | 不构造 |
| 27 | `Degraded` | `Box<DegradeNotice>` | **注意：降级在这里也可以是错误。** 只有 `DeviceOptions::lowering_refuses` 非空时才出现，而 `40` §6.6 要求它**为空**，所以本项目**不应看到这个 variant**；看到就是配置漂了 → 当内部错误并报警 | `MTLCommandBufferErrorDomain` code 1 + 报警 |

**五个 variant 的载荷结构必须记住**（`KNOWN`：`error.rs:369`、`387`、`419`、`442`）：

```
Invalid     { call: &'static str, problem: Problem }
Nil         { call: &'static str, problem: Problem }
Unproven    { call: &'static str, problem: Problem }
MetalError  { call: &'static str, problem: Problem,
              domain: &'static str, code: i64, localized_description: Box<str> }
```

四者共享 `call` 与 `problem` 两个字段。**`call` 是上游方法名字符串**，`problem` 是 `Problem` 枚举（`error.rs:498`）。这两个字段是我们日志里定位 refusal 的唯一稳定键，必须全链路带着走到 `50-IPC-HELPER.md` 的 wire error 里。

### 4.2 `MetalError` → `NSError` 的直通

这是本节最重要的一条，因为它决定了「我们的错误看起来像不像 Metal 的」。

`KNOWN`：`MetalError` 已经携带 Metal 自己的 `domain`（`&'static str`）、`code`（`i64`）与 `localized_description`。上游在这些点上已经做过 Metal 实测（`40` §7.3 的 basis 分布：`metal-measured` 20 + `metal-documented` 3）。

> **R42-01**（`INFERRED`）：`Error::MetalError` 必须**原样**构造 `NSError`：
> ```
> NSError(domain: @(e.domain), code: (NSInteger)e.code,
>         userInfo: @{ NSLocalizedDescriptionKey: @(e.localized_description) })
> ```
> **不得**改 domain、不得重编 code、不得改写 description 文本。理由：客户端（WindowServer / CoreAnimation）对 `MTLLibraryErrorDomain` 的某几个 code 有分支行为；换成我们自己的 domain 会让那些分支全部走到默认分支。

> **R42-02**（`INFERRED`）：`userInfo` 可以**增加**本项目的键（`<Proj>UpstreamCall` = `e.call`、`<Proj>UpstreamProblem` = `problem` 的 variant 名、`<Proj>DegradeCodes` = 本次调用触发的 degradation code 列表），不得**删除或改写** Metal 自己的键。增加的键必须用本项目前缀，避免与未来的 Apple 键撞名。

> **R42-03**（`INFERRED`）：不是 `MetalError` 的 variant **不得**借用 Metal 的 domain。`Unsupported` / `NotImplemented` / `AppleOnly` / `Bind` / `RateMap` / `PlacementConflict` 一律用本项目自有 domain。理由：这些失败纯 Metal 不会产生；挂在 Metal 的 domain 上会让客户端按 Metal 的语义解释一个 Metal 永远不会给的 code，比给一个陌生 domain 更危险。

#### 4.2.1 本项目的 domain 清单

`INFERRED`。`<Proj>` 是本项目的 bundle 前缀（由 `70-BUILD-PACKAGE.md` 定）。

| domain | 承载 | code 空间 |
|---|---|---|
| `<Proj>MetalUnsupportedErrorDomain` | `Error::Unsupported` | code = `Feature` 的稳定序号；`userInfo[feature]` / `userInfo[needs]` 给结构化值 |
| `<Proj>MetalRuntimeGapErrorDomain` | `Error::NotImplemented(RuntimeGap)` | code = `RuntimeGap` 的 variant 序号 |
| `<Proj>MetalAppleOnlyErrorDomain` | `Error::AppleOnly` | code = `AppleOnly` 的 variant 序号（当前 5 个） |
| `<Proj>MetalInternalErrorDomain` | `Vulkan` / `Bind` / `PlacementConflict` / `RateMap` / `SamplerLimit` / `Degraded` | code = 内部分类 |
| `<Proj>MetalProjectGapErrorDomain` | 第 7 节的 `N-nn`（上游没有、我们也还没做的） | code = `N` 编号 |

**code 必须稳定**：序号一旦发布不得重排。实现方式是在本项目维护一张生成的映射表（输入是上游的 variant 名列表），不是手写数字。`50-IPC-HELPER.md` 的 wire error 用同一张表。

#### 4.2.2 `Needs` → `userInfo` 的结构化值

`KNOWN`（`crates/metal2vulkan/src/error/mod.rs:490`，`pub enum Needs` 的 8 个 variant）：

```
AnyOf(Vec<Vec<Capability>>)
DeviceCapability(&'static str)
NotImplemented
NotRepresentable
DriverDefect(DriverWorkaround)
RuntimeDriverDefect(RuntimeDriverDefect)
MetalGpuFamily(i64)
MetalRefuses(&'static [&'static str])
```

这 8 个 variant 直接回答 `40` §9.4 第 20 项要求的「capability 查询返回 false 时能给出缺什么」。逐条处置（`INFERRED`）：

| variant | `userInfo` 里怎么表示 | 对能力报告的意义 |
|---|---|---|
| `AnyOf(alternatives)` | `needs.anyOf` = 字符串数组的数组（每个内层数组是一组 capability 名） | **可修复**：启用任一组就能翻译。进 `60-CAPABILITY-MATRIX.md` 的「换 Mesa 配置可解」列 |
| `DeviceCapability(name)` | `needs.deviceCapability` = name | **设备缺**：Lavapipe 的问题，不是上游的 |
| `NotImplemented` | `needs.kind` = `"notImplemented"` | **上游缺**：任何设备上都拒绝（`40` §7.3 的 Where 列） |
| `NotRepresentable` | `needs.kind` = `"notRepresentable"` | **Vulkan 无此形式**：永久 |
| `DriverDefect(w)` / `RuntimeDriverDefect(d)` | `needs.driverDefect` = variant 名 | 升级 Mesa 可能解；必须与 `DeviceProperties::driver_defects` 对照（`40` §7.4） |
| `MetalGpuFamily(raw)` | `needs.metalGpuFamily` = raw | 需要某个 GPU family，而 APV 自己连 `Mac2` 都报 false（`91` §2.3）。进 `60` 的 `R-007` |
| `MetalRefuses(names)` | `needs.metalRefuses` = 字符串数组 | **纯 Metal 自己也拒绝**：这不是我们的缺口，是客户端的误用 |

`MetalRefuses` 这一条特别重要：它和 `40` §7.3 的 `metal-takes` basis 是**相反**的两件事。`MetalRefuses` 表示 Metal 也拒绝（我们拒绝是对的）；`metal-takes` 表示 Metal 接受而上游拒绝（我们比 Metal 严格，是上游记录的开放缺陷，共 28 条）。能力报告必须把两类分开统计。`KNOWN`

### 4.3 `void` selector 上的 `Err`：三档落点

第 2.4 节的反向陷阱的落地。ObjC 的 `void` selector 拿到 `Err` 时，错误只有三个去处：

| 档 | 条件 | 动作 | 例 |
|---|---|---|---|
| **① assert / abort** | `Error::Invalid` 且 `problem` 对应的 Metal 行为是结束进程 | `NSAssert` + abort。**只在上游明确说「Metal 的进程在此结束」时用** | 同一命令缓冲上开第二个编码器；`setProtectionOptions:` 的 1 / 3 / 7（`40` §3.2） |
| **② 让命令缓冲失败** | 编码期的其余 `Err` | `CommandBuffer::commit_failed(CommitFailure)`，调用本身 return | `set_depth_bias` 的 `Err`；`set_viewport` 的 `Err`；`Ended` 状态下的编码命令（第 3.3 节） |
| **③ 记日志后忽略** | `Err` 是降级或提示性的，且 Metal 在同样输入上什么也不做 | degradation 日志 + 继续 | `set_point_size`（上游：no-op，与 Metal 一致）；`set_depth_cleared` / `set_stencil_cleared`（上游：什么也不改，与 Metal 一致）；`invalidate_compressed_texture*`（no-op） |

> **R42-04**（`INFERRED`）：**第 ② 档是默认档。** 不确定某个 `Err` 属于哪档时走 ②，因为它既不崩进程也不产生错画面，而且客户端能通过 `commandBuffer.error` 观察到。走 ③ 等于静默损坏，走 ① 等于拿 WindowServer 的稳定性赌一个未实测的判断。

> **R42-05**（`INFERRED`）：② 档每次触发都必须记录 `Invalid::call` / `problem`，并累加一个计数器。`40` §7.2 已经要求 `draws_dropped_*` 非零报警，本条是同一性质的要求：**命令缓冲因 adapter 转发失败而失败的次数非零，必须报警**，因为它意味着本文的某一行映射写错了。

### 4.4 `RuntimeGap` / `AppleOnly` / `Unsupported` 的三者分工

`KNOWN`（三者的定义处：`error.rs:1267` 的 `pub enum RuntimeGap`；`apple_only.rs:70` 的 `pub enum AppleOnly`；`crates/metal2vulkan/src/error/mod.rs:330` 的 `pub struct Unsupported`）。

| 错误 | 含义 | 本项目能做什么 |
|---|---|---|
| `Unsupported { feature, needs }` | 设备缺少精确回答所需机制 | **按 `needs` 分流**（第 4.2.2 节）。`DeviceCapability` → 上报 Lavapipe；`NotImplemented` → 上报上游；`AnyOf` → 试着改 Mesa 配置 |
| `NotImplemented(RuntimeGap)` | 上游尚未构建的**纯 Metal** 功能 | 返回确定错误。**不得自己补**（`40` §1 规则 1）。可向上游提，或在第 7 节登记为本项目范围 |
| `AppleOnly(AppleOnly)` | Apple 私有调用无 Vulkan 形式，或其在 Apple GPU 上的语义未测 | 返回确定错误 |

`RuntimeGap` 的前 24 个 variant（`KNOWN`，源码顺序）：

```
Textures, ResourceHeap, SparseHeaps, SparseTileMaps,
HeapPastMaxBufferSize { size, max_buffer_size },
HeapTextureAlignment { alignment }, HeapTextureMemory,
FunctionTablePastMaxBufferLength { count, max_buffer_length },
IndirectCommandBufferPastMaxBufferLength { count, max_buffer_length },
IndirectRenderCommands, IndirectImageblockSize { width, height },
CommandReplay, RenderAttachments, AccelerationStructures,
FeatureEnable(VkFeature), ExtensionEnable(VkExtension), Render,
TexelsPastBufferLength, OverlappingSurfaceRows, MemorylessSurfacePlane,
IndirectCommandPastSize { index, size }, ExecutionRangePastBuffer { .. }, ...
```

对本项目特别相关的四个（`INFERRED` 的相关性判断）：

| variant | 为什么相关 |
|---|---|
| `HeapPastMaxBufferSize { size, max_buffer_size }` | `91` 实测 APV 的 `maxBufferLength` 正好 1 GiB（`10` 分册的硬下限）。heap 超过它就撞这条。heap 容量策略必须据此定 |
| `AccelerationStructures` | 整个 ray tracing 面的统一出口。第 7 节 `N-04` 的落点就是它 |
| `FeatureEnable(VkFeature)` / `ExtensionEnable(VkExtension)` | 「要启某个 Vulkan feature/扩展才行」。直接对应 `40` §6.2 的 `optional_device_extensions`，可以用它驱动启动自检的扩展清单 |
| `OverlappingSurfaceRows` / `MemorylessSurfacePlane` | IOSurface 相关（`41` 分册）。plane 的行距与 memoryless 的组合 |

`AppleOnly` 的 5 个 variant（`KNOWN`：`apple_only.rs:70`，全集）：

```
ProtectedContent, LineWidth, ViewportTransformDisabled,
VertexAmplificationMode, SurfaceClientDirection
```

对应的 SPI 行在第 5.4.9 节逐条给出。另有 `AppleOnlyCall`（`apple_only.rs:124`）枚举「哪个调用是 Apple-only」，第一个 variant 是 `InvalidateCompressedTexture`。

### 4.5 哪些 refusal 必须在 descriptor 校验期就拦

接 `22` §3.6 的 A/B/C/D 四档。原则（`INFERRED`）：**一个 refusal 如果能在 descriptor 校验期判出来，就必须在那里判**，理由有两条：① 那里有 `NSError **` 出参，错误有地方去；② 那里还没有占用上游资源，失败的代价最小。

| `22` 的档 | 哪些上游 refusal 归这里 | 判定位置 | 失败形态 |
|---|---|---|---|
| **A（硬错）** | `Invalid`（descriptor 字段非法）；`Unsupported(Format)`（`40` §8.2.14 的无候选格式）；`PlacementConflict`；`SamplerLimit`；`22` R25 的 `resourceIndex >= 16384` | ObjC shim 的逐字段 checked-convert（②）+ Rust 侧跨字段校验（③） | 按 R13 三档 |
| **B（能力错）** | `Unsupported`（`needs = DeviceCapability` / `NotRepresentable`）；`NotImplemented(RuntimeGap)` 中与 descriptor 字段一一对应的那些（`SparseHeaps`、`SparseTileMaps`、`AccelerationStructures`）；第 7 节的 `N-04` / `N-09` / `N-10` / `N-11` / `N-12` | Rust 侧跨字段校验（③） | nil + `NSError`（自有 domain）+ capability 查询同步 false |
| **C（纯提示）** | 不产生 refusal，只产生 degradation | — | 继续，记 code |
| **D（已是默认）** | 不产生 refusal | — | 继续；**按 R24 仍回答声明值** |

**必须在 descriptor 期拦的 10 条清单**（`INFERRED`，每条给出判定依据）：

| # | 条件 | 档 | 依据 |
|---|---|---|---|
| 1 | `pixelFormat` 在 `40` §8.2.14 的无候选集合里 | A | 格式无 Vulkan 表示，创建后的每次使用都会失败 |
| 2 | `pixelFormat` × 本次 `FormatUsage` 组合在设备 profile 上无候选 | A | 必须带 usage 判（`22` §5.2 的「最容易犯的错」） |
| 3 | `TextureDescriptor::rotation != 0` 而 `framebuffer_only == false` | A | `40` §3.2：Metal 自己 assert |
| 4 | `rotation > 4` | A | 同上 |
| 5 | `forceResourceIndex == YES` 且 `resourceIndex >= 16384` | A | `22` R25 |
| 6 | `placementSparsePageSize != 0`，或 heap 的 sparse 字段非 0 | B | Lavapipe 的 sparse 仅 Linux（`40` §2.2） |
| 7 | `MTLAccelerationStructure*` / `MTLBVH*` 的任何 descriptor | B | `N-04`；上游出口是 `RuntimeGap::AccelerationStructures` |
| 8 | `MTLTensorDescriptor` | B | `N-11` |
| 9 | `MTLCompileOptions` 走源码编译路径 | B | 边界 ①；`needs = "MSL front end"` |
| 10 | `MTLCounterSampleBufferDescriptor` / `MTLCounterHeapDescriptor` | B | `N-02`；且 `device.counterSets` 必须返回空数组，使 descriptor 永远无效 |

**反过来，不得在 descriptor 期拦的两类**（`INFERRED`）：

1. **`metal-takes` 的 28 条**（`40` §7.3）：纯 Metal 接受的输入。`22` §3.2 已明确不得比 Metal 更严格。在 descriptor 期拦会把一个上游的开放缺陷变成我们的硬拒绝。
2. **`Unproven`**：它不是「输入不合法」而是「我们证不出 Metal 的答案」。按 `40` §2.9 停 guest 并命名问题，不是返回 nil。在 descriptor 期把它变成 nil 会让客户端继续跑在一个我们答不出的假设上。

### 4.6 命令缓冲层的错误

`KNOWN`（`error.rs:1877` 的 `pub enum CommandBufferError`，19 个 variant）：

```
DeviceLost, OutOfMemory, Internal(VkResultCode), IndexPoolOverflow,
CubicArgumentSampler, MeshRecordsOverflow(..), TessellationRecordsOverflow(..),
MeshGridPastLimits, Refused, Injected(u64), RenderTargetSize, PageFault,
GpuHang, GpuRecoveryVictim, AccessRevoked, Execution(u64),
PipelineCreation(PipelineCreationCause), EncodedUseRebound, DetachedBacking
```

读法（`INFERRED`）：

| 组 | variant | 映射到 `MTLCommandBufferError` |
|---|---|---|
| 设备级 | `DeviceLost` / `AccessRevoked` | code 4（`DeviceRemoved`）/ 11（`AccessRevoked`） |
| GPU 行为级 | `GpuHang` / `GpuRecoveryVictim` / `PageFault` | code 2（`Timeout`）/ 2 / 3（`PageFault`） |
| 内存 | `OutOfMemory` | code 8 |
| 翻译/管线 | `PipelineCreation(cause)` / `MeshRecordsOverflow` / `TessellationRecordsOverflow` / `MeshGridPastLimits` / `IndexPoolOverflow` / `CubicArgumentSampler` / `RenderTargetSize` | code 1（`Internal`）+ `userInfo` 带 variant 名 |
| 我们注入的 | `Injected(code)` | **这是 `commit_failed` 的回路**：`CommitFailure::code` 原样出现在这里。第 3.3 节与 §4.3 ② 档的错误由此被客户端观察到 |
| 后备变更 | `EncodedUseRebound` / `DetachedBacking` | `40` §4 第 2 项（分散后备）的失败出口，归 `41` 分册 |
| 拒绝 | `Refused` | adapter 的 refusal 让提交失败 |

> **R42-06**（`INFERRED`）：`CommandBuffer::error()` 返回 `Option<CommandBufferError>`，另有 `error_description() -> Option<String>`、`refusal() -> Option<Error>`、`failed_pipeline() -> Option<FailedPipeline>`、`dropped_draw() -> Option<FailedPipeline>`（`KNOWN`，四个方法都在 `command_buffer/mod.rs`）。ObjC 的 `commandBuffer.error` 必须同时消费前三个：`error()` 给 code，`refusal()` 给 typed refusal（如果有），`error_description()` 只进日志，**不进 `NSError` 的 `NSLocalizedDescriptionKey`**（它是上游的内部描述，不是 Metal 的）。`dropped_draw()` 按 `40` §7.2 的要求排障时必须打印。

### 4.7 三条禁止（重申 + 一条新增）

| # | 禁止 | 来源 |
|---|---|---|
| 1 | 禁止读 `Error` 的消息文本做分支，只匹配 variant | `40` §2.9 / §9.1 第 7 项（上游明确要求） |
| 2 | 禁止解析 degradation 的通告文本；只用 `Degradation::code()`（稳定字符串 `metal2vulkan-degrade-<kind>`）与 `category()` | `40` §7.1 |
| 3 | 禁止把 `Err` 静默丢弃 | 第 4.3 节 R42-04 |
| 4 | **新增**：禁止把非 `MetalError` 的 variant 映射到 Metal 自己的 error domain | 本文 R42-03 |

---

## 5. 逐对象、逐 selector 的映射表

### 5.0 表的读法与族规则

**列**：

| 列 | 内容 |
|---|---|
| Metal selector | `21` / 附录 A 给的 selector 名 |
| enc | x86_64 type encoding。来源：`21` 第 8 节 / 附录 A（`KNOWN`）。标 `—` 表示本仓库尚未枚举（记 `M-006`） |
| 上游调用 | `crate::path::item` 全名。`metal2vulkan_runtime::` 省略成 `rt::` |
| 上游签名 | 精确签名。接收者 `&mut self` / `&self` / `self` 照实写。公共前缀省略 |
| 参 | 参数转换。族规则用 `R-x` 引用 |
| 返 | 返回转换 |
| 错 | 错误处置（第 4 节的档） |
| 标 | 第 1.3 节的落点分类 + 证据标签 |

**族规则**（`INFERRED`，每条的事实基础在第 2 节）：

| 规则 | 适用 | 参数转换 | 返回转换 | 错误处置 |
|---|---|---|---|---|
| **R-B** | 单项 buffer 绑定 | `id<MTLBuffer>` → `Option<&Buffer>`（K-05/K-06）；`offset` → `u64`；`atIndex:` → `u32`（K-15 checked） | `void` | `Err` → 第 4.3 节 ② 档 |
| **R-BA** | 多项 buffer 绑定 | 同 R-B + `withRange:` 按 K-07 拆成 slice + `first` | `void` | ② |
| **R-BY** | `set*Bytes:length:atIndex:` | `(ptr, len)` → `&[u8]`。**必须在调用前拷贝到本进程可控内存**：ObjC 侧的指针是客户端栈或堆，上游按 `&[u8]` 立即读完，所以单次调用内安全；跨调用不得保留该指针 | `void` | ② |
| **R-T** | texture 绑定 | `id<MTLTexture>` → `Option<&Texture>`；索引 `u32` | `void` | ② |
| **R-TA** | 多项 texture 绑定 | R-T + K-07 | `void` | ② |
| **R-S** | sampler 绑定（四形态） | 见第 2.7 节的四形态表。**render 与 compute 形态不同** | `void` | ② |
| **R-D** | draw | `MTLPrimitiveType` → `DrawPrimitiveType::from_raw`（K-11，值 9 必须保留为「让命令缓冲以 GPU 方式失败」）；计数与 base 按 K-15 收窄到 `u32` / `i32`；短形态按 K-03 补默认值 | `void` | ② |
| **R-U** | `useResource` / `useHeap` | 资源 → `ResourceRef<'_>`（K-06），heap → `&Heap`；无 stages 形态补全 stages（K-03） | `void` | ② |
| **R-F** | fence | `id<MTLFence>` → `&Fence`；stages → `RenderStages` | `void` | ② |
| **R-G** | 纯 getter（`L`） | 无 | snapshot 或常量 | 无 |
| **R-N** | 无落点，返回 nil | 无 | `nil` | 返回 nil；有 `error:` 出参时填自有 domain（第 4.2.1 节） |
| **R-Z** | 无落点，返回零值 | 无 | `0` / `NO` / 空数组 | 记 degradation |

---

### 5.1 `MTLCommandEncoder`（8 required）

签名源：三个编码器各自的 `end_encoding`（第 3.1 节）。

| Metal selector | enc | 上游调用 | 上游签名 | 参 | 返 | 错 | 标 |
|---|---|---|---|---|---|---|---|
| `endEncoding` | `v16@0:8` | `rt::RenderCommandEncoder::end_encoding` / `ComputeCommandEncoder::end_encoding` / `BlitCommandEncoder::end_encoding` / `ResourceStateCommandEncoder::end_encoding` | `end_encoding(self) -> Result<(), Error>` | `inner.take()` → 按值传（第 3.2 节） | `void`；`Ok` → `Ended`，`Err(e)` → `EndedFailed(e)` | `Err` → 第 4.3 节 ② 档（`commit_failed`），**不传给客户端**（selector 是 `void`） | `U` `KNOWN` |
| `device` | `@16@0:8` | `rt::RenderCommandEncoder` 无 `device()`；经宿主对象持有的 `CommandBuffer::device` | `device(&self) -> &Device` | 无 | ObjC device 对象 | 无 | `U` `KNOWN` |
| `label` | `@16@0:8` | — | — | 无 | 本地 `NSString`（R-G） | 无 | `L` `INFERRED` |
| `setLabel:` | `v24@0:8@16` | — | — | 原子 copy（`21` §9.6：`objc_setProperty_atomic_copy`） | `void` | 无 | `L` `KNOWN` |
| `pushDebugGroup:` | `v24@0:8@16` | — | — | 本地栈 | `void` | 无 | `L` / `N-06` `INFERRED` |
| `popDebugGroup` | `v16@0:8` | — | — | 本地栈 | `void` | 栈空时按 Metal 忽略 | `L` / `N-06` `INFERRED` |
| `insertDebugSignpost:` | `v24@0:8@16` | — | — | 本地日志 | `void` | 无 | `L` / `N-06` `INFERRED` |
| `barrierAfterQueueStages:beforeStages:` | `v32@0:8Q16Q24` | **无** | — | — | `void` | 记 degradation，继续 | **`N-06`** `KNOWN` |

> `barrierAfterQueueStages:beforeStages:` 是队列级屏障，上游全无对应（第 1.2 节抽取的 857 条里零命中 `barrier_after`）。`40` 第 4 节未登记。第 7 节 `N-06`。

### 5.2 `MTLCommandQueue`

#### 5.2.1 公开层（11 required）

签名源：`crates/metal2vulkan-runtime/src/queue.rs:72`（`CommandQueue`，5 个公开方法）。

| Metal selector | enc | 上游调用 | 上游签名 | 参 | 返 | 错 | 标 |
|---|---|---|---|---|---|---|---|
| `commandBuffer` | `@16@0:8` | `rt::CommandQueue::command_buffer` | `command_buffer(&self) -> Result<CommandBuffer, Error>` | 无 | 新建 ObjC command buffer（autoreleased，K-12） | `Err` → 返回 nil，记日志 | `U` `KNOWN` |
| `commandBufferWithUnretainedReferences` | `@16@0:8` | 同上 | 同上 | 无 | 同上，ObjC 侧标记 `retainedReferences = NO` | 同上 | `C` `INFERRED` |
| `commandBufferWithDescriptor:` | `@24@0:8@16` | 同上 | 同上 | descriptor snapshot（`22`）；`retainedReferences` / `errorOptions` 留在 ObjC 侧 | 同上 | 同上 | `C` `INFERRED` |
| `label` | `@16@0:8` | `rt::CommandQueue::label` | `label(&self) -> Option<String>` | 无 | `NSString` 或 nil | 无 | `U` `KNOWN` |
| `setLabel:` | `v24@0:8@16` | `rt::CommandQueue::set_label` | `set_label(&self, label: &str)` | `NSString` → UTF-8 `&str`，非 UTF-8 按替换字符处理 | `void` | 无 | `U` `KNOWN` |
| `device` | `@16@0:8` | `rt::CommandQueue::device` | `device(&self) -> &Device` | 无 | ObjC device | 无 | `U` `KNOWN` |
| `insertDebugCaptureBoundary` | `v16@0:8` | — | — | — | `void` | 无 | `L` `INFERRED` |
| `addResidencySet:` | `v24@0:8@16` | — | — | 本地集合 | `void` | 无 | `L` `INFERRED`（`22` §5.3：residency set 本地簿记 + `use_resource` 等价调用 + `Performance` degradation） |
| `addResidencySets:count:` | `v32@0:8r^@16Q24` | — | — | 同上 | `void` | 无 | `L` `INFERRED` |
| `removeResidencySet:` | `v24@0:8@16` | — | — | 同上 | `void` | 无 | `L` `INFERRED` |
| `removeResidencySets:count:` | `v32@0:8r^@16Q24` | — | — | 同上 | `void` | 无 | `L` `INFERRED` |

**`CommandQueue` 的两个 runtime 扩展**，Metal 侧无 selector，但本项目会用（`KNOWN`）：

| 上游 | 签名 | 用途 |
|---|---|---|
| `rt::CommandQueue::with_vk_queue` | `unsafe with_vk_queue<R>(&self, f: impl FnOnce(vk::Queue, u32) -> R) -> R` | 直接触碰底层 `VkQueue`（`40` §4.1 的最后一行）。IOSurface 桥与 display provider 可能需要 |
| `rt::Device::new_command_queue_for_presenting` | `new_command_queue_for_presenting(&self) -> Result<CommandQueue, Error>` | 上游为 present 路径准备的队列。**本项目不走 Vulkan presentation（`40` §4 第 4 项），所以不用**，但启动自检应记录它存在以免将来误判 |

#### 5.2.2 `MTLCommandQueueSPI`（25 required + 22 optional = 47）

`B`：逐条 selector 未枚举（`M-004`）。按语义给三组与规则。`INFERRED`（分组）；`KNOWN`（上游 `CommandQueue` 只有 5 个公开方法，所以 47 条里 `U` = 0）。

| 组 | 判定（按 selector 名） | 规则 | 标 |
|---|---|---|---|
| 队列属性与簿记 | `label*`、`device`、`*Count`、`*Index`、`is*`、`supports*` | `L`：本地答，取值由 `20-OBJC-DEVICE.md` 定 | `L` |
| 提交与调度控制 | `commit*`、`enqueue*`、`notify*`、`*Priority`、`*Barrier` | 上游无队列级控制面。能等价成命令缓冲级操作的用 `CommandBuffer` 的方法组合；不能的 `R-Z` + degradation | `C` / `N-10` |
| 诊断与捕获 | `*Capture*`、`*Diagnostic*`、`*Statistics*` | `R-Z` | `L` |

> 本组唯一必须现在定下的事：**`MTLCommandQueueSPI` 里不存在任何本项目必须转发给上游的调用。** 上游 `CommandQueue` 的全部公开面是 5 个方法，已在第 5.2.1 节用完。所以 47 条全部是 `L` / `C` / `N`，没有被漏掉的承重落点。`KNOWN`

### 5.3 `MTLCommandBuffer`

#### 5.3.1 公开层（39 required）

签名源：`crates/metal2vulkan-runtime/src/command_buffer/mod.rs:155`（`CommandBuffer`，40 个公开方法）。

| Metal selector | enc | 上游调用 | 上游签名 | 参 | 返 | 错 | 标 |
|---|---|---|---|---|---|---|---|
| `commit` | `v16@0:8` | `rt::CommandBuffer::commit` | `commit(&self) -> Result<(), Error>` | 无 | `void` | `Err` → 命令缓冲进 `Error` 状态；**不 abort** | `U` `KNOWN` |
| `status` | `Q16@0:8` | `rt::CommandBuffer::status` | `status(&self) -> CommandBufferStatus` | 无 | `MTLCommandBufferStatus`（直接映射，`40` §2.2） | 无 | `U` `KNOWN` |
| `error` | `@16@0:8` | `rt::CommandBuffer::error` + `refusal` + `error_description` | `error(&self) -> Option<CommandBufferError>`；`refusal(&self) -> Option<Error>`；`error_description(&self) -> Option<String>` | 无 | 按 R42-06 构造 `NSError` | — | `U` `KNOWN` |
| `enqueue` | `v16@0:8` | — | — | 本地排队标记 | `void` | 无 | `L` `INFERRED`（上游无 `enqueue`；提交顺序由本项目的 wire 层保证，`50` 分册） |
| `waitUntilCompleted` | `v16@0:8` | `rt::CommandBuffer::wait_until_completed` / `wait_until_completed_for` | `wait_until_completed(&self) -> Result<(), Error>`；`wait_until_completed_for(&self, timeout: Duration) -> Result<(), TimedOut>` | **必须用带超时的形态**，超时取 `40` §6.6 的预算 | `void` | `WaitWouldDeadlock` → 立即返回，**不得挂住 WindowServer**（`40` §5） | `U` `KNOWN` |
| `waitUntilScheduled` | `v16@0:8` | `rt::CommandBuffer::wait_until_scheduled` | `wait_until_scheduled(&self) -> Result<(), Error>` | 无 | `void` | 同上 | `U` `KNOWN` |
| `addCompletedHandler:` | `v24@0:8@?16` | `rt::CommandBuffer::add_completed_handler` | `add_completed_handler(&self, handler: Handler) -> Result<(), Error>` | K-09 | `void` | `Err` → 立即在当前线程调一次 block（命令缓冲已终态） | `U` `KNOWN` |
| `addScheduledHandler:` | `v24@0:8@?16` | `rt::CommandBuffer::add_scheduled_handler` | `add_scheduled_handler(&self, handler: Handler) -> Result<(), Error>` | K-09 | `void` | 同上 | `U` `KNOWN` |
| `encodeSignalEvent:value:` | `v32@0:8@16Q24` | `rt::CommandBuffer::encode_signal_event` | `encode_signal_event(&self, event: EventRef<'_>, value: u64) -> Result<(), Error>` | `id<MTLEvent>` → `EventRef<'_>`（`Event` 与 `SharedEvent` 的统一引用） | `void` | ② | `U` `KNOWN` |
| `encodeWaitForEvent:value:` | `v32@0:8@16Q24` | `rt::CommandBuffer::encode_wait_for_event` | `encode_wait_for_event(&self, event: EventRef<'_>, value: u64) -> Result<(), Error>` | 同上 | `void` | ② | `U` `KNOWN` |
| `commandQueue` | `@16@0:8` | `rt::CommandBuffer::command_queue` | `command_queue(&self) -> &CommandQueue` | 无 | ObjC queue | 无 | `U` `KNOWN` |
| `device` | `@16@0:8` | `rt::CommandBuffer::device` | `device(&self) -> &Device` | 无 | ObjC device | 无 | `U` `KNOWN` |
| `GPUStartTime` | `d16@0:8` | `rt::CommandBuffer::gpu_start_time` | `gpu_start_time(&self) -> Result<f64, Error>` | 无 | `double` | `Err` → 0.0（Metal 在未完成时也答 0） | `U` `KNOWN` |
| `GPUEndTime` | `d16@0:8` | `rt::CommandBuffer::gpu_end_time` | `gpu_end_time(&self) -> Result<f64, Error>` | 无 | `double` | 同上 | `U` `KNOWN` |
| `kernelStartTime` | `d16@0:8` | `rt::CommandBuffer::kernel_start_time` | `kernel_start_time(&self) -> f64` | 无 | `double` | 无 | `U` `KNOWN` |
| `kernelEndTime` | `d16@0:8` | `rt::CommandBuffer::kernel_end_time` | `kernel_end_time(&self) -> f64` | 无 | `double` | 无 | `U` `KNOWN` |
| `blitCommandEncoder` | `@16@0:8` | `rt::CommandBuffer::blit_command_encoder` | `blit_command_encoder(&self) -> Result<BlitCommandEncoder, Error>` | 无 | 新建 ObjC blit encoder，`inner = Some(..)` | `Err`（如已有编码器打开）→ 第 4.3 节 ① 档 | `U` `KNOWN` |
| `computeCommandEncoder` | `@16@0:8` | `rt::CommandBuffer::compute_command_encoder` | `compute_command_encoder(&self) -> Result<ComputeCommandEncoder, Error>` | 无 | 同上 | 同上 | `U` `KNOWN` |
| `computeCommandEncoderWithDispatchType:` | `@24@0:8Q16` | `rt::CommandBuffer::compute_command_encoder_with_dispatch_type` / `..._with_raw_dispatch_type` | `with_dispatch_type(&self, dispatch_type: DispatchType) -> Result<ComputeCommandEncoder, Error>`；`with_raw_dispatch_type(&self, raw: u64) -> Result<..., Error>` | 已知值走 typed，未知值走 raw（K-11：除 1 外每个值都按 serial） | 同上 | 同上 | `U` `KNOWN` |
| `renderCommandEncoderWithDescriptor:` | `@24@0:8@16` | `rt::CommandBuffer::render_command_encoder` | `render_command_encoder(&self, descriptor: &RenderPassDescriptor) -> Result<RenderCommandEncoder, Error>` | `MTLRenderPassDescriptor` snapshot → `rt::RenderPassDescriptor`（`22` §5.1 逐字段） | 同上 | 同上；`RenderPassProblem` → ① 或 nil 按 `22` R13 | `U` `KNOWN` `*(partial)*` |
| `resourceStateCommandEncoder` | `@16@0:8` | `rt::CommandBuffer::resource_state_command_encoder` | `resource_state_command_encoder(&self) -> Result<ResourceStateCommandEncoder, Error>` | 无 | 同上 | **macOS 上 sparse 不可用（`40` §2.2）→ 预期 `Err`，返回 nil** | `U` `KNOWN` |
| `blitCommandEncoderWithDescriptor:` | `@24@0:8@16` | `rt::CommandBuffer::blit_command_encoder` | 同上 | descriptor 的 sample buffer attachment 部分无落点（`N-02`），其余字段忽略 | 同上 | descriptor 要求 counter 采样时 → `N-02` 的 B 档 | `C` `INFERRED` |
| `computeCommandEncoderWithDescriptor:` | `@24@0:8@16` | `rt::CommandBuffer::compute_command_encoder_with_dispatch_type` | 同上 | descriptor 的 `dispatchType` 取出来；sample buffer attachment → `N-02` | 同上 | 同上 | `C` `INFERRED` |
| `resourceStateCommandEncoderWithDescriptor:` | `@24@0:8@16` | `rt::CommandBuffer::resource_state_command_encoder` | 同上 | 同上 | 同上 | 同上 | `C` `INFERRED` |
| `parallelRenderCommandEncoderWithDescriptor:` | `@24@0:8@16` | **无上游类型** | — | — | **nil** | 第一版返回 nil（第 3.5 节） | **`N-01`** `KNOWN` |
| `accelerationStructureCommandEncoder` | `@16@0:8` | **无** | — | — | nil | `RuntimeGap::AccelerationStructures` | **`N-04`** `KNOWN` |
| `accelerationStructureCommandEncoderWithDescriptor:` | `@24@0:8@16` | **无** | — | — | nil | 同上 | **`N-04`** `KNOWN` |
| `presentDrawable:` | `v24@0:8@16` | **无**（上游范围外） | — | — | `void` | 走 IOSurface + display provider（`11` 分册） | `S4-4` `KNOWN` |
| `presentDrawable:atTime:` | `v32@0:8@16d24` | 同上 | — | — | `void` | 同上 | `S4-4` `KNOWN` |
| `presentDrawable:afterMinimumDuration:` | `v32@0:8@16d24` | 同上 | — | — | `void` | 同上 | `S4-4` `KNOWN` |
| `label` | `@16@0:8` | **无**（上游 `CommandBuffer` 没有 label 方法） | — | 无 | 本地 `NSString`（R-G） | 无 | `L` `KNOWN`（`22` §5.2 已记此 gap，本文确认：40 个公开方法里零命中 `label`） |
| `setLabel:` | `v24@0:8@16` | **无** | — | 本地存 | `void` | 无 | `L` `KNOWN` |
| `pushDebugGroup:` | `v24@0:8@16` | **无** | — | 本地栈 | `void` | 无 | `L` `INFERRED` |
| `popDebugGroup` | `v16@0:8` | **无** | — | 本地栈 | `void` | 无 | `L` `INFERRED` |
| `errorOptions` | `Q16@0:8` | 部分：`execution_report` / `executions` | `execution_report(&self) -> Option<StatusReport>`；`executions(&self) -> Vec<Execution>` | 无 | 返回客户端创建时给的 options（R24） | 无 | `L` `INFERRED`（`22` §5.3 的 C 档） |
| `logs` | `@16@0:8` | **无**（`MessageSink` 是驱动通告，不是 shader log） | — | 无 | 空 `MTLLogContainer` | 记 degradation | `L` `INFERRED` |
| `retainedReferences` | `c16@0:8` | **无**（ObjC 侧的 retain 策略） | — | 无 | 创建时的声明值（R24） | 无 | `L` `KNOWN`（`22` §3.6 C 档） |
| `useResidencySet:` | `v24@0:8@16` | 等价：`use_resource` / `use_heap` | — | 展开成资源集合上的 `use_*` | `void` | 无 | `L` `INFERRED` |
| `useResidencySets:count:` | `v32@0:8r^@16Q24` | 同上 | — | 同上 | `void` | 无 | `L` `INFERRED` |

**`CommandBuffer` 的 10 个 runtime 扩展**（Metal 无 selector，本项目**应当**使用。`40` §4.1 已列，本文补精确签名，`KNOWN`）：

| 上游 | 签名 | 本项目用在哪 |
|---|---|---|
| `commit_failed` | `commit_failed(&self, failure: CommitFailure) -> Result<(), Error>` | 第 3.3 节与 §4.3 ② 档的唯一出口 |
| `set_submission_check` | `set_submission_check(&self, check: SubmissionCheck) -> Result<(), Error>` | guest 命令流校验点 |
| `add_submission_handler` | `add_submission_handler(&self, handler: Handler) -> Result<(), Error>` | 批次到达 `VkQueue` 的回调（跑在设备 scheduler 线程，K-09） |
| `add_executed_commands_handler` | `add_executed_commands_handler(&self, handler: ExecutedCommandsHandler) -> Result<(), Error>` | 间接记录被读时的回调 |
| `used_resources` | `used_resources(&self) -> UsedResources` | `detachBacking` 的等待依据（`40` §4 第 2 项） |
| `ended_encoders` | `ended_encoders(&self) -> Vec<EndedEncoder>` | 配 `FailedEncoders::Set`；也用于第 3.4 节的「未 endEncoding 就释放」核对 |
| `uses` / `encoders_use` | `uses(&self, objects: &[ObjectId]) -> bool`；`encoders_use(&self, encoders: Range<usize>, objects: &[ObjectId]) -> bool` | 资源是否被这个命令缓冲用到 |
| `dropped_draw` | `dropped_draw(&self) -> Option<FailedPipeline>` | `40` §7.2 的静默损坏信号，排障必打印 |
| `failed_pipeline` | `failed_pipeline(&self) -> Option<FailedPipeline>` | 管线创建失败定位 |
| `encode_wait_for_vk_semaphore` / `encode_signal_vk_semaphore` | `unsafe encode_wait_for_vk_semaphore(&self, semaphore: vk::Semaphore) -> Result<(), Error>`（另一个同形） | 与 display provider / IOSurface 桥的 Vulkan 侧同步 |

#### 5.3.2 `MTLCommandBufferSPI`（21 required + 36 optional = 57）

`B`：逐条未枚举（`M-004`）。但其中**有 5 条承重 SPI 上游明确做了**，必须逐条给（`KNOWN`，取自上游 `docs/RUNTIME-PORTING.md` 的 `CommandBuffer` 节与源码）：

| Metal selector（SPI） | 上游调用 | 上游签名 | 语义要点 | 标 |
|---|---|---|---|---|
| `setProtectionOptions:` | `rt::CommandBuffer::set_protection_options` | `set_protection_options(&self, options: u64) -> Result<(), Error>` | 非 0 options 下建的编码器**让命令缓冲从该编码器起失败**（`CommandBufferError::ProtectedEncoder`，按 Metal GPU 行为）；**1 / 3 / 7 被拒绝**（在 Metal 上会结束进程）；未实测的变化 → `AppleOnly::ProtectedContent` | `U` `KNOWN` `*(partial)*` |
| `encodeSignalEventScheduled:value:` | `rt::CommandBuffer::encode_signal_event_scheduled` | `encode_signal_event_scheduled(&self, event: &SharedEvent, value: u64) -> Result<(), Error>` | 注意参数是 `&SharedEvent` 不是 `EventRef`：**只接受 shared event** | `U` `KNOWN` |
| `GPUStartTime` / `GPUEndTime` 的 SPI 变体 | 同第 5.3.1 节 | — | `40` §6.6 的 `gpu_times_from_host = true` 使它们由主机时钟推出 | `U` `KNOWN` |
| `errorOptions` 相关的执行报告 | `rt::CommandBuffer::execution_report` | `execution_report(&self) -> Option<StatusReport>` | **只能在命令缓冲完成后读**；是运行事实不是错误（`40` §7.4） | `U` `KNOWN` |
| `executions`（需 `record_executions`） | `rt::CommandBuffer::executions` | `executions(&self) -> Vec<Execution>` | 每个 draw / dispatch 跑了哪个管线。`40` §6.6：发布 false / 研发 true | `U` `KNOWN` |

剩余 52 条的分组规则（`INFERRED`）：

| 组 | 判定 | 规则 |
|---|---|---|
| 标签与簿记 | `label*`、`*Identifier`、`*Index`、`device`、`commandQueue` | `L` |
| 调试与捕获 | `*DebugGroup*`、`*Signpost*`、`*Capture*`、`*Diagnostic*`、`dealloc*` | `L` + degradation |
| counter / 采样 | 含 `ounter`、`sampleBuffer` | `N-02` → R-Z |
| 其余 encoder 工厂与 MTL4 面 | `new*Encoder*`、`*MTL4*`、`*ArgumentTable*` | `N-01` / `N-10` → R-N |

---

### 5.4 `MTLRenderCommandEncoder`（131 required）

全家族里工作量最大的一张表。签名源：`crates/metal2vulkan-runtime/src/render.rs:1313`（`RenderCommandEncoder`，**116 个公开方法**）。encoding 源：`21` §8.5（`KNOWN`）。

分布：**`U` 105 / `C` 13 / `N` 13**。`U + C = 118`（90%）。

> 注意：上游的 116 个方法里有一部分对应的是 `MTLRenderCommandEncoderSPI` 的 selector（不在这 131 条里），列在第 5.4.9 节。所以 116 与 118 不是同一个口径下的数。

#### 5.4.1 pipeline 与固定功能状态（26 条）

| Metal selector | enc | 上游调用（`rt::RenderCommandEncoder::`） | 上游签名 | 参 | 返 | 错 | 标 |
|---|---|---|---|---|---|---|---|
| `setRenderPipelineState:` | `v24@0:8@16` | `set_render_pipeline_state` | `(&mut self, state: &RenderPipelineState) -> Result<(), Error>` | 对象表（K-06）；**非 nil**（上游不收 `Option`） | `void` | nil 入参 → A 档；`Err` → ② | `U` `KNOWN` |
| `setViewport:` | `v64@0:8{?=dddddd}16` | `set_viewport` | `(&mut self, viewport: Viewport) -> Result<(), Error>` | K-10（6 个 `double`） | `void` | ② | `U` `KNOWN` `*(partial)*` |
| `setViewports:count:` | `v32@0:8r^{?=dddddd}16Q24` | `set_viewports` | `(&mut self, viewports: &[Viewport]) -> Result<(), Error>` | K-07（无 `first`，整段） | `void` | ②；count > `max_viewports` → A | `U` `KNOWN` `*(partial)*` |
| `setFrontFacingWinding:` | `v24@0:8Q16` | `set_front_facing_winding` | `(&mut self, winding: Winding)` | K-11 | `void` | 无（不返回 `Result`） | `U` `KNOWN` |
| `setCullMode:` | `v24@0:8Q16` | `set_cull_mode` | `(&mut self, mode: CullMode)` | K-11 | `void` | 无 | `U` `KNOWN` |
| `setDepthClipMode:` | `v24@0:8Q16` | `set_depth_clip_mode` | `(&mut self, mode: DepthClipMode) -> Result<(), Error>` | K-11 | `void` | ② | `U` `KNOWN` |
| `setDepthBias:slopeScale:clamp:` | `v28@0:8f16f20f24` | `set_depth_bias` | `(&mut self, depth_bias: f32, slope_scale: f32, clamp: f32) -> Result<(), Error>` | 三个 `float`，过 `22` R19 非有限拒绝 | `void` | ② | `U` `KNOWN` `*(partial)*` |
| `setDepthTestMinBound:maxBound:` | `v24@0:8f16f20` | **无** | — | — | `void` | 记 degradation；depth bounds 失效 | **`N-07`** `KNOWN` |
| `setScissorRect:` | `v48@0:8{?=QQQQ}16` | `set_scissor_rect` | `(&mut self, rect: ScissorRect) -> Result<(), Error>` | K-10（4 个 `NSUInteger`） | `void` | ② | `U` `KNOWN` |
| `setScissorRects:count:` | `v32@0:8r^{?=QQQQ}16Q24` | `set_scissor_rects` | `(&mut self, rects: &[ScissorRect]) -> Result<(), Error>` | K-07 | `void` | ② | `U` `KNOWN` |
| `setTriangleFillMode:` | `v24@0:8Q16` | `set_triangle_fill_mode` | `(&mut self, mode: TriangleFillMode) -> Result<(), Error>` | K-11 | `void` | ② | `U` `KNOWN` |
| `setBlendColorRed:green:blue:alpha:` | `v32@0:8f16f20f24f28` | `set_blend_color` | `(&mut self, red: f32, green: f32, blue: f32, alpha: f32)` | 四个 `float`，R19 | `void` | 无 | `U` `KNOWN` |
| `setDepthStencilState:` | `v24@0:8@16` | `set_depth_stencil_state` | `<'a>(&mut self, state: impl Into<Option<&'a DepthStencilState>>) -> Result<(), Error>` | K-05：nil → `None`（Metal 的默认状态） | `void` | ② | `U` `KNOWN` |
| `setStencilReferenceValue:` | `v20@0:8I16` | `set_stencil_reference_value` | `(&mut self, value: u32)` | `unsigned int` | `void` | 无 | `U` `KNOWN` |
| `setStencilFrontReferenceValue:backReferenceValue:` | `v24@0:8I20I20` | `set_stencil_reference_values` | `(&mut self, front: u32, back: u32)` | 两个 `unsigned int` | `void` | 无 | `U` `KNOWN` |
| `setVisibilityResultMode:offset:` | `v32@0:8Q16Q24` | `set_visibility_result_mode` | `(&mut self, mode: VisibilityResultMode, offset: u64) -> Result<(), Error>` | K-11 + `u64` | `void` | ②；`VisibilityProblem` → A | `U` `KNOWN` |
| `setColorStoreAction:atIndex:` | `v32@0:8Q16Q24` | `set_color_store_action` | `(&mut self, action: StoreAction, index: u32) -> Result<(), Error>` | K-11 + K-15 | `void` | ② | `U` `KNOWN` |
| `setDepthStoreAction:` | `v24@0:8Q16` | `set_depth_store_action` | `(&mut self, action: StoreAction) -> Result<(), Error>` | K-11 | `void` | ② | `U` `KNOWN` |
| `setStencilStoreAction:` | `v24@0:8Q16` | `set_stencil_store_action` | `(&mut self, action: StoreAction) -> Result<(), Error>` | K-11 | `void` | ② | `U` `KNOWN` |
| `setColorStoreActionOptions:atIndex:` | `v32@0:8Q16Q24` | `set_color_store_action_options` | `(&mut self, _options: StoreActionOptions, index: u32) -> Result<(), Error>` | K-11 + K-15 | `void` | ②；**自定义采样位置被拒**（上游：Metal 也拒绝） | `U` `KNOWN` |
| `setDepthStoreActionOptions:` | `v24@0:8Q16` | `set_depth_store_action_options` | `(&mut self, options: StoreActionOptions) -> Result<(), Error>` | K-11 | `void` | ② | `U` `KNOWN` |
| `setStencilStoreActionOptions:` | `v24@0:8Q16` | `set_stencil_store_action_options` | `(&mut self, options: StoreActionOptions) -> Result<(), Error>` | K-11 | `void` | ② | `U` `KNOWN` |
| `setTessellationFactorBuffer:offset:instanceStride:` | `v40@0:8@16Q24Q32` | `set_tessellation_factor_buffer` | `(&mut self, buffer: Option<&Buffer>, offset: u64, instance_stride: u64) -> Result<(), Error>` | R-B | `void` | ② | `U` `KNOWN` |
| `setTessellationFactorScale:` | `v20@0:8f16` | `set_tessellation_factor_scale` | `(&mut self, scale: f32)` | `float`，R19 | `void` | 无 | `U` `KNOWN` |
| `setThreadgroupMemoryLength:offset:atIndex:` | `v40@0:8Q16Q24Q32` | `set_threadgroup_memory_length` | `(&mut self, length: u64, offset: u64, index: u32) -> Result<(), Error>` | **三参形态，length 是 `u64`**（与 compute 的 `u32` 两参不同，K-15） | `void` | ② | `U` `KNOWN` |
| `setColorAttachmentMap:` | `v24@0:8@16` | **无** | — | — | `void` | 记 degradation；attachment 重映射失效 | **`N-08`** `KNOWN` |

小计：`U` 24 / `N` 2。

#### 5.4.2 vertex 阶段绑定（20 条）

族规则：buffer / bytes 走 R-B / R-BA / R-BY，texture 走 R-T / R-TA，sampler 走 R-S（render 形态，见第 2.7 节）。全部返回 `void`，错误走 ②。

| Metal selector | enc | 上游调用（`rt::RenderCommandEncoder::`） | 上游签名 | 族 | 标 |
|---|---|---|---|---|---|
| `setVertexBytes:length:atIndex:` | `v40@0:8r^v16Q24Q32` | `set_vertex_bytes` | `(&mut self, bytes: &[u8], index: u32) -> Result<(), Error>` | R-BY | `U` `KNOWN` |
| `setVertexBytes:length:attributeStride:atIndex:` | `v48@0:8r^v16Q24Q32Q40` | `set_vertex_bytes_with_stride` | `(&mut self, bytes: &[u8], stride: u64, index: u32) -> Result<(), Error>` | R-BY | `U` `KNOWN` |
| `setVertexBuffer:offset:atIndex:` | `v40@0:8@16Q24Q32` | `set_vertex_buffer` | `(&mut self, buffer: Option<&Buffer>, offset: u64, index: u32) -> Result<(), Error>` | R-B | `U` `KNOWN` |
| `setVertexBuffer:offset:attributeStride:atIndex:` | `v48@0:8@16Q24Q32Q40` | `set_vertex_buffer_with_stride` | `(&mut self, buffer: Option<&Buffer>, offset: u64, stride: u64, index: u32) -> Result<(), Error>` | R-B | `U` `KNOWN` |
| `setVertexBufferOffset:atIndex:` | `v32@0:8Q16Q24` | `set_vertex_buffer_offset` | `(&mut self, offset: u64, index: u32) -> Result<(), Error>` | R-B | `U` `KNOWN` |
| `setVertexBufferOffset:attributeStride:atIndex:` | `v40@0:8Q16Q24Q32` | `set_vertex_buffer_offset_with_stride` | `(&mut self, offset: u64, stride: u64, index: u32) -> Result<(), Error>` | R-B | `U` `KNOWN` |
| `setVertexBuffers:offsets:withRange:` | `v48@0:8r^@16r^Q24{_NSRange=QQ}32` | `set_vertex_buffers` | `(&mut self, buffers: &[Option<&Buffer>], offsets: &[u64], first: u32) -> Result<(), Error>` | R-BA | `U` `KNOWN` |
| `setVertexBuffers:offsets:attributeStrides:withRange:` | `v56@0:8r^@16r^Q24r^Q32{_NSRange=QQ}40` | `set_vertex_buffers_with_strides` | `(&mut self, buffers: &[Option<&Buffer>], offsets: &[u64], strides: &[u64], first: u32) -> Result<(), Error>` | R-BA | `U` `KNOWN` |
| `setVertexTexture:atIndex:` | `v32@0:8@16Q24` | `set_vertex_texture` | `(&mut self, texture: Option<&Texture>, index: u32) -> Result<(), Error>` | R-T | `U` `KNOWN` |
| `setVertexTextures:withRange:` | `v40@0:8r^@16{_NSRange=QQ}24` | `set_vertex_textures` | `(&mut self, textures: &[Option<&Texture>], first: u32) -> Result<(), Error>` | R-TA | `U` `KNOWN` |
| `setVertexSamplerState:atIndex:` | `v32@0:8@16Q24` | `set_vertex_sampler_state` | `(&mut self, sampler: Option<&SamplerState>, index: u32) -> Result<(), Error>` | R-S | `U` `KNOWN` |
| `setVertexSamplerState:lodMinClamp:lodMaxClamp:atIndex:` | `v40@0:8@16f24f28Q32` | `set_vertex_sampler_states` | `(&mut self, samplers: &[Option<&SamplerState>], clamps: Option<(&[f32], &[f32])>, first: u32) -> Result<(), Error>` | R-S：**1 元素 slice + `Some((&[min], &[max]))`**；两 clamp 过 R19 与 R20（`min <= max`） | **`C`** `KNOWN` |
| `setVertexSamplerStates:withRange:` | `v40@0:8r^@16{_NSRange=QQ}24` | `set_vertex_sampler_states` | 同上，`clamps = None` | R-S | `U` `KNOWN` |
| `setVertexSamplerStates:lodMinClamps:lodMaxClamps:withRange:` | `v56@0:8r^@16r^f24r^f32{_NSRange=QQ}40` | `set_vertex_sampler_states` | 同上，`clamps = Some((mins, maxs))` | R-S | `U` `KNOWN` |
| `setVertexVisibleFunctionTable:atBufferIndex:` | `v32@0:8@16Q24` | `set_vertex_visible_function_table` | `(&mut self, table: Option<&VisibleFunctionTable>, index: u32) -> Result<(), Error>` | R-T 形 | `U` `KNOWN`（**对象可建，通过表调用被拒**，`40` §2.4） |
| `setVertexVisibleFunctionTables:withBufferRange:` | `v40@0:8r^@16{_NSRange=QQ}24` | `set_vertex_visible_function_tables` | `(&mut self, tables: &[Option<&VisibleFunctionTable>], first: u32) -> Result<(), Error>` | R-TA 形 | `U` `KNOWN` |
| `setVertexAmplificationCount:viewMappings:` | `v32@0:8Q16r^{?=II}24` | `set_vertex_amplification_count` | `(&mut self, count: u64, view_mappings: Option<&[VertexAmplificationViewMapping]>) -> Result<(), Error>` | `{?=II}` 数组 → `&[VertexAmplificationViewMapping]`；**mappings 少于 count 被拒 `Invalid`** | `U` `KNOWN` |
| `setVertexIntersectionFunctionTable:atBufferIndex:` | `v32@0:8@16Q24` | **无** | — | — | **`N-04`** `KNOWN` |
| `setVertexIntersectionFunctionTables:withBufferRange:` | `v40@0:8r^@16{_NSRange=QQ}24` | **无** | — | — | **`N-04`** `KNOWN` |
| `setVertexAccelerationStructure:atBufferIndex:` | `v32@0:8@16Q24` | **无** | — | — | **`N-04`** `KNOWN` |

小计：`U` 16 / `C` 1 / `N` 3。

#### 5.4.3 fragment 阶段绑定（15 条）

与第 5.4.2 节同构，方法名把 `vertex` 换成 `fragment`，去掉 4 个 buffer 的 stride 变体与 amplification。

| Metal selector | enc | 上游调用（`rt::RenderCommandEncoder::`） | 族 | 标 |
|---|---|---|---|---|
| `setFragmentBytes:length:atIndex:` | `v40@0:8r^v16Q24Q32` | `set_fragment_bytes(&mut self, bytes: &[u8], index: u32)` | R-BY | `U` `KNOWN` |
| `setFragmentBuffer:offset:atIndex:` | `v40@0:8@16Q24Q32` | `set_fragment_buffer(&mut self, buffer: Option<&Buffer>, offset: u64, index: u32)` | R-B | `U` `KNOWN` |
| `setFragmentBufferOffset:atIndex:` | `v32@0:8Q16Q24` | `set_fragment_buffer_offset(&mut self, offset: u64, index: u32)` | R-B | `U` `KNOWN` |
| `setFragmentBuffers:offsets:withRange:` | `v48@0:8r^@16r^Q24{_NSRange=QQ}32` | `set_fragment_buffers(&mut self, buffers: &[Option<&Buffer>], offsets: &[u64], first: u32)` | R-BA | `U` `KNOWN` |
| `setFragmentTexture:atIndex:` | `v32@0:8@16Q24` | `set_fragment_texture(&mut self, texture: Option<&Texture>, index: u32)` | R-T | `U` `KNOWN` |
| `setFragmentTextures:withRange:` | `v40@0:8r^@16{_NSRange=QQ}24` | `set_fragment_textures(&mut self, textures: &[Option<&Texture>], first: u32)` | R-TA | `U` `KNOWN` |
| `setFragmentSamplerState:atIndex:` | `v32@0:8@16Q24` | `set_fragment_sampler_state(&mut self, sampler: Option<&SamplerState>, index: u32)` | R-S | `U` `KNOWN` |
| `setFragmentSamplerState:lodMinClamp:lodMaxClamp:atIndex:` | `v40@0:8@16f24f28Q32` | `set_fragment_sampler_states`（1 元素 + `Some(clamps)`） | R-S | **`C`** `KNOWN` |
| `setFragmentSamplerStates:withRange:` | `v40@0:8r^@16{_NSRange=QQ}24` | `set_fragment_sampler_states(.., None, first)` | R-S | `U` `KNOWN` |
| `setFragmentSamplerStates:lodMinClamps:lodMaxClamps:withRange:` | `v56@0:8r^@16r^f24r^f32{_NSRange=QQ}40` | `set_fragment_sampler_states(.., Some((mins, maxs)), first)` | R-S | `U` `KNOWN` |
| `setFragmentVisibleFunctionTable:atBufferIndex:` | `v32@0:8@16Q24` | `set_fragment_visible_function_table(&mut self, table: Option<&VisibleFunctionTable>, index: u32)` | R-T 形 | `U` `KNOWN` |
| `setFragmentVisibleFunctionTables:withBufferRange:` | `v40@0:8r^@16{_NSRange=QQ}24` | `set_fragment_visible_function_tables(&mut self, tables: &[Option<&VisibleFunctionTable>], first: u32)` | R-TA 形 | `U` `KNOWN` |
| `setFragmentIntersectionFunctionTable:atBufferIndex:` | `v32@0:8@16Q24` | **无** | — | **`N-04`** `KNOWN` |
| `setFragmentIntersectionFunctionTables:withBufferRange:` | `v40@0:8r^@16{_NSRange=QQ}24` | **无** | — | **`N-04`** `KNOWN` |
| `setFragmentAccelerationStructure:atBufferIndex:` | `v32@0:8@16Q24` | **无** | — | **`N-04`** `KNOWN` |

小计：`U` 11 / `C` 1 / `N` 3。

#### 5.4.4 tile 阶段绑定（15 条）

与第 5.4.3 节同构，`fragment` → `tile`。全部 encoding 与 fragment 族逐项相同（`21` §8.5 可核）。

| Metal selector | 上游调用（`rt::RenderCommandEncoder::`） | 族 | 标 |
|---|---|---|---|
| `setTileBytes:length:atIndex:` | `set_tile_bytes(&mut self, bytes: &[u8], index: u32)` | R-BY | `U` `KNOWN` |
| `setTileBuffer:offset:atIndex:` | `set_tile_buffer(&mut self, buffer: Option<&Buffer>, offset: u64, index: u32)` | R-B | `U` `KNOWN` |
| `setTileBufferOffset:atIndex:` | `set_tile_buffer_offset(&mut self, offset: u64, index: u32)` | R-B | `U` `KNOWN` |
| `setTileBuffers:offsets:withRange:` | `set_tile_buffers(&mut self, buffers: &[Option<&Buffer>], offsets: &[u64], first: u32)` | R-BA | `U` `KNOWN` |
| `setTileTexture:atIndex:` | `set_tile_texture(&mut self, texture: Option<&Texture>, index: u32)` | R-T | `U` `KNOWN` |
| `setTileTextures:withRange:` | `set_tile_textures(&mut self, textures: &[Option<&Texture>], first: u32)` | R-TA | `U` `KNOWN` |
| `setTileSamplerState:atIndex:` | `set_tile_sampler_state(&mut self, sampler: Option<&SamplerState>, index: u32)` | R-S | `U` `KNOWN` |
| `setTileSamplerState:lodMinClamp:lodMaxClamp:atIndex:` | `set_tile_sampler_states`（1 元素 + `Some(clamps)`） | R-S | **`C`** `KNOWN` |
| `setTileSamplerStates:withRange:` | `set_tile_sampler_states(.., None, first)` | R-S | `U` `KNOWN` |
| `setTileSamplerStates:lodMinClamps:lodMaxClamps:withRange:` | `set_tile_sampler_states(.., Some((mins, maxs)), first)` | R-S | `U` `KNOWN` |
| `setTileVisibleFunctionTable:atBufferIndex:` | `set_tile_visible_function_table(..)` | R-T 形 | `U` `KNOWN` |
| `setTileVisibleFunctionTables:withBufferRange:` | `set_tile_visible_function_tables(..)` | R-TA 形 | `U` `KNOWN` |
| `setTileIntersectionFunctionTable:atBufferIndex:` | **无** | — | **`N-04`** `KNOWN` |
| `setTileIntersectionFunctionTables:withBufferRange:` | **无** | — | **`N-04`** `KNOWN` |
| `setTileAccelerationStructure:atBufferIndex:` | **无** | — | **`N-04`** `KNOWN` |

小计：`U` 11 / `C` 1 / `N` 3。

#### 5.4.5 object 阶段绑定（11 条）

**这一组是 `40` §3.3 的索引表漏掉的落点。** 上游文档的 `RenderCmd` 一节不列它们，但源码里 9 个 `set_object_*` 方法都在（`KNOWN`：`render.rs` 的 `pub fn set_object_buffer` 等符号）。`21` §8.5 把这 11 条全标「— 继承」（APV 不实现），但**上游有落点**，所以本项目可以实现它们而不必补缺。

| Metal selector | 上游调用（`rt::RenderCommandEncoder::`） | 族 | 标 |
|---|---|---|---|
| `setObjectBytes:length:atIndex:` | `set_object_bytes(&mut self, bytes: &[u8], index: u32)` | R-BY | `U` `KNOWN` |
| `setObjectBuffer:offset:atIndex:` | `set_object_buffer(&mut self, buffer: Option<&Buffer>, offset: u64, index: u32)` | R-B | `U` `KNOWN` |
| `setObjectBufferOffset:atIndex:` | `set_object_buffer_offset(&mut self, offset: u64, index: u32)` | R-B | `U` `KNOWN` |
| `setObjectBuffers:offsets:withRange:` | `set_object_buffers(&mut self, buffers: &[Option<&Buffer>], offsets: &[u64], first: u32)` | R-BA | `U` `KNOWN` |
| `setObjectTexture:atIndex:` | `set_object_texture(&mut self, texture: Option<&Texture>, index: u32)` | R-T | `U` `KNOWN` |
| `setObjectTextures:withRange:` | `set_object_textures(&mut self, textures: &[Option<&Texture>], first: u32)` | R-TA | `U` `KNOWN` |
| `setObjectSamplerState:atIndex:` | `set_object_sampler_state(..)` | R-S | `U` `KNOWN` |
| `setObjectSamplerState:lodMinClamp:lodMaxClamp:atIndex:` | `set_object_sampler_states`（1 元素 + `Some(clamps)`） | R-S | **`C`** `KNOWN` |
| `setObjectSamplerStates:withRange:` | `set_object_sampler_states(.., None, first)` | R-S | `U` `KNOWN` |
| `setObjectSamplerStates:lodMinClamps:lodMaxClamps:withRange:` | `set_object_sampler_states(.., Some((mins, maxs)), first)` | R-S | `U` `KNOWN` |
| `setObjectThreadgroupMemoryLength:atIndex:` | `set_object_threadgroup_memory_length(&mut self, length: u32, index: u32) -> Result<(), Error>` | **`length` 是 `u32`**（与同名 render 三参形态不同，K-15） | `U` `KNOWN` |

小计：`U` 10 / `C` 1。

#### 5.4.6 mesh 阶段绑定（10 条）

同第 5.4.5 节，`object` → `mesh`。同样是 `40` §3.3 索引漏掉的落点。

| Metal selector | 上游调用（`rt::RenderCommandEncoder::`） | 族 | 标 |
|---|---|---|---|
| `setMeshBytes:length:atIndex:` | `set_mesh_bytes` | R-BY | `U` `KNOWN` |
| `setMeshBuffer:offset:atIndex:` | `set_mesh_buffer` | R-B | `U` `KNOWN` |
| `setMeshBufferOffset:atIndex:` | `set_mesh_buffer_offset` | R-B | `U` `KNOWN` |
| `setMeshBuffers:offsets:withRange:` | `set_mesh_buffers` | R-BA | `U` `KNOWN` |
| `setMeshTexture:atIndex:` | `set_mesh_texture` | R-T | `U` `KNOWN` |
| `setMeshTextures:withRange:` | `set_mesh_textures` | R-TA | `U` `KNOWN` |
| `setMeshSamplerState:atIndex:` | `set_mesh_sampler_state` | R-S | `U` `KNOWN` |
| `setMeshSamplerState:lodMinClamp:lodMaxClamp:atIndex:` | `set_mesh_sampler_states`（1 元素 + `Some(clamps)`） | R-S | **`C`** `KNOWN` |
| `setMeshSamplerStates:withRange:` | `set_mesh_sampler_states(.., None, first)` | R-S | `U` `KNOWN` |
| `setMeshSamplerStates:lodMinClamps:lodMaxClamps:withRange:` | `set_mesh_sampler_states(.., Some((mins, maxs)), first)` | R-S | `U` `KNOWN` |

小计：`U` 9 / `C` 1。

#### 5.4.7 draw（15 条）

族规则 R-D。注意 `instanceCount` 缺省为 1、`baseInstance` / `baseVertex` 缺省为 0（K-03）。

| Metal selector | enc | 上游调用（`rt::RenderCommandEncoder::`） | 上游签名 | 参 | 标 |
|---|---|---|---|---|---|
| `drawPrimitives:vertexStart:vertexCount:instanceCount:baseInstance:` | `v56@0:8Q16Q24Q32Q40Q48` | `draw_primitives` | `(&mut self, primitive_type: impl Into<DrawPrimitiveType>, vertex_start: u32, vertex_count: u32, instance_count: u32, base_instance: u32) -> Result<(), Error>` | R-D | `U` `KNOWN` `*(partial)*` |
| `drawPrimitives:vertexStart:vertexCount:instanceCount:` | `v48@0:8Q16Q24Q32Q40` | `draw_primitives` | 同上 | R-D，`base_instance = 0` | **`C`** `KNOWN` |
| `drawPrimitives:vertexStart:vertexCount:` | `v40@0:8Q16Q24Q32` | `draw_primitives` | 同上 | R-D，`instance_count = 1`、`base_instance = 0` | **`C`** `KNOWN` |
| `drawPrimitives:indirectBuffer:indirectBufferOffset:` | `v40@0:8Q16@24Q32` | `draw_primitives_indirect` | `(&mut self, primitive_type: impl Into<DrawPrimitiveType>, indirect_buffer: &Buffer, indirect_buffer_offset: u64) -> Result<(), Error>` | R-D；buffer **非 `Option`** | `U` `KNOWN` `*(partial)*` |
| `drawIndexedPrimitives:indexCount:indexType:indexBuffer:indexBufferOffset:instanceCount:baseVertex:baseInstance:` | `v80@0:8Q16Q24Q32@40Q48Q56q64Q72` | `draw_indexed_primitives` | `(&mut self, primitive_type: impl Into<DrawPrimitiveType>, index_count: u32, index_type: IndexType, index_buffer: &Buffer, index_buffer_offset: u64, instance_count: u32, base_vertex: i32, base_instance: u32) -> Result<(), Error>` | R-D；`baseVertex` 是 `NSInteger` → `i32` checked | `U` `KNOWN` `*(partial)*` |
| `drawIndexedPrimitives:indexCount:indexType:indexBuffer:indexBufferOffset:instanceCount:` | `v64@0:8Q16Q24Q32@40Q48Q56` | `draw_indexed_primitives` | 同上 | R-D，`base_vertex = 0`、`base_instance = 0` | **`C`** `KNOWN` |
| `drawIndexedPrimitives:indexCount:indexType:indexBuffer:indexBufferOffset:` | `v56@0:8Q16Q24Q32@40Q48` | `draw_indexed_primitives` | 同上 | R-D，`instance_count = 1`、其余 0 | **`C`** `KNOWN` |
| `drawIndexedPrimitives:indexType:indexBuffer:indexBufferOffset:indirectBuffer:indirectBufferOffset:` | `v64@0:8Q16Q24@32Q40@48Q56` | `draw_indexed_primitives_indirect` | `(&mut self, primitive_type: impl Into<DrawPrimitiveType>, index_type: IndexType, index_buffer: &Buffer, index_buffer_offset: u64, indirect_buffer: &Buffer, indirect_buffer_offset: u64) -> Result<(), Error>` | R-D | `U` `KNOWN` `*(partial)*` |
| `drawPatches:patchStart:patchCount:patchIndexBuffer:patchIndexBufferOffset:instanceCount:baseInstance:` | `v72@0:8Q16Q24Q32@40Q48Q56Q64` | `draw_patches` | `(&mut self, number_of_patch_control_points: u32, patch_start: u32, patch_count: u32, patch_index_buffer: Option<&Buffer>, patch_index_buffer_offset: u64, instance_count: u32, base_instance: u32) -> Result<(), Error>` | patch index buffer 可 nil（K-05） | `U` `KNOWN` |
| `drawPatches:patchIndexBuffer:patchIndexBufferOffset:indirectBuffer:indirectBufferOffset:` | `v56@0:8Q16@24Q32@40Q48` | `draw_patches_indirect` | `(&mut self, number_of_patch_control_points: u32, patch_index_buffer: Option<&Buffer>, patch_index_buffer_offset: u64, indirect_buffer: &Buffer, indirect_buffer_offset: u64) -> Result<(), Error>` | 同上 | `U` `KNOWN` |
| `drawIndexedPatches:patchStart:patchCount:patchIndexBuffer:patchIndexBufferOffset:controlPointIndexBuffer:controlPointIndexBufferOffset:instanceCount:baseInstance:` | `v88@0:8Q16Q24Q32@40Q48@56Q64Q72Q80` | `draw_indexed_patches` | `(&mut self, number_of_patch_control_points: u32, patch_start: u32, patch_count: u32, patch_index_buffer: Option<&Buffer>, patch_index_buffer_offset: u64, control_point_index_buffer: &Buffer, control_point_index_buffer_offset: u64, instance_count: u32, base_instance: u32) -> Result<(), Error>` | **control point index buffer 非 `Option`**（patch index buffer 是） | `U` `KNOWN` |
| `drawIndexedPatches:patchIndexBuffer:patchIndexBufferOffset:controlPointIndexBuffer:controlPointIndexBufferOffset:indirectBuffer:indirectBufferOffset:` | `v72@0:8Q16@24Q32@40Q48@56Q64` | `draw_indexed_patches_indirect` | `(&mut self, number_of_patch_control_points: u32, patch_index_buffer: Option<&Buffer>, patch_index_buffer_offset: u64, control_point_index_buffer: &Buffer, control_point_index_buffer_offset: u64, indirect_buffer: &Buffer, indirect_buffer_offset: u64) -> Result<(), Error>` | 同上 | `U` `KNOWN` |
| `drawMeshThreadgroups:threadsPerObjectThreadgroup:threadsPerMeshThreadgroup:` | `v88@0:8{?=QQQ}16{?=QQQ}40{?=QQQ}64` | `draw_mesh_threadgroups` | `(&mut self, groups: Size, threads_per_object_group: Size, threads_per_mesh_group: Size) -> Result<(), Error>` | K-10 ×3 | `U` `KNOWN` |
| `drawMeshThreads:threadsPerObjectThreadgroup:threadsPerMeshThreadgroup:` | `v88@0:8{?=QQQ}16{?=QQQ}40{?=QQQ}64` | `draw_mesh_threads` | `(&mut self, threads: Size, threads_per_object_group: Size, threads_per_mesh_group: Size) -> Result<(), Error>` | K-10 ×3 | `U` `KNOWN` |
| `drawMeshThreadgroupsWithIndirectBuffer:indirectBufferOffset:threadsPerObjectThreadgroup:threadsPerMeshThreadgroup:` | `v80@0:8@16Q24{?=QQQ}32{?=QQQ}56` | `draw_mesh_threadgroups_indirect` | `(&mut self, indirect_buffer: &Buffer, indirect_buffer_offset: u64, threads_per_object_group: Size, threads_per_mesh_group: Size) -> Result<(), Error>` | K-10 ×2 | `U` `KNOWN` |

小计：`U` 11 / `C` 4。

> **mesh draw 的三条都有上游落点**，这是 `40` §3.3 漏掉的第二处。但 mesh **pipeline state 的查询**没有落点（第 5.13 节 `N-05`），`Error::MeshRecordsOverflow` 与「mesh 管线不产生 `PipelineRecord`」（`40` §6.6）说明上游的 mesh 路径是部分实现。

#### 5.4.8 资源驻留、同步、间接命令、tile 查询（19 条）

| Metal selector | enc | 上游调用（`rt::RenderCommandEncoder::`） | 上游签名 | 参 | 标 |
|---|---|---|---|---|---|
| `useResource:usage:stages:` | `v40@0:8@16Q24Q32` | `use_resource` | `(&mut self, resource: ResourceRef<'_>, usage: ResourceUsage, stages: RenderStages) -> Result<(), Error>` | R-U | `U` `KNOWN` |
| `useResource:usage:` | `v32@0:8@16Q24` | `use_resource` | 同上 | R-U，stages 补全 | **`C`** `KNOWN` |
| `useResources:count:usage:stages:` | `v48@0:8r^@16Q24Q32Q40` | `use_resources` | `(&mut self, resources: &[ResourceRef<'_>], usage: ResourceUsage, stages: RenderStages) -> Result<(), Error>` | R-U + K-07 | `U` `KNOWN` |
| `useResources:count:usage:` | `v40@0:8r^@16Q24Q32` | `use_resources` | 同上 | R-U，stages 补全 | **`C`** `KNOWN` |
| `useHeap:stages:` | `v32@0:8@16Q24` | `use_heap` | `(&mut self, heap: &Heap, stages: RenderStages) -> Result<(), Error>` | R-U；**`&Heap` 非 `ResourceRef`**（K-06） | `U` `KNOWN` |
| `useHeap:` | `v24@0:8@16` | `use_heap` | 同上 | R-U，stages 补全 | **`C`** `KNOWN` |
| `useHeaps:count:stages:` | `v40@0:8r^@16Q24Q32` | `use_heaps` | `(&mut self, heaps: &[&Heap], stages: RenderStages) -> Result<(), Error>` | **slice 元素非 `Option`** | `U` `KNOWN` |
| `useHeaps:count:` | `v32@0:8r^@16Q24` | `use_heaps` | 同上 | stages 补全 | **`C`** `KNOWN` |
| `updateFence:afterStages:` | `v32@0:8@16Q24` | `update_fence` | `(&mut self, fence: &Fence, after_stages: RenderStages) -> Result<(), Error>` | R-F | `U` `KNOWN` |
| `waitForFence:beforeStages:` | `v32@0:8@16Q24` | `wait_for_fence` | `(&mut self, fence: &Fence, before_stages: RenderStages) -> Result<(), Error>` | R-F | `U` `KNOWN` |
| `memoryBarrierWithScope:afterStages:beforeStages:` | `v40@0:8Q16Q24Q32` | `memory_barrier_with_scope` | `(&mut self, scope: BarrierScope, after_stages: RenderStages, before_stages: RenderStages)` | K-11 ×3；**不返回 `Result`** | `U` `KNOWN` |
| `memoryBarrierWithResources:count:afterStages:beforeStages:` | `v48@0:8r^@16Q24Q32Q40` | `memory_barrier_with_resources` | `(&mut self, resources: &[ResourceRef<'_>], after_stages: RenderStages, before_stages: RenderStages) -> Result<(), Error>` | K-06 + K-07 | `U` `KNOWN` |
| `textureBarrier` | `v16@0:8` | **无** | — | — | **`N-06`** `KNOWN` |
| `executeCommandsInBuffer:withRange:` | `v40@0:8@16{_NSRange=QQ}24` | `execute_commands_in_buffer`（另有 `_checked`） | `(&mut self, icb: &IndirectCommandBuffer, range: Range<u64>) -> Result<(), Error>` | K-08 | `U` `KNOWN` `*(partial)*` |
| `executeCommandsInBuffer:indirectBuffer:indirectBufferOffset:` | `v40@0:8@16@24Q32` | `execute_commands_in_buffer_indirect`（另有 `_checked`） | `(&mut self, icb: &IndirectCommandBuffer, range_buffer: &Buffer, offset: u64) -> Result<(), Error>` | K-06 | `U` `KNOWN` `*(partial)*` |
| `dispatchThreadsPerTile:` | `v40@0:8{?=QQQ}16` | `dispatch_threads_per_tile` | `(&mut self, threads: Size) -> Result<(), Error>` | K-10 | `U` `KNOWN` |
| `sampleCountersInBuffer:atSampleIndex:withBarrier:` | `v36@0:8@16Q24c32` | **无** | — | — | **`N-02`** `KNOWN` |
| `tileWidth` | `Q16@0:8` | `tile_width` | `(&self) -> Result<u64, Error>` | 无；`Ended` 后答缓存值（第 3.3 节） | `U` `KNOWN` |
| `tileHeight` | `Q16@0:8` | `tile_height` | `(&self) -> Result<u64, Error>` | 同上 | `U` `KNOWN` |

小计：`U` 13 / `C` 4 / `N` 2。

> `_checked` 变体（`execute_commands_in_buffer_checked`、`execute_commands_in_buffer_indirect_checked`）是 runtime 扩展，签名各多两个参数 `check: IndirectCommandCheck, needs: IndirectCommandCheckNeeds`。**本项目应当用 `_checked` 形态**：它是 `40` §4.1 点名的 guest 命令流校验点，普通形态不做逐命令校验。`INFERRED`

#### 5.4.9 `MTLRenderCommandEncoderSPI`：上游**有**落点的 14 条

`21` 附录 A.1 的 `PGSerializerRenderCommandEncoder` 有 152 条 IMP，超出 `MTLRenderCommandEncoder` 的 131 条。超出部分走 SPI 协议。其中上游明确实现的（`KNOWN`，取自上游 `docs/RUNTIME-PORTING.md` 的 `RenderCmd` / `RenderEncoder` 节与源码签名），本项目实现 SPI 层时必须用这些落点而不是自己补：

| Metal selector（SPI） | 上游调用（`rt::RenderCommandEncoder::`） | 上游签名 | 语义要点 | 标 |
|---|---|---|---|---|
| `setDepthClipMode:`（公开，但 SPI 另有一份） | `set_depth_clip_mode` | `(&mut self, mode: DepthClipMode) -> Result<(), Error>` | 公开方法即落点（上游「Composed from runtime calls」把 `SetDepthClipModeSpi` 指向它） | `U` `KNOWN` |
| `setPrimitiveRestartEnabled:index:` | `set_primitive_restart_enabled` | `(&mut self, _enabled: bool, index: u64)` | **索引 strip 按 Metal 对该 index type 取的值重启，且只在那里重启** | `U` `KNOWN` |
| `setAlphaTestReferenceValue:` | `set_alpha_test_reference_value` | `(&mut self, value: f32) -> Result<(), Error>` | 私有 alpha test 的参考值 | `U` `KNOWN` |
| `setLineWidth:` | `set_line_width` | `(&mut self, width: f32) -> Result<(), Error>` | **1 接受，其他值 → `AppleOnly::LineWidth`** | `U` `KNOWN` `*(partial)*` |
| `setPointSize:` | `set_point_size` | `(&mut self, size: f32) -> Result<(), Error>` | no-op，与 Metal 一致 → 第 4.3 节 ③ 档 | `U` `KNOWN` |
| `setProvokingVertexMode:` | `set_provoking_vertex_mode` | `(&mut self, mode: u64) -> Result<(), Error>` | 模式 0 / 1 照 Metal 画；其余按 1 画（patch 按 0），逐 draw 报 `provoking-vertex-unmatched` | `U` `KNOWN` `*(partial)*` |
| `setViewportTransformEnabled:` | `set_viewport_transform_enabled` | `(&mut self, enabled: bool) -> Result<(), Error>` | **on 接受，off → `AppleOnly::ViewportTransformDisabled`** | `U` `KNOWN` `*(partial)*` |
| `setVertexAmplificationMode:value:` | `set_vertex_amplification_mode` | `(&mut self, mode: u64, value: u64) -> Result<(), Error>` | 设 amplification count 并保留 view mappings；**0、>8、超过 mappings 数 → `AppleOnly::VertexAmplificationMode`** | `U` `KNOWN` `*(partial)*` |
| `setDepthCleared` | `set_depth_cleared` | `(&mut self) -> Result<(), Error>` | 什么也不改，与 Metal 一致 → ③ 档 | `U` `KNOWN` |
| `setStencilCleared` | `set_stencil_cleared` | `(&mut self) -> Result<(), Error>` | 同上 | `U` `KNOWN` |
| `setColorResolveTexture:slice:depthPlane:level:yInvert:atIndex:` | `set_color_resolve_target` | `(&mut self, target: Option<ResolveTarget>, index: u32) -> Result<(), Error>` | **最后设置的那个对整个 pass 的每个 draw 生效** | `U` `KNOWN` `*(partial)*` |
| `setDepthResolveTexture:slice:depthPlane:level:yInvert:` | `set_depth_resolve_target` | `(&mut self, target: Option<ResolveTarget>) -> Result<(), Error>` | 同上 | `U` `KNOWN` `*(partial)*` |
| `setStencilResolveTexture:slice:depthPlane:level:yInvert:` | `set_stencil_resolve_target` | `(&mut self, target: Option<ResolveTarget>) -> Result<(), Error>` | 同上 | `U` `KNOWN` `*(partial)*` |
| `dispatchThreadsPerTile:inRegion:` / `...withRenderTargetArrayIndex:` | `dispatch_threads_per_tile_in_region` | `(&mut self, threads: Size, region: Region, render_target_array_index: Option<u32>) -> Result<(), Error>` | 无 index 形态传 `None`（region 触到的 tile），有 index 形态传 `Some(index)` | `U` `KNOWN` |

---

### 5.5 `MTLComputeCommandEncoder`（39 required）

签名源：`crates/metal2vulkan-runtime/src/compute.rs:154`（`ComputeCommandEncoder`，47 个公开方法）。encoding 源：`21` 附录 A.2（35 条带 encoding）+ 4 条 APV 继承未列（标 `—`，记 `M-006`）。

分布：**`U` 35 / `N` 4**（90%）。

| Metal selector | enc | 上游调用（`rt::ComputeCommandEncoder::`） | 上游签名 | 参 / 要点 | 标 |
|---|---|---|---|---|---|
| `setComputePipelineState:` | `v24@0:8@16` | `set_compute_pipeline_state` | `(&mut self, state: &ComputePipelineState) -> Result<(), Error>` | 非 `Option` | `U` `KNOWN` |
| `dispatchThreadgroups:threadsPerThreadgroup:` | `v64@0:8{?=QQQ}16{?=QQQ}40` | `dispatch_threadgroups` | `(&mut self, groups: Size, threads: Size) -> Result<(), Error>` | K-10 ×2 | `U` `KNOWN` |
| `dispatchThreadgroupsWithIndirectBuffer:indirectBufferOffset:threadsPerThreadgroup:` | `v56@0:8@16Q24{?=QQQ}32` | `dispatch_threadgroups_indirect` | `(&mut self, indirect_buffer: &Buffer, indirect_buffer_offset: u64, threads: Size) -> Result<(), Error>` | K-06 + K-10 | `U` `KNOWN` |
| `dispatchThreads:threadsPerThreadgroup:` | `v64@0:8{?=QQQ}16{?=QQQ}40` | `dispatch_threads` | `(&mut self, threads: Size, per_group: Size) -> Result<(), Error>` | K-10 ×2 | `U` `KNOWN` |
| `dispatchThreadsWithIndirectBuffer:indirectBufferOffset:` | `v32@0:8@16Q24` | `dispatch_threads_indirect` | `(&mut self, indirect_buffer: &Buffer, indirect_buffer_offset: u64) -> Result<(), Error>` | **参数由一个 host step 读取**（上游行为） | `U` `KNOWN` |
| `dispatchType` | `Q16@0:8` | `dispatch_type` | `(&self) -> DispatchType` | 直接映射 | `U` `KNOWN` |
| `setBytes:length:atIndex:` | `v40@0:8r^v16Q24Q32` | `set_bytes` | `(&mut self, bytes: &[u8], index: u32) -> Result<(), Error>` | R-BY | `U` `KNOWN` |
| `setBytes:length:attributeStride:atIndex:` | `v48@0:8r^v16Q24Q32Q40` | `set_bytes_with_stride` | `(&mut self, bytes: &[u8], stride: u64, index: u32) -> Result<(), Error>` | R-BY | `U` `KNOWN` |
| `setBuffer:offset:atIndex:` | `v40@0:8@16Q24Q32` | `set_buffer` | `(&mut self, buffer: Option<&Buffer>, offset: u64, index: u32) -> Result<(), Error>` | R-B | `U` `KNOWN` |
| `setBuffer:offset:attributeStride:atIndex:` | `v48@0:8@16Q24Q32Q40` | `set_buffer_with_stride` | `(&mut self, buffer: Option<&Buffer>, offset: u64, stride: u64, index: u32) -> Result<(), Error>` | R-B | `U` `KNOWN` |
| `setBufferOffset:atIndex:` | `v32@0:8Q16Q24` | `set_buffer_offset` | `(&mut self, offset: u64, index: u32) -> Result<(), Error>` | R-B | `U` `KNOWN` |
| `setBufferOffset:attributeStride:atIndex:` | `v40@0:8Q16Q24Q32` | `set_buffer_offset_with_stride` | `(&mut self, offset: u64, stride: u64, index: u32) -> Result<(), Error>` | R-B | `U` `KNOWN` |
| `setBuffers:offsets:withRange:` | `v48@0:8r^@16r^Q24{_NSRange=QQ}32` | `set_buffers` | `(&mut self, buffers: &[Option<&Buffer>], offsets: &[u64], first: u32) -> Result<(), Error>` | R-BA | `U` `KNOWN` |
| `setBuffers:offsets:attributeStrides:withRange:` | `v56@0:8r^@16r^Q24r^Q32{_NSRange=QQ}40` | `set_buffers_with_strides` | `(&mut self, buffers: &[Option<&Buffer>], offsets: &[u64], strides: &[u64], first: u32) -> Result<(), Error>` | R-BA | `U` `KNOWN` |
| `setTexture:atIndex:` | `v32@0:8@16Q24` | `set_texture` | `(&mut self, texture: Option<&Texture>, index: u32) -> Result<(), Error>` | R-T | `U` `KNOWN` |
| `setTextures:withRange:` | `v40@0:8r^@16{_NSRange=QQ}24` | `set_textures` | `(&mut self, textures: &[Option<&Texture>], first: u32) -> Result<(), Error>` | R-TA | `U` `KNOWN` |
| `setSamplerState:atIndex:` | `v32@0:8@16Q24` | `set_sampler_state` | `(&mut self, sampler: Option<&SamplerState>, index: u32) -> Result<(), Error>` | R-S | `U` `KNOWN` |
| `setSamplerState:lodMinClamp:lodMaxClamp:atIndex:` | `v40@0:8@16f24f28Q32` | `set_sampler_state_with_lod_clamps` | `(&mut self, sampler: Option<&SamplerState>, lod_min_clamp: f32, lod_max_clamp: f32, index: u32) -> Result<(), Error>` | **compute 侧有单项带 clamps 的方法，render 侧没有**（第 2.7 节）。两 clamp 过 R19 + R20 | `U` `KNOWN` |
| `setSamplerStates:withRange:` | `v40@0:8r^@16{_NSRange=QQ}24` | `set_sampler_states` | `(&mut self, samplers: &[Option<&SamplerState>], first: u32) -> Result<(), Error>` | R-S | `U` `KNOWN` |
| `setSamplerStates:lodMinClamps:lodMaxClamps:withRange:` | `v56@0:8r^@16r^f24r^f32{_NSRange=QQ}40` | `set_sampler_states_with_lod_clamps` | `(&mut self, samplers: &[Option<&SamplerState>], lod_min_clamps: &[f32], lod_max_clamps: &[f32], first: u32) -> Result<(), Error>` | **三个 slice 必须等长** | `U` `KNOWN` |
| `setThreadgroupMemoryLength:atIndex:` | `v32@0:8Q16Q24` | `set_threadgroup_memory_length` | `(&mut self, length: u32, index: u32) -> Result<(), Error>` | **`length` 是 `u32`，两参**（render 是 `u64` 三参，K-15） | `U` `KNOWN` |
| `setImageblockWidth:height:` | `v32@0:8Q16Q24` | `set_imageblock_size` | `(&mut self, width: u64, height: u64) -> Result<(), Error>` | 名字不机械（K-02 的反例之一） | `U` `KNOWN` |
| `setStageInRegion:` | `v64@0:8{?={?=QQQ}{?=QQQ}}16` | `set_stage_in_region` | `(&mut self, region: Region) -> Result<(), Error>` | K-10（嵌套 9 字段） | `U` `KNOWN` |
| `setStageInRegionWithIndirectBuffer:indirectBufferOffset:` | `v32@0:8@16Q24` | `set_stage_in_region_indirect` | `(&mut self, indirect_buffer: &Buffer, indirect_buffer_offset: u64) -> Result<(), Error>` | region 由 host step 读 | `U` `KNOWN` |
| `setVisibleFunctionTable:atBufferIndex:` | `v32@0:8@16Q24` | `set_visible_function_table` | `(&mut self, table: Option<&VisibleFunctionTable>, index: u32) -> Result<(), Error>` | 对象可建，表调用被拒 | `U` `KNOWN` |
| `setVisibleFunctionTables:withBufferRange:` | `v40@0:8r^@16{_NSRange=QQ}24` | `set_visible_function_tables` | `(&mut self, tables: &[Option<&VisibleFunctionTable>], first: u32) -> Result<(), Error>` | 同上 | `U` `KNOWN` |
| `updateFence:` | `v24@0:8@16` | `update_fence` | `(&mut self, fence: &Fence) -> Result<(), Error>` | R-F（**无 stages**，与 render 不同） | `U` `KNOWN` |
| `waitForFence:` | `v24@0:8@16` | `wait_for_fence` | `(&mut self, fence: &Fence) -> Result<(), Error>` | 同上 | `U` `KNOWN` |
| `memoryBarrierWithScope:` | `v24@0:8Q16` | `memory_barrier_with_scope` | `(&mut self, scope: BarrierScope)` | 不返回 `Result` | `U` `KNOWN` |
| `memoryBarrierWithResources:count:` | `v32@0:8r^@16Q24` | `memory_barrier_with_resources` | `(&mut self, resources: &[ResourceRef<'_>]) -> Result<(), Error>` | K-06 + K-07 | `U` `KNOWN` |
| `executeCommandsInBuffer:withRange:` | `v40@0:8@16{_NSRange=QQ}24` | `execute_commands_in_buffer`（另有 `_checked`） | `(&mut self, icb: &IndirectCommandBuffer, range: Range<u64>) -> Result<(), Error>` | K-08；**用 `_checked`** | `U` `KNOWN` |
| `executeCommandsInBuffer:indirectBuffer:indirectBufferOffset:` | `v40@0:8@16@24Q32` | `execute_commands_in_buffer_indirect`（另有 `_checked`） | `(&mut self, icb: &IndirectCommandBuffer, range_buffer: &Buffer, offset: u64) -> Result<(), Error>` | 同上 | `U` `KNOWN` |
| `useResource:usage:` | `—` | `use_resource` | `(&mut self, resource: ResourceRef<'_>, usage: ResourceUsage) -> Result<(), Error>` | R-U（**无 stages**） | `U` `KNOWN` |
| `useResources:count:usage:` | `—` | `use_resources` | `(&mut self, resources: &[ResourceRef<'_>], usage: ResourceUsage) -> Result<(), Error>` | R-U + K-07 | `U` `KNOWN` |
| `useHeap:` | `—` | `use_heap` | `(&mut self, heap: &Heap) -> Result<(), Error>` | R-U | `U` `KNOWN` |
| `useHeaps:count:` | `—` | `use_heaps` | `(&mut self, heaps: &[&Heap]) -> Result<(), Error>` | R-U | `U` `KNOWN` |
| `sampleCountersInBuffer:atSampleIndex:withBarrier:` | `v36@0:8@16Q24c32` | **无** | — | — | **`N-02`** `KNOWN` |
| `setAccelerationStructure:atBufferIndex:` | `v32@0:8@16Q24` | **无** | — | — | **`N-04`** `KNOWN` |
| `setIntersectionFunctionTable:atBufferIndex:` | `v32@0:8@16Q24` | **无** | — | — | **`N-04`** `KNOWN` |
| `setIntersectionFunctionTables:withBufferRange:` | `v40@0:8r^@16{_NSRange=QQ}24` | **无** | — | — | **`N-04`** `KNOWN` |

#### 5.5.1 `MTLComputeCommandEncoderSPI`：predication 全族（上游**有**完整实现）

`KNOWN`。`40` §3.2 已记「上游有完整实现」，本文补精确签名。这是上游最反直觉的一块：它实现了 Metal 的循环展开策略与未闭合块的行为。

| Metal selector（SPI） | enc（`21` A.2） | 上游调用（`rt::ComputeCommandEncoder::`） | 上游签名 | 语义要点 |
|---|---|---|---|---|
| `encodeStartIf:offset:comparison:referenceValue:` | `v44@0:8@16Q24Q32I40` | `encode_start_if` | `(&mut self, buffer: Option<&Buffer>, offset: u64, comparison: u64, reference_value: u32) -> Result<(), Error>` | 计数器由 runtime 的 step kernel 推进；**unit 结束时仍有打开的块 → 让命令缓冲失败（`PredicationOpenAtUnitEnd`）**；越过 buffer 的读按 Metal 读（heap 的字节或 0；读 0 时报通告） |
| `encodeStartElse` | `v16@0:8` | `encode_start_else` | `(&mut self) -> Result<(), Error>` | 无打开块时是不平衡记录，按 Metal 丢弃它覆盖的那段 unit 工作 |
| `encodeStartWhile:offset:comparison:referenceValue:` | `v44@0:8@16Q24Q32I40` | `encode_start_while` | `(&mut self, buffer: Option<&Buffer>, offset: u64, comparison: u64, reference_value: u32) -> Result<(), Error>` | 按 `encode_start_do_while` 的方式展开 |
| `encodeStartDoWhile` | `v16@0:8` | `encode_start_do_while` | `(&mut self) -> Result<(), Error>` | 展开为 **64 份**循环体（嵌套在另一循环内时 16 份，超过 16384 步或有门控 dispatch 时更少，至少 1 份），从循环停止处再提交直到结束；**无界循环跑到进程结束，与 Metal 一致** |
| `encodeEndIf` | `c16@0:8` | `encode_end_if` | `(&mut self) -> Result<bool, Error>` | **返回 `BOOL`**。无打开块时按 Metal 答 `NO`（**不是报错**，K-04 的特例） |
| `encodeEndWhile` | `c16@0:8` | `encode_end_while` | `(&mut self) -> Result<bool, Error>` | 同上 |
| `encodeEndDoWhile:offset:comparison:referenceValue:` | `c44@0:8@16Q24Q32I40` | `encode_end_do_while` | `(&mut self, buffer: Option<&Buffer>, offset: u64, comparison: u64, reference_value: u32) -> Result<bool, Error>` | 同上 |
| `insertCompressedTextureReinterpretationFlush` | `v16@0:8` | `insert_compressed_texture_reinterpretation_flush` | `(&mut self)` | no-op（Vulkan 不暴露压缩） |

> **三个返回 `BOOL` 的 selector 必须把 `Ok(false)` 映射成 `NO`，把 `Err` 也映射成 `NO`**（`INFERRED`）。理由：Metal 在这里从不报错，只答 `NO`；把 `Err` 变成 `YES` 会让客户端以为块闭合了。`Err` 的内容进日志。

### 5.6 `MTLBlitCommandEncoder`（24 required + 2 optional）

签名源：`crates/metal2vulkan-runtime/src/blit.rs:157`（`BlitCommandEncoder`，25 个公开方法）。encoding 源：`21` 附录 A.3。

分布：**`U` 21 / `N` 4 / `B` 1**。

| Metal selector | 上游调用（`rt::BlitCommandEncoder::`） | 上游签名 | 参 / 要点 | 标 |
|---|---|---|---|---|
| `copyFromBuffer:sourceOffset:toBuffer:destinationOffset:size:` | `copy_from_buffer_to_buffer` | `(&mut self, source_buffer: &Buffer, source_offset: u64, destination_buffer: &Buffer, destination_offset: u64, size: u64) -> Result<(), Error>` | K-06 ×2 | `U` `KNOWN` |
| `copyFromBuffer:sourceOffset:sourceBytesPerRow:sourceBytesPerImage:sourceSize:toTexture:destinationSlice:destinationLevel:destinationOrigin:` | `copy_from_buffer_to_texture` | `(&mut self, source_buffer: &Buffer, source_offset: u64, source_bytes_per_row: u64, source_bytes_per_image: u64, source_size: Size, destination_texture: &Texture, destination_slice: u64, destination_level: u64, destination_origin: Origin, ...)` | 最后一个参数是 `BlitOption`；无 options 形态传空 | `U` `KNOWN` `*(partial)*` |
| `copyFromBuffer:...destinationOrigin:options:` | 同上 | 同上 | `MTLBlitOption` → `BlitOption`（K-11） | `U` `KNOWN` `*(partial)*` |
| `copyFromTexture:sourceSlice:sourceLevel:sourceOrigin:sourceSize:toBuffer:destinationOffset:destinationBytesPerRow:destinationBytesPerImage:` | `copy_from_texture_to_buffer` | `(&mut self, source_texture: &Texture, source_slice: u64, source_level: u64, source_origin: Origin, source_size: Size, destination_buffer: &Buffer, destination_offset: u64, destination_bytes_per_row: u64, destination_bytes_per_image: u64, ...)` | K-10 ×2 | `U` `KNOWN` `*(partial)*` |
| `copyFromTexture:...destinationBytesPerImage:options:` | 同上 | 同上 | 同上 | `U` `KNOWN` `*(partial)*` |
| `copyFromTexture:sourceSlice:sourceLevel:sourceOrigin:sourceSize:toTexture:destinationSlice:destinationLevel:destinationOrigin:` | `copy_from_texture_to_texture` | `(&mut self, source_texture: &Texture, source_slice: u64, source_level: u64, source_origin: Origin, source_size: Size, destination_texture: &Texture, destination_slice: u64, destination_level: u64, destination_origin: Origin, ...)` | K-10 ×3 | `U` `KNOWN` `*(partial)*` |
| `copyFromTexture:sourceSlice:sourceLevel:toTexture:destinationSlice:destinationLevel:sliceCount:levelCount:` | `copy_texture_slices` | `(&mut self, source_texture: &Texture, source_slice: u64, source_level: u64, destination_texture: &Texture, destination_slice: u64, destination_level: u64, slice_count: u64, level_count: u64) -> Result<(), Error>` | — | `U` `KNOWN` `*(partial)*` |
| `copyFromTexture:toTexture:` | `copy_texture` | `(&mut self, source_texture: &Texture, destination_texture: &Texture) -> Result<(), Error>` | — | `U` `KNOWN` `*(partial)*` |
| `copyIndirectCommandBuffer:sourceRange:destination:destinationIndex:` | `copy_indirect_command_buffer` | `(&mut self, source: &IndirectCommandBuffer, source_range: Range<u64>, destination: &IndirectCommandBuffer, destination_index: u64) -> Result<(), Error>` | K-08 | `U` `KNOWN` |
| `fillBuffer:range:value:` | `fill_buffer` | `(&mut self, buffer: &Buffer, range: Range<u64>, value: u8) -> Result<(), Error>` | K-08；`value` 的 encoding 是 `C`（`uint8_t`） | `U` `KNOWN` |
| `generateMipmapsForTexture:` | `generate_mipmaps` | `(&mut self, texture: &Texture) -> Result<(), Error>` | — | `U` `KNOWN` `*(partial)*` |
| `optimizeContentsForCPUAccess:` | `optimize_contents_for_cpu_access` | `(&mut self, texture: &Texture) -> Result<(), Error>` | no-op（提示）→ ③ 档 | `U` `KNOWN` |
| `optimizeContentsForCPUAccess:slice:level:` | `optimize_contents_for_cpu_access_slice_level` | `(&mut self, texture: &Texture, slice: u64, level: u64) -> Result<(), Error>` | 同上 | `U` `KNOWN` |
| `optimizeContentsForGPUAccess:` | `optimize_contents_for_gpu_access` | `(&mut self, texture: &Texture) -> Result<(), Error>` | 同上 | `U` `KNOWN` |
| `optimizeContentsForGPUAccess:slice:level:` | `optimize_contents_for_gpu_access_slice_level` | `(&mut self, texture: &Texture, slice: u64, level: u64) -> Result<(), Error>` | 同上 | `U` `KNOWN` |
| `optimizeIndirectCommandBuffer:withRange:` | `optimize_indirect_command_buffer` | `(&mut self, buffer: &IndirectCommandBuffer, range: Range<u64>) -> Result<(), Error>` | K-08 | `U` `KNOWN` |
| `resetCommandsInBuffer:withRange:` | `reset_commands_in_buffer` | `(&mut self, buffer: &IndirectCommandBuffer, range: Range<u64>) -> Result<(), Error>` | K-08 | `U` `KNOWN` |
| `synchronizeResource:` | `synchronize_resource` | `(&mut self, resource: ResourceRef<'_>) -> Result<(), Error>` | K-06（managed storage） | `U` `KNOWN` |
| `synchronizeTexture:slice:level:` | `synchronize_texture` | `(&mut self, texture: &Texture, slice: u64, level: u64) -> Result<(), Error>` | — | `U` `KNOWN` |
| `updateFence:` | `update_fence` | `(&mut self, fence: &Fence) -> Result<(), Error>` | R-F | `U` `KNOWN` |
| `waitForFence:` | `wait_for_fence` | `(&mut self, fence: &Fence) -> Result<(), Error>` | R-F | `U` `KNOWN` |
| `resolveCounters:inRange:destinationBuffer:destinationOffset:` | **无** | — | — | **`N-02`** `KNOWN` |
| `sampleCountersInBuffer:atSampleIndex:withBarrier:` | **无** | — | — | **`N-02`** `KNOWN` |
| `getTextureAccessCounters:region:mipLevel:slice:resetCounters:countersBuffer:countersBufferOffset:`（opt） | **无** | — | — | **`N-02`** `KNOWN` |
| `resetTextureAccessCounters:region:mipLevel:slice:`（opt） | **无** | — | — | **`N-02`** `KNOWN` |
| 1 条 required 未在本仓库枚举 | — | — | — | **`B`**（`M-005`） |

#### 5.6.1 `MTLBlitCommandEncoderSPI`：上游**有**落点的 6 条

`KNOWN`。

| Metal selector（SPI） | 上游调用（`rt::BlitCommandEncoder::`） | 上游签名 | 语义要点 |
|---|---|---|---|
| `fillBuffer:range:pattern4:` | `fill_buffer_pattern4` | `(&mut self, buffer: &Buffer, range: Range<u64>, pattern: u32) -> Result<(), Error>` | — |
| `fillTexture:level:slice:region:bytes:length:` | `fill_texture` | `(&mut self, texture: &Texture, level: u64, slice: u64, region: Region, pattern: &[u8]) -> Result<(), Error>` | 每种纹理类型、每种格式、按 Metal 的摆放；**多采样纹理的每个采样各取 pattern 的自己那几个字节**；texture buffer 的 fill 写它的 buffer 字节（Metal 写的是它自己栈上的东西，我们写 0 并报 `texture-buffer-fill-leftover`） |
| `fillTexture:level:slice:region:color:` | `fill_texture_color` | `(&mut self, texture: &Texture, level: u64, slice: u64, region: Region, color: ClearColor, pixel_format: Option<PixelFormat>) -> Result<(), Error>` | `pixel_format = None`；`ClearColor` 是 4 个 `double`（K-10） |
| `fillTexture:level:slice:region:color:pixelFormat:` | 同上 | 同上 | `pixel_format = Some(..)`；normalized / sRGB / half / float / small-float 的普通 fill 走设备的 clear（可能报 `device-color-conversion`）；Metal 不打包的格式下的颜色会 fill 成命令缓冲最后打包的那个 texel（报 `unpacked-fill-color`） |
| `invalidateCompressedTexture:` | `invalidate_compressed_texture` | `(&mut self, texture: &Texture) -> Result<(), Error>` | no-op → ③ 档；另见 `AppleOnlyCall::InvalidateCompressedTexture` |
| `invalidateCompressedTexture:slice:level:` | `invalidate_compressed_texture_slice` | `(&mut self, texture: &Texture, slice: u64, level: u64) -> Result<(), Error>` | no-op |
| `copyFromTexture:...destinationOrigin:options:`（SPI 的带 options 纹理到纹理） | **组合** | `copy_from_texture_to_buffer` → `copy_from_buffer_to_texture` | **`C`**：options 为 0 时就是 `copy_from_texture_to_texture`；公开 `BlitOption` 非 0 时必须经一个中转 buffer（`40` §3.2 已记，上游「Composed from runtime calls」的第一行） |

### 5.7 `MTLBuffer`（11 required）

签名源：`crates/metal2vulkan-runtime/src/buffer.rs:63`（`Buffer`，25 个公开方法）。

| Metal selector | enc | 上游调用 | 上游签名 | 参 / 返 | 标 |
|---|---|---|---|---|---|
| `length` | `Q16@0:8` | `rt::Buffer::length` | `(&self) -> u64` | — | `U` `KNOWN` |
| `contents` | `^v16@0:8` | `rt::Buffer::contents` | `(&self) -> Option<NonNull<u8>>` | `None` → `NULL`（K-05；private storage 无 contents） | `U` `KNOWN` |
| `didModifyRange:` | `v32@0:8{_NSRange=QQ}16` | `rt::Buffer::did_modify_range` | `(&self, range: Range<u64>) -> Result<(), Error>` | K-08 | `U` `KNOWN` |
| `gpuAddress` | `Q16@0:8` | `rt::Buffer::gpu_address` | `(&self) -> GpuAddress` | 在 runtime 的 Metal 地址空间里；配 `AddressPlacement` pin（`22` §5.2） | `U` `KNOWN` |
| `newTextureWithDescriptor:offset:bytesPerRow:` | `@40@0:8@16Q24Q32` | `rt::Buffer::new_texture` | `(&self, descriptor: &TextureDescriptor, offset: u64, bytes_per_row: u64) -> Result<Texture, Error>` | descriptor snapshot；返回 +1 ObjC texture（K-12） | `U` `KNOWN` `*(partial)*` |
| `addDebugMarker:range:` | `v40@0:8@16{_NSRange=QQ}24` | **无** | — | 本地列表（R-G） | `L` `INFERRED` |
| `removeAllDebugMarkers` | `v16@0:8` | **无** | — | 清本地列表 | `L` `INFERRED` |
| `sparseBufferTier` | `q16@0:8` | **无** | — | `0`（sparse 不可用，`40` §2.2） | `L` `INFERRED` |
| `newRemoteBufferViewForDevice:` | `@24@0:8@16` | **无** | — | `nil`（单设备，`peerCount` = 0） | `L` `INFERRED` |
| `remoteStorageBuffer` | `@16@0:8` | **无** | — | `nil`（同上） | `L` `INFERRED` |
| `newTensorWithDescriptor:offset:error:` | `@40@0:8@16Q24^@32` | **无** | — | `nil` + `NSError` | **`N-11`** `KNOWN` |

#### 5.7.1 `Buffer` 的 runtime 扩展与 SPI 落点（`KNOWN`）

| 上游 | 签名 | 对应 Metal | 用途 |
|---|---|---|---|
| `rt::Buffer::new_linear_texture` | `(&self, descriptor: &TextureDescriptor, offset: u64, bytes_per_row: u64, _bytes_per_image: u64) -> Result<Texture, Error>` | `newLinearTextureWithDescriptor:offset:bytesPerRow:bytesPerImage:`（SPI） | 别名 image，或 Vulkan 不能别名时的 shadow image。`*(partial)*` |
| `rt::Buffer::new_texture_with_iosurface_plane` | `(&self, descriptor: &TextureDescriptor, plane: IoSurfacePlane) -> Result<Texture, Error>` | 无（`GpuDevice::new_texture_on_surface` 的组合件） | **IOSurface 桥的核心**（`41` 分册）。注意：`Buffer::new_texture` 走 buffer 规则，会拒绝 Metal 接受的非 16 对齐的 surface plane 行距；必须走这条 |
| `rt::Buffer::host_backing` | `(&self) -> Option<HostBacking>` | 无 | 现在 GPU 实际用的是哪种后备（指针导入 / dma-buf / guest RAM 块 / 拷贝）。能力报告必须记 |
| `rt::Buffer::detach_backing` | `(&self) -> Result<bool, Error>` | `detachBacking`（SPI） | `40` §4 第 2 项。返回「这次真的分离了吗」，必须原样答（第 3.6 节） |
| `rt::Buffer::rebind_bytes_no_copy` | `unsafe (&self, memory: HostMemory, deallocator: Option<Deallocator>, keep_alive: Option<KeepAlive>) -> Result<(), Error>` | `replaceBackingWithRanges:`（SPI）的落点 | 同长度的另一段内存，同对象同 GPU 地址，按 commit 顺序；未提交的工作或打开的编码器用过它们 → `RebindProblem::EncodedUses`（render 编码器从打开起就算用了它的 attachment 字节） |
| `rt::Buffer::vk_buffer` | `unsafe (&self) -> (vk::Buffer, u64)` | 无 | 直接触碰 Vulkan 对象 |
| `rt::Buffer::object_id` | `(&self) -> ObjectId` | 无（Metal 用指针标识） | 对象表的键（K-06） |
| `rt::Buffer::as_resource` | `(&self) -> ResourceRef<'_>` | 无 | `useResource:` 等的参数（K-06） |

### 5.8 `MTLTexture`（36 required + 3 optional）

签名源：`crates/metal2vulkan-runtime/src/texture.rs:393`（`Texture`，50 个公开方法）。

分布：**`U` 26 / `C` 3 / `L` 8 / `S4-1` 2**。**零 `N`**：纹理面是本文覆盖率最高的对象。

| Metal selector | enc | 上游调用（`rt::Texture::`） | 上游签名 | 参 / 返 | 标 |
|---|---|---|---|---|---|
| `width` | `Q16@0:8` | `width` | `(&self) -> u64` | — | `U` `KNOWN` |
| `height` | `Q16@0:8` | `height` | `(&self) -> u64` | — | `U` `KNOWN` |
| `depth` | `Q16@0:8` | `depth` | `(&self) -> u64` | — | `U` `KNOWN` |
| `arrayLength` | `Q16@0:8` | `array_length` | `(&self) -> u64` | — | `U` `KNOWN` |
| `mipmapLevelCount` | `Q16@0:8` | `mipmap_level_count` | `(&self) -> u64` | — | `U` `KNOWN` |
| `sampleCount` | `Q16@0:8` | `sample_count` | `(&self) -> u64` | — | `U` `KNOWN` |
| `pixelFormat` | `Q16@0:8` | `pixel_format` | `(&self) -> PixelFormat` | → raw（`40` §8） | `U` `KNOWN` |
| `textureType` | `Q16@0:8` | `texture_type` | `(&self) -> TextureType` | → raw | `U` `KNOWN` |
| `usage` | `Q16@0:8` | `usage` | `(&self) -> TextureUsage` | → raw flag word | `U` `KNOWN` |
| `swizzle` | `{?=CCCC}16@0:8` | `swizzle` | `(&self) -> TextureSwizzleChannels` | 4 个 `unsigned char` | `U` `KNOWN` |
| `isFramebufferOnly` | `c16@0:8` | `framebuffer_only` | `(&self) -> bool` | 名字不机械（K-02） | `U` `KNOWN` |
| `isShareable` | `c16@0:8` | `is_shareable` | `(&self) -> bool` | — | `U` `KNOWN` |
| `allowGPUOptimizedContents` | `c16@0:8` | `allow_gpu_optimized_contents` | `(&self) -> bool` | — | `U` `KNOWN` |
| `gpuResourceID` | `{MTLResourceID=Q}16@0:8` | `gpu_resource_id` | `(&self) -> ResourceId` | `ResourceId` → `MTLResourceID`（单字段结构） | `U` `KNOWN` |
| `parentTexture` | `@16@0:8` | `parent_texture` | `(&self) -> Option<&Texture>` | K-05；经对象表换回 ObjC 对象 | `U` `KNOWN` |
| `parentRelativeLevel` | `Q16@0:8` | `parent_relative_level` | `(&self) -> u64` | — | `U` `KNOWN` |
| `parentRelativeSlice` | `Q16@0:8` | `parent_relative_slice` | `(&self) -> u64` | — | `U` `KNOWN` |
| `newSharedTextureHandle` | `@16@0:8` | `new_shared_texture_handle` | `(&self) -> Result<SharedTextureHandle, Error>` | **仅进程内**；跨进程序列化是本项目的（`S4-6`） | `U` `KNOWN` `*(partial)*` |
| `newTextureViewWithPixelFormat:` | `@24@0:8Q16` | `new_texture_view` | `(&self, pixel_format: PixelFormat) -> Result<Texture, Error>` | 返回 +1 | `U` `KNOWN` |
| `newTextureViewWithPixelFormat:textureType:levels:slices:` | `@64@0:8Q16Q24{_NSRange=QQ}32{_NSRange=QQ}48` | `new_texture_view_with_levels_slices` | `(&self, pixel_format: PixelFormat, texture_type: TextureType, levels: Range<u64>, slices: Range<u64>) -> Result<Texture, Error>` | K-08 ×2 | `U` `KNOWN` |
| `newTextureViewWithPixelFormat:textureType:levels:slices:swizzle:` | `@68@0:8Q16Q24{_NSRange=QQ}32{_NSRange=QQ}48{?=CCCC}64` | `new_texture_view_with_swizzle` | `(&self, pixel_format: PixelFormat, texture_type: TextureType, levels: Range<u64>, slices: Range<u64>, swizzle: TextureSwizzleChannels) -> Result<Texture, Error>` | K-08 ×2 + K-10 | `U` `KNOWN` |
| `replaceRegion:mipmapLevel:slice:withBytes:bytesPerRow:bytesPerImage:` | `v104@0:8{?={?=QQQ}{?=QQQ}}16Q64Q72r^v80Q88Q96` | `replace_region` | `(&self, region: Region, level: u64, slice: u64, bytes: &[u8], bytes_per_row: u64, bytes_per_image: u64) -> Result<(), Error>` | K-10；**guest 内存走 `replace_region_with_host_bytes`**（见下） | `U` `KNOWN` |
| `replaceRegion:mipmapLevel:withBytes:bytesPerRow:` | `v88@0:8{?={?=QQQ}{?=QQQ}}16Q64r^v72Q80` | `replace_region` | 同上 | `slice = 0`、`bytes_per_image = 0` | **`C`** `KNOWN` |
| `getBytes:bytesPerRow:bytesPerImage:fromRegion:mipmapLevel:slice:` | `v104@0:8^v16Q24Q32{?={?=QQQ}{?=QQQ}}40Q88Q96` | `get_bytes` | `(&self, bytes: &mut [u8], bytes_per_row: u64, bytes_per_image: u64, region: Region, level: u64, slice: u64) -> Result<(), Error>` | 出参缓冲长度必须按 `22` R17 的 checked 乘加算 | `U` `KNOWN` |
| `getBytes:bytesPerRow:fromRegion:mipmapLevel:` | `v88@0:8^v16Q24{?={?=QQQ}{?=QQQ}}32Q80` | `get_bytes` | 同上 | `slice = 0`、`bytes_per_image = 0` | **`C`** `KNOWN` |
| `newTextureViewWithDescriptor:` | `@24@0:8@16` | **组合** | `new_texture_view*` 四件套 | **`C`**：拆 `MTLTextureViewDescriptor`（`22` §5.3 记 `BLOCKED(调用名)`，**本文关闭**：落点就是 `new_texture_view` / `_with_levels_slices` / `_with_swizzle` / `_with_placement`，按 descriptor 里设了哪些字段选) | **`C`** `KNOWN` |
| `tailSizeInBytes`（opt） | `Q16@0:8` | `tail_size_in_bytes` | `(&self) -> Option<u64>` | `None` → 0 | `U` `KNOWN` |
| `firstMipmapInTail`（opt） | `Q16@0:8` | `first_mipmap_in_tail` | `(&self) -> Option<u64>` | `None` → 0 | `U` `KNOWN` |
| `isSparse`（opt） | `c16@0:8` | `is_sparse` | `(&self) -> bool` | — | `U` `KNOWN` |
| `iosurface` | `^{__IOSurface=}16@0:8` | **无**（上游范围外） | — | 本项目的 IOSurface 对象 | `S4-1` `KNOWN` |
| `iosurfacePlane` | `Q16@0:8` | **无** | — | 同上 | `S4-1` `KNOWN` |
| `buffer` | `@16@0:8` | **无 getter** | — | 本地：创建时就知道它建在哪个 buffer 上 | `L` `INFERRED` |
| `bufferOffset` | `Q16@0:8` | **无 getter** | — | 本地（创建参数） | `L` `INFERRED` |
| `bufferBytesPerRow` | `Q16@0:8` | **无 getter** | — | 本地（创建参数） | `L` `INFERRED` |
| `rootResource` | `@16@0:8` | **无 getter** | — | 本地：view 链的根由本项目维护 | `L` `INFERRED` |
| `compressionType` | `q16@0:8` | **无 getter** | — | 本地：返回声明值（`22` R24 + C 档） | `L` `INFERRED` |
| `sparseTextureTier` | `q16@0:8` | **无 getter** | — | `0` | `L` `INFERRED` |
| `newRemoteTextureViewForDevice:` | `@24@0:8@16` | **无** | — | `nil` | `L` `INFERRED` |
| `remoteStorageTexture` | `@16@0:8` | **无** | — | `nil` | `L` `INFERRED` |

#### 5.8.1 `Texture` 的 runtime 扩展与 SPI 落点（`KNOWN`）

| 上游 | 签名 | 对应 Metal | 要点 |
|---|---|---|---|
| `rt::Texture::replace_region_with_host_bytes` | `(&self, region: Region, level: u64, slice: u64, bytes: HostBytes<'_>, bytes_per_row: u64, bytes_per_image: u64) -> Result<(), Error>` | `replaceRegion:...` 的 guest 内存形态 | **读取过程中可能变化的内存（guest 的）必须走这条**：调用经指针拷一次，不先拷调用方的。`HostBytes::new(pointer, length)` 是 `unsafe` |
| `rt::Texture::new_texture_view_with_placement` | `(&self, pixel_format: PixelFormat, placement: IdPlacement) -> Result<Texture, Error>` | `newTextureViewWithPixelFormat:resourceIndex:`（SPI） | `IdPlacement` 来自 `22` R25 |
| `rt::Texture::new_texture_subview_with_placement` | `(&self, pixel_format: PixelFormat, texture_type: TextureType, levels: Range<u64>, slices: Range<u64>, swizzle: Option<TextureSwizzleChannels>, placement: IdPlacement) -> Result<Texture, Error>` | `newTextureViewWithPixelFormat:textureType:levels:slices:swizzle:resourceIndex:`（SPI）与无 swizzle 的变体 | swizzle 为 `Option`，两个 SPI 变体共用这一个方法 |
| `rt::Texture::rotation` | `(&self) -> u64` | `rotation`（SPI） | 0–4，IOSurface plane 专用；必须与 `framebuffer_only` 同设（`22` §3.7） |
| `rt::Texture::protection_options` | `(&self) -> u64` | `protectionOptions`（SPI） | **总是 0** |
| `rt::Texture::address_mode_map` | `(&self) -> AddressModeMap` | 无（runtime 扩展） | 把纹理按别的 address mode 呈现；YCbCr 两 plane 路径可能需要（`22` §5.4） |
| `rt::Texture::alpha_reads_one` | `(&self) -> bool` | 无 | RGBX 族（`40` §8.2.6）的 alpha 行为 |
| `rt::Texture::is_drawable` | `(&self) -> bool` | 无 | 与 `MTLDrawable`（`S4-4`）相关 |
| `rt::Texture::allocated_size` | `(&self) -> Option<u64>` | `allocatedSize`（`MTLAllocation`） | **`Option`**：答不出时 `None`，本项目必须补一个有依据的值 |
| `rt::Texture::vk_image` | `unsafe (&self) -> Option<vk::Image>` | 无 | IOSurface 桥 |

### 5.9 `MTLResource`（14）与 `MTLResourceSPI`（12 + 1）

`MTLResource` 的方法在上游分散在 `Buffer` / `Texture` / `Heap` / `IndirectCommandBuffer` / `VisibleFunctionTable` 上（上游没有统一的 `Resource` trait 对象）。下表的「上游调用」列写 `{Buffer,Texture,...}::x` 表示同名方法在各接收者上都有。

#### 5.9.1 `MTLResource`（14 required）

| Metal selector | enc | 上游调用 | 上游签名 | 标 |
|---|---|---|---|---|
| `label` | `@16@0:8` | `{Buffer,Texture,Heap,IndirectCommandBuffer,VisibleFunctionTable}::label` | `(&self) -> Option<String>` | `U` `KNOWN` |
| `setLabel:` | `v24@0:8@16` | 同上 `::set_label` | `(&self, label: &str)` | `U` `KNOWN` |
| `device` | `@16@0:8` | 同上 `::device` | `(&self) -> &Device` | `U` `KNOWN` |
| `resourceOptions` | `Q16@0:8` | 同上 `::resource_options` | `(&self) -> ResourceOptions` | `U` `KNOWN`；**按 `22` R24 答声明值，不答归一化值** |
| `storageMode` | `Q16@0:8` | 同上 `::storage_mode` | `(&self) -> StorageMode` | `U` `KNOWN`；同上 |
| `cpuCacheMode` | `Q16@0:8` | 同上 `::cpu_cache_mode` | `(&self) -> CpuCacheMode` | `U` `KNOWN` |
| `hazardTrackingMode` | `Q16@0:8` | 同上 `::hazard_tracking_mode` | `(&self) -> HazardTrackingMode` | `U` `KNOWN` |
| `heap` | `@16@0:8` | `{Buffer,Texture,IndirectCommandBuffer,VisibleFunctionTable}::heap` | `(&self) -> Option<&Heap>` | `U` `KNOWN` |
| `heapOffset` | `Q16@0:8` | 同上 `::heap_offset` | `(&self) -> u64` | `U` `KNOWN` |
| `isAliasable` | `c16@0:8` | `{Buffer,Texture,IndirectCommandBuffer,VisibleFunctionTable}::is_aliasable` | `(&self) -> bool` | `U` `KNOWN` |
| `makeAliasable` | `v16@0:8` | `{Buffer,Texture}::make_aliasable` | `(&self) -> Result<(), Error>` | `U` `KNOWN` |
| `setPurgeableState:` | `Q24@0:8Q16` | `{Buffer,Texture,Heap,IndirectCommandBuffer}::set_purgeable_state` | `(&self, state: PurgeableState) -> Result<PurgeableState, Error>` | `U` `KNOWN`：**返回旧状态**；16 KiB 起或可共享纹理保留状态；**heap 里的资源被拒**。`VisibleFunctionTable::set_purgeable_state` 不返回 `Result` |
| `allocatedSize` | `Q16@0:8` | `Texture::allocated_size` / `IndirectCommandBuffer::allocated_size` / `VisibleFunctionTable::allocated_size`；**`Buffer` 无** | `(&self) -> Option<u64>` / `(&self) -> u64` | **`C`** `KNOWN`：buffer 用 `length()` 按分配粒度上舍入；texture 的 `None` 必须补值 |
| `setOwnerWithIdentity:` | `i20@0:8I16` | **无** | — | **`N-03`** `KNOWN` |

#### 5.9.2 `MTLResourceSPI`（12 required + 1 optional）

**这一节是本文发现的最密集的 gap 簇：13 条里 8 条无上游落点，而 APV 实现了其中 6 条。** `KNOWN`

| Metal selector | enc | APV（`21` §8.1.8） | 上游调用 | 本项目回答 | 标 |
|---|---|---|---|---|---|
| `protectionOptions` | `Q16@0:8` | — 继承 | `rt::Texture::protection_options` | 总是 0；buffer 侧本地答 0 | `U` `KNOWN` |
| `allocationID` | `Q16@0:8` | — 继承 | **无** | 本地：用我们自己的 `ObjectId`（终身唯一，K-06） | `L` `INFERRED` |
| `responsibleProcess` | `i16@0:8` | — 继承 | **无** | 本地：helper 的 pid 或 guest 侧的归属 pid（`50` 分册） | `L` `INFERRED` |
| `setResponsibleProcess:` | `v20@0:8i16` | — 继承 | **无** | 本地存 | `L` `INFERRED` |
| `unfilteredResourceOptions` | `Q16@0:8` | — 继承 | **无** | 本地：声明值（`22` R24 的「声明值」正是它） | `L` `INFERRED` |
| `doesAliasResource:` | `c24@0:8@16` | **实现**（texture +0x89B5 / buffer +0x15760） | **无** | 需自建 aliasing 关系表 | **`N-03`** `KNOWN` |
| `doesAliasAllResources:count:` | `c32@0:8r^@16Q24` | **实现** | **无** | 同上 | **`N-03`** `KNOWN` |
| `doesAliasAnyResources:count:` | `c32@0:8r^@16Q24` | **实现** | **无** | 同上 | **`N-03`** `KNOWN` |
| `isComplete` | `c16@0:8` | **实现**（buffer +0x15768） | **无**（只有 `CommandBuffer::status`） | 由「用到该资源的命令缓冲是否全部完成」推：`CommandBuffer::uses(&[object_id])` 遍历在飞的命令缓冲 | **`N-03`** `KNOWN` |
| `isWriteComplete` | `c16@0:8` | — 继承 | **无** | 同上，但只看写用途 | **`N-03`** `KNOWN` |
| `waitUntilComplete` | `v16@0:8` | **实现**（buffer +0x15778） | **无** | 对每个用到它的在飞命令缓冲调 `wait_until_completed_for`（**必须带超时**，否则违反 `40` §5 的不挂住要求） | **`N-03`** `KNOWN` |
| `isPurgeable` | `c16@0:8` | **实现**（buffer +0x15770） | **无查询**（`set_purgeable_state` 返回旧值但没有只读查询） | 本地：缓存最后一次 `set_purgeable_state` 的返回值 | **`N-03`** `KNOWN` |
| `setOwnerWithIdentity:`（opt） | `i20@0:8I16` | — 继承 | **无** | 本地存，返回 0（成功） | **`N-03`** `KNOWN` |

> `isComplete` / `waitUntilComplete` / `doesAlias*` 这一簇是**可以用上游基元自己拼出来的**（`CommandBuffer::uses`、`encoders_use`、`used_resources` 都是公开的），所以 `N-03` 的性质是「本项目要写一层资源在飞账本」，不是「上游缺了不可替代的东西」。但它不在 `40` 第 4 节的十项里，所以没人被分配这项工作。第 7 节据此定处置。`INFERRED`

### 5.10 `MTLHeap`（21）

签名源：`crates/metal2vulkan-runtime/src/heap.rs:274`（`Heap`，21 个公开方法）。左侧 selector 名按 Metal 公开 API，encoding 记 `M-006`（`B`）。

| Metal selector | 上游调用（`rt::Heap::`） | 上游签名 | 标 |
|---|---|---|---|
| `label` / `setLabel:` | `label` / `set_label` | `(&self) -> Option<String>` / `(&self, label: &str)` | `U` `KNOWN` |
| `device` | `device` | `(&self) -> &Device` | `U` `KNOWN` |
| `storageMode` | `storage_mode` | `(&self) -> StorageMode` | `U` `KNOWN` |
| `cpuCacheMode` | `cpu_cache_mode` | `(&self) -> CpuCacheMode` | `U` `KNOWN` |
| `hazardTrackingMode` | `hazard_tracking_mode` | `(&self) -> HazardTrackingMode` | `U` `KNOWN` |
| `resourceOptions` | `resource_options` | `(&self) -> ResourceOptions` | `U` `KNOWN` |
| `type` | `heap_type` | `(&self) -> HeapType` | `U` `KNOWN` |
| `size` | `size` | `(&self) -> u64` | `U` `KNOWN` |
| `usedSize` | `used_size` | `(&self) -> u64` | `U` `KNOWN` |
| `currentAllocatedSize` | `current_allocated_size` | `(&self) -> u64` | `U` `KNOWN` |
| `maxAvailableSizeWithAlignment:` | `max_available_size` | `(&self, alignment: u64) -> Result<u64, Error>` | `U` `KNOWN` |
| `setPurgeableState:` | `set_purgeable_state` | `(&self, state: PurgeableState) -> Result<PurgeableState, Error>` | `U` `KNOWN` |
| `newBufferWithLength:options:` | `new_buffer` | `(&self, length: u64, options: ResourceOptions) -> Result<Buffer, Error>` | `U` `KNOWN` |
| `newBufferWithLength:options:offset:` | `new_buffer_at_offset` | `(&self, length: u64, options: ResourceOptions, offset: u64) -> Result<Buffer, Error>` | `U` `KNOWN`（placement heap） |
| `newTextureWithDescriptor:` | `new_texture` | `(&self, descriptor: &TextureDescriptor) -> Result<Texture, Error>` | `U` `KNOWN` |
| `newTextureWithDescriptor:offset:` | `new_texture_at_offset` | `(&self, descriptor: &TextureDescriptor, offset: u64) -> Result<Texture, Error>` | `U` `KNOWN` |
| `newAccelerationStructureWithSize:` | **无** | — | **`N-04`** `KNOWN` |
| `newAccelerationStructureWithSize:offset:` | **无** | — | **`N-04`** `KNOWN` |
| `newAccelerationStructureWithDescriptor:` | **无** | — | **`N-04`** `KNOWN` |
| `newAccelerationStructureWithDescriptor:offset:` | **无** | — | **`N-04`** `KNOWN` |

`Heap` 的其余 runtime 扩展（`KNOWN`）：`gpu_address() -> GpuAddress`（对应 `gpuAddress` SPI；**sparse heap 的 gpu_address 是 0**）、`object_id() -> ObjectId`、`detach_backing() -> Result<bool, Error>`、`rebind_bytes_no_copy(unsafe)`。

**第一版的取舍**（`INFERRED`，依据 `21` §4.2）：APV 的 `supportsResourceHeaps` 返回 0 且 `newHeapWithDescriptor:` 返回 nil。本项目**第一版照 APV 关闭 heap**，但 `MTLHeap` 协议的 21 条仍按上表实现（因为上游 17 条有落点，成本低），只是 `MTLDevice::newHeapWithDescriptor:` 先返回 nil。打开 heap 的前置条件是 `RuntimeGap::ResourceHeap` 与 `HeapPastMaxBufferSize` 两条在目标 guest 上不触发（`maxBufferLength` 实测 1 GiB，`91` §2.1）。

---

### 5.11 `MTLLibrary`（14 required）

签名源：`crates/metal2vulkan-runtime/src/library.rs:33`（`Library`，8 个公开方法）。

`21` §8.1 的读法 1：**APV 对这 14 条一条未实现**（无适配类），全部由 `_MTLLibrary` 提供。本项目若照 APV 不建 library 类，这 14 条就不需要写；但 `21` §10 的建议是不建类。**本节仍给全量映射**，因为一旦需要自建 library 对象（例如为了接我们自己的 metallib 解析，`30` / `32` 分册），落点就要现成。

| Metal selector | enc | 上游调用（`rt::Library::`） | 上游签名 | 标 |
|---|---|---|---|---|
| `functionNames` | `@16@0:8` | `function_names` | `(&self) -> Vec<String>` | `U` `KNOWN` |
| `newFunctionWithName:` | `@24@0:8@16` | `new_function_with_name` | `(&self, name: &str) -> Result<Function, Error>` | `U` `KNOWN` |
| `newFunctionWithName:constantValues:error:` | `@40@0:8@16@24^@32` | `new_function_with_name_constant_values` | `(&self, name: &str, constants: &FunctionConstantValues) -> Result<Function, Error>` | `U` `KNOWN`。`FunctionConstantValues` 在 `crates/metal2vulkan/src/library/function.rs:704`（**跨 crate**） |
| `newFunctionWithDescriptor:error:` | `@32@0:8@16^@24` | `new_function_with_descriptor` | `(&self, descriptor: &FunctionDescriptor) -> Result<Function, Error>` | `U` `KNOWN`。注意有两个 `FunctionDescriptor`：`metal2vulkan-runtime/src/library.rs:100` 与 `metal2vulkan/src/pipeline/descriptor.rs:22`。**这里用 runtime 的那个** |
| `reflectionForFunctionWithName:` | `@24@0:8@16` | `reflection_for_function_with_name` | `(&self, name: &str) -> Result<Option<FunctionReflection>, Error>` | `U` `KNOWN` |
| `installName` | `@16@0:8` | `install_name` | `(&self) -> Option<&str>` | `U` `KNOWN` |
| `type` | `q16@0:8` | `library_type` | `(&self) -> LibraryType` | `U` `KNOWN`（名字不机械，K-02） |
| `device` | `@16@0:8` | `device` | `(&self) -> &Device` | `U` `KNOWN` |
| `label` | `@16@0:8` | **无**（上游 `Library` 没有 label） | — | `L` `KNOWN`（8 个公开方法里零命中） |
| `setLabel:` | `v24@0:8@16` | **无** | — | `L` `KNOWN` |
| `newFunctionWithName:constantValues:completionHandler:` | `v40@0:8@16@24@?32` | `new_function_with_name_constant_values` | K-13（自建线程 + 同步调用） | **`C`** `INFERRED` |
| `newFunctionWithDescriptor:completionHandler:` | `v32@0:8@16@?24` | `new_function_with_descriptor` | K-13 | **`C`** `INFERRED` |
| `newIntersectionFunctionWithDescriptor:error:` | `@32@0:8@16^@24` | **无** | — | **`N-04`** `KNOWN` |
| `newIntersectionFunctionWithDescriptor:completionHandler:` | `v32@0:8@16@?24` | **无** | — | **`N-04`** `KNOWN` |

**library 创建侧的两条承重事实**（`KNOWN`）：

| 上游 | 签名 | 要点 |
|---|---|---|
| `rt::Device::new_library_with_data` | `(&self, data: &[u8]) -> Result<Library, Error>` | **只接受 metallib**。裸 AIR 必须先过 `metal2vulkan::library::Library::from_air`（`40` §2.4）。另：它读**任何 Apple 平台**的 metallib（上游「Composed from runtime calls」的 `GpuDevice::allow_foreign_libraries` 行：无需额外调用） |
| `rt::Device::new_library_with_compile_library` | `(&self, library: metal2vulkan::library::Library) -> Library` | **不返回 `Result`**。这是把翻译器侧已解析好的 library 交给 runtime 的入口，`30` / `32` 分册的 AIR 路径落在这里 |
| `rt::Device::new_library_with_source` | `(&self, _source: &str) -> Result<Library, Error>` | 存在但**上游无 MSL 前端**，必然 `Err`。参数名带下划线前缀即是信号。见 `N-13` |

### 5.12 `MTLFunction`（13）与 `MTLFunctionSPI`（23）

#### 5.12.1 `MTLFunction`（13 required）

签名源：`library.rs:55`（`Function`，12 个公开方法）。`21` §8.1.10：**APV 全部 13 条都实现**（在 `AppleParavirtContainerFunction` 上），是唯一 100% 自实现的协议。

| Metal selector | enc | 上游调用（`rt::Function::`） | 上游签名 | 标 |
|---|---|---|---|---|
| `name` | `@16@0:8` | `name` | `(&self) -> &str` | `U` `KNOWN` |
| `functionType` | `Q16@0:8` | `function_type` | `(&self) -> Result<FunctionType, Error>` | `U` `KNOWN` |
| `options` | `Q16@0:8` | `options` | `(&self) -> FunctionOptions` | `U` `KNOWN` |
| `device` | `@16@0:8` | `device` | `(&self) -> &Device` | `U` `KNOWN` |
| `functionConstantsDictionary` | `@16@0:8` | `function_constants_dictionary` | `(&self) -> Result<BTreeMap<String, FunctionConstant>, Error>` | `U` `KNOWN`：`BTreeMap` → `NSDictionary`（键序无关） |
| `patchType` | `Q16@0:8` | `patch_type` | `(&self) -> Result<PatchType, Error>` | `U` `KNOWN` |
| `patchControlPointCount` | `q16@0:8` | `patch_control_point_count` | `(&self) -> Result<Option<u32>, Error>` | `U` `KNOWN`：**`None` → `-1`**（encoding 是 `q`，K-05 的正例） |
| `vertexAttributes` | `@16@0:8` | `vertex_attributes` | `(&self) -> Result<Option<Vec<Attribute>>, Error>` | `U` `KNOWN`：`None` → nil，`Some(v)` → `NSArray<MTLVertexAttribute *>` |
| `stageInputAttributes` | `@16@0:8` | `stage_input_attributes` | `(&self) -> Result<Option<Vec<Attribute>>, Error>` | `U` `KNOWN` |
| `newArgumentEncoderWithBufferIndex:` | `@24@0:8Q16` | `new_argument_encoder_with_buffer_index` | `(&self, index: u32) -> Result<ArgumentEncoder, Error>` | `U` `KNOWN` |
| `newArgumentEncoderWithBufferIndex:reflection:` | `@32@0:8Q16^@24` | `new_argument_encoder_with_buffer_index` + `ArgumentEncoder::layout` | `layout(&self) -> &ArgumentBufferLayout` | **`C`** `KNOWN`：上游无带 reflection 出参的变体；`reflection` 出参由 `layout()` 构造 `MTLArgument` 数组 |
| `label` | `@16@0:8` | **无** | — | `L` `KNOWN` |
| `setLabel:` | `v24@0:8@16` | **无** | — | `L` `KNOWN` |

`Function` 的另两个公开方法（Metal 无对应 selector，`KNOWN`）：`function_descriptor(&self) -> StageFunction`、`linked_function(&self) -> LinkedFunction`。前者是把 function 放进 pipeline descriptor 的 stage 槽位时用的值，**管线创建路径必须用它**（`31-PIPELINE-ARTIFACT.md` 的消费契约）。

#### 5.12.2 `MTLFunctionSPI`（23 required）

`B`：逐条未枚举（`M-004`）。两组 + 规则（`INFERRED` 分组；`KNOWN` 上游侧）：

| 组 | 判定 | 规则 | `U` 估计 |
|---|---|---|---|
| 函数元数据与反射 | `*Attributes*`、`*Reflection*`、`*ConstantValues*`、`*Type`、`*Name`、`*Hash*` | 多数可由 `Function` 的 12 个公开方法 + `Library::reflection_for_function_with_name` 答出 → `U` / `C` | ~4 |
| 函数指针 / 可见函数表 / 链接 | `*FunctionHandle*`、`*VisibleFunctionTable*`、`*DynamicLibrar*`、`*Linked*` | 对象可建、调用被拒（`40` §2.4）。落点在 `ComputePipelineState::function_handle` / `RenderPipelineState::function_handle` | ~2 |

### 5.13 `MTLRenderPipelineState`（26 required）

签名源：`crates/metal2vulkan-runtime/src/pipeline/render.rs:100`（`RenderPipelineState`，30 个公开方法）。`21` §8.7：**APV 实现 0 条**，全由 `_MTLRenderPipelineState` 提供。

分布：**`U` 13 / `L` 1 / `S4-3` 1 / `N-05` 11**。这是**除 `MTLResourceSPI` 外落点率最低的承重协议**（50%）。

| Metal selector | enc | 上游调用（`rt::RenderPipelineState::`） | 上游签名 | 标 |
|---|---|---|---|---|
| `label` | `@16@0:8` | `label` | `(&self) -> Option<&str>` | `U` `KNOWN` |
| `device` | `@16@0:8` | `device` | `(&self) -> &Device` | `U` `KNOWN` |
| `gpuResourceID` | `{MTLResourceID=Q}16@0:8` | `gpu_resource_id` | `(&self) -> ResourceId` | `U` `KNOWN` |
| `maxTotalThreadsPerThreadgroup` | `Q16@0:8` | `max_total_threads_per_threadgroup` | `(&self) -> u32` | `U` `KNOWN` |
| `imageblockMemoryLengthForDimensions:` | `Q40@0:8{?=QQQ}16` | `imageblock_memory_length_for_dimensions` | `(&self, dimensions: Size) -> Result<u64, Error>` | `U` `KNOWN` |
| `imageblockSampleLength` | `Q16@0:8` | `imageblock_sample_length` | `(&self) -> Result<u64, Error>` | `U` `KNOWN` |
| `supportIndirectCommandBuffers` | `c16@0:8` | `support_indirect_command_buffers` | `(&self) -> bool` | `U` `KNOWN` |
| `threadgroupSizeMatchesTileSize` | `c16@0:8` | `threadgroup_size_matches_tile_size` | `(&self) -> bool` | `U` `KNOWN` |
| `reflection` | `@16@0:8` | `compiled_reflection` | `(&self) -> Result<RenderPipelineReflection, Error>` | `U` `KNOWN` |
| `requiredThreadsPerTileThreadgroup` | `{?=QQQ}16@0:8` | `required_threads_per_tile_threadgroup` | `(&self) -> Size` | `U` `KNOWN` |
| `functionHandleWithFunction:stage:` | `@32@0:8@16Q24` | `function_handle` | `(&self, function: &Function, stage: RenderStages) -> Result<Option<FunctionHandle>, Error>` | `U` `KNOWN` |
| `newVisibleFunctionTableWithDescriptor:stage:` | `@32@0:8@16Q24` | `new_visible_function_table` | `(&self, descriptor: &VisibleFunctionTableDescriptor, stage: RenderStages) -> Result<VisibleFunctionTable, Error>` | `U` `KNOWN` |
| `newRenderPipelineStateWithAdditionalBinaryFunctions:error:` | `@32@0:8@16^@24` | `new_render_pipeline_state_with_additional_binary_functions` | `(&self, functions: &RenderPipelineFunctionsDescriptor) -> Result<RenderPipelineState, Error>` | `U` `KNOWN` |
| `shaderValidation` | `q16@0:8` | **无** | — | `L` `INFERRED`：答「关闭」 |
| `newRenderPipelineDescriptorForSpecialization` | `@16@0:8` | **无** | — | `S4-3` `KNOWN`（Apple 的序列化管线 descriptor，`40` §4 第 3 项） |
| `maxTotalThreadgroupsPerMeshGrid` | `Q16@0:8` | **无** | — | **`N-05`** `KNOWN` |
| `maxTotalThreadsPerMeshThreadgroup` | `Q16@0:8` | **无** | — | **`N-05`** `KNOWN` |
| `maxTotalThreadsPerObjectThreadgroup` | `Q16@0:8` | **无** | — | **`N-05`** `KNOWN` |
| `meshThreadExecutionWidth` | `Q16@0:8` | **无** | — | **`N-05`** `KNOWN` |
| `objectThreadExecutionWidth` | `Q16@0:8` | **无** | — | **`N-05`** `KNOWN` |
| `requiredThreadsPerMeshThreadgroup` | `{?=QQQ}16@0:8` | **无** | — | **`N-05`** `KNOWN` |
| `requiredThreadsPerObjectThreadgroup` | `{?=QQQ}16@0:8` | **无** | — | **`N-05`** `KNOWN` |
| `functionHandleWithBinaryFunction:stage:` | `@32@0:8@16Q24` | **无** | — | **`N-05`** `KNOWN` |
| `functionHandleWithName:stage:` | `@32@0:8@16Q24` | **无** | — | **`N-05`** `KNOWN` |
| `newRenderPipelineStateWithBinaryFunctions:error:` | `@32@0:8@16^@24` | **无**（只有 `_with_additional_binary_functions`） | — | **`N-05`** `KNOWN` |
| `newIntersectionFunctionTableWithDescriptor:stage:` | `@32@0:8@16Q24` | **无** | — | **`N-04`** `KNOWN`（计入 `N-04`，不重复计入 `N-05`） |

`RenderPipelineState` 的 17 个 runtime 扩展（Metal 无 selector，但 **`31-PIPELINE-ARTIFACT.md` 的消费契约要用**，`KNOWN`）：

```
resource_index() -> u64            unique_identifier() -> u64
can_encode_indirect_commands() -> bool          indirect_command_writes() -> CommandWrites
fragment_color_outputs() -> Vec<u32>            has_flat_fragment_inputs() -> bool
reads_barycentric_coord() -> bool               writes_point_size() -> bool
writes_render_target_array_index() -> bool      writes_viewport_array_index() -> bool
vertex_writes_memory() -> bool                  vertex_writes_textures() -> bool
fragment_writes_textures() -> bool              tile_writes_textures() -> bool
mesh_writes_textures() -> bool                  object_writes_textures() -> bool
texture_access(stages, index) -> Result<Option<BindingAccess>, Error>
```

`resource_index()` 与 `unique_identifier()` 正是 `40` §4 第 3 项说的「上游按 Metal 规则答已测的部分」，本项目**必须用它们而不是自己编号**。

### 5.14 `MTLComputePipelineState`（18 required）

签名源：`pipeline/mod.rs:204`（`ComputePipelineState`，18 个公开方法）。左侧按 Metal 公开 API 名，encoding 记 `M-006`。

| Metal selector | 上游调用（`rt::ComputePipelineState::`） | 上游签名 | 标 |
|---|---|---|---|
| `label` | `label` | `(&self) -> Option<&str>` | `U` `KNOWN` |
| `device` | `device` | `(&self) -> &Device` | `U` `KNOWN` |
| `gpuResourceID` | `gpu_resource_id` | `(&self) -> ResourceId` | `U` `KNOWN` |
| `maxTotalThreadsPerThreadgroup` | `max_total_threads_per_threadgroup` | `(&self) -> u32` | `U` `KNOWN` |
| `threadExecutionWidth` | `thread_execution_width` | `(&self) -> u32` | `U` `KNOWN`（上游在本栈上答 **32**） |
| `staticThreadgroupMemoryLength` | `static_threadgroup_memory_length` | `(&self) -> u32` | `U` `KNOWN` |
| `imageblockMemoryLengthForDimensions:` | `imageblock_memory_length_for_dimensions` | `(&self, dimensions: Size) -> u64` | `U` `KNOWN`（**不返回 `Result`**，与 render 侧不同） |
| `supportIndirectCommandBuffers` | `support_indirect_command_buffers` | `(&self) -> bool` | `U` `KNOWN` |
| `requiredThreadsPerThreadgroup` | `required_threads_per_threadgroup` | `(&self) -> Size` | `U` `KNOWN` |
| `reflection` | `compiled_reflection` | `(&self) -> Result<ComputePipelineReflection, Error>` | `U` `KNOWN` |
| `functionHandleWithFunction:` | `function_handle` | `(&self, function: &Function) -> Result<Option<FunctionHandle>, Error>` | `U` `KNOWN` |
| `newVisibleFunctionTableWithDescriptor:` | `new_visible_function_table` | `(&self, descriptor: &VisibleFunctionTableDescriptor) -> Result<VisibleFunctionTable, Error>` | `U` `KNOWN` |
| `newComputePipelineStateWithAdditionalBinaryFunctions:error:` | `new_compute_pipeline_state_with_additional_binary_functions` | `(&self, functions: &[Function]) -> Result<ComputePipelineState, Error>` | `U` `KNOWN`（参数是 `&[Function]`，render 侧是一个 descriptor） |
| `resourceIndex`（SPI） | `resource_index` | `(&self) -> u64` | `U` `KNOWN` |
| `shaderValidation` | **无** | — | `L` `INFERRED` |
| `newIntersectionFunctionTableWithDescriptor:` | **无** | — | **`N-04`** `KNOWN` |
| `functionHandleWithName:` | **无** | — | **`N-05`** `KNOWN` |
| `newComputePipelineStateWithBinaryFunctions:error:` | **无** | — | **`N-05`** `KNOWN` |

其余 runtime 扩展：`unique_identifier() -> u64`、`can_encode_indirect_commands() -> bool`、`indirect_command_writes() -> CommandWrites`、`writes_textures() -> bool`。`KNOWN`

### 5.15 `MTLDepthStencilState`（3）与 `MTLSamplerState`（3）

签名源：`depth_stencil.rs:30`（3 个方法）、`sampler.rs:464`（2 个方法）。

| 协议 | Metal selector | enc | 上游调用 | 上游签名 | 标 |
|---|---|---|---|---|---|
| `MTLDepthStencilState` | `label` | `@16@0:8` | — | 上游 `DepthStencilState` 无 `label`；但有 `descriptor()` | `L` `KNOWN` |
| | `device` | `@16@0:8` | `rt::DepthStencilState::device` | `(&self) -> &Device` | `U` `KNOWN` |
| | `gpuResourceID` | `{MTLResourceID=Q}16@0:8` | `rt::DepthStencilState::gpu_resource_id` | `(&self) -> Result<ResourceId, Error>` | `U` `KNOWN`：**Apple10 以下答 0（纯 Metal 的答案）；声称 Apple10 的设备上答 `NotImplemented(IndirectRenderCommands)`**。本栈不声称任何 family（`91` §2.3），所以走 0 的分支 |
| `MTLSamplerState` | `label` | `@16@0:8` | **无** | — | `L` `KNOWN` |
| | `device` | `@16@0:8` | `rt::SamplerState::device` | `(&self) -> &Device` | `U` `KNOWN` |
| | `gpuResourceID` | `{MTLResourceID=Q}16@0:8` | `rt::SamplerState::gpu_resource_id` | `(&self) -> ResourceId` | `U` `KNOWN` |

> 两个 state 对象的 `label` 都是 `L`：上游 `DepthStencilState`（3 个方法）与 `SamplerState`（2 个方法）都没有 label 方法。第 1.4.1 节两行据此各记 `U` 2 / `L` 1。

`DepthStencilState` 另有 `descriptor(&self) -> &DepthStencilDescriptor`（`KNOWN`），可以用来回放创建时的声明值（`22` R24）。

### 5.16 `MTLFence`（3）、`MTLEvent`（3）、`MTLSharedEvent`（5）

签名源：`fence.rs:79`、`event.rs:60` / `:65` / `:70`。

| 协议 | Metal selector | 上游调用 | 上游签名 | 标 |
|---|---|---|---|---|
| `MTLFence` | `label` | `rt::Fence::label` | `(&self) -> Option<String>` | `U` `KNOWN` |
| | `setLabel:` | `rt::Fence::set_label` | `(&self, label: &str)` | `U` `KNOWN` |
| | `device` | `rt::Fence::device` | `(&self) -> &Device` | `U` `KNOWN` |
| `MTLEvent` | `label` | `rt::Event::label` | `(&self) -> Option<String>` | `U` `KNOWN` |
| | `setLabel:` | `rt::Event::set_label` | `(&self, label: &str)` | `U` `KNOWN` |
| | `device` | `rt::Event::device` | `(&self) -> &Device` | `U` `KNOWN` |
| `MTLSharedEvent` | `signaledValue` | `rt::SharedEvent::signaled_value` | `(&self) -> u64` | `U` `KNOWN` |
| | `setSignaledValue:` | `rt::SharedEvent::set_signaled_value` | `(&self, value: u64)` | `U` `KNOWN` |
| | `newSharedEventHandle` | `rt::SharedEvent::new_shared_event_handle` | `(&self) -> SharedEventHandle` | `U` `KNOWN`：**不返回 `Result`**；**句柄仅进程内**，跨进程序列化是 `S4-6`（`50` 分册） |
| | `notifyListener:atValue:block:` | `rt::SharedEvent::notify_listener` | `(&self, listener: &SharedEventListener, value: u64, block: SharedEventNotification)` | `U` `KNOWN`（K-09） |
| | `waitUntilSignaledValue:timeoutMS:` | `rt::SharedEvent::wait_until_signaled_value` | `(&self, value: u64, timeout: Duration) -> bool` | `U` `KNOWN`：`timeoutMS` → `Duration::from_millis`；返回 `bool` 直接答 |

注意 `rt::SharedEvent::device(&self) -> **Option**<&Device>`（`KNOWN`，与 `Fence` / `Event` 的 `&Device` 不同）：从句柄打开的 shared event 可能没有设备。ObjC 的 `device` 在 `None` 时答当前设备（单设备栈）。`INFERRED`

另两个 runtime 扩展：`rt::SharedEvent::vk_semaphore(unsafe) -> vk::Semaphore`、`rt::SharedEventListener::new() -> SharedEventListener`、`rt::SharedEventHandle::label() -> Option<String>`。`KNOWN`

### 5.17 `MTLDrawable`（6 required）

**整族归 `40` §4 第 4 项**（presentation）。上游 `docs/METAL-COVERAGE.md` 把 `MTLDrawable` 全族列为 out of scope（`KNOWN`，`40` §10.1 已引）。零上游落点。

| Metal selector | 上游调用 | 本项目 | 标 |
|---|---|---|---|
| `present` | **无** | display provider（`11` 分册）：把 scanout IOSurface 提交给 display sink | `S4-4` `KNOWN` |
| `presentAtTime:` | **无** | 同上，带目标时刻 | `S4-4` `KNOWN` |
| `presentAfterMinimumDuration:` | **无** | 同上，带最小间隔 | `S4-4` `KNOWN` |
| `addPresentedHandler:` | **无** | 本地 handler 列表，display sink 回调时投递（K-09 的线程规则同样适用） | `S4-4` `KNOWN` |
| `presentedTime` | **无** | display sink 的时间戳 | `S4-4` `KNOWN` |
| `drawableID` | **无** | 本地递增 ID | `S4-4` `KNOWN` |

与上游的唯一接缝：`rt::Texture::is_drawable(&self) -> bool`（`KNOWN`）。本项目的 drawable 纹理必须让它答 `true`，否则上游可能走非 drawable 的路径。`INFERRED`

> **本项目不走 Vulkan swapchain**（`40` §4 第 4 项与 §6.2 的「必须不要」行）。`rt::Device::new_command_queue_for_presenting` 存在但不用（第 5.2.1 节）。

### 5.18 `MTLIOCommandQueue`（5 required）

**整族无上游落点，且 `40` 第 4 节未登记。** `22` §5.3 已把 `MTLIOCommandQueueDescriptor` 判为 B 档（`needs = "MTLIO fast resource loading"`），但 `40` §4 的十项里没有 MTLIO 这一项，所以没有分册被指派负责它。

| Metal selector | 上游调用 | 本项目 | 标 |
|---|---|---|---|
| `enqueueBarrier` | **无** | — | **`N-09`** `KNOWN` |
| `commandBuffer` | **无** | nil | **`N-09`** `KNOWN` |
| `commandBufferWithUnretainedReferences` | **无** | nil | **`N-09`** `KNOWN` |
| `label` / `setLabel:` | **无** | 本地 | `L` / **`N-09`** `KNOWN` |

处置：`MTLDevice::newIOCommandQueueWithDescriptor:error:` 返回 nil + `Unsupported`，使这 5 条永不可达。见第 7 节 `N-09`。`INFERRED`

---

### 5.19 `MTLDevice`（137 required + 2 optional）

签名源：`crates/metal2vulkan-runtime/src/device/mod.rs:102`（`Device`，95 个公开方法）+ `capabilities.rs:61`（`DeviceProperties`，20 字段 + 11 方法）。encoding 源：`21` §8.2（全量）。

分布：**`U` 55 / `C` 15 / `L` 40 / `S4-n` 2 / `N-nn` 27**。

#### 5.19.1 工厂：有上游落点的 32 条

| Metal selector | 上游调用（`rt::Device::`） | 上游签名 | 要点 | 标 |
|---|---|---|---|---|
| `newCommandQueue` | `new_command_queue` | `(&self) -> Result<CommandQueue, Error>` | — | `U` `KNOWN` |
| `newCommandQueueWithMaxCommandBufferCount:` | `new_command_queue_with_max_command_buffer_count` | `(&self, count: usize) -> Result<CommandQueue, Error>` | `NSUInteger` → `usize` | `U` `KNOWN` |
| `newCommandQueueWithDescriptor:` | `new_command_queue_with_max_command_buffer_count` | 同上 | **`C`**：从 `MTLCommandQueueDescriptor` 取 `maxCommandBufferCount`；其余字段本地 | `C` `INFERRED` |
| `newBufferWithLength:options:` | `new_buffer` | `(&self, length: u64, options: ResourceOptions) -> Result<Buffer, Error>` | K-11 | `U` `KNOWN` |
| `newBufferWithBytes:length:options:` | `new_buffer_with_bytes` | `(&self, bytes: &[u8], options: ResourceOptions) -> Result<Buffer, Error>` | R-BY 的拷贝规则 | `U` `KNOWN` |
| `newBufferWithBytesNoCopy:length:options:deallocator:` | `new_buffer_with_bytes_no_copy` | `unsafe (&self, memory: HostMemory, length: u64, options: ResourceOptions, deallocator: Option<Deallocator>) -> Result<Buffer, Error>` | `HostMemory::new(ptr)` 是 `unsafe`；deallocator 按 K-09；**`VK_EXT_external_memory_host`，设备拒绝指针时退到 dma-buf（macOS 无 dma-buf → 退到拷贝，报 `copied-host-pages`）** | `U` `KNOWN` `*(partial)*` |
| `newTextureWithDescriptor:` | `new_texture` | `(&self, descriptor: &TextureDescriptor) -> Result<Texture, Error>` | descriptor snapshot（`22`） | `U` `KNOWN` |
| `newSharedTextureWithDescriptor:` | `new_shared_texture` | `(&self, descriptor: &TextureDescriptor) -> Result<Texture, Error>` | **仅进程内** | `U` `KNOWN` `*(partial)*` |
| `newSharedTextureWithHandle:` | `new_shared_texture_with_handle` | `(&self, handle: &SharedTextureHandle, placement: IdPlacement) -> Result<Texture, Error>` | **多一个 `IdPlacement` 参数**（Metal 的公开形态没有它）→ 传 `22` R25 的结果或默认 | `C` `KNOWN` |
| `newSamplerStateWithDescriptor:` | `new_sampler_state` / `new_sampler_state_with_options` | `(&self, descriptor: &SamplerDescriptor) -> Result<SamplerState, Error>`；`_with_options(&self, descriptor: &SamplerDescriptor, options: SamplerStateOptions) -> Result<SamplerState, Error>` | `SamplerDescriptor` 在 `crates/metal2vulkan/src/bind/state.rs:1421`（**跨 crate**，本文新查清）。带 argument-buffer 支持或 placement 时走 `_with_options` | `U` `KNOWN` |
| `newDepthStencilStateWithDescriptor:` | `new_depth_stencil_state` | `(&self, descriptor: &DepthStencilDescriptor) -> Result<DepthStencilState, Error>` | `DepthStencilDescriptor` 在 `crates/metal2vulkan/src/metal/state.rs:256`（**跨 crate**，本文新查清，关闭 `22` §5.1 的 `BLOCKED`） | `U` `KNOWN` |
| `newRenderPipelineStateWithDescriptor:error:` | `new_render_pipeline_state` | `(&self, descriptor: &RenderPipelineDescriptor, options: &PipelineOptions) -> Result<RenderPipelineState, Error>` | `RenderPipelineDescriptor` 在 `crates/metal2vulkan/src/pipeline/descriptor.rs:297`；`PipelineOptions` 在 `metal2vulkan-runtime/src/pipeline/options.rs:97`。**无 options 的 Metal 形态传默认 `PipelineOptions`** | `U` `KNOWN` |
| `newRenderPipelineStateWithDescriptor:options:reflection:error:` | `new_render_pipeline_state_with_reflection` | `(&self, descriptor: &RenderPipelineDescriptor, options: &PipelineOptions) -> Result<(RenderPipelineState, Option<RenderPipelineReflection>), Error>` | reflection 出参从元组第二项来 | `U` `KNOWN` |
| `newRenderPipelineStateWithTileDescriptor:options:reflection:error:` | `new_tile_render_pipeline_state_with_reflection` | `(&self, descriptor: &TileRenderPipelineDescriptor, options: &PipelineOptions) -> Result<(RenderPipelineState, Option<RenderPipelineReflection>), Error>` | `TileRenderPipelineDescriptor` 在 `metal2vulkan/src/pipeline/descriptor.rs:629`。**推翻 `22` §5.1 的「上游无 tile pipeline 类型 → gap → B」** | `U` `KNOWN` |
| `newRenderPipelineStateWithMeshDescriptor:options:reflection:error:` | `new_mesh_render_pipeline_state_with_reflection` | `(&self, descriptor: &MeshPipelineDescriptor, options: &PipelineOptions) -> Result<(RenderPipelineState, Option<RenderPipelineReflection>), Error>` | `MeshPipelineDescriptor` 在同文件 `:583`。**推翻 `22` §5.1 的 mesh 行 `BLOCKED` / B** | `U` `KNOWN` |
| `newComputePipelineStateWithFunction:error:` | `new_compute_pipeline_state_with_function` | `(&self, function: &Function, options: &PipelineOptions) -> Result<ComputePipelineState, Error>` | — | `U` `KNOWN` |
| `newComputePipelineStateWithFunction:options:reflection:error:` | `new_compute_pipeline_state_with_function_and_reflection` | `(&self, function: &Function, options: &PipelineOptions) -> Result<(ComputePipelineState, Option<ComputePipelineReflection>), Error>` | — | `U` `KNOWN` |
| `newComputePipelineStateWithDescriptor:options:reflection:error:` | `new_compute_pipeline_state_with_reflection` | `(&self, descriptor: &ComputePipelineDescriptor, options: &PipelineOptions) -> Result<(ComputePipelineState, Option<ComputePipelineReflection>), Error>` | `ComputePipelineDescriptor` 在 `metal2vulkan/src/pipeline/descriptor.rs:528`。**关闭 `22` §5.1 的 `BLOCKED(类型名)`** | `U` `KNOWN` |
| `newLibraryWithData:error:` | `new_library_with_data` | `(&self, data: &[u8]) -> Result<Library, Error>` | 只接受 metallib | `U` `KNOWN` |
| `newLibraryWithFile:error:` | `new_library_with_data` | 同上 | **`C`**：读文件 → `&[u8]` | `C` `INFERRED` |
| `newLibraryWithURL:error:` | `new_library_with_data` | 同上 | **`C`**：同上 | `C` `INFERRED` |
| `newDefaultLibrary` | `new_library_with_data` | 同上 | **`C`**：本项目的默认 metallib 位置由 `70` 分册定 | `C` `INFERRED` |
| `newDefaultLibraryWithBundle:error:` | `new_library_with_data` | 同上 | **`C`** | `C` `INFERRED` |
| `newFence` | `new_fence` | `(&self) -> Fence` | **不返回 `Result`** | `U` `KNOWN` |
| `newEvent` | `new_event` | `(&self) -> Result<Event, Error>` | — | `U` `KNOWN` |
| `newSharedEvent` | `new_shared_event` | `(&self) -> Result<SharedEvent, Error>` | — | `U` `KNOWN` |
| `newSharedEventWithHandle:` | `new_shared_event_with_handle` | `(&self, handle: &SharedEventHandle) -> Result<SharedEvent, Error>` | **仅进程内** | `U` `KNOWN` `*(partial)*` |
| `newHeapWithDescriptor:` | `new_heap` / `new_heap_with_range_token` | `(&self, descriptor: &HeapDescriptor) -> Result<Heap, Error>`；`_with_range_token(&self, descriptor: &HeapDescriptor, token: RangeToken) -> Result<Heap, Error>` | 第一版返回 nil（第 5.10 节）；打开后用带 token 的形态 pin 地址 | `U` `KNOWN` |
| `newIndirectCommandBufferWithDescriptor:maxCommandCount:options:` | `new_indirect_command_buffer` | `(&self, descriptor: &IndirectCommandBufferDescriptor, max_count: u64, options: ResourceOptions) -> Result<IndirectCommandBuffer, Error>` | — | `U` `KNOWN` |
| `newRasterizationRateMapWithDescriptor:` | `new_rasterization_rate_map` | `(&self, descriptor: &RateMapDescriptor) -> Result<RasterizationRateMap, Error>` | `RateMapDescriptor` 在 `metal2vulkan::bind`（跨 crate，K-01 的例外） | `U` `KNOWN` |
| `newBinaryArchiveWithDescriptor:error:` | `new_binary_archive` | `(&self, descriptor: &BinaryArchiveDescriptor) -> Result<BinaryArchive, Error>` | `url` 按 `22` R28 重定向 | `U` `KNOWN` |
| `newArchiveWithURL:error:` | `new_binary_archive` | 同上 | **`C`**：URL → descriptor | `C` `INFERRED` |
| `newArgumentEncoderWithArguments:` | `new_argument_encoder_with_arguments` | `(&self, arguments: &[ArgumentDescriptor]) -> Result<ArgumentEncoder, Error>` | `ArgumentDescriptor` 在 `crates/metal2vulkan/src/bind/argument_buffer.rs:168`（**跨 crate**，关闭 `22` §5.3 的 `BLOCKED(构造签名)`） | `U` `KNOWN` |
| `newArgumentEncoderWithBufferBinding:` | `new_argument_encoder_with_buffer_binding` | `(&self, binding: &BufferBinding) -> Result<ArgumentEncoder, Error>` | — | `U` `KNOWN` |
| `newDynamicLibrary:error:` | `new_dynamic_library` | `(&self, library: &Library) -> Result<DynamicLibrary, Error>` | **对象可建，链接使用被拒**（`40` §2.4） | `U` `KNOWN` |
| `newDynamicLibraryWithURL:error:` | `new_dynamic_library_with_url` | `(&self, url: &Path) -> Result<DynamicLibrary, Error>` | 同上 | `U` `KNOWN` |
| `newTextureWithDescriptor:iosurface:plane:` | **组合** | `new_buffer_with_bytes_no_copy` → `Buffer::new_texture_with_iosurface_plane` | **`C`**：`40` §3.2 已记，第 5.7.1 节给落点。**必须走 `new_texture_with_iosurface_plane` 而不是 `Buffer::new_texture`**（后者按 buffer 规则，会拒绝 Metal 接受的非 16 对齐行距） | `C` `KNOWN` |

异步形态 7 条（K-13，全部 `C`）：`newRenderPipelineStateWithDescriptor:completionHandler:`、`newRenderPipelineStateWithDescriptor:options:completionHandler:`、`newComputePipelineStateWithFunction:completionHandler:`、`newComputePipelineStateWithFunction:options:completionHandler:`、`newComputePipelineStateWithDescriptor:options:completionHandler:`、`newRenderPipelineStateWithMeshDescriptor:options:completionHandler:`、`newRenderPipelineStateWithTileDescriptor:options:completionHandler:`。`C` `INFERRED`

#### 5.19.2 工厂：无上游落点的 24 条

| Metal selector | 组 | 本项目回答 | 标 |
|---|---|---|---|
| `newLibraryWithSource:options:error:` | MSL 前端 | nil + `Unsupported`（`needs = "MSL front end"`，边界 ①） | **`N-13`** `KNOWN` |
| `newLibraryWithSource:options:completionHandler:` | 同上 | 同上，block 立即以错误调用 | **`N-13`** `KNOWN` |
| `newLibraryWithStitchedDescriptor:error:` | function stitching | nil + `Unsupported` | **`N-13`** `KNOWN` |
| `newLibraryWithStitchedDescriptor:completionHandler:` | 同上 | 同上 | **`N-13`** `KNOWN` |
| `newAccelerationStructureWithSize:` | ray tracing | nil | **`N-04`** `KNOWN` |
| `newAccelerationStructureWithDescriptor:` | 同上 | nil | **`N-04`** `KNOWN` |
| `newCounterSampleBufferWithDescriptor:error:` | counters | nil + `Unsupported`；配 `counterSets` 返回空数组 | **`N-02`** `KNOWN` |
| `newCounterHeapWithDescriptor:error:` | 同上 | nil + `Unsupported` | **`N-02`** `KNOWN` |
| `newIOCommandQueueWithDescriptor:error:` | MTLIO | nil + `Unsupported`（`needs = "MTLIO fast resource loading"`） | **`N-09`** `KNOWN` |
| `newIOFileHandleWithURL:error:` | 同上 | nil | **`N-09`** `KNOWN` |
| `newIOFileHandleWithURL:compressionMethod:error:` | 同上 | nil | **`N-09`** `KNOWN` |
| `newIOHandleWithURL:error:` | 同上 | nil | **`N-09`** `KNOWN` |
| `newIOHandleWithURL:compressionMethod:error:` | 同上 | nil | **`N-09`** `KNOWN` |
| `newMTL4CommandQueue` | MTL4 | nil | **`N-10`** `KNOWN` |
| `newMTL4CommandQueueWithDescriptor:error:` | 同上 | nil | **`N-10`** `KNOWN` |
| `newCommandAllocator` | 同上 | nil | **`N-10`** `KNOWN` |
| `newCommandAllocatorWithDescriptor:error:` | 同上 | nil | **`N-10`** `KNOWN` |
| `newCommandBuffer` | 同上（MTL4 的设备级命令缓冲） | nil | **`N-10`** `KNOWN` |
| `newArgumentTableWithDescriptor:error:` | 同上 | nil | **`N-10`** `KNOWN` |
| `newCompilerWithDescriptor:error:` | 同上（MTL4 compiler 对象） | nil；与 `32` 分册的 compiler plugin 是两件事 | **`N-10`** `KNOWN` |
| `newPipelineDataSetSerializerWithDescriptor:` | 同上 | nil | **`N-10`** `KNOWN` |
| `newTensorWithDescriptor:error:` | tensor | nil + `Unsupported` | **`N-11`** `KNOWN` |
| `newTextureViewPoolWithDescriptor:error:` | view pool | nil + `Unsupported`；`IdPlacement` 可部分替代（`22` §5.3） | **`N-12`** `KNOWN` |
| `newBufferWithLength:options:placementSparsePageSize:` | placement sparse | nil + `Unsupported`（Lavapipe sparse 仅 Linux） | **`N-14`** `KNOWN` |
| `newLogStateWithDescriptor:error:` | shader log | **成功**，handler 可能永不触发 + degradation（`22` §5.3） | `L` `INFERRED` |
| `newResidencySetWithDescriptor:error:` | residency set | **成功**，本地簿记（`22` §5.3） | `L` `INFERRED` |

#### 5.19.3 能力与限值：有上游落点的 23 条

| Metal selector | enc | 上游调用 | 上游签名 | 标 |
|---|---|---|---|---|
| `name` | `@16@0:8` | `rt::Device::name` 或 `properties().name` | `(&self) -> &str` / 字段 `String` | `U` `KNOWN` |
| `registryID` | `Q16@0:8` | `rt::Device::registry_id` | `(&self) -> u64` | `U` `KNOWN`：**由 `deviceUUID` 折叠而来**（上游文档 `DeviceCaps::registry_id` 行）。`91` 实测 APV 的值是 4294968049 |
| `hasUnifiedMemory` | `c16@0:8` | `properties().has_unified_memory` | 字段 `bool` | `U` `KNOWN`（`91` 实测 APV 答 False） |
| `maxBufferLength` | `Q16@0:8` | `properties().max_buffer_length` | 字段 `u64` | `U` `KNOWN`（`91` 实测 APV = 1 GiB，与 `10` 分册的硬下限一致） |
| `maxThreadsPerThreadgroup` | `{?=QQQ}16@0:8` | `properties().max_threads_per_threadgroup` | 字段 `Size` | `U` `KNOWN` |
| `maxThreadgroupMemoryLength` | `Q16@0:8` | `properties().max_threadgroup_memory_length` | 字段 `u64` | `U` `KNOWN` |
| `argumentBuffersSupport` | `Q16@0:8` | `properties().argument_buffers_support` | 字段 `ArgumentBuffersTier` | `U` `KNOWN`（`91` 实测 APV = 0 / Tier1） |
| `readWriteTextureSupport` | `Q16@0:8` | `properties().read_write_texture_support` | 字段 `ReadWriteTextureTier` | `U` `KNOWN` |
| `supports32BitFloatFiltering` | `c16@0:8` | `properties().supports_32bit_float_filtering` | 字段 `bool` | `U` `KNOWN` |
| `areProgrammableSamplePositionsSupported` | `c16@0:8` | `properties().are_programmable_sample_positions_supported()` | `-> Result<bool, RuntimeGap>` | `U` `KNOWN`；`Err` → 第 4.4 节 |
| `areRasterOrderGroupsSupported` | `c16@0:8` | `properties().are_raster_order_groups_supported()` | `-> Result<bool, RuntimeGap>` | `U` `KNOWN`：**设备启用 `fragmentShaderPixelInterlock` 时为 yes** `*(partial)*` |
| `isDepth24Stencil8PixelFormatSupported` | `c16@0:8` | `properties().is_depth24_stencil8_pixel_format_supported()` | `-> Result<bool, RuntimeGap>` | `U` `KNOWN`：**答 no 时建该格式会被拒** |
| `supportsTextureSampleCount:` | `c24@0:8Q16` | `properties().supports_texture_sample_count(count)` | `-> Result<bool, RuntimeGap>` | `U` `KNOWN` |
| `supportsVertexAmplificationCount:` | `c24@0:8Q16` | `properties().supports_vertex_amplification_count(count)` | `-> Result<bool, RuntimeGap>` | `U` `KNOWN` |
| `supportsRasterizationRateMapWithLayerCount:` | `c24@0:8Q16` | `properties().supports_rasterization_rate_map_with_layer_count(count)` | `-> Result<bool, RuntimeGap>` | `U` `KNOWN` |
| `minimumLinearTextureAlignmentForPixelFormat:` | `Q24@0:8Q16` | `properties().minimum_linear_texture_alignment_for_pixel_format(format)` | `-> Result<u64, Error>` | `U` `KNOWN` |
| `supportsFamily:` | `c24@0:8q16` | `rt::Device::supports_family` + `family_blockers` | `supports_family(&self, family: i64) -> bool`；`family_blockers(&self, family: GpuFamily) -> Vec<RowAudit>`；`family_rows(&self, family: GpuFamily) -> Vec<RowAudit>` | `U` `KNOWN`：**不得硬编码**（`60` §1.4）。注意 `supports_family` 收 `i64` raw，不是 `GpuFamily` |
| `heapBufferSizeAndAlignWithLength:options:` | `{?=QQ}32@0:8Q16Q24` | `rt::Device::heap_buffer_size_and_align` | `(&self, length: u64, _options: ResourceOptions) -> SizeAndAlign` | `U` `KNOWN`：**options 被忽略**（参数名带下划线） |
| `heapTextureSizeAndAlignWithDescriptor:` | `{?=QQ}24@0:8@16` | `rt::Device::heap_texture_size_and_align`（另有 `metal_heap_texture_size_and_align`） | `(&self, descriptor: &TextureDescriptor) -> Result<SizeAndAlign, Error>`；`metal_...(&self, descriptor) -> Result<Option<SizeAndAlign>, Error>` | `U` `KNOWN`：第一个给「Metal 的答案（能建模时）或设备自己的 footprint」；第二个只在能给 Metal 的答案时给 `Some`。**`40` §11 的 `R-03`（`MACOS_RELEASE` 26 vs 27 差异）就要比这两个的差值** |
| `sparseTileSizeWithTextureType:pixelFormat:sampleCount:` | `{?=QQQ}40@0:8Q16Q24Q32` | `rt::Device::sparse_tile_size` | `(&self, texture_type: TextureType, pixel_format: PixelFormat, sample_count: u64) -> Size` | `U` `KNOWN` |
| `sparseTileSizeWithTextureType:pixelFormat:sampleCount:sparsePageSize:` | `{?=QQQ}48@0:8Q16Q24Q32q40` | `rt::Device::sparse_tile_size_for_page` | `(&self, _texture_type: TextureType, pixel_format: PixelFormat, sample_count: u64, page: SparsePageSize) -> Size` | `U` `KNOWN` |
| `sparseTileSizeInBytes` | `Q16@0:8` | `rt::Device::sparse_tile_size_in_bytes` | `(&self) -> u64` | `U` `KNOWN` |
| `sparseTileSizeInBytesForSparsePageSize:` | `Q24@0:8q16` | `rt::Device::sparse_tile_size_in_bytes_for_page` | `(&self, page: SparsePageSize) -> u64` | `U` `KNOWN` |
| `convertSparsePixelRegions:toTileRegions:withTileSize:alignmentMode:numRegions:`（opt） | 见 `21` §8.2 | `rt::Device::convert_sparse_pixel_regions` | `(&self, pixel_regions: &[Region], tile_regions: &mut [Region], tile_size: Size, mode: SparseTextureRegionAlignmentMode) -> Result<(), Error>` | `U` `KNOWN` |
| `convertSparseTileRegions:toPixelRegions:withTileSize:numRegions:`（opt） | 见 `21` §8.2 | `rt::Device::convert_sparse_tile_regions` | `(&self, tile_regions: &[Region], tile_size: Size) -> Vec<Region>` | `U` `KNOWN`：**返回 `Vec` 而不是写出参** → 写回客户端的 `toPixelRegions:` 缓冲 |

> sparse 的 6 条有落点但 **Lavapipe 的 sparse 在 macOS 上不可用**（`40` §2.2）。所以它们答得出尺寸，却建不出 sparse 资源。`supportsPlacementSparse` 必须答 `NO`（第 5.19.4 节），`MTLTexture::isSparse` 恒 false。这不是矛盾：Metal 的 `sparseTileSize*` 在不支持 sparse 的设备上也有定义值。`INFERRED`

#### 5.19.4 能力与限值：本地可答的 38 条

全部 `L`。「本地可答」不等于「随便填」：每条的取值由 `20-OBJC-DEVICE.md` 的 limits / flags 表定，并进 capability manifest（`40` §7.5）。本表只给来源与第一版取值依据。

| Metal selector | 第一版取值依据 | 标签 |
|---|---|---|
| `isLowPower` | `91` 实测 APV = False → False | `TESTED(25G76)` |
| `isHeadless` | `91` 实测 APV = False → False | `TESTED(25G76)` |
| `isRemovable` | `91` 实测 APV = False → False | `TESTED(25G76)` |
| `location` / `locationNumber` | APV 的值；`20` 分册定 | `B`（`M-008`） |
| `architecture` | 本项目自报（`MTLArchitecture` 对象） | `INFERRED` |
| `maxTransferRate` | 0（统一内存设备的 Metal 约定） | `INFERRED` |
| `peerCount` / `peerGroupID` / `peerIndex` | 0 / 0 / 0（单设备） | `INFERRED` |
| `currentAllocatedSize` | 本项目的分配账本累加 | `INFERRED` |
| `recommendedMaxWorkingSetSize` | 由 guest RAM 与 `40` §6 的策略定；`20` 分册 | `B`（`M-008`） |
| `maxArgumentBufferSamplerCount` | 上游有 `Device::sampler_id_pool_size()` / `sampler_ids_live()`（`KNOWN`），可据此定 | `C` `INFERRED` |
| `maximumConcurrentCompilationTaskCount` | 本项目编译线程池并发度（K-13） | `INFERRED` |
| `shouldMaximizeConcurrentCompilation` / `setShouldMaximizeConcurrentCompilation:` | 本地存，影响线程池 | `INFERRED` |
| `getDefaultSamplePositions:count:` | 由 `40` §6.2 的 `VK_EXT_sample_locations` 与 Vulkan 的默认采样位置推 | `INFERRED` |
| `supports32BitMSAA` | `40` §8.2.2：`RGBA8Uint` / `Sint` 的 MSAA 仅 1 采样 → 需实测 | `B`（`M-009`） |
| `supportsBCTextureCompression` | Lavapipe `textureCompressionBC = true`（`40` §8.2.7）→ True | `INFERRED` |
| `supportsPullModelInterpolation` | 由启用的扩展推；`60` 分册 | `B`（`M-009`） |
| `supportsQueryTextureLOD` | 同上 | `B`（`M-009`） |
| `supportsShaderBarycentricCoordinates` / `areBarycentricCoordsSupported` | 上游有 `RenderPipelineState::reads_barycentric_coord()`（`KNOWN`），说明翻译器认识它；设备侧由 `60` 分册定 | `B`（`M-009`） |
| `supportsPlacementSparse` | False（`N-14`） | `INFERRED` |
| `supportsPrimitiveMotionBlur` | False（ray tracing 相关，`N-04`） | `INFERRED` |
| `supportsRaytracing` / `supportsRaytracingFromRender` | False（`N-04`） | `INFERRED` |
| `supportsDynamicLibraries` / `supportsRenderDynamicLibraries` | APV 实测两者都有 IMP；上游对象可建、链接被拒 → **False**（否则客户端会去链接） | `INFERRED` |
| `supportsFunctionPointers` / `supportsFunctionPointersFromRender` | False（Vulkan 无函数指针，`40` §2.4） | `INFERRED` |
| `supportsFeatureSet:` | 已弃用的 feature set 面。按 `supportsFamily:` 的结果推；APV 连 `Mac2` 都 False（`91` §2.3）→ 全 False | `INFERRED` |
| `supportsCounterSampling:` | False（`N-02`） | `INFERRED` |
| `counterSets` | 空数组（`N-02`，使 counter descriptor 永远无效） | `INFERRED` |
| `sizeOfCounterHeapEntry:` | 0（`N-02`） | `INFERRED` |
| `queryTimestampFrequency` | 由 `host_time` 的基准推（上游有自由函数 `rt::host_time() -> f64`，`KNOWN`） | `C` `INFERRED` |
| `sampleTimestamps:gpuTimestamp:` | `rt::host_time()` 两个出参同值。`40` §6.6 的 `gpu_times_from_host = true` 使 GPU 时间也来自主机时钟 | `C` `KNOWN` |
| `minimumTextureBufferAlignmentForPixelFormat:` | 上游只有 `minimum_linear_texture_alignment_for_pixel_format`；texture buffer 的对齐另算 | `L` / `C` `INFERRED` |
| `functionHandleWithFunction:` | 设备级无落点；落点在两个 pipeline state 上（第 5.13 / 5.14 节）→ 需要一个当前 pipeline 上下文，设备级形态返回 nil | `C` `INFERRED` |

#### 5.19.5 无落点的能力查询 5 条

| Metal selector | 本项目回答 | 标 |
|---|---|---|
| `accelerationStructureSizesWithDescriptor:` | 全 0（`22` §5.3 已定） | **`N-04`** `KNOWN` |
| `heapAccelerationStructureSizeAndAlignWithDescriptor:` | `{0, 0}` | **`N-04`** `KNOWN` |
| `heapAccelerationStructureSizeAndAlignWithSize:` | `{0, 0}` | **`N-04`** `KNOWN` |
| `tensorSizeAndAlignWithDescriptor:` | `{0, 0}` | **`N-11`** `KNOWN` |
| `functionHandleWithBinaryFunction:` | nil | **`N-05`** `KNOWN` |

#### 5.19.6 `Device` 的 runtime 扩展（本项目**必须**用的 12 个）

`KNOWN`。`40` §4.1 已列用途，本文给精确签名。

| 上游 | 签名 | 本项目用在哪 |
|---|---|---|
| `registry_ids_with` | `(options: &DeviceOptions) -> Result<Vec<u64>, Error>` | 启动自检第 2 项（`40` §6.7），**不建设备**就列出合格物理设备 |
| `system_default_identity_with` | `(options: &DeviceOptions) -> Result<PhysicalDeviceIdentity, Error>` | 启动自检第 3 项 |
| `with_registry_id` | `(registry_id: u64, options: &DeviceOptions) -> Result<Device, Error>` | 只建那一个设备（`40` §6.3 第二重） |
| `system_default_with` / `all_with` | `(options: &DeviceOptions) -> Result<Device, Error>` / `-> Result<Vec<Device>, Error>` | 诊断用；产品路径用 `with_registry_id` |
| `enables_extension` | `(&self, name: &CStr) -> bool` | 启动自检第 6 项 |
| `enabled` | `(&self) -> &EnableSet` | 实际启用集合，进 capability manifest |
| `pixel_format_capabilities` | `(&self, format: PixelFormat) -> FormatCapabilities` | `40` §8.4 的格式表生成（301 个格式） |
| `pixel_format_info` | `(&self, raw: u64) -> PixelFormatInfo` | Apple 的 flag word 由本项目补（`40` §4 第 8 项） |
| `texture_level_info` | `(&self, query: &TextureLevelQuery) -> TextureLevelInfo` | `40` §4 第 1 项把 `GpuDevice::texture_level_info` 划给消费者，但**上游有这个方法**，所以是 `U` 不是缺口 |
| `reserve_resource_ids` / `reserve_address_pool` | `(&self, kind: ResourceIdKind, ids: &[ResourceId]) -> Result<(), Error>` / `(&self, placement: AddressPlacement, length: u64) -> Result<AddressPool, Error>` | guest 自有编号与地址 pin（`22` §5.2） |
| `warm` / `warm_statistics` | `(&self, records: Vec<PipelineRecord>, byte_budget: u64)` / `(&self) -> WarmStatistics` | 管线预热（`40` §6.6） |
| `work_counts` / `degraded_objects` / `shader_cache_statistics` / `private_properties` | `(&self) -> WorkCounts` / `(&self, kind: Degradation) -> Option<u64>` / `(&self) -> ShaderCacheStatistics` / `(&self) -> PrivateProperties` | 可观测性（`40` §7） |
| `use_host_ram` | `(&self, ram: &Arc<HostRam>) -> Result<HostRamUse, Error>` | 导入 guest 页的第三条退路（`41` 分册） |
| `imports_shared_host_pointers` | `(&self) -> Result<bool, Error>` | 启动自检：`VK_EXT_external_memory_host` 真的能用吗 |
| `raw` / `device_proc_addr` / `compile_device` / `vk_buffer_usage` | `unsafe (&self) -> DeviceHandles<'_>` / `(&self, name: &CStr) -> vk::PFN_vkVoidFunction` / `(&self) -> &metal2vulkan::device::Device` / `(&self) -> BufferUsageFlags` | Vulkan interop 与翻译器侧访问 |

### 5.20 `MTLDeviceSPI`（427 required + 80 optional = 507）

`21` §8.3 不逐条列这 507 条（它们在 `S-DUMP` 第 1574–2440 行）。本节按 `21` §8.3 的 9 类普查给**每组规则**，并逐条给出**有上游落点的承重行**。逐条映射记 `M-002`（本文最大的未覆盖面）。

#### 5.20.1 分组规则

`KNOWN`（组与方法数取自 `21` §8.3）；规则 `INFERRED`。

| 组 | 方法数 | APV 实现 | 规则 | 预计 `U` |
|---|---:|---:|---|---:|
| 能力布尔查询（`supports*` / `is*` / `are*` / `has*`） | 255 | 11 | **默认继承 `_MTLDevice` 的默认值，只覆写与默认不同的。** 覆写集由 `60-CAPABILITY-MATRIX.md` 定。有上游依据的走 `DeviceProperties` 的 11 个方法或 `family_blockers`；无依据的 `L` + 进 capability manifest | ~8 |
| `new*` 工厂 | 78 | 6 | 大半可 `return nil`（`21` §4.1.3 的 APV 证据）。有上游落点的在第 5.20.2 节逐条给 | ~10 |
| 限值 / 对齐（`max*` / `min*`） | 64 | 0 | `L`：取 `DeviceProperties` 的字段，或 `20` 分册的 limits 表。**三道闸**（`22` R18）：本文上限、`DeviceProperties` 实测上限、协议上限，取最小 | ~6 |
| 其它 | 69 | 9 | 逐条判；`vendorName` / `familyName` / `productName` / `featureProfile` / `llvmVersion` 等在 `20` / `32` 分册已定值 | ~2 |
| 编译器接口 | 12 | 1 | **不走上游**：这是 `32-COMPILER-PLUGIN.md` 的面（compiler plugin dylib 的 8 个接口 selector + `newCompilerWithDescriptor:`）。`21` §8.0 的提醒：pipeline 创建链的 5 个 selector 不在任何协议里，必须另外实现 | 0 |
| setter | 11 | 1 | `L`：本地存 + 按 R24 回放 | 0 |
| 尺寸 / 对齐计算 | 10 | 0 | 有落点：`heap_buffer_size_and_align`、`heap_texture_size_and_align`、`metal_heap_texture_size_and_align`、`texture_level_info`、`sparse_tile_size*`（4 个） | ~8 |
| pipeline / variant | 6 | 0 | `S4-3`（Apple 的序列化管线 descriptor，`40` §4 第 3 项）+ `N-05` | 0 |
| counter / 采样 | 2 | 0 | `N-02` → R-Z | 0 |
| **合计** | **507** | **28** | | **~34** |

#### 5.20.2 承重行：有上游落点的 `MTLDeviceSPI` 条目

`KNOWN`。这些必须逐条转发，不能按组规则糊过去。

| Metal selector（SPI） | 上游调用 | 上游签名 | 标 |
|---|---|---|---|
| `newBufferWithDescriptor:` | `rt::Device::new_buffer_with_descriptor` | `(&self, descriptor: BufferDescriptor<'_>) -> Result<Buffer, Error>` | `U` `KNOWN`：`BufferDescriptor` 按值且带生命周期；配 `BufferContents`（含 `CopyHost` + `HostBytes`，读取中可能变化的 guest 内存）与 `AddressPlacement`。另有 `BufferDescriptor::with_pool_slot(&pool, offset)` 把 buffer 放在 `AddressPool` 的地址 + 256 字节对齐的偏移上 |
| `newSharedTextureWithHandle:withResourceIndex:` | `rt::Device::new_shared_texture_with_handle` | `(&self, handle: &SharedTextureHandle, placement: IdPlacement) -> Result<Texture, Error>` | `U` `KNOWN`：index 即 `IdPlacement` |
| `reserveResourceIndicesForResourceType:indices:indexCount:` | `rt::Device::reserve_resource_ids` | `(&self, kind: ResourceIdKind, ids: &[ResourceId]) -> Result<(), Error>` | `U` `KNOWN` |
| `newTextureWithDescriptor:iosurface:plane:` | 第 5.19.1 节的组合 | — | `C` `KNOWN` |
| `heapBufferSizeAndAlignWithLength:options:` | `rt::Device::heap_buffer_size_and_align` | 见第 5.19.3 节 | `U` `KNOWN` |
| `heapTextureSizeAndAlignWithDescriptor:` | `rt::Device::heap_texture_size_and_align` | 同上 | `U` `KNOWN` |
| `newSamplerStateWithDescriptor:` 的 argument-buffer / placement 形态 | `rt::Device::new_sampler_state_with_options` | `(&self, descriptor: &SamplerDescriptor, options: SamplerStateOptions) -> Result<SamplerState, Error>` | `U` `KNOWN` |
| `newVisibleFunctionTableWithDescriptor:` | `rt::ComputePipelineState::new_visible_function_table` / `rt::RenderPipelineState::new_visible_function_table` | 见第 5.13 / 5.14 节 | `C` `KNOWN`：**设备级形态无落点**（上游的表挂在 pipeline state 上）。APV 对它调 `doesNotRecognizeSelector:` 后返回 nil（`21` §2.5）→ 本项目 `return nil` |
| `newIndirectCommandBufferWithDescriptor:maxCount:options:` | `rt::Device::new_indirect_command_buffer` | 见第 5.19.1 节 | `U` `KNOWN`（注意 SPI 的参数名是 `maxCount:`，公开形态是 `maxCommandCount:`） |
| `supportsSampleCount:` | `properties().supports_texture_sample_count(count)` | `-> Result<bool, RuntimeGap>` | `U` `KNOWN` |
| `pixelFormatInfo` 系 | `rt::Device::pixel_format_info` | `(&self, raw: u64) -> PixelFormatInfo` | `U` + `S4-8` `KNOWN`：**Apple 的 flag word 要本项目补**（`40` §4 第 8 项）；block 事实在 `metal2vulkan::metal::format` |
| texture level 查询系 | `rt::Device::texture_level_info` | `(&self, query: &TextureLevelQuery) -> TextureLevelInfo` | `U` `KNOWN` |
| `supportsBufferWithIOSurface` 之类的 IOSurface 标志 | **无** | — | `S4-1` `KNOWN`（上游明确划给消费者） |
| `gpuCoreCount` | `properties().gpu_core_count` | 字段 `Option<u32>`，**Lavapipe 上为 `None`** | `S4-8` `KNOWN`：本项目必须给一个有依据的值 |
| `doubleFPConfig` / `singleFPConfig` / `halfFPConfig` | **无** | — | `L` `INFERRED`：APV 实测有 IMP（`21` §8.1.2），取值由 `20` 分册定 |
| `newIndirectComputeCommandEncoderWithBuffer:` / `newIndirectRenderCommandEncoderWithBuffer:` | **无**（上游的间接命令走 `IndirectCommandBuffer::indirect_*_command_at`） | `rt::IndirectCommandBuffer::indirect_render_command_at(&self, index: u64) -> Result<IndirectRenderCommand, Error>`（另一个同形） | `C` `KNOWN`：APV 对这两条直接 `return nil`（`21` §2.5），第一版照做 |

#### 5.20.3 分组规则的两条硬约束

> **R42-07**（`INFERRED`）：第 5.20.1 节的「默认继承」只适用于**能力布尔**与**限值**两组。`new*` 工厂组**不得**依赖继承：`_MTLDevice` 的默认实现可能返回一个我们没有后备的对象。每个 `new*` SPI selector 必须显式覆写为「有落点则转发，无落点则 `return nil`」。依据：`21` §2.5 的 APV 行为（`return nil` 比 `doesNotRecognizeSelector:` 安全，后者抛 `NSInvalidArgumentException`）。

> **R42-08**（`INFERRED`）：507 条里的每一条，在第一版实现中必须落在**三种状态之一**：① 显式覆写并转发；② 显式覆写并返回 nil / 0 / NO；③ 明确决定继承 `_MTLDevice` 的默认值，且该决定进 capability manifest。**不允许「没想过」**。验收方式见第 9.3 节：用 `class_copyMethodList` 的实际覆写集与本文的三态清单 diff。

---

## 6. 与 `22-OBJC-DESCRIPTORS.md` 的交界

### 6.1 交界点的精确位置

`22` 管 descriptor 类的**字段级**处置，本文管**方法调用**的映射。两者在 descriptor 构造那一步交界。交界点有且只有一个：

```text
客户端                   ObjC shim                      Rust adapter              上游
   │                        │                              │                        │
   │ [MTLTextureDescriptor  │                              │                        │
   │   setWidth:1024]       │                              │                        │
   ├───────────────────────►│  ① 可变 descriptor 对象        │                        │
   │                        │     （22 §1：必须 snapshot）  │                        │
   │ newTextureWithDescriptor:                             │                        │
   ├───────────────────────►│                              │                        │
   │                        │  ② 逐字段 checked-convert     │                        │
   │                        │     （22 R12 的 ②，在 .m 里） │                        │
   │                        │  ③ 不可变 C snapshot          │                        │
   │                        ├─────────────────────────────►│                        │
   │                        │                              │ ④ 跨字段校验（22 R12 ③）│
   │                        │                              │ ⑤ snapshot → 上游值类型  │
   │                        │                              ├───────────────────────►│
   │                        │                              │   Device::new_texture  │
   │                        │                              │   (&TextureDescriptor) │
   │                        │                              │                        │
   ╞═══════════════════ 22 的责任 ═══════════════════╪══ 交界 ══╪══ 42 的责任 ══════════╡
                                                   ③④⑤
```

> **交界契约（`INFERRED`）**：
>
> 1. **②（逐字段）归 `22`**：它知道每个字段的合法域、默认值、encoding。
> 2. **③（snapshot 的 C 结构布局）归 `22`**：`22` §6 定义 wire 形态。
> 3. **④（跨字段校验）归 `22`**（规则）+ 归 `42`（**上游侧的拒绝点**）：`22` 定「哪些组合非法」，`42` 定「上游在哪个调用上拒绝它、用哪个 `Problem`」。
> 4. **⑤（snapshot → 上游值类型）归 `42`**：它是本文第 5 节「参数转换」列的一部分。
> 5. **`42` 不定义任何 descriptor 字段的合法域**，`22` **不定义任何上游调用名**。两者引用对方，不复制。

### 6.2 本文对 `22` 的四处修正

本文抽取上游源码时查清了 `22` 第 5 节标 `BLOCKED` 或判断有误的几行。`KNOWN`（来源在表内）。

| `22` 的原文 | 实际情况 | 本文依据 |
|---|---|---|
| §5.1 `MTLTileRenderPipelineDescriptor` → 「上游无 tile pipeline 类型 → **gap → B**」 | **错。** 上游有 `metal2vulkan::pipeline::TileRenderPipelineDescriptor`（`crates/metal2vulkan/src/pipeline/descriptor.rs:629`）与 `rt::Device::new_tile_render_pipeline_state` / `_with_reflection`。应改为**逐字段映射**，档位从 B 降为无 | `KNOWN`：定义处行号 + 两个 `pub fn` 签名 |
| §5.1 `MTLMeshRenderPipelineDescriptor` → 「`BLOCKED`；当前 **B**」 | **部分错。** 上游有 `metal2vulkan::pipeline::MeshPipelineDescriptor`（同文件 `:583`）与 `rt::Device::new_mesh_render_pipeline_state` / `_with_reflection`，render encoder 侧也有 9 个 `set_mesh_*` + 9 个 `set_object_*` + 3 个 mesh draw。**descriptor 与编码两侧都有落点；缺的只是 `MTLRenderPipelineState` 上的 7 个 mesh/object 限值查询**（本文 `N-05`）。档位从 B 降为「逐字段映射 + 7 条查询本地补」 | `KNOWN`：定义处行号 + 第 5.4.5 / 5.4.6 / 5.4.7 / 5.13 节 |
| §5.1 `MTLComputePipelineDescriptor` → `BLOCKED(类型名)` | **已关闭**：`metal2vulkan::pipeline::ComputePipelineDescriptor`（`descriptor.rs:528`） | `KNOWN` |
| §5.1 `MTLDepthStencilDescriptor` + `MTLStencilDescriptor` → `BLOCKED(descriptor 值类型名)`；「上游只列出 `DepthStencilState` 对象」 | **已关闭**：`metal2vulkan::metal::state::DepthStencilDescriptor`（`crates/metal2vulkan/src/metal/state.rs:256`）。另：`rt::DepthStencilState::descriptor(&self) -> &DepthStencilDescriptor` 可回放创建值 | `KNOWN` |

另外三处小关闭：

| `22` 的 `BLOCKED` | 关闭 |
|---|---|
| §5.1 `MTLVertexDescriptor` / `MTLStageInputOutputDescriptor` → `BLOCKED(类型名)` | `metal2vulkan::pipeline::VertexDescriptor`（`descriptor.rs:780`）。stage input/output 侧仍 `BLOCKED`（本文 `M-010`） |
| §5.3 `MTLArgumentDescriptor` → `BLOCKED(构造签名)` | `metal2vulkan::bind::argument_buffer::ArgumentDescriptor`（`:168`），经 `rt::Device::new_argument_encoder_with_arguments(&[ArgumentDescriptor])` |
| §5.3 `MTLTextureViewDescriptor` → `BLOCKED(调用名)` | 落点是 `rt::Texture::new_texture_view` / `_with_levels_slices` / `_with_swizzle` / `_with_placement` / `new_texture_subview_with_placement`（第 5.8 节） |

### 6.3 方法侧必须向 descriptor 侧回传的三件事

`INFERRED`。这三件事是「方法调用」才知道、而 descriptor 校验需要的，必须从本文的表流回 `22` 的校验：

| 回传项 | 为什么 descriptor 侧需要 |
|---|---|
| **本次使用的 `FormatUsage` 集合** | `22` §5.2 的「最容易犯的错」：同一格式在 `Attachment` 与 `Sample` 下的候选不同。但 usage 由**调用**决定（`newTextureWithDescriptor:` 的 usage 来自 descriptor 字段，而 `MTLRenderPassColorAttachmentDescriptor` 的 texture 的 usage 来自它作为 attachment 这件事）。所以方法侧必须把「这个 descriptor 正在被用于哪个调用」传给格式判定 |
| **`PipelineOptions`** | 13 个 `resourceIndex` 字段（`22` R25）产出 `Option<IdPlacement>`，但 pipeline descriptor 的那几个要变成 `PipelineOptions::placement`（`40` §3.2），而 `PipelineOptions` 是**方法参数**不是 descriptor 字段（`rt::Device::new_render_pipeline_state(&descriptor, &options)`）。所以 `22` 的校验结果必须经本文的「参数转换」列落到第二个参数上 |
| **当前设备的 `DeviceProperties` 与 limits** | `22` R18 的三道闸要 `DeviceProperties` 的实测上限。那是设备对象的状态，方法侧才有 |

---

## 7. `40` 第 4 节没登记的新 gap

本节是本文最有价值的输出。**判定方法**：对第 1.4.1 节的 87 个 `N` 行，逐条检查它是否落在 `40` 第 4 节的十项之内。不落在之内的，按语义归并成编号 gap。

归并后 **14 个新 gap**。下表按「第一版会不会出问题」排序，不按条数。

### 7.1 新 gap 全表

| 编号 | gap | 条数 | 上游状况 | 本项目第一版处置 | reach 判断 |
|---|---|---:|---|---|---|
| **`N-01`** | **`MTLParallelRenderCommandEncoder` 整族无上游类型** | 1 条 selector（`MTLCommandBuffer::parallelRenderCommandEncoderWithDescriptor:`）+ 整个 `MTLParallelRenderCommandEncoder` 协议 + `MTLParallelRenderCommandEncoderSPI`（`21` §7：2 req + 1 opt） | 全文检索 `ParallelRender` 零命中。`40` §2.2 的对象清单里也没有 | **返回 nil**（第 3.5 节）。不自建录制重放层（违反 `40` §1 规则 1） | **未知，必须先查**（`M-001`）。`_MTLParallelRenderCommandEncoder` 在 Metal.framework 里存在且 APV 实现了工厂方法，说明这条路在真机上是活的 |
| **`N-03`** | **资源 aliasing 与完成状态查询簇** | 9 条（`MTLResourceSPI` 8 + `MTLResource::setOwnerWithIdentity:`） | 无直接落点，但基元齐全（`CommandBuffer::uses` / `encoders_use` / `used_resources` 都公开） | **自建一层「资源在飞账本」**：按 `ObjectId` 记哪些在飞命令缓冲用到它。`waitUntilComplete` 必须用 `wait_until_completed_for` 带超时 | **高**。APV 实现了其中 6 条，说明 Metal 栈内部有人调。aliasing 查询错答会让客户端重用正在用的内存 |
| **`N-02`** | **GPU counter / 采样整族** | 14 条（3 个 encoder 各 1 条 `sampleCountersInBuffer:`、blit 的 `resolveCounters:` 与 2 条 texture access counter、`MTLDevice` 的 5 条、3 条带 descriptor 的 encoder 工厂的 counter attachment 部分） | 上游零覆盖（`counter` / `sample_counters` 全文零命中公开方法） | `counterSets` 返回**空数组**（使 descriptor 永远无效）、`supportsCounterSampling:` 答 NO、采样 selector 为 no-op + degradation | **低**。性能分析面，WindowServer 不依赖。但**必须答空而不是答假值**，否则客户端会去读空缓冲 |
| **`N-04`** | **ray tracing 整族** | 28 条（render 3 阶段 × 3 = 9、compute 4、`MTLDevice` 5、`MTLRenderPipelineState` 1、`MTLComputePipelineState` 1、`MTLHeap` 4、`MTLLibrary` 2、`MTLCommandBuffer` 2） | 上游有统一出口 `RuntimeGap::AccelerationStructures`；Lavapipe 无 `VK_KHR_acceleration_structure` | B 档：descriptor 期拦（第 4.5 节第 7 条）；`supportsRaytracing*` 答 NO | **低**。`22` §5.3 已判 B，但 `40` 第 4 节未登记，所以本文正式登记 |
| **`N-05`** | **mesh / object pipeline state 查询 + binary function 变体** | 11 条（`MTLRenderPipelineState` 10 + `MTLComputePipelineState` 2 中的 1，去重后 11） | 编码侧与 descriptor 侧**有**落点（第 6.2 节），只有 state 查询没有 | 本地按翻译结果答：7 个限值从 `compiled_reflection` 或 `PipelineArtifact` 推（`31` 分册）；`functionHandleWithName:` / `WithBinaryFunction:` 返回 nil | **中**。启用 mesh 路径时必答。`Error::MeshRecordsOverflow` 与「mesh 管线不产生 `PipelineRecord`」说明上游 mesh 是部分实现 |
| **`N-06`** | **屏障与 debug 面的三条孤立 selector** | 3 条（`MTLRenderCommandEncoder::textureBarrier`、`MTLCommandEncoder::barrierAfterQueueStages:beforeStages:`、debug group / signpost 族） | 无 | `textureBarrier` → 用 `memory_barrier_with_scope(BarrierScope::Textures, ..)` 近似并报 degradation；`barrierAfterQueueStages:` → no-op + degradation；debug 族 → 本地簿记 | **中**。`textureBarrier` 是旧式 framebuffer-fetch 之外的自读自写路径，WindowServer 的旧代码路径可能用。近似是否够记 `M-011` |
| **`N-07`** | **depth bounds test**（`setDepthTestMinBound:maxBound:`） | 1 条 | 无 | no-op + degradation。**但 APV 实现了它**（`PGSerializerRenderCommandEncoder +0x141A3`），说明真机上有人设它 | **中**。depth bounds 失效的后果是画多了东西而不是少画，所以不是静默丢失，但会有性能与正确性影响 |
| **`N-08`** | **`setColorAttachmentMap:`** | 1 条 | 无 | no-op + degradation | **低**。attachment 重映射，罕见 |
| **`N-09`** | **MTLIO 整族** | 10 条（`MTLIOCommandQueue` 5 + `MTLDevice` 5 工厂） | 无 | `newIOCommandQueueWithDescriptor:error:` → nil + `Unsupported`，使 5 条协议方法不可达 | **低**。`22` §5.3 已判 B；本文正式登记为 gap |
| **`N-10`** | **MTL4 面整族** | 8 条（`MTLDevice` 的 8 个 MTL4 工厂）+ `MTLCommandQueueSPI` / `MTLCommandBufferSPI` 里的 MTL4 部分 | 无 | 全部 nil。`supportsFamily(Metal4)` 必须 false（`60` 已要求，`91` 实测 APV 也是 False） | **低**。macOS 26 的新 API，系统自身在 Intel + APV 上不用它 |
| **`N-11`** | **tensor 族** | 3 条（`MTLDevice` 2 + `MTLBuffer` 1） | 无 | nil + `Unsupported` | **低** |
| **`N-12`** | **texture view pool / resource view pool** | 1 条（`newTextureViewPoolWithDescriptor:error:`） | 无；`IdPlacement` 可部分替代 | nil + `Unsupported` | **低** |
| **`N-13`** | **MSL 源码前端与 function stitching** | 4 条（`newLibraryWithSource:` ×2、`newLibraryWithStitchedDescriptor:` ×2） | `rt::Device::new_library_with_source` 存在但必然 `Err`（参数名 `_source`） | nil + `Unsupported`（`needs = "MSL front end"`）。这是**边界 ① 的设计选择**，不是意外缺口 | **低**。系统组件用预编译 metallib |
| **`N-14`** | **placement sparse** | 2 条（`newBufferWithLength:options:placementSparsePageSize:`、`supportsPlacementSparse`）+ `MTLHeap` 的 sparse 放置 | 上游有 sparse 全族类型，但 **Lavapipe 的 sparse 仅 Linux** | `supportsPlacementSparse` 答 NO；带 sparse page size 的工厂 nil + `Unsupported` | **低**。`40` §2.2 已记能力缺失，但未登记为「本项目要补的事」 |

合计 `N` 条数：1 + 9 + 14 + 28 + 11 + 3 + 1 + 1 + 10 + 8 + 3 + 1 + 4 + 2 = **96**。第 1.4.1 节的 `N` 计数是 87，差 9 条来自跨协议重复计入（例如 `N-04` 的 `MTLHeap` 4 条与 `MTLLibrary` 2 条在第 1.4.1 节分别记在各自协议行里，而第 1.4.3 节的 1202 条口径已去重）。**以第 1.4.1 节的 87 为逐条口径，以本节的 14 个 gap 为语义口径。**

### 7.2 最严重的是 `N-01`，理由

`INFERRED`（严重度判断）；`KNOWN`（下表的事实列）。

| 维度 | `N-01`（parallel render encoder） | 其余 13 个 gap |
|---|---|---|
| Metal 协议地位 | `parallelRenderCommandEncoderWithDescriptor:` 是 **`MTLCommandBuffer` 的 required 方法** | 多数在 SPI 或可选面 |
| 真机是否活 | **APV 实现了它**（`AppleParavirtCommandBuffer +0x17F06`），且 `_MTLParallelRenderCommandEncoder` 类在 Metal.framework 里**实测存在**（`91` §2.2：size 232 / im 28 / ivar 20），`PGSerializerParallelRenderCommandEncoder` 也存在并实现 `endEncoding` | `N-07` 同样「APV 实现了」，但只影响 depth bounds；其余多数 APV 也不实现 |
| 能否本地答掉 | **不能。** 它要返回一个能编码的对象，而上游没有第二个写入口 | `N-02` / `N-08` / `N-09` / `N-10` / `N-11` / `N-12` / `N-14` 都能答 nil / 空 / NO 而语义正确 |
| 能否按能力拒绝 | **不能干净地拒绝。** Metal 没有 `supportsParallelRenderCommandEncoder` 这样的查询，客户端只能靠返回值判断。返回 nil 后客户端的行为未知 | `N-04` / `N-09` / `N-13` 都有配套的 `supports*` 查询可以提前答 NO |
| 补它要做什么 | 一层「每子编码器录制 + 按创建序重放」。**这正是 `40` §1 规则 1 禁止的**（不得复制上游的 Encoder、不得自行推导绑定） | `N-03` 要一层资源在飞账本，用的是上游的公开基元，不违反规则 1 |
| 失败形态 | 客户端拿到 nil 后若不检查就会崩，若检查则这一帧整个 pass 不画 | 多数是 degradation 或可观测的 `NSError` |

**第二严重的是 `N-03`**：条数不多但**错答会导致内存被重用**（客户端按 `doesAliasResource:` 的答案决定能不能复用 heap 里的空间）。它比 `N-01` 可控，因为上游基元齐全，只是没人被分配这项工作。

### 7.3 每个新 gap 的归属分册

`INFERRED`。写明归属是为了不让这 14 项再次无人认领。

| gap | 归属 | 需要做什么 |
|---|---|---|
| `N-01` | **本文 + `50-IPC-HELPER.md`** | 第一版返回 nil；`M-001` 查清 reach 后若必须支持，方案在 `50` 的 wire 层讨论（子编码器各自一条命令流，由 helper 按创建序合并） |
| `N-03` | **本文 + `50`** | 资源在飞账本挂在 `50` 的对象表上（它已经按 `ObjectId` 索引） |
| `N-02` | `60-CAPABILITY-MATRIX.md` | 进能力矩阵的「明确不支持」列 |
| `N-04` | `60` | 同上；`22` §5.3 已有 B 档条目，补一条 `40` §4 的交界 |
| `N-05` | `31-PIPELINE-ARTIFACT.md` | 7 个限值从 `PipelineArtifact` / `compiled_reflection` 推 |
| `N-06` | 本文 + `60` | `textureBarrier` 的近似映射正确性记 `M-011` |
| `N-07` | `60` | 进「比 Metal 宽松」列（我们不做 depth bounds 剔除） |
| `N-08` | `60` | 同上 |
| `N-09` | `60` | 进「明确不支持」列 |
| `N-10` | `60` | 同上；与 `supportsFamily(Metal4) = false` 一致 |
| `N-11` | `60` | 同上 |
| `N-12` | `60` | 同上 |
| `N-13` | `00-OVERVIEW.md` 边界 ① / `30-SHADER-AIR.md` | 这是设计选择，`60` 记为「按设计不支持」 |
| `N-14` | `60` | 已有 `40` §2.2 的能力记录，补一条「本项目回答什么」 |

---

## 8. 与 `40` 第 4 节十项的交界表

`40` 第 4 节列了上游明确不做、留给本项目的十项。本节给**交界表**：每一项在本文的映射表里表现为什么。不重复第 4 节的内容。

| # | `40` §4 的事项 | 在本文的映射表里表现为 | 涉及条数 | 上游给的基元（本文已给精确签名的） |
|---:|---|---|---:|---|
| 1 | 真实 IOSurface 与 Mach VM | `MTLTexture::iosurface` / `iosurfacePlane` 两条无落点（第 5.8 节 `S4-1`）；`MTLDevice::newTextureWithDescriptor:iosurface:plane:` 是 `C`（组合，第 5.19.1 节）；`MTLDeviceSPI` 的 IOSurface 标志无落点 | 2 + 1`C` + SPI 若干 | `Device::new_buffer_with_bytes_no_copy`、`Buffer::new_texture_with_iosurface_plane`、`Buffer::host_backing`、`Device::new_texture_with_vk_image` / `new_buffer_with_vk_buffer`、`Device::texture_level_info`、`HostMemory` 的四条退路 |
| 2 | 分散后备（`replaceBackingWithRanges:`、`detachBacking`） | `MTLBufferSPI` / `MTLHeap` 的后备 selector（本文未逐条枚举，`M-004`）；落点在第 5.7.1 节 | SPI 若干 | `Buffer::rebind_bytes_no_copy`、`Heap::rebind_bytes_no_copy`、`Buffer::detach_backing`、`Heap::detach_backing`、`CommandBuffer::used_resources`、`CommandBufferError::EncodedUseRebound` / `DetachedBacking` |
| 3 | Apple 的序列化管线 descriptor 与 guest 可见标识 | `MTLRenderPipelineState::newRenderPipelineDescriptorForSpecialization`（第 5.13 节 `S4-3`）；`MTLDeviceSPI` 的 pipeline/variant 组 6 条（第 5.20.1 节） | 1 + 6 | `RenderPipelineState::resource_index` / `unique_identifier`、`ComputePipelineState::resource_index` / `unique_identifier`、`IndirectCommandBuffer::resource_index` / `unique_identifier` / `identifier_unmeasured`、`Device::reserve_resource_ids`、`IdPlacement` |
| 4 | presentation（`CAMetalLayer`、`MTLDrawable` 全族） | `MTLDrawable` 6 条全部 `S4-4`（第 5.17 节）；`MTLCommandBuffer::presentDrawable:` ×3（第 5.3.1 节） | 6 + 3 | `Texture::is_drawable`；**本项目不走 swapchain**，`Device::new_command_queue_for_presenting` 不用 |
| 5 | OS 服务（时钟、定时器、线程、偏好、HostVm、启动器） | `MTLDevice::queryTimestampFrequency` / `sampleTimestamps:gpuTimestamp:`（第 5.19.4 节 `L`/`C`）；K-13 的编译线程池；`MTLDeviceSPI` 的 setter 组 | 2 + 若干 | 自由函数 `rt::host_time() -> f64`；`rt::process_exiting() -> bool`；`40` §6.6 的 `gpu_times_from_host` |
| 6 | 跨进程 `MTLSharedEvent` 与 `MTLSharedTextureHandle` | `MTLSharedEvent::newSharedEventHandle`（第 5.16 节 `U` 但**仅进程内**）；`MTLTexture::newSharedTextureHandle`（第 5.8 节同）；`MTLDevice::newSharedEventWithHandle:` / `newSharedTextureWithDescriptor:` / `newSharedTextureWithHandle:`（第 5.19.1 节，均标 `*(partial)*`） | 5 | `SharedEventHandle`、`SharedTextureHandle`（进程内）、`SharedEvent::vk_semaphore` |
| 7 | Metal plugin 注册、IOGPU service、IOUserClient、display provider / sink、签名安装启动 | **不在本文的 selector 面上**。唯一交界：`MTLDeviceSPI` 的 `featureProfile` / `vendorName` / `familyName` / `productName` 等自报字段（第 5.20.1 节「其它」组） | 0 直接 | 无 |
| 8 | Apple 的格式与设备描述 | `MTLDeviceSPI::pixelFormatInfo` 系（第 5.20.2 节 `U` + `S4-8`）；`gpuCoreCount`（`Option` 为 `None`）；无实测覆盖的私有 limit / flag（第 5.19.4 节的 `B` 行与 `M-009`） | 若干 | `Device::pixel_format_info`、`Device::pixel_format_capabilities`、`Device::private_properties`、`metal2vulkan::metal::format` |
| 9 | Vulkan loader 与 Lavapipe 的 macOS x86_64 构建与打包 | **不在 selector 面上**。交界是 `DeviceOptions::loader`（`40` §6.4） | 0 | `Error::LoaderNotFound { tried }` |
| 10 | 进程模型、wire protocol、对象表与 generation、崩溃恢复 | **贯穿全表**：K-06 的对象表用 `ObjectId`；第 4.2.1 节的 code 稳定映射表与 `50` 共用；第 3.3 节的 `commit_failed` 是崩溃恢复的注入点 | 全表 | `Buffer/Texture/Heap::object_id`、`CommandBuffer::used_resources` / `commit_failed` / `set_submission_check`、`Submission`、`FailedEncoders` |

### 8.1 交界表的两条读法

`INFERRED`。

1. **第 7 项与第 9 项在 selector 面上是零交界。** 它们是本项目的本体工作但不出现在 Metal 的调用面上，所以本文的覆盖率计数里看不到它们。实现时不要因为「本文没提」就以为不用做。
2. **第 10 项贯穿全表，不是一个局部。** 它决定了本文每一行的「对象参数怎么解析」。`50-IPC-HELPER.md` 的对象表如果换了键（例如改回指针），本文第 5 节的每一行都要重新审。所以 K-06 的「键是 `ObjectId`」是本文与 `50` 之间的硬契约，不是建议。

---

## 9. 验收：adapter fixture 的形状

`40` §3.3 末尾要求「为上游 `docs/RUNTIME-PORTING.md` 的每一节建一条 adapter 单元测试 fixture，证明转发指向上游的精确调用，且 ObjC 侧 `class_copyMethodList` 的 selector 与 type encoding 与 `21` 的清单逐项一致」。本节把它具体化。

### 9.1 fixture 的形状

`INFERRED`。一条 fixture 由四部分组成，缺一不可：

```
fixtures/
  render_encoder/
    set_fragment_texture.fixture.json      ① 输入：selector + 实参（含 encoding 校验）
    set_fragment_texture.expect.json       ② 期望：上游调用序列
    set_fragment_texture.rs                ③ 驱动：ObjC 调用的发起
  _shared/
    upstream_recorder.rs                   ④ 记录器：拦上游调用
```

#### ① 输入（`.fixture.json`）

```json
{
  "protocol": "MTLRenderCommandEncoder",
  "selector": "setFragmentTexture:atIndex:",
  "encoding": "v32@0:8@16Q24",
  "spec_section": "42 §5.4.3",
  "args": [
    { "kind": "object", "protocol": "MTLTexture", "handle": "tex_A" },
    { "kind": "nsuinteger", "value": 3 }
  ]
}
```

`encoding` 字段是**断言**：fixture 加载时用 `method_getTypeEncoding` 读实际实现的 encoding，与此字段逐字节比较。不等则 fixture 失败。这条直接兑现 `40` §3.3 的后半句要求。

#### ② 期望（`.expect.json`）

```json
{
  "upstream_calls": [
    {
      "receiver": "RenderCommandEncoder",
      "method": "set_fragment_texture",
      "args": [
        { "kind": "option_ref", "some": true, "object_id": "$tex_A.object_id" },
        { "kind": "u32", "value": 3 }
      ]
    }
  ],
  "objc_return": { "kind": "void" },
  "degradations": [],
  "errors": []
}
```

硬规则（`INFERRED`）：

| 规则 | 内容 |
|---|---|
| `upstream_calls` 是**有序且完备**的 | 不只断言「调了 `set_fragment_texture`」，还断言**没调别的**。`C` 行的 fixture 因此会列出多个调用，顺序固定 |
| 对象参数断言 `object_id` 而非指针 | K-06 的硬契约；指针会随运行变化 |
| `U` 行的 `upstream_calls` 长度必须是 **1** | 长度不是 1 说明这行其实是 `C`，本文的分类错了 |
| `L` 行的 `upstream_calls` 必须是**空数组** | 空数组是断言，不是「没写」。它证明本地可答的行真的没碰上游 |
| `N` 行必须断言 `objc_return` 与 `degradations` / `errors` | 证明无落点的行给的是确定答案，不是静默成功 |

#### ③ 驱动（`.rs`）

每条 fixture 一个 `#[test]`，三步：建最小对象图（device → queue → command buffer → encoder）、按 `.fixture.json` 发起 ObjC 调用、与 `.expect.json` 比对。

#### ④ 记录器

`INFERRED`。记录器是**唯一**需要工程判断的部分。三种实现，按侵入性从低到高：

| 方案 | 做法 | 优点 | 缺点 |
|---|---|---|---|
| **A. adapter 内的转发层注入**（**推荐**） | adapter 的每个转发点经一个 `trait UpstreamSink`，产品构建用直通实现，fixture 构建用记录实现。`#[cfg(test)]` 或 feature gate | 不碰上游；记录的是**我们的意图**，正是要断言的东西；零运行期开销 | 要求 adapter 从一开始就把转发走一层 trait。**所以这是对实现结构的要求，不只是测试要求** |
| B. 上游的可观测通道反推 | 用 `DeviceOptions::record_executions` + `CommandBuffer::executions` + `WorkCounts` 差值 | 不需要结构约束 | 粒度太粗：`executions` 只给「哪个管线跑了」，看不出 `set_fragment_texture` 的 index |
| C. 符号级拦截 | `dyld` interpose 或链接期替换 | 完全透明 | Rust 的 `pub fn` 多数被内联或泛型单态化，符号不稳定 |

> **R42-09**（`INFERRED`）：采用方案 A，并把它写成实现约束：**adapter 的每一次上游调用必须经一个可替换的 sink。** 这同时给了三个附带好处：① 第 4.3 节 R42-05 的「转发失败计数」有天然挂点；② 第 7.1 节每个 `N` 行的 degradation 记录有天然挂点；③ `50-IPC-HELPER.md` 的 wire 层重放可以复用同一 sink。

### 9.2 怎么断言「转发到了正确的上游调用」

三层断言，逐层收紧。`INFERRED`。

| 层 | 断言 | 发现什么错 |
|---|---|---|
| **L1 调用身份** | `receiver` + `method` 字符串与本文第 5 节的「上游调用」列逐字相等 | 转发到了错的方法（例如 render 的 `set_threadgroup_memory_length` 三参形态被当成 compute 的两参形态） |
| **L2 实参等值** | 每个参数的类型标签与值相等；`Option` 的 `Some`/`None` 相等；slice 的长度与逐元素相等；`Range` 的 start/end 相等 | K-07（slice 过滤掉 nil 导致错位）、K-08（`NSRange` 当成 start/end）、K-03（缺省值补错）、K-15（宽度截断） |
| **L3 调用集合完备** | 实际调用序列与期望序列**完全相等**（长度 + 顺序 + 内容） | 多调（例如一次绑定被转发两次）、少调（`C` 行漏了组合中的一步）、顺序错（`C` 行的 `copy_from_texture_to_buffer` 与 `copy_from_buffer_to_texture` 反了） |

**L2 的一条特别规则**：`impl Into<DrawPrimitiveType>` 这类泛型参数必须断言**转换后的值**，不是转换前的 raw。理由：`DrawPrimitiveType::from_raw` 对值 5–8 与值 9 的处置不同（K-11），断言 raw 看不出 from_raw 是否被调用。

### 9.3 与 `91` 的运行期 selector 表交叉检查

`91` §2.4 给了 25 个协议的运行期确证条目数。本文的覆盖计数（第 1.4 节）必须与它对账。`INFERRED`（检查方法）。

#### 9.3.1 四项对账

| 检查 | 方法 | 判定 |
|---|---|---|
| **C1 条目数一致** | 在目标 guest（或 `91` 的运行器）上对每个协议跑 `protocol_copyMethodDescriptionList`（required + optional 各一次），计数与 `91` §2.4 逐协议比 | 不等 → `91` 的基线变了（点版本差异），本文的计数全部失效，必须重算 |
| **C2 selector 集合一致** | 同上，取 selector 名集合，与本文第 5 节的表的左侧逐项比 | 本文少了 → 补行；本文多了 → 该 selector 不在这个协议里，分类错 |
| **C3 encoding 一致** | 对每个 selector 比 `method_getTypeEncoding`（我们的实现）与 `protocol_getMethodDescription`（协议声明）与本文的 `enc` 列 | 三者不等 → 转发会在 ABI 层崩。这是 `40` §3.3 的后半句要求 |
| **C4 覆写三态一致** | 对本项目的每个类跑 `class_copyMethodList`，与本文的 `U`/`C`/`L`/`S4`/`N` 分类对账：`U`/`C` 必须是显式覆写；`L`/`N` 必须是显式覆写（R42-07）；只有第 5.20.1 节明确决定继承的才允许不在列表里 | 有 selector 既不在覆写列表也不在「明确继承」清单 → 违反 R42-08 |

#### 9.3.2 C2 的四处已知偏差（必须在对账脚本里白名单）

`KNOWN`。这四处是 `91` 已经证伪 `21` 的地方（第 0.4 节），对账时不要当成新问题：

| 偏差 | 处理 |
|---|---|
| `_MTLRenderCommandEncoder` / `_MTLComputeCommandEncoder` / `_MTLBlitCommandEncoder` / `_MTLBuffer` / `_MTLTexture` / `_MTLEvent` 这些类名不存在 | 对账脚本不按类名查，按**协议名**查。本项目自建类的名字由实现定 |
| 资源链多两层（`_MTLResource` / `_MTLAllocation`） | `MTLResource` 的 `label` / `setLabel:` / `allocatedSize` 的「实现者」是基类，`class_copyMethodList` 在我们自己的类上看不到它们。C4 的判定要沿继承链查 |
| `MTLLibraryBuilder` / `MTLLibraryDataWithArchive` 不存在 | 第 5.11 节不依赖它们 |
| `MTLDeviceSPI` 重复声明 `MTLDevice` 的 22 条 | C1 的合计用去重后的 1202，不用 1224 |

#### 9.3.3 逐节 fixture 清单（34 条 + 本文新增 11 条）

`40` §3.3 要求「上游 `RUNTIME-PORTING.md` 的每一节」一条。上游有 34 节。本文另加 11 条，覆盖上游文档没有节但本文有表的部分。`INFERRED`

| # | fixture 组 | 对应本文节 | 代表 selector（最少一条） |
|---:|---|---|---|
| 1–2 | `Handle`、`Platform` | 5.0、5.19.1 | `newCommandQueue` |
| 3–4 | `BlitCmd`、`BlitEncoder` | 5.6 | `copyFromBuffer:sourceOffset:toBuffer:destinationOffset:size:` |
| 5 | `CommandQueue` | 5.2.1 | `commandBuffer` |
| 6 | `CommandBuffer` | 5.3.1 | `renderCommandEncoderWithDescriptor:` |
| 7–8 | `ComputeCmd`、`ComputeEncoder` | 5.5、5.5.1 | `dispatchThreadgroups:threadsPerThreadgroup:`、`encodeStartIf:offset:comparison:referenceValue:` |
| 9 | `TextureDescriptor` | 6.1（交界） | `newTextureWithDescriptor:` |
| 10 | `RenderPassDescriptor` | 6.1 | `renderCommandEncoderWithDescriptor:` |
| 11–12 | `RenderPipelineDescriptor`、`ComputePipelineDescriptor` | 5.19.1 | `newRenderPipelineStateWithDescriptor:error:` |
| 13 | `GpuDevice` | 5.19.1 | `newBufferWithLength:options:` |
| 14 | `SharedEvent` | 5.16 | `waitUntilSignaledValue:timeoutMS:` |
| 15–19 | `IndirectCommandBuffer`、`IcbRenderCmd`、`IndirectRenderCommand`、`IcbComputeCmd`、`IndirectComputeCommand` | 10（速查表） | `newIndirectCommandBufferWithDescriptor:maxCommandCount:options:` |
| 20–22 | `RateMap`、`RateMapDescriptor`、`RateMapLayerDescriptor` | 10 | `newRasterizationRateMapWithDescriptor:` |
| 23–24 | `RenderCmd`、`RenderEncoder` | 5.4.1–5.4.8 | **每个子节至少一条**（见下） |
| 25–28 | `GpuResource`、`Buffer`、`Texture`、`Heap` | 5.9.1、5.7、5.8、5.10 | `isAliasable`、`contents`、`replaceRegion:...`、`newBufferWithLength:options:` |
| 29–30 | `SamplerState`、`DepthStencilState` | 5.15 | `gpuResourceID` |
| 31–33 | `ComputePipeline`、`RenderPipeline`、`Library` | 5.14、5.13、5.11 | `threadExecutionWidth`、`reflection`、`newFunctionWithName:` |
| 34 | `DeviceCaps` | 5.19.3 | `supportsFamily:` |
| **35** | **object 阶段绑定**（上游文档无此节） | **5.4.5** | `setObjectBuffer:offset:atIndex:` |
| **36** | **mesh 阶段绑定**（同上） | **5.4.6** | `setMeshBuffer:offset:atIndex:` |
| **37** | **mesh draw**（同上） | **5.4.7** | `drawMeshThreadgroups:threadsPerObjectThreadgroup:threadsPerMeshThreadgroup:` |
| **38** | **tile / mesh pipeline 构造**（上游文档的 `Platform` 节不列） | **5.19.1** | `newRenderPipelineStateWithTileDescriptor:options:reflection:error:` |
| **39** | **消费语义**（第 3 节） | **3.2、3.3** | `endEncoding` 后调 `setFragmentTexture:atIndex:`，断言 `commit_failed` 被调且 `upstream_calls` 不含 `set_fragment_texture` |
| **40** | **错误穿透**（第 4 节） | **4.2** | 制造一个 `MetalError`，断言 `NSError` 的 domain / code / description 与上游给的逐字节相同 |
| **41** | **`void` selector 上的 `Err`** | **4.3** | 让 `set_depth_bias` 返回 `Err`，断言命令缓冲失败且进程不退出 |
| **42** | **`L` 行不碰上游** | **5.19.4** | `isLowPower`，断言 `upstream_calls == []` |
| **43** | **`N` 行给确定答案** | **7.1** | `parallelRenderCommandEncoderWithDescriptor:` 返回 nil 且记了一条 `N-01` 的日志 |
| **44** | **`MTLResourceSPI` 的 `N-03` 簇** | **5.9.2** | `doesAliasResource:`，断言答案来自我们的 aliasing 表而非上游 |
| **45** | **`MTLDeviceSPI` 的三态覆盖** | **5.20.3** | 对 507 条跑 C4 对账，断言零「没想过」 |

第 23–24 组的子 fixture（`INFERRED`，render encoder 的覆盖必须按子节拆，否则 131 条里只测到一两条）：

| 子 fixture | 本文节 | 代表 selector |
|---|---|---|
| 23a 固定功能状态 | 5.4.1 | `setViewport:`、`setDepthStencilState:`（nil 分支） |
| 23b vertex 绑定 | 5.4.2 | `setVertexBuffers:offsets:withRange:`（含 nil 项与 `first` 偏移） |
| 23c fragment 绑定 | 5.4.3 | `setFragmentSamplerState:lodMinClamp:lodMaxClamp:atIndex:`（**`C` 行**，断言两个 1 元素 slice） |
| 23d tile 绑定 | 5.4.4 | `setTileTextures:withRange:` |
| 23e draw 短形态 | 5.4.7 | `drawPrimitives:vertexStart:vertexCount:`（**断言补了 `instance_count = 1`**） |
| 23f draw 的私有 primitive | 5.4.7 | primitive type = 5（triangle fan，合法）与 9（**断言命令缓冲以 GPU 方式失败，不是被拒绝**） |
| 23g use 的 stages 补全 | 5.4.8 | `useResource:usage:`（**断言补了全 stages**） |
| 23h ICB `_checked` | 5.4.8 | `executeCommandsInBuffer:withRange:`（**断言走的是 `_checked` 形态**） |
| 23i SPI 的 `AppleOnly` | 5.4.9 | `setLineWidth:` 传 2.0（断言 `AppleOnly::LineWidth`） |

### 9.4 验收门

全部通过才算 `40` §3.3 兑现。`INFERRED`。

| # | 门 |
|---:|---|
| 1 | 第 9.3.3 节的 45 组 fixture 全部存在且通过 |
| 2 | C1 对账：25 个协议的条目数与 `91` §2.4 逐协议相等（或差异有记录的点版本原因） |
| 3 | C2 对账：selector 集合零差异（白名单除外） |
| 4 | C3 对账：encoding 三方一致，零差异 |
| 5 | C4 对账：`MTLDeviceSPI` 507 条零「没想过」（R42-08） |
| 6 | 第 1.4.1 节的 590 行里，每个 `U` 行都有一条 fixture 断言 `upstream_calls` 长度为 1 |
| 7 | 每个 `C` 行都有一条 fixture 断言完整的调用序列（顺序敏感） |
| 8 | 每个 `L` 行都有一条 fixture 断言 `upstream_calls == []` |
| 9 | 每个 `N` 行都有一条 fixture 断言确定答案 + 日志 |
| 10 | R42-09 的 sink 结构到位：产品构建的 sink 是直通实现，且有一条测试证明它零开销（inline 后无额外分支） |
| 11 | 第 4.3 节 R42-05 的「转发失败计数」在一次完整测试套后为 **0** |
| 12 | 一次完整测试套累积的 degradation code 集合已导出并与 `60-CAPABILITY-MATRIX.md` 的声明对照（`40` §7.5 第 5 项） |

---

## 10. 本文范围外协议的落点速查表

第 1.4.3 节说明：`91` §2.4 的 25 个协议之外还有一批协议，不在 `21` §8.0 的第一版必须实现集合里。本节给它们的上游落点**速查**，不逐条展开。目的是实现期扩面时不必重新读上游源码。`KNOWN`（接收者与方法数取自第 1.2 节的抽取）。

| Metal 协议 / 类 | 上游类型（定义处） | 公开方法数 | 承重方法 |
|---|---|---:|---|
| `MTLArgumentEncoder` | `ArgumentEncoder`（`argument_encoder.rs:168`） | 24 | `set_argument_buffer`、`set_argument_buffer_start_offset_array_element`、`set_buffer(s)`、`set_texture(s)`、`set_sampler_state(s)`、`set_render_pipeline_state(s)`、`set_compute_pipeline_state(s)`、`set_indirect_command_buffer(s)`、`set_visible_function_table(s)`、`encoded_length`、`alignment`、`constant_data(index)`、`layout()`、`new_argument_encoder_for_buffer_at_index` |
| `MTLIndirectCommandBuffer` | `IndirectCommandBuffer`（`indirect_command_buffer.rs:966`） | 25 | `indirect_render_command_at`、`indirect_compute_command_at`、`commands(range)`、`reset_with_range`、`size`、`gpu_resource_id`、`resource_index`、`unique_identifier`、`identifier_unmeasured`、`command_writes`、`gpu_written`、`may_name_encoding_states`、`as_resource`、资源族 getter |
| `MTLIndirectRenderCommand` | `IndirectRenderCommand`（同文件） | 32 | 11 条命令（`draw_primitives`、`draw_indexed_primitives`、`draw_patches`、`draw_indexed_patches`、`set_render_pipeline_state`、`set_vertex_buffer`、`set_vertex_buffer_with_stride`、`set_fragment_buffer`、`set_barrier`、`clear_barrier`、`reset`）+ getter（`command_type`、`vertex_buffer`、`fragment_buffer`、`has_barrier`、`draw`、`pipeline_unique_identifier`、`pipeline_state`、`pipeline_id`）。**宽度是 `u64` / `i64`，与 render encoder 的 `u32` / `i32` 不同**（K-15） |
| `MTLIndirectComputeCommand` | `IndirectComputeCommand`（同文件） | 21 | 11 条命令 + getter（`command_type`、`kernel_buffer`、`stage_in_region`、`threadgroup_memory_length`、`has_barrier`、`dispatch`、`imageblock_size`、`pipeline_unique_identifier`） |
| `MTLRasterizationRateMap` | `RasterizationRateMap`（`rate_map.rs:160`） | 12 | `layer_count`、`physical_granularity`、`physical_size_for_layer`、`screen_size`、`parameter_buffer_size_and_align`、`copy_parameter_data_to_buffer`、`map_physical_to_screen_coordinates`、`map_screen_to_physical_coordinates`、`mutability`、`reset_using_descriptor`。**零层的 map 与未 reset 的可变 map 被拒（Metal 的进程会结束）** |
| `MTLBinaryArchive` | `BinaryArchive`（`binary_archive/mod.rs:70`） | 7 | `add_render_pipeline_functions`、`add_compute_pipeline_functions`、`add_tile_render_pipeline_functions`、`serialize_to_url` |
| `MTLVisibleFunctionTable` | `VisibleFunctionTable`（`function_table.rs:640`） | 15 | `set_function`、`set_functions` + 资源族 getter。**对象可建，通过表调用被拒**（`40` §2.4） |
| `MTLDynamicLibrary` | `DynamicLibrary`（`dynamic_library.rs:32`） | 6 | `install_name`、`serialize_to_url`、`preloaded_library`。**链接使用被拒** |
| `MTLResourceStateCommandEncoder` | `ResourceStateCommandEncoder`（`sparse/encoder.rs:60`） | 7 | `update_texture_mapping(s)`、`update_texture_mapping_indirect`、`move_texture_mappings`、`update_fence`、`wait_for_fence`、`end_encoding(self)`。**macOS 上 sparse 不可用** |
| `MTLAccelerationStructure` 全族、`MTLBVH*`、`MTLTensor*`、`MTLIntersectionFunctionTable`、`MTLArgumentTable`、`MTL4*`、`MTLCounterSampleBuffer`、`MTLCounterHeap`、`MTLIOCommandBuffer`、`MTLIOFileHandle`、`MTLResidencySet`、`MTLLogState`、`MTLCaptureScope` | **无上游类型** | 0 | 分别归 `N-04` / `N-11` / `N-10` / `N-02` / `N-09`，或 `L`（residency set、log state） |

---

## 11. 证据来源

### 11.1 上游（metal2vulkan，commit `219f01365dc4c8eb346816c405b5b17403793764`）

本文的全部上游签名取自**源码**，不取自文档（`40` §0 的要求）。抽取方法与结果见第 1.2 节。

| 路径（`upstream/m2v/`） | 本文用到的内容 |
|---|---|
| `crates/metal2vulkan-runtime/src/render.rs:1313` | `RenderCommandEncoder` 的 116 个公开方法签名（第 5.4 节全部行） |
| `crates/metal2vulkan-runtime/src/compute.rs:154` | `ComputeCommandEncoder` 的 47 个（第 5.5、5.5.1 节） |
| `crates/metal2vulkan-runtime/src/blit.rs:157` | `BlitCommandEncoder` 的 25 个（第 5.6、5.6.1 节） |
| `crates/metal2vulkan-runtime/src/command_buffer/mod.rs:155`、`:308` | `CommandBuffer` 的 40 个 + `CommitFailure` 的三字段（第 3.3、5.3 节） |
| `crates/metal2vulkan-runtime/src/device/mod.rs:102`、`device/create.rs:61` | `Device` 的 95 个 + `DeviceOptions`（第 5.19 节） |
| `crates/metal2vulkan-runtime/src/capabilities.rs:61` | `DeviceProperties` 的 20 字段 + 11 方法（K-14、第 5.19.3 节） |
| `crates/metal2vulkan-runtime/src/buffer.rs:63`、`texture.rs:393`、`heap.rs:274` | `Buffer` / `Texture` / `Heap` 的 25 / 50 / 21 个（第 5.7、5.8、5.10 节） |
| `crates/metal2vulkan-runtime/src/library.rs:33`、`:55`、`:100` | `Library` / `Function` / `FunctionDescriptor`（第 5.11、5.12 节） |
| `crates/metal2vulkan-runtime/src/pipeline/render.rs:100`、`pipeline/mod.rs:204`、`pipeline/options.rs:97` | `RenderPipelineState` / `ComputePipelineState` / `PipelineOptions`（第 5.13、5.14 节） |
| `crates/metal2vulkan-runtime/src/queue.rs:72`、`fence.rs:79`、`event.rs:60`/`:65`/`:70` | `CommandQueue` / `Fence` / `Event` / `SharedEvent` / `SharedEventHandle`（第 5.2、5.16 节） |
| `crates/metal2vulkan-runtime/src/depth_stencil.rs:30`、`sampler.rs:464` | `DepthStencilState` / `SamplerState`（第 5.15 节） |
| `crates/metal2vulkan-runtime/src/indirect_command_buffer.rs:966`、`argument_encoder.rs:168`、`function_table.rs:640`、`rate_map.rs:160`、`binary_archive/mod.rs:70`、`dynamic_library.rs:32`、`sparse/encoder.rs:60`、`texture/shared.rs:41`、`host_memory.rs:126` | 第 10 节速查表 |
| `crates/metal2vulkan-runtime/src/error.rs:64`、`:265`、`:369`、`:387`、`:419`、`:442`、`:498`、`:1267`、`:1877` | `Error` 的 27 个 variant、`DeadlockCause`、`Invalid` / `Nil` / `Unproven` / `MetalError` 的字段、`Problem`、`RuntimeGap`、`CommandBufferError` 的 19 个 variant（第 4 节全部） |
| `crates/metal2vulkan-runtime/src/apple_only.rs:70`、`:124` | `AppleOnly` 的 5 个 variant、`AppleOnlyCall`（第 4.4 节） |
| `crates/metal2vulkan/src/error/mod.rs:330`、`:490` | `Unsupported` 的两字段、`Needs` 的 8 个 variant（第 4.2.2 节） |
| `crates/metal2vulkan/src/pipeline/descriptor.rs:22`、`:297`、`:528`、`:583`、`:629`、`:684`、`:780` | `FunctionDescriptor` / `RenderPipelineDescriptor` / `ComputePipelineDescriptor` / `MeshPipelineDescriptor` / `TileRenderPipelineDescriptor` / `ColorAttachmentDescriptor` / `VertexDescriptor`（第 6.2 节的四处修正） |
| `crates/metal2vulkan/src/metal/state.rs:256`、`bind/state.rs:1421`、`bind/argument_buffer.rs:168`、`library/function.rs:704` | `DepthStencilDescriptor` / `SamplerDescriptor` / `ArgumentDescriptor` / `FunctionConstantValues`（第 6.2 节） |
| `docs/RUNTIME-PORTING.md`（57 KB，34 节，396 行表格，365 行点名 selector，47 行 SPI，46 行 `*(partial)*`） | 命名约定（第 2 节的事实基础）、`*(partial)*` 的标记位置、「Composed from runtime calls」的组合项（第 5.6.1、5.19.1 节的 `C` 行）、「Not the runtime's」（第 8 节交界表） |
| `docs/ARCHITECTURE.md` | 分层（本文第 0 节的全局定位） |
| `docs/API.md`（312 KB，10 节的 tour 形态） | 用法语境的交叉核对。**本文的签名不取自它**：它是教程不是逐符号参考 |
| `LICENSE`、`LICENSE-GPL-2.0`、`LICENSE-GPL-3.0`、`LICENSE-LGPL-3.0` | 许可边界（文件头） |

**抽取可复现**（`KNOWN`）：对 `crates/metal2vulkan-runtime/src/**/*.rs`（排除 `tests/`）按 `impl` 块归属抽取 `pub fn` / `pub unsafe fn`，得 857 条。第 1.2 节的接收者分布表可由此重算。

### 11.2 本项目

| 分册 | 本文用到的内容 |
|---|---|
| `00-OVERVIEW.md` §7 | 证据标签规则（第 0.3 节） |
| `20-OBJC-DEVICE.md` | limits / flags 的取值（第 5.19.4 节的全部 `L` 行指向它）；5 个协议外虚方法 |
| `21-OBJC-OBJECT-FAMILY.md` §8 + 附录 A.1 / A.2 / A.3 | 左侧 selector 名与 x86_64 encoding（第 5 节全部 `enc` 列）；APV 的实现交集；§8.3 的 `MTLDeviceSPI` 9 类普查（第 5.20.1 节）；§2 的 `return nil` 优于 `doesNotRecognizeSelector:` 的结论；§9 的所有权与 ABI 规则（K-12） |
| `22-OBJC-DESCRIPTORS.md` | A/B/C/D 四档（第 4.5 节）；R12–R25（第 2 节多处）；§5 的字段级映射（第 6 节交界）。**本文修正它的四行** |
| `40-RUNTIME-VULKAN.md` | §2 对象清单；§3.1 命名规则（第 2 节的扩展起点）；§3.2 需特别处理的行；§3.3 的索引（本文兑现它）；**§4 十项（第 8 节引用，不重复）**；§5 线程与所有权（第 3 节细化）；**§6 设备创建（引用，不重复）**；§7 可观测性；§8 格式表；§9 验收（第 9.4 节扩展） |
| `60-CAPABILITY-MATRIX.md` | 能力矩阵；第 7.3 节把 10 个新 gap 派给它 |
| `91-RUNTIME-EVIDENCE.md` | §2.2 的四处证伪（第 0.4 节）；§2.4 的协议条目数全表（第 1.1 节的左侧口径）；§2.1 的 `maxBufferLength` = 1 GiB、`argumentBuffersSupport` = 0；§2.3 的 APV 不声明任何 GPU family |
| `31-PIPELINE-ARTIFACT.md` | `PipelineArtifact` 消费契约（第 5.13 节的 17 个扩展、第 7.3 节 `N-05` 的归属） |
| `50-IPC-HELPER.md` | wire error（第 4.2.1 节的 code 稳定映射表与它共用）；对象表（K-06 的硬契约） |
| `docs/METAL2VULKAN_INTEGRATION.md` | §4.3 的三条规则（第 3.5 节与 R42-09 引用规则 1）；§9 许可边界 |

### 11.3 转述声明

对上游文档只做转述与结构化。表格类事实（符号名、签名、参数名、variant 名、文件路径与行号）是接口事实，照实记录。散文段落未连续摘录超过 30 词。**内容已转述以符合许可限制。**

**上游代码未复制进本仓库。** `upstream/m2v` 在 `.gitignore` 里。本文给的「上游签名」是接口声明，不含实现。

---

## 12. 未解决项清单

| 编号 | 事项 | 标签 | 查清方法 |
|---|---|---|---|
| **`M-001`** | **客户端是否真的取 `parallelRenderCommandEncoderWithDescriptor:`**（决定 `N-01` 的优先级，以及是否必须自建录制重放层） | `BLOCKED` | `91` 的 `macos-26-intel` 运行器上 SIP 已关闭：用 `DYLD_INSERT_LIBRARIES` 对 `Metal.framework` 的该 selector 做 method swizzle 计数，分别在 ① 空桌面、② 登录窗口、③ 开 Safari + 动画三个场景下各跑 60 s，记录调用方的 `dladdr` 与调用次数。零调用 → `N-01` 降为低优先级并在第一版返回 nil 定稿；非零 → 记录调用方后在 `50` 分册设计子编码器命令流合并 |
| **`M-002`** | **`MTLDeviceSPI` 507 条的逐条 selector 名 + encoding + 落点**（本文唯一按组而非逐条给的大块，也是最大的未覆盖面） | `BLOCKED` | 三步：① 从 `S-DUMP` 第 1574–2440 行取逐条方法名（已有，只是未进本仓库的表）；② 按 `21` §0.2 验证过的同序配对取 `S-METAL` `protocol_t` 的 encoding；③ 对每条跑第 2 节的 K-02 猜测后回 `upstream/m2v` 源码核对。产出一张 507 行的表追加到本文第 5.20 节。工作量估计：507 行 × 查一次源码 |
| **`M-003`** | **上游 46 行 `*(partial)*` 的具体差异**（上游说「有这个调用但有差别」，差别的内容决定我们是否要在 ObjC 侧补偿，以及能力报告怎么写） | `BLOCKED` | `cargo doc -p metal2vulkan-runtime -p metal2vulkan` 后逐个读那 46 个 item 的 rustdoc；或直接读源码的 doc comment。把每条差异归入三类：① 无需补偿（上游已按 Metal 行为）；② 需 ObjC 侧补偿；③ 需进能力报告的降级。本文第 5 节已标出哪些行是 `*(partial)*`，按那张表逐条过 |
| `M-004` | `MTLCommandQueueSPI`（47）、`MTLCommandBufferSPI`（57）、`MTLFunctionSPI`（23）的逐条 selector 名与 encoding | `BLOCKED` | 同 `M-002` 的三步。`21` §0.3 说这三个协议的定义副本在 `S-APV` 里，所以方法名与 encoding 同在一条 method record 里，不需要配对 |
| `M-005` | `MTLBlitCommandEncoder` 的 24 条 required 里，本仓库只枚举了 23 条，缺的是哪一条 | `BLOCKED` | 运行器上 `protocol_copyMethodDescriptionList(@protocol(MTLBlitCommandEncoder), YES, YES)` 全量列出，与 `21` 附录 A.3 的 23 条 diff |
| `M-006` | `MTLHeap`（21）、`MTLComputePipelineState`（18）、`MTLFence`（3）、`MTLEvent`（3）、`MTLSharedEvent`（5）、`MTLDrawable`（6）、`MTLIOCommandQueue`（5）的 x86_64 encoding | `BLOCKED` | 同 `M-005` 的方法，一次脚本跑完 7 个协议。本文这几节的左侧用的是 Metal 公开 API 名，encoding 列为 `—` |
| `M-007` | Metal 对**重复 `endEncoding`** 与 **`endEncoding` 之后调编码命令**的真实行为（release 版） | `BLOCKED` | 运行器上对 APV 的真实 encoder 做这两件事，观察 ① 进程是否存活、② `commandBuffer.status` / `.error`、③ 画面是否正确。第 3.3 节的两行档位据此定稿 |
| `M-008` | `location` / `locationNumber` / `recommendedMaxWorkingSetSize` 的 APV 实测值 | `BLOCKED` | 运行器上读 `MTLCopyAllDevices()[0]` 的这三个属性（`91` 的脚本已经在读 `registryID` / `hasUnifiedMemory` 等，加三行即可） |
| `M-009` | `supports32BitMSAA`、`supportsPullModelInterpolation`、`supportsQueryTextureLOD`、`supportsShaderBarycentricCoordinates` / `areBarycentricCoordsSupported` 在本栈上该答什么 | `BLOCKED` | 两步：① 运行器上读 APV 的答案作为参照；② 目标 guest 上建设备后对每项跑一次最小功能测试（`80-TEST-HARNESS.md`），实测通过才答 YES。`60` 分册负责定值 |
| `M-010` | `MTLStageInputOutputDescriptor` 的上游对应类型（`22` §5.1 的 `BLOCKED(类型名与是否实现)` 尚未关闭） | `BLOCKED` | 在 `crates/metal2vulkan/src/pipeline/` 下查 stage input/output 相关的 `pub struct`；若无，确认它是否被折进 `ComputePipelineDescriptor` 的字段 |
| `M-011` | `textureBarrier` 用 `memory_barrier_with_scope(BarrierScope::Textures, ..)` 近似是否足够（`N-06`） | `INFERRED` | 两步：① 读 `BarrierScope` 的 variant 与 `memory_barrier_with_scope` 的 rustdoc，确认 texture scope 的语义范围；② 写一个「同一 pass 内写 attachment 再采样它」的最小 case，在目标 guest 上比对像素与参考结果。不等则 `N-06` 从近似降为 refusal |
| `M-012` | `MTLResource::allocatedSize` 在 buffer 上的正确答案（上游 `Buffer` 无此方法，`Texture::allocated_size` 返回 `Option`） | `INFERRED` | 运行器上读 APV 的 buffer / texture 的 `allocatedSize` 与 `length` / 尺寸的关系，推出分配粒度；进 `20` 分册的 limits 表 |
| `M-013` | `MTLDeviceSPI` 的 `gpuCoreCount` 该答什么（上游在 Lavapipe 上为 `None`，`40` §4 第 8 项划给本项目） | `INFERRED` | 两条候选：① 答 `0`（「不是 GPU」）；② 答 Lavapipe 实际用的 LLVM 线程数。先在运行器上读 APV 的答案作为参照，再在目标 guest 上看哪个值不会让客户端做出错误决策（例如按核数分 workgroup） |
| `M-014` | 上游 `Problem` 枚举（`error.rs:498`）的全部 variant 与各自对应的 Metal 行为档位（第 4.3 节的三档分配） | `BLOCKED` | 逐条读 `Problem` 的 variant rustdoc（上游在每个 variant 上注明了 Metal 的行为，第一个 variant 的注释就点明「Metal 也 assert」）。产出一张 `Problem` → ①/②/③ 档的表，追加到第 4.3 节 |
| `M-015` | `MTLCommandBufferError` 的 19 个 variant 到 Metal 的 `MTLCommandBufferError` code 的精确对应（第 4.6 节给的是分组推断） | `INFERRED` | 两边对齐：① 读上游各 variant 的 rustdoc（`CommitFailure::code` 的注释已点名 2 / 8 / 1 / 16 几个码）；② 在运行器上制造对应失败，读 APV 的 `commandBuffer.error.code` |
| `M-016` | `DeviceProperties` 的 11 个方法返回 `Err(RuntimeGap)` 的具体条件（第 4.4 节只说「上游没建这个判定」） | `BLOCKED` | 读这 11 个方法的实现分支；或在目标 guest 上逐个调用并记录 `Err` 的 `RuntimeGap` variant。启动自检（`40` §6.7）顺带落盘即可 |

### 12.1 优先级

`INFERRED`。

1. **`M-001`** 先查：它是唯一可能推翻一个架构决定的（要不要自建录制重放层）。成本低（一次 swizzle 计数），收益高。
2. **`M-002`** 次之：507 条是本文最大的未覆盖面，且 `MTLDeviceSPI` 是 `21` §8.1 算出的 49 条 APV 实现里的大头，不逐条给落点就无法写 device 的转发表。
3. **`M-003`** 第三：46 行 `*(partial)*` 决定能力报告的准确度，也决定哪些行需要 ObjC 侧补偿。不查清就会把「有差别的落点」当成「等价落点」用。

`M-004` / `M-005` / `M-006` 是同一类工作（协议元数据枚举），一次脚本可以一起关掉，建议与 `M-002` 合并成一轮。
