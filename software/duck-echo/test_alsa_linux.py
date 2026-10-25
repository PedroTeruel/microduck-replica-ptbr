"""Exercise real Linux subprocesses with simulated ALSA tools, without hardware."""
import json
import os
from pathlib import Path
import tempfile
import time
import subprocess
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import duck_echo as echo


FAKE_ALSA = r'''#!/usr/bin/env python3
import array, json, math, os, signal, sys, time
from pathlib import Path
kind = Path(sys.argv[0]).name
if os.environ.get('FAKE_BUSY') == kind:
    print('audio open error: Device or resource busy', file=sys.stderr)
    sys.exit(1)
if kind == 'arecord':
    signal.signal(signal.SIGINT, lambda *_: sys.exit(0))
    seconds = int(sys.argv[sys.argv.index('-d') + 1])
    block = array.array('h', [x for i in range(480) for x in (0, int(2000*math.sin(i/7)))])
    for _ in range(seconds * 100):
        sys.stdout.buffer.write(block.tobytes())
        sys.stdout.buffer.flush()
        time.sleep(.01)
elif kind == 'aplay':
    data = sys.stdin.buffer.read()
    Path(os.environ['FAKE_PLAYBACK']).write_text(str(len(data)))
elif kind == 'amixer':
    state_path = Path(os.environ['FAKE_MIXER'])
    state = json.loads(state_path.read_text())
    if sys.argv[3] == 'controls':
        for index, name in enumerate(state):
            print("numid=%d,iface=MIXER,name='%s'" % (index+1, name))
        sys.exit(0)
    name = sys.argv[4].removeprefix('name=')
    if sys.argv[3] == 'cset':
        state[name] = sys.argv[5]
        state_path.write_text(json.dumps(state))
    print('  : values=' + state[name])
'''


