#!/usr/bin/env python3
"""按原厂 vendor_boot 头重打包；支持 platform / recovery 双片段 (header v4)。

  # 单片段：platform 片段用给定 ramdisk（临时验证用）
  python3 make_vendor_boot.py --stock vb_a.img --ramdisk-lz4 twrp.lz4 --out o.img

  # 正常方案：platform=原厂 ramdisk（系统启动），recovery=TWRP ramdisk
  python3 make_vendor_boot.py --stock vb_a.img --recovery-lz4 twrp.lz4 --out o.img

  # 显式指定 platform 片段
  python3 make_vendor_boot.py --stock vb_a.img --platform-lz4 p.lz4 --recovery-lz4 r.lz4 --out o.img

头/表/dtb/bootconfig 全部沿用原厂镜像；片段表按 type=1 platform、type=2 recovery 重写。
"""
import argparse
import struct
import sys

PS = 4096
LZ4_MAGIC = b"\x02\x21\x4c\x18"


def al(x):
    return (x + PS - 1) // PS * PS


def parse(st):
    if st[:8] != b"VNDRBOOT":
        sys.exit("stock 不是 VNDRBOOT")
    hver, ps = struct.unpack_from("<II", st, 8)
    hsz, dtbsz = struct.unpack_from("<II", st, 2096)
    dtbaddr = struct.unpack_from("<Q", st, 2104)[0]
    tsz, num, esz, bcsz = struct.unpack_from("<IIII", st, 2112)

    cmd = st[28:2076].split(b"\x00")[0].decode()
    rd_off = al(hsz)
    rd_size = struct.unpack_from("<I", st, 24)[0]
    dtb_off = rd_off + al(rd_size)
    tb_off = dtb_off + al(dtbsz)
    bc_off = tb_off + al(tsz)

    frags = []
    for i in range(num):
        e = tb_off + i * esz
        sz, off, typ = struct.unpack_from("<III", st, e)
        name = st[e + 12:e + 44].split(b"\x00")[0].decode()
        frags.append({"size": sz, "off": off, "type": typ, "name": name,
                      "data": st[rd_off + off:rd_off + off + sz]})

    return {
        "hver": hver, "ps": ps, "hsz": hsz, "cmd": cmd, "dtbsz": dtbsz,
        "dtbaddr": dtbaddr, "dtb": st[dtb_off:dtb_off + dtbsz],
        "rd_size": rd_size, "tsz": tsz, "num": num, "esz": esz,
        "bcsz": bcsz, "bootconfig": st[bc_off:bc_off + bcsz], "frags": frags,
    }


def read_lz4(path):
    d = open(path, "rb").read()
    if d[:4] != LZ4_MAGIC:
        sys.exit(f"{path} 不是 lz4 legacy 帧（需要 lz4 -l）")
    return d


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stock", required=True, help="原厂 vendor_boot（头/表/dtb/bootconfig 来源）")
    ap.add_argument("--ramdisk-lz4", default=None, help="单片段模式：platform 片段内容")
    ap.add_argument("--platform-lz4", default=None, help="platform 片段内容（默认=原厂片段）")
    ap.add_argument("--recovery-lz4", default=None, help="recovery 片段内容（给出则生成双片段）")
    ap.add_argument("--out", required=True)
    ap.add_argument("--cmdline", default=None, help="默认沿用原厂 cmdline")
    ap.add_argument("--selinux-permissive", action="store_true",
                    help="在 cmdline 末尾追加 androidboot.selinux=permissive")
    ap.add_argument("--pad-to", type=int, default=104857600,
                    help="末尾补零到该字节数，默认 104857600(=BOARD_VENDOR_BOOTIMAGE_PARTITION_SIZE)；0=不补")
    a = ap.parse_args()

    if a.ramdisk_lz4 and (a.platform_lz4 or a.recovery_lz4):
        sys.exit("--ramdisk-lz4 与 --platform-lz4/--recovery-lz4 不能混用")

    st = parse(open(a.stock, "rb").read())
    if st["ps"] != PS:
        sys.exit(f"pagesize {st['ps']} != {PS}，脚本需调整")
    if st["hsz"] != 2128:
        sys.exit(f"header_size {st['hsz']} 非 v4 标准值")

    stock_platform = next((f["data"] for f in st["frags"] if f["type"] == 1), None)
    if stock_platform is None:
        sys.exit("原厂镜像里没有 type=1 platform 片段")

    if a.ramdisk_lz4:
        frags = [{"type": 1, "name": "", "data": read_lz4(a.ramdisk_lz4)}]
    else:
        plat = read_lz4(a.platform_lz4) if a.platform_lz4 else stock_platform
        frags = [{"type": 1, "name": "", "data": plat}]
        if a.recovery_lz4:
            frags.append({"type": 2, "name": "recovery",
                          "data": read_lz4(a.recovery_lz4)})

    cmd = (a.cmdline or st["cmd"]).encode()
    if a.selinux_permissive and b"androidboot.selinux" not in cmd:
        cmd += b" androidboot.selinux=permissive"
    if len(cmd) >= 2048:
        sys.exit("cmdline 超长")

    total = sum(len(f["data"]) for f in frags)
    hdr = bytearray(open(a.stock, "rb").read()[:st["hsz"]])
    struct.pack_into("<I", hdr, 24, total)
    hdr[28:2076] = cmd.ljust(2048, b"\x00")
    struct.pack_into("<I", hdr, 2100, st["dtbsz"])
    struct.pack_into("<Q", hdr, 2104, st["dtbaddr"])

    table = b""
    off = 0
    for f in frags:
        table += struct.pack("<III", len(f["data"]), off, f["type"])
        table += f["name"].encode().ljust(32, b"\x00") + b"\x00" * 64
        off += len(f["data"])
    struct.pack_into("<IIII", hdr, 2112, len(table), len(frags), 108, st["bcsz"])

    out = bytearray(al(st["hsz"]))
    out[:st["hsz"]] = hdr
    for f in frags:
        out += f["data"]
    out += b"\x00" * (al(len(out)) - len(out))
    out += st["dtb"]
    out += b"\x00" * (al(len(out)) - len(out))
    out += table
    out += b"\x00" * (al(len(out)) - len(out))
    out += st["bootconfig"]
    out += b"\x00" * (al(len(out)) - len(out))

    content = len(out)
    if a.pad_to:
        if content > a.pad_to:
            sys.exit(f"内容 {content}B 已超过 --pad-to {a.pad_to}")
        out += b"\x00" * (a.pad_to - content)

    with open(a.out, "wb") as fp:
        fp.write(out)

    print(f"cmdline : {cmd.decode()}")
    print(f"bootconfig({st['bcsz']}B): {st['bootconfig']!r}")
    for f in frags:
        print(f"frag type={f['type']} name={f['name'] or '-'} size={len(f['data'])}B")
    print(f"dtb: {st['dtbsz']}B")
    print(f"content {content}B"
          + (f" -> padded to {len(out)}B (zeros {len(out) - content}B)" if a.pad_to else " (no padding)")
          + f"  wrote {a.out}")


if __name__ == "__main__":
    main()
