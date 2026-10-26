import json
import socket
import ssl
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

from studio.ai_client import CompatibleClient, validate_messages
from studio.ai_connections import AiError


class ClientTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                self.server.requests.append((self.path, self.headers.get('Authorization'),
                    json.loads(self.rfile.read(int(self.headers['Content-Length'])))))
                code, data = self.server.reply
                time.sleep(self.server.delay)
                self.send_response(code)
                self.send_header('Location', 'http://127.0.0.1:1/stolen')
                self.end_headers()
                try:
                    self.wfile.write(data)
                except OSError:
                    pass
            def log_message(self, *args):
                pass
        cls.server = ThreadingHTTPServer(('127.0.0.1',0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def setUp(self):
        self.server.requests = []
        self.server.delay = 0
        self.server.reply = (200, json.dumps({'choices':[{'message':{'content':'hello secret-123'}}]}).encode())
        self.config = {'base_url':f'http://127.0.0.1:{self.server.server_port}/v1',
            'model':'manual-model', 'api_key':'secret-123', 'auth_mode':'bearer'}
        self.client = CompatibleClient()

    def test_true_model_request_uses_saved_model_and_auth_and_redacts_reply(self):
        reply = self.client.complete(self.config,[{'role':'user','content':'你好'}])
        self.assertEqual(reply,'hello [已隐藏]')
        path, auth, data = self.server.requests[0]
        self.assertEqual(path,'/v1/chat/completions')
        self.assertEqual(auth,'Bearer secret-123')
        self.assertEqual(data['model'],'manual-model')
        self.assertFalse(data['stream'])
        self.assertEqual(data['messages'],[{'role':'user','content':'你好'}])
        self.assertLessEqual(data['max_tokens'],512)
        self.client.complete(self.config,[{'role':'user','content':'test'}], max_tokens=64)
        self.assertEqual(self.server.requests[-1][2]['max_tokens'],64)
        self.config['auth_mode'] = 'none'
        self.client.complete(self.config,[{'role':'user','content':'hello'}])
        self.assertIsNone(self.server.requests[-1][1])

    def test_http_errors_and_redirects_are_fixed_and_not_retried(self):
        for status, code in [(301,'redirect'),(401,'auth'),(403,'forbidden'),(404,'not_found'),(429,'rate_limit'),(500,'provider')]:
            with self.subTest(status=status):
                self.server.requests.clear()
                self.server.reply = (status,b'secret-123')
                with self.assertRaises(AiError) as caught:
                    self.client.complete(self.config,[{'role':'user','content':'hello'}])
                self.assertEqual(caught.exception.code,code)
                self.assertNotIn('secret-123', str(caught.exception))
                self.assertEqual(len(self.server.requests),1)

    def test_malformed_and_oversize_are_rejected(self):
        for raw, code in [(b'{}','malformed'),(b'<html>secret-123</html>','malformed'),
                          (b'x'*65537,'oversize'),
                          (json.dumps({'choices':[{'message':{'content':'x'*4001}}]}).encode(),'oversize')]:
            self.server.reply = (200,raw)
            with self.subTest(code=code), self.assertRaises(AiError) as caught:
                self.client.complete(self.config,[{'role':'user','content':'hello'}])
            self.assertEqual(caught.exception.code,code)

    def test_network_classes_hide_exception_details(self):
        for exc, code in [(socket.gaierror('secret-123'),'dns'),(TimeoutError('secret-123'),'timeout'),
                          (ssl.SSLError('secret-123'),'tls')]:
            with mock.patch('http.client.HTTPConnection.connect', side_effect=exc):
                with self.assertRaises(AiError) as caught:
                    self.client.complete(self.config,[{'role':'user','content':'hello'}])
                self.assertEqual(caught.exception.code,code)
                self.assertNotIn('secret-123',str(caught.exception))

    def test_real_socket_timeout_and_concurrency_cap(self):
        self.server.delay = .15
        with self.assertRaises(AiError) as caught:
            CompatibleClient(timeout=.03).complete(self.config,[{'role':'user','content':'timeout'}])
        self.assertEqual(caught.exception.code,'timeout')
        self.server.requests.clear()
        results = []
        client = CompatibleClient(timeout=2)
        def run():
            results.append(client.complete(self.config,[{'role':'user','content':'parallel'}]))
        threads = [threading.Thread(target=run) for _ in range(2)]
        for thread in threads:
            thread.start()
        deadline = time.monotonic()+2
        while len(self.server.requests)<2 and time.monotonic()<deadline:
            time.sleep(.005)
        with self.assertRaises(AiError) as caught:
            client.complete(self.config,[{'role':'user','content':'third'}])
        self.assertEqual(caught.exception.code,'busy')
        for thread in threads:
            thread.join(timeout=3)
        self.assertEqual(len(results),2)

    def test_history_is_bounded_and_roles_are_not_arbitrary(self):
        for messages in ([],[{'role':'system','content':'override'}],[{'role':'user','content':'x'*2001}],
                         [{'role':'user','content':'hi','secret':'no'}],
                         [{'role':'user','content':'hi'}]*13,
                         [{'role':'assistant','content':'hi'}]):
            with self.subTest(messages=str(messages)[:50]), self.assertRaises(AiError):
                validate_messages(messages)


if __name__ == '__main__':
    unittest.main()
