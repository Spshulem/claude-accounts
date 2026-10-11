import contextlib
import io
import runpy
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

MODULE = runpy.run_path(str(Path(__file__).resolve().parent / 'claude-accounts'))

class FailoverEligibilityTests(unittest.TestCase):
    def run_case(self, wired=True, token=True, credentials=False, limited=False, manual=False):
        fn = MODULE['cmd_use' if manual else 'cmd_auto']
        g = fn.__globals__
        readings = {
            'acct2': {'ok': True, 'windows': [{'name': 'session', 'pct': 100}]},
            'acct3': {'ok': True, 'windows': [{'name': 'session', 'pct': 100 if limited else 20}]},
        }
        with patch.dict(g, {
            'labels': lambda: ['acct2', 'acct3'],
            'active': lambda: 'acct2',
            'load_state': lambda: {},
            'save_state': lambda state: None,
            'usage': lambda label, state, **kwargs: readings[label],
            'read_credentials': lambda label: {'login': True} if credentials else None,
            'conductor_wired': lambda: wired,
            'token_present': lambda label: token,
            'retire_exhausted': lambda state, keep: None,
            'identity': lambda label: None,
            'log': lambda msg: None,
        }), patch.dict(g, {'switch': unittest.mock.Mock()}) as _:
            switch = g['switch']
            args = SimpleNamespace(label='acct3', now=False, threshold=None, dry_run=False, verbose=False)
            with contextlib.redirect_stdout(io.StringIO()):
                result = fn(args)
            return result, switch.call_args

    def test_auto_accepts_conductor_token_without_cli_login(self):
        result, call = self.run_case()
        self.assertEqual(result, 0)
        self.assertEqual(call.args, ('acct3',))
        self.assertFalse(call.kwargs['retire'])

    def test_manual_accepts_conductor_token_without_cli_login(self):
        result, call = self.run_case(manual=True)
        self.assertEqual(result, 0)
        self.assertEqual(call.args, ('acct3',))

    def test_auto_rejects_missing_token_and_login(self):
        result, call = self.run_case(token=False)
        self.assertEqual(result, 2)
        self.assertIsNone(call)

    def test_manual_rejects_missing_token_and_login(self):
        with self.assertRaises(SystemExit):
            self.run_case(token=False, manual=True)

    def test_token_only_slot_requires_conductor_wiring(self):
        result, call = self.run_case(wired=False)
        self.assertEqual(result, 2)
        self.assertIsNone(call)

    def test_exhausted_token_slot_is_not_selected(self):
        result, call = self.run_case(limited=True)
        self.assertEqual(result, 2)
        self.assertIsNone(call)

    def test_cli_login_remains_eligible_without_conductor(self):
        result, call = self.run_case(wired=False, token=False, credentials=True)
        self.assertEqual(result, 0)
        self.assertEqual(call.args, ('acct3',))

if __name__ == '__main__':
    unittest.main()
