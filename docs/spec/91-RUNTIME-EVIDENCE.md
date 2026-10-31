# 91 运行证据：第一批 `TESTED`

文档版本：1.0
基线日期：2026-10-30
上级文档：`docs/spec/00-OVERVIEW.md`
配套分册：`docs/spec/90-EVIDENCE-INDEX.md`（静态样本索引）

## 0. 本文作用

`90-EVIDENCE-INDEX.md` 索引静态样本。本文索引**运行证据**。

在本文之前，本项目的 `TESTED` 标签数量为零，全部结论来自静态分析。本文记录第一批在真实 macOS 26 x86_64 上执行代码得到的结果。

采集手段：GitHub Actions 的 `macos-26-intel` 运行器。workflow 在 `.github/workflows/evidence-macos26-intel.yml`，产出的分析脚本在 `tools/ci/`。

### 0.1 证据分级：为什么这里的 `TESTED` 带一个限定

采集平台是 **macOS 26.6.1 (25G76)**，项目目标是 **macOS 26.7.2 (25G325)**。两者是同一大版本的不同点版本。因此本文引入一个比 `00-OVERVIEW.md` 第 7 节更细的标签：

| 标签 | 含义 |
|---|---|
| `TESTED(25G76)` | 在 26.6.1 上实测通过。对 25G325 是**强证据但不是终证**：ABI、类布局、协议条目数在点版本间通常不变，但不保证 |
| `TESTED` | 在 25G325 上实测通过。**本文仍然没有任何这一级的结论** |

内核版本的接近程度（`KNOWN`）：

| | 25G325（目标） | 25G76（运行器） |
|---|---|---|
| `ProductVersion` | 26.7.2 | 26.6.1 |
| xnu | `12377.161.15.701.48`（`LC_SOURCE_VERSION`） | `12377.161.13~4`（`uname -a`） |

同一 `12377.161` 系，补丁号差 2。

---

## 1. 最重要的一条：运行器本身就跑着 AppleParavirtGPU

`TESTED(25G76)`。`MTLCopyAllDevices()` 在 `macos-26-intel` 运行器上返回**一个** device：

```
name       = Apple Paravirtual device
class      = AppleParavirtDevice
superchain = MTLIOAccelDevice -> _MTLDevice -> NSObject
registryID = 4294968049
```

进程内加载的镜像里有：

```
/System/Library/Extensions/AppleParavirtGPUMetal.bundle/Contents/MacOS/AppleParavirtGPUMetal
/System/Library/PrivateFrameworks/IOAccelerator.framework/Versions/A/IOAccelerator
```

`/System/Library/Extensions/` 下 7 个 Paravirt 件全部在位：`AppleParavirtGPU.kext`、`AppleParavirtGPUIOGPUFamily.kext`、`AppleParavirtGPUMetal.bundle`、`AppleParavirtGPUMetalIOGPUFamily.bundle`、`AppleParavirtIOSurface.kext`、`AppleM2ScalerParavirtDriver.kext`、`AppleVideoToolboxParavirtualization.kext`。

**这件事改变了本项目的取证条件。** `00-OVERVIEW.md` 把 APV 定位为"规格书"，此前只能静态读它的二进制。现在有一台免费、可随时重建、**SIP 已关闭**的机器，上面跑着这份规格书的活实例，而且它的 Metal 栈就是我们要替换的那一层。

运行器环境（`TESTED(25G76)`）：

| 项 | 值 |
|---|---|
| `sw_vers` | macOS 26.6.1 / 25G76 |
| `uname` | Darwin 25.6.0, xnu-12377.161.13~4, RELEASE_X86_64 |
| CPU | Intel Core i7-8700B @ 3.20 GHz（Coffee Lake-H，CPUID model `0x9E`） |
| **SIP** | **disabled** |
| GPU | Apple Paravirtual device（即运行器是 KVM/Virtualization.framework guest） |

CPU 这一项顺带给 `72-CPU-COMPAT.md` 一条印证：`0x9E` 正是 `72` 第 2.3 节表里映射到 `CPUFAMILY_INTEL_KABYLAKE` 的 model，与 `MacBookPro16,1` 同 model。

---

## 2. 核对结果：22 条断言过了 20 条

脚本 `tools/ci/summarize_objc_dump.py` 对分册里的承重断言逐条核对。

