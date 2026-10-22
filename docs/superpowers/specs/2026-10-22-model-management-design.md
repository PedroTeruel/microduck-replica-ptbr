# Studio 模型管理

用户已确认 UI-08，并在 2026-10-22 明确要求开始实现。目标是把电脑上已经训练、导出的模型装进鸭子，选择使用、命名、改手柄键、删除以及恢复默认，不要求用户重新烧录系统镜像。

## 使用流程

总览「管理」直接进入 `#/models`。顶部为导入按钮和简明说明；列表区分内置默认与自行导入，显示名称、用途、是否当前选用、是否正在执行、按键。安装不自动启用或上力。路径、哈希及训练细节折叠显示。重量和导出鸭子档案保留在原设置页，不混入模型管理。

导入支持现有部署导出目录打成的 ZIP 或 tar.gz：一个 policy.onnx、manifest.json、deployment-contract.json，以及该模型的可选执行配置。安装前检查档案边界、文件身份、用途和主程序的真实 ONNX 预检；失败不出现在可用模型列表中。名称可编辑；禁止覆盖系统文件或现有模型。

选用复用 robot.loadPolicy；成功以 robot.policies 回读为准，不能把 accepted 当成功。失败尝试恢复旧路径并如实报告回退结果。基础内置路径保存为默认恢复来源，避免 custom_only 的通用 reset 误指向官方其他模型。

手柄按键使用当前主程序实际支持的 A、X、LB、RB、十字下；复用 pad.bind，解绑为空字符串，恢复默认采用省略 skill 的原生语义。冲突明确显示原动作，用户选择替换后才写入。动作与模型用途分开，行走不是普通按一下执行的技能。

自行导入模型允许删除；当前仍被槽或按键用途引用时先明确要求切换 / 恢复默认，不留下悬空引用。内置文件不提供删除入口。正在运动 / 未确认卸力时拒绝切换等运行配置更改，保留现有急停和基础按键。

## 架构

- 所有导入文件在 Studio 用户可写的 state/models 下，默认 /var/lib/microduck-studio/models。无需增加 root helper 权限。
- model_package.py：档案安全提取、静态合同检查、调用 robotd validate-policy；不连接硬件。
- models.py：库元数据、默认来源、安装、改名、删除、运行端 RPC 和回读确认。
- app.py：同源 / 会话 / CSRF 校验后的 HTTP 接口，流式限制上传大小，序列化变更。
- models.js：独立管理页。现有 tune.js 总览卡改为链接该页。

## HTTP 契约

GET /api/models 返回 {ok:true,data:View}；POST /api/models/import 接收原始 ZIP/tar.gz 字节，URL 参数 filename、name（可选），要求 X-CSRF。POST /api/models/op 接收不超过 32KiB 的 JSON，并要求 X-CSRF。

操作：rename{id,name}、select{id,slot}、restore{slot}、delete{id}、bind{button,slot,replace?}、unbind{button}、reset_bindings{}。

成功返回 {ok:true,data:View}。失败返回 {ok:false,error:中文原因,code:可选标识}，HTTP 400/409/413/503 按实际错误选择。ModelError 为 service 层可预期异常。

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

Models(rd,log,state_dir,tune=None,root='/',validator=None,rpc=None) 提供 async view()、import_package(path,name='') 和 handle(args,by=None)。测试可注入 validator 与 rpc；生产使用固定可信 robotd 路径及真实 socket，测试 / 演示不能把假成功当生产确认。

## 验证与交付

先写失败用例再实现关键读写路径。档案遍历 / 链接 / 重复路径 / 大小 / 哈希 / 不兼容必须拒绝；临时失败不留半安装；默认不可删除、有引用不可删除；选用与按键变更需回读，失败回退。HTTP 验证会话 / Origin / CSRF 和大小；无头浏览器验证管理入口、导入、命名、选用、改键、删除与恢复。真机不发送运动、不切实际控制模型，实际部署和加载另按当前状态核验。
