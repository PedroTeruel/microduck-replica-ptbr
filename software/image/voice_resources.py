"""Build offline, immutable ARM64/cp313 voice resources from publisher inputs."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import stat
import tempfile
import zipfile

MODEL_NAME = 'vosk-model-small-cn-0.22'
MODEL_URL = 'https://alphacephei.com/vosk/models/' + MODEL_NAME + '.zip'
MODEL_SHA256 = '3af8b0e7e0f835ae9d414ce5df580237a3cfb08d586c9fbbb0f7ff29ad5b14ba'


def digest(path):
    with Path(path).open('rb') as source:
        return hashlib.file_digest(source, 'sha256').hexdigest()


def entries(archive, prefix, seen, budget):
    result = []
    for info in archive.infolist():
        name = info.filename
        parts = PurePosixPath(name).parts
        kind = stat.S_IFMT(info.external_attr >> 16)
        if (not name or name.startswith('/') or '\\' in name or ':' in name
                or '\x00' in name or '..' in parts or '.' in name.split('/')
                or '//' in name or kind not in (0, stat.S_IFREG, stat.S_IFDIR)):
            raise ValueError('unsafe archive member')
        if info.is_dir():
            continue
        destination = prefix + '/' + name
        if destination in seen:
            raise ValueError('duplicate archive file')
        seen.add(destination)
        budget[0] += info.file_size
        budget[1] += 1
        if budget[0] > budget[2] or budget[1] > 20000:
            raise ValueError('archive expansion limit exceeded')
        result.append((info, destination))
    return result


def prepare(model_archive, wheels_dir, output, *, expected_model_sha256=MODEL_SHA256,
            max_bytes=512*1024*1024):
    model_archive, wheels_dir, output = map(Path, (model_archive, wheels_dir, output))
    if output.exists() or output.is_symlink():
        raise FileExistsError('output already exists')
    if digest(model_archive) != expected_model_sha256:
        raise ValueError('model archive checksum mismatch')
    wheels = sorted(wheels_dir.glob('*.whl'))
    if not wheels or not any(w.name.startswith('vosk-0.3.45-') for w in wheels):
        raise ValueError('target Vosk wheel missing')
    for wheel in wheels:
        try:
            python_tag, abi, architecture = wheel.stem.rsplit('-', 3)[-3:]
        except ValueError:
            raise ValueError('invalid target wheel') from None
        if (python_tag not in ('py3', 'cp313') or abi not in ('none', 'cp313')
                or architecture != 'any' and not all(
                    tag.endswith('_aarch64') for tag in architecture.split('.'))):
            raise ValueError('wheel target must be linux ARM64/cp313: ' + wheel.name)

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix='.voice-resources-', dir=output.parent))
    try:
        seen, budget = set(), [0, 0, max_bytes]
        for archive_path, prefix in [(model_archive, 'models'), *[(w, 'asr-deps') for w in wheels]]:
            with zipfile.ZipFile(archive_path) as archive:
                members = entries(archive, prefix, seen, budget)
                if prefix == 'models' and any(
                        not name.startswith('models/'+MODEL_NAME+'/') for _, name in members):
                    raise ValueError('unsafe model archive root')
                for info, relative in members:
                    destination = temporary / relative
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(info) as source, destination.open('xb') as target:
                        shutil.copyfileobj(source, target, length=65536)
                    destination.chmod(0o644)
        if not (temporary/'models'/MODEL_NAME/'am/final.mdl').is_file():
            raise ValueError('model acoustic file missing')
        files = [{'path': p.relative_to(temporary).as_posix(), 'size':p.stat().st_size, 'sha256':digest(p)}
                 for p in sorted(temporary.rglob('*')) if p.is_file()]
        result = {'schema':1, 'target':'linux-aarch64-cp313',
                  'model':{'name':MODEL_NAME,'url':MODEL_URL,'sha256':expected_model_sha256,
                           'license':'Apache-2.0','license_source':'https://alphacephei.com/vosk/models'},
                  'wheels':[{'name':w.name,'sha256':digest(w)} for w in wheels], 'files':files}
        (temporary/'resources-manifest.json').write_text(
            json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
        for folder in temporary.rglob('*'):
            if folder.is_dir():
                folder.chmod(0o755)
        temporary.chmod(0o755)
        temporary.rename(output)
        return result
    finally:
        if temporary.exists():
            shutil.rmtree(temporary)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--model-archive', required=True, type=Path)
    parser.add_argument('--wheels', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    result = prepare(args.model_archive,args.wheels,args.output)
    print(json.dumps({'ok':True,'target':result['target'],'files':len(result['files']),
                      'wheels':len(result['wheels']),'bytes':sum(f['size'] for f in result['files'])}))


if __name__ == '__main__':
    main()
