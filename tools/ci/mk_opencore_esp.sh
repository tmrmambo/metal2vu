#!/bin/bash
# tools/ci/mk_opencore_esp.sh —— 装配 OpenCore 的 EFI 树并做成一块可引导的 FAT32 裸镜像。
#
# 规格: docs/spec/71-IMAGE-OPENCORE.md §6 §8.2 / docs/spec/76-BOOT-LAYOUT-PICKER.md §2 §5 §6
#
# 用法:
#   mk_opencore_esp.sh <工作目录> [选项]
#     --oc-tag <tag>        OpenCorePkg 的 release tag，或 latest
#     --ocbin-ref <ref>     OcBinaryData 的 git ref（分支或 commit），默认 master
#     --lilu-tag <tag>      Lilu 的 release tag，或 latest
#     --vsmc-tag <tag>      VirtualSMC 的 release tag，或 latest
#     --picker builtin|canopy
#     --variant RELEASE|DEBUG
#     --size-mib <N>        镜像大小，默认 64
#
# 为什么是一块**裸 FAT32**（没有分区表）
# -------------------------------------
# 71 §8.2.4 的 L1 命令行把 OpenCore 当一块独立的盘挂在 AHCI 上
# （`-drive id=oc,...,file=opencore.img` + `-device ide-hd,bus=sata.0,drive=oc,bootindex=0`），
# 而 OVMF 对「整块盘就是一个 FAT 文件系统」这种形态是认的。
# 注意这和镜像里那个 ESP 不是一回事：76 的 71-F 把镜像内 ESP 改成了 512 MiB 且在 GPT 里
# （三分区布局的 p1）。本脚本产的是前者 —— L1 上单独挂的那块引导盘。
#
# 为什么不用 loop mount
# --------------------
# GitHub 的运行器上 `mount -o loop` 要 root 且会碰 /dev/loop*，在容器化的 runner 上
# 时常不可用。`mkfs.vfat` + `mtools`（mcopy/mmd）全程只操作文件，不需要 root，
# 也不依赖内核的 loop 设备。
#
# DEBUG 与 RELEASE 两套都要留（71 §2.5，依据 80 §1.4）
# ---------------------------------------------------
# L1 的串口是 panic 期唯一文本通道，而 OpenCore 的 RELEASE 构建几乎不输出日志。
# 官方要求把 BOOTx64.efi / OpenCore.efi / OpenRuntime.efi / OpenCanopy.efi
# 四个换成 DEBUG 或 NOOPT 版才能拿到有用信息。所以 --variant 是个档位。
set -euo pipefail

WORK="${1:?用法: mk_opencore_esp.sh <工作目录> [选项]}"; shift

OC_TAG=latest
OCBIN_REF=master
LILU_TAG=latest
VSMC_TAG=latest
PICKER=builtin
VARIANT=RELEASE
SIZE_MIB=64

while [ $# -gt 0 ]; do
    case "$1" in
        --oc-tag)     OC_TAG="$2"; shift 2 ;;
        --ocbin-ref)  OCBIN_REF="$2"; shift 2 ;;
        --lilu-tag)   LILU_TAG="$2"; shift 2 ;;
        --vsmc-tag)   VSMC_TAG="$2"; shift 2 ;;
        --picker)     PICKER="$2"; shift 2 ;;
        --variant)    VARIANT="$2"; shift 2 ;;
        --size-mib)   SIZE_MIB="$2"; shift 2 ;;
        *) echo "不认识的参数 $1" >&2; exit 2 ;;
    esac
done

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
DL="$WORK/dl"; STAGE="$WORK/stage"; OUT="$WORK/out"
mkdir -p "$DL" "$STAGE" "$OUT"

need() { command -v "$1" >/dev/null || { echo "缺工具: $1" >&2; exit 2; }; }
for t in curl unzip python3 iasl mkfs.vfat mcopy mmd; do need "$t"; done

