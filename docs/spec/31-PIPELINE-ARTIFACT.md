# 31 — PipelineArtifact 消费契约

文档版本：1.0
基线日期：2026-10-30
归属：`docs/spec/00-OVERVIEW.md` 第 8 节分册 `31`
前置分册：`30-SHADER-AIR.md`（AIR 格式与覆盖率）

## 0. 上游快照与本文范围

同 `30-SHADER-AIR.md` 第 0 节：commit `219f01365dc4c8eb346816c405b5b17403793764`（2026-10-29），crate `0.2.0`（unreleased），许可证 `GPL-2.0-or-later OR LGPL-3.0-or-later`，toolchain `1.98.1`。全部引用路径相对该 commit 的仓库根。

本文回答一个问题：**`metal2vulkan` 的 pipeline 编译输出到底是什么结构，消费方必须做什么、禁止做什么。**

证据标签同 `00-OVERVIEW.md` 第 7 节（`KNOWN`/`INFERRED`/`BLOCKED`/`TESTED`）。本分册内容与 CPU 架构无关。

### 0.1 一句话总结

上游**不是**一个"把 AIR 变成 SPIR-V 的函数"。它是一个**两级的 pipeline 编译与绑定计划器**：

```
Device::compile_*_pipeline(descriptor, budget)
    → ComputePipeline / RenderPipeline        ← 不可变 plain data，可廉价 clone
          .stage(s)      StageModule           SPIR-V words + 创建 shader stage 所需的全部事实
          .layout        PipelineLayout         稠密、无冲突的 descriptor set layout 与 push range
          .interface     PipelineInterface      每个静态使用的 Metal slot、访问方式、证明过的窗口
          .dependencies  Vec<RuntimeDependency> 它依赖的每一项 bind-time 状态与本 profile 的实现机制
          .requirements  Requirements           它的模块对设备的全部要求
          .graphics / .vertex_input / .metal_info  固定功能状态与 Metal 查询答案
          .key / .profile / .variant_bits

pipeline.plan(BindShape)  → BindingPlan         每个 shape 一次，纯函数，可 memo
plan.instantiate_dispatch(Dispatch) → DispatchCommands   每条命令一次
plan.instantiate_draw(DrawCall)     → DrawCommands
```

`BindingPlan` **从不调用 Vulkan** `KNOWN`（`bind/mod.rs` 模块文档首句："The binder never calls Vulkan"）。它产出的全是 plain data，由消费方去记录 Vulkan 命令。

---

## 1. 顶层 artifact

来源：`crates/metal2vulkan/src/pipeline/artifact.rs`。入口：`Device::compile_compute_pipeline`、`Device::compile_render_pipeline`、`Device::compile_tile_pipeline`、`Device::compile_mesh_pipeline`、`Device::compile_render_variant`。

全部 artifact 的共同性质 `KNOWN`（`artifact.rs` 模块文档）：

- **不可变 plain data**；
- **SPIR-V words 在 `Arc` 后面，所以 clone 很便宜**；
- 每个模块对它所针对的 profile 都是合法的，且**恰好**在 `requirements` 之下；
- **落盘缓存的编码是 `cache::PipelineArtifact`，不是 serde**。

### 1.1 `RenderPipeline`

`KNOWN`（`artifact.rs`，`pub struct RenderPipeline`，`#[non_exhaustive]`，`Clone + Debug + PartialEq + Eq`）：

| 字段 | 类型 | 含义 |
|---|---|---|
| `key` | `PipelineKey` | 本 pipeline 的缓存 key（第 9 节） |
| `profile` | `Hash256` | 它所针对的 device profile 的指纹。**缓存载入时必须校验它** |
| `stages` | `Vec<StageModule>` | 见 1.3 的顺序规则 |
| `layout` | `PipelineLayout` | 第 3 节 |
| `vertex_input` | `VertexInputState` | 第 6 节 |
| `graphics` | `GraphicsState` | 第 5 节 |
| `dependencies` | `Vec<RuntimeDependency>` | 第 7 节 |
| `interface` | `PipelineInterface` | 第 4 节 |
| `requirements` | `Requirements` | 第 8 节。"模块对设备的全部要求（是 enable 集合的超集）" |
| `variant_bits` | `u32` | 本 pipeline 能接受的 specialization 与 variant 位 |

方法：

- `runs_stage(at: usize, topology: vk::PrimitiveTopology) -> bool` `KNOWN` —— 一条画 `topology` 的 `VkPipeline` 是否运行 `stages[at]`。规则：除 geometry stage 外全部运行；geometry stage 只运行与其 topology class 匹配的那一个（pipeline 的 geometry stage 按 point、line、triangle 顺序排列）。越界返回 `false`。
- `footprint() -> u64` `KNOWN` —— 本 pipeline 保活的字节数（自身存储 + stage 与 dependency 的 + 每个 stage 的 SPIR-V words、constant blob、entry point、specialization constant、note、attachment 列表）。上游明示这是**下界而非精确值**：layout、vertex input、graphics state、interface、requirements、strategy census 按自身大小计，不走嵌套 map；低估的量被 Metal 的 slot 与 attachment 数量界住，任何模块都长不大它。用于有界 memo 的权重。

### 1.2 `ComputePipeline`

`KNOWN`（`artifact.rs`，`pub struct ComputePipeline`）：

| 字段 | 类型 | 含义 |
|---|---|---|
| `key` | `PipelineKey` | |
| `profile` | `Hash256` | |
| `stage` | `StageModule` | 单数 |
| `layout` | `PipelineLayout` | |
| `dependencies` | `Vec<RuntimeDependency>` | |
| `interface` | `PipelineInterface` | |
| `metal_info` | `ComputePipelineMetalInfo` | 第 5.4 节 |
| `requirements` | `Requirements` | |
| `variant_bits` | `u32` | |

**tile pipeline 也是 `ComputePipeline`** `KNOWN`（`Device::compile_tile_pipeline`）。

### 1.3 `stages` 的顺序规则（必须精确遵守）

`KNOWN`（`RenderPipeline::stages` 的 doc comment）：

1. 基本情形：**vertex，然后 fragment**（后者仅当 rasterization 打开）。
2. post-tessellation vertex 函数的 pipeline：**合成的 vertex stage、合成的 tessellation control stage，然后它的 evaluation stage，然后 fragment stage**。
3. 下列两种情形会插入**三个**合成 geometry stage（每种需求各一组）：
   - fragment 函数读 `[[barycentric_coord]]` 而设备没有 `fragmentShaderBarycentric`；
   - vertex 函数选择自己的 slice 或 viewport 而设备没有对应 output。

   三个 stage 按 **point、line、triangle** 的 topology class 顺序排，位置在 fragment stage **之前**，或者没有 fragment stage 时排在最后。
4. 一条 `VkPipeline` **只运行**与其 draw 的 class 匹配的那一个 geometry stage —— 用 `runs_stage()` 判断，**不要自己数**。
5. mesh pipeline 的 stage 是 object（`TASK_EXT`）、mesh（`MESH_EXT`）、fragment，且**没有 vertex input** `KNOWN`（`pipeline/mod.rs` "Mesh pipelines"）。

> **消费方规则**：遍历 `stages` 时必须对每条 `VkPipeline` 调用 `runs_stage(at, topology)` 过滤，而不是按 `stage.stage` 的值去推。topology class 的映射是上游的内部约定（`POINT_LIST`→0；`LINE_LIST`/`LINE_STRIP`→1；`TRIANGLE_LIST`/`TRIANGLE_STRIP`/`TRIANGLE_FAN`→2；其他 topology 返回 `false`）。

---

## 2. `StageModule`

`KNOWN`（`artifact.rs`，`pub struct StageModule`）。这是"一个 stage 的最终 SPIR-V 与消费方创建 shader stage 所需的全部事实"。

| 字段 | 类型 | 含义与消费规则 |
|---|---|---|
| `stage` | `vk::ShaderStage` | |
| `entry_point` | `String` | 入口点名。**按构造不含 NUL** |
| `spirv` | `Arc<[u32]>` | **SPIR-V 1.5 words，已为本 pipeline relocate 完毕**。另有 `spirv_bytes() -> Vec<u8>` 给需要字节切片的消费方（little-endian） |
| `specialization` | `SpecializationLayout` | specialization constant 及其默认值。**kernel 的默认值是占位符**（local size = 1）：见下方警告 |
| `required_subgroup_size` | `Option<u32>` | tier 钉住某个尺寸时给出，对应 `VkPipelineShaderStageRequiredSubgroupSizeCreateInfo` |
| `stage_flags` | `vk::PipelineShaderStageCreateFlags` | 目前是 `REQUIRE_FULL_SUBGROUPS` |
| `reconvergence` | `Reconvergence` | `Guaranteed` 或 `ImplementationDefined` |
| `precision_notes` | `Vec<PrecisionNote>` | 有意偏离精确 Metal 语义的地方 |
| `strategies` | `StrategyCensus` | 产出该模块的 lowering 策略（覆盖率闸门） |
| `constant_blob` | `Option<Arc<[u8]>>` | 本 stage 在它的 `Synthetic(ConstantBlob)` binding 上读取的常量数据，binder 从 `WriteSource::ConstantBlob { stage }` 填。**每个 stage 有自己的** |
| `rounded_colors` | `Vec<u32>` | 本 fragment stage 在 shader 里 round 其 float 写入的 color attachment，已排序 |
| `specialized_notes` | `Vec<SpecializedNote>` | 只在某些特化下成立的 note（见 `30-SHADER-AIR.md` 6.6） |
| `own_pixel_textures` | `Vec<u32>` | 本 fragment stage 只在本 fragment 自己的像素处读取的 texture slot，已排序 |
| `snapshot_textures` | `Vec<u32>` | 上述中可以通过"同一批图元的较早 draw 拍的快照"来读的那些，已排序 |
| `private_bytes` | `u64` | 本 stage 一个线程保有的私有内存字节数。link 自己造的 stage 是 0 |
| `stats` | `ModuleStats` | 第 2.3 节 |

### 2.1 kernel 的 specialization 默认值是占位符 —— 严重警告

`KNOWN`（`StageModule::specialization`、`stage_flags`、`required_subgroup_size` 三处 doc comment 一致说明）：

> **kernel 的 specialization 默认值是 binder 要替换掉的占位符（local size = 1）。创建每条 compute `VkPipeline` 必须用一个已规划 dispatch 的 `DispatchRegion` 的 `specialization`、`stage_flags` 与 `required_subgroup_size`，绝不用本 stage 的默认值。**

上游进一步点明后果：在默认特化的 local size 1 下使用这些 flag 是**非法用法** —— `VUID-VkPipelineShaderStageCreateInfo-flags-02759`，带 required subgroup size 时是 `-pNext-02757`。

**消费方规则**：
- render/tile/mesh stage 可以用 `StageModule` 上的 `specialization`/`stage_flags`/`required_subgroup_size`（再叠加 `BindingPlan::specialization`）。
- **compute stage 必须**从 `DispatchRegion` 取这三项。一个 Metal dispatch 可以变成多条 Vulkan dispatch（多个 `DispatchRegion`），**每个 region 带自己完整的 specialization**，所以消费方要**为每个不同的 specialization 创建一条 `VkPipeline`** `KNOWN`（`bind/mod.rs` 模块文档）。

### 2.2 精度 note 的读取

`KNOWN`。API 与规则见 `30-SHADER-AIR.md` 6.6 节。要点复述：

- `precision_notes` 本身是"不知道特化时"的答案；
- 知道 pipeline 的特化后用 `precision_notes_under(&SpecializationKey)`；
- 还知道 draw/dispatch 绑定值时用 `precision_notes_bound(&SpecializationKey, &dyn Fn(SpecKey) -> Option<u64>)`，第二个参数从 `BindingPlan::specialized_value(key)` 取；
- 取具体 clause 用 `note_clauses_under` / `note_clauses_bound` / `bound_format_clauses`；
- **保守规则**：stage 没声明且 `bound` 也没给的常量的 test 视为成立（宁可多报 note）。

### 2.3 `ModuleStats`

`KNOWN`（`artifact.rs`，`pub struct ModuleStats`，`#[non_exhaustive]`，有 `serde`）。"finalize verifier 在每次翻译、每种构建里都会数的那些计数"。因为 verifier 数的就是它检查过的模块，而 serialization 与 relocation 只赋字面量、不增删指令，所以这些计数就是 `StageModule::spirv` 里那个模块的。

| 字段 | 类型 | 含义 |
|---|---|---|
| `functions` | `u32` | 函数数：入口点，加上 canonicalization 与 lowering 留在它旁边的那些 |
| `blocks` | `u32` | 全部函数的基本块总数 |
| `reachable_blocks` | `u32` | 从各自函数入口可达的块，**永不超过** `blocks`。差值是 SPIR-V 要求 construct 声明但没有路径到达的 merge block（例如循环内条件的两臂都离开 construct），模块用 `OpUnreachable` 终结它们 |
| `instructions` | `u64` | 指令 + phi + terminator |
| `constructs` | `u32` | 结构化 construct：selection、switch、loop header |
| `loops` | `u32` | 循环数。**structurizer 不造自己的循环，所以这就是输入自己的循环数** |

上游对如何读它给了明确的方法论 `KNOWN`，本项目应照用：

- `blocks` 能多大程度代表驱动实际编译的程序，取决于 `functions`。驱动先内联再计费，所以函数少的模块其 blocks 就是程序的 blocks；而一个从很多点调用一个多块函数的模块，其程序远大于它自己的 blocks，而两种情形在 `blocks` 单看之下一模一样。lowering 自己就会发出这种函数：handle-table 与 root-table 的查找是展开的无分支步骤，发一次，每次访问都调。
- `instructions` 是第二个数字，原因是"每块的实测成本在一个合成模块与一个真实负载之间差了几倍，所以从一个 shader 取的每块数值对下一个 shader 没有预测力"。
- `blocks` 单看说不清那是谁的块。翻译自己会加块（内联，以及 structurizer 按 SPIR-V 要求布置控制流），输入自己也有块。`loops` 与 `constructs` 把两者分开：**`blocks` 涨而 `loops` 不动，说明是翻译自己的工作或同一控制流的不同形状，不是 shader 里有了新控制流。**
- 对比的 AIR 一侧由调用方自己通过 `metal2vulkan-air` 取：输入本身（内联前）的计数 = `metal2vulkan_air::decode` 后数每个 `ir::Function` 的 `body` 的块；canonicalization 产出的 = 走 `DeviceProfile::specialized_entry` 给的 entry。

> **本项目含义**：Lavapipe 是 CPU 渲染，指令数直接等于时间。`80-TEST-HARNESS.md` 应把 `ModuleStats` 的四个数字（`functions`、`blocks`、`instructions`、`loops`）作为每个 pipeline 的性能回归指标落档，并按上游的方法论解读（涨 `blocks` 不涨 `loops` = 翻译侧变化）。

---

## 3. `PipelineLayout`

`KNOWN`（`crates/metal2vulkan/src/pipeline/layout.rs`）。模块文档的三句话就是契约：

> link 分配 binding 号；layout 列出的**恰好是**每个 stage **静态使用的** descriptor，所以一个被使用的 binding 下面不会有洞，也不会有 Metal argument table 互相冲突。set 0 装每个 per-slot 与 synthetic binding；**set 1 只在有 handle heap 时存在**。

### 3.1 `PipelineLayout`

| 字段 | 类型 | 含义 |
|---|---|---|
| `sets` | `Vec<DescriptorSetLayout>` | set 0（总有）与 set 1（只在有 handle heap 时），按 set 顺序 |
| `push_constants` | `Vec<PushConstantRange>` | 每个有 push 字段的 stage 一条：固定窗口 |
| `push_descriptor_eligible` | `bool` | set 0 能装进 `maxPushDescriptors`。为 `false` 时**同一个 layout** 作为 pooled set 使用；**layout 永不拆分** |

### 3.2 `DescriptorSetLayout`

| 字段 | 类型 | 含义 |
|---|---|---|
| `set` | `u32` | |
| `bindings` | `Vec<DescriptorBinding>` | **稠密的 `0..n`，按 binding 顺序** |
| `flags` | `vk::DescriptorSetLayoutCreateFlags` | heap set 是 `UPDATE_AFTER_BIND_POOL`；set 0 为空 |

### 3.3 `DescriptorBinding`

| 字段 | 类型 | 含义 |
|---|---|---|
| `binding` | `u32` | |
| `ty` | `vk::DescriptorType` | |
| `count` | `u32` | 数组大小；heap array 用 profile 的 update-after-bind 最大值 |
| `stages` | `vk::ShaderStageFlags` | **恰好是**静态使用该 binding 的那些 stage |
| `source` | `BindingSource` | 什么喂这个 binding（3.5 节） |
| `immutable_sampler` | `Option<vk::SamplerDesc>` | 烘进 layout 的 constexpr sampler |
| `flags` | `vk::DescriptorBindingFlags` | `PARTIALLY_BOUND`、`UPDATE_AFTER_BIND`、`VARIABLE_DESCRIPTOR_COUNT` |
| `variables` | `u32` | 单个 stage 的入口点在该 binding 上使用的最多变量数（即其 `OpEntryPoint` 列出的那些） |

`variables` 字段需要特别说明 `KNOWN`：一个通过多种类型到达同一个 buffer 的函数会在该 buffer 的 binding 上使用每种类型的一个变量（可写时各为 `Aliased`）。值为 0 的情形是：只有 pipeline 在创建时追加的 stage 使用它（tessellation pipeline 的 control stage、合成的 geometry stage，它们的模块 layout 看不到），或者没有 stage 使用它。

上游给出这个字段存在的具体理由 `KNOWN`：**一个从 SPIR-V 翻到其它语言的翻译器可能要区分"一个 binding 上有多个变量"的情形 —— MoltenVK 1.4.1 的 SPIRV-Cross 对一个有多于一个变量的 dynamic buffer binding 会写出编译不过的 Metal。** 对本项目（直接喂 Lavapipe）不构成问题，但若将来走 MoltenVK 路径需要它。

### 3.4 `PushConstantRange`

`KNOWN`：

| 字段 | 类型 |
|---|---|
| `stages` | `vk::ShaderStageFlags` |
| `offset` | `u32` |
| `size` | `u32` |

**固定窗口** `KNOWN`（doc comment）：**vertex `[0, 64)`，fragment `[64, 128)`，compute `[0, 128)`**，再按该 stage 实际使用的字段裁剪。

