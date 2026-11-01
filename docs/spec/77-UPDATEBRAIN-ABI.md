# 77 `UpdateBrainLibrary.dylib` 接口逆向：能不能从我们自己的 root 进程驱动它装资产

文档版本：1.0
基线：macOS Tahoe 26.7.2 / build 25G325 / **x86_64**
对应组件：`142-36613 - 26.7.2 macOS Tahoe (25G325)/UpdateBrain.zip` 内的 `UpdateBrainLibrary.dylib`
上级文档：`docs/spec/75-IMAGE-PREBAKE.md`（第 0.0 节确立 R6）
配套：`docs/spec/91-RUNTIME-EVIDENCE.md`（CI 实测通道）、`analysis/idb/updatebrain/MANIFEST-77-UPDATEBRAIN-ABI.md`

## 0. 本文作用与约定

本文回答 `75` 第 0.0 节新增的 R6 留下的那个问题：**从一个 SIP 关闭的 root 进程里 `dlopen` 这个 dylib，要调哪些东西、按什么顺序、喂什么参数，才能让它把一份 `payloadv2` 资产装到我们指定的目标卷上。**

### 0.1 样本与地址约定

样本、SHA-256、`LC_UUID`、IDB 均登记在 `analysis/idb/updatebrain/MANIFEST-77-UPDATEBRAIN-ABI.md`。本文只用 x86_64 slice：

- 主库 `UpdateBrainLibrary.x86_64.dylib`，`LC_UUID AD034192-FC60-3A23-B517-62E39B45B640`，`LC_SOURCE_VERSION 2422.160.6.700.2`。
- 启动桩 `UpdateBrainService.x86_64`，`LC_UUID B8D41668-A172-35E8-81C0-0CF49884E1A7`。

**地址写成 RVA**，RVA = IDA 对 thin slice 显示的 VA（image base 0），等于该 slice 内的文件偏移。

证据标签：
- `KNOWN` = 反汇编/字符串直接读出，带 RVA。
- `INFERRED` = 对控制流或运行期行为的解释，没有直接读出。
- `BLOCKED` = 静态定不下来，必须在运行环境实测。

### 0.2 对 `75` 第 0.0 节的两处订正

1. **类名**：`75` 的线索写 `MSUSFRTargetController`。x86_64 slice 里**没有这个类**，对应的类是 **`MSUTargetController`**（`+[MSUTargetController sharedController]` RVA `0xe44e`）。`prepareTargetVolumeForInstallRevertingToSnapshot:error:` / `mountTargetVolumeRevertingToSnapshot:error:` / `rootSnapshotNameForTarget` 都是它的实例方法（RVA `0x12d54` / `0x129f2` / `0x129ad`）。`75` 的名字疑似取自 arm64 slice 或一次跨 slice 的 strings grep。`KNOWN`。
2. **封印的性质**：`75` 把"封印 + Preboot + cryptex"整体当成"只有 Apple 工具会做、可能需要联网"的黑箱。本文把它拆开：**SSV 封印是一条本地 syscall，不联网**（第 D 节）；**联网只出现在 cryptex1 / boot bundle 个性化**，而且那一步有明确的跳过分支（第 D、F 节）。

## 1. 结论先行

| # | 问题 | 结论 | 标签 |
|---|---|---|---|
| 1 | 唯一导出符号 | **只有一个**：`_update_brain_service_main`（RVA `0x419b3`）。ObjC 类全部 hidden visibility，不在导出表，只能靠 `objc_getClass` 拿 | `KNOWN` |
| 2 | 那个导出是不是"装资产"的入口 | **不是**。它 self-sandbox 后直接 `xpc_main`，变成一个 XPC 守护进程，干活靠 XPC 客户端发消息 | `KNOWN` |
| 3 | 172 KB 的小二进制在调什么 | 纯启动桩：`main` 只 `return _update_brain_service_main(argc,argv,envp)` | `KNOWN` |
| 4 | 真正的协议 | raw-XPC：verb 字符串 `PrepareUpdate` / `ApplyUpdate` / `SuspendUpdate` / `ResumeUpdate` / `PingService`，查表派发到 C `_handle_MSU*`，每个 verb 要求 peer 带 `allow-softwareupdated` entitlement | `KNOWN` |
| 5 | 目标卷怎么指定 | update-attributes 字典里的 `clientProvidedTargetUUID`，落到 `-[MSUTargetController setSystemTargetWithVolumeGroupUUID:]`；缺省用 booted OS | `KNOWN` |
| 6 | 封印怎么做 | `-[LPStaticAPFSVolume createSnapshot:error:]` → **`fs_snapshot_create(2)` 本地 syscall**（RVA `0x145024`）。APFS 内核算 seal，不联网 | `KNOWN` |
| 7 | cryptex1 个性化 | 在 **PREPARE 相位**调 `AMAuthInstallBundlePersonalize`，组 TSS 请求发 `https://gs.apple.com:443/`。**但有跳过分支**（splat 关 / 已 pre-personalized / 无 boot bundle） | `KNOWN` 调用存在；`BLOCKED` 跳不跳 |
| 8 | 改固件 NVRAM | 在 **APPLY 相位**：`_prepare_boot_environment`（RVA `0x852d`）跑 `bless … --setBoot` 并写 NVRAM fallback。**这一步我们绝不能让它跑** | `KNOWN` |
| 9 | R6 死活 | **不是被封印挡死**（本地）；**卡在一条未知**：x86/VMM 的 PREPARE 会不会被迫联网签 cryptex1。再加一条工程量：没有干净导出，驱动它要么按地址调内部函数、要么自己编排 ObjC | 见第 F 节 |

