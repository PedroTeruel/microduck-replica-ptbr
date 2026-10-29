# 鸭子本地语音 e 听音乐

新版默认单击手柄右摇杆按钮 **R3** 开启监听，短“嘎”一声；松手说话，再次单击关闭，低“咕”一声。网页开关采用同样提示，只在实际切换时叫一次；Select、断开和服务退出等自动取消保持安静。默认 `ECHO_REPLY_MODE=duck`：已启用声控时执行明确坐站口令，音乐模式回答明确音乐问题；普通或未识别的话语保持安静，不复读人的声音，也不提供自由聊天。关闭会取消待处理的识别并停止录音/复读，再播放关闭提示。

提示声使用Instalação音效库 de  WAV 时长，再加 100 毫秒Inicialização余量e 350 毫秒尾音，期间暂停收音；提示声结束后稍停再说话。每次ServiçoInicialização仍默认关闭监听e听音乐。

录音回放保留为单独的 `record` 命令，暂不绑定新按钮。明确需要旧复读行为时，可设置 `ECHO_REPLY_MODE=echo` 或传 `--reply-mode echo`；此时默认音调和语速提高到 1.25 倍，设为 1.0 可恢复原声。

本轮语音eWeb音乐面板已por meio deSSHSuperior机，分句问题经真人复测恢复。外放音乐声学e身体动作效果仍待真人验收，SoftwareTeste不代替这两项。详见 [本轮Validação](../../docs/superpowers/verification/2026-10-25-audio-interaction.md)。Inferior文初版Histórico验收对应按住说话 de Versão。

这是独立Serviço，por meio de SSH Instalação，沿用主程序 de 坐立动作接口，不重新Gravação或重启 robotd/padd。只读旁听实体手柄，不独占输入设备。声音只放在内存，不保存对话录音Arquivo。

**初版Histórico验收：2026-10-25 por meio de SSH 部署到 duck-0de6（192.168.0.102），设为开机自Inicialização。真实麦克风采集、变调回放、实体手柄 R3 按住/松开跑通。45项SoftwareTestepor meio de；Usuário随后明确确认真人语音“LevantareSentar都Sucesso”。**

实际手柄为 Nintendo Switch Pro Controller，输入设备 /dev/input/event4。Instalação前后 robotd PID 1090、padd PID 1128  e Inicialização时间均未变化，Controle环保持 50 Hz。已设置Serviço enabled，未为此重启整机；已配对手柄开机回连后，复读Serviço会自动检测。

适用Hardware：64 位 Linux、TLV320AIC3104 HAT、已有正常 de 喇叭播放通路、suporta BTN_THUMBR  de 实体手柄。采集 de 是项目初始化脚本使用 de  Mic3R（Direito声道）。não suportaWeb模拟手柄 de  R3。

## 听音乐 e 明确提问（已Superior机，外放 e 动作效果待验收）

Web可分别Controle监听e听音乐；打开听音乐会同时打开麦克风，关闭监听会一起关闭音乐模式。R3 eWebLeitura同一个实际监听状态。实体手柄关闭时仍可从Web开始收音；真正 de 手柄断开、Select、输入溢出eServiço退出会取消Atual输入。

音乐模式复用这一条麦克风流，按短时能量起音 e 包络重复证据估计节奏e粗略感觉。轻快、舒缓、摇摆只是节奏反馈，不代表准确曲风或情绪识别。音乐不会送去普通复读或坐站口令识别。说“感觉怎么样”“喜欢这种歌吗”等明确问题时，单独 de 本地流式识别器复用已有 Vosk Model，按近期可靠节奏调用原生 chirp、coo、greet 音效；没有可靠节奏用 inquire。Completo问题 de 逐词置信度至少 0.8；稳定Completo partial 保持 0.5 秒pode在音乐持续时回答，回应间隔至少 4 秒。提示声e尾音期间抑制自身收音。

