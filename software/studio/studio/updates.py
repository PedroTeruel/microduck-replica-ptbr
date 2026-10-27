"""Unprivileged, asynchronous bridge to the root coordinator's narrow IPC."""
import asyncio
import json
import os
from pathlib import Path

MAX_UPLOAD=160*1024*1024
OPS={'check','download','validate','install','rollback'}

def safe_during_update(name,args):
    if name in {'relax','servo.ports'}:return True
    if name!='pad.op' or not isinstance(args,dict):return False
    if args.get('op') in {'stop','action_stop','walk_stop'}:return True
    if args.get('op')=='motion' and args.get('action') in {'stop','idle_stop','record_finish'}:return True
    if args.get('op')=='audio':
        switches={key:value for key,value in args.items() if key!='op'}
        return bool(switches) and set(switches)<={'listening','music'} and all(value is False for value in switches.values())
    return False

class UpdateError(Exception):
    def __init__(self,code,message,status=400): super().__init__(message); self.code,self.status=code,status

class Updates:
    def __init__(self,address='unix:/run/microduck-updater/control.sock',marker='/run/microduck-updater/installing',
                 readiness='/run/microduck-studio/update.sock'):
        self.address,self.marker,self.readiness=address,Path(marker),Path(readiness)
        self.server=None

    def installing(self): return self.marker.exists()

    async def connect(self):
        from .rpc import open_conn
        try: return await asyncio.wait_for(open_conn(self.address),2)
        except Exception: raise UpdateError('unavailable','软件更新服务尚未安装或暂时不可用',503) from None

    async def reply(self,reader):
        raw=await asyncio.wait_for(reader.readline(),20)
        if len(raw)>1024*1024 or not raw.endswith(b'\n'): raise UpdateError('service','更新服务回包中断',503)
        result=json.loads(raw)
        if result.get('ok') is not True:
            code=result.get('code','service')
            raise UpdateError(code,str(result.get('error','更新请求失败'))[:500],409 if code in {'busy','preflight','cache'} else 400)
        return result

    async def request(self,operation='status'):
        if operation not in OPS|{'status'}: raise UpdateError('validation','不支持的更新操作')
        writer=None
        try:
            reader,writer=await self.connect()
            writer.write(json.dumps({'op':operation}).encode()+b'\n'); await writer.drain()
            return await self.reply(reader)
        except UpdateError as error:
            if operation=='status' and error.code=='unavailable':
                return {'ok':True,'available':False,'installed':None,'ready':False,'busy':False,'error':str(error)}
            raise
        except (OSError,ValueError,asyncio.TimeoutError): raise UpdateError('service','更新服务暂时没有回应，请稍后重试',503) from None
        finally:
            if writer: writer.close()

    async def upload(self,request):
        length=request.headers.get('content-length','')
        if not length.isdigit() or not 0<int(length)<=MAX_UPLOAD: raise UpdateError('oversize','更新包必须为 1 至 160 MiB 的完整文件',413)
        reader,writer=await self.connect()
        try:
            writer.write(json.dumps({'op':'upload','size':int(length)}).encode()+b'\n'); await writer.drain()
            received=0
            async with asyncio.timeout(180):
                async for chunk in request.stream():
                    received+=len(chunk)
                    if received>int(length): raise UpdateError('oversize','更新文件大小超限',413)
                    writer.write(chunk); await writer.drain()
                if received!=int(length): raise UpdateError('upload','更新文件上传不完整')
                return await self.reply(reader)
        except (OSError,ValueError,asyncio.TimeoutError): raise UpdateError('service','上传中断，请重新选择文件',503) from None
        finally: writer.close()

    async def start_readiness(self,snapshot):
        if os.name!='posix' or not self.readiness.parent.is_dir(): return
        if self.readiness.exists(): self.readiness.unlink()
        async def serve(reader,writer):
            try:
                raw=await asyncio.wait_for(reader.readline(),2)
                if raw==b'{"op": "readiness"}\n' or json.loads(raw)=={'op':'readiness'}:
                    result=snapshot()
                else: result={'ready':False,'error':'不支持的内部请求'}
                writer.write(json.dumps(result,ensure_ascii=False).encode()+b'\n'); await writer.drain()
            except Exception: pass
            finally: writer.close()
        self.server=await asyncio.start_unix_server(serve,path=str(self.readiness),limit=8192)
        self.readiness.chmod(0o600)

    async def stop_readiness(self):
        if self.server:
            self.server.close(); await self.server.wait_closed(); self.readiness.unlink(missing_ok=True)

async def handle(request,updates,session,has_password,local_dev,origin_ok):
    if not has_password and not local_dev: raise UpdateError('password_required','请先在设置中配置网页密码，再使用软件更新',403)
    if not session: raise UpdateError('unauthorized','请先登录',401)
    if request.method=='POST' and (not origin_ok or request.headers.get('x-csrf')!=session['csrf']):
        raise UpdateError('csrf','请求来源或登录令牌不正确',403)
    if request.url.path.endswith('/upload'): return await updates.upload(request)
    if request.method=='GET': return await updates.request()
    data=bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data)>8192: raise UpdateError('oversize','更新请求过大',413)
    try: body=json.loads(data)
    except (ValueError,RecursionError): raise UpdateError('validation','更新请求不是有效 JSON') from None
    if not isinstance(body,dict) or set(body)!={'op'} or not isinstance(body['op'],str) or body['op'] not in OPS:
        raise UpdateError('validation','不支持的更新操作或字段')
    return await updates.request(body['op'])
