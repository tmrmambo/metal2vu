# Guest Objective-C Proxy / metal2vulkan Bridge Runtime Implementation Contract

> [!IMPORTANT]
> **本文已被 `docs/spec/50-IPC-HELPER.md` 吸收并校正。** 该分册逐条列出 10 处更正（其第 9.1 节），
> 其中三处是实质错误，不要照本文实现：
> - 同步编译超时 30 s → **4.5 s**（上游 4.5+4.5 与 guest 10 s FIFO 检查不容）
> - 「确认 helper 已死」用的是「或」→ **必须用「与」**（连接 invalid ≠ 映射已释放，僵尸进程仍可写共享内存）
> - 对象 id 用自建计数器 → **必须用上游 `ObjectId`**（终身唯一、永不复用）
>
> 另外本文的消息集只覆盖 clear 与 triangle；全量能力的 35 个 opcode 见该分册第 2.2 节。

[KNOWN] 文档版本：0.2-contract  
[KNOWN] 目标系统：macOS Tahoe 26.7.2 build 25G325，x86_64  
[KNOWN] 上游固定版本：metal2vulkan `0dfdbcd59d235e37ba13b87a5ab30835b5bb9e35`  

## 0. 合同状态与证据边界

- [KNOWN] 本合同只规定 guest Objective-C proxy、helper IPC、对象生命周期、完成语义以及 metal2vulkan runtime 适配；不修改基线规格、现有原型或上游源码。
- [KNOWN] 固定上游已在浅克隆中核验为 commit `0dfdbcd59d235e37ba13b87a5ab30835b5bb9e35`，工作树无修改。
- [KNOWN] 本次直接读取了固定 commit 的 `metal2vulkan-runtime`、`metal2vulkan` 和 `metal2vulkan-air` 源码，并针对两个 x86_64 vendor bundle 的 `__TEXT,__objc_methlist` 做了小范围 selector/type 记录解码。
- [BLOCKED] 本次没有在 25G325 x86_64 guest 中加载 proxy、Vulkan loader、Lavapipe 或 IOSurface，因此本文没有任何 `TESTED` 运行时能力声明。
- [INFERRED] 本文中标为 `INFERRED` 的规范句是实现选择，而不是 Apple 私有 ABI 的事实；实现可以按该合同编码，但相应能力只有通过规定 gate 后才可对 Metal 客户端报告。
- [KNOWN] Metal.framework 枚举和 bundle discovery 的 25G325 x86_64 BaseSystem 静态合同已闭合；目标 guest 动态行为仍未 `TESTED`。
- [BLOCKED] launchd/XPC entitlement、第三方 bundle trust、installed SystemOS IOGPU、device bootstrap 下游 selector 和 WindowServer 路径仍分别受 B-007、B-009、B-011、B-012 和显示侧阻断项约束。

### 0.1 输入快照

| 输入 | SHA-256 | 状态 |
|---|---|---|
| `C:\Users\viola\Documents\KVM MacOS\analysis\macos26-guest-metal-driver-spec.md` | `f5979b306be0939de3038d69a4078929bdf7d49bb84e5f77d21289db61ec21fa` | [KNOWN] 已读 |
| `C:\Users\viola\Documents\KVM MacOS\analysis\macos26-metal-user-spi.md` | `38ff75fb28ec182c9b41b20745dbc44aec512960bb9f2091d47e06cc2094607a` | [KNOWN] 已读 |
| `C:\Users\viola\Documents\KVM MacOS\analysis\metal2vulkan-gap-architecture.md` | `d72b5d9269525c067f6fa4864ab9c4a2f6139fc87f374035fbeeb2097c9bcee2` | [KNOWN] 已读 |
| `C:\Users\viola\Documents\KVM MacOS\metal_drivers\AMDRadeonX6000MTLDriver_decompressed` | `c0cea683b94a5d645cde7fb50faa917b02ab35bdab1a697d847e4b7678e1dadb` | [KNOWN] x86_64 ABI 样本 |
| `C:\Users\viola\Documents\KVM MacOS\metal_drivers\AppleIntelICLGraphicsMTLDriver_decompressed` | `2d21f64f6361045ce83f9bb0ce9d4aa56e452fab484066709673a1335f06141e` | [KNOWN] x86_64 ABI 样本 |

### 0.2 B-004 / B-005 判定

- [KNOWN] **B-005 在 Slice A/B 的合同层面关闭**：每个必需 Metal 操作已映射到固定 commit 的真实 crate、源文件、类型和方法，或明确标成上游不存在的 adapter gap。
- [KNOWN] **B-004 在静态合同层面关闭**：clear 与 triangle 的全部导出 selector 已取得精确 x86_64 encoding。
- [KNOWN] `newFunctionWithName:` 由 25G325 x86_64 Metal.framework 的 `MTLLibrary` required-instance protocol record 证明为 `@24@0:8@16`。
- [KNOWN] protocol list 位于 `0x7FF80B3A46D8`，method record 位于 `0x7FF80B3A46F8`，type string 位于 `0x7FF80B44B975`。
- [KNOWN] B-001、B-002、B-003 的静态合同也已闭合；`initWithAcceleratorPort:` 参数语义是 `io_service_t`，不是 `io_connect_t`。
- [BLOCKED] 目标 guest 尚无 framework 枚举和固定 triangle app trace，因此上述结论仍不是 `TESTED`。
- [KNOWN] 实现不得用通用 IMP 越过任何未列 selector；新发现的硬依赖必须先取得 type record。

## 1. 固定架构边界

- [INFERRED] Proxy 必须由静态编译的 Objective-C 类组成，每个导出 selector 有独立、带类型的实现；Rust 只通过窄 C ABI 接收已归一化的值。
- [INFERRED] Proxy 进程只保存 Objective-C 对象、wire handles、不可变 descriptor snapshot、callback blocks 和连接状态；不得装载 Mesa、LLVM、ash 或 Vulkan ICD。
- [INFERRED] Helper 进程保存 metal2vulkan runtime 对象、Vulkan loader、Lavapipe、客户端命名空间和提交状态。
- [KNOWN] 固定上游没有 Objective-C class、XPC/Mach transport、真实 IOSurface owner 或跨进程 handle；这些都是本项目 adapter 的责任。
- [INFERRED] `RenderCommandEncoder` proxy 是客户端内的临时单写者日志对象，不分配远端 encoder handle；`endEncoding` 把有界日志封入所属 command buffer，helper 在 `SUBMIT` 时创建并消费真实上游 encoder。
- [INFERRED] 上述本地记录方式保持 upstream `RenderCommandEncoder` “owned、`Send`、not `Sync`”的约束，也避免在多条 IPC 之间持有不可恢复的半开 encoder。
- [INFERRED] 未列入本合同的 selector 不注册；proxy 不实现 `+resolveInstanceMethod:`、`forwardingTargetForSelector:` 或自定义“全真”`respondsToSelector:`。
- [KNOWN] 继承自 `NSObject` 的 `respondsToSelector:` 只会为真实安装的方法返回真，因此未知 selector 会走正常的 Objective-C `doesNotRecognizeSelector:` 路径，而不会以错误 ABI 返回零。

## 2. 分阶段必需 selector

### 2.1 Phase A：真实 IOSurface clear

| 对象 | selector | 合同动作 | ABI 状态 |
|---|---|---|---|
| Device | `newCommandQueue` | 同步创建远端 queue，成功返回 +1 对象 | [KNOWN] 精确编码已取证 |
| Device | `newTextureWithDescriptor:iosurface:plane:` | 验证并传递 IOSurface capability，创建 backing buffer 和 texture | [KNOWN] 精确编码已取证 |
| CommandQueue | `commandBuffer` | 同步创建远端 command buffer，返回 +0/autoreleased proxy | [KNOWN] 精确编码已取证 |
| CommandBuffer | `renderCommandEncoderWithDescriptor:` | 客户端复制并验证 pass descriptor，建立本地 encoder log | [KNOWN] 精确编码已取证 |
| RenderCommandEncoder | `endEncoding` | 封闭本地 log；第二次调用或后续编码使 command buffer 进入记录错误 | [KNOWN] 精确编码已取证 |
| CommandBuffer | `commit` | 冻结对象引用并发送一次 `SUBMIT` | [KNOWN] 精确编码已取证 |
| CommandBuffer | `waitUntilCompleted` | 等到本地终态；连接失效时先置 `Error/DeviceLost` 再返回 | [KNOWN] 精确编码已取证 |
| CommandBuffer | `status` | 只读本地原子状态，不做同步 IPC | [KNOWN] 精确编码已取证 |
| CommandBuffer | `error` | 只读缓存的最终 `NSError`，非 `Error` 状态返回 `nil` | [KNOWN] 精确编码已取证 |
| CommandBuffer | `addCompletedHandler:` | 在 commit 前复制 block；终态后按 queue 顺序调用一次 | [KNOWN] 精确编码已取证 |

- [INFERRED] Phase A 只接受单 plane、plane 0、`BGRA8Unorm`、2D、单 sample、单 mip、单 slice、线性 rows 和 color attachment 0。
- [INFERRED] Phase A 的 clear 依赖 render-pass load action，不需要 shader 或 render pipeline，但必须执行 `endEncoding`、`commit` 和真实完成等待。

### 2.2 Phase B：真实 metallib triangle

