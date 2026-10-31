# 废弃内容

本目录中的内容全部停用。

它们只用于历史审计和失败原因对照。

## 内容

| 路径 | 状态 | 原因 |
|---|---|---|
| `MyVirtualMTLDriver/` | 已弃用 | 手写 AIR、Gallium 和动态 Objective-C 路线不成立 |
| `PROJECT_SPEC.legacy.md` | 已弃用 | 错误声明 Phase 0 到 3 完成 |
| `CLOUD_DEPLOYMENT_SPEC.legacy.md` | 已弃用 | 含宿主假设、固定密码和关闭防火墙样例 |

## 禁止用途

不得：

- 继续补丁式开发旧原型。
- 把旧测试当成像素证据。
- 执行旧部署脚本。
- 复制固定密码。
- 关闭系统防火墙。
- 把旧规格作为当前计划。

## 当前替代

- 总规格：[../PROJECT_SPEC.md](../PROJECT_SPEC.md)
- 云约束：[../CLOUD_DEPLOYMENT_SPEC.md](../CLOUD_DEPLOYMENT_SPEC.md)
- Metal 合同：[../analysis/macos26-guest-metal-driver-spec.md](../analysis/macos26-guest-metal-driver-spec.md)
- 上游接入：[../docs/METAL2VULKAN_INTEGRATION.md](../docs/METAL2VULKAN_INTEGRATION.md)

归档是可逆移动。

原始内容未删除。
