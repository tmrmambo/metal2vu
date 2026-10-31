# metal2vulkan 复用缺口与最小系统显示设备架构审计

> [!IMPORTANT]
> 2026-10-29 约束修正：部署环境可能是公有云 KVM 或 Hyper-V 客体。
> 无法修改宿主、QEMU、VMM、PCI 设备模型或宿主 Vulkan。
> 所有必需运行组件必须位于 macOS guest。
> 文中的 host helper 路线只作参考，不是交付架构。

审计日期：2026-10-29  
审计方式：浅克隆、源码/构建文件静态审计、现有二进制字符串与 Mach-O 头只读检查；未构建、未运行测试、未改动现有驱动源码。

## 0. 结论标签

- **[evidence]**：由本次读取到的代码、构建文件、二进制头/字符串或权威文档直接支持。
- **[inference]**：由多个 evidence 推导出的工程判断，尚未在目标 macOS 实机验证。
- **[unknown]**：现有材料不足，必须做目标系统探针、获得私有 ABI 信息或补充输入后才能回答。

## 1. 审计快照与范围

- **[evidence]** 上游远端为 https://github.com/steelbrain/metal2vulkan，按要求浅克隆到 `C:\Users\viola\.kiro\crew\scratch\runtime-0c169757\metal2vulkan-upstream`；分支 `master`；commit `0dfdbcd59d235e37ba13b87a5ab30835b5bb9e35`；`git rev-parse --is-shallow-repository` 为 `true`；工作树干净。
- **[evidence]** 上游 commit 主题为 `Give a refused copied buffer's placed range back to the address space`，提交时间 `2026-10-29T00:53:00+02:00`。
- **[evidence]** 本地手写项目 `C:\Users\viola\Documents\KVM MacOS\deprecated\MyVirtualMTLDriver` 位于 `master`，commit `b1e6875c625ee171bc4fb4667e5d3e084ffbfa37`，工作树干净。
- **[evidence]** 三个参考组件实际是 Mach-O 文件而非目录；Mach-O 头均为 `MH_KEXT_BUNDLE`、CPU `arm64`、subtype `0xc0000002`：
  - `C:\Users\viola\Documents\KVM MacOS\metal_drivers\com.apple.driver.AppleParavirtGPUIOGPUFamily`
  - `C:\Users\viola\Documents\KVM MacOS\metal_drivers\com.apple.iokit.IOGPUFamily`
  - `C:\Users\viola\Documents\KVM MacOS\metal_drivers\com.apple.iokit.AppleParavirtIOSurface`
- **[inference]** 上述 arm64 kext 只能作为架构/私有接口证据，不能直接复用于本地构建脚本明确指定的 `x86_64-apple-darwin` 目标。
- **[evidence]** 本次没有运行完整构建、Cargo 测试、Mesa 构建、Vulkan 设备探针或 WindowServer 探针；因此任何“能在目标 macOS x86_64 上工作”的说法均不成立。

## 2. 执行结论

- **[inference]** 应把现成 metal2vulkan 作为 **AIR 前端 + AIR→SPIR-V 编译器 + Rust Metal 语义运行层** 的核心，停止扩展本地手写 AIR/Gallium/Metal 对象实现。
- **[inference]** 用户所说的 “text” 若为 “kext”，则“kext/DriverKit + Rust 核心 + Objective-C 胶水”按当前含义 **不够**。只有把 IOGPU 用户客户端、显示提供者、IOSurface 映射、完整用户态 Metal bundle、进程间协议、服务监督和签名权限都展开并实现，这三个粗粒度名词才可能覆盖完整系统。
- **[inference]** 最小安全架构是：客户端/WindowServer 内只保留薄 Objective-C 代理；metal2vulkan-runtime、Vulkan loader 和 Lavapipe 放到受监督辅助进程；IOSurface 走 Mach/XPC 可传递对象，控制面走带对象 ID 和 timeline 值的版本化 IPC。
- **[inference]** Lavapipe 首选形态是 **Vulkan loader 动态发现的独立 ICD dylib**。不建议直接调用 Mesa 私有共享库接口，也不建议把 `liblavapipe_st` 静态嵌入 Metal bundle。
- **[unknown]** 最大可行性风险不在 AIR→SPIR-V，而在目标 macOS 版本允许第三方注册 IOGPU/显示提供者及用户态 Metal bundle 的私有 ABI、签名和 entitlement。

## 3. metal2vulkan 实际可复用范围

### 3.1 AIR 到 SPIR-V 链路

