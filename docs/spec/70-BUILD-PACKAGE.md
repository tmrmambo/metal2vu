# 70 工具链、构建、镜像与安装布局

文档版本：1.0
基线日期：2026-10-30
对应组件：组件清单第 5 项（Vulkan loader 与 Lavapipe 的 macOS x86_64 构建打包），并覆盖全部组件的构建与安装
上级文档：`docs/spec/00-OVERVIEW.md`
配套分册：`docs/spec/80-TEST-HARNESS.md`

## 0. 本文作用与写作约束

本文回答四个问题：

1. 每个组件要什么工具链，哪些能在非 macOS 机器上做，哪些必须在 macOS 上做。
2. 给定当前开发机是 Windows，现实的构建机方案是什么。
3. Mesa Lavapipe 与 Vulkan loader 在 macOS x86_64 上怎么建、产出什么、怎么保证运行时只用随包的那一份。
4. SIP/AMFI 怎么关、怎么在镜像构建期固化、怎么在 guest 内验证。

目标基线：macOS Tahoe 26.7.2，build 25G325，**x86_64**（00-OVERVIEW 第 2.3 节）。

写作约束同 80 分册：每条结论带证据标签与来源 URL；命令按可直接照抄编写；对外部网页内容均为转述，不作连续摘录。**内容已转述以符合许可限制。**

---

## 1. 工具链总表

### 1.1 按组件

| # | 组件 | 语言 | 必需工具 | 能否在非 macOS 上构建 |
|---|---|---|---|---|
| 1 | Metal plugin bundle（ObjC 对象族） | Objective-C | Apple clang、macOS SDK、`Metal.framework` / `IOSurface.framework` / `IOKit.framework` 头与 tbd、`ibtool` 不需要 | **否**。依赖 Apple SDK 与私有基类 `MTLIOAccelDevice` 的链接期符号 |
| 2 | kext：accelerator service 与 user client | C++（freestanding） | Apple clang、**Kernel.framework**（随 Xcode）、`kmutil`、代码签名工具链 | **否**。`Kernel.framework` 不随任何可再分发 SDK 提供 |
| 3 | kext：display provider | C++ | 同上 | **否** |
| 4 | IOSurface 用户态桥 | Rust + C shim | `cargo`、`x86_64-apple-darwin` target、Apple clang（bindgen / C shim）、macOS SDK | **理论可以，实际否**。见 1.3 |
| 5 | Vulkan loader + Mesa Lavapipe | 上游 C/C++ | meson、ninja、cmake、Apple clang、LLVM（含 `llvm-config`）、bison、flex、Python 3 + mako、SPIRV-Tools、zstd | **否**。Mesa 的 darwin 代码路径与 dylib 链接只在 macOS 上成立 |
| 6 | 进程模型与恢复（helper） | Rust | `cargo`、`x86_64-apple-darwin` target | 同 #4 |
| — | AIR → SPIR-V、Metal 语义映射（metal2vulkan） | Rust | `cargo` | **是**，纯 Rust 部分可在 Windows 上 `cargo check` / 跑单测 |
| 7 | 自动化测试管线（harness） | Rust | `cargo`，目标为宿主平台 | **是**，harness 跑在 host 上，不在 guest 里 |

### 1.2 关键结论：macOS 构建机是硬需求

组件 1、2、3、5 全部必须在 macOS 上构建，而它们正是项目的全部交付面。

两条独立的原因，任一条就足够：

- **技术**：`Kernel.framework`（kext 必需）与 Metal 的私有基类符号只在 Xcode 内，不随任何可重分发 SDK 提供。Mesa 的 darwin 路径依赖 Apple clang 的 Mach-O 链接行为与 `install_name_tool` 系列工具。
- **许可**：Apple SDK 的使用条款限制在 Apple 硬件上运行相关软件。osxcross 这类工具需要使用者自备打包好的 macOS SDK，它把宿主编译器、SDK、Darwin 版二进制工具与编译器包装器组合成交叉工具链（转述自 <https://github.com/tpoechtrager/osxcross/blob/master/README.md>）——即它绕过的是技术障碍，不是许可障碍。**本项目不采用交叉编译路径。**

社区对"Linux 上编译 macOS 目标"的通行评估也指向同一结论：难点在 SDK 与链接器行为，并且产出的二进制无法在非 Darwin 内核上测试（转述自 <https://dev.to/farzon/the-warf-way-part-ii-tackling-the-macos-frontier-with-osx-cross-and-darling-15j0>）。对一个要写 kext 的项目，"编出来但没法测"没有价值。

`KNOWN`。

### 1.3 Rust 侧的交叉编译：能编不能用

`rustup target add x86_64-apple-darwin` 在 Windows 上会成功，`cargo build --target x86_64-apple-darwin` 会在链接阶段失败——需要 Apple 的链接器与 SDK。

即使用 `zig cc` 或 osxcross 补上链接器，仍有两个问题：

1. 组件 4、6 要链 `IOSurface`、`CoreFoundation`、`IOKit`，这些 framework 的 tbd 来自 SDK。
2. 组件 4 的 C shim 要包含 `<IOSurface/IOSurfaceRef.h>`。

结论：**Rust 代码在 Windows 上做 `cargo check`、`cargo clippy`、`cargo test`（纯逻辑部分）是有价值的日常循环；产出交付物必须在 macOS 构建机上。** `INFERRED`，但风险极低。

### 1.4 当前开发机现状

| 已有 | 版本 |
|---|---|
| `py`（Python launcher） | 3.14 |
| `cargo` | 1.99.1 |
| `rustup` | 已装 |

| 缺失 | 影响 |
|---|---|
| clang | 无法编译任何 C/C++/ObjC |
| cmake | 无法建 Vulkan loader |
| meson / ninja | 无法建 Mesa |
| xcodebuild / Xcode CLT | 无法建 kext 与 bundle |

Windows 开发机能做的事，完整清单：

- metal2vulkan / runtime 的 Rust 逻辑开发与单测。
- harness 的开发与运行（它跑在 host 上，目标三元组就是 Windows，见 80 分册 2.2）。
- 文档、IDA 静态分析（仓库里已有 `.i64`）。
- 远程驱动构建机与实验机。

Windows 开发机**不能**做的事：任何交付物的构建。

---

## 2. 构建机方案

### 2.1 一个常被搞错的前提：不需要 Intel Mac

Apple 的 clang 是交叉编译器，在 Apple Silicon 上用 `-arch x86_64` 或 `--target=x86_64-apple-macos26` 即可产出 x86_64 Mach-O。所以 **Apple Silicon Mac 可以构建 x86_64 交付物**。

但有两个真实的卡点：

1. **Homebrew 依赖必须是 x86_64 切片。** Mesa 要链 LLVM、zstd、SPIRV-Tools；Apple Silicon 上的 `/opt/homebrew` 只装 arm64 切片，无法链进 x86_64 产物。解法是并行安装两套 Homebrew：arm64 在 `/opt/homebrew`，x86_64 在 `/usr/local`，后者通过 Rosetta 2 运行。这是 Homebrew 在 Apple Silicon 上的既定布局，两个前缀是硬编码的、不可互换（转述自 <https://stackoverflow.com/a/65760032> 与 <https://gist.github.com/ahgraber/79a802544e79c2f80ae0dd2744b58cc5>）。**不要让 arm64 shell 用 `/usr/local`，也不要让 x86_64 shell 用 `/opt/homebrew`**（转述自 <https://blog.rottenwifi.com/how-to-run-homebrew-and-x86_64-terminal-apps-on-an-m1-mac/>）。
2. **KDK（Kernel Debug Kit）的 x86_64 可用性。** kext 链接需要 `Kernel.framework`；`kmutil create` 自 macOS 13 起创建 boot/system collection 需要对应版本的 KDK，而 Apple 并不为所有 macOS 版本提供 KDK（转述自 <https://gist.github.com/steven-michaud/16cff5628850799e428a2f2c56029677>）。本项目只需 **auxiliary** collection（见第 4 节），`INFERRED` 不需要 KDK；但这一点必须实测确认。

### 2.2 三个方案

| 方案 | 形态 | 成本 | 优点 | 缺点 |
|---|---|---|---|---|
| **A** | GitHub Actions 的 `macos-15-intel` 运行器 | 免费额度内 / 按分钟 | 零硬件、原生 x86_64、Homebrew 单前缀即可、可复现 | 单次最长运行时长有限；Mesa+LLVM 首次构建慢；无法交互调试 |
| **B** | 一台 Apple Silicon Mac（mini 即可）+ 双 Homebrew | 一次性硬件 | 可交互、可本地跑 `kmutil`、可随时试 | 需要双前缀、需要 Rosetta、x86_64 侧工具链偶有缺包 |
| **C** | 在实验 guest 内自建（macOS 26 x86_64 虚机本身当构建机） | 复用现有 | 构建与目标**同架构同版本**，`Kernel.framework` 与 KDK 天然匹配 | 鸡生蛋：guest 还没跑起来（80 分册 4.1 的 E0）；SIP 关闭的机器不适合当构建机 |

**推荐组合：A 为主，B 为辅，C 不用。**

理由：

- A 的 `macos-15-intel` 标签明确存在，GitHub 的公告说明它用于需要 x86_64 环境的用户迁移，并会提供到 2027 年 8 月（转述自 <https://github.com/actions/runner-images/issues/13045> 与 <https://github.blog/changelog/2025-09-19-github-actions-macos-13-runner-image-is-closing-down/>）。本项目的基线是 Intel 平台的最后一个 macOS 版本（00-OVERVIEW 第 2.3 节），时间窗完全覆盖。runner-images 仓库也已有加入 macOS 26 Intel 镜像的动作（<https://github.com/actions/runner-images/actions/runs/21746582828>），若上线则进一步对齐基线。
- 组件 5（Mesa + LLVM）是构建里最重最少变的部分。它应该被做成**独立的、带缓存的 CI 产物**，而不是每次构建主项目都重编一遍。A 的缓存机制适合这件事。
- B 的价值在 `kmutil` 与 `ioreg` 的交互式排查，以及 CI 不好做的签名/公证实验。**但它不是 CI 的替代**，手工机器上的构建不可复现。
- C 在 E0 通过之后可以作为"验证构建机与目标一致性"的对照，但不作为常规路径：SIP 关闭、随时被 restore 覆盖的机器不适合存放工具链。

**时效性提示**：x86_64 macOS 的 CI 支持有明确的落日（2027 年 8 月）。因此第 7 节的版本清单必须包含**完整的依赖源码与二进制归档**，使得 CI 消失后仍可离线重建。这不是过度设计——Apple 已停止生产 Intel Mac、macOS 26 是 Intel 的最终版本（转述自 <https://github.com/atuinsh/atuin/issues/3053>），上游会持续退场。

### 2.3 构建机 bootstrap 脚本

#### 方案 A：GitHub Actions

