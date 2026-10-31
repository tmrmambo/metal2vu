# macOS 26 Guest Metal 驱动与桥接层实现规格

文档版本：1.0-implementation-contract  
目标系统：macOS Tahoe 26.7.2，build 25G325，x86_64  
更新时间：2026-10-29  
状态：Gate 0 `PASS-STATIC`；目标 guest 尚无 `TESTED` 结果  
权威范围：本文件取代 `PROJECT_SPEC.md` 中全部 Metal 实现结论  
规范附件：`analysis/spec-work/metal-registration-contract.md`、`analysis/spec-work/bridge-runtime-contract.md`

## 0. 文档用途

本规格定义一个完全位于 macOS guest 内的软件 Metal 栈。

它用于指导以下代码：

1. Metal Objective-C 代理层。
2. Rust 桥接与对象层。
3. guest 内渲染辅助进程。
4. metal2vulkan 接入层。
5. Vulkan loader 与 Lavapipe 打包层。
6. IOSurface 数据与同步层。
7. 系统显示注册与输出层。

本规格不是现状报告。实现必须遵守这里的边界、接口和验收门。

## 0.1 证据标签

每项结论必须带下列标签之一：

| 标签 | 含义 | 可否直接编码 |
|---|---|---|
| `KNOWN` | 已由本地二进制、源码或公开 ABI 直接证明 | 可以 |
| `INFERRED` | 多项证据支持，但未在目标 guest 实测 | 只能做可替换实现 |
| `BLOCKED` | 缺少二进制、精确 ABI 或系统实测 | 不可以写死 |
| `TESTED` | 已在 25G325 x86_64 guest 通过验收 | 可以作为兼容基线 |

`BLOCKED` 项不得用占位值伪装成已实现。

## 0.2 规范词

- **必须**：违反后不得合入主线。
- **应该**：默认执行，除非记录原因。
- **可以**：允许选项，不构成承诺。
- **禁止**：即使短期能运行，也不得进入交付路径。

## 1. 不可改变的边界

| 约束 | 状态 | 规则 |
|---|---|---|
| 宿主不可控制 | `KNOWN` | 不修改 QEMU、KVM、Hyper-V 或云平台 VMM |
| 宿主 GPU 不可假定 | `KNOWN` | 不依赖直通、VirGL、Venus、宿主 Metal 或 Vulkan |
| 全部运行件位于 guest | `KNOWN` | 驱动、helper、Vulkan loader、Lavapipe 全部随 guest 交付 |
| 目标架构为 x86_64 | `KNOWN` | arm64 二进制只能当协议证据 |
| AIR 转换复用上游 | `KNOWN` | 使用 metal2vulkan，不维护第二套 AIR 编译器 |
| CPU Vulkan 后端 | `INFERRED` | 首选 guest 内 Lavapipe |
| 进程隔离 | `INFERRED` | Mesa、LLVM、AIR 编译放入受管 helper |
| 系统显示与 GPU 执行分层 | `KNOWN` | 两者使用独立接口和失败域 |

AppleParavirtGPU 和 reims-vgpu 只能作为协议参考。

它们不得成为交付时的宿主依赖。

## 1.1 禁止项

1. 禁止修改宿主设备模型。
2. 禁止依赖宿主安装 Vulkan ICD。
3. 禁止继续扩展手写 Gallium ABI。
4. 禁止把 AIR bitcode 直接交给 llvmpipe。
5. 禁止用一个通用 IMP 响应不同 selector。
6. 禁止让 `respondsToSelector:` 对未知方法返回真。
7. 禁止把 raw pointer、Objective-C `id` 或 Vulkan handle 跨进程传递。
8. 禁止在完成渲染前触发 Metal completion handler。
9. 禁止声明未通过测试的 Metal family 或 feature。
10. 禁止把模拟测试当作像素或系统集成证据。

## 2. 交付范围

### 2.1 首版必须完成

```text
真实 metallib
  -> Metal Objective-C API
  -> guest helper
  -> metal2vulkan
  -> guest Vulkan loader
  -> guest Lavapipe
  -> 真实 IOSurface
  -> guest 显示输出
```

首版分为三个可独立验收的竖切：

| 竖切 | 输出 | 系统依赖 |
|---|---|---|
| A | Lavapipe 清屏到真实 IOSurface | 无 Metal 注册，无 WindowServer |
| B | 真实 metallib 三角形到同一 IOSurface | metal2vulkan，仍无 WindowServer |
| C | Metal.framework 枚举设备并产生首帧 | 私有注册 ABI 与显示层 |

### 2.2 首版不做

- 光线追踪。
- Mesh shader。
- 稀疏资源。
- 性能计数器。
- 动态库和函数指针。
- 多 GPU。
- 跨进程原生 `MTLSharedEvent`。
- 无损视频编码。
- 性能优化。

实现不得为这些功能声明支持。

## 3. 总体架构

```text
Metal client / WindowServer
          |
          v
Metal.framework
          |
          v
Objective-C proxy bundle
  - 精确 selector ABI
  - retain/release
  - descriptor 解码
  - callback 派发
          |
          | XPC/Mach 控制消息
          | IOSurface Mach right
          v
Render helper
  - 客户端命名空间
  - 对象表与 generation
  - metal2vulkan-runtime
  - Vulkan loader
  - Lavapipe ICD
          |
          v
IOSurface CPU pages
          |
          +--> guest linear framebuffer sink
          |
          +--> guest network display sink
```

系统显示提供者是独立组件：

```text
WindowServer
    -> guest display provider
    -> scanout IOSurface
    -> render completion wait
    -> DisplaySink
```

## 3.1 三条数据线

| 数据线 | 内容 | 禁止内容 |
|---|---|---|
| 控制线 | 对象 ID、描述符、命令、状态、错误 | raw pointer、进程内 handle |
| 数据线 | IOSurface、受限共享内存、metallib bytes | 任意文件路径 |
| 同步线 | request sequence、logical completion value、terminal event | 假完成、raw Vulkan handle |

## 4. 组件职责

### 4.1 Objective-C proxy bundle

必须：

1. 以目标系统接受的方式被 Metal.framework 加载。
2. 实现真实 Objective-C 对象族。
3. 为每个 selector 使用精确类型编码。
4. 转换 descriptor、block、`NSError **` 和返回对象。
5. 管理客户端对象与 helper 对象的对应关系。
6. 在 helper 失败时返回确定错误。
7. 不加载 Mesa 或 LLVM。

不得：

- 直接持有 Vulkan 对象。
- 执行 AIR 编译。
- 在 WindowServer 内运行 Lavapipe。
- 为未知 selector 自动装入默认函数。

### 4.2 Render helper

必须：

1. 由 launchd 或等价系统服务监督。
2. 每个客户端使用独立对象命名空间。
3. 验证每条消息的版本、大小和所有权。
4. 承载 metal2vulkan、Vulkan loader 和 Lavapipe。
5. 维护每条 logical queue 的单调 `queue_seq`。
6. 只在渲染与内存可见后回复完成。
7. 崩溃重启后增加 generation。
8. 拒绝旧 generation 的所有对象。

### 4.3 metal2vulkan 接入层

`KNOWN`：上游提供 AIR 解析、AIR 到 SPIR-V、Metal 对象语义。

接入层必须：

- 固定上游 commit。
- 保存源码 commit 与补丁哈希。
- 保留 typed error。
- 保留编译 deadline 和预算。
- 记录每次 refusal 与 degradation。
- 完整保留 PipelineArtifact、BindingPlan、layout、interface 和 requirements。
- 禁止自行推导 descriptor binding 或修补 SPIR-V。
- 不复制上游已有实现。

当前参考 commit：

`0dfdbcd59d235e37ba13b87a5ab30835b5bb9e35`

此值在正式 vendor 前必须再次核验。

