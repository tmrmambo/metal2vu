# 开发规格总览

文档版本：1.1
基线日期：2026-10-30
状态：有效，并取代既有文档中本文第 4 节列出的结论

> 1.1 修订（由分册 `20`、`30`、`60`、`80`、`90` 的首轮调查反馈）：
> 修正基类名拼写（第 4.4 节）；补入 x86 二进制已取得的事实与随之确证的栈结论（第 4.1 节）；
> 补入第 2.5 节平台前置风险；第 4.4 节的"关键未知"已结案。

## 0. 本文作用

本文是开发手册集的锚文档。它规定目标、边界、组件划分、证据规则和各分册职责。

既有的 `analysis/` 与 `docs/` 文档中有若干方向性错误。第 4 节逐条列出被取代的结论。发生冲突时以本文和 `docs/spec/` 分册为准。

本文档集的目标是**全量能力规格**，不是最小可行集。先写最小集会导致返工。

## 1. 项目目标

在**纯 CPU、无 GPU 直通、宿主不可控制**的 macOS guest 中提供可用的 Metal 与系统显示。

实现方式是写一个胶水层，把两个现成的东西连起来：

- guest 中已有的 **Metal 客户端与 Metal.framework**
- 随包交付的 **Vulkan loader + Mesa Lavapipe（CPU Vulkan 实现）**

项目不重写 Metal，不重写 Vulkan，不重写 AIR 编译器。

## 2. 部署形态与边界

### 2.1 目标形态

macOS 作为**云平台自己的 KVM guest** 直接运行，不使用嵌套虚拟化。

参考平台是 Vultr：支持自定义 ISO、提供 VNC 控制台、提供完整 API、共享 CPU 机型即可做实验。

### 2.2 不可改变的边界

- 不修改宿主、QEMU、VMM、PCI 设备模型、云平台。
- 不假定宿主提供 GPU、Vulkan、VirGL、Venus 或任何非标设备。
- 不要求嵌套虚拟化。
- 所有运行组件随 guest 交付。

**这是项目的核心价值**：不依赖宿主，guest 自己就能跑起来，因此可以放到任何提供通用 KVM 实例的云上。

### 2.3 目标基线

- macOS Tahoe 26.7.2，build 25G325，**x86_64**。
- macOS 26 是 Intel 平台的最终版本，因此该版本的接口规范不会再有大改。这降低了对私有 ABI 做长期适配的风险。

### 2.4 研发期安全策略

研发阶段 **SIP 与 AMFI 全部关闭**，先解决能否跑通。

- OpenCore NVRAM：放开 `csr-active-config`
- boot-args：`amfi_get_out_of_my_way=1`
- 这两项在镜像构建时固化，不是每次实验要做的步骤

因此第三方 kext 可加载、`/Library/GPUBundles` 中的 bundle 可加载，签名与 trust gate 在研发期不构成阻断。分发阶段再单独处理。

### 2.5 平台前置风险（最高优先级）

本节的两项在任何实现工作之前必须先有答案。它们威胁的是第 2.1 节的部署形态本身，不是某个模块。

**风险 1：目标云平台能否启动 macOS。** `BLOCKED`

macOS 原生**没有 VirtIO 块设备驱动**，且不存在可用的第三方实现（网卡侧有 `virtio-net-osx`，块设备侧没有等价物）。社区在 KVM 上跑 macOS 的通行做法是把启动盘接成模拟 AHCI，而云平台的设备模型不可改。

缓解事实：macOS 原生有 `IONVMeFamily`，Apple 自己的机器就用 NVMe SSD。因此真正的分叉是**系统盘呈现为 NVMe 还是 virtio-blk** —— 前者大概率可启动，后者不可行。Vultr 的块存储文档提到卷在 guest 内呈现为 `vtbd`（VirtIO）或 `nda`（NVMe），但**系统盘的控制器未确证**。

关闭方式：开一台最低配实例，挂自定义 ISO，观察 macOS 安装器能否看见磁盘。成本是小时级与几美元，优先于全部编码工作。

