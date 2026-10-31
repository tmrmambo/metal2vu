# MANIFEST — 分册 `32-COMPILER-PLUGIN.md` 的取证记录

- 轮次：第四轮（compiler plugin ABI）
- 日期：2026-10-30
- 目标：回答 `MTLCompiler` 与厂商 compiler plugin 之间的 ABI；闭合
  `docs/spec/21-OBJC-OBJECT-FAMILY.md` 第 12.3、12.4 节
- 产出文档：`docs/spec/32-COMPILER-PLUGIN.md`
- 平台：Windows + Python 3.14 + 官方 IDA MCP；首次 IDAPython 前已调用 `ida::reference`

**本轮只新增文件，没有修改或删除 `analysis/` 下任何既有文件。**
`analysis/idb/macos26-25G325-x86_64-frameworks/idb/Metal-BaseSystem-analysis.i64` 与
`analysis/idb/macos26-25G325-x86_64/AppleParavirtGPUMetal-apvmetal.i64` 均**复制到
`$env:TEMP\apv-cplug\idawork\` 后打开**，原件未被打开、未被写回。

## 1. 新增的二进制样本

| 文件 | 字节 | arch / subtype | Mach-O 类型 | `LC_UUID` | `LC_SOURCE_VERSION` | platform | `LC_ID_DYLIB` | SHA-256 |
|---|---:|---|---|---|---|---|---|---|
| `analysis/binaries/macos26-25G325-x86_64/metal-bundle/libMTLIGCCompilerPlugin.dylib` | 146,000 | `x86_64h` / 8 (Haswell) | `MH_DYLIB` | `C2C53566-81C9-303D-BA51-FD34BFF5CBE4` | `24.5.10.0.0` | macOS minos 10.15.0 / sdk 26.7.1 | `/usr/local/lib/libMTLIGCCompilerPlugin.dylib` | `F72D7F2A2249EB993CDE6F407E222432D13E709321E23820AB157C5F4C657058` |

元数据由 `analysis/binaries/macos26-25G325-x86_64/tools/macho.py` 的 `report()` 产生。
该件是 **thin**（原件就不是 FAT），所以未经过 `tools/thin.py`。

### 1.1 来源链

```
SharedSupport.dmg                                    18,366,480,610 bytes
  └─ UDIF → GPT "Apple_HFS" → HFS+ 卷
      └─ /com_apple_MobileAsset_MacSoftwareUpdate/d3cc6643f7010f6ec14cc728f4a47a7c7644e8a5.zip
          └─ AssetData/payloadv2/payload.047       （zip stored, 141,092,188 bytes）
              └─ pbzx → XZ → Apple Archive (YAA1)
                  └─ System/Library/Extensions/AppleIntelGraphicsShared.bundle/
                       Contents/MacOS/libMTLIGCCompilerPlugin.dylib    F  146000
