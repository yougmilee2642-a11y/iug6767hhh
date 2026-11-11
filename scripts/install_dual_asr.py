"""Download audited official weights atomically. No network is needed at runtime."""
import hashlib
import json
import tarfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parents[1]
TONE_REVISION = '106f3b0b32a9e107eb613312e4ebc61ff3d53926'
RELEASE = 'https://github.com/k2-fsa/sherpa-onnx/releases/download/'
FILES = [
    ('tone/model.onnx', f'https://huggingface.co/t-tech/T-one/resolve/{TONE_REVISION}/model.onnx', None),
    ('gigaam/v3_rnnt.ckpt', 'https://cdn.chatwm.opensmodel.sberdevices.ru/GigaAM/v3_rnnt.ckpt', '0fd2c9a1ff66abd8d32a3a07f7592815'),
    ('speaker/wespeaker_en_voxceleb_resnet34_LM.onnx', RELEASE+'speaker-recongition-models/wespeaker_en_voxceleb_resnet34_LM.onnx', None),
    ('speaker/segmentation.tar.bz2', RELEASE+'speaker-segmentation-models/sherpa-onnx-pyannote-segmentation-3-0.tar.bz2', None),
]

def ranged_download(url, temp):
    # This CDN sometimes stalls on a single large response. Validate every range.
    with requests.get(url, headers={'Range':'bytes=0-0'}, timeout=(30,30)) as probe:
        probe.raise_for_status()
        size = int(probe.headers['Content-Range'].split('/')[-1])
    chunk_size = 4*1024*1024
    offsets = list(range(0,size,chunk_size))
    def fetch(start):
        end = min(size-1,start+chunk_size-1)
        for attempt in range(4):
            try:
                with requests.get(url, headers={'Range':f'bytes={start}-{end}'}, timeout=(30,45)) as response:
                    response.raise_for_status()
                    if response.status_code != 206 or response.headers.get('Content-Range') != f'bytes {start}-{end}/{size}':
                        raise RuntimeError('Unexpected CDN byte range')
                    content = response.content
                    if len(content) != end-start+1: raise RuntimeError('Truncated range')
                    return content
            except Exception:
                if attempt == 3: raise
                time.sleep(attempt+1)
    with ThreadPoolExecutor(max_workers=6) as pool, temp.open('wb') as out:
        for index, content in enumerate(pool.map(fetch,offsets),1):
            out.write(content)
            if index%10==0: print(f'GigaAM: {index}/{len(offsets)} parts',flush=True)

def download(item):
    relative, url, expected = item
    path = ROOT/'models'/relative
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.is_file():
        temp = path.with_suffix(path.suffix+'.part')
        if 'GigaAM/' in url:
            ranged_download(url,temp)
        else:
          with requests.get(url, stream=True, timeout=(30, 120)) as response:
            response.raise_for_status()
            size = int(response.headers.get('Content-Length', 0))
            print(f'Downloading {relative}: {size/1024**2:.1f} MB', flush=True)
            count = 0
            with temp.open('wb') as out:
                for chunk in response.iter_content(1024*1024):
                    out.write(chunk); count += len(chunk)
            if size and count != size:
                raise RuntimeError(f'Truncated download: {relative}')
        if expected and hashlib.md5(temp.read_bytes()).hexdigest() != expected:
            raise RuntimeError(f'Checksum mismatch: {relative}')
        temp.replace(path)
    if expected and hashlib.md5(path.read_bytes()).hexdigest() != expected:
        raise RuntimeError(f'Checksum mismatch: {relative}')
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    print(f'Ready {relative}: {path.stat().st_size/1024**2:.1f} MB', flush=True)
    return dict(file=relative, url=url, sha256=digest, bytes=path.stat().st_size)

if __name__ == '__main__':
    with ThreadPoolExecutor(max_workers=4) as pool:
        manifest = list(pool.map(download, FILES))
    # Extract only the expected model; never extract arbitrary archive paths.
    with tarfile.open(ROOT/'models/speaker/segmentation.tar.bz2') as archive:
        member = archive.getmember('sherpa-onnx-pyannote-segmentation-3-0/model.onnx')
        with archive.extractfile(member) as src, (ROOT/'models/speaker/segmentation.onnx').open('wb') as out:
            out.write(src.read())
    (ROOT/'models/dual-asr-manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    print('All local ASR and speaker weights installed.', flush=True)
