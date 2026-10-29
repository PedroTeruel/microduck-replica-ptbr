# 连续语音 e 音乐互动Registro de validação

## R3 首版 e 实际问题

- 旧版按住说话由Usuário验收过；本轮按要求改成单击开/关。基线源码 aa583d1，连续版 cb68555。
- cb68555 在 Windows 78 项 em  63 por meio de、15 Linux 跳过；随后鸭子Superior 78 项全部por meio de。复查修复了提示声丢弃待播队列后卡住收音，e重复取消产生多清理线程 de 问题。
- cb68555 已安装到 duck-0de6，voice PID6663，安装文件哈希一致；robotd1099、padd1132、Studio982 的进程和启动时间不变。备份 `/var/lib/duck-echo/upgrades/20261025-222332-cb68555046`。模型和设备配置保留。
- Usuário实际试用反馈“有反应后又没有，隔了很久”。日志证实开启后约13秒才识别、约8秒复读，对应每句10秒Superior限，而非短句停顿。
- 暂停 duck-echo 后作3秒内存采样（不保存录音）：Direito声道 DC  em 值911.25、originalRMS988.89、去直流AC RMS368.03；固定-42dB阈值把环境当成持续说话。诊断后语音Serviço暂时停止，运动ServiçoInalterado。
- 7ff619c 针对该证据修正：每20ms去直流，非语音窗口学习底噪，2.5倍对比门限，60ms启动抑制、120ms预录。测试中0.6秒语音在0.6秒停顿后输出约1.32秒片段。Windows85项中70通过、15跳过；鸭子85项全通过，安装后PID10180，原服务身份不变。备份 `/var/lib/duck-echo/upgrades/20261025-223800-7ff619c4a1`。用户随后确认“短暂停顿后就复读了”。很高的启动底噪仍可能超过初始门限，不能称作任意噪声环境的完整VAD。

## 音乐互动开发Validação

- 音乐Serviço实现653304d；单流采集，私有UnixControle口、共享Vosk Model、流式提问、模式切换队列取消。Windows111项 em 94por meio de、17跳过；WSL此前110项全por meio de，之后补了1项DCTeste。
- 本地模拟节拍75/125 BPM、摇摆、变速、恒定音量、静音/过期、声道eDC偏置Validaçãopor meio de；这些不是实际歌曲曲风识别。
- 用电脑本地 SAPI 合成“感觉怎么样”“喜欢这种歌吗”“你喜欢这首歌吗”“不要问感觉怎么样”， e 不断播放 de 模拟125BPM伴奏混合，用实际VoskModeloTeste。三种问题各回应1次，否定句0次；问题开始后约1.95/2.20/2.44秒回应。无Rede、麦克风、喇叭或机器人RPC。2286191 改成每100msVerificação问题候选、仅对Completo候选对齐置信度，复跑四项均por meio de且没有词对齐告警。
- Studio增加缓存客户端e音乐生成器，复用已有动作会话、心跳、实体手柄优先e锁存清理；只发小幅头e身体意图。相关252项PythonVerificaçãopor meio de，9项NodeVerificaçãopor meio de。真实Studio+假机器人+模拟音频状态 de EdgeCompleto浏览器Verificaçãopor meio de：Preservado全部坐站录制/三次回放流程，新增监听状态/BPM显示、小幅头身体律动、关闭监听后停止、320/390/1440px无溢出。截图在本地 artifacts/audio-interaction-20261025/browser-music；这仍是假机器人输出，非真机跳舞验收。
- 复查修复了停止/重开 e 音乐启用交错 de 旧消费者取消竞态，eCabeça四个轴均遵守Usuário幅度限制（72d7560）。Stage6174ded按Usuário补充改为默认duck、不自动复读，实际开启短叫一次，原生叫声抑制窗口依据声库WAV头估计并留余量；录音复读Preservado显式echo/record，无新增独立按键。WSL e 鸭子均130项全por meio de，Windows130项 em 113por meio de17跳过；Studio新增小幅度回归后253项por meio de，9项Nodepor meio de。

## 收尾Superior机（东京时间10-26，设备日志为CST10-25）

- 语音6174ded已安装，PID15491；备份 `/var/lib/duck-echo/upgrades/20261025-230043-6174ded3f1`。安装前后robotd1099/padd1132/Studio982不变。按用户要求试了一次音乐模式短暂开启后关闭：控制口和麦克风正常，监听/音乐均回到false；坐站与策略状态未变化。此次仅开关通路，不是音乐辨识或动作验收。
- Usuário确认已站稳并停Inferior，第一次Web升级被真实policy_enabled=true门禁拒绝，尚未修改Serviço。只读日志确认已站起但未收到Web停策略Comando；按已约定 de “停Inferior（站好）”补发robot.stoperobot.enable{on:false,toggle:false}，两项accepted=true，回读standing、homed、policy_enabled=false后Instalação。
- 网页5f0d2ce部署成功，7个运行文件哈希一致；Studio PID18032，robotd1099/padd1132/duck-echo15491进程及启动时间不变。原12个用户状态文件逐个hash不变，备份 `/home/radxa/.microduck-backups/web-audio-20261025-824ebc3854`，权限0700。
- 根页、healthz、pad.js、audio-interaction.js、audio-ui-state.js、motion-studio.js/css、motion-heartbeat.js均HTTP200，JS/CSSConteúdo哈希匹配且no-cache。WebSocket全量快照é necessárioUsuário登录，未绕过登录。
- 用 e Studio相同 de radxaUsuárioExecução已InstalaçãoAudioClient，Leitura新语音Serviçoavailable=true；实际进程Parâmetrosreply-mode=duck；Controlesocket0600、Diretório0700。监听关闭时未增加麦克风采集。此时Placa principal约76.9°C，短暂开关时约75.6°C；未Teste长时间音乐负载。设备回读Bateria约10%（7.17V），已提示充电/换电后再验收身体律动。
- Usuário随后描述短按R3开启时有叫声，并询问持续接收逻辑；解释为一次开启持续监听，停顿只分句，suporta口令触发动作，等动作Concluído再说Inferior一条。Usuário追加“关闭也要不同提示声”，bda4f38加入显式R3/Web关闭 de coo，自动断开/退出仍安静取消。134项Teste在WSL e 鸭子均全por meio de，Windows117por meio de17项跳过；独立复查73项 em 72por meio de1跳过，无剩余阻塞发现。
- 最终语音bda4f38已上机，PID21412，备份 `/var/lib/duck-echo/upgrades/20261025-232504-bda4f384b8`；只重启语音服务，robotd1099、padd1132、Studio18032身份不变。设备开关检查从false开启再关闭，分别观察到原生chirp/coo的aplay进程，麦克风数据到达、无故障，最后listening/music=false；坐站/策略状态前后均standing、homed、policy_enabled=false，未启动律动。此时内存约125MiB、主板76.9°C；没有长时间音乐负载结论。

## Versão交付

源码改动回收到studio-dev，冻结源码包与manifest保存在本地 `artifacts/audio-interaction-20261025/release/`，记录独立语音/网页实际运行提交、依赖与ASR模型归档哈希、设备备份位置。该产物是源码与验证基线，不是新系统镜像或通用OTA发布。原动作记录保留，未重启robotd/padd、修改无线设置或训练模型。

## 尚待实际验收

真人对开/关提示 e 日常坐站口令 de 最终复核；手机/音箱实放音乐Inferior de 节拍e提问；不同音乐感觉 de 叫声；Web律动 de 实际姿态效果。不能把模拟音频e假机器人Verificação记作真实音乐动作已经por meio de。电量回读较低，先充电或换电，再进行身体动作验收。
