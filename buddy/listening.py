"""Local voice activity end-pointing. No microphone audio leaves Buddy until a turn ends."""
import array
import math
import time

class SilenceDetector:
    def __init__(self, sample_rate=16000, threshold=0.018, silence_seconds=1.45,
                 timeout_seconds=18.0, max_seconds=45.0):
        self.threshold = threshold
        self.silence_seconds = silence_seconds
        self.timeout_seconds = timeout_seconds
        self.max_seconds = max_seconds
        self.began = time.monotonic()
        self.last_sound = self.began
        self.active_since = None
        self.heard_speech = False
        self.noise = 0.004
        self.last_level = 0.0

    def inspect(self, pcm, now=None):
        now = time.monotonic() if now is None else now
        if pcm:
            arr = array.array('h')
            arr.frombytes(pcm[:len(pcm) - len(pcm) % 2])
            if arr:
                # Decimated RMS is fast even on Raspberry Pi.
                stride = max(1, len(arr) // 2000)
                selected = arr[::stride]
                level = math.sqrt(sum(v*v for v in selected)/len(selected))/32768.0
                self.last_level = level
                moving_threshold = max(self.threshold, self.noise*3.2)
                if level > moving_threshold:
                    if self.active_since is None:
                        self.active_since = now
                    if now-self.active_since > 0.13:
                        self.heard_speech = True
                        self.last_sound = now
                else:
                    self.active_since = None
                    if not self.heard_speech:
                        self.noise = min(.02, .92*self.noise+.08*level)
        age = now-self.began
        if self.heard_speech and now-self.last_sound >= self.silence_seconds:
            return 'send'
        if age > self.max_seconds:
            return 'send' if self.heard_speech else 'timeout'
        if not self.heard_speech and age >= self.timeout_seconds:
            return 'timeout'
        return 'keep'
