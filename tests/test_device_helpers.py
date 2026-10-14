import subprocess
from pathlib import Path
import unittest

ROOT = Path(__file__).parents[1]

class HelperTests(unittest.TestCase):
    def test_helpers_have_a_closed_action_allowlist(self):
        for name in ('linux-power.sh', 'unraid-power.sh'):
            path = ROOT / 'pc' / name
            self.assertTrue(path.exists(), name + ' missing')
            r = subprocess.run(['bash', str(path), 'not-an-action'], capture_output=True, text=True)
            self.assertNotEqual(r.returncode, 0)
            self.assertIn('Unsupported', r.stderr)
            subprocess.run(['bash', '-n', str(path)], check=True)

if __name__ == '__main__':
    unittest.main()
