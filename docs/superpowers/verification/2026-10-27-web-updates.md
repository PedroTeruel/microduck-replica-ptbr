# WebSoftwareAtualização、本地语音 e 新Imagem：交付记录

日期：2026-10-27（东京时间）。Usuário要求实现Web在线升级，将本地语音“Sentar／Levantar”纳入新Imagem；随后确认“暂时关着，先Concluído本地SoftwareeImagem”。自由AI语音对话保持暂停。

**已ConcluídoSoftware、签名包、首次引导输入包e匹配Imagem。Usuário后续授权推送 e 公开发布，master源码、20261027 LatestImagem e 2026.10.27Software发行均已Concluído，见[公开发布记录](2026-10-27-web-updates-publication.md)。没有部署到关闭 de 鸭子或烧卡，旧卡首次引导 e 新Imagem实物验收仍待开机后进行。**

## Versão e 产物

运行文件冻结在`e382f0741d7dfe4e972605e2843474df7219cade`；其后`1b7416e`只修正三项既有浏览器回归测试的等待条件，运行文件无差异。软件版本`2026.10.27`。最终文档提交另记在Git历史，不改变包内运行来源。

工作区根目录的`复刻镜像-20261027`、`软件升级包-20261027`为本地交付。完整文件大小/hash保存在`artifacts/software-updates-20261027/delivery.json`；镜像、升级包和首次引导归档均附SHA256文件。

| 产物 | SHA256 |
| --- | --- |
| `microduck-replica-20261027.img.xz` | `91ab5550e0f409d634722718a638d6e9615412b779b5d26c0af5c777056d0194` |
| `2026.10.27.software-update.tar` | `b6543c9f3a2ad6477106410dbed9753be9fa37c61b79ea0350767a18229d0e55` |
| `microduck-bootstrap-20261027.tar.gz` | `866f8d49e3097133ab911debda9c4fdc66b9f02b867a789aadfb9793b99b3610` |
| 发行公钥 | `0878853a92b10c9196c5b63e02087664923c576e6bc2e064d3bbdcc1be056bf5` |
| 语音资源清单 | `2639f40cd196c7f64fd5adef2220c135b82186c5ebe22ff527c57fde7ae66b9c` |

镜像741,604,104字节，网页升级包5,683,200字节，首次引导归档57,811,043字节。引导归档只含冻结公开源码、原ARM64引擎、公钥、签名包、ASR资源、许可与操作说明；它不是网页上传包，也未执行到鸭子上。普通网页上传使用单独的`.software-update.tar`。新镜像已完成同一bootstrap，无须重复初装。

## 实现 e 边界

- 设置顶部新增SoftwareAtualização：Versão、Verificação、Baixar、离线Enviar、Validação、Instalação、任务状态、重连读回 e 回退。沿用登录、Host/Origin/CSRFeno-store；白名单不接受任意Fonte、Caminho或shell。
- 一套签名software组件管理Studio、匹配helper e duck-echo。执行器/健康Verificação/公钥、UsuárioDadoseASR资源位于Versão树外。冻结GitExecuçãoArquivo白名单，不含Teste、日志、Usuário状态或私钥。外层USTAR四Arquivo严格校验，内层tar.zst由原引擎Validação。
- 使用原镜像实际ARM64 updaterd0.15.1，源码`1fa84386f07884e27866411bc1ba166977bced95`、IPCAPI37，自定义profile/from_dir/dry_run；没有另写事务切换引擎。`auto_apply=off`，无周期检查/自动安装。
- 独立root控制器通过有peer权限检查的IPC提供固定动词；发布源固定为`fanhao375/microduck-replica`的`microduck-software-v`正式发布。无发布、网络错误、下载成功和安装成功分别显示。首个2026.10.27软件Release已公开；同版镜像检查时没有更高版本是正常状态。
- 原引擎还会尝试延迟重启updaterd/btd，稳定Serviço边界拒绝它们，仅允许Web e 语音Serviço。离线构建禁止修改任何宿主Serviço；健康Verificação使用真实绝对systemctlCaminho。
- 切换前Verificação新鲜总线回读、实际站姿/策略关闭、15关节/速度/时间、供电、空间 e 录放/标定/Servo/音频占用。marker e 跨进程锁同时保护Webe实体R3，取消迟到ASR，避免预检 e 坐站Comando竞态；急停、卸力e关闭监听Preservado。
- 首次引导核对旧Serviçodrop-in，覆盖已知10-image.conf，拒绝未知自定义InicializaçãoConfiguração。旧状态经固定UID、无跟随Diretório描述符、类型/链接数/大小Verificação后复制到私有暂存，再原子迁移到空目标；不递归chownUsuário可Controle树。已有非空新状态Preservado；异常恢复原Serviço e 程序入口。
- Studio普通UsuárioExecução，显式外部StateDirectory/LogsDirectory，程序树root拥有不可写。语音默认actions/toggle/duck、Inicialização不监听，明确共享ASRCaminho、Mic3RInicialização准备 e audio/input权限。

## 实际Validação

