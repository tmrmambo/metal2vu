# 实施路线与验收门

文档版本：1.0  
状态：**Gate 定义有效，前置条件与阻断项已过时**

> [!IMPORTANT]
> Gate 1–7 的划分与验收证据要求仍然有效。但下列前置条件已不成立：
>
> - **第 6 节 Gate 5 的前置「B-009 关闭」应删除。** 研发期 SIP 与 AMFI 全部关闭（`docs/spec/00-OVERVIEW.md` 第 2.4 节），第三方 bundle 的 trust gate 问题不发生。
> - **第 7 节 Gate 6 的前置「B-008 关闭」已实质满足。** B-008 原记为「`IOMobileFramebufferLegacy` 用户 ABI 未取得」，那是 **ARM 路径**的家族；x86 走 `IOFramebuffer` / IOGraphicsFamily，其 22 条 user client selector、`StdFBShmem_t` 布局与 accelerator↔display 关联机制均已取得。见 `docs/spec/11-KERNEL-DISPLAY.md`。
> - **第 9 节的阻断项表已过时。** 现行状态见各 `docs/spec/` 分册的证据标签。
>
> 另有一项本表未列、但优先级高于全部 Gate 的前置风险：**目标云平台能否启动 macOS**（系统盘是 NVMe 还是 virtio-blk）。见 `docs/spec/00-OVERVIEW.md` 第 2.5 节。

## 1. 当前点

当前位于 Gate 0 之后，Gate 1 之前。

| 内容 | 状态 |
|---|---|
| B-001 到 B-005 | `CLOSED-KNOWN` |
| Gate 0 | `PASS-STATIC` |
| 运行代码 | 尚未开始新架构 |
| 目标 guest 测试 | 尚未开始 |

## 2. Gate 1：guest Lavapipe

工作：

1. 固定 Vulkan loader、Mesa 和 LLVM 版本。
2. 构建 macOS x86_64 Lavapipe ICD。
3. 让 helper 探针只加载随包 ICD。
4. 查询 device 和 features。

通过证据：

- Vulkan 1.2。
- timeline semaphore。
- CPU device identity。
- loader、ICD 和依赖的绝对路径。
- 版本和 SHA-256。
- 无其他 ICD 被选择。

失败时停止 Gate 2。

## 3. Gate 2：真实 IOSurface 清屏

工作：

1. 创建真实单 plane `BGRA8Unorm` IOSurface。
2. 写入非零 sentinel。
3. 导入或复制到 Lavapipe。
4. 提交 clear。
5. 等待完成后读回。

通过证据：

- 活动像素正确。
- row padding 不变。
- raw bytes 和 SHA-256。
- 明确记录 in-place、shadow 或 copy。
- Vulkan validation 无错误。

该 Gate 关闭 B-006 的首个部分。

## 4. Gate 3：真实 metallib 三角形

工作：

1. 用目标 SDK 生成最小 metallib。
2. 调用固定提交的 metal2vulkan。
3. 建立 render pipeline。
4. 绘制非索引三角形。
5. 对比 CPU reference。

通过证据：

- metallib SHA-256。
- 每个 SPIR-V stage 的 SHA-256。
- PipelineArtifact、BindingPlan 和 requirements 指纹。
- layout、interface 和固定功能状态均由上游产生。
- verifier 结果。
- PNG 和 raw bytes。
- 固定采样点正确。
- 无未解释 degradation。

## 5. Gate 4：helper 隔离

工作：

1. 定义 wire protocol v1。
2. 实现 namespace、object ID 和 generation。
3. 通过 Mach/XPC 传 IOSurface。
4. 重跑 Gate 3。
5. 强制结束 helper。

通过证据：

- 像素哈希与同进程路径一致。
- raw pointer 没有跨进程。
- 客户端存活。
- 在途命令全部进入 `DeviceLost`。
- 重启后旧 handle 被拒绝。

该 Gate 关闭 B-007 的运行部分。

## 6. Gate 5：Metal.framework 枚举

前置条件：

- Gate 4 通过。
- B-009 关闭。
- B-012 关闭。

工作：

1. 建立静态 Objective-C 对象族。
2. 实现最小精确 selector。
3. 安装 proxy bundle。
4. 让 Metal.framework 枚举设备。
5. 通过普通 Metal app 重跑 Gate 3。

通过证据：

- `MTLCopyAllDevices` 可见。
- registry ID 与 IOKit service 一致。
- 没有自定义 factory 绕过框架。
- 不使用动态 selector fallback。
- 普通 Metal app 像素正确。

## 7. Gate 6：WindowServer 首帧

前置条件：

- Gate 5 通过。
- B-008 关闭。
- B-010 关闭。

工作：

1. 实现 accelerator 和 display provider。
2. 发布一个 display mode。
3. 接收 scanout IOSurface。
4. 关联 render 和 frame sequence。
5. 输出到 framebuffer 或网络 sink。

通过证据：

- WindowServer 枚举 display。
- mode 有效。
- scanout IOSurface 可追踪。
- 首帧像素正确。
- swap completion 单调完成。
- WindowServer 不重启。

## 8. Gate 7：恢复

工作：

1. helper kill。
2. helper timeout。
3. display sink 断开。
4. sleep 和 wake。
5. 新 generation 资源重建。

通过证据：

- WindowServer 不崩溃。
- 显示进入确定状态。
- 所有 waiter 被唤醒。
- callback 只执行一次。
- 新 generation 可恢复首帧。

## 9. 剩余阻断项

| 编号 | 内容 | 关闭方式 |
|---|---|---|
| B-006 | IOSurface import | Gate 2 像素证据 |
| B-007 | XPC 权限与 bootstrap | Gate 4 目标 guest trace |
| B-008 | framebuffer 用户 ABI | x86_64 IDB 或动态 trace |
| B-009 | bundle 签名与 trust | 目标 guest 加载 trace |
| B-010 | 云平台输出路径 | 每个平台设备探针 |
| B-011 | installed SystemOS 样本 | UUID、SHA-256 和 IDB |
| B-012 | framework 启动 selector | 目标 guest 方法 trace |

## 10. 开发批次

每个批次只做一个 Gate。

每批必须交付：

- 源码。
- 构建清单。
- 测试命令。
- 原始证据。
- 结果摘要。
- 新发现的阻断项。

前一个 Gate 未通过，不启动后一个 Gate。

## 11. OpenCore 支线

OpenCore 支线独立排期。

它不得与 Metal Gate 混为一个构建任务。

首个里程碑只要求：

1. 读取云平台设备。
2. 进入 launchd。
3. 保存串口和崩溃记录。
4. 不改变 Metal helper 的 ABI。
