//! 能力矩阵与能力报告。
//!
//! 规格：`docs/spec/60-CAPABILITY-MATRIX.md`、`docs/spec/43-COVERAGE-REFUSALS.md`
//!
//! 本 crate 的唯一职责是把三方事实合成一份**诚实的**能力声明：
//!   1. 上游 metal2vulkan 的覆盖面与拒绝面（`43` §1、§2）
//!   2. Lavapipe 实际支持什么（`43` §3，大部分仍 `BLOCKED`，等
//!      `build-lavapipe-macos` 的产物）
//!   3. 本项目自己实现了什么
//!
//! 硬规则（`40-RUNTIME-VULKAN.md` §7.1）：**消费上游通告只许用
//! `Degradation::code()` 与 `category()`，禁止解析通告文本。**

#![forbid(unsafe_code)]

use std::collections::BTreeMap;

/// `supportsFamily:` 的答案。
///
/// `43` §5.2 的结论：本 commit 上 `Device::supports_family` 对 20 个
/// `GpuFamily` 值在**任何** Vulkan 设备上**全部返回 false**，根因是两条
/// 无条件 gap 行（`Linear textures`、`Fast resource loading`），不是
/// `PointSizeRange`。`91` §1 观测到参考实现 APV 同样全 false。
///
/// 所以本函数**转发** `Device::supports_family`，不硬编码。硬编码会在上游
/// 补上那两条之后变成谎报。
pub fn supports_family(_raw: i64) -> bool {
    // TODO(43 §5.2): 转发 metal2vulkan_runtime 的 Device::supports_family。
    // 不得硬编码 false —— 见本函数文档。
    todo!("docs/spec/43-COVERAGE-REFUSALS.md 第 5.2 节")
}

/// 一条能力的证据等级。与 `00-OVERVIEW.md` 第 7 节的标签同构。
#[derive(Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Debug)]
pub enum Evidence {
    /// 静态分析确证。
    Known,
    /// 合理实现选择，未实测。
    Inferred,
    /// 缺样本或运行证据。
    Blocked,
    /// 在 26.6.1 / 25G76 上实测通过（`91` §0.1）。
    Tested25G76,
    /// 在目标 25G325 guest 上验收通过。
    Tested,
}

/// 能力清单。`60` §6 要求只有 `Tested` 的能力才能进发布 profile。
#[derive(Clone, Debug, Default)]
pub struct Manifest {
    pub entries: BTreeMap<String, Entry>,
}

#[derive(Clone, Debug)]
pub struct Entry {
    pub supported: bool,
    pub evidence: Evidence,
    /// 不支持时「缺什么」。来源是上游 `Unsupported::needs`（`43` §2.2）。
    pub needs: Vec<String>,
    /// 稳定降级码，形如 `metal2vulkan-degrade-<kind>`。**不是人类可读文本。**
    pub degradations: Vec<String>,
}

impl Manifest {
    /// `60` §6 第 3 条：只有 `Tested` 能进发布 profile。
    pub fn release_profile(&self) -> Self {
        // TODO(60 §6): 按证据等级过滤。
        todo!("docs/spec/60-CAPABILITY-MATRIX.md 第 6 节")
    }
}
