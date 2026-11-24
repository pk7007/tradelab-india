"""Static guard: no source file may reach a broker order endpoint except the reviewed, locked sites.

Detected in Python (AST, so comments do not count):
- any reference to a Kite order-mutation method (`place_order`, `modify_order`, `cancel_order`, `exit_order`, GTT and
  position-conversion calls), whether called or only referenced (so `po = kite.place_order` is caught);
- any string naming such a method or an SDK route key (`'order.place'`, `'gtt.delete'`, ...), which catches
  `getattr(kite, 'place_order')`;
- any string containing the Kite API host;
- any call carrying a Kite order, GTT or position path (relative or full URL) that writes: a non-GET or non-constant
  `method=`, a request body keyword, a write verb (`post`, `put`, `patch`, `delete`), or a positional body passed to
  `Request` / `urlopen`;
- dynamic dispatch on a broker client: `getattr(<client>, <non-constant>)` where the client is created inline
  (`.client(...)`, `KiteConnect(...)`) or assigned from one earlier in the same function;
- any string containing the Kite API host, and separately any full order URL held in a constant.
Detected in JavaScript and HTML: any reference to the Kite API host or a bare order/GTT path.

Each allowed site is counted: ALLOWLIST maps (file, enclosing function, finding) to the exact number of occurrences, so
a second call in an allowed function fails the test. Known limit: a static check cannot follow names built at runtime
(`exec`, concatenated method names); the dispatcher allowlist in auto_selector.py and the live lock in app.py cover
the paths that exist today.
"""
import ast
import re
import subprocess
from collections import Counter
from pathlib import Path

ORDER_METHODS = {'place_order', 'modify_order', 'cancel_order', 'exit_order', 'place_gtt', 'modify_gtt', 'delete_gtt',
                 'convert_position', 'place_mf_order', 'cancel_mf_order', 'place_mf_sip', 'modify_mf_sip', 'cancel_mf_sip'}
ROUTE_KEY = re.compile(r'^(?:order|gtt|portfolio\.positions)\.(?:place|modify|cancel|delete|convert)')
ORDER_PATH = re.compile(r'(?:^|api\.kite\.trade)/(?:orders|gtt|portfolio/positions)(?:[/?]|$)')
HOST = 'api.kite.trade'
WRITE_VERBS = {'post', 'put', 'patch', 'delete'}
BODY_KEYWORDS = {'form', 'data', 'json', 'body', 'files'}
SKIP_PARTS = {'.venv', 'venv', '.tools', 'node_modules', 'graphify-out', '__pycache__', '.git'}
JS_PATTERN = re.compile(r'api\.kite\.trade|["\'`](?:/orders|/gtt)[/"\'`?]')
ALLOWLIST = {
    ('app.py', '<module>', 'broker host string'): 1,                       # KITE_API constant
    ('app.py', 'Handler.do_POST', 'method call place_order'): 1,           # route to the locked handler
    ('app.py', 'Handler.place_order', "order write '/orders/regular' via kite_request"): 1,
    ('broker_transport.py', 'fetch_json', 'broker host string'): 1,        # host allow-check, not a request
    ('auto_selector.py', 'AutoSelector.request', 'dynamic dispatch on broker client'): 1,   # READ_ONLY_METHODS first
}


def _strings(node):
    return [n.value for n in ast.walk(node) if isinstance(n, ast.Constant) and isinstance(n.value, str)]