### 2.1 通过的（`TESTED(25G76)`）

| 分册 | 断言 | 实测 |
|---|---|---|
| `20` §0.1 | 类名是 `MTLIOAccelDevice`，无前导下划线 | ✅ 存在 |
| `20` §0.1 | `_MTLDevice` 是它的父类，两者是不同的类 | ✅ `superchain = [_MTLDevice, NSObject]` |
| `21` | `MTLDeviceSPI` required == **427** | ✅ 427 |
| `21` | `MTLDeviceSPI` optional == **80** | ✅ 80 |
| `21` | 合计 **507** | ✅ 507 |
| `21` | 七个 `MTLIOAccel*` 节点（device/queue/command buffer/buffer/texture/pooled/heap） | ✅ 7/7 全在 |
| `20` §接入点 | 5 个协议外虚方法在 `_MTLDevice` 上 | ✅ 5/5 全在 |
| `20` §接入点 | 那 5 个方法**不在任何协议里** | ✅ 25 个协议全查，零泄漏 |
| `20` | `AppleParavirtDevice` 有 **71** 个 IMP | ✅ 71 |
| `20` | APV `argumentBuffersSupport` == 0（Tier1） | ✅ 0 |
| `60` | `supportsFamily(Metal4)` 必须 false | ✅ False |
| `10` | `getMaxResourceSize` 的 1 GiB 硬下限 | ✅ `maxBufferLength = 1073741824`，正好 1 GiB |
| `32` §3 | plugin 导出 36 个 `AIRNT*` + 4 个 `MTLCompiler*` | ✅ 精确命中，全表见第 4 节 |
| `32` | `llvmVersion` 必须 32023 | ✅ 工具链自报 `metalfe-32023.883` |
| `32` | 版本门只认 3802/3902/32023/32024 | ✅ 磁盘上并存 `Versions/32023` 与 `Versions/32024` |
| `32` | `MTLCompiler` 的 init 形态 | ✅ `initWithTargetData:cacheUUID:pluginPath:device:compilerFlags:` |
| `30` §2 | metallib 容器魔数 `MTLB`，头 0x58 字节 | ✅ 见第 3 节 |
| `30` §2 | TLV 标签 `NAME`/`TYPE`/`HASH` | ✅ 字节流中确认 |
| `30` §3 | `float3` 占 16 字节、对齐 16 | ✅ 编译器接受 `static_assert` |
| `30` §2 | `0x0B17C0DE` wrapper 形式 | ✅ 见第 3 节 |

### 2.2 证伪的（规格要改）

**类名错了四处。** `21` 分册说 encoder 与 state 走 `_MTL*` 抽象层，state 侧对了，**encoder 侧的类名是编的**：

| 分册里写的类名 | 实测 | 说明 |
|---|---|---|
| `_MTLRenderCommandEncoder` | **不存在** | 但 `_MTLParallelRenderCommandEncoder` 存在（size=232，im=28，ivar=20） |
| `_MTLComputeCommandEncoder` | **不存在** | |
| `_MTLBlitCommandEncoder` | **不存在** | |
| `_MTLBuffer` / `_MTLTexture` / `_MTLEvent` | **不存在** | 资源侧真实链是 `MTLIOAccelBuffer -> MTLIOAccelResource -> _MTLResource -> _MTLAllocation -> _MTLObjectWithLabel` |
| `MTLLibraryBuilder` / `MTLLibraryDataWithArchive` | **不存在** | `20`/`32` 说 metallib 解析在这两个类里，名字是错的 |

**本轮发现了两个分册没记录的类**，它们在真实继承链上：

| 类 | instance size | 作用 |
|---|---:|---|
| `_MTLObjectWithLabel` | — | 几乎所有 Metal 对象的根（在 `NSObject` 之上） |
| `_MTLAllocation` | — | 资源与 pipeline state 的共同父类 |
| `MTLIOAccelResource` | — | `MTLIOAccelBuffer` / `Texture` / `PooledResource` 的共同父类 |
| `_MTLResource` | — | `MTLIOAccelResource` 的父类 |

即资源族的真实层数比 `21` 分册画的多两层。

### 2.3 新发现（分册没有的）

