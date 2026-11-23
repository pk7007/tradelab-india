import copy
import datetime
import json
import tempfile
import unittest
from pathlib import Path

from scripts import project_report as pr

FIXED = datetime.date(2026, 11, 23)
FAKE_SECRET = "api_key=ABCD1234SECRETVALUE9999"


def make_runner(overrides=None, calls=None):
    """Stub runner: overrides map a substring of the joined command to (rc, output) or an exception."""
    overrides = overrides or {}

    def runner(cmd, cwd, timeout=600):
        joined = " ".join(cmd)
        if calls is not None:
            calls.append(joined)
        for key, value in overrides.items():
            if key in joined:
                if isinstance(value, Exception):
                    raise value
                return value
        if "pytest" in joined:
            return 0, "....\n12 passed in 1.20s\n"
        if "ruff" in joined:
            return 0, "All checks passed!\n"
        if "bandit" in joined:
            return 0, ""
        if joined.startswith("node"):
            return 0, ""
        if "log" in cmd:
            return 0, "abc1234 Add thing\ndef5678 Fix thing\n"
        if "describe" in cmd:
            return 128, "fatal: no tags"
        return 0, ""

    return runner


def make_root(js_tests=("a.test.js",), web=("app.js",), docs=True):
    tmp = tempfile.TemporaryDirectory()
    root = Path(tmp.name)
    (root / "tests").mkdir()
    (root / "web").mkdir()
    (root / "docs").mkdir()
    for name in js_tests:
        (root / "tests" / name).write_text("//")
    for name in web:
        (root / "web" / name).write_text("//")
    if docs:
        (root / "docs" / "current-state-audit-2026-11-23.md").write_text(
            "# Audit\n\n## Material risks to track\n\n1. Kill does not neutralise exposure.\n"
            "3. Forward performance is unobserved. The system must not be described as profitable or live-ready.\n\n## Recommended next verification\n\n1. Other\n")
        (root / "docs" / "tooling.md").write_text("# T\n\n## Open items\n- defusedxml later.\n- hooks not run.\n")
    return tmp, root


def build(root, runner=None, **kw):
    kw.setdefault("report_dir", "reports")
    return pr.build_report(root, runner or make_runner(), today=FIXED, **kw)


class PytestParsing(unittest.TestCase):
    def test_shapes(self):
        cases = {
            "12 passed in 1.2s": {"passed": 12},
            "3 failed, 10 passed, 2 skipped in 4.00s": {"failed": 3, "passed": 10, "skipped": 2},
            "1 failed, 4 passed, 1 warning in 0.5s": {"failed": 1, "passed": 4, "warnings": 1},
            "2 errors in 0.10s": {"errors": 2},
            "=== 5 passed, 1 xfailed, 3 deselected in 0.3s ===": {"passed": 5, "xfailed": 1, "deselected": 3},
            "no tests ran in 0.01s": {},
        }
        for text, expected in cases.items():
            self.assertEqual(pr.parse_pytest_counts("line\n" + text + "\n"), expected, text)

    def test_unparseable_returns_none(self):
        self.assertIsNone(pr.parse_pytest_counts("Traceback boom"))


