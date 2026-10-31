# 90 - 证据索引

文档版本：1.0
基线日期：2026-10-30
锚文档：`00-OVERVIEW.md`（证据规则见其第 7 节）

## 0. 本文作用

登记本项目可用的全部二进制样本：架构、来源层级、`LC_UUID`、SHA-256、IDB，
并明确每件**能否用于 x86 实现决策**。

两条硬规则（`00-OVERVIEW.md` §7）在本文逐件落地：

1. arm64 证据不得用于 x86 实现决策。
2. BaseSystem 样本不得冒充 installed SystemOS 样本。

本轮新增 `analysis/binaries/macos26-25G325-x86_64/`，其完整来源链、
抽取方法与可复现脚本见该目录的 `MANIFEST.md`。本文只做分级与裁决，
不重复来源链细节。

本轮没有打开、改写或复制任何 `.i64`；第 4 节的 IDB 哈希引自既有 MANIFEST。

## 1. 样本层级定义

| 层级 | 含义 | 可用性 |
|---|---|---|
| **T1 installed SystemOS** | 目标系统盘上实际存在的那份字节 | 可直接用于 x86 实现决策 |
| **T2 KC 重建件** | 从 installed SystemOS 的 kernel collection 的 `LC_FILESET_ENTRY` 重建出的独立 Mach-O | 代码与符号等同 T1；`__DATA` 指针未重定基 |
| **T3 BaseSystem** | 25G325 安装资产内 x86_64 BaseSystem（recovery 环境）的 dyld cache 映像 | 可用于 ABI 与控制流决策，必须以 UUID+RVA 绑定，不得声称与 T1 字节相同 |
| **T4 异架构** | arm64 / arm64e 样本 | **只能作协议与设计参考**，不得用于 x86 实现决策 |
| **T5 异构建** | 架构对但 OS 构建不是 25G325 | 仅在所用结论与版本无关时可用，必须注明 |

## 2. 可用于 x86 实现决策的样本

### 2.1 T2：25G325 installed SystemOS kernel collection 重建件

全部 `x86_64` / cpusubtype 3 (`ALL`) / `MH_KEXT_BUNDLE`，来源见
`analysis/binaries/macos26-25G325-x86_64/MANIFEST.md` 第 2、3 节。

| 标签 | 逻辑路径 | 本地样本 | 字节 | `LC_UUID` | `LC_SOURCE_VERSION` | SHA-256 |
|---|---|---|---:|---|---|---|
| **KNOWN** | `/System/Library/Extensions/AppleParavirtGPU.kext/Contents/MacOS/AppleParavirtGPU` | `analysis/binaries/macos26-25G325-x86_64/kext/com.apple.driver.AppleParavirtGPU` | 13,133,432 | `B88E1D48-71A2-3DC0-8D87-605DDB039B83` | `64.5.0.0.0` | `803615D37075DE5960E0C2B6E16218411BD6EFA5667C701439C69EDAB29954B7` |
| **KNOWN** | `/System/Library/Extensions/IOAcceleratorFamily2.kext/Contents/MacOS/IOAcceleratorFamily2` | `.../kext/com.apple.iokit.IOAcceleratorFamily2` | 13,526,648 | `6C4A16B1-66DC-3A8B-9F0B-D3E027B16EB1` | `487.4.4.0.0` | `BDCE06A7DBC6873E66EFF6134C3C3C739EAAD3ED6447D9DFA86CEEC73061F134` |
| **KNOWN** | `/System/Library/Extensions/IOGraphicsFamily.kext/IOGraphicsFamily` | `.../kext/com.apple.iokit.IOGraphicsFamily` | 13,248,120 | `74AA6483-8AB4-3A94-8143-5E306C16D7DA` | `600.0.0.0.0` | `219AEB6EE04D762C9FD7341063F5EAB23E02F0A7330E9D096E7D7F81C39A8673` |
| **KNOWN** | `/System/Library/Extensions/IOSurface.kext/Contents/MacOS/IOSurface` | `.../kext/com.apple.iokit.IOSurface` | 13,157,866 | `766DF6D3-1EEC-34DB-A9AD-EF72A36FB2A8` | `393.5.11.0.0` | `E9487381590812B988F3AD517897438546BB1E932C3DE224BCF78FDCA9F409D7` |
| **KNOWN** | `/System/Library/Extensions/IOGPUFamily.kext/Contents/MacOS/IOGPUFamily` | `.../kext/com.apple.iokit.IOGPUFamily` | 13,330,040 | `07C66EBC-383D-3A88-A65B-27E94F8CA231` | `130.16.5.0.0` | `1471596A9BDBF80946F06299C6670C1A334B121E637375CF7BD4778BCE371FA0` |
| **KNOWN** | `/System/Library/Extensions/IOPCIFamily.kext/Contents/MacOS/IOPCIFamily` | `.../kext/com.apple.iokit.IOPCIFamily` | 13,338,090 | `81D9CF0C-0587-3EC8-B878-E0042113108B` | `726.100.6.0.0` | `DA288A5829A52DB8BA62B16AB37F56D1E889AB938084FF79C0EA56176E5BB59B` |
| **KNOWN** | `/System/Library/Extensions/AppleGraphicsControl.kext/Contents/PlugIns/AppleGraphicsDeviceControl.kext/Contents/MacOS/AppleGraphicsDeviceControl` | `.../kext/com.apple.AppleGraphicsDeviceControl` | 13,018,744 | `02FECF8A-3227-3BBB-B0EB-1DB31965ADB9` | `8.1.12.0.0` | `18FE4493C66EE861F436B61DBE469008B3B2EB4FD635DC34D8E06466FF626B32` |

