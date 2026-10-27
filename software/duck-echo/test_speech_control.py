import threading
import unittest

import speech_control as speech


class FakeRecognizer:
    def __init__(self, text='坐下', confidence=1.0, entered=None, release=None):
        self.text, self.confidence = text, confidence
        self.entered, self.release = entered, release

    def recognize(self, pcm, rate=48000):
        if self.entered:
            self.entered.set()
        if self.release:
            self.release.wait(2)
        return {'text': self.text, 'confidence': self.confidence}


class FakeExecutor:
    def __init__(self):
        self.commands = []

    def execute(self, command, allowed):
        if allowed():
            self.commands.append(command)
            return {'accepted': True}
        return {'accepted': False}


class SpeechTests(unittest.TestCase):
    def test_update_marker_invalidates_inflight_and_queued_recognition(self):
        entered,release=threading.Event(),threading.Event();blocked=[False]
        control=self.make(FakeRecognizer(entered=entered,release=release),guard=lambda:not blocked[0])
        control.submit(b'inflight');self.assertTrue(entered.wait(1));control.submit(b'queued')
        blocked[0]=True;release.set();self.assertTrue(control.idle.wait(1))
        self.assertEqual(self.executor.commands,[]);self.assertEqual(self.echoed,[])
        self.assertEqual(len(control.queue),0)

    def make(self, recognizer=None, **kwargs):
        self.echoed = []
        self.executor = FakeExecutor()
        self.control = speech.VoiceControl(
            lambda: recognizer or FakeRecognizer(), self.executor, self.echoed.append, **kwargs)
        self.addCleanup(self.control.close)
        self.assertTrue(self.control.ready.wait(1))
        return self.control

    def test_recognized_command_executes_instead_of_echo(self):
        control = self.make()
        control.submit(b'pcm')
        self.assertTrue(control.idle.wait(1))
        self.assertEqual(self.executor.commands, ['sit'])
        self.assertEqual(self.echoed, [])

    def test_ready_exposes_existing_recognizer_for_shared_model_without_new_factory(self):
        recognizer = FakeRecognizer()
        control = self.make(recognizer)
        self.assertIs(getattr(control, 'recognizer', None), recognizer)

    def test_disabled_ordinary_asr_keeps_echo_without_using_shared_recognizer(self):
        recognizer = FakeRecognizer()
        recognizer.recognize = lambda data: self.fail('voice-mode off ran posture ASR')
        import inspect
        self.assertIn('recognize_speech', inspect.signature(speech.VoiceControl).parameters)
        control = self.make(recognizer, recognize_speech=False)
        control.submit(b'pcm')
        self.assertTrue(control.idle.wait(1))
        self.assertEqual(self.echoed, [b'pcm'])

    def test_ordinary_low_confidence_and_negative_speech_keep_echo(self):
        for text, score in [('你好', 1), ('坐下', .4), ('不要坐下', 1), ('复读坐下', 1)]:
            control = self.make(FakeRecognizer(text, score))
            control.submit(b'pcm')
            self.assertTrue(control.idle.wait(1))
            self.assertEqual(self.executor.commands, [])
            self.assertEqual(self.echoed, [b'pcm'])
            control.close()

    def test_new_press_cancels_result_still_being_recognized(self):
        entered, release = threading.Event(), threading.Event()
        control = self.make(FakeRecognizer(entered=entered, release=release))
        control.submit(b'pcm')
        self.assertTrue(entered.wait(1))
        control.cancel()
        release.set()
        self.assertTrue(control.idle.wait(1))
        self.assertEqual(self.executor.commands, [])
        self.assertEqual(self.echoed, [])

    def test_expired_recognition_never_executes(self):
        entered, release = threading.Event(), threading.Event()
        now = [0.0]
        control = self.make(FakeRecognizer(entered=entered, release=release), clock=lambda: now[0])
        control.submit(b'pcm')
        self.assertTrue(entered.wait(1))
        now[0] = 7
        release.set()
        self.assertTrue(control.idle.wait(1))
        self.assertEqual(self.executor.commands, [])

    def test_model_failure_preserves_echo(self):
        def failure():
            raise RuntimeError('missing model')
        self.echoed = []
        self.executor = FakeExecutor()
        with self.assertLogs('duck-echo', level='ERROR'):
            control = speech.VoiceControl(failure, self.executor, self.echoed.append)
            self.addCleanup(control.close)
            self.assertTrue(control.ready.wait(1))
        control.submit(b'pcm')
        self.assertTrue(control.idle.wait(1))
        self.assertEqual(self.echoed, [b'pcm'])

    def test_shadow_mode_recognizes_but_does_not_move(self):
        control = self.make(execute_commands=False)
        control.submit(b'pcm')
        self.assertTrue(control.idle.wait(1))
        self.assertEqual(self.executor.commands, [])
        self.assertEqual(self.echoed, [b'pcm'])


if __name__ == '__main__':
    unittest.main()