### 4.4 Vulkan loader 与 Lavapipe

首选方式：标准 Vulkan loader 动态加载独立 Lavapipe ICD。

必须：

1. loader、ICD、LLVM 随 guest 包安装。
2. helper 显式选择随包 loader。
3. helper 只暴露随包 ICD。
4. 启动日志记录绝对路径、版本和 SHA-256。
5. 设备必须是 CPU Vulkan 设备。
6. 必须支持 Vulkan 1.2 和 timeline semaphore。
7. 不直接调用 Mesa 私有 Gallium 接口。

静态链接 Lavapipe 仅在动态 ICD 被实测阻断后评估。

## 5. Metal 设备发现合同

### 5.1 证据状态

| 项目 | 状态 | 直接证据 |
|---|---|---|
| B-001 设备枚举静态链 | `KNOWN` | 25G325 x86_64 BaseSystem Metal 与 IOAccelerator |
| B-002 plugin 发现静态链 | `KNOWN` | Metal、libsystem_sandbox 与 payload plist |
| B-003 initializer ABI | `KNOWN` | framework、Intel、AMD 四份 method record |
| 目标 guest 动态行为 | `BLOCKED` | 尚无 25G325 x86_64 guest trace |
| installed SystemOS IOGPU | `BLOCKED` | 尚无 exact Mach-O、UUID 与 SHA-256 |
| 第三方 bundle trust | `BLOCKED` | 静态 gate 已知，实际加载受 B-009 阻断 |

当前 Metal 样本 UUID 为 `FDB3FD2C-840A-3FC3-81FB-C524F891F642`。

当前 IOAccelerator 样本 UUID 为 `4FDBB3F6-9AA3-352B-87ED-57161AA64D1F`。

它们来自 25G325 BaseSystem，不代表 installed SystemOS 同字节。

### 5.2 枚举与创建设备链

`KNOWN`：静态调用链固定如下：

```text
MTLCopyAllDevices / MTLCreateSystemDefaultDevice
  -> MTLDeviceArrayInitialize
  -> _MTLRegisterDevices
  -> IOMainPort
  -> IOServiceMatching("IOAccelerator")
  -> IOServiceAddMatchingNotification("IOServicePublish")
  -> IOIteratorNext
  -> _getMetalPluginClassForService
  -> MTLIOAccelService
  -> [pluginClass alloc]
  -> initWithAcceleratorPort:(io_service_t)service
  -> IOAccelDeviceCreateWithAPIProperty(service, "Metal")
  -> IOServiceOpen(service, mach_task_self_, 5, &connection)
  -> _MTLAddDevice
  -> device array
```

关键 RVA：

| 入口 | 映像 | RVA | 状态 |
|---|---|---:|---|
| `_MTLCopyAllDevices` | Metal | `+0x1632` | `KNOWN` |
| `_MTLCreateSystemDefaultDevice` | Metal | `+0x17A91` | `KNOWN` |
| `_MTLAddDevice` | Metal | `+0x23B0` | `KNOWN` |
| `_MTLRegisterDevices` | Metal | `+0x1D980D` | `KNOWN` |
| `_getMetalPluginClassForService` | Metal | `+0x1D89FB` | `KNOWN` |
| `_IOAccelDeviceCreateWithAPIProperty` | IOAccelerator | `+0xF60` | `KNOWN` |
| `_IOAccelDeviceGetConnect` | IOAccelerator | `+0x12EF` | `KNOWN` |

`_MTLAddDevice` 要求对象同时遵守 `MTLDevice` 和 `MTLDeviceSPI`。

它随后调用 `initLimits`、`initFeatureQueries`、`initGPUFamilySupport`。

`INFERRED`：v1 Device proxy 必须继承 `_MTLIOAccelDevice`。

它必须调用 superclass `initWithAcceleratorPort:`。

这样复用 type-5 打开和 framework 基类行为。

只继承 `_MTLDevice` 需要另行证明等价性。

`BLOCKED`：目标 trace 必须记录三个 init 方法的下游 selector。

任何新增硬依赖都必须加入精确 ABI 表。

禁止用动态 selector fallback 伪造这些方法。

### 5.3 plugin bundle 发现

Metal.framework 从 `IOAccelerator` service 读取属性。

| 项目 | 精确合同 | 状态 |
|---|---|---|
| `MetalPluginName` | service 上的 `CFString` basename | `KNOWN` |
| `MetalPluginClassName` | service 上的可选 `CFString` | `KNOWN` |
| 第一候选 | `/Library/GPUBundles/<name>.bundle` | `KNOWN` |
| 第二候选 | `/System/Library/Extensions/<name>.bundle` | `KNOWN` |
| 指定类 | `-[NSBundle classNamed:]` | `KNOWN` |
| 类 fallback | `-[NSBundle principalClass]` | `KNOWN` |
| 类门 | 必须是 `_MTLDevice` 子类 | `KNOWN` |
| trust 类 | `KernelExtensionManagement` | `KNOWN` |

`MetalPluginName` 不得包含目录或 `.bundle` 后缀。

仅把 key 写进 bundle `Info.plist` 不会注册设备。

同名 key 必须发布在匹配的 IOKit service 上。

候选目录必须存在，并通过 `gpu_bundle_is_path_trusted`。

`/Library/GPUBundles` 的交付可行性仍由 B-009 实测决定。

若 trust gate 拒绝，禁止绕过 rootless。

### 5.4 initializer 与 type-5 UserClient

精确声明必须等价于：

```objc
- (instancetype)initWithAcceleratorPort:(io_service_t)service;
```

精确 encoding 为：

```text
@20@0:8I16
```

唯一参数是 32-bit `io_service_t` Mach name。

它不是 `io_connect_t`，也不是指针或 64-bit 整数。

x86_64 调用时，参数位于 `EDX`。

`IOServiceOpen` 成功后才产生 type-5 `io_connect_t`。

`IOAccelDeviceRef+0x14` 保存该 connection。

IOAccelerator 的 v1 创建序列为：

| selector | payload 或输出上限 | 失败规则 | 状态 |
|---:|---:|---|---|
| 9 | API 字符串 16 bytes | 错误被忽略 | `KNOWN` |
| 2 | `0x258` bytes | 创建失败 | `KNOWN` |
| 0 | `0x40` bytes | 创建失败 | `KNOWN` |
| 7 | `0x18` bytes | 可选，失败继续 | `KNOWN` |

initializer 失败必须 release 半成品，并返回 `nil`。

不得把半初始化对象交给 `_MTLAddDevice`。

### 5.5 `MTLCopyAllDevices` 合同

`MTLCopyAllDevices` 返回当前数组的 retained immutable copy。

数组顺序是 `_MTLAddDevice` 的 append 顺序。

设备必须依次通过：

1. plugin class gate。
2. initializer 非 `nil`。
3. `MTLDevice` conformance。
4. `MTLDeviceSPI` conformance。
5. 可选 `ALLOWED_GPU_IDS` 过滤。
6. `_registerInterestNotification` 成功。

同一 `io_service_t` 再次发布时必须去重。

hot-plug 继续走 `IOServicePublish` callback。

### 5.6 默认设备合同

`MTLCreateSystemDefaultDevice` 先建立同一 device array。

CoreGraphics 将选择转交 SkyLight。

SkyLight 用 display accelerator port 匹配设备 `acceleratorPort`。

多 alias 时，优先非 `isLowPower` 设备。

`deviceNameMatch` 可执行严格名称筛选。

`preferRemovable` 和 `avoidRemovable` 可改变选择。

无有效显示映射时，可回退到数组首项。

数组为空时必须返回 `nil`。

返回对象遵守 Create ownership。

### 5.7 失败合同