**T2 的唯一使用限制：** 重建件保留了条目自身的 load command 与 `vmaddr`，
符号表可用（2,114 至 4,707 个符号/件），RVA 与 KC 内一致；但 chained fixup
是 collection 级的，没有随件携带，所以 `__DATA` 里的函数指针与 vtable 槽仍是
编码值。读 `__DATA` 指针时必须按 chained fixup 解码，不能直接当地址用。
`LC_DYSYMTAB`、relocation 与 code signature 已清零。

容器哈希（可用于校验重建）：
`SystemKernelExtensions.kc` 369,213,440 bytes，`x86_64` `MH_FILESET`，172 条目，
UUID `EAAB5F23-BA1B-DAF9-781D-6C22A45A9689`，SHA-256
`5EDE2BA5627482282E8964B00B6E17A0F7115F07D799E618DB806FBC60D94421`。
`BootKernelExtensions.kc` 67,584,000 bytes，`x86_64` `MH_FILESET`，204 条目，
UUID `F6EB5100-67F3-FB2F-6706-BE6A8D30B730`，SHA-256
`AD6F93AF96071D10F7483D1E4268331E2346FE0EC641AC896E03527FC8FDEBF4`。

### 2.2 T1：25G325 installed SystemOS 原生独立 Mach-O

字节与安装资产内容完全一致，没有任何重建。

| 标签 | 逻辑路径 | 本地样本 | 字节 | 架构 | `LC_UUID` | SHA-256 |
|---|---|---|---:|---|---|---|
| **KNOWN** | `/System/Library/Extensions/AppleParavirtGPUMetal.bundle/Contents/MacOS/AppleParavirtGPUMetal` | `.../metal-bundle/AppleParavirtGPUMetal.universal` | 808,272 | FAT：`x86_64`/3 + `arm64e`/2 | x86_64 `15DB02D8-D7E6-30A1-979C-DFD657E47F19`；arm64e `46514AE2-B7A4-3D78-8DCB-4B44FDEEE6C3` | `42A413EC5F9B11974BC0E788A21DAE3B5A10981B5ECF8F8AF488E461901B5AD0` |
| **KNOWN** | 同上，x86_64 slice（fat 偏移 16,384） | `.../metal-bundle/AppleParavirtGPUMetal.x86_64` | 380,688 | `x86_64` / 3 | `15DB02D8-D7E6-30A1-979C-DFD657E47F19` | `71423441A9CD4055224AF18D2DCDECA59139640748D07079572630539E948BAF` |
| **KNOWN** | `/System/Library/Kernels/kernel` | `.../kernel/kernel.x86_64` | 19,008,056 | `x86_64` / 3，`MH_EXECUTE` | `E514CEBA-9206-34D5-86C2-64E880FDDA2B` | `B3161C243158355226E677CC2B44A5F43397E5DC94CC28F5A7B00028E29DE4F1` |
| **KNOWN** | `/System/Library/Extensions/IOGraphicsFamily.kext/iogdiagnose` | `.../kext/iogdiagnose.universal` | 136,544 | FAT：`x86_64`/3 + `arm64e`/2 | x86_64 `99915E43-465E-3E59-A346-DD9D24A33B7A` | `71533509F4E2978865EBAEDF418467DCEB9846CE416962266C612D07C2FCABCC` |
| **KNOWN** | 同上，x86_64 slice | `.../kext/iogdiagnose.x86_64` | 46,544 | `x86_64` / 3 | `99915E43-465E-3E59-A346-DD9D24A33B7A` | `881F8677168894093E406C59940B8FA15C35535D670C5D1E0380956067832CDE` |

