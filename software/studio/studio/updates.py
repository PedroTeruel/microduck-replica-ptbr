"""Unprivileged, asynchronous bridge to the root coordinator's narrow IPC."""
import asyncio
import json
import os
from pathlib import Path
from . import helper

MAX_UPLOAD=160*1024*1024
OPS={'check','download','validate','install','rollback'}
NATIVE_OPS={'native_status','native_install','native_recover'}

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

def neutral_robot_command(method,params):
    """Only emergency/neutral output may cross a newly persisted update guard."""
    if method in {'robot.stop','robot.relax'}:return True
    if method=='robot.enable':return params.get('on') is False and params.get('toggle',False) is False
    if method in {'robot.move','robot.head'}:
        keys={'vx','vy','vyaw'} if method=='robot.move' else {'neck_pitch','head_pitch','head_yaw','head_roll'}
        return bool(params) and set(params)<=keys and all(type(value) in (int,float) and value==0 for value in params.values())
    if method=='robot.pose':return params=={'active':False}
    if method=='robot.mouth':return params=={'open':0.0}
    return method=='robot.sound' and params=={'tag':'wheee','hold':False}

class Updates:
    def __init__(self,address='unix:/run/microduck-updater/control.sock',marker='/run/microduck-updater/installing',
                 readiness='/run/microduck-studio/update.sock', *, native_call=None, native_state=None):
        self.address,self.marker,self.readiness=address,Path(marker),Path(readiness)
        self.server=None
        # Explicit dependencies are for local fixtures; production always uses the fixed helper.
        self.native_call=native_call or self._native_call
        self.native_state=native_state or helper.native_update_state
        self.native_task=None
        self.native_gate=asyncio.Lock()
        self.native_error=None

    def installing(self): return self.marker.exists() or self.native_state().get('active') is True

    def native_preparing(self): return self.native_gate.locked() or (self.native_task is not None and not self.native_task.done())

    @staticmethod
    def _native_call(by,action,**kwargs):
        if not helper.available(): return False,'unavailable',None
        return helper.robotd_update(by,action,**kwargs)

    async def native_status(self):
        persisted=self.native_state()
        try: ok,code,detail=await asyncio.to_thread(self.native_call,'Studio','status',timeout=10)
        except Exception: ok,code,detail=False,'unavailable',None
        fields=('active','phase','transaction_id','available','installed_sha256','target_sha256','running_verified','mode','reason')
        value={key:detail[key] for key in fields if isinstance(detail,dict) and key in detail} if ok else dict(persisted)
        if persisted.get('active') is True:
            value['active']=True
            if persisted.get('phase')=='recovery_required':
                value.update(phase='recovery_required',reason=persisted.get('reason'))
        value['service_available']=ok is True
        value['active']=value.get('active') is True
        value['available']=ok is True and value.get('available') is True
        value['supported']=ok is True and value.get('running_verified') is True
        value['current']=(value['supported'] and not value['active'] and
            isinstance(value.get('target_sha256'),str) and len(value['target_sha256'])==64 and
            value.get('installed_sha256')==value['target_sha256'])
        value['submitting']=self.native_preparing()
        value['request_error']=self.native_error
        if not ok and not value.get('reason'):
            value['reason']='O auxiliar instalado não oferece um serviço confiável de atualização do programa principal. Instale primeiro o pacote web/voz correspondente.'
        return value

    async def snapshot(self):
        result=await self.request()
        return {**result,'native':await self.native_status()}

    async def native_request(self,action,*,confirmed=None):
        if action=='status': return {'ok':True,'native':await self.native_status()}
        if action not in {'install','recover'} or confirmed is not True:
            raise UpdateError('validation','A atualização do programa principal exige confirmação explícita de que o robô está seguro e com os servos sem torque.')
        if self.native_preparing() or self.marker.exists():
            raise UpdateError('busy','Já há uma atualização em andamento. Aguarde ou consulte o estado novamente.',409)
        # Do not add this task to readiness or to the motion guard. Root first
        # queries app readiness, then writes the persistent exclusion itself.
        async def run():
            try:
                ok,code,detail=await asyncio.to_thread(self.native_call,'Studio',action,confirmed=True)
                if not ok:
                    reason=(detail or {}).get('reason') or (detail or {}).get('note') or str(code)
                    self.native_error=('A solicitação não teve resultado final; consulte o estado real novamente: '+str(reason))[:500]
            except Exception:
                self.native_error='A conexão da solicitação foi interrompida; a atualização independente do programa principal ainda pode estar em andamento. Consulte o estado real novamente.'
        async with self.native_gate:
            software=await self.request()
            if software.get('busy') is True:
                raise UpdateError('busy','A atualização web/voz ainda não terminou.',409)
            self.native_error=None
            self.native_task=asyncio.create_task(run())
        return {'ok':True,'native':await self.native_status()}

    async def connect(self):
        from .rpc import open_conn
        try: return await asyncio.wait_for(open_conn(self.address),2)
        except Exception: raise UpdateError('unavailable','O serviço de atualização de software não está instalado ou está temporariamente indisponível.',503) from None

    async def reply(self,reader):
        raw=await asyncio.wait_for(reader.readline(),20)
        if len(raw)>1024*1024 or not raw.endswith(b'\n'): raise UpdateError('service','A resposta do serviço de atualização foi interrompida.',503)
        result=json.loads(raw)
        if result.get('ok') is not True:
            code=result.get('code','service')
            raise UpdateError(code,str(result.get('error','A solicitação de atualização falhou.'))[:500],409 if code in {'busy','preflight','cache'} else 400)
        return result

    async def request(self,operation='status'):
        if operation not in OPS|{'status'}: raise UpdateError('validation','Operação de atualização não suportada.')
        if operation in {'install','rollback'} and (self.native_preparing() or self.native_state().get('active') is True):
            raise UpdateError('busy','A atualização do programa principal ainda não terminou. Conclua-a ou restaure o programa antes de continuar.',409)
        writer=None
        try:
            reader,writer=await self.connect()
            writer.write(json.dumps({'op':operation}).encode()+b'\n'); await writer.drain()
            return await self.reply(reader)
        except UpdateError as error:
            if operation=='status' and error.code=='unavailable':
                return {'ok':True,'available':False,'installed':None,'ready':False,'busy':False,'error':str(error)}
            raise
        except (OSError,ValueError,asyncio.TimeoutError): raise UpdateError('service','O serviço de atualização não respondeu. Tente novamente mais tarde.',503) from None
        finally:
            if writer: writer.close()

    async def upload(self,request):
        length=request.headers.get('content-length','')
        if not length.isdigit() or not 0<int(length)<=MAX_UPLOAD: raise UpdateError('oversize','O pacote de atualização deve ser um arquivo completo de 1 a 160 MiB.',413)
        reader,writer=await self.connect()
        try:
            writer.write(json.dumps({'op':'upload','size':int(length)}).encode()+b'\n'); await writer.drain()
            received=0
            async with asyncio.timeout(180):
                async for chunk in request.stream():
                    received+=len(chunk)
                    if received>int(length): raise UpdateError('oversize','O arquivo de atualização excede o tamanho permitido.',413)
                    writer.write(chunk); await writer.drain()
                if received!=int(length): raise UpdateError('upload','O envio do arquivo de atualização está incompleto.')
                return await self.reply(reader)
        except (OSError,ValueError,asyncio.TimeoutError): raise UpdateError('service','O envio foi interrompido. Selecione o arquivo novamente.',503) from None
        finally: writer.close()

    async def start_readiness(self,snapshot):
        self.readiness_snapshot=snapshot
        if os.name!='posix' or not self.readiness.parent.is_dir(): return
        if self.readiness.exists(): self.readiness.unlink()
        async def serve(reader,writer):
            try:
                raw=await asyncio.wait_for(reader.readline(),2)
                if raw==b'{"op": "readiness"}\n' or json.loads(raw)=={'op':'readiness'}:
                    result=snapshot()
                else: result={'ready':False,'error':'Solicitação interna não suportada.'}
                writer.write(json.dumps(result,ensure_ascii=False).encode()+b'\n'); await writer.drain()
            except Exception: pass
            finally: writer.close()
        self.server=await asyncio.start_unix_server(serve,path=str(self.readiness),limit=8192)
        self.readiness.chmod(0o600)

    async def stop_readiness(self):
        if self.server:
            self.server.close(); await self.server.wait_closed(); self.readiness.unlink(missing_ok=True)

