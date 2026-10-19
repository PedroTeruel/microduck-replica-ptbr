# Studio 的 root 小助手：舵机总线交接、手柄配对（安装、卸载、上机核对）

写给人看，也写给以后接手的 AI 看：每一步都写了为什么。
方案出处：scratchpad `console/handover-plan.md`（v2 定稿）§2.2、§4.2、§5；规矩照 `console/studio-ops-plan.md` §7。

## 1. 它是干什么的

Studio 的舵机页要自己打开舵机总线 `/dev/ttyS2`，所以主程序 robotd 要先停下，用完再交还。

- 停、起 robotd 要 root，Studio 不是 root。
- 所以只给 Studio 一把「只能开这一扇门的钥匙」：sudoers 只放行 `/usr/local/sbin/microduck-helper` 这一个文件。
- 它只认五个动词，参数逐个校验，robotd 是什么状态它自己去读，不信网页传来的。

| 动词 | stdin（一个 JSON 对象） | 做什么 |
|---|---|---|
| `bus-take` | `{"by": "谁·哪台电脑", "allow_seated": false}` | 接管，**不卸力**：先停手柄服务 → 隔 200 ms 读两次主程序状态（策略在跑就拒绝；坐姿只有 `allow_seated` 并且不动才放行；正在回站姿最多等 3 秒）→ 立旗 → `systemctl stop --no-block robotd`，10 秒没停就 KILL → 确认串口没人占 |
| `bus-give-back` | `{"by": …, "soft": true}` | 软交还：Studio 已经在总线上全卸了。撤旗 → 起 robotd → 等启动 4 步都 success → 拉回手柄服务 → 放锁 |
| | `{"by": …, "marker": {…}}` | 不卸力交还：写交接标记 → 撤旗（**锁不放**）→ 起 robotd → 等 robotd 接手（接手保持、不开模型）。没接手就把总线拿回来，交给 Studio 接着保持 |
| `bus-abort` | `{"by": …}` | 中止交接（交接倒数期间按了网页卸力）：立旗 → KILL robotd → 删标记 → 确认串口空出来。目标 1 秒以内，之后 Studio 自己开串口卸力。**没有会话时拒绝（退出 3）**：旗、管理锁、交接标记都不在就什么都不碰 |
| `pad-pair` | `{"by": …, "mac": 可选, "timeout": 10–120（默认 60）}` | 以 root 跑官方 `/usr/local/bin/robotctl pad pair --json --timeout N [MAC]`。MAC 先转大写再校验。子进程总超时 = `timeout + 30` 秒（超时就杀掉）。robotctl 在 `/var/lib/robot/weird-ble` 板上会先停 btd、给适配器断电再开，最后把 btd 起回来。**不碰**总线旗子、hold 单元、robotd，也不拿服务管理锁；只拿 `helper.lock`，一次只跑一个配对 |
| `pad-forget` | `{"by": …, "mac": …}` | 以 root 跑官方 `/usr/local/bin/robotctl pad forget MAC`（MAC 必填，校验同上）。同样不碰总线、hold 单元、robotd |

**输出**：一行一个 JSON：`{"step", "level", "ms", "msg", "detail"}`，最后一行 `step="done"`，`detail` 里有 `exit` 和 `result`。同一份结果写进 `/run/microduck-helper/last-result.json`（0644），Studio 重启以后读它。

`pad-pair` 的 `detail` 还有：`pair`（robotctl 的 stdout，按 `PadPairResult` 解析：`{"outcome":"paired","pad":{…}}` 或 `{"outcome":"failed","reason":"not_found|ambiguous|timeout|no_adapter|rejected|other","detail":…}`）、`stderr`（robotctl 的几行提示，如 `paused btd …`、`warning: …`）和 `stdout`。配上了退出 0；robotctl 说失败退出 5，`detail.reason` 保留官方原因。`pad-forget` 的 `detail` 有 `removed`（true / false / null）、`stdout`、`stderr`。

**退出码**

| 码 | 意思 |
|---|---|
| 0 | 成功 |
| 2 | 参数错（动词不认识、stdin 不是 JSON 对象、有不认识的键、标记校验没过） |
| 3 | 状态不允许（没装保护、策略在跑、没有会话、不是 root） |
| 4 | 忙或中止（管理锁被板端脚本占着、小助手正在跑别的总线操作 / 另一个配对或忘掉、交还被中止） |
| 5 | 执行失败（停不下来、串口被占、robotd 没认标记已经全卸、软交还起不来；或者 `pad-pair` / `pad-forget` 找不到 robotctl、robotctl 说配对失败、超时被杀） |
| 6 | 交接没成，总线已拿回（旗重新立好、robotd 停了、锁还在），Studio 重开串口接着保持 |

