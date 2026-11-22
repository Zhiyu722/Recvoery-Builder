#!/usr/bin/env bash
# repack_vendor_boot.sh — make a built vendor_boot image bootable on any device.
#
#   bash tools/repack_vendor_boot.sh <built vendor_boot.img> [ramdisk_dir]
#
# The AOSP build often emits a useless platform fragment (an empty lz4 frame) or a
# dual-fragment image that some bootloaders cannot consume. This script rebuilds
# the image from a template and lets you choose the layout:
#
#   MODE=auto    keep if platform is already populated; otherwise dual when a
#                v4 stock image and a built recovery fragment exist; else single
#   MODE=dual    platform = stock platform, recovery = built recovery fragment
#   MODE=single  platform = built recovery fragment (or ramdisk_dir), one fragment
#   MODE=keep    leave the built image untouched (verify only)
#
# Environment:
#   STOCK_VENDOR_BOOT   stock vendor_boot image (default: auto-discover)
#   DEVICE_TREE         device tree checkout; used for prebuilt/ and BoardConfig.mk
#   MODE                auto (default) | dual | single | keep
#   PAD_TO              auto (default) | <bytes> | 0. auto reads
#                       BOARD_VENDOR_BOOTIMAGE_PARTITION_SIZE from BoardConfig.mk
#   PERMISSIVE=1        append androidboot.selinux=permissive
#   USE_BUNDLED_STOCK=1 allow falling back to prebuilt/vendor_boot_stock.img in
#                       this repo (that file is only an example for one device)
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
BUILT="${1:?usage: repack_vendor_boot.sh <vendor_boot.img> [ramdisk_dir]}"
REC_ROOT="${2:-}"
MODE="${MODE:-auto}"
PAD_TO="${PAD_TO:-auto}"
STOCK="${STOCK_VENDOR_BOOT:-}"
DEVICE_TREE="${DEVICE_TREE:-}"

[ -f "$BUILT" ] || { echo "missing built image: $BUILT" >&2; exit 1; }

# ---- locate a stock image ---------------------------------------------------
find_stock() {
  [ -n "$STOCK" ] && { echo "$STOCK"; return; }
  if [ -n "$DEVICE_TREE" ]; then
    for p in "$DEVICE_TREE/prebuilt/vendor_boot_stock.img" \
             "$DEVICE_TREE/prebuilt/vendor_boot.img" \
             "$DEVICE_TREE/prebuilt/vb.img"; do
      [ -f "$p" ] && { echo "$p"; return; }
    done
  fi
  if [ "${USE_BUNDLED_STOCK:-0}" = "1" ] && [ -f "$ROOT/prebuilt/vendor_boot_stock.img" ]; then
    echo "$ROOT/prebuilt/vendor_boot_stock.img"
    return
  fi
}

STOCK=$(find_stock || true)
STOCK_VERSION=0
if [ -n "$STOCK" ]; then
  [ -f "$STOCK" ] || { echo "stock image not found: $STOCK" >&2; exit 1; }
  STOCK_VERSION=$(python3 - "$STOCK" "$ROOT/tools" <<'PY'
import sys
sys.path.insert(0, sys.argv[2])
import vendor_boot_lib as vbl
print(vbl.parse(open(sys.argv[1], "rb").read()).version)
PY
  ) || { echo "cannot parse stock image: $STOCK" >&2; exit 1; }
  echo "== stock vendor_boot: $STOCK (header v$STOCK_VERSION)"
else
  echo "== no stock vendor_boot (dual mode and platform comparison disabled)"
fi

# ---- resolve padding --------------------------------------------------------
if [ "$PAD_TO" = "auto" ]; then
  PAD_TO=0
  BOARD_CONFIG=""
  if [ -n "$DEVICE_TREE" ] && [ -f "$DEVICE_TREE/BoardConfig.mk" ]; then
    BOARD_CONFIG="$DEVICE_TREE/BoardConfig.mk"
  else
    BOARD_CONFIG=$(find "$ROOT" -maxdepth 4 -name BoardConfig.mk -print -quit 2>/dev/null || true)
  fi
  if [ -n "$BOARD_CONFIG" ]; then
    PAD_TO=$(grep -E '^[[:space:]]*BOARD_VENDOR_BOOTIMAGE_PARTITION_SIZE[[:space:]]*:?=' "$BOARD_CONFIG" \
      | head -n1 | grep -oE '[0-9]+' | head -n1 || true)
    [ -n "$PAD_TO" ] && echo "== pad to $PAD_TO B (from $BOARD_CONFIG)" \
                     || PAD_TO=0
  fi
  [ "$PAD_TO" = "0" ] && echo "== no padding target found; output keeps its natural size"
fi

WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT

