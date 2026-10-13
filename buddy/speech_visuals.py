"""Measure speech waveform levels for Buddy face animation."""
import io
import math
import struct
import wave

def voice_envelope(wav_bytes, frame_ms=40):
    with wave.open(io.BytesIO(wav_bytes), "rb") as source:
        rate = source.getframerate()
        width = source.getsampwidth()
        channels = source.getnchannels()
        if width != 2:
            return [0.35] * max(1, int(source.getnframes()/rate*1000/frame_ms))
        size = max(1, int(rate * frame_ms / 1000))
        levels = []
        while True:
            block = source.readframes(size)
            if not block:
                break
            count = len(block)//2
            values = struct.unpack('<'+str(count)+'h', block[:count*2])
            stride = max(1, channels*3)
            sample = values[::stride]
            rms = math.sqrt(sum(s*s for s in sample)/max(1,len(sample)))/32768
            levels.append(rms)
    peak = max(.015, sorted(levels)[int(len(levels)*.92)] if levels else .015)
    return [min(1., (n/peak)**.8) if n > .007 else 0. for n in levels] or [0.]
