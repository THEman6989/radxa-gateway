import http.client
import importlib.util
import json
from pathlib import Path
import threading
import unittest
from unittest import mock
import http.server

spec = importlib.util.spec_from_file_location('fleet_server', Path(__file__).parents[1] / 'radxa/server.py')
server = importlib.util.module_from_spec(spec)
spec.loader.exec_module(server)

class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.http = http.server.HTTPServer(('127.0.0.1', 0), server.Handler)
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.thread.start()
        self.client = http.client.HTTPConnection(*self.http.server_address, timeout=10)

    def tearDown(self):
        self.client.close()
        self.http.shutdown()
        self.http.server_close()
        self.thread.join()

    def request(self, method, path, body=None, headers=None):
        self.client.request(method, path, body=body, headers=headers or {})
        r = self.client.getresponse()
        return r.status, r.read()

    def test_device_api_is_json(self):
        code, body = self.request('GET', '/api/devices')
        self.assertEqual(code, 200)
        self.assertEqual(len(json.loads(body)['devices']), 3)

    def test_unknown_target_never_falls_back_to_main(self):
        with mock.patch.object(server.subprocess, 'run') as run:
            code, _ = self.request('POST', '/api/devices/typo/shutdown')
        self.assertEqual(code, 404)
        run.assert_not_called()

    def test_cross_origin_requests_rejected(self):
        with mock.patch.object(server.subprocess, 'run') as run:
            code, _ = self.request('POST', '/wake', headers={'Origin': 'https://evil.invalid'})
        self.assertEqual(code, 403)
        run.assert_not_called()

    def test_main_action_legacy_command_preserved(self):
        with mock.patch.object(server.subprocess, 'run', return_value=mock.Mock(returncode=0, stdout='', stderr='')) as run:
            code, body = self.request('POST', '/api/devices/main/shutdown')
        self.assertEqual(code, 200)
        self.assertEqual(run.call_args.args[0][-1], 'sudo -n /usr/bin/systemctl poweroff')

    def test_extra_device_actions_use_the_correct_transport(self):
        fleet = server.get_fleet()
        for target, expected in [('mi50', 'amin@192.168.178.153'), ('unraid', 'root@192.168.178.52')]:
            with mock.patch.object(fleet, 'pause_watchdog'), \
                 mock.patch.object(server.subprocess, 'run', return_value=mock.Mock(returncode=0, stdout='', stderr='')) as run:
                code, body = self.request('POST', '/api/devices/' + target + '/shutdown')
            self.assertEqual(code, 200)
            self.assertIn(expected, run.call_args.args[0])
            self.assertTrue(run.call_args.args[0][-1].endswith(' shutdown'))

    def test_main_timeout_is_not_reported_as_success(self):
        import subprocess
        with mock.patch.object(server.subprocess, 'run', side_effect=subprocess.TimeoutExpired('ssh', 15)):
            code, body = self.request('POST', '/api/devices/main/reboot')
        self.assertEqual(json.loads(body)['status'], 'unknown')

    def test_no_legacy_page_on_unknown_routes(self):
        code, _ = self.request('GET', '/typo')
        self.assertEqual(code, 404)

    def test_malformed_hours_returns_400_without_action(self):
        code, _ = self.request('POST', '/api/devices/mi50/alwayson/start', '{"hours":-1}')
        self.assertEqual(code, 400)

    def test_page_has_named_tabs(self):
        _, body = self.request('GET', '/')
        for label in ('Haupt-PC', 'MI50-PC', 'Unraid-PC', 'role="tab"'):
            self.assertIn(label.encode(), body)

if __name__ == '__main__':
    unittest.main()