| 发现 | 影响的分册 |
|---|---|
| `MTLCompiler` 有**第二个** init：`initWithTargetData:cacheUUID:pluginPath:device:compilerFlags:fallbackDeviceFeatureProfile:` | `32`。`fallbackDeviceFeatureProfile` 是新参数，与 `20` 分册的 `featureProfile = 10000` 直接相关 |
| **APV 不声明任何 GPU family**：`supportsFamily(Mac2)` = **False**，`Apple9` = False，`Metal3` = False，`Metal4` = False | `60`。此前只确证 Metal 4 必须 false；现在知道参考实现连 `Mac2` 都报 false |
| `hasUnifiedMemory` = False，`isLowPower` = False，`isHeadless` = False，`isRemovable` = False | `20` |
| `_MTLDevice` 有 **702** 个实例方法、64 个 ivar、instance size 712 | `21` |
| `MTLIOAccelDevice` instance size **54424**；`AppleParavirtDevice` **54784**（差 360） | `20`。APV 自己只加了 360 字节、12 个 ivar |
| `libMTLIGCCompilerPlugin.dylib` 的字符串里有 **`FlatBuffers 1.12.0`** | `32` §8。FlatBuffers 依赖与版本确证 |
| plugin 另导出 6 个无前缀别名：`_GetFunctionId`、`_GetVertexFunctionId`、`_GetFragmentFunctionId`、`_GetComputeFunctionId`、`_GetObjectFunctionId`、`_GetMeshFunctionId` | `32` §3。40 个符号之外还有这 6 个 |
| `MTLCompiler.framework/Versions/32023/Libraries/` 目录存在 | `32`。厂商 plugin 可能在这里，上一轮的 `find` 深度不够没进去 |

### 2.4 协议条目数全表（`TESTED(25G76)`）

| 协议 | required | optional | 继承 |
|---|---:|---:|---|
| `MTLDeviceSPI` | **427** | **80** | `MTLDevice` |
| `MTLDevice` | 137 | 2 | `NSObject` |
| `MTLRenderCommandEncoder` | 131 | 0 | `MTLCommandEncoder` |
| `MTLCommandBuffer` | 39 | 0 | `NSObject` |
| `MTLComputeCommandEncoder` | 39 | 0 | `MTLCommandEncoder` |
| `MTLTexture` | 36 | 3 | `MTLResource` |
| `MTLRenderPipelineState` | 26 | 0 | `MTLAllocation`, `NSObject` |
| `MTLCommandQueueSPI` | 25 | 22 | `MTLCommandQueue` |
| `MTLBlitCommandEncoder` | 24 | 2 | `MTLCommandEncoder` |
| `MTLFunctionSPI` | 23 | 0 | `MTLFunction` |
| `MTLCommandBufferSPI` | 21 | 36 | `MTLCommandBuffer` |
| `MTLHeap` | 21 | 0 | `MTLAllocation` |
| `MTLComputePipelineState` | 18 | 0 | `MTLAllocation`, `NSObject` |
| `MTLLibrary` | 14 | 0 | `NSObject` |
| `MTLResource` | 14 | 0 | `MTLAllocation` |
| `MTLFunction` | 13 | 0 | `NSObject` |
| `MTLResourceSPI` | 12 | 1 | `MTLResource` |
| `MTLBuffer` | 11 | 0 | `MTLResource` |
| `MTLCommandQueue` | 11 | 0 | `NSObject` |
| `MTLCommandEncoder` | 8 | 0 | `NSObject` |
| `MTLDrawable` | 6 | 0 | `NSObject` |
| `MTLIOCommandQueue` | 5 | 0 | `NSObject` |
| `MTLSharedEvent` | 5 | 0 | `MTLEvent` |
| `MTLEvent` | 3 | 0 | `NSObject` |
| `MTLFence` | 3 | 0 | `NSObject` |

**`MTLDevice` 本身只有 137 required。** 要实现的 507 条里 370 条来自 `MTLDeviceSPI` 自己。

---

## 3. metallib 容器格式核对

`TESTED(25G76)`。七个自写 shader（`tools/ci/shaders/`）用 `xcrun metal` + `xcrun metallib` 编译，**全部零错误零警告**（七个 `.log` 均为 0 字节）。

`.air` 的头 8 字节全部是：

```
dec0170b 00000000
```

