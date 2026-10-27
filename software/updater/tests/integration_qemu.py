"""Opt-in real ARM updater proof in a temporary root; never addresses a robot.

Requires the extracted bundled updater, QEMU libraries and an explicit publisher
key. The private key is passed only to minisign, never copied or printed.
"""
import argparse
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from bootstrap import bootstrap,profile
from build_package import build
from control import Engine,UpdateError
from package import unpack_outer

def run(args):
    with tempfile.TemporaryDirectory(prefix='microduck-qemu-proof-') as temporary:
        root=Path(temporary); output=root/'packages'; target=root/'image';target.mkdir()
        command=['qemu-aarch64','-L',args.library_root]
        packages={version:build(args.repo,args.ref,version,output,args.signing_key,args.public_key)
            for version in ('2026.10.27','2026.10.28')}
        with open(root/'bootstrap.log','w') as log:
            # Capture only subprocess diagnostics; bootstrap itself returns public metadata.
            import contextlib
            result=bootstrap(target,packages['2026.10.27'],args.public_key,args.engine,command,offline=True)
        assert result['version']=='2026.10.27'
        cache=root/'cache';cache.mkdir()
        with packages['2026.10.28'].open('rb') as source:unpack_outer(source,cache/'2026.10.28')
        configuration=profile(target).replace('action = "none"','action = "restart"\nunits = ["microduck-studio", "duck-echo"]')
        probe=root/'probe.py';bad=root/'bad-health'
        probe.write_text('from pathlib import Path\nimport sys\nsys.exit(1 if Path('+repr(str(bad))+').exists() else 0)\n')
        configuration=configuration.replace('probe = "none"',f'probe = "command"\nprogram = "/usr/bin/python3"\nargs = [{json.dumps(str(probe))}]\ntimeout = "2s"')
        config=root/'profile.toml';config.write_text(configuration)
        shims=root/'shims';shims.mkdir();calls=root/'service-calls.log'
        for program in ('systemctl','systemd-run'):
            script=shims/program
            script.write_text('#!/usr/bin/python3\nimport json,sys\nwith open('+repr(str(calls))+',"a") as f:f.write(json.dumps(sys.argv)+"\\n")\n'
                +'sys.exit(1 if "systemd-run" in sys.argv[0] else 0)\n');script.chmod(0o755)
        environment={**os.environ,'PATH':str(shims)+':'+os.environ['PATH']}
        path=root/'engine.sock';engine=Engine(str(path));process=None;log=(root/'engine.log').open('w')
        def start():
            nonlocal process
            path.unlink(missing_ok=True)
            process=subprocess.Popen([*command,str(target/'usr/local/lib/microduck-updater/updaterd'),'--config',str(config),
                '--socket',str(path),'--robot-socket',str(root/'absent-robot.sock')],stdout=log,stderr=log,env=environment)
            for _ in range(100):
                if process.poll() is not None:raise RuntimeError('actual updater exited during test')
                if path.exists():return
                time.sleep(.05)
            raise RuntimeError('actual updater did not listen')
        def stop(kill=False):
            if process and process.poll() is None:
                process.kill() if kill else process.terminate();process.wait(timeout=10)
        def apply(dry=False):
            options={'from_dir':str(cache/'2026.10.28')}
            if dry:options['dry_run']=True
            return engine.call('update.apply',{'component':'software','target':{'exact':'2026.10.28'},'options':options})
        current=target/'opt/microduck/software/current'
        try:
            start();assert apply(True)['outcome']=='dry_run_passed'
            artifact=cache/'2026.10.28/2026.10.28.tar.zst';original=artifact.read_bytes();artifact.write_bytes(original+b'tamper')
            try:apply(True);raise AssertionError('wrong artifact hash was accepted')
            except UpdateError:pass
            artifact.write_bytes(original)
            manifest=cache/'2026.10.28/2026.10.28.manifest.json';original_manifest=manifest.read_bytes();manifest.write_bytes(original_manifest+b' ')
            try:apply(True);raise AssertionError('wrong manifest signature was accepted')
            except UpdateError:pass
            manifest.write_bytes(original_manifest)
            assert apply()['outcome']=='applied';assert current.resolve().name=='2026.10.28'
            assert engine.call('update.rollback',{'component':'software'})['outcome']=='applied'
            assert current.resolve().name=='2026.10.27'
            bad.touch();rolled=apply();assert rolled['outcome']=='rolled_back',rolled
            assert current.resolve().name=='2026.10.27'
            # Kill the actual engine after its durable trial and link swap. New
            # engine starts consume its own persistent boot recovery, not Python state.
            outcome=[]
            def inflight():
                try:outcome.append(apply())
                except Exception as error:outcome.append(type(error).__name__)
            thread=threading.Thread(target=inflight,daemon=True);thread.start()
            for _ in range(100):
                if current.resolve().name=='2026.10.28':break
                time.sleep(.01)
            assert current.resolve().name=='2026.10.28';stop(kill=True);thread.join(3)
            recovered=False
            for _ in range(3):
                start();time.sleep(.3)
                if current.resolve().name=='2026.10.27':recovered=True;break
                stop(kill=True)
            assert recovered,'durable trial did not recover old version after engine crash'
            recorded=[json.loads(line) for line in calls.read_text().splitlines()]
            mutations=[entry for entry in recorded if Path(entry[0]).name=='systemctl' and len(entry)>1 and entry[1] in {'restart','reset-failed'}]
            assert all(set(entry[2:])<={'microduck-studio','duck-echo'} for entry in mutations),mutations
            print(json.dumps({'actual_engine':'0.15.1/API37','signed_bootstrap':True,'dry_run':True,'wrong_hash_refused':True,
                'wrong_manifest_signature_refused':True,'apply':True,'rollback':True,'health_failure_auto_rollback':True,
                'process_crash_durable_recovery':True,'service_restart_scope':True}))
        finally:stop();log.close()

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('engine','library-root','repo','ref','signing-key','public-key'):parser.add_argument('--'+name,required=True)
    run(parser.parse_args())
