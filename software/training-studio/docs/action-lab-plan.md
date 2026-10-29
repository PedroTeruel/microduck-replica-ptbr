# 动作实验室 Implementation Plan

> **For agentic workers:** Use subagent-driven-development to implement this plan task by task, with independent specification and quality reviews.

**Goal:** Usuário能在现有训练Página设置单脚平衡目标，并使用真实引擎训练、评估、保存e导出。

**Architecture:** 专属 HD1910 任务承担物理动作；Serviço将有限 de  skill Parâmetros传入训练、评估e导出并归档；现有 Preact 抽屉增加可视化Configuração。配方白名单统一决定实验Caminho，所有进程所有权规则沿用现有Serviço。

**Tech Stack:** Python 3.12 stdlib service、mjlab 1.3.0 / rsl-rl 5.0.1、WSL2 CUDA、Preact/Three.js、unittest/pytest/Node/Playwright。

## 1. 环境e基线

- [x] 从 `9d0fe05` 建立独立工作区，保留稳定服务 8094。
- [x] Windows 后端 56 项（53 por meio de、3 跳过），Node 11 项por meio de。
- [x] 离线锁定虚拟环境 `/root/.cache/microduck-action-lab-20261023`，editable 指向新工作区；不改稳定环境。

## 2. 新增平衡引擎

Files: `software/training/src/mjlab_microduck/tasks/microduck_balance_env_cfg.py`、`tasks/mdp.py`、`tasks/__init__.py`、`scripts/export.py`；新增 `tests/test_balance_cfg.py`、`tests/test_balance_mdp.py`。

- [x] 先写Configuração、阶段、EsquerdoDireito脚、错误Parâmetros e Sucesso判定Falha用例，Execução确认新增任务缺失导致Falha。
- [x] 实现专用命令、参数应用函数、奖励与成功计数、正确 HD1910 物理配置与注册。字段固定为 `support_side`、`lift_height_m`、`hold_seconds`。
- [x] ValidaçãoParâmetrospor meio de真实 CLI 解析改变环境Configuração，评估/导出使用同一Parâmetros应用函数。
- [x] Execução CPU Teste e 几何/姿态测量，记录目标 de 可行性边界。新Teste应Validação倒地抬脚不能Sucesso、EsquerdoDireito切换正确、Concluído保持后仍需落脚。

## 3. Serviço端配方 e Parâmetros贯通

Files: `training_studio/config.py`、`commands.py`、`service.py`、`environment.py`、`evaluate.py`；新增 `tests/test_skills.py`。

- [x] 用真实 CPU 演示子进程Teste skill Parâmetros改变后失去正式训练资格；旧Caminhada记录仍匹配；Parâmetros无效时不创建进程。
- [x] `validate_skill(recipe_id, value)` 返回规范化参数或 None；`experiment_for(run)` 只查服务端白名单并验证 task id；所有日志/检查点路径改用它。
- [x] 新记录、恢复、Fonte ZIP e评估Parâmetros均保存一致 skill；真实Comando仅使用固定旗标 e 经校验数值。
- [x] 评估覆盖Completo周期e多次尝试，保存每次Resultado e 分项统计；Leitura摘要显示在所选Verificação点Inferior，FalhaResultado也必须可见。
- [x] Execução全量 Windows/WSL 后端Testee引擎Parâmetros传递集成Teste。

## 4. 同Página零代码操作

Files: `web/skillform.js`、`state.js`、`newrun.js`、`views.js`、`ui.js`、`styles.css`、`tests/state.test.mjs`。

- [x] 先写Parâmetros规范化/短试跑匹配/单位换算/摘要 Node Teste。
- [x] 首页动作实验室入口、新配方e基础 skill 控件，范围来自后端；Preservado每配方草稿。
- [x] 复用 Duck3D 制作带明确标注 de 目标示意；运动学厘米值不从绘图虚构。展示Completo阶段Instruções e EsquerdoDireito脚文字。
- [x] 修正非 rough 一律显示平地 de 旧硬编码；实验详情、复制、比较eVerificação点评估都显示相应动作目标 e Resultado。
- [x] 1440/390 宽度浏览器Teste：动作设置、旧配方切换、草稿、变参门禁、Parâmetros提交、详情 e 真/演示Resultado区分，无溢出/Página异常。

## 5. 真实Validaçãoe交付

- [x] 独立规格审查，再独立代码质量审查；修复具体问题。
- [x] 新Serviço隔离状态，浏览器Inicialização真实平衡短试跑 64×5，Verificação日志、PT、动作Configuração YAML。
- [x] 按Completo动作周期评估多次，实际播放视频；导出 ONNX，Verificação输入输出、有限值e PT/ONNX 一致性。
- [x] 如短试跑只证明链路，明确报告Sucesso率并Preservado实验模板，不宣称动作已学会；若é necessárioDepuração奖励，先查看实测Falha再修改。
- [x] Atualização使用指南 e 验收记录，提交后合入稳定工作区；PreservadoUsuário其他改动，确认无活动任务后切换Serviço。