## A. 类与方法的全貌

`KNOWN`。`__objc_classlist` 共 **186 个类**，130 个在本 slice 有方法实现。按前缀分组（只列数量多或相关的）：

| 前缀 | 数量 | 代表类 | 性质 |
|---|---:|---|---|
| `NS*` | 39 | Foundation | 外部 |
| `UARPTLV*BackDeploy` / `UARP*BackDeploy` | 49 | 配件固件 TLV（Unified Accessory Restore Protocol） | 与 Intel VM 无关 |
| **`MSU*`** | **20** | 见下 | **本任务主体** |
| `*RestoreInfoFirmwareCopierBackDeploy` / `Ace3*` / `PS190*` / `PFX*` / `AppleTypeCRetimer*` | 多 | SoC / T2 / retimer / 配件固件 restore | 与非 T2 Intel VM 无关 |
| **`LP*`** | **5** | `LPStaticMedia` 及其 APFS 子类 | **APFS/媒体抽象** |
| `MA*` / `AS*` | 6 | MobileAsset / AssetService | 资产查询 |
| `NRD*` / `MSUNRD*` | 4 | NeRD（recovery/软更）客户端 | 多为 arm 软更 |
| `BI*` / `UM*` / `IASP*` / `OS*` | 多 | 构建信息 / 事件 / 进度 / 个性化 | 辅助 |

### A.1 `MSU*` 族（RVA 为方法实现地址）

| 类 | super | instanceSize | 方法数 | 作用（`KNOWN`） |
|---|---|---:|---:|---|
| `MSUBrainServerImpl` | NSObject | 40 | 27 | XPC 服务端对象。`+sharedInstance`(`0x3b909`)、`-startListener:`(`0x3b9b9`)、一组 `-_nsxpc*` 转发到 `-brain`(`0x3c3df`，返回 `_brain` ivar) |
| `MSUBrain` | NSObject | 8 | 10 | protocol 壳。`applyUpdate:progress:completion:`(`0x5408`)、`prepareUpdate:…`(`0x53fc`)、`preflightUpdate:…`(`0x53f6`) 在本 build **全是空桩**（`push/pop/ret`）；只有 `calculateUpdateStorageRequirements:…`(`0x5414`) 有体，转 `_MSUAssetCalculate*Sizes_server` |
| `MSUTargetController` | NSObject | 48 | 63 | **目标卷控制器**。详见 A.3 |
| `MSUAssetStager` | NSObject | 8 | 17 | `+stageAssetsUsingUpdateAttributes:withError:`(`0x20854`)、`+buildVersionFromAttributes:` 等。按 update-attributes 下/铺资产 |
| `MSUPrebrain` | NSObject | 40 | 35 | preflight 引擎。`-preflightPersonalize:options:updateAttributes:session:error:connection:callback:`(`0x47412`)、`-preflightPrerequisiteCheck:withError:`(`0x47953`)、`_diskIsInvalidStartupDisk:` 等磁盘判定 |
| `MSUTicket` | NSObject | 472 | 17 | ApImg4 ticket 解析。`+ticketWithPath:error:`(`0x560d3`)、`+ticketWithURL:error:`、`-nsih`/`-nsihString`、`-ticketData` |
| `MSUBootObjectCopier` | NSObject | 72 | 38 | Preboot / Recovery boot object 铺设 + ticket 写入。`-initWithSystemVolume:prebootVolume:uuid:`(`0x125c2b`)、`-populateSystemRecoveryVolume:buildIdentity:ticket:fetchBootObjectBlock:`(`0x127200`)、`-_writeTicketToDirectory:`(`0x128ea4`) |
| `MSUBootFirmwareUpdater` | NSObject | 88 | 48 | SPI/NAND iBoot/LLB/SEP 固件更新。`+requiresSEPInFW`(`0x14baec`)、`-apNonce`、`-updateBootFirmwareWithError:`。**嵌入式/T2/AS 专用** |
| `MSUMigrationHelper` | NSObject | 64 | 21 | firmlink + Data 模板 + preboot 迁移。`-createFirmlinks`(`0x11aade`)、`-dataTemplatePath`(`0x11aae9`)、`-preparePrebootVolumeForMigration:…`、`-queuePackagesForBootTimeInstall:` |
| `MSUFreeSpaceManager` | NSObject | 56 | 22 | 空间预留/清理。`-requestFreeSpace:…`(`0x16805`) |
| `MSUNRDUpdateBrainController` / `MSUBridgeOSController` / `MSUAnalytics` / `MSUDiskUsageMonitor` / `MSUPrebrain` 等 | NSObject | — | — | 软更编排 / bridgeOS / 遥测 / 磁盘监控 |

> **`MSUBrain` 的 10 个方法是空桩这件事很重要**（`KNOWN`，RVA `0x53f6`/`0x53fc`/`0x5408` 体内只有 `push rbp; mov rbp,rsp; pop rbp; retn`）。它说明本 build 的真正引擎**不在 ObjC `MSUBrain` 里**，而在 C 层（`_MSU*_server` / `_handle_MSU*`）。NSXPC 那套 `MSUBrainServerImpl` 接口是**残留/未接线**的；真正的协议是 raw-XPC（见 C.1）。`_nsxpcInvoke:args:options:completion:`(`0x3bf55`) 直接回 `error 1300 "not implemented"`。

