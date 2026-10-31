# MANIFEST — 分册 `21-OBJC-OBJECT-FAMILY.md` 的分析产物

本文件只登记本轮**新增**的产物。本目录下既有文件（`MANIFEST-10-KERNEL-ACCELERATOR.md`、`MANIFEST-display-iosurface.md` 及其 `.i64`）未被改动。

## 1. 新增 IDB

| 文件 | 大小 | SHA-256 |
|---|---|---|
| `AppleParavirtGPUMetal-apvmetal.i64` | 7052494 | `41C5C294AC01B09555C960CD2B517AE84F02BC57DADF8E7A305A8C646316F617` |

建库输入：

| 项 | 值 |
|---|---|
| 源文件 | `analysis/binaries/macos26-25G325-x86_64/metal-bundle/AppleParavirtGPUMetal.x86_64` |
| 源文件 SHA-256 | `71423441A9CD4055224AF18D2DCDECA59139640748D07079572630539E948BAF` |
| 源文件大小 | 380688 |
| `LC_UUID` | `15DB02D8-D7E6-30A1-979C-DFD657E47F19` |
| `mach_header.filetype` | `0x8`（`MH_BUNDLE`） |
| arch | x86_64 |
| image base | `0x0`（RVA == 文件内偏移） |
| IDA 自动分析识别函数数 | 1080 |
| 分析日期 | 2026-10-30 |
| 分析方式 | 源文件复制到 `$env:TEMP\apvmetal-objc-family\` 后建库，`.i64` 另存入本目录；源目录与既有 IDB 未改动 |

本样本对应分册 `21-OBJC-OBJECT-FAMILY.md` 第 0 节的样本代号 **`S-APV`**。

## 2. 本轮只读使用、未新增产物的样本

| 代号 | 文件 | 用法 |
|---|---|---|
| `S-METAL` | `analysis/idb/macos26-25G325-x86_64-frameworks/idb/Metal-BaseSystem-analysis.i64` | 复制到 `$env:TEMP` 后打开，取 `_MTLDevice` / `_MTLLibrary` / `MTLCompiler` 的反编译与 `__objc_protolist` 的 type encoding。**原 IDB 未改动、未另存。** UUID `FDB3FD2C-840A-3FC3-81FB-C524F891F642`，image base `0x7FF80B179000` |
| `S-DUMP` | `analysis/idb/macos26-25G325-x86_64-frameworks/metal-objc.json` | 只读。UTF-16LE 文本，144 个 `@protocol` 块，提供方法名；与 `S-METAL` 的协议元数据同序（分册 `21` 第 0.2 节验证） |

## 3. 关键 RVA 索引（便于复查）

`S-APV`（base = 0）：

| 符号 | RVA |
|---|---|
| `-[AppleParavirtDevice initWithAcceleratorPort:]` | `0xA30F` |
| `-[AppleParavirtDevice setupCompiler]` | `0xA459` |
| `-[AppleParavirtDevice setupDeviceInfo]` | `0xA7CA` |
| `-[AppleParavirtDevice featureProfile]` | `0xACC3`（`return 10000`） |
| `-[AppleParavirtDevice llvmVersion]` | `0xB04F`（`return 32023`） |
| `-[AppleParavirtDevice newVertexVariantWithCompilerOutput:pipelineStatisticsOutput:]` | `0xAF05` |
| `-[AppleParavirtDevice newRenderPipelineWithDescriptor:vertexVariant:fragmentVariant:errorMessage:]` | `0xAFB0` |
| `-[AppleParavirtDevice newComputePipelineWithDescriptor:variant:errorMessage:]` | `0xB008` |
| `-[AppleParavirtFunctionVariant initWithCompilerOutput:device:functionType:]` | `0x30CF` |
| `__objc_classlist` | `0x416E0`..`0x417C0`（28 个类） |
| `__objc_protolist` | `0x417C0`..`0x41950`（50 个协议定义副本） |
| `IOConnectCallMethod` stub | `0x1C43E`（17 个调用点，私有 selector `0x100`..`0x106`） |

`S-METAL`（base = `0x7FF80B179000`）：

| 符号 | RVA |
|---|---|
| `-[_MTLDevice newLibraryWithData:error:]` | `0x276A6` |
| `-[_MTLDevice newRenderPipelineStateWithDescriptor:error:]` | `0x1D185` |
| `-[_MTLDevice newComputePipelineStateWithDescriptor:error:]` | `0x25095` |
| `-[_MTLDevice argumentBuffersSupport]` | `0x3A82` |
| `-[_MTLDevice indirectArgumentBufferCapabilities]` | `0x11AB48`（`return 0`） |
| `-[_MTLDevice compiler]` | `0x119DF4`（`return nil`） |
| `-[_MTLDevice vertexVariantWithCompilerOutput:pipelineStatisticsOutput:]` | `0x11A20C`（`return nil`） |
| `-[_MTLDevice newRenderPipelineWithDescriptor:vertexVariant:fragmentVariant:]` | `0x11A21E`（`return nil`） |
| `-[_MTLDevice newComputePipelineWithDescriptor:variant:]` | `0x11A230`（`return nil`） |
| `-[_MTLLibrary newFunctionWithName:]` | `0x1C6D3` |
| `-[_MTLLibrary newFunctionWithNameInternal:]` | `0x1C726` |
| `-[MTLCompiler newRenderPipelineStateWithDescriptor:options:reflection:error:completionHandler:]` | `0x1D534` |
| `-[MTLCompiler newRenderPipelineStateWithDescriptorInternal:options:reflection:destinationBinaryArchive:error:compilerTask:completionHandler:]` | `0x18F8A6` |

## 4. 缺口

| 项 | 状态 |
|---|---|
| `libAppleParavirtCompilerPlugin.dylib` | **未取得**。全盘搜索 `*CompilerPlugin*` 零命中。应从 `InstallAssistant.pkg` payload 的 `System/Library/Extensions/AppleParavirtGPUMetal.bundle/Contents/Resources/` 抽取。分册 `21` 第 12.4 节 |
| `S-METAL` 的 selector 名字 | **不可解析**（dyld cache selector 外置）。分册 `21` 第 12.1 节给出三条取得路径 |
| `S-APV` 与 `S-METAL` 是否同轮构建 | 未比对。`S-APV` 记录的 `MTLIOAccelDevice` `instanceSize` 是 `0xD400`，`S-METAL` 的 ivar 排到 `0xD490`。分册 `21` 第 12.5 节 |