> **消费方规则**：窗口是固定的，**不要自己重新布置 push constant**。`BindingPlan::push`（`PushTemplate`）会告诉你每个字段在窗口里的 offset，见第 10.3 节。

### 3.5 `BindingSource` 全量

`KNOWN`（`layout.rs`，`enum BindingSource`，`#[non_exhaustive]`）。这是"什么喂这个 binding"的封闭词表，共 18 个 variant：

| variant | 含义 |
|---|---|
| `Buffer(SlotRef)` | 一个 Metal `[[buffer(n)]]` slot |
| `Texture(SlotRef)` | 一个 Metal `[[texture(n)]]` slot（image 或 texel buffer） |
| `Sampler(SlotRef)` | 一个 Metal `[[sampler(n)]]` slot |
| `CombinedTextureSampler { texture, sampler }` | 一个 texture slot 与一个 sampler 走一个 combined descriptor。constexpr sampler 是该 binding 的 `immutable_sampler`；runtime sampler 是该 texture 所在 stage 的 `[[sampler(n)]]` slot，按 `sampler.sampler_use()` 构造 |
| `YCbCrPlanes(SlotRef)` | 绑在某个 `[[texture(n)]]` slot 上的两平面 YCbCr texture 的两个平面，作为一个让设备自己的 sampler Y′CbCr conversion 去采样的 image（`ResourceKind::YCbCrPlanes`）：一个 combined descriptor，image 是两平面的 image 带 conversion 的 view，sampler 是该 binding 的 `immutable_sampler`（`vk::SamplerDesc::ycbcr`） |
| `Synthetic { stage, binding }` | 翻译器为某个 stage 追加的 binding（argument table、root 或 handle table、constant blob） |
| `Heap(HandleClass)` | set 1 heap 的一个 runtime array |
| `HeapSampler { stage, sampler }` | 某个 stage 用来采样 set 1 heap image 的独立 sampler。constexpr sampler 是 `immutable_sampler`，不占 descriptor write |
| `InputAttachment(u32)` | 该 color index 的 framebuffer-fetch 输入 |
| `AccelerationStructure { slot, level }` | 绑在某个 `[[buffer(n)]]` slot 上的 acceleration structure，作为 top-level structure 绑定；primitive-level 的通过一个单实例 top-level structure（identity transform、mask `0xFF`、instance index 与 user id 都是 0） |
| `TileAttachment(u32)` | tile 函数的该 color index 的 color attachment，作为 storage image |
| `TileMap(SlotRef)` | 绑在某个 `[[texture(n)]]` slot 上的 sparse texture 的 tile map，一个只读 storage buffer（`pipeline::tile_map`、`bind::SparseTileMap`） |
| `SeparateTexture { texture, sampler }` | 一个 texture slot 与一个 sampler 走**分离** descriptor 时的 image 一半：texture 作为它自身类型的 sampled image（cube 是 cube view），带 `sampler` 的 comparison。**每个 (texture, sampler, use) 一个 binding** |
| `SeparateSampler { stage, sampler }` | sampler 一半：`stage` 的**每个 (sampler, use) 一个 binding** |
| `ExtendedShadow(u32)` | draw 的 render pass instance 持有的该 color index 的扩展范围 color attachment 的 `half` 影子（`ResourceKind::ExtendedShadow`），作为 storage image |
| `SnapshotTexels(u32)` | draw 绑在该 fragment texture slot 上的 texture 的快照（`ResourceKind::SnapshotTexels`），作为 storage image |

> **消费方规则**：`BindingSource` 是只读的信息，用来回答"这个 descriptor 是什么"。**实际往哪里写**由 `BindingPlan::descriptors`（`DescriptorWrite` + `WriteSource`）决定，见第 10.2 节。不要从 `BindingSource` 自己去构造 descriptor write。

---

## 4. `PipelineInterface`

`KNOWN`（`crates/metal2vulkan/src/pipeline/interface.rs`）。模块文档明确它的两重身份：

> binder 的输入，以及给消费方的一个 Metal-reflection 形状的视图。每个 stage 与 slot 给出 argument kind、shader 如何访问它（**证明出来的，绝不是猜的**）、函数选的 buffer form 与 view、以及证明过的窗口。**它取代了旧引擎的 `ShaderReflection`，0.2.0 已删除后者。**

### 4.1 `PipelineInterface` 字段

| 字段 | 类型 | 含义 |
|---|---|---|
| `slots` | `BTreeMap<SlotRef, SlotInterface>` | **每一个静态使用的 Metal argument slot** |
| `threadgroup` | `Vec<ThreadgroupArgument>` | kernel 的 `[[threadgroup(n)]]` 参数 |
| `needs_pointer_translation` | `bool` | 某个函数读 resident root table（有 `Psb` slot 或 dynamic root），所以 binder 要建它，且**为每个 `Psb` slot 建一个条目** |
| `needs_handle_translation` | `bool` | 某个函数解析 texture 或 sampler 句柄，所以 binder 要建 handle table 与 set 1 heap |
| `push` | `Vec<PushPlacement>` | 每个 stage 的 push 放置，按 stage 顺序：binder 要写的 push 字节与 `ArgumentTable` 内容 |
| `reaches_command_buffers` | `bool` | 某个 stage 的函数可能到达一个 indirect command buffer。**只有这样的 pipeline 才能 encode/reset/copy indirect command；`false` 是证明出来的** |
| `command_writes` | `CommandWrites` | 各 stage 的函数可能往它们到达的 ICB 里写什么（全部 stage 合并）。**清零的位是对本 pipeline 的每个函数都证明过的** |
| `texture_writing_stages` | `Vec<Stage>` | 函数可能写 texture 的那些 stage，按 pipeline 的 stage 顺序。**未列出的 stage 不写任何 texture，这是证明出来的** |
| `numbered_samplers` | `Vec<(Stage, Vec<NumberedSampler>)>` | 一个 pipeline state 为它的每个 Metal 函数编号的 sampler；每个函数的按 Metal 的顺序，函数按 pipeline 的 stage 顺序 |

**"证明出来的"是关键措辞。** `reaches_command_buffers == false`、`command_writes` 的清零位、`texture_writing_stages` 的缺席，都是上游证明过的事实，消费方可以据此省掉 barrier、省掉 resident set、省掉 ICB 支持。反之，为 `true` 时必须按它准备。

### 4.2 `SlotInterface`

`KNOWN`：三态 `Buffer(BufferSlot)` / `Texture(TextureSlot)` / `Sampler(SamplerSlot)`。

#### `BufferSlot`

| 字段 | 类型 | 含义 |
|---|---|---|
| `access` | `AccessSet` | 模块通过该 slot 对 buffer 做了什么：函数的 load 与 store，atomic 算两者，以及"一个 store 通过 sub-word store 的两次 atomic 合并部分字"时算 read |
| `window` | `Window` | shader 能触及的字节窗口，**相对 bind offset** |
| `form` | `BufferForm` | 函数如何到达该 buffer |
| `kind` | `BufferKind` | slot 装什么 |

`AccessSet { read: bool, write: bool }`，有常量 `UNUSED`/`READ`/`WRITE`/`READ_WRITE`。

`Window` `KNOWN`：
- `Bounded { start: i64, len: u64 }` —— `[start, start + len)`，**`start` 可以是负的**；
- `Whole` —— 从 bind offset 到 allocation 末尾。**shader 有 dynamic root 时总是这个**。

`BufferForm` `KNOWN`：
- `Descriptor(DescriptorView)` —— 通过这种 view 的 descriptor；
- `Psb` —— 通过 buffer device address（dynamic root、per-stage 限制回退，或一个 `BufferRangeLimit` variant）。**绑的 buffer 必须有 device address**。

`DescriptorView` `KNOWN`：
- `Storage` —— storage buffer；
- `UniformWords` —— 作为 `u32[]` 看的 uniform buffer（**需要 `uniformBufferStandardLayout`**）；
- `UniformVec4` —— 作为 `uvec4` 数组看的 uniform buffer（std140，到处都合法）。

辅助方法 `BufferForm::uniform_view()` `KNOWN`：form 是否通过 uniform-buffer view 读 —— 这类 view 的 range，在设备的 view base alignment 整除 bind offset 时，plan 会从 bind offset 起算（`SpecKey::RangeAtBindOffset`、`BindState::view_base_alignment`）。

`BufferKind` `KNOWN` —— slot 装什么，即函数参数在 AIR ABI 里的那个位置是什么：
- `Buffer` —— 一个 buffer（`setBuffer:offset:atIndex:`）；
- `VisibleFunctionTable` —— 一个 visible-function table（`setVisibleFunctionTable:atBufferIndex:`），被当作 `pipeline::table` 的 words 读；
- `IntersectionFunctionTable` —— 一个 intersection function table，当作它的 words 读。

上游注明：Metal 对这三者各有自己的绑定调用，且它的 API validation 会阻止一个 slot 里装了另一种 kind 的 dispatch。

#### `TextureSlot`

| 字段 | 类型 | 含义 |
|---|---|---|
| `texture_type` | `metal::TextureType` | **shader 声明的** texture 类型 |
| `sampled_type` | `SampledType` | shader 读写的数值类型 |
| `depth_compare` | `bool` | 带 comparison 采样的 depth texture |
| `access` | `TextureAccess` | `{ sample, read, write }` 三个 bool（Metal 的 `access::` 限定符加上 sampling） |

#### `SamplerSlot`

| 字段 | 类型 | 含义 |
|---|---|---|
| `compare` | `bool` | shader 带 depth comparison 采样 |
| `coordinate_sensitive` | `bool` | 有一个坐标敏感的采样操作用它，所以它的坐标模式是一个 runtime fact |

### 4.3 `NumberedSampler`

`KNOWN`。这个类型解决一个很具体的 Metal 语义问题：**一个 pipeline state 要为它的函数编号 sampler，如 Metal 自己的那样 —— 每个取一个普通 sampler resource ID（在它之后创建的 sampler state 的 `gpuResourceID` 从它之后开始），除非 device 已经持有一个相等的。** 上游标明实测平台：Apple M4（macOS 27.0.1）与 M3 Max（macOS 26.7）。

顺序 `KNOWN`：先是该函数的 constexpr sampler，按模块 `!air.sampler_states` 的**逆序**；然后在它读 texture 时加一个 `Read`；然后在它写 texture 时加一个 `Write`。

| variant | 含义 |
|---|---|
| `Constexpr([u64; 2])` | 特化后的函数通过它采样/gather/查询 level 的 constexpr sampler，用它的规范 AIR state words 标识（即 `SamplerRef::Constexpr` 的命名方式）：**state 相等的两个算一个** |
| `Read` | 一次 texture `read` 的 sampler：特化后的函数读任意类型 texture（texture buffer 的、depth texture 的、多采样的）的一个 texel，通过参数、argument buffer 或任何句柄。**size query、atomic，或函数从不读的 texture 参数都不占** |
| `Write` | 一次 texture `write` 的 sampler：特化后的函数写任意类型 texture（含 texture buffer）的一个 texel |

单个函数的列表在 `CompiledFunction::numbered_samplers`，pipeline 的在 `PipelineInterface::numbered_samplers`。

> **消费方规则**：`21-OBJC-OBJECT-FAMILY.md` 回答 `MTLSamplerState.gpuResourceID` 与 `MTLFunctionHandle.gpuResourceID` 时**必须**用这个列表，不得自己编号。否则 guest 的 bindless 代码会拿到错的 resource ID。

### 4.4 `StageInterface`（单个 compiled function 的接口）

`KNOWN`（`interface.rs`，`pub struct StageInterface`）。这是"link 与 binder 在不看模块 words 的情况下需要的东西"。字段比 `PipelineInterface` 多，列出对本项目重要的：

| 字段 | 含义 |
|---|---|
| `stage`、`slots`、`threadgroup`、`push` | 同 `PipelineInterface` 的对应项，但只是本函数的 |
| `descriptors: Vec<StageDescriptor>` | 模块声明的**每一个** descriptor binding 符号（含 synthetic），带它需要的 descriptor；**按符号排序（这是 link 契约）** |
| `spec: Vec<StageSpec>` | 模块声明的每个 specialization constant，**按 key 排序** |
| `needs_pointer_translation`、`needs_handle_translation` | 同上 |
| `io: pipeline::stage_io::StageIo` | stage-IO 接口（vertex 与 fragment；kernel 为空）：模块的每个 `Location` key 是什么，以及函数读的每个 vertex attribute 及其编译时所用的 fetch 方式。**这是 link 用来编号 location 并推导 vertex input 的唯一契约** |
| `tessellation: Option<TessellationStage>` | post-tessellation vertex 函数的 evaluation stage：模块是一个 `TessellationEvaluation` entry，**通过 vertex argument table 绑定，如 Metal 绑定它那样** |
| `writes_memory: bool` | 函数写了别的 invocation 或后续命令能读的内存。**Metal 对有这种副作用的多采样 fragment 函数每个被覆盖的 sample 跑一次。** `ExecutionStatus` buffer 的 words（resident-miss 计数更新的那些）不算函数的，color 的 interlocked storage form 或 `half` 影子也不算（它们承载的是 Metal 的 color attachment 写） |
| `mesh_records: Option<MeshRecords>` | 为没有 `VK_EXT_mesh_shader` 的设备编译的 mesh 函数：模块是一个 `GLCompute` entry，把它的 threadgroup 的 vertex 与 primitive 写成这些 record，由 pipeline 合成的 vertex stage 来画 |
| `emulated_payload: Option<u32>` | 为没有 `VK_EXT_mesh_shader` 的设备编译的 object 或 mesh 函数的 payload words（无 payload 时 0），放在它的 object threadgroup 在 draw 的 work buffer 里的 slot（`MeshRecords::slot_words`） |
| `payload: Option<u32>` | object 或 mesh 函数的 payload arena 字节数。link 会把 mesh 函数的提到至少等于其 pipeline 的 object 函数的（`NeedsInput(ObjectPayload)`） |
| `reaches_command_buffers`、`command_writes`、`writes_textures` | 见 4.5 |
| `numbered_samplers` | 见 4.3 |
| `own_pixel_textures`、`snapshot_textures` | 见 4.6 |
| `private_bytes` | 一个线程保有的私有内存字节数：它的 `thread` 变量与被运行时下标访问的数组、它的调用栈，以及它按线程持有的常量。`PrecisionNote::FunctionStorageAssumed` 的宣告就命名这个值 |

### 4.5 `reaches_command_buffers` / `writes_textures` 的精确语义

这两个 flag 值得单独展开，因为它们是"证明"的典型例子，且上游写得很细。

`reaches_command_buffers` `KNOWN`：对**它的函数常量已特化的那个 entry** 而言（把某个参数或路径关掉的常量会把它排除掉）。`false` 只在"函数可证明地不触及任何 ICB"时出现。为 `true` 的条件是以下任一：

1. 函数接收一个 ICB（`air.command_buffer`），作为参数，或作为它接收的某个 buffer 在**任意深度** argument-buffer 布局里的成员 —— **不管函数体怎么用它**；
2. 函数体对**任意指针**调用 indirect-command 操作：metadata 命名的 command buffer、函数体从其它字节 cast 出来的、从没有布局描述的成员载入的、或从整数构造的（上游点明理由：**Metal 不给 command buffer 的 record 任何地址，所以"操作"是到达它们的唯一途径**）；
3. 函数发起一个它看不进去的调用。

实现在 `metal2vulkan-air` 的 `Entry::may_encode_indirect_commands`。

`command_writes: CommandWrites` `KNOWN`：函数的 indirect-command 操作可能往它们到达的 record 里写什么（它可能调用的操作，以及它的 draw 可能传的 primitive type；`Entry::command_writes`）。**清零的位是证明过的**：函数的任何操作都不写它。`reaches_command_buffers` 为 `false` 时为空。

`writes_textures` `KNOWN`：同样对已特化的 entry。`false` 只在可证明不写时出现。为 `true` 的条件：

1. 函数接收一个声明为 `access::write` 或 `access::read_write` 的 texture（参数，或任意深度 argument-buffer 布局里的成员），**不管函数体怎么用它**；
2. 函数体通过任意句柄（argument buffer 的、heap 的、resource ID 都算）调用了一个存 texel 的 texture 操作（一次 `write`、一个写到 texture 的 imageblock slice、或一个非 load 的 atomic）；
3. 函数发起一个它看不进去的调用。

**不算 texture 写**的 `KNOWN`：color attachment output、imageblock 与 tile store、以及对"某个 texture 所 view 的 buffer 的字节"的 store。

> **消费方规则**：这三者（`reaches_command_buffers`、`command_writes`、`writes_textures`）是**barrier 与 resident set 的决策依据**。按它们裁剪是安全的；**自己从 shader 或 descriptor 去推则不安全**，因为上游的证明覆盖了"函数体 cast 出来的指针""看不进去的调用"这些情形。

### 4.6 `own_pixel_textures` / `snapshot_textures`

`KNOWN`。这是一个很具体的优化事实，上游把条件写得极严。

`own_pixel_textures`：一个 fragment 函数的 texture slot，其**每一次** texel 读都在该 fragment 自己的像素处 —— 即一个 level 0、无 offset、对单采样非数组 2D image 的 `OpImageFetch`，坐标是 Metal 对 `[[position]]` 的 x、y 的饱和 `uint2`（`read(uint2(p.xy))`），clamp 进 image 或不 clamp。**在每边小于 2²⁴ 像素的 framebuffer 上**，这种 slot 的读落在"包住该 draw 的 scissor 的矩形，每边再宽一个像素（为它的 helper invocation）"之内，且按坐标那样 clamp。

`snapshot_textures`：上述中，draw 可以通过"同一批图元的较早 draw 拍的快照"来读的那些。条件（`spirv::requirements::snapshot_textures`）`KNOWN`：该 slot 的 fetch 返回的**任何值**都不会直接或通过调用到达一个 derivative、一次 sample、一个 quad 或 subgroup 操作、一个分支、一个整数除数、一个动态向量下标、或一个非 `Function`/`Private`/`Output` 变量的 store —— 所以一个 helper invocation 的该值到不了任何 fragment 的结果，也不会给它带来未定义行为；并且函数不写内存、不持有 interlock。

### 4.7 `MeshRecords`（无 `VK_EXT_mesh_shader` 时的 mesh 输出布局）

`KNOWN`（`interface.rs`，`pub struct MeshRecords`）。全部是 words。