`kernel.x86_64` 的 `LC_SOURCE_VERSION` 是 `12377.161.15.701.48`，
platform macOS minos 26.7.1 / sdk 26.7.1。它是 x86 侧 IOKit 基类与 KPI 的
参考样本。

**顺带更正：** `00-OVERVIEW.md` §4.1 写"仓库中已分析的四个内核 `.i64`
（`AppleParavirtGPUIOGPUFamily`、`IOGPUFamily`、`AppleParavirtIOSurface`、
arm64 kernel）"。实际 `analysis/idb/macos26-25G325-arm64/` 下的四个 `.i64` 是
`AppleParavirtGPUIOGPUFamily-existing-analysis`、
`AppleParavirtGPUIOGPUFamily-raw-reanalysis`、`IOGPUFamily`、
`AppleParavirtIOSurface`，**没有任何内核 IDB**。该句列举有误，但其结论
（这些样本全属 ARM 路径）不受影响。

### 2.3 T1：plist 与元数据

31 个文件在 `analysis/binaries/macos26-25G325-x86_64/plists/`，逐件 SHA-256 见
该目录 `MANIFEST.md` 第 6 节。关键三件与既有文档逐位一致，可作管线正确性交叉校验：

| 标签 | 文件 | SHA-256 | 既有记录位置 |
|---|---|---|---|
| **KNOWN** | `AppleParavirtGPU.kext/Contents/Info.plist` | `1CE54F84BC97B9542E9AC638CBDDEAC756F10AC0581A59BE516BE9BC5DAEA039` | `analysis/spec-work/metal-registration-contract.md` §4.3 |
| **KNOWN** | `AppleParavirtGPUMetal.bundle/Contents/Info.plist` | `A635FB1C1C14A4089889FB5EE93B7800EB9708BDE5FB99390950BA661350035C` | 同上 |
| **KNOWN** | `AppleParavirtGPUIOGPUFamily.kext/Contents/Info.plist` | `70D2093FECDBD45C1381BB949EED25F29688D64BF3E4F3F503A5998BDFD5C86F` | 同上 |

本轮新增、既有文档未记录的：
`IOAcceleratorFamily2.kext/Contents/Info.plist`
`4E095827648BD7407BA77D52E9723C5868954792FA1E1862413A1F95399BEB84`、
`IOGraphicsFamily.kext/Info.plist`
`41101D839D6BF0685CA5F9337FB12FA4457358ADBDD6EDDC06F2D1966D072878`、
`IOSurface.kext/Contents/Info.plist`
`4EE11D8571C78B8BF91B79E23F593A9938861F641E1755C4C863874C0B8E41AC`、
`IOGPUFamily.kext/Contents/Info.plist`
`E80A80FD6D00CFD14E9A6D62ACD55EDBC4DF946F034071991FB86B965C45A7EB`、
`IOPCIFamily.kext/Contents/Info.plist`
`A0FE0E7FA4018AB7502D951C472292A5A97530F32897D21D975CB58AA3A52606`。

### 2.4 T3：25G325 x86_64 BaseSystem dyld cache 映像

架构与构建都对（`x86_64`，两条 `LC_BUILD_VERSION`：macOS minos 26.7.0 /
sdk 26.7.1 与 macCatalyst 26.7.0 / 26.7.0，即 zippered 映像），但层级是
BaseSystem，不是 installed SystemOS。

| 标签 | 逻辑路径 | 本地样本 | 字节 | `LC_UUID` | `LC_SOURCE_VERSION` | SHA-256 |
|---|---|---|---:|---|---|---|
| **KNOWN** | `/System/Library/Frameworks/Metal.framework/Versions/A/Metal` | `analysis/idb/macos26-25G325-x86_64-frameworks/raw/Metal` | 5,723,760 | `FDB3FD2C-840A-3FC3-81FB-C524F891F642` | `373.7.1.0.0` | `9BAB47CD9A7E11E15A17486C8E4BA2775CDDC1A705A6F60A39C0A87D9F598C9D` |
| **KNOWN** | `/System/Library/PrivateFrameworks/IOAccelerator.framework/Versions/A/IOAccelerator` | `.../raw/IOAccelerator` | 78,856 | `4FDBB3F6-9AA3-352B-87ED-57161AA64D1F` | `487.4.4.0.0` | `7EF85F8415B13992A34FDDDF0B523D8D4DA366564E93D78187D8E0BC5BF01FA2` |
| **KNOWN** | 同上 Metal，解析副本 | `.../analysis-input/Metal` | 6,356,568 | `FDB3FD2C-840A-3FC3-81FB-C524F891F642` | `373.7.1.0.0` | `AFD31CC024908EC448914F0B54C5EF213AC6CCAE570A45C406384749A5AA63D9` |
| **KNOWN** | 同上 IOAccelerator，解析副本 | `.../analysis-input/IOAccelerator` | 79,400 | `4FDBB3F6-9AA3-352B-87ED-57161AA64D1F` | `487.4.4.0.0` | `A2E859A54796D6C440C108E43E3926AD9A138B7D52DB934C17357317F255BF09` |
| **KNOWN** | `/usr/lib/system/libsystem_sandbox.dylib` | `.../analysis-input/libsystem_sandbox.dylib` | 58,696 | `A682C065-1706-3C81-AAA7-DEF3E7B450D8` | `2680.160.6.701.1` | `9D83CCD7471C035DF20B80313915335E62FA1A1358F958DB95A90FA05FB54C1E` |
| **KNOWN** | `/System/Library/PrivateFrameworks/SkyLight.framework/Versions/A/SkyLight` | `.../analysis-input/SkyLight` | 8,227,280 | `0900DFAB-ABDA-3500-AA65-806935F7AF44` | `922.13.4.3.0` | `40A54C61E89D66734565BD3E105899C7D2F5676F373A6A1EC28FBACDF2561195` |

