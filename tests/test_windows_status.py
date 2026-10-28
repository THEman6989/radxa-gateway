import unittest
from unittest import mock
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).parents[1]/'radxa'))
from devices import Fleet

class WindowsStatusTests(unittest.TestCase):
    def test_windows_presence_and_state_are_separate_from_linux(self):
        fleet=Fleet({'main':{'name':'Haupt-PC','host':'linux','windows':{'host':'win','user':'amin','mac':'00:11:22:33:44:55','control_ready':False}}},None)
        with mock.patch.object(fleet,'probe',side_effect=lambda d:d['host']=='linux'):
            d=fleet.status()['devices'][0]
        self.assertTrue(d['online'])
        self.assertFalse(d['windows']['online'])
        self.assertFalse(d['windows']['control_ready'])

    def test_unconfigured_windows_control_never_spawns(self):
        fleet=Fleet({'main':{'name':'Haupt-PC','host':'linux','windows':{'host':'win','control_ready':False}}},None)
        with mock.patch('devices.subprocess.run') as run:
            result=fleet.action('main','winshutdown')
        self.assertEqual(result['status'],'error')
        run.assert_not_called()

    def test_mi50_has_no_windows_section_in_status(self):
        fleet=Fleet({'mi50':{'name':'MI50','host':'linux'}},None)
        with mock.patch.object(fleet,'probe',return_value=False):
            d=fleet.status()['devices'][0]
        self.assertIsNone(d['windows'])

    def test_hidden_grid_is_actually_hidden(self):
        page=Path(__file__).parents[1].joinpath('radxa/index.html').read_text()
        self.assertIn('[hidden]{display:none!important}',page)

if __name__=='__main__':unittest.main()