| 失败点 | 结果 | 状态 |
|---|---|---|
| IOMainPort 或通知注册失败 | device array 保持空 | `KNOWN` |
| plugin name 缺失或非字符串 | 跳过 service | `KNOWN` |
| bundle 路径或 trust 失败 | 跳过 service | `KNOWN` |
| class 不是 `_MTLDevice` 子类 | 跳过 service | `KNOWN` |
| type-5 open 失败 | initializer 返回 `nil` | `KNOWN` |
| selector 2 或 0 失败 | 创建失败 | `KNOWN` |
| MTLDevice/SPI conformance 失败 | framework assertion | `KNOWN` |
| registry ID 不在 allow-list | 不加入数组 | `KNOWN` |

不得导出自定义同名函数绕过 framework 枚举。

不得把 BaseSystem 静态证据标成目标 guest `TESTED`。

## 6. Objective-C ABI 合同

### 6.1 对象族

首版对象族如下：

| 对象 | 首次需要阶段 | 后端对象 |
|---|---|---|
| Device | 枚举 | helper client/device |
| CommandQueue | 清屏 | runtime command queue |
| CommandBuffer | 清屏 | runtime command buffer |
| RenderCommandEncoder | 清屏 | runtime render encoder |
| BlitCommandEncoder | IOSurface 验证 | runtime blit encoder |
| Buffer | 三角形 | runtime buffer |
| Texture | 清屏 | runtime texture |
| Library | 三角形 | AIR library |
| Function | 三角形 | AIR function |
| RenderPipelineState | 三角形 | Vulkan pipeline |
| SamplerState | UI shader | Vulkan sampler |
| DepthStencilState | UI shader | Vulkan depth state |
| Drawable proxy | 系统显示 | scanout IOSurface |

Compute、Heap、Fence、Event 在对应能力启用后加入。

### 6.2 ABI 硬规则

1. 每个 selector 必须有唯一 IMP。
2. IMP 必须匹配完整 Objective-C type encoding。
3. 结构体参数必须按 x86_64 Darwin ABI 传递。
4. 返回结构体不得伪装成对象指针。
5. block 必须复制，并在最终调用后释放。
6. `NSError **` 只在失败时写入。
7. `new`、`copy`、`alloc`、`mutableCopy` 返回 retained 对象。
8. 其他对象返回遵守 Cocoa 命名规则。
9. helper object ID 不得作为 Objective-C 指针暴露。
10. `dealloc` 只执行一次，并调用 superclass。
11. helper 的 `DESTROY` 处理必须幂等。
12. 未列 selector 不得动态安装。
13. 禁止自定义“全真”`respondsToSelector:`。
14. descriptor getter 必须由 typed Objective-C shim 调用。
15. Rust 只接收已归一化的 C ABI 值。

首选静态 Objective-C 类，让编译器生成调用约定。

若使用 `class_addMethod`，必须逐字使用下表 encoding。

### 6.2.1 精确 x86_64 encoding

| selector | exact encoding | 证据状态 |
|---|---|---|
| `dealloc` | `v16@0:8` | `KNOWN`，AMD/Intel method records |
| `initWithAcceleratorPort:` | `@20@0:8I16` | `KNOWN`，framework/AMD/Intel records |
| `newCommandQueue` | `@16@0:8` | `KNOWN`，AMD/Intel records |
| `newTextureWithDescriptor:iosurface:plane:` | `@40@0:8@16^{__IOSurface=}24Q32` | `KNOWN`，AMD/Intel records |
| `commandBuffer` | `@16@0:8` | `KNOWN`，AMD/Intel records |
| `renderCommandEncoderWithDescriptor:` | `@24@0:8@16` | `KNOWN`，AMD/Intel records |
| `endEncoding` | `v16@0:8` | `KNOWN`，AMD/Intel records |
| `commit` | `v16@0:8` | `KNOWN`，AMD/Intel records |
| `waitUntilCompleted` | `v16@0:8` | `KNOWN`，AMD/Intel records |
| `status` | `Q16@0:8` | `KNOWN`，AMD/Intel records |
| `error` | `@16@0:8` | `KNOWN`，AMD/Intel records |
| `addCompletedHandler:` | `v24@0:8@?16` | `KNOWN`，AMD/Intel records |
| `newLibraryWithData:error:` | `@32@0:8@16^@24` | `KNOWN`，AMD/Intel records |
| `newFunctionWithName:` | `@24@0:8@16` | `KNOWN`，25G325 Metal `MTLLibrary` protocol record |
| `newRenderPipelineStateWithDescriptor:error:` | `@32@0:8@16^@24` | `KNOWN`，AMD/Intel records |
| `newBufferWithBytes:length:options:` | `@40@0:8r^v16Q24Q32` | `KNOWN`，AMD/Intel records |
| `setRenderPipelineState:` | `v24@0:8@16` | `KNOWN`，AMD/Intel records |
| `setVertexBuffer:offset:atIndex:` | `v40@0:8@16Q24Q32` | `KNOWN`，AMD/Intel records |
| `drawPrimitives:vertexStart:vertexCount:` | `v40@0:8Q16Q24Q32` | `KNOWN`，AMD/Intel records |
| `name` | `@16@0:8` | `KNOWN`，AMD/Intel records |
| `registryID` | `Q16@0:8` | `KNOWN`，AMD/Intel records |
| `isLowPower` | `c16@0:8` | `KNOWN`，AMD/Intel records |
| `isHeadless` | `c16@0:8` | `KNOWN`，AMD/Intel records |
| `isRemovable` | `c16@0:8` | `KNOWN`，AMD/Intel records |
| `hasUnifiedMemory` | `c16@0:8` | `KNOWN`，AMD/Intel records |
| `maxBufferLength` | `Q16@0:8` | `KNOWN`，AMD/Intel records |
| `maxThreadsPerThreadgroup` | `{?=QQQ}16@0:8` | `KNOWN`，AMD/Intel records |
| `maxThreadgroupMemoryLength` | `Q16@0:8` | `KNOWN`，AMD/Intel records |
| `supportsFamily:` | `c24@0:8q16` | `KNOWN`，AMD/Intel records |
| `supportsFeatureSet:` | `c24@0:8Q16` | `KNOWN`，AMD/Intel records |
| `supportsTextureSampleCount:` | `c24@0:8Q16` | `KNOWN`，AMD/Intel records |
| `device` | `@16@0:8` | `KNOWN`，AMD/Intel records |
| `commandQueue` | `@16@0:8` | `KNOWN`，AMD/Intel records |
| `label` | `@16@0:8` | `KNOWN`，AMD/Intel records |
| `setLabel:` | `v24@0:8@16` | `KNOWN`，AMD/Intel records |
| `length` | `Q16@0:8` | `KNOWN`，AMD/Intel records |
| `contents` | `^v16@0:8` | `KNOWN`，AMD/Intel records |
| resource option getters | `Q16@0:8` | `KNOWN`，AMD/Intel records |
| texture scalar getters | `Q16@0:8` | `KNOWN`，AMD/Intel records |

`newFunctionWithName:` 的新增直接证据如下：

| 项目 | 值 |
|---|---|
| 样本 | 25G325 x86_64 BaseSystem Metal.framework |
| protocol list | `0x7FF80B3A46D8` |
| method record | `0x7FF80B3A46F8` |
| type string | `0x7FF80B44B975` |
| encoding | `@24@0:8@16` |

该证据已写入持久化 Metal IDB。

以上均为静态 `KNOWN`，不是目标 guest `TESTED`。

### 6.3 对象状态

```text
Allocated
  -> Connected
  -> Alive
  -> Invalidating
  -> Dead
```

规则：

