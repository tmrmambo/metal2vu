> [!CAUTION]
> 本文档已于 2026-10-29 弃用，且含不安全样例。
> 不得执行固定密码、关闭防火墙或未经验证的云设备配置。
> 当前约束见 `..\CLOUD_DEPLOYMENT_SPEC.md`。


﻿# 公有云 macOS 虚拟机自动化部署与硬件兼容性技术规范

本文档系统性记录 macOS 虚拟机以无宿主依赖、单磁盘镜像形式部署于主流公有云（AWS、Google Cloud、Microsoft Azure）及通用 KVM/Hyper-V 底座上的整体解决方案。

---

## 1. 架构目标与部署约束

### 1.1 核心设计指标
* **单盘无感交付**：镜像采用单一磁盘文件组织，不依赖额外的引导盘或云平台自定义固件。
* **零宿主参数侵入**：脱离对底层 Hypervisor 特殊参数的依赖，不要求宿主配置 AppleSMC 虚拟设备或传入 OSK 授权密钥字符串。
* **双模引导自适应**：同一份磁盘镜像自适应 Legacy BIOS（如 SeaBIOS、Hyper-V 第一代）与 UEFI（如 OVMF、Hyper-V 第二代）。
* **全自主图形渲染**：集成基于 Gallium llvmpipe 的软件 Metal 驱动，解除宿主物理 GPU 直通或特定虚拟显示协议的硬性绑定。
* **全生命周期无人值守**：自动化完成开机引导、系统设置跳过、动态账户创建、云元数据获取与远程服务启用。

---

## 2. 引导层架构设计：双模自适应与 OpenDuet

公有云环境实例形态多样，部分旧型机型或默认模板仅提供传统 BIOS 固件，而新型规格则普遍采用 UEFI。为确保单镜像在异构实例间的通用性，引导层采用混合分区与多阶段加载架构。

```
[云虚机固件启动]
       │
       ├─► 传统 BIOS: SeaBIOS 或 Hyper-V 第一代
       │         │
       │         ▼
       │   MBR 扇区 0: boot0
       │         │
       │         ▼
       │   活动 FAT 分区引导扇区: boot1f32
       │         │
       │         ▼
       │   加载根目录 \boot
       │         │
       │         ▼
       │   进入 64 位长模式并在 RAM 中构建 EDK2 UEFI 环境
       │         │
       │         ▼
       └─────────┼─► 原生 UEFI: OVMF 或 Hyper-V 第二代
                 │         │
                 │         ▼
                 └─► 加载 \EFI\OC\OpenCore.efi
                           │
                           ▼
                     [OpenCore 内核补丁与驱动注入]
                           │
                           ▼
                     加载并拉起 macOS XNU 内核
```

### 2.1 分区布局
1. **磁盘前置引导分区**：
   * 格式：FAT32。
   * 大小：建议划分为 200MB 至 512MB。
   * 双重角色：在 Legacy 引导下作为标记为 Active 的启动分区（内置 `boot0`、`boot1f32` 以及 OpenDuet 的二进制内核 `boot`）；在 UEFI 引导下作为标准的 ESP 分区（存放 `\EFI\BOOT\BOOTx64.efi` 与 `\EFI\OC\OpenCore.efi`）。
2. **系统主数据分区**：
   * 格式：APFS 容器。
   * 组织结构：包含 macOS 系统卷、数据卷、Preboot 卷、Recovery 卷与 VM 虚拟内存卷。

### 2.2 NVRAM 持久化策略
* **UEFI 原生环境**：通过 `OpenRuntime.efi` 与硬件固件 NVRAM 直接交互。
* **Legacy BIOS 环境**：由于底层缺失 UEFI 变量存储介质，OpenCore 配合 `OpenVariableRuntimeDxe.efi` 运行，关机时由系统钩子或守护进程将变量快照序列化写入引导分区的 `nvram.plist`，实现跨重启持久化。

---

## 3. 外设与驱动适配矩阵

不同云平台呈现的外设拓扑存在显著差异，下表汇总各硬件子系统的适配方案与就绪状态：

