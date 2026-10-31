# macOS Tahoe 26.7.2 (25G325) x86_64 二进制样本

- 架构：`x86_64`（逐件以 Mach-O 头确证，见下表）
- 来源层级：**installed SystemOS payload**（不是 BaseSystem，不是 recovery，不是运行时抓取）
- 提取日期：2026-10-30
- 提取平台：Windows + Python 3.14，纯只读解析，无 macOS 工具参与
- 工具：`tools/` 下的脚本，全部为本轮新写

本目录只新增文件，没有修改或删除仓库任何既有文件。

## 1. 来源链

```
SharedSupport.dmg                                        18,366,480,610 bytes
  SHA-256 521B8029FB15F2421FFEBEA9F06BE1B147B0EA067AAA2BB90AF552D8AE5F6D25
  UDIF 容器：version 4，flags 0x1，sectorCount 39,160,367
  全部 blkx chunk 类型只有 0x0 / 0x1 / 0x2，即未压缩镜像，可随机访问
  |
  +-- GPT 分区 "disk image (Apple_HFS : 5)"
  |     虚拟扇区 409,640，长度 38,488,544 扇区
  |     虚拟字节偏移 209,735,680
  |     |
  |     +-- HFS+ 卷（签名 H+，version 4，blockSize 4096，81 files / 4 folders）
  |           |
  |           +-- /com_apple_MobileAsset_MacSoftwareUpdate/
  |                 d3cc6643f7010f6ec14cc728f4a47a7c7644e8a5.zip
  |                 18,356,470,215 bytes，单一 extent，起始分配块 328,911
  |                 镜像内虚拟字节偏移 1,556,985,856
  |                 |
  |                 +-- AssetData/payloadv2/payload.NNN   53 个
  |                       pbzx 容器 -> XZ 分块 -> Apple Archive（YAA1）流
  |                       合计 458,715 个条目
```

`payload.NNN` 的内层格式本轮重新解出，记录在 `tools/yaa.py`：每个条目是
`b'YAA1'` + `uint16` 头长度（含 magic 与该字段本身）+ 字段表 + 头后紧跟的
blob 数据。字段为 3 字符键 + 1 字符类型码。`DAT` 存文件内容，`XAT` 存
xattr。本轮用到的类型码：`*`=0 字节、`1/2/4/8`=对应宽度小端整数、
`S`=8 字节、`T`=12 字节、`P`=头内 uint16 长度前缀数据、`A/B/C`=头后 blob
且长度字段宽度分别为 2/4/8 字节。

53 个 payload 全部解析到 `leftover=0`，即字节流被完整消费，没有同步丢失。
47 个抽取件的长度与归档头声明的 `DAT` 长度逐件一致。

### 1.1 用到的 zip 条目

| payload | zip header offset | compress | 压缩字节 | 原始字节 | CRC32 |
|---|---:|---|---:|---:|---|
| `payload.000` | 16,565,631,692 | store | 694,332 | 694,332 | `5BB3382A` |
| `payload.005` | 8,084,971,782 | store | 138,000,632 | 138,000,632 | `CAF619D8` |
| `payload.006` | 17,997,689,099 | deflate | 165,800,749 | 165,850,740 | `6B94EB9D` |
| `payload.024` | 14,881,710,861 | store | 185,242,056 | 185,242,056 | `7630818D` |
| `payload.042` | 3,463,761,565 | store | 154,896,368 | 154,896,368 | `938D1527` |
| `payload.047` | 15,505,451,162 | store | 141,092,188 | 141,092,188 | `A488F991` |
| `payload.050` | 5,089,959,572 | store | 14,797,764 | 14,797,764 | `AFCD0345` |
| `payload.051` | 5,829,289,859 | store | 18,578,124 | 18,578,124 | `831D5E89` |

## 2. 关键结论：目标 kext 没有独立 Mach-O

`payloadv2` 的 458,715 个条目里，下列 kext bundle **只有** `Info.plist`、
`version.plist`、`_CodeSignature/CodeResources`，连 `Contents/MacOS/` 目录条目
都不存在：