| 字段 | 含义 |
|---|---|
| `vertices` | mesh 类型的 `NV` |
| `primitives` | mesh 类型的 `NP` |
| `corners` | 一个图元的 index 数：1（point）、2（line）、3（triangle） |
| `vertex_words` | 一条 vertex record 的 words |
| `primitive_words` | 一条 primitive record 的 words |
| `fields` | 每个字段，按 record 顺序：先 vertex record 的，再 primitive record 的 |
| `slot_words` | 一个 object threadgroup 在 draw 的 work buffer 里的 slot 的 words：它的 grid 的三个计数加一个零，然后是 pipeline 的 object 与 mesh 函数中较大的那个 payload（在单个函数自己的 interface 里，就是它自己的 payload） |

布局规则 `KNOWN`：mesh threadgroup `w`（它在 draw 的 mesh threadgroup 中的序号：按 object threadgroup 逐个，每个的 grid x 变化最快）拥有从 draw 的第一个 word 加 `w · group_words()` 起的 `group_words()` 个 word：**先是它的图元计数，然后 `vertices` 条 vertex record（每条 `vertex_words` 个 word），然后 `primitives` 条 primitive record（每条 `primitive_words` 个 word），每条 primitive record 以该图元的 `corners` 个 index 开头。** 每个字段位于它在 record 里的 offset，每个 lane 一个 word。

**一个 threadgroup 在它的函数体跑之前把自己的 words 清零**，所以函数没写的 index、culled 标志、render target slice 或 viewport index 读作 0，与 Metal 的一致 `KNOWN`。

辅助方法：`group_words()` = `1 + vertices · vertex_words + primitives · primitive_words`；`primitive_base()` = `1 + vertices · vertex_words`；`topology()` 按 `corners` 给出 `POINT_LIST`/`LINE_LIST`/`TRIANGLE_LIST`。

`RecordField { value: RecordValue, per_primitive: bool, offset: u32, words: u32, numeric: IoNumeric }`。`RecordValue` 全量：`Position`、`PointSize`、`ClipDistance`、`Culled`（置位处为 1）、`Layer`（图元的 render target slice：其 `[[render_target_array_index]]` 若小于 pass 的长度则取它，否则 0）、`ViewportIndex`（同理，比较 draw 的 viewport count）、以及 user varying（vertex data、primitive data 或 raw index）。

`IoNumeric` 表示每个 word 装什么：一个 `float` 的位、一个 `uint`、或一个 `int` 的位（`bool` 是 `uint`，0 或 1）。

---

## 5. 固定功能状态

### 5.1 `GraphicsState`

`KNOWN`（`crates/metal2vulkan/src/pipeline/graphics.rs`，`pub struct GraphicsState`）。18 个字段：

| 字段 | 类型 | 含义 |
|---|---|---|
| `topology` | `vk::PrimitiveTopology` | |
| `color_attachments` | `Vec<Option<ColorAttachmentState>>` | 按 color index；`None` 表示该 index 无 attachment |
| `depth_format` | `Option<vk::Format>` | |
| `stencil_format` | `Option<vk::Format>` | |
| `rasterization_samples` | `vk::SampleCountFlags` | |
| `alpha_to_coverage` | `bool` | |
| `alpha_to_one` | `bool` | |
| `rasterizer_discard` | `bool` | 对应 Metal 的 `rasterizationEnabled == false` |
| `dynamic_states` | `Vec<vk::DynamicState>` | **消费方必须恰好启用这些 dynamic state** |
| `input_attachments` | `Vec<InputAttachmentUse>` | framebuffer fetch 的 input attachment 用法 |
| `rasterization_order_attachment_access` | `bool` | |
| `max_vertex_amplification_count` | `u32` | |
| `declares_layer` | `bool` | |
| `tessellation` | `Option<TessellationState>` | 见 5.3 |
| `fragment_imageblock` | `Option<FragmentImageblock>` | |
| `sample_shading` | `bool` | |
| `vertex_writes_memory` | `bool` | |
| `writes_viewport_index` | `bool` | |

`graphics.rs` 另外导出的相关类型 `KNOWN`：`BlendState`、`ColorAttachmentState`、`EmulatedTessellation`、`FragmentImageblock`、`ImageblockMechanism`、`InputAttachmentUse`、`ShaderTestsUse`、`ShadowStencilUse`、`StandInUse`、`StandInView`、`StorageAttachmentUse`、`StorageAttachmentView`、`TessellationState`。

### 5.2 `ColorAttachmentState` 与 `BlendState`

`KNOWN`：

`ColorAttachmentState`：

| 字段 | 类型 | 含义 |
|---|---|---|
| `format` | `vk::Format` | |
| `write_mask` | `vk::ColorComponentFlags` | descriptor 的 write mask，**或者空** —— 当 fragment 函数没有任何 index 0 的 output 命名该 attachment 时，为空以使 draw 不修改它。上游补充：在没有 `independentBlend` 的设备上每个 attachment 共用一个 mask 与 blend state，此时该 attachment 取"函数写的那些 attachment 的 mask"，因为它所在 location 上没有声明 output，结果同样是不修改它 |
| `blend` | `Option<BlendState>` | `None` 表示 blending 关闭 |

`BlendState`：`src_color`、`dst_color`、`color_op`、`src_alpha`、`dst_alpha`、`alpha_op`，类型分别是 `vk::BlendFactor` 与 `vk::BlendOp`。方法 `reads_second_output()` 判断某个 factor 是否读 fragment 的第二个 output（`[[color(n), index(1)]]`，即 dual-source blending）。

### 5.3 `TessellationState`

`KNOWN`（`graphics.rs`）：

| 字段 | 类型 |
|---|---|
| `patch_control_points` | `u32` |
| `domain` | `PatchDomain` |
| `control_points` | `u32` |
| `factor_step_function` | `metal::TessellationFactorStepFunction` |
| `push_offset` | `u32` |
| `control_point_index_type` | `metal::TessellationControlPointIndexType` |

以及 `EmulatedTessellation`（含 `domain`、`control_points`、`descriptor: TessellationDescriptor`，方法 `scan_kernel() -> bind::TessellationScanKernel`）—— 用于没有 `tessellationShader` 的设备。

上游在 `README.md` 里明示这条路径 `KNOWN`：一个 post-tessellation vertex 函数在有 `tessellationShader` 的设备上会多出 `.tesc.spv` 与 `.tese.spv` 两个模块；在没有的设备上，它**就是** `.vert.spv` 模块本身，由它来画 tessellator 产生的三角形。

### 5.4 `ComputePipelineMetalInfo`

`KNOWN`（`artifact.rs`）。"对 Metal 的 per-pipeline compute 查询的答案"。五个字段，每个都有具体语义，**本项目的 `MTLComputePipelineState` 必须直接回答它们**：

| 字段 | 类型 | 含义 |
|---|---|---|
| `max_total_threads_per_threadgroup` | `u32` | `maxComputeWorkGroupInvocations`，再被以下几项进一步限制：flattened tier、emulated simdgroup 的 scratch、函数自己的最大值、descriptor 的（compute 或 tile descriptor 的 `max_total_threads_per_threadgroup`）。**tile pipeline 的最多 1024**（32×32 的 tile threadgroup），且取这些限制内"边长都是偶数"的最大 threadgroup，与 Metal 的取整一致 |
| `metal_max_total_threads_per_threadgroup` | `u32` | **Apple GPU 上在应用本设备限制之前**的 `maxTotalThreadsPerThreadgroup`：1024、函数自己的最大值、descriptor 的三者取最小（上游实测 M3 Max 与 M4 上 compute pipeline 原样回答 descriptor 的限制），tile pipeline 的再向下取整到边长都是偶数。**超过它的 threadgroup 的 dispatch 什么都不跑，与普通 Metal 一致；在它之内但超过上一行的，是本设备的缺口，类型化拒绝。** 上游明示："Apple 对寄存器装不下的 kernel 给出的低于 1024 的答案没有建模" |
| `thread_execution_width` | `u32` | **恒为 32** |
| `static_threadgroup_memory_length` | `u32` | 静态大小的 threadgroup 内存字节数。simdgroup 被模拟的 kernel 还要计入 `max_total_threads_per_threadgroup` 个线程的 scratch 与声明 arena 的最小值，以便任何能放在它旁边的 `[[threadgroup(n)]]` 长度都能放下 |
| `support_indirect_command_buffers` | `bool` | 从 descriptor 原样回传 |

> **消费方规则**：这两个 `max_total_threads_per_threadgroup` 的区别必须精确实现。`MTLComputePipelineState.maxTotalThreadsPerThreadgroup` 应回答 `metal_max_total_threads_per_threadgroup`（这是 guest 看到的、与真 Metal 一致的值）；而真正允许的 dispatch 上界是 `max_total_threads_per_threadgroup`，超出它要给类型化拒绝。两者混用会让 guest 的"按 pipeline 上界算 threadgroup 大小"的代码跑出设备上界。

---

## 6. `VertexInputState`

`KNOWN`（`crates/metal2vulkan/src/pipeline/vertex.rs`）：

| 字段 | 类型 | 含义 |
|---|---|---|
| `bindings` | `Vec<VertexBinding>` | 固定功能 binding，按 binding 顺序 |
| `attributes` | `Vec<VertexAttribute>` | 固定功能 attribute，按 location 顺序 |
| `pulled` | `Vec<PulledAttribute>` | 在 shader 里取的 attribute；**plan 会绑定它们的源 buffer** |
| `variant_pulled` | `BTreeSet<u32>` | Metal vertex-buffer 索引：在 descriptor 自己的 projection 下本该由固定功能取，但本 pipeline 因为是在一个命名它们的 `VariantKey`（`pulled_vertex_buffers`）下编译的而改成 pull。**它的 plan 会继续列出它们** |

`VertexStride` 是 `Static(u32)` 或 `PerBind`（即 Metal 的 `MTLBufferLayoutStrideDynamic`，每次 bind 设置）。

一个内部细节值得消费方知道 `KNOWN`（`may_access_beyond_stride`）：portability subset 用 `vertexAttributeAccessBeyondStride` 门控"固定功能 attribute 能否越过它 binding 的 stride 结束"。在该 subset 不给这个特性时，**link 会把第一个这样的 attribute 改成 pull，binder 会把"bound stride 低于 attribute 末尾"的那个改成 pull**，所以一条 pipeline 只会在设备确实有这个特性时才命名它。

---

## 7. `RuntimeDependency`、`RuntimeFact`、`Mechanism`

`KNOWN`（`crates/metal2vulkan/src/pipeline/facts.rs`）。模块文档的一句话定义了整个机制：

> `RuntimeFact` 是**唯一的依赖词表**：`select` 发出 fact，planner 提供它们的值，`device::mechanism(fact, profile)` 是一个**全函数**，每个 (fact, profile) 对给出一个 `Mechanism`。

`RuntimeDependency { fact: RuntimeFact, mechanism: Mechanism }`，构造器 `RuntimeDependency::new(fact, mechanism)`。

### 7.1 `RuntimeFact`（Metal 在 pipeline 或 encode 时绑定、而与翻译有关的状态）

`KNOWN`（`facts.rs`，`enum RuntimeFact`，`#[non_exhaustive]`）。本项目必须理解的清单：

| variant | 含义 |
|---|---|
| `ThreadsPerThreadgroup` | Metal 的每 threadgroup 线程数 |
| `ThreadgroupMemoryLength { index }` | threadgroup-memory 参数 `index` 的长度 |
| `LocalSizeConstraint { multiple }` | 每个 dispatch region 的 local size 必须是它的倍数 |
| `LocalSizeLimits` | local size 要对照设备的 per-axis、总量与 subgroup 限制检查 |
| `DispatchGrid` | 一个 dispatch 的 grid size 与 region base |
| `IndirectGroupCount` | GPU 写的 indirect group count |
| `ResourcePresence { slot }` | 该 slot 是否被绑定 —— 针对 shader 会观察其 null 性的 slot |
| `SampleCount` | 光栅化采样数 |
| `StorageTextureFormat { slot }` | 绑在该 slot 上的 storage texture 的格式 |
| `SamplerCoordinates { slot }` | 绑在该 slot 上的 runtime sampler 的坐标模式；对可能读 pixel 坐标的采样，还包括"那个 pixel sampler 是否 nearest 过滤"—— 即函数读取的该 slot 的 `SpecKey::SamplerState` 的那些字段 |
| `SamplerReduction { slot }` | reduction 模式 |
| `ImageViewShape { slot }` | 绑在该 slot 上的 texture 的 view 形状（cube 当 2D array） |
| `VertexFetch { attr }` | 一个 vertex attribute 怎么取（固定功能或 pulled，以及 pulled 的格式） |
| `VertexBufferStride { layout }` | 一个 vertex buffer layout 的 stride |
| `BaseVertexInstance` | base vertex 与 base instance |
| `DeviceAddresses { slot }` | 该 slot 需要一个 device address（`BufferForm::Psb`） |
| `BufferRangeLimit { slot }` | 该 slot 的窗口可能超过 descriptor range 限制 |
| `TexelBufferRange { slot }` | 绑在该 slot 上的 texel buffer 必须满足 texel-buffer 限制 |
| `FramebufferFetch { color }` | 该 color index 的 framebuffer fetch |
| `ExecutionStatus` | 函数写 command buffer 的 `ExecutionStatus` buffer（resident-set miss、absent read、顺序一致 fence、argument buffer 的 cubic sampler）：通过 buffer 的 device address（`PushField::ExecutionStatusAddress`），或在不给 buffer 地址的设备上通过 stage 对它的 binding（`SyntheticBinding::ExecutionStatus`） |
| `HeapNumericType { class }` | set 1 heap 的该 class 的 array 用默认 `Float` sampled type 声明，因为该 class 的某个 heap group 只被 query —— 没有结构性信息能给它定类型（argument-buffer 成员的 texture type 只是它的 MSL 类型名）。**后果**：一个在"除数值类型外"都匹配该 class 的 resident texture 不能作为该 array 的元素，所以通过这种句柄的 query 答的是 neutral 的；binder 会报告每个这样的 texture（`PlanDiagnostic::IncompatibleHeapEntry`） |
| `SimdgroupEmulation { bytes_per_simdgroup, arena }` | kernel 的 simdgroup 通过 workgroup 内存模拟：除它的 threadgroup arena 外，还为 `N` 线程 threadgroup 的 `⌈N/32⌉` 个 simdgroup 各取 `bytes_per_simdgroup`，**每个 dispatch region 都必须把它们装进 `maxComputeSharedMemorySize`**。`arena` 是模块声明的 threadgroup arena 的静态部分，`None` 表示没声明 |
| `AmplificationCount` | render encoder 的 vertex amplification count，stage 读作 `[[amplification_count]]`（`SpecKey::AmplificationCount`） |
| `EmulatedSimdgroups` | kernel 在 `VariantKey::emulated_simdgroups` 下编译：不管 profile 的 subgroup 给它什么 tier，它的 simdgroup 都在模拟 tier 跑，所以每种 threadgroup 大小都能跑，含部分 simdgroup |
| `ImageblockSize { cell_bytes }` | compute encoder 的 imageblock 尺寸（`setImageblockWidth:height:`，`SpecKey::ImageblockWidth`/`ImageblockHeight`）：kernel 的显式 imageblock 在 threadgroup arena 之后，每像素取 `cell_bytes` 的 threadgroup Workgroup 内存 |
| `RenderTargetArrayLength { layer_dropped }` | vertex 函数写 `[[render_target_array_index]]`，而它只在 `renderTargetArrayLength ≥ 2` 的 render pass 里真正选 slice：在最多一层的 pass 里每个 index 都渲染 slice 0，函数跑在"不写 `Layer`"的 variant 上（`VariantKey::dropped_vertex_layer`）。`layer_dropped` 说明它是否在那个 variant 下编译的。**写 `Layer` 的那个 variant 还会从 `PushField::RenderTargetArrayLength` 读长度**（binder 每个 draw 写一次），并对等于或超过它的 index 存 0，Metal 在那里渲染 pass 的第一层 |
| `StageInRegion` | kernel 读 compute encoder 的 stage-in region（`setStageInRegion:`）：一个按 thread position 步进的 `[[stage_in]]` attribute 把它的元素 clamp 到 region 并加上 region 的原点，`[[grid_origin]]`/`[[grid_size]]` 读这个 region（`PushField::StageInRegion`） |
| `StageInStride { layout }` | kernel 从 Metal buffer index `layout` 处的 buffer 按 encoder 绑定它时的 stride 取 `[[stage_in]]` attribute（即 stage-input layout 是 `MTLBufferLayoutStrideDynamic`）：binder 把绑定的 stride 写进 `PushField::StageInStride`，对不带 stride 绑定的 buffer 写 0，与 Metal 的读法一致。**固定 stride 的 layout 读它自己编译进去的那个，不管 bind 的是什么，也不记录任何东西** |
| `UniformViewRange { slot, choice }` | Profile F 的 per-stage storage-buffer 回退可能通过 uniform view 读的只读 slot，其窗口没有把 descriptor range 界在 `maxUniformBufferRange` 之内（`Whole` 窗口，或更长的 `Bounded`）：只有 shape 绑定的 range 确实装得下时该 view 才精确。`choice` 说明本次编译选了什么 |

（`facts.rs` 的 `enum RuntimeFact` 在 `UniformViewRange` 之后还有若干 variant，本次未全部读出。**未查**，查清方法：读 `crates/metal2vulkan/src/pipeline/facts.rs` 第 120 行之后。）

### 7.2 `Mechanism`（本 profile 怎么满足一个 fact）

`KNOWN`（`facts.rs`，`enum Mechanism`，15 个 variant）：

| variant | 含义（`INFERRED`，由名字与上下文推出；上游未逐个加 doc comment） |
|---|---|
| `Specialization` | 通过 specialization constant 满足 |
| `Variant` | 需要编译另一个 variant（`VariantKey`） |
| `PushConstant` | 通过 push constant 满足 |
| `DynamicState` | 通过 Vulkan dynamic state 满足 |
| `DynamicStateOrPushConstant` | 二者之一 |
| `Builtin` | 通过 SPIR-V builtin 满足 |
| `PlanTimeCheck` | 在 plan 时检查 |
| `BinderView` | 通过 binder 构造的 view 满足 |
| `KeyProjection` | 投影进 compile key |
| `RegionSelected` | 由 dispatch region 选择 |
| `IndirectClamp` | 通过 indirect clamp 前置 pass 满足 |
| `SyntheticBinding` | 通过 translator 追加的 binding 满足 |
| `RenderPassContract` | 由 render pass 的契约保证 |
| `PipelineStateOrPushConstant` | pipeline state 或 push constant |
| `None` | 本 profile 下不需要任何机制 |