| Verificação | Resultado e 范围 |
| --- | --- |
| Studio完整非浏览器回归 | `STUDIO_E2E=0 py -3.13 -I run_tests.py`：1201项，268.296秒，OK，75跳过。Windows AF_UNIX语音状态线程有已知环境提示，不宣称Windows原生音频链路通过。 |
| 本地语音 | 155项，OK，18跳过；另在WSL实际flock、迟到ASR取消等12项针对性Verificaçãopor meio de。 |
| Atualização器Linux | 独立质量审查18项por meio de，含真实UID65534鉴权/日志Gravação、符号链接 e 迁移竞态拒绝。 |
| Imagem侧 | 128项por meio de，49.590秒，含错误hash/未知Caminho、Completo组件输入、共享签名bootstrap e Falha不记Sucesso。 |
| 原ARMAtualização器/QEMU | 10项Verificação全真：签名首次Instalação、dry-run、错hash/manifest签名拒绝、27→28切换、手动回退、健康Falha自动回退、持久切换后kill引擎再Inicialização恢复、Serviço范围。没有向实际robotd发运动Comando。 |
| 最终真实Edge | e382f07实际Studio/Controle器，1项17.394秒por meio de；1440/390/320布局、无发布、Baixar待停稳、Validação、Instalação、刷新任务、回退、Enviar、坏包 e 额外root字段拒绝，Controle台错误为空。引擎/设备预检为明确Teste替身；原引擎事务另有实测，不把替身称为真机升级。 |
| 独立规格复查 | 503b7cfpor meio de：9Controle器+4语音Verificação，R3互斥P2已关闭。 |
| 独立质量复查 | e382f074por meio de：外部状态/日志、旧状态无跟随迁移问题已关闭，无剩余P1/P2。 |
| Imagem实际ARM Python | 只读Imagem em  de Python3.13.5/VoskSucesso加载 em 文Modelo，静音识别为空；ARM Python经QEMU以UID65534Inicialização不可写源码 de Studio，healthzSucesso、外部状态/日志可写。机器人端点全部关闭。 |

一次包含旧浏览器用例 de CompletoExecução曾得到1200项、3Falha、5跳过。已 e 18cd3基线对照，定位为Bateria值在EdgeInicialização前已被滤波器锁定、Servo关闭状态早于异步记账Concluído de Teste竞态；1b7416e只修Teste同步，不改产品或减弱原断言。原三项Falha重跑35.020秒por meio de，随后Superior述1201项非浏览器Completo回归por meio de；没有再次跑完全部旧浏览器套件。

报告位于`artifacts/software-updates-20261027`：studio-unit-regression.log、image-tests.log、engine-acceptance.log、browser-final/browser.json及截图、image-verification.json、native-voice-check.json、unprivileged-startup.json、build-image.log、verify-image.log和delivery.json。

## Imagem构建 e 只读验收

沿用已核验底图 e Execução时payload，不换步态Modelo：

- 底图SHA256：`652dd54e70f49fd3633058d5ed9bbb2f63b435648da2346dfbfa60fcaa4c5bcc`。
- payload SHA256：`370f64af5c690eeebab429f4c59d9c5d00883b5cf1e7f0d0e2c18d4afe45998d`。
- robotd SHA256：`edf182edb7bf11aeeeedfdab98170ab2ec48a9ec18417f9b68c744b0a60c6d16`；来源`0791fcd44f71c705dc8bb0fbcde405593b52d19b`。
- 原updaterd SHA256：`d5f9086bae5c2ec10ba75fc2d41c27578236a12d9a6364bffa8d9315fda97fa6`。
- Vosk small-cn0.22 ZIP SHA256：`3af8b0e7e0f835ae9d414ce5df580237a3cfb08d586c9fbbb0f7ff29ad5b14ba`；11套ARM64/cp313 wheel、304个资源文件、80,414,834字节。模型Apache-2.0，依赖许可证保留。

冻结Git归档构建签名包，现有WSLImagem脚本调用同一共享bootstrap。独立解压交付xz，SHA/xz/分区/e2fsck只读Verificaçãopor meio de，再ro,noload挂载验收并卸载：

- 原Execução时/Modelo39项hash、9个Modelo引用一致；15颗Servo保持未标定、IMU commissioning默认正确。
- software350个ExecuçãoArquivo逐项hash一致，current相对链接、root拥有不可写；Fontee382f07e包hash一致。
- 独立升级器/公钥/Configuração、自动应用关闭、稳定Serviço、State/Logs权限 e 90覆盖正确，sudoers语法por meio de。
- 304个语音资源Arquivohash一致，Mic3R准备、明确ASRCaminho、actions/toggle/duck默认一致，实际ARMModelo加载por meio de。
- 无个人Wi-Fi、SSH主机/开发者密钥、机器ID、WebUsuárioDados、AI Key或发行私钥。摄像头仍为Teste源。

发行私钥只在构建机私有Diretório，Git/Imagem/交付包仅含公钥。产物复制到WindowsDiretório并重新核对大小/hash。后续已按Usuário指示推送源码并发布Imagem/Software附件；公开状态 e 匿名Baixar核验见[发布记录](2026-10-27-web-updates-publication.md)。

## 尚待实物Validação

鸭子关闭，未执行旧卡首次引导/实际Web升级/回退、物理掉电恢复、真人声学或新卡Completo首次Superior手。原坐站口令曾由Usuário确认Sucesso；本次Imagem组合仍须Superior机Validação。QEMU kill/Inicialização恢复不代替真实供电 em 断验收。

音乐跟拍头身实动问题仍待修复，自由AI人声对话未接入，本版不把它们记为Concluído。使用步骤见[SoftwareAtualização e 语音](../../SoftwareAtualização e 语音Instruções de uso-20261027.md)。
