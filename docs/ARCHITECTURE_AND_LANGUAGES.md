# 架构、语言与工程目录

文档版本：1.0  
状态：有效设计，目录尚未创建

## 1. 进程和内核边界

```text
Client process
  Metal.framework
  Objective-C proxy
        |
        | Mach/XPC
        v
System render helper
  Rust object service
  metal2vulkan
  Vulkan loader
  Lavapipe
        |
        | IOSurface
        v
Kernel and display side
  IOGPU provider
  IOUserClient
  Display provider
  Display sink
```

LLVM、Mesa 和 AIR 编译不得进入 WindowServer。

## 2. 语言分工

| 组件 | 语言 | 原因 |
|---|---|---|
| Metal Device、Queue、Buffer 等类 | Objective-C | 直接匹配 Objective-C ABI |
| selector 实现 | Objective-C | 每个方法需要精确签名 |
| descriptor 解码 | Objective-C | 直接读取系统对象 |
| block callback | Objective-C | 正确 copy、调用和 release |
| NSError | Objective-C | 保持系统错误语义 |
| IOSurfaceRef 客户端边界 | Objective-C/C | 使用 Apple C framework |
| proxy 状态核心 | Rust | 安全状态机和并发 |
| IPC wire protocol | Rust | 长度校验、版本和对象所有权 |
| helper 对象表 | Rust | namespace、generation 和配额 |
| metal2vulkan adapter | Rust | 上游本身是 Rust |
| Vulkan loader 控制 | Rust | 与 `ash` 和 runtime 同层 |
| capability 和错误映射 | Rust | 单一规则来源 |
| helper 监督与恢复 | Rust | 进程状态和重建 |
| network display sink | Rust | 网络、编码和限流 |
| IOKit accelerator provider | C++ | XNU IOKit 驱动 ABI |
| IOUserClient | C++ | 内核对象和内存映射 |
| display provider | C++ | mode、swap、vblank 和 fence |
| framebuffer sink | C++ | 现有 guest 设备接入 |
| ObjC 与 C++ 窄交界 | Objective-C++ | 只在两种 ABI 相交时使用 |
| Lavapipe、Mesa、Vulkan loader | 上游 C/C++ | 不重写 |

首版不在内核中使用 Rust。

## 3. Objective-C 层

Objective-C 层必须很薄。

它只负责：

- 静态定义 Metal 对象类。
- 实现精确 selector ABI。
- 复制 descriptor 值。
- 管理 retain、release 和 autorelease。
- 管理 completion block。
- 把请求交给窄 C ABI 或 IPC。
- 把 typed error 转成 NSError。

它不得：

- 解析 AIR。
- 创建 Vulkan 对象。
- 装载 Lavapipe。
- 使用通用 selector fallback。
- 把 raw Objective-C 对象跨进程传递。

## 4. Rust 层

Rust helper 是用户态执行核心。

它负责：

- 客户端身份和 namespace。
- 对象 ID 和 generation。
- 消息大小与整数溢出检查。
- metal2vulkan runtime 调用。
- Vulkan loader 和 ICD 选择。
- IOSurface 元数据检查。
- 命令 sequence 和 timeline。
- 超时、取消和配额。
- helper 崩溃后的失效规则。

Rust 不重建 Objective-C 对象模型。

## 5. C++ 层

C++ 只负责系统驱动边界。

它负责：

- IOService match 和发布。
- type-5 或目标 ABI 需要的 IOUserClient。
- 共享内存和 notification queue。
- display mode。
- swap completion。
- vblank、cursor、gamma 和 ICC。
- framebuffer 接入。
- 必要时的 IOSurface kernel bridge。

C++ 层不得包含 AIR 编译器。

## 6. C ABI 边界

Objective-C 和 Rust 之间只传：

- 固定宽度整数。
- 带长度的字节片段。
- 明确布局的 plain structs。
- 不透明对象 ID。
- 错误码。

不得传：

- Rust 引用。
- C++ 对象。
- Objective-C `id`。
- Vulkan handle。
- 进程外 raw pointer。

所有结构都要带版本和长度。

## 7. 计划目录

```text
KVM MacOS/
  README.md
  PROJECT_SPEC.md
  CLOUD_DEPLOYMENT_SPEC.md
  docs/
  analysis/
  deprecated/
  vendor/
    metal2vulkan/
  objc/
    MetalProxy/
      Classes/
      Descriptors/
      Callbacks/
      Errors/
  crates/
    bridge-protocol/
    proxy-core/
    render-helper/
    m2vk-adapter/
    iosurface-adapter/
    display-sink-network/
  cpp/
    IOGPUProvider/
    DisplayProvider/
    FramebufferSink/
  include/
    bridge_abi.h
  tests/
    fixtures/
    gate1-lavapipe/
    gate2-iosurface-clear/
    gate3-metallib-triangle/
    gate4-helper/
    gate5-metal-enumeration/
    gate6-windowserver/
    gate7-recovery/
  packaging/
    launchd/
    metal-bundle/
    kext/
    manifests/
```

这些目录只在对应 Gate 开始时创建。

不得先生成空骨架冒充进度。

## 8. 依赖方向

```text
Objective-C proxy
    -> bridge ABI
    -> bridge-protocol
    -> render-helper
    -> m2vk-adapter
    -> vendored metal2vulkan
    -> Vulkan loader
    -> Lavapipe
```

`metal2vulkan` 不得反向依赖项目的 Objective-C 类。

系统驱动不得依赖 helper 内部 Rust 类型。

## 9. 版本边界

每个可发布包必须记录：

- macOS build。
- Metal 和 IOAccelerator UUID。
- metal2vulkan commit。
- 本地补丁哈希。
- Rust toolchain。
- Vulkan loader 版本。
- Mesa 和 LLVM 版本。
- 每个二进制 SHA-256。
- capability manifest。
