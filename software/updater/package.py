"""Distribution envelope checks only. Signature/transaction validation belongs to updaterd."""
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import tarfile
import tempfile

MAX_OUTER = 160 * 1024 * 1024
MAX_ARTIFACT = 128 * 1024 * 1024
MAX_METADATA = 1024 * 1024
_VERSION = re.compile(r'(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?\Z')
VOICE = {'duck_echo.py','audio_control.py','continuous_audio.py','music_feel.py',
         'music_interaction.py','speech_control.py','voice_commands.py','duck-echo.service','install.py'}

class PackageError(ValueError): pass

def valid_version(version):
    if not isinstance(version,str) or len(version)>80: return False
    match = _VERSION.fullmatch(version)
    return bool(match and not any(p.isdigit() and len(p)>1 and p[0]=='0' for p in (match[4] or '').split('.')))

def runtime_path(name):
    parts = PurePosixPath(name).parts
    if any(p in {'__pycache__','state','logs','cache','tests','dev','.git'} for p in parts): return None
    if name.startswith('software/studio/'):
        rel=name[len('software/studio/'):]
        allowed=(rel=='run.py' or rel.startswith(('studio/','web/','deps/','deploy/')))
        if allowed and not rel.endswith(('.pyc','.pyo','.key','.pem','.log')): return 'studio/'+rel
    if name.startswith('software/duck-echo/') and name.rsplit('/',1)[-1] in VOICE:
        return 'duck-echo/'+name.rsplit('/',1)[-1]
    return None

def unpack_outer(source, destination):
    """Atomically stage exactly four regular files; staged is still UNTRUSTED."""
    destination=Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if destination.exists(): raise PackageError('cache destination already exists')
    temporary=Path(tempfile.mkdtemp(prefix='.unverified-',dir=destination.parent))
    try:
        names=set(); consumed=0
        def read(size):
            nonlocal consumed
            if consumed+size>MAX_OUTER:raise PackageError('distribution exceeds size limit')
            data=source.read(size);consumed+=len(data)
            return data
        while True:
            header=read(512)
            if len(header)!=512:raise PackageError('truncated distribution header')
            if header==bytes(512):
                while block:=read(min(1024*1024,MAX_OUTER-consumed)):
                    if any(block):raise PackageError('unexpected trailing distribution data')
                break
            # Deliberately reject PAX/GNU extensions, so a hostile long-name
            # header cannot allocate unbounded metadata before our member checks.
            member=tarfile.TarInfo.frombuf(header,'utf-8','strict');name=member.name
            if (len(names)>=4 or name in names or member.type not in (tarfile.REGTYPE,tarfile.AREGTYPE)
                or '/' in name or '\\' in name or name.startswith('.') or member.size<0):
                raise PackageError('unsafe distribution member')
            maximum=MAX_ARTIFACT if name.endswith(('.tar.gz','.tar.zst')) else MAX_METADATA
            if member.size>maximum:raise PackageError('distribution exceeds size limit')
            names.add(name)
            with open(temporary/name,'xb') as dst:
                os.chmod(temporary/name,0o600);remaining=member.size
                while remaining:
                    block=read(min(1024*1024,remaining))
                    if not block:raise PackageError('truncated distribution member')
                    dst.write(block);remaining-=len(block)
            padding=(-member.size)%512
            if len(read(padding))!=padding:raise PackageError('truncated distribution padding')
        manifests=[n for n in names if n.endswith('.manifest.json')]
        if len(manifests)!=1: raise PackageError('expected one manifest')
        manifest=json.loads((temporary/manifests[0]).read_bytes())
        version=manifest.get('version')
        artifact=manifest.get('url')
        if (not valid_version(version) or manifest.get('channel')!='software'
            or artifact not in (f'{version}.tar.gz',f'{version}.tar.zst')
            or manifest.get('sig_url')!=artifact+'.minisig'
            or manifests[0]!=f'{version}.manifest.json'
            or names!={manifests[0],manifests[0]+'.minisig',artifact,artifact+'.minisig'}
            or type(manifest.get('size')) is not int or manifest['size']!=(temporary/artifact).stat().st_size
            or not re.fullmatch('[0-9a-f]{64}',manifest.get('sha256',''))):
            raise PackageError('invalid software manifest envelope')
        temporary.rename(destination)
        return manifest
    except (tarfile.TarError,OSError,ValueError,TypeError,AttributeError,KeyError) as error:
        if isinstance(error,PackageError): raise
        raise PackageError('invalid distribution envelope') from error
    finally:
        if temporary.exists(): shutil.rmtree(temporary)
