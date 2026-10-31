# 32 — Compiler plugin 边界：`MTLCompiler` 与厂商 compiler plugin 的 ABI

文档版本：1.0
基线：macOS Tahoe 26.7.2 / build 25G325 / **x86_64**
归属：本分册是 `00-OVERVIEW.md` 第 8 节分册表的新增项，填补 `21-OBJC-OBJECT-FAMILY.md` 第 12.3、12.4 节两个 `BLOCKED`
配套分册：`21-OBJC-OBJECT-FAMILY.md`（驱动侧 5 个 selector）、`30-SHADER-AIR.md`（AIR 解析）、`31-PIPELINE-ARTIFACT.md`（产物消费契约）

## 0. 本文回答的问题与一句话结论

`21-OBJC-OBJECT-FAMILY.md` 第 2.4.1 节确证驱动是用
`[[MTLCompiler alloc] initWithTargetData:cacheUUID:pluginPath:device:compilerFlags:32]`
把自己的编译器插进 Metal 的，但 `pluginPath` 指向的那个 dylib 与它的接口完全没有文档。本文把这条链整条打开。

一句话结论：**compiler plugin 收到的是 AIR LLVM bitcode 原始字节（指针 + 长度），不是 Metal 预先解析过的 IR。** 它必须自己 `llvm::parseBitcodeFile`、自己读 `air.*` named metadata，并且必须导出一张 **40 个 C 符号的平坦函数表**（4 个 `MTLCompiler*` + 36 个 `AIRNT*`），返回一块**完全由厂商定义的不透明字节**。因此 `30-SHADER-AIR.md` 的 AIR→SPIR-V 工作整体属于 plugin 侧；需要调整的只是范围（见第 9 节）。

### 0.1 样本

| 代号 | 文件 | LC_UUID / 哈希 | arch | filetype | image base |
|---|---|---|---|---|---|
| `S-METAL` | `analysis/idb/macos26-25G325-x86_64-frameworks/idb/Metal-BaseSystem-analysis.i64` | `FDB3FD2C-840A-3FC3-81FB-C524F891F642` | x86_64 | `MH_DYLIB` | `0x7FF80B179000` |
| `S-IGCPLUG` | `analysis/binaries/macos26-25G325-x86_64/metal-bundle/libMTLIGCCompilerPlugin.dylib` | `C2C53566-81C9-303D-BA51-FD34BFF5CBE4`；SHA-256 `F72D7F2A2249EB993CDE6F407E222432D13E709321E23820AB157C5F4C657058`；146,000 bytes | **x86_64h**（subtype 8） | `MH_DYLIB` | `0x0` |
| `S-APV` | `analysis/binaries/macos26-25G325-x86_64/metal-bundle/AppleParavirtGPUMetal.x86_64` | `15DB02D8-D7E6-30A1-979C-DFD657E47F19` | x86_64 | `MH_BUNDLE` | `0x0` |
| `S-INDEX` | `analysis/binaries/macos26-25G325-x86_64/payloadv2-full-index.tsv.zip`（458,715 条） | — | — | TSV | — |
| `S-DSCMAP` | `metal_drivers/dyld_shared_cache_x86_64.map.txt` | SHA-256 `9E2BAB27E0478A03D4728E0572B24BEFF6F619A1A07307B0537537E9BC80ECDD`；3,609 个 image | x86_64 | `dyld_shared_cache_util -map` 文本 | — |
| `S-BASESYS` | 本轮重建的 `x86_64BaseSystem.dmg`（在 `$env:TEMP`，未入库） | 1,464,270,504 bytes；SHA-256 `642E6148288527C51639D1B08C7F0B5A8CB4A68AEC2AC6DA3C78CF1723C5119A` | — | UDIF / Apple_APFS | — |

`S-IGCPLUG` 是本轮新抽件，来源见第 1 节。`S-BASESYS` 的 SHA-256 与
`analysis/spec-work/metal-registration-contract.md` 第 1.1 节既有记录**逐位相同**，
因此本轮的解包管线与上一轮同源。

新增 IDB：`analysis/idb/macos26-25G325-x86_64/libMTLIGCCompilerPlugin-compilerplugin.i64`。
`analysis/idb/` 下既有文件一个未改。`S-METAL` 以**复制件**打开（`$env:TEMP`），原件未被写回。

地址一律写成 `样本代号 + RVA`。证据标签定义见 `00-OVERVIEW.md` 第 7 节。

### 0.2 架构标注的一处例外

`S-IGCPLUG` 是 **x86_64h**（Haswell），不是 x86_64。它是 Intel 图形栈的共享件，`AppleIntelICLGraphicsMTLDriver` / `AMDRadeonX6000MTLDriver` 也都是 x86_64h（见 `21` 第 0 节的 `S-INTEL`）。
本文从它取的是**接口形状与调用约定**（C 符号名、参数个数与语义），这部分与 subtype 无关。
凡涉及具体数值常量（arch 枚举、版本号）均单独标注为 Intel 专有，不作为本项目取值依据。

---

## 1. `libAppleParavirtCompilerPlugin.dylib`：确证位置，但未取得

### 1.1 它不在 payloadv2 里（索引级确证）

`KNOWN`。`S-INDEX` 全量 458,715 条中，`AppleParavirtGPUMetal.bundle` 名下只有 **3 个文件条目**：

```
System/Library/Extensions/AppleParavirtGPUMetal.bundle/Contents/MacOS/AppleParavirtGPUMetal   F  808272   payload.042
System/Library/Extensions/AppleParavirtGPUMetal.bundle/Contents/Info.plist                    F  1520     payload.050
System/Library/Extensions/AppleParavirtGPUMetal.bundle/Contents/version.plist                 F  472      payload.050
```

`Contents/Resources` 在索引中**只有目录条目**（`D 0 493 524288 … payload.000`），其下零个文件条目。
全量索引中 `CompilerPlugin` 的唯一命中是 Intel 的那一个（第 1.2 节）。
`AppleParavirtGPUMetalIOGPUFamily.bundle` 同形。

因此 `21-OBJC-OBJECT-FAMILY.md` 第 12.4 节给出的取得方法（"从 payloadv2 按路径抽取，full-index 应能定位"）**不成立，应作废**。

### 1.2 它在 dyld shared cache 里（map 级确证）

`KNOWN`（存在与路径）/ `BLOCKED`（Mach-O 未取得）。`S-DSCMAP` 第 8507 行起：

```
/System/Library/Extensions/AppleParavirtGPUMetal.bundle/Contents/Resources/libAppleParavirtCompilerPlugin.dylib
        __TEXT       0x7FFB0A22F000 -> 0x7FFB0A23033C      (0x133C = 4,924 bytes)
        __DATA_CONST 0x7FFB416CF230 -> 0x7FFB416CF3C0      (0x190 =   400 bytes)
        __DATA       0x7FFB43D9AA10 -> 0x7FFB43D9AA28      (0x18  =    24 bytes)
```

同一 map 还含 ARM 路径的对应件
`AppleParavirtGPUMetalIOGPUFamily.bundle/Contents/Resources/libAppleParavirtCompilerPluginIOGPUFamily.dylib`。

这解释了第 1.1 节的"空 Resources 目录"：macOS 13 起，落在 dyld shared cache 里的 dylib 会从磁盘删除，
`dlopen` 由 cache 命中（`-[MTLCompiler initWithTargetData:…]` 的 `pluginPath` 只是一个 cache key，不要求文件存在；
Intel plugin 自己也导入 `__dyld_shared_cache_contains_path`，见第 5.6 节）。

**4,924 字节 `__TEXT` + 400 字节 `__DATA_CONST` 这个体量本身是一条结论**：APV 的 plugin 不可能内含编译器。
`__DATA_CONST` 400 字节 ≈ 50 个指针，与第 5.1 节那张 40 项函数表的量级一致。
`INFERRED`：APV plugin 是一层薄转发，真正的 AIR→目标码由 `GPUCompiler.framework`（同 cache 内，紧邻 `libsrc2module.dylib`）完成。

### 1.3 为什么本轮没拿到：精确阻断点

`BLOCKED`。本轮已经做到：

1. 从 `SharedSupport.dmg` 内层 OTA zip 取出 `AssetData/payloadv2/basesystem_patches/x86_64BaseSystem.dmg`
   （891,864,876 bytes，zip **stored**，header offset 6,867,904,670；SHA-256 `35745579C8FBC20ABBD98E5954B70BE22F329DF199D06429604A042F8765827E`）。
   该文件是 `BXDIFF50` 全量替换补丁：magic 后 `+0x08` ControlSize = 0、`+0x10` PatchedFileSize = 1,464,270,504、`+0x18` DiffSize = 0、`+0x20` ExtraSize = 891,864,816。
2. `ipsw 3.1.739 ota patch bxdiff -s` 重建出 `S-BASESYS`，长度与 SHA-256 均与既有记录一致。
3. `ipsw disk dmg -p 3` 取出其 `Apple_APFS` 分区原始镜像（1,396,506,624 bytes）。
4. 在该分区中扫到目标文件名条目与两份 cache 的 UUID 明文：
   - `dyld_shared_cache_x86_64` → UUID `B1090D84-48D4-3D45-94E6-A5C7F9CE7DE7`
   - `dyld_shared_cache_x86_64.01` → UUID `ADDD15FF-C4C5-36EC-8ED1-88BB9F5C8F49`
   两者与 `metal-registration-contract.md` 第 1.1 节记录一致。

**阻断点**：这两个 cache 文件在该 APFS 卷上以 **AppleFSCompression (decmpfs) 存储**。
分区内每个 cache 的 inode 旁都带 `com.apple.decmpfs` 与 `com.apple.ResourceFork` 两个 xattr，
decmpfs 头为 `'fpmc'` + `compression_type = 8`（= LZVN，压缩数据在 resource fork）。
`dyld_v1  x86_64` 这个 16 字节 magic 能被扫到，正是因为 LZVN 的 literal run 把它原样放过；
紧随其后的 `mappingCount` 等字段已是 LZVN 回引用 token，直接解析必然得到垃圾值
（实测 `mappingOffset = 0x228` 可信，`mappingCount` 解出 `0x01380004`）。

要闭合需要两件本仓库没有的东西：APFS B 树遍历 + resource fork 读取，以及 LZVN 解压。
**不要为此在 Windows 上重写这两样。** 最小代价路径按成本排序：

1. 在任意 macOS/Linux 分析机上挂载 `S-BASESYS`（已重建，1.46 GB，可直接拷过去），
   复制 `/System/Library/dyld/dyld_shared_cache_x86_64` 与 `.01`，再
   `ipsw dyld extract <primary> /System/Library/Extensions/AppleParavirtGPUMetal.bundle/Contents/Resources/libAppleParavirtCompilerPlugin.dylib`。
   **同一步必须顺带抽出 `/System/Library/PrivateFrameworks/MTLCompiler.framework/Versions/32023/MTLCompiler`**（见第 4 节，它是本文唯一剩下的 `BLOCKED` 的另一半）。
2. 在 25G325 x86_64 guest 内直接取 `/System/Library/dyld/dyld_shared_cache_x86_64*`。与 `90-EVIDENCE-INDEX.md` 第 5 节的取证步骤合并。
3. 退而求其次：`nm -gU` 一下 plugin 即可核对第 5.1 节那张表，不必反编译。