```yaml
# .github/workflows/build-macos-x86_64.yml
name: build-macos-x86_64
on: [push, workflow_dispatch]

jobs:
  build:
    runs-on: macos-15-intel          # x86_64 原生
    steps:
      - uses: actions/checkout@v4
        with: { submodules: recursive }

      - name: Xcode command line tools
        run: xcode-select -p && clang --version && xcodebuild -version

      - name: Homebrew deps
        run: |
          brew update
          brew install meson ninja cmake llvm bison flex \
                       spirv-tools glslang zstd pkg-config

      - name: Python deps
        run: |
          python3 -m venv .venv
          . .venv/bin/activate
          pip install mako packaging pyyaml

      - name: Rust toolchain
        run: |
          rustup target add x86_64-apple-darwin
          rustc -vV

      - name: Cache third-party (mesa + loader)
        id: tpcache
        uses: actions/cache@v4
        with:
          path: third_party/_install
          key: tp-${{ runner.os }}-x86_64-${{ hashFiles('third_party/versions.lock') }}

      - name: Build third-party
        if: steps.tpcache.outputs.cache-hit != 'true'
        run: ./scripts/build-third-party.sh

      - name: Build project
        run: ./scripts/build-all.sh --release --arch x86_64

      - name: Package
        run: ./scripts/package.sh --out dist/

      - uses: actions/upload-artifact@v4
        with:
          name: metal2vu-macos-x86_64
          path: dist/
```

`third_party/versions.lock` 是第 7 节的版本清单。缓存键挂在它上面，所以上游版本不动就不重编 LLVM/Mesa。

#### 方案 B：Apple Silicon Mac 的双前缀 bootstrap

```bash
#!/usr/bin/env bash
# scripts/bootstrap-builder-applesilicon.sh
set -euo pipefail

# 1. Rosetta 2（x86_64 Homebrew 的前提）
softwareupdate --install-rosetta --agree-to-license

# 2. x86_64 Homebrew 装到 /usr/local（硬编码前缀，不可改）
if [ ! -x /usr/local/bin/brew ]; then
  arch -x86_64 /bin/bash -c \
    "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
fi

# 3. 所有 x86_64 依赖都要走 arch -x86_64 + /usr/local/bin/brew
X86BREW="arch -x86_64 /usr/local/bin/brew"
$X86BREW update
$X86BREW install meson ninja cmake llvm bison flex spirv-tools glslang zstd pkg-config

# 4. 验证切片正确。任何一个是 arm64 都会在链接 x86_64 产物时失败
for f in /usr/local/opt/llvm/lib/libLLVM.dylib \
         /usr/local/opt/zstd/lib/libzstd.dylib; do
  echo "== $f"; lipo -info "$f" || file "$f"
done

# 5. Rust
rustup target add x86_64-apple-darwin
```

**第 4 步不可省。** 把一个 arm64 的 `libLLVM.dylib` 喂给 x86_64 的 Mesa 构建，报错信息会指向符号未定义而不是架构不符，排查会浪费大量时间。

#### 两个方案共用的环境约定

```bash
# x86_64 构建时的环境（Apple Silicon 上额外需要 arch -x86_64 包裹）
export HOMEBREW_PREFIX=/usr/local          # 方案 A 上原生即为此值
export PATH="$HOMEBREW_PREFIX/opt/llvm/bin:$HOMEBREW_PREFIX/opt/bison/bin:$HOMEBREW_PREFIX/opt/flex/bin:$PATH"
export PKG_CONFIG_PATH="$HOMEBREW_PREFIX/lib/pkgconfig:$HOMEBREW_PREFIX/share/pkgconfig"
export LIBRARY_PATH="$HOMEBREW_PREFIX/lib:${LIBRARY_PATH:-}"
export MACOSX_DEPLOYMENT_TARGET=26.0
export SDKROOT="$(xcrun --sdk macosx --show-sdk-path)"
```

`MACOSX_DEPLOYMENT_TARGET=26.0` 把部署目标钉在基线。设得更低会让链接器接受在 26 上已变化的符号，产生在目标上行为不明的二进制。

---

## 3. 各组件构建

### 3.1 Rust 核心（组件 4、6，以及 metal2vulkan）

workspace 布局（00-OVERVIEW 第 4.6 节要求吸收 metal2vulkan 为独立 crate 并保留 git 历史）：

```text
Cargo.toml                      # workspace
crates/
  metal2vulkan/                 # subtree，保留上游历史
  metal2vulkan-runtime/         # subtree
  m2v-iosurface/                # 组件 4：IOSurface 桥（Rust + C shim）
  m2v-core/                     # 窄 C ABI，被 ObjC bundle dlopen/链接
  m2v-helper/                   # 组件 6：helper 进程
  harness/                      # 组件 7，目标为 host 平台
third_party/
  mesa/                         # submodule，固定 commit
  Vulkan-Loader/                # submodule，固定 tag
  Vulkan-Headers/               # submodule，固定 tag
  versions.lock
```

`m2v-core` 产出 `cdylib` 与 `staticlib`：

```toml
# crates/m2v-core/Cargo.toml
[lib]
name = "m2v_core"
crate-type = ["staticlib", "cdylib"]
```

构建：

```bash
cargo build --release --target x86_64-apple-darwin \
            -p m2v-core -p m2v-iosurface -p m2v-helper
# 产物
#   target/x86_64-apple-darwin/release/libm2v_core.a
#   target/x86_64-apple-darwin/release/libm2v_core.dylib
#   target/x86_64-apple-darwin/release/m2v-helper
```

**静态库还是动态库**：第一版 ObjC bundle 与 Rust 核心同进程（00-OVERVIEW 第 6 节），因此**链静态库**，把 Rust 核心直接埋进 bundle 的可执行里。理由是减少一个运行时查找环节——bundle 由 Metal.framework 加载，其 `@rpath` 行为还未确证，少一个 dylib 少一类失败模式。`cdylib` 保留给 helper 进程拆分之后。

C 头由 `cbindgen` 生成并纳入版本控制（而非构建时生成），这样 ObjC 侧的编译不依赖 Rust 工具链：

```bash
cbindgen --config crates/m2v-core/cbindgen.toml \
         --crate m2v-core \
         --output include/m2v_core.h
```

`INFERRED`：`cbindgen` 的配置细节与 ABI 稳定性规则属 `50-IPC-HELPER.md` 范围，本文只规定产物形态。

### 3.2 Metal plugin bundle（组件 1）

形态：`.bundle`，principal class 为继承 `MTLIOAccelDevice` 的 Device 类。

**命名修正**：00-OVERVIEW 第 4.4 节把基类写作 `_MTLIOAccelDevice`，这是笔误。实际类名是 **`MTLIOAccelDevice`**，无前导下划线；带下划线的 `_MTLDevice` 是它的父类，两者是不同的类。来源：`20-OBJC-DEVICE.md` 第 0.1 节，依据 `Metal` 样本的 `__objc_classlist` 全量遍历，`KNOWN`。本文沿用该修正。

```bash
# scripts/build-bundle.sh（节选）
BUNDLE="build/Metal2Vu.bundle"
mkdir -p "$BUNDLE/Contents/MacOS" "$BUNDLE/Contents/Resources"

clang -arch x86_64 \
      -isysroot "$SDKROOT" \
      -mmacosx-version-min=26.0 \
      -fobjc-arc -fmodules -O2 -g \
      -Iinclude \
      -framework Foundation \
      -framework IOKit \
      -framework IOSurface \
      -framework CoreGraphics \
      -framework Metal \
      -bundle \
      -o "$BUNDLE/Contents/MacOS/Metal2Vu" \
      src/objc/*.m \
      target/x86_64-apple-darwin/release/libm2v_core.a

plutil -convert binary1 -o "$BUNDLE/Contents/Info.plist" src/objc/Info.plist
```

`Info.plist` 必须声明的键（`INFERRED`，依据 00-OVERVIEW 第 4.1 节表中 `MetalPluginClassName` 的既有用法，确切键集由 `20-OBJC-DEVICE.md` 负责确证）：

| 键 | 值 |
|---|---|
| `CFBundleIdentifier` | `net.metal2vu.Metal2Vu` |
| `CFBundleExecutable` | `Metal2Vu` |
| `CFBundlePackageType` | `BNDL` |
| `MetalPluginClassName` | 本项目 Device 类名。**可省**——`20-OBJC-DEVICE.md` 第 3 节确证：该属性缺失或类型不对时，Metal 退回 `[bundle principalClass]`。`KNOWN` |
| `LSMinimumSystemVersion` | `26.0` |

注意 `MetalPluginName` **不在 bundle 的 `Info.plist` 里**，它是 kext 发布到 IORegistry 的属性。Metal 的查找顺序是：读 IORegistry 的 `MetalPluginName` → `gpu_bundle_find_trusted(name, …)` 解析出 bundle 路径 → `NSBundle` 加载 → 取类 → 校验是否为 `_MTLDevice` 子类（`KNOWN`，来源 `20-OBJC-DEVICE.md` 第 3 节）。因此 bundle 的文件名/路径与 kext 属性值的对应关系由那个 trust gate 函数决定，不由本文的安装布局单方面决定。

**类继承的链接方式**：基类 `MTLIOAccelDevice` 没有公开头，做法是自己写一个 `@interface MTLIOAccelDevice : NSObject` 的前向声明，让 ObjC 类符号 `_OBJC_CLASS_$_MTLIOAccelDevice` 在链接 `-framework Metal` 时解析。

`KNOWN`：该类在 `Metal` 样本中可被外部引用——`20-OBJC-DEVICE.md` 第 4.3 节记录 AMD 驱动导入了 `_OBJC_IVAR_$_MTLIOAccelDevice._deviceRef`，说明相关符号确实对外可见。

`INFERRED`：类符号本身的确切链接参数（是否需要 `-undefined dynamic_lookup`、还是直接由 `-framework Metal` 满足）未实测。另有一条来自 `20-OBJC-DEVICE.md` 第 4.3 节的**硬性实现约束**：子类不得假定 `MTLIOAccelDevice` 的 `instanceSize`，它超过 54 KB 且跨版本变化；访问基类成员须经 `_OBJC_IVAR_$_` 符号或 `-deviceRef` / `-sharedRef` getter。这一点影响 ObjC 源码写法，不影响本文的构建参数。

### 3.3 C++ kext（组件 2、3）

kext 不能用 `clang` 直接编，要用 Xcode 的 IOKit 模板所依赖的一组特定参数。最省事且可复现的做法是保留一个最小的 `.xcodeproj` 并用 `xcodebuild`：

```bash
xcodebuild -project kext/Metal2VuAccel.xcodeproj \
           -scheme Metal2VuAccel \
           -configuration Release \
           -arch x86_64 \
           MACOSX_DEPLOYMENT_TARGET=26.0 \
           CONFIGURATION_BUILD_DIR="$PWD/build/kext" \
           CODE_SIGN_IDENTITY="-" \
           CODE_SIGNING_REQUIRED=YES \
           CODE_SIGNING_ALLOWED=YES \
           build
```

