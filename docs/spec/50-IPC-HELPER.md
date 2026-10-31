# 50 — 进程模型、wire protocol、对象表与 generation、崩溃恢复

文档版本：1.0
基线：macOS Tahoe 26.7.2 / build 25G325 / **x86_64**
职责（`00-OVERVIEW.md` 第 8 节）：进程模型、wire protocol、对象表与 generation、崩溃恢复
对应上游"不做"清单第 10 项（`40-RUNTIME-VULKAN.md` 第 4 节）：上游提供 `ObjectId`、`used_resources`、`commit_failed`、`set_submission_check`，其余全是本项目的工作

## 0. 本文作用与前稿关系

本文**吸收并校正** `analysis/spec-work/bridge-runtime-contract.md`（版本 `0.2-contract`，SHA-256 见该文第 0.1 节）。原稿在 IPC 契约上做得相当细 —— 第 6.3 节的 handle 格式、第 8 节的 envelope / 消息集 / blob schema / 固定上限、第 9 节的 IOSurface 两轴模式、第 10 节的完成状态机都可以直接用。

两类必须改的地方：

1. **原稿锚定的上游 commit 不是本项目的基线。** 原稿写 `0dfdbcd59d235e37ba13b87a5ab30835b5bb9e35`；`40-RUNTIME-VULKAN.md` 的锚点是 `219f01365dc4c8eb346816c405b5b17403793764`（产品版本 `0.2.0`）。本文按后者。
2. **原稿是最小集规格。** 它的消息集只覆盖 clear 与 triangle（原稿第 2.1、2.2 节），`00-OVERVIEW.md` 第 4.7 节已作废最小集规格。本文按全量能力补齐。

本文第 9 节逐条列出"原稿如此、现更正为"。凡本文未在第 9 节标为更正的原稿条目，均为**吸收并保留**。

### 0.1 `00-OVERVIEW.md` 第 6 节的决定

> 第一版**同进程**，不引入 IPC。helper 进程隔离在接入 WindowServer 之前引入，目的是让 Mesa/LLVM 崩溃不拖死 WindowServer。接口形状提前按可切分设计，但第一版不付出 IPC 成本。

因此本文**同时**规定两件事：

- **第一版的同进程形态**（第 1.1–1.3 节）：窄 C ABI 边界在哪，哪些类型可以跨这个边界。
- **切分后的接口形状**（第 2 节起）：同一个调用变成什么消息。

第 1.4 节是两者的对应表。规则是：**第一版的 C ABI 必须按这张表的形状写，哪怕它现在只是一次函数调用。** 否则切分时要重写全部调用点。

### 0.2 样本与标签

证据标签见 `00-OVERVIEW.md` 第 7 节。本文大部分内容是**实现规格**（`INFERRED`），上游 API 事实标 `KNOWN` 并给出 `40-RUNTIME-VULKAN.md` 的节号；macOS 的 XPC / launchd / IOSurface 行为凡未在目标 guest 实测的一律 `BLOCKED`。

样本代号沿用 `22-OBJC-DESCRIPTORS.md` 第 0 节（`S-METAL`、`D-OBJC`）。

---

## 1. 进程模型

### 1.1 第一版：同进程，一道窄 C ABI 边界

```text
┌─ WindowServer / CoreAnimation / app 进程 ────────────────────────┐
│                                                                   │
│  Metal 客户端代码                                                 │
│      │ ObjC selector（x86_64 encoding，21 分册）                   │
│  Metal.framework                                                  │
│      │ class gate（20 分册 §3.1）                                  │
│  /Library/GPUBundles/Metal2Vu.bundle                              │
│   ├─ ObjC 对象族（.m）           ← 20 / 21 / 22 分册                │
│   │     │ **窄 C ABI：m2v_* 函数 + 纯 C 结构**  ← 本文 §1.2         │
│   ├─ libm2v_core.a（Rust，静态链入）                               │
│   │   ├─ adapter（对象表、snapshot 消费、错误映射）  ← 本文 §3 §4    │
│   │   ├─ metal2vulkan-runtime + metal2vulkan                      │
│   │   └─ IOSurface 桥（41 分册）                                   │
│   │     │ ash                                                     │
│   ├─ Contents/Resources/lib/libvulkan.dylib（loader）              │
│   └─ Contents/Resources/lib/libvulkan_lvp.dylib（Lavapipe + LLVM） │
└───────────────────────────────────────────────────────────────────┘
```

安装布局见 `70-BUILD-PACKAGE.md` 第 6.1 节。第一版**不安装** `/usr/local/libexec/metal2vu-helper` 与 `/Library/LaunchDaemons/net.metal2vu.helper.plist`（该节已如此标注）。

**同进程形态的代价，必须明写**：Lavapipe 把 LLVM 整个拖进客户端进程。对 WindowServer 来说这意味着：

| 风险 | 后果 | 第一版的处置 |
|---|---|---|
| LLVM JIT 的任何崩溃 | WindowServer 崩溃 → 全屏黑 → 登录会话重启 | 无法缓解。这正是引入 helper 的理由 |
| LLVM 的内存占用（JIT 代码 + 优化器） | WindowServer RSS 膨胀，可能触发 jetsam | 限制 shader cache 内存上限（`ShaderCacheOptions`，`40-RUNTIME-VULKAN.md` 第 6.6 节） |
| LLVM 需要可写可执行内存 | 与 WindowServer 的加固运行时冲突 | 研发期 SIP/AMFI 关闭（`00-OVERVIEW.md` 第 2.4 节）；分发期 `BLOCKED` |
| 管线编译阻塞 | 上游默认 `pipeline_creation_wait` 4.5 s + `pipeline_commit_wait` 4.5 s = 最坏 9 s，而 guest 的 FIFO 检查是 10 s（`40-RUNTIME-VULKAN.md` 第 6.6 节） | 必须显式设定并与显示超时对齐，见第 5.5 节 |

> **D1**：第一版只允许在**不是 WindowServer** 的进程里验证（`metal-probe`、测试 app）。**接入 WindowServer 之前必须先完成切分。** 这不是优化，是 `00-OVERVIEW.md` 第 6 节的明文要求。

### 1.2 窄 C ABI 边界的位置与形状

边界在 **ObjC 对象族与 Rust adapter 之间**，不在别处。

> **D2**：边界是**一组 `extern "C"` 函数 + 一组纯 C 结构（POD）**，声明在 `include/m2v_abi.h`。该头文件只 `#include <stdint.h>` 与 `<stdbool.h>`，不含任何 ObjC 类型、不含 `Vk*` 类型、不含 Rust 类型。Rust 侧用 `bindgen` 从它生成绑定（`22-OBJC-DESCRIPTORS.md` R32）。

**可以跨边界的类型**（白名单，`INFERRED`）：

| 类 | 形式 | 说明 |
|---|---|---|
| 对象标识 | `uint64_t m2v_oid`（上游 `ObjectId` 的数值形式） | 见第 3 节。**不是指针** |
| descriptor snapshot | `m2v_*_snapshot` POD 结构，定长 + 定长内联数组 | `22-OBJC-DESCRIPTORS.md` 第 4 节逐类定义 |
| 变长字节 | `struct { const uint8_t *ptr; size_t len; }`，**调用期间有效，被调方必须复制** | metallib、顶点字节、label 的 UTF-8 |
| 标量与定长 struct | `uint64_t` / `int64_t` / `double` / `m2v_size3` / `m2v_clear_color` 等 | — |
| 错误 | `m2v_error`：`{ uint32_t category; int64_t source_code; char source_kind[64]; char message[512]; bool retryable; }` | 第 4 节 |
| 回调 | `void (*)(void *ctx, const m2v_event *ev)` + `void *ctx` | **只允许这一种**，见 D4 |
| 命令日志 | `m2v_cmd_log`：定长 header + `m2v_cmd` 的紧凑数组 | 第 2.4 节 |
| IOSurface | `IOSurfaceRef`（即 `void *`） | **仅在同进程阶段**。见 D3 |

**不得跨边界的类型**（黑名单）：

- 任何 ObjC `id`、`Class`、`SEL`、block（`@?`）。block 必须在 ObjC 侧 `_Block_copy` 并包成 `(fn ptr, ctx)` 对。
- 任何 `Vk*` handle。上游的 `Device::raw()` / `Texture::vk_image()` 等都是 `unsafe`（`40-RUNTIME-VULKAN.md` 第 4.1 节），它们的结果**不出 Rust**。
- 任何 Rust 类型（`&str`、`Vec`、`Option`、trait object、`Arc`）。
- 任何裸指针，除了上表的三项（变长字节的 `ptr`、回调的 `ctx`、`IOSurfaceRef`）。
- 任何自引用结构或含填充未定义的结构。POD 结构必须 `#pragma pack` 关闭、字段按对齐排列、显式填充字段并清零。

> **D3**：`IOSurfaceRef` 跨 C ABI 在同进程阶段是合法的（它是 CF 对象，Rust 侧只 `CFRetain` / `CFRelease` 并调 `IOSurface*` C API）。**切分后它不再跨边界** —— 第 2.3 节的 `IMPORT_SURFACE` 传的是 Mach right。因此 ABI 的这一项必须从第一天就包在一个 `m2v_surface_token` 里，同进程阶段 token 内部装 `IOSurfaceRef`，切分后装 Mach send right。调用点不变。
>
> **D4**：Rust 侧**绝不**直接调用 ObjC block。事件回调的实现必须是：Rust 调 `(fn ptr)(ctx, ev)` → 那个函数在 ObjC 侧（`.m` 文件里）→ 它负责取出 block 列表、在锁外逐个调用、捕获 ObjC 异常。理由：Rust 的 unwind 不能穿过 ObjC 的异常，反之亦然；`bridge-runtime-contract.md` 第 10.3 节已记录该条，成立。
>
> **D5**：边界上的全部函数必须是 `#[no_mangle] pub extern "C"` 且**整个函数体包在 `catch_unwind` 里**。Rust panic 穿过 FFI 是未定义行为。`catch_unwind` 捕获到 panic 时填 `m2v_error{ category: InternalError }` 并返回失败，不得重新 panic。

### 1.3 ABI 的函数分组

```c
/* 生命周期 */
m2v_status m2v_bootstrap(const m2v_bootstrap_options *opt, m2v_oid *out_device, m2v_error *err);
m2v_status m2v_shutdown(void);                       /* 调上游 process_exiting */

/* 对象创建：每个返回一个 oid */
m2v_status m2v_new_command_queue (m2v_oid dev, const m2v_queue_snapshot *s,    m2v_oid *out, m2v_error *e);
m2v_status m2v_new_buffer        (m2v_oid dev, const m2v_buffer_snapshot *s,   m2v_bytes init, m2v_oid *out, m2v_error *e);
m2v_status m2v_new_texture       (m2v_oid dev, const m2v_texture_snapshot *s,  m2v_oid *out, m2v_error *e);
m2v_status m2v_new_texture_on_surface(m2v_oid dev, const m2v_texture_snapshot *s, m2v_surface_token tok, uint64_t plane, m2v_oid *out, m2v_import_mode *mode, m2v_error *e);
m2v_status m2v_new_heap          (m2v_oid dev, const m2v_heap_snapshot *s,     m2v_oid *out, m2v_error *e);
m2v_status m2v_new_library       (m2v_oid dev, m2v_bytes metallib,             m2v_oid *out, m2v_error *e);
m2v_status m2v_new_function      (m2v_oid lib, const m2v_function_snapshot *s, m2v_oid *out, m2v_error *e);
m2v_status m2v_new_render_pipeline (m2v_oid dev, const m2v_render_pipeline_snapshot *s,  m2v_oid *out, m2v_oid *refl, m2v_error *e);
m2v_status m2v_new_compute_pipeline(m2v_oid dev, const m2v_compute_pipeline_snapshot *s, m2v_oid *out, m2v_oid *refl, m2v_error *e);
m2v_status m2v_new_depth_stencil (m2v_oid dev, const m2v_depth_stencil_snapshot *s, m2v_oid *out, m2v_error *e);
m2v_status m2v_new_sampler       (m2v_oid dev, const m2v_sampler_snapshot *s,  m2v_oid *out, m2v_error *e);
m2v_status m2v_new_icb           (m2v_oid dev, const m2v_icb_snapshot *s,      m2v_oid *out, m2v_error *e);
m2v_status m2v_new_argument_encoder(m2v_oid dev, const m2v_arg_desc *a, size_t n, m2v_oid *out, m2v_error *e);
m2v_status m2v_new_binary_archive(m2v_oid dev, const m2v_archive_snapshot *s,  m2v_oid *out, m2v_error *e);
m2v_status m2v_new_event         (m2v_oid dev, bool shared,                    m2v_oid *out, m2v_error *e);
m2v_status m2v_new_fence         (m2v_oid dev,                                 m2v_oid *out, m2v_error *e);
m2v_status m2v_new_residency_set (m2v_oid dev, const m2v_resset_snapshot *s,   m2v_oid *out, m2v_error *e);
/* … 其余按 21 分册的对象清单一一对应 */

/* 对象查询：只读，不进 Rust 的锁 */
m2v_status m2v_query_device_properties(m2v_oid dev, m2v_device_properties *out, m2v_error *e);
m2v_status m2v_query_family_blockers (m2v_oid dev, uint64_t family, m2v_family_audit *out, m2v_error *e);
m2v_status m2v_query_format_caps     (m2v_oid dev, uint64_t pf, m2v_format_caps *out, m2v_error *e);

/* 提交 */
m2v_status m2v_command_buffer_create(m2v_oid queue, const m2v_cb_snapshot *s, m2v_oid *out, m2v_error *e);
m2v_status m2v_submit  (m2v_oid cb, uint64_t queue_seq, const m2v_cmd_log *log, m2v_error *e);
m2v_status m2v_wait    (m2v_oid cb, uint64_t deadline_ms, m2v_cb_state *out, m2v_error *e);
m2v_status m2v_cb_state_read(m2v_oid cb, m2v_cb_state *out);   /* 无锁，不失败 */

/* 释放 */
m2v_status m2v_release (m2v_oid obj);                /* 幂等 */

/* 事件 */
void       m2v_set_event_sink(void (*cb)(void *, const m2v_event *), void *ctx);
```

> **D6**：**`m2v_submit` 一次传完整个命令缓冲的全部编码记录。** 这是切分友好性的核心设计决定。ObjC 侧的 encoder 对象是**客户端进程内的单写者日志**，每个 `setVertexBuffer:offset:atIndex:` 只往本地日志追加一条记录，**不跨 ABI**。`endEncoding` 封闭日志，`commit` 发一次 `m2v_submit`。
>
> 原稿第 1 节已经这么设计了（"`RenderCommandEncoder` proxy 是客户端内的临时单写者日志对象，不分配远端 encoder handle"）。**该决定成立并保留**，理由在全量能力下更强：
> 1. 上游的 encoder 是独占值、`Send` 但非 `Sync`、`end_encoding(self)` 消费（`40-RUNTIME-VULKAN.md` 第 5 节）。跨 IPC 持有一个半开 encoder 意味着一旦连接断开就有一个不可恢复的独占值。
> 2. `MTLRenderCommandEncoder` 有约 80 条命令（`40-RUNTIME-VULKAN.md` 第 3.3 节），compute 30 条，blit 26 条。每条一次往返 = 每帧数千次 IPC。
> 3. 整条日志可以在提交前一次性校验（上游的 `set_submission_check` 与 `execute_commands_in_buffer_checked` 正是为此而设，`40-RUNTIME-VULKAN.md` 第 4.1 节），"校验通过才开始录"比"录到一半失败"好处理得多。
>
> 代价：encoder 上的**同步查询**无法本地回答。清单与处置见第 2.4.3 节。

### 1.4 同进程调用 → IPC 消息的对应表

`INFERRED`。这张表是第一版 ABI 的设计约束：**左列的每一个函数必须能一对一变成右列的一条消息，参数不变。**

| 同进程 C ABI | 切分后的消息 | 同步性 | 说明 |
|---|---|---|---|
| `m2v_bootstrap` | `HELLO` | 同步 | 返回 device oid + capability snapshot + limits |
| `m2v_shutdown` | `GOODBYE` + 连接关闭 | 同步 | helper 侧调 `process_exiting` |
| `m2v_new_command_queue` | `CREATE_QUEUE` | 同步 | |
| `m2v_new_buffer` | `CREATE_BUFFER` | 同步 | `init` 字节走 blob（第 2.5 节） |
| `m2v_new_texture` | `CREATE_TEXTURE` | 同步 | |
| `m2v_new_texture_on_surface` | `IMPORT_SURFACE` | 同步 | `m2v_surface_token` 从 `IOSurfaceRef` 变成 Mach right（D3） |
| `m2v_new_heap` | `CREATE_HEAP` | 同步 | |
| `m2v_new_library` | `CREATE_LIBRARY` | 同步 | metallib 走 blob，可能 OOL |
| `m2v_new_function` | `CREATE_FUNCTION` | 同步 | |
| `m2v_new_render_pipeline` | `CREATE_RENDER_PIPELINE` | **同步，长耗时** | 上游 `pipeline_creation_wait` 默认 4.5 s；见第 5.5 节 |
| `m2v_new_compute_pipeline` | `CREATE_COMPUTE_PIPELINE` | 同上 | |
| `m2v_new_depth_stencil` / `_sampler` / `_fence` / `_event` | `CREATE_STATE`（带 kind 判别） | 同步 | 这四个都是小对象、无长耗时，合成一条消息减少 opcode |
| `m2v_new_icb` / `_argument_encoder` / `_binary_archive` / `_residency_set` / `_visible_function_table` | `CREATE_BINDING`（带 kind 判别） | 同步 | 同上 |
| `m2v_query_device_properties` / `_family_blockers` / `_format_caps` | **不变成消息** | — | 这三项在 `HELLO` 时一次性全量取回并冻结在客户端。见 D7 |
| `m2v_command_buffer_create` | `CREATE_COMMAND_BUFFER` | 同步 | |
| `m2v_submit` | `SUBMIT` | **异步**：立即回 accepted/rejected，完成走事件 | 第 2.4 节 |
| `m2v_wait` | `WAIT` | 同步，带 deadline | 第 5.4 节 |
| `m2v_cb_state_read` | **不变成消息** | — | 只读客户端侧的原子状态；事件流负责推进它 |
| `m2v_release` | `DESTROY` | 异步，fire-and-forget，幂等 | 第 3.4 节 |
| 事件回调 | `EVENT_SCHEDULED` / `EVENT_TERMINAL` / `EVENT_DEVICE_LOST` / `EVENT_DEGRADATION` / `EVENT_LOG` | 单向 server→client | 第 2.3 节 |
| encoder 上的每条命令 | **不变成消息**（D6） | — | 进 `m2v_cmd_log` |
| `label` / `setLabel:` | **不变成消息** | — | proxy 本地保存；需要时随下一条创建/提交消息捎带 |
| descriptor getter（`texture.width` 等） | **不变成消息** | — | 读创建时的 snapshot |
| `MTLEvent` 的 host 侧 signal / wait | `EVENT_SIGNAL` / `EVENT_HOST_WAIT` | signal 异步、wait 同步带 deadline | 第 5.6 节 |
| `MTLSharedEvent` 的跨进程 handle | `EXPORT_SHARED_EVENT` / `IMPORT_SHARED_EVENT` | 同步 | 上游句柄仅进程内（`40-RUNTIME-VULKAN.md` 第 4 节第 6 项），本项目实现，见第 5.6 节 |
| `MTLSharedTextureHandle` 的 encode / decode | `EXPORT_SHARED_TEXTURE` / `IMPORT_SHARED_TEXTURE` | 同步 | 同上，见 `22-OBJC-DESCRIPTORS.md` 第 4.25 节 |
| `MTLHeap` 上的 `newBufferWithLength:options:offset:` | `CREATE_ON_HEAP` | 同步 | |
| `MTLBuffer.contents` | **不变成消息** | — | 见 D8 |
| `MTLTexture.replaceRegion:…` | `REPLACE_REGION` | 同步（需要知道何时可以复用源内存） | 走 blob；大区域必须 OOL |
| `MTLBuffer.didModifyRange:` | 捎带在下一条 `SUBMIT` 上 | — | 不值得单独一条消息 |
| `MTLCommandBuffer.addCompletedHandler:` | **不变成消息** | — | block 存在 proxy 侧，由 `EVENT_TERMINAL` 触发 |