### 1.4 替代样本：Intel 的 compiler plugin（已取得）

`KNOWN`。`S-INDEX` 中 `CompilerPlugin` 的唯一文件命中：

```
System/Library/Extensions/AppleIntelGraphicsShared.bundle/Contents/MacOS/libMTLIGCCompilerPlugin.dylib   F  146000  payload.047
```

本轮用仓库既有 `analysis/binaries/macos26-25G325-x86_64/tools/extract_one.py` 抽出，
字节数与归档头声明一致，入库为 `metal-bundle/libMTLIGCCompilerPlugin.dylib`。

**它和 APV 的 plugin 装在 `MTLCompiler` 的同一个插槽上。** 证据三条：
文件名同构（`libMTL**IGC**CompilerPlugin.dylib` ↔ `libAppleParavirt**CompilerPlugin**.dylib`）；
源文件名 `MTLIntelCompilerPlugin.cpp`（assert 串，`S-IGCPLUG` 字符串表）；
导出 `MTLCompilerCreate` / `MTLCompilerBuildRequestWithSerializedBitcode` /
`MTLCompilerReleaseReply` / `MTLCompilerDelete` 这组只在该接口下成立的符号（第 5.1 节）。
**未直接验证**的是 Intel device 的 `setupCompiler` 等价代码是否真的把这条路径传给
`-[MTLCompiler initWithTargetData:…pluginPath:…]`（`S-INTEL` 未在本轮打开）；标 `INFERRED`（强）。
因此 Intel 件是"plugin 侧 ABI 的实现样本"，本文第 5 节全部取自它。
注意它是**插件接口的一种实现**，不是接口定义本身；接口定义在 `MTLCompiler.framework`（`BLOCKED`）。
两者差异只可能出现在"MTLCompiler 实际 `dlsym` 了哪几个符号"上，不会出现在"符号的签名"上。

---

## 2. 整条链：从 `newRenderPipelineStateWithDescriptor:` 到 plugin

`KNOWN`，除标注外。

```
应用
 └─ [device newRenderPipelineStateWithDescriptor:d error:&e]        S-METAL +0x1D185   (_MTLDevice)
     ├─ c = [self compiler]                                         基类 return nil  S-METAL +0x119DF4
     │                                                              驱动必须覆写（21 第 2.3 节）
     └─ [c newRenderPipelineStateWithDescriptor:options:reflection:error:completionHandler:]
                                                                    S-METAL +0x1D534   (MTLCompiler, ObjC, 在 Metal.framework 内)
         └─ -[MTLCompiler newRenderPipelineStateWithDescriptorInternal:…]      +0x18F8A6
             ├─ MTLGetCompilerOptions(device, descOptions, _compilerFlags, …)  +0x17B18B
             ├─ -[MTLCompiler createVertexStageAndLinkPipelineWithFragment:fragmentVariant:…]  +0x18DE91
             └─ MTLCompilerConnectionManagerInternal::buildRequest(…)          +0x1302EE / +0x1302F4
                 ├─ MTLXPCCompilerConnection          （跨进程：MTLCompilerService）  +0x3CB88…
                 └─ MTLMonolithicCompilerConnection    （同进程）
                     └─ MTLMonolithicCompilerConnection::attemptLazyInit()      +0x3DAD6
                         └─ new CompilerPluginInterface(llvmVersion)            +0x3DCE6
                             ├─ dlopen("/System/Library/PrivateFrameworks/MTLCompiler.framework/Versions/<llvmVersion>/MTLCompiler", RTLD_NOW|RTLD_LOCAL)
                             └─ dlsym × 4：MTLCodeGenServiceCreate / Destroy / BuildRequest / SetPluginPath
                                 └─ （MTLCompiler.framework 内，BLOCKED）
                                     dlopen(pluginPath) + 解析第 5.1 节的 40 个符号
                                     └─ libAppleParavirtCompilerPlugin.dylib / libMTLIGCCompilerPlugin.dylib
                                         └─ AIRNTEmitPipelineImage → MTLCompilerBuildRequestWithSerializedBitcode
                                             └─ 自己 llvm::parseBitcodeFile(AIR)
         └─ 回到 MTLCompiler：拿到 dispatch_data_t 不透明产物
             ├─ [device newVertexVariantWithCompilerOutput:pipelineStatisticsOutput:]    ← 驱动
             ├─ [device newFragmentVariantWithCompilerOutput:pipelineStatisticsOutput:]  ← 驱动
             └─ [device newRenderPipelineWithDescriptor:vertexVariant:fragmentVariant:errorMessage:]  ← 驱动
```

**本项目有两个插入点，不是一个**：
① 驱动侧 5 个 selector（`21` 第 2 节已收口）；② compiler plugin 的 40 个 C 符号（本文第 5 节）。
两者之间走的是 Metal 自己的管道，本项目不碰。

有一个绕开②的办法，见第 8.4 节（覆写 `compiler` 返回自制对象），但代价更大。

---

## 3. `-[MTLCompiler initWithTargetData:cacheUUID:pluginPath:device:compilerFlags:]` 完整实现

`KNOWN`。`S-METAL` +0x1D1D7 是薄壳，整个方法体 9 条指令，尾调 6 参版并把
`fallbackDeviceFeatureProfile` 压成 `0xFFFFFFFF`：

```asm
; -[MTLCompiler initWithTargetData:cacheUUID:pluginPath:device:compilerFlags:]   S-METAL +0x1D1D7
push rbp ; mov rbp,rsp
mov  rsi, cs:off_7FF841017AE0        ; = initWithTargetData:cacheUUID:pluginPath:device:compilerFlags:
                                     ;      fallbackDeviceFeatureProfile:
mov  eax, 0FFFFFFFFh
push rax                             ; a8 = fallbackDeviceFeatureProfile = 0xFFFFFFFF
push [rbp+arg_0]                     ; a7 = compilerFlags（栈传递，见 9.8 的 ABI 注意）
call cs:7FF84005DB38h                ; objc_msgSend
add  rsp, 10h ; pop rbp ; retn
```

6 参真实现 `S-METAL` +0x17C367：

```objc
// -[MTLCompiler initWithTargetData:(dispatch_data_t)targetData
//                       cacheUUID:(const MTLUINT256_t *)cacheUUID     // 32 字节
//                      pluginPath:(NSString *)pluginPath
//                          device:(id<MTLDeviceSPI>)device
//                   compilerFlags:(uint64_t)compilerFlags
//    fallbackDeviceFeatureProfile:(uint64_t)fallback]
if (!pluginPath) cold_2();                       // 致命，不返回
if (![pluginPath isKindOfClass:[NSString class]]) cold_1();   // 致命

CC_SHA256_CTX c; CC_SHA256_Init(&c);
if (!reuseCacheOnReboot()) {                     // S-METAL +0x1D1F8，env/默认开关
    CC_SHA256_Update(&c, "Sep 22 2026", 11);     // Metal.framework 自己的 __DATE__
    CC_SHA256_Update(&c, "21:48:04",    8);      // Metal.framework 自己的 __TIME__
}
CC_SHA256_Update(&c, cacheUUID, 32);             // ← 驱动给的 32 字节
CC_SHA256_Final(md /*32B*/, &c);

self->_pluginPath              = [pluginPath copy];                       // ivar +0x10
self->_device                  = device;                                  // ivar +0x08，**弱持有**（无 retain）
self->_compilerFlags           = compilerFlags;                           // ivar +0x30
self->_compilerQueue           = dispatch_queue_create("compiler queue", NULL);   // ivar +0x18
uint32_t llvmVersion           = _MTLGetMTLCompilerLLVMVersionForDevice(device);  // S-METAL +0x1649E3
self->_compilerConnectionManager = getCompilerConnectionManager(device, llvmVersion);  // +0x173357
const char *pathC              = [pluginPath cStringUsingEncoding:4];     // 4 = NSUTF8StringEncoding
mgr[8]                         = fallback;                                // 存 fallbackDeviceFeatureProfile
self->_compilerId              = mgr->vtbl[2](mgr, pathC, targetData);
                                 // == MTLCompilerConnectionManagerInternal::registerCompilerPlugin
self->_shaderCache             = addOrRemoveShaderFunctionCache(device, md, /*remove=*/false);  // ivar +0x38
return self;
```

`MTLCompiler` 的 ivar 布局（`S-METAL` `_OBJC_IVAR_$_MTLCompiler.*` 实读）：

| 偏移 | ivar | 类型 |
|---|---|---|
| `0x08` | `_device` | `_MTLDevice *`（未 retain） |
| `0x10` | `_pluginPath` | `NSString *`（copy） |
| `0x18` | `_compilerQueue` | `dispatch_queue_t` |
| `0x20` | `_compilerConnectionManager` | `MTLCompilerConnectionManager *`（C++） |
| `0x28` | `_compilerId` | `uint64_t`（plugin 序号，1 起） |
| `0x30` | `_compilerFlags` | `uint64_t` |
| `0x38` | `_shaderCache` | `std::shared_ptr<MTLCompilerCache>` |

### 3.1 五个参数的精确语义与本项目取值

| 参数 | 类型 | 语义 | 本项目怎么填 | 标签 |
|---|---|---|---|---|
| `targetData` | `dispatch_data_t` | **不透明，Metal 一个字节都不看**。只做 `dispatch_retain` 存进 `std::vector<MTLCompilerPlugin>`（第 3.2 节），最终原样交给 plugin。APV 放 8 字节 `{u32 MaxMetalShaderVersionMajor, u32 Minor}` | 放什么都行，但必须与自己的 plugin 约定。建议照 APV 放 `{major, minor}`；`major` 必须 > 1（`setupCompiler` 的 cold 块，`S-APV` +0x1ADED） | `KNOWN` |
| `cacheUUID` | `const MTLUINT256_t *`（**32 字节，按值读，不是对象**） | 唯一用途是喂进 `CC_SHA256_Update(…, 32)`，参与 shader 磁盘缓存的目录键（第 7 节）。改一位就整条缓存作废 | 用构建哈希。APV 用 `SHA256(__DATE__[0..11) ‖ __TIME__[0..8))` | `KNOWN` |
| `pluginPath` | `NSString *` | **非 nil 且必须是 `NSString`，否则调 cold 块致命终止**。只被 `copy` 一次并 `cStringUsingEncoding:4` 转成 C 串下传 | `<bundle>/Contents/Resources/lib<Name>CompilerPlugin.dylib`。研发期 SIP/AMFI 关，文件可以真的在磁盘上，不必进 cache | `KNOWN` |
| `device` | `id<MTLDeviceSPI>` | 用来取 `llvmVersion`（第 3.3 节）与建 connection manager；**不 retain**，所以不会与 device 形成循环 | `self` | `KNOWN` |
| `compilerFlags` | `uint64_t` | 见第 3.4 节 | 照 APV 填 `32`（`0x20`） | `KNOWN`（存法）/ 部分 `BLOCKED`（位义） |

### 3.2 `registerCompilerPlugin`：注册是惰性的，这里不 dlopen

