"""Opt-in microphone recording and spoken output via QtMultimedia and OpenAI.

No always-on listening. Audio recordings stay in memory and are sent to OpenAI
only when the user explicitly stops the recording. Speech output is a WAV file
created in the OS temporary directory and deleted when Buddy exits.
"""
import json
import os
import struct
import logging
import tempfile
import urllib.error
import urllib.request
import uuid
import wave
from io import BytesIO

from PySide6.QtCore import QObject, QBuffer, QIODevice, QUrl, Signal
from PySide6.QtMultimedia import (QAudioFormat, QAudioSource, QMediaDevices,
                                  QAudioOutput, QMediaPlayer)


def _request(url, body, content_type, timeout=60):
    key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not key:
        raise RuntimeError("OpenAI API key is missing in .env.")
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "Authorization": "Bearer " + key, "Content-Type": content_type,
        "User-Agent": "Buddy-Day-Zero/0.23"
    })
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            raise RuntimeError("OpenAI API quota or rate limit reached.") from exc
        raise RuntimeError("Voice service failed (HTTP %s)." % exc.code) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError("Could not connect to the voice service.") from exc


def transcribe_wav(wav_data):
    boundary = "buddy" + uuid.uuid4().hex
    parts = (
        "--" + boundary + "\r\n"
        'Content-Disposition: form-data; name="model"\r\n\r\n'
        "whisper-1\r\n"
        "--" + boundary + "\r\n"
        'Content-Disposition: form-data; name="file"; filename="speech.wav"\r\n'
        "Content-Type: audio/wav\r\n\r\n"
    ).encode() + wav_data + ("\r\n--" + boundary + "--\r\n").encode()
    raw = _request("https://api.openai.com/v1/audio/transcriptions", parts,
                   "multipart/form-data; boundary=" + boundary)
    result = json.loads(raw)
    text = result.get("text", "").strip()
    if not text:
        raise RuntimeError("I couldn't make out any words. Please try again.")
    return text


def synthesize_wav(text, voice="alloy"):
    if voice not in {"alloy","ash","ballad","coral","echo","fable","nova","onyx","sage","shimmer"}:
        voice = "alloy"
    data = json.dumps({
        "model": "tts-1", "voice": voice,
        "input": text[:4000], "response_format": "wav"
    }).encode("utf-8")
    audio = _request("https://api.openai.com/v1/audio/speech", data,
                     "application/json", timeout=90)
    if not audio.startswith(b"RIFF") or b"WAVE" not in audio[:16]:
        raise RuntimeError("Voice service returned invalid audio.")
    return audio
\n\ndef normalize_pcm_wav(data):
    """Rebuild a PCM WAV from real sample bytes, not unreliable RIFF sizes.

    Some streamed speech responses declare a placeholder-sized data chunk.
    Python wave.getnframes() then reports hours for a seconds-long response.
    Rewriting the header also makes Qt playback and caption timing agree.
    """
    if len(data) < 44 or data[:4] != b'RIFF' or data[8:12] != b'WAVE':
        raise ValueError('Speech service returned invalid WAV audio.')
    pos = 12
    fmt = None
    payload = None
    declared_size = None
    while pos + 8 <= len(data):
        tag = data[pos:pos+4]
        size = struct.unpack_from('<I', data, pos+4)[0]
        start = pos + 8
        if tag == b'fmt ':
            if size < 16 or start + 16 > len(data):
                raise ValueError('Invalid WAV format header.')
            fmt = data[start:start+16]
        if tag == b'data':
            payload = data[start:]
            declared_size = size
            break
        if size > len(data) - start:
            raise ValueError('Malformed WAV chunk.')
        pos = start + size + (size & 1)
    if fmt is None or payload is None:
        raise ValueError('Speech WAV is missing format or samples.')
    encoding, channels, rate, _, block_align, bits = struct.unpack('<HHIIHH', fmt)
    if encoding != 1 or channels not in (1, 2) or bits != 16 or rate < 8000:
        raise ValueError('Unsupported speech audio format.')
    if block_align != channels * 2:
        raise ValueError('Unexpected speech sample alignment.')
    payload = payload[:len(payload) - len(payload) % block_align]
    if not payload:
        raise ValueError('Speech WAV contains no audio.')
    actual_ms = round(1000 * len(payload) / (rate * block_align))
    header_ms = round(1000 * declared_size / (rate * block_align))
    if abs(header_ms - actual_ms) > 250:
        logging.getLogger('buddy.audio').warning(
            'Speech WAV declared %.2fs but contains %.2fs of PCM; repairing header',
            header_ms / 1000, actual_ms / 1000)
    result = BytesIO()
    with wave.open(result, 'wb') as output:
        output.setnchannels(channels)
        output.setsampwidth(2)
        output.setframerate(rate)
        output.writeframes(payload)
    return result.getvalue(), actual_ms