| 对象 | selector | 合同动作 | ABI 状态 |
|---|---|---|---|
| Device | `newLibraryWithData:error:` | 同步复制 `dispatch_data_t` 字节并解析真实 metallib | [KNOWN] 精确编码已取证 |
| Library | `newFunctionWithName:` | 按 UTF-8 名称选择 metallib function，成功返回 +1 对象 | [KNOWN] `@24@0:8@16`，25G325 Metal protocol record |
| Device | `newRenderPipelineStateWithDescriptor:error:` | 将受限 descriptor snapshot 编译为 upstream render pipeline | [KNOWN] 精确编码已取证 |
| Device | `newBufferWithBytes:length:options:` | 在方法返回前复制顶点字节，创建远端 buffer | [KNOWN] 精确编码已取证 |
| RenderCommandEncoder | `setRenderPipelineState:` | 记录强引用的 pipeline handle | [KNOWN] 精确编码已取证 |
| RenderCommandEncoder | `setVertexBuffer:offset:atIndex:` | 记录可空 buffer、offset 和 slot | [KNOWN] 精确编码已取证 |
| RenderCommandEncoder | `drawPrimitives:vertexStart:vertexCount:` | 记录非索引 draw；短式固定 instance count 1、base instance 0 | [KNOWN] 精确编码已取证 |
| RenderCommandEncoder | `endEncoding` | 与 Phase A 相同 | [KNOWN] 精确编码已取证 |
| CommandBuffer | `commit` | 与 Phase A 相同 | [KNOWN] 精确编码已取证 |

- [INFERRED] Phase B 的最小 fixture 必须使用 `MTLPrimitiveTypeTriangle` raw value 3、`vertexStart = 0`、`vertexCount = 3`、vertex buffer slot 0 和 color attachment 0。
- [INFERRED] Phase B 首版只接受 vertex shader 通过 `[[buffer(0)]]` 读取顶点数据的 descriptor；非空 `vertexDescriptor` 在其字段适配完成前返回 `Unsupported`。

### 2.3 Phase C：helper isolation

| 变化 | selector 增量 | 合同 | 状态 |
|---|---|---|---|
| 进程边界 | 无 | Phase A/B selector 不变，所有远端创建和 submit 改走本合同 IPC | [INFERRED] 设计已定 |
| 崩溃通知 | 无 | XPC invalidation handler 将所有在途 command buffer 置 `Error/DeviceLost` | [INFERRED] 设计已定 |
| 完成通知 | 无 | helper 的 upstream scheduled/completed handler 产生单调事件 | [KNOWN] upstream handler API 存在；[INFERRED] IPC 转发层待实现 |
| IOSurface | 无 | 传 capability/right，不传 raw pointer、Objective-C `id` 或 `Vk*` handle | [INFERRED] schema 已定；[BLOCKED] 具体 target transfer API/entitlement |

### 2.4 Phase D：普通 Metal.framework 客户端

| 对象 | selector/入口 | 合同 | 状态 |
|---|---|---|---|
| Device initializer | `initWithAcceleratorPort:` | 接受 32-bit port name，完成 proxy connection；不得把 port 当指针 | [KNOWN] 精确编码 `@20@0:8I16`；[BLOCKED] 调用链 B-001/B-002 |
| Device identity | `name`, `registryID` | 返回 generation 内冻结的 identity snapshot | [KNOWN] 精确编码已取证 |
| Device topology | `isLowPower`, `isHeadless`, `isRemovable`, `hasUnifiedMemory` | 返回 profile 中已冻结的布尔值 | [KNOWN] 精确编码已取证；[BLOCKED] 目标值未测试 |
| Device limits | `maxBufferLength`, `maxThreadsPerThreadgroup`, `maxThreadgroupMemoryLength` | 返回 adapter limit、runtime limit、测试 limit 的最小值 | [KNOWN] 精确编码已取证；[BLOCKED] 测试 limit 未产生 |
| Device capabilities | `supportsFamily:`, `supportsFeatureSet:`, `supportsTextureSampleCount:` | 只从冻结 capability profile 回答 | [KNOWN] 精确编码已取证；[INFERRED] 未测试项一律 false |
| Child identity | `device` | 返回被 child 强持有的同一 Device proxy | [KNOWN] 精确编码已取证 |
| CommandBuffer identity | `commandQueue` | 返回被 command buffer 强持有的同一 Queue proxy | [KNOWN] 精确编码已取证 |
| Common labels | `label`, `setLabel:` | label 保存在 proxy；支持的 upstream 对象同时更新 helper | [KNOWN] 精确编码已取证；[INFERRED] command buffer label 可仅本地保存 |
| Buffer queries | `length`, `contents`, `resourceOptions`, `storageMode`, `cpuCacheMode`, `hazardTrackingMode` | 返回创建 snapshot；跨进程普通 buffer 的 `contents` 为 `NULL`，除非另有共享映射合同 | [KNOWN] 精确编码已取证；[INFERRED] 跨进程内容策略 |
| Texture queries | `textureType`, `pixelFormat`, `width`, `height`, `depth`, `mipmapLevelCount`, `arrayLength`, `sampleCount`, `usage`, `resourceOptions` | 返回创建 snapshot，不做同步 IPC | [KNOWN] 精确编码已取证 |
| Framework registration | `MTLCopyAllDevices`, `MTLCreateSystemDefaultDevice` 的系统路径 | 只能由 Metal.framework 真实枚举进入 Device initializer | [BLOCKED] B-001/B-002；不得导出自定义同名替代函数 |

- [BLOCKED] Phase D 表是本项目固定 acceptance app 的最小公共对象面，不是任意第三方 Metal app 的完整兼容承诺。
- [BLOCKED] 在取得一次 25G325 x86_64 framework 枚举和固定 app trace 前，任何额外 framework 硬依赖必须作为新表项补证，不能交给动态 fallback。

## 3. 精确 Objective-C ABI / type encoding

- [KNOWN] 下表的地址是 selector/type 相邻记录在两个已哈希 x86_64 样本的 `__TEXT,__objc_methlist` 中的位置；它们不是 arm64 推断。
- [KNOWN] `@` 表示对象，`@?` 表示 block，`Q` 表示 64-bit unsigned integer/`NSUInteger`，`q` 表示 64-bit signed integer/`NSInteger`，`I` 表示 32-bit unsigned integer，`c` 表示 x86_64 Objective-C `BOOL`，`^{__IOSurface=}` 表示 opaque `IOSurfaceRef` 指针。
- [INFERRED] 实现首选在 Objective-C 源文件中声明这些方法，让编译器生成调用约定；若仍用 `class_addMethod`，必须逐字使用完整 encoding 并为每个 selector 提供独立 IMP。

| selector | x86_64 exact encoding | 直接证据 | 状态 |
|---|---|---|---|
| `dealloc` | `v16@0:8` | AMD representative `0x385cd0`；Intel representative `0xc1ba8` | [KNOWN] |
| `initWithAcceleratorPort:` | `@20@0:8I16` | AMD `0x387194`；Intel `0xc28d8` | [KNOWN] |
| `newCommandQueue` | `@16@0:8` | AMD `0x388b24`；Intel `0xc28f0` | [KNOWN] |
| `newTextureWithDescriptor:iosurface:plane:` | `@40@0:8@16^{__IOSurface=}24Q32` | AMD `0x388b84`；Intel `0xc2974` | [KNOWN] |
| `commandBuffer` | `@16@0:8` | AMD `0x3888bc`；Intel `0xc2458` | [KNOWN] |
| `renderCommandEncoderWithDescriptor:` | `@24@0:8@16` | AMD `0x3887a8`；Intel `0xc2318` | [KNOWN] |
| `endEncoding` | `v16@0:8` | AMD render record `0x388044`；Intel render record `0xc3288` | [KNOWN] |
| `commit` | `v16@0:8` | AMD `0x3887fc`；Intel `0xc22dc` | [KNOWN] |
| `waitUntilCompleted` | `v16@0:8` | AMD protocol record `0x389ac4`；Intel `0xc47c4` | [KNOWN] |
| `status` | `Q16@0:8` | AMD protocol record `0x389c20`；Intel `0xc4920` | [KNOWN] |
| `error` | `@16@0:8` | AMD protocol record `0x389c2c`；Intel `0xc492c` | [KNOWN] |
| `addCompletedHandler:` | `v24@0:8@?16` | AMD protocol record `0x389ab8`；Intel `0xc47b8` | [KNOWN] |
| `newLibraryWithData:error:` | `@32@0:8@16^@24` | AMD protocol record `0x38a4ec`；Intel `0xc51ec` | [KNOWN] |
| `newFunctionWithName:` | `@24@0:8@16` | Metal `MTLLibrary` protocol list `0x7FF80B3A46D8`；record `0x7FF80B3A46F8`；type `0x7FF80B44B975` | [KNOWN] |
| `newRenderPipelineStateWithDescriptor:error:` | `@32@0:8@16^@24` | AMD protocol record `0x38a528`；Intel `0xc5228` | [KNOWN] |
| `newBufferWithBytes:length:options:` | `@40@0:8r^v16Q24Q32` | AMD `0x388b54`；Intel `0xc2914` | [KNOWN] |
| `setRenderPipelineState:` | `v24@0:8@16` | AMD render record `0x387abc`；Intel `0xc3294` | [KNOWN] |
| `setVertexBuffer:offset:atIndex:` | `v40@0:8@16Q24Q32` | AMD render record `0x387ae0`；Intel `0xc32a0` | [KNOWN] |
| `drawPrimitives:vertexStart:vertexCount:` | `v40@0:8Q16Q24Q32` | AMD render record `0x387d44`；Intel `0xc34c8` | [KNOWN] |
| `name` | `@16@0:8` | AMD protocol record `0x38a858`；Intel `0xc5558` | [KNOWN] |
| `registryID` | `Q16@0:8` | AMD `0x38a864`；Intel `0xc5564` | [KNOWN] |
| `isLowPower` | `c16@0:8` | AMD `0x38a888`；Intel `0xc5588` | [KNOWN] |
| `isHeadless` | `c16@0:8` | AMD `0x38a894`；Intel `0xc5594` | [KNOWN] |
| `isRemovable` | `c16@0:8` | AMD `0x38a8a0`；Intel `0xc55a0` | [KNOWN] |
| `hasUnifiedMemory` | `c16@0:8` | AMD `0x38a8ac`；Intel `0xc55ac` | [KNOWN] |
| `maxBufferLength` | `Q16@0:8` | AMD protocol record `0x38a9cc`；Intel `0xc56cc` | [KNOWN] |
| `maxThreadsPerThreadgroup` | `{?=QQQ}16@0:8` | AMD protocol record `0x38a87c`；Intel `0xc557c` | [KNOWN] |
| `maxThreadgroupMemoryLength` | `Q16@0:8` | AMD protocol record `0x38a978`；Intel `0xc5678` | [KNOWN] |
| `supportsFamily:` | `c24@0:8q16` | AMD `0x38a5b8`；Intel `0xc52b8` | [KNOWN] |
| `supportsFeatureSet:` | `c24@0:8Q16` | AMD `0x38a5ac`；Intel `0xc52ac` | [KNOWN] |
| `supportsTextureSampleCount:` | `c24@0:8Q16` | AMD `0x38a5c4`；Intel `0xc52c4` | [KNOWN] |
| `device` | `@16@0:8` | AMD representative `0x38bf14`；Intel representative `0xc6c14` | [KNOWN] |
| `commandQueue` | `@16@0:8` | AMD `0x389ba8`；Intel `0xc48a8` | [KNOWN] |
| `label` | `@16@0:8` | AMD representative `0x385d44`；Intel representative `0xc205c` | [KNOWN] |
| `setLabel:` | `v24@0:8@16` | AMD representative `0x385d50`；Intel representative `0xc48d8` | [KNOWN] |
| `length` | `Q16@0:8` | AMD `0x389a28`；Intel `0xc46e0` | [KNOWN] |
| `contents` | `^v16@0:8` | AMD `0x3899d4`；Intel `0xc468c` | [KNOWN] |
| `resourceOptions`, `storageMode`, `cpuCacheMode`, `hazardTrackingMode` | `Q16@0:8` | AMD `0x38bf20`–`0x38bf44`；Intel `0xc6c20`–`0xc6c44` | [KNOWN] |
| `textureType`, `pixelFormat`, `width`, `height`, `depth`, `mipmapLevelCount`, `arrayLength`, `sampleCount`, `usage` | `Q16@0:8` | AMD `0x38d650`–`0x38d6b0`；Intel `0xc8310`–`0xc8370` | [KNOWN] |