- 只有 `Alive` 对象可以创建新对象。
- helper generation 改变后，对象进入 `Dead`。
- `Dead` 对象不得自动绑定新 helper。
- Objective-C runtime 管理本地 retain count。
- Queue 强持有 Device。
- CommandBuffer 强持有 Queue。
- Encoder 强持有 CommandBuffer。
- Function 强持有 Library 和 Device。
- 在途提交强持有全部资源 snapshot。
- 普通 parent release 不得使活 child 失效。
- generation 变化或 device loss 才使整树失效。
- `DESTROY` 只撤销客户端外部 lease。
- helper 内部或在途 clone 必须继续保活。
- 同一 issued handle 的重复 `DESTROY` 返回成功。
- 当前 generation 内的 `id` 永不复用。

`dealloc` 必须依次：

1. 原子切换到 `Invalidating`。
2. 清空本地 ivar 和 block。
3. 发送一次 best-effort `DESTROY`。
4. 调用 superclass `dealloc`。
5. 不等待 helper 回复。

每个 remote handle 最多对应一个活 proxy。

弱 cache 只保持 `device` 和 `commandQueue` pointer identity。

弱 cache 不延长对象寿命。

### 6.4 最小清屏 selector

| 类 | selector | 返回/错误 | 后端动作 |
|---|---|---|---|
| Device | `newCommandQueue` | retained queue 或 `nil` | 创建队列 |
| Device | `newTextureWithDescriptor:iosurface:plane:` | retained texture 或 `nil` | 导入 IOSurface plane |
| CommandQueue | `commandBuffer` | autoreleased buffer 或 `nil` | 创建命令缓冲 |
| CommandBuffer | `renderCommandEncoderWithDescriptor:` | encoder 或 `nil` | 解码 render pass |
| RenderEncoder | `endEncoding` | `void` | 封闭命令列表 |
| CommandBuffer | `commit` | `void` | 提交 helper |
| CommandBuffer | `waitUntilCompleted` | `void` | 仅在本地终态后返回 |
| CommandBuffer | `status` | 状态枚举 | 读取状态 |
| CommandBuffer | `error` | `NSError *` | 读取 typed error |
| CommandBuffer | `addCompletedHandler:` | `void` | 登记一次性 block |

清屏使用 render pass 的 load action。

它不需要 shader 或 pipeline。

### 6.5 最小三角形 selector

| 类 | selector | 后端动作 |
|---|---|---|
| Device | `newLibraryWithData:error:` | 解析真实 metallib |
| Library | `newFunctionWithName:` | 选择 AIR 函数 |
| Device | `newRenderPipelineStateWithDescriptor:error:` | 编译 SPIR-V 和 Vulkan pipeline |
| Device | `newBufferWithBytes:length:options:` | 创建顶点数据 |
| RenderEncoder | `setRenderPipelineState:` | 绑定 pipeline |
| RenderEncoder | `setVertexBuffer:offset:atIndex:` | 绑定顶点 buffer |
| RenderEncoder | `drawPrimitives:vertexStart:vertexCount:` | 记录 draw |
| RenderEncoder | `endEncoding` | 封闭命令列表 |
| CommandBuffer | `commit` | 提交 |

每次调用必须先生成不可变 descriptor snapshot。

调用返回后，不得再读取调用者的 mutable descriptor。

Rust 不得使用无类型 `objc_msgSend` 猜 getter ABI。

v1 只接受下列 profile：

| snapshot | 必须接受 | 必须拒绝 |
|---|---|---|
| IOSurface texture | 2D、BGRA8、单 plane、单 mip、单 slice、sample 1 | tiled、压缩、多 plane、多 sample |
| Render pass | color 0、Clear/Load/DontCare、Store | resolve、depth、stencil、其他 color |
| Pipeline | vertex+fragment、BGRA8、blend off、sample 1 | vertex descriptor、tessellation、ICB、mesh |
| Draw | triangle、slot 0、instance count 1 | 超出 `u32` 的 start/count/index |

所有枚举和 flags 必须 checked-convert。

所有非有限 clear color 必须拒绝。

任何未列非默认字段必须返回 `Unsupported`。

`newLibraryWithData:error:` 的输入是 `dispatch_data_t`。

实现必须映射或分段复制，不得假定为 `NSData *`。

`newBufferWithBytes:length:options:` 返回前必须复制输入字节。

禁止用固定 shader 或默认 pipeline 替代调用者输入。

### 6.6 线程规则

| 对象 | 并发规则 |
|---|---|
| Device | 可并发创建资源 |
| CommandQueue | 可并发创建 command buffer |
| CommandBuffer | 同时只允许一个 open encoder |
| Encoder | 固定创建线程，`endEncoding` 后封闭 |
| Resource | 生命周期线程安全；内容同步由命令决定 |
| Callback list | 内部加锁；取出后再调用 block |
| IPC receiver | 不执行用户 block 或昂贵编译 |
| Helper object table | 锁内 lookup 和 clone，锁外调用 runtime |

proxy 在 queue lock 内分配单调 `queue_seq`。

helper 必须按 `queue_seq` 串行 replay 和 commit。

同一 queue 的事件按 `queue_seq` 发布。

不同 queue 不承诺相对顺序。

锁顺序固定如下：

```text
connection
  -> queue sequencer
  -> command buffer
  -> callback list
```

未知线程规则必须按更严格方式实现。

### 6.7 Getter 与 identity

| getter | 规则 |
|---|---|
| `device` | 返回 child 强持有的同一 Device proxy |
| `commandQueue` | 返回 CommandBuffer 强持有的同一 Queue proxy |
| `name`, `registryID` | 返回 generation 内冻结 snapshot |
| topology getters | 返回 capability profile snapshot |
| limit getters | 返回 protocol、runtime、quota、test 的最小值 |
| `label` | proxy 本地保存；可用时同步 helper |
| Buffer scalar getters | 返回创建 snapshot，不做 IPC |
| Texture scalar getters | 返回创建 snapshot，不做 IPC |
| Buffer `contents` | 无共享映射合同时返回 `NULL` |

getter 不得返回 Rust reference 或 Vulkan handle。

CommandBuffer label 在 v1 可以只保存在 proxy。

## 7. Rust FFI 与对象表合同

### 7.1 Handle 格式

跨进程 handle 必须是 typed XPC dictionary：

```text
{
    kind: u64,
    flags: u64,
    generation: u64,
    id: u64
}
```

禁止把 C 或 Rust struct bytes 放上 wire。

| kind | 值 | 对象 |
|---|---:|---|
| Device | 1 | runtime device |
| Queue | 2 | command queue |
| CommandBuffer | 3 | command buffer record |
| Buffer | 4 | runtime buffer |
| Texture | 5 | texture 与 IOSurface lease |
| Library | 6 | AIR library |
| Function | 7 | AIR function |
| RenderPipeline | 8 | render pipeline state |

规则：

- v1 `flags` 必须为零。
- `id` 必须非零。
- 可空引用使用 XPC null 或缺失字段。
- `generation` 必须等于 connection generation。
- `kind` 必须与请求字段匹配。
- 客户端不能访问其他 namespace。
- 同一 `id` 不得在当前 generation 重用。
- 不存在的普通 handle 返回 `StaleHandle`。
- 已签发 handle 的重复 `DESTROY` 返回成功。

本地 C ABI 可以传四个归一化标量。

它不得把 wire dictionary 伪装成内存 struct。

helper generation 使用持久化非零 32-bit epoch。

wire 中将该值无损扩展到 `u64`。

每次 helper 启动都必须原子增加 epoch。

进程静态变量不能满足跨崩溃要求。

最终状态文件路径受 B-007 阻断。

### 7.2 错误合同

helper 错误必须映射成稳定类别：

