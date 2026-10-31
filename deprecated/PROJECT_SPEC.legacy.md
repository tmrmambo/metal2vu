> [!CAUTION]
> 本文档已于 2026-10-29 弃用。
> Phase、测试、Gallium 和部署结论均不得用于当前项目。
> 当前规格见 `..\PROJECT_SPEC.md`。


# MyVirtualMTLDriver 技术规格与研发规划文档

**当前状态**：核心胶水层与仿真测试验证完成（Phase 0 ~ Phase 3 完成，进入交叉构建与真机部署准备）  
**目标平台**：macOS x86_64（运行于通用 KVM 虚拟机）  
**工程定位**：运行于 Guest 内部的纯软件 Metal 驱动胶水层，后端对接 Mesa Gallium llvmpipe  

---

## 一、 项目目标与设计边界

### 1. 目标
在不修改 KVM 宿主机配置、不依赖硬件 GPU 直通、不依赖嵌套虚拟化的前提下，在 macOS 虚拟机内部实现一个兼容系统规范的 Metal 用户态驱动。使 WindowServer 能够正常完成图形上下文初始化与图层合成，解决通用虚拟机环境下图形界面严重卡顿、花屏或登录死循环问题。

### 2. 设计边界
* **仅限 Guest 内部**：所有组件均部署于虚拟机虚拟磁盘中，宿主机视其为普通 UEFI KVM 虚拟机。
* **避免内存安全隐患**：胶水层核心逻辑使用 Rust 编写，通过 C 接口与 Objective-C Runtime 及 Mesa C 库进行交互。
* **分阶段交付**：优先保障 WindowServer 2D 图层合成与基础桌面可用，后续再评估完整 3D 渲染支持度。

---

## 二、 当前已梳理成果与技术架构

### 1. 驱动发现与加载链路
* **注册点**：通过设备树节点或虚拟加速器属性读取 `MetalPluginName` 与 `MetalPluginClassName`。
* **加载时机**：`Metal.framework` 初始化或调用 `MTLCreateSystemDefaultDevice()` 时，触发 `CFBundle` 动态加载对应 Mach-O Bundle。
* **入口方式**：基于 Objective-C Runtime 动态查找指定类并实例化。

### 2. 类层次与方法分级
系统采用继承体系，大部分非核心逻辑由基类实现，驱动层需关注重写的方法分为两级：

```
NSObject
 └── _MTLDevice
      └── MTLIOAccelDevice
           └── VirtualMTLDevice (自研 Rust 胶水层)
```

* **第一级：最小核心集（约 25~30 个方法，已在 Rust 中实现）**
  * 目标：满足 WindowServer 正常启动与退出。
  * 核心包含：`name`、`supportsFamily:`、`newCommandQueue`、`newBufferWithLength:options:`、`newTextureWithDescriptor:iosurface:plane:`、`newRenderPipelineStateWithDescriptor:error:`、`drawPrimitives:...`、`commit`。
* **第二级：完整原语集（约 60~80 个核心方法，已建立类型与虚表骨架）**
  * 目标：满足常用 AppKit 应用与基础 3D 渲染。
  * 扩展包含：深度模板状态配置、更多纹理格式转换、Compute 计算管线调度、Blit 内存拷贝。
* **第三级：MTLDeviceSPI 私有协议与动态方法解析兜底（共 100+ 显式桩函数 + 动态兜底）**
  * 目标：彻底杜绝 WindowServer / SkyLight 在私有调用链路上的崩溃。
  * 发现事实：通过 IDA 对比 Intel (`MTLIGAccelDevice`) 与 AMD (`GFX10_MtlDevice`)，二者均严格遵循私有协议 `_OBJC_PROTOCOL_$_MTLDeviceSPI`（包含 427 个必选方法与 80 个可选方法）。
  * 核心私有属性覆盖：`sharedMemorySize`（预设 2GB）、`dedicatedMemorySize`（0，表征统一内存）、`maxBufferLength`（1GB）、`featureProfile`（10002）、`indirectArgumentBufferCapabilities`（7）、`minLinearTextureAlignmentForPixelFormat:`（64 字节）等。
  * 运行时安全网：在 `VirtualMTLDevice` 元类注册 `+resolveInstanceMethod:`，当遭遇未显式注册的私有 Selector 时，动态生成返回 0 / NULL 的默认安全函数，规避 `unrecognized selector sent to instance` 导致的异常终止。

