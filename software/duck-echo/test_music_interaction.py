"""Streaming music questions with fake decoders; no microphone or Model load."""
import array
import importlib
import json
import threading
import time
import unittest
from types import SimpleNamespace

try:
    music = importlib.import_module('music_interaction')
except ModuleNotFoundError:
    music = SimpleNamespace()


def eventually(predicate, timeout=1):
    until = time.monotonic() + timeout
    while time.monotonic() < until:
        if predicate():
            return True
        time.sleep(.005)
    return predicate()


class Decoder:
    def __init__(self, *args):
        self.outputs = []
        self.reset_count = 0
        self.words = self.partial_words = False
        self.alignment_calls = 0
        self.aligned_text = None
        self.entered = self.release = None

    def SetWords(self, enabled):
        self.words = enabled

    def SetPartialWords(self, enabled):
        self.partial_words = enabled

    def AcceptWaveform(self, pcm):
        if self.entered:
            self.entered.set()
            self.release.wait(1)
        self.current = self.outputs.pop(0) if self.outputs else ('partial', '', .0)
        return self.current[0] == 'final'

    def PartialResult(self):
        if not self.partial_words:
            return json.dumps({'partial': self.current[1]})
        self.alignment_calls += 1
        return json.dumps({'partial': self.aligned_text if self.aligned_text is not None else self.current[1],
                           'partial_result': [{'conf': self.current[2]}]})

    def Result(self):
        return json.dumps({'text': self.current[1], 'result': [{'conf': self.current[2]}]})

    def Reset(self):
        self.reset_count += 1


class StreamingTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(hasattr(music, 'MusicInteraction'), 'streaming music recognizer missing')
        self.decoder = Decoder()
        self.created = []
        def factory(model, rate, grammar):
            self.created.append((model, rate, json.loads(grammar)))
            return self.decoder
        self.shared = SimpleNamespace(model=SimpleNamespace(vosk_model_find_word=lambda word: 0),
                                      recognizer_type=factory)
        self.now = [10.]
        self.replies = []
        self.feel = SimpleNamespace(snapshot=lambda: {'feel': 'lively', 'confidence': 1., 'age': 0})
        self.control = music.MusicInteraction(lambda: self.shared, self.feel,
            lambda tag, allowed: self.replies.append(tag) if allowed() else None,
            clock=lambda: self.now[0])
        self.addCleanup(self.control.close)
        self.control.set_enabled(True)

    def feed(self, kind, text, confidence, at=None):
        if at is not None:
            self.now[0] = at
        self.decoder.outputs.append((kind, text, confidence))
        self.control.feed(array.array('h', [100, 200] * 960).tobytes(), self.now[0])
        self.assertTrue(self.control.idle.wait(1))

    def test_stable_confident_full_partial_answers_without_music_silence_once(self):
        self.feed('partial', '感觉 怎么样', .9)
        self.assertEqual(self.replies, [])
        self.feed('partial', '感觉 怎么样', .9, 10.6)
        self.assertEqual(self.replies, ['chirp'])
        self.feed('final', '感觉 怎么样', .9, 11.)
        self.assertEqual(self.replies, ['chirp'])
        self.assertTrue(self.decoder.words)
        self.assertFalse(self.decoder.partial_words, 'alignment must return to cheap text-only partials')
        self.assertGreaterEqual(self.decoder.reset_count, 1)
        self.assertIs(self.created[0][0], self.shared.model)
        self.assertIn('[unk]', self.created[0][2])

    def test_final_requires_exact_question_and_word_confidence(self):
        for text, confidence in [('坐下', 1), ('不要 感觉 怎么样', 1), ('感觉 怎么样', .79),
                                 ('今天 感觉 怎么样 天气', 1)]:
            self.feed('final', text, confidence)
        self.assertEqual(self.replies, [])
        self.feed('final', '喜欢 这种 歌 吗', .9)
        self.assertEqual(self.replies, ['chirp'])

    def test_unknown_rhythm_uses_inquire_and_debounce_expires(self):
        self.feel.snapshot = lambda: {'feel': 'unknown', 'confidence': 0, 'age': 0}
        self.feed('final', '好听 吗', 1)
        self.assertEqual(self.replies, ['inquire'])
        self.feed('final', '好听 吗', 1, 15.)
        self.assertEqual(self.replies, ['inquire', 'inquire'])

    def test_disabled_inflight_question_never_quacks(self):
        self.decoder.entered, self.decoder.release = threading.Event(), threading.Event()
        self.decoder.outputs.append(('final', '感觉 怎么样', 1))
        self.control.feed(b'\x00' * 3840, 10.)
        self.assertTrue(self.decoder.entered.wait(1))
        self.control.set_enabled(False)
        self.decoder.release.set()
        self.assertTrue(self.control.idle.wait(1))
        self.assertEqual(self.replies, [])

    def test_drop_resets_decoder_and_queue_is_bounded(self):
        self.feed('partial', '感觉 怎么样', .9)
        self.decoder.entered, self.decoder.release = threading.Event(), threading.Event()
        self.control.feed(b'\x00' * 3840, 10.)
        self.assertTrue(self.decoder.entered.wait(1))
        for _ in range(100):
            self.control.feed(b'\x00' * 3840, 10.)
        self.assertLessEqual(len(self.control.queue), 32)
        self.decoder.release.set()
        self.assertTrue(self.control.idle.wait(1))
        self.assertEqual(self.replies, [])
        self.assertGreater(self.decoder.reset_count, 0)

    def test_model_unavailable_is_reported_without_crashing(self):
        self.control.close()
        self.control = music.MusicInteraction(lambda: None, self.feel, lambda *args: None)
        self.addCleanup(self.control.close)
        self.control.set_enabled(True)
        self.control.feed(b'\x00' * 3840, time.monotonic())
        self.assertTrue(self.control.idle.wait(1))
        self.assertIn('unavailable', self.control.error)

    def test_disable_resets_decoder_without_waiting_for_new_microphone_input(self):
        self.feed('partial', '感觉 怎么样', .9)
        before = self.decoder.reset_count
        self.control.set_enabled(False)
        self.assertTrue(eventually(lambda: self.decoder.reset_count > before))

    def test_question_uses_recent_confident_context_before_voice_changed_rhythm(self):
        self.feed('partial', '', 0, 8.)
        self.feel.snapshot = lambda: {'feel': 'mellow', 'confidence': 1., 'age': 0}
        self.feed('final', '感觉 怎么样', .9, 10.)
        self.assertEqual(self.replies, ['chirp'])

    def test_non_question_partials_never_request_word_alignment(self):
        for index in range(50):
            self.feed('partial', '不要 感觉 怎么样', .99, 10+index*.02)
        self.assertEqual(self.decoder.alignment_calls, 0)
        self.assertEqual(self.replies, [])

    def test_candidate_alignments_are_throttled_and_low_word_confidence_never_answers(self):
        for index in range(50):
            self.feed('partial', '感觉 怎么样', .79, 10+index*.02)
        self.assertLessEqual(self.decoder.alignment_calls, 10)
        self.assertEqual(self.replies, [])

    def test_aligned_partial_must_still_be_the_exact_complete_question(self):
        self.decoder.aligned_text = '感觉'
        self.feed('partial', '感觉 怎么样', .99, 10.)
        self.feed('partial', '感觉 怎么样', .99, 10.6)
        self.assertEqual(self.replies, [])


if __name__ == '__main__':
    unittest.main()
