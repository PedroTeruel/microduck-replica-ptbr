"""Bounded local streaming question recognition sharing the existing Vosk Model."""
import array
from collections import deque
import json
import logging
import sys
import threading
import time

from music_feel import is_music_question, reaction_tag
from voice_commands import updates_allowed

LOG = logging.getLogger('duck-echo')
QUESTION_GRAMMAR = [
    '感觉 怎么样', '你 感觉 怎么样', '觉得 怎么样', '你 觉得 怎么样',
    '喜欢 这种 歌 吗', '你 喜欢 这种 歌 吗', '喜欢 这 首 歌 吗',
    '你 喜欢 这 首 歌 吗', '喜欢 这个 歌 吗', '你 喜欢 这个 歌 吗',
    '这 首 歌 好听 吗', '好听 吗',
    '不要 感觉 怎么样', '不 喜欢 这种 歌', '别 问 好听 吗',
    '他说 感觉 怎么样', '我说 喜欢 这种 歌 吗', '[unk]',
]


class MusicInteraction:
    """The capture callback only queues <=32 20ms frames; one worker owns Kaldi.

    No text leaves the worker or survives its current partial. Generation changes
    invalidate in-flight results when input drops, modes change or listening ends.
    """
    def __init__(self, recognizer_provider, feel, reply, channel=1, clock=time.monotonic,guard=updates_allowed):
        self.provider, self.feel, self.reply = recognizer_provider, feel, reply
        self.channel, self.clock = channel, clock
        self.guard=guard
        self.condition = threading.Condition()
        self.queue = deque(maxlen=32)
        self.history = deque(maxlen=64)
        self.enabled = self.closed = False
        self.generation = 0
        self.error = None
        self.idle = threading.Event()
        self.idle.set()
        self.last_reply = -1e9
        self.thread = threading.Thread(target=self._run, name='music-question', daemon=True)
        self.thread.start()

    def set_enabled(self, enabled):
        with self.condition:
            self.enabled = bool(enabled) and self.guard()
            self.generation += 1
            self.queue.clear()
            self.history.clear()
            self.condition.notify_all()

    def cancel(self):
        with self.condition:
            self.generation += 1
            self.queue.clear()
            self.history.clear()
            self.condition.notify_all()

    def feed(self, stereo, timestamp):
        # Production capture supplies 3840-byte frames; splitting also bounds
        # callers that supply a whole clip. Overflow discards the decoder context.
        with self.condition:
            if not self.enabled or self.closed:
                return
            state = self.feel.snapshot()
            if state.get('confidence', 0) >= .55 and (state.get('age') or 0) <= .5:
                if not self.history or timestamp - self.history[-1][0] >= .1:
                    self.history.append((timestamp, state))
            for offset in range(0, len(stereo), 3840):
                if len(self.queue) == self.queue.maxlen:
                    self.generation += 1
                    self.queue.clear()
                self.queue.append((self.generation, timestamp, stereo[offset:offset+3840]))
            self.idle.clear()
            self.condition.notify_all()

    def _valid(self, generation):
        with self.condition:
            return self.guard() and self.enabled and not self.closed and self.generation == generation

    def _context(self, timestamp):
        with self.condition:
            # Prefer the recent rhythm before recognition started hearing the
            # question; a voice onset must not redefine the musical response.
            states = [state for at, state in self.history if .5 <= timestamp-at <= 4]
            if states:
                return states[-1]
        return self.feel.snapshot()

    def _decoder(self):
        shared = self.provider()
        if shared is None:
            self.error = 'music speech recognition unavailable; local model is not ready'
            return None
        grammar = [phrase for phrase in QUESTION_GRAMMAR if phrase == '[unk]' or
                   all(shared.model.vosk_model_find_word(word) >= 0 for word in phrase.split())]
        decoder = shared.recognizer_type(shared.model, 48000, json.dumps(grammar, ensure_ascii=False))
        decoder.SetWords(True)
        decoder.SetPartialWords(False)
        self.error = None
        return decoder

    def _run(self):
        decoder = None
        decoder_generation = -1
        candidate = None
        candidate_at = None
        context = None
        last_partial = -1e9
        while True:
            with self.condition:
                while not self.queue and not self.closed:
                    if decoder is not None and decoder_generation != self.generation:
                        decoder.Reset()
                        decoder_generation = self.generation
                        candidate = candidate_at = context = None
                        last_partial = -1e9
                    self.idle.set()
                    self.condition.wait()
                if self.closed:
                    return
                generation, timestamp, raw = self.queue.popleft()
            try:
                if not self._valid(generation) or self.clock()-timestamp > 1:
                    continue
                if decoder is None:
                    decoder = self._decoder()
                    if decoder is None:
                        continue
                if decoder_generation != generation:
                    decoder.Reset()
                    decoder_generation = generation
                    candidate = candidate_at = context = None
                    last_partial = -1e9
                samples = array.array('h')
                samples.frombytes(raw[:len(raw)//4*4])
                if sys.byteorder != 'little':
                    samples.byteswap()
                mono = samples[self.channel::2]
                if sys.byteorder != 'little':
                    mono.byteswap()
                final = decoder.AcceptWaveform(mono.tobytes())
                if final:
                    result = json.loads(decoder.Result())
                else:
                    if timestamp-last_partial < .1:
                        continue
                    last_partial = timestamp
                    # Vosk aligns the whole partial lattice when PartialWords
                    # is enabled. Incomplete/unknown music paths can warn on
                    # every frame. Inspect cheap best-path text first, then
                    # align only an exact candidate to verify real confidence.
                    result = json.loads(decoder.PartialResult())
                    if is_music_question(result.get('partial', ''), 1):
                        decoder.SetPartialWords(True)
                        try:
                            result = json.loads(decoder.PartialResult())
                        finally:
                            decoder.SetPartialWords(False)
                text = result.get('text' if final else 'partial', '')
                words = result.get('result' if final else 'partial_result', [])
                confidence = min((word.get('conf', 0) for word in words), default=0)
                question = is_music_question(text, confidence)
                normalized = ''.join(text.split()) if question else None
                if question and normalized != candidate:
                    candidate, candidate_at = normalized, timestamp
                    context = self._context(timestamp)
                elif not question:
                    candidate = candidate_at = context = None
                answer = question and (final or timestamp-candidate_at >= .5)
                if answer and self.clock()-self.last_reply >= 4 and self._valid(generation):
                    self.reply(reaction_tag(context or {}), lambda: self._valid(generation))
                    if self._valid(generation):
                        self.last_reply = self.clock()
                if final or answer:
                    decoder.Reset()
                    candidate = candidate_at = context = None
                    last_partial = -1e9
            except Exception:
                self.error = 'music speech recognition unavailable'
                LOG.exception('music question recognition failed')
                decoder = None
            finally:
                with self.condition:
                    if not self.queue:
                        self.idle.set()

    def close(self):
        with self.condition:
            self.enabled = False
            self.closed = True
            self.generation += 1
            self.queue.clear()
            self.condition.notify_all()
        self.thread.join(timeout=2)