- **[evidence]** `C:\Users\viola\.kiro\crew\scratch\runtime-0c169757\metal2vulkan-upstream\docs\ARCHITECTURE.md` 与对应源码给出的真实链路为：metallib/AIR bitcode → container/bitstream/bitcode 解析 → typed AIR IR/ABI → canonicalization/内联/函数常量 → MemoryPlan → lowering strategy → CFG structurize → typed SPIR-V builder → tidy → 内建 verifier → SPIR-V 1.5 serialize → pipeline link/relocate。
- **[evidence]** `metal2vulkan-air` 独立实现 metallib 容器、LLVM bitcode reader、AIR metadata ABI、intrinsics 和 canonicalization；核心库不依赖外部 LLVM 工具读取 bitcode。
- **[evidence]** `metal2vulkan` CLI 对 `.ll` 输入才调用 LLVM 21+ 的 `llvm-as`；`spirv-val` 是 CLI/测试中的独立检查，不参与库的翻译决策。
- **[evidence]** 编译器每次编译有 deadline、取消令牌、工作量和字节预算；核心阶段在 `catch_unwind` 内，panic 被转成 typed internal error。来源：`C:\Users\viola\.kiro\crew\scratch\runtime-0c169757\metal2vulkan-upstream\docs\ARCHITECTURE.md` 与 `C:\Users\viola\.kiro\crew\scratch\runtime-0c169757\metal2vulkan-upstream\crates\metal2vulkan\src\pipeline\compile.rs`。
- **[inference]** 这条链路可直接替换本地 `compiler/metallib.rs` 和 `compiler/air.rs`，但必须从真实 metallib/AIR fixture 验证目标应用覆盖；“能生成有效 SPIR-V”不等于“与 Metal 语义兼容”。

### 3.2 Metal 对象覆盖

- **[evidence]** `metal2vulkan-runtime` 的 Rust API已有 Device、CommandQueue、CommandBuffer、Blit/Compute/Render encoders、Buffer、Texture、Heap、SamplerState、DepthStencilState、Fence、Event、SharedEvent、Library、Function、compute/render pipeline state、rasterization-rate map 和 indirect command buffer 等对象。来源：`C:\Users\viola\.kiro\crew\scratch\runtime-0c169757\metal2vulkan-upstream\crates\metal2vulkan-runtime\README.md`、`src/lib.rs` 和模块树。
- **[evidence]** 方法以 Metal selector 的 snake_case 形式存在，错误使用 typed `Error`；无法精确实现的调用会拒绝或记录 degradation，不宣称全部 Metal API 已完成。
- **[evidence]** `SharedEventHandle` 和 `SharedTextureHandle` 明确只在一个进程内共享；跨进程 export 未实现。来源：`C:\Users\viola\.kiro\crew\scratch\runtime-0c169757\metal2vulkan-upstream\crates\metal2vulkan-runtime\src\event.rs` 与 `src\texture\shared.rs`。
- **[evidence]** runtime 没有 Objective-C Metal 对象类。`objc2`/`objc2-metal` 仅是 macOS host A/B benchmark 的 dev-dependency；产品库是普通 Rust library。来源：`C:\Users\viola\.kiro\crew\scratch\runtime-0c169757\metal2vulkan-upstream\crates\metal2vulkan-runtime\Cargo.toml`。
- **[inference]** 对象语义层可复用，Objective-C ABI、retain/release、NSError、block callback、descriptor object、动态 selector 和私有 SPI 代理层仍需单独实现。

### 3.3 Vulkan 运行层

- **[evidence]** runtime 通过 `ash 0.38` 创建/采用 Vulkan instance、device、queue、command buffer、pipeline、资源、barrier 和 timeline semaphore；要求 Vulkan 1.2 和 `timelineSemaphore`。
- **[evidence]** `ash` 使用 `loaded` feature；`Device::system_default` 运行时通过 `ash::Entry::load_from` 打开 Vulkan loader，构建时不链接 Vulkan。macOS 默认尝试 `libvulkan.dylib`、`libvulkan.1.dylib`、`$VULKAN_SDK/lib`、`/opt/homebrew/lib` 和 `/usr/local/lib`。来源：`C:\Users\viola\.kiro\crew\scratch\runtime-0c169757\metal2vulkan-upstream\crates\metal2vulkan-runtime\src\device\create.rs`。
- **[evidence]** runtime 也可用 `unsafe Device::from_raw` 采用调用方创建的 Vulkan instance/device/queue，前提是调用方准确提供 enabled features/extensions，且 timeline semaphore 已开启。来源：`src\device\adopt.rs`。
- **[evidence]** runtime 的 Metal GPU 地址是进程内逻辑地址空间，不把 Vulkan device address 暴露为 Metal 地址。来源：`src\address.rs`。
- **[inference]** metal2vulkan-runtime 是 Vulkan 使用者，不是 Vulkan driver；项目仍须单独打包 Vulkan loader 和 Lavapipe ICD。

### 3.4 IOSurface 与平台边界

