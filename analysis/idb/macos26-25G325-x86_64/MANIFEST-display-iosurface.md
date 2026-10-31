# IDB 清单 — macos26-25G325-x86_64（显示与 IOSurface 轮次）

建立日期：2026-10-30
用途：`docs/spec/11-KERNEL-DISPLAY.md`、`docs/spec/12-KERNEL-IOSURFACE.md` 的全部地址引用

> **本文件只覆盖本目录根下的 `*-kc-rebuild.i64` 与 `kernel-low30-symmap.json` 五件。**
> 同一目录的 `idb/*-segfixed.i64` 与 `tools/*.py` 来自另一轮（accelerator 侧，
> `docs/spec/10-KERNEL-ACCELERATOR.md`），不在本文件范围内。两轮各自独立建库，
> 内容重复但互不依赖；需要合并时以 `tools/fixseg.py` 的实现为准（它与本文 §2.1 的
> 修法等价）。
>
> **维护者注意（两处写入冲突风险）：**
> ① 本轮曾向本目录写入过一个名为 `MANIFEST.md` 的文件，随后改名为现名，以免与
> accelerator 轮次抢占同一文件名。若 accelerator 轮次此前已存在 `MANIFEST.md`，
> 其内容可能已被覆盖，请从该轮的工作记录重建。
> ② `kernel-low30-symmap.json` 由本轮写入。若 accelerator 轮次此前用同名文件存过
> 不同格式的符号表，同样可能已被覆盖；本轮的格式见 §1 末尾说明。
样本层级：**T2**（25G325 installed SystemOS kernel collection 的 `LC_FILESET_ENTRY` 重建件），分级依据见 `docs/spec/90-EVIDENCE-INDEX.md` §1、§2.1

本目录只新增文件，**没有改写 `analysis/idb/` 下任何既有文件**。

## 1. 文件

| IDB | 输入样本（`analysis/binaries/macos26-25G325-x86_64/kext/`） | 输入 `LC_UUID` | IDA 加载后镜像基址 | 符号数 | 函数数 |
|---|---|---|---|---:|---:|
| `IOGraphicsFamily-x86_64-kc-rebuild.i64` | `com.apple.iokit.IOGraphicsFamily` | `74AA6483-8AB4-3A94-8143-5E306C16D7DA` | `0x14CE4000` | 2114 | 1146 |
| `AppleParavirtGPU-x86_64-kc-rebuild.i64` | `com.apple.driver.AppleParavirtGPU` | `B88E1D48-71A2-3DC0-8D87-605DDB039B83` | `0x14898000` | — | 844 |
| `IOAcceleratorFamily2-x86_64-kc-rebuild.i64` | `com.apple.iokit.IOAcceleratorFamily2` | `6C4A16B1-66DC-3A8B-9F0B-D3E027B16EB1` | `0x14B65000` | 4707 | 3028 |
| `IOSurface-x86_64-kc-rebuild.i64` | `com.apple.iokit.IOSurface` | `766DF6D3-1EEC-34DB-A9AD-EF72A36FB2A8` | `0xFFFFFF8002B84000` | 2767 | 1673 |
| `kernel-low30-symmap.json` | `kernel/kernel.x86_64` | `E514CEBA-9206-34D5-86C2-64E880FDDA2B` | — | 23670 | — |

`kernel-low30-symmap.json` 是 `{ 独立内核 VA 的低 30 位 (十进制字符串) : 符号名 }` 的映射，用来把 kext 里 chained-fixup 解码出的跨模块 target 还原成具名内核符号。它不是 IDB。

**IDB 名字里的 `kc-rebuild` 是刻意的**：这些库里的地址是 kernel collection 内的地址（其中 SystemKC 条目的 `vmaddr` 被重建脚本截断成了低 30 位），不是任何可直接在运行系统上观察到的 slid 地址。引用时必须写 `UUID + RVA`，RVA = `VA − 上表镜像基址`。

## 2. 建库前必须做的两步修正

**直接把 `analysis/binaries/.../kext/` 下的重建件丢给 IDA 会得到一个"有符号、没字节"的空库**（函数数 0、`is_loaded()` 全 False）。本目录的 4 个 IDB 是在修正后的副本上建立的；修正只在 `$env:TEMP` 下的副本上做，仓库原件未改动。

### 2.1 `LC_SEGMENT_64` 的 `fileoff` / `filesize` 字段错位

重建脚本把每个 segment 的 `fileoff` 写成了 `vmaddr`，把 `filesize` 写成了真实的 `fileoff`。`section_64.offset` 是正确的。修法：

