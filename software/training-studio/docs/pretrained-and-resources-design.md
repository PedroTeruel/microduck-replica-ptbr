# 预训练ModeloDiretório e 执行端资源 · 2026-10-23

Usuário要求把 kissqy 已训练Modelo加入动作实验室，并核对Oficial V8；训练详情é necessário显示 GPU 型号、温度、显存、CPU  e 内存，e训练进度。沿用已确定 de 独立动作实验室e em 控风格，拆成两个可独立验收 de 改动。

## 预训练Modelo

动作实验室内区分训练配方 e 预训练Modelo。配方创建新实验；Modelo条目展示已有权重 de Fonte、Versão、Hardware、用途、格式、获取地址eValidação范围。por meio deFonte e 关键词筛选，详情解释Atual能力。界面不将外部权重伪装成本机已Concluído实验。

官方来源固定为 `pollen-robotics/microduck-policies` V8（`665ae4eb20bfe13bca1ef4ea6d4bb6b4a096e448`），manifest 明确 XL330、61 输入、14 输出、50 Hz。kissqy 固定为 `525a215a19397767a073b782f57e97cf53683761` 的 V167 发布清单，HD1910，包含源码中可见的 ONNX 与发布包内权重。模型获取链接指向原发布方，保留署名、版本与许可信息，不重新分发受个人非商业许可约束的模型。

Atual接入是可浏览e获取 de 现成ModeloDiretório。ONNX 没有Completo PPO 优化器e训练Verificação点，不能沿用现有“继续训练”；单纯 61→14 也不证明Comando、HOME、Servo动力学兼容。Página明确本地评估/续训未接入，不改写Atual机器人策略。增加收录只é necessário扩展Serviço端清单。

## Atual执行端资源

训练详情增加资源面板，通过独立只读 `/api/resources` 获取。后台懒启动、约每 3 秒缓存系统读数，GPU 探测有超时，不占训练锁，也不影响原 `/api/state` 的轮询。GPU 支持多卡，展示型号、负载、温度及显存；CPU 展示型号、核心、利用率、可读取的温度；内存展示已用/总量。轮次与吞吐量继续来自实际训练日志。

这些是执行端Atual整体读数。WSL CPU/内存是子系统可见范围，GPU 包含其他进程；查看已结束实验也不能当作Histórico占用。缺失温度或não suporta de 驱动字段返回 null e原因，初次采样 e Conexão em 断分别显示采样 em 、Dados过期，不伪造零占用。演示环境不生成虚构Hardware读数。

## 实施 e 验收

1. 新增 `training_studio/pretrained.py` 与受版本控制的模型清单；测试唯一 ID、固定来源、HTTPS、格式/硬件、不可续训和返回副本。接入 `state.pretrained_models`。
2. 新增 `training_studio/resources.py` 和 API；先测 CSV 空值/多卡、CPU 差分、内存、温度不可用、超时与缓存/关闭，再实现探测器。实读本机 WSL 的 NVIDIA 状态。
3. 新增 `web/pretrained.js`、`web/resources.js`，更新动作库和 RunView；测试查询与格式化逻辑，在桌面及 390/320 宽度验收来源筛选、详情、外链、空值、断线与资源显示。
4. 独立审查、Python/Node 回归 e 浏览器Testepor meio de后合入现用分支。只有原Serviço无活动任务时重启，Preservado所有实验。不触发训练、Modelo部署或付费云操作。