### A.2 `LP*` 族

| 类 | super | instanceSize | 方法数 | 作用 |
|---|---|---:|---:|---|
| `LPStaticMedia` | NSObject | 12 | 44 | 媒体基类。`+mediaForPath:`(`0x1471ab`)、`+mediaForUUID:`(`0x148444`)、`+liveMediaForSnapshotAtPath:`(`0x148122`)、`+_copyLiveFilesystemIOMediaForRootedSnapshot`(`0x14992f`)、`-BSDName`/`-devNodePath`/`-mountPoint`、`+waitForIOMediaWithDevNode:` |
| `LPStaticAPFSVolume` | LPStaticMedia | 12 | 38 | APFS 卷。`-createSnapshot:error:`(`0x145024`)、`-rootToSnapshot:error:`(`0x1463b5`)、`-revertToSnapshot:options:error:`(`0x145e3c`)、`-deleteSnapshots:waitForDeletionFor:error:`(`0x1453c3`)、`-renameSnapshot:to:error:`(`0x1459b8`)、`-mountAtPath:options:error:`(`0x1425ef`)、`-setRole:withError:`(`0x14124a`)、`-eraseVolumeWithError:`(`0x141d60`) |
| `LPStaticAPFSContainer` | LPStaticMedia | 12 | 18 | APFS 容器。`-addVolumeWithName:role:caseSensitive:reserveSize:quotaSize:pairedVolume:error:`(`0x13ef51`)、`-volumeWithRole:group:`、`-prebootVolume`/`-recoveryVolume`/`-updateVolume` |
| `LPStaticPartitionMedia` | LPStaticMedia | 12 | 4 | 分区媒体 |
| `LPStaticAPFSPhysicalStore` | LPStaticMedia | 12 | 4 | 物理存储 |

`LP` 的几个 `instanceSize=12` 说明它们只是对 `IOMedia`/APFS 对象的瘦包装（一个指针 + flags）。`KNOWN`。

### A.3 `MSUTargetController`（最可能的入口族，63 个方法）

挑与"指定并准备目标卷"直接相关的（`KNOWN`，RVA 见括号）：

- 单例与栈：`+sharedController`(`0xe44e`)、`+pushController:`(`0xe4f0`)、`+popController`(`0xe5b6`)
- **指定目标**：`-setSystemTargetWithVolumeGroupUUID:`(`0xf34d`) / `:timeout:`(`0xf361`)、`-setSystemTargetUUID:`(`0xe78e`) / `:timeout:`(`0xe7a2`)、`-setTargetVolume:`(`0x16447`)、`-setTargetContainer:`(`0x1641f`)、`-setUpdateContainer:`(`0x163ed`)、`-setUpdateVolumeUUID:`(`0xf69e`)
- **解析**：`-_mediaForUUID:timeout:`(`0x16276`) → `+[LPStaticMedia mediaForUUID:]`；`-_primaryMedia`(`0x15e03`)
- **准备/挂载**：`-configureTargetVolumeForInstallWithError:`(`0x1078b`)、`-prepareTargetVolumeForInstallRevertingToSnapshot:error:`(`0x12d54`)、`-mountTargetVolumeRevertingToSnapshot:error:`(`0x129f2`)、`-mountAndGetUpdateVolumeMountPoint`(`0x15219`)、`-configureUpdateVolumeInContainer:reserveSize:erase:error:`(`0xfa1e`)、`-configureXARTPartitionWithError:`(`0x102eb`)
- **铺 Preboot/Recovery/BaseSystem**：`-populateSystemPrebootWithVariant:withError:`(`0x13a39`)、`-populatePairedRecoveryWithVariant:updateBundlePath:buildIdentity:supportStagedBoot:error:`(`0x1499a`)、`-copyBaseSystemToPath:fromImage:orPatch:baseImage:architecture:error:`(`0x149a2`)
- **卷取用**：`-targetVolume`(`0x15068`)、`-targetDataVolume`(`0x15089`)、`-targetPrebootVolume`(`0x15129`)、`-recoveryVolume`(`0x15179`)、`-updateVolume`(`0x151c9`)、`-targetContainer`(`0x16415`)、`-targetMountPath`(`0x157c8`)
- **校验**：`-validateTargetVolumeConfiguration:`(`0x1067f`)、`-targetVolumeIsRoot`(`0x1295b`)、`-rootSnapshotNameForTarget`(`0x129ad`)

### A.4 启动桩（Apple 自己的调用示例）

`KNOWN`。`UpdateBrainService.x86_64` 只有 2 个函数：

```c
int main(int argc, const char **argv, const char **envp) {       // RVA 0x6a8
    return update_brain_service_main(argc, argv, envp);           // RVA 0x6b2，thunk
}
```

`_update_brain_service_main` 是 `@rpath/UpdateBrainLibrary.dylib` 的导入符号。**所以 Apple 的"调用示例"就一句：把 `argc/argv/envp` 原样转交给 dylib 的那个导出。** 它没有演示任何 ObjC 调用——因为真正的交互在 dylib 里起的 XPC 服务上。

## B. 导出的 C 符号面

`KNOWN`。export trie 解析（`tools/export_trie.py`）：

