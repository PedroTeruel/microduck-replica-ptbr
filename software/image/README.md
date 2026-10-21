# Microduck 复刻镜像：构建脚本

> 用户看这份：[烧录和第一次使用](烧录和第一次使用.md)。下面是做镜像的人看的。

复刻镜像是一张烧好就能用的 SD 卡：我们 fork 的主程序、走路和动作模型、Microduck Studio、
首次开机（起名、认 IMU、建热点）和配网（连不上 WiFi 就开热点）都装好了。
这个目录是做这张卡的脚本：从一只调好的鸭子上只读地拉主程序和模型，装进底图，
清掉机器身份、日志和别人留下的东西，缩容压缩。

镜像免费下载，只供个人非商业复刻，**不随任何收费产品分发**：里面的模型是作者的个人非商业许可，
见 [`overlay/usr/share/doc/microduck/模型说明.txt`](overlay/usr/share/doc/microduck/模型说明.txt)。

## 镜像里有什么

| 组件 | 在镜像里的位置 | 从哪来 | 许可 |
|---|---|---|---|
| 系统底座 | `/` | Armbian 26.2.1（Debian 13）、内核 6.1.115-vendor-rk35xx、Radxa 的 U-Boot | 各包自有，`/usr/share/doc/<包>/copyright` |
| 官方运行时 0.15.1 | `/opt/robot/daemon/`、`/usr/local/bin/robotctl` | Pollen Robotics，源码提交 1fa8438，底图里自带 | Apache-2.0 |
| 主程序 robotd、padd、mediad | `/opt/robot/feetech-ft5-r5/` | 我们的 fork（官方 0.15.1 + 飞特总线、I²C IMU 模块、陀螺融合、UDP 手柄），从调好的鸭子上拉 | Apache-2.0 |
| ONNX Runtime 1.28.0 | `/opt/robot/feetech-ft5-r5/onnxruntime/` | Microsoft，原样 | MIT |
| 走路和动作模型 10 个 | `/opt/robot/feetech-ft5-r5/models/`、`roller/` | 社区作者训练，从调好的鸭子上拉，删掉了训练归档 | 个人非商业 |
| Microduck Studio | `/home/radxa/studio-dev/`，服务 `microduck-studio`，端口 8000 | [`../studio/`](../studio/)，只装运行文件 | Apache-2.0 |
| 首次开机、配网、root 小助手 | `/usr/local/sbin/microduck-firstboot`、`microduck-netcheck`、`microduck-helper` | [`overlay/`](overlay/)、Studio 的 `deploy/` | Apache-2.0 |
| 出厂标定 | `/etc/robot/feetech-ft5/hd1910-calibration.toml` | [`calib/hd1910-calibration.option-a.toml`](calib/hd1910-calibration.option-a.toml)：15 颗都是 2048 / −1 / 未标定 | — |

每部分的许可全文在镜像里的 `/usr/share/doc/microduck/`，构建时也拷到输出目录随发布一起放出去。

出厂时几个跟二号鸭不一样的地方：

- **主程序跑标定模式**（`robotd.service.d/zzzz-zz-microduck-commissioning.conf` 给它加 `--commissioning`）。
  没标定的鸭子只有在标定模式下才能读 IMU、做 IMU 粗校、看到 15 颗的标定；上手清单第 3 步
  「写进主程序」成功后，root 小助手删掉这个文件，主程序回到运动模式。
- **摄像头默认用测试画面**（官方配置 `/etc/robot/robotd.toml` 的 `[media] source = "test"`），
  没接摄像头的鸭子 mediad 不会反复崩。
- **radxa 默认密码 `microduck`**，root 锁着，SSH 只认钥匙。
- 手柄键位、走路参数沿用二号鸭的 `robotd.toml`（动作幅度 0.7、摔倒不自动卸力、电池没电不自动关机）。

## 准备输入

### 1. 底图

`microduck-zero3w-0.15.1-R1-V112.img`：在社区公开的 R1 镜像上，用 `tools/radxa/` 里的 R1 转换脚本
（参数 `--no-tof --overlay i2c4-m0`）改出来的：换 Radxa 的 U-Boot 和 B1 设备树、打开 I²C4（27/28 脚）
给 IMU 模块用。底图里已经有官方运行时 0.15.1。20261020、20261021 两版用的底图
sha256 都是 `652dd54e70f49fd3633058d5ed9bbb2f63b435648da2346dfbfa60fcaa4c5bcc`。

以后打算换成干净的 Armbian + 官方安装器做底图，就不用依赖别人的镜像了。

### 2. payload（从一只调好的鸭子上拉）

这只鸭子要装好我们 fork 的主程序，并且已经能走：

- `/opt/robot/feetech-ft5-r5/` 下有 `robotd`、`padd`、`mediad`、`onnxruntime/`、`models/`、`roller/`；
- `/etc/systemd/system/robotd.service.d/zzzz-r17-0151.conf`（主程序的启动参数，不能带 `--commissioning`）；
- `/etc/robot/feetech-ft5/robotd.toml`（拉的时候会自动去掉本机的 IMU 接线，声音包指回官方的）。

拉的东西是白名单，只读，不改鸭子上任何文件：

```sh
# 电脑上：把脚本拷过去
scp capture-payload.sh radxa@<鸭子 IP>:/tmp/
# 鸭子上
sudo sh /tmp/capture-payload.sh /tmp/microduck-payload.tgz
# 电脑上：拉回来
scp radxa@<鸭子 IP>:/tmp/microduck-payload.tgz .
```

20261020 那一版是从二号鸭拉的，payload 的 sha256 `9e1e64b8…`。里面的 robotd（sha256 `9b734239…`）
是 10-15 在 fork 的工作区里编的，**不完全等于**哪一个提交（之前这里写成 `a844db6`，不对）。