`KNOWN`。`MTLCompilerConnectionManagerInternal::registerCompilerPlugin(const char *path, dispatch_data_t targetData)`，`S-METAL` +0x12FE7E，全函数反编译要点：

```c
std::mutex::lock(&mgr->m /*+96*/);
char *p = malloc(strlen(path)+1); memcpy(p, path, strlen(path)+1);
dispatch_retain(targetData);
// 向 std::vector<MTLCompilerPlugin> push_back（begin/end/cap 在 mgr+72/+80/+88）
//   struct MTLCompilerPlugin { const char *path; dispatch_data_t targetData; };   // 16 字节
std::mutex::unlock(&mgr->m);
return (uint32_t)((oldEnd - oldBegin) / 16) + 1;        // ← 1 起的序号
```

三条可直接用的结论：

1. **返回值 `_compilerId` = plugin 在全局 vector 里的 1 起下标。** `getCompilerPluginAtIndex(i)`（+0x1304A6）就是 `begin + 16*i - 16`。
2. **`initWithTargetData:` 期间不加载任何 dylib、不做版本协商、不验证路径存在。** 即 `setupCompiler` 返回 YES 不代表 plugin 可用；第一条编译请求才会暴露加载失败。本项目的自检必须真的建一次 pipeline，不能只看 `setupCompiler`。`KNOWN`
3. plugin 表是**进程级全局**的（一个 connection manager 对应一个 `llvmVersion`），多个 device 各注册一次，互不干扰。

### 3.3 `llvmVersion` 的来源：默认由 `featureProfile` 决定，不是 `llvmVersion`

`KNOWN`。`_MTLGetMTLCompilerLLVMVersionForDevice(device)`，`S-METAL` +0x1649E3：

```c
if (_MTLIsInternalBuild() && forcedLLVMVersionOnceToken != -1) { /* env 强制 */ }
uint32_t r = forcedLLVMVersion;
if (r == 0) {
    if (_MTLIsInternalBuild() && deviceLLVMVersionOnceToken != -1) { /* once */ }
    if (useDeviceForLLVMVersion == 1) {                       // env MTL_USE_DEVICE_LLVM_VERSION_SELECTOR
        r = [device llvmVersion];                             // selref slot S-METAL +0x7FF841017750
        if ((int)r < 32024) return 32023;
    } else {
        uint64_t fp = [device featureProfile];                // selref slot S-METAL +0x7FF8410163E0
        r = 32023;
        if (fp >= 8 && fp - 10000 >= 3) return getMaxSupportedLLVMVersion(false);
    }
}
return r;
```

两个 selector 槽的归属是靠调用点交叉确证的（不是猜的）。下列括号里的 RVA 是**引用点所在地址**，不是函数入口：

- `+0x7FF8410163E0` 共 10 处引用，其中 `-[_MTLDevice initLimits]` 内 +0x2597、
  `-[_MTLDevice initGPUFamilySupport]` 内 +0x3B14、`-[_MTLDeviceFeatureQueries initWithDevice:]` 内 +0x3C47
  → **`featureProfile`**（与 `20-OBJC-DEVICE.md` 第 5.2 / 5.4 节"整张 limits 表是 `featureProfile` 的纯函数"一致）。`KNOWN`
- `+0x7FF841017750` 共 4 处引用，其中 `_MTLGetLLVMVersionFromDevice` 内 +0x1648D8
  → **`llvmVersion`**。`KNOWN`

**对本项目的直接后果**：`featureProfile = 10000`（`21` 第 5.1 节已定）落在 `fp - 10000 < 3` 分支，
所以 `llvmVersion` **= 32023**，且 release 路径上**根本不调用驱动的 `llvmVersion` 方法**。
APV 覆写 `llvmVersion` 返回 32023（`S-APV` +0xB04F）只是为了和 `MTL_USE_DEVICE_LLVM_VERSION_SELECTOR=1` 时自洽。
本项目同样覆写成 32023 即可，且**不要返回 ≥ 32024**（会把 `CompilerPluginInterface` 推到 `Versions/32024`）。

`getCompilerConnectionManager(device, v)`（+0x173357）对 `v` 只接受 **3802 / 3902 / 32023 / 32024**，
其余走 `abort()`。`-[_MTLDevice getCompilerConnectionManager:]`（+0x11CBC0）同样是这 4 个 case + `abort()`。
**这是一个会直接杀进程的硬约束。** `KNOWN`

### 3.4 `compilerFlags`：已解码 3 位，APV 的 `32` 未解码

`KNOWN`（已解码位）/ `BLOCKED`（bit 5）。

`_compilerFlags` 在 `S-METAL` 中只有两类消费者（遍历 `-[MTLCompiler *]` 全部 119 个 IMP 的伪码确证，命中 16 个函数）：

**(a) `MTLGetCompilerOptions(device, descOptions, compilerFlags, MTLCompileType, bool, MTLCompilerBitCodeType)`，`S-METAL` +0x17B18B。** 它对 `compilerFlags` 只做三次移位：

| 表达式（`v25` = compilerFlags） | compilerFlags 位 | 映射到 options 位 |
|---|---|---|
| `(v25 << 13) & 0x200000` | bit 8 (`0x100`) | `0x200000` |
| `((uint16)v25 << 8) & 0x8000` | bit 7 (`0x80`) | `0x8000` |
| `(v25 << 14) & 0x800000` | bit 9 (`0x200`) | `0x800000` |

bit 7 的语义由 `-[MTLCompiler allowLibrariesFromOtherPlatforms]`（`S-METAL` +0x1951A1）单句确证：
`LOBYTE(self->_compilerFlags) |= 0x80;`。**bit 7 = 允许加载其它平台的 library。** `KNOWN`

**(b) 四个 descriptor 序列化 selector**，形如 `[descriptor <sel>:self->_compilerFlags]`，
出现在 `-[MTLCompiler newRenderPipelineStateWithDescriptorInternal:…]`（+0x18F8A6，4 处：selref 槽
`+0x7FF841018038`、`+0x7FF841018040`、`+0x7FF841018058`、`+0x7FF841017DE8`）、
`newComputePipelineStateWithDescriptorInternal:`（+0x1933C7，槽 `+0x7FF8410180E8`）、
`newRenderPipelineStateWithTileDescriptorInternal:`（+0x194DB5，槽 `+0x7FF841018158`）。
它们返回 `dispatch_data_t` / `dispatch_object_s *`，即第 6 节那组 FlatBuffers descriptor。

**`0x20`（bit 5）在 (a) 中不被消费**，所以它只能在 (b) 的 descriptor 序列化里、或在 `MTLCompiler.framework` 内被读。
**本文没有把它定下来。** 取得方法，按代价排序：

1. 这 6 个 selref 槽在 `S-METAL` 上名字不可解（`21` 第 12.1 节），但 IMP 可达：
   对每个槽取 `data_refs_to` 的反向 IMP，反编译其中对 `& 0x20` 的分支。代价是 6 个函数。
2. 抽出 `MTLCompiler.framework/Versions/32023/MTLCompiler`（第 1.3 节同一步），
   grep `0x20` 对 request 的影响。
3. 在 guest 上实测：`compilerFlags = 0` 与 `= 32` 各建一次 pipeline，比较产物与行为。属 `TESTED` 级。

**本项目的决定**：照 APV 填 `32`。理由是 Intel/AMD 以外 APV 是唯一的"非硬件驱动"先例，
而且该值不进 `MTLGetCompilerOptions`，错填的后果被限制在 descriptor 序列化一层。`INFERRED`

---

## 4. `MTLCompiler.framework`：被 `dlopen` 的中间层

`KNOWN`（加载与符号名）/ `BLOCKED`（其内部实现）。

`CompilerPluginInterface::CompilerPluginInterface(int llvmVersion)`，`S-METAL` +0x3DCE6，全函数：

```c
this->llvmVersion /*+40*/ = llvmVersion;
const char *p = NULL;
if (llvmVersion == 32023) p = "/System/Library/PrivateFrameworks/MTLCompiler.framework/Versions/32023/MTLCompiler";
if (llvmVersion == 32024) p = "/System/Library/PrivateFrameworks/MTLCompiler.framework/Versions/32024/MTLCompiler";
if (!p) { os_log_error(...); abort(); }                     // ← 只有这两个版本
void *h = dlopen(p, 5 /* RTLD_NOW|RTLD_LOCAL */);
this->handle /*+0*/ = h;
if (h) {
    this->fnCreate        /*+8*/  = dlsym(h, "MTLCodeGenServiceCreate");
    this->fnDestroy       /*+16*/ = dlsym(h, "MTLCodeGenServiceDestroy");
    this->fnBuildRequest  /*+24*/ = dlsym(h, "MTLCodeGenServiceBuildRequest");
    this->fnSetPluginPath /*+32*/ = dlsym(h, "MTLCodeGenServiceSetPluginPath");
} else {
    os_log_fault("%s", dlerror());
    memset(this+8, 0, 32);                                   // 四个指针清零，后续调用必崩
}
```

`~CompilerPluginInterface()`（+0x3DCCA）只做 `dlclose`。

`MTLMonolithicCompilerConnection::attemptLazyInit()`（+0x3DAD6）：

```c
if (this->field_17 /*+136*/ == 0) {
    std::string procName = MTLGetProcessName();
    CompilerPluginInterface *i = new CompilerPluginInterface(this->field_11[8] /* llvmVersion */);
    this->field_16 /*+128*/ = i;
    this->field_17 = i->fnCreate(procName);                  // MTLCodeGenServiceCreate(processName)
}
```

**所以：**

1. **厂商 plugin 的 `dlopen` 不在 Metal.framework 里，在 `MTLCompiler.framework` 里**，由
   `MTLCodeGenServiceSetPluginPath` 接收第 3.2 节存下的 `(pluginPath, targetData)` 对。
2. `MTLCodeGenService*` 这 4 个符号是 **Metal.framework ↔ MTLCompiler.framework** 的接口，
   **不是** 本项目要导出的东西。本项目要导出的是第 5 节那张表。
3. 并发模型有两种：`MTLMonolithicCompilerConnection`（同进程 `dlopen`）与
   `MTLXPCCompilerConnection`（跨进程，`MTLCompilerService`，`S-METAL` +0x3CB88 起，
   带 `setupSandbox` / `compilerProcessSpawnRequest` / `compilerProcessSpawnAfterCrashRequest`）。
   `MTLCompilerConnectionManager::getIsMonolithic()` 在 +0xCA278。
   **后果：本项目的 plugin 必须假定自己可能被加载进一个独立的、沙箱化的 `MTLCompilerService` 进程里**，
   因此 reply 里**绝不能放指针**，也不能依赖驱动进程的任何状态。`KNOWN`（两条路径存在）/ `INFERRED`（选择规则未逐条解码）
4. `MTLCodeGenServiceCreate` 的入参是 `std::string processName`（按值），这是 ABI 上唯一已知的参数。

### 4.1 这一层仍是 `BLOCKED` 的部分

`BLOCKED`。`MTLCompiler.framework/Versions/32023/MTLCompiler` 未取得（与第 1.3 节同一个阻断点，
`S-DSCMAP` 第 14325 行：`__TEXT 0x7FFC1CE8D000 -> 0x7FFC1CF5B239`，约 844 KB）。
由此未定的三件事：