> **D7**：capability 与 limits 在 `HELLO` 时一次性冻结。理由：`20-OBJC-DEVICE.md` 第 1 节已证明整张 limits 表是 `featureProfile` 一个枚举值的纯函数、对 user client 零依赖；而 `supportsFamily:` 必须由上游 `family_blockers` 推出、不得硬编码（`40-RUNTIME-VULKAN.md` 第 2.1 节）。两者结合：**启动时算一次，之后是常量。** 连带规则：helper 重启产生新 generation 时**不热更新**已有连接的 snapshot（原稿第 11 节的该条成立）。
>
> **D8**：`MTLBuffer.contents` 在同进程阶段返回真实指针（上游 `Buffer::contents`）。切分后：
> - `StorageModeShared` / `Managed` 的 buffer，helper 把其后备页通过 Mach memory entry 映射进客户端，`contents` 返回映射地址。**这是必须做的** —— CoreAnimation 大量用 `contents` 直写顶点与 uniform，返回 `NULL` 等于不可用。
> - `StorageModePrivate` 的 buffer，`contents` 返回 `NULL`（Metal 的正确行为）。
> - `BLOCKED`：Mach memory entry 的跨进程映射在 25G325 的 WindowServer sandbox 下是否可行**未实测**。关闭方式见第 8.4 节的 Gate H-2。原稿第 2.4 节把跨进程 `contents` 写成"为 `NULL`，除非另有共享映射合同"，**现更正为：共享映射是必需项，不是可选项**，并把它列为切分的前置条件。

---

## 2. Wire protocol

传输：**XPC**（`xpc_connection_t` + `xpc_dictionary_t`）。`INFERRED`。选它而不是裸 Mach 或 UNIX socket 的理由：

1. XPC 原生携带 **audit token**（`xpc_connection_get_audit_token`），这是第 3.1 节 per-client namespace 的唯一可信身份来源；
2. XPC 原生携带 **Mach send right** 与 **shared memory object**，IOSurface 与 OOL blob 需要它；
3. XPC 有现成的 invalidation handler，崩溃检测不用自己写（第 6 节）；
4. launchd 原生托管 XPC service（第 8 节）。

代价：XPC 字典的序列化比自定义二进制慢。处置：**每帧的量级是 O(命令缓冲数) 而不是 O(命令数)**（D6），所以字典开销不在热路径上；真正大的是命令日志，它走 `xpc_data_t`（见第 2.4 节），本身就是一次 memcpy。

### 2.1 Request / reply envelope

吸收原稿第 8.1 节，**保留全部 7 个键**并补 2 个。

| 键 | XPC 类型 | 规则 | 来源 |
|---|---|---|---|
| `v` | uint64 | 必须 `== 1` | 原稿，保留 |
| `kind` | uint64 | 必须在第 2.2 节表中 | 原稿，保留 |
| `request_id` | uint64 | 非零、连接内严格递增 | 原稿，保留 |
| `client_id` | uint64 | `HELLO` 为 0；其余必须等于 connection-bound 值。**helper 不以请求中的 `client_id` 选 namespace** | 原稿，保留（这一条是对的，第 7.2 节重申） |
| `generation` | uint64 | `HELLO` 为 0；其余必须等于当前 generation 且 `<= u32::MAX` | 原稿，保留 |
| `declared_bytes` | uint64 | 客户端声明的 body/blob 字节数；**helper 必须独立重算并要求相等** | 原稿，保留（原稿第 12 节已把"信任 `payload_size`"列为需修正项，正确） |
| `body` | dictionary | 只允许该 kind 定义的键与精确类型 | 原稿，保留 |
| `proto_hash` | data[32] | **新增**：协议定义的内容哈希（opcode 表 + 每个 body 的键与类型 + 全部上限）。helper 与客户端编译期各算一次，不等即拒绝连接 | 本文新增，见 D9 |
| `deadline_ms` | uint64 | **新增**：客户端对该请求的期望上限，0 = 用协议默认。helper 用它决定是否值得开始（例如一个 100 ms 预算的管线编译请求直接拒绝） | 本文新增，见第 5.5 节 |

Reply 固定含 `v`、`kind`、`request_id`、`generation`、`ok`；`ok == true` 时有 `body`，`ok == false` 时有 `error`，**两者不得同时出现**（原稿，保留）。

> **D9**：`proto_hash` 解决的是一个真实的运维问题：helper 与 bundle 是两个文件，升级时可能只换一个（`70-BUILD-PACKAGE.md` 第 6.5 节的安装脚本逐文件 `cp`，中间失败就会不一致）。没有这个检查，不一致表现为"某个字段被静默忽略"，比直接拒绝难查得多。哈希的输入必须是**协议定义本身**（由一个 `build.rs` 从 schema 定义生成），不是二进制哈希 —— 二进制每次构建都变。
>
> **D10**：未知键、错误的 XPC 类型、重复键、过深的字典/数组、`declared_bytes` 不匹配，全部是 `ProtocolError`（原稿，保留）。**补充**：`ProtocolError` 的处置是**关闭整个连接**，不是失败单条请求。理由：协议错误意味着对端的状态机已经和我们不一致，继续服务只会产生更多难解释的失败。
>
> **D11**：**变更请求不自动重试。** XPC 连接中断时该 generation 全部失效（原稿，保留）。这一条必须配一条反面规则：**只读请求（第 1.4 节标"不变成消息"的那些，以及 `WAIT`）也不重试** —— `WAIT` 重试会让"等了多久"这个语义变得不可定义。

### 2.2 消息集与 opcode

原稿第 8.2 节有 16 个 opcode（13 个请求 + 3 个事件），只覆盖 clear 与 triangle。下表按全量能力补齐到 **35 个 opcode（29 个请求 + 6 个事件）**。保留原稿已分配的值，新增项用未占用的值。

| kind | 值 | 方向 | body | reply body | 来源 |
|---|---:|---|---|---|---|
| `HELLO` | 1 | C→H | `min_v`, `max_v`, `client_nonce:data[16]`, `proto_hash` | `client_id`, `generation`, device oid, capability snapshot, limits, `DriverFact` 集合 | 原稿，扩充 reply |
| `CREATE_QUEUE` | 2 | C→H | device oid, queue snapshot | queue oid | 原稿 |
| `IMPORT_SURFACE` | 3 | C→H | device oid, `surface`（Mach right）, `plane`, texture snapshot | texture oid, **两轴 import mode** | 原稿，保留两轴（第 9 节） |
| `CREATE_BUFFER` | 4 | C→H | device oid, buffer snapshot, blob（可空） | buffer oid, `host_backing` 实际取值 | 原稿 `CREATE_BUFFER_BYTES` 扩为全量 buffer |
| `CREATE_LIBRARY` | 5 | C→H | device oid, metallib blob | library oid, function 名清单 | 原稿 |
| `CREATE_FUNCTION` | 6 | C→H | library oid, function snapshot | function oid | 原稿 |
| `CREATE_RENDER_PIPELINE` | 7 | C→H | device oid, function oids, pipeline snapshot, `options` | pipeline oid, reflection oid（可空）, degradation code 集合 | 原稿 |
| `CREATE_COMMAND_BUFFER` | 8 | C→H | queue oid, cb snapshot | cb oid | 原稿 |
| `SUBMIT` | 9 | C→H | cb oid, `queue_seq`, 命令日志 blob | accepted / rejected | 原稿 |
| `WAIT` | 10 | C→H | cb oid, `deadline_ms` | 当前终态或 `Timeout` | 原稿 |
| `DESTROY` | 11 | C→H | 一个 typed oid | 幂等 ack | 原稿 |
| `CANCEL_CLIENT` | 12 | C→H | 空 | ack 后关闭连接 | 原稿 |
| `CREATE_TEXTURE` | 13 | C→H | device oid, texture snapshot | texture oid | **新增** |
| `CREATE_HEAP` | 14 | C→H | device oid, heap snapshot | heap oid, `SizeAndAlign` | **新增** |
| `CREATE_ON_HEAP` | 15 | C→H | heap oid, kind, snapshot, `offset` | resource oid | **新增** |
| `CREATE_COMPUTE_PIPELINE` | 16 | C→H | device oid, function oid, pipeline snapshot, `options` | pipeline oid, reflection oid, `threadExecutionWidth`, `maxTotalThreadsPerThreadgroup`, `staticThreadgroupMemoryLength` | **新增** |
| `CREATE_STATE` | 17 | C→H | device oid, kind ∈ {depth_stencil, sampler, fence, event}, snapshot | state oid | **新增** |
| `CREATE_BINDING` | 18 | C→H | device oid, kind ∈ {icb, argument_encoder, binary_archive, residency_set, visible_function_table, rate_map, log_state}, snapshot | oid + kind 专属回执（如 argument encoder 的 `encodedLength`/`alignment`） | **新增** |
| `REPLACE_REGION` | 19 | C→H | texture oid, region, level, slice, blob, `bytes_per_row`, `bytes_per_image` | ack | **新增** |
| `BUFFER_DID_MODIFY` | 20 | C→H | buffer oid, range | ack | **新增**（也可捎带在 `SUBMIT` 上） |
| `MAP_BUFFER` | 21 | C→H | buffer oid | Mach memory entry + `offset`/`length` | **新增**，见 D8 |
| `EVENT_SIGNAL` | 22 | C→H | event oid, `value` | ack | **新增** |
| `EVENT_HOST_WAIT` | 23 | C→H | event oid, `value`, `deadline_ms` | 到达 / `Timeout` | **新增** |
| `EXPORT_SHARED_EVENT` | 24 | C→H | event oid | 可序列化 token（第 5.6 节） | **新增** |
| `IMPORT_SHARED_EVENT` | 25 | C→H | device oid, token | event oid | **新增** |
| `EXPORT_SHARED_TEXTURE` | 26 | C→H | texture oid | 可序列化 token | **新增** |
| `IMPORT_SHARED_TEXTURE` | 27 | C→H | device oid, token | texture oid | **新增** |
| `ARCHIVE_SERIALIZE` | 28 | C→H | binary archive oid | blob（重定向后的，见 `22-OBJC-DESCRIPTORS.md` R28） | **新增** |
| `QUERY` | 29 | C→H | device oid, query kind, 参数 | 结果 | **新增**：`HELLO` 之后仍需要的少量查询（`pixel_format_capabilities` 逐格式、`heapTextureSizeAndAlign` 等） |
| `EVENT_SCHEDULED` | 100 | H→C | cb oid, `queue_seq`, `completion_value` | — | 原稿 |
| `EVENT_TERMINAL` | 101 | H→C | cb oid, `queue_seq`, `completion_value`, status, error（可空）, **surface seeds**, `WorkCounts` 增量 | — | 原稿，扩充 |
| `EVENT_DEVICE_LOST` | 102 | H→C | generation, 稳定错误 | — | 原稿 |
| `EVENT_DEGRADATION` | 103 | H→C | `code`（稳定字符串 `metal2vulkan-degrade-<kind>`）, `category`, 涉及对象 oid, 原因字段 | — | **新增**，见 D12 |
| `EVENT_LOG` | 104 | H→C | 严重度, 有界文本, 关联 oid | — | **新增**：`MessageSink` 的内容需要进客户端的 `MTLLogState` handler（`22-OBJC-DESCRIPTORS.md` 第 4.28 节） |
| `EVENT_DROPPED_DRAW` | 105 | H→C | cb oid, 第一个被丢弃的 draw 的描述 | — | **新增**，见 D13 |

> **D12**：degradation 必须作为**事件推给客户端**，不只是记在 helper 的日志里。理由：`40-RUNTIME-VULKAN.md` 第 7.1 节要求"每个声明为支持的能力都要附上它在本栈上会触发的 degradation code 列表"，而那张表只有客户端侧知道是哪次调用触发的。节流：每种 `code` 每连接只推一次（对应上游 `DeviceOptions::announce_each` 的默认行为），研发配置下可改为每次都推。
>
> **D13**：`draws_dropped_*` 非零是"画面少了东西但没有任何错误"的唯一信号（`40-RUNTIME-VULKAN.md` 第 7.2 节：对 WindowServer 来说是**静默损坏**）。它必须有自己的事件，不能埋在 `WorkCounts` 里等客户端轮询。事件里带 `CommandBuffer::dropped_draw` 返回的第一个被丢弃的 draw。

### 2.3 Handle 格式与 generation

原稿第 6.3 节定义 `{kind:u64, flags:u64, generation:u64, id:u64}` 四元组，并保留 8 个 kind 值。

**吸收并校正**：

| 项 | 原稿 | 本文 |
|---|---|---|
| 格式 | typed dictionary，4 个 u64 | **保留**。不用 C struct bytes 是对的（XPC 字典有类型检查，struct 有填充和字节序问题） |
| `flags` | v1 必须为 0 | **保留**，并指定用途：bit 0 = `is_shared`（该对象是跨进程导入的）、bit 1 = `is_heap_sub`（该资源在 heap 上）、bit 2 = `is_view`（texture view），其余保留必须为 0 |
| `generation` | 必须等于 connection generation | **保留** |
| `id` | "在 generation 内按 client 单调增加且永不复用" | **更正：`id` 必须是上游的 `ObjectId`**，见 D14 |
| kind 集合 | 8 个（Device/Queue/CommandBuffer/Buffer/Texture/Library/Function/RenderPipeline） | **扩充到 24 个**，见下表 |

> **D14**：`40-RUNTIME-VULKAN.md` 第 3.2 节：*"Metal 用指针标识对象；runtime 另给 `ObjectId`（终身唯一、永不复用）。本项目的 wire 对象表应用它，不用指针。"* 原稿自己维护一个 per-client 单调计数器，这是**重复劳动且更弱** —— 上游的 `ObjectId` 是**终身**唯一（跨 generation 也不复用），原稿的是 generation 内唯一。
>
> **现更正为**：`id` 字段直接存上游 `ObjectId` 的数值。好处有三：
> 1. 不必自己保证不复用；
> 2. helper 侧的查表是 `ObjectId → 我们的 entry`，而上游的 handle 本身 `Hash + Eq` 按身份（`40-RUNTIME-VULKAN.md` 第 3.1 节），所以查表和身份判定用同一个键；
> 3. 诊断时一个 id 永远指向同一个历史对象，不会出现"这个 id 在上一代是别的东西"。
>
> 保留原稿的一条：`id` 必须非零。
>
> `BLOCKED`：**`ObjectId` 是否对本项目创建的每一类对象都可取、以及它的数值表示（是否是 `u64`）未核。** 关闭方式：`cargo doc -p metal2vulkan-runtime` 读 `ObjectId` 与各对象的 `object_id()`。若某类对象没有 `ObjectId`（例如纯值类型包装），该类回退到本项目的 per-client 计数器，并在 kind 表里标注。

全量 kind 表（`INFERRED`，1–8 保留原稿的赋值）：

| kind | 值 | 远端对象（上游类型） | 可重建 |
|---|---:|---|---|
| `Device` | 1 | `Device` | — |
| `Queue` | 2 | `CommandQueue` | 是 |
| `CommandBuffer` | 3 | `CommandBuffer` + adapter 记录 | **否** |
| `Buffer` | 4 | `Buffer` | 看来源（第 6.4 节） |
| `Texture` | 5 | `Texture`（+ IOSurface backing lease） | 看来源 |
| `Library` | 6 | `Library` | 是（客户端持有 metallib） |
| `Function` | 7 | `Function` | 是 |
| `RenderPipeline` | 8 | `RenderPipelineState` | 是 |
| `ComputePipeline` | 9 | `ComputePipelineState` | 是 |
| `DepthStencilState` | 10 | `DepthStencilState` | 是 |
| `SamplerState` | 11 | `SamplerState` | 是 |
| `Heap` | 12 | `Heap` | 是（内容不可重建） |
| `Fence` | 13 | `Fence` | 是 |
| `Event` | 14 | `Event` | 是（计数值丢失） |
| `SharedEvent` | 15 | `SharedEvent` | 是（计数值丢失） |
| `IndirectCommandBuffer` | 16 | `IndirectCommandBuffer` | 是（内容不可重建） |
| `ArgumentEncoder` | 17 | `ArgumentEncoder` | 是 |
| `BinaryArchive` | 18 | `BinaryArchive` | 是 |
| `VisibleFunctionTable` | 19 | `VisibleFunctionTable` | 是 |
| `RateMap` | 20 | `RasterizationRateMap` | 是 |
| `ResidencySet` | 21 | 本项目的簿记对象（`22-OBJC-DESCRIPTORS.md` 第 4.26 节） | 是 |
| `LogState` | 22 | 本项目的簿记对象 | 是 |
| `RenderPipelineReflection` | 23 | 上游反射结果的快照 | 随 pipeline |
| `ComputePipelineReflection` | 24 | 同上 | 随 pipeline |

**kind 校验**（原稿有，保留并明确）：

> **D15**：每一个 handle 参数的解析必须是 `lookup(oid) → entry`，然后 `entry.kind == 期望的 kind`。三道检查缺一不可：
> 1. `generation == 当前 generation` → 否则 `DeviceLost`（不是 `InvalidArgument`：客户端需要知道这是"要重建"而不是"传错了"）；
> 2. `entry.client_id == connection 绑定的 client_id` → 否则 `ProtocolError` 并**关闭连接**（跨 namespace 访问是攻击信号，不是笔误）；
> 3. `entry.kind == 期望` → 否则 `InvalidArgument`。
>
> 顺序必须是 generation → namespace → kind。先查 namespace 再查 kind 可以避免通过 kind 错误推断别的 client 有哪些对象。

### 2.4 `SUBMIT` 的命令日志

原稿第 8.4 节定义了 3 个命令 kind（set pipeline / set vertex buffer / draw primitives），上界 64 个 encoder、65536 条命令。**上界保留**，命令集按全量补齐。

#### 2.4.1 日志的编码

> **D16**：命令日志**不是 XPC 字典数组**，而是**一个 `xpc_data_t` 里的紧凑二进制流**。原稿第 8.4 节把 `encoders` 写成"最多 64 项的 array"，每项一个字典 —— 65536 条命令按字典编码是 65536 次 `xpc_dictionary_create`。**现更正为**：
>
> ```text
> m2v_cmd_log 布局（小端，8 字节对齐）：
>   header:   { magic:u32 = 'M2VL', version:u32 = 1, encoder_count:u32, cmd_count:u32,
>               total_bytes:u64, oid_count:u32, reserved:u32 }
>   oid_table: [u64; oid_count]            ← 日志中引用的全部对象，去重
>   encoders:  [encoder_header; encoder_count]
>              encoder_header = { kind:u32, cmd_offset:u32, cmd_count:u32, pass_snapshot_offset:u32 }
>   pass_snapshots: 紧凑排布的 render/compute/blit pass snapshot（POD）
>   cmds:      [cmd; cmd_count]
>              cmd = { op:u16, len:u16, payload… }   ← len 含 header，必须 8 字节对齐
> ```
>
> 命令里引用对象用的是 **`oid_table` 的下标（u32）**，不是 oid 本身。好处：helper 可以**先一次性解析并校验 `oid_table` 的全部对象**（一次加锁、一次批量 clone），再线性走命令流，中途不再碰对象表。这正是第 7.4 节锁顺序规则需要的形状。
>
> 校验要求：`total_bytes` 必须等于 `xpc_data_t` 的实际长度；每个 `cmd_offset + cmd_count` 必须在界内；每个 `cmd.len` 必须让游标恰好走到下一条命令；走完必须恰好到 `total_bytes`。**任一不符 → `ProtocolError` + 关连接**（这是一个长度字段驱动的解析器，第 7.3 节）。

