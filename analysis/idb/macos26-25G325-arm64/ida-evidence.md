# IDA evidence: macOS 26 paravirtual GPU, IOGPU, display, and IOSurface path

## Scope and method

This is binary-evidence extraction, not the final project report. Only the four requested scratch copies were opened, in the requested order, with one IDA database open at a time. Analysis used IDA/IDAPython read APIs only. No names, types, comments, or bytes were changed; `save_database`, rename, patch, and other mutation APIs were not called. Closing scratch databases was allowed to perform IDA's normal scratch-IDB save.

Evidence labels used below:

- **LOCAL IMPLEMENTATION**: code, data, symbol, vtable, xref, or call site present in the named image.
- **INHERITED/IMPORT**: an undefined/imported symbol or behavior reached through a base-class vtable.
- **STRING-ONLY**: text exists, but no implementing routine or full ABI was proved from it alone.
- **INFERENCE**: a reconstruction from multiple local facts; the supporting facts are stated.

All four images are ARM64 kernel Mach-O images. Local authenticated/rebased function pointers in class vtables and dispatch tables consistently resolve by taking the encoded low 32 bits and adding image bias `0xfffffe0007004000`; resolved targets were checked against IDA function names. The raw pointer-auth bits are retained where useful below.

## Database open/close ledger

| # | Requested scratch input | IDA instance | Open | Close | Scratch IDB reported on close |
|---|---|---:|---|---|---|
| 1 | `C:\Users\viola\.kiro\crew\scratch\runtime-0c169757\macos26-iogpu-f9ac1ea41d0a6be3\01-paravirt-existing-idb\com.apple.driver.AppleParavirtGPUIOGPUFamily.i64` | `63c11f24b454` | success | `closed: true`, `final_lease: true` | same `.i64` path |
| 2 | `C:\Users\viola\.kiro\crew\scratch\runtime-0c169757\macos26-iogpu-f9ac1ea41d0a6be3\02-paravirt-macho\com.apple.driver.AppleParavirtGPUIOGPUFamily` | `d7da0f7b16b0` | success | `closed: true`, `final_lease: true` | `C:\Users\viola\.kiro\crew\scratch\runtime-0c169757\macos26-iogpu-f9ac1ea41d0a6be3\02-paravirt-macho\com.apple.driver.AppleParavirtGPUIOGPUFamily.i64` |
| 3 | `C:\Users\viola\.kiro\crew\scratch\runtime-0c169757\macos26-iogpu-f9ac1ea41d0a6be3\03-iogpu-family\com.apple.iokit.IOGPUFamily` | `282e76fd0af5` | success | `closed: true`, `final_lease: true` | `C:\Users\viola\.kiro\crew\scratch\runtime-0c169757\macos26-iogpu-f9ac1ea41d0a6be3\03-iogpu-family\com.apple.iokit.IOGPUFamily.i64` |
| 4 | `C:\Users\viola\.kiro\crew\scratch\runtime-0c169757\macos26-iogpu-f9ac1ea41d0a6be3\04-paravirt-iosurface\com.apple.iokit.AppleParavirtIOSurface` | `b319e83844ed` | success | `closed: true`, `final_lease: true` | `C:\Users\viola\.kiro\crew\scratch\runtime-0c169757\macos26-iogpu-f9ac1ea41d0a6be3\04-paravirt-iosurface\com.apple.iokit.AppleParavirtIOSurface.i64` |

The pre-existing IDB's internal `db.path` metadata named an original input under `C:\Users\viola\Documents\KVM MacOS`; the actual MCP open and close targets were the scratch `.i64` above. No tool operation opened, closed, or wrote the metadata-named original path. **LOCAL IMPLEMENTATION / scope fact**.

---

## 1. AppleParavirtGPUIOGPUFamily, existing IDB

### Image and symbols

- **LOCAL IMPLEMENTATION**: ARM64, 64-bit; base `0xfffffe00073071c0`, IDA range `0xfffffe00073071c0..0xfffffe000aa92e98`.
- **LOCAL IMPLEMENTATION**: 941 functions, 2,773 names, 609 strings, 807 imports in one dynamic import module.
- **LOCAL IMPLEMENTATION**: code is `__text` at `0xfffffe00084dd540..0xfffffe00084fd778`; undefined imports occupy `0xfffffe000aa91560..0xfffffe000aa92e98`.
- **LOCAL IMPLEMENTATION**: `_kmod_info` is exported at `0xfffffe000aa90ff0`; module start/stop are `_start` `0xfffffe00084fbcf0` and `_stop` `0xfffffe00084fbd14`.
- **INHERITED/IMPORT**: key undefined symbols include `IOGPU::newUserClient` `0xfffffe000aa92350`, `IOUserClient::clientMemoryForType` `0xfffffe000aa91820`, `IOMobileFramebufferLegacy::probe` `0xfffffe000aa922c0`, `IOMobileFramebufferLegacy::newUserClient` `0xfffffe000aa92028`, `IOSurfaceParavirtMapperService::mappingForSurface` `0xfffffe000aa922f8`, `IOSurfaceParavirtMapping::prepare` `0xfffffe000aa91fb8`, and `IOSurfaceParavirtMapping::complete` `0xfffffe000aa91fc0`.

### Class/metaclass hierarchy

Every row is proved by the local `OSMetaClass` constructor call. The `meta` and `vtable` addresses are exported entries. **LOCAL IMPLEMENTATION**, with the named base marked **INHERITED/IMPORT** unless it is another local APV class.

| Class | `metaClass` | vtable | Direct base | Object size |
|---|---:|---:|---|---:|
| `AppleParavirtDisplay` | `0xfffffe0007a8c5e8` | `0xfffffe0007a8c5f8` | `IOMobileFramebufferLegacy` | 10,984 |
| `AppleParavirtDisplayFence` | `0xfffffe0007a8d5e8` | `0xfffffe0007a8d5f8` | `IOGPUEventFence` | 224 |
| `AppleParavirtEventMachine` | `0xfffffe0007a8d9b8` | `0xfffffe0007a8d9c8` | `IOGPUEventMachine` | 5,200 |
| `AppleParavirtChannel` | `0xfffffe0007a8dc70` | `0xfffffe0007a8dc80` | `IOGPUChannel` | 80 |
| `AppleParavirtRootChannel` | `0xfffffe0007a8df60` | `0xfffffe0007a8df70` | `AppleParavirtChannel` | 80 |
| `AppleParavirtVirtualChannel` | `0xfffffe0007a8e250` | `0xfffffe0007a8e260` | `AppleParavirtChannel` | 160 |
| `AppleParavirtGPU` | `0xfffffe0007a8e548` | `0xfffffe0007a8e558` | `IOGPU` | 1,472 |
| `AppleParavirtCommandDescriptor` | `0xfffffe0007a8f0a0` | `0xfffffe0007a8f0b0` | `IOGPUCommandDescriptor` | 344 |
| `AppleParavirtDevice` | `0xfffffe0007a8f358` | `0xfffffe0007a8f368` | `IOGPUDevice` | 368 |
| `AppleParavirtWorkQueue` | `0xfffffe0007a8f630` | `0xfffffe0007a8f640` | `IOGPUWorkQueue` | 256 |
| `AppleParavirtSegmentResourceList` | `0xfffffe0007a8f8f0` | `0xfffffe0007a8f900` | `IOGPUSegmentResourceList` | 56 |
| `AppleParavirtPageTable` | `0xfffffe0007a8fb60` | `0xfffffe0007a8fb70` | `OSObject` | 32 |
| `AppleParavirtMemoryMap` | `0xfffffe0007a8fe68` | `0xfffffe0007a8fe78` | `IOGPUMemoryMap` | 104 |
| `AppleParavirtSysMemory` | `0xfffffe0007a90158` | `0xfffffe0007a90168` | `IOGPUSysMemory` | 216 |
| `AppleParavirtTask` | `0xfffffe0007a90448` | `0xfffffe0007a90458` | `IOGPUTask` | 600 |
| `AppleParavirtKernelTask` | `0xfffffe0007a90700` | `0xfffffe0007a90710` | `AppleParavirtTask` | 600 |
| `AppleParavirtResource` | `0xfffffe0007a909b8` | `0xfffffe0007a909c8` | `IOGPUResource` | 264 |
| `AppleParavirtMapperMemory` | `0xfffffe0007a90cb0` | `0xfffffe0007a90cc0` | `IOGPUMemory` | 136 |
| `AppleParavirtMapperMemoryMap` | `0xfffffe0007a90fa8` | `0xfffffe0007a90fb8` | `AppleParavirtMemoryMap` | 104 |
| `AppleParavirtCommandQueue` | `0xfffffe0007a91298` | `0xfffffe0007a912a8` | `IOGPUCommandQueue` | 1,464 |
| `AppleParavirtDeviceUserClient` | `0xfffffe0007a915d0` | `0xfffffe0007a915e0` | `IOGPUDeviceUserClient` | 304 |
| `AppleParavirtResourceHeapHandle` | `0xfffffe0007a922d0` | `0xfffffe0007a922e0` | `IOGPUObject` | 32 |
| `AppleParavirtResourceHeap` | `0xfffffe0007a92540` | `0xfffffe0007a92550` | `IOGPUObject` | 184 |

