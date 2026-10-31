# Metal 能力档位

文档版本：1.0  
状态：**已作废**，由 `docs/spec/60-CAPABILITY-MATRIX.md` 取代  
基线：macOS 26.7.2 build 25G325 x86_64

> [!CAUTION]
> **本文第 2 节的 `MVP-1` 档已作废，不得作为实现范围。**
> 它内部矛盾：目标写「第一个稳定桌面和基础 AppKit」，但 render 范围要求 blend、depth/stencil、compute、indirect 全部报告 false。WindowServer 合成不可能不用 blend 与 compute。
>
> `docs/spec/60-CAPABILITY-MATRIX.md` 用实测量化了 WindowServer 首帧的最小集（19 项），并给出全量能力矩阵。那份的几条关键更正：
> - blend 与 compute 是**必需**的
> - framebuffer fetch 在**登录路径**就被用到，attachment 格式是私有 `RGB10A8_2P_XR10`
> - scanout 是 `RGBA16Float`，不是 `BGRA8Unorm`
> - 跨进程管线缓存不是优化，是必需（最大着色器 210k words）
>
> 本文第 4 节关于 `MTLDeviceSPI` 427 required + 80 optional 的数字**已被三个独立样本确证为真**，可继续引用。

## 1. 三种“完成”

| 档位 | 目标 | 是否等于完整 Metal |
|---|---|---|
| `MVP-1` | 第一个稳定桌面和基础 AppKit | 否 |
| `FULL-1` | 常用 Metal、桌面、恢复和多显示 | 否 |
| `API-COMPLETE` | 对目标系统声明完整兼容 | 是 |

`FULL-1` 是项目完整能力。

它不自动等于 Apple 全部 Metal 能力。

## 2. 最小能力 `MVP-1`

### 2.1 Metal 对象

必须实现：

- Device。
- CommandQueue。
- CommandBuffer。
- RenderCommandEncoder。
- Buffer。
- Texture。
- Library。
- Function。
- RenderPipelineState。
- Drawable 或等价 scanout 对象。

只有复制路径需要时，才加入最小 BlitCommandEncoder。

### 2.2 Render 范围

| 能力 | `MVP-1` |
|---|---|
| 设备 | 一个 CPU device |
| 队列 | 单逻辑队列 |
| attachment | 只用 color 0 |
| 像素格式 | `BGRA8Unorm` |
| texture | 2D、单 plane、单 mip、单 slice |
| sample count | 1 |
| load action | Clear、Load、DontCare |
| store action | Store |
| shader | vertex、fragment |
| draw | 非索引 triangle |
| vertex buffer | slot 0 |
| viewport/scissor | 基础支持 |
| blend | 不支持，必须报告 false |
| depth/stencil | 不支持，必须报告 false |
| compute | 不支持，必须报告 false |
| indirect | 不支持，必须报告 false |

### 2.3 编译链

必须：

- 读取真实 metallib。
- 按名称取得 vertex 和 fragment function。
- 直接调用固定提交的 metal2vulkan。
- 保存输入 metallib 和每个 stage SPIR-V 哈希。
- 保存 PipelineArtifact、BindingPlan 和 requirements 指纹。
- 完整消费上游 layout、interface 和固定功能状态。
- 不自行重算 binding。
- 通过上游 verifier。
- 对不支持的 AIR 明确返回编译错误。

不得使用 synthetic AIR 作为验收输入。

### 2.4 内存和 IOSurface

必须：

- 创建真实单 plane IOSurface。
- 校验 width、height、stride、plane 和 alloc size。
- 区分 in-place、shadow 和 copy。
- 在完成回调前保证像素可见。
- 保持 row padding 不被越界写入。
- 禁止跨进程传 raw pointer 或 Vulkan handle。

### 2.5 命令、同步和错误

必须：

- CommandBuffer 状态单向变化。
- `Completed` 与 `Error` 互斥。
- completion block 只调用一次。
- helper 内使用单调 timeline。
- IPC 使用单调 sequence。
- 超时返回确定错误。
- helper 崩溃使在途命令进入 `DeviceLost`。
- helper 重启后拒绝旧 generation 对象。

