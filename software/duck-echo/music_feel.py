"""Small local rhythm features and deliberate music-question reactions."""
import array
from collections import deque
import math
import statistics
import sys
import threading
import time
import unicodedata

RATE = 48000
FRAME_SECONDS = .02
QUESTIONS = frozenset((
    '感觉怎么样', '你感觉怎么样', '觉得怎么样', '你觉得怎么样',
    '喜欢这种歌吗', '你喜欢这种歌吗', '喜欢这首歌吗', '你喜欢这首歌吗',
    '喜欢这个歌吗', '你喜欢这个歌吗', '这首歌好听吗', '好听吗',
))


def is_music_question(text, confidence):
    if not isinstance(text, str) or len(text) > 80:
        return False
    if not isinstance(confidence, (int, float)) or not math.isfinite(confidence) or confidence < .8:
        return False
    text = ''.join(c for c in text if not c.isspace() and not unicodedata.category(c).startswith('P'))
    for address in ('小鸭子', '鸭子'):
        if text.startswith(address):
            text = text[len(address):]
            break
    return text in QUESTIONS


def reaction_tag(state):
    if state.get('confidence', 0) < .55:
        return 'inquire'
    return {'lively': 'chirp', 'mellow': 'coo', 'sway': 'greet'}.get(state.get('feel'), 'inquire')


