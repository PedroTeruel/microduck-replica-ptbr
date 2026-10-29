# 项目进度

**项目**：Microduck 复刻
**开始**：2026-08-28
**Histórico进度基准**：2026-09-03（HardwareCódigo aberto状态勘误：HAT 板Oficial已Código aberto）
**仓库**：https://github.com/fanhao375/microduck-replica （公开）

> **模型入口更新（2026-09-28）**：结构件、CAD 与打印工程统一到 [microduck-replica-cad](https://github.com/fanhao375/microduck-replica-cad) 下载。主仓旧 `print/`、`cad/` STL 已移除，目录只保留入口说明。下文分析批次与数量是历史记录；最新实物进度见 [构建日志](构建日志.md)，版本核对见 [CAD 记录](docs/CAD结构件版本核对-20260928.md)。

---

## 目标

复刻 Pollen Robotics  de  **Microduck**（25cm 双足机器鸭，$399，2026 圣诞开卖）。
OficialSoftwareCódigo aberto；Hardware**部分Código aberto** —— **HAT 板有Completo KiCad 工程 e 生产Arquivo**
（[`elec_RPI_Robot_HAT`](https://github.com/pollen-robotics/elec_RPI_Robot_HAT)，Apache-2.0），
但 `imu_to_dxl` 板、可编辑机械 CAD、整机 BOM 与装配文档均未公开。

> **勘误 2026-09-03**：此前记录为「Hardware不Código aberto、无 PCB Princípio图」，**判断错误**。
> 原因是只检索了 `microduck` 主仓，漏掉了同组织下 `elec_` 前缀的硬件仓库。

este projeto从Oficial公开 de  **MJCF 仿真Modelo + 47 个 STL** 反推出Mecânica复刻所需 de 全部信息。

---

## Atual状态（2026-09-29）

| 环节 | 已确认 | 还缺什么 |
|---|---|---|
| 飞特Mecânica | 整机已装，09-18 Concluído站起/Sentar演示；Modelo统一在 CAD 仓库 | 本轮Teste 14 颗关节；嘴部 ID 29 按Usuário要求排除、未验收；装配零位 e 范围仍需逐关节核对 |
| Armbian 与 HAT | DHCP 修复后的个人镜像已联网；HAT 经 `/dev/ttyS2` 读通关节；调试台 0.15.4 已部署 | 长时、带运动通信及保护配置验收 |
| 50 Hz 回读目标 | 3000 轮、14 颗共 42000 状态，此窗口零错误，实际 46.8664 Hz；保持原姿势 e 设置 | 不含 IMU、推理或动作Gravação；不能等同整机 50 Hz Controle循环，其他窗口仍有偶发缺应答 |
| 摄像头 | 正确排线InferiorOficial B1 采集 40 帧、1920×1080 | este projeto Armbian Configuração复测 e 持续帧率 |
| IMU 与 Rust | 0.2.0 固件的飞特接口有软件/模拟测试记录；Rust `feetech` fork 已有适配实现 | 真实混合总线、响应时序和整机上板验收未完成 |
| 训练 | HD1910 工程、M6 参数及短训练检查已整合到 `software/training` | 本机标定、模型核对及实机步态 |
| 公开镜像 | 旧版首登说明改为 `root / 1234`，向导后才创建 duck；新增 DHCP 修复候选版 | 候选镜像仅离线校验，尚未对新产物烧卡实测；基础镜像未装机器人运行时 |

依据：[3000 轮Teste摘要](tools/radxa/50Hz保持姿势读状态-20260928.md)、[ImagemInstruções de uso](tools/radxa/ImagemInstruções de uso.md)、[摄像头记录](tools/radxa/摄像头Registro de depuração-20260928.md)。Inferior一步是有实物支撑条件Inferior逐关节小范围Validação，再Concluído保护、IMU eExecução时接入。以InferiorPreservado早期分析过程，其 em  de Concluído项e待办不能代替Atual实机验收状态。

## Histórico分析基准（2026-09-03）

| 环节 | 状态 | Instruções |
|---|---|---|
| 零件几何 | ✅ Concluído | 47 个 STL |
| 装配关系 | ✅ Concluído | 精确到 0.1mm，已出爆炸图 |
| CAD 装配体 | ✅ Concluído | 已应用世界变换，可直接导入 |
| 关节Parâmetros | ✅ Concluído | 14 个受控关节 de 轴线 e 行程 |
| 质量惯量 | ✅ Concluído | 15 个刚体 |
| 紧Firmware清单 | ✅ Concluído | 孔特征反推，M2 系统 |
| 执行器选型 | ✅ Concluído | XL330 ×15，BAM M6 Parâmetros |
| 轴承规格 | ✅ Concluído | Ø22×16×4、Ø15×10×3 |
| **电控方案** | ✅ Concluído | 从 Rust 源码Completo还原，见「第 6 批」 |
| 主控选型 | ✅ Concluído | **Radxa Zero 3W 市售模块**，非定制载板 |
| **HAT 板** | ✅ Oficial已Código aberto | KiCad + Gerber + BOM + 贴片坐标，直接打样（4 层板） |
| **`imu_to_dxl` 板** | ✅ 已自绘（未打样） | 全网无公开工程；芯片/地址/协议已完整还原，本仓库提供原理图 + PCB |
| **走线方案** | ❌ 缺失 | Oficial无任何资料 |
| **ControleSoftware** | ✅ 可用 | 主控同款则Oficial Rust Execução时直接跑；换主控才需移植 |
| **策略重训** | ✅ 非必需 | Hardware同款则Oficial 9 个 ONNX 直接可用；改本体/电控才需重训 |

---

## 已Concluído

### 第 1 批 · 资料摸底

- ~~确认 **Microduck 硬件不开源**~~：`microduck` 仓库全是 Rust 软件，
  `docs/` 下 5 个子目录全是软件文档，全库搜不到任何 `.stl/.step/.f3d/bom` 文件
  —— **这条结论下错了**（2026-09-03 更正）。只查了主仓，没查同组织下 `elec_` 前缀的
  硬件仓库；**HAT 板在 [`elec_RPI_Robot_HAT`](https://github.com/pollen-robotics/elec_RPI_Robot_HAT)
  里是CompletoCódigo aberto de **（Apache-2.0，含 KiCad + Gerber + BOM + 贴片坐标）。
  教训：判断「某项目有没有Código aberto某部分」时，必须检索**整个组织**，不能只看主仓。
- 确认 **`microduck_rl` 里有 47 个 STL + 完整 MJCF**，这是唯一的几何来源
- 确认 **3D ModeloLicença是 CC BY-NC-SA**（非商用），代码是 Apache-2.0
- 排除了 Open Duck Mini v2 路线（见「决策记录」）

### 第 2 批 · 装配图

- 用 MuJoCo 离屏渲染，白色天空盒，1600×2100
- 4 张常规视图 + 2 张爆炸图 + 1 张分色对照图
- 爆炸图沿运动学链逐级偏移（每级 48mm），越靠链末端炸得越远
- 自己实现了世界坐标→像素 de 投影，usado para画标注引线 e 避让排版
- 产出：`assembly-drawings/`（7 张），脚本 `scripts/render_assembly.py`

### 第 3 批 · CAD 装配体

- upstream 47 个 STL 都是**零件自身坐标系**，直接导入 CAD 会全部堆在原点
- 从 MJCF 取每个 geom  de 世界变换，应用后按刚体分组导出
- 产出：`cad/` —— 整机单文件（796792 三角面）+ 15 个部件，单位 mm
- 整机实测外形 **144 × 141 × 264 mm**（ e Oficial标称 25cm 吻合）
- 脚本 `scripts/export_assembly_stl.py`

### 第 4 批 · 紧Firmware反推

- 写了孔特征识别：焊接顶点 → 建面片邻接图 → 按二面角 35° 切割光滑曲面片
  → 每片拟合圆柱（轴 = 法向协方差最小特征向量）→ 投影拟合圆求直径
  → 按法向朝向判别孔/凸台
- 47 个零件扫完耗时 2.5 秒
- 产出：`docs/紧固件反推.md`、`docs/hole_analysis.json`、`scripts/analyze_holes.py`

### 第 10 批 · 英文文档

- 背景：awesome 列表收录时特意标注 "In Chinese"；流量Dados显示 Google 仅 5 次
  而 Bing 132 次，英文圈基本没进来
- 按访问量定优先级，先翻 `硬件方案逆向.md`（站内访问第 2，84 次），
  因为它是**全网独有Conteúdo** —— HF 员工 @mishig25 做 de  3D 解剖页（3.6 万浏览）
  已覆盖「整机长什么样」那一层，规格类文档 e 其重合，而芯片地址、总线Protocolo、
  12 字节Dados块布局这些只有este repositório有
- 产出：`docs/hardware-teardown.en.md`（426 行）+ `docs/actuator-selection.en.md`（459 行），
  均 e  em 文版互相链接
- 英文 README  de 文档索引改为用 🇬🇧 标记哪些有英文版

### 第 9 批 · 执行器选型分析

- 回答两个高频问题：为什么用Servo不用闭环步进；能不能不改Mecânica件换成便宜 de  STS3215
- **硬Dados对照**：同为 15 刚体双足鸭，XL330 版 **737.2 g** vs STS3215 版 **2107.1 g**，
  差 2.86 倍 —— Open Duck Mini v2 就是「STS3215 版 de 答案」（42cm / 2.1kg）
- **执行器Parâmetros对照**：kp 差 32×、forcerange 差 3.5×、damping  e  frictionloss 各差 11×、
  armature 差 15.5× —— 每一项都差一个Quantidade级
- 反直觉发现：XL330 建模 de 回差反而更大（±1.0° vs ±0.5°）
- 结论：**没有 em 间路线** —— 保 XL330（Servo ¥4500）或换 STS3215
  （等于去做 Open Duck Mini v2）
- **补充同级别Servo横向对比**：飞特 STS3032（20 g / 23.2×12.1×28.5 mm / 0.44 N·m /
  4.8–6 V）尺寸比 XL330 还小、重量相当，但力矩约 85%（同电压口径）且电压Superior限 6 V；
  SCS0009 仅 11 g 但只有 0.23 N·m（Pollen 自己用在 Amazing Hand Superior）
- 结论：空档明确为「18–20 g / ≥0.9 N·m / 7.4 V / 总线」，atualmente只有 Robotis 一家满足
- **深度评估宇树 S288**（通读Oficial 11 页手册）：19.5 g / 34×20×23 mm /
  **减速比 288.35:1  e  XL330 完全相同** / M2 固定 / 单线半双工 —— MecânicaSuperior几乎是平替
- S288  de 两个实质升级：**阻抗Controle**（τ = τ_ff + k_p·Δp + k_d·Δω）e
  **输出端编码器**（OutPos 13 位）—— 后者可直接消灭回差建模 de 整套复杂度
- S288  de 三个硬约束：电压 12.6 V (3S) vs Microduck  de  7.4 V (2S)；
  总线地址空间仅 0~14 装不Inferior第 16 个设备（IMU 须另走 SPI）；
  **力矩标注存疑**（转子端/输出端两种解读都说不通），已列出向厂商求证 de 四个问题
- 产出：重写 `docs/执行器选型.md`（106 → 424 行）

### 第 8 批 · X Comunidade情报 e 外部Validação ⭐

- por meio de opencli  de  twitter read Comando（search / thread）Leitura X 公开帖
- **核心收获：逆向结论获得外部独立Validação** —— @tspy  de Hardware拆解（169 赞）
  独立列出 Radxa ZERO 3W / RK3566， e este repositório完全一致
- 记录热度Dados：Oficial三条推合计约 860 万浏览；GitHub 三天涨 3.7 倍
- 记录Comunidade已做出 de 二次开发（R2D2 语音合成、激光笔追踪、翻筋斗、霹雳舞）
- **识别并标注噪音**：大量 meme 币蹭热度；「Microdino」经查回复区
  充斥 scam 指控且 CAD 问题含糊其辞，**判定为不可信，不予引用**
- 明确一个前提：**截至 8/31 市面无实物**，所有公开 teardown 都是推理而非物理拆解
- 产出：`docs/社区动态.md`（150 行）

### 第 7 批 · Oficial规格交叉Validação + Comunidade动态

- Oficial 2026-08-27 发布，公布部分规格； e este repositório逆向Resultado**逐项对照**
- 互相印证：RK3566 / NP-F550 / 8×8 ToF / 宽 140mm 全部对Superior
- Oficial补足：RAM 1GB + 32GB eMMC（**正是 Radxa Zero 3W  de  SKU，反向佐证主控判断**；源码 em 无佐证，复刻建议 2G/16G）、
  NPU 0.8 TOPS、NFC 双天线
- 逆向独有：主控型号、主总线方案、全部芯片地址 e Protocolo
- **发现一处矛盾**：Oficial标 2 个 IMU，源码里只有 1 个在用（BMI088 标注 dormant）
- 记录OficialCódigo aberto立场：Pollen 明确要求媒体**不要**称其为"Código abertoHardware"（但加了 "for now"）
- 记录Comunidade三个未获回复 de  issue（#175 STEP / #173 打印源Arquivo / #174 Alimentação板Princípio图）

### 第 6 批 · Hardware方案逆向 ⭐

- 思路：**Execução时要驱动真实Hardware，就必须写死设备Caminho、I2C 地址、寄存器偏移、
  波特率eProtocolo —— 代码即规格书**
- 从 `duck-control/src/{model,imu,bus}.rs`、`deploy/*.dts`、`deploy/robotd.toml`、
  `tof/`、`mediad/` 里逐项挖出完整电控方案
- 产出：`docs/硬件方案逆向.md`（394 行，完整推导）+ `docs/硬件规格速查.md`（270 行，一页纸速查）

### 第 5 批 · 执行器选型

- 整理 BAM M6 Configuração、三项域随机化范围、回差编码器建模
- 提取 `joints_properties.xml` 里 5 组 BAM 实测标定的原生 PD 参数
- 产出：`docs/执行器选型.md`

---

## 关键发现

1. **整机是 M2 螺丝系统。**
   Ø2.2 过孔 ×77、Ø4.4 沉头孔 ×28、Ø1.6 攻丝底孔 ×20。
   Ø2.2  e  Ø4.4 成对出现 = M2 内六角柱头 de 过孔+沉孔组合。
   交叉验证：`xl330.stl` 自身是 Ø2.0×4 + Ø1.6×8，与 XL330 的 M2 安装孔一致。
   结构件过孔约 **146 个**。

2. **是 15 个Servo，不是 14 个。**
   `xl330` 网格在整机 MJCF 中被引用 **15 次**。14 个进策略动作空间
   （左腿 5 + 颈头 4 + 右腿 5），第 15 个驱动喙/下颚，走 `passive_*` 连杆。
   这 e Oficial README  de  "15 servos" 一致 —— 只数关节列表会漏掉。

3. **Cabeça占整机四分之一重量。**
   躯干 199g，Cabeça总成 189g，整机 737g。重心很高，
   这解释了为什么它 de Caminhada策略难训。

4. **回差建模是 sim2real  de 关键细节。**
   真实Servo磁编码器在齿轮间隙 de **输出侧**，Firmware位置环闭环在
   `主关节角 + 回差角` 上；舵机在死区空转时测到的位置不变，PD 误差也不变。

5. **自己造比买贵。**
   15 个 XL330 按渠道从 $359（ROBOTIS 国际站）到 €629（MyBotShop）不等，
   即从略低于到远超整机 $399 售价。核价见 BOM.md。

6. **⭐ 主控是市售模块，不是定制载板 —— 此前判断有误。**
   （2026-08-31 补充：此结论已获 X Superior @tspy  de 独立拆解Validação）
   设备树里写死 `compatible = "radxa,zero-3w", "rockchip,rk3566"`，
   就是市面Superior能买到 de  **Radxa Zero 3W**（Pi Zero 形态，65×30mm， e  STL 吻合）。
   这直接推翻了「电控是硬墙」 de 结论。

7. **IMU 挂在 Dynamixel 总线Superior，不走 I2C。**
   自制 `imu_to_dxl` v2 板：LSM6DSV16X，总线 ID 200，寄存器 124，12 字节块
   （陀螺 6 字节 + SFLP 四元数 fp16 6 字节）。e 15 个Servo在**同一次 sync_read**
   里读回，零额外总线开销，主机不用跑姿态融合。

8. **没有电量计，没有 ADC。**
   Bateria电压直接读Servopor meio de Dynamixel 报告 de 自身供电电压。
   所以 6.6–8.2V 是「带载可用区间」而非电芯量程。复刻时**不é necessário设计任何Bateria监测电路**。

---

## 决策记录

| 决策 | 结论 | 理由 |
|---|---|---|
| 做 Microduck 还是 Open Duck Mini v2 | **做 Microduck** | Usuário明确要 Microduck 本身。Open Duck Mini v2 虽然全套Código aberto（BOM/CAD/STL/装配指南齐全），但那是另一台机器人 |
| 仓库公开还是私有 | **公开** | Usuário选择。CC BY-NC-SA 允许转发，已配好Atribuição、同Protocolo、非商用声明 |
| 是否把 6 个上游仓库一起打包 | **不打包** | 分析脚本使用 `scripts/fetch_upstream.sh` 获取上游。2026-09-04 曾提供 `print/` STL 副本；2026-09-28 为避免误打已移除，模型下载统一指向 CAD 仓库。训练工程的来源与许可证另见 `software/training/UPSTREAM.md`。 |
| 许可证 | **双协议** | `scripts/` 原创 → Apache-2.0；`assembly-drawings/` `cad/` 是 CC BY-SA-NC 衍生作品 → 依 ShareAlike 沿用同协议 |
| 遇到 PCB 这堵墙怎么办 | **Mecânica照抄 + 电控自建** | 100% 复刻不可能。Usuário表示能自己做 PCB，所以这条路可行 |

---

## 早期待办存档（以Inferior为Histórico状态）

### 优先级 高
- [x] **画 `imu_to_dxl` 板** —— **原理图与 PCB 都已完成**（2026-09-07）。
      STM32G031F8P6 + LSM6DSV16X + SN74LVC2G241 半双工缓冲；
      45 × 22 mm 双层板，底层整片 GND，22 个Rede全通、DRC 0 违规。
      **未打样、无实物Validação** → [工程 e 复查Resultado](hardware/imu_to_dxl/)
- [ ] **`imu_to_dxl` 打样验证** —— 下单前先跑器件标准化、复核丝印；
      Conexão器高度（直插 8 mm vs 躯干内腔）需用 STEP 在装配体里确认
- [x] ~~**PCB 板框反推**~~ —— **已作废**：Oficial KiCad 工程 e  Gerber 直接提供精确板框、
      孔位 e Conexão器开口，无需从 STL 反推
- [ ] **决定 HAT 板做不做** —— 不要录音/喇叭 de 话可完全省略，
      ToF 直接挂 i2c3，Alimentação用现成 UBEC

### 优先级  em 
- [x] ~~英文化~~ **已Concluído**：Hardware方案逆向 / 执行器选型 / 紧Firmware反推 三份全部英文化，
      加上 README 共 4 份双语。`社区动态.md` 与 `PROGRESS.md` 不翻 ——
      前者时效性强会过期，后者是内部进度
- [ ] `硬件规格速查.md` 暂不翻 —— 与 @mishig25 的 3D 解剖 Space 内容重合度高
- [ ] **STL 可打印性Verificação** —— Validação 47 个网格是否水密、是否有非流形边，
      判断能否直接切片
- [ ] **打印工艺评估** —— 仿真网格无配合公差，需评估哪些孔位要放量、
      哪些面é necessário支撑
- [ ] **走线通道分析** —— 从装配体 de 内部空腔反推可Caminhada线Caminho

### 优先级 低
- [ ] **ControleSoftware方案** —— Rust Execução时绑定 RK3566，评估移植成本
      vs 用 Python 重写Controle循环
- [ ] **策略重训** —— 换电控后官方 ONNX 失效，需用 `microduck_rl` 重训
      （需 CUDA GPU，或用 `--hf-jobs` 跑在 HuggingFace 上）

---

## 风险 e 已知局限

1. **仿真 STL ≠ 可打印工程件。** 仿真只保证外形 e 惯量，不保证配合公差、
   螺纹孔、热熔螺母座、走线空间。直接打印大概率装不起来。
2. **紧Firmware是反推 de ，不是图纸。** 螺丝长度按孔深推算，是区间不是实测值。
   打印收缩还会改变实际孔径（FDM Superior Ø2.2 通常偏小 0.1–0.3mm）。
3. **`imu_to_dxl` 板需自绘。** 全网无公开工程，只能照还原出的协议自己设计。
   （HAT 板Oficial已Código aberto，含 Gerber，**不构成阻塞**。）
4. **Oficial策略不可迁移。** 换电控后 9 个 ONNX 全部失效，必须重训。
5. **非商用限制。** 所有几何衍生Conteúdo受 CC BY-SA-NC 约束，不得usado para商业产品。

---

## Arquivo索引

| Caminho | Conteúdo |
|---|---|
| `README.md` | 项目总览、装配结构、关节参数、可行性分析 |
| `PROGRESS.md` | 本文档 |
| `NOTICE.md` | 署名与来源 |
| `assembly-drawings/` | 7 张装配图 |
| `cad/`、`print/` | CAD 仓库下载入口；旧 STL 与对照表已移除，历史分析产出可从 Git 历史追溯 |
| `docs/紧固件反推.md` | M2 螺丝系统、采购量、轴承规格 |
| `docs/执行器选型.md` | XL330 参数、BAM M6、5 组标定 PD、回差建模 |
| `docs/硬件规格速查.md` | 一页纸硬件规格表 |
| `docs/硬件方案逆向.md` | 电控方案完整推导与证据 |
| `docs/社区动态.md` | X / GitHub 情报、外部验证、噪音与风险 |
| `docs/hole_analysis.json` | 孔扫描原始数据 |
| `scripts/` | 拉上游 / 渲染 / 导出 CAD / 扫孔，4 个脚本 |
