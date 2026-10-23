"""HD1910 adaptation catalog built from public task-name/budget metadata only.

The engine independently defines registrations. Contract tests compare the two;
the lightweight Studio server never imports the GPU training package.
"""
import copy

from .recipe_verification import RECIPE_VERIFICATION


SOURCE_REVISION = "525a215a19397767a073b782f57e97cf53683761"
REFERENCE_ENGINE_REVISION = "8d0db74916a4f833d1d9b95d6a1d7f4d13b9d5ec"
ENGINE_BASELINE_REVISION = "d424a0c899f6b33cbd3daeb279913134349c0b63"
SOURCE_URL = ("https://github.com/kissqy/Microduck-kissqy/blob/" + SOURCE_REVISION +
              "/microduck-hd1910/training-console/data/tasks.json")
OFFICIAL_SOURCE_URL = ("https://github.com/pollen-robotics/microduck_rl/tree/" +
                       ENGINE_BASELINE_REVISION + "/src/mjlab_microduck/tasks")
BUDGET_NOTE = ("默认预算沿用参考目录的 4096 环境 × 每轮 24 步；轮数是预算上限，不保证收敛。"
               "改变环境数会改变采样量和课程进度，不能按相同轮数视为等效训练；先运行 64 环境 × 5 轮短试跑。")
PREREQUISITE_NOTE = ("需要同地形、同齿隙版本的行走和倒地起身 PT 教师检查点，并核对 HD1910 执行器、"
                     "61 维观测、14 维动作、归一化及指令语义兼容。还需完成教师加载与联合训练适配；"
                     "当前禁止启动联合任务，不能从零替代联合训练。ONNX 成品不能作为 PT 教师直接续训。")

# (category, task stem, public variants, reference iteration budget, rollers)
# These are names and numerical metadata, not imported upstream implementation.
_FAMILIES = (
    ("行走与倒地起身", "VelStand", ("Flat", "Flat-Backlash", "Rough", "Rough-Backlash"), 6000, False),
    ("坐下与站起", "SitStand", ("Flat", "Flat-Backlash", "Rough", "Rough-Backlash"), 15000, False),
    ("低头捡取", "GroundPick", ("Flat", "Flat-Backlash", "Rough", "Rough-Backlash"), 20000, False),
    ("左脚踢球", "BallKickLeft", ("Flat", "Flat-Backlash"), 10000, False),
    ("右脚踢球", "BallKick", ("Flat", "Flat-Backlash"), 10000, False),
    ("前滚翻", "Roulade", ("Flat",), 10000, False),
    ("行走老师", "Velocity", ("Flat", "Flat-Backlash", "Rough", "Rough-Backlash"), 50000, False),
    ("倒地起身老师", "StandUp", ("Flat", "Flat-Backlash", "Rough", "Rough-Backlash"), 15000, False),
    ("轮滑行走", "Velocity", ("Flat", "Flat-Backlash"), 50000, True),
    ("轮滑蹲下", "RollerCrouch", ("Flat", "Flat-Backlash"), 8000, True),
    ("轮滑对称蹬滑", "Velocity", ("Swizzle", "Swizzle-Backlash"), 50000, True),
    ("轮滑下坡", "RollerSlope", ("Flat", "Flat-Backlash"), 8000, True),
    ("轮滑倒地起身", "RollerStandUp", ("Flat",), 15000, True),
    ("轮滑原地旋转", "Spin", ("Flat",), 8000, True),
)
_GOALS = {
    "行走与倒地起身": "结合行走、静止保持与倒地恢复；先准备两类兼容教师。",
    "坐下与站起": "跟随坐站目标，练习降低身体、保持坐姿并重新站立。",
    "低头捡取": "在动作相位指令下低头接近地面，再回到站立姿态。",
    "左脚踢球": "将重心转移到右脚，用左脚完成踢球动作后恢复平衡。",
    "右脚踢球": "将重心转移到左脚，用右脚完成踢球动作后恢复平衡。",
    "前滚翻": "从准备姿态完成向前翻滚，再恢复身体支撑。",
    "行走老师": "根据速度和转向指令练习步行，为联合任务准备行走教师。",
    "倒地起身老师": "从倒地姿态练习恢复双脚站立，为联合任务准备恢复教师。",
    "轮滑行走": "使用轮滑脚部，根据推进、滑行与制动指令练习动作和姿态稳定。",
    "轮滑蹲下": "使用轮滑脚部，在降低重心和恢复站立时保持支撑。",
    "轮滑对称蹬滑": "使用轮滑脚部，练习双腿对称开合产生的蹬滑动作。",
    "轮滑下坡": "使用轮滑脚部，练习在斜坡滑行时保持姿态和支撑。",
    "轮滑倒地起身": "使用轮滑脚部，从倒地姿态重新建立站立支撑。",
    "轮滑原地旋转": "使用轮滑脚部，练习围绕身体竖直方向旋转并保持稳定。",
}


