"""Root-owned local IPC. No web-supplied paths, sources, engine verbs, or shell."""
import argparse
import json
import os
from pathlib import Path
import socket
import stat
import struct
import tempfile
import threading

from control import Controller, Engine, UpdateError, preflight
from package import MAX_OUTER

DEFAULT_CONFIG={
    'state_dir':'/var/lib/microduck-updater/control',
    'socket':'/run/microduck-updater/control.sock',
    'engine_socket':'/run/microduck-updater/engine.sock',
    'robot_socket':'/run/robotd.sock',
    'studio_socket':'/run/microduck-studio/update.sock',
    'audio_socket':'/run/duck-echo/control.sock',
    'marker':'/run/microduck-updater/installing',
    'allow_users':['radxa'], 'group':'radxa',
}

class Server:
    def __init__(self,controller,path,allowed_uids,group=None):
        self.controller,self.path,self.allowed_uids,self.group=controller,Path(path),set(allowed_uids),group
        self.slots=threading.BoundedSemaphore(8)
    def serve(self):
        self.path.parent.mkdir(parents=True,exist_ok=True,mode=0o755)
        if self.path.exists():
            if not stat.S_ISSOCK(self.path.lstat().st_mode): raise RuntimeError('IPC path is not a socket')
            self.path.unlink()
        with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM) as server:
            server.bind(str(self.path)); os.chmod(self.path,0o660)
            if self.group is not None: os.chown(self.path,0,self.group)
            server.listen(8)
            while True:
                connection,_=server.accept()
                if not self.slots.acquire(blocking=False): connection.close(); continue
                threading.Thread(target=self.handle,args=(connection,),daemon=True).start()
    def handle(self,connection):
        try:
            connection.settimeout(15)
            uid=struct.unpack('3i',connection.getsockopt(socket.SOL_SOCKET,socket.SO_PEERCRED,12))[1]
            if uid not in self.allowed_uids: raise UpdateError('unauthorized','本机用户无权操作更新服务')
            with connection.makefile('rb') as reader:
                raw=reader.readline(8193)
                if len(raw)>8192 or not raw.endswith(b'\n'): raise UpdateError('validation','更新请求过大')
                request=json.loads(raw)
                if not isinstance(request,dict): raise UpdateError('validation','更新请求必须为对象')
                op=request.get('op')
                if op=='status' and set(request)=={'op'}:
                    if not self.controller.busy: self.controller.refresh()
                    result=self.controller.view()
                elif op=='upload' and set(request)=={'op','size'}:
                    size=request['size']
                    if type(size) is not int or not 0<size<=MAX_OUTER: raise UpdateError('oversize','更新文件大小超限')
                    if self.controller.busy: raise UpdateError('busy','另一项更新任务正在进行')
                    # At most eight bounded temporary streams, root-private, with
                    # a short inactivity timeout and a total upload ceiling.
                    import time
                    deadline=time.monotonic()+180
                    with tempfile.TemporaryFile(dir=self.controller.root) as stream:
                        remaining=size
                        while remaining:
                            block=reader.read(min(1024*1024,remaining))
                            if not block or time.monotonic()>deadline: raise UpdateError('upload','上传中断或超时')
                            stream.write(block); remaining-=len(block)
                        stream.seek(0); result=self.controller.upload(stream)
                elif set(request)=={'op'}: result=self.controller.start(op)
                else: raise UpdateError('validation','更新请求包含不支持的字段')
                connection.sendall(json.dumps({'ok':True,**result},ensure_ascii=False).encode()+b'\n')
        except (OSError,ValueError,UpdateError) as error:
            try: connection.sendall(json.dumps({'ok':False,'code':getattr(error,'code','service'),
                'error':str(error)[:500] if isinstance(error,UpdateError) else '更新服务请求未完成'},ensure_ascii=False).encode()+b'\n')
            except OSError: pass
        finally:
            connection.close()
            self.slots.release()

def main():
    import grp
    import pwd
    parser=argparse.ArgumentParser(description=__doc__); parser.add_argument('--config',default='/etc/microduck-updater/control.json')
    args=parser.parse_args(); config_path=Path(args.config)
    info=config_path.stat()
    if info.st_uid!=0 or info.st_mode&0o022: raise RuntimeError('control config must be root-owned and not writable by group/others')
    config={**DEFAULT_CONFIG,**json.loads(config_path.read_bytes())}
    if os.geteuid()!=0: raise RuntimeError('update controller must run as root')
    import fcntl
    root=Path(config['state_dir']); root.mkdir(parents=True,exist_ok=True,mode=0o700)
    os.chmod(root,0o700)
    with open(root/'service.lock','w') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        controller=Controller(root,Engine(config['engine_socket']),lambda:preflight(config),marker=config['marker'])
        allowed={0,*[pwd.getpwnam(user).pw_uid for user in config['allow_users']]}
        Server(controller,config['socket'],allowed,grp.getgrnam(config['group']).gr_gid).serve()

if __name__=='__main__': main()
