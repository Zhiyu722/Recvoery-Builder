#!/usr/bin/env python3
"""vendor_boot 打包自检。

  python3 check_vendor_boot.py <vendor_boot.img>...
  python3 check_vendor_boot.py --stock vb_a.img <vendor_boot.img>   # 额外比对 platform 片段是否与原厂逐字节一致

判据：platform 片段非空(>1MB) / bootconfig 含 androidboot.hardware / cmdline 保留 bootconfig /
片段表自洽（偏移连续、总长等于 vendor_ramdisk_size）。退出码 0=全部 OK。
"""
import hashlib
import struct
import sys

TYPES = {0: "none", 1: "platform", 2: "recovery", 3: "dlkm"}


def al(x, ps):
    return (x + ps - 1) // ps * ps


def parse(d):
    hver, ps = struct.unpack_from("<II", d, 8)
    vrs = struct.unpack_from("<I", d, 24)[0]
    hsz, dtbsz = struct.unpack_from("<II", d, 2096)
    tsz, num, esz, bcsz = struct.unpack_from("<IIII", d, 2112)
    cmd = d[28:2076].split(b"\x00")[0].decode("ascii", "replace")
    base = al(hsz, ps)
    tbl = base + al(vrs, ps) + al(dtbsz, ps)
    frags = []
    for i in range(num):
        o = tbl + i * esz
        sz, off, ty = struct.unpack_from("<III", d, o)
        nm = d[o + 12:o + 44].split(b"\x00")[0].decode("ascii", "replace")
        frags.append({"type": ty, "size": sz, "off": off, "name": nm,
                      "md5": hashlib.md5(d[base + off:base + off + sz]).hexdigest()})
    bc = d[tbl + al(tsz, ps):tbl + al(tsz, ps) + bcsz] if bcsz else b""
    return dict(hver=hver, ps=ps, vrs=vrs, cmd=cmd, bcsz=bcsz, bc=bc, frags=frags)


def check(path, stock_md5=None):
    d = open(path, "rb").read()
    if d[:8] != b"VNDRBOOT":
        print(f"== {path}\nFAIL 不是 vendor_boot 镜像")
        return False
    i = parse(d)
    ok = True
    print(f"== {path}")
    print(f"header v{i['hver']} pagesize {i['ps']} vendor_ramdisk_size {i['vrs']} "
          f"bootconfig {i['bcsz']}B")
    print(f"cmdline: {i['cmd']}")

    if "bootconfig" not in i["cmd"]:
        print("WARN  cmdline 里没有 bootconfig token（原厂是 'console=... bootconfig bootconfig'）")
    if i["bcsz"] == 0:
        print("FAIL  bootconfig 为空：androidboot.hardware 丢失 -> ro.hardware 失效")
        ok = False
    else:
        print(f"bootconfig: {i['bc']!r}")
        if b"androidboot.hardware" not in i["bc"]:
            print("FAIL  bootconfig 缺 androidboot.hardware")
            ok = False

    total = 0
    for n, f in enumerate(i["frags"]):
        print(f"frag{n}: type={f['type']}({TYPES.get(f['type'], '?')}) size={f['size']} "
              f"off={f['off']} name={f['name']!r} md5={f['md5']}")
        if f["off"] != total:
            print(f"FAIL  frag{n} 偏移 {f['off']} != 累计 {total}（片段表不自洽）")
            ok = False
        total += f["size"]
    if total != i["vrs"]:
        print(f"FAIL  片段总长 {total} != vendor_ramdisk_size {i['vrs']}")
        ok = False

    plat = [f for f in i["frags"] if f["type"] == 1]
    if not plat:
        print("FAIL  没有 platform 片段 -> 正常启动无 first-stage ramdisk")
        ok = False
    elif max(f["size"] for f in plat) < 1024 * 1024:
        print(f"FAIL  platform 片段只有 {max(f['size'] for f in plat)}B（空 LZ4 帧）-> 正常启动必挂")
        ok = False
    elif stock_md5 and plat[0]["md5"] != stock_md5:
        print(f"FAIL  platform 片段 md5 {plat[0]['md5']} != 原厂 {stock_md5}"
              " -> 正常启动内容被 TWRP 污染")
        ok = False

    rec = [f for f in i["frags"] if f["type"] == 2]
    if rec:
        print(f"NOTE  recovery 片段 {rec[0]['size']}B（TWRP 应在这一片里）")
    else:
        print("WARN  没有 recovery 片段：recovery 模式会跑 platform 片段内容")

    print("RESULT:", "OK" if ok else "NOT FLASHABLE (正常启动会失败)")
    return ok


if __name__ == "__main__":
    args = sys.argv[1:]
    stock = None
    if args[:1] == ["--stock"]:
        if len(args) < 3:
            print(__doc__)
            sys.exit(2)
        stock = parse(open(args[1], "rb").read())
        stock = next((f["md5"] for f in stock["frags"] if f["type"] == 1), None)
        args = args[2:]
    if not args:
        print(__doc__)
        sys.exit(2)
    results = [check(p, stock) for p in args]
    sys.exit(0 if all(results) else 1)
