"""Bounded, non-streaming Chat Completions adapter. No retries or redirects."""
import http.client
import json
import socket
import ssl
import threading
import time
from urllib.parse import urlsplit

from .ai_connections import AiError, base_url

BODY_LIMIT = 65536
OUTPUT_LIMIT = 4000


class RequestControl:
    """Interrupt connected I/O, including a response owned by HTTPResponse.

    Python's OS DNS resolver cannot be interrupted here. An expired resolution/
    connect is checked before sending any request or credentials. Connection and
    TLS setup also retain their socket timeout.
    """
    def __init__(self):
        self.stopped = threading.Event()
        self._lock = threading.Lock()
        self._socket = None

    @staticmethod
    def _shutdown(sock):
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                sock.close()
            except OSError:
                pass

    def bind(self, sock):
        with self._lock:
            self._socket = sock
            stopped = self.stopped.is_set()
        if stopped:
            self._shutdown(sock)
        self.check()

    def cancel(self):
        self.stopped.set()
        with self._lock:
            sock = self._socket
        self._shutdown(sock)

    def unbind(self):
        with self._lock:
            self._socket = None

    def check(self):
        if self.stopped.is_set():
            raise TimeoutError()


def validate_messages(messages):
    if not isinstance(messages, list) or not 1 <= len(messages) <= 12:
        raise AiError('validation', 'A conversa aceita no máximo 12 mensagens. Limpe o histórico e tente novamente.')
    total = 0
    for index, message in enumerate(messages):
        if (not isinstance(message, dict) or set(message) != {'role','content'}
                or message['role'] != ('user' if index % 2 == 0 else 'assistant')
                or not isinstance(message['content'], str) or not message['content'].strip()
                or len(message['content']) > (2000 if index % 2 == 0 else OUTPUT_LIMIT)
                or '\x00' in message['content']):
            raise AiError('validation', 'Formato de mensagem inválido. A entrada do usuário pode ter até 2.000 caracteres e a resposta do modelo, até 4.000.')
        total += len(message['content'])
    if total > 12000 or messages[-1]['role'] != 'user':
        raise AiError('validation', 'A conversa é longa demais ou está fora de ordem. Limpe o histórico e tente novamente.')
    return messages


class CompatibleClient:
    def __init__(self, timeout=15):
        self.timeout = timeout
        self._gate = threading.BoundedSemaphore(2)

    def complete(self, config, messages, *, max_tokens=512, cancel=None):
        validate_messages(messages)
        if not self._gate.acquire(blocking=False):
            raise AiError('busy', 'Já há uma solicitação de IA em andamento. Tente novamente em instantes.', 429)
        connection = response = watchdog = None
        control = cancel if cancel is not None else RequestControl()
        try:
            control.check()
            url = urlsplit(base_url(config['base_url']))
            cls = http.client.HTTPSConnection if url.scheme == 'https' else http.client.HTTPConnection
            connection = cls(url.hostname, url.port, timeout=self.timeout)
            deadline = time.monotonic() + self.timeout
            watchdog = threading.Timer(self.timeout,control.cancel)
            watchdog.daemon = True
            watchdog.start()
            body = json.dumps({'model':config['model'], 'messages':messages, 'stream':False,
                               'max_tokens':max_tokens}, ensure_ascii=False).encode('utf-8')
            headers = {'Content-Type':'application/json', 'Accept':'application/json'}
            if config['auth_mode'] == 'bearer':
                headers['Authorization'] = 'Bearer ' + config['api_key']
            connection.connect()
            # getresponse() may transfer this socket to HTTPResponse (and clear
            # connection.sock), so retain the actual socket before parsing headers.
            control.bind(connection.sock)
            if time.monotonic() >= deadline:
                raise TimeoutError()
            connection.request('POST', (url.path.rstrip('/') or '') + '/chat/completions', body, headers)
            response = connection.getresponse()
            control.check()
            if response.status != 200:
                code, message = {
                    401:('auth','Chave de API inválida ou não ativada.'),
                    403:('forbidden','O provedor recusou o acesso. Verifique as permissões do modelo.'),
                    404:('not_found','O modelo ou o caminho da API não existe. Verifique a URL base e o ID do modelo.'),
                    429:('rate_limit','O provedor limitou as solicitações ou o saldo é insuficiente. Verifique novamente mais tarde.'),
                }.get(response.status, ('redirect','O redirecionamento do provedor foi recusado. Informe o endereço final da API.')
                      if 300 <= response.status < 400 else ('provider','A solicitação ao provedor falhou.'))
                raise AiError(code,message,502)
            parts, size = [], 0
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError()
                control.check()
                part = response.read1(min(8192, BODY_LIMIT + 1 - size))
                control.check()
                if not part:
                    break
                parts.append(part)
                size += len(part)
                if size > BODY_LIMIT:
                    raise AiError('oversize','A resposta do provedor é grande demais.',502)
            try:
                data = json.loads(b''.join(parts))
                result = data['choices'][0]['message']['content']
                if not isinstance(result,str) or not result.strip():
                    raise ValueError()
            except (ValueError, TypeError, KeyError, IndexError, RecursionError):
                raise AiError('malformed','O provedor não retornou uma resposta de texto válida.',502) from None
            if len(result) > OUTPUT_LIMIT:
                raise AiError('oversize','A resposta de texto do provedor é longa demais.',502)
            control.check()
            key = config.get('api_key')
            return result.replace(key,'[oculto]') if key else result
        except socket.gaierror:
            if control.stopped.is_set():
                raise AiError('timeout','A solicitação de IA expirou ou foi cancelada. Tente novamente em instantes.',504) from None
            raise AiError('dns','Não foi possível resolver o endereço do provedor. Verifique a rede e a URL base.',502) from None
        except ssl.SSLError:
            if control.stopped.is_set():
                raise AiError('timeout','A solicitação de IA expirou ou foi cancelada. Tente novamente em instantes.',504) from None
            raise AiError('tls','Falha no certificado HTTPS ou na conexão TLS do provedor.',502) from None
        except (TimeoutError, socket.timeout):
            raise AiError('timeout','A solicitação de IA expirou. Tente novamente em instantes.',504) from None
        except (OSError, http.client.HTTPException):
            if control.stopped.is_set():
                raise AiError('timeout','A solicitação de IA expirou ou foi cancelada. Tente novamente em instantes.',504) from None
            raise AiError('provider','Não foi possível conectar ao provedor. Verifique o serviço e a rede.',502) from None
        finally:
            if watchdog:
                watchdog.cancel()
            control.unbind()
            try:
                if response:
                    response.close()
                if connection:
                    connection.close()
            finally:
                self._gate.release()
