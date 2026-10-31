//! IOSurface 用户态桥。
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
