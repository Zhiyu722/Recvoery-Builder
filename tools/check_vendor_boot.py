#!/usr/bin/env python3
"""Validate Android vendor_boot images (header v3/v4).

  check_vendor_boot.py img.img [img2.img ...]
  check_vendor_boot.py --stock stock.img img.img     # also compare platform fragment
  check_vendor_boot.py --expect-platform-md5 MD5 img.img

Exit code 0 when every image is structurally valid, 1 otherwise.
Warnings (missing bootconfig, missing recovery fragment, small platform, ...)
do not fail the check; use --require-platform to make one of them fatal.
"""
import argparse
import hashlib
import struct
import sys
from pathlib import Path

import vendor_boot_lib as vbl


def check(path, stock_md5=None, expect_md5=None, require_platform=False, quiet=False):
    problems = []
    warnings = []
    try:
        data = Path(path).read_bytes()
        img = vbl.parse(data)
    except (OSError, ValueError) as e:
        print(f"== {path}\nFAIL  {e}")
        return False

    print(f"== {path}")
    frag_total = sum(len(f["data"]) for f in img.fragments)
    print(f"header v{img.version} page_size {img.page_size} "
          f"vendor_ramdisk_size {img.ramdisk_size}B (fragments {frag_total}B) "
          f"dtb {img.dtb_size}B bootconfig {len(img.bootconfig)}B")
    if img.version == 4 and frag_total > img.ramdisk_size:
        problems.append("fragments overlap or exceed vendor_ramdisk_size")
    elif img.version == 4 and frag_total < img.ramdisk_size:
        warnings.append("vendor ramdisk has unused tail bytes")
    print(f"cmdline: {img.cmdline.decode(errors='replace')}")

    if img.version == 4:
        table_size, count, entry_size, bc_size = struct.unpack_from("<IIII", data, 2112)
        if count == 0:
            problems.append("fragment table is empty")
        if entry_size < vbl.ENTRY_SIZE:
            problems.append(f"fragment entry size {entry_size} < {vbl.ENTRY_SIZE}")
        if len(img.bootconfig) != bc_size:
            problems.append("bootconfig_size does not match parsed bootconfig")
        if not img.bootconfig:
            warnings.append("bootconfig is empty")
        elif b"androidboot.hardware" not in img.bootconfig:
            warnings.append("bootconfig has no androidboot.hardware")
        if b"bootconfig" not in img.cmdline:
            warnings.append("cmdline has no 'bootconfig' token")

        expected_off = 0
        for i, frag in enumerate(img.fragments):
            if frag.get("offset") != expected_off:
                warnings.append(f"fragment {i} offset {frag.get('offset')} != {expected_off} "
                                "(gaps/overlaps are unusual but legal)")
            expected_off = max(expected_off, (frag.get("offset") or 0) + len(frag["data"]))
    else:
        warnings.append("header v3: no fragment table, recovery cannot ride in vendor_boot")

    for frag in img.fragments:
        print(f"fragment type={frag['type']}({vbl.TYPE_NAMES.get(frag['type'], '?')}) "
              f"name={frag['name'] or '-'} size={len(frag['data'])}B "
              f"md5={hashlib.md5(frag['data']).hexdigest()}")

    platforms = [f for f in img.fragments if f["type"] == 1]
    if not platforms:
        msg = "no platform fragment"
        (problems if require_platform else warnings).append(msg)
    else:
        if max(len(f["data"]) for f in platforms) <= 8:
            warnings.append("platform fragment is an empty lz4 frame")
        elif max(len(f["data"]) for f in platforms) < 1024 * 1024:
            warnings.append("platform fragment is smaller than 1 MiB")

    if img.version == 4 and not any(f["type"] == 2 for f in img.fragments):
        warnings.append("no recovery fragment (recovery mode will use platform)")

    if stock_md5 and platforms and hashlib.md5(platforms[0]["data"]).hexdigest() != stock_md5:
        problems.append(f"platform md5 {hashlib.md5(platforms[0]['data']).hexdigest()} "
                        f"!= stock {stock_md5}")
    if expect_md5 and platforms and hashlib.md5(platforms[0]["data"]).hexdigest() != expect_md5:
        problems.append(f"platform md5 {hashlib.md5(platforms[0]['data']).hexdigest()} "
                        f"!= expected {expect_md5}")

    if not quiet:
        for w in warnings:
            print(f"WARN  {w}")
    for p in problems:
        print(f"FAIL  {p}")
    ok = not problems
    print("RESULT:", "OK" if ok else "FAILED")
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("images", nargs="+")
    ap.add_argument("--stock", help="stock image; compare its platform fragment with each image")
    ap.add_argument("--expect-platform-md5", help="required md5 of the platform fragment")
    ap.add_argument("--require-platform", action="store_true",
                    help="treat a missing platform fragment as an error")
    ap.add_argument("--quiet", action="store_true", help="do not print warnings")
    a = ap.parse_args()

    stock_md5 = None
    if a.stock:
        try:
            stock_md5 = vbl.platform_digest(Path(a.stock).read_bytes())
        except (OSError, ValueError) as e:
            sys.exit(f"{a.stock}: {e}")
        if stock_md5 is None:
            sys.exit(f"{a.stock}: no platform fragment")

    results = [check(p, stock_md5, a.expect_platform_md5, a.require_platform, a.quiet)
               for p in a.images]
    sys.exit(0 if all(results) else 1)


if __name__ == "__main__":
    main()
