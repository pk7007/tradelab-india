"""Reviewed-build identity includes core signal and data-validation dependencies."""
import ast
import hashlib
from pathlib import Path
import unittest


class PaperBuildTests(unittest.TestCase):
    def test_core_financial_dependencies_change_reviewed_build(self):
        root = Path(__file__).resolve().parents[1]
        tree = ast.parse((root / 'app.py').read_text(encoding='utf-8'))
        assignment = next(node for node in tree.body if isinstance(node, ast.Assign)
                          and any(isinstance(target, ast.Name) and target.id == 'PAPER_BUILD_FILES'
                                  for target in node.targets))
        names = ast.literal_eval(assignment.value)
        content = {name: (root / name).read_bytes() for name in names}

        def fingerprint(parts):
            return hashlib.sha256(b''.join(hashlib.sha256(parts[name]).digest()
                                           for name in names)).hexdigest()

        original = fingerprint(content)
        for dependency in ('strategy_contract.py', 'research.py', 'research_context.py',
                           'integrated_news.py', 'syndication.py', 'syndication_transport.py'):
            with self.subTest(dependency=dependency):
                self.assertIn(dependency, names)
                altered = dict(content)
                altered[dependency] += b'\n# fixture dependency change\n'
                self.assertNotEqual(fingerprint(altered), original)