### 3. 内存与光栅化后端
* **内存桥接**：实现 Gallium `sw_winsys` 接口，在处理 `newTextureWithDescriptor:iosurface:plane:` 时提取 `IOSurface` 的基地址指针，将其直接映射为 llvmpipe 瓦片渲染的写出目标。
* **Mesa llvmpipe 打包**：采用 Meson 构建精简的静态库，仅保留 Gallium 核心、llvmpipe 与 NIR 组件，剥离 X11、Wayland 与 OpenGL 前端，通过静态链接打包进最终驱动。

### 4. 着色器转换路径
* **输入形式**：系统组件与应用内置的 `.metallib` 二进制文件（内含 AIR 字节码）。
* **转换链路**：AIR 字节码 -> 提取 LLVM IR -> 转换至 SPIR-V -> Mesa `spirv_to_nir()` -> llvmpipe JIT 编译为 x86_64 机器码。
* **执行策略**：在管线构建期单次编译并缓存，渲染期直接执行 JIT 汇编。

---

## 三、 工程落地与代码实现清单

项目代码已在 `MyVirtualMTLDriver` 模块下完成工程化落地：

| 模块子系统 | 对应源码路径 | 核心能力与实现状态 |
| :--- | :--- | :--- |
| **运行时与 FFI** | `src/ffi/types.rs`<br>`src/ffi/vtable.rs`<br>`src/ffi/objc_runtime.rs` | 完整定义 Metal 数据类型、像素格式、C-ABI 虚表；实现 Objective-C 类动态注册（`objc_allocateClassPair` / `class_addMethod`）；包含 100+ `MTLDeviceSPI` 私有属性与能力查询桩；实现 `+resolveInstanceMethod:` 动态方法解析兜底安全网。 |
| **内存与后备后端** | `src/backend/gallium.rs`<br>`src/backend/sw_winsys.rs`<br>`src/backend/iosurface.rs` | Mesa Gallium3D C ABI 结构布局；64 字节对齐软件 winsys 适配器；Apple `IOSurface` 零拷贝锁定与基地址导出（`create_display_target`）。 |
| **驱动状态机与编码器** | `src/driver/buffer.rs`<br>`src/driver/texture.rs`<br>`src/driver/device.rs`<br>`src/driver/queue.rs`<br>`src/driver/encoder.rs` | 设备实例管理（`VirtualMTLDevice`）；多级命令队列与命令缓冲区；`VirtualMTLRenderCommandEncoder` 录制与向 Gallium PipeContext 的回放派发。 |
| **着色器与容器解包** | `src/compiler/metallib.rs`<br>`src/compiler/air.rs` | `.metallib` 二进制容器解析（支持 FourCC 区块与 Apple Offset Table）；AIR 字节码参数反射与 Gallium `create_vs_state` / `create_fs_state` 桥接。 |
| **Bundle 打包与部署** | `bundle/Info.plist`<br>`scripts/package_bundle.py`<br>`scripts/build_darwin.sh` | macOS Bundle 规范布局定义、Plist 配置、交叉编译与代码签名自动化脚本。 |
| **端到端集成测试** | `tests/integration_tests.rs` | 覆盖 设备初始化 -> 队列分配 -> IOSurface 纹理绑定 -> Metallib 编译 -> 命令录制 -> 回放提交 的全流程闭环验证（35 项测试通过）。 |

---

## 四、 存疑点、技术风险与待测试项

由于缺乏 macOS 内核与私有框架源码，当前方案存在以下需通过实机测试验证的技术盲区：

| 模块 | 潜在风险 / 存疑点 | 当前评估 | 验证方案 |
| :--- | :--- | :--- | :--- |
| **驱动加载** | macOS 14/15/26 的 AMFI 与系统加固运行时对未签名第三方 `MetalPluginName` 的加载拦截策略 | **待测试** | 制作最小空壳 Bundle，在启用与关闭 SIP 环境下分别测试加载日志。 |
| **IOSurface 同步** | llvmpipe 纯 CPU 写入 `IOSurface` 内存后，宿主显示服务或 CoreAnimation 的 Flush 信号触发机制 | **存疑** | 验证写入像素后调用 `IOSurfaceUnlock` 是否能即时反映在屏幕，是否需要注入额外通知。 |
| **私有 SPI 差异** | 不同次版本 macOS 中 `_MTLDevice` 内部是否存在未公开且未被基类捕获的硬编码调用 | **存疑** | 使用 IDA 逆向对比 15.x 与 26.x 中 `Metal.framework` 的调用链分支。 |
| **AIR 兼容性** | 高版本 Metal Shading Language 专有 Intrinsic 指令在转至 SPIR-V/NIR 时的算子缺失率 | **待测试** | 提取 WindowServer 实际使用的 `.metallib` 进行离线翻译测试。 |

