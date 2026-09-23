import importlib.util
import subprocess
import unittest
from pathlib import Path
from unittest import mock


SERVER_PATH = Path(__file__).parents[1] / "radxa" / "server.py"
spec = importlib.util.spec_from_file_location("radxa_server_power", SERVER_PATH)
assert spec is not None
server = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(server)


class PowerActionTests(unittest.TestCase):
    def test_shutdown_uses_scoped_passwordless_systemctl_command(self):
        handler = mock.Mock()
        completed = subprocess.CompletedProcess(args=[], returncode=0, stdout="", stderr="")

        with mock.patch.object(server.subprocess, "run", return_value=completed) as run:
            server.Handler._run_ssh_shutdown(handler)

        run.assert_called_once_with(
            [
                "ssh",
                "-o",
                "StrictHostKeyChecking=no",
                "-o",
                "ConnectTimeout=5",
                "-p",
                "2222",
                "amin@localhost",
                "sudo -n /usr/bin/systemctl poweroff",
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
        handler._json.assert_called_once_with(
            {"status": "ok", "message": "Shutdown eingeleitet."}
        )


if __name__ == "__main__":
    unittest.main()