| 类别 | 值 | 含义 |
|---|---:|---|
| `InvalidArgument` | 1 | 描述符、范围或状态无效 |
| `Unsupported` | 2 | 功能未声明支持 |
| `OutOfMemory` | 3 | guest 内分配失败 |
| `CompileFailed` | 4 | AIR、metallib 或 pipeline 失败 |
| `DeviceLost` | 5 | helper 或 Vulkan device 失效 |
| `Timeout` | 6 | compile 或已终止 generation 超时 |
| `ProtocolError` | 7 | IPC 版本、schema 或 namespace 错误 |
| `InternalError` | 8 | 其他已捕获错误 |

panic、abort 和 Vulkan 错误不得穿过 FFI。

wire error 固定包含：

| key | type |
|---|---|
| `category` | `u64` |
| `source_kind` | string，最多 128 bytes |
| `source_code` | `i64` |
| `message` | string，最多 4096 bytes |
| `retryable` | Boolean |

`NSError` domain 固定为 `GuestMetalBridgeErrorDomain`。

`NSError` code 使用稳定类别值。

userInfo 只保存 bounded source 和 request IDs。

不得保存完整 shader 或像素。

未知 upstream error variant 必须映射 `InternalError`。

Rust unwind 不得穿过 FFI。

## 8. IPC 合同

### 8.1 传输

首版使用 XPC/Mach。

控制消息使用 typed XPC dictionary。

大数据使用受限共享内存对象。

IOSurface 使用 Mach right 或 XPC surface 对象。

禁止把 C/Rust 结构体原样强转为 wire bytes。

### 8.2 Request envelope

每条 request 固定包含：

| key | XPC type | 规则 |
|---|---|---|
| `v` | unsigned integer | 必须为 1 |
| `kind` | unsigned integer | 必须是已列消息 |
| `request_id` | unsigned integer | 非零并严格递增 |
| `client_id` | unsigned integer | `HELLO` 为 0，其余匹配 connection |
| `generation` | unsigned integer | `HELLO` 为 0，其余匹配当前值 |
| `declared_bytes` | unsigned integer | 必须等于 helper 重算值 |
| `body` | dictionary | 只允许该消息定义的 key |

reply 固定包含：

```text
v, kind, request_id, generation, ok
```

`ok=true` 时只能包含 `body`。

`ok=false` 时只能包含 `error`。

helper 必须把 namespace 绑定到 XPC audit token。

请求内的 `client_id` 不能选择 namespace。

未知 key、错误 type 或长度不符都是 `ProtocolError`。

### 8.3 消息集

| kind | 值 | body | reply 或 event |
|---|---:|---|---|
| `HELLO` | 1 | min/max version、nonce | client、generation、device、capabilities |
| `CREATE_QUEUE` | 2 | Device handle、在途上限 | Queue handle |
| `IMPORT_SURFACE` | 3 | Device、surface right、plane、snapshot | Texture、两轴导入模式 |
| `CREATE_BUFFER_BYTES` | 4 | Device、options、blob | Buffer handle |
| `CREATE_LIBRARY` | 5 | Device、metallib blob | Library handle |
| `CREATE_FUNCTION` | 6 | Library、UTF-8 name | Function handle |
| `CREATE_RENDER_PIPELINE` | 7 | functions、pipeline snapshot | Pipeline handle |
| `CREATE_COMMAND_BUFFER` | 8 | Queue handle | CommandBuffer handle |
| `SUBMIT` | 9 | CommandBuffer、queue_seq、encoder logs | accepted；稍后事件 |
| `WAIT` | 10 | CommandBuffer、deadline_ms | 当前终态或 Timeout |
| `DESTROY` | 11 | 一个 typed handle | 幂等确认 |
| `CANCEL_CLIENT` | 12 | 空 | 确认后断开 |
| `EVENT_SCHEDULED` | 100 | CB、queue_seq、completion_value | server one-way |
| `EVENT_TERMINAL` | 101 | CB、queue_seq、终态、error、surface seeds | server one-way |
| `EVENT_DEVICE_LOST` | 102 | generation、stable error | server one-way |

`completion_value` 等于 logical queue 的 `queue_seq`。

它不是 Vulkan semaphore handle 或原始 counter。

v1 encoder log 最多包含 64 个 render encoder。

每个 command buffer 最多包含 65,536 条 command。

command kind 固定为：

| 值 | command |
|---:|---|
| 1 | `SET_RENDER_PIPELINE` |
| 2 | `SET_VERTEX_BUFFER` |
| 3 | `DRAW_PRIMITIVES` |

clear encoder 可以没有 command。

helper 仍必须创建 encoder，并执行 `end_encoding`。

helper 必须先验证完整 log，再调用 runtime。

验证失败时不得提交部分 command buffer。

### 8.4 Blob schema

| key | XPC type | 规则 |
|---|---|---|
| `transport` | unsigned integer | 0 inline；1 read-only OOL memory |
| `length` | unsigned integer | 等于实际 data 或 mapping 长度 |
| `sha256` | data[32] | helper 解析前重算 |
| `data` | data | 仅 inline，最多 1 MiB |
| `memory` | shared-memory object | 仅 OOL，当前受 B-007 阻断 |

Gate 2 和 Gate 3 fixture 必须各小于 1 MiB。

这样首批测试不依赖未取证的 OOL API。

超过 1 MiB 的输入必须走只读 OOL memory。

禁止把 64 MiB blob 塞进 control dictionary。

### 8.5 固定上限

| 项目 | v1 hard limit |
|---|---:|
| control payload | 1 MiB/request |
| dictionary depth | 4 |
| dictionary keys | 128/request |
| label | 256 UTF-8 bytes |
| error text | 4 KiB |
| inline blob | 1 MiB |
| metallib | 64 MiB；超过 1 MiB 必须 OOL |
| copied buffer | 1 GiB；超过 1 MiB 必须 OOL |
| IOSurface allocation | 1 GiB |
| surface width/height | 各 16,384 |
| encoder count | 64/command buffer |
| command count | 65,536/command buffer |
| uncompleted CB | 64/queue，256/client |
| live remote objects | 65,536/client |
| accounted allocations | 2 GiB/client |
| pipeline compile | 30 秒 |
| queue sequence gap | 10 秒 |
| liveness deadline | 60 秒 |

配置只能降低这些上限。

客户端请求不能提高上限。

所有乘加必须使用 checked arithmetic。

10 秒是健康检查，不是 Metal API 超时返回。

60 秒到达后，必须先确认 helper 已停止写入。

### 8.6 重试与一致性

mutating request 不得自动重试。

connection 中断会使整个 generation 失效。

helper 必须独立重算实际长度、深度和数量。

helper 不得只信任 `declared_bytes`。

## 9. IOSurface 合同

### 9.1 首版格式

首版只保证：

- 单 plane。
- `BGRA8Unorm`。
- 线性布局。
- 明确 `width`、`height`、`bytesPerRow`。
- 无压缩。
- 无 tiled layout。

其他格式返回 `Unsupported`。

### 9.2 导入检查

IOSurface 必须随 connection 传 capability 或 Mach right。

全局 IOSurface ID 只能用于诊断和交叉检查。

单独 ID 不得作为授权。

helper 取得自己的 `IOSurfaceRef` 后必须重读：

1. plane count。
2. base address。
3. allocation size。
4. width 与 height。
5. bytes per element。
6. bytes per row。
7. plane offset。
8. plane size。
9. 所有乘加是否溢出。
10. 请求范围是否落在 allocation 内。

单 plane BGRA8 必须满足：

```text
bytes_per_element == 4
bytes_per_row >= width * 4
offset + bytes_per_row * (height - 1) + width * 4 <= allocation_size
```

每一步都必须 checked。

不得信任客户端提供的重复字段。

### 9.3 两轴内存模式

host buffer 与 texture 必须分开报告。

| 轴 | 值 | 判定 |
|---|---|---|
| Host pages | `ImportedHostPages` | host-pointer import 成功，未复制 pages |
| Host pages | `CopiedHostPages` | runtime 报告 page copy degradation |
| Texture | `InPlaceImage` | 无 shadow，目标像素测试通过 |
| Texture | `ShadowedTexture` | runtime 使用 shadow，并在完成时写回 |

