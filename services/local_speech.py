"""Local dual ASR/Silero on configured devices. Lightweight ONNX VAD stays CPU."""
import io
import os
import threading
from pathlib import Path
from providers.local_settings import LocalAIError
from services.russian_tts import prepare_russian_speech

ROOT=Path(__file__).resolve().parents[1]
_lock=threading.RLock()
_stt_lock=threading.RLock()
_tts_lock=threading.RLock()
_stt=_vad=_tts=None
_stt_device=_tts_device=None
_compute_type=None
_dll_handles=[]
_warmed=False


def select_device(requested, cuda_available):
    if requested not in {'auto', 'cpu', 'cuda'}:
        raise ValueError('LOCAL_STT_DEVICE/LOCAL_TTS_DEVICE: допустимы auto, cpu, cuda.')
    if requested == 'cuda' and not cuda_available:
        raise LocalAIError('cuda_unavailable')
    return 'cuda' if requested == 'cuda' or requested == 'auto' and cuda_available else 'cpu'


def configure_cuda_libraries(torch):
    # Official CUDA PyTorch wheels include cuBLAS/cuDNN DLLs on Windows.
    # Scope the DLL directory to this process, never change system PATH.
    if os.name == 'nt' and not _dll_handles and torch.version.cuda:
        library = Path(torch.__file__).parent / 'lib'
        _dll_handles.append(os.add_dll_directory(str(library)))


def model_path(variable,default):
    path=Path(os.getenv(variable,default))
    return path if path.is_absolute() else ROOT/path


def readiness():
    from services import dual_asr
    return {'stt_weights':dual_asr.weights_ready(),
            'tts_weights':model_path('LOCAL_TTS_PATH','models/silero/v5_ru.pt').is_file(),
            'stt_loaded':_stt is not None,'tts_loaded':_tts is not None,'vad_loaded':_vad is not None,
            'stt_device':_stt_device,'tts_device':_tts_device,'stt_compute_type':_compute_type,
            'vad_device':'cpu','warmed':_warmed,
            'stt_provider':'T-one CPU + GigaAM v3 RNNT',
            'speaker_filter':'pyannote segmentation + WeSpeaker CPU', 'preview_device':'cpu'}


def load_models():
    global _stt,_vad,_tts,_stt_device,_tts_device,_compute_type
    with _lock:
        if _stt is not None and _vad is not None and _tts is not None: return
        import torch
        configure_cuda_libraries(torch)
        from services import dual_asr
        from silero_vad import load_silero_vad
        import onnxruntime
        onnxruntime.disable_telemetry_events()
        torch.set_num_threads(int(os.getenv('LOCAL_CPU_THREADS','6')))
        tts_path=model_path('LOCAL_TTS_PATH','models/silero/v5_ru.pt')
        if not dual_asr.weights_ready() or not tts_path.is_file(): raise LocalAIError('missing_weights')
        if _stt is None:
            dual_asr.load()
            _stt=dual_asr._gigaam
            _stt_device=str(_stt._device)
            _compute_type='fp16_encoder' if _stt_device.startswith('cuda') else 'float32'
        if _vad is None: _vad=load_silero_vad(onnx=True)
        if _tts is None:
            device=select_device(os.getenv('LOCAL_TTS_DEVICE','auto'),torch.cuda.is_available())
            model=torch.package.PackageImporter(str(tts_path)).load_pickle('tts_models','model')
            model.to(torch.device(device))
            _tts,_tts_device=model,device


def transcribe_local(data,context=''):
    return transcribe_final(data,context)['raw_text']


def transcribe_final(data,context='',interaction_id='',stream_id='',speaker_mode='primary'):
    from services import dual_asr
    with _stt_lock:
        load_models()
        try:
            return dual_asr.final(data,interaction_id,stream_id,vad=_vad,speaker_mode=speaker_mode)
        finally:
            dual_asr.close_stream(interaction_id,stream_id)


def transcribe_preview(data,interaction_id,stream_id,sequence):
    from services import dual_asr
    # Silero carries mutable recurrent state; never share it between concurrent decodes.
    with _stt_lock:
        load_models()
        return dual_asr.preview(data,interaction_id,stream_id,sequence,vad=_vad)


def speech_window(audio, speech, sample_rate=16000):
    margin=int(sample_rate*0.2)
    start=max(0,int(speech[0]['start'])-margin)
    end=min(len(audio),int(speech[-1]['end'])+margin)
    return audio[start:end]


def synthesize_local(text):
    # Only the spoken copy changes. Dialogue/history retain the original text.
    spoken_text=prepare_russian_speech(text)
    if not spoken_text:
        raise ValueError('После подготовки не осталось текста для озвучки.')
    sample_rate=int(os.getenv('LOCAL_TTS_SAMPLE_RATE','48000'))
    if sample_rate not in (8000,24000,48000):
        raise ValueError('LOCAL_TTS_SAMPLE_RATE должен быть 8000, 24000 или 48000.')
    with _tts_lock:
        load_models()
        import soundfile as sf
        import torch
        speaker=os.getenv('LOCAL_TTS_SPEAKER','xenia')
        if speaker not in _tts.speakers:
            raise ValueError('LOCAL_TTS_SPEAKER отсутствует в установленной модели.')
        with torch.inference_mode():
            audio=_tts.apply_tts(text=spoken_text,speaker=speaker,sample_rate=sample_rate,
                put_accent=True,put_yo=True,put_stress_homo=True,put_yo_homo=True)
        result=io.BytesIO()
        sf.write(result,audio.detach().cpu().numpy(),sample_rate,format='WAV',subtype='PCM_16')
        return result.getvalue()


def warm_up():
    # Silero prepares its inference kernels on first synthesis, after weight loading.
    # Pay that cost during startup rather than the user's first greeting.
    global _warmed
    load_models()
    wav=synthesize_local('Здравствуйте! Чем могу помочь?')
    # Execute both ASR engines, VAD and CUDA kernels before the first conversation.
    transcribe_preview(wav,'warmup','warmup',0)
    from services import dual_asr
    dual_asr.close_stream('warmup','warmup')
    transcribe_local(wav)
    _warmed=True
