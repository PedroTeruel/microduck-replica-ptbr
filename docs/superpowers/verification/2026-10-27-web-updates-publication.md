# 20261027镜像与软件包公开发布

日期：2026-10-27（东京时间）。用户在本地交付和IMU代码核对后明确要求“推送，按最新，弄个镜像”。此授权覆盖推送源码、发布对应软件包和镜像；没有授权烧卡或让关闭的鸭子运动。

**公开发布完成：源码已推送master，镜像20261027设为Latest，软件2026.10.27另行发布；8个镜像附件和10个软件附件的服务器端大小/SHA256全部匹配。实际匿名更新目录、软件包下载/签名以及镜像校验文件/XZ文件头检查通过。两份Release均为draft=false、prerelease=false；本版实物验收仍待完成。**

## 版本与来源

- 源码集成推送：`762b0d44b784104aeb73c7b6bad10a25713daa44`，保留远端16项新文档提交；仅README有冲突，保留最新项目介绍再加入新版软件入口。
- 软件/镜像运行来源：`e382f0741d7dfe4e972605e2843474df7219cade`。发布树的Studio、duck-echo、updater、镜像安装脚本与该提交逐路径对照一致，无需重做同内容镜像。
- 两个发行标签均为附注标签，解引用到e382f074；不把后续文档提交冒充镜像构建来源。
- runtime源码`0791fcd44f71c705dc8bb0fbcde405593b52d19b`已通过GitHub提交API确认公开存在，robotd/步态模型/总线ID200 IMU支持保持20261023c版本。
- 原本本地的训练配方修改未进入本次公开发布树；`software/training`和`software/training-studio`与发布前origin/master相同。原本地分支和用户未跟踪文档保留。

## 发行入口与文件

| 发行 | 入口 | 附件与校验 |
| --- | --- | --- |
| 镜像20261027 | [镜像发行页](https://github.com/fanhao375/microduck-replica/releases/tag/microduck-replica-image-20261027) | 8个：xz、SHA256、清单、许可、模型、第三方、语音说明和README，全部服务器端摘要匹配，Latest读回正确。 |
| 软件2026.10.27 | [软件发行页](https://github.com/fanhao375/microduck-replica/releases/tag/microduck-software-v2026.10.27) | 10个：签名软件包/校验、manifest/签名、首次引导包/校验、公钥、Apache许可、语音说明和README，全部服务器端摘要匹配。 |

| 核心产物 | 字节数 | SHA256 |
| --- | --- | --- |
| `microduck-replica-20261027.img.xz` | 741604104 | `91ab5550e0f409d634722718a638d6e9615412b779b5d26c0af5c777056d0194` |
| `2026.10.27.software-update.tar` | 5683200 | `b6543c9f3a2ad6477106410dbed9753be9fa37c61b79ea0350767a18229d0e55` |
| `microduck-bootstrap-20261027.tar.gz` | 57811043 | `866f8d49e3097133ab911debda9c4fdc66b9f02b867a789aadfb9793b99b3610` |

全部资产明确逐个上传，不使用工作区通配。发行私钥不在附件中；Git仅包含发行公钥。中文语音说明文件经GitHub自动规范化为default.txt后，在草稿阶段核对内容hash并改为明确ASCII文件名`microduck-software-20261027-voice.txt`，再验证后公开。

## 发布核对

- 本地交付文件重新核对大小/hash、内外包签名和引导归档319个清单文件，通过。
- 原本地完整验证与独立审查见[构建验证](2026-10-27-web-updates.md)。发布合并仅改文档；运行文件与已验收冻结来源一致。合并后又运行Linux更新器18项及Studio更新HTTP5项，全部通过。
- GitHub两份标签指向、软件10附件的uploaded状态、大小和SHA256逐项检查通过。草稿资产URL含临时untagged路径，只在正式公开后检查稳定tag下载URL。
- 完整18附件和两个标签来源通过，Latest指向镜像20261027；实际已发布代码的匿名目录客户端能正确区分镜像和软件，识别2026.10.27并下载5,683,200字节软件包，hash及两份minisign签名通过。公开镜像SHA256文件与本地一致，Range读取返回正确XZ文件头。
- 公开验收快照见[release-assets.json](2026-10-27-release-assets.json)。镜像完整性由独立解压/逐文件只读验收与GitHub服务器端完整文件摘要共同验证，实物验收另行记录。

证据在工作区`artifacts/software-updates-20261027`的publication-assets.json、draft/public分阶段publication-verification.json及发行说明文件。原delivery.json的local_only=true保留为首次本地交付时的历史，不覆盖本次公开状态。

## 实物边界

鸭子关闭，本轮没有SSH安装、烧卡、机器人动作或云端请求。旧卡初次引导/升级/回退、新卡首次使用、真实掉电与真人声学仍待验收；发行页标题与正文明确说明。软件发行不是默认自动应用，镜像与组件包分开识别。

音乐头身实动尚未修复，自由AI人声对话未接入；原版实物坐站/录放成功不能替代本次组合镜像实物验收。发行说明第一段保留免费个人非商业复刻及模型许可边界。
