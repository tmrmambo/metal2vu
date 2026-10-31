# macOS Tahoe 26.7.2 x86_64 Metal 注册与设备创建合同

> [!NOTE]
> 本文的注册链结论（`MetalPluginName`、两个 bundle 目录、`_MTLDevice` class gate、`@20@0:8I16`）
> 经独立复核**全部正确**，继续有效，并在 `docs/spec/20-OBJC-DEVICE.md` 与 `10-KERNEL-ACCELERATOR.md` 中细化到字段级。
>
> 两处标注需更正：
> - 第 1.2 节把两个 `*MTLDriver_decompressed` 列为 25G325 样本并标 `KNOWN`。它们的 SDK 是 **26.6.1**，不是 25G325。所支撑的 encoding 结论与小版本无关，可继续用，但样本构建标注要改。
> - 第 8.3 节的 B-009 trust gate 实验，在研发期 SIP/AMFI 关闭的配置下不再是前置条件。见 `docs/spec/00-OVERVIEW.md` 第 2.4 节。

- **[KNOWN]** 目标版本：macOS Tahoe 26.7.2，build 25G325，x86_64；来源为第 1.1 节 build 元数据。  
- **[KNOWN]** 范围：B-001、B-002、B-003。  
- **[BLOCKED]** 状态：静态合同已闭合；installed SystemOS 样本与目标机动态验收仍有明确阻断。

## 0. 结论与边界

- **[KNOWN]** B-001 的 guest 用户态静态链已经闭合到 `IOServiceOpen(..., type=5, ...)`：`MTLCopyAllDevices @ Metal+0x1632` 调用 `MTLDeviceArrayInitialize @ Metal+0x12ec7a`，后者进入 `_MTLRegisterDevices @ Metal+0x1d980d`；设备基类最终在 `IOAccelDeviceCreateWithAPIProperty @ IOAccelerator+0xf60` 调用 type 5 的 `IOServiceOpen`。绝对地址和逐级参数见第 3 节。
- **[KNOWN]** B-002 的发现合同已经闭合：service 属性键是 `MetalPluginName` 和可选的 `MetalPluginClassName`；bundle 候选严格按 `/Library/GPUBundles/<name>.bundle`、`/System/Library/Extensions/<name>.bundle` 的顺序查找；类由 `-[NSBundle classNamed:]` 或 `-[NSBundle principalClass]` 取得，并且必须是 `_MTLDevice` 的子类。直接代码证据为 `Metal+0x1d89fb`、`libsystem_sandbox+0x1270` 和 `libsystem_sandbox+0x143b`。
- **[KNOWN]** B-003 的 x86_64 ABI 已闭合：framework 基类、Intel device、AMD base device 和 AMD GFX10 device 的方法表都给出 `@20@0:8I16`；framework 调用点把 `IOIteratorNext` 返回的 32-bit service name 放入 `EDX`，而不是把 `IOServiceOpen` 返回的 connection 传给 plugin。方法表和调用点见第 5 节。
- **[BLOCKED]** 本轮取得的是 25G325 安装资产内 x86_64 BaseSystem cache 的 Metal/IOAccelerator 映像，不把它冒充 installed SystemOS cache。`/System/Library/PrivateFrameworks/IOGPU.framework/Versions/A/IOGPU` 只在既有 full-system map 中出现；其 exact Mach-O、UUID 和 SHA-256 尚未取得。最小采集步骤见第 8.1 节。
- **[BLOCKED]** 本轮没有在 25G325 x86_64 guest 中执行 Metal probe，因此没有任何 `TESTED` 结论。第 8.2 节给出一次运行即可核对 B-001 至 B-003 的最小 trace。
- **[KNOWN]** 本合同只描述 macOS guest 内 `Metal.framework -> IOAccelerator.framework -> IOKit user client` 的行为；没有把 Windows、Linux、QEMU、宿主 GPU 或宿主 Vulkan 的行为写进运行合同。该边界由本节所列 guest Mach-O 调用地址限定。

## 1. 样本与来源链

### 1.1 25G325 来源证明

| 标签 | 项目 | 值 | 证据 |
|---|---|---|---|
| **[KNOWN]** | build 元数据 | `ProductBuildVersion=25G325`、`ProductVersion=26.7.2` | `C:\Users\viola\Documents\KVM MacOS\SharedSupport.dmg!/Shared Support/com_apple_MobileAsset_MacSoftwareUpdate/d3cc6643f7010f6ec14cc728f4a47a7c7644e8a5.zip!/AssetData/boot/SystemVersion.plist`；抽取件 SHA-256 `A4B73DEF6ED2AAB787378535418D9A2D1304F3D5D809FDDFD3C53DC286373CAC` |
| **[KNOWN]** | x86 BaseSystem patch | `C:\Users\viola\Documents\KVM MacOS\SharedSupport.dmg!/Shared Support/com_apple_MobileAsset_MacSoftwareUpdate/d3cc6643f7010f6ec14cc728f4a47a7c7644e8a5.zip!/AssetData/payloadv2/basesystem_patches/x86_64BaseSystem.dmg`，BXDIFF50 full-replacement，SHA-256 `35745579C8FBC20ABBD98E5954B70BE22F329DF199D06429604A042F8765827E` | patch header `ControlSize=0`；只重建该 DMG，没有展开 18 GB update ZIP |
| **[KNOWN]** | 重建 BaseSystem DMG | 1,464,270,504 bytes；SHA-256 `642E6148288527C51639D1B08C7F0B5A8CB4A68AEC2AC6DA3C78CF1723C5119A` | BXDIFF50 `PatchedFileSize=1,464,270,504` 与输出长度一致 |
| **[KNOWN]** | x86 cache primary | UUID `B1090D84-48D4-3D45-94E6-A5C7F9CE7DE7`；SHA-256 `353B861E2354E0D426E572BB2BB99C5E49D95D2CF8EE6C74FBBCD7E17F94263E` | BaseSystem `/System/Library/dyld/dyld_shared_cache_x86_64` |
| **[KNOWN]** | x86 cache subcache | UUID `ADDD15FF-C4C5-36EC-8ED1-88BB9F5C8F49`；SHA-256 `9348C71FF3A09B60AD8302601F540D1368693C06C425749D1F39F0E96949CF8C` | BaseSystem `/System/Library/dyld/dyld_shared_cache_x86_64.01` |

