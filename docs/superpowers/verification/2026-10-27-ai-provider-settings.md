# AI接入Configuração入口：Validação e 交付状态

日期：2026-10-27（东京时间，工作从10-26跨日）。Usuário确认“还没开通，先做好Configuração入口”。

**状态：已通过SSH安装到duck-0de6，部署后HTTP、运行文件与用户数据检查通过。** 代码、模拟接口、浏览器流程和设备隔离单测通过。用户确认“停好了”后，回读仍显示策略开启、站着且全部关节速度为0；补做与网页一致的`robot.stop → robot.enable {on:false,toggle:false}`，收到accepted并确认policy_enabled=false，再更新网页服务。没有自动重新使能或替换模型。

## 冻结代码 e 能力

- 实现`907a4a2f2abc0e013044954b829a7e2eb257e9a4`；长回复上下文修正`7536e0e48d1a0e92ced15f97417b0247a02a827d`；请求取消/慢响应截止时间修正`991bb50278c185f13248c03519b8e21c4eb0b800`。最终运行文件冻结在991bb50。
- 设置页顶部“AI 对话”，语音面板有入口。最多10个Conexão，豆包方舟文字Modelo e 自定义兼容接口，名称/Base URL/Model ID/Key或明确本地免Key，保存草稿、Atual选择、编辑删除、真实短ConexãoTeste、文字多轮试聊e清空。
- 保存e选择不访问提供商。未ConfiguraçãoCompleto不能选用/Teste/聊天。只用Usuário保存 de 地址、Modeloe认证；普通Chat Completions e 豆包专用实时语音Protocolo分开Instruções，没有假装已ConexãoHardware语音。
- 私有单Arquivo原子Gravação、POSIX0600；Key不作为秘密字段返回，不进浏览器持久存储、日志或诊断包，输入保存后清空。地址/提供商改变不带用旧Key。已设Web登录密码、会话、OrigineCSRF保护；所有AI响应no-store。
- AI模块无机器人端口依赖，不执行回复 em  de 动作、RPC或代码；不改现有音频Serviço、R3、音乐、运动Modelo或Rede。

## 已ExecuçãoVerificação

| 范围 | Resultado |
| --- | --- |
| 新功能存储/客户端/真实HTTP | 初轮23项por meio de；包含原子存取、损坏Preservado、Key/URL变化、草稿、登录/CSRF、诊断脱敏、本地模拟Por favor求、限流/超时等。 |
| 相关广覆盖回归 | 161项por meio de，120.400秒，发生在最后长回复 e 截止时间修正前；Windows既有默认音频AF_UNIX线程e资源AvisoPreservado，未声称为干净Linux验收。 |
| Node | 29项相关Verificaçãopor meio de；长回复 e 组件生命周期定向5项por meio de。 |
| 独立规格审查 | 24项Python、5项Nodepor meio de，无遗漏或超范围实现。 |
| 独立质量复查 | 16项客户端/HTTPpor meio de，2.899秒；唯一重要Rede问题修复后批准991bb50。 |
| 最终真实本地Edge | 5.595秒por meio de，无Controle台错误；320/390/1440布局、草稿e两套Conexão、保存/选择不发外部Por favor求、重载PreservadoAtualConexão、Key不回显、短Teste、多轮/长回复后继续、401/回显Key脱敏、清空 e 删除均por meio de，假机器人无AI动作输出。 |
| 鸭子Superior de 隔离单测 | 使用冻结staging模块 e 临时TesteDiretório，21项por meio de，1.283秒；含Linux0600 e 慢响应/取消恢复。没替换ExecuçãoWeb，没写实际UsuárioConfiguração，没访问公开AIServiço。 |

浏览器使用本地模拟提供商真实接收HTTPPor favor求，能区分保存/选择 e 实际Teste/聊天。模拟Key只存在Teste临时状态，不是Usuário凭据，不纳入Imagem或部署ExecuçãoArquivo。

## 审查发现 e 修正

1. 早期JSON序列化后全局替换短Key会改坏字段名/标识。改为结构化处理展示字符串，保护schema/身份字段，并单独脱敏模型输出；有`key='model'`回归。
2. Modelo输出Superior限4000字而Histórico消息旧Validação仅2000字，长回复会使Inferior一轮Falha。改为Usuário2000、助手4000、总体12000，按Completo旧轮次裁剪，不截断Superior一轮Conteúdo；真实浏览器Validação2501字回复后仍能继续。
3. 旧客户端只在`getresponse()`返回后查总时间，慢慢发送状态行/响应头可长时间占住两个工作槽；async等待超时不能终止线程。独立复现0.05秒超时实际0.812秒，两次取消后后续busy。改为每请求取消控制、保留真实连接socket、watchdog中断已连接I/O及finally回收；复查0.05秒限制在0.062秒退出，取消两次后第三次0.015秒恢复。

限制：Python标准库 de 系统DNS解析不能直接 em 断；若解析/Conexão在过期后才返回，会关闭且不发送凭据/Por favor求。不声称所有操作系统DNS都满足绝对截止时间。ConfiguraçãoPor favor求不阻塞Web事件循环，异常Por favor求并发受限。

## 已Instalação de 包

- 源991bb50，8个运行文件，staging：`/home/radxa/.web-ai-settings-20261026-86ab26ebd5`。
- 仅替换8个StudioExecuçãoArquivo并重启microduck-studio，PID11672→27725；robotd1097、padd1135、duck-echo6325 de PID e Inicialização时间Inalterado，全部Serviçoactive、语音Serviçoenabled。
- 安装脚本再次确认实际policy_enabled=false后才停止网页服务、备份和原子更新。备份目录`/home/radxa/.microduck-backups/web-ai-settings-20261026-86ab26ebd5`，权限0700，包含原运行文件、清单与用户数据；脚本有失败回退。
- 部署后独立Verificaçãoexit_code=0：主页、healthz e 全部相关资源HTTP200、Web资源 e 磁盘hash一致、8个清单hash一致；未登录AIConfiguraçãoPor favor求401；原12个UsuárioDadosArquivohashInalterado。登录后 de Configuração流程由真实本地Edge+模拟提供商验过，未绕过现场登录，也没向设备写TesteKey或TesteConexão。
- 证据：`deployment/apply_frozen_remote.result.json`、`deployment/device-verification.json`、`deployment/stop_before_update_remote.result.json`。本轮没有重烧镜像、启用OTA或改Wi-Fi。
- 没有Usuário真实API Key，未Validação豆包或其它真实云端账号；麦克风/扬声器、端到端语音eAI动作调用尚未接入。

说明：[配置使用指南](../../AI对话接入配置-20261027.md)。证据在根工作区`artifacts/ai-provider-settings-20261026/`；软件总账归F26，音乐跟拍的实物问题仍按原记录未通过验收。