### Vtable evidence

The following are raw vtable qword indices, including the two Itanium prefix qwords. **LOCAL IMPLEMENTATION**.

- `AppleParavirtGPU` vtable `0xfffffe0007a8e558`: slot 192/entry `0xfffffe0007a8eb58` -> `start` `0xfffffe00084e7fcc`; 193 -> `stop` `0xfffffe00084e8ec4`; 276 -> `getStampMemory` `0xfffffe00084e94c4`; 280 -> `newEventMachine` `0xfffffe00084e94d8`; 291 -> `scrubEvents` `0xfffffe00084eb418`; 295 -> `createUserGPUTask` `0xfffffe00084e9510`; 301 -> `configureDevice` `0xfffffe00084ea930`; 302 -> `teardownDevice` `0xfffffe00084eaa7c`; 303 -> `createKernelGPUTask` `0xfffffe00084e95dc`; 304 -> `newDevice` `0xfffffe00084eac18`; 305 -> `newDeviceUserClient` `0xfffffe00084eac50`; 307 -> `newSysMemory` `0xfffffe00084eac88`; 309 -> `newResource` `0xfffffe00084eacf8`; 310 -> `newCommandDescriptor` `0xfffffe00084ead30`; 312 -> `newMemoryMap` `0xfffffe00084eacc0`; 313 -> `createMemoryForIOSurfaceDeviceCache` `0xfffffe00084eafc8`; 316 -> `restart` `0xfffffe00084ea7a4`; 318 -> `newCommandQueue` `0xfffffe00084ead68`.
- `AppleParavirtDisplay` vtable `0xfffffe0007a8c5f8`: slot 192 -> `start` `0xfffffe00084deac0`; 193 -> `stop` `0xfffffe00084deb48`; 307/308 -> `get_gamma_table`/`set_gamma_table` at `0xfffffe00084e2444`/`0xfffffe00084e235c`; 403 -> `start_hardware` `0xfffffe00084e183c`; 404 -> `stop_hardware_gated` `0xfffffe00084e1c7c`; 405 -> `swap_begin_gated` `0xfffffe00084e45f0`; 454 -> `notify_swap_done_gated` `0xfffffe00084e1f98`; 475 -> `program_hardware_gated` `0xfffffe00084e4420`.
- `AppleParavirtDeviceUserClient` vtable `0xfffffe0007a915e0`: slot 274/entry `0xfffffe0007a91e70` -> `externalMethod` `0xfffffe00084f9c58`; slot 307/entry `0xfffffe0007a91f78` -> `getTargetAndTrapForIndex` `0xfffffe00084f9cac`.
- `AppleParavirtCommandQueue` vtable `0xfffffe0007a912a8`: slot 46 -> `processSegmentKernelCommand` `0xfffffe00084f7be4`; slot 47 -> `processCommandBuffer` `0xfffffe00084f7644`; slot 50 -> `parseSegmentList` `0xfffffe00084f76a0`; slot 53 -> `init` `0xfffffe00084f7578`.
- `AppleParavirtMapperMemory` vtable `0xfffffe0007a90cc0`: slot 47 -> `setPurgeable` `0xfffffe00084f6d6c`; 51/52 -> `wire`/`unwire` `0xfffffe00084f6cbc`/`0xfffffe00084f6d24`; 54 -> `createGPUMappingInTaskAtAddressLengthAlignment` `0xfffffe00084f6d94`; 58 -> mapper-specific `init` `0xfffffe00084f6b9c`.
- `AppleParavirtMapperMemoryMap` vtable `0xfffffe0007a90fb8`: slot 48/49 -> GPU VA allocate/reserve `0xfffffe00084f7008`/`0xfffffe00084f7018`; 52/54 -> commit/release page table `0xfffffe00084f6fa0`/`0xfffffe00084f6fac`.

### Probe, start, stop, and user-client creation

- **INHERITED/IMPORT**: no local `AppleParavirtGPU::probe`; `IOService::probe` is imported at `0xfffffe000aa92938`. `AppleParavirtDisplay` likewise imports `IOMobileFramebufferLegacy::probe` at `0xfffffe000aa922c0`.
- **LOCAL IMPLEMENTATION**: `AppleParavirtGPU::start` `0xfffffe00084e7fcc` calls `setupAPVLog` at call site `0xfffffe00084e7ff0`, `setupInterruptsEarly` at `0xfffffe00084e80e0`, inherited `IOGPU::start` through base vtable slot 192, `setupChannels` at `0xfffffe00084e811c`, `setupInterruptsLate` at `0xfffffe00084e8128`, and `setupDeviceInfo` at `0xfffffe00084e8134`. It constructs each `AppleParavirtDisplay` at call site `0xfffffe00084e8188` and starts/registers it through virtual calls.
- **LOCAL IMPLEMENTATION**: `configureDevice` `0xfffffe00084ea930` calls `setupMMIO` `0xfffffe00084ea94c`, `setupVersion` `0xfffffe00084ea958`, `setupMapperService` `0xfffffe00084ea964`, `setupRoot` `0xfffffe00084ea970`, then `setupFIFO` `0xfffffe00084ea97c`; it clamps `DisplayPortCount` to 1..8.
- **LOCAL IMPLEMENTATION**: `AppleParavirtGPU::stop` `0xfffffe00084e8ec4` releases channels, queues, displays, interrupt sources, mapper service, FIFO/MMIO objects, then calls inherited `IOGPU::stop` when the base-start flag is set.
- **INHERITED/IMPORT**: no local `newUserClient`; `IOGPU::newUserClient` is imported at `0xfffffe000aa92350`. The local factory override `AppleParavirtGPU::newDeviceUserClient` `0xfffffe00084eac50` allocates `AppleParavirtDeviceUserClient`, and base `IOGPU::newUserClient` invokes that virtual factory for user-client type 5.
- **INHERITED/IMPORT**: `clientMemoryForType` is not locally implemented; only `IOUserClient::clientMemoryForType` at `0xfffffe000aa91820` is imported.

### APV vendor externalMethod ABI

`AppleParavirtDeviceUserClient::externalMethod` at `0xfffffe00084f9c58` subtracts `0x100`, selects a 24-byte entry only when the relative selector is below 17, and otherwise falls through to `IOGPUDeviceUserClient::externalMethod` through base vtable slot 274. The table xref is `0xfffffe00084f9c64` -> `kVendorDeviceMethods` `0xfffffe0007a920a8`. **LOCAL IMPLEMENTATION**.

`SI`/`SO` are scalar counts; `STI`/`STO` are structure byte sizes. `0xffffffff` means variable size.

| Selector | Table entry | Handler | SI | STI | SO | STO | Class |
|---:|---:|---|---:|---:|---:|---:|---|
| `0x100` | `0xfffffe0007a920a8` | `s_createMemorylessTexture` `0xfffffe00084f99d0` | 0 | var | 1 | 0 | LOCAL IMPLEMENTATION |
| `0x101` | `0xfffffe0007a920c0` | `s_createObject` `0xfffffe00084f99ec` | 0 | var | 1 | 0 | LOCAL IMPLEMENTATION |
| `0x102` | `0xfffffe0007a920d8` | `s_deleteMemorylessTexture` `0xfffffe00084f9a08` | 0 | 8 | 0 | 0 | LOCAL IMPLEMENTATION |
| `0x103` | `0xfffffe0007a920f0` | `s_deleteObject` `0xfffffe00084f9a18` | 0 | var | 0 | 0 | LOCAL IMPLEMENTATION |
| `0x104` | `0xfffffe0007a92108` | `s_createFunction` `0xfffffe00084f9a2c` | 0 | var | 1 | 0 | LOCAL IMPLEMENTATION |
| `0x105` | `0xfffffe0007a92120` | `s_addChildResource` `0xfffffe00084f9a48` | 0 | var | 0 | 0 | LOCAL IMPLEMENTATION |
| `0x106` | `0xfffffe0007a92138` | `s_removeChildResource` `0xfffffe00084f9a5c` | 0 | 8 | 0 | 0 | LOCAL IMPLEMENTATION |
| `0x107` | `0xfffffe0007a92150` | `s_setupDirtyRing` `0xfffffe00084f9a6c` | 0 | 0 | 0 | 24 | LOCAL IMPLEMENTATION |
| `0x108` | `0xfffffe0007a92168` | `s_flushDirtyRing` `0xfffffe00084f9a84` | 0 | 0 | 0 | 0 | LOCAL IMPLEMENTATION |
| `0x109` | `0xfffffe0007a92180` | `s_getDeviceInfo` `0xfffffe00084f9a90` | 0 | 0 | 0 | 284 | LOCAL IMPLEMENTATION |
| `0x10a` | `0xfffffe0007a92198` | `s_createComputePipeline` `0xfffffe00084f9aa0` | 0 | var | 1 | 0 | LOCAL IMPLEMENTATION |
| `0x10b` | `0xfffffe0007a921b0` | `s_addHeapBuffer` `0xfffffe00084f9abc` | 0 | 24 | 0 | 0 | LOCAL IMPLEMENTATION |
| `0x10c` | `0xfffffe0007a921c8` | `s_heapTextureSizeAndAlign` `0xfffffe00084f9acc` | 0 | var | 0 | 0 | LOCAL IMPLEMENTATION |
| `0x10d` | `0xfffffe0007a921e0` | `s_resetRasterizationRateMap` `0xfffffe00084f9ae0` | 0 | var | 0 | 0 | LOCAL IMPLEMENTATION |
| `0x10e` | `0xfffffe0007a921f8` | `s_sendDelay` `0xfffffe00084f9af4` | 0 | 12 | 0 | 0 | LOCAL IMPLEMENTATION; returns unsupported `0xe00002c7` |
| `0x10f` | `0xfffffe0007a92210` | `s_commandQueueSetInfoChannelAndQueue` `0xfffffe00084f9b04` | 1 | 0 | 0 | 0 | LOCAL IMPLEMENTATION |
| `0x110` | `0xfffffe0007a92228` | `s_synchronizeResource` `0xfffffe00084f9b18` | 1 | 0 | 0 | 0 | LOCAL IMPLEMENTATION |