即小端 `0x0B17C0DE`。**这确证 `30` 分册第 2 节列出的四种容器输入形式里，`xcrun metal -c` 产出的裸 `.air` 是 `0x0B17C0DE` wrapper 形式，不是裸 `BC C0DE`。**

`.metallib` 的头（以 `basic.metallib` 为例）：

```
00000000: 4d54 4c42 0180 0200 0900 0081 1a00 0000  MTLB............
00000010: 551c 0000 0000 0000 5800 0000 0000 0000  U.......X.......
00000020: f800 0000 0000 0000 5801 0000 0000 0000  ........X.......
00000030: 2d00 0000 0000 0000 8501 0000 0000 0000  -...............
00000040: 1000 0000 0000 0000 9501 0000 0000 0000  ................
00000050: c01a 0000 0000 0000 0200 0000 7c00 0000  ............|...
00000060: 4e41 4d45 0700 765f 6d61 696e 0054 5950  NAME..v_main.TYP
00000070: 4501 0000 4841 5348 2000 6f27 e220 c11c  E...HASH .o'. ..
```

逐项确证 `30` 分册第 2 节：

| 断言 | 实测 |
|---|---|
| 魔数 `MTLB` | ✅ 偏移 0 |
| 头 0x58 字节 | ✅ 偏移 0x18 的 8 字节是 `58 00 ...`，即头长字段 = 0x58，且 TLV 区从 0x60 开始 |
| TLV 标签 `NAME` | ✅ 偏移 0x60，后跟 2 字节长度 `07 00` 与 7 字节 `v_main\0` |
| TLV 标签 `TYPE` | ✅ 紧随 `NAME` |
| TLV 标签 `HASH` | ✅ 长度 `20 00` = 32 字节，即 SHA-256 |
| 版本字段 | `01 80 02 00` + `09 00 00 81`，偏移 4..0xB |

七个语料的函数数与体积：

| 语料 | `.air` | `.metallib` | 函数 |
|---|---:|---:|---|
| `basic` | 4,112 | 7,253 | 2（`v_main`, `f_main`） |
| `float3_layout` | 4,640 | 4,766 | 1 |
| `compute_atomic` | 5,920 | 8,909 | 2 |
| `simd_group` | 4,976 | 5,100 | 1 |
| `texture_sampler` | 8,080 | 13,507 | 3 |
| `fbfetch` | 4,560 | 13,032 | 4 |
| `argbuf` | 6,448 | 13,343 | 3 |

**`float3_layout.metal` 的 `static_assert` 全部通过**，即编译器自己确认了：`sizeof(float3) == 16`、`alignof(float3) == 16`、`sizeof(packed_float3 + float) == 16`、`sizeof(float3 + float) == 32`、`sizeof(half3) == 8`。这把 `30` 分册第 3 节的 `v96:128:128` data layout 断言从静态推断变成编译器确认。

**`fbfetch.metal` 零错误通过**，含三附件 fetch（`float4`/`float4`/`half4` 的 `[[color(0..2)]]` 输入）与显式 depth 写出。即 framebuffer fetch 的 MSL 侧形态确认可用，`60` 分册点名的那个上游缺口的输入端已有语料。

---

## 4. compiler plugin 的导出符号全表

`TESTED(25G76)`。来源：`/System/Volumes/Data/System/Library/Extensions/AppleIntelGraphicsShared.bundle/Contents/MacOS/libMTLIGCCompilerPlugin.dylib`（Intel 的 plugin，作为 APV plugin 的替代样本，与 `32` 分册第 1 节的决定一致）。

4 个 `MTLCompiler*`（`32` 分册第 3 节的四件套，全部命中）：

```
_MTLCompilerCreate
_MTLCompilerDelete
_MTLCompilerBuildRequestWithSerializedBitcode
_MTLCompilerReleaseReply
```

36 个 `AIRNT*`：

