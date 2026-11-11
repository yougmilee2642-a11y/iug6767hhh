"""Local T-one streaming preview + GigaAM final recognition, with speaker gating.

T-one ONNX protocol/labels follow voicekit-team/T-one (Apache-2.0).
Only GigaAM's final text reaches the dialogue. No network calls or guessed merge.
"""
import io
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from providers.local_settings import LocalAIError

ROOT = Path(__file__).resolve().parents[1]
LABELS = 'абвгдеёжзийклмнопрстуфхцчшщъыьэюя '
RATE = 16000
_load_lock = threading.RLock()
_preview_lock = threading.RLock()
_final_lock = threading.RLock()
_tone = _gigaam = _diarizer = _embedding = None
_streams = {}
_speakers = {}
MAX_SESSIONS = 128
TTL = 600


def weights_ready():
    return all((ROOT/'models'/name).is_file() for name in (
        'tone/model.onnx', 'gigaam/v3_rnnt.ckpt',
        'speaker/segmentation.onnx', 'speaker/wespeaker_en_voxceleb_resnet34_LM.onnx'))


def load():
    global _tone, _gigaam, _diarizer, _embedding
    with _load_lock:
        if _gigaam is not None: return
        if not weights_ready(): raise LocalAIError('missing_weights')
        import torch
        import gigaam
        import onnxruntime as ort
        import sherpa_onnx as sherpa
        threads = int(os.getenv('LOCAL_CPU_THREADS', '6'))
        options = ort.SessionOptions()
        options.intra_op_num_threads = threads
        options.inter_op_num_threads = 1
        options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        tone = ort.InferenceSession(str(ROOT/'models/tone/model.onnx'), options, providers=['CPUExecutionProvider'])
        embedding_config = sherpa.SpeakerEmbeddingExtractorConfig(
            model=str(ROOT/'models/speaker/wespeaker_en_voxceleb_resnet34_LM.onnx'),
            num_threads=2, provider='cpu')
        embedding = sherpa.SpeakerEmbeddingExtractor(embedding_config)
        config = sherpa.OfflineSpeakerDiarizationConfig(
            segmentation=sherpa.OfflineSpeakerSegmentationModelConfig(
                pyannote=sherpa.OfflineSpeakerSegmentationPyannoteModelConfig(
                    model=str(ROOT/'models/speaker/segmentation.onnx'), window_shift_ratio=0.5),
                num_threads=2, provider='cpu'),
            embedding=embedding_config,
            clustering=sherpa.FastClusteringConfig(num_clusters=-1, threshold=0.5),
            min_duration_on=0.2, min_duration_off=0.3)
        if not config.validate(): raise LocalAIError('missing_weights')
        diarizer = sherpa.OfflineSpeakerDiarization(config)
        device = os.getenv('LOCAL_STT_DEVICE', 'cuda')
        if device == 'auto': device = 'cuda' if torch.cuda.is_available() else 'cpu'
        if device == 'cuda' and not torch.cuda.is_available(): raise LocalAIError('cuda_unavailable')
        # Pre-check files: gigaam.load_model never downloads in the running app.
        giga = gigaam.load_model('v3_rnnt', device=device, fp16_encoder=device=='cuda',
                                 use_flash=False, download_root=str(ROOT/'models/gigaam'))
        _tone, _embedding, _diarizer, _gigaam = tone, embedding, diarizer, giga


def decode_audio(data):
    # PyAV supports browser WebM/MP4 and WAV. Whisper is not imported or executed.
    import av
    with av.open(io.BytesIO(data)) as container:
        resampler = av.AudioResampler(format='fltp', layout='mono', rate=RATE)
        pieces = []
        length = 0
        for frame in container.decode(audio=0):
            for converted in resampler.resample(frame):
                samples = converted.to_ndarray().reshape(-1).astype(np.float32)
                pieces.append(samples); length += len(samples)
                if length > RATE*120: raise ValueError('Реплика должна быть короче 120 секунд.')
        for converted in resampler.resample(None):
            samples = converted.to_ndarray().reshape(-1).astype(np.float32)
            pieces.append(samples); length += len(samples)
        if length > RATE*120: raise ValueError('Реплика должна быть короче 120 секунд.')
    return np.concatenate(pieces) if pieces else np.empty(0, dtype=np.float32)


