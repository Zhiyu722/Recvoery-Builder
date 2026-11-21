#!/usr/bin/env bash
# repack_vendor_boot.sh — 把构建出来的 vendor_boot 重新打包成「能正常启动 + 能进 recovery」的结构。
#
#   bash tools/repack_vendor_boot.sh <构建出的 vendor_boot.img> [recovery/root 目录]
#
# 为什么需要这一步：
#   BOARD_INCLUDE_RECOVERY_RAMDISK_IN_VENDOR_BOOT 让 AOSP 生成两个片段，但 platform 片段
#   来自 out 里的 vendor_ramdisk（本设备树没有往里装 first_stage 文件），结果只有 4 字节的
#   空 LZ4 帧；正常启动用的就是 platform 片段，于是系统进不去。这里把 platform 片段换成
#   原厂 vendor_boot 的 platform 片段（逐字节一致），recovery 片段保留构建产物（TWRP）。
#
# 环境变量：
#   PERMISSIVE=0   不追加 androidboot.selinux=permissive（默认追加，和 TWRP 现行行为一致）
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
STOCK="$ROOT/prebuilt/vendor_boot_stock.img"
BUILT="${1:?用法: repack_vendor_boot.sh <vendor_boot.img> [recovery/root]}"
REC_ROOT="${2:-$(dirname "$BUILT")/recovery/root}"

[ -f "$STOCK" ] || { echo "缺少 $STOCK"; exit 1; }
[ -f "$BUILT" ] || { echo "缺少 $BUILT"; exit 1; }

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

echo "== 构建产物结构 =="
python3 "$ROOT/tools/extract_fragment.py" "$BUILT" --list || true

if python3 "$ROOT/tools/extract_fragment.py" "$BUILT" --type 2 --out "$WORK/recovery.lz4"; then
  echo "== 使用构建产物里的 recovery 片段 =="
else
  echo "== 构建产物没有 recovery 片段，改用 $REC_ROOT 现场打包 =="
  [ -d "$REC_ROOT" ] || { echo "缺少 $REC_ROOT"; exit 1; }
  ( cd "$REC_ROOT" && find . | cpio -o -H newc --quiet | lz4 -l -12 -f - "$WORK/recovery.lz4" -q )
fi

EXTRA=()
if [ "${PERMISSIVE:-1}" != "0" ]; then
  EXTRA+=(--selinux-permissive)
fi

python3 "$ROOT/tools/make_vendor_boot.py" \
  --stock "$STOCK" \
  --recovery-lz4 "$WORK/recovery.lz4" \
  --out "$WORK/vendor_boot_fixed.img" \
  "${EXTRA[@]}"

echo "== 校验 =="
python3 "$ROOT/tools/check_vendor_boot.py" --stock "$STOCK" "$WORK/vendor_boot_fixed.img"

cp -f "$BUILT" "$BUILT.orig"
cp -f "$WORK/vendor_boot_fixed.img" "$BUILT"
echo "✅ 已替换 $BUILT（原始镜像备份为 $BUILT.orig）"
md5sum "$BUILT"