```

抽取命令（在 `$env:TEMP\apv-cplug`，`tools/` 为仓库 `analysis/binaries/macos26-25G325-x86_64/tools/` 的副本）：

```powershell
py tools\extract_one.py payload.047 "System/Library/Extensions/AppleIntelGraphicsShared.bundle/Contents/MacOS/libMTLIGCCompilerPlugin.dylib"
```

`extract_one.py` 报告 `extracted [...] / missing []`，输出长度与归档头声明的 `DAT` 长度一致。

### 1.2 定位依据

`analysis/binaries/macos26-25G325-x86_64/payloadv2-full-index.tsv.zip`（458,715 条）中
`CompilerPlugin` 的**唯一**文件命中就是上面这一条。同一索引证明
`System/Library/Extensions/AppleParavirtGPUMetal.bundle/Contents/Resources/` 在 payloadv2 中
**只有目录条目、零个文件条目**，即 `libAppleParavirtCompilerPlugin.dylib` 不在安装资产的 payloadv2 里。
全部索引证据写在 `docs/spec/32-COMPILER-PLUGIN.md` 第 1.1 节。

## 2. 新增的 IDB

| IDB | 字节 | SHA-256 | 输入样本 | image base | 关键标注 |
|---|---:|---|---|---|---|
| `analysis/idb/macos26-25G325-x86_64/libMTLIGCCompilerPlugin-compilerplugin.i64` | 1,245,992 | `9C04080D40B67E678F23E11D779DACE8FA5B662D618CC58E826B25A0E859107B` | `metal-bundle/libMTLIGCCompilerPlugin.dylib` | `0x0` | compiler plugin 的 46 个导出符号与 `MTLCompilerBuildRequestWithSerializedBitcode` 的 13 参 ABI |

该 IDB 由 `ida::open_database` 自动分析后 `ida::save_database` 写出，脚本未做 rename / patch / 类型应用。

既有 IDB 的使用方式（**只读**）：

| IDB | 用法 |
|---|---|
| `analysis/idb/macos26-25G325-x86_64-frameworks/idb/Metal-BaseSystem-analysis.i64` | 复制为 `$env:TEMP\apv-cplug\idawork\Metal-compilerplugin.i64` 后打开。本轮**未**对该复制件执行 `save_database`，也未回写仓库 | 
| `analysis/idb/macos26-25G325-x86_64/AppleParavirtGPUMetal-apvmetal.i64` | 复制为 `$env:TEMP\apv-cplug\idawork\APVMetal-compilerplugin.i64`；本轮最终未使用（APV 侧结论直接引用 `21` 分册既有记录） |

## 3. 本轮重建的中间产物（未入库）

全部在 `$env:TEMP\apv-cplug\`，总计约 4.6 GB，**刻意不入库**。

| 文件 | 字节 | SHA-256 | 说明 |
|---|---:|---|---|
| `bs.bxdiff` | 891,864,876 | `35745579C8FBC20ABBD98E5954B70BE22F329DF199D06429604A042F8765827E` | `AssetData/payloadv2/basesystem_patches/x86_64BaseSystem.dmg`，`BXDIFF50` 全量替换补丁。zip **stored**，header offset 6,867,904,670 |
| `x86_64BaseSystem.dmg` | 1,464,270,504 | `642E6148288527C51639D1B08C7F0B5A8CB4A68AEC2AC6DA3C78CF1723C5119A` | `ipsw 3.1.739 ota patch bxdiff -s` 的输出。**与 `analysis/spec-work/metal-registration-contract.md` 第 1.1 节既有记录逐位相同** |
| `apfs.part` | 1,396,506,624 | — | `ipsw disk dmg x86_64BaseSystem.dmg -p 3` 取出的 `Apple_APFS` 分区原始镜像 |

### 3.1 `BXDIFF50` 头字段（实读）

```
+0x00  "BXDIFF50"
+0x08  u64 ControlSize      = 0
+0x10  u64 PatchedFileSize  = 1,464,270,504   (0x5746FEA8)
+0x18  u64 DiffSize         = 0
+0x20  u64 ExtraSize        =   891,864,816   (0x3528C6F0)
+0x28  20 字节 SHA-1
+0x55 附近起 XZ 流（magic FD 37 7A 58 5A 00）
```

`ControlSize == 0 && DiffSize == 0` 即全量替换，所以 `-s` 模式的 TARGET 可以是一个 0 字节文件。

### 3.2 复现步骤

```powershell
$t = "$env:TEMP\apv-cplug"; mkdir $t; cd $t
cp -r "<repo>\analysis\binaries\macos26-25G325-x86_64\tools" .

# 1) Intel compiler plugin
py tools\extract_one.py payload.047 "System/Library/Extensions/AppleIntelGraphicsShared.bundle/Contents/MacOS/libMTLIGCCompilerPlugin.dylib"