def build_action_recipes(defaults):
    """Return fresh catalog objects; existing three recipe objects stay untouched."""
    recipes = []
    for category, stem, variants, iterations, rollers in _FAMILIES:
        for variant in variants:
            suffix = "-Rollers" if category == "轮滑行走" else ""
            upstream_task = f"Mjlab-{stem}-{variant}-MicroDuck{suffix}"
            rid = "hd1910-" + upstream_task.removeprefix("Mjlab-").lower()
            terrain = "Slope" if stem == "RollerSlope" else "Rough" if "Rough" in variant else "Flat"
            terrain_label = {"Flat": "平地", "Rough": "起伏地形", "Slope": "斜坡"}[terrain]
            backlash = "Backlash" in variant
            launchable = stem != "VelStand"
            teachers = [] if launchable else [
                "hd1910-" + upstream_task.replace("VelStand", teacher).removeprefix("Mjlab-").lower()
                for teacher in ("Velocity", "StandUp")]
            goal = _GOALS[category]
            recipe = {
                "id": rid, "title": f"HD1910 {category} · {terrain_label}" + (" · 齿隙" if backlash else ""),
                "description": goal + "采用本项目 HD1910 M6 仿真基线，实际效果需训练后评估。",
                "upstream_task_id": upstream_task, "task_id": upstream_task + "-Studio-HD1910",
                "experiment_name": "microduck_hd1910_" + upstream_task.removeprefix("Mjlab-").removesuffix("-MicroDuck").lower().replace("-", "_"),
                "launchable": launchable, "prerequisite_note": "" if launchable else PREREQUISITE_NOTE,
                "teacher_recipe_ids": teachers,
                "defaults": dict(defaults, num_envs=4096, iterations=iterations),
                "hardware": "Linux + NVIDIA CUDA 显卡；HD1910 舵机 M6 模型；" + ("需要轮滑脚部硬件" if rollers else "普通脚部"),
                "validation": "尚未完成本机 GPU 短试跑；仿真配方适配不代表动作已学会，也未经过真机验证。",
                "catalog": {
                    "category": category, "tags": [terrain_label, "齿隙" if backlash else "无齿隙", "轮滑硬件" if rollers else "普通脚部"],
                    "preview_kind": "text", "source_label": "官方配方 · 本项目 HD1910 适配",
                    "source_url": SOURCE_URL, "source_revision": SOURCE_REVISION,
                    "official_source_url": OFFICIAL_SOURCE_URL, "engine_baseline_revision": ENGINE_BASELINE_REVISION,
                    "reference_engine_revision": REFERENCE_ENGINE_REVISION,
                    "terrain": terrain, "backlash": backlash, "requires_rollers": rollers,
                    "reference_envs": 4096, "reference_steps_per_iteration": 24,
                    "reference_iterations": iterations, "budget_note": BUDGET_NOTE,
                    "verification_state": "unverified", "verification_label": "待 GPU 验证",
                    "verification_evidence": [],
                    "instructions": [goal, "先完成本配方与相同种子、学习率、档案的短试跑。" if launchable else PREREQUISITE_NOTE,
                                     "检查点评估用于查看实际动作，短试跑只验证流程，不能证明收敛或真机性能。"],
                },
            }
            record = RECIPE_VERIFICATION.get(rid, {})
            # Only checked-in successful evidence may upgrade this public label.
            if launchable and record.get("verification_state") == "pipeline" and record.get("verification_evidence"):
                for key in ("verification_state", "verification_label", "verification_evidence"):
                    if key in record:
                        recipe["catalog"][key] = copy.deepcopy(record[key])
                recipe["validation"] = record.get("validation", "已完成本机 GPU 短试跑；仅验证流程，未证明收敛或真机性能。")
            recipes.append(recipe)
    return recipes
