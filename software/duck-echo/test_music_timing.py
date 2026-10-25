"""Sample timing and numeric microphone regressions; no recorded PCM fixtures."""
import array
import math
import random
import sys
import unittest

from music_feel import MusicFeel, RATE


# Actual microphone AC RMS, 2026-10-26, one value per 20 ms; no PCM saved.
MICROPHONE_RMS = (
    702.2, 881.0, 1038.9, 741.5, 752.3, 663.3, 547.3, 491.4, 485.4, 627.6,
    838.2, 611.1, 731.9, 675.1, 813.0, 738.5, 872.6, 857.7, 727.1, 754.6,
    1034.8, 1154.8, 853.5, 900.1, 764.1, 568.4, 500.7, 453.8, 545.3, 712.7,
    614.7, 498.4, 387.6, 443.3, 625.5, 499.1, 370.0, 416.8, 547.0, 469.6,
    425.6, 457.3, 559.3, 777.9, 736.7, 1233.2, 1052.4, 828.7, 723.9, 680.9,
    769.2, 773.3, 677.9, 797.3, 649.4, 701.6, 741.4, 803.7, 522.9, 561.2,
    840.3, 892.2, 793.2, 674.5, 733.5, 452.3, 586.0, 832.6, 717.1, 661.3,
    631.9, 577.4, 649.9, 953.3, 958.4, 981.1, 1221.5, 894.1, 1156.6, 757.1,
    949.2, 1257.5, 1138.4, 960.8, 1085.1, 1037.4, 1192.8, 1090.5, 1087.8, 1156.2,
    1398.6, 1004.1, 1019.1, 1326.8, 1018.3, 1009.5, 992.8, 717.7, 678.9, 585.8,
    492.1, 608.2, 573.7, 543.6, 592.9, 543.3, 503.3, 528.9, 561.8, 570.0,
    611.4, 698.6, 729.4, 740.3, 993.1, 1105.2, 952.4, 666.9, 410.2, 619.9,
    381.9, 426.8, 457.2, 650.3, 1145.4, 1474.0, 1401.4, 985.1, 1724.7, 1518.8,
    1047.9, 912.4, 687.0, 469.3, 387.4, 350.4, 315.1, 410.7, 313.1, 619.8,
    777.0, 734.4, 711.1, 711.9, 644.0, 529.0, 507.6, 455.2, 360.6, 743.6,
    411.2, 320.5, 285.8, 287.8, 1140.1, 1284.5, 1117.2, 662.2, 599.8, 555.1,
    504.1, 462.6, 510.0, 301.7, 276.9, 274.6, 330.8, 851.8, 824.5, 702.5,
    697.0, 635.6, 589.0, 575.0, 328.7, 351.4, 869.2, 368.2, 319.0, 265.3,
    531.5, 671.7, 743.5, 786.0, 946.0, 1186.5, 1053.0, 665.1, 468.0, 649.8,
    569.3, 437.5, 394.3, 423.5, 427.2, 417.0, 307.5, 279.4, 281.2, 256.9,
    510.7, 972.1, 1082.1, 785.6, 1017.6, 1273.8, 1202.1, 988.9, 839.4, 820.5,
    681.4, 703.3, 747.7, 701.1, 976.1, 1195.5, 1016.0, 599.1, 471.1, 492.8,
    608.5, 398.4, 391.6, 387.7, 325.3, 370.9, 399.3, 325.3, 267.8, 262.7,
    314.5, 558.3, 436.3, 584.3, 498.0, 505.6, 439.2, 316.8, 285.0, 262.1,
    256.8, 458.0, 527.6, 580.8, 1275.0, 1380.6, 1134.1, 847.1, 886.7, 1060.1,
    1041.3, 742.0, 649.9, 607.7, 373.6, 369.0, 402.3, 315.9, 276.8, 311.0,
    305.6, 316.1, 577.6, 733.9, 766.9, 473.5, 326.7, 321.3, 294.1, 342.2,
    260.0, 323.2, 247.4, 261.9, 1221.6, 1216.4, 1059.1, 721.6, 572.0, 725.5,
    762.6, 696.4, 662.8, 635.5, 518.9, 478.3, 373.6, 363.7, 423.3, 388.2,
    523.0, 492.3, 586.4, 713.8, 678.7, 406.7, 430.0, 328.1, 274.7, 325.9,
    355.1, 358.4, 587.3, 1054.8, 1132.6, 1123.5, 1040.6, 615.4, 495.4, 431.7,
    414.8, 485.0, 449.4, 506.4, 485.5, 581.3, 973.1, 593.7, 515.8, 589.9,
    868.1, 1035.9, 1182.0, 1242.0, 847.3, 835.3, 698.1, 704.0, 693.3, 622.5,
    740.5, 604.7, 363.7, 350.5, 1050.8, 1327.6, 1072.4, 629.8, 488.1, 495.1,
    423.3, 390.8, 380.7, 290.6, 294.4, 284.6, 325.5, 329.9, 273.5, 342.3,
    346.5, 367.0, 443.7, 383.6, 408.4, 374.4, 318.5, 308.3, 299.7, 349.6,
    437.9, 442.0, 284.4, 256.2, 1116.8, 1419.9, 1124.5, 701.1, 527.1, 513.3,
    472.4, 495.2, 569.3, 530.5, 526.2, 555.4, 569.0, 651.1, 447.2, 349.5,
    503.7, 612.1, 403.4, 368.1, 407.9, 435.2, 442.7, 462.7, 304.3, 322.3,
    249.2, 245.4, 277.2, 279.5, 1161.9, 1335.3, 1094.6, 742.5, 853.7, 598.2,
)