`AppleParavirtGPU.kext`、`AppleParavirtGPUIOGPUFamily.kext`、
`AppleParavirtIOSurface.kext`、`IOAcceleratorFamily2.kext`、
`IOGraphicsFamily.kext`（另有 `iogdiagnose` 辅助工具）、`IOGPUFamily.kext`、
`IOSurface.kext`、`IOPCIFamily.kext`、`IOMobileGraphicsFamily.kext`、
`IOMobileGraphicsFamily-DCP.kext`、`AppleGraphicsDeviceControl.kext`。

可执行码全部被链接进两个 kernel collection：

| 容器 | 逻辑路径 | 字节 | 架构 | Mach-O 类型 | `LC_UUID` | SHA-256 | 来源 payload |
|---|---|---:|---|---|---|---|---|
| Boot KC | `System/Library/KernelCollections/BootKernelExtensions.kc` | 67,584,000 | `x86_64` / subtype 3 | `MH_FILESET`，204 个 fileset 条目 | `F6EB5100-67F3-FB2F-6706-BE6A8D30B730` | `AD6F93AF96071D10F7483D1E4268331E2346FE0EC641AC896E03527FC8FDEBF4` | `payload.006` |
| System KC | `System/Library/KernelCollections/SystemKernelExtensions.kc` | 369,213,440 | `x86_64` / subtype 3 | `MH_FILESET`，172 个 fileset 条目 | `EAAB5F23-BA1B-DAF9-781D-6C22A45A9689` | `5EDE2BA5627482282E8964B00B6E17A0F7115F07D799E618DB806FBC60D94421` | `payload.005` |

两个 KC 都是 x86_64 单架构。资产里没有 arm64 的 `.kc`，arm64 机型用
`AssetData/boot/kernelcache.release.mac15j` / `mac16j` 与
`System/Library/Kernels/kernel.release.t60xx` 系列，system KC 在设备上由
`kmutil` 生成。两个 KC 体积合计 436 MB，没有放进仓库；用
`tools/scan.py` 可从 `SharedSupport.dmg` 重建，哈希如上表可校验。

## 3. kext 抽取件（`kext/`）

每件由 `tools/kc.py` 从 KC 的 `LC_FILESET_ENTRY` 重建为独立 Mach-O：保留该
条目自身的 load command 与 `vmaddr`，把 `LC_SEGMENT_64`、section、
`LC_SYMTAB` 的文件偏移改写到新布局，无法随件携带的 linkedit 派生命令
（`LC_DYSYMTAB`、relocation、code signature）清零。

**因此 RVA 与 KC 内一致，符号表可用；但 `__DATA` 指针仍是 collection 级
chained-fixup 编码值，未重定基。** 读 `__DATA` 里的函数指针与 vtable 时必须
按 chained fixup 解码，不能直接当地址用。

每件都内嵌了 collection 共享的 `__LINKEDIT`（约 12.9 MB），所以文件都在
13 MB 量级。这是有意保留：符号名是分析价值的主体。

