# 飞特舵机调试软件

配 ID、改参数、拉滑杆看舵机转。这里保留 Windows 调试软件和旧驱动副本，另提供官方驱动、串口助手及最新资料入口。

| 文件 | 干什么 | 版本 | 大小 |
|---|---|---|---|
| [FD1.9.8.5(250729).7z](FD1.9.8.5%28250729%29.7z) | **FD 调试软件**。配 ID、开过流过压保护、拉滑杆测舵机 | 1.9.8.5（2025-07-29），中英文可切换 | 167 KB |
| [CH340_URT.rar](CH340_URT.rar) | **旧版 CH340 驱动副本**。适用于对应转接芯片；URT-2 的 CH343 驱动见下方官方入口 | — | 224 KB |

## 装法

```
1  插 URT-2 → 设备管理器「端口」里出现 USB-Enhanced-SERIAL CH343 (COMx)，记下号
   没出现先核对转接芯片型号，再从下面的官方入口选对应驱动
2  解压 FD1.9.8.5(250729).7z → 直接运行，不用安装
3  FD 里选那个 COM 口 → 波特率 1000000 → 点「打开」→ 点「搜索」
```

搜到舵机就通了。**怎么飞线、怎么供电、配 ID、改哪些参数、ID 对照表** —— 全在 [调试记录 · 舵机配置](../../调试记录.md#舵机配置--拿到货一步一步做)，一步一步。

## 驱动与串口助手

| 官方入口 | 用途 |
|---|---|
| [CH343SER.ZIP](https://gitee.com/ftservo/fddebug/blob/master/CH343SER.ZIP) | URT-2 等 CH343 转接板；系统已自动识别时无需另装 |
| [CH341SER.ZIP](https://gitee.com/ftservo/fddebug/blob/master/CH341SER.ZIP) | 对应 CH340 / CH341 芯片的转接板 |
| [UartAssist.zip](https://gitee.com/ftservo/fddebug/blob/master/UartAssist.zip) | 通用串口收发助手，按设备协议收发文本或十六进制数据 |

2026-10-25 核对官方仓库，FD 1.9.8.5 仍列为稳定版本。后续版本以[飞特官方仓库](https://gitee.com/ftservo/fddebug)为准；协议、内存表和 SDK 见[飞特资料索引](../../docs/飞特资料/README.md)。

## 来源与校验

从飞特官方 Gitee 仓库 [gitee.com/ftservo/fddebug](https://gitee.com/ftservo/fddebug) master 分支原样复制（2026-09-11），**MIT 许可**（`LICENSE` 同目录）。

```
sha256
FD1.9.8.5(250729).7z   33b92ac03ff048238bb6455a96aec98e97f6c87a97903ac197406f6d937c7734
CH340_URT.rar          546aaf96a54647f7a3ddd7e21389d64be2d198926c6058d8b19ee90e9eea4e17
```

怀疑文件坏了就 `sha256sum` 一下对这两行。

**为什么放进仓库**：Gitee 有时要登录才能下、有时改目录结构，clone 下来的人不该再去找。MIT 允许原样分发。
**要更新**：去上面那个仓库拿新版，换文件、改这里的版本号和哈希、改 [NOTICE](../../NOTICE.md) 里的版本。

## 网页调试台

FD 只能在 Windows 上跑。装到板子上或者想看 3D 模型跟着动，用 [`../servo-web/`](../servo-web/)：`python server.py --port COM5`，浏览器打开就能拖，还能一键导出 0–90 全部寄存器。
