# macOS Tahoe 26.7.2（25G325）IOGPU、Display 与 IOSurface 注册链

> [!IMPORTANT]
> 2026-10-29 约束修正：所有必需组件必须运行在 macOS guest。
> 无法修改宿主、QEMU、VMM 或宿主 Vulkan。
> 本文是协议证据报告，不是当前实施计划。
> reims-vgpu 只保留为 APV 协议参考和回归样本。
> 当前实施路线见 `..\PROJECT_SPEC.md`。

分析日期：2026-10-29  
目标系统：macOS Tahoe 26.7.2，build 25G325，x86_64 KVM 客体  
结论范围：只读逆向与源码核对；未修改驱动源码或项目内二进制；未构建 Mesa，未运行完整测试。

## 0. 执行结论

1. **系统链条已闭合到内核两端。** `AppleParavirtGPU : IOGPU : IOAccelerator` 提供 accelerator、device user client、队列/资源/事件；`AppleParavirtDisplay : IOMobileFramebufferLegacy` 提供 mode/swap/vblank/cursor/gamma；`AppleParavirtIOSurface` 通过 `IOSurfaceRoot` 注册 mapper，并把 IOSurface 转成 host mapping ID。唯一未取得实现的中段是 `IOMobileFramebufferLegacy` 的 WindowServer 用户客户端 ABI。
2. **`initWithAcceleratorPort:` 的静态合同已闭合。** 25G325 x86_64 Metal.framework 传入 `IOIteratorNext` 返回的 `io_service_t`。`IOAccelDeviceCreateWithAPIProperty` 随后在基类内部打开 type-5 UserClient。精确 encoding 为 `@20@0:8I16`。目标 guest 动态行为仍待 Gate 5 验证。
3. **reims-vgpu 是重要协议参考，不是交付路线。** 它提供 QEMU `apple-gfx-pci`、Option ROM、host 端 APV FIFO、IOSurface 和 display 协议，并在 Linux Vulkan 路径使用 metal2vulkan。其源码与本轮 IDA 地址和结构交叉吻合，可用于核对 APV 行为。当前项目不能依赖这些宿主组件。
4. **“客体无需安装驱动”必须限定。** reims-vgpu 首页概括为使用 macOS 自带 AppleParavirtGPU，并称只有小型 `ReimsVgpu.kext`；但 [reims-util 当前 README 的 kext 章节](https://github.com/steelbrain/reims-util#the-kexts) 明确说 macOS 26.4+ 默认使用 `apv-arm64-port` kext 集，26.7 还可加入视频 kext。25G325 属于 26.7.2，不能把该方案描述成“纯 stock guest、零客体 kext”。
5. **当前实施路线是 guest-only proxy、helper 和 display provider。** reims-vgpu 需要 QEMU 和宿主组件，不能作为交付方案。它只用于核对 APV 协议、结构和行为。

## 1. 方法、证据标签与内存缩减

### 1.1 方法

- 四个内核映像均先复制到 `KIROCREW_SCRATCH` 的彼此隔离子目录；IDA MCP 只打开副本。
- IDA MCP 在首次 IDAPython 前调用了 reference；数据库严格串行打开、关闭；未调用 `save_database`、rename、patch 或等价写操作。
- 两份既有分析文档也只读取 scratch 副本。
- reims-vgpu、reims-util 与 QEMU fork只做网页/源码轻量读取；未 clone、未构建、未执行。
- 主机可用内存从约 1.9 GB 降到约 0.7 GB 后，停止新增子代理和新增 IDA 分析。报告保留已完成的四库 IDA 结果，并跳过未开始的全量 x86 用户态/Framebuffer 逆向。

### 1.2 标签

- **LOCAL**：目标映像中存在本地代码、表、vtable、xref 或直接 store/call。
- **IMPORT/INHERITED**：只看到导入或父类入口。
- **STRING-ONLY**：只有字符串，不能证明实现。
- **INFERENCE**：由多个直接事实重建，尚缺一段可执行调用证据。
- 证据强度：`strong` = 两个独立来源交叉支持；`moderate` = 单一直接来源；`weak` = 无直接来源的推断。

## 2. 项目原件完整性

下表的“前/后”分别在复制前和全部 IDA 数据库关闭后取得。六个输入的大小与 SHA-256 均完全相同。

| 项目原件 | 前大小 | 后大小 | 前/后 SHA-256 | 结果 |
|---|---:|---:|---|---|
| `C:\Users\viola\Documents\KVM MacOS\metal_drivers\com.apple.driver.AppleParavirtGPUIOGPUFamily.i64` | 2,834,133 | 2,834,133 | `DE3F059B18F987BA890F341DA6E63763FCC7D871ECFFF9A5BE6F44A9040B4FDA` | 未变 |
| `C:\Users\viola\Documents\KVM MacOS\metal_drivers\com.apple.driver.AppleParavirtGPUIOGPUFamily` | 405,616 | 405,616 | `9AD1175C60D53B60DF9D6B4836AC4050D3896B5AD6F8BBEC8F022A5485685EF5` | 未变 |
| `C:\Users\viola\Documents\KVM MacOS\metal_drivers\com.apple.iokit.IOGPUFamily` | 670,728 | 670,728 | `1D290CA65F62E1811B7832B95FE55ABD4F8D1891F64DB38026F590DEEDFE521C` | 未变 |
| `C:\Users\viola\Documents\KVM MacOS\metal_drivers\com.apple.iokit.AppleParavirtIOSurface` | 141,088 | 141,088 | `AF3AEB0F358F0B3C14ABED17F29588D6DECDF977C72068EBAD0A56C9263FF0D3` | 未变 |
| `C:\Users\viola\Documents\KVM MacOS\analysis\macos26-metal-user-spi.md` | 307,364 | 307,364 | `38FF75FB28EC182C9B41B20745DBC44AEC512960BB9F2091D47E06CC2094607A` | 未变 |
| `C:\Users\viola\Documents\KVM MacOS\analysis\metal2vulkan-gap-architecture.md` | 36,071 | 36,071 | `9A533A0B0C26E324FFB4E7F619823503B2E2114D7556FB348234A074EAAC2AE8` | 未变 |

### 2.1 被分析副本与 IDA 串行记录

| 顺序 | scratch 副本 | IDA instance | 关闭结果 |
|---:|---|---|---|
| 1 | `C:\Users\viola\.kiro\crew\scratch\runtime-0c169757\macos26-iogpu-f9ac1ea41d0a6be3\01-paravirt-existing-idb\com.apple.driver.AppleParavirtGPUIOGPUFamily.i64` | `63c11f24b454` | `closed=true, final_lease=true` |
| 2 | `C:\Users\viola\.kiro\crew\scratch\runtime-0c169757\macos26-iogpu-f9ac1ea41d0a6be3\02-paravirt-macho\com.apple.driver.AppleParavirtGPUIOGPUFamily` | `d7da0f7b16b0` | `closed=true, final_lease=true` |
| 3 | `C:\Users\viola\.kiro\crew\scratch\runtime-0c169757\macos26-iogpu-f9ac1ea41d0a6be3\03-iogpu-family\com.apple.iokit.IOGPUFamily` | `282e76fd0af5` | `closed=true, final_lease=true` |
| 4 | `C:\Users\viola\.kiro\crew\scratch\runtime-0c169757\macos26-iogpu-f9ac1ea41d0a6be3\04-paravirt-iosurface\com.apple.iokit.AppleParavirtIOSurface` | `b319e83844ed` | `closed=true, final_lease=true` |

完整 IDA 提取记录位于 `C:\Users\viola\.kiro\crew\scratch\runtime-0c169757\macos26-iogpu-f9ac1ea41d0a6be3\ida-evidence.md`。关闭 raw Mach-O 后产生的 `.i64` 只位于相应 scratch 子目录。

## 3. 系统设备注册链

### 3.1 从虚拟 PCI 到 UEFI 显示

reims-vgpu 为 x86_64/Linux 路径提供已经运行的外部实现，可补足本轮内核映像之前的设备层：

1. QEMU `q35` 暴露 PCI `apple-gfx-pci`，Vendor/Device 为 `106b:eeee`，class code `0x030200`。来源：[reims-vgpu README](https://github.com/steelbrain/reims-vgpu#three-pathways) 与 [Option ROM 头文件](https://github.com/steelbrain/reims-vgpu/blob/master/firmware/src/ReimsVgpu.h)。
2. Option ROM 通过 PCI BAR0 控制 EFI display，寄存器为 `0x1200..0x121c`；BAR2 是 EFI framebuffer alias。framebuffer 是 `EfiRuntimeServicesData` common buffer，以 x86 4 KiB 页编号，最大 64 MiB。来源：[Option ROM 实现](https://github.com/steelbrain/reims-vgpu/blob/master/firmware/src/ReimsVgpu.c)。
3. ROM 安装 Graphics Output Protocol，向 boot.efi 提供启动帧缓冲。macOS 内核接管后的 PCI personality、`AppleParavirtGPULoader` 与 provider match 不在本轮四个映像中，仍是 **IMPORT/INFERENCE**。

### 3.2 GPU accelerator 服务

```text
apple-gfx-pci / Apple provider（provider match 未取样）
  -> AppleParavirtGPU::start @ 0xfffffe00084e7fcc
     -> setupAPVLog
     -> setupInterruptsEarly
     -> IOGPU::start @ 0xfffffe00090de384
        -> virtual configureDevice
           -> AppleParavirtGPU::configureDevice @ 0xfffffe00084ea930
              -> setupMMIO
              -> setupVersion
              -> setupMapperService
              -> setupRoot
              -> setupFIFO
        -> IOSurfaceRoot / global comm page
        -> event、device、work-queue namespaces
        -> IOGPUFenceMachine、scheduler、kernel IOGPUTask
     -> setupChannels
     -> setupInterruptsLate
     -> setupDeviceInfo
     -> 为每个 display port 构造、启动、注册 AppleParavirtDisplay
```

直接证据：

- **LOCAL** `AppleParavirtGPU : IOGPU`，对象大小 1,472；metaclass `0xfffffe0007a8e548`，vtable `0xfffffe0007a8e558`。
- **LOCAL** `IOGPU : IOAccelerator`，对象大小 816；metaclass `0xfffffe0007cb4460`，vtable `0xfffffe0007cb4470`。
- **LOCAL** GPU vtable：`start` `0xfffffe00084e7fcc`、`stop` `0xfffffe00084e8ec4`、`configureDevice` `0xfffffe00084ea930`、`newDeviceUserClient` `0xfffffe00084eac50`、`createMemoryForIOSurfaceDeviceCache` `0xfffffe00084eafc8`、`newCommandQueue` `0xfffffe00084ead68`。
- **LOCAL** channel：Root=0；Exec=1、`0x80000` bytes；Object=2、`0x10000`；Memory=3、`0x10000`；per-display channel；可选 Info=12、`0x80000`。虚拟 channel 创建/销毁向 host 发 FIFO `0x30/0x31`，doorbell 在 GPU MMIO `+32`。
- **INHERITED** GPU 与 display 都没有本地 `probe`；分别只导入 `IOService::probe` 与 `IOMobileFramebufferLegacy::probe`。因此 provider matching 的 plist/loader 顺序不能由这四个映像单独证明。

### 3.3 IOGPU device user client

```text
IOServiceOpen/框架连接 type 5（框架侧调用未取样）
  -> IOGPU::newUserClient @ 0xfffffe00090e06b0
  -> virtual AppleParavirtGPU::newDeviceUserClient @ 0xfffffe00084eac50
  -> AppleParavirtDeviceUserClient : IOGPUDeviceUserClient
  -> IOGPUDeviceUserClient::init / attach / start
  -> 映射 APV stamp memory，flags 0x04001001
  -> virtual createDevice -> AppleParavirtDevice
  -> base selectors 0..59 + APV vendor selectors 0x100..0x110
```

- **LOCAL** `IOGPU::newUserClient` 的 type：5=`IOGPUDeviceUserClient`；7=`IOGPUGLDrawableUserClient`；`0x20`=`IOGPUSurfaceMTL`；`0x21`=`IOGPUMemoryInfoUserClient`；其他 type 返回 `0xe00002c2`。
- **LOCAL** `AppleParavirtDeviceUserClient::externalMethod` `0xfffffe00084f9c58` 只处理 `0x100..0x110`，其他 selector 落回 `IOGPUDeviceUserClient::externalMethod` `0xfffffe00090b4b30`。
- **LOCAL** base dispatch 有 60 项；restricted client 把 25、31..38、40..58 改为 `s_restricted`。首版必须确认 connection 是否 restricted，不能只假定所有 selector 可用。

### 3.4 IOSurface mapper 服务

```text
AppleARMIODevice/provider（只在 mapper-device start 中看到 safe-cast）
  -> IOSurfaceParavirtMapperDevice::probe @ 0xfffffe00084fff4c，score=3000
  -> IOSurfaceParavirtMapperDevice::start @ 0xfffffe00084fff5c
     -> map device memory 0
     -> work loop / command gate / interrupt source
     -> mapper ring + descriptor table MMIO
     -> registerService
  -> IOSurfaceParavirtMapperService::probe @ 0xfffffe00085041cc，score=3000
  -> IOSurfaceParavirtMapperService::start @ 0xfffffe00085041dc
     -> safe-cast provider 为 MapperDevice
     -> find IOSurfaceRoot
     -> new IOSurfaceParavirtMapperInterface @ call 0xfffffe000850425c
     -> IOSurfaceRoot::registerMapperInterface（import 0xfffffe000aa917f0）
```

APV GPU 在 `setupMapperService` `0xfffffe00084ea2ec` 等待 `IOSurfaceParavirtMapperService`，存到 GPU `+0x5a8`。该 mapper **没有 user client、externalMethod 或 clientMemoryForType**；它是 kernel-to-kernel service，再通过 MMIO/ring 与 host 通信。

映射调用顺序：

```text
IOGPU::deviceCacheForIOSurface @ 0xfffffe00090e12f8
  -> APV createMemoryForIOSurfaceDeviceCache @ 0xfffffe00084eafc8
  -> AppleParavirtMapperMemory::init @ 0xfffffe00084f6b9c
  -> MapperService::mappingForSurface @ 0xfffffe0008504558
  -> MapperDevice::internalMappingForSurface
  -> IOSurfaceParavirtMapping::prepare @ 0xfffffe00085035ec
  -> getMappingID @ 0xfffffe00085035dc
  -> complete @ 0xfffffe0008503544
```

- mapping ID 为 1..8191；0 保留。
- ring entry 是 16 bytes：`{u32 command, u32 mapping_id, i32 status, u32 reserved}`。
- command 1=map、2=unmap；reims host 源码还证明 3=test。每条完成后更新 read counter，并 raise interrupt 0。来源：[reims IOSurface ring](https://github.com/steelbrain/reims-vgpu/blob/master/crates/reims-vgpu-core/src/iosurface/ring.rs)。
- mapper MMIO：`+0x1000` ring base、`+0x1008` entry count、`+0x1010` descriptor-table base、`+0x1018` guest write counter/doorbell、`+0x1020` host read counter、`+0x1028` offered features、`+0x1030` enabled descriptor form。IDA 与 [reims host 寄存器实现](https://github.com/steelbrain/reims-vgpu/blob/master/crates/reims-vgpu-core/src/iosurface/regs.rs) 完全吻合，证据 `strong`。
- x86_64 的 4 KiB 页只能安全覆盖 8192 个 512-byte first-form descriptor；1024-byte second form只能覆盖 4096 个 ID，因此 reims host 不向 x86 客体提供 second form。ARM64 16 KiB 页可以使用 1024-byte form。不要把本轮 ARM64 映像观察到的 second-form 能力直接抄到 x86 ABI。

### 3.5 Display/WindowServer

```text
AppleParavirtDisplay : IOMobileFramebufferLegacy
  -> start @ 0xfffffe00084deac0
     -> 发布 CursorPlane=1
     -> inherited framebuffer start
  -> start_hardware @ 0xfffffe00084e183c
     -> shared state、timer、work loop、interrupt bits 0x0c
  -> mode set / program_hardware_gated
  -> program_hardware_swap_gated @ 0xfffffe00084e2ffc
     -> IOGPU::deviceCacheForIOSurface
     -> mapper prepare/getMappingID
     -> display FIFO command 8
     -> AppleParavirtDisplayFence + IOGPUFenceMachine
```

关键证据：

- **LOCAL** `AppleParavirtDisplay` metaclass `0xfffffe0007a8c5e8`，vtable `0xfffffe0007a8c5f8`；base 是 **INHERITED** `IOMobileFramebufferLegacy`。
- **LOCAL** display vtable：`start_hardware` `0xfffffe00084e183c`、`swap_begin_gated` `0xfffffe00084e45f0`、`notify_swap_done_gated` `0xfffffe00084e1f98`、`program_hardware_gated` `0xfffffe00084e4420`、gamma get/set `0xfffffe00084e2444/0xfffffe00084e235c`。
- software VBL callback 重新 arm，参数 16；“16 ms”解释合理，但 timer 方法单位及相位未在映像中命名，仍是 **INFERENCE**。
- gamma 是 3×257 项、总计 3,084 bytes；转换成 float 后随 swap 传给 host。
- display command 8 payload 为 40 bytes：`+0 u32 display`、`+4 u32 task`、`+8 u64 mapping_id`、`+16 u64 gamma_gpu_va`、`+24 u64 gamma_length`、`+32 u32 gamma_entry_count`、`+36 u32 checksum`。IDA 曾把 `0x101` 暂释为 flags；[reims display decoder](https://github.com/steelbrain/reims-vgpu/blob/master/crates/reims-vgpu-core/src/fifo/commands/display.rs) 证明它是 257 的 entry count，已据此修正。
- cursor command 4 为 44 bytes，只接受 BGRA、4 bytes/element；mode、sleep、properties、compositor、ICC 分别使用 host command 2/9/10/11/12 等。
- **未解中段**：`IOMobileFramebufferLegacy::newUserClient`、WindowServer 的 method selectors 与从 framebuffer transaction 到 `program_hardware_*` 的精确调用不在输入中。

## 4. `initWithAcceleratorPort:` 到 IOGPU 的连接

### 4.1 直接证据

用户态既有报告证明：

- AMD `-[GFXAAMD_MtlDevice initWithAcceleratorPort:] @ 0x2338a`；`-[GFX10_MtlDevice initWithAcceleratorPort:] @ 0x11692d`。
- Intel `-[MTLIGAccelDevice initWithAcceleratorPort:] @ 0x2e87d`。
- 两边 device 都继承 `_MTLIOAccelDevice`；厂商 command queue/buffer/encoder/resource 同样继承 `_MTLIOAccel*` 类。
- 两个 vendor bundle 内未见可信 C factory；AMD `+[GFXAAMD_MtlDevice registerDevices] @ 0x2126a` 是空函数。设备枚举应由 Metal.framework/IOAccelerator 层完成。
- 内核 `IOGPU::newUserClient @ 0xfffffe00090e06b0` 明确把 type 5 创建为 vendor `AppleParavirtDeviceUserClient`。

### 4.2 最可能的顺序

```text
Metal.framework / IOAccelerator 枚举 IOGPU service
  -> IOServiceOpen(service, task, type=5, &connection)       [INFERENCE]
  -> connection 是 accelerator Mach port / io_connect_t     [INFERENCE]
  -> 厂商 MTL device alloc
  -> -initWithAcceleratorPort:(connection)                  [LOCAL user-side selector]
  -> _MTLIOAccelDevice 建立 base IOGPU selector/trap 封装    [INHERITED]
  -> vendor MTL 类编码资源/对象/command buffers
  -> selectors 0..59 与 APV 0x100..0x110                   [LOCAL kernel dispatch]
```

这条链的两端都已直接证明；缺的是 Metal.framework/IOAccelerator 私有枚举实现和 `_MTLIOAccelDevice` 的方法体。因此不能把 `initWithAcceleratorPort:` 的参数形式写死为某个 C typedef，也不能声称它必然由 type-5 `IOServiceOpen` 的单一步骤直接返回。实现探针应同时记录 service registry ID、connection port name、user-client class 和 device `registryID`，确认四者一致。

reims-vgpu 对路线选择的意义是：它保留 macOS 自带/移植的 AppleParavirt Metal plugin 与 IOGPU 链，host 只实现 Apple guest 观察到的协议，不需要自己重建 `initWithAcceleratorPort:`。

## 5. 清屏、三角形与 WindowServer 首帧

| 里程碑 | 最小必需内核/系统接口 | 不必先做 | 证据 |
|---|---|---|---|
| 纯用户态 IOSurface 清屏 | `IOSurfaceCreate`/lock/base/plane；metal2vulkan-runtime；Vulkan loader+Lavapipe；helper 内 timeline wait；完成后 IOSurface 可见性同步 | IOGPU user client、APV FIFO、display provider、mapper kext | 既有架构报告；`moderate` |
| 经 IOGPU 的清屏 | type-5 connection；base selector 0 config、2 event machine、7 queue、9 或 40 resource、14 shmem、16 notification queue、28 bind queue、29 submit或 trap 0；完成 stamp/fence | shader function与 render pipeline可省，前提是 APV command schema有 clear op | IDA dispatch `strong`；clear packet schema未知 |
| 三角形 | 清屏全部；真实 IOSurface target；APV `0x101 createObject`、`0x104 createFunction`；render pipeline/object；vertex/fragment资源；queue submit；event/fence completion | display provider可省，先 readback | dispatch envelope `strong`；render object/packet schema未知 |
| WindowServer 首帧 | GPU 与 mapper service注册；`AppleParavirtDisplay` framebuffer注册；可枚举 mode；`IOGPUSurfaceMTL`/framebuffer user-client路径；IOSurface resource/cache；mapper command 1；display command 8；display fence；VBL/swap-done | cursor、ICC、非默认 gamma、sleep/wake可后置，但必须返回一致状态 | GPU/mapper/display两端 `strong`；Framebuffer user ABI未知 |

### 5.1 IOGPU 路径的最小闭环

1. type 5 打开 device user client。
2. selector 0 读取 64-byte config，决定所有可变 record 的真实尺寸。
3. selector 2 取得 536-byte event-machine/stamp 信息。
4. selector 7 创建 command queue；输入至少 `0x408` 且必须等于 config 给出的尺寸，输出 16 bytes，首 qword 含 queue ID。
5. selector 14 建立 shared command memory，输出 `{u64 clientAddress, u32 mappedLength, u32 shmemID}`。
6. selector 16 建立 notification queue，输出 `{u64 queueAddress, u32 queueID, u32 pad}`；selector 28 绑定 command queue 与 notification queue。
7. selector 9 创建一般 resource，或 selector 40 用 IOSurface 建立 resource。
8. selector 29 批量提交；要求 `structureInputSize == count * stride`；或 trap 0 提交单个不超过 `0x40` bytes 的 fast record。
9. IOGPU 准备所有 memory、处理 APV command descriptor、kick scheduler、登记 event fence，完成后更新 stamp/notification。

**限制：** 上述是 envelope，不是 APV Metal command stream。clear/draw 的私有 packet 和 shader binary format尚未恢复；直接照 selector 表实现只能打开通道，不能保证画出像素。

### 5.2 WindowServer 首帧闭环

1. WindowServer 打开 framebuffer/display service，取得或创建 scanout IOSurface。
2. IOGPU 为 IOSurface 建 device cache/resource。
3. APV mapper 为 IOSurface 分配 mapping ID，`prepare` 触发 16-byte ring command 1。
4. host 读取 descriptor，建立 host-side surface；写 `IOReturn`，推进 `+0x1020`，raise interrupt 0。
5. `program_hardware_swap_gated` 发 display command 8，40-byte payload 指向 mapping ID。
6. host 解码 command 8 并 present；GPU 内核登记 `AppleParavirtDisplayFence`，event/fence machine 完成后通知 swap done。
7. VBL timer/host interrupt驱动下一帧。

第 1 步的私有 `IOMobileFramebufferLegacy` user ABI 是当前唯一阻断精确复刻的关键缺口。

## 6. 可先用纯用户态 IOSurface 绕开的层

### 6.1 可以绕开

在普通测试进程或受监督 helper 中完成 clear/triangle 时，可暂时绕开：

- `AppleParavirtGPU`、`IOGPUDeviceUserClient` 的私有 selectors/traps；
- APV Root/Exec/Object/Memory FIFO；
- `AppleParavirtIOSurface` host mapper；
- `AppleParavirtDisplay` 与 `IOMobileFramebufferLegacy`；
- WindowServer、mode、VBL、cursor、gamma/ICC。

数据面为真实 IOSurface Mach object；helper 在自身地址空间重新取得 plane base/offset/stride，把 host pointer 导入 Lavapipe，等待 Vulkan timeline 后再完成 IOSurface lock/unlock/seed 与 IPC ACK。raw pointer、Vk handle、Rust runtime handle都不能跨进程。

### 6.2 不能绕开

- 要被 Metal.framework 枚举为系统 GPU，必须有可匹配的 accelerator/service 和相容的 device user client，除非直接复用 AppleParavirt 路径。
- 要被 WindowServer 当系统显示器，必须有 framebuffer/display provider、mode 与 swap completion。
- host/KVM 若需直接消费 guest IOSurface 页，必须有 mapper/guest-memory transport；单纯在 guest helper 写 IOSurface 不能自动让 host 取得页表和 lifetime。
- 真正的 cross-process MTLSharedEvent 尚不能由 metal2vulkan-runtime 的进程内 `SharedEventHandle` 替代。

### 6.3 reims-vgpu host 路线，仅作参考

reims-vgpu 把 metal2vulkan 放在 **Linux host/QEMU 侧**，并复用 guest 中的 Apple Metal plugin、IOGPU 与 display 链。它不是“guest helper + 自定义 KEXT”。host library 通过 QEMU callbacks map/read guest memory、raise interrupt、处理 displays、IOSurface 和 tasks。当前项目无法控制宿主，因此不能采用该架构。其源码只作为 APV 协议和行为回归样本。

## 7. KEXT 是否必需，DriverKit 是否等价

### 7.1 KEXT 结论

- **系统中必须有 kernel graphics implementation。** 本轮直接观察到的 IOGPU、display 与 mapper 都是 kernel Mach-O，且依赖 `IOGPU`、`IOMobileFramebufferLegacy`、`IOSurfaceRoot` 等私有内核家族。
- **guest-only 交付不能依赖 AppleParavirt host device。** 若现有 guest 设备无法满足注册和显示合同，项目必须提供自己的 guest-side accelerator、IOUserClient 和 display provider。AppleParavirt 与 reims-vgpu 只用于协议比对。
- **25G325 的 reims 打包并非零 kext。** [reims-util README](https://github.com/steelbrain/reims-util#the-kexts) 声明：macOS 26 有 Lilu+`ReimsVgpu.kext`；26.4+ 默认还有 `apv-arm64-port` kext 集。应冻结具体 commit 并审计 OpenCore image实际携带内容。
- `ReimsVgpu.kext` 是 Lilu plugin，不实现 IOGPU。其 [实现](https://github.com/steelbrain/reims-util/blob/master/kext/src/ReimsVgpu.cpp) 做四类兼容补丁：
  1. 把 x86 `AppleParavirtAccelerator::setupVersion` 从最高 6 提升到 245，并写入 60-byte guest features；
  2. 把双平面 texture object type 从 2 修成 12；
  3. patch `AppleParavirtGPUMetal` 的 feature profile `10000 -> 10001`；
  4. patch tiled texture bounds 与 swizzled/descriptor2 capability。
- 版本 245 在 [reims feature table](https://github.com/steelbrain/reims-vgpu/blob/master/crates/reims-vgpu-core/src/guest/abi/features.rs) 开启 multiple displays；版本 237/110/100/61/60/31/10 分别带入 descriptor2、swizzle、shared texture、64 FIFO、IOSurface buffer、dual-plane、mapper/display-mapped-surface等能力。

### 7.2 DriverKit

Apple 公开 DriverKit 提供基础 `IOService`、memory、dispatch、`IOUserClient` 与 entitlement 模型，但公开文档没有 `IOGPU`、`IOAccelerator` graphics provider、`IOMobileFramebufferLegacy` 或等价 display family。来源：[Apple DriverKit](https://developer.apple.com/documentation/driverkit)。本轮映像也只显示 kernel IOKit inheritance/import，没有 DriverKit counterpart symbol。

结论：**没有公开 DriverKit 等价 IOGPU/display family 的证据。** DriverKit 不能作为已证明替代；最多把它设为单独 feasibility gate。reims-vgpu 的成功也不是 DriverKit 证据，它依赖 Apple guest graphics stack、QEMU device model、Option ROM 与 kext compatibility/port。

## 8. helper、user client、memory type 与 fence 最小表

### 8.1 如果仍做 guest helper

| IPC 消息 | 最小字段 | 对应 user-client动作 | 约束 |
|---|---|---|---|
| `HELLO` | protocol version、feature bits、client generation | selector 0 config、2 event machine | 先协商可变结构尺寸；拒绝未知版本 |
| `OPEN_DEVICE` | registry ID、audit identity | type-5 connection | 每客户端 namespace；记录 restricted 状态 |
| `IMPORT_SURFACE` | IOSurface Mach right、object ID、plane、format、width/height、stride、seed | selector 40 `create_resource_iosurface`，或纯用户态导入 | 绝不传 raw pointer；验证 overflow/alloc size |
| `CREATE_SHMEM` | size、flags | selector 14 | 返回 helper-local映射与 shmem ID，不跨进程复用地址 |
| `CREATE_QUEUE` | config-sized queue record、priority/QoS | selector 7，16，28 | queue、notification queue成对管理 |
| `CREATE_OBJECT` | typed descriptor、dependent object IDs | APV `0x101`；function 用 `0x104` | APV variable schema尚未恢复；必须版本化 |
| `SUBMIT` | sequence、queue ID、command blob ID/offset/length、resource IDs、waits/signals | selector 29 或 trap 0 | bounded sizes；`count*stride` checked；超时 |
| `COMPLETE` | sequence、status、completed timeline/seed | stamp/notification/fence | ACK 只能在 Vulkan和必要 cache/IOSurface同步后发出 |
| `PRESENT` | surface ID、display ID、wait value、frame sequence | 正常由 WindowServer/display provider完成 | helper 不应伪造 display fence已完成 |
| `DESTROY/CLOSE` | object IDs、generation | delete queue/resource/fence/event | 旧 generation handle全部失效；幂等清理 |

推荐的第一版同步是 helper 内 Vulkan timeline semaphore + IPC sequence ACK。不要把进程内 `SharedEventHandle` 当成跨进程 Mach shared event。

### 8.2 内核/user-client memory contract

| 类别 | 建立接口 | 返回/布局 | 最小用途 | 状态 |
|---|---|---|---|---|
| stamp memory | device-client start内映射 | flags `0x04001001`；numeric `clientMemoryForType` 未知 | event completion | LOCAL，type code未知 |
| device shmem | selector 14 `(SI2, STI0, SO0, STO16)` | `{u64 clientVA,u32 length,u32 shmemID}` | command bytes/records | LOCAL |
| notification queue | selector 16 `(SI2,0,0,16)`；selector 28 `(SI2,0,0,0)` | `{u64 queueVA,u32 queueID,u32 pad}` | async completion | LOCAL |
| standard resource | selector 9 `(0,var,0,var)` | args至少 `0x58`；type 0 | buffer/texture backing | LOCAL |
| resource group | selector 9 | resource type 3 | grouped residency/lifetime | LOCAL；非首清屏必需 |
| virtual/client ranges | selector 9 | types 64/128 | virtual或client ranges | LOCAL；按实际需要 |
| IOSurface resource | selector 40 `(SI3,0,SO1,0)`；内部 type 130 | 返回 resource ID | render target/scanout共享 | LOCAL |
| mapper descriptor | kernel mapper | x86 first form 512 bytes；ID 1..8191 | host取得IOSurface布局/页 | LOCAL + reims交叉验证 |
| mapper ring | MMIO `0x1000..0x1030` | 16-byte map/unmap/test command | guest↔host mapping lifetime | LOCAL + reims交叉验证 |
| EFI framebuffer | Option ROM BAR2 | 4 KiB页、32bpp、≤64 MiB | boot/recovery GOP | reims源码，moderate |

`clientMemoryForType` 的实现和 numeric type codes在四个映像中都不存在；不要虚构。IOGPU 的实用映射主要由 selector 14/16 返回 client VA。

### 8.3 Fence/完成模型

| 层 | 接口 | 值/对象 | 何时算完成 |
|---|---|---|---|
| GPU stamp | selector 2 event-machine record | 536-byte metadata + mapped stamp memory | event machine观察到目标 stamp |
| command completion | selector 16 queue + selector 28 bind | notification queue ID/VA | scheduler处理提交并写通知/stamp |
| MTL fence | selector 21 create `(0,0,0,4)`；22 destroy `(SI1)` | `u32 fenceID` | IOGPUFenceMachine signal |
| MTL event | selector 23 create `(SI1,0,0,24)`；24 destroy `(SI1)` | event ID/metadata | signal/wait value满足 |
| per-submit event fence | command descriptor提交路径 | `IOGPUEventFence` | prepare/process/complete后登记并触发 |
| display fence | `AppleParavirtDisplayFence::init @ 0xfffffe00084e4be4` | retains memory map + optional interrupt source | host display command完成并通知 swap done |
| IOSurface mapping | mapper ring status + interrupt 0 | `IOReturn` in entry `+8` | read counter推进且 status success |
| helper | Vulkan timeline + IPC sequence | 64-bit monotonic value | queue timeline完成、可见性同步、ACK 已发 |

## 9. 下一步实现用“最小 ABI 表”

这是首个 clear/triangle/scanout 所需的窄集合，不包含 IO command、late-eval、resource group、性能计数等无关接口。

| 层 | type/selector/command | ABI | 必要阶段 | 地址/来源 |
|---|---|---|---|---|
| service open | user-client type 5 | APV device user client | IOGPU clear+ | `IOGPU::newUserClient @ 0xfffffe00090e06b0` |
| config | base sel 0 | `(0,0,0,64)` | 全部 IOGPU | `s_get_config @ 0xfffffe00090b1bcc` |
| stamps | base sel 2 | `(0,0,0,536)` | 提交完成 | `s_get_event_machine @ 0xfffffe00090b1d0c` |
| queue | base sel 7 | `(0,var,0,16)` | clear+ | `s_new_command_queue @ 0xfffffe00090b1f90` |
| resource | base sel 9 | `(0,var,0,var)`，args≥`0x58` | clear+ | `s_new_resource @ 0xfffffe00090b2328` |
| shmem | base sel 14 | `(2,0,0,16)` | command data | `s_create_shmem @ 0xfffffe00090b2524` |
| notify queue | base sel 16 | `(2,0,0,16)` | async completion | `s_create_notificationqueue @ 0xfffffe00090b2560` |
| bind notify | base sel 28 | `(2,0,0,0)` | async completion | `s_set_notification_queue @ 0xfffffe00090b2624` |
| batch submit | base sel 29 | `(4,var,1,0)` | clear+ | `s_submit_command_buffers @ 0xfffffe00090b26dc` |
| fast submit | base trap 0 | record≤`0x40` + optional 4-byte status | 单提交优化 | `t_submit_command_buffer @ 0xfffffe00090b3eb4` |
| IOSurface resource | base sel 40 | `(3,0,1,0)` | IOSurface target | `s_create_resource_iosurface @ 0xfffffe00090b2e08` |
| fence | base sel 21/22 | create `(0,0,0,4)`；destroy `(1,0,0,0)` | GPU dependency | `0xfffffe00090b25a4/0xfffffe00090b25b4` |
| event | base sel 23/24 | create `(1,0,0,24)`；destroy `(1,0,0,0)` | wait/signal | `0xfffffe00090b25c8/0xfffffe00090b25e0` |
| APV object | vendor sel `0x101` | `(0,var,1,0)` | triangle | `s_createObject @ 0xfffffe00084f99ec` |
| APV function | vendor sel `0x104` | `(0,var,1,0)` | triangle shader | `s_createFunction @ 0xfffffe00084f9a2c` |
| APV sync | vendor sel `0x110` | `(SI1,0,0,0)` | resource visibility | `s_synchronizeResource @ 0xfffffe00084f9b18` |
| surface client | user-client type `0x20` | `IOGPUSurfaceMTL`，shape selector 9、signal 18 | WindowServer path | `IOGPU::newUserClient` + tables `0xfffffe0007cae398/0xfffffe0007cae728` |
| mapper map/unmap | ring cmd 1/2 | `{cmd,id,status,reserved}`，16 bytes | scanout | mapper MMIO/ring；reims host交叉验证 |
| display shared state | display cmd 1 | 8 bytes | display start | APV call `0xfffffe00084df194` |
| display cursor | display cmd 4 | 44 bytes | 首帧后 | APV call `0xfffffe00084e40b4` |
| display present | display cmd 8 | 40 bytes，mapping ID + optional gamma | WindowServer首帧 | APV call `0xfffffe00084e351c`；reims decoder |
| display mode ACK | display cmd 2 | 8 bytes | mode set | APV `handleHostInterrupt @ 0xfffffe00084de854` |

**仍不能编码的最小 ABI：** APV `createObject/createFunction` variable payload、render-pipeline object schema、IOGPU command-buffer entry schema、clear/draw packet和 `IOMobileFramebufferLegacy` user methods。下一轮应只针对这些缺口，不再枚举无关 selector。

## 10. reims-vgpu 与当前目标的重合

| 当前目标层 | reims-vgpu 现成实现 | 重合判断 |
|---|---|---|
| x86 PCI device | QEMU `apple-gfx-pci`，`106b:eeee`，q35/KVM | 仅作 APV 设备协议参考；当前项目不能要求宿主提供 |
| Option ROM/boot display | UEFI GOP，BAR0 EFI regs，BAR2 framebuffer alias | 覆盖安装器/Recovery/boot framebuffer |
| guest GPU driver | AppleParavirt guest stack；26.7.2 默认还需 reims-util 的 compatibility/port kext集 | 复用私有 IOGPU/display ABI，而非重写 |
| guest/host GPU protocol | MMIO、Root/Exec/Object/Memory/Info/display FIFO、task/resource/object语义 | 与 IDA 的 channel/command evidence重合 |
| IOSurface mapper | descriptor table、mapping ring、map/unmap、guest-memory callbacks | MMIO与16-byte ring完全吻合 |
| display | mode、mapped-surface present、gamma、cursor、window callbacks | display command 8/4 等与 IDA吻合 |
| Vulkan | Linux host通过 metal2vulkan，GPU memory经 `/dev/udmabuf` | 正是既有目标的 Metal→Vulkan方向，但位置在host |
| helper隔离 | guest task 0外可在host进程内独立线程执行；不是guest IPC helper | 可减少guest组件；崩溃域仍需按项目模型评估 |
| 测试 | behavior-lock suite固定 guest/host可观察契约 | 可作为 ABI regression oracle，优先复用 |

重要差异：reims-vgpu 的产品结构是“Apple guest driver → QEMU/reims host library → Metal 或 Vulkan”，当前结构是“guest Objective-C proxy → guest helper/Lavapipe → IOSurface”。两者不得混成一条链。前者只能作为 APV 协议参考，不能进入 guest-only 交付图。

## 11. 未解项与下一步判定门

1. `IOMobileFramebufferLegacy` 的 probe/newUserClient、WindowServer method selectors 与 transaction调用链未取样。
2. Metal.framework/IOAccelerator 如何枚举 service、构造 accelerator port并调用 vendor `initWithAcceleratorPort:` 尚无直接反编译证据。
3. APV `createObject/createFunction` variable structures、render pipeline与 clear/draw command bytes尚未恢复。
4. 25G325 上 reims-util 实际打包的 `apv-arm64-port` kext清单、哈希、来源与加载顺序尚未对一个生成的 OpenCore image做独立核验；reims-vgpu首页“one small kext”与 reims-util 的 26.4+说明存在粒度冲突。
5. reims README 要求 x86 guest 设置 `METAL_ERROR_MODE=5` 才能避免 icon service导致桌面缺失；这说明当前路径仍有 Metal行为差异，不能把“截图可运行”等同于完整兼容。
6. 公开 DriverKit没有等价 graphics family；第三方签名、entitlement、SIP/boot policy仍未解决。
7. 本轮四个二进制是 ARM64 kernel images；x86 4 KiB page、ported kext与用户态 AppleParavirtGPUMetal的精确 25G325 ABI需用对应副本另行核实。
8. 主机内存降到约 0.7 GB 后停止了新增 IDA与全量逆向；未执行 Mesa、QEMU、OpenCore或 VM 验证。

### 建议的下一步

按当前 guest-only Gate 执行：先在目标 guest 验证 Vulkan loader 和 Lavapipe，再完成真实 IOSurface clear、metallib triangle 和 helper 隔离。只有 Gate 4 通过后，才继续关闭 B-008、B-009、B-010 和 B-012，并实现 Metal.framework 与 WindowServer 注册。reims-vgpu 不进入构建，只保留协议测试向量。

## 12. 外部依据

- [reims-vgpu README](https://github.com/steelbrain/reims-vgpu)
- [reims-vgpu host C/Rust API](https://github.com/steelbrain/reims-vgpu/blob/master/docs/api.md)
- [reims-vgpu architecture](https://github.com/steelbrain/reims-vgpu/blob/master/docs/architecture.md)
- [QEMU apple-gfx device](https://github.com/steelbrain/qemu-reims-vgpu/blob/steelbrain/reims-vgpu/hw/display/apple-gfx.c)
- [Option ROM PCI/BAR definitions](https://github.com/steelbrain/reims-vgpu/blob/master/firmware/src/ReimsVgpu.h)
- [Option ROM GOP implementation](https://github.com/steelbrain/reims-vgpu/blob/master/firmware/src/ReimsVgpu.c)
- [reims guest feature/version table](https://github.com/steelbrain/reims-vgpu/blob/master/crates/reims-vgpu-core/src/guest/abi/features.rs)
- [reims display command decoder](https://github.com/steelbrain/reims-vgpu/blob/master/crates/reims-vgpu-core/src/fifo/commands/display.rs)
- [reims IOSurface mapper registers](https://github.com/steelbrain/reims-vgpu/blob/master/crates/reims-vgpu-core/src/iosurface/regs.rs)
- [reims IOSurface mapper ring](https://github.com/steelbrain/reims-vgpu/blob/master/crates/reims-vgpu-core/src/iosurface/ring.rs)
- [reims-util kext packaging](https://github.com/steelbrain/reims-util#the-kexts)
- [ReimsVgpu.kext source](https://github.com/steelbrain/reims-util/blob/master/kext/src/ReimsVgpu.cpp)
- [ReimsVgpu.kext Info.plist](https://github.com/steelbrain/reims-util/blob/master/kext/src/Info.plist)
- [Apple DriverKit](https://developer.apple.com/documentation/driverkit)
