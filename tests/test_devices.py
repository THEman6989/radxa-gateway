import importlib.util
import json
from pathlib import Path
import sys
import unittest
from unittest import mock

ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / 'radxa'))

class DevicesTests(unittest.TestCase):
    def test_named_devices_have_independent_status(self):
        path = ROOT / 'radxa' / 'devices.py'
        self.assertTrue(path.exists(), 'Multi-device backend is missing')
        import devices
        fleet = devices.Fleet({'main': {'name': 'Haupt-PC', 'host': 'localhost', 'port': 2222},
                               'mi50': {'name': 'MI50-PC', 'host': '192.0.2.2', 'port': 22},
                               'unraid': {'name': 'Unraid-PC', 'host': '192.0.2.3', 'port': 22}}, {})
        with mock.patch.object(fleet, 'probe', side_effect=lambda d: d['host'] == 'localhost'):
            state = fleet.status()
        self.assertEqual([d['id'] for d in state['devices']], ['main', 'mi50', 'unraid'])
        self.assertEqual([d['online'] for d in state['devices']], [True, False, False])
        self.assertEqual(state['devices'][0]['name'], 'Haupt-PC')

    def fleet(self):
        import devices
        return devices.Fleet({'mi50': {'name': 'MI50-PC', 'host': '192.0.2.2', 'user': 'amin',
                             'mac': 'b4:2e:99:89:35:14', 'helper': '/usr/local/sbin/radxa-power',
                             'pause_file': '/nonexistent/test-paused'}}, {})

    def test_unknown_target_and_action_never_execute(self):
        fleet = self.fleet()
        with mock.patch('devices.subprocess.run') as run:
            for target, action in [('typo', 'shutdown'), ('mi50', 'rm -rf /')]:
                with self.assertRaises(ValueError):
                    fleet.action(target, action)
            run.assert_not_called()

    def test_shutdown_uses_named_target_and_pauses_watchdog(self):
        fleet = self.fleet()
        result = mock.Mock(returncode=0, stdout='', stderr='')
        with mock.patch('devices.subprocess.run', return_value=result) as run, \
             mock.patch.object(fleet, 'pause_watchdog') as pause:
            response = fleet.action('mi50', 'shutdown')
        pause.assert_called_once()
        args = run.call_args.args[0]
        self.assertIn('amin@192.0.2.2', args)
        self.assertEqual(args[-1], 'sudo -n /usr/local/sbin/radxa-power shutdown')
        self.assertEqual(response['status'], 'ok')

    def test_timeout_is_unknown_not_success(self):
        import subprocess
        fleet = self.fleet()
        with mock.patch('devices.subprocess.run', side_effect=subprocess.TimeoutExpired('ssh', 15)), \
             mock.patch.object(fleet, 'pause_watchdog'):
            self.assertEqual(fleet.action('mi50', 'reboot')['status'], 'unknown')

    def test_wake_uses_target_mac_and_broadcast(self):
        fleet = self.fleet()
        with mock.patch('devices.subprocess.run', return_value=mock.Mock(returncode=0, stdout='', stderr='')) as run:
            fleet.action('mi50', 'wake')
        self.assertEqual(run.call_args.args[0], ['/usr/bin/wakeonlan', '-i', '192.168.2.255', '-p', '9', 'b4:2e:99:89:35:14'])

    def test_wakewin_only_for_flagged_devices_and_uses_windows_mac(self):
        import devices
        fleet = self.fleet()
        with self.assertRaises(ValueError):
            fleet.action('mi50', 'wakewin')
        fleet.config['unraid'] = dict(fleet.config['mi50'], name='Unraid-PC',
                                      windows={'mac': 'e4:54:e8:b7:2d:f4', 'host': '192.0.2.9', 'port': 22, 'user': 'amine'})
        import threading
        fleet.locks['unraid'] = threading.Lock()
        with mock.patch('devices.subprocess.run', return_value=mock.Mock(returncode=0, stdout='', stderr='')) as run:
            result = fleet.action('unraid', 'wakewin')
        self.assertEqual(result['status'], 'ok')
        self.assertIn('Windows', result['message'])
        self.assertEqual(run.call_args.args[0], ['/usr/bin/wakeonlan', '-i', '192.168.2.255', '-p', '9', 'e4:54:e8:b7:2d:f4'])
        with mock.patch('devices.subprocess.run') as run:
            with self.assertRaises(ValueError):
                fleet.action('main', 'wakewin')
            run.assert_not_called()

    def test_win_power_actions_use_windows_ssh_transport(self):
        import devices
        fleet = self.fleet()
        with self.assertRaises(ValueError):
            fleet.action('mi50', 'winshutdown')
        fleet.config['unraid'] = dict(fleet.config['mi50'], name='Unraid-PC',
                                      windows={'mac': 'e4:54:e8:b7:2d:f4', 'host': '192.0.2.9', 'port': 22, 'user': 'amine'})
        import threading
        fleet.locks['unraid'] = threading.Lock()
        import base64, devices as devmod
        self.assertEqual(base64.b64decode(devmod.WIN_SUSPEND_B64).decode('utf-16le'),
                         "Add-Type -AssemblyName System.Windows.Forms; "
                         "[void][System.Windows.Forms.Application]::SetSuspendState('Suspend', $false, $false)")
        expected = {'winsleep': 'powershell -NoProfile -NonInteractive -EncodedCommand ' + devmod.WIN_SUSPEND_B64,
                    'winreboot': 'shutdown /r /t 0',
                    'winshutdown': 'shutdown /s /t 0'}
        for action, cmd in expected.items():
            with mock.patch('devices.subprocess.run', return_value=mock.Mock(returncode=0, stdout='', stderr='')) as run:
                result = fleet.action('unraid', action)
            self.assertEqual(result['status'], 'ok')
            args = run.call_args.args[0]
            self.assertEqual(args[-1], cmd)
            self.assertIn('amine@192.0.2.9', args)

    def test_alwayson_has_independent_holders(self):
        fleet = self.fleet()
        fleet.config['unraid'] = dict(fleet.config['mi50'], name='Unraid-PC')
        import threading
        fleet.locks['unraid'] = threading.Lock()
        with mock.patch('devices.threading.Thread') as thread, mock.patch.object(fleet, 'action', return_value={'status': 'ok'}):
            fleet.start('mi50', 1)
            fleet.start('unraid', 2)
            self.assertTrue(fleet.alwayson('mi50')['active'])
            self.assertTrue(fleet.alwayson('unraid')['active'])
            fleet.stop('mi50')
            self.assertFalse(fleet.alwayson('mi50')['active'])
            self.assertTrue(fleet.alwayson('unraid')['active'])
            fleet.stop('unraid')

    def test_status_uses_network_probe_not_repeated_ssh_handshakes(self):
        import devices
        with mock.patch('devices.subprocess.run', return_value=mock.Mock(returncode=0)) as run:
            self.assertTrue(devices.Fleet.probe({'host': 'localhost', 'status_host': '192.0.2.44'}))
        self.assertEqual(run.call_args.args[0][-1], '192.0.2.44')
        self.assertEqual(run.call_args.args[0][0], 'ping')

    def test_invalid_hours_rejected_without_wake(self):
        fleet = self.fleet()
        with mock.patch.object(fleet, 'action') as action:
            for value in [-1, 10000, '1', True, float('inf')]:
                with self.assertRaises(ValueError):
                    fleet.start('mi50', value)
            action.assert_not_called()

if __name__ == '__main__':
    unittest.main()