`result` 的取值：

- bus-take：`taken`、`refused`、`no_guard`、`busy`、`stop_failed`、`port_busy`
- bus-give-back：`adopted`、`retake`、`retake_failed`、`limp`、`aborted`、`soft`、`soft_failed`、`refused`、`no_session`、`detach_failed`
- bus-abort：`aborted`、`abort_incomplete`、`no_session`（没有会话时拒绝，退出 3）
- pad-pair：`paired`、`pair_failed`（退出 5，`detail.reason` 是官方原因）、`timeout`、`no_robotctl`、`bad_output`
- pad-forget：`forgotten`、`forget_failed`、`timeout`、`no_robotctl`
- 都可能有：`bad_args`、`bad_marker`、`bad_verb`、`not_root`、`busy`、`error`

## 2. 文件和路径

| 东西 | 位置 | 为什么 |
|---|---|---|
| 小助手 | `/usr/local/sbin/microduck-helper`（root:root 0755，`#!/usr/bin/python3 -IS`） | `-I` 不读用户的环境和目录，`-S` 不加载 site。Linux 把 shebang 后面当成一个参数，所以写成 `-IS`，不能写 `-I -S` |
| robotd 的 drop-in | `/etc/systemd/system/robotd.service.d/zzzz-studio-bus.conf` | `ConditionPathExists=!/run/microduck-helper/bus-held`：旗在，robotd 就起不来。**不用 `systemctl mask --runtime`**：robotd 的本体在 /etc，/run 里的 mask 盖不住 |
| sudoers | `/etc/sudoers.d/microduck-studio`（0440） | 只放行一个全路径。装之前 `visudo -cf` |
| 旗 | `/run/microduck-helper/bus-held`（目录 0755、文件 0644） | 在内存盘里：断电、重启就没了，robotd 照常开机自启。不放在 Studio 的目录里，是因为 Studio 单元以后要是用 `RuntimeDirectory`，systemd 会在 Studio 重启时删掉那个目录。**Studio 的单元不许用 `RuntimeDirectory=microduck-helper`** |
| 中止请求 | `/run/microduck-helper/abort` | bus-abort 写，正在跑的 bus-give-back 看到就停 |
| 小助手自己的锁 | `/run/microduck-helper/helper.lock`（flock） | bus-take、bus-give-back、pad-pair、pad-forget 一次只跑一个（一次只允许一个配对）。**bus-abort 不拿**：卸力不能被正在跑的交还挡住，它的几步都可以重复做 |
| 官方 robotctl | `/usr/local/bin/robotctl`（写死在 `deploy/microduck-helper` 里） | 只有 `pad-pair` / `pad-forget` 调它。不存在就回 `no_robotctl`（退出 5），不会去别的路径找 |
| 管理锁 | `/run/microduck-service-management.lock`，由临时单元 `microduck-bus-hold` 一直拿着（`flock -n … sleep infinity`） | 板上的 `service.sh` 拿不到这把锁就不动 robotd |
| 交接标记 | `/run/microduck-handover/handover.json`（目录 0700、文件 0600，同目录临时文件 + fsync + rename） | 只有 root 读写；robotd 读完就删 |
| 操作记录 | `/var/lib/microduck-helper/oplog.jsonl`（目录 0700、文件 0600） | 一次一行：谁、什么时候、结果 |

**标记格式**（fork 的 robotd 照这个读）：

```
{"schema": "microduck-handover/1", "requested_by": str, "boot_id": str, "mono_ms": int,
 "ttl_ms": int, "port": "/dev/ttyS2", "arm_registers": {"limit", "p", "d"}（可选）,
 "joints": [{"id", "torque", "goal", "present", "offset", "load"?, "temp"?, "status"?} × 15]}
```

- `boot_id`、`mono_ms`（CLOCK_MONOTONIC 毫秒）由**小助手自己填**，Studio 给了也覆盖掉。
- **ttl_ms 超过 30000 直接拒（退出码 2），不悄悄截断**，低于 1000 也拒；默认 20000。robotd 那边最多也只认 30 秒，两边说法一致。
- id 必须正好是 10–14、20–24、30–34，每个一次；torque 必须是 1（主程序只接手 15 颗全开的）；goal、present、offset 是 −32767..32767 的整数。

**几个时间**：

| 时间 | 值 |
|---|---|
| gate 两次读的间隔 | 0.2 s |
| 等回站姿 | 3 s |
| stop 到 KILL | 10 s |
| KILL 以后再等 | 3 s |
| robotd 读标记 | 15 s |
| 接手后走完启动第 4 步 | 20 s |
| 软交还 | 30 s |
| 中止交接 | KILL 后等 0.5 s |

