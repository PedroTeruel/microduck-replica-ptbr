# 动作实验室：单脚平衡

日期：2026-10-23。Usuário已授权在现有训练台内实现首个零代码动作玩法。

## Usuário流程

按用户最后明确的布局，动作实验室是同一训练台内的独立页面 `#/actions`，在左侧导航和手机底栏中与训练工作台并列。首页保留浏览入口。配方库先收录现有平地行走、起伏地形、单脚平衡，支持搜索、按类别筛选，以及预览和文字说明。选择配方后进入现有新建训练抽屉，不另建产品或服务器。

单脚平衡用户选择支撑脚（机器人自身左/右）、另一只脚抬高多少、保持多久；进阶训练参数仍折叠。配方卡从后端 `catalog` 元数据读取类别、标签、预览类型、来源和验证状态；一次只加载正在查看的三维预览，避免配方增多后同时创建大量 WebGL 场景。文字说明同样是完整的卡片类型，不要求每个配方都有视频。

三维目标示意展示EsquerdoDireito脚e抬脚方向，并标注「目标示意 · 非训练Resultado」。绘图不宣称精确运动学或平衡Validação。已创建实验保存动作Parâmetros，Parâmetros只读；复制实验或短试跑转正式训练沿用Parâmetros。修改动作目标é necessário新 de 匹配短试跑。实际策略效果只来自选定Verificação点 de 物理评估视频。

## 固定接口

- 配方 `hd1910-single-leg`，任务 `Mjlab-Balance-Flat-MicroDuck-HD1910`，实验目录 `microduck_hd1910_balance`。
- 请求及记录新增 `skill` 对象：`support_side` 为 `left/right`；`lift_height_m` 为 0.005–0.02、默认 0.01；`hold_seconds` 为 1–5、默认 3。拒绝布尔数值、非有限值、未知字段、行走配方夹带技能参数。
- 配方元数据增加 `experiment_name`；单脚配方提供 `skill_defaults` 和 `skill_limits`，前端按后端范围展示厘米与秒。新配方默认 256 环境、1000 轮、25 轮保存；短试跑仍强制 64 环境、5 轮、每轮保存。
- 动作参数加入短试跑匹配、恢复、导出来源及评估。旧行走记录没有 `skill` 时保持兼容；不接受任意任务名、路径或命令片段。
- 每个配方 de 日志Diretório从Serviço端白名单取得，训练日志识别、PT 扫描、恢复Caminho、评估/导出Verificação点校验必须一致。

## 训练引擎

从 HD1910 速度Configuração深拷贝，Preservado Feetech BAM、61 维观测、14 维动作、50 Hz、NaN 防护 e 匹配物理随机化。新增专属Comando、奖励e阶段进度；删除会抵消抬脚或改写Comando de 步态奖励/课程。EsquerdoDireito只训练所选支撑脚，不启用无条件Imagem损失。

动作包括稳定、抬脚、保持、落脚、双脚稳定结束；Completo周期eParâmetros随实验固定。奖励 e Sucesso判断必须Verificação正确支撑脚、抬脚高度、躯干姿态、滑移、禁用身体接地、落脚恢复，防止跌倒后脚离地骗取奖励。新Comando语义另行记录，不能仅因输入输出维度相同就声称旧机器人Execução时可直接使用。

训练 CLI 使用类型化ComandoConfiguração字段传递Parâmetros；评估、导出在创建环境前用同一校验函数应用保存Parâmetros。Preservado现有归一化导出Caminho，不改依赖锁Arquivo，不改变既有Caminhada配方行为。

## 验收

1. CPU Configuração/奖励Teste：范围、EsquerdoDireito映射、阶段边界、终止/Sucesso门控、有限值、61/14/50 契约、旧工厂隔离；Verificação候选姿态e几何能suporta目标。
2. Serviço回归：匹配短试跑、旧记录、配方隔离Caminho、错误Parâmetros、暂停/续训、导出Parâmetros e Fonte。
3. 前端：草稿、单位换算、EsquerdoDireito切换、短试跑门禁、复制、Resultado展示 e 移动布局。目标示意不得成为评估凭证。
4. 真实 GPU：64 环境 5 轮、保存 PT、按Completo周期多次评估、真实视频、导出 ONNX 并核对推理。记录实际Sucesso次数；训练退出Sucesso不等同于动作Sucesso。
5. 集成回稳定工作区，Preservado既有实验eServiço状态。只在没有活动任务时重启Serviço。

## 边界

首版Concluído单脚平衡可Configuração训练闭环。跳跃、精准转圈不显示为可Execução模板。长训收敛e真机效果依据实际证据报告，不由示意动画或短试跑por meio de替代。

## 后续定位：Comunidade动作配方库

Usuário进一步明确：动作实验室应承载ComunidadeAutor编写 de 动作任务，让普通Usuário选择并训练，不要求每个人从零写奖励代码。首版单脚平衡是这一流程 de Completo样例。Comunidade发布、审核、Baixar e 自动Instalação尚未实现。

规划 em  de 配方应包含：Autor e Fonte、Licença、配方Versão、适配Hardware e 引擎Versão、动作Instruções、可调整Parâmetros e 范围、训练规则、Sucesso e Falha判定、评估条件e示例视频。Parâmetros应同时进入训练、续训、评估 e 导出，Usuário修改目标后Preservado自己 de 实验记录。

Contribuição流程优先走仓库 PR：Autor实现任务eTeste → 维护者审核兼容性 e Validação证据 → 收录为可选择 de 配方 → Usuário短试跑后正式训练。Atual仍由Serviço端白名单注册任务；未来Página不能把任意Enviar脚本直接当作已经审核 de 内置能力。

配方卡 de Validação状态需分别表达「训练链路por meio de」「在指定条件InferiorConcluído动作」「经过真机Validação」。一次Sucesso退出或几轮短试跑不能升级为动作已经学会。已有策略权重是可选 de 独立成果，注明Fontee对应目标，不 e 训练配方混为一谈。

Página后续按配方元Dados渲染卡片 e Parâmetros表单，逐步减少动作名称硬编码。先稳定配方约定eContribuição样例，再建设分享入口；本轮没有新建账号、EnviarServiço或Comunidade后台。