> **消费方规则**：`dependencies` 是**自我描述的**。消费方应当遍历它，对每一项按 `mechanism` 决定自己要做什么：
> - `Specialization` / `RegionSelected` → 从 `BindingPlan::specialization` 或 `DispatchRegion::specialization` 取值，不要自己算；
> - `PushConstant` / `DynamicStateOrPushConstant` / `PipelineStateOrPushConstant` → 从 `BindingPlan::push`（`PushTemplate`）取放置，见 10.3；
> - `DynamicState` → 该 dynamic state 必然已出现在 `GraphicsState::dynamic_states` 里；
> - `Variant` → 该 fact 需要另一个 variant，`BindingPlan::variant` 会非空，必须重编译；
> - `SyntheticBinding` → 该 binding 必然在 `PipelineLayout` 里，`BindingSource::Synthetic`；
> - `None` → 什么都不做。
>
> `mechanism` 是全函数，所以 `dependencies` 里的每一项都有确定答案，**不存在"需要消费方自己想办法"的情形**。

---

## 8. `Requirements`

`KNOWN`（`crates/metal2vulkan/src/device/requirements.rs`，模块文档）：

> 这些 enum 命名了新核心所消费的那个 Vulkan 子集：device feature、extension、property、limit 与 format usage。它们是 `error::Capability`（一个拒绝所说的"什么会让这个输入可翻译"）与 `Requirements`（一个发出的模块需要启用什么）的载荷。`spirv::requirements` 推导 `Requirements` 值；`device` 把它们对照一个 profile 检查。**每个 enum 都是 `#[non_exhaustive]`；新消费一项就是追加一行。**

词表 `KNOWN`：`VkFeature`（按 `VkPhysicalDevice*Features` 成员命名：core 1.0–1.3 结构体加本 crate 消费的 extension 结构体）、`VkExtension`、`VkProperty`、`VkLimit`，以及 format usage。另有 `device::profile::Independence`。

`VkFeature` 的分组（源码里用注释分段）`KNOWN`：Robustness、Arithmetic widths、Narrow storage、Atomics、Memory model and addressing、Stage stores、Stages and stage builtins、Images and samplers、Descriptor indexing，等等。本项目关心的具体项（节选）：

- Robustness：`RobustBufferAccess`、`RobustBufferAccess2`、`RobustImageAccess`、`RobustImageAccess2`、`NullDescriptor`
- 算术宽度：`ShaderInt8`、`ShaderInt16`、`ShaderInt64`、`ShaderFloat16`、`ShaderFloat64`
- 窄存储：`StorageBuffer8BitAccess`、`UniformAndStorageBuffer8BitAccess`、`StoragePushConstant8`、`StorageBuffer16BitAccess`、`UniformAndStorageBuffer16BitAccess`、`StoragePushConstant16`、`StorageInputOutput16`
- 原子：`ShaderBufferInt64Atomics`、`ShaderSharedInt64Atomics`、`ShaderImageInt64Atomics`、`ShaderBufferFloat32Atomics`/`AtomicAdd`/`AtomicMinMax`、`ShaderSharedFloat32*`、`ShaderImageFloat32*`
- 内存模型与寻址：`BufferDeviceAddress`、`ScalarBlockLayout`、**`UniformBufferStandardLayout`**（`DescriptorView::UniformWords` 需要它）、`VulkanMemoryModel`、`VulkanMemoryModelDeviceScope`、`WorkgroupMemoryExplicitLayout`(+`8BitAccess`/`16BitAccess`)、`ShaderZeroInitializeWorkgroupMemory`
- stage store：`VertexPipelineStoresAndAtomics`、`FragmentStoresAndAtomics`
- stage 与 builtin：`ShaderDrawParameters`、`GeometryShader`、`TessellationShader`、`SampleRateShading`、`DualSrcBlend`、`IndependentBlend`、`ShaderClipDistance`、`ShaderCullDistance`、`ShaderOutputLayer`、`ShaderOutputViewportIndex`、`Multiview`、`FragmentShaderBarycentric`、`FragmentShaderPixelInterlock`、`FragmentShaderSampleInterlock`、`ShaderDemoteToHelperInvocation`、`ShaderTerminateInvocation`、`DynamicRenderingLocalRead`、`RasterizationOrderColorAttachmentAccess`（及 Depth/Stencil 两个）、`VertexAttributeInstanceRateDivisor`、`VertexAttributeInstanceRateZeroDivisor`、`DrawIndirectFirstInstance`、`MultiDrawIndirect`、`DrawIndirectCount`、`DepthClamp`、`FillModeNonSolid`
- image 与 sampler：`ImageCubeArray`、`ShaderImageGatherExtended`、`ShaderResourceMinLod`、`SamplerAnisotropy`、`SamplerFilterMinmax`、`SamplerMirrorClampToEdge`、`ShaderStorageImageMultisample`、`ShaderStorageImageExtendedFormats`、`ShaderStorageImageReadWithoutFormat`、`ShaderStorageImageWriteWithoutFormat`

> **消费方规则**：
> 1. `Requirements` 是"这个 artifact 的模块需要设备启用什么"的**完整**陈述，且上游保证它是 **enable 集合的超集** `KNOWN`（`RenderPipeline::requirements` 的 doc comment："a superset of the enable set"）。
> 2. **不得自己从 SPIR-V 推导 capability**。上游明示 capability 与 extension 由模块内容推导、绝不由 lowering 写入，且必须落在 profile 内（否则 `Error::Internal`，kind `RequirementsExceedProfile`）。
> 3. 创建 `VkDevice` 时启用的 feature 集合必须覆盖所有 artifact 的 `requirements` 的并集。本项目的 `40-RUNTIME-VULKAN.md` 负责把这个并集与 Lavapipe 的实际能力对齐。
> 4. **`60-CAPABILITY-MATRIX.md` 的"Lavapipe 支持"列就是这些 enum 的取值。** 用 `DeviceDescription::query`（需要 `ash` feature）从真实设备导出 profile，比手写 JSON 可靠。

---

## 9. cache key 的构成与失效条件

来源：`crates/metal2vulkan/src/cache/mod.rs`、`crates/metal2vulkan/src/pipeline/compile/key.rs`。

### 9.1 总原则

`KNOWN`（`cache/mod.rs` 模块文档）：

> **这个 crate 自己不保存任何缓存**；存储、限界与淘汰都归消费方。
>
> key 是对一种**本 crate 自己拥有的规范编码**取的 SHA-256：在所声明的 `SEMANTICS_VERSION` 之下，**相等的 key 意味着相等的输出**，而且**每个 key 都包含 device profile 的指纹，所以一个 artifact 绝不会被另一台设备用上**。

### 9.2 四个版本号 + 一个源码指纹

`KNOWN`（`cache/mod.rs` 的常量与其 doc comment）。**它们独立移动**，本项目必须全部纳入缓存 key。

| 常量 | 当前值 | 含义 | 什么时候 +1 |
|---|---|---|---|
| `SEMANTICS_VERSION` | **1929** | **输出语义的版本** —— 翻译器发出什么。**每个 pipeline 与 function key 都包含它，每个编码 artifact 都携带它**，所以 bump 它会 miss 掉每一个缓存 artifact 与 key | 只要"在 key 不变的情况下任何输入的输出可能改变"：模块的 words、一个拒绝或它的 class、一项 requirement、一项 reflection / interface / binding-plan 事实，或一条 precision note。`src/tests/golden_hashes.rs` 在"golden 输出 hash 在版本未变的情况下变了"时失败 |
| `ARTIFACT_FORMAT_VERSION` | **479** | **编码 artifact 的字节布局版本**。每个编码 artifact 携带它；在另一个值下 decode 是 `ArtifactError`（**一次 cache miss**）。与 `SEMANTICS_VERSION` 独立 | 只要编码变了：在某个被编码类型、它的 `codec` body 或它的 `envelope` 里增删/重排/改类型了一个字段、variant 或 tag。**删掉一个 variant 而 tag 保持不用则不需要 bump** —— 装着它的条目会 decode 失败，那就是一次 miss |
| `RUNTIME_VERSION` | **1709** | **本 crate 的运行时拿一个编译好的 pipeline 做什么**的版本：实例化一个 binding plan（`BindingPlan::instantiate_*`：descriptor range、push 字节、root/argument/handle table、dispatch region 与 draw）、device replay 与其 preprocess、resident set、indirect clamp、status 解码，以及 binder 计算的其它运行期数据。与前两个独立 | 只要"一次对未变 artifact 与 plan 的运行可能做别的事"：一个答案、一个拒绝或它的 class、一次宣告，或这次运行记录与提交的内容。**在编码 artifact 或 plan 里加一个字段，若它的零值会改变既有 pipeline 的行为，也需要同样的 bump**（或 executor 的），因为它们的 digest 看不到它 |
| `SOURCE_DIGEST` | `env!("M2V_SOURCE_DIGEST")` | **本次构建所编译的源码的摘要**：对 manifest、build script，以及 crate root 的模块树所编译或读取的恰好那些文件取 SHA-256，小写 hex。**跨构建缓存翻译结果的缓存要在 `SEMANTICS_VERSION` 与 `ARTIFACT_FORMAT_VERSION` 旁边再带上它**，这样"另一份源码的构建"绝不会读到"另一个构建的输出"，即使没有任何版本号动过。`metal2vulkan-runtime` 的 shader cache 就这么做。改一个 test-only 模块不会改变它 | 自动 |

**消费方规则**：缓存 key 必须是

```
cache_key = H( PipelineKey
             , SEMANTICS_VERSION
             , ARTIFACT_FORMAT_VERSION
             , SOURCE_DIGEST
             , profile 指纹 )
```

其中前三项其实已经在 `PipelineKey` 与 artifact envelope 里了（见 9.3），但 `SOURCE_DIGEST` **不在**，必须由消费方加上。另外，记录"运行之后发生了什么"的东西（本项目自己的回归记录、一次运行拒绝了什么）要在 artifact 旁边**用 `RUNTIME_VERSION` 做 key**，正如缓存 artifact 用 `SEMANTICS_VERSION` 做 key。

> 这纠正了本项目既有文档 `docs/METAL2VULKAN_INTEGRATION.md` 的一句话："所有缓存必须绑定完整 Git SHA 和上游语义版本"。**Git SHA 不够**，因为同一个 SHA 在不同 feature 组合下编译出的源码集不同；上游为此专门提供了 `SOURCE_DIGEST`。应改成"绑定 `SOURCE_DIGEST` 与四个版本号"。

### 9.3 `PipelineKey` 与 `FunctionCompileKey` 的构成

`KNOWN`（`pipeline/compile/key.rs` 模块文档 + `function_key`/`pipeline_key`）。**key 永远不需要解码的 AIR。**

`FunctionCompileKey = H(` domain tag `"metal2vulkan/function-compile-key/v2"`, `SEMANTICS_VERSION`, 然后长度前缀编码的：

1. 函数的 **AIR hash**（即容器 `HASH` 标签的那个 SHA-256）；
2. **entry 名**；
3. **函数常量值 —— 按"提供时的样子"**（按 index 的与按 name 的两张表，各含 index/name、`MTLDataType` 原始值、字节）；
4. **profile 指纹**（含 policy）；
5. **规范化的 lowering 输入**（`canonical_inputs`，见下）；
6. 当 stage 链接函数时：**每个 linked function 的 list、名字、AIR hash、常量值**；
7. 当 stage 链接 dynamic library 时：**它的 import 被搜索的每个库，按顺序（install name + 内容 hash），以及没有加载成功的那个 install name**。

`)`

向后兼容的保证 `KNOWN`：没有 linked function 的 stage 保持它在"链接功能存在之前"的 key；没有 `emulated_simdgroups`、`dropped_vertex_layer`、`storage_view_slots`、`signed_color_attachments`、`multisampled`、`replay_bindings`、`framebuffer_fetch` 编译的 stage 保持它在"那些输入存在之前"的 key；不链接 dynamic library 的 stage 保持它的 key。**这意味着上游在加字段时刻意不去 invalidate 既有缓存** —— 本项目在改 key 时也应遵守同样的纪律，否则每次改动都会清空整个 shader cache。

`PipelineKey = H(` **profile 指纹**，**各 stage 的 `FunctionCompileKey`（按 stage 顺序）**，以及 **artifact 所依赖的每一个 descriptor 字段（含固定功能状态，因为 artifact 携带它）** `)`。

#### `canonical_inputs` 的规范化规则（会影响 key 命中率）

`KNOWN`（`key.rs::canonical_inputs`）。这几条让"语义相同但写法不同"的 descriptor 共享 key：

| 规则 | 说明 |
|---|---|
| 空的 vertex-fetch projection 写成 none | 一个不读任何 attribute 的 vertex 函数，**带不带 vertex descriptor 都编译成一样的东西** |
| stage-input descriptor 规范化 | `StageInputDescriptor::canonical()`：只保留被某个 attribute 命名的 layout；constant step 的 stride 写成 `Some(0)`、step rate 写成 0（它只读一个元素，在它的 offset 处，不管 stride 是静态的还是 per-bind 的）；index type 与 index buffer 保持 Metal 默认，除非某个保留的 layout 步进 index buffer。**取法相同的 descriptor 彼此相等** |
| `max_call_stack_depth` 为 0 当作 1 | 1 是 Metal 默认，即"完全没有深度" |
| Metal 默认的 tessellation state 当作没有 state | `out.tessellation = inputs.tessellation.filter(\|d\| *d != TessellationDescriptor::default())` |
| `threadgroup_size_matches_tile_size` 只在 tile 函数上有意义 | `inputs.threadgroup_size_matches_tile_size && inputs.tile_attachments.is_some()` |

另有一条历史兼容的编码细节 `KNOWN`（`inputs_encoding`）：key 已经 hash 过的那部分 lowering 输入（vertex-fetch projection、storage-image 选择、device-address slot）按"在加字段之前 `LoweringInputs` 的 derive `Debug` 所写的样子"编码。map 与 set 是规范的（有序、plain enum），所以它们的 `Debug` 形式是一个全序、确定的编码。**后来的字段只在被设置时由 `function_key` 追加。**

### 9.4 artifact 的编解码与失效

`KNOWN`（`cache/mod.rs`、`cache/envelope.rs`、`cache/codec.rs`、`cache/scan.rs`、`cache/artifacts.rs`）。

trait `PipelineArtifact`（由 `ComputePipeline` 与 `RenderPipeline` 实现）给出一对方法：

- `to_bytes()` —— 编码；
- `from_bytes_for_key(key, ...)` —— 解码存在某个 key 下的字节。

`CompiledFunction` 有同样的一对。

**一次 decode 校验**（按顺序）`KNOWN`：

1. 格式版本（`ARTIFACT_FORMAT_VERSION`）
2. 语义版本（`SEMANTICS_VERSION`）
3. **key**
4. **设备的 profile 指纹**
5. 一个 checksum（SHA-256）
6. 然后**线性扫一遍每个模块**（`cache::scan`）做合理性检查

**它不重跑 verifier** `KNOWN`。信任来自"上述身份 + 那次线性扫描"，而不是重跑自有的 verifier。

**每一个 `ArtifactError` 都是一次 cache miss** `KNOWN`：重新编译并替换该条目。**不要把它当错误上报给 guest。**

缓存粒度 `KNOWN`：

| 层 | key | 存哪里 |
|---|---|---|
| `CompiledFunction`（单函数） | `FunctionCompileKey` | 消费方。`Device::function_compile_key` 不解码就能算出来 |
| `ComputePipeline` / `RenderPipeline` | `PipelineKey` | 消费方。`Device::compute_pipeline_key` 不解码；`Device::render_pipeline_key` 会解码（但不 lowering）vertex 函数以知道它读哪些 attribute，返回 `RenderPipelineKeys`（pipeline 的 key、每个 stage 的 function key、每个函数 stage 所用的 `LoweringInputs`） |
| `BindingPlan` | `(PipelineKey, BindShape)` | **只在内存里 memo** `KNOWN`（`cache/mod.rs`："A `BindingPlan` memoizes in memory on `(PipelineKey, BindShape)`"） |
| 失败的编译 | 仅在 `Error::is_permanent_for` 允许时 memo | 见 `30-SHADER-AIR.md` 6.5：只有 `Budget` 与 `Cancelled` 是瞬态 |

### 9.5 content digest（与 key 不同）

`KNOWN`（`cache/digest.rs`；`ComputePipeline::content_digest`、`RenderPipeline::content_digest`、`BindingPlan::content_digest`，均需 `serde` feature）。

规则：字段与 enum variant **按名字**，**处于零值的字段省略**（`0`、`false`、`None`、空），对 `serde` 序列化取 SHA-256。

与 key 的区别 `KNOWN`：**plan 不命名任何 cache key，也不命名任何版本号**，所以"两次构建对同一个 pipeline 按同一个 shape 做的 plan"给出相同 digest；它在 plan 陈述的任何值变化时变化。**它标识内容，不认证任何东西。**

一条重要的维护纪律 `KNOWN`（`bind/plan.rs` 的注释）：

> 往 plan 类型加字段时：plan 的 content digest 会省略零值字段，所以**新字段必须恰好在"plan 的含义与该字段不存在时相同"的时候保持它的零值**。如果它的零值会让既有 plan 表示新行为，这次增加还必须 bump runtime version 或 validation executor 的 ABI —— digest 看不见它。

> **本项目含义**：`80-TEST-HARNESS.md` 应把 `content_digest` 作为"artifact / plan 没变"的断言（比 SPIR-V hash 更全面，因为它覆盖 layout、interface、requirements），并把 `RUNTIME_VERSION` 作为运行记录的 key。

---

## 10. `BindingPlan` 与两级绑定模型

来源：`crates/metal2vulkan/src/bind/mod.rs`（模块文档是契约本身）、`bind/plan.rs`、`bind/instantiate.rs`、`bind/state.rs`、`bind/dispatch.rs`、`bind/graphics.rs`、`bind/neutral.rs`。

### 10.1 两级模型

`KNOWN`（`bind/mod.rs`）：

**第 0 级：消费方描述绑定了什么。** 一个 `BindState`，按 Metal slot 键入：每个 `Stage` 一个 `StageTable`，内含 `BoundBuffer`、`BoundTexture`、`BoundSampler` 与 threadgroup 内存长度；用 `useResource`/`useHeap` 变为 resident 的资源（`UsedResource`）；argument buffer 能命名的活 sampler state（`ArgumentSampler`）；以及 encoder 状态如 compute encoder 的 stage-in region（`StageInRegion`）与 render encoder 的 tessellation factor buffer（`TessellationFactors`）。

