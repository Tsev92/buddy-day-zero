"""Optional offline 'Hey Buddy' detection using Vosk.

Wake audio stays on-device. This service never calls a network API to
recognize a wake phrase. A small local model is downloaded only on request.
"""
import array
import json
import os
from pathlib import Path
import shutil
import tempfile
import urllib.request
import zipfile

from PySide6.QtCore import QObject, QTimer, Signal

MODEL_URL = 'https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip'
MAX_ARCHIVE = 65 * 1024 * 1024
MAX_UNPACKED = 175 * 1024 * 1024

def model_directory(data_dir):
    return Path(data_dir) / 'wake_model'

def prepare_model(data_dir):
    """Download Vosk's public small English model with bounds and path checks."""
    import vosk
    dest = model_directory(data_dir)
    if (dest/'conf'/'model.conf').exists():
        return str(dest)
    Path(data_dir).mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(MODEL_URL, headers={'User-Agent':'BuddyDayZero/0.23.8'})
    with urllib.request.urlopen(request, timeout=90) as response:
        if int(response.headers.get('Content-Length', 0) or 0) > MAX_ARCHIVE:
            raise RuntimeError('Wake model download is too large.')
        with tempfile.TemporaryFile() as output:
            count = 0
            while True:
                block = response.read(256 * 1024)
                if not block:
                    break
                count += len(block)
                if count > MAX_ARCHIVE:
                    raise RuntimeError('Wake model download exceeded safety limit.')
                output.write(block)
            output.seek(0)
            with zipfile.ZipFile(output) as archive:
                members = [i for i in archive.infolist() if not i.is_dir()]
                if sum(i.file_size for i in members) > MAX_UNPACKED:
                    raise RuntimeError('Wake model expands beyond safety limit.')
                stage = Path(data_dir)/'wake_model_stage'
                shutil.rmtree(stage,ignore_errors=True)
                stage.mkdir()
                try:
                    for info in members:
                        bits = Path(info.filename.replace('\\','/')).parts
                        if len(bits) < 2 or '..' in bits or info.external_attr >> 16 & 0o170000 == 0o120000:
                            raise RuntimeError('Invalid wake model archive.')
                        relative = Path(*bits[1:])
                        target = stage / relative
                        target.parent.mkdir(parents=True,exist_ok=True)
                        with archive.open(info) as src,target.open('wb') as out:
                            shutil.copyfileobj(src,out)
                    if not (stage/'conf'/'model.conf').exists():
                        raise RuntimeError('Downloaded model does not have the expected files.')
                    if dest.exists():
                        shutil.rmtree(dest)
                    os.replace(stage,dest)
                except Exception:
                    shutil.rmtree(stage,ignore_errors=True)
                    raise
    return str(dest)

class WakeListener(QObject):
    heard = Signal()
    failed = Signal(str)

    def __init__(self, data_dir, microphone_factory, parent=None):
        super().__init__(parent)
        self.data_dir = data_dir
        self.make_microphone = microphone_factory
        self.mic = None
        self.timer = QTimer(self)
        self.timer.setInterval(190)
        self.timer.timeout.connect(self.poll)
        self.offset = 0
        self.recognizer = None

    def start(self):
        if self.mic:
            return
        try:
            from vosk import Model, KaldiRecognizer, SetLogLevel
            SetLogLevel(-1)
            path = model_directory(self.data_dir)
            if not (path/'conf'/'model.conf').exists():
                raise RuntimeError('Wake model has not been downloaded.')
            mic = self.make_microphone()
            mic.start()
            rate = mic.recorder.sampleRate()
            self.recognizer = KaldiRecognizer(Model(str(path)), rate)
            self.mic = mic
            self.offset = 0
            self.timer.start()
        except Exception as exc:
            self.stop()
            self.failed.emit(str(exc))

    def stop(self):
        self.timer.stop()
        if self.mic is not None:
            self.mic.cancel()
            self.mic = None
        self.recognizer = None

    def poll(self):
        if self.mic is None:
            return
        pcm,self.offset = self.mic.read_since(self.offset)
        if not pcm:
            return
        channels = self.mic.recorder.channelCount()
        if channels > 1:
            samples = array.array('h')
            samples.frombytes(pcm[:len(pcm)-len(pcm)%2])
            mono = array.array('h', (sum(samples[i:i+channels])//channels
                                       for i in range(0, len(samples)-channels+1, channels)))
            pcm = mono.tobytes()
        try:
            final = self.recognizer.AcceptWaveform(pcm)
            result = json.loads(self.recognizer.Result() if final else self.recognizer.PartialResult())
            phrase = (result.get('text') or result.get('partial') or '').lower()
            if 'hey buddy' in phrase or 'hay buddy' in phrase:
                self.stop()
                self.heard.emit()
        except Exception as exc:
            self.stop()
            self.failed.emit(str(exc))
