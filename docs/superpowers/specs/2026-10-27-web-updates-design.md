# 网页软件更新、语音坐站与镜像共用组件包

用户已批准[在线升级流程方案](../../在线升级流程方案-20261027.md)，要求实现并把本地语音坐下/站起纳入，新镜像随后使用相同安装包。自由AI语音仍暂停，不合入其草稿。范围是现有HD1910/Radxa Zero3W复刻栈的网页、匹配helper及duck-echo程序；robotd/padd/模型/OS保持现有已验证版本。

## 已验证的引擎选择

复用底图真实ARM64 updaterd0.15.1/rev1fa84386/API37，复制到独立root拥有的稳定路径，不在普通软件包内更新它。2026-10-27已在WSL用现有qemu-aarch64及只读提取的五个共享库运行版本查询、自定义profile --self-test与实际IPC，确认local_dir、组件software、Restart、command健康检查、exact/from_dir/dry_run可用。没有另写签名/事务/回退引擎。

组件`software`作为单一事务：`/opt/microduck/software/releases/<semver>/{studio,duck-echo}`及current原子链接；helper随Studio版本并使用稳定root包装入口。稳定systemd单元、升级器、健康检查、发行公钥与用户数据在此目录之外。配置auto_apply=off，不设置周期检查。仅重启microduck-studio与duck-echo。robotd/padd不被更新或重启。

ASR依赖/模型位于`/opt/microduck/resources/{asr-deps,models}`，通过明确参数交给语音服务；默认actions+toggle+duck，启动不自动监听。Mic3R初始化作为稳定启动准备，保留原声卡初始化且不触碰喇叭音量。R3开关提示音及已验收坐站语义保持。

## 包、签名、检查与下载

整套版本首选`2026.10.27`（后续同日修订使用SemVer允许格式），独立源码SHA/文件hash登记。使用维护者自己的minisign发行公钥；私钥只在本机私有签名目录，不能进Git/安装包/镜像。首个包由冻结Git运行白名单构建，不包含开发状态、Key或日志。

在线源固定为用户仓库fanhao375/microduck-replica的`microduck-software-v*`正式发布，不能把镜像release误当组件release；无匹配发布显示“尚无发布的软件更新”，网络失败不显示已是最新。内置源/信任配置root管理，网页不提供任意root命令、安装路径、发布源覆盖。

分发外包只含一个版本的四个普通文件：`<version>.manifest.json`及签名、组件压缩包及签名。manifest.channel=software，url为本地裸文件名，hash/大小/版本/源码/兼容性信息固定；同一外包既能HTTPS下载也能网页上传。外包严格限制数目/总大小/文件名，拒绝绝对路径、..、链接、重复成员和特殊文件，未验证代码不执行。

现有引擎无download动词，check结果也不返回artifactURL。以小型受限控制服务做发布元信息查找、限量下载/外包缓存及任务记录，缓存root私有；交给真实引擎exact/from_dir/dry_run完成签名、hash、兼容、archive与required-files验证，才显示可安装。实际安装再调用相同exact/from_dir，复用同一个缓存且重新验证。元信息展示都是不可信纯文本。若dry_run的运动预检尚不满足，显示已下载但待停稳验证，不能假绿。

控制服务独立于Studio，安装/回退任务不依赖网页请求存活；任务ID、阶段/错误/结果落在更新状态目录，页面刷新或Studio重启后可读回。下载、验证、准备、应用、健康检查、完成、回退/失败分开显示；有限并发及单次安装锁。source/catalogURL和上传/下载限额固定，HTTP只允许明确loopback测试；公网TLS校验、限次受控重定向，不把凭据带到陌生目标。

## 安装前置与恢复

控制层在dry_run/apply/rollback前读真实robot.busStatus，要求motion/control/homed、policy_enabled=false、关节反馈新鲜/无实际运动，并检查Studio舵机/标定/录制回放会话、语音监听/音乐已关闭。缺少回读拒绝；不能因上游引擎允许robotd缺席就跳过复刻栈安装保护。检查稳定供电/低电与磁盘余量，错误说明具体原因。安装期间拒绝新的运动/配置操作，重连后解除更新占用，不能靠按钮禁用当服务端锁。

稳定health命令验证当前清单、实际运行程序来源、Studio healthz+静态资源、duck-echo控制socket、需要的ASR资源和robotd/padd未被重启；服务missing/active但未就绪都不能成功。检查失败由原引擎恢复previous版本链接并启动旧服务。没有破坏性外部迁移hook；首次新镜像种下合法基线，之后的每次升级保留上一版。用户标定/WiFi/配对/录制/APIKey均在版本目录外，禁止用发布者state覆盖。断电/执行器崩溃恢复按原引擎持久事务验收，不夸大未做过的物理断电测试。

一次性bootstrap保留旧安装/单元及数据，安装稳定组件配置和入口，使用同一签名包/原引擎initial install；校验失败恢复旧服务配置。新镜像通过相同installer的offline rootfs入口安装相同签名包，允许显式构建用QEMU命令，不在x86宿主执行ARM代码。普通升级不改OS/内核、运行时或个人网络。

## 网页与权限

设置页顶部“软件更新”：当前套件/组件版本、更新说明、检查更新、下载/上传包、待安装版本、立即更新、退回上一版及真实进度/结果。使用现有视觉与320px布局。所有HTTP复用网页登录、Host/Origin/CSRF，要求设密码（明确localhost开发模式除外），no-store，输入白名单与大小限制。backend文件和网络工作不阻塞主事件循环。

安装开始显示网页可能短断，自动重连并按任务记录判成功；本地缓存包可离线安装/回退。没有真实发布源时不能演示假最新版本；真实本地HTTPS/loopback provider测试下载链路，实际引擎在WSL临时root测试签名/安装/回退。

## 验收与交付

失败测试先行；实际旧ARM引擎+本地签名包通过首次安装、新版切换、坏签名/错hash/越界包/服务失败自动恢复及任务崩溃恢复。真实本地Edge验证登录/CSRF、无发布、检查/下载/上传/安装/重连/回退/错误/窄屏；不能仅mock一个成功返回。语音相关原测试与运行文件/资源匹配，不重写已验收识别逻辑。上机冻结清单、备份、真实停稳检查及用户数据hash/robotd/padd身份验证。新镜像构建、解压只读检查、固件模型hash/干净身份/无私钥和APIKey核对；新卡真人首装和本次镜像声学仍需实际验收，旧版成功不能替代。
