# 30 — Shader 边界：AIR/metallib 格式与 metal2vulkan 覆盖率

文档版本：1.0
基线日期：2026-10-30
归属：`docs/spec/00-OVERVIEW.md` 第 8 节分册 `30`
配套分册：`31-PIPELINE-ARTIFACT.md`（消费契约）、`60-CAPABILITY-MATRIX.md`（能力矩阵）

## 0. 上游快照

本文全部上游证据取自一次浅克隆，克隆位置在仓库外（`$env:TEMP\m2v-air-audit`），不进入本仓库。

| 项 | 值 | 标签 |
|---|---|---|
| 仓库 | `https://github.com/steelbrain/metal2vulkan` | `KNOWN` |
| commit SHA | `219f01365dc4c8eb346816c405b5b17403793764` | `KNOWN` |
| commit 日期 | `2026-10-29T17:10:41+02:00` | `KNOWN` |
| commit 标题 | `Re-pin the runtime sources at the landing tip` | `KNOWN` |
| 分支 | `master`（无 tag） | `KNOWN` |
| crate 版本 | `0.2.0`，`CHANGELOG.md` 标 unreleased；crates.io 上的 `0.1.0` 是无关的早期设计 | `KNOWN` |
| 许可证 | `GPL-2.0-or-later OR LGPL-3.0-or-later`（`LICENSE`、`Cargo.toml` `workspace.package.license`） | `KNOWN` |
| 工具链 | `rust-toolchain.toml` channel `1.98.1`；`workspace.package.rust-version = "1.98"` | `KNOWN` |
| 输出目标 | SPIR-V 1.5，Vulkan 1.2 下限（`docs/ARCHITECTURE.md`；`Feature::VulkanVersion` 拒绝低于 1.2 的设备） | `KNOWN` |

本机 cargo 为 1.99.1，高于上游 pin 的 1.98.1。**未执行**上游构建或 `cargo doc`：按任务约定不在构建上花时间，且 `rust-toolchain.toml` 会驱动 rustup 下载 1.98.1 工具链。本文结论全部来自源码阅读，未依赖编译结果。

本文件内凡引用上游路径，均相对该 commit 的仓库根；凡引用符号，均给出文件与符号名。

### 0.1 证据标签用法

- `KNOWN`：上游源码或生成文档直接写明，给出文件路径与符号名。
- `INFERRED`：由上游源码的结构可以合理推出，但上游未明文陈述。
- `BLOCKED`：缺少必要样本或运行证据；写明缺什么、如何取得。
- 架构标注：本分册的全部内容与 CPU 架构无关（AIR 是 GPU IR，metallib 容器是与宿主架构无关的格式）。唯一的架构相关项是 universal metallib 的 CPU type 字段，见 1.2。

---

## 1. metallib 容器格式

来源：`crates/metal2vulkan-air/src/container/mod.rs`、`container/mtlb.rs`、`container/tags.rs`。
入口符号：`air::container::parse`。

### 1.1 四种接受的输入形式

`container::parse` 只看头四个字节，不扫描文件寻找 magic。`KNOWN`（`container/mod.rs`，常量 `MTLB_MAGIC`/`UNIVERSAL_MAGIC`/`WRAPPER_MAGIC`/`BITCODE_MAGIC`）。

| 头 4 字节 | 形式 | 结果 |
|---|---|---|
| `4D 54 4C 42`（`MTLB`） | Metal library，每个函数一个 bitcode 模块 | `Library::Metallib` |
| `CB FE BA BE` | universal metallib（big-endian magic） | 取其 AIR slice 再按 `MTLB` 解析 |
| `DE C0 17 0B` | bitcode wrapper（`0x0b17c0de`，一个 `.air` 文件） | `Library::Module` |
| `42 43 C0 DE`（`BC C0DE`） | 裸 LLVM bitcode 流 | `Library::Module` |

其他任何头是 `ContainerError::BadMagic`；不足 4 字节是 `ContainerError::Truncated`。

### 1.2 universal metallib

`KNOWN`（`container/mod.rs`，`air_slice`，常量 `AIR_SLICE_CPU_TYPE = 0x0100_0017`、`UNIVERSAL_HEADER_LEN = 8`、`UNIVERSAL_SLICE_LEN = 20`）。上游注明这是 `MTLDynamicLibrary` 的 `serializeToURL:error:` 写出的形式，并说明证据来自 M3 Max 与 M4 上的实测探针。

布局，全部 big-endian：

```
offset 0   u32  magic = 0xCBFEBABE
offset 4   u32  slice_count
offset 8   每片 20 字节：u32 cputype, u32 cpusubtype, u32 offset, u32 size, u32 align
```

`cputype == 0x01000017` 的那一片是库的 AIR，内容本身是一个 `MTLB` 文件；其余片是为某个具体 GPU 编译的代码，上游不读。没有 AIR slice 是 `ContainerError::NoAirSlice`（上游注明 Metal 自己也拒绝，报 "its AIR slice is missing"）。

> 本项目含义：x86_64 guest 上 Metal 客户端提交的 metallib 是否带 GPU slice，取决于它是如何生成的。`newLibraryWithData:` 路径通常是纯 `MTLB`。**未查**：25G325 x86_64 上 `MTLDynamicLibrary` 序列化产物是否也用 `0xCBFEBABE`。查清方法：在目标 guest 上调用 `serializeToURL:` 并看前 4 字节。

### 1.3 bitcode wrapper 头

`KNOWN`（`container/mod.rs`，`bitcode_stream`、`WrapperHeader`，常量 `WRAPPER_HEADER_LEN = 20`）。20 字节，little-endian：

```
offset 0   u32  magic = 0x0B17C0DE
offset 4   u32  version        （只记录，不解释）
offset 8   u32  offset         （bitcode 流相对文件起点的字节偏移）
offset 12  u32  size           （bitcode 流字节数）
offset 16  u32  cputype        （只记录，不解释）
```

校验：`offset >= 20`，`offset + size <= 文件长度`，且 `stream[0..4] == "BC\xC0\xDE"`。metallib 里每个函数的 bitcode 都是**带这个 wrapper 的**（见 1.5）。

### 1.4 MTLB 头（0x58 = 88 字节）

`KNOWN`（`container/mtlb.rs`，`parse`、`MtlbHeader`、`Fields`，常量 `HEADER_LEN = 0x58`）。全部 little-endian，紧凑排列。上游注明字段布局是在 Apple 产出的 2.7–2.9 格式上观察到的。

| 偏移 | 宽度 | 字段 | 说明 |
|---|---|---|---|
| 0x00 | 4 B | magic | `MTLB` |
| 0x04 | u16 | `platform` | 只记录 |
| 0x06 | u16 | `version_major` | **只接受 1 或 2**（`SUPPORTED_MAJOR`），其他是 `UnsupportedContainerVersion` |
| 0x08 | u16 | `version_minor` | 只记录 |
| 0x0A | u8 | `file_type` | 0 = executable library，2 = dynamic library（`MTLLibraryTypeDynamic`）。其他值是 `Unsupported(Feature::LibraryKind(n))` |
| 0x0B | u8 | `os` | 只记录 |
| 0x0C | u16 | `os_version_major` | 只记录 |
| 0x0E | u16 | `os_version_minor` | 只记录 |
| 0x10 | u64 | `file_size` | 必须 ≤ 实际字节数；解析只看 `[..file_size]` |
| 0x18 | u64 | function_list offset | |
| 0x20 | u64 | function_list size | |
| 0x28 | u64 | public_metadata offset | |
| 0x30 | u64 | public_metadata size | |
| 0x38 | u64 | private_metadata offset | |
| 0x40 | u64 | private_metadata size | |
| 0x48 | u64 | bitcode offset | |
| 0x50 | u64 | bitcode size | |

四个 section 都必须满足 `offset >= 0x58` 且 `offset + size <= file_size`。

### 1.5 函数表

`KNOWN`（`container/mtlb.rs`，`parse`、`function`，常量 `MIN_ENTRY_LEN = 8`）。

```
function_list.offset:        u32 count
function_list.offset + 4:    count 个条目，每条：
                               u32 entry_size   （含自身 4 字节，最小 8）
                               TLV 标签表，以 ENDT 结束，长度正好填满 entry_size
最后一条之后:                 扩展头的 TLV 标签表
```

`function_list.size` 是**各条目 size 之和**（不含那个 `u32 count`）：上游要求 `entries_end == function_list.offset + 4 + function_list.size`，且最后一条正好落在那里。扩展头紧跟在后面。

每个函数条目的 `OFFT` 给出三个相对各自 section 基址的偏移：public metadata、private metadata、bitcode。每条 metadata 记录是 `u32 size` 加一段恰好那么长的标签表。bitcode 是 `MDSZ` 字节的**带 wrapper 的** bitcode，`HASH` 是它的 SHA-256。

**不相交约束** `KNOWN`：任意两个函数不得共享或重叠 public metadata 记录、private metadata 记录或 bitcode 区间。上游说明理由是保持解析与解析结果对文件大小线性。唯一例外是 dynamic library（`file_type == 2`）：Apple 工具链把库导出的每个函数都列出来（`TYPE` 3，`NAME` 是符号名），它们共享库那唯一一个模块，于是可以**完全相同**地共享一段 bitcode 区间，只哈希一次。违反是 `ContainerError::BadOffset`，哈希不符是 `ContainerError::HashMismatch`。

### 1.6 TLV 标签格式

`KNOWN`（`container/tags.rs`，`read_list`、`TagReader`）。

```
fourcc : 4 字节 ASCII
length : u16 little-endian（不含 fourcc 与自身）
bytes  : length 字节
```

终结符 `ENDT` **没有** length 字段。字符串是 NUL 结尾的 UTF-8（`TagReader::cstr`）。已知标签必须被字节级完全消费（`TagReader::finish`），多余字节是 `BadTag`；重复的一次性标签是 `DuplicateTag`。未知 fourcc 原样保留为 `RawTag`，**不参与任何翻译决策**（上游明确：翻译语义只来自 bitcode 与 AIR metadata，绝不来自容器标签）。

### 1.7 已知标签清单

#### 函数表条目（`container/mtlb.rs::function`）`KNOWN`

| fourcc | 载荷 | 含义 |
|---|---|---|
| `NAME` | cstr | 函数名；`newFunctionWithName:` 按它选函数 |
| `TYPE` | u8 | stage，见 1.8 |
| `HASH` | 32 B | 该函数 bitcode 的 SHA-256，解析时强制校验 |
| `MDSZ` | u64 | bitcode 字节数 |
| `OFFT` | u64 ×3 | (public_md_off, private_md_off, bitcode_off)，各自相对 section 基址 |
| `VERS` | u16 ×4 | (air_major, air_minor, language_major, language_minor) |

以上六个是**必需**的（缺任一是 `MissingTag`）。上游明确保留但不解释的函数表标签：`LAYR`、`TESS`、`RFLT`（`LibraryFunction::raw_tags` 的文档注释列举）。`INFERRED`：这些分别大概是 layered rendering、tessellation、reflection 相关，但上游没解析，本项目也不应依赖。

#### public metadata（`container/mtlb.rs::public_metadata`）`KNOWN`

| fourcc | 载荷 | 含义 |
|---|---|---|
| `CNST` | `u16 n`，然后 n 条 `cstr name, u8 data_type, u16 index, u8 flags` | 函数常量。`data_type` 是原始 `MTLDataType`；`index` 是 `[[function_constant(n)]]`；`flags` 只记录不解释 |
| `VATT` | `u16 n`，然后 n 条 `cstr name, u16 packed` | vertex attribute。`packed` 含 index 与 flag，由 ABI 交叉校验解码 |
| `VATY` | `u16 n`，然后 n 个 `u8` | vertex attribute 的 `MTLDataType`，原始值 |

上游明确保留但不解释的 public metadata 标签：`ARGR`、`RETR`。

#### private metadata `KNOWN`

全部原样保留（`LibraryFunction::private`）。上游注明"no content observed"：没有观察到内容。`BLOCKED` 对本项目而言不构成阻断，因为上游不读它，本项目也不需要读。

#### 扩展头（`container/mtlb.rs::linkage`）`KNOWN`

| fourcc | 载荷 | 含义 |
|---|---|---|
| `HDYN` | `u64 offset, u64 size` | 指向文件内一段标签表：`NAME` = 库的 install name（dynamic library 的 `installName`，executable 的文件名），`DYNL` ×N = 它链接过的各 dynamic library 的 install name，按链接顺序 |
| `ILST` | `u64 offset, u64 size` | 指向文件内一段：`u32 count`，然后 count 条记录，每条 `u32 size`（含自身）+ 标签表，其中 `NAME` 是它从那些库导入的一个符号名 |

上游注明 `HDYN`/`ILST` 是在 Apple 的 2.9 格式产出中观察到的（探针 + M3 Max + M4）。

### 1.8 `TYPE` 值语义

`KNOWN`（`container/mod.rs`，`FunctionStage::from_type_tag`）。上游给出的证据来源是
`validation/fixtures/public/reflection/metallib-tags.txt`，并标明每个值 Metal 回答的 `MTLFunctionType`。

| `TYPE` | `FunctionStage` | 含义 |
|---|---|---|
| 0 | `Vertex` | vertex 函数 |
| 1 | `Fragment` | fragment 函数 |
| 2 | `Kernel` | kernel，**tile 函数也是 2** |
| 3 | `Exported` | dynamic library 导出的符号。**不是 stage**：上游实测 `newFunctionWithName:` 对它直接断言失败，即使源码里写的是 `kernel` |
| 4 | `Visible` | `[[visible]]` 函数（`!air.visible`），供 `MTLLinkedFunctions` 链接，不是 stage |
| 5 | — | 未观察到，落入 `Other(5)` |
| 6 | `Intersection` | `[[intersection(...)]]` 函数，intersection function table 的成员，不是 stage |
| 7 | `Mesh` | mesh 函数 |
| 8 | `Object` | object 函数 |
| 其他 | `Other(u8)` | 原样保留 |

**AIR metadata 才是权威**：容器 `TYPE` 只做交叉校验（`AirAbi::check_container`）。不一致是 `AbiError::ContainerMismatch`。

### 1.9 metadata 记录的两种 size 约定

`KNOWN`（`container/mtlb.rs::metadata`）。Apple 产出里存在两种，上游都精确接受：

- 标签表长度本身 —— `metallib` 链接 `.air` 文件时写出的；
- 标签表长度 + 4（即把那个 `u32 size` 字自己算进去）—— `metal` 直接编译成 metallib 时写出的。

任何其他值是 `BadTag`。**实现方必须同时接受这两种**，否则会在某条工具链上解析失败。

### 1.10 照着解析一个真实 metallib 的步骤

1. 读头 4 字节分流（1.1）。`0xCBFEBABE` 先取 AIR slice（1.2）。
2. 读 0x58 字节头，校验 `version_major ∈ {1,2}`、`file_type ∈ {0,2}`、`file_size <= len`、四个 section 范围（1.4）。
3. 读 `function_list`：`u32 count`，逐条读 `u32 entry_size` + TLV（1.5、1.6）。校验条目总长与 `function_list.size` 一致。
4. 对每条解出 `NAME/TYPE/HASH/MDSZ/OFFT/VERS`，算出 bitcode 绝对区间 `bitcode.offset + OFFT[2] .. + MDSZ`。
5. 读最后一条之后的扩展头 TLV，解 `HDYN`/`ILST`（1.7）。
6. 若 `file_type == 2`，整个 bitcode section 就是那一个共享模块。
7. 排序全部 bitcode 区间，校验不相交（dynamic library 允许完全相同）；逐段 SHA-256 与 `HASH` 比对。
8. 排序 public/private metadata 偏移，校验不相交，逐条按 1.9 的双 size 约定解析。
9. 每个函数的 bitcode 是**带 wrapper 的**：再按 1.3 剥一层得到 `BC C0DE` 流。
10. 把流交给 bitcode 解码器（第 2 节）。

---

## 2. AIR 的 bitcode 方言

来源：`crates/metal2vulkan-air/src/bitstream/`、`bitcode/`、`ir/`。

### 2.1 bitstream 层：标准 LLVM，无差异

`KNOWN`（`bitstream/mod.rs` 模块文档）。上游明确这一层"LLVM-agnostic"：32 位字、fixed 与 VBR 字段、`ENTER_SUBBLOCK`/`END_BLOCK`、`DEFINE_ABBREV`（literal、fixed、VBR、array、char6、blob）、`UNABBREV_RECORD`、`BLOCKINFO`（`SETBID` 与 abbrev；block/record 名字被忽略）。

关键常量：`BLOCKINFO_BLOCK_ID = 0`，`TOP_LEVEL_ABBREV_WIDTH = 2`，abbrev id 0..3 保留给 `END_BLOCK`/`ENTER_SUBBLOCK`/`DEFINE_ABBREV`/`UNABBREV_RECORD`，应用 abbrev 从 4 起，`MAX_ABBREV_WIDTH = 32`。流长度必须是 4 字节倍数。

**结论：AIR 在 bitstream 层与标准 LLVM bitcode 完全相同。** 可以用任何标准 bitstream 读取器读骨架。

### 2.2 bitcode 层：module version **必须**是 2

`KNOWN`（`bitcode/module.rs`，`MODULE_VERSION_2 = 2`，`decode`）。模块块必须以 `VERSION` 记录开头，值必须是 2，否则 `BitcodeError::UnsupportedBitcodeVersion`。module version 2 的含义是：相对 value id 编号，且全局与函数名放在模块之后的 `STRTAB` 块里。

**结论：AIR 不是独立方言，是 LLVM module-version-2 bitcode 的一个子集。** 差异只有三处，全部是"子集"而非"扩展"：

1. **封闭指令集**（2.3）：AIR 只用 LLVM 指令的一个子集；LLVM 定义而模型未覆盖的记录码是 `Unsupported`，LLVM 未定义的是 `UnknownRecord`/`UnknownBlock`，操作数不匹配是 `MalformedRecord`。
2. **封闭 calling convention**：非 AIR 的 calling convention 是 `Feature::CallingConvention`（`bitcode/function.rs::call`、`bitcode/module.rs::function`）。
3. **语义全在 metadata 与 `air.*` intrinsic 里**（第 4、5 节）。

模块级 LLVM 构造 alias、ifunc、comdat 等是 `Feature::ModuleRecord`（上游 reach 标注 "LLVM constructs AIR does not emit"）。

### 2.3 封闭指令集：26 个 opcode

`KNOWN`（`ir/inst.rs`，`enum Opcode`）：

```
BinOp  FNeg  Cast  ICmp  FCmp  Select  Freeze
ExtractElement  InsertElement  ShuffleVector  ExtractValue  InsertValue
Alloca  Load  Store  Gep  AtomicRmw  CmpXchg  Fence
Call  Phi
Ret  Br  CondBr  Switch  Unreachable
```

