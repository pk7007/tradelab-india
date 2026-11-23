"""Structure checker tests on temporary git fixture trees (no real repo)."""
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts import structure_check as sc

WORKFLOW = """steps:
  - run: |
      python -m py_compile good.py ghost.py
      node --check web/ok.js
      node --check web/gone.js
      node tests/ok.test.js
"""
SECRET = "AKIA" + "ABCDEFGHIJKLMNOP"
TOKEN = "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8"


def git(root, *args):
    subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True)


def write(root, rel, text="", size=None):
    path = Path(root, rel)
    path.parent.mkdir(parents=True, exist_ok=True)
    if size:
        path.write_bytes(b"x" * size)
    else:
        path.write_text(text, encoding="utf-8")


def build(root):
    git(root, "init", "-q")
    git(root, "config", "user.email", "t@example.invalid")
    git(root, "config", "user.name", "t")
    write(root, ".github/workflows/checks.yml", WORKFLOW)
    write(root, ".gitignore", ".env\n*.sqlite\nignored.txt\n")
    write(root, "good.py", "x = 1\n")
    write(root, "orphan.py", "y = 2\n")
    write(root, "tests/test_good.py", "import good\n")
    write(root, "tests/test_secret.py", f"K = '{SECRET}'\n")
    write(root, "tests/ok.test.js", "// ok\n")
    write(root, "tests/extra.test.js", "// not in CI\n")
    write(root, "web/ok.js", "// ok\n")
    write(root, "web/stray.js", "// not checked\n")
    write(root, "docs/a.md", "[good](b.md) [bad](nope.md) [web](https://x.invalid/y)"
                             " [mail](mailto:a@b.invalid) [anc](#top) [f](b.md#sec)\n")
    write(root, "docs/b.md", "# b\n")
    write(root, "config.py", f"KEY = '{SECRET}'\nTOKEN = '{TOKEN}'\n")
    write(root, ".env", "A=1\n")
    write(root, "store.sqlite", "db")
    write(root, "big.bin", size=sc.SIZE_LIMIT + 10)
    git(root, "add", "-A", "-f")
    git(root, "commit", "-qm", "fixture")
    write(root, "untracked.txt", "u\n")
    write(root, "ignored.txt", "i\n")


def snapshot(root):
    out = {}
    for base, dirs, files in os.walk(root):
        if ".git" in dirs:
            dirs.remove(".git")
        for name in files:
            p = Path(base, name)
            out[str(p)] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


class StructureCheckTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name)
        build(cls.root)
        cls.report = sc.run_checks(cls.root)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def kinds(self, check, severity=None):
        return {f["path"] for f in self.report["findings"]
                if f["check"] == check and (severity is None or f["severity"] == severity)}

    def test_py_ci_coverage(self):
        self.assertIn("orphan.py", self.kinds("py_not_compiled", "integrity"))
        self.assertIn("config.py", self.kinds("py_not_compiled"))
        self.assertNotIn("good.py", self.kinds("py_not_compiled"))
        self.assertIn("ghost.py", self.kinds("ci_missing_file", "integrity"))

    def test_untested_modules_are_info(self):
        self.assertIn("orphan.py", self.kinds("py_untested", "info"))
        self.assertNotIn("good.py", self.kinds("py_untested"))

    def test_js_coverage(self):
        self.assertIn("web/stray.js", self.kinds("js_not_checked", "integrity"))
        self.assertNotIn("web/ok.js", self.kinds("js_not_checked"))
        self.assertIn("web/gone.js", self.kinds("ci_missing_file", "integrity"))
        self.assertIn("tests/extra.test.js", self.kinds("js_test_not_run"))
        self.assertNotIn("tests/ok.test.js", self.kinds("js_test_not_run"))

    def test_broken_links_only(self):
        found = [f for f in self.report["findings"] if f["check"] == "broken_link"]
        self.assertEqual([f["path"] for f in found], ["docs/a.md"])
        self.assertIn("nope.md", found[0]["detail"])
        self.assertEqual(found[0]["severity"], "info")

    def test_large_file(self):
        self.assertEqual(self.kinds("large_file", "info"), {"big.bin"})

    def test_secrets_by_location_and_tests_excluded(self):
        hits = [f for f in self.report["findings"] if f["check"] == "secret_pattern"]
        self.assertTrue(hits)
        self.assertTrue(all(f["severity"] == "integrity" for f in hits))
        self.assertEqual({f["path"] for f in hits}, {"config.py"})
        self.assertEqual({f["line"] for f in hits}, {1, 2})

    def test_secret_values_never_in_output(self):
        blob = json.dumps(self.report) + sc.render_text(self.report)
        for secret in (SECRET, TOKEN, "ABCDEFGHIJKLMNOP"):
            self.assertNotIn(secret, blob)

    def test_tracked_should_be_ignored(self):
        self.assertEqual(self.kinds("tracked_should_be_ignored", "integrity"),
                         {".env", "store.sqlite"})

    def test_untracked_not_ignored(self):
        self.assertEqual(self.kinds("untracked", "info"), {"untracked.txt"})

    def test_exit_codes(self):
        self.assertEqual(sc.exit_code(self.report, strict=False), 1)
        clean = {"findings": [{"severity": "info"}]}
        self.assertEqual(sc.exit_code(clean, strict=False), 0)
        self.assertEqual(sc.exit_code(clean, strict=True), 1)
        self.assertEqual(sc.exit_code({"findings": []}, strict=True), 0)

    def test_readonly_and_cli(self):
        before = snapshot(self.root)
        script = Path(sc.__file__).resolve()
        proc = subprocess.run([sys.executable, str(script), "--root", str(self.root), "--json"],
                              capture_output=True, text=True)
        self.assertEqual(proc.returncode, 1)
        data = json.loads(proc.stdout)
        self.assertIn("findings", data)
        self.assertNotIn(SECRET, proc.stdout + proc.stderr)
        text = subprocess.run([sys.executable, str(script), "--root", str(self.root)],
                              capture_output=True, text=True)
        self.assertIn("integrity", text.stdout)
        self.assertEqual(before, snapshot(self.root))

    def test_clean_tree_passes(self):
        with tempfile.TemporaryDirectory() as d:
            git(d, "init", "-q")
            write(d, ".github/workflows/checks.yml", "run: python -m py_compile a.py\n")
            write(d, "a.py", "x=1\n")
            write(d, "tests/test_a.py", "import a\n")
            git(d, "add", "-A")
            report = sc.run_checks(d)
            self.assertEqual(sc.exit_code(report, strict=True), 0, report["findings"])


if __name__ == "__main__":
    unittest.main()


def mini(files, workflow="run: python -m py_compile a.py\n", extra_workflows=None):
    d = tempfile.TemporaryDirectory()
    git(d.name, "init", "-q")
    write(d.name, ".github/workflows/checks.yml", workflow)
    for name, body in (extra_workflows or {}).items():
        write(d.name, f".github/workflows/{name}", body)
    for rel, body in files.items():
        if isinstance(body, bytes):
            Path(d.name, rel).parent.mkdir(parents=True, exist_ok=True)
            Path(d.name, rel).write_bytes(body)
        else:
            write(d.name, rel, body)
    git(d.name, "add", "-A", "-f")
    return d


def checks(report, name):
    return [f for f in report["findings"] if f["check"] == name]


