# 41 - IOSurface 用户态桥

文档版本：1.0
基线：macOS Tahoe 26.7.2 build 25G325，**x86_64**
锚文档：`00-OVERVIEW.md`（证据规则见其第 7 节；本册是其第 5 节组件清单第 4 项）
上游锚定：metal2vulkan `219f01365dc4c8eb346816c405b5b17403793764`
配套分册：`12-KERNEL-IOSURFACE.md`（内核侧对象模型）、`40-RUNTIME-VULKAN.md`（上游契约）、`22-OBJC-DESCRIPTORS.md`（descriptor 字段）、`50-IPC-HELPER.md`（D82/D99–D104）、`11-KERNEL-DISPLAY.md`（上屏）、`21-OBJC-OBJECT-FAMILY.md`（block 生命周期）
状态：有效。本文是 `40-RUNTIME-VULKAN.md` 第 4 节「上游不做的十项」第 1、2 项的实现契约，并承担第 6 项的 `MTLSharedTextureHandle` 一半。

## 0. 本文作用与结论摘要

本文回答：用户态怎么创建与导入真实 IOSurface、怎么把它的内存交给 Vulkan、三种导入模式的判定、对齐与格式怎么对上、跨进程怎么传且怎么验权、分散后备怎么实现、生命周期与可见性的规则。

本文**不重复** `12-KERNEL-IOSURFACE.md` 的内核事实，也不重复 `40-RUNTIME-VULKAN.md` 的上游 API 清单。两者是本文的输入。

### 0.1 本轮确证的核心结论

| # | 结论 | 标签 |
|---|---|---|
| 1 | **两轴不是「可映射」×「布局可接受」，而是 host-buffer 存储轴 × texture 存储轴。** 可映射性与布局可接受性是这两轴的**判定依据**，不是轴本身。四个组合里三个对应 in-place / shadow / copy，第四个是双重代价的最坏格。见 §2.1。 | `KNOWN`（来源：`50-IPC-HELPER.md` D103 的轴定义 + 上游 `WorkCounts` 字段） |
| 2 | **本项目不自己解析 `IOSurfaceLockResult`（3176 字节）。** 它是 `IOSurface.framework` 与内核之间的传输结构，用户态的契约面是公开 getter。这把 `12` 分册 §1.5.4 里「8 个未命名字段需要用户态消费点」这条阻断从主路径上摘掉了。 | `INFERRED`（实现决策；结构事实见 `12` §1.5） |
| 3 | **`'b3a8'` 就是 `MTLPixelFormatRGB10A8_2P_XR10`（raw 550）在 IOSurface 侧的 `OSType`**，值 `0x62336138` = 1647534392。两 plane：plane 0 每像素 32 位（10:10:10 打包），plane 1 每像素 8 位 alpha（清零块为 `0xFF`，即不透明）。`BitsPerComponent = 10`、`ComponentRange = WideRange`（即 XR）、`ContainsRGB = 1`、`ContainsAlpha = 1`、`ContainsYCbCr = 0`。见 §3.5。 | `INFERRED`（强证据，九项判别属性逐条吻合；来源是第三方运行期转储，非 Apple 头文件、非本项目样本。关闭方法见 S-003） |
| 4 | **`60-CAPABILITY-MATRIX.md` §3 把 `'b3a8'` 归进「两 plane YCbCr（`YCBCR8_420_2P` 系）」一行，归类有误。** 该格式 `ContainsYCbCr = 0`、`ContainsRGB = 1`，是两 plane **RGB**。上游的 `texture/surface_two_planes.rs` 同时承载 YCbCr 与 RGB 两族，分册只取了文件名的一半。见 §3.5.2。 | `INFERRED`（同上；建议 `60` 分册据此更正） |
| 5 | **`RGB10A8_2P_XR10` 的 texture 轴被算术强制为 `ShadowedTexture`。** 上游的单一候选是 `R32G32_UINT`（8 字节/texel），而 surface 侧是 plane 0 的 4 字节 + plane 1 的 1 字节。任何单张 `VK_IMAGE_TILING_LINEAR` image 都无法在这两块内存上原地成立。见 §3.5.3。 | `INFERRED`（算术推导，输入全部 `KNOWN`） |
| 6 | **本构建上 pixel-size casting 默认是开的。** `IOSurface::init` 在 `[S] +0x4063` 无条件 `or byte [rbx+3DAh], 1`（标志字 bit 16），`isPixelCastingAllowed` / `isPixelSizeCastingAllowed` 都读这一位；唯一的关闭开关是 boot-arg `iosurface_debug` 的 bit1。因此 `IOSurfaceAllowsPixelSizeCasting` 预期返回真，而 Apple 的 `-[MTLIOAccelTexture initWithDevice:descriptor:iosurface:plane:field:args:argsSize:]` 确实调它。见 §3.1.4。 | `KNOWN`（`12` §2.2 的位表 + §1.2 第 11 步；调用点来自 `20` §8.5） |
| 7 | **全局 lookup 默认是开的，所以 IOSurface 全局 ID 在本构建上确实不构成任何授权。** `IOSurfaceRoot::start` 第 11 步解析 `iosurface_debug`，其 bit2 =「允许全局 lookup」，**默认开且带警告**；`find_surface` 的放行条件 ③ 是 `(flags & 0x80002) == 2`。ID 空间就是内核表下标（32 位、连续、可枚举）。见 §4.5。 | `KNOWN`（`12` §1.2、§3.4） |
| 8 | **U-01 不可行时本册有完整退路，且退路不依赖共享可写映射。** 代价是 `MTLBuffer.contents` 的跨进程直写改为「客户端私有页 + 显式 `didModifyRange:` 上传」，每帧多一次拷贝；IOSurface 路径本身**不受影响**，因为它走的是 Mach right 而不是 memory entry。见 §4.3/§4.4。 | `INFERRED` |
| 9 | **上屏不经过本册产出的 surface。** `IOSurface::isDisplayable()` 在本构建恒为 0（`12` §2.2 已证全件无置位点），且第一版不声明 `DisplayPipeSupported`，所以 scanout 的唯一通路是 framebuffer 内存。本册的 surface 只服务 Metal 客户端自己的 texture/buffer，到屏幕要经过一次显式拷贝。见 §7。 | `KNOWN`（机制）+ `INFERRED`（拷贝代价） |
| 10 | **自建 resource 类的 `deallocator` 成本必须记在本册，且调用点不是 `-dealloc`。** 它是上游 `KeepAlive` 被释放之时，可能比 `-dealloc` 晚数帧。`CFRelease(IOSurfaceRef)` 必须和它在同一个 KeepAlive 载荷里，不能放进 `-dealloc`。见 §6.1/§6.2。 | `KNOWN`（`21` §9.5、`22` R41/R42）+ `INFERRED`（排序推论） |

### 0.2 样本与证据约定

本文自己不新建二进制证据。引用的样本标签沿用既有分册：

| 标签 | 样本 | `LC_UUID` | 出处 |
|---|---|---|---|
| `[S]` | `kext/com.apple.iokit.IOSurface`（x86_64，Boot KC 重建件） | `766DF6D3-1EEC-34DB-A9AD-EF72A36FB2A8` | `12-KERNEL-IOSURFACE.md` §0.2 |
| `S-METAL` | `Metal.framework` x86_64 | 见 `90-EVIDENCE-INDEX.md` | `22-OBJC-DESCRIPTORS.md` |
| `D-OBJC:N` | `analysis/idb/macos26-25G325-x86_64-frameworks/metal-objc.json` 第 N 行（UTF-16LE） | — | `22` §0.1 |
| `S-APV` | `AppleParavirtGPUMetal.bundle` x86_64 | 见 `90` | `21` |
| `CI` | `macos-26-intel` 运行器（26.6.1 / 25G76，SIP 关闭，跑着 AppleParavirtGPU） | — | `91-RUNTIME-EVIDENCE.md` |

**一条重要的样本缺口，贯穿全文。** `IOSurface.framework` 的 x86_64 可执行码本轮**未取**（`12` 分册多处记为 T3 未取）。因此：

- 凡是**公开头文件已经规定**的（函数签名、属性键名、flag 常量、返回值语义），标 `KNOWN`，锚点写明「公开 ABI：`IOSurface.framework/Headers/IOSurfaceRef.h`」。公开头文件是 ABI 合同，不是推测。
- 凡是**需要看 framework 实现才能确定**的（getter 到 `IOSurfaceLockResult` 字段的具体取法、base address 在 lock 周期间是否稳定、属性键到内核 selector 的具体打包），标 `BLOCKED`，并在 §9 给取法。
- 凡是**只能在运行期观察**的（Lavapipe 的 `minImportedHostPointerAlignment` 实际值、`'b3a8'` 的格式描述字典、全局 lookup 是否真的放行），标 `BLOCKED` 并指明能否用 `91` 分册的 CI 通道取。

---

## 1. IOSurface 的用户态 API 面

### 1.1 为什么真的用这套 API

三条理由，前两条有依据，第三条是决策。

1. **它是公开 API。** `20-OBJC-DEVICE.md` §8.5 的结论：resource 层每个 `init*` 都真打内核，必须覆写；**IOSurface 相关调用是唯一的例外，因为那些是 IOSurface 框架的公开 API，本项目可以而且应该真的用**。`KNOWN`（该分册的符号级判定）
2. **自己打 selector 要重做 63 条调度表与 3176 字节结构的编解码，而这两者的用户态消费语义恰好是本轮的样本缺口。** 用 framework 等于把这段缺口挡在合同后面。`12` 分册 §1.6 已证 IOSurface 的内存**不是**通过 `IOConnectMapMemory` 拿的，而是 `s_create_surface` / `s_lock_surface` 返回的 `IOSurfaceLockResult` 里带用户态地址、由 `IOSurfaceClient::mapInTask` 在内核里直接映射进调用者 task。要绕开 framework，就得自己解 3176 字节。`KNOWN`
3. **Apple 自己在同一位置就是这么用的。** `20` §8.5/§8.6 的调用集合（`KNOWN`，`S-METAL` 的导入符号反向 xref）：

| Apple 的方法 | 它调的 IOSurface API |
|---|---|
| `-[MTLIOAccelBuffer initWithDevice:iosurface:args:argsSize:]` | `IOSurfaceGetAllocSize`、`IOSurfaceGetID` |
| `-[MTLIOAccelTexture initWithDevice:descriptor:iosurface:plane:field:args:argsSize:]` | `IOSurfaceCopyValue`、`IOSurfaceGetBaseAddress`、`IOSurfaceGetBytesPerElement`、`IOSurfaceGetBytesPerRow`、`IOSurfaceGetElementHeight`、`IOSurfaceGetHeight`、`IOSurfaceGetID`、`IOSurfaceGetPlaneCount`、`IOSurfaceAllowsPixelSizeCasting`、`IOSurfaceGetAllocSize` |
| `-[_MTLDevice newSharedTextureWithDescriptor:]` | `IOSurfaceCreate` |
| `-[_MTLDevice _newDescriptorForSharedTexture:]` | `IOSurfaceCopyValue` |
| `-[MTLSharedTextureHandle createMachPort]` / `initWithMachPort:` | `IOSurfaceCreateMachPort` / `IOSurfaceLookupFromMachPort` |
| `MTLSharedEventListenerInternal` 的 4 个方法 | `IOSurfaceSharedEvent*` |
| `-[MTLIOAccelResource setPurgeableState:]` | `IOSurfaceSetPurgeable`（与 `IOAccelResourceSetPurgeable` 并列） |

**注意第 2 行用的是 `IOSurfaceGetBaseAddress`，不是 `…OfPlane`。** 这说明 Apple 的 texture init 取的是 surface 基址，plane 的位置靠 `plane` 形参与别处取得的 offset 自己算。本项目**不照抄这一点**，改为逐 plane 用 `IOSurfaceGetBaseAddressOfPlane`（理由见 §3.2.2）。

### 1.2 本项目使用的 API 全集（C 声明，可直接照抄）

`KNOWN`（公开 ABI：`IOSurface.framework/Headers/IOSurfaceRef.h` 与 `IOSurfaceAPI.h`）。本项目只用下表，**不用其他任何 IOSurface 符号**；新增必须走 §9 的流程。

```c
/* ============ 41-iosurface/iosurface_api.h ============
 * 本项目使用的 IOSurface 公开 API 全集。
 * 只放声明；不要在这里写任何包装逻辑。
 * 链接：-framework IOSurface -framework CoreFoundation
 */
#ifndef M2VU_IOSURFACE_API_H
#define M2VU_IOSURFACE_API_H

#include <CoreFoundation/CoreFoundation.h>
#include <IOSurface/IOSurfaceRef.h>
#include <mach/mach.h>

/* ---- 1. 创建与查找 ---- */
/* IOSurfaceRef IOSurfaceCreate(CFDictionaryRef properties);                     返回 +1 */
/* IOSurfaceRef IOSurfaceLookup(IOSurfaceID csid);                              返回 +1，失败 NULL */
/* IOSurfaceID  IOSurfaceGetID(IOSurfaceRef buffer); */
/* mach_port_t  IOSurfaceCreateMachPort(IOSurfaceRef buffer);                   返回一个 send right，调用方负责 mach_port_deallocate */
/* IOSurfaceRef IOSurfaceLookupFromMachPort(mach_port_t port);                  返回 +1 */
/* xpc_object_t IOSurfaceCreateXPCObject(IOSurfaceRef buffer); */
/* IOSurfaceRef IOSurfaceLookupFromXPCObject(xpc_object_t xobj); */
/* CFTypeID     IOSurfaceGetTypeID(void); */

/* ---- 2. surface 级几何 ---- */
/* size_t   IOSurfaceGetAllocSize(IOSurfaceRef);        OSType IOSurfaceGetPixelFormat(IOSurfaceRef); */
/* size_t   IOSurfaceGetWidth(IOSurfaceRef);            size_t IOSurfaceGetHeight(IOSurfaceRef); */
/* size_t   IOSurfaceGetBytesPerElement(IOSurfaceRef);  size_t IOSurfaceGetBytesPerRow(IOSurfaceRef); */
/* size_t   IOSurfaceGetElementWidth(IOSurfaceRef);     size_t IOSurfaceGetElementHeight(IOSurfaceRef); */
/* void *   IOSurfaceGetBaseAddress(IOSurfaceRef); */

/* ---- 3. plane 级几何（本项目的主路径） ---- */
/* size_t   IOSurfaceGetPlaneCount(IOSurfaceRef); */
/* void *   IOSurfaceGetBaseAddressOfPlane(IOSurfaceRef, size_t planeIndex); */
/* size_t   IOSurfaceGetWidthOfPlane(IOSurfaceRef, size_t);            …GetHeightOfPlane */
/* size_t   IOSurfaceGetBytesPerElementOfPlane(IOSurfaceRef, size_t);  …GetBytesPerRowOfPlane */
/* size_t   IOSurfaceGetElementWidthOfPlane(IOSurfaceRef, size_t);     …GetElementHeightOfPlane */
/* size_t   IOSurfaceGetNumberOfComponentsOfPlane(IOSurfaceRef, size_t); */

/* ---- 4. lock / seed / use count ---- */
/* kern_return_t IOSurfaceLock(IOSurfaceRef, IOSurfaceLockOptions options, uint32_t *seed); */
/* kern_return_t IOSurfaceUnlock(IOSurfaceRef, IOSurfaceLockOptions options, uint32_t *seed); */
/*   kIOSurfaceLockReadOnly  = 0x00000001
 *   kIOSurfaceLockAvoidSync = 0x00000002 */
/* uint32_t IOSurfaceGetSeed(IOSurfaceRef); */
/* int32_t  IOSurfaceGetUseCount(IOSurfaceRef); */
/* void     IOSurfaceIncrementUseCount(IOSurfaceRef);  void IOSurfaceDecrementUseCount(IOSurfaceRef); */
/* Boolean  IOSurfaceIsInUse(IOSurfaceRef); */

/* ---- 5. attachment ---- */
/* void       IOSurfaceSetValue(IOSurfaceRef, CFStringRef key, CFTypeRef value); */
/* CFTypeRef  IOSurfaceCopyValue(IOSurfaceRef, CFStringRef key);     返回 +1 */
/* void       IOSurfaceRemoveValue(IOSurfaceRef, CFStringRef key);   void IOSurfaceRemoveAllValues(IOSurfaceRef); */

/* ---- 6. 对齐与上限查询 ---- */
/* size_t IOSurfaceGetPropertyMaximum(CFStringRef property); */
/* size_t IOSurfaceGetPropertyAlignment(CFStringRef property); */
/* size_t IOSurfaceAlignProperty(CFStringRef property, size_t value); */
/* Boolean IOSurfaceAllowsPixelSizeCasting(IOSurfaceRef); */

/* ---- 7. purgeable ---- */
/* kern_return_t IOSurfaceSetPurgeable(IOSurfaceRef, uint32_t newState, uint32_t *oldState); */
/*   kIOSurfacePurgeableNonVolatile = 0, Volatile = 1, Empty = 2, KeepCurrent = 3 */

#endif /* M2VU_IOSURFACE_API_H */
```

**不使用的部分，以及为什么：**

| 不用 | 理由 |
|---|---|
| `IOSurfaceCreateXPCObject` / `IOSurfaceLookupFromXPCObject` | 本项目的 wire protocol 由 `50-IPC-HELPER.md` 规定，surface 一律走 Mach right（D99）。XPC 包装是另一条等价通路，留作 U-03 不通过时的备选（§4.1.3） |
| `IOSurfaceSetPurgeable` 之外的 purgeable 辅助 | `MTLResource.purgeableState` 只需这一个 |
| `kIOSurfaceIsGlobal` 作为创建键 | 见 §4.5：全局可见不是授权，而且默认开。本项目只在 `MTLSharedTextureHandle` 路径上显式用它，并配 MAC token |
| 任何 `IOSurfaceRootUserClient` 的 selector 直调 | §1.1 理由 2 |

### 1.3 创建 surface 时的 properties key → 内核 ivar 逐条对应

`KNOWN`（键名：公开 ABI；ivar 偏移与 setter：`12-KERNEL-IOSURFACE.md` §2.2/§2.3，由 `[S] IOSurface::setLayoutFromDescriptor +0x102CA` 逐条读出）。

链路是三跳，不是一跳（`12` §2.2 的更正框已把这一点钉死）：

```text
CFDictionary（用户态）
  → [S] IOSurface::parse_properties  +0x42B0        构造 IOSurfaceDescriptor
  → [S] IOSurface::setLayoutFromDescriptor +0x102CA  descriptor getter → IOSurface ivar
  → [S] IOSurface::allocate          +0x7AB8        按 §2.4 的四条分支取内存
```

#### 1.3.1 surface 级

| properties key | `IOSurfaceDescriptor` setter（`[S]` RVA） | `IOSurface` ivar | 宽度 | 备注 |
|---|---|---|---|---|
| `kIOSurfaceWidth` | `setWidth 0x133BE` | `+0x58` | 8 | 必填 |
| `kIOSurfaceHeight` | `setHeight 0x133CA` | `+0x60` | 8 | 必填 |
| `kIOSurfaceBytesPerRow` | `setBytesPerRow 0x1343A` | `+0x68` | 8 | 不填则内核自算，**本项目一律显式填**（§3.1.2） |
| `kIOSurfaceBytesPerElement` | `setBytesPerElement 0x13448` | `+0x70` | 2 (u16) | 必填；`> 65535` 会被截断 |
| `kIOSurfaceElementWidth` | `setElementWidth 0x133D8` | `+0x72` | 1 (u8) | 非块格式填 1 |
| `kIOSurfaceElementHeight` | `setElementHeight 0x133E6` | `+0x73` | 1 (u8) | 非块格式填 1 |
| `kIOSurfaceOffset` | `setBufferOffset 0x1342C` | `+0x78` | 8 | 单 plane 时 = `planeOffset[0]` |
| `kIOSurfacePixelFormat` | `setPixelFormat 0x133B0` | `+0x80` | 4 (u32) | `OSType`，见 §3.4 |
| `kIOSurfaceAllocSize` | `setAllocSize 0x133F4` | `+0x90` | 8 | 不填则内核自算；**本项目显式填并自己校验** |
| `kIOSurfacePlaneInfo`（数组长度） | `setPlaneCount 0x1341E` | `+0x98` | 4 (u32) | **用户态写 20 以上是浪费**，见 §1.3.3 |
| 无公开键 | `setSliceCount 0x136F2` | `+0x3C0` | 4 (u32) | 本项目不设 |
| 无公开键 | `setIsTiled 0x13402` → 标志字 bit 9 | `+0x3D8` | 位 | 本项目一律 false |
| 无公开键 | `setDisableMapping 0x13410` → 标志字 bit 22 | `+0x3D8` | 位 | 本项目一律 false（置了就拿不到 CPU 映射） |
| `kIOSurfaceCacheMode` | 不经 descriptor | `BLOCKED` | — | `parse_properties` 对 `+0x3D8` 没有任何访问（`12` §2.2 已证），所以 cache mode 落在别的 ivar 上，本轮未定位。取法见 S-002 |
| `kIOSurfacePixelSizeCastingAllowed` | 不经 descriptor | 标志字 bit 16，**但 `init +0x4063` 无条件置 1** | 位 | 见 §3.1.4。即这个键在本构建上大概率被忽略 |
| `kIOSurfaceIsGlobal`（已弃用） | 不经 descriptor | 标志字 bit 1（`find_surface` 条件 ③ 读 `(flags & 0x80002) == 2`） | 位 | 见 §4.5 |
| `kIOSurfaceName` | 不经 descriptor | 属性字典 | — | 纯诊断。本项目一律填 `net.metal2vu.<role>.<objectid>` |

