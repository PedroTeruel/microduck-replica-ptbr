# Qinmo IMU：Web选择 e Instalação方向Validação

这份功能通过 `2026.10.28` 签名软件包分两步交付：先更新网页 / 语音，重连后在同一软件更新页承托卸力并明确确认可选的主程序更新。无需重烧 SD 卡；仅网页版本变化不能证明主程序支持秦墨。完整入口和旧卡的一次性引导见 [20261028 更新说明](软件更新与Qinmo使用说明-20261028.md)。本版尚未完成实物升级与秦墨实物的站立、行走验收，也未据此发布新镜像。

已有 FT6、IMU-to-DXL 继续默认自动识别。FT6 e自家小板使用已知身份；通用 Dynamixel 2.0 只确认兼容布局。Qinmo  de 文档没有可核验 de 唯一厂商身份e自动单位识别依据，因此é necessário在同一个 IMU Página选择一次。之后每次开机会沿用保存 de 类型，不é necessário重复选择；“已Configuração Qinmo”不表示自动认证了厂商。

1. 双手扶稳鸭子，在Web点“失能（卸力）”，等主程序确认失能。正在Inicialização、还没进入Controle de 受suporta状态也可走恢复流程；这不代表Web知道真实扭矩已关闭。
2. 在 IMU 页的“总线 IMU 类型”选 `Qinmo · Feetech`，点“保存类型并重新连接”，再确认已扶稳。
3. 等Página回到标定模式，按原来 de 静止、前倾步骤采集并计算方向，再交给主程序Concluído摆正e低头Validação。重新选择会清除旧方向 de 确认状态，不能跳过Validação。
4. ValidaçãoConcluído后Preservado选定类型。原来在正常Controle模式 de 会话会回到Controle模式并失能；原来属于出厂标定 de 会话继续按首次使用清单“写进主程序”。

Página分别显示“Configuração类型”e“实际Conexão”。Qinmo 角速度采用“original值 ÷ 16.4 °/s”；旧总线板采用“original值 × 0.0175 °/s”。ConexãoFalha时仍可查看已保存类型、取消会话并恢复原Parâmetros。Inicialização恢复 de 取消会停留在安全标定模式，可重新选择并Validação，不会自动Inicialização运动。

刷新Página或重启后，未Concluído de 会话e原Configuração备份仍在。普通Controle模式 de 取消恢复主 / saved Configuração、原标定e原模式；Falha时Preservado可恢复会话。Servo总线占用、SoftwareAtualização、其他标定会话、活动或未知Controle状态都会拒绝切换。

先在软件更新页确认匹配的主程序实际运行身份已核验；本版使用匹配 robotd 和 helper 0.8.0。支持证据是新增的 `configured_imu_profile` 诊断字段；缺少时页面明确提示更新主程序，不会写不受支持的配置。可选主程序更新只支持本项目已知 20261027 基线，自定义或其他构建需维护者核验。没有旧升级入口的卡仍需一次 SSH 引导，已有入口且受支持的用户可全程在网页操作，无需编辑配置。当前首版仅支持 Feetech 舵机总线的 Qinmo，未支持 Qinmo 的 DXL2 模式；I²C 芯片沿用原流程。

事务限制 e Teste见 [helper InstalaçãoInstruções](../software/studio/deploy/INSTALL.md) e [SoftwareRegistro de validação](superpowers/verification/2026-10-27-qinmo-studio.md)。
