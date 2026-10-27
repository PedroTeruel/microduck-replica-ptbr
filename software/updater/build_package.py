"""Build a frozen Git runtime whitelist and sign using publisher's minisign CLI."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import tarfile
import importlib.util
from package import runtime_path, valid_version

def build(repo, ref, version, output, signing_key, public_key, minisign='minisign', changelog='', zstd='zstd', native_robotd=None):
    if not valid_version(version): raise ValueError('version must be SemVer')
    revision=subprocess.check_output(['git','-C',str(repo),'rev-parse','--verify',ref+'^{commit}'],text=True).strip()
    frozen=subprocess.check_output(['git','-C',str(repo),'archive','--format=tar',revision,'software/studio','software/duck-echo'])
    native_files={}
    if native_robotd is not None:
        path=Path(native_robotd)
        if path.is_symlink() or not path.is_file() or path.stat().st_size>32*1024*1024:
            raise ValueError('native input must be a bounded regular file')
        spec=importlib.util.spec_from_file_location('publisher_native_manifest',Path(__file__).resolve().parents[1]/'studio/deploy/native_update.py')
        native=importlib.util.module_from_spec(spec);spec.loader.exec_module(native)
        data=path.read_bytes(); native_manifest=native.native_manifest(version,data)
        native.validate_payload(data,native_manifest,version)
        native_files={'studio/deploy/native/robotd':data,
                      'studio/deploy/native/manifest.json':(json.dumps(native_manifest,sort_keys=True,indent=2)+'\n').encode()}
    output=Path(output); output.mkdir(parents=True,exist_ok=True)
    artifact=output/f'{version}.tar.zst'; files={}; tar_buffer=io.BytesIO()
    with tarfile.open(fileobj=tar_buffer,mode='w') as dest:
        with tarfile.open(fileobj=io.BytesIO(frozen)) as source:
            for item in source:
                name=runtime_path(item.name)
                if not name: continue
                if not item.isfile():
                    if item.isdir(): continue
                    raise ValueError('runtime whitelist contains a non-regular file')
                data=source.extractfile(item).read(); files[name]=hashlib.sha256(data).hexdigest()
                if name in native_files: raise ValueError('native payload must only come from the explicit publisher input')
                info=tarfile.TarInfo(name); info.size=len(data); info.mode=0o755 if name.endswith('microduck-helper') else 0o644
                dest.addfile(info,io.BytesIO(data))
        if native_files:
            if any(name not in files for name in ('studio/deploy/microduck-helper','studio/deploy/native_update.py')):
                raise ValueError('frozen source does not contain the native updater')
            for name,data in native_files.items():
                files[name]=hashlib.sha256(data).hexdigest()
                info=tarfile.TarInfo(name);info.size=len(data);info.mode=0o755 if name.endswith('/robotd') else 0o644
                dest.addfile(info,io.BytesIO(data))
        provenance=json.dumps({'version':version,'source_revision':revision,'files':files},sort_keys=True,indent=2).encode()
        info=tarfile.TarInfo('suite-version.json'); info.size=len(provenance); info.mode=0o644
        dest.addfile(info,io.BytesIO(provenance))
    with artifact.open('wb') as stream:
        if shutil.which(zstd):
            subprocess.run([zstd,'-q','-T1','-10','-c'],input=tar_buffer.getvalue(),stdout=stream,check=True)
        else:
            import ctypes
            from ctypes.util import find_library
            library=ctypes.CDLL(find_library('zstd') or 'libzstd.so.1')
            library.ZSTD_compressBound.argtypes=[ctypes.c_size_t]; library.ZSTD_compressBound.restype=ctypes.c_size_t
            library.ZSTD_compress.argtypes=[ctypes.c_void_p,ctypes.c_size_t,ctypes.c_void_p,ctypes.c_size_t,ctypes.c_int]
            library.ZSTD_compress.restype=ctypes.c_size_t
            library.ZSTD_isError.argtypes=[ctypes.c_size_t]; library.ZSTD_isError.restype=ctypes.c_uint
            data=tar_buffer.getvalue(); capacity=library.ZSTD_compressBound(len(data)); buffer=ctypes.create_string_buffer(capacity)
            size=library.ZSTD_compress(buffer,capacity,data,len(data),10)
            if library.ZSTD_isError(size): raise RuntimeError('zstd compression failed')
            stream.write(buffer.raw[:size])
    manifest=output/f'{version}.manifest.json'
    manifest.write_text(json.dumps({'channel':'software','version':version,'url':artifact.name,
        'sig_url':artifact.name+'.minisig','sha256':hashlib.sha256(artifact.read_bytes()).hexdigest(),
        'size':artifact.stat().st_size,'min_hw_rev':1,'schema_version':1,'source_revision':revision,
        'changelog':changelog,'compatibility':{'architecture':'aarch64','python':'3.13','robotd':'HD1910 motion/control'}},
        sort_keys=True,indent=2)+'\n',encoding='utf-8')
    # Keys are explicit paths and are never included in archives or command output.
    for path in (manifest,artifact):
        subprocess.run([minisign,'-S','-s',str(signing_key),'-m',str(path),'-x',str(path)+'.minisig'],check=True,capture_output=True)
        subprocess.run([minisign,'-V','-p',str(public_key),'-m',str(path),'-x',str(path)+'.minisig'],check=True,capture_output=True)
    outer=output/f'{version}.software-update.tar'
    with tarfile.open(outer,'w',format=tarfile.USTAR_FORMAT) as archive:
        for path in (manifest,Path(str(manifest)+'.minisig'),artifact,Path(str(artifact)+'.minisig')):
            info=tarfile.TarInfo(path.name);info.size=path.stat().st_size;info.mode=0o644
            with path.open('rb') as stream:archive.addfile(info,stream)
    return outer

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('repo','ref','version','output','signing-key','public-key'): parser.add_argument('--'+name,required=True)
    parser.add_argument('--minisign',default='minisign'); parser.add_argument('--zstd',default='zstd'); parser.add_argument('--changelog',default='')
    parser.add_argument('--native-robotd',help='Optional reviewed Qinmo AArch64 ELF; all identities are fixed and verified')
    args=vars(parser.parse_args())
    print(build(**{key.replace('-','_'):value for key,value in args.items()}))