class Rendering(unittest.TestCase):
    def test_all_pass(self):
        tmp, root = make_root()
        with tmp:
            report, status = build(root)
        self.assertEqual(status, "PASS")
        self.assertIn("Overall status: PASS", report)
        self.assertIn("12 passed", report)
        for heading in ("Summary", "Checks", "Changes since last report", "Carried findings", "Recommended next steps", "Latest rating pointer", "What this report does not establish"):
            self.assertIn("## " + heading, report)

    def test_failed_check_is_shown_with_tail(self):
        tmp, root = make_root()
        with tmp:
            report, status = build(root, make_runner({"pytest": (1, "x\n" * 80 + "2 failed, 10 passed in 3s\n")}))
        self.assertEqual(status, "FAIL")
        self.assertIn("FAILED", report)
        self.assertIn("2 failed, 10 passed", report)
        self.assertIn("Overall status: FAIL", report)
        steps = report.split("## Recommended next steps")[1]
        self.assertLess(steps.index("Fix failing check"), steps.index("Kill"))

    def test_runner_exception_is_error(self):
        tmp, root = make_root()
        with tmp:
            report, status = build(root, make_runner({"ruff": FileNotFoundError("ruff")}))
        self.assertEqual(status, "FAIL")
        self.assertIn("ERROR", report)
        self.assertIn("FileNotFoundError", report)

    def test_unparseable_pytest_with_zero_rc_is_not_pass(self):
        tmp, root = make_root()
        with tmp:
            report, status = build(root, make_runner({"pytest": (0, "weird output")}))
        self.assertNotEqual(status, "PASS")

    def test_node_failures_listed(self):
        tmp, root = make_root(js_tests=("a.test.js", "b.test.js"))
        with tmp:
            report, status = build(root, make_runner({"b.test.js": (1, "AssertionError nope")}))
        self.assertEqual(status, "FAIL")
        self.assertIn("1/2", report)
        self.assertIn("AssertionError nope", report)

    def test_optional_plugins_missing(self):
        tmp, root = make_root()
        with tmp:
            report, status = build(root)
        self.assertEqual(status, "PASS")
        self.assertIn("not available", report)

    def test_optional_plugin_present_json(self):
        tmp, root = make_root()
        (root / "scripts").mkdir()
        (root / "scripts" / "structure_check.py").write_text("")
        with tmp:
            report, status = build(root, make_runner({"structure_check.py": (0, STRUCTURE_OK)}))
            report2, status2 = build(root, make_runner({"structure_check.py": (1, "not json at all")}))
        self.assertEqual(status, "PASS")
        self.assertIn("structure_check", report)
        self.assertEqual(status2, "FAIL")
        self.assertIn("not json at all", report2)

    def test_missing_docs_tolerated(self):
        tmp, root = make_root(docs=False)
        with tmp:
            report, status = build(root)
        self.assertEqual(status, "PASS")
        self.assertIn("none", report.split("## Latest rating pointer")[1])
        self.assertIn("not found", report.split("## Carried findings")[1])

    def test_carried_findings_and_rating_pointer(self):
        tmp, root = make_root()
        (root / "docs" / "rating-2026-11-20.md").write_text("x")
        (root / "docs" / "rating-2026-11-23.md").write_text("x")
        with tmp:
            report, _ = build(root)
        self.assertIn("Kill does not neutralise exposure", report)
        self.assertIn("defusedxml later", report)
        self.assertIn("(../docs/rating-2026-11-23.md)", report)
        self.assertNotIn("rating-2026-11-20", report)

    def test_secret_scrubbed(self):
        tmp, root = make_root()
        with tmp:
            report, _ = build(root, make_runner({"ruff": (1, "oops " + FAKE_SECRET + " token ghp_" + "a" * 36 + "\n")}))
        self.assertNotIn("ABCD1234SECRETVALUE9999", report)
        self.assertNotIn("ghp_" + "a" * 36, report)
        self.assertIn("[REDACTED]", report)

    def test_claim_phrase_in_commit_is_flagged_not_rewritten(self):
        tmp, root = make_root()
        with tmp:
            report, _ = build(root, make_runner({"log": (0, "abc1 make it profitable\n")}))
        self.assertIn("abc1 make it profitable", report)
        self.assertIn("## Wording to review", report)
        review = report.split("## Wording to review")[1].split("\n## ")[0]
        self.assertIn("make it profitable", review)

    def test_negated_carried_excerpt_is_kept_and_not_flagged(self):
        tmp, root = make_root()
        with tmp:
            report, _ = build(root)
        self.assertIn("must not be described as profitable or live-ready", report)
        self.assertNotIn("## Wording to review", report)

    def test_claims_only_in_allowed_places(self):
        tmp, root = make_root()
        with tmp:
            report, _ = build(root, make_runner({"log": (0, "abc1 guaranteed returns\n")}))
        flagged = pr.find_claim_lines(report)
        self.assertTrue(any("guaranteed returns" in line for line in flagged))
        self.assertEqual(pr.find_claim_lines("No profitability is established."), [])

    def test_deterministic(self):
        tmp, root = make_root()
        with tmp:
            a, _ = build(root)
            b, _ = build(root)
        self.assertEqual(a, b)
        self.assertIn("2026-11-23", a)

    def test_changes_since_date_and_tag(self):
        calls = []
        tmp, root = make_root()
        with tmp:
            build(root, make_runner(calls=calls), since="2026-11-01")
            self.assertTrue(any("--since=2026-11-01" in c for c in calls))
            calls.clear()
            build(root, make_runner({"describe": (0, "v1\n")}, calls=calls))
            self.assertTrue(any("v1..HEAD" in c for c in calls))
            calls.clear()
            build(root, make_runner(calls=calls))
            self.assertTrue(any("-20" in c for c in calls))

    def test_scrub_function(self):
        self.assertNotIn("hunter2", pr.scrub("password: hunter2"))
        self.assertNotIn("sk-" + "b" * 30, pr.scrub("key sk-" + "b" * 30))
        self.assertEqual(pr.scrub("plain text"), "plain text")

    def test_scrub_many_shapes(self):
        cases = [
            "Authorization: Bearer abcdefgh12345",
            'password: "a b c secretphrase"',
            "password='my pass word'",
            '{"api_secret": "zzzTOPSECRETzzz"}',
            "slack xoxb-1234567890-abcdefghijkl",
            "slack xoxp-1234567890-abcdefghijkl",
            "google AIza" + "A" * 35,
            "-----BEGIN RSA PRIVATE KEY-----\nMIIEvQIBADANBgkq\nline2\n-----END RSA PRIVATE KEY-----",
            "aws_secret_access_key = wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
            "AKIA" + "B" * 16,
            "github_pat_" + "c" * 30,
            "ghp_" + "d" * 30,
            "sk-" + "e" * 30,
        ]
        for text in cases:
            cleaned = pr.scrub(text)
            self.assertIn("[REDACTED]", cleaned, text)
            for secret in ("abcdefgh12345", "a b c", "secretphrase", "my pass word", "zzzTOPSECRETzzz", "1234567890-abcdefghijkl",
                           "AAAAAAAAAAAAAAAAAAAA", "MIIEvQIBADANBgkq", "line2", "wJalrXUtnFEMI", "BBBBBBBB", "cccccccc", "dddddddd", "eeeeeeee"):
                self.assertNotIn(secret, cleaned, text)

    def test_missing_tool_is_error_not_failed(self):
        tmp, root = make_root()
        with tmp:
            for key, result in (("ruff", (1, "/usr/bin/python: No module named ruff")),
                                ("bandit", (127, "bandit: command not found")),
                                ("pytest", (1, "/usr/bin/python: No module named pytest")),
                                ("a.test.js", (127, "node: command not found"))):
                report, status = build(root, make_runner({key: result}))
                self.assertEqual(status, "FAIL", key)
                table = report.split("## Checks")[1].split("\n\n")[1]
                self.assertIn("ERROR", table, key)
                self.assertNotIn("FAILED", table, key)

    def test_rating_link_relative_to_report_dir(self):
        tmp, root = make_root()
        (root / "docs" / "rating-2026-11-23.md").write_text("x")
        with tmp:
            report, _ = build(root, report_dir=".")
        self.assertIn("(docs/rating-2026-11-23.md)", report)

    def test_step_summary_written(self):
        with tempfile.TemporaryDirectory() as d:
            target = Path(d) / "summary.md"
            pr.write_step_summary(str(target), "FAIL", "## Summary\n\nOverall status: FAIL\n")
            self.assertIn("FAIL", target.read_text())
            pr.write_step_summary("", "PASS", "x")  # no path: no-op, no exception


