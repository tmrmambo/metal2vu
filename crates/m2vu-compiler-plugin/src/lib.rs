//! Metal compiler plugin。
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