`CODE_SIGN_IDENTITY="-"` 是 ad-hoc 签名。研发期 SIP 关闭下 ad-hoc 足够（见第 5 节），但**不能完全不签**：`kmutil` 对无签名 bundle 的处理路径与 ad-hoc 不同，不签会多引入一类失败。

不用 `xcodebuild` 的等价手写编译（供 CI 上无 `.xcodeproj` 时参考，`INFERRED`，需实测）：

```bash
KERNEL_FW="$SDKROOT/System/Library/Frameworks/Kernel.framework"
clang++ -arch x86_64 \
  -isysroot "$SDKROOT" \
  -mkernel -fapple-kext \
  -nostdinc -nostdinc++ \
  -I"$KERNEL_FW/Headers" \
  -I"$KERNEL_FW/PrivateHeaders" \
  -fno-builtin -fno-exceptions -fno-rtti -fno-common \
  -fno-stack-protector -fno-stack-check \
  -msoft-float -mno-red-zone \
  -DKERNEL -DKERNEL_PRIVATE -DDRIVER_PRIVATE -DAPPLE -DNeXT \
  -std=gnu++17 -O2 -g \
  -c src/kext/*.cpp -o build/obj/

clang++ -arch x86_64 -isysroot "$SDKROOT" \
  -nostdlib -Xlinker -kext -lkmod -lcc_kext \
  -Xlinker -export_dynamic \
  -o build/kext/Metal2VuAccel.kext/Contents/MacOS/Metal2VuAccel \
  build/obj/*.o
```

kext 的 `Info.plist` 必须声明 `OSBundleLibraries` 中的依赖家族。按 00-OVERVIEW 第 4.1 节的 x86 路径，参照 `AppleParavirtGPU.kext` 的依赖集：

```xml
<key>OSBundleLibraries</key>
<dict>
  <key>com.apple.kpi.iokit</key>        <string>26.0</string>
  <key>com.apple.kpi.libkern</key>      <string>26.0</string>
  <key>com.apple.kpi.mach</key>         <string>26.0</string>
  <key>com.apple.kpi.bsd</key>          <string>26.0</string>
  <key>com.apple.iokit.IOAcceleratorFamily2</key> <string>1.0</string>
  <key>com.apple.iokit.IOGraphicsFamily</key>     <string>1.0</string>
  <key>com.apple.iokit.IOPCIFamily</key>          <string>1.0</string>
  <key>com.apple.iokit.IOSurface</key>            <string>1.0</string>
</dict>
```

`INFERRED`：确切的版本字符串与是否需要 `AppleGraphicsDeviceControl` 由 `10-KERNEL-ACCELERATOR.md` 与 `11-KERNEL-DISPLAY.md` 确证。**版本号写错会导致 `kmutil` 以"依赖未满足"拒绝链接，而错误信息不会直接指出是哪一项**——诊断方法见 4.4。

### 3.4 Mesa Lavapipe 与 Vulkan loader 的 macOS x86_64 构建

这是组件 5，**从未验证过**，也是本文最长的一节。

#### 3.4.1 Mesa 对 macOS 的支持现状

`KNOWN`，三条，均来自 Mesa 官方文档：

1. **Mesa 在 macOS 上可以不打补丁直接构建**，但有若干注意事项；多数构建期依赖可从 Homebrew 获得，Mako（Python 模板库）需用 pip 安装；macOS 对构建环境挑剔，文档建议先进 `brew sh` 以便 Homebrew 依赖进入 PATH（转述自 <https://docs.mesa3d.org/macos.html>）。
2. **Gallium 驱动可通过 `-Dgallium-drivers=` 在 macOS 上启用**；软件渲染器应以 `llvmpipe` 的形式加入驱动列表，而不是用旧的软件光栅化器选项；只有软件渲染器和转发到其它 API 的驱动能工作，Linux 的硬件驱动不行（转述自同一页）。
3. **Meson 构建在 macOS 上有测试覆盖**（转述自 <https://docs.mesa3d.org/meson.html>）。

Lavapipe 本身的要求（`KNOWN`，来源 <https://docs.mesa3d.org/drivers/llvmpipe.html>）：

- x86/amd64 上推荐 64 位模式；SSE2 强烈建议；SSE3 与 SSE4.1 能产生更高效的代码。
- 它用 LLVM 做运行时代码生成，着色器与光栅化都走 LLVM IR 再翻译成机器码；多线程，可利用多核。

LLVM 版本门槛，`KNOWN`，来源是 Mesa 的 `meson.build`（<https://gitlab.freedesktop.org/mesa/mesa/-/blob/main/meson.build>）：

- 当启用 `clc` 或使用 **ORCJIT** 时，`_llvm_version = '>= 15.0.0'`。
- 否则（x86_64 默认走 MCJIT）为 `>= 8.0.0`。
- `llvm_has_mcjit` 的架构白名单包含 `x86_64`，所以 x86_64 默认可用 MCJIT；但 Mesa 注释明确 MCJIT 在 LLVM 中已废弃、不再接受新架构移植。
- **在 darwin 上 Mesa 会额外链接 `all-targets`**，注释给的理由是 Apple 系统经常交叉编译并产出多架构胖二进制，因此 JIT 初始化所有 target 而不只是本机 target。这直接意味着 **macOS 上的 Lavapipe 比 Linux 上更大**，因为它要带全部 LLVM 后端。
- **RTTI 必须与 LLVM 一致**：LLVM 以无 RTTI 构建时 Mesa 也必须禁 RTTI，反之同理，不一致会在配置阶段直接报错。
- 启用 SPIRV-Tools 时要求 `>= 2024.1`。

**决策**：用 Homebrew 的 `llvm`（当前为 19 以上），走 ORCJIT（`-Dllvm-orcjit=true`），从而落在 `>= 15.0.0` 这一支，避开已废弃的 MCJIT。`INFERRED`：ORCJIT 在 macOS x86_64 上的实际稳定性未验证，若出问题则退回 MCJIT 并在版本清单中记录。

#### 3.4.2 已有的成功先例

`KNOWN`：存在一个公开的 **macOS arm64** Lavapipe 构建仓库，产出 `libvulkan_lvp.dylib` 与 ICD 清单 `lvp_icd.aarch64.json`，并说明 ICD 清单通过相对路径引用驱动、因此解包目录可任意移动；同时说明 `llvm`、`zstd`、`spirv-tools` 等运行时依赖需另行安装（转述自 <https://github.com/rerun-io/lavapipe-build>）。

它的构建脚本（<https://github.com/rerun-io/lavapipe-build/blob/main/build.sh>）给出的关键做法，全部可直接借用：

- Homebrew 装 `meson ninja llvm bison flex glslang spirv-tools vulkan-loader vulkan-headers zstd`。
- Python venv 装 `mako packaging pyyaml`。
- 用 meson 的 `--native-file` 显式指定 `bison` 与 `llvm-config` 的路径，避免拿到系统自带的旧 bison。
- 配置项：`--prefer-static`、`-Dgallium-drivers=llvmpipe`、`-Dvulkan-drivers=swrast`、`-Dllvm=enabled`、`-Dshared-llvm=disabled`、`-Dplatforms=`（空）、`-Dglx=disabled`、`-Dgbm=disabled`、`-Dgallium-va=disabled`、`-Dopengl=false`、`-Dgles1=disabled`、`-Dgles2=disabled`、`-Degl=disabled`。
- 安装后把 ICD JSON 的 `library_path` 改写成 `./libvulkan_lvp.dylib`（相对路径）。
- 用 `otool -L` 找出所有指向 Homebrew 前缀的动态依赖，逐个拷进交付目录并用 `install_name_tool -change` 改写成 `@loader_path/<名字>`。
- 最后再跑一次 `otool -L`，**若仍有 Homebrew 路径就直接失败退出**。

**最后一条是整个打包里最重要的一步。** 一个仍引用 `/opt/homebrew/...` 或 `/usr/local/...` 的 dylib 在目标 guest 上必然加载失败，而失败信息是 `image not found`，不会告诉你是哪一层的哪个依赖。把它做成构建期的硬检查，而不是运行期的惊喜。

注意 `-Dvulkan-drivers=swrast` 才是 Lavapipe，不是 `lavapipe`。驱动在 Mesa 里的内部名是 `swrast`。

#### 3.4.3 本项目的 x86_64 构建脚本

```bash
#!/usr/bin/env bash
# scripts/build-third-party.sh
# 在 macOS x86_64 构建机上运行（方案 A 原生；方案 B 需 arch -x86_64 包裹整个脚本）
set -euo pipefail

TP="$PWD/third_party"
INSTALL="$TP/_install"
: "${HOMEBREW_PREFIX:=/usr/local}"
: "${MACOSX_DEPLOYMENT_TARGET:=26.0}"
export MACOSX_DEPLOYMENT_TARGET

export PATH="$HOMEBREW_PREFIX/opt/llvm/bin:$HOMEBREW_PREFIX/opt/bison/bin:$HOMEBREW_PREFIX/opt/flex/bin:$PATH"
export LIBRARY_PATH="$HOMEBREW_PREFIX/lib:${LIBRARY_PATH:-}"
export PKG_CONFIG_PATH="$HOMEBREW_PREFIX/lib/pkgconfig:$HOMEBREW_PREFIX/share/pkgconfig"

rm -rf "$INSTALL"; mkdir -p "$INSTALL"

# ---------- 0. Python 构建期依赖 ----------
python3 -m venv "$TP/_venv"
# shellcheck disable=SC1091
source "$TP/_venv/bin/activate"
pip install --quiet mako packaging pyyaml

# ---------- 1. Vulkan-Headers ----------
cmake -S "$TP/Vulkan-Headers" -B "$TP/_b/headers" \
      -D CMAKE_BUILD_TYPE=Release \
      -D CMAKE_INSTALL_PREFIX="$INSTALL" \
      -D CMAKE_OSX_ARCHITECTURES=x86_64 \
      -D CMAKE_OSX_DEPLOYMENT_TARGET="$MACOSX_DEPLOYMENT_TARGET"
cmake --build "$TP/_b/headers" --target install

# ---------- 2. Vulkan-Loader ----------
# 官方要求：C99 编译器、CMake >= 3.22.1、Git；必须给出 Vulkan-Headers 安装目录
cmake -S "$TP/Vulkan-Loader" -B "$TP/_b/loader" \
      -D CMAKE_BUILD_TYPE=Release \
      -D CMAKE_INSTALL_PREFIX="$INSTALL" \
      -D VULKAN_HEADERS_INSTALL_DIR="$INSTALL" \
      -D CMAKE_OSX_ARCHITECTURES=x86_64 \
      -D CMAKE_OSX_DEPLOYMENT_TARGET="$MACOSX_DEPLOYMENT_TARGET" \
      -D BUILD_TESTS=OFF \
      -D LOADER_USE_UNSAFE_FILE_SEARCH=OFF
cmake --build "$TP/_b/loader" --target install -- -j"$(sysctl -n hw.ncpu)"
# 产物：$INSTALL/lib/libvulkan.1.dylib（+ libvulkan.dylib 符号链接）

# ---------- 3. Mesa Lavapipe ----------
cat > "$TP/mesa/native-x86_64.ini" <<INI
[binaries]
bison = '$HOMEBREW_PREFIX/opt/bison/bin/bison'
flex  = '$HOMEBREW_PREFIX/opt/flex/bin/flex'
llvm-config = '$HOMEBREW_PREFIX/opt/llvm/bin/llvm-config'
INI

meson setup "$TP/_b/mesa" "$TP/mesa" \
      --native-file "$TP/mesa/native-x86_64.ini" \
      --prefer-static \
      -Dprefix="$INSTALL" \
      -Dbuildtype=release \
      -Dgallium-drivers=llvmpipe \
      -Dvulkan-drivers=swrast \
      -Dllvm=enabled \
      -Dshared-llvm=disabled \
      -Dllvm-orcjit=true \
      -Dplatforms= \
      -Dglx=disabled \
      -Dgbm=disabled \
      -Dgallium-va=disabled \
      -Dopengl=false \
      -Dgles1=disabled \
      -Dgles2=disabled \
      -Degl=disabled \
      -Dshared-glapi=disabled \
      -Dspirv-tools=enabled

ninja -C "$TP/_b/mesa"
ninja -C "$TP/_b/mesa" install
# 产物：$INSTALL/lib/libvulkan_lvp.dylib
#       $INSTALL/share/vulkan/icd.d/lvp_icd.x86_64.json

echo "third-party build OK -> $INSTALL"
```