### 1.2 二进制样本表

| 标签 | 逻辑路径 / 本地样本 | 架构 | Mach-O UUID | SHA-256 | 说明 |
|---|---|---|---|---|---|
| **[KNOWN]** | `/System/Library/Frameworks/Metal.framework/Versions/A/Metal`; scratch raw extraction | `x86_64` / subtype `3` | `FDB3FD2C-840A-3FC3-81FB-C524F891F642` | `9BAB47CD9A7E11E15A17486C8E4BA2775CDDC1A705A6F60A39C0A87D9F598C9D` | 25G325 BaseSystem cache image；source version `373.7.1.0.0` |
| **[KNOWN]** | `/System/Library/PrivateFrameworks/IOAccelerator.framework/Versions/A/IOAccelerator`; scratch raw extraction | `x86_64` / subtype `3` | `4FDBB3F6-9AA3-352B-87ED-57161AA64D1F` | `7EF85F8415B13992A34FDDDF0B523D8D4DA366564E93D78187D8E0BC5BF01FA2` | 25G325 BaseSystem cache image；source version `487.4.4.0.0` |
| **[BLOCKED]** | `/System/Library/PrivateFrameworks/IOGPU.framework/Versions/A/IOGPU` | `x86_64` | 未取得 | 未取得 | `C:\Users\viola\Documents\KVM MacOS\metal_drivers\dyld_shared_cache_x86_64.map.txt`（SHA-256 `9E2BAB27E0478A03D4728E0572B24BEFF6F619A1A07307B0537537E9BC80ECDD`）只证明 full-system cache 预期含该路径和 `__TEXT 0x7FF90756E000..0x7FF9075BAECC`；字符串/map 不能替代 Mach-O 证明 |
| **[KNOWN]** | `C:\Users\viola\Documents\KVM MacOS\metal_drivers\AppleIntelICLGraphicsMTLDriver_decompressed` | `x86_64h` / subtype `8` | `251E3AE2-1396-3AD1-974A-422AE954B85A` | `2D21F64F6361045CE83F9BB0CE9D4AA56E452FAB484066709673A1335F06141E` | method-list 直接证据样本 |
| **[KNOWN]** | `C:\Users\viola\Documents\KVM MacOS\metal_drivers\AMDRadeonX6000MTLDriver_decompressed` | `x86_64h` / subtype `8` | `774E6DC1-A6B4-381B-AFD9-29C8E813DE95` | `C0CEA683B94A5D645CDE7FB50FAA917B02AB35BDAB1A697D847E4B7678E1DADB` | method-list 直接证据样本 |

- **[KNOWN]** Metal 与 IOAccelerator 的 SHA-256 是 `ipsw dyld extract` 重建出的 standalone Mach-O 的哈希，不声称等于 cache 内非连续 segment bytes 的哈希；UUID 是 Mach-O `LC_UUID`，用于把 RVA 与样本绑定。
- **[KNOWN]** 下文 `Metal+RVA` 的 image base 是 `0x7FF80B179000`，`IOAccelerator+RVA` 的 image base 是 `0x7FF80B170000`；绝对 VA 是该 BaseSystem cache 的 unslid VA，installed SystemOS 需要以 UUID+RVA 重定位。
- **[KNOWN]** 本轮没有 IDA MCP 接口可用，因而没有创建或改写 IDB；所有新地址来自只读 cache/Mach-O 解析和 x86_64 指令反汇编，既有 driver IDB 未被打开或覆盖。

## 2. 相关导出与内部入口

| 标签 | 映像 | 符号 | BaseSystem unslid VA / RVA | 合同用途 |
|---|---|---|---|---|
| **[KNOWN]** | Metal | `_MTLCopyAllDevices` | `0x7FF80B17A632` / `+0x1632` | 返回当前 device array 的 `copy` |
| **[KNOWN]** | Metal | `_MTLCreateSystemDefaultDevice` | `0x7FF80B190A91` / `+0x17A91` | 选择并返回 retained default device 或 `nil` |
| **[KNOWN]** | Metal | `_MTLCopyAllDevicesWithObserver` | `0x7FF80B1A12AA` / `+0x282AA` | 安装 observer 并返回当前 snapshot |
| **[KNOWN]** | Metal | `_MTLRemoveDeviceObserver` | `0x7FF80B2A883C` / `+0x12F83C` | 从 notifier array 移除 observer |
| **[KNOWN]** | Metal | `_MTLAddDevice` | `0x7FF80B17B3B0` / `+0x23B0` | 校验、过滤、append 和通知 |
| **[KNOWN]** | Metal | `_MTLRegisterDevices` | `0x7FF80B35280D` / `+0x1D980D` | private/non-external registration entry |
| **[KNOWN]** | IOAccelerator | `_IOAccelDeviceCreateWithAPIProperty` | `0x7FF80B170F60` / `+0xF60` | 打开 type-5 user client 并建立 `IOAccelDeviceRef` |
| **[KNOWN]** | IOAccelerator | `_IOAccelDeviceCreate` | `0x7FF80B17321A` / `+0x321A` | 以 `APIProperty=NULL` 转调上一函数 |
| **[KNOWN]** | IOAccelerator | `_IOAccelDeviceGetConnect` | `0x7FF80B1712EF` / `+0x12EF` | 类型正确时返回 `IOAccelDeviceRef+0x14` 的 connection，否则返回 0 |
| **[KNOWN]** | libsystem_sandbox | `_gpu_bundle_find_trusted` | `0x7FF80C4D0270` / `+0x1270` | 生成并验证两个固定 bundle path |
| **[KNOWN]** | libsystem_sandbox | `_gpu_bundle_is_path_trusted` | `0x7FF80C4D043B` / `+0x143B` | rootless/trusted-cache 判定 |
| **[KNOWN]** | SkyLight | `_SLSCreateDefaultMetalDevice` | `0x7FF8069AC494` / `+0x40F494` | CoreGraphics re-export 的实际 default selector |
| **[KNOWN]** | SkyLight | `_SLSDisplayCopyCurrentMetalDevice` | `0x7FF8069AC754` / `+0x40F754` | display accelerator port 到 MTLDevice 的映射 |