**第 1 级：plan，按 shape。** `BindState::shape()` 保留"能改变一个 plan 的东西"（`BindShape`：哪些 slot 绑了什么 kind 的资源、格式、sampler 模式、对齐 class 之类）。`ComputePipeline::plan` 与 `RenderPipeline::plan` 把 pipeline 与 shape 变成一个 `BindingPlan`。

> **`BindingPlan` 是 `(pipeline, device, shape)` 的纯函数：按 `(PipelineKey, BindShape)` memo 它。** `KNOWN`，上游两处明示（`bind/mod.rs` 与 `bind/plan.rs` 的模块文档）。

**第 2 级：instantiate，按命令。** `BindingPlan::instantiate_dispatch(Dispatch) -> DispatchCommands`，`BindingPlan::instantiate_draw(DrawCall) -> DrawCommands`。给出：

- 每个 buffer descriptor 要绑定的 range（`DescriptorRange`：**恰好那个 range，绝不更多**）；
- argument/handle table 要上传的字节（`DescriptorBytes`）与 resident root table 的字节（`RootTable`）；
- push-constant 字节，其中由消费方填入 device address 的洞（`PushHole`）；
- 要记录的 Vulkan dispatch 或 draw。

### 10.2 `BindingPlan` 字段

`KNOWN`（`bind/plan.rs`，`pub struct BindingPlan`，`#[non_exhaustive]`，`Default`）：

| 字段 | 类型 | 含义 |
|---|---|---|
| `variant` | `VariantKey` | shape 要求的 variant。**常规路径下为空**；非空时消费方必须按它编译 pipeline（render pipeline 用 `Device::compile_render_variant`）并为同一个 shape 重新 plan，那个 plan 会给出相同的 key |
| `specialization` | `SpecializationKey` | 本 shape 对 pipeline 的特化：shape 决定的那些常量（threadgroup 长度、slot 是否存在）。**每个 compute `DispatchRegion` 携带完整的 key：这些，加上它的 local size 与 `MultiRegion`** |
| `descriptors` | `Vec<DescriptorWrite>` | **每个 layout binding 与数组元素一条写** |
| `vertex_buffers` | `Vec<VertexBufferBind>` | |
| `uses` | `Vec<ResourceUse>` | staging、writeback 与 hazard 事实 |
| `push` | `PushTemplate` | instantiate 要填哪些 push 字段、填在哪 |
| `diagnostics` | `Vec<PlanDiagnostic>` | plan 做了什么、消费方可能想记日志的 |
| `compute` | `Option<ComputeTemplate>` | `instantiate_dispatch` 需要的 pipeline 与设备事实（**仅 compute plan**）。**对消费方不透明** |
| `graphics` | `Option<GraphicsTemplate>` | `instantiate_draw` 需要的（**仅 render plan**）。**对消费方不透明** |
| `views` | `ViewSetup` | render plan 的 draw 在该 shape 的 vertex amplification 下的 view；compute plan 取默认（无 multiview） |

`ViewSetup` `KNOWN`：

| 字段 | 含义 |
|---|---|
| `view_mask: u32` | multiview 的 view mask：amplification count > 1 时是 `(1 << count) - 1`，否则 0（无 multiview）。消费方用它创建 pipeline（`VkPipelineRenderingCreateInfo::viewMask` 或其 subpass 的），并在相同 view mask 的 render pass instance 里记录 draw |
| `base_layer: u32` | view 0 渲染进 pass 的第几层（从 pass 的第一层算）：第一个 view mapping 的 `renderTargetArrayIndexOffset`，当它小于 pass 的 `renderTargetArrayLength` 时取它，否则 0。消费方的 attachment view 从那里开始，view `a` 渲染进 `base_layer + a` 层。**无 multiview 时，`base_layer != 0` 的 draw 渲染进那一层，通过只针对它的 attachment view** |

vertex amplification 的语义 `KNOWN`："amplification `a` 是 view `a`，它读 `a` 作为自己的 `[[amplification_id]]`，并渲染进每个 attachment view 的第 `a` 层。"

`ComputeTemplate` / `GraphicsTemplate` 的字段**全部 `pub(crate)`** `KNOWN`，上游明示 "Opaque to the consumer"。**消费方不得尝试读它们**；它们只是 `instantiate_*` 的输入。

### 10.3 descriptor 写入规则

#### `DescriptorWrite`

`KNOWN`（`bind/plan.rs`）：

| 字段 | 类型 |
|---|---|
| `set` | `u32` |
| `binding` | `u32` |
| `array_element` | `u32` |
| `ty` | `vk::DescriptorType` |
| `source` | `WriteSource` |

#### `WriteSource` 全量

`KNOWN`（`bind/plan.rs`，`enum WriteSource`，`#[non_exhaustive]`）。这是消费方真正要照着写 descriptor 的那个枚举：

| variant | 消费方要做什么 |
|---|---|
| `Buffer { slot }` | 写该 slot 绑定的 buffer。**range 由 slot 的 window 与 bind offset 导出；消费方绑定恰好那个 range，绝不更多** —— 具体 range 来自 `instantiate_*` 的 `DescriptorRange` |
| `InlineBytes { slot }` | 消费方上传的 `setBytes` 数据 |
| `Texture { slot, view }` | 该 slot 绑定的 texture，按 `view`（`ImageViewDesc`）构造 view |
| `CombinedImageSampler { image, sampler }` | 一个 combined image sampler：它的 image（`ImageSource`）与它的 sampler（`SamplerSource`） |
| `YCbCrInPlace { slot }` | 两平面 YCbCr texture 的平面，就地读：一个 uniform texel buffer，覆盖两平面的字节，格式是 `YCbCrInPlace::format`，从第一个平面的第一个字节起算 `YCbCrInPlace::view_bytes` 字节。**只有在该 slot 的 in-place variant 下才绑它**（`VariantKey::ycbcr_in_place`） |
| `YCbCrPlanesImage { slot }` | 两平面作为一个 image，由设备自己的 sampler Y′CbCr conversion 采样：combined image sampler，image 是带 conversion 的那个 view，sampler 是该 binding 的 immutable sampler，**layout `GENERAL`**。只有 planes-image variant 下才绑 |
| `TexelBuffer { slot, format, window }` | 该 slot 绑定的 texture buffer，作为 texel buffer view |
| `Sampler { slot, compare, integer, opaque_black }` | 为这次使用构造一个 `VkSampler`：`compare` 打开 depth comparison，`integer` 选整数 border color（`metal::sampler::SamplerUse`、`bind::sampler_desc`）。**plan 校验 shape 陈述的部分（reduction）；descriptor 的其余部分是 per-bind 的。** `opaque_black` 说明"不透明黑 border 如何构造，使它通过该 sampler 遇到的每个 texture 都读出 Metal 的那个 texel" |
| `ArgumentTable { stage, bytes_len }` | 该 stage 的 argument table；**instantiate 填字节** |
| `HandleTable { stage, bytes_len }` | 该 stage 的一张 handle table（它的 texture table 或 sampler table），一个 `bytes_len` 字节的**只读 storage buffer**，内容由 instantiate 给（`DescriptorBytes`）。**消费方绑定恰好 `bytes_len` 字节：shader 从绑定的 range 数表里的条目数** |
| `ConstantBlob { stage }` | 该 stage 的 `StageModule::constant_blob`，**由消费方 pad 到 16 字节** |
| `HeapEntry { class, element, source, view }` | set 1 heap 的 `class` array 的第 `element` 个元素：resident texture `source`，按 `view`。**一个 texture 的每次写只有一个 layout**：某个 storage array 持有它时、或该 texture 绑在某个 slot 上而那个 slot 自己的 binding 是 storage image 时用 `GENERAL`；否则 `SHADER_READ_ONLY_OPTIMAL` |
| `Attachment { color_index }` | 该 color attachment 作为 input attachment |
| `Neutral(NeutralResource)` | 一个中性替身：静态使用了，但（兼容的）东西没绑。**每个设备把 `Device::neutral_kinds()` 里的每一种创建一次** `KNOWN` |
| `TessellationFactors` | encoder 的 tessellation factor buffer（`BindState::tessellation_factors`），control stage 的只读 storage buffer，覆盖该 draw 的 `DescriptorRange` |
| `AccelerationStructure { slot, level }` | 绑在 buffer slot 上的 acceleration structure 的 top-level structure：`level == Instance` 时就是绑定的 instance structure；`level == Primitive` 时是"一个覆盖绑定的 primitive structure 的单实例 top-level structure"（`bind::acceleration::primitive_wrap`）。**guest 没绑的 slot 取一个零实例的 top-level structure，任何 ray 都 miss 它** |
| `Imageblock` | render pass 的 fragment imageblock 存储（`GraphicsState::fragment_imageblock`）：消费方为该 pass instance 创建的那一个 storage image，**`GENERAL` layout**，绑给 pass 的每个 draw，以及每个"显式 imageblock 独立存在"的 tile dispatch |
| `StorageAttachment { color_index, view, format }`（名称按 doc 推断） | render pass 的该 color attachment 作为 storage image：`view` 命名的那个 view，格式 `format`，identity component mapping，`GENERAL` layout。`StorageAttachmentView::Attachment` 是对 attachment 自身 image 的 2D view（pass 的那一层那一级）；`StorageAttachmentView::SamplePlanes { layers }` 是对 sample planes 的全部 `layers` 层的 2D-array view。**tile dispatch 的特别规则**：image 的格式是 tile pipeline descriptor 的（`TileRenderPipelineDescriptor::color_attachment_formats`，Metal 对 pass 的要求），extent 至少是 render area（`BindState::render_area`）；整数格式时 `format` 就是 image 自己的，浮点格式时是"同通道同宽度的无符号整数格式"（`R16_SFLOAT` → `R16_UINT`），**使 dispatch 搬的是 texel 的位**，所以消费方创建这种 image 要带 `MUTABLE_FORMAT`（它自己的格式不支持 storage 时还要 `EXTENDED_USAGE`） |
| `ExecutionStatus` | command buffer 的 `ExecutionStatus` buffer（在不给 buffer 地址的设备上） |
| `SnapshotTexels`、`ExtendedShadow`、`TileMap`、`MeshRecords` 等 | 对应 `BindingSource` 的同名项 |

（`WriteSource` 在 `Imageblock` 之后还有若干 variant，本次未读完。**未查**，查清方法：读 `crates/metal2vulkan/src/bind/plan.rs` 第 700 行之后到 `PushTemplate` 之前。）

#### `DescriptorRange`

`KNOWN`（`bind/instantiate.rs`）。**这是 descriptor 写入最关键的约束。**

| 字段 | 类型 |
|---|---|
| `set` | `u32` |
| `binding` | `u32` |
| `range` | `BufferRange { offset: u64, range: u64 }` |

doc comment 的全文（要点）`KNOWN`：

> plan 的一个 buffer descriptor 为这次 draw 或 dispatch 绑定的 range。对 `WriteSource::Buffer`，`range.offset` 从**绑定的 allocation 的起点**算；对 `WriteSource::InlineBytes`，从**消费方上传那些字节的起点**算（消费方把它放在对齐到该 descriptor type 的 `min*BufferOffsetAlignment` 的 offset 上）。
>
> **消费方绑定恰好这个 range，绝不更多。** 它至少 16 字节，位于被 pad 到 16 字节的 allocation 之内，且它的 offset 是那个对齐的倍数。

#### `DescriptorBytes`

`KNOWN`：`{ set: u32, binding: u32, bytes: Vec<u8> }`。消费方把 `bytes` 上传到某处并把那个 `(set, binding)` 的 descriptor 指向它。

#### `NeutralResource`

`KNOWN`（`bind/neutral.rs`）。规则：**每个设备把 `Device::neutral_kinds()` 的每一种创建一次**，然后 plan 里出现 `WriteSource::Neutral(kind)` 时写那一个。

### 10.4 push constant 的下发规则

#### `PushTemplate`

`KNOWN`（`bind/plan.rs`）：

```
PushTemplate { fields: Vec<PushFieldPlacement> }     // 每个 stage 内按放置顺序
PushFieldPlacement { stage: Stage, field: PushField, location: FieldLocation, size: u32 }
FieldLocation = PushWindow { offset: u32 }           // pipeline 的 push-constant 块内的字节偏移
              | ArgumentTable { offset: u32 }        // 溢出到该 stage 的 argument table 内的字节偏移
```

**关键事实**：push 字段可能**溢出到 argument table**。一个只会写 push constant 的消费方会漏掉这些字段。

#### `PushHole`

`KNOWN`（`bind/instantiate.rs`，`enum PushHole`）。上游明示它是"消费方在上传 `descriptor_bytes` **之后**填的 push-constant 字段：**一个声明的字段，不是一个补丁**"。

七个 variant，每个都是"一个 device address 或一个小整数"：

| variant | 填什么 | 宽度与位置 |
|---|---|---|
| `RootTableAddress { stages, offset }` | 上传好的 resident root table（`RootTable`）的 device address | `u64`，在每个 region 的 push 字节的 `offset`（**绝对偏移，在 push-constant 块内**） |
| `ExecutionStatusAddress { stages, offset }` | command buffer 的 `ExecutionStatus` buffer 的 device address | `u64`，同上 |
| `CommandRecordsAddress { stages, offset }` | 被重放的 ICB 的 record 存储（它的 header）的 device address | `u64`，在 device replay 的 preprocess push 字节的 `offset` |
| `ReplayRegionAddress { stages, offset }` | 一个 device-replay variant 的 dispatch 要读的 region record 的 device address（`ReplayLayout::region_offset`，在 replay 的 scratch 里按命令与 region 定位） | `u64`。注意三种来源：replay 之外的 flat variant 的 dispatch（`instantiate_dispatch`）读它的 preprocess 写在 group count 旁边的那条 record；一个 folded object 函数的 mesh draw（`TASK_EXT`）读它的 scratch 的 region record —— 来自 arguments pass（`DrawCommands::mesh_arguments`）或上传的 fold（`DrawCommands::object_fold`），位于 `MeshArguments::OBJECT_RECORD`，**是 16 的倍数** |
| `CaptureIndexAddress { stages, offset }` | 一个 de-indexed draw 的第一个 index 的 device address（`VariantKey::primitive_id_indices`）：draw 的 index buffer 的地址加它的 index offset。**binder 要求它是 index size 的倍数**，buffer 要有 `SHADER_DEVICE_ADDRESS` usage 且地址是 4 的倍数；或者是一个 private list 形式 draw 的 list（`VariantKey::private_list`） | `u64`，在 variant 的 **vertex** push 字节的 `offset` |
| `MergedDrawAddress { stages, offset }` | 一个 merged draw replay 的 header 的 device address（`MergedLayout::header_offset`，在 replay 的 scratch 里） | `u64`，在 merged variant 的 **vertex** push 字节的 `offset`（`PushField::MergedDrawAddress`） |
| `SnapshotPhase { stages, offset }` | 一个 snapshot variant（`VariantKey::snapshot_textures`，`PushField::SnapshotPhase`）的哪一个 draw 在跑 | **`u32`**，在 variant 的 **fragment** push 字节的 `offset`：**拍快照的那个 draw 填 1**（它的每个 color write mask 都是 0），**读快照的那个 draw 填 0**（用 pipeline 的 mask） |

> **消费方规则**：
> 1. push 字节由 `instantiate_*` 给出，**消费方只在 `PushHole` 指定的 offset 上写指定宽度的值**。
> 2. `PushHole` 的 `stages` 字段说明该洞出现在哪些 stage 的 push range 里；`vkCmdPushConstants` 要用它。
> 3. **顺序**：先上传 `descriptor_bytes`（与 `RootTable` 的字节），拿到 device address，**再**填洞，**再** `vkCmdPushConstants`。
> 4. `FieldLocation::ArgumentTable` 的字段**不走 `vkCmdPushConstants`**，走对应 stage 的 argument table 的 `DescriptorBytes`。

### 10.5 `RootTable` 的字节布局（必须精确实现）

`KNOWN`（`bind/instantiate.rs`，`pub struct RootTable` 的 doc comment）。这是 pointer translation 的核心数据结构。**32 字节一条，little-endian**，字段顺序 `{host, guest, size, bind_offset}: u64`：

| 条目 | 内容 |
|---|---|
| 0 | **null root（全零）** |
| 1 | **sink**。它的 `host` 字段（在 `RootTable::SINK_HOST_OFFSET`）留 0，**由消费方填入它的 `NeutralResource::Sink` 的 device address**。它的 `guest` 与 `size` 字段装 resident set 的首 root `R0` 与条目数 `N` |
| `2 + n` | `BufferForm::Psb` 的 slot `[[buffer(n)]]`。**未绑定时为零，所以通过它的每次访问都被 contain** |
| `R0 .. R0 + N` | **resident set**，按 guest address 排序且互不相交，每条 `bind_offset = 0` |

消费方的三步 `KNOWN`：

1. 写 sink 地址；
2. 把字节上传到一块**device address 是 16 字节对齐**的内存；
3. 用那个地址填 `PushHole::RootTableAddress`。

另有一条高级用法 `KNOWN`：`R0` 以"从表自身地址起的 32 字节条目数"计，模 2⁶⁴，所以消费方可以让表指向一个它上传在别处的 resident set（`ResidentSet`）：表与 set 都 32 字节对齐，且 set 至少持有表自己的那些 range（`RootTable::resident_ranges()`），然后把 `RootTable::resident_fields(table, set, count)` 给出的 16 字节写到 sink 条目的 `guest` 与 `size` 字段上，位置是 `RootTable::RESIDENT_FIELDS_OFFSET`。常量 `RootTable::ENTRY_ALIGNMENT = 32`。

### 10.6 `ResourceUse`（barrier 与 staging 的唯一依据）

`KNOWN`（`bind/plan.rs`）：

```
ResourceUse {
    resource: UseTarget,
    access: AccessSet,            // 由 lowering 证明；未知访问是 READ_WRITE
    class: AccessClass,
    stages: vk::PipelineStageFlags2,
    range: Option<ByteRange>,     // None: 从绑定 offset 起的整个资源
}
```

`range` 的"绑定 offset"定义 `KNOWN`：一个 slot 的是它的 bind offset；index buffer 的是该 draw 的 index offset；indirect buffer 的是 arguments 的 offset。

