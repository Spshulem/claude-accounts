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



class QuotaFreshnessTests(unittest.TestCase):
    def auto(self, current, candidates):
        fn = MODULE['cmd_auto']
        readings = {'current': current, **candidates}
        switch = unittest.mock.Mock()
        with patch.dict(fn.__globals__, {
            'labels': lambda: list(readings),
            'active': lambda: 'current',
            'load_state': lambda: {},
            'save_state': lambda state: None,
            'usage': lambda label, state, **kwargs: readings[label],
            'read_credentials': lambda label: {'login': True},
            'conductor_wired': lambda: True,
            'token_present': lambda label: True,
            'retire_exhausted': lambda state, keep: None,
            'identity': lambda label: None,
            'log': lambda msg: None,
            'switch': switch,
        }), contextlib.redirect_stdout(io.StringIO()) as output:
            result = fn(SimpleNamespace(threshold=None, dry_run=False, verbose=True))
        return result, switch, output.getvalue()

    def reading(self, percent, stale=False):
        return {'ok': True, 'stale': stale, 'windows': [{'name': 'weekly', 'pct': percent}]}

    def test_stale_weekly_only_active_switches_to_fresh_spare(self):
        result, switch, _ = self.auto(self.reading(29, stale=True), {'spare': self.reading(16)})
        self.assertEqual(result, 0)
        self.assertEqual(switch.call_args.args, ('spare',))

    def test_unreadable_active_switches_to_fresh_spare(self):
        result, switch, _ = self.auto({'ok': False, 'error': 'not logged in'}, {'spare': self.reading(0)})
        self.assertEqual(result, 0)
        self.assertEqual(switch.call_args.args, ('spare',))

    def test_stale_candidates_do_not_cause_blind_switching(self):
        result, switch, output = self.auto(self.reading(29, stale=True), {'spare': self.reading(0, stale=True)})
        self.assertEqual(result, 2)
        switch.assert_not_called()
        self.assertIn('quota unavailable', output)
        self.assertNotIn('fine', output)

    def test_exhausted_active_ranks_fresh_headroom_above_stale(self):
        result, switch, _ = self.auto(self.reading(100), {'stale': self.reading(0, stale=True), 'fresh': self.reading(40)})
        self.assertEqual(result, 0)
        self.assertEqual(switch.call_args.args, ('fresh',))

    def test_fresh_active_does_not_switch(self):
        result, switch, _ = self.auto(self.reading(40), {'spare': self.reading(0)})
        self.assertEqual(result, 0)
        switch.assert_not_called()


class MenuQuotaFreshnessTests(unittest.TestCase):
    def test_stale_active_shows_unknown_title_and_cached_warning(self):
        plugin = runpy.run_path(str(Path(__file__).resolve().parent / 'menubar' / 'claude-accounts.3m.py'))
        render = plugin['render']
        account = {'active': True, 'identity': 'Mock account', 'label': 'slot', 'token': True,
                   'usage': {'ok': True, 'stale': True, 'windows': [{'name': 'weekly', 'pct': 29}]}}
        with patch.dict(render.__globals__, {
            'claude': lambda refresh: {'active': 'slot', 'accounts': [account]},
            'codex': lambda refresh: (None, None, False),
            'config': lambda: {},
        }), contextlib.redirect_stdout(io.StringIO()) as output:
            render(False)
        lines = output.getvalue().splitlines()
        self.assertEqual(lines[0], '✳ ?')
        self.assertTrue(any('Cached limits; current quota unavailable' in line for line in lines))

if __name__ == '__main__':
    unittest.main()
