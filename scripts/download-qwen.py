"""Resumable official ModelScope GGUF download, pinned to Qwen's HF SHA256."""
import concurrent.futures
import hashlib
import json
import time
import urllib.request
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
URL='https://modelscope.cn/models/Qwen/Qwen3-4B-GGUF/resolve/master/Qwen3-4B-Q4_K_M.gguf'
SIZE=2497280256
SHA='7485fe6f11af29433bc51cab58009521f205840f5b4ae3a32fa7f92e8534fdf5'
CHUNK=64*1024*1024
PARTS=ROOT/'downloads/qwen-parts'
TARGET=ROOT/'models/qwen3/Qwen3-4B-Q4_K_M.gguf'


def chunk(index):
    start=index*CHUNK;end=min(SIZE,start+CHUNK)-1
    path=PARTS/f'part-{index:03}'
    for attempt in range(6):
        have=path.stat().st_size if path.exists() else 0
        if have==end-start+1:return path
        if have>end-start+1:raise RuntimeError('Oversized download part')
        try:
            request=urllib.request.Request(URL,headers={'Range':f'bytes={start+have}-{end}','Accept-Encoding':'identity'})
            with urllib.request.urlopen(request,timeout=90) as response:
                if response.status!=206 or not response.headers.get('Content-Range','').startswith(f'bytes {start+have}-'):
                    raise RuntimeError('Source did not honor byte range')
                with path.open('ab') as output:
                    remaining=end-start+1-have
                    while remaining:
                        data=response.read(min(262144,remaining))
                        if not data:raise RuntimeError('Interrupted model download')
                        output.write(data);remaining-=len(data)
            return path
        except Exception:
            if attempt==5:raise
            time.sleep(min(30,2**attempt))


def main():
    PARTS.mkdir(parents=True,exist_ok=True);TARGET.parent.mkdir(parents=True,exist_ok=True)
    count=(SIZE+CHUNK-1)//CHUNK
    with concurrent.futures.ThreadPoolExecutor(max_workers=16) as pool:
        futures=[pool.submit(chunk,i) for i in range(count)]
        while not all(future.done() for future in futures):
            total=sum(path.stat().st_size for path in PARTS.glob('part-*'))
            print(json.dumps({'downloaded_mb':round(total/1024**2,1),'total_mb':round(SIZE/1024**2,1),'percent':round(100*total/SIZE,1)}),flush=True)
            time.sleep(20)
        paths=[future.result() for future in futures]
    digest=hashlib.sha256();temporary=TARGET.with_suffix('.verified.part')
    with temporary.open('wb') as output:
        for path in paths:
            with path.open('rb') as source:
                while data:=source.read(1024*1024):digest.update(data);output.write(data)
    if temporary.stat().st_size!=SIZE or digest.hexdigest()!=SHA:raise RuntimeError('GGUF checksum mismatch; not loading model')
    temporary.replace(TARGET)
    print(json.dumps({'status':'verified','path':str(TARGET),'sha256':SHA}),flush=True)


if __name__=='__main__':main()
