#!/usr/bin/env python3
"""Extract a fragment from a vendor_boot image (header v3/v4).

  extract_fragment.py img --list
  extract_fragment.py img --type 2 --out recovery.lz4
  extract_fragment.py img --name dlkm --out dlkm.lz4

Exit code 0 when found, 3 when not found.
"""
import argparse
import sys
from pathlib import Path

import vendor_boot_lib as vbl


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("img")
    ap.add_argument("--type", help="fragment type: 0-3 or platform/recovery/dlkm")
    ap.add_argument("--name", help="fragment name (exact match)")
    ap.add_argument("--index", type=int, help="fragment index")
    ap.add_argument("--out")
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()

    try:
        img = vbl.parse(Path(a.img).read_bytes())
    except (OSError, ValueError) as e:
        sys.exit(f"{a.img}: {e}")

    if a.list:
        for i, f in enumerate(img.fragments):
            print(f"index={i} type={f['type']}({vbl.TYPE_NAMES.get(f['type'], '?')}) "
                  f"size={len(f['data'])} off={f.get('offset', '-')} name={f['name']!r}")
        if not img.fragments:
            print("(no fragments)")
        return

    matches = list(enumerate(img.fragments))
    if a.type is not None:
        try:
            ftype = vbl.type_id(a.type)
        except ValueError as e:
            sys.exit(str(e))
        matches = [(i, f) for i, f in matches if f["type"] == ftype]
    if a.name is not None:
        matches = [(i, f) for i, f in matches if f["name"] == a.name]
    if a.index is not None:
        matches = [(i, f) for i, f in matches if i == a.index]

    if not matches:
        sys.exit(3)
    index, frag = matches[0]
    if not a.out:
        sys.exit("need --out (or use --list)")
    Path(a.out).write_bytes(frag["data"])
    print(f"wrote {a.out} ({len(frag['data'])}B, index={index}, type={frag['type']}, "
          f"name={frag['name']!r})")


if __name__ == "__main__":
    main()
