# 收录一个动作配方

动作实验室是训练台内 de 配方库。Atual由仓库维护者por meio de代码 e  PR 收录任务，Usuário在Página选择配方、设置Parâmetros并训练。WebEnviar、远程Baixar、自动InstalaçãoeComunidade账号系统尚未实现。

## Autor交付什么

一份可收录 de 动作配方é necessário同时提供：

1. 动作目标、起始状态、结束状态 e Falha条件。
2. 适配 de 机器人Modelo、Servoe引擎Versão。
3. 真实注册 de 训练任务、奖励 e 终止规则、合理默认值e独立实验Diretório。
4. 可修改Parâmetros de 类型、范围 e 单位；Parâmetros必须贯通训练、续训、评估、导出。
5. Completo周期评估方法 e Sucesso判定；不可用累计奖励直接代替动作是否Concluído。
6. Teste、短试跑记录、original视频 e 已知限制。没有实际回放时pode先提供文字Instruções。
7. Autor、源码Fonte、LicençaeVersão信息。训练好 de 权重作为独立可选成果，注明对应配方 e 目标。

## Atual收录位置

引擎任务位于 `software/training/src/mjlab_microduck/tasks/`，在任务注册表中登记。训练台使用 `software/training-studio/training_studio/config.py` 的服务端白名单，不接受页面直接执行任意任务名或脚本。

现有单脚平衡样例包括 `balance_parameters.py`、`microduck_balance_env_cfg.py`、相关 `mdp.py` 函数及测试。新增其他类型的动作，需要实现适合它的参数校验与 CLI 传递，不能直接套用单脚平衡的三个字段。

每个配方的 `catalog` 元数据决定动作实验室的展示：

| 字段 | 用途 |
| --- | --- |
| `category` | 页面分类，例如行走、平衡 |
| `tags` | 搜索用标签 |
| `preview_kind` | 当前支持 `robot_model`、`balance_target`、`text` |
| `source_label` | 当前卡片来源说明，不代替源码署名与许可证 |
| `verification_state` / `verification_label` | 验证状态及用户可读标签 |
| `instructions` | 这个动作的简要步骤或目标说明 |

三维Modelo或目标示意都必须注明非训练Resultado。未来增加视频/图片预览类型时，é necessário一起记录实际策略、目标、条件 e Fonte，不能把演示动画显示为训练Sucesso de 视频。

## 怎么审核 e 展示Validação状态

先审查Hardwaree任务接口，再Execução CPU Teste、64 环境 × 5 轮短试跑、Completo动作评估e导出核对。Página分别展示：

- **尚未Validação**：Instruções任务存在，尚未取得相应Validação证据。
- **短试跑por meio de**：训练 e 产物链路跑通，不代表已经学会动作。
- **动作ValidaçãoResultado**：给出固定目标 e 条件Inferior de Sucesso次数、尝试次数 e Falha情况。
- **真机ValidaçãoResultado**：单独记录Hardware、部署接口 e 实测证据。

AtualPágina只有项目内置 de 三个配方。单脚平衡已por meio de真实短试跑，5 轮策略 de 动作Sucesso率仍为 0/8；起伏地形尚未por meio deeste projeto de  GPU Validação。未来ComunidadeAutor de 配方也使用同样 de 证据标准。
