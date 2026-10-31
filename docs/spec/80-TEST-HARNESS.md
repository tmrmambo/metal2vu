# 80 自动化实验管线

文档版本：1.1
基线日期：2026-10-30
对应组件：组件清单第 7 项（自动化测试管线）
上级文档：`docs/spec/00-OVERVIEW.md`

**1.1 修订**（在 1.0 基础上增补，无结论推翻）：

| 变更 | 位置 | 原因 |
|---|---|---|
| 新增 2.3.5：guest 内 ARD/VNC 通道 | 2.3.5，并连带修订 1.3、2.1 的 T3/T4 行、2.2 能力表、3.3.4、4.2 的 B8b、5.3 | 1.0 把 L2 的画面能力写成"只有单发 `screencapture`"，漏了 macOS 自带的可程序化 VNC 服务端。它给 L2 补回**输入注入**与持续连接，但不补回归因能力 |
| 新增 3.3.8：自定义镜像与 ISO 槽位工具组 | 3.3.8 | 1.0 的 `env_create` 接受 `from_iso`，但工具面里没有任何工具能产出一个 `iso_id`。1.2 的平台约束此前只停在调研层，未落到工具层 |
| 新增 H-011 / H-012 / H-013 | 4.3 | 2.3.5 引入的两个未实测点，以及 CI 计费口径 |

## 0. 本文作用与写作约束

本项目至今**从未在目标 guest 上执行过任何代码**。所有 `KNOWN` 标签都来自静态样本分析，`TESTED` 标签数量为零。这不是某个模块的缺口，而是整个项目的瓶颈：没有运行证据，`10`/`11`/`20` 三个分册的实现契约无法收敛，只能继续靠推断堆叠。

本文定义把"跑一次实验"从人工操作变成一次函数调用的管线。设计目标按优先级排列：

1. **单次实验零人工干预**：从镜像就绪到证据落盘，中间不需要人点任何东西。
2. **同一套自动化代码在本地 KVM 与 Vultr 两边都能跑**：平台差异收敛到一个 trait 的两个实现里，测试用例本身不感知。
3. **失败可自动归档并可被模型直接消费**：证据是结构化 JSON + 带哈希的产物目录，不是一堆散落的截图。
4. **不依赖 guest 桌面可用**：前期恰恰在修显示，GUI 自动化不能成为前置条件。

写作约束：

- 每条结论带证据标签（`KNOWN` / `INFERRED` / `BLOCKED` / `TESTED`）与来源 URL。
- 命令与 API 调用按可直接照抄编写。
- 本文对外部网页内容均为转述，不作连续摘录。**内容已转述以符合许可限制。**

---

## 1. 平台能力调研结论

本节是设计的事实基础。先查清，再设计。

### 1.1 Vultr 实例生命周期 API

`KNOWN`（来源：Vultr 官方 Go 客户端 `govultr` 的 `instance.go`，<https://github.com/vultr/govultr/blob/master/instance.go>）

所有路径前缀 `https://api.vultr.com/v2`，鉴权为 `Authorization: Bearer ${VULTR_API_KEY}`。

| 动作 | 方法与路径 | 请求体要点 |
|---|---|---|
| 创建实例 | `POST /v2/instances` | `region`、`plan`、`os_id` 或 `snapshot_id` 或 `iso_id`、`sshkey_id[]`、`label`、`tags[]`、`enable_ipv6`、`user_data`、`firewall_group_id` |
| 查询实例 | `GET /v2/instances/{instance-id}` | — |
| 列出实例 | `GET /v2/instances` | 游标分页 |
| 修改实例 | `PATCH /v2/instances/{instance-id}` | — |
| 销毁实例 | `DELETE /v2/instances/{instance-id}` | 数据不可恢复，IP 释放 |
| 开机 | `POST /v2/instances/{instance-id}/start` | — |
| 关机 | `POST /v2/instances/{instance-id}/halt` | — |
| 重启 | `POST /v2/instances/{instance-id}/reboot` | — |
| 重装 | `POST /v2/instances/{instance-id}/reinstall` | `hostname` 可选 |
| **恢复快照** | `POST /v2/instances/{instance-id}/restore` | `{"snapshot_id": "..."}` 或 `{"backup_id": "..."}` |
| 带宽查询 | `GET /v2/instances/{instance-id}/bandwidth` | 返回按日期键的 `incoming_bytes` / `outgoing_bytes` |
| 同宿主邻居 | `GET /v2/instances/{instance-id}/neighbors` | — |

实例对象中与 harness 相关的字段：`id`、`status`、`power_status`、`server_status`、`main_ip`、`default_password`、`os_id`、`snapshot_id`、`image_id`、`plan`、`region`、`features[]`、`allowed_bandwidth`、`vcpu_count`、`ram`、`disk`、`kvm`。

**关键点**：`default_password` 仅在创建响应中返回，后续 `GET` 不再带出。创建时必须立即落盘到凭据存储，否则只能重装。`INFERRED`，按 govultr 的 `omitempty` 标注推断，需实测确认。

字段 `kvm` 是一个 URL 字符串，历史上指向网页控制台。它的语义与可用性见 1.3。

### 1.2 Vultr 快照与自定义 ISO

`KNOWN`（来源：`govultr/snapshot.go`、`govultr/iso.go`，<https://github.com/vultr/govultr/blob/master/snapshot.go>、<https://github.com/vultr/govultr/blob/master/iso.go>）

快照：

| 动作 | 方法与路径 | 请求体 |
|---|---|---|
| 从实例建快照 | `POST /v2/snapshots` | `{"instance_id":"...","description":"..."}` |
| 从 URL 建快照 | `POST /v2/snapshots/create-from-url` | `{"url":"...","description":"...","uefi":true}` |
| 查询快照 | `GET /v2/snapshots/{snapshot-id}` | 看 `status` |
| 列出快照 | `GET /v2/snapshots` | — |
| 改描述 | `PUT /v2/snapshots/{snapshot-id}` | `{"description":"..."}` |
| 删除快照 | `DELETE /v2/snapshots/{snapshot-id}` | — |

快照对象字段：`id`、`date_created`、`description`、`size`、`compressed_size`、`status`、`os_id`、`app_id`。

**`create-from-url` 带 `uefi` 布尔字段**，这是 Vultr 支持 UEFI 引导的直接证据（`KNOWN`，来源同上）。官方文档也说明快照可从 RAW 镜像 URL 创建、且跨所有区域可用（转述自 <https://docs.vultr.com/product-overviews/snapshots>）。

快照创建耗时：官方文档给出的量级是**最长约 30 分钟**，随实例尺寸变化（转述自 <https://docs.vultr.com/products/compute/cloud-compute/features/snapshots>）。这个数字决定了 golden snapshot 必须是一次性成本，不能进入单次实验回路。

自定义 ISO：

| 动作 | 方法与路径 | 请求体 |
|---|---|---|
| 上传 ISO | `POST /v2/iso` | `{"url":"https://..."}` |
| 查询 ISO | `GET /v2/iso/{iso-id}` | 看 `status` |
| 列出 ISO | `GET /v2/iso` | 返回 `md5sum`、`sha512sum` |
| 删除 ISO | `DELETE /v2/iso/{iso-id}` | — |
| 公共 ISO 库 | `GET /v2/iso-public` | — |
| 挂载到实例 | `POST /v2/instances/{instance-id}/iso/attach` | `{"iso_id":"..."}`，会重启实例 |
| 卸载 | `POST /v2/instances/{instance-id}/iso/detach` | 会重启实例 |
| 挂载状态 | `GET /v2/instances/{instance-id}/iso` | `state` ∈ `ready` / `isomounting` / `isomounted` |

**三条硬约束**（`KNOWN`）：

1. **ISO 只能由 Vultr 从公开 URL 拉取**，没有直传接口（`ISOReq` 只有 `url` 字段，来源同上）。因此 harness 必须自带一个 ISO 托管端点——对象存储桶或一台长驻小实例上的 HTTP 服务。
2. **单账户最多 2 个 ISO**（转述自 <https://docs.vultr.com/products/orchestration/isos/faq>）。这意味着不能用"每次实验上传一个新 ISO"的模式，必须把 ISO 当作稀缺槽位管理：一个槽位放安装介质，另一个槽位放救援/payload 介质。
3. **ISO 体积上限 10 GB**（转述自 <https://docs.vultr.com/how-to-upload-and-use-custom-isos-on-vultr>）。macOS 安装介质加 OpenCore EFI 在此之内，但要留意不要把整个 `InstallAssistant.pkg` 和恢复镜像一起塞进去。

ISO 上传后 `md5sum` 与 `sha512sum` 由平台回报，harness 必须与本地计算值比对，这是镜像完整性的唯一可得校验点。

### 1.3 Vultr 控制台：noVNC，无可编程 VNC 端点

这是本文最重要的一条调研结论。

`KNOWN`：Vultr 的实例控制台是**基于 noVNC 的网页客户端**。官方 FAQ 与各机型的连接文档都明确写了用的是 noVNC，并列举了剪贴板共享、虚拟键盘、`CTRL+ALT+DEL` 等网页端功能（转述自 <https://docs.vultr.com/vultr-web-console-faq> 与 <https://docs.vultr.com/products/compute/cloud-compute/connection/vultr-console>）。

`KNOWN`：**Vultr API v2 没有任何返回 VNC 主机/端口/密码的端点。** 证据是官方 Go 客户端 `govultr` 的仓库文件清单中不存在 `console.go` / `vnc.go`，且 `InstanceService` 接口的 36 个方法里没有任何一个与控制台相关（来源：<https://api.github.com/repos/vultr/govultr/contents/> 与 `instance.go` 的接口定义）。官方 MCP 服务器同样不提供——它被明确声明为只读、且不含任何花钱的工具（转述自 <https://docs.vultr.com/reference/mcp-server/overview>）。

`INFERRED`：网页控制台背后必然存在一个 websockify/noVNC 的 WebSocket 端点，由门户会话态（cookie）而非 API key 授权。它不是公开契约，随时可能变。

**结论与设计后果**：

- 在 Vultr 上**不能**用标准 VNC 客户端库做截图与输入注入。把 noVNC 的 WebSocket 端点逆出来当生产依赖是错误的工程决策：未声明接口 + 会话态鉴权 + 可随时变更，会让整条管线变成会无声腐烂的东西。
- 因此 **Vultr 层的默认人机通道是 SSH**，截图与输入注入是**本地 KVM 层独有能力**。
- Vultr 上需要看画面时，只能"从 guest 内部看自己"，而不是"从 host 看 guest"。有两条 guest 内路径：单发截屏（2.8 的 `screencapture`）与**持续连接的 ARD/VNC**（2.3.5，可带输入注入）。两条都有同一个致命缺陷：guest 没进系统或 WindowServer 已死时都不可用——而这正是本项目前期最常见的状态。
- 由此推出 **2.1 的测试分层必须把"需要 host 层画面"的用例全部钉在本地层**，Vultr 层只跑"SSH 可达即可判定"的用例。这不是妥协，这是平台能力的直接推论。

如果后续确实需要在 Vultr 上拿画面而 SSH 已不可用，唯一正当的手段是人工打开网页控制台截图并手动归档，并在证据 JSON 中标注 `capture_method: "manual-portal"`。不要把它自动化。

### 1.4 Vultr 串口/串行控制台：没有

`KNOWN`（否定性证据）：Vultr 的全部"连接到实例"文档只提供三条路径——网页 noVNC 控制台、OpenSSH、PuTTY（转述自 <https://docs.vultr.com/products/compute/instances/cloud-gpu/connection> 与 <https://docs.vultr.com/products/compute/instances/vx1-cloud-compute/connection>）。官方故障排查文档在 SSH 不可用时给出的替代方案也是网页控制台，而不是串口（转述自 <https://docs.vultr.com/support/products/compute/how-to-troubleshoot-ssh-connectivity-issues>）。`govultr` 中不存在任何串口相关服务。

**设计后果，这是整条管线最硬的约束之一**：

- **early boot 与 kernel panic 的日志在 Vultr 上无法程序化获取。** 没有串口就没有 `panic` 时的文本输出通道；panic 发生时 guest 已经不能跑 SSH，而画面又只在网页控制台里。
- 因此 **panic 期证据必须靠"重启后回捞"**：macOS 会把 panic 报告写进 `/Library/Logs/DiagnosticReports/*.panic`（转述自 Apple 社区文档 <https://discussions.apple.com/thread/251053592>）。管线的 panic 处理流程是：检测到无响应 → 强制重启 → 等 SSH → 回捞 panic 报告。这要求**根分区在 panic 后仍可挂载**，即 panic 不能发生在写入 panic 报告之前。
- **所有新的内核侧改动必须先在本地 KVM 上跑**，因为只有本地有串口。把一个未经本地串口验证的 kext 直接推到 Vultr 上，一旦 early panic，就会得到一个无法诊断的黑屏实例，只能销毁重建。这条规则写进 2.1 的提升门槛。

### 1.5 Vultr 固件、引导与设备暴露：部分未确证

| 项目 | 状态 | 依据 / 查清方法 |
|---|---|---|
| UEFI 引导 | `KNOWN`：支持 | `POST /v2/snapshots/create-from-url` 的 `uefi` 字段（来源：`govultr/snapshot.go`） |
| 自定义引导链 | `INFERRED`：可行 | 自定义 ISO + UEFI 快照两条路都允许自带引导器，OpenCore 作为 `EFI/BOOT/BOOTX64.EFI` 应可被固件拾取。未实测 |
| 磁盘控制器型号 | `BLOCKED` | Vultr 块存储文档提到 VirtIO 卷在 guest 内呈现为 `vtbd` 设备、NVMe 卷呈现为 `nda` 设备（转述自 <https://docs.vultr.com/products/storage/block-storage/mount/freebsd>），说明平台使用 VirtIO 与 NVMe，但**系统盘的具体控制器未确证**。查清方法：4.1 的 E0-L2 首启探针，`ioreg -r -c IOPCIDevice -l` 读 vendor/device ID |
| 网卡型号 | `BLOCKED` | 同上，同一次探针一并取得 |
| NVRAM 持久性 | `BLOCKED` | OpenCore 要固化 `csr-active-config` 到 NVRAM，必须确认实例重启后 EFI 变量是否保留。查清方法：写入一个标记变量，重启后读回 |
| 串口 | `KNOWN`：无 | 见 1.4 |

**`vtbd`/`nda` 这条线索指向本项目最大的平台风险**，详见第 5 节。macOS 原生不含 VirtIO 块设备驱动；社区在 KVM 上跑 macOS 的通行做法是把启动盘接成模拟 AHCI，网卡用 `vmxnet3` 或 `e1000-82545em`（转述自 <https://github.com/PassthroughPOST/Hackintosh-KVM/blob/master/kexts/Other/virtio-net.kext/Contents/Resources/readme.md> 与 <https://github.com/mateussouzaweb/kvm-qemu-virtualization-guide/blob/master/Docs/08%20-%20MacOS%20Virtualization.md>）。网卡侧存在第三方驱动 `virtio-net-osx`（<https://github.com/pmj/virtio-net-osx>），但**块设备侧没有等价物**，而块设备是启动的必要条件，不是可选优化。

因此 **"Vultr 上能不能启动 macOS"本身是一个未验证的前置条件**，不是实现细节。它必须是整条管线的第一个实验（见 4.1 的 E0）。

### 1.6 Vultr 机型与计费粒度

`KNOWN`：计费按小时，最小计费单位为 1 小时，常规 Cloud Compute 机型的月度小时数封顶在 672 小时（转述自 <https://www.vultr.com/products/regular-performance-compute/> 与 <https://docs.vultr.com/support/platform/billing/how-am-i-billed-for-my-servers>）。GPU 与 VX1 机型按实际月小时数计费、不封顶在 672（转述自 <https://docs.vultr.com/support/platform/billing/how-are-gpu-products-billed-differently>）。

**设计后果**：

