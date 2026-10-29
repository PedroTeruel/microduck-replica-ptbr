# IMU 初始方向可重复标定

Usuário重新授权 de 是“初始方向保存后仍能重新做、Instalação四元数也能重新校验”。之前取消 de 采集Algoritmos改造保持取消：不改变粗校 de 静止3秒／前倾3秒／扶正再 verify-imu，不改变站姿精校 de 方向采集Algoritmos。只做本地实现 e 模拟Validação，不Conexão板子，不构建或Gravação新Imagem。

## 已确认 de 问题 e 设计选择

`CoarseCard` 在 mount.verified 不是 false 时直接隐藏；后端 coarse/verify 又只接受 commissioning。因此已有错误配置或改变装法的用户无法通过网页回到初始粗校。只显示按钮仍不能完成恢复。motion 下直接写方向会绕过原 runtime 验证；整套 calib-commit 会重置关节零位。采用受控地临时返回 commissioning，保持原 verify-imu 流程。

## Usuário流程

1. IMU 页始终展示“初始方向标定（可重新做）”入口。已确认时不自动开始，点击“重新标定方向”并明确确认后才进入。
2. motion 模式必须先由Usuário卸力，并有新鲜回读确认扭矩OFF、策略关闭、无起身或临时增益恢复；保持双手扶住。重新标定按钮Instruções会重启主程序，但Preservado关节标定e原IMU方向备份。
3. 使用受控 helper 切回 commissioning；已有 factory commissioning 直接打开原粗校，不新增覆盖Arquivo。
4. 原样采静止、采实际前倾，算方向，回正后点击主程序Validação，再按提示前倾。ValidaçãoFalha可重采，保存前不改旧IMU方向。
5. 原来处于 motion  de 重标定会话在ValidaçãoSucesso并回读一致后恢复原运动模式，保持卸力。原本 factory commissioning  de 流程不擅自切模式。粗校Sucesso后入口仍可再次进入。
6. 会话跨Web刷新、Studio重启e板子断电可恢复，界面显示“重标定未结束”，可继续Validação或明确取消并恢复进入前备份。

## 实现边界

- 新增固定 helper 动词 `imu-recalibrate`，仅接受 enter/status/finish/cancel，参数严格校验，无任意路径、命令、服务名。与 bus-take / calib-commit 共用锁，并阻止这些写操作干扰正在进行的重标定会话；卸力不被锁挡住。
- enter 使用新鲜双快照门槛、保存Atual主程序有效ExecStart、主／saved标定、ControleServiço状态 e 源信息。只允许直接robotdComando；生成唯一自有 de 持久commissioning drop-in，并先持久保存带Versão e 会话ID de manifest。重启后须读到commissioning e 卸力。不能修改或删除出厂drop-ine其他人 de Configuração。
- original runtime verify 会把 motion_enabled 写成 false，并保存主／savedArquivo。finish 必须只恢复进入前 de  motion_enabled，Preservado新Validação de AtualIMU方向； e 进入前逐项比较，除该源Instalaçãoe motion_enabled 外任何关节零位／方向／限位、其他IMUe设置均不能变化。复用原子Gravação、Arquivo校验、CompletoExecução回读 e 回滚。删除覆盖Arquivo前核对Conteúdo/所有权/originalExecStart，原状态不明则拒绝。
- enterFalha恢复进入前状态；finishFalha恢复重标定 de 安全commissioning状态且Preservado可重试会话；cancel明确恢复进入前标定 e 模式。不把取消后 de 旧方向称为本次新Validação。
- 后端粗校／Validação沿用原计算 e FirmwareComando。只有后台确认本次verifySucesso并且回读 source、verified、quat 一致，才Por favor求finish。不能仅凭helper或RPC accepted显示Sucesso。
- 前端不手工编辑四元数、不翻转Modelo符号、不改站姿精校 de 识别Algoritmos。只新增重做入口、进度、取消e恢复提示。

## Validação e 交付

先补FalhaTeste，再实现。覆盖verified=true入口、两步确认、已在commissioning直接重做、motion未卸力拒绝、原流程Sucesso／Falha／重试、持久会话重开、四元数回读不一致、runtime关闭motion_enabled后finish恢复、非2048零位 e 其他Parâmetros保持、覆盖Arquivo被改动拒绝、重启Falha回滚、冲突操作拒绝。跑原IMU计算／向导、helper／HTTP、浏览器回归。交付本地代码并Instruções明天先Teste卡部署Validação，再打包Imagem；不把源码Atualização称为已ConcluídoImagem。