没有 `invoke`/`landingpad`/`resume`/`catchswitch`/`va_arg`/`indirectbr`/`callbr`/`atomicrmw` 之外的异常与变长参数构造。每条指令携带自己的结果类型；浮点运算保留 fast-math flag（精度契约由 lowering 负责）。metadata attachment 只保留两类：terminator 上的 `LoopHints`，load/call 上的 `RangeMd`；其余在 decode 时丢弃。

### 2.4 类型模型与 pointer 擦除

`KNOWN`（`ir/types.rs`，`enum Type`）：

```
Void  Label  Metadata
Int(1..=64)   Half  BFloat  Float  Double
Vector{elem, len>=1}   Array{elem, len}
Struct{fields, packed, name}   OpaqueStruct{name}
Ptr{space}            Function{ret, params, vararg}
```

要点：

- 整数宽度 1..64；上游注明语料里确实存在 `i2`、`i40` 这类宽度，支持与否由 lowering 决定。
- `bfloat` 在类型模型里（`Type::BFloat`，16 位，8 指数 7 尾数）。
- **指针的 pointee 在 decode 时被擦除**，只留 address space。typed-pointer 形式的旧 bitcode 的 pointee 保存在 decode-only 的 `PointeeTable` 里，只用于 decode 期的 ABI 交叉校验，之后无人读。擦除使类型图无环，于是 interner 可以要求"子类型 id 必然小于父类型 id"，布局与打印都能一趟前向扫描完成。
- `vararg` 可表示但在使用处被拒。
- 结构体 `name` 只用于诊断并保持 identified struct 的 nominal 性，**任何决策都不得按名字分支**（上游 `ARCHITECTURE.md` 的 "Structure, not names" 规则）。
- 资源句柄的身份来自 metadata ABI，**绝不来自** `OpaqueStruct` 的名字。

### 2.5 address space 编号

`KNOWN`（`ir/types.rs`，`enum AddrSpace`、`AddrSpace::from_raw`）：

| LLVM 编号 | `AddrSpace` | Metal 地址空间 |
|---|---|---|
| 0 | `Thread` | `thread`：线程私有内存（局部变量与栈） |
| 1 | `Device` | `device`：可读写的 buffer 内存，所有线程可达 |
| 2 | `Constant` | `constant`：只读 buffer 内存，所有线程可达 |
| 3 | `Threadgroup` | `threadgroup`：一个 threadgroup 内共享 |
| 4 | `ThreadgroupImageblock` | `threadgroup_imageblock`：tile 的 imageblock，threadgroup 内存的一个区域 |
| **5** | — | **未定义**，`Unsupported(Feature::AddressSpace(5))` |
| 6 | `ObjectData` | `object_data`：object 函数的 payload（`[[payload]]`），它启动的 mesh 函数读 |
| 7 | `MeshOutput` | mesh 函数的输出句柄（`metal::mesh<..>`，一个 opaque struct） |

其他编号是 `Feature::AddressSpace(n)`。上游 `REFUSALS.md` 对这一项的 reach 标注是 `none: Apple's AGX library address spaces` —— 即只有 Apple 自己的 AGX 库会用到未定义的编号。

> **本项目含义**：5 号空洞是真实的。若 guest 的 Metal.framework 或系统库（CoreImage、SkyLight 的内建 shader）带有使用 5 号空间的 metallib，整条链会拒绝。**未查**：25G325 x86_64 的系统 metallib 是否出现 addrspace(5)。查清方法：把 `/System/Library/**/*.metallib` 全量过一遍 `metal2vulkan-air::decode`，统计 `Feature::AddressSpace` 拒绝。

### 2.6 DataLayout 与结构体布局/对齐规则

`KNOWN`（`ir/layout.rs`，`DataLayout::parse`、`TypeLayouts`）。上游把模块的 `target datalayout` 字符串解析成类型化规则；**未知 specifier 是错误**（`BitcodeError::BadDataLayout`），不是忽略。

`TypeLayouts` 对 `TypeTable` 的每个类型做一趟前向扫描（子先于父，无递归），回答 `alloc_size`、`store_size`、`abi_align` 与 struct 字段偏移。规则是 LLVM 的：

1. 没有精确条目的整数宽度，取**下一个更大**的条目；没有更大的就取最大的那个。
2. 没有条目的 vector，自然对齐到其 store size 向上取到 2 的幂。
3. struct 对齐到"字段对齐的最大值"与 aggregate（`a`）条目二者之中较大者，除非是 packed（`<{ }>`：字段间无填充，对齐 1）。

**关键后果** `KNOWN`（`ir/layout.rs` 模块文档明示）：AIR 的 `v96:128:128` 使 `float3` 占 **16** 字节，不是 12。这是实现方最容易踩的坑。

`DataLayout` 的完整字段集（`ir/layout.rs`）：`endian`（`e`/`E`）、`pointers`（按 address space，空间 0 是没有条目的空间的回退）、`ints`、`floats`（`f`）、`vectors`（`v`，按 vector 总位宽）、`aggregate`（`a`；ABI 对齐 0 表示 1 字节）、`native_ints`（`n`）、`stack_align_bits`（`S`）、`alloca_space`（`A`）、`program_space`（`P`）、`globals_space`（`G`）、`mangling`（`m:`，仅诊断）、`fn_ptr_align`（`F`：`Fi<n>` 独立 / `Fn<n>` 函数对齐倍数）、`non_integral`（`ni:`）。

`PointerSpec` 带 `index_bits`（GEP 偏移的算术宽度；未给出时等于 `size_bits`）。

### 2.7 Metal 的对齐不等于 LLVM 的对齐

`KNOWN`（`abi/mod.rs` 模块文档明示）。重要细节：`air.arg_type_align_size` 是 **Metal 的**对齐，而 LLVM 类型本身不携带它（clang 把很多 struct 降低成 packed）。因此上游对它只要求"是 2 的幂"，不与 LLVM 布局比对。

能与 LLVM 布局比对的是（仅在 typed-pointer bitcode 下）：

- buffer（或 Core Image pointer）的 `air.arg_type_size` 等于其 pointee 在 DataLayout 下的 `alloc_size`；
- buffer 的 `air.buffer_size` 是它的整数倍（一个数组的引用）；
- 每个 `air.struct_type_info` 成员起点落在容器内，数组与嵌套 struct 整体落在容器内。

> **本项目含义**：在 Metal 对象层构造 argument buffer 布局时，不得用 LLVM/C ABI 对齐去推 Metal 对齐。`31-PIPELINE-ARTIFACT.md` 第 11 节给出上游提供的 `ArgumentBufferLayout`，必须用它。

---

## 3. 各 stage 的签名约定

来源：`abi/mod.rs`（`enum Stage`、`EntryPoint`）、`abi/module.rs`（`NAMED`）。

### 3.1 入口点只有 5 个命名列表

`KNOWN`（`abi/module.rs`，`NAMED`，`decode` 末尾的 stage 循环）：`!air.kernel`、`!air.vertex`、`!air.fragment`、`!air.object`、`!air.mesh`。解码顺序固定为 kernel → vertex → fragment → object → mesh，各自按列表内顺序。

**tile 函数没有自己的列表**：它在 `!air.kernel` 里，容器 `TYPE` 也是 2。区分 tile 与普通 kernel 靠**编译时输入**，不靠 AIR：上游的 CLI 对一个 kernel 加 `--color-format` 就编译成 tile pipeline，库侧是 `LoweringInputs::tile_attachments`。`KNOWN`（`README.md`、`pipeline/mod.rs` 的 "Tile pipelines" 段）。

**post-tessellation vertex 函数**也没有自己的列表：它在 `!air.vertex` 里，靠 `air.patch` 属性识别（`Stage::Vertex { patch: Some(_) }`）。

`[[visible]]`、`[[intersection]]`、Core Image kernel、dynamic library 导出符号都**不是 stage**，分别在 `!air.visible`、`!air.ci` 等列表里。

### 3.2 stage 属性

`KNOWN`（`abi/mod.rs`，`enum Stage`）：

| stage | 属性 | AIR key |
|---|---|---|
| `Kernel` | `max_total_threads: Option<u32>` | `air.max_work_group_size`（`[[max_total_threads_per_threadgroup]]`） |
| `Vertex` | `patch: Option<PatchInfo>` | `air.patch, <kind>[, air.patch_control_point, <n>]`；`kind` ∈ {`Triangle`, `Quad`}；`control_points` 为 `None` 表示 `[[patch(kind)]]`，即每 patch 控制点数由 draw 决定 |
| `Fragment` | `early_fragment_tests: bool` | `early_fragment_tests` |
| `Object` | `max_total_threads`、`max_mesh_threadgroups` | `air.max_work_group_size`、`air.max_mesh_work_groups`（`[[max_total_threadgroups_per_mesh_grid]]`） |
| `Mesh` | `max_total_threads` | `air.max_work_group_size` |

`Stage::max_total_threads()` 只对 kernel/object/mesh 返回值；vertex 与 fragment 恒为 `None`。

### 3.3 签名的结构约定

`KNOWN`（`abi/mod.rs::EntryPoint`、`abi/check.rs`）：

- **每个 LLVM 参数恰好有一个 binding**，按参数顺序排在 `EntryPoint::params` 里。少了、多了、重复都是 `AbiError`。
- 每个 role 必须与参数的**类型与 address space** 相符。buffer/texture/sampler 表若以 `array_ref` 传入，则是一个 `thread` 空间指针。
- **outputs 与返回类型相符**：按返回结构体字段顺序排，每个 output 标明自己的字段号（`OutputBinding::field`）。canonicalization 会移除被 false 函数常量谓词关掉的 output，因此特化后的字段号**可以不连续**。
- `!air.visible` 函数：每个参数绑定一次，返回值非 void 时恰好有一个 output。
- `!air.ci` Core Image kernel：每个参数绑定一次，role 与参数类型相符，返回值非 void 时恰好有一个标量或向量 output。
- **texture 的形状不在 ABI 模型里** `KNOWN`（`abi/mod.rs` 模块文档明示）：唯一拼出形状的 metadata 是 MSL 类型名（一个只做诊断的 `DiagName`），以及仅在 typed-pointer bitcode 下的 pointee struct（已擦除）。因此 texture 的 `ImageShape` 来自**使用它的 intrinsic 的类型化操作数位置**（`intrinsics::ImageShape`）。这条对本项目很重要：不能靠 metadata 判断一个 texture 是 2D 还是 cube。

---

## 4. AIR 的 metadata ABI

来源：`crates/metal2vulkan-air/src/abi/`（`mod.rs` 模型、`module.rs` 命名 metadata、`args.rs` 参数、`structs.rs` 结构体、`sampler.rs` constexpr sampler、`keys.rs` key 词表、`check.rs` 交叉校验、`md.rs` 读取原语、`visible.rs`、`core_image.rs`）。
入口符号：`air::abi::decode(module, pointees, meter) -> AirAbi`。

### 4.1 语法是**封闭且严格**的

`KNOWN`（`abi/mod.rs` 模块文档）。这是本项目必须理解的最重要一条：

- 命名 metadata 集合封闭。任何其他 `air.*`/`llvm.*` 列表、未知的 `air.compile.*` 选项、未知的 module flag 都是 `AbiError::UnknownKey`。
- 参数、output、struct 成员、entry 属性的**每个 key 都有固定 arity 与值类型**，且只被定义它的 role 接受。未知 key、role 不接受的 key、重复 key、缺必需 key、值类型错，分别是 `UnknownKey`/`BadValue`/`MissingKey`。
- 一个特例值得单记：argument-buffer 成员的 `air.indirect_argument` 属于 `air.indirect_buffer` 的布局。因此**一个 `air.buffer`（参数或成员）的布局在任意深度上含有 `air.indirect_argument` 都是 `UnknownKey`**。
- 名字（`air.arg_name`、`air.arg_type_name`、struct 成员名与类型名、常量名）保留为 `DiagName` 仅供诊断，**绝不决定任何事**。
- 唯一的例外是 varying 的 user key（`generated(..)`、`user(..)`）：它是 Metal 的接口匹配 ABI，以 `UserKey` 形式保存，**只做相等比较**。

**对本项目的直接含义**：上游不会"宽容地忽略"一个新 key。macOS 26/27 编译器新增任何 metadata key，上游会以 `UnknownKey` 拒绝整个模块。这是本项目最可能遇到的第一类回归，必须有对应的扩展流程（第 7.2 节）。

### 4.2 命名 metadata 封闭集合

`KNOWN`（`abi/module.rs`，常量 `NAMED`，`enum Named`）。共 17 项：

| 名字 | 解码为 |
|---|---|
| `air.version` | `AirAbi::air_version: Option<Version>`（三段 `{major, minor, patch}`） |
| `air.language_version` | `AirAbi::language`；节点首操作数必须是字符串 `"Metal"`，后跟三个 u32 |
| `air.compile_options` | `AirAbi::compile: CompileOptions` |
| `air.kernel` | 入口列表 |
| `air.vertex` | 入口列表 |
| `air.fragment` | 入口列表 |
| `air.object` | 入口列表 |
| `air.mesh` | 入口列表 |
| `air.function_constants` | `Vec<FunctionConstantDecl>` |
| `air.sampler_states` | `Vec<StaticSampler>`（constexpr sampler） |
| `air.visible_function_references` | `Vec<VisibleFunctionRef>` |
| `air.visible` | `Vec<VisibleFunction>` |
| `air.ci` | `Vec<CoreImageKernel>`（Core Image） |
| `air.signature` | `Option<LinkageSignature>` |
| `air.source_file_name` | 校验形状后丢弃 |
| `llvm.module.flags` | `AirAbi::limits: ModuleLimits` |
| `llvm.ident` | `AirAbi::producer`（只保留第一个） |

**第 18 项被专门拒绝** `KNOWN`：`air.global_bindings`（MSL 3.2 的 program-scope buffer binding，每条 `!{!"air.global_binding", <global>, <binding>}`）。它是合法 AIR，上游未实现，所以以 `Unsupported(Feature::ProgramScopeBinding)` 拒绝，而不是报 `UnknownKey`。

### 4.3 `air.compile_options`

`KNOWN`（`abi/module.rs::compile_options`，`CompileOptions`）。封闭集合，每项是一个单字符串节点：

| 字符串 | 落到 |
|---|---|
| `air.compile.fast_math_enable` | `fast_math = Some(true)` |
| `air.compile.fast_math_disable` | `fast_math = Some(false)` |
| `air.compile.framebuffer_fetch_enable` | `framebuffer_fetch = Some(true)` |
| `air.compile.framebuffer_fetch_disable` | `framebuffer_fetch = Some(false)` |
| `air.compile.denorms_disable` | `denorms_disable = true` |

重复或互相矛盾是 `BadValue`，未知字符串是 `UnknownKey`。

### 4.4 `llvm.module.flags` 的 `air.max_*`

`KNOWN`（`abi/mod.rs::ModuleLimits`，`abi/module.rs::module_flags`）。这些是模块**编译时所针对的 argument table 大小**，不是设备限制：

`air.max_device_buffers`、`air.max_constant_buffers`、`air.max_threadgroup_buffers`、`air.max_textures`、`air.max_read_write_textures`、`air.max_samplers`。每项 `Option<u32>`，`None` 表示模块未声明。

> **本项目含义**：这组值可以用来给 `_MTLIOAccelDevice` 的 `initLimits` 做合理性校验，但不是设备能力的来源。

### 4.5 整数可以是"一个全局"

`KNOWN`（`abi/mod.rs::AbiInt`）。metadata 里的整数有两种形式：

- `AbiInt::Const(u32)`：直接写出的整数；
- `AbiInt::Global(GlobalId)`：一个整数全局，其值由 **static initializer** 计算（典型场景是依赖函数常量的 slot 索引）。canonicalization 在求值 static initializer 之后把它替换成 `Const`。

`Slot { index: AbiInt, count: AbiInt }` 是 Metal argument table 的槽位：`index` 是 `[[buffer(n)]]`/`[[texture(n)]]`/`[[attribute(n)]]` 的 `n`，`count` 是数组长度（单个参数为 1）。AIR key 是 `air.location_index, <index>, <count>`。

> **本项目含义**：**不能**在 decode 阶段就把 slot 当成常量读出来。必须走 canonicalization（`air::specialize*`）才能拿到数值。这是"禁止自行推导 descriptor binding"的技术根因之一。

### 4.6 `ParamRole` 全量清单

`KNOWN`（`abi/mod.rs`，`enum ParamRole`）。这是入口参数与 argument-buffer 成员共用的 role 集合。

#### 资源类

| `ParamRole` | AIR key | 载荷 |
|---|---|---|
| `Buffer(BufferArg)` | `air.buffer`（device/constant 空间） | `BufferArg` |
| `ArgumentBuffer(BufferArg)` | `air.indirect_buffer` | 同上；这是 argument buffer |
| `Threadgroup(BufferArg)` | `air.buffer`（threadgroup 空间） | 同上；slot 是 `[[threadgroup(n)]]` |
| `Texture(TextureArg)` | `air.texture` | `TextureArg` |
| `Sampler { location }` | `air.sampler` | `Slot` |
| `AccelerationStructure { kind, arg }` | `air.instance_acceleration_structure` / `air.primitive_acceleration_structure` | `AccelerationStructureKind` + `ObjectArg` |
| `FunctionTable(ObjectArg)` | `air.visible_function_table` | |
| `IntersectionTable(ObjectArg)` | `air.intersection_function_table` | |
| `CommandBuffer(ObjectArg)` | `air.command_buffer` | indirect command buffer |
| `ComputePipelineState(ObjectArg)` | `air.compute_pipeline_state` | |
| `RenderPipelineState(ObjectArg)` | `air.render_pipeline_state` | |
| `DepthStencilState(ObjectArg)` | `air.depth_stencil_state` | MSL 4.0；上游注明只有 Metal 的 Apple10 family 能跑 |
| `IndirectConstant { location }` | `air.indirect_constant` | argument buffer 里的普通值 |

`BufferArg` 字段 `KNOWN`：`location: Slot`、`access: Access`、`space: AddrSpace`（`air.address_space`）、`buffer_size: Option<u32>`（`air.buffer_size`）、`layout: Option<StructRef>`（`air.struct_type_info`）、`raster_order_group: Option<u32>`。

`TextureArg` 字段：`location: Slot`、`access: Access`、`raster_order_group: Option<u32>`。

`ObjectArg` 字段：`location: Slot`、`access: Option<Access>`（未声明则 `None`）。

`Access` 取值 `KNOWN`：`Read`（`air.read`）、`Write`（`air.write`）、`ReadWrite`（`air.read_write`）、`Sample`（`air.sample`，仅 texture）。texture 必须有四者之一；buffer 必须有前三者之一（`abi/keys.rs` 的 `TEXTURE_ACCESS`、`BUFFER_ACCESS`）。

#### stage 输入类