#### 2.4.2 命令集

`INFERRED`。opcode 空间按 encoder kind 分段，便于一眼看出非法组合：

| 段 | encoder kind | opcode 范围 | 命令数 | 来源 |
|---|---|---|---:|---|
| 0x0000–0x00FF | 通用（任何 encoder） | `SET_LABEL`、`PUSH_DEBUG_GROUP`、`POP_DEBUG_GROUP`、`INSERT_DEBUG_SIGNPOST`、`UPDATE_FENCE`、`WAIT_FOR_FENCE`、`USE_RESOURCE`、`USE_HEAP`、`USE_RESIDENCY_SET` | 9 | 21 分册 |
| 0x0100–0x01FF | render | 约 80 条（`40-RUNTIME-VULKAN.md` 第 3.3 节 `RenderCmd` 节） | ~80 | 上游表 |
| 0x0200–0x02FF | compute | 30 条（上游 `ComputeCmd` 节） | 30 | 上游表 |
| 0x0300–0x03FF | blit | 26 条（上游 `BlitCmd` 节） | 26 | 上游表 |
| 0x0400–0x04FF | resource state | sparse 相关 | — | **全部 B**（macOS 不可用） |
| 0x0500–0x05FF | acceleration structure | build / refit / copy | — | **全部 B** |
| 0x0600–0x06FF | ICB 录制（`MTLIndirectRenderCommand` / `MTLIndirectComputeCommand`） | 上游 `IcbRenderCmd` / `IcbComputeCmd` 节 | — | 上游表 |

> **D17**：**opcode 表不手写、不抄。** 它必须由一个生成器从上游 `docs/RUNTIME-PORTING.md` 的 TSV（`40-RUNTIME-VULKAN.md` 第 0 节：那份表由脚本生成并有 CI 校验）派生，输出 Rust 的 `enum` + ObjC 的 `#define` + `proto_hash` 的输入。理由：那张表约 400 行且上游仍在演进，手抄会腐烂，而腐烂的表现是"某条命令被静默忽略"。
>
> **D18**：每条命令的 payload 字段必须是**已经 checked-convert 过的**。`NSUInteger` → `u32` 的收窄发生在 ObjC 侧记录日志时（`22-OBJC-DESCRIPTORS.md` R16），不是在 helper 侧。好处：越界在客户端进程里就变成 Metal 风格的失败（assert / 命令缓冲记录错误），helper 不必为客户端的 bug 产生一条 `ProtocolError`。
>
> **D19**：**private primitive type 必须原样传递。** `MTLPrimitiveType` 的 5–8 是合法值，9 不是合法值但 Metal 接受它并让命令缓冲以 GPU 方式失败（`40-RUNTIME-VULKAN.md` 第 3.2 节）。因此 `DRAW_PRIMITIVES` 的 `primitive` 字段**不在 ObjC 侧校验**，由 helper 调上游 `DrawPrimitiveType::from_raw` 决定。这是第 2.4 节里唯一的"不在客户端侧校验"的例外，必须在代码里注释说明为什么。

#### 2.4.3 D6 的代价：encoder 上的同步查询

把全部命令都变成日志之后，encoder 上**返回值不是 void** 的 selector 无法本地回答。全量清单与处置（`INFERRED`）：

| selector | 返回 | 处置 |
|---|---|---|
| `encodeStartIf:` / `encodeStartWhile:` / `encodeStartDoWhile` | `BOOL` | **必须按 Metal 返回 `NO`**（`40-RUNTIME-VULKAN.md` 第 3.2 节明确：上游有完整实现，这三个按 Metal 返回 `NO` 而非报错）。本地返回 `NO`，同时把命令记进日志 |
| `MTLIndirectCommandBuffer` 的 SPI getter（读回已录制的间接命令） | 各种 | 走 `QUERY`（同步消息）。上游有 `ExecutedCommands` / `RecordsRead` / `add_executed_commands_handler`（`40-RUNTIME-VULKAN.md` 第 2.2 节） |
| `MTLArgumentEncoder.constantDataAtIndex:` | `void *` | argument encoder 的目标 buffer 必须是**客户端可写映射**（D8），`setArgumentBuffer:offset:` 之后客户端直接在映射里写。helper 只需要知道 layout，layout 在 `CREATE_BINDING` 的回执里一次性给全 |
| `MTLComputeCommandEncoder` 上无返回值命令 | void | 无影响 |
| `dispatchThreadgroups:` 系 | void | 无影响 |

> **D20**：`MTLArgumentEncoder` 是 D6 的真正难点。它的用法是"把 buffer 的一段映射出来，让 encoder 往里写描述符"。如果 buffer 不可映射，整条 argument buffer 路径就得退化成每个 `setBuffer:offset:atIndex:` 一次 IPC —— 那是不可接受的。因此：
> - **argument buffer 必须走 D8 的共享映射**；
> - helper 在 `CREATE_BINDING` 的回执里给出 `encodedLength`、`alignment`、以及**每个 index 的字节偏移与字段布局**（由上游的 `ArgumentEncoder` 提供）；
> - 客户端侧的 `MTLArgumentEncoder` proxy 用这张布局表自己往映射里写；
> - 写进去的"描述符"的内容是 **`ResourceId`**（上游 `ResourceId` / `ResourceIdKind` / `IdPlacement`，`40-RUNTIME-VULKAN.md` 第 2.3 节），而 `IdPlacement` 正是上游为"guest 自有编号"提供的下压机制。
>
> `BLOCKED`：上游 `ArgumentEncoder` 是否暴露足以让外部写入的布局信息**未核**。关闭方式：读其 rustdoc。若不暴露，argument buffer 路径在切分后退化为 B，必须在 `60-CAPABILITY-MATRIX.md` 记为已知损失。

### 2.5 Blob：inline / OOL 分界

吸收原稿第 8.3 节，保留 schema 的四个键并修正一处。

| 键 | XPC 类型 | 规则 | 来源 |
|---|---|---|---|
| `transport` | uint64 | 0 = `inline_data`，1 = `shared_memory_ro`，**2 = `shared_memory_rw`（新增，给 D8 的映射）** | 原稿，扩充 |
| `length` | uint64 | 必须等于实际 mapped/data 长度 | 原稿，保留 |
| `sha256` | data[32] | **见 D21** | 原稿，修正 |
| `data` | data | 仅 transport 0；**上限 256 KiB**（原稿 1 MiB，见 D22） | 原稿，修正上限 |
| `memory` | XPC shared-memory 对象 | transport 1/2；helper 按 transport 决定映射保护 | 原稿，保留 |

> **D21**：原稿写"helper 在解析前重算 sha256；不匹配拒绝"。**这一条在安全上没有意义，必须明确它的真实用途。** 客户端是不可信的，它可以同时给出一致的数据和哈希；哈希不防御任何攻击。它唯一的价值是**检测传输/映射错误**，以及**给缓存当键**。
>
> **现更正为**：`sha256` 是**可选的缓存键与完整性校验**，不是授权检查。规则：
> - transport 0：`sha256` 可省。给了就校验（检测 bug），不给也接受。
> - transport 1/2：`sha256` **必须给**，因为共享内存在 helper 读的过程中客户端仍可能改写（TOCTOU）。helper 的处置是：**先把共享内存整段复制进 helper 自己的私有内存，再对副本算哈希并解析**。哈希是对副本算的，所以它校验的是"我复制下来的这一份"，而不是"客户端现在那一份"。
> - **绝不原地解析共享内存里的结构化数据**（metallib、命令日志）。这是第 7.3 节的硬规则。
>
> **D22**：原稿的 inline 上限是 1 MiB，与"逻辑 control payload 1 MiB/request"相等，等于一个 inline blob 就能占满整条消息。**现更正为 inline 上限 256 KiB**，理由：XPC 消息是要整块序列化与拷贝的，1 MiB 的字典消息会在 WindowServer 的主线程上产生可见停顿。256 KiB 覆盖绝大多数 metallib（典型合成 shader 库在数十 KiB 量级）与全部 label / 小顶点数据。
>
> **D23**：`> 256 KiB` 必须 OOL。原稿把 OOL 路径标 `BLOCKED`（目标 transfer API / entitlement 未证），并因此要求 v1 fixture 把 metallib 控制在 1 MiB 内。**该约束在全量规格下不成立** —— 真实客户端的 metallib 会超。因此 OOL 路径从"可选"变成**切分的前置条件**，与 D8 一起列为 Gate H-2（第 8.4 节）。
>
> **在 OOL 可用之前：第一版同进程，根本没有 blob**（指针直接传，见第 1.2 节）。这正好说明同进程优先的设计是对的。

### 2.6 固定上限

吸收原稿第 8.5 节的 18 项，保留大部分，修正 3 项，新增 9 项。

| 项目 | 原稿 | 本文 | 说明 |
|---|---:|---:|---|
| 逻辑 control payload | 1 MiB/request | **1 MiB** | 保留 |
| inline blob | 1 MiB | **256 KiB** | D22 |
| 字典嵌套深度 | 4 | **4** | 保留 |
| 字典键数 | 128/request | **128** | 保留 |
| 字符串 / 错误文本 | 4 KiB；label 256 B | **4 KiB / 256 B** | 保留 |
| metallib | 64 MiB；> 1 MiB 必须 OOL | **64 MiB；> 256 KiB 必须 OOL** | 上限保留，分界随 D22 |
| 单 buffer 创建 | 1 GiB；> 1 MiB 必须 OOL | **1 GiB；> 256 KiB 必须 OOL** | 同上。原稿第 12 节已指出这是协议 hard cap 而非可达值，正确 |
| IOSurface 分配 | 1 GiB | **1 GiB** | 保留 |
| surface 宽/高 | 各 16384 | **各 16384** | 保留 |
| encoder 数 | 64/command buffer | **64** | 保留 |
| 命令数 | 65536/command buffer | **65536** | 保留 |
| 未完成 CB | 64/queue，256/client | **64/queue，256/client** | 保留。64 与上游每队列默认一致（`KNOWN`） |
| 活跃远端对象 | 65536/client | **65536/client** | 保留 |
| 计入的分配总量 | 2 GiB/client | **2 GiB/client** | 保留 |
| 同步管线编译 | 30 s | **见第 5.5 节的分级** | **修正**：30 s 与上游的 4.5+4.5 s 和 guest 的 10 s FIFO 检查不协调 |
| queue 序号间隙 | 10 s | **10 s** | 保留 |
| liveness hard deadline | 60 s | **60 s** | 保留 |
| 命令日志字节数 | — | **16 MiB/command buffer** | **新增**：65536 条命令 × 最大单条 payload 需要一个独立的字节上限 |
| 日志中的 oid 表 | — | **4096/command buffer** | **新增** |
| pass 中的 color attachment | — | **`min(maxColorAttachments, MAX_COLOR_ATTACHMENTS)`** | **新增**（`22-OBJC-DESCRIPTORS.md` R6） |
| 单次 `REPLACE_REGION` 字节数 | — | **64 MiB** | **新增** |
| 每 client 的共享映射数 | — | **1024** | **新增**（D8 的映射要计数，否则是 VM 耗尽面） |
| 每 client 的共享映射总字节 | — | **1 GiB**（计入 2 GiB 总量） | **新增** |
| 每 client 的并发 in-flight 请求 | — | **64** | **新增**：防止一个 client 用并发请求挤占 helper 的工作队列 |
| 每 client 的请求速率 | — | **4096/s 的令牌桶，突发 8192** | **新增** |
| 每 client 的 library 数 | — | **1024** | **新增**：每个 library 都带翻译结果，是真实的内存成本 |
| 每 client 的 pipeline 数 | — | **4096** | **新增** |
| 单个 pipeline 编译的翻译预算 | — | **交给上游 `Error::Budget`** | **新增**：上游有翻译期限（`40-RUNTIME-VULKAN.md` 第 7.3 节），不自己造 |

> **D24**：配置只能**降低**这些上限，不能由客户端请求提高（原稿，保留）。
>
> **D25**：全部乘加用 checked 算术；任何溢出在分配、映射或调上游之前返回 `InvalidArgument`（原稿，保留）。
>
> **D26**：上限必须进 `proto_hash`（D9）。否则客户端和 helper 对上限的理解不一致时，表现是"大于某个尺寸的请求莫名失败"。

---

## 3. 对象表

### 3.1 Per-client namespace

> **D27**：helper 侧的对象表是 **per-connection** 的，不是全局的。表的键是 `ObjectId`，值是一个 entry：
>
> ```rust
> struct Entry {
>     kind: Kind,                   // 第 2.3 节的 24 个值之一
>     handle: UpstreamHandle,       // 上游 handle 的一个 clone（Device/Buffer/Texture/…）
>     deps: SmallVec<[ObjectId; 4]>,// 该对象强依赖的对象（texture → 其 backing buffer）
>     quota: QuotaCharge,           // 第 3.5 节
>     created_at: Instant,
>     label: BoundedString,         // ≤ 256 B，只为诊断
> }
> ```
>
> `client_id` **不在 entry 里**，因为表本身就属于某个 connection。这比在 entry 里存 `client_id` 再比较更难出错：没有"忘了比较"的可能。
>
> **D28**：`client_id` 由 helper 在 `accept` 时分配并与 **XPC audit token** 绑定：
>
> ```rust
> let token = xpc_connection_get_audit_token(conn);   // 不可伪造，内核填充
> let client = ClientIdentity {
>     pid:        audit_token_to_pid(token),
>     euid:       audit_token_to_euid(token),
>     pidversion: audit_token_to_pidversion(token),   // 防 pid 复用
>     csflags:    /* csops(CS_OPS_STATUS) */,
> };
> ```
>
> **helper 永不使用请求里的 `client_id` 选择 namespace**（原稿第 8.1 节的该条成立，保留）。请求里的 `client_id` 只用于一次相等性检查；不等就是 `ProtocolError` + 关连接。
>
> `audit_token_to_pidversion` 是必需的：pid 会被复用，`(pid, pidversion)` 才唯一。
>
> `BLOCKED`：**25G325 上 WindowServer 的 audit token 中 `euid` 与 `csflags` 的实际取值未实测。** 这决定第 7.6 节的准入策略能不能写成白名单。关闭方式：helper 启动后把第一批连接的 token 全量落盘（Gate H-1）。

### 3.2 Object ID 的分配与"永不复用"

> **D29**：**不自己分配 ID。** 用上游 `ObjectId`（`40-RUNTIME-VULKAN.md` 第 3.2 节：终身唯一、永不复用）。这是对原稿第 6.3 节的更正，理由见 D14。
>
> 分配流程：
> 1. 创建消息到达 → 校验 snapshot → 调上游创建方法，拿到一个上游 handle；
> 2. 从 handle 取 `ObjectId`；
> 3. 在对象表里插入 entry（**若该 ID 已存在 → `InternalError` 并关连接**：上游承诺不复用，若复用则我们的假设已破，继续运行会把两个对象混在一起）；
> 4. 回执里返回 `{kind, flags, generation, id}`。
>
> **D30**：上游的对象 handle 是**廉价克隆值**，`Clone` = retain、`Drop` = release，相等即同一对象，`Send + Sync`（`40-RUNTIME-VULKAN.md` 第 5 节）。因此：
> - 同一上游对象被两次取到（例如上游对同一物理设备 + 相同 options 返回同一个 `Device`）会得到**同一个 `ObjectId`**。对象表的插入必须是"已存在则增加外部租约计数"，不是"插入新 entry"。
> - 这正是 Metal 的语义（每 GPU 一个 `MTLDevice`）。
> - 连带约束（`40-RUNTIME-VULKAN.md` 第 5 节）：**本项目只会有一个设备，必须保证 `DeviceOptions` 恒定**，否则会意外建出第二个 `Device`。`DeviceOptions` 的固定配置表在 `40-RUNTIME-VULKAN.md` 第 6.6 节，helper 必须原样使用并把它的哈希写进 capability snapshot。

### 3.3 跨 namespace 隔离

> **D31**：两个 client 的对象表之间**没有任何共享路径**，除了三处显式的、必须各自授权的桥：
>
> | 桥 | 机制 | 授权 |
> |---|---|---|
> | IOSurface | `IMPORT_SURFACE` 的 Mach right | 右本身就是授权（第 7.5 节） |
> | `MTLSharedEvent` | `EXPORT_SHARED_EVENT` 产出 token，`IMPORT_SHARED_EVENT` 消费 | token 是 128 位随机数 + HMAC，不是对象 ID。见第 5.6 节 |
> | `MTLSharedTextureHandle` | 同上 | 同上 |
>
> **D32**：对象表的 `deps` 只能指向**同一个表里**的 ID。跨表引用（例如导入别人的 shared texture）在导入侧**建一个新的本地 entry**，`flags` 的 `is_shared` 位置 1，`deps` 为空。导入侧的生命周期与导出侧完全独立 —— 这是 Metal 的语义（`MTLSharedTextureHandle` 解出来的是一个新的 `MTLTexture`）。
>
> **D33**：诊断与日志必须**按 client 分文件或分标签**。一个 client 的 oid 不得出现在另一个 client 可读的任何输出里，否则就把"对方有哪些对象"泄出去了。

### 3.4 销毁与幂等

吸收原稿第 6.1、6.2、6.3 节。这一组原稿做得对，保留并明确三处。

> **D34**：`DESTROY` / `m2v_release` **只撤销客户端的外部租约**，不强制释放上游对象（原稿第 6.2 节，保留）。实际释放发生在"外部租约 + 全部内部引用"都归零时 —— 内部引用来自在途命令缓冲持有的 handle clone、`deps` 反向引用、以及上游自己的 `KeepAlive`。
>
> **D35**：`DESTROY` 对一个**曾签发但已不存在**的 ID 返回成功（原稿，保留）。对一个**从未签发过**的 ID 返回 `InvalidArgument`。区分方式：维护一个 per-client 的"已签发 ID 的高水位 + 已销毁 ID 的紧凑集合"。由于 `ObjectId` 终身不复用（D29），"从未签发" = 不在已签发集合里。
>
> **D36**：`dealloc` 只运行一次，**幂等性属于 helper 的 `DESTROY` 处理，不属于重复调用 `dealloc`**（原稿第 6.1 节，保留。该条是对基线"dealloc 必须幂等释放远端对象"的正确修正）。
>
> **D37**：**父对象释放不使子对象失效。** 原稿第 6.2 节已指出基线的"父对象销毁不得留下可提交子对象"与 retain 语义冲突，正确。保留：child 强持有 parent；只有 generation 变化、连接失效或明确的 device loss 才整棵树失效。
>
> **D38**：**`CommandBuffer` 的 entry 在终态事件发出且回调取走之后才可移除。** 这是唯一一个"helper 侧生命周期长于客户端租约"的 kind。实现上给它一个额外的内部引用，由终态投递路径释放。

### 3.5 配额

原稿第 8.5 节有 4 项与对象表相关的配额（活跃对象 65536、未完成 CB 64/queue + 256/client、分配总量 2 GiB）。保留并补齐成一张可执行的表。

| 资源 | 配额 | 计费时点 | 超限时的错误 |
|---|---:|---|---|
| 活跃远端对象总数 | 65536/client | 创建成功时 +1，entry 移除时 −1 | `OutOfMemory` |
| 其中 library | 1024/client | 同上 | `OutOfMemory` |
| 其中 pipeline（render + compute） | 4096/client | 同上 | `OutOfMemory` |
| 其中 command buffer（未完成） | 64/queue，256/client | `CREATE_COMMAND_BUFFER` 时 +1，终态事件投递后 −1 | `OutOfMemory`（**不是** `Timeout`：客户端应当等待而不是重试） |
| 设备内存计费总量 | 2 GiB/client | buffer / texture / heap 创建成功时 += 其 `SizeAndAlign.size` | `OutOfMemory` |
| 共享映射数 | 1024/client | `MAP_BUFFER` 成功时 +1 | `OutOfMemory` |
| 共享映射总字节 | 1 GiB/client（计入 2 GiB） | 同上 | `OutOfMemory` |
| 并发 in-flight 请求 | 64/client | 请求入队时 +1 | `ProtocolError`（客户端违反了自己应当遵守的窗口） |
| 请求速率 | 4096/s 令牌桶，突发 8192 | 每请求 −1 token | 桶空时**延迟服务**（不拒绝），持续 10 s 空则 `ProtocolError` + 关连接 |

