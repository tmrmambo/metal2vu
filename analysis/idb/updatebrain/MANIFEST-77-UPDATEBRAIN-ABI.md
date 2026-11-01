# UpdateBrain 接口逆向样本与 IDB（分册 `77-UPDATEBRAIN-ABI.md`）

- 架构目标：`x86_64`（universal 的 x86_64 slice）
- 来源：`142-36613 - 26.7.2 macOS Tahoe (25G325)/UpdateBrain.zip`（普通 zip，Python `zipfile` 直接读）
- 提取日期：2026-11-01
- 提取平台：Windows + Python 3.14，纯只读解析，无 macOS 工具参与
- IDA：headless（`idat`）worker，ida-domain API
- 本目录只新增文件，没有修改仓库任何既有文件。
- 发布边界：样本（`*.dylib`、无扩展名的 service 二进制）与 IDB（`*.i64`/`.id*`/`.nam`/`.til`）都落在 `.gitignore` 的排除规则内，不进仓；可复现性由下表 SHA-256 保证。

## 1. 来源链

```
UpdateBrain.zip                                                 4,392,999 bytes
  SHA-256 C87D840F1FF673AD964805E2C75D817A618AB98CE0EA44589574B1CE974D04D5
  顶层 Info.plist: MobileAssetProperties.Build = 25G325 / OSVersion = 26.7.2
                    _ContentVersion = 2422160006700002（= LC_SOURCE_VERSION 2422.160.6.700.2）
  |
  +-- AssetData/com.apple.MobileSoftwareUpdate.UpdateBrainService.xpc/Contents/
  |     MacOS/UpdateBrainLibrary.dylib                         11,717,552 bytes（universal）
  |     MacOS/com.apple.MobileSoftwareUpdate.UpdateBrainService   172,544 bytes（universal）
  |     Resources/UpdateBrainService.sb                           1,849 bytes
  |     Info.plist                                                2,123 bytes
  +-- Info.plist                                                  1,439 bytes
  +-- AssetData/.TrustCache                                       2,740 bytes
```

## 2. 样本（`analysis/binaries/updatebrain/`）

| 文件 | 字节 | arch / subtype | Mach-O 类型 | `LC_UUID` | `LC_SOURCE_VERSION` | platform | SHA-256 |
|---|---:|---|---|---|---|---|---|
| `UpdateBrainLibrary.dylib`（universal 原件） | 11,717,552 | FAT：x86_64/3 + arm64e/2 | `MH_DYLIB` | — | 2422.160.6.700.2 | — | `010BCAF9DB3FD58A2DBE9B99EDB6303BB9AE37816AA67ACC18146CADDB3BFDC2` |
| `UpdateBrainLibrary.x86_64.dylib`（thin slice，IDB 输入） | 5,543,200 | x86_64 / 3 | `MH_DYLIB` | `AD034192-FC60-3A23-B517-62E39B45B640` | 2422.160.6.700.2 | macOS minos 11.0 / sdk 26.7.1 | `2A06C21844893AE4D60E3F20E43D2F9F1C337DFD57EC3E56F04876CBF3575B55` |
| `com.apple.MobileSoftwareUpdate.UpdateBrainService`（universal 原件） | 172,544 | FAT：x86_64/3 + arm64/0 | `MH_EXECUTE` | — | 2422.160.6.700.2 | — | `42BCC575E435E980039AE5E5CEEDC4CF47572E15563886936C5A2BDA582B868A` |
| `UpdateBrainService.x86_64`（thin slice，IDB 输入） | 53,760 | x86_64 / 3 | `MH_EXECUTE` | `B8D41668-A172-35E8-81C0-0CF49884E1A7` | 2422.160.6.700.2 | macOS minos 11.0 / sdk 26.7.1 | `887F862C87E41680645DD1FC2513EB7E0B2A20A266F1E0E0244251B7BC42C9B3` |
| `UpdateBrainService.sb`（沙箱 profile） | 1,849 | — | — | — | — | — | `031CFBDB19FBF26AB36702C7B2DFBB3568E21C90DD526CDAD55787A446B87A10` |
| `TrustCache.bin`（`AssetData/.TrustCache`） | 2,740 | — | — | — | — | — | `EBC2EBE8D7A3B2B59B7AF445D40C0A5A772155DF26BD3D798C1544F01AE927B7` |

