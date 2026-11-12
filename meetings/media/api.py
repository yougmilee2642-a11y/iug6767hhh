"""Bounded consented audio, scoped playback and transcript preview/confirm."""
import hashlib
import json
import os
from pathlib import Path
from fastapi import APIRouter,BackgroundTasks,File,Form,Request,UploadFile
from fastapi.responses import JSONResponse,Response
from pydantic import BaseModel,ConfigDict,Field
from meetings import confirmations,store
from meetings.api import ConfirmTokenIn,_meeting,denied
from meetings.auth import MeetError,MeetRoute,current_user
from meetings.connectors.mock import digest
from meetings.media import analytics,backend,pipeline

ERRORS={'asr_unavailable':'Модели распознавания не настроены. Файл сохранён; обработку можно повторить после настройки.',
        'diarization_unavailable':'Диаризация недоступна. Файл сохранён.', 'invalid_audio':'Не удалось декодировать аудиофайл. Исходный файл сохранён.',
        'audio_too_long':'Запись превышает предел длительности. Исходный файл сохранён.',
        'no_speech':'Речь не найдена. Исходный файл сохранён.', 'access_revoked':'Доступ изменился. Обработка остановлена.',
        'audio_deleted':'Аудио удалено по политике хранения.'}
ERRORS['processing_interrupted']='Обработка прервалась при перезапуске. Файл сохранён; нажмите «Повторить обработку».'
ERRORS['secret_model_denied']='Закрытые материалы не обрабатываются моделью. Исходный файл сохранён без расшифровки.'


def max_bytes():
    try:value=int(os.getenv('MEETINGS_AUDIO_MAX_MB','64'))
    except ValueError:value=64
    return max(1,min(value,256))*1024*1024


def media_type(data):
    if data[:4]==b'RIFF' and data[8:12]==b'WAVE':return 'audio/wav'
    if data[:4]==b'OggS':return 'audio/ogg'
    if data[:4]==bytes.fromhex('1a45dfa3'):return 'audio/webm'
    if len(data)>12 and data[4:8]==b'ftyp':return 'audio/mp4'
    if data[:3]==b'ID3' or len(data)>2 and data[0]==255 and data[1]&224==224:return 'audio/mpeg'
    raise MeetError(422,'invalid_audio','Допустимы WAV, MP3, M4A, OGG, WebM. Содержимое файла не распознано.')


def checked_job(c,user,jid,write=False):
    if not 0<jid<=2**63-1:raise denied(user,'media_job',str(jid)[:30],'media.read')
    row=c.execute('SELECT * FROM media_jobs WHERE id=?',(jid,)).fetchone()
    if not row:raise denied(user,'media_job',jid,'media.read')
    meeting=_meeting(c,user,row['meeting_id'],'transcript.edit' if write else None,'media.write' if write else 'media.read')
    return row,meeting


def job_out(c,row):
    return {k:row[k] for k in ('id','meeting_id','asset_id','status','progress','error_code','duration_ms','imported_at','created_at','updated_at')} | {
        'error_message':ERRORS.get(row['error_code'],'Обработка не завершена. Исходный файл сохранён.') if row['error_code'] else None,
        'segments':[dict(r) for r in c.execute('SELECT id,position,speaker_label,text,start_ms,end_ms FROM media_segments WHERE job_id=? ORDER BY position',(row['id'],))],
        'notice':'Черновик распознавания. Проверьте говорящих и текст перед добавлением в стенограмму.'}


class Mapping(BaseModel):
    model_config=ConfigDict(extra='forbid')
    speaker_map:dict[str,str]=Field(default_factory=dict,max_length=30)


def import_proof(c,user,jid,mapping):
    job,meeting=checked_job(c,user,jid,True)
    if job['status']!='done' or not job['asset_id'] or job['imported_at']:
        raise MeetError(409,'media_not_ready','Расшифровка недоступна или уже добавлена. Обновите запись.')
    if meeting['version']!=job['meeting_version'] or pipeline.transcript_hash(c,meeting['id'])!=job['transcript_hash']:
        raise MeetError(409,'stale','Встреча или стенограмма изменилась во время обработки. Проверьте изменения и повторите обработку.')
    segments=[dict(r) for r in c.execute('SELECT * FROM media_segments WHERE job_id=? ORDER BY position',(jid,))]
    if not segments:raise MeetError(422,'no_speech','Нет распознанных реплик.')
    labels={s['speaker_label'] for s in segments};names=set(json.loads(meeting['participants']))
    if any(k not in labels or v not in names for k,v in mapping.items()):
        raise MeetError(422,'speaker_mapping','Говорящих можно сопоставить только с участниками встречи. Неизвестное имя оставьте без сопоставления.')
    return job,meeting,{'job_id':jid,'asset_id':job['asset_id'],'segments':segments,'speaker_map':mapping,
                       'meeting_version':meeting['version'],'transcript_hash':job['transcript_hash']}