@dataclass
class ToneStream:
    state: object = None
    remaining: object = field(default_factory=lambda: np.zeros(2400, dtype=np.int32))
    previous: int = 34
    text: str = ''
    sequence: int = 0
    samples: int = 0
    touched: float = field(default_factory=time.monotonic)

    def feed(self, audio, final=False):
        # Incoming WAV is 16kHz; low-pass resample to T-one's trained 8kHz PCM.
        from scipy.signal import resample_poly
        pcm = np.rint(np.clip(resample_poly(audio, 1, 2), -1, 1)*32767).astype(np.int32)
        self.samples += len(audio)
        if self.samples > RATE*120: raise ValueError('Реплика длиннее 120 секунд.')
        self.remaining = np.concatenate((self.remaining, pcm))
        if final:
            self.remaining = np.pad(self.remaining, (0, 2400+(-len(self.remaining)%2400)))
        consumed = 0
        while len(self.remaining)-consumed >= 2400:
            chunk = self.remaining[consumed:consumed+2400].reshape(1, 2400, 1)
            state = self.state if self.state is not None else np.zeros((1,219729), dtype=np.float16)
            probs, self.state = _tone.run(None, {'signal':chunk, 'state':state})
            for token in probs.reshape(-1,35).argmax(axis=-1):
                token = int(token)
                if token != self.previous and token < len(LABELS): self.text += LABELS[token]
                self.previous = token
            consumed += 2400
        self.remaining = self.remaining[consumed:]
        self.touched = time.monotonic()
        return self.text.strip()


def expire_sessions():
    now = time.monotonic()
    for key in list(_streams):
        if now-_streams[key].touched > TTL: del _streams[key]
    for key in list(_speakers):
        if now-_speakers[key][1] > TTL: del _speakers[key]


def preview(data, interaction_id, stream_id, sequence, vad=None):
    load()
    audio = decode_audio(data)
    with _preview_lock:
        expire_sessions()
        key = (interaction_id, stream_id)
        if key not in _streams:
            if sequence != 0: raise ValueError('Потерян первый фрагмент потока.')
            if len(_streams) >= MAX_SESSIONS: raise LocalAIError('unavailable')
            _streams[key] = ToneStream()
        stream = _streams[key]
        if sequence != stream.sequence: raise ValueError('Нарушен порядок фрагментов потока.')
        text = stream.feed(audio)
        stream.sequence += 1
        result={'text':text, 'raw_text':text, 'cumulative':True,
                'provider':'T-one ONNX CPU · предварительный текст', 'final':False}
        reference=_speakers.get(interaction_id)
        if reference is not None and vad is not None:
            import torch
            from silero_vad import get_speech_timestamps
            speech=get_speech_timestamps(torch.from_numpy(audio.copy()),vad,sampling_rate=RATE)
            voiced=np.concatenate([audio[s['start']:s['end']] for s in speech]) if speech else np.empty(0,dtype=np.float32)
            embedding=speaker_embedding(voiced)
            if not speech:
                result.update(speaker_checked=True,primary_speech=False)
            elif embedding is not None:
                score=float(np.dot(reference[0],embedding))
                result.update(speaker_checked=True,primary_speech=score>=float(os.getenv('LOCAL_SPEAKER_THRESHOLD','0.6')))
        return result


def speaker_embedding(audio):
    if len(audio) < RATE*0.6: return None
    stream = _embedding.create_stream()
    stream.accept_waveform(sample_rate=RATE, waveform=np.ascontiguousarray(audio))
    stream.input_finished()
    if not _embedding.is_ready(stream): return None
    result = np.asarray(_embedding.compute(stream), dtype=np.float32)
    return result / max(float(np.linalg.norm(result)), 1e-9)


def foreground_spans(audio, speech, selected, reference):
    """Restore VAD word edges and reject separate distant intro/outro voices.

    Energy is relative within this reply; internal quiet speech is retained.
    A quiet edge is removed only when it is separated by a pause and its voice
    does not strongly match the main voice. No text or dataset labels are used.
    """
    candidates=[]
    for region in speech:
        a,b=int(region['start']),int(region['end'])
        part=audio[a:b]
        overlap=sum(max(0,min(b,d)-max(a,c)) for c,d in selected)
        embedding=speaker_embedding(part)
        similarity=None if embedding is None or reference is None else float(np.dot(reference,embedding))
        if overlap >= (b-a)*.5 or similarity is not None and similarity>=.75:
            candidates.append((a,b,float(np.sqrt(np.mean(part**2))),similarity))
    if not candidates:return selected,0
    peak=max(r[2] for r in candidates)
    strong=[i for i,r in enumerate(candidates) if r[2]>=peak*.25]
    if not strong:return selected,0
    first,last=min(strong),max(strong)
    retained=[];removed=0
    for i,(a,b,energy,similarity) in enumerate(candidates):
        at_edge=i<first or i>last
        gap=(candidates[first][0]-b) if i<first else (a-candidates[last][1])
        if at_edge and energy<peak*.25 and gap>RATE*.3 and (similarity is None or similarity<.85):
            removed+=1;continue
        retained.append((a,b))
    return retained,removed


