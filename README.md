# KVM macOS Guest 项目

状态日期：2026-10-29

## 当前结论

项目采用 guest-only 架构。所有必需组件必须位于 macOS guest。

不得依赖修改宿主、QEMU、KVM、Hyper-V、宿主 GPU 或宿主 Vulkan。

Metal 支线已完成 Gate 0 静态规格。尚无目标 guest 运行结果。

| 支线 | 当前状态 | 下一门 |
|---|---|---|
| OpenCore 客制化与运维 | 尚未开始 | 先定义设备探针与启动基线 |
| Metal 到 Lavapipe | Gate 0 `PASS-STATIC` | Gate 1：guest Lavapipe 启动 |

## 当前架构

```text
Metal client / WindowServer
          |
          v
Metal.framework
          |
          v
Objective-C proxy bundle
          |
          | versioned Mach/XPC IPC
          v
Rust render helper
  - metal2vulkan-air
  - metal2vulkan compiler
  - metal2vulkan-runtime
  - Vulkan loader
  - Lavapipe ICD
          |
          v
IOSurface
          |
          +--> guest framebuffer sink
          +--> guest network display sink
```

AIR 到 SPIR-V 由 metal2vulkan 直接完成。

项目只增加系统适配层，不增加第二套 AIR 转换器。

## 文档入口

**权威规格是 [`docs/spec/`](docs/spec/)（16 份）。先读 [`docs/spec/00-OVERVIEW.md`](docs/spec/00-OVERVIEW.md)。**

| 文档 | 用途 |
|---|---|
| [docs/spec/00-OVERVIEW.md](docs/spec/00-OVERVIEW.md) | **锚文档**：目标、边界、组件、证据规则、被取代的旧结论 |
| [docs/spec/90-EVIDENCE-INDEX.md](docs/spec/90-EVIDENCE-INDEX.md) | 全部样本的架构、层级、UUID、SHA-256 |
| [docs/DOCUMENT_INDEX.md](docs/DOCUMENT_INDEX.md) | 分册地图与新旧文档的关系 |
| [CLOUD_DEPLOYMENT_SPEC.md](CLOUD_DEPLOYMENT_SPEC.md) | 不可控制宿主时的部署合同 |
| [docs/ARCHITECTURE_AND_LANGUAGES.md](docs/ARCHITECTURE_AND_LANGUAGES.md) | 组件、语言和目录设计 |

下列文档保留为**证据与历史**，与 `docs/spec/` 冲突时以后者为准：
[PROJECT_SPEC.md](PROJECT_SPEC.md)（§4 已取代）、
[docs/CAPABILITY_PROFILES.md](docs/CAPABILITY_PROFILES.md)（`MVP-1` 已作废）、
[docs/METAL2VULKAN_INTEGRATION.md](docs/METAL2VULKAN_INTEGRATION.md)（§5 禁令已取代）、
[docs/IMPLEMENTATION_ROADMAP.md](docs/IMPLEMENTATION_ROADMAP.md)（前置条件已过时）、
[analysis/](analysis/)（逆向证据，分架构标注）。

## 旧原型

旧 Gallium 原型和旧规格位于 [deprecated](deprecated/README.md)。

它们只保留为历史证据。不得继续开发或用于交付。

## 当前下一步

1. 固定 metal2vulkan 上游提交和补丁清单。
2. 在目标 guest 构建 Vulkan loader 与 Lavapipe。
3. 完成 Gate 1 设备和功能探针。
4. Gate 1 通过后，再做真实 IOSurface 清屏。
