# 动作实验室验收 · 2026-10-23

首版已在现有训练台接入实验性的 HD1910 单脚平衡：选择支撑脚、抬脚高度和保持时间，使用原有训练、暂停/继续、检查点、评估和导出流程。后续按用户要求增加独立的 `#/actions` 动作实验室，收录当前三个内置配方。社区发布与自动安装尚未实现。

## 独立动作库Página验收

目录元数据提交 `6ca4d5f`、界面提交 `109083a` 已通过 `a8e498f` 合入 `studio-dev`，入口仍为原来的 8094 服务。新增内容只涉及目录、导航和文档，没有改变已验证的训练引擎。

- Node 状态 e ParâmetrosTesteAtualização为 **21/21**；后端动作配方回归 **13/13**。
- Edge / Playwright 分别在隔离演示Serviçoe原真实ServiçoVerificação：工作台入口、Esquerdo侧导航、直接访问、刷新、浏览器前进/后退，e分类、多关键词搜索、无Resultado清除。
- 三个配方分别ValidaçãoModelo、文字e单脚目标示意。Diretório本身不创建 WebGL 视图，打开预览只加载一个视图，关闭后释放；关闭、Escape、Tab 焦点循环 e 焦点恢复por meio de。
- 卡片e详情入口均打开正确配方 de 训练设置，默认短试跑。整个浏览 e 选择验收未发送任何创建任务 de  POST Por favor求。
- Verificação 1440、768、390、320 像素宽度。手机五项导航无横向溢出，预览e训练抽屉 de 底部操作可见。几何断言等待抽屉入场动画结束；截图已人工Verificação。
- 原服务确认 GPU 环境就绪、没有活动任务；旧平地实验 `caa6a1c5de10` 与单脚实验 `a930fbbab951` 保留，单脚结果仍为 0/8，实际视频可以播放。页面异常和失败资源均为零。
- 独立代码审查无剩余 P1/P2。此次没有重复Inicialização GPU 训练，也未新增Comunidade在线发布功能。

证据位于外层 `本地记录/training-action-lab-20261023/catalog-browser.mjs`、`catalog-validation/` 与 `catalog-validation-stable/`，含报告和桌面、手机截图。收录流程见 [贡献配方](recipe-contribution.md)。

## Validação范围

- Windows 后端 73 项：70 por meio de、3 项 Linux 专属跳过；WSL 后端 73/73 por meio de。
- Node 状态 e ParâmetrosTeste 18/18 por meio de。
- 引擎Parâmetros、Configuração、脚底几何、HD1910  e  NaN 回归 46/46 por meio de。
- 真正 CUDA  de  4 环境、30 步Testepor meio de：Direito脚Comando、61 维 actor、14 维动作、50 Hz、critic/奖励有限、局部重置正常。
- Edge / Playwright 在 1440  e  390 宽度Verificação目标编辑、厘米换算、配方独立草稿、复制、变参后短试跑门禁、演示评估标识e实际回放。无Página异常、横向溢出。
- 独立规格 e 代码审查发现评估初始化随机种子问题，已修复并复测；没有剩余 P1/P2。

CPU Teste有原Configuração de  tuple/list 类型Aviso，GPU Teste有 actuator 名称也匹配 site  de 提示，均未阻止执行。ONNX Runtime  de  CPU 推理会打印 WSL GPU 设备探测Aviso，CPU 推理实际Concluído；这些提示不能作为 GPU 训练Falha de 证据。

## 真实训练 e 产物

Hardware为 RTX 5060 Ti 16 GB、WSL2 Ubuntu 22.04，torch 2.9.1+cu128、mjlab 1.3.0、rsl-rl-lib 5.0.1。没有改动依赖锁Arquivo。