```
exported symbols: 1
  0x000419b3  _update_brain_service_main        (纯 C，MH_DYLIB 唯一导出)
  _OBJC_CLASS_$ : 0    _OBJC_METACLASS_$ : 0    _OBJC_IVAR_$ : 0
```

含义，逐条：

- **能从外部 `dlsym` 直接拿到的入口只有一个**：`_update_brain_service_main`。
- **所有 ObjC 类都是 hidden visibility**，export trie 里零个 `_OBJC_CLASS_$`。但这不挡 `objc_getClass("MSUTargetController")`：ObjC 运行期在 `dlopen` 时把 `__objc_classlist` 全量注册，和符号可见性无关。`INFERRED`（标准 ObjC 运行期行为）。
- `_MSUPrepareUpdate_server`(`0x4c2f4`)、`_handle_MSUPrepareUpdate_impl`(`0x3eaf0`) 等引擎函数**都不是导出符号**，`dlsym` 拿不到，只能按"基址 + RVA"算地址（见 C.5）。
- 链接的框架 40 个（`KNOWN`，`LC_LOAD_DYLIB`），与本文相关的：`APFS`、`MobileAsset`、`OSPersonalization`、`MobileSoftwareUpdate`、`SoftwareUpdate`、`DeviceIdentity`、`AppleDeviceQuerySupport`、`MobileInBoxUpdate`、`DiskArbitration`、`DiskImages`、`CFNetwork`、`Security`、`libimg4.dylib`、`libcrypto.44.dylib`、`libMobileGestalt.dylib`。它要一套完整的 macOS 用户态在位，不能跨平台跑。

## C. 驱动它需要的最小调用序列

### C.1 入口点与真正的协议

`_update_brain_service_main`（RVA `0x419b3`）干这些（`KNOWN`，pseudocode 读出）：

1. `[[NSBundle mainBundle] pathForResource:@"UpdateBrainService" ofType:@"sb"]`。**找不到就 `return 72`**（日志 `UpdateBrainService.sb missing`），一件事不干。
2. `sandbox_init(<.sb 路径>, 3, &err)` self-sandbox。失败 `return 70`。
3. 起 dispatch queue、`atexit`、信号处理、把分区执行回调设成 `msu_execute_command_with_callback`（所有外部命令如 mount/bless 从这里过）。
4. `[[MSUBrainServerImpl sharedInstance] startListener:queue]`。
5. **`xpc_main(UpdateBrainService_event_handler)`** —— 从此变成 XPC 守护进程，阻塞。

`UpdateBrainService_event_handler` 按一张**派发表**（RVA `0x39f960`）工作，表项是 `{entitlement, verb, handler}`（`KNOWN`）：

| 入场券 entitlement | verb | handler |
|---|---|---|
| `allow-softwareupdated` | `PrepareUpdate` | `_handle_MSUPrepareUpdate`(`0x43574`) |
| `allow-softwareupdated` | `ApplyUpdate` | `_handle_MSUApplyUpdate`(`0x43745`) |
| `allow-softwareupdated` | `SuspendUpdate` | `_handle_MSUSuspendUpdate`(`0x4383a`) |
| `allow-softwareupdated` | `ResumeUpdate` | `_handle_MSUResumeUpdate`(`0x438c9`) |
| `allow-softwareupdated` | `PingService` | `_handle_MSUPingService`(`0x43941`) |

**所以 Apple 设计的驱动方式是**：一个带 `allow-softwareupdated` entitlement、且满足 XPC service `_AllowedClients`（`anchor apple`）的客户端，连上这个服务，发 `PrepareUpdate` 再发 `ApplyUpdate`。

**这条路我们走不了，而且现在能精确说出卡点**（`INFERRED`）：
- `_AllowedClients: anchor apple`（`xpc-Info.plist`）挡住"谁能连"——要 Apple 签名。
- 即便我们自己 `dlopen` 并 `_update_brain_service_main` 把服务跑起来，连它的客户端仍要过 `allow-softwareupdated` 的 entitlement 检查（在 event handler 里，派发前）。SIP/AMFI 关掉后这个检查是否还拦，未实测（`U-003`）。

### C.2 它要什么输入

PREPARE/APPLY 的 handler 第二个参数是一个 **update-attributes `CFDictionary`**（`KNOWN`，`_handle_MSUPrepareUpdate_impl` 签名 `(a1, const __CFDictionary *a2, …)`）。从 `_create_update_context_with_error`(`0x3209f`) 与 prepare handler 读出的键（`KNOWN`，节选）：

- 资产定位：package path（"Could not extract package path from request"）、`SplatComboBundlePath`、`RestoreVersionInfo`、`PreflightBuildManifest`
- 目标：`clientProvidedTargetUUID`（否则用 booted OS UUID）、`targetVolume`、`recoveryVolume`、`mountPoint`、`__CleanupTargetUUID`
- 尺寸：`InstallationSize-Snapshot`（类型错就报 `InstallationSize-Snapshot has invalid type in …`，RVA `0x294b04`/`0x294f34`）、`PrepareSize` / `SnapshotPrepareSize` / `ApplySize` / `SnapshotApplySize`
- 模式开关：`ota-arv-mode`、`__AllowPredownloadPersonalize`、`EnableManagedRequest`、`SocksProxySettings`、`cleanupLevel`、`forceEventResubmission`
- 一条 Intel 专属：日志 `Overriding assetHasBuildManifest = 1 on Intel`（RVA 近 `_create_update_context_with_error`）。`KNOWN`，说明 x86 路径强制"资产带 build manifest"。