STRUCTURE_OK = '{"root": "/x", "counts": {"integrity": 0, "info": 3}, "findings": []}'
STRUCTURE_BAD = ('{"root": "/x", "counts": {"integrity": 2, "info": 1}, "findings": ['
                 '{"check": "dup-def", "severity": "integrity", "path": "a.py", "line": 3, "detail": "d"},'
                 '{"check": "orphan", "severity": "info", "path": "b.py", "line": 1, "detail": "d"},'
                 '{"check": "bad-import", "severity": "integrity", "path": "c.py", "line": 9, "detail": "d"}]}')
READY = {
    "ok": True, "counts": {"PASS": 5, "BLOCKED": 2, "FAIL": 0},
    "checks": [
        {"id": "a", "title": "A", "status": "PASS", "detail": "", "ownerAction": ""},
        {"id": "broker-login", "title": "Zerodha login", "status": "BLOCKED", "detail": "offline", "ownerAction": "Owner: log in interactively."},
    ],
}


# Real outputs captured from scripts/structure_check.py --json and scripts/paper_readiness.py --json (2026-11-23).
REAL_STRUCTURE = json.loads('{"root": ".", "counts": {"integrity": 0, "info": 5}, "findings": [{"check": "py_untested", "severity": "info", "path": "app.py", "line": null, "detail": "no tests/test_<module>.py and no test imports it"}, {"check": "secret_scan_skipped", "severity": "info", "path": "(secret scan)", "line": null, "detail": "files not scanned: tests=71 binary=0 oversize=0 symlink=0"}, {"check": "untracked", "severity": "info", "path": ".github/workflows/status-report.yml", "line": null, "detail": "untracked and not ignored"}, {"check": "untracked", "severity": "info", "path": "scripts/project_report.py", "line": null, "detail": "untracked and not ignored"}, {"check": "untracked", "severity": "info", "path": "tests/test_project_report.py", "line": null, "detail": "untracked and not ignored"}]}')
REAL_READINESS = json.loads('{"generatedAt": "2026-11-23T22:47:13.998331+05:30", "istDate": "2026-11-23", "ok": false, "counts": {"FAIL": 1, "BLOCKED": 6, "PASS": 6}, "checks": [{"id": "live-lock", "title": "Live execution locked", "status": "PASS", "detail": "LIVE_EXECUTION_READY is False (locked). TRADELAB_ENABLE_LIVE_ORDERS is not true.", "ownerAction": ""}, {"id": "kite-credentials", "title": "Kite variable names", "status": "BLOCKED", "detail": "Present: none. Missing or placeholder: KITE_API_KEY, KITE_API_SECRET. Optional set: none (default redirect URL applies). Names only; values never read out.", "ownerAction": "Owner: put KITE_API_KEY and KITE_API_SECRET from your own Kite developer app in .env (see .env.example). Never paste them into chat."}, {"id": "kiteconnect", "title": "kiteconnect importable", "status": "FAIL", "detail": "kiteconnect is not importable.", "ownerAction": "Run: python -m pip install -r requirements.txt (inside your project virtual environment)."}, {"id": "broker-login", "title": "Zerodha login", "status": "BLOCKED", "detail": "Interactive login cannot be verified offline; broker tokens live in memory only and a fresh app is disconnected.", "ownerAction": "Owner: start the app, open http://127.0.0.1:8765/ and click Connect Zerodha, then sign in yourself."}, {"id": "data-dir", "title": "Private data directory writable", "status": "PASS", "detail": "Will be created on first save under writable /home/user/tradelab-india/.claude/worktrees/agent-a5b12c60362207bf8/data.", "ownerAction": ""}, {"id": "paper-db", "title": "Paper database integrity", "status": "PASS", "detail": "No ledger at /home/user/tradelab-india/.claude/worktrees/agent-a5b12c60362207bf8/data/private/TradeLabIndia/paper.sqlite yet; the app creates it on first start.", "ownerAction": ""}, {"id": "ledger-lease", "title": "No active worker lease in ledger", "status": "PASS", "detail": "No ledger, so no lease.", "ownerAction": ""}, {"id": "worker-default", "title": "Worker disarmed by default", "status": "PASS", "detail": "A fresh PaperWorker reports state=disarmed, enabled=False, live=False (observed-candle paper only).", "ownerAction": ""}, {"id": "session-config", "title": "Session / square-off configuration", "status": "BLOCKED", "detail": "No Intraday v1 paper account exists to validate (entry cutoff and square-off are per-account).", "ownerAction": "Owner: create an imported Intraday v1 account at /trader-paper with entryEnd before squareOff, both on 5-minute IST boundaries, squareOff <= 15:25."}, {"id": "calendar", "title": "Session calendar covers today", "status": "BLOCKED", "detail": "No calendar manifest supplied to this check.", "ownerAction": "Owner: pass --calendar PATH, and paste an attributed calendar manifest into the worker panel when arming (sample: docs/infy-paper-calendar-2026-11-20.json)."}, {"id": "fixture-replay", "title": "Fixture recovery replay", "status": "PASS", "detail": "scripts/fixture_recovery.py passed (temporary loopback servers and database; no internet, no broker).", "ownerAction": ""}, {"id": "storage-approval", "title": "Data-storage approval flag", "status": "BLOCKED", "detail": "KITE_DATA_STORAGE_APPROVED is not true. Blocks: POST /api/paper-worker/start (app.py), saving history as CSV (market_data.py) and the automatic-selection start.", "ownerAction": "Owner: confirm your Kite data-retention rights, then set KITE_DATA_STORAGE_APPROVED=true in .env and restart the app. Do not set it without that confirmation."}, {"id": "market-hours", "title": "Market plausibly open (approximate)", "status": "BLOCKED", "detail": "Approximate only (weekday and clock, no holiday calendar): IST now is 2026-11-23 Mon 22:47. Outside weekday 09:15-15:30 IST.", "ownerAction": "Owner: arm during a confirmed NSE trading session (09:15-15:30 IST), after checking the NSE holiday list yourself."}]}')