async def handle(request,updates,session,has_password,local_dev,origin_ok):
    if not has_password and not local_dev: raise UpdateError('password_required','Configure uma senha para a interface web nas configurações antes de usar a atualização de software.',403)
    if not session: raise UpdateError('unauthorized','Faça login primeiro.',401)
    if request.method=='POST' and (not origin_ok or request.headers.get('x-csrf')!=session['csrf']):
        raise UpdateError('csrf','A origem da solicitação ou o token de login é inválido.',403)
    if request.url.path.endswith('/upload'): return await updates.upload(request)
    if request.method=='GET': return await updates.snapshot()
    data=bytearray()
    async for chunk in request.stream():
        data.extend(chunk)
        if len(data)>8192: raise UpdateError('oversize','A solicitação de atualização é grande demais.',413)
    try: body=json.loads(data)
    except (ValueError,RecursionError): raise UpdateError('validation','A solicitação de atualização não contém JSON válido.') from None
    if not isinstance(body,dict) or not isinstance(body.get('op'),str):
        raise UpdateError('validation','Operação ou campo de atualização não suportado.')
    if body['op'] in NATIVE_OPS:
        expected={'op'} if body['op']=='native_status' else {'op','confirmed'}
        if set(body)!=expected or (body['op']!='native_status' and body.get('confirmed') is not True):
            raise UpdateError('validation','A atualização do programa principal exige confirmação explícita e não aceita campos adicionais.')
        return await updates.native_request(body['op'][7:],confirmed=body.get('confirmed'))
    if set(body)!={'op'} or body['op'] not in OPS:
        raise UpdateError('validation','Operação ou campo de atualização não suportado.')
    return await updates.request(body['op'])