**几个参数的理由，不是抄来的默认值**：

- `-Dshared-llvm=disabled` + `--prefer-static`：把 LLVM 静态链进 `libvulkan_lvp.dylib`。代价是 dylib 很大（darwin 上还要带 `all-targets`，见 3.4.1），收益是运行时不需要在 guest 上存在一个版本匹配的 `libLLVM.dylib`。对一个要在别人机器上自给自足运行的交付物，这个交换是对的。
- `-Dplatforms=` 空：guest 里没有 X11 也没有 Wayland，窗口系统集成一律不要。
- `-Dopengl=false` 与 `gles*`/`egl` 全关：本项目只要 Vulkan。少编一半东西，也少一半失败面。
- `-Dgallium-drivers=llvmpipe` **必须保留**：Lavapipe（`swrast`）依赖 llvmpipe 的 draw/gallivm 基础设施。Mesa 的 `meson.build` 里有显式检查——Lavapipe 与 llvmpipe 都要求 LLVM draw 支持，缺了会直接报错。
- `-Dspirv-tools=enabled`：要求 SPIRV-Tools `>= 2024.1`（3.4.1）。Homebrew 的版本满足。

#### 3.4.4 打包与 `@loader_path` 重定位

```bash
#!/usr/bin/env bash
# scripts/package-vulkan.sh
set -euo pipefail

INSTALL="$PWD/third_party/_install"
STAGE="$PWD/build/stage/Metal2Vu.bundle/Contents/Resources"
mkdir -p "$STAGE/lib" "$STAGE/vulkan/icd.d"

cp "$INSTALL/lib/libvulkan_lvp.dylib"  "$STAGE/lib/"
cp "$INSTALL/lib/libvulkan.1.dylib"    "$STAGE/lib/"
cp "$INSTALL/share/vulkan/icd.d/lvp_icd.x86_64.json" "$STAGE/vulkan/icd.d/"

# ICD 清单改为相对路径引用（相对于清单自身所在目录）
python3 - "$STAGE/vulkan/icd.d/lvp_icd.x86_64.json" <<'PY'
import json, sys
p = sys.argv[1]
d = json.load(open(p))
d["ICD"]["library_path"] = "../../lib/libvulkan_lvp.dylib"
json.dump(d, open(p, "w"), indent=4)
open(p, "a").write("\n")
PY

# 把所有非系统动态依赖搬进 lib/ 并改写为 @loader_path
relocate() {
  local target="$1"
  chmod u+w "$target"
  while read -r dep; do
    [ -z "$dep" ] && continue
    local name; name="$(basename "$dep")"
    if [ ! -f "$(dirname "$target")/$name" ]; then
      cp "$dep" "$(dirname "$target")/"
      chmod u+w "$(dirname "$target")/$name"
      relocate "$(dirname "$target")/$name"       # 递归处理依赖的依赖
    fi
    install_name_tool -change "$dep" "@loader_path/$name" "$target"
  done < <(otool -L "$target" | awk '/\/usr\/local\/|\/opt\/homebrew\//{print $1}')
  install_name_tool -id "@loader_path/$(basename "$target")" "$target" 2>/dev/null || true
}

relocate "$STAGE/lib/libvulkan_lvp.dylib"
relocate "$STAGE/lib/libvulkan.1.dylib"

# 硬检查：任何残留的 Homebrew 路径都是构建失败
fail=0
for f in "$STAGE"/lib/*.dylib; do
  if otool -L "$f" | grep -qE '/usr/local/|/opt/homebrew/'; then
    echo "ERROR: $f 仍引用 Homebrew 路径："; otool -L "$f"; fail=1
  fi
done
[ "$fail" -eq 0 ] || exit 1

# 重新 ad-hoc 签名（install_name_tool 会破坏签名）
for f in "$STAGE"/lib/*.dylib; do
  codesign --force --sign - --timestamp=none "$f"
done

echo "vulkan payload OK"
for f in "$STAGE"/lib/*.dylib; do
  echo "== $f"; otool -L "$f" | sed -n '2,$p'; lipo -info "$f"
done
```

两个容易漏的点：

1. **`relocate` 必须递归。** 直接依赖改完了，但依赖的依赖（例如 `libzstd` 又依赖别的 Homebrew 库）仍指向构建机路径。先例脚本只处理一层，对本项目不够。
2. **`install_name_tool` 之后必须重签。** 修改 Mach-O 头会使既有签名失效；在 SIP 关闭的研发机上也许还能加载，但在任何更严格的配置下会直接失败，而且失败时机是加载时，很难定位。

#### 3.4.5 ICD 发现规则与"只用随包 ICD"

`KNOWN`，全部来自 Vulkan-Loader 的驱动接口文档（<https://github.com/KhronosGroup/Vulkan-Loader/blob/main/docs/LoaderDriverInterface.md>）：

**macOS 上的搜索顺序**是先看应用 bundle 的资源目录，再按与 Linux 类似的顺序看系统与用户路径。文档给出的示例搜索路径序列为：

```text
<bundle>/Contents/Resources/vulkan/icd.d
/Users/<用户>/.config/vulkan/icd.d
/etc/xdg/vulkan/icd.d
/usr/local/etc/vulkan/icd.d
/etc/vulkan/icd.d
/Users/<用户>/.local/share/vulkan/icd.d
/usr/local/share/vulkan/icd.d
/usr/share/vulkan/icd.d
```

**四种强制手段**，按优先级与副作用排列：

| 手段 | 形式 | 语义 | 副作用 |
|---|---|---|---|
| `VK_DRIVER_FILES` | 环境变量，冒号分隔清单文件或目录 | **替换**默认搜索路径 | 若同时设了 `VK_ADD_DRIVER_FILES`，后者被忽略；`VK_ICD_FILENAMES` 是其已弃用的旧名，两者同时存在时以新名为准 |
| `VK_ADD_DRIVER_FILES` | 同上 | **追加**在标准搜索之前 | 存在 `VK_DRIVER_FILES` 时整体失效 |
| `VK_LOADER_DRIVERS_SELECT` | 逗号分隔的 glob，匹配**清单文件名** | 从"已找到"的驱动里按名字筛选 | 需要 1.3.234 及之后版本的 headers 构建的 loader；**匹配不到任何驱动时结果是无驱动可用**，应用会失败 |
| `VK_LOADER_SEARCH_ONLY_IN_BUNDLE` | 置任意值 | 只在 `(bundle)/Contents/Resources/` 下找清单 | 专为把驱动放进 app bundle、避免系统上别处的驱动影响应用而设 |

还有一条不依赖文件系统的路径：**`VK_LUNARG_direct_driver_loading` 扩展**让应用把驱动直接提供给 loader，绕过清单文件发现机制。

**本项目的选择**：

交付形态是 bundle（3.2），因此主手段是 `VK_LOADER_SEARCH_ONLY_IN_BUNDLE` + bundle 内的 `Contents/Resources/vulkan/icd.d`。但 bundle 是被 Metal.framework 加载进**宿主进程**的，`(bundle)` 指的是宿主应用的 bundle 而不是我们的——`BLOCKED`，这一点必须实测，它决定上述手段是否成立。

因此渲染核心在初始化 Vulkan 之前，**在进程内显式设置环境变量**，不依赖外部注入：

```c
/* m2v-core 初始化时，先于任何 vkCreateInstance */
static void m2v_pin_icd(const char *bundle_resources) {
    char icd[PATH_MAX];
    snprintf(icd, sizeof icd, "%s/vulkan/icd.d/lvp_icd.x86_64.json",
             bundle_resources);
    setenv("VK_DRIVER_FILES", icd, /*overwrite=*/1);
    unsetenv("VK_ICD_FILENAMES");          /* 避免旧名干扰 */
    unsetenv("VK_ADD_DRIVER_FILES");       /* 显式清掉，语义更可预测 */
    setenv("VK_LOADER_DRIVERS_SELECT", "lvp_icd.*", 1);
}
```

顺序与理由：`VK_DRIVER_FILES` 用绝对路径把搜索完全替换掉；`VK_LOADER_DRIVERS_SELECT` 作为第二道保险，即使路径解析出了意外也只会接受名字匹配的 Lavapipe；两个可能干扰的变量显式清空。

**长期更干净的形态是 `VK_LUNARG_direct_driver_loading`**：渲染核心与驱动在同一进程、同一交付包内，让 loader 去文件系统里找我们自己带的东西本来就是多余的一环。`INFERRED`，评估归 `40-RUNTIME-VULKAN.md`。

#### 3.4.6 验证构建产物

在 macOS x86_64 构建机上（不是在 guest 里）先过一遍冒烟：

```bash
export VK_DRIVER_FILES="$PWD/build/stage/Metal2Vu.bundle/Contents/Resources/vulkan/icd.d/lvp_icd.x86_64.json"
export VK_LOADER_DEBUG=error,warn
export DYLD_LIBRARY_PATH="$PWD/build/stage/Metal2Vu.bundle/Contents/Resources/lib"

vulkaninfo --summary
# 期望看到一个 deviceName 形如 "llvmpipe (LLVM <ver>, <N> bits)"、deviceType 为 CPU 的设备
```

构建机的 macOS 版本与 guest 不同，所以这只是冒烟，不是验收。真正的验收是 80 分册的 T2 用例（`metal-probe --offscreen-render`）。

本节的全部内容在被 T2 证实之前标 `BLOCKED`：**Lavapipe 在 macOS x86_64 上可建、产物可加载、能完成一次离屏渲染——这三件事都没有被验证过。** 已有先例是 arm64（3.4.2），x86_64 与之的差异至少包括：ORCJIT/MCJIT 的选择、`all-targets` 下静态 LLVM 的体积与链接行为、SSE 路径的代码生成。