只有下面组合可称为直接路径：

```text
ImportedHostPages + InPlaceImage
```

buffer pages 被 import 不证明 texture 原地渲染。

两轴值必须写入 reply 和诊断日志。

`ShadowedTexture` 可用于早期 Gate 2。

任何 shadow 或 copy 都不得称为零拷贝。

`IOSurfaceLock/Unlock` flags、seed 和可见性顺序仍为 `BLOCKED`。

Gate 2 必须固定这些规则。

### 9.4 生命周期

- IOSurface right 必须覆盖全部在途提交。
- helper 必须持有自己的 `IOSurfaceRef`。
- runtime `KeepAlive` 必须持有 owner 和 mapping lease。
- texture 外部 lease 结束不能释放在途 clone。
- 首个 writer 前取得必要写 lease。
- 最后 writer 完成后执行 unlock、seed 或 merge-back。
- 客户端释放 proxy 不得提前解除 mapping。
- helper 崩溃后，客户端可以重新 import IOSurface。
- 旧 texture handle 不得复活。

## 10. 同步与完成合同

### 10.1 CommandBuffer 状态

```text
NotEnqueued
  -> Committed
  -> Scheduled
  -> Completed
  -> Error
```

`Completed` 和 `Error` 是互斥终态。

`Error` 可以从记录失败、Committed 或 Scheduled 进入。

v1 不实现 `enqueue`，所以不产生 `Enqueued`。

内部 `RecordingPoisoned` 仍对外显示 `NotEnqueued`。

调用 `commit` 时，它直接终结为 `Error`。

该路径不得提交 Vulkan 工作。

状态只允许向前移动。

重复或逆序终态必须忽略，并记录诊断。

每个 command buffer 只触发一次 terminal event。

### 10.2 完成条件

helper 只能在以下步骤完成后发送 `EVENT_TERMINAL`：

1. upstream completed handler 已运行。
2. upstream status 已冻结为 Completed 或 Error。
3. upstream error 已读取并冻结。
4. copied host pages 已 merge-back。
5. texture shadow 已写回。
6. IOSurface unlock、seed 或可见性操作完成。
7. 最终 stable error 已固定。

upstream completed handler 是 Vulkan semantic completion 边界。

adapter 不得读取 private Vulkan timeline 猜完成。

IOSurface 收尾失败必须得到 `Error/InternalError`。

不得先发 `Completed`，再报告 surface 错误。

### 10.3 Client 发布顺序

client 收到 terminal event 后必须：

1. 在锁内冻结 status、error 和 completion value。
2. 唤醒全部 waiter。
3. 取出 callback list。
4. 解锁。
5. 按登记顺序调用 block。

terminal event 若先到，先本地发布 `Scheduled`。

不同 queue 不承诺 callback 相对顺序。

callback 期间不得持有 connection 或对象表锁。

### 10.4 `waitUntilCompleted`

该 Objective-C 方法没有 timeout 返回值。

它只能在本地终态后返回。

10 秒只触发健康诊断。

60 秒触发 supervisor 处置。

supervisor 必须先终止当前 helper generation。

它还必须确认 helper 不会继续写 IOSurface。

确认后才能发布 `Timeout` 或 `DeviceLost`。

若无法确认，wait 必须继续阻塞。

外部 watchdog 可以终止调用进程。

不得伪造终态来突破时间上限。

### 10.5 Completion block

`addCompletedHandler:` 的非空 block 必须立即 `_Block_copy`。

block 只能在 `commit` 前登记。

commit 后登记必须产生确定 misuse diagnostic。

每个 block 只调用一次。

调用后必须立即 `_Block_release`。

用户 block exception 不得穿过 Rust 或 XPC。

Objective-C shim 必须捕获、记录并继续清理。

### 10.6 SharedEvent

首版不声明跨进程 `MTLSharedEvent`。

首版使用 logical `queue_seq` 和 IPC terminal event。

只有取得 Mach shared-event ABI 后，才能加入原生支持。

## 11. Metal 到 Vulkan 映射

### 11.1 Slice A/B 精确映射

固定上游 commit：

```text
0dfdbcd59d235e37ba13b87a5ab30835b5bb9e35
```

| Metal 或 adapter 操作 | upstream 路径 | symbol | 状态 |
|---|---|---|---|
| CPU Vulkan device | `metal2vulkan-runtime/src/device/create.rs` | `Device::system_default_with` | `KNOWN` |
| `newCommandQueue` | `metal2vulkan-runtime/src/queue.rs` | `Device::new_command_queue` | `KNOWN` |
| `commandBuffer` | `metal2vulkan-runtime/src/queue.rs` | `CommandQueue::command_buffer` | `KNOWN` |
| IOSurface owner | adapter gap | 无 upstream symbol | `KNOWN` gap |
| host memory lifetime | `metal2vulkan-runtime/src/host_memory.rs` | `HostMemory::new`, `KeepAlive` | `KNOWN` |
| IOSurface base buffer | `metal2vulkan-runtime/src/buffer_descriptor.rs` | `BufferDescriptor::new`, `BufferContents::NoCopy` | `KNOWN` |
| buffer creation | 同上 | `Device::new_buffer_with_descriptor` | `KNOWN` |
| IOSurface texture | `metal2vulkan-runtime/src/buffer_texture.rs` | `IoSurfacePlane::new` | `KNOWN` |
| IOSurface texture | 同上 | `Buffer::new_texture_with_iosurface_plane` | `KNOWN` |
| texture descriptor | `metal2vulkan-runtime/src/texture_descriptor.rs` | `TextureDescriptor` | `KNOWN` |
| render encoder | `metal2vulkan-runtime/src/render.rs` | `CommandBuffer::render_command_encoder` | `KNOWN` |
| clear pass | `metal2vulkan-runtime/src/render_pass.rs` | `RenderPassDescriptor` | `KNOWN` |
| load/store values | `metal2vulkan-runtime/src/render_values.rs` | `LoadAction::from_raw`, `StoreAction::from_raw` | `KNOWN` |
| `endEncoding` | `metal2vulkan-runtime/src/render.rs` | `RenderCommandEncoder::end_encoding` | `KNOWN` |
| metallib | `metal2vulkan-runtime/src/library.rs` | `Device::new_library_with_data` | `KNOWN` |
| function lookup | 同上 | `Library::new_function_with_name` | `KNOWN` |
| stage source | `metal2vulkan/src/pipeline/descriptor.rs` | `StageSource::Function` | `KNOWN` |
| pipeline descriptor | 同上 | `RenderPipelineDescriptor::new` | `KNOWN` |
| pipeline compile | `metal2vulkan-runtime/src/pipeline/render.rs` | `Device::new_render_pipeline_state` | `KNOWN` |
| vertex bytes | `metal2vulkan-runtime/src/buffer_descriptor.rs` | `Device::new_buffer_with_bytes` | `KNOWN` |
| resource options | `metal2vulkan-runtime/src/values.rs` | `ResourceOptions::from_raw` | `KNOWN` |
| bind pipeline | `metal2vulkan-runtime/src/render.rs` | `set_render_pipeline_state` | `KNOWN` |
| bind vertex buffer | 同上 | `set_vertex_buffer` | `KNOWN` |
| draw | 同上 | `draw_primitives` | `KNOWN` |
| commit | `metal2vulkan-runtime/src/command_buffer/mod.rs` | `CommandBuffer::commit` | `KNOWN` |
| scheduled event | 同上 | `add_scheduled_handler` | `KNOWN` |
| terminal event | 同上 | `add_completed_handler`, `status`, `error` | `KNOWN` |
| bounded helper wait | 同上 | `wait_until_completed_for` | `KNOWN` |
| internal timeline | `command_buffer/completion.rs` | `Completion`, `Submitted` | `KNOWN` |
| public raw timeline | adapter gap | 无 public upstream symbol | `KNOWN` gap |
| Objective-C objects | adapter gap | 无 upstream symbol | `KNOWN` gap |
| XPC/Mach transport | adapter gap | 无 upstream symbol | `KNOWN` gap |