- **最小计费单位 1 小时意味着"短实验也付满 1 小时"**，所以频繁创建销毁实例在经济上是浪费。正确模式是：一台长驻实验实例反复 `restore` 快照，而不是每次 `create` + `delete`。这与 1.2 的快照耗时结论指向同一个架构。
- 快照本身单独计费，陈旧快照必须有 GC 策略（见 3.4 的保留规则）。
- 出站带宽计费，归档回传要走压缩；证据包如果包含完整 `.logarchive`，单次可达数百 MB。

机型选择不写死 plan ID，而是在运行时查询：

```bash
curl -s "https://api.vultr.com/v2/plans?type=vc2&per_page=100" \
     -H "Authorization: Bearer ${VULTR_API_KEY}" \
  | jq '.plans[] | select(.vcpu_count>=4 and .ram>=8192) | {id,vcpu_count,ram,disk,monthly_cost}'
```

`type=vc2` 对应共享 CPU 的常规 Cloud Compute。`INFERRED`：macOS 26 需要 ≥4 vCPU、≥8 GB RAM 才能在可接受时间内完成安装与 Metal 实验；Lavapipe 是 CPU 渲染器，vCPU 数直接决定帧率，实验机型偏大比偏小划算。

### 1.7 本地 QEMU 侧的对应能力

这一侧能力远强于 Vultr，也正因如此必须谨慎：**在本地能做而在 Vultr 不能做的事，不允许成为测试用例的隐含前提。**

`KNOWN`（来源：QEMU QMP 参考手册 <https://www.qemu.org/docs/master/interop/qemu-qmp-ref.html>）

**截图** —— `screendump`（自 0.14，需 `CONFIG_PIXMAN`）。参数 `filename`（必填）、`device`（可选，显示设备 ID）、`head`（可选）、`format`（可选，`png` 或 `ppm`，默认 `ppm`，`format` 自 7.1 起可用）：

```json
{ "execute": "screendump",
  "arguments": { "filename": "/var/harness/shot.png", "format": "png" } }
```

**输入注入** —— `input-send-event`（自 2.6）。参数 `device`（可选）、`head`（可选）、`events`（`InputEvent` 数组）。事件类型 `key` / `btn` / `rel` / `abs` / `mtt`。按键用 `{"type":"qcode","data":"ctrl"}` 形式的 QKeyCode；绝对定位用 `abs` 事件分别给 `x`、`y` 轴值；按钮用 `btn` 配 `down` 布尔与 `button` 名。三个官方示例分别是按下左键、组合 `ctrl-alt-del`、移动到绝对坐标。手册同时说明各 console 在 QOM 树的 `/backend/console[$index]` 下可见，带 `device` 链接与 `head` 属性，可据此把 console 映射到具体显示设备。

**VNC 密码** —— `set_password`（自 0.14，选项结构自 7.0）。`protocol` 取 `vnc`，`password` 为新密码，`connected` 对 VNC 目前只实现了 `keep`。配套 `expire_password` 可设 `now` / `never` / `+INT` / 绝对秒。这给了 harness 一个干净的做法：启动时 `-vnc 127.0.0.1:N,password=on`，随后通过 QMP 注入一次性密码，不把密码写进命令行。

**快照** —— `snapshot-save` / `snapshot-load` / `snapshot-delete`（均自 6.0，以后台 job 形式）。参数 `job-id`、`tag`、`vmstate`（保存 vmstate 的块设备节点名）、`devices`（块设备节点名数组）。手册明确：命令返回不代表完成，必须用 job 命令与 `JOB_STATUS_CHANGE` 事件判定完成并取错误详情；保存/加载期间 guest CPU 可能被停止；要一致性快照就必须把所有可写块设备节点都列进 `devices`。

```json
{ "execute": "snapshot-load",
  "arguments": { "job-id": "load-golden-01", "tag": "golden",
                 "vmstate": "disk0", "devices": ["disk0"] } }
```

完成判定：轮询 `{"execute":"query-jobs"}`，等 `status` 变为 `concluded` 并检查有无 `error`。

**串口重定向** —— 命令行侧，不走 QMP：

```bash
-chardev socket,id=ser0,host=127.0.0.1,port=4555,server=on,wait=off,logfile=/var/harness/serial.log \
-serial chardev:ser0
```

`logfile=` 让串口输出无条件落盘，这是 panic 期唯一可靠的文本证据通道。`INFERRED`：`logfile` 对 socket chardev 可用；若实测不支持则改用 `-serial file:/var/harness/serial.log` 并放弃交互能力。

**能力对照表**

| 能力 | 本地 KVM | Vultr | 说明 |
|---|---|---|---|
| 实例创建/销毁 | ✅ 本地脚本 | ✅ API | — |
| 整机快照恢复 | ✅ `snapshot-load`，秒级 | ✅ `restore`，分钟级 | 本地可做实验内回滚，Vultr 只能做实验间回滚 |
| host 层截图 | ✅ `screendump` | ❌ | **Vultr 无** |
| guest 层截图 + 输入 | ✅（也可用，但没必要） | ⚠️ ARD/VNC 5900 + SSH 隧道，**仅 WindowServer 存活时** | 见 2.3.5。不可归因，不能当 T3 判据 |
| host 层输入注入 | ✅ `input-send-event` | ❌ | **Vultr 无** |
| 串口文本日志 | ✅ chardev + logfile | ❌ | **Vultr 无**，panic 诊断能力差一个数量级 |
| early boot 可观测 | ✅ 串口 | ❌ | 新内核改动必须先过本地 |
| SSH | ✅ | ✅ | 两边共有，前期主通道 |
| 附加盘投放 | ✅ `blockdev-add` / `-drive` | ✅ Block Storage attach | 两边共有 |
| ISO 挂载 | ✅ 任意数量 | ⚠️ 账户上限 2 个、≤10 GB、须公开 URL | — |
| 设备模型可选 | ✅ 全可控 | ❌ 固定 | **这是两层环境最本质的差异** |

最后一行是关键：本地可以把启动盘配成 AHCI、网卡配成 `vmxnet3`，所以 macOS 一定能启动；Vultr 的设备模型不可改，所以 1.5 的 `BLOCKED` 项在本地永远测不出来。**本地绿灯不能推断 Vultr 绿灯**，这是 2.1 分层设计的核心理由。

---

## 2. 架构

### 2.1 两层执行环境与测试分层

两层环境，职责不同，不是主备关系。

| 层 | 环境 | 职责 | 独有能力 |
|---|---|---|---|
| L1 本地 | 开发机或自建 Linux 宿主上的 QEMU/KVM | 快速迭代、内核侧改动的第一道关、panic 诊断、GUI 自动化 | 串口、host 截图、host 输入、设备模型可控、秒级快照 |
| L2 Vultr | Vultr 共享 CPU 实例 | 最终验证、设备模型真实性、"云上可跑"这一项目核心价值的证明 | 真实不可控宿主 |

**测试分层（Tier）**。每个用例声明自己的 Tier，决定它在哪层运行、用什么通道判定。

| Tier | 名称 | 判定通道 | 可运行层 | 典型用例 |
|---|---|---|---|---|
| T0 | 冷启动与设备枚举 | 串口（L1）/ 平台 API 状态 + SSH 可达（L2） | L1 + L2 | 固件类型、磁盘控制器、网卡、NVRAM 持久性、SIP/AMFI 实际值 |
| T1 | kext 加载 | SSH | L1 + L2 | kext 进入 aux collection、`IORegistry` 中服务已发布、selector 可打开 |
| T2 | 用户态无桌面验证 | SSH | L1 + L2 | Metal device 枚举、离屏渲染、IOSurface 创建与读回、Lavapipe 可用 |
| T3 | 显示与合成 | 串口 + host 截图（L1）/ guest 内 ARD-VNC 或 `screencapture`（L2，仅 WindowServer 存活时，**不可归因**，见 2.3.5） | **L1 为主**，L2 仅在 T2 全绿后尝试 | framebuffer 注册、WindowServer 选中本项目 device、桌面出图 |
| T4 | GUI 交互 | host 输入注入 + host 截图（L1）/ guest 内 ARD-VNC（L2） | **L1 为主**；T3 在 L2 通过后 L2 可跑（2.3.5） | 窗口拖动、动画、真实 App 渲染 |

**提升门槛（promotion gate）**，强制规则：

1. 任何改动内核侧（组件 2、3）的提交，**必须先在 L1 通过 T0 + T1**，才允许进 L2。理由见 1.4：L2 没有串口，early panic 无法诊断。
2. T3 用例默认只在 L1 运行。只有当同一构建的 T2 在 L2 上全绿、且 L2 的 SSH 在实验全程未断，才允许在 L2 跑 T3。
3. **T4 永不在 L2 运行。** 平台不提供 host 层输入注入（1.3），任何试图在 L2 跑 T4 的用例都是设计错误。
4. 1.5 表中标 `BLOCKED` 的项目**只能由 L2 的 T0 关闭**。L1 的 T0 不产生关于这些项目的证据，其结果在证据 JSON 中必须标 `platform: "local"` 以防被误用。

第 4 条是 00-OVERVIEW 第 7 节"标注证据的样本来源"规则在运行证据上的延伸：L1 证据不得冒充 L2 证据。

### 2.2 harness 组件与进程形态

```text
  harness-cli / harness-mcp (Rust)
        |
        +-- Runner           单次实验编排：恢复 → 投放 → 执行 → 采证 → 判定 → 归档
        |
        +-- trait Platform   实例生命周期、快照、payload 投放
        |     +-- LocalQemu  QMP over unix socket + 本地磁盘镜像
        |     +-- Vultr      api.vultr.com/v2 + Block Storage
        |
        +-- trait ScreenIO   截图与输入注入（可返回 Unsupported）
        |     +-- QmpScreen  screendump / input-send-event
        |     +-- VncScreen  RFB 客户端（L1 可选，L2 不可用）
        |     +-- NullScreen Vultr 默认，一切返回 Unsupported
        |
        +-- trait Shell      命令执行
        |     +-- Ssh        russh，两层共用
        |     +-- SerialLine 串口交互，仅 L1
        |
        +-- Collector        日志与证据采集（见 2.8）
        +-- Detector         失败检测（见 2.9）
        +-- Archiver         归档与哈希（见 2.10）
```

语言选择：**Rust**。理由不是偏好，而是三条具体约束：

1. 项目核心已是 Rust（组件 4、6），harness 共用 `metal2vulkan` 的类型定义与 crate 生态，避免维护第二套模型。
2. harness 要被 MCP 工具面调用并长期驻留，需要稳定的 async 运行时与强类型 JSON（`tokio` + `serde`），这比 Python 的等价方案更不容易在长跑中静默失效。
3. 开发机现有 `cargo 1.99.1` 与 `rustup`，无需新装工具链（见 `70-BUILD-PACKAGE.md` 第 2 节）。

依赖选型：

| 用途 | crate | 备注 |
|---|---|---|
| async 运行时 | `tokio` | — |
| HTTP | `reqwest` + `rustls` | Vultr API |
| SSH | `russh` | 纯 Rust，不依赖系统 libssh |
| QMP | 自写约 200 行 | QMP 是行分隔 JSON，没必要引依赖 |
| VNC | `vnc-rs` | 见 2.3 |
| 图像 | `image` | PPM→PNG、裁剪、逐像素比较 |
| 哈希 | `sha2` | 证据哈希 |
| schema | `serde` + `schemars` | 结果 JSON 带自描述 schema |

Python 只用于一次性探索脚本，不进管线。若必须用 Python（例如复用 OpenCV 做图像匹配），以子进程 + JSON stdout 的形式接入，不混进主控流程。

### 2.3 VNC 作为 L1 的画面与输入主干

**为什么要 VNC 而不是只用 QMP**：QMP 的 `screendump` 每次截图都要落一个文件再读回，输入注入是无状态单发；VNC 给的是一个持续连接，可以拿帧更新增量、可以等"画面稳定"、可以在一次连接内完成一串操作。做"等待某区域出现某图案"这类判定时，VNC 的语义合适得多。

**它工作在 host 层**，这是关键属性：guest 桌面死掉、WindowServer 重启、甚至 guest 内核 panic 后的屏幕残留，VNC 都还能取到画面。guest 内的 `screencapture` 做不到这一点。

**客户端库选型**

| 候选 | 语言 | 评估 |
|---|---|---|
| `vnc-rs` | Rust | **选定。** 纯 Rust 协议引擎，消费来自前端与服务端的事件并生成渲染事件（转述自 <https://lib.rs/crates/vnc-rs>）。无 C 依赖，与 harness 同语言 |
| `whitequark/rust-vnc` | Rust | 协议 + 客户端状态机实现（转述自 <https://github.com/whitequark/rust-vnc>）。备选，维护活跃度较低 |
| `vncdotool` | Python | 命令行 VNC 客户端兼库，定位就是自动化难以控制的虚拟机与硬件设备，支持键鼠模拟、截图与基于图像的 `expect` 校验（转述自 <https://github.com/sibson/vncdotool> 与 <https://docsearch.algolia.com/mcp/docs/repo/sibson/vncdotool>）。**作为人工排错工具保留**，不进管线 |
| `pyvnc` | Python | 纯 Python 异步客户端，截图与键鼠输入（转述自 <https://github.com/regulad/pyvnc>）。不选 |

决策：管线内用 `vnc-rs`；`vncdotool` 装在开发机上，供人手动戳一下看看，不被代码调用。

**接口设计**

```rust
/// 画面与输入。Vultr 上整体返回 Err(Unsupported)。
#[async_trait]
pub trait ScreenIO: Send + Sync {
    /// 当前能力声明。用例据此跳过而不是失败。
    fn caps(&self) -> ScreenCaps;

    // ---- 画面 ----

    /// 抓一帧。rect 为 None 时抓全屏。返回 PNG 字节与元数据。
    async fn capture(&self, rect: Option<Rect>) -> Result<Frame, ScreenError>;

    /// 等待画面稳定：连续 `stable_for` 内无像素变化即返回最后一帧。
    /// 用于"等安装程序画完这一屏"，避免抓到半渲染状态。
    async fn wait_stable(&self, rect: Option<Rect>, stable_for: Duration,
                         timeout: Duration) -> Result<Frame, ScreenError>;

    /// 等待某区域与模板图匹配。tolerance 为归一化平均绝对误差上限。
    /// 返回匹配时刻的帧。超时返回 Timeout 并附最后一帧，便于归档。
    async fn wait_match(&self, template: &Template, rect: Option<Rect>,
                        tolerance: f32, timeout: Duration)
        -> Result<Frame, ScreenError>;

    // ---- 输入 ----

    /// 绝对坐标移动。坐标为帧缓冲像素坐标，由实现换算到设备坐标系。
    async fn mouse_move(&self, x: u32, y: u32) -> Result<(), ScreenError>;

    /// 点击。先 move 再 down/up，中间插入 `settle` 延迟。
    async fn click(&self, x: u32, y: u32, button: MouseButton,
                   count: u8) -> Result<(), ScreenError>;

    async fn mouse_down(&self, button: MouseButton) -> Result<(), ScreenError>;
    async fn mouse_up(&self, button: MouseButton) -> Result<(), ScreenError>;

    /// 拖动：down → 分 steps 步插值移动 → up。
    async fn drag(&self, from: (u32, u32), to: (u32, u32),
                  button: MouseButton, steps: u32) -> Result<(), ScreenError>;

    /// 输入文本。实现负责把字符映射为 keysym/QKeyCode 序列并处理 shift。
    /// 只保证 ASCII 可打印字符；非 ASCII 返回 UnsupportedText。
    async fn type_text(&self, text: &str,
                       per_key: Duration) -> Result<(), ScreenError>;

    /// 组合键。按 mods 顺序按下，按 key，再逆序释放。
    /// 例：chord(&[Mod::Cmd], Key::Char('q'))
    async fn chord(&self, mods: &[Mod], key: Key) -> Result<(), ScreenError>;

    /// 单键按下并释放。
    async fn key(&self, key: Key) -> Result<(), ScreenError>;

    /// 原样透传一串底层事件，给需要精确时序的用例兜底。
    async fn raw_events(&self, events: &[InputEvent]) -> Result<(), ScreenError>;
}

pub struct ScreenCaps {
    pub capture: bool,
    pub input: bool,
    /// 画面来自 host 层（guest 死了也能取）还是 guest 内部。
    pub host_level: bool,
    pub framebuffer_size: Option<(u32, u32)>,
}

pub struct Frame {
    pub png: Vec<u8>,
    pub width: u32,
    pub height: u32,
    pub captured_at: OffsetDateTime,
    /// "vnc" | "qmp-screendump" | "guest-ard-vnc" | "guest-screencapture" | "manual-portal"
    pub source: &'static str,
}

pub enum ScreenError {
    /// 本平台不提供该能力。用例应跳过并记 skipped，不记 failed。
    Unsupported,
    Timeout { last_frame: Option<Frame> },
    Disconnected,
    UnsupportedText { ch: char },
    Io(std::io::Error),
}
```

