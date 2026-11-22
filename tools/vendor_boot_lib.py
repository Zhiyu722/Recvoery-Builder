"""Shared helpers for Android vendor_boot images (header v3 / v4).

Only standard AOSP layout is assumed:

  v3: header | vendor_ramdisk | dtb
  v4: header | fragments... | dtb | fragment table | bootconfig

Nothing in this module is device specific.
"""
import struct

MAGIC = b"VNDRBOOT"
TYPE_NAMES = {0: "none", 1: "platform", 2: "recovery", 3: "dlkm"}
NAME_TYPES = {v: k for k, v in TYPE_NAMES.items()}
ENTRY_SIZE = 108  # vendor_ramdisk_table_entry_v4
NAME_SIZE = 32
BOARD_ID_SIZE = 64


def align(x, page_size):
    return (x + page_size - 1) // page_size * page_size


def type_id(value):
    if isinstance(value, int):
        return value
    try:
        return int(value, 0)
    except (TypeError, ValueError):
        pass
    key = str(value).lower()
    if key in NAME_TYPES:
        return NAME_TYPES[key]
    raise ValueError(f"unknown fragment type: {value!r}")


class Image:
    def __init__(self):
        self.version = 0
        self.page_size = 4096
        self.header_size = 2128
        self.dtb_size = 0
        self.dtb_addr = 0
        self.cmdline = b""
        self.ramdisk_size = 0
        self.bootconfig = b""
        self.fragments = []  # dict(type, name, board_id, data)
        self.dtb = b""


def parse(data):
    if len(data) < 2112 or data[:8] != MAGIC:
        raise ValueError("not a vendor_boot image (bad magic or too short)")

    img = Image()
    img.version, img.page_size = struct.unpack_from("<II", data, 8)
    if img.version not in (3, 4):
        raise ValueError(f"unsupported vendor_boot header version {img.version}")
    if img.page_size < 2048 or img.page_size & (img.page_size - 1):
        raise ValueError(f"invalid page size {img.page_size}")

    ps = img.page_size
    img.header_size, img.dtb_size = struct.unpack_from("<II", data, 2096)
    img.dtb_addr = struct.unpack_from("<Q", data, 2104)[0]
    img.cmdline = data[28:2076].split(b"\x00")[0]
    ramdisk_size = img.ramdisk_size = struct.unpack_from("<I", data, 24)[0]

    min_header = 2112 if img.version == 3 else 2128
    if img.header_size < min_header:
        raise ValueError(f"header_size {img.header_size} < {min_header}")
    if img.header_size > len(data):
        raise ValueError("header_size beyond end of file")

    rd_off = align(img.header_size, ps)
    if rd_off + ramdisk_size > len(data):
        raise ValueError("vendor ramdisk beyond end of file")
    ramdisk = data[rd_off:rd_off + ramdisk_size]
    dtb_off = rd_off + align(ramdisk_size, ps)
    if dtb_off + img.dtb_size > len(data):
        raise ValueError("dtb beyond end of file")
    img.dtb = data[dtb_off:dtb_off + img.dtb_size]

    if img.version == 3:
        img.fragments = [{"type": 1, "name": "", "board_id": b"\x00" * BOARD_ID_SIZE,
                          "offset": 0, "data": ramdisk}]
        return img

    table_size, count, entry_size, bc_size = struct.unpack_from("<IIII", data, 2112)
    if entry_size < ENTRY_SIZE:
        raise ValueError(f"fragment entry size {entry_size} < {ENTRY_SIZE}")
    table_off = dtb_off + align(img.dtb_size, ps)
    if table_off + table_size > len(data):
        raise ValueError("fragment table beyond end of file")
    if count * entry_size > table_size:
        raise ValueError("fragment table smaller than entry_num * entry_size")

    for i in range(count):
        off = table_off + i * entry_size
        size, roff, ftype = struct.unpack_from("<III", data, off)
        name = data[off + 12:off + 12 + NAME_SIZE].split(b"\x00")[0].decode("ascii", "replace")
        board_id = data[off + 44:off + 44 + BOARD_ID_SIZE]
        if roff + size > len(ramdisk):
            raise ValueError(f"fragment {i} (type {ftype}) beyond vendor ramdisk")
        img.fragments.append({"type": ftype, "name": name, "board_id": board_id,
                              "offset": roff, "data": ramdisk[roff:roff + size]})

    bc_off = table_off + align(table_size, ps)
    if bc_off + bc_size > len(data):
        raise ValueError("bootconfig beyond end of file")
    img.bootconfig = data[bc_off:bc_off + bc_size]
    return img