**几个环境变量**：`MICRODUCK_HELPER_DETACHED`、`MICRODUCK_HELPER_REQUEST`、`MICRODUCK_HELPER_REQUESTED_MS`。

- 用途：bus-give-back 第一次被调用时，用 `systemd-run --wait --pipe --collect --quiet --unit=microduck-handover-<时间>-<pid>` 把自己放进独立的临时单元再跑一遍，stdin 原样转过去，输出原样转回来。这样 Studio 死了，交还也不会断在半路。
- 这几个变量**只**决定「不要再转一次」，以及中止请求、结果怎么对号，**不给任何权限**。sudo 默认 env_reset，调用方也传不进来。
- **没有任何环境变量能改根目录**：测试是 import 进去、换一个假的 Ctx，不靠环境变量。

**所有判断 robotd 起没起来的地方**，都看 `systemctl show robotd -p ActiveState,SubState,Result,ConditionResult`。旗在的时候 `systemctl start robotd` 返回 0，但单元停在 inactive、`ConditionResult=no`，不能当成起来了。每次拉 robotd 之前都先 `reset-failed`，防撞上 start-limit-hit。

**信任边界**：能 sudo 小助手的用户（现在是 radxa）本来就能直接打开 ttyS2；robotd 又会在总线上回读核对标记。所以伪造标记不会多给权限，最坏是「保持住本来就顶着的舵机」。

## 3. 安装（一次，SSH）

```sh
# 电脑上：把 deploy 目录拷到鸭子上
scp -r deploy radxa@鸭子:/tmp/studio-deploy
# 鸭子上
cd /tmp/studio-deploy && sudo sh install.sh radxa
```

`install.sh` 做四件事：

1. 装小助手到 `/usr/local/sbin`（0755）；`/usr`、`/usr/local`、`/usr/local/sbin` 要是属主不是 root，或者组 / 其他人可写，就提醒；
2. 装 drop-in，然后 `systemctl daemon-reload`。**不重启 robotd**；
3. 生成 sudoers 那一行，`visudo -cf` 过了才装（0440）；
4. 打印核对信息。

**第 1 步只装 drop-in 的 `[Unit]` 那段。** `[Service] Environment=MICRODUCK_HANDOVER_MARKER=…` 是注释掉的：等 fork 的 robotd 装好、第 3 步（Studio 交还不卸力）验收以后，再手动打开那两行、`daemon-reload`。打开以后 robotd 下次启动才会看交接标记；没有标记就跟 V167 完全一样。旧版 robotd 不认这个变量，打开了也没影响。

装完马上核对：

```sh
systemctl show robotd -p DropInPaths            # 要有 zzzz-studio-bus.conf
echo '{}' | sudo -n /usr/local/sbin/microduck-helper bus-nope; echo $?   # 用 radxa：应该是 2
echo '{}' | sudo -n /usr/local/sbin/microduck-helper bus-take;  echo $?  # 应该是 2：缺 by（什么都没动）
echo '{}' | sudo -n /usr/local/sbin/microduck-helper pad-pair;  echo $?  # 应该是 2：缺 by（不跑 robotctl）
ls -l /usr/local/bin/robotctl                                        # 官方 0.15.1 或更新
stat -c '%U:%G %a %n' /usr /usr/local /usr/local/sbin /usr/local/sbin/microduck-helper
sudo -l -U radxa | grep microduck-helper
```

## 4. 卸载

```sh
sudo sh uninstall.sh            # 旗在（Studio 正占着总线）时拒绝
sudo sh uninstall.sh --purge    # 连 /var/lib/microduck-helper 一起删
```

卸载会删掉 sudoers 那一行、drop-in（然后 daemon-reload）、小助手，停掉 `microduck-bus-hold`，清掉 `/run/microduck-helper` 和 `/run/microduck-handover`。robotd 不重启。

## 5. 出事时怎么看

- `sudo ls -l /run/microduck-helper/`：`bus-held` 在 = 主程序被 Studio 挡着，起不来是故意的。要放开：在 Studio 里交还，或者重启。
- `cat /run/microduck-helper/last-result.json`：上一次做了什么、卡在哪一步（`steps` 是最后 30 行进度）。
- `journalctl -t microduck-helper -b`：每一行进度都写在这里。
- `systemctl status microduck-bus-hold`：管理锁在不在 Studio 手里。
- `sudo tail /var/lib/microduck-helper/oplog.jsonl`：操作记录。

## 6. 上机核对清单（二号鸭，用户扶着；他说开始就连着跑，不用每次问）

