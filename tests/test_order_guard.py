import ast
import tempfile
import unittest
from collections import Counter
from pathlib import Path

import auto_selector
import order_guard as guard

ROOT = Path(__file__).resolve().parents[1]


class RepositoryGuardTests(unittest.TestCase):
    def test_no_broker_order_call_exists_outside_the_reviewed_allowlist(self):
        findings = guard.scan_repo(ROOT)
        self.assertEqual([f for f in findings if not f['allowed']], [])

    def test_the_allowlist_is_exact_including_counts_so_it_cannot_go_stale_or_grow_silently(self):
        seen = Counter((f['file'], f['where'], f['finding']) for f in guard.scan_repo(ROOT))
        self.assertEqual(dict(seen), guard.ALLOWLIST)

    def test_a_violation_or_an_extra_allowed_call_is_reported_as_not_allowed(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'bot.py').write_text('def go(kite):\n    kite.place_order(variety="regular")\n', encoding='utf-8')
            (root / 'app.py').write_text('class Handler:\n    def do_POST(self):\n        self.place_order(1)\n'
                                         '        self.place_order(2)\n', encoding='utf-8')
            files = [root / 'bot.py', root / 'app.py']
            allowed = {(f['file'], f['line']): f['allowed'] for f in guard.scan_repo(root, files)}
        self.assertEqual(allowed, {('bot.py', 2): False, ('app.py', 3): True, ('app.py', 4): False})

    def test_only_the_guard_itself_is_skipped_and_it_makes_no_broker_call(self):
        self.assertEqual(guard.SELF, 'order_guard.py')
        tree = ast.parse((ROOT / guard.SELF).read_text(encoding='utf-8'))
        calls = {n.func.attr if isinstance(n.func, ast.Attribute) else getattr(n.func, 'id', None)
                 for n in ast.walk(tree) if isinstance(n, ast.Call)}
        self.assertFalse(calls & guard.ORDER_METHODS)
        imported = {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        imported |= {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
        self.assertEqual(imported, {'ast', 're', 'subprocess', 'collections', 'pathlib'})

    def test_the_tracked_file_list_covers_the_app_and_skips_virtual_environments(self):
        files = {p.relative_to(ROOT).as_posix() for p in guard.tracked_files(ROOT)}
        self.assertIn('app.py', files)
        self.assertIn('web/app.js', files)
        self.assertFalse(any(part in guard.SKIP_PARTS for name in files for part in Path(name).parts))


class AllowedSitesAreLockedTests(unittest.TestCase):
    """Each allowlisted site must keep the protection that justifies it."""

    def setUp(self):
        self.app = ast.parse((ROOT / 'app.py').read_text(encoding='utf-8'))

    @staticmethod
    def method(tree, cls, name):
        klass = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == cls)
        return next(n for n in klass.body if isinstance(n, ast.FunctionDef) and n.name == name)

    def test_live_execution_ready_is_bound_exactly_once_at_top_level_to_false(self):
        bindings = []
        for node in ast.walk(self.app):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target] if isinstance(node, (ast.AugAssign, ast.AnnAssign)) else []
            bindings += [node for t in targets if isinstance(t, ast.Name) and t.id == 'LIVE_EXECUTION_READY']
            if isinstance(node, (ast.Global, ast.Nonlocal)):
                self.assertNotIn('LIVE_EXECUTION_READY', node.names)
        self.assertEqual(len(bindings), 1)
        self.assertIn(bindings[0], self.app.body)
        self.assertIsInstance(bindings[0].value, ast.Constant)
        self.assertIs(bindings[0].value.value, False)

    def test_the_locks_are_direct_early_returns_before_the_broker_call(self):
        body = self.method(self.app, 'Handler', 'place_order').body
        submit = next(i for i, stmt in enumerate(body) if any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                                                              and n.func.id == 'kite_request' for n in ast.walk(stmt)))

        def early_return(test_source):
            return any(isinstance(stmt, ast.If) and ast.unparse(stmt.test) == test_source
                       and any(isinstance(s, ast.Return) for s in stmt.body) for stmt in body[:submit])

        self.assertTrue(early_return('not LIVE_ORDERS_ENABLED'))
        self.assertTrue(early_return('not LIVE_EXECUTION_READY'))
        self.assertTrue(early_return("values.get('confirm_text') != 'PLACE LIVE ORDER'"))

    def test_the_selection_dispatcher_checks_its_read_only_allowlist_first(self):
        tree = ast.parse((ROOT / 'auto_selector.py').read_text(encoding='utf-8'))
        first = self.method(tree, 'AutoSelector', 'request').body[0]
        self.assertEqual(ast.unparse(first.test), 'method not in READ_ONLY_METHODS')
        self.assertIsInstance(first.body[-1], ast.Raise)
        self.assertEqual(auto_selector.READ_ONLY_METHODS, frozenset({'historical_data', 'quote'}))

    def test_the_selection_dispatcher_refuses_an_order_method_without_touching_the_client(self):
        class Untouchable:
            def __getattr__(self, name):
                raise AssertionError('touched ' + name)
        for method in ('place_order', 'modify_order', 'cancel_order', 'exit_order', 'place_gtt', '_post', 'profile'):
            with self.assertRaisesRegex(ValueError, 'read-only'):
                auto_selector.AutoSelector.request(Untouchable(), method)

    def test_no_project_module_imports_the_app(self):
        for path in guard.tracked_files(ROOT):
            relative = path.relative_to(ROOT).as_posix()
            if path.suffix != '.py' or relative.startswith('tests/') or relative == 'app.py':
                continue
            text = path.read_text(encoding='utf-8', errors='replace')
            tree = ast.parse(text)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    self.assertNotIn('app', [a.name for a in node.names], relative)
                if isinstance(node, ast.ImportFrom):
                    self.assertNotEqual(node.module, 'app', relative)
                if isinstance(node, ast.Constant) and node.value == 'app':
                    self.fail('%s names the app module dynamically' % relative)