---

## 五、 分阶段研发路线图

```
+-------------------------------------------------------------------------+
| Phase 0: 基础设施与骨架搭建 (验证动态加载与符号导出)                       |
+-------------------------------------------------------------------------+
                                     │
                                     ▼
+-------------------------------------------------------------------------+
| Phase 1: 最小可运行原型 POC (实现 ~30 个核心虚函数，尝试拉起 WindowServer) |
+-------------------------------------------------------------------------+
                                     │
                                     ▼
+-------------------------------------------------------------------------+
| Phase 2: 内存管道与软渲联调 (Mesa llvmpipe 静态链接与 IOSurface 绘制测试) |
+-------------------------------------------------------------------------+
                                     │
                                     ▼
+-------------------------------------------------------------------------+
| Phase 3: 着色器流水线对接 (接入 AIR->NIR 转换，跑通基础 UI Shader)         |
+-------------------------------------------------------------------------+
                                     │
                                     ▼
+-------------------------------------------------------------------------+
| Phase 4: 稳定性加固与多版本适配 (处理异常崩溃，补齐扩展方法)               |
+-------------------------------------------------------------------------+
```

### Phase 0: 基础设施与骨架搭建
1. 建立 Rust 驱动工程目录结构（`cargo` 项目）。
2. 构建符合 macOS Bundle 规范的打包脚本与 `Info.plist`。
3. 导出符合 Objective-C Runtime 规范的类注册函数。
4. 交付件：一个能够被 `Metal.framework` 探测并成功执行 `alloc/init` 的空壳 Bundle。

### Phase 1: 最小核心集实现 (POC)
1. 实现基础设备信息与特性查询接口（返回预设兼容值）。
2. 实现基础命令队列与命令缓冲区外壳。
3. 捕获 WindowServer 启动期间调用的所有 Selector，记录未捕获调用并做安全桩返回。
4. 交付件：能够避免 WindowServer 发生 `SIGABRT` 或 `unrecognized selector` 崩溃。

### Phase 2: 渲染管道联调
1. 静态集成编译精简版 `libmesa_llvmpipe`。
2. 实现 `sw_winsys` 与 `IOSurface` 的内存锁与基地址传递。
3. 验证 CPU 填充纯色与简单四边形能否直接呈现在虚拟机屏幕上。
4. 交付件：可在虚拟屏幕上输出经由 llvmpipe 软光栅光栅化的固定测试图像。

### Phase 3: 着色器转换接入
1. 集成 AIR 解析模块，提取 `.metallib` 中的字节码段。
2. 接入 SPIR-V/NIR 转换管线，打通至 llvmpipe JIT 编译器。
3. 针对 WindowServer 的混合与着色 Shader 进行测试与算子补全。
4. 交付件：桌面窗口、文字与基础图标能够以正确颜色和几何形态渲染。

### Phase 4: 综合适配与性能调优
1. 优化 llvmpipe 的多线程配置与剪裁矩形过滤。
2. 收集各家云厂商 KVM 实例下的运行日志。
3. 形成固化镜像制作脚本。

---

## 六、 后续任务分工与 Subagent 协同原则

针对后续长线开发，采用多 Agent 并行机制：
1. **主会话职责**：保持高层架构方向决策、审核子 Agent 交付件、记录总路线图变更、避免上下文膨胀。
2. **Subagent 任务隔离**：
   * **Subagent - 逆向组**：专门负责在 IDA 中针对特定 Selector 或版本变动进行针对性反编译，产出精确类型定义。
   * **Subagent - 编译器组**：专门负责验证并测试 AIR 字节码解析与 NIR 转换工具链。
   * **Subagent - 渲染与工程组**：专门负责 Rust 代码编写与构建脚本调试。
