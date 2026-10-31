#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成 workspace 内各 crate 的骨架。

骨架的意思是：`cargo check` 能过，模块边界与公开契约按分册写死，函数体是
`todo!()` 加一条指向分册小节的注释。**不写假实现。** 一个返回 `Ok(())` 的
空壳比 `todo!()` 危险，因为它会在集成时骗过调用方。

幂等：已存在的文件不覆盖。
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CRATES = {
    # ---------------------------------------------------------------
    "m2vu-capability": dict(
        spec="60-CAPABILITY-MATRIX.md / 43-COVERAGE-REFUSALS.md",
        what="能力矩阵与诚实的能力报告",
        deps=["metal2vulkan", "metal2vulkan-runtime", "serde", "serde_json", "thiserror"],
        lib='''//! 能力矩阵与能力报告。
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
''',
    ),
    # ---------------------------------------------------------------
    "m2vu-iosurface": dict(
        spec="41-IOSURFACE-USERSPACE.md",
        what="IOSurface 用户态桥",
        deps=["metal2vulkan-runtime", "thiserror", "tracing"],
        lib='''//! IOSurface 用户态桥。
//!
//! 规格：`docs/spec/41-IOSURFACE-USERSPACE.md`
//!
//! 这是 `40-RUNTIME-VULKAN.md` 第 4 节「上游不做的十项」里第 1、2 项的
//! 实现，并承担第 6 项的 `MTLSharedTextureHandle` 一半。
//!
//! 三条来自 `41` 的硬规则，实现时不得违反：
//!
//! - **R41-1**：不得假定 plane 连续、不得假定 tightly packed、不得用
//!   `base + Σ plane_size` 推下一个 plane。每个 plane 独立取
//!   `IOSurfaceGetBaseAddressOfPlane`，行距独立取
//!   `IOSurfaceGetBytesPerRowOfPlane`。
//! - **R41-3**：几何导入时测一次，**base address 每次 lock 后必须重读**。
//!   跨 lock 边界缓存 base 是错的。
//! - **R41-17**：本 crate 内**禁止出现** `mach_make_memory_entry_64`。
//!   IOSurface 走 Mach port right + 内核 `IOSurfaceClient::mapInTask`，
//!   与 memory entry 是两条独立机制；混用会把 `50` 分册 U-01 的未知
//!   传染到本来不依赖它的路径上。

#![cfg_attr(not(target_os = "macos"), allow(dead_code))]

/// 轴 1：`VkBuffer` 背后的 `VkDeviceMemory` 是不是 surface 自己的页。
///
/// 判定依据是内存**可映射性**（`41` §2.1）。
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum HostBufferAxis {
    ImportedHostPages,
    CopiedHostPages,
}

/// 轴 2：着色器触碰的 `VkImage` 是不是落在轴 1 那块内存上。
///
/// 判定依据是布局**可接受性**（`41` §2.1）。
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum TextureAxis {
    InPlaceImage,
    ShadowedTexture,
}

/// 两轴组合。四格 = in-place / shadow / copy + 一个双重代价的最坏格。
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub struct ImportMode {
    pub host_buffer: HostBufferAxis,
    pub texture: TextureAxis,
}

impl ImportMode {
    /// `50` 分册 D103：只有这一个组合算直接路径。
    pub fn is_direct(self) -> bool {
        self.host_buffer == HostBufferAxis::ImportedHostPages
            && self.texture == TextureAxis::InPlaceImage
    }

    /// R41-5：双重代价的最坏格。出现在**我们自己创建的** surface 上
    /// 等于实现缺陷，必须当缺陷查而不是当降级报。
    pub fn is_worst_cell(self) -> bool {
        self.host_buffer == HostBufferAxis::CopiedHostPages
            && self.texture == TextureAxis::ShadowedTexture
    }
}

/// 本次判定落到该取值的**那一条**原因。不是「不满足条件」这种空话。
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum ImportReason {
    BaseMisaligned { base: usize, required: usize },
    AllocSizeMisaligned { size: usize, required: usize },
    ImportGateRefused,
    RowPitchMismatch { surface: usize, vulkan: usize },
    FormatNeedsMerge,
    LinearTilingUnsupported,
    UsageUnsupportedLinear,
}

/// `RGB10A8_2P_XR10` 在 IOSurface 侧的 `OSType`。
///
/// `41` §3.5 确证：`'b3a8'` = `0x62336138` = 1647534392。两 plane **RGB**
/// （`ContainsYCbCr = 0`、`ContainsRGB = 1`），不是 YCbCr —— `60` §3 把它
/// 归进 YCbCr 一行是归类错误。
///
/// `43` §4.2 把它定为 WindowServer 首帧 19 项里最致命的一项：
/// `ExtendedRangeBlend` 在每台设备上拒绝、算术已强制 shadow、Lavapipe 的
/// input-attachment fetch 还要再加 scratch，三条成本叠在同一张登录屏
/// attachment 上。
pub const OSTYPE_RGB10A8_2P_XR10: u32 = 0x6233_6138;

/// 本 crate 对外的唯一入口。helper 与同进程版本共用它。
pub trait SurfaceBridge {
    /// D100：拿到自己的 `IOSurfaceRef` 之后**必须**重新读全部几何，
    /// `declared` 只用于交叉检查，不作为事实。
    fn measure(&self) -> Result<(), BridgeError>;

    /// 在某个 plane 上建纹理。内部跑 `41` §2.3 的决策树。
    ///
    /// R41-6：实现必须在**专用串行段**内执行并捕获本次创建期间的
    /// degradation。从全局累计计数器反推归属是错的。
    fn import_plane_as_texture(&self) -> Result<(), BridgeError>;

    /// R41-3：lock 后 base 变了就重绑，不得继续用旧指针。
    fn rebind_if_moved(&self) -> Result<bool, BridgeError>;
}

#[derive(Debug, thiserror::Error)]
pub enum BridgeError {
    #[error("surface 几何不合法")]
    InvalidGeometry,
    /// R41-2：`planeCount > 20` 拒绝导入而不是截断 —— 我们无法确认
    /// framework 返回的是截断后的几何还是真实几何。
    #[error("plane 数 {count} 超过内核的 20 硬上限")]
    TooManyPlanes { count: usize },
    #[error("未知的 IOSurface OSType {ostype:#x}")]
    UnknownOsType { ostype: u32 },
    #[error("尚未实现")]
    NotImplemented,
}
''',
    ),
    # ---------------------------------------------------------------
    "m2vu-objc": dict(
        spec="20-OBJC-DEVICE.md / 21-OBJC-OBJECT-FAMILY.md / 22-OBJC-DESCRIPTORS.md / 42-RUNTIME-MAPPING.md",
        what="ObjC Metal driver shim",
        deps=["metal2vulkan", "metal2vulkan-runtime", "m2vu-capability", "m2vu-iosurface", "thiserror", "tracing"],
        lib='''//! ObjC 侧的 Metal driver shim。
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
''',
    ),
    # ---------------------------------------------------------------
    "m2vu-compiler-plugin": dict(
        spec="32-COMPILER-PLUGIN.md / 30-SHADER-AIR.md / 31-PIPELINE-ARTIFACT.md",
        what="Metal compiler plugin（cdylib，46 个 C 导出）",
        deps=["metal2vulkan", "metal2vulkan-air", "thiserror"],
        lib='''//! Metal compiler plugin。
//!
//! 规格：`docs/spec/32-COMPILER-PLUGIN.md`
//!
//! # 它是什么
//!
//! Metal.framework 通过三跳加载链找到它：
//!
//! ```text
//! MTLCompiler (Metal.framework)
//!   -> MTLCompiler.framework/Versions/32023/MTLCompiler   (dlopen + 4 次 dlsym)
//!     -> 厂商 plugin                                       (本 crate)
//! ```
//!
//! 加载点是
//! `[[MTLCompiler alloc] initWithTargetData:cacheUUID:pluginPath:device:compilerFlags:32]`，
//! `pluginPath` = `<bundle>/Contents/Resources/libAppleParavirtCompilerPlugin.dylib`。
//! `91` §2.3 另发现一个带 `fallbackDeviceFeatureProfile:` 的第二个 init。
//!
//! # 关键事实
//!
//! - **plugin 收到的是 AIR LLVM bitcode 的原始字节**（`const void*, size_t`），
//!   不是已解析的 IR。要自己 `parseBitcodeFile`、自己读 `air.vertex` /
//!   `air.patch` 这些 named metadata。
//! - `llvmVersion` 必须是 **32023**。`91` §2 实测：工具链自报
//!   `metalfe-32023.883`，磁盘上 `MTLCompiler.framework` 并存
//!   `Versions/32023` 与 `Versions/32024`，与 `getCompilerConnectionManager`
//!   只接受 3802/3902/32023/32024（否则 `abort()`）一致。
//! - plugin 可能被加载进独立沙箱化的 `MTLCompilerService` 进程，
//!   **所以 reply 里绝不能放指针**。
//! - `pipelineStatisticsOutput` 是 40 字节厂商缓冲，末 8 字节是编译耗时 ns。
//!   APV 丢弃它，本项目也丢。
//!
//! # 导出符号
//!
//! `91` §4 在真机上实测 Intel 的 `libMTLIGCCompilerPlugin.dylib`：
//! **4 个 `MTLCompiler*` + 36 个 `AIRNT*` + 6 个无前缀别名 = 46 个导出**
//! （`32` 分册原记「40 个」，36+4 的拆分对，漏了那 6 个别名）。
//!
//! `AIRNTGetLegalizationPasses` 能让上游先降级 8 类特性（raytracing、
//! bfloat、TLS、tessellation、vertex/fragment linking 等），实质缩小
//! `30` 分册要覆盖的范围。

#![allow(non_snake_case)]

/// `32` 分册与 `91` §2 双向确证的版本常量。
pub const LLVM_VERSION: u32 = 32_023;

/// `getCompilerConnectionManager` 接受的全集。其余值 `abort()`。
pub const ACCEPTED_VERSIONS: &[u32] = &[3802, 3902, 32_023, 32_024];

/// `pipelineStatisticsOutput` 的大小。末 8 字节是编译耗时 ns。
pub const PIPELINE_STATISTICS_BYTES: usize = 40;

// -------------------------------------------------------------------------
// 四个 MTLCompiler* 导出。签名见 `32` 第 3 节。
//
// 注意：这些是 `extern "C"`，而 plugin 可能跑在沙箱化的独立进程里。
// reply 里放指针会在跨进程时变成悬垂。
// -------------------------------------------------------------------------

/// # Safety
/// 由 `MTLCompiler.framework` 通过 `dlsym` 调用，ABI 由 `32` 第 3 节规定。
#[no_mangle]
pub unsafe extern "C" fn MTLCompilerCreate() -> *mut core::ffi::c_void {
    // TODO(32 §3): 建编译上下文。
    todo!("docs/spec/32-COMPILER-PLUGIN.md 第 3 节")
}

/// # Safety
/// 同上。
#[no_mangle]
pub unsafe extern "C" fn MTLCompilerDelete(_ctx: *mut core::ffi::c_void) {
    todo!("docs/spec/32-COMPILER-PLUGIN.md 第 3 节")
}

/// 收 AIR bitcode 原始字节 + 一个 FlatBuffers 描述。
///
/// 第二个输入的 identifier 是 `AIRF` / `AIRP`，命名空间 `Air` / `Mtl4`。
/// **它的 schema 仍是 `32` 第 8 节的空白**（`91` §5.2 的 `R-002`）。
/// `91` §4 在 Intel plugin 的字符串里只找到 `FlatBuffers 1.12.0`，
/// 没有 identifier —— 它是 4 字节写在 buffer 里的，不必进字符串表。
///
/// # Safety
/// `bitcode` 必须指向 `len` 字节可读内存。
#[no_mangle]
pub unsafe extern "C" fn MTLCompilerBuildRequestWithSerializedBitcode(
    _ctx: *mut core::ffi::c_void,
    _bitcode: *const core::ffi::c_void,
    _len: usize,
) -> *mut core::ffi::c_void {
    todo!("docs/spec/32-COMPILER-PLUGIN.md 第 3、8 节")
}

/// # Safety
/// 同上。
#[no_mangle]
pub unsafe extern "C" fn MTLCompilerReleaseReply(_reply: *mut core::ffi::c_void) {
    todo!("docs/spec/32-COMPILER-PLUGIN.md 第 3 节")
}

/// 36 个 `AIRNT*` 的全名。`91` §4 在真机上取得。
///
/// 骨架阶段只记名字；逐个实现时从这里对照，防止漏导出 —— 漏一个会让
/// `MTLCompiler.framework` 的 `dlsym` 失败，而失败表现是 pipeline 创建
/// 静默返回 nil，极难定位。
pub const AIRNT_EXPORTS: &[&str] = &[
    "AIRNTClone", "AIRNTDispose", "AIRNTDisposeCompilationContext",
    "AIRNTEmitAssembly", "AIRNTEmitBuiltinExecutableImage", "AIRNTEmitDylibImage",
    "AIRNTEmitExecutableImage", "AIRNTEmitObject", "AIRNTEmitPipelineImage",
    "AIRNTEmitPipelineImages", "AIRNTGetBuiltinFunctionId",
    "AIRNTGetComputeFunctionId", "AIRNTGetDefaultArch",
    "AIRNTGetFragmentFunctionId", "AIRNTGetFunctionId", "AIRNTGetLLVMVersion",
    "AIRNTGetLegalizationPasses", "AIRNTGetMeshFunctionId",
    "AIRNTGetMostCompatibleArch", "AIRNTGetObjectFunctionId",
    "AIRNTGetPreferredAIRArch", "AIRNTGetSupportedArchs",
    "AIRNTGetSupportedBitcodeVersion", "AIRNTGetSupportedImpls",
    "AIRNTGetTileFunctionId", "AIRNTGetVendorName", "AIRNTGetVersion",
    "AIRNTGetVertexFunctionId", "AIRNTInit", "AIRNTInitCompilationContext",
    "AIRNTParseCommandLineOptions", "AIRNTSupportsArch",
    "AIRNTSupportsEmitBuiltinExecutableImage",
    "AIRNTSupportsEmitExecutableImage", "AIRNTSupportsTarget",
    "AIRNTSupportsThreads",
];

/// 6 个无前缀别名。`32` 分册原先没记。
pub const BARE_ALIASES: &[&str] = &[
    "GetFunctionId", "GetVertexFunctionId", "GetFragmentFunctionId",
    "GetComputeFunctionId", "GetObjectFunctionId", "GetMeshFunctionId",
];

#[cfg(test)]
mod tests {
    use super::*;

    /// `91` §4 实测 46 个导出：4 + 36 + 6。
    #[test]
    fn export_counts_match_runtime_evidence() {
        assert_eq!(AIRNT_EXPORTS.len(), 36);
        assert_eq!(BARE_ALIASES.len(), 6);
    }

    #[test]
    fn llvm_version_is_accepted() {
        assert!(ACCEPTED_VERSIONS.contains(&LLVM_VERSION));
    }
}
''',
        cdylib=True,
    ),
    # ---------------------------------------------------------------
    "harness": dict(
        spec="80-TEST-HARNESS.md",
        what="自动化实验管线",
        deps=["serde", "serde_json", "thiserror", "tracing"],
        lib='''//! 自动化实验管线。
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
''',
    ),
}