#### 1.3.2 plane 级

`kIOSurfacePlaneInfo` 的值是一个 `CFArray`，每项一个 `CFDictionary`。键与 setter 的对应（`KNOWN`，`12` §2.3）：

| plane key | setter（`[S]` RVA） | 说明 |
|---|---|---|
| `kIOSurfacePlaneWidth` | `setPlaneWidth 0x13456` | |
| `kIOSurfacePlaneHeight` | `setPlaneHeight 0x13474` | |
| `kIOSurfacePlaneBytesPerRow` | `setPlaneBytesPerRow 0x1350A` | **逐 plane 独立** |
| `kIOSurfacePlaneOffset` | `setPlaneOffset 0x134EC` | **逐 plane 独立，不得假定等于前一 plane 的 offset + size** |
| `kIOSurfacePlaneSize` | `setPlaneSize 0x13546` | **逐 plane 独立** |
| `kIOSurfacePlaneBase` | `setPlaneBase 0x134CE` | 与 offset 分开的另一个字段 |
| `kIOSurfacePlaneBytesPerElement` | `setPlaneBytesPerElement 0x13528` | |
| `kIOSurfacePlaneElementWidth` | `setPlaneElementWidth 0x13492` | |
| `kIOSurfacePlaneElementHeight` | `setPlaneElementHeight 0x134B0` | |
| 无公开键 | `setPlaneAddressFormat 0x13564` | 本项目不设 |
| 无公开键 | `setPlaneCompression*` 共 14 个（`0x13582`–`0x13728`） | Apple Silicon 的 lossless compression，x86 上保持 0 |

**`12` 分册 §2.3 给本册的那条结论必须原样执行：** 内核侧把 plane 表达为「每 plane 独立的 offset + bytesPerRow + size + elementWidth/Height」，**base 与 offset 是两个字段**。因此 Vulkan 侧导入时：

> **R41-1**：**不得假定 plane 连续，不得假定 tightly packed，不得用 `base + Σ plane_size` 推下一个 plane 的位置。** 每个 plane 的地址必须独立取 `IOSurfaceGetBaseAddressOfPlane(s, i)`，行距必须独立取 `IOSurfaceGetBytesPerRowOfPlane(s, i)`。单 plane BGRA8 的常规情况里 `planeCount = 1`、`planeOffset[0] = bufferOffset`，但这只是常规，不是保证。

#### 1.3.3 20 是硬上限

`KNOWN`（`12` §1.5.1/§1.5.4）。`IOSurfaceClient::getLockResult`（`[S] +0x11C0A`）里 plane 数组是 20 条 × 152 字节，循环上界按 `min(planeCount, 20)` 截断，`planeCount > 20` 的 surface **被静默截断**，用户态拿不到第 21 个 plane 的描述。

> **R41-2**：创建 surface 时 `planeCount ≤ 20`；导入 surface 时若 `IOSurfaceGetPlaneCount` 返回 `> 20`，**拒绝导入**（不是截断），理由是我们无法确认 framework 返回的是截断后的几何还是真实几何。本项目用到的最大 plane 数是 2（`'b3a8'`），余量充足。

### 1.4 lock / unlock / seed / use count 的语义

`KNOWN`（公开 ABI）+ `BLOCKED`（跨进程可见性序列，见 §6.4）。

| 调用 | 语义 | 对本项目 |
|---|---|---|
| `IOSurfaceLock(s, 0, &seed)` | 取**写**锁，使 CPU 侧映射对后续 CPU 读写有效，`seed` 回填当前内容代号 | 写入前必须取，时序见 D104 / §6.4 |
| `IOSurfaceLock(s, kIOSurfaceLockReadOnly, &seed)` | 取**读**锁。多个读者可并存 | 采样前取 |
| `kIOSurfaceLockAvoidSync` | 跳过缓存同步 | **本项目不使用**。Lavapipe 就是 CPU，不存在跨总线缓存，但「不同步」在跨进程写者在场时会把可见性问题藏起来。宁可付同步成本 |
| `IOSurfaceUnlock(s, options, &seed)` | 放锁；写锁放开时 `seed` 前进 | 时序见 §6.4 |
| `IOSurfaceGetSeed(s)` | 内容代号。**变化意味着内容变了**，不意味着几何变了 | shadow 模式的「要不要重做转换」判据 |
| `IOSurfaceIncrementUseCount` / `Decrement` / `IsInUse` | 「有人正在用它」的协作式提示，不是锁 | 导入期间 `Increment` 一次，`KeepAlive` 释放时 `Decrement` 一次 |

内核侧对应（`KNOWN`，`12` §1.4 的 selector 表 + §6.1 第 4 点）：`IOSurfaceLock` → selector 2 `s_lock_surface`（12 字节入、3176 字节出）；`IOSurfaceUnlock` → selector 3（12 字节入、4 字节出）；use count 是 per-category 的三层计数之一（`IOSurface::increment_use_count_for_category [S] 0xB05A`），与 OSObject 引用计数、client 计数是三套独立的东西。

**几何是不可变的，映射不是。** `setLayoutFromDescriptor` 只在 `init` 路径上调用一次；可变的是 selector 46 `s_set_image_origin_and_extents`（28 字节入）能改的 origin/extents，以及 `IOSurfaceClient::mapInTask` 建立的 per-task 映射。由此得到：

> **R41-3**：**几何只需在导入时测一次（D100）并在每次 lock 后交叉检查；base address 必须每次 lock 后重读。** 把 base address 缓存跨越 lock 边界是错的。重读发现 base 变了，必须走 `rebind_bytes_no_copy` 重绑（§5.2 的同一条调用），不得继续用旧指针。`INFERRED`（基于 `s_lock_surface` 每次返回一份新的 3176 字节结构、其 `+0x00` 取自 per-client 的 `clt+0x50`；framework 是否每次都把该字段回写到 getter 的返回值，是 S-001）

### 1.5 对齐与上限查询三件套

`KNOWN`（公开 ABI）。这三个函数是**本项目唯一正当的「IOSurface 要求什么对齐」信息来源**，不得硬编码常量。

```c
size_t IOSurfaceGetPropertyAlignment(CFStringRef property);  /* 该属性值必须是此值的倍数 */
size_t IOSurfaceAlignProperty(CFStringRef property, size_t value);  /* 向上取整到合法值 */
size_t IOSurfaceGetPropertyMaximum(CFStringRef property);    /* 该属性的上限，0 表示无限 */
```

本项目在启动自检里对下列键各查一次并落盘（§8.1 第 3 项）：
`kIOSurfaceAllocSize`、`kIOSurfaceWidth`、`kIOSurfaceHeight`、`kIOSurfaceBytesPerRow`、`kIOSurfaceBytesPerElement`、`kIOSurfacePlaneBytesPerRow`、`kIOSurfacePlaneOffset`、`kIOSurfacePlaneSize`。

内核侧的对偶是 selector 13 `s_get_limits`（40 字节出，`KNOWN`，`12` §1.4）。40 字节的逐字段布局本轮未取（`12` §1.5.4 把它与 160 字节的 `IOSurfaceColorAndSpatialKeysStruct` 并列为同类缺口），但本项目不解析它，只用上面三个 getter。

### 1.6 attachment（`SetValue` / `CopyValue`）

`KNOWN`（公开 ABI）+ `KNOWN`（内核侧 selector 9/10/11，`12` §1.4，**restricted 表也放行**）。

attachment 是 surface 上的一张 CF 属性字典。本项目的用法只有三类：

| 用途 | 键 | 值 | 读写方 |
|---|---|---|---|
| 诊断标识 | `net.metal2vu.role` | `CFString`：`"client-texture"` / `"shared-texture"` / `"scratch"` | 创建方写，任何方读 |
| 跨进程交叉检查（**不是凭据**） | `net.metal2vu.owner` | `CFData` 16 字节 owner UUID | 创建方写，导入方读后与自己的对象表比对 |
| 色彩信息 | `kIOSurfaceColorSpace` 等 Apple 定义的键 | 按 Apple 约定 | 透传，不解释 |

> **R41-4**：**attachment 不是授权凭据。** 任何持有 surface 的进程都能 `IOSurfaceSetValue` 覆盖任意键（selector 9 在 restricted 表里也放行）。`net.metal2vu.owner` 的作用是在 ID 碰撞或 generation 错配时**更早**地发现问题，不是替代 §4.5 的 MAC token。

selector 27/28 的 `s_set_bulk_attachments` / `s_get_bulk_attachments`（160 字节）对应 `IOSurface::setBulkAttachments(IOSurfaceColorAndSpatialKeysStruct*, size_t)`（`[S] 0xD0EA`）。本项目**不走** bulk 路径：它的 160 字节结构逐字段布局未取（`12` §1.5.4），而逐键 `SetValue` 功能等价。`INFERRED`

### 1.7 本节的 `BLOCKED` 清单

| 项 | 为什么阻断 | 对主路径的影响 |
|---|---|---|
| `IOSurfaceGetBaseAddressOfPlane` 返回值在 lock 周期之间是否稳定 | 需 `IOSurface.framework` 实现或运行探针 | 已用 R41-3 兜住（每次 lock 后重读），所以**不阻断实现**，只影响能否省掉重读 |
| `kIOSurfaceCacheMode` 落到哪个 ivar | `parse_properties` 对标志字无访问，该键的消费点未定位 | 本项目一律不设该键，用默认值。不阻断 |
| `s_get_limits` 的 40 字节布局 | 未取 | 不用它。不阻断 |
| `IOSurfaceLockResult` 头部 8 个未命名字段（`+0x00/+0x08/+0x10/+0x18/+0x5C/+0x64/+0x68/+0x6C/+0x78`）的语义名 | 需用户态消费点 | 不解析该结构。不阻断（这正是结论 2 的价值） |
| `IOSurfaceLock` 的 flags 在跨进程写者在场时的精确可见性序列 | `50` 分册 U-04，标 Gate 2 | **阻断跨进程写路径的验收**，不阻断同进程实现。见 §6.4 |

---

## 2. 三种导入模式与两轴

### 2.1 两轴到底是什么

`40-RUNTIME-VULKAN.md` 第 4 节与 `50-IPC-HELPER.md` D103 都提到「两轴 import mode」，但只有 D103 给了轴定义。核实结果如下。

**先说核实的结论，因为它和一个自然的猜想不同。** 一个常见的猜想是两轴 =「内存是否可直接映射给 Vulkan」×「布局是否 Vulkan 可接受」。**这两件事不是轴，是轴的判定依据。** 真正的两轴是**存储位置**，分别在两个不同的 Vulkan 对象上：

| 轴 | 名称 | 取值 | 这个轴在问什么 | 判定依据 |
|---|---|---|---|---|
| **轴 1** | host-buffer 存储 | `ImportedHostPages` / `CopiedHostPages` | **`VkBuffer` 背后的 `VkDeviceMemory` 是不是 surface 自己的那些页** | 内存**可映射性**：基址对齐、页粒度、保护位、是否连续 |
| **轴 2** | texture 存储 | `InPlaceImage` / `ShadowedTexture` | **着色器采样/写入的那个 `VkImage` 是不是就落在轴 1 的那块内存上** | 布局**可接受性**：`rowPitch` 能否匹配、format 有无直接候选、tiling 是否 linear 可用 |

两轴的取值判据（`KNOWN`，来源 `50` D103 的判定表 + 上游 `WorkCounts` 字段名）：

```text
轴 1 = ImportedHostPages   ⟺ WorkCounts.host_pointer_imports_made 增加，且本次创建期间无 CopiedHostPages 通告
轴 1 = CopiedHostPages     ⟺ 收到 Degradation::CopiedHostPages，或 copied counter 增加
轴 2 = InPlaceImage        ⟺ 本次创建期间无 texture shadow/copy 类 degradation
轴 2 = ShadowedTexture     ⟺ 上游采用 shadow image，并在 completion 时 copy / merge back
```

**为什么必须是两轴而不是一轴。** 因为两轴可以独立取值，而单轴分类会把两种代价截然不同的情况合并：

- 轴 1 直接、轴 2 影子：**页没拷，但每帧有一次 image↔buffer 的转换**。代价与分辨率成正比，但不碰客户端的页。
- 轴 1 拷贝、轴 2 原地：**页拷了一份，image 落在副本上原地成立**。代价是每次内容变化一次全量拷入，而且**客户端的后续写不再可见**，必须靠 `didModifyRange:` / `IOSurfaceUnlock` 触发重拷。

这两者在单轴分类下都会被叫做「不是直接路径」，但一个是算力问题、一个是**正确性合同问题**。D103 的原话是「只有 `ImportedHostPages + InPlaceImage` 才能称为直接路径」，本文接受并细化成下表。

### 2.2 四个组合 = 三种模式 + 一个最坏格

| 轴 1 | 轴 2 | 模式名 | 每帧代价（W×H，Bpp = 每像素字节） | 客户端写是否自动可见 |
|---|---|---|---|---|
| `ImportedHostPages` | `InPlaceImage` | **in-place** | 0 | **是** |
| `ImportedHostPages` | `ShadowedTexture` | **shadow** | 读 W·H·Bpp + 写 W·H·Bpp'（转换 pass） | 是（但需 seed 变化触发重转换） |
| `CopiedHostPages` | `InPlaceImage` | **copy** | 拷 W·H·Bpp（内容变化时） | **否**，需显式触发 |
| `CopiedHostPages` | `ShadowedTexture` | **copy + shadow（最坏格）** | 拷 + 转换，两笔都付 | 否 |

> **R41-5**：**最坏格必须被当作缺陷而不是降级上报。** 它意味着两个独立的判定同时失败，而这两个判定的输入（对齐、行距）在**我们自己创建的 surface** 上是完全可控的。出现在我们创建的 surface 上 = 实现缺陷；出现在导入的 surface 上 = 记录来源进程与几何，进 `60-CAPABILITY-MATRIX.md` 的已知损失。

### 2.3 完整决策树

`INFERRED`（决策逻辑是实现选择；每个判定项的输入标注在右侧）。

```text
import_surface(surface, plane, desc) -> (Backing, ImportMode)

[0] 几何重测与校验 ...................................... D100 / D101，§3.6
    g = measure(surface, plane)                 必做，不信任何 snapshot
    if !check_geometry(g, desc) -> Reject(InvalidGeometry)
    if g.plane_count > 20       -> Reject(TooManyPlanes)            R41-2

[1] 格式判定 ............................................ §3.4
    mtl = ostype_to_mtl(g.pixel_format)         IOSurface OSType -> MTLPixelFormat
    if mtl is None              -> Reject(UnknownOSType)
    if desc.pixel_format != mtl && !IOSurfaceAllowsPixelSizeCasting(surface)
                                -> Reject(FormatMismatch)           §3.1.4
    cand = vk_format(mtl, usages, profile)      上游 metal2vulkan::metal::format
    if cand is None             -> Reject(Unsupported(Format))      40 §8.2.14

[2] 轴 1 判定：页能不能导入 ............................. §3.1
    base = IOSurfaceGetBaseAddressOfPlane(surface, plane)
    a1 = base % minImportedHostPointerAlignment                     Lavapipe 实测值，S-004
    a2 = g.alloc_size % minImportedHostPointerAlignment
    if a1 != 0 -> axis1 = CopiedHostPages ; notice(D102 的拒绝改为记录)
    else:
        try HostMemory::with_import_gate(...)   上游基元，40 §4.1
        if gate 拒绝 -> axis1 = CopiedHostPages
        else         -> axis1 = ImportedHostPages

[3] 轴 2 判定：image 能不能原地 ......................... §3.2 / §3.3
    if cand.bytes_per_texel * g.width > g.bytes_per_row -> 不可能，已被 [0] 挡掉
    if cand.emulation 需要多 plane 合并（YCbCr / RGB10A8_2P_XR10）
                                -> axis2 = ShadowedTexture          §3.5.3，算术强制
    else if !lavapipe_linear_ok(cand.vk_format, usages)             §3.3
                                -> axis2 = ShadowedTexture
    else if vk_row_pitch(cand.vk_format, g.width, usages) != g.bytes_per_row
                                -> axis2 = ShadowedTexture          §3.2.1
    else                        -> axis2 = InPlaceImage

[4] 组装
    mode = (axis1, axis2)
    if mode == (Copied, Shadowed) -> report_defect_or_known_loss()  R41-5
    backing = build(surface, plane, g, cand, mode)
    report_import_mode(surface_id, axis1, axis2, reasons)           D103，§2.4
    return (backing, mode)
```

**三条实现约束：**

> **R41-6**：**轴 1 的判定不得靠「试了再看全局计数器」。** D103 要求对 surface backing 的创建使用**专用串行段**，并在 `DeviceOptions::messages` 的 sink 里捕获本次创建期间的每一条 `CopiedHostPages` 通告。并发创建时从全局累计值反推归属是错的，`50` 分册的 T-16 就是专门测这件事（并发 import 8 个 surface、4 个故意不对齐，要求各自报出正确取值且不互相污染）。

> **R41-7**：**D102 的处置是记录，不是拒绝。** `50` 分册 D102 原文是「helper 必须拒绝 base address 不满足 `minImportedHostPointerAlignment` 的 surface」，但紧接着自己更正为「处置不是失败，而是记录两轴 import mode 并发 degradation」。本文采后者：对**导入的** surface 永不因对齐而拒绝（否则 WindowServer 的一次不对齐分配就等于黑屏），对**我们创建的** surface 则在创建期就保证对齐（§3.1.2），一旦不对齐视为实现缺陷。

> **R41-8**：**`minImportedHostPointerAlignment` 必须在启动自检里实测一次并缓存，不得每次导入都查。** 它是 `VkPhysicalDeviceExternalMemoryHostPropertiesEXT` 的字段，设备生命周期内恒定。

### 2.4 degradation 上报与归因

本模块产生的通告必须按 `40-RUNTIME-VULKAN.md` §7.1 的规则消费：只用 `Degradation::code()`（稳定串 `metal2vulkan-degrade-<kind>`）与 `category()`，**禁止解析通告文本**。

| 上游 kind | 本模块的含义 | category | 上报粒度 |
|---|---|---|---|
| `copied-host-pages` | 轴 1 退化为拷贝 | `Performance` | 每 surface 一次（创建时） |
| `shadowed-texture` | 轴 2 退化为影子 | `Performance` | 每 surface 一次 |
| `shared-in-system-memory` | 共享存储落在系统内存 | `Performance` | 每 surface 一次 |
| `device-color-conversion` | `colorSpaceConversionMatrix` 非 0（`22` §4.1 的 B 档触发点） | `Precision` | 每 surface 一次 |
| `decoded-texel-precision` | XR / packed 格式在 shader 内编解码的精度记录 | `Precision` | 每格式一次 |

本模块**自己**还要产出三个不在上游枚举里的事实，走本项目的结构化日志而不是伪装成上游 kind：

```text
m2vu-surface-import   { surface_id, generation, axis1, axis2, reasons[], geometry, ostype, mtl_format, vk_format, emulation }
m2vu-surface-rebind   { surface_id, generation, old_base, new_base, cause }     R41-3
m2vu-surface-reject   { surface_id, reason, geometry }                          §2.3 的每个 Reject
```

