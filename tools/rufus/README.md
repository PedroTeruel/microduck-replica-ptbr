# Rufus · Windows 烧卡Ferramentas

[返回Índice de ferramentas](../README.md) · [Gravaçãoe第一次使用](../../software/image/Gravaçãoe第一次使用.md)

usado para把鸭子ImagemGravação microSD 卡。aqui提供Oficial原版 **Rufus 4.15 便携版，Windows x64**，无需Instalação。

**[下载 rufus-4.15p.exe](rufus-4.15p.exe)** · [官方发布页](https://github.com/pbatard/rufus/releases/tag/v4.15) · [其他平台与新版](https://rufus.ie/zh/)

## 烧卡步骤

1. 下载鸭子的 `.img.xz` 镜像，将 microSD 卡插入读卡器并连接电脑。
2. 打开 Rufus，在「设备」 em 核对 SD 卡 de 容量e盘符。**Gravação会清空所选卡 de Dados。**
3. 点击「选择」，选中镜像文件。若文件筛选器没有显示 `.img.xz`，切换为所有文件。
4. 核对目标卡后点击「开始」，等待状态回到「准备就绪」，再安全弹出读卡器。
5. Windows 提示格式化 Linux 分区时点「取消」。把卡插回鸭子，继续[首次开机 e 配网](../../software/image/Gravaçãoe第一次使用.md#3-第一次开机)。

## Fonte e 校验

2026-10-25 核对Oficial发布。EXE  e  GitHub 发布资产 SHA256 一致，Windows 数字签名有效，签名者为 Akeo Consulting；BaixarArquivo未经修改。

| Arquivo | 用途 |
|---|---|
| [rufus-4.15p.exe](rufus-4.15p.exe) | Windows x64 便携版 |
| [rufus-4.15-source.zip](rufus-4.15-source.zip) | 同Versão de Oficial源代码，Preservado构建Arquivo e 各组件Licença |
| [LICENSE.txt](LICENSE.txt) | Rufus  de  GPL-3.0-or-later Licença |
| [SHA256SUMS.txt](SHA256SUMS.txt) · [SOURCE.json](SOURCE.json) | 校验值、BaixarFonteeVersão记录 |

在 PowerShell 中运行 `Get-FileHash .\rufus-4.15p.exe -Algorithm SHA256`，与 `SHA256SUMS.txt` 对照即可核对文件。

Rufus 作者为 Pete Batard / Akeo Consulting，源码与更新由 [pbatard/rufus](https://github.com/pbatard/rufus) 维护。