- [KNOWN] `newFunctionWithName:` 的 encoding 已由 25G325 x86_64 Metal.framework protocol metadata 直接证明；AMD/Intel selRef 只作交叉证据。
- [BLOCKED] 目标 guest 仍须用 `protocol_getMethodDescription(objc_getProtocol("MTLLibrary"), sel_registerName("newFunctionWithName:"), YES, YES).types` 核对 installed SystemOS 输出，才能升级为 `TESTED`。
- [KNOWN] `C:\Users\viola\Documents\KVM MacOS\deprecated\MyVirtualMTLDriver\src\ffi\objc_runtime.rs` 中的紧凑 encoding（例如 `@@:@^vQ`）没有 stack offsets，且 IOSurface 被写成 `^v`；它们不能替代上表的直接二进制证据。
- [KNOWN] 同一原型文件会把未知 selector 动态安装为 `@@:` 并让 `respondsToSelector:` 恒真；该机制与本合同明确冲突，禁止复用。

## 4. Descriptor snapshot 合同

- [INFERRED] Descriptor 解码必须位于编译为 Objective-C 的 shim 中，通过目标 SDK 的 typed declarations 调 getter；Rust 不得用无类型 `objc_msgSend` 猜测 descriptor getter ABI。
- [INFERRED] 每次创建/encoder 调用在返回前生成不可变 snapshot；调用返回后不再读取调用者的 mutable descriptor。
- [INFERRED] Snapshot 只允许下面的 v1 profile；任何非默认、未列出的值都返回 `Unsupported` 或将所属 command buffer 标为记录错误，不能被忽略。

### 4.1 IOSurface texture snapshot v1

| 字段 | 接受值/约束 | 状态 |
|---|---|---|
| `texture_type` | `MTLTextureType2D` | [INFERRED] v1 限制 |
| `pixel_format` | `MTLPixelFormatBGRA8Unorm`，raw 80 | [KNOWN] upstream enum table；[INFERRED] v1 限制 |
| `width`, `height` | 各 `1..=16384`，并与 helper 从 IOSurface 重读值一致 | [INFERRED] 安全上限 |
| `depth` | 1 | [INFERRED] v1 限制 |
| `mipmap_level_count` | 1 | [INFERRED] v1 限制 |
| `sample_count` | 1 | [INFERRED] v1 限制 |
| `array_length` | 1 | [INFERRED] v1 限制 |
| `usage` | 必须包含 `RenderTarget`；未知 bit 拒绝 | [KNOWN] upstream checked enum/flags；[INFERRED] v1 限制 |
| `resource_options` | `Shared` storage；只接受 upstream `ResourceOptions::from_raw` 可解析的 bits | [KNOWN] checked converter 存在；[INFERRED] v1 限制 |
| `framebuffer_only`, `rotation`, `is_drawable` | v1 均为默认值 false/0/false | [INFERRED] v1 限制 |
| `plane` | 0，surface 必须没有 planes 或恰有一个 plane | [INFERRED] v1 限制 |

### 4.2 Render pass snapshot v1

| 字段 | 接受值/约束 | 状态 |
|---|---|---|
| `color[0].texture` | 当前 generation、当前 client 的 IOSurface texture handle | [INFERRED] adapter contract |
| `color[0].level/slice/depth_plane` | 全部 0 | [INFERRED] v1 限制 |
| `color[0].resolve_*` | 无 resolve texture，indices 全 0 | [INFERRED] v1 限制 |
| `color[0].load_action` | `DontCare`、`Load` 或 `Clear`，通过 `LoadAction::from_raw` 校验；clear gate 要求 `Clear` | [KNOWN] upstream converter |
| `color[0].store_action` | `Store`；其他值 v1 拒绝 | [KNOWN] upstream enum；[INFERRED] v1 限制 |
| `color[0].store_action_options` | 0 | [INFERRED] v1 限制 |
| `color[0].clear_color` | 4 个有限 `f64`；非有限值 v1 拒绝 | [INFERRED] v1 限制 |
| `color[1..7]` | texture 为 nil | [INFERRED] v1 限制 |
| depth/stencil/visibility | 均无 attachment/resource | [INFERRED] v1 限制 |
| target size/array/tile/rate map/sample positions | 全部默认值；非默认 v1 拒绝 | [INFERRED] v1 限制 |

### 4.3 Render pipeline snapshot v1

| 字段 | 接受值/约束 | 状态 |
|---|---|---|
| `vertex_function`, `fragment_function` | 两者均为当前 Device 的 Function handle | [INFERRED] adapter contract |
| `vertex_descriptor` | nil | [INFERRED] v1 限制 |
| `color_attachments[0]` | BGRA8Unorm；blend off；One/Zero/Add；write mask ALL | [KNOWN] `ColorAttachmentDescriptor::new` 默认；[INFERRED] v1 限制 |
| `color_attachments[1..7]` | Invalid/nil | [INFERRED] v1 限制 |
| depth/stencil format | Invalid/nil | [INFERRED] v1 限制 |
| raster sample count | 1 | [INFERRED] v1 限制 |
| alpha-to-coverage / alpha-to-one | false / false | [INFERRED] v1 限制 |
| rasterization enabled | true | [INFERRED] v1 限制 |
| input primitive topology | Unspecified 或 Triangle；其他值 v1 拒绝 | [INFERRED] v1 限制 |
| amplification/tessellation/ICB/binary functions | 默认值；全部未启用 | [INFERRED] v1 限制 |

- [INFERRED] `NSError **` 在成功时不写；失败且指针非空时写入 autoreleased `NSError`，对象返回 `nil`。
- [INFERRED] `newLibraryWithData:error:` 必须把 `dispatch_data_t` 映射或分段复制到受限 blob；不得假定参数是 `NSData *`。
- [INFERRED] `newBufferWithBytes:length:options:` 必须在 Objective-C 方法返回前完成字节复制，因调用者可立即修改或释放原内存。

## 5. Metal → metal2vulkan 精确映射