class ScannerTests(unittest.TestCase):
    def found(self, source):
        return [f['finding'] for f in guard.scan_python(source)]

    def test_order_mutations_calls_references_and_names_are_found(self):
        for source in ('kite.place_order(variety="regular")', 'self.client.modify_order("x")', 'k.cancel_order(o)',
                       'broker.exit_order(1)', 'kite.place_gtt(x)', 'kite.convert_position(x)',
                       'po = kite.place_order', "getattr(kite, 'place_order')(x)", "kite._post('order.place', p)",
                       "route = 'gtt.delete'"):
            self.assertEqual(len(self.found(source)), 1, source)

    def test_order_endpoint_writes_are_found_but_reads_are_not(self):
        flagged = ("kite_request('/orders/regular', t, method='POST')", "kite_request(f'/orders/{oid}', t, method='DELETE')",
                   "send('/gtt/triggers', form={'a': 1})", "requests.post(base + '/orders/regular', data=body)",
                   "call('/portfolio/positions', method='put')", "kite_request('/orders/regular', t, method=verb)",
                   "requests.post('https://api.kite.trade/orders/regular', b)", "urlopen(Request('/orders/regular', body))",
                   "session.delete('/orders/regular/1')")
        for source in flagged:
            self.assertGreaterEqual(len(self.found(source)), 1, source)
        for source in ("kite_request('/orders', t)", "kite_request('/orders', t, method='GET')", "# kite.place_order(x)",
                       "kite_request('/user/margins', t, method='POST')", "def place_order(self): pass"):
            self.assertEqual(self.found(source), [], source)

    def test_a_full_order_url_is_found_even_when_held_in_a_constant(self):
        self.assertEqual(self.found('URL = "https://api.kite.trade/orders/regular"\nrequests.post(URL, data=b)'),
                         ['broker order URL string'])
        self.assertEqual(self.found('HOST = "https://api.kite.trade"'), ['broker host string'])

    def test_dynamic_dispatch_on_a_broker_client_is_found_inline_or_via_a_variable(self):
        self.assertEqual(self.found('getattr(self.market.client(t), name)()'), ['dynamic dispatch on broker client'])
        self.assertEqual(self.found('def tool(m, t, name):\n    k = m.client(t)\n    return getattr(k, name)()'),
                         ['dynamic dispatch on broker client'])
        self.assertEqual(self.found('def tool(name):\n    k = KiteConnect(api_key=a)\n    getattr(k, name)()'),
                         ['dynamic dispatch on broker client'])
        self.assertEqual(self.found("getattr(self.market, 'master', [])"), [])
        self.assertEqual(self.found('def other(obj, name):\n    return getattr(obj, name)'), [])
        self.assertEqual(self.found('def a(m, t):\n    k = m.client(t)\ndef b(k, name):\n    getattr(k, name)'), [])

    def test_findings_name_their_enclosing_function(self):
        self.assertEqual(guard.scan_python('class A:\n    def go(self):\n        kite.place_order(x)\n')[0]['where'], 'A.go')

    def test_scripts_may_call_the_local_api_but_never_the_broker(self):
        self.assertEqual(guard.scan_script("api('/api/orders/place', {method:'POST'})"), [])
        for source in ("fetch('https://api.kite.trade/orders/regular')", "post('/orders/regular')", "x=`/gtt/triggers`"):
            self.assertEqual(len(guard.scan_script(source)), 1, source)


if __name__ == '__main__':
    unittest.main()
