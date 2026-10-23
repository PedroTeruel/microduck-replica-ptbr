# 来源与许可

- 训练台原创代码遵循仓库 [Apache-2.0](../../LICENSE)，文档遵循根目录 [NOTICE](../../NOTICE.md) 的文档许可。训练引擎中的官方任务及本项目 HD1910 适配各自保留署名与许可。
- 界面沿用本仓库中控 Studio 的黑白黄鸭子标识、颜色与组件规则。
- 三维预览复用 `../studio/web/duck3d.js` 与 `../studio/web/model/`。模型是 Pollen Robotics 公开仿真几何的衍生内容，按仓库根 NOTICE 保留 **CC BY-NC-SA** 条件；不是新的实物打印 CAD。历史转换说明见 [Studio 模型来源](../studio/web/model/NOTICE.md)，完整许可边界以根 NOTICE 为准。
- 网页复用已分发的 Preact、htm、Three.js，不从外部 CDN 下载。Preact、Three.js 为 MIT，htm 为 Apache-2.0；许可原文在 [`../studio/web/vendor/licenses/`](../studio/web/vendor/licenses/)。
- HD1910 训练配方、Pollen Robotics 训练引擎、LuwuDynamics 的 1910 M6 参数和 Rhoban/BAM 各自保留原署名与许可，详见 [`../training/UPSTREAM.md`](../training/UPSTREAM.md)。
- 本训练台没有引入其他训练产品的前端代码、品牌图标或截图。示意动作和合成数据仅供界面演示。
- 新增动作目录参考 [kissqy 的公开任务目录](https://github.com/kissqy/Microduck-kissqy/blob/525a215a19397767a073b782f57e97cf53683761/microduck-hd1910/training-console/data/tasks.json) 的任务名称与分类，训练实现使用本仓库已有 Pollen Robotics 任务工厂和本项目 HD1910 适配；没有复制对方原创训练器、界面或模型权重。新增基线不表示精确复现作者成品的质量配置和完整训练历史。
