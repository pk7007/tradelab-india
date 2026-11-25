"""Offline paper-readiness preflight: no network, no secret values, ledger untouched."""
import contextlib
import hashlib
import io
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT))
import paper_readiness  # noqa: E402

SECRET = 'FAKE-SECRET-VALUE-9f8e7d6c'
NOW = '2026-11-23T10:30:00+05:30'  # Monday, inside the approximate window


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class Base(unittest.TestCase):
    def setUp(self):
        t = tempfile.TemporaryDirectory()
        self.addCleanup(t.cleanup)
        self.tmp = Path(t.name)
        self.env = dict(TRADELAB_DATA_DIR=str(self.tmp / 'data'), TRADELAB_PAPER_DB=str(self.tmp / 'paper.sqlite'))

    def run_main(self, *extra, env=None, json_out=True, now=NOW):
        out, err = io.StringIO(), io.StringIO()
        argv = ['--skip-replay', '--now', now, '--env-file', str(self.tmp / 'absent.env')] + list(extra)
        if json_out:
            argv.append('--json')
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = paper_readiness.main(argv, environ=self.env if env is None else env)
        return code, out.getvalue(), err.getvalue()

    def items(self, *extra, env=None, now=NOW):
        code, out, _ = self.run_main(*extra, env=env, now=now)
        data = json.loads(out)
        return code, data, {c['id']: c for c in data['checks']}