def filter_speaker(audio, interaction_id, speech=None):
    """Enroll a clearly dominant first speaker; keep matching speech afterwards.

    Uncertain/mixed speech is returned for repetition, never assigned by loudness.
    Voice profiles live in bounded RAM for ten minutes, never on disk.
    """
    if not interaction_id: return audio, {'status':'no_session'}
    expire_sessions()
    segments = _diarizer.process(np.ascontiguousarray(audio)).sort_by_start_time()
    if not segments: return np.empty(0,dtype=np.float32), {'status':'no_speech'}
    groups = {}
    spans = []
    for s in segments:
        start, end = max(0,int(s.start*RATE)), min(len(audio),int(s.end*RATE))
        if end <= start: continue
        spans.append((start, end, s.speaker))
        groups.setdefault(s.speaker, []).append(audio[start:end])
    if not groups: return np.empty(0,dtype=np.float32), {'status':'no_speech'}
    reference = _speakers.get(interaction_id)
    new_reference=None
    if reference is None:
        durations={label:sum(len(p) for p in pieces) for label,pieces in groups.items()}
        chosen=max(durations,key=durations.get)
        if len(groups) > 1:
            share=durations[chosen]/sum(durations.values())
            if share<.75 or durations[chosen]<RATE*2.4:
                return np.empty(0,dtype=np.float32), {'status':'multiple_initial_speakers','requires_repeat':True,
                    'message':'Не удалось уверенно выделить ваш голос. Повторите ответ ближе к микрофону.'}
        voiced = np.concatenate(groups[chosen])
        embedding = speaker_embedding(voiced) if len(voiced) >= RATE*1.2 else None
        new_reference=embedding
        metadata = {'status':'enrolled' if embedding is not None else 'awaiting_clear_reply'}
        if len(groups)>1:metadata['dominant_speech_share']=round(share,3)
    else:
        candidates = []
        for label, pieces in groups.items():
            embedding = speaker_embedding(np.concatenate(pieces))
            if embedding is not None: candidates.append((float(np.dot(reference[0],embedding)),label))
        if not candidates:
            # A short isolated "да" cannot provide a reliable voice fingerprint.
            if len(groups) != 1:
                return np.empty(0,dtype=np.float32), {'status':'uncertain','requires_repeat':True,
                    'message':'Не удалось отделить ваш голос. Повторите ответ ближе к микрофону.'}
            chosen = next(iter(groups)); metadata = {'status':'short_reply_unverified'}
        else:
            score, chosen = max(candidates)
            threshold = float(os.getenv('LOCAL_SPEAKER_THRESHOLD','0.6'))
            if score < threshold:
                return np.empty(0,dtype=np.float32), {'status':'different_or_uncertain_speaker',
                    'similarity':round(score,3),'requires_repeat':True,
                    'message':'Не уверена, что слышу ваш голос. Повторите ответ ближе к микрофону.'}
            _speakers[interaction_id] = (reference[0],time.monotonic())
            metadata = {'status':'matched','similarity':round(score,3)}
    selected = [(a,b) for a,b,label in spans if label==chosen]
    if speech:
        selected,removed=foreground_spans(audio,speech,selected,reference[0] if reference is not None else new_reference)
        metadata['removed_distant_regions']=removed
    # Simultaneous voices cannot safely be removed by masking time spans.
    overlap = sum(max(0,min(b,d)-max(a,c)) for a,b in selected
                  for c,d,label in spans if label!=chosen)/RATE
    # Small boundary disagreements should not reject an otherwise clear reply.
    # Extensive overlap still needs a repeat; masking cannot separate sources.
    overlap_limit=max(.5,sum(b-a for a,b in selected)/RATE*.1)
    if overlap > overlap_limit:
        return np.empty(0,dtype=np.float32), {'status':'overlapping_speakers','requires_repeat':True,
            'message':'Голоса накладываются друг на друга. Повторите ответ, пока остальные молчат.'}
    if overlap:metadata['brief_boundary_overlap_seconds']=round(overlap,3)
    # Preserve timeline and gaps; zero other voices without joining word edges.
    output = np.zeros_like(audio)
    for a,b in selected:
        # Diarization boundaries are approximate. Preserve soft consonants without
        # copying neighbouring speaker spans into the retained signal.
        start,end=max(0,a-int(RATE*.2)),min(len(audio),b+int(RATE*.2))
        for c,d,label in spans:
            if label==chosen:continue
            if d<=a:start=max(start,d)
            elif c>=b:end=min(end,c)
        output[start:end] = audio[start:end]
    metadata['detected_speakers'] = len(groups)
    metadata['removed_background_speakers'] = max(0,len(groups)-1)
    # Commit a first voice only after selection and overlap checks have passed.
    if reference is None and new_reference is not None:
        new_reference=speaker_embedding(np.concatenate([audio[a:b] for a,b in selected]))
        if new_reference is not None:
            if len(_speakers)>=MAX_SESSIONS:
                del _speakers[min(_speakers,key=lambda k:_speakers[k][1])]
            _speakers[interaction_id]=(new_reference,time.monotonic())
    return output, metadata