| `ParamRole` | AIR key | 说明 |
|---|---|---|
| `Builtin(Builtin)` | 各 builtin 自己的 key | 见 4.7 |
| `StageIn { location }` | `air.stage_in` | kernel 的 `[[stage_in]]`；`location` 是该成员的 `[[attribute(n)]]` |
| `VertexInput { location }` | `air.vertex_input` | vertex attribute 的 `[[attribute(n)]]` |
| `FragmentInput(Varying)` | `air.fragment_input` | `Varying { key: UserKey, interpolation: Interpolation }` |
| `ColorInput { index, raster_order_group }` | `air.render_target` 作为 fragment 输入 | framebuffer fetch，读 `[[color(n)]]` |
| `PatchInput(PatchInput)` | `air.patch_control_point_input` / `air.patch_input` | 见 4.9 |
| `Imageblock(ImageblockArg)` | `air.imageblock` / `air.imageblock_data` | 见下 |

`Interpolation` `KNOWN`：`Flat`（`air.flat`，取 provoking vertex 的值）或 `Smooth { sampling, perspective }`，其中 `sampling` ∈ {`Center`(`air.center`), `Centroid`(`air.centroid`), `Sample`(`air.sample`)}，`perspective` 对应 `air.perspective`(true)/`air.no_perspective`(false)。

`ImageblockArg` `KNOWN`：`kind` ∈ {`Explicit`(`air.imageblock, "explicit"`，kernel), `Implicit`(`air.imageblock, "implicit"`，kernel), `Data`(`air.imageblock_data`，fragment 输入或输出)}；`data_size: Option<u32>`（`air.imageblock_data_size`）；`layout: Option<StructRef>`（cell 布局）；`master: Option<StructRef>`（`air.imageblock_master`，整个 imageblock 的布局）；`alias_implicit: bool`（`air.alias_implicit_imageblock`）。

#### mesh / object 类

| `ParamRole` | AIR key | 说明 |
|---|---|---|
| `Payload { layout }` | `air.payload` | object 函数写、它启动的 mesh 函数读；`object_data` 空间指针。大小与对齐来自该 binding 的 `air.arg_type_size` 与 `air.arg_type_align_size` |
| `MeshGridProperties` | `air.mesh_grid_properties` | object 函数对其启动的 mesh grid 的句柄 |
| `Mesh(Box<MeshOutputs>)` | `air.mesh` | mesh 函数的输出句柄，类型 `mesh<V, P, NV, NP, t>` |

`MeshOutputs` `KNOWN`（`air.mesh_type_info`）：`vertex: Vec<MeshField>`、`primitive: Vec<MeshField>`（primitive 类型为 `void` 时为空）、`max_vertices: u32`（NV）、`max_primitives: u32`（NP）、`topology: MeshTopology` ∈ {`Point`(`air.point`), `Line`(`air.line`), `Triangle`(`air.triangle`)}。

`MeshFieldRole` 全量 `KNOWN`：
- vertex 字段：`Position { invariant }`（`air.position` + `air.invariant`）、`PointSize`、`ClipDistance { array_size }`（`air.clip_distance_array_size`）、`VertexData { slot, key }`（`air.mesh_vertex_data, <slot>, <user key>`）；
- primitive 字段：`PrimitiveCulled`、`PrimitiveId`、`RenderTargetArrayIndex`、`ViewportArrayIndex`、`PrimitiveData { slot, key }`（`air.mesh_primitive_data, <slot>, <user key>`）。

### 4.7 `Builtin` 全量清单

`KNOWN`（`abi/mod.rs`，`enum Builtin`；key 拼写见 `abi/keys.rs`）。这是一个**封闭**集合。

#### dispatch 类（kernel；部分也出现在其他 stage）

`ThreadPositionInGrid`、`ThreadPositionInThreadgroup`、`ThreadgroupPositionInGrid`、`ThreadsPerThreadgroup`（本 threadgroup 的实际大小，非均匀 grid 边缘会更小）、`ThreadsPerGrid`、`ThreadgroupsPerGrid`、`ThreadIndexInThreadgroup`、`ThreadIndexInSimdgroup`、`ThreadIndexInQuadgroup`、`SimdgroupIndexInThreadgroup`、`QuadgroupIndexInThreadgroup`、`ThreadsPerSimdgroup`、`SimdgroupsPerThreadgroup`、`QuadgroupsPerThreadgroup`、`DispatchThreadsPerThreadgroup`（dispatch 声明的 threadgroup 大小，与本 threadgroup 实际大小无关）、`DispatchSimdgroupsPerThreadgroup`、`StageInGridSize`（`air.stage_in_grid_size`，`[[grid_size]]`）、`StageInGridOrigin`（`air.stage_in_grid_origin`，`[[grid_origin]]`）。

#### vertex 类

`VertexId`、`InstanceId`、`BaseVertex`（无 index buffer 的 draw 取 `vertexStart`，indexed draw 取 `baseVertex`；**仅 vertex 函数**）、`BaseInstance`（vertex 与 post-tessellation vertex）、`AmplificationId`、`AmplificationCount`、`PositionInPatch`、`PatchId`。

#### fragment 类

`Position(Option<Interpolation>)`、`FrontFacing`、`PointCoord`、`PrimitiveId`、`SampleId`、`SampleMaskIn`（`air.sample_mask_in`）、`PostDepthCoverage`（`air.sample_mask_in` + `air.post_depth_coverage`；上游注明 Metal 编译器要求该函数声明 `[[early_fragment_tests]]`）、`BarycentricCoord(Interpolation)`、`RenderTargetArrayIndex`、`ViewportArrayIndex`（后两者 fragment 与 tile 函数）。

### 4.8 `OutputRole` 全量清单

`KNOWN`（`abi/mod.rs`，`enum OutputRole`、`OutputBinding`）：

| `OutputRole` | AIR key | 载荷 |
|---|---|---|
| `Position { invariant }` | `air.position` | `air.invariant` |
| `VertexOutput(UserKey)` | `air.vertex_output, <user key>` | |
| `PointSize` | `air.point_size` | |
| `ClipDistance { array_size }` | `air.clip_distance` | `air.clip_distance_array_size` |
| `RenderTargetArrayIndex` | `air.render_target_array_index` | |
| `ViewportArrayIndex` | `air.viewport_array_index` | |
| `RenderTarget { attachment, index, raster_order_group }` | `air.render_target, <attachment>, <index>` | `index` 是 dual-source blending 索引 |
| `Depth(DepthQualifier)` | `air.depth` | `air.depth_qualifier` ∈ {`Any`, `Less`, `Greater`} |
| `SampleMask` | `air.sample_mask` | |
| `Stencil` | `air.stencil` | |
| `ImageblockData(ImageblockArg)` | `air.imageblock_data` | fragment 的 imageblock 输出 |

`OutputBinding` 另有：`shared: bool`（`air.shared`，该 output 被所有 vertex-amplification view 共享）、`predicate: Option<Predicate>`、`ty: ArgTypeInfo`、`name: Option<DiagName>`。

### 4.9 post-tessellation 的 patch 输入

`KNOWN`（`abi/mod.rs`，`enum PatchInput`、`ControlPointField`）：

- `PatchInput::ControlPoints { function: FuncId, fields: Vec<ControlPointField> }` —— `air.patch_control_point_input`。`function` 是 `air.patch_control_point_function` 命名的**声明**，Metal 从 pipeline 的 vertex descriptor 合成它的函数体。`fields` 一项对应该函数返回结构体的一个成员，按成员顺序。
- `PatchInput::Patch { location: Slot }` —— `air.patch_input`，per-patch attribute 的 `[[attribute(n)]]`。

`ControlPointField`：`location: Slot`（该字段从哪个 `[[attribute(n)]]` 取）、`predicate`、`ty: ArgTypeInfo`（control-point 字段**不声明** size 与 alignment）、`name`、`unused: bool`（`air.arg_unused`：函数不读任何控制点的这个字段）、`gated_off: bool`（canonicalization 解析谓词后置位：Metal 对它不取任何数据）。

`AirAbi::control_point_fetches()` 遍历全部入口给出这些合成声明的 `FuncId`。

### 4.10 函数常量

`KNOWN`（`abi/mod.rs`，`FunctionConstantDecl`、`Predicate`）。

`!air.function_constants` 的每条给出：

| 字段 | 含义 |
|---|---|
| `index: u32` | `[[function_constant(index)]]`，请求按它提供值 |
| `global: GlobalId` | initializer 全局（section `air.fc_initializer`）；**这是常量的身份** |
| `ty: TypeId` | 该全局的值类型 |
| `flag: Option<bool>` | 第五操作数（若有）。上游明示"含义未明，只记录不解释" |
| `data_type: Option<metal::DataType>` | 容器 `CNST` 标签给出的 `MTLDataType`，在 `check_container` 跑过之后才有 |
| `name: DiagName` | 仅诊断 |
| `type_name: DiagName` | metadata 拼出的 MSL 类型名（`bool`/`uint`/`float4`）。**这是 AIR 里唯一区分有符号与无符号整数的地方** |

`Predicate { global, name }` 是函数常量谓词（`air.function_constant, !{<global>, <type>, <name>}`）：参数或 output 只在那个整数全局的值非零时存在。谓词可以挂在参数 binding、output binding、control-point 字段、mesh 字段上。

容器交叉校验 `KNOWN`（`abi/check.rs::container`，经 `AirAbi::check_container`）：

1. bitcode 必须**恰好声明一个入口点**（一个 metallib 函数就是它自己的模块，只装那个入口）；
2. 容器 `TYPE` 必须等于那个入口的 stage；
3. 每个 `CNST` 条目必须按 index 命中一个已声明的函数常量，且其 `MTLDataType` 的存储形式等于该常量 initializer 全局的值类型。

不一致是 `AbiError::ContainerMismatch`，且**不修改** `AirAbi`。模型未覆盖的 stage（`TYPE` 不是 vertex/fragment/kernel/mesh/object）是 `Unsupported(Feature::Stage)`。

> **本项目含义**：第 1 条很关键。如果 guest 提交的是一个 bitcode 模块（而非 metallib）且带多个入口，`check_container` 不适用，但 `newFunctionWithName:` 语义得由本项目自己从 ABI 枚举（`container/mod.rs` 模块文档明示"a wrapper or raw module may hold several entry points; enumerating them needs its AIR metadata"）。

### 4.11 `air.struct_type_info` 与 argument buffer 的 `[[id(n)]]`

`KNOWN`（`abi/mod.rs`，`StructInfo`、`Member`、`MemberKind`、`IndirectArg`、`StructRef`）。

`StructRef(u32)` 是 `AirAbi::structs` 的索引，多个引用共享同一布局。`StructInfo { members: Vec<Member> }`，按声明顺序。

`Member` 字段：

| 字段 | 含义 |
|---|---|
| `offset: u32` | 成员在结构体内的字节偏移 |
| `size: u32` | **一个元素**的字节数 |
| `array_len: u32` | 数组长度；**非数组成员是 0**（不是 1） |
| `layout: Option<StructRef>` | 成员本身是结构体时的布局 |
| `kind: MemberKind` | 在 argument buffer 里绑定什么 |
| `render_target: Option<u32>` | `air.render_target, <n>`（imageblock 成员） |
| `raster_order_group: Option<u32>` | `air.raster_order_group, <n>`（imageblock 成员） |
| `type_name`、`name` | 仅诊断 |
| `key: UserKey` | 成员名字节。对 imageblock 成员是它的 user key（`user(..)`，否则是声明名），view 的成员靠它命名它所 view 的 master 成员（MSL §4.7.1）。只做相等比较 |

`MemberKind` 三种：

- `Plain` —— 普通字节。
- `Indirect(IndirectArg)` —— `air.indirect_argument, !{..}`：成员自己的 argument binding。
- `IndirectStruct { first_id: u32 }` —— `air.indirect_argument, <first id>`：一个结构体成员，其内部成员的 Metal `[[id(n)]]` 被 `first_id` 偏移。

**`[[id(n)]]` 的计算规则** `KNOWN`（`MemberKind::IndirectStruct` 文档明示）：

```
成员的 [[id]] = 沿嵌套路径上各层 IndirectStruct 的 first_id 之和
              + 该成员 role 自己的 air.location_index
              + 数组元素下标（数组成员）
```

`IndirectArg::ordinal` **不是** `[[id(n)]]`：它是成员节点的首个整数，即该成员在所属布局里的序号（上游注明在语料的每个成员里都等于它在 `StructInfo::members` 里的位置，也就是 LLVM 字段索引）。

> **本项目含义**：这是"禁止自行推导 binding"的第二个技术根因。`[[id]]` 需要沿嵌套路径累加，且与 LLVM 字段索引不是同一回事。本项目必须用上游的 `bind::ArgumentBufferLayout`（见 `31-PIPELINE-ARTIFACT.md` 第 11 节），不得自己算。

### 4.12 constexpr sampler

`KNOWN`（`abi/mod.rs::StaticSampler`，`abi/sampler.rs`）。`!air.sampler_states` 的每条是 `!{!"air.sampler_state", <global>}`；`global` 是常量全局，其 initializer 装着 sampler 的 words，由 `abi::sampler::decode_global` 解成 `SamplerState`。

导出的 sampler 词表（`abi/mod.rs` 的 `pub use sampler::`）：`AddressMode`、`BorderColor`、`CompareFunction`、`Coordinates`、`Filter`、`MipFilter`、`Reduction`、`Half`、`SamplerState`。

### 4.13 visible function、链接与 stitching

`KNOWN`（`abi/mod.rs`，`VisibleFunction`、`VisibleFunctionRef`、`VisibleTarget`、`VisibleSymbol`、`Stitching`、`LinkageSignature`）。

- `!air.visible_function_references` 的每条是 `!{!"air.visible_function_reference", ptr @stub, !"<symbol>"}`。`target` 是 `VisibleTarget::Function(FuncId)`（可调用的 stub）或 `VisibleTarget::Global(GlobalId)`（**不是** 可调用 stub，`visible_function_stubs()` 会跳过）。`symbol: VisibleSymbol` 是链接 ABI，只做相等比较。
- `!air.visible` 的每条给出导出函数、每个参数的 binding（`VisibleParamKind::Input{..}` = MSL 签名的参数，`Padding` = MSL 签名里没有的参数）、`outputs`（非 void 时一个）、`stitching: Option<Stitching>`（`[[stitchable]]` 函数才有）。
- `air.stitching_info`：只解结构与 helper 函数；MSL 类型描述符**不解**（没有翻译读它）。`StitchingType { helpers: [Option<FuncId>; 4] }`，上游明示"roles are not established; they are recorded, not interpreted"。
- `!air.signature`：只解 kind 与操作数个数。kind ∈ {`LinkedConstants`(`air.linked_constants_signature`), `StitchingModules`(`air.stitching_modules_signature`)}。`air.rename_qualified_function_signature`（Apple 编译器在 macOS 14 的产出）是 `!{!"<kind>", !<signature>, !"<name>"}`，被读作它包裹的那个 signature，名字不保留。

拒绝规则 `KNOWN`：仍声明函数常量的 linked-constants 模块被拒（`Feature::Linking`）；带 signature 的 linked function 模块同样被拒。

`AirAbi::reaches_function_tables(ep)`：该入口能否通过 visible-function table 调用 —— 它自己接收一个，或它接收的某个 buffer 的 `air.struct_type_info` 布局在**任意深度**上有一个 role 是 `FunctionTable` 的成员。对布局线性。

### 4.14 Core Image kernel

`KNOWN`（`abi/mod.rs`，`CoreImageKernel`、`CoreImageParam`、`CoreImageRole`；`abi/core_image.rs`）。`!air.ci` 列出模块导出的 Core Image kernel。每个参数是 `!{i32 <param>, !"air.ci_<role>", <attr>*}`。

`CoreImageRole` 封闭集合（每个都与参数 IR 类型交叉校验）：

| role | 要求 |
|---|---|
| `Builtin` | 标量或向量数值 |
| `Matrix` | 矩阵，表示为向量数组或一个 struct 的唯一字段 |
| `Texture { location_count, access }` | texture 句柄，device 空间指针，裸传或作为 struct 唯一字段。`location_count` 来自 `air.location_count`（上游注明每个观察到的模块里都是 1，只记录不解释） |
| `Sampler` | sampler 句柄，constant 空间指针，裸传或作为 struct 唯一字段 |
| `Pointer { access, size, align }` | 指向 `size` 字节；`size`/`align` 来自 `air.arg_type_size`/`air.arg_type_align_size` |

返回值是 `!{!"air.ci_builtin", <attr>*}`，标量或向量。

上游明示：**本模块的翻译不读 Core Image 声明** —— 它描述 Core Image 怎么传参，不影响生成的 SPIR-V。

> **本项目含义**：guest 的 CoreImage 会提交带 `!air.ci` 的 metallib。上游能解析不会拒，但 Core Image 自身的调用约定不由上游实现。这是本项目的一个 `BLOCKED` 项，见第 8 节。

### 4.15 其它入口级字段

- `EntryPoint::user_annotation: Option<DiagName>` —— `air.user_annotation`，即 `[[user_annotation("...")]]` 传的字符串，Metal 作为 `MTLFunctionReflection.userAnnotation` 回答；**不改变函数计算什么** `KNOWN`。
- `EntryPoint::reaches_command_buffers(structs)` —— 该入口是否接收 indirect command buffer（参数，或它接收的某 buffer 在任意深度布局里的 `air.command_buffer` 成员）。上游明示这**只是 metadata 的陈述**，函数体怎么用它不管；函数体通过自己 cast 出来的指针到达的 command buffer 不计入这里，由 `canon::Entry::may_encode_indirect_commands` 另行统计。
- `EntryPoint::takes_writable_textures(structs)` —— 同上逻辑，针对 `access::write`/`access::read_write` 的 texture。
- `ParamRole::handle()` / `Member::handle()` —— 给出 `AbiHandle`，是 memory provenance 格的种子。`AbiHandle` 全量：`Texture(Access)`、`Sampler`、`AccelerationStructure(kind)`、`FunctionTable`、`IntersectionTable`、`CommandBuffer`、`ComputePipelineState`、`RenderPipelineState`、`DepthStencilState`、`MeshGridProperties`、`Mesh`。

---

## 5. `air.*` intrinsic 清单与语义分组

来源：`crates/metal2vulkan-air/src/intrinsics/`。入口符号：`intrinsics::classify`（按声明分类，每个声明一次）、`intrinsics::bind`（按调用读取立即数）。

### 5.1 两段式解码

`KNOWN`（`intrinsics/mod.rs` 模块文档）：

1. **声明期** `classify(name, sym, fn_ty, types)`：按前缀选族，族的名字语法给出一个 variant，variant 导出类型化 `Signature`，**声明的函数类型必须与它匹配**。
2. **调用期** `bind(class, args, consts)`：signature 标为 `Operand::Imm` 的位置必须是整数常量，读进 variant 的字段。