1. **`dlsym` 的确切符号清单与顺序**。第 5.1 节的表是从 Intel plugin 的导出表反推的，
   因此"plugin 导出了这些"是 `KNOWN`，"MTLCompiler 要求这些"是 `INFERRED`。
2. **版本协商的判据**。候选是 `AIRNTGetVersion` / `AIRNTGetSupportedBitcodeVersion` / `AIRNTGetLLVMVersion`
   三者之一或组合（Intel 分别返回 `17.0.0` / `3902` / `0`）。哪个被当作 gate 未定。
3. **缺符号时的行为**（是否全部必需、是否允许 `dlsym` 返回 NULL）。

不关闭这三项也能写出 plugin：把 40 个符号全部实现，`AIRNTGetVersion` 抄 `17.0.0`、
`AIRNTGetSupportedBitcodeVersion` 返回 `3902`、`AIRNTGetLLVMVersion` 返回 `0`，即与 Intel 完全同形。
闭合方式见第 1.3 节。

---

## 5. plugin 侧 ABI：本项目要实现的那一面

全节主证据 `S-IGCPLUG`（image base = 0，RVA 即文件内地址）。
"plugin 导出了它" = `KNOWN`；"MTLCompiler 要求它" = `INFERRED`（理由见第 4.1 节）。

### 5.1 导出符号全集（46 个 defined-external，`LC_SYMTAB` 实读）

`KNOWN`。`nsyms = 1313`，defined-external = 46，undefined = 88，local = 0。
入口是**纯 C 函数**（名字无 C++ mangling、无 ObjC 类），不是 ObjC 类工厂。

**A 组 — `MTLCompiler*`，4 个（编译请求主入口）**

| 符号 | RVA |
|---|---|
| `_MTLCompilerCreate` | `0x225F` |
| `_MTLCompilerDelete` | `0x22C0` |
| `_MTLCompilerReleaseReply` | `0x22F0` |
| `_MTLCompilerBuildRequestWithSerializedBitcode` | `0x2338` |

**B 组 — `AIRNT*`，36 个（后端能力描述与产物发射）**

| 符号 | RVA | 符号 | RVA |
|---|---|---|---|
| `_AIRNTInit` | `0x33B7` | `_AIRNTDispose` | `0x342F` |
| `_AIRNTClone` | `0x33F3` | `_AIRNTGetVersion` | `0x3441` |
| `_AIRNTGetVendorName` | `0x3453` | `_AIRNTGetLLVMVersion` | `0x33AF` |
| `_AIRNTGetDefaultArch` | `0x3460` | `_AIRNTGetSupportedArchs` | `0x3472` |
| `_AIRNTSupportsArch` | `0x3513` | `_AIRNTGetSupportedImpls` | `0x3505` |
| `_AIRNTGetSupportedBitcodeVersion` | `0x3557` | `_AIRNTSupportsTarget` | `0x4279` |
| `_AIRNTGetMostCompatibleArch` | `0x41DA` | `_AIRNTGetPreferredAIRArch` | `0x42F3` |
| `_AIRNTSupportsThreads` | `0x3A75` | `_AIRNTParseCommandLineOptions` | `0x3A7D` |
| `_AIRNTGetLegalizationPasses` | `0x3871` | `_AIRNTInitCompilationContext` | `0x3B39` |
| `_AIRNTDisposeCompilationContext` | `0x3B5C` | `_AIRNTEmitAssembly` | `0x3562` |
| `_AIRNTEmitObject` | `0x356A` | `_AIRNTEmitDylibImage` | `0x3572` |
| `_AIRNTEmitExecutableImage` | `0x36B6` | `_AIRNTEmitPipelineImage` | `0x3B6D` |
| `_AIRNTEmitPipelineImages` | `0x3867` | `_AIRNTEmitBuiltinExecutableImage` | `0x42D7` |
| `_AIRNTSupportsEmitExecutableImage` | `0x4271` | `_AIRNTSupportsEmitBuiltinExecutableImage` | `0x42CF` |
| `_AIRNTGetFunctionId` | `0x3D2C` | `_AIRNTGetVertexFunctionId` | `0x3D40` |
| `_AIRNTGetFragmentFunctionId` | `0x3D4A` | `_AIRNTGetComputeFunctionId` | `0x3D36` |
| `_AIRNTGetTileFunctionId` | `0x3D68` | `_AIRNTGetObjectFunctionId` | `0x3D54` |
| `_AIRNTGetMeshFunctionId` | `0x3D5E` | `_AIRNTGetBuiltinFunctionId` | `0x42DF` |

**C 组 — 无前缀的 6 个，判定为 Intel 内部符号泄漏，本项目不需要**：
`_GetFunctionId` (0x3D7C)、`_GetVertexFunctionId` (0x4012)、`_GetFragmentFunctionId` (0x40EF)、
`_GetComputeFunctionId` (0x3E51)、`_GetObjectFunctionId` (0x41CA)、`_GetMeshFunctionId` (0x41D2)。
它们是 `AIRNTGet*FunctionId` 的实现体被误标为 external（`AIRNTGetFunctionId` 只是 `return sub_65D0();`）。`INFERRED`

`LC_ID_DYLIB` = `/usr/local/lib/libMTLIGCCompilerPlugin.dylib`（**不是**安装路径；
`dlopen` 用的是绝对路径，`install_name` 无关）。
依赖只有 4 条：`Foundation`、`libobjc.A.dylib`、`libc++.1.dylib`、`libSystem.B.dylib`。

### 5.2 `MTLCompilerCreate` / `Delete` / `ReleaseReply`

`KNOWN`，全函数反编译。

```c
// S-IGCPLUG +0x225F
void *MTLCompilerCreate(const void *createArgs);
//   syslog(LOG_INFO, "MTLCompilerCreate: Compile thought IGC\n");
//   obj = operator new(0x120);          // 288 字节的厂商私有编译器实例
//   ctor(obj, createArgs);
//   *(uint32_t *)((char *)obj + 0x118) = *(uint32_t *)createArgs;   // 取 createArgs 第一个 u32
//   openIGCLibrary(obj);                // dlopen 自己的后端
//   return obj;

// S-IGCPLUG +0x22C0
void MTLCompilerDelete(void *compiler);   // 析构 + operator delete

// S-IGCPLUG +0x22F0
void MTLCompilerReleaseReply(void *compiler);
//   if (compiler->p272) { operator delete[](compiler->p272); compiler->p272 = NULL; }  // 错误串
//   if (compiler->p264) { free(compiler->p264);              compiler->p264 = NULL; }  // 产物字节
```

三条可直接照搬的契约：

1. **`MTLCompilerCreate` 的返回值是不透明句柄**，由 plugin 自己 `new`/`delete`，Metal 只搬指针。
2. **reply 不是独立对象，它挂在 compiler 实例的两个槽上**：
   `+0x108` = `malloc` 出来的产物缓冲（`free` 释放）、`+0x110` = `new[]` 出来的错误串（`delete[]` 释放）。
   `MTLCompilerReleaseReply(compiler)` 收的参数就是 compiler 句柄本身。
   **因此 `BuildRequest` 与 `ReleaseReply` 之间 compiler 句柄不可并发复用**；
   并发度由 `AIRNTSupportsThreads`（Intel `return 0`）与上层的 process pool 控制，不由 plugin 内部加锁。`KNOWN`
3. `createArgs` 的第一个 `u32` 被原样存进实例。它是 `MTLCodeGenServiceSetPluginPath` 传下来的
   `targetData` 的首 4 字节的最可能归宿 —— 而 APV 的 `targetData` 首 4 字节正是
   `MaxMetalShaderVersionMajor`（第 3.1 节）。`INFERRED`（强）

### 5.3 `MTLCompilerBuildRequestWithSerializedBitcode`：13 个参数

`KNOWN`（参数个数、返回值、已识别的参数）/ `INFERRED`（标注处）。`S-IGCPLUG` +0x2338 全函数反编译。

```c
int MTLCompilerBuildRequestWithSerializedBitcode(
        void        *compiler,            // a1  MTLCompilerCreate 的句柄
        const int   *request,             // a2  指向已解析的 FlatBuffers 请求对象；*request = function type
        uint64_t     a3,                  // a3  随 request 一起下传给各 stage 的编译例程（未定）
        uint32_t     flags,               // a4  bit1 (0x2) = 采集 statistics/计时
        const void  *bitcode,             // a5  AIR LLVM bitcode 起始地址
        size_t       bitcodeLen,          // a6  AIR bitcode 字节数
        void       **outReply,            // a7  成功时 = 产物缓冲；失败时写 NULL
        uint64_t     a8,                  // a8  仅 compute 路径用到（下传 sub_2ABB）
        void       **a9,                  // a9  out 槽（AIRNTEmitPipelineImage 传一块 0x20 临时缓冲并丢弃）
        void       **a10,                 // a10 同上，a9+8
        void       **outStats,            // a11 out：statistics 缓冲（flags&2 时 malloc(40)）
        size_t      *outStatsLen,         // a12 out：写入常量 40
        char       **outErrorString);     // a13 out：失败时 new char[n] 的 C 串
// 返回 0 = 成功，1 = 失败
```

**函数类型分派（`*request`）** —— 三条 `__assert_rtn` 把取值范围钉死，
assert 文件名 `MTLIntelCompilerPlugin.cpp`：

| `*request` | 分支 | 说明 |
|---|---|---|
| `0` | `sub_4FA8`（vertex） | 产出 **两个**可选输出；两者都空时 assert 行 151：`"Neither Vertex nor Tess outputs have been set."` → 该类型同时覆盖 vertex 与 post-tessellation |
| `2` | `sub_51D8`（fragment） | 单输出 |
| `3` | `sub_5340`（compute） | 单输出 |
| 其它 | assert 行 221：`0 && "Unknown Function Type"` | **包括 1** —— 本样本未实现 |

`a2 == NULL` 时走 `sub_C706()`，assert 串 `0 && "compilerInput is NULL"`。

**失败路径（统一）**：

```c
*outErrorString = new char[n];                 // 从一个 std::string 里 strlcpy 出来（SSO 与堆两种布局都处理）
strlcpy(*outErrorString, msg, n);
*outReply = NULL;
compiler->p264 = NULL;
return 1;
```

**成功路径**会把产物写进 `compiler->p264` 并让 `*outReply` 指向同一块（第 5.4 节），返回 0。

**statistics（= 驱动侧的 `pipelineStatisticsOutput`）**：

```c
if (flags & 2) {
    void *s = malloc(0x28);                    // 40 字节
    memcpy(s, (char *)stageOut + 0x118 /*650 的 __m256 偏移*/, 0x28);
    *outStatsLen = 40;
    *outStats    = s;
}
…
if (flags & 2) {                               // 函数末尾
    *((int64_t *)*outStats + 4) = now_ns - (t0 + accumulated);   // +0x20 = 编译墙钟纳秒
}
```

即 **`pipelineStatisticsOutput` 是一块 40 字节的厂商私有缓冲，最后 8 字节是编译耗时（ns）**，
前 32 字节由各 stage 的编译结果直接 `memcpy` 得来。`KNOWN`

