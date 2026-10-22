# HD1910 single-leg balance

`Mjlab-Balance-Flat-MicroDuck-HD1910` uses the existing HD1910 Feetech BAM
actuator, 14 actions, 61 actor observations, and 50 Hz control. Its experiment
directory is `microduck_hd1910_balance`. The new task uses the existing full
collision robot model so head, knee and trunk support can be detected and
rejected. Walking tasks keep their original model and behavior.

The saved skill is exactly:

```json
{"support_side": "left", "lift_height_m": 0.01, "hold_seconds": 3.0}
```

Support is `left` or `right` in the robot's own frame. Clearance is 0.005–0.02 m;
hold is 1–5 s. Values are fixed for a run and reused for evaluation and export.
Typed training overrides are supported by frozen mjlab 1.3.0:

```sh
uv run --frozen --no-sync --offline train Mjlab-Balance-Flat-MicroDuck-HD1910 \
  --env.commands.twist.support-side left \
  --env.commands.twist.lift-height-m 0.01 \
  --env.commands.twist.hold-seconds 3 \
  --env.scene.num-envs 64 --agent.max-iterations 5
```

The cycle has 1 s initialization/weight transfer, 1 s smooth lift, the requested
hold, 1 s lowering, and 0.5 s settling. A cycle timeout completes the episode
after 3.5 + hold seconds, independently of whether the skill succeeded. The
9 s episode ceiling accommodates every accepted hold value, including direct
CLI overrides. Each reset starts at phase zero; partial resets only reset their
own clocks. Training keeps automatic resets; evaluation disables them so the
terminal state can be measured before an explicit seeded reset.

The three twist slots have a task-specific contract:

1. Support sign: +1 left, −1 right.
2. Scheduled clearance of the swing foot's lowest sole vertex, in metres.
3. Phase / 3: initialization 0, lift 1/3, hold 2/3, return 1.

Head/body slots retain their widths with tiny ranges and exact-zero sampling.
The ONNX normalizer is exported through the existing runner path. Export requires
`--balance-config skill.json` and writes both ONNX metadata and a `.skill.json`
sidecar. **A matching runtime scheduler is required.** Shared tensor dimensions
do not make this policy ready to replace a velocity policy on hardware.

## Reward and measured success

Dense reward tracks scheduled sole clearance and transfers whole-robot CoM
toward the named support foot. A hold reward additionally requires loaded named
support, no swing-foot contact, acceptable tilt and low velocities. Return
reward requires both feet down. No fixed joint target is imposed. Positive
costs use negative weights, while all positive task rewards reject non-finite
state. Head/body terrain contact ends the episode. Existing finite critic
observations and BAM startup fields are retained, including force checks on
both ground sensors. Command curricula and large walking pushes are removed;
small mass, friction, encoder, IMU, delay and CoM randomization remain.

Evaluation uses measured 50 Hz samples, not reward. Success requires the full
cycle, essentially the full continuous requested hold (two frames of boundary
tolerance), and 0.46 s or more of the final 0.5 s two-foot settle. Hold checks:
named support contact with ≥0.5 N force, no other body support, no swing contact,
clearance error ≤max(2 mm, 20% of target), trunk tilt ≤25°, root speed ≤0.08 m/s,
support-foot speed ≤0.04 m/s, and projected sole-outline CoM margin ≥−2 mm.
The outline margin is an approximation for a tilted foot and never proves
stability by itself. Contact, speed and sustained duration are separate gates.
Return requires both sole clearances within 3 mm of the plane. Missing samples,
non-finite state, physics termination and interrupted holds are failures.

## CPU geometry evidence and limitations

Read-only MuJoCo forward-kinematic/IK probes used actual sole mesh vertices and
XML joint bounds on both sides at 5, 10 and 20 mm. Total model mass is
0.73724318 kg. HOME CoM is centered while sole inner edges lie about 21.2 mm
from center: raising a knee without lateral weight transfer is insufficient.
HOME foot sites differ from sole minimum height by about 0.054 mm; rotation
invalidates a constant offset, so runtime clearance uses transformed meshes.

All six height targets were reached to within 5 µm, but unconstrained solutions
approached joint limits (0.057° minimum margin) and used excessive head motion.
Constrained candidates at 10 mm, with modest head/hip yaw and trunk tilt below
25°, had projected outline margins −0.37 mm (left) and +0.35 mm (right), with
support-foot tilt 1.7–2.3°. These establish height reachability, **not a robust
static equilibrium**. No candidate is used as a reference reward pose.

CPU regression tests check the actual transformed collision geometry, both
support sides, phase reset behavior, typed CLI arguments, signs, and failure
classification. A noisy 3 s settle test using the actual HD1910 actuator and
trained-policy hold/return evaluations are still needed before any stability
or hardware readiness claim. A five-iteration smoke run checks integration;
it does not establish that a useful skill has been learned.
