# 本机短试跑

先选 **HD1910 平地行走 → 64 个环境 → 5 轮**。页面的「开始短试跑」会自动使用这组参数，每轮保存一次。训练引擎每轮为每个环境采样 24 步，因此总计 `64 × 24 × 5 = 7,680` 条采样；日志轮数从 0 开始，最后一个文件是 `model_4.pt`。

## 在界面里操作

1. Inicialização真实训练Serviço，打开它显示 de 地址。在「计算环境」确认真实模式、CUDA、图形后端e任务Verificaçãopor meio de。
2. 点「新建训练」，选「HD1910 平地Caminhada」，填实验名，点「开始短试跑」。先保持默认种子e学习率。
3. 等待状态变为完成。应出现 5 个指标点和 `model_0.pt` 至 `model_4.pt`，日志累计 7,680 步。
4. 选最后的 `model_4.pt` 进行评估，查看 250 步、约 5 秒的策略回放。训练区域的 CAD 外观与评估视频用途不同。
5. 导出Modelo包，确认BaixarSucesso。é necessário部署前，再进行Modelo e 机器人Configuração核对 e 独立仿真Validação。

5 轮只Verificação加载、GPU 仿真、优化器Atualizaçãoe产物流程。奖励负数、鸭子跌倒或动作不稳定都不足以判定这个短TesteFalha；重点是无报错退出、指标有限、Verificação点可加载、视频可播放。先por meio de这个Teste再安排长训练。

## Windows 使用 WSL2

真实训练服务在 Linux 中执行；Windows 负责浏览器界面。需要 NVIDIA 驱动支持 WSL CUDA，WSL 内的 `nvidia-smi` 能看到显卡，并已安装 Python 3.12 与 uv。以下命令在 WSL 的项目根目录执行：

```sh
export PATH="$HOME/.local/bin:$PATH"
cd software/training
uv sync --frozen --python 3.12
cd ../training-studio
../training/.venv/bin/python run.py --port 8094
```

然后在 Windows 浏览器打开 <http://127.0.0.1:8094>。8094 用于和默认 8093 的演示服务区分；启动时不加 `--demo`。

默认图形后端是 EGL，环境预检和训练/评估使用相同设置。Ubuntu 22.04 如果缺少 `libEGL.so.1`，需安装系统包 `libegl1` 后重新检测。显式设置的 `MUJOCO_GL` 会被保留，所选后端的系统依赖也必须准备好。预检只检查图形库能否加载，实际渲染通过策略评估视频验证。

首次注册全部任务可能需要几十秒，预检允许最多 60 秒。关闭网页不停止服务；关闭运行 `run.py` 的终端会结束其拥有的任务。更换启动目录或记录目录前，注意保留训练引擎日志和服务 state 两处记录。

## 本次实测

2026-10-23，Windows + WSL Ubuntu 22.04、RTX 5060 Ti 16 GB、Python 3.12.14、torch 2.9.1+cu128、mjlab 1.3.0：Superior述 5 轮约 41 秒Concluído（包含Inicialização加载），生成 5 个 PT。评估得到 960×540、50 FPS、250 帧视频。ONNX checker e 32 组同输入 PT/ONNX 推理核对por meio de。耗时是本次测量，首次内核编译或其他机器可能不同。