class RobustnessTests(unittest.TestCase):
    def run_mini(self, files, **kw):
        d = mini(files, **kw)
        self.addCleanup(d.cleanup)
        return sc.run_checks(d.name), d

    def test_non_git_root_exits_2(self):
        with tempfile.TemporaryDirectory() as d:
            script = Path(sc.__file__).resolve()
            proc = subprocess.run([sys.executable, str(script), "--root", d],
                                  capture_output=True, text=True)
            self.assertEqual(proc.returncode, 2)
            self.assertEqual(len(proc.stderr.strip().splitlines()), 1)
            self.assertNotIn("Traceback", proc.stderr)
            missing = subprocess.run([sys.executable, str(script), "--root", d + "/nope"],
                                     capture_output=True, text=True)
            self.assertEqual(missing.returncode, 2)

    def test_continuation_quotes_multiline(self):
        wf = ('run: |\n  python -m py_compile a.py \\\n    "b.py" \\\n    \'c.py\'\n'
              "  node --check web/x.js \\\n      web/y.js\n")
        files = {n: "x=1\n" for n in ("a.py", "b.py", "c.py", "d.py")}
        files.update({"web/x.js": "//\n", "web/y.js": "//\n"})
        report, _ = self.run_mini(files, workflow=wf)
        self.assertEqual({f["path"] for f in checks(report, "py_not_compiled")}, {"d.py"})
        self.assertEqual(checks(report, "js_not_checked"), [])
        self.assertEqual(checks(report, "ci_missing_file"), [])

    def test_glob_and_compileall_are_not_false_integrity(self):
        wf = "run: |\n  python -m py_compile scripts/*.py nomatch/*.py\n  python -m compileall pkg\n"
        files = {"scripts/s.py": "x=1\n", "pkg/m.py": "x=1\n", "top.py": "x=1\n"}
        report, _ = self.run_mini(files, workflow=wf)
        self.assertEqual(checks(report, "ci_missing_file"), [])
        self.assertEqual({f["path"] for f in checks(report, "py_not_compiled")}, {"top.py"})
        unknown = checks(report, "ci_unknown_coverage")
        self.assertTrue(unknown)
        self.assertTrue(all(f["severity"] == "info" for f in unknown))
        self.assertIn("nomatch/*.py", {f["path"] for f in unknown})

    def test_all_workflows_parsed(self):
        report, _ = self.run_mini({"a.py": "x=1\n", "b.py": "x=1\n"},
                                  extra_workflows={"other.yaml": "run: python -m py_compile b.py\n"})
        self.assertEqual(checks(report, "py_not_compiled"), [])

    def test_secret_skips_reported_without_values(self):
        files = {"bin.dat": b"\xff\xfe\x00" + SECRET.encode(), "tests/t.py": f"K='{SECRET}'\n",
                 "a.py": "x=1\n"}
        report, _ = self.run_mini(files)
        skipped = checks(report, "secret_scan_skipped")
        self.assertEqual(len(skipped), 1)
        self.assertEqual(skipped[0]["severity"], "info")
        self.assertIn("tests=1", skipped[0]["detail"])
        self.assertIn("binary=1", skipped[0]["detail"])
        self.assertEqual(checks(report, "secret_pattern"), [])
        self.assertNotIn(SECRET, json.dumps(report))
        self.assertIn("tests/", sc.__doc__)

    def test_link_edge_cases(self):
        doc = ("[ok](b.md) [paren](c_(1).md) [angle](<sp ace.md>) [abs](/etc/passwd)\n"
               "[ref]: missing_ref.md\n[ref2]: b.md\n[bad](gone.md)\n"
               "```\n[fenced](fenced_missing.md)\n```\n")
        files = {"docs/a.md": doc, "docs/b.md": "x", "docs/c_(1).md": "x", "docs/sp ace.md": "x"}
        report, _ = self.run_mini(files)
        broken = {f["detail"] for f in checks(report, "broken_link")}
        self.assertEqual(broken, {"broken relative link: missing_ref.md",
                                  "broken relative link: gone.md"})
        absolute = checks(report, "absolute_link")
        self.assertEqual(len(absolute), 1)
        self.assertEqual(absolute[0]["severity"], "info")

    def test_symlinks(self):
        d = mini({"a.py": "x=1\n", "docs/b.md": "x"})
        self.addCleanup(d.cleanup)
        os.symlink("a.py", Path(d.name, "alias.py"))
        os.symlink("nowhere", Path(d.name, "dangling"))
        git(d.name, "add", "-A")
        report = sc.run_checks(d.name)
        self.assertNotIn("alias.py", {f["path"] for f in checks(report, "py_not_compiled")})
        self.assertEqual({f["path"] for f in checks(report, "dangling_symlink")}, {"dangling"})
        self.assertEqual(checks(report, "dangling_symlink")[0]["severity"], "info")

    def test_env_example_exempt_and_env_variants_flagged(self):
        report, _ = self.run_mini({"a.py": "x=1\n", ".env.example": "A=\n", ".env.local": "A=1\n",
                                   "data/private/x.txt": "x", "k.pem": "x"})
        self.assertEqual({f["path"] for f in checks(report, "tracked_should_be_ignored")},
                         {".env.local", "data/private/x.txt", "k.pem"})