# ---------------------------------------------------------------------------
# 1. 解析版本。规格（71 §2.5）要求「查 release 页取最新，写死 tag」——
#    所以这里既支持 latest，也把解析出来的 tag 记进 MANIFEST，下一轮好钉死。
# ---------------------------------------------------------------------------
resolve_tag() {   # resolve_tag <owner/repo> <tag|latest>
    if [ "$2" != "latest" ]; then echo "$2"; return; fi
    curl -fsSL "https://api.github.com/repos/$1/releases/latest" \
      | python3 -c 'import json,sys; print(json.load(sys.stdin)["tag_name"])'
}

OC_TAG=$(resolve_tag acidanthera/OpenCorePkg "$OC_TAG")
LILU_TAG=$(resolve_tag acidanthera/Lilu "$LILU_TAG")
VSMC_TAG=$(resolve_tag acidanthera/VirtualSMC "$VSMC_TAG")

echo "---- 钉下来的版本 ----"
printf '  %-14s %s\n' OpenCorePkg "$OC_TAG" OcBinaryData "$OCBIN_REF" \
                      Lilu "$LILU_TAG" VirtualSMC "$VSMC_TAG"
printf '  %-14s %s\n' picker "$PICKER" variant "$VARIANT"

# ---------------------------------------------------------------------------
# 2. 下载。release 资产的命名规则：OpenCore-<ver>-<RELEASE|DEBUG>.zip，
#    其中 <ver> 是去掉前导 v 的 tag。
# ---------------------------------------------------------------------------
fetch() {   # fetch <url> <落地文件名>
    echo "  取 $2"
    curl -fsSL -o "$DL/$2" "$1"
}

OC_VER="${OC_TAG#v}"
fetch "https://github.com/acidanthera/OpenCorePkg/releases/download/${OC_TAG}/OpenCore-${OC_VER}-${VARIANT}.zip" \
      "oc.zip"
fetch "https://github.com/acidanthera/Lilu/releases/download/${LILU_TAG}/Lilu-${LILU_TAG#v}-${VARIANT}.zip" \
      "lilu.zip"
fetch "https://github.com/acidanthera/VirtualSMC/releases/download/${VSMC_TAG}/VirtualSMC-${VSMC_TAG#v}-${VARIANT}.zip" \
      "vsmc.zip"
fetch "https://codeload.github.com/acidanthera/OcBinaryData/zip/refs/heads/${OCBIN_REF}" \
      "ocbin.zip"

for z in oc lilu vsmc ocbin; do
    mkdir -p "$DL/$z"
    unzip -q -o "$DL/$z.zip" -d "$DL/$z"
done
OCBIN="$(find "$DL/ocbin" -maxdepth 1 -type d -name 'OcBinaryData*' | head -1)"
[ -n "$OCBIN" ] || { echo "OcBinaryData 解出来的目录没找到" >&2; exit 1; }

# ---------------------------------------------------------------------------
# 3. 铺 EFI 树
# ---------------------------------------------------------------------------
EFI="$STAGE/EFI"
mkdir -p "$EFI/BOOT" "$EFI/OC/ACPI" "$EFI/OC/Drivers" "$EFI/OC/Kexts" \
         "$EFI/OC/Tools" "$EFI/OC/Resources"

cp "$DL/oc/X64/EFI/BOOT/BOOTx64.efi"   "$EFI/BOOT/"
cp "$DL/oc/X64/EFI/OC/OpenCore.efi"    "$EFI/OC/"

# 驱动。注意 HfsPlus.efi 来自 OcBinaryData，不是 OpenCorePkg
# （76 §6 的 71-A / L-003：OcBinaryData/Drivers/ 下没有叫 OpenHfsPlus.efi 的文件，
#  照 71 §6.9.1 的文件名抄会在这一步 cp 不到东西）。
for d in OpenRuntime.efi ResetNvramEntry.efi ToggleSipEntry.efi OpenCanopy.efi; do
    cp "$DL/oc/X64/EFI/OC/Drivers/$d" "$EFI/OC/Drivers/"
done
cp "$OCBIN/Drivers/HfsPlus.efi" "$EFI/OC/Drivers/"

# OpenShell 不启用，但文件留在 Tools 里（71 §6.9.1：picker 不出现时它是唯一的自救手段）
cp "$DL/oc/X64/EFI/OC/Tools/OpenShell.efi" "$EFI/OC/Tools/" 2>/dev/null || true