**交叉确证：** `IOAccelerator` 的 `LC_SOURCE_VERSION` 是 `487.4.4.0.0`，与本轮 T2
的 `IOAcceleratorFamily2.kext`（`487.4.4.0.0`，`Info.plist` 的 `CFBundleVersion`
也是 `487.4.4`）同一工程版本。用户态 framework 与内核 family 对得上，这支持
把 T3 的 Metal/IOAccelerator 结论用于 x86 实现。

**使用限制：** 地址必须以 `UUID + RVA` 形式引用，不得只给 BaseSystem unslid VA。
installed SystemOS 的同名映像尚未取得（第 5 节）。

## 3. 只能作参考、不得用于 x86 实现决策的样本

### 3.1 T4：arm64e 样本

| 标签 | 本地样本 | 字节 | 架构 | `LC_UUID` | `LC_SOURCE_VERSION` | SHA-256 | 裁决 |
|---|---|---:|---|---|---|---|---|
| **参考** | `metal_drivers/com.apple.driver.AppleParavirtGPUIOGPUFamily` | 405,616 | `arm64` / subtype 2 (`arm64e`)，caps `0xc0` | `A232D9E4-57ED-32FA-B024-75DBBEA5B27D` | `64.4.7.0.0` | `9AD1175C60D53B60DF9D6B4836AC4050D3896B5AD6F8BBEC8F022A5485685EF5` | 异架构，且非 25G325 |
| **参考** | `metal_drivers/com.apple.iokit.AppleParavirtIOSurface` | 141,088 | `arm64` / 2，caps `0xc0` | `7A448A27-6B72-3AEA-9B05-2E560DC5F5E0` | `64.4.7.0.0` | `AF3AEB0F358F0B3C14ABED17F29588D6DECDF977C72068EBAD0A56C9263FF0D3` | 同上 |
| **参考** | `metal_drivers/com.apple.iokit.IOGPUFamily` | 670,728 | `arm64` / 2，caps `0xc0` | `1859F9C2-097A-301E-B9EC-4710E6B60908` | `130.16.4.0.0` | `1D290CA65F62E1811B7832B95FE55ABD4F8D1891F64DB38026F590DEEDFE521C` | 同上 |

这三件对应 `00-OVERVIEW.md` §4.1 表格的右列，即 ARM 路径。它们作废的具体结论
（display FIFO command 8 的 40 字节 payload、cursor command 4、mapper ring
16 字节条目、mapping ID 1..8191、IOGPU selector 0/2/7/9/14/16/28/29/40）
在 x86 侧仍不成立，本轮没有改变这一点。

### 3.2 既有 arm64 样本不是 25G325

**KNOWN（事实）：** 25G325 的 `AppleParavirtGPU` 工程版本是 `64.5.0.0.0`，
`IOGPUFamily` 是 `130.16.5.0.0`。仓库里三件 arm64 样本分别是 `64.4.7.0.0`、
`64.4.7.0.0`、`130.16.4.0.0`。

**KNOWN（同构建跨架构 source version 相同）：** 本轮的
`AppleParavirtGPUMetal.universal`、`AppleParavirtGPUMetalIOGPUFamily.universal`、
`iogdiagnose.universal` 三件 universal 二进制，其 x86_64 与 arm64e slice 的
`LC_SOURCE_VERSION` 分别都是 `64.5.0.0.0`、`64.5.0.0.0`、`600.0.0.0.0`，
两两相同。

**INFERRED（强）：** 由上两条，`64.4.7.0.0` / `130.16.4.0.0` 的 arm64 样本来自
**早于 25G325 的 macOS 构建**。因此 `analysis/idb/macos26-25G325-arm64/` 目录名
里的 `25G325` 标注不可信；架构标注 `arm64` 正确。

