//! ObjC 侧的 Metal driver shim。
//!
//! 规格：`docs/spec/20-OBJC-DEVICE.md`、`21-OBJC-OBJECT-FAMILY.md`、
//! `22-OBJC-DESCRIPTORS.md`、`42-RUNTIME-MAPPING.md`
//!
//! # 五个接入点
//!
//! `20` 分册确证并由 `91` §2.1 运行期核对：驱动真正的接入点是 5 个
//! **不在任何协议里**的 `_MTLDevice` 虚方法（基类全 `return nil`，必须覆写）。
//! `91` 在 25 个协议里全量检索，零泄漏。
//!
//! ```text
//! newVertexVariantWithCompilerOutput:pipelineStatisticsOutput:
//! newFragmentVariantWithCompilerOutput:pipelineStatisticsOutput:
//! newComputeVariantWithCompilerOutput:pipelineStatisticsOutput:
//! newRenderPipelineWithDescriptor:vertexVariant:fragmentVariant:errorMessage:
//! newComputePipelineWithDescriptor:variant:errorMessage:
//! ```
//!
//! `AppleParavirtDevice` 对 `newLibraryWithData:error:`、
//! `newFunctionWithName:`、`newRenderPipelineStateWithDescriptor:error:`
//! 等**零 IMP** —— metallib 解析在 Metal.framework 内，不在驱动里。
//!
//! # 继承
//!
//! `91` §2.1 实测：`AppleParavirtDevice : MTLIOAccelDevice : _MTLDevice :
//! NSObject`。类名**无前导下划线**；`_MTLDevice` 是其父类，两者是不同的类。
//!
//! `91` §2.2 证伪了 `21` 的四个类名：`_MTLRenderCommandEncoder`、
//! `_MTLComputeCommandEncoder`、`_MTLBlitCommandEncoder`、`_MTLBuffer`、
//! `_MTLTexture` **都不存在**。资源链真实形态是
//! `MTLIOAccelBuffer -> MTLIOAccelResource -> _MTLResource ->
//! _MTLAllocation -> _MTLObjectWithLabel`。
//! encoder 宿主类**没有 Apple 抽象基类可继承**，所以「`endEncoding` 之后
//! 对象进入什么状态」完全由本项目定义（`42` §3.2）。

#![cfg_attr(not(target_os = "macos"), allow(dead_code))]

/// APV 的 `featureProfile`。
///
/// `20`/`21` 确证：`S-APV +0xACC3` 处 `mov eax, 2710h`，即 **10000**
/// （AMD 是 10002）。整张 limits 表是这个枚举值的纯函数。
pub const APV_FEATURE_PROFILE: u32 = 10_000;

/// 五条 release 断言必须非零，否则进程终止（`20` §5.2）。
pub const REQUIRED_NONZERO_LIMITS: &[&str] = &[
    "maxColorAttachments",
    "maxIndirectBuffers",
    "maxIndirectTextures",
    "maxIndirectSamplers",
    "maxIndirectSamplersPerDevice",
];

/// encoder 的四态单向状态机（`42` §3.2）。
///
/// 上游的 `end_encoding` **消费** self，而 ObjC 侧 `endEncoding` 之后对象
/// 还在、还能被 retain。这个错配是实现期一定会踩的坑。
///
/// `endEncoding` 是 `void`，吞掉 `Result`；错误的唯一出口是
/// `CommandBuffer::commit_failed(CommitFailure)`。
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum EncoderState {
    Encoding,
    Ended,
    EndedFailed,
    Dropped,
}

impl EncoderState {
    /// 消费后再调编码命令 → 让命令缓冲失败（默认档）。
    /// `label` / `device` / debug 组正常答；`tileWidth`/`tileHeight` 答缓存值；
    /// 重复 `endEncoding` 忽略。
    pub fn accepts_encoding_command(self) -> bool {
        matches!(self, EncoderState::Encoding)
    }
}

/// `MTLDeviceSPI` 的协议条目数。`91` §2.4 运行期确证。
pub const MTL_DEVICE_SPI_REQUIRED: usize = 427;
pub const MTL_DEVICE_SPI_OPTIONAL: usize = 80;

/// `argumentBuffersSupport` 必须返回 0 或 1，别的值终止进程（`20` §5.2）。
/// APV 返回 0（Tier1），`91` §2.1 实测确认。
pub const APV_ARGUMENT_BUFFERS_TIER: u64 = 0;

/// 五个接入点的实现入口。
pub trait PipelineHooks {
    /// `42` §5 的转发表起点。
    fn new_vertex_variant(&self) -> Result<(), ShimError>;
    fn new_fragment_variant(&self) -> Result<(), ShimError>;
    fn new_compute_variant(&self) -> Result<(), ShimError>;
    fn new_render_pipeline(&self) -> Result<(), ShimError>;
    fn new_compute_pipeline(&self) -> Result<(), ShimError>;
}

#[derive(Debug, thiserror::Error)]
pub enum ShimError {
    #[error("尚未实现")]
    NotImplemented,
}
