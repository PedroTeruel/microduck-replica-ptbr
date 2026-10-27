"""A requested component image must fail rather than silently omit updates/voice."""
from test_apply_rootfs import ApplyTestBase


class ComponentHook(ApplyTestBase):
    def test_incomplete_component_inputs_fail_before_rootfs_changes(self):
        payload=self.fx.make_payload()
        root=self.fx.make_rootfs()
        before=(root/'etc/robot/feetech-ft5/robotd.toml').read_bytes()
        result=self.run_fail(root,payload,self.fx.make_studio(),self.fx.make_overlay(),
            env_extra={'SOFTWARE_UPDATE_PACKAGE':'/missing-package.tar'})
        self.assertIn('软件升级组件输入',result.stdout+result.stderr)
        self.assertEqual((root/'etc/robot/feetech-ft5/robotd.toml').read_bytes(),before)