**待办：** 该目录的 MANIFEST 应补注这些样本的真实来源构建，或标记为未确证。
本轮不修改既有文件，只在此记录。

### 3.3 T5：架构对、构建不对的 vendor Metal driver

| 标签 | 本地样本 | 字节 | 架构 | `LC_BUILD_VERSION` | `LC_UUID` | SHA-256 |
|---|---|---:|---|---|---|---|
| **KNOWN** | `metal_drivers/AMDRadeonX6000MTLDriver_decompressed` | 8,678,176 | `x86_64` / subtype 8 (`x86_64h`) | macOS minos 26.6.0 / **sdk 26.6.1**（唯一一条） | `774E6DC1-A6B4-381B-AFD9-29C8E813DE95` | `C0CEA683B94A5D645CDE7FB50FAA917B02AB35BDAB1A697D847E4B7678E1DADB` |
| **KNOWN** | `metal_drivers/AppleIntelICLGraphicsMTLDriver_decompressed` | 8,258,224 | `x86_64` / 8 (`x86_64h`) | macOS minos 14.0.0 / **sdk 26.6.1**（唯一一条） | `251E3AE2-1396-3AD1-974A-422AE954B85A` | `2D21F64F6361045CE83F9BB0CE9D4AA56E452FAB484066709673A1335F06141E` |

25G325 的全部样本 sdk 都是 `26.7.1`。这两件是 `26.6.1`，**不是 25G325**。
`analysis/spec-work/metal-registration-contract.md` §1.2 把它们列在 25G325
样本表里并标 **KNOWN**，这一处构建标注有误，需要更正为 26.6.x。

它们支撑的结论是 x86_64 ObjC 方法表 encoding `@20@0:8I16` 与
`initWithAcceleratorPort:` 的参数寄存器约定。该结论与 26.6/26.7 的小版本差异
无关，可继续使用，但必须标注样本构建为 26.6.x，不得写成 25G325。

### 3.4 x86_64 代码、但在 x86 guest 上不会被加载

| 标签 | 本地样本 | 字节 | 架构 | `LC_UUID` | SHA-256 |
|---|---|---:|---|---|---|
| **参考** | `.../metal-bundle/AppleParavirtGPUMetalIOGPUFamily.universal` | 1,012,992 | FAT：`x86_64`/3 + `arm64e`/2 | x86_64 `C1EE81DD-EDB4-3DE1-9EAD-6C82F4800AA6`；arm64e `CBA08755-62C9-3105-9194-32EA2DAECBEA` | `EC5E4104033C69B40504ABBBB75A37C1E12E840FEC4A5694EB134E9A74884C76` |
| **参考** | `.../metal-bundle/AppleParavirtGPUMetalIOGPUFamily.x86_64` | 487,696 | `x86_64` / 3 | `C1EE81DD-EDB4-3DE1-9EAD-6C82F4800AA6` | `266EF0EFC29C8B6CA3F660969542A60254CC489321F5EE92A2601173DDFABB3D` |

这是 ARM 路径的 Metal plugin，但 Apple 把它编成了 universal，所以它确实含
25G325 的 x86_64 代码，可作 ObjC 侧第二份对照（两个 bundle 的
`MetalPluginClassName` 都是 `AppleParavirtDevice`）。它配对的
`AppleParavirtGPUIOGPUFamily.kext` 不在 x86_64 kernel collection 里，
x86 guest 上不会有 service 发布这个 `MetalPluginName`，**不得据它推断 x86
运行时行为**。

## 4. IDB 清单

本轮未打开任何 `.i64`。哈希引自既有 MANIFEST，未重新计算。

### 4.1 `analysis/idb/macos26-25G325-arm64/`（T4，构建标注见 §3.2）

| IDB | 字节 | SHA-256 |
|---|---:|---|
| `AppleParavirtGPUIOGPUFamily-existing-analysis.i64` | 3,908,736 | `5ED11D98EAE2D65334C1178FDE5B2AC6A77CC1629F5D249A3751E45D78452E48` |
| `AppleParavirtGPUIOGPUFamily-raw-reanalysis.i64` | 2,867,884 | `718B484E53E3105E3AE188A7ECBB0EB0BEB174C66E49D74063399D27014E932A` |
| `IOGPUFamily.i64` | 6,791,023 | `8D580779C8087DBF649DE5180489D1D24FBD8368B7C4B48C165948F6FBA5CBBF` |
| `AppleParavirtIOSurface.i64` | 1,651,627 | `68F3C996A9DFEF3011D8DCD778A8BE1409663ED67F3431FF0DF49346CF99CB2D` |
| `ida-evidence.md` | 57,728 | `4992A34F63C08BA78C21F984CA6890D943621849F098C95FF264DB880B641413` |