The wrappers dereference the base device pointer at user-client offset `+0x120` (288) and call the corresponding `AppleParavirtDevice` routines. **LOCAL IMPLEMENTATION**.

`getTargetAndTrapForIndex` `0xfffffe00084f9cac` accepts selectors `0x100..0x105`, xref `0xfffffe00084f9cc4` -> six 24-byte records at `kVendorDeviceTraps` `0xfffffe0007a92240`; the function pointer is the middle qword and the other two qwords are zero. **LOCAL IMPLEMENTATION**.

| Selector | Trap handler |
|---:|---|
| `0x100` | `t_removeChildResource` `0xfffffe00084f9b2c` |
| `0x101` | `t_setupDirtyRing` `0xfffffe00084f9b58` |
| `0x102` | `t_flushDirtyRing` `0xfffffe00084f9c04` |
| `0x103` | `t_addHeapBuffer` `0xfffffe00084f9c10` |
| `0x104` | `t_commandQueueSetInfoChannelAndQueue` `0xfffffe00084f9c40` |
| `0x105` | `t_synchronizeResource` `0xfffffe00084f9c4c` |

### Channels, queues, resources, and events

- **LOCAL IMPLEMENTATION**: `setupChannels` `0xfffffe00084e8490` creates `ROOT` channel 0, then virtual channels `Exec` 1 with `0x80000` bytes, `Object` 2 with `0x10000`, `Memory` 3 with `0x10000`, per-display channels, and optional `Info` channel 12 with `0x80000`.
- **LOCAL IMPLEMENTATION**: it creates work queues with depths 128 for Exec, 1,024 for Object, and 128 for Info. `AppleParavirtWorkQueue::init` is `0xfffffe00084eeb8c`.
- **LOCAL IMPLEMENTATION**: `AppleParavirtVirtualChannel::init` `0xfffffe00084e6964` allocates channel bytes plus `0x4000`, writes 16-KiB page numbers, and submits FIFO command `0x30` with a 4-byte channel index at call site `0xfffffe00084e6d54`; `free` sends command `0x31` at `0xfffffe00084e6e6c`.
- **LOCAL IMPLEMENTATION**: `submitBufferLocked` `0xfffffe00084e6f7c` copies descriptor bytes into a wrapping ring, sleeps in 10-microsecond increments while full (`IOSleepMicros` call `0xfffffe00084e7108`), updates the producer value, and writes the channel doorbell through GPU MMIO offset 32.
- **LOCAL IMPLEMENTATION**: `AppleParavirtEventMachine::signalStamps` `0xfffffe00084e5680` maps stamp bits 0/1/2/3/12 to Root/Exec/Object/Memory/Info channels and invokes each channel notification method; remaining bits are matched against display channels.
- **LOCAL IMPLEMENTATION**: `AppleParavirtResource::map` `0xfffffe00084f6158` creates/uses an `AppleParavirtMemoryMap` and calls `AppleParavirtMemoryMap::addResource` at `0xfffffe00084f61a8`. `synchronize` `0xfffffe00084f6218` emits FIFO command `0x35` and submits it on the Memory channel at call site `0xfffffe00084f63a8`.
- **LOCAL IMPLEMENTATION**: `AppleParavirtCommandQueue::processSegmentKernelCommand` `0xfffffe00084f7be4` translates generic IOGPU kernel commands to APV FIFO IDs including `0x37`, `0x43`, and `0x45`; exact user-space Metal packet schemas remain unknown.

### AppleParavirtDisplay: mode, swap, vblank, fence, cursor, and gamma

- **LOCAL IMPLEMENTATION**: `AppleParavirtDisplay::init` `0xfffffe00084de0d4` stores the `AppleParavirtGPU`, kernel GPU task ID, display index, display channel, two interrupt event sources, and initial 3x257 gamma ramps. The class starts/stops at `0xfffffe00084deac0`/`0xfffffe00084deb48`; start publishes `CursorPlane=1` and calls the inherited framebuffer start.
- **LOCAL IMPLEMENTATION**: `start_hardware` `0xfffffe00084e183c` runs a work-loop block. The block at `0xfffffe00084e18fc` calls `setupSharedState`, creates a timer event source, registers it on the work loop, enables power/display state, sets shared-state interrupt bits `0x0c`, and signals the process interrupt source.
- **LOCAL IMPLEMENTATION plus INFERENCE**: string `"Failed to create VBL timer"` is at `0xfffffe000730acc3`. Timer callback block `0xfffffe00084e1bdc` invokes object-vtable byte offset `0xc98`, which resolves through the APV display vtable to raw slot 405, `swap_begin_gated` `0xfffffe00084e45f0`. That routine re-arms the timer through timer-vtable offset `0x1f0` with argument 16. A 16-ms software-vblank cadence is the likely meaning, but the imported timer method's unit and phase are not named in this image.
- **LOCAL IMPLEMENTATION**: `handleHostInterrupt` `0xfffffe00084de854` atomically consumes shared bits. Bit 4 recreates display attributes and emits FIFO command 2 with an 8-byte payload `{displayIndex, sharedStateValue}`; bit 8 destroys attributes.
- **LOCAL IMPLEMENTATION**: `set_digital_out_mode` `0xfffffe00084df354` searches timing/color elements. Its block `0xfffffe00084df420` updates `DisplayWidth`, `DisplayHeight`, and `DPTimingModeId` from the selected timing object.
- **LOCAL IMPLEMENTATION**: `set_gamma_table`/`get_gamma_table` are `0xfffffe00084e235c`/`0xfffffe00084e2444`; each copies exactly 3,084 bytes. `prepareGammaTable` `0xfffffe00084e2514` converts 3 x 257 unsigned entries to floats using scale `1/1024`, maps the 3,084-byte result into the GPU task, and returns a checksum plus map.
- **LOCAL IMPLEMENTATION**: `program_hardware_gated` `0xfffffe00084e4420` dispatches cursor and surface updates from the current framebuffer transaction; `swap_begin_gated` is `0xfffffe00084e45f0`.
- **LOCAL IMPLEMENTATION**: `program_hardware_swap_gated` `0xfffffe00084e2ffc` calls IOGPU `deviceCacheForIOSurface` at exact call site `0xfffffe00084e3050` -> target `0xfffffe00090e12f8`, prepares the returned map, safe-casts its memory to `AppleParavirtMapperMemory`, and calls `getMappingID` at `0xfffffe00084e30bc`.
- **LOCAL IMPLEMENTATION**: the swap path emits FIFO command `0x0a` at call site `0xfffffe00084e3198`. It appends an 8-byte pair `{displayIndex, 1}`, another 8-byte constant `{0, 12}` copied from `0xfffffe0007307900`, and a 48-byte color matrix, then submits at `0xfffffe00084e34fc`.
- **LOCAL IMPLEMENTATION**: it then emits FIFO command 8 at `0xfffffe00084e351c`, requests a 40-byte payload at `0xfffffe00084e352c`, and submits it at `0xfffffe00084e3660`. Exact writes are: `+0` display index (`u32`), `+4` kernel GPU task ID (`u32`), `+8` IOSurface paravirt mapping ID (`u64`), `+16` gamma-map GPU VA (`u64`, zero when absent), `+24` gamma-map length (`u64`, zero when absent), `+32` flags `0x101` when gamma is attached, and `+36` gamma checksum (`u32`). Field meanings follow the producers and are therefore **INFERENCE backed by LOCAL IMPLEMENTATION**; widths/offsets/constants are direct stores.
- **LOCAL IMPLEMENTATION**: swap submission creates `AppleParavirtDisplayFence` objects at call sites `0xfffffe00084e36c4` and `0xfffffe00084e3744`, merges their event records into the GPU event machine, and registers them with the IOGPU fence machine. `AppleParavirtDisplayFence::init` `0xfffffe00084e4be4` first invokes inherited `IOGPUEventFence` initialization and retains an `IOGPUMemoryMap` plus optional `IOInterruptEventSource`.
- **LOCAL IMPLEMENTATION**: `program_hardware_cursor_gated` `0xfffffe00084e3a10` requires IOSurface pixel format `0x42475241` (`'BGRA'`) and 4 bytes per element. It builds FIFO command 4 at `0xfffffe00084e40b4`; typed helper `getCommandBytes<APVCmdDisplayCursorGlyph>` `0xfffffe00084e4334` proves a 44-byte payload. Stores are: display index `+0`, GPU task ID `+4`, GPU VA `+8`, mapping length `+16`, row bytes `+24`, width/height `u16` at `+32/+34`, hotspot `u16` at `+36/+38`, and checksum `u32` at `+40`.
- **LOCAL IMPLEMENTATION**: other display command IDs proved at call sites are 1 (`setupSharedState`, `0xfffffe00084df194`), 2 (`handleHostInterrupt`, `0xfffffe00084de8c0`), 9 (power state, `0xfffffe00084e398c`), `0x0b` (`setParameter`, `0xfffffe00084e4ae0`), and `0x0c` (guest ICC profile, `0xfffffe00084e2d30`). Their symbolic host protocol names are not present.

