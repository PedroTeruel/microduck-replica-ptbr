# Microduck Training Studio

小鸭子的可视化训练工作台。默认使用推荐参数，进阶设置可以展开；支持训练曲线、三维模型、检查点评估回放、暂停/继续、实验比较和成果导出。

界面沿用机器人中控 Studio 的浅灰配色、鸭子标识、黑色按钮和手机底部导航。

训练引擎位于相邻的 [`../training`](../training/README.md)，机器人中控位于 [`../studio`](../studio/README.md)。本目录是独立服务，使用已有训练工程，不需要更新机器人镜像。

## 先在本机体验

需要 Python 3.12。服务本身使用标准库，网页没有构建步骤，也不从 CDN 加载依赖。请保留相邻的 `studio/web`，它提供已随仓库分发的网页库和三维模型。

```console
cd software/training-studio
python run.py --demo --open
```

Windows 也可以双击 `start-demo.cmd`；Linux/macOS 可执行 `sh start-demo.sh`。默认地址：<http://127.0.0.1:8093>。

演示模式会启动独立的轻量子进程，生成**合成指标、文本检查点和明确标注的 SVG 示意回放**，用于体验操作流程。它不执行 GPU 策略训练。演示导出包只有记录，不包含可部署的 ONNX/PT 权重。

## 实际训练

在已准备好的 Linux NVIDIA GPU 电脑或 Windows WSL2 中，使用本仓库的训练工程及其锁定依赖。真实模式检查 MuJoCo 图形后端、mjlab 1.3.0、CUDA 和 HD1910 任务注册；不自动安装包、不申请云电脑，也不处理充值。本机操作见 [本机短试跑](docs/local-smoke.md)。

```sh
cd software/training
uv sync --frozen --python 3.12
cd ../training-studio
../training/.venv/bin/python run.py
```

在本机另开终端转发端口（用户名、地址按你的云电脑填写）：

```sh
ssh -N -L 8093:127.0.0.1:8093 用户名@云电脑地址
```

然后打开 <http://127.0.0.1:8093>。可用 `--training-root /路径/software/training` 指定引擎位置，`--state-dir /持久目录/training-studio` 指定记录目录。关闭网页不会停止训练；**关闭训练台服务会停止它拥有的子进程**。长时间运行时应通过云电脑上的终端会话管理器或服务管理器保持 `run.py` 运行。

服务默认只监听本机。确需通过其他网络入口使用时，可设置 `STUDIO_ACCESS_TOKEN` 后用 `--host 0.0.0.0` 启动；页面会要求输入令牌。从本机访问云电脑推荐使用上面的 SSH 转发；局域网直连需使用服务所在机器的监听地址。令牌仅保存在当前浏览器会话，API 和产物下载都需要 `X-Studio-Token`；Host/Origin 校验保持开启。

## 一次完整练习

想训练单脚站、跳跃或自己的动作，先读 [自定义动作训练指南](web/custom-actions.md)。运行训练台后，也可从侧栏或新建训练窗口打开这份说明；它介绍官方做法、当前支持范围、单脚站示例和新增任务的开发步骤。

1. 在「计算环境」确认检测通过；安装依赖后可重新检测。
2. 新建实验，先选 **HD1910 平地行走**。首次执行固定 **64 个环境、5 轮**的短试跑，检查加载、仿真步进和保存链路。短试跑不是训练成果。
3. 试跑成功后进入正式训练。可展开并行环境数、训练轮数、保存间隔、种子、学习率；收起后仍显示改动摘要。修改学习率、随机种子或导入档案后，需要重新完成匹配设置的短试跑；环境数和轮数可为正式训练放大。
4. 查看原始训练指标、轮数和日志。百分比表示计划轮数进度，不表示动作掌握程度。三维模型可以旋转；**CAD 模型和演示动作不能用来判断策略表现**。
5. 暂停、继续，或停止任务。选择已保存的检查点后进行评估，真实模式生成一次 250 步仿真回放。回放对应所选检查点，不是连续实时训练画面。
6. 比较同任务、同模式的正式实验；确认需要的检查点后导出模型包，再走既有的仿真和真机验证流程。

| 操作 | 行为 |
|---|---|
| 暂停 | Linux 使用进程组 SIGSTOP，保留策略、优化器和显存；演示子进程确认暂停后才更新界面 |
| 继续 | 暂停状态使用原进程继续；停止/完成状态从选定检查点新建实验并记录来源 |
| 停止 | 结束拥有的训练进程，保留已完成写入的检查点；不保证保存尚未写入的迭代 |
| 评估 | 训练停止后，对选定检查点运行有步数上限的推理并生成视频 |
| 导出 | 调用引擎 `scripts/export.py`，保留其内置观测归一化，并打包 ONNX、检查点、配置及来源记录 |

暂停仍占用显存，**不会自动关停云电脑或停止平台计费**。同一服务一次只执行一个训练、评估或导出操作。重新启动服务会将未结束的旧任务标记为中断，不凭记录中的 PID 操作其他进程。

## 档案与结果

支持导入 `microduck-studio-duck-profile/v1` JSON（最多 64 KiB）。档案随实验保存用于核对，**不会自动覆盖训练中的质量、惯量、关节零位或舵机配置**。当前 HD1910 配方是仿真基线，仍需独立验证自己的实物。

服务记录默认在 `state/runs/<id>/`，引擎原始日志和 PT 检查点仍在 `../training/logs/rsl_rl/`。备份或迁移时保留这两处；界面记录引用引擎检查点的原路径。导出的 ZIP 可单独保存，但本版没有“上传 ZIP 恢复训练”入口。

HD1910 平地任务已在 WSL2 / RTX 5060 Ti 上完成真实 64 环境、5 轮训练、PT 保存、250 步视频评估及 ONNX 导出，并独立核对 PT/ONNX 推理一致性。详见 [验收记录](docs/verification.md)。起伏地形、长训练、目标云电脑和真机部署仍需分别验收；短试跑不证明动作已经训练成熟。

## 开发验证

```console
python -m unittest discover -s tests -v
node --test tests/state.test.mjs
```

浏览器验收使用 Playwright，脚本自行启动一个隔离的演示服务、设置测试令牌，实际调用接口并保存截图。设置 `PLAYWRIGHT_MODULE_ROOT` 为现有 `node_modules` 路径即可复用已安装的 Playwright；也可在开发环境安装 Playwright。`BROWSER_EXECUTABLE` 可指定 Chrome/Edge 可执行文件，`PYTHON` 可指定 Python 3.12。无需安装浏览器依赖即可运行前面的单元测试。

```console
node dev/browser-check.mjs
```

验收输出默认写入系统临时目录，可用 `BROWSER_CHECK_OUTPUT` 指定目录。测试不会连接云平台、GPU 或机器人。设计与 API 约定见 [design.md](docs/design.md)，实现验收清单见 [implementation-plan.md](docs/implementation-plan.md)，本次测试与审核结果见 [verification.md](docs/verification.md)。

动作指南以 `web/custom-actions.md` 为源文件。修改后，在安装了 Python-Markdown 的文档编辑环境运行 `python dev/build-guide.py`，同步提交生成的 `web/guide.html`。网页直接使用已生成文件；运行训练台无需安装 Markdown 或执行构建。

## 署名

本目录原创代码采用仓库 Apache-2.0；文档按仓库对应文档许可保留。共享模型、网页库和训练引擎遵循各自许可证，见 [NOTICE.md](NOTICE.md)。

同类项目对比与下一步优先级见 [kissqy 训练中控对比](docs/reference-comparison-2026-10-23.md)。