| 文件 | 字节 | 架构 / subtype | Mach-O 类型 | `LC_UUID` | `LC_SOURCE_VERSION` | SHA-256 | 来源容器 | KC 内 fileoff / vmaddr |
|---|---:|---|---|---|---|---|---|---|
| `kext/com.apple.driver.AppleParavirtGPU` | 13,133,432 | `x86_64` / 3 (ALL) | `MH_KEXT_BUNDLE` | `B88E1D48-71A2-3DC0-8D87-605DDB039B83` | `64.5.0.0.0` | `803615D37075DE5960E0C2B6E16218411BD6EFA5667C701439C69EDAB29954B7` | System KC | `0x14898000` / `0x14898000` |
| `kext/com.apple.iokit.IOAcceleratorFamily2` | 13,526,648 | `x86_64` / 3 | `MH_KEXT_BUNDLE` | `6C4A16B1-66DC-3A8B-9F0B-D3E027B16EB1` | `487.4.4.0.0` | `BDCE06A7DBC6873E66EFF6134C3C3C739EAAD3ED6447D9DFA86CEEC73061F134` | System KC | `0x14b65000` / `0x14b65000` |
| `kext/com.apple.iokit.IOGraphicsFamily` | 13,248,120 | `x86_64` / 3 | `MH_KEXT_BUNDLE` | `74AA6483-8AB4-3A94-8143-5E306C16D7DA` | `600.0.0.0.0` | `219AEB6EE04D762C9FD7341063F5EAB23E02F0A7330E9D096E7D7F81C39A8673` | System KC | `0x14ce4000` / `0x14ce4000` |
| `kext/com.apple.iokit.IOGPUFamily` | 13,330,040 | `x86_64` / 3 | `MH_KEXT_BUNDLE` | `07C66EBC-383D-3A88-A65B-27E94F8CA231` | `130.16.5.0.0` | `1471596A9BDBF80946F06299C6670C1A334B121E637375CF7BD4778BCE371FA0` | System KC | `0x14c91000` / `0x14c91000` |
| `kext/com.apple.AppleGraphicsDeviceControl` | 13,018,744 | `x86_64` / 3 | `MH_KEXT_BUNDLE` | `02FECF8A-3227-3BBB-B0EB-1DB31965ADB9` | `8.1.12.0.0` | `18FE4493C66EE861F436B61DBE469008B3B2EB4FD635DC34D8E06466FF626B32` | System KC | `0x13d3f000` / `0x13d3f000` |
| `kext/com.apple.iokit.IOSurface` | 13,157,866 | `x86_64` / 3 | `MH_KEXT_BUNDLE` | `766DF6D3-1EEC-34DB-A9AD-EF72A36FB2A8` | `393.5.11.0.0` | `E9487381590812B988F3AD517897438546BB1E932C3DE224BCF78FDCA9F409D7` | Boot KC | `0x2a84000` / `0xffffff8002b84000` |
| `kext/com.apple.iokit.IOPCIFamily` | 13,338,090 | `x86_64` / 3 | `MH_KEXT_BUNDLE` | `81D9CF0C-0587-3EC8-B878-E0042113108B` | `726.100.6.0.0` | `DA288A5829A52DB8BA62B16AB37F56D1E889AB938084FF79C0EA56176E5BB59B` | Boot KC | `0x28e9000` / `0xffffff80029e9000` |
| `kext/iogdiagnose.universal` | 136,544 | FAT：`x86_64`/3 + `arm64e`/2 | `MH_EXECUTE` | x86_64 `99915E43-465E-3E59-A346-DD9D24A33B7A`；arm64e `8F985A04-C29C-34E0-9F5B-0C75DB0DAD58` | `600.0.0.0.0` | `71533509F4E2978865EBAEDF418467DCEB9846CE416962266C612D07C2FCABCC` | `payload.047` 原件 | — |
| `kext/iogdiagnose.x86_64` | 46,544 | `x86_64` / 3 | `MH_EXECUTE` | `99915E43-465E-3E59-A346-DD9D24A33B7A` | `600.0.0.0.0` | `881F8677168894093E406C59940B8FA15C35535D670C5D1E0380956067832CDE` | 上一行 slice off 16,384 | — |

### 3.1 符号表可用性与类名确证

