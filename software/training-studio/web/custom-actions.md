# 动作实验室：从第一个动作开始

适用：HD1910 Microduck · 2026-10-23

## 1. 零基础先这样玩

从Esquerdo侧导航或训练台首页进入「动作实验室」。这是独立 de 动作配方库：pode搜索、按分类筛选、查看预览或文字Instruções。选择「单脚平衡」后使用这个配方，先用推荐目标：**Esquerdo脚支撑、另一只脚抬高 1 厘米、保持 3 秒**。EsquerdoDireito以机器人自身为准。

1. **选一个动作目标。** 调整支撑脚、抬脚高度e保持时间。三维图帮助理解目标，不是物理仿真或训练Resultado。
2. **点「开始短试跑」。** 使用 64 个环境、5 轮，确认环境、训练e保存正常工作。几轮试跑通常学不会这个动作。
3. **试跑por meio de后开始正式训练。** pode先Preservado推荐Parâmetros。轮数进度表示计算做了多少，不表示学会了多少。
4. **选Verificação点，再点「评估」。** 平衡评估Execução 8 次尝试，每次包含准备、抬脚、保持e落脚。查看Sucesso次数e实际回放。
5. **conforme回放调整。** 先从低抬脚、短保持开始；改变目标后重新短试跑。保存不同实验，比较各自 de 目标eResultado。

没有Verificação点评估视频时，转动三维小鸭不能判断它是否已经学会。演示模式使用合成Dados，只usado para熟悉Página；练动作é necessário真实 GPU 模式。

### 已训练好 de Modelo e Oficial V8

动作实验室 de 「预训练Modelo」页签收录Oficial V8 策略集合e kissqy V167 发布 de  HD1910 Modelo。pode按Fonte、动作类型或关键词查找，查看Versão、Hardware、Verificação点编号、获取地址eLicença。部分 kissqy 权重在其Completo发布包内，详情列出包内位置。