```
_AIRNTClone                               _AIRNTGetLegalizationPasses
_AIRNTDispose                             _AIRNTGetMeshFunctionId
_AIRNTDisposeCompilationContext           _AIRNTGetMostCompatibleArch
_AIRNTEmitAssembly                        _AIRNTGetObjectFunctionId
_AIRNTEmitBuiltinExecutableImage          _AIRNTGetPreferredAIRArch
_AIRNTEmitDylibImage                      _AIRNTGetSupportedArchs
_AIRNTEmitExecutableImage                 _AIRNTGetSupportedBitcodeVersion
_AIRNTEmitObject                          _AIRNTGetSupportedImpls
_AIRNTEmitPipelineImage                   _AIRNTGetTileFunctionId
_AIRNTEmitPipelineImages                  _AIRNTGetVendorName
_AIRNTGetBuiltinFunctionId                _AIRNTGetVersion
_AIRNTGetComputeFunctionId                _AIRNTGetVertexFunctionId
_AIRNTGetDefaultArch                      _AIRNTInit
_AIRNTGetFragmentFunctionId               _AIRNTInitCompilationContext
_AIRNTGetFunctionId                       _AIRNTParseCommandLineOptions
_AIRNTGetLLVMVersion                      _AIRNTSupportsArch
                                          _AIRNTSupportsEmitBuiltinExecutableImage
                                          _AIRNTSupportsEmitExecutableImage
                                          _AIRNTSupportsTarget
                                          _AIRNTSupportsThreads
```

另有 6 个无前缀别名，`32` 分册未记录：

```
_GetFunctionId  _GetVertexFunctionId  _GetFragmentFunctionId
_GetComputeFunctionId  _GetObjectFunctionId  _GetMeshFunctionId
```

**合计 46 个导出，不是 40 个。** `32` 分册第 3 节说"40 个纯 C 符号"，36 + 4 的拆分正确，但漏了这 6 个别名。

---

## 5. 本轮没拿到的，以及下一步

### 5.1 `libAppleParavirtCompilerPlugin.dylib` 仍未取得

`find /System -name 'lib*CompilerPlugin*.dylib'` 在磁盘上只找到 Swift 的三个与 Intel 的一个，**没有 APV 的那个**。两个候选位置本轮的 `find` 深度不够没进去：

1. `/System/Library/Extensions/AppleParavirtGPUMetal.bundle/` 的全深度遍历
2. `/System/Library/PrivateFrameworks/MTLCompiler.framework/Versions/32023/Libraries/`（该目录确认存在）

记为 `R-001`，下一轮 workflow 修正 `find` 深度即可。

### 5.2 FlatBuffers `AIRF`/`AIRP` descriptor 仍是空白

字符串检索在 Intel plugin 里只找到 `FlatBuffers 1.12.0`，没找到 `AIRF`/`AIRP` identifier 或 `Air.`/`Mtl4.` 命名空间串。两种可能：identifier 不以可打印字符串形式存在（它是 4 字节写在 buffer 里的，不必进字符串表），或者在 APV 的 plugin 而不是 Intel 的里。

**但现在有一条此前不存在的路**：运行器上 APV 是活的驱动、SIP 已关闭，所以可以在自己的进程里拦 `MTLCompilerBuildRequestWithSerializedBitcode`，把它收到的两个输入原样 dump 下来。这直接给出 descriptor 的真实字节。记为 `R-002`。

### 5.3 内核侧一条都没碰到

`10`/`11`/`12` 三册本轮零收获。运行器不能加载 kext（没有重启、aux collection 不可重建）。但 SIP 已关闭意味着**可以读 IORegistry、可以 `IOServiceOpen` 到 APV 的 user client**，这能验证 `10` 分册的 type-5 selector 0/2 结构与 `11` 分册的 22 条 `IOFramebufferUserClient` selector。记为 `R-003`。

### 5.4 本轮 workflow 的两个 job 报失败

`census` 与 `symbols` 两个 job 的 `conclusion` 是 `failure`，但 artifact 全部产出（步骤带 `if: always()`）。失败来自某个步骤的非零退出码，不影响已采集的数据。记为 `R-004`，下一轮修。

### 5.5 未解决项清单

