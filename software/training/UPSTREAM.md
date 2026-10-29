# Projeto de treinamentoFonte e 维护位置

本目录是普通源码目录，随 `microduck-replica` 一起克隆和下载，不是 Git 子模块。
后续 HD1910 训练工作维护在这里；原 `fanhao375/microduck_rl` 的 HD1910 分支保留作历史来源。

## 导入Versão

2026-09-24 从以Inferior固定Versão导入已跟踪 de Completo源码快照：

- 来源：[fanhao375/microduck_rl @ d9e1926](https://github.com/fanhao375/microduck_rl/tree/d9e1926c5220a0eb79fa5aab9df7b336f8e9a226)
- 完整提交：`d9e1926c5220a0eb79fa5aab9df7b336f8e9a226`
- Pollen Robotics 上游基线：`d424a0c899f6b33cbd3daeb279913134349c0b63`；在其上增加 HD1910 任务、M6 参数引用、初始化适配和测试。
- 导入方式：该提交的 `git archive` 源码快照；不包含 `.git`、虚拟环境、训练日志或检查点。
- 原 README 原样保存为 [README.upstream.md](README.upstream.md)。迁移调整本Diretório de Instruções e 入口链接，
  并修正 HF Jobs  de 打包根Diretório，让归档仅包含Projeto de treinamento；补充本地打包回归Teste。
  训练/执行器逻辑、依赖锁Arquivo、Configuração、原有Testee几何资产保持该VersãoConteúdo。

这份快照 em  de  Microduck 几何、质量惯量e关节约定来自训练项目，不代表飞特复刻实机已Concluído测量。

## Autor e Licença

| Conteúdo | Fonte | Licença |
|---|---|---|
| 训练框架、原有任务、工具及文档 | [Pollen Robotics / microduck_rl](https://github.com/pollen-robotics/microduck_rl) | [Apache-2.0](LICENSE) |
| Microduck 3D Modelo e 网格 | 同Superior | upstream README  de  CC BY-SA-NC 声明；本仓按 CC BY-NC-SA 4.0 PreservadoAtribuição、非商用 e 相同方式共享条件，见 [NOTICE](../../NOTICE.md#Licença名称Instruções) |
| `1910_m6.json` 舵机动力学参数与配套配置参考 | [LuwuDynamics / xgoduck_rl](https://github.com/LuwuDynamics/xgoduck_rl) | [Apache-2.0 副本](src/mjlab_microduck/robot/hd1910/LICENSE) |
| BAM 执行器模型与辨识库（通过依赖安装） | [Rhoban / BAM](https://github.com/Rhoban/bam) | Apache-2.0；锁文件固定 `62bd8ce12154340be97e06f7f41a0ca8f116d967` |
| HD1910 任务、状态初始化适配、相应Teste e 本Diretório新增文档 | 本复刻项目 | Apache-2.0 |

根Diretório对este projeto其他文档 de  CC Licença不覆盖本训练Diretório de  Apache 文档；3D ModeloLicença单独Preservado。
依赖库继续遵循各自Licença。

## Parâmetrosoriginal出处

- LuwuDynamics 固定提交：`326d77a1122870bdefa2c36403937502c958e69c`
- 原路径：`src/mjlab_microduck/robot/xgoduck/params/1910_m6.json`
- 本目录路径：[`src/mjlab_microduck/robot/hd1910/1910_m6.json`](src/mjlab_microduck/robot/hd1910/1910_m6.json)
- 原文件 SHA-256：`ef2d51adfb1cc0831b9b02ca19aa9176fceecdf725148d084378d7d9a64afceb`

Parâmetros按原ArquivoPreservado，不是este projeto自行辨识 de Resultado。详细引用eConfiguração边界见
[ParâmetrosFonte](src/mjlab_microduck/robot/hd1910/README.md)。以后基于这些Parâmetros训练自己 de 策略，仍PreservadoParâmetrosAutorAtribuição。
