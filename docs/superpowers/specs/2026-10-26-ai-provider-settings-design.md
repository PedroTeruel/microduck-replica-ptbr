# 网页AI对话接入配置

用户要求参考小智语音项目，在现有鸭子网页保存服务商、接口URL、API Key及模型，以后用于语音对话。已确认“还没开通，先做好配置入口”。本版完成可持久保存、选择和测试的接入基础，加网页文字试聊验证接口；不宣称已接通麦克风、喇叭或云端账号。

## 依据与方案

- [小智服务端配置](https://github.com/xinnan-tech/xiaozhi-esp32-server/blob/main/main/xiaozhi-server/config.yaml)将ASR、LLM、TTS作为可选模块，LLM可配置model_name、base_url、api_key。
- [豆包方舟官方示例](https://docs.volcengine.com/docs/ark/context-management?lang=en)使用`https://ark.cn-beijing.volces.com/api/v3`，API Key与已开通Model ID调用Chat Completions。
- [豆包实时语音3.0官方文档](https://docs.volcengine.com/docs/DoubaoVoice/endtoend-realtime-voice-full-duplex-version?lang=en)使用专用Realtime事件协议与`wss://openspeech.bytedance.com/api/v3/duplex/realtime/dialogue`。普通方舟Chat API与实时语音不混用；本版先做通用对话接入，实时语音在后续适配。

采用轻量的已有Studio后端代理，无需在RK3566安装整套小智服务端。直接在网页请求模型会暴露Key且受跨域约束；完整部署小智引入另一套设备协议与服务，超出此次配置入口需要。

## 用户流程

设置页增加位置靠前、清晰可见的“AI 对话”卡片，现有语音面板提供到设置的入口。可新增、编辑、删除最多10套连接，选择当前连接。配置包含名称、服务商（豆包方舟文字模型/其他兼容对话接口）、基础URL、Model ID、可选API Key。豆包预填基础URL，Model ID由用户控制台填写，不猜测最新模型ID。

保存草稿允许暂缺Key/模型，显示具体缺少项；“测试连接”和“试聊”只使用已经保存且完整的配置。Key必需的接口未填Key不能启用；本地免Key服务可明确选择免Key。保存和选用不会自动调用云端。切换/删除/编辑连接后清掉旧测试结果或试聊上下文，不能把旧配置的成功显示成新配置成功。

连接测试使用一次很短的真实模型请求验证鉴权/模型，而非仅凭HTTP200或`/models`目录。文字试聊有简短多轮上下文与清空按钮，不记入磁盘或日志。界面明确“文字试聊尚未连接鸭子麦克风/扬声器，不执行机器人动作”，实时语音专用接口本版尚未适配。

## 后端与凭据

- 独立模块管理私有`state_dir/ai-connections.json`，POSIX0600、原子写入、进程内锁；首次不创建默认个人配置。重启后保存的连接和当前选择仍在。读到损坏或非法文件应报错并保留原文件，不静默覆盖。
- HTTP API复用现有登录、Origin与CSRF检查，响应no-store；API需要已设网页密码，现有明确本机dev-autologin测试模式除外。未登录和跨站调用不能保存或用Key请求模型。
- Key只由表单POST写入鸭子，任何GET、快照、成功/失败响应和诊断包均不返回完整Key。页面保存后清空Key输入，以`key_configured`表示已保存；空输入保留同一连接原Key，可明确清除。改变目标服务地址/服务商不得悄悄带用旧Key，需重新填写或选择免Key。
- 私有文件不进入Git、基础镜像或前端localStorage；不宣称加密存储。普通升级保留用户配置；新增日志不写请求体、Authorization、Key或对话原文，诊断包不纳入该文件。
- 模型请求只在后台线程运行，配置锁不跨网络请求；小并发上限、超时与响应体/输入长度上限，单次调用不自动重试。URL限定HTTP(S)、禁止userinfo/query/fragment及控制字符，禁止重定向转发Key。HTTP仅用于明确本地服务；公网服务用HTTPS。错误按类别显示且脱敏，不将服务端任意HTML/错误内容当执行指令。
- AI模块没有机器人端口依赖；不执行模型返回的任何动作、RPC、代码或工具调用。所有现有本地语音/音乐/运动行为保持。

## 验收

存取/重启/保留及清除Key/目标变化/损坏文件保护，真实HTTP登录与CSRF，模拟兼容接口的鉴权、测试、试聊、超时、错误、大小上限及不跟随重定向，测试日志/响应中无Key，验证均先写失败测试。真实本地Edge完成窄屏新增保存、重载、切换、测试、试聊、清空、删除，实际模拟服务确实收到请求。没有用户真实Key时不声称豆包云端或硬件语音已验收。部署延续既有停稳策略关闭、冻结文件/备份/用户状态hash/运动核心身份检查流程。