class Microphone(QObject):
    """Manual start/stop recording; Qt owns the native audio device."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.source = None
        self.buffer = None
        self.recorder = None

    def start(self):
        if self.source is not None:
            raise RuntimeError("Already recording.")
        device = QMediaDevices.defaultAudioInput()
        if device.isNull():
            raise RuntimeError("No microphone is available.")
        fmt = QAudioFormat()
        fmt.setSampleRate(16000)
        fmt.setChannelCount(1)
        fmt.setSampleFormat(QAudioFormat.Int16)
        if not device.isFormatSupported(fmt):
            fmt = device.preferredFormat()
            if fmt.sampleFormat() != QAudioFormat.Int16:
                raise RuntimeError("This microphone does not offer 16-bit PCM audio.")
        self.buffer = QBuffer(self)
        self.buffer.open(QIODevice.WriteOnly)
        self.source = QAudioSource(device, fmt, self)
        self.recorder = fmt
        self.source.start(self.buffer)

    def read_since(self, offset):
        """Read new PCM bytes without stopping the audio source."""
        if self.buffer is None:
            return b'', offset
        raw = bytes(self.buffer.data())
        end = len(raw)
        if end < offset:
            offset = 0
        return raw[offset:end], end

    def stop(self):
        if self.source is None:
            raise RuntimeError("Not recording.")
        self.source.stop()
        pcm = bytes(self.buffer.data())
        fmt = self.recorder
        self.source.deleteLater()
        self.buffer.close()
        self.buffer.deleteLater()
        self.source = self.buffer = self.recorder = None
        if len(pcm) < fmt.sampleRate() * fmt.channelCount() * 2 // 4:
            raise RuntimeError("Recording was too short. Please try again.")
        if len(pcm) > 20 * 1024 * 1024:
            raise RuntimeError("Recording too long. Try a shorter message.")
        out = BytesIO()
        with wave.open(out, "wb") as wav:
            wav.setnchannels(fmt.channelCount())
            wav.setsampwidth(2)
            wav.setframerate(fmt.sampleRate())
            wav.writeframes(pcm)
        return out.getvalue()

    def cancel(self):
        if self.source is not None:
            self.source.stop()
            self.source.deleteLater()
            self.buffer.close()
            self.buffer.deleteLater()
            self.source = self.buffer = self.recorder = None


class Speaker(QObject):
    speakingChanged = Signal(bool)
    error = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.player = QMediaPlayer(self)
        self.output = QAudioOutput(self)
        self.player.setAudioOutput(self.output)
        self.output.setVolume(0.8)
        self.player.playbackStateChanged.connect(self._state)
        self.player.errorOccurred.connect(self._error)
        self._file = None

    def play_wav(self, data):
        self.stop()
        self._file = tempfile.NamedTemporaryFile(prefix="buddy-voice-", suffix=".wav",
                                                  delete=False)
        self._file.write(data)
        self._file.close()
        self.player.setSource(QUrl.fromLocalFile(self._file.name))
        self.player.play()

    def stop(self):
        self.player.stop()
        self.player.setSource(QUrl())
        if self._file is not None:
            try: os.unlink(self._file.name)
            except OSError: pass
            self._file = None

    def _state(self, state):
        active = state == QMediaPlayer.PlayingState
        self.speakingChanged.emit(active)
        if state == QMediaPlayer.StoppedState and self._file is not None:
            # The backend no longer needs the file after playback stops.
            self.player.setSource(QUrl())
            try: os.unlink(self._file.name)
            except OSError: pass
            self._file = None

    def _error(self, error, message):
        if error != QMediaPlayer.NoError:
            self.error.emit("Audio playback failed: " + message)
