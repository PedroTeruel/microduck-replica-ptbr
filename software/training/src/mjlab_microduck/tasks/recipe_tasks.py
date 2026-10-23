"""Pure task/experiment contract for the Studio action recipe catalog.

The 14 roles and 35 upstream IDs follow kissqy/Microduck-kissqy's
microduck-hd1910/training-console/data/tasks.json at repository revision
525a215a19397767a073b782f57e97cf53683761. These are local HD1910 adaptations of
the official task factories, not reproductions of the reference checkpoints.
No simulation dependencies are imported so Studio can inspect this contract.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class RecipeTask:
    upstream_task: str
    task_id: str
    experiment_name: str
    role: str
    rough: bool
    backlash: bool

    @property
    def requires_teachers(self) -> bool:
        return self.role == "joint"


def _variants(role: str, stem: str, terrains=("Flat",), backlash=True, suffix=""):
    for terrain in terrains:
        for use_backlash in ((False, True) if backlash else (False,)):
            tag = "-Backlash" if use_backlash else ""
            upstream = f"Mjlab-{stem}-{terrain}{tag}-MicroDuck{suffix}"
            slug = upstream.removeprefix("Mjlab-").removesuffix("-MicroDuck").lower().replace("-", "_")
            yield RecipeTask(
                upstream_task=upstream,
                task_id=upstream + "-Studio-HD1910",
                experiment_name="microduck_hd1910_" + slug,
                role=role,
                rough=terrain == "Rough",
                backlash=use_backlash,
            )


RECIPE_TASKS = (
    *_variants("joint", "VelStand", ("Flat", "Rough")),
    *_variants("sitstand", "SitStand", ("Flat", "Rough")),
    *_variants("ground_pick", "GroundPick", ("Flat", "Rough")),
    *_variants("kick_left", "BallKickLeft"),
    *_variants("kick_right", "BallKick"),
    *_variants("roulade", "Roulade", backlash=False),
    *_variants("walk", "Velocity", ("Flat", "Rough")),
    *_variants("stand", "StandUp", ("Flat", "Rough")),
    *_variants("roller", "Velocity", suffix="-Rollers"),
    *_variants("crouch", "RollerCrouch"),
    *_variants("swizzle", "Velocity", ("Swizzle",)),
    *_variants("slope", "RollerSlope"),
    *_variants("roller_stand", "RollerStandUp", backlash=False),
    *_variants("spin", "Spin", backlash=False),
)