另有 `metal_drivers/com.apple.driver.AppleParavirtGPUIOGPUFamily.i64`
2,834,133 bytes，SHA-256
`DE3F059B18F987BA890F341DA6E63763FCC7D871ECFFF9A5BE6F44A9040B4FDA`。

### 4.2 `analysis/idb/macos26-25G325-x86_64-frameworks/idb/`（T3）

| IDB | 字节 | SHA-256 | 关键标注 |
|---|---:|---|---|
| `Metal-BaseSystem-analysis.i64` | 60,887,653 | `B8F9A4AFAB85D308F37CBC6962D0C862C3691DD2C8919C87C88659040F7D36DF` | 注册链与 `newFunctionWithName:` ABI |
| `IOAccelerator-BaseSystem-analysis.i64` | 1,005,286 | `AB85F84D2052652C6BC4D017C8060C751459E42ABDEAD08E055FB65EEDCAD5BA` | type-5 open 与 selector 9/2/0/7 |
| `libsystem_sandbox-BaseSystem-analysis.i64` | 626,152 | `E39BF92450ED8F57F574CB442E4AD471F1F62D7C6225FCE66804BB5AD118C762` | GPU bundle 路径与 trust gate |
| `SkyLight-BaseSystem-analysis.i64` | 88,026,862 | `87E3F40EAB2B1C122A493132DF27126A8BA6C19A9E574715522B25D34B734E03` | display accelerator 到 default Metal device |

### 4.3 `metal_drivers/`（T5）

| IDB | 字节 |
|---|---:|
| `AMDRadeonX6000MTLDriver_decompressed.i64` | 71,661,735 |
| `AppleIntelICLGraphicsMTLDriver_decompressed.i64` | 45,185,530 |

既有 MANIFEST 未记录这两件的 SHA-256，本轮也未计算（不碰 `.i64`）。

### 4.4 本轮新增样本尚无 IDB

§2.1、§2.2 的 9 个 x86_64 Mach-O 全部没有 IDB。
`10-KERNEL-ACCELERATOR.md`、`11-KERNEL-DISPLAY.md`、`12-KERNEL-IOSURFACE.md`
的第一步应是对以下四件建库：
`com.apple.driver.AppleParavirtGPU`、`com.apple.iokit.IOAcceleratorFamily2`、
`com.apple.iokit.IOGraphicsFamily`、`com.apple.iokit.IOSurface`。

## 5. BLOCKED

### 5.1 installed SystemOS 的 dyld shared cache 常驻映像

**缺的东西：** x86_64 的
`/System/Library/PrivateFrameworks/IOGPU.framework/Versions/A/IOGPU`、
`/System/Library/Frameworks/IOSurface.framework/Versions/A/IOSurface`、
以及 installed SystemOS 层级的
`IOAccelerator.framework/Versions/A/IOAccelerator` 与
`Metal.framework/Versions/A/Metal`（现有的是 T3 BaseSystem）。

**卡在哪一步（KNOWN）：** 本轮把 `payloadv2` 的 458,715 个条目全部索引完，
结论是：

1. 资产内**没有任何** `dyld_shared_cache_*` 文件。全部 dyld 相关条目只有
   `usr/lib/dyld`、`usr/bin/dyld_usage`、`usr/bin/update_dyld_shared_cache`、
   man page 与 `Dyld.framework` 的 Resources。
2. 资产内**没有任何** framework 可执行映像。`IOGPU.framework`、
   `IOSurface.framework`、`IOAccelerator.framework` 三条路径只有目录、
   符号链接和 `Resources/Info.plist`。直接依据：
   `analysis/binaries/macos26-25G325-x86_64/payloadv2-graphics-index.tsv`。
3. installed SystemOS 的 cache 以
   `AssetData/payloadv2/image_patches/cryptex-system-x86_64` 交付，
   1,600,890,778 bytes，magic `RIDIFF10`。这是增量 patch，应用它需要
   **已安装的 26.x 系统上的基准 cryptex 镜像**。
   （同目录另有 `cryptex-system-arm64e` 4,456,809,362 bytes 与
   `cryptex-app` 31,379,554 bytes，同为 `RIDIFF10`。）

**缺什么工具：** 一个 `RIDIFF10` 应用器，外加它需要的基准镜像。
`ipsw ota patch rsr` 实现了前者，但按 `00-OVERVIEW.md` 的平台约束只在 Darwin
可用；基准镜像无论如何都要来自一台已装 26.x 的机器，所以补工具并不能单独解困。

**最小可行替代方案，按代价排序：**

