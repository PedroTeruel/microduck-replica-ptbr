"""Isolated browser launcher: real update coordinator, explicit fake transaction engine."""
import importlib.util
import json
import os
from pathlib import Path
import runpy
import sys
import threading

root=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(root/'deps'),str(root)]
spec=importlib.util.spec_from_file_location('update_fixture',root.parent/'updater/tests/e2e_fixture.py')
fixture_module=importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixture_module)
output=Path(os.environ['UPDATE_E2E_DIR'])
fixture=fixture_module.Fixture(output/'controller',os.environ['UPDATE_E2E_PACKAGE'],marker=output/'installing')
record_lock=threading.Lock()
original_call=fixture.engine.call
def record(method,params=None,progress=None):
    with record_lock,(output/'engine.jsonl').open('a',encoding='utf-8') as stream:
        stream.write(json.dumps({'method':method,'params':params},ensure_ascii=False)+'\n')
    return original_call(method,params,progress)
fixture.engine.call=record
server=fixture.serve(int(os.environ['UPDATE_FIXTURE_PORT']))

from studio import app as app_module
from studio.updates import Updates
original_build=app_module.build_app
def build(*args,**kwargs):
    kwargs['updates']=Updates(address=f'tcp:127.0.0.1:{server.server_address[1]}',
        marker=output/'installing',readiness=output/'readiness.sock')
    return original_build(*args,**kwargs)
app_module.build_app=build
runpy.run_path(str(root/'tests/audio_fixture_launcher.py'),run_name='__main__')