> **D39**：**配额是 per-client，但 helper 还需要一个全局闸门。** 一个 client 用光自己的 2 GiB 不应该让别的 client 失败，但 N 个 client 各 2 GiB 会把宿主打爆。因此：
> - 全局设备内存上限 = `min(DeviceProperties 的可用内存, 物理内存 × 0.5)`；
> - 全局用量到达 90% 时，**新的创建请求按 client 的当前用量从大到小开始拒绝**（最大的先失败），返回 `OutOfMemory`；
> - 到达 100% 时全部创建失败。
>
> 为什么"最大的先失败"：这让单个失控的 client 自己承担后果，而不是让一个只用 10 MB 的 WindowServer 因为别人失控而掉帧。`INFERRED`。
>
> **D40**：配额计费必须用 checked 算术，且**减法必须是 saturating**。一个因 bug 导致的重复退费会把计数器绕回极大值，从而永久拒绝服务 —— 比泄漏难查得多。

### 3.6 锁顺序

吸收原稿第 7 节（该节的规则是对的），补一条。

> **D41**：固定锁顺序：**connection state → queue sequencer → command-buffer state → callback list**（原稿，保留）。对象表的查表必须**在锁内 clone、立刻解锁**，不得在持锁时进入上游 runtime、XPC send 或用户代码（原稿，保留 —— 上游 handle 是廉价克隆值，这个做法是可行的）。
>
> **D42**：**新增：对象表的锁在 `SUBMIT` 路径上只加一次。** 第 2.4.1 节的 `oid_table` 设计使这成为可能：解析 `oid_table` 时加一次锁、批量校验并 clone 全部引用对象、解锁；之后走命令流时只用已 clone 的 handle。没有这一条，65536 条命令意味着 65536 次加锁。

---

## 4. 错误映射

三段：上游 typed `Error` → 稳定 wire error → `NSError`。

### 4.1 稳定 wire error

吸收原稿第 10.5 节的 8 个 category，保留取值，补 3 个。

| category | 值 | 含义 | `retryable` |
|---|---:|---|---|
| `InvalidArgument` | 1 | 客户端误用。参数越界、kind 不符、状态不允许 | false |
| `Unsupported` | 2 | 本栈不具备该能力 | false |
| `OutOfMemory` | 3 | 内存或配额耗尽 | **true**（释放一些对象后可能成功） |
| `CompileFailed` | 4 | 库解析、着色器翻译或管线创建失败 | false |
| `DeviceLost` | 5 | 设备或 helper 失效，整代作废 | false（但重建新代后可重试） |
| `Timeout` | 6 | 超过 deadline | **true** |
| `ProtocolError` | 7 | envelope / schema / 版本 / namespace 违规 | false（且关连接） |
| `InternalError` | 8 | 其他被捕获的失败 | false |
| `Stopped` | 9 | **新增**：`Unproven` 触发的"停止 guest"，见 D45 | false |
| `WouldDeadlock` | 10 | **新增**：上游 `WaitWouldDeadlock`，见 D46 | false |
| `NotProvisioned` | 11 | **新增**：启动期致命错误（loader 未找到、驱动配置不可用、缓存目录不可写）。与 `Unsupported` 分开，因为这是**部署问题**而不是能力问题 | false |

> **D43**：**原稿把 `Unproven` 映射到 `Unsupported`（第 10.5 节 category 2 那一行），这是错的。** 现更正，见 D45。
>
> **D44**：wire error 字典固定为 `{ category:u64, source_kind:string<=128, source_code:i64, message:string<=4096, retryable:bool, needs:string<=512 }`。原稿有前五项，**新增 `needs`**：`40-RUNTIME-VULKAN.md` 第 7.3 节要求"capability 查询在返回 false 时必须能回答缺什么"，而那个信息来自上游 `Unsupported::needs`。不传它就只能在 helper 的日志里有，客户端侧的 capability 报告拿不到。
>
> **D45**：**`Error::Unproven` 必须映射到 `Stopped`，不是 `Unsupported`。** 上游的语义是"无法证明纯 Metal 的答案"，建议是**停止 guest 并命名问题，不得猜**（`40-RUNTIME-VULKAN.md` 第 2.9 节与第 7.3 节第 4 条）。映射到 `Unsupported` 会让客户端以为"这个功能不支持"，于是走它自己的回退路径，**而回退路径基于一个我们已经知道可能是错的答案**。
>
> 具体处置：
> 1. helper 侧：把 `Unproven` 的 `问题名`（上游给的类型化字段）写进结构化日志与 `90-EVIDENCE-INDEX.md` 的证据目录；
> 2. 发 `EVENT_DEVICE_LOST`，`category = Stopped`，`message` 含问题名；
> 3. 把当前 generation 整代作废；
> 4. **不自动重启 helper**（第 6.5 节的 supervisor 策略对 `Stopped` 的处置是"停止并等人"）。自动重启会在同一条路径上再次撞上同一个 `Unproven`，变成崩溃循环。
> 5. 客户端侧：全部在途命令缓冲进 `Error`，`NSError` 的 domain 是 `GuestMetalBridgeErrorDomain`、code 为 9。
>
> `Stopped` 与 `DeviceLost` 必须分开：`DeviceLost` 是"重建就好"，`Stopped` 是"有一个我们不理解的语义，继续跑会产出错的东西"。研发期这两者的处置完全不同。
>
> **D46**：**`Error::WaitWouldDeadlock(DeadlockCause)` 必须立即返回 `WouldDeadlock`，绝不挂起。** 上游的设计是"会死锁的等待被直接拒绝而非挂起"（`40-RUNTIME-VULKAN.md` 第 2.9 节与第 5 节）。
>
> 处置的硬要求：
> 1. helper 侧：`WAIT` 立刻回 `WouldDeadlock`，不进任何等待原语；
> 2. 客户端侧：`waitUntilCompleted` **不能挂住 WindowServer**。它没有返回值，所以唯一的出路是**先把该 command buffer 置为终态 `Error`**（`category = WouldDeadlock`），再让 `waitUntilCompleted` 返回（第 5.4 节）；
> 3. `DeadlockCause` 必须进日志。它是本项目自己的 bug 的指示器（Metal 客户端很难自己构造出死锁等待），不是客户端的错。

### 4.2 上游 `Error` 全量 variant 的映射

`KNOWN`（variant 清单取自 `40-RUNTIME-VULKAN.md` 第 2.9 节）。上游 `Error` 是 **non-exhaustive** 枚举，因此必须有显式 default。

| 上游 variant | wire category | `NSError` 行为 | 补充动作 |
|---|---|---|---|
| `Invalid(Invalid)` | `InvalidArgument` | **按 Metal 行为：assert / abort / 返回 nil**。`Invalid` 的 `call` 给方法名、`problem` 给类型化 `Problem` | `problem` 进 `source_kind`。若 Metal 在该输入上会结束进程，则我们也结束 —— 第一版同进程时这就是客户端进程 |
| `Nil(Nil)` | `InvalidArgument` | 返回 nil，**不填 `NSError`** | — |
| `MetalError(MetalError)` | 按 `MetalError` 的 domain/code 决定 | **构造等价 `NSError`**：用 Metal 自己的 domain、code、描述，**不是** `GuestMetalBridgeErrorDomain` | 见 D47 |
| `Unsupported(Unsupported)` | `Unsupported` | 返回 nil + `NSError` | `feature` → `source_kind`，`needs` → `needs`。进 capability 报告，对应查询返回 false |
| `NotImplemented(RuntimeGap)` | `Unsupported` | 返回确定错误，**不得伪造成功** | `source_kind = "runtime-gap"`。这是上游的待办，与设备能力无关，必须在报告里分开计数 |
| `AppleOnly(AppleOnly)` | `Unsupported` | 返回确定错误 | `source_kind = "apple-only"` |
| `Unproven(Unproven)` | **`Stopped`** | 见 D45 | **停止 guest 并命名问题** |
| `Compile(...)` | `CompileFailed` | 编译 `NSError`（Metal 的 `MTLLibraryErrorDomain` / `MTLBinaryArchiveDomain` 语义） | 编译日志按第 7.7 节脱敏后放 `userInfo` |
| `Budget` | `CompileFailed` | 同上，`message` 说明超预算 | 翻译期限（上游 1 个 variant） |
| `LimitExceeded(Limit)` | `Unsupported` | 返回 nil + `NSError` | 14 个 variant，`basis = ours`；进"比 Metal 严格"的清单（`40-RUNTIME-VULKAN.md` 第 7.3 节） |
| `RateMap(UnpinnedCompile)` | `Unsupported` | 同上 | 5 个 variant |
| `BindError(...)` | `Unsupported` 或 `OutOfMemory` | 同上 | 9 个 variant，全部 `basis = device`；若是"超设备限额"则 `OutOfMemory` 更准确 |
| `OutOfMemory` | `OutOfMemory` | `NSError`，`retryable = true` | — |
| `MemoryKind(...)` | `OutOfMemory` | 同上 | 细分类型，进 `source_kind` |
| `SamplerLimit(...)` | `OutOfMemory` | 同上 | Vulkan 的 `maxSamplerAllocationCount` 远小于 Metal 的实际用量，必须是 OOM 而不是 Unsupported |
| `DeviceLost` | `DeviceLost` | **命令缓冲进 `DeviceLost`**，`EVENT_DEVICE_LOST`，整代作废 | 第 6 节 |
| `Vulkan` / `VkResultCode` / `FailureOrigin` | `InternalError` | `NSError` | `VkResultCode` 进 `source_code`，`FailureOrigin` 进 `source_kind` |
| `NoDevice` | `NotProvisioned` | **启动期致命** | `DeviceOptions::kinds` 只许 CPU，无合格设备就是部署错（`40-RUNTIME-VULKAN.md` 第 6.3 节） |
| `LoaderNotFound(LoaderNotFound)` | `NotProvisioned` | 启动期致命 | `tried` 的全部路径进日志（`40-RUNTIME-VULKAN.md` 第 6.4 节） |
| `DriverSetting(DriverSetting)` | `NotProvisioned` | 启动期致命，**不降级继续**（`40-RUNTIME-VULKAN.md` 第 6.5 节） | — |
| `ShaderCache(...)` | `NotProvisioned` | 启动期致命 | 缓存目录不可建或不可写 |
| `InstanceApiVersion` / `InstanceExtensionRequired` / `ExtensionFeature` | `NotProvisioned` | 启动期致命 | 本项目要求 Vulkan ≥ 1.2 + `timelineSemaphore` + `VK_EXT_external_memory_host` |
| `WaitWouldDeadlock(DeadlockCause)` | **`WouldDeadlock`** | 见 D46 | **不得挂住 WindowServer** |
| `TimedOut` | `Timeout` | `NSError`，`retryable = true` | — |
| `CommandBufferError` | 看内含原因 | 命令缓冲终态 `Error` | — |
| `FailedPipeline` / `PipelineCreationCause` / `FailedState` | `CompileFailed` | 返回 nil + `NSError` | `PipelineCreationCause` 进 `source_kind` |
| `BinaryArchiveError` / `BinaryArchiveMiss` / `ArchivedPipeline` | `CompileFailed` | 同上 | `BinaryArchiveMiss` 在 `FailOnBinaryArchiveMiss` 选项下才是错误，否则是正常的 miss |
| `DynamicLibraryError` | `Unsupported` | 同上 | 链接使用被上游拒绝 |
| `MeshRecordsOverflow` / `TessellationRecordsOverflow` | `Unsupported` | 同上 | mesh / tessellation 路径的上限 |
| `EncoderCall` / `Problem` | `InvalidArgument` | 按 `Invalid` 处置 | `Problem` 有 64 + 164 个细分 variant；`basis = metal-takes` 的 28 条必须标为"比 Metal 严格" |
| `FunctionTableProblem` / `ArgumentEncoderProblem` / `RenderPassProblem` / `DrawProblem` / `RenderStateProblem` / `CopyProblem` / `MipmapProblem` / `ViewProblem` / `RebindProblem` / `BufferTextureProblem` / `TextureProblem` / `HeapProblem` / `SparseProblem` / `VisibilityProblem` / `IndirectCommandBufferProblem` / `BinaryFunctionProblem` / `RequiredThreadsProblem` / `WrappedImageProblem` / `WrappedBufferProblem` / `PlacementConflict` / `SemaphoreProblem` | `InvalidArgument` | 同上 | 每个 problem 枚举值都有稳定的 `source_kind` 字符串 |
| **其他（non-exhaustive 的新 variant）** | `InternalError` | `NSError` | **必须有显式 `_ => InternalError` 分支，不得 panic、不得让 Rust unwind 穿过 FFI**（原稿第 10.5 节该条成立，保留） |

> **D47**：`MetalError` 这一行是全表里唯一**不**用 `GuestMetalBridgeErrorDomain` 的。理由：`MetalError` 的语义是"纯 Metal 在这个输入上也会返回 nil 并填一个带 Metal domain/code 的 `NSError`"。如果我们把它换成自己的 domain，客户端里那些 `if ([err.domain isEqual:MTLLibraryErrorDomain] && err.code == MTLLibraryErrorCompileFailure)` 的分支就全都走不进去 —— 我们会把一个 Metal 客户端已经能正确处理的错误变成一个它不认识的错误。
>
> **D48**：**禁止读 `Error` 的消息文本做分支**（`40-RUNTIME-VULKAN.md` 第 3.2 节明确要求）。只匹配 variant。`message` 字段只进日志与 `NSError.localizedDescription`。
>
> **D49**：`source_kind` 必须是**稳定字符串**。degradation 侧上游已经给了稳定形式（`Degradation::code()` → `metal2vulkan-degrade-<kind>`，`40-RUNTIME-VULKAN.md` 第 7.1 节）；错误侧上游没有给，因此本项目必须自己维护一张 `variant → 稳定字符串` 的表，**由生成器从上游的枚举定义派生**（同 D17 的理由）。

### 4.3 `NSError` 的构造

> **D50**：domain 固定 `GuestMetalBridgeErrorDomain`，code 用第 4.1 节的 category 值（原稿，保留）。例外是 D47 的 `MetalError`。
>
> **D51**：`userInfo` 的内容白名单（原稿第 10.5 节说"保存 bounded `source_kind` 和 request/submission IDs，不保存完整 shader 或像素"，**成立并细化**）：
>
> | 键 | 内容 | 上限 |
> |---|---|---|
> | `NSLocalizedDescriptionKey` | 人读的一句话，**不含客户端数据** | 256 B |
> | `M2VSourceKind` | D49 的稳定字符串 | 128 B |
> | `M2VSourceCode` | `NSNumber`，上游的细分 code | — |
> | `M2VNeeds` | `Unsupported::needs` 的稳定形式 | 512 B |
> | `M2VRequestId` / `M2VSubmissionId` / `M2VGeneration` | `NSNumber` ×3 | — |
> | `M2VDegradeCodes` | 该次调用触发的 degradation code 数组 | 32 项 |
> | `NSUnderlyingErrorKey` | 仅 `MetalError` 路径下的原始 Metal 错误 | — |
>
> **不得出现**：shader 源码或 metallib 字节、像素数据、客户端给的 label 之外的任何字符串、文件路径、`Vk*` handle 的数值、helper 的内存地址。
>
> **D52**：`NSError **` 出参的规则（原稿第 4 节，保留）：成功时**不写**；失败且指针非空时写入一个 **autoreleased** `NSError`，对象返回 `nil`。失败且指针为 `NULL` 时只返回 `nil`。

---

## 5. 完成语义

### 5.1 Command buffer 状态机

吸收原稿第 10.1 节。该节的状态机是对的（它本身就是对基线的一次正确修正），**保留并补一个状态**。

```text
                      NotEnqueued
                           │ commit 被本地接受（snapshot 冻结、日志封闭、queue_seq 分配）
                           ▼
                      Committed
                           │ SUBMIT 被 helper 接受（校验通过、上游 encoder 已重放）
                           ▼
                      Committed（wire 上不另设状态）
                           │ 上游 scheduled handler
                           ▼
                       Scheduled
                           │ 上游 completed handler + IOSurface 可见性收尾
            ┌──────────────┴──────────────┐
            ▼                             ▼
        Completed                       Error
```

| 事实 | 标签 | 来源 |
|---|---|---|
| 上游 `CommandBufferStatus` 定义 0..5 为 NotEnqueued / Enqueued / Committed / Scheduled / Completed / Error，但 runtime **没有 `enqueue`**，因此本协议不产生 `Enqueued` | `KNOWN` | 原稿第 10.1 节；`40-RUNTIME-VULKAN.md` 第 2.2 节 `CommandBufferStatus` |
| 状态**只前进**；`Completed` 与 `Error` 互斥终态 | `KNOWN`（上游保证，`40-RUNTIME-VULKAN.md` 第 5 节） | 原稿，保留 |
| completion handler **只调用一次** | `KNOWN`（同上） | 原稿，保留 |
| 内部 `RecordingPoisoned` 对客户端报告 `NotEnqueued`；`commit` 时直接成为终态 `Error`，不向 Vulkan 提交 | `INFERRED` | 原稿，保留 |
| 重复 / 乱序的终态事件由 compare-and-swap 忽略并记协议诊断 | `INFERRED` | 原稿，保留 |
| `EVENT_TERMINAL` 先于 `EVENT_SCHEDULED` 到达时，客户端的事件定序器先发布 `Scheduled` 再发布终态；回调仍只运行一次 | `INFERRED` | 原稿，保留 |

> **D53**：**新增一个仅 helper 侧可见的状态 `Accepted`**，位于 `Committed` 与 `Scheduled` 之间，表示"`SUBMIT` 已校验通过、上游 encoder 已重放、`CommandBuffer::commit` 已调用"。它不在 wire 上暴露（客户端看到的仍是 `Committed`），但 supervisor 的超时分级需要区分"卡在校验/重放"与"卡在 GPU 执行"（第 6.6 节）。
>
> **D54**：`queue_seq` 由 proxy 在 queue 锁下分配，helper 按 `queue_seq` 顺序重放与提交（原稿第 7 节，保留）。同 queue 的 scheduled、终态、completed-handler 派发顺序按 `queue_seq` 单调；**不同 queue 不承诺相对顺序**（原稿，保留）。缺失的 `queue_seq` 在 10 s 后使该连接进入 `ProtocolError` 并全部失效（原稿，保留 —— 这避免了无界重排缓存）。
>
> **D55**：helper 必须为**每个逻辑 Queue** 维护一个串行提交执行器，即使多个 Queue 最终共享同一个上游 `VkQueue`（原稿，保留）。Lavapipe 只有一个 graphics queue（`40-RUNTIME-VULKAN.md` 第 2.1 节），这会触发上游的 `shared-present-queue` degradation（第 7.1 节的关键 kind 之一），必须记录。

### 5.2 `SUBMIT` 的失败必须是"按 Metal 的方式失败"

这是原稿没有覆盖、而上游专门提供了工具的一块。