**失败语义上的两个设计决定**：

1. `Unsupported` 与 `Timeout` 严格区分。前者是平台不具备（Vultr 上必然发生），用例记 `skipped`；后者是真实失败。把两者混成一个错误码，会让 Vultr 上的全部 T3/T4 用例变成假失败，淹没真信号。
2. `Timeout` 必须携带 `last_frame`。超时时最后那帧是唯一能说明"卡在哪一屏"的证据，丢掉它等于放弃诊断。

**坐标系**：VNC 的帧缓冲坐标与 QMP `abs` 事件的坐标系不同——QMP 的绝对轴值是一个归一化范围（官方示例里出现了 20000 这样的值），需要按帧缓冲尺寸换算。两个实现各自封装换算，`ScreenIO` 对外只暴露帧缓冲像素坐标。`INFERRED`，换算系数需在 L1 首次联调时用"点击已知位置并观察响应"的方式校准一次，校准结果写入 harness 配置。

### 2.3.5 guest 内 ARD/VNC：L2 上唯一的输入通道

1.3 证明了 Vultr **host 层**没有可编程画面。但 macOS 自己带一个可程序化开启的 VNC 服务端，这给 L2 补回一部分能力——**条件是 WindowServer 活着**。

**开启方式**（`KNOWN`，Apple 的 `kickstart` 工具，路径固定）：

```bash
sudo /System/Library/CoreServices/RemoteManagement/ARDAgent.app/Contents/Resources/kickstart \
     -activate -configure -access -on \
     -clientopts -setvnclegacy -vnclegacy yes \
     -setvncpw -vncpw "${HARNESS_VNC_PW}" \
     -restart -agent -privs -all
```

它会让 ARD agent 在 **TCP 5900** 上监听标准 RFB。随后把它关进本机：

```bash
sudo defaults write /Library/Preferences/com.apple.RemoteManagement.plist \
     VNCOnlyLocalConnections -bool yes
```

harness 侧通过 SSH 隧道接入，不开放公网端口：

```bash
ssh -N -L 5900:127.0.0.1:5900 harness@${INSTANCE_IP}
```

**这条路径必须走 SSH 隧道而不是直接暴露 5900。** 传统 VNC 认证是 8 字节 DES 挑战，密码上限 8 字符，公网直曝等于把 root 桌面交出去。`VNCOnlyLocalConnections` + 隧道是唯一可接受的形态。

**它给了什么，没给什么**

| 能力 | guest ARD/VNC（L2） | guest `screencapture`（L2） | host VNC/QMP（L1） |
|---|---|---|---|
| 持续连接、增量帧、`wait_stable` / `wait_match` | ✅ | ❌ 单发 | ✅ |
| 输入注入（键鼠） | ✅ | ❌ 完全没有 | ✅ |
| 登录窗口（未登录状态） | ✅ ARD 连 console session | ❌ 需要已登录的 GUI session | ✅ |
| WindowServer 已死 | ❌ | ❌ | ✅ |
| 内核 panic 屏 / early boot | ❌ | ❌ | ✅ |

所以 1.3 的结论**不变**（Vultr 的显示验证能力弱于本地），但 3.3.4 的工具组在 L2 上不再是整组 `unsupported`：桌面活着时它可用，桌面死掉时它返回 `unsupported/no_host_screen`。

**三条必须写进实现的告警**

1. **黑屏不可归因。** ARD 的取帧走的是 CoreGraphics/WindowServer 的捕获路径，而这正是本项目在改的东西。拿到一张黑图，无法区分"没渲染出东西"和"捕获路径本身坏了"。因此**它不能作为 T3 的判据**，只能作为 T3 已通过后的辅助观察与 T4 的交互手段。P3 之前的主判据仍是 `metal-probe` 的离屏像素比较（2.7）。
2. **`-vnclegacy yes` 在 25G325 上是否仍被接受未实测**（`INFERRED`）。Apple 在逐步收紧传统 VNC 认证；若该开关失效，标准 RFB 客户端连不上 Apple 的 Screen Sharing 协议，这条通道整体失效，L2 退回只有 `screencapture`。这是 H-011。
3. **TCC 可能拦屏幕录制。** 研发期 SIP/AMFI 全关（`70-BUILD-PACKAGE.md` 第 5 节），但 TCC 与 SIP 是两套机制。ARD agent 作为系统级服务历史上不受 TCC 约束，但在 26.x 上未实测（`INFERRED`，H-012）。若被拦，`kickstart` 的 `-privs -all` 之外还需直接写 TCC 数据库——SIP 关闭下可行。

**H-011 与 H-012 可以在 E0-L1 之后、不依赖 Vultr 就一次测完**：本地 KVM 的 guest 里跑 `kickstart`，从 host 侧隧道连 5900 抓一帧，与同时刻的 QMP `screendump` 比对。三种结果分别对应：连不上 → H-011 为否；连上但全黑而 `screendump` 有内容 → H-012 命中；两张图一致 → 两项都通过。

**`ScreenIO` 的实现项**：新增 `GuestArdVnc`，复用 2.3 选定的 `vnc-rs`（同一个 RFB 协议，换的只是连接对象与隧道管理），`caps()` 返回 `host_level: false`。`Frame::source` 用 `"guest-ard-vnc"`。

**它不改变分层规则。** 2.1 的"需要 host 层画面的用例钉在 L1"仍然成立，因为告警 1 说明 guest 层画面在显示未修好时没有判据价值。`GuestArdVnc` 的收益窗口是 P3 之后，与 4.2 里 `ScreenIO` 排在 B7/B8 的排期一致。

### 2.4 golden snapshot 流程

macOS 安装是交互式的、耗时几十分钟、且在当前阶段（显示未修好）本身就可能失败。**每次实验重装是不可接受的。** 正确形态是：人工装一次，做成基准快照，之后每个实验从快照开始。

#### 2.4.1 实验回路的形状

```text
  [golden snapshot]  ← 一次性成本，人工参与
         |
         v  restore
  ┌──────────────────────────────────────────────────┐
  │ 1. 恢复快照        (L1 秒级 / L2 分钟级)          │
  │ 2. 启动并等就绪    (SSH 可达 / 串口出现标记)      │
  │ 3. 投放 payload    (SSH 或附加盘)                 │
  │ 4. 执行任务        (guest agent)                  │
  │ 5. 采集证据        (2.8)                          │
  │ 6. 判定            (2.9)                          │
  │ 7. 归档            (2.10)                         │
  │ 8. 回滚或销毁                                     │
  └──────────────────────────────────────────────────┘
```

**golden snapshot 必须是"干净但已武装"的状态**，即：macOS 已装好、SIP/AMFI 已关、SSH 已开、guest agent 已安装并由 launchd 托管、本项目组件**未**安装。本项目组件是每次实验投放的变量，不进基准。

#### 2.4.2 构建 golden snapshot：L1

一次性，人工参与。

1. 用 `70-BUILD-PACKAGE.md` 第 4 节产出的 OpenCore + macOS 安装介质，创建 qcow2 系统盘：
   ```bash
   qemu-img create -f qcow2 /srv/harness/macos-golden.qcow2 128G
   ```
2. 启动安装，设备模型按 1.7 对照表最后一行配置（AHCI 启动盘 + `vmxnet3` 网卡），带串口与 QMP：
   ```bash
   qemu-system-x86_64 \
     -enable-kvm -machine q35 -cpu host,vendor=GenuineIntel \
     -smp 8 -m 16384 \
     -drive if=pflash,format=raw,readonly=on,file=/usr/share/OVMF/OVMF_CODE.fd \
     -drive if=pflash,format=raw,file=/srv/harness/OVMF_VARS.fd \
     -device ich9-ahci,id=sata \
     -drive id=disk0,if=none,format=qcow2,file=/srv/harness/macos-golden.qcow2 \
     -device ide-hd,bus=sata.0,drive=disk0 \
     -drive id=oc,if=none,format=raw,file=/srv/harness/opencore.img \
     -device ide-hd,bus=sata.1,drive=oc \
     -netdev user,id=n0,hostfwd=tcp::2222-:22 -device vmxnet3,netdev=n0 \
     -device VGA,vgamem_mb=128 \
     -vnc 127.0.0.1:1,password=on \
     -chardev socket,id=ser0,host=127.0.0.1,port=4555,server=on,wait=off,logfile=/srv/harness/serial.log \
     -serial chardev:ser0 \
     -qmp unix:/srv/harness/qmp.sock,server=on,wait=off
   ```
   `INFERRED`：以上设备组合与 CPU flag 需按实际 OpenCore 配置调整，详见 `70-BUILD-PACKAGE.md`。
3. 通过 VNC 完成安装（这一步是人工的，也是 GUI 自动化唯一真正有价值的候选场景——见 2.7 的说明）。
4. 装好后在 guest 内武装环境：
   ```bash
   # 开 SSH
   sudo systemsetup -setremotelogin on
   # 装公钥
   mkdir -p ~/.ssh && chmod 700 ~/.ssh
   printf '%s\n' "$HARNESS_PUBKEY" >> ~/.ssh/authorized_keys
   chmod 600 ~/.ssh/authorized_keys
   # 关掉会干扰实验的东西
   sudo pmset -a sleep 0 displaysleep 0 disksleep 0
   sudo systemsetup -setcomputersleep Never
   # 验证 SIP / AMFI（见 70-BUILD-PACKAGE.md 第 5.4 节）
   csrutil status; nvram boot-args
   ```
5. 安装 guest agent（见 2.6）。
6. 关机，`-snapshot` 之外另存一份只读基准：
   ```bash
   qemu-img convert -O qcow2 -c /srv/harness/macos-golden.qcow2 \
                             /srv/harness/golden/macos-26.7.2-25G325-golden.qcow2
   sha256sum /srv/harness/golden/macos-26.7.2-25G325-golden.qcow2 \
     > /srv/harness/golden/macos-26.7.2-25G325-golden.qcow2.sha256
   chmod a-w /srv/harness/golden/macos-26.7.2-25G325-golden.qcow2
   ```
7. 之后每次实验用 overlay，基准盘永不被写：
   ```bash
   qemu-img create -f qcow2 -b /srv/harness/golden/macos-26.7.2-25G325-golden.qcow2 \
                   -F qcow2 /run/harness/exp-${EXP_ID}.qcow2
   ```
   实验结束删 overlay 即完成回滚，**比 `snapshot-load` 更快也更不易出错**。`snapshot-load` 留给"实验中途回滚到某个中间点"的场景。

#### 2.4.3 构建 golden snapshot：L2

一次性，人工参与，依赖 1.5 的 `BLOCKED` 项先被 E0 实验关闭。

完整 API 序列：

```bash
export VH="Authorization: Bearer ${VULTR_API_KEY}"
export VJ="Content-Type: application/json"

# ---- 步骤 1：托管安装 ISO 并上传 ----
# 前提：ISO 已放到一个公开可达的 HTTPS URL（1.2 的约束 1），≤10 GB。
ISO_ID=$(curl -s -X POST "https://api.vultr.com/v2/iso" -H "$VH" -H "$VJ" \
  -d '{"url":"https://assets.example.net/macos-26.7.2-25G325-oc.iso"}' \
  | jq -r '.iso.id')

# 轮询至 status=complete，并比对哈希（平台回报 md5sum/sha512sum）
until [ "$(curl -s "https://api.vultr.com/v2/iso/${ISO_ID}" -H "$VH" | jq -r '.iso.status')" = "complete" ]; do
  sleep 20
done
curl -s "https://api.vultr.com/v2/iso/${ISO_ID}" -H "$VH" | jq '.iso | {md5sum, sha512sum}'
# 与本地 `md5sum` / `sha512sum` 比对，不一致则删除重传

# ---- 步骤 2：选机型并创建实例，直接从 ISO 启动 ----
PLAN=$(curl -s "https://api.vultr.com/v2/plans?type=vc2&per_page=100" -H "$VH" \
  | jq -r '[.plans[] | select(.vcpu_count>=4 and .ram>=8192)] | sort_by(.monthly_cost)[0].id')

INST_ID=$(curl -s -X POST "https://api.vultr.com/v2/instances" -H "$VH" -H "$VJ" \
  -d "{\"region\":\"ewr\",\"plan\":\"${PLAN}\",\"iso_id\":\"${ISO_ID}\",
       \"label\":\"macos-golden-builder\",\"tags\":[\"harness\",\"golden-builder\"],
       \"enable_ipv6\":false,\"backups\":\"disabled\"}" \
  | jq -r '.instance.id')

# 创建响应里的 default_password 必须立刻落盘（1.1 的关键点）
# ---- 步骤 3：人工经网页控制台完成安装 ----
# 这一步不可自动化，原因见 1.3。
# 安装完成后在 guest 内执行 2.4.2 步骤 4、5 的全部武装操作。

# ---- 步骤 4：卸载 ISO ----
curl -s -X POST "https://api.vultr.com/v2/instances/${INST_ID}/iso/detach" -H "$VH"
until [ "$(curl -s "https://api.vultr.com/v2/instances/${INST_ID}/iso" -H "$VH" | jq -r '.iso_status.state')" = "ready" ]; do
  sleep 10
done

# ---- 步骤 5：关机后建 golden 快照 ----
curl -s -X POST "https://api.vultr.com/v2/instances/${INST_ID}/halt" -H "$VH"
until [ "$(curl -s "https://api.vultr.com/v2/instances/${INST_ID}" -H "$VH" | jq -r '.instance.power_status')" = "stopped" ]; do
  sleep 10
done

SNAP_ID=$(curl -s -X POST "https://api.vultr.com/v2/snapshots" -H "$VH" -H "$VJ" \
  -d "{\"instance_id\":\"${INST_ID}\",\"description\":\"golden macos-26.7.2-25G325 armed r1\"}" \
  | jq -r '.snapshot.id')

# 快照可能要 ~30 分钟（1.2）
until [ "$(curl -s "https://api.vultr.com/v2/snapshots/${SNAP_ID}" -H "$VH" | jq -r '.snapshot.status')" = "complete" ]; do
  sleep 60
done
echo "GOLDEN_SNAPSHOT_ID=${SNAP_ID}"
```

#### 2.4.4 单次实验：L2 的 API 序列

**保留实验实例、反复 restore**，不每次创建销毁。理由见 1.6：最小计费单位 1 小时。

```bash
# ---- 1. 恢复到 golden ----
curl -s -X POST "https://api.vultr.com/v2/instances/${INST_ID}/restore" -H "$VH" -H "$VJ" \
  -d "{\"snapshot_id\":\"${SNAP_ID}\"}"

# restore 是异步的。判定依据：status 回到 active 且 server_status 可用
until [ "$(curl -s "https://api.vultr.com/v2/instances/${INST_ID}" -H "$VH" \
           | jq -r '.instance.status + "/" + .instance.power_status')" = "active/running" ]; do
  sleep 15
done

# ---- 2. 等 SSH 就绪（真正的就绪判定，不信平台状态）----
IP=$(curl -s "https://api.vultr.com/v2/instances/${INST_ID}" -H "$VH" | jq -r '.instance.main_ip')
for i in $(seq 1 60); do
  ssh -o BatchMode=yes -o StrictHostKeyChecking=accept-new \
      -o ConnectTimeout=5 -i "$HARNESS_KEY" "harness@${IP}" 'echo ready' && break
  sleep 10
done

# ---- 3..7 见 2.5 / 2.6 / 2.8 / 2.9 / 2.10 ----

# ---- 8. 回滚（下次实验开头的 restore 即是回滚）----
# 实验机长期保留。只在实验矩阵跑完后销毁：
# curl -s -X DELETE "https://api.vultr.com/v2/instances/${INST_ID}" -H "$VH"
```