连续采集Por favor求 20 毫秒 period、80 毫秒 buffer；节拍时间按样本推进，避免驱动成批送达造成节奏失真。重复性估计只Preservado有限数值包络，每秒最多计算五次，状态Leitura复用缓存。平滑音乐通常é necessário数秒重复证据；没有清晰重复、声音停止或采集过期时不生成节拍。稳定读数只是音量包络 de 周期估计，强弱拍、倍速 e 混合节奏仍可能存在歧义；不同证据冲突时优先较强suporta，不能保证唯一 de 音乐拍点。

仅 toggle 模式提供私有 `/run/duck-echo/control.sock`（目录 0700、socket 0600）。每连接一条 UTF-8 JSON 行，最多 8192 字节，只支持 `{"method":"status"}` 或 `{"method":"set","listening":true,"music":true}`；布尔值必须是 JSON true/false。返回监听、音乐、节奏和短故障信息，不提供录音、转写或任意机器人命令。服务重启默认关闭。hold 保留旧的按住说话行为，没有网页音乐控制 socket。

音乐问答é necessário已Instalação本地识别Modelo。Modelo未就绪会在状态里显示音乐识别故障；单独 de 录音回放 e 显式 echo 模式仍可使用。Software假 ALSA/UNIX socket Teste不等于真实外放音乐、混响e提问识别已por meio de验收。

##  em 文口令模式

本地声控模式：说“Sentar”“Sentar来”“Levantar”“起立”等明确短口令时执行对应动作；普通话语默认不回放。“不要Sentar”、多个动作混在一句里、低置信度识别不会触发动作。按 Select、手柄断线或输入溢出会取消未执行 de 旧口令并关闭持续监听。

已经在鸭子 CPU Superiorpor meio de 14 条合成Teste语音，覆盖正向口令、否定、引用、混合动作e普通话语，识别约 0.26–0.51 秒，峰值内存约 144 MB。使用含未知语音 e 否定形式 de 小词表，避免Completo听写 de  6–7 秒延迟。Usuário随后使用实际麦克风 e  R3 Teste，并确认站起eSentar均Sucesso。

验收后曾出现 SSH  e Web均不可达。后续经蓝牙配网恢复Conexão，将这台鸭子固定到 TP-LINK_5G_6494（5240 MHz），关闭其他已保存Rede de 自动Conexão e  Wi-Fi 省电。Web连续 20 次访问均Sucesso。语音关闭约 160 秒、开启约 180 秒 de 蓝牙记录均无断链，手柄Dados最大间隔均不足 49 毫秒；开启期间Concluído真人复读、Sentar e 站起，已取得两次动作 accepted=true  de 日志。Usuário确认复读e摇杆均正常；另一次看到灯闪时，动作也正常，记录 em 没有对应断链。此前日志确有真实掉线，尚未确定其原因，短时复测不能证明长期间歇问题彻底消失。详见 docs/network-20261025.md  e 本地 artifacts/duck-network-20261025/final-verification.json。

使用 Vosk small-cn-0.22，Modeloe依赖放在 /opt/duck-echo 内，不Enviar语音。Completo录音不GravaçãoArquivo，日志只记口令类别、置信度e动作回执，不记普通对话文本。每次会先读Atual坐立状态，重复“Sentar”不会反向站起；主程序拒绝姿态Por favor求时不绕过。坐着卸力后 de 恢复仍遵循现有Firmware要求。

单击模式在说话停顿后处理一句，最长 10 秒；识别Resultado超过 6 秒不再执行。自己复读e动作提示声期间会抑制收音，尾音结束后继续监听。普通自动分句适合安静环境，持续外放音乐时应开启音乐模式。

需要恢复旧版按住说话时，在 `/etc/default/duck-echo` 中设置 `ECHO_TRIGGER_MODE=hold`，然后只重启 `duck-echo` 服务。hold 模式仍在松开 R3 后处理；声控录满 10 秒时取消这一句。

