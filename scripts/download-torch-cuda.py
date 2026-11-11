"""Resumable official wheel download with SHA256 verification; no package execution."""
import hashlib
import argparse
import html.parser
import json
import time
import threading
import signal
import sys
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import unquote, urlsplit, urldefrag
import httpx

ROOT=Path(__file__).resolve().parents[1]
NAME='torch-2.11.0+cu128-cp311-cp311-win_amd64.whl'
CHUNK=1024*1024


@contextmanager
def download_lock():
    folder=ROOT/'models/gpu-runtime';folder.mkdir(parents=True,exist_ok=True)
    with (folder/'download.lock').open('a+b') as lock:
        if lock.tell()==0:lock.write(b'0');lock.flush()
        lock.seek(0)
        try:
            if __import__('os').name=='nt':
                import msvcrt
                msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(lock.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
        except OSError:
            raise SystemExit('Download already running. Do not start a second copy.')
        yield


class Links(html.parser.HTMLParser):
    def __init__(self): super().__init__(); self.links=[]
    def handle_starttag(self, tag, attributes):
        if tag=='a': self.links.extend(value for key,value in attributes if key=='href')


def main():
    arguments=argparse.ArgumentParser()
    arguments.add_argument('--workers',type=int,default=16,choices=range(1,33))
    arguments.add_argument('--status',action='store_true')
    arguments.add_argument('--pause',action='store_true')
    options=arguments.parse_args()
    folder=ROOT/'models/gpu-runtime';folder.mkdir(parents=True,exist_ok=True)
    progress=folder/(NAME+'.progress.json');partial=folder/(NAME+'.partial');target=folder/NAME
    pause_request=folder/'download.pause'
    if options.pause:
        pause_request.touch()
        print('Pause requested. Completed parts will be saved; the server and Ollama are not stopped.')
        return
    if options.status:
        saved=json.loads(progress.read_text())
        downloaded=min(saved['size'],len(saved['done'])*CHUNK)
        print(json.dumps({'percent':round(100*downloaded/saved['size'],1),
            'downloaded_mb':round(downloaded/1e6),'total_mb':round(saved['size']/1e6),
            'pause_requested':pause_request.exists(),'verified_wheel_exists':target.exists()}))
        return
    if pause_request.exists():pause_request.unlink()
    with httpx.Client(trust_env=False,timeout=30,follow_redirects=True) as client:
        response=client.get('https://download.pytorch.org/whl/cu128/torch/');response.raise_for_status()
        parser=Links();parser.feed(response.text)
        link=next(link for link in parser.links if unquote(urlsplit(link).path).endswith('/'+NAME))
        url,fragment=urldefrag(link)
        if urlsplit(url).hostname not in {'download.pytorch.org','download-r2.pytorch.org'}:
            raise ValueError('Wheel must come from official PyTorch host')
        if not fragment.startswith('sha256='):raise ValueError('Missing official SHA256')
        digest=fragment.split('=',1)[1]
        response=client.get(url,headers={'Range':'bytes=0-0'})
        if response.status_code!=206:raise ValueError('Server does not support ranges')
        total=int(response.headers['content-range'].split('/')[-1])
    done=set()
    if partial.exists() and progress.exists():
        saved=json.loads(progress.read_text())
        if saved['sha256']==digest and saved['size']==total:done=set(saved['done'])
        else:raise ValueError('Existing partial belongs to another wheel; preserve it for review')
    if not partial.exists():
        with partial.open('wb') as stream:stream.truncate(total)
    began=time.monotonic()
    initial=len(done)
    clients=[]
    clients_lock=threading.Lock()
    thread_client=threading.local()
    stop=threading.Event()
    previous_signal=signal.getsignal(signal.SIGINT)
    def pause(_signum,_frame):
        stop.set()
        print('Pausing: saving completed parts; waiting for current requests only...',flush=True)
    signal.signal(signal.SIGINT,pause)
    def fetch(index):
        if pause_request.exists():stop.set()
        if stop.is_set():return index,None
        start=index*CHUNK;end=min(total,start+CHUNK)-1
        if not hasattr(thread_client,'client'):
            thread_client.client=httpx.Client(trust_env=False,timeout=20,follow_redirects=True,
                limits=httpx.Limits(max_connections=1,max_keepalive_connections=1))
            with clients_lock:clients.append(thread_client.client)
        for attempt in range(3):
            if pause_request.exists():stop.set()
            if stop.is_set():return index,None
            try:
                response=thread_client.client.get(url,headers={'Range':f'bytes={start}-{end}'})
                if response.status_code!=206 or response.headers.get('content-range')!=f'bytes {start}-{end}/{total}':
                    raise ValueError('Invalid content range')
                if len(response.content)!=end-start+1:raise ValueError('Incomplete range')
                return index,response.content
            except (httpx.HTTPError,ValueError):
                if attempt==2:raise
    count=(total+CHUNK-1)//CHUNK
    print(json.dumps({'size_mb':round(total/1e6),'resume_chunks':len(done),'chunks':count}),flush=True)
    failures=[]
    with ThreadPoolExecutor(max_workers=options.workers) as pool,partial.open('r+b') as stream:
        futures=[pool.submit(fetch,index) for index in range(count) if index not in done]
        last=0
        for future in as_completed(futures):
            if pause_request.exists():stop.set()
            try:index,data=future.result()
            except (httpx.HTTPError,ValueError) as error:
                failures.append(type(error).__name__)
                continue
            if data is None:continue
            stream.seek(index*CHUNK);stream.write(data);done.add(index)
            now=time.monotonic()
            if now-last>10 or len(done)==count:
                stream.flush()
                progress.write_text(json.dumps({'sha256':digest,'size':total,'done':sorted(done)}))
                speed=(len(done)-initial)*CHUNK/max(1,now-began)/1e6
                print(json.dumps({'downloaded_mb':round(len(done)*CHUNK/1e6),'percent':round(len(done)*100/count,1),
                    'mb_per_second':round(speed,2)}),flush=True);last=now
    for client in clients:client.close()
    signal.signal(signal.SIGINT,previous_signal)
    if stop.is_set():
        progress.write_text(json.dumps({'sha256':digest,'size':total,'done':sorted(done)}))
        print(json.dumps({'paused':True,'completed_chunks':len(done),'chunks':count}),flush=True)
        return
    if failures:
        progress.write_text(json.dumps({'sha256':digest,'size':total,'done':sorted(done)}))
        raise RuntimeError(f'{len(failures)} ranges failed; rerun to resume verified download')
    sha=hashlib.sha256()
    with partial.open('rb') as stream:
        for block in iter(lambda:stream.read(8*CHUNK),b''):sha.update(block)
    if sha.hexdigest()!=digest:raise ValueError('SHA256 mismatch — do not install')
    if target.exists():raise ValueError('Target already exists; preserve it')
    partial.rename(target)
    print(json.dumps({'verified':True,'wheel':str(target),'sha256':digest}),flush=True)


if __name__=='__main__':
    if '--status' in sys.argv or '--pause' in sys.argv:main()
    else:
        with download_lock():main()
