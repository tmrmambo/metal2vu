# metal2vulkan 接入合同

文档版本：1.0  
状态：**部分被取代**，见下  
固定参考提交：`0dfdbcd59d235e37ba13b87a5ab30835b5bb9e35`（**已过时**）

> [!IMPORTANT]
> 三处已被取代，由 `docs/spec/30` / `31` / `32` / `40` 四份分册接管：
>
> 1. **第 5 节「禁止的重复实现」已作废。** 现决定**吸收 metal2vulkan 并自行维护**（fork 为 workspace 内独立 crate，保留 git 历史以便 rebase）。见 `docs/spec/00-OVERVIEW.md` 第 4.6 节。
> 2. **固定提交已前移**至 `219f01365dc4c8eb346816c405b5b17403793764`（2026-10-29）。见 `docs/spec/40-RUNTIME-VULKAN.md` 第 0 节。
> 3. **第 9 节引用的「2135 项中 958 项实现、828 项缺失」被误读过。** 那组数字的计数单位是**macOS 27 SDK 的 Metal 公共 API 条目**，不是 AIR 指令；AIR 侧上游没有指令级覆盖表。见 `docs/spec/30-SHADER-AIR.md`。
>
> 另有一条本文未预见的事实：**驱动根本不解析 AIR。** Metal.framework 自己解析 metallib，驱动通过一个 **compiler plugin dylib** 接入，接口是 40 个 C 符号。AIR→SPIR-V 属于 plugin 侧。见 `docs/spec/32-COMPILER-PLUGIN.md`。

## 1. 决定

项目直接复用 metal2vulkan 的完整 AIR 编译与规划子系统。

编译结果不是单独的 SPIR-V 字节。

必须一起保留 stage SPIR-V、layout、interface、requirements、BindingPlan、固定功能状态和 cache key。

不再增加第二个 AIR 转换层或 SPIR-V 修补层。

项目需要额外适配层，但它不转换 AIR 或重算 binding。

## 2. 正确链路

```text
metallib bytes
    |
    v
metal2vulkan-air
  container + bitcode + AIR ABI
    |
    v
metal2vulkan compiler
  canonicalize + lower + structurize
  SPIR-V build + link + verify
    |
    v
PipelineArtifact
  - stage SPIR-V
  - layout + interface
  - requirements + BindingPlan
  - fixed-function state + cache key
    |
    v
metal2vulkan-runtime
  Metal object semantics
  Vulkan resource and command mapping
    |
    v
ash -> Vulkan loader -> Lavapipe ICD
```

## 3. 三个上游部分

| 上游部分 | 真实职责 | 项目决定 |
|---|---|---|
| `crates/metal2vulkan-air` | metallib、LLVM bitcode、AIR metadata、intrinsics、canonicalization | 直接复用 |
| `crates/metal2vulkan` | lowering、memory plan、CFG、SPIR-V、链接和校验 | 直接复用 |
| `crates/metal2vulkan-runtime` | Metal 风格对象、Vulkan 资源、命令和同步 | 直接复用 |

产品代码应从 `metal2vulkan-runtime` 或 `metal2vulkan` 的公开 API 进入。

`metal2vulkan-air` 由 translator 的精确 revision 依赖。

只有分析工具才应直接调用 `metal2vulkan-air`。

三个产品 crate 必须来自同一 Git revision。

编译主线证据位于上游：

- `docs/ARCHITECTURE.md`
- `crates/metal2vulkan/src/pipeline/compile.rs`
- `crates/metal2vulkan-runtime/src/`

## 4. 项目必须新增的适配层

### 4.1 Objective-C ABI adapter

把真实 Metal selector 转成稳定请求。

它负责：

- Objective-C 类型和 ownership。
- descriptor snapshot。
- block 和 NSError。
- capability 查询。
- 对象 ID 映射。

它不读取 AIR 内部格式。

### 4.2 IPC adapter

把进程内调用转成版本化消息。

它负责：

- client namespace。
- object ID。
- generation。
- sequence 和 completion。
- 消息长度和配额。
- IOSurface Mach right。

它不改写 SPIR-V。

### 4.3 Runtime adapter

它位于 `metal2vulkan-runtime` 外侧。

它负责：