| 平台 / 基础设施 | 子系统 | 虚拟设备规范 | 驱动实现方案 | 适配策略与注意事项 |
| :--- | :--- | :--- | :--- | :--- |
| **通用 KVM / 本机** | 网络 | VirtIO-net: `0x1AF4:0x1000` | `VirtioNet.kext` | 社区成熟驱动，稳定可用 |
| **通用 KVM / 本机** | 存储 | VirtIO-blk: `0x1AF4:0x1001` | `AppleVirtIOStorage.kext` | 系统原生包含，即插即用 |
| **通用 KVM / 本机** | 显卡 | Bochs-display / Standard VGA | `MyVirtualMTLDriver` + llvmpipe | 软件渲染接管 WindowServer 与 Metal |
| **AWS Nitro** | 网络 | ENA: `0x1D0F:0xEC20` | `amazon-ena-ethernet-dext` | AWS 官方提供，具备官方代码签名 |
| **AWS Nitro** | 存储 | Nitro EBS NVMe: `0x1D0F:0x8061` | 原生 `IONVMeFamily.kext` + `NVMeFix.kext` | 原生识别标准 NVMe，轻量补丁增强稳定性 |
| **Google Cloud** | 网络 | gVNIC: `0x1AE0:0x0042` | **暂无驱动** | 创建实例时必须配置为 `VIRTIO_NET` |
| **Google Cloud** | 存储 | VirtIO-SCSI / Local NVMe | 原生 `IONVMeFamily.kext` 或 VirtIO | 原生支持度高 |
| **Azure / Hyper-V** | 网络 | NetVSC: VMBus Synthetic | `HyperVNetwork.kext` 来自 `MacHyperVSupport` | 开源驱动注入，支持千兆与万兆链路 |
| **Azure / Hyper-V** | 存储 | StorVSC: VMBus Synthetic | `HyperVStorage.kext` 来自 `MacHyperVSupport` | 开源驱动注入，映射合成 SCSI 控制器 |
| **通用全平台** | 传感器 | AppleSMC | `VirtualSMC.kext` | 内存劫持应答，解耦宿主仿真要求 |
| **通用全平台** | 处理器 | AMD EPYC / Intel Xeon 多核 | 动态内核补丁 + `CpuTopologyRebuild.kext` | 修复拓扑识别与 TSC 同步漂移 |

---

## 4. 高级存储特性：APFS 卷加密与 FileVault 运行可行性分析

针对虚拟机内启用 APFS 分区加密（FileVault 2）的技术可行性与环境依赖，评估结论如下：

### 4.1 硬件依赖性分析
* **无硬件 T2 或 SEP 依赖**：
  macOS 针对搭载 T2 安全芯片或 Apple Silicon 的机型采用专属硬件密钥分级派生机制。但当系统配置为标准 Intel 传统机型标识（如 `iMac19,1` 或 `MacPro7,1`）时，系统自动降级运行纯软件实现的 FileVault 2 逻辑。
* **密码学指令集**：
  加解密算法采用标准的 AES-XTS-128 或 AES-XTS-256，密钥派生采用 PBKDF2。只要宿主 CPU 透传了标准的 x86 `aes` 指令扩展，加解密开销均在可接受范围内。

### 4.2 虚拟机环境运行的技术门槛
要在虚拟机中稳定使用 APFS 卷加密，必须满足以下运行环境约束：
1. **稳健的 NVRAM 实现**：
   FileVault 在系统启动前期依赖 NVRAM 保存引导参数与密钥派生标志。若虚拟机 NVRAM 无法持久化，重启后将导致预引导器丢失配置。
2. **OpenCore 协议覆盖**：
   `config.plist` 中必须显式配置以下参数：
   * `UEFI -> ProtocolOverrides -> HashServices = true`
   * `UEFI -> ProtocolOverrides -> AppleSmcIo = true`
   * `UEFI -> ProtocolOverrides -> FirmwareVolume = true`
   * `UEFI -> Quirks -> RequestBootVarRouting = true`
3. **输入设备栈支持**：
   解密界面处于内核加载之前的 Preboot 阶段，OpenCore 必须启用 `UEFI -> Input -> KeySupport = true`，否则可能因键盘事件未被捕获而无法输入解密口令。

### 4.3 公有云无人值守冲突与替代最佳实践
* **核心冲突**：
  FileVault 加密系统卷后，系统在拉起操作系统、网络协议栈及 SSH 守护进程之前，必须在 UEFI 图形或控制台界面由人工输入密码解锁容器。在无人工干预的公有云自动化运维场景下，此特性将导致实例启动挂起。
