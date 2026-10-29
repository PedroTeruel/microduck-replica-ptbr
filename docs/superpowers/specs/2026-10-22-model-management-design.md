# Studio Modelo管理

Usuário已确认 UI-08，并在 2026-10-22 明确要求开始实现。目标是把电脑Superior已经训练、导出 de Modelo装进鸭子，选择使用、命名、改手柄键、删除e恢复默认，不要求Usuário重新Gravação系统Imagem。

## 使用流程

总览「管理」直接进入 `#/models`。顶部为导入按钮和简明说明；列表区分内置默认与自行导入，显示名称、用途、是否当前选用、是否正在执行、按键。安装不自动启用或上力。路径、哈希及训练细节折叠显示。重量和导出鸭子档案保留在原设置页，不混入模型管理。

导入suporta现有部署导出Diretório打成 de  ZIP 或 tar.gz：一个 policy.onnx、manifest.json、deployment-contract.json，e该Modelo de 可选执行Configuração。Instalação前Verificação档案边界、Arquivo身份、用途e主程序 de 真实 ONNX 预检；Falha不出现在可用Modelo列表 em 。名称可编辑；禁止覆盖系统Arquivo或现有Modelo。

选用复用 robot.loadPolicy；Sucesso以 robot.policies 回读为准，不能把 accepted 当Sucesso。Falha尝试恢复旧Caminho并如实报告回退Resultado。基础内置Caminho保存为默认恢复Fonte，避免 custom_only  de 通用 reset 误指向Oficial其他Modelo。

手柄按键使用Atual主程序实际suporta de  A、X、LB、RB、十字Inferior；复用 pad.bind，解绑为空字符串，恢复默认采用省略 skill  de 原生语义。冲突明确显示原动作，Usuário选择替换后才Gravação。动作 e Modelo用途分开，Caminhada不是普通按一Inferior执行 de 技能。

自行导入Modelo允许删除；Atual仍被槽或按键用途引用时先明确要求切换 / 恢复默认，不留Inferior悬空引用。内置Arquivo不提供删除入口。正在运动 / 未确认卸力时拒绝切换等ExecuçãoConfiguração更改，Preservado现有急停e基础按键。

## 架构

- 所有导入Arquivo在 Studio Usuário可写 de  state/models Inferior，默认 /var/lib/microduck-studio/models。无需增加 root helper 权限。
- model_package.py：档案安全提取、静态合同Verificação、调用 robotd validate-policy；不ConexãoHardware。
- models.py：库元Dados、默认Fonte、Instalação、改名、删除、Execução端 RPC e回读确认。
- app.py：同源 / 会话 / CSRF 校验后 de  HTTP 接口，流式限制Enviar大小，序列化变更。
- models.js：独立管理页。现有 tune.js 总览卡改为链接该页。

## HTTP 契约

GET /api/models 返回 {ok:true,data:View}；POST /api/models/import 接收original ZIP/tar.gz 字节，URL Parâmetros filename、name（可选），要求 X-CSRF。POST /api/models/op 接收不超过 32KiB  de  JSON，并要求 X-CSRF。

操作：rename{id,name}、select{id,slot}、restore{slot}、delete{id}、bind{button,slot,replace?}、unbind{button}、reset_bindings{}。

Sucesso返回 {ok:true,data:View}。Falha返回 {ok:false,error: em 文原因,code:可选标识}，HTTP 400/409/413/503 按实际错误选择。ModelError 为 service 层可预期异常。

View 包含：

```
{
 items:[{id,name,source:'builtin'|'imported',task,suggested_slot,slots:[],running:false,
         buttons:[],can_delete:false,reason:null,sha12,installed:true}],
 slots:[{slot,label,model_id,path,error,default_id}],
 bindings:[{button,label,slot,skill,model_id,default_skill}],
 capabilities:{import:false,select:false,reason:null},
 buttons:[{button,label}],
 error:null
}
```

Models(rd,log,state_dir,tune=None,root='/',validator=None,rpc=None) 提供 async view()、import_package(path,name='') e handle(args,by=None)。Teste可注入 validator  e  rpc；生产使用固定可信 robotd Caminho e 真实 socket，Teste / 演示不能把假Sucesso当生产确认。

## Validação e 交付

先写Falha用例再实现关键读写Caminho。档案遍历 / 链接 / 重复Caminho / 大小 / 哈希 / 不兼容必须拒绝；临时Falha不留半Instalação；默认不可删除、有引用不可删除；选用 e 按键变更需回读，Falha回退。HTTP Validação会话 / Origin / CSRF e大小；无头浏览器Validação管理入口、导入、命名、选用、改键、删除 e 恢复。真机不发送运动、不切实际ControleModelo，实际部署e加载另按Atual状态核验。