`InstallationSize-Snapshot` 等尺寸键既从 update-attributes 读、也从资产 `Info.plist` 读（两套字符串都在）。这正是 `75` 第 0.0 节那条线索的来源。

### C.3 目标卷怎么指定

`KNOWN`。两条等价路径：

1. **update-attributes 里给 `clientProvidedTargetUUID`**。`_create_update_context_with_error` 日志 `Using clientProvidedTargetUUID for context: %@`，否则 `Using bootedOS UUID for context`。
2. **直接 `-[MSUTargetController setSystemTargetWithVolumeGroupUUID:]`**（RVA `0xf34d`）。控制器用 `-_mediaForUUID:timeout:` → `+[LPStaticMedia mediaForUUID:]` 把 UUID 解析成 `IOMedia`。

即**目标是用 APFS volume group UUID（或 system volume UUID）指定的**，不是设备节点、不是挂载点。这对我们正好：把目标镜像 `hdiutil attach` 后，它的 volume group UUID 可读，喂进去即可。对 `-setTargetVolume:` 则可以直接给一个 `LPStaticAPFSVolume` 对象（`+[LPStaticMedia mediaForUUID:]`/`mediaForPath:` 产）。

### C.4 它对运行环境的假设（逐条对我们的场景判定）

场景 = `macos-26-intel` runner（`91` 第 1 节：25G76 / x86_64 / SIP 关 / 免密 sudo / Paravirtual GPU，即本身是 VM guest），目标 = 一块 `hdiutil attach` 的镜像、不是本机启动盘。

| 假设 | 成立？ | 依据 |
|---|---|---|
| 必须跑在 macOS 上（要 APFS/MobileAsset/OSPersonalization/DeviceIdentity 等 40 个框架） | **成立** | `KNOWN`，`LC_LOAD_DYLIB`。只能在 runner 上跑，不能在开发机 |
| 要 root | **成立且满足** | `xpc-Info.plist` `_RoleAccount=root`；runner 免密 sudo |
| 要 `UpdateBrainService.sb` 在 main bundle | 仅当走 `_update_brain_service_main` 时 | `KNOWN`（C.1 第 1 步）。我们若绕开入口直接驱动引擎/ObjC，就不触发 self-sandbox |
| 要 XPC entitlement `allow-softwareupdated` / `anchor apple` | 仅当走 XPC 时 | `INFERRED`。不走 XPC 则不适用（`75` 的推断在此被更精确地定位：检查在 event handler，不在 dylib 符号上） |
| 要 `mobileassetd` / MobileAsset | 看是否让它自己下资产 | `KNOWN` 字符串 `mobileassetd`、`Triggering MobileAsset purge`。我们本地已有资产，应走 `clientProvidedTargetUUID` + 本地 package path，尽量不触发下载 |
| 要 `.TrustCache` 被加载 | **不影响 dlopen** | `INFERRED`。`.TrustCache` 是给 XPC service 的代码签名/信任用；dlopen 一个 dylib 到 SIP 关的进程不需要它 |
| 要 NVRAM 可写 | **只有 APPLY 相位要，而且我们禁止它写**（第 E 节） | `KNOWN` |
| 要真实设备身份（ECID/chipID）给 TSS | **仅当 cryptex1/boot 个性化不被跳过时** | `KNOWN` 调用在；`BLOCKED` 跳不跳。VM guest 无 SEP/ECID，这条若触发就是硬墙 |

### C.5 可照抄的调用骨架

因为**唯一导出会把自己变成守护进程**，而 raw-XPC 又过不了 entitlement，所以 R6 只剩两种真正能动手的形态。两者都从同一个 `dlopen` 起步。

**形态 B（首选）：按"基址 + RVA"直接调内部引擎**，替我们跑 Apple 的 PREPARE 相位，跳过 APPLY。

```c
#include <dlfcn.h>
#include <CoreFoundation/CoreFoundation.h>
#include <objc/runtime.h>
#include <objc/message.h>

// 1) dlopen 会注册全部 ObjC 类，并把镜像映射进来
void *h = dlopen("/path/UpdateBrainLibrary.dylib", RTLD_NOW | RTLD_LOCAL);

// 2) 用唯一导出反推 slice 载入基址（UUID 已钉死，RVA 稳定）
void *known = dlsym(h, "update_brain_service_main");   // == base + 0x419b3
uintptr_t base = (uintptr_t)known - 0x419b3;

// 3) 取内部引擎（非导出，故按 RVA 算）。签名见反汇编：
//    _handle_MSUPrepareUpdate_impl(a1, CFDictionaryRef updateAttributes, ...)
typedef long (*prep_impl_fn)(void *a1, CFDictionaryRef attrs,
                             void *a3, long a4, long a5, long a6, long a7);
prep_impl_fn PrepareImpl = (prep_impl_fn)(base + 0x3eaf0);

// 4) 构造 update-attributes（键见 C.2）。clientProvidedTargetUUID 指向我们 attach 的镜像的
//    APFS volume group UUID；package path 指向本地解出的 payloadv2 bundle。
//    注意：完整字典 schema 尚未逆清，见 U-002。
CFMutableDictionaryRef attrs = CFDictionaryCreateMutable(...);
CFDictionarySetValue(attrs, CFSTR("clientProvidedTargetUUID"), targetVGUUID);
// ... 其余键 ...

// 5) 只跑 PREPARE。绝不调 _MSUApplyUpdate_server(base+0x4e0b2) / _prepare_boot_environment。
long rc = PrepareImpl(ctx, attrs, NULL, 0, 0, 0, 0);
```

