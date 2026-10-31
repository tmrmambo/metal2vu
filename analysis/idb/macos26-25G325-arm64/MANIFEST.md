# macOS 26.7.2 IOGPU IDA 数据库

- Build：`25G325`
- 架构：`arm64`
- 保存日期：`2026-10-29`
- 分析方式：IDA MCP 串行分析 scratch 副本
- 主报告：`../../macos26-iogpu-display-registration.md`

## 已分析数据库

| 文件 | 大小 | SHA-256 | 来源 |
|---|---:|---|---|
| `AppleParavirtGPUIOGPUFamily-existing-analysis.i64` | 3,908,736 | `5ED11D98EAE2D65334C1178FDE5B2AC6A77CC1629F5D249A3751E45D78452E48` | 项目既有 IDB 的 scratch 分析副本 |
| `AppleParavirtGPUIOGPUFamily-raw-reanalysis.i64` | 2,867,884 | `718B484E53E3105E3AE188A7ECBB0EB0BEB174C66E49D74063399D27014E932A` | AppleParavirtGPUIOGPUFamily Mach-O 的新分析 |
| `IOGPUFamily.i64` | 6,791,023 | `8D580779C8087DBF649DE5180489D1D24FBD8368B7C4B48C165948F6FBA5CBBF` | IOGPUFamily Mach-O 的新分析 |
| `AppleParavirtIOSurface.i64` | 1,651,627 | `68F3C996A9DFEF3011D8DCD778A8BE1409663ED67F3431FF0DF49346CF99CB2D` | AppleParavirtIOSurface Mach-O 的新分析 |
| `ida-evidence.md` | 57,728 | `4992A34F63C08BA78C21F984CA6890D943621849F098C95FF264DB880B641413` | IDA 地址、调用和结构证据 |

## 原始输入

| 输入 | 大小 | SHA-256 |
|---|---:|---|
| `com.apple.driver.AppleParavirtGPUIOGPUFamily.i64` | 2,834,133 | `DE3F059B18F987BA890F341DA6E63763FCC7D871ECFFF9A5BE6F44A9040B4FDA` |
| `com.apple.driver.AppleParavirtGPUIOGPUFamily` | 405,616 | `9AD1175C60D53B60DF9D6B4836AC4050D3896B5AD6F8BBEC8F022A5485685EF5` |
| `com.apple.iokit.IOGPUFamily` | 670,728 | `1D290CA65F62E1811B7832B95FE55ABD4F8D1891F64DB38026F590DEEDFE521C` |
| `com.apple.iokit.AppleParavirtIOSurface` | 141,088 | `AF3AEB0F358F0B3C14ABED17F29588D6DECDF977C72068EBAD0A56C9263FF0D3` |

## 复用规则

1. 从这里复制目标 `.i64` 到当前 scratch。
2. 只打开 scratch 副本。
3. IDA 会沿用已有分析结果。
4. 有用的新分析应保存为新快照。
5. 不直接覆盖这里的参考快照。