def router():
    api=APIRouter(route_class=MeetRoute)

    @api.post('/api/meet/meetings/{meeting_id}/audio')
    async def upload(meeting_id:int,request:Request,background:BackgroundTasks,file:UploadFile=File(...),consent:bool=Form(False)):
        user=current_user(request)
        with store.db() as c:_meeting(c,user,meeting_id,'transcript.edit','media.upload')
        if not consent:raise MeetError(403,'consent_required','Перед загрузкой подтвердите согласие всех участников на запись и обработку.')
        data=await file.read(max_bytes()+1)
        if len(data)>max_bytes():raise MeetError(413,'audio_too_large','Файл превышает допустимый размер записи.')
        mime=media_type(data);sha=hashlib.sha256(data).hexdigest()
        with store.write_tx() as c:
            meeting=_meeting(c,user,meeting_id,'transcript.edit','media.upload')
            existing=c.execute('SELECT j.* FROM media_jobs j JOIN media_assets a ON a.id=j.asset_id WHERE j.meeting_id=? AND j.created_by=? AND a.sha256=? AND j.imported_at IS NULL ORDER BY j.id DESC LIMIT 1',
                               (meeting_id,user['id'],sha)).fetchone()
            if existing:
                output={'job':job_out(c,existing),'unchanged':True}
                return JSONResponse(output,status_code=503 if existing['status']=='failed' else 200)
            if c.execute("SELECT count(*) FROM media_jobs WHERE status IN ('queued','transcribing','diarizing','extracting')").fetchone()[0]>=8:
                raise MeetError(429,'media_queue_full','Очередь записей заполнена. Повторите загрузку позже.')
            stamp=store.now()
            aid=c.execute('INSERT INTO media_assets(meeting_id,created_by,content,media_type,sha256,consent_at,created_at) VALUES (?,?,?,?,?,?,?)',
                          (meeting_id,user['id'],data,mime,sha,stamp,stamp)).lastrowid
            enabled=backend.ready();status='queued' if enabled else 'failed';error=None if enabled else 'asr_unavailable'
            jid=c.execute('INSERT INTO media_jobs(meeting_id,asset_id,status,error_code,created_by,meeting_version,transcript_hash,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)',
                          (meeting_id,aid,status,error,user['id'],meeting['version'],pipeline.transcript_hash(c,meeting_id),stamp,stamp)).lastrowid
            store.audit(c,user['id'],'audio_uploaded',object_type='meeting',object_id=meeting_id,bytes=len(data),consent=True,job_id=jid)
            output={'job':job_out(c,c.execute('SELECT * FROM media_jobs WHERE id=?',(jid,)).fetchone()),'unchanged':False}
        if enabled:background.add_task(pipeline.run,jid,str(store.db_path().resolve()))
        return JSONResponse(output,status_code=202 if enabled else 503)

    @api.get('/api/meet/meetings/{meeting_id}/audio')
    def listing(meeting_id:int,request:Request):
        user=current_user(request)
        with store.db() as c:
            _meeting(c,user,meeting_id)
            return {'jobs':[job_out(c,r) for r in c.execute('SELECT * FROM media_jobs WHERE meeting_id=? ORDER BY id DESC LIMIT 20',(meeting_id,))],
                    'max_bytes':max_bytes(),'max_minutes':backend.duration_limit()//60}

    @api.get('/api/meet/media-jobs/{job_id}')
    def status(job_id:int,request:Request):
        user=current_user(request)
        with store.db() as c:
            job,_=checked_job(c,user,job_id)
            return {'job':job_out(c,job)}

    @api.get('/api/meet/media-assets/{asset_id}/audio')
    def playback(asset_id:int,request:Request):
        user=current_user(request)
        if not 0<asset_id<=2**63-1:raise denied(user,'media_asset',str(asset_id)[:30],'audio.read')
        with store.db() as c:
            row=c.execute('SELECT * FROM media_assets WHERE id=?',(asset_id,)).fetchone()
            if not row:raise denied(user,'media_asset',asset_id,'audio.read')
            _meeting(c,user,row['meeting_id'])
            store.audit(c,user['id'],'audio_read',object_type='meeting',object_id=row['meeting_id'])
            return Response(row['content'],media_type=row['media_type'],headers={'Content-Disposition':'inline','Cache-Control':'no-store'})

    @api.post('/api/meet/media-jobs/{job_id}/retry')
    def retry(job_id:int,request:Request,background:BackgroundTasks):
        user=current_user(request)
        with store.write_tx() as c:
            job,meeting=checked_job(c,user,job_id,True)
            if job['status'] not in ('failed','done') or job['imported_at'] or not job['asset_id']:
                raise MeetError(409,'media_not_retryable','Запись уже обрабатывается, добавлена или удалена.')
            if not backend.ready():raise MeetError(503,'asr_unavailable',ERRORS['asr_unavailable'])
            c.execute("UPDATE media_jobs SET status='queued',progress=0,error_code=NULL,meeting_version=?,transcript_hash=?,updated_at=? WHERE id=?",
                      (meeting['version'],pipeline.transcript_hash(c,meeting['id']),store.now(),job_id))
            c.execute('DELETE FROM media_segments WHERE job_id=?',(job_id,))
            store.audit(c,user['id'],'audio_retry',object_type='meeting',object_id=meeting['id'],job_id=job_id)
        background.add_task(pipeline.run,job_id,str(store.db_path().resolve()))
        return {'job_id':job_id,'status':'queued'}

    @api.post('/api/meet/media-jobs/{job_id}/import/preview')
    def preview(job_id:int,payload:Mapping,request:Request):
        user=current_user(request)
        with store.write_tx() as c:
            job,meeting,proof=import_proof(c,user,job_id,payload.speaker_map)
            token=confirmations.create(c,user,'media.import','media_job',job_id,meeting['version'],{'proof':proof,'hash':digest(proof)})
            store.audit(c,user['id'],'media_import_preview',object_type='meeting',object_id=meeting['id'],stage='preview',confirmation_id=token['confirmation_id'])
            return {**token,'preview':{**proof,'notice':'Реплики будут добавлены в конец стенограммы. Задачи и протокол автоматически не подтверждаются.'}}

    @api.post('/api/meet/media-jobs/{job_id}/import/confirm')
    def confirm(job_id:int,payload:ConfirmTokenIn,request:Request):
        user=current_user(request)
        with store.write_tx() as c:
            p=confirmations.load(c,user,payload.confirmation_id,'media.import','media_job',job_id,payload.idempotency_key)
            job,meeting=checked_job(c,user,job_id,True)
            if p['already']:return {**p['result'],'already_confirmed':True}
            _,_,proof=import_proof(c,user,job_id,p['payload']['proof']['speaker_map'])
            if digest(proof)!=p['payload']['hash']:raise MeetError(409,'stale','Расшифровка изменилась. Сформируйте новый предпросмотр.')
            index=c.execute('SELECT COALESCE(max(idx),0) FROM utterances WHERE meeting_id=?',(meeting['id'],)).fetchone()[0]
            ids=[]
            # Resolve the per-recording map at import. Repeated generic labels in
            # a second recording cannot silently rename an earlier recording.
            for i,s in enumerate(proof['segments']):
                label=proof['speaker_map'].get(s['speaker_label']) or f"Запись {job_id} · {s['speaker_label']}"
                uid=c.execute('INSERT INTO utterances(meeting_id,idx,speaker_label,text,original_text,source,start_ms,end_ms,media_job_id) VALUES (?,?,?,?,?,?,?,?,?)',
                              (meeting['id'],index+i+1,label,s['text'],s['text'],'audio',s['start_ms'],s['end_ms'],job_id)).lastrowid
                ids.append('U'+str(uid))
            c.execute('UPDATE media_jobs SET imported_at=?,updated_at=? WHERE id=?',(store.now(),store.now(),job_id))
            c.execute('UPDATE meetings SET version=version+1 WHERE id=?',(meeting['id'],))
            result={'meeting_id':meeting['id'],'utterance_ids':ids,'already_confirmed':False}
            confirmations.finish(c,payload.confirmation_id,payload.idempotency_key,result)
            store.audit(c,user['id'],'media_import_confirmed',object_type='meeting',object_id=meeting['id'],stage='confirm',confirmation_id=payload.confirmation_id,source_ids=ids)
            return result

    @api.get('/api/meet/meetings/{meeting_id}/analytics')
    def report(meeting_id:int,request:Request):
        user=current_user(request)
        with store.db() as c:
            meeting=_meeting(c,user,meeting_id)
            return analytics.build(c,meeting)
    return api


def install_background(app):
    def interrupted_jobs():
        # The documented prototype runs one API process. Recovery does not run
        # inference: the operator chooses Retry on the retained source file.
        with store.write_tx() as c:
            c.execute("UPDATE media_jobs SET status='failed',progress=0,error_code='processing_interrupted',updated_at=? "
                      "WHERE status IN ('queued','diarizing','transcribing','extracting')",(store.now(),))
    from meetings.lifecycle import install
    install(app,interrupted_jobs)