`UseTarget` 全量 `KNOWN`：`Slot(SlotRef)`、`Used(u32)`（一个 used resource，按消费方 token）、`IndexBuffer`、`Indirect`、`TessellationFactors`、`TileMap(SlotRef)`（sparse texture 的 tile map，整块：**消费方在命令前更新 map（mapping 改变）需要一个到这次读的 barrier**）、`PatchIndices`、`ControlPointIndices`。

`AccessClass` 全量 `KNOWN`（用于选 barrier 的 stage/access）：`Storage`、`Uniform`、`Sampled`、`StorageImage`、`VertexInput`、`Index`、`Indirect`、`Attachment`、`YCbCrPlanes`（两平面 YCbCr texture 的平面，就地读：**是对平面字节的读，不是对 texture 的 image 的读**）。

层级 `KNOWN`：`BindingPlan::uses` 是 shape 的（绑定的 slot、used resource）；`DrawCommands::uses` 与 `DispatchCommands::uses` **再加上每条命令自己的 index buffer 与 indirect arguments**。

> **消费方规则**：barrier 必须完全由 `uses` 驱动。`access` 是证明出来的（未知时保守取 `READ_WRITE`），`class` 与 `stages` 直接给出 barrier 的参数。**不得自己从 descriptor 或 shader 去推 barrier**。

### 10.7 `instantiate_*` 的产物与多 region

`KNOWN`（`bind/mod.rs`、`bind/dispatch.rs`、`bind/graphics.rs`）：

- `DispatchCommands`（`bind/dispatch.rs`）：含 `Vec<DispatchRegion>`。**一个 Metal dispatch 可以变成多条 Vulkan dispatch**，每条带它完整的 specialization constant，**所以消费方要为每个不同的 specialization 创建一个 `VkPipeline`**。
- `DispatchRegion`：携带创建该条 `VkPipeline` 所需的 `specialization`、`stage_flags`、`required_subgroup_size`（见 2.1 的警告）。
- `DrawCommands`（`bind/graphics.rs`）：含 `uses`、`index_bounds_pass`、`indirect_needs_arguments`、`amplifications`、`mesh_arguments`、`object_fold` 等字段。
- 拒绝是 `BindError`（`crate::error::BindError`）。典型：`BindError::NeedsVariant`（需要另一个 variant）、`MissingStageInRegion`、`DescriptorRangeExceeded`。

### 10.8 消费方需要记录的辅助 pass（节选）

`KNOWN`（`bind/mod.rs` 模块文档）。上游提供了大量 helper kernel/module，**消费方按 plan 的指示记录它们**。本项目需要知道它们存在，因为每一个都意味着额外的 `VkPipeline` 与 dispatch：

| 场景 | 上游提供的 |
|---|---|
| 每个 command buffer | 一个 `ExecutionStatus` buffer：用 `ExecutionStatus::initial()` 初始化，用 `ExecutionStatus::decode()` 读回（报告 clamp 掉的 indirect count 与 resident-set miss） |
| indirect dispatch | 可带一个 `IndirectClamp` 前置 pass（`indirect_clamp_module`） |
| 没有东西界住 index fetch 的 indexed indirect draw | `IndexBoundsPass`（`index_bounds_plan_module` + `index_bounds_fill_module`），或整批共用一个 `IndexBoundsRun` |
| Vulkan input assembly 组不出 Metal 那样图元的 indexed draw（strip 在非全 1 的 index 处重启） | `IndexRewritePass`（三条 `index_rewrite_module` dispatch，`RewritePhase`）+ 一条 indirect draw；或 `IndexRewriteRun`；或 `IndexGather`（`index_gather_module`，indirect 的还要一条 `index_gather_plan_module`） |
| `Boolean` visibility result | `VisibilityResolve`（`visibility_resolve_module`）；跨 render pass instance 时先 `VisibilityCombine`（`visibility_combine_module`） |
| fetching draw 读多采样 attachment 的 sample plane | `planes_split_module` / `planes_merge_modules`（`PlanesCopy`） |
| 多采样 depth/stencil aspect 的移动与 resolve | `depth_stencil_copy_modules`、`stencil_split_module`、`depth_stencil_resolve_modules` |
| 设备 blit 过滤不了的格式的 mipmap | `MipmapFilterChain`（`mipmap_filter_module`），`float` 双线性 |
| kernel 编码进 ICB 的 compute 命令 | `replay_preprocess`（`replay_preprocess_module`）+ `instantiate_replay`；或在有 `VK_EXT_device_generated_commands` 时 `replay_preprocess_generated` |
| 不观察 threadgroup partition 的 kernel 的 indirect dispatch | `flat_dispatch_module`（`FlatIndirect`） |
| 一条命令既通过"拷进拷出的 texture"又用别的方式写同一 buffer 的字节 | `shadow_merge_module` / `shadow_merge_image_module` / `shadow_merge_kept_image_module` / `shadow_copy_back_module` / `shadow_copy_in_module` |
| 两 buffer 间多行等长拷贝 | `rows_copy_module` |
| 两平面扩展范围 texture 相关的 blit | `plane_words_module`、`plane_copy_module`、`plane_bytes_copy_module` |
| 旋转 texture / heap 的两平面 texture / heap 的宿主页 texture | `rotate_texels_module`、`two_plane_texels_module`、`tiled_texels_module` |
| 设备没有对应块格式 | `astc_decode_module`（`BlockDecodeModule`）、`pvrtc_decode_module`、`etc_decode_module`、`chroma_decode_module`/`chroma_sample_module` |

另有若干查询函数 `KNOWN`：`sampler_desc`（一个 plan 的 sampler write 需要的 Vulkan sampler）、`heap_classes`（某 profile 上 handle heap 的 array class）、`FunctionTableWords`、`FunctionTableSnapshot`、`instance_record`/`primitive_wrap`/`geometry_flags`/`geometry_table_offset`（acceleration structure）、`RasterizationRateMap`（消费方的 `MTLRasterizationRateMap`）、`SparseTileMap`、**`ArgumentBufferLayout`**（argument encoder 在 argument buffer 里把每个参数写在哪：一个函数的 `Function::argument_buffer_layout`，或由一组 `ArgumentDescriptor` 构造的 `ArgumentBufferLayout::from_descriptors`，常量 `ARGUMENT_HANDLE_BYTES`）。

### 10.9 `PlanDiagnostic`

`KNOWN`（`bind/plan.rs`，`enum PlanDiagnostic`）：

| variant | 含义 |
|---|---|
| `IncompatibleBinding { slot, substituted }` | 该 slot 绑定的资源与 shader 声明的类型不符；**写的是声明类型的 neutral**（**guest 的未定义行为**） |
| `IncompatibleHeapEntry { class, element, source, substituted }` | resident texture `source` 在"除数值类型外"都匹配该 class 的 heap array，而 array 的数值类型只是"只被 query 的 heap group"的默认值（`RuntimeFact::HeapNumericType`）：该 array 的第 `element` 个元素是 neutral，所以通过指向 `source` 的句柄做的 query 答的是 neutral 的 |
| （还有一个 cross-class 的 variant，关于绑定 texture 的数值类型 class 与声明的不符） | plan 没有精确答案；plain Metal 对这种 texture 按它自己的 class 读、把 words 当声明类型交回（写时把 lane 的位按它自己的 class 存），该 slot 的 variant（`VariantKey::cross_class`）给出这个行为 |

> **消费方规则**：`diagnostics` 应当**记日志但不致命**。`IncompatibleBinding` 是 guest 的 UB，Metal 自己也不保证。但本项目在开发期应当把它**当错误看待**，因为它更可能是本项目的 slot 映射写错了，而不是 guest 真的在做 UB。

---

## 11. 消费方必须做什么、禁止做什么

这一节是本分册的操作性结论。每条都给出上游依据。

### 11.1 必须做

| # | 必须 | 依据 |
|---|---|---|
| 1 | **按 `PipelineLayout` 原样创建 descriptor set layout 与 push-constant range，不重新编号。** `bindings` 已经是稠密的 `0..n`，`stages` 恰好是静态使用者 | `layout.rs` 模块文档；`ARCHITECTURE.md` 不变量 2（link 只往预留槽里写字面数字） |
| 2 | **按 `BindingPlan::descriptors` 与 `instantiate_*` 的 `DescriptorRange` 写 descriptor，绑定恰好那个 range** | `DescriptorRange` doc comment："The consumer binds exactly this range, never more" |
| 3 | **compute stage 从 `DispatchRegion` 取 specialization / stage_flags / required_subgroup_size**，不用 `StageModule` 的默认值 | `StageModule::specialization`、`stage_flags`、`required_subgroup_size` 三处 doc comment；违反是 Vulkan 非法用法（VUID-02759 / VUID-02757） |
| 4 | **为每个不同的 specialization 创建一条 `VkPipeline`** | `bind/mod.rs`："the consumer creates one `VkPipeline` per distinct specialization" |
| 5 | **按 `RenderPipeline::runs_stage(at, topology)` 过滤 geometry stage**，不自己数 | `runs_stage` doc comment |
| 6 | **barrier 完全由 `ResourceUse` 驱动** | `ResourceUse::access` "Proven from lowering; unknown access is `READ_WRITE`" |
| 7 | **memo `BindingPlan` on `(PipelineKey, BindShape)`** | `bind/plan.rs`："A plan is a pure value of `(pipeline, BindShape)`, memoized by the consumer" |
| 8 | **`BindingPlan::variant` 非空时重新编译并重新 plan** | `BindingPlan::variant` doc comment |
| 9 | **每个设备创建 `Device::neutral_kinds()` 的每一种一次** | `bind/mod.rs` |
| 10 | **每个 command buffer 绑一个 `ExecutionStatus` buffer**，用 `initial()` 初始化、`decode()` 读回 | `bind/mod.rs` |
| 11 | **把 `SOURCE_DIGEST` 加入缓存 key** | `cache/mod.rs::SOURCE_DIGEST` doc comment |
| 12 | **把每个 `ArtifactError` 当 cache miss 处理**：重编译并替换条目，不上报 guest | `cache/mod.rs`："Every `ArtifactError` is a cache miss" |
| 13 | **按 `dependencies` 的 `Mechanism` 逐项决定要做什么**。`mechanism` 是全函数，不存在"要自己想办法"的情形 | `facts.rs` 模块文档 |
| 14 | **把 `PipelineInterface::numbered_samplers` 作为 sampler resource ID 的唯一来源** | `NumberedSampler` doc comment（M4 / M3 Max 实测） |
| 15 | **用 `bind::ArgumentBufferLayout` 布置 argument buffer** | `30-SHADER-AIR.md` 4.11：`[[id(n)]]` 要沿嵌套路径累加，且不等于 LLVM 字段索引 |
| 16 | **PushHole 填值的顺序**：先上传 descriptor bytes 与 root table、取 device address，再填洞，再 `vkCmdPushConstants` | `PushHole` doc comment："the consumer fills after uploading `descriptor_bytes`" |
| 17 | **把 `FieldLocation::ArgumentTable` 的 push 字段写进 argument table**，不只写 push constant | `PushTemplate` / `FieldLocation` |
| 18 | **`RootTable` 按 32 字节条目精确实现，填 sink 的 `host` 字段，16 字节对齐上传** | `RootTable` doc comment |

### 11.2 禁止做

| # | 禁止 | 为什么 |
|---|---|---|
| 1 | **禁止自行推导 descriptor set / binding 号** | link 已分配，且保证稠密无洞、无 Metal argument table 冲突。自己推会与 SPIR-V 里已写好的字面量不一致 `KNOWN`（`layout.rs` 模块文档；`ARCHITECTURE.md` 不变量 2） |
| 2 | **禁止改写、patch 或重新编号 SPIR-V** | `ARCHITECTURE.md` 不变量 1："nothing parses SPIR-V words to decide what to emit"；不变量 2：link 与 relocate 只写字面数字到预留槽，所以一个 compiled function 被每条 pipeline 复用。改写会破坏 relocation 契约与 golden hash，且 verifier 已经跑过、改写之后没有任何东西再验它 |
| 3 | **禁止自行从 SPIR-V 推导 capability / extension** | 它们由模块内容推导，必须落在 profile 内，否则 `Error::Internal(RequirementsExceedProfile)`。用 `Requirements` `KNOWN` |
| 4 | **禁止自行推导 Metal argument buffer 的 `[[id(n)]]`** | 要沿嵌套 `IndirectStruct::first_id` 累加，`IndirectArg::ordinal` 不是它 `KNOWN`（`30-SHADER-AIR.md` 4.11） |
| 5 | **禁止把 slot 的 `Slot::index` 在 decode 阶段当常量读** | 它可能是 `AbiInt::Global`，要等 canonicalization 求值 static initializer `KNOWN`（`30-SHADER-AIR.md` 4.5） |
| 6 | **禁止绑定比 `DescriptorRange` 更大的 range** | 明文禁止。更大的 range 会让 robustness 行为与上游证明的 window 不一致 |
| 7 | **禁止用 `StageModule` 的默认 specialization 创建 compute `VkPipeline`** | 是 Vulkan 非法用法 `KNOWN` |
| 8 | **禁止读 `ComputeTemplate` / `GraphicsTemplate` 的字段** | 它们是 `pub(crate)`，上游明示 "Opaque to the consumer"。字段会变 |
| 9 | **禁止用 Git SHA 作为缓存 key 的全部** | 同一 SHA 在不同 feature 下源码集不同。必须用 `SOURCE_DIGEST` + 四个版本号 `KNOWN` |
| 10 | **禁止重跑 verifier 来"确认" artifact** | decode 已经校验版本、key、profile 指纹、checksum 并线性扫过模块。重跑是浪费，且 `verify` 失败在这里只会是 `Internal` |
| 11 | **禁止把 `Error::NeedsInput` 透传给 guest** | 它表示本项目自己没有把 descriptor 里的信息补全。应在胶水层断言 `KNOWN`（`ARCHITECTURE.md`："asked for and never guessed"） |
| 12 | **禁止用 `BindingSource` 去构造 descriptor write** | `BindingSource` 是 layout 侧的只读描述；写入由 `WriteSource` 决定，两者的 variant 集合不同（例如 `WriteSource::Neutral` 在 `BindingSource` 里没有对应项） |
| 13 | **禁止在 `plan` 之外的地方调用 Vulkan 相关推断** | binder 从不调用 Vulkan，它的输出就是全部需要的 plain data。另起一套推断就会与它不一致 `KNOWN`（`bind/mod.rs` 首句） |
| 14 | **禁止往 plan 类型加"零值会改变既有行为"的字段而不 bump `RUNTIME_VERSION`** | content digest 省略零值字段，看不见它 `KNOWN`（`bind/plan.rs` 的维护注释） |

---

## 12. Metal pipeline descriptor → 上游 descriptor 的全量字段映射

来源：`crates/metal2vulkan/src/pipeline/descriptor.rs`。

模块文档给出总原则 `KNOWN`：

> 消费方解码出的 guest descriptor **逐字段**映射到这些上;原始 `u32` 序数通过 `metal::` 的 `TryFrom<u32>` impl 转换，**那些 impl 会拒绝未知值**。构造器从 Metal 自己的默认值开始。尚未实现的特性（mesh、tile、tessellation）**仍然有它们的 descriptor 字段，这样拒绝才是类型化的**。

全部 descriptor 都是 `#[non_exhaustive]`，所以**不能在 crate 外用 struct literal 构造** `KNOWN`（`pipeline/mod.rs`）：必须 `new(...)` 之后逐字段赋值。

### 12.1 `MTLRenderPipelineDescriptor` → `RenderPipelineDescriptor`

`KNOWN`。构造器 `RenderPipelineDescriptor::new(vertex: StageSource)`。

| Metal 属性 | 上游字段 | 类型 | Metal 默认 | 是否进 key | 备注 |
|---|---|---|---|---|---|
| `vertexFunction` | `vertex` | `StageSource` | 必填 | **是** | |
| `fragmentFunction` | `fragment` | `Option<StageSource>` | `None` | **是** | **rasterization 关闭时也要传**：Metal 两种情况都链接它，所以它的拒绝能看到它（带 ICB 的 texture、没有 depth attachment 的 depth output、没有 vertex output 写的 stage input），之后 runtime 再为编译把它丢掉；一个"不写任何已附加 color、也不读任何被保留的东西"的 fragment 函数会被造出来 |
| `vertexDescriptor` | `vertex_descriptor` | `Option<VertexDescriptor>` | `None` | **是**（规范化后，见 9.3） | |
| `colorAttachments[i]` | `color_attachments` | `[Option<ColorAttachmentDescriptor>; 8]` | 全 `None` | **是** | **`MTLPixelFormatInvalid` 映射为 `None`** |
| `depthAttachmentPixelFormat` | `depth_format` | `Option<metal::PixelFormat>` | `None` | **是** | |
| `stencilAttachmentPixelFormat` | `stencil_format` | `Option<metal::PixelFormat>` | `None` | **是** | |
| `rasterSampleCount` | `raster_sample_count` | `u32` | `1` | **是** | |
| `alphaToCoverageEnabled` | `alpha_to_coverage` | `bool` | `false` | **是** | |
| `alphaToOneEnabled` | `alpha_to_one` | `bool` | `false` | **是** | 设备没有 Vulkan `alphaToOne` 时拒绝（`Feature::AlphaToOne`） |
| `rasterizationEnabled` | `rasterization_enabled` | `bool` | `true` | **是** | |
| `inputPrimitiveTopology` | `input_primitive_topology` | `metal::PrimitiveTopologyClass` | `Unspecified` | **是** | |
| `maxVertexAmplificationCount` | `max_vertex_amplification_count` | `u32` | `1` | **是** | **> 1 时 pipeline 是 multiview pipeline；0 是非法 descriptor** |
| （tessellation 相关的若干属性） | `tessellation` | `Option<TessellationDescriptor>` | `None`（= Metal 默认） | **是**（非默认时） | 只对 post-tessellation vertex 函数生效；对其他 vertex 函数**忽略** |
| `supportIndirectCommandBuffers` | `support_indirect_command_buffers` | `bool` | `false` | **是** | |
| `maxVertexCallStackDepth` | `max_vertex_call_stack_depth` | `u32` | `1` | **是**（0 与 1 规范化为同一值） | `Function` vertex stage 在它之下编译（`LoweringInputs::max_call_stack_depth`） |
| `maxFragmentCallStackDepth` | `max_fragment_call_stack_depth` | `u32` | `1` | **是**（同上） | |
| `supportAddingVertexBinaryFunctions` | `support_adding_vertex_binary_functions` | `bool` | `false` | **否** | pipeline 不依赖它 |
| `supportAddingFragmentBinaryFunctions` | `support_adding_fragment_binary_functions` | `bool` | `false` | **否** | |
| `vertexBuffers[i].mutability` | `vertex_buffers` | `BTreeMap<u32, metal::Mutability>` | 未列出的是 `Mutability::Default` | **否** | **上游实测（M3 Max + M4）：Metal 把它当作给优化器的承诺 —— 对 immutable buffer 的写会落下去，API 与 shader validation 都不阻止。** 所以不进 key |
| `fragmentBuffers[i].mutability` | `fragment_buffers` | `BTreeMap<u32, metal::Mutability>` | 同上 | **否** | |
| `textureWriteRoundingMode`（**Apple SPI**） | `texture_write_rounding_mode` | `metal::TextureWriteRoundingMode` | `TowardZero` | **是** | fragment 函数对 half-float color attachment 的 `float` 输出怎么 round。`Function` fragment stage 在它之下编译（`LoweringInputs::color_writes`） |
| **Metal 私有固定功能状态**（Apple SPI，OpenGL on Metal 设置的） | `private` | `PrivateRenderState` | `PrivateRenderState::new()` | **是**（在 `pipeline_key` 里） | 见 12.2 |

