import importlib.util
import time
import unittest
from pathlib import Path
from unittest import mock


SERVER_PATH = Path(__file__).parents[1] / "radxa" / "server.py"
spec = importlib.util.spec_from_file_location("radxa_server", SERVER_PATH)
assert spec is not None
server = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(server)


class AlwaysOnLifecycleTests(unittest.TestCase):
    def tearDown(self):
        server.stop_alwayson()

    def test_start_holds_suspend_guard_and_stop_releases_it(self):
        with (
            mock.patch.object(server, "_wol_cmd", return_value=True) as wol,
            mock.patch.object(server, "_start_pc_inhibitor", return_value=True) as acquire,
            mock.patch.object(server, "_stop_pc_inhibitor") as release,
        ):
            self.assertTrue(server.start_alwayson(1))
            status = server.alwayson_status()
            self.assertTrue(status["active"])
            wol.assert_called_once_with()
            acquire.assert_called_once_with()

            server.stop_alwayson()
            self.assertFalse(server.alwayson_status()["active"])
            release.assert_called()

    def test_status_exposes_verified_backend_only_while_holder_lives(self):
        living = mock.Mock()
        living.poll.return_value = None
        setattr(server, "_alwayson_inhibitor", living)
        status = server.alwayson_status()
        self.assertTrue(status["inhibitor_active"])
        self.assertEqual(status["inhibitor_backend"], "kde-powerdevil-suspend-only")

        living.poll.return_value = 1
        status = server.alwayson_status()
        self.assertFalse(status["inhibitor_active"])
        self.assertIsNone(status["inhibitor_backend"])

    def test_remote_helper_requests_suspend_only_policy(self):
        helper = (Path(__file__).parents[1] / "pc" / "plasma_suspend_helper.py").read_text()
        self.assertIn("INTERRUPT_SESSION = 1", helper)
        self.assertIn("CHANGE_SCREEN_SETTINGS = 4", helper)
        self.assertIn("AddInhibition", helper)
        self.assertIn("ReleaseInhibition", helper)
        self.assertIn("SimulateUserActivity", helper)


if __name__ == "__main__":
    unittest.main()