# ---- find the built recovery fragment ---------------------------------------
RECOVERY_LZ4=""
if python3 "$ROOT/tools/extract_fragment.py" "$BUILT" --type 2 --out "$WORK/recovery.lz4" \
     >/dev/null 2>&1; then
  RECOVERY_LZ4="$WORK/recovery.lz4"
  echo "== built image has a recovery fragment ($(stat -c%s "$RECOVERY_LZ4")B)"
fi

PLATFORM_SIZE=$(python3 "$ROOT/tools/extract_fragment.py" "$BUILT" --type 1 --out "$WORK/platform.lz4" \
  >/dev/null 2>&1 && stat -c%s "$WORK/platform.lz4" || echo 0)
[ "$PLATFORM_SIZE" -le 8 ] && PLATFORM_SIZE=0

pack_dir() {
  [ -n "$REC_ROOT" ] && [ -d "$REC_ROOT" ] || return 1
  ( cd "$REC_ROOT" && find . | cpio -o -H newc --quiet | lz4 -l -12 -f - "$WORK/from_dir.lz4" -q )
}

if [ "$MODE" = "auto" ]; then
  if [ -n "$STOCK" ] && [ "$STOCK_VERSION" -ge 4 ] && [ -n "$RECOVERY_LZ4" ]; then
    MODE=dual
  elif [ -n "$RECOVERY_LZ4" ]; then
    MODE=single
  elif [ "$PLATFORM_SIZE" -gt 0 ]; then
    MODE=keep
  elif pack_dir; then
    MODE=single
  else
    echo "cannot determine a layout: no recovery fragment, platform is empty, no ramdisk_dir" >&2
    exit 1
  fi
  echo "== MODE=auto -> $MODE"
fi

# ---- rebuild ----------------------------------------------------------------
TEMPLATE="$BUILT"
[ -n "$STOCK" ] && TEMPLATE="$STOCK"
PAD_ARGS=(--pad-to "$PAD_TO")
PERM_ARGS=()
[ "${PERMISSIVE:-0}" = "1" ] && PERM_ARGS=(--selinux-permissive)

case "$MODE" in
  keep)
    echo "== keeping the built image as-is (platform fragment already populated)"
    python3 "$ROOT/tools/check_vendor_boot.py" "$BUILT"
    exit 0
    ;;
  dual)
    [ -n "$STOCK" ] || { echo "MODE=dual needs STOCK_VENDOR_BOOT" >&2; exit 1; }
    if [ -z "$RECOVERY_LZ4" ]; then
      if ! pack_dir; then
        echo "MODE=dual needs a recovery fragment or ramdisk_dir" >&2; exit 1
      fi
      RECOVERY_LZ4="$WORK/from_dir.lz4"
    fi
    python3 "$ROOT/tools/make_vendor_boot.py" \
      --template "$STOCK" --recovery-lz4 "$RECOVERY_LZ4" \
      --out "$WORK/vendor_boot_fixed.img" "${PAD_ARGS[@]}" "${PERM_ARGS[@]}"
    ;;
  single)
    if [ -n "$RECOVERY_LZ4" ]; then
      RAMDISK="$RECOVERY_LZ4"
    elif [ "$PLATFORM_SIZE" -gt 0 ]; then
      RAMDISK="$WORK/platform.lz4"
    elif pack_dir; then
      RAMDISK="$WORK/from_dir.lz4"
    else
      echo "MODE=single needs a recovery/platform fragment or ramdisk_dir" >&2; exit 1
    fi
    python3 "$ROOT/tools/make_vendor_boot.py" \
      --template "$TEMPLATE" --ramdisk-lz4 "$RAMDISK" \
      --out "$WORK/vendor_boot_fixed.img" "${PAD_ARGS[@]}" "${PERM_ARGS[@]}"
    ;;
  *)
    echo "unknown MODE=$MODE (auto|dual|single|keep)" >&2; exit 1
    ;;
esac

echo "== verify =="
if [ "$MODE" = "dual" ] && [ -n "$STOCK" ]; then
  python3 "$ROOT/tools/check_vendor_boot.py" --stock "$STOCK" "$WORK/vendor_boot_fixed.img"
elif [ "$MODE" = "single" ]; then
  python3 "$ROOT/tools/check_vendor_boot.py" --require-platform \
    --expect-platform-md5 "$(md5sum "$RAMDISK" | cut -d' ' -f1)" "$WORK/vendor_boot_fixed.img"
else
  python3 "$ROOT/tools/check_vendor_boot.py" --require-platform "$WORK/vendor_boot_fixed.img"
fi

[ -f "$BUILT.orig" ] || cp -f "$BUILT" "$BUILT.orig"
cp -f "$WORK/vendor_boot_fixed.img" "$BUILT"
echo "done: $BUILT (backup: $BUILT.orig)"
md5sum "$BUILT"
