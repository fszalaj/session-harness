"""Bounded HTTPS JSON transport with fixed origins and no redirects or retries."""
from decimal import Decimal
import http.client
import json
import math
import queue
import re
import ssl
import threading
import time
from urllib.parse import urlsplit

ORIGINS = frozenset({
    'https://api.openai.com', 'https://api.anthropic.com',
    'https://generativelanguage.googleapis.com', 'https://api.x.ai',
    'https://api.deepseek.com', 'https://api.moonshot.ai',
    'https://api.z.ai', 'https://openrouter.ai',
    'https://api.groq.com', 'https://api.mistral.ai',
    'https://router.huggingface.co', 'https://huggingface.co',
    'https://api.morphllm.com', 'https://integrate.api.nvidia.com',
    'https://api.meta.ai', 'https://ollama.com',
})
MAX_BODY = 2_000_000
MAX_RESPONSE = 8_000_000


class APIError(ValueError):
    """Public errors contain a fixed status only, never provider diagnostics."""
    def __init__(self, status, http_status=None):
        self.status = status
        self.http_status = http_status if type(http_status) is int and 100 <= http_status <= 599 else None
        super().__init__(status)


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise APIError('invalid_api_json')
        result[key] = value
    return result


def _invalid_constant(_):
    raise APIError('invalid_api_json')


def _json_decimal(value):
    if len(value) > 256:
        raise APIError('invalid_api_json')
    return Decimal(value)


def decode_json(data):
    try:
        result = json.loads(data, parse_float=_json_decimal, parse_constant=_invalid_constant,
                            object_pairs_hook=_unique)
        if not isinstance(result, dict):
            raise APIError('invalid_api_json')
        return result
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise APIError('invalid_api_json') from None


def validate_request(origin, path, method, headers, body, timeout):
    if origin not in ORIGINS:
        raise APIError('unsupported_api_origin')
    if (not isinstance(path, str) or not path.startswith('/') or path.startswith('//')
            or not path.isascii() or re.search(r'[\x00-\x20\x7f#]', path)
            or urlsplit(path).scheme or urlsplit(path).netloc):
        raise APIError('invalid_api_path')
    if method not in {'GET', 'POST'} or not isinstance(body, bytes) or len(body) > MAX_BODY:
        raise APIError('invalid_api_request')
    if method == 'GET' and body:
        raise APIError('invalid_api_request')
    if (type(timeout) not in (int, float) or not math.isfinite(timeout)
            or not 0 < timeout <= 600):
        raise APIError('invalid_api_timeout')
    allowed = {'authorization', 'x-api-key', 'x-goog-api-key', 'anthropic-version',
               'content-type', 'accept'}
    if not isinstance(headers, dict):
        raise APIError('invalid_api_headers')
    for key, value in headers.items():
        if (not isinstance(key, str) or key.lower() not in allowed
                or not isinstance(value, str) or not value or not value.isascii()
                or re.search(r'[\x00-\x1f\x7f]', value)):
            raise APIError('invalid_api_headers')


class _Connection(http.client.HTTPSConnection):
    def __init__(self, host, deadline, cancelled):
        self.deadline, self.cancelled = deadline, cancelled
        super().__init__(host, timeout=max(0.001, deadline - time.monotonic()),
                         context=ssl.create_default_context())

    def _remaining(self):
        remaining = self.deadline - time.monotonic()
        if self.cancelled.is_set() or remaining <= 0:
            raise APIError('api_timeout')
        return remaining

    def connect(self):
        self.timeout = self._remaining()
        super().connect()
        self.sock.settimeout(self._remaining())

    def send(self, data):
        self._remaining()
        if self.sock is None:
            self.connect()
        self.sock.settimeout(self._remaining())
        super().send(data)


def request_json(origin, path, method='GET', *, headers=None, body=b'', timeout=120):
    """No billing inference is made from an exception after a request starts."""
    if headers is not None and not isinstance(headers, dict):
        raise APIError('invalid_api_headers')
    headers = {} if headers is None else dict(headers)
    validate_request(origin, path, method, headers, body, timeout)
    deadline = time.monotonic() + timeout
    cancelled, output = threading.Event(), queue.Queue(maxsize=1)
    try:
        connection = _Connection(urlsplit(origin).hostname, deadline, cancelled)
    except Exception:
        raise APIError('api_transport_error') from None

    def work():
        try:
            connection.request(method, path, body=body or None, headers=headers)
            response = connection.getresponse()
            if not 200 <= response.status < 300:
                raise APIError('api_http_error', response.status)
            encoding = response.getheader('Content-Encoding')
            if encoding and encoding.lower() != 'identity':
                raise APIError('unsupported_api_encoding')
            length = response.getheader('Content-Length')
            if length is not None and (not length.isdigit() or int(length) > MAX_RESPONSE):
                raise APIError('api_response_too_large')
            chunks, size = [], 0
            while True:
                remaining = deadline - time.monotonic()
                if cancelled.is_set() or remaining <= 0:
                    raise APIError('api_timeout')
                if connection.sock is not None:
                    connection.sock.settimeout(remaining)
                chunk = response.read1(min(65536, MAX_RESPONSE - size + 1))
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_RESPONSE:
                    raise APIError('api_response_too_large')
                chunks.append(chunk)
            value = decode_json(b''.join(chunks))
            if not cancelled.is_set():
                output.put_nowait((True, value))
        except Exception as exc:
            status = exc.status if isinstance(exc, APIError) else 'api_transport_error'
            if not cancelled.is_set():
                output.put_nowait((False, (status, getattr(exc, 'http_status', None))))
        finally:
            connection.close()

    worker = threading.Thread(target=work, name='session-harness-api', daemon=True)
    try:
        worker.start()
    except Exception:
        connection.close()
        raise APIError('api_transport_error') from None
    try:
        success, value = output.get(timeout=max(0.001, deadline - time.monotonic()))
        if not success:
            raise APIError(*value)
        return value
    except queue.Empty:
        raise APIError('api_timeout') from None
    finally:
        cancelled.set()
        connection.close()