**与驱动侧的对应**：`21-OBJC-OBJECT-FAMILY.md` 第 2.4 节确证 APV 的三个
`new*VariantWithCompilerOutput:pipelineStatisticsOutput:` **完整丢弃第二个参数**。
本文解释了为什么可以丢：它只是性能计数，不含任何功能性数据。
**本项目同样忽略它。** `KNOWN`（APV 行为 + 本节内容）

### 5.4 产物（compiler output）的字节布局

`KNOWN`。`sub_28D3`（vertex 路径的产物封装，`S-IGCPLUG` +0x28D3）全函数：

```c
uint32_t payloadLen = *(uint32_t *)stageOut;         // 后端输出 blob 自带长度前缀
uint64_t tailOff    = payloadLen + 16;
size_t   total      = payloadLen + 20;
*outLen  = total;
uint64_t *reply = malloc(total);
compiler->p264  = reply;                             // 交给 MTLCompilerReleaseReply 回收
reply[0] = 1;                                        // u64：版本/条目数
reply[1] = ((uint64_t)tailOff << 32) | 0x10;         // u32 headerSize=0x10 | u32 tailOffset
memcpy(reply + 2, stageOut, payloadLen);             // 厂商 blob 从 +0x10 开始
*(uint32_t *)((char *)reply + tailOff) = tailValue;  // 尾部一个 u32
*outReply = reply;
```

形状是 `{ u64 = 1; u32 = 0x10; u32 tailOffset; <payload>; u32 tail }`。

**这块字节 100% 由厂商定义。** 证据链三段：

1. plugin 这端用 `malloc` 自己拼（本节）。
2. Metal 只把它包成 `dispatch_data_t`，经完成 block
   `void(^)(MTLCompilerError, dispatch_data_t, const char *)` 交出去
   （`MTLCompilerConnectionManagerInternal::buildRequest`，`S-METAL` +0x1302EE / +0x1302F4，符号名即签名）。
3. 驱动这端 `dispatch_data_get_size` → `dispatch_data_create_map` → **整块 `memcpy` 进 GPU 可见缓冲**，零解析
   （`-[AppleParavirtFunctionVariant initWithCompilerOutput:device:functionType:]`，`S-APV` +0x30CF，
   见 `21-OBJC-OBJECT-FAMILY.md` 第 2.4.2 节）。

所以：**`compiler output` = `dispatch_data_t`，内容是 plugin 与同一厂商的驱动私下约定的格式，Metal 全程不看。**
本项目可以直接把 `31-PIPELINE-ARTIFACT.md` 的 `PipelineArtifact` 序列化成这块字节（见第 8 节）。`KNOWN`

另一条"legacy" 路径的回调签名不同：
`MTLLegacyMonolithicCompilerConnection::BuildRequest(MTLCompilerRequest*, const char*, dispatch_data_t, int, bool, objc_object*, void(^)(unsigned, const void*, size_t, dispatch_data_t))`
（`S-METAL` +0x1415DA），回调是 `(status, bytes, len, data)`。`featureProfile = 10000` 不走这条，
但如果将来 `getIsMonolithic` 判据变化要留意。`KNOWN`（签名）/ `INFERRED`（不走）

### 5.5 `AIRNT*` 的已解码签名

`KNOWN`，全部逐函数反编译。`Ctx` = `AIRNTInit` 返回的句柄。

```c
void       *AIRNTInit(void);                              // +0x33B7  new 0x28，ctor(obj, 7)
void        AIRNTDispose(void *Ctx);                      // +0x342F  assert "PluginCtx != nullptr"
void       *AIRNTClone(void *Ctx);                        // +0x33F3
int         AIRNTGetVersion(void *Ctx, uint32_t *major, uint32_t *minor, uint32_t *patch);
                                                          // +0x3441  Intel: 17 / 0 / 0, return 0
const char *AIRNTGetVendorName(void);                     // +0x3453  Intel: "Intel"
int         AIRNTGetLLVMVersion(void);                    // +0x33AF  Intel: 0
int         AIRNTGetSupportedBitcodeVersion(void);        // +0x3557  Intel: 3902
void        AIRNTGetDefaultArch(void *Ctx, uint32_t *cpuType, uint32_t *cpuSubtype);
                                                          // +0x3460  Intel: 0x01000015 / 0x00950002
void        AIRNTGetSupportedArchs(void *Ctx, uint32_t **cpuTypes, uint32_t **cpuSubtypes, size_t *count);
                                                          // +0x3472  Intel: 7 项，两个 malloc(0x1C)，调用方负责 free
bool        AIRNTSupportsArch(void *Ctx, uint32_t cpuType, uint32_t cpuSubtype);
                                                          // +0x3513  cpuType != 0x01000015 直接 false；
                                                          //          否则 wmemchr 查 Ctx+8..Ctx+16 的 subtype 表
bool        AIRNTSupportsTarget(void *Ctx, uint32_t cpuType, uint32_t cpuSubtype, uint32_t platform);
                                                          // +0x4279  platform 必须 == 1；assert 串
                                                          //   "Platform == llvm::MachO::PLATFORM_MACOS && \"Invalid Intel platform detected\""
int         AIRNTGetSupportedImpls(void *Ctx, a2, a3, void **out, size_t *count);
                                                          // +0x3505  Intel: *out = 0, *count = 0, return 0
int         AIRNTSupportsThreads(void);                   // +0x3A75  Intel: 0
void       *AIRNTInitCompilationContext(uint64_t a1, uint64_t a2);
                                                          // +0x3B39  new {a1, a2}（16 字节），别无动作
void        AIRNTDisposeCompilationContext(void *c);      // +0x3B5C
void       *AIRNTGetPreferredAIRArch(void *Ctx, uint32_t cpuType, uint32_t cpuSubtype,
                                     uint32_t platform, uint32_t langVersion, a6, a7,
                                     uint32_t *outCpuType, uint32_t *outSubtype);
                                                          // +0x42F3  Intel: platform 必须 == 1；
                                                          //          *outCpuType = 0x01000017；
                                                          //          langVersion 14 -> *outSubtype = 10
                                                          //          langVersion 13 -> 9；其它 -> 0/0
void        AIRNTGetLegalizationPasses(void *Ctx, a2, uint32_t deviceKey,
                                       const char ***outPasses, size_t *outCount);
                                                          // +0x3871  见 5.5.1
bool        AIRNTEmitPipelineImage(void *Ctx, a2, uint32_t flags, const void *bitcode,
                                   size_t bitcodeLen, a6, int a7, uint32_t deviceKey,
                                   const void *serializedPipelineDescriptor, int a10,
                                   void **outReply, uint64_t a12, void **outStats,
                                   size_t *outStatsLen, char **outErrorString);
                                                          // +0x3B6D  见 5.5.2
```

Intel 专有常量（**本项目不得照抄**）：`0x01000015` / `0x01000017` 是 AIR 的 `cputype` 取值，
`0x00950002` 等是 subtype。它们与 `30-SHADER-AIR.md` 第 1.2 节 universal metallib 的
CPU type 字段同一命名空间。本项目要填什么取决于 Metal 用哪个 arch 去编 metallib，
**未查清**；取得方法：`AIRNTGetSupportedArchs` 的返回表只要包含 Metal 实际请求的那一个即可，
最省力的做法是先返回"全部 7 个 Intel 值 + `AIRNTSupportsArch` 恒 true"，用一次真实编译把实际值 log 出来。

#### 5.5.1 `AIRNTGetLegalizationPasses`：本项目最该利用的机制

`KNOWN`。`S-IGCPLUG` +0x3871 全函数，assert 来自 `AIRNTInterface.cpp:175 "mtlDevice != nullptr"`、`:183`。

```c
void AIRNTGetLegalizationPasses(void *Ctx, a2, uint32_t deviceKey,
                                const char ***outPasses, size_t *outCount)
{
    void *dev = lookupDevice(deviceKey);  if (!dev) assert(...);
    std::vector<const char *> v;
    v.push_back(supportsVertexAmplification(dev) ? "air-debug-post-vertex-dump-amplification-id"
                                                 : "air-degenerate-vertex-amplification-emulation");
    if ( supportsRaytracing(dev)) v.push_back("air-raytracing-emulation");
    if (!supportsRaytracing(dev)) v.push_back("air-tls-emulation");
    v.push_back("air-16bit-texture-coordinate-emulation");
    v.push_back("air-bfloat-emulation");
    v.push_back("mtl-fetch-compute-tessellation");
    v.push_back("mtl-vertex-linking");
    v.push_back("mtl-fragment-linking");
    *outPasses = malloc(v.size()*8); memcpy(...); *outCount = v.size();
}
```

（两处 `sub_21DB(dev)` 的真实谓词名未确证；取反的那一对说明一个能力开则加 raytracing 仿真、
关则加 TLS 仿真。标 `INFERRED` 为"raytracing 支持位"。）

**这是一张"我不支持，请你先降级"的清单。** plugin 报出的 pass 名会在 AIR 到达 plugin 之前
由 Metal / `GPUCompiler.framework` 侧跑掉，即 **plugin 收到的 bitcode 已经不含这些特性**。
已确证的 8 个 pass 名：

| pass 名 | 消除的 AIR 特性 | 对 `30-SHADER-AIR.md` 的影响 |
|---|---|---|
| `air-raytracing-emulation` | 光线求交全族 | `30` 第 5.2 节"光线求交"、6.3 节 `ray tracing` 整条可不实现 |
| `air-tls-emulation` | thread-local storage | — |
| `air-16bit-texture-coordinate-emulation` | 16 位纹理坐标采样变体 | `30` 第 5.2 节"纹理与采样"的一部分 |
| `air-bfloat-emulation` | bfloat16 | `30` 第 5.5 节的版本差异项 |
| `air-degenerate-vertex-amplification-emulation` | vertex amplification | `30` 第 4.7 节 Builtin 的 amplification 相关项 |
| `air-debug-post-vertex-dump-amplification-id` | （支持 amplification 时的调试 pass） | — |
| `mtl-fetch-compute-tessellation` | tessellation 改写成 compute 取数 | `30` 第 4.9 节 post-tessellation patch 输入 |
| `mtl-vertex-linking` | vertex 阶段的函数链接 | `30` 第 4.13 节 visible function / stitching 的一部分 |
| `mtl-fragment-linking` | fragment 阶段的函数链接 | 同上 |

**本项目应把这 8 个 pass 全部报上去**（不做任何能力判断），这样 metal2vulkan 要覆盖的 AIR 子集会显著缩小。
这是本文对 `30` 分册范围最实质的修正，详见第 9 节。`INFERRED`（本项目的用法）/ `KNOWN`（机制与 pass 名）

#### 5.5.2 `AIRNTEmitPipelineImage`：pipeline 级入口

`KNOWN`。`S-IGCPLUG` +0x3B6D。要点（去掉 Intel 内部对象管理）：