| kext | 符号数 | 可见的关键类 |
|---|---:|---|
| `com.apple.driver.AppleParavirtGPU` | 2,220 | `AppleParavirtGPUControl`、`AppleParavirtAccelerator`、`AppleParavirtFramebuffer`、`AppleParavirtDisplayPipe`、`AppleParavirt2DContext`、`AppleParavirtPageTable`、`AppleParavirtResource`，以及基类 `IOGraphicsAccelerator2`、`IOFramebuffer`、`IOAccelContext2`、`IOAccelResource2`、`IOAccelCommandQueue` |
| `com.apple.iokit.IOAcceleratorFamily2` | 4,707 | `IOGraphicsAccelerator2`、`IOAccelDisplayPipe`、`IOAccelLegacyDisplayPipe`、`IOAccelDisplayMachine`、`IOAccelSurface`、`IOAccelSurfaceMTL`、`IOAccelShared2`、`IOAccelSharedUserClient2`、`IOAccelDisplayPipeUserClient2` |
| `com.apple.iokit.IOGraphicsFamily` | 2,114 | `IOFramebuffer`、`IOFramebufferUserClient`、`IOFramebufferSharedUserClient`、`IOFBController`、`IODisplay`、`IODisplayWrangler`、`IOGraphicsWorkLoop`、`IOBootFramebuffer`、`IOGDiagnosticUserClient` |
| `com.apple.iokit.IOGPUFamily` | 3,731 | `IOGPU`、`IOGPUDevice`、`IOGPUDeviceUserClient`、`IOGPUResource`、`IOGPUScheduler`、`IOGPUCommandQueue`、`IOGPUSurfaceMTL`、`IOGPUFenceMachine` |
| `com.apple.iokit.IOSurface` | 2,767 | `IOSurfaceRoot`、`IOSurfaceRootUserClient`、`IOSurface`、`IOSurfaceDescriptor`、`IOSurfaceClient`、`IOSurfaceMemoryPool`、`IOSurfaceRootParavirtMapperInterface`、`IOFenceTransaction` |

`AppleParavirtAccelerator` 继承 `IOGraphicsAccelerator2`、`AppleParavirtFramebuffer`
继承 `IOFramebuffer`，与 `00-OVERVIEW.md` 第 4.2 节的判断一致：x86 路径走
**IOAcceleratorFamily2 + IOGraphicsFamily**，不走 IOGPUFamily / IOMobileFramebuffer。

## 4. Metal plugin bundle（`metal-bundle/`）

这是本轮唯一以**原生独立 Mach-O** 形式存在于 payload 的目标，取自
`payload.042`，字节与归档内容完全一致。

| 文件 | 字节 | 架构 / subtype | Mach-O 类型 | `LC_UUID` | `LC_SOURCE_VERSION` | platform | SHA-256 |
|---|---:|---|---|---|---|---|---|
| `metal-bundle/AppleParavirtGPUMetal.universal` | 808,272 | FAT：`x86_64`/3 + `arm64e`/2 (caps `0x80`) | `MH_BUNDLE` | x86_64 `15DB02D8-D7E6-30A1-979C-DFD657E47F19`；arm64e `46514AE2-B7A4-3D78-8DCB-4B44FDEEE6C3` | `64.5.0.0.0` | macOS minos 26.7.0 / sdk 26.7.1 | `42A413EC5F9B11974BC0E788A21DAE3B5A10981B5ECF8F8AF488E461901B5AD0` |
| `metal-bundle/AppleParavirtGPUMetal.x86_64` | 380,688 | `x86_64` / 3 | `MH_BUNDLE` | `15DB02D8-D7E6-30A1-979C-DFD657E47F19` | `64.5.0.0.0` | macOS minos 26.7.0 / sdk 26.7.1 | `71423441A9CD4055224AF18D2DCDECA59139640748D07079572630539E948BAF` |
| `metal-bundle/AppleParavirtGPUMetalIOGPUFamily.universal` | 1,012,992 | FAT：`x86_64`/3 + `arm64e`/2 | `MH_BUNDLE` | x86_64 `C1EE81DD-EDB4-3DE1-9EAD-6C82F4800AA6`；arm64e `CBA08755-62C9-3105-9194-32EA2DAECBEA` | `64.5.0.0.0` | macOS minos 26.7.0 / sdk 26.7.1 | `EC5E4104033C69B40504ABBBB75A37C1E12E840FEC4A5694EB134E9A74884C76` |
| `metal-bundle/AppleParavirtGPUMetalIOGPUFamily.x86_64` | 487,696 | `x86_64` / 3 | `MH_BUNDLE` | `C1EE81DD-EDB4-3DE1-9EAD-6C82F4800AA6` | `64.5.0.0.0` | macOS minos 26.7.0 / sdk 26.7.1 | `266EF0EFC29C8B6CA3F660969542A60254CC489321F5EE92A2601173DDFABB3D`