> **D56**：`SUBMIT` 的校验失败**不是**简单地回一个错误。Metal 的语义是"命令缓冲被提交了，但它失败了"，而不是"提交调用失败了"（`commit` 是 `void`）。上游为此提供三个扩展（`40-RUNTIME-VULKAN.md` 第 4.1 节）：
>
> | 上游 API | 用法 |
> |---|---|
> | `CommandBuffer::set_submission_check` | 在提交时跑一次检查，**按 Metal 的方式让该次提交失败** |
> | `CommandBuffer::commit_failed(CommitFailure)` | 把命令缓冲按失败提交，**仍运行 Metal 会运行的编码器并保留其信号** |
> | `execute_commands_in_buffer_checked` / `_indirect_checked` | 录制前逐条校验间接命令（guest 命令流校验点） |
>
> 因此 `SUBMIT` 的处理流程是：
> 1. 解析并校验整条日志与全部 oid（第 2.4.1 节）。**任一失败 → 不提交部分命令缓冲**（原稿第 8.4 节，保留），改走 `commit_failed(CommitFailure)`；
> 2. 回执是 `ok = true`（"提交被接受"），**命令缓冲的失败通过 `EVENT_TERMINAL` 的 `status = Error` 表达**；
> 3. 只有**协议层**的失败（envelope 坏、长度不符、oid 跨 namespace）才回 `ok = false`。
>
> 为什么这样分：客户端的 `commit` 已经返回了，它唯一能观察到结果的地方是 `status` / `error` / completion handler。把一个命令级错误变成"`commit` 的同步失败"在 ObjC 侧没有地方可以报。
>
> **D57**：**`commit_failed` 必须保留编码器的信号。** 上游明确："仍运行 Metal 会运行的编码器并保留其信号"。这意味着一个失败的命令缓冲**仍然会 signal 它的 fence / event**。如果我们跳过这一步，等在那个 event 上的另一个命令缓冲会永久挂住 —— 那就把一个可报告的错误变成了一次挂死。

### 5.3 IOSurface 可见性收尾必须在完成事件之前

吸收原稿第 10.2 节。该节的结论是对的，**保留并强化为一条带顺序的清单**。

> **D58**：`EVENT_TERMINAL` 的投递前置条件，**全部满足才能发**：
>
> 1. 上游 completed handler 已运行（`KNOWN`：上游的 completion 路径在 completed handler 之前已处理资源 hold 与 copied-host-page merge-back，`40-RUNTIME-VULKAN.md` 第 5 节与原稿第 10.2 节）；
> 2. `CommandBuffer::status` 已是 `Completed` 或 `Error`；
> 3. `CommandBuffer::error` 已冻结；
> 4. **该命令缓冲写过的每一个 IOSurface 的可见性收尾已成功**：shadow 副本已 copy-back、`IOSurfaceUnlock` 已调用、seed 已更新；
> 5. `WorkCounts` 的增量已采样（为了放进事件体）。
>
> **顺序不可调换。** 把第 4 步放到发事件之后，客户端会在 surface 还没有被 unlock、或 shadow 还没 copy-back 的时候去读像素 —— 那就是一帧撕裂或一帧旧内容，而且不可复现。
>
> **D59**：**IOSurface 收尾失败把最终状态改为 `Error`（`category = InternalError`）；不能先发 `Completed` 再报告 surface 错误**（原稿第 10.2 节，保留）。
>
> **D60**：`EVENT_TERMINAL` 的 `surface seeds` 字段（原稿已有）必须带上该命令缓冲触及的每个 surface 的**收尾后**的 seed。用途：客户端侧的 display 路径用 seed 判断"这一帧真的变了"，而不是每帧无条件重新上屏。

### 5.4 `waitUntilCompleted` 没有 timeout 返回值

这是本节最硬的一处，原稿第 10.2 节已经讨论对了，本文**保留其结论并把实现写死**。

事实（`KNOWN`）：

- `-[MTLCommandBuffer waitUntilCompleted]` 的 type encoding 是 `v16@0:8`（`bridge-runtime-contract.md` 第 3 节，双样本证据）—— **返回 void，没有超时出口**。
- 上游有 `CommandBuffer::wait_until_completed_for`（有界）与 `wait_until_completed`（无界）两种形式（原稿第 5 节）。
- 上游对会死锁的等待直接拒绝（`WaitWouldDeadlock`，第 4.1 节 D46）。

> **D61**：**helper 侧只用有界形式。** `WAIT` 消息带 `deadline_ms`，helper 调 `wait_until_completed_for(deadline)`。helper **永不**调用无界形式 —— 一个无界等待会占住 helper 的一个工作线程直到进程结束。
>
> **D62**：**客户端侧的 `waitUntilCompleted` 只能在终态后返回。** 实现是一个循环：
>
> ```text
> loop {
>     if cb.state is terminal { return; }
>     r = WAIT(cb, deadline = HEALTH_DEADLINE)        // 10 s
>     match r {
>         Terminal(s)   => { publish(s); return; }     // 含 Error
>         Timeout       => {
>             // 10 s 到了但 helper 说还在跑。这不改变状态，只触发健康诊断。
>             emit_health_diagnostic(cb);
>             if elapsed >= LIVENESS_DEADLINE {         // 60 s
>                 // 进入处置路径，见 D63
>                 supervisor.dispose(generation);
>                 // 只有在 supervisor 确认 helper 已死、映射已释放之后：
>                 if supervisor.confirmed_dead() {
>                     cb.force_terminal(Error, Timeout); publish(); return;
>                 }
>                 // 未确认则继续等 —— 见 D64
>             }
>         }
>         ConnectionInvalid => { cb.force_terminal(Error, DeviceLost); publish(); return; }
>     }
> }
> ```
>
> **10 s 只触发健康诊断，不改变状态、不返回**（原稿第 10.2 节，保留）。
>
> **D63**：60 s liveness hard deadline 到达时，**supervisor 必须终止该 helper generation 并确认进程已死、映射已释放或连接已失效**；**只有在确认不会再写 IOSurface 之后**，客户端才把命令缓冲置为 `Error`、触发回调、让 `waitUntilCompleted` 返回（原稿第 10.2 节，保留）。
>
> **D64**：**supervisor 无法确认 helper 已停止时，`waitUntilCompleted` 必须继续等待**，不得在共享内存仍可能被写时伪造终态（原稿第 10.2 节，保留 —— 这一条是整节里最重要的安全性质）。
>
> 但原稿在这里留了一个未封口的分支："或由调用进程的外部 watchdog 处置"。**本文补上这个分支的内容**：
>
> | 场景 | 处置 |
> |---|---|
> | 确认 helper 已死（`kill` 成功 + `waitpid`/`kqueue` 收到 exit，且全部共享映射已 `vm_deallocate`） | 伪造终态 `Error/Timeout`，返回 |
> | helper 进程还在但不响应（`SIGKILL` 已发、尚未 reap） | 继续等，最长再等 **30 s**；期间每 5 s 重试 reap |
> | 30 s 后仍未 reap（内核态卡住，例如在一个不可中断的 VM 操作里） | **这是一个不可恢复的状态。** `waitUntilCompleted` 继续挂住。同时：向系统日志写一条 `fault` 级记录、落盘一份诊断（第 6.7 节）、并**不再接受新连接** |
> | 该进程是 WindowServer | 上一行意味着 WindowServer 挂住 → 登录会话冻结。**这正是第 6.6 节的超时分级必须保证"永不走到这里"的原因**：显示路径的 deadline 必须远小于 60 s，见 D66 |
>
> **D65**：**显示侧超时不得永久阻塞 WindowServer。** 由 D64 的最后一行推出一条独立规则：**display 路径（`11-KERNEL-DISPLAY.md` 的 scanout 提交）绝不调用 `waitUntilCompleted`。** 它只能用"查 `status` + 事件回调"的异步形态。原因是 D64 的最坏分支在协议层无法消除，只能靠不进入它来回避。
>
> 实现约束：display 路径的每一帧提交必须带一个 `deadline_ms`（D66 的值），到期后的处置是**用上一帧的内容再上屏一次**（重复一帧），而不是等。重复一帧是可见的卡顿；挂住是黑屏加会话重启。

### 5.5 超时预算的分级

原稿第 8.5 节给了三个数（同步管线编译 30 s、queue 间隙 10 s、liveness 60 s）。**30 s 这个数与上游和 guest 的既有约束不协调，必须改。**

事实（`KNOWN`，`40-RUNTIME-VULKAN.md` 第 6.6 节）：上游 `DevicePolicy::pipeline_creation_wait` 与 `pipeline_commit_wait` 默认各 4.5 s；一个 host step 若既建状态又提交，最坏等 **9 s**；而 **guest 的 FIFO 检查是 10 s**。上游 README 明确指出这个关系，并要求本项目的 display provider 超时必须大于两者之和。

> **D66**：超时预算表（`INFERRED`，但受上面的 `KNOWN` 约束）：
>
| 层 | 名称 | 值 | 约束来源 |
|---|---|---:|---|
| 上游 | `pipeline_creation_wait` | **2.0 s** | 显式设定，不用默认 4.5 s |
| 上游 | `pipeline_commit_wait` | **2.0 s** | 同上 |
| 协议 | 管线创建消息的 deadline | **4.5 s** | ≥ 两者之和 4.0 s，留 0.5 s 余量 |
| 协议 | 其余同步消息的 deadline | **1.0 s** | 创建小对象、查询 |
| 协议 | `REPLACE_REGION` / 大 blob 的 deadline | **4.5 s** | 与管线同级（都可能是数十 MiB 的拷贝） |
| 协议 | queue 序号间隙 | **10 s** | 原稿，保留 |
| **显示** | **display 路径单帧 deadline** | **2.0 s** | 必须 < guest FIFO 检查的 10 s，且必须 < 健康 deadline。到期重复上一帧（D65） |
| 健康 | 健康诊断 deadline | **10 s** | 原稿，保留。只触发诊断 |
| 处置 | liveness hard deadline | **60 s** | 原稿，保留。触发 supervisor 处置 |
| 处置 | 强杀后等待 reap | **30 s** | 本文新增（D64） |
>
> 为什么把上游的 4.5 s 降到 2.0 s：原稿的 30 s 同步编译 deadline 意味着一次 `newRenderPipelineStateWithDescriptor:error:` 可以让调用线程停 30 s。在 WindowServer 上这是 30 s 黑屏。2.0 + 2.0 = 4.0 s 的最坏情况加上 0.5 s 余量，仍然远小于 guest 的 10 s FIFO 检查，而且 `60-CAPABILITY-MATRIX.md` 的管线预热（`Device::warm`，`40-RUNTIME-VULKAN.md` 第 6.6 节）正是为了让热路径上**根本不触发编译**。
>
> 代价：**预算内没建好的管线会让 draw 被丢弃而命令缓冲不报错**（`draws_dropped_still_making`，`40-RUNTIME-VULKAN.md` 第 7.2 节）。这正是 D13 要求 `EVENT_DROPPED_DRAW` 的原因 —— 把预算调紧之后，这个信号从"罕见"变成"可能每次冷启动都发生"，必须可观测。
>
> **D67**：**全部 deadline 必须进 `proto_hash`（D26）且必须可由配置降低、不可由客户端提高（D24）。**

### 5.6 Event、Fence 与跨进程 shared event

| 对象 | 上游 | 切分后 |
|---|---|---|
| `MTLFence` | `Fence`（编码器间 barrier / 事件） | 纯粹在命令日志内，**不需要消息**（它只在同一个命令缓冲或同一 queue 的相邻命令缓冲之间用） |
| `MTLEvent` | `Event`、`EventRef` → timeline semaphore | `EVENT_SIGNAL` / `EVENT_HOST_WAIT`；编码器内的 signal/wait 走命令日志 |
| `MTLSharedEvent` | `SharedEvent`、`SharedEventHandle`、`SharedEventListener`、`SharedEventNotification` → timeline semaphore；**handle 仅进程内** | `EXPORT_SHARED_EVENT` / `IMPORT_SHARED_EVENT`。跨进程部分是本项目的（`40-RUNTIME-VULKAN.md` 第 4 节第 6 项） |

> **D68**：`MTLSharedEventHandle` 的跨进程表示**不是对象 ID**。它是：
>
> ```text
> { nonce: [u8;16], event_oid: u64, mac: [u8;32] }
> mac = HMAC-SHA256(helper 的 per-generation 密钥, nonce || event_oid || 导出者的 client_id)
> ```
>
> `IMPORT_SHARED_EVENT` 的处理：重算 MAC，不等则 `InvalidArgument`；相等则在导入者的 namespace 里建一个新 entry（`flags.is_shared = 1`）指向同一个上游 `SharedEvent` 的 clone。
>
> 为什么要 MAC：对象 ID 是可猜的（`ObjectId` 单调递增）。没有 MAC，任何 client 都能通过猜 ID 拿到别人的 event，从而 signal 它、让对方的命令缓冲提前通过 —— 这是一个跨 client 的正确性破坏，不只是信息泄露。
>
> 密钥是 **per-generation** 的：helper 重启后旧 token 全部失效，与 generation 语义一致。
>
> **D69**：`MTLSharedEventListener` 的回调是客户端的 block + 一个 `dispatch_queue_t`。它**完全在客户端侧**：proxy 登记 block，helper 发 `EVENT_SIGNAL` 的通知事件，proxy 在指定 queue 上派发。helper 不知道 dispatch queue 的存在。
>
> **D70**：`MTLSharedEvent.signaledValue` 的 setter 是 host 侧 signal。它必须是**异步 fire-and-forget**（`EVENT_SIGNAL`），因为 Metal 的语义里它不返回任何东西，而把它做成同步会在每次 signal 上加一个往返。连带要求：proxy 侧的 `signaledValue` getter 读本地缓存值，由 `EVENT_SIGNAL` 的通知事件推进。**两者之间有窗口**，这与 Metal 在真实 GPU 上的行为一致（GPU 侧 signal 对 CPU 的可见性也有延迟）。

### 5.7 Completion handler 的生命周期

吸收原稿第 10.3 节。该节完整且正确，**整节保留**，这里只列条目以便实现对账。

| 规则 | 来源 |
|---|---|
| `addCompletedHandler:` 入参非空时**立即** `_Block_copy`；空 block 使命令缓冲记录 `InvalidArgument` | 原稿，保留 |
| block 只能在 `commit` 前登记；commit 后登记**不调用**并产生与上游 `HandlerAfterCommit` 对应的确定性误用诊断 | 原稿，保留（上游同样拒绝 commit 后 handler） |
| 命令缓冲 proxy 从 commit 到回调表清空期间**自持有** | 原稿，保留 |
| 每个 block 被取出后调用**一次**，调用结束立即 `_Block_release` | 原稿，保留 |
| 用户 block 抛出的 ObjC 异常**不得穿过 Rust/XPC 回调边界**；shim 必须捕获、记录并继续释放剩余 block | 原稿，保留（与 D4、D5 同一规则） |
| 回调执行时**不得持有**连接、对象表、命令缓冲状态、surface registry 或回调表的锁 | 原稿，保留 |
| 客户端收到终态事件后，**先在锁内**冻结 status/error 与 logical completion value 并唤醒 waiter，**再在锁外**按注册顺序调用 block | 原稿，保留 |

> **D71**：补一条原稿没有的：**`addScheduledHandler:` 与 `addCompletedHandler:` 的派发顺序**。同一命令缓冲的 scheduled handler 全部跑完之后才跑 completed handler；跨命令缓冲按 `queue_seq`（D54）。实现上这意味着事件定序器必须在发布终态之前确保 scheduled 已发布（原稿第 10.1 节的乱序处理已经给了这个机制）。
>
> **D72**：`completion_value` 是 **helper 的逻辑值**，等于 helper 为该逻辑 queue 接受的 `queue_seq`。**它不得记录或暴露内部 `VkSemaphore` 的 handle 或计数器**（原稿第 8.4 节与第 12 节，保留；上游不公开 raw timeline value，这是一个真实的 API gap）。

---

## 6. 崩溃与恢复

### 6.1 Generation 的语义

> **D73**：generation 是一个 **32 位非零计数器**，含义是"helper 进程的第 N 次化身"。规则：
>
> 1. **helper 启动时原子地 +1 并持久化。** 原稿第 6.3 节已指出"进程内静态计数不合格，必须定义跨进程崩溃的持久化 epoch"，正确，保留。
> 2. 回卷（达到 `u32::MAX`）时 **helper 拒绝启动并要求重置安装标识**（原稿，保留）。
> 3. 全部 handle 带 generation；generation 不符 → `DeviceLost`（D15）。
> 4. **旧 generation 的 handle 在新 helper 中永远被拒绝**（原稿第 10.4 节，保留）。
>
> **D74**：持久化位置（原稿标 `BLOCKED`，本文给出具体方案，仍 `BLOCKED` 于实测）：
>
> | 项 | 取值 |
> |---|---|
> | 路径 | `/var/db/net.metal2vu/generation`（`root:wheel`，`0600`） |
> | 写法 | 写临时文件 + `fsync` + `rename`（原子替换），不是原地改写 |
> | 内容 | 8 字节：`{magic:u32 = 'M2VG', value:u32}` |
> | 失败处置 | **无法写 → helper 拒绝启动**（`NotProvisioned`）。不得退回进程内计数器 |
>
> 为什么不用 `/Library/Application Support`：那是用户可写路径下的目录树；generation 必须由 root 独占。为什么不用 NVRAM：写入次数有限且 SIP 关闭下的可靠性未知。
>
> `BLOCKED`：**`/var/db` 在 25G325 的 launchd daemon sandbox 下是否可写未实测。** 关闭方式：Gate H-1（第 8.4 节）。

### 6.2 崩溃检测

> **D75**：三条独立的检测路径，**全部必须实现**：
>
> | 路径 | 机制 | 延迟 | 检测什么 |
> |---|---|---|---|
> | XPC invalidation | `xpc_connection_set_event_handler` 收到 `XPC_ERROR_CONNECTION_INVALID` | 内核级，近即时 | helper 进程死亡、helper 主动断开 |
> | 请求 deadline | 每条同步请求的 `deadline_ms`（D66） | 1.0–4.5 s | helper 活着但卡住 |
> | liveness 探针 | 每 2 s 一条 `kind = QUERY` 的轻量心跳；连续 5 次无回应 | 10 s | helper 活着但事件循环卡住 |
>
> 单靠 XPC invalidation 不够：**helper 可以在不死的情况下卡住**（LLVM 在一个病态 shader 上跑很久、或 Lavapipe 在一个死循环里）。这种情况下 XPC 连接完好无损，而客户端会无限等。
>
> **D76**：客户端侧的 invalidation handler 以**一次性 CAS** 把连接标为 dead，并快照全部非终态命令缓冲（原稿第 10.4 节，保留）。CAS 是必须的：三条检测路径可能同时触发。

### 6.3 Proxy 在 helper 崩溃时必须做的全部动作

吸收原稿第 10.4 节（5 条），补齐到 11 条，并给出顺序。

> **D77**：**顺序固定**，因为后面几步依赖前面几步已完成：
>
> | # | 动作 | 为什么在这个位置 |
> |---|---|---|
> | 1 | CAS 把连接状态置 `Dead`（D76） | 必须先关门，否则后续步骤里会有新请求挤进来 |
> | 2 | 拒绝全部新的创建 / 提交调用，返回 `DeviceLost` | — |
> | 3 | **等待全部共享映射被安全处理**：对每个 `MAP_BUFFER` 得到的映射，先确认 helper 已死（第 6.4 节），再 `vm_deallocate` | **必须在第 5 步之前**。否则客户端可能在 helper 其实还活着的情况下，一边读映射一边被告知"完成了" —— 与 D64 同一条推理 |
> | 4 | 快照全部非终态命令缓冲（在锁内，一次性取出列表） | — |
> | 5 | 每个快照命令缓冲进 `Error`，wire category `DeviceLost`，唤醒 waiter | 原稿，保留 |
> | 6 | 每个 completed handler 调用**恰好一次**（锁外，按注册顺序） | 原稿，保留 |
> | 7 | 已终态的命令缓冲**不被覆盖** | 原稿，保留 |
| 8 | 当前 generation 的全部 proxy 进 `Dead` | 原稿，保留 |
| 9 | 全部 `MTLSharedEvent` 的 host 侧等待者被唤醒并返回失败 | **新增**：它们不挂在命令缓冲上，第 5 步不会唤醒它们 |
| 10 | 全部登记的 `MTLSharedEventListener` block 调用一次（带失败指示） | **新增**，同上 |
| 11 | 发一条结构化日志，含 generation、非终态命令缓冲数、映射数、最后一条成功请求的 `request_id` | **新增**：这是事后诊断的唯一线索 |
>
> **D78**：第 5、6、9、10 步的回调**全部在锁外**，且顺序是"先全部置终态并唤醒，再全部回调"。混着做会让一个客户端的回调里读到另一个命令缓冲还没置终态。