```c
dev = lookupDevice(deviceKey);
compiler = getCompiler(dev);  if (!compiler) fatal();
if (getTargetTripleOSMajor(compiler, bitcode, bitcodeLen) <= 12) { cleanup(); return false; }   // macOS 13+ 门槛
desc = new ParsedDescriptor(0x50);
parseSerializedPipelineDescriptor(desc, serializedPipelineDescriptor, Ctx+32);
// 从 desc 的四个互斥 sub-table 里挑出非空的那一个（偏移 40 / 48 / 56 / 64）
request = desc->renderTable ?: desc->computeTable ?: desc->tileTable ?: desc->otherTable;
a3      = desc-> 对应的第二个字段;
tmp     = malloc(0x20);
int rc  = MTLCompilerBuildRequestWithSerializedBitcode(
              compiler, request, a3, flags, bitcode, bitcodeLen,
              outReply, a12, &tmp[0], &tmp[1],
              outStats, outStatsLen, outErrorString);
free(tmp); cleanup();
return rc == 0;
```

三条结论：

1. **`bitcode` + `bitcodeLen` 是 AIR LLVM bitcode 的原始字节**，由 `getTargetTripleOSMajor`
   直接读其 target triple —— 这要求 plugin 能解析 bitcode。
2. **`serializedPipelineDescriptor` 是一块序列化的 pipeline 描述**，被 parse 成一个 0x50 字节的对象，
   其中按 stage 组织成 4 个互斥的子表。见第 6 节。
3. `a9` / `a10` 在这一层被当临时缓冲接走并丢弃，所以它们**不是功能性输出**。

---

## 6. 第二个输入：FlatBuffers 的 `Air` / `Mtl4` schema

`KNOWN`。这是本文发现的、`30` 与 `31` 都没有覆盖的一类输入。

证据四条，相互独立：

1. **`S-IGCPLUG` 的 undefined 符号**里有 `flatbuffers::flatbuffer_version_string` 与 7 个
   `flatbuffers::data<Offset<T>>` 的局部静态保护变量，T 分别是：
   `Air::FunctionGroup`、`Air::AttributeDescriptor`、`Air::BufferLayoutDescriptor`、
   `Air::PipelineBufferDescriptor`、`Air::FragmentColorAttachmentDescriptor`、
   `flatbuffers::String`、`uint64_t`。
2. **`S-IGCPLUG` 的字符串表**里有 `FlatBuffers 1.12.0`。
3. **`S-METAL` 的模板实参**里有
   `std::unordered_map<std::string, flatbuffers::Offset<Mtl4::LibraryFunctionDescriptor>>`
   （出现在 `addOrRemoveShaderFunctionCache` 用到的 hash table 实例化，`S-METAL` +0x17C05A）。
4. **`-[MTLCompiler getFunctionId:airScript:vendorPluginFunctionId:bitcodeHashList:]`**
   （`S-METAL` +0x17ED65）对 `airScript` 的判别方式：

   ```c
   if (strncmp((char *)airScript + 4, "AIRP", 4) == 0)
       h = _getPipelineFrameworkHash((char *)airScript + *(uint32_t *)airScript, functionType, isLegacyProfile);
   else if (strncmp((char *)airScript + 4, "AIRF", 4) == 0)
       h = _getFunctionHash((char *)airScript + *(uint32_t *)airScript, isLegacyProfile);
   ```

   `*(u32 *)buf` = 根表偏移、`buf + 4` = 4 字节标识符 —— **这就是 FlatBuffers 的 buffer 头布局**。

因此：

- **`airScript` / `serialized*Descriptor` 是 FlatBuffers buffer**，`file_identifier`
  **`AIRF`** = 单函数、**`AIRP`** = 整条 pipeline。
- schema 的命名空间是 `Air`（以及 Metal 4 路径的 `Mtl4`）。已知表名：
  `Air::FunctionGroup`、`Air::AttributeDescriptor`、`Air::BufferLayoutDescriptor`、
  `Air::PipelineBufferDescriptor`、`Air::FragmentColorAttachmentDescriptor`、
  `Mtl4::LibraryFunctionDescriptor`。
- 它承载的正是 `31-PIPELINE-ARTIFACT.md` 要消费的东西：
  顶点属性（`AttributeDescriptor`）、buffer 布局与步进（`BufferLayoutDescriptor`、`PipelineBufferDescriptor`）、
  颜色附件格式与混合（`FragmentColorAttachmentDescriptor`）、函数分组（`FunctionGroup`）。
- 生产者是 Metal 侧那 6 个"descriptor + `compilerFlags` → `dispatch_data_t`"的 selector（第 3.4 节 (b)）。

**未查清**：完整的字段表（schema）。`BLOCKED`。
FlatBuffers 的 reflection 元数据（`.bfbs`）不随二进制交付，表名只能从 C++ 符号里读到，字段名读不到。
取得方法按代价排序：

1. 反编译 `S-IGCPLUG` 的 `parseSerializedPipelineDescriptor`（本文 `sub_EF8` / `sub_100A` / `sub_101E` / `sub_1014` / `sub_1000`，RVA `0xEF8`、`0x100A`、`0x101E`、`0x1014`、`0x1000`），
   按 vtable 偏移还原字段号与类型。FlatBuffers 的访问器是 `GetField<T>(vtable_offset, default)`，偏移可逐个读出。代价中等，产出完整。
2. 在 guest 上 hook 那 6 个 selector 的返回值，把 `dispatch_data_t` dump 下来，
   用 `flatc --raw-binary` 对已知 identifier 反解结构。属 `TESTED` 级，最直接。
3. 只实现本项目需要的字段：先按 (1) 定位 `FragmentColorAttachmentDescriptor` 与 `AttributeDescriptor`，其余留空。

---

## 7. 缓存：`cacheUUID` 做什么、键怎么拼、落在哪

`KNOWN`，除标注外。

### 7.1 `cacheUUID` 的唯一用途

`addOrRemoveShaderFunctionCache(id<MTLDeviceSPI> device, MTLUINT256_t md, bool remove)`，`S-METAL` +0x17C05A：

```c
id a   = [device <selref +0x7FF8410157A0>];         // 一个 device 侧对象
uint32_t x = [a <selref +0x7FF841015168>];
uint32_t y = [a <selref +0x7FF8410169A0>];
NSString *name = [NSString stringWithFormat:@"%u_%u", x, y];
if (MTLGPUDebugEnabled()) name = [NSString stringWithFormat:@"%@_ShaderValidation", name];

static os_unfair_lock caches_mutex;                  // S-METAL +0x1E20F8
static std::unordered_map<std::string, std::shared_ptr<MTLCompilerCache>> caches;   // +0x37D76160
os_unfair_lock_lock(&caches_mutex);
auto it = caches.find(name.UTF8String);
if (remove) { if (it != end && 唯一持有者) { flush(); caches.erase(it); } }
else if (it != end) result = it->second;
else {
    result = MTLCompilerCache::createFSCache(name, "functions", &md);   // ← md 在这里进去
    caches.emplace(name, result);
}
os_unfair_lock_unlock(&caches_mutex);
```

即：

- **缓存实例按 `"%u_%u"` 的 device 标识对共享**（两个 u32 的来源 selector 在 `S-METAL` 上名字不可解，
  槽地址已给出；`INFERRED` 为 vendorID/deviceID 或 registry ID 对）。
- **`cacheUUID` 经 `SHA256(Metal 的 __DATE__ ‖ __TIME__ ‖ cacheUUID)` 后作为 `createFSCache` 的第三个参数**，
  即磁盘缓存的版本戳。Metal 自己升级、或驱动的 `cacheUUID` 变一位，缓存全部作废。
  `reuseCacheOnReboot()`（`S-METAL` +0x1D1F8，读 `gReuseCacheOnReboot`）为真时**不**混入 Metal 的时间戳。
- 子目录名常量 **`"functions"`**。

### 7.2 落盘位置

`KNOWN`（函数链）/ `INFERRED`（最终路径串）。

```
_MTLGetShaderCachePath()                S-METAL +0x11040B   dispatch_once 包装
  └─ block_invoke                               +0x110429
      └─ getShaderCacheMainFolder()             +0x5EC5F
          └─ copyCacheMainFolder("com.apple.metal", &out, /*create=*/true)
```

`_MTLSetShaderCachePath`（+0x110588）、`_MTLMakeShaderCacheWritableByAllUsers`（+0x1105A2）、
`gShaderCachePermissions`（+0x1E21B2）、env 变量 **`MTL_SHADER_CACHE_SIZE`**（字符串 `S-METAL` +0x23C3F2）同族。

`copyCacheMainFolder("com.apple.metal", …)` 的实现未逐行反编译；按 Darwin 惯例它是
`confstr(_CS_DARWIN_USER_CACHE_DIR)` + `com.apple.metal`，即
`/var/folders/<xx>/<yyy>/C/com.apple.metal/functions/<name>/`。标 `INFERRED`。
闭合方式：反编译 `copyCacheMainFolder`（一个函数），或在 guest 上 `ls` 一次。

### 7.3 函数级缓存键的构成（plugin 参与的部分）

`KNOWN`。`-[MTLCompiler getFunctionId:airScript:vendorPluginFunctionId:bitcodeHashList:]`，`S-METAL` +0x17ED65，
返回一个 `MTLHashKey`，由一张 `(uint32 tag, MTLUINT256_t hash)` 的三元组表构成：

| tag | 内容 | 来源 |
|---|---|---|
| `1026` | `getGPUCompilerHashForScript(airScript)` | Metal 侧，对 FlatBuffers script 取哈希 |
| `1027` | **`vendorPluginFunctionId`（32 字节）** | **厂商 plugin** 的 `AIRNTGet*FunctionId` 返回值 |
| `1032` | `_getPipelineFrameworkHash` / `_getFunctionHash` 的 32 字节结果 | Metal 侧，按 `AIRP` / `AIRF` 分流 |

另有 `bitcodeHashList`（`std::vector<MTLUINT256_t const *>`）与 `[function <sel>]` 一起进 `MTLHashKey` 构造。
`MTL_REPLACE_FAST_MATH_WITH_RELAXED_MATH` 为真时会对 tag 1032 的哈希再做一次 `CC_SHA256` 混淆。

**对本项目的要求**：`AIRNTGet*FunctionId` 这一族**必须返回一个会随后端变化而改变的 32 字节哈希**。
如果它返回常量，换了后端版本后 Metal 会命中旧缓存并把过时产物喂给驱动。
建议：`SHA256(构建 ID ‖ 后端 pass 列表 ‖ 目标 SPIR-V 版本 ‖ 请求相关字段)`。`INFERRED`（建议）/ `KNOWN`（机制）

`-[MTLCompiler getBuiltInFunctionId:]` 在 `S-METAL` +0x17C70B，对应 plugin 的 `AIRNTGetBuiltinFunctionId`。

---

## 8. 本项目的落法

### 8.1 `PipelineArtifact` 装在哪：方案 A（推荐）

`INFERRED`（设计决定，基于第 5.4、5.5、4 节的 `KNOWN` 证据）

**方案 A：plugin 做完整的 AIR→SPIR-V→`PipelineArtifact`，把序列化后的 artifact 当作 compiler output 的 payload。**