| 编号 | 事项 | 标签 | 查清方法 |
|---|---|---|---|
| R-001 | `libAppleParavirtCompilerPlugin.dylib` 的磁盘路径 | `BLOCKED` | 下一轮 workflow 对 `AppleParavirtGPUMetal.bundle` 与 `MTLCompiler.framework/Versions/*/Libraries/` 做全深度 `find` |
| R-002 | FlatBuffers descriptor 的真实字节与 schema | `BLOCKED` | 在运行器上拦 `MTLCompilerBuildRequestWithSerializedBitcode` 的实参并 dump |
| R-003 | APV 的 type-5 / type-6 user client 实际接口 | `BLOCKED` | 运行器上 `ioreg -r -c IOAccelerator -l` + `IOServiceOpen` 实测 |
| R-004 | `census` / `symbols` 两个 job 的失败原因 | `INFERRED` | 读 `gh run view --log` 定位非零退出的步骤 |
| R-005 | encoder 族的真实类名（`21` 分册那四个名字是编的） | `BLOCKED` | 运行器上遍历 `objc_copyClassNamesForImage(Metal.framework)` 全量列出 |
| R-006 | 25G76 的结论在 25G325 上是否成立 | `BLOCKED` | 只能在目标 guest 上重跑同一套脚本。E0-L1 之后做 |
| R-007 | APV 为何连 `supportsFamily(Mac2)` 都报 false，本项目该怎么报 | `INFERRED` | `60` 分册据此重算 WindowServer 首帧最小集的前置条件 |

---

## 5.6 上游 metal2vulkan 的可建性：已确证

`TESTED(25G76)` 与 `TESTED(ubuntu)`。workflow `upstream-check.yml`，run `41182923637`，上游 ref `219f01365dc4c8eb346816c405b5b17403793764`。

| 步骤 | `macos-26-intel`（rustc 1.98.0） | `ubuntu-latest`（rustc 1.99.1） |
|---|---|---|
| `cargo metadata` | ✅ | ✅ |
| `cargo check -p metal2vulkan -p metal2vulkan-air -p metal2vulkan-runtime` | ✅ | ✅ |
| `cargo check --workspace --all-features` | ✅ | ✅ |
| `cargo check --target x86_64-apple-darwin` | **✅** | n/a |

**这关掉了吸收 metal2vulkan 之前的唯一技术前提。** 上游六个 crate 合计 1,685,285 行（`metal2vulkan` 561,805 / `metal2vulkan-runtime` 355,326 / `metal2vulkan-validation` 484,598 / `metal2vulkan-conformance` 193,467 / `metal2vulkan-air` 85,531 / `metal2vulkan-devtools` 4,558），在两个平台上零错误通过，且目标三元组 `x86_64-apple-darwin` 也通过。

注意 `rust-toolchain.toml` 把 channel 钉在 `1.98.1`，而 ubuntu runner 报的是 1.99.1 —— 说明 runner 上 rustup 没有按 `rust-toolchain.toml` 切换（`cargo check` 在仓库根目录跑时应当切换）。macOS runner 报 1.98.0，切换生效。**这个不一致本身是一条待查项（`R-008`）**：如果 CI 用的工具链与 `rust-toolchain.toml` 不符，那"一次普通构建就检查 MSRV 承诺"这条上游设计意图在我们的 CI 上不成立。

**一个本地环境的硬事实**：开发机（Windows）**编不了**上游。`cargo check` 止于 `error: linker 'link.exe' not found`，缺 MSVC Build Tools。所以上游与本项目自有 crate 的任何编译验证都只能在 CI 或 Linux/macOS 机器上做。记为 `R-009`。

## 5.7 Lavapipe 在 x86_64 macOS 上可建：已确证

`TESTED(25G76)`。workflow `build-lavapipe-macos.yml`，run `41190532445`。

**这是本项目最大的一处去风险。** `70-BUILD-PACKAGE.md` 第 3.4 节与
`80-TEST-HARNESS.md` 第 5.4 节都把它登记为风险：arm64 macOS 有成品先例，
**x86_64 零先例**，而它阻塞 `metal-probe`，而 `metal-probe` 是 T2 的唯一判据。

| 步骤 | 结果 |
|---|---|
| Vulkan-Loader 构建 | ✅ |
| Mesa meson setup | ✅ |
| Mesa ninja 构建 | ✅ |
| loader `dlopen` 自检 | ✅ |

环境：macOS 26.6.1 (25G76) x86_64，Mesa `mesa-25.3.2`，Vulkan-Loader
`v1.4.321`，LLVM **20.1.8**（运行器预装的 `llvm@20`）。

产物（`lavapipe-macos-x86_64.tar.gz`，3,339,354 字节）：

