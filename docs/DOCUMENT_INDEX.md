# 文档索引与状态

状态日期：2026-10-31

> [!IMPORTANT]
> **2026-10-30 起，权威规格是 `docs/spec/`（16 份，约 1.5 MB）。**
> 本目录与 `analysis/` 下的文档降级为**证据与历史**。两者冲突时一律以 `docs/spec/` 为准。
> 旧文档中已确认被取代的结论，逐条列在 [spec/00-OVERVIEW.md](spec/00-OVERVIEW.md) 第 4 节。

## 0. 阅读顺序（新）

1. [spec/00-OVERVIEW.md](spec/00-OVERVIEW.md) —— 锚文档。目标、边界、组件、证据规则、被取代结论
2. 按要做的组件读对应分册，见 `00-OVERVIEW.md` 第 8 节的分册职责表
3. [spec/90-EVIDENCE-INDEX.md](spec/90-EVIDENCE-INDEX.md) —— 任何地址引用前先查样本层级

`docs/spec/` 分册一览：

| 分册 | 内容 |
|---|---|
| `00-OVERVIEW` | 锚文档 |
| `10` `11` `12` | 内核侧：accelerator / display / IOSurface |
| `20` `21` `22` | ObjC 侧：Device 继承契约 / 对象族与 selector / descriptor |
| `30` `31` `32` | Shader 侧：AIR 格式与覆盖率 / PipelineArtifact / **compiler plugin ABI** |
| `40` | Metal→Vulkan 映射与 Lavapipe 要求 |
| `50` | 进程模型、wire protocol、恢复 |
| `60` | 全量能力矩阵 |
| `70` `80` | 构建打包 / 自动化实验管线 |
| `90` | 证据索引 |

## 1. 旧阅读顺序（仅用于查历史结论）

1. [../README.md](../README.md)
2. [../PROJECT_SPEC.md](../PROJECT_SPEC.md)
3. [CAPABILITY_PROFILES.md](CAPABILITY_PROFILES.md) —— **`MVP-1` 档已作废**
4. [ARCHITECTURE_AND_LANGUAGES.md](ARCHITECTURE_AND_LANGUAGES.md)
5. [METAL2VULKAN_INTEGRATION.md](METAL2VULKAN_INTEGRATION.md) —— **第 5 节禁令已被吸收决定取代**
6. [IMPLEMENTATION_ROADMAP.md](IMPLEMENTATION_ROADMAP.md)
7. [../analysis/macos26-guest-metal-driver-spec.md](../analysis/macos26-guest-metal-driver-spec.md) —— **B-008 盯错家族**

## 2. 现行合同

| 文档 | 状态 | 作用 |
|---|---|---|
| `README.md` | 有效 | 项目入口和真实进度 |
| `PROJECT_SPEC.md` | 有效 | 总目标、边界和决策 |
| `CLOUD_DEPLOYMENT_SPEC.md` | 有效约束 | 未知宿主和安全合同 |
| `docs/CAPABILITY_PROFILES.md` | 有效 | 最小、完整、API 完整能力 |
| `docs/ARCHITECTURE_AND_LANGUAGES.md` | 有效 | 组件、进程、语言和目录 |
| `docs/METAL2VULKAN_INTEGRATION.md` | 有效 | 上游复用和适配边界 |
| `docs/IMPLEMENTATION_ROADMAP.md` | 有效 | Gate、阻断项和交付顺序 |
| `analysis/macos26-guest-metal-driver-spec.md` | 有效 | Metal 1.0 实现合同 |
| `analysis/spec-work/metal-registration-contract.md` | 有效附件 | 注册、plugin 和 initializer ABI |
| `analysis/spec-work/bridge-runtime-contract.md` | 有效附件 | selector、IPC、寿命和同步 |

## 3. 证据报告

这些文件提供证据，不单独决定架构：

| 文档 | 用途 |
|---|---|
| `analysis/macos26-metal-user-spi.md` | AMD 与 Intel Metal 类和 selector 证据 |
| `analysis/macos26-iogpu-display-registration.md` | IOGPU、Display、IOSurface 和 APV 证据 |
| `analysis/metal2vulkan-gap-architecture.md` | 上游能力、旧原型缺口和许可证证据 |
| `analysis/idb/` | 持久化 IDA 数据库和清单 |

证据报告中的历史建议可能被新约束取代。

发生冲突时，按以下顺序决定：

1. 当前目标 guest 的 `TESTED` 证据。
2. `analysis/macos26-guest-metal-driver-spec.md`。
3. 根目录现行合同。
4. 单项证据报告。
5. `deprecated/` 中的历史文件。

## 4. 历史文件

`deprecated/` 中的内容全部停用。

它们不得用于：

- 当前构建。
- 当前测试通过声明。
- 部署。
- 新功能补丁。

## 5. 文档完成情况

| 内容 | 状态 |
|---|---|
| guest-only 总规格 | 已完成 |
| 最小能力规格 | 已完成 |
| 完整项目能力规格 | 已完成 |
| API 完整判定规则 | 已完成 |
| 语言和组件分工 | 已完成 |
| 工程目录设计 | 已完成 |
| metal2vulkan 接入边界 | 已完成 |
| Gate 路线 | 已完成 |
| 云部署约束 | 已完成 |
| OpenCore 详细实现规格 | 尚未开始 |
| 目标 guest 运行记录 | 尚未产生 |
| 平台设备矩阵 | 等待各平台探针 |

文档合同已足够开始 Gate 1。

运行数据仍需后续补入。