```
plugin（新 dylib，Rust + 一层 C shim）
  MTLCompilerBuildRequestWithSerializedBitcode(bitcode, len, request, …)
    ├─ metal2vulkan-air：AIR bitcode → SPIR-V
    ├─ 解析 FlatBuffers request（第 6 节）→ 固定功能状态、顶点属性、附件格式
    ├─ 组装 31-PIPELINE-ARTIFACT.md 的 PipelineArtifact（SPIR-V + BindingPlan + layout + interface）
    └─ 序列化成 {magic, version, len} + bincode/flatbuffer 字节 → *outReply

driver plugin（ObjC bundle）
  new*VariantWithCompilerOutput:  →  Variant 对象只持有这块字节（或其反序列化句柄）
  newRenderPipelineWithDescriptor:vertexVariant:fragmentVariant:errorMessage:
    → 反序列化两个 variant 的 artifact，交给 Rust 渲染核心建 VkPipeline
```

为什么选 A：

1. **缓存命中率**。Metal 把 compiler output 按第 7 节的键写进磁盘缓存并在后续启动直接复用。
   artifact 在 payload 里 ⇒ **AIR→SPIR-V 与 artifact 组装都被缓存掉**，第二次起 pipeline 创建只剩反序列化 + `vkCreateGraphicsPipelines`。
   这对 Lavapipe（CPU 实现）是实质收益。
2. **与 APV / Intel 同形**，没有走偏。驱动侧 variant 的职责就是"量大小、拷走、交给后端"。
3. **跨进程安全**。第 4 节确证 plugin 可能跑在 `MTLCompilerService` 里。
   A 方案的 reply 是自包含字节流，天然满足"不能有指针"。

A 方案的代价与必须遵守的约束：

- `PipelineArtifact` 必须**可序列化且自带版本号**。磁盘缓存会跨进程、跨重启复用，
  版本不匹配必须能识别并拒绝 —— 靠 `cacheUUID`（第 3.1 节）与 `AIRNTGet*FunctionId`（第 7.3 节）两道闸。
  **两者都要用构建哈希，不能是常量。**
- plugin 里会同时存在 LLVM bitcode 解析与 artifact 组装，dylib 体积与初始化成本都在编译进程里，
  不在渲染热路径上 —— 这是好事。
- **pipeline 级与 function 级的边界要定清**。`AIRNTEmitPipelineImage` 是 pipeline 级（`AIRP`），
  但驱动侧拿到的是**每个 stage 一个 variant**（`newVertexVariant…` / `newFragmentVariant…` 分开调）。
  所以 reply 必须是 **per-stage** 的，pipeline 级的链接信息要么复制进两个 stage 的 reply，
  要么留到 `newRenderPipelineWithDescriptor:vertexVariant:fragmentVariant:` 再合。
  APV 的做法是后者（variant 只持一块 buffer，pipeline 由私有 selector `0x100` 现场组装，`21` 第 11 节）。
  **本项目照 APV：variant 里放 stage 级 SPIR-V + 该 stage 的 interface/BindingPlan；
  pipeline 级的固定功能状态在 `newRenderPipelineWithDescriptor:…` 里从 `MTLRenderPipelineDescriptor` 直接读**
  （那里能拿到完整的 ObjC descriptor，不必依赖 FlatBuffers 那一份）。

### 8.2 方案 B 及其后果

**方案 B：plugin 只做 AIR→SPIR-V，`PipelineArtifact` 留在 driver plugin 内组装。**

- reply = SPIR-V + 最小 stage metadata。
- 后果 1：**artifact 组装不被缓存**，每次 pipeline 创建都要重做（反射、binding 规划、layout 推导）。
- 后果 2：**固定功能状态只能从 ObjC descriptor 读**，第 6 节那份 FlatBuffers 白拿不用。
  这其实不算损失（ObjC descriptor 更全、字段已知，见 `22-OBJC-DESCRIPTORS.md`）。
- 后果 3：**plugin 与 driver plugin 的版本耦合变松**，reply 格式更稳定、更好调试。
- 后果 4：驱动侧要带 SPIR-V 反射逻辑，窄 C ABI 的接口面变宽。

**取舍结论**：第一版用 **B 的简化形式起步、按 A 收口**。
具体做法：reply 从一开始就定成"`{magic, version, stage, spirv_len, spirv, meta_len, meta}`"这种
**自包含、可扩展**的容器；`meta` 先只放最小集，等 artifact 稳定后把完整 `PipelineArtifact` 放进去，
格式号 +1。这样不需要改任何 ABI 就能从 B 滑到 A。`INFERRED`

### 8.3 哪些 `AIRNT*` 必须返回真值，哪些可以常量

`INFERRED`（基于第 5.5 节的 Intel 实现）

| 必须真实现 | 原因 |
|---|---|
| `MTLCompilerCreate/Delete/ReleaseReply/BuildRequestWithSerializedBitcode` | 编译主路径 |
| `AIRNTInit/Dispose/Clone` | 句柄生命周期 |
| `AIRNTGetLegalizationPasses` | 第 5.5.1 节，决定本项目要实现多少 AIR |
| `AIRNTEmitPipelineImage` | pipeline 级入口 |
| `AIRNTGet*FunctionId`（7 个） | 第 7.3 节，缓存正确性 |
| `AIRNTGetSupportedArchs` / `SupportsArch` / `GetDefaultArch` / `GetPreferredAIRArch` / `SupportsTarget` | arch 协商；取值待第 5.5 节的方法确定 |

| 可以照 Intel 填常量 | 取值 |
|---|---|
| `AIRNTGetVersion` | `17 / 0 / 0`，`return 0` |
| `AIRNTGetVendorName` | 自己的厂商串 |
| `AIRNTGetLLVMVersion` | `0` |
| `AIRNTGetSupportedBitcodeVersion` | `3902` |
| `AIRNTGetSupportedImpls` | `*out = NULL; *count = 0; return 0` |
| `AIRNTSupportsThreads` | `0`（并发由上层 process pool 给） |
| `AIRNTInitCompilationContext` / `Dispose…` | `new {a1,a2}` / `delete` |
| `AIRNTParseCommandLineOptions` | 空实现 |
| `AIRNTSupportsEmitExecutableImage` / `…BuiltinExecutableImage` | `false` |
| `AIRNTEmitAssembly/Object/DylibImage/ExecutableImage/BuiltinExecutableImage/PipelineImages` | 返回失败。**除非实测证明 Metal 真的会调** |

### 8.4 方案 D：绕开 compiler plugin（评估过，不推荐）

`INFERRED`。`-[_MTLDevice newRenderPipelineStateWithDescriptor:error:]`（`S-METAL` +0x1D185）的做法是
`c = [self compiler]` 然后对 `c` 发**普通 `objc_msgSend`**。`compiler` 的 selref 槽被 33 个函数引用
（`21` 第 2.2 节）。**返回值没有类型检查、没有 `conformsToProtocol:` 断言**，
所以理论上可以覆写 `compiler` 返回一个自制对象，整条 `MTLCompiler` → `MTLCompiler.framework` → plugin 全部绕开，
由本项目直接从 metallib 走到 SPIR-V。

不推荐，三条理由：

1. **鸭子类型面太宽。** `MTLCompiler` 有 119 个 IMP；至少
   `newRenderPipelineStateWithDescriptor:options:reflection:error:completionHandler:`、
   `newComputePipelineStateWithDescriptor:options:reflection:error:completionHandler:`、
   `getFunctionId:airScript:vendorPluginFunctionId:bitcodeHashList:`、`getBuiltInFunctionId:`、
   `compileRequest:*` 一族、`libraryCacheStats`、`pipelineCacheStats`、`unloadShaderCaches`、
   `getShaderCacheKeys`、`copyShaderCacheToPath:`、`allowLibrariesFromOtherPlatforms`、`compilerFlags`
   都有外部调用点。漏一个就是运行期 `doesNotRecognizeSelector:`。
2. **反射与函数常量全部要自己做。** `MTLRenderPipelineReflection`、`MTLAutoreleasedArgument` 一族
   由 `MTLCompiler` 构造；绕开它就要自己造这些 Metal 内部对象。
3. **磁盘缓存全部失效。** 第 7 节那套免费的持久化缓存归 `MTLCompiler`，绕开就没有。

唯一值得记住的好处：它把 `30-SHADER-AIR.md` 第 1 节的 metallib 容器解析**重新变成必需**（见第 9 节），
也就是说如果将来 compiler plugin 这条路因为 `MTLCompiler.framework` 的未知 gate 走不通，方案 D 是后备，
而 `30` 第 1 节正是这个后备的成本。**不要删掉 `30` 第 1 节。**

---

## 9. `30-SHADER-AIR.md` 需要如何调整

本节按任务要求**只写建议，不改那份文档**。

### 9.1 定位：基本成立，三处要改

`30` 的核心前提"本项目要做 AIR→SPIR-V"**成立且位置正确**：plugin 收到的是 AIR bitcode 原始字节
（第 5.3、5.5.2 节，`KNOWN`），不是预解析 IR。所以不需要重写那份文档，只要三处调整。

### 9.2 建议一：第 1 节（metallib 容器格式）降级为"备用路径"

**事实**：plugin 收到的是 `(bitcode, bitcodeLen)` 一对，即**已经从 metallib 容器里取出来的单个函数的 bitcode**。
容器解析（MTLB 头、函数表、TLV 标签、universal metallib）由 Metal 的
`MTLLibraryBuilder` / `MTLLibraryContainer` / `MTLLibraryDataWithArchive` 完成
（`21` 第 2.2 节；`S-METAL` +0x2770A / +0x1C1A6 / +0x1C88E）。

**建议**：`30` 第 1 节（1.1–1.10）改标题与前言，明确它服务于两种场景而**不是** compiler plugin 主路径：
- 离线工具链与 corpus 测试（`30` 第 7.3 节已经这么用了）；
- 第 8.4 节的方案 D 后备。

主路径的输入契约改写成：**单函数 LLVM bitcode 模块，`(const void *, size_t)`**。
**未查清**：这块 bitcode 是否带 `30` 第 1.3 节的 bitcode wrapper 头（`0x0B17C0DE`）。
Intel plugin 用 `llvm::parseBitcodeFile(MemoryBufferRef)` + 自有 `readBitcode`，两者都能吃裸 bitcode；
`getTargetTripleOSMajor` 在 parse 之后才用。**实现时必须两种都接受**：看前 4 字节是
`BC\xC0\xDE` 还是 `0x0B17C0DE`，后者跳过 wrapper。`INFERRED`

### 9.3 建议二：新增一节覆盖 FlatBuffers `Air` schema（当前是空白）

第 6 节的那套 `AIRF` / `AIRP` FlatBuffers 请求**在 `30` 与 `31` 里都没有对应内容**，
但它是 plugin 的第二个输入，承载顶点属性、buffer 布局、颜色附件、函数分组。
**建议**：在 `30` 新增一节（或并入 `31`），内容是第 6 节 + 其中列出的取得方法。
在它查清之前，`31-PIPELINE-ARTIFACT.md` 里"固定功能状态从哪里来"这个问题有两个答案
（FlatBuffers request / ObjC descriptor），必须显式二选一 —— 本文第 8.1 节建议选 ObjC descriptor。

### 9.4 建议三：按 legalization pass 削减 AIR 覆盖范围（最实质的一处）

第 5.5.1 节的 8 个 pass 名意味着 plugin 可以声明不支持一整族特性，由上游先降级。
对照 `30` 第 6.3、6.4 节的缺口清单，**下列条目可以从"必须实现"降为"由 legalization 消除"**：