class ReadinessTests(Base):
    def test_missing_kite_names_are_blocked_not_fail(self):
        _, _, c = self.items()
        self.assertEqual(c['kite-credentials']['status'], 'BLOCKED')
        self.assertIn('KITE_API_KEY', c['kite-credentials']['detail'])
        self.assertIn('KITE_API_SECRET', c['kite-credentials']['detail'])
        self.assertTrue(c['kite-credentials']['ownerAction'])
        self.assertEqual(c['broker-login']['status'], 'BLOCKED')
        self.assertEqual(c['storage-approval']['status'], 'BLOCKED')
        self.assertIn('paper-worker', c['storage-approval']['detail'])

    def test_secret_values_never_printed(self):
        env_file = self.tmp / '.env'
        env_file.write_text('KITE_API_KEY=%s\nKITE_API_SECRET=%s-b\n' % (SECRET, SECRET), encoding='utf-8')
        env = dict(self.env, KITE_API_KEY=SECRET + '-env', KITE_API_SECRET=SECRET + '-env2')
        for as_json in (True, False):
            _, out, err = self.run_main('--env-file', str(env_file), env=env, json_out=as_json)
            self.assertNotIn(SECRET, out + err)
        _, _, c = self.items('--env-file', str(env_file), env=env)
        self.assertEqual(c['kite-credentials']['status'], 'PASS')
        self.assertIn('KITE_API_KEY', c['kite-credentials']['detail'])

    def test_dotenv_names_only_and_placeholder_is_missing(self):
        env_file = self.tmp / '.env'
        env_file.write_text('KITE_API_KEY=your_kite_api_key_here\nKITE_API_SECRET=%s\n' % SECRET, encoding='utf-8')
        _, out, _ = self.run_main('--env-file', str(env_file))
        self.assertNotIn(SECRET, out)
        c = {x['id']: x for x in json.loads(out)['checks']}
        self.assertEqual(c['kite-credentials']['status'], 'BLOCKED')
        self.assertIn('KITE_API_KEY', c['kite-credentials']['detail'])

    def test_live_flag_set_still_reported_locked(self):
        _, _, c = self.items(env=dict(self.env, TRADELAB_ENABLE_LIVE_ORDERS='true'))
        self.assertEqual(c['live-lock']['status'], 'PASS')
        self.assertIn('locked', c['live-lock']['detail'].lower())
        self.assertIn('ineffective', c['live-lock']['detail'].lower())

    def test_fail_when_live_readiness_unlocked(self):
        proj = self.tmp / 'proj'
        proj.mkdir()
        (proj / 'app.py').write_text('LIVE_EXECUTION_READY = True\n', encoding='utf-8')
        code, data, c = self.items('--project-root', str(proj))
        self.assertEqual(c['live-lock']['status'], 'FAIL')
        self.assertEqual(code, 1)
        self.assertFalse(data['ok'])

    def test_fail_when_app_flag_unreadable(self):
        proj = self.tmp / 'proj'
        proj.mkdir()
        (proj / 'app.py').write_text('x = 1\n', encoding='utf-8')
        code, _, c = self.items('--project-root', str(proj))
        self.assertEqual(c['live-lock']['status'], 'FAIL')
        self.assertEqual(code, 1)

    def test_core_code_checks_pass_and_blocked_only_exits_zero(self):
        code, _, c = self.items()
        self.assertEqual(c['live-lock']['status'], 'PASS')
        self.assertEqual(c['worker-default']['status'], 'PASS')
        failing = [k for k, v in c.items() if v['status'] == 'FAIL']
        self.assertEqual(code, 1 if failing else 0)
        # With the only environment-dependent failure (missing SDK) set aside, nothing else fails.
        self.assertFalse([k for k in failing if k != 'kiteconnect'], failing)

    def test_real_ledger_untouched_and_integrity_checked(self):
        db = self.tmp / 'paper.sqlite'
        con = sqlite3.connect(db)
        con.execute('CREATE TABLE accounts(id TEXT PRIMARY KEY, body TEXT NOT NULL)')
        con.execute("INSERT INTO accounts VALUES('a','{}')")
        con.commit()
        con.close()
        before, mtime = sha(db), db.stat().st_mtime_ns
        _, _, c = self.items()
        self.assertEqual(c['paper-db']['status'], 'PASS')
        self.assertIn('integrity', c['paper-db']['detail'].lower())
        self.assertEqual(sha(db), before)
        self.assertEqual(db.stat().st_mtime_ns, mtime)
        self.assertEqual(sorted(p.name for p in self.tmp.iterdir() if p.name.startswith('paper')), ['paper.sqlite'])

    def test_corrupt_ledger_fails(self):
        db = self.tmp / 'paper.sqlite'
        db.write_bytes(b'this is not a sqlite database' * 50)
        before = sha(db)
        code, _, c = self.items()
        self.assertEqual(c['paper-db']['status'], 'FAIL')
        self.assertEqual(code, 1)
        self.assertEqual(sha(db), before)

    def test_absent_ledger_is_not_created(self):
        _, _, c = self.items()
        self.assertEqual(c['paper-db']['status'], 'PASS')
        self.assertFalse((self.tmp / 'paper.sqlite').exists())

    def test_data_dir_unwritable_fails(self):
        blocker = self.tmp / 'file'
        blocker.write_text('x')
        code, _, c = self.items(env=dict(self.env, TRADELAB_DATA_DIR=str(blocker / 'sub')))
        self.assertEqual(c['data-dir']['status'], 'FAIL')
        self.assertEqual(code, 1)

    def test_storage_approval_true_passes(self):
        _, _, c = self.items(env=dict(self.env, KITE_DATA_STORAGE_APPROVED='true'))
        self.assertEqual(c['storage-approval']['status'], 'PASS')

    def test_invalid_intraday_account_fails_and_valid_passes(self):
        from paper import PaperEngine
        engine = PaperEngine(self.tmp / 'paper.sqlite')
        good = dict(symbol='DEMO', provider='p', adjustment='None', source='imported', permitted=True, capital=10000,
                    units=10, maxExposure=5000, dailyLossLimit=500, costBps=10, slippageBps=5, strategy='intraday-v1',
                    maxLoss=100, stopDistancePct=1, targetMultiple=2, participationPct=5, entryEnd='14:30', squareOff='15:05')
        engine.create(good)
        _, _, c = self.items()
        self.assertEqual(c['session-config']['status'], 'PASS')
        con = sqlite3.connect(self.tmp / 'paper.sqlite')
        body = json.loads(con.execute('SELECT body FROM accounts').fetchone()[0])
        body['config']['squareOff'] = '15:40'
        con.execute('UPDATE accounts SET body=?', (json.dumps(body),))
        con.commit()
        con.close()
        code, _, c = self.items()
        self.assertEqual(c['session-config']['status'], 'FAIL')
        self.assertEqual(code, 1)

    def test_no_intraday_account_is_blocked(self):
        _, _, c = self.items()
        self.assertEqual(c['session-config']['status'], 'BLOCKED')

    def test_calendar_coverage_and_squareoff(self):
        cal = ROOT / 'docs' / 'infy-paper-calendar-2026-11-20.json'
        _, _, c = self.items('--calendar', str(cal))
        self.assertEqual(c['calendar']['status'], 'PASS')
        _, _, c = self.items('--calendar', str(cal), now='2026-12-01T10:00:00+05:30')
        self.assertEqual(c['calendar']['status'], 'BLOCKED')
        bad = self.tmp / 'bad.json'
        bad.write_text('{"nope": 1}')
        _, _, c = self.items('--calendar', str(bad))
        self.assertEqual(c['calendar']['status'], 'FAIL')

    def test_squareoff_fails_only_when_no_account_can_finish_before_close(self):
        from paper import PaperEngine
        cal = str(ROOT / 'docs' / 'infy-paper-calendar-2026-11-20.json')      # close 15:15
        engine = PaperEngine(self.tmp / 'paper.sqlite')
        late = dict(symbol='DEMO', provider='p', adjustment='None', source='imported', permitted=True, capital=10000,
                    units=10, maxExposure=5000, dailyLossLimit=500, costBps=10, slippageBps=5, strategy='intraday-v1',
                    maxLoss=100, stopDistancePct=1, targetMultiple=2, participationPct=5, entryEnd='14:30', squareOff='15:15')
        engine.create(late)
        _, _, c = self.items('--calendar', cal)
        self.assertEqual(c['calendar']['status'], 'FAIL')
        self.assertIn('15:15', c['calendar']['detail'])
        engine.create(dict(late, squareOff='15:05'))
        code, _, c = self.items('--calendar', cal)
        self.assertEqual(c['calendar']['status'], 'PASS')
        self.assertIn('1 of 2', c['calendar']['detail'])
        self.assertIn('cannot be armed', c['calendar']['detail'])

    def test_stale_calendar_fails_and_pass_reports_version_and_runway(self):
        import json
        sample = json.loads((ROOT / 'docs' / 'infy-paper-calendar-2026-11-20.json').read_text())
        _, _, c = self.items('--calendar', str(ROOT / 'docs' / 'infy-paper-calendar-2026-11-20.json'))
        self.assertIn(sample['version'], c['calendar']['detail'])
        self.assertIn('runway', c['calendar']['detail'])
        stale = self.tmp / 'stale.json'
        stale.write_text(json.dumps(dict(sample, availableAt='2025-01-01T00:00:00+05:30')))
        _, _, c = self.items('--calendar', str(stale))
        self.assertEqual(c['calendar']['status'], 'FAIL')
        self.assertIn('stale', c['calendar']['detail'])

    def test_market_hours_approximate(self):
        _, _, c = self.items()
        self.assertEqual(c['market-hours']['status'], 'PASS')
        self.assertIn('approximate', c['market-hours']['detail'].lower())
        _, _, c = self.items(now='2026-11-22T11:00:00+05:30')  # Sunday
        self.assertEqual(c['market-hours']['status'], 'BLOCKED')
        _, _, c = self.items(now='2026-11-23T20:00:00+05:30')
        self.assertEqual(c['market-hours']['status'], 'BLOCKED')
        self.assertIn('2026-11-23', c['market-hours']['detail'])

    def test_replay_stub_pass_and_fail(self):
        ok = self.tmp / 'ok.py'
        ok.write_text('print("{}")\n')
        bad = self.tmp / 'bad.py'
        bad.write_text('import sys; sys.exit(3)\n')
        argv = ['--now', NOW, '--env-file', str(self.tmp / 'absent.env'), '--json']
        for script, status in ((ok, 'PASS'), (bad, 'FAIL')):
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                got = paper_readiness.main(argv + ['--replay-script', str(script)], environ=self.env)
            data = {x['id']: x for x in json.loads(out.getvalue())['checks']}
            self.assertEqual(data['fixture-replay']['status'], status)
            if status == 'FAIL':
                self.assertEqual(got, 1)

    def test_skip_replay_is_blocked(self):
        _, _, c = self.items()
        self.assertEqual(c['fixture-replay']['status'], 'BLOCKED')

    def test_human_output_has_checklist_and_actions(self):
        _, out, _ = self.run_main(json_out=False)
        self.assertIn('BLOCKED', out)
        self.assertIn('PASS', out)
        self.assertIn('Owner action', out)
        self.assertIn('no network', out.lower())


    def test_missing_sdk_is_fail_with_exit_one(self):
        with mock.patch.object(paper_readiness.importlib.util, 'find_spec', return_value=None):
            code, _, c = self.items()
        self.assertEqual(c['kiteconnect']['status'], 'FAIL')
        self.assertEqual(code, 1)

    def test_armed_worker_default_fails(self):
        import paper_worker
        armed = dict(state='armed', enabled=True, live=False)
        with mock.patch.object(paper_worker.PaperWorker, 'status', return_value=armed):
            code, _, c = self.items()
        self.assertEqual(c['worker-default']['status'], 'FAIL')
        self.assertEqual(code, 1)

    def test_wal_sidecar_is_included_and_untouched(self):
        db = self.tmp / 'paper.sqlite'
        con = sqlite3.connect(db)
        con.execute('PRAGMA journal_mode=WAL')
        con.execute('PRAGMA wal_autocheckpoint=0')
        con.execute('CREATE TABLE accounts(id TEXT PRIMARY KEY, body TEXT NOT NULL)')
        con.execute("INSERT INTO accounts VALUES('a','{}')")
        con.commit()
        con.execute('PRAGMA wal_checkpoint(TRUNCATE)')
        con.execute("INSERT INTO accounts VALUES('b','{}')")  # newest row lives only in -wal
        con.commit()
        self.addCleanup(con.close)
        wal = Path(str(db) + '-wal')
        shm = Path(str(db) + '-shm')
        self.assertGreater(wal.stat().st_size, 0)
        before = (sha(db), sha(wal), sha(shm))
        _, _, c = self.items()
        self.assertEqual(c['paper-db']['status'], 'PASS')
        self.assertIn('2 account(s)', c['paper-db']['detail'])
        self.assertEqual((sha(db), sha(wal), sha(shm)), before)

    def test_ledger_detail_advises_stopping_app(self):
        db = self.tmp / 'paper.sqlite'
        sqlite3.connect(db).close()
        _, _, c = self.items()
        self.assertIn('stop the app', c['paper-db']['detail'].lower())

    def test_json_shape_documented(self):
        _, data, _ = self.items()
        self.assertEqual(sorted(data), ['checks', 'counts', 'generatedAt', 'istDate', 'ok'])
        self.assertEqual(sorted(data['counts']), ['BLOCKED', 'FAIL', 'PASS'])
        for item in data['checks']:
            self.assertEqual(sorted(item), ['detail', 'id', 'ownerAction', 'status', 'title'])


if __name__ == '__main__':
    unittest.main()
