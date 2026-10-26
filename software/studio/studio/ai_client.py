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


def validate_messages(messages):
    if not isinstance(messages, list) or not 1 <= len(messages) <= 12:
        raise AiError('validation', '对话最多 12 条消息，请清空后重试')
    total = 0
    for index, message in enumerate(messages):
        if (not isinstance(message, dict) or set(message) != {'role','content'}
                or message['role'] != ('user' if index % 2 == 0 else 'assistant')
                or not isinstance(message['content'], str) or not message['content'].strip()
                or len(message['content']) > (2000 if index % 2 == 0 else OUTPUT_LIMIT)
                or '\x00' in message['content']):
            raise AiError('validation', '消息格式不正确，用户输入最多 2000 字，模型回复最多 4000 字')
        total += len(message['content'])
    if total > 12000 or messages[-1]['role'] != 'user':
        raise AiError('validation', '对话过长或顺序不正确，请清空后重试')
    return messages


class CompatibleClient:
    def __init__(self, timeout=15):
        self.timeout = timeout
        self._gate = threading.BoundedSemaphore(2)

    def complete(self, config, messages, *, max_tokens=512):
        validate_messages(messages)
        if not self._gate.acquire(blocking=False):
            raise AiError('busy', 'AI 请求正在进行，请稍后重试', 429)
        connection = None
        try:
            url = urlsplit(base_url(config['base_url']))
            cls = http.client.HTTPSConnection if url.scheme == 'https' else http.client.HTTPConnection
            connection = cls(url.hostname, url.port, timeout=self.timeout)
            deadline = time.monotonic() + self.timeout
            body = json.dumps({'model':config['model'], 'messages':messages, 'stream':False,
                               'max_tokens':max_tokens}, ensure_ascii=False).encode('utf-8')
            headers = {'Content-Type':'application/json', 'Accept':'application/json'}
            if config['auth_mode'] == 'bearer':
                headers['Authorization'] = 'Bearer ' + config['api_key']
            connection.request('POST', (url.path.rstrip('/') or '') + '/chat/completions', body, headers)
            response = connection.getresponse()
            if response.status != 200:
                code, message = {
                    401:('auth','API Key 无效或尚未开通'),
                    403:('forbidden','提供商拒绝访问，请检查模型权限'),
                    404:('not_found','模型或接口路径不存在，请检查 Base URL 和 Model ID'),
                    429:('rate_limit','提供商限流或余额不足，请稍后检查'),
                }.get(response.status, ('redirect','提供商重定向已拒绝，请填写最终接口地址')
                      if 300 <= response.status < 400 else ('provider','提供商请求失败'))
                raise AiError(code,message,502)
            parts, size = [], 0
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError()
                if connection.sock:
                    connection.sock.settimeout(remaining)
                part = response.read1(min(8192, BODY_LIMIT + 1 - size))
                if not part:
                    break
                parts.append(part)
                size += len(part)
                if size > BODY_LIMIT:
                    raise AiError('oversize','提供商回复过大',502)
            try:
                data = json.loads(b''.join(parts))
                result = data['choices'][0]['message']['content']
                if not isinstance(result,str) or not result.strip():
                    raise ValueError()
            except (ValueError, TypeError, KeyError, IndexError, RecursionError):
                raise AiError('malformed','提供商未返回有效文字回复',502) from None
            if len(result) > OUTPUT_LIMIT:
                raise AiError('oversize','提供商回复文字过长',502)
            key = config.get('api_key')
            return result.replace(key,'[已隐藏]') if key else result
        except socket.gaierror:
            raise AiError('dns','无法解析提供商地址，请检查网络和 Base URL',502) from None
        except ssl.SSLError:
            raise AiError('tls','提供商 HTTPS 证书或 TLS 连接失败',502) from None
        except (TimeoutError, socket.timeout):
            raise AiError('timeout','AI 请求超时，请稍后重试',504) from None
        except (OSError, http.client.HTTPException):
            raise AiError('provider','无法连接提供商，请检查服务和网络',502) from None
        finally:
            if connection:
                connection.close()
            self._gate.release()
