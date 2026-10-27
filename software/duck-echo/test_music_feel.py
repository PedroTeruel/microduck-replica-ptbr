import array
import math
import unittest

import music_feel as music


class BeatTests(unittest.TestCase):
    def listen(self, bpm, duration=8, swing=False):
        listener = music.MusicFeel()
        period = 60 / bpm
        for frame in range(int(duration / .02)):
            at = frame * .02
            phase = at % period
            pulse = phase < .055 or (swing and period * 2/3 <= phase < period * 2/3 + .055)
            listener.observe(1400 if pulse else 100, at)
        return listener, duration - .02

    def test_measured_fast_and_slow_beats_produce_different_reactions(self):
        fast, now = self.listen(125)
        slow, _ = self.listen(75)
        self.assertAlmostEqual(fast.snapshot(now)['bpm'], 125, delta=6)
        self.assertAlmostEqual(slow.snapshot(now)['bpm'], 75, delta=4)
        self.assertEqual(fast.snapshot(now)['feel'], 'lively')
        self.assertEqual(slow.snapshot(now)['feel'], 'mellow')
        self.assertNotEqual(music.reaction_tag(fast.snapshot(now)), music.reaction_tag(slow.snapshot(now)))

    def test_swing_is_based_on_alternating_onsets(self):
        listener, now = self.listen(100, duration=10, swing=True)
        state = listener.snapshot(now)
        self.assertEqual(state['feel'], 'sway')
        self.assertAlmostEqual(state['bpm'], 100, delta=6)
        self.assertNotIn('genre', state)

    def test_constant_loudness_is_not_invented_as_a_beat(self):
        listener = music.MusicFeel()
        for n in range(400):
            listener.observe(1500, n * .02)
        self.assertEqual(listener.snapshot(7.98)['feel'], 'unknown')
        self.assertIsNone(listener.snapshot(7.98)['bpm'])

    def test_silence_and_stale_capture_expire_previous_context(self):
        listener, now = self.listen(125)
        for n in range(1, 101):
            listener.observe(0, now + n * .02)
        self.assertEqual(listener.snapshot(now + 2)['feel'], 'unknown')
        self.assertEqual(listener.snapshot(now + 4)['confidence'], 0)
        self.assertEqual(music.reaction_tag(listener.snapshot(now + 4)), 'inquire')

    def test_new_tempo_replaces_old_tempo_without_growing_memory(self):
        listener, _ = self.listen(75)
        for frame in range(600):
            at = 8 + frame * .02
            listener.observe(1400 if (at - 8) % .48 < .055 else 100, at)
        self.assertAlmostEqual(listener.snapshot(19.98)['bpm'], 125, delta=6)
        self.assertLessEqual(len(listener.onsets), 64)

    def test_pcm_uses_right_channel_and_handles_partial_frames(self):
        listener = music.MusicFeel()
        left_only = array.array('h', [x for _ in range(960) for x in (2000, 0)]).tobytes()
        listener.feed(left_only + b'\0', now=1)
        self.assertEqual(listener.snapshot(1)['level'], 0)

    def test_microphone_dc_bias_is_not_music_energy(self):
        listener = music.MusicFeel()
        biased = array.array('h', [x for _ in range(960) for x in (0, 911)]).tobytes()
        listener.feed(biased, now=1)
        self.assertEqual(listener.snapshot(1)['level'], 0)


class QuestionTests(unittest.TestCase):
    def test_questions_are_exact_and_allow_duck_address(self):
        for text in ('感觉 怎么样？', '鸭子，喜欢这种歌吗', '你喜欢这首歌吗？', '这首歌好听吗'):
            with self.subTest(text=text):
                self.assertTrue(music.is_music_question(text, .9))

    def test_negated_quoted_and_uncertain_speech_does_not_answer(self):
        for text in ('不要问感觉怎么样', '他说喜欢这种歌吗', '感觉怎么样然后坐下', ''):
            self.assertFalse(music.is_music_question(text, .99))
        for confidence in (.6, float('nan'), float('inf')):
            self.assertFalse(music.is_music_question('感觉怎么样', confidence))

    def test_reaction_tags_are_distinct_with_unknown_fallback(self):
        tags = [music.reaction_tag({'feel': feel, 'confidence': .9})
                for feel in ('lively', 'mellow', 'sway')]
        self.assertEqual(len(set(tags)), 3)
        self.assertEqual(music.reaction_tag({'feel': 'lively', 'confidence': .1}), 'inquire')


if __name__ == '__main__':
    unittest.main()
