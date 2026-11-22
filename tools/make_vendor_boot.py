#!/usr/bin/env python3
"""Repack an Android vendor_boot image (header v3/v4) for any device.

The template image supplies header fields, cmdline, dtb and bootconfig.
Fragments from the template are kept unless replaced or dropped.

Examples:
  # dual fragment: stock platform + built recovery
  make_vendor_boot.py --template stock_vb.img --recovery-lz4 twrp.lz4 -o out.img

  # single fragment: use the given ramdisk as platform, drop everything else
  make_vendor_boot.py --template built_vb.img --ramdisk-lz4 ramdisk.lz4 -o out.img

  # replace by type number or name, keep all other stock fragments
  make_vendor_boot.py --template vb.img --fragment dlkm=dlkm.lz4 -o out.img

Header v3 has no fragment table: only one ramdisk can be written.
"""
import argparse
import sys
from pathlib import Path

import vendor_boot_lib as vbl

LZ4_MAGIC = b"\x02\x21\x4c\x18"


def read_lz4(path):
    try:
        data = Path(path).read_bytes()
    except OSError as e:
        sys.exit(f"{path}: {e}")
    if data[:4] != LZ4_MAGIC:
        sys.exit(f"{path}: not an lz4 legacy frame (compress with lz4 -l)")
    return data


def parse_fragment_arg(value):
    if "=" not in value:
        sys.exit(f"--fragment expects TYPE=PATH, got {value!r}")
    ftype, path = value.split("=", 1)
    try:
        ftype = vbl.type_id(ftype)
    except ValueError as e:
        sys.exit(str(e))
    return ftype, read_lz4(path)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--template", "--stock", dest="template", required=True,
                    help="vendor_boot used for header/cmdline/dtb/bootconfig and kept fragments")
    ap.add_argument("--ramdisk-lz4", help="replace ALL fragments with this platform ramdisk")
    ap.add_argument("--platform-lz4", help="replace/create the platform (type 1) fragment")
    ap.add_argument("--recovery-lz4", help="replace/create the recovery (type 2) fragment")
    ap.add_argument("--dlkm-lz4", help="replace/create the dlkm (type 3) fragment")
    ap.add_argument("--fragment", action="append", default=[], metavar="TYPE=PATH",
                    help="replace/create any fragment; TYPE may be 1/2/3 or platform/recovery/dlkm")
    ap.add_argument("--drop", action="append", default=[], metavar="TYPE",
                    help="drop fragments of this type")
    ap.add_argument("--cmdline", help="override the cmdline (default: keep template)")
    ap.add_argument("--selinux-permissive", action="store_true",
                    help="append androidboot.selinux=permissive if not present")
    ap.add_argument("--pad-to", type=int, default=0,
                    help="pad output with zeros to this many bytes (default: 0 = no padding)")
    ap.add_argument("-o", "--out", required=True)
    a = ap.parse_args()

    try:
        img = vbl.parse(Path(a.template).read_bytes())
    except ValueError as e:
        sys.exit(f"{a.template}: {e}")

    fragments = [dict(f) for f in img.fragments]

    if a.ramdisk_lz4:
        if a.platform_lz4 or a.recovery_lz4 or a.dlkm_lz4 or a.fragment:
            sys.exit("--ramdisk-lz4 cannot be combined with other fragment options")
        fragments = [{"type": 1, "name": "", "board_id": b"\x00" * vbl.BOARD_ID_SIZE,
                      "data": read_lz4(a.ramdisk_lz4)}]
    else:
        for ftype, path in ((1, a.platform_lz4), (2, a.recovery_lz4), (3, a.dlkm_lz4)):
            if path:
                vbl.set_fragment(fragments, ftype, read_lz4(path))
        for value in a.fragment:
            ftype, data = parse_fragment_arg(value)
            vbl.set_fragment(fragments, ftype, data)
        for value in a.drop:
            try:
                fragments = vbl.drop_type(fragments, value)
            except ValueError as e:
                sys.exit(str(e))

    if img.version == 3 and len(fragments) != 1:
        sys.exit("header v3 supports a single vendor ramdisk; "
                 "only --ramdisk-lz4 / --platform-lz4 is valid")

    cmdline = img.cmdline
    if a.cmdline is not None:
        cmdline = a.cmdline.encode()
    if a.selinux_permissive and b"androidboot.selinux" not in cmdline:
        cmdline += b" androidboot.selinux=permissive"

    try:
        out, content = vbl.build(img, fragments, cmdline=cmdline, pad_to=a.pad_to)
    except ValueError as e:
        sys.exit(str(e))
    Path(a.out).write_bytes(out)

    print(f"template : {a.template} (header v{img.version}, page {img.page_size}, "
          f"{len(img.fragments)} fragment(s))")
    print(f"cmdline  : {cmdline.decode(errors='replace')}")
    if img.version == 4:
        print(f"bootconfig: {img.bootconfig!r}")
    for f in fragments:
        print(f"fragment : type={f['type']}({vbl.TYPE_NAMES.get(f['type'], '?')}) "
              f"name={f['name'] or '-'} size={len(f['data'])}B")
    print(f"content  : {content}B"
          + (f" -> {len(out)}B (zero padding {len(out) - content}B)" if a.pad_to else "")
          + f" -> {a.out}")


if __name__ == "__main__":
    main()
