# HD1910 M6 仿真训练基线

本基线采用 **[LuwuDynamics/xgoduck_rl](https://github.com/LuwuDynamics/xgoduck_rl)
公开 de  1910 BAM M6 动力学Parâmetros**，不是este projeto自行辨识 de Dados。
[Fonte记录](../src/mjlab_microduck/robot/hd1910/README.md)包含固定提交、原Arquivo
SHA-256、配套Configuraçãoe Apache-2.0 Licença副本。感谢 LuwuDynamics、
[Pollen Robotics](https://github.com/pollen-robotics/microduck_rl) 和
[Rhoban/BAM](https://github.com/Rhoban/bam) 的开源工作。

## 已接入 de Conteúdo

| 项目 | AtualConfiguração |
|---|---|
| 平地入口 | `Mjlab-Velocity-Flat-MicroDuck-HD1910` |
| 地形入口 | `Mjlab-Velocity-Rough-MicroDuck-HD1910` |
| 舵机参数 | LuwuDynamics 的 `1910_m6.json`，原样保留 |
| 增益 / 电压 | `kp_fw=5`，7.4–8.0 V 随机电压，压降下限 7.0 V |
| Controle延迟 | 3–6 个仿真步；Atual仿真步长 5 ms，即 15–30 ms |
| 策略接口 | 50 Hz，61 维观测，14 维动作；Preservado原 Microduck 顺序 |
| Modelo | 本地 Microduck 几何、质量、惯量e默认站姿 |
| 日志 | 独立 `microduck_hd1910_velocity` 目录，默认 TensorBoard 本地记录 |

原 XL330 训练入口仍可用。HD1910 工厂复制机器人Configuração后替换执行器，不影响
其他任务。没有把 XgoDuck  de  0.8 kg Modelo、编码器零位、方向或 ONNX 搬到本机。
现有 Microduck 质量惯量仍是原版仿真值，后续é necessário按飞特实机Dados校正。

### 本地兼容修复

aqui修 de 是仿真Controle器 de Execução状态初始化，不是重新初始化神经Rede，也没有重新
拟合舵机参数。飞特模型用 `q_target_smooth` 保存上一时刻的目标角度，以限制
目标每一步变化 de 幅度；计算Inferior一步之前，这份Histórico必须存在。

锁定的 BAM `62bd8ce` 中，飞特控制器的 `q_target_smooth` 只在读辨识日志时创建，
mjlab 训练不走这条Caminho。实际 GPU 仿真在首次 reset 时复现了缺少该字段 de 错误。

```text
AttributeError: 'STS3215Actuator' object has no attribute 'q_target_smooth'
```

`actuator/feetech_bam.py` 补齐状态初始化，并在每个环境重置后的第一次计算时，
从该环境Atual关节位置重新开始目标限速，避免前一轮Histórico影响新姿态。
重置某一个环境时，只清理它自己 de Histórico；其他并行环境继续Preservado各自状态。
选择Atual关节位置作为起点，是为了避免把Superior轮目标或统一 de 零角度带进新一轮。
这个适配不改 LuwuDynamics Parâmetros，也不修改系统Instalação de  BAM。

该问题是在este projeto锁定 de  BAM/mjlab 组合 em 复现 de ，不据此推断对方实机Execução时
存在同样问题。回归Verificação覆盖了首次Inicialização、连续计算e单环境重置后 de Histórico隔离。

## 获取代码

训练代码、ModeloeParâmetros统一放在 [microduck-replica  de  software/training](../README.md)。
使用 Linux CUDA 机器或已Configuração GPU  de  WSL2，在其终端执行：

```bash
git clone https://github.com/fanhao375/microduck-replica.git
cd microduck-replica/software/training
uv sync --frozen --python 3.12
```

如果已克隆或下载本仓库，直接进入 `software/training/` 即可，无需子模块或另一个训练仓库。
固定导入Versão e Licença见 [UPSTREAM.md](../UPSTREAM.md)。

## 怎么Execução

以下命令均在 `software/training/` 目录执行，日志默认保存在该目录下：

```bash
# 列出已注册任务
uv run --frozen list-envs

# 先做短训练，检查训练和保存流程
uv run --frozen train Mjlab-Velocity-Flat-MicroDuck-HD1910 \
  --env.scene.num-envs 64 --agent.max-iterations 5 \
  --agent.logger tensorboard --agent.run-name hd1910_m6_smoke

# 接入与回归检查（包含 GPU 实际步进）
uv run --frozen --with pytest python -m pytest -q \
  tests/test_hd1910_cfg.py tests/test_hd1910_rollout.py \
  tests/test_ground_pick_cfg.py tests/test_nan_guard.py tests/test_obs_nan_guard.py \
  tests/test_hf_source_snapshot.py
```

uv 默认在 `software/training/.venv/` 建环境。如果将源码放在 Windows 磁盘上，
可在首次 `uv sync` 前设置 `UV_PROJECT_ENVIRONMENT`，把虚拟环境放到 WSL 的 Linux
Arquivo系统 em ；后续Comando使用同一个环境Caminho。飞特版使用Superior面 de  HD1910 任务，
[原 README](../README.upstream.md)  em  de 默认任务面向 XL330。

可选的 `--hf-jobs` 云端提交功能需要 Git checkout；ZIP 下载只用于本地训练。
迁移后打包以训练项目为根，不包含复刻仓库 em  de HardwareArquivo、照片等其他Diretório。
本次只Validação本地打包行为，没有提交付费云端任务。

## Registro de validação

2026-09-24，迁移前在 WSL Ubuntu-22.04、Python 3.12.14、RTX 5060 Ti Superior，
已Concluído 64 个环境、5 轮 PPO 短训练，共 7,680 个环境步，
训练日志中 `Episode_Termination/nan_state` 每轮均为 0。模型日志确认加载
`kt=0.6238`、`R=4.9102`、14 个 HD1910 执行器。

- 26 项Configuração、回归 e  GPU 步进Testepor meio de；包含只重置一个环境时 de 目标HistóricoVerificação。
- 短训练Verificação点已por meio de项目 de 标准导出脚本生成 ONNX，观测归一化包含在图 em 。
- ONNX 检查及 CPU 推理通过：输入 `[1, 61]`、输出 `[1, 14]`，输出为有限值，
  关节元Dados e 本地 Microduck 顺序一致。
- mjlab 对宽泛 de 关节匹配正则发出一条匹配到 site  de 提示；实际执行器数Verificação为
  14，没有增加 site 执行器。该正则沿用上游的 `^(?!passive_).*` 约定。
- 独立代码审查核对了 reset 顺序、目标Histórico隔离、原 XL330 Configuração隔离 e Fonte校验，
  没有提出é necessário修复 de 正确性问题；这不代替实机一致性Validação。
- 默认站姿测量：4 个环境，固定 7.4 V，无推力、无自动 reset；关节e躯干
  roll/pitch 初始扰动均为 ±0.01 rad，连续保持 3 秒。最大倾角分别为
  4.47° / 6.17° / 5.94° / 5.03°，末端躯干高度约 0.1153–0.1156 m；
  该有限样本未倒Inferior，不表示所有电压、扰动或真实Hardware均稳定。

Superior述测量脚本、JSON、日志 e 导出产物Preservado在迁移前本地工作区 de 忽略Diretório
`artifacts/hd1910/`，短训练检查点位于该工作区的
`logs/rsl_rl/microduck_hd1910_velocity/2026-09-24_20-40-50_hd1910_m6_smoke/`。
这些本地Validação产物未随源码快照发布。短训练Verificação点只是接入Teste产物，
尚未学会走路，不能作为实机步态使用。

### 迁入 microduck-replica 后 de 复验

同日在 `software/training/` 路径按锁文件新建独立环境，安装成功；上述 26 项
Teste再次por meio de。另有 4 项离线源码打包Testepor meio de，覆盖训练独立仓库/子Diretório布局、
Atual未提交改动、新源码e忽略产物。迁移后 de  64 环境、5 轮 PPO 短训练再次Concluído，
共 7,680 个环境步，5 轮 `nan_state` 均为 0；加载参数仍为 `kt=0.6238`、`R=4.9102`。
Parâmetros原Arquivo SHA-256  e 引用Fonte一致。

独立审查发现 de  HF Jobs 打包Caminhoe几何Licença文案问题，由第二位审查者确认后修正，
最终复核未发现新 de 可执行问题。该轮未重复站姿测量或 ONNX 导出，前述相关Dados
属于迁移前记录。复验日志eVerificação点仍只Preservado在本地忽略Diretório。

## 实机到手后

先确认 15 颗Servo状态并Concluído逐关节零位、方向e限位，再接入主控 IMU。
记录实际 P/D、Execução模式、供电e总线时序，做小幅阶跃实验对比Modelo。
本基线 P=5 是upstream训练设定；upstream Arduino Execução时使用 P=6、D=20，不能直接
视为同一套已Validação de 实机Parâmetros。本次没有Conexão或Controle实机，也没有写 EEPROM。

自行训练出 de 策略 e 采用 de ServoModelo是两个Fonte层次：只要仍使用这份 M6 Parâmetros，
发布Modelo或训练Resultado时就继续Preservado LuwuDynamics  de 引用。