- **[KNOWN]** Intel/AMD 两个 plugin 样本没有被 framework 路径调用的 C factory；framework 在 `Metal+0x1D89FB..+0x1D8B94` 取得 Objective-C class，并在 `Metal+0x1D958F..+0x1D95DC` 执行 `alloc`/`initWithAcceleratorPort:`/`MTLAddDevice`。

## 3. 编号设备创建链

1. **[KNOWN]** `_MTLCopyAllDevices @ Metal+0x1632` 和 `_MTLCreateSystemDefaultDevice @ Metal+0x17A91` 都先调用 `MTLDeviceArrayInitialize @ Metal+0x12EC7A`；`MTLCopyAllDevices` 的 call site 是 `0x7FF80B17A63D`，default 的 call site 是 `0x7FF80B190A9F`。
2. **[KNOWN]** `MTLDeviceArrayInitialize` 的 dispatch-once block `Metal+0x2B0BD` 创建串行队列 `com.Metal.DeviceArray`、空 `NSMutableArray` device array、notifier array 和 `com.Metal.DeviceNotifyQueueDispatch`；对应 stores 位于 `0x7FF80B1A40E5..0x7FF80B1A4120`。
3. **[KNOWN]** `MTLDeviceArrayInitialize` 在 `0x7FF80B2A80DD` tail-jump 到 `_MTLRegisterDevices @ Metal+0x1D980D`；`_MTLRegisterDevices` 用 unfair lock 确保只发布一个 `MTLIOAccelServiceGlobalContext`，地址范围 `0x7FF80B35280D..0x7FF80B3528C3`。
4. **[KNOWN]** `-[MTLIOAccelServiceGlobalContext init] @ Metal+0x1D8C9A` 调用 `IOMainPort(*bootstrap_port, &mainPort)`、`IONotificationPortCreate(mainPort)`，再建立 `com.Metal.DeviceDispatch` queue；错误分别在 `0x7FF80B351CDD` 和 `0x7FF80B351D72` 后返回 `nil`。
5. **[KNOWN]** 同一 init 在 `0x7FF80B351D4B..0x7FF80B351D72` 精确执行 `IOServiceMatching("IOAccelerator")` 和 `IOServiceAddMatchingNotification(port, "IOServicePublish", matching, _mtlIOAccelDeviceMatched, self, &iterator)`；没有在这一层按 vendor、PCI ID 或 IOGPU class 收窄。
6. **[KNOWN]** matching notification 返回的初始 iterator 在 `0x7FF80B351DB6..0x7FF80B351E3D` 被立即 drain；每个 `IOIteratorNext` service 先交给 `_getMetalPluginClassForService @ Metal+0x1D89FB`，成功时被保存为 `{unsigned int service, Class deviceClass}` descriptor。后续 publish callback `_mtlIOAccelDeviceMatched @ Metal+0x1D8B94` 对每个 service 调用 `registerService:deviceClass:nil`。
7. **[KNOWN]** `registerService:deviceClass: @ Metal+0x1D8F46` 先按 32-bit service name 去重；class 参数为空时重新执行 plugin lookup。成功后它构造 `MTLIOAccelService`，调用点 `0x7FF80B351FD1..0x7FF80B351FE1`。
8. **[KNOWN]** `-[MTLIOAccelService initWithAcceleratorPort:deviceClass:] @ Metal+0x1D9395` 拒绝 `IOObjectConformsTo(service, "IOServiceCompatibility")` 的对象，retain service，取得 registry ID，并安装 `IOGeneralInterest` notification；直接地址为 `0x7FF80B3523F8..0x7FF80B352478`。
9. **[KNOWN]** service wrapper 在 `0x7FF80B35258F..0x7FF80B3525A5` 对 plugin class 执行 `alloc`，然后以 `EDX=service` 调用 `initWithAcceleratorPort:`；这里的参数仍是 `IOIteratorNext` 返回的 `io_service_t`，尚未是 user-client connection。
10. **[KNOWN]** vendor initializer 调用 framework base `-[MTLIOAccelDevice initWithAcceleratorPort:] @ Metal+0x17CF`；base 在 `0x7FF80B17A813..0x7FF80B17A821` 执行 `IOAccelDeviceCreateWithAPIProperty(service, "Metal")`。
11. **[KNOWN]** `_IOAccelDeviceCreateWithAPIProperty @ IOAccelerator+0xF60` 在 `0x7FF80B170F86..0x7FF80B170F9B` 精确调用 `IOServiceOpen(service, mach_task_self_, 5, &connection)`；x86_64 参数寄存器为 `EDI=service`、`ESI=mach_task_self_`、`EDX=5`、`RCX=&connection`。
12. **[KNOWN]** API property 非空时，IOAccelerator 把最多 16 bytes 的 `"Metal"` buffer 交给 `IOConnectCallStructMethod(connection, 9, api, 16, NULL, NULL)`，call site `0x7FF80B170FCD..0x7FF80B170FFD`；该 selector 的错误在此处被忽略。
13. **[KNOWN]** IOAccelerator 随后要求 selector 2 成功返回至多 `0x258` bytes、selector 0 成功返回 `0x40` bytes；call sites 是 `0x7FF80B17104E..0x7FF80B171076` 和 `0x7FF80B171119..0x7FF80B171141`。selector 7 的 `0x18`-byte 输出是可选的，失败不会使整个 create 失败，call site `0x7FF80B171184..0x7FF80B1711D3`。
14. **[KNOWN]** base init 保存 `IOAccelDeviceRef`、registry ID 和原 service port，并对 service 执行 `IOObjectRetain`，地址 `0x7FF80B17A822..0x7FF80B17A85A`；实际 connection 保存在 `IOAccelDeviceRef+0x14`，由 `_IOAccelDeviceGetConnect @ IOAccelerator+0x12EF` 读取。
15. **[KNOWN]** plugin init 返回非 `nil` 时，service wrapper 在 `0x7FF80B3525B4..0x7FF80B3525E4` 设置 weak device、发送 `_setAcceleratorService:`、调用 `_MTLAddDevice`，然后 release 临时 owner；`NSMutableArray` 成为长期 owner。
16. **[KNOWN]** `_MTLAddDevice @ Metal+0x23B0` 要求对象同时 conform `MTLDevice` 和 `MTLDeviceSPI`，再发送 `initLimits`、`initFeatureQueries`、`initGPUFamilySupport`；断言地址为 `0x7FF80B17B3F7..0x7FF80B17B55F`。
17. **[KNOWN]** `_MTLAddDevice` 的串行 block `Metal+0x8455` 完成 wrapper、`ALLOWED_GPU_IDS` registry-ID allow-list、`_registerInterestNotification` 和 append；真正的 `addObject:` 位于 `0x7FF80B1815BA..0x7FF80B1815D4`，成功后 `0x7FF80B1815F8` 调用 `_MTLNotifyDeviceWasAdded`。