helper 创建设备时必须：

```text
DeviceOptions::loader = package absolute loader path
DeviceOptions::kinds = [DeviceKind::Cpu]
```

IOSurface 必须先建立 backing Buffer。

texture 必须从该 Buffer 创建。

`KeepAlive` 不能省略。

helper 只在 `SUBMIT` replay 时创建真实 encoder。

proxy 不分配远端 encoder handle。

上述映射关闭 B-005 的 Slice A/B 合同。

它不证明目标 guest 已成功运行。

### 11.2 Shader 合同

- 输入必须是真实 metallib。
- AIR 解析必须由 metal2vulkan 完成。
- 生成 SPIR-V 必须通过上游 verifier。
- 可用时还要运行 `spirv-val`。
- 编译结果以输入哈希、设备 profile 和上游 commit 缓存。
- 编译失败必须返回完整 typed error。
- 禁止回退到空 shader。

## 12. 能力报告合同

每次 `HELLO` 必须生成不可变 `CapabilitySnapshot`。

公开能力来自下列交集：

```text
selector 与 ABI 已实现
  ∩ adapter 路径已实现
  ∩ metal2vulkan 已支持
  ∩ Lavapipe 已支持
  ∩ 25G325 guest test allow-list
```

snapshot hash 必须覆盖：

- selector table version。
- IPC protocol version。
- metal2vulkan commit。
- loader 与 ICD SHA-256。
- runtime device identity。
- hard limits。
- 已通过 test ID。

规则：

1. 未在交集内的能力返回 false。
2. `supportsFamily:` 不得用固定大值兜底。
3. `supportsFeatureSet:` 在 v1 固定返回 false。
4. `supportsTextureSampleCount:` 只回答已测试值。
5. 最大 buffer 值取 protocol、runtime、quota、test 的最小值。
6. threadgroup limits 采用同一最小值规则。
7. getter 只读取本地 snapshot，不做同步 IPC。
8. helper restart 必须生成新 profile version。
9. binary hash 变化必须生成新 profile version。
10. 现有 connection 的 snapshot 不得热更新。

在没有非零 target test limit 时，不得发布 framework device。

## 13. 系统显示合同

### 13.1 事实边界

`KNOWN`：Apple 图形栈把 accelerator 和 display 分开。

`KNOWN`：AppleParavirtDisplay 继承 `IOMobileFramebufferLegacy`。

`BLOCKED`：25G325 x86_64 的第三方 display 注册 ABI。

`BLOCKED`：WindowServer 到 framebuffer user client 的精确 selector。

因此，display 代码不能从 AppleParavirt 包格式直接照抄。

### 13.2 DisplaySink

系统显示层必须只依赖 guest 可见输出。

```text
DisplaySink
  - LinearFramebufferSink
  - NetworkDisplaySink
```

`LinearFramebufferSink`：

- 使用云平台已经提供的线性 framebuffer。
- 不要求宿主新增设备。
- 在 render completion 后复制或映射 scanout。
- 必须处理 stride、像素格式和刷新范围。

`NetworkDisplaySink`：

- 用于没有可写 framebuffer 的 guest。
- 输出在 guest 网络栈内完成。
- 不作为 Metal 执行依赖。

如果平台既无 framebuffer，又无网络输出，无法产生可见桌面。

### 13.3 首帧完成

首帧只有同时满足下列条件才算成功：

1. WindowServer 枚举到 display。
2. 有有效 mode。
3. WindowServer 提供 scanout IOSurface。
4. 对应 Metal command buffer 完成。
5. display provider 等待同一 frame sequence。
6. sink 获得正确像素。
7. swap completion 返回 WindowServer。
8. WindowServer 不发生超时或重启。

## 14. 故障与恢复

### 14.1 Helper 崩溃

XPC invalidation handler 必须用一次性 CAS 标记 connection dead。

proxy 随后必须：

1. 快照全部 nonterminal command buffer。
2. 将每个快照终结为 `Error/DeviceLost`。
3. 唤醒每个 waiter。
4. 调用每个 completion block 一次。
5. 保留已终态 command buffer 的原状态。
6. 使当前 generation 的 proxy 全部 `Dead`。
7. 拒绝新 helper 中的全部旧 handle。
8. 允许 supervisor 启动新 generation。

新 generation 只接受新建对象。

IOSurface capability 可以由客户端显式重新 import。

buffer、library、pipeline 和 command buffer 不自动重建。

不得静默把旧对象接到新 helper。

### 14.2 编译超时

- 取消编译任务。
- 返回 `CompileFailed` 或 `Timeout`。
- 不缓存半成品。
- 不影响其他客户端。

### 14.3 显示超时

- 不得永久阻塞 WindowServer。
- 返回失败的 swap completion。
- 可以保留上一帧或输出黑帧。
- 必须记录 frame sequence。

## 15. 安全合同

helper 把客户端、metallib 和 descriptor 当作不可信输入。

必须：

- 校验所有长度和乘法。
- 限制对象数与总内存。
- 限制编译时间和工作量。
- 按 audit token 隔离客户端。
- 禁止客户端传入任意文件路径。
- 禁止 helper 加载包外 ICD。
- 日志不得保存用户像素或完整 shader 数据。
- 崩溃日志可以保存哈希和错误位置。

## 16. 打包合同

建议包结构：

```text
System extension or KEXT
  - accelerator/display provider，若目标 ABI 要求

Metal proxy bundle
  - Objective-C classes
  - 小型 Rust/C ABI shim

Render helper
  - metal2vulkan-runtime
  - Vulkan loader
  - Lavapipe ICD
  - LLVM 依赖

Launch service
  - helper lifecycle
  - crash policy
  - logs

Version manifest
  - 每个二进制版本、来源、SHA-256、许可证
```

签名、entitlement、SIP 和 boot policy 当前为 `BLOCKED`。

它们必须在系统注册代码合入前完成实机验证。

## 17. 验收门

### Gate 0：规格证据闭合

通过条件：

- Metal.framework 注册链有直接证据。
- 最小 selector 有精确 x86_64 ABI。
- metal2vulkan 映射表落到真实 API。
- 未知项没有伪装成默认值。

当前结果：`PASS-STATIC`。

该结果只表示规格可以指导编码。

它不表示任何 guest 路径已经运行。

### Gate 1：Lavapipe 启动

通过条件：

- guest x86_64 成功加载随包 Vulkan loader。
- 只枚举到指定 Lavapipe ICD。
- Vulkan 1.2 和 timeline semaphore 可用。
- 保存路径、版本、SHA-256 和设备属性。

### Gate 2：真实 IOSurface 清屏

通过条件：

- 创建真实单 plane BGRA IOSurface。
- 先写入非零 sentinel。
- Lavapipe 完成 clear。
- 活动像素全部匹配目标 BGRA。
- row padding 保持 sentinel。
- 保存 raw bytes 和 SHA-256。
- 分别记录 `ImportedHostPages/CopiedHostPages`。
- 分别记录 `InPlaceImage/ShadowedTexture`。

### Gate 3：真实 metallib 三角形

通过条件：

- 输入由目标 SDK 生成。
- 保存 metallib SHA-256。
- 每个 SPIR-V stage 通过 verifier。
- 保存 PipelineArtifact、BindingPlan 和 requirements 指纹。
- 不丢弃上游 layout、interface 或固定功能状态。
- Vulkan validation 无错误。
- 固定采样点与 CPU reference 匹配。
- 保存 PNG、raw bytes 和哈希。