错误分级 `KNOWN`：

| 情形 | 结果 |
|---|---|
| 名字在封闭集合之外 | **不是 decode 错误**。调用保留为 `Callee::UnknownIntrinsic`；只有在函数常量特化之后仍存活才被 post-canonical 检查拒绝 |
| 已知名字但立即数命名了模型未定义的枚举值 | 同上（保留为 unknown） |
| 已知名字但声明与 signature 不符 | `IntrinsicError::SignatureMismatch`（**畸形输入**） |
| 立即数不是常量 | `IntrinsicError::ImmediateNotConstant`（**畸形输入**） |
| `llvm.*` marker | decode 时直接丢弃（`Dropped`） |

**一个关键设计**：`Signature` 的 `Operand::Handle` 位置与 `Signature::ret_handle` 给出类型化的句柄位置，这是 memory provenance 格的种子。**句柄只按位置识别，绝不按 pointee struct 的名字识别**（`intrinsics/sig.rs` 明示）。

还有一个重要机制 `AirIntrinsic::alternative()` `KNOWN`：同一个名字可能有多种操作数形式，上游按声明类型逐个试。已知的多形式：texture read 的 legacy 形式、64 位 atomic min/max 不带结果的形式、atomic 与 barrier 的 AIR 2.9 形式、simdgroup-matrix block load/store 的 AIR 2.7 形式、AIR 2.5 的 kernel/vertex buffer setter 不带 attribute stride 的形式。

### 5.2 已解码的族

`KNOWN`（`intrinsics/mod.rs`，`enum AirIntrinsic` 26 个 variant）。按语义分组：

#### 数学与转换

| variant | 名字语法 | 来源文件 |
|---|---|---|
| `Math(Math)` | `air.[fast_]<function>[.<s\|u>].<type>` | `intrinsics/math.rs` |
| `Convert(Convert)` | `air.convert.<kind>.<type>.<kind>.<type>` | `intrinsics/convert.rs` |
| `Pack(Pack)` | `air.{pack,unpack}.<format>.<type>` | 同上 |

`math.rs` 用一张声明式表 `TABLE` 列出每个函数 stem 与其定义域、操作数形状。浮点函数可带可选 `fast_` 前缀且**不带**符号 token；符号敏感的整数函数**必须**带 `.s.` 或 `.u.`；符号无关的整数函数**不带**。同一个 stem 可以同时命名浮点与整数函数（`min`/`max`/`clamp`），由符号 token 决定，且 type token 必须与定义域一致。

两个函数以 **Metal runtime routine** 的形式到达 AIR（Apple 编译器发出声明，其后端在 pipeline creation 时定义）`KNOWN`：
- `frexp` → `___metal_frexp_<T>_pthread<I>(T, thread I*)`。**AIR 2.9 改为** `air.frexp.<T>(T, thread I*)`，两者解到同一个 `Math`。
- `ilogb` → `___metal_ilogb_<T>(T, i32 mode)`。

`T` 是 `float`/`half` 标量或向量（`v<n>float`、`v<n>half`），`I` 是其 int32 形状。canonicalization 用实测答案把这两个调用替换成普通 AIR（`air::canon::routine`）。

#### 原子与内存

| variant | 名字语法 |
|---|---|
| `Atomic(Atomic)` | `air.atomic.{global,local,private}.<op>[.<s\|u>].<type>` |
| `Coherent(Coherent)` | `air.{load,store}.{device,system}_coherent[.volatile].<type>.p<space><...>` |

操作数布局 `KNOWN`（`intrinsics/atomic.rs` 模块文档），对应 Metal 的原子函数：
- read-modify-write：`T (ptr, T, i32 order, i32 scope, i1 volatile)`
- load：`T (ptr, i32 order, i32 scope, i1 volatile)`
- store：`void (ptr, T, i32 order, i32 scope, i1 volatile)`
- weak compare-exchange：`T (ptr, ptr expected, T desired, i32 success order, i32 failure order, i32 scope, i1 volatile)`，其中 `expected` 是一个 thread 指针，旧值写回它

order 与 scope 是立即数；超出枚举的值使调用保留为 unknown，**不猜**。

三个 AIR 版本差异 `KNOWN`，必须全部支持：

| AIR 版本 | 形式 |
|---|---|
| < 2.0（deployment target ≤ macOS 10.12 / iOS 10） | **没有**尾部 volatile flag：`i32 @air.atomic.global.add.u.i32(ptr addrspace(1), i32, i32 order, i32 scope)` |
| 2.0 – 2.8 | 如上表 |
| **2.9**（deployment target macOS 27） | 在 scope 与 volatile 之间**多一个 `i32` 立即数**，即 Metal 的 `mem_flags`：`T (ptr, i32 order, i32 scope, i32 flags, i1 volatile)` |

上游注明：Metal 的头文件在**每个**语言版本都给原子 builtin 传 `mem_flags`（MSL 4.1 之前是 `__METAL_MEMORY_FLAGS_NONE__` 配 relaxed order）；AIR 2.8 把它丢掉。哪种形式由**声明的类型**读出（`Atomic::flags` 对 2.8 形式是 `None`，对 2.9 形式是操作数的掩码）。

另一个 `KNOWN`：Metal 的 64 位 `atomic_min_explicit`/`atomic_max_explicit` 作用在 `device atomic_ulong` 上不返回值（MSL §6.16.4.6），所以 `air.atomic.global.{min,max}.u.i64` 也可以声明为 `void (ptr addrspace(1), i64, i32 order, i32 scope, i1 volatile)`：同操作同立即数，只是没有旧值（`Atomic::fetch == false`）。

#### 屏障与栅栏

`Sync(Sync)` —— `air.wg.barrier`、`air.simdgroup.barrier`、`air.atomic.fence`（`intrinsics/sync.rs`）。

签名 `KNOWN`：
- barrier：AIR 2.8 是 `void (i32 mem_flags, i32 scope)`，AIR 2.9（macOS 27）是 `void (i32 mem_flags, i32 order, i32 scope)`
- fence：`void (i32 mem_flags, i32 order, i32 scope)`
- 全部操作数都是立即数

`mem_flags` 掩码 `KNOWN`：`mem_device` 1、`mem_threadgroup` 2、`mem_texture` 4、`mem_threadgroup_imageblock` 8、`mem_object_data` 16。

**scope 的语义在两种形式间不同** `KNOWN`，这是最容易做错的一处：
- AIR 2.8：barrier 的 scope 操作数**同时是执行作用域与内存作用域**，只从操作数读，**绝不从名字读**。AIR 也会用 `air.simdgroup.barrier` 来拼一个 threadgroup 范围的 barrier。
- AIR 2.9：操作数是 MSL 4.1 的 `thread_scope` 参数，即**仅内存作用域**（观察到有序访问的那些线程，MSL §6.10.1），而**名字就是执行作用域**：`threadgroup_barrier`（`air.wg.barrier`）同步 threadgroup，`simdgroup_barrier`（`air.simdgroup.barrier`）同步 simdgroup，不论给的 scope 是什么。上游给出实例：Apple 编译器把 `threadgroup_barrier(..., thread_scope_simdgroup)` 写成 `air.wg.barrier` 配 scope 4。

上游说明：Metal 的头文件在 MSL 4.1 之前的每个语言版本都传名字自己的 scope，所以两种读法在那些版本拼出的每个 barrier 上一致。

#### 求导与归约

| variant | 名字语法 |
|---|---|
| `Derivative(Derivative)` | `air.[fast_]{dfdx,dfdy}.<type>`、`air.fwidth.<type>` |
| `BoolReduce(BoolReduce)` | `air.{all,any}.v<N>i1` |

#### 纹理与采样

`Texture(Texture)` —— `air.<op>_{texture,depth}_<dim>[.i16][.<s|u>].<type>`；`Sampler(SamplerOp)` —— `air.get_read_sampler`（`intrinsics/texture.rs`）。

每个操作的操作数布局由 variant 导出（`Texture::layout`），每个位置带一个 `TexRole`。上游注明布局来自本地语料普查与公共 fixture 的声明。完整布局 `KNOWN`：

```
sample  {T, i8} (tex, smp, [depth: i32], coord, [array: layer], [compare: ref],
                 [not cube: i1 offset?, offset], i1 level?, float bias-or-level,
                 float min-lod-clamp, i32 access)
grad    同上，但三个 LOD 位置换成 dPdx, dPdy, float min-lod-clamp，
        位置在 coord/layer/compare 之后、offset 对之前（cube 没有 offset 对）
gather  {T, i8} (tex, smp, [depth: i32], coord, [array: layer], [compare: ref],
                 [not cube: i1 offset?, offset], [texture: i32 component], i32 access)
        gather_compare 的深度 texel 是 f32，返回四个
read    当前形式 {T, i8} (tex, smp, [depth: i32], coord, [cube: face], [array: layer],
                        [2d/3d, not ms: offset], ms ? sample : lod, i32 access)
        legacy 形式省略 sampler 与 offset 位置
        texture buffer 没有 level: (tex, [smp], coord, i32 access)
write   void (tex, coord, [cube: face], [array: layer], texel, [not buffer: lod], i32 access)
```

**residency status 的版本门** `KNOWN`，重要：从 **AIR 2.2** 起，sample/gather/read 声明 residency status —— 结果是 `{T, i8}`（texel + Metal 的 residency 字节），且 sample 带上述 min-LOD-clamp 位置。**AIR ≤ 2.1 两者都没有**：声明只返回 texel，sample 没有 clamp 位置。由**声明**选形式，所以 2.2 以下的整个区间不需要单独分支。上游明示：这两件事是在同一个 emitter 步骤里改的，没见过只有其中一个的模块，所以**混合形式保留为 unknown** —— 一个当前形式的 read（带 sampler 与 offset）而不带 status，不被视为它的一种形式。

read/write 的 texel 是 `f32` 或 `f16`，或 `s`/`u` 的 `i32` 或 `i16`（以及 Metal 的其他形式，源码续行未全读）。

#### SIMD 与矩阵

| variant | 名字语法 |
|---|---|
| `Group(Group)` | `air.{simd,quad}_<op>[.<s\|u>].<type>`，加 ballot、`is_first`、active-mask 查询 |
| `IsUniform(IsUniform)` | `air.is_uniform.<type>` |
| `SimdgroupSize(SimdgroupSize)` | `air.get_simdgroup_size.<i16\|i32>` |
| `SimdMatrix(SimdMatrix)` | `air.simdgroup_matrix_8x8_{load,store,init_diag,init_filled,multiply_accumulate}`、`air.simdgroup_matrix_16x16x16_[widening_]multiply_accumulate` |

`simd.rs` 的约定 `KNOWN`：整数类型的值操作数拼出符号（`.s.`/`.u.`），浮点不拼。lane 索引、delta、mask、width 都是 `i16` 操作数。一张声明式表 `OPS` 列出每个操作的操作数形状与它存在于哪些 scope（simdgroup、quad）。

`matrix.rs` 的约定 `KNOWN`：8x8 矩阵是一个 `<64 x T>` 值；16x16x16 的操作数是每线程 `<8 x T>` 的 fragment。8 位浮点格式用 `i8` lane 承载，名字拼出格式。8x8 load/store 取一个指针加三个 `<2 x i64>` 操作数；16x16x16 的乘积在两个因子各自之后取一个 `i1`。

#### 阶段级

| variant | 内容 |
|---|---|
| `GlobalBuiltin(GlobalBuiltin)` | `air.get_<built-in>.<i16\|i32>`：由 program-scope 变量声明的 kernel builtin |
| `FunctionConstant(FunctionConstant)` | 函数常量查询，由 canonicalization 的特化解析 |
| `Fragment(Fragment)` | discard、rate-map 坐标映射、sample count |
| `Imageblock(Imageblock)` | imageblock 的 data 指针、size、implicit imageblock 的 load/store |
| `AbsentAccess`、`Derivative`、`BoolReduce`、`GlobalVar` | 同在 `intrinsics/stage.rs` |

#### 对象族

`intrinsics/objects.rs`：`AsyncCopy`（simdgroup async copy 与其 event 操作）、`FunctionTable`（visible/intersection function table 上的操作）、`AccelerationStructure`（instance acceleration structure 查询）、`Tensor`（Apple 的 opaque tensor ABI 的描述符操作）、`IndirectCommand`（compute/render command 的 ICB 编码操作）、`RenderState`、`CommandStage`。

上游明示这些只解成类型化 signature；非句柄的位置是普通操作数，其含义由 lowering 拥有（或拒绝）。

#### mesh / object

`Mesh(Mesh)` —— object 函数的 `air.set_threadgroups_per_grid_mesh_properties`，mesh 函数的 `air.set_*_mesh`（写 output 的 vertex、index、primitive、primitive count）。每个先取自己的句柄（`air.mesh_grid_properties` 或 `air.mesh` 参数）；slot/vertex/index/primitive 操作数是 `i32` 值。

#### 光线求交

`Intersect(Intersect)` —— `air.intersect[.<tag>]*`（`intrinsics/intersect.rs`）。

上游给出完整 ABI `KNOWN`。Metal 的 `intersector<Tags...>::intersect` 降到一个 intrinsic，名字按 ABI 位序拼出 intersector 的 tag：

```
intersection_function_buffer 1   instancing 2        max_levels 4
triangle_data 8                  curve_data 16       world_space_data 32
user_data 64                     primitive_motion 128
instance_motion 256              extended_limits 512
```

`max_levels<N>`（N > 2）拼 `multi_level_instancing` 代替 `instancing`；`max_levels<2>` 就是普通 `instancing`。无 tag 的 intersector 调 `air.intersect` 本身。

操作数顺序（上游注明读自 Apple 的 `metal_raytracing` 头并在编译探针上确认）：

```
origin <3 x float>, direction <3 x float>, min_distance float, max_distance float,
structure ptr addrspace(1)
[instancing]                     mask i32
[任一 motion tag]                time float
                                 intersection function table ptr addrspace(1)
                                 （或带 intersection_function_buffer 时：buffer ptr addrspace(1)
                                   加 size 与 stride 的 i64, i64）
[user_data]                      user_data ptr addrspace(1)
                                 payload ptr, payload size i64
[multi-level]                    i8 max_levels, ptr instance_ids, ptr user_instance_ids
                                 九个 i32 设置（front-facing winding、triangle cull mode、
                                 geometry cull mode、opacity cull mode、forced opacity、
                                 geometry type、curve basis、curve type、curve control-point count）
[instancing]                     i1 assume_identity_transforms
                                 i1 accept_any_intersection
[intersection_function_buffer]   i32 base_id, i32 geometry_multiplier
```

结果是字面结构体 `{ i32 type, float distance, i32 primitive_id, i32 geometry_id, ptr addrspace(1) primitive_data }`，再加 `i32 instance_id, i32 user_instance_id`（instancing）或 `i8 instance_count`（multi-level，两个 id 通过那两个指针写回），加 `<2 x float> barycentrics, i1 front_facing`（`triangle_data`），以及更多（源码续行未全读）。

### 5.3 `llvm.*` 封闭集合与 AGX

`KNOWN`（`intrinsics/llvm.rs`）。三类：

- **Kept**：保留的 LLVM 操作（`LlvmIntrinsic`，含 `LlvmFloatOp`、`LlvmIntOp`）；
- **Dropped**：decode 时丢弃的 marker（`llvm.lifetime.*` 之类，`enum Dropped`，`dropped_family()` 查询）；
- **AGX**：Apple GPU family `llvm.agx<N>.*`（`AgxOp`、`AgxSpace`）。

名字形式：base name + overload 后缀。overload 类型从声明读出，后缀必须拼对（LLVM 自己的读取器也拒绝拼错的 intrinsic）。指针 overload 拼成 `p<space>`（opaque）或 `p<space><pointee>`（typed），**只校验 space**，pointee 是 decode-only 的。

AGX intrinsic 语义未建模的是 `Feature::AgxUnmodeled`（`lower/simd/agx.rs::unmodeled`），上游 reach 标注 `rare: Apple's own libraries' AGX intrinsics`。

### 5.4 已知但**不解码**的族

`KNOWN`（`intrinsics/mod.rs`，常量 `UNDECODED`、`UNDECODED_FEATURES`；查询函数 `undecoded_family`、`undecoded_feature`、`undecoded_ray_tracing`）。

这是"listed"的那一半契约：语料里的每个名字要么解码，要么匹配这里的一个条目。每条是一个名字前缀。

| 前缀 | 理由（上游原文要点） |
|---|---|
| `air.function_constant_predicate` | 语料与 fixture 里都没观察到声明 |
| `air.set_intersection_function_table.` | 同上 |
| `air.convert.f.f8e4m3.` | 见下 FP8 说明 |
| `air.convert.f.f8e4m3fn.` | 同上 |
| `air.convert.f.f8e5m2.` | 同上 |
| `air.get_imageblock_samples` | 多重采样 imageblock（见下） |
| `air.get_imageblock_num_colors` | 同上 |
| `air.get_color_coverage_mask` | 同上 |
| `air.store.implicit_imageblock.mask.` | 同上 |

**FP8 窄化** `KNOWN`（常量 `FP8_NARROWING`）：在 Apple M3（AGXMetalG15X，macOS 26.7）上，Metal **编译不出**从 float 的转换（编译服务被中断）；从整数的能编能跑，但返回的字节不是该格式的编码，且各格式返回相同。MSL 对这些 `air.convert` 没有定义 rounding/overflow/saturation（MSL 4.1 只通过显式 mode 的 `pack` 提供 8 位浮点），上游手上没有设备能钉死它。注意上游专门说明：这些前缀只覆盖标量目标（唯一观察到的），向量目标（`air.convert.f.v<N>f8<format>.`）不匹配任何前缀，会变成**未列出的** unknown intrinsic。

**多重采样 imageblock** `KNOWN`（常量 `MULTISAMPLE_IMAGEBLOCK`）：一个多重采样 imageblock 的 sample count（`get_num_samples`）、它的像素持有的 color 与各自的 coverage mask（`get_num_colors`、`get_color_coverage_mask`）、以及按 coverage mask 的 store。理由：tile 函数与 fragment imageblock 只在单采样 pass 上跑，而 Metal 为一个像素保留多少 color 没有被探测过。

`UNDECODED_FEATURES` 把其中一部分映射到类型化 feature，使其拒绝信息更准确 `KNOWN`：

| 前缀 | `Feature` |
|---|---|
| `air.set_intersection_function_table.` | `IntersectionFunctionTable` |
| `air.get_imageblock_samples` | `Imageblocks` |
| `air.get_imageblock_num_colors` | `Imageblocks` |
| `air.get_color_coverage_mask` | `Imageblocks` |
| `air.store.implicit_imageblock.mask.` | `Imageblocks` |