## 4. 精确 plugin discovery 合同

### 4.1 service 属性与 class 选择

| 标签 | 项目 | 精确规则 | 地址证据 |
|---|---|---|---|
| **[KNOWN]** | `MetalPluginName` | 必须由 `IORegistryEntryCreateCFProperty(service, CFSTR("MetalPluginName"), NULL, 0)` 返回 `CFString`；否则该 service 不产生 device class | `0x7FF80B351A1E..0x7FF80B351A4C` |
| **[KNOWN]** | name 编码 | `CFStringGetCString(value, nameBuf, 0xFF, 0x08000100)`；`0x08000100` 是 UTF-8 encoding；代码不检查该函数的 Boolean 返回值 | `0x7FF80B351A4E..0x7FF80B351A6A` |
| **[KNOWN]** | path lookup | 调用 `gpu_bundle_find_trusted(nameBuf, pathBuf, 0x400)`；返回 0 才继续 | `0x7FF80B351A6A..0x7FF80B351A80` |
| **[KNOWN]** | bundle object | 用 `[NSString stringWithUTF8String:pathBuf]` 和 `[NSBundle bundleWithPath:]`；bundle 为 `nil` 时 lookup 返回 `nil` | `0x7FF80B351AB4..0x7FF80B351AED` |
| **[KNOWN]** | `MetalPluginClassName` | 再从同一 service 读取 `CFSTR("MetalPluginClassName")`；若值是 `CFString`，先调用 `[bundle classNamed:value]` | `0x7FF80B351AF2..0x7FF80B351B35` |
| **[KNOWN]** | class fallback | class key 缺失、类型错误或 `classNamed:` 返回 `nil` 时调用 `[bundle principalClass]` | `0x7FF80B351B38..0x7FF80B351B5F` |
| **[KNOWN]** | class gate | 最终 class 必须满足 `[candidate isSubclassOfClass:[_MTLDevice class]]`，否则返回 `nil` | `0x7FF80B351B62..0x7FF80B351B8A` |
| **[KNOWN]** | factory 形式 | 此路径没有 `dlsym` C device factory；class lookup 后由 `objc_alloc` 和 `initWithAcceleratorPort:` 创建设备 | `0x7FF80B35258F..0x7FF80B3525A5` |

### 4.2 固定路径与 trust gate

1. **[KNOWN]** `_gpu_bundle_find_trusted @ libsystem_sandbox+0x1270` 只遍历两个目录，顺序是 `/Library/GPUBundles`、`/System/Library/Extensions`；常量数组位于 `0x7FF8412168D0`。
2. **[KNOWN]** 每个候选严格按 `%s/%s.bundle` 拼接，格式字符串位于 `0x7FF80C4D5422`；`MetalPluginName` 应是 basename，不应包含绝对路径或 `.bundle` 后缀。
3. **[KNOWN]** candidate 必须 `stat` 成功且 `st_mode & S_IFMT == S_IFDIR`，地址 `0x7FF80C4D035E..0x7FF80C4D038E`。
4. **[KNOWN]** `_gpu_bundle_is_path_trusted @ libsystem_sandbox+0x143B` 调用 `rootless_check_trusted_class(path, "KernelExtensionManagement")`；返回 0 被接受，返回 -1 是错误，返回 1 时只有 `__dyld_shared_cache_contains_path(path)` 为真才被转换成成功，地址 `0x7FF80C4D0441..0x7FF80C4D0462`。
5. **[KNOWN]** `gpu_bundle_find_trusted` 成功返回 0；两处都没有合格目录时返回 1；非法空参数、内部错误或输出截断时返回 -1，并设置 `errno`，地址 `0x7FF80C4D02AC..0x7FF80C4D0420`。
6. **[BLOCKED]** `/Library/GPUBundles` 中第三方 bundle 在 25G325 的签名、SIP、rootless 与 cache 外加载结果不能由上述静态代码单独推出；必须执行第 8.3 节的 target trace。

### 4.3 25G325 payload 中的实际实例