1. **在 25G325 x86_64 guest 内执行（推荐）。** 直接复制
   `/System/Library/dyld/dyld_shared_cache_x86_64*` 出来，或在 guest 内
   `dyld_shared_cache_util -extract`。所需条件：一台能起到桌面的 25G325
   x86_64 guest + 文件传出通道。这条路同时能闭合
   `metal-registration-contract.md` §8.1 和 §8.2，收益最高。
2. **重建 x86_64 BaseSystem 并从其 cache 取 IOSurface.framework。**
   `AssetData/payloadv2/basesystem_patches/x86_64BaseSystem.dmg` 是
   `BXDIFF50` 全量替换（891,864,876 bytes 压缩，重建后 1,464,270,504 bytes，
   见 `metal-registration-contract.md` §1.1）。需要在 Windows 上补写
   APFS/HFS 解析 + dyld cache 抽取。**注意这只会得到 T3 层级的样本**，
   且既有结论是 `IOGPU` 不在 BaseSystem cache 内，所以这条路解不了 IOGPU。
3. **自写 `RIDIFF10` 应用器。** 仍需基准镜像，等价于先有方案 1，不划算。

**结论：** 目标 5（`IOGPU.framework`）与目标 6 的 framework 侧标 `BLOCKED`，
解锁条件是方案 1。

### 5.2 不是 BLOCKED，是确证不存在

按 `00-OVERVIEW.md` §7 补充规则 4，下列项不得标 `BLOCKED`：

| 项 | 裁决 | 依据 |
|---|---|---|
| `AppleParavirtIOSurface.kext` 的 x86_64 可执行码 | **确证不存在** | 该 bundle 在 payloadv2 中只有 `Info.plist` 与 `_CodeSignature`；两个 x86_64 kernel collection 的 fileset 条目列表（204 + 172）里都没有它 |
| `AppleParavirtGPUIOGPUFamily.kext` 的 x86_64 可执行码 | **确证不存在** | 同上 |
| `IOMobileGraphicsFamily.kext` / `-DCP.kext` 的 x86_64 可执行码 | **确证不存在** | 同上。这与 `00-OVERVIEW.md` §4.2 的判断一致：该家族属于 ARM 路径 |
| `IOGPUFamily.kext` 的 x86_64 可执行码 | **已取得**（§2.1） | 在 `SystemKernelExtensions.kc` 内，`x86_64` |

即 `IOGPUFamily` 在 x86 上存在，但 `AppleParavirtGPU.kext` 的
`OSBundleLibraries` 不含它；x86 APV 的依赖是
`AppleGraphicsDeviceControl`、`IOAcceleratorFamily2`、`IOGraphicsFamily`、
`IOPCIFamily`、`IOSurface`。符号层面也一致：x86 `AppleParavirtGPU` 里
`AppleParavirtAccelerator` 继承 `IOGraphicsAccelerator2`、
`AppleParavirtFramebuffer` 继承 `IOFramebuffer`，没有 `IOGPUDevice` 相关基类。

### 5.3 仍未关闭的运行证据

**BLOCKED：** 本轮全部结论都是静态的，没有任何 `TESTED`。
目标 guest 内的 Metal probe、`ioreg` 实测与
`/Library/GPUBundles` trust gate 结果仍缺，闭合步骤见
`analysis/spec-work/metal-registration-contract.md` §8.2 与 §8.3。

## 6. `macos26-25G325-x86_64-frameworks` 目录的架构标注裁决

**结论：`raw/`、`analysis-input/`、`idb/`、`metal-objc.json` 的 `x86_64`
标注正确；`plugin-plists/` 的标注误导，须更正。**

### 6.1 正确的部分

§2.4 已逐件用 Mach-O 头确证：6 个映像全是 `x86_64` / cpusubtype 3，
`LC_BUILD_VERSION` 的 macOS 条目都是 minos 26.7.0 / sdk 26.7.1，与
25G325 的其他样本一致。目录 MANIFEST 已写明层级是 BaseSystem，没有冒充
installed SystemOS。这部分没有问题。

### 6.2 误导的部分

`plugin-plists/` 的 18 个 plist 全部来自
`AssetData/payloadv2/payload.050`（`scan-results.json` 自己记录了这一点），
而 **`payloadv2` 是合并资产，不是 x86 资产**。把它们放在一个标着
`x86_64` 的目录下，暗示做过架构筛选，而实际没有。

plist 本身是架构中立的 XML，所以内容没错；错的是"这批样本来自 x86 资产"
这个隐含断言。实际上那 18 个文件里：