---

## 4. kext 的构建与加载

### 4.1 现代 macOS 上第三方 kext 的加载模型

`KNOWN`，来源：`kmutil(8)` 手册（<https://keith.github.io/xcode-man-pages/kmutil.8.html>）。

自 macOS 11 起，kext 不再被单独加载，而是必须先被**链接进三种 kext collection 之一**才能使用。三种 collection：

| collection | 内容 | 位置 | 可变性 |
|---|---|---|---|
| **boot** | 内核与启动引导所需的全部系统 kext | `/System/Library/KernelCollections` | 不可变 |
| **system** | 其余系统 kext，启动之后加载，预链接到 boot collection | 同上 | 不可变；**Apple Silicon 上不存在** |
| **auxiliary（aux）** | `/Library/Extensions` 中的 kext 与其它第三方 kext | 由 `kernelmanagerd` 动态构建，预链接到 boot（与 system，若存在） | 可变 |

**第三方 kext 走 auxiliary collection。** 手册描述的流程是：kext 只有在被 `kernelmanagerd` 构建进 aux collection、且系统重启之后才可加载；启动时 `kernelmanagerd` 把该 collection 载入内核，其中的 kext 才能开始匹配与加载。如果 `kmutil load`、`kextload(8)` 或任何 KextManager 调用去加载一个尚不可加载的 kext，`kernelmanagerd` 会把它暂存到受保护位置、做校验、并提示用户批准重建 aux collection；校验与重建成功后，该 kext 在**下次启动**可用。

**这是对实验循环的关键影响**：装一个新 kext 到生效，正常路径需要**一次重启**。80 分册的 `result.json` 里 `steps[].detail.required_reboot` 字段就是为此而设。

### 4.2 安装与加载序列

```bash
# ---- 1. 安装到 /Library/Extensions ----
sudo rm -rf /Library/Extensions/Metal2VuAccel.kext
sudo cp -R build/kext/Metal2VuAccel.kext /Library/Extensions/
sudo chown -R root:wheel /Library/Extensions/Metal2VuAccel.kext
sudo chmod -R 755        /Library/Extensions/Metal2VuAccel.kext

# ---- 2. 触发 aux collection 重建 ----
# 研发期 SIP 关闭下，直接显式重建比等 kernelmanagerd 的提示更可控
sudo kmutil create -n aux --volume-root / \
                   --kernel /System/Library/Kernels/kernel \
                   --allow-missing-kdk
# 若上面的参数在 25G325 上不被接受，退回触发式：
#   sudo kmutil load -p /Library/Extensions/Metal2VuAccel.kext

# ---- 3. 重启 ----
sudo reboot

# ---- 4. 重启后确认 ----
kmutil showloaded --bundle-identifier net.metal2vu.accel
kextstat | grep metal2vu
ioreg -r -c Metal2VuAccelerator -l -w 0
```

`INFERRED`：`kmutil create -n aux` 的确切参数集需在 25G325 上实测。手册说明 `-n/--new` 接受 `boot`/`sys`/`aux`，`-L/--no-system-collection` 用于构建 aux 时不去找也不生成 system collection，`-s/--strip` 控制符号剥离（取值 `none`/`all`/`allkexts`，默认 `none`），`-k/--kernel` 在构建 boot collection 时给出内核路径。手册同时明确 `create` 只应由"研究自定义内核或替换 boot/system collection 内容"的开发者使用，并且自 macOS 13 起创建 boot 或 system collection 需要 KDK——**aux 不在该要求之内**。

**研发期首选的命令是 `kmutil load -p <path>`**，让 `kernelmanagerd` 走正常的暂存—校验—重建流程。它更慢（要重启），但不会把系统的 collection 状态搞乱。只有在需要跳过重启或排查 collection 本身时才用 `create`。

### 4.3 免重启的快速循环（研发期）

每次改 kext 都重启会让迭代变得难以忍受。SIP 关闭下有一条更快的路：

```bash
# 卸载旧的（要求 kext 支持 unload，即引用计数归零）
sudo kmutil unload --bundle-identifier net.metal2vu.accel

# 直接加载新的（已在 aux collection 中、仅二进制变了时可行）
sudo kmutil load --path /Library/Extensions/Metal2VuAccel.kext
```

`INFERRED`，三个前提：

1. SIP 的 `CSR_ALLOW_UNTRUSTED_KEXTS` 已放开（第 5 节）。
2. kext 的 `stop`/`free` 路径正确，否则 `unload` 会失败或留下泄漏，几次之后行为开始诡异。
3. **IOService 的 provider 已经没有活的 client**。显示类 kext 一旦被 WindowServer 持有就卸不掉，这时只能重启。

实用规则：**改 `IOClass` 层级、`Info.plist`、或依赖集时必须重启；只改方法体时可以尝试 unload/load。** harness 在 `install` 任务里按改动类型决定是否重启，并把决定记进 `required_reboot`。

### 4.4 加载失败的诊断方法

按从廉价到昂贵排序。

```bash
# ---- 1. 依赖与链接诊断（最常用，先跑这个）----
sudo kmutil print-diagnostics /Library/Extensions/Metal2VuAccel.kext
# 会报出未满足的 OSBundleLibraries、符号缺失、Info.plist 错误

# ---- 2. 检查 collection 的一致性 ----
sudo kmutil check
sudo kmutil inspect --bundle-identifier net.metal2vu.accel

# ---- 3. 依赖关系 ----
kmutil libraries --bundle-identifier net.metal2vu.accel
kmutil find --bundle-identifier net.metal2vu.accel

# ---- 4. kext 管理子系统的日志（真实原因常常只在这里）----
log show --last 30m --info --debug --style ndjson \
  --predicate 'subsystem == "com.apple.kext" OR process == "kernelmanagerd" OR process == "kmutil" OR process == "syspolicyd"'

# ---- 5. kmutil 自己的日志与状态转储 ----
kmutil log
sudo kmutil dumpstate

# ---- 6. 暂存区：被暂存但未批准的 kext 卡在这里 ----
sudo kmutil clear-staging     # 清掉脏状态后重试
```

**常见失败与对应信号**（`INFERRED`，依据手册描述与 kext 开发通例，需在实测中补全）：

| 症状 | 大概率原因 | 查法 |
|---|---|---|
| `kmutil load` 说要批准/重启，重启后仍没加载 | `OSBundleLibraries` 版本号不对，aux collection 重建时静默跳过了它 | `print-diagnostics` + `log show` 的 `com.apple.kext` 窗口 |
| 加载了但 `ioreg` 里看不到服务 | `IOKitPersonalities` 的匹配条件不成立（`IOProviderClass` / `IOPCIMatch` 错） | `ioreg -r -c <IOProviderClass> -l` 看 provider 是否存在 |
| 服务在但 `IOServiceOpen` 失败 | user client 的 type 号或 `newUserClient` 实现不对 | 见 `10-KERNEL-ACCELERATOR.md` |
| 加载时 panic | 符号解析到了错版本的 KPI，或 `init`/`start` 里的错误 | 80 分册 2.9.2 的 panic 流程；必须在 L1 带串口的环境下做 |
| `syspolicyd` 拒绝 | SIP/AMFI 没真关 | 第 5.4 节的验证 |

**`kextstat` 与 `kmutil showloaded` 都要采**（80 分册 2.8.3）：前者给出加载地址与引用计数，后者给出 collection 归属。两者信息不重合。

---

## 5. SIP 与 AMFI 的关闭配置

00-OVERVIEW 第 2.4 节规定研发期 SIP 与 AMFI 全部关闭，并在镜像构建时固化，不作为每次实验的步骤。本节给出确切配置。

### 5.1 SIP 的真实形状：一个 32 位位域

`KNOWN`，来源：<https://khronokernel.com/macos/2022/12/09/SIP.html>（该文给出 macOS 13 的 `csr.h` 定义）。

SIP 由 XNU 的 CSR（Configurable Security Restriction）栈处理。Intel 系统从 NVRAM 变量 `csr-active-config` 读取配置；Apple Silicon 从设备树的 `lp-sip0` 条目读取。值是一个 UINT32，按位域解释，**不是一个布尔开关**。

macOS 13 的位定义：

| 位 | 名称 | 含义 |
|---|---|---|
| `0x001` | `CSR_ALLOW_UNTRUSTED_KEXTS` | 允许安装与加载未签名内核驱动 |
| `0x002` | `CSR_ALLOW_UNRESTRICTED_FS` | 不受限的文件系统访问 |
| `0x004` | `CSR_ALLOW_TASK_FOR_PID` | 允许 `task_for_pid` |
| `0x008` | `CSR_ALLOW_KERNEL_DEBUGGER` | 允许内核调试器 |
| `0x010` | `CSR_ALLOW_APPLE_INTERNAL` | Apple 内部模式 |
| `0x020` | `CSR_ALLOW_UNRESTRICTED_DTRACE` | 不受限 DTrace（旧名 `CSR_ALLOW_DESTRUCTIVE_DTRACE`） |
| `0x040` | `CSR_ALLOW_UNRESTRICTED_NVRAM` | 不受限 NVRAM 写入 |
| `0x080` | `CSR_ALLOW_DEVICE_CONFIGURATION` | 设备配置 |
| `0x100` | `CSR_ALLOW_ANY_RECOVERY_OS` | 任意恢复 OS |
| `0x200` | `CSR_ALLOW_UNAPPROVED_KEXTS` | 允许未经手工批准即安装未签名 kext |
| `0x400` | `CSR_ALLOW_EXECUTABLE_POLICY_OVERRIDE` | 可执行策略覆盖 |
| `0x800` | `CSR_ALLOW_UNAUTHENTICATED_ROOT` | 允许未认证的根卷 |

**两个关键事实**（同一来源）：

1. **Intel 上 XNU 不直接读 `csr-active-config`**，是 `boot.efi` 读出来再传给内核。因此该变量必须对固件可见，且**在量产机上 `boot.efi` 会在传递前剥掉 `0x10`（AppleInternal）位**。
2. Intel 上一个 SIP 值作用于所有被引导的 macOS 安装；Apple Silicon 支持按卷配置。

### 5.2 本项目使用的值：`0xFEF`

目标是"除 AppleInternal 以外全部放开"：

```text
0xFFF (全部 12 位) − 0x010 (AppleInternal) = 0xFEF
```

不设 `0x10` 的理由，两条：

1. 它在量产机上会被 `boot.efi` 剥掉（5.1 的事实 1），设了没用。
2. 社区明确不建议通过 `csr-active-config` 打开 `CSR_ALLOW_APPLE_INTERNAL`（转述自 <https://github.com/dortania/bugtracker/issues/157>）。它会让系统进入 Apple 内部代码路径，引入与目标环境无关的行为差异——对一个要确证 ABI 的项目，这是在给自己制造噪声。

`0xFEF` 中与本项目直接相关的位：