`.universal` 是归档原件，`.x86_64` 是 fat slice（偏移 16,384）的逐字节拷贝，
两者的 x86_64 `LC_UUID` 相同。做 x86 决策用 `.x86_64`；要证明来源完整性用
`.universal`。

两个 bundle 都同时含 x86_64 与 arm64e 代码，所以 **ARM 路径的
`AppleParavirtGPUMetalIOGPUFamily` 也有一份合法的 x86_64 代码**，可作
ObjC 侧对照；但它配对的 kext（`AppleParavirtGPUIOGPUFamily`）不在 x86_64 KC
里，x86 guest 上不会被加载。

## 5. 内核（`kernel/`）

| 文件 | 字节 | 架构 / subtype | Mach-O 类型 | `LC_UUID` | `LC_SOURCE_VERSION` | platform | SHA-256 | 来源 |
|---|---:|---|---|---|---|---|---|---|
| `kernel/kernel.x86_64` | 19,008,056 | `x86_64` / 3 | `MH_EXECUTE` | `E514CEBA-9206-34D5-86C2-64E880FDDA2B` | `12377.161.15.701.48` | macOS minos 26.7.1 / sdk 26.7.1 | `B3161C243158355226E677CC2B44A5F43397E5DC94CC28F5A7B00028E29DE4F1` | `payload.024`，逻辑路径 `System/Library/Kernels/kernel` |

同一 payload 里另有 `kernel.release.t6000/t6020/t6030` 与 `payload.025` 的
`t6031/t6041/t6050/t8103/t8112/t8122/t8132/t8140/t8142/vmapple`，都是 arm64
内核，本轮未抽取。

## 6. plist 与元数据（`plists/`）

31 个文件，文件名是逻辑路径以 `__` 替换 `/`。全部来自 `payload.050` 与
`payload.051`，`AFT=8` 表示在目标卷上以 AppleFSCompression 存储，归档内存的是
解压后的原始内容，不需要 ZBM/decmpfs 解码。

交叉校验：`AppleParavirtGPU.kext/Contents/Info.plist` 的 SHA-256
`1CE54F84BC97B9542E9AC638CBDDEAC756F10AC0581A59BE516BE9BC5DAEA039` 与
`AppleParavirtGPUMetal.bundle/Contents/Info.plist` 的
`A635FB1C1C14A4089889FB5EE93B7800EB9708BDE5FB99390950BA661350035C`
和 `analysis/spec-work/metal-registration-contract.md` 第 4.3 节既有记录
逐位相同，说明本轮管线与上一轮取到的是同一来源。

从 x86 `Info.plist` 读出的依赖关系（`OSBundleLibraries`）：

| kext | version | `OSBundleRequired` | 依赖 |
|---|---|---|---|
| `com.apple.driver.AppleParavirtGPU` | 15.0.0 | 未声明 | `AppleGraphicsDeviceControl`、`IOAcceleratorFamily2`、`IOGraphicsFamily`、`IOPCIFamily`、`IOSurface`、`kpi.iokit/libkern/mach/private` |
| `com.apple.iokit.IOAcceleratorFamily2` | 487.4.4 | `Safe Boot` | `AppleMobileFileIntegrity`、`IOGraphicsFamily`、`IOPCIFamily`、`IOReportFamily`、`IOSurface`、`kpi.*` |
| `com.apple.iokit.IOGraphicsFamily` | 600 | `Safe Boot` | `IOPCIFamily`、`kpi.*` |
| `com.apple.iokit.IOSurface` | 393.5.11 | `Console` | 仅 `kpi.*` |