```
lib/libvulkan_lvp.dylib                     Lavapipe ICD 本体
share/vulkan/icd.d/lvp_icd.x86_64.json      ICD manifest
lib/libvulkan.1.4.321.dylib                 Vulkan loader
loader/vulkan.framework/Versions/A/vulkan   loader 的 framework 形态
lib/pkgconfig/vulkan.pc
share/drirc.d/00-mesa-defaults.conf
```

即 `00-OVERVIEW.md` 组件清单第 5 项（Vulkan loader 与 Lavapipe 的
macOS x86_64 构建打包）**已经有可用产物**。

### 5.7.1 三个踩到的坑（都在 CI 的两步式结构里，本地连续跑遇不到）

逐条记下来，因为每一条都让一次 job 白跑，而表象都不指向真实原因。

| # | 表象 | 真实原因 |
|---|---|---|
| 1 | job 在工具链步骤卡一个多小时不出来 | 写了 `brew install llvm@19`，而 `macos-26-intel` 预装的是 **`llvm@20`**。`llvm@19` 没有 bottle，brew 转去从源码编 LLVM。改为先探测预装的，找不到就立刻失败并打印可用 formula，**绝不退回 `brew install llvm`** |
| 2 | `meson setup` 失败 | `meson.build:641: ERROR: Program 'glslangValidator' not found`。缺 `glslang`，不是可选项 —— lavapipe 要用它编内部着色器 |
| 3 | `ninja` 跑到 **758/786** 才挂，exit 127 | `/bin/sh: llvm-ar: command not found`。meson 在配置期把归档器记成裸名 `llvm-ar`（当时 `$LP/bin` 在 PATH 上），而构建步骤是另一个 shell、没 `export` 同样的 PATH |

坑 3 顺带给了一条有价值的信息：挂之前 **lavapipe 自己的全部 `lvp_*.c.o` 都已编译通过**，所以 Lavapipe 的源码在 x86_64 macOS 上本来就没问题，三次失败全部是构建环境问题，不是移植问题。

另记一条无害项：日志里 `-mtls-dialect=gnu2` 与 `-mtls-dialect=desc` 两个探测
失败（`clang: error: unsupported option '-mtls-dialect=' for target
'x86_64-apple-macosx16.0.0'`）是正常的，meson 只是记录为不可用。

### 5.7.2 还没做的

`BLOCKED`：**产物只验证到 `dlopen` loader 成功**，没有实际
`vkCreateInstance` + `vkEnumeratePhysicalDevices` 跑通，所以：

- `43-COVERAGE-REFUSALS.md` 第 3 节那一批「等 `build-lavapipe-macos` 产物」
  的 `BLOCKED` 行**还不能关**。要关它们需要再跑一轮：加载 ICD、建 instance、
  枚举设备、读 `VkPhysicalDeviceFeatures` / `VkPhysicalDeviceLimits` /
  `vkGetPhysicalDeviceFormatProperties`，把 `60`/`43` 要的那些字段全部打出来。
- `41-IOSURFACE-USERSPACE.md` 的 `S-004`（`minImportedHostPointerAlignment`）
  与 `S-005`（`B8G8R8A8_UNORM` 的 `linearTilingFeatures` 是否含
  `COLOR_ATTACHMENT_BIT`）同理 —— 这两条是「上屏零拷贝是否成立」的判据，
  现在**已经具备测的条件**，只差那个探针程序。

记为 `R-010`：写一个 `lavapipe-probe` 并把它接到本 workflow 的产物上。
这是下一轮最该做的一件事，因为它一次能关掉 `43`/`41`/`60` 三册里的一批
`BLOCKED`。

## 6. 复现方式

```powershell
# 触发
gh workflow run evidence-macos26-intel.yml --ref main

# 取产物
$id = gh run list --workflow=evidence-macos26-intel.yml --limit 1 --json databaseId --jq '.[0].databaseId'
gh run download $id --dir ci-evidence

# 核对分册断言
py tools\ci\summarize_objc_dump.py ci-evidence\objc-dump\objc-dump.json
```

**`ci-evidence/` 不进仓库。** 其中含 Apple 二进制的派生分析（符号表、字符串），受 `.gitignore` 顶部的发布边界约束。本文记录的是结论，不是原始产物；原始产物可由上面三条命令随时重建。