### APV-side IOSurface mapper bridge

- **LOCAL IMPLEMENTATION**: `setupMapperService` `0xfffffe00084ea2ec` matches service string `IOSurfaceParavirtMapperService`, waits indefinitely, safe-casts to that metaclass, and stores it at GPU offset `+0x5a8` (qword 181).
- **LOCAL IMPLEMENTATION**: `AppleParavirtGPU::createMemoryForIOSurfaceDeviceCache` `0xfffffe00084eafc8` uses `AppleParavirtMapperMemory` unless IOSurface creation properties contain `APVSharedTexture`; otherwise it calls the inherited IOGPU implementation.
- **LOCAL IMPLEMENTATION with cross-binary target**: `AppleParavirtMapperMemory::init` `0xfffffe00084f6b9c` calls `IOSurfaceParavirtMapperService::mappingForSurface` at `0xfffffe0008504558` and stores the returned wrapper. `wire` `0xfffffe00084f6cbc` calls `IOSurfaceParavirtMapping::prepare` at `0xfffffe00085035ec`; `unwire` `0xfffffe00084f6d24` calls `complete` at `0xfffffe0008503544`; `getMappingID` `0xfffffe00084f6f58` tail-calls `0xfffffe00085035dc`.

---

## 2. AppleParavirtGPUIOGPUFamily, raw Mach-O

- **LOCAL IMPLEMENTATION**: the raw Mach-O opened independently as ARM64/64-bit with the same base/range, 16 segment ranges, 941 functions, 2,773 names, 609 strings, and 807 imports as database 1.
- **LOCAL IMPLEMENTATION**: key symbol addresses independently reproduced exactly: `AppleParavirtDisplay` vtable `0xfffffe0007a8c5f8`, `AppleParavirtGPU` vtable `0xfffffe0007a8e558`, `AppleParavirtDeviceUserClient` vtable `0xfffffe0007a915e0`, vendor method table `0xfffffe0007a920a8`, vendor trap table `0xfffffe0007a92240`, `AppleParavirtGPU::start` `0xfffffe00084e7fcc`, display swap `0xfffffe00084e2ffc`, and vendor `externalMethod` `0xfffffe00084f9c58`.
- **LOCAL IMPLEMENTATION**: metaclass constructors independently reproduced `AppleParavirtGPU : IOGPU` size 1,472, `AppleParavirtDisplay : IOMobileFramebufferLegacy` size 10,984, and `AppleParavirtDeviceUserClient : IOGPUDeviceUserClient` size 304.
- **LOCAL IMPLEMENTATION**: all 17 vendor dispatch entries reproduced the same handlers and SI/STI/SO/STO values listed in database 1. Xrefs independently reproduced as `0xfffffe00084f9c64` -> method table and `0xfffffe00084f9cc4` -> trap table.
- **LOCAL IMPLEMENTATION**: selected vtable slots independently reproduced: GPU slots 192/193/305/318; display slots 192/193/403/404/405/454/475; user-client slots 274/307.
- **LOCAL IMPLEMENTATION**: display FIFO command call sites independently reproduced IDs 1, 2, 4, 8, 9, `0x0a`, `0x0b`, and `0x0c` at the addresses listed above.
- **INFERENCE**: matching layout, counts, addresses, tables, vtable targets, and call-site immediates show that the existing IDB and raw Mach-O represent the same linked image. No claim of a whole-file byte hash is made.

---

## 3. IOGPUFamily

### Image, hierarchy, exports, and vtables

- **LOCAL IMPLEMENTATION**: ARM64/64-bit; base `0xfffffe000755e1d0`, range `0xfffffe000755e1d0..0xfffffe000aac8f58`; 2,206 functions, 4,541 names, 1,028 strings, and 673 imports.
- **LOCAL IMPLEMENTATION**: `__text` is `0xfffffe00090a9c80..0xfffffe00090f0818`; undefined imports begin at `0xfffffe000aac7a50`.

Key local metaclass evidence:

| Class | `metaClass` / vtable | Direct base | Size | Class |
|---|---|---|---:|---|
| `IOGPU` | `0xfffffe0007cb4460` / `0xfffffe0007cb4470` | `IOAccelerator` | 816 | LOCAL IMPLEMENTATION; base imported |
| `IOGPUDeviceUserClient` | `0xfffffe0007cabd68` / `0xfffffe0007cabd78` | `IOUserClient` | 304 | LOCAL IMPLEMENTATION; base imported |
| `IOGPUDevice` | `0xfffffe0007cb29b0` / `0xfffffe0007cb29c0` | `IOGPUObject` | 288 | LOCAL IMPLEMENTATION |
| `IOGPUCommandQueue` | `0xfffffe0007cb4f98` / `0xfffffe0007cb4fa8` | `IOGPUObject` | 1,432 | LOCAL IMPLEMENTATION |
| `IOGPUResource` | `0xfffffe0007cb0f28` / `0xfffffe0007cb0f38` | `IOGPUObject` | 160 | LOCAL IMPLEMENTATION |
| `IOGPUMemory` | `0xfffffe0007ca9ba8` / `0xfffffe0007ca9bb8` | `IOGPUObject` | 128 | LOCAL IMPLEMENTATION |
| `IOGPUMemoryMap` | `0xfffffe0007cb6048` / `0xfffffe0007cb6058` | `IOGPUObject` | 72 | LOCAL IMPLEMENTATION |
| `IOGPUSysMemory` | `0xfffffe0007cb65b0` / `0xfffffe0007cb65c0` | `IOGPUMemory` | 216 | LOCAL IMPLEMENTATION |
| `IOGPUEventMachine` | `0xfffffe0007cae9b0` / `0xfffffe0007cae9c0` | `OSObject` | 5,200 | LOCAL IMPLEMENTATION |
| `IOGPUEventFence` | `0xfffffe0007cafd78` / `0xfffffe0007cafd88` | `OSObject` | 208 | LOCAL IMPLEMENTATION |
| `IOGPUWorkQueue` | `0xfffffe0007cb1c10` / `0xfffffe0007cb1c20` | `IOGPUObject` | 256 | LOCAL IMPLEMENTATION |
| `IOGPUCommandDescriptor` | `0xfffffe0007cb3290` / `0xfffffe0007cb32a0` | `IOGPUObject` | 304 | LOCAL IMPLEMENTATION |
| `IOGPUTask` | `0xfffffe0007cb41c8` / `0xfffffe0007cb41d8` | `IOGPUObject` | 464 | LOCAL IMPLEMENTATION |
| `IOGPUSurfaceMTL` | `0xfffffe0007cad8a0` / `0xfffffe0007cad8b0` | `IOUserClient` | 768 | LOCAL IMPLEMENTATION; base imported |
| `IOGPUGLDrawableUserClient` | `0xfffffe0007cab260` / `0xfffffe0007cab270` | `IOUserClient` | 1,576 | LOCAL IMPLEMENTATION; base imported |
| `IOGPUDeviceShmem` | `0xfffffe0007cb0c88` / `0xfffffe0007cb0c98` | `IOGPUKernelMappedMemory` | 104 | LOCAL IMPLEMENTATION |
| `IOGPUNotificationQueue` | `0xfffffe0007cb68a0` / `0xfffffe0007cb68b0` | `IOGPUObject` | 48 | LOCAL IMPLEMENTATION |

Selected raw vtable indices, all **LOCAL IMPLEMENTATION**:

- `IOGPU`: 192 `start` `0xfffffe00090de384`; 193 `stop` `0xfffffe00090dfa8c`; 247 `newUserClient` `0xfffffe00090e06b0`; 279 `createEventMachine` `0xfffffe00090e0bac`; 283 `createDevice` `0xfffffe00090e102c`; 284 `createSysMemory` `0xfffffe00090e0c60`; 286/287 `createMemoryMap` `0xfffffe00090e0de4`/`0xfffffe00090e0eb0`; 288 `createResource` `0xfffffe00090e10f4`; 304 `newDevice` `0xfffffe00090e0a04`; 305 `newDeviceUserClient` `0xfffffe00090e0a3c`; 318 `newCommandQueue` `0xfffffe00090e0ff4`.
- `IOGPUDeviceUserClient`: 192/193 start/stop `0xfffffe00090b1800`/`0xfffffe00090b49f0`; 274 `externalMethod` `0xfffffe00090b4b30`; 294 `clientClose` `0xfffffe00090b4ab4`; 307 trap selection `0xfffffe00090b4be8`; 308/309 device-client start/stop `0xfffffe00090b4708`/`0xfffffe00090b4944`.
- `IOGPUCommandQueue`: 47 `processCommandBuffer` `0xfffffe00090e428c`; 53 `init` `0xfffffe00090e30cc`; 61 `submitCommandBuffer` `0xfffffe00090e6288`.
- `IOGPUResource`: 42 `init` `0xfffffe00090bfb18`; 43 `initialize` `0xfffffe00090c2230`; 49/50 map overloads `0xfffffe00090c2f1c`/`0xfffffe00090c2d8c`; 56 `unmap` `0xfffffe00090c2f54`.
- `IOGPUMemoryMap`: 42/43 init overloads `0xfffffe00090eb904`/`0xfffffe00090eb93c`; 53/55 commit/release `0xfffffe00090ec33c`/`0xfffffe00090ec370`.