def music_pcm(seconds=8, bpm=125):
    period = 60 / bpm
    samples = array.array('h', (value for i in range(round(seconds * RATE))
        for value in (0, round((2200 if (i / RATE) % period < .055 else 180)
                              * math.cos(2 * math.pi * i / 192)))))
    if sys.byteorder != 'little':
        samples.byteswap()
    return samples.tobytes()


class EnvelopeProbe(MusicFeel):
    def __init__(self):
        super().__init__()
        self.frames = []

    def observe(self, rms, at):
        self.frames.append((rms, at))
        super().observe(rms, at)


class SampleTimingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.raw = music_pcm()

    def replay(self, size=3840, burst=False, listener=None):
        listener = listener or MusicFeel()
        for offset in range(0, len(self.raw), size):
            chunk = self.raw[offset:offset + size]
            end = (offset + len(chunk)) / (RATE * 4)
            now = 10 + (math.ceil((end - 1e-9) / .125) * .125 if burst else end)
            listener.feed(chunk, now)
            self.assertLessEqual(listener.snapshot(now).get('last_beat') or 0, now)
        return listener, now

    def test_125ms_delivery_bursts_preserve_sample_bpm_and_past_beat(self):
        uniform, now = self.replay()
        burst, burst_now = self.replay(burst=True)
        batches, batches_now = self.replay(size=24000, burst=True)
        for listener, at in ((uniform, now), (burst, burst_now), (batches,batches_now)):
            state = listener.snapshot(at)
            self.assertGreaterEqual(state['confidence'], .55)
            self.assertAlmostEqual(state['bpm'], 125, delta=6)
            self.assertLessEqual(state['last_beat'], at)
        self.assertAlmostEqual(uniform.snapshot(now)['bpm'], burst.snapshot(burst_now)['bpm'], delta=2)
        self.assertAlmostEqual(uniform.snapshot(now)['bpm'], batches.snapshot(batches_now)['bpm'], delta=2)

    def test_arbitrary_byte_boundaries_preserve_identical_energy_frames(self):
        aligned, _ = self.replay(listener=EnvelopeProbe())
        split, _ = self.replay(size=997, listener=EnvelopeProbe())
        self.assertEqual(len(aligned.frames), 400)
        self.assertEqual(aligned.frames, split.frames)

    def test_capture_gap_discards_old_rhythm_before_new_audio(self):
        listener, now = self.replay()
        self.assertGreaterEqual(listener.snapshot(now)['confidence'], .55)
        listener.feed(self.raw[:3840], now + 2)
        self.assertIsNone(listener.snapshot(now + 2)['bpm'])

    def test_short_omitted_pcm_gap_discards_previous_rhythm(self):
        listener, now = self.replay()
        listener.feed(self.raw[:3840], now + .42)
        self.assertIsNone(listener.snapshot(now + .42)['bpm'])

    def test_repeated_short_pcm_omissions_recover_fresh_sample_time(self):
        listener, now = self.replay()
        for index, offset in enumerate(range(0,len(self.raw),3840)):
            if index in (0,50):
                now += .4  # Music disabled: these samples never reach feed().
            now += .02
            listener.feed(self.raw[offset:offset+3840],now)
            self.assertLessEqual(listener.snapshot(now)['last_beat'] or 0,now)
        state = listener.snapshot(now)
        self.assertLess(state['age'], .1)
        self.assertGreaterEqual(state['confidence'], .55)
        self.assertAlmostEqual(state['bpm'], 125, delta=3)

    def test_backward_capture_clock_discards_old_rhythm(self):
        listener, _ = self.replay()
        listener.feed(self.raw[:3840], 1)
        self.assertIsNone(listener.snapshot(1)['bpm'])

    def test_capture_clock_drift_does_not_make_live_samples_stale(self):
        listener = MusicFeel()
        loud, quiet = self.raw[:3840], self.raw[3840*4:3840*5]
        # A sustained 1000 ppm clock difference accumulates beyond the stale
        # timeout. Bound the wall mapping using recent arrivals, not startup.
        for index in range(30000):
            at = (index+1)*.02
            now = 10 + at*1.001
            listener.feed(loud if index % 24 < 3 else quiet, now)
        state = listener.snapshot(now)
        self.assertLess(state['age'], .1)
        self.assertGreaterEqual(state['confidence'], .55)
        self.assertAlmostEqual(state['bpm'], 125, delta=3)
        self.assertLessEqual(state['last_beat'], now)
        self.assertLessEqual(len(listener.envelope), 400)
        self.assertLess(len(listener.partial), 3840)