* **推荐解决方案**：
  1. **系统盘采用云厂商底座加密**：
     利用 AWS KMS、GCP 托管密钥或 Azure 磁盘加密直接在物理块存储层实现静态加密。该方式对操作系统透明，不阻断无人值守自动化引导。
  2. **从属数据盘自动解锁**：
     若业务数据卷需使用 APFS 原生加密，可将加密限制在非根目录的数据卷，在系统正常启动并获取云凭据后，通过系统后台任务调用命令行无缝解锁：
     ```bash
     echo "SecretPassphrase" | diskutil apfs unlockVolume <VOLUME_UUID> -stdinpass
     ```

---

## 5. 自动化配置与无人值守全生命周期

为实现云镜像部署后立即可用，系统镜像内预置了一套轻量自启动配置流水线。

```
系统首次启动
   │
   ├─► 1. 规避初始化向导: 跳过 OOBE
   │        touch /var/db/.AppleSetupDone
   │
   ├─► 2. 执行自动化初始脚本: LaunchDaemon com.cloud.init.plist
   │        │
   │        ├─► 从云元数据服务 169.254.169.254 获取实例元数据与 SSH 密钥
   │        │
   │        ├─► 调用 sysadminctl 动态创建运维账户并分配管理员权限
   │        │
   │        ├─► 写入 ~/.ssh/authorized_keys 并纠正访问权限为 0600
   │        │
   │        ├─► 启用远程登录服务 SSH:
   │        │     systemsetup -setremotelogin on
   │        │
   │        └─► 启用屏幕共享与远程桌面 VNC 以及 ARD:
   │              /System/Library/CoreServices/RemoteManagement/ARDAgent.app/Contents/Resources/kickstart \
   │                -activate -configure -access -on -users <username> -privs -all -restart -agent
   │
   └─► 3. 自毁初始化服务并生成初始化标记
```

### 5.1 预置配置脚本模板
自动化服务可封装为 `com.cloud.init.sh`，在根文件系统制作阶段预先写入：

```bash
#!/bin/bash
set -e

FLAG_FILE="/var/db/.cloud_provision_done"
if [ -f "$FLAG_FILE" ]; then
    exit 0
fi

# 1. 声明初始凭据: 支持云元数据动态拉取或环境变量注入
ADMIN_USER="cloudadmin"
ADMIN_PASS="TemporaryBootstrapPass123!"

# 2. 创建管理员用户
if ! id "$ADMIN_USER" &>/dev/null; then
    sysadminctl -addUser "$ADMIN_USER" -password "$ADMIN_PASS" -admin
fi

# 3. 开启 SSH 守护服务
systemsetup -setremotelogin on

# 4. 开启远程桌面 ARD / VNC 监听
/System/Library/CoreServices/RemoteManagement/ARDAgent.app/Contents/Resources/kickstart \
    -activate -configure -access -on \
    -users "$ADMIN_USER" -privs -all \
    -restart -agent -menu

# 5. 防火墙与睡眠策略调整
pmset -a sleep 0 displaysleep 0 disksleep 0
defaults write /Library/Preferences/com.apple.alf globalstate -int 0

# 6. 标记初始化已完成
touch "$FLAG_FILE"
```

---

## 6. 故障隔离与看门狗机制

在没有本地物理控制台的公有云节点中，引导故障可能导致实例完全失联。系统需具备故障自愈与备用通道：

1. **OpenCore 引导计时器与静默启动**：
   * `Misc -> Boot -> ShowPicker = false`
   * `Misc -> Boot -> Timeout = 0`
   * 正常状态下 50 毫秒内跳过引导菜单，直接加载目标分区。
2. **看门狗与引导重试计数器**：
   * 启用 OpenCore 的 Boot Watchdog 机制。
   * 若系统连续多次启动未成功进入 macOS 用户空间，引导器自动回退并加载同盘预置的独立救援镜像（Rescue OS），开放基础 SSH 与磁盘修复网络服务。
3. **串口控制台调试**：
   * 在 OpenCore 内核引导参数中追加 `debug=0x100 serial=3 console=3`，将内核启动阶段的 panic 堆栈及诊断日志实时镜像至虚拟串口，便于通过各云厂商的串口控制台（Serial Console）回溯排障。