### Probe/start/stop and creation chain

- **INHERITED/IMPORT**: there is no local service `probe` for `IOGPU`; `IOService::probe` is imported at `0xfffffe000aac8958`.
- **LOCAL IMPLEMENTATION**: `IOGPU::start` `0xfffffe00090de384` calls the vendor virtual `configureDevice`, finds `IOSurfaceRoot`, initializes the global comm page, creates event/device/work-queue namespaces, statistics, a work loop, `IOGPUFenceMachine`, event-scrubber thread, scheduler, and kernel `IOGPUTask`; failures call `IOGPU::stop`.
- **LOCAL IMPLEMENTATION**: `IOGPU::stop` `0xfffffe00090dfa8c` finishes all stamps, releases scheduler/scrubber/fence machine, unmaps kernel mappings, removes the kernel task from its namespace, calls the vendor `teardownDevice`, then `IOAccelerator::stop`.
- **LOCAL IMPLEMENTATION**: `IOGPU::newUserClient` `0xfffffe00090e06b0` accepts low-16-bit type 5 -> virtual `newDeviceUserClient`; 7 -> `IOGPUGLDrawableUserClient`; `0x20` -> `IOGPUSurfaceMTL`; `0x21` -> `IOGPUMemoryInfoUserClient`; other types return `0xe00002c2`.
- **LOCAL IMPLEMENTATION plus APV virtual override**: type 5 calls APV's `newDeviceUserClient` and `IOGPUDeviceUserClient::init` at call site `0xfffffe00090e081c`, attaches and starts it. `deviceUserClientStart` `0xfffffe00090b4708` invokes vendor `getStampMemory` through method offset `0x890`, maps it into the task with flags `0x04001001`, calls virtual `createDevice` through offset `0x8c8`, sets the restricted-client byte at `+0x103`, and returns success.

### Base device externalMethod dispatch

`IOGPUDeviceUserClient::externalMethod` `0xfffffe00090b4b30` requires started byte `+0x100`; selectors `0..59` reject non-null `asyncReference`, select normal table `0xfffffe0007cac840` or restricted table `0xfffffe0007cacde0` using byte `+0x103`, and tail-call `IOUserClient::externalMethod`. Xrefs are `0xfffffe00090b4b7c` and `0xfffffe00090b4b60`. **LOCAL IMPLEMENTATION**.

Normal 24-byte dispatch entries:

| Sel | Handler (address) | SI | STI | SO | STO |
|---:|---|---:|---:|---:|---:|
| 0 | `s_get_config` `0xfffffe00090b1bcc` | 0 | 0 | 0 | 64 |
| 1 | `s_get_name` `0xfffffe00090b1cdc` | 0 | 0 | 0 | 64 |
| 2 | `s_get_event_machine` `0xfffffe00090b1d0c` | 0 | 0 | 0 | 536 |
| 3 | `s_get_surface_info` `0xfffffe00090b1dec` | 0 | 0 | 0 | 16 |
| 4 | `s_get_current_trace_filter` `0xfffffe00090b1e04` | 0 | 0 | 0 | 8 |
| 5 | `s_get_device_info` `0xfffffe00090b1e34` | 0 | 0 | 0 | 32 |
| 6 | `s_get_next_gid_group` `0xfffffe00090b1f30` | 0 | 0 | 0 | 16 |
| 7 | `s_new_command_queue` `0xfffffe00090b1f90` | 0 | var | 0 | 16 |
| 8 | `s_delete_command_queue` `0xfffffe00090b2298` | 1 | 0 | 0 | 0 |
| 9 | `s_new_resource` `0xfffffe00090b2328` | 0 | var | 0 | var |
| 10 | `s_delete_resource` `0xfffffe00090b24d8` | 1 | 0 | 0 | 0 |
| 11 | `s_finish_object_event` `0xfffffe00090b24ec` | 2 | 0 | 0 | 0 |
| 12 | `s_set_resource_purgeable` `0xfffffe00090b2504` | 2 | 0 | 1 | 0 |
| 13 | `NULL` | 0 | 0 | 0 | 0 |
| 14 | `s_create_shmem` `0xfffffe00090b2524` | 2 | 0 | 0 | 16 |
| 15 | `s_destroy_shmem` `0xfffffe00090b254c` | 1 | 0 | 0 | 0 |
| 16 | `s_create_notificationqueue` `0xfffffe00090b2560` | 2 | 0 | 0 | 16 |
| 17 | `s_destroy_notificationqueue` `0xfffffe00090b2580` | 1 | 0 | 0 | 0 |
| 18 | `s_get_shared_info` `0xfffffe00090b2594` | 0 | 0 | 0 | 8 |
| 19-20 | `NULL` | 0 | 0 | 0 | 0 |
| 21 | `s_create_mtlfence` `0xfffffe00090b25a4` | 0 | 0 | 0 | 4 |
| 22 | `s_destroy_mtlfence` `0xfffffe00090b25b4` | 1 | 0 | 0 | 0 |
| 23 | `s_create_mtlevent` `0xfffffe00090b25c8` | 1 | 0 | 0 | 24 |
| 24 | `s_destroy_mtlevent` `0xfffffe00090b25e0` | 1 | 0 | 0 | 0 |
| 25 | `s_get_memory_data` `0xfffffe00090b25f4` | 0 | 0 | 0 | 48 |
| 26 | `s_unsupported` `0xfffffe00090b2604` | 0 | 0 | 0 | var |
| 27 | `s_get_allocated_size` `0xfffffe00090b2614` | 0 | 0 | 1 | 0 |
| 28 | `s_set_notification_queue` `0xfffffe00090b2624` | 2 | 0 | 0 | 0 |
| 29 | `s_submit_command_buffers` `0xfffffe00090b26dc` | 4 | var | 1 | 0 |
| 30 | `s_set_priority_and_background` `0xfffffe00090b2994` | 1 | 12 | 1 | 0 |
| 31 | `s_set_quality_of_service` `0xfffffe00090b2a38` | 1 | 4 | 0 | 0 |
| 32 | `s_create_mtllateevalevent` `0xfffffe00090b2ad8` | 0 | 0 | 2 | 0 |
| 33 | `s_destroy_mtllateevalevent` `0xfffffe00090b2b14` | 1 | 0 | 0 | 0 |
| 34 | `s_async_signal_mtlLateEvalevent` `0xfffffe00090b2b54` | 2 | 0 | 0 | 0 |
| 35 | `s_query_mtlLateEvalevent` `0xfffffe00090b2c28` | 1 | 0 | 2 | 0 |
| 36 | `s_set_display_params_for_gpu` `0xfffffe00090b2d04` | 2 | 0 | 0 | 0 |
| 37 | `s_set_app_gpu_role` `0xfffffe00090b2d40` | 2 | 0 | 0 | 0 |
| 38 | `s_get_app_gpu_role` `0xfffffe00090b2d84` | 1 | 0 | 1 | 0 |
| 39 | `s_set_resource_owner_identity` `0xfffffe00090b2df0` | 2 | 0 | 0 | 0 |
| 40 | `s_create_resource_iosurface` `0xfffffe00090b2e08` | 3 | 0 | 1 | 0 |
| 41 | `s_resource_detach_backing` `0xfffffe00090b2ea0` | 1 | 0 | 0 | 0 |
| 42 | `s_resource_replace_backing_bytes` `0xfffffe00090b2eb4` | 0 | 24 | 0 | 0 |
| 43 | `s_resource_replace_backing_ranges` `0xfffffe00090b2ec4` | 0 | 24 | 1 | 0 |
| 44 | `s_create_vniodesc` `0xfffffe00090b2f10` | 1 | 0 | 2 | 0 |
| 45 | `s_destroy_vniodesc` `0xfffffe00090b3040` | 1 | 0 | 0 | 0 |
| 46 | `s_create_io_command_queue` `0xfffffe00090b3068` | 2 | 0 | 2 | 0 |
| 47 | `s_destroy_io_command_queue` `0xfffffe00090b3250` | 1 | 0 | 0 | 0 |
| 48 | `s_set_io_notification_queue` `0xfffffe00090b32d0` | 2 | 0 | 0 | 0 |
| 49 | `s_submit_io_commands` `0xfffffe00090b341c` | 1 | var | 0 | 0 |
| 50 | `s_create_io_command_buffer` `0xfffffe00090b36b0` | 1 | 0 | 2 | 0 |
| 51 | `s_destroy_io_command_buffer` `0xfffffe00090b3768` | 2 | 0 | 0 | 0 |
| 52 | `s_try_cancel_io_command_buffer` `0xfffffe00090b3820` | 2 | 0 | 0 | 0 |
| 53 | `s_perform_io` `0xfffffe00090b38d8` | 1 | 0 | 0 | 0 |
| 54 | `s_io_command_buffer_complete` `0xfffffe00090b397c` | 1 | 0 | 0 | 0 |
| 55 | `s_io_command_buffer_barrier_complete` `0xfffffe00090b3a1c` | 3 | 0 | 0 | 0 |
| 56 | `s_group_add_resources` `0xfffffe00090b3ad8` | 2 | var | 0 | 0 |
| 57 | `s_group_remove_resources` `0xfffffe00090b3c90` | 2 | var | 0 | 0 |
| 58 | `s_create_device_assertion` `0xfffffe00090b3e48` | 2 | 0 | 1 | 0 |
| 59 | `s_perform_mapping` `0xfffffe00090b3e98` | 0 | 0 | 0 | 0 |

