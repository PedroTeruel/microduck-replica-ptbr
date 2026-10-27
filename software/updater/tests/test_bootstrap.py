import json
from pathlib import Path
import sys
import tempfile
import unittest
import os
import subprocess
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from bootstrap import profile, install_stable, verify_tree,copy_regular_tree,migrate_state
from engine_systemctl import allowed

class Bootstrap(unittest.TestCase):
    @unittest.skipUnless(os.name=='posix' and getattr(os,'geteuid',lambda:1)()==0,'requires isolated Linux root permission probe')
    def test_factory_state_and_logs_writable_by_actual_unprivileged_process(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);root.chmod(0o755);(root/'etc').mkdir()
            (root/'etc/passwd').write_text('radxa:x:65534:65534:fixture:/nonexistent:/bin/false\n')
            dropins=root/'etc/systemd/system/microduck-studio.service.d';dropins.mkdir(parents=True)
            (dropins/'10-image.conf').write_text('[Service]\nExecStart=\nExecStart=/usr/bin/python3 -I run.py --listen 0.0.0.0:8000\n')
            engine=root/'engine';engine.write_bytes(b'fixture');key=root/'key.pub';key.write_text('public')
            install_stable(root,engine,key)
            script='from pathlib import Path;import sys;sys.path.insert(0,'+repr(str(Path(__file__).resolve().parents[2]/'studio'))+');from studio.auth import Auth;from studio.log import Log;Auth(sys.argv[1]).set_password("fixture-password");log=Log(sys.argv[2],echo=False,background=False);log.info("startup");log.flush()'
            def demote():os.setgroups([]);os.setgid(65534);os.setuid(65534)
            subprocess.run([sys.executable,'-I','-c',script,str(root/'var/lib/microduck-studio'),str(root/'var/log/microduck-studio')],preexec_fn=demote,check=True)
            self.assertTrue((root/'var/lib/microduck-studio/password.json').is_file())
            self.assertTrue(list((root/'var/log/microduck-studio').glob('*.log')))
            override=(root/'etc/systemd/system/microduck-studio.service.d/90-software-update.conf').read_text()
            self.assertIn('--log-dir /var/log/microduck-studio',override)
            effective=[line for conf in sorted(dropins.glob('*.conf')) for line in conf.read_text().splitlines() if line.startswith('ExecStart=')][-1]
            self.assertIn('--state-dir /var/lib/microduck-studio --log-dir /var/log/microduck-studio',effective)

    @unittest.skipUnless(os.name=='posix','no-follow Linux migration')
    def test_legacy_symlink_and_swapped_entry_never_copy_root_secret(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'legacy';source.mkdir();secret=root/'root-secret';secret.write_text('root-secret')
            secret.chmod(0o600);(source/'link').symlink_to(secret)
            with self.assertRaises(ValueError):copy_regular_tree(source,root/'snapshot',os.getuid())
            self.assertFalse((root/'snapshot/link').exists())
            (source/'link').unlink();(source/'safe').write_text('safe')
            from unittest import mock
            original=os.open
            def raced(path,*args,**kwargs):
                if path=='safe' and kwargs.get('dir_fd') is not None:
                    (source/'safe').unlink();(source/'safe').symlink_to(secret)
                return original(path,*args,**kwargs)
            with mock.patch('bootstrap.os.open',side_effect=raced):
                with self.assertRaises((ValueError,OSError)):copy_regular_tree(source,root/'race-snapshot',os.getuid())
            self.assertFalse((root/'race-snapshot/safe').exists())
            self.assertEqual(secret.read_text(),'root-secret')

    @unittest.skipUnless(os.name=='posix','atomic Linux state migration')
    def test_regular_state_promoted_and_existing_nonempty_state_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'legacy';source.mkdir();(source/'password.json').write_text('legacy')
            backup=root/'private';backup.mkdir(mode=0o700);destination=root/'state';destination.mkdir()
            migrate_state(source,destination,backup,os.getuid(),os.getgid())
            self.assertEqual((destination/'password.json').read_text(),'legacy')
            (source/'password.json').write_text('changed')
            migrate_state(source,destination,backup,os.getuid(),os.getgid())
            self.assertEqual((destination/'password.json').read_text(),'legacy')
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