# 2) BaseSystem 重建（约 25 分钟）
py zipget.py "AssetData/payloadv2/basesystem_patches/x86_64BaseSystem.dmg" bs.bxdiff
ni -ItemType File base_empty.dmg
ipsw ota patch bxdiff -s bs.bxdiff base_empty.dmg -o bsout
mv bsout\base_empty.dmg x86_64BaseSystem.dmg

# 3) APFS 分区
ipsw disk dmg x86_64BaseSystem.dmg -p 3 -o apfs.part
```

`zipget.py` 是本轮新写的 18 行脚本，用仓库既有 `tools/vfile.py::open_dmg_zip` 取内层 zip 的
可 seek 视图，再 `zipfile` + `shutil.copyfileobj` 导出单个 entry。源码附在第 6 节。

## 4. 阻断点（精确）

`libAppleParavirtCompilerPlugin.dylib` 与 `MTLCompiler.framework/Versions/32023/MTLCompiler`
都在 BaseSystem 的 dyld shared cache 里，而那两个 cache 文件在 APFS 卷上是
**AppleFSCompression（decmpfs）存储**：

- `apfs.part` 内扫到两份 cache 的 inode 与明文 UUID：
  `dyld_shared_cache_x86_64` → `B1090D84-48D4-3D45-94E6-A5C7F9CE7DE7`，
  `dyld_shared_cache_x86_64.01` → `ADDD15FF-C4C5-36EC-8ED1-88BB9F5C8F49`
  （两者与 `metal-registration-contract.md` 第 1.1 节记录一致）。
- 每个 inode 旁有 `com.apple.decmpfs` 与 `com.apple.ResourceFork` 两个 xattr；
  decmpfs 头为 `'fpmc'` + `compression_type = 8`（LZVN，数据在 resource fork）。
- `dyld_v1  x86_64` 这个 16 字节 magic 能被扫到（LZVN literal run），
  但紧随其后的字段已是回引用 token：`mappingOffset` 解出 `0x228`（可信），
  `mappingCount` 解出 `0x01380004`（垃圾）。因此直接 carve 不可行。

闭合需要 APFS B 树遍历 + resource fork 读取 + LZVN 解压，三样本仓库都没有。
**不建议在 Windows 上重写。** 最小代价路径见 `docs/spec/32-COMPILER-PLUGIN.md` 第 1.3 节。

## 5. 分析覆盖面

### 5.1 `S-METAL`（`Metal-BaseSystem-analysis.i64` 的复制件，base `0x7FF80B179000`）

逐函数反编译并写入分册的：

| RVA | 符号 |
|---|---|
| `0x1D1D7` | `-[MTLCompiler initWithTargetData:cacheUUID:pluginPath:device:compilerFlags:]`（9 条指令，尾调下一行） |
| `0x17C367` | `-[MTLCompiler initWithTargetData:cacheUUID:pluginPath:device:compilerFlags:fallbackDeviceFeatureProfile:]` |
| `0x12FE7E` | `MTLCompilerConnectionManagerInternal::registerCompilerPlugin(const char*, dispatch_data_t)` |
| `0x1304A6` | `MTLCompilerConnectionManagerInternal::getCompilerPluginAtIndex(unsigned long long)` |
| `0x173357` | `getCompilerConnectionManager(id<MTLDeviceSPI>, int)` |
| `0x11CBC0` | `-[_MTLDevice getCompilerConnectionManager:]` |
| `0x1649E3` | `_MTLGetMTLCompilerLLVMVersionForDevice(id<MTLDevice>)` |
| `0x164A98` | 同上的 `_block_invoke`（env `MTL_USE_DEVICE_LLVM_VERSION_SELECTOR`） |
| `0x3DAD6` | `MTLMonolithicCompilerConnection::attemptLazyInit()` |
| `0x3DCE6` | `CompilerPluginInterface::CompilerPluginInterface(int)` ← **dlopen + 4 个 dlsym** |
| `0x3DCCA` | `CompilerPluginInterface::~CompilerPluginInterface()` |
| `0x17B18B` | `MTLGetCompilerOptions(id<MTLDeviceSPI>, unsigned long, unsigned long, MTLCompileType, bool, MTLCompilerBitCodeType)` |
| `0x1951A1` | `-[MTLCompiler allowLibrariesFromOtherPlatforms]`（确证 compilerFlags bit 7） |
| `0x1951DC` | `-[MTLCompiler compilerFlags]` |
| `0x17ED65` | `-[MTLCompiler getFunctionId:airScript:vendorPluginFunctionId:bitcodeHashList:]` ← **`AIRF`/`AIRP` 与缓存键** |
| `0x17C05A` | `addOrRemoveShaderFunctionCache(id<MTLDeviceSPI>, MTLUINT256_t, bool)` |
| `0x17C54C` | `-[MTLCompiler unloadShaderCaches]` |
| `0x17C5C5` | `-[MTLCompiler copyShaderCacheToPath:]` |
| `0x11040B` / `0x110429` / `0x5EC5F` | `_MTLGetShaderCachePath` 与 `getShaderCacheMainFolder` |
| `0x1FE5C` / `0x1FC2E` / `0x25544` | 三个 `-[_MTLDevice new*VariantWithCompilerOutput:…]`（取裸 selector 槽） |
| `0x1FC8D` | `-[MTLFunctionVariant initWithCompilerOutput:]` |

另有两次全量扫描：

1. `-[MTLCompiler *]` 全部 **119** 个 IMP 逐个反编译，grep `_compilerFlags`，命中 16 个函数
   → 证明 `compilerFlags` 只有第 3.4 节那两类消费者。
2. 对 selref 槽 `0x7FF841017750`（4 处）与 `0x7FF8410163E0`（10 处）取 `data_refs_to`，
   按调用方函数名反证它们分别是 `llvmVersion` 与 `featureProfile`。
   后者的调用方含 `-[_MTLDevice initLimits]`、`initGPUFamilySupport`、`-[_MTLDeviceFeatureQueries initWithDevice:]`。

### 5.2 `S-IGCPLUG`（`libMTLIGCCompilerPlugin.dylib`，base `0x0`）

- `LC_SYMTAB` 全量读取：`nsyms = 1313`，defined-external **46**，undefined **88**，local 0。
- 逐函数反编译：`MTLCompilerCreate` (0x225F)、`MTLCompilerDelete` (0x22C0)、
  `MTLCompilerReleaseReply` (0x22F0)、`MTLCompilerBuildRequestWithSerializedBitcode` (0x2338)、
  `sub_28D3`（产物封装）、`AIRNTInit` (0x33B7)、`AIRNTGetVersion` (0x3441)、
  `AIRNTGetVendorName` (0x3453)、`AIRNTGetLLVMVersion` (0x33AF)、
  `AIRNTGetDefaultArch` (0x3460)、`AIRNTGetSupportedArchs` (0x3472)、
  `AIRNTSupportsArch` (0x3513)、`AIRNTGetSupportedImpls` (0x3505)、
  `AIRNTGetSupportedBitcodeVersion` (0x3557)、`AIRNTSupportsTarget` (0x4279)、
  `AIRNTGetPreferredAIRArch` (0x42F3)、`AIRNTSupportsThreads` (0x3A75)、
  `AIRNTGetLegalizationPasses` (0x3871)、`AIRNTInitCompilationContext` (0x3B39)、
  `AIRNTEmitPipelineImage` (0x3B6D)、`AIRNTGetFunctionId` (0x3D2C)。
- 字符串表全量导出（约 180 条有效），其中直接支撑分册结论的：
  `libigc.dylib`、`CreateShaderCompilerAIR`、`CompileVSAIRFn`/`CompilePSAIRFn`/`CompileCSAIRFn`、
  `readBitcode`、`getTargetTripleOSMajor`、`trusted_dlopen`、`FlatBuffers 1.12.0`、
  `air.vertex`、`air.patch`、`mtl.serialized_link_info`、`MTLIntelCompilerPlugin.cpp`、
  `AIRNTInterface.cpp`、以及第 5.5.1 节那 8 个 legalization pass 名。
- undefined 符号中确证 plugin 自己解析 bitcode 的那组：
  `llvm::parseBitcodeFile(MemoryBufferRef, LLVMContext&, function_ref<...>)`、
  `llvm::LLVMContext::{ctor,dtor}`、`llvm::Module::~Module`、`llvm::Module::getNamedMetadata(Twine const&)`、
  `llvm::NamedMDNode::getOperand(unsigned)`、`llvm::MDString::getString()`、
  `llvm::Triple::Triple(Twine const&)`、`llvm::Triple::getOSVersion()`。
- undefined 符号中确证 FlatBuffers `Air` schema 的那组（7 个
  `flatbuffers::data<flatbuffers::Offset<T>>` 的局部静态保护变量）：
  `Air::FunctionGroup`、`Air::AttributeDescriptor`、`Air::BufferLayoutDescriptor`、
  `Air::PipelineBufferDescriptor`、`Air::FragmentColorAttachmentDescriptor`、
  `flatbuffers::String`、`unsigned long long`。
- 另：`CC_SHA256_{Init,Update,Final}`、`gpu_bundle_is_path_trusted`、
  `__dyld_shared_cache_contains_path`、`dlopen`/`dlsym`/`dladdr`/`dlclose`/`dlerror`。

## 6. 本轮新写的脚本（`$env:TEMP\apv-cplug`，未入库）

| 脚本 | 行数 | 职责 |
|---|---:|---|
| `zipget.py` | 29 | 用 `tools/vfile.py::open_dmg_zip` 从内层 OTA zip 导出单个 entry |
| `inspect.py` | 190 | Mach-O 段/依赖/rpath/export trie 报告（export trie 走通后被 `syms.py` 取代） |
| `syms.py` | 52 | `LC_SYMTAB` 分类（defined-external / undefined / local） |
| `findcache2.py` | 95 | 在原始镜像里按 `dyld_v1` magic + 头字段合理性筛选并 carve dyld cache（因 decmpfs 压缩返回 0 命中） |
| `probe.py` | 33 | 在原始镜像里定位 `dyld_v1` / `dyld_shared_cache_x86_64` / 目标文件名，并 dump 命中处上下文 96 字节 |

`zipget.py` 全文：

```python
"""Copy one stored/deflated entry out of the nested asset zip inside SharedSupport.dmg."""
import io, os, shutil, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), 'tools'))
import zipfile
from vfile import open_dmg_zip

