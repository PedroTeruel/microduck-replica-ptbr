#!/usr/bin/python3
"""Constrain the legacy engine's hardcoded deferred base-daemon restarts."""
import os
from pathlib import Path
import sys

def allowed(program,arguments,offline=False):
    if offline: return False
    if program!='systemctl' or not arguments: return False
    if arguments[0] in {'show','is-active','is-enabled'}: return True
    return (arguments[0] in {'restart','reset-failed'} and len(arguments)>1
        and all(name.removesuffix('.service') in {'microduck-studio','duck-echo'} for name in arguments[1:]))

if __name__=='__main__':
    if not allowed(Path(sys.argv[0]).name,sys.argv[1:],os.environ.get('MICRODUCK_OFFLINE_BUILD')=='1'):
        print('microduck engine service boundary denied unrelated/deferred service operation',file=sys.stderr)
        sys.exit(1)
    os.execv('/usr/bin/systemctl',['/usr/bin/systemctl',*sys.argv[1:]])
