"""Browser-test launcher: real Studio with an in-memory audio status fixture."""
from pathlib import Path
import runpy
import sys
import time

root = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(root/'deps'),str(root)]
from studio import pad


class AudioFixture:
    def __init__(self):
        self.listening = self.music = False

    def snapshot(self):
        now = time.monotonic()
        return {'available':True,'listening':self.listening,'music':self.music,'error':None,
                'rhythm':{'bpm':120.,'confidence':.9,'feel':'lively','last_beat':now-now%.5,'age':.01,'level':1000.}}

    def set(self, **values):
        if values.get('music'):
            self.listening = True
        self.listening = values.get('listening',self.listening)
        self.music = values.get('music',self.music) and self.listening
        return self.snapshot()

    def close(self):
        pass


original = pad.default_pad
def create(*args,**kwargs):
    result = original(*args,**kwargs)
    result.audio.close()
    result.audio = AudioFixture()
    return result
pad.default_pad = create
sys.argv[0] = str(root/'run.py')
runpy.run_path(sys.argv[0],run_name='__main__')