### 6.4 "确认 helper 已死"的具体判据

D63、D64、D77 第 3 步都依赖这一判据。原稿没有定义它。

> **D79**：**确认 helper 已死 = 下面三项全部成立**：
>
> 1. XPC 连接已 invalid（`XPC_ERROR_CONNECTION_INVALID`），**或** supervisor 报告该 generation 的进程已 reap；
> 2. **该 generation 的全部 Mach memory entry 已 `vm_deallocate`，且客户端侧没有任何剩余映射**；
> 3. 该 generation 写过的全部 IOSurface 已被客户端侧重新 `IOSurfaceLock`/`Unlock` 一轮（证明没有别的写者持有锁）。
>
> 第 2、3 项是本文新增的。原稿第 10.2 节写"确认进程死亡、mapping 释放或 connection invalidation"，用的是 **"或"** —— 那是不够的：**XPC 连接 invalid 不等于映射已释放**。XPC 连接是一个 Mach port 的生死，共享内存是另一个对象；一个僵尸进程（已 `SIGKILL` 但未 reap，内核态卡在某个 VM 操作里）完全可以在连接已断的情况下仍持有对那段内存的写映射。
>
> **现更正为"与"**。

### 6.5 哪些对象可重建、哪些不可

原稿第 10.4 节给了一句（"IOSurface capability 可由客户端显式重新 import；private buffer、library、pipeline 和 command buffer 不自动重建"）。本文按第 2.3 节的 24 个 kind 给全表。

> **D80**：**没有任何对象被自动重建。** 这是一条设计决定，不是偷懒：自动重建意味着客户端在不知情的情况下拿到一个内容不同的对象（buffer 的字节没了、heap 的子分配没了），那比明确失败危险得多。下表的"可重建"指**客户端有能力自己重建**，由客户端决定是否重建。

| kind | 客户端可重建 | 重建所需的输入 | 内容是否保留 |
|---|---|---|---|
| `Device` | 是（新 generation 的 `HELLO`） | 无 | — |
| `Queue` | 是 | queue snapshot（proxy 已存） | — |
| `CommandBuffer` | **否** | — | 在途的工作**已丢失**，必须向上层报错 |
| `Buffer`（`newBufferWithBytes:`） | 是 | 原始字节 —— **但 proxy 没有保存它们**（R26 要求复制后就交给 helper） | **否** |
| `Buffer`（`newBufferWithLength:`，内容由 GPU 写） | 是（对象） | length + options | **否** |
| `Buffer`（`noCopy`，客户端页） | 是 | 客户端仍持有那段内存 | **是** |
| `Texture`（普通） | 是（对象） | texture snapshot | **否** |
| `Texture`（IOSurface backed） | 是 | 客户端仍持有 `IOSurfaceRef` → 重新 `IMPORT_SURFACE` | **是**（内容在 surface 里，不在 helper 里） |
| `Texture`（view） | 是 | 基纹理可重建则可 | 随基纹理 |
| `Library` | 是 | 客户端仍持有 metallib 字节？**通常不持有** | 对象可重建、需客户端重新提供字节 |
| `Function` | 是 | library + function snapshot | 是 |
| `RenderPipeline` / `ComputePipeline` | 是 | pipeline snapshot（proxy 已存）+ function | 是；且**翻译结果在着色器缓存里**，重建很快（第 6.8 节） |
| `DepthStencilState` / `SamplerState` | 是 | snapshot（proxy 已存） | 是 |
| `Heap` | 是（对象） | heap snapshot | **否**（子分配全丢） |
| heap 上的资源 | **否**（heap 内容丢了） | — | **否** |
| `Fence` | 是 | 无 | — |
| `Event` / `SharedEvent` | 是（对象） | 无 | **否**（signaled value 归零）。见 D81 |
| `IndirectCommandBuffer` | 是（对象） | ICB snapshot | **否**（已录制的命令全丢，必须重录） |
| `ArgumentEncoder` | 是 | argument descriptor 数组（proxy 已存） | 是 |
| `BinaryArchive` | 是 | snapshot；若有 `url` 则内容在磁盘上 | 看是否落盘 |
| `VisibleFunctionTable` | 是 | snapshot + function | 是 |
| `RateMap` | 是 | snapshot | 是 |
| `ResidencySet` / `LogState` | 是 | snapshot | 是 |
| reflection | 随 pipeline | — | 是 |

> **D81**：**`Event` / `SharedEvent` 的 signaled value 在 generation 切换时归零，这是一个语义缺口。** 一个等在 `value = 100` 上的客户端，在重建后的 event 上永远等不到（新 event 从 0 开始，而客户端已经把"我已经 signal 到 100 了"的状态丢了）。处置：
> - **不尝试恢复计数值**（helper 没有持久化它，恢复它需要跨崩溃持久化 event 状态，成本与收益不成比例）；
> - 重建的 event 的 proxy 必须拒绝任何"等待一个 < 已知最高 signaled value 的值"之外的等待，直接返回失败；
> - 把这一项写进 `60-CAPABILITY-MATRIX.md` 的已知损失。
>
> `INFERRED`。
>
> **D82**：**IOSurface 是唯一跨 generation 存活的内容载体。** 它的内容在内核的 IOSurface 对象里，helper 只是映射了它。这是一个重要的架构性质：**崩溃恢复后画面不必从零重建**，客户端重新 import 同一个 surface 就能接着用。这也是为什么 display 路径必须走 IOSurface 而不是 Vulkan swapchain（`40-RUNTIME-VULKAN.md` 第 4 节第 4 项的决定在这里得到第二个理由）。

### 6.6 Supervisor 策略与超时分级

> **D83**：supervisor **不是** helper 自己，也不是客户端。它是 launchd（第 8 节）加上客户端侧的一小段处置逻辑。分工：
>
> | 职责 | 归谁 |
> |---|---|
> | 检测 helper 进程退出并重启它 | launchd（`KeepAlive`） |
> | 限制重启频率 | launchd（`ThrottleInterval`）+ 本项目的 crash-loop 断路器（D85） |
> | 决定"这次失败要不要重启" | **本项目**，按第 4.1 节的 category |
> | 强杀卡住的 helper | **客户端侧的处置逻辑**（它是唯一知道"我等了多久"的一方） |
> | 确认已死（D79） | 客户端侧 |
>
> **D84**：按 category 的处置策略（`INFERRED`）：
>
> | 触发 | 处置 |
> |---|---|
> | helper 进程崩溃（signal / abort） | 走第 6.3 节的 11 步；允许 launchd 重启；客户端在下一次 `MTLCreateSystemDefaultDevice` 或下一帧重新 `HELLO` |
> | `category = Stopped`（`Unproven`，D45） | 走 11 步；**禁止自动重启**（写一个 `stop` 标记文件，launchd 的 `KeepAlive.PathState` 看到它就不重启）；需人工介入 |
> | `category = NotProvisioned`（loader / 驱动配置 / 缓存目录） | helper 自己在启动自检阶段退出（`40-RUNTIME-VULKAN.md` 第 6.7 节的 8 项自检）；**禁止自动重启**，同上 |
> | `category = DeviceLost`（Vulkan device lost） | 允许重启。Lavapipe 上 device lost 极罕见，出现一次就落一份完整诊断 |
> | 卡住超过 liveness deadline（60 s） | 客户端 `SIGKILL` → 等 reap（最长 30 s，D64）→ 走 11 步 |
> | 启动自检失败 | helper 退出码非 0；launchd 按 `ThrottleInterval` 重试；连续 3 次失败触发断路器 |
>
> **D85**：**crash-loop 断路器**。连续 3 次在 60 s 内崩溃 → 停止重启 60 s；连续 5 次 → 停止重启并写 `stop` 标记。理由：一个必崩的 shader 会让 helper 在每次重试时立刻再崩，而每次重启都要重新建 Vulkan device、重新 warm 管线缓存 —— 这会把一台机器的 CPU 吃满。
>
> 断路器的状态和 generation 一样需要持久化（同一文件，加两个字段：`last_crash_unix:u64`、`crash_count_in_window:u32`）。
>
> **D86**：超时的两类用途必须分清（这是对原稿第 10.2 节最后一条的保留与强调）：
>
> | 类 | 名称 | 值 | 作用 |
> |---|---|---:|---|
> | **健康检查** | 10 s | 只记诊断、只采样一次状态 | **绝不改变状态、绝不返回、绝不杀进程** |
> | **处置** | 60 s | 触发 `SIGKILL` + D79 的确认 + 终态伪造 | 改变状态 |
>
> 原稿的话是："基线『普通提交等待 10 秒、总等待 60 秒』只能作为健康检查和 helper 处置 policy，不能直接改变无返回值 `waitUntilCompleted` 的 API 语义。" **成立，保留。**

### 6.7 崩溃诊断的落盘

> **D87**：每次 helper 异常终止必须在 `/var/log/net.metal2vu/<generation>/` 下落一份诊断包。内容白名单（第 7.7 节的脱敏规则同样适用）：
>
> | 项 | 说明 |
> |---|---|
> | `manifest.json` | generation、helper 二进制哈希、loader / ICD / Mesa / LLVM 版本与哈希、`DeviceOptions` 哈希、`proto_hash` |
> | `capability.json` | 该 generation 的 capability snapshot（`40-RUNTIME-VULKAN.md` 第 7.5 节的生成物） |
> | `last-requests.jsonl` | 最后 256 条请求的 `{request_id, kind, client_id, declared_bytes, 结果}`。**不含 body** |
> | `degradations.jsonl` | 该 generation 累积的 degradation code 与计数 |
> | `work-counts.json` | `WorkCounts` 终值，含 `draws_dropped_*` |
> | `refusals.jsonl` | 该 generation 命中的拒绝 variant 与 `needs` |
> | `objects.json` | 每个 client 的对象计数（按 kind）与配额用量。**不含 label 之外的内容** |
> | 系统 crash report 的路径引用 | 不复制内容，只记路径 |
>
> **不得包含**：shader 源码、metallib 字节、像素、buffer 内容、客户端路径、共享内存快照。

### 6.8 恢复后的冷启动代价与缓解

> **D88**：helper 重启后最贵的一项是**管线翻译**。缓解是上游的管线预热（`40-RUNTIME-VULKAN.md` 第 6.6 节），必须实现：
>
> 1. `DeviceOptions::pipeline_records` 的回调在每次管线状态创建时被调一次 → `PipelineRecord::to_bytes` 持久化到本项目控制的目录；
> 2. 启动时 `from_bytes` 读回（格式不符的记录返回 `None`，**直接丢弃** —— 这正是系统更新后的正确行为）；
> 3. `Device::warm(records, byte_budget)` 立即返回，在后台线程按序重建；
> 4. `Device::warm_statistics` 落盘。
>
> `warm` 的安全性质（`KNOWN`，`40-RUNTIME-VULKAN.md` 第 6.6 节）：不取标识符、不取 resource ID、不取 sampler 编号、不建 neutral、不报降级、不读别的 translator 或别的 `RUNTIME_VERSION` 的记录 —— **所以它不会改变程序拿到的任何答案**。因此它可以无条件在启动时跑。
>
> **D89**：着色器缓存目录必须由本项目显式指定（`ShaderCacheOptions`），**不得用上游默认的每用户目录**（`40-RUNTIME-VULKAN.md` 第 6.6 节）。helper 是 root daemon，"每用户目录"在它那里没有意义。位置：`/var/db/net.metal2vu/shader-cache/<guest-build>-<component-hash>/`。目录名含 guest build 与组件哈希，这样系统更新或组件更新后自然失效。

---

## 7. 安全

### 7.1 威胁模型

> **D90**：**客户端是不可信的。** 这不是假设性的 —— 第一版同进程时客户端就是宿主进程本身，但切分后 helper 是一个 root daemon，而它的客户端里有 WindowServer（高权限）也有任意用户 app（低权限）。任意一个用户态 app 都可以连上 helper，因为 Metal 客户端就是任意 app。
>
> 因此 helper 的输入处理面必须按"接收攻击者可控数据的 root 服务"来写：
>
| 攻击者能控制的 | 处置节 |
|---|---|
| XPC 字典的全部内容（键、类型、嵌套、长度） | 7.3 |
| blob 的字节与声明长度 | 7.3 |
| 命令日志的全部字节（长度字段、偏移、计数） | 7.3 |
| oid 的数值（可枚举、可猜） | 7.2 |
| metallib 的全部字节（喂给 translator 与 LLVM） | 7.4 |
| IOSurface（通过 Mach right） | 7.5 |
| 请求的时序与并发度 | 7.8 |
| 路径字符串（如果我们接受它们） | 7.6 |

### 7.2 按 audit token 隔离

> **D91**：见 D28。核心规则重述：**namespace 由连接的 audit token 决定，不由请求内容决定。** 请求里的 `client_id` 只用于一致性检查。
>
> **D92**：oid 是可枚举的（`ObjectId` 单调递增）。因此**跨 namespace 的 oid 查找必须在 kind 检查之前失败**（D15 的顺序规则）。实现上这意味着对象表就是 per-connection 的（D27），"跨 namespace 查找"在代码里不可表达 —— 这比"查到了再检查 owner"安全。
>
> **D93**：**三处跨 namespace 的桥必须各自独立授权**（D31）。shared event / shared texture 的 token 必须带 MAC（D68），不得用裸 oid。

### 7.3 长度与乘法校验；不原地解析共享内存

> **D94**：**所有长度字段都是攻击者可控的，一律不信。** 具体规则：
>
> 1. `declared_bytes` 必须与 helper 独立重算的值相等（原稿第 8.1 节与第 12 节，保留 —— 原稿已把"信任 `payload_size`"列为需修正项）。
> 2. 每个 `xpc_data_t` 的长度取自 XPC（内核已填），**不取自字典里客户端声明的字段**；两者不等即 `ProtocolError`。
> 3. 命令日志的解析是一个长度驱动的游标。校验在解析**之前**：`header.total_bytes == 实际字节数`、每个 `encoder.cmd_offset + cmd_count` 在界内、每个 `cmd.len >= 4 且 8 字节对齐`、游标走完恰好到 `total_bytes`、`oid_count <= 4096`。任一不符 → `ProtocolError` + 关连接（第 2.4.1 节）。
> 4. **全部乘加用 checked 算术**（原稿第 8.5 节，保留）。重点位置：`bytes_per_row * (height - 1) + width * bpe`、`offset + length`、`stride * count`、`level` 链推导的 mip 尺寸、`plane_offset + plane_size`、配额累加（D40）。
> 5. 任何溢出在**分配、映射或调上游之前**返回 `InvalidArgument`（原稿，保留）。
>
> **D95**：**绝不原地解析共享内存里的结构化数据**（D21）。规则：
>
> | 数据 | 处理 |
> |---|---|
> | OOL blob（metallib、顶点字节、`REPLACE_REGION` 的像素） | **先整段复制进 helper 私有内存**，再解析副本 |
> | 命令日志 | 同上（它走 `xpc_data_t`，XPC 已经给了我们一份副本；若改走 OOL 则同样先复制） |
> | `MAP_BUFFER` 映射的 buffer 内容 | **helper 永不解析它**。它是客户端写、GPU 读的数据，helper 对其内容没有任何假设 |
>
> 理由：共享内存是 TOCTOU 面。一个"先校验头部再按头部解析主体"的解析器，如果直接在共享内存上跑，攻击者可以在两步之间改写头部。
>
> **D96**：复制的代价必须被配额约束，否则"先复制"本身就是 DoS 面。因此第 2.6 节的 `metallib ≤ 64 MiB`、`单次 REPLACE_REGION ≤ 64 MiB`、`命令日志 ≤ 16 MiB/command buffer`、`并发 in-flight 请求 ≤ 64/client` 四项合起来给出单 client 的瞬时复制上界。

### 7.4 metallib 与 translator：最大的攻击面

> **D97**：**metallib 字节会被喂给上游的 AIR 解析器、translator 和 LLVM。** 这是 helper 里最大的攻击面，而且其中的代码不是本项目写的。处置：
>
> 1. **只接受 metallib，不接受裸 AIR。** 上游 `Device::new_library_with_data` 只接受 metallib；裸 AIR 需先过 `metal2vulkan::library::Library::from_air`（`40-RUNTIME-VULKAN.md` 第 2.4 节）。**本项目不暴露裸 AIR 路径**（`metal2vulkan-air` crate 只给分析工具用，第 1 节规则 3）。
> 2. **`dispatch_data_t` 不得假定是 `NSData *`**（原稿第 4 节，保留）。必须用 `dispatch_data_apply` 或 `dispatch_data_create_map` 分段处理。
> 3. 翻译有预算：上游 `Error::Budget`（1 个 variant）与 `Error::LimitExceeded(Limit)`（14 个 variant）。**用上游的，不自己造**（第 2.6 节）。
> 4. **translator 的 panic 必须被当作 helper 崩溃处理**，不是当作编译错误。一个 panic 意味着上游遇到了它自己没预料到的输入；此时 helper 的内部状态不可信。处置：`catch_unwind` 捕获 → 落诊断（第 6.7 节，记录 metallib 的**哈希**，不记内容）→ **helper 自行退出**，让 generation 前进。
> 5. 这一项是 helper 隔离最直接的收益：**同进程时 translator 的 panic 就是 WindowServer 的 abort。**
>
> **D98**：**不得在日志里保存完整 shader。** 原稿第 10.5 节已有此要求，保留。记录的是：metallib 的 SHA-256、字节数、function 名清单（≤ 64 个、每个 ≤ 1024 B）、编译失败时上游给的类型化 `Problem`。**不记 AIR 字节、不记反汇编、不记 SPIR-V。**
>
> 研发期的例外：**可以**把失败的 metallib 落到一个独立的、`root:wheel 0600` 的 quarantine 目录（`/var/db/net.metal2vu/quarantine/<sha256>.metallib`），用于复现。规则：仅在研发配置下启用；文件数上限 64；进 `70-BUILD-PACKAGE.md` 的卸载清单。`INFERRED`。

### 7.5 IOSurface：capability 而非 ID

吸收原稿第 9 节。该节的结论正确，保留并加一条。