| 标签 | provider metadata | service 属性 | 解析出的 bundle / class | 直接证据 |
|---|---|---|---|---|
| **[KNOWN]** | stock x86 PCI `AppleParavirtGPU.kext` 的 `IOKitPersonalities/AppleParavirtGPUControl/AcceleratorProperties` | `MetalPluginName=AppleParavirtGPUMetal`; `MetalPluginClassName=AppleParavirtDevice`; `IOMatchCategory=IOAccelerator`; outer personality `IOPCIMatch=0xEEEE106B` | `/System/Library/Extensions/AppleParavirtGPUMetal.bundle`; `NSPrincipalClass=AppleParavirtDevice` | provider plist SHA-256 `1CE54F84BC97B9542E9AC638CBDDEAC756F10AC0581A59BE516BE9BC5DAEA039`; bundle plist SHA-256 `A635FB1C1C14A4089889FB5EE93B7800EB9708BDE5FB99390950BA661350035C` |
| **[KNOWN]** | packaged IOGPUFamily personality `AppleParavirtGPUIOGPUFamily.kext/IOKitPersonalities/AppleParavirtGPUARM` | `MetalPluginName=AppleParavirtGPUMetalIOGPUFamily`; `MetalPluginClassName=AppleParavirtDevice`; `IOMatchCategory=IOAccelerator`; `IOProviderClass=AppleARMIODevice` | `/System/Library/Extensions/AppleParavirtGPUMetalIOGPUFamily.bundle`; `NSPrincipalClass=AppleParavirtDevice` | provider plist SHA-256 `70D2093FECDBD45C1381BB949EED25F29688D64BF3E4F3F503A5998BDFD5C86F`; bundle plist SHA-256 `9CE9E4B1B656A28C3EE40065567CF72E3560A629265DE85926149ED28B782068` |
| **[BLOCKED]** | x86_64 guest 的 IOGPU port | payload 同时含上述 stock PCI 与 ARM-provider metadata，静态 plist 不能证明适配后的 x86 guest 最终发布哪组 service 属性 | 不得把两个 plugin basename 混用；以 target `ioreg` 结果选择 | 最小 trace 见第 8.2 节 |
| **[KNOWN]** | Intel ICL example | `MetalPluginName=AppleIntelICLGraphicsMTLDriver`，没有 `MetalPluginClassName` | `/System/Library/Extensions/AppleIntelICLGraphicsMTLDriver.bundle`; fallback `NSPrincipalClass=MTLIGAccelDevice` | provider plist SHA-256 `82AE3EA9439A38DA77569569DD624B49A6064FB363EAFE37EFAC0F93E4C8FC73`; bundle plist SHA-256 `5EA35A0E1C29A0C44B26395C930B5BBE8781779CFA3D7B5622711413429FB7AA` |

## 5. `initWithAcceleratorPort:` 精确 ABI

### 5.1 方法表证据

| 标签 | 类 | method entry | type string VA | IMP | encoding |
|---|---|---|---|---|---|
| **[KNOWN]** | `MTLIOAccelDevice` | `0x7FF80B390F1C` | `0x7FF80B44DA2E` | `0x7FF80B17A7CF` | `@20@0:8I16` |
| **[KNOWN]** | `MTLIGAccelDevice` | `0x000C28DC` | `0x006EE018` | `0x0002E87D` | `@20@0:8I16` |
| **[KNOWN]** | `GFXAAMD_MtlDevice` | `0x00388CCC` | `0x004BD1D8` | `0x0002338A` | `@20@0:8I16` |
| **[KNOWN]** | `GFX10_MtlDevice` | `0x00387198` | `0x004BD1D8` | `0x0011692D` | `@20@0:8I16` |

- **[KNOWN]** encoding `@20@0:8I16` 解码为：返回 Objective-C object (`@`)；argument frame size 20；`self` 为 `@` offset 0；`_cmd` 为 `:` offset 8；唯一显式参数为 32-bit `unsigned int` (`I`) offset 16。证据是上表四个 method entry，而不是 selector 字符串。
- **[KNOWN]** Darwin x86_64 调用寄存器是 `RDI=self`、`RSI=_cmd`、`EDX=unsigned int acceleratorPort`，返回 object/`nil` 于 `RAX`；framework call site `0x7FF80B352598..0x7FF80B3525A5` 明确写 `EDX=[service+8]`。
- **[KNOWN]** 该 unsigned int 的语义是 `io_service_t`/Mach port name：来源是 `IOIteratorNext @ 0x7FF80B351DA6..0x7FF80B351DBE`，base init 随后对同值执行 `IORegistryEntryGetRegistryEntryID` 和 `IOObjectRetain @ 0x7FF80B17A836..0x7FF80B17A85A`。
- **[KNOWN]** type-5 `io_connect_t` 是 base init 内部稍后由 `IOServiceOpen` 产生并存入 `IOAccelDeviceRef+0x14`；因此不得把 plugin initializer 声明成接收 `io_connect_t`，即使二者底层都是 32-bit Mach name。直接证据为 `0x7FF80B170F86..0x7FF80B17104A`。

### 5.2 相邻 wrapper ABI

| 标签 | 方法 | encoding | 直接证据 |
|---|---|---|---|
| **[KNOWN]** | `-[MTLIOAccelService initWithAcceleratorPort:deviceClass:]` | `@28@0:8I16#20` | method entry `0x7FF80B391D0C`，IMP `0x7FF80B352395` |
| **[KNOWN]** | `-[MTLIOAccelServiceDescriptor initWithAcceleratorPort:deviceClass:]` | `@28@0:8I16#20` | method entry `0x7FF80B391D54`，IMP `0x7FF80B351BF6` |
| **[KNOWN]** | `-[MTLIOAccelService acceleratorPort]` | `I16@0:8` | method entry `0x7FF80B391CD0`，IMP `0x7FF80B17A7B8` |
| **[KNOWN]** | `-[MTLIOAccelServiceGlobalContext registerService:deviceClass:]` | `v28@0:8I16#20` | method entry `0x7FF80B391DBC`，IMP `0x7FF80B351F46` |

### 5.3 返回与所有权

