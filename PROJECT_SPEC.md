# KVM macOS Guest 项目总规格

文档版本：2.0-guest-only  
状态：**部分被取代**，见下  
基线日期：2026-10-29

> [!IMPORTANT]
> **权威规格已移至 `docs/spec/`。** 本文保留为项目目标与边界的简述，但以下内容已被取代：
> - **第 4 节「不得新增第二套 AIR parser、AIR IR 或 SPIR-V 生成器」** —— 已改为**吸收 metal2vulkan 并自行维护**（fork 为独立 crate、保留 git 历史）。见 `docs/spec/00-OVERVIEW.md` 第 4.6 节。
> - **第 5 节引用的 `MVP-1` 能力档** —— 已作废（内部矛盾：要桌面却要求 blend/compute 报 false）。见 `docs/spec/60-CAPABILITY-MATRIX.md`。
> - **第 10 节的权威合同指向** —— 现为 `docs/spec/00-OVERVIEW.md`。
>
> 第 2 节的边界、第 9 节的证据规则仍然有效，并在 `docs/spec/00-OVERVIEW.md` 第 2、7 节细化。

## 1. 目标

项目包含两条支线：

1. OpenCore 客制化与运维便利化。
2. guest-only Metal 到 Lavapipe 图形链。

当前重点是第二条支线。

目标是在不可控制的 KVM 或 Hyper-V guest 中提供 CPU Metal 路径。

## 2. 不可改变的边界

- 不修改宿主、QEMU、VMM 或云平台。
- 不假定宿主提供 GPU、Vulkan、VirGL 或 Venus。
- 不要求 GPU 直通。
- 所有运行组件随 guest 交付。
- 目标基线是 macOS 26.7.2，build 25G325，x86_64。
- arm64 样本只能用于协议参考。
- 未经目标 guest 验证的能力不得声明可用。

## 3. Metal 主链

```text
Metal.framework
  -> Objective-C proxy
  -> Mach/XPC IPC
  -> Rust render helper
  -> metal2vulkan
  -> Vulkan loader
  -> Lavapipe
  -> IOSurface
  -> guest display sink
```

系统显示提供者独立于渲染 helper：

```text
WindowServer
  -> C++ display provider
  -> scanout IOSurface
  -> completion fence
  -> framebuffer or network sink
```

## 4. 上游复用决定

metal2vulkan 是唯一 AIR 到 SPIR-V 实现。

直接复用以下部分：

- `metal2vulkan-air`：metallib、AIR bitcode 和 AIR ABI。
- `metal2vulkan`：lowering、SPIR-V 生成、链接和校验。
- `metal2vulkan-runtime`：Metal 对象语义和 Vulkan 调度。

项目新增的是适配层：

- Objective-C ABI 适配。
- IPC 对象和消息适配。
- IOSurface 适配。
- capability、错误和恢复适配。
- IOGPU 与显示注册适配。

不得新增第二套 AIR parser、AIR IR 或 SPIR-V 生成器。

## 5. 能力目标

能力分为三档：

| 档位 | 用途 | 定义 |
|---|---|---|
| 最小能力 | 第一个可交付桌面 | 单设备、单显示、基础 render、IOSurface 首帧 |
| 完整项目能力 | 常用桌面和应用 | render、compute、blit、同步、恢复和多显示 |
| API 完整 | macOS 26 Metal 兼容声明 | 全部必需 selector 和所选可选 selector 逐项验证 |

详细范围见 [docs/CAPABILITY_PROFILES.md](docs/CAPABILITY_PROFILES.md)。

## 6. 语言分工

| 边界 | 语言 |
|---|---|
| Metal Objective-C 对象和 selector | Objective-C |
| 描述符、block、NSError 和 retain/release | Objective-C |
| helper、IPC、对象表和恢复 | Rust |
| metal2vulkan 接入和 Vulkan 调度 | Rust |
| IOKit、IOUserClient 和显示提供者 | C++ |
| Objective-C 与 C++ 的窄交界 | Objective-C++ |
| Mesa、Lavapipe 和 Vulkan loader | 上游 C/C++ |

详细设计见 [docs/ARCHITECTURE_AND_LANGUAGES.md](docs/ARCHITECTURE_AND_LANGUAGES.md)。

## 7. 当前进度

| 项目 | 状态 |
|---|---|
| guest-only 边界 | 已冻结 |
| Metal 注册静态合同 | 已完成 |
| 最小 selector ABI | 已完成 |
| IPC、寿命和错误合同 | 已完成 |
| metal2vulkan 静态映射 | 已完成 |
| 目标 guest Lavapipe | 未测试 |
| 真实 IOSurface 像素 | 未测试 |
| helper 进程 | 未实现 |
| Objective-C proxy | 未实现 |
| IOGPU/display provider | 未实现 |
| WindowServer 首帧 | 未测试 |
| OpenCore 运维支线 | 尚未开始 |

Gate 0 结果是 `PASS-STATIC`。

该结果只允许开始编码，不代表功能可用。

## 8. 实现顺序

1. Gate 1：guest Lavapipe。
2. Gate 2：真实 IOSurface 清屏。
3. Gate 3：真实 metallib 三角形。
4. Gate 4：helper 隔离。
5. Gate 5：Metal.framework 枚举。
6. Gate 6：WindowServer 首帧。
7. Gate 7：崩溃恢复。

不得跳过前门，直接开发完整显示驱动。

## 9. 证据规则

- `KNOWN`：源码、二进制或公开 ABI 直接证明。
- `INFERRED`：合理实现选择，尚未实测。
- `BLOCKED`：缺少必要样本或运行证据。
- `TESTED`：目标 guest 已通过定义的验收。

模拟对象、空实现和假完成不能作为运行证据。

## 10. 当前权威合同

Metal 的逐项实现合同是：

[analysis/macos26-guest-metal-driver-spec.md](analysis/macos26-guest-metal-driver-spec.md)

注册和运行附件是：

- [analysis/spec-work/metal-registration-contract.md](analysis/spec-work/metal-registration-contract.md)
- [analysis/spec-work/bridge-runtime-contract.md](analysis/spec-work/bridge-runtime-contract.md)

历史 Gallium 规格已移入 [deprecated](deprecated/README.md)。
