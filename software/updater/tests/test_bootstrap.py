import json
from pathlib import Path
import sys
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from bootstrap import profile, install_stable, verify_tree
from engine_systemctl import allowed

class Bootstrap(unittest.TestCase):
    def test_engine_service_boundary_disables_factory_host_and_unrelated_units(self):
        self.assertTrue(allowed('systemctl',['restart','microduck-studio','duck-echo']))
        for program,args,offline in [('systemd-run',['--','systemctl','restart','btd'],False),
                ('systemctl',['restart','robotd'],False),('systemctl',['restart','updaterd'],False),
                ('systemctl',['restart','duck-echo'],True),('systemctl',['show','robotd'],True)]:
            self.assertFalse(allowed(program,args,offline))
    def test_factory_profile_isolated_and_final_profile_uses_fixed_roots(self):
        text=profile('/tmp/image')
        self.assertIn('"/tmp/image/opt/microduck/software"',text)
        self.assertIn('auto_apply = "off"',text)
        self.assertNotIn('check_interval',text)
        self.assertIn('studio/run.py',text)
        self.assertNotIn('studio/server.py',text)
        self.assertIn('action = "none"',text)
        self.assertIn('units = ["microduck-studio", "duck-echo"]',profile('/'))

    def test_stable_units_matched_helper_and_external_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); engine=root/'source-engine'; engine.write_bytes(b'ELF fixture')
            key=root/'public.pub'; key.write_text('public')
            install_stable(root,engine,key)
            studio=(root/'etc/systemd/system/microduck-studio.service').read_text()
            voice=(root/'etc/systemd/system/duck-echo.service').read_text()
            self.assertIn('WorkingDirectory=/opt/microduck/software/current/studio',studio)
            self.assertIn('--state-dir /var/lib/microduck-studio',studio)
            self.assertIn('--speech-deps /opt/microduck/resources/asr-deps',voice)
            self.assertIn('ECHO_VOICE_MODE=actions',voice)
            self.assertIn('microduck-voice-prepare.service',voice)
            self.assertIn('current/studio/deploy/microduck-helper',(root/'usr/local/sbin/microduck-helper').read_text())
            self.assertTrue((root/'usr/local/lib/microduck-updater/updaterd').is_file())
            self.assertNotIn('robotd', (root/'etc/systemd/system/microduck-updater-engine.service').read_text().split('ExecStart=')[1])
            settings=root/'etc/default/duck-echo'; settings.parent.mkdir(parents=True,exist_ok=True); settings.write_text('ECHO_PITCH=1.5\n')
            install_stable(root,engine,key)
            self.assertEqual(settings.read_text(),'ECHO_PITCH=1.5\n')

    def test_offline_hash_verification_refuses_changed_tree(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); (root/'studio').mkdir(); (root/'studio/run.py').write_text('runtime')
            import hashlib
            (root/'suite-version.json').write_text(json.dumps({'version':'2026.10.27','files':{'studio/run.py':hashlib.sha256(b'runtime').hexdigest()}}))
            verify_tree(root)
            (root/'studio/run.py').write_text('tamper')
            with self.assertRaises(ValueError): verify_tree(root)

if __name__=='__main__': unittest.main()