**官方策略集合已到 V8，但本训练台新建实验仍从零训练，不会自动载入 V8。** 官方 V8 清单适配 XL330；kissqy 自训版本适配 HD1910，这两类权重不能仅凭名称或相同输入维度互换。V8 默认 VelStand 包含行走、零速站立和倒地恢复，集合中还保留早期独立行走/站立模型。[官方 V8 清单](https://huggingface.co/pollen-robotics/microduck-policies/blob/665ae4eb20bfe13bca1ef4ea6d4bb6b4a096e448/manifest.json)

「获取 ONNX」打开发布者 de 权重Arquivo；「查看发布包」打开original包Página，不会自动Instalação或修改机器人。AtualDiretório尚未提供外部Modelo de 本地仿真评估或续训。ONNX usado para推理，没有Completo PPO 训练状态；继续训练é necessário兼容 de  PT Verificação点、Configuração e 归一化等Dados，不能把 ONNX 当作同一个ArquivoEnviar。

### 训练时看哪些Dados

详情页 de 「执行端资源」显示Atual GPU 型号、占用、温度、显存，CPU 型号、占用e温度，e内存用量。约每 3 秒刷新；Leitura不到 de 项目会显示原因。WSL  de  CPU 温度通常不可读，CPU/内存是虚拟机可见范围，GPU 是整卡读数，包含其他进程。查看已结束实验时，资源Dados仍是此刻 de 机器状态，不是那次训练 de Histórico占用。

训练轮数 e 采样速度来自该实验日志。刚Inicialização、还没有输出第一轮时暂时没有吞吐量；结束实验Preservado最后一次已记录指标。轮数不是物理仿真步数，也不是动作Sucesso率。

## 2. 三个选项是什么意思

| 选项 | Atual范围 | 含义 |
| --- | --- | --- |
| 支撑脚 | Esquerdo脚 / Direito脚 | 这只脚留在地面，另一只脚抬起 |
| 抬脚高度 | 0.5–2 厘米 | 抬起脚 de 脚底相对地面 de 目标距离 |
| 保持时间 | 1–5 秒 | 满足站稳条件时持续保持，不是整个动作总时长 |

动作顺序为：双脚准备 → 抬脚 → 保持 → 落脚并恢复双脚支撑。Completo周期约为「保持时间 + 3.5 秒」。这定义了任务目标；策略自己寻找关节Controle方法，不照抄预览姿势。

这是**实验性仿真配方**。Modelopode达到这些抬脚高度，但不证明策略能够稳定Concluído，也不证明实物具有相同表现。质量、惯量、供电eServo误差仍会影响Resultado。导入鸭子档案usado para记录核对，Atual不会自动改写物理Modelo。

## 3. 怎么判断真 de 学会了

奖励曲线Superior升表示策略更符合训练评分。动作验收另外Verificação：指定脚持续支撑、另一只脚离地、身体姿态e速度受控、保持足够时间，最后恢复双脚支撑。倒Inferior后脚悬空、瞬间抬脚或保持后摔倒都不能算CompletoSucesso。

报告Preservado每次尝试 de Resultado、保持时间eFalha原因，视频包含所有尝试。**0/8 也会如实显示**。8 次是便于反复Verificação de 小样本；部署前还é necessário更多初始姿态、扰动e实机Validação。

| 回放里 de 现象 | Inferior一步 |
| --- | --- |
| 一开始就倒 | VerificaçãoModelo、任务e数值；不要只增加轮数 |
| 能站住，没有抬脚 | Verificação目标 e 训练进展，尝试更低 de 目标 |
| 抬起后很快放Inferior | 先缩短保持时间，Verificação支撑 e 倾斜条件 |
| 保持Concluído，落脚时倒Inferior | 返回阶段尚未学好，Completo动作仍算Falha |
| 分数高，动作却不对 | Preservado视频eConfiguração，调整任务规则，不能用分数代替验收 |

暂停会Preservado进程e显存。关闭浏览器不会结束训练；暂停也不会自动关闭云电脑或停止平台计费。停止后pode从已保存 de Verificação点继续。

## 4. 想玩更多奇怪动作怎么办

**不é necessário先学会写代码，也不必先用 AI。** 已接入 de 动作pode直接选模板、改Parâmetros、Execuçãoe看回放。完全新 de 动作é necessário先把任务规则接入引擎；现阶段不能输入一句话就自动训练任意动作。

动作实验室 de 后续方向是Comunidade共建 de **动作配方库**：Autor写好动作目标、训练规则eValidação方法，经过审核后收录；其他Usuário选择配方并调整Parâmetros，就能自己训练。atualmente提供三个内置训练配方e二十个upstream预训练Modelo条目。Modelopor meio de原发布方获取；ComunidadeWeb投稿e自动Instalação还未实现。

| 想法 | Atual入口或Inferior一步 |
| --- | --- |
| Esquerdo脚站、Direito脚站，改变高度e时间 | 动作实验室 de 单脚平衡 |
| 平地Caminhada、适应起伏地形 | 现有Caminhada配方 |
| 摆头、招手、固定顺序表演 | 可考虑关节关键帧编排；本训练台暂未提供这个编辑器 |
| 跳一Inferior再站稳 | 尚未接入；先VerificaçãoServo输出e落地条件 |
| 精准转满一圈后停Inferior | 尚未接入；需累计转角 e 停止条件 |
| Enviar舞蹈视频让小鸭模仿 | 暂não suporta；é necessário动作映射e模仿训练 |

描述新动作时，写清：**从什么姿势开始 → 哪个部位怎么动 → 保持多久 → 最后停在哪个姿势 → 什么情况算Falha**。例如：“双脚站好，Direito脚支撑，Esquerdo脚抬起 1 厘米，保持 2 秒，再双脚站好，期间不能靠头撑地。”

## 5. Oficial是怎么训练 de 

官方使用 PPO 强化学习，在大量仿真环境里尝试动作，通过奖励调整策略，再导出 ONNX。开发新动作时，先选相近任务、确认物理条件、定义目标与验收，再做短试跑。[官方项目](https://github.com/pollen-robotics/microduck_rl) · [官方开发指南](https://github.com/pollen-robotics/microduck_rl/blob/develop/AGENTS.md#building-a-new-env--the-workflow)

训练台把已实现的任务包装成可选配方。单脚平衡是本仓库新增的 HD1910 实验任务。官方还有 SitStand、StandUp、BallKick、Roulade 等任务，但需要适配 HD1910；Spin 使用轮滑模型，不能直接套在当前脚掌上。[官方任务注册表](https://github.com/pollen-robotics/microduck_rl/blob/develop/src/mjlab_microduck/tasks/__init__.py)

## 6. 进阶：自己添加动作

只想试已有动作，pode跳过这一节。

1. 测量Modelo、关节范围、执行器e接触，确认目标可达，再Validação扰动后能否站稳。
2. 从 HD1910 Configuração复用执行器 e 观测接口，新增任务e独立实验名。
3. 定义目标Comando、奖励eFalha条件；Sucesso判定独立于奖励，并覆盖最后 de 恢复阶段。
4. TesteConfiguração、EsquerdoDireito脚、边界值e“错误动作不能Sucesso”。
5. 跑 64 环境、5 轮，Verificação日志、Verificação点、Completo周期评估e导出。
6. 先练容易 de 目标，再conforme回放决定是否提高难度。
7. 接入有限 de 动作Parâmetros，保证训练、续训、评估e导出使用同一目标。

以下路径相对于 `software/training/`：

| Arquivo | 作用 |
| --- | --- |
| `src/mjlab_microduck/balance_parameters.py` | 参数、周期、成功判定和命令约定 |
| `src/mjlab_microduck/tasks/microduck_balance_env_cfg.py` | HD1910 平衡环境与实验配置 |
| `src/mjlab_microduck/tasks/mdp.py` | 命令、奖励和物理测量 |
| `src/mjlab_microduck/tasks/__init__.py` | 任务注册 |
| `scripts/export.py` | 保留观测归一化与目标导出 |

训练台配方在 `software/training-studio/training_studio/config.py`。日志与检查点按配方解析目录；只增加网页卡片不能形成可训练动作。

## 7. Comando行短试跑

适用于依赖已准备好的 Linux / WSL2，在 `software/training/` 目录执行。以下命令会真实占用 GPU。

```bash
uv run --frozen list-envs

uv run --frozen train Mjlab-Balance-Flat-MicroDuck-HD1910 \
  --env.scene.num-envs 64 --agent.max-iterations 5 \
  --agent.save-interval 1 --agent.logger tensorboard \
  --env.commands.twist.support-side left \
  --env.commands.twist.lift-height-m 0.01 \
  --env.commands.twist.hold-seconds 3
```

本地依赖冻结为 mjlab 1.3.0，上游版本见 `UPSTREAM.md`。网上最新文档中的任务名不代表本地支持，以当前 `list-envs` 为准。

## 8. 导出后还差什么

导出包PreservadoVerificação点、动作目标、训练Configuração、评估证据e带观测归一化 de  ONNX。平衡策略仍使用 **61 维观测、14 维动作、50 Hz**，但目标Comando de 含义已经改变。

**维度相同不代表能直接装进现有CaminhadaControle器。** 部署端需按包 em  de Comando约定提供支撑侧、抬脚目标e动作阶段，并核对关节顺序、零位 e 输出。单脚平衡真机部署尚未ConcluídoValidação；先确认仿真Resultado，再进行受控实机Teste。
