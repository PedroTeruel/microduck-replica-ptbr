"""Authenticated updater boundary over real HTTP; unavailable is never fake success."""
import unittest
from unittest import mock
from tests import test_ai_http as ai_http
from tests.test_http import WsClient

class UpdatesHttp(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=ai_http.AiHttp.asyncSetUp
    asyncTearDown=ai_http.AiHttp.asyncTearDown
    call=ai_http.AiHttp.call
    def test_emergency_gate_uses_real_pad_stop_and_motion_protocol(self):
        from studio.updates import safe_during_update
        for name,args in [('relax',{}),('pad.op',{'op':'stop'}),('pad.op',{'op':'action_stop'}),
                ('pad.op',{'op':'motion','action':'stop'}),('pad.op',{'op':'motion','action':'idle_stop'}),
                ('pad.op',{'op':'audio','listening':False,'music':False})]:
            self.assertTrue(safe_during_update(name,args),(name,args))
        for args in ({'op':'motion','action':'play'},{'op':'audio','listening':True},
                {'op':'audio','listening':False,'music':True},{'op':'drive','x':1}):
            self.assertFalse(safe_during_update('pad.op',args),args)
    async def test_updates_require_password_login_csrf_host_and_no_store(self):
        for method in ('GET','POST'):
            status,headers,_=await self.call(method,'/api/updates',{'op':'check'} if method=='POST' else None)
            self.assertEqual(status,401); self.assertEqual(headers.get('cache-control'),'no-store')
        for headers in ({**self.headers,'Origin':'http://evil.example'},
                        {key:value for key,value in self.headers.items() if key!='X-CSRF'}):
            status,_,_=await self.call('POST','/api/updates',{'op':'check'},headers)
            self.assertEqual(status,403)
        for method,headers in (('PUT',self.headers),('GET',{'Host':'evil.example'})):
            _,headers,_=await self.call(method,'/api/updates',headers=headers)
            self.assertEqual(headers.get('cache-control'),'no-store')
        self.auth.clear_password()
        status,_,data=await self.call('GET','/api/updates',headers=self.headers)
        self.assertEqual(status,403); self.assertEqual(data['code'],'password_required')

    async def test_uninstalled_controller_and_no_arbitrary_privileged_verbs(self):
        status,headers,data=await self.call('GET','/api/updates',headers=self.headers)
        self.assertEqual(status,200); self.assertFalse(data['available'])
        self.assertIsNone(data['installed']); self.assertEqual(headers.get('cache-control'),'no-store')
        for body in ({'op':'shell','command':'id'},{'op':'install','from_dir':'/tmp/evil'},
                     {'op':'download','url':'http://evil.example'},{'op':[]},[],b'x'*8193):
            status,_,_=await self.call('POST','/api/updates',body,self.headers)
            self.assertIn(status,(400,413))

    async def test_upload_limit_and_csrf_precede_body_consumption(self):
        status,headers,_=await self.call('POST','/api/updates/upload',b'x',{'Origin':self.origin})
        self.assertEqual(status,401); self.assertEqual(headers.get('cache-control'),'no-store')
        status,_,_=await self.call('POST','/api/updates/upload',b'x',{**self.headers,'Content-Length':str(160*1024*1024+1)})
        self.assertEqual(status,413)

    async def test_installation_gates_motion_on_server_and_keeps_emergency_relax(self):
        token=self.headers['Cookie'].split('=',1)[1]
        client=WsClient(self.port,origin=self.origin,cookie=token);await client.open()
        try:
            with mock.patch('studio.updates.Updates.installing',return_value=True):
                for index,name in enumerate(('servo.open','imu.op','calib.op','pad.op','tune.op')):
                    await client.send({'t':'cmd','id':str(index),'name':name,'args':{'op':'move'}})
                    await client.pump(until=lambda:any(message.get('id')==str(index) and message.get('t')=='result' for message in client.msgs))
                    result=next(message for message in client.msgs if message.get('id')==str(index) and message.get('t')=='result')
                    self.assertFalse(result['ok']);self.assertIn('软件更新',result['reason'])
                await client.send({'t':'cmd','id':'relax','name':'relax'})
                await client.pump(until=lambda:any(message.get('id')=='relax' and message.get('t')=='result' for message in client.msgs))
                result=next(message for message in client.msgs if message.get('id')=='relax' and message.get('t')=='result')
                self.assertTrue(result['ok'],result)
        finally:client.close()