class EnvelopePeriodicityTests(unittest.TestCase):
    def test_real_microphone_envelope_finds_repeated_period(self):
        listener = MusicFeel()
        stable = []
        for index, rms in enumerate(MICROPHONE_RMS, 1):
            at = index * .02
            listener.observe(rms, at)
            state = listener.snapshot(at)
            if state['confidence'] >= .55:
                stable.append(state)
        self.assertGreaterEqual(len(stable), 20)
        self.assertAlmostEqual(stable[-1]['bpm'], 100, delta=6)
        self.assertLessEqual(stable[-1]['last_beat'], 8)

    def test_smooth_repeated_envelopes_measure_different_tempos(self):
        for bpm in (83, 141):
            with self.subTest(bpm=bpm):
                listener = MusicFeel()
                for index in range(500):
                    at = index * .02
                    listener.observe(700 + 220 * math.cos(2 * math.pi * at * bpm / 60), at)
                state = listener.snapshot(at)
                self.assertGreaterEqual(state['confidence'], .55)
                self.assertAlmostEqual(state['bpm'], bpm, delta=4)

    def test_nonrhythmic_energy_does_not_create_confident_beats(self):
        source = random.Random(37)
        listener = MusicFeel()
        for index in range(600):
            at = index * .02
            listener.observe(source.uniform(200, 2000), at)
            self.assertLess(listener.snapshot(at)['confidence'], .55)

    def test_slow_volume_ramp_does_not_create_period_from_correlation(self):
        listener = MusicFeel()
        for index in range(600):
            at = index * .02
            listener.observe(200 + index * 2, at)
            self.assertIsNone(listener.snapshot(at)['bpm'])

    def test_weak_onset_sequence_does_not_hide_stronger_repetition(self):
        listener = MusicFeel()
        for index in range(500):
            at = index*.02
            level = 700 + 220*math.cos(2*math.pi*at/.48)
            if index in (355,395,435,475):
                level = 2200
            listener.observe(level, at)
        state = listener.snapshot(at)
        self.assertGreaterEqual(state['confidence'], .55)
        self.assertAlmostEqual(state['bpm'], 125, delta=4)

    def test_moderate_sparse_onsets_do_not_hide_stronger_repetition(self):
        listener = MusicFeel()
        for index in range(500):
            at = index*.02
            level = 700 + 220*math.cos(2*math.pi*at/.48)
            if index in (315,355,395,435,475):
                level = 2200
            listener.observe(level, at)
        state = listener.snapshot(at)
        self.assertGreaterEqual(state['confidence'], .55)
        self.assertAlmostEqual(state['bpm'], 125, delta=4)

    def test_music_stopping_at_measured_microphone_hiss_releases_beat(self):
        listener = MusicFeel()
        for index,rms in enumerate(MICROPHONE_RMS,1):
            listener.observe(rms,index*.02)
        self.assertGreaterEqual(listener.snapshot(8)['confidence'], .55)
        source = random.Random(17)
        for index in range(1,101):
            listener.observe(300 + source.uniform(-40,40),8+index*.02)
        self.assertEqual(listener.snapshot(10)['confidence'], 0)
        self.assertIsNone(listener.snapshot(10)['last_beat'])

    def test_slow_beats_stopping_at_microphone_hiss_release_within_two_seconds(self):
        listener = MusicFeel()
        for index in range(722):
            at = index*.02
            listener.observe(1400 if at % 1.2 < .055 else 100, at)
        self.assertGreaterEqual(listener.snapshot(14.42)['confidence'], .55)
        source = random.Random(17)
        for index in range(1,101):
            listener.observe(300 + source.uniform(-40,40),14.42+index*.02)
        self.assertEqual(listener.snapshot(16.42)['confidence'], 0)
        self.assertIsNone(listener.snapshot(16.42)['last_beat'])


if __name__ == '__main__':
    unittest.main()
