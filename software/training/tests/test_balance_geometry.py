"""Exercise the real sole mesh and whole-robot CoM on CPU MuJoCo."""
from types import SimpleNamespace
import re

import mujoco
import numpy as np
import pytest
import torch

from mjlab_microduck.robot.microduck_constants import MICRODUCK_ALLCOLLISIONS_XML, HOME_FRAME
from mjlab_microduck.tasks import mdp


def make_cpu_geometry_env(ankle_delta=0., side="left"):
    model = mujoco.MjModel.from_xml_path(str(MICRODUCK_ALLCOLLISIONS_XML))
    data = mujoco.MjData(model)
    data.qpos[:7] = [0, 0, .12, 1, 0, 0, 0]
    for i in range(1, model.njnt):
        for pattern, value in HOME_FRAME.joint_pos.items():
            if re.fullmatch(pattern, model.joint(i).name):
                data.qpos[model.jnt_qposadr[i]] = value
                break
    data.qpos[model.jnt_qposadr[model.joint(f"{side}_ankle").id]] += ankle_delta
    mujoco.mj_forward(model, data)
    tensor = lambda x: torch.tensor(np.asarray(x).copy(), dtype=torch.float32).unsqueeze(0)
    root = model.body("trunk_base").id
    geom_quat = np.empty((model.ngeom, 4))
    site_quat = np.empty((model.nsite, 4))
    for i in range(model.ngeom):
        mujoco.mju_mat2Quat(geom_quat[i], data.geom_xmat[i])
    for i in range(model.nsite):
        mujoco.mju_mat2Quat(site_quat[i], data.site_xmat[i])
    d = SimpleNamespace(joint_pos=tensor(data.qpos[7:]), joint_vel=tensor(data.qvel[6:]),
                        root_link_pos_w=tensor(data.xpos[root]), root_link_quat_w=tensor(data.xquat[root]),
                        root_link_lin_vel_w=torch.zeros(1, 3), root_link_ang_vel_w=torch.zeros(1, 3),
                        geom_pos_w=tensor(data.geom_xpos), geom_quat_w=tensor(geom_quat),
                        site_pos_w=tensor(data.site_xpos), site_quat_w=tensor(site_quat),
                        site_lin_vel_w=torch.zeros(1, model.nsite, 3),
                        projected_gravity_b=torch.tensor([[0., 0., -1.]]))
    robot = SimpleNamespace(data=d, indexing=SimpleNamespace(
        geom_ids=torch.arange(model.ngeom), site_ids=torch.arange(model.nsite), root_body_id=root),
        find_geoms=lambda name: ([model.geom(name).id], [name]),
        find_sites=lambda name: ([model.site(name).id], [name]))
    foot = SimpleNamespace(data=SimpleNamespace(found=torch.ones(1, 2),
                          force=torch.tensor([[[0., 0., 3.6], [0., 0., 3.6]]])))
    other = SimpleNamespace(data=SimpleNamespace(found=torch.zeros(1, 1), force=torch.zeros(1, 1, 3)))
    class Scene(dict):
        pass
    scene = Scene(robot=robot)
    scene.sensors = {"feet_ground_contact": foot, "nonfoot_ground_contact": other}
    scene.terrain = SimpleNamespace(env_origins=torch.zeros(1, 3))
    env = SimpleNamespace(num_envs=1, device="cpu", episode_length_buf=torch.ones(1), scene=scene,
                          sim=SimpleNamespace(mj_model=model, data=SimpleNamespace(subtree_com=tensor(data.subtree_com))))
    cmd = mdp.BalanceCommandCfg(resampling_time_range=(1e9, 1e9), support_side=side).build(env)
    env.command_manager = SimpleNamespace(get_term=lambda name: cmd)
    return env, model, data


@pytest.mark.parametrize("side", ["left", "right"])
@pytest.mark.parametrize("ankle_delta", [0., .4])
def test_mesh_clearance_matches_mujoco_after_foot_rotation(side, ankle_delta):
    env, model, data = make_cpu_geometry_env(ankle_delta, side)
    m = mdp.balance_measurements(env)
    gid = model.geom(f"{side}_foot_collision").id
    mesh = model.geom_dataid[gid]
    start, n = model.mesh_vertadr[mesh], model.mesh_vertnum[mesh]
    vertices = model.mesh_vert[start:start+n] @ data.geom_xmat[gid].reshape(3, 3).T + data.geom_xpos[gid]
    assert m["support_clearance_m"].item() == pytest.approx(vertices[:, 2].min(), abs=1e-6)
    assert m["finite"].item()
    if ankle_delta:
        site_z = data.site_xpos[model.site(f"{side}_foot").id, 2]
        assert abs(site_z - vertices[:, 2].min()) > .001
    # Whole-robot CoM starts BETWEEN the feet, outside either single support.
    if not ankle_delta:
        assert m["com_margin_m"].item() < -.015
        assert model.body_mass.sum() == pytest.approx(.73724318)


def test_nonfoot_contact_and_force_nan_are_visible_and_safe():
    env, _, _ = make_cpu_geometry_env()
    env.scene.sensors["nonfoot_ground_contact"].data.found[:] = 1
    assert mdp.balance_nonfoot_contact(env).item()
    m = mdp.balance_measurements(env)
    assert m["nonfoot_contact"].item()
    assert mdp.balance_height_reward(env).item() == 0
    env.scene.sensors["nonfoot_ground_contact"].data.force[:] = float("nan")
    assert not mdp.balance_measurements(env)["finite"].item()
    assert torch.isfinite(mdp.balance_hold_reward(env)).all()