**形态 A（更可控但要自己编排）：直接驱动 ObjC 对象**，只做我们要的几步，内容拷贝和封印用引擎的 ObjC 面：

```objc
dlopen(".../UpdateBrainLibrary.dylib", RTLD_NOW);   // 注册 ObjC 类

Class TC  = objc_getClass("MSUTargetController");
id tc     = objc_msgSend((id)TC, sel_getUid("sharedController"));

// 指定目标 = 我们 attach 的镜像的 volume group UUID
objc_msgSend(tc, sel_getUid("setSystemTargetWithVolumeGroupUUID:"), targetVGUUID);

NSError *err = nil;
objc_msgSend(tc, sel_getUid("configureTargetVolumeForInstallWithError:"), &err);
// 挂载/准备目标卷（不回滚快照时传 nil）
objc_msgSend(tc, sel_getUid("prepareTargetVolumeForInstallRevertingToSnapshot:error:"), nil, &err);

// —— 把 payloadv2 的 system 内容铺到 [tc targetVolume].mountPoint ——
// 这一步是 C 引擎 _prepare_snapshot 里的 copy_patched_files/copy_archived_files/
// set_hardlinks/verify_postbom（RVA 0x5574e 内），自己编排等于重写它，工作量不小（U-002）。

// 封印：本地 fs_snapshot_create
id vol = objc_msgSend(tc, sel_getUid("targetVolume"));
objc_msgSend(vol, sel_getUid("createSnapshot:error:"),
             CFSTR("com.apple.os.update-MSUPrepareUpdate"), &err);

// Preboot / firmlink：MSUBootObjectCopier + MSUMigrationHelper（见 A.1）
```

两条都**只碰目标卷**，自己 bless 目标（`75` R1/R2 的 `bless --folder <target>/System/Library/CoreServices --bootefi --create-snapshot`），**永不让它 `--setBoot` 本机**。

## D. 封印那一步到底怎么做的

### D.1 封印是本地算的，不联网 `KNOWN`

`_prepare_snapshot`(`0x5574e`) 把资产内容铺到目标卷后，调 `-[LPStaticAPFSVolume createSnapshot:@"com.apple.os.update-MSUPrepareUpdate" error:]`（受 ctx flag bit 0x40 门控）。而 `createSnapshot:error:`(`0x145024`) 的实体是：

```c
int fd = open(volume.mountPoint.fileSystemRepresentation, O_RDONLY);
fs_snapshot_create(fd, snapshotName, 0);     // 就这一条 BSD syscall
close(fd);
```

**封印（SSV 的 Merkle root hash）由 APFS 内核在 `fs_snapshot_create` 时算。** UpdateBrain 不自己算 hash，也不向任何服务器要 hash。这推翻了 `75` 第 0.0 节"封印只有 Apple 能做、疑似联网"的最坏假设。

佐证：`_stage_ota_boot_objects` 里有 `Copied root hash from %s -> %s`、`OS.dmg.root_hash`、`BaseSystem.dmg.root_hash`（RVA `0x292ed7` 一带）——即资产里**预置了 root hash/mtree manifest**，引擎把它铺到位，封印本身靠 syscall。`KNOWN`。

还有跳过开关：`skip-sealing`（RVA `0x2921c0`）、日志 `Skip sealing flag is set. System may not boot after update.`（`0x2918ce`）、`msu_use_boms is set. Skipping pre-sealing.`。即封印可被显式跳过——只要 authenticated-root 已关（我们的 `csr-active-config=0xFEF` 的 bit 11，`75` 第 1.5 节）系统照样能起。`KNOWN`。

### D.2 ARV 开关影响控制流 `KNOWN`

`ARV sealing enabled, do not call APFSContainerResizePrepare`（`0x282c80`）、`APFSContainerResizePrepare is not present`、`Calling APFSContainerResizePrepare for %s and %llu bytes`。读出的逻辑（`INFERRED`）：

- **ARV（Authenticated Root Volume）封印开着**时：**不**调 `APFSContainerResizePrepare`，走快照封印路径（`createSnapshot`）。
- 关着（旧式非封印）时：才去 `APFSContainerResizePrepare` 调整容器。

`ota-arv-mode` 是 update-attributes 的键（C.2）。对 macOS 26 的 SSV，走的是 ARV 路径。

### D.3 cryptex1 个性化：**这一步可能联网，是 R6 的命门** `KNOWN` + `BLOCKED`

在 **PREPARE 相位**（`_MSUPrepareUpdate_server`(`0x4c2f4`) → `_personalize_with_options`（15 字节 thunk）→ `__personalize_with_options`（实体，4453 字节）→ `_personalize_boot_bundle`(`0x27a5f`)）：