def apply_speaker_mode(audio, interaction_id, speech, speaker_mode='primary'):
    """Keep every voice for meeting capture or retain the enrolled caller by default."""
    if speaker_mode == 'all':
        return audio, {'status':'all_speakers','filter_applied':False}
    if speaker_mode == 'primary':
        return filter_speaker(audio,interaction_id,speech)
    raise ValueError('speaker_mode must be primary or all')


def split_long_audio(audio, speech):
    """Split long silences and >24s audio without losing any input samples."""
    # Removing background speech can leave many seconds of silence. RNNT may
    # omit a short confirmation after that gap; decode both speech regions fully.
    for left,right in zip(speech,speech[1:]):
        if right['start']-left['end'] >= RATE*2:
            cut=(int(left['end'])+int(right['start']))//2
            before=[s for s in speech if s['end']<=cut]
            after=[{'start':s['start']-cut,'end':s['end']-cut} for s in speech if s['start']>=cut]
            yield from split_long_audio(audio[:cut],before)
            yield from split_long_audio(audio[cut:],after)
            return
    limit = RATE*24
    start = 0
    while len(audio)-start > limit:
        target = start+limit
        # Prefer actual VAD gaps in the latter half, never drop audio.
        gaps = [(int(a['end'])+int(b['start']))//2 for a,b in zip(speech,speech[1:])
                if b['start']-a['end'] >= RATE*0.15 and start+limit//2 <= a['end'] <= target]
        if gaps: end = max(gaps)
        else:
            # Continuous long speech: quietest 20ms frame near the limit.
            candidates = range(target-RATE*2,target,320)
            end = min(candidates,key=lambda i:float(np.mean(audio[i:i+320]**2)))+160
        yield audio[start:end]
        start = end
    if start < len(audio): yield audio[start:]


def final(data, interaction_id='', stream_id='', vad=None, speaker_mode='primary'):
    if speaker_mode not in {'primary', 'all'}:
        raise ValueError('speaker_mode must be primary or all')
    load()
    began = time.perf_counter()
    audio = decode_audio(data)
    from silero_vad import get_speech_timestamps
    import torch
    if not len(audio): return {'text':'','raw_text':'','final':True}
    with _final_lock:
        speech = get_speech_timestamps(torch.from_numpy(audio.copy()),vad,sampling_rate=RATE)
        if not speech:
            return {'text':'','raw_text':'','final':True,'speaker':{'status':'no_speech'}}
        audio, speaker = apply_speaker_mode(audio,interaction_id,speech,speaker_mode)
        if not len(audio):
            return {'text':'','raw_text':'','final':True,'speaker':speaker,
                    'provider':'T-one + GigaAM v3 RNNT'}
        speech = get_speech_timestamps(torch.from_numpy(audio.copy()),vad,sampling_rate=RATE)
        if not speech: return {'text':'','raw_text':'','final':True,'speaker':speaker}
        margin = int(RATE*0.2)
        start,end = max(0,speech[0]['start']-margin),min(len(audio),speech[-1]['end']+margin)
        audio = audio[start:end]
        speech = [{'start':max(0,s['start']-start),'end':min(len(audio),s['end']-start)} for s in speech]
        texts = []
        with torch.inference_mode():
            for chunk in split_long_audio(audio,speech):
                # Crop only exact zeros introduced by speaker masking, with
                # generous margins. Quiet nonzero speech is always retained.
                nonzero=np.flatnonzero(chunk)
                if not len(nonzero):continue
                chunk=chunk[max(0,int(nonzero[0])-margin):min(len(chunk),int(nonzero[-1])+1+margin)]
                wav = torch.from_numpy(chunk.copy()).to(_gigaam._device).to(_gigaam._dtype).unsqueeze(0)
                length = torch.tensor([wav.shape[-1]],device=_gigaam._device)
                encoded, encoded_len = _gigaam.forward(wav,length)
                text = _gigaam._decode(encoded,encoded_len,length)[0][0]
                texts.append(text.strip())
        raw = ' '.join(t for t in texts if t)
        return {'text':raw,'raw_text':raw,'final':True,'speaker':speaker,
                'provider':'T-one CPU + GigaAM v3 RNNT '+str(_gigaam._device),
                'recognition_ms':round((time.perf_counter()-began)*1000)}


def close_stream(interaction_id, stream_id):
    with _preview_lock:
        _streams.pop((interaction_id,stream_id),None)