- wire descriptor 到上游类型。
- 完整保留 PipelineArtifact。
- 完整保留 BindingPlan、layout、interface 和 requirements。
- 不自行推导 descriptor binding 或 push constant。
- 上游对象到 helper object ID。
- typed error 到稳定 wire error。
- capability profile 限制。
- deadline、取消和日志。

它不得复制上游 Device、Queue 或 Encoder。

### 4.4 IOSurface adapter

上游只提供 host-memory 和 IOSurface plane 的 stand-in。

本项目负责：

- 创建和接收真实 IOSurface。
- 读取 plane、stride 和 alloc size。
- 在 helper 地址空间重新映射。
- 维护 surface lifetime。
- 区分 in-place、shadow 和 copy。
- 在 Vulkan 完成后处理可见性。

### 4.5 System adapter

本项目还要实现：

- Metal plugin 注册。
- IOGPU service。
- IOUserClient。
- display provider。
- display sink。
- 签名、安装和启动。

这些都不属于 AIR 转换。

## 5. 禁止的重复实现

不得新写：

- metallib parser。
- LLVM bitcode reader。
- AIR metadata parser。
- AIR intrinsic 表。
- AIR canonicalizer。
- AIR 到 SPIR-V lowering。
- SPIR-V builder。
- SPIR-V 修补器或黑盒后处理器。
- descriptor binding 和 push constant 重算。
- pipeline artifact 或 cache key 的第二套格式。
- 第二套 Metal runtime。
- 手写 Gallium ABI。

旧原型中的相关代码只保留为失败样本。

## 6. 补缺规则

遇到上游缺失 AIR 指令时，按以下顺序处理：

1. 建立最小真实 metallib fixture。
2. 记录上游 typed error。
3. 在固定提交上写最小补丁。
4. 把补丁放在上游正确 crate。
5. 添加 SPIR-V 和像素回归测试。
6. 优先向上游提交。
7. 在本项目保存补丁哈希。

不得在外面加黑盒 AIR 或 SPIR-V 重写器。

如果上游工件不正确，应修补对应上游 crate。

修补后必须重跑 verifier、binding 和像素测试。

## 7. Vendor 方式

计划使用：

```text
vendor/metal2vulkan/
crates/m2vk-adapter/
```

`vendor/metal2vulkan/` 保存固定提交。

`crates/m2vk-adapter/` 只保存项目适配。

本地补丁应保持很小，并形成 patch manifest。

固定快照的产品版本是 `0.2.0`。

该版本在该提交时尚未发布到 crates.io。

不得改用旧的 crates.io `0.1.0`。

上游锁定 Rust `1.98.1`。

runtime API 仍标记为 unstable。

所有缓存必须绑定完整 Git SHA 和上游语义版本。

## 8. Vulkan 与 Lavapipe

metal2vulkan-runtime 是 Vulkan 使用者。

它不是 Vulkan driver。

项目仍须随 guest 打包：

- Vulkan loader。
- Lavapipe ICD。
- ICD manifest。
- Mesa 和 LLVM 运行依赖。

首选标准 loader 动态加载 ICD。

只有目标 guest 证明该方式失败，才评估静态链接。

## 9. 许可证边界

固定提交的产品 crate 使用：

`GPL-2.0-or-later OR LGPL-3.0-or-later`

分发前必须决定所选许可证。

如果使用 LGPL，还要满足替换和重新链接条件。

Mesa 与 LLVM 也要保存逐组件许可证清单。

该快照仍是 Beta。

上游统计为 2,135 项中 958 项实现。

另有 828 项缺失，349 项不在范围内。

macOS CI 不运行 Vulkan device 测试。

维护主要集中在一个人。

这些风险要求固定 SHA、保留补丁，并建立本地 corpus。

## 10. 接入验收

接入完成必须证明：

- 项目没有调用旧 `compiler/air.rs`。
- 项目没有调用旧 Gallium ABI。
- 真实 metallib 由固定提交编译。
- 每个 SPIR-V stage 有哈希和 verifier 结果。
- PipelineArtifact、BindingPlan 和 requirements 被完整消费。
- 项目没有自行推导 Metal binding 编号。
- 项目没有 SPIR-V 修补层。
- triangle 像素与参考结果一致。
- 不支持的 AIR 返回明确错误。
- 上游 commit 和补丁哈希进入构建清单。