另有一条规则 `undecoded_ray_tracing(name)` `KNOWN`：名字第一段是 `intersect` 但 tag 语法拒绝（更晚的 tag、新组合），或第一段以 `_intersection_query` 结尾（Metal 的 `intersection_query` 操作：`next`、`reset`、`commit_triangle_intersection`、candidate 与 committed 的 getter，**尚未解码**），都归 `Feature::RayTracing`。其余未解码名字留在 `Feature::UnknownIntrinsic`。

### 5.5 AIR 版本差异汇总

`KNOWN`（源码注释统计：2.0 ×6、2.1 ×3、2.2 ×6、2.5 ×6、2.6 ×2、2.7 ×15、2.8 ×20、2.9 ×22 处提及）。对实现方重要的几条：

| AIR 版本 | 变化 |
|---|---|
| < 2.0 | atomic 没有尾部 volatile flag |
| ≤ 2.1 | texture sample/gather/read **不带** residency status，sample **没有** min-LOD-clamp 位置 |
| ≥ 2.2 | 带 status（结果 `{T, i8}`），sample 带 clamp |
| 2.5 | kernel/vertex buffer setter 没有 attribute stride（`alternative()` 覆盖） |
| 2.7 | simdgroup-matrix block load/store 的旧形式；容器格式 2.7 已被观察 |
| 2.8 | barrier 是 2 操作数（无 order），atomic 无 `mem_flags` |
| **2.9** | barrier 是 3 操作数（带 order，scope 改为仅内存作用域，执行作用域由名字决定）；atomic 多一个 `mem_flags` 立即数；`frexp` 改为 `air.frexp.<T>`。deployment target macOS **27** |

`LibraryFunction::air_version` 与 `language_version` 来自容器 `VERS` 标签；`AirAbi::air_version` 来自 `!air.version`。两者都可用，但注意上游**不按版本号分支**，而是按**声明的函数类型**选形式（`classify` 逐个试 `alternative()`）。这是更稳的做法，本项目应沿用。

---

## 6. 覆盖率与缺口

### 6.1 那组统计数字的真实出处与计数单位

本项目既有文档 `docs/METAL2VULKAN_INTEGRATION.md` 第 9 节写"上游统计为 2,135 项中 958 项实现。另有 828 项缺失，349 项不在范围内"。

**真实出处** `KNOWN`：上游 `docs/METAL-COVERAGE.md` 第 11–16 行的 Totals 表。

| Status | Items | 其中 deprecated |
|---|---|---|
| implemented | 958 | 36 |
| missing | 828 | 27 |
| out of scope | 349 | 5 |
| **all** | **2135** | 68 |

**核实结果：数字抄录正确，但计数单位在本项目既有文档里完全缺失，导致它被误读。** 更正如下。

#### 计数单位是什么

`KNOWN`（`METAL-COVERAGE.md` 文首定义）：**"Every public item of the macOS 27.0 SDK (Xcode 27.0, 27A266a)'s Metal headers, by name"** —— macOS 27.0 SDK 的 Metal 头文件里**每一个按名字计的公共 API 条目**。

不是 AIR 指令，不是测试用例，不是 intrinsic。

本文对该表做了独立解析核对，2135 行中能被机械解析的 2067 行的 kind 分布为：

| kind | 条数 |
|---|---|
| property | 1011 |
| method | 774 |
| class | 152 |
| protocol | 79 |
| class method | 30 |
| function | 19 |
| category | 2 |

（余下 ~68 行是枚举等格式不同的行，未纳入本次机械解析；这与 Totals 表的 deprecated 列恰好同为 68，但**未查**二者是否同一集合。）

即：**一个 Objective-C property 算一项，一个 selector 算一项，一个 class 或 protocol 自身算一项。**

#### 三个状态的定义

`KNOWN`（`METAL-COVERAGE.md` 文首）：

- **implemented**：有对应实现回答它。注意上游明确——一个调用**仍可能**对某些输入拒绝（`REFUSALS.md` 列出设备条件），对应实现的 rustdoc 说明差异在哪。
- **missing**：还没有对应实现；size 是工作量（S ≤ 一天，M 数天，L 一周以上，XL 一个新子系统）。上游强调"一个缺失的调用不会给出错误答案：需要它的程序根本构建不起来"。
- **out of scope**：ray tracing、多 GPU、macOS 专有服务、IOSurface、drawable、源码编译 —— 由消费方拥有；以及 macOS 本身不提供的条目。

implemented 的 958 项细分 `KNOWN`：runtime 回答 635 项，translator 的 plain value（pipeline descriptor、reflection、函数常量）回答 323 项。
missing 的 828 项按工作量：S 145、M 147、L 160、**XL 376**。

#### 三条必须记住的修正

1. **分母是 macOS 27 SDK，不是 macOS 26。** 本项目目标基线是 macOS Tahoe 26.7.2（build 25G325）。26 上不存在的 API（表里标 "macOS 27" 的若干条，例如 `MTLTextureViewDescriptor.minLOD`、persistent kernels）对本项目不是缺口。反过来，26 上存在的 API 都在这 2135 项里。

2. **这组数字衡量的是 Metal API 面，不是 shader 翻译面（本分册的主题）。** AIR → SPIR-V 的覆盖率在 `REFUSALS.md`，计数单位完全不同：125 个 translator/front-end 拒绝 variant。上游**没有** AIR 指令级覆盖率表 `KNOWN`（已核对 `docs/` 下全部文档）。shader 侧的"覆盖率"只能通过三件事读出：封闭指令集（26 opcode，2.3 节）、已解码 intrinsic 族（26 个 variant，5.2 节）、未解码族（9 条前缀，5.4 节）。

3. **"958 实现"里不含 Metal 4。** 见 6.2。

### 6.2 Metal 4 时代的真实覆盖率：0

这是本次审计最重要的结论。

对 `METAL-COVERAGE.md` 做机械统计，以 `MTL4` 开头的条目 `KNOWN`：

| 状态 | 条数 |
|---|---|
| **implemented** | **0** |
| missing | 374 |
| out of scope | 100 |
| 合计 | 474 |

上游 Totals 下方的 "Missing, in build order" 表把它们归为两组 `KNOWN`：

| 组 | size | 条数 |
|---|---|---|
| Metal 4's command model | L/XL | 369 |
| machine learning encoding | XL | 18 |
| tensors | L | 68 |

拒绝码是 `RuntimeGap::Metal4Api`，拒绝说明文字是 `Metal 4's command model (MTL4CommandQueue, MTL4CommandBuffer, argument tables, the compiler)` `KNOWN`。

**结论**：如果 guest 上的 Metal 客户端走 Metal 4 的命令模型（`MTL4CommandQueue`/`MTL4CommandBuffer`/argument table/`MTL4Archive`/`MTL4MachineLearningCommandEncoder`），上游**完全不支持**。上游覆盖的是 Metal 1–3 的命令模型（`MTLCommandQueue`/`MTLCommandBuffer`/encoder）。

> **本项目含义**：这决定了本项目在 ObjC 层应该发布什么。`20-OBJC-DEVICE.md`/`21-OBJC-OBJECT-FAMILY.md` 必须明确：**不实现 Metal 4 命令模型的 protocol conformance**，让 `supportsFamily:`/能力查询把 Metal 4 路径关掉，强迫客户端走 Metal 3 路径。macOS 26 上 Metal 4 是可选的（WindowServer 与 AppKit 在 26 上仍走 Metal 3 路径）`INFERRED` —— **未查**：25G325 x86_64 的 WindowServer / SkyLight 是否使用 `MTL4*`。查清方法：在仓库已有的 `SkyLight`、`Metal` IDB 里搜 `MTL4` 类引用与 `_MTL4*` 符号。这是 `11-KERNEL-DISPLAY.md` 与本分册的共同前置项。

### 6.3 按类别的未实现与已知缺陷清单

来源：`docs/REFUSALS.md` 第 1 节（Translator and front-end refusals，`Unsupported`：一个 `Feature` 加它的 `Needs`）。上游的总计 `KNOWN`：

| 种类 | variant 数 | 有构造点 | reach system | reach app | reach rare | reach none |
|---|---|---|---|---|---|---|
| Translator / front-end 拒绝 | 125 | 125 | 6 | 32 | 70 | 17 |
| Runtime 缺口 | 70 | 70 | 1 | 8 | 45 | 16 |
| Apple-only 调用 | 5 | 5 | 0 | 0 | 0 | 5 |
| Binder 在设备限制上的拒绝 | 9 | 9 | 0 | 1 | 7 | 1 |
| 翻译上限 | 14 | 14 | 0 | 0 | 7 | 7 |
| 编译层不编译的 rate map | 5 | 5 | 0 | 0 | 4 | 1 |
| 翻译 deadline | 1 | 1 | 0 | 0 | 0 | 1 |

按 basis 的分布 `KNOWN`（basis 的定义见上游 `REFUSALS.md` 文首）：translator/front-end 的 125 项中，48 项 basis = `device`（设备缺机制），54 项 basis = `ours`（上游自己的缺口/上限/deadline），23 项 basis = `-`（尚未声明）。

下面按本项目关心的类别列出。**`ours` 标记的项是上游自己没做，对本项目就是真缺口；`device` 标记的项取决于 Lavapipe 的能力，归 `60-CAPABILITY-MATRIX.md` 与 `40-RUNTIME-VULKAN.md`。**

#### AIR 指令 / intrinsic 层

| `Feature` | 阻断什么 | basis | reach |
|---|---|---|---|
| `UnknownIntrinsic` | 封闭集合之外的 intrinsic | `ours` | **`rare`：上游明文写"AIR from a newer compiler (macOS 27 AIR 2.9)"** |
| `AgxUnmodeled` | 语义未建模的 AGX intrinsic | `ours` | `rare`：Apple 自家库的 AGX intrinsic |
| `Instruction` | 封闭指令集之外的指令记录 | `-` | `none` |
| `Constant` | 类型化模型之外的 bitcode 常量记录（block address、inline asm、`select` 等常量表达式） | `-` | `none` |
| `Type` | 类型化模型之外的类型 | `-` | `none` |
| `Attribute` | 改变调用 ABI 且 AIR 不用的 LLVM 属性（`inalloca`、`preallocated`、`byref`、`nest`、`swift*`） | `-` | `none` |
| `BitcodeRecord` | LLVM 在 `block` 里定义但类型化模型未覆盖、且没有更具体 variant 的记录 | `-` | `none` |
| `ModuleRecord` | 模块级记录（alias、ifunc、comdat …） | `-` | `none` |
| `CallingConvention` | 非 AIR 的 calling convention | `-` | `none` |
| `SyncScope` | LLVM 内建 `singlethread` 与 system 之外的同步作用域 | `-` | `none` |
| `AddressSpace` | 类型化模型未定义的 LLVM address space（见 2.5） | `ours` | `none`：Apple AGX 库的 address space |
| `StaticInitializer` | 无法求值的 static initializer | `ours` | `none` |
| `WideSwitchLiteral` | 宽于 32 位的 switch case 字面量 | `ours` | `rare` |
| **`Lowering`** | **"某个 lowering 族的指令/intrinsic/接口元素，其 lowering 尚未落地"（每个族落地时各自收窄）** | `ours` | **`system`：上游明文"the catch-all of lowering families not landed: any shader can meet one"，35 个构造点** |

**`Lowering` 是最危险的一项**：它是 catch-all，reach 标 `system`，意思是任何 shader 都可能撞上，且上游自己写明 35 个构造点。

#### shader stage

| `Feature` | basis | 状态 |
|---|---|---|
| `Tessellation` | `ours` | **未实现**（13 个构造点，含 `metal2vulkan-air/src/canon/mod.rs::post_check` 2 处）。设备侧另需 `maxTessellationGenerationLevel`、`maxPushConstantsSize`、`maxStorageBufferRange` |
| `MeshShading` | `ours` | **未实现**（7 个构造点）。另外 `pipeline/mod.rs` 明示："带 object 函数的 mesh pipeline 的 plan、object 函数的 payload 都被拒" |
| `TileShading` | `ours` | **未实现**（5 个构造点，Apple GPU family 特性） |
| `Imageblocks` | `ours` | **部分实现**：上游写"an imageblock outside the forms implemented"（10 个构造点）。多采样 imageblock 的 intrinsic 整族未解码（5.4） |
| `KernelStageIn` | `ours` | **部分未实现**："kernel stage-in combinations Metal leaves unestablished" |
| `Stage` | `-` | 模型未覆盖的 stage（见 1.8 的 `Other(n)`） |

#### 纹理与采样

| `Feature` | basis | 要点 |
|---|---|---|
| `Format` | `ours` | **120 个构造点**，reach `system`：上游明文"pixel formats a device lacks for a use (CoreVideo's 4:2:x and 10-bit formats among them)" |
| `DivergentImplicitLod` | `ours` | 通过多候选句柄的 divergent implicit-LOD 采样/LOD 查询，**未实现** |
| `ImplicitLodOutsideFragment` | `ours` | fragment 之外的 implicit-LOD 采样，**未实现** |
| `MinLodClamp` | `ours` | 无 `shaderResourceMinLod` 时的 `min_lod_clamp` |
| `SamplerBicubicFilter` | `ours` | reach `system`，上游明文："macOS 26.6.2 makes a runtime sampler with MTLSamplerMinMagFilterCubic (the consumer's boots), whose mip-filtered form is refused" |
| `SamplerBorderColor` | `ours` | Vulkan 无法表达的 border color |
| `TextureSwizzle` | `ours` | "Metal 行为未实测"的 swizzle |
| `TextureView` | `ours` | Vulkan 无法在该 image 上精确构造的 view |
| `MipmapGeneration` | `ours` | 设备上跑不了的 `generateMipmapsForTexture:` |
| `GatherExtended`、`StorageImageMultisample`、`StorageTextureInVertexStage`、`TexelOffset`、`CubeArray`、`SamplerAnisotropy`、`SamplerLodBias`、`SamplerCompare`、`SamplerAddressMode`、`TexelBuffer`、`TextureSize`、`TextureSampleCount`、`ViewFormatReinterpretation`、`SparseTexture`、`SparseTextures`、`PixelSamplerCompare` | 混合 | 多数是 `device`（Lavapipe 能力问题），归 `60` |

#### 原子与内存模型

| `Feature` | basis | 要点 |
|---|---|---|
| `Int64Atomics` | `device` | 需要设备的 64 位原子特性或 buffer device address |
| `ImageAtomics` | `device` | 32 位整数之外的 image 原子 |
| `CoherentMemory` | `device` | `coherent(device)` 访问，需 Vulkan memory model |
| `DereferenceLoadedPointer` | `device` | 解引用从内存载入或由整数构造的指针。reach **`app`**："pointers loaded from argument buffers" |
| `PointerToInteger`、`PointerCompare` | `-` | |
| `HandleAsPointer` | `ours` | 资源句柄当字节指针用，或句柄 provenance 冲突 |
| `ConstantGlobalEscaping` | `ours` | 地址逃逸的 constant 全局 |
| `ThreadgroupMemorySize` | `device` | 超设备限制的 threadgroup 内存 |
| `PrivateMemory` | `-` | 每线程私有内存超 Function 存储上限 |
| `StageStoresAndAtomics` | `device` | vertex/fragment 里的 store/atomic，需对应 Vulkan 特性 |
| `Int64Arithmetic`、`Float64Arithmetic` | `device` | |

#### 函数常量

| `Feature` | basis | 要点 |
|---|---|---|
| `FunctionConstantArgument` | `ours` | "被函数常量谓词移除的指针入口参数被观察到被读" —— 除了 absent buffer（读作 null）与另一例外。**未实现** |

此外 `Error::NeedsInput` 机制 `KNOWN`：缺少的 pipeline 输入（函数常量值、stage-input 或 vertex descriptor、storage texture 的格式）是 `Error::NeedsInput`，**问出来，绝不猜**。

#### argument buffer

| `Feature` | basis | 要点 |
|---|---|---|
| `ArgumentBufferPointers` | `device` | argument buffer 里装 buffer pointer（dynamic root），需 buffer device address。reach **`app`** |
| `ArgumentBufferTextures` | `ours` | argument buffer 里装 texture 或 sampler（handle domain），**16 个构造点**。reach **`app`：bindless** |
| `ArgumentBufferObjects` | `ours` | argument buffer 成员是 pipeline state、ICB、function table 或 acceleration structure。**未实现** |

> **本项目含义**：argument buffer tier 2（bindless）是 `ArgumentBufferTextures`，reach `app`，`ours`。这意味着上游在部分设备上能做，部分不能。`60-CAPABILITY-MATRIX.md` 必须据 Lavapipe 的 descriptor indexing 能力判定。

#### indirect command buffer

| `Feature` | basis | 要点 |
|---|---|---|
| `GpuEncodedIndirectCommands` | `ours` | kernel 编码的 ICB，**17 个构造点**，需 buffer device address |

CPU 侧编码的 ICB 是实现了的（`indirect_commands.rs` 54KB、`bind/replay.rs` 97KB、`bind/indirect_commands.rs`），`bind::indirect_commands` 是公开模块。

#### binary archive

`METAL-COVERAGE.md` 的 missing 表 `KNOWN`：`more binary archive entries`，size S，4 项（`MTLBinaryArchive.addMeshRenderPipelineFunctionsWithDescriptor:error:`、`addLibraryWithDescriptor:error:`、`addFunctionWithDescriptor:library:error:` 等）。即 binary archive **部分实现**，缺 4 个入口。

#### dynamic library 与函数指针

| `Feature` | basis | 要点 |
|---|---|---|
| `DynamicCall` | `ours` | 间接调用、函数指针、visible/intersection function table。**9 个构造点**，"every device (no Vulkan mechanism); every device (not implemented)" |
| `Recursion` | `ours` | 递归（4 个构造点，含 `canon/recursion.rs::dynamic_alloca`） |
| `Linking` | `ours` | linkage signature / stitching / dynamic library（3 个构造点） |
| `DirectCall` | `ours` | inliner 吃不下的已定义函数调用（variadic、byval） |

注意一个矛盾点需要本项目澄清：`REFUSALS.md` 说 `Linking` 拒绝 dynamic library，但 `pipeline/descriptor.rs` 的 `DynamicLibraries` 有完整的 install name 搜索实现，`cache/key.rs` 把搜索到的每个库记进 key，并有 `engine_dynamic_libraries.rs`（24KB）测试。`INFERRED`：`Feature::Linking` 拒的是 **linkage signature / stitching**，而 dynamic library 的**静态内联链接**是实现了的；`canon/link.rs`（71KB）与 `canon/devirt.rs`（106KB）支撑这一点。**未查**：具体哪些 dynamic library 形式被拒。查清方法：读 `canon/link.rs::not_implemented` 与 `canon/mod.rs::post_check` 的拒绝条件。

#### ray tracing

| `Feature` | basis | 要点 |
|---|---|---|
| `RayTracing` | `ours` | 12 个构造点。reach 标注 `rare: ray tracing (out of scope by ruling)` |
| `IntersectionFunctionTable` | `ours` | 9 个构造点，同样 out of scope |