**平台状态不等于就绪**。`status=active` 只说明平台认为实例在跑，不说明 macOS 进了 launchd、更不说明 SSH 起来了。唯一可信的就绪信号是 SSH 握手成功（L2）或串口出现 agent 的启动标记（L1）。这条规则贯穿全管线。

#### 2.4.5 快照版本与 GC

golden 快照按 `(macOS build, 武装版本)` 命名并保留最近 2 个版本；中间态快照（例如"装了某个实验中的 kext"）打 `tmp-` 前缀，超过 72 小时自动删除。快照单独计费，没有 GC 会稳定漏钱。

### 2.5 payload 投放

两条路，适用场景互斥。

#### 路径 A：SSH（网络可用时的默认路径）

适用：T1/T2 的绝大多数实验。payload 是 `70-BUILD-PACKAGE.md` 产出的一个 tarball。

```bash
# 投放
scp -i "$HARNESS_KEY" -o StrictHostKeyChecking=accept-new \
    "dist/metal2vu-${BUILD_ID}.tar.gz" "harness@${IP}:/tmp/"
scp -i "$HARNESS_KEY" "dist/metal2vu-${BUILD_ID}.tar.gz.sha256" "harness@${IP}:/tmp/"

# guest 内校验后安装
ssh -i "$HARNESS_KEY" "harness@${IP}" bash -s <<'EOF'
set -euo pipefail
cd /tmp
shasum -a 256 -c "metal2vu-${BUILD_ID}.tar.gz.sha256"
sudo /usr/local/libexec/harness-agent install /tmp/metal2vu-${BUILD_ID}.tar.gz
EOF
```

**必须先校验哈希再安装。** 投放一个被截断的 tarball 然后花两小时调查一个不存在的 bug，是这类管线最常见的时间浪费。

#### 路径 B：附加块设备（网络不可用时）

适用场景，三种：

1. 实验本身会**打掉网络**（改网卡相关、或 panic 后需要带回证据）。
2. 实验要**替换 agent 自身**，无法用 agent 来装自己。
3. **救援**：guest 起不来，需要从外部塞一个修复脚本进去。

L2 用 Block Storage（`KNOWN`，来源：`govultr/block_storage.go`，<https://github.com/vultr/govultr/blob/master/block_storage.go>）：

```bash
# 建卷
BLK_ID=$(curl -s -X POST "https://api.vultr.com/v2/blocks" -H "$VH" -H "$VJ" \
  -d '{"region":"ewr","size_gb":10,"label":"harness-payload","block_type":"storage_opt"}' \
  | jq -r '.block.id')

# 挂载。live=true 表示不重启实例即挂载
curl -s -X POST "https://api.vultr.com/v2/blocks/${BLK_ID}/attach" -H "$VH" -H "$VJ" \
  -d "{\"instance_id\":\"${INST_ID}\",\"live\":true}"

# ... 实验 ...

# 卸载
curl -s -X POST "https://api.vultr.com/v2/blocks/${BLK_ID}/detach" -H "$VH" -H "$VJ" \
  -d '{"live":true}'
```

块设备对象带 `mount_id`、`attached_to_instance`、`bootable` 等字段，可用于确认挂载实际生效。

**约束与风险**：`live=true` 的热插拔要求 guest 侧能响应热插事件。macOS 对 VirtIO 块设备的支持是 1.5 的 `BLOCKED` 项——**路径 B 在 L2 上能否工作，与"Vultr 能否启动 macOS"是同一个未知**。因此：

- 路径 B 在 L2 上标记为 `BLOCKED`，由 E0 实验一并查清。
- 在它被确证之前，**L2 的唯一投放路径是 SSH**，这进一步强化了 2.1 的分层结论。

L1 用 `-drive` 或运行时 `blockdev-add`，并用 raw 镜像加 HFS+/FAT 文件系统，确保 macOS 无驱动依赖即可读：

```bash
# 构建 payload 盘（在 Linux 宿主上）
dd if=/dev/zero of=/run/harness/payload-${EXP_ID}.img bs=1M count=512
mkfs.vfat -n PAYLOAD /run/harness/payload-${EXP_ID}.img
mcopy -i /run/harness/payload-${EXP_ID}.img dist/metal2vu-${BUILD_ID}.tar.gz ::/
```

FAT 而非 HFS+：macOS 必然能读 FAT，且 Linux 侧工具链（`mtools`）无需特权即可写入。

#### 路径 C：ISO（仅救援）

受 1.2 的两个 ISO 槽位限制，ISO 不用于常规投放。它只在"实例完全起不来、需要换一个引导介质"时使用，且必须由人确认后执行（挂载 ISO 会重启实例）。

### 2.6 guest agent

#### 2.6.1 定位

agent 是 guest 内的小服务，职责是：接任务、执行、回传结构化结果、采集本地证据。它**不是** harness 的一部分逻辑，不做判定，只做执行与上报。判定在 host 侧（`Detector`），因为 guest 可能已经不可信。

语言：Rust，静态链接，单文件，无运行时依赖。目标 `x86_64-apple-darwin`。

#### 2.6.2 启动方式：launchd

两个 job，职责分开。

`/Library/LaunchDaemons/net.metal2vu.harness-agent.plist` —— root 权限，负责 kext 加载、系统日志采集：

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>                 <string>net.metal2vu.harness-agent</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/local/libexec/harness-agent</string>
    <string>serve</string>
    <string>--socket</string><string>/var/run/harness-agent.sock</string>
    <string>--state-dir</string><string>/var/db/harness</string>
  </array>
  <key>RunAtLoad</key>             <true/>
  <key>KeepAlive</key>
  <dict><key>SuccessfulExit</key>  <false/></dict>
  <key>ThrottleInterval</key>      <integer>5</integer>
  <key>StandardOutPath</key>       <string>/var/log/harness-agent.out.log</string>
  <key>StandardErrorPath</key>     <string>/var/log/harness-agent.err.log</string>
  <key>ProcessType</key>           <string>Interactive</string>
</dict>
</plist>
```

`/Library/LaunchAgents/net.metal2vu.harness-gui.plist` —— 在登录用户的 GUI session 中运行，负责任何需要窗口服务器连接的事（Metal 上屏、`screencapture`、CoreGraphics 查询）。**这个 job 的存在本身就是显示状态的探针**：它起不来或反复重启，说明 WindowServer 有问题。

安装与加载（现代 `launchctl` 子命令，`KNOWN`）：

```bash
sudo cp net.metal2vu.harness-agent.plist /Library/LaunchDaemons/
sudo chown root:wheel /Library/LaunchDaemons/net.metal2vu.harness-agent.plist
sudo chmod 644       /Library/LaunchDaemons/net.metal2vu.harness-agent.plist
sudo launchctl bootstrap system /Library/LaunchDaemons/net.metal2vu.harness-agent.plist
sudo launchctl enable system/net.metal2vu.harness-agent
sudo launchctl print system/net.metal2vu.harness-agent   # 确认 state = running

# GUI agent（uid 501 为实验用户）
launchctl bootstrap gui/501 /Library/LaunchAgents/net.metal2vu.harness-gui.plist
launchctl print gui/501/net.metal2vu.harness-gui
```

#### 2.6.3 协议

传输：**不自己开网络端口。** agent 监听 unix domain socket，harness 通过 SSH 转发进去：

```bash
ssh -i "$HARNESS_KEY" "harness@${IP}" \
    'sudo /usr/local/libexec/harness-agent client --socket /var/run/harness-agent.sock' \
    < request.json > response.json
```

这样做的三个理由：不新增攻击面（符合 `CLOUD_DEPLOYMENT_SPEC.md` 第 5 节的安全基线）、鉴权复用 SSH、网络配置变更不影响 agent 可达性。

报文：换行分隔 JSON（NDJSON），请求一条，响应可多条（进度流 + 终局）。

请求：

```json
{
  "v": 1,
  "task_id": "e7f2a1c9-0b44-4d8e-9a31-5c6b2d8f1a07",
  "kind": "run",
  "deadline_ms": 120000,
  "payload": {
    "argv": ["/usr/local/bin/metal-probe", "--enumerate-devices", "--json"],
    "env": { "MTL_DEBUG_LAYER": "1", "VK_LOADER_DEBUG": "error,warn" },
    "cwd": "/tmp",
    "stdin_b64": null,
    "capture": { "stdout": true, "stderr": true, "max_bytes": 4194304 }
  }
}
```

`kind` 取值：

| kind | 语义 |
|---|---|
| `ping` | 存活与版本。必须在 1 秒内返回 |
| `sysinfo` | 一次性收集 build、SIP 状态、boot-args、CPU、内存、显示配置 |
| `run` | 执行一个进程并捕获输出 |
| `install` | 安装 payload tarball（校验哈希、解包到安装布局、按 `70` 第 6 节的顺序加载） |
| `uninstall` | 卸载本项目组件，回到 golden 等价状态（用于不想 restore 的快速迭代） |
| `collect` | 按 2.8 的清单采集证据，打包到 `/var/db/harness/out/${task_id}/` |
| `kextload` / `kextunload` | 内核扩展加载/卸载，带诊断 |
| `screenshot` | guest 内 `screencapture`。**L2 上的唯一画面来源**，WindowServer 死时失败 |
| `shutdown` / `reboot` | 受控下电，用于区分"主动重启"与"崩溃重启" |

进度与终局响应：

```json
{"v":1,"task_id":"e7f2…","type":"progress","at":"2026-10-30T11:04:21.337Z","stage":"kextload","note":"staging"}
{"v":1,"task_id":"e7f2…","type":"result",
 "at":"2026-10-30T11:04:58.902Z",
 "status":"ok",
 "exit_code":0,
 "duration_ms":37565,
 "stdout_b64":"…","stderr_b64":"…","truncated":false,
 "artifacts":[{"path":"/var/db/harness/out/e7f2…/ioreg.txt","sha256":"…","bytes":918273}],
 "agent":{"version":"0.3.1","build_id":"…","pid":412}}
```

`status` 取值：`ok` / `nonzero_exit` / `timeout` / `agent_error` / `precondition_failed`。

#### 2.6.4 超时：三层，各有不同的恢复动作

| 层 | 超时对象 | 时长 | 超时后动作 |
|---|---|---|---|
| L-task | 单个任务 | 请求中的 `deadline_ms` | agent 向子进程发 `SIGTERM`，3 秒后 `SIGKILL`，回 `status=timeout` 并附已采集的部分输出 |
| L-agent | agent 整体无响应 | 固定 30 秒（`ping` 无回） | harness 判定 agent 死，走 2.9 的 agent 崩溃分支 |
| L-experiment | 整个实验 | 用例声明，默认 15 分钟 | harness 放弃 guest 内通道，转为 host 层取证（串口日志 / 截图），然后强制重启 |

三层分开的理由：单任务超时是常态（渲染卡住），agent 超时意味着 guest 内通道不可信，实验超时意味着整个 guest 可能已经不在了。三者的恢复动作完全不同，用一个超时值表达不了。

#### 2.6.5 agent 自身崩溃如何被发现

`KeepAlive` + `SuccessfulExit=false` 让 launchd 在 agent 异常退出时重启它，这是好的——但**对 harness 是有害的静默**：agent 悄悄重启后看起来一切正常，而上一个任务的状态已经丢了。

因此 agent 必须持久化一个单调递增的 **启动代（incarnation）**：

- 启动时读 `/var/db/harness/incarnation`，+1 后写回并 `fsync`，同时记录启动时间与上次是否干净退出。
- 每条响应的 `agent` 字段带 `incarnation`。
- harness 在实验开始时记下 `incarnation`，每次响应比对。**代号变化 = agent 在实验期间重启过 = 该实验结果不可信**，判定为 `failed`，原因 `agent_restarted`，并归档 `/var/log/harness-agent.err.log` 与同期的 `log show` 窗口。

同时两个独立的交叉检查，防止 agent 和 launchd 一起装死：

1. **心跳文件**：agent 每 5 秒 touch `/var/db/harness/heartbeat` 并写入当前 `task_id`。harness 通过 SSH 直接 `stat` 它，不经过 agent。文件停止更新但 SSH 仍通 → agent 挂了，机器还活着。
2. **launchd 视角**：`launchctl print system/net.metal2vu.harness-agent` 的输出里有 `last exit code` 与 `runs` 计数。harness 在实验前后各取一次，`runs` 增加即确认重启。

```bash
# 不经过 agent 的存活检查
ssh -i "$HARNESS_KEY" "harness@${IP}" \
  'stat -f "%m %N" /var/db/harness/heartbeat; cat /var/db/harness/incarnation'
```

### 2.7 鸡生蛋问题与它的唯一正确解

**问题陈述**：GUI 自动化需要一个可用的桌面；本项目前期做的事就是让桌面第一次出现。因此在显示修好之前，任何以 GUI 为前提的自动化都是无法启动的循环。

**结论**：前期全链路由 **SSH + 串口 + host 层画面** 驱动。GUI 自动化只是后期环节，而且它的价值主要在两件事上，都不在主回路里：

1. **golden snapshot 的初次安装**（2.4.2 步骤 3）。这是真正值得自动化的 GUI 场景——它交互固定、重复率低但每次都痛。可以用 `ScreenIO::wait_match` + `click` 把 macOS 安装器的若干屏脚本化。优先级低，因为做一次就有快照了。
2. **T4 用例**（桌面交互、窗口拖动、真实 App）。这是显示跑通之后才有意义的验收。

**据此的测试分层已在 2.1 给出。** 这里补充它在时间轴上的展开：

| 阶段 | 可用通道 | 可运行 Tier | 退出条件 |
|---|---|---|---|
| P0 立项期（当前） | 无。guest 从未启动 | — | E0 实验：L1 上 macOS 启动并 SSH 可达 |
| P1 通道建立期 | 串口（L1）、SSH | T0、T1 | agent 在两层都能跑 `ping` 与 `sysinfo` |
| P2 内核期 | + `ioreg`、`kmutil` 诊断 | T0–T1 | 本项目 accelerator service 在 `IORegistry` 中可见且 user client 可打开 |
| P3 用户态期 | + Metal 枚举、离屏渲染 | T0–T2 | 离屏渲染出正确像素，IOSurface 可读回 |
| P4 显示期 | + host 截图（L1） | T0–T3 | 桌面在 L1 上出图；WindowServer 选中本项目 device |
| P5 交互期 | + host 输入注入（L1） | T0–T4 | T4 用例通过 |

**P0→P1 是当前唯一要紧的事。** 在 P1 之前，`10`/`11`/`20` 分册里所有 `INFERRED` 都只能继续是 `INFERRED`。

一个必须明说的反模式：**不要为了"让 GUI 自动化先跑起来"而先去修一个假的显示路径。** 前期的显示验证应该走离屏（T2）——`IOSurface` + Lavapipe 渲染后由 CPU 读回像素并与参考图比较，完全不需要 WindowServer。这条路径在 P3 就能建立，而且它给出的像素级证据比截图更精确。

### 2.8 日志与证据采集

每项给出确切命令。agent 的 `collect` 任务按本节清单执行，产物落在 `/var/db/harness/out/${task_id}/`。

#### 2.8.1 时间窗的定义

所有基于时间窗的采集都以**实验开始时刻**为锚，而不是"最近 N 分钟"。agent 在实验开始时记录：

```bash
# 实验开始时执行，结果写入 /var/db/harness/out/${task_id}/window.json
date -u +%Y-%m-%dT%H:%M:%SZ          # 墙上时钟，给 log show --start
sysctl -n kern.boottime               # 本次启动时刻，用于判断是否发生过重启
```

采集时用 `--start`，而不是 `--last`：

```bash
log show --start "2026-10-30 11:02:00" --end "2026-10-30 11:19:00" ...
```

`--last N[s|m|h|d]` 在实验耗时不定时会漏掉开头，`--start`/`--end` 不会。两者都由 `log show` 支持（`KNOWN`，来源：`log(1)` 手册 <https://keith.github.io/xcode-man-pages/log.1.html>）。

#### 2.8.2 IORegistry

这是组件 2、3 的核心证据。

```bash
# 全量，纯文本。体积大（数 MB），但是唯一完整的快照
ioreg -l -w 0 > ioreg-full.txt