| `30` 的条目 | 处置 |
|---|---|
| 第 5.2 节"光线求交"全族、第 6.3 节 `ray tracing` | 报 `air-raytracing-emulation` → 不实现 |
| bfloat16 相关（第 5.5 节版本差异） | 报 `air-bfloat-emulation` → 不实现 |
| 16 位纹理坐标采样变体 | 报 `air-16bit-texture-coordinate-emulation` → 不实现 |
| vertex amplification（第 4.7 节 Builtin） | 报 `air-degenerate-vertex-amplification-emulation` → 不实现 |
| post-tessellation patch 输入（第 4.9 节） | 报 `mtl-fetch-compute-tessellation` → 作为 compute 处理 |
| visible function 链接 / stitching（第 4.13 节）中 vertex/fragment 阶段那部分 | 报 `mtl-vertex-linking`、`mtl-fragment-linking` |
| TLS | 报 `air-tls-emulation` |

**这不是能力裁剪**（`00-OVERVIEW.md` 第 4.7 节禁止用分档裁剪规格）：
特性对客户端仍然可用，只是降级发生在 Metal 侧而不是本项目侧。**本项目的能力矩阵不因此变差。**
`60-CAPABILITY-MATRIX.md` 应据此把这些行从"本项目未实现"改为"由 Metal legalization 承担"。

**前置实测**：必须验证 Metal 真的尊重 `AIRNTGetLegalizationPasses` 的返回值
（即报了 `air-raytracing-emulation` 之后，到达 plugin 的 bitcode 里确实没有 `air.ray*` intrinsic）。
在第一条 pipeline 跑通后，把收到的 bitcode dump 下来对照即可，属 `TESTED` 级。

### 9.5 不需要改的部分

`30` 第 2–5 节（bitcode 方言、封闭指令集、address space、metadata ABI、`air.*` intrinsic 清单）
**全部仍然必需且位置正确** —— 那就是 plugin 拿到字节之后要做的事。
第 7 节（扩展与维护方法、吸收方案）同样不变。

---

## 10. 本项目要实现的最小 plugin

`INFERRED`（设计），基于第 5 节的 `KNOWN` 证据。

### 10.1 交付形态

```
<Name>.bundle/
  Contents/
    Info.plist                 NSPrincipalClass = 本项目的 _MTLDevice 子类
    MacOS/<Name>               driver plugin（ObjC，21 分册）
    Resources/
      lib<Name>CompilerPlugin.dylib    ← 本文的产物
```

- Mach-O 类型 `MH_DYLIB`，arch **x86_64**（不必 x86_64h）。
- 依赖面照 Intel：`libSystem` + `libc++` 足够；Rust 实现时静态链接，再加一层 `extern "C"` shim。
- `install_name` 无关紧要（Intel 用的是 `/usr/local/lib/...`）。
- 研发期 SIP/AMFI 关，文件在磁盘上即可，不需要进 dyld shared cache。

### 10.2 导出符号清单（40 个）

照第 5.1 节 A 组 4 个 + B 组 36 个全部导出。**不要**导出 C 组那 6 个。
用 export list 文件固定，防止 Rust/C++ 的内部符号泄漏。

### 10.3 必须处理的调用序列

`INFERRED`（顺序）。已 `KNOWN` 的只有"`AIRNTEmitPipelineImage` 内部调
`MTLCompilerBuildRequestWithSerializedBitcode`"这一跳（第 5.5.2 节）。
完整顺序要等第 4.1 节闭合或实测。按 Intel 的实现形状，安全的实现顺序是：

```
1) 加载期（每个进程一次）
   AIRNTInit()                                   -> PluginCtx
   AIRNTGetVersion / GetVendorName / GetLLVMVersion / GetSupportedBitcodeVersion
   AIRNTGetSupportedArchs / GetDefaultArch
   AIRNTSupportsThreads
   AIRNTParseCommandLineOptions(...)             （可空）

2) 设备协商（每个 device 一次）
   AIRNTSupportsTarget(Ctx, cpuType, cpuSubtype, platform=1)
   AIRNTSupportsArch(Ctx, cpuType, cpuSubtype)
   AIRNTGetPreferredAIRArch(Ctx, …, langVersion, &outCpuType, &outSubtype)
   AIRNTGetLegalizationPasses(Ctx, …, deviceKey, &passes, &count)   ← 报全部 8 个
   MTLCompilerCreate(createArgs)                 -> Compiler       （由 MTLCodeGenServiceSetPluginPath 触发）

3) 缓存查询（每个函数，可能先于编译）
   AIRNTGetFunctionId / GetVertexFunctionId / GetFragmentFunctionId /
   GetComputeFunctionId / GetTileFunctionId / GetObjectFunctionId /
   GetMeshFunctionId / GetBuiltinFunctionId      -> 32 字节哈希

4) 编译（每条 pipeline）
   AIRNTInitCompilationContext(a1, a2)           -> CompCtx
   AIRNTEmitPipelineImage(Ctx, …, bitcode, len, …, serializedPipelineDescriptor, …,
                          &reply, …, &stats, &statsLen, &errStr)
     └─ MTLCompilerBuildRequestWithSerializedBitcode(Compiler, request, …, bitcode, len,
                                                     &reply, …, &stats, &statsLen, &errStr)
   AIRNTDisposeCompilationContext(CompCtx)
   MTLCompilerReleaseReply(Compiler)             ← 上层取走 reply 之后

5) 卸载
   MTLCompilerDelete(Compiler)
   AIRNTDispose(Ctx)
```

### 10.4 实现侧的 8 条硬规则

1. **`MTLCompilerBuildRequestWithSerializedBitcode` 成功返回 0，失败返回 1。** 别反。
2. **失败必须写 `*outErrorString`**，`new char[]`，内容是人读的英文串。
   它最终经 `MTLCompiler` 包成 `NSError` 交给应用（`21` 第 9.4 节：驱动层只报字符串）。
3. **成功必须写 `*outReply` 并把同一指针留在 compiler 实例里**，供 `MTLCompilerReleaseReply` 回收。
   产物缓冲用 `malloc`、错误串用 `new[]` —— 释放端按这两种配对，不能混。
4. **reply 里不能有指针、不能有进程地址。** plugin 可能在独立的 `MTLCompilerService` 进程里（第 4 节）。
5. **`flags & 2` 时必须写 `*outStats`（40 字节 `malloc`）与 `*outStatsLen = 40`**。
   不写而上层读会崩。内容可以全 0，只要把末 8 字节填成耗时即可（驱动侧会忽略，但上层统计会读）。
6. **`*request == 0/2/3` 之外必须报错，不要 `assert`。** Intel 用 `__assert_rtn`，release 版也会终止进程；
   本项目应写错误串 + `return 1`（与 `21` 第 2.5 节"`return nil` 比 `doesNotRecognizeSelector:` 安全"同理）。
7. **`AIRNTGet*FunctionId` 必须随构建变化**（第 7.3 节）。
8. **plugin 内部不要假定单线程，但也不要以为自己要做并发**：`AIRNTSupportsThreads` 报 0，
   每个 compiler 句柄串行使用；跨句柄并发要安全。

### 10.5 验收点（接 `80-TEST-HARNESS.md`）

1. `[[MTLCompiler alloc] initWithTargetData:…]` 返回非 nil，且 `-[MTLCompiler pluginPath]` 等于预期路径。
   只能证明注册成功，**不能证明 plugin 被加载**（第 3.2 节）。
2. 一条最小 render pipeline 创建成功：`newRenderPipelineStateWithDescriptor:error:` 返回非 nil。
   这一步同时覆盖 `MTLCompiler.framework` 的全部未知 gate（第 4.1 节）。
3. 在 plugin 里把收到的 bitcode 与 FlatBuffers request 原样 dump 到磁盘。
   这一个动作同时关闭第 6 节、第 9.2 节、第 9.4 节的全部 `BLOCKED`。**优先级最高。**
4. 重启后再建同一条 pipeline，确认命中第 7 节的磁盘缓存（plugin 不被调用）。

---

## 11. 未查清事项汇总

| # | 事项 | 标签 | 取得方法 | 优先级 |
|---|---|---|---|---|
| 1 | `libAppleParavirtCompilerPlugin.dylib` 本体 | `BLOCKED` | 第 1.3 节（APFS + LZVN，或换 macOS/Linux 机，或 guest 内取） | 中（Intel 件已可替代） |
| 2 | `MTLCompiler.framework/Versions/32023/MTLCompiler` | `BLOCKED` | 同第 1.3 节，同一步 | **高** —— 它定义 `dlsym` 清单与版本协商 |
| 3 | `compilerFlags` bit 5 (`0x20`) 的语义 | `BLOCKED` | 第 3.4 节三条路 | 中 |
| 4 | FlatBuffers `Air` / `Mtl4` schema 的字段表 | `BLOCKED` | 第 6 节三条路；**第 10.5 节验收点 3 一次解决** | **高** |
| 5 | plugin 收到的 bitcode 是否带 bitcode wrapper 头 | `INFERRED` | 同上 | 中（实现上两种都接受即可） |
| 6 | `AIRNT*` arch 枚举（cpuType / cpuSubtype）本项目该填什么 | `BLOCKED` | 第 5.5 节末：先全接受 + log 实际请求值 | 中 |
| 7 | Metal 是否真的尊重 `AIRNTGetLegalizationPasses` | `INFERRED` | 第 9.4 节末，验收点 3 | **高** —— 决定 `30` 的范围 |
| 8 | monolithic vs XPC 的选择规则 | `INFERRED` | 反编译 `MTLCompilerConnectionManager::getIsMonolithic`（`S-METAL` +0xCA278）与 `MTLCompilerConnectionManagerInternal` 构造（+0x12FBDE） | 低（两种都要支持） |
| 9 | shader 缓存目录的完整路径串 | `INFERRED` | 反编译 `copyCacheMainFolder`，或 guest 内 `ls` | 低 |
| 10 | `"%u_%u"` 缓存名里那两个 u32 的来源 selector | `INFERRED` | 槽 `S-METAL` +0x7FF8410157A0 / +0x7FF841015168 / +0x7FF8410169A0；按 `21` 第 12.1 节的三条路解名 | 低 |
| 11 | `MTLCodeGenService*` 四个函数的完整签名 | `BLOCKED` | 与 #2 同 | 低（本项目不实现它们） |
| 12 | 全链路未实测 | — | 本文无一条 `TESTED` | — |

### 11.1 本文关闭的既有 `BLOCKED`

| 既有条目 | 新状态 |
|---|---|
| `21-OBJC-OBJECT-FAMILY.md` 第 12.3 节（`compilerFlags` 语义） | **部分关闭**：bit 7/8/9 已解码，bit 5 仍 `BLOCKED`（本文 3.4） |
| `21-OBJC-OBJECT-FAMILY.md` 第 12.4 节（plugin 未取得） | **取得方法作废、重写**：不在 payloadv2，在 dyld shared cache；替代样本已入库（本文 1.1–1.4） |
| "不拿到它就不知道 `MTLCompiler` 与 compiler plugin 之间的接口长什么样" | **关闭**：接口已还原（本文 4、5 节） |