def set_fragment(fragments, ftype, data, name=None):
    """Replace the first fragment of ftype (keeping its name/board_id), or append."""
    ftype = type_id(ftype)
    for frag in fragments:
        if frag["type"] == ftype:
            frag["data"] = data
            if name is not None:
                frag["name"] = name
            return frag
    frag = {"type": ftype, "name": name or "", "board_id": b"\x00" * BOARD_ID_SIZE,
            "data": data}
    fragments.append(frag)
    return frag


def drop_type(fragments, ftype):
    ftype = type_id(ftype)
    return [f for f in fragments if f["type"] != ftype]


def build(img, fragments, cmdline=None, pad_to=0):
    """Rebuild an image using img as header/dtb/bootconfig template."""
    ps = img.page_size
    cmd = img.cmdline if cmdline is None else cmdline
    if isinstance(cmd, str):
        cmd = cmd.encode()
    if len(cmd) >= 2048:
        raise ValueError("cmdline too long (>= 2048 bytes)")

    if not fragments:
        raise ValueError("no fragments to write")

    if img.version == 3:
        if len(fragments) != 1:
            raise ValueError("header v3 supports only one vendor ramdisk")
        ramdisk = fragments[0]["data"]
        total = len(ramdisk)
    else:
        total = sum(len(f["data"]) for f in fragments)

    hdr = bytearray(img.header_size)
    hdr[:8] = MAGIC
    struct.pack_into("<II", hdr, 8, img.version, ps)
    struct.pack_into("<I", hdr, 24, total)
    hdr[28:2076] = cmd.ljust(2048, b"\x00")
    struct.pack_into("<II", hdr, 2096, img.header_size, img.dtb_size)
    struct.pack_into("<Q", hdr, 2104, img.dtb_addr)

    table = b""
    if img.version == 4:
        off = 0
        chunks = []
        for f in fragments:
            chunks.append(struct.pack("<III", len(f["data"]), off, f["type"]))
            name = f.get("name", "").encode()[:NAME_SIZE].ljust(NAME_SIZE, b"\x00")
            board = (f.get("board_id") or b"")[:BOARD_ID_SIZE].ljust(BOARD_ID_SIZE, b"\x00")
            chunks.append(name + board)
            off += len(f["data"])
        table = b"".join(chunks)
        struct.pack_into("<IIII", hdr, 2112, len(table), len(fragments),
                         ENTRY_SIZE, len(img.bootconfig))

    out = bytearray(hdr)
    out += b"\x00" * (align(len(out), ps) - len(out))
    if img.version == 3:
        out += fragments[0]["data"]
    else:
        for f in fragments:
            out += f["data"]
    out += b"\x00" * (align(len(out), ps) - len(out))
    out += img.dtb
    out += b"\x00" * (align(len(out), ps) - len(out))
    if img.version == 4:
        out += table
        out += b"\x00" * (align(len(out), ps) - len(out))
        out += img.bootconfig
        out += b"\x00" * (align(len(out), ps) - len(out))

    content = len(out)
    if pad_to:
        if content > pad_to:
            raise ValueError(f"content {content}B exceeds pad target {pad_to}B")
        out += b"\x00" * (pad_to - content)
    return bytes(out), content


def platform_digest(data):
    """md5 of the platform fragment (v3: vendor ramdisk), None if absent."""
    import hashlib
    img = parse(data)
    for frag in img.fragments:
        if frag["type"] == 1:
            return hashlib.md5(frag["data"]).hexdigest()
    return None
