"""Request boundaries for direct and reverse-proxied deployments."""

from hashlib import sha256
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from openpyxl import Workbook
from waitress.proxy_headers import proxy_headers_middleware
from werkzeug.test import Client
from werkzeug.wrappers import Response

from main import create_app


class DeploymentTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app(test_config={
            'TESTING': True, 'SECRET_KEY': 'deployment-test-key',
            'TRUSTED_HOSTS': ['words.example.org', 'localhost'],
        })

    def test_security_headers_cover_full_page_fragments_static_files_and_errors(self):
        for path, headers, status in [
            ('/', {}, 200), ('/', {'HX-Request': 'true'}, 200),
            ('/static/app.js', {}, 200), ('/missing', {}, 404),
        ]:
            with self.subTest(path=path, headers=headers):
                response = self.app.test_client().get(path, headers=headers)
                self.assertEqual(response.status_code, status)
                self.assertEqual(response.headers['X-Content-Type-Options'], 'nosniff')
                self.assertEqual(response.headers['X-Frame-Options'], 'DENY')
                self.assertEqual(response.headers['Referrer-Policy'], 'same-origin')
                policy = response.headers['Content-Security-Policy']
                self.assertIn("script-src 'self';", policy)
                self.assertIn("frame-ancestors 'none'", policy)
                self.assertNotIn('unsafe-eval', policy)
                self.assertNotIn('Access-Control-Allow-Origin', response.headers)
                response.close()

    def test_host_header_is_checked_even_for_htmx_and_static_requests(self):
        for path in ('/', '/static/app.js'):
            for headers in ({}, {'HX-Request': 'true'}):
                with self.subTest(path=path, headers=headers):
                    response = self.app.test_client().get(
                        path, base_url='http://attacker.example', headers=headers,
                    )
                    self.assertEqual(response.status_code, 400)
        response = self.app.test_client().get('/', base_url='http://words.example.org:8080')
        self.assertEqual(response.status_code, 200)

    def test_only_exact_trusted_proxy_can_supply_scheme_and_client_address(self):
        app = create_app(test_config={
            'TESTING': True, 'SECRET_KEY': 'proxy-test-key',
            'TRUSTED_HOSTS': ['words.example.org'], 'SESSION_COOKIE_SECURE': True,
        })

        @app.get('/request-info')
        def request_info():
            from flask import request
            return {
                'scheme': request.scheme, 'address': request.remote_addr,
                'host': request.host, 'forwarded_host': request.headers.get('X-Forwarded-Host'),
                'forwarded': request.headers.get('Forwarded'),
            }

        headers = {
            'X-Forwarded-Proto': 'https', 'X-Forwarded-For': '192.0.2.50, 198.51.100.20',
            'X-Forwarded-Host': 'attacker.example',
            'Forwarded': 'for=192.0.2.50;host=attacker.example;proto=https',
        }
        for trusted_proxy, peer, expected_scheme, expected_address in [
            (None, '127.0.0.1', 'http', '127.0.0.1'),
            ('127.0.0.1', '192.0.2.10', 'http', '192.0.2.10'),
            ('127.0.0.1', '127.0.0.1', 'https', '198.51.100.20'),
        ]:
            with self.subTest(trusted_proxy=trusted_proxy, peer=peer):
                client = Client(proxy_headers_middleware(
                    app.wsgi_app, trusted_proxy=trusted_proxy,
                    trusted_proxy_count=1,
                    trusted_proxy_headers={'x-forwarded-for', 'x-forwarded-proto'} if trusted_proxy else set(),
                    clear_untrusted=True,
                ), Response)
                response = client.get('/request-info', base_url='http://words.example.org',
                                      headers=headers, environ_overrides={'REMOTE_ADDR': peer})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json, {
                    'scheme': expected_scheme, 'address': expected_address,
                    'host': 'words.example.org', 'forwarded_host': None, 'forwarded': None,
                })
                self.assertEqual('Strict-Transport-Security' in response.headers, expected_scheme == 'https')

    def test_https_cookies_and_hsts_are_opt_in(self):
        response = self.app.test_client().get('/')
        cookie = response.headers['Set-Cookie']
        self.assertIn('HttpOnly', cookie)
        self.assertIn('SameSite=Lax', cookie)
        self.assertNotIn('; Secure', cookie)
        self.assertNotIn('Strict-Transport-Security', response.headers)

        app = create_app(test_config={'TESTING': True, 'SESSION_COOKIE_SECURE': True})
        for scheme in ('http', 'https'):
            response = app.test_client().get('/', base_url=f'{scheme}://localhost')
            self.assertIn('; Secure', response.headers['Set-Cookie'])
            self.assertEqual('Strict-Transport-Security' in response.headers, scheme == 'https')

    def test_oversize_searches_and_invalid_filters_do_not_update_preferences(self):
        client = self.app.test_client()
        client.get('/?search=1&q=crema')
        for query, status in [
            ({'search': '1', 'q': 'x' * 501}, 400),
            ({'search': '1', 'q': 'x' * 8193}, 414),
            ({'search': '1', 'column': 'not a real column'}, 400),
            ({'search': '1', 'label': 'not a real label'}, 400),
        ]:
            with self.subTest(query_length=len(str(query))):
                response = client.get('/', query_string=query)
                self.assertEqual(response.status_code, status)
                with client.session_transaction() as state:
                    self.assertEqual(state['search']['query'], 'crema')

    def test_files_outside_static_are_not_served_and_requests_cannot_write(self):
        client = self.app.test_client()
        for path in ('/db/example.xlsx', '/config.py', '/.git/config', '/requirements.txt',
                     '/static/../config.py', '/static/%2e%2e/main.py'):
            with self.subTest(path=path):
                self.assertEqual(client.get(path).status_code, 404)
        for method in ('post', 'put', 'patch', 'delete'):
            self.assertEqual(getattr(client, method)('/').status_code, 405)

        with TemporaryDirectory() as directory:
            path = Path(directory) / 'read-only.xlsx'
            workbook = Workbook()
            workbook.active.append([None, 'LIMBA FRANCEZĂ'])
            workbook.active.append(['ETIMON/', 'café'])
            workbook.save(path)
            workbook.close()
            path.chmod(0o444)
            original = sha256(path.read_bytes()).digest()
            app = create_app(path, test_config={'TESTING': True})
            self.assertEqual(app.test_client().get('/?search=1&q=cafe').status_code, 200)
            self.assertEqual(sha256(path.read_bytes()).digest(), original)
            self.assertEqual(path.stat().st_mode & 0o777, 0o444)
