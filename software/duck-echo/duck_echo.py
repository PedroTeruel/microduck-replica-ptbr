#!/usr/bin/env python3
"""Click R3 to toggle continuous speech; --trigger-mode hold retains hold/release."""
import argparse
import array
import glob
import json
import logging
import math
import os
import select
import signal
import struct
import subprocess
import sys
import tempfile
import threading
import time

LOG = logging.getLogger('duck-echo')
RATE = 48000
FRAME_BYTES = 4
BUTTON = 318  # Linux BTN_THUMBR (right stick click)
INPUT_EVENT = struct.Struct('@qqHHi')  # 64-bit Linux timeval, type, code, value


def prepare_audio(raw, channel):
    if channel not in (0, 1):
        raise ValueError('microphone channel must be 0 or 1')
    samples = array.array('h')
    samples.frombytes(raw[:len(raw) // FRAME_BYTES * FRAME_BYTES])
    if sys.byteorder != 'little':
        samples.byteswap()
    mono = samples[channel::2]
    peak = max((abs(x) for x in mono), default=0)
    rms = math.sqrt(sum(x * x for x in mono) / max(1, len(mono)))
    stereo = array.array('h', (x for sample in mono for x in (sample, sample)))
    if sys.byteorder != 'little':
        stereo.byteswap()
    return stereo.tobytes(), {
        'frames': len(mono), 'seconds': round(len(mono) / RATE, 3),
        'peak': peak, 'rms': round(rms, 3),
        'dbfs': round(20 * math.log10(max(rms, 1e-6) / 32768), 1),
    }


def decode_events(raw):
    if len(raw) % INPUT_EVENT.size:
        raise ValueError('incomplete evdev event')
    return [(kind, code, value) for _, _, kind, code, value in INPUT_EVENT.iter_unpack(raw)]


class HoldButton:
    def __init__(self, audio, initially_down=False, repeat_on_limit=True):
        self.audio = audio
        self.down = initially_down
        self.recording = False
        self.since = 0.0
        self.repeat_on_limit = repeat_on_limit

    def event(self, value, now=None):
        now = time.monotonic() if now is None else now
        if value == 1 and not self.down:
            self.down = True
            self.since = now
            self.audio.start()
            self.recording = True
        elif value == 0:
            self.down = False
            if self.recording:
                self.recording = False
                self.audio.stop(play=now - self.since >= 0.25)

    def tick(self, now=None):
        if self.recording and self.audio.expired():
            self.recording = False
            self.audio.stop(play=self.repeat_on_limit)

    def cancel(self):
        cancel_processing = getattr(self.audio, 'cancel_processing', None)
        if cancel_processing is not None:
            cancel_processing()
        if self.recording:
            self.recording = False
            self.audio.stop(play=False)


def terminate(process):
    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=1)


class AlsaAudio:
    def __init__(self, capture_device, playback_device, channel=1, pitch=1.25, maximum=10):
        self.capture_device = capture_device
        self.playback_device = playback_device
        self.channel, self.pitch, self.maximum = channel, pitch, maximum
        self.capture = None
        self.player = None
        self.player_thread = None
        self.playback_ok = None
        self.last_result = None
        self.voice = None
        self.playback_lock = threading.RLock()

    def start(self):
        self.cancel_processing()
        self.stop(play=False)
        self.stop_playback()
        errors = tempfile.TemporaryFile()
        try:
            process = subprocess.Popen([
                'arecord', '-q', '-D', self.capture_device, '-t', 'raw',
                '-f', 'S16_LE', '-c', '2', '-r', str(RATE), '-d', str(self.maximum),
            ], stdout=subprocess.PIPE, stderr=errors)
        except BaseException:
            errors.close()
            raise
        chunks = bytearray()

        def read():
            try:
                while True:
                    block = process.stdout.read(4096)
                    if not block:
                        break
                    remaining = self.maximum * RATE * FRAME_BYTES - len(chunks)
                    if remaining > 0:
                        chunks.extend(block[:remaining])
            except OSError:
                LOG.exception('capture stream read failed')

        reader = threading.Thread(target=read, daemon=True)
        self.capture = (process, errors, reader, chunks, time.monotonic())
        reader.start()
        LOG.info('recording: hold R3; release to repeat (maximum %ss)', self.maximum)

    def expired(self):
        if self.capture is None:
            return False
        process, _, _, _, started = self.capture
        return process.poll() is not None or time.monotonic() - started >= self.maximum + 1

    def stop(self, play):
        if not play:
            self.cancel_processing()
        if self.capture is None:
            return None
        process, errors, reader, chunks, _ = self.capture
        self.capture = None
        interrupted = process.poll() is None
        if interrupted:
            process.send_signal(signal.SIGINT)
        try:
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            terminate(process)
        reader.join(timeout=2)
        if reader.is_alive():
            errors.close()
            raise RuntimeError('capture reader did not stop; discarding clip')
        process.stdout.close()
        errors.seek(0)
        error_text = errors.read().decode(errors='replace').strip()
        errors.close()
        # arecord exits 1 when its normal SIGINT handler finalizes a recording.
        normal_interrupt = interrupted and process.returncode in (-signal.SIGINT, 1) and (
            not error_text or 'signal' in error_text.lower())
        if process.returncode != 0 and not normal_interrupt:
            LOG.error('capture failed (%s): %s', process.returncode, error_text)
            self.last_result = {'ok': False, 'error': error_text or 'arecord failed'}
            return self.last_result
        output, level = prepare_audio(bytes(chunks), self.channel)
        level['signal_detected'] = level['dbfs'] > -65 and level['peak'] > 20
        level['ok'] = level['signal_detected'] and level['seconds'] >= 0.25
        self.last_result = level
        LOG.info('microphone: %s', json.dumps(level))
        if play and level['ok']:
            if self.voice is not None:
                self.voice.submit(output)
            else:
                self.play(output)
        elif play:
            LOG.warning('clip too short or silent; check microphone and mixer routing')
        return level

    def play(self, data, allowed=None):
        with self.playback_lock:
            self._play(data, allowed)

    def _play(self, data, allowed=None):
        self.stop_playback()
        if allowed is not None and not allowed():
            return
        self.playback_ok = None
        errors = tempfile.TemporaryFile()
        try:
            process = subprocess.Popen([
                'aplay', '-q', '-D', self.playback_device, '-t', 'raw', '-f', 'S16_LE',
                '-c', '2', '-r', str(round(RATE * self.pitch)),
            ], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=errors)
        except BaseException:
            errors.close()
            raise
        self.player = process

        def write():
            try:
                if allowed is not None and not allowed():
                    terminate(process)
                    process.communicate(timeout=1)
                    return
                process.communicate(input=data, timeout=self.maximum / self.pitch + 4)
                self.playback_ok = process.returncode == 0
                if process.returncode not in (0, -signal.SIGTERM):
                    errors.seek(0)
                    LOG.error('playback failed: %s', errors.read().decode(errors='replace').strip())
                elif process.returncode == 0:
                    LOG.info('repeat playback completed (pitch/speed %.2fx)', self.pitch)
            except subprocess.TimeoutExpired:
                self.playback_ok = False
                terminate(process)
                process.communicate()
                LOG.error('playback timeout')
            except (OSError, ValueError):
                self.playback_ok = False
                LOG.exception('playback stream failed')
                terminate(process)
            finally:
                errors.close()

        self.player_thread = threading.Thread(target=write, daemon=True)
        self.player_thread.start()

    def stop_playback(self):
        with self.playback_lock:
            self._stop_playback()

    def _stop_playback(self):
        if self.player is not None:
            terminate(self.player)
            self.player = None
        if self.player_thread is not None:
            self.player_thread.join(timeout=2)
            self.player_thread = None

    def finish_playback(self):
        if self.player_thread:
            self.player_thread.join(timeout=self.maximum / self.pitch + 6)
        self.stop_playback()
        return self.playback_ok is True

    def playback_active(self):
        player, writer = self.player, self.player_thread
        return ((player is not None and player.poll() is None) or
                (writer is not None and writer.is_alive()))

    def close(self):
        self.cancel_processing()
        self.stop(play=False)
        self.stop_playback()

    def cancel_processing(self):
        if self.voice is not None:
            self.voice.cancel()


def key_bitmap(fd, current=False):
    import fcntl
    bits = bytearray(96)
    # EVIOCGKEY or EVIOCGBIT(EV_KEY), with sizeof(bitmap) in the ioctl.
    request = (2 << 30) | (len(bits) << 16) | (ord('E') << 8) | (0x18 if current else 0x21)
    fcntl.ioctl(fd, request, bits, True)
    return bits


def right_pressed(fd):
    bits = key_bitmap(fd, current=True)
    return bool(bits[BUTTON // 8] & (1 << (BUTTON % 8)))


def devices():
    result = []
    for path in sorted(glob.glob('/dev/input/event*')):
        try:
            fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK)
            try:
                bits = key_bitmap(fd)
                if bits[BUTTON // 8] & (1 << (BUTTON % 8)):
                    name_path = '/sys/class/input/' + os.path.basename(path) + '/device/name'
                    with open(name_path, encoding='utf-8') as source:
                        name = source.read().strip()
                    result.append({'path': path, 'name': name})
            finally:
                os.close(fd)
        except (OSError, ValueError):
            continue
    return result


def make_button(audio, initially_down=False, trigger_mode='toggle'):
    if trigger_mode == 'hold':
        return HoldButton(audio, initially_down=initially_down, repeat_on_limit=audio.voice is None)
    from continuous_audio import ToggleButton
    return ToggleButton(audio, initially_down=initially_down)


def daemon(audio, stopped, selected=None, trigger_mode='toggle'):
    announced = False
    while not stopped.is_set():
        available = devices()
        if selected:
            available = [item for item in available if item['path'] == selected]
        if not available:
            if not announced:
                LOG.info('waiting for a gamepad with R3; existing padd keeps control')
                announced = True
            stopped.wait(1)
            continue
        announced = False
        item = available[0]
        fd = None
        button = None
        try:
            fd = os.open(item['path'], os.O_RDONLY | os.O_NONBLOCK)
            button = make_button(audio, initially_down=right_pressed(fd), trigger_mode=trigger_mode)
            LOG.info('listening without grab: %s (%s), R3=%s', item['name'], item['path'], BUTTON)
            resync = False
            while not stopped.is_set():
                readable, _, _ = select.select([fd], [], [], 0.1)
                if readable:
                    raw = os.read(fd, INPUT_EVENT.size * 64)
                    if not raw:
                        raise OSError('gamepad disconnected')
                    for kind, code, value in decode_events(raw):
                        if kind == 0 and code == 3:  # SYN_DROPPED: discard until SYN_REPORT
                            button.cancel()
                            resync = True
                        elif resync:
                            if kind == 0 and code == 0:
                                button = make_button(audio, initially_down=right_pressed(fd),
                                                     trigger_mode=trigger_mode)
                                resync = False
                        elif kind == 1 and code == BUTTON:
                            button.event(value)
                        elif kind == 1 and code == 314 and value == 1:  # Select cancels pending voice actions
                            button.cancel()
                            audio.cancel_processing()
                button.tick()
        except (OSError, ValueError, RuntimeError):
            LOG.exception('input/audio unavailable; retrying')
        finally:
            if button:
                button.cancel()
            audio.stop(play=False)
            audio.stop_playback()
            if fd is not None:
                os.close(fd)
        stopped.wait(1)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['daemon', 'devices', 'probe', 'record'])
    parser.add_argument('--capture-device', default='plughw:CARD=aic3104,DEV=0')
    parser.add_argument('--playback-device', default='plughw:CARD=aic3104,DEV=0')
    parser.add_argument('--channel', type=int, choices=[0, 1], default=1)
    parser.add_argument('--pitch', type=float, default=1.25, help='pitch AND speed ratio; 1.0 = original')
    parser.add_argument('--maximum', type=int, default=10)
    parser.add_argument('--seconds', type=float, default=4)
    parser.add_argument('--input', help='optional fixed /dev/input/eventN')
    parser.add_argument('--trigger-mode', choices=['toggle', 'hold'], default='toggle')
    parser.add_argument('--voice-mode', choices=['off', 'shadow', 'actions'], default='off')
    parser.add_argument('--voice-model', default='/opt/duck-echo/models/vosk-model-small-cn-0.22')
    parser.add_argument('--speech-deps', default='/opt/duck-echo/asr-deps')
    args = parser.parse_args(argv)
    if not 0.75 <= args.pitch <= 1.6:
        parser.error('--pitch must be between 0.75 and 1.6')
    if not 1 <= args.maximum <= 10 or not 0.25 <= args.seconds <= args.maximum:
        parser.error('require 1 <= maximum <= 10 and 0.25 <= seconds <= maximum')
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    if not sys.platform.startswith('linux'):
        parser.error('runtime requires 64-bit Linux on the duck; unit tests also run on Windows')
    if args.action == 'devices':
        print(json.dumps(devices(), ensure_ascii=False, indent=2))
        return 0
    stopped = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stopped.set())
    signal.signal(signal.SIGINT, lambda *_: stopped.set())
    audio = AlsaAudio(args.capture_device, args.playback_device, args.channel, args.pitch, args.maximum)
    if args.action == 'daemon' and args.trigger_mode == 'toggle':
        from continuous_audio import ContinuousAudio
        audio = ContinuousAudio(audio)
    if args.action == 'daemon' and args.voice_mode != 'off':
        from speech_control import MandarinRecognizer, VoiceControl
        from voice_commands import PostureCommands, RobotClient
        robot = RobotClient()
        def cue(accepted):
            robot.call('robot.sound', {'tag': 'chirp' if accepted else 'inquire'})
        if args.trigger_mode == 'toggle':
            raw_cue = cue
            cue = lambda accepted: audio.command_cue(raw_cue, accepted)
        audio.voice = VoiceControl(
            lambda: MandarinRecognizer(args.voice_model, args.speech_deps),
            PostureCommands(robot), audio.play, execute_commands=args.voice_mode == 'actions', cue=cue)
    try:
        if args.action == 'daemon':
            daemon(audio, stopped, args.input, trigger_mode=args.trigger_mode)
            return 0
        audio.start()
        until = time.monotonic() + args.seconds
        while time.monotonic() < until and not stopped.is_set() and not audio.expired():
            stopped.wait(0.05)
        result = audio.stop(play=args.action == 'record' and not stopped.is_set())
        played = audio.finish_playback()
        if args.action == 'record' and result is not None:
            result['playback_ok'] = played
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result and result['ok'] and (args.action != 'record' or played) else 2
    finally:
        if audio.voice is not None:
            audio.voice.close()
        audio.close()


if __name__ == '__main__':
    sys.exit(main())