- cryptex1 子步的判定（`0x27a5f` 内，line ~552）：**当 splat 启用 且 未 pre-personalized（ctx flag bit 0x400 == 0）** 才 `AMAuthInstallUpdaterCryptex1SetInfo(...)` 配置 cryptex1；否则日志 `Skipping cryptex1 personalization (enabled=%i, personalization=%i, pre-personalized=%i)`。`KNOWN`。
- 核心提交（line 713）：`AMAuthInstallBundlePersonalize(...)`，随后 `_log_compressed_tss_request`。个性化前 `_copy_current_ticket()`，日志 `Carrying EngineeringSyscfgAllowed Entitlement forward into new TSS Request`。`KNOWN`。
- dylib 内有完整 TSS 客户端：`https://gs.apple.com:443/`（`0x2b82fa`）、`queryTatsuSigningServer:ssoOnly:error:`、`composeTSSRequest:`、`TSS Connection attempt %d of %d`、`Server not reachable`。`KNOWN`。
- `writing cryptex1 ticket to %@`（`0x2d2cec`）在 `_ramrod_splat_write_personalized_ticket`(`0x12473c`)：ticket **写到目标**。ticket 的来源正是上面 `AMAuthInstallBundlePersonalize` 的产物。

所以：**正常路径下，cryptex1/boot bundle 个性化会组 TSS 请求发 gs.apple.com，需要联网 + 可被 Apple 签名的设备身份（ECID/chipID，来自 `DeviceIdentity`/`AppleDeviceQuerySupport`）。** 一台 paravirtual VM guest 没有 SEP、没有真 ECID，TSS 不会给它签 Mac ticket；CI 里我们也不会向 Apple 发请求。

**但有逃生门，静态定不死（`BLOCKED`，记 `U-001`）**：

- `_personalize_boot_bundle` 开头：`if (ctx[+12056] != 0)` 就只 `symlink target/boot` 然后成功返回，**完全不进 AuthInstall**。即"无 boot bundle / splat-only / 不需个性化"时整段跳过。
- `Skipping cryptex1 personalization …`、`DoNotPersonalize`、`Verifying global ticket without nonce`（`0x289045`）、`cryptex1 chips unavailable, skipping verification`（`0x2d2a07`）合起来表明：**无协处理器 / 用 global（无 nonce）ticket 时可跳过逐机签名**。
- 历史上非 T2 Intel Mac 的系统安装根本不做 TSS 个性化。x86/VMM 的 Tahoe 是不是也落进"无需个性化"分支，**只有在 runner 上实跑 PREPARE 才知道**。

## E. 对"装到非启动盘"的适配

### E.1 它会改本机 NVRAM、会 `--setBoot`——在 APPLY 相位 `KNOWN`

`_MSUApplyUpdate_server`(`0x4e0b2`) → `_prepare_boot_environment`(`0x852d`) 里（行号为该函数 pseudocode 内）：

- line 1339 `Saving fallback bless info to NVRAM` → `update_brain_create_failback_bless_info()`(`0xbafd`) → `set_bridgeos_failback_info()`。**写 NVRAM**。
- line 1397–1408 `Using bless to boot the SURamDisk`：`bless --folder … --setBoot` → `_run_bless_with_arguments`(`0xc15a`)，后者用 `NSTask` 跑 `/usr/sbin/bless`。**`--setBoot` 改本机固件启动项**。
- line 1367–1382 另一处 `bless --folder`（render volume label，无 `--setBoot`）。

即 UpdateBrain 的正常模型是 iOS 式两相：PREPARE 把系统卷铺好 + 封印 + 个性化；APPLY **把本机下次启动指向 SURamDisk 并写 NVRAM**，重启进 ramdisk 完成 splat。**在 CI runner 上让 APPLY 跑 = 改 runner 自己的引导 = 灾难。**

**规避（`INFERRED`，R6 的核心策略）**：只跑 PREPARE，拿它的产物（铺好内容 + `com.apple.os.update-MSUPrepareUpdate` 封印快照 + Preboot/firmlink），**不调 `_MSUApplyUpdate_server`**；收尾用我们自己的 `bless --folder <目标>/System/Library/CoreServices --bootefi --create-snapshot` 对**目标镜像**做，永不 `--setBoot` 本机。另一道保险：所有外部命令过 `set_partition_execution_function` 设的回调（入口里设成 `msu_execute_command_with_callback`）；形态 A/B 里我们不调入口，就可以不装这个回调，或装我们自己的、把 bless/nvram 变 no-op。

### E.2 会不会动当前启动卷 `KNOWN` + `INFERRED`

PREPARE 写的是 `[MSUTargetController targetVolume]`——由 `clientProvidedTargetUUID` 决定（C.3）。给对目标 UUID，它写目标，不写 `/`。`should_prepare_to_snapshot`(`0x3dc7b`) 还显式护栏：目标 `mountPoint == "/"` 直接报错 1127（`KNOWN`）。所以**只要把目标 UUID 指准，它不碰当前启动卷**；指错了它自己会拒。

### E.3 `seputil` / boot SEP 在 Intel 上 `KNOWN` + `INFERRED`

沙箱白名单含 `/usr/libexec/seputil`（`75` 第 0.0 节）；`MSUBootFirmwareUpdater` 的 `+requiresSEPInFW`(`0x14baec`)、`generateFirmwareImagesWithCallback:context:`、UARP/Ace3/PS190 等都是 SEP/T2/配件固件路径。非 T2 Intel VM guest 无 SEP，这些应当短路不跑（`INFERRED`，`cryptex1 chips unavailable, skipping verification` 支持此判断）。这条与 D.3 的个性化跳过是同一个运行期事实的两面，一起在 runner 上验（`U-001`）。

### E.4 有没有 dry-run / target 模式 `KNOWN`