**风险 2：云平台的可观测性低于本地。** `KNOWN`

参考平台的控制台是网页 noVNC，**API 不提供可编程的 VNC 端点**，因此云侧不能程序化截图或注入输入；**也没有串口**，因此 early boot 与 kernel panic 无法在云侧程序化取证。

直接后果，必须写进开发纪律：

1. 云侧的唯一主通道是 SSH；host 层画面与输入是**本地 KVM 独有能力**。
2. 任何内核侧改动必须先在本地串口环境通过，再推云端。否则一次 early panic 得到的是一个无法诊断的实例。
3. 需要 host 层画面才能判定的测试用例只能钉在本地层，不得作为云侧验收手段。

详见 `80-TEST-HARNESS.md` 第 1.3、1.4 节与其测试分层。

## 3. 三条边界

把"一个胶水层"拆成三条性质不同的边界。混在一起谈会把难度估错。

| 边界 | 内容 | 上游覆盖 | 难度性质 |
|---|---|---|---|
| ① Shader | AIR → SPIR-V | metal2vulkan 全包 | 查漏补缺 |
| ② API 语义 | Metal 对象与命令 → Vulkan | metal2vulkan-runtime 覆盖大部分 | 工作量，无深层未知 |
| ③ 系统集成 | 让 OS 相信存在一张显卡 | 零 | **可行性**，且不是翻译问题而是注册与握手问题 |

①② 是工作量问题。项目成败在 ③。

## 4. 本版取代的既有结论

以下结论来自既有 `analysis/` 文档，已确认有误或方向错误。分册不得继续沿用。

### 4.1 APV 在 x86 与 ARM 上是两套不同的栈

既有文档把两者混为一谈，并用 arm64 证据指导 x86 实现。实际区分如下（来源：25G325 x86_64 payload 中两个 kext 的 `Info.plist`）：

| 项目 | `AppleParavirtGPU.kext`（x86 路径） | `AppleParavirtGPUIOGPUFamily.kext`（ARM 路径） |
|---|---|---|
| `IOClass` | `AppleParavirtGPUControl` | `AppleParavirtGPU` |
| `IOProviderClass` | `IOPCIDevice` | `AppleARMIODevice` |
| 匹配方式 | `IOPCIMatch=0xEEEE106B` | `IONameMatch=paravirtualizedgraphics,gpu` |
| `IOMatchCategory`（外层） | `IOFramebuffer` | `IOAccelerator` |
| `FramebufferCount` | `0` | 未声明 |
| `IOProbeScore` | `1000000` | 未声明 |
| 依赖家族 | **IOAcceleratorFamily2、IOGraphicsFamily、IOPCIFamily、IOSurface、AppleGraphicsDeviceControl** | **IOGPUFamily、AppleParavirtIOSurface、IOMobileGraphicsFamily、IOAVFamily、IOSurface** |
| Metal plugin | `AppleParavirtGPUMetal` | `AppleParavirtGPUMetalIOGPUFamily` |
| `MetalPluginClassName` | `AppleParavirtDevice` | `AppleParavirtDevice` |

仓库中已分析的四个 `.i64`（`AppleParavirtGPUIOGPUFamily` 两份、`IOGPUFamily`、`AppleParavirtIOSurface`）**全部属于右列**，对 x86 目标不是正确参考。（更正：这四份里没有 kernel IDB；且据分册 `90` 第 3.2 节，它们的 `LC_SOURCE_VERSION` 是 `64.4.7` / `130.16.4`，而 25G325 是 `64.5.0` / `130.16.5`，**这批 arm64 样本并非 25G325**，目录名的构建标注不可信。）

**x86 侧证据已于 2026-10-30 取得，上述判断得到符号级确证。** 分册 `90` 登记全部样本。要点：

