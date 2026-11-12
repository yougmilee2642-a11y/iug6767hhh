"""Opt-in host adapter. Importing the module NEVER loads or downloads weights.

Tests replace Backend; the agent must never call this real inference adapter.
Existing dual_asr's locked local GigaAM/sherpa objects are reused without TTS.
"""
import io
import os


class MediaError(ValueError):
    def __init__(self, code): self.code=code; super().__init__(code)


RATE=16000


def duration_limit():
    try: value=int(os.getenv('MEETINGS_AUDIO_MAX_MINUTES','120'))
    except ValueError: value=120
    return max(1,min(value,240))*60


def decode(data):
    """CPU-only bounded decoder; never feeds URL/file protocols to FFmpeg."""
    import av
    import numpy as np
    try:
        with av.open(io.BytesIO(data),options={'protocol_whitelist':'pipe'}) as container:
            resampler=av.AudioResampler(format='fltp',layout='mono',rate=RATE)
            pieces=[];length=0
            for frame in container.decode(audio=0):
                for converted in resampler.resample(frame):
                    samples=converted.to_ndarray().reshape(-1).astype(np.float32)
                    length+=len(samples)
                    if length>RATE*duration_limit():raise MediaError('audio_too_long')
                    pieces.append(samples)
            for converted in resampler.resample(None):
                samples=converted.to_ndarray().reshape(-1).astype(np.float32);length+=len(samples)
                if length>RATE*duration_limit():raise MediaError('audio_too_long')
                pieces.append(samples)
        if not length:raise MediaError('invalid_audio')
        result=np.concatenate(pieces)
        if not np.isfinite(result).all():raise MediaError('invalid_audio')
        return result
    except MediaError:raise
    except Exception:raise MediaError('invalid_audio') from None


def ready():
    if os.getenv('MEETINGS_AUDIO_PIPELINE_ENABLED','0')!='1':return False
    from services import dual_asr
    return dual_asr.weights_ready()


class Backend:
    """Host-only inference; segmentation labels never identify a person by voice."""
    def __init__(self):
        if not ready():raise MediaError('asr_unavailable')
        try:
            from services import dual_asr
            dual_asr.load()
            self.asr=dual_asr
        except Exception:raise MediaError('asr_unavailable') from None

    def diarize(self,audio):
        import numpy as np
        try:
            with self.asr._final_lock:
                result=self.asr._diarizer.process(np.ascontiguousarray(audio)).sort_by_start_time()
            return [{'start':float(s.start),'end':float(s.end),'speaker':str(s.speaker)} for s in result]
        except Exception:raise MediaError('diarization_unavailable') from None

    def transcribe(self,audio):
        import torch
        try:
            with self.asr._final_lock,torch.inference_mode():
                model=self.asr._gigaam
                wav=torch.from_numpy(audio.copy()).to(model._device).to(model._dtype).unsqueeze(0)
                length=torch.tensor([wav.shape[-1]],device=model._device)
                encoded,encoded_len=model.forward(wav,length)
                return model._decode(encoded,encoded_len,length)[0][0].strip()
        except Exception:raise MediaError('asr_unavailable') from None
