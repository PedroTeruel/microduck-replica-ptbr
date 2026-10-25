# Project research archive

[Home](../README.en.md) · [Documentation](README.en.md) · [简体中文](项目研究归档.md)

> Archived from the README on 2026-10-25. These early investigations describe the upstream XL330 design and the state of the build at the time. Dimensions, prices, feasibility judgments and outstanding work are historical references. Use the current [CAD resources](https://github.com/fanhao375/microduck-replica-cad), [BOM](../BOM/README.md) and [image guide](../software/image/烧录和第一次使用.md) when building today. Run reproduction commands from the repository root.

## 🔨 Build Progress

> This repository states repeatedly that simulation STLs are not manufacturing files.
> **The build log is the test of that claim.** The result gets recorded either way.

**→ [Build Log](../BUILD-LOG.en.md)**

---

## Exploded Assembly View

![Exploded view](../assembly-drawings/06_爆炸图_四分之三.png)

Seven drawings under `assembly-drawings/`:

| File | Contents |
|---|---|
| `01_正面` `02_侧面` `03_背面` `04_四分之三` | Front / side / rear / isometric, assembled, natural colors |
| **`05_爆炸图_侧面`** | 15 parts exploded along the kinematic chain, labeled with names and masses |
| **`06_爆炸图_四分之三`** | Isometric — shows the left/right leg mirroring clearly |
| `07_分色对照_装配态` | Assembled state in the same color coding, for cross-reference |

## Assembly Structure

```
Trunk 199 g
├─ L hip yaw→roll 23 g → L hip roll 6 g → L thigh 48 g → L shin 22 g → L ankle+foot 30 g
├─ Neck base 37 g → Neck pitch 6 g → Head yaw/roll 49 g → Head assembly + beak 189 g
└─ R hip yaw→roll 23 g → R hip roll 6 g → R thigh 48 g → R shin 22 g → R ankle+foot 30 g

Total 737.2 g   Envelope 144 × 141 × 264 mm
```

The trunk and the head weigh almost the same (199 g vs 189 g) — **the head is a quarter of
the whole robot and the center of mass sits high**, which explains why its walking policy
is hard to train.

## Joint Parameters

Five DoF per leg, four for neck and head — **14 under policy control**.
The robot actually carries **15 Dynamixel XL330**: the 15th drives the beak through a
passive linkage and never enters the action space.

| Joint | Travel |
|---|---|
| `hip_yaw` | −25° … +30° |
| `hip_roll` | ±22° |
| `hip_pitch` / `knee` / `ankle` / `head_pitch` | ±90° |
| `neck_pitch` | −90° … +60° |
| `head_yaw` | ±170° |
| `head_roll` | ±25° |

## 📋 Bill of Materials

**Feetech build · compiled by 机械行者Robo · 2026-10-23: 33 printed items and 23 purchased items.** Includes materials, quantities, recorded prices and purchase links. XL330 servos and associated electronics need separate checks.

**[Online preview](../BOM/README.md)** · **[Download the complete Excel file](../BOM/装配BOM-机械行者Robo-2026-10-23-带采购链接.xlsx)**. The same version is also provided in the CAD repository.

The [early reverse-engineered parts estimate](../BOM.en.md) remains available as historical reference; use the current assembly shopping list above when preparing a build.

## Print files and CAD assemblies

**Download models from [fanhao375/microduck-replica-cad](https://github.com/fanhao375/microduck-replica-cad).** SolidWorks, STEP, print projects, assembly BOMs and installation instructions are maintained together there.

| Servo version | Print resources |
|---|---|
| Feetech HD-1910 | [Feetech section](https://github.com/fanhao375/microduck-replica-cad#飞特-hd-1910-打印资料) |
| Dynamixel XL330 | [XL330 section](https://github.com/fanhao375/microduck-replica-cad#dynamixel-xl330-打印资料) |

The old `print/` parts and `cad/` assembly STLs came from upstream simulation geometry and did not include the physical CAD changes. Those files have been removed; the directories now contain download pointers. **Do not mix the two servo versions or print simulation/web-viewer meshes from this repository.**

See the respective CAD sections for file versions, changes and printing methods, and the [printing notes](../print/README.en.md) for general guidance. CAD modelling and assembly documentation are by **机械行者Robo**, with attribution and licensing in the CAD repository. The [assembly videos](../README.en.md#-assembly-videos) walk through the build.

---

## Electronics, Reverse-Engineered from the Runtime

<div align="center">
  <img src="../assets/hw/01-物理布局.png" alt="Microduck electronics overview: where each board sits" width="880">
  <br>
  <sub><b>Physical layout of the five modules.</b> Dashed grey = physical region, solid = module,
  dashed red = mounted <b>outside</b> the shell.<br>
  <b>Orange</b> is the servo bus (top-down), <b>red</b> is battery power (bottom-up).<br>
  The one thing people get wrong: <b>the compute board, the HAT and the camera are all in the head</b> —
  the camera sits ~13 mm from the board centre with no joint between them,<br>
  so the MIPI ribbon never crosses the neck. What does cross it is the servo bus and the power line.<br>
  <a href="../docs/硬件入门.md">Full diagram set (Chinese) →</a>　·　<a href="../assets/hw/Microduck硬件图集.pdf">Download PDF (7 diagrams, A3)</a></sub>
</div>


**One 1 Mbps TTL serial bus does everything.**

```
                Radxa Zero 3W (RK3566) · Armbian
                  ├── UART2  1 Mbps TTL half-duplex ── 15× XL330 + imu_to_dxl (ID 200)
                  ├── I2C3   400 kHz (pins 3/5) ────── AIC3104@0x18 · ToF@0x29 · BMI088 (unused)
                  ├── I2S3   12.288 MHz ────────────── audio
                  ├── MIPI CSI ─────────────────────── IMX219 (I2C@0x10, mounted upside down)
                  ├── Bluetooth ────────────────────── gamepad / phone app
                  ├── Wi-Fi ────────────────────────── WebRTC
                  └── USB-C ────────────────────────── power + maskrom
```

| | |
|---|---|
| **Main board** | **Radxa Zero 3W** — an off-the-shelf module, *not* a custom carrier |
| SoC | RK3566, quad Cortex-A55, Mali-G52, 0.8 TOPS NPU. Official: 1 GB RAM / 32 GB storage. For a replica a 1 GB or 2 GB board **without eMMC** plus a 32 GB microSD card is enough |
| **Servo bus** | **Single-wire half-duplex TTL** — *not* RS-232, *not* RS-485. Dynamixel Protocol V2 @ 1 Mbps on `/dev/ttyS2` |
| **Custom board 1** | **`imu_to_dxl` v2** — an LSM6DSV16X that speaks Dynamixel: bus ID 200, register 124, a 12-byte block read in the *same* `sync_read` as the servos |
| **Custom board 2** | **RPI Robot HAT** — TLV320AIC3104 @ 0x18, a dormant BMI088, a Stemma header for the ToF. **Published by Pollen** ([`elec_RPI_Robot_HAT`](https://github.com/pollen-robotics/elec_RPI_Robot_HAT)) |
| Battery | Sony NP-F550, 2S Li-ion. **No fuel gauge, no ADC** — pack voltage is read from what the servos report as their own supply |
| Sensors | LSM6DSV16X IMU · VL53L5CX/L8CX 8×8 ToF · IMX219 (Pi Camera v2) |

The `imu_to_dxl` design is the elegant part: the IMU is not on I²C. It presents itself as a
Dynamixel slave, so orientation arrives in the same bus transaction as the joint states —
no second bus, no host-side sensor fusion (the LSM6DSV16X's on-chip SFLP block emits a game
rotation quaternion and estimates its own gyro bias).

**Full detail:** [Hardware Teardown](../docs/hardware-teardown.en.md) (English) ·
[Spec Sheet](../docs/硬件规格速查.md) (Chinese)

---

## Can You Actually Build One?

| | Status |
|---|---|
| Part geometry | ✅ 47 STLs |
| Assembly relationships | ✅ 0.1 mm accurate, drawings produced |
| Joint axes / travel | ✅ all 14 |
| Mass / inertia | ✅ all 15 bodies |
| Servo model | ✅ Dynamixel XL330 × 15 |
| Bearings | ✅ Ø22×16×4 and Ø15×10×3 |
| Battery / sensors | ✅ NP-F550 2S, IMX219, VL53L8CX, LSM6DSV16X |
| Main board | ✅ **Radxa Zero 3W, off the shelf** |
| **HAT board** | ✅ **Officially published** — KiCad + Gerbers + BOM → [`elec_RPI_Robot_HAT`](https://github.com/pollen-robotics/elec_RPI_Robot_HAT) |
| **`imu_to_dxl` board** | ⚠️ Not published; must be redrawn. Protocol and register layout fully recovered |
| **Fastener list** | ✅ Reverse-engineered from hole features → M2 system |
| **Cable routing** | ❌ Nothing published |
| Control software | ⚠️ Rust runtime is Apache-2.0 and **runs as-is on the same main board** |

⚠️ **Simulation STLs are not manufacturing files.** Simulation only needs outer shape and
inertia — it guarantees nothing about fit tolerances, threads, heat-set insert bosses or
cable clearance. Printing these directly will most likely not assemble.

💰 **Building one probably costs more than buying one — but how much more depends entirely on
your channel.** Fifteen XL330s run about **$359** at ROBOTIS international, **$412** at ROBOTIS US,
and **€603–629** in Europe inc-VAT — anywhere from slightly under the robot's retail price to well
above it. Add the compute module, battery, two boards to fabricate and filament, and it is certainly
more. Full costing: [BOM.en.md](../BOM.en.md).

**The conclusion has been revised** from "the mechanics are copyable, the electronics are a wall"
to **"the whole robot is reproducible"** — the main board is an off-the-shelf module, and the custom
boards' function and protocol have been fully recovered from source.
See [Hardware Teardown](../docs/hardware-teardown.en.md).

---

## The Realistic Path

Skip 100% replication and go **"copy the mechanics, build your own electronics"**:

| | Approach |
|---|---|
| Mechanics | Select the matching servo version in the [CAD repository](https://github.com/fanhao375/microduck-replica-cad) |
| Servos | XL330 × 15, off the shelf |
| Main board | **Radxa Zero 3W**, same as the original |
| IMU board | Roll your own `imu_to_dxl`: LSM6DSV16X + a small MCU + half-duplex transceiver. The protocol is fully documented here |
| HAT | **Order the official Gerbers** (4-layer); or skip it entirely if you don't need audio |
| Software | Same main board → the official Rust runtime runs unmodified |
| Policies | The nine shipped ONNX policies work; retrain with [microduck_rl](https://github.com/pollen-robotics/microduck_rl) if you change hardware |

## Three Pitfalls Worth Knowing

1. **Armbian runs a login console on UART2.** `serial-getty@ttyS2` holds the port —
   `systemctl mask` it. Pollen found this with `fuser -v /dev/ttyS2`.
2. **i2c3 collides with the FUSB302.** Using the hardware I²C on header pins 3/5 costs you
   USB-C PD negotiation (plain 5 V charging still works).
3. **The NPU ships disabled** in Armbian — flash the overlay and reboot to run RKNN models.

---

## Ecosystem Map

Microduck material is scattered across several GitHub orgs and three HuggingFace resource types —
**the official hardware repos are especially easy to miss**. [`docs/ecosystem.en.md`](../docs/ecosystem.en.md)
annotates every official repo, simulator, policy, dataset and community project with what it is and
what it is good for.

## Documentation

| Document | Contents |
|---|---|
| [**Hardware Spec Sheet**](../docs/硬件规格速查.md) | One-page reference — block diagram, part numbers, bus parameters, build list, pitfalls |
| [**Hardware Primer**](../docs/硬件入门.md) | **Board by board** — what each of the five modules does, how one 20 ms control tick flows, what changes on the Feetech route, and a closing section on **five checks to run before you replicate** |
| [**Electronics Sourcing (CN)**](../docs/电控采购清单.md) | Taobao links with verified availability — main board, camera, ToF, power, both PCBs, cabling and the debug adapter |
| [**Mechanical Sourcing (CN)**](../docs/机械采购清单.md) | Bearings, M2 fasteners, heat-set inserts and the insertion tip, thread locker, filament |
| [**Hardware Teardown**](../docs/hardware-teardown.en.md) 🇬🇧 | **Full derivation with evidence citations — the main board, both custom boards, bus protocol, sensors, power** |
| [**Actuator Selection**](../docs/actuator-selection.en.md) 🇬🇧 | XL330 parameters, BAM M6 config, five calibrated PD sets, backlash modeling — plus **why closed-loop steppers do not work here, what swapping to a Feetech STS3215 actually costs** (737 g vs 2107 g, measured), and a **cross-comparison of same-class servos** including a deep assessment of the Unitree S288 |
| [**Fastener Reconstruction**](../docs/fastener-reconstruction.en.md) 🇬🇧 | Hole-feature scan across 47 STLs → M2 system and purchase quantities |
| [Community Intelligence](../docs/社区动态.md) | X / GitHub signals, independent verification, noise and scam warnings |
| [Progress](../PROGRESS.md) | Status, decisions, open work |

> 🇬🇧 marks documents available in English. The rest are Chinese-only for now — their
> tables, part numbers, addresses and diagrams are readable without it, and machine
> translation handles the prose well.

## Reproducing This

```bash
# 1. Fetch upstream for the drawing scripts below (training is already in software/training/)
bash scripts/fetch_upstream.sh

# 2. Regenerate the drawings
python scripts/render_assembly.py upstream/microduck_rl assembly-drawings

# 3. Export upstream assembly previews for analysis (not manufacturing)
python scripts/export_assembly_stl.py upstream/microduck_rl analysis-output/cad-upstream

# 4. Re-scan hole features
python scripts/analyze_holes.py upstream/microduck_rl/src/mjlab_microduck/robot/microduck/assets
```

Requires `mujoco`, `numpy`, `pillow`, `scipy`. Rendering needs a working OpenGL context.

## License

- `scripts/`, the code in `software/studio/`, and `software/image/` — Apache-2.0
- The walking and skill models in the replica image are not in this repository; they are under their author's personal non-commercial licence, so **the image must not be distributed with any paid product** (see the [model notes](../software/image/overlay/usr/share/doc/microduck/模型说明.txt), Chinese)
- `assembly-drawings/` and retained simulation meshes — **CC BY-SA-NC 4.0**. Upstream 3D models are CC BY-SA-NC;
  ShareAlike requires derivatives to carry the same license. **Non-commercial only.**

See [NOTICE.md](../NOTICE.md). Not affiliated with or endorsed by Pollen Robotics.