DMG = r'c:\Users\viola\Documents\KVM MacOS\SharedSupport.dmg'

def main():
    name, out = sys.argv[1], sys.argv[2]
    rf, _p, _s = open_dmg_zip(DMG)
    z = zipfile.ZipFile(io.BufferedReader(rf, 1 << 22))
    info = z.getinfo(name)
    print('entry', info.filename, 'size', info.file_size,
          'compress', info.compress_type, 'hdr_off', info.header_offset, flush=True)
    with z.open(info) as src, open(out, 'wb') as dst:
        shutil.copyfileobj(src, dst, 1 << 22)
    print('wrote', out, os.path.getsize(out), flush=True)

main()
```

这 5 个脚本都只做读取与报告，没有一个写入仓库目录。若后续要复现，
把它们和 `tools/` 一起放进 `$env:TEMP` 即可；按 `MANIFEST.md` 第 8 节的约定，
**不要在仓库目录内跑**（中间产物 4.6 GB）。

## 7. 证据等级声明

本轮**没有任何 `TESTED` 结论**。全部为 `KNOWN`（二进制直接证明）、
`INFERRED`（由结构合理推出）或 `BLOCKED`（见第 4 节与分册第 11 节）。
验收点见 `docs/spec/32-COMPILER-PLUGIN.md` 第 10.5 节。