`UpdateBrainLibrary.dylib` 的 x86_64 slice 在 universal 文件内 off=16384 size=5,543,200；arm64e slice off=5,570,560 size=6,146,992（UUID `29D12338-060B-3AE2-95E7-F529B0C709F9`，本轮未做分析）。两个 slice 的 `LC_ID_DYLIB` 都是 `@rpath/UpdateBrainLibrary.dylib`。

service 二进制的 x86_64 slice off=16384 size=53,760；arm64 slice off=81,920 size=90,624（UUID `5E0F3D70-861A-3550-907C-F3B392434920`）。

## 3. IDB（`analysis/idb/updatebrain/`）

| IDB | 输入 slice UUID | 函数数 | 导出数 | 说明 |
|---|---|---:|---:|---|
| `UpdateBrainLibrary.x86_64.dylib.i64` | `AD034192-FC60-3A23-B517-62E39B45B640` | 10,871 | 1 | 主库。地址约定：RVA = IDA 显示的 VA（image base 0），即 thin slice 内文件偏移 |
| `UpdateBrainService.x86_64.i64` | `B8D41668-A172-35E8-81C0-0CF49884E1A7` | 2 | — | XPC service 启动桩。只有 `_main` + 一个到 dylib 的 thunk |

ObjC 元数据完整：`__objc_classlist` 可枚举 186 个类名，方法以 `-[Class sel]` / `+[Class sel]` 命名，130 个类在本 slice 内有方法实现。

## 4. 取证脚本（`analysis/binaries/updatebrain/tools/`）

| 脚本 | 职责 |
|---|---|
| `extract_updatebrain.py` | 从 `UpdateBrain.zip` 解出 6 个件到 `analysis/binaries/updatebrain/`，并解析 Mach-O 头报告 arch / `LC_UUID` / `LC_SOURCE_VERSION` / `LC_BUILD_VERSION` / SHA-256。`--report` 只对已解出的件复核 |
| `export_trie.py` | 解析 thin x86_64 Mach-O 的 export trie（`nm -gU` 的真相），按 `_OBJC_CLASS_$` / C 函数分组。对本库输出 "1 个导出：`_update_brain_service_main`" |

复现：

```powershell
py analysis\binaries\updatebrain\tools\extract_updatebrain.py
py analysis\binaries\updatebrain\tools\export_trie.py
```

然后把两个 `*.x86_64*` thin 件各自在 IDA 里打开做自动分析即得上表 IDB。

## 5. 关键 RVA 速查（x86_64 slice，image base 0）

| RVA | 符号 | 作用 |
|---|---|---|
| `0x419b3` | `_update_brain_service_main` | 唯一导出。self-sandbox + `xpc_main` 守护进程入口 |
| `0x4c2f4` | `_MSUPrepareUpdate_server` | PREPARE 相位引擎 |
| `0x4e0b2` | `_MSUApplyUpdate_server` | APPLY 相位引擎（arm ramdisk 重启） |
| `0x3eaf0` | `_handle_MSUPrepareUpdate_impl` | PrepareUpdate 的 xpc 请求拆包 |
| `0x408e0` | `_handle_MSUApplyUpdate_impl` | ApplyUpdate 的 xpc 请求拆包 |
| `0x39f960` | （dispatch table） | verb→handler 表，含 `allow-softwareupdated` 入场券 |
| `0x5574e` | `_prepare_snapshot` | 写 system volume + `createSnapshot` 封印 |
| `0x852d` | `_prepare_boot_environment` | bless `--setBoot` + 写 NVRAM fallback |
| `0xc15a` | `_run_bless_with_arguments` | `NSTask` 跑 `/usr/sbin/bless` |
| `0x27a5f` | `_personalize_boot_bundle` | cryptex1 / boot bundle 个性化（AMAuthInstall→TSS） |
| `0x6c5f` | `_prepare_personalization_files` | 并行解包/打补丁资产 prepare 文件（非 TSS） |
| `0x145024` | `-[LPStaticAPFSVolume createSnapshot:error:]` | `fs_snapshot_create(2)` syscall |
| `0x12d54` | `-[MSUTargetController prepareTargetVolumeForInstallRevertingToSnapshot:error:]` | 挂载/准备目标卷 |
| `0xf34d` | `-[MSUTargetController setSystemTargetWithVolumeGroupUUID:]` | 按 volume group UUID 指定目标 |
