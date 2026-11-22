# prebuilt/vendor_boot_stock.img（示例）

本文件只是 **EEBBK X5 Pro** 的原厂 `vendor_boot` 示例，用来演示和离线验证工具，
**不会被任何工作流或脚本自动使用**。构建其他机型时请提供对应机型的原厂镜像。

- **来源**：EEBBK X5 Pro（`ums9230_6h10_h280`，UNISOC ums9230）
- **尺寸**：27,906,048 B（已裁掉分区尾部零填充；整分区为 104,857,600 B）
- **整镜像 md5**：`1724e94cf9c00d8fe367db45710a3631`
- **platform 片段 md5**：`04ad5340d507e5dab55969316b21a490`
- **bootconfig**：`androidboot.hardware=ums9230_6h10_h280\n`
- **cmdline**：`console=ttyS1,115200n8 bootconfig bootconfig`

## 为其他机型提供原厂镜像

推荐把文件放到设备树仓库：

```
<device_tree>/prebuilt/vendor_boot_stock.img
```

工作流会优先读取这里，其次读取输入 `stock_vendor_boot` 指定的 URL/路径。
也可以显式传入：

```bash
STOCK_VENDOR_BOOT=prebuilt/vendor_boot_stock.img bash tools/repack_vendor_boot.sh ...
```

或者设置 `USE_BUNDLED_STOCK=1` 允许回退到本目录的示例文件（只适合 X5 Pro）。

## 为什么需要它

`vendor_boot` 重打包会用原厂镜像提供：

1. `platform` 片段（正常启动用，必须与原厂一致，否则系统起不来）；
2. `bootconfig`（`androidboot.hardware` 丢失会导致 init 找不到机型配置）；
3. `dtb` 与 cmdline（含 `bootconfig` token）。

换机型 / 换固件必须换这个文件，否则 platform 片段里的内核模块与新内核
vermagic 不匹配。文件体积约 27 MB，可以放在设备树仓库或构建时下载。
