#!/bin/bash
# tools/ci/free_space.sh —— 在 GitHub 的 macOS 运行器上腾空间，并把每一项腾出多少记下来。
#
# 用法
# ----
#     tools/ci/free_space.sh              # 腾光所有可腾项
#     tools/ci/free_space.sh 200          # 腾到容器可用 ≥ 200 GB 就停，不够则退出码 1
#
# 为什么不用 du 统计
# ------------------
# du 在 /Applications/Xcode_*.app 这种几十万个文件的目录上要跑好几分钟，而且
# APFS 的克隆与 decmpfs 压缩会让 du 的数字跟「删掉它能多出多少可用空间」对不上。
# 所以这里改成：每删一项就重新读一次容器可用空间，差值就是这一项的真实收益。
# 代价是每项多一次 diskutil 调用（约 0.3 秒），换来的是不会再出现
# 「du 说能腾 30 GB、删完只多了 4 GB」这种事。
#
# 不删的东西
# ----------
#   - xcode-select -p 指向的那个 Xcode。cc / xcrun / 各种 SDK 都在它里面，
#     删了之后连 hvf_probe.c 都编不过。
#   - /usr/local/Homebrew 本体。后面还要 brew install qemu。
#
# 退出码
# ------
#     0  没给目标，或给了目标且达成
#     1  给了目标但腾完仍不够（调用方应当据此停下，而不是继续往一块没空间的盘上写）
set -uo pipefail

NEED_GB="${1:-0}"

free_bytes() {
    diskutil info -plist / 2>/dev/null \
        | plutil -extract APFSContainerFree raw -o - - 2>/dev/null \
        || echo 0
}

gb() { echo $(( ${1:-0} / 1000000000 )); }

START=$(free_bytes)
printf '起点：容器可用 %s GB（目标 %s GB）\n' "$(gb "$START")" "$NEED_GB"
df -h / || true
echo

ACTIVE_XCODE=""
if ACTIVE_DEV=$(xcode-select -p 2>/dev/null); then
    # /Applications/Xcode_16.4.app/Contents/Developer → /Applications/Xcode_16.4.app
    case "$ACTIVE_DEV" in
        /Applications/*.app/*) ACTIVE_XCODE="${ACTIVE_DEV%%.app/*}.app" ;;
    esac
fi
printf '活动 Xcode：%s（保留）\n\n' "${ACTIVE_XCODE:-无（用 CommandLineTools）}"

# 账单攒在文件里，不攒在变量里：`VAR="$VAR$(printf …)"` 会被命令替换吃掉行尾换行，
# 于是所有行糊成一行。这个坑踩过一次，表现是日志里一条 300 字符的长行。
REPORT=$(mktemp)
trap 'rm -f "$REPORT"' EXIT
row() { printf "$@" >> "$REPORT"; }
TOTAL_FREED=0

target_met() {
    [ "$NEED_GB" = "0" ] && return 1
    [ "$(gb "$(free_bytes)")" -ge "$NEED_GB" ]
}

# reclaim <说明> <路径…>
reclaim() {
    label="$1"; shift
    if target_met; then
        row '  %-42s %10s  %s\n' "$label" "-" "已达目标，跳过"
        return 0
    fi
    before=$(free_bytes)
    hit=0
    for p in "$@"; do
        [ -e "$p" ] || continue
        hit=1
        sudo rm -rf "$p" 2>/dev/null || true
    done
    if [ "$hit" = "0" ]; then
        row '  %-42s %10s  %s\n' "$label" "-" "不存在"
        return 0
    fi
    after=$(free_bytes)
    delta=$(( after - before ))
    TOTAL_FREED=$(( TOTAL_FREED + delta ))
    row '  %-42s %7s GB  可用 → %s GB\n' "$label" "$(gb "$delta")" "$(gb "$after")"
    printf '  腾掉 %-36s +%s GB\n' "$label" "$(gb "$delta")"
}

echo "---- 开始腾（按「体积大 × 我们一定不需要」排序）----"

# 1) 非活动的 Xcode。运行器上通常装了 6–7 个，每个 4–10 GB，是最大的一块。
for app in /Applications/Xcode*.app; do
    [ -d "$app" ] || continue
    [ "$app" = "$ACTIVE_XCODE" ] && continue
    reclaim "Xcode: $(basename "$app")" "$app"
done

# 2) 模拟器运行时。iOS/watchOS/tvOS 的 runtime 每个几 GB。
reclaim "CoreSimulator Runtimes" \
    /Library/Developer/CoreSimulator/Profiles/Runtimes
reclaim "CoreSimulator Devices/Caches" \
    /Library/Developer/CoreSimulator/Devices \
    "$HOME/Library/Developer/CoreSimulator" \
    "$HOME/Library/Developer/Xcode/iOS DeviceSupport"

# 3) actions/setup-* 预装的各语言工具链缓存
reclaim "hostedtoolcache" "$HOME/hostedtoolcache" /Users/runner/hostedtoolcache

# 4) 我们用不到的 SDK
reclaim "Android SDK/NDK" \
    /usr/local/lib/android "$HOME/Library/Android" /Library/Android
reclaim ".NET" /usr/local/share/dotnet "$HOME/.dotnet"
reclaim "Haskell (ghcup/stack)" "$HOME/.ghcup" "$HOME/.stack"
reclaim "Ruby/gem 缓存" "$HOME/.gem" /usr/local/lib/ruby/gems
reclaim "Julia/Swift toolchains" /Applications/Julia*.app /Library/Developer/Toolchains

# 5) 浏览器与杂项 app
reclaim "浏览器" \
    "/Applications/Google Chrome.app" "/Applications/Firefox.app" \
    "/Applications/Microsoft Edge.app" "/Applications/Chromium.app"

# 6) 缓存
reclaim "各类缓存" \
    "$HOME/Library/Caches" /Library/Caches \
    "$HOME/Library/Developer/Xcode/DerivedData" \
    "$HOME/Library/Developer/Xcode/Archives"

# 7) brew 的下载缓存。单独一条，因为它不是 rm 而是 brew 自己的子命令。
if ! target_met; then
    before=$(free_bytes)
    brew cleanup --prune=all >/dev/null 2>&1 || true
    rm -rf "$(brew --cache 2>/dev/null)" 2>/dev/null || true
    after=$(free_bytes)
    TOTAL_FREED=$(( TOTAL_FREED + after - before ))
    row '  %-42s %7s GB  可用 → %s GB\n' \
        "brew cleanup --prune=all" "$(gb $(( after - before )))" "$(gb "$after")"
fi

END=$(free_bytes)
echo
echo "---- 逐项账单 ----"
cat "$REPORT"
printf '合计：%s GB → %s GB（多出 %s GB）\n' \
    "$(gb "$START")" "$(gb "$END")" "$(gb $(( END - START )))"
df -h / || true

if [ "$NEED_GB" != "0" ] && [ "$(gb "$END")" -lt "$NEED_GB" ]; then
    echo "::error::腾完仍只有 $(gb "$END") GB，低于目标 ${NEED_GB} GB"
    exit 1
fi
exit 0
