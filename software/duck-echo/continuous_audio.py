"""One continuous PCM source, bounded utterances, and cancellable echo dispatch."""
import logging
import subprocess
import tempfile
import threading
import time

LOG = logging.getLogger('duck-echo')
RATE, FRAME_BYTES = 48000, 4


class ToggleButton:
    def __init__(self, audio, initially_down=False):
        self.audio, self.down = audio, initially_down
        self.recording = False

    def event(self, value, now=None):
        if value == 0:
            self.down = False
        elif value == 1 and not self.down:
            self.down = True
            if self.recording:
                self.cancel()
            else:
                self.audio.start()
                self.recording = True

    def tick(self, now=None):
        if self.recording and self.audio.expired():
            self.cancel()

    def cancel(self):
        self.recording = False
        self.audio.stop(play=False)


class PcmSegmenter:
    """20 ms RMS windows on the selected microphone; silence terminates speech."""
    def __init__(self, channel=1, maximum=10, silence=.6, minimum=.25, threshold=-42):
        from duck_echo import prepare_audio
        if channel not in (0, 1) or not .25 <= maximum <= 10:
            raise ValueError('invalid microphone channel or phrase maximum')
        self.prepare = prepare_audio
        self.channel = channel
        self.window_bytes = round(RATE * .02) * FRAME_BYTES
        self.maximum_bytes = round(maximum * RATE) * FRAME_BYTES
        self.minimum_bytes = round(minimum * RATE) * FRAME_BYTES
        self.silence_bytes = round(silence * RATE) * FRAME_BYTES
        self.threshold = threshold
        self.reset()

    def reset(self):
        self.partial = bytearray()
        self.phrase = bytearray()
        self.quiet = 0
        self.voiced = 0

    @property
    def buffered_bytes(self):
        return len(self.partial) + len(self.phrase)

    def feed(self, data):
        phrases = []
        # Never retain an unbounded source chunk, even with a non-ALSA source.
        for offset in range(0, len(data), self.window_bytes):
            self.partial.extend(data[offset:offset + self.window_bytes])
            while len(self.partial) >= self.window_bytes:
                raw = bytes(self.partial[:self.window_bytes])
                del self.partial[:self.window_bytes]
                selected, level = self.prepare(raw, self.channel)
                voiced = level['dbfs'] >= self.threshold
                if not self.phrase and not voiced:
                    continue
                self.phrase.extend(selected)
                self.voiced += len(selected) if voiced else 0
                self.quiet = 0 if voiced else self.quiet + len(selected)
                if len(self.phrase) >= self.maximum_bytes or self.quiet >= self.silence_bytes:
                    if self.voiced >= self.minimum_bytes:
                        phrases.append(bytes(self.phrase[:self.maximum_bytes]))
                    self.phrase.clear()
                    self.quiet = self.voiced = 0
        return phrases