def plugin_root():
    tmp, root = make_root()
    (root / "scripts").mkdir()
    (root / "scripts" / "structure_check.py").write_text("")
    (root / "scripts" / "paper_readiness.py").write_text("")
    return tmp, root


class PluginContracts(unittest.TestCase):
    def run_plugin(self, key, result):
        tmp, root = plugin_root()
        with tmp:
            overrides = {"structure_check.py": (0, STRUCTURE_OK), "paper_readiness.py": (0, json.dumps(READY))}
            overrides[key] = result
            return build(root, make_runner(overrides))

    @staticmethod
    def row(report, name):
        return [line for line in report.split("## Checks")[1].splitlines() if line.startswith("| " + name)][0]

    def test_structure_pass(self):
        report, status = self.run_plugin("structure_check.py", (0, STRUCTURE_OK))
        self.assertEqual(status, "PASS")

    def test_structure_integrity_fails_even_with_exit_zero_and_lists_findings(self):
        report, status = self.run_plugin("structure_check.py", (0, STRUCTURE_BAD))
        self.assertEqual(status, "FAIL")
        self.assertIn("FAILED", self.row(report, "structure_check"))
        self.assertIn("dup-def", report)
        self.assertIn("c.py", report)
        self.assertNotIn("orphan", report)
        self.assertNotIn('"counts"', report)

    def test_structure_bad_output_is_error(self):
        for result in ((2, STRUCTURE_OK), (0, ""), (0, "not json"), (0, '{"root": "x"}'), (0, '{"counts": {"info": 1}, "findings": []}')):
            report, status = self.run_plugin("structure_check.py", result)
            self.assertEqual(status, "FAIL", result)
            self.assertIn("ERROR", self.row(report, "structure_check"), result)

    def test_readiness_blocked_is_not_failure_and_lists_owner_actions(self):
        report, status = self.run_plugin("paper_readiness.py", (0, json.dumps(READY)))
        self.assertEqual(status, "PASS")
        self.assertIn("Zerodha login", report)
        self.assertIn("Owner: log in interactively.", report)

    def test_readiness_fail_item_fails(self):
        bad = copy.deepcopy(READY)
        bad["ok"] = False
        bad["counts"]["FAIL"] = 1
        bad["checks"].append({"id": "paper-db", "title": "Paper ledger", "status": "FAIL", "detail": "corrupt ledger", "ownerAction": ""})
        report, status = self.run_plugin("paper_readiness.py", (1, json.dumps(bad)))
        self.assertEqual(status, "FAIL")
        self.assertIn("corrupt ledger", report)
        self.assertIn("FAILED", self.row(report, "paper_readiness"))

    def test_readiness_bad_output_is_error(self):
        for result in ((0, "garbage"), (3, "{}"), (0, '{"ok": true}')):
            report, status = self.run_plugin("paper_readiness.py", result)
            self.assertEqual(status, "FAIL", result)
            self.assertIn("ERROR", self.row(report, "paper_readiness"), result)


    def test_real_structure_output_passes(self):
        report, status = self.run_plugin("structure_check.py", (0, json.dumps(REAL_STRUCTURE)))
        self.assertEqual(status, "PASS")
        self.assertIn("integrity 0", self.row(report, "structure_check"))

    def test_real_readiness_environment_failure_does_not_fail_overall(self):
        report, status = self.run_plugin("paper_readiness.py", (1, json.dumps(REAL_READINESS)))
        row = self.row(report, "paper_readiness")
        self.assertIn("FAILED (environment)", row)
        self.assertEqual(status, "PASS")
        self.assertIn("kiteconnect is not importable", report)
        # BLOCKED items are listed with owner actions and are not failures
        self.assertIn("Zerodha login", report)
        self.assertIn("click Connect Zerodha", report)
        self.assertIn("Environment-only failures", report)

    def test_real_readiness_with_extra_real_failure_fails_overall(self):
        bad = copy.deepcopy(REAL_READINESS)
        for item in bad["checks"]:
            if item["id"] == "live-lock":
                item["status"] = "FAIL"
                item["detail"] = "live lock broken"
        report, status = self.run_plugin("paper_readiness.py", (1, json.dumps(bad)))
        self.assertEqual(status, "FAIL")
        row = self.row(report, "paper_readiness")
        self.assertIn("FAILED", row)
        self.assertNotIn("(environment)", row)
        self.assertIn("live lock broken", report)

    def test_real_readiness_only_blocked_passes(self):
        ok = copy.deepcopy(REAL_READINESS)
        ok["checks"] = [c for c in ok["checks"] if c["status"] != "FAIL"]
        ok["ok"] = True
        report, status = self.run_plugin("paper_readiness.py", (0, json.dumps(ok)))
        self.assertEqual(status, "PASS")
        self.assertIn("PASS", self.row(report, "paper_readiness"))

if __name__ == "__main__":
    unittest.main()
