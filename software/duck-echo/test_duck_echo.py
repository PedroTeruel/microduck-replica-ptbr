import array
import math
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import duck_echo as echo


def pcm(values):
    return array.array('h', values).tobytes()


class AudioTests(unittest.TestCase):
    def test_selects_onboard_right_mic_and_duplicates_to_speakers(self):
        data, level = echo.prepare_audio(pcm([100, 2000, -100, -2000]), 1)
        self.assertEqual(array.array('h', data).tolist(), [2000, 2000, -2000, -2000])
        self.assertAlmostEqual(level['rms'], 2000)

    def test_silence_has_finite_level(self):
        data, level = echo.prepare_audio(b'\x00' * 40, 1)
        self.assertEqual(len(data), 40)
        self.assertEqual(level['peak'], 0)
        self.assertTrue(math.isfinite(level['dbfs']))

    def test_partial_pcm_frame_is_discarded(self):
        data, level = echo.prepare_audio(pcm([1, 200]) + b'\x00', 1)
        self.assertEqual(data, pcm([200, 200]))
        self.assertEqual(level['frames'], 1)

    def test_rejects_invalid_channel(self):
        with self.assertRaises(ValueError):
            echo.prepare_audio(b'', 2)


class FakeAudio:
    def __init__(self):
        self.calls = []
        self.finished = False

    def start(self):
        self.calls.append('start')
        self.finished = False

    def stop(self, play):
        self.calls.append(('stop', play))

    def expired(self):
        return self.finished


class ButtonTests(unittest.TestCase):
    def setUp(self):
        self.audio = FakeAudio()
        self.button = echo.HoldButton(self.audio)

    def test_holds_record_and_release_repeats(self):
        self.button.event(1, now=1)
        self.button.event(2, now=1.2)
        self.button.event(0, now=2)
        self.assertEqual(self.audio.calls, ['start', ('stop', True)])

    def test_short_accidental_click_is_discarded(self):
        self.button.event(1, now=1)
        self.button.event(0, now=1.1)
        self.assertEqual(self.audio.calls, ['start', ('stop', False)])

    def test_disconnect_cancels_without_playback(self):
        self.button.event(1, now=1)
        self.button.cancel()
        self.assertEqual(self.audio.calls, ['start', ('stop', False)])

    def test_started_held_requires_release_before_recording(self):
        self.button = echo.HoldButton(self.audio, initially_down=True)
        self.button.event(1, now=1)
        self.button.event(0, now=2)
        self.assertEqual(self.audio.calls, [])
        self.button.event(1, now=3)
        self.assertEqual(self.audio.calls, ['start'])

    def test_time_limit_plays_only_once_and_requires_new_press(self):
        self.button.event(1, now=1)
        self.audio.finished = True
        self.button.tick(now=11)
        self.button.event(1, now=11.1)
        self.button.event(0, now=12)
        self.assertEqual(self.audio.calls, ['start', ('stop', True)])
        self.button.event(1, now=13)
        self.assertEqual(self.audio.calls[-1], 'start')

    def test_repeated_press_does_not_restart_capture(self):
        self.button.event(1, now=1)
        self.button.event(1, now=2)
        self.assertEqual(self.audio.calls, ['start'])

    def test_voice_time_limit_cancels_instead_of_executing_while_held(self):
        self.button = echo.HoldButton(self.audio, repeat_on_limit=False)
        self.button.event(1, now=1)
        self.audio.finished = True
        self.button.tick(now=11)
        self.button.event(0, now=12)
        self.assertEqual(self.audio.calls, ['start', ('stop', False)])

    def test_cancel_after_release_invalidates_pending_recognition_for_input_overflow(self):
        self.audio.cancel_processing = lambda: self.audio.calls.append('cancel_pending')
        self.assertFalse(self.button.recording)
        self.button.cancel()  # SYN_DROPPED also takes this path after release.
        self.assertEqual(self.audio.calls, ['cancel_pending'])


class InputTests(unittest.TestCase):
    def test_event_layout_matches_64_bit_linux(self):
        self.assertEqual(echo.INPUT_EVENT.size, 24)
        raw = echo.INPUT_EVENT.pack(10, 500, 1, 318, 1)
        self.assertEqual(echo.decode_events(raw), [(1, 318, 1)])

    def test_incomplete_event_is_rejected(self):
        with self.assertRaises(ValueError):
            echo.decode_events(b'123')


class PlaybackTests(unittest.TestCase):
    def player(self, code):
        return SimpleNamespace(
            returncode=code, communicate=lambda **kw: None,
            poll=lambda: code,
        )

    def test_device_busy_is_reported_as_failed_playback(self):
        audio = echo.AlsaAudio('capture', 'playback')
        with patch.object(echo.subprocess, 'Popen', return_value=self.player(1)):
            with self.assertLogs('duck-echo', level='ERROR'):
                audio.play(pcm([1000, 1000]))
                self.assertFalse(audio.finish_playback())

    def test_success_requires_player_exit_zero(self):
        audio = echo.AlsaAudio('capture', 'playback')
        with patch.object(echo.subprocess, 'Popen', return_value=self.player(0)):
            audio.play(pcm([1000, 1000]))
            self.assertTrue(audio.finish_playback())


if __name__ == '__main__':
    unittest.main()