### 2.6 系统能力

必须：

1. Metal.framework 枚举设备。
2. 普通 Metal app 通过 proxy 画出三角形。
3. WindowServer 枚举一个 display 和一个 mode。
4. scanout IOSurface 输出首帧。
5. 至少一个 display sink 可见。
6. helper 崩溃不终止客户端或 WindowServer。

### 2.7 `MVP-1` 完成定义

只有 Gate 1 到 Gate 7 全部通过，才算完成。

## 3. 完整项目能力 `FULL-1`

`FULL-1` 在 `MVP-1` 上增加以下内容。

### 3.1 Render

- 多 color attachment。
- blend state 和 color write mask。
- depth 和 stencil。
- indexed draw。
- instanced draw。
- indirect draw。
- 多 vertex buffer。
- triangle strip 和常用 primitive。
- viewport array 和 scissor array。
- pipeline cache。

### 3.2 Texture 和 sampler

- 1D、2D、3D、array 和 cube。
- 多 mip 和多 slice。
- texture view。
- 常用 unorm、snorm、uint、sint 和 float 格式。
- sampler filter、address mode、LOD 和 compare。
- mipmap 生成。
- MSAA 和 resolve。
- IOSurface 多 plane 格式。

每种格式都要有转换表和像素测试。

### 3.3 Compute

- ComputePipelineState。
- threadgroup grid。
- threadgroup memory。
- buffer、texture 和 sampler binding。
- barrier。
- indirect dispatch。

### 3.4 Blit

- buffer 到 buffer。
- buffer 到 texture。
- texture 到 buffer。
- texture 到 texture。
- fill。
- mipmap。
- resource synchronize。

### 3.5 内存和资源

- shared、managed 和 private 语义映射。
- heap。
- alias 和 hazard tracking。
- resource purgeability。
- residency 和预算。
- 大资源与内存不足错误。

不支持的 Apple 语义必须明确降级或拒绝。

### 3.6 同步

- 多队列。
- Fence。
- Event。
- SharedEvent。
- wait 和 signal。
- 跨队列顺序。
- CPU wait 和 callback。
- display present fence。

真正的跨进程 SharedEvent 需要独立实现。

### 3.7 高级绑定

- function constants。
- argument buffer。
- indirect command buffer。
- binary archive 或等价 cache。
- dynamic library 和 function pointer，仅在上游支持后加入。

### 3.8 显示和运维

- 多 mode。
- 多 display。
- mode change。
- cursor。
- gamma 和 ICC。
- vblank 和 swap deadline。
- sleep、wake 和 reconnect。
- framebuffer 与网络 sink 切换。
- helper 自动重启。
- 日志、指标和故障快照。

### 3.9 应用验收

必须至少覆盖：

- WindowServer。
- CoreAnimation。
- AppKit 基础窗口。
- 浏览器基础合成。
- 视频 UI，不含硬件解码承诺。
- 一个 render 样本。
- 一个 compute 样本。
- helper kill 和恢复。

## 4. API 完整 `API-COMPLETE`

要声明目标 macOS 26 Metal 完整兼容，还必须：

- 覆盖 `MTLDeviceSPI` 的 427 个必需方法。
- 对 80 个可选方法逐项决定。
- 验证所有继承方法。
- 为每个 selector 保存精确 x86_64 encoding。
- 为每个方法定义 ownership、线程和错误。
- 为每个 capability 保存目标 guest 证据。
- 验证 Apple 版本变化。
- 禁止用统一默认 IMP 伪造支持。

353 个公共 IMP 只是交叉样本。

它们不是完整能力证明。

## 5. 能力报告规则

- 未实现能力返回 false 或确定错误。
- `INFERRED` 能力不得向客户端报告为可用。
- 只有 `TESTED` 能力可以进入发布 profile。
- 每次发布要保存 capability manifest。
- capability manifest 必须绑定系统 build 和组件哈希。
