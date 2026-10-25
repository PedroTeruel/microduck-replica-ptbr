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
    """Envelope onsets measure rhythm, not musical genre or a human emotion.

    Processing keeps at most eight seconds/64 onset timestamps. No audio is
    retained. Observation and snapshot may run on different service threads.
    """
    def __init__(self, channel=1, clock=time.monotonic):
        if channel not in (0, 1):
            raise ValueError('microphone channel must be 0 or 1')
        self.channel, self.clock = channel, clock
        self.onsets = deque(maxlen=64)
        self.lock = threading.RLock()
        self.previous = self.level = 0.
        self.last_at = self.last_signal = None
        self.since_onset = -1e6

    def feed(self, stereo, now=None):
        now = self.clock() if now is None else now
        samples = array.array('h')
        samples.frombytes(stereo[:len(stereo)//4*4])
        if sys.byteorder != 'little':
            samples.byteswap()
        # Every sixth sample suffices for a level envelope (8 kHz, no FFT).
        mono = samples[self.channel::12]
        frame = int(RATE / 6 * FRAME_SECONDS)
        count = len(mono)
        for offset in range(0, count, frame):
            block = mono[offset:offset+frame]
            mean = sum(block)/max(1,len(block))
            rms = math.sqrt(sum((value-mean)**2 for value in block) / max(1, len(block)))
            self.observe(rms, now - (count-offset-len(block))/(RATE/6))

    def observe(self, rms, at):
        if not math.isfinite(rms) or not math.isfinite(at) or rms < 0:
            return
        with self.lock:
            if self.last_at is not None and at < self.last_at:
                return
            if self.last_at is not None and at-self.last_at > .5:
                self.onsets.clear()
                self.previous = 0.
            self.level, self.last_at = rms, at
            if rms > 30:
                self.last_signal = at
            if rms > max(120, self.previous*1.65) and at-self.since_onset >= .17:
                self.onsets.append(at)
                self.since_onset = at
            self.previous = rms
            while self.onsets and at-self.onsets[0] > 8:
                self.onsets.popleft()

    def snapshot(self, now=None):
        now = self.clock() if now is None else now
        with self.lock:
            state = {'bpm': None, 'confidence': 0., 'feel': 'unknown',
                     'level': round(self.level, 1), 'last_beat': None,
                     'age': None if self.last_at is None else round(max(0, now-self.last_at), 3)}
            if (self.last_at is None or now-self.last_at > .5 or self.last_signal is None
                    or now-self.last_signal > .5 or len(self.onsets) < 4):
                return state
            gaps = [b-a for a,b in zip(self.onsets, list(self.onsets)[1:])][-10:]
            # A repeated long-short pair can yield a swing-like response. This
            # does not assert jazz: other genres share the same rhythm.
            swing = False
            if len(gaps) >= 6:
                even, odd = gaps[::2], gaps[1::2]
                a, b = statistics.median(even), statistics.median(odd)
                ratio = max(a,b)/max(.001,min(a,b))
                swing = (1.45 <= ratio <= 2.6 and
                         all(abs(v-a) < a*.18 for v in even) and
                         all(abs(v-b) < b*.18 for v in odd))
            if swing:
                period = a+b
                variation = .03
            else:
                period = statistics.median(gaps)
                variation = statistics.median(abs(v-period) for v in gaps)/max(period,.001)
            if not .3 <= period <= 1.2 or variation > .16 or now-self.onsets[-1] > max(1.5, period*2):
                return state
            confidence = min(1., len(gaps)/6) * (1-min(1.,variation*3))
            bpm = 60/period
            feel = 'sway' if swing or 90 <= bpm < 115 else 'lively' if bpm >= 115 else 'mellow'
            state.update(bpm=round(bpm,1), confidence=round(confidence,3), feel=feel,
                         last_beat=self.onsets[-1])
            return state