class ContinuousAudio:
    """Capture never waits for ASR/playback, and input cancellation never joins workers.

    Only the capture thread owns arecord, so rapid off/on cannot open two capture
    streams. The dispatch thread keeps one pending phrase or playback request.
    Generation changes invalidate work across stop, EOF, and reconnect.
    """
    def __init__(self, backend, capture_device=None, channel=None, maximum=None,
                 silence=.6, minimum=.25, tail=.35, clock=time.monotonic, observer=None,
                 threshold=-42):
        self.backend = backend
        self.capture_device = capture_device or backend.capture_device
        self.channel = backend.channel if channel is None else channel
        self.maximum = backend.maximum if maximum is None else maximum
        self.segmenter = PcmSegmenter(self.channel, self.maximum, silence, minimum, threshold)
        self.tail, self.clock = tail, clock
        self.observer = observer
        self.voice = None
        self.condition = threading.Condition()
        # Never acquire this while holding condition: VoiceControl._echo holds
        # its own condition while calling our nonblocking play() enqueue.
        self.dispatch_lock = threading.Lock()
        self.generation = 0
        self.active = self.closed = self.failed = False
        self.pending = None
        self.stop_output = False
        self.output_pending = False
        self.cue_active = False
        self.suppress_until = 0
        self.capture = None
        self.capture_stop = None
        self.capture_thread = threading.Thread(target=self._capture_loop, name='continuous-capture', daemon=True)
        self.worker = threading.Thread(target=self._dispatch, name='continuous-dispatch', daemon=True)
        self.capture_thread.start()
        self.worker.start()

    def start(self):
        self.stop(play=False)
        with self.condition:
            if self.closed:
                return
            self.active, self.failed = True, False
            self.condition.notify_all()
        LOG.info('continuous listening on; click R3 again to stop')

    def expired(self):
        with self.condition:
            return self.failed

    def cancel_processing(self):
        with self.condition:
            generation = self._invalidate()
        self._cancel_voice(generation)

    def _invalidate(self):
        self.generation += 1
        self.pending = None
        self.output_pending = False
        self.segmenter.reset()
        return self.generation

    def _valid(self, generation):
        with self.condition:
            return self.active and generation == self.generation and not self.closed

    def _cancel_voice(self, generation):
        with self.dispatch_lock:
            with self.condition:
                current = generation == self.generation
            if current and self.voice is not None:
                self.voice.cancel()

    def stop(self, play=False, expected_generation=None):
        with self.condition:
            if expected_generation is not None and expected_generation != self.generation:
                return
            self.active = False
            generation = self._invalidate()
            capture_stop = self.capture_stop
            self.stop_output = True
            self.condition.notify_all()
        self._cancel_voice(generation)
        if capture_stop is not None:
            capture_stop.set()

    def stop_playback(self):
        with self.condition:
            self.stop_output = True
            self.condition.notify_all()

    def _suppressed(self):
        playing = self.backend.playback_active()
        if playing or self.output_pending or self.cue_active:
            self.suppress_until = self.clock() + self.tail
            return True
        return self.clock() < self.suppress_until

    def suppressed(self):
        with self.condition:
            return self._suppressed()

    def feed(self, data, generation=None):
        """Feed captured PCM; this is also the future single-source analysis hook."""
        with self.condition:
            if not self.active or (generation is not None and generation != self.generation):
                return
            if self._suppressed():
                self.segmenter.reset()
                return
            for phrase in self.segmenter.feed(data):
                self.pending = ('phrase', self.generation, phrase)
                self.condition.notify_all()
            observer, timestamp = self.observer, self.clock()
        # Observers must be quick in-memory consumers. They never run under the
        # capture lock and never receive output-contaminated or inactive input.
        if observer is not None:
            try:
                observer(data, timestamp)
            except Exception:
                LOG.exception('PCM observer failed')

    def play(self, data):
        with self.condition:
            if self.active and not self.closed:
                self.output_pending = True
                self.segmenter.reset()
                self.pending = ('play', self.generation, data)
                self.condition.notify_all()

    def command_cue(self, callback, accepted):
        with self.condition:
            if not self.active or self.closed:
                return
            self.cue_active = True
            self.pending = None
            self.output_pending = False
            self.segmenter.reset()
        try:
            callback(accepted)
        finally:
            with self.condition:
                self.cue_active = False
                # robot.sound acknowledges asynchronously, so reserve enough
                # time for the short chirp itself as well as the acoustic tail.
                self.suppress_until = max(self.suppress_until, self.clock() + 1 + self.tail)

    def _dispatch(self):
        while True:
            with self.condition:
                while self.pending is None and not self.stop_output and not self.closed:
                    self.condition.wait()
                stop = self.stop_output
                self.stop_output = False
                job, self.pending = self.pending, None
                closed = self.closed
            if stop or closed:
                self.backend.stop_playback()
            if closed:
                self.backend.close()
                return
            if job is None:
                continue
            kind, generation, data = job
            if kind == 'phrase' and self.voice is not None:
                with self.dispatch_lock:
                    with self.condition:
                        valid = self.active and generation == self.generation
                    if valid:
                        self.voice.submit(data)
                continue
            with self.condition:
                valid = self.active and generation == self.generation
                if kind == 'phrase' and valid:
                    self.output_pending = True
                    self.segmenter.reset()
            if valid:
                try:
                    self.backend.play(data, allowed=lambda generation=generation: self._valid(generation))
                except Exception:
                    LOG.exception('continuous playback failed')
                finally:
                    with self.condition:
                        if generation == self.generation:
                            self.output_pending = False
                            self.suppress_until = self.clock() + self.tail

    @staticmethod
    def _reap_capture(process, requested):
        requested.wait()
        from duck_echo import terminate
        terminate(process)

    def _capture_loop(self):
        while True:
            with self.condition:
                while not self.active and not self.closed:
                    self.condition.wait()
                if self.closed:
                    return
                generation = self.generation
            errors = tempfile.TemporaryFile()
            process = None
            reaper = capture_stop = None
            try:
                process = subprocess.Popen([
                    'arecord', '-q', '-D', self.capture_device, '-t', 'raw',
                    '-f', 'S16_LE', '-c', '2', '-r', str(RATE),
                ], stdout=subprocess.PIPE, stderr=errors)
                # Exactly one reaper owns this process. Repeated off/cancel
                # events only set its Event; cleanup joins the same owner.
                capture_stop = threading.Event()
                reaper = threading.Thread(target=self._reap_capture, args=(process, capture_stop),
                                          name='continuous-reaper', daemon=True)
                reaper.start()
                with self.condition:
                    self.capture = process
                    self.capture_stop = capture_stop
                    valid = self.active and generation == self.generation
                if valid:
                    while True:
                        data = process.stdout.read(self.segmenter.window_bytes)
                        if not data:
                            break
                        self.feed(data, generation)
                        with self.condition:
                            if not self.active or generation != self.generation:
                                break
            except (OSError, ValueError):
                LOG.exception('continuous capture unavailable')
            finally:
                if process is not None:
                    # Also handles stop arriving during Popen, before the
                    # process and its stop Event were visible to evdev.
                    capture_stop.set()
                    reaper.join()
                    process.stdout.close()
                errors.seek(0)
                message = errors.read().decode(errors='replace').strip()
                errors.close()
                with self.condition:
                    if self.capture is process:
                        self.capture = None
                        self.capture_stop = None
                    failed = self.active and generation == self.generation
                    if failed:
                        self.failed = True
                if failed:
                    LOG.warning('continuous capture ended; press R3 after release to retry: %s', message)
                    self.stop(play=False, expected_generation=generation)

    def close(self):
        self.stop(play=False)
        with self.condition:
            self.closed = True
            self.condition.notify_all()
        self.capture_thread.join(timeout=2)
        self.worker.join(timeout=2)