- **[KNOWN]** plugin initializer 必须按 Objective-C init 规则返回 retained device 或 `nil`；caller 在非 `nil` 分支设置 service、调用 `_MTLAddDevice`，随后 release caller 的临时引用，地址 `0x7FF80B3525AB..0x7FF80B3525E4`。
- **[KNOWN]** `MTLIOAccelDevice` base init 在 `super init`、`IOAccelDeviceCreateWithAPIProperty` 或必需的 `lazyInitialize` 失败时 release self 并返回 `nil`；成功或 `supportLazyInitialization` 为真时返回 self，控制流 `0x7FF80B17A7F5..0x7FF80B17A9D8`。
- **[KNOWN]** plugin 返回 `nil` 时 service wrapper仍结束自身 init，但不会执行 `_setAcceleratorService:`、`_MTLAddDevice` 或 device-added notification；分支点是 `0x7FF80B3525AB..0x7FF80B3525B4`。

## 6. `MTLCopyAllDevices` 与 default-device 规则

### 6.1 `MTLCopyAllDevices`

1. **[KNOWN]** `_MTLCopyAllDevices @ Metal+0x1632` 先初始化注册链，再对 `com.Metal.DeviceArray` 执行 `dispatch_sync`；block `Metal+0x8711` 仅发送 `[deviceArray copy]`，地址 `0x7FF80B18171A..0x7FF80B181728`。
2. **[KNOWN]** 返回数组是调用瞬间的 immutable retained copy；数组顺序就是 `_MTLAddDevice` 的 append 顺序，代码没有排序，证据为 `copy @ Metal+0x8711` 与 `addObject: @ 0x7FF80B1815BA..0x7FF80B1815D4`。
3. **[KNOWN]** 全局数组只含通过以下门的对象：plugin class 是 `_MTLDevice` 子类；init 返回非 `nil`；对象 conform `MTLDevice` 与 `MTLDeviceSPI`；registry ID 通过 `ALLOWED_GPU_IDS`；`_registerInterestNotification` 返回真。直接地址分别为 `Metal+0x1D89FB`、`0x7FF80B3525AB`、`0x7FF80B17B408..0x7FF80B17B441`、`Metal+0x8455`、`0x7FF80B18159A..0x7FF80B1815B8`。
4. **[KNOWN]** `ALLOWED_GPU_IDS` 是逗号分隔的进程环境变量；每项由 `strtoll(token, NULL, 0)` 解析并与 device `registryID` 比较，初始化地址 `0x7FF80B1A423A..0x7FF80B1A42CE`。
5. **[KNOWN]** hot-plug 继续由 `IOServicePublish` callback append；`MTLCopyAllDevicesWithObserver` 把 notifier 放入 notifier array并返回同类 snapshot，入口 `Metal+0x282AA`。

### 6.2 `MTLCreateSystemDefaultDevice`

1. **[KNOWN]** `_MTLCreateSystemDefaultDevice @ Metal+0x17A91` 动态打开 `/System/Library/Frameworks/CoreGraphics.framework/CoreGraphics`，解析 `CGSCreateDefaultMetalDevice`；CoreGraphics 将该符号 re-export 到 SkyLight 的 `_SLSCreateDefaultMetalDevice @ SkyLight+0x40F494`，Metal call range `0x7FF80B190B01..0x7FF80B190B58`。
2. **[KNOWN]** `com.apple.Metal` CFPreferences 中的 `deviceNameMatch` 若为 `CFString`，会保存为 name override；once block 是 `0x7FF80B190CDD..0x7FF80B190D2D`，key CFString 位于 `0x7FF840FBF900`。
3. **[KNOWN]** `IOSurfaceCopyGPUPolicies()` 的 `GPUSelectionPolicy` 字符串可设置 `preferRemovable` 或 `avoidRemovable`；解析地址 `0x7FF80B1A4127..0x7FF80B1A4228`，key/value CFStrings 位于 `0x7FF840FBF980`、`0x7FF840FBF9A0`、`0x7FF840FBF9E0`。
4. **[KNOWN]** `avoidRemovable` 在 service init 阶段生效：只要 service 的 `Removable` CF property 存在就丢弃该 service，不检查 property 的 Boolean 内容，地址 `0x7FF80B3524B0..0x7FF80B3524F6`。
5. **[KNOWN]** 当 CoreGraphics selector 可用且 `deviceNameMatch != nil` 或 `preferRemovable == true` 时，Metal 先在 device array 中顺序查找：优先首个 `[device.name containsString:deviceNameMatch]`，其次首个 `isRemovable` device；block 为 `Metal+0x12F320`，比较地址 `0x7FF80B2A83A5..0x7FF80B2A83EC`。
6. **[KNOWN]** 当有效的 `deviceNameMatch` 存在但没有 name/removable match 时，该路径直接返回 `nil`，不调用 CoreGraphics，也不执行 first-device fallback；外层门是 `0x7FF80B190C21..0x7FF80B190C33`。
7. **[KNOWN]** 没有 strict name override 结果时，Metal 调用 SkyLight。`_SLSDisplayCopyCurrentMetalDevice @ SkyLight+0x40F754` 通过 `_SLSAcceleratorForDisplayNumber` 取得 main-display accelerator port，再从 `MTLCopyAllDevices` snapshot 中选首个 `device.acceleratorPort == port`，地址 `0x7FF8069AC776..0x7FF8069AC88F`。
8. **[KNOWN]** main display 存在多个 alias bit 时，`_SLSCreateDefaultMetalDevice` 对 bit 0..30 调用 `_SLSAcceleratorForDisplayAlias`，在 array 中按 `acceleratorPort` 匹配并拒绝 `isLowPower == 1` 的候选；地址 `0x7FF8069AC4E9..0x7FF8069AC699`。没有可用高性能 alias 时回到 `_SLSDisplayCopyCurrentMetalDevice`。
9. **[KNOWN]** `preferRemovable` 还由 `__MTLOverrideCurrentPreferredDevice @ Metal+0x875F` 实施：传入对象不是 removable 或为 `nil` 时，它改选 array 中首个 removable device；不存在 removable device 时保留原候选，地址 `0x7FF80B18176F..0x7FF80B181835`。
10. **[KNOWN]** CoreGraphics selector 缺失时，Metal 不执行 name/removable 预扫描，直接尝试 `deviceArray[0]`，因此该分支会忽略 `deviceNameMatch`；CoreGraphics selector 存在、返回 `nil` 且没有 strict name override 时，同样 fallback 到 `deviceArray[0]`。array 为空则返回 `nil`；fallback block 是 `Metal+0x12F437`，外层地址 `0x7FF80B190C4E..0x7FF80B190C93`。
11. **[KNOWN]** default-device 返回值遵守 `Create` ownership：array 候选在 blocks 中显式 `objc_retain`；SkyLight 路径也 retain 匹配对象，证据为 `0x7FF80B2A83EC..0x7FF80B2A8401`、`0x7FF80B2A846F..0x7FF80B2A8480` 和 `0x7FF8069AC839..0x7FF8069AC842`。
12. **[KNOWN]** CoreGraphics 无法加载的非交互进程会记录“Use MTLCopyAllDevices(WithObserver) instead”错误，但静态控制流仍可落到 first-device fallback；日志地址 `0x7FF80B37D7A3..0x7FF80B37D7DA`。