- x86_64 `AppleParavirtGPU` 中 `AppleParavirtAccelerator` 继承 `IOGraphicsAccelerator2`，`AppleParavirtFramebuffer` 继承 `IOFramebuffer`；没有任何 `IOGPUDevice` 相关基类。
- x86 `AppleParavirtGPU.kext` 的 `OSBundleLibraries` 是 `AppleGraphicsDeviceControl`、`IOAcceleratorFamily2`、`IOGraphicsFamily`、`IOPCIFamily`、`IOSurface`，**不含 IOGPUFamily**。
- `AppleParavirtIOSurface.kext` 与 `AppleParavirtGPUIOGPUFamily.kext` 的 x86_64 可执行码**确证不存在**（不是未取得）。
- 目标 kext 在安装资产中只有 `Info.plist`，可执行码全部链接进两个 x86_64 `MH_FILESET` kernel collection，已按 `LC_FILESET_ENTRY` 重建为独立 Mach-O。重建件的 `__DATA` 指针仍是 collection 级 chained-fixup 编码值，读取前必须解码。
- `AppleParavirtGPUMetal.bundle` 的可执行文件是原生独立 Mach-O，x86_64 slice 已取得。**它是 ObjC 侧的首选参考实现**，优先于 AMD/Intel 驱动。

由此作废的具体内容：display FIFO command 8 的 40 字节 payload、cursor command 4、mapper ring 16 字节条目、mapping ID 1..8191、IOGPU selector 0/2/7/9/14/16/28/29/40 等，在确认 x86 侧使用同一家族之前都不得作为实现依据。

### 4.2 B-008 盯错了显示家族

既有文档把阻断项记为"`IOMobileFramebufferLegacy` 用户 ABI 未取得"。该家族属于 ARM 路径。

x86 路径依赖 `IOGraphicsFamily`，外层 personality 的 `IOMatchCategory` 是 `IOFramebuffer`。因此 x86 显示侧应按 **IOFramebuffer / IOGraphicsFamily** 规格实现。该家族有公开源码与多个第三方先例，难度等级与私有 ABI 不同。

分册 `11-KERNEL-DISPLAY.md` 负责确证这一点并给出实现契约。

### 4.3 不把 APV 当实现，只当规格

曾考虑过"写一个合成 provider 让 Apple 自己的 APV 驱动匹配上来，在 guest 内部实现 APV 协议的宿主端"。该方案作废，理由有二：

1. APV 的 FIFO、mapping ID、doorbell、host surface 存在的唯一原因是跨 VM 边界。本项目没有那条边界，等于为了和自己通信去实现一个面向 hypervisor 的协议，完整承担抽象成本而没有收益。
2. `AppleParavirtGPUMetal.bundle` 是面向宿主 GPU 写的，强行让它指回 guest 内的软件渲染器会非常扭曲。

**APV 的正确用法是规格书。** 它是 Apple 自己为虚拟机写的驱动，不操作真实硬件寄存器，因此比 AMD/Intel 驱动可读得多，也更接近本项目要写的东西。AMD/Intel 驱动最终全是硬件寄存器操作，不适合当参考实现。

### 4.4 ObjC 侧继承 `MTLIOAccelDevice`

**命名更正**：Apple 的类名是 `MTLIOAccelDevice`，**没有前导下划线**。带下划线的 `_MTLDevice` 是它的父类，两者是不同的类。本文 1.0 版写作 `_MTLIOAccelDevice`，是笔误。

Metal.framework 的 class gate 只要求 principal class 是 `_MTLDevice` 子类，但 AMD 与 Intel 的 device 类都继承 `MTLIOAccelDevice`。

本项目的 Device 类同样继承 `MTLIOAccelDevice`，并且**整个对象族都继承 `MTLIOAccel*` 层**，与 AMD/Intel 一致。详见 `20-OBJC-DEVICE.md`。

**本文 1.0 版把"三个 init 方法对 user client 的真实依赖"列为决定 ③ 规模的关键未知。该项已结案：它不是风险。** `initLimits` / `initFeatureQueries` / `initGPUFamilySupport` 三个方法属 `_MTLDevice`（不属 `MTLIOAccelDevice`），对 user client 零依赖，整张 limits 表是 `featureProfile` 一个枚举值的纯函数。

