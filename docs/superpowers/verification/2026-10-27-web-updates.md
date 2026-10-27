# 网页软件更新、本地语音与新镜像：交付记录

日期：2026-10-27（东京时间）。用户要求实现网页在线升级，将本地语音“坐下／站起来”纳入新镜像；随后确认“暂时关着，先完成本地软件和镜像”。自由AI语音对话保持暂停。

**已完成软件、签名包、首次引导输入包和匹配镜像。用户后续授权推送与公开发布，master源码、20261027 Latest镜像及2026.10.27软件发行均已完成，见[公开发布记录](2026-10-27-web-updates-publication.md)。没有部署到关闭的鸭子或烧卡，旧卡首次引导与新镜像实物验收仍待开机后进行。**

## 版本与产物

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

## 实现与边界

- 设置顶部新增软件更新：版本、检查、下载、离线上传、验证、安装、任务状态、重连读回与回退。沿用登录、Host/Origin/CSRF和no-store；白名单不接受任意来源、路径或shell。
- 一套签名software组件管理Studio、匹配helper与duck-echo。执行器/健康检查/公钥、用户数据和ASR资源位于版本树外。冻结Git运行文件白名单，不含测试、日志、用户状态或私钥。外层USTAR四文件严格校验，内层tar.zst由原引擎验证。
- 使用原镜像实际ARM64 updaterd0.15.1，源码`1fa84386f07884e27866411bc1ba166977bced95`、IPCAPI37，自定义profile/from_dir/dry_run；没有另写事务切换引擎。`auto_apply=off`，无周期检查/自动安装。
- 独立root控制器通过有peer权限检查的IPC提供固定动词；发布源固定为`fanhao375/microduck-replica`的`microduck-software-v`正式发布。无发布、网络错误、下载成功和安装成功分别显示。首个2026.10.27软件Release已公开；同版镜像检查时没有更高版本是正常状态。
- 原引擎还会尝试延迟重启updaterd/btd，稳定服务边界拒绝它们，仅允许网页与语音服务。离线构建禁止修改任何宿主服务；健康检查使用真实绝对systemctl路径。
- 切换前检查新鲜总线回读、实际站姿/策略关闭、15关节/速度/时间、供电、空间及录放/标定/舵机/音频占用。marker与跨进程锁同时保护网页和实体R3，取消迟到ASR，避免预检与坐站命令竞态；急停、卸力和关闭监听保留。
- 首次引导核对旧服务drop-in，覆盖已知10-image.conf，拒绝未知自定义启动配置。旧状态经固定UID、无跟随目录描述符、类型/链接数/大小检查后复制到私有暂存，再原子迁移到空目标；不递归chown用户可控制树。已有非空新状态保留；异常恢复原服务与程序入口。
- Studio普通用户运行，显式外部StateDirectory/LogsDirectory，程序树root拥有不可写。语音默认actions/toggle/duck、启动不监听，明确共享ASR路径、Mic3R启动准备及audio/input权限。

## 实际验证

| 检查 | 结果与范围 |
| --- | --- |
| Studio完整非浏览器回归 | `STUDIO_E2E=0 py -3.13 -I run_tests.py`：1201项，268.296秒，OK，75跳过。Windows AF_UNIX语音状态线程有已知环境提示，不宣称Windows原生音频链路通过。 |
| 本地语音 | 155项，OK，18跳过；另在WSL实际flock、迟到ASR取消等12项针对性检查通过。 |
| 更新器Linux | 独立质量审查18项通过，含真实UID65534鉴权/日志写入、符号链接与迁移竞态拒绝。 |
| 镜像侧 | 128项通过，49.590秒，含错误hash/未知路径、完整组件输入、共享签名bootstrap及失败不记成功。 |
| 原ARM更新器/QEMU | 10项检查全真：签名首次安装、dry-run、错hash/manifest签名拒绝、27→28切换、手动回退、健康失败自动回退、持久切换后kill引擎再启动恢复、服务范围。没有向实际robotd发运动命令。 |
| 最终真实Edge | e382f07实际Studio/控制器，1项17.394秒通过；1440/390/320布局、无发布、下载待停稳、验证、安装、刷新任务、回退、上传、坏包与额外root字段拒绝，控制台错误为空。引擎/设备预检为明确测试替身；原引擎事务另有实测，不把替身称为真机升级。 |
| 独立规格复查 | 503b7cf通过：9控制器+4语音检查，R3互斥P2已关闭。 |
| 独立质量复查 | e382f074通过：外部状态/日志、旧状态无跟随迁移问题已关闭，无剩余P1/P2。 |
| 镜像实际ARM Python | 只读镜像中的Python3.13.5/Vosk成功加载中文模型，静音识别为空；ARM Python经QEMU以UID65534启动不可写源码的Studio，healthz成功、外部状态/日志可写。机器人端点全部关闭。 |