All rows are **LOCAL IMPLEMENTATION**. In the restricted table, selectors 25, 31-38, and 40-58 point to `s_restricted` `0xfffffe00090b3ea4`; selectors 0-24, 26-30, 39, and 59 retain their normal targets. Null selectors remain null.

`getTargetAndTrapForIndex` `0xfffffe00090b4be8` accepts traps 0..13. The normal table `0xfffffe0007cad380` maps them to `t_submit_command_buffer`, `t_delete_resource`, `t_finish_resource_event`, `t_set_resource_purgeable`, group add/remove/update, queue group assignment, display params, shared-event signal/wait, MTL-event signal/wait, and background-role check at `0xfffffe00090b3eb4..0xfffffe00090b4654`. The restricted table `0xfffffe0007cad4d0` replaces traps 4-7 with `t_restricted` `0xfffffe00090b46f8`; the rest are unchanged. Table xrefs are `0xfffffe00090b4c20` and `0xfffffe00090b4c04`. **LOCAL IMPLEMENTATION**.

### Memory exposure and mappings

- **INHERITED/IMPORT**: this image has no local `clientMemoryForType`; `IOUserClient::clientMemoryForType` is imported at `0xfffffe000aac7c48`, with no direct local xref. No IOGPU class in this image overrides it.
- **LOCAL IMPLEMENTATION**: the practical device memory ABI is method-based. Selector 14 calls `IOGPUDevice::create_shmem` `0xfffffe00090d2a90`; output bytes are `{u64 clientAddress, u32 mappedLength, u32 namespaceID}`. Call sites `0xfffffe00090d2b38`/`0xfffffe00090d2b44` obtain client data and the client map.
- **LOCAL IMPLEMENTATION**: `IOGPUDeviceShmem::init` `0xfffffe00090bf514` creates an `IOMemoryDescriptor`, maps it into the owning task, stores the map at object `+0x48`, and exposes its address through `getClientData` `0xfffffe00090bf748`.
- **LOCAL IMPLEMENTATION**: selector 16 creates a notification queue and returns `{u64 queueAddress, u32 queueID, u32 padding}`; selector 28 binds command-queue ID and notification-queue ID.
- **LOCAL IMPLEMENTATION**: `IOGPUMemoryMap` stores GPU VA at `+0x28`; `allocGPUVirtualAddress` `0xfffffe00090ebbf4` reserves via `IOGPUTask`, adds the map to `IOGPUMemory`, and unwinds on failure. `prepareMapping`/`completeMapping` `0xfffffe00090ebdb8`/`0xfffffe00090ebdc4` call `IOGPUMemory::prepareMemory`/`completeMemory`.

### Queue/resource/event minimum mechanics

- **LOCAL IMPLEMENTATION**: selector 7 validates a variable input of at least `0x408` bytes and exact configured size, creates the vendor queue through a virtual factory, initializes it, inserts it in the device namespace, and returns a 16-byte record whose first qword contains queue ID.
- **LOCAL IMPLEMENTATION**: selector 9 requires resource arguments of at least `0x58` bytes and a config-sized return record. `IOGPUDevice::new_resource` `0xfffffe00090d3be0` handles resource types 0 (standard), 3 (resource group), 64 (virtual), 128 (client-buffer/ranges), and 130 (IOSurface).
- **LOCAL IMPLEMENTATION**: resource return stores include GPU VA/type at `+0`, client backing address at `+8`, shared addresses from `+16`, flags at `+32`, resource namespace ID at `+36`, resident size at `+40`, allocation IDs/addresses through `+80`, and optional driver data after `+88`. Semantic names beyond those proved by called accessors are **INFERENCE**.
- **LOCAL IMPLEMENTATION**: selector 29 takes four scalar inputs, variable structure input, and one scalar output. It reads queue ID at scalar block `+0`, element count at `+16`, stride at `+24`, checks `structureInputSize == count * stride`, checks stride against GPU config, then calls `IOGPUCommandQueue::submit_command_buffers` at call site `0xfffffe00090b2878`.
- **LOCAL IMPLEMENTATION**: batched submit `0xfffffe00090e37ac` checks thread submission permission, iterates entries by configured stride, resolves referenced device shmem, calls per-buffer submission `0xfffffe00090e3ab8`, flushes/kicks the scheduler, and returns a submission-status scalar.
- **LOCAL IMPLEMENTATION**: the fast trap 0, `t_submit_command_buffer` `0xfffffe00090b3eb4`, takes queue ID plus at most `0x40` bytes copied from a user pointer, submits one record, and optionally copies back a 4-byte status.
- **LOCAL IMPLEMENTATION**: `IOGPUCommandDescriptor::prepare` `0xfffffe00090daf3c` prepares every retained `IOGPUMemory`; `complete` `0xfffffe00090db244` completes each one. This brackets GPU access to all command resources.
- **LOCAL IMPLEMENTATION**: per-buffer submission copies/merges event records, invokes virtual queue processing, kicks the scheduler, and registers event fences. Exact call sites include `IOGPUEventMachine::copyEvent` `0xfffffe00090e3b7c`, scheduler kick `0xfffffe00090e3bd4`, and `IOGPUFenceMachine::addEventFence` `0xfffffe00090e3c70`.
- **LOCAL IMPLEMENTATION**: `IOGPUEventFence::init` `0xfffffe00090bc214` initializes two event records at call sites `0xfffffe00090bc25c` and `0xfffffe00090bc264`. `IOGPUFenceMachine::addEventFence` `0xfffffe00090bdd28` tests/enqueues the fence and kicks completion if already signaled.
- **LOCAL IMPLEMENTATION**: selector 40 creates an IOSurface resource from three scalars and returns its resource ID. `IOGPUResource::newResourceWithIOSurface` `0xfffffe00090c127c` obtains an `IOSurfaceDeviceCache` through call `0xfffffe00090c12d8` -> `IOGPU::deviceCacheForIOSurface` `0xfffffe00090e12f8`.

### Ancillary drawable/surface user clients

- **LOCAL IMPLEMENTATION**: `IOGPUGLDrawableUserClient::externalMethod` `0xfffffe00090b0564` uses six 24-byte dispatches at `0xfffffe0007cab1d0`: set surface `(SI0, STI48)`, set surface/get status `(SI0, STI48, STO40)`, swap rect `(SI4)`, swap interval `(SI2)`, signal shared event `(SI3)`, and create Mach port from IOSurface `(SI1, SO1)`. Table xref: `0xfffffe00090b0578`.
- **LOCAL IMPLEMENTATION**: `IOGPUSurfaceMTL` user-client type `0x20` has a 19-entry legacy 48-byte table at `0xfffffe0007cae398`; xref `0xfffffe00090b5f20`. Handlers cover read/write lock/unlock, state, ID/mode, scale, shape, flush, control, and related legacy operations. Selectors 6 and 17 are handled directly by `set_shape_backing_length_ext`; selector 9 uses new-style dispatch `0xfffffe0007cae728` -> `s_set_shape` `(SI2, STI variable)`; selector 18 uses `sSignalEventDispatch` `0xfffffe0007cae380` -> `s_signal_shared_event` `(SI3)`.

---

## 4. AppleParavirtIOSurface

### Image, hierarchy, exports, and vtables

- **LOCAL IMPLEMENTATION**: ARM64/64-bit; base `0xfffffe000730d3a0`, range `0xfffffe000730d3a0..0xfffffe000aa922e0`; 182 functions, 901 names, 229 strings, and 380 imports.
- **LOCAL IMPLEMENTATION**: `__text` is `0xfffffe00084fd780..0xfffffe0008504cc0`.