- **[evidence]** runtime README 明确把真实 IOSurface/Mach VM、guest-visible identifiers、CAMetalLayer presentation 和 OS services 列为 consumer 的职责。
- **[evidence]** runtime 提供 `HostMemory`、no-copy buffer 和 `Buffer::new_texture_with_iosurface_plane`；后者只接受调用方从 IOSurface 取出的 offset、bytesPerRow、planar/YCbCr facts，是“IOSurface stand-in”，不创建、传递或拥有 IOSurface。来源：`src\host_memory.rs` 与 `src\buffer_texture.rs`。
- **[evidence]** Mesa Lavapipe 当前源码宣告 `VK_EXT_external_memory_host` 和 `VK_KHR_timeline_semaphore`，host pointer 最小导入对齐为 4096；其 `lvp_GetMemoryHostPointerPropertiesEXT` 对 HOST_ALLOCATION 返回 memory type 0。来源：[Mesa lvp_device.c](https://gitlab.freedesktop.org/mesa/mesa/-/raw/main/src/gallium/frontends/lavapipe/lvp_device.c)。
- **[unknown]** 尚未在目标 macOS x86_64 上证明：该 Mesa 配置实际编译成功、loader 能发现 ICD、Lavapipe 能导入该进程映射的 IOSurface 页、渲染后 WindowServer 能看到一致内容。

### 3.5 依赖、许可证与测试

- **[evidence]** 上游 workspace 要求 Rust 1.98；固定 toolchain 为 1.98.1。主要产品依赖为 `ash 0.38`、`libc`、`sha2`，translator 可选 `serde/serde_json`。
- **[evidence]** metal2vulkan 三个产品 crate 是 `GPL-2.0-or-later OR LGPL-3.0-or-later` 双许可证。来源：根 `Cargo.toml`、`LICENSE` 与各产品 crate manifest。
- **[inference]** Cargo 默认把 Rust 依赖静态并入最终 cdylib。若闭源 Metal bundle 直接嵌入 metal2vulkan 并选择 LGPLv3，分发时需满足 LGPL Combined Work 的替换/重新链接条件；若选择 GPL，则组合工作的分发条件更强。应在架构冻结前做正式许可证审查，此处不是法律意见。
- **[evidence]** Mesa 文档说明核心和大多数代码为 MIT，但要求逐文件检查 SPDX；LLVM 为 Apache-2.0 with LLVM Exceptions。来源：[Mesa license](https://gitlab.freedesktop.org/mesa/mesa/-/raw/main/docs/license.rst) 与 [LLVM license](https://raw.githubusercontent.com/llvm/llvm-project/main/LICENSE.TXT)。
- **[evidence]** 上游验证包括 clippy、unit/integration、内建 verifier、spirv-val、解释器、golden hash、authored Metal/Vulkan comparisons 与可选 corpus audit。来源：`docs\VALIDATION.md` 和 `.github\workflows\ci.yml`。
- **[evidence]** CI 的 macOS runner 是 arm64 `macos-26`，只编译/测试无设备路径；Lavapipe device execution 仅在 Linux CPU ICD lane 运行。
- **[inference]** 上游测试设计值得复用，但不能把测试数量、coverage 表或宣传数字当作目标 macOS x86_64 兼容性证明。

## 4. 本地手写驱动现状

### 4.1 已确认的阻断项

- **[evidence]** `C:\Users\viola\Documents\KVM MacOS\deprecated\MyVirtualMTLDriver\Cargo.toml` 只依赖 libc、bitflags、parking_lot；没有 metal2vulkan、ash、Mesa 或 Vulkan loader 依赖。
- **[evidence]** `src\compiler\air.rs::compile_to_gallium_shader` 只检查 bitcode magic、做字符串式参数扫描，然后把 AIR bitcode 指针作为 `PIPE_SHADER_IR_LLVM` tokens 传给 Gallium；没有 AIR ABI lowering、NIR 生成或 SPIR-V 生成；context 不可用时返回 `MockGalliumShader`。
- **[inference]** Apple AIR 虽以 LLVM bitcode 为容器，其 intrinsics、metadata ABI 和语义并不是把字节指针交给 llvmpipe shader-state 就可执行；当前函数不是可用的 AIR 编译器。
- **[evidence]** `src\driver\encoder.rs::VirtualMTLRenderPipelineState` 只有 blend/rasterizer/depth-stencil handles，没有 vertex/fragment shader handles；replay 也没有绑定 VS/FS。
- **[evidence]** 本地 integration test 使用 synthetic `MOCK_*_AIR_BITCODE`、null Gallium context 和 mock IOSurface；mock draw 是 no-op，command buffer 仍无条件进入 Completed。
- **[inference]** 当前 integration test 只证明 Rust 状态机不崩溃，不证明 AIR 执行、像素输出、IOSurface 可见性或 Metal ABI。
- **[evidence]** `VirtualMTLTexture::new_iosurface` 保存 IOSurface 指针，却另行调用 `screen.resource_create` 创建 Gallium resource；没有把 IOSurface base address/display target 绑定到该 resource。
- **[evidence]** `present_drawable` 只对保存的 IOSurface 做 unlock/lock，没有像素复制、完成 fence 或 display flip。
- **[inference]** 当前清屏/绘制很可能落在独立 Gallium allocation，而不是目标 IOSurface；“零拷贝 WindowServer display”的注释没有代码闭环。
- **[evidence]** Objective-C glue 只注册 `VirtualMTLDevice` 一个类；返回的 queue/buffer/texture/pipeline 是 `Box<Arc<...>>` 强转为 `id`，没有为这些对象注册 Objective-C class。
- **[evidence]** `device_init_imp` 只返回 `this`，没有创建或写入 `_rustDeviceContext`；多数资源方法在 `get_device` 失败时返回 null。
- **[evidence]** descriptor 被忽略：普通 texture 固定为 64×64 BGRA，IOSurface texture 固定为 1920×1080 BGRA，render pipeline 使用 default descriptor；compute pipeline、sampler、depth-stencil、heap、shared event/texture 均返回 null。
- **[evidence]** `respondsToSelector:` 无条件返回 YES，未知 selector 被动态安装成统一 `@@:` 返回 null 的 IMP；不同真实签名会造成 ABI 错配风险。
- **[evidence]** `MTLDriverFactory` 返回 class pointer；`MTLCreateSystemDefaultDevice` 直接 alloc/init 该类。当前材料没有证明这两个符号或 plist key 是目标 Metal.framework 接受的 driver ABI。
- **[evidence]** `dist\MyVirtualMTLDriver.bundle` 只有 Info.plist，没有 `Contents\MacOS\MyVirtualMTLDriver`；现有 x86_64-apple-darwin target 只看到 rmeta，未看到 Darwin dylib。
- **[inference]** 本地源码适合作为接口清单/实验脚手架，不适合作为继续补丁式扩展的执行核心。

### 4.2 三个 Apple 组件揭示的系统分层

- **[evidence]** AppleParavirt GPU kext 包含 `AppleParavirtGPU`、`AppleParavirtDevice`、`AppleParavirtDeviceUserClient`、`AppleParavirtCommandQueue`、resource/task/page-table/memory-map 类，以及 FIFO/MMIO/interrupt、resource heap、shared texture 和 command descriptor 代码痕迹。
- **[evidence]** 同一 kext 还包含独立 `AppleParavirtDisplay` 和 `AppleParavirtDisplayFence`，以及 `program_hardware_swap_gated`、cursor、gamma、ICC profile、display attributes 和 `WindowServer` 字符串。
- **[evidence]** IOGPUFamily kext 含 `IOGPUDeviceUserClient::s_submit_command_buffers`、new/delete queue/resource、shared-event wait/signal、`IOGPUSurfaceMTL`、`IOGPUResource::newResourceWithIOSurface`、scheduler 和 command queue。
- **[evidence]** AppleParavirtIOSurface kext 含独立 mapper device/service/interface、createMapping、wire/unwire、host mapping ring、descriptor table 和 IOSurfaceRoot 连接。
- **[inference]** Apple 自己没有把“GPU 执行”“显示提供者”“IOSurface host mapping”压成一个 glue 层；这些是独立失败域和协议。

## 5. 问题 1：kext/DriverKit + Rust 核心 + Objective-C 胶水是否足够

- **[inference]** **按当前实现不够。** Rust 核心可由 metal2vulkan 提供主要执行语义，但 kext/DriverKit 和 Objective-C 两侧仍缺完整系统协议。
- **[inference]** 若把三个词展开成下列全部层，粗略物料表才可能“够”：
  1. 硬件/虚拟设备 match、BAR/MMIO/interrupt、power lifecycle；
  2. IOGPU accelerator、device user client、queue/resource/event/VM ABI；
  3. display provider、mode、swap/vblank/fence、cursor、gamma/ICC；
  4. IOSurface mapper/lifetime/coherency；
  5. 完整用户态 Metal Objective-C bundle；
  6. metal2vulkan-runtime + Vulkan loader + Lavapipe；
  7. 辅助进程 IPC、对象表、同步、崩溃恢复；
  8. 安装、签名、entitlement、版本匹配和诊断。
- **[evidence]** Apple 的公开 DriverKit 文档提供基础 IOService、memory、dispatch 和 IOUserClient 机制，并要求 DriverKit entitlement；该公开页面没有 IOGPU 或 graphics/display family。来源：[Apple DriverKit](https://developer.apple.com/documentation/driverkit.md)。
- **[inference]** DriverKit 不是 IOGPU kext 的已证明等价替代。最小计划应把 “DriverKit 可替代” 设为独立 feasibility gate，而不是前提。
- **[unknown]** 目标 macOS 26.x x86_64 是否允许非 Apple 签名的 DriverKit/kext 发布所需私有 IOGPU/显示 class、Metal bundle 是否会绑定它，以及所需 entitlement/boot policy。

## 6. 问题 2：注册为系统显示设备仍缺的独立层

| 独立层 | metal2vulkan | 本地现状 | 结论 |
|---|---|---|---|
| AIR→SPIR-V 与 pipeline planning | 已有 | 本地实现为 mock/直传 bitcode | **[inference] reuse upstream；discard local** |
| Vulkan Metal 语义 runtime | 已有 Rust API | 本地只做少量 Gallium replay | **[inference] reuse upstream** |
| Vulkan loader + Lavapipe ICD | 不随项目交付 | 未集成 | **[evidence] missing** |
| Objective-C Metal bundle 全对象 ABI | 没有 | 只有不完整 Device class | **[evidence] missing/major rewrite** |
| IOGPU accelerator/provider | 没有 | 没有 | **[evidence] missing** |
| IOGPU DeviceUserClient、queue/resource/event ABI | 没有 | 没有 | **[evidence] missing** |
| Display provider/port/modes/swap/vblank/cursor/gamma | 没有 | 没有 | **[evidence] missing** |
| IOSurface OS bridge与跨进程传递 | 只有 host-memory stand-in | 只有单进程 C wrapper | **[evidence] adapt + missing IPC** |
| helper 控制协议、对象 ID、callback | 没有 | 没有 | **[evidence] missing** |
| 服务监督、超时、重启、状态失效 | 没有 | 没有 | **[evidence] missing** |
| Metal/IOGPU 私有 ABI 版本适配 | 没有 | 硬编码 selector/常量 | **[unknown] target-specific** |
| 签名、entitlement、安装/boot policy | 没有 | ad-hoc codesign 脚本 | **[unknown] target-specific** |

- **[inference]** IOGPU accelerator 与 display provider 应保持独立：前者服务 Metal command/resource，后者服务 WindowServer 的显示枚举与 swap。
- **[inference]** IOSurface mapper是否必须进入 kext 取决于虚拟机数据面。如果 Lavapipe 只写 guest 内同一 IOSurface 的 CPU 页，用户态映射可完成前两条竖切；若 host/KVM 后端要直接消费 guest surface 页或 doorbell，则仍需内核/虚拟硬件映射层。
- **[unknown]** 当前输入没有 host 侧 KVM display protocol、虚拟 PCI/MMIO 设备定义或 framebuffer consumer，无法确定内核数据面的最小命令集。

## 7. 建议的最小系统架构

```text
Metal client / WindowServer process
  └─ Metal.framework
      └─ User-space Metal bundle (Objective-C proxy objects only)
          ├─ control: versioned Mach/XPC IPC, object IDs, command batches, callbacks
          ├─ data: IOSurface Mach/XPC objects + bounded shared-memory blobs
          └─ IOGPU connection: registry identity, resource/display fences as required

Supervised render helper process
  ├─ object table + per-client namespaces
  ├─ metal2vulkan-runtime
  │   ├─ metal2vulkan-air
  │   └─ metal2vulkan translator
  ├─ Vulkan loader dylib
  └─ Mesa Lavapipe ICD dylib + LLVM
       └─ renders into helper-mapped IOSurface memory

System/device side
  ├─ IOGPU accelerator/provider + DeviceUserClient
  ├─ display provider: modes, swap/vblank, cursor, gamma/ICC, display fences
  └─ IOSurface mapper / virtual-hardware transport when host sharing requires it
```

- **[inference]** 前两条竖切应先在普通测试进程内直接调用 runtime，以隔离 translator/IOSurface 问题；只有像素闭环通过后再引入 IPC。
- **[inference]** WindowServer 阶段应启用辅助进程，因为把 LLVM JIT、Mesa 和未信任 metallib 解析直接装进 WindowServer 会扩大崩溃与内存破坏影响。

## 8. 问题 3：Lavapipe 放入辅助进程的可行性

| 维度 | 判断 | 依据与必要设计 |
|---|---|---|
| 可行性 | **[inference] 可行，但不是透明搬迁** | Lavapipe 是 CPU Vulkan ICD；IOSurface 可跨 address space/process。Apple 文档称 IOSurface 跨 API、架构、地址空间和进程，并要求 CPU 访问时 lock/unlock：[Apple IOSurface guide](https://developer.apple.com/library/archive/documentation/Performance/Conceptual/OpenCL_MacProgGuide/SynchronizingIOSurfacesAcrossProcessors/SynchronizingIOSurfacesAcrossProcessors.html)。 |
| 地址空间 | **[evidence] raw pointer/Vk handle/Rust handle 均不可跨进程** | runtime 的 GPU address、Vk objects、SharedEventHandle、SharedTextureHandle 都是一个 Device/进程内对象。IPC 必须传 object ID、offset/length、descriptor 和 timeline value；禁止把客户端指针当 helper 指针。 |
| IOSurface | **[inference] 用 Mach/XPC 对象传递，在 helper 重新取得 IOSurfaceRef 和 base address** | 每个进程映射地址可不同；helper 用自己的 pointer 构造 `HostMemory`，读取 plane offset/stride 后调用 `new_texture_with_iosurface_plane`。需保持 send right、surface、HostMemory 和 command buffer 的生命周期。 |
| 同步 | **[evidence] IOSurface lock/unlock 不是 Vulkan queue fence** | lock/unlock解决 CPU/设备可见性；runtime 的 timeline semaphore留在 helper。协议需 `submit(sequence, waits[])`、`completion(sequence,status,seed)`；只有 helper wait 完成并完成必要 unlock/flush 后，代理才可通知 Metal completion 或提交 display swap。 |
| 共享 event | **[evidence] upstream 跨进程 shared event 未实现** | 不能直接使用 runtime 的 SharedEventHandle 跨 IPC。先以 helper 内 timeline + Mach/XPC completion 模拟；若要求真正 Mach-port MTLSharedEvent 语义，需要单独实现和逐项验证。 |
| 崩溃隔离 | **[inference] 显著优于 in-process** | Mesa/LLVM/translator 崩溃只终止 helper；代理设置 deadline，失败所有在途 command buffer，释放/失效该 helper generation 的对象，并可重启。 |
| 崩溃恢复 | **[inference] 有状态成本** | pipeline/library/resource IDs 属于旧 generation；重启后必须重建，不能继续使用旧 Vk objects。IOSurface 可重新导入，private resources 需由客户端重传或宣布 device removed。 |
| WindowServer 权限 | **[unknown] 高风险** | WindowServer/Metal bundle 能否启动或连接自定义 helper、传 IOSurface/Mach rights、读取 app-bundled Vulkan loader/ICD，取决于 sandbox、seat/bootstrap namespace、签名和 entitlement；本次材料没有答案。 |
| 安全边界 | **[inference] IPC 必须按不可信输入设计** | 校验消息版本、大小、对象 ownership、offset overflow、surface extent/stride、命令预算；按 audit token 隔离客户端；禁止 helper 解析任意文件路径。 |

- **[inference]** 对 WindowServer 路径，推荐一个受 launchd/system extension 管理的 helper，并为每个客户端建立独立 namespace；不推荐把所有客户端的裸对象 ID 放在全局表。
- **[inference]** 辅助进程首版不要追求 zero-copy shared events；先用 IOSurface 数据面和明确完成 ACK，证明正确性后再优化同步。

## 9. 问题 4：Lavapipe 的加载/链接形态

### 9.1 选项比较

| 形态 | 实际构建依据 | 优点 | 风险 | 结论 |
|---|---|---|---|---|
| Vulkan loader 动态加载 ICD | Mesa `src/gallium/frontends/lavapipe/meson.build` 先构建内部 `liblavapipe_st`；`src/gallium/targets/lavapipe/meson.build` 再构建共享 `vulkan_lvp` 并生成 `lvp_icd.json`。 | 标准 Vulkan 边界；可独立升级/替换；metal2vulkan-runtime 已按此模型使用 `ash/loaded`；避免依赖 Mesa 私有 C 符号。 | loader/manifest 搜索、签名/rpath、错误选择其他 ICD、环境变量在系统进程中被忽略。 | **[inference] 推荐，放在 helper 内** |
| 直接 dlopen `libvulkan_lvp.dylib`，绕过 loader | ICD 导出 `vk_icdGetInstanceProcAddr`，但其契约面向 Vulkan loader。 | 可固定一份库，减少全局 discovery。 | 要自行实现 loader/ICD negotiation、dispatch、WSI/extension 处理；metal2vulkan-runtime 的默认创建路径不接受“ICD 当 loader”；维护成本高。 | **[inference] 不推荐** |
| 把 Mesa `liblavapipe_st` 静态链接 | Mesa build 明确把它作为内部 `static_library`，再 `link_whole` 到 ICD target。 | 单文件部署；无 manifest 搜索。 | `liblavapipe_st` 不是稳定公共 API；需同时整合 Gallium、llvmpipe、NIR、WSI、LLVM、生成代码和全局状态；符号/升级/体积/内存/许可证审计成本最高。 | **[inference] discard，除非长期维护 Mesa fork** |
| 把 metal2vulkan/runtime 静态并入 ObjC bundle | Cargo 默认最直接。 | 调用简单、无 IPC。 | LGPL relinking 条件；LLVM/Mesa 崩溃进入客户端或 WindowServer；每进程重复 JIT/cache/内存；私有 ABI 与核心耦合。 | **[inference] 只用于短期普通进程原型，不用于 WindowServer** |

### 9.2 推荐部署细节

- **[evidence]** Khronos loader 通过 driver manifest 的 `library_path` 加载 ICD；`VK_DRIVER_FILES` 可覆盖 discovery，旧 `VK_ICD_FILENAMES` 已弃用。来源：[Khronos Loader Driver Interface](https://github.com/KhronosGroup/Vulkan-Loader/blob/main/docs/LoaderDriverInterface.md)。
- **[inference]** helper 应显式指定 app-bundled `libvulkan.1.dylib` 给 `DeviceOptions.loader`，并在第一次 loader 调用前只暴露 app-bundled `lvp_icd.json`；不要依赖 WindowServer 继承用户 shell 环境。
- **[unknown]** 系统/提升权限进程是否会忽略 `VK_DRIVER_FILES`，以及 loader 在目标 bundle 布局的确切搜索行为，需要目标机探针。若环境覆盖不可用，可评估 loader settings 或 `VK_LUNARG_direct_driver_loading`，但仍保持标准 Vulkan dispatch。
- **[inference]** 记录并校验 loader、ICD、Mesa、LLVM、metal2vulkan 的绝对路径、版本和 SHA-256，防止加载宿主机另一份 ICD。

## 10. 问题 5：上游模块与本地手写模块逐项对应

状态含义：`reuse` 直接采用上游；`adapt` 保留边界/概念但重写适配；`missing` 上游和本地都无可用实现；`discard` 不进入新执行路径。

| 本地模块 | metal2vulkan 对应 | 状态 | 理由 |
|---|---|---|---|
| `src\compiler\metallib.rs` | `metal2vulkan-air::{container,bitstream,bitcode,abi}`、`metal2vulkan::library` | **[inference] reuse upstream / discard local** | 上游是真实 container+bitcode+ABI；本地主要由 synthetic fixture 验证。 |
| `src\compiler\air.rs` | AIR canonicalization、`lower/`、`memory/`、`structurize/`、`spirv/`、`pipeline/` | **[inference] reuse upstream / discard local** | 本地没有 AIR lowering，只直传 bitcode或返回 mock。 |
| `src\backend\gallium.rs` | `metal2vulkan-runtime` + `ash` + Mesa Lavapipe ICD | **[inference] discard** | 手抄 Gallium ABI 易漂移，且新核心输出 Vulkan；Lavapipe 才是目标 Vulkan frontend。 |
| `src\backend\sw_winsys.rs` | `HostMemory`、no-copy Buffer、IOSurface-plane texture | **[inference] adapt concept / discard Gallium ABI** | 外部行布局概念有用；displaytarget callbacks 不再是新路径。 |
| `src\backend\iosurface.rs` | 上游无 OS owner；runtime 有 `IoSurfacePlane` stand-in | **[inference] adapt** | 保留 C framework wrapper 思路，补 plane API、alloc size、Mach/XPC 传递、lifetime、seed/error；不能直接称 zero-copy 已完成。 |
| `src\driver\device.rs` | runtime `Device`、`DeviceProperties`、resource creators | **[inference] reuse upstream / discard implementation** | 本地 capability 值硬编码，创建失败会退化为 1-byte buffer。 |
| `src\driver\queue.rs` | runtime `CommandQueue` 和 scheduler | **[inference] reuse upstream / discard local** | 上游已有提交、等待、错误和线程模型。 |
| `src\driver\encoder.rs` | runtime command buffer、render/compute/blit encoders | **[inference] reuse upstream / discard local** | 本地缺 shader binding、完整 hazards、typed failures；present 不是显示协议。 |
| `src\driver\buffer.rs` | runtime `Buffer`、HostMemory、rebind/adopt | **[inference] reuse upstream；ObjC shell adapt** | 数据对象用上游，代理层只持 object ID/handle。 |
| `src\driver\texture.rs` | runtime `Texture`、TextureDescriptor、buffer/IOSurface plane path | **[inference] reuse upstream；IOSurface adapter adapt** | 本地 IOSurface 与 Gallium resource 未绑定。 |
| `src\ffi\types.rs` | `metal2vulkan::metal`、runtime values，外加真实 ObjC ABI types | **[inference] adapt** | 避免两套枚举；仅保留经 SDK/目标二进制验证的 ABI structs。 |
| `src\ffi\objc_runtime.rs` | 上游无对应 | **[evidence] missing / major rewrite** | 需要完整 ObjC class family、ownership、blocks/errors、selector signatures 和 IPC proxy；当前仅 Device class。 |
| `src\ffi\vtable.rs` | 上游无对应 | **[inference] discard** | 未挂到真实 ObjC object，多数函数为 null；手工 vtable 不是 Objective-C protocol conformance。 |
| `src\lib.rs` factory exports | 上游无对应 | **[unknown] adapt after ABI capture** | factory symbol/return contract未证实；当前返回 class 而非已连接系统服务的 device。 |
| `bundle\Info.plist` 与 package scripts | 上游无对应 | **[unknown] rewrite after target capture** | 当前 generic BNDL/ad-hoc sign；没有系统注册、entitlement 或可执行产物证据。 |
| `tests\integration_tests.rs` | 上游 validation/runtime examples | **[inference] discard as acceptance proof** | 改为真实 metallib、真实 Lavapipe、真实 IOSurface 像素和系统探针测试。 |
| IOGPU accelerator/user client | 无 | **[evidence] missing** | 参考 kext 证明是独立层。 |
| display provider | 无 | **[evidence] missing** | 参考 kext 的 AppleParavirtDisplay/Fence 证明是独立层。 |
| cross-process protocol/supervisor | 无 | **[evidence] missing** | runtime handles 仅进程内。 |

## 11. 问题 6：最小竖切与验收证据

### Slice A：清屏到真实 IOSurface，不接 WindowServer

- **[inference]** 在目标 macOS x86_64 的普通、非特权测试程序中，动态加载固定版本 Vulkan loader + Lavapipe ICD；创建真实 BGRA IOSurface，并先填充非零 sentinel。
- **[inference]** 在同一进程先用 IOSurface base/alloc size 构造 runtime no-copy Buffer，再用真实 plane offset/bytesPerRow 创建 IOSurface-plane Texture；提交只含 clear 的 render pass。
- **[evidence]** clear 不依赖 AIR shader，因此该步隔离验证 loader/ICD、runtime resource、IOSurface layout、提交和可见性。
- **验收证据 [inference]**：
  - `vulkaninfo`/runtime identity 显示唯一 CPU device 为 Lavapipe/llvmpipe，记录 loader 与 ICD 绝对路径和 SHA-256；
  - command buffer 返回 Completed，无 typed error、无 Vulkan validation error；
  - wait 完成后 read-lock IOSurface，活动矩形每像素为预期 BGRA，row padding 仍为 sentinel；保存 raw bytes + SHA-256；
  - 记录 runtime WorkCounts/degradation，明确是 in-place、shadow 还是 copy；即使首版允许 copy，也不得把 copy 伪称 zero-copy；
  - 禁止 mock IOSurface、null context 和 synthetic completion。
- **[unknown]** 该步通过前，不应开始 kext/WindowServer 集成。

### Slice B：真实 metallib 三角形到同一 IOSurface

- **[inference]** 用目标 SDK 的 `metal/metallib` 生成最小 vertex+fragment metallib；通过 `Device::new_library_with_data`、真实 render pipeline、三顶点 draw 写入 Slice A 的 IOSurface。
- **验收证据 [inference]**：
  - 保存输入 metallib SHA-256、上游 commit、目标 Lavapipe profile/identity；
  - 保存生成 SPIR-V 每 stage 的 SHA-256，并通过内建 verifier；若 `spirv-val` 可用也记录结果，但不把它当语义证明；
  - Vulkan validation 无错误；runtime 无未解释的 refusal/degradation；
  - IOSurface readback：背景保持 clear 色，三角形内部多个固定采样点为预期颜色，边界外固定点不变；保存 PNG/raw/hash；
  - 与 CPU reference mask 比较，容差和颜色空间明确；不得只检查 command buffer status。
- **[inference]** 同进程通过后，把完全相同的 fixture 移到 helper，以 IOSurface Mach/XPC 对象 + IPC completion 重跑；像素 hash 必须一致，helper 强制崩溃测试必须只使该提交失败而不终止客户端。

### Slice C：接入 Metal.framework 与 WindowServer

- **[inference]** 先做普通 Metal client 枚举 gate，再做 WindowServer gate，避免把 bundle discovery 与 display provider 问题混在一起。
- **验收证据 [inference]**：
  1. Metal.framework 而非直接调用自定义 factory，能枚举该 device；device registryID 与 IOKit service 一致；最小 app 通过 Objective-C API 重跑 Slice B；
  2. `ioreg`/IORegistry 显示 accelerator、DeviceUserClient、display provider/port，WindowServer 实际打开对应 service；
  3. display mode 出现在 CoreGraphics display 列表；WindowServer 分配/交换真实 IOSurface；display provider 的 swap fence/sequence 单调完成；
  4. 屏幕或虚拟输出出现测试图；保存屏幕捕获、IOSurface hash、IORegistry snapshot 和限定时间段 unified log，三者关联同一 frame sequence；
  5. helper kill 后 WindowServer 不崩溃，设备进入明确失效/黑帧状态并可受控恢复；超时不得永久卡住 WindowServer；
  6. cursor、mode set、sleep/wake、gamma/ICC 暂不作为首帧 gate，但必须拒绝或返回一致状态，不能用“未知 selector 返回 0”掩盖。
- **[unknown]** 若第 1 或第 2 gate 因私有 ABI/签名政策失败，则“系统显示设备”路线在该 OS 上不可行；清屏和三角形成功也不能改变这个结论。

## 12. 未解项与下一步判定门

1. **[unknown]** 目标 macOS 26.x x86_64 的 Metal driver bundle discovery、factory ABI、Info.plist schema、Objective-C superclass/protocol 和私有 selector 精确签名。
2. **[unknown]** 第三方 kext/DriverKit 对 IOGPU/display provider 的可发布性、签名、entitlement、SIP/Reduced Security 与安装策略；公开 DriverKit 没有证明 graphics family。
3. **[unknown]** Lavapipe + Vulkan loader 在目标 macOS x86_64 的可构建/可签名/可发现性，以及 `VK_EXT_external_memory_host` 对真实 IOSurface mapping 的行为。
4. **[unknown]** WindowServer 到 helper 的 bootstrap/Mach/XPC 权限和 IOSurface right 传递规则。
5. **[unknown]** KVM host 侧虚拟 GPU/display transport；没有设备寄存器、FIFO、doorbell、framebuffer consumer 或 host protocol 输入。
6. **[unknown]** 用户真实 metallib/AIR corpus 对上游当前 commit 的覆盖、refusal 和精度差异；上游 Linux Lavapipe lane不能代替本地 corpus。
7. **[unknown]** 分发模式对应的 metal2vulkan LGPL/GPL、Mesa逐文件许可证、LLVM 和 Apple SDK/private interface 合规方案。

- **[inference]** Go/No-Go 顺序应为：A 真实 IOSurface clear → B 真实 metallib triangle → B2 helper 隔离 → C1 Metal.framework 枚举 → C2 IOGPU/display provider → C3 WindowServer 首帧。任一 gate 失败时先关闭该缺口，不继续堆叠后续层。

## 13. 主要外部源码依据

- [Mesa Lavapipe frontend Meson build](https://gitlab.freedesktop.org/mesa/mesa/-/raw/main/src/gallium/frontends/lavapipe/meson.build)
- [Mesa Lavapipe ICD target Meson build](https://gitlab.freedesktop.org/mesa/mesa/-/raw/main/src/gallium/targets/lavapipe/meson.build)
- [Mesa Lavapipe device implementation](https://gitlab.freedesktop.org/mesa/mesa/-/raw/main/src/gallium/frontends/lavapipe/lvp_device.c)
- [Khronos Vulkan Loader driver interface](https://github.com/KhronosGroup/Vulkan-Loader/blob/main/docs/LoaderDriverInterface.md)
- [Apple DriverKit](https://developer.apple.com/documentation/driverkit.md)
- [Apple IOSurface cross-process/synchronization guide](https://developer.apple.com/library/archive/documentation/Performance/Conceptual/OpenCL_MacProgGuide/SynchronizingIOSurfacesAcrossProcessors/SynchronizingIOSurfacesAcrossProcessors.html)
- [Mesa license overview](https://gitlab.freedesktop.org/mesa/mesa/-/raw/main/docs/license.rst)
- [LLVM license](https://raw.githubusercontent.com/llvm/llvm-project/main/LICENSE.TXT)