### Gate 4：Helper 隔离

通过条件：

- Gate 3 通过 IPC 重跑。
- 像素哈希与同进程版本一致。
- raw pointer 没有跨进程传递。
- 强制结束 helper 不会结束客户端。
- 所有在途 command buffer 进入 `Error`。
- 重启后旧 handle 被拒绝。

### Gate 5：Metal.framework 枚举

通过条件：

- `MTLCopyAllDevices` 能看到目标 device。
- `MTLCreateSystemDefaultDevice` 的选择可解释。
- registry ID 与 IOKit service 一致。
- 普通 Metal app 通过 proxy 重跑 Gate 3。
- 未使用自定义工厂直调绕过 framework。

### Gate 6：WindowServer 首帧

通过条件：

- WindowServer 枚举 display 和 mode。
- scanout IOSurface 与 frame sequence 可追踪。
- sink 输出正确测试图。
- swap completion 单调完成。
- WindowServer 不重启。

### Gate 7：恢复

通过条件：

- helper 崩溃不会拖死 WindowServer。
- 显示进入确定状态。
- helper 可受控重启。
- 新 generation 可重建资源。

## 18. 开发顺序

| 顺序 | 工作 | 允许开始条件 |
|---:|---|---|
| 1 | 冻结规格 1.0 | B-001 至 B-005 静态闭合 |
| 2 | vendor metal2vulkan | Gate 0 |
| 3 | guest Lavapipe 构建探针 | Gate 0 |
| 4 | 同进程 IOSurface clear | Gate 1 |
| 5 | 同进程 metallib triangle | Gate 2 |
| 6 | helper IPC | Gate 3 |
| 7 | Objective-C proxy 对象族 | Gate 4 与精确 ABI |
| 8 | Metal.framework 注册 | proxy ABI 与 B-009/B-012 |
| 9 | display provider | Gate 5 与 B-008/B-010 |
| 10 | WindowServer 首帧 | 前九项完成 |

不得从 selector 总表直接开始写完整驱动。

先实现每个 gate 的最小闭环。

## 19. 当前阻断项

| 编号 | 状态 | 项目 | 关闭或剩余证据 |
|---|---|---|---|
| B-001 | `CLOSED-KNOWN` | Metal.framework 设备枚举链 | 25G325 x86_64 BaseSystem 调用链与持久化 IDB |
| B-002 | `CLOSED-KNOWN` | plugin bundle 与 class 发现规则 | keys、路径顺序、class gate、trust gate |
| B-003 | `CLOSED-KNOWN` | `initWithAcceleratorPort:` 精确 ABI | `@20@0:8I16` 与 `io_service_t` 调用点 |
| B-004 | `CLOSED-KNOWN` | 最小 selector 精确 ABI | 完整声明表；`newFunctionWithName:` 已由 protocol record 补齐 |
| B-005 | `CLOSED-KNOWN` | proxy 到 metal2vulkan 映射 | 固定 commit 的逐操作 path 与 symbol 表 |
| B-006 | `BLOCKED` | IOSurface host import 实测 | Gate 2 日志、两轴模式与像素证据 |
| B-007 | `BLOCKED` | XPC 权限与 bootstrap 路径 | 目标 guest 实测 |
| B-008 | ~~`BLOCKED`~~ **已实质关闭** | ~~IOMobileFramebufferLegacy 用户 ABI~~ **盯错家族**：那是 ARM 路径。x86 走 `IOFramebuffer` / IOGraphicsFamily | 22 条 `IOFramebufferUserClient` selector 全表、`StdFBShmem_t` 240 字节布局、`clientMemoryForType` 内存类型、accelerator↔display 关联机制均已取得。见 `docs/spec/11-KERNEL-DISPLAY.md` |
| B-009 | `BLOCKED` | 第三方签名与加载策略 | `/Library/GPUBundles` target trust trace |
| B-010 | `BLOCKED` | 现有 framebuffer 输出路径 | 云平台设备与 guest 探针 |
| B-011 | `BLOCKED` | installed SystemOS framework 精确样本 | System Cryptex cache、IOGPU UUID、hash、IDB |
| B-012 | `BLOCKED` | framework device bootstrap 下游 selector | 三个 init 方法的目标 guest trace 与新增 ABI records |

`CLOSED-KNOWN` 表示静态合同可编码。

它不表示目标 guest 已经 `TESTED`。

## 20. 源材料

本规格依赖：

- `analysis/macos26-metal-user-spi.md`
- `analysis/macos26-iogpu-display-registration.md`
- `analysis/metal2vulkan-gap-architecture.md`
- `analysis/spec-work/metal-registration-contract.md`
- `analysis/spec-work/bridge-runtime-contract.md`
- `analysis/idb/macos26-25G325-arm64/`
- `analysis/idb/macos26-25G325-x86_64-frameworks/`
- `metal_drivers/AppleIntelICLGraphicsMTLDriver_decompressed.i64`
- `metal_drivers/AMDRadeonX6000MTLDriver_decompressed.i64`

合同 SHA-256：

| 文件 | SHA-256 |
|---|---|
| `metal-registration-contract.md` | `38344BEA4D45A33D45C2B3EB6DB7E4ED6B836AF7EC32A070381CD0C0B8374D0B` |
| `bridge-runtime-contract.md` | `7EEFFBE4D69E6D4ED7EF5255388C785F585A687ACAED9B61290B943AE7C0D717` |

arm64 IDB 只证明系统分层和 APV 内核协议。

厂商 x86_64 IDB 证明 selector 和 plugin 实现边界。

BaseSystem framework IDB 证明 B-001 至 B-004 静态合同。

BaseSystem 样本不得冒充 installed SystemOS 同字节样本。

B-011 保存该缺口和最小采集条件。

## 21. 规格完成定义

规格书达到 1.0，必须满足：

1. B-001 至 B-005 全部关闭。
2. 每个首版 selector 都有精确 ABI。
3. 每个对象都有所有权和线程规则。
4. 每条 IPC 消息都有字段和上限。
5. 每个 Metal 操作都有后端映射。
6. 每个完成事件都有唯一触发条件。
7. 每个未知能力都返回 false 或明确错误。
8. Gate 0 可由独立检查复核。

Gate 1 以后属于实现验证。

它们不会阻止规格 1.0，但会决定项目可行性。


## 22. Gate 0 审核记录

审核日期：2026-10-29。

审核结果：`PASS-STATIC`。

已复核：

1. B-001 至 B-005 均有直接静态证据。
2. `newFunctionWithName:` 已补齐精确 encoding。
3. 注册链关键调用已在 Metal IDB 复核。
4. type-5 open 已在 IOAccelerator IDB 复核。
5. bundle trust gate 已在 sandbox IDB 复核。
6. default-device 映射已在 SkyLight IDB 复核。
7. 四份新 IDB 已保存到长期目录。
8. 旧 parent-child 销毁规则已删除。
9. `dealloc` 与 `DESTROY` 语义已分开。
10. raw Vulkan timeline 不再出现在 wire 合同。
11. IOSurface 模式已改为两个独立轴。
12. `Completed` 与 `Error` 已改为互斥终态。
13. `waitUntilCompleted` 不再伪造 timeout 返回。
14. control payload 与 OOL blob 上限不再冲突。
15. Markdown code fence 成对，表格列数一致。

未执行：

- guest 构建。
- Lavapipe 启动。
- IOSurface 像素测试。
- XPC 权限测试。
- Metal.framework target trace。
- WindowServer 测试。

这些项目由 B-006 至 B-012 和 Gate 1 至 Gate 7 管理。

本文件现在可以指导实现。

实现仍须严格按 Gate 顺序推进。