class _Visitor(ast.NodeVisitor):
    def __init__(self):
        self.stack, self.found, self.call_funcs, self.clients = [], [], set(), [set()]

    def _scoped(self, node):
        self.stack.append(node.name)
        self.clients.append(set())
        self.generic_visit(node)
        self.clients.pop()
        self.stack.pop()

    @staticmethod
    def _makes_client(value):
        return isinstance(value, ast.Call) and (
            (isinstance(value.func, ast.Attribute) and value.func.attr == 'client')
            or (isinstance(value.func, ast.Name) and value.func.id == 'KiteConnect')
            or (isinstance(value.func, ast.Attribute) and value.func.attr == 'KiteConnect'))

    def visit_Assign(self, node):
        if self._makes_client(node.value):
            self.clients[-1].update(t.id for t in node.targets if isinstance(t, ast.Name))
        self.generic_visit(node)

    visit_ClassDef = visit_FunctionDef = visit_AsyncFunctionDef = _scoped

    def _add(self, node, finding):
        self.found.append((node.lineno, '.'.join(self.stack) or '<module>', finding))

    def visit_Constant(self, node):
        if isinstance(node.value, str):
            if node.value in ORDER_METHODS or ROUTE_KEY.match(node.value):
                self._add(node, 'order name string %r' % node.value)
            elif HOST in node.value:
                self._add(node, 'broker order URL string' if ORDER_PATH.search(node.value) else 'broker host string')

    def visit_Attribute(self, node):
        if node.attr in ORDER_METHODS and id(node) not in self.call_funcs:
            self._add(node, 'attribute reference %s' % node.attr)
        self.generic_visit(node)

    def visit_Call(self, node):
        func = node.func
        if isinstance(func, ast.Attribute):
            self.call_funcs.add(id(func))
        name = func.attr if isinstance(func, ast.Attribute) else func.id if isinstance(func, ast.Name) else None
        if name in ORDER_METHODS:
            self._add(node, 'method call %s' % name)
        if (name == 'getattr' and len(node.args) >= 2 and not isinstance(node.args[1], ast.Constant)
                and (self._makes_client(node.args[0])
                     or (isinstance(node.args[0], ast.Name) and node.args[0].id in self.clients[-1]))):
            self._add(node, 'dynamic dispatch on broker client')
        values = list(node.args) + [k.value for k in node.keywords]
        paths = [s for value in values for s in _strings(value) if ORDER_PATH.search(s)]
        if paths:
            method = next((k.value for k in node.keywords if k.arg == 'method'), None)
            writes = (
                (method is not None and not (isinstance(method, ast.Constant) and str(method.value).upper() == 'GET'))
                or any(k.arg in BODY_KEYWORDS for k in node.keywords)
                or (name or '').lower() in WRITE_VERBS
                or (name in ('Request', 'urlopen') and len(node.args) >= 2)
            )
            if writes:
                self._add(node, 'order write %r via %s' % (paths[0], name))
        self.generic_visit(node)


def scan_python(source, filename='<source>'):
    visitor = _Visitor()
    visitor.visit(ast.parse(source, filename=filename))
    return [dict(file=filename, line=line, where=where, finding=finding) for line, where, finding in visitor.found]


def scan_script(source, filename='<script>'):
    return [dict(file=filename, line=number, where='<script>', finding='broker order reference')
            for number, line in enumerate(source.splitlines(), 1) if JS_PATTERN.search(line)]


def tracked_files(root):
    root = Path(root)
    try:
        listed = subprocess.run(['git', 'ls-files', '*.py', '*.js', '*.html'], cwd=root, capture_output=True, text=True,
                                timeout=60, check=True).stdout.splitlines()
        paths = [root / line for line in listed]
    except (OSError, subprocess.SubprocessError):
        paths = [p for pattern in ('*.py', '*.js', '*.html') for p in root.rglob(pattern)]
    return sorted(p for p in paths if p.is_file() and not SKIP_PARTS & set(p.relative_to(root).parts))


def scan_repo(root, files=None):
    """Every finding in project sources (tests excluded). A site is allowed only up to its allowlisted count."""
    root = Path(root)
    results, used = [], Counter()
    for path in files if files is not None else tracked_files(root):
        relative = path.relative_to(root).as_posix()
        if relative.startswith('tests/'):
            continue
        text = path.read_text(encoding='utf-8', errors='replace')
        found = scan_python(text, relative) if path.suffix == '.py' else scan_script(text, relative)
        for item in found:
            key = (item['file'], item['where'], item['finding'])
            used[key] += 1
            item['allowed'] = used[key] <= ALLOWLIST.get(key, 0)
            results.append(item)
    return results