一次包含旧浏览器用例的完整运行曾得到1200项、3失败、5跳过。已与18cd3基线对照，定位为电池值在Edge启动前已被滤波器锁定、舵机关闭状态早于异步记账完成的测试竞态；1b7416e只修测试同步，不改产品或减弱原断言。原三项失败重跑35.020秒通过，随后上述1201项非浏览器完整回归通过；没有再次跑完全部旧浏览器套件。

报告位于`artifacts/software-updates-20261027`：studio-unit-regression.log、image-tests.log、engine-acceptance.log、browser-final/browser.json及截图、image-verification.json、native-voice-check.json、unprivileged-startup.json、build-image.log、verify-image.log和delivery.json。

## 镜像构建与只读验收

沿用已核验底图与运行时payload，不换步态模型：

- 底图SHA256：`652dd54e70f49fd3633058d5ed9bbb2f63b435648da2346dfbfa60fcaa4c5bcc`。
- payload SHA256：`370f64af5c690eeebab429f4c59d9c5d00883b5cf1e7f0d0e2c18d4afe45998d`。
- robotd SHA256：`edf182edb7bf11aeeeedfdab98170ab2ec48a9ec18417f9b68c744b0a60c6d16`；来源`0791fcd44f71c705dc8bb0fbcde405593b52d19b`。
- 原updaterd SHA256：`d5f9086bae5c2ec10ba75fc2d41c27578236a12d9a6364bffa8d9315fda97fa6`。
- Vosk small-cn0.22 ZIP SHA256：`3af8b0e7e0f835ae9d414ce5df580237a3cfb08d586c9fbbb0f7ff29ad5b14ba`；11套ARM64/cp313 wheel、304个资源文件、80,414,834字节。模型Apache-2.0，依赖许可证保留。

冻结Git归档构建签名包，现有WSL镜像脚本调用同一共享bootstrap。独立解压交付xz，SHA/xz/分区/e2fsck只读检查通过，再ro,noload挂载验收并卸载：

- 原运行时/模型39项hash、9个模型引用一致；15颗舵机保持未标定、IMU commissioning默认正确。
- software350个运行文件逐项hash一致，current相对链接、root拥有不可写；来源e382f07和包hash一致。
- 独立升级器/公钥/配置、自动应用关闭、稳定服务、State/Logs权限及90覆盖正确，sudoers语法通过。
- 304个语音资源文件hash一致，Mic3R准备、明确ASR路径、actions/toggle/duck默认一致，实际ARM模型加载通过。
- 无个人Wi-Fi、SSH主机/开发者密钥、机器ID、网页用户数据、AI Key或发行私钥。摄像头仍为测试源。

发行私钥只在构建机私有目录，Git/镜像/交付包仅含公钥。产物复制到Windows目录并重新核对大小/hash。后续已按用户指示推送源码并发布镜像/软件附件；公开状态与匿名下载核验见[发布记录](2026-10-27-web-updates-publication.md)。

## 尚待实物验证

鸭子关闭，未执行旧卡首次引导/实际网页升级/回退、物理掉电恢复、真人声学或新卡完整首次上手。原坐站口令曾由用户确认成功；本次镜像组合仍须上机验证。QEMU kill/启动恢复不代替真实供电中断验收。

音乐跟拍头身实动问题仍待修复，自由AI人声对话未接入，本版不把它们记为完成。使用步骤见[软件更新与语音](../../软件更新与语音使用说明-20261027.md)。
