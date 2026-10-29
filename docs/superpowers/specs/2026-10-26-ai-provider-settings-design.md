# WebAI对话接入Configuração

Usuário要求参考小智语音项目，在现有鸭子Web保存Serviço商、接口URL、API Key e Modelo，以后usado para语音对话。已确认“还没开通，先做好Configuração入口”。本版Concluído可持久保存、选择eTeste de 接入基础，加Web文字试聊Validação接口；不宣称已接通麦克风、喇叭或云端账号。

## 依据 e 方案

- [小智服务端配置](https://github.com/xinnan-tech/xiaozhi-esp32-server/blob/main/main/xiaozhi-server/config.yaml)将ASR、LLM、TTS作为可选模块，LLM可配置model_name、base_url、api_key。
- [豆包方舟官方示例](https://docs.volcengine.com/docs/ark/context-management?lang=en)使用`https://ark.cn-beijing.volces.com/api/v3`，API Key与已开通Model ID调用Chat Completions。
- [豆包实时语音3.0官方文档](https://docs.volcengine.com/docs/DoubaoVoice/endtoend-realtime-voice-full-duplex-version?lang=en)使用专用Realtime事件协议与`wss://openspeech.bytedance.com/api/v3/duplex/realtime/dialogue`。普通方舟Chat API与实时语音不混用；本版先做通用对话接入，实时语音在后续适配。

采用轻量 de 已有Studio后端代理，无需在RK3566Instalação整套小智Serviço端。直接在WebPor favor求Modelo会暴露Key且受跨域约束；Completo部署小智引入另一套设备Protocolo e Serviço，超出此次Configuração入口é necessário。

## Usuário流程

设置页增加位置靠前、清晰可见 de “AI 对话”卡片，现有语音面板提供到设置 de 入口。可新增、编辑、删除最多10套Conexão，选择AtualConexão。Configuração包含名称、Serviço商（豆包方舟文字Modelo/其他兼容对话接口）、基础URL、Model ID、可选API Key。豆包预填基础URL，Model ID由UsuárioControle台填写，不猜测最新ModeloID。

保存草稿允许暂缺Key/Modelo，显示具体缺少项；“TesteConexão”e“试聊”只使用已经保存且Completo de Configuração。Key必需 de 接口未填Key不能启用；本地免KeyServiço可明确选择免Key。保存e选用不会自动调用云端。切换/删除/编辑Conexão后清掉旧TesteResultado或试聊SuperiorInferior文，不能把旧Configuração de Sucesso显示成新ConfiguraçãoSucesso。

连接测试使用一次很短的真实模型请求验证鉴权/模型，而非仅凭HTTP200或`/models`目录。文字试聊有简短多轮上下文与清空按钮，不记入磁盘或日志。界面明确“文字试聊尚未连接鸭子麦克风/扬声器，不执行机器人动作”，实时语音专用接口本版尚未适配。

## 后端 e 凭据

- 独立模块管理私有`state_dir/ai-connections.json`，POSIX0600、原子写入、进程内锁；首次不创建默认个人配置。重启后保存的连接和当前选择仍在。读到损坏或非法文件应报错并保留原文件，不静默覆盖。
- HTTP API复用现有登录、Origin e CSRFVerificação，响应no-store；APIé necessário已设Web密码，现有明确本机dev-autologinTeste模式除外。未登录e跨站调用不能保存或用KeyPor favor求Modelo。
- Key只由表单POST写入鸭子，任何GET、快照、成功/失败响应和诊断包均不返回完整Key。页面保存后清空Key输入，以`key_configured`表示已保存；空输入保留同一连接原Key，可明确清除。改变目标服务地址/服务商不得悄悄带用旧Key，需重新填写或选择免Key。
- 私有Arquivo不进入Git、基础Imagem或前端localStorage；不宣称加密存储。普通升级PreservadoUsuárioConfiguração；新增日志不写Por favor求体、Authorization、Key或对话原文，诊断包不纳入该Arquivo。
- ModeloPor favor求只在后台线程Execução，Configuração锁不跨RedePor favor求；小并发Superior限、超时 e 响应体/输入长度Superior限，单次调用不自动重试。URL限定HTTP(S)、禁止userinfo/query/fragment e Controle字符，禁止重定向转发Key。HTTP仅usado para明确本地Serviço；公网Serviço用HTTPS。错误按类别显示且脱敏，不将Serviço端任意HTML/错误Conteúdo当执行指令。
- AI模块没有机器人端口依赖；不执行Modelo返回 de 任何动作、RPC、代码或Ferramentas调用。所有现有本地语音/音乐/运动行为保持。

## 验收

存取/重启/Preservado e 清除Key/目标变化/损坏Arquivo保护，真实HTTP登录 e CSRF，模拟兼容接口 de 鉴权、Teste、试聊、超时、错误、大小Superior限 e 不跟随重定向，Teste日志/响应 em 无Key，Validação均先写FalhaTeste。真实本地EdgeConcluído窄屏新增保存、重载、切换、Teste、试聊、清空、删除，实际模拟Serviço确实收到Por favor求。没有Usuário真实Key时不声称豆包云端或Hardware语音已验收。部署延续既有停稳策略关闭、冻结Arquivo/备份/Usuário状态hash/运动核心身份Verificação流程。