| 位 | 为什么需要 |
|---|---|
| `0x001` | 加载我们自己 ad-hoc 签名的 kext（组件 2、3） |
| `0x002` | 写 `/Library/Extensions`、`/Library/GPUBundles`，读系统卷上的样本 |
| `0x004` | 调试器附加到 WindowServer 与测试进程 |
| `0x008` | 内核调试 |
| `0x020` | 80 分册 H-010 用 DTrace 主动触发 panic 来验证 panic 采集链路 |
| `0x040` | 从 guest 内改 boot-args（见 5.3 的路径 B） |
| `0x200` | 免去"系统设置里手工批准 kext"这一步——这是无人值守实验的硬需求 |
| `0x800` | 若需要向系统卷写入（例如替换系统 bundle 做对照实验） |

参考值对照（供排查时辨认别人的配置）：

| 值 | 含义 | 场景 |
|---|---|---|
| `0x000` | SIP 完全启用 | 出厂默认 |
| `0x067` | 部分关闭，OCLP 常用 | 根卷补丁 |
| `0x07F` | 旧的"全关"，含 AppleInternal | Big Sur 之前的通行值，**今天不要用** |
| `0x803` | `0x1 + 0x2 + 0x800` | 需要改系统卷的最小组合 |
| `0xFEF` | **本项目研发期** | 全开，不含 AppleInternal |

### 5.3 在镜像构建期固化

#### 路径 A：OpenCore config.plist（**首选，这是"固化"的正确位置**）

NVRAM 的 Apple 启动变量 GUID 为 `7C436110-AB2A-4BBB-A880-FE41995C9F82`（`KNOWN`，该 GUID 在 OpenCore 文档与社区配置中一致使用，例：<https://github.com/dortania/OpenCore-Install-Guide/blob/master/troubleshooting/extended/userspace-issues.md>）。

```xml
<key>NVRAM</key>
<dict>
  <key>Add</key>
  <dict>
    <key>7C436110-AB2A-4BBB-A880-FE41995C9F82</key>
    <dict>
      <!-- csr-active-config = 0xFEF，小端 4 字节 EF 0F 00 00 -->
      <key>csr-active-config</key>
      <data>7w8AAA==</data>

      <!-- 研发期 boot-args。各项见 5.5 -->
      <key>boot-args</key>
      <string>amfi_get_out_of_my_way=1 keepsyms=1 debug=0x100 -v serial=3 msgbuf=1048576</string>

      <key>prev-lang:kbd</key>
      <string>656e2d55533a30</string>
    </dict>
  </dict>

  <key>Delete</key>
  <dict>
    <!-- 关键：Add 只在变量不存在时写入。必须先 Delete 才能保证每次启动都是我们的值 -->
    <key>7C436110-AB2A-4BBB-A880-FE41995C9F82</key>
    <array>
      <string>csr-active-config</string>
      <string>boot-args</string>
    </array>
  </dict>

  <key>WriteFlash</key>
  <true/>
</dict>
```

**`Delete` 段不可省，这是最容易出错的一点。** OpenCore 的 `Add` 语义是"读一下，不存在才写"，因此一旦 NVRAM 里已有旧值，新配置不会生效；把变量名也列进 `Delete` 可以让 OpenCore 先删后加，每次启动都强制为配置里的值（转述自 <https://github.com/acidanthera/bugtracker/issues/575> 与 <https://github.com/mrlimerunner/sonoma-wifi-hacks>）。另有已知副作用：把 `csr-active-config` 放进 `config.plist` 会使恢复环境里的 `csrutil` 无法改变实际生效值（转述自 <https://github.com/acidanthera/bugtracker/issues/1728>）——这对本项目没有坏处，反而保证了配置的唯一来源是镜像。

`<data>7w8AAA==</data>` 的来源：`0xFEF` 小端 4 字节是 `EF 0F 00 00`，base64 编码为 `7w8AAA==`。换算校验命令：

```bash
# 从 hex 生成 plist data
python3 -c "import base64,struct;print(base64.b64encode(struct.pack('<I',0xFEF)).decode())"
# -> 7w8AAA==
# 反向校验
python3 -c "import base64,struct;print(hex(struct.unpack('<I',base64.b64decode('7w8AAA=='))[0]))"
# -> 0xfef
```

`WriteFlash` 为真时 OpenCore 把这些变量真正写入固件 NVRAM。**这一项在 Vultr 上能否生效取决于实例的 NVRAM 持久性**——80 分册的 H-002，`BLOCKED`。如果 NVRAM 不持久，OpenCore 每次启动重新注入即可，只是 `csrutil status` 在系统内看到的值仍正确，不影响实验。

#### 路径 B：guest 内临时修改（仅排查用）

```bash
# 需要 0x40（CSR_ALLOW_UNRESTRICTED_NVRAM）已放开
sudo nvram csr-active-config=%ef%0f%00%00
sudo nvram boot-args="amfi_get_out_of_my_way=1 keepsyms=1 debug=0x100 -v serial=3"
sudo reboot
```

**不要把这条路径当作固化手段。** 它会在下次 OpenCore 启动时被路径 A 覆盖（因为 `Delete` 段），而且 golden snapshot 之后的任何 `restore` 都会丢掉它。它只适合"临时试一个 boot-arg 看看"。

#### 路径 C：恢复环境 `csrutil`

```bash
# 在 Recovery 的终端里
csrutil disable
csrutil authenticated-root disable
```

不用。`csrutil disable` 设的具体位组合不受我们控制、随版本变化，而且本项目需要的是一个确定的位域值。社区也指出在非官方 Mac 上 `csrutil disable` 常常只得到部分关闭的结果（转述自 <https://docs.bluebubbles.app/server/advanced/disabling-sip-on-unofficial-macs-for-the-private-api>）。

### 5.4 在 guest 内验证确实已关闭

四项检查，缺一不可。前三项是声明，第四项是功能。

```bash
# ---- 1. SIP 文本状态 ----
csrutil status
csrutil authenticated-root status

# ---- 2. NVRAM 实际值 ----
nvram csr-active-config    # 期望：%ef%0f%00%00
nvram boot-args
nvram -p | grep -Ei 'csr|boot-args'
```

```bash
# ---- 3. 内核实际生效的位域（权威检查）----
# csrutil 的文本输出会随版本变化，不适合程序解析。
# 正确做法是调 libSystem 的 csr_get_active_config()。
cat > /tmp/sipcheck.c <<'EOF'
#include <stdio.h>
#include <stdint.h>
typedef uint32_t csr_config_t;
extern int csr_get_active_config(csr_config_t *);
extern int csr_check(csr_config_t);
int main(void) {
    csr_config_t cfg = 0;
    if (csr_get_active_config(&cfg) != 0) { puts("csr_get_active_config failed"); return 1; }
    printf("csr_active_config = 0x%x\n", cfg);
    struct { const char *n; csr_config_t b; } bits[] = {
        {"UNTRUSTED_KEXTS",   0x001}, {"UNRESTRICTED_FS",       0x002},
        {"TASK_FOR_PID",      0x004}, {"KERNEL_DEBUGGER",       0x008},
        {"APPLE_INTERNAL",    0x010}, {"UNRESTRICTED_DTRACE",   0x020},
        {"UNRESTRICTED_NVRAM",0x040}, {"DEVICE_CONFIGURATION",  0x080},
        {"ANY_RECOVERY_OS",   0x100}, {"UNAPPROVED_KEXTS",      0x200},
        {"EXEC_POLICY_OVERRIDE",0x400},{"UNAUTHENTICATED_ROOT", 0x800},
    };
    for (unsigned i = 0; i < sizeof bits / sizeof *bits; i++)
        printf("  %-22s %s\n", bits[i].n, (cfg & bits[i].b) ? "allowed" : "RESTRICTED");
    return 0;
}
EOF
clang -O1 -o /tmp/sipcheck /tmp/sipcheck.c && /tmp/sipcheck
```

用 `csr_get_active_config` 而不是解析 `csrutil status` 的理由：SIP 是位域，`csrutil` 的布尔式输出丢信息；按位查询是推荐做法（转述自 <https://khronokernel.com/macos/2022/12/09/SIP.html>，该文还给出了 Objective-C 与 Python 的实现示例）。

```bash
# ---- 4. 功能性验证（最终判据）----
# 4a. AMFI 真关了？—— 运行一个 ad-hoc 签名、无 entitlement 的可执行
clang -o /tmp/amfitest /tmp/sipcheck.c
codesign --force --sign - /tmp/amfitest
/tmp/amfitest && echo "AMFI: ad-hoc 二进制可执行"

# 4b. 未签名 dylib 能被加载？—— 这是 /Library/GPUBundles 的前提
clang -dynamiclib -o /tmp/libunsigned.dylib -x c - <<<'int probe(void){return 42;}'
# 故意不签名
python3 - <<'PY'
import ctypes
try:
    lib = ctypes.CDLL("/tmp/libunsigned.dylib")
    print("AMFI: 未签名 dylib 加载成功 ->", lib.probe())
except OSError as e:
    print("AMFI: 未签名 dylib 被拒 ->", e)
PY

# 4c. 未签名 kext 能进 aux collection？—— 这是组件 2、3 的前提
sudo kmutil load -p /Library/Extensions/Metal2VuAccel.kext
sudo kmutil print-diagnostics /Library/Extensions/Metal2VuAccel.kext
```

**第 4 项是唯一真正的判据。** `csrutil status` 说 disabled 但 kext 仍加载不上，是完全可能的（例如 `syspolicyd` 另有策略、或 boot-args 没被固件传递）。80 分册的 T0 用例必须包含 4a/4b/4c 三项，并把结果写进 `result.json` 的 `guest.sip_status` 与 `guest.amfi_disabled`。

### 5.5 boot-args 清单

| 参数 | 作用 | 标签 | 必要性 |
|---|---|---|---|
| `amfi_get_out_of_my_way=1` | 关闭 AMFI 的代码签名强制 | `KNOWN`（00-OVERVIEW 第 2.4 节；社区配置中也写作 `amfi_get_out_of_my_way=0x1`，转述自 <https://github.com/azukashi/Sequoia-Haswell-OC/blob/master/README.md>） | **必需**，组件 1、2、3 的前提 |
| `keepsyms=1` | 保留内核符号，使 panic backtrace 可读 | `INFERRED` | **必需**。没有它，panic 报告里只有地址，80 分册的 panic 诊断几乎无用 |
| `-v` | 详细启动，文字启动过程 | `KNOWN` | **必需**。L1 的 early boot 可观测性（80 分册 2.9.1） |
| `serial=3` | 把内核日志路由到串口（输入+输出） | `INFERRED` | **L1 必需**。80 分册 1.4 的结论是串口是 panic 期唯一文本通道；没有这个 boot-arg，串口上不会有内核输出 |
| `debug=0x100` | panic 时把 panic 信息输出到屏幕而不是显示图形 panic 界面 | `INFERRED` | 强烈建议。让 panic 文本能被截图抓到 |
| `msgbuf=1048576` | 扩大内核消息缓冲到 1 MiB | `INFERRED` | 建议。显示栈的日志量很大，默认缓冲会把早期消息冲掉 |
| `kextlog=0xfff` | kext 加载的详细日志 | `INFERRED` | 排查第 4.4 节问题时临时加 |