### 12.2 `PrivateRenderState`（Apple SPI）

`KNOWN`（`descriptor.rs`，`pub struct PrivateRenderState`）。上游明示这些是"公共 SDK 任何头文件里都没有的 selector"，每一项在被设置之前都是 Metal 的默认值，**每一项在 Apple M4 上实测过**。一个"翻译还没做出其效果"的属性，在 pipeline 创建时拒绝非默认值 —— `NotImplemented` 配 `Feature::PrivateRenderState` 命名它（`error::PrivateRenderField`）。

| Apple SPI 属性 | 字段 | 默认 | Metal 上的实测效果 |
|---|---|---|---|
| `sampleMask` | `sample_mask: u64` | 全 1 | 在有 fragment 函数的 pipeline 里，**函数跑完之后**与 coverage 做 AND，超过 pipeline 采样数的位被忽略；没有 fragment 函数的 pipeline 忽略它 |
| `sampleCoverage` | `sample_coverage: f32` | `1.0` | 每个 2×2 quad 要保留的 sample 比例，在它的 window pixel 上 dither，与 `sample_mask` 一起在函数跑完之后施加。**采样数超过 4 时非 1 的值被拒绝**（Metal 在那里没被实测过） |
| `sampleCoverageInvert` | `sample_coverage_invert: bool` | `false` | **不改变 Metal 画什么** |
| `alphaTestEnabled` | `alpha_test_enabled: bool` | `false` | 开启时，fragment 在"`alpha_test_function` 对 color 0 的 alpha 与 render encoder 的 reference 成立"时通过，二者各按 8 位 unorm code 比较；失败的 fragment 什么都不写 |
| `alphaTestFunction` | `alpha_test_function: u64` | `0`（`MTLCompareFunctionNever`） | 原始值；**只在 alpha test 开着时读**，超过 `MTLCompareFunctionAlways` 的值被拒 |
| `logicOperationEnabled` | `logic_operation_enabled: bool` | `false` | 开启时 `logic_operation` 施加于每个 normalized、sRGB 与整数 color attachment 的 code，之后它们不做 blend；**float attachment 忽略它**。Copy 与 no-op 在每个设备上都能做；其他操作需要设备的 `logicOp`，且在"某个 attachment 是 sRGB、某个 float attachment 做 blend、或某个格式没被实测"时被拒 |
| `logicOperation` | `logic_operation: u64` | `0` | 原始值；只在开着时按低 4 位读，**按 Direct3D 的顺序**：0 clear、1 set、2 copy、3 copy inverted、4 no-op、5 invert、6 and、7 nand、8 or、9 nor、10 xor、11 equivalent、12 and reverse、13 and inverted、14 or reverse、15 or inverted |
| `clipDistanceEnableMask` | `clip_distance_enable_mask: u8` | `0xff` | **不改变 Metal 画什么**；vertex 函数写的每个 clip distance 都生效 |
| `pointSmoothEnabled` | `point_smooth_enabled: bool` | `false` | **未实现：开启被拒** |
| `pointCoordLowerLeft` | `point_coord_lower_left: bool` | `false` | **不改变 Metal 画什么**；`[[point_coord]]` 保持左上原点 |
| `pointSizeOutputVS` | `point_size_output_vs: bool` | `false` | **不改变 Metal 画什么**；点的大小就是 vertex 函数的 `[[point_size]]` |
| `twoSideEnabled` | `two_side_enabled: bool` | `false` | **不改变 Metal 画什么** |
| `vertexDepthCompareClampMask` | `vertex_depth_compare_clamp_mask: u32` | `0` | **不改变 Metal 画什么** |
| `fragmentDepthCompareClampMask` | `fragment_depth_compare_clamp_mask: u32` | `0` | 第 `s` 位把 fragment 函数通过 `[[sampler(s)]]` 做的 depth 比较的 reference clamp 到 `[0, 1]`（NaN 取作 0），**第 31 位**对应 constexpr sampler；**通过 argument buffer 的 sampler 做的比较在非 0 mask 下被拒** |
| `depthStencilWriteDisabled` | `depth_stencil_write_disabled: bool` | `false` | **不改变 Metal 画什么** |
| `needsCustomBorderColorSamplers` | `needs_custom_border_color_samplers: bool` | `false` | **不改变 Metal 画什么**；sampler 的私有 custom border color 在有它和没它时都采样为透明黑 |
| `vertexAmplificationMode` | `vertex_amplification_mode: u64` | `0` | 0 与 1 画法相同（取 encoder 设的 amplification count 与 view mapping）；**Metal 的 descriptor 在 2 或更大时断言**，所以被当作未知值拒绝 |
| `explicitVisibilityGroupID` | `explicit_visibility_group_id: u32` | `u32::MAX`（无） | 在 `maxVertexAmplificationCount == 1` 的 pipeline 里**不改变 Metal 画什么**；pipeline 做 amplification 时任何其他 group 都被拒（Metal 在那里画一个 copy 的 color 却算每个 copy 的 sample，这条规则没做） |

相等性 `KNOWN`：`PrivateRenderState` 自己实现 `PartialEq`，`sample_coverage` 按 `f32::to_bits()` 比较（`bits()` 方法）。

> **本项目含义**：这 19 项是 OpenGL on Metal（`GLDriver`）设置的。**guest 若运行 OpenGL 应用，会经过它们。** 其中"不改变 Metal 画什么"的 9 项可以直接接受任何值；`pointSmoothEnabled` 开启、`sampleCoverage != 1` 且采样数 > 4、`logicOperation` 的非 copy/no-op 操作在特定条件下、`fragmentDepthCompareClampMask != 0` 且通过 argument buffer sampler 比较、`vertexAmplificationMode >= 2`、amplification 时的 `explicitVisibilityGroupID` —— 这六类会被拒。`21-OBJC-OBJECT-FAMILY.md` 必须把这 19 个 SPI selector 实现出来（否则 `GLDriver` 调不到就可能崩），并把值原样转给上游。

### 12.3 `MTLComputePipelineDescriptor` → `ComputePipelineDescriptor`

`KNOWN`。构造器 `ComputePipelineDescriptor::new(kernel: StageSource)`。

| Metal 属性 | 上游字段 | 类型 | Metal 默认 | 进 key | 备注 |
|---|---|---|---|---|---|
| `computeFunction` | `kernel` | `StageSource` | 必填 | **是** | |
| `stageInputDescriptor` | `stage_input` | `Option<StageInputDescriptor>` | `None` | **是**（规范化后） | kernel 的 `[[stage_in]]` 怎么取。读 stage-in attribute 的 kernel 在它之下编译（`LoweringInputs::stage_input`） |
| `maxTotalThreadsPerThreadgroup` | `max_total_threads_per_threadgroup` | `Option<u32>` | `None` | **是** | **Metal 的 0（= 设备最大值）映射为 `None`** |
| `threadGroupSizeIsMultipleOfThreadExecutionWidth` | `threadgroup_size_is_multiple_of_execution_width` | `bool` | `false` | **是** | "guest 保证内部 region 的 local size 是 32 的倍数" |
| `supportIndirectCommandBuffers` | `support_indirect_command_buffers` | `bool` | `false` | **是** | |
| `maxCallStackDepth` | `max_call_stack_depth` | `u32` | `1` | **是**（0 与 1 规范化） | kernel 在它之下编译（`LoweringInputs::max_call_stack_depth`），它决定"通过 visible function 递归"的调用栈大小 |
| `requiredThreadsPerThreadgroup` | `required_threads_per_threadgroup` | `Option<[u32; 3]>` | `None` | **否** | **Metal 的零尺寸（无要求）映射为 `None`**。runtime 拒绝其他 threadgroup 大小的 dispatch，与 Metal 的 API validation 一致。**pipeline 不依赖它**（state 的 `maxTotalThreadsPerThreadgroup` 仍是 kernel 的，与 Metal 一致） |
| `supportAddingBinaryFunctions` | `support_adding_binary_functions` | `bool` | `false` | **否** | |
| `buffers[i].mutability` | `buffers` | `BTreeMap<u32, metal::Mutability>` | 未列出的是 `Default` | **否** | 同 12.1 的说明 |
| `needsCustomBorderColorSamplers`（**Apple SPI**） | `needs_custom_border_color_samplers` | `bool` | `false` | **否** | **不改变 Metal 跑什么**，同 render descriptor 的 |

### 12.4 `MTLTileRenderPipelineDescriptor` → `TileRenderPipelineDescriptor`

`KNOWN`。构造器 `TileRenderPipelineDescriptor::new(tile: StageSource)`。编译入口 `Device::compile_tile_pipeline`，产出 `ComputePipeline`。

| Metal 属性 | 上游字段 | 类型 | Metal 默认 | 进 key | 备注 |
|---|---|---|---|---|---|
| `tileFunction` | `tile` | `StageSource` | 必填 | **是** | |
| `colorAttachments[i].pixelFormat` | `color_attachment_formats` | `[Option<metal::PixelFormat>; 8]` | 全 `None` | **是** | render pass 的 color attachment 格式，按 color index，隐式 imageblock 装它们 |
| `rasterSampleCount` | `raster_sample_count` | `u32` | `1` | **是** | |
| `threadgroupSizeMatchesTileSize` | `threadgroup_size_matches_tile_size` | `bool` | `false` | **是**（只在有 `tile_attachments` 时） | **普通 Metal 在它为真时把 pass 的 tile 当作 tile 函数的 threadgroup**，不论某次 dispatch 跑的是每 tile 多少线程：它的每 threadgroup 线程数与 simdgroup 数、它在 grid 里的位置、每 grid 线程数，以及 `simdgroup · 32 + lane` 的 thread index。Metal 的 API validation 阻止"每 tile 线程数不等于 tile"的 dispatch。tile 函数在它之下编译（`LoweringInputs::threadgroup_size_matches_tile_size`），而 dispatch 仍跑它给的 threadgroup（`Dispatch::Threadgroups`），由 binder 对照"布局已实测的那些形状"检查 |
| `maxTotalThreadsPerThreadgroup` | `max_total_threads_per_threadgroup` | `Option<u32>` | `None` | **是** | Metal 的 0（pipeline 自己的最大值）映射为 `None`。它限制编译出的 pipeline 的 `metal_info.max_total_threads_per_threadgroup`，与 compute descriptor 的一样 |
| `maxCallStackDepth` | `max_call_stack_depth` | `u32` | `1` | **是** | |
| `requiredThreadsPerThreadgroup` | `required_threads_per_threadgroup` | `Option<[u32; 3]>` | `None` | **否** | |
| `supportAddingBinaryFunctions` | `support_adding_binary_functions` | `bool` | `false` | **否** | |
| `buffers[i].mutability` | `buffers` | `BTreeMap<u32, metal::Mutability>` | — | **否** | |

### 12.5 `MTLMeshRenderPipelineDescriptor` → `MeshPipelineDescriptor`

`KNOWN`。构造器 `MeshPipelineDescriptor::new(mesh: StageSource)`。编译入口 `Device::compile_mesh_pipeline`，产出 `RenderPipeline`。

| Metal 属性 | 上游字段 | 类型 | Metal 默认 | 备注 |
|---|---|---|---|---|
| `objectFunction` | `object` | `Option<StageSource>` | `None` | **带 object 函数的 mesh pipeline 的 plan 被拒**（`pipeline/mod.rs` 的 "Not implemented yet"） |
| `meshFunction` | `mesh` | `StageSource` | 必填 | |
| `fragmentFunction` | `fragment` | `Option<StageSource>` | `None` | 做光栅化的 pipeline 需要它 |
| `colorAttachments[i]` | `color_attachments` | `[Option<ColorAttachmentDescriptor>; 8]` | 全 `None` | |
| `depthAttachmentPixelFormat` | `depth_format` | `Option<metal::PixelFormat>` | `None` | |
| `stencilAttachmentPixelFormat` | `stencil_format` | `Option<metal::PixelFormat>` | `None` | |
| `rasterSampleCount` | `raster_sample_count` | `u32` | `1` | |
| `rasterizationEnabled` | `rasterization_enabled` | `bool` | `true` | |
| `alphaToCoverageEnabled` | `alpha_to_coverage` | `bool` | `false` | |
| `alphaToOneEnabled` | `alpha_to_one` | `bool` | `false` | |
| `supportIndirectCommandBuffers` | `support_indirect_command_buffers` | `bool` | `false` | **runtime 的事；编译忽略它** |
| `textureWriteRoundingMode`（Apple SPI） | `texture_write_rounding_mode` | `metal::TextureWriteRoundingMode` | `TowardZero` | 同 render pipeline |

**`METAL-COVERAGE.md` 记录的 mesh descriptor 缺口** `KNOWN`：`mesh pipeline descriptor fields`，size S，12 项 —— 包括 `maxTotalThreadsPerObjectThreadgroup`、`maxTotalThreadsPerMeshThreadgroup`、`objectThreadgroupSizeIsMultipleOfThreadExecutionWidth` 等。即上面这张表**不是** `MTLMeshRenderPipelineDescriptor` 的全部字段，还缺 12 个。

### 12.6 `MTLRenderPipelineColorAttachmentDescriptor` → `ColorAttachmentDescriptor`

`KNOWN`。构造器 `ColorAttachmentDescriptor::new(pixel_format)`。**只为 pixel format 不是 `Invalid` 的 attachment 构造。**

| Metal 属性 | 上游字段 | 类型 | Metal 默认 |
|---|---|---|---|
| `pixelFormat` | `pixel_format` | `metal::PixelFormat` | 必填 |
| `blendingEnabled` | `blending_enabled` | `bool` | `false` |
| `sourceRGBBlendFactor` | `source_rgb_blend_factor` | `metal::BlendFactor` | `One` |
| `destinationRGBBlendFactor` | `destination_rgb_blend_factor` | `metal::BlendFactor` | `Zero` |
| `rgbBlendOperation` | `rgb_blend_operation` | `metal::BlendOperation` | `Add` |
| `sourceAlphaBlendFactor` | `source_alpha_blend_factor` | `metal::BlendFactor` | `One` |
| `destinationAlphaBlendFactor` | `destination_alpha_blend_factor` | `metal::BlendFactor` | `Zero` |
| `alphaBlendOperation` | `alpha_blend_operation` | `metal::BlendOperation` | `Add` |
| `writeMask` | `write_mask` | `metal::ColorWriteMask` | `ALL` |

#### Metal 4 的三个 specialization 占位符

`KNOWN`（`ColorAttachmentDescriptor::specialized()` 的 doc comment）。**这是一个 macOS 26/27 才出现的行为，本项目必须实现。**

实测平台：Apple M3 Max，macOS 27.0.1，每种形状一次运行，通过一个 classic descriptor（其余五个 blend 字段设为 `One`、`One`、`Add`，使"回退到默认"的槽与"保留探针值"的槽读出不同结果）对一个已知的 destination 画一个三角形。结论：

| 占位符 | 原始值 | 在 **classic** `MTLRenderPipelineDescriptor` 下的 blend 行为 |
|---|---|---|
| `MTLBlendFactorUnspecialized` | **19** | 在 **source** 槽里按 `One` blend；在 **destination** 槽里按 `Zero` blend —— **各取该槽自己的默认值** |
| `MTLBlendOperationUnspecialized` | **5** | 按 `Add` —— 该槽自己的默认值 |
| `MTLColorWriteMaskUnspecialized` | — | **不在这里**：它是一个 mask 的一个位，而非一个槽的整个值；它自己的实测在 `metal::state::color_write_mask` |

三条必须照做的细节 `KNOWN`：

1. **setter 保留占位符**：descriptor 把 19 与 5 读回来。所以变的是"blend 拿它做什么"，不是"descriptor 装着什么"。
2. `newRenderPipelineStateWithDescriptor:error:` **返回一个 state 且无 error**，draw 存下那些默认值算出来的东西。
3. **占位符是被专门接受的**：再往上一个值就会让普通 Metal 的进程死在断言上（factor 20 报 `Invalid blend factor`，operation 6 报 `func is not a valid MTLBlendOperation`），**且没有打开任何 API validation 层**。

解析时机 `KNOWN`，上游给了理由：

> 解析发生在 blend 被**解释**的地方，**绝不在 descriptor 被构造的地方**，因为 Metal 自己的 getter 会把占位符答回来，而一个 binary archive 的 key 是原始字。

> **本项目含义**：
> - `MTLRenderPipelineColorAttachmentDescriptor` 的 getter 必须把 19/5 原样答回（不要规范化）。
> - 送进上游编译时调用 `ColorAttachmentDescriptor::specialized()`。
> - binary archive 的 key 用原始字。
> - `22-OBJC-DESCRIPTORS.md` 必须收录 `metal::BlendFactor::Unspecialized = 19`、`metal::BlendOperation::Unspecialized = 5`，以及"20 与 6 要断言"这条。

### 12.7 `MTLVertexDescriptor` → `VertexDescriptor`

`KNOWN`：