# 全量，plist 格式，供程序解析
ioreg -l -a -w 0 > ioreg-full.plist

# 加速器子树：本项目 accelerator service 是否发布、属性是否正确
ioreg -r -c IOAccelerator -l -w 0 > ioreg-ioaccelerator.txt

# 显示子树：x86 路径依赖 IOGraphicsFamily（00-OVERVIEW 第 4.2 节）
ioreg -r -c IOFramebuffer   -l -w 0 > ioreg-iofb.txt
ioreg -r -c IODisplay       -l -w 0 > ioreg-iodisplay.txt
ioreg -r -c IOPCIDevice     -l -w 0 > ioreg-iopci.txt

# IOSurface root
ioreg -r -c IOSurfaceRoot   -l -w 0 > ioreg-iosurface.txt

# 本项目服务按类名定点取（类名以实际 Info.plist 的 IOClass 为准）
ioreg -r -c Metal2VuAccelerator -l -w 0 > ioreg-ours.txt
```

`-w 0` 关闭换行截断，否则长属性值会被截断成不可用的证据。

#### 2.8.3 kext 状态

```bash
# 已加载内核扩展。kextstat 在现代 macOS 上仍存在但已不推荐；两者都采
kextstat                                   > kextstat.txt 2>&1
kmutil showloaded                          > kmutil-showloaded.txt 2>&1
kmutil showloaded --bundle-identifier net.metal2vu.accel \
                                           > kmutil-showloaded-ours.txt 2>&1

# 依赖解析与加载失败诊断（见 70-BUILD-PACKAGE.md 第 4.4 节）
kmutil print-diagnostics /Library/Extensions/Metal2VuAccel.kext \
                                           > kmutil-diagnostics.txt 2>&1
kmutil check                               > kmutil-check.txt 2>&1
kmutil inspect --bundle-identifier net.metal2vu.accel \
                                           > kmutil-inspect.txt 2>&1
```

`kmutil` 的子命令集（`load` / `unload` / `showloaded` / `find` / `libraries` / `print-diagnostics` / `create` / `inspect` / `check` / `log` / `dumpstate` / `clear-staging` / `trigger-panic-medic`）为 `KNOWN`，来源：`kmutil(8)` 手册 <https://keith.github.io/xcode-man-pages/kmutil.8.html>。

#### 2.8.4 统一日志

`log show` 的谓词按 NSPredicate 语法（`KNOWN`，来源同 2.8.1）。采以下几个窗口：

```bash
W_START="$(jq -r .start window.json)"
W_END="$(jq -r .end   window.json)"
COMMON="--start $W_START --end $W_END --info --debug --style ndjson --no-pager"

# 1) 内核 + 本项目 kext
log show $COMMON \
  --predicate 'senderImagePath CONTAINS "Metal2Vu" OR process == "kernel"' \
  > log-kernel.ndjson

# 2) WindowServer 与显示栈
log show $COMMON \
  --predicate 'process == "WindowServer" OR subsystem BEGINSWITH "com.apple.windowserver" OR subsystem == "com.apple.iokit.IOGraphicsFamily"' \
  > log-windowserver.ndjson

# 3) Metal / GPU 栈
log show $COMMON \
  --predicate 'subsystem BEGINSWITH "com.apple.Metal" OR subsystem BEGINSWITH "com.apple.gpu" OR senderImagePath CONTAINS "Metal"' \
  > log-metal.ndjson

# 4) kext 管理子系统：加载失败的真实原因在这里
log show $COMMON \
  --predicate 'subsystem == "com.apple.kext" OR process == "kernelmanagerd" OR process == "kmutil" OR process == "syspolicyd"' \
  > log-kextmgmt.ndjson

# 5) 被测进程自身
log show $COMMON --predicate 'process == "metal-probe"' > log-probe.ndjson

# 6) 兜底：整窗全量，压缩归档。体积大，但失败时能救命
log show $COMMON > log-all.ndjson && gzip -9 log-all.ndjson
```

`--style ndjson` 让每行一条 JSON 记录，可被 `Detector` 流式消费，也可被模型直接读。

实时流（长实验期间并行跑，不必等结束）：

```bash
log stream --level debug --style ndjson \
  --predicate 'process == "WindowServer" OR process == "kernel" OR senderImagePath CONTAINS "Metal2Vu"' \
  > log-stream.ndjson &