> **D99**：`IMPORT_SURFACE` 的 `surface` 必须是**随消息传递的 capability / Mach right**；**单独的全局 IOSurface ID 不得作为授权依据**（原稿第 9 节与第 12 节，保留）。ID 只能用于诊断与交叉检查。
>
> **D100**：helper 取得自己的 `IOSurfaceRef` 之后**必须重新读取**：plane count、base address、allocation size、width、height、bytes-per-element、bytes-per-row、plane offset、plane size（原稿第 9 节，保留）。请求里的 snapshot **只用于交叉检查**，不作为事实。
>
> 这正是 `22-OBJC-DESCRIPTORS.md` R11 的另一半：客户端声明的几何值一律不信，自己重测。
>
> **D101**：几何有效性必须逐步 checked（原稿给了单 plane BGRA8 的形式，本文推广到任意格式）：
>
> ```text
> bytes_per_element == 该 plane 的格式所要求的值
> bytes_per_row     >= width * bytes_per_element                      (checked mul)
> plane_offset + bytes_per_row * (height - 1) + width * bytes_per_element
>                   <= allocation_size                                 (checked mul+add)
> plane_index       <  plane_count（或 plane_count == 0 且 plane_index == 0）
> ```
>
> **D102**：**新增一条原稿没有的**：helper 必须拒绝 base address 不满足 `VK_EXT_external_memory_host` 的 `minImportedHostPointerAlignment` 的 surface。理由：不满足对齐时上游会退化成拷贝（`Degradation::CopiedHostPages`），而对 scanout surface 来说每帧一次全画面拷贝是不可接受的性能悬崖。处置不是失败，而是**记录两轴 import mode 并发 degradation**（见下），让上层能看到这一帧走的是拷贝路径。
>
> **D103**：**两轴 import mode 必须分开报告**（原稿第 9 节，保留 —— 原稿已正确指出基线的单轴 `DirectHostImport`/`ShadowCopy` 分类不足）：
>
> | 轴 | 取值 | 判定依据 |
> |---|---|---|
> | host-buffer 存储 | `ImportedHostPages` | `WorkCounts.host_pointer_imports_made` 增加，且无 `CopiedHostPages` |
> | | `CopiedHostPages` | 收到 `Degradation::CopiedHostPages` 或 copied counter 增加 |
> | texture 存储 | `InPlaceImage` | 无 texture shadow/copy degradation |
> | | `ShadowedTexture` | 上游采用 shadow image 并在 completion 时 copy/merge back |
>
> **只有 `ImportedHostPages + InPlaceImage` 才能称为直接路径**（原稿，保留）。为了准确归因，helper 对 surface backing 的创建使用**专用串行段**，并在 `DeviceOptions::messages` 的 sink 里捕获每次 `CopiedHostPages` 通告；**不得从全局累计值在并发创建后猜**（原稿，保留 —— 这一条很重要且容易被省掉）。
>
> **D104**：surface 的写锁时序（原稿第 9 节，保留）：写 lock 在**第一个在途 writer 之前**取得，unlock / seed 更新在**最后一个 writer 的上游 completion 之后**完成；**不得在 proxy 释放 texture 时提前 unlock**。
>
> `BLOCKED`：`IOSurfaceLock`/`Unlock` 的 flags、seed 与跨进程可见性的最终序列必须由目标 guest 的探针固定（原稿标 Gate 2，保留）。本文不把它当作已验证的 cache-coherency ABI。

### 7.6 禁止客户端传任意文件路径；禁止加载包外 ICD

> **D105**：**helper 不接受任何客户端提供的文件系统路径作为打开目标。** 协议里根本没有 path 类型的字段。
>
> `22-OBJC-DESCRIPTORS.md` 有三处 descriptor 字段是 `NSURL`（`MTLBinaryArchiveDescriptor.url`、`MTLCaptureDescriptor.outputURL`、`MTLDynamicLibraryDescriptorSPI.url`，见该文 R28）。处置：
>
> 1. proxy 侧把 URL 的**内容哈希**算出来，只把哈希（32 字节）放进消息；
> 2. helper 侧用哈希在**自己的缓存目录**下命名文件；
> 3. 实际的读/写发生在 helper 自己的目录里，**从不触碰客户端给的路径**；
> 4. `NSError` 的 `userInfo` 里说明路径被重定向（R28）。
>
> 这样一个用户 app 无法让 root helper 去读 `/etc/master.passwd` 或写 `/Library/LaunchDaemons/`。
>
> **D106**：**禁止加载包外 ICD。** 三重保险（`40-RUNTIME-VULKAN.md` 第 6.3、6.4 节，本文重申并加 helper 侧的落地方式）：
>
> | 保险 | 做法 |
> |---|---|
> | 1 | `DeviceOptions::kinds` 只允许 `DeviceKind::Cpu`；无合格设备时返回 `Error::NoDevice`（**失败而不是回退**） |
> | 2 | 启动期 `registry_ids_with` 列出全部合格设备、`system_default_identity_with` 读身份、校验 kind 为 CPU 且 `deviceName` 匹配 `llvmpipe (LLVM …)` 模式、再用 `with_registry_id` **只建那一个** |
> | 3 | `DeviceOptions::loader` 显式给随包 loader 的绝对路径；环境变量 `VK_DRIVER_FILES` 指向随包 `lvp_icd.x86_64.json` 的绝对路径，`VK_ICD_FILENAMES` 与 `VK_ADD_DRIVER_FILES` **显式 unset**，`VK_LOADER_DRIVERS_SELECT=lvp_icd.*`，`VK_LAYER_PATH` / `VK_INSTANCE_LAYERS` 在发布配置下清空 |
>
> **helper 侧的落地方式**（本文新增）：
>
> 1. 环境变量必须在 **helper 进程自己的 `main` 开头**用 `setenv` 设定，**不依赖 launchd 的 `EnvironmentVariables`**。理由：launchd 的环境变量是可被 plist 改写的，而 plist 在 `/Library/LaunchDaemons` 下；用代码里的常量更难被改。
> 2. 设定之后、打开 loader **之前**，helper 必须把继承来的全部 `VK_*` 与 `DYLD_*` 变量**枚举并记录**，然后 unset 不在白名单里的。继承的 `DYLD_INSERT_LIBRARIES` 是 SIP 关闭下的真实注入面。
> 3. 这一步的结果（最终生效的变量集）必须进启动自检记录（`40-RUNTIME-VULKAN.md` 第 6.7 节的 8 项之外的第 9 项）。
>
> `BLOCKED`：**这些变量在目标 guest 的 launchd 环境下是否生效（launchd 传递、SIP 关闭后的 `DYLD_*` 交互）未实测**（`40-RUNTIME-VULKAN.md` 第 6.4 节已标此 `BLOCKED`）。关闭方式：Gate H-1。

### 7.7 日志脱敏

> **D107**：日志的内容白名单（统一规则，第 4.3 节的 `userInfo`、第 6.7 节的诊断包、第 7.4 节的 metallib 处理都遵循它）：
>
> | 可以记 | 不可以记 |
> |---|---|
> | oid、kind、generation、client_id、request_id、queue_seq | 任何像素字节 |
> | 稳定的 `source_kind` / degradation code / refusal variant | 完整 shader（源码、AIR、metallib、SPIR-V） |
> | 数值型的尺寸、计数、偏移、配额用量 | buffer 内容 |
> | metallib 的 SHA-256、字节数、function 名（有界） | 客户端提供的文件路径 |
> | 客户端设置的 `label`（≤ 256 B） | 客户端提供的任意字符串（如 `additionalCompilerArguments`，`22-OBJC-DESCRIPTORS.md` 第 4.22 节） |
> | audit token 的 pid / euid / pidversion | helper 的内存地址、`Vk*` handle 数值 |
> | 时间戳与耗时 | 共享内存的快照 |
>
> **D108**：日志必须**按 client 分标签**（D33），且一个 client 不得读到另一个 client 的日志。helper 的日志写在 root 拥有的目录下，客户端通过 `EVENT_LOG` 只能收到与自己有关的条目。

### 7.8 速率与资源耗尽

> **D109**：第 3.5 节的配额表与第 2.6 节的上限表合起来是 DoS 防御。补三条执行规则：
>
> 1. **速率限制的处置是延迟，不是拒绝**（第 3.5 节）。拒绝会让一个短暂突发的正常客户端失败；延迟只让它变慢。只有持续 10 s 打空令牌桶才视为恶意并关连接。
> 2. **helper 的工作线程池有固定上限**（= 可用 CPU 数，不随客户端数增长），每个 client 在池里的并发度上限是 `min(4, 池大小)`。否则 N 个 client 各发 64 个并发请求会创建 64N 个线程。
> 3. **管线编译必须在独立的、更小的池里**（上限 2 个线程）。它是唯一的长耗时 CPU 密集操作，和短请求混在一个池里会让短请求被饿死。
>
> **D110**：全局内存闸门见 D39。补一条：helper 必须**自己监控自己的 RSS**，超过宿主物理内存的 25% 时主动驱逐着色器缓存（`ShaderCacheOptions` 的内存容量上限，`40-RUNTIME-VULKAN.md` 第 2.4 节 `DEFAULT_MEMORY_CAPACITY`）。理由：helper 是 root daemon，被 jetsam 杀掉的代价是全部客户端的 `DeviceLost`。

---

## 8. launchd 与监督

### 8.1 为什么是 launchd daemon 而不是 XPC service bundle

两种形态可选，必须选对：

| 形态 | 位置 | 实例数 | 身份 |
|---|---|---|---|
| **XPC service bundle** | `Metal2Vu.bundle/Contents/XPCServices/…` | **每个调用方一个实例** | 继承调用方的用户与部分沙箱 |
| **launchd daemon** | `/usr/local/libexec/metal2vu-helper` + `/Library/LaunchDaemons/net.metal2vu.helper.plist` | **全系统一个** | root，自己的沙箱 |

> **D111**：**选 launchd daemon。** `INFERRED`。四条理由：
>
> 1. **Vulkan device 必须只有一个。** 上游对同一物理设备 + 相同 options 返回同一个 `Device`（D30），但那是进程内的。每客户端一个 helper 实例意味着每个实例各建一个 `VkDevice`，每个各带一份 LLVM —— 内存开销乘以客户端数。
> 2. **IOSurface 的跨进程桥需要一个共同的第三方。** WindowServer 产出的 scanout surface 要被 helper 写，而 helper 又要被普通 app 的 helper 看到吗？不 —— 一个 helper 就没有这个问题。
> 3. **generation 的持久化需要 root**（D74）。
> 4. **管线缓存与着色器缓存应当全系统共享**（D88/D89）。每客户端一个实例会让每个实例各 warm 一遍。
>
> 代价：root daemon 的攻击面（第 7 节的全部内容都是为此而写）。这个代价是必须付的 —— 第 1 项的内存开销在一台只有几 GB 的云实例上是致命的。
>
> `70-BUILD-PACKAGE.md` 第 6.1 节的布局表已经按 daemon 形态写（`/usr/local/libexec/metal2vu-helper` + `/Library/LaunchDaemons/net.metal2vu.helper.plist`），本文与之一致。

### 8.2 launchd plist 的形态

`INFERRED`。路径与所有权取自 `70-BUILD-PACKAGE.md` 第 6.1 节（`root:wheel`，`0644`）。

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>                 <string>net.metal2vu.helper</string>

  <!-- 按需启动：第一个 MachServices 查找触发 -->
  <key>MachServices</key>
  <dict>
    <key>net.metal2vu.helper</key> <true/>
  </dict>

  <key>ProgramArguments</key>
  <array>
    <string>/usr/local/libexec/metal2vu-helper</string>
    <string>--config</string>
    <string>/Library/GPUBundles/Metal2Vu.bundle/Contents/Resources/helper.json</string>
  </array>

  <!-- 崩溃后重启；由 PathState 提供人工闸门（D84） -->
  <key>KeepAlive</key>
  <dict>
    <key>SuccessfulExit</key>      <false/>
    <key>Crashed</key>             <true/>
    <key>PathState</key>
    <dict>
      <!-- 文件存在则不重启。D84 的 stop 标记 -->
      <key>/var/db/net.metal2vu/stop</key> <false/>
    </dict>
  </dict>

  <key>ThrottleInterval</key>      <integer>10</integer>
  <key>ExitTimeOut</key>           <integer>15</integer>

  <key>UserName</key>              <string>root</string>
  <key>GroupName</key>             <string>wheel</string>
  <key>ProcessType</key>           <string>Interactive</string>

  <key>EnvironmentVariables</key>
  <dict>
    <!-- 刻意为空。全部 VK_* 由 helper 自己 setenv（D106 第 1 条） -->
  </dict>

  <key>SoftResourceLimits</key>
  <dict>
    <key>NumberOfFiles</key>       <integer>4096</integer>
  </dict>

  <key>StandardErrorPath</key>     <string>/var/log/net.metal2vu/stderr.log</string>