**`serial=3`、`debug=0x100`、`keepsyms=1`、`msgbuf=` 四项都标 `INFERRED`**：这些是 XNU 在 `pexpert` 层解析的参数，语义长期稳定但没有 Apple 的公开文档保证，且 `debug` 的位含义跨版本有增减。查清方法：在 L1 上逐项开关并观察串口与 panic 报告的变化，把确证结果写回本表（对应 80 分册的未解决项，建议新增 B-0xx 编号跟踪）。

**不要在分发配置里带这些参数。** 本表是研发期配置；`debug`、`serial`、`amfi_get_out_of_my_way` 都是显著降低安全性的开关。分发阶段的配置单独制定（00-OVERVIEW 第 2.4 节末句）。

---

## 6. 安装布局与加载顺序

### 6.1 落地路径

| 组件 | 路径 | 所有者 / 权限 | 说明 |
|---|---|---|---|
| Metal plugin bundle（组件 1，含 Rust 核心、Lavapipe、loader） | `/Library/GPUBundles/Metal2Vu.bundle` | `root:wheel` `755` | Metal.framework 的第三方 GPU bundle 搜索位置 |
| ├ ObjC 可执行 | `…/Contents/MacOS/Metal2Vu` | `root:wheel` `755` | 静态链入 `libm2v_core.a` |
| ├ Lavapipe | `…/Contents/Resources/lib/libvulkan_lvp.dylib` | `root:wheel` `644` | `@loader_path` 已重定位（3.4.4） |
| ├ Vulkan loader | `…/Contents/Resources/lib/libvulkan.1.dylib` | `root:wheel` `644` | — |
| ├ 其余重定位依赖 | `…/Contents/Resources/lib/*.dylib` | `root:wheel` `644` | zstd、SPIRV-Tools 等 |
| └ ICD 清单 | `…/Contents/Resources/vulkan/icd.d/lvp_icd.x86_64.json` | `root:wheel` `644` | `library_path` 为 `../../lib/libvulkan_lvp.dylib` |
| accelerator kext（组件 2） | `/Library/Extensions/Metal2VuAccel.kext` | `root:wheel` `755` | 进 aux collection（第 4 节） |
| display kext（组件 3） | `/Library/Extensions/Metal2VuDisplay.kext` | `root:wheel` `755` | 同上 |
| helper（组件 6） | `/usr/local/libexec/metal2vu-helper` | `root:wheel` `755` | 第一版不启用（00-OVERVIEW 第 6 节） |
| helper 的 launchd plist | `/Library/LaunchDaemons/net.metal2vu.helper.plist` | `root:wheel` `644` | 第一版不安装 |
| 测试探针 | `/usr/local/bin/metal-probe` | `root:wheel` `755` | 80 分册 B3 |
| harness agent | `/usr/local/libexec/harness-agent` | `root:wheel` `755` | 80 分册 2.6，**属于 golden snapshot，不属于本包** |
| 版本清单 | `/Library/GPUBundles/Metal2Vu.bundle/Contents/Resources/MANIFEST.json` | `root:wheel` `644` | 第 7 节 |

`BLOCKED`：`/Library/GPUBundles` 是否是 25G325 上 Metal.framework 实际搜索第三方 plugin bundle 的路径，由 `20-OBJC-DEVICE.md` 用仓库中的 `Metal-BaseSystem-analysis.i64` 确证。00-OVERVIEW 第 2.4 节已把它当作既定路径，但本文不把未确证的路径当 `KNOWN`。

**组件 2 与 3 是两个 kext 还是一个**：00-OVERVIEW 第 5 节指出两者耦合、必须一起设计。本文按两个 bundle 布局，因为它们的 `IOProviderClass` 不同（accelerator 挂 `IOPCIDevice`，display 走 `IOFramebuffer` 范畴），分开便于独立卸载与独立诊断。`INFERRED`，最终由 `11-KERNEL-DISPLAY.md` 决定；若决定合并，则合为一个 bundle 两个 personality。

### 6.2 加载顺序与依赖

```text
启动
 └─ kernelmanagerd 载入 aux collection
     ├─ Metal2VuAccel.kext
     │    provider: IOPCIDevice（或合成 provider，见 10 分册）
     │    发布: MetalPluginName、type-5 user client
     └─ Metal2VuDisplay.kext
          依赖: Metal2VuAccel 已完成 start（需要与之关联）
          provider: IOFramebuffer 范畴
          发布: display mode、接收 scanout

WindowServer 启动
 └─ 枚举 IOAccelerator → 选中一个 → 读其 MetalPluginName
     └─ 加载 /Library/GPUBundles/Metal2Vu.bundle
         ├─ gpu_bundle_find_trusted() 解析路径 → NSBundle 加载
         ├─ principal class（MTLIOAccelDevice 子类）初始化
         ├─ IOServiceOpen(type 5) 到 Metal2VuAccel
         ├─ m2v_pin_icd() 钉死 ICD（3.4.5）
         └─ vkCreateInstance → Lavapipe
```

**三条顺序约束**：

1. **两个 kext 必须在 WindowServer 启动前完成匹配。** 它们都在 aux collection 里，而 aux collection 在启动早期就被载入，所以正常情况下成立。但如果 accelerator 的 `start` 很慢（例如在里面等什么东西），display 的关联可能失败。规则：`start` 里不做阻塞操作。
2. **display 依赖 accelerator**。关联机制（display 如何找到并绑定到 accelerator）是 `11-KERNEL-DISPLAY.md` 的核心问题，`BLOCKED`。在它确证之前，布局上保证 accelerator 的 `IOProbeScore` 高于 display，并在 display 的 `start` 里显式等待/查找 accelerator 服务。
3. **ICD 钉死必须早于任何 `vkCreateInstance`**。`m2v_pin_icd()` 在 principal class 的初始化路径里调用，不能延迟到第一次渲染。

### 6.3 安装脚本

```bash
#!/usr/bin/env bash
# scripts/install.sh —— 在 guest 内以 root 运行
set -euo pipefail

PKG="${1:?usage: install.sh <payload-dir>}"

# ---- 0. 校验 ----
( cd "$PKG" && shasum -a 256 -c MANIFEST.sha256 )

# ---- 1. bundle ----
install -d -o root -g wheel -m 755 /Library/GPUBundles
rm -rf /Library/GPUBundles/Metal2Vu.bundle
cp -R "$PKG/Metal2Vu.bundle" /Library/GPUBundles/
chown -R root:wheel /Library/GPUBundles/Metal2Vu.bundle
find /Library/GPUBundles/Metal2Vu.bundle -type d -exec chmod 755 {} +
find /Library/GPUBundles/Metal2Vu.bundle -type f -exec chmod 644 {} +
chmod 755 /Library/GPUBundles/Metal2Vu.bundle/Contents/MacOS/Metal2Vu

# ---- 2. kext（顺序：accelerator 先，display 后）----
for k in Metal2VuAccel.kext Metal2VuDisplay.kext; do
  rm -rf "/Library/Extensions/$k"
  cp -R "$PKG/$k" /Library/Extensions/
  chown -R root:wheel "/Library/Extensions/$k"
  chmod -R 755 "/Library/Extensions/$k"
done

# ---- 3. 探针与 helper ----
install -o root -g wheel -m 755 "$PKG/metal-probe"      /usr/local/bin/metal-probe
install -o root -g wheel -m 755 "$PKG/metal2vu-helper"  /usr/local/libexec/metal2vu-helper

# ---- 4. 版本清单落地（便于 guest 内自述）----
install -o root -g wheel -m 644 "$PKG/MANIFEST.json" \
        /Library/GPUBundles/Metal2Vu.bundle/Contents/Resources/MANIFEST.json

# ---- 5. 触发 kext collection 重建 ----
kmutil load -p /Library/Extensions/Metal2VuAccel.kext   || true
kmutil load -p /Library/Extensions/Metal2VuDisplay.kext || true
kmutil print-diagnostics /Library/Extensions/Metal2VuAccel.kext
kmutil print-diagnostics /Library/Extensions/Metal2VuDisplay.kext

echo "installed; reboot required for kext activation"
```

卸载脚本必须存在且完整，因为 80 分册 2.6.3 的 `uninstall` 任务依赖它来做"不 restore 的快速迭代"：

```bash
#!/usr/bin/env bash
# scripts/uninstall.sh
set -euo pipefail
kmutil unload --bundle-identifier net.metal2vu.display || true
kmutil unload --bundle-identifier net.metal2vu.accel   || true
rm -rf /Library/Extensions/Metal2VuDisplay.kext \
       /Library/Extensions/Metal2VuAccel.kext \
       /Library/GPUBundles/Metal2Vu.bundle
rm -f  /usr/local/bin/metal-probe /usr/local/libexec/metal2vu-helper
kmutil clear-staging || true
echo "uninstalled; reboot recommended"
```

---

## 7. 版本清单与完整性

### 7.1 每个可发布包必须记录的内容

`MANIFEST.json`，随包交付，同时作为 80 分册 `result.json` 中 `build` 字段的来源：