class MusicFeel:
    """Envelope repetition measures rhythm, not genre or a human emotion.

    Keep eight seconds of numeric levels, 64 onsets, and one partial 20 ms PCM
    window. Periodicity runs at most five times per sample second on the capture
    thread; snapshot only reads its cached result. No recordings are retained.
    """
    def __init__(self, channel=1, clock=time.monotonic):
        if channel not in (0, 1):
            raise ValueError('microphone channel must be 0 or 1')
        self.channel, self.clock = channel, clock
        self.onsets = deque(maxlen=64)
        self.envelope = deque(maxlen=400)
        self.lock = threading.RLock()
        self.partial = bytearray()
        self.sample_bytes = 0
        self.sample_offset = None
        self.last_arrival = None
        self.arrival_offsets = deque(maxlen=1024)
        self._reset_rhythm()

    def _reset_rhythm(self):
        self.onsets.clear()
        self.envelope.clear()
        self.previous = self.level = 0.
        self.last_at = self.last_signal = None
        self.since_onset = -1e6
        self.analysis_at = -1e6
        self.rhythm = None

    def feed(self, stereo, now=None):
        now = self.clock() if now is None else now
        if not math.isfinite(now) or not stereo:
            return
        with self.lock:
            duration = len(stereo) / (RATE * 4)
            if (self.last_arrival is not None and
                    (now < self.last_arrival or now-self.last_arrival > max(.18, duration+.15))):
                # Permit measured 125 ms ALSA bursts, but treat short omitted
                # PCM intervals (mode changes/output suppression) as a new
                # stream rather than slowly correcting their missing samples.
                self._reset_rhythm()
                self.partial.clear()
                self.sample_bytes = 0
                self.sample_offset = None
                self.arrival_offsets.clear()
            elapsed = 0. if self.last_arrival is None else max(0.,now-self.last_arrival)
            self.last_arrival = now
            self.sample_bytes += len(stereo)
            # ALSA may deliver several windows in a burst. Their spacing comes
            # from samples, not read() arrival. Tighten the wall mapping as a
            # burst drains so even its newest sample never lies in the future.
            offset = now - self.sample_bytes / (RATE * 4)
            # A monotonic queue retains only the recent lower arrival bound.
            # Otherwise even small audio/wall clock drift accumulates forever.
            while self.arrival_offsets and self.arrival_offsets[-1][1] >= offset:
                self.arrival_offsets.pop()
            self.arrival_offsets.append((now,offset))
            while now-self.arrival_offsets[0][0] > 2:
                self.arrival_offsets.popleft()
            recent_offset = self.arrival_offsets[0][1]
            # Advance phase gently (at most 1% of elapsed wall time). Tightening
            # the bound backwards is immediate, to keep all beats in the past.
            self.sample_offset = (recent_offset if self.sample_offset is None else
                                  min(recent_offset,self.sample_offset+.01*elapsed))
            window_bytes = round(RATE * FRAME_SECONDS) * 4
            position = 0
            while position < len(stereo):
                take = min(window_bytes-len(self.partial), len(stereo)-position)
                self.partial.extend(stereo[position:position+take])
                position += take
                if len(self.partial) != window_bytes:
                    continue
                samples = array.array('h')
                samples.frombytes(self.partial)
                self.partial.clear()
                if sys.byteorder != 'little':
                    samples.byteswap()
                # Every sixth sample gives an 8 kHz, DC-free level envelope.
                mono = samples[self.channel::12]
                mean = sum(mono)/len(mono)
                rms = math.sqrt(sum((value-mean)**2 for value in mono) / len(mono))
                consumed = self.sample_bytes - (len(stereo)-position)
                self.observe(rms, consumed / (RATE * 4))

    def observe(self, rms, at):
        if not math.isfinite(rms) or not math.isfinite(at) or rms < 0:
            return
        with self.lock:
            if self.last_at is not None and at < self.last_at:
                return
            if self.last_at is not None and at-self.last_at > .5:
                self._reset_rhythm()
            self.level, self.last_at = rms, at
            self.envelope.append((at, math.log(max(1., rms))))
            if rms > 30:
                self.last_signal = at
            if rms > max(120, self.previous*1.65) and at-self.since_onset >= .17:
                self.onsets.append(at)
                self.since_onset = at
            self.previous = rms
            while self.onsets and at-self.onsets[0] > 8:
                self.onsets.popleft()
            if at-self.analysis_at >= .2-1e-9:
                self.analysis_at = at
                onsets = self._onset_rhythm(at)
                if onsets is not None and onsets[1] >= .85:
                    self.rhythm = onsets
                else:
                    periodic = self._periodic_rhythm()
                    # Sparse startup onsets can form a different, moderately
                    # regular rhythm. Let substantially stronger repetition
                    # win, while preserving well-supported drums and swing.
                    self.rhythm = (onsets if onsets is not None and onsets[1] >= .55
                                   and (periodic is None or periodic[1] <= onsets[1]+.1)
                                   else periodic)

    def _onset_rhythm(self, at):
        if len(self.onsets) < 4:
            return None
        gaps = [b-a for a,b in zip(self.onsets, list(self.onsets)[1:])][-10:]
        # A repeated long-short pair permits a swing response without a genre
        # claim. Preserve sharp drum timing when the onsets are consistent.
        swing = False
        if len(gaps) >= 6:
            even, odd = gaps[::2], gaps[1::2]
            a, b = statistics.median(even), statistics.median(odd)
            ratio = max(a,b)/max(.001,min(a,b))
            swing = (1.45 <= ratio <= 2.6 and
                     all(abs(v-a) < a*.18 for v in even) and
                     all(abs(v-b) < b*.18 for v in odd))
        if swing:
            period, variation = a+b, .03
        else:
            period = statistics.median(gaps)
            variation = statistics.median(abs(v-period) for v in gaps)/max(period,.001)
            if sum(abs(v-period) <= period*.2 for v in gaps) < len(gaps)*.8:
                return None
        if not .3 <= period <= 1.2 or variation > .16 or at-self.onsets[-1] > 1.5:
            return None
        confidence = min(1., len(gaps)/6) * (1-min(1.,variation*3))
        return period, confidence, swing, self.onsets[-1]

    @staticmethod
    def _correlation(values, lag):
        left, right = values[:-lag], values[lag:]
        mean_left, mean_right = sum(left)/len(left), sum(right)/len(right)
        covariance = sum((a-mean_left)*(b-mean_right) for a,b in zip(left,right))
        variance = (sum((v-mean_left)**2 for v in left) *
                    sum((v-mean_right)**2 for v in right))
        return covariance / math.sqrt(variance) if variance > 1e-12 else 0.

    def _periodic_rhythm(self):
        # Use six recent seconds, at least four repetitions, and agreement in
        # both halves. Log levels retain quieter drums under sustained music.
        frames = list(self.envelope)[-300:]
        if len(frames) < 150 or any(abs(b[0]-a[0]-FRAME_SECONDS) > .002
                                    for a,b in zip(frames, frames[1:])):
            return None
        values = [v for _,v in frames]
        contrast = statistics.pstdev(values)
        if contrast < .08 or statistics.pstdev(values[-50:]) < max(.08,contrast*.4):
            # The room microphone keeps reporting hiss after music stops. Old
            # periodic history must not project new beats into that quiet tail.
            return None
        scores = {lag: self._correlation(values, lag) for lag in range(15,61)
                  if len(values) >= lag*4+1}
        middle = len(values)//2
        candidates = [(score,lag) for lag,score in scores.items() if score >= .35
                      and score >= scores.get(lag-1, -1) and score >= scores.get(lag+1, -1)
                      and self._correlation(values[:middle],lag) >= .2
                      and self._correlation(values[middle:],lag) >= .2]
        if not candidates:
            return None
        best = max(score for score,_ in candidates)
        if best-statistics.median(scores.values()) < .2:
            return None  # A ramp correlates at every lag; it has no beat peak.
        # Prefer the shorter supported repetition over a nearly equal harmonic.
        score, lag = min(((s,l) for s,l in candidates if s >= best*.85), key=lambda item: item[1])
        flux = [0.] + [max(0.,b-a) for a,b in zip(values,values[1:])]
        phases = [sum(flux[index] for index in range(phase,len(flux),lag)) for phase in range(lag)]
        phase = max(range(lag), key=phases.__getitem__)
        beat_index = len(frames)-1 - (len(frames)-1-phase) % lag
        return lag*FRAME_SECONDS, min(1.,score/.6), False, frames[beat_index][0]

    def snapshot(self, now=None):
        now = self.clock() if now is None else now
        with self.lock:
            offset = self.sample_offset or 0.
            last_at = None if self.last_at is None else self.last_at + offset
            last_signal = None if self.last_signal is None else self.last_signal + offset
            state = {'bpm': None, 'confidence': 0., 'feel': 'unknown',
                     'level': round(self.level, 1), 'last_beat': None,
                     'age': None if last_at is None else round(max(0, now-last_at), 3)}
            if (not math.isfinite(now) or last_at is None or not 0 <= now-last_at <= .5
                    or last_signal is None or now-last_signal > .5 or self.rhythm is None):
                return state
            period, confidence, swing, beat = self.rhythm
            beat += offset
            # Even the slowest supported period is 1.2 s. Do not retain two
            # slow periods after the sound has stopped at the microphone.
            if beat > now or now-beat > 1.5:
                return state
            bpm = 60/period
            feel = 'sway' if swing or 90 <= bpm < 115 else 'lively' if bpm >= 115 else 'mellow'
            state.update(bpm=round(bpm,1), confidence=round(confidence,3), feel=feel,
                         last_beat=beat)
            return state