`METAL-COVERAGE.md` 把 ray tracing 整类划入 out of scope（349 项的主要来源）。但 AIR 前端**能解析** `air.intersect`（5.2 节），`lower/raytracing/`（60KB + 27KB）也有代码。`INFERRED`：部分落地但按裁定不交付。

> **本项目含义**：Lavapipe 没有 ray tracing，这项对本项目就是明确的 out of scope，不需要补。

#### 其它值得单列的 `ours` 项

| `Feature` | 要点 |
|---|---|
| `SimdgroupMatrix` | **未实现**（`lower/simd/matrix.rs::not_implemented`）。注意 AIR 前端能解析（5.2），只是 lowering 没做 |
| `Tensors` | **未实现**（2 个构造点）。Metal 4 的 shader tensor；AIR 前端有 `tensor_ops.rs` 与 `canon/matmul2d/` |
| `RasterizationRateMap` | **未实现**（`lower/fragment/mod.rs::select`）。另有第 6 节 "Rate maps the compile layer does not compile" 5 个 variant |
| `FramebufferFetch` | **24 个构造点**，reach **`system`**。上游明文："macOS 26.6.2's login reaches it (two WindowServer and RenderBox pipelines fetch RGB10A8_2P_XR10 attachments, the consumer's boots)" |
| `RasterOrderGroups` | `ours`，需 fragment shader interlock |
| `VertexAmplification`、`LayeredRendering`、`Barycentrics`、`StencilExport`、`SampleRateShading`、`PrimitiveId`、`PixelCoverageAtSampleRate` | 多数混合 `ours`/`device` |
| `HostMemory` | `newBufferWithBytesNoCopy:`，reach `system` |
| `ProgramScopeBinding` | MSL 3.2 的 program-scope buffer binding（4.2 节） |

### 6.4 本项目最严重的三个缺口（结论）

按 reach × basis × 本项目路径的交叉判断：

1. **`Feature::Lowering`（catch-all，reach `system`，`ours`，35 个构造点）**。上游自己说任何 shader 都可能撞上。这不是一个特性缺口，是"多个 lowering 族尚未落地"的总开关。本项目无法事先枚举它会在哪里触发，只能靠 corpus 审计（7.3 节）在真实 guest metallib 上扫。

2. **`Feature::FramebufferFetch`（reach `system`，`ours`，24 个构造点）**。上游明确记录 macOS 26.6.2 的登录流程会撞上它：两条 WindowServer 与 RenderBox 的 pipeline 会 fetch `RGB10A8_2P_XR10` attachment。本项目的目标就是让 WindowServer 合成起来，这一项直接挡在 Gate 上。

3. **Metal 4 命令模型 0 覆盖（474 项，374 missing + 100 out of scope）**，以及 `Feature::Format`（120 个构造点，reach `system`，上游点名 CoreVideo 的 4:2:x 与 10-bit 格式）。前者决定 ObjC 层必须把客户端挡回 Metal 3；后者决定 Lavapipe 的格式支持面是硬约束。

次一级但必须排期的：`ArgumentBufferTextures`（bindless，reach `app`）、`DereferenceLoadedPointer`（reach `app`，argument buffer 里的指针）、`Tessellation`/`MeshShading`/`TileShading` 三条 stage 未实现。

### 6.5 typed refusal 机制

`KNOWN`（`docs/ARCHITECTURE.md` "Typed refusals" 段；`crates/metal2vulkan/src/error/mod.rs` 124KB；`crates/metal2vulkan-air/src/error.rs` 42KB）。

#### 错误分类

| 错误 | 含义 | 是否瞬态 |
|---|---|---|
| `Error::Unsupported` | 设备无法精确运行的输入。**命名 Metal 特性，以及什么条件下能翻译**（`Feature` + `Needs`/`Capability`） | 否（永久） |
| `Error::NeedsInput` | 缺少一个 pipeline 输入（函数常量值、stage-input 或 vertex descriptor、storage texture 格式、`LinkedFunction`、`DynamicSymbol`、`DynamicLibrary`、`ObjectPayload`）。**问出来，绝不猜** | 否 |
| `Error::LimitExceeded(Limit)` | 确定性上限 | 否 |
| `Error::NotImplemented(RuntimeGap)` | runtime 缺口（70 个 variant） | 否 |
| `Error::Metal(MetalError)` | "调用做错了什么"：一个 `Problem`，转发到 9 组 problem 枚举（共 64 + 164 个 variant） | 否 |
| `Error::AppleOnly` | Apple 独有调用（5 个） | 否 |
| `Error::RateMap(UnpinnedCompile)` | 编译层不编译的 rate map（5 个） | 否 |
| `Error::Internal` | **翻译器 bug，绝不是输入错误**。kind 含 `Verify`、`RequirementsExceedProfile` | 否 |
| `Error::Budget` | 超过 deadline | **是** |
| `Error::Cancelled` | 被取消 | **是** |

上游明示：**只有 `Budget` 与 `Cancelled` 是瞬态**。其余都是永久的，`Error::is_permanent_for` 控制失败编译能否被 memo（`cache/mod.rs`）。

`compile_stage` 跑在 `catch_unwind` 里 `KNOWN`（`ARCHITECTURE.md`），所以核心的 panic 变成 `Error::Internal`，**绝不**把 unwind 抛给调用方。这对本项目很重要：Rust panic 不会穿过 C ABI 边界。

#### 怎么读出"因为什么功能被拒"

`KNOWN`：`Error::Unsupported` 的载荷是 `Unsupported { feature: Feature, needs: Needs }`（air crate 侧是 `error::Unsupported`，有构造器 `Unsupported::not_implemented(Feature)`）。`Feature` 是一个 `#[non_exhaustive]` 枚举，variant 名就是 6.3 节表里的那些（`Feature::Tessellation`、`Feature::AddressSpace(u32)`、`Feature::LibraryKind(u8)` 等）。`Needs` 表达"缺什么机制"：

- `Needs::NotImplemented` —— 在**每个**设备上都拒（上游自己没做）；
- `Needs` 的 capability 形式 —— 命名设备缺的 Vulkan feature / extension / property / limit / format usage。词表在 `crates/metal2vulkan/src/device/requirements.rs`（`VkFeature`、`VkExtension`、`VkProperty`、`VkLimit`、format usage，全部 `#[non_exhaustive]`，"新消费一项就是追加一行"）。

因此读法是：**匹配 `Feature` variant 得到"哪个 Metal 功能"，匹配 `Needs` 得到"是上游没做还是设备不行"。** 这正是 `REFUSALS.md` 的 Where 列与 Basis 列的来源。

#### 映射成 Metal 客户端可见的错误

上游**不提供**这层映射 `KNOWN`：`METAL-COVERAGE.md` 把 `NSError` 的构造算在消费方。本项目必须自己写。建议的映射规则（`INFERRED`，待 `21-OBJC-OBJECT-FAMILY.md` 定稿）：

| 上游错误 | Metal 客户端可见行为 | 理由 |
|---|---|---|
| `Unsupported` / `NotImplemented` / `AppleOnly` / `RateMap` | `newXPipelineStateWithDescriptor:error:` 返回 `nil` + `NSError`，domain `MTLLibraryErrorDomain` 或 `MTLCommandBufferErrorDomain`，`localizedDescription` 带 `Feature` 名与 `Needs` | Metal 对不支持的 pipeline 就是返回 nil + error |
| `NeedsInput` | **本项目的 bug，不是客户端的**：客户端已经提供了 descriptor，缺的输入必须由本项目从 descriptor 里补全。应当在胶水层断言而不是透传 | 上游明示 "asked for and never guessed" |
| `LimitExceeded` | 返回 `nil` + `NSError`；若发生在 encode 期则置 `MTLCommandBufferError` | |
| `Metal(MetalError)` | **客户端 API 误用**。上游对每个 variant 都要求一行 `Basis:` 说明"相信 Metal 自己也拒绝这个输入"的依据。应按 Metal 的行为处理：API validation 级别的用 `NSAssert`/日志，`NSError` 级别的返回 error | 上游 `REFUSALS.md` 第 8/9 节；basis 分布：`metal-measured` 20+57、`metal-documented` 3+27、`metal-takes` 5+23、`unknown` 8+26 |
| `Metal` 且 basis = **`metal-takes`** | **已知缺陷**：上游明文"measured: plain Metal **takes** this input, so the refusal reaches past Metal. An open defect"。共 5 + 23 项。本项目必须对这些单独记录并上报上游 | 这是 pass-through 会出错的地方 |
| `Internal` | **翻译器 bug**。记日志 + 落 repro bundle，返回 `nil` + error；绝不静默 | |
| `Budget` / `Cancelled` | **可重试**。本项目应退避重试一次，仍失败则按 `Internal` 处理 | 唯一的瞬态类 |

> **行动项**：basis = `metal-takes` 的 28 项是上游承认的、比 Metal 更严格的拒绝。这些会让本来能跑的客户端跑不起来。`60-CAPABILITY-MATRIX.md` 必须逐项列出。**未查**：这 28 项具体是哪些。查清方法：读上游 `docs/REFUSALS.md` 第 8、9 节，筛 Basis 列为 `metal-takes` 的行；或跑 `python3 scripts/refusal-surface/refusal_surface.py` 重新生成。

### 6.6 精度与 fast path，以及本项目在哪里选 exact

来源：`docs/FAST-PATHS.md`（142 KB）、`pipeline/artifact.rs`（`PrecisionNote`、`Reconvergence`、`SpecializedNote`、`SpecClause`、`SpecTest`）、`device/policy.rs`（`DevicePolicy`）。

#### 上游的三条原则

`KNOWN`（`FAST-PATHS.md` 文首）：

1. **GPU 的原生算术就是契约。** 设备有原生形式的运算（`float`/`half` 算术与函数、NaN 位、min/max、rounding、texel 与颜色转换、sampler 与 filter、resolve），那个形式**就是唯一的形式**；没有路径去模拟 Metal 的位。设备缺的才实现或模拟。
2. **精度记录是日志，绝不致命。** 每个与 Metal 的差异记进 pipeline artifact 的 `PrecisionNote`，runtime 在创建 pipeline state 时以 `metal2vulkan-degrade-<code>` 宣告一次。工作继续跑；只有 Metal 自己拒绝的才终止。
3. 每一行要么是"用速度换精确性的 fast default + 它的 exact 开关"，要么是"设备缺口（无开关可给）"。

文档分五节 `KNOWN`：`Fast defaults`（第 25 行）、`Not speed choices: device gaps`（第 48 行）、`Accuracy switches whose default is Metal's`（第 93 行）、`Costs of matching Metal`（第 108 行）、`Known gaps`（第 314 行）。

#### 差异记录机制

| 类型 | 位置 | 含义 |
|---|---|---|
| `PrecisionNote` | `StageModule::precision_notes: Vec<PrecisionNote>` | 该 stage 有意偏离精确 Metal 语义的地方。`enum PrecisionNote` 的 variant 例：`F16FmaDoubleRounding`、`F16IntConvDoubleRounding`、`NativeTranscendentals`、`NativeDivision`、`NativeFma`、`NativeDot`、`NativeMix`、`DeviceArithmetic`、`DeviceColorConversion`、`BicubicFilterArithmetic`、`FastMathRewrites`、`FunctionStorageAssumed`、`HeapTextureCompressed`、`GroupedCompletion`、`DrawDroppedStillMaking`、`DispatchDroppedStillMaking` |
| `SpecializedNote { note, when: Vec<SpecClause> }` | `StageModule::specialized_notes` | 只在**某些特化**下成立的 note：仅当模块按 specialization constant 选到那条 arm 时才偏离（绑定格式的 class = `SpecKey::TexelFormat`，绑定 sampler 的 word = `SpecKey::SamplerState`）。按 note 排序，每个 note 至多一条 |
| `Reconvergence` | `StageModule::reconvergence` | `Guaranteed`（最大 reconvergence，或没有 tangled 操作依赖它）/ `ImplementationDefined`（该 profile 下发散后的 reconvergence 由实现定义） |
| degrade code | runtime 宣告 | `metal2vulkan-degrade-<code>`，稳定码。`docs/API.md` 第 9 节逐个列出，并有测试强制该文档列齐 |

读 note 的 API `KNOWN`（`pipeline/artifact.rs`）：

- `StageModule::precision_notes_under(&SpecializationKey) -> Vec<PrecisionNote>` —— 给定 pipeline 的特化下实际成立的 note。key 没给的常量读它的默认值，空 key 给出默认特化的 note。
- `StageModule::precision_notes_bound(&SpecializationKey, &dyn Fn(SpecKey) -> Option<u64>)` —— 再加上 draw/dispatch 绑定的值（stage 作为数据读取的 key，即 `PushField::Specialized`，不进 pipeline key）。
- `StageModule::note_clauses_under` / `note_clauses_bound` / `bound_format_clauses` —— 取某个 note 成立的具体 clause。
- `BindingPlan::specialized_value(SpecKey) -> Option<u64>` —— 该 plan 绑定的资源给某个 key 的值，喂给 `precision_notes_bound`。

**一条重要的保守规则** `KNOWN`（`clause_holds` 的注释）：stage 没声明、`bound` 也没给的常量的 test **视为成立**。即 note 的报告是保守的（宁可多报）。

#### exact 开关

`KNOWN`：开关在 `DevicePolicy`（runtime 侧是 `DeviceOptions::policy`）。`DevicePolicy::exact_answers()` **一次打开全部**。上游有测试 `tests::fast_paths` 强制：任何 `DevicePolicy` 精度选项、它的取值、或某个 fast default 记录的 note，若没写进 `FAST-PATHS.md` 就失败；反之 `FAST-PATHS.md` 命名了不存在的 policy 值也失败。

已确认的 fast default 与开关（`FAST-PATHS.md` 第一张表，`KNOWN`）：

| 开关 | fast 默认 | exact 值 | 影响 |
|---|---|---|---|
| `half_chains` | `HalfChainPolicy::AtExits` | `EachOperation` | 无 `shaderFloat16` 的设备上，`half` 加减乘链在 `float` 精度下保持不 round，只在值离开链时 round（store、output、转换、比较、call、phi、vector move、没有 `contract`+`reassoc` 的运算）。exact 形式每个运算都 round 到 `half` |
| `heap_compression` | `HeapCompressionPolicy::Compressed` | `Uncompressed` | heap 里 Metal 无损压缩的颜色纹理在某些驱动上可能把 texel 存在别处。实测代价：ANV 上一个 2048² `RGBA8Unorm` render target 的 clear pass 26.9 µs vs 676 µs |
| `completion` | `CompletionPolicy::Grouped` | `Exact` | 一个队列上就绪的 command buffer 批合并成一次 `vkQueueSubmit`（最多 4 个，只有最后一个 signal timeline）。影响：除最后一个外，每个 command buffer 的完成被观察到的时刻晚 0.1–0.2 ms/批 |
| `batch_order` | `BatchOrderPolicy::Ends` | `Exact` | 批的末尾加一个 barrier 把它的工作排在同队列后续全部命令之前。上游实测在 ANV/RADV/NVIDIA 上**无任何答案差异** |
| `host_page_textures` | `HostPageTexturePolicy::InPlace` | `Shadow` | 宿主页面上只采样/读取的纹理直接 alias 那些页做 linear image。上游明示这是"对只依赖文档化 Vulkan 行为的一次有意、有范围的例外，由 owner 裁定" |
| `pipeline_waits` | `PipelineWaitPolicy::Bounded`，`pipeline_creation_wait = 4.5 s`，`pipeline_commit_wait = 4.5 s` | `Exact` | 超时还没编好的 pipeline，其 draw/dispatch 在那个 command buffer 里**什么都不画/不写**。上游实测 M2 Pro 冷启动最长一次编译 11.59 s |

#### 本项目应在哪些地方选 exact

目标形态是 CPU 渲染（Lavapipe），且第一要务是"桌面能起来、WindowServer 合成正确"，不是帧率。据此逐项判定（`INFERRED`，依据是上面各行的实测代价与本项目的目标）：

| 开关 | 本项目选择 | 理由 |
|---|---|---|
| `pipeline_waits` | **`Exact`** | 这是本项目必须改的一项。`Bounded` 下超时的 draw**静默不画**，上游自己记录"guest 的菜单栏画了一半就停在那里"。在一个靠 VNC 截图做验收的测试管线里，静默丢 draw 会把每个 bug 都伪装成渲染错误。Lavapipe 的编译比 GPU 驱动慢，4.5 s 更容易被超。代价是创建线程被占住，但第一版同进程、无 IPC，可接受 |
| `batch_order` | **`Ends`**（保持默认） | 上游实测无答案差异，纯开销 |
| `completion` | **`Exact`** | 本项目第一版只有一个队列、无 host import 压力，`Grouped` 的收益（减少 execbuffer ioctl）在 Lavapipe 上不存在（没有内核提交）。而完成时刻变晚会让 `80-TEST-HARNESS.md` 的"等 command buffer 完成再截图"变得不确定 |
| `heap_compression` | **不适用** | 该行的条件是 `DriverFact::CompressedImagesHideAliasedWrites`（ANV）。Lavapipe 不在其列，两个取值等价。保持默认 |
| `host_page_textures` | **`Shadow`（exact）** | `InPlace` 依赖一次运行时驱动探测，其结论存进 shader cache 目录。本项目第一版不应引入"行为取决于一次探测结果"的不确定性。Lavapipe 是 CPU 渲染，shadow 的拷贝代价远小于 GPU 情形 |
| `half_chains` | **`AtExits`**（保持默认） | Lavapipe 是否报 `shaderFloat16` 未定。若不报，`EachOperation` 会给每个 half 运算加一条 `OpQuantizeToF16`，上游实测 fixture 的 SPIR-V 字数从 121,270 涨到 131,766（1,024 → 2,464 条 quantize）。CPU 渲染下指令数直接等于时间。桌面合成对 half 精度不敏感 |

另外两项**不是开关、必须记录**：

- `Reconvergence::ImplementationDefined`：若 Lavapipe 不报 maximal reconvergence，所有带 tangled 操作（simd/quad/barrier）的 shader 都会是这个值。`60-CAPABILITY-MATRIX.md` 需要确认 Lavapipe 的 `VK_KHR_shader_maximal_reconvergence`。**未查**。
- `PrecisionNote::NativeTranscendentals` 等"设备缺口"类：无开关，Lavapipe 的 `sin`/`exp`/`pow` 就是答案。桌面合成可接受。

---

## 7. 扩展与维护方法

### 7.1 从 metallib 字节到 SPIR-V 的完整 pass 流水线

`KNOWN`（`docs/ARCHITECTURE.md` "The pipeline"）。每一阶段的入口符号与文件：