# kext 最小集三件（76 §5.4：一个不多、一个不少）
cp -R "$DL/lilu/Lilu.kext"                       "$EFI/OC/Kexts/"
cp -R "$DL/vsmc/Kexts/VirtualSMC.kext"           "$EFI/OC/Kexts/"
cp -R "$DL/vsmc/Kexts/AppleMCEReporterDisabler.kext" "$EFI/OC/Kexts/"

# OpenCanopy 的资源（76 §2.3：Label 与 Font 都是 mandatory，Audio 不取）
if [ "$PICKER" = canopy ]; then
    mkdir -p "$EFI/OC/Resources/Image" "$EFI/OC/Resources/Label" "$EFI/OC/Resources/Font"
    cp -R "$OCBIN/Resources/Image/Acidanthera/GoldenGate" "$EFI/OC/Resources/Image/"
    cp -R "$OCBIN/Resources/Label/."  "$EFI/OC/Resources/Label/"
    cp -R "$OCBIN/Resources/Font/."   "$EFI/OC/Resources/Font/"
fi

# ---------------------------------------------------------------------------
# 4. 编 SSDT-EC。父设备是 \_SB.PCI0 而不是桌面版的 \_SB.PCI0.LPCB（76 §5.3.1）
# ---------------------------------------------------------------------------
echo "---- iasl ----"
iasl -ve -p "$WORK/SSDT-EC" "$REPO_ROOT/tools/oc/SSDT-EC-QEMU.dsl"
cp "$WORK/SSDT-EC.aml" "$EFI/OC/ACPI/SSDT-EC.aml"
ls -l "$EFI/OC/ACPI/SSDT-EC.aml"

# ---------------------------------------------------------------------------
# 5. 生成 config.plist，并跑 ACPI 存在性门禁（76 §5.3.5 / L-014）
# ---------------------------------------------------------------------------
echo "---- config.plist ----"
python3 "$REPO_ROOT/tools/ci/make_oc_config.py" generate \
        "$DL/oc/Docs/Sample.plist" "$EFI/OC/config.plist" \
        --picker "$PICKER" --acpi-dir "$EFI/OC/ACPI"

# ---------------------------------------------------------------------------
# 6. 做成裸 FAT32 镜像
# ---------------------------------------------------------------------------
IMG="$OUT/opencore.img"
rm -f "$IMG"
dd if=/dev/zero of="$IMG" bs=1048576 count="$SIZE_MIB" status=none
mkfs.vfat -F 32 -n OPENCORE "$IMG" >/dev/null
# mtools 对镜像默认会抱怨「不是分区」，-i 指定整个文件即可
export MTOOLS_SKIP_CHECK=1
( cd "$STAGE" && mcopy -i "$IMG" -s -Q EFI :: )

echo "---- 镜像内容回读（这是「文件真的进去了」的唯一证据）----"
mdir -i "$IMG" -/ ::/EFI | sed -n '1,80p'

# ---------------------------------------------------------------------------
# 7. MANIFEST：版本 + 每个文件的哈希。71 §8.2.5 要求 golden 的哈希覆盖引导配置。
# ---------------------------------------------------------------------------
MAN="$OUT/opencore-manifest.txt"
{
    echo "# OpenCore ESP manifest"
    echo "opencorepkg_tag=$OC_TAG"
    echo "ocbinarydata_ref=$OCBIN_REF"
    echo "lilu_tag=$LILU_TAG"
    echo "virtualsmc_tag=$VSMC_TAG"
    echo "picker=$PICKER"
    echo "variant=$VARIANT"
    echo "image_size_mib=$SIZE_MIB"
    echo "built_at=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo
    echo "# sha256 of every staged file"
    ( cd "$STAGE" && find . -type f -print0 | sort -z | xargs -0 sha256sum )
    echo
    echo "# sha256 of the image itself"
    sha256sum "$IMG"
} > "$MAN"
cat "$MAN"

echo
echo ">>> 产物: $IMG ($(du -h "$IMG" | cut -f1))"
echo ">>> 清单: $MAN"