20261021 那一版用的还是这份 payload，只把 robotd 换成 fork `hd1910-v167-imu-autodetect` 分支
提交 `f4bbe53` 编的 arm64 版（sha256 `0a6a86b2…`，fork 的地址见首页「软件」一节），
`payload.json` 里 robotd 那一条的 sha256 跟着改；换完的 payload sha256 `26252fbc…`。
以后的 robotd 都从提交编，对得上源码。

### 3. 构建机

WSL 的 Ubuntu 22.04 或任意 Linux，要 root（loop 设备）：

```sh
sudo apt install fdisk e2fsprogs xz-utils openssl python3.11
```

脚本要 Python 3.11 以上（用 `tomllib`）。Ubuntu 22.04 自带的 `python3` 是 3.10，
装了 python3.11 以后让 `python3` 指向它，比如建一个只放这一个链接的目录、加到 `PATH` 最前面。

## 构建

```sh
sudo STUDIO_VERSION=<Studio 的提交号> IMAGE_VERSION=<本目录的提交号> \
    sh build-image.sh /path/to/microduck-zero3w-0.15.1-R1-V112.img \
    /path/to/microduck-payload.tgz ../studio ~/microduck-out
```

- `OUT_DIR` 不能放在 `/mnt` 下：WSL 的 Windows 盘上 loop 很慢、权限也不对；用 `~/microduck-out`。
- 只给自己的验收卡用：`DEV_AUTHORIZED_KEY="$(cat 某把.pub)"` 会把这把公钥写进 radxa 的
  `authorized_keys`，测出问题能直接远程改，不用重烧卡，镜像清单里会注明。**正式发布绝对不要设**：
  那等于给所有用户的鸭子留了一扇后门。
- 版本号不给的话脚本自己用 `git rev-parse`（有未提交改动加 `-dirty`），拿不到就写「未知」。
  WSL 里读 Windows 盘上的 git worktree 常常拿不到，所以发布时自己传。
- 镜像文件名默认是 `microduck-replica-日期.img.xz`；同一天出第二版时传 `IMAGE_TAG=20261021b` 这样的名字（只能数字和小写字母）。
- 大约 10 分钟。产出：
  - `microduck-replica-YYYYMMDD.img.xz` 和同名 `.sha256`；
  - `镜像清单.txt`：底图和 payload 的 sha256、删了什么、加了什么；
  - `开源许可.txt`、`第三方.txt`、`模型说明.txt`；
  - `work.img`：总是保留，确认无误后手工删。

单独的检查入口（不需要 root）：

```sh
sh build-image.sh --selftest                 # GPT / MBR 分区行改写
sh capture-payload.sh --clean-toml IN OUT    # robotd.toml 清理函数
sh apply-rootfs.sh ROOT PAYLOAD ../studio ./overlay   # 在假目录树上试装（ROOT 不能是 /）
```

## 测试

```sh
# WSL root 下跑全（有几条要 root 才能验属主和权限）
python3 -I -m unittest discover -s tests -v
sh -n apply-rootfs.sh && sh -n build-image.sh && sh -n capture-payload.sh
```

Windows 上用 `py -3.13 -I -m unittest discover -s tests -v` 也能跑（Git Bash 的 sh），权限那条会跳过。

## 脚本自己会拦住的事

构建过程中下面任何一条不满足就停下，并写清卡在哪一步、怎么办：

- payload 里每个文件的 sha256 跟清单对不上、有清单外的文件、有符号链接；
- overlay、Studio 的 `deploy/`、`run.py` 里有 Windows 换行（CR）：
  Windows 上 clone 时 `core.autocrlf=true` 会把没后缀的脚本变成 CRLF，开机就跑不起来。
  仓库的 `.gitattributes` 已经给这些目录定了 LF；
- 镜像里任何文件（包括二进制）还有模型作者的名字（只有 `模型说明.txt` 例外，那里按许可要署名）；
- `etc/systemd`、`udev`、`cron` 里有悬空链接，或者还引用着已删掉的文件；
- `opt/robot/feetech-ft5-r5` 下还有训练归档（`export-data.zip`、`training-*.json`、`upstream-params`、`*.pt`）；
- 「待人工确认」里还有普通文件（要先确认不含个人数据，再用 `ALLOW_UNCONFIRMED=1` 放行，清单里会注明）；
- 官方声卡初始化（`aic3104-init`）不全。

另外：所有删除都先打印再删；所有写入都走 `safe_dir` / `safe_file`，ROOT 里指向外部的符号链接会让脚本失败，
不会写坏宿主机；`apply-rootfs.sh` 不碰 loop 设备、不 chroot。

## 发布前核对

1. 测试全过（WSL root）。
2. 用提交好的代码构建，`STUDIO_VERSION`、`IMAGE_VERSION` 写提交号，日志里没有 `ALLOW_UNCONFIRMED` 放行。
3. 把交付的 `.img.xz` 解压回来、只读挂载，至少看：sha256 对得上；`e2fsck -fn` 没错；
   主程序和模型的 sha256 跟 payload 一致、`robotd.toml` 引用的模型都在；
   标定模式 drop-in 在；`machine-id` 是空的、没有 SSH 主机钥匙；SSH 只认钥匙；
   全盘只有 `模型说明.txt` 带模型作者的名字。
4. 新卡在真鸭子上从头走一遍[烧录和第一次使用](烧录和第一次使用.md)：热点 → 配网 → 上手清单 6 步 → 站起来走。
5. 镜像里主程序对应的 fork 提交已经推到 fork 上。
6. 发布：GitHub Releases 放 `.img.xz`、`.sha256`、`镜像清单.txt` 和三份 txt；
   Release 说明第一段写「免费、只供个人非商业复刻、不随收费产品分发」。