**先只读核对**（不动任何东西）：

- `systemctl --version`（257）、`sudo -V | grep -i -E 'env_reset|secure_path'`、`ls -l /etc/sudoers.d`。
- **systemd-run 那几个行为**：
  - `systemd-run --wait --pipe --collect --quiet -p … /bin/sh -c 'exit 6'; echo $?`：`--wait` 会不会把服务的退出码带回来。小助手不靠这个，先读 last-result 里的 request_id 对号，对不上才用 systemd-run 的退出码；
  - `--pipe` 下把调用方杀掉，服务里面的进程写 stdout 会拿到 EPIPE（小助手忽略 SIGPIPE），而不是被一起杀掉；
  - 临时单元默认 `KillMode=control-group`，所以 `systemctl stop microduck-bus-hold` 会连 flock 和 sleep 一起停掉、锁跟着放掉。用 `flock -n /run/microduck-service-management.lock true; echo $?` 核对。

**第 1 步的上机测试（跟小助手有关的）**：

| 编号 | 做什么 | 看什么 |
|---|---|---|
| U1 | 卸力状态下 `bus-take` | 退出码 0；旗在；robotd inactive；Studio 开串口读 40 全是 0、位置不变 |
| U2 | 站姿保持（init 以后）`bus-take` | 0；Studio 读 40 全是 1，位置差 <1°，鸭子不往下沉 |
| U3 | 策略开着（手柄 Start 进保持）`bus-take` | 3，原因是「先按手柄 Start…」；padd 回来了；robotd 没被停。按 Start 2 秒回站姿以后再 take → 0，不软 |
| U4 | 旗在的时候 `sudo systemctl start robotd` | 退出码 0，但 `systemctl show robotd -p ActiveState,ConditionResult` 是 inactive / no；板上的 `service.sh status`（路径以板上实际为准）被锁拒：「已有服务管理操作正在执行」 |
| U4b | 旗在时 KILL 以后的自动重启 | **不要在用户拿着总线的时候拿 robotd 做。** 先用一个假单元验：建一个带同样 Condition 的临时服务，起来、立旗、`systemctl kill -s KILL`，看 2 秒后它有没有被拉起来。用户空下来以后，再在 robotd 上做一次 |
| U4c | 旗在时连着 `systemctl start robotd` 6 次 | 看 `Result` 会不会变成 start-limit-hit。然后撤旗（`bus-give-back {"soft":true}` 会先 reset-failed）确认能起来 |
| U5 | 会话中 `systemctl restart studio-trial` | 鸭子不软；旗、`microduck-bus-hold` 还在；Studio 起来以后 `bus-take` 返回 0，detail 里 `session_was_open=true` |
| U6 | 软交还 | 扶住；`bus-give-back {"soft":true}` 返回 0；robotd 四步 success；padd 回来；`microduck-bus-hold` 停了 |
| U7 | 离开舵机页 | 有保持就不交还（另一个子代理的部分，一起验） |
| V0（小助手部分） | 量 `bus-take` 和 `bus-abort` 各用多久 | 看 last-result 的 `ms`；abort 目标 ≤1 秒 |
| U8 | 在 Studio 里配一次手柄（雷神 G50 Pro，Switch Pro 模式，名字 `Pro Controller`） | 向导里「配对走的是」写小助手；`cat /run/microduck-helper/last-result.json` 的 `verb=pad-pair`、`result=paired`，`detail.stderr` 有 `paused btd …`；30 秒内 padd 认到并进按键测试。没有新版小助手时向导会提示先重装 |

**还没覆盖到的**：标记交还（`{"marker": …}`）要等 fork 的 robotd 装上、drop-in 打开 Environment 以后才能在板上测，那是第 4 步的 V1–V12。

## 7. 已知的限制

- bus-take 在「判完状态」到「立旗、停 robotd」之间，有大约 0.1 秒的窗口，这期间蓝牙 App 还能把策略打开。padd、gamesir 已经先停了，btd 没停。
- configd 的 `system.reboot`、SSH 里直接 `poweroff` 拦不住（方案 §2.5）。重启的话，robotd 起来时照老规矩全卸。
- 交接倒数期间手柄 Select 不起作用（padd 要等 robotd 四步都 success 才启动）；那几秒用网页卸力（走 bus-abort）或关电源。
- 旧版小助手（不认 `pad-pair`）会回 `bad_verb`；Studio 把它当没有新版小助手，退回 configd → bluetoothctl。这块板（`/var/lib/robot/weird-ble`）上后备路可能配不上，向导会提示重装小助手或在鸭子上运行 `sudo robotctl pad pair`。
