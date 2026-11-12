"""One local inference worker, bounded input, immutable reviewable segments."""
import hashlib
import json
import math
from pathlib import Path
import threading
from meetings import access, notifications, store
from meetings.connectors.mock import digest
from meetings.media import backend

_worker=threading.Lock()


def authorize(job):
    with store.db() as c:
        if not access.object_decision(c,job['created_by'],'meeting',job['meeting_id'],'transcript.edit').allowed:
            raise backend.MediaError('access_revoked')
        if not store.can_read_meeting(c,job['created_by'],job['meeting_id'],model=True):
            raise backend.MediaError('secret_model_denied')


def transcript_hash(c,mid):
    return digest([dict(r) for r in c.execute('SELECT id,text,original_text,speaker_label,deleted FROM utterances WHERE meeting_id=? ORDER BY id',(mid,))])


def update(job_id,path,status,progress,error=None):
    if store.db_path().resolve()!=Path(path):return False
    with store.write_tx() as c:
        return bool(c.execute('UPDATE media_jobs SET status=?,progress=?,error_code=?,updated_at=? WHERE id=? AND imported_at IS NULL',
                               (status,progress,error,store.now(),job_id)).rowcount)


def run(job_id,path):
    """Called as a background task after upload. No task/protocol is confirmed."""
    path=Path(path)
    if store.db_path().resolve()!=path:return
    with _worker:
        try:
            with store.db() as c:
                job=c.execute('SELECT j.*,a.content,a.sha256 FROM media_jobs j LEFT JOIN media_assets a ON a.id=j.asset_id WHERE j.id=?',(job_id,)).fetchone()
                if not job or job['status']!='queued' or job['imported_at']:return
                if not job['content']:raise backend.MediaError('audio_deleted')
                actor=access.load_user(c,job['created_by'])
                if not actor or not access.object_decision(c,actor['id'],'meeting',job['meeting_id'],'transcript.edit').allowed:
                    raise backend.MediaError('access_revoked')
                content=job['content']
                if hashlib.sha256(content).hexdigest()!=job['sha256']:raise backend.MediaError('invalid_audio')
            update(job_id,path,'diarizing',5)
            authorize(job)
            audio=backend.decode(content);duration=len(audio)/backend.RATE
            engine=backend.Backend()
            authorize(job)
            spans=engine.diarize(audio)
            if not isinstance(spans,list) or len(spans)>10000:raise backend.MediaError('invalid_diarization')
            normalized=[];labels={}
            for span in spans:
                a,b=float(span['start']),float(span['end']);label=str(span['speaker'])
                if not all(math.isfinite(v) for v in (a,b)) or not 0<=a<b<=duration+0.05 or len(label)>100:
                    raise backend.MediaError('invalid_diarization')
                b=min(b,duration)
                labels.setdefault(label,'Говорящий '+str(len(labels)+1))
                if len(labels)>30:raise backend.MediaError('invalid_diarization')
                # Bound each recognition window; retain the original time axis.
                while a<b:
                    finish=min(b,a+25)
                    normalized.append((a,finish,labels[label]));a=finish
            normalized.sort()
            segments=[]
            update(job_id,path,'transcribing',20)
            for i,(a,b,label) in enumerate(normalized):
                authorize(job)
                text=engine.transcribe(audio[round(a*backend.RATE):round(b*backend.RATE)])
                if not isinstance(text,str) or len(text)>8000:raise backend.MediaError('invalid_transcript')
                if text.strip():segments.append((label,text.strip(),round(a*1000),round(b*1000)))
                update(job_id,path,'transcribing',20+int(65*(i+1)/max(1,len(normalized))))
            if not segments:raise backend.MediaError('no_speech')
            update(job_id,path,'extracting',90)
            if store.db_path().resolve()!=path:return
            with store.write_tx() as c:
                current=c.execute('SELECT * FROM media_jobs WHERE id=?',(job_id,)).fetchone()
                if not current or current['imported_at']:return
                if not current['asset_id']:raise backend.MediaError('audio_deleted')
                if not access.object_decision(c,job['created_by'],'meeting',job['meeting_id'],'transcript.edit').allowed:
                    raise backend.MediaError('access_revoked')
                if not store.can_read_meeting(c,job['created_by'],job['meeting_id'],model=True):
                    raise backend.MediaError('secret_model_denied')
                c.execute('DELETE FROM media_segments WHERE job_id=?',(job_id,))
                c.executemany('INSERT INTO media_segments(job_id,position,speaker_label,text,start_ms,end_ms) VALUES (?,?,?,?,?,?)',
                              [(job_id,i+1,*s) for i,s in enumerate(segments)])
                c.execute("UPDATE media_jobs SET status='done',progress=100,duration_ms=?,updated_at=? WHERE id=?",(round(duration*1000),store.now(),job_id))
                notifications.emit(c,job['created_by'],'media_ready','meeting',job['meeting_id'],
                                   'Расшифровка готова к проверке и сопоставлению говорящих.',f'media-ready:{job_id}')
                store.audit(c,job['created_by'],'media_processed',object_type='meeting',object_id=job['meeting_id'],segment_count=len(segments))
        except backend.MediaError as error:
            update(job_id,path,'failed',0,error.code)
        except Exception:
            # Never return decoder/model/path details or input content to the client.
            update(job_id,path,'failed',0,'media_processing_failed')
