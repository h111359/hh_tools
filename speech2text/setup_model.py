"""Explicit model download only; ordinary transcription never calls this module."""
import argparse
import hashlib
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
os.environ['HF_HOME'] = str(ROOT / 'cache/huggingface')
os.environ['HF_HUB_DISABLE_TELEMETRY'] = '1'
from huggingface_hub import HfApi, hf_hub_download


def digest(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--repo', default='Systran/faster-whisper-base')
    p.add_argument('--revision', default='ebe41f70d5b6dfa9166e2c581c45c9c0cfc57b66')
    p.add_argument('--destination', default='base')
    a = p.parse_args()
    dest = ROOT / 'models' / a.destination
    dest.mkdir(parents=True, exist_ok=True)
    receipt = dest / 'receipt.json'
    if receipt.exists():
        r = json.loads(receipt.read_text())
        if r['repo'] == a.repo and r['revision'] == a.revision and all(
                (dest / n).is_file() and digest(dest / n) == h for n, h in r['sha256'].items()):
            print('Model already present; checksums verified:', dest)
            return
        raise SystemExit('Model receipt mismatch/corruption. Choose a fresh destination or explicitly remove the damaged model directory.')
    info = HfApi().model_info(a.repo, revision=a.revision, files_metadata=True)
    required = {'model.bin', 'config.json', 'tokenizer.json', 'vocabulary.txt'}
    hashes = {}
    for f in info.siblings:
        if f.rfilename not in required:
            continue
        print('Downloading/verifying', f.rfilename, flush=True)
        path = Path(hf_hub_download(a.repo, f.rfilename, revision=info.sha, local_dir=dest))
        sha = digest(path)
        if f.lfs and sha != f.lfs.sha256:
            raise RuntimeError('Upstream SHA256 mismatch: ' + f.rfilename)
        if not f.lfs:
            data = path.read_bytes()
            gitsha = hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()
            if gitsha != f.blob_id:
                raise RuntimeError('Upstream Git blob checksum mismatch: ' + f.rfilename)
        hashes[f.rfilename] = sha
    if set(hashes) != required:
        raise RuntimeError('Required model files missing')
    tmp = receipt.with_suffix('.tmp')
    tmp.write_text(json.dumps({'repo': a.repo, 'revision': info.sha, 'sha256': hashes}, indent=2))
    tmp.replace(receipt)
    print('Verified model ready:', dest)

if __name__ == '__main__':
    main()