| Class | `metaClass` / vtable | Direct base | Size | Class |
|---|---|---|---:|---|
| `IOSurfaceParavirtMappingInternal` | `0xfffffe0007a93720` / `0xfffffe0007a93730` | `OSObject` | 152 | LOCAL IMPLEMENTATION |
| `IOSurfaceParavirtMapperDevice` | `0xfffffe0007a93998` / `0xfffffe0007a939a8` | `IOService` | 432 | LOCAL IMPLEMENTATION; base imported |
| `IOSurfaceParavirtMapping` | `0xfffffe0007a94428` / `0xfffffe0007a94438` | `OSObject` | 32 | LOCAL IMPLEMENTATION |
| `IOSurfaceParavirtMapperInterface` | `0xfffffe0007a94698` / `0xfffffe0007a946a8` | `IOSurfaceRootParavirtMapperInterface` | 24 | LOCAL IMPLEMENTATION; base imported |
| `IOSurfaceParavirtMapperService` | `0xfffffe0007a94910` / `0xfffffe0007a94920` | `IOService` | 152 | LOCAL IMPLEMENTATION; base imported |

Selected vtable entries, **LOCAL IMPLEMENTATION**:

- `IOSurfaceParavirtMapperDevice`: slot 191 `probe` `0xfffffe00084fff4c`, 192 `start` `0xfffffe00084fff5c`, 193 `stop` `0xfffffe0008500848`.
- `IOSurfaceParavirtMapperService`: slot 191 `probe` `0xfffffe00085041cc`, 192 `start` `0xfffffe00085041dc`, 193 `stop` `0xfffffe0008504454`, 274 `createMapping` `0xfffffe000850445c`.
- `IOSurfaceParavirtMapperInterface`: slots 41/42 -> `preparedMappingForHostOnlySurface` `0xfffffe0008503c1c` and `supportsHostOnlySurfaces` `0xfffffe0008503e74`.
- `IOSurfaceParavirtMappingInternal`: slots 41/42 -> `init` `0xfffffe00084fdbc8` and `finalize` `0xfffffe00084fe03c`.

### Probe/start/stop and IOSurfaceRoot registration

- **LOCAL IMPLEMENTATION**: both probe methods set score 3000: device `0xfffffe00084fff4c`, service `0xfffffe00085041cc`.
- **LOCAL IMPLEMENTATION**: mapper-device start `0xfffffe00084fff5c` safe-casts its provider to `AppleARMIODevice`, maps device memory index 0, creates work loop/gate/interrupt source, prepares ring and descriptor table memory, publishes physical addresses and feature bits to MMIO, enables interrupts, and registers the service.
- **LOCAL IMPLEMENTATION**: mapper-service start `0xfffffe00085041dc` safe-casts provider to `IOSurfaceParavirtMapperDevice`, finds `IOSurfaceRoot`, creates `IOSurfaceParavirtMapperInterface` at call `0xfffffe000850425c`, and invokes imported `IOSurfaceRoot::registerMapperInterface` (import `0xfffffe000aa917f0`).
- **LOCAL IMPLEMENTATION**: device stop dispatches cleanup on its work loop; service stop is an empty local override at `0xfffffe0008504454`.
- **INHERITED/IMPORT**: this image has no local user client or `externalMethod`; only `IOService::newUserClient` imports `0xfffffe000aa91b88` and `0xfffffe000aa91b90`. There is no local or imported `clientMemoryForType` reference.

### Mapping object chain

- **LOCAL IMPLEMENTATION**: service `createMapping` `0xfffffe000850445c` calls `mappingForSurface(IOSurface*)` at `0xfffffe0008504480`; that calls the shared-pointer overload at `0xfffffe00085045c0`.
- **LOCAL IMPLEMENTATION**: shared-pointer `mappingForSurface` `0xfffffe0008504640` calls device `internalMappingForSurface` at `0xfffffe000850466c`, then wraps the internal object as `IOSurfaceParavirtMapping`.
- **LOCAL IMPLEMENTATION**: device lookup `0xfffffe0008500998` keys a dynamically grown array by IOSurface ID and checks IOSurface trace ID before reuse; a new internal mapping is inserted through `add_mapping` call `0xfffffe0008500b68`.
- **LOCAL IMPLEMENTATION**: public `prepare` `0xfffffe00085035ec` increments a wrapper reference count and calls internal `prepare` at `0xfffffe0008503624`; public `getMappingID` `0xfffffe00085035dc` returns internal qword `+0x30`; public `complete` `0xfffffe0008503544` balances the wrapper count and calls internal completion.
- **LOCAL IMPLEMENTATION**: internal `prepare` `0xfffffe00084fe360` increments an internal wire count and calls `wire_mapping` at `0xfffffe00084fe3a0` only on the first active prepare. Internal completion `0xfffffe00084fea5c` schedules deferred unwire one second later through `arm_timer` `0xfffffe00084fead4` when the last prepare is completed.
- **LOCAL IMPLEMENTATION**: `wire_mapping` prepares the IOSurface backing descriptor and private page-table descriptor, writes 32-bit page-number entries with low validity bits, then calls device `wire_host_mapping` at `0xfffffe00084fe5e8`; unwire calls `unwire_host_mapping` at `0xfffffe00084febe8` and clears valid bits.

### Mapper allocation and descriptor ABI

- **LOCAL IMPLEMENTATION**: mapper-device init `0xfffffe00084ff610` allocates a 1,024-byte bitmap, reserves bit 0, and therefore supports mapping IDs 1..8191 (`MAX_PREPARED_MAPPINGS = 0x2000`).
- **LOCAL IMPLEMENTATION**: the command ring is one page, mapped in kernel, with `entryCount = page_size >> 4`; each entry is 16 bytes.
- **LOCAL IMPLEMENTATION**: the surface-descriptor page table is one page of 32-bit physical-page entries (`page_size >> 2` entries). Descriptor storage is 512 bytes per mapping in legacy mode or 1,024 bytes when the 64-bit-descriptor feature is enabled.
- **LOCAL IMPLEMENTATION**: an internal mapping records IOSurface ID at `+0x90`, trace ID at `+0x88`, mapping ID at `+0x30`, descriptor pointer/size at `+0x38/+0x40` (legacy) or `+0x48/+0x50` (64-bit), page-table descriptor/map at `+0x58/+0x60`, page-table page count at `+0x78`, and IOSurface backing page count at `+0x80`.
- **LOCAL IMPLEMENTATION with inferred getter names**: legacy descriptor stores pixel format `+4`, base offset `+8`, allocation size `+16`, packed width/height and element dimensions beginning `+20`, bytes-per-row `+28`, bytes-per-element `+32`, plane count `+36`, address format `+37`, compression type `+38`, memory-layout flag `+39`, and cache mode `+44`. Address format and compression type must be zero.
- **LOCAL IMPLEMENTATION with inferred getter names**: 64-bit descriptor stores pixel format `+4`, base offset `+8`, allocation size `+24`, width `+32`, height `+40`, bytes-per-row `+48`, bytes-per-element `+56`, encoded element dimensions around `+60/+61`, plane count `+62`, address format `+63`, compression `+64`, memory-layout flags `+65`, cache mode `+84`, and protection options `+88`.
- **INHERITED/IMPORT**: the field producers correspond to imported IOSurface getters at `0xfffffe000aa92138..0xfffffe000aa92250`, including surface/trace ID, alloc size, cache mode, plane count, pixel format, base/plane offsets, dimensions, row/element sizes, address format, compression type, memory descriptor, and protection options.

### Host ring and MMIO ABI

- **LOCAL IMPLEMENTATION**: MMIO base is stored at device qword 19. Start publishes ring physical address at MMIO `+0x1000`, ring entry count at `+0x1008`, surface-descriptor table physical address at `+0x1010`, guest producer at `+0x1018`, host completion producer at `+0x1020`, host-supported features at `+0x1028`, and guest-enabled features at `+0x1030`.
- **LOCAL IMPLEMENTATION**: `do_host_mapping_gated` `0xfffffe0008502530` writes each 16-byte ring entry as `{u32 command, u32 mappingID, u32 result, u32 reserved}`. Wire uses command 1 through block `0xfffffe000850251c`; unwire uses command 2 through block `0xfffffe0008502988`.
- **LOCAL IMPLEMENTATION**: after enqueue, it increments the producer and writes MMIO `+0x1018`, waits up to 60 seconds for host completion, reads result at entry `+8`, advances its completed index, and wakes ring-space waiters. `wait_for_ring_space_gated` is `0xfffffe000850299c`.
- **LOCAL IMPLEMENTATION**: interrupt handler `0xfffffe0008500740` reads host completion producer from MMIO `+0x1020`, updates the local completion watermark, and wakes the command-gate sleepers associated with completed ring entries.
- **LOCAL IMPLEMENTATION**: `IOSurfaceParavirtMapperInterface::preparedMappingForHostOnlySurface` `0xfffffe0008503c1c` routes through service `prepared_mapping_for_host_only_surface` `0xfffffe0008503ce8`, creates/wraps the mapping, immediately calls `prepare(0)`, and marks the wrapper as pre-prepared. `supportsHostOnlySurfaces` delegates to device feature state.

---

## Cross-binary chain