## 7. 失败行为

| 标签 | 失败点 | 可观察结果 | 直接地址 |
|---|---|---|---|
| **[KNOWN]** | `IOMainPort` 或 matching notification 注册失败 | global context init 返回 `nil`；本次调用的 device array 保持空；后续设备枚举入口仍会再次进入 `_MTLRegisterDevices` 尝试初始化 | `0x7FF80B351CDD..0x7FF80B351DA5`; `Metal+0x12EC7A`; `Metal+0x1D980D` |
| **[KNOWN]** | `MetalPluginName` 缺失、非 CFString、路径不存在或 trust 失败 | service 被跳过，不创建 `MTLIOAccelService` 或 device | `0x7FF80B351A1E..0x7FF80B351AA1` |
| **[KNOWN]** | class key/classNamed 无效 | fallback 到 `principalClass`；principal class 仍无效或不是 `_MTLDevice` 子类时 service 被跳过 | `0x7FF80B351B05..0x7FF80B351B8A` |
| **[KNOWN]** | 同一 service port 再次 publish | `registerService:deviceClass:` 按 `_acceleratorPort` 去重并直接返回 | `0x7FF80B351F66..0x7FF80B351FAE` |
| **[KNOWN]** | service conforms `IOServiceCompatibility` | service wrapper release self 并返回 `nil` | `0x7FF80B3523F8..0x7FF80B35249E` |
| **[KNOWN]** | `IOServiceAddInterestNotification` 失败 | notification port 被 detach/destroy；service wrapper release self并返回 `nil` | `0x7FF80B352478..0x7FF80B35249E` |
| **[KNOWN]** | `avoidRemovable` 且 `Removable` property 存在 | notification 被拆除，service wrapper被丢弃 | `0x7FF80B3524B0..0x7FF80B3524F6` |
| **[KNOWN]** | type-5 `IOServiceOpen` 失败 | `_IOAccelDeviceCreateWithAPIProperty` 返回 `NULL`；base/plugin init 返回 `nil`；device 不进入 array | `0x7FF80B170F86..0x7FF80B170FC3`; `0x7FF80B17A82D..0x7FF80B17A9D6` |
| **[KNOWN]** | IOAccel selector 2 或 selector 0 失败 | CF `IOAccelDeviceRef` 被 release，create 返回 `NULL` | `0x7FF80B17106F..0x7FF80B17114D` |
| **[KNOWN]** | API-property selector 9 或 optional selector 7 失败 | selector 9 error 被忽略；selector 7 data 缺失但 create 继续 | `0x7FF80B170FE4..0x7FF80B171002`; `0x7FF80B171192..0x7FF80B1711D3` |
| **[KNOWN]** | plugin init 返回 `nil` | 不调用 `_MTLAddDevice`，service wrapper保留但 weak device 为空 | `0x7FF80B3525A5..0x7FF80B3525B4` |
| **[KNOWN]** | device 不 conform `MTLDevice` 或 `MTLDeviceSPI` | `_MTLAddDevice` 进入 `_MTLReleaseAssertionFailure` 后 `ud2`，不是普通 `nil` 失败 | `0x7FF80B17B408..0x7FF80B17B560` |
| **[KNOWN]** | registry ID 不在非空 `ALLOWED_GPU_IDS` | object 不 append，不发送 device-added notification | `Metal+0x8455` 的 `0x7FF80B1814E8..0x7FF80B1815FD` |
| **[KNOWN]** | general-interest termination/eject | message `0xE0000010` 调 `_wasTerminated`，`0xE3FF80C8` 调 `_safeEjectRequested`，`0xE3FF80C9` 调 `_safeEjectCancelled` | `_mtlIOAccelServiceInterest @ 0x7FF80B352117..0x7FF80B352157` |

## 8. 剩余阻断与最小闭合步骤

### 8.1 exact installed-SystemOS IOGPU/Metal/IOAccelerator 样本

- **[BLOCKED]** 精确缺件是 25G325 installed System Cryptex 的完整 `dyld_shared_cache_x86_64` family，以及其中 `/System/Library/PrivateFrameworks/IOGPU.framework/Versions/A/IOGPU`；BaseSystem cache 的 719-image list 包含 Metal 与 IOAccelerator，但不含 IOGPU。
- **[BLOCKED]** 最小 acquisition 不需要展开 18 GB image：只从 `C:\Users\viola\Documents\KVM MacOS\SharedSupport.dmg` 的内层 update ZIP 取 `C:\Users\viola\Documents\KVM MacOS\SharedSupport.dmg!/Shared Support/com_apple_MobileAsset_MacSoftwareUpdate/d3cc6643f7010f6ec14cc728f4a47a7c7644e8a5.zip!/AssetData/payloadv2/image_patches/cryptex-system-x86_64`（central-directory size 1,600,890,778 bytes），在 macOS 13+ 分析机运行 `ipsw ota patch rsr --cryptex <that-file>`，或直接调用 `/usr/lib/libParallelCompression.dylib` 的 `RawImagePatch`，输出一个 SystemOS DMG。
- **[BLOCKED]** 只读挂载该 DMG后复制 `/System/Library/dyld/dyld_shared_cache_x86_64*`，运行 `ipsw dyld extract <primary-cache> /System/Library/PrivateFrameworks/IOGPU.framework/Versions/A/IOGPU`，再记录 cache UUID、Mach-O UUID、architecture 与 SHA-256；同样重抽 Metal/IOAccelerator，并以 UUID/hash 判断它们是否与第 1 节 BaseSystem样本相同。
- **[KNOWN]** 当前非-Darwin `ipsw` build 的 `RawImagePatch` 明确返回 “only supported on darwin”；因此本报告没有猜测 IOGPU UUID、hash、函数地址或 installed-SystemOS 与 BaseSystem 的二进制同一性。