STREAM_PID=$!
# ... 实验 ...
kill "$STREAM_PID"
```

**`log stream` 是 WindowServer 崩溃检测的主通道**：崩溃瞬间的消息在 `log show` 里也有，但流式能让 `Detector` 当场判定并立刻抓截图，而不是事后才知道。

完整归档（体积最大，只在失败时采）：

```bash
sudo log collect --start "$W_START" --output harness.logarchive
# 若只要某进程，加 --predicate 可显著降体积（手册提示该选项会增加采集时间与内存）
tar -czf harness.logarchive.tar.gz harness.logarchive && rm -rf harness.logarchive
```

#### 2.8.5 panic 与崩溃报告

```bash
# kernel panic 报告。目录为系统级诊断报告目录
sudo ls -lt /Library/Logs/DiagnosticReports/ | head -50 > diagreports-listing.txt
sudo cp /Library/Logs/DiagnosticReports/*.panic           out/ 2>/dev/null || true
sudo cp /Library/Logs/DiagnosticReports/Retired/*.panic   out/ 2>/dev/null || true

# 用户态崩溃（WindowServer、我们的 helper、测试程序）
sudo cp /Library/Logs/DiagnosticReports/WindowServer*.ips out/ 2>/dev/null || true
sudo cp /Library/Logs/DiagnosticReports/*metal2vu*.ips    out/ 2>/dev/null || true
cp ~/Library/Logs/DiagnosticReports/*.ips                 out/ 2>/dev/null || true

# 上一次 panic 的 NVRAM 残留（重启后仍可读，是"确实 panic 过"的独立证据）
nvram -p > nvram-all.txt 2>&1
nvram aapl,panic-info 2>/dev/null > nvram-panic-info.txt || true
```

`/Library/Logs/DiagnosticReports` 为 panic 报告路径，`Retired` 子目录存放轮转出的旧报告（`KNOWN`，转述自 Apple 社区文档 <https://discussions.apple.com/thread/251053592> 与 <https://discussions.apple.com/thread/256372916>）。崩溃报告在近年 macOS 上为 `.ips`（JSON）格式，`INFERRED`，需在 25G325 上确认后更新本节。

**重启检测**：实验前后各取 `sysctl -n kern.boottime`，变化即表示重启过。配合 `nvram aapl,panic-info` 区分"主动重启"与"panic 重启"。

```bash
sysctl -n kern.boottime > boottime.txt
# 也采 shutdown 原因码：0 为正常，负值为异常
log show --last boot --predicate 'eventMessage CONTAINS "Previous shutdown cause"' \
  --style compact > shutdown-cause.txt
```

#### 2.8.6 旧式 syslog 与 system.log

现代 macOS 的 `system.log` 只包含被降级到 ASL 的少量消息，不是主通道，但仍采：

```bash
sudo cp /var/log/system.log      out/ 2>/dev/null || true
sudo cp /var/log/system.log.0.gz out/ 2>/dev/null || true
sudo cp /var/log/install.log     out/ 2>/dev/null || true   # 安装期证据
```

#### 2.8.7 显示与 Metal 状态查询

```bash
# 显示配置（含分辨率、色深、所选 GPU）
system_profiler -json SPDisplaysDataType   > sp-displays.json
system_profiler -json SPHardwareDataType   > sp-hardware.json

# guest 内截图。L2 的唯一画面来源（1.3）
screencapture -x -t png /var/db/harness/out/${TASK}/guest-screen.png
# 多屏时逐屏
screencapture -x -t png -D 1 guest-screen-d1.png

# WindowServer 是否在跑、是哪一代
pgrep -l WindowServer        > windowserver-pid.txt
launchctl print system/com.apple.WindowServer > windowserver-launchd.txt 2>&1

# Metal device 枚举（本项目自带探针，见 4.2）
/usr/local/bin/metal-probe --enumerate-devices --json > metal-devices.json
/usr/local/bin/metal-probe --offscreen-render --out offscreen.png --json > offscreen-result.json
```

`screencapture -x` 禁止快门声，`-t png` 指定格式。`INFERRED`：`screencapture` 需要 GUI session，必须由 `LaunchAgent`（2.6.2 的第二个 job）执行，从 `LaunchDaemon` 调用会失败。

#### 2.8.8 Metal 与 Vulkan 诊断开关

实验执行时注入的环境变量。这些变量**只在研发期开启**，因为它们会显著改变时序并放大日志量。

| 变量 | 值 | 作用 | 标签 |
|---|---|---|---|
| `MTL_DEBUG_LAYER` | `1` | 开启 Metal API 校验层 | `INFERRED` |
| `MTL_SHADER_VALIDATION` | `1` | shader 侧校验 | `INFERRED` |
| `MTL_CAPTURE_ENABLED` | `1` | 允许 GPU trace 捕获 | `INFERRED` |
| `METAL_DEVICE_WRAPPER_TYPE` | `1` | 请求校验包装 device | `INFERRED` |
| `MTL_HUD_ENABLED` | `1` | 屏上性能 HUD。仅 P4 之后有意义 | `INFERRED` |
| `VK_LOADER_DEBUG` | `error,warn` 或 `all` | Vulkan loader 的驱动发现过程。**ICD 没被找到时唯一能看的东西** | `KNOWN` |
| `VK_DRIVER_FILES` | 随包 ICD 的绝对路径 | 强制只用随包 Lavapipe | `KNOWN` |
| `VK_LOADER_DRIVERS_SELECT` | `lvp_icd.*` | 二次保险，按清单文件名过滤 | `KNOWN` |
| `VK_LOADER_SEARCH_ONLY_IN_BUNDLE` | 置任意值 | 只在 app bundle 的 Resources 下找驱动 | `KNOWN` |
| `LP_NATIVE_VECTOR_WIDTH` | `128` / `256` | 覆盖 Lavapipe 向量宽度，用于排查 SIMD 相关错误 | `KNOWN` |
| `GALLIUM_OVERRIDE_CPU_CAPS` | `sse2` / `nosse` | 降级 CPU 特性，隔离指令集问题 | `KNOWN` |

Vulkan loader 相关四项的证据来源：<https://github.com/KhronosGroup/Vulkan-Loader/blob/main/docs/LoaderDriverInterface.md>。Lavapipe 两项来源：<https://docs.mesa3d.org/drivers/llvmpipe.html>。Metal 侧为 `INFERRED`：这些变量名在 Apple 工具链中广为使用但无公开文档保证，须在 25G325 上逐一实测有效性并把结果写回本表。

**ICD 强制的三重保险**，顺序重要（`KNOWN`，依据 loader 文档的优先级描述）：

1. `VK_DRIVER_FILES` 指向随包 ICD 的绝对路径。它会**覆盖**默认搜索路径；若同时设了 `VK_ADD_DRIVER_FILES`，后者被忽略。
2. `VK_LOADER_DRIVERS_SELECT=lvp_icd.*` 按清单文件名做 glob 过滤，把系统上其它 ICD 排除。注意：若 glob 匹配不到任何驱动，结果是**没有驱动可用**，Vulkan 应用会直接失败——这是有意的失败关闭行为。
3. 若渲染核心最终以 app bundle 形式交付，加 `VK_LOADER_SEARCH_ONLY_IN_BUNDLE`，让 loader 只看 `(bundle)/Contents/Resources/vulkan/icd.d`。

更彻底的做法是 `VK_LUNARG_direct_driver_loading`：应用直接把驱动入口交给 loader，完全绕过 ICD 清单文件发现（`KNOWN`，同一文档）。`INFERRED`：这对本项目是更干净的形态，因为渲染核心是我们自己的进程内代码，不需要让 loader 去文件系统里找东西。值得在 `40-RUNTIME-VULKAN.md` 中评估。

### 2.9 失败检测与自动归档

#### 2.9.1 失败模式与可观测信号

| 失败模式 | L1 信号 | L2 信号 | 判定方法 |
|---|---|---|---|
| **kernel panic** | 串口出现 `panic(cpu` 字样；QMP 有 `GUEST_PANICKED` 事件（若配了 `pvpanic`）；画面变为 panic 屏 | SSH 突然断开 + 平台 `power_status` 仍 `running` + 后续重启后 `/Library/Logs/DiagnosticReports/*.panic` 出现新文件 | L1 实时；L2 事后 |
| **early boot 卡死（未进 launchd）** | 串口在某行后停止输出超过 `boot_timeout` | SSH 在 `boot_timeout` 内始终不可达，且无 panic 报告 | L1 可定位到卡在哪；**L2 只能知道"没起来"** |
| **WindowServer 重启** | `log stream` 中 WindowServer 进程退出 + 新 pid；`launchctl print` 的 `runs` 增加；host 截图显示回到登录窗口 | 同左的日志与 launchctl 信号（SSH 可用时）；`guest-screen.png` 变为登录屏 | 两层都可，靠日志 |
| **WindowServer 挂起（不重启但不出图）** | host 截图连续 N 次完全相同且不响应输入注入 | **难以判定**。只能靠 guest 内 `screencapture` 是否超时 | L1 可靠，L2 不可靠 |
| **测试进程 hang** | `deadline_ms` 超时 + `sample` 抓栈 | 同左 | 两层都可 |
| **无输出（渲染全黑/全空）** | 离屏结果像素全零或与参考图差异超阈值 | 同左（T2 不需要桌面） | 两层都可，这是前期主判据 |
| **agent 崩溃** | `incarnation` 变化 / 心跳停更 / `launchctl runs` 增加 | 同左 | 两层都可（见 2.6.5） |
| **guest 失联但机器活着** | QMP `query-status` 正常但 SSH/串口无响应 | 平台 API 正常但 SSH 不通 | 两层都可 |
| **平台层故障** | — | API 返回 5xx 或实例 `status` 变为非 `active` | 仅 L2，必须与 guest 故障区分开 |

最后一行要强调：**平台故障不是实验失败**。harness 必须把它判为 `infra_error` 并重试，而不是记成被测代码的问题。把 Vultr 的一次 503 记成"我们的 kext 有 bug"会污染整个证据库。

#### 2.9.2 panic 的具体检测实现

L1，最可靠的一路——在 QEMU 命令行加 pvpanic 设备：

```bash
-device pvpanic
```

guest panic 时 QMP 会发出 `GUEST_PANICKED` 事件。`INFERRED`：macOS 不实现 pvpanic 协议，因此该事件在 macOS guest 上**很可能不会触发**。必须以串口模式匹配为主通道：

```rust
/// 串口流上的 panic 检测。匹配即立刻：抓截图、冻结 VM、归档。
const PANIC_PATTERNS: &[&str] = &[
    "panic(cpu ",
    "Kernel Extensions in backtrace",
    "Debugger called:",
    "Sleeping by machine_halt",
    "System Integrity Protection: ",   // 伴随 panic 头部输出
];
```

匹配到 panic 后的动作顺序（顺序重要，先取证再动机器）：

1. `screendump` 抓 panic 屏（panic 屏上有完整 backtrace，有时比日志更全）。
2. QMP `stop` 冻结 vCPU，防止自动重启把现场冲掉。
3. 导出串口日志全文。
4. 可选：QMP `dump-guest-memory` 落内核内存转储（体积大，仅在 `--deep-panic-capture` 时做）。
5. QMP `system_reset` 重启，等 SSH，回捞 `*.panic` 文件。
6. 归档并判定 `failed` / `panic`。

L2，只有事后一路：

```bash
# 1. SSH 断开 + 平台仍 running → 疑似 panic
# 2. 等待 panic_recovery_timeout（默认 180 秒），期间反复试 SSH
# 3. 仍不通 → 强制重启
curl -s -X POST "https://api.vultr.com/v2/instances/${INST_ID}/reboot" -H "$VH"
# 4. 等 SSH 回来（最长 600 秒）
# 5. 回捞证据
ssh … 'sudo ls -t /Library/Logs/DiagnosticReports/*.panic | head -1'
ssh … 'sysctl -n kern.boottime'          # 确认确实重启了
ssh … 'nvram -p | grep -i panic'          # 独立证据
# 6. 若 SSH 在第 4 步也没回来 → 判定 unrecoverable，走 2.9.4 的实例替换
```

#### 2.9.3 WindowServer 事件检测

```bash
# 流式判定（P4 之后的主通道）
log stream --style ndjson --predicate \
  'process == "WindowServer" OR (process == "launchd" AND eventMessage CONTAINS "WindowServer")'
```

判定规则：

- **重启**：出现 WindowServer 的新 pid，或 `launchctl print system/com.apple.WindowServer` 的 `runs` 计数增加。
- **挂起**：L1 上连续 3 次 `capture`（间隔 2 秒）的 PNG 的 SHA-256 完全一致，且在期间注入过鼠标移动。完全一致意味着连光标都没动，说明合成已停。
- **选错 device**：`ioreg -r -c IOAccelerator -l` 中查 WindowServer 持有的 accelerator，确认是本项目的服务而不是别的。这是组件 2 与 3 耦合（00-OVERVIEW 第 5 节）的直接验收点。

#### 2.9.4 失败时自动归档什么

**一个原则**：失败路径采集的东西必须是成功路径的超集，且在机器被重启或销毁之前完成。重启会冲掉易失证据（画面、内存、`log stream` 的尾部），销毁会冲掉一切。

归档清单按失败模式分档：

| 失败模式 | 额外归档项 |
|---|---|
| 全部失败 | 2.8 全部项 + `log-all.ndjson.gz` + 失败时刻截图（L1）+ 完整串口日志（L1）+ 实验配置快照 + payload 的 SHA-256 |
| panic | panic 屏截图、`*.panic` 全文、`nvram -p`、`shutdown-cause.txt`、（可选）`dump-guest-memory` 输出 |
| early boot 卡死 | 串口全文、最后一帧截图、每 10 秒一帧的启动过程截图序列（L1） |
| WindowServer 事件 | 事件前后各 60 秒的 `log stream` 窗口、事件前最后一帧与事件后第一帧截图、`ioreg -r -c IOAccelerator`、`ioreg -r -c IOFramebuffer` |
| hang | `sample <pid> 10 -file sample.txt`、`spindump -timeline`、`vmmap <pid>`、`lsof -p <pid>` |
| 无输出 | 渲染结果 PNG、参考图 PNG、逐像素差异图、Lavapipe 日志（`VK_LOADER_DEBUG=all`） |
| agent 崩溃 | `/var/log/harness-agent.err.log`、`incarnation` 前后值、`launchctl print` 前后输出、agent 自身的 `.ips` 崩溃报告 |
| 平台故障 | 完整 HTTP 请求/响应（脱敏后）、实例对象 JSON、`GET /v2/instances/{id}` 的连续采样 |

hang 的三条命令：

```bash
sample "$PID" 10 -file sample.txt          # 10 秒用户态栈采样
sudo spindump -timeline 10 -file spindump.txt
vmmap "$PID" > vmmap.txt 2>&1
```

**自动归档必须有体积上限**，否则一次 `log collect` 加内存转储能吃掉几十 GB。默认单实验归档上限 2 GB，超出时按优先级丢弃：先丢内存转储，再丢 `log-all`，再丢截图序列，**结构化结果 JSON 与 panic 报告永不丢弃**。

### 2.10 证据归档格式

#### 2.10.1 目录结构

```text
evidence/
└── 2026-10-30/
    └── exp-20261030T110218Z-e7f2a1c9/
        ├── result.json                 ← 结构化结果，schema 见 2.10.3
        ├── MANIFEST.json               ← 全部产物的 SHA-256 与大小
        ├── config/
        │   ├── experiment.json         ← 用例定义（含 tier、超时、判据）
        │   ├── platform.json           ← 平台与实例/VM 的完整描述
        │   ├── build.json              ← 被测构建的版本清单（见 70 第 7 节）
        │   └── env.json                ← 注入的环境变量
        ├── guest/
        │   ├── sysinfo.json
        │   ├── ioreg-full.plist.gz
        │   ├── ioreg-ioaccelerator.txt
        │   ├── ioreg-iofb.txt
        │   ├── kextstat.txt
        │   ├── kmutil-showloaded.txt
        │   ├── kmutil-diagnostics.txt
        │   ├── sp-displays.json
        │   ├── metal-devices.json
        │   └── nvram-all.txt
        ├── logs/
        │   ├── log-kernel.ndjson.gz
        │   ├── log-windowserver.ndjson.gz
        │   ├── log-metal.ndjson.gz
        │   ├── log-kextmgmt.ndjson.gz
        │   ├── log-stream.ndjson.gz
        │   ├── log-all.ndjson.gz
        │   ├── serial.log              ← 仅 L1
        │   ├── harness-agent.err.log
        │   └── harness.logarchive.tar.gz   ← 仅失败时
        ├── crashes/
        │   ├── 2026-10-30-110412.panic
        │   └── WindowServer-2026-10-30-110415.ips
        ├── frames/
        │   ├── 000-boot-t0000.png
        │   ├── 001-boot-t0010.png
        │   ├── …
        │   ├── final.png
        │   └── failure.png
        ├── render/
        │   ├── offscreen.png
        │   ├── reference.png
        │   └── diff.png
        └── harness/
            ├── harness.log             ← harness 自身的执行日志
            └── api-trace.ndjson        ← 全部平台 API 调用（脱敏）
```

目录名 `exp-{ISO8601 basic UTC}-{实验 UUID 前 8 位}`，天然按时间排序且全局唯一。

#### 2.10.2 MANIFEST.json

每个产物一条记录，便于后续校验与去重：

```json
{
  "schema": "metal2vu.evidence.manifest/1",
  "experiment_id": "e7f2a1c9-0b44-4d8e-9a31-5c6b2d8f1a07",
  "generated_at": "2026-10-30T11:19:44Z",
  "artifacts": [
    {
      "path": "guest/ioreg-full.plist.gz",
      "bytes": 1843021,
      "sha256": "9f2c…",
      "media_type": "application/gzip",
      "collected_at": "2026-10-30T11:18:02Z",
      "collector": "agent:collect",
      "truncated": false
    },
    {
      "path": "frames/failure.png",
      "bytes": 421337,
      "sha256": "1ab4…",
      "media_type": "image/png",
      "collected_at": "2026-10-30T11:17:51Z",
      "collector": "host:qmp-screendump",
      "truncated": false
    }
  ],
  "dropped": [
    { "path": "logs/harness.logarchive.tar.gz",
      "reason": "archive_size_budget_exceeded", "would_be_bytes": 2847193021 }
  ],
  "manifest_sha256": "…"
}
```

`collector` 字段区分证据来自 host 还是 guest，这直接对应 00-OVERVIEW 第 7 节的"标注样本来源"规则：guest 内自述与 host 观测的可信度不同，不能混用。

`dropped` 数组必须存在（可为空）。静默丢弃证据比不采集更有害。

#### 2.10.3 result.json schema

这是管线对外的主要契约。要能被后续程序与模型直接消费，因此：字段扁平、枚举封闭、时间统一 UTC ISO-8601、所有度量带单位。

```json
{
  "schema": "metal2vu.evidence.result/1",

  "experiment_id": "e7f2a1c9-0b44-4d8e-9a31-5c6b2d8f1a07",
  "case_id": "T2.metal.offscreen-triangle",
  "tier": "T2",
  "started_at": "2026-10-30T11:02:18Z",
  "ended_at":   "2026-10-30T11:19:44Z",
  "duration_ms": 1046000,

  "verdict": "failed",
  "verdict_reason": "render_mismatch",
  "evidence_label": "BLOCKED",

  "platform": {
    "layer": "L1",
    "kind": "local-qemu",
    "region": null,
    "plan": null,
    "instance_id": null,
    "vm_name": "exp-e7f2a1c9",
    "cpu_model": "host/GenuineIntel",
    "vcpus": 8,
    "ram_mib": 16384,
    "firmware": "uefi-ovmf",
    "disk_controller": "ich9-ahci",
    "nic_model": "vmxnet3",
    "has_serial": true,
    "has_host_screen": true,
    "has_host_input": true
  },

  "guest": {
    "os_product": "macOS",
    "os_version": "26.7.2",
    "os_build": "25G325",
    "arch": "x86_64",
    "boot_time": "2026-10-30T11:03:04Z",
    "boot_args": "amfi_get_out_of_my_way=1 -v keepsyms=1",
    "csr_active_config": "0x7ef",
    "sip_status": "disabled",
    "amfi_disabled": true,
    "agent_version": "0.3.1",
    "agent_incarnation": 7
  },

  "build": {
    "build_id": "b-20261030-0914-a31f9c2",
    "git_commit": "a31f9c2d…",
    "git_dirty": false,
    "components": [
      { "name": "Metal2VuAccel.kext",      "version": "0.3.1",
        "sha256": "…", "install_path": "/Library/Extensions/Metal2VuAccel.kext" },
      { "name": "Metal2Vu.bundle",          "version": "0.3.1",
        "sha256": "…", "install_path": "/Library/GPUBundles/Metal2Vu.bundle" },
      { "name": "libvulkan_lvp.dylib",      "version": "mesa-26.0.0-devel+g1a2b3c4",
        "sha256": "…", "install_path": "/Library/GPUBundles/Metal2Vu.bundle/Contents/Resources/lib/libvulkan_lvp.dylib" },
      { "name": "libvulkan.1.dylib",        "version": "1.4.321",
        "sha256": "…", "install_path": "/Library/GPUBundles/Metal2Vu.bundle/Contents/Resources/lib/libvulkan.1.dylib" }
    ]
  },

  "steps": [
    { "name": "restore_snapshot", "status": "ok",    "duration_ms": 8412 },
    { "name": "wait_ready",       "status": "ok",    "duration_ms": 46118,
      "detail": { "ready_signal": "ssh" } },
    { "name": "deploy_payload",   "status": "ok",    "duration_ms": 12044,
      "detail": { "method": "ssh-scp", "sha256_verified": true } },
    { "name": "install",          "status": "ok",    "duration_ms": 94213 },
    { "name": "kextload",         "status": "ok",    "duration_ms": 31005,
      "detail": { "required_reboot": true } },
    { "name": "run_case",         "status": "failed","duration_ms": 61900,
      "detail": { "exit_code": 3, "stdout_artifact": "guest/probe-stdout.txt" } },
    { "name": "collect",          "status": "ok",    "duration_ms": 183002 },
    { "name": "archive",          "status": "ok",    "duration_ms": 41221 }
  ],

  "observations": {
    "kext_loaded": true,
    "service_published": true,
    "user_client_opened": true,
    "metal_devices": [
      { "name": "Metal2Vu Software Device", "registry_id": 4296098624,
        "is_low_power": false, "is_headless": false, "is_ours": true }
    ],
    "windowserver_pid_before": 182,
    "windowserver_pid_after": 182,
    "windowserver_restarts": 0,
    "panicked": false,
    "reboots": 1,
    "reboot_expected": true,
    "agent_restarted": false,
    "render": {
      "mode": "offscreen",
      "width": 512, "height": 512, "format": "BGRA8Unorm",
      "output_sha256": "…",
      "reference_sha256": "…",
      "mean_abs_error": 0.41,
      "max_abs_error": 1.0,
      "mismatch_fraction": 0.73,
      "all_zero": false
    }
  },

  "detections": [
    { "kind": "render_mismatch", "severity": "error",
      "at": "2026-10-30T11:16:19Z",
      "message": "offscreen output differs from reference beyond tolerance 0.02",
      "evidence": ["render/offscreen.png", "render/reference.png", "render/diff.png"] },
    { "kind": "log_pattern", "severity": "warn",
      "at": "2026-10-30T11:16:02Z",
      "message": "Vulkan loader reported no compatible driver on first attempt",
      "evidence": ["logs/log-metal.ndjson.gz#L4412"] }
  ],

  "costs": {
    "wall_clock_ms": 1046000,
    "platform_billed_hours": 0,
    "egress_bytes": 0,
    "archive_bytes": 412993011
  },

  "manifest": { "path": "MANIFEST.json", "sha256": "…" },
  "harness_version": "0.4.0",
  "notes": null
}
```

**封闭枚举**，不允许自由取值：

| 字段 | 取值 |
|---|---|
| `verdict` | `passed` / `failed` / `skipped` / `infra_error` / `inconclusive` |
| `verdict_reason` | `ok` / `render_mismatch` / `render_all_zero` / `panic` / `boot_timeout` / `windowserver_restart` / `windowserver_hang` / `hang` / `nonzero_exit` / `kext_load_failed` / `service_not_published` / `user_client_denied` / `agent_restarted` / `agent_unreachable` / `platform_error` / `unsupported_capability` / `precondition_failed` |
| `evidence_label` | `KNOWN` / `INFERRED` / `BLOCKED` / `TESTED`（对应 00-OVERVIEW 第 7 节） |
| `platform.layer` | `L1` / `L2` |
| `platform.kind` | `local-qemu` / `vultr` |
| `tier` | `T0` / `T1` / `T2` / `T3` / `T4` |
| `steps[].status` | `ok` / `failed` / `skipped` / `timeout` |
| `detections[].severity` | `info` / `warn` / `error` |

**三条设计决定**，各有理由：

1. `verdict` 与 `evidence_label` 分开。`verdict=passed` 只说明这次跑过了；`evidence_label=TESTED` 是对规格条目的断言，要求"在声明的平台层上、按声明的验收标准通过"。一次 L1 的 `passed` 不足以把一条需要 L2 证据的结论升级为 `TESTED`（见 2.1 的提升门槛第 4 条）。
2. `inconclusive` 必须存在。"没得出结论"与"失败了"是不同的信息，混在一起会让后续分析把平台噪声当成代码缺陷。
3. `unsupported_capability` 配 `verdict=skipped`。这是 Vultr 上 T3/T4 用例的正常归宿（2.3 的 `ScreenError::Unsupported`），不该显示为红色。

schema 文件本身由 `schemars` 从 Rust 类型生成并随 harness 版本发布到 `docs/spec/schemas/result-1.json`，保证代码与文档不漂移。

---

## 3. MCP 工具面设计

### 3.1 为什么自建而不用 Vultr 官方 MCP

Vultr 提供官方托管 MCP 服务器，端点 `https://mcp.vultr.com/mcp`，按产品域还有分端点；但它被明确声明为**只读**，不能创建、修改或删除任何资源，也不含任何花钱的工具（转述自 <https://docs.vultr.com/reference/mcp-server/overview> 与 <https://docs.vultr.com/reference/mcp-server/tools/overview>）。

因此它能做的只有"查我有哪些实例"。实验管线需要创建、恢复、销毁、挂盘、执行命令——全部在它能力之外。

结论：**自建 MCP 服务器**（`harness-mcp`，与 `harness-cli` 同一 crate 的两个 bin）。可以把官方只读 MCP 作为旁路的账务与资源查询补充，但管线主干不依赖它。

### 3.2 两条贯穿全部工具的设计约束

**约束 1：长耗时操作一律异步化。** 管线里有大量分钟级到半小时级的操作（快照创建最长约 30 分钟，见 1.2；实例 restore 分钟级；macOS 启动数十秒到数分钟）。如果这些以同步工具调用暴露，模型会在一次工具调用上阻塞十几分钟，期间什么都做不了，而且极易撞上客户端超时。

统一模式：**提交 → 拿 handle → 轮询 / 等待**。

- 所有可能超过 10 秒的工具立即返回 `{"job_id": "...", "state": "running", "poll_after_ms": 5000}`。
- 一个通用 `harness.job_wait` 工具做有界等待：最多等 `max_wait_ms`（硬上限 60 秒），到时返回当前状态而不是继续挂着。模型据此决定是继续等还是先去做别的。
- 一个 `harness.job_get` 做即时查询，永不阻塞。
- 每个 job 带 `progress`（0..1 或 `null`）与 `stage`（人类可读的阶段名），让模型能判断是在推进还是卡住了。

**约束 2：失败语义三分，不混用。** 每个工具的错误都归入三类，模型据此选择不同动作：

| 类别 | 含义 | 模型应做的事 |
|---|---|---|
| `unsupported` | 本平台不具备该能力（例：Vultr 上截图） | 跳过，不重试，记 `skipped` |
| `transient` | 平台或网络的瞬时故障（5xx、超时、速率限制） | 按 `retry_after_ms` 退避重试 |
| `permanent` | 请求本身错（参数非法、资源不存在、配额用尽、余额不足） | 不重试，报告给人 |

错误体统一形状：

```json
{ "error": { "class": "transient", "code": "vultr_rate_limited",
             "message": "…", "retry_after_ms": 3000,
             "details": { "http_status": 429 } } }
```

### 3.3 工具清单

命名空间 `harness.*`。所有时间参数单位毫秒，所有时间戳为 UTC ISO-8601。

#### 3.3.1 作业控制

| 工具 | 入参 | 返回 | 失败语义 |
|---|---|---|---|
| `harness.job_get` | `job_id: string` | `{job_id, state: "running"\|"done"\|"failed"\|"cancelled", stage: string, progress: number\|null, started_at, updated_at, result: object\|null, error: object\|null}` | `permanent/job_not_found` |
| `harness.job_wait` | `job_id: string`, `max_wait_ms: int (≤60000, default 30000)` | 同 `job_get`。到时返回当前状态，**不报错** | `permanent/job_not_found` |
| `harness.job_cancel` | `job_id: string` | `{job_id, state: "cancelled"\|"done", note}` | `permanent/job_not_cancellable` |
| `harness.job_list` | `state?: string`, `limit?: int` | `{jobs: [...]}` | — |

`job_wait` 的有界语义是整个异步设计的关键。无界等待会让模型失去控制权；有界等待让它每 30 秒拿回一次决策机会。

#### 3.3.2 实例生命周期

| 工具 | 入参 | 返回 | 失败语义 |
|---|---|---|---|
| `harness.env_list` | — | `{envs: [{env_id, layer: "L1"\|"L2", kind, label, state, caps: {host_screen, host_input, serial, snapshot_restore_seconds}}]}` | — |
| `harness.env_create` | `layer`, `plan?`, `region?`, `from_snapshot?`, `from_iso?`, `label`, `tags?: [string]`, `vcpus?`, `ram_mib?` | **async** `{job_id}`；完成后 `result: {env_id, ip?, ssh_port, credentials_ref}` | `permanent/quota_exceeded`、`permanent/insufficient_funds`、`transient/*` |
| `harness.env_get` | `env_id` | `{env_id, layer, state, power_state, ip, plan, region, uptime_ms, caps}` | `permanent/env_not_found` |
| `harness.env_start` / `env_stop` / `env_reboot` | `env_id`, `force?: bool` | **async** `{job_id}` | — |
| `harness.env_destroy` | `env_id`, `confirm: bool (必须为 true)` | **async** `{job_id}` | `permanent/confirmation_required` |
| `harness.env_wait_ready` | `env_id`, `signal: "ssh"\|"serial_marker"\|"agent_ping"`, `timeout_ms (default 600000)` | **async** `{job_id}`；完成后 `result: {ready: bool, signal_seen, elapsed_ms, last_frame_artifact?}` | — |

**`env_destroy` 强制 `confirm` 的理由**：销毁是不可逆且会丢失现场的操作。按安全准则，不可逆动作需要显式意图，不能被一次参数笔误触发。

**`env_wait_ready` 必须独立成一个工具**，不能塞进 `env_create` 里。平台报告的 `active` 不等于 guest 就绪（2.4.4），两者是不同的等待对象、不同的超时、不同的失败含义。

凭据不经 MCP 返回。`credentials_ref` 是一个指向本地凭据存储的不透明键；真实密码与私钥由 harness 进程持有，模型拿不到也不需要。这避免把 root 密码写进会话记录。

#### 3.3.3 快照

| 工具 | 入参 | 返回 | 失败语义 |
|---|---|---|---|
| `harness.snapshot_list` | `layer?`, `prefix?` | `{snapshots: [{snapshot_id, label, layer, created_at, size_bytes, state, is_golden}]}` | — |
| `harness.snapshot_create` | `env_id`, `label`, `golden?: bool` | **async** `{job_id}`（L2 可达 30 分钟）；完成后 `result: {snapshot_id}` | `transient/*` |
| `harness.snapshot_restore` | `env_id`, `snapshot_id`, `wait_ready?: bool (default true)` | **async** `{job_id}`；完成后 `result: {restored: true, ready: bool, elapsed_ms}` | `permanent/snapshot_not_found`、`permanent/snapshot_layer_mismatch` |
| `harness.snapshot_delete` | `snapshot_id`, `confirm: bool` | `{deleted: true}` | `permanent/snapshot_is_golden`（golden 需先去标） |

`snapshot_layer_mismatch`：L1 的 qcow2 与 L2 的平台快照不可互换。显式报错好过产生一个无法启动的环境。

#### 3.3.4 画面与输入

**L1 全部可用。L2 的可用性取决于 guest 内 ARD/VNC（2.3.5）是否连得上**：桌面活着时这一组可用但 `screen_caps` 报 `host_level: false`；桌面死掉、未进系统、或 `-vnclegacy` 被拒时，整组返回 `unsupported/no_host_screen`。L2 永远拿不到 host 层画面，这是平台事实（1.3），不是实现缺失。

**L2 上的截图不构成 T3 判据**（2.3.5 告警 1：黑屏无法区分"没渲染"与"捕获路径坏了"）。工具层对此的落地：`screen_capture` 在 `host_level: false` 时，返回体必须带 `attributable: false`，`experiment_verdict` 不得把这类帧计入判定。

| 工具 | 入参 | 返回 | 失败语义 |
|---|---|---|---|
| `harness.screen_caps` | `env_id` | `{capture, input, host_level, framebuffer: {width,height}\|null, source}` | — |
| `harness.screen_capture` | `env_id`, `rect?: {x,y,w,h}`, `label?` | `{artifact_path, sha256, width, height, captured_at, source, preview_png_b64?}` | `unsupported/no_host_screen` |
| `harness.screen_wait_stable` | `env_id`, `rect?`, `stable_for_ms (default 1500)`, `timeout_ms (default 60000)` | **async** `{job_id}`；完成后 `result: {stable: bool, artifact_path, sha256}` | `unsupported/no_host_screen` |
| `harness.screen_wait_match` | `env_id`, `template_ref`, `rect?`, `tolerance (default 0.02)`, `timeout_ms` | **async** `{job_id}`；完成后 `result: {matched: bool, mean_abs_error, artifact_path}`。**超时也返回最后一帧** | `unsupported/no_host_screen` |
| `harness.input_click` | `env_id`, `x`, `y`, `button?: "left"\|"right"\|"middle"`, `count?: int (default 1)` | `{ok: true}` | `unsupported/no_host_input` |
| `harness.input_move` | `env_id`, `x`, `y` | `{ok: true}` | `unsupported/no_host_input` |
| `harness.input_drag` | `env_id`, `from: [x,y]`, `to: [x,y]`, `button?`, `steps?: int (default 20)` | `{ok: true}` | `unsupported/no_host_input` |
| `harness.input_text` | `env_id`, `text: string`, `per_key_ms?: int (default 30)` | `{ok: true, chars_sent: int}` | `unsupported/no_host_input`、`permanent/unsupported_character` |
| `harness.input_chord` | `env_id`, `mods: ["cmd"\|"ctrl"\|"alt"\|"shift"]`, `key: string` | `{ok: true}` | `unsupported/no_host_input` |
| `harness.input_key` | `env_id`, `key: string`, `down?: bool\|null` | `{ok: true}` | `unsupported/no_host_input` |

`preview_png_b64` 可选且默认关闭。截图是几百 KB 到几 MB，无条件内联会迅速填满上下文。默认只回 `artifact_path` 与哈希；模型需要看图时显式请求预览，服务端缩放到 ≤1024 px 宽再编码。**这是上下文预算的硬设计，不是优化。**

`input_text` 对非 ASCII 返回 `permanent/unsupported_character` 而不是静默丢弃。静默丢字符会导致"密码输错但不知道为什么"这类极难诊断的失败。

#### 3.3.5 命令执行

| 工具 | 入参 | 返回 | 失败语义 |
|---|---|---|---|
| `harness.exec` | `env_id`, `argv: [string]`, `cwd?`, `env?: {k:v}`, `stdin_b64?`, `timeout_ms (default 120000)`, `sudo?: bool`, `max_output_bytes?: int (default 262144)` | **async**（>10 秒时）或同步；`result: {exit_code, stdout, stderr, truncated, duration_ms, stdout_artifact?, stderr_artifact?}` | `permanent/env_unreachable`、`transient/ssh_transient` |
| `harness.exec_script` | `env_id`, `interpreter: "bash"\|"zsh"`, `script: string`, 其余同上 | 同上 | 同上 |
| `harness.agent_ping` | `env_id` | `{alive: bool, agent_version, incarnation, uptime_ms, current_task_id\|null}` | `permanent/agent_unreachable` |
| `harness.agent_task` | `env_id`, `kind`（2.6.3 的枚举）, `payload: object`, `deadline_ms` | **async** `{job_id}`；完成后为 agent 的 result 报文 | 同 2.6.3 的 `status` 映射 |
| `harness.file_put` | `env_id`, `local_ref`, `remote_path`, `verify_sha256: bool (default true)` | `{ok, bytes, sha256}` | `permanent/hash_mismatch` |
| `harness.file_get` | `env_id`, `remote_path`, `max_bytes?` | `{artifact_path, bytes, sha256, truncated}` | `permanent/not_found` |

**`argv` 是数组，不是字符串。** 不提供"随便给我一条 shell 命令行"的接口，参数不经 shell 拼接。这既避免引号与空格的 bug，也避免把未经转义的外部值注入到远端 shell。需要 shell 语义时用 `exec_script`，此时 `script` 作为标准输入喂给解释器，而不是拼进命令行。

输出超过 `max_output_bytes` 时截断并落盘，返回 `truncated: true` 与 `stdout_artifact` 路径。**绝不把 MB 级 stdout 直接返回给模型。**

#### 3.3.6 日志与证据采集

| 工具 | 入参 | 返回 | 失败语义 |
|---|---|---|---|
| `harness.collect` | `env_id`, `experiment_id`, `profile: "minimal"\|"standard"\|"failure"\|"full"`, `window?: {start,end}` | **async** `{job_id}`（`full` 可数分钟）；完成后 `result: {artifact_count, total_bytes, manifest_path, dropped: [...]}` | — |
| `harness.logs_query` | `env_id`, `predicate: string`, `window: {start,end}`, `limit?: int (default 200)`, `style?: "ndjson"\|"compact"` | `{lines: [...], truncated, artifact_path}` | `permanent/invalid_predicate` |
| `harness.serial_tail` | `env_id`, `lines?: int (default 200)`, `since?: timestamp` | `{lines: [...], artifact_path}` | `unsupported/no_serial`（L2 恒为此） |
| `harness.crash_reports` | `env_id`, `since?: timestamp`, `kinds?: ["panic","ips"]` | `{reports: [{path, kind, created_at, sha256, process?, excerpt}]}` | — |
| `harness.detect` | `env_id`, `experiment_id`, `checks?: [string]` | `{detections: [...], summary: {panicked, windowserver_restarts, agent_restarted, reboots}}` | — |

四个 profile 的区别就是 2.9.4 的归档清单分档：`minimal` 只采 `sysinfo` + `ioreg-ioaccelerator` + `kextstat`（秒级）；`standard` 是 2.8 全部项；`failure` 加 `log-all` 与崩溃报告；`full` 再加 `log collect` 的 `.logarchive`。

`crash_reports` 的 `excerpt` 只给前若干行（panic 的头部已含最关键的 `panic(cpu …)` 行与 backtrace 起始），全文走 `artifact_path`。

#### 3.3.7 实验编排与结果查询

| 工具 | 入参 | 返回 | 失败语义 |
|---|---|---|---|
| `harness.experiment_run` | `case_id`, `layer`, `build_ref`, `env_id?`（省略则自动选/建）, `overrides?: {timeout_ms, env, tier}` | **async** `{job_id, experiment_id}`；完成后 `result` 即 2.10.3 的 `result.json` | `permanent/case_not_found`、`permanent/tier_not_supported_on_layer` |
| `harness.experiment_get` | `experiment_id` | 完整 `result.json` | `permanent/not_found` |
| `harness.experiment_list` | `case_id?`, `layer?`, `verdict?`, `build_ref?`, `since?`, `limit?` | `{experiments: [{experiment_id, case_id, layer, verdict, verdict_reason, started_at, duration_ms}]}` | — |
| `harness.experiment_artifacts` | `experiment_id`, `glob?: string` | `{artifacts: [{path, bytes, sha256, media_type}]}` | — |
| `harness.experiment_artifact_read` | `experiment_id`, `path`, `offset?`, `max_bytes? (≤131072)`, `as?: "text"\|"base64"` | `{content, bytes_read, eof}` | `permanent/not_found`、`permanent/too_large` |
| `harness.experiment_diff` | `experiment_id_a`, `experiment_id_b` | `{verdict_changed, observation_deltas: {...}, new_detections: [...], resolved_detections: [...]}` | — |
| `harness.case_list` | `tier?`, `layer?` | `{cases: [{case_id, tier, layers, description, default_timeout_ms}]}` | — |

**`tier_not_supported_on_layer` 是 2.1 提升门槛的程序化落地**：试图在 L2 上跑 T4 用例，直接被工具层拒掉，不是跑完才发现。规则写在代码里，不靠人记。

**`experiment_diff` 是让模型自己推进实验的关键工具。** 迭代的核心动作是"改一行，再跑一次，看变了什么"。如果每次都要模型自己把两份几百行的 JSON 读进上下文比对，上下文会被迅速耗尽。服务端做 diff，只回变化量。

`experiment_artifact_read` 的 128 KB 上限与 `offset` 分页同理：让模型能精确读一段日志，而不是把整个文件拉进来。

#### 3.3.8 自定义镜像与 ISO 槽位

3.3.2 的 `env_create` 接受 `from_iso`，但没有任何工具能产出一个 `iso_id`。这一组补上它，并把 1.2 的三条硬约束变成工具层的强制行为。

| 工具 | 入参 | 返回 | 失败语义 |
|---|---|---|---|
| `harness.image_list` | `layer?` | `{images: [{image_id, layer, label, kind: "install"\|"rescue"\|"payload", size_bytes, sha512, state, slot?: int, published_url?}]}` | — |
| `harness.image_publish` | `local_path`, `label`, `kind` | **async** `{job_id}`；完成后 `result: {image_id, published_url, sha512, size_bytes}` | `permanent/image_too_large`（>10 GB）、`permanent/no_publish_endpoint` |
| `harness.image_register` | `image_id`, `layer`, `slot?: 0\|1`, `confirm: bool` | **async** `{job_id}`（L2 为平台拉取，分钟级）；完成后 `result: {platform_iso_id, hash_verified: bool, slot}` | `permanent/iso_slots_full`、`permanent/hash_mismatch`、`permanent/confirmation_required` |
| `harness.image_unregister` | `platform_iso_id`, `confirm: bool` | **async** `{job_id}` | `permanent/image_in_use` |
| `harness.image_attach` / `image_detach` | `env_id`, `platform_iso_id?`, `confirm: bool` | **async** `{job_id}`；完成后 `result: {iso_state, rebooted: true}` | `permanent/confirmation_required` |

**为什么 `publish` 与 `register` 必须是两个工具。** Vultr 只接受公开 URL，没有直传接口（1.2 约束 1）。这是两个性质完全不同的动作：`publish` 是把本地文件放到自己的托管端点（本地层直接返回 `file://` 路径，不做任何上传），`register` 是让平台去拉。合成一个工具会让"上传成功但平台拉取失败"这类最常见的失败无法定位在哪一步。L1 的 `register` 是本地登记，秒级完成。

**`iso_slots_full` 不自动腾位。** 账户上限 2 个（1.2 约束 2），槽位是稀缺资源且按约定分工——槽 0 放安装介质、槽 1 放救援/payload 介质。工具发现满了就报错，由调用方显式决定踢掉哪一个。让它自动回收会在"另一个实验正用着那张救援盘"时造成不可恢复的损失。

**`hash_mismatch` 必须是 `permanent` 且必须阻断。** 平台回报 `md5sum` / `sha512sum`，这是镜像完整性的唯一可得校验点（1.2 结尾）。拉取过程中的静默截断会表现为"引导到一半黑屏"，排查成本极高。`register` 在哈希不符时自动删除平台侧对象再报错，不留半个坏镜像占着槽位。

**`image_attach` 强制 `confirm` 的理由**：挂载与卸载 ISO 都会重启实例（1.2 的端点表）。这是会丢现场的动作，与 `env_destroy` 同级，不能被一次参数笔误触发。

**不提供 `image_delete_local`。** 本地镜像归档由人管理，不由模型管理。镜像构建产物是 `70-BUILD-PACKAGE.md` 第 7 节版本清单的一部分，删掉就不可复现了。

### 3.4 并发、配额与成本护栏

工具面必须自带护栏，否则一个循环就能跑出一笔意外账单。

| 护栏 | 默认值 | 行为 |
|---|---|---|
| L2 并发实例上限 | 2 | 超限时 `env_create` 返回 `permanent/concurrency_limit` |
| L2 实例最长存活 | 24 小时 | 超时自动 `halt` 并告警，不自动销毁（销毁会丢现场） |
| 单日 L2 新建实例数上限 | 10 | 考虑到 1.6 的最小计费单位 1 小时 |
| 快照总数上限 | 8（含 golden） | 超限时拒绝创建并列出可删候选 |
| `tmp-` 前缀快照保留 | 72 小时 | 自动删除 |
| 单实验归档上限 | 2 GB | 按 2.9.4 的优先级丢弃，记入 `dropped` |
| 证据总容量 | 200 GB | 超限时按时间顺序归档到冷存储，`passed` 的先走，`failed` 的保留更久 |

这些值放在 `harness.toml`，由人改，不由模型改。**不提供修改护栏的工具。**

### 3.5 一个完整的实验回路示例

模型侧的调用序列，展示异步模式如何避免阻塞：

```text
1. harness.case_list { tier: "T2" }
      → 选定 case_id = "T2.metal.offscreen-triangle"

2. harness.env_list {}
      → 发现 L1 环境 env-local-01 处于 stopped

3. harness.snapshot_list { layer: "L1" }
      → golden = "snap-local-golden-r3"

4. harness.experiment_run {
       case_id: "T2.metal.offscreen-triangle",
       layer: "L1",
       build_ref: "b-20261030-0914-a31f9c2",
       env_id: "env-local-01" }
      → { job_id: "job-7f21", experiment_id: "exp-e7f2a1c9" }

5. harness.job_wait { job_id: "job-7f21", max_wait_ms: 30000 }
      → { state: "running", stage: "install", progress: 0.45 }
      （此处模型可以去做别的事，而不是干等）

6. harness.job_wait { job_id: "job-7f21", max_wait_ms: 30000 }
      → { state: "done", result: { verdict: "failed",
                                   verdict_reason: "render_mismatch" } }

7. harness.detect { env_id: "env-local-01", experiment_id: "exp-e7f2a1c9" }
      → 两条 detection：render_mismatch(error) + log_pattern(warn)

8. harness.experiment_artifacts { experiment_id: "exp-e7f2a1c9",
                                  glob: "render/*" }
      → offscreen.png / reference.png / diff.png

9. harness.experiment_artifact_read {
       experiment_id: "exp-e7f2a1c9",
       path: "logs/log-metal.ndjson", offset: 4300, max_bytes: 16384 }
      → 定位到 loader 第一次没找到驱动的那几行

10. （改代码、重新构建）

11. harness.experiment_run { …, build_ref: "b-20261030-1142-c88e0a1" }
12. harness.job_wait …
13. harness.experiment_diff { experiment_id_a: "exp-e7f2a1c9",
                              experiment_id_b: "exp-9b31c2d7" }
      → { verdict_changed: true,
          resolved_detections: ["render_mismatch"],
          observation_deltas: { "render.mean_abs_error": [0.41, 0.0] } }
```

第 13 步是整个设计要达到的效果：**判断"修好了没有"是一次工具调用，不是一次人工比对。**

---

## 4. 落地顺序

### 4.1 E0：第一个实验，也是唯一的当前目标

**E0-L1：macOS 在本地 KVM 上启动并 SSH 可达。**

验收：`harness.env_wait_ready { signal: "ssh" }` 返回 `ready: true`，且 `harness.collect { profile: "standard" }` 产出完整证据包。

这一步交付：L1 的 `Platform` 实现、`Ssh` 实现、串口采集、`collect` 的 2.8 清单、`result.json` 落盘。暂不需要 `ScreenIO`、不需要 MCP、不需要 agent（用裸 SSH 执行命令）。

**E0-L2：macOS 在 Vultr 实例上启动并 SSH 可达。**

这一步会关闭 1.5 表中的全部 `BLOCKED` 项，并回答第 5 节的头号风险。它可能的结论包括"做不到"——如果是，整个 L2 层的设计需要重做（见 5.1 的缓解路径）。

**E0 之前不要写 MCP 工具面。** 工具面是对一个已能工作的管线的封装；先封装再实现会得到一个形状错误的 API。

### 4.2 之后的顺序

| 批次 | 交付 | 依赖 |
|---|---|---|
| B1 | guest agent（`ping` / `sysinfo` / `run` / `collect`）+ launchd 托管 + `incarnation` 机制 | E0-L1 |
| B2 | golden snapshot 流程（L1 的 overlay 模式）+ `experiment_run` 骨架 + `result.json` | B1 |
| B3 | `metal-probe`：Metal device 枚举 + 离屏渲染 + 参考图比较。**这是 T2 的核心工具，也是 P3 之前唯一的像素级判据** | B2 |
| B4 | `Detector`：panic / 重启 / agent 崩溃 / 无输出四类检测 | B2 |
| B5 | MCP 工具面（3.3.1–3.3.3、3.3.5–3.3.8），**先不含 3.3.4** | B2 + B4 |
| B6 | L2 的 `Platform` 实现 + golden snapshot（L2） | E0-L2 |
| B7 | `ScreenIO` 的 QMP 实现 + 3.3.4 工具组 | B5 |
| B8 | `ScreenIO` 的 VNC 实现（`HostVnc`）+ `wait_match` + 安装流程脚本化 | B7 |
| B8b | `ScreenIO` 的 `GuestArdVnc` 实现（2.3.5）+ `kickstart` 固化进 golden snapshot | B8 + P3 |
| B9 | T4 用例集 | P5 |

`ScreenIO` 排在 B7/B8 而不是更早，是 2.7 的直接结果：**P3 之前它产生不了有用的信息**（画面上没东西可看），而 `metal-probe` 的离屏比较在 P3 就能给出精确判据。先做截图是把顺序搞反了。

### 4.3 未解决项清单

| 编号 | 事项 | 标签 | 查清方法 |
|---|---|---|---|
| H-001 | Vultr 实例的系统盘控制器与网卡型号 | `BLOCKED` | E0-L2 的首启探针：`ioreg -l` 看 `IOPCIDevice` 的 vendor/device ID |
| H-002 | Vultr 实例重启后 EFI NVRAM 变量是否保留 | `BLOCKED` | 写标记变量 → 重启 → 读回 |
| H-003 | macOS 能否在 Vultr 的设备模型下启动 | `BLOCKED` | E0-L2 |
| H-004 | Vultr Block Storage 热插拔在 macOS guest 内是否可见 | `BLOCKED` | E0-L2 之后，`attach` 后看 `diskutil list` |
| H-005 | `default_password` 是否仅在创建响应中返回 | `INFERRED` | 创建后对比 `POST` 响应与 `GET` 响应 |
| H-006 | QMP `abs` 事件坐标系与帧缓冲像素的换算系数 | `INFERRED` | B7 时用已知位置点击校准 |
| H-007 | `-chardev socket` 是否支持 `logfile=` | `INFERRED` | 本地 `qemu-system-x86_64` 直接试 |
| H-008 | 2.8.8 中 Metal 侧诊断环境变量在 25G325 上的实际有效性 | `INFERRED` | B3 时逐一实测，结果写回该表 |
| H-009 | 25G325 的用户态崩溃报告是 `.ips` 还是 `.crash` | `INFERRED` | E0-L1 后 `ls /Library/Logs/DiagnosticReports/` |
| H-010 | macOS guest 是否响应 `pvpanic` | `INFERRED` | E0-L1 时故意触发 panic（`sudo dtrace -w -n "BEGIN{panic();}"`，需 SIP 放开 dtrace 位） |
| H-011 | `kickstart -setvnclegacy -vnclegacy yes` 在 25G325 上是否仍让标准 RFB 客户端可连（2.3.5） | `INFERRED` | E0-L1 之后即可测：guest 内执行 `kickstart`，本地 `vncdotool` 隧道连 5900 抓一帧 |
| H-012 | TCC 是否拦截 ARD agent 的屏幕录制（2.3.5） | `INFERRED` | 同 H-011 一次测完：若连上但帧全黑而 `screencapture` 有内容，即 TCC 拦截 |
| H-013 | `macos-15-intel` 是否按"标准运行器"计费（公开仓库免费无限） | `INFERRED` | 公开仓库跑一次 5 分钟空 job，看账单页是否计入分钟数 |

---

## 5. 风险

按严重度排列，只列真正可能让方案失效的。

### 5.1 macOS 可能根本无法在 Vultr 上启动（头号风险）

Vultr 文档显示平台使用 VirtIO 与 NVMe（1.5）。macOS 原生不含 VirtIO 块设备驱动，社区在 KVM 上运行 macOS 的通行配置是模拟 AHCI 启动盘；网卡侧有第三方 `virtio-net-osx`，**块设备侧没有可用的等价物**（1.5 的证据）。磁盘驱动是启动的必要条件。

如果 Vultr 的系统盘是 VirtIO 且无 NVMe 选项，macOS 看不到启动盘，OpenCore 连引导都无从开始。

这不仅威胁 harness 的 L2 层，**它威胁 00-OVERVIEW 第 2.1 节所定义的整个部署形态**——"macOS 作为云平台自己的 KVM guest 直接运行"。

缓解路径，按优先级：

1. **E0-L2 尽早执行**，把这件事从未知变成已知。它是一次性的、几美元的实验，却决定了整个 L2 架构是否成立。
2. 若盘是 NVMe：macOS 有原生 NVMe 支持，加上 OpenCore 的相应配置可能可行。先查清是哪种。
3. 若盘是 VirtIO：评估为 macOS 写一个 VirtIO-blk 驱动的代价。这会**新增一个与项目主线无关的内核组件**，但它比"放弃云部署"便宜。
4. 退路：把 L2 换成提供可控设备模型的平台（允许自定义 QEMU 参数的 provider，或裸金属）。这会削弱"任何通用 KVM 实例"这一卖点，但保住项目可运行性。00-OVERVIEW 第 2.1 节称 Vultr 为"参考平台"而非唯一平台，这条退路与总览不冲突。

### 5.2 Vultr 上没有 panic 期可观测性

1.4 的结论：没有串口，panic 时的画面只在网页控制台里，SSH 已断。L2 上的 panic 只能靠重启后回捞报告，而且前提是根分区还能挂载、panic 报告确实写成功了。

后果：**一个只在 L2 复现的内核缺陷会非常难查。** 它不会阻塞项目，但会在出现时造成以天计的停滞。

缓解：2.1 的提升门槛第 1 条（内核改动必须先过 L1）把这类情况的发生概率压到最低。接受残余风险。

### 5.3 没有 host 层画面与输入，L2 的显示验证能力受限

1.3 的结论。L2 上的画面只有 guest 内两条路径（2.3.5）：ARD/VNC 与 `screencapture`。两者都在最需要的时候不可用——WindowServer 死了、还没进系统、或内核 panic。

**2.3.5 补回的是交互能力，不是归因能力。** ARD/VNC 给了 L2 输入注入和持续连接，这让 T4 在 L2 上可跑；但它的取帧路径穿过本项目正在改的 WindowServer/CoreGraphics 捕获链，一张黑图无法区分"没渲染"与"捕获坏了"。所以 T3 的判定仍然只能在 L1 做。

这意味着**"macOS 在云上出桌面"这个项目的最终目标，在 L2 上的验证手段比 L1 弱**。最后一步的签收可能需要人工打开网页控制台看一眼。

缓解：接受，并分两层处理。L2 上能自动判定的是"桌面已经工作"之后的交互（ARD/VNC，`attributable: false` 但够用）；"桌面是否工作"的首次判定留在 L1。真正只能人工的是"L1 通过、L2 黑屏"这一种差异场景的归因——把人工签收显式写进验收流程并标 `capture_method: "manual-portal"`，而不是假装自动化。

### 5.4 Lavapipe 在 x86_64 macOS 上的可建性尚未验证

详见 `70-BUILD-PACKAGE.md` 第 3.4 节。存在 arm64 macOS 的成功先例，但 x86_64 未验证，且 LLVM 的链接方式（静态 vs 动态）与 dylib 重定位是已知的坑点。

它不影响 harness 的架构，但会阻塞 B3（`metal-probe` 的离屏渲染），而 B3 是 T2 的唯一判据。

### 5.5 整条管线最大的风险是它自己变成项目

harness 的规模会膨胀。本文定义的东西如果全部实现，是一个几千行的 Rust 项目加一个 guest agent 加一个 MCP 服务器。而项目真正的目标是 `10`/`11`/`20` 三个分册里的胶水层。

**这是最可能实际发生的失败模式**：花六周把 harness 做得很漂亮，而 guest 上依然什么都没跑过。

对策是 4.1 的硬性约束：**E0 之前只写 E0 需要的代码。** E0-L1 需要的只有：启一个 QEMU、读串口、跑 SSH 命令、落一个 JSON。那大概是四百行。本文其余部分是在 E0 通过之后才开始有价值的设计，不是现在要写的代码。

---

## 6. 相关分册

- `70-BUILD-PACKAGE.md`：被测产物如何构建、SIP/AMFI 如何固化、安装布局与加载顺序。本文的 `build_ref` 与 `components[]` 由它定义。
- `90-EVIDENCE-INDEX.md`：静态样本索引。本文产出的是运行证据，两者在 `evidence_label` 上共用一套标签体系。
- `00-OVERVIEW.md` 第 7 节：证据规则。本文第 2.10.3 节的 `evidence_label` 与 `platform.layer` 是该规则在运行证据上的落地。