```
VertexDescriptor {
    layouts:    BTreeMap<u32, VertexBufferLayoutDescriptor>,   // 按 buffer index
    attributes: BTreeMap<u32, VertexAttributeDescriptor>,      // 按 attribute index
}
VertexBufferLayoutDescriptor { stride: Option<u32>, step_function: metal::VertexStepFunction, step_rate: u32 }
VertexAttributeDescriptor    { format: metal::VertexFormat, offset: u32, buffer_index: u32 }
```

- `stride` 为 `None` 对应 **`MTLBufferLayoutStrideDynamic`**（每次 bind 设置）。
- `VertexBufferLayoutDescriptor::new(stride)` 给出 per-vertex layout（`step_function = PerVertex`，`step_rate = 1`）。

#### `check_layouts()` —— Metal 的校验规则（必须照做）

`KNOWN`（`VertexDescriptor::check_layouts`）。上游明示 Metal 在 `newSerializedDescriptor` 处以断言停住 pipeline 创建，**无论是否打开 API validation**，针对两种情形，**按这个顺序**：

1. **先，按 attribute 顺序**：一个被设置的 attribute 的 buffer 没有 layout —— Metal 的消息是 `Attribute at index N references a buffer at index M that has no stride`。**不管 vertex 函数读不读它、声明为 unread、还是根本没声明。**
2. **然后，按 buffer 顺序**：一个 stride 非零或 dynamic 的 layout，没有任何被设置的 attribute 命名它的 buffer —— Metal 的消息是 `None of the attributes set bufferIndex to M, but MTLVertexDescriptor set buffer layout[M].stride(S)`，**不管它的 step 是什么**。**stride 为 0 的 layout 通过。**

上游返回 `Error::InvalidDescriptor(DescriptorError::VertexLayout { layout })`，`layout` 是第一个不一致的 buffer。

一条定义 `KNOWN`：**format 为 `Invalid` 的 attribute 是"未设置"的，不管它命名哪个 buffer。**

### 12.8 `MTLStageInputOutputDescriptor` → `StageInputDescriptor`

`KNOWN`：

```
StageInputDescriptor {
    layouts:            BTreeMap<u32, StageInputLayoutDescriptor>,    // 按 buffer index
    attributes:         BTreeMap<u32, StageInputAttributeDescriptor>, // 按 attribute index
    index_type:         metal::IndexType,
    index_buffer_index: u32,
}
```

默认（`StageInputDescriptor::new()`）`KNOWN`：无 layout 无 attribute，**16 位 index，来自 buffer 0**。

#### `check_layouts()`

`KNOWN`。先走 12.7 的两条规则（Metal 的断言对 kernel 的 attribute —— 读的、声明 unread 的、没声明的 —— 与它的 layout 是一样说法），给 `DescriptorError::StageInputLayout { layout }`。然后，**按 buffer 顺序**，对除 Metal 的 unset layout 之外的每个 layout，检查两件 Metal pipeline 创建会断言的事（同样不分是否打开 API validation）：

1. **vertex step function** → `DescriptorError::StageInputStepFunction { layout, step_function }`，Metal 消息 `invalid stepFunction value`；
2. **constant step 配非 0 step rate** → `DescriptorError::StageInputStepRate { layout, step_rate }`，Metal 消息 `stepRate(1) must be zero if stepFunction is MTLStepFunctionConstant`。

#### `canonical()` 与 `narrowed_to()`

`canonical()` `KNOWN` —— 见 9.3 的规范化表。要点：只保留被 attribute 命名的 layout；constant step 的 stride 写 `Some(0)`、step rate 写 0；index type 与 index buffer 保持默认，除非某个保留的 layout 步进 index buffer（`ThreadPositionInGridXIndexed`/`YIndexed`）。

`narrowed_to(read: &BTreeSet<u32>)` `KNOWN`（crate 私有，但其理由对消费方有意义）：**一个 kernel 一次取一个 attribute，只从那个 attribute 自己的 descriptor 条目取**（`StageInFetch::of`，由 `lower::stage_io::stage_in::param` 对每个被某条指令使用的 `[[stage_in]]` 参数调用），所以 `read` 没列出的 attribute 到不了模块的任何指令：**在这个窄化 descriptor 下的编译与在整个 descriptor 下的编译逐字相同**。

上游明确区分了三件事 `KNOWN`，本项目不要混：

- **fetch** 读的是窄化后的 descriptor；
- **layout 一致性检查**（`check_layouts`）读的是**给定的整个** descriptor；
- **reflection**（`ComputePipelineDescriptor::reflection`，它为每个被设置的 attribute 列一个 buffer，不管读不读）与 **compute pipeline key**（`compute_fields`）也读**给定的整个** descriptor。

`narrowed_to` **不是一个检查**：`read` 命名了而 descriptor 没有的 attribute 保持缺席，编译在 Metal 的 pipeline 创建会停住的地方拒绝它（`InvalidDescriptor(StageInputAttribute)`）。

### 12.9 `MTLTessellationPipelineDescriptor` 相关 → `TessellationDescriptor`

`KNOWN`（`descriptor.rs`）。Metal 把这些放在 `MTLRenderPipelineDescriptor` 上：

| Metal 属性 | 上游字段 | 类型 | Metal 默认 |
|---|---|---|---|
| `maxTessellationFactor` | `max_tessellation_factor` | `u32` | **16** |
| `tessellationPartitionMode` | `partition_mode` | `metal::TessellationPartitionMode` | **pow2** |
| `tessellationFactorFormat` | `factor_format` | `metal::TessellationFactorFormat` | **half** |
| `tessellationFactorStepFunction` | `factor_step_function` | `metal::TessellationFactorStepFunction` | **constant** |
| `tessellationOutputWindingOrder` | `output_winding_order` | `metal::Winding` | **clockwise** |
| `tessellationControlPointIndexType` | `control_point_index_type` | `metal::TessellationControlPointIndexType` | （源码未在同行注出；见 `metal::TessellationControlPointIndexType` 的 `Default`） |
| `tessellationFactorScaleEnabled` | `factor_scale_enabled` | `bool` | `false` |

进 key 的方式 `KNOWN`：`canonical_inputs` 把"等于 `TessellationDescriptor::default()`"的 tessellation 写成 `None`（Metal 的默认 tessellation state 就是没有 state）。

### 12.10 `MTLFunctionDescriptor` / `MTLLinkedFunctions` / 动态库

`KNOWN`：

```
FunctionDescriptor {
    function:  Function,                   // 库函数
    constants: FunctionConstantValues,     // 它被特化的常量值
    linked:    LinkedFunctions,            // 该 stage 链接的函数（MTLLinkedFunctions）
    libraries: DynamicLibraries,           // 该 stage 链接的动态库
}
```

构造器 `FunctionDescriptor::new(function)`（无常量值、无 linked function、无动态库），链式方法 `with_linked()`、`with_libraries()`、`with_loaded_dependencies(load)`。

`LinkedFunctions` ← `MTLLinkedFunctions` `KNOWN`：

| Metal 属性 | 上游字段 | 类型 | 含义 |
|---|---|---|---|
| `functions` | `functions` | `Vec<LinkedFunction>` | pipeline 通过引用或通过 function table 调用的 visible function（**每个都有一个 table handle**） |
| `privateFunctions` | `private_functions` | `Vec<LinkedFunction>` | 只通过引用调用的 |
| `binaryFunctions` | `binary_functions` | `Vec<LinkedFunction>` | 编译成二进制的 visible function。**translator 像链接 `functions` 一样链接它们的 AIR，table 也能装它们** |
| `groups` | `groups` | `BTreeMap<String, Vec<LinkedFunction>>` | 按 call-site group 名，一个通过函数指针的调用可能调到哪些函数 |

**每个字段都进 compile key** `KNOWN`。

解析规则 `KNOWN`：编译按 `FunctionInfo::name` 把每个 visible-function reference 对照 `functions`、`private_functions`、`binary_functions` 解析：被命名的那个函数（它模块的一个 visible function，在 bitcode 库里是 `FunctionStage::Visible`）**被静态链接并内联**，它接着引用的那些也一样。没有任何东西命名的 reference 是 `Error::NeedsInput(LinkedFunction)`，**仅当对它的调用在特化之后还存活**。通过 table 的调用编译成"对该调用类型的那些 handle 的一次 switch"。`groups` 命名"一个通过函数指针的 call site 可能调到哪些函数"；**decoder 丢弃 call site 的 `!air.function_groups`，所以没有输出依赖它**。

`LinkedFunction { function, constants, precompiled }` `KNOWN`：`precompiled` 对应 `MTLFunctionOptionCompileToBinary`（Metal 对 `binary_functions` 里的函数、以及加到已造 pipeline state 上的 binary function 要求它）；runtime 会检查它，像 Metal 那样拒绝不符的。**translation 两种情况都链接它的 AIR，所以它不进任何 key。**

`DynamicLibraries` `KNOWN`：

| Metal 属性 | 上游字段 | 含义 |
|---|---|---|
| `preloadedLibraries`（render stage 的 `vertexPreloadedLibraries` / `fragmentPreloadedLibraries`） | `preloaded: Vec<DynamicLibrary>` | **先搜，按顺序** |
| （按 install name 加载的） | `loaded: BTreeMap<String, DynamicLibrary>` | 按 install name 的、从它命名的文件加载的库，如 Metal 加载它那样：**在 `preloaded` 之后搜**，按 install name 到达的顺序。**一个 install name 上的文件可以装着另一个 install name 的库；Metal 照样用它** |

搜索顺序 `KNOWN`（上游注明是在探针、M3 Max、M4 上实测的 Metal 在 pipeline creation 时的解析方式）：**一次搜索，按顺序** —— 先 `preloaded`，然后 `loaded` 为"该 stage 的库所命名的 install name"持有的那些库，**广度优先**（它自己的依赖按链接顺序，然后它们的；然后它的 linked function 的库的，然后 preloaded 库的 —— 最后这个顺序**未实测**）。**第一个导出该符号的库供给它，且它的定义被静态链接并内联**；一个库对它自己定义的函数的调用仍然是它自己的。

错误 `KNOWN`：没有库导出的 import 是 `Error::NeedsInput(DynamicSymbol)`；如果某个 install name 在 `loaded` 里缺失（Metal 加载不了的文件），**每一个** import 都是 `Error::NeedsInput(DynamicLibrary)`，**即使某个 preloaded 库导出了它** —— 因为 Metal 会让那种创建失败。两者都**只在某个 import 的使用在特化之后还存活时**发生。

**搜索到达的每一个库都是 compile key 的一部分** `KNOWN`（install name + 内容 hash；以及没加载成功的那个 install name）。

辅助方法 `FunctionDescriptor::with_loaded_dependencies(load)` `KNOWN`：为该 stage 的搜索到达的、而它还缺的每个 install name 在 `libraries.loaded` 里放一个库，如 Metal 在 pipeline creation 时加载它们那样。`load(install_name) -> Option<DynamicLibrary>`。install name 按 `DynamicLibraries` 搜索它们的顺序到来（一个已加载库自己的依赖排在已经到达的那些之后），**加载在第一个 `load` 返回 `None` 的地方停止**：之后编译会拒绝任何在特化后还存活的 import（`NeedsInput(DynamicLibrary)`），**与 Metal 让那种创建失败、而把别的造出来一致**。`loaded` 里已有的库原样使用。

### 12.11 `StageSource`

`KNOWN`：

```
StageSource = Function(FunctionDescriptor)   // 要编译的函数
            | Compiled(CompiledFunction)     // 调用方已经编译好的函数（只 link + relocate；不 decode、不 lowering）
```

`Compiled` 这条路径是本项目做 shader cache 的关键：按 `FunctionCompileKey` 缓存 `CompiledFunction`，命中时走 `StageSource::Compiled`，pipeline **不再 decode、不再 lowering**。

### 12.12 本项目在映射层要补的东西

`INFERRED`（本文的推论，归 `22-OBJC-DESCRIPTORS.md` 落实）：

1. **`MTLPixelFormatInvalid` → `None`** 的转换要在三处做：`color_attachments[i]`、`depth_format`、`stencil_format`、`color_attachment_formats[i]`。
2. **Metal 的"0 表示默认/无"约定**要逐字段处理：`maxTotalThreadsPerThreadgroup` 0 → `None`；`requiredThreadsPerThreadgroup` 零尺寸 → `None`；`maxCallStackDepth` 0 → 规范化为 1；`MTLBufferLayoutStrideDynamic` → `stride: None`。
3. **`maxVertexAmplificationCount == 0` 是非法 descriptor**，要在胶水层拦。
4. **原始 `u32` 序数走 `metal::` 的 `TryFrom<u32>`**，它会拒绝未知值 —— 这正是本项目需要的行为（guest 传了未来的枚举值时给出类型化拒绝，而不是静默误解）。
5. **Metal 4 的三个 specialization 占位符**（12.6）：getter 原样答回，编译前调 `specialized()`。
6. **19 个 `PrivateRenderState` SPI selector**（12.2）必须实现，否则 OpenGL on Metal 调不到。
7. **mesh descriptor 还缺 12 个字段**（12.5），本项目要么不发布 mesh 支持，要么向上游补。

---

## 13. 待查清单

| # | 事项 | 为什么重要 | 查清方法 |
|---|---|---|---|
| 1 | `RuntimeFact` 在 `UniformViewRange` 之后的全部 variant | `dependencies` 的处理必须覆盖全部 fact，漏一个就会漏一项 bind-time 状态 | 读 `crates/metal2vulkan/src/pipeline/facts.rs` 第 120 行之后 |
| 2 | `WriteSource` 在 `Imageblock` 之后的全部 variant | descriptor 写入必须覆盖全部来源 | 读 `crates/metal2vulkan/src/bind/plan.rs` 第 700 行到 `PushTemplate` 之前 |
| 3 | `Mechanism` 的 15 个 variant 各自的精确含义 | 本文的解释是 `INFERRED`（上游未逐个加 doc comment），消费规则需要确证 | 读 `device::mechanism(fact, profile)` 的实现（`crates/metal2vulkan/src/device/mechanism.rs`，17 KB），看每个 (fact, profile) 产出哪个 mechanism |
| 4 | `BindShape` 的完整字段集 | 它决定 plan 的 memo key，必须完整构造 | 读 `crates/metal2vulkan/src/bind/state.rs` 第 1546 行起的 `pub struct BindShape` |
| 5 | `DispatchCommands` / `DrawCommands` 的完整字段集 | 这是消费方真正要记录的东西 | 读 `bind/dispatch.rs` 第 149/197 行、`bind/graphics.rs` 第 440 行 |
| 6 | `GraphicsState` 是否还有本文未列的字段 | 固定功能状态要完整落到 `VkGraphicsPipelineCreateInfo` | 读 `crates/metal2vulkan/src/pipeline/graphics.rs` 的 `pub struct GraphicsState` 全文 |
| 7 | `Requirements` 自身的字段结构（不只是 `VkFeature` 等词表） | 要知道怎么遍历它得到"要启用什么" | 读 `crates/metal2vulkan/src/device/requirements.rs` 的 `pub struct Requirements` |
| 8 | `metal::TessellationControlPointIndexType` 的 Metal 默认值 | 12.9 表里这一格缺 | 读 `crates/metal2vulkan/src/metal/mod.rs` 或 `metal/generated.rs` 的该枚举的 `Default` impl |
| 9 | Lavapipe 的 `maxPushDescriptors` | 决定 `push_descriptor_eligible` 的常见取值，影响 descriptor 分配策略 | `vulkaninfo`，或 `DeviceDescription::query` 导出 profile |
| 10 | Lavapipe 是否支持 `bufferDeviceAddress` | 决定 `BufferForm::Psb`、dynamic root、`ArgumentBufferPointers`、`GpuEncodedIndirectCommands` 是否可用 —— 这是本项目 argument buffer 能走多远的分水岭 | 同上 |
| 11 | Lavapipe 是否支持 `uniformBufferStandardLayout` | 决定 `DescriptorView::UniformWords` 是否可用（否则只能 `UniformVec4`，std140 对齐，会浪费空间） | 同上 |
| 12 | `metal2vulkan-runtime` 实现了哪些 Metal 对象，本项目还要补哪些 | 本分册只覆盖 translator 的 artifact 契约；runtime 的覆盖面是 `40-RUNTIME-VULKAN.md` 的题 | 读 `crates/metal2vulkan-runtime/README.md` 与 `docs/RUNTIME-PORTING.md`（57 KB，"你把 Metal 调用（Objective-C 或 metal-rs）移植到 runtime 时读"） |
| 13 | `ArgumentBufferLayout::from_descriptors` 的精确语义与 `ARGUMENT_HANDLE_BYTES` 的值 | 本项目的 `MTLArgumentEncoder` 要靠它 | 读 `crates/metal2vulkan/src/bind/argument_buffer.rs`（40 KB） |
| 14 | `ExecutionStatus::decode()` 返回什么、怎么映射成 guest 可见的东西 | resident-set miss 与 clamp 掉的 indirect count 是真实的行为差异，不能静默丢 | 读 `crates/metal2vulkan/src/bind/status.rs`（24 KB） |

---

## 14. 与其他分册的接口

| 本分册给出 | 消费方 |
|---|---|
| artifact 全量字段与消费规则（第 1–8 节） | `40-RUNTIME-VULKAN.md`（怎么把它变成 Vulkan 对象）、`50-IPC-HELPER.md`（哪些字段要过 IPC 边界） |
| cache key 构成与失效条件（第 9 节） | `70-BUILD-PACKAGE.md`（shader cache 的磁盘布局）、`80-TEST-HARNESS.md`（content digest 作为回归断言） |
| `BindingPlan` 两级模型与下发规则（第 10 节） | `40-RUNTIME-VULKAN.md`、`21-OBJC-OBJECT-FAMILY.md`（encoder 的 selector 怎么填 `BindState`） |
| 必须做 / 禁止做（第 11 节） | 全部实现分册；也是 `IMPLEMENTATION_ROADMAP` 的接入验收条件 |
| Metal descriptor 全量字段映射（第 12 节） | `22-OBJC-DESCRIPTORS.md`（descriptor 类的字段、默认值、校验与 snapshot 规则直接照它写） |
| 12.2 的 19 个 Apple SPI 属性 | `21-OBJC-OBJECT-FAMILY.md`（必须实现这些 selector） |
| 12.6 的 Metal 4 占位符 | `22-OBJC-DESCRIPTORS.md`（getter 原样答回；`metal::BlendFactor::Unspecialized = 19`、`BlendOperation::Unspecialized = 5`） |
| 待查清单（第 13 节） | `90-EVIDENCE-INDEX.md` |
