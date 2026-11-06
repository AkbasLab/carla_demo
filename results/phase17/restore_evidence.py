"""Restore complete Phase 17 pilot evidence from checksum-verified archive parts."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import tempfile
import zipfile


def restore(batch,output_dir=None):
    root=Path(__file__).resolve().parent/'evidence'
    manifest=json.loads((root/'archives.json').read_text())
    if batch not in manifest['batches']:raise ValueError('Unknown pilot batch')
    spec=manifest['batches'][batch]
    with tempfile.TemporaryDirectory() as temp:
        archive=Path(temp)/'evidence.zip';combined=hashlib.sha256()
        with archive.open('wb') as target:
            for part in spec['parts']:
                source=root/part['name'];data=source.read_bytes()
                if len(data)!=part['bytes'] or hashlib.sha256(data).hexdigest()!=part['sha256']:
                    raise ValueError('Archive part checksum mismatch: '+part['name'])
                target.write(data);combined.update(data)
        if combined.hexdigest()!=spec['archive_sha256']:raise ValueError('Combined archive checksum mismatch')
        with zipfile.ZipFile(archive) as z:
            if z.testzip() is not None:raise ValueError('Archive CRC failed')
            members=z.infolist()
            if len(members)!=spec['file_count']:raise ValueError('Archive file count mismatch')
            for info in members:
                name=PurePosixPath(info.filename)
                if name.is_absolute() or '..' in name.parts or '\\' in info.filename or ((info.external_attr>>16)&0o170000)==0o120000:
                    raise ValueError('Unsafe archive member: '+info.filename)
            if output_dir is not None:
                out=Path(output_dir)
                if out.exists() and any(out.iterdir()):raise ValueError('Restore into a fresh directory')
                out.mkdir(parents=True,exist_ok=True)
                z.extractall(out)
    return dict(batch=batch,files=spec['file_count'],verified=True,restored_to=str(output_dir) if output_dir else None)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--batch',required=True,choices=['validation_run1','validation_run2'])
    p.add_argument('--output-dir',help='Omit to verify checksums without extracting')
    a=p.parse_args();print(json.dumps(restore(a.batch,a.output_dir),indent=2))
