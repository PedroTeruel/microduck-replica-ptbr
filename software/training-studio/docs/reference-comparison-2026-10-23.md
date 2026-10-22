# 与 kissqy 训练中控的对比 · 2026-10-23

参考仓库：[kissqy/Microduck-kissqy](https://github.com/kissqy/Microduck-kissqy)，本次核对提交 `525a215a19397767a073b782f57e97cf53683761`。检查了公开训练中控页面、说明和实际后端源码；没有运行对方训练程序，也没有将其代码并入本项目。

## 当前能用到哪一步

我们的本机演示流程已经实际通过：新建实验、短试跑、正式演示、暂停/继续/停止、持久记录、选定检查点评估、下载及续训、实验比较。Linux 进程控制经过真实 CPU 子进程和信号测试。

真实训练模式已在本机 WSL2 / RTX 5060 Ti 完成 64 环境、5 轮训练、视频评估、ONNX 导出及 PT/ONNX 推理一致性核对，详见 [验收记录](verification.md)。用户可以先在本机重复短试跑；目标云 GPU、长训练和真机仍未验收。演示模型、指标和回放不能证明策略已经学会动作。

## 主要差距

| 优先级 | kissqy 的实现 | 我们当前状态 | 应补的工作 |
|---|---|---|---|
| P0 真实训练验证 | 公开记录了冻结引擎的 CPU 物理步进、PPO 更新及 PT/ONNX 一致性验证；并明确保留 GPU 长训与真机验收限制 | 本机 GPU 的 64 环境、5 轮及产物核对已通过；缺目标云 GPU 验证 | 在 GPULab 重复训练 → 保存 PT → 策略回放 → 导出 ONNX → 同输入推理比对，保存证据 |
| P1 云端连接 | 页面配置 SSH、部署环境、建立端口转发；远端独立后台服务保存队列与成果 | 用户需手工准备依赖、运行服务和 SSH 转发；网页关闭可继续，但服务关闭会停止它拥有的任务 | 增加连接引导与可重连的执行服务，再做页面化环境准备 |
| P1 真实动作观察 | 能从正在训练的指定环境读取刚体姿态，也能启动 PT/ONNX 的交互式物理评估 | 三维区域是 CAD；策略效果在停止训练后通过 250 步检查点评估视频查看 | 分清模型外观、训练现场、检查点评估；先补可交互策略评估，再增加有开销控制的训练现场采样 |
| P1 导出验证 | ONNX checker、Runtime 推理、模型与固件的关节/观测/动作/频率及标定约定 | 已调用现有归一化导出器，打包来源和评估记录；本次样本通过独立推理核对，尚未内置每次导出后的推理检查和完整部署兼容检查 | 增加导出验证结果和具体失败原因；可下载不等于可部署 |
| P2 批次实验 | 队列保存入队时参数快照、顺序执行、失败处理；界面列出 14 类动作与 35 种配方 | 单个活动任务、两个 HD1910 配方、五项常用进阶数值 | 先做复制实验与顺序队列，再逐个扩展经过验证的动作配方 |
| P2 训练诊断 | GPU/显存/温度、预计剩余、分项奖励与课程信息 | 目前以迭代、奖励、回合长度、采样速度和日志为主 | 显示真实资源数据与分项奖励，说明停滞或失败原因；时间估算须标明估计 |

## 应保留的设计

- 默认简单、进阶折叠。对方将服务器、队列、物理参数、课程等集中在长页面，功能丰富；我们的新用户入口可以更专注。这个判断来自页面比较，不是用户可用性测试。
- 与机器人中控相同的浅灰外壳、鸭子标识、按钮和移动导航，减少两套工具之间的学习成本。
- 固定短试跑以及学习率、种子、档案的配置匹配检查。
- 真实训练进程暂停/继续。对方的暂停队列允许当前训练继续；另一组暂停/恢复用于仿真 viewer，不能把这些操作当作同一种能力。
- 实验对比、选定检查点的评估与续训、明确的演示标记和产物来源。

## 实施顺序

1. 先完成目标 GPU 的真实小任务闭环，定位环境与引擎接口问题。
2. 再补云端连接和交互式策略评估，让用户能看到自己训练出来的动作。
3. 完善导出后验证、模型与固件兼容检查。
4. 增加队列、诊断和更多经验证的配方；保留默认简单的界面。

此次对比没有启动付费云资源、修改镜像、复制对方代码或承诺训练收敛。参考仓库的原创部分声明个人非商业许可，后续如复用其代码需单独核对许可；本轮只分析交互和实现思路。

### 后续实现更新

同日后续已增加独立动作实验室、第三个 HD1910 单脚平衡实验配方，以及官方 V8 / kissqy V167 各 10 项预训练模型来源目录。目录提供版本、硬件与获取链接，不代表已导入本地评估或续训。新建训练仍从零开始；社区自有权重保留原发布方的许可，没有打包进本项目。

训练详情已增加真实 GPU 型号、利用率、温度、显存，CPU 型号、利用率和可用温度、内存读数，约 3 秒刷新。WSL 未暴露的 CPU 温度显示不可读。以上是执行端当前整体状态；分项奖励、课程、预计完成时间及历史资源曲线仍未实现。远端连接管理和自动安装也仍需另外实现。

## 代码与文档依据

- [项目训练说明](https://github.com/kissqy/Microduck-kissqy/blob/525a215a19397767a073b782f57e97cf53683761/microduck-hd1910/training-console/README.md)
- [真实训练、评估与导出](https://github.com/kissqy/Microduck-kissqy/blob/525a215a19397767a073b782f57e97cf53683761/microduck-hd1910/training-console/training/runtime_adapter.py)
- [训练现场采样](https://github.com/kissqy/Microduck-kissqy/blob/525a215a19397767a073b782f57e97cf53683761/microduck-hd1910/training-console/training/live_view.py)
- [SSH 部署与连接](https://github.com/kissqy/Microduck-kissqy/blob/525a215a19397767a073b782f57e97cf53683761/microduck-hd1910/training-console/training/remote_ssh.py)
- [独立远端服务](https://github.com/kissqy/Microduck-kissqy/blob/525a215a19397767a073b782f57e97cf53683761/microduck-hd1910/training-console/training/remote_server_boot.py)
- [训练后台保活](https://github.com/kissqy/Microduck-kissqy/blob/525a215a19397767a073b782f57e97cf53683761/microduck-hd1910/training-console/training/durable_manager.py)
- [队列快照与暂停语义](https://github.com/kissqy/Microduck-kissqy/blob/525a215a19397767a073b782f57e97cf53683761/microduck-hd1910/training-console/training/training_queue.py)
- [公开验证记录与未验证范围](https://github.com/kissqy/Microduck-kissqy/blob/525a215a19397767a073b782f57e97cf53683761/microduck-hd1910/training-console/docs/Verification.md)