| # | 阶段 | 产物 | 入口符号 / 模块 |
|---|---|---|---|
| 1 | **parse** | `Library`：容器的函数表 | `air::container::parse`（`metal2vulkan-air/src/container/mod.rs`）；translator 侧 `library::Library::parse`（`metal2vulkan/src/library/mod.rs`） |
| 2 | **decode** | 类型化 AIR 模块 + 其 ABI + decode-only `PointeeTable` | `air::bitcode::decode` / `decode_with`（`bitcode/decoded.rs`）；底层 `air::bitstream::Reader`、`air::bitcode::decode_module`（`bitcode/module.rs`）；ABI `air::abi::decode`（`abi/mod.rs`）；intrinsic `air::intrinsics::classify`/`bind`；IR `air::ir` |
| 3 | **specialize** | 一个已内联的 `Entry`：函数常量烘进去、常量传播、linked function 解析、pointee 擦除 | `air::specialize` / `specialize_linked` / `specialize_dynamic`（`metal2vulkan-air/src/lib.rs`）→ `air::canon::specialize*`（`canon/mod.rs`） |
| 4 | **analyze** | `MemoryPlan`：provenance、每个值一种表示、slot window | `metal2vulkan/src/memory/`（`plan.rs`、`provenance.rs`、`handles.rs`、`leaf.rs`、`arena.rs`、`roots.rs`） |
| 5 | **select** | `Plan`：每条指令与每个接口元素一个策略、push-constant 放置、requirements、输出大小估计（在此校验） | `metal2vulkan/src/lower/select.rs`、`lower/strategy.rs`、`lower/push.rs`、`lower/estimate.rs` |
| 6 | **structurize** | AIR CFG 上的结构化树 | `metal2vulkan/src/structurize/`（`mod.rs`、`cfg.rs`、`loops.rs`、`regions.rs`、`tree.rs`、`emit.rs`） |
| 7 | **emit** | 通过 builder 生成的类型化 SPIR-V 模块 | `structurize::emit`、`lower/*` 各族、`spirv::builder`（`spirv/builder/module.rs`、`function.rs`、`constructs.rs`、`ops/*`） |
| 8 | **tidy** | 单赋值提升、死值移除、大 entry 的重复区域 roll 成循环 | `structurize::promote`、`spirv::dead`、`spirv::roll` |
| 9 | **verify** | 完整 verifier；requirements 必须落在 profile 内 | `spirv::verify`（`verify/mod.rs`、`cfg.rs`、`rules.rs`）、`spirv::requirements` |
| 10 | **serialize** | SPIR-V 1.5 words + 类型化 relocation | `spirv::serialize`（`serialize/mod.rs`） |
| = | | `CompiledFunction`，key 是 `FunctionCompileKey`，调用方可缓存 | `library/compiled.rs` |
| 11 | **link** | binding、`Location`、spec id、pipeline layout、pipeline 级限制、生成的 geometry stage | `pipeline::link`（`pipeline/link/mod.rs` 系列：`graphics.rs`、`geometry.rs`、`varyings.rs`、`vertex.rs`、`mesh.rs`、`tessellation/`、`contract.rs`） |
| 12 | **relocate** | 各 stage 的最终 words | `pipeline::relocate`（`pipeline/relocate.rs`） |
| = | | `ComputePipeline` / `RenderPipeline` / tile 与 mesh pipeline | `pipeline/artifact.rs` |
| 13 | **bind** | `BindState` → `BindShape` → `BindingPlan` → dispatch/draw 命令 | `bind/`（`state.rs`、`plan.rs`、`instantiate.rs`、`dispatch.rs`、`graphics.rs`） |

单 stage 的编排入口是 `pipeline::compile::compile_stage` `KNOWN`：它跑 decode → serialize，**只保留可 relocate 的模块与 plain metadata**；解码的 AIR、plan、类型化模块在返回前全部丢弃。跑在 `catch_unwind` 里。

#### 三条跨阶段的不变量

`KNOWN`（`ARCHITECTURE.md`）。本项目在扩展时必须遵守：

1. **每个阶段把合法的类型化输入映射到合法的类型化输出。** 没有哪个阶段产出一种"后面的阶段再修"的形式，也**没有任何代码解析 SPIR-V words 来决定发什么**。
2. **`select` 之后不再改变函数包含哪些指令**，除了 tidy pass（保语义）。link 与 relocate 只往 serializer 预留的槽里写字面数字（descriptor set 与 binding、`Location`、`SpecId`），所以**一个编译好的函数可以被它链接进的每条 pipeline 复用**。
3. **每个特性与设备只有一种表示，在 emit 之前就选定。** `select` 从 AIR 与 device profile 决定每个策略。**没有重试、没有候选模块、没有把 validator 放进循环**。一个族处理不了的输入就拒绝它。

另外 `KNOWN`：库**不跑任何外部工具** —— 自己的 bitcode reader，自己的 verifier。只有命令行用 `llvm-as` 读 `.ll` 输入、用 `spirv-val` 做独立复核。

### 7.2 新增一条 AIR 指令支持需要改哪几个地方

下面给出具体文件与扩展点。分两种情形。

#### 情形 A：新增一条 `air.*` intrinsic

1. **族的名字语法与 variant**
   `crates/metal2vulkan-air/src/intrinsics/<family>.rs`。选对族（`math.rs`/`convert.rs`/`atomic.rs`/`texture.rs`/`simd.rs`/`matrix.rs`/`sync.rs`/`stage.rs`/`objects.rs`/`mesh.rs`/`intersect.rs`/`llvm.rs`）。
   - 数学族与 simd 族有**声明式表**：`math.rs::TABLE`、`simd.rs::OPS`。加一行即可。
   - 其它族要加 enum variant + `parse` 分支。
2. **顶层分派**
   `intrinsics/mod.rs::AirIntrinsic::parse` 的 `or_else` 链（若是新族才需要动），以及 `AirIntrinsic::signature`、`AirIntrinsic::bind`、`AirIntrinsic::alternative`（如有多形式）的 match 臂。
3. **类型化 signature**
   族文件里的 `signature()` 方法，用 `intrinsics/sig.rs` 的 `Signature`/`Operand`/`HandleKind`。
   - `Operand::Imm` 标出立即数位置（`bind` 会读它们）。
   - `Operand::Handle` 与 `Signature::ret_handle` 标出句柄位置 —— **这是 memory provenance 格的种子，漏标会导致资源访问被误判**。
   - 操作数形状复杂的族用 `intrinsics/layout.rs::Layout` 给每个位置一个命名 role。
4. **若暂不实现语义**：加进 `intrinsics/mod.rs::UNDECODED`（前缀 + 理由），需要类型化拒绝时再加进 `UNDECODED_FEATURES`（前缀 + `Feature`）。这样调用会以具体 feature 被拒而不是 `UnknownIntrinsic`。
5. **路由到 lowering**
   `crates/metal2vulkan/src/lower/select.rs::route_air`（以及 `route`）。这里把 `AirIntrinsic` variant 映射到策略。
6. **lowering 本体**
   `crates/metal2vulkan/src/lower/<family>/`：`arith/`（含 `math.rs`、`narrow.rs`、`wide.rs`、`extended_range/`、`libm/`）、`access/`、`texture/`、`sampler/`、`simd/`、`sync/`、`fragment/`、`stage_io/`、`dispatch.rs`、`tessellation/`、`mesh/`、`raytracing/`。
7. **SPIR-V 构造**
   若需要新的 SPIR-V 指令：`crates/metal2vulkan/src/spirv/builder/ops/<group>.rs`（`arith.rs`、`atomic.rs`、`composite.rs`、`convert.rs`、`geometry.rs`、`glsl.rs`、`group.rs`、`image.rs`、`memory.rs`、`mesh.rs`、`misc.rs`、`ray.rs`）。opcode 与 enumerant 在 `src/spv.rs`（由 `scripts/regen-spirv-grammar/` 从 Khronos grammar 生成，**不手写**）。
8. **requirements**
   `crates/metal2vulkan/src/spirv/requirements/mod.rs`：capability 与 extension 由模块内容**推导**，绝不由 lowering 写入。若用到新的 Vulkan 特性，在 `crates/metal2vulkan/src/device/requirements.rs` 追加 `VkFeature`/`VkExtension`/`VkProperty`/`VkLimit` 的一行。
9. **verifier 规则**
   `crates/metal2vulkan/src/spirv/verify/rules.rs`（若新指令有结构约束，如 convergent、atomic pointer）。
10. **解释器**（仅测试用，但覆盖 compute lowering 的正确性）
    `crates/metal2vulkan/src/spirv/interp/`：`eval.rs`（标量/向量求值）、`glsl.rs`、`image.rs`、`group.rs`、`memory.rs`、`deriv.rs`、`sched.rs`。
11. **测试**
    - 族级 parse/signature 测试：`intrinsics/families_tests.rs`、`intrinsics/tests.rs`
    - fixture：`crates/metal2vulkan-validation/fixtures/public/`（`.ll`/`.air.ll`/`.metal`/`.spvasm`），并 bless `crates/metal2vulkan/tests/public_fixture_expectations_engine.tsv`
    - 端到端：`crates/metal2vulkan/tests/engine_*.rs` 里对应的文件
    - golden hash：bless `crates/metal2vulkan/tests/golden_hashes.tsv`
12. **版本**
    `crates/metal2vulkan/src/cache/mod.rs::SEMANTICS_VERSION`（当前 1929）**必须 +1**，因为同一个 key 下的输出变了。若 artifact 编码也变了，`ARTIFACT_FORMAT_VERSION`（当前 479）同样 +1。
13. **文档**
    若新增了 fast default 或 exact 开关，必须在 `docs/FAST-PATHS.md` 加行（`tests::fast_paths` 强制）。若新增了拒绝，跑 `python3 scripts/refusal-surface/refusal_surface.py` 重生成 `docs/REFUSALS.md`，并给拒绝的 doc comment 加 `Basis:` 行（`tests/refusal_surface.rs` 强制）。

#### 情形 B：新增一条 LLVM 指令（扩展封闭指令集）

1. `crates/metal2vulkan-air/src/ir/inst.rs`：`enum Opcode` 加 variant，`enum InstKind` 加对应形状。
2. `crates/metal2vulkan-air/src/bitcode/function.rs::record`：加记录码解码（当前有 8 个 `Feature::Instruction` 构造点在这里）。记录码常量在 `bitcode/codes.rs`。
3. `crates/metal2vulkan-air/src/ir/verify.rs`：加校验规则。
4. `crates/metal2vulkan-air/src/ir/print.rs`：加打印（golden printout 在 `tests/air_input/`）。
5. `crates/metal2vulkan-air/src/canon/`：若新指令影响 SCCP（`sccp.rs`）、常量折叠（`fold.rs`）、内联（`inline.rs`）、devirt（`devirt.rs`）、speculation（`speculate.rs`），逐个处理。
6. 之后同情形 A 的第 5–13 步。

#### 情形 C：新增一个 metadata key（最可能的 macOS 版本升级场景）

1. `crates/metal2vulkan-air/src/abi/keys.rs`：`enum Key` 加 variant，并在 `KEYS` 测试表加一行（测试 `key_spellings_round_trip_and_are_unique` 强制 enum 与拼写双向一致）。
2. `crates/metal2vulkan-air/src/abi/args.rs`：在接受它的 role 的解析里加 key 处理（arity、值类型）。
3. `crates/metal2vulkan-air/src/abi/mod.rs`：若是新 role 或新属性，加到 `ParamRole`/`OutputRole`/`Builtin`/`Member` 的模型里。
4. `crates/metal2vulkan-air/src/abi/check.rs`：加与 IR 的交叉校验。
5. 若是新的**命名 metadata 列表**：`abi/module.rs` 的 `enum Named` 与常量 `NAMED`。
6. 若该 key 合法但暂不实现：按 `air.global_bindings` 的先例，在 `abi/module.rs::decode` 里以 `Unsupported(Feature::<Name>)` 拒绝，**不要**让它落到 `UnknownKey`。这样拒绝信息才有用。
7. 之后同情形 A 的第 5–13 步。

### 7.3 测试与验证设施，以及本项目要复用哪些

来源：`docs/VALIDATION.md`、`CONTRIBUTING.md`、`docs/ARCHITECTURE.md` "Checks"。

#### 上游的验证梯级

`KNOWN`（`ARCHITECTURE.md` 的 Checks 表）：

| 检查 | 抓什么 | 本项目复用 |
|---|---|---|
| clippy，warning 当错误 | 警告与常见缺陷 | **是**，直接进 CI |
| 单元与集成测试 | 构造与 lowering 回归 | **是** |
| **always-on verifier**（release 也跑） | 非法模块 | **是**，这是免费的；见下 |
| `spirv-val`（测试与命令行） | 非法模块（独立复核） | **是**，但只在 CI，不在产品路径 |
| **解释器测试**（`spirv::interp`） | 错误的 compute lowering、越界访问、不终止 | **部分**，见下 |
| fixture 清单（`tests/public_fixture_expectations_engine.tsv`） | 某个 fixture 在某个 committed profile 上停止编译或开始拒绝 | **是**，但需要本项目自己的 Lavapipe profile |
| **golden output hash**（`src/tests/golden_hashes.rs`） | 非预期的输出变化 | **是**，这是吸收后防止自己改坏的主要闸门 |
| 在 Metal 与 Vulkan 上跑 authored case 并比对 | 与 Metal 答案不同 | **不可用**，见下 |
| release 模式下有界的 corpus 翻译 | 真实 AIR 上的时间、内存与覆盖率 | **是，这是本项目最该复用的一项** |

#### 内建 verifier 查什么

`KNOWN`（`ARCHITECTURE.md` "Validity by construction"）。**在任何 word 离开 crate 之前，release 构建里也跑**，查：

- ownership
- SSA dominance
- 结构化控制流与规范循环（canonical loop）
- convergent 指令
- atomic pointer
- 无环调用图
- stage 规则
- 记录的 interface 与 requirements
- profile 的规则

违反是 `Error::Internal`（kind `Verify`）：**翻译器 bug，绝不是输入错误**。

另外三条 by-construction 的保证 `KNOWN`：

- builder 的类型化构造器检查操作数与结果类型；storage-class 规则按构造成立；`if_`/`switch_`/`loop_` 是唯一的 construct 开启者，各由自己的 scope 闭合，所以 construct 一定正确嵌套。
- 类型**连同其布局一起 intern**，所以一个类型唯一，且其显式布局是 key 的一部分。
- capability 与 extension 由模块内容**推导**，绝不由 lowering 写入，且必须落在 profile 内（否则 `Error::Internal`，kind `RequirementsExceedProfile`）。
- serializer 写逻辑布局并按顺序密集编号 result id，所以**相等的模块给出相等的 words**。任何不确定的东西（如 hash map 顺序）都到不了输出。

> **本项目含义**：输出确定性是免费得到的。`80-TEST-HARNESS.md` 可以把"同一 metallib + 同一 profile → 同一 SPIR-V SHA-256"作为硬断言。

#### golden hash 怎么用

`KNOWN`（`CONTRIBUTING.md` "Golden output hashes and SEMANTICS_VERSION"）：

- `src/tests/golden_hashes.rs` 对**每个公共 fixture 入口点 × 每个 committed profile** 钉住最终 SPIR-V 的 hash（或拒绝的 class），表在 `crates/metal2vulkan/tests/golden_hashes.tsv`。
- 表里**只记 cell，不记版本**。`SEMANTICS_VERSION` 单独 bump 不改表。
- 在 `development` 分支上 bless 时，若某 cell 在 fixture 与 profile 都没变的情况下移动了，而 `SEMANTICS_VERSION` 还是上次 bless 时的值，**bless 会拒绝**。这是强制 bump 的机制。
- bless 命令（需 macOS，因为要 `xcrun metal-as`）：
  ```
  cargo nextest run -p metal2vulkan --all-features \
    --run-ignored ignored-only -E 'test(bless_golden_hashes)'
  ```
- **绝不手工合并表**：merge 之后取 `development` 的表重新 bless。

> **本项目的问题**：bless 需要 macOS + `xcrun metal-as`。本项目的开发机是 Windows。**行动项**：要么在目标 guest（macOS）里跑 bless，要么把 `.air.ll` fixture 预编译成 `.metallib` 提交进仓库，让 bless 不需要 `metal-as`。后者更可行，归 `70-BUILD-PACKAGE.md`。

#### 解释器

`KNOWN`（`spirv/interp/`，18 KB mod + 37 KB eval + 51 KB sched 等）。`spirv::interp` 是一个 CPU 解释器，**只在测试里用**。它抓：错误的 compute lowering、越界访问、不终止。

本项目**部分复用**：它只覆盖 compute（`GLCompute`）。桌面合成是 render pipeline。但对 blit/resolve 的 helper kernel（上游有几十个：`astc_decode`、`etc_decode`、`ycbcr_convert`、`mipmap_filter`、`color_resolve` …）它很有价值。

#### corpus audit 怎么用

`KNOWN`（`docs/VALIDATION.md`；`crates/metal2vulkan-validation` 的 bin 列表）。上游的 corpus 工具链：

| 二进制 | 作用 |
|---|---|
| `corpus-harvest` | 采集 |
| `corpus-index` | 建索引（可恢复的分片索引） |
| `corpus-status` | 完成度状态 |
| **`corpus-triage`** | **有界的、可恢复的、按索引分片的审计**，给出 completion / read / time 三个摘要 |
| `corpus-pipeline` | 按 pipeline 维度 |
| `corpus-vulkan` / `corpus-metal` / `corpus-moltenvk` | 在三个 venue 上跑 |
| `corpus-case-check` | 单 case 检查 |
| `corpus-draw-ab` | draw 级 A/B |
| `command-replay` | 命令重放 |
| `format-scout` | 格式探查 |

`VALIDATION.md` 的证据梯级明确 `KNOWN`："A corpus-wide support or performance claim → A resumable indexed `corpus-triage` audit, with its completion, read and time summaries"。即**任何"覆盖率"级别的论断都必须用 `corpus-triage` 跑出来**，不能靠读代码推断。

另外 `intrinsics/mod.rs` 提到 `bitcode-reader` 审计有一个 **intrinsic census**：它报告每个未知名字及其行数。这正是本项目需要的工具 —— 把 25G325 x86_64 的全部系统 metallib 喂进去，就能得到真实的未知 intrinsic 清单。

> **本项目必须做的第一件事**（`80-TEST-HARNESS.md` 的输入）：
> 1. 从 25G325 x86_64 的 installed SystemOS 抽出全部 `*.metallib`（`/System/Library/Frameworks/**`、`/System/Library/PrivateFrameworks/**`、`/System/Library/Extensions/*/Contents/Resources/**`、`/System/Library/GPUBundles/**`），建成私有 corpus。
> 2. 跑 intrinsic census，得到未知 `air.*` 名字 + 行数。
> 3. 跑 `corpus-triage`，得到每条 metallib 的"能编/拒绝/拒绝原因"分布。
> 4. 把 `Feature::Lowering`（6.4 节第一缺口）与 `Feature::FramebufferFetch`（第二缺口）在真实样本上的命中率量出来。
>
> 这是把 6.4 节的三个缺口从"上游自述"变成"本项目实测"的唯一途径。

