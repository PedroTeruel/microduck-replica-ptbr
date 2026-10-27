#!/usr/bin/env python3
"""Prepare isolated local Mandarin ASR, then select echo/shadow/action mode."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile

from install import DEFAULTS, DESTINATION, STATE, InstallationRollback, run

MODEL_NAME = 'vosk-model-small-cn-0.22'
MODEL_URL = 'https://alphacephei.com/vosk/models/' + MODEL_NAME + '.zip'
MODEL_SHA256 = '3af8b0e7e0f835ae9d414ce5df580237a3cfb08d586c9fbbb0f7ff29ad5b14ba'


def extract_model(archive, destination):
    if hashlib.sha256(archive.read_bytes()).hexdigest() != MODEL_SHA256:
        raise RuntimeError('Chinese model archive checksum mismatch')
    with zipfile.ZipFile(archive) as source:
        for name in source.namelist():
            if not (destination / name).resolve().is_relative_to(destination.resolve()):
                raise RuntimeError('unsafe model archive member')
        source.extractall(destination)


def unpack_wheels(folder, destination):
    wheels = sorted(folder.glob('*.whl'))
    if not wheels:
        raise RuntimeError('no dependency wheels supplied')
    destination.mkdir(parents=True, exist_ok=True)
    for wheel in wheels:
        python_tag, abi, architecture = wheel.stem.rsplit('-', 3)[-3:]
        current = 'cp' + str(sys.version_info.major) + str(sys.version_info.minor)
        if python_tag != 'py3' and 'py3' not in python_tag.split('.') and python_tag != current:
            raise RuntimeError('dependency wheel Python version mismatch: ' + wheel.name)
        if architecture != 'any' and platform.machine().lower() not in architecture:
            raise RuntimeError('dependency wheel architecture mismatch: ' + wheel.name)
        with zipfile.ZipFile(wheel) as source:
            for name in source.namelist():
                if not (destination / name).resolve().is_relative_to(destination.resolve()):
                    raise RuntimeError('unsafe dependency wheel member')
            source.extractall(destination)


def install_dependencies(destination, wheels=None):
    # --target touches neither distro packages nor the robot's Python paths.
    with tempfile.TemporaryDirectory(prefix='asr-install-', dir=DESTINATION) as folder:
        temporary = Path(folder) / 'deps'
        if wheels is not None:
            unpack_wheels(wheels, temporary)
        else:
            subprocess.run([sys.executable, '-m', 'pip', 'install', '--target', str(temporary),
                            '--disable-pip-version-check', 'vosk==0.3.45'], check=True, timeout=240)
        verify = 'import sys;sys.path.insert(0,sys.argv[1]);from vosk import Model;print("Vosk import OK")'
        subprocess.run([sys.executable, '-c', verify, str(temporary)], check=True, timeout=20)
        previous = destination.with_name(destination.name + '-previous')
        if previous.exists():
            raise RuntimeError('previous dependency backup exists; preserve or move it before upgrading speech')
        if destination.exists():
            destination.rename(previous)
        temporary.rename(destination)


def activate(mode):
    with InstallationRollback('aic3104', STATE / 'mixer-before.json'):
        text = DEFAULTS.read_text() if DEFAULTS.exists() else ''
        lines = [line for line in text.splitlines() if not line.startswith('ECHO_VOICE_MODE=')]
        DEFAULTS.write_text('\n'.join(lines) + '\nECHO_VOICE_MODE=' + mode + '\n')
        run(['systemctl', 'restart', 'duck-echo.service'])
        run(['systemctl', 'is-active', 'duck-echo.service'])


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=['off', 'shadow', 'actions'], default='shadow')
    parser.add_argument('--archive', type=Path, help='already-downloaded official model ZIP')
    parser.add_argument('--wheels', type=Path, help='offline wheels matching this Python and architecture')
    parser.add_argument('--prepare-only', action='store_true', help='install and verify model; keep current service mode')
    args = parser.parse_args(argv)
    if sys.platform != 'linux' or os.geteuid() != 0:
        parser.error('run with sudo python3 /opt/duck-echo/install_speech.py')
    if args.mode != 'off' or args.prepare_only:
        dependencies = DESTINATION / 'asr-deps'
        if not (dependencies / 'vosk/__init__.py').is_file():
            install_dependencies(dependencies, args.wheels)
        model = DESTINATION / 'models' / MODEL_NAME
        if not (model / 'am/final.mdl').is_file():
            model.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix='asr-model-', dir=DESTINATION) as folder:
                temporary = Path(folder)
                archive = args.archive
                if archive is None:
                    archive = temporary / (MODEL_NAME + '.zip')
                    print('Downloading official local Chinese model', flush=True)
                    with urllib.request.urlopen(MODEL_URL, timeout=30) as source, archive.open('wb') as output:
                        shutil.copyfileobj(source, output)
                extract_model(archive, temporary)
                (temporary / MODEL_NAME).rename(model)
        # Model loading is verified in a separate process before changing service mode.
        check = ('from speech_control import MandarinRecognizer;import sys;'
                 'r=MandarinRecognizer(sys.argv[1],sys.argv[2]);'
                 'print(r.recognize(bytes(48000*4)))')
        subprocess.run([sys.executable, '-c', check, str(model), str(dependencies)],
                       cwd=DESTINATION, check=True, timeout=30)
    if not args.prepare_only:
        activate(args.mode)
        print(json.dumps({'voice_mode': args.mode, 'service': 'duck-echo', 'robotd_restarted': False}))
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print('Speech setup failed:', error, file=sys.stderr)
        sys.exit(1)
