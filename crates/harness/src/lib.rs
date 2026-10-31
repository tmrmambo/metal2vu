//! 自动化实验管线。
//!
//! 规格：`docs/spec/80-TEST-HARNESS.md`
//!
//! # 排期纪律（`80` §4.1，不要违反）
//!
//! > **E0 之前只写 E0 需要的代码。** E0-L1 需要的只有：启一个 QEMU、
//! > 读串口、跑 SSH 命令、落一个 JSON。那大概是四百行。
//!
//! 而且：**E0 之前不要写 MCP 工具面。** 工具面是对一个已能工作的管线的
//! 封装；先封装再实现会得到一个形状错误的 API。
//!
//! `80` §5.5 把「花六周把 harness 做得很漂亮，而 guest 上依然什么都没跑过」
//! 列为最可能实际发生的失败模式。本 crate 的骨架因此刻意只声明 trait，
//! 不预先铺实现。

#![forbid(unsafe_code)]

/// 平台层：实例生命周期、快照、payload 投放。
///
/// 两个实现：`LocalQemu`（QMP over unix socket）与 `Vultr`
/// （`api.vultr.com/v2` + Block Storage）。测试用例本身不感知差异。
pub trait Platform {
    fn layer(&self) -> Layer;
}

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Layer {
    /// 本地 KVM。有 host 层画面、输入注入与串口。
    L1,
    /// 云实例。**没有** host 层画面、没有输入注入、没有串口（`80` §1.3、§1.4）。
    L2,
}

/// 画面与输入。
///
/// `80` §3.3.4 修订后的语义：L1 全部可用；L2 取决于 guest 内 ARD/VNC
/// （§2.3.5）是否连得上 —— 桌面活着时可用但 `host_level: false`，
/// 桌面死掉、未进系统或 `-vnclegacy` 被拒时整组 `unsupported`。
///
/// **L2 上的截图不构成 T3 判据**（§2.3.5 告警 1）：取帧路径穿过本项目正在
/// 改的 WindowServer/CoreGraphics 捕获链，一张黑图无法区分「没渲染」与
/// 「捕获坏了」。所以返回体必须带 `attributable: false`。
pub trait ScreenIO {
    fn caps(&self) -> ScreenCaps;
}

#[derive(Clone, Copy, Debug)]
pub struct ScreenCaps {
    pub capture: bool,
    pub input: bool,
    /// host 层取帧。L2 恒为 false。
    pub host_level: bool,
}

/// 命令执行。`Ssh`（russh）两层共用；`SerialLine` 仅 L1。
pub trait Shell {
    fn layer(&self) -> Layer;
}

/// `Unsupported` 与 `Timeout` 必须严格区分（`80` §2.3）。
///
/// 前者是平台不具备（Vultr 上必然发生），用例记 `skipped`；后者是真实失败。
/// 混成一个错误码会让 L2 上全部 T3/T4 用例变成假失败，淹没真信号。
///
/// `Timeout` 必须携带最后一帧 —— 那是唯一能说明「卡在哪一屏」的证据。
#[derive(Debug, thiserror::Error)]
pub enum ScreenError {
    #[error("平台不具备该能力：{0}")]
    Unsupported(&'static str),
    #[error("超时")]
    Timeout,
}
