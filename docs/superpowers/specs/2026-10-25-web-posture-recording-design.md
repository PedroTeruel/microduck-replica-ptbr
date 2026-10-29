# Web录制增加Sentar e 站起

Usuário已经明确回复：“对，把Sentare站起也录进去”。这是对原首版排除坐站 de 范围修正；沿用此前允许本地开发、Teste、SSH Atualização现有Controle网址 de 授权，不重复询问执行Licença。

Concluído记录：aa825fc 已实现并AtualizaçãoAtual鸭子原Web，Usuário确认“能保存，回放坐站也正常”。389 项SoftwareVerificação e 部署/回退边界见[验收](../verification/2026-10-25-web-posture-recording.md)。

## 选择 e 边界

采用明确 de “Sentar／站起”目标步骤，并Leitura主程序实时状态决定是否é necessário切换e何时继续。直接记录 sit_toggle 按键可能因起始姿态不同反向执行；只按延时播放无法识别 rise 仍在执行，均不采用。此次不加入踢腿、翻滚、捡取、卸力/Superior力或Modelo切换。

入口仍是现有动作录制区。Usuário先站稳并开始走，再录制“Sentar→等待→站起→等待”，结束、命名保存、选择回放。经过同样Caminho de Web十字Inferior e 遥控坐站按钮均可录制；记录经过实际Verificação并获 robotd 接受 de 目标。录制不因受控坐站而结束，空动作提示不能把有效坐站误报为空。可Preservado以坐着结束 de 单次记录；多次循环要求末态回到站姿，否则Instruções需录回站姿再循环。不自动补站起动作。

保存采用有Versão de 语义步骤白名单，不将任意 robot.do/init/enable GravaçãoArquivo；旧 de  v1 指令记录继续可读。新含坐站Conteúdo采用 v2，旧Versão回退对 v2 不兼容 de 边界需在记录 em Instruções。兼容性指纹继续包含实际 sitstand Modelo e Configuração。

## 状态证据 e 执行

robot.policies.enabled 是InicializaçãoConfiguração常量；bus.policy_enabled 才是Execução开关。坐站 de  sitting 标志在开始Sentar时立即变 true、开始起身时立即变 false；homed 也不是起身Concluído信号。主程序现有 robot.state.policy 会报告 sit、rise、walk/stand。por meio de Studio 原有订阅提供该策略阶段、样本时间 e 实际/目标关节信息，不重启或修改 robotd。

坐站执行要求Fonte状态新鲜、策略已启用、扭矩确认、Modelo存在、无实体手柄冲突 e 原有保护por meio de。回放Leitura目标姿态：已达到目标时不再切换；不明确时终止，不重试 toggle。起身必须等待新鲜非 rise  de  walk/stand 阶段；Sentaré necessário新鲜 sit/sitting  e 关节实际/目标收敛 de 连续样本，不能仅凭切换回执或坐姿标志宣布Concluído。缺失阶段/位置证据、超时或未知执行Resultado均停止后续动作，Preservado明确原因。Por favor求回复 e 样本按会话/代次e时间隔离，不能用旧样本或迟到回复恢复会话。

坐站步骤不能被迟到连续目标合并丢弃；到该步骤时暂停回放时间轴，确认Concluído后再继续。等待不产生后续摇杆/头嘴目标，不在Inferior一轮补发旧帧。ModeloConteúdo、状态异常、实体手柄、急停、切页、后台、失焦、断网 e 心跳超时继续 em 止后续输出，重连不续播。

普通暂停/停止不能物理取消已交给 robotd  de 坐站。暂停停止连续Controle并冻结时间轴，坐站仍由主程序Concluído；恢复须重新Validação。停止或离开Página取消后续步骤，明确提示“Atual坐站仍会Concluído”，不假称立即物理停止、不自动站回 HOME、也不自动卸力。仍在Concluído de 坐站阻止新 de 自动会话；急停继续走现有卸力通道。

## 验收

新Teste先Falha再实现：只坐站也生成非空记录，Web按钮e十字Inferior均被纳入，拒绝不保存，旧 v1 Arquivo可读，语义字段严格Validação；实际发送 de 回放顺序是 sit→stand 且不反向切换。单独 sitting/homed 变化不能提早续播，连续收敛 e  rise→walk/stand 新样本才能推进；旧样本、超时、RPC 丢回执、取消、暂停/恢复、断线/重连、身份变化、有限循环 e 尾态不匹配均覆盖。原 205 项动作/手柄Teste继续por meio de。真实 Studio+fake robotd+Edge 走通坐站录制、保存、单次e三次回放 e  320/390/1440 布局。真机部署只更换匹配 Studio Arquivo并重启 Studio，Preservado state e其他Serviço；自动Teste不主动移动真鸭子，真实效果交由Usuário确认。