</dict>
</plist>
```

逐键说明：

| 键 | 取值 | 为什么 |
|---|---|---|
| `MachServices` | 一个服务名 | **按需启动**。helper 不该在没有 Metal 客户端时占内存（云实例内存紧） |
| `KeepAlive.Crashed` | true | 崩溃重启（D84 允许重启的那几行） |
| `KeepAlive.SuccessfulExit` | false | 正常退出（`m2v_shutdown` 之后）不重启。helper 在最后一个连接断开后空转 60 s 自行退出 |
| `KeepAlive.PathState` | `stop` 文件不存在才启动 | D84 的"禁止自动重启"闸门。比 `launchctl unload` 好：它跨重启保持 |
| `ThrottleInterval` | 10 s | 配合 D85 的断路器。launchd 的默认是 10 s，显式写出来是为了让它成为契约 |
| `ExitTimeOut` | 15 s | `SIGTERM` 到 `SIGKILL` 的窗口。要够 helper 跑完 `process_exiting`（`40-RUNTIME-VULKAN.md` 第 5 节：进程退出路径必须调用它，避免把 Vulkan 对象泄给驱动） |
| `ProcessType` | `Interactive` | 它在显示路径上，不能被当后台任务降频。这一项对帧率直接可见 |
| `EnvironmentVariables` | **空** | D106 第 1 条 |
| `RunAtLoad` | **不设** | 与 `MachServices` 的按需启动冲突 |
| `LimitLoadToSessionType` | **不设** | daemon 不属于任何 session |
| `Sockets` | **不设** | 走 Mach service，不走 socket |

> **D112**：**没有 `EnableTransactions`。** 它要求 helper 用 `xpc_transaction_begin/end` 告诉 launchd"我现在闲了可以被杀"。对我们不合适：helper 持有 Vulkan device、着色器缓存与管线缓存，被杀再起的代价很高，而"闲"的判定（没有在途命令缓冲）与"可以被杀"（客户端还持有一堆对象）不是一回事。改用 helper 自己的空闲退出（最后一个连接断开后 60 s）。
>
> **D113**：**不签 entitlement、不走 `com.apple.security.*`。** 研发期 SIP/AMFI 关闭（`00-OVERVIEW.md` 第 2.4 节），因此 helper 是 ad-hoc 签名的 root daemon，不需要也拿不到 Apple 的私有 entitlement。分发阶段这是一个独立问题，`70-BUILD-PACKAGE.md` 负责。
> `BLOCKED`：**`MachServices` 发布的名字能否被 WindowServer 在它的沙箱里查找到，未实测。** WindowServer 的沙箱配置文件可能限制 `mach-lookup`。关闭方式：Gate H-1。若不行，退路是让 kext 转交一个 Mach port（代价是把一个用户态服务的发现放到内核里，不优雅但可行）。

### 8.3 与 `70-BUILD-PACKAGE.md` 安装布局的对应

| 组件 | 路径（取自 `70-BUILD-PACKAGE.md` 第 6.1 节） | 本文的要求 |
|---|---|---|
| helper 可执行 | `/usr/local/libexec/metal2vu-helper` | `root:wheel 0755`。**第一版不安装**（同进程） |
| launchd plist | `/Library/LaunchDaemons/net.metal2vu.helper.plist` | `root:wheel 0644`。**第一版不安装** |
| helper 配置 | `/Library/GPUBundles/Metal2Vu.bundle/Contents/Resources/helper.json` | **新增项**，需加进该分册的布局表与 `MANIFEST.json`。内容：第 2.6 节的上限（可降不可升）、第 5.5 节的 deadline、日志级别 |
| loader | `…/Contents/Resources/lib/libvulkan.dylib` | helper 用绝对路径打开（D106 第 3 条） |
| Lavapipe | `…/Contents/Resources/lib/libvulkan_lvp.dylib` | 同上 |
| ICD 清单 | `…/Contents/Resources/vulkan/icd.d/lvp_icd.x86_64.json` | `VK_DRIVER_FILES` 指向它 |
| generation 与断路器状态 | `/var/db/net.metal2vu/generation` | **新增项**。`root:wheel 0600`（D74、D85） |
| 着色器缓存 | `/var/db/net.metal2vu/shader-cache/<guest-build>-<component-hash>/` | **新增项**（D89） |
| 管线记录 | `/var/db/net.metal2vu/pipeline-records/<同上>/` | **新增项**（D88） |
| binary archive 重定向目录 | `/var/db/net.metal2vu/archives/` | **新增项**（D105） |
| 崩溃诊断 | `/var/log/net.metal2vu/<generation>/` | **新增项**（D87） |
| quarantine（仅研发） | `/var/db/net.metal2vu/quarantine/` | **新增项**（D98） |
| stop 标记 | `/var/db/net.metal2vu/stop` | **新增项**（D84、D112） |

> **D114**：`70-BUILD-PACKAGE.md` 第 6.5 节的卸载脚本目前只删 `/usr/local/libexec/metal2vu-helper`。**它必须同时删 `/Library/LaunchDaemons/net.metal2vu.helper.plist`（先 `launchctl bootout`）、`/var/db/net.metal2vu/` 整树、`/var/log/net.metal2vu/` 整树。** 不删 `/var/db` 会让下一次安装继承一个旧的 generation 与一个可能已 `stop` 的闸门 —— 后者的表现是"装好了但 helper 不起"，极难查。

### 8.4 切分的前置 Gate

`00-OVERVIEW.md` 第 6 节要求"helper 隔离在接入 WindowServer 之前引入"。下表是切分可以开始的条件。全部 `BLOCKED`。

| Gate | 内容 | 不通过的退路 |
|---|---|---|
| **H-1** | 在目标 guest 上证明：(a) launchd daemon 能启动并发布 `MachServices`；(b) WindowServer 能 `mach-lookup` 到它；(c) 全部 `VK_*` 环境变量在 helper 的 `main` 里生效且 loader 按预期打开；(d) `/var/db/net.metal2vu` 可写；(e) audit token 的 `euid` / `csflags` 取值已记录 | (b) 不通过 → 由 kext 转交 Mach port（D113） |
| **H-2** | 证明 Mach memory entry 的跨进程**可写**映射在 WindowServer 的沙箱下可行（D8），以及 OOL blob 的只读映射可行（D23） | 不通过 → `MTLBuffer.contents` 跨进程返回 `NULL`，CoreAnimation 的直写路径失效 → **切分不可行**，必须回到同进程并另找办法隔离 LLVM（例如把 translator 单独放进 helper，Vulkan 留在客户端进程） |
| **H-3** | 证明 IOSurface 的 Mach right 能从 WindowServer 传到 helper 并被 helper 成功 `IOSurfaceLookupFromMachPort`（或等价 API），且 `IOSurfaceLock`/`Unlock` 的跨进程可见性序列已固定（D104 的 `BLOCKED`） | 不通过 → 显示路径不可切分 |
| **H-4** | 证明上游 `ArgumentEncoder` 暴露足以让外部写入的布局信息（D20） | 不通过 → argument buffer 路径在切分后降级为 B，记入 `60-CAPABILITY-MATRIX.md` 的已知损失 |
| **H-5** | 同进程版本已通过 `80-TEST-HARNESS.md` 的渲染验收，且全部 C ABI 调用点已按第 1.4 节的形状写 | — |

> **D115**：**H-2 是切分的真正单点风险。** 它不通过意味着"helper 隔离"这个方案本身要改形状。因此它应当在**写任何 IPC 代码之前**用一个几十行的探针程序验证（一个 root daemon + 一个普通 app，传一个可写映射过去并双向写）。成本是小时级。

---

## 9. 原稿更正汇总

本节逐条给出对 `analysis/spec-work/bridge-runtime-contract.md` 的处置。**"保留"的条目不在此表中逐一重复**，只列更正、作废与新增。

### 9.1 事实性错误（原稿如此 → 现更正为）

| # | 位置 | 原稿如此 | 现更正为 | 依据 |
|---|---|---|---|---|
| C-1 | 第 0 节 | 上游固定 commit `0dfdbcd59d235e37ba13b87a5ab30835b5bb9e35` | 上游锚定 `219f01365dc4c8eb346816c405b5b17403793764`，产品版本 `0.2.0` | `40-RUNTIME-VULKAN.md` 文档头 |
| C-2 | 第 6.3 节 | "`id` 在 generation 内按 client 单调增加且永不复用"（自建计数器） | **`id` 必须是上游 `ObjectId`**（终身唯一、永不复用，跨 generation 也不复用） | `40-RUNTIME-VULKAN.md` 第 3.2 节明确要求"本项目的 wire 对象表应用它，不用指针"；第 4 节第 10 项把 `ObjectId` 列为上游为本项目提供的基元。原稿自建计数器既是重复劳动又更弱（D14） |
| C-3 | 第 10.5 节 | `Unproven` 映射到 wire category `Unsupported` | **映射到新增的 `Stopped`**，处置是停止 guest 并命名问题、禁止自动重启 | `40-RUNTIME-VULKAN.md` 第 2.9 节与第 7.3 节第 4 条：上游明确"不得猜"。映射成 `Unsupported` 会让客户端走它自己的回退路径，而那个回退基于一个可能是错的答案（D45） |
| C-4 | 第 10.2 节 | 确认 helper 已停止 = "进程死亡、mapping 释放**或** connection invalidation" | 三项必须**全部**成立（"与"，不是"或"）：连接 invalid 或进程已 reap、**且**全部 Mach memory entry 已 `vm_deallocate`、**且**相关 IOSurface 已重新 lock/unlock 一轮 | XPC 连接是一个 Mach port 的生死，共享内存是另一个对象。一个已 `SIGKILL` 但未 reap 的僵尸可以在连接已断的情况下仍持有写映射。原稿用"或"会让 D64 的安全性质失效（D79） |
| C-5 | 第 8.3 节 | "`sha256`：helper 在解析前重算；不匹配拒绝"（作为校验手段） | `sha256` **不是安全检查**（客户端可以同时给出一致的数据和哈希）。它是传输错误检测与缓存键。真正的安全规则是：**OOL 数据必须先整段复制进 helper 私有内存，再对副本算哈希并解析**；绝不原地解析共享内存 | 共享内存是 TOCTOU 面（D21、D95） |
| C-6 | 第 2.4 节 | 跨进程普通 buffer 的 `contents` 为 `NULL`，"除非另有共享映射合同" | **共享映射是必需项，不是可选项。** 它是切分的前置 Gate H-2 | CoreAnimation 大量用 `contents` 直写顶点与 uniform；返回 `NULL` 等于该路径不可用（D8） |
| C-7 | 第 8.4 节 | `encoders` 是"最多 64 项的 array"，每项一个 XPC 字典 | **命令日志是一个 `xpc_data_t` 里的紧凑二进制流**，带 header + oid 表 + 命令数组 | 65536 条命令按字典编码是 65536 次 `xpc_dictionary_create`；且 oid 表的设计使对象表锁在 `SUBMIT` 路径上只加一次（D16、D42） |
| C-8 | 第 8.5 节 | inline blob 上限 1 MiB（= 整条消息的上限） | **256 KiB** | 1 MiB 的字典消息在 WindowServer 主线程上会产生可见停顿；且原稿自己在第 12 节已指出"1 MiB control message 与 64 MiB metallib"自相矛盾（D22） |
| C-9 | 第 8.5 节 | 同步管线编译 deadline 30 s | **4.5 s**，并把上游 `pipeline_creation_wait` / `pipeline_commit_wait` 从默认 4.5 s 降到各 2.0 s | `40-RUNTIME-VULKAN.md` 第 6.6 节：上游默认两项合计最坏 9 s，而 **guest 的 FIFO 检查是 10 s**。原稿的 30 s 意味着 `newRenderPipelineStateWithDescriptor:error:` 可以让 WindowServer 停 30 s（D66） |
| C-10 | 第 8.4 节 | OOL 路径标 `BLOCKED`，并因此要求 fixture 把 metallib 控制在 1 MiB 内 | **OOL 是切分的前置条件**（Gate H-2），不是可选项。真实客户端的 metallib 会超 1 MiB | 全量规格下 fixture 约束不成立（D23） |

### 9.2 因"最小集规格作废"而失效的条目

依据：`00-OVERVIEW.md` 第 4.7 节。

| 原稿位置 | 内容 | 处置 |
|---|---|---|
| 第 2.1 节 | Phase A：10 个 selector 的 IOSurface clear | **作废**。消息集按全量，见第 2.2 节的 34 个 opcode |
| 第 2.2 节 | Phase B：9 个 selector 的 metallib triangle | **作废**。同上 |
| 第 2.3 节 | Phase C：helper isolation，"selector 增量：无" | **保留其结论**（切分不增加 selector），并补齐第 1.4 节的对应表 |
| 第 2.4 节 | Phase D：普通 Metal 客户端的"最小公共对象面" | **作废**。对象面按 `21-OBJC-OBJECT-FAMILY.md` 的全量清单 |
| 第 4.1–4.3 节 | 三张 "snapshot v1" 表（BGRA8 / 单 plane / `vertexDescriptor` 必须 nil 等） | **作废**，由 `22-OBJC-DESCRIPTORS.md` 第 4 节的全量字段表取代（该文第 7.3 节已逐条交接） |
| 第 8.2 节 | 13 个请求 opcode | **扩充到 29 个请求 + 6 个事件**（第 2.2 节），保留原有取值 |
| 第 6.3 节 | 8 个 handle kind | **扩充到 24 个**（第 2.3 节），保留 1–8 的取值 |
| 第 8.4 节 | 3 个命令 kind | **扩充到按 encoder 分段的全量命令集**（第 2.4.2 节），且 opcode 表由生成器从上游 TSV 派生（D17） |
| 第 11 节 | capability 表的 11 行"当前公开回答 false" | **作废**作为规格；它是一张**状态表**而不是契约。全量矩阵与当前状态归 `60-CAPABILITY-MATRIX.md` |
| 第 13 节 | 实施顺序与 Gate 清单 | **保留原则**，Gate 重新表述为第 8.4 节的 H-1…H-5（原稿的 Gate 2/3/4 对应 H-3 / H-5 的一部分 / 第 10 节的 T-07） |

### 9.3 原稿已对基线做出的正确修正（保留）

原稿第 12 节有一张"基线规格修正"表。该表的 **17 条全部成立**，本文继承。关键几条在此点明，以免后续分册回退：

| 原稿修正 | 本文位置 |
|---|---|
| 父对象销毁不使子对象失效（child 强持有 parent） | D37 |
| `dealloc` 只运行一次；幂等性属于 helper 的 `DESTROY` | D36 |
| generation 必须跨进程持久化，进程内静态计数不合格 | D73、D74 |
| helper 必须独立重算长度，不信 `payload_size` | D94 |
| 两轴 import mode（host-buffer 轴 + texture 轴），单轴分类不足 | D103 |
| IOSurface 的授权必须来自 capability/right，ID 只作诊断 | D99 |
| `Completed` / `Error` 是互斥终态 | 第 5.1 节 |
| v1 无 `enqueue`，状态不产生 `Enqueued` | 第 5.1 节 |
| 以上游 completed handler 为 Vulkan 语义完成点，不读 private Vk timeline 猜完成 | D58 |
| `waitUntilCompleted` 只能在终态后返回；deadline 必须先终止为 `Error` | D62、D63 |
| `SUBMIT` 返回 helper logical `completion_value`，不暴露 `VkSemaphore` | D72 |
| `@@:` 通用 IMP 必须删除而非沿用 | 继承；归 `21-OBJC-OBJECT-FAMILY.md` |

### 9.4 本文相对原稿的新增项

| 类 | 新增 |
|---|---|
| 进程模型 | 同进程阶段的 C ABI 白/黑名单（D2）、`m2v_surface_token` 的双形态（D3）、`catch_unwind` 要求（D5）、第 1.4 节的全量对应表 |
| 协议 | `proto_hash`（D9）、`deadline_ms`（D66）、16 个新 opcode、`EVENT_DEGRADATION` / `EVENT_LOG` / `EVENT_DROPPED_DRAW`（D12、D13）、命令日志的二进制布局（D16）、opcode 表由生成器派生（D17）、private primitive type 原样传递（D19） |
| 对象表 | 24 个 kind、`deps` 字段、`pidversion`（D28）、三道检查的顺序（D15）、`SUBMIT` 路径只加一次锁（D42）、9 项新配额、全局内存闸门（D39） |
| 错误 | 3 个新 category（`Stopped` / `WouldDeadlock` / `NotProvisioned`）、`needs` 字段（D44）、`MetalError` 保留 Metal 自己的 domain（D47）、`source_kind` 稳定串由生成器派生（D49）、`userInfo` 白名单（D51） |
| 完成 | helper 侧的 `Accepted` 状态（D53）、`commit_failed` 必须保留编码器信号（D57）、`EVENT_TERMINAL` 的 5 项前置条件与顺序（D58）、D64 的四个分支、**display 路径禁用 `waitUntilCompleted`**（D65）、超时预算表（D66）、shared event 的 MAC token（D68） |
| 崩溃恢复 | 三条检测路径（D75）、第 6.3 节的 11 步与顺序、D79 的"与"判据、24 个 kind 的可重建表、event signaled value 的语义缺口（D81）、IOSurface 跨 generation 存活（D82）、crash-loop 断路器（D85）、诊断包内容（D87） |
| 安全 | 完整威胁模型（D90）、不原地解析共享内存（D95）、translator panic 当作崩溃（D97）、`minImportedHostPointerAlignment` 拒绝（D102）、路径重定向（D105）、helper 自己 `setenv` 并清洗继承环境（D106）、日志白名单（D107）、三条速率执行规则（D109） |
| launchd | 整节（原稿无）。daemon 而非 XPC service bundle 的四条理由（D111）、完整 plist、不用 `EnableTransactions`（D112）、与安装布局的对应表、卸载脚本的补充（D114）、5 个切分 Gate |

---

## 10. 验收与剩余未知

### 10.1 必须建立的测试

| # | 测试 | 阶段 | 判据 |
|---|---|---|---|
| T-01 | **C ABI 形状对账**：对第 1.3 节的每个函数，检查签名只用第 1.2 节白名单里的类型 | 同进程 | 用一个解析 `m2v_abi.h` 的脚本做，进 CI |
| T-02 | **`proto_hash` 一致性**：客户端与 helper 各算一次 | 切分后 | 相等；人为改一个上限后必须不等 |
| T-03 | **对象表隔离**：两个 client，A 猜 B 的 oid（遍历 `1..1000`） | 切分后 | 全部 `ProtocolError` 并关 A 的连接；**B 不受影响** |
| T-04 | **kind 混淆**：把一个 Buffer 的 oid 传给需要 Texture 的消息 | 任一 | `InvalidArgument`；不得崩、不得进上游 |
| T-05 | **generation 失效**：杀 helper，用旧 handle 发请求 | 切分后 | `DeviceLost`；新 `HELLO` 得到的 generation 严格大于旧值；重启后读 `/var/db` 的值与之一致 |
| T-06 | **崩溃恢复**：在有 N 个在途命令缓冲时 `SIGKILL` helper | 切分后 | 客户端存活；每个在途 CB **只终结一次**；每个 block **只调用一次**；旧 handle 全部拒绝；新 generation 可重建（原稿 Gate 4，保留） |
| T-07 | **`waitUntilCompleted` 的处置路径**：让 helper 卡住（用一个人为死循环的 debug 开关） | 切分后 | 10 s 时只出现健康诊断、状态不变；60 s 时 `SIGKILL`；确认已死（D79 三项）之后才返回；全程不伪造终态 |
| T-08 | **display 路径不挂死**：同上，但走 display 提交 | 切分后 | 2.0 s 后重复上一帧；**`waitUntilCompleted` 从未被调用**（用一个断言 + 符号拦截证明） |
| T-09 | **长度字段模糊测试**：对 envelope、blob schema、命令日志的每个长度/偏移/计数字段做边界与溢出注入 | 任一 | 全部 `ProtocolError` 或 `InvalidArgument`；**零崩溃、零断言失败、零越界读**（ASan + 一轮 libFuzzer） |
| T-10 | **TOCTOU**：一个线程写共享内存里的 header，另一个线程发 `SUBMIT` | 切分后 | helper 的解析结果只取决于它复制下来的那一份；无崩溃 |
| T-11 | **metallib 模糊测试**：对一批真实 metallib 做位翻转 | 任一 | translator 的失败全部变成 `CompileFailed`；panic 变成 helper 退出 + 诊断包（不是 WindowServer 崩溃） |
| T-12 | **配额**：逐项打满第 3.5 节的 9 项配额 | 任一 | 对应错误；**打满一项不影响其他 client**；减法不绕回（D40） |
| T-13 | **速率**：以 10× 令牌桶速率发请求 | 切分后 | 被延迟而非拒绝；持续 10 s 后关连接 |
| T-14 | **`Unproven` 处置**：用 debug 开关注入一个 `Unproven` | 任一 | `EVENT_DEVICE_LOST` 的 category 是 `Stopped`；`stop` 标记被写；launchd **不重启**；诊断包含问题名 |
| T-15 | **`WaitWouldDeadlock`**：构造一个自等待 | 任一 | 立即返回 `WouldDeadlock`；命令缓冲进终态 `Error`；**WindowServer 不挂** |
| T-16 | **两轴 import mode 归因**：并发 import 8 个 surface，其中 4 个故意不对齐 | 任一 | 每个 surface 各自报出正确的两轴取值；**不得互相污染**（D103 的专用串行段） |
| T-17 | **crash-loop 断路器**：让 helper 连续崩 5 次 | 切分后 | 第 4 次之后暂停 60 s；第 6 次之后写 `stop` 并不再重启 |
| T-18 | **`dropped_draw` 可观测**：把 `pipeline_creation_wait` 设成 1 ms | 任一 | `EVENT_DROPPED_DRAW` 被投递；`WorkCounts.draws_dropped_*` 非零；**命令缓冲不报错**（这是 Metal 的行为） |
| T-19 | **卸载完整性**：装、跑、卸，再装 | 切分后 | 第二次安装的 generation 从 1 开始；`stop` 标记不残留；helper 正常起（D114） |
| T-20 | **环境清洗**：带 `DYLD_INSERT_LIBRARIES` 与一个假的 `VK_DRIVER_FILES` 启动 helper | 切分后 | 两者都被清掉；loader 打开的是随包那一份；自检记录里能看到被清掉的变量清单 |

T-01、T-04、T-09、T-11、T-12、T-14、T-15、T-18 **在同进程阶段就能跑**（它们测的是 adapter 与错误映射，不是 IPC）。它们应当与第一版一起进 CI。

### 10.2 剩余未知（按影响排序）

| # | 未知 | 影响 | 关闭方式 | 标签 |
|---|---|---|---|---|
| U-01 | **Mach memory entry 的跨进程可写映射在 WindowServer 沙箱下是否可行**（D8、Gate H-2） | **切分方案的单点风险。** 不可行则 `MTLBuffer.contents` 跨进程失效，CoreAnimation 的直写路径断掉，helper 隔离这个方案要换形状 | 一个几十行的探针：root daemon + 普通 app，传可写映射并双向写。小时级（D115） | `BLOCKED` |
| U-02 | **WindowServer 能否 `mach-lookup` 到我们的 `MachServices`**（D113、Gate H-1） | 不行则服务发现要改走 kext 转交 Mach port | 装 plist、从一个模拟 WindowServer 沙箱的进程查一次 | `BLOCKED` |
| U-03 | **IOSurface 的 Mach right 跨进程传递的具体 API 与 entitlement**（Gate H-3；原稿第 9 节已标此 `BLOCKED`） | 显示路径不可切分 | 目标 guest 探针 | `BLOCKED` |
| U-04 | **`IOSurfaceLock`/`Unlock` 的 flags、seed 与跨进程可见性的最终序列**（D104） | D58 第 4 步的实现细节；错了会得到撕裂帧 | 目标 guest 探针（原稿 Gate 2） | `BLOCKED` |
| U-05 | **`ObjectId` 对每一类对象是否都可取、数值表示是什么**（D14） | 决定对象表的键。不可取的 kind 要退回自建计数器 | `cargo doc -p metal2vulkan-runtime` | `BLOCKED` |
| U-06 | **上游 `ArgumentEncoder` 是否暴露足以外部写入的布局信息**（D20、Gate H-4） | argument buffer 路径在切分后是否降级 | 同上 | `BLOCKED` |
| U-07 | **`/var/db` 在 launchd daemon sandbox 下是否可写**（D74） | generation 持久化。不可写则 helper 拒绝启动 | Gate H-1 | `BLOCKED` |
| U-08 | **`VK_*` 与 `DYLD_*` 在 launchd 下的实际传递行为**（D106；`40-RUNTIME-VULKAN.md` 第 6.4 节已标此 `BLOCKED`） | ICD 固定的三重保险是否真的生效 | Gate H-1 + T-20 | `BLOCKED` |
| U-09 | **WindowServer 的 audit token 中 `euid` 与 `csflags` 取值**（D28） | 决定第 7 节的准入策略能否写成白名单 | Gate H-1 的 (e) | `BLOCKED` |
| U-10 | **`xpc_data_t` 在 1 MiB 量级的实际拷贝成本** | 决定 C-8 的 256 KiB 分界是否还要再降 | 同进程阶段用一个微基准测，不需要目标 guest | `BLOCKED` |
| U-11 | **上游 translator 对 MSL `os_log` 的支持情况**（`22-OBJC-DESCRIPTORS.md` 第 4.28 节） | `MTLLogState` 的 handler 会不会永远不触发 | `30-SHADER-AIR.md` 的覆盖率审计 | `BLOCKED` |
| U-12 | **helper 在真实合成负载下的 RSS**（D110） | 决定 25% 的驱逐阈值是否合适，以及云实例的最小内存配置 | 同进程阶段就能测（RSS 的大头是 LLVM 与着色器缓存，与进程形态无关） | `BLOCKED` |

### 10.3 与其他分册的接口

| 分册 | 本文依赖它 | 它依赖本文 |
|---|---|---|
| `20-OBJC-DEVICE.md` | limits 表是 `featureProfile` 的纯函数（D7） | 无 |
| `21-OBJC-OBJECT-FAMILY.md` | 全量 selector 与 encoding（第 2.4.2 节的通用命令段） | 对象的所有权与线程规则必须与第 3、5 节一致 |
| `22-OBJC-DESCRIPTORS.md` | 全部 snapshot 的 POD 定义（第 1.2 节）、R16/R19/R25 的校验、R28 的路径重定向 | 错误档位 A/B/C/D 的 wire 表达（第 4.1 节）、`NSError` 构造（第 4.3 节） |
| `11-KERNEL-DISPLAY.md` | display provider 的超时必须大于编译预算之和（D66） | **display 路径禁用 `waitUntilCompleted`**（D65）、单帧 deadline 2.0 s、超时重复上一帧 |
| `41-IOSURFACE-USERSPACE.md` | surface 几何的重测规则（D100、D101）、lock 时序（D104） | 两轴 import mode 的上报（D103）、跨 generation 存活（D82） |
| `40-RUNTIME-VULKAN.md` | 全部上游 API 事实、`DeviceOptions` 固定配置、错误 variant 全表 | 无 |
| `60-CAPABILITY-MATRIX.md` | 无 | 第 4.2 节的 `needs`、第 6.5 节的已知损失（event signaled value、argument buffer 降级）、degradation code 集合 |
| `70-BUILD-PACKAGE.md` | 安装布局（第 8.3 节） | **5 个新增路径 + 卸载脚本的补充**（D114）、`helper.json` 配置文件 |
| `80-TEST-HARNESS.md` | 无 | 第 10.1 节的 20 个测试，其中 T-06 / T-07 / T-08 / T-17 需要"强杀 helper"这一能力 |
| `90-EVIDENCE-INDEX.md` | 无 | 第 6.7 节的诊断包格式、启动自检的 9 项记录 |