```json
{
  "schema": "metal2vu.build.manifest/1",

  "build_id": "b-20261030-0914-a31f9c2",
  "built_at": "2026-10-30T09:14:52Z",
  "target": {
    "triple": "x86_64-apple-darwin",
    "macosx_deployment_target": "26.0",
    "baseline_os_build": "25G325"
  },

  "builder": {
    "kind": "github-actions",
    "runner_label": "macos-15-intel",
    "os_build": "24G90",
    "xcode": "17.2 (17C123)",
    "apple_clang": "Apple clang version 17.0.0 (clang-1700.0.13.3)",
    "sdk": "MacOSX26.0.sdk",
    "homebrew_prefix": "/usr/local"
  },

  "source": {
    "git_commit": "a31f9c2d4e5f6a7b8c9d0e1f2a3b4c5d6e7f8a9b",
    "git_describe": "v0.3.1-14-ga31f9c2",
    "git_dirty": false,
    "submodules": [
      { "path": "third_party/mesa",
        "url": "https://gitlab.freedesktop.org/mesa/mesa.git",
        "commit": "1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b",
        "describe": "mesa-26.0.0-devel" },
      { "path": "third_party/Vulkan-Loader",
        "url": "https://github.com/KhronosGroup/Vulkan-Loader.git",
        "commit": "…", "describe": "v1.4.321" },
      { "path": "third_party/Vulkan-Headers",
        "url": "https://github.com/KhronosGroup/Vulkan-Headers.git",
        "commit": "…", "describe": "v1.4.321" },
      { "path": "crates/metal2vulkan",
        "url": "…", "commit": "…", "describe": "…" },
      { "path": "crates/metal2vulkan-runtime",
        "url": "…", "commit": "…", "describe": "…" }
    ]
  },

  "toolchain": {
    "rustc": "1.99.1 (abcdef012 2026-09-15)",
    "cargo": "1.99.1",
    "cmake": "4.1.2",
    "meson": "1.9.0",
    "ninja": "1.13.1",
    "llvm": { "version": "21.1.4", "linkage": "static", "jit": "orcjit",
              "rtti": false, "targets": "all-targets" },
    "bison": "3.8.2",
    "flex": "2.6.4",
    "spirv_tools": "2026.1",
    "glslang": "16.0.0",
    "zstd": "1.5.7",
    "python": "3.13.3",
    "mako": "1.3.10"
  },

  "mesa_config": {
    "gallium_drivers": ["llvmpipe"],
    "vulkan_drivers": ["swrast"],
    "shared_llvm": false,
    "prefer_static": true,
    "platforms": [],
    "opengl": false
  },

  "artifacts": [
    { "name": "Metal2Vu.bundle/Contents/MacOS/Metal2Vu",
      "sha256": "…", "bytes": 2841024,
      "arch": ["x86_64"], "signature": "adhoc",
      "install_path": "/Library/GPUBundles/Metal2Vu.bundle/Contents/MacOS/Metal2Vu" },
    { "name": "Metal2Vu.bundle/Contents/Resources/lib/libvulkan_lvp.dylib",
      "sha256": "…", "bytes": 148293120,
      "arch": ["x86_64"], "signature": "adhoc",
      "upstream": "mesa@1a2b3c4",
      "install_path": "/Library/GPUBundles/Metal2Vu.bundle/Contents/Resources/lib/libvulkan_lvp.dylib" },
    { "name": "Metal2Vu.bundle/Contents/Resources/lib/libvulkan.1.dylib",
      "sha256": "…", "bytes": 1204736,
      "arch": ["x86_64"], "signature": "adhoc",
      "upstream": "Vulkan-Loader@v1.4.321",
      "install_path": "/Library/GPUBundles/Metal2Vu.bundle/Contents/Resources/lib/libvulkan.1.dylib" },
    { "name": "Metal2Vu.bundle/Contents/Resources/vulkan/icd.d/lvp_icd.x86_64.json",
      "sha256": "…", "bytes": 203, "arch": [], "signature": "none",
      "install_path": "/Library/GPUBundles/Metal2Vu.bundle/Contents/Resources/vulkan/icd.d/lvp_icd.x86_64.json" },
    { "name": "Metal2VuAccel.kext",
      "sha256": "…", "bytes": 184320, "arch": ["x86_64"], "signature": "adhoc",
      "bundle_id": "net.metal2vu.accel",
      "os_bundle_libraries": {
        "com.apple.kpi.iokit": "26.0",
        "com.apple.iokit.IOAcceleratorFamily2": "1.0",
        "com.apple.iokit.IOGraphicsFamily": "1.0",
        "com.apple.iokit.IOPCIFamily": "1.0",
        "com.apple.iokit.IOSurface": "1.0"
      },
      "install_path": "/Library/Extensions/Metal2VuAccel.kext" },
    { "name": "Metal2VuDisplay.kext",
      "sha256": "…", "bytes": 151552, "arch": ["x86_64"], "signature": "adhoc",
      "bundle_id": "net.metal2vu.display",
      "install_path": "/Library/Extensions/Metal2VuDisplay.kext" },
    { "name": "metal-probe",
      "sha256": "…", "bytes": 3215360, "arch": ["x86_64"], "signature": "adhoc",
      "install_path": "/usr/local/bin/metal-probe" },
    { "name": "metal2vu-helper",
      "sha256": "…", "bytes": 2998272, "arch": ["x86_64"], "signature": "adhoc",
      "install_path": "/usr/local/libexec/metal2vu-helper" }
  ],

  "expected_runtime_config": {
    "csr_active_config": "0xfef",
    "boot_args_required": ["amfi_get_out_of_my_way=1"],
    "boot_args_recommended": ["keepsyms=1", "-v", "serial=3", "debug=0x100"]
  },

  "package": {
    "tarball": "metal2vu-b-20261030-0914-a31f9c2-x86_64.tar.gz",
    "sha256": "…",
    "bytes": 61298371
  },

  "manifest_sha256": "…"
}
```

### 7.2 必须记录的最小集

即使不用上面的完整形式，以下几项**不可省**，每一项都对应一类真实发生过的排查困境：

| 项 | 为什么不可省 |
|---|---|
| 每个二进制产物的 SHA-256 | 没有它，"guest 上跑的到底是哪个版本"无法回答；80 分册 2.5 的投放校验也依赖它 |
| 自身 git commit + dirty 标记 | dirty 构建产生的结果不可复现。**dirty 构建禁止进入任何记 `TESTED` 的实验** |
| 每个 submodule 的 commit | 上游 Mesa 在快速演进，"换了个 Mesa 就好了/坏了"必须能定位到 commit |
| LLVM 的版本 + 链接方式 + JIT 选择 + RTTI | 这四项任一不同，Lavapipe 的行为与体积都不同（3.4.1） |
| Apple clang 版本 + SDK 版本 + 部署目标 | kext 的 KPI 绑定与 ObjC 的私有基类符号对这三项敏感 |
| 构建机 OS build | 构建机与目标 OS 不同是常态（2.2 方案 A），记录差值 |
| 每个 kext 的 `OSBundleLibraries` | 4.4 表里最常见的失败就出在这里 |
| `csr_active_config` 期望值与必需 boot-args | 包与运行环境的契约。安装脚本可据此在安装前拒绝不满足条件的 guest |

### 7.3 完整性与可重建

```bash
# 生成（打包时）
( cd dist/payload && find . -type f -print0 | sort -z \
    | xargs -0 shasum -a 256 > ../MANIFEST.sha256 )

# 校验（投放后、安装前，在 guest 内）
( cd /tmp/payload && shasum -a 256 -c MANIFEST.sha256 )
```

**离线可重建归档**，针对 2.2 末尾的落日风险。每次发布一个版本，同时归档：

```text
archive/b-20261030-0914-a31f9c2/
  MANIFEST.json
  metal2vu-…-x86_64.tar.gz          # 产物
  sources/
    mesa-1a2b3c4.tar.zst            # git archive 的源码快照
    Vulkan-Loader-v1.4.321.tar.zst
    Vulkan-Headers-v1.4.321.tar.zst
    metal2vulkan-….tar.zst
  brew-bottles/                     # Homebrew 二进制瓶，x86_64 切片
    llvm-21.1.4.ventura.bottle.tar.gz
    zstd-1.5.7.ventura.bottle.tar.gz
    spirv-tools-2026.1.ventura.bottle.tar.gz
    bison-3.8.2.ventura.bottle.tar.gz
    flex-2.6.4.ventura.bottle.tar.gz
  SHA256SUMS
```

归档 Homebrew 瓶而不只是记版本号：x86_64 的瓶会随 Homebrew 停止支持 Intel 而消失，到那时只有版本号是没用的。这是一次性的几 GB 存储换取构建能力不随上游退场而失效。

---

## 8. 未解决项清单

| 编号 | 事项 | 标签 | 查清方法 | 阻塞什么 |
|---|---|---|---|---|
| P-001 | Lavapipe 能否在 macOS x86_64 上成功构建 | `BLOCKED` | 跑 3.4.3 的脚本 | 组件 5 全部；80 分册 B3 |
| P-002 | 静态 LLVM + `all-targets` 下 `libvulkan_lvp.dylib` 的体积与加载时间是否可接受 | `BLOCKED` | P-001 之后测量 | 可能需要改用动态 LLVM 并随包交付 `libLLVM.dylib` |
| P-003 | ORCJIT 在 macOS x86_64 上是否稳定 | `INFERRED` | P-001 后跑离屏渲染；失败则退 MCJIT | 3.4.3 的配置项 |
| P-004 | 继承 `MTLIOAccelDevice` 的确切链接参数（`-framework Metal` 是否足够，还是需要 `-undefined dynamic_lookup`） | `INFERRED` | 在构建机上直接试编一个最小子类。类符号对外可见这一点已由 `20-OBJC-DEVICE.md` 第 4.3 节确证 | 3.2 的链接参数 |
| P-005 | `/Library/GPUBundles` 是否为 25G325 上的实际搜索路径 | `BLOCKED` | 反编译 `Metal` 样本中的 **`gpu_bundle_find_trusted`**（由 `20-OBJC-DEVICE.md` 第 3 节定位为路径解析与 trust gate 的唯一入口），读出它拼接的目录常量 | 6.1 的落地路径 |
| P-006 | kext 的 `OSBundleLibraries` 确切条目与版本字符串 | `BLOCKED` | 读 `AppleParavirtGPU.kext` 的 `Info.plist`（仓库已有 x86 payload）；归 `10`/`11` 分册 | 3.3；4.4 的首要失败源 |
| P-007 | aux collection 构建是否需要 KDK | `INFERRED` | 在 L1 guest 上跑 4.2 的两条命令 | 2.1 的卡点 2；构建机方案 |
| P-008 | macOS 26 是否提供 x86_64 KDK | `BLOCKED` | 查 Apple 开发者下载；若无则 P-007 必须为"不需要" | 内核调试能力 |
| P-009 | `serial=3` / `debug=0x100` / `keepsyms=1` / `msgbuf=` 在 25G325 上的确切语义 | `INFERRED` | L1 上逐项开关并观察串口与 panic 报告 | 5.5；80 分册 1.4 的 panic 诊断 |
| P-010 | Vultr 实例的 NVRAM 是否持久（`WriteFlash` 是否有效） | `BLOCKED` | 80 分册 H-002 | 5.3 路径 A 在 L2 的有效性 |
| P-011 | ad-hoc 签名在 SIP=0xFEF 下是否足够，还是需要 Developer ID | `INFERRED` | 跑 5.4 的第 4 项 | 3.3 的签名参数；分发阶段策略 |
| P-012 | `install_name_tool` 递归重定位后是否仍有系统外依赖（`otool -L` 全绿） | `BLOCKED` | 3.4.4 的硬检查 | 交付物在 guest 上能否加载 |
| P-013 | 组件 2 与 3 合为一个 kext 还是两个 | `INFERRED` | 归 `11-KERNEL-DISPLAY.md` | 6.1 / 6.2 的布局 |

---

## 9. 相关分册

- `80-TEST-HARNESS.md`：本文产出的 `MANIFEST.json` 是它 `result.json` 中 `build` 字段的来源；5.4 的四项验证是它 T0 用例的内容；4.2 的重启需求对应它的 `required_reboot`。
- `10-KERNEL-ACCELERATOR.md` / `11-KERNEL-DISPLAY.md`：确证 P-006、P-013，决定 3.3 的 `OSBundleLibraries` 与 6.1 的 kext 划分。
- `20-OBJC-DEVICE.md`：确证 P-004、P-005，决定 3.2 的链接参数与 bundle 落地路径。
- `40-RUNTIME-VULKAN.md`：决定 3.4.5 中是否改用 `VK_LUNARG_direct_driver_loading`。
- `90-EVIDENCE-INDEX.md`：本文第 7 节的 SHA-256 规则与它的样本索引共用一套完整性约定。
