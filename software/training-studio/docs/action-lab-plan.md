# 动作实验室 Implementation Plan

> **For agentic workers:** Use subagent-driven-development to implement this plan task by task, with independent specification and quality reviews.

**Goal:** 用户能在现有训练页面设置单脚平衡目标，并使用真实引擎训练、评估、保存和导出。

**Architecture:** 专属 HD1910 任务承担物理动作；服务将有限的 skill 参数传入训练、评估和导出并归档；现有 Preact 抽屉增加可视化配置。配方白名单统一决定实验路径，所有进程所有权规则沿用现有服务。

**Tech Stack:** Python 3.12 stdlib service、mjlab 1.3.0 / rsl-rl 5.0.1、WSL2 CUDA、Preact/Three.js、unittest/pytest/Node/Playwright。

## 1. 环境和基线

- [x] 从 `9d0fe05` 建立独立工作区，保留稳定服务 8094。
- [x] Windows 后端 56 项（53 通过、3 跳过），Node 11 项通过。
- [x] 离线锁定虚拟环境 `/root/.cache/microduck-action-lab-20261023`，editable 指向新工作区；不改稳定环境。

## 2. 新增平衡引擎

Files: `software/training/src/mjlab_microduck/tasks/microduck_balance_env_cfg.py`、`tasks/mdp.py`、`tasks/__init__.py`、`scripts/export.py`；新增 `tests/test_balance_cfg.py`、`tests/test_balance_mdp.py`。

- [x] 先写配置、阶段、左右脚、错误参数与成功判定失败用例，运行确认新增任务缺失导致失败。
- [x] 实现专用命令、参数应用函数、奖励与成功计数、正确 HD1910 物理配置与注册。字段固定为 `support_side`、`lift_height_m`、`hold_seconds`。
- [x] 验证参数通过真实 CLI 解析改变环境配置，评估/导出使用同一参数应用函数。
- [x] 运行 CPU 测试及几何/姿态测量，记录目标的可行性边界。新测试应验证倒地抬脚不能成功、左右切换正确、完成保持后仍需落脚。

## 3. 服务端配方与参数贯通

Files: `training_studio/config.py`、`commands.py`、`service.py`、`environment.py`、`evaluate.py`；新增 `tests/test_skills.py`。

- [x] 用真实 CPU 演示子进程测试 skill 参数改变后失去正式训练资格；旧行走记录仍匹配；参数无效时不创建进程。
- [x] `validate_skill(recipe_id, value)` 返回规范化参数或 None；`experiment_for(run)` 只查服务端白名单并验证 task id；所有日志/检查点路径改用它。
- [x] 新记录、恢复、来源 ZIP 和评估参数均保存一致 skill；真实命令仅使用固定旗标与经校验数值。
- [x] 评估覆盖完整周期和多次尝试，保存每次结果与分项统计；读取摘要显示在所选检查点下，失败结果也必须可见。
- [x] 运行全量 Windows/WSL 后端测试和引擎参数传递集成测试。

## 4. 同页面零代码操作

Files: `web/skillform.js`、`state.js`、`newrun.js`、`views.js`、`ui.js`、`styles.css`、`tests/state.test.mjs`。

- [x] 先写参数规范化/短试跑匹配/单位换算/摘要 Node 测试。
- [x] 首页动作实验室入口、新配方和基础 skill 控件，范围来自后端；保留每配方草稿。
- [x] 复用 Duck3D 制作带明确标注的目标示意；运动学厘米值不从绘图虚构。展示完整阶段说明与左右脚文字。
- [x] 修正非 rough 一律显示平地的旧硬编码；实验详情、复制、比较和检查点评估都显示相应动作目标及结果。
- [x] 1440/390 宽度浏览器测试：动作设置、旧配方切换、草稿、变参门禁、参数提交、详情与真/演示结果区分，无溢出/页面异常。

## 5. 真实验证和交付

- [x] 独立规格审查，再独立代码质量审查；修复具体问题。
- [x] 新服务隔离状态，浏览器启动真实平衡短试跑 64×5，检查日志、PT、动作配置 YAML。
- [x] 按完整动作周期评估多次，实际播放视频；导出 ONNX，检查输入输出、有限值和 PT/ONNX 一致性。
- [x] 如短试跑只证明链路，明确报告成功率并保留实验模板，不宣称动作已学会；若需要调试奖励，先查看实测失败再修改。
- [x] 更新使用指南与验收记录，提交后合入稳定工作区；保留用户其他改动，确认无活动任务后切换服务。