`AppleParavirtGPU.kext` 的唯一 personality：`IOClass=AppleParavirtGPUControl`、
`IOProviderClass=IOPCIDevice`、`IOMatchCategory=IOFramebuffer`、
`IOPCIMatch=0xEEEE106B`。
`IOSurface.kext` 的 personality：`IOClass=IOSurfaceRoot`、
`IOProviderClass=IOResources`、`IOMatchCategory=IOSurfaceRoot`。
`IOGraphicsFamily.kext` 的 personality：`IODisplayWrangler`（provider
`IOResources`，category `IOGraphics`）、`AppleDisplay`、`AppleBacklightDisplay`
（provider `IODisplayConnect`）。

## 7. 索引产物

| 文件 | 内容 |
|---|---|
| `payloadv2-payload-map.tsv` | 53 个 payload 的条目数与首尾逻辑路径，合计 458,715 条 |
| `payloadv2-graphics-index.tsv` | 626 条与图形栈相关的条目：逻辑路径、类型、`DAT` 字节数、mode、BSD flags、decmpfs 类型、xattr 字节数、所属 payload |
| `payloadv2-full-index.tsv.zip` | 全部 458,715 条，列同上。解压后 69,565,757 bytes。用它查"某路径在 25G325 里存不存在、在哪个 payload"，不必重跑 15 分钟的全量扫描 |

`payloadv2-graphics-index.tsv` 是"某文件在这份资产里到底存不存在"的直接依据。
它证明 `IOGPU.framework/Versions/A/IOGPU`、`IOSurface.framework/Versions/A/IOSurface`、
`IOAccelerator.framework/Versions/A/IOAccelerator` 这三条路径在 payloadv2 中
**只有目录、符号链接与 Resources**，没有可执行映像。

## 8. 工具（`tools/`）

| 脚本 | 职责 |
|---|---|
| `udif.py` | 未压缩 UDIF (.dmg) 的随机访问读取与分区表 |
| `hfsplus.py` | HFS+ 卷头与 catalog B 树遍历，输出 fork extent |
| `vfile.py` | 把 HFS+ fork 包装成可 seek 的文件对象，供 `zipfile` 直接用 |
| `yaa.py` | Apple Archive（`YAA1`）条目头解析 |
| `scan.py` | 遍历全部 payload，产生条目索引并按 substring 抽取目标 |
| `extract_one.py` | 从指定 payload 精确抽取指定逻辑路径 |
| `kc.py` | `MH_FILESET` kernel collection 的条目枚举与单 kext 重建 |
| `extract_kexts.py` | 本轮 7 个 kext 的抽取驱动 |
| `thin.py` | 从 universal Mach-O 取出 x86_64 slice |
| `macho.py` | Mach-O 头、`LC_UUID`、source version、platform 与 SHA-256 报告 |

复现步骤：把 `tools/` 复制到临时目录，先 `py scan.py payload.005 payload.006`
得到两个 `.kc`，再 `py extract_kexts.py`，最后
`py extract_one.py payload.024 'System/Library/Kernels/kernel'`。
不要在仓库目录内跑，中间产物有 436 MB。

## 9. 未取得的目标

见 `docs/spec/90-EVIDENCE-INDEX.md` 第 5 节，内含阻断点、缺失工具与最小替代方案。

---

## 10. 追加（2026-10-30，第四轮 / 分册 `32-COMPILER-PLUGIN.md`）

本节只新增记录，没有修改本文件上面任何内容，也没有改动本目录既有文件。

### 10.1 新增样本：Metal compiler plugin

| 文件 | 字节 | arch / subtype | Mach-O 类型 | `LC_UUID` | `LC_SOURCE_VERSION` | platform | `LC_ID_DYLIB` | SHA-256 |
|---|---:|---|---|---|---|---|---|---|
| `metal-bundle/libMTLIGCCompilerPlugin.dylib` | 146,000 | `x86_64h` / 8 (Haswell) | `MH_DYLIB` | `C2C53566-81C9-303D-BA51-FD34BFF5CBE4` | `24.5.10.0.0` | macOS minos 10.15.0 / sdk 26.7.1 | `/usr/local/lib/libMTLIGCCompilerPlugin.dylib` | `F72D7F2A2249EB993CDE6F407E222432D13E709321E23820AB157C5F4C657058` |

