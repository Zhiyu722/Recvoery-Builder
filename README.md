# Recvoery-Builder

通用 TWRP / OrangeFox 构建工作流，以及可复用的 `vendor_boot` 重打包工具。仓库不绑定任何机型、厂商或设备树路径。

## 包含内容

- `.github/workflows/TWRP-Recovery-Builder-zh.yml`：Android 8+ TWRP，支持 `recovery` / `boot` / `vendor_boot`。
- `.github/workflows/twrp_legacy_builder.yml`：Android <8 的旧版 TWRP。
- `.github/workflows/OrangeFox-Recovery-Builder.yml`：OrangeFox，支持 `recovery` / `boot` / `vendorboot`。
- `tools/`：解析、生成、校验、重打包 `vendor_boot` 的独立脚本。
- `prebuilt/vendor_boot_stock.img`：**仅作为示例**的原厂镜像（见 `prebuilt/README.md`），不会被自动使用。

## 工作流用法

在 Actions 页面手动运行，按目标机型填写：

| 输入 | 说明 |
| --- | --- |
| `device_tree_repo_url` / `DEVICE_TREE` | 设备树仓库地址（任意 git 仓库） |
| `device_tree_branch` / `DEVICE_TREE_BRANCH` | 设备树分支 |
| `device_tree_path` / `DEVICE_PATH` | 设备树在源码中的路径，如 `device/vendor/codename` |
| `build_target` / `BUILD_TARGET` | `recovery`、`boot` 或 `vendor_boot` / `vendorboot` |
| `vendor_boot_repack` / `VENDOR_BOOT_REPACK` | `auto`、`dual`、`single`、`off` |
| `stock_vendor_boot` / `STOCK_VENDOR_BOOT` | 原厂 `vendor_boot` 的 URL 或路径，可留空 |
| `vendor_boot_pad_to` / `VENDOR_BOOT_PAD_TO` | `auto`、`0` 或字节数 |
| `vendor_boot_permissive` / `VENDOR_BOOT_PERMISSIVE` | 是否追加 `androidboot.selinux=permissive` |

`vendor_boot` 目标只会在 `vendor_boot_repack != off` 时执行重打包。

### 原厂 vendor_boot 从哪里来

按以下顺序查找，找到即用：

1. 输入 `stock_vendor_boot` / `STOCK_VENDOR_BOOT`（`http(s)://` 会下载，其他值按路径处理）；
2. 设备树里的 `prebuilt/vendor_boot_stock.img`（推荐，跟随设备树版本走）；
3. 都没有：`auto` 退化为 `single`，`dual` 直接报错。

仓库自带的 `prebuilt/vendor_boot_stock.img` 不会参与自动查找；需要时请显式填写该路径，或设置 `USE_BUNDLED_STOCK=1`。

## vendor_boot 重打包模式

| 模式 | platform 片段 | recovery 片段 | 适用情况 |
| --- | --- | --- | --- |
| `dual` | 原厂 | 构建产物 | bootloader 支持多片段（header v4） |
| `single` | 构建产物 | 无（合并为 platform） | bootloader 只认单片段，或 `vendor_boot` 里只有 TWRP |
| `auto` | 有原厂镜像且构建产物含 recovery 片段时用 `dual`，否则 `single` | 同左 | 默认 |
| `off` | 不改动 | 不改动 | 构建产物已可直接使用 |

> 部分设备的 bootloader 会把 `vendor_boot` 里的多个片段拼成一个 initramfs，`dual` 会导致解压失败/无限重启；这类设备请用 `single`。

`auto` 在构建产物 platform 已非空且没有 recovery 片段时保持原样（`keep`），不会破坏正常构建。

## 工具

所有脚本只依赖 Python 3 标准库与 `lz4`、`cpio`，不读取机型常量。

```bash
# 查看镜像结构（header v3/v4 均可）
python3 tools/check_vendor_boot.py vendor_boot.img

# v3/v4 片段列表
python3 tools/extract_fragment.py vendor_boot.img --list
python3 tools/extract_fragment.py vendor_boot.img --type 2 --out recovery.lz4

# 用原厂镜像做模板，加入构建出的 recovery 片段
python3 tools/make_vendor_boot.py \
  --template stock_vendor_boot.img --recovery-lz4 recovery.lz4 \
  --pad-to 209715200 --out vendor_boot_fixed.img   # 换成目标分区字节数，0=不补

# 单片段：把 recovery ramdisk 作为 platform，丢掉其他片段
python3 tools/make_vendor_boot.py \
  --template vendor_boot.img --ramdisk-lz4 recovery.lz4 \
  --selinux-permissive --out vendor_boot_fixed.img

# 完整流程（自动选模式、自动补零、自动校验）
STOCK_VENDOR_BOOT=stock_vendor_boot.img \
DEVICE_TREE=device/vendor/codename \
MODE=auto PAD_TO=auto PERMISSIVE=1 \
bash tools/repack_vendor_boot.sh out/target/product/codename/vendor_boot.img
```

`make_vendor_boot.py` 还支持 `--fragment TYPE=PATH`（如 `--fragment dlkm=dlkm.lz4`）和 `--drop TYPE`，用于保留/替换原厂的其他片段。

## 约束

- 片段必须是 **lz4 legacy 帧**（`lz4 -l`），不是 modern frame。
- `platform` 片段里的内核模块必须与目标内核的 vermagic 匹配；换机型或换固件必须换原厂 `vendor_boot`。
- header v3 没有片段表，只能写入一个 ramdisk，`dual` 不可用。
- `PAD_TO=auto` 从设备树的 `BoardConfig.mk` 读取 `BOARD_VENDOR_BOOTIMAGE_PARTITION_SIZE`；读不到则不补零。
- 重打包前会备份为 `<image>.orig`（仅在不存在时创建），校验失败不会覆盖构建产物。