由此确定的内核侧规模：type-5 user client 只需 selector 0（64 字节）与 selector 2（600 字节）两个固定结构；type-6 可通过把 `supportLazyInitialization` 覆写为 YES 整条绕开。**内核侧是小工程。**

唯一的硬约束是 `initLimits` 的五条 release 断言（`maxColorAttachments`、`maxIndirectBuffers`、`maxIndirectTextures`、`maxIndirectSamplers`、`maxIndirectSamplersPerDevice` 必须非零），以及 `argumentBuffersSupport` 必须返回 0 或 1。详见 `20-OBJC-DEVICE.md` 第 5.2.1 节。

### 4.5 研发期不受 B-009 约束

既有 roadmap 把 Gate 5 的前置条件写成"B-009 关闭"（第三方 bundle trust gate 实测通过）。在 SIP 与 AMFI 关闭的研发配置下该问题不发生，该前置条件应移除，否则会无谓阻塞自己。

### 4.6 metal2vulkan 的使用方式改为吸收

既有文档规定"vendor 固定 commit，只写适配层，不得新增第二套实现"。现决定**吸收并自行维护**。

- 许可证一致：metal2vulkan 与 reims-vgpu 均为 `GPL-2.0-or-later OR LGPL-3.0-or-later`，本项目开源，选定其一并保留版权声明即可。
- 吸收方式：fork 为 workspace 内独立 crate 并保留 git 历史（subtree 或 submodule），便于 rebase。**不把代码打散揉进自有模块。** 上游仍在演进且完成度有限，需要保留合并上游修复的能力。
- 吸收意味着"归本项目维护、可以直接改"，不意味着重写。

### 4.7 最小集规格作废

既有 `docs/CAPABILITY_PROFILES.md` 的 `MVP-1` 档位内部矛盾：目标写作"第一个稳定桌面和基础 AppKit"，但 render 范围要求 blend、depth/stencil、compute、indirect 全部报告 false。桌面合成不可能不用 blend 与 compute。

本文档集按全量能力编写。能力分档只用于**排期与报告**，不用于裁剪规格。`60-CAPABILITY-MATRIX.md` 负责给出全量矩阵与当前状态。

## 5. 组件清单

| # | 组件 | 语言 | 上游覆盖 | 主分册 |
|---|---|---|---|---|
| 1 | ObjC 对象族与 selector 胶水 | Objective-C | 无 | `20` `21` `22` |
| 2 | kext：accelerator service 与 user client | C++ | 无 | `10` |
| 3 | kext：display provider 与 accelerator 关联 | C++ | 无 | `11` `12` |
| 4 | IOSurface 用户态桥 | Rust / C | 仅 stand-in | `41` |
| 5 | Vulkan loader 与 Lavapipe 的 macOS x86_64 构建打包 | 上游 C/C++ | 不随 metal2vulkan 交付 | `70` |
| 6 | 进程模型与恢复 | Rust | 无，上游 handle 仅进程内 | `50` |
| 7 | 自动化测试管线 | Rust / Python | 无 | `80` |
| — | AIR → SPIR-V | Rust | metal2vulkan 全包，需审计 | `30` `31` |
| — | Metal 对象语义 → Vulkan | Rust | metal2vulkan-runtime 大部分 | `40` |

组件 2 与 3 耦合：WindowServer 选用哪个 Metal device 合成，取决于 display 挂在哪个 accelerator 上。两者必须一起设计。

## 6. 进程与模块形态

第一版**同进程**，不引入 IPC。

```text
Metal 客户端
  Metal.framework
  本项目 Metal plugin bundle（ObjC 对象族）
      | 窄 C ABI
  渲染核心（Rust：metal2vulkan + runtime + IOSurface 桥）
      | ash
  Vulkan loader -> Lavapipe ICD
      |
  IOSurface
```

