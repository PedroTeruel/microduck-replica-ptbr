# 预训练目录与计算资源验收 · 2026-10-23

本轮将现成模型的来源目录加入动作实验室，并在训练详情加入执行端当前资源监控。未改变训练算法、机器人策略或原实验状态。

## 模型来源

- 官方 [V8](https://huggingface.co/pollen-robotics/microduck-policies/blob/665ae4eb20bfe13bca1ef4ea6d4bb6b4a096e448/manifest.json)：固定 `665ae4eb20bfe13bca1ef4ea6d4bb6b4a096e448`，10 个 ONNX，XL330、61 维观测、14 维动作、50 Hz。V8 集合中保留早期独立行走/站立模型；默认行走是 VelStand。
- [kissqy V167](https://github.com/kissqy/Microduck-kissqy/blob/525a215a19397767a073b782f57e97cf53683761/microduck-hd1910/firmware/verification/v167/arm64-models.json)：固定 `525a215a19397767a073b782f57e97cf53683761`，10 个 HD1910 模型，其中 4 个需要滑轮脚。作者审计为 QEMU ARM64 推理，`hardware_tested=false`，不代表本项目完成物理评估。
- 15 个独立 ONNX 的上游字节流 SHA-256 全部匹配；34,138,802 字节固件包内的 10 个 ONNX 也全部匹配。没有将权重复制进产品或执行模型。包的 161 个成员中没有 PT/PTH，完整 Git 树也没有；其他未检查的包不作推断。
- 20 个条目均有硬件、作者、固定版本、SHA、实际字节大小、使用许可及获取入口。包内权重和单文件链接分别标注，社区受限权重仍由原发布者分发。
- 当前只提供来源说明与上游获取，未接入外部模型本地仿真、自动安装或续训。新建配方实验从零训练，原有检查点续训流程保持原约束。

## 资源与交互

- Windows Python 测试 93 项：90 通过、3 项 Linux 专属跳过；WSL Python 93/93；Node 26/26。
- 独立审查发现跨机器时钟比较会误报数据过期，已在 `7598562` 改为服务端单调时钟计算的样本年龄，加浏览器接收后的本地经过时间；远端时钟差和页面挂起回归通过。复审无剩余 P1/P2。
- 隔离演示服务和原 8094 真实服务的浏览器验收通过：20 模型、来源/类别/关键词筛选、所有详情的源地址与SHA、手机详情按钮、原配方入口、真实资源采样、断线保留旧读数/过期标记/恢复，以及离开实验后停止前端轮询。零页面异常，浏览和选择不发送训练 POST。
- 真实服务读取 RTX 5060 Ti（总显存 16311 MiB）、i5-14600KF（20 逻辑核心）、CPU 利用率和 WSL 内存（总量 16640778240 bytes）。GPU 温度随采样变化；CPU 温度为 null，原因是 WSL 未暴露对应传感器。资源来自执行端整体，未声称为本次训练独占用量。
- 桌面 1440 与手机 320 宽度检查并人工查看截图。原停止实验 `9843544f2296` 的 0/1000 轮、9 秒、0 检查点仍保留；另三条旧实验也完整保留。只在服务无活动任务时更新重启，GPU 环境仍就绪。

## 证据

外层 `本地记录/training-action-lab-20261023/` 保存 `pretrained-source-package-audit.json`、`kiss-model-inventory.json`、官方 refs/manifest/tree，以及 `models-resources-browser.mjs`。`models-resources-validation-stable/` 保存原 8094 服务的报告与截图，`models-resources-validation/` 保存隔离验收。`pretrained-ui-mock/` 是明确使用模拟资源的 UI 边界测试，不作为真实硬件证据。

本轮未启动真实 GPU 训练、付费云电脑或机器人动作；只在隔离演示服务创建一条合成训练记录用于展示资源面板。