没有单独的 "dry-run" 开关字符串。但有天然的 **target 模式**：两相拆分本身（PREPARE 只写目标卷、APPLY 才碰本机引导）就是我们要的"装到非启动盘"模式。`clientProvidedTargetUUID` + 只跑 PREPARE = 事实上的 target-only。`SuspendUpdate`/`ResumeUpdate` verb 说明相位之间可挂起，也佐证 PREPARE 产物是自洽的落盘状态。`INFERRED`。

## F. 可行性裁决

**R6 = 条件可行，未证死也未证活；压在一条必须在 runner 上关掉的未知上。** 不含糊地说：

- **封印不是障碍**：本地 `fs_snapshot_create`，不联网（D.1）。`75` 最担心的那条解除。
- **改本机 NVRAM 不是障碍**：它只在 APPLY 相位发生，而 R6 只跑 PREPARE、自己 bless 目标就能完全避开（E.1）。
- **真正的命门是 D.3**：x86/VMM 的 PREPARE 相位会不会**被迫向 `gs.apple.com` 签 cryptex1/boot ticket**。
  - **若会**（像 T2/Apple Silicon 那样逐机 TSS）：**R6 不可行**。VM guest 没有可被 Apple 签名的设备身份，CI 也不该联网签名；这一步失败，PREPARE 整体失败。
  - **若不会**（像非 T2 Intel 那样走"无个性化 / global ticket"分支）：**R6 可行**，能全程离线产出 25G325 的封印系统卷。代码里确实有这条跳过分支，但静态看不出 x86/VMM 落哪边。
- **第二重成本（非阻断）**：没有干净导出。驱动它要么按"基址+RVA"调内部 `_handle_MSUPrepareUpdate_impl`（需逆清 update-attributes 字典 schema，`U-002`），要么自己编排 ObjC（重写 `_prepare_snapshot` 的内容拷贝，工作量更大）。SIP 关掉后机制上都成立，不是硬墙。

**裁决一句话**：先用 runner 实跑一次隔离的 PREPARE（`U-001`），看它到不到 `gs.apple.com`。到了就判 R6 死、回退 `75` 的 R1；没到就判 R6 活、投入 `U-002` 的字典 schema 逆向。**在 `U-001` 关掉之前，R6 既不能排期也不能宣布可行。**

## 未解决项清单

| 编号 | 问题 | 查清方法 | CI 可测 |
|---|---|---|---|
| **U-001** | x86/VMM 的 PREPARE 相位是否联网签 cryptex1/boot ticket（R6 命门） | 在 `macos-26-intel` runner（SIP 关）起一个本地回环抓包 / 防火墙拒绝出站，`dlopen` + 形态 B 调 `_handle_MSUPrepareUpdate_impl` 跑一次 PREPARE，看是否有到 `gs.apple.com:443` 的连接、`AMAuthInstallBundlePersonalize` 是否返回 `TSS_ERR_SERVER_NOT_REACHABLE`。或先只测 `_personalize_boot_bundle` 是否走 `ctx[+12056]` 跳过分支 | **是**（`91` 的 `macos-26-intel`） |
| **U-002** | update-attributes `CFDictionary` 的完整 schema（形态 B 要喂对） | 继续逆 `_create_update_context_with_error`(`0x3209f`) 与 `_handle_MSUPrepareUpdate_impl`(`0x3eaf0`)：把每个 `CFDictionaryGetValue(attrs, CFSTR(...))` 的键、类型、必填性列全；对照一次真实 `softwareupdated` 调 UpdateBrain 的 sysdiagnose 日志 | 部分（静态为主，日志需 runner） |
| **U-003** | AMFI/SIP 关掉后，自建客户端带自签 `allow-softwareupdated` entitlement 能否过 event handler 的入场券检查（决定能否干脆走 raw-XPC 而非按地址调） | runner 上自签一个带该 entitlement 的小客户端，连 `_update_brain_service_main` 起的服务发 `PingService`，看 handler 是否放行 | **是** |
| **U-004** | PREPARE 产的 `com.apple.os.update-MSUPrepareUpdate` 快照是不是**最终可引导的 SSV**，还是只是中间态（最终封印在被跳过的 APPLY/ramdisk 里才定版） | runner 上 PREPARE 完，对目标镜像 `bless --create-snapshot` 后挂起来 `diskutil apfs listSnapshots` + 尝试 `bless --bootefi` 引导校验；或比对快照的 sealed/ARV flag | **是** |
| **U-005** | 只跑 PREPARE 时 `MSUBootObjectCopier`/`MSUMigrationHelper` 是否已把 Preboot（boot.efi、firmlink、Data 模板）铺齐，使目标无需 APPLY 即可引导 | runner 上 PREPARE 后检查目标 Preboot 卷内容与 `75` 第 2.3.2 节 `asr` 产物对比；缺什么就是我们收尾要补的 | **是** |
| **U-006** | 形态 B 按"基址+RVA"调非导出函数，在 arm64e（若将来要）与未来 build 上 RVA 会漂；是否该改用符号化的内部 stub 定位（如扫 `allow-softwareupdated` 派发表反查 handler） | 以派发表 `0x39f960` 为锚，运行期从 verb 字符串反查 handler 指针，避免硬编码 RVA | 否（本机静态可做） |
| **U-007** | `mobileassetd`/MobileAsset 在"本地已有资产 + `clientProvidedTargetUUID`"下是否仍被触发（触发=意外下载/联网） | U-001 的同一次 PREPARE 里一并观察有无 `mobileassetd` 活动与 `/private/var/MobileAsset` 读写 | **是** |