### 8.2 一次 target guest trace 闭合 B-001/B-002/B-003 的 `TESTED` 状态

1. **[BLOCKED]** 在 25G325 x86_64 guest 内编译一个普通、非系统受保护的 probe，只调用 `MTLCopyAllDevices()`、逐项打印 `name/registryID/isRemovable/isLowPower`，再调用 `MTLCreateSystemDefaultDevice()`；保存 stdout、`sw_vers` 和 probe SHA-256。
2. **[BLOCKED]** 对 probe 启动 LLDB，设置 `_MTLRegisterDevices`、`_getMetalPluginClassForService`、`-[MTLIOAccelService initWithAcceleratorPort:deviceClass:]`、`IOServiceOpen`、目标 plugin 的 `initWithAcceleratorPort:`、`_MTLAddDevice` 断点；每次记录 image UUID+slide、`EDI/ESI/EDX/RCX/RAX` 和 thread backtrace。
3. **[BLOCKED]** 在 `_getMetalPluginClassForService` 断点用同一个 `EDI` service 执行/旁路采集 `ioreg -r -c IOAccelerator -l`，保存 `MetalPluginName`、`MetalPluginClassName`、`IOClass`、registry-entry ID；这一步决定 x86 guest 实际走 `AppleParavirtGPUMetal` 还是 `AppleParavirtGPUMetalIOGPUFamily`。
4. **[BLOCKED]** 在 `IOServiceOpen` 断点核对 `EDI` 等于 plugin initializer 的 `EDX`，`EDX`（第三个 C 参数）等于 5，并在返回后读取 `RCX` 指向的 connection；这条 trace 将静态 B-001 升为 `TESTED`。
5. **[BLOCKED]** 在目标 class 已加载后执行 `method_getTypeEncoding(class_getInstanceMethod(NSClassFromString(@"AppleParavirtDevice"), sel_registerName("initWithAcceleratorPort:")))`，要求精确输出 `@20@0:8I16`；再核对 initializer 的 `EDX` 是 service port，这条 trace 将 B-003 升为 `TESTED`。
6. **[BLOCKED]** 对 `MTLCopyAllDevices` snapshot 和 default device 同时记录 `acceleratorPort` 与 registry ID；若设置 `com.apple.Metal/deviceNameMatch`、`ALLOWED_GPU_IDS` 或 removable policy，测试必须在报告中显式保存设置值，避免把带 override 的结果写成系统默认规则。

### 8.3 第三方 `/Library/GPUBundles` trust gate

- **[BLOCKED]** 最小测试件是一个已签名、只有一个 `_MTLDevice` 子类的 bundle，以及一个发布 `MetalPluginName`/`MetalPluginClassName` 的受控 `IOAccelerator` service；不要先实现完整渲染对象族。
- **[BLOCKED]** target trace 在 `_gpu_bundle_find_trusted @ libsystem_sandbox+0x1270` 和 `_gpu_bundle_is_path_trusted @ +0x143B` 记录 candidate path、`rootless_check_trusted_class` 返回值、`__dyld_shared_cache_contains_path` 返回值、最终 return 与 `errno`；成功标准是 `/Library/GPUBundles/<name>.bundle` 返回 0 并到达目标 class initializer。
- **[BLOCKED]** 若 trust gate 拒绝，则规格不得建议绕过 rootless；应把 bundle 放入系统接受的安装位置并完成签名/boot-policy 验证，或保留该路径为明确不可交付项。

## 9. 规格实施约束

- **[KNOWN]** 注册实现必须发布一个可被 `IOServiceMatching("IOAccelerator")` 命中的 service，并把 `MetalPluginName` 作为 service 的 `CFString` property；仅在 bundle `Info.plist` 中放同名 key 不满足 `IORegistryEntryCreateCFProperty @ Metal+0x1D8A2A` 的读取位置。
- **[KNOWN]** plugin bundle 必须位于两个固定候选目录之一，basename 与 `MetalPluginName` 完全一致，且 candidate class 必须继承 `_MTLDevice`；直接门位于 `libsystem_sandbox+0x1270` 和 `Metal+0x1D8B62`。
- **[KNOWN]** device initializer 的公开给 runtime 的 encoding 必须精确为 `@20@0:8I16`；实现签名应按语义写成 `- (instancetype)initWithAcceleratorPort:(io_service_t)service`，不得声明成指针、64-bit integer 或 `io_connect_t`。
- **[KNOWN]** initializer 内部必须容许 `IOServiceOpen(service, mach_task_self_, 5, &connection)` 失败并返回 `nil`；不得向 framework 返回半初始化对象，framework 的 base failure contract 位于 `Metal+0x17CF`、IOAccelerator failure contract位于 `+0xF60`。
- **[KNOWN]** 首个可审核适配竖切只需完成：service publication、trusted bundle lookup、class gate、精确 initializer ABI、type-5 open、`MTLAddDevice` append、`MTLCopyAllDevices` 可见性；default-device 与渲染 selector 应在该竖切通过后分别验收。
- **[BLOCKED]** 在第 8.2 和 8.3 节 trace 通过前，不得把本报告的静态 `KNOWN` 标签升级为目标 guest 的 `TESTED`，也不得把 BaseSystem UUID/hash登记成 installed SystemOS UUID/hash。