```bash
# 先更新运行文件，再准备本地识别依赖和模型。离线安装可提供 ARM64/cp313 wheels。
sudo python3 /home/radxa/duck-echo/install.py
sudo python3 /opt/duck-echo/install_speech.py --mode actions \
  --archive /home/radxa/duck-echo/vosk-model-small-cn-0.22.zip \
  --wheels /home/radxa/duck-echo/arm64-wheels

# 观察识别，暂不执行动作：
sudo python3 /opt/duck-echo/install_speech.py --mode shadow

# 关闭口令识别（需要复读时另设 ECHO_REPLY_MODE=echo）：
sudo python3 /opt/duck-echo/install_speech.py --mode off
```

来源：[Vosk 官方模型](https://alphacephei.com/vosk/models)、[ARM64 安装支持](https://alphacephei.com/vosk/install)。

## SSH Superior机

将本文件夹上传到鸭子的 `/home/radxa/duck-echo`。在鸭子上执行：

```bash
cd /home/radxa/duck-echo
arecord -l
python3 duck_echo.py devices
sudo python3 install.py prepare-mic
python3 duck_echo.py probe --seconds 3
python3 duck_echo.py record --seconds 4
sudo python3 install.py
journalctl -u duck-echo -n 30 --no-pager
```

`probe` 的 3 秒内在麦克风旁说话，输出包含 peak、rms、dbfs；静音/过短/采集失败时退出码为 2。`record` 命令在 4 秒内录音，然后播放；播放进程退出成功才会输出 `playback_ok: true`。进程成功仍需耳朵确认实际音质和喇叭响度。

Instalaçãoé necessário sudo；Serviço以 radxa UsuárioExecução，并加入 audio/input 附加组。依赖系统 Python 3、alsa-utils e systemd，无需Baixar Python 包。

## 原声 e 设备设置

```bash
sudo nano /etc/default/duck-echo
# ECHO_PITCH=1.0 为原声，1.25 为较高较快的声音。
# ECHO_CHANNEL=1 为 Mic3R 右声道；仅硬件确实接左路时改成 0。
sudo systemctl restart duck-echo
```

仅重启复读Serviço。声卡名不同则修改 ECHO_CAPTURE/ECHO_PLAYBACK；本Instalação脚本 de 麦克风设置专usado para aic3104，其他声卡须另按其Hardware确认采集通路。

## 诊断 e 撤回

- 没有手柄时Serviço等待，Conexão后自动找到suporta R3  de  evdev 设备；Inicialização时 R3 已按Inferior需先松开再试。多个手柄会监听第一个。日志写出实际设备名 e  event Caminho。
- 录不到声音：查看 `arecord -l`、probe 电平和 Mic3R 焊接/线路；尚未验证本机硬件，不把静音归因为软件或焊接。
- 播放提示 Device busy：松开原有发声扳机后再试。原生音效 e 复读可能竞争Hardware播放通路；本版会报错，不会停止 robotd 或篡改全局 ALSA 播放Configuração。
- 变调同时改变语速；本版suporta按键后识别坐立短口令，不含连续唤醒、自由对话e保持语速 de 变声。

```bash
sudo systemctl stop duck-echo
sudo python3 /opt/duck-echo/install.py uninstall
```

卸载会关闭复读Serviço并恢复Instalação前 de 麦克风采集设置。程序e备份留在 /opt/duck-echo、/var/lib/duck-echo；喇叭音量不受该Instalação脚本修改。Instalação或升级Falha时会尝试恢复本次修改 de Arquivo、采集设置e此前 de 复读Serviço状态；恢复Falha会明确输出错误。

## 离线Validação

```bash
python3 -m unittest discover -v
python3 duck_echo.py --help
```

Linux 集成Teste用临时假 arecord/aplay/amixer 程序Execução真实子进程，覆盖录放、限时、断线、声卡忙碌、麦克风设置恢复；不代表真机声音已经验收。