#### 设备测试的安全机制（复用）

`KNOWN`（`VALIDATION.md` "Device tests and GPU safety"）。上游的理由：**一个永不终止的 shader 会在进程被杀之后继续占住 GPU，而卡死的 GPU 能挂死宿主**。机制：

- 设备测试只在 cfg 下编译（不是 feature，因为 gate 用 `--all-features` 构建）：`--cfg m2v_cpu_icd`（只用 CPU ICD：lavapipe、SwiftShader）或 `--cfg m2v_gpu`（真 GPU）。两者互斥。
- 设备选择是**参数**，无默认：`--device-type cpu|gpu`。`cpu` 只匹配 CPU 设备，**绝不回退到 GPU**。
- 所有宿主对设备工作的等待走 `src/gpu/wait.rs`，默认 10 秒；`--gpu-wait-timeout SECONDS` 可提高。等待出现在别处是测试失败。
- **hang tripwire**：等待超时或提交以 device fault 结束时，进程写 `~/.cache/m2v-gpu/hang`（JSON：跑了什么、在什么上、何时），**不释放任何东西**，以 86 退出。该文件存在期间**每一次 GPU 打开都被拒绝**；CPU 设备从不检查它。

> **本项目含义**：本项目的目标就是 CPU ICD（Lavapipe），所以 `--cfg m2v_cpu_idc` 这条路径正是我们要用的，而且 CI 已经在 Linux 上以 `LP_NUM_THREADS=1` 跑它 `KNOWN`。**直接复用**：`80-TEST-HARNESS.md` 应沿用 `--device-type cpu` + 有界 wait + tripwire 三件套，因为 guest 里 Lavapipe 死循环会拖死 WindowServer。

#### 生成式文档的检查（必须保留）

`KNOWN`（`CONTRIBUTING.md` "Generated docs"）。四份文档由测试强制：

| 文档 | 生成器 | 强制测试 |
|---|---|---|
| `docs/REFUSALS.md` | `python3 scripts/refusal-surface/refusal_surface.py`（`--check` 校验） | `crates/metal2vulkan/tests/refusal_surface.rs`，且 runtime 的每个 `Problem` variant 的 doc comment 必须以 `Basis:` 行结尾 |
| `docs/METAL-COVERAGE.md` | `python3 scripts/metal-coverage/coverage.py` | `crates/metal2vulkan-validation/tests/integration/metal_coverage.rs`（校验表里命名的每个对应实现确实存在），以及总计表 |
| `docs/CONFORMANCE-COVERAGE.md` | `python3 scripts/conformance-coverage/coverage.py` | 生成器自检 |
| `docs/FAST-PATHS.md` | 手工维护（是 ledger，原地编辑，不留历史） | `tests::fast_paths` |
| `docs/API.md` | 手工 | 必须列齐每个 degrade code 及其 category，且逐字引用 `examples/api_preview.rs` |
| `crates/metal2vulkan/tests/api_signatures.tsv` | `python3 scripts/api-signatures/signatures.py --bless` | `tests/api_signatures.rs`；**删掉或改掉一行就是已发布 crate 的破坏性变更** |

> **本项目必须保留全部这些检查。** 吸收之后本项目成为维护方，这些是唯一能防止"改一处、悄悄坏一片"的机制。特别是 `api_signatures.tsv`：它把 public surface 钉死，是本项目 ObjC 胶水层的 ABI 稳定性保障。

### 7.4 吸收方案

#### 许可证

`KNOWN`：`GPL-2.0-or-later OR LGPL-3.0-or-later`（`LICENSE`、`Cargo.toml` 的 `workspace.package.license`、每个已发布 crate 的副本）。三份文本在根目录：`LICENSE-GPL-2.0`、`LICENSE-LGPL-3.0`、`LICENSE-GPL-3.0`（LGPL v3 引用 GPL v3 的条款）。

上游明确接受条件 `KNOWN`（`CONTRIBUTING.md`）："Contributions are accepted under the same dual license: a change you submit can be redistributed and modified under either."

本项目的处理（与 `00-OVERVIEW.md` 4.6 一致）：

1. **选定一个**。建议 **GPL-2.0-or-later**：本项目是开源的，且内核侧 kext 与 OpenCore 生态也在 GPL 世界里；LGPL 的"允许替换并重新链接"义务对一个随 guest 交付的 Metal plugin bundle 很难满足（bundle 由 Metal.framework 加载，用户无法替换其中的 Rust 渲染核心）。
2. 保留全部版权声明与三份 license 文本。`metal2vulkan` 的作者署名是 `Anees Iqbal <hello@aneesiqbal.ai>`（`Cargo.toml` `workspace.package.authors`）。
3. 对 Mesa 与 LLVM 另立逐组件许可证清单（归 `70-BUILD-PACKAGE.md`）。

#### fork 策略：保留 git 历史

**结论：用 `git subtree`，不用 `git submodule`，不用 vendor 目录。**

理由：

| 方案 | rebase 上游 | 本地可改 | 离线构建 | 单仓 CI | 判定 |
|---|---|---|---|---|---|
| submodule | 好 | 需要第二个仓库 | 需要额外 clone | 麻烦 | 否 |
| **subtree** | **好**（`git subtree pull`） | **好**（直接改，在本仓提交） | **好** | **好** | **选它** |
| vendor 目录（丢历史） | 差（只能人工 diff） | 好 | 好 | 好 | 否 |
| 打散揉进自有模块 | 不可能 | — | — | — | `00-OVERVIEW.md` 4.6 明令禁止 |

落地步骤：

```
# 一次性
git remote add m2v-upstream https://github.com/steelbrain/metal2vulkan
git fetch m2v-upstream master
git subtree add --prefix=third_party/metal2vulkan m2v-upstream master
# 记录基线
#   commit 219f01365dc4c8eb346816c405b5b17403793764  2026-10-29

# 后续同步上游
git fetch m2v-upstream master
git subtree pull --prefix=third_party/metal2vulkan m2v-upstream master
```

规则：

1. **本项目的改动一律是独立 commit，commit message 前缀 `[m2v]`**，便于 `git subtree pull` 时识别冲突来源。
2. **优先把修复提给上游**。上游仍在演进且完成度有限（`CHANGELOG.md` 标 0.2.0 unreleased），本项目的修复若被上游接受，下次 pull 就自动消掉一个本地 patch。
3. **本地 patch 必须有清单**：`third_party/metal2vulkan/PATCHES.md`，每条记 commit SHA、改了什么、为什么、是否已提给上游。这是 `00-OVERVIEW.md` 第 7 节证据规则的延伸。
4. **不改 public API**，除非同时改 `tests/api_signatures.tsv` 并记入 `PATCHES.md`。

#### Rust 版本要求

`KNOWN`：`rust-toolchain.toml` channel `1.98.1`；`workspace.package.rust-version = "1.98"`。上游明示该 channel 就是已发布 crate 承诺的 MSRV，所以"普通构建就是在检查这个承诺"，提升它是"一次刻意的、全舰队的动作"。

本项目的处理：

- **保留 `rust-toolchain.toml` 不动**。本机 cargo 1.99.1 会自动下载 1.98.1。理由：上游注释里记录了一次事故 —— 不固定 channel 导致"三个只存在于更晚 Rust 的 lint 被报成 development 坏了"。
- 本项目自己的 crate（ObjC 胶水的 Rust 侧、IOSurface 桥、测试管线）可以用更新的 toolchain，但**必须能与 1.98 编译的 metal2vulkan 链接**。这意味着 `third_party/metal2vulkan` 要么是独立 workspace（推荐），要么本项目整体降到 1.98。
- **决定：`third_party/metal2vulkan` 保持为独立 workspace**（它自带 `[workspace]` 根 `Cargo.toml`），本项目通过 path 依赖引用。这样两个 toolchain 可以并存，且 `git subtree pull` 不会和本项目的 workspace 成员表冲突。

#### 依赖清单

`KNOWN`（`Cargo.toml` 的 `[workspace.dependencies]`）。被一个以上 crate 使用的外部依赖，各一个版本：

| crate | 版本 | 说明 |
|---|---|---|
| `ash` | `0.38`，`default-features = false` | Vulkan 绑定。**构建期绝不带 loader**；需要打开 loader 的 crate 自己加 `loaded` feature |
| `libc` | `0.2` | |
| `serde` | `1`，features `["derive"]` | |
| `serde_json` | `1` | |
| `sha2` | `0.11`，`default-features = false` | 走 CPU 自身的 SHA 指令（ARMv8 SHA2 扩展、x86 SHA-NI），运行期检测。不使用默认的 `alloc` 与 `oid` feature |

各 crate 自己的依赖未在此列（需要时读各 `crates/*/Cargo.toml`）。**未查**：完整的传递依赖树与各自许可证。查清方法：`cargo tree -p metal2vulkan -p metal2vulkan-air -p metal2vulkan-runtime --all-features --edges normal` 加 `cargo license`，归 `70-BUILD-PACKAGE.md`。

#### 哪些 crate 进产品，哪些只是工具

`KNOWN`（`README.md` 的 crate 表；`Cargo.toml` 的 members）：

| crate | 已发布 | 进本项目产品 | 用途 |
|---|---|---|---|
| `metal2vulkan` | 是 | **是** | 翻译器。Metal 形状的 API（device、library、pipeline descriptor、binding plan），为一个被描述的 Vulkan 设备编译 compute/render/tessellation/tile/mesh pipeline |
| `metal2vulkan-air` | 是 | **是**（被 `metal2vulkan` 精确 pin `=0.x.y`） | AIR 前端。独立可用，适合"读 AIR 而不翻译"的工具 |
| `metal2vulkan-runtime` | 是 | **是** | Metal API on Vulkan。device、command queue/buffer、encoder、buffer、texture、heap、pipeline state、event，通过 `ash` 跑在 Vulkan 设备上。**只用翻译器的 public API** |
| `metal2vulkan-validation` | **否** | **否，只做工具** | authored case + corpus 审计。本项目的 corpus 审计要用它（7.3 节） |
| `metal2vulkan-devtools` | **否** | **否，只做工具** | 外部工具 runner 与 fixture 组装器，测试共用 |
| `metal2vulkan-conformance` | 否（README 未列） | **否** | 一致性套件。`docs/CONFORMANCE-COVERAGE.md` 的来源 |

feature 选择 `KNOWN`（`README.md`）：`metal2vulkan` 的三个 feature，库本身一个都不需要：

- `serde`：API 的 plain-data 值的序列化。**本项目需要**（artifact 要落盘缓存，`BindingPlan::content_digest` 也要 `serde`）。
- `ash`：到 `ash::vk` 的双向转换，以及 `DeviceDescription::query`（从 physical device 读）。**本项目需要**（要从真实 Lavapipe 设备读 profile，不想维护手写 JSON）。
- `cli`：`metal2vulkan` 命令（隐含打开 `serde`）。**本项目只在开发期需要**，不进产品。

运行期要求 `KNOWN`：库**不跑任何外部工具**。runtime 在运行期打开 Vulkan loader，需要一个 **Vulkan 1.2** 设备。

#### 构建闭环（本项目 CI 应跑的）

`KNOWN`（`CONTRIBUTING.md` "The loop"）。全部不打开设备：

```
cargo fmt --all
cargo clippy --workspace --all-targets --all-features -- -D warnings
RUSTDOCFLAGS='-D warnings' cargo doc --workspace --all-features --no-deps
scripts/api-docs
cargo nextest run -p metal2vulkan -p metal2vulkan-air -p metal2vulkan-runtime -p metal2vulkan-devtools --all-features
cargo nextest run -p metal2vulkan-validation --all-features
cargo test --workspace --all-features --doc
```

外部工具（测试与验证用，库不用）`KNOWN`：`llvm-as`（LLVM ≥ 21，读 `.ll` fixture）、`llvm-dis`、`spirv-val`、`spirv-as`、`xcrun metal-as`（macOS，读 `.air.ll` fixture；其他平台的测试会 skip）、`spirv-cross`（检查 MoltenVK 会写出的 MSL；缺失时打 `SKIPPED`，`METAL2VULKAN_TEST_REQUIRE_SPIRV_CROSS=1` 使缺失成为失败）。各自从 `PATH` 或 `METAL2VULKAN_<TOOL>` 环境变量找。

`cargo-nextest` 是必需的（`cargo install cargo-nextest --locked`）。

---

## 8. 本项目待查清单

按 `00-OVERVIEW.md` 第 7 节第 4 条，"没查"不等于"被阻断"。以下每条都给出查清方法。

| # | 事项 | 为什么重要 | 查清方法 |
|---|---|---|---|
| 1 | 25G325 x86_64 的 WindowServer / SkyLight 是否使用 `MTL4*` | 决定本项目是否必须实现 Metal 4 命令模型（上游 0 覆盖） | 仓库里已有 `SkyLight.i64`、`Metal.i64`：搜 `_OBJC_CLASS_$_MTL4*` 引用与 `MTL4` 选择器。若无引用则 Metal 4 不是阻断项 |
| 2 | 25G325 x86_64 的系统 metallib 是否出现 `addrspace(5)` | 5 号 address space 是真实空洞，命中即整模块被拒 | 抽全部系统 metallib，跑 `metal2vulkan-air::decode`，统计 `Feature::AddressSpace` |
| 3 | `Feature::Lowering` 在真实 guest metallib 上的命中率 | 6.4 节第一缺口，catch-all，上游自称 reach `system` | 建私有 corpus，跑 `corpus-triage`，按 `Feature` 分组统计 |
| 4 | `Feature::FramebufferFetch` 的实际命中条目 | 6.4 节第二缺口，上游点名 macOS 26.6.2 登录流程会撞 | 同上；重点看 WindowServer 与 RenderBox 的 metallib，确认那两条 `RGB10A8_2P_XR10` pipeline |
| 5 | 未知 `air.*` intrinsic 的真实清单 | 决定情形 A 扩展的排期 | 跑 `bitcode-reader` 审计的 intrinsic census |
| 6 | basis = `metal-takes` 的 28 项具体是哪些 | 这是上游承认"比 Metal 更严格"的拒绝，会让本来能跑的客户端跑不起来 | 读上游 `docs/REFUSALS.md` 第 8、9 节，筛 Basis 列；或跑 `refusal_surface.py` |
| 7 | 哪些 dynamic library 形式被 `Feature::Linking` 拒绝 | 6.3 节记录了一处表面矛盾（descriptor 层有完整实现，但 REFUSALS 说拒） | 读 `canon/link.rs::not_implemented` 与 `canon/mod.rs::post_check` 的条件 |
| 8 | Lavapipe 是否报 `VK_KHR_shader_maximal_reconvergence` | 决定 `Reconvergence` 是 `Guaranteed` 还是 `ImplementationDefined`，影响所有带 simd/quad/barrier 的 shader | 在目标构建的 Lavapipe 上跑 `vulkaninfo`，或用 `DeviceDescription::query` 导出 profile JSON |
| 9 | Lavapipe 是否报 `shaderFloat16` | 决定 `half_chains` 开关是否生效 | 同上 |
| 10 | Core Image 的 AIR（`!air.ci`）在本项目链路上的归属 | guest 的 CoreImage 一定会提交带 `!air.ci` 的 metallib。上游能解析但明示"本模块的翻译不读它" | 在 corpus 里找 `!air.ci` 模块，看它们是作为 kernel 入口被编译还是只被 CoreImage 自己的运行时消费。若是后者，本项目可能需要在 ObjC 层另立 CoreImage 路径 |
| 11 | metallib 2135 项表里未被机械解析的 ~68 行是什么 kind | 影响 6.1 节计数单位的完整性（并非关键） | 读 `scripts/metal-coverage/coverage.tsv` 的 kind 列全集 |
| 12 | 完整传递依赖树与各依赖许可证 | 分发前的许可证清单 | `cargo tree --all-features --edges normal` + `cargo license`，归 `70-BUILD-PACKAGE.md` |
| 13 | 25G325 x86_64 上 `MTLDynamicLibrary::serializeToURL:` 是否也产 `0xCBFEBABE` | 影响容器解析是否必须支持 universal 形式 | 在目标 guest 上调用并看前 4 字节 |
| 14 | golden hash bless 在非 macOS 上的可行方案 | 本项目开发机是 Windows，bless 需要 `xcrun metal-as` | 把 `.air.ll` fixture 预编译成 `.metallib` 提交，或在目标 guest 里跑 bless |

### 8.1 明确**不是**阻断项的

按 `00-OVERVIEW.md` 第 7 节第 4 条澄清，避免被误标 `BLOCKED`：

- **AIR 格式本身不是阻断项。** 本文第 1–5 节已从上游源码整理出可实现级别的格式说明。不需要 Apple 文档，不需要逆向 Metal 编译器。
- **ray tracing 不是阻断项。** Lavapipe 没有 ray tracing，`METAL-COVERAGE.md` 已把它整类划入 out of scope。
- **Metal 4 的 ML encoding（18 项 XL）不是阻断项。** 桌面合成不走它。
- **tensor（68 项 L）不是阻断项。** 同上。
- **private metadata 的内容不是阻断项。** 上游不读它，本项目也不需要读。

---

## 9. 与其他分册的接口

| 本分册给出 | 消费方 |
|---|---|
| 容器与 ABI 解析规格（第 1–4 节） | `31-PIPELINE-ARTIFACT.md`（artifact 字段的语义根源）、`22-OBJC-DESCRIPTORS.md`（descriptor 字段如何映射到 AIR 的 slot 与函数常量） |
| stage 签名约定（第 3 节） | `21-OBJC-OBJECT-FAMILY.md`（`MTLFunctionType` 的回答）、`22-OBJC-DESCRIPTORS.md` |
| 覆盖率与缺口（第 6 节） | `60-CAPABILITY-MATRIX.md`（全量矩阵的"上游支持"列）、`IMPLEMENTATION_ROADMAP` 的排期 |
| `Feature`/`Needs` 到 `NSError` 的映射规则（6.5 节） | `21-OBJC-OBJECT-FAMILY.md`（必须落实为具体的 `NSError` domain 与 code） |
| exact 开关的选择（6.6 节） | `40-RUNTIME-VULKAN.md`（`DevicePolicy` 的构造） |
| 测试设施复用结论（7.3 节） | `80-TEST-HARNESS.md`（corpus 审计是它的第一个输入） |
| 吸收方案（7.4 节） | `70-BUILD-PACKAGE.md`（subtree 布局、toolchain、依赖） |
| 待查清单（第 8 节） | `90-EVIDENCE-INDEX.md`（每条查清后的证据归档） |