def write(path, text):
    full = os.path.join(ROOT, path)
    if os.path.exists(full):
        print(f"  skip (exists) {path}")
        return False
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    print(f"  wrote {path}")
    return True


def main():
    n = 0
    for name, c in CRATES.items():
        deps = "\n".join(f"{d}.workspace = true" for d in c["deps"])
        libsec = ""
        if c.get("cdylib"):
            libsec = (
                '\n[lib]\n'
                '# Metal.framework 用 dlopen + dlsym 加载它，所以必须是 cdylib。\n'
                'crate-type = ["cdylib", "rlib"]\n'
            )
        cargo = (
            f"[package]\n"
            f"name = \"{name}\"\n"
            f"description = \"{c['what']}\"\n"
            f"version.workspace      = true\n"
            f"edition.workspace      = true\n"
            f"rust-version.workspace = true\n"
            f"license.workspace      = true\n"
            f"repository.workspace   = true\n"
            f"publish = false\n"
            f"{libsec}\n"
            f"# 规格：docs/spec/{c['spec']}\n"
            f"[dependencies]\n{deps}\n"
        )
        n += write(f"crates/{name}/Cargo.toml", cargo)
        n += write(f"crates/{name}/src/lib.rs", c["lib"])
    print(f"\n{n} 个文件已写入。")
    print("注意：函数体是 todo!() 而不是返回 Ok(())。")
    print("空壳实现会在集成时骗过调用方，比未实现危险。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
