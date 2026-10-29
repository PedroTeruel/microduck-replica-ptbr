# WebSoftwareAtualização、语音坐站 e Imagem共用组件包

Usuário已批准[在线升级流程方案](../../在线升级流程方案-20261027.md)，要求实现并把本地语音Sentar/站起纳入，新Imagem随后使用相同Instalação包。自由AI语音仍暂停，不合入其草稿。范围是现有HD1910/Radxa Zero3W复刻栈 de Web、匹配helper e duck-echo程序；robotd/padd/Modelo/OS保持现有已ValidaçãoVersão。

## 已Validação de 引擎选择

复用底图真实ARM64 updaterd0.15.1/rev1fa84386/API37，复制到独立root拥有 de 稳定Caminho，不在普通Software包内Atualização它。2026-10-27已在WSL用现有qemu-aarch64 e 只读提取 de 五个共享库ExecuçãoVersão查询、自定义profile --self-test e 实际IPC，确认local_dir、组件software、Restart、command健康Verificação、exact/from_dir/dry_run可用。没有另写签名/事务/回退引擎。

组件`software`作为单一事务：`/opt/microduck/software/releases/<semver>/{studio,duck-echo}`及current原子链接；helper随Studio版本并使用稳定root包装入口。稳定systemd单元、升级器、健康检查、发行公钥与用户数据在此目录之外。配置auto_apply=off，不设置周期检查。仅重启microduck-studio与duck-echo。robotd/padd不被更新或重启。

ASR依赖/模型位于`/opt/microduck/resources/{asr-deps,models}`，通过明确参数交给语音服务；默认actions+toggle+duck，启动不自动监听。Mic3R初始化作为稳定启动准备，保留原声卡初始化且不触碰喇叭音量。R3开关提示音及已验收坐站语义保持。

## 包、签名、Verificação e Baixar

整套版本首选`2026.10.27`（后续同日修订使用SemVer允许格式），独立源码SHA/文件hash登记。使用维护者自己的minisign发行公钥；私钥只在本机私有签名目录，不能进Git/安装包/镜像。首个包由冻结Git运行白名单构建，不包含开发状态、Key或日志。

在线源固定为用户仓库fanhao375/microduck-replica的`microduck-software-v*`正式发布，不能把镜像release误当组件release；无匹配发布显示“尚无发布的软件更新”，网络失败不显示已是最新。内置源/信任配置root管理，网页不提供任意root命令、安装路径、发布源覆盖。

分发外包只含一个版本的四个普通文件：`<version>.manifest.json`及签名、组件压缩包及签名。manifest.channel=software，url为本地裸文件名，hash/大小/版本/源码/兼容性信息固定；同一外包既能HTTPS下载也能网页上传。外包严格限制数目/总大小/文件名，拒绝绝对路径、..、链接、重复成员和特殊文件，未验证代码不执行。

现有引擎无download动词，checkResultado也不返回artifactURL。以小型受限ControleServiço做发布元信息查找、限量Baixar/外包缓存 e 任务记录，缓存root私有；交给真实引擎exact/from_dir/dry_runConcluído签名、hash、兼容、archive e required-filesValidação，才显示可Instalação。实际Instalação再调用相同exact/from_dir，复用同一个缓存且重新Validação。元信息展示都是不可信纯文本。若dry_run de 运动预检尚不满足，显示已Baixar但待停稳Validação，不能假绿。

ControleServiço独立于Studio，Instalação/回退任务不依赖WebPor favor求存活；任务ID、阶段/错误/Resultado落在Atualização状态Diretório，Página刷新或Studio重启后可读回。Baixar、Validação、准备、应用、健康Verificação、Concluído、回退/Falha分开显示；有限并发 e 单次Instalação锁。source/catalogURLeEnviar/Baixar限额固定，HTTP只允许明确loopbackTeste；公网TLS校验、限次受控重定向，不把凭据带到陌生目标。

## Instalação前置 e 恢复

Controle层在dry_run/apply/rollback前读真实robot.busStatus，要求motion/control/homed、policy_enabled=false、关节反馈新鲜/无实际运动，并VerificaçãoStudioServo/标定/录制回放会话、语音监听/音乐已关闭。缺少回读拒绝；不能因upstream引擎允许robotd缺席就跳过复刻栈Instalação保护。Verificação稳定供电/低电 e 磁盘余量，错误Instruções具体原因。Instalação期间拒绝新 de 运动/Configuração操作，重连后解除Atualização占用，不能靠按钮禁用当Serviço端锁。

稳定healthComandoValidaçãoAtual清单、实际Execução程序Fonte、Studio healthz+静态资源、duck-echoControlesocket、é necessário de ASR资源erobotd/padd未被重启；Serviçomissing/active但未就绪都不能Sucesso。VerificaçãoFalha由原引擎恢复previousVersão链接并Inicialização旧Serviço。没有破坏性外部迁移hook；首次新Imagem种Inferior合法基线，之后 de 每次升级PreservadoSuperior一版。Usuário标定/WiFi/配对/录制/APIKey均在VersãoDiretório外，禁止用发布者state覆盖。断电/执行器崩溃恢复按原引擎持久事务验收，不夸大未做过 de 物理断电Teste。

一次性bootstrapPreservado旧Instalação/单元 e Dados，Instalação稳定组件Configuraçãoe入口，使用同一签名包/原引擎initial install；校验Falha恢复旧ServiçoConfiguração。新Imagempor meio de相同installer de offline rootfs入口Instalação相同签名包，允许显式构建用QEMUComando，不在x86宿主执行ARM代码。普通升级不改OS/内核、Execução时或个人Rede。

## Web e 权限

设置页顶部“SoftwareAtualização”：Atual套件/组件Versão、AtualizaçãoInstruções、VerificaçãoAtualização、Baixar/Enviar包、待InstalaçãoVersão、立即Atualização、退回Superior一版 e 真实进度/Resultado。使用现有视觉 e 320px布局。所有HTTP复用Web登录、Host/Origin/CSRF，要求设密码（明确localhost开发模式除外），no-store，输入白名单 e 大小限制。backendArquivoeRede工作不阻塞主事件循环。

Instalação开始显示Web可能短断，自动重连并按任务记录判Sucesso；本地缓存包可离线Instalação/回退。没有真实发布源时不能演示假最新Versão；真实本地HTTPS/loopback providerTesteBaixar链路，实际引擎在WSL临时rootTeste签名/Instalação/回退。

## 验收 e 交付

FalhaTeste先行；实际旧ARM引擎+本地签名包por meio de首次Instalação、新版切换、坏签名/错hash/越界包/ServiçoFalha自动恢复 e 任务崩溃恢复。真实本地EdgeValidação登录/CSRF、无发布、Verificação/Baixar/Enviar/Instalação/重连/回退/错误/窄屏；不能仅mock一个Sucesso返回。语音相关原Teste e ExecuçãoArquivo/资源匹配，不重写已验收识别逻辑。Superior机冻结清单、备份、真实停稳Verificação e UsuárioDadoshash/robotd/padd身份Validação。新Imagem构建、解压只读Verificação、FirmwareModelohash/干净身份/无私钥eAPIKey核对；新卡真人首装e本次Imagem声学仍需实际验收，旧版Sucesso不能替代。
