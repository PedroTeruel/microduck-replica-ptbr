# 导入训练好 de Modelo

打开 Studio  de 「Modelo管理」，不用重新烧系统Imagem。

1. 在训练电脑Superior找到同一次部署导出 de ModeloDiretório。
2. 将 `policy.onnx`、`manifest.json`、`deployment-contract.json` 打成 ZIP、tar.gz 或 tgz。若导出时有 `deployment-execution.json`、`deployment-runtime.json`、`model-info.json`，也放在同一目录。不要混入训练日志、脚本或多个模型。
3. 选择部署包，可填写显示名称，点「导入Modelo」。部署包Superior限 64 MiB；展开后Superior限 256 MiB。
4. 导入por meio de只表示已经Instalação。先卸力，再在Modelo卡片选择用途，点「使用此Modelo」。Página等主程序确认实际ModeloCaminho后才显示Sucesso。
5. é necessário动作键时，点Modelo de 「设置按键」，按一次实体手柄 de 动作键，或在「手柄按键」Inferior拉框选择；占用 de 键é necessário确认替换。走路仍使用原来 de 站、走Controle。

单独一个 ONNX 文件缺少动作用途、关节顺序、站姿和运行参数，不能直接当成兼容部署包。Studio 会检查文件身份和合同，再调用本机 `robotd validate-policy` 预检 ONNX。没有可用的预检程序时会拒绝导入，不会把解压成功当成兼容。

AtualExecução程序 de 基础站姿eServo P Parâmetros在Inicialização时确定。 e 现有基础站姿、P Parâmetros或关节顺序不同 de Modelo不能直接热切换，Página会给出原因；é necessário先Concluído相应 de 部署适配。

## Modelo、动作、按键 de 关系

- 「已Instalação」：ModeloArquivo在库里；「Atual选用」：该用途已经选择这个Modelo；「正在执行」：主程序正在Execução它。
- 按键绑定到动作，动作使用Atual选 em  de Modelo。可设置 de 键为 A、X、LB、RB、十字Inferior。走路e独立Ficar em pé不作为普通动作键绑定。
- 实体按键录入需确认已卸力、五键ConfiguraçãoCompleto且为常规动作，并等待Configuração稳定两秒；若有直接起身等特殊动作绑定，使用Inferior拉框分配，避免录入按键同时触发原动作。
- 「取消绑定」只清除该按键；「恢复默认按键」恢复五个键 de 默认动作，都不会删除Modelo。
- 「恢复内置」把某个用途切回初次记录 de 默认Modelo，导入Modelo仍留在库里。
- 内置默认不能删除。导入Modelo仍被Atual用途引用时不能删除，先切换其他Modelo或恢复内置。

导入文件和显示名称存放于 Studio 的 state 目录；鸭子上通常是 `/var/lib/microduck-studio`。升级 Studio 时保留这个目录。默认模型文件保留在原安装位置。改名只改变显示名称，不改变模型身份。

## 开发Validação

`tests/test_models.py` 和 `tests/test_model_package.py` 使用临时模型和假主程序，不接触舵机。`tests/test_models_e2e.py` 使用真实 HTTP、部署包解析、模型库和无头 Edge，测试中的预检器与运行接口明确替换为本地测试实现。这些测试确认软件流程，不代替实际模型在硬件上的运动验收。