- Intel 路径：`AppleParavirtGPU.kext`、`AppleParavirtGPUMetal.bundle`、
  `AMDRadeonX6000MTLDriver.bundle`、`AppleIntelICLGraphics.kext`、
  `AppleIntelICLGraphicsMTLDriver.bundle`、`AppleIntelKBLGraphics.kext`
- Apple Silicon 路径：`AGXG13G`、`AGXG13X`、`AGXG14G`、`AGXG15G`、`AGXG15S`、
  `AGXG16G`、`AGXG17G`、`AGXG17P`、`AGXG17X`、
  `AppleParavirtGPUIOGPUFamily.kext`、`AppleParavirtGPUMetalIOGPUFamily.bundle`
- 两者都有：`IOKitRegistryCompatibility.kext`（其 x86_64 可执行码在
  `BootKernelExtensions.kc` 内，fileset 条目 `com.apple.iokit.IOKitRegistryCompatibility`，
  `vmaddr=0xffffff80026b9000`，`LC_UUID=C783D03F-7627-3EE2-933A-3605F1023D9D`）

这正是任务提出的疑点（`AGXG17G` 与 `AMDRadeonX6000MTLDriver` 同时出现）的
原因，不是提取错误。

### 6.3 "合并资产" 的直接证据

全部来自本轮对 `d3cc6643f7010f6ec14cc728f4a47a7c7644e8a5.zip` 的完整索引
（`payloadv2-payload-map.tsv`、`payloadv2-graphics-index.tsv`）：

| 证据 | 内容 |
|---|---|
| 两套 SU RamDisk | `x86_64SURamDisk.dmg` 272,629,760 与 `arm64eSURamDisk.dmg` 201,326,619 |
| 两套 BaseSystem patch | `basesystem_patches/x86_64BaseSystem.dmg` 与 `arm64eBaseSystem.dmg` |
| 两套 system cryptex patch | `image_patches/cryptex-system-x86_64` 与 `cryptex-system-arm64e` |
| 两套 boot 路径 | Apple Silicon 的 `AssetData/boot/kernelcache.release.mac15j` / `mac16j`，与 Intel 的 `usr/standalone/i386/boot.efi`、`apfs.efi` |
| 两套内核 | `System/Library/Kernels/kernel`（本轮确证 `x86_64`）与 11 个 `kernel.release.t6000…t8142`、`vmapple`（arm64） |
| 用户态二进制是 universal | 本轮 3 件抽取件都是 FAT `x86_64` + `arm64e`（§2.2、§3.4） |

**唯一的单架构部分是预建的 kernel collection：** 资产只有一对
`System/Library/KernelCollections/{Boot,System}KernelExtensions.kc`，两件都是
`x86_64` `MH_FILESET`。Apple Silicon 机型不用它们，而是用上表的
`kernelcache.release.mac1*j`，system KC 在设备上由 `kmutil` 生成。
这恰好是本轮能拿到 x86_64 kext 而拿不到 arm64 kext 的原因。

### 6.4 建议的更正动作

本轮只新增文件，没有改既有文件。下列更正留给维护者：

1. `analysis/idb/macos26-25G325-x86_64-frameworks/plugin-plists/` 应改名或加
   README，说明来源是 25G325 的**合并** `payloadv2` 资产，不是 x86 专属资产。
2. `analysis/spec-work/metal-registration-contract.md` §1.2 里两个
   `*MTLDriver_decompressed` 的构建标注应从 25G325 改为 26.6.x（§3.3）。
3. `analysis/idb/macos26-25G325-arm64/MANIFEST.md` 的 `25G325` 标注应改为
   未确证或改为实测构建（§3.2）。

## 7. 本轮新增产物清单

全部在 `analysis/binaries/macos26-25G325-x86_64/`：

| 子目录 | 件数 | 内容 |
|---|---:|---|
| `kext/` | 9 | 7 个 x86_64 kext 重建件 + `iogdiagnose` 原件与 slice |
| `metal-bundle/` | 4 | 2 个 Metal plugin 的原件与 x86_64 slice |
| `kernel/` | 1 | x86_64 `System/Library/Kernels/kernel` |
| `plists/` | 31 | Info.plist / version.plist / `.elides` / IOPCIFamily.exports / bridgesupport |
| `tools/` | 10 | UDIF、HFS+、YAA1、pbzx、`MH_FILESET`、Mach-O 报告脚本 |
| 根 | 4 | `MANIFEST.md`、`payloadv2-payload-map.tsv`、`payloadv2-graphics-index.tsv`、`payloadv2-full-index.tsv.zip`（458,715 条全量索引） |

来源容器：`SharedSupport.dmg`，18,366,480,610 bytes，SHA-256
`521B8029FB15F2421FFEBEA9F06BE1B147B0EA067AAA2BB90AF552D8AE5F6D25`。
