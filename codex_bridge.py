"""Use the installed Codex client protocol; never edit Codex databases or sessions."""
import json
import os
from pathlib import Path
import queue
import shutil
import subprocess
import threading
import time

class CodexError(ValueError):
    pass

def executable():
    path=shutil.which('codex')
    if not path:
        raise CodexError('Codex CLI is unavailable. Open Codex and check its installation.')
    return path

def creation_flags():
    return subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0

class Client:
    def __init__(self, shared=False):
        self.lock=threading.Lock();self.messages=queue.Queue();self.sequence=0
        self.process=subprocess.Popen([executable(),'app-server',*(['proxy'] if shared else ['--stdio'])],stdin=subprocess.PIPE,stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,text=True,encoding='utf-8',bufsize=1,creationflags=creation_flags())
        self.reader=threading.Thread(target=self._read,daemon=True);self.reader.start()
        try:
            self.call('initialize',{'clientInfo':{'name':'codex_project_desk','title':'Project Desk','version':'2.0.0'}})
            self.process.stdin.write(json.dumps({'method':'initialized','params':{}})+'\n');self.process.stdin.flush()
        except Exception:
            self.close();raise

    def _read(self):
        try:
            for line in self.process.stdout:
                try:self.messages.put(json.loads(line))
                except json.JSONDecodeError:continue
        finally:self.messages.put(None)

    def call(self,method,params,timeout=20):
        with self.lock:
            self.sequence+=1;identity=self.sequence
            try:
                self.process.stdin.write(json.dumps({'id':identity,'method':method,'params':params})+'\n');self.process.stdin.flush()
            except (OSError,ValueError):
                raise CodexError('Codex connection closed. Open Codex and try again.')
            deadline=time.monotonic()+timeout
            while True:
                remaining=deadline-time.monotonic()
                if remaining<=0:raise CodexError('Codex did not respond in time. Try again.')
                try:message=self.messages.get(timeout=remaining)
                except queue.Empty:raise CodexError('Codex did not respond in time. Try again.')
                if message is None:raise CodexError('Could not connect to the running Codex service. Open Codex first.')
                if message.get('id')!=identity:continue
                if 'error' in message:raise CodexError(message['error'].get('message','Codex rejected the request.'))
                return message.get('result',{})

    def read_thread(self,identity):
        return self.call('thread/read',{'threadId':identity})['thread']

    def close(self):
        if self.process.poll() is None:
            self.process.terminate()
            try:self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:self.process.kill();self.process.wait(timeout=3)
        for stream in (self.process.stdin,self.process.stdout):
            if stream:stream.close()

    def __enter__(self):return self
    def __exit__(self,*args):self.close()