| Metal/adapter 操作 | 固定 upstream 路径与 symbol | 适配规则 | 状态 |
|---|---|---|---|
| Helper 创建 CPU Vulkan device | [crates/metal2vulkan-runtime/src/device/create.rs](https://github.com/steelbrain/metal2vulkan/blob/0dfdbcd59d235e37ba13b87a5ab30835b5bb9e35/crates/metal2vulkan-runtime/src/device/create.rs) `Device::system_default_with` + `DeviceOptions::loader` + `DeviceOptions::kinds` | loader 用包内绝对路径；`kinds = [DeviceKind::Cpu]`；记录 identity/hash | [KNOWN] 可复用 |
| `newCommandQueue` | [crates/metal2vulkan-runtime/src/queue.rs](https://github.com/steelbrain/metal2vulkan/blob/0dfdbcd59d235e37ba13b87a5ab30835b5bb9e35/crates/metal2vulkan-runtime/src/queue.rs) `Device::new_command_queue` | upstream 默认最多 64 个未完成 CB | [KNOWN] 可复用 |
| `commandBuffer` | [crates/metal2vulkan-runtime/src/queue.rs](https://github.com/steelbrain/metal2vulkan/blob/0dfdbcd59d235e37ba13b87a5ab30835b5bb9e35/crates/metal2vulkan-runtime/src/queue.rs) `CommandQueue::command_buffer` | helper 创建后放入 client object table | [KNOWN] 可复用 |
| 接收 IOSurface | 无 upstream symbol | XPC/Mach capability → helper 自有 `IOSurfaceRef` 和本地 base address | [KNOWN] 真实 upstream gap；[BLOCKED] target transfer ABI |
| IOSurface lifetime backing | [crates/metal2vulkan-runtime/src/host_memory.rs](https://github.com/steelbrain/metal2vulkan/blob/0dfdbcd59d235e37ba13b87a5ab30835b5bb9e35/crates/metal2vulkan-runtime/src/host_memory.rs) `HostMemory::new`, `KeepAlive` | `KeepAlive` 持有 helper 的 IOSurface owner 和 mapping lease | [KNOWN] 可复用 |
| IOSurface base buffer | [crates/metal2vulkan-runtime/src/buffer_descriptor.rs](https://github.com/steelbrain/metal2vulkan/blob/0dfdbcd59d235e37ba13b87a5ab30835b5bb9e35/crates/metal2vulkan-runtime/src/buffer_descriptor.rs) `BufferDescriptor::new`, `BufferContents::NoCopy`, `Device::new_buffer_with_descriptor` | length 为 helper 重读的 allocation size；`keep_alive = Some(...)` | [KNOWN] 可复用；禁止省略 keep-alive |
| `newTextureWithDescriptor:iosurface:plane:` | [crates/metal2vulkan-runtime/src/buffer_texture.rs](https://github.com/steelbrain/metal2vulkan/blob/0dfdbcd59d235e37ba13b87a5ab30835b5bb9e35/crates/metal2vulkan-runtime/src/buffer_texture.rs) `IoSurfacePlane::new`, `Buffer::new_texture_with_iosurface_plane` | 先创建 backing Buffer，再由 Buffer 创建 texture；不是 Device 的单步调用 | [KNOWN] 可复用 |
| Texture descriptor | [crates/metal2vulkan-runtime/src/texture_descriptor.rs](https://github.com/steelbrain/metal2vulkan/blob/0dfdbcd59d235e37ba13b87a5ab30835b5bb9e35/crates/metal2vulkan-runtime/src/texture_descriptor.rs) `TextureDescriptor`, `TextureDescriptor::texture_2d` | 从 snapshot 逐字段构造，不采用调用者未验证的 raw struct | [KNOWN] 可复用 |
| `renderCommandEncoderWithDescriptor:` | [crates/metal2vulkan-runtime/src/render.rs](https://github.com/steelbrain/metal2vulkan/blob/0dfdbcd59d235e37ba13b87a5ab30835b5bb9e35/crates/metal2vulkan-runtime/src/render.rs) `CommandBuffer::render_command_encoder` | helper 在 `SUBMIT` replay 时创建 | [KNOWN] 可复用 |
| Clear pass descriptor | [crates/metal2vulkan-runtime/src/render_pass.rs](https://github.com/steelbrain/metal2vulkan/blob/0dfdbcd59d235e37ba13b87a5ab30835b5bb9e35/crates/metal2vulkan-runtime/src/render_pass.rs) `RenderPassDescriptor`, `RenderPassColorAttachmentDescriptor`；[render_values.rs](https://github.com/steelbrain/metal2vulkan/blob/0dfdbcd59d235e37ba13b87a5ab30835b5bb9e35/crates/metal2vulkan-runtime/src/render_values.rs) `LoadAction::from_raw`, `StoreAction::from_raw`, `ClearColor` | color 0 绑定 surface texture，load clear，store store | [KNOWN] 可复用 |
| `endEncoding` | [crates/metal2vulkan-runtime/src/render.rs](https://github.com/steelbrain/metal2vulkan/blob/0dfdbcd59d235e37ba13b87a5ab30835b5bb9e35/crates/metal2vulkan-runtime/src/render.rs) `RenderCommandEncoder::end_encoding` | upstream encoder 被消费；错误使 helper submit 失败 | [KNOWN] 可复用 |
| `newLibraryWithData:error:` | [crates/metal2vulkan-runtime/src/library.rs](https://github.com/steelbrain/metal2vulkan/blob/0dfdbcd59d235e37ba13b87a5ab30835b5bb9e35/crates/metal2vulkan-runtime/src/library.rs) `Device::new_library_with_data` | 只接受 metallib；bare AIR 被 typed compile error 拒绝 | [KNOWN] 可复用 |
| `newFunctionWithName:` | [crates/metal2vulkan-runtime/src/library.rs](https://github.com/steelbrain/metal2vulkan/blob/0dfdbcd59d235e37ba13b87a5ab30835b5bb9e35/crates/metal2vulkan-runtime/src/library.rs) `Library::new_function_with_name` | UTF-8 name 由 proxy snapshot 传入 | [KNOWN] runtime 与 Objective-C ABI 可复用 |
| Function → stage descriptor | [crates/metal2vulkan-runtime/src/library.rs](https://github.com/steelbrain/metal2vulkan/blob/0dfdbcd59d235e37ba13b87a5ab30835b5bb9e35/crates/metal2vulkan-runtime/src/library.rs) `Function::function_descriptor`；[crates/metal2vulkan/src/pipeline/descriptor.rs](https://github.com/steelbrain/metal2vulkan/blob/0dfdbcd59d235e37ba13b87a5ab30835b5bb9e35/crates/metal2vulkan/src/pipeline/descriptor.rs) `StageSource::Function` | vertex/fragment 分别转换 | [KNOWN] 可复用 |
| Render pipeline descriptor | [crates/metal2vulkan/src/pipeline/descriptor.rs](https://github.com/steelbrain/metal2vulkan/blob/0dfdbcd59d235e37ba13b87a5ab30835b5bb9e35/crates/metal2vulkan/src/pipeline/descriptor.rs) `RenderPipelineDescriptor::new`, `ColorAttachmentDescriptor::new` | 逐字段填充 v1 snapshot，禁止固定 shader 替代输入 | [KNOWN] 可复用 |
| `newRenderPipelineStateWithDescriptor:error:` | [crates/metal2vulkan-runtime/src/pipeline/render.rs](https://github.com/steelbrain/metal2vulkan/blob/0dfdbcd59d235e37ba13b87a5ab30835b5bb9e35/crates/metal2vulkan-runtime/src/pipeline/render.rs) `Device::new_render_pipeline_state`；[pipeline/options.rs](https://github.com/steelbrain/metal2vulkan/blob/0dfdbcd59d235e37ba13b87a5ab30835b5bb9e35/crates/metal2vulkan-runtime/src/pipeline/options.rs) `PipelineOptions::default` | 同步编译，30 秒 adapter deadline | [KNOWN] 可复用 |
| `newBufferWithBytes:length:options:` | [crates/metal2vulkan-runtime/src/buffer_descriptor.rs](https://github.com/steelbrain/metal2vulkan/blob/0dfdbcd59d235e37ba13b87a5ab30835b5bb9e35/crates/metal2vulkan-runtime/src/buffer_descriptor.rs) `Device::new_buffer_with_bytes`；[values.rs](https://github.com/steelbrain/metal2vulkan/blob/0dfdbcd59d235e37ba13b87a5ab30835b5bb9e35/crates/metal2vulkan-runtime/src/values.rs) `ResourceOptions::from_raw` | raw options 先校验；传入已复制 slice | [KNOWN] 可复用 |
| `setRenderPipelineState:` | [crates/metal2vulkan-runtime/src/render.rs](https://github.com/steelbrain/metal2vulkan/blob/0dfdbcd59d235e37ba13b87a5ab30835b5bb9e35/crates/metal2vulkan-runtime/src/render.rs) `RenderCommandEncoder::set_render_pipeline_state` | helper 从 handle lookup 后调用 | [KNOWN] 可复用 |
| `setVertexBuffer:offset:atIndex:` | [crates/metal2vulkan-runtime/src/render.rs](https://github.com/steelbrain/metal2vulkan/blob/0dfdbcd59d235e37ba13b87a5ab30835b5bb9e35/crates/metal2vulkan-runtime/src/render.rs) `RenderCommandEncoder::set_vertex_buffer` | `NSUInteger` 必须 checked-convert 到 upstream `u64` offset / `u32` index；超界拒绝 | [KNOWN] 可复用 |
| `drawPrimitives:vertexStart:vertexCount:` | [crates/metal2vulkan-runtime/src/render.rs](https://github.com/steelbrain/metal2vulkan/blob/0dfdbcd59d235e37ba13b87a5ab30835b5bb9e35/crates/metal2vulkan-runtime/src/render.rs) `RenderCommandEncoder::draw_primitives`；[render_values.rs](https://github.com/steelbrain/metal2vulkan/blob/0dfdbcd59d235e37ba13b87a5ab30835b5bb9e35/crates/metal2vulkan-runtime/src/render_values.rs) `DrawPrimitiveType::from_raw` | start/count checked-convert 到 `u32`；short form 传 `(instance_count=1, base_instance=0)` | [KNOWN] 可复用；[INFERRED] 超过 `u32::MAX` v1 拒绝 |
| `commit` | [crates/metal2vulkan-runtime/src/command_buffer/mod.rs](https://github.com/steelbrain/metal2vulkan/blob/0dfdbcd59d235e37ba13b87a5ab30835b5bb9e35/crates/metal2vulkan-runtime/src/command_buffer/mod.rs) `CommandBuffer::commit` | helper replay 全部 encoder 后调用一次 | [KNOWN] 可复用 |
| scheduled notification | [crates/metal2vulkan-runtime/src/command_buffer/mod.rs](https://github.com/steelbrain/metal2vulkan/blob/0dfdbcd59d235e37ba13b87a5ab30835b5bb9e35/crates/metal2vulkan-runtime/src/command_buffer/mod.rs) `CommandBuffer::add_scheduled_handler` | helper 生成 `EVENT_SCHEDULED`；不泄露 `VkSemaphore` | [KNOWN] 可复用 |
| completion notification | [crates/metal2vulkan-runtime/src/command_buffer/mod.rs](https://github.com/steelbrain/metal2vulkan/blob/0dfdbcd59d235e37ba13b87a5ab30835b5bb9e35/crates/metal2vulkan-runtime/src/command_buffer/mod.rs) `CommandBuffer::add_completed_handler`, `CommandBuffer::status`, `CommandBuffer::error` | IOSurface 可见性收尾后生成一个 terminal event | [KNOWN] 可复用；[INFERRED] adapter 收尾 |
| `waitUntilCompleted` | [crates/metal2vulkan-runtime/src/command_buffer/mod.rs](https://github.com/steelbrain/metal2vulkan/blob/0dfdbcd59d235e37ba13b87a5ab30835b5bb9e35/crates/metal2vulkan-runtime/src/command_buffer/mod.rs) `CommandBuffer::wait_until_completed_for`, `CommandBuffer::wait_until_completed` | helper reconciliation wait 使用 bounded form；客户端 API 只在终态后返回 | [KNOWN] 可复用 |
| Vulkan timeline completion | [crates/metal2vulkan-runtime/src/command_buffer/completion.rs](https://github.com/steelbrain/metal2vulkan/blob/0dfdbcd59d235e37ba13b87a5ab30835b5bb9e35/crates/metal2vulkan-runtime/src/command_buffer/completion.rs) `Completion`, `Submitted` | upstream 内部每 `VkQueue` timeline 达值后完成 batch | [KNOWN] 可复用内部语义 |
| 公开 raw timeline value | 无 public upstream symbol | IPC 的 `completion_value` 必须是 helper logical value，不得冒充 Vulkan semaphore counter | [KNOWN] 真实 upstream API gap |
| `device`, `commandQueue` getters | [crates/metal2vulkan-runtime/src/queue.rs](https://github.com/steelbrain/metal2vulkan/blob/0dfdbcd59d235e37ba13b87a5ab30835b5bb9e35/crates/metal2vulkan-runtime/src/queue.rs) `CommandQueue::device`；[command_buffer/mod.rs](https://github.com/steelbrain/metal2vulkan/blob/0dfdbcd59d235e37ba13b87a5ab30835b5bb9e35/crates/metal2vulkan-runtime/src/command_buffer/mod.rs) `CommandBuffer::device`, `CommandBuffer::command_queue`；各 resource 的 `device` method | Proxy 返回缓存的同一 parent proxy，不把 Rust reference 跨 FFI | [KNOWN] 可复用 |
| `label`, `setLabel:` | [crates/metal2vulkan-runtime/src/queue.rs](https://github.com/steelbrain/metal2vulkan/blob/0dfdbcd59d235e37ba13b87a5ab30835b5bb9e35/crates/metal2vulkan-runtime/src/queue.rs) `CommandQueue::label/set_label`；[attributes.rs](https://github.com/steelbrain/metal2vulkan/blob/0dfdbcd59d235e37ba13b87a5ab30835b5bb9e35/crates/metal2vulkan-runtime/src/attributes.rs) `Buffer::label/set_label`；[texture/attributes.rs](https://github.com/steelbrain/metal2vulkan/blob/0dfdbcd59d235e37ba13b87a5ab30835b5bb9e35/crates/metal2vulkan-runtime/src/texture/attributes.rs) `Texture::label/set_label` | CommandBuffer 没有 upstream label method，故该对象的 label 只保存在 proxy snapshot | [KNOWN] 部分复用，明确 upstream gap |
| Buffer query selectors | [crates/metal2vulkan-runtime/src/buffer.rs](https://github.com/steelbrain/metal2vulkan/blob/0dfdbcd59d235e37ba13b87a5ab30835b5bb9e35/crates/metal2vulkan-runtime/src/buffer.rs) `Buffer::length`, `contents`, `resource_options`, `storage_mode`, `cpu_cache_mode`, `hazard_tracking_mode` | 跨进程 proxy 优先返回创建 snapshot；`contents` 受共享映射合同限制 | [KNOWN] 可复用；[INFERRED] proxy snapshot |
| Texture query selectors | [crates/metal2vulkan-runtime/src/texture.rs](https://github.com/steelbrain/metal2vulkan/blob/0dfdbcd59d235e37ba13b87a5ab30835b5bb9e35/crates/metal2vulkan-runtime/src/texture.rs) `Texture::texture_type`, `pixel_format`, `width`, `height`, `depth`, `mipmap_level_count`, `array_length`, `sample_count`, `usage`, `resource_options` | 创建 reply 返回一次 snapshot，getter 不做 IPC | [KNOWN] 可复用；[INFERRED] cache policy |
| `supportsFeatureSet:` | 无对应 upstream legacy feature-set symbol | v1 固定 false；将来必须有显式 feature-set→tested capability 表 | [KNOWN] upstream gap；[INFERRED] v1 答案 |
| Capability family | [crates/metal2vulkan-runtime/src/families/mod.rs](https://github.com/steelbrain/metal2vulkan/blob/0dfdbcd59d235e37ba13b87a5ab30835b5bb9e35/crates/metal2vulkan-runtime/src/families/mod.rs) `Device::supports_family`, `Device::family_blockers` | 结果还要与 adapter 实现和 guest test allowlist 相交 | [KNOWN] 可复用 |
| Device limits/identity | [crates/metal2vulkan-runtime/src/device/mod.rs](https://github.com/steelbrain/metal2vulkan/blob/0dfdbcd59d235e37ba13b87a5ab30835b5bb9e35/crates/metal2vulkan-runtime/src/device/mod.rs) `Device::registry_id`, `Device::name`, `Device::properties`；[capabilities.rs](https://github.com/steelbrain/metal2vulkan/blob/0dfdbcd59d235e37ba13b87a5ab30835b5bb9e35/crates/metal2vulkan-runtime/src/capabilities.rs) `DeviceProperties` | 只作为 backend 上限，不直接成为公开承诺 | [KNOWN] 可复用 |
| Import/copy observability | [crates/metal2vulkan-runtime/src/work_counts.rs](https://github.com/steelbrain/metal2vulkan/blob/0dfdbcd59d235e37ba13b87a5ab30835b5bb9e35/crates/metal2vulkan-runtime/src/work_counts.rs) `Device::work_counts`；[degradation.rs](https://github.com/steelbrain/metal2vulkan/blob/0dfdbcd59d235e37ba13b87a5ab30835b5bb9e35/crates/metal2vulkan-runtime/src/degradation.rs) `Degradation::CopiedHostPages` | 报告 buffer import/copy 轴；texture shadow 另轴记录 | [KNOWN] 可复用 |
| ObjC object family、NSError、block ABI | 无 upstream symbol | 全部由 proxy shim 实现 | [KNOWN] upstream gap |
| XPC schema、audit-token namespace、generation | 无 upstream symbol | 全部由 helper adapter 实现 | [KNOWN] upstream gap |

## 6. 对象状态与所有权

### 6.1 Proxy 对象状态

| 状态 | 允许操作 | 转移 | 状态 |
|---|---|---|---|
| `Alive` | 与对象种类匹配的 selector | `dealloc` → `Invalidating`；connection loss → `Dead` | [INFERRED] 合同状态 |
| `Invalidating` | 只允许本地析构；不得创建新远端对象 | 发送一次 best-effort `DESTROY` 后 → `Dead` | [INFERRED] 合同状态 |
| `Dead` | 状态/error getter 可读缓存；创建/编码调用确定失败 | 终态，不重绑 | [INFERRED] 合同状态 |

- [INFERRED] Objective-C runtime 管理 proxy 的本地 retain count；实现不得覆盖 `retain`、`release` 或 `autorelease`。
- [INFERRED] `dealloc` 只能执行一次，清空 ivar 后发送一次 best-effort `DESTROY`，再调用 superclass；幂等性属于 helper 的 `DESTROY` 处理，不属于重复调用 `dealloc`。
- [KNOWN] `new`、`copy`、`alloc`、`mutableCopy` method family 返回 +1；本合同所有 `new*` selector 因此返回 retained proxy。
- [INFERRED] `commandBuffer` 和 `renderCommandEncoderWithDescriptor:` 返回 +0/autoreleased proxy；getter 返回 +0 对象。
- [INFERRED] 每个 remote handle 在一个 client namespace 内最多对应一个活 proxy；弱 cache 用于保持 `device`/`commandQueue` 的 Objective-C pointer identity，但弱 cache 不延长生命周期。

### 6.2 Parent-child 与在途引用

| 对象 | 必须强持有 | 释放条件 | 状态 |
|---|---|---|---|
| Queue proxy | Device proxy | queue proxy dealloc | [INFERRED] |
| CommandBuffer proxy | Queue proxy；commit 后持有所有 encoder/resource/pipeline snapshots | terminal event 已发布且 callbacks 已取走后可释放在途引用 | [INFERRED] |
| Encoder proxy | CommandBuffer proxy；记录期间持有绑定对象 | `endEncoding` 后引用移交 CommandBuffer | [INFERRED] |
| IOSurface Texture proxy | Device proxy；本地 IOSurface 引用；远端 backing handle | proxy dealloc 只撤外部 lease；在途提交仍持有 | [INFERRED] |
| Function proxy | Library proxy 和 Device proxy | function proxy dealloc | [INFERRED] |
| Pipeline proxy | Device proxy；helper 内的 compiled state | pipeline proxy dealloc 且无在途 command 使用 | [INFERRED] |
| Completion block | CommandBuffer proxy 间接持有 `_Block_copy` 结果 | 调用一次后 `_Block_release`；未 commit 的 CB dealloc 时也释放 | [INFERRED] |

- [KNOWN] Upstream `Device`、`CommandQueue`、`CommandBuffer`、`Buffer`、`Texture`、`Library` 和 `Function` 是 cheap clonable `Send + Sync` handles；encoder 是 owned、`Send`、not `Sync`。
- [INFERRED] Helper object table entry保存一个 upstream handle clone 和依赖 handles；lookup 在锁内 clone，runtime 调用在锁外执行。
- [INFERRED] `DESTROY` 只删除客户端的外部 lease；command buffer、encoder log 或其他 child 持有的内部引用继续保活对象直到安全点。
- [KNOWN] 因此基线中的“父对象销毁不得留下可提交子对象”不符合 Metal/retain 语义；释放 Device proxy 不得使仍强持有 Device 的 Queue/Buffer 失效。
- [INFERRED] 只有 helper generation 变化、connection invalidation 或明确 device loss 才整棵对象树失效。

### 6.3 Remote handle 与销毁

- [INFERRED] Wire handle 固定为 typed dictionary，而不是 C struct bytes：`{kind:u64, flags:u64, generation:u64, id:u64}`。
- [INFERRED] v1 `flags` 必须为 0；`kind` 必须在下表中；`generation` 必须等于 connection generation；`id` 必须非零。

| kind | 值 | 远端对象 | 状态 |
|---|---:|---|---|
| Device | 1 | `metal2vulkan_runtime::Device` | [INFERRED] wire assignment |
| Queue | 2 | `CommandQueue` | [INFERRED] wire assignment |
| CommandBuffer | 3 | `CommandBuffer` + adapter record | [INFERRED] wire assignment |
| Buffer | 4 | `Buffer` | [INFERRED] wire assignment |
| Texture | 5 | `Texture` + IOSurface backing lease | [INFERRED] wire assignment |
| Library | 6 | `Library` | [INFERRED] wire assignment |
| Function | 7 | `Function` | [INFERRED] wire assignment |
| RenderPipeline | 8 | `RenderPipelineState` | [INFERRED] wire assignment |

- [INFERRED] `id` 在 generation 内按 client 单调增加且永不复用；不存在或已销毁的 handle 对普通操作返回 `InvalidArgument/StaleHandle`。
- [INFERRED] `DESTROY` 对一个曾签发但已不存在的 `id` 返回成功，因此重复 destroy 幂等；它不得使同一对象的内部/in-flight clone 提前释放。
- [INFERRED] Helper restart 的 generation 来自受保护状态中的持久化 32-bit 非零计数器，启动时以原子 replace 加一；计数器回卷时 helper 拒绝启动并要求重置安装 identity。
- [BLOCKED] generation 状态文件的最终路径、owner 和 launchd sandbox access 必须在 B-007 打包探针中确定；不能用进程内静态变量假装跨崩溃递增。

## 7. 线程规则

| 范围 | 规则 | 状态 |
|---|---|---|
| Device/Queue 创建 | 可从多线程并发；object-table 锁内只做校验和 clone | [KNOWN] upstream handles `Send + Sync`；[INFERRED] adapter locking |
| CommandBuffer 记录 | 同一时刻只允许一个 open encoder；commit 后不可再编码 | [KNOWN] upstream 约束；[INFERRED] proxy mirror |
| Encoder | 记录线程固定为创建线程；跨线程或并发调用将 CB 标记 `InvalidArgument/ConcurrentEncoding` | [INFERRED] 更严格的 v1 规则 |
| Queue commit | proxy 在 queue lock 下分配 `queue_seq`；helper 按 `queue_seq` 顺序 replay/commit | [INFERRED] 显式保证 IPC 跨线程顺序 |
| Status/error | 原子/读锁读取，不等待 helper、不持有 callback 锁 | [INFERRED] |
| Callback list | commit 前可加；commit 后拒绝；取出列表后再调用 block | [KNOWN] upstream 同样拒绝 commit 后 handler；[INFERRED] proxy implementation |
| IPC receive | 不在 XPC receive callback 内执行用户 block或昂贵编译 | [INFERRED] |
| Runtime callbacks | 进入 helper per-queue event sequencer；不持有 object-table 或 IOSurface registry lock | [INFERRED] |

- [INFERRED] Helper 必须为每个 logical Queue 维护串行 submit executor，即使多个 Queue 最终共享一个 upstream `VkQueue`。
- [INFERRED] 同 queue 的 scheduled、terminal 和 completed-handler dispatch 顺序按 `queue_seq` 单调；不同 queue 不承诺相对顺序。
- [INFERRED] 缺失的 `queue_seq` 在 10 秒后使该 client connection 进入 `ProtocolError` 并全部失效，避免无界重排缓存。
- [INFERRED] 锁顺序固定为 connection state → queue sequencer → command-buffer state → callback list；object table lookup 必须 clone 后立即解锁，不能在持锁时进入 runtime、XPC send 或用户代码。

## 8. IPC envelope、消息和上限

### 8.1 Request/reply envelope

| key | XPC type | 规则 | 状态 |
|---|---|---|---|
| `v` | unsigned integer | 必须为 1 | [INFERRED] protocol v1 |
| `kind` | unsigned integer | 必须是已列 message kind | [INFERRED] |
| `request_id` | unsigned integer | 非零、connection 内严格递增 | [INFERRED] |
| `client_id` | unsigned integer | `HELLO` 为 0；其余必须等于 connection-bound 值 | [INFERRED] |
| `generation` | unsigned integer | `HELLO` 为 0；其余必须等于 current generation 且不超过 `u32::MAX` | [INFERRED] |
| `declared_bytes` | unsigned integer | 客户端声明的 body/blob bytes；helper 必须独立重算并要求相等 | [INFERRED] |
| `body` | dictionary | 只允许该 kind 定义的 keys 和 exact types | [INFERRED] |

- [INFERRED] Reply 固定包含 `v`、`kind`、`request_id`、`generation`、`ok`；`ok=true` 时有 `body`，`ok=false` 时有 `error`，两者不得同时出现。
- [INFERRED] `client_id` 由 helper 随 connection 分配并绑定 XPC audit token；helper 不以请求中的 `client_id` 选择 namespace。
- [INFERRED] 未知 key、错误 XPC type、重复 key 语义、过深 dictionary/array 或不匹配的 `declared_bytes` 均为 `ProtocolError`。
- [INFERRED] Mutating request 不自动重试；XPC connection 中断时该 generation 全部失效，避免重复创建或重复 submit。

### 8.2 Message kinds

| kind | 值 | body | reply/event | 状态 |
|---|---:|---|---|---|
| `HELLO` | 1 | `min_v:u64`, `max_v:u64`, `client_nonce:data[16]` | `client_id`, `generation`, Device handle, capability snapshot, limits | [INFERRED] |
| `CREATE_QUEUE` | 2 | Device handle, `max_uncompleted:u64` | Queue handle | [INFERRED] |
| `IMPORT_SURFACE` | 3 | Device handle, `surface:xpc_object`, `plane:u64`, texture snapshot | Texture handle, two-axis import mode | [INFERRED]；[BLOCKED] concrete surface XPC object |
| `CREATE_BUFFER_BYTES` | 4 | Device handle, `resource_options:u64`, blob | Buffer handle | [INFERRED] |
| `CREATE_LIBRARY` | 5 | Device handle, metallib blob | Library handle | [INFERRED] |
| `CREATE_FUNCTION` | 6 | Library handle, `name_utf8:data` | Function handle | [INFERRED] |
| `CREATE_RENDER_PIPELINE` | 7 | Device handle, function handles, pipeline snapshot | RenderPipeline handle | [INFERRED] |
| `CREATE_COMMAND_BUFFER` | 8 | Queue handle | CommandBuffer handle | [INFERRED] |
| `SUBMIT` | 9 | CommandBuffer handle, `queue_seq:u64`, encoder logs | immediate accepted/error reply；later events | [INFERRED] |
| `WAIT` | 10 | CommandBuffer handle, `deadline_ms:u64` | current terminal state or `Timeout` | [INFERRED] |
| `DESTROY` | 11 | one typed handle | idempotent ack | [INFERRED] |
| `CANCEL_CLIENT` | 12 | empty | ack then connection close | [INFERRED] |
| `EVENT_SCHEDULED` | 100 | CB handle, `queue_seq`, `completion_value` | server→client one-way | [INFERRED] |
| `EVENT_TERMINAL` | 101 | CB handle, `queue_seq`, `completion_value`, status, optional error, surface seeds | server→client one-way | [INFERRED] |
| `EVENT_DEVICE_LOST` | 102 | generation, stable error | server→client one-way | [INFERRED] |

### 8.3 Blob schema

| key | XPC type | 规则 | 状态 |
|---|---|---|---|
| `transport` | unsigned integer | 0=`inline_data`，1=`read_only_shared_memory` | [INFERRED] |
| `length` | unsigned integer | 必须等于实际 mapped/data length | [INFERRED] |
| `sha256` | data[32] | helper 在解析前重算；不匹配拒绝 | [INFERRED] |
| `data` | data | 仅 transport 0；最多 1 MiB | [INFERRED] |
| `memory` | XPC shared-memory/Mach-memory object | 仅 transport 1；helper 只读映射 | [BLOCKED] target API/entitlement；schema 保留 |

- [INFERRED] v1 Gate A/B fixture 必须控制 metallib 和 vertex bytes 各不超过 1 MiB，因此不依赖尚未补证的 shared-memory attachment。
- [INFERRED] 大于 1 MiB 的 metallib 只有 `read_only_shared_memory` 路径通过 B-007 probe 后才可接受；禁止把 64 MiB data 塞入声称“1 MiB control message”的 dictionary。

### 8.4 `SUBMIT` encoder log v1

- [INFERRED] `encoders` 是最多 64 项的 array；v1 每项 `kind=render`，含一个 render-pass snapshot 和最多 65,536 条总 commands。
- [INFERRED] Command kind 1 为 `SET_RENDER_PIPELINE {pipeline}`；kind 2 为 `SET_VERTEX_BUFFER {index:u64, offset:u64, buffer:handle-or-null}`；kind 3 为 `DRAW_PRIMITIVES {primitive:u64, vertex_start:u64, vertex_count:u64}`。
- [INFERRED] Clear encoder 的 commands 可以为空；helper 仍必须创建 render encoder并调用 `end_encoding`，使 load/store action 真正执行。
- [INFERRED] Helper 必须先验证整条 log 和全部 handles，再按顺序调用 upstream；任何一项失败都不得提交部分 command buffer。
- [INFERRED] `completion_value` 等于 helper 对该 logical queue 接受的 `queue_seq`，是 IPC logical timeline；它不得记录或暴露内部 `VkSemaphore` handle/counter。

### 8.5 固定 limits

| 项目 | v1 hard limit | 状态 |
|---|---:|---|
| 逻辑 control payload | 1 MiB/request | [INFERRED] |
| dictionary nesting | 4 | [INFERRED] |
| dictionary keys | 128/request | [INFERRED] |
| string/error text | 4 KiB；label 256 bytes | [INFERRED] |
| inline blob | 1 MiB | [INFERRED] |
| metallib | 64 MiB；超过 1 MiB 必须 OOL | [INFERRED]；[BLOCKED] OOL path |
| copied buffer creation | 1 GiB；超过 1 MiB 必须 OOL | [INFERRED]；[BLOCKED] OOL path |
| IOSurface allocation | 1 GiB | [INFERRED] |
| surface width/height | 各 16,384 | [INFERRED] |
| encoder count | 64/command buffer | [INFERRED] |
| command count | 65,536/command buffer | [INFERRED] |
| uncompleted CB | 64/queue，256/client | [KNOWN] upstream queue default 64；[INFERRED] client cap |
| live remote objects | 65,536/client | [INFERRED] |
| total accounted allocations | 2 GiB/client | [INFERRED] |
| synchronous pipeline compile | 30 s | [INFERRED] |
| queue-sequence gap | 10 s | [INFERRED] |
| liveness hard deadline | 60 s | [INFERRED] |

- [INFERRED] 配置只能降低这些上限，不能由客户端请求提高。
- [INFERRED] 所有乘加使用 checked arithmetic；任何 overflow 在 allocation、mapping 或 runtime call 前返回 `InvalidArgument`。

## 9. IOSurface transfer、验证与两轴模式

- [BLOCKED] 现有材料只证明“应通过 Mach/XPC capability 传 IOSurface”，没有证明 25G325 x86_64 下可用的具体 creation/lookup API、bootstrap namespace 或 entitlement。
- [INFERRED] `IMPORT_SURFACE.surface` 必须是 connection 随消息传递的 capability/right；单独的全局 IOSurface ID 不得作为授权依据。
- [INFERRED] Helper 取得自己的 `IOSurfaceRef` 后必须重新读取 plane count、base address、allocation size、width、height、bytes-per-element、bytes-per-row、plane offset 和 plane size；请求 snapshot 只用于交叉检查。
- [INFERRED] 单 plane BGRA8 的有效范围必须满足：`bytes_per_element = 4`、`bytes_per_row >= width * 4`、`offset + bytes_per_row * (height - 1) + width * 4 <= allocation_size`，且每一步 checked。
- [INFERRED] IOSurface owner、helper mapping 和 runtime `KeepAlive` 必须覆盖 texture 外部 lease与所有在途 command-buffer clones。
- [INFERRED] 对 CPU/Lavapipe 写路径，surface lease 在首个在途 writer 前取得写 lock，在最后一个 writer 的 upstream completion 后完成必要 unlock/seed 更新；不得在 proxy 释放 texture 时提前 unlock。
- [BLOCKED] `IOSurfaceLock/Unlock` flags、seed 与跨进程可见性的最终序列必须由 Gate 2 target probe 固定；本文不把它冒充为已验证 cache-coherency ABI。

| 轴 | 值 | 判定 | 状态 |
|---|---|---|---|
| Host-buffer storage | `ImportedHostPages` | `WorkCounts.host_pointer_imports_made` 增加，且没有 `CopiedHostPages` | [KNOWN] upstream 可观测；[INFERRED] per-import attribution |
| Host-buffer storage | `CopiedHostPages` | 收到 `Degradation::CopiedHostPages` 或 copied counter 增加 | [KNOWN] upstream 可观测 |
| Texture storage | `InPlaceImage` | 没有 texture shadow/copy degradation，Gate 2 像素验证通过 | [INFERRED] 需 runtime notice + test |
| Texture storage | `ShadowedTexture` | runtime 采用 shadow image 并在 completion copy/merge back | [KNOWN] upstream 有该路径；[BLOCKED] target 行为未测 |

- [KNOWN] “buffer host pages 已 import”不等于“texture 直接渲染到这些 rows”；基线的 `DirectHostImport`/`ShadowCopy` 单轴分类不足。
- [INFERRED] Helper 必须把两轴值都写入 `IMPORT_SURFACE` reply 和诊断日志；只有 `ImportedHostPages + InPlaceImage` 可称为直接路径。
- [INFERRED] 为准确归因，helper 对 surface backing 创建使用专用串行段，并在 `DeviceOptions::messages` 中捕获每次 `CopiedHostPages` notice；不得从全局累计值在并发创建后猜测。

## 10. CommandBuffer 完成与错误状态机

### 10.1 可见状态

- [INFERRED] v1 对客户端可见的状态机固定如下。

```text
NotEnqueued
    | commit accepted locally
    v
Committed
    | upstream scheduled handler
    v
Scheduled
    | upstream completed handler + IOSurface visibility finalization
    +-------------------------------> Completed
    +-------------------------------> Error
```

- [KNOWN] Upstream `CommandBufferStatus` 定义 0..5 为 NotEnqueued、Enqueued、Committed、Scheduled、Completed、Error，但 runtime 没有 `enqueue`，因此本合同不产生 `Enqueued`。
- [INFERRED] 内部 `RecordingPoisoned` 仍向客户端报告 `NotEnqueued`；调用 `commit` 时直接成为 terminal `Error`，不向 Vulkan 提交。
- [INFERRED] 状态只前进；`Completed` 和 `Error` 是互斥终态，任何 duplicate/out-of-order terminal event 由 compare-and-swap 忽略并记录 protocol diagnostic。
- [INFERRED] `EVENT_TERMINAL` 若先于 `EVENT_SCHEDULED` 到达，client event sequencer 先发布 `Scheduled` 再发布终态；callback 仍只运行一次。

### 10.2 完成条件

- [KNOWN] Upstream completion waiter只有在对应 `VkQueue` timeline value 达到后才 finish batch，并在需要时等待 fence；其 completion path在 completed handlers 前处理资源 holds 和 copied-host-page merge-back。
- [INFERRED] Helper 只有在 upstream completed handler 已运行、`CommandBuffer::status` 为 Completed/Error、`CommandBuffer::error` 已冻结、IOSurface unlock/seed 或其他可见性收尾成功后，才发送 `EVENT_TERMINAL`。
- [INFERRED] IOSurface 收尾失败把最终状态改为 `Error/InternalError`；不能先发送 Completed 再报告 surface 错误。
- [INFERRED] Client 收到 terminal event 后先在锁内冻结 status/error 和 logical completion value并唤醒 waiters，再在锁外按注册顺序调用 blocks。
- [INFERRED] `waitUntilCompleted` 没有可观察的“超时但仍在运行”返回；10 秒只触发健康诊断，不能改变状态或返回。
- [INFERRED] 60 秒 liveness hard deadline 到达时，supervisor 必须终止该 helper generation并确认进程死亡、mapping 释放或 connection invalidation；只有确认不会再写 IOSurface 后，client 才把 CB 置 `Error/Timeout` 或 `Error/DeviceLost`、触发 blocks 并让 `waitUntilCompleted` 返回。
- [BLOCKED] 若 supervisor 无法确认 helper 已停止，`waitUntilCompleted` 必须继续等待或由调用进程的外部 watchdog 处置；它不能在共享内存仍可能被写时伪造终态。
- [KNOWN] 因此基线“普通提交等待 10 秒、总等待 60 秒”只能作为健康检查和 helper 处置 policy，不能直接改变无返回值 `waitUntilCompleted` 的 API 语义。

### 10.3 Block lifetime 与调用

- [INFERRED] `addCompletedHandler:` 入参非空时立即 `_Block_copy`；空 block 使 CB 记录 `InvalidArgument`。
- [INFERRED] Block 只能在 commit 前登记；commit 后登记不调用并产生与 upstream `HandlerAfterCommit` 对应的 deterministic misuse diagnostic。
- [INFERRED] CommandBuffer proxy 从 commit 到 callback list 清空期间自持有；每个 block 被取出后调用一次，调用结束立即 `_Block_release`。
- [INFERRED] 用户 block 抛出的 Objective-C exception 不能穿过 Rust/XPC callback boundary；shim 必须捕获、记录并继续释放剩余 blocks。
- [INFERRED] callback 执行时不得持有 connection、object table、CB state、surface registry 或 callback-list lock。

### 10.4 Helper crash recovery

- [INFERRED] XPC invalidation handler以一次性 CAS 将 connection 标为 dead，并快照所有 nonterminal CB。
- [INFERRED] 每个快照 CB 进入 `Error`，wire category `DeviceLost`，wake waiters，并将 completed blocks 各调用一次；已终态 CB 不被覆盖。
- [INFERRED] 当前 generation 的所有 proxy 进入 `Dead`；旧 handle 在新 helper 中永远拒绝。
- [INFERRED] Supervisor 可启动新 helper并产生新 generation，但只有新建 Device/Queue/Library/Pipeline/Buffer/Texture 才能使用它。
- [INFERRED] IOSurface capability 可由客户端显式重新 import；private buffers、libraries、pipelines 和 command buffers不自动重建。

### 10.5 Stable wire error

| category | 值 | upstream/adapter 来源 | 状态 |
|---|---:|---|---|
| `InvalidArgument` | 1 | `Error::Invalid`, `Error::Nil` 的非 NSError 路径，range/kind/state violation | [INFERRED] mapping |
| `Unsupported` | 2 | `Unsupported`, `NotImplemented`, `AppleOnly`, `Unproven`, unsupported profile value | [INFERRED] mapping |
| `OutOfMemory` | 3 | `OutOfMemory`、对应 Vulkan OOM | [INFERRED] mapping |
| `CompileFailed` | 4 | `Compile`, `MetalError`, pipeline/library parse/compile | [INFERRED] mapping |
| `DeviceLost` | 5 | `DeviceLost`, helper crash, Vulkan device lost | [INFERRED] mapping |
| `Timeout` | 6 | compile/liveness deadline | [INFERRED] mapping |
| `ProtocolError` | 7 | envelope/schema/version/namespace violation | [INFERRED] mapping |
| `InternalError` | 8 | 其他已捕获 failure | [INFERRED] mapping |

- [INFERRED] Wire `error` dictionary固定为 `category:u64`, `source_kind:string<=128`, `source_code:i64`, `message:string<=4096`, `retryable:bool`。
- [INFERRED] `NSError` domain 固定为 `GuestMetalBridgeErrorDomain`，code 使用上表值；`userInfo` 保存 bounded `source_kind` 和 request/submission IDs，不保存完整 shader 或像素。
- [KNOWN] Upstream `Error` 是 non-exhaustive typed enum；adapter 必须有 unknown-variant → `InternalError` 的显式 default，不能 panic 或让 Rust unwind 穿过 FFI。

## 11. Capability reporting

- [INFERRED] 每次 `HELLO` 生成不可变 `CapabilitySnapshot`，其 hash 覆盖：proxy selector-table version、adapter protocol version、upstream commit、loader/ICD hashes、runtime device description、hard limits和通过的 test IDs。
- [INFERRED] Public capability 的真值必须满足 `proxy selector+ABI implemented ∩ adapter path implemented ∩ upstream/runtime supported ∩ Lavapipe supported ∩ target guest test allowlist`。
- [INFERRED] Helper restart、任一 binary hash 变化或 test allowlist 变化必须产生新 profile version；现有 connection 的 snapshot 不热更新。

| 能力 | Proxy/adapter | Upstream | 目标测试 | 当前公开回答 | 状态 |
|---|---|---|---|---|---|
| 单 plane BGRA8 IOSurface clear | 合同已定义 | 有 render-pass clear 和 host-memory paths | 未运行 Gate 2 | false / device 不可发布 | [BLOCKED] |
| 真实 metallib vertex+fragment | ABI 与 mapping 已定义 | library/function/graphics pipeline 已有 | 未运行 Gate 3 | false | [BLOCKED] 仅缺目标测试 |
| Triangle draw + vertex buffer | 合同已定义 | exact methods 已有 | 未运行 Gate 3 | false | [BLOCKED] |
| Helper isolation/restart | IPC/state machine 已定义 | 无 upstream helper | 未运行 Gate 4 | false | [BLOCKED] |
| `supportsTextureSampleCount:1` | query ABI 已知 | runtime query 已有 | 未验证 IOSurface/render | false | [BLOCKED] |
| 任意 `supportsFamily:` | query ABI 已知 | `supports_family`/blockers 已有 | 无 family gate | false | [BLOCKED] |
| `supportsFeatureSet:` | query ABI 已知 | 无直接 legacy feature-set contract | 无 | false | [BLOCKED] |
| SharedEvent 跨进程 | 未实现 | upstream handles 明确进程内 | 无 | false | [KNOWN] 不支持 |
| Compute/heap/sparse/ray tracing/mesh | 不在 v1 selector/profile | upstream 部分存在 | 无 | false | [KNOWN] 不声明 |
| CAMetalLayer/WindowServer present | 不在本合同 | upstream不拥有 OS presentation | 无 | false | [BLOCKED] 独立阶段 |

- [INFERRED] `maxBufferLength` 返回 `min(runtime.properties.max_buffer_length, 1 GiB protocol cap, largest_target_tested_buffer)`；没有非零 target test 值时不得发布 framework device。
- [INFERRED] `maxThreadsPerThreadgroup` 和 `maxThreadgroupMemoryLength` 同样取 runtime 值与 test profile 值的逐项最小值。
- [INFERRED] `name`、`registryID` 等 identity 值可来自 `Device::name`/`registry_id`，但不能被解释为 Metal family 支持证明。
- [INFERRED] Capability query 只读本地 snapshot；helper失联后不改变历史 snapshot，但任何新创建操作失败，existing CB 进入 DeviceLost。

## 12. 基线规格修正

| 基线位置/主张 | 修正合同 | 状态 |
|---|---|---|
| §6.3 “父对象销毁不得留下可提交的子对象” | Child 强持有 parent；普通 parent release 不失效 child，generation/device loss 才失效树 | [KNOWN] 与 retain 和 upstream clone model 冲突 |
| §6.3/§6.2 “dealloc 必须幂等释放远端对象” | `dealloc` 只运行一次；helper `DESTROY` 必须幂等 | [INFERRED] 安全修正 |
| §7.1 generation 每次重启递增 | 必须定义跨进程崩溃的持久化 epoch；进程静态计数不合格 | [INFERRED] 补全；[BLOCKED] 安装路径 |
| §8.2 信任 `payload_size` | Helper 必须独立重算实际 lengths、depth 和 count，并要求声明一致 | [INFERRED] 安全修正 |
| §8.4 1 MiB control message 与 64 MiB metallib | >1 MiB 必须 OOL read-only memory；该 target transport 在补证前不可用 | [KNOWN] 原约束自相矛盾 |
| §8.4 单 buffer 1 GiB | 这是 protocol hard cap，不是当前 `newBufferWithBytes` 可达值；公开 limit 还受 OOL、runtime、quota 和 tests 限制 | [INFERRED] 收紧 |
| §9.3 `DirectHostImport` / `ShadowCopy` | 必须分开报告 host-buffer import/copy 与 texture in-place/shadow 两个轴 | [KNOWN] upstream 实际有两层决策 |
| §9.2 “IOSurface ID 或 Mach right” | ID 只能作诊断/交叉检查，授权必须来自随 connection 传递的 capability/right | [INFERRED] 安全修正 |
| §10.1 `Completed \-> Error` 图示 | Completed/Error 是互斥终态；Error 从记录失败、Committed 或 Scheduled 分支进入 | [KNOWN] 状态机修正 |
| §10.1 总是包含 `Enqueued` | v1 无 `enqueue` selector，状态不产生 Enqueued | [KNOWN] upstream 注释明确 |
| §10.2 单独检查 Vulkan barrier | Adapter 以 upstream completed handler 为 Vulkan semantic completion 点，再做 IOSurface 收尾；不得读取 private Vk timeline 猜完成 | [KNOWN] upstream completion 实现；[INFERRED] adapter boundary |
| §10.3 “等待有限完成” | `waitUntilCompleted` 只能在 terminal state 后返回；deadline 必须先终止为 Error | [KNOWN] API 无 timeout return；[INFERRED] liveness policy |
| §8.3 `SUBMIT` 返回 Vulkan timeline value | upstream 不公开 raw value；v1 返回 helper logical `completion_value`，内部完成由 upstream timeline watcher证明 | [KNOWN] API gap |
| §6.5 “所有 descriptor 字段逐项读取” | v1 必须逐项读取与当前 profile 相关的字段，并显式拒绝其他非默认字段；不能默默忽略，也不必假装支持完整 descriptor | [INFERRED] 可实施化 |
| §12 capability 来自交集 | 保留该原则，并增加 target-test allowlist、selector-table version 和 protocol limits | [INFERRED] 补全 |
| §5/B-003 `initWithAcceleratorPort:` encoding 未知 | encoding 为 `@20@0:8I16`；参数是 `io_service_t`；framework 调用链已定位 | [KNOWN] 25G325 Metal 与四份 method record |
| B-004 `newFunctionWithName:` type 未知 | encoding 为 `@24@0:8@16` | [KNOWN] 25G325 `MTLLibrary` protocol record |
| B-005 仅有模块级“reuse” | 替换为本文逐操作 path/type/method 表；Objective-C、IPC、OS IOSurface 和 raw timeline 明确是 gap | [KNOWN] 已收敛 |
| 现有原型 fallback 可“安全吸收”私有 selector | `@@:` 通用 IMP 会破坏非对象返回、参数和结构体 ABI；必须删除而非沿用 | [KNOWN] 现有源码与双样本 encoding 直接冲突 |

## 13. 实施停止线与验收清单

- [KNOWN] 本合同不要求、也不允许修改固定 upstream；adapter 只调用其 public API。
- [INFERRED] 实现顺序固定为：typed ObjC class shells → protocol codec/validator → helper object table → same-process upstream mapping tests → XPC transport → IOSurface target probe → framework registration。
- [KNOWN] `newFunctionWithName:` 必须注册为 `@24@0:8@16`；不得使用 selector 冒号数推导或通用 IMP。
- [BLOCKED] 在目标 guest trace 前，不得把静态 selector 合同升级为 `TESTED`。
- [BLOCKED] 在 B-007 关闭前，只能在测试 transport 或同进程路径验证 runtime；不得声称 WindowServer/client sandbox 能传 IOSurface。
- [INFERRED] 每个导出 class 的 method-list 单元测试必须枚举 `class_copyMethodList`，逐项比较 selector 和 `method_getTypeEncoding`，并确认未知 selector 的 `respondsToSelector:` 为 false。
- [INFERRED] Mapping 单元测试必须对本文每行 exact upstream call 建一条 fixture，并证明 adapter 不调用 `C:\Users\viola\Documents\KVM MacOS\deprecated\MyVirtualMTLDriver\src\compiler` 或 `src\backend\gallium.rs`。
- [INFERRED] Gate 2 必须保存两轴 import mode、surface geometry、row-padding sentinel、raw pixel hash、loader/ICD hashes 和 terminal event trace。
- [INFERRED] Gate 3 必须保存 metallib hash、function names、pipeline error、SPIR-V validation、fixed sample pixels 和 callback order。
- [INFERRED] Gate 4 必须强杀 helper，证明 client 生存、每个在途 CB 只终结一次、blocks 只调用一次、旧 generation handles 全部拒绝、新 generation 可重建。
- [KNOWN] 只要实现严格安装本文列出的 selector，Slice A/B/C 不需要、也不得存在 generic selector fallback。


## 14. 主会话整合证据

- [KNOWN] `metal-registration-contract.md` SHA-256 为 `38344BEA4D45A33D45C2B3EB6DB7E4ED6B836AF7EC32A070381CD0C0B8374D0B`。
- [KNOWN] 25G325 x86_64 BaseSystem Metal raw extract SHA-256 为 `9BAB47CD9A7E11E15A17486C8E4BA2775CDDC1A705A6F60A39C0A87D9F598C9D`。
- [KNOWN] Metal Mach-O UUID 为 `FDB3FD2C-840A-3FC3-81FB-C524F891F642`。
- [KNOWN] 主会话从 `MTLLibrary` required-instance method list 直接解码 `newFunctionWithName:`。
- [KNOWN] protocol list 为 `0x7FF80B3A46D8`，record 为 `0x7FF80B3A46F8`，type string 为 `0x7FF80B44B975`。
- [KNOWN] 持久化 IDB 为 `analysis/idb/macos26-25G325-x86_64-frameworks/idb/Metal-BaseSystem-analysis.i64`。
- [BLOCKED] installed SystemOS 的同一 protocol 输出仍须由目标 guest 核对。