`m2vu-surface-import` 的 `reasons[]` 必须给出**判定的那一条**，不是「不满足条件」这种空话。可取值固定为：
`base-misaligned`、`alloc-size-misaligned`、`import-gate-refused`、`row-pitch-mismatch`、`format-needs-merge`、`linear-tiling-unsupported`、`usage-unsupported-linear`。

### 2.5 Rust 接口（可直接照抄）

```rust
// ============ crates/m2vu-iosurface/src/import.rs ============

use core_foundation::base::TCFType;
use metal2vulkan_runtime::{
    Buffer, Degradation, Device, HostMemory, KeepAlive, Texture, TextureDescriptor,
};

/// 轴 1：`VkBuffer` 背后的内存从哪来。
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum HostBufferAxis {
    /// surface 自己的页被 `VK_EXT_external_memory_host` 导入。
    ImportedHostPages,
    /// 页被拷进设备自有内存；客户端的后续写不再自动可见。
    CopiedHostPages,
}

/// 轴 2：着色器触碰的 `VkImage` 落在哪。
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum TextureAxis {
    /// image 直接坐在轴 1 的内存上。
    InPlaceImage,
    /// 另开一张 image，按 seed 变化同步。
    ShadowedTexture,
}

/// 两轴的组合。`Display` 输出 `in-place` / `shadow` / `copy` / `copy+shadow`。
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub struct ImportMode {
    pub host_buffer: HostBufferAxis,
    pub texture: TextureAxis,
}

impl ImportMode {
    /// D103：只有这一个组合是直接路径。
    pub fn is_direct(self) -> bool {
        self.host_buffer == HostBufferAxis::ImportedHostPages
            && self.texture == TextureAxis::InPlaceImage
    }
    /// R41-5：双重代价的最坏格，必须当缺陷查。
    pub fn is_worst_cell(self) -> bool {
        self.host_buffer == HostBufferAxis::CopiedHostPages
            && self.texture == TextureAxis::ShadowedTexture
    }
}

/// 本次判定落到该取值的**那一条**原因。不是「不满足条件」。
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

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub struct PlaneGeometry {
    pub index: usize,
    pub width: usize,
    pub height: usize,
    pub bytes_per_element: usize,
    pub bytes_per_row: usize,
    pub element_width: usize,
    pub element_height: usize,
    /// `IOSurfaceGetBaseAddressOfPlane` 的返回值。**每次 lock 后重读**（R41-3）。
    pub base: *mut u8,
    /// 相对 surface 基址的偏移。**与 `base` 分开，不得互推**（R41-1）。
    pub offset: usize,
    pub size: usize,
}

#[derive(Clone, Debug)]
pub struct SurfaceGeometry {
    pub surface_id: u32,
    pub pixel_format: u32, // OSType
    pub width: usize,
    pub height: usize,
    pub bytes_per_element: usize,
    pub bytes_per_row: usize,
    pub alloc_size: usize,
    pub buffer_offset: usize,
    pub plane_count: usize,
    pub seed: u32,
    pub planes: Vec<PlaneGeometry>, // 长度 == max(plane_count, 1)
}

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum ImportRejection {
    InvalidGeometry(GeometryFault),
    TooManyPlanes { count: usize },
    UnknownOsType { ostype: u32 },
    FormatMismatch { declared: u32, actual: u32 },
    UnsupportedFormat,
    PlaneIndexOutOfRange { index: usize, count: usize },
}

/// 本模块对外的唯一入口。helper 与同进程版本共用同一个 trait。
pub trait SurfaceBridge {
    /// D100：拿到自己的 `IOSurfaceRef` 之后**必须**重新读全部几何。
    /// `declared` 只用于交叉检查，不作为事实。
    fn measure(
        &self,
        surface: IoSurfaceRef,
        declared: Option<&SurfaceGeometry>,
    ) -> Result<SurfaceGeometry, ImportRejection>;

    /// 在 surface 的某个 plane 上建纹理。内部完成 §2.3 的决策树。
    /// R41-6：实现必须在专用串行段内执行，并捕获本次创建期间的 degradation。
    fn import_plane_as_texture(
        &self,
        surface: IoSurfaceRef,
        plane: usize,
        desc: &TextureDescriptor,
    ) -> Result<SurfaceTexture, ImportRejection>;

    /// 在整张 surface 的分配上建 buffer（`MTLBufferDescriptor.iosurface` 路径，`22` §4.2）。
    fn import_as_buffer(
        &self,
        surface: IoSurfaceRef,
        options: metal2vulkan_runtime::ResourceOptions,
    ) -> Result<SurfaceBuffer, ImportRejection>;

    /// R41-3：lock 后 base 变了就重绑，不得继续用旧指针。
    fn rebind_if_moved(&self, backing: &mut SurfaceBacking) -> Result<bool, RebindError>;
}

pub struct SurfaceTexture {
    pub texture: Texture,
    pub mode: ImportMode,
    pub reasons: Vec<ImportReason>,
    pub backing: SurfaceBacking,
}

pub struct SurfaceBuffer {
    pub buffer: Buffer,
    pub mode: ImportMode,
    pub reasons: Vec<ImportReason>,
    pub backing: SurfaceBacking,
}

/// 把「这块内存还活着」和「surface 的 CF 引用」绑在一起的那个载体。
/// 它的 `Drop` 就是 §6.1 的汇合点：`CFRelease` + `IOSurfaceDecrementUseCount`
/// + 调用并释放 `deallocator` block，全部在这里，一次。
pub struct SurfaceBacking {
    host: HostMemory,
    keep: KeepAlive,
    /// 每 plane 一个指针快照，用于 R41-3 的比对。
    bases: Vec<*mut u8>,
    geometry: SurfaceGeometry,
    /// `CFRetain` 过的句柄；`Drop` 时 `CFRelease`。
    surface: RetainedSurface,
    /// `22` R41/R42 的 block。`Some` 时必须恰好调用一次。
    deallocator: Option<DeallocatorBlock>,
}
```

---

## 3. 对齐、布局与格式

### 3.1 三个对齐约束，三个不同的来源

必须分清，因为它们互不替代，而且只有第一个是我们能改的。

| # | 约束 | 来源 | 查法 | 我们能不能控制 |
|---|---|---|---|---|
| 1 | IOSurface 的 `bytesPerRow` / `allocSize` / plane offset 对齐 | IOSurface 自己 | `IOSurfaceGetPropertyAlignment(key)` | **创建时能，导入时不能** |
| 2 | Vulkan 导入 host pointer 的对齐 | 驱动 | `VkPhysicalDeviceExternalMemoryHostPropertiesEXT::minImportedHostPointerAlignment` | 不能 |
| 3 | linear image 的行距 | 驱动 | `vkGetImageSubresourceLayout` 的 `rowPitch`（**不可指定，只能读**） | 不能 |
| 4 | Metal 侧要对外声明的对齐 | 本项目 | `_MTLDevice` 的 `iosurfaceTextureAlignmentBytes` / `iosurfaceReadOnlyTextureAlignmentBytes` / `linearTextureAlignmentBytes`（`20` §5.2 的 limits 表） | **能，而且必须自洽** |

#### 3.1.1 第 4 项是本项目的义务，不是查询

`20-OBJC-DEVICE.md` §5.2 已证整张 limits 表是 `featureProfile` 一个枚举值的纯函数，其中包含 `linearTextureAlignmentBytes`、`iosurfaceTextureAlignmentBytes`、`iosurfaceReadOnlyTextureAlignmentBytes`、`deviceLinearTextureAlignmentBytes` 四项。`KNOWN`

> **R41-9**：这四个 limit 的取值必须满足
> ```text
> iosurfaceTextureAlignmentBytes         >= max(minImportedHostPointerAlignment, page_size)
> iosurfaceReadOnlyTextureAlignmentBytes >= minImportedHostPointerAlignment
> linearTextureAlignmentBytes            >= 第 3 项实测的最坏 rowPitch 粒度
> deviceLinearTextureAlignmentBytes      >= linearTextureAlignmentBytes
> ```
> 并且全部是 2 的幂。理由：客户端**会**照着这些值对齐自己的分配（这是这些 limit 存在的唯一原因）。报小了，客户端按我们说的做却走到 copy 路径；报大了，白浪费内存但正确。因此**报大安全、报小是缺陷**。
> `INFERRED`（取值是实现选择）；右侧三个输入里前两个必须实测（S-004、S-005）。

#### 3.1.2 我们创建的 surface：强制对齐

```text
bpr_min   = width * bytes_per_element                            （checked mul）
bpr_align = IOSurfaceAlignProperty(kIOSurfaceBytesPerRow, bpr_min)
bpr       = round_up(bpr_align, iosurfaceTextureAlignmentBytes)   ← 自己再抬一级
size      = IOSurfaceAlignProperty(kIOSurfaceAllocSize,
                                   bpr * height + plane_offsets…)
```

两级抬升的理由：第一级满足 IOSurface，第二级满足 Vulkan 与我们对外声明的 limit。只做第一级会出现「IOSurface 接受、Vulkan 要拷」的情况，而那正是 R41-7 定义成缺陷的那一格。

#### 3.1.3 导入的 surface：接受并记录

不改，不拒绝（R41-7），只把不满足的那一项写进 `reasons[]` 并按 §2.3 落到相应轴。

#### 3.1.4 pixel-size casting 在本构建上默认开

`KNOWN`（`12` §2.2 的位表第 bit 16 行 + §1.2 第 11 步）。标志字 `surf+0x3D8` 的 bit 16（即 `surf+0x3DA` 的 bit 0x01）由 `[S] IOSurface::init +0x4063` 的 `or byte [rbx+3DAh], 1` **无条件**置 1，`isPixelCastingAllowed` 与 `isPixelSizeCastingAllowed` 都读这一位；唯一的关闭路径是 boot-arg `iosurface_debug` 的 bit1（「禁止 pixel-size casting」，`IOSurfaceRoot::start` 第 11 步解析，默认值 `20` 即 `0b10100`，bit1 为 0）。

对本项目的两条后果：

1. `IOSurfaceAllowsPixelSizeCasting` 预期返回真。因此 §2.3 的 `[1]` 步在 `desc.pixel_format != ostype_to_mtl(...)` 时**通常会放行**。这是必须的：客户端合法地用 `BGRA8Unorm` descriptor 在一张 `'BGRA'` surface 上建纹理，也合法地用 `R32Uint` view 去读同一张 surface。
2. 放行不等于不校验。**casting 允许改变「怎么解释这些位」，不允许改变「有多少位」。** 校验式：
   ```text
   bytes_per_element(desc.pixel_format) == g.plane.bytes_per_element        必须相等
   block_size(desc.pixel_format)        == (g.plane.element_width, element_height)
   ```
   不相等 → `Reject(FormatMismatch)`，不管 casting 是否允许。`INFERRED`（Metal 的 pixel-size casting 语义就是等尺寸重解释；不等尺寸的情形本项目不支持，记为 S-006）

### 3.2 `bytesPerRow` 与 `VkSubresourceLayout::rowPitch`

#### 3.2.1 不匹配时怎么办

这是轴 2 的核心判定。Vulkan 的事实（`KNOWN`，公开规范）：

- 创建 `VkImage` 时**不能指定** `rowPitch`。
- 建好之后 `vkGetImageSubresourceLayout` 给出驱动选的 `rowPitch`（仅对 `VK_IMAGE_TILING_LINEAR` 有定义）。
- 因此「IOSurface 的 `bytesPerRow` 恰好等于驱动的 `rowPitch`」是一个**只能检查、不能要求**的条件。

四条处置，按优先级：

| 优先级 | 做法 | 适用 | 代价 |
|---|---|---|---|
| 1 | 相等 → 直接把 image 绑到导入的内存上 | 常见（我们创建的 surface 按 §3.1.2 对齐过） | 0 |
| 2 | 不相等 → **走 buffer 路径**：把页导入成 `VkBuffer`，再用上游 `Buffer::new_texture_with_iosurface_plane`（`40` §3.2「没有单一调用的项」里 `new_texture_on_surface` 的组成之一）在 buffer 上建纹理并显式给 `bytes_per_row` | 行距可被 buffer 路径吸收时 | 0 或一次布局转换，由上游决定 |
| 3 | buffer 路径也不接受 → 轴 2 = `ShadowedTexture`，影子 image 自选 pitch，用 `VK_EXT_host_image_copy`（Lavapipe `hostImageCopy = true`，`60` §2.2）在两者之间搬 | 兜底 | 每次 seed 变化一次 W·H·Bpp 的搬运 |
| 4 | — | — | **不做**：不得为了凑 pitch 去改客户端 surface 的几何，也不得谎报 `bytesPerRow` |

> **R41-10**：优先级 2 是主路径，不是优化。`VkBuffer` 没有 pitch 概念，所以「页导入」这一轴在绝大多数情况下都能成立；pitch 只影响轴 2。把两轴分开的实践意义就在这里：**行距不匹配只应该让轴 2 退化，不应该牵连轴 1。** 实现里如果写成「pitch 不匹配就整个走 copy」，那是把两轴退回一轴，`50` 分册 D103 明确说这是不够的。

#### 3.2.2 为什么逐 plane 取基址而不是算

Apple 的 `-[MTLIOAccelTexture initWithDevice:descriptor:iosurface:plane:field:args:argsSize:]` 用的是 `IOSurfaceGetBaseAddress`（surface 基址）而不是 `…OfPlane`（`KNOWN`，`20` §8.5）。本项目**不照抄**，理由：

1. `12` §2.3 已证内核侧 plane 的 `base` 与 `offset` 是**两个独立字段**（`setPlaneBase 0x134CE` 与 `setPlaneOffset 0x134EC`），所以 `surface_base + plane_offset` 不一定等于 plane 的实际地址。
2. Apple 能这么写，是因为它随后把 args 交给内核的 `IOAccelResourceCreate`，由内核侧用自己的 ivar 算；本项目没有那条内核路径，算错就是野指针。
3. 代价只是多几个函数调用。

> **R41-11**：plane 地址一律 `IOSurfaceGetBaseAddressOfPlane(s, i)`。`plane_offset` 只用于 D101 的边界校验，**不用于定址**。

### 3.3 Lavapipe 能接受的 linear image 条件

`KNOWN`（Lavapipe 的能力位来自 `60-CAPABILITY-MATRIX.md` §2.2）+ `BLOCKED`（具体数值未实测）。

成立需要同时满足五条：

| # | 条件 | 来源 | 状态 |
|---|---|---|---|
| 1 | `VK_EXT_external_memory_host` 可用 | `60` §2.2：Lavapipe `= true` | `KNOWN` |
| 2 | 导入的 host pointer 与长度都是 `minImportedHostPointerAlignment` 的倍数 | 驱动属性 | 值 `BLOCKED`（S-004） |
| 3 | `VkPhysicalDeviceExternalMemoryHostPropertiesEXT` 报出的 memory type 与 image 的 `memoryTypeBits` 有交集 | `vkGetMemoryHostPointerPropertiesEXT` | `BLOCKED`（S-004 同一次探测） |
| 4 | `vkGetPhysicalDeviceFormatProperties(fmt).linearTilingFeatures` 覆盖本次要的全部 usage（采样 / 存储 / color attachment） | 驱动 format 表 | `BLOCKED`（S-005；`40` §8.4 已要求对全部 301 个格式实测，本项目复用那次产物） |
| 5 | 该 format × `VK_IMAGE_TILING_LINEAR` × 该 usage 的 `vkGetPhysicalDeviceImageFormatProperties` 不返回 `ERROR_FORMAT_NOT_SUPPORTED` | 同上 | 同上 |

**第 4 条是最容易漏的那条，而且它对合成路径很关键。** 很多驱动的 `linearTilingFeatures` 覆盖采样但不覆盖 `COLOR_ATTACHMENT_BIT`。WindowServer 的合成目标是 attachment，不是只被采样的纹理（`60` §5.1：WindowServer 向 1920×1080 的 `RGBA16Float` IOSurface plane 写入）。所以：

> **R41-12**：启动自检必须对本项目实际会用到的格式集合，分别查 `linearTilingFeatures` 的 `SAMPLED_IMAGE_BIT`、`STORAGE_IMAGE_BIT`、`COLOR_ATTACHMENT_BIT`、`COLOR_ATTACHMENT_BLEND_BIT` 四位并落盘。缺 attachment 位 → 那个格式的 surface 在作为 render target 时**必然** `ShadowedTexture`，这要事先知道，不能等到第一帧才发现。

格式集合的最小闭包（来自 `60` §5.1 的 WindowServer 实测事实，`KNOWN`）：
`B8G8R8A8_UNORM`、`B8G8R8A8_SRGB`、`R16G16B16A16_SFLOAT`、`R32G32_UINT`（`RGB10A8_2P_XR10` 的落点）、`R8_UNORM`、`R8G8_UNORM`。

**macOS 上没有 dma-buf。** `40` §2.3 已记明 `DmaBufChunk` / `DmaBufRequest` / `DmaBufSource` 是 `#[cfg(unix)]` 但 macOS 上无 dma-buf，必须走指针导入。因此上游 `HostMemory` 的四条退路里，本项目只有三条可用：`with_import_gate`（指针导入 + 门控）、`with_dirty_pages`（脏页日志驱动增量拷入）、`with_runs`（分段）。`with_dma_buf` 永不使用。`KNOWN`

### 3.4 OSType → MTLPixelFormat → VkFormat 三段映射

#### 3.4.1 映射的归属

第二段与第三段**不是本册的工作**：

- `MTLPixelFormat → VkFormat` 全量表在 `40-RUNTIME-VULKAN.md` §8.2，且该分册 §8.4 明令**禁止手写维护**，必须由 `Device::pixel_format_capabilities` + `metal2vulkan::metal::format::vk_format` 在设备上生成。
- 本册只负责**第一段**：`OSType → MTLPixelFormat`，并且同样必须是生成物。

#### 3.4.2 第一段的权威来源与生成方式

`OSType` 的语义不在 Metal 里，在 CoreVideo / IOSurface 的格式描述表里。运行期可查，这是唯一可靠的办法：

```c
/* 对每个候选 OSType 取出它的属性字典，再据字典推 MTLPixelFormat。*/
CFDictionaryRef d = CVPixelFormatDescriptionCreateWithPixelFormatType(NULL, ostype);
/* 判别用的键（全部 KNOWN，公开 ABI）：
 *   kCVPixelFormatBitsPerComponent        每分量位数
 *   kCVPixelFormatContainsRGB / ContainsYCbCr / ContainsAlpha / ContainsGrayscale
 *   kCVPixelFormatComponentRange          FullRange / VideoRange / WideRange
 *   kCVPixelFormatPlanes                  数组，每项含 BitsPerBlock / BlockWidth /
 *                                         HorizontalSubsampling / VerticalSubsampling / BlackBlock
 */
```

> **R41-13**：`OSType → MTLPixelFormat` 表是**生成物**，由启动自检对本项目的候选集逐个调 `CVPixelFormatDescriptionCreateWithPixelFormatType` 得到，与下表 diff，差异进 `90-EVIDENCE-INDEX.md`。下表是**预期值**，实测优先。这与 `40` §8.4 对第三段的要求是同一条纪律。

#### 3.4.3 本项目的候选集（预期值表）

| `OSType` | 十六进制 | `MTLPixelFormat`（raw） | `VkFormat`（第一候选，`40` §8.2） | 标签 | 用在哪 |
|---|---|---|---|---|---|
| `'BGRA'` | `0x42475241` | `BGRA8Unorm`（80） | `B8G8R8A8_UNORM` | `KNOWN`（`kCVPixelFormatType_32BGRA` 公开 ABI） | **合成主格式**；APV 的硬件光标也只接受它 |
| `'RGBA'` | `0x52474241` | `RGBA8Unorm`（70） | `R8G8B8A8_UNORM` | `KNOWN`（`kCVPixelFormatType_32RGBA`） | app 路径 |
| `'ABGR'` | `0x41424752` | `RGBA8Unorm` + swizzle | `R8G8B8A8_UNORM` + component mapping | `KNOWN`（`kCVPixelFormatType_32ABGR`） | 少见 |
| `32`（数值，非 fourcc） | `0x00000020` | `ARGB8Unorm`（84） | `R8G8B8A8_UNORM` + swizzle | `KNOWN`（`kCVPixelFormatType_32ARGB` 的值就是十进制 32） | 少见。**注意它不是四字符码**，解析器必须允许非可打印值 |
| `'RGhA'` | `0x52476841` | `RGBA16Float`（115） | `R16G16B16A16_SFLOAT` | `KNOWN`（`kCVPixelFormatType_64RGBAHalf`） | **WindowServer 的 scanout 纹理格式**（`60` §5.1） |
| `'b3a8'` | `0x62336138` | **`RGB10A8_2P_XR10`（550）** | `R32G32_UINT` | `INFERRED`（强证据，§3.5） | **WindowServer 登录路径的 framebuffer-fetch attachment 格式**（`60` §5.1） |
| `'w30r'` | `0x77333072` | `BGR10A2Unorm`（94）或 `BGR10_XR`（554） | `A2R10G10B10_UNORM_PACK32` / `R32_UINT` | `BLOCKED`（`kCVPixelFormatType_30RGBLEPackedWideGamut` 键名公开，但落到哪个 Metal 格式需实测区分） | 宽色域路径，S-007 |
| `'420v'` / `'420f'` | `0x34323076` / `0x34323066` | `YCBCR8_420_2P`（500）族 | 见 `40` §8.2.12 | `KNOWN`（公开 ABI） | VideoToolbox 路径 |
| `'L008'` | `0x4C303038` | `R8Unorm`（10） | `R8_UNORM` | `KNOWN`（`kCVPixelFormatType_OneComponent8`） | 单通道、mask |
| `'2C08'` | `0x32433038` | `RG8Unorm`（30） | `R8G8_UNORM` | `KNOWN`（`kCVPixelFormatType_TwoComponent8`） | |