1. **LOCAL IMPLEMENTATION / INHERITED IMPORT**: `AppleParavirtGPU : IOGPU : IOAccelerator`. APV start configures MMIO/root/FIFO/mapper, then base IOGPU start builds namespaces, scheduler, event machine, fence machine, kernel task, and IOSurfaceRoot integration.
2. **LOCAL IMPLEMENTATION**: opening IOGPU user-client type 5 at `IOGPU::newUserClient` `0xfffffe00090e06b0` calls APV virtual `newDeviceUserClient` `0xfffffe00084eac50`, yielding `AppleParavirtDeviceUserClient : IOGPUDeviceUserClient`.
3. **LOCAL IMPLEMENTATION**: base device-user-client start maps APV stamp memory, creates an `AppleParavirtDevice` through virtual factories, and exposes selectors 0..59. APV `externalMethod` prepends vendor selectors `0x100..0x110` and vendor traps `0x100..0x105` while falling back to base dispatch.
4. **LOCAL IMPLEMENTATION**: base selectors allocate command queues, resources, shared memory, notification queues, events, and fences. APV subclasses translate queue/resource operations to APV FIFO descriptors and Root/Exec/Object/Memory/Info/display channels.
5. **LOCAL IMPLEMENTATION**: `IOGPU::deviceCacheForIOSurface` `0xfffffe00090e12f8` creates `IOGPUResource` backing. Its virtual memory factory lands in APV `createMemoryForIOSurfaceDeviceCache` `0xfffffe00084eafc8`, which creates `AppleParavirtMapperMemory` for normal IOSurfaces.
6. **LOCAL IMPLEMENTATION, exact cross-image calls**: APV mapper memory calls AppleParavirtIOSurface service `mappingForSurface` `0xfffffe0008504558`, then public mapper `prepare`/`getMappingID`/`complete` at `0xfffffe00085035ec`/`0xfffffe00085035dc`/`0xfffffe0008503544`.
7. **LOCAL IMPLEMENTATION**: AppleParavirtIOSurface turns the IOSurface memory descriptor into page tables plus a 512/1,024-byte surface descriptor, assigns mapping ID 1..8191, and sends host ring command 1. The host-visible mapping ID is then available to APV display and resource commands.
8. **LOCAL IMPLEMENTATION**: `AppleParavirtDisplay : IOMobileFramebufferLegacy` receives a swap IOSurface, asks IOGPU for its device cache/mapping, emits APV display command 8 with display ID, GPU task ID, mapper ID, optional gamma map, and fences completion through IOGPU events.
9. **INFERENCE**: this establishes virtual GPU -> IOGPU service/user client -> APV display/framebuffer -> IOSurface paravirt mapper. The missing `IOMobileFramebufferLegacy` implementation is the unobserved bridge between WindowServer's framebuffer user client and `AppleParavirtDisplay::program_hardware_*`.

## Compact minimum ABI for first useful rendering

Counts use `(SI, STI, SO, STO)`, with `var` for `0xffffffff`.

| Stage | Minimum observed entry | Contract needed for clear/triangle/first frame | Evidence class |
|---|---|---|---|
| Open GPU device | `IOGPU::newUserClient`, type 5 | Returns APV device user client after attach/start, stamp map, and device creation | LOCAL IMPLEMENTATION |
| Query config | base selector 0 | `(0,0,0,64)`; returns feature/config sizes needed to size later records | LOCAL IMPLEMENTATION |
| Event stamps | base selector 2 | `(0,0,0,536)`; returns stamp-map address/shape and stamp offsets | LOCAL IMPLEMENTATION |
| Create command queue | base selector 7 | `(0,var,0,16)`; variable input must match configured size, output includes queue ID | LOCAL IMPLEMENTATION |
| Create resource | base selector 9 | `(0,var,0,var)`; minimum args `0x58`; returns resource ID, GPU VA/mapping and backing metadata | LOCAL IMPLEMENTATION |
| Create IOSurface resource | base selector 40 | `(3,0,1,0)`; attaches an IOSurface-backed resource and returns resource ID | LOCAL IMPLEMENTATION |
| Shared command memory | base selector 14 | `(2,0,0,16)`; returns client VA, mapped length, and shmem ID | LOCAL IMPLEMENTATION |
| Completion queue | base selectors 16 and 28 | create `(2,0,0,16)`, then bind `(2,0,0,0)` to command queue | LOCAL IMPLEMENTATION |
| Submit batch | base selector 29 | `(4,var,1,0)`; queue ID, count, stride, bytes; validates `size=count*stride` | LOCAL IMPLEMENTATION |
| Submit one fast | base trap 0 | queue ID, payload length `<=0x40`, user pointer, optional 4-byte status | LOCAL IMPLEMENTATION |
| Vendor object creation | APV `0x101` | `(0,var,1,0)` opaque object creation; required object kinds are encoded in user data | LOCAL IMPLEMENTATION; schema unknown |
| Vendor shader function | APV `0x104` | `(0,var,1,0)` returns a function/object handle | LOCAL IMPLEMENTATION; schema unknown |
| Vendor pipeline helper | APV `0x10a` | `(0,var,1,0)` explicitly creates a compute pipeline; a triangle's render-pipeline encoding is not named | LOCAL IMPLEMENTATION plus exact unknown |
| Vendor resource graph | APV `0x105/0x106/0x10b` | child-resource add/remove and heap-buffer attachment | LOCAL IMPLEMENTATION |
| Vendor queue/info | APV `0x10f/0x110` | select info channel/queue and synchronize a resource | LOCAL IMPLEMENTATION |
| Surface user client | type `0x20` | legacy surface methods plus selectors 6/9/17 for shape and 18 for shared-event signal | LOCAL IMPLEMENTATION |
| IOSurface host mapping | service `mappingForSurface`, then `prepare/getMappingID/complete` | assigns mapping ID and sends host ring wire/unwire commands 1/2 | LOCAL IMPLEMENTATION |
| First scanout | `AppleParavirtDisplay::program_hardware_swap_gated` | FIFO command 8, 40-byte payload with display/task/mapping ID and optional gamma map | LOCAL IMPLEMENTATION |
| Cursor | display command 4 | BGRA/4-BPE IOSurface, 44-byte glyph payload | LOCAL IMPLEMENTATION |
| Mode/gamma | display mode methods and 3,084-byte gamma record | mode selects timing/color; gamma is 3 x 257 entries converted to float | LOCAL IMPLEMENTATION |
| WindowServer framebuffer call | imported `IOMobileFramebufferLegacy` ABI | Required to reach the APV display swap from WindowServer; implementation not among supplied binaries | INHERITED/IMPORT; exact unknown |

**INFERENCE**: a clear can use the same queue/resource/shmem/submit path without shader-function creation if the user command stream supports a clear operation. A triangle additionally needs vendor object/function/render-pipeline state and a submitted encoded command buffer. The dispatch envelope is proved, but the opaque Metal/APV render object and command byte schemas are not.

## Exact unknowns and limits

1. **INHERITED/IMPORT**: `IOUserClient::clientMemoryForType` implementation and its numeric type codes are outside the supplied images. No local override was found in APV or IOGPUFamily.
2. **INHERITED/IMPORT**: `IOMobileFramebufferLegacy` probe/newUserClient/swap user ABI and the WindowServer call sequence are outside the supplied images. This prevents a fully exact user-to-framebuffer minimum ABI.
3. **INFERENCE / exact unknown**: numeric APV FIFO IDs 1, 2, 4, 8, 9, `0x0a`, `0x0b`, and `0x0c` and their locally observed payload writes are proved; authoritative enum names and complete host-side schemas are absent.
4. **INFERENCE / exact unknown**: APV selectors with variable structures expose counts and wrapper targets, but structures for `createObject`, `createFunction`, render pipeline state, heap texture sizing, and rasterization-rate maps are not fully recoverable from these wrappers alone.
5. **INFERENCE / exact unknown**: clear/triangle command bytes inside IOGPU/APV shared command buffers, shader binary format, and all resource-type-specific private payloads are not named in these kernel images.
6. **LOCAL IMPLEMENTATION plus INFERENCE / exact unknown**: the callback and re-arm argument 16 are proved; interpreting the imported timer method as milliseconds gives a likely 16-ms software VBL cadence, but the unit, phase, and relation to a physical/host vblank signal are not symbolically proved.
7. **INHERITED/IMPORT**: the host consumer of the IOSurface mapper ring and APV GPU FIFO is not present, so host acceptance rules beyond guest-side validation and returned error fields remain unknown.
8. **LOCAL IMPLEMENTATION caveat**: several PAC/chained-fixup targets appear to Hex-Rays as `MEMORY[address]`, and a few functions decompile with assert/cold edges represented as recursive calls. Exact conclusions above use named functions, raw stores, disassembly, vtable slots, and xrefs where pseudocode was ambiguous.

## Raw IDA/IDAPython errors

The following read-only query errors occurred and were corrected; database opening/closing itself produced no raw IDA error.

1. Database 1 initial inventory:

   `AttributeError: module 'ida_nalt' has no attribute 'get_file_type_name'`

   Raw traceback ended at `<ida-mcp>, line 6`. The inventory was rerun without that unavailable helper.

2. Database 3 hierarchy query:

   `SyntaxError: invalid syntax. Perhaps you forgot a comma? (<ida-mcp>, line 2)`

   The mistyped address token was `0xfffffe00090af f54`; the query was rerun with `0xfffffe00090aff54`.

No decompilation call reported a `PseudocodeError`; ambiguous decompiler output is called out under exact unknowns rather than treated as a failed query.
