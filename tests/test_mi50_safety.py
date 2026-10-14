import sys
from pathlib import Path
import tempfile
import unittest
from unittest import mock
sys.path.insert(0, str(Path(__file__).parents[1] / 'radxa'))

class SafetyTests(unittest.TestCase):
    def test_old_recovery_evidence_is_not_a_new_fault(self):
        import mi50_safety as m
        result=m.classify({'boot':'new','last_heartbeat':1000,'reason':'gpu-fault','evidence':'old crash','requested_at':10}, {}, True, 1001)
        self.assertEqual(result['level'],'ok')

    def test_current_fault_after_shutdown_is_visible_without_heartbeat(self):
        import mi50_safety as m
        result=m.classify({'boot':'b','last_heartbeat':100,'observed_fault':{'boot':'b','at':105,'evidence':'amdgpu ring timeout'}}, {'action':'shutdown','at':102,'boot':'b'}, False, 200)
        self.assertEqual(result['code'],'gpu-fault')

    def test_no_network_does_not_prove_shutdown_or_freeze(self):
        import mi50_safety as m
        result=m.classify({'boot':'b','last_heartbeat':100}, {'action':'shutdown','at':102,'boot':'b'}, False, 250)
        self.assertEqual(result['code'],'shutdown-unconfirmed')
        self.assertNotEqual(result['level'],'ok')

    def test_shutdown_overdue_with_live_host_warns(self):
        import mi50_safety as m
        self.assertEqual(m.classify({'boot':'b','last_heartbeat':250}, {'action':'shutdown','at':100,'boot':'b'}, True, 251)['code'],'shutdown-stalled')

    def test_new_boot_clears_old_fault_and_old_shutdown(self):
        import mi50_safety as m
        self.assertEqual(m.classify({'boot':'new','last_heartbeat':250,'observed_fault':{'boot':'old','at':200}}, {'action':'shutdown','at':100,'boot':'old'}, True, 251)['level'],'ok')

    def test_persisted_unknown_hardoff_blocks_a_second_dispatch(self):
        import mi50_safety as m
        with tempfile.TemporaryDirectory() as temp:
            safety=m.Safety(Path(temp)/'config.json',Path(temp)/'state.json')
            safety.save({'hardoff':{'status':'unknown','at':1}})
            with mock.patch.object(safety,'request') as request, mock.patch('mi50_safety.threading.Thread') as thread:
                self.assertEqual(safety.start_hardoff(mock.Mock())['status'],'error')
                request.assert_not_called();thread.assert_not_called()

    def test_async_hardoff_persists_completion_without_real_hardware(self):
        import mi50_safety as m
        import time
        with tempfile.TemporaryDirectory() as temp:
            safety=m.Safety(Path(temp)/'config.json',Path(temp)/'state.json')
            pause=mock.Mock()
            with mock.patch('mi50_safety.hardoff',return_value={'ok':True,'message':'TEST ONLY: completed'}):
                result=safety.start_hardoff(pause)
                self.assertEqual(result['status'],'ok')
                for _ in range(100):
                    state=safety.read(safety.path)
                    if state.get('hardoff',{}).get('status')=='done':break
                    time.sleep(.01)
                self.assertEqual(state['hardoff']['status'],'done')
                pause.assert_called_once()

    def test_pending_hardoff_blocks_other_device_actions(self):
        import devices
        fleet=devices.Fleet({'mi50':{'name':'MI50','host':'test','user':'amin','mac':'aa:bb:cc:dd:ee:ff'}},{})
        fleet.safety=mock.Mock()
        fleet.safety.pending.return_value=True
        with mock.patch('devices.subprocess.run') as run:
            response=fleet.action('mi50','wake')
            self.assertEqual(response['status'],'error')
            run.assert_not_called()

    def test_hardoff_requires_exact_controller_and_never_retries(self):
        import mi50_safety as m
        calls=[]
        def request(path,payload=None):
            calls.append((path,payload))
            return {'device_id':'wrong','wifi_connected':True,'pending_action':'none'}
        with self.assertRaises(RuntimeError): m.hardoff(request,lambda _:None)
        self.assertEqual(len(calls),1)

    def test_hardoff_waits_and_checks_completion(self):
        import mi50_safety as m
        replies=[{'device_id':'nodemcu-v3-main','wifi_connected':True,'pending_action':'none'},
                 {'ok':True,'status':'queued','action':'power-off','hold_seconds':8,'wait_seconds':0,'delay_before_action_seconds':0},
                 {'device_id':'nodemcu-v3-main','pending_action':'none','action_status':'done','last_action':'power-off done','last_error':''}]
        request=mock.Mock(side_effect=replies); wait=mock.Mock()
        result=m.hardoff(request,wait)
        self.assertTrue(result['ok']);wait.assert_called_once_with(9)
        self.assertEqual(request.call_args_list[1].args[1]['action'],'power-off')
        self.assertEqual(request.call_count,3)

if __name__=='__main__':unittest.main()