**不在候选集的 `OSType` 一律 `Reject(UnknownOSType)`，不猜。** 这与 `40` §8.2.14 的处置一致（上游无候选的格式第一版全部报 false / 返回确定错误）。

### 3.5 `RGB10A8_2P_XR10` 与 `'b3a8'`

这是 `60-CAPABILITY-MATRIX.md` §5.1 点名的格式，也是本册被点名必须查清的一项。**查清了。**

#### 3.5.1 它是什么

`INFERRED`（强证据）。`'b3a8'` 的 `CVPixelFormatDescription` 字典（来源：[gregcotten 的公开 CVPixelFormat 描述转储](https://gist.github.com/gregcotten/16cb3902ae21b1448d71c02f1d505750)，一份在真实 macOS 上对全部公开与私有格式逐个调 `CVPixelFormatDescriptionCreateWithPixelFormatType` 的结果。内容已改写以符合许可限制）：

| 字典键 | 值 | 对 `RGB10A8_2P_XR10` 的判别意义 |
|---|---|---|
| `PixelFormat` | `1647534392` = `0x62336138` = `'b3a8'` | 数值自洽（`0x62`=`b`、`0x33`=`3`、`0x61`=`a`、`0x38`=`8`） |
| `BitsPerComponent` | `10` | 对应名字里的 `RGB10` 与 `XR10` |
| `ComponentRange` | `WideRange` | 对应 `XR`（extended range） |
| `ContainsRGB` | `1` | 对应 `RGB` |
| `ContainsYCbCr` | `0` | **排除 YCbCr 族** |
| `ContainsAlpha` | `1` | 对应 `A8` |
| `ContainsGrayscale` | `0` | 排除单通道族 |
| `Planes` | **两项** | 对应 `2P` |
| `Planes[0].BitsPerBlock` | `32`，无 subsampling | plane 0 每像素 4 字节：10:10:10 打包进 32 位 |
| `Planes[1].BitsPerBlock` | `8`，`BlackBlock = 0xFF`，无 subsampling | plane 1 每像素 1 字节 alpha，**清零块是 0xFF 即不透明** |

九项判别属性逐条吻合，且名字的四段（`RGB10` / `A8` / `2P` / `XR10`）在字典里各有对应物。该转储同一位置相邻的 `'pw44'` 是 `ContainsYCbCr = 1` 的 10 位宽色域 4:4:4 两 plane YCbCr，作为对照组进一步排除了混淆。

**仍然是 `INFERRED` 而不是 `KNOWN`，因为**：证据来源是第三方运行期转储，不是 Apple 头文件，也不是本项目的 25G325 样本（`00-OVERVIEW.md` §7 规则 3）。关闭方法见 S-003，可以用 `91` 分册的 CI 通道一次性关掉。

#### 3.5.2 对 `60-CAPABILITY-MATRIX.md` 的更正建议

`60` §3 的格式表有一行写作：

> 两 plane YCbCr 纹理（`YCBCR8_420_2P` 系）｜ **SYS**（RenderBox 在 26.6.2 guest 上对 `'b3a8'` surface 建过）

**`'b3a8'` 不是 YCbCr。** 它 `ContainsYCbCr = 0`、`ContainsRGB = 1`。上游的 `crates/metal2vulkan-runtime/src/texture/surface_two_planes.rs` 同时承载 YCbCr 与 RGB 两个两 plane 族（`40` §8.2.12 的 `two_plane_ycbcr!()` 覆盖 `RGB{8,10}_{420,422,444}_2P` 也说明了这一点），分册在引用该文件的文档注释时把 `'b3a8'` 归到了 YCbCr 一侧。

正确的说法是：**RenderBox 在 26.6.2 guest 上对一张两 plane 的 10 位宽色域 RGB + A8 surface 建过纹理**，而这正是登录路径那个 `RGB10A8_2P_XR10` attachment 的 surface 侧形态。这把 `60` §5.1 里原本看起来不相干的两条证据（第 1 条「登录路径做 framebuffer fetch，attachment 格式是 `RGB10A8_2P_XR10`」与最后一条「RenderBox 对 `'b3a8'` surface 建两 plane 纹理」）**合成了同一条事实的两端**，并把它的优先级从「YCbCr 适配」提到「登录屏首帧的必要条件」。`INFERRED`

#### 3.5.3 两 plane 怎么表达，以及为什么它被算术强制成 shadow

创建侧（`INFERRED`，按 §1.3.2 的键）：

```text
kIOSurfacePixelFormat       = 0x62336138            /* 'b3a8' */
kIOSurfaceWidth             = W
kIOSurfaceHeight            = H
kIOSurfaceBytesPerElement   = 4                     /* 以 plane 0 为准 */
kIOSurfacePlaneInfo = [
  { PlaneWidth=W, PlaneHeight=H, PlaneBytesPerElement=4,
    PlaneBytesPerRow = align(4*W),  PlaneOffset = 0,
    PlaneSize = PlaneBytesPerRow*H,
    PlaneElementWidth=1, PlaneElementHeight=1 },          /* RGB10 XR packed, 32 bpp */
  { PlaneWidth=W, PlaneHeight=H, PlaneBytesPerElement=1,
    PlaneBytesPerRow = align(1*W),  PlaneOffset = <读出来的，不要算>,
    PlaneSize = PlaneBytesPerRow*H,
    PlaneElementWidth=1, PlaneElementHeight=1 },          /* A8 */
]
kIOSurfaceAllocSize         = align(plane1.Offset + plane1.Size)
```

导入侧的关键结论：

```text
上游候选（40 §8.2.4）：RGB10A8_2P_XR10 -> VK_FORMAT_R32G32_UINT      8 字节 / texel
surface 侧实际存储：     plane 0 = 4 字节 / texel， plane 1 = 1 字节 / texel   合计 5
8 != 5，且 8 != 4，且 8 != 1
⇒ 任何单张 VK_IMAGE_TILING_LINEAR 的 R32G32_UINT image，无论绑到 plane 0 的内存、
  plane 1 的内存，还是整张 allocation 上，行距与 texel 跨距都无法与 surface 对上。
⇒ 轴 2 必然是 ShadowedTexture。
```

`INFERRED`（算术推导；两个输入都是 `KNOWN`：上游候选来自 `40` §8.2.4，plane 位宽来自 §3.5.1 的格式描述）。

轴 1 不受影响：整张 allocation 作为一个 host pointer 导入，再在其上开两个 `VkBuffer` 视图（偏移分别是两个 plane 的 offset），仍然可以是 `ImportedHostPages`。所以 `'b3a8'` 的模式是 **shadow**，不是 copy。

落实到实现：

> **R41-14**：`'b3a8'` 的处理路径是固定的，不走 §2.3 的轴 2 判定（判定结果已知）：
> 1. 整张 allocation 导入成一块 `HostMemory`，两个 plane 各开一个 buffer 视图；
> 2. 建一张 `R32G32_UINT` 的 shadow image（`VK_IMAGE_TILING_OPTIMAL` 即可，既然已经是影子，就别再自找 linear 的限制）；
> 3. **作为 attachment 时**：渲染进 shadow，`end_encoding` 后一个 compute/blit pass 把 64 位 texel 拆回 plane 0 的 32 位与 plane 1 的 8 位，再按 §6.4 的时序 unlock；
> 4. **作为 sampled texture 时**：seed 变化时把两 plane 合并进 shadow；
> 5. 两个方向都发 `shadowed-texture` 通告，并在 `m2vu-surface-import` 的 `reasons[]` 里写 `format-needs-merge`。
>
> 代价：1920×1080 时每帧 shadow 是 `1920*1080*8` = 16.6 MB，拆分 pass 读 16.6 MB 写 10.4 MB。**这是登录屏每帧的固定成本**，必须进性能预算。

#### 3.5.4 `_sRGB` 变体

`RGB10A8_2P_XR10_sRGB`（raw 551）在 IOSurface 侧**大概率共用 `'b3a8'`**，差异由 `kIOSurfaceColorSpace` 一类的 attachment 表达，而不是另一个 `OSType`。理由：IOSurface 的 `OSType` 描述位布局，色彩空间是 attachment。`INFERRED`，关闭方法同 S-003。

实现上的处置：`ostype_to_mtl('b3a8')` 返回 **550**；若 descriptor 声明的是 551，按 §3.1.4 的 casting 规则放行（位宽相同），并在 shader 侧按 sRGB 编解码。

### 3.6 几何校验：D100 / D101 的实现

`KNOWN`（规则来自 `50-IPC-HELPER.md` D100/D101）。D101 给的是单 plane BGRA8 的形式，这里推广到任意 plane 数与任意格式，并补上 D101 没写的三条。

```rust
// ============ crates/m2vu-iosurface/src/geometry.rs ============

#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum GeometryFault {
    /// bytes_per_element 与格式要求不符（D101 第 1 条）
    BytesPerElementMismatch { got: usize, want: usize },
    /// bytes_per_row < width * bytes_per_element（D101 第 2 条）
    RowTooShort { bpr: usize, need: usize },
    /// plane 的最后一个像素越出 alloc_size（D101 第 3 条）
    PlaneOverrunsAllocation { end: usize, alloc: usize },
    /// plane_index 越界（D101 第 4 条）
    PlaneIndexOutOfRange { index: usize, count: usize },
    /// 本文补：两个 plane 的字节区间相交
    PlanesOverlap { a: usize, b: usize },
    /// 本文补：width/height 为 0，或超出 DeviceProperties 的 max_texture_2d
    DimensionOutOfRange { w: usize, h: usize },
    /// 本文补：任何 checked 算术溢出
    ArithmeticOverflow,
    /// 本文补：element_width/height 与格式的 block 尺寸不符
    BlockSizeMismatch { got: (usize, usize), want: (usize, usize) },
}

/// D101 的逐步校验。**全部用 checked 算术**，任何溢出都是 fault 而不是 wrap。
pub fn check_geometry(
    g: &SurfaceGeometry,
    plane: usize,
    fmt: metal2vulkan::metal::PixelFormat,
    limits: &Limits,
) -> Result<(), GeometryFault> {
    // D101 第 4 条：plane_index < plane_count，或 plane_count == 0 且 plane_index == 0
    let effective = if g.plane_count == 0 { 1 } else { g.plane_count };
    if plane >= effective {
        return Err(GeometryFault::PlaneIndexOutOfRange { index: plane, count: effective });
    }
    if effective > 20 {
        // R41-2：20 是内核硬上限，拿到更大的值说明我们看到的几何不可信
        return Err(GeometryFault::PlaneIndexOutOfRange { index: plane, count: effective });
    }
    let p = &g.planes[plane];

    if p.width == 0 || p.height == 0
        || p.width > limits.max_texture_2d || p.height > limits.max_texture_2d {
        return Err(GeometryFault::DimensionOutOfRange { w: p.width, h: p.height });
    }

    // D101 第 1 条
    let want_bpe = fmt.bytes_per_block();
    if p.bytes_per_element != want_bpe {
        return Err(GeometryFault::BytesPerElementMismatch { got: p.bytes_per_element, want: want_bpe });
    }
    // 本文补：block 尺寸
    let want_block = fmt.block_extent();
    if (p.element_width, p.element_height) != want_block {
        return Err(GeometryFault::BlockSizeMismatch {
            got: (p.element_width, p.element_height), want: want_block });
    }

    // D101 第 2 条（checked mul）
    let row_need = p.width.checked_mul(p.bytes_per_element).ok_or(GeometryFault::ArithmeticOverflow)?;
    if p.bytes_per_row < row_need {
        return Err(GeometryFault::RowTooShort { bpr: p.bytes_per_row, need: row_need });
    }

    // D101 第 3 条（checked mul + add）
    //   plane_offset + bytes_per_row * (height - 1) + width * bytes_per_element <= alloc_size
    let last_row = p.bytes_per_row
        .checked_mul(p.height.checked_sub(1).ok_or(GeometryFault::ArithmeticOverflow)?)
        .ok_or(GeometryFault::ArithmeticOverflow)?;
    let end = p.offset
        .checked_add(last_row).ok_or(GeometryFault::ArithmeticOverflow)?
        .checked_add(row_need).ok_or(GeometryFault::ArithmeticOverflow)?;
    if end > g.alloc_size {
        return Err(GeometryFault::PlaneOverrunsAllocation { end, alloc: g.alloc_size });
    }
    Ok(())
}

/// 本文补的第五条：多 plane 时两两不相交。
/// 理由：D101 只保证每个 plane 各自落在 allocation 内，不保证互不覆盖。
/// 一个把 plane 1 的 offset 设成 0 的恶意 surface 能让 alpha 的写覆盖颜色。
pub fn check_planes_disjoint(g: &SurfaceGeometry) -> Result<(), GeometryFault> {
    let mut iv: Vec<(usize, usize, usize)> = g.planes.iter()
        .map(|p| (p.offset, p.offset + p.bytes_per_row * p.height, p.index))
        .collect();
    iv.sort_unstable();
    for w in iv.windows(2) {
        if w[0].1 > w[1].0 {
            return Err(GeometryFault::PlanesOverlap { a: w[0].2, b: w[1].2 });
        }
    }
    Ok(())
}
```

> **R41-15**：`check_geometry` 与 `check_planes_disjoint` 在**每次导入**时跑，并在**每次 lock 后**对几何部分重跑一次交叉检查（base address 是必须重读的，见 R41-3；其余字段按 §1.4 的「几何不可变」只做比对，不一致即 `Reject` 并断开该 surface）。

---

## 4. Mach VM 与跨进程

### 4.1 `IOSurfaceCreateMachPort` / `IOSurfaceLookupFromMachPort` 的权限模型

#### 4.1.1 内核侧的机制

`KNOWN`（`12-KERNEL-IOSURFACE.md` §1.4 的 selector 表 + §2.1 的类职责表）。

| 用户态 API | selector | 入/出 | 内核侧载体 |
|---|---|---|---|
| `IOSurfaceCreateMachPort` | **35** `s_create_port_from_surface` | 2 scalar 入、1 scalar 出 | `IOSurfaceSendRight` / `IOSurfaceWiredSendRight`（`[S] init 0x23846` / `0x23C10`） |
| `IOSurfaceLookupFromMachPort` | **34** `s_lookup_surface_from_port` | 1 scalar 入、**3176 字节出** | 同上 |

两条都在 restricted 表里**放行**（`12` §1.4 的最后一列），即带 `com.apple.private.gpu-restricted` / `com.apple.developer.gpu-restricted` 的降权进程也能用。本项目的 helper 不会签这两个 entitlement，走完整的 63 条表。`KNOWN`

关键事实：**selector 34 的输出是 3176 字节，与 `s_create_surface`、`s_lock_surface`、`s_lookup_surface` 完全一样**。也就是说「从 port 取回 surface」和「创建 surface」在内核侧返回同一种东西，`IOSurfaceClient::getLockResult` 是共同出口。这是 §1.1 理由 2 的另一个体现：port 路径没有独立的 ABI 要解。

#### 4.1.2 权限模型

Mach port 的语义决定了权限模型，而不是 IOSurface（`KNOWN`，Mach 公开语义 + `12` §3.4 的 `find_surface`）：

| 性质 | 结论 |
|---|---|
| 权限的载体 | **send right 本身**。持有 right = 有权取回 surface |
| 传递方式 | Mach IPC 的 port descriptor（XPC 里是 `xpc_mach_send_create`），不能序列化成字节 |
| 不可伪造 | right 是内核对象，用户态无法凭一个整数构造它 |
| 可复制 | 持有者可以把 right 再传给第三方。**一旦传出就控制不住** |
| 与 `find_surface` 的关系 | port 路径**绕开** `find_surface` 的三条放行条件。即不需要 surface 是「全局可见」的，也不需要调用方是拥有者 task |
| 回收 | `mach_port_deallocate` 释放 right；surface 的生命由 §6.1 的三层计数决定，不由 right 决定 |

> **R41-16**：**surface 的授权一律是 Mach right，ID 只作诊断。** 这就是 `50-IPC-HELPER.md` D99 的原话（`IMPORT_SURFACE` 的 `surface` 必须是随消息传递的 capability / Mach right；单独的全局 IOSurface ID 不得作为授权依据）。本册把它落到两条具体要求：
> 1. wire 消息里 surface 字段的类型是 port descriptor，`u32` 的 ID 字段**另起一个名字**（`surface_id_for_diagnostics`），让类型系统阻止误用；
> 2. helper 侧 `IOSurfaceLookupFromMachPort` 成功后**立刻** `IOSurfaceGetID` 并与消息里的诊断 ID 比对，不一致**不拒绝**（right 才是权威），但记一条 `m2vu-surface-id-mismatch` 告警。ID 不符说明发送方的记账乱了。

#### 4.1.3 U-03 不通过时的备选

`50` 分册 U-03 是「IOSurface 的 Mach right 跨进程传递的具体 API 与 entitlement」未实测（Gate H-3）。若 `IOSurfaceCreateMachPort` 在 WindowServer 沙箱下不可用，备选顺序：

1. `IOSurfaceCreateXPCObject` / `IOSurfaceLookupFromXPCObject`。同一机制的 XPC 包装，沙箱 profile 对它的处置可能不同。成本：几行代码。
2. 由 kext 转交。本项目的 accelerator user client 可以作为中介：WindowServer 把 surface ID 交给 kext，kext 用 `IOSurfaceRoot::lookupSurface(id, owner_task)`（`[S] +0x16612`，`12` §3.4）解析，再把 `IOSurface*` 交给 helper 侧的 user client。**代价**：`12` §7 已登记「`IOSurfaceRoot::lookupSurface` 是否作为 KPI 导出」未关闭（需 `IOSurface.exports`，仓库内只有 `IOPCIFamily.exports`），所以这条路先要解决一个「要上游材料」的阻断。
3. 回到同进程。`50` 分册 Gate H-3 的处置原文就是「不通过 → 显示路径不可切分」。

### 4.2 U-01：验证方法

`50` 分册 U-01 是本项目**整个切分方案的单点风险**：Mach memory entry 的跨进程**可写**映射在 WindowServer 沙箱下是否可行（D8、Gate H-2）。D115 已经给了探针形状（root daemon + 普通 app，传一个可写映射过去并双向写，小时级）。本节补三件 D115 没写的：探针要测的**五个格**、判定标准、以及**本册为什么必须独立于它**。

#### 4.2.1 探针要测的五个格

单测「能不能映射」不够。沙箱的拒绝可能发生在五个不同位置，处置各不相同：

| # | 格 | 测法 | 不通过的含义 |
|---|---|---|---|
| 1 | daemon 能否创建可写 memory entry | `mach_make_memory_entry_64(mach_task_self(), &size, addr, VM_PROT_READ\|VM_PROT_WRITE, &entry, MACH_PORT_NULL)` | 自己都建不出来，与沙箱无关，是实现错误 |
| 2 | entry 的 send right 能否经 XPC 送达受沙箱的 peer | `xpc_mach_send_create` + `xpc_dictionary_set_value` | 沙箱禁 `mach-send`。处置：改走 kext 转交（D113 的同一条退路） |
| 3 | peer 能否 **只读** 映射 | `mach_vm_map(mach_task_self(), …, VM_PROT_READ, …)` | OOL blob 的只读映射也断（D23），比 U-01 更严重 |
| 4 | peer 能否 **可写** 映射 | `mach_vm_map(…, VM_PROT_READ\|VM_PROT_WRITE, …)` | **这才是 U-01 本体** |
| 5 | **双向可见性**：peer 写、daemon 读到；daemon 写、peer 读到；且无需显式同步 | 两边各写一个 magic 并轮询对方的 | 映射成功但不是别名（例如被降级成 copy-on-write）。这是最隐蔽的失败模式，必须显式测 |

第 5 格最容易被漏掉，而它是**正确性**问题而不是能力问题：一个被静默降级成 COW 的映射会让 `MTLBuffer.contents` 看起来工作，但客户端写的顶点数据永远到不了 GPU。

#### 4.2.2 判定标准

```text
U-01 = 可行   ⟺  1..5 全部通过，且第 5 格在「peer 是受 WindowServer 沙箱 profile 约束的进程」条件下通过
U-01 = 不可行 ⟺  第 4 或第 5 格不通过
U-01 = 待定   ⟺  第 2 或第 3 格不通过（此时测不到 4/5，先修 2/3）
```

**探针必须在受约束的 peer 上跑。** 用一个普通 app 当 peer 只能证明「非沙箱进程可以」，而 WindowServer 自己是有 profile 的。`BLOCKED`：能不能在目标 guest 上构造一个与 WindowServer 等价的沙箱环境，本轮未查（S-008）。退路是直接在 WindowServer 上测，代价是失败时掉图形界面，所以必须先有 SSH 与串口（`00-OVERVIEW.md` §2.5 风险 2 的纪律）。

#### 4.2.3 本册必须独立于 U-01

**这是本节最重要的一条，而且它是一个设计约束，不是观察。**

`50` 分册把 U-01 列为「切分方案的单点风险」，但它影响的是 **`MTLBuffer.contents` 的跨进程直写**（D8），**不是 IOSurface 路径**。两者走的是不同的内核机制：

| 路径 | 机制 | 受 U-01 影响 |
|---|---|---|
| `MTLBuffer.contents` 跨进程 | Mach **memory entry** + `mach_vm_map` | **是** |
| IOSurface 跨进程 | Mach **port right** + `IOSurfaceLookupFromMachPort` + 内核侧 `IOSurfaceClient::mapInTask`（`[S] 0x1197A`） | **否** |

IOSurface 的映射不是我们建的，是 `IOSurface.kext` 在内核里直接映射进调用者 task 的（`12` §1.6 已证：IOSurface 的内存不通过 `IOConnectMapMemory` 拿，而是 `mapInTask` 在内核里建）。沙箱对 `IOSurfaceLookupFromMachPort` 的处置是 U-03 的事，与 U-01 是两个独立的未知。

> **R41-17**：**本册的实现不得依赖 U-01 的结果。** 具体做法：`SurfaceBacking` 的内存来源只有两种，`IOSurfaceGetBaseAddressOfPlane` 返回的指针（跨进程由 §4.1 的 right 路径取得）和本进程自己分配的页（§5 的重映射区）。**任何地方都不出现 `mach_make_memory_entry_64`。** 需要跨进程共享裸内存的功能一律归 `50` 分册，不进本册。

### 4.3 U-01 = 可行：路径 A

`INFERRED`。这是期望的情形，本册几乎不变：

```text
WindowServer                             helper
  IOSurfaceCreate / 已有 surface
  IOSurfaceCreateMachPort  --------->  （port descriptor 经 XPC）
                                        IOSurfaceLookupFromMachPort
                                        measure()          D100
                                        check_geometry()   D101
                                        import_plane_as_texture()
  MTLBuffer.contents 的那些 buffer:
  helper 侧用 memory entry 把后备页映射回客户端（D8），contents 返回映射地址
```

本册只需保证一点：**IOSurface 路径与 memory entry 路径的内存绝不混用**。即一个 `SurfaceBacking` 的页永远不会被包装成 memory entry 再映射给别人。理由：IOSurface 的页由内核的 `IOSurfaceClient` 记账，在它上面再套一层 memory entry 会让 §6.1 的三层计数变成四层，而第四层的生命周期没人管。

### 4.4 U-01 = 不可行：路径 B（退路）

`INFERRED`。这是本节被点名必须给出的那条。

#### 4.4.1 断掉的是什么

| 功能 | U-01 不可行后的状态 |
|---|---|
| `MTLBuffer.contents` 跨进程返回真实指针 | **断**。返回 `NULL` 不是选项（`50` C-6：CoreAnimation 大量用 `contents` 直写顶点与 uniform，返回 `NULL` 等于该路径不可用） |
| CoreAnimation 的直写路径 | **断** |
| IOSurface 的创建、导入、采样、作为 attachment | **不受影响**（§4.2.3） |
| `MTLSharedTextureHandle` | **不受影响**（它走 §4.6 的 surface ID + token，不走 memory entry） |
| 上屏 | **不受影响**（§7：走 framebuffer 内存，由 `IOFramebufferUserClient::clientMemoryForType(110)` 建立映射，那是 IOKit 的机制，不是 memory entry） |

#### 4.4.2 退路的三个档位，按代价排序

**档位 B1：把 `contents` 改成「客户端私有页 + 显式上传」。** 推荐。

```text
newBufferWithLength:options:
  客户端进程（proxy 侧）：vm_allocate 一块页对齐的私有内存，contents 返回它
  helper 侧：一块等大的设备内存
  客户端写完 -> didModifyRange: / commit 时，proxy 把脏区间经 OOL 送给 helper
  helper 侧用上游 HostMemory::with_dirty_pages 或 BufferContents::CopyHost 吸收
```

代价与适用：

| 项 | 值 |
|---|---|
| 每帧额外拷贝 | 脏区间大小。CoreAnimation 的 uniform 与顶点通常是数十 KB 到数 MB 级，不是全画面 |
| 正确性 | **完整**。Metal 的 `contents` 合同只要求「返回可写的 CPU 地址，且 `didModifyRange:` 之后 GPU 能看到」。`StorageModeManaged` 本来就是这个合同 |
| 对 `StorageModeShared` 的影响 | Metal 的 `Shared` 合同更强：不需要 `didModifyRange:`。**这一条会被破坏**。缓解：把提交点（`commit`）当成隐式的全缓冲 `didModifyRange:`，并对跨提交点的中途写入发一条本项目自有的告警 `m2vu-shared-buffer-late-write` |
| 上游支持 | 有。`HostBytes`、`Texture::replace_region_with_host_bytes`、`BufferContents::CopyHost` 就是上游专为「读取过程中可能变化的 guest 内存」准备的（`40` §4.1） |

**档位 B2：只把 translator 放进 helper，Vulkan 留在客户端进程。** 这是 `50` 分册 Gate H-2 自己给的处置（「必须回到同进程并另找办法隔离 LLVM，例如把 translator 单独放进 helper，Vulkan 留在客户端进程」）。

| 项 | 值 |
|---|---|
| 收益 | 保住了最大的那个隔离目标：`50` D97 已论证 metallib → AIR 解析 → translator → LLVM 是最大攻击面，而且不是本项目写的代码；同进程时 translator 的一个 panic 就是 WindowServer 的 abort |
| 丢掉的 | Mesa / Lavapipe 自己的崩溃仍然会拖死 WindowServer |
| 对本册的影响 | **零**。IOSurface 桥与 Vulkan 在同一个进程里，连 §4.1 的 port 传递都不需要 |
| 额外成本 | wire protocol 只需两条消息（`COMPILE_LIBRARY`、`COMPILE_PIPELINE`），比完整切分小一个数量级 |

**档位 B3：全同进程。** 第一版本来就是同进程（`00-OVERVIEW.md` §6），所以这不是退步，只是不前进。代价是 `50` 分册整册的收益归零。

#### 4.4.3 推荐与触发条件

> **R41-18**：U-01 不可行时采 **B1 + B2 组合**：translator 进 helper（拿到最大的隔离收益），`MTLBuffer.contents` 走 B1 的私有页 + 显式上传（保住 CoreAnimation），Vulkan 与 IOSurface 桥**留在客户端进程**。
>
> 这个组合的性质值得说清：它把「helper 隔离」的目标从「隔离整个渲染栈」缩小到「隔离编译器」，而编译器恰好是攻击面与崩溃面的大头。**本册在三个档位下的代码都一样**，因为 R41-17 已经把本册与 memory entry 解耦了。

### 4.5 IOSurface 全局 ID 不是授权凭据：验权手段

#### 4.5.1 为什么它不是凭据（本构建上有证据）

`KNOWN`。三条事实叠起来：

1. **ID 就是内核表下标。** `[S] IOSurfaceRoot::find_surface +0x164B8` 的第一步是 `if (id == 0 || id >= root->tableCount) goto not_found; IOSurface *s = ((IOSurface **)root->table)[id];`（`12` §3.4）。所以 ID 空间是 32 位连续小整数，**可枚举**。
2. **全局 lookup 默认开。** `IOSurfaceRoot::start` 第 11 步解析 `PE_parse_boot_argn("iosurface_debug", …)`，默认值 `20`，其 **bit2 =「允许全局 lookup」，默认开且带警告**（`12` §1.2）。
3. **放行条件 ③ 不看调用者。** `find_surface` 的三条放行里，条件 ③ 是 `(s->flags & 0x80002) == 2`（bit1 置、bit19 清），**与调用方的 task 无关**（`12` §3.4）。

合起来：在本构建上，任何进程都可以对 `id = 1, 2, 3, …` 逐个 `IOSurfaceLookup`，拿到所有被标成全局的 surface。这就是 `22-OBJC-DESCRIPTORS.md` §4.25 第 4 点那条要求的机制依据。

#### 4.5.2 四层验权，按权威性排序

`INFERRED`（机制是实现选择；每层的必要性由 §4.5.1 决定）。

| 层 | 手段 | 权威性 | 失败处置 |
|---|---|---|---|
| **1** | **helper 自己的对象表。** 只有 helper 创建过、或经 §4.1 的 Mach right 导入过的 surface 才在表里 | **最高。** 这是唯一的真凭据 | 不在表里 → 直接拒绝，不要试图 `IOSurfaceLookup` 救 |
| **2** | **MAC token。** `HMAC-SHA256(k_boot, surface_id ‖ generation ‖ nonce ‖ client_id)` 截 16 字节，`k_boot` 是 helper 启动时从 `getentropy` 取的 32 字节，**只在 helper 的地址空间内** | 高。与 `50` 分册 D68 的 shared event MAC token 同一机制，复用同一把 key 派生 | 不匹配 → 拒绝 + 速率计数（`50` D109 的三条速率规则） |
| **3** | **XPC peer 的 audit token。** `xpc_connection_get_audit_token`，取 `euid` 与 `csflags`（`50` Gate H-1(e) 要求记录这两项的取值） | 中。证明「谁在问」，不证明「他有权要这个 surface」 | 与 token 里的 `client_id` 不符 → 拒绝 |
| **4** | **surface 上的 `net.metal2vu.owner` attachment。** `IOSurfaceCopyValue` 读出 16 字节 UUID 与表里比对 | **低，仅交叉检查**（R41-4：任何持有者都能覆写它） | 不符 → **不拒绝**，记 `m2vu-surface-owner-mismatch` 告警 |

> **R41-19**：验权的判据是**第 1 层**，第 2–4 层是纵深。**任何代码路径都不得以「`IOSurfaceLookup` 成功」作为授权结论。** `IOSurfaceLookup` 在本册里只有一个用途：§4.6 的解码路径在对象表里**命中之后**，用它作为「这个 ID 现在确实还指向同一张 surface」的一致性检查。

#### 4.5.3 我们自己创建的 surface 要不要设成全局

| surface 的用途 | 设全局？ | 理由 |
|---|---|---|
| Metal 客户端的普通 texture / buffer 后备 | **不设** | 没有跨进程需求，设了就白送一个可枚举的句柄 |
| `MTLSharedTextureHandle` 的目标 | **设**，并且必须配第 2 层的 MAC token | 解码侧需要一条不经 port 的取回路径（§4.6.3） |
| scratch / shadow | **不设** | |

### 4.6 `MTLSharedTextureHandle` 的 `<NSSecureCoding>` 实现

#### 4.6.1 为什么这一半归本册

`KNOWN`。三条输入：

- `40-RUNTIME-VULKAN.md` §2.3 与第 4 节第 6 项：上游的 `SharedTextureHandle` **仅进程内**，跨进程 `MTLSharedEvent` / `MTLSharedTextureHandle` 是本项目的工作。
- `22-OBJC-DESCRIPTORS.md` §4.25：`MTLSharedTextureHandle`（`D-OBJC:14438`）是 descriptor 族里唯一声明 `<NSSecureCoding>`（不是 `<NSCopying>`）的类；它的 ivar `_priv` 的类型编码是 `^{MTLSharedTextureHandlePrivate=^{__IOSurface}@@}`，即 **Apple 的内部表示就是一个 `IOSurfaceRef` 加两个对象指针**。
- `20-OBJC-DEVICE.md` §8.6：Apple 的 `createMachPort` / `initWithMachPort:` 走 `IOSurfaceCreateMachPort` / `IOSurfaceLookupFromMachPort`。

所以 Apple 自己有两条路：**port 路（`createMachPort`）**与**序列化路（`NSSecureCoding`）**。序列化路只能传字节，不能传 right，因此它必然传的是 ID 一类的东西。本项目照这个结构做，但把授权挪到 token 上。

#### 4.6.2 wire 格式

`INFERRED`。序列化内容固定为五个键，**全部定长、全部标量或定长 `NSData`**：

| key | 类 | 内容 |
|---|---|---|
| `"v"` | `NSNumber`（`unsignedIntValue`） | 格式版本，当前 `1`。不认识的版本 → 解码失败 |
| `"sid"` | `NSNumber`（`unsignedIntValue`） | IOSurface 全局 ID。**诊断 + 一致性检查用，不是凭据** |
| `"gen"` | `NSNumber`（`unsignedLongLongValue`） | helper 的 generation（`50` 分册 D73/D74 要求跨进程持久化） |
| `"n"` | `NSData`，**恰好 16 字节** | nonce |
| `"t"` | `NSData`，**恰好 16 字节** | §4.5.2 第 2 层的 MAC token |

**不序列化**：几何、格式、plane 索引、label。理由是 D100：解码侧必须自己重测，传了也不信，传了反而给攻击者一个让两侧不一致的旋钮。

#### 4.6.3 ObjC 实现（可直接照抄）

```objc
// ============ 41-iosurface/M2VUSharedTextureHandle.m ============
// MTLSharedTextureHandle 的 <NSSecureCoding>。
// 22 §4.25 第 2 点：必须逐键 decodeObjectOfClass:forKey:，拒绝未知键，
// 不得用 decodeObjectForKey:（它会反序列化任意类）。

#import <Foundation/Foundation.h>
#import <IOSurface/IOSurfaceRef.h>

static NSString * const kM2VUKeyVersion   = @"v";
static NSString * const kM2VUKeySurfaceID = @"sid";
static NSString * const kM2VUKeyGenerat   = @"gen";
static NSString * const kM2VUKeyNonce     = @"n";
static NSString * const kM2VUKeyToken     = @"t";

static const uint32_t kM2VUHandleVersion  = 1;
static const NSUInteger kM2VUNonceLen     = 16;
static const NSUInteger kM2VUTokenLen     = 16;

@interface M2VUSharedTextureHandle : NSObject <NSSecureCoding>
@property (nonatomic, readonly) IOSurfaceRef surface;   /* CFRetain 过 */
@property (nonatomic, readonly) IOSurfaceID  surfaceID;
@property (nonatomic, readonly) uint64_t     generation;
@property (nonatomic, readonly, copy) NSData *nonce;
@property (nonatomic, readonly, copy) NSData *token;
@end

@implementation M2VUSharedTextureHandle {
    IOSurfaceRef _surface;
}

/* 必须返回 YES，否则 NSKeyedUnarchiver 的 secure 模式不会调用我们。*/
+ (BOOL)supportsSecureCoding { return YES; }

- (void)dealloc {
    /* 注意：这里只放 handle 自己的引用。纹理后备的 CFRelease 在
       SurfaceBacking 的 Drop 里（§6.1），两者是不同的引用。*/
    if (_surface) { CFRelease(_surface); _surface = NULL; }
}

- (void)encodeWithCoder:(NSCoder *)coder {
    NSAssert(coder.allowsKeyedCoding, @"keyed coding required");
    [coder encodeObject:@(kM2VUHandleVersion)  forKey:kM2VUKeyVersion];
    [coder encodeObject:@(_surfaceID)          forKey:kM2VUKeySurfaceID];
    [coder encodeObject:@(_generation)         forKey:kM2VUKeyGenerat];
    [coder encodeObject:_nonce                 forKey:kM2VUKeyNonce];
    [coder encodeObject:_token                 forKey:kM2VUKeyToken];
}

- (nullable instancetype)initWithCoder:(NSCoder *)coder {
    if (!coder.allowsKeyedCoding) { return nil; }
    self = [super init];
    if (!self) { return nil; }

    /* 逐键、逐类解码。NSNumber / NSData 都是具体类，不是容器，
       所以不需要 decodeObjectOfClasses:。*/
    NSNumber *v   = [coder decodeObjectOfClass:[NSNumber class] forKey:kM2VUKeyVersion];
    NSNumber *sid = [coder decodeObjectOfClass:[NSNumber class] forKey:kM2VUKeySurfaceID];
    NSNumber *gen = [coder decodeObjectOfClass:[NSNumber class] forKey:kM2VUKeyGenerat];
    NSData   *n   = [coder decodeObjectOfClass:[NSData   class] forKey:kM2VUKeyNonce];
    NSData   *t   = [coder decodeObjectOfClass:[NSData   class] forKey:kM2VUKeyToken];

    if (!v || !sid || !gen || !n || !t)                       { return nil; }
    if (v.unsignedIntValue != kM2VUHandleVersion)             { return nil; }
    if (n.length != kM2VUNonceLen || t.length != kM2VUTokenLen) { return nil; }

    _surfaceID  = (IOSurfaceID)sid.unsignedIntValue;
    _generation = gen.unsignedLongLongValue;
    _nonce      = [n copy];
    _token      = [t copy];

    /* 这里**不**取 surface，也**不**验权。
       理由：initWithCoder: 跑在客户端进程里，没有 k_boot，验不了；
       而且它不该有能力验。解码只产出一个未授权的请求对象。
       取 surface 与验权在 -[Device newSharedTextureWithHandle:] 里，
       由 helper 按 §4.5.2 的四层做。*/
    _surface = NULL;
    return self;
}
@end
```

#### 4.6.4 消费侧的顺序

`INFERRED`。`-[Device newSharedTextureWithHandle:]` 的实现必须按这个顺序，**不能调换前两步**：

```text
1. 把 {sid, gen, nonce, token} 送给 helper（或同进程的桥），由它查对象表        §4.5.2 第 1 层
   命中 -> 拿到 helper 侧已持有的 IOSurfaceRef
   未命中 -> 失败，返回 nil。不要尝试 IOSurfaceLookup
2. 验 MAC token                                                              第 2 层
3. 验 audit token 的 client_id                                               第 3 层
4. IOSurfaceGetID(s) == sid 一致性检查；不一致记告警（第 1 层已经授权了）
5. IOSurfaceCopyValue(net.metal2vu.owner) 交叉检查；不符记告警                第 4 层
6. measure() + check_geometry()                                              D100 / D101
7. import_plane_as_texture()
```

> **R41-20**：第 1 步失败时返回 `nil` 并构造 `NSError`，**不得**回退到 `IOSurfaceLookup(sid)`。§4.5.1 已证 ID 可枚举，这个回退就是把四层验权作废。

---

## 5. 分散后备（上游不做的第 2 项）

### 5.1 要做的是什么

`KNOWN`（范围划分来自 `40-RUNTIME-VULKAN.md` 第 4 节第 2 项：**分散后备**（`replaceBackingWithRanges:`、`detachBacking`），上游提供的基元是「把内存重映射成连续区后用 `rebind_bytes_no_copy`」）。

对应的 descriptor 字段是 `MTLBufferDescriptor.addressRanges`，类型 `@"MTLResourceAddressRangeArray"`，**当前处置是 B 档，直到本册实现**（`22-OBJC-DESCRIPTORS.md` §4.2）。

两个操作：

| Metal SPI | 语义 | 本项目的落法 |
|---|---|---|
| `replaceBackingWithRanges:` | 把一个 buffer 的后备换成若干不连续的地址区间 | §5.2：重映射成连续 VA → `rebind_bytes_no_copy` |
| `detachBacking` | 摘掉后备，buffer 对象还在 | §5.4：等在途命令缓冲不再用它 → 释放重映射区 |

### 5.2 重映射的具体做法

`INFERRED`（本册的实现选择）。**用 `mach_vm_remap`，不用 `vm_allocate` + 逐段 map。**

#### 5.2.1 为什么是 `mach_vm_remap`

本册被点名要在这两者之间选。理由：

| 方案 | 能否得到**别名**（写一边另一边可见） | 问题 |
|---|---|---|
| `mach_vm_remap(copy = FALSE, inherit = VM_INHERIT_SHARE)` | **能**。这是它的定义：在目标 task 的 VA 空间里为同一批物理页再开一个窗口 | 要求源区间页对齐、页粒度 |
| `vm_allocate` 新区 + 逐段 `memcpy` | **不能**。那是拷贝，不是别名 | 违反 no-copy 合同；客户端的后续写丢失 |
| `vm_allocate` 新区 + 逐段 `mach_vm_map` 到同一个 memory entry | 能，但要先为每段建 memory entry | 引入 `mach_make_memory_entry_64`，**违反 R41-17**（把本册绑到 U-01 上） |

所以是 `mach_vm_remap`，而且它恰好不碰 memory entry。

#### 5.2.2 具体序列

```c
/* ============ 41-iosurface/scattered.c ============
 * 把 n 个不连续区间别名到一段连续 VA。
 * 前置：每个区间的 base 与 length 都必须页对齐（见 §5.3 条件 b）。
 * 返回 KERN_SUCCESS 时 *out_base 是连续区的基址，长度 total。
 */
#include <mach/mach.h>
#include <mach/mach_vm.h>

typedef struct { mach_vm_address_t base; mach_vm_size_t length; } m2vu_range_t;

kern_return_t
m2vu_remap_contiguous(const m2vu_range_t *r, size_t n,
                      mach_vm_address_t *out_base, mach_vm_size_t *out_total)
{
    const mach_vm_size_t pg = (mach_vm_size_t)vm_page_size;
    mach_vm_size_t total = 0;
    for (size_t i = 0; i < n; i++) {
        if ((r[i].base % pg) != 0 || (r[i].length % pg) != 0) return KERN_INVALID_ARGUMENT;
        if (r[i].length == 0)                                 return KERN_INVALID_ARGUMENT;
        mach_vm_size_t t = total + r[i].length;
        if (t < total) return KERN_INVALID_ARGUMENT;          /* 溢出 */
        total = t;
    }
    if (total == 0) return KERN_INVALID_ARGUMENT;

    /* 1) 先占一段连续 VA。VM_FLAGS_ANYWHERE 让内核选位置。
     *    这一步只是预留洞，里面的页随后会被逐段 OVERWRITE 掉。*/
    mach_vm_address_t res = 0;
    kern_return_t kr = mach_vm_allocate(mach_task_self(), &res, total, VM_FLAGS_ANYWHERE);
    if (kr != KERN_SUCCESS) return kr;

    /* 2) 逐段别名进去。
     *    copy = FALSE   -> 别名，不是拷贝（这是整件事的要点）
     *    VM_FLAGS_FIXED | VM_FLAGS_OVERWRITE -> 落在第 1 步预留的洞里
     *    VM_INHERIT_SHARE -> fork 后仍共享（本项目不 fork，但语义要对）
     */
    mach_vm_address_t cur = res;
    for (size_t i = 0; i < n; i++) {
        vm_prot_t cur_prot = VM_PROT_NONE, max_prot = VM_PROT_NONE;
        mach_vm_address_t target = cur;
        kr = mach_vm_remap(mach_task_self(), &target, r[i].length, /*mask=*/0,
                           VM_FLAGS_FIXED | VM_FLAGS_OVERWRITE,
                           mach_task_self(), r[i].base, /*copy=*/FALSE,
                           &cur_prot, &max_prot, VM_INHERIT_SHARE);
        if (kr != KERN_SUCCESS) goto fail;
        if (target != cur) { kr = KERN_FAILURE; goto fail; }   /* FIXED 没被尊重 */
        if ((cur_prot & (VM_PROT_READ | VM_PROT_WRITE)) != (VM_PROT_READ | VM_PROT_WRITE)) {
            kr = KERN_PROTECTION_FAILURE; goto fail;           /* 拿不到读写，别装作成功 */
        }
        cur += r[i].length;
    }
    *out_base = res; *out_total = total;
    return KERN_SUCCESS;

fail:
    (void)mach_vm_deallocate(mach_task_self(), res, total);
    return kr;
}
```

#### 5.2.3 三个必须检查的点

> **R41-21**：上面代码里的三条检查不是防御性冗余，各自对应一个真实失败模式：
> 1. **页对齐检查**：`mach_vm_remap` 的粒度是页。非页对齐的区间无法别名，只能拷。遇到就**不要偷偷拷**，返回失败并让 §5.3 的条件 b 把这种 surface 挡在 B 档。
> 2. **`target != cur`**：`VM_FLAGS_FIXED` 在某些情形下会被忽略并落到别处，那样连续性就破了，后面的指针算术全错。
> 3. **`cur_prot` 不含读写**：源区间的 `max_protection` 可能本来就不含 `VM_PROT_WRITE`（例如它自己是个只读映射）。此时 remap 会「成功」但给出只读窗口，随后第一次 GPU 写就是 `SIGBUS`。

#### 5.2.4 接到上游

```rust
// 重映射成功后交给上游。上游要的是一段连续的 host 内存。
let (base, total) = remap_contiguous(&ranges)?;        // §5.2.2
let host = HostMemory::with_import_gate(
    HostBacking::Pointer { ptr: base as *mut u8, len: total },
    gate,                                               // 40 §4.1
)?;
// 关键：rebind 而不是重建 buffer。buffer 的 ObjectId 必须不变，
// 因为 Metal 的 replaceBackingWithRanges: 不改变 buffer 的身份。
buffer.rebind_bytes_no_copy(host)?;                     // 40 第 4 节第 2 项的那个基元
```

### 5.3 `addressRanges` 从 B 档升到可实现所需的全部条件

本册被点名要给出「全部条件」。七条，分成三类。

#### 5.3.1 必须先取得的事实（三条，都 `BLOCKED`）

| 条件 | 缺什么 | 取法 | 能否用 `91` 的 CI 通道 |
|---|---|---|---|
| **a** | `MTLResourceAddressRangeArray` 的读接口：类名、selector、每项的字段（base / length 的编码与单位） | 该类的 ObjC 元数据。`22` §4.2 只记了字段类型是 `@"MTLResourceAddressRangeArray"`，没有类的内部 | **能。** `91` §5.3 已证运行器上可以遍历 `objc_copyClassNamesForImage(Metal.framework)` 并 dump 方法/ivar 列表（R-005 就是用这条通道关的）。这是 S-009 |
| **b** | 实际传进来的区间是否页对齐 | 运行期事实。谁调 `replaceBackingWithRanges:`、传什么粒度 | **能，部分。** 运行器上可以 hook 该 selector 并记录实参。但「系统路径会不会调它」需要在目标 guest 上 trace（`60` C-07 的同一次采集）。这是 S-010 |
| **c** | `rebind_bytes_no_copy` 的精确签名、前置条件、以及它对「在途命令缓冲正在用旧后备」的处置 | 上游 rustdoc | **不需要 CI。** `cargo doc -p metal2vulkan-runtime --open`（`40` §0 的「读法」）。这是 S-011 |

#### 5.3.2 必须通过的运行期检查（两条，`INFERRED`）

| 条件 | 检查 | 不通过的处置 |
|---|---|---|
| **d** | `mach_vm_remap(copy = FALSE)` 在同一 task 内确实产生**别名**而不是 COW | 探针：remap 后两边各写一个 magic，双向验证。与 §4.2.1 第 5 格同形但更简单（不跨进程）。这是 S-012 |
| **e** | 重映射区的基址满足 `minImportedHostPointerAlignment` | `mach_vm_allocate` 给的是页对齐基址，页大小（4 KiB 或 16 KiB）通常 ≥ 该值，但必须实测而不是假定（S-004 的同一次探测）。不满足 → 轴 1 退化为 `CopiedHostPages`，分散后备的意义就没了 → 维持 B 档 |

#### 5.3.3 必须实现的约束（两条，`INFERRED`）

| 条件 | 约束 |
|---|---|
| **f** | 区间集合的合法性：总长 ≤ `DeviceProperties::max_buffer_length`（`91` 已实测 APV 是正好 1 GiB，`maxBufferLength = 1073741824`）；区间数 ≤ 本项目设的上限（建议 **256**，理由是每段一次 `mach_vm_remap` 系统调用，上限决定一次 `replaceBackingWithRanges:` 的最坏延迟）；区间两两不相交（同 §3.6 的 `check_planes_disjoint`，同一套逻辑） |
| **g** | 换后备的时机：**在途命令缓冲仍在用旧后备时不得换。** 判据是上游 `CommandBuffer::used_resources`（`40` §4.1：「命令缓冲完成前它用到哪些内存 → `detachBacking` 的等待依据」，上游明确为此而写）。见 §5.4 |

#### 5.3.4 升档判据

> **R41-22**：`addressRanges` 从 B 档升到 D 档（可用）需要 **a–g 全部成立**。其中 a、c 是纯文档工作（小时级），d 是一个几十行探针，b 决定这件事值不值得做。**建议顺序：先 c（免费），再 a（CI 一轮），再 b（决定优先级），最后 d/e。**
>
> 若 b 的结论是「系统路径从不调 `replaceBackingWithRanges:`」，则**维持 B 档并记入已知损失**，不要实现。`60-CAPABILITY-MATRIX.md` §3 已经把分散后备标为 `SYS`（不是 `WS` 也不是 `CA`），即它不在 WindowServer 首帧的关键路径上。

### 5.4 `detachBacking` 的等待依据

`INFERRED`（机制来自 `40` §4.1 的上游扩展清单）。

```rust
/// detachBacking：摘后备，对象还在。
/// 不能直接释放内存，因为在途命令缓冲可能还在读它。
pub fn detach_backing(&self, buffer: &Buffer) -> Result<(), DetachError> {
    // 1) 问每个在途命令缓冲：你还用它吗
    //    上游 used_resources 就是为这件事写的。
    for cb in self.inflight_command_buffers() {
        if cb.used_resources().contains_buffer(buffer) {
            // 2) 不等 waitUntilCompleted。50 D65 禁止在 display 路径上用它，
            //    而且上游会对会死锁的等待直接返回 WaitWouldDeadlock。
            //    改为挂一个 completion handler，在最后一个完成时才真释放。
            self.defer_release(buffer.clone(), cb.clone());
            return Ok(()); // Metal 的 detachBacking 是立即返回的
        }
    }
    // 3) 没人用了，现在释放
    self.release_backing_now(buffer)
}
```

> **R41-23**：`detachBacking` **立即返回**，释放是延迟的。释放点是「最后一个用到该后备的命令缓冲的 completion handler」，与 §6.2 的 `deallocator` 调用点是同一个时刻（都挂在 `KeepAlive` 的释放上）。**不得在 `detachBacking` 里阻塞等待**，那会挂住 WindowServer（`40` §5 的死锁等待规则、`50` D65）。

---

## 6. 生命周期、线程与可见性

### 6.1 三套引用计数的交界

本节是本册最容易写错的地方，因为有**三套互不相干的计数**在同一块内存上。

#### 6.1.1 三套计数各是什么

| 套 | 对象 | 加减 | 谁管 |
|---|---|---|---|
| **A** | `IOSurfaceRef` 的 CF 引用计数 | `CFRetain` / `CFRelease` | 本项目。内核侧的对偶是 `IOSurface::clientRetain` / `clientRelease`（`[S] 0xB3E6` / `0xB3F8`），`s_release_surface`（selector 1）走的是 client 计数而不是直接 `release`（`12` §6.1 第 4 点） |
| **B** | 上游的 `KeepAlive` | `HostMemory` 构造时产生，最后一个用到这块内存的命令缓冲完成时释放 | 上游 |
| **C** | ObjC 对象（`MTLTexture` / `MTLBuffer`）的 retain 计数 | `retain` / `release` / ARC | Metal.framework 与客户端 |

另外内核侧还有第四套（per-category use count，`IOSurface::increment_use_count_for_category [S] 0xB05A`），它是协作式提示，不参与内存回收，由 `IOSurfaceIncrementUseCount` / `Decrement` 操作。

#### 6.1.2 正确的交界：三条规则

> **R41-24**：**`CFRelease` 必须在 `KeepAlive` 的释放载荷里，不能在 `-dealloc` 里。**
>
> 顺序必须是：
> ```text
> 客户端 release MTLTexture
>   -> ObjC -dealloc           （套 C 归零）
>        -> drop Rust 侧的 Texture handle
>             -> 上游在「最后一个用到它的命令缓冲完成」时释放 KeepAlive   （套 B 归零）
>                  -> 我们的载荷跑：IOSurfaceDecrementUseCount
>                                   调用并释放 deallocator block
>                                   CFRelease(surface)                （套 A 归零）
> ```
> 把 `CFRelease` 放进 `-dealloc` 是**释放后使用**：`22` R42 已明确「`deallocator` 的调用点是上游 `KeepAlive` 被释放之时，不是 `MTLBuffer` 的 `dealloc` 之时，两者可能相差数帧（在途命令缓冲仍持有后备）」。同一个理由适用于 surface 本身：`-dealloc` 之后 GPU 可能还在读那些页。
> `KNOWN`（`22` R42 的事实）+ `INFERRED`（推广到 `IOSurfaceRef`）

> **R41-25**：**`CFRetain` 的时点是 snapshot 生成时，在 ObjC 方法返回之前。** `22-OBJC-DESCRIPTORS.md` §4.2 对 `MTLBufferDescriptor.iosurface` 字段的规定是「非 `NULL` 时走 `41` 的导入路径；`IOSurfaceRef` 必须 `CFRetain` 并交给 snapshot」。R1/R2 要求 snapshot 在调用返回前生成，R11 要求 snapshot 不可变。合起来：**`CFRetain` 在 shim 里做，`SurfaceBacking` 接手这一个 +1，不再额外 retain。**

> **R41-26**：**一张 surface 上的多个 plane 纹理共享同一个 `SurfaceBacking`。** 不要为每个 plane 各 `CFRetain` 一次再各自 `CFRelease`，那样会在 plane 0 的纹理先死时让 plane 1 的 `base` 指针来源变得可疑。做法：`SurfaceBacking` 是一个 `Arc`，每个 plane 纹理持一份克隆，最后一份掉线时跑 §6.1.2 的载荷。

#### 6.1.3 载荷的实现

```rust
// ============ crates/m2vu-iosurface/src/backing.rs ============

/// 一个 CFRetain 过的 IOSurfaceRef。Drop 时 CFRelease。
/// 只允许由 ObjC shim 构造（它负责那一次 CFRetain，R41-25）。
pub struct RetainedSurface(IoSurfaceRef);

unsafe impl Send for RetainedSurface {}
unsafe impl Sync for RetainedSurface {}

impl Drop for RetainedSurface {
    fn drop(&mut self) {
        unsafe {
            IOSurfaceDecrementUseCount(self.0);
            CFRelease(self.0 as _);
        }
    }
}

/// `22` R41：必须 `_Block_copy` 一次、恰好调用一次、调用后 `_Block_release`。
/// `21` §9.5：本项目不继承 `MTLIOAccelBuffer`，所以这份责任落在自己头上。
pub struct DeallocatorBlock {
    /// `m2vu_copy_buffer_deallocator` 的返回值（即 `_Block_copy` 的结果）。非空。
    block: *mut c_void,
    /// 回调的两个实参，与 Metal 的 `^(void *pointer, NSUInteger length)` 一致。
    pointer: *mut c_void,
    length: usize,
    called: bool,
}

impl DeallocatorBlock {
    /// 只能由 ObjC shim 构造；`_Block_copy` 在那里做（§6.2 的 shim）。
    pub unsafe fn from_copied(block: *mut c_void, pointer: *mut c_void, length: usize) -> Self {
        debug_assert!(!block.is_null());
        Self { block, pointer, length, called: false }
    }
}

impl Drop for DeallocatorBlock {
    fn drop(&mut self) {
        // R41-27：调用时不得持有任何锁。调用方必须在拿出 block 之前退出
        // 所有临界区；这个 Drop 的位置就是那个点。
        debug_assert!(!self.called, "deallocator called twice");
        self.called = true; // 先置位，异常路径上也不会二次调用
        unsafe {
            // ObjC 侧的 shim，内含 @try/@catch（§6.2）
            m2vu_invoke_buffer_deallocator(self.block, self.pointer, self.length as c_ulong);
            m2vu_release_buffer_deallocator(self.block);
        }
    }
}
```

> **R41-27**：`deallocator` 的调用**不得持有任何锁**（`22` R41 的原文：对象表、连接状态、命令缓冲状态、回调表都不行）。ObjC 异常必须在 shim 边界捕获，不得穿过 Rust/FFI。实现上这意味着 `SurfaceBacking` 的 `Drop` 必须先把 `deallocator` `take()` 出来、退出所有临界区、再让它 drop。

### 6.2 `_Block_copy` / `_Block_release` 的时机

`KNOWN`（`21-OBJC-OBJECT-FAMILY.md` §9.5 的符号级事实 + `22` R41/R42）。

`21` §9.5 的事实：`S-APV` 的导入表里**没有** `_Block_copy` / `_Block_release`，只有 `__Block_object_assign` / `__Block_object_dispose` / `__NSConcreteStackBlock`（这三个是「本模块自己创建带捕获变量的 block」所需，不是拷贝外来 block 所需）。APV 对带 block 的方法一律原样透传给基类，由 `MTLIOAccelBuffer` / `_MTLCommandBuffer` 负责 `Block_copy` 与持有周期。

**本项目自建 resource 类（继承 `_MTLResource` 子树而不是 `MTLIOAccelResource`，`20` §8.5 的决定），因此这份责任落到自己头上。** `21` §9.5 明文要求把这笔成本记在本册。记在这里：

| 时点 | 动作 | 位置 |
|---|---|---|
| `newBufferWithBytesNoCopy:length:options:deallocator:` 进入 | `_Block_copy(deallocator)`，存进 snapshot | ObjC shim，**在方法返回前**（R1/R2） |
| snapshot 交给 Rust | 所有权移交 `DeallocatorBlock` | 窄 C ABI 边界 |
| `KeepAlive` 释放 | `m2vu_invoke_buffer_deallocator(block)` 恰好一次，然后 `_Block_release` | `DeallocatorBlock::drop`（§6.1.3） |
| 导入路径失败（§2.3 的任何 `Reject`） | **仍然要调用一次再释放**。Metal 的合同是「给了 deallocator 就一定会被调用」 | `Reject` 的清理路径 |

最后一行容易漏：失败路径上如果直接丢掉 block，客户端的内存就泄了，而且它永远等不到回调。

ObjC 侧的 shim（可直接照抄）：

```objc
// ============ 41-iosurface/M2VUBlockShim.m ============
// 只做两件事：把外来 block 拷进我们的所有权；在调用点捕获 ObjC 异常。
#import <Foundation/Foundation.h>
#include <Block.h>

typedef void (^M2VUBufferDeallocator)(void *pointer, NSUInteger length);

/* 返回 _Block_copy 的结果，所有权移交调用方（Rust 侧的 DeallocatorBlock）。*/
void *m2vu_copy_buffer_deallocator(M2VUBufferDeallocator _Nullable block) {
    if (!block) { return NULL; }
    return (void *)Block_copy(block);
}

/* R41-27：调用点。ObjC 异常不得穿过 FFI 边界。*/
void m2vu_invoke_buffer_deallocator(void *copied, void *pointer, unsigned long length) {
    if (!copied) { return; }
    M2VUBufferDeallocator b = (__bridge M2VUBufferDeallocator)copied;
    @try {
        b(pointer, (NSUInteger)length);
    } @catch (NSException *e) {
        /* 记日志后吞掉。客户端的 deallocator 抛异常是客户端的缺陷，
           但让它穿过 Rust 的栈会是未定义行为。*/
        m2vu_log_deallocator_exception(e.name.UTF8String, e.reason.UTF8String);
    }
}

void m2vu_release_buffer_deallocator(void *copied) {
    if (copied) { Block_release(copied); }
}
```

### 6.3 seed 与 use count：什么时候必须重测几何

`KNOWN`（规则来自 `50` D100/D101）+ `INFERRED`（触发表）。

先把两件事分开，因为 D100 的措辞容易让人把它们混在一起：

| 量 | 变化意味着 | 变化后要做什么 |
|---|---|---|
| **几何**（width / height / bytesPerRow / plane offset / size / alloc size / pixel format） | 按 §1.4，这些在 surface 创建后**不可变** | 只做**比对**。发现变了说明我们看到的不是同一张 surface，或 framework 的返回值不可信 → 断开该 surface，记 `m2vu-surface-geometry-drift` |
| **base address**（`IOSurfaceGetBaseAddressOfPlane`） | 映射可能被重建（`IOSurfaceClient::mapInTask` / `unmap`，`[S] 0x1197A` / `0x11BE2`） | **重读是强制的**（R41-3）。变了就 `rebind_bytes_no_copy` |
| **seed**（`IOSurfaceGetSeed`） | **内容**变了 | shadow 模式下触发重转换；in-place 模式下什么都不用做 |
| **use count** | 有别的参与者 | 纯提示。进日志，不影响任何判定 |

完整触发表：

| 触发 | 重测几何（比对） | 重读 base（强制） | 重算 shadow |
|---|---|---|---|
| 首次导入（D100） | ✔ 全量 | ✔ | ✔ |
| 每次 `IOSurfaceLock` 返回 | ✔ 比对 | ✔ | — |
| `IOSurfaceUnlock` 后 seed 前进 | — | — | ✔（若轴 2 = shadow） |
| 跨 generation 重新 import（§6.5） | ✔ 全量 | ✔ | ✔ |
| `replaceBackingWithRanges:`（§5） | ✔ 全量 | ✔ | ✔ |
| 客户端声明的 snapshot 与实测不一致 | 已经在比对里 | — | — |
| `selector 46` 改了 image origin/extents | ✔ 全量（这是唯一能改「几何」的合法路径，`12` §1.4） | ✔ | ✔ |

> **R41-28**：**请求里的 snapshot 永不作为事实。** D100 的原话是「请求里的 snapshot **只用于交叉检查**，不作为事实」，`22` R11 的另一半也是这个（「需要晚一点才知道的信息（例如 IOSurface 的真实行距）必须由 Rust 侧自己重新测量，不得用 descriptor 里客户端声明的值」）。实现上：`measure()` 的 `declared` 形参是 `Option<&SurfaceGeometry>`，只用来产出 diff 日志，**不参与任何控制流**。

### 6.4 lock 时序（D104）

`KNOWN`（规则来自 `50` D104）+ `BLOCKED`（跨进程可见性序列，U-04）。

D104 的原文三条：写 lock 在**第一个在途 writer 之前**取得；unlock / seed 更新在**最后一个 writer 的上游 completion 之后**完成；**不得在 proxy 释放 texture 时提前 unlock**。

落到实现：

```text
                                 时间 →
客户端：  encoder 开始写 surface S ─────────────── endEncoding ── commit
我们：
  [1] 第一个把 S 作为 writable 目标的 encoder 被创建时：
        if writer_count(S) == 0 { IOSurfaceLock(S, 0, &seed_at_lock) }
        writer_count(S) += 1
  [2] 每个用到 S 作为 writable 的命令缓冲提交时：
        挂一个 completion handler
  [3] 每个 completion handler 跑时：
        writer_count(S) -= 1
        if writer_count(S) == 0 {
            if 轴2 == ShadowedTexture { 把 shadow 写回 plane（§3.5.3 第 3 步） }
            IOSurfaceUnlock(S, 0, &seed_after)
        }
  [4] texture 对象被释放时：
        什么都不做。writer_count 不受对象生命周期影响。
```

三条实现要求：

> **R41-29**：`writer_count` 按 **surface** 计，不按 plane、不按 texture 对象。一张 surface 上两个 plane 各有一个 writer，是一次 lock 两次计数。

> **R41-30**：**第 [4] 步是 D104 的第三条，必须显式写成「什么都不做」并配一条测试。** 「proxy 释放 texture 时提前 unlock」是一个很自然的实现冲动（对象没了，锁该放了），而它会在 GPU 还在写的时候把 seed 前进，让读者看到撕裂帧。这正是 `50` 分册把它单独列出来的原因。

> **R41-31**：读锁走同一套计数但**独立的计数器**，且 `kIOSurfaceLockReadOnly` 的 lock/unlock 必须配对。读写同时在途时先取写锁（写锁语义覆盖读）。

`BLOCKED`：`50` 分册 U-04 是「`IOSurfaceLock`/`Unlock` 的 flags、seed 与跨进程可见性的最终序列」未实测，并明确「本文不把它当作已验证的 cache-coherency ABI」。本册的态度相同：**上面的时序是基于 Metal 侧的合同推出的正确性要求，不是基于已验证的内核 cache 语义。** 影响：跨进程写路径的验收被阻断（§8.2 的 V-07）。同进程实现不受影响，因为 Lavapipe 就是 CPU，不存在跨总线缓存（`12` §3.4 的同一条理由）。

### 6.5 跨 generation 存活（D82）

`KNOWN`（`50` 分册 D82）。D82 的原话：**IOSurface 是唯一跨 generation 存活的内容载体。** 它的内容在内核的 IOSurface 对象里，helper 只是映射了它。崩溃恢复后画面不必从零重建，客户端重新 import 同一个 surface 就能接着用。

这给本册三条要求：

| # | 要求 | 理由 |
|---|---|---|
| **1** | **helper 重启后，重新 import 走的是完整的首次导入路径**，不是「恢复」路径 | 新 generation 的 Vulkan device 是新的，`HostMemory`、`VkBuffer`、shadow image 全部要重建。surface 的**内容**活着，我们的**对象**没活 |
| **2** | **几何必须全量重测**（§6.3 的触发表最后一行区域） | 新 generation 没有任何可信的缓存 |
| **3** | **shadow 内容必须重算一次**，不能假定它还在 | shadow 是我们的 `VkImage`，随 device 一起死了 |

与 `50` 分册 D64/D79 的衔接（`KNOWN`，`50` §6.3 的 11 步与 C-4 的「与」判据）：确认 helper 已停止的三项必须**全部**成立，其中第 3 项是「该 generation 写过的全部 IOSurface 已被客户端侧重新 `IOSurfaceLock`/`Unlock` 一轮（证明没有别的写者持有锁）」。本册对此的义务：

> **R41-32**：helper 必须维护一张 **「本 generation 写过哪些 surface」** 的表（surface ID + 最后一次 unlock 时的 seed），落盘到 generation 状态里。恢复时由新 generation 读出，并对每一项等待客户端完成一轮 lock/unlock 才认为旧 generation 彻底退出。表的上限按 `50` §2.6 的配额精神设一个显式上界（建议 **4096** 条），溢出时降级为「等全部 surface」。

> **R41-33**：**旧 generation 遗留的写锁是一个真实故障模式，必须有超时。** 如果 helper 在持有写锁时被 `SIGKILL`，`IOSurfaceUnlock` 永远不会被调用。内核侧的锁由 `IOSurface::lockSurface` / `unlockSurface`（`[S] 0x9164` / `0x969E`）管，`12` §6.1 第 5 点已记明回收是异步的（`IOSurfaceRoot::start` 起了 `async_release_thread`）。**但「异步回收」只保证对象最终释放，不保证锁被放开。** 本轮未查清内核在 task 死亡时是否强制解锁（S-013）。在查清之前，处置是：恢复超时（建议与 `50` D66 的超时预算表对齐）之后，新 generation **放弃那张 surface**，让客户端重建，并记 `m2vu-surface-orphaned-lock`。不要尝试在新 generation 里强行 unlock 一张自己没锁过的 surface。

### 6.6 线程规则

`INFERRED`（基于 `21` §9.6 的线程契约 + `40` §5 的上游所有权规则）。

| 对象 | 规则 |
|---|---|
| `SurfaceBacking` | `Send + Sync`。内部可变状态（`bases` 快照、`writer_count`）用 `os_unfair_lock` 或 `Mutex` 保护。理由：`21` §9.6 第 1 条「device 必须线程安全，它的工厂方法会被任意线程并发调用」 |
| 导入路径（`import_plane_as_texture`） | **必须在专用串行段内**（R41-6）。这不是为了线程安全，是为了 degradation 归因 |
| `IOSurfaceLock` / `Unlock` | 在哪个线程调都可以，但**同一张 surface 的 lock/unlock 必须经过 §6.4 的计数器**，不得由多个线程各自 lock |
| `deallocator` 调用 | 不持锁（R41-27）。会在命令缓冲的 completion queue 上跑，不在提交线程上（`21` §9.6 第 4 条） |
| `CFRetain` / `CFRelease` | CF 的引用计数本身是线程安全的，但 `RetainedSurface` 的 `Drop` 必须保证只跑一次（靠 `Arc`，R41-26） |
| 重映射（§5.2） | `mach_vm_remap` 是系统调用，线程安全。但 `replaceBackingWithRanges:` 与在途命令缓冲的 `used_resources` 检查必须原子，用对象表的锁 |

---

## 7. 上屏：本册产出的 surface 怎么喂给显示

### 7.1 事实：本册的 surface 不参与 scanout

`KNOWN`。三条事实合起来封死了「把 surface 标成 displayable 送去上屏」这条路：

1. **`IOSurface::isDisplayable()` 在本构建恒返回 0。** `12` §2.2 的更正框已经把这一点证到底：实现就是 `return (flags986 & 0x10) >> 4`（`[S] 0x109F4`），而标志字 bit 20 **在全件 1,673 个函数里没有任何置位点**，只有 `init +0x3F83` 的 `and dword [rbx+3D8h], 0FFEDB3FDh` 把它清零。该位是私有 ivar、无 setter 导出、定义它的 kext 已被全量扫描。**没有那个开关。**
2. **第一版不声明 `DisplayPipeSupported`。** `11-KERNEL-DISPLAY.md` §4.1 的建议，且该分册已证在全部已取样本里**没有任何人读**这两个键（`IOAccelDisplayPipe::copyCapabilities` 在 `[F2]` 内零调用点）。
3. **IOFramebuffer 这一层没有「提交帧」的动作。** `11` §3.5.1：`IOFramebufferUserClient` 的 22 条 selector 里没有任何 flip / swap / present。WindowServer 把 framebuffer 内存（`clientMemoryForType` 的 type 110）映射进自己的地址空间后**直接写像素**。

因此（`12` §6.2 已经把这个结论写出来，本册照搬并补代价）：

```text
Lavapipe 渲染目标              == 本项目 framebuffer 的 IOBufferMemoryDescriptor
WindowServer 的 backing store  == 同一块内存（经 clientMemoryForType(110)）
IOSurface                      == 只服务 Metal 客户端自己的 texture / drawable，与上屏无关
```

### 7.2 两个 host-memory 来源，一套导入机制

`INFERRED`。本册的 `HostMemory` 导入路径要服务**两个**来源，它们的内存合同不同：

| 来源 | 谁分配 | 生命周期 | 对齐 | 导入方式 |
|---|---|---|---|---|
| IOSurface | `IOSurface.kext`（`[S] IOSurface::allocate +0x7AB8` 的四条分支，`12` §2.4） | 三套计数（§6.1） | 不可控（R41-7） | §2.3 的完整决策树 |
| framebuffer | 本项目的 kext，`IOBufferMemoryDescriptor::withOptions` + `kIOMemoryKernelUserShared`（`11` §3.4.1 已更正为这个标志） | == framebuffer service 的生命周期 | **可控**：我们自己分配，按 §3.1.2 的两级抬升 | 同一套 `HostMemory`，但 `KeepAlive` 的载荷是空的（内核持有所有权，我们不释放） |

> **R41-34**：framebuffer 内存的 `SurfaceBacking` 等价物**不得带 `RetainedSurface`，也不得带 `deallocator`**。它的所有权在内核侧（`11` §6.2：那块 `IOBufferMemoryDescriptor` 由 framebuffer 对象持有，在 `initWithID` 分配、在 `free()` 释放）。用一个独立类型 `FramebufferBacking` 表达，不要复用 `SurfaceBacking` 然后把两个字段填 `None`，那样迟早有人在错误的地方调 `CFRelease`。

### 7.3 从 surface 到屏幕的那一次拷贝

`INFERRED`（代价计算；输入是 `60` §5.1 的实测事实）。

`60-CAPABILITY-MATRIX.md` §5.1 的实测事实：**WindowServer 向 IOSurface plane 的 1920×1080 `RGBA16Float` 纹理写入**（来源：上游 `crates/metal2vulkan-validation/src/runtime_lane/surface_aliases.rs` 的文档），即合成目标不是 `BGRA8Unorm`，而是一张 `RGBA16Float` 的 surface。而 framebuffer 是 `BGRA8Unorm`（`11` §2.5：`maxWidth × maxHeight × 4`）。所以链路是：

```text
各 layer 的纹理  ──合成 pass──▶  RGBA16Float IOSurface (1920×1080)
                                      │
                                      │  一次格式转换 + 拷贝
                                      ▼
                                 framebuffer 内存 BGRA8Unorm (1920×1080)
                                      │
                                      ▼  WindowServer 自己写 / 我们写
                                   屏幕
```

每帧代价（1920×1080）：

| 项 | 字节 |
|---|---|
| 读 `RGBA16Float` surface | 1920 × 1080 × 8 = **16,588,800** |
| 写 `BGRA8Unorm` framebuffer | 1920 × 1080 × 4 = **8,294,400** |
| 合计 | 约 **24.9 MB/帧** |
| 60 Hz | 约 **1.49 GB/s** 的内存带宽 |

> **R41-35**：这一次转换**必须在 Vulkan 侧做**（一个 blit 或 compute pass，目标是导入的 framebuffer 内存），不得在 CPU 上 memcpy。理由：Lavapipe 的 pass 是多线程的，而一个单线程 memcpy 加格式转换在 1.49 GB/s 上会成为帧率天花板。实现上就是把 framebuffer 内存当作一张 `B8G8R8A8_UNORM` 的 linear image（§3.3 的五条必须成立，这是 R41-12 把 `B8G8R8A8_UNORM` 列进最小闭包的原因），然后 `vkCmdBlitImage` 或一个 fragment pass。

> **R41-36**：**如果 WindowServer 的合成目标能被我们改成直接写 framebuffer，这次拷贝就没了。** 判定依据是 `11` §3.5.1 的那句「如果本项目**不**声明 `DisplayPipeSupported`，那么 WindowServer 的输出就是直接写我们那块 `IOBufferMemoryDescriptor`」。但 `60` §5.1 的实测说它写的是一张 `RGBA16Float` surface。两者不矛盾（中间 surface 是合成的中间结果，最终仍落到 framebuffer），但**到底有几次拷贝只能在目标 guest 上实测**。记为 S-014，可用 `91` 的 CI 通道取（运行器上跑着真 WindowServer + 真 APV，可以观察它建了哪些 surface）。

---

## 8. 启动期自检与验收

形式照 `40-RUNTIME-VULKAN.md` §6.7 与 §9 的要求：自检在**对外发布设备之前**完成并落盘，验收条目逐条可执行。

### 8.1 启动期自检清单

每项都必须落盘（进 `90-EVIDENCE-INDEX.md`），失败处置分「致命」与「记录」两档。

| # | 检查 | 失败处置 | 依据 |
|---|---|---|---|
| **1** | `IOSurfaceGetTypeID()` 返回非 0，即 `IOSurface.framework` 已加载 | **致命** | 没有它整个模块不存在 |
| **2** | `VkPhysicalDeviceExternalMemoryHostPropertiesEXT::minImportedHostPointerAlignment` 读出并缓存；同时记录 `vkGetMemoryHostPointerPropertiesEXT` 给出的 memory type mask | **致命**（`40` §6.2 把 `VK_EXT_external_memory_host` 列为本项目的必需扩展） | R41-8、§3.3 条件 2/3 |
| **3** | `IOSurfaceGetPropertyAlignment` / `GetPropertyMaximum` 对 §1.5 的 8 个键各查一次 | 记录 | §1.5 |
| **4** | §3.1.1 的四个 Metal limit 按 R41-9 算出并自洽检查（2 的幂、不小于第 2 项） | **致命**（报小了会让客户端系统性走 copy 路径） | R41-9 |
| **5** | 对 R41-12 的最小闭包格式集，查 `linearTilingFeatures` 的 4 个位 + `vkGetPhysicalDeviceImageFormatProperties(LINEAR)` | 记录；缺 `COLOR_ATTACHMENT_BIT` 的格式**预先**标记为必然 shadow | R41-12 |
| **6** | `OSType → MTLPixelFormat` 表生成：对 §3.4.3 的候选集逐个 `CVPixelFormatDescriptionCreateWithPixelFormatType`，与预期值表 diff | 记录 diff；候选集里有查不到的 `OSType` → 从候选集移除并记录 | R41-13 |
| **7** | **`'b3a8'` 专项**：取它的描述字典并核对 §3.5.1 的九项；核对 plane 0 = 32 bpp、plane 1 = 8 bpp | 记录。不符 → §3.5.3 的 R41-14 固定路径失效，退回 §2.3 的通用判定 | S-003 |
| **8** | **自环测试**：创建一张 64×64 `'BGRA'` surface → `measure` → `check_geometry` → `import_plane_as_texture` → 断言模式是 **in-place** | **致命**。这是「本模块到底能不能工作」的最小证明；我们自己创建的 surface 走不到 in-place，说明 §3.1.2 的对齐逻辑错了 | R41-7 的反面 |
| **9** | **`mach_vm_remap` 别名性自检**（§5.3 条件 d）：分配两页、remap 成连续区、双向写验证 | 记录。失败 → `addressRanges` 维持 B 档 | S-012 |
| **10** | `vm_page_size` 读出并与第 2 项比较，记录 `page_size >= minImportedHostPointerAlignment` 是否成立 | 记录 | §5.3 条件 e |
| **11** | `IOSurfaceAllowsPixelSizeCasting` 对第 8 项创建的 surface 返回真（§3.1.4 的预期） | 记录。为假 → 本构建的 bit 16 结论不成立，§3.1.4 要重查 | 结论 6 |
| **12** | `MessageSink` 已接上，且第 8 项的创建过程被专用串行段包住、通告被捕获（而不是落 stderr） | **致命** | R41-6、`40` §6.6 |

### 8.2 验收条目

每条给出可执行的判据。标签列是**当前**状态，不是目标。

| # | 验收 | 判据 | 当前标签 |
|---|---|---|---|
| **V-01** | 自检 12 项全部通过并落盘 | 自检报告存在，第 1/2/4/8/12 项为 pass | `BLOCKED`（要开机） |
| **V-02** | 我们创建的 surface 在 `'BGRA'` / `'RGhA'` 两个格式上都走 **in-place** | `ImportMode::is_direct()` 为真，`reasons[]` 为空 | `BLOCKED` |
| **V-03** | 导入一张**故意不对齐**的 surface，两轴各自报出正确取值，`reasons[]` 恰好含 `base-misaligned` | 轴 1 = `CopiedHostPages`，轴 2 不受牵连（R41-10） | `BLOCKED` |
| **V-04** | **归因不串台**：并发 import 8 张 surface，其中 4 张故意不对齐 | 8 张各自报出正确的两轴取值，不互相污染。**这就是 `50` 分册的 T-16**，本册与它共用同一个测试 | `BLOCKED` |
| **V-05** | `'b3a8'` 的两 plane 往返：建 surface → 作为 attachment 渲染 → 拆回两 plane → 读回比对 | 逐像素一致（10 位 RGB 与 8 位 alpha 分别比对）；模式为 **shadow**；`reasons[]` 含 `format-needs-merge` | `BLOCKED` |
| **V-06** | D101 的每条校验各有一个否定用例 | 8 个 `GeometryFault` variant 各被触发一次且被拒绝；**无一例 panic、无一例溢出** | 可在宿主上做（纯逻辑），`INFERRED` |
| **V-07** | lock 时序（D104）：跨进程一个写者 + 一个读者，读者不得看到撕裂帧 | 读者每帧读到的要么是第 N 帧要么是第 N+1 帧的完整内容，不混 | `BLOCKED`（U-04 未关闭，`50` 已标 Gate 2） |
| **V-08** | R41-30：texture 被提前释放时**不**提前 unlock | 释放 texture 后 GPU 仍在写，读者看到的 seed 不前进 | `BLOCKED` |
| **V-09** | `deallocator` 恰好调用一次，且在 `KeepAlive` 释放时而非 `-dealloc` 时 | 计数器 == 1；调用时刻晚于 `-dealloc`（用时间戳断言）；失败路径上也调用一次 | 可在宿主上做（需 ObjC），`INFERRED` |
| **V-10** | 跨 generation：helper 崩溃后客户端重新 import 同一 surface，画面内容**没丢** | 重新 import 后第一帧的内容 == 崩溃前最后一帧（D82） | `BLOCKED` |
| **V-11** | R41-33：带着写锁崩溃后，新 generation 在超时内放弃该 surface 而不是挂死 | 超时触发，记 `m2vu-surface-orphaned-lock`，其余 surface 正常恢复 | `BLOCKED`（S-013 未关闭） |
| **V-12** | `MTLSharedTextureHandle` 往返：编码 → 跨进程 → 解码 → 取回纹理 | 内容一致；**且**一个伪造的 token 被第 2 层拒绝；**且**一个仅有正确 `sid` 但 token 错的请求被拒绝（R41-20） | `BLOCKED` |
| **V-13** | `initWithCoder:` 的健壮性：缺键、类型错、长度错、未知版本各一个用例 | 四种都返回 `nil`，无 crash，**无 `decodeObjectForKey:` 的使用**（静态检查） | 可在宿主上做，`INFERRED` |
| **V-14** | 上屏：framebuffer 内存被导入成 `B8G8R8A8_UNORM` linear image 并被 Vulkan 写入 | 屏幕出现预期图案；带宽符合 §7.3 的量级 | `BLOCKED`（要开机 + `11` 分册的 framebuffer 先跑起来） |
| **V-15** | **无最坏格**：整套测试跑完，`is_worst_cell()` 为真的次数 == 0 | 计数为 0；非 0 则按 R41-5 定位到具体 surface | `BLOCKED` |

### 8.3 与其他分册验收的共用关系

| 本册条目 | 与谁共用 |
|---|---|
| V-04 | `50-IPC-HELPER.md` 的 T-16（同一个测试） |
| V-07 / V-08 | `50` 的 Gate 2 / U-04 |
| V-10 / V-11 | `50` §6.3 的崩溃恢复 11 步 |
| V-14 | `11-KERNEL-DISPLAY.md` 的 framebuffer 验收（本册是它的消费侧） |
| 自检第 5、6 项 | `40-RUNTIME-VULKAN.md` §8.4 的格式表生成（复用同一次产物） |
| 自检第 2、4 项 | `60-CAPABILITY-MATRIX.md` C-06 的格式实测 |

---

## 9. 未解决项清单

列在这里的都是**尚未关闭**的项。每行给查清方法，并标明能否用 `91-RUNTIME-EVIDENCE.md` 的 CI 通道取（`macos-26-intel` 运行器：macOS 26.6.1 / 25G76，SIP 已关闭，跑着真 AppleParavirtGPU，可随时重建）。用该通道取得的结论按 `91` §0.1 的分级标 **`TESTED(25G76)`**，不是 `TESTED`。

### 9.1 清单

| 编号 | 事项 | 影响 | 查清方法 | CI 通道 | 标签 |
|---|---|---|---|:---:|---|
| **S-001** | `IOSurfaceGetBaseAddressOfPlane` 的返回值在同一 surface 的多次 lock 之间是否稳定；framework 是否每次 lock 都把 `IOSurfaceLockResult +0x00`（per-client 映射基址，`12` §1.5.2）回写到 getter | 决定能否省掉 R41-3 的每次重读。**不阻断实现**（R41-3 已按最坏情况写） | 运行器上：建一张 surface，lock/unlock 20 轮，每轮记 base；再在另一进程并发 lock 同一 surface，看本进程的 base 是否变 | ✅ | `BLOCKED` |
| **S-002** | `kIOSurfaceCacheMode` 落到 `IOSurface` 的哪个 ivar。`12` §2.2 已证 `parse_properties`（`[S] +0x42B0`）对标志字 `+0x3D8` 没有任何访问，所以它不在那里 | 本项目一律不设该键，用默认值。**不阻断** | 两条路：(a) 反编译 `[S] parse_properties +0x42B0`，找 `kIOSurfaceCacheMode` 字面量的消费点（**二进制在仓库内，可关**）；(b) 运行器上用不同 cache mode 建 surface，比较 `ioreg -c IOSurfaceRoot` 的属性转储 | ✅（(b)） | `BLOCKED`，但(a) 属「可关，未做」 |
| **S-003** | **`'b3a8'` 就是 `RGB10A8_2P_XR10`** 的确证，以及 `_sRGB` 变体（raw 551）是否共用同一 `OSType` | 本册结论 3、结论 5、R41-14 全建在它上面。错了则 §3.5.3 的固定路径失效，退回 §2.3 的通用判定（**仍能工作，只是多一次判定**） | 运行器上三步：(1) `CVPixelFormatDescriptionCreateWithPixelFormatType(NULL, 0x62336138)` 取字典，核对 §3.5.1 的九项；(2) `IOSurfaceCreate` 一张 `'b3a8'` surface，读 `IOSurfaceGetPlaneCount` / 逐 plane `BytesPerElement`；(3) 在它上面用 `MTLPixelFormatRGB10A8_2P_XR10`（550）与 551 各建一次 `MTLTexture`，看 APV 是否接受 | ✅ **最该先做的三条之一** | `INFERRED`（强证据） |
| **S-004** | Lavapipe 的 `minImportedHostPointerAlignment` 实际值，以及 `vkGetMemoryHostPointerPropertiesEXT` 给出的 memory type mask 是否与 linear image 的 `memoryTypeBits` 有交集 | **决定整个 no-copy 导入路径是否成立。** 不成立则所有 surface 都走 copy，每帧全画面拷贝 | 启动自检第 2 项即是。先在**宿主**上用一份 macOS x86_64 的 Lavapipe 构建跑一个 20 行的查询程序；目标 guest 上重跑一次确认 | ⚠️ 需先把 Lavapipe 构建产物放上运行器（`70-BUILD-PACKAGE.md` 的产物） | `BLOCKED` **最该先做的三条之一** |
| **S-005** | 对 R41-12 最小闭包里 6 个格式的 `linearTilingFeatures` 四个位 + `vkGetPhysicalDeviceImageFormatProperties(LINEAR, usage)` | 决定哪些格式**必然** shadow。`B8G8R8A8_UNORM` 缺 `COLOR_ATTACHMENT_BIT` 会直接影响 §7.3 的上屏路径 | 与 S-004 同一个程序，多查 6 个格式。`40` §8.4 已要求对全部 301 个格式实测，本册复用那次产物 | ⚠️ 同 S-004 | `BLOCKED` **最该先做的三条之一** |
| **S-006** | Metal 的 pixel-size casting 在**位宽不等**时的真实行为（§3.1.4 假定它只允许等尺寸重解释） | 若 Metal 实际允许不等尺寸，本项目会比 Metal 严格（即 `40` §7.3 里 basis = `metal-takes` 的那类缺陷） | 运行器上：对一张 `'BGRA'`（4 字节/元素）surface，用 `R16Unorm`（2 字节）与 `RGBA16Float`（8 字节）各建一次纹理，看 APV 接受还是 assert | ✅ | `INFERRED` |
| **S-007** | `'w30r'`（`kCVPixelFormatType_30RGBLEPackedWideGamut`）落到 `BGR10A2Unorm`（94）还是 `BGR10_XR`（554） | 宽色域路径。不在首帧关键路径上 | 运行器上取它的格式描述字典（`ComponentRange` 是 `WideRange` 还是 `FullRange` 即可区分），再用两个 Metal 格式各建一次纹理 | ✅ | `BLOCKED` |
| **S-008** | 能否在目标 guest 上构造一个与 WindowServer 等价的沙箱环境来跑 §4.2 的 U-01 探针 | 决定 U-01 的探针结论是否可信。用非沙箱进程当 peer 只证明了「不受约束时可以」 | 读 `/System/Library/Sandbox/Profiles/` 下 WindowServer 的 profile，用 `sandbox_init_with_parameters` 或 `sandbox-exec` 套同一份 profile 起探针 peer | ✅（SIP 已关，profile 可读） | `BLOCKED` |
| **S-009** | `MTLResourceAddressRangeArray` 的读接口：类名、selector、每项字段的编码与单位（字节？页？） | §5.3 条件 a。**阻断 `addressRanges` 从 B 档升档** | 运行器上 `objc_copyClassNamesForImage(Metal.framework)` 全量遍历 + 对该类 dump `class_copyMethodList` / `class_copyIvarList`。`91` §5.3 已证这条通道可用（R-005 就是这么关的） | ✅ | `BLOCKED` |
| **S-010** | 系统路径（WindowServer / CoreAnimation / RenderBox）**是否真的调** `replaceBackingWithRanges:`，以及传进来的区间粒度是否页对齐 | §5.3 条件 b。**决定 §5 值不值得实现。** `60` §3 已把分散后备标为 `SYS`（不在 WindowServer 首帧关键路径） | 运行器上用 `DYLD_INSERT_LIBRARIES` 或 `method_exchangeImplementations` 拦该 selector，记录调用方与实参；跑一轮登录 + 桌面操作。与 `60` C-07 的格式 trace 是同一次采集 | ✅ | `BLOCKED` |
| **S-011** | 上游 `rebind_bytes_no_copy` 的精确签名、前置条件，以及它对「在途命令缓冲正在用旧后备」的处置 | §5.3 条件 c。也影响 R41-3 的重绑路径 | `cargo doc -p metal2vulkan-runtime --open`，读该方法的 rustdoc（`40` §0 的「读法」：每个 item 的 rustdoc 都注明其 Metal 对应物与差异） | ❌ 不需要，**免费，应最先做** | `BLOCKED` |
| **S-012** | `mach_vm_remap(copy = FALSE, VM_INHERIT_SHARE)` 在同一 task 内确实产生**别名**而非 COW | §5.3 条件 d。别名不成立则 §5 整节作废 | 启动自检第 9 项即是。可以在**任何** macOS 上跑（与 guest 无关），几十行 | ✅（或本地任意 Mac） | `BLOCKED` |
| **S-013** | 持有 IOSurface 写锁的 task 死亡时，内核是否强制解锁 | R41-33 的处置（超时后放弃该 surface）是在它未知时的保守选择。若内核强制解锁，可以改成直接重用 | 两条路：(a) 反编译 `[S] IOSurfaceClient::unmap +0x11BE2` 与 `IOSurface::unlockSurface +0x969E` 的调用链，看 user client 的 `clientClose` / `free` 路径是否经过它（**二进制在仓库内，可关**）；(b) 运行器上：一个进程 lock 后 `SIGKILL`，另一进程观察能否 lock | ✅（(b)） | `BLOCKED`，(a) 属「可关，未做」 |
| **S-014** | WindowServer 从合成到 framebuffer 实际有几次拷贝，以及它建了哪些 surface（格式、尺寸、plane 数） | §7.3 的带宽预算与 R41-36。也直接喂 `60` C-07 | 运行器上 `ioreg` + 对 `IOSurfaceCreate` 做 interpose，记录 WindowServer 建的每张 surface 的 properties 字典 | ✅ | `BLOCKED` |
| **S-015** | `IOSurfaceCreateMachPort` / `LookupFromMachPort` 在 WindowServer 沙箱下是否可用，需要什么 entitlement | §4.1.3。不可用则按备选顺序退（XPC 包装 → kext 转交 → 同进程）。**这是 `50` 分册 U-03 / Gate H-3 的同一项**，本册只补备选顺序 | 目标 guest 探针（`50` 已定）。运行器上可以先测「非沙箱 ↔ 非沙箱」这一半 | ⚠️ 部分 | `BLOCKED` |
| **S-016** | `IOSurfaceGetSeed` 的单调性与回绕：只读 lock 是否让 seed 前进；seed 是 32 位，回绕周期多长 | shadow 模式的重算判据。若只读 lock 也前进，shadow 会被无谓重算；若会回绕，需要配一个单调计数器 | 运行器上：lock/unlock 若干轮，分别用只读与读写 flags，记 seed 序列 | ✅ | `BLOCKED` |
| **S-017** | `IOSurfaceGetBaseAddressOfPlane` 等 getter 在**未 lock** 时是否返回有效指针 | 影响 `measure()` 能否在 lock 之前跑（§2.3 的 `[0]` 步目前假定可以） | 运行器上：不 lock 直接取 base 并读一个字节，看是否 `SIGBUS` | ✅ | `BLOCKED` |
| **S-018** | IOSurface attachment（selector 9/10/11）的大小与速率上限 | DoS 面。`50` §2.6 对 wire 消息有配额，但 attachment 是直接打内核的，不经我们的配额 | 运行器上：对一张 surface 反复 `IOSurfaceSetValue` 大块 `CFData`，观察内核内存与是否有上限报错；并反编译 `[S] s_set_value` 的长度检查 | ✅ | `BLOCKED` |
| **S-019** | `IOSurfaceGetPropertyAlignment(kIOSurfacePlaneOffset)` 是否返回有意义的值（两 plane 格式里 plane 1 的 offset 要不要对齐） | §3.5.3 的创建侧参数。目前写作「读出来的，不要算」，但创建时我们得给一个值 | 启动自检第 3 项即是。再用 `IOSurfaceAlignProperty` 对一个故意不对齐的值做一次往返 | ✅ | `BLOCKED` |
| **S-020** | 本册全部结论都是静态分析或公开 ABI 推导，**无一条 `TESTED`** | 全册 | §8.2 的 15 条验收。其中 V-06、V-09、V-13 可在宿主上做，其余要开机 | 部分 ✅ | `BLOCKED` |

### 9.2 排序建议：最该先查的三条

> **第一梯队（S-011、S-004、S-005）。** 这三条的共同点是：**成本极低而且会改变设计**。
>
> 1. **S-011** 零成本（读一次 rustdoc），而 `rebind_bytes_no_copy` 同时是 §5 的全部基础和 R41-3 的重绑路径。它的前置条件如果比我们假定的严（例如要求无在途命令缓冲），R41-3 就得改成「延迟重绑」。**应该在写任何代码之前做。**
> 2. **S-004** 决定 no-copy 导入是否成立。它为假意味着本册的主路径从 in-place 退成 copy，每帧全画面拷贝，`60` §5.1 的首帧最小集要重算。**一个 20 行的 Vulkan 查询程序。**
> 3. **S-005** 决定 `B8G8R8A8_UNORM` 能不能当 linear attachment。它为假意味着 §7.3 的上屏路径要多一张 shadow，`11` 分册「Lavapipe 直接渲进 framebuffer 内存（零拷贝）」那条优势就没了。**与 S-004 同一个程序。**
>
> **第二梯队（S-003、S-009、S-010）。** 都能用 `91` 的 CI 通道一轮取完，且各自解锁一块功能：S-003 把结论 3/5 从 `INFERRED` 升到 `TESTED(25G76)` 并锁定登录屏路径；S-009 + S-010 一起决定 §5 是实现还是维持 B 档。
>
> **第三梯队**：其余。S-001、S-016、S-017 是优化前提（能省掉多少重复工作），不影响正确性，因为本册已按最坏情况写。

### 9.3 本册没有引入新的 `BLOCKED`

一条值得说明的纪律（`00-OVERVIEW.md` §7 补充规则 4：「没查」不等于「被阻断」）。

本册的 20 条里，**`S-002` 的 (a) 路与 `S-013` 的 (a) 路属于「可关，本轮因时间未做」而不是真阻断**（二进制 `[S]` 在仓库内，反编译即可）；**`S-011` 属于「免费，应最先做」**（读上游文档）。清单里把这三条单独标注了，不与真正缺样本的项混为一谈。

真正缺东西的是：缺 Lavapipe 在 macOS x86_64 的构建产物（S-004、S-005，由 `70-BUILD-PACKAGE.md` 交付）、缺目标 guest（S-020 与多数验收）、缺 `IOSurface.framework` 的 x86_64 样本（S-001、S-017 的静态路，但两者都有运行期替代路）。

---

## 10. 与其他分册的接口

### 10.1 本册消费什么

| 来源 | 本册用到的 |
|---|---|
| `12-KERNEL-IOSURFACE.md` | §1.5 的 `IOSurfaceLockResult` 布局与 20 plane 硬上限（R41-2）、§1.5.4 的交接、§2.2 的 ivar 表与标志位表（结论 6、§4.5.1）、§2.3 的 plane 表达（R41-1、R41-11）、§2.4 的内存来源、§1.4 的 selector 表（§4.1.1）、§3.4 的 `find_surface`（§4.5.1）、`isDisplayable()` 恒 0（§7.1） |
| `40-RUNTIME-VULKAN.md` | §2.3 的资源对象清单、第 4 节第 1/2/6 项的范围划分、§4.1 的 runtime 扩展（`HostMemory` 三条可用退路、`used_resources`、`rebind_bytes_no_copy`）、§6 的 `DeviceOptions`、§7.1 的 degradation 解码规则、§8 的格式表与 §8.4 的生成纪律 |
| `22-OBJC-DESCRIPTORS.md` | §4.1 的 texture descriptor 字段、§4.2 的 `iosurface` / `addressRanges` / `deallocator` / `contents`、R11（自己重测）、R26、R41/R42（block 时机）、§4.25（`MTLSharedTextureHandle`） |
| `50-IPC-HELPER.md` | D82、D99、D100、D101、D102、D103、D104、D105、D109、C-4、Gate H-2/H-3、U-01、U-03、U-04、T-16 |
| `11-KERNEL-DISPLAY.md` | §2.5 的 framebuffer 后备、§3.3 的 `clientMemoryForType(110)`、§3.4.1 的 `kIOMemoryKernelUserShared`、§3.5.1 的「没有 swap selector」、§4.1 的 `DisplayPipeSupported` |
| `21-OBJC-OBJECT-FAMILY.md` | §6.5 的 resource 类决定、§9.5 的 block 责任归属、§9.6 的线程契约 |
| `20-OBJC-DEVICE.md` | §5.2 的 limits 表（四个对齐 limit）、§8.5/§8.6 的 Apple IOSurface 调用集合 |
| `60-CAPABILITY-MATRIX.md` | §2.2 的 Lavapipe 能力位、§3 的格式与资源行、§5.1 的 WindowServer 实测事实 |
| `91-RUNTIME-EVIDENCE.md` | §0.1 的 `TESTED(25G76)` 分级、§1 的运行器环境、§5.3 的「可以 `IOServiceOpen`、可以遍历 ObjC 元数据」这条通道 |

### 10.2 本册产出什么给别人

| 去向 | 本册给出的 |
|---|---|
| `22-OBJC-DESCRIPTORS.md` | `iosurface` 字段的导入路径（§2、§3）与 `CFRetain` 时点（R41-25）；`addressRanges` 从 B 档升档的全部条件（§5.3）；`deallocator` 的自建责任与调用点（§6.2）；`MTLSharedTextureHandle` 的序列化格式与解码实现（§4.6） |
| `50-IPC-HELPER.md` | D100/D101 的实现（§3.6）、D103 的两轴判定与归因（§2）、D104 的时序实现（§6.4）、D82 的三条要求（§6.5）；**以及一条新结论：IOSurface 路径不依赖 U-01（§4.2.3），U-01 的影响面比该分册写的小** |
| `60-CAPABILITY-MATRIX.md` | §3.5.2 的更正建议（`'b3a8'` 不是 YCbCr，它就是登录路径那个 `RGB10A8_2P_XR10` 的 surface 侧形态）；`RGB10A8_2P_XR10` 必然 shadow 的结论与每帧代价（§3.5.3）；最坏格计数作为已知损失的来源（R41-5） |
| `11-KERNEL-DISPLAY.md` | framebuffer 内存的导入要求（R41-34）与上屏那次拷贝的代价（§7.3、R41-35） |
| `20-OBJC-DEVICE.md` | 四个对齐 limit 的取值约束（R41-9） |
| `70-BUILD-PACKAGE.md` | 本册需要 Lavapipe 构建产物才能关 S-004/S-005，这两条是 `70` 的下游依赖 |
| `80-TEST-HARNESS.md` | §8.2 的 15 条验收；其中 V-06/V-09/V-13 可钉在宿主层，其余需要 guest |
| `90-EVIDENCE-INDEX.md` | §8.1 的 12 项自检产物 |
