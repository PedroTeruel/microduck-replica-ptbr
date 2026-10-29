#  e  kissqy 训练 em 控 de 对比 · 2026-10-23

参考仓库：[kissqy/Microduck-kissqy](https://github.com/kissqy/Microduck-kissqy)，本次核对提交 `525a215a19397767a073b782f57e97cf53683761`。检查了公开训练中控页面、说明和实际后端源码；没有运行对方训练程序，也没有将其代码并入本项目。

## Atual能用到哪一步

我们 de 本机演示流程已经实际por meio de：新建实验、短试跑、正式演示、暂停/继续/停止、持久记录、选定Verificação点评估、Baixar e 续训、实验比较。Linux 进程Controle经过真实 CPU 子进程e信号Teste。

真实训练模式已在本机 WSL2 / RTX 5060 Ti Concluído 64 环境、5 轮训练、视频评估、ONNX 导出 e  PT/ONNX 推理一致性核对，详见 [验收记录](verification.md)。Usuáriopode先在本机重复短试跑；目标云 GPU、长训练e真机仍未验收。演示Modelo、指标e回放不能证明策略已经学会动作。

## 主要差距

| 优先级 | kissqy  de 实现 | 我们Atual状态 | 应补 de 工作 |
|---|---|---|---|
| P0 真实训练Validação | 公开记录了冻结引擎 de  CPU 物理步进、PPO Atualização e  PT/ONNX 一致性Validação；并明确Preservado GPU 长训 e 真机验收限制 | 本机 GPU  de  64 环境、5 轮 e 产物核对已por meio de；缺目标云 GPU Validação | 在 GPULab 重复训练 → 保存 PT → 策略回放 → 导出 ONNX → 同输入推理比对，保存证据 |
| P1 云端Conexão | PáginaConfiguração SSH、部署环境、建立端口转发；远端独立后台Serviço保存队列 e 成果 | Usuário需手工准备依赖、ExecuçãoServiçoe SSH 转发；Web关闭可继续，但Serviço关闭会停止它拥有 de 任务 | 增加Conexão引导 e 可重连 de 执行Serviço，再做Página化环境准备 |
| P1 真实动作观察 | 能从正在训练 de 指定环境Leitura刚体姿态，也能Inicialização PT/ONNX  de 交互式物理评估 | 三维区域是 CAD；策略效果在停止训练后por meio de 250 步Verificação点评估视频查看 | 分清Modelo外观、训练现场、Verificação点评估；先补可交互策略评估，再增加有开销Controle de 训练现场采样 |
| P1 导出Validação | ONNX checker、Runtime 推理、Modelo e Firmware de 关节/观测/动作/频率 e 标定约定 | 已调用现有归一化导出器，打包Fontee评估记录；本次样本por meio de独立推理核对，尚未内置每次导出后 de 推理VerificaçãoeCompleto部署兼容Verificação | 增加导出ValidaçãoResultadoe具体Falha原因；可Baixar不等于可部署 |
| P2 批次实验 | 队列保存入队时Parâmetros快照、顺序执行、Falha处理；界面列出 14 类动作 e  35 种配方 | 单个活动任务、两个 HD1910 配方、五项常用进阶数值 | 先做复制实验 e 顺序队列，再逐个扩展经过Validação de 动作配方 |
| P2 训练诊断 | GPU/显存/温度、预计剩余、分项奖励 e 课程信息 | atualmente以迭代、奖励、回合长度、采样速度e日志为主 | 显示真实资源Dados e 分项奖励，Instruções停滞或Falha原因；时间估算须标明估计 |

## 应Preservado de 设计

- 默认简单、进阶折叠。对方将Serviço器、队列、物理Parâmetros、课程等集 em 在长Página，功能丰富；我们 de 新Usuário入口pode更专注。这个判断来自Página比较，不是Usuário可用性Teste。
-  e 机器人 em 控相同 de 浅灰外壳、鸭子标识、按钮e移动导航，减少两套Ferramentas之间 de 学习成本。
- 固定短试跑e学习率、种子、档案 de Configuração匹配Verificação。
- 真实训练进程暂停/继续。对方 de 暂停队列允许Atual训练继续；另一组暂停/恢复usado para仿真 viewer，不能把这些操作当作同一种能力。
- 实验对比、选定Verificação点 de 评估 e 续训、明确 de 演示标记e产物Fonte。

## 实施顺序

1. 先Concluído目标 GPU  de 真实小任务闭环，定位环境 e 引擎接口问题。
2. 再补云端Conexãoe交互式策略评估，让Usuário能看到自己训练出来 de 动作。
3. 完善导出后Validação、Modelo e Firmware兼容Verificação。
4. 增加队列、诊断e更多经Validação de 配方；Preservado默认简单 de 界面。

此次对比没有Inicialização付费云资源、修改Imagem、复制对方代码或承诺训练收敛。参考仓库 de 原创部分声明Pessoal e não comercialLicença，后续如复用其代码需单独核对Licença；本轮只分析交互e实现思路。

### 后续实现Atualização

同日后续已增加独立动作实验室、第三个 HD1910 单脚平衡实验配方，eOficial V8 / kissqy V167 各 10 项预训练ModeloFonteDiretório。Diretório提供Versão、Hardware e 获取链接，不代表已导入本地评估或续训。新建训练仍从零开始；Comunidade自有权重Preservado原发布方 de Licença，没有打包进este projeto。

训练详情已增加真实 GPU 型号、利用率、温度、显存，CPU 型号、利用率e可用温度、内存读数，约 3 秒刷新。WSL 未暴露 de  CPU 温度显示不可读。以Superior是执行端Atual整体状态；分项奖励、课程、预计Concluído时间 e Histórico资源曲线仍未实现。远端Conexão管理e自动Instalação也仍需另外实现。

## 代码 e 文档依据

- [项目训练说明](https://github.com/kissqy/Microduck-kissqy/blob/525a215a19397767a073b782f57e97cf53683761/microduck-hd1910/training-console/README.md)
- [真实训练、评估与导出](https://github.com/kissqy/Microduck-kissqy/blob/525a215a19397767a073b782f57e97cf53683761/microduck-hd1910/training-console/training/runtime_adapter.py)
- [训练现场采样](https://github.com/kissqy/Microduck-kissqy/blob/525a215a19397767a073b782f57e97cf53683761/microduck-hd1910/training-console/training/live_view.py)
- [SSH 部署与连接](https://github.com/kissqy/Microduck-kissqy/blob/525a215a19397767a073b782f57e97cf53683761/microduck-hd1910/training-console/training/remote_ssh.py)
- [独立远端服务](https://github.com/kissqy/Microduck-kissqy/blob/525a215a19397767a073b782f57e97cf53683761/microduck-hd1910/training-console/training/remote_server_boot.py)
- [训练后台保活](https://github.com/kissqy/Microduck-kissqy/blob/525a215a19397767a073b782f57e97cf53683761/microduck-hd1910/training-console/training/durable_manager.py)
- [队列快照与暂停语义](https://github.com/kissqy/Microduck-kissqy/blob/525a215a19397767a073b782f57e97cf53683761/microduck-hd1910/training-console/training/training_queue.py)
- [公开验证记录与未验证范围](https://github.com/kissqy/Microduck-kissqy/blob/525a215a19397767a073b782f57e97cf53683761/microduck-hd1910/training-console/docs/Verification.md)
