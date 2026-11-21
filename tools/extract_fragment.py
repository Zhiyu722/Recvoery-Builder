#!/usr/bin/env python3
"""从 vendor_boot (header v4) 镜像里取出指定 type 的片段。

  python3 extract_fragment.py img --list
  python3 extract_fragment.py img --type 2 --out recovery.lz4

找到则退出码 0，未找到退出码 3（方便 shell 里做 fallback）。
"""
import argparse
import struct
import sys

PS = 4096


def al(x):
    return (x + PS - 1) // PS * PS


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("img")
    ap.add_argument("--type", type=int, default=2)
    ap.add_argument("--out")
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()

    d = open(a.img, "rb").read()
    if d[:8] != b"VNDRBOOT":
        sys.exit("不是 vendor_boot 镜像")
    hsz, dtbsz = struct.unpack_from("<II", d, 2096)
    tsz, num, esz, bcsz = struct.unpack_from("<IIII", d, 2112)
    vrs = struct.unpack_from("<I", d, 24)[0]
    base = al(hsz)
    tbl = base + al(vrs) + al(dtbsz)

    frags = []
    for i in range(num):
        o = tbl + i * esz
        sz, off, ty = struct.unpack_from("<III", d, o)
        nm = d[o + 12:o + 44].split(b"\x00")[0].decode("ascii", "replace")
        frags.append((ty, sz, off, nm))

    for ty, sz, off, nm in frags:
        print(f"type={ty} size={sz} off={off} name={nm!r}")

    hit = next((f for f in frags if f[0] == a.type), None)
    if hit is None:
        sys.exit(3)
    if not a.list:
        if not a.out:
            sys.exit("需要 --out")
        ty, sz, off, nm = hit
        with open(a.out, "wb") as fp:
            fp.write(d[base + off:base + off + sz])
        print(f"wrote {a.out} ({sz}B)")


if __name__ == "__main__":
    main()
