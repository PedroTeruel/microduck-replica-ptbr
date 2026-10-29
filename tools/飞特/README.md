# 飞特ServoDepuraçãoSoftware

配 ID、改Parâmetros、拉滑杆看Servo转。aquiPreservado Windows DepuraçãoSoftwaree旧驱动副本，另提供Oficial驱动、串口助手 e 最新资料入口。

| Arquivo | 干什么 | Versão | 大小 |
|---|---|---|---|
| [FD1.9.8.5(250729).7z](FD1.9.8.5%28250729%29.7z) | **FD DepuraçãoSoftware**。配 ID、开过流过压保护、拉滑杆测Servo | 1.9.8.5（2025-07-29）， em 英文可切换 | 167 KB |
| [CH340_URT.rar](CH340_URT.rar) | **旧版 CH340 驱动副本**。适usado para对应转接芯片；URT-2  de  CH343 驱动见Inferior方Oficial入口 | — | 224 KB |

## 装法

```
1  插 URT-2 → 设备管理器「端口」里出现 USB-Enhanced-SERIAL CH343 (COMx)，记下号
   没出现先核对转接芯片型号，再从下面的官方入口选对应驱动
2  解压 FD1.9.8.5(250729).7z → 直接运行，不用安装
3  FD 里选那个 COM 口 → 波特率 1000000 → 点「打开」→ 点「搜索」
```

搜到Servo就通了。**怎么飞线、怎么供电、配 ID、改哪些Parâmetros、ID 对照表** —— 全在 [Registro de depuração · ServoConfiguração](../../Registro de depuração.md#ServoConfiguração--拿到货一步一步做)，一步一步。

## 驱动 e 串口助手

| Oficial入口 | 用途 |
|---|---|
| [CH343SER.ZIP](https://gitee.com/ftservo/fddebug/blob/master/CH343SER.ZIP) | URT-2 等 CH343 转接板；系统已自动识别时无需另装 |
| [CH341SER.ZIP](https://gitee.com/ftservo/fddebug/blob/master/CH341SER.ZIP) | 对应 CH340 / CH341 芯片的转接板 |
| [UartAssist.zip](https://gitee.com/ftservo/fddebug/blob/master/UartAssist.zip) | 通用串口收发助手，按设备协议收发文本或十六进制数据 |

2026-10-25 核对官方仓库，FD 1.9.8.5 仍列为稳定版本。后续版本以[飞特官方仓库](https://gitee.com/ftservo/fddebug)为准；协议、内存表和 SDK 见[飞特资料索引](../../docs/飞特资料/README.md)。

## Fonte e 校验

从飞特官方 Gitee 仓库 [gitee.com/ftservo/fddebug](https://gitee.com/ftservo/fddebug) master 分支原样复制（2026-09-11），**MIT 许可**（`LICENSE` 同目录）。

```
sha256
FD1.9.8.5(250729).7z   33b92ac03ff048238bb6455a96aec98e97f6c87a97903ac197406f6d937c7734
CH340_URT.rar          546aaf96a54647f7a3ddd7e21389d64be2d198926c6058d8b19ee90e9eea4e17
```

怀疑文件坏了就 `sha256sum` 一下对这两行。

**为什么放进仓库**：Gitee 有时要登录才能Inferior、有时改Diretório结构，clone Inferior来 de 人不该再去找。MIT 允许原样分发。
**要Atualização**：去Superior面那个仓库拿新版，换Arquivo、改aqui de Versão号e哈希、改 [NOTICE](../../NOTICE.md) 里 de Versão。

## WebDepuração台

FD 只能在 Windows 上跑。装到板子上或者想看 3D 模型跟着动，用 [`../servo-web/`](../servo-web/)：`python server.py --port COM5`，浏览器打开就能拖，还能一键导出 0–90 全部寄存器。
