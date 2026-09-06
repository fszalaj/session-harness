"""Transport boundary tests use fake connections and never call a provider."""
from decimal import Decimal
import json
import os
import ssl
import threading
import time
import unittest
from unittest.mock import MagicMock, patch

import api_transport as transport


class Response:
    def __init__(self, body=b'{"ok":true}', status=200, headers=None):
        self.body, self.status, self.headers = body, status, headers or {}
        self.reads = 0

    def getheader(self, key):
        return self.headers.get(key)

    def read1(self, size):
        self.reads += 1
        data, self.body = self.body[:size], self.body[size:]
        return data


class TransportTests(unittest.TestCase):
    def test_decimal_json_duplicate_nonfinite_and_invalid_bodies(self):
        self.assertEqual(transport.decode_json(b'{"cost":0.00000000011}')['cost'], Decimal('0.00000000011'))
        for body in (b'[]', b'{"a":1,"a":2}', b'{"cost":NaN}', b'{"cost":Infinity}', b'\xff'):
            with self.assertRaises(transport.APIError):
                transport.decode_json(body)

    def test_fixed_origin_paths_headers_and_size_validate_before_connect(self):
        invalid = [dict(origin='http://api.openai.com'), dict(origin='https://api.openai.com.evil'),
                   dict(origin='https://secret@api.openai.com'), dict(path='//evil/path'),
                   dict(path='/v1/\nsecret'), dict(headers={'Authorization': 'secret\r\nx:bad'}),
                   dict(headers={'Host': 'evil'}), dict(timeout=0), dict(timeout=True),
                   dict(body=b'x' * (transport.MAX_BODY + 1)), dict(method='DELETE')]
        with patch('api_transport._Connection') as connection:
            for changes in invalid:
                args = dict(origin='https://api.openai.com', path='/v1/models')
                args.update(changes)
                with self.subTest(changes=list(changes)), self.assertRaises(transport.APIError):
                    transport.request_json(**args)
            connection.assert_not_called()

    def test_environment_proxies_never_used_and_single_request(self):
        connection = MagicMock()
        connection.getresponse.return_value = Response()
        with patch.dict(os.environ, {'HTTPS_PROXY': 'https://private-proxy', 'ALL_PROXY': 'https://private-proxy'}), patch('api_transport._Connection', return_value=connection) as factory:
            result = transport.request_json('https://api.openai.com', '/v1/models', headers={'Authorization': 'Bearer private'})
        self.assertEqual(result, {'ok': True})
        self.assertEqual(factory.call_args.args[0], 'api.openai.com')
        self.assertEqual(connection.request.call_count, 1)
        connection.close.assert_called()

    def test_redirect_and_error_never_follow_read_or_echo_private_body(self):
        for status in (301, 302, 307, 308, 401, 429, 500):
            response = Response(body=b'{"error":"private-key"}', status=status,
                                headers={'Location': 'https://private.invalid/key'})
            connection = MagicMock()
            connection.getresponse.return_value = response
            with patch('api_transport._Connection', return_value=connection), self.assertRaises(transport.APIError) as caught:
                transport.request_json('https://api.x.ai', '/v1/chat/completions', 'POST', body=b'{}')
            self.assertEqual(str(caught.exception), 'api_http_error')
            self.assertEqual(connection.request.call_count, 1)
            self.assertEqual(response.reads, 0)

    def test_oversize_and_compression_reject(self):
        for headers in ({'Content-Length': str(transport.MAX_RESPONSE + 1)}, {'Content-Encoding': 'gzip'},
                        {'Content-Length': 'unknown'}):
            connection = MagicMock()
            response = Response(headers=headers)
            connection.getresponse.return_value = response
            with patch('api_transport._Connection', return_value=connection), self.assertRaises(transport.APIError):
                transport.request_json('https://api.x.ai', '/v1/models')
            self.assertEqual(response.reads, 0)
        connection = MagicMock()
        connection.getresponse.return_value = Response(body=b'x' * (transport.MAX_RESPONSE + 1))
        with patch('api_transport._Connection', return_value=connection), self.assertRaises(transport.APIError):
            transport.request_json('https://api.x.ai', '/v1/models')

    def test_total_deadline_even_when_headers_stall(self):
        stopped = threading.Event()
        connection = MagicMock()
        connection.getresponse.side_effect = lambda: (stopped.wait(3), Response())[1]
        connection.close.side_effect = stopped.set
        start = time.monotonic()
        with patch('api_transport._Connection', return_value=connection), self.assertRaises(transport.APIError) as caught:
            transport.request_json('https://api.x.ai', '/v1/models', timeout=0.05)
        self.assertEqual(caught.exception.status, 'api_timeout')
        self.assertLess(time.monotonic() - start, 0.5)
        self.assertTrue(stopped.is_set())

    def test_network_error_is_sanitized_and_not_retried(self):
        connection = MagicMock()
        connection.request.side_effect = OSError('private-key in network exception')
        with patch('api_transport._Connection', return_value=connection), self.assertRaises(transport.APIError) as caught:
            transport.request_json('https://api.x.ai', '/v1/models')
        self.assertEqual(str(caught.exception), 'api_transport_error')
        self.assertEqual(connection.request.call_count, 1)

    def test_tls_verification_default_and_cancel_prevents_late_send(self):
        cancel = threading.Event()
        connection = transport._Connection('api.x.ai', time.monotonic() + 5, cancel)
        self.assertTrue(connection._context.check_hostname)
        self.assertEqual(connection._context.verify_mode, ssl.CERT_REQUIRED)
        cancel.set()
        with patch.object(connection, 'connect') as connect, self.assertRaises(transport.APIError):
            connection.send(b'Authorization: private')
        connect.assert_not_called()
        connection.close()


    def test_tls_setup_error_is_sanitized(self):
        with patch('api_transport._Connection', side_effect=OSError('private local path')), self.assertRaises(transport.APIError) as caught:
            transport.request_json('https://api.x.ai', '/v1/models')
        self.assertEqual(str(caught.exception), 'api_transport_error')


if __name__ == '__main__':
    unittest.main()