@unittest.skipUnless(os.name == 'posix', 'Linux subprocess integration')
class LinuxAlsaTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        for name in ('arecord', 'aplay', 'amixer'):
            path = self.root / name
            path.write_text(FAKE_ALSA)
            path.chmod(0o755)
        self.playback = self.root / 'played'
        self.environment = patch.dict(os.environ, {
            'PATH': str(self.root) + os.pathsep + os.environ['PATH'],
            'FAKE_PLAYBACK': str(self.playback),
            'FAKE_MIXER': str(self.root / 'mixer.json'),
            'FAKE_BUSY': '',
        })
        self.environment.start()
        self.audio = echo.AlsaAudio('fake-mic', 'fake-speaker', maximum=1)

    def tearDown(self):
        self.audio.close()
        self.environment.stop()
        self.temp.cleanup()

    def test_real_capture_release_and_playback_subprocesses(self):
        self.audio.start()
        time.sleep(.4)
        result = self.audio.stop(play=True)
        self.assertTrue(self.audio.finish_playback())
        self.assertTrue(result['ok'])
        self.assertGreater(int(self.playback.read_text()), 48000)

    def test_natural_time_limit_caps_recording(self):
        self.audio.start()
        deadline = time.monotonic() + 4
        while not self.audio.expired() and time.monotonic() < deadline:
            time.sleep(.05)
        result = self.audio.stop(play=False)
        self.assertLessEqual(result['frames'], 48000)
        self.assertGreater(result['frames'], 40000)
        self.assertFalse(self.playback.exists())

    def test_disconnect_discards_clip_and_reaps_recorder(self):
        button = echo.HoldButton(self.audio)
        button.event(1)
        process = self.audio.capture[0]
        time.sleep(.3)
        button.cancel()
        self.assertIsNotNone(process.poll())
        self.assertFalse(self.playback.exists())

    def test_busy_capture_does_not_play(self):
        os.environ['FAKE_BUSY'] = 'arecord'
        self.audio.start()
        time.sleep(.1)
        with self.assertLogs('duck-echo', level='ERROR'):
            result = self.audio.stop(play=True)
        self.assertFalse(result['ok'])
        self.assertFalse(self.playback.exists())

    def test_busy_playback_reports_failure(self):
        os.environ['FAKE_BUSY'] = 'aplay'
        self.audio.start()
        time.sleep(.4)
        with self.assertLogs('duck-echo', level='ERROR'):
            self.audio.stop(play=True)
            self.assertFalse(self.audio.finish_playback())

    def test_mic_setup_and_restore_preserve_existing_settings(self):
        import install
        original = {name: 'off' for name in install.CAPTURE_SETTINGS}
        original['PGA Capture Volume'] = '12,13'
        (self.root / 'mixer.json').write_text(json.dumps(original))
        backup = self.root / 'backup.json'
        install.prepare_microphone('aic3104', backup)
        self.assertEqual(json.loads(backup.read_text())['values'], original)
        changed = json.loads((self.root / 'mixer.json').read_text())
        self.assertEqual(changed['Right PGA Mixer Mic3R Switch'], 'on')
        install.restore_microphone(backup)
        self.assertEqual(json.loads((self.root / 'mixer.json').read_text()), original)

    def test_native_3104_mic2_alias_without_line2_controls(self):
        import install
        original = {name.replace('Mic3', 'Mic2'): 'off'
                    for name in install.CAPTURE_SETTINGS if 'Line2' not in name}
        original['PGA Capture Volume'] = '10,10'
        (self.root / 'mixer.json').write_text(json.dumps(original))
        backup = self.root / 'backup.json'
        install.prepare_microphone('aic3104', backup)
        changed = json.loads((self.root / 'mixer.json').read_text())
        self.assertEqual(changed['Right PGA Mixer Mic2R Switch'], 'on')
        self.assertNotIn('Right PGA Mixer Line2R Switch', changed)
        install.restore_microphone(backup)
        self.assertEqual(json.loads((self.root / 'mixer.json').read_text()), original)

    def test_unknown_codec_is_rejected_before_mixer_changes(self):
        import install
        original = {'PGA Capture Volume': '10,10'}
        (self.root / 'mixer.json').write_text(json.dumps(original))
        backup = self.root / 'backup.json'
        with self.assertRaises(RuntimeError):
            install.prepare_microphone('aic3104', backup)
        self.assertEqual(json.loads((self.root / 'mixer.json').read_text()), original)
        self.assertFalse(backup.exists())

    def test_reinstall_after_restore_saves_a_fresh_baseline(self):
        import install
        original = {name: 'off' for name in install.CAPTURE_SETTINGS}
        original['PGA Capture Volume'] = '10,10'
        mixer = self.root / 'mixer.json'
        mixer.write_text(json.dumps(original))
        backup = self.root / 'backup.json'
        install.prepare_microphone('aic3104', backup)
        install.restore_microphone(backup)
        updated = dict(original, **{'PGA Capture Volume': '20,20'})
        mixer.write_text(json.dumps(updated))
        install.prepare_microphone('aic3104', backup)
        install.restore_microphone(backup)
        self.assertEqual(json.loads(mixer.read_text()), updated)

    def test_upgrade_preserves_active_installation_backup(self):
        import install
        original = {name: 'off' for name in install.CAPTURE_SETTINGS}
        original['PGA Capture Volume'] = '10,10'
        mixer = self.root / 'mixer.json'
        mixer.write_text(json.dumps(original))
        backup = self.root / 'backup.json'
        install.prepare_microphone('aic3104', backup)
        install.prepare_microphone('aic3104', backup)
        self.assertEqual(json.loads(backup.read_text())['values'], original)
        install.restore_microphone(backup)
        self.assertEqual(json.loads(mixer.read_text()), original)

    def test_failed_upgrade_restores_attempt_state_files_and_prior_service(self):
        import install
        original = {name: 'off' for name in install.CAPTURE_SETTINGS}
        original['PGA Capture Volume'] = '20,20'
        mixer = self.root / 'mixer.json'
        mixer.write_text(json.dumps(original))
        state, destination = self.root / 'state', self.root / 'installed'
        state.mkdir()
        destination.mkdir()
        baseline = {'card': 'aic3104', 'values': dict(original, **{'PGA Capture Volume': '12,13'})}
        backup = state / 'mixer-before.json'
        backup.write_text(json.dumps(baseline))
        program = destination / 'duck_echo.py'
        program.write_text('# prior program\n')
        unit = self.root / 'unit.service'
        unit.write_text('# prior unit\n')
        calls = []
        real_run = install.run

        def run(arguments, check=True):
            if arguments[0] == 'amixer':
                return real_run(arguments, check)
            calls.append(arguments)
            if arguments[:2] == ['systemctl', 'enable'] and '--now' in arguments:
                raise subprocess.CalledProcessError(1, arguments, stderr='injected enable failure')
            return SimpleNamespace(returncode=0, stdout='stable', stderr='')

        with patch.multiple(install, STATE=state, DESTINATION=destination, UNIT=unit,
                            DEFAULTS=self.root / 'defaults'), patch.object(install, 'run', run):
            with self.assertRaises(subprocess.CalledProcessError):
                install.main(['install'])
        self.assertEqual(json.loads(mixer.read_text()), original)
        self.assertEqual(json.loads(backup.read_text()), baseline)
        self.assertEqual(program.read_text(), '# prior program\n')
        self.assertEqual(unit.read_text(), '# prior unit\n')
        self.assertIn(['systemctl', 'start', 'duck-echo.service'], calls)


if __name__ == '__main__':
    unittest.main()
