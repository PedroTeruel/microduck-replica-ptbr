# IMU 初始方向可重复标定

用户重新授权的是“初始方向保存后仍能重新做、安装四元数也能重新校验”。之前取消的采集算法改造保持取消：不改变粗校的静止3秒／前倾3秒／扶正再 verify-imu，不改变站姿精校的方向采集算法。只做本地实现与模拟验证，不连接板子，不构建或烧录新镜像。

## 已确认的问题与设计选择

`CoarseCard` 在 mount.verified 不是 false 时直接隐藏；后端 coarse/verify 又只接受 commissioning。因此已有错误配置或改变装法的用户无法通过网页回到初始粗校。只显示按钮仍不能完成恢复。motion 下直接写方向会绕过原 runtime 验证；整套 calib-commit 会重置关节零位。采用受控地临时返回 commissioning，保持原 verify-imu 流程。

## 用户流程

1. IMU 页始终展示“初始方向标定（可重新做）”入口。已确认时不自动开始，点击“重新标定方向”并明确确认后才进入。
2. motion 模式必须先由用户卸力，并有新鲜回读确认扭矩OFF、策略关闭、无起身或临时增益恢复；保持双手扶住。重新标定按钮说明会重启主程序，但保留关节标定和原IMU方向备份。
3. 使用受控 helper 切回 commissioning；已有 factory commissioning 直接打开原粗校，不新增覆盖文件。
4. 原样采静止、采实际前倾，算方向，回正后点击主程序验证，再按提示前倾。验证失败可重采，保存前不改旧IMU方向。
5. 原来处于 motion 的重标定会话在验证成功并回读一致后恢复原运动模式，保持卸力。原本 factory commissioning 的流程不擅自切模式。粗校成功后入口仍可再次进入。
6. 会话跨网页刷新、Studio重启和板子断电可恢复，界面显示“重标定未结束”，可继续验证或明确取消并恢复进入前备份。

## 实现边界

- 新增固定 helper 动词 `imu-recalibrate`，仅接受 enter/status/finish/cancel，参数严格校验，无任意路径、命令、服务名。与 bus-take / calib-commit 共用锁，并阻止这些写操作干扰正在进行的重标定会话；卸力不被锁挡住。
- enter 使用新鲜双快照门槛、保存当前主程序有效ExecStart、主／saved标定、控制服务状态及源信息。只允许直接robotd命令；生成唯一自有的持久commissioning drop-in，并先持久保存带版本及会话ID的manifest。重启后须读到commissioning及卸力。不能修改或删除出厂drop-in和其他人的配置。
- original runtime verify 会把 motion_enabled 写成 false，并保存主／saved文件。finish 必须只恢复进入前的 motion_enabled，保留新验证的当前IMU方向；与进入前逐项比较，除该源安装和 motion_enabled 外任何关节零位／方向／限位、其他IMU和设置均不能变化。复用原子写入、文件校验、完整运行回读及回滚。删除覆盖文件前核对内容/所有权/原始ExecStart，原状态不明则拒绝。
- enter失败恢复进入前状态；finish失败恢复重标定的安全commissioning状态且保留可重试会话；cancel明确恢复进入前标定与模式。不把取消后的旧方向称为本次新验证。
- 后端粗校／验证沿用原计算与固件命令。只有后台确认本次verify成功并且回读 source、verified、quat 一致，才请求finish。不能仅凭helper或RPC accepted显示成功。
- 前端不手工编辑四元数、不翻转模型符号、不改站姿精校的识别算法。只新增重做入口、进度、取消和恢复提示。

## 验证与交付

先补失败测试，再实现。覆盖verified=true入口、两步确认、已在commissioning直接重做、motion未卸力拒绝、原流程成功／失败／重试、持久会话重开、四元数回读不一致、runtime关闭motion_enabled后finish恢复、非2048零位及其他参数保持、覆盖文件被改动拒绝、重启失败回滚、冲突操作拒绝。跑原IMU计算／向导、helper／HTTP、浏览器回归。交付本地代码并说明明天先测试卡部署验证，再打包镜像；不把源码更新称为已完成镜像。