| 实验 | 目标 | Resultado |
| --- | --- | --- |
| `1eddca56e439`，隔离服务 | 左脚支撑、抬脚 1 cm、保持 3 秒 | 64 环境 × 5 轮，7,680 采样，5 个 PT；实际评估和 ONNX 导出完成 |
| `a930fbbab951`，原 8094 服务 | 右脚支撑、抬脚 0.5 cm、保持 1 秒 | 64 环境 × 5 轮，7,680 采样，含启动 28.9 秒，5 个 PT；实际评估、近景视频与导出完成 |

正式入口实验 `a930fbbab951` 的最终验收：

- 8 次尝试均提前触发物理Falha，**Sucesso 0/8**，实际总计 250 步。每次预算包含Completo 4.5 秒周期；Falha会提前结束，并不是把每次固定裁成短视频。
- 视频 960×540、50 FPS、250 帧、5 秒，Preservado全部 8 次尝试；浏览器实际播放Sucesso。镜头从默认 3 m 调整为 0.7 m，能清楚看到Pé。
- 初始化 seed 42；逐次 reset seed 42–49。修正后 de 两次评估，各次终止步数相同，平均奖励只存在约 3.43e-8 浮点差。8 次共享一个初始化电压/电阻样本，不代表覆盖全部Hardware随机化分布。
- Verificação点 76 个张量全部有限，actor 权重e观测归一化严格加载Sucesso。
- ONNX checker、32 组零/随机输入 CPU 推理通过，输入 61 维、输出 14 维；PT/ONNX 最大绝对差 `4.0531158447265625e-6`，通过 `atol=1e-5, rtol=1e-4`。
- 保存 de 环境 YAML、run.skill、skill.json、评估摘要、ONNX Comando元Dadose导出 ZIP  de 目标完全一致。
- 导出契约明确标记 `runtime_adapter_required=true`、`hardware_validated=false`。输入输出维度相同不意味着可以直接用于原行走部署端。

最终代表产物 SHA-256：

- `model_4.pt`：`b785059649269a9f18065e18050122a3acd571d06f5a96b387d8883cffab3b1e`
- `policy.onnx`：`2076ce787aaf20fc1b9c3dd83eba229d3d6dae09e6471739e7701c5b72e3c878`
- `rl-video-step-0.mp4`：`f547716356ba95f66bb76bef357277fda04151fdc054ab8a3691d3d0a90d8da6`

## 集成 e 证据

在独立工作区开发，从 `9d0fe05` 开始；引擎 `2e5a3f1`、启动随机种子修复 `9261167`、近景镜头修复 `a168cc2` 已合入 `studio-dev`。同时保留了中控状态条的其他提交和 `software/studio/docs/` 未跟踪文件。仅在原服务没有活动任务时重启，继续使用原状态目录，旧行走实验 `caa6a1c5de10` 可读取。临时 8095/8096 服务已结束，用户继续使用 8094。

外层 `本地记录/training-action-lab-20261023/` 保存浏览器脚本、运行日志、截图及隔离验证；`stable-validation/` 保存正式入口的检查脚本、产物报告与最终截图。真实 run.json/产物仍保存在原 `本地记录/training-local-20261023/state/runs/a930fbbab951/`。模型和视频没有加入 Git。

Windows worktree  de  Git Caminho不能由 WSL Git 直接解析，Execução记录 git_commit 仍可能为 null；FonteArquivo SHA-256 Preservado。新记录已经把实际InstalaçãoVersãoe锁Arquivo em  de 平台候选Versão分开保存，避免把 cu129 锁Arquivo候选写成实际InstalaçãoVersão。

## 结论边界

本轮证明可Configuração目标贯通真实训练、保存、Completo周期尝试、实际回放 e 导出。**没有证明策略已经学会单脚平衡**。Modelo几何可达到 5–20 mm 抬脚，但未证明可靠静态平衡；短训练Falha被如实展示。

长训练收敛、新任务 de 真实长训暂停/恢复、云平台e真机部署仍需分别Validação。现有暂停/恢复回归在ServiçoTeste em por meio de，不应表述为Concluído了这些额外实测。跳跃、精准转圈、视频模仿 e Comunidade配方发布仍不在Atual可Execução范围。