逻辑路径 `System/Library/Extensions/AppleIntelGraphicsShared.bundle/Contents/MacOS/libMTLIGCCompilerPlugin.dylib`，
来自 **`payload.047`**。原件就是 thin（非 FAT），因此未经过 `tools/thin.py`；
元数据由 `tools/macho.py` 的 `report()` 产生。抽取命令：

```powershell
py tools\extract_one.py payload.047 "System/Library/Extensions/AppleIntelGraphicsShared.bundle/Contents/MacOS/libMTLIGCCompilerPlugin.dylib"
```

**为什么它放在 `metal-bundle/`**：它和 `AppleParavirtGPUMetal` 装在 `MTLCompiler` 的同一个插槽上
（`-[MTLCompiler initWithTargetData:cacheUUID:pluginPath:device:compilerFlags:]` 的 `pluginPath`），
是 Metal driver plugin 家族的一员，不是 Intel 驱动本体。
它导出 4 个 `MTLCompiler*` + 36 个 `AIRNT*` C 符号，是 compiler plugin 接口的实现样本。
详见 `docs/spec/32-COMPILER-PLUGIN.md` 第 5 节。

### 10.2 索引结论：`libAppleParavirtCompilerPlugin.dylib` 不在 payloadv2

`payloadv2-full-index.tsv.zip` 的 458,715 条中：

- `CompilerPlugin` 的**唯一**文件命中就是第 10.1 节那一条。
- `System/Library/Extensions/AppleParavirtGPUMetal.bundle/Contents/Resources/`
  **只有目录条目**（`D 0 493 524288 … payload.000`），其下零个文件条目。
  同 bundle 名下只有 3 个文件：`Contents/MacOS/AppleParavirtGPUMetal`（payload.042）、
  `Contents/Info.plist`、`Contents/version.plist`（payload.050）。
- `AppleParavirtGPUMetalIOGPUFamily.bundle` 同形。

该文件实际在 **dyld shared cache** 内（`metal_drivers/dyld_shared_cache_x86_64.map.txt` 第 8507 行，
`__TEXT 0x7FFB0A22F000 -> 0x7FFB0A23033C`，仅 4,924 字节）。
因此 `docs/spec/21-OBJC-OBJECT-FAMILY.md` 第 12.4 节给出的"从 payloadv2 按路径抽取"**不成立**。
阻断点与最小取得路径见 `docs/spec/32-COMPILER-PLUGIN.md` 第 1.3 节、
`analysis/idb/macos26-25G325-x86_64/MANIFEST-32-COMPILER-PLUGIN.md` 第 4 节。

### 10.3 本轮新用到的 zip 条目

| 条目 | zip header offset | compress | 字节 | SHA-256 |
|---|---:|---|---:|---|
| `AssetData/payloadv2/payload.047` | 15,505,451,162 | store | 141,092,188 | （见第 1.1 节） |
| `AssetData/payloadv2/basesystem_patches/x86_64BaseSystem.dmg` | 6,867,904,670 | store | 891,864,876 | `35745579C8FBC20ABBD98E5954B70BE22F329DF199D06429604A042F8765827E` |

后者是 `BXDIFF50` 全量替换补丁；用 `ipsw 3.1.739 ota patch bxdiff -s` 重建出的 BaseSystem DMG 为
1,464,270,504 bytes，SHA-256 `642E6148288527C51639D1B08C7F0B5A8CB4A68AEC2AC6DA3C78CF1723C5119A`，
**与 `analysis/spec-work/metal-registration-contract.md` 第 1.1 节既有记录逐位相同**。
该 DMG 与其 APFS 分区镜像留在 `$env:TEMP`，按本文件第 8 节的约定不入库。
