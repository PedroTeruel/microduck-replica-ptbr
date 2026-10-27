"""Standalone voice must agree with Studio's public persistent guard."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
import threading
from types import SimpleNamespace
from unittest import mock
import voice_commands as voice


class NativeGuard(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.path=self.root/'var/lib/microduck-helper/native-update/journal.json'
        self.path.parent.mkdir(parents=True)
        self.record={'schema':'microduck-native-update/1','transaction_id':'a'*32,
                     'active':False,'phase':'completed','running_verified':True}

    def write(self,value): self.path.write_text(json.dumps(value),encoding='utf-8')

    def test_contract_matches_public_helper_for_journal_and_every_exclusion(self):
        source=Path(__file__).resolve().parents[1]/'studio/studio/helper.py'
        spec=importlib.util.spec_from_file_location('guard_contract_helper',source)
        helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(helper)
        self.assertTrue(hasattr(voice,'NativeUpdateGuard'),'standalone persistent native guard missing')
        guard=voice.NativeUpdateGuard(self.root)
        cases=[self.record,{**self.record,'active':True},{**self.record,'restore_pending':True},
               {**self.record,'cleanup_pending':True},{**self.record,'active':1},
               {**self.record,'phase':'future'},{**self.record,'reason':[]},
               {**self.record,'transaction_id':'wrong'},{**self.record,'schema':'future'},
               {**self.record,'restore_pending':1},{**self.record,'cleanup_pending':None}]
        for record in cases:
            self.write(record)
            self.assertEqual(guard.active(),helper.native_update_state(root=str(self.root))['active'],record)
        self.write(self.record)
        for path in helper.NATIVE_UPDATE_EXCLUSIONS:
            exclusion=self.root/path.lstrip('/');exclusion.parent.mkdir(parents=True,exist_ok=True)
            exclusion.touch()
            self.assertTrue(guard.active(),path)
            self.path.unlink()
            self.assertTrue(guard.active(),path)
            self.write(self.record);exclusion.unlink()
            self.assertFalse(guard.active(),path)

    def test_bounded_malformed_unsafe_and_cached_reads(self):
        self.assertTrue(hasattr(voice,'NativeUpdateGuard'),'standalone persistent native guard missing')
        guard=voice.NativeUpdateGuard(self.root)
        self.assertFalse(guard.active())
        for raw in ('{', ' '*65537, '[[]]', '{"schema":"future"}'):
            self.path.write_text(raw,encoding='utf-8');self.assertTrue(guard.active())
        self.write(self.record)
        with mock.patch.object(voice.json,'loads',wraps=json.loads) as parse:
            for _ in range(30):self.assertFalse(guard.active())
            self.assertEqual(parse.call_count,1,'reparsed journal for every audio frame')
        other=self.path.with_name('other');self.write({**self.record,'active':True})
        self.path.replace(other);self.write(self.record)
        self.assertFalse(guard.active(),'cache missed inode replacement')
        if os.name=='posix':
            self.path.unlink();self.path.symlink_to(other)
            self.assertTrue(guard.active(),'symlink journal was followed')

    def test_updates_allowed_and_lease_use_persistent_guard_after_boot(self):
        self.assertTrue(hasattr(voice,'NativeUpdateGuard'),'standalone persistent native guard missing')
        self.write({**self.record,'cleanup_pending':True})
        with mock.patch.object(voice,'NATIVE_GUARD',voice.NativeUpdateGuard(self.root)):
            self.assertFalse(voice.updates_allowed())
            with self.assertRaises(voice.UpdateLocked):
                with voice.motion_lease(self.root/'no-software-marker'):self.fail('native guard bypassed')

    def test_music_inflight_reply_rechecks_native_guard(self):
        import music_interaction
        self.assertIn('guard',__import__('inspect').signature(music_interaction.MusicInteraction).parameters)
        self.write(self.record)
        guard=voice.NativeUpdateGuard(self.root)
        control=music_interaction.MusicInteraction(lambda:None,SimpleNamespace(snapshot=lambda:{}),
            lambda *args:None,guard=lambda:not guard.active())
        self.addCleanup(control.close)
        control.set_enabled(True);generation=control.generation
        self.assertTrue(control._valid(generation))
        self.write({**self.record,'active':True})
        self.assertFalse(control._valid(generation))
        control.set_enabled(True)
        self.assertFalse(control.enabled)
        control.set_enabled(False)
        self.assertFalse(control.enabled)

    def test_inflight_recognized_phrase_and_latched_r3_cannot_dispatch_after_journal(self):
        from speech_control import VoiceControl
        from test_speech_control import FakeExecutor,FakeRecognizer
        from continuous_audio import ContinuousAudio
        from test_continuous_audio import FakeAudio,CaptureProcess
        self.write(self.record)
        entered,release=threading.Event(),threading.Event()
        executor=FakeExecutor();echoed=[]
        with mock.patch.object(voice,'NATIVE_GUARD',voice.NativeUpdateGuard(self.root)):
            control=VoiceControl(lambda:FakeRecognizer(entered=entered,release=release),executor,echoed.append)
            spawn=mock.patch('continuous_audio.subprocess.Popen',side_effect=lambda *a,**k:CaptureProcess())
            spawn.start();self.addCleanup(spawn.stop)
            audio=ContinuousAudio(FakeAudio(),capture_device='fixture')
            self.addCleanup(control.close);self.addCleanup(audio.close)
            self.assertTrue(control.ready.wait(1))
            control.submit(b'inflight');self.assertTrue(entered.wait(1))
            audio.start();self.assertTrue(audio.active)
            self.write({**self.record,'cleanup_pending':True})
            release.set();self.assertTrue(control.idle.wait(1))
            self.assertEqual(executor.commands,[]);self.assertEqual(echoed,[])
            audio.feed(b'\0'*3840)
            self.assertFalse(audio.active)
            audio.start();self.assertFalse(audio.active)


if __name__=='__main__':unittest.main()
