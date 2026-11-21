# prebuilt/vendor_boot_stock.img

- **来源**：EEBBK X5 Pro（`ums9230_6h10_h280`，Android 14，UNISOC ums9230）设备上提取的**原厂** `vendor_boot`（slot a）。
- **尺寸**：27,906,048 B（已裁掉分区尾部零填充；原镜像 104,857,600 B 是整分区大小，内容有效部分只到 bootconfig 结束）。
- **整镜像 md5**：`1724e94cf9c00d8fe367db45710a3631`
- **platform 片段 md5**：`04ad5340d507e5dab55969316b21a490`（`check_vendor_boot.py --stock` 就拿这个比对）
- **bootconfig**：`androidboot.hardware=ums9230_6h10_h280\n`
- **cmdline**：`console=ttyS1,115200n8 bootconfig bootconfig`

## 用途

`tools/repack_vendor_boot.sh` 用这个文件提供：

1. `platform` 片段（正常启动用，**必须与原厂逐字节一致**，否则系统起不来）；
2. `bootconfig`（`androidboot.hardware`，丢了 `ro.hardware` 就错，init 找不到机型 rc）；
3. `dtb` 与 cmdline（含 `bootconfig` token）。

## 注意

- 换机型 / 换固件必须换这个文件，否则 platform 片段里的内核模块与新内核 vermagic 不匹配。
- 该文件**不要**放进设备树仓库，只放在 builder 仓库（体积 27 MB）。