```python
true_fileoff  = segment.filesize_field
true_filesize = max(sec.offset + sec.size for sec in segment.sections if sec.offset != 0) - true_fileoff
# 只含 zero-fill section（offset == 0，如 __common / __bss）的段用 min(vmsize, filelen - true_fileoff)
```

四件修正后的值：

| 样本 | `__TEXT` | `__DATA` | `__DATA_CONST` | `__LINKEDIT` |
|---|---|---|---|---|
| IOGraphicsFamily | `0x4000` / `0x2E24A` | `0x34000` / `0xF9C0` | `0x44000` / `0x1E50` | `0x48000` / `0xC5A678` |
| AppleParavirtGPU | `0x4000` / `0x17B97` | `0x1C000` / `0x9080` | `0x28000` / `0xC30` | `0x2C000` / `0xC5A678` |
| IOAcceleratorFamily2 | `0x4000` / `0x6978C` | `0x70000` / `0x16EC8` | `0x88000` / `0x25C0` | `0x8C000` / `0xC5A678` |
| IOSurface | `0x4000` / `0x2C4DE` | `0x34000` / `0x65D8` | `0x3C000` / `0x1520` | `0x40000` / `0xC4C5EA` |

### 2.2 `__DATA` 指针是 chained-fixup 编码值

位域（`DYLD_CHAINED_PTR_64_KERNEL_CACHE` 风格）：

```
target : 30, cacheLevel : 2, diversity : 16, addrDiv : 1, key : 2, next : 12, isAuth : 1
```

- `target = value & 0x3FFFFFFF`
- SystemKC 重建件（IOGraphicsFamily / AppleParavirtGPU / IOAcceleratorFamily2）：`target` **直接等于**本库里的地址。
- BootKC 重建件（IOSurface）：本库里的地址 `= 0xFFFFFF8000100000 + target`。
- 指向内核本体的 target，换算到 `kernel.x86_64` 独立件地址的 per-segment 增量：`__TEXT −0x18000`、`__DATA +0x450000`、`__DATA_CONST +0xDCA000`。配合 `kernel-low30-symmap.json` 可还原符号名。

校验锚点：IOGraphicsFamily 的 `__ZTV` for `IOFramebuffer`（RVA `0x35248`）槽 2 原始值 `0x0040000054D0CDC4` → `target 0x14D0CDC4` → RVA `0x28DC4` = `IOFramebuffer::~IOFramebuffer()`。

### 2.3 vtable 槽号的 "+2"

反编译里的 `(*(void**)(*(void**)obj + N))` 对应 `__ZTV` 槽号 `N/8 + 2`（槽 0/1 是 offset-to-top 与 typeinfo）。本项目文档里的槽号一律以 `__ZTV` 起点计。

### 2.4 一个 grep 陷阱

这些重建件的 `__LINKEDIT` 携带的是**整个 kernel collection 的 linkedit 大块**（三件 SystemKC 重建件的 `__LINKEDIT` 长度都是 `0xC5A678`），所以字符串表里有**全部 kext 的 C++ mangled 名**。对重建件做 `strings | grep <mangled>` 判断"哪个 kext 引用了某符号"会全是假阳性。必须解析该件自己的 `LC_SYMTAB` nlist 并检查 `n_type & N_TYPE == N_UNDF`。`__cstring` 是每件独立的，对普通字面量 grep 仍然有效。

## 3. 库内已做的标注

本轮分析以读为主，**没有在库里新增重命名、注释或结构定义**。4 个库的价值在于：

1. 省掉 §2.1 / §2.2 的踩坑与 IDA 自动分析时间。
2. IOGraphicsFamily 库里 IDA 已从类型库解析出 `StdFBShmem_t`（240 字节）、`IOPixelInformation`（172 字节）、`IODisplayModeInformation`（36 字节）、`IOTimingInformation`（168 字节）、`IODetailedTimingInformationV2`（160 字节）、`IOHardwareCursorDescriptor`/`IOHardwareCursorInfo`、`IOGBounds`/`IOGPoint`/`IOGSize` 等公开结构，可直接 `db.types.get_by_name()` 取布局。

## 4. 未覆盖

- `com.apple.AppleGraphicsDeviceControl`、`com.apple.iokit.IOGPUFamily`、`com.apple.iokit.IOPCIFamily` 尚无 IDB。
- `kernel.x86_64` 尚无 IDB（本轮只用它的符号表做跨模块解析）。
- 两个 `.kc` 共 376 个 fileset 条目里只抽取了 7 个 graphics kext，全集 nlist 扫描未做（`12-KERNEL-IOSURFACE.md` §4.3 的证据范围限制源于此）。