helper 进程隔离在接入 WindowServer 之前引入，目的是让 Mesa/LLVM 崩溃不拖死 WindowServer。接口形状提前按可切分设计，但第一版不付出 IPC 成本。

内核侧独立：

```text
本项目 kext
  accelerator service（发布 MetalPluginName，提供 type-5 user client）
  display provider（IOFramebuffer，发布 mode，接收 scanout）
```

## 7. 证据规则

沿用既有四级标签，这部分是好的，保留：

- `KNOWN`：源码、二进制或公开 ABI 直接证明，必须给出样本、地址或引用。
- `INFERRED`：合理实现选择，尚未实测。
- `BLOCKED`：缺少必要样本或运行证据，必须写明缺什么、如何取得。
- `TESTED`：目标 guest 已通过定义的验收。

补充规则：

1. 模拟对象、空实现和假完成不是运行证据。
2. 标注证据的**架构**。arm64 证据不得用于 x86 实现决策，反之同理。
3. 标注证据的**样本来源**。BaseSystem 样本不得冒充 installed SystemOS 样本。
4. "没查" 不等于 "被阻断"。能用现有材料查清的事项不得标 `BLOCKED`。

## 8. 分册职责

| 分册 | 负责回答的核心问题 |
|---|---|
| `10-KERNEL-ACCELERATOR.md` | x86_64 25G325 上 `IOServiceMatching("IOAccelerator")` + type-5 背后是哪个内核家族；本项目 kext 必须发布什么、实现哪些 selector |
| `11-KERNEL-DISPLAY.md` | x86 显示家族确证；IOFramebuffer provider 的全量实现契约；accelerator 与 display 的关联机制 |
| `12-KERNEL-IOSURFACE.md` | IOSurface 在内核侧如何与 accelerator resource 关联；scanout surface 的所有权与生命周期 |
| `20-OBJC-DEVICE.md` | `_MTLIOAccelDevice` 继承契约；init 链对 user client 的真实依赖；必须覆写的方法集 |
| `21-OBJC-OBJECT-FAMILY.md` | 全量 Metal 协议与 selector 清单、required/optional、精确 x86_64 encoding、所有权与线程规则 |
| `22-OBJC-DESCRIPTORS.md` | 全部 descriptor 类的字段、默认值、校验与 snapshot 规则 |
| `30-SHADER-AIR.md` | AIR/metallib 格式要点；metal2vulkan 对 macOS 26 的覆盖率、缺口与缺陷清单；扩展方法 |
| `31-PIPELINE-ARTIFACT.md` | PipelineArtifact、BindingPlan、layout、interface、固定功能状态的消费契约 |
| `40-RUNTIME-VULKAN.md` | Metal 操作到上游符号的全量映射；Lavapipe 能力要求；loader 与 ICD 选择 |
| `41-IOSURFACE-USERSPACE.md` | 真实 IOSurface 创建、导入 Vulkan、对齐、in-place/shadow/copy、可见性与生命周期 |
| `50-IPC-HELPER.md` | 进程模型、wire protocol、对象表与 generation、崩溃恢复 |
| `60-CAPABILITY-MATRIX.md` | Metal 特性 × 上游支持 × Lavapipe 支持 × 本项目状态的全量矩阵 |
| `70-BUILD-PACKAGE.md` | 工具链与构建；Mesa/LLVM 在 macOS x86_64 的构建；SIP/AMFI 配置；安装布局与启动顺序 |
| `80-TEST-HARNESS.md` | 自动化管线：VNC 截图与输入、快照、guest agent、日志与证据归档、MCP 工具面 |
| `90-EVIDENCE-INDEX.md` | 全部样本的架构、来源、UUID、SHA-256 与 IDB 清单 |

## 9. 分册写作要求

1. 每条结论必须带证据标签与架构标注。
2. 地址必须附样本 UUID 与 RVA，不得只给绝对 VA。
3. 不得为未查清的事项编造默认值；写明"未查"并给出查清方法。
4. 面向实现编写：读者应能直接照着写代码，而不是再去推断。
5. 中文。
