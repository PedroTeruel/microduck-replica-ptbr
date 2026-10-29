# 摄像头 e  ToF 状态卡

Usuário确认在Bateria、Servo、IMU、手柄、Placa principal所在 de 状态栏加入摄像头e ToF，主要显示在线状态，点击进入已有独立Página。顺序为Bateria、Servo、IMU、摄像头、ToF、手柄、Placa principal。继续本地开发，不Conexão或Atualização板子，IMU 流程保持原样。

摄像头以独立本机 mediad socket  de 只读 hello VerificaçãoServiço响应，ConfiguraçãoLeitura本身不能证明设备在线。Serviço正常且Configuração camera 时显示“Serviço在线／点开确认画面”；test 显示“Teste画面／视频Serviço在线”；Serviço未响应显示“未Conexão”，无设备证明不显示Hardware已识别。ToF 收到Completo新帧才显示在线，fake/sim 标明模拟，Serviço在线但尚无帧显示等待Dados，明确 unavailable 显示未Conexão。错误、超时e未知单独处理。所有Verificação不Por favor求视频帧、不建立 WebRTC、不Inicialização或重启Serviço。

状态栏只在总览／手柄区域可见且浏览器前台时低频Leitura，每10秒一次，离开或后台取消Por favor求e计时。过期读数清空，不沿用在线绿色。手机使用两列，最后Placa principal占满一行；桌面七列，窄桌面分行，所有卡片可读无横向溢出。

Usuário同时询问“没Hardware时自动不InicializaçãoServiço”是否Concluído。已审查AtualImagem：firstboot 自动识别是 IMU；apply-rootfs 把 media source 改为 test，防止摄像头缺失崩溃但仍Execução媒体Serviço；旧Ferramentassuporta手动关闭 ToF／摄像头。这不等于Hardware自动检测e按需Inicialização。该系统策略尚未实现，本轮不把WebRede错误用作关闭系统Serviço依据。
