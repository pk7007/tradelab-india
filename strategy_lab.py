"""Versioned offline experiments and guarded automatic PAPER promotion."""
from contextlib import contextmanager
import datetime as dt
import hashlib
import json
import math
from pathlib import Path
import random
import sqlite3
from tempfile import TemporaryDirectory
import uuid

from intraday_evaluation import evaluate_intraday
from paper import PaperEngine
from research import IST, timestamp

TUNABLE = {'stopDistancePct', 'targetMultiple', 'entryEnd', 'squareOff'}


def encoded(value):
    return json.dumps(value, sort_keys=True, allow_nan=False, separators=(',', ':'))


def fingerprint(value):
    return hashlib.sha256(encoded(value).encode()).hexdigest()


def metrics(report):
    """Costed closed round trips, retaining unresolved exposure separately."""
    basis = 0.0
    quantity = 0
    trade_pnl = 0.0
    outcomes = []
    for fill in report['fills']:
        units = fill['quantity']
        if fill['side'] == 'BUY':
            basis += units * fill['price'] + fill['fee']
            quantity += units
        else:
            cost = basis * units / quantity
            trade_pnl += units * fill['price'] - fill['fee'] - cost
            basis -= cost
            quantity -= units
            if quantity == 0:
                outcomes.append(trade_pnl)
                trade_pnl = 0.0
    lower = None
    if len(outcomes) >= 30:
        rng = random.Random(42)
        samples = sorted(sum(rng.choices(outcomes, k=len(outcomes))) / len(outcomes)
                         for _ in range(1000))
        lower = samples[49]
    return dict(completedTrades=len(outcomes), netExpectancy=sum(outcomes) / len(outcomes) if outcomes else None,
                bootstrapLower95=lower, returnPct=report['returnPct'], maxDrawdownPct=report['maxDrawdownPct'],
                fees=report['fees'], openQuantity=report['openQuantity'], pending=report['pending'],
                ledgerMatches=report['ledgerMatches'])


def forward_evidence(account, candidate_id, events, observed_stamps, drawdown_limit):
    """Require candidate-specific executable quote paper evidence, never OHLC receipts.

    The quote execution/mark producer is not implemented yet. This explicit
    contract therefore leaves promotion closed for every current candle worker.
    """
    if account['quantity'] or account.get('pending'):
        raise ValueError('Forward evidence must be flat without pending orders.')
    fills = [event for event in events if event.get('type') == 'fill']
    if not observed_stamps or not fills:
        raise ValueError('Executable quote paper evidence is unavailable; candle observations do not qualify.')
    if any(fill.get('strategyRevision') != candidate_id or
           fill.get('executionModel') != 'observed-quote-paper' or
           timestamp(fill['bar']).isoformat() not in observed_stamps for fill in fills):
        raise ValueError('Candidate-specific executable quote fills required; baseline and candle fills do not qualify.')
    sessions = {timestamp(fill['bar']).date() for fill in fills}
    marks = [event for event in events if event.get('type') == 'quote-mark']
    if not marks or any(mark.get('strategyRevision') != candidate_id or
                        timestamp(mark['bar']).isoformat() not in observed_stamps or
                        isinstance(mark.get('equity'), bool) or
                        not isinstance(mark.get('equity'), (int, float)) or
                        not math.isfinite(mark['equity']) or mark['equity'] <= 0 for mark in marks):
        raise ValueError('Candidate-specific executable quote equity marks required.')
    if any(timestamp(b['bar']) < timestamp(a['bar']) for a, b in zip(marks, marks[1:])):
        raise ValueError('Forward quote equity marks must be ordered.')
    if not {timestamp(fill['bar']).isoformat() for fill in fills} <= {timestamp(mark['bar']).isoformat() for mark in marks}:
        raise ValueError('Every forward fill requires a reconciled quote equity mark.')
    peak = account['config']['capital']; drawdown = 0
    for mark in marks:
        peak = max(peak, mark['equity'])
        drawdown = max(drawdown, 100 * (1 - mark['equity'] / peak))
    if not math.isclose(marks[-1]['equity'], account['equity'], abs_tol=1e-7, rel_tol=1e-10):
        raise ValueError('Final forward quote equity must reconcile to the paper account.')
    result = metrics(dict(fills=fills, returnPct=100 * (account['equity']/account['config']['capital']-1),
                          maxDrawdownPct=drawdown, fees=account['fees'], openQuantity=account['quantity'],
                          pending=account.get('pending'), ledgerMatches=True))
    if len(sessions) < 10 or result['completedTrades'] < 30:
        raise ValueError('Thirty completed candidate quote paper trades across ten observed sessions required.')
    if (result['netExpectancy'] or 0) <= 0 or (result['bootstrapLower95'] or 0) <= 0 or result['returnPct'] <= 0 or drawdown > drawdown_limit:
        raise ValueError('Candidate forward expectancy, uncertainty and drawdown acceptance failed.')
    return result


class StrategyLab:
    def __init__(self, path, paper_engine=None, clock=lambda: dt.datetime.now(IST)):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.paper = paper_engine
        self.clock = clock
        with self.db() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS hypotheses(id TEXT PRIMARY KEY, body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS revisions(id TEXT PRIMARY KEY, hypothesis TEXT NOT NULL, body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS evaluations(id TEXT PRIMARY KEY, hypothesis TEXT NOT NULL,
                    revision TEXT NOT NULL, stage TEXT NOT NULL, body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS sealed_views(partition TEXT PRIMARY KEY, evaluation TEXT NOT NULL, data_hash TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS sealed_windows(partition TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL, first_session TEXT NOT NULL, last_session TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS exposed_windows(evaluation TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL, first_session TEXT NOT NULL, last_session TEXT NOT NULL,
                    stage TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS lab_events(seq INTEGER PRIMARY KEY, at TEXT NOT NULL, body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS paper_promotions(id TEXT PRIMARY KEY, day TEXT UNIQUE NOT NULL,
                    account TEXT NOT NULL, hypothesis TEXT NOT NULL, revision TEXT NOT NULL,
                    previous_config TEXT NOT NULL, promoted_config TEXT NOT NULL, rolled_back INTEGER NOT NULL DEFAULT 0);
            ''')

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        try:
            db.execute('BEGIN IMMEDIATE')
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def event(self, db, kind, **values):
        db.execute('INSERT INTO lab_events(at,body) VALUES(?,?)',
                   (self.clock().isoformat(), encoded(dict(type=kind, **values))))

    def register(self, values):
        if not isinstance(values, dict):
            raise ValueError('Hypothesis object required.')
        text = values.get('hypothesis')
        if not isinstance(text, str) or not 1 <= len(text.strip()) <= 2000:
            raise ValueError('State the evidence-backed hypothesis.')
        provenance = values.get('provenance')
        required = {'datasetId', 'datasetVersion', 'source', 'corporateActions', 'universe', 'benchmark'}
        if not isinstance(provenance, dict) or set(provenance) != required:
            raise ValueError('Provide datasetId/version, source, corporateActions, universe and benchmark provenance.')
        if any(not isinstance(value, str) or not value.strip() or len(value) > 1000 for value in provenance.values()):
            raise ValueError('Provenance fields require bounded nonempty text.')
        criteria = values.get('criteria')
        if not isinstance(criteria, dict) or set(criteria) != {'maxDrawdownPct'}:
            raise ValueError('Pre-register maxDrawdownPct only; other acceptance gates are fixed.')
        limit = criteria['maxDrawdownPct']
        if isinstance(limit, bool) or not isinstance(limit, (int, float)) or not math.isfinite(limit) or not 0 < limit <= 100:
            raise ValueError('Drawdown limit must be a positive percentage up to 100.')
        config = values.get('baselineConfig')
        with TemporaryDirectory() as directory:
            validator = PaperEngine(Path(directory) / 'validate.sqlite')
            config = validator.create(dict(config or {}, permitted=True))['config']
        if config['strategy'] != 'intraday-v1':
            raise ValueError('Only the existing Intraday v1 declarative model is supported.')
        identity = uuid.uuid4().hex
        body = dict(id=identity, hypothesis=text.strip(), accountId=values.get('accountId'),
                    baselineConfig=config, criteria=criteria, provenance=provenance,
                    registeredAt=self.clock().isoformat(), policy='paper-improvement-v1',
                    policyDetails=dict(minSessions=60, holdoutSessions=20, maxCandidates=5,
                                       minObservedTrades=30, minObservedSessions=10,
                                       bootstrapSamples=1000, bootstrapSeed=42))
        body['fingerprint'] = fingerprint(body)
        with self.db() as db:
            db.execute('INSERT INTO hypotheses VALUES(?,?)', (identity, encoded(body)))
            self.event(db, 'hypothesis-registered', id=identity)
        return body

    @staticmethod
    def load(db, table, identity):
        if table not in ('hypotheses', 'revisions'):
            raise ValueError('Unknown object type.')
        row = db.execute('SELECT body FROM ' + table + ' WHERE id=?', (identity,)).fetchone()
        if row is None:
            raise ValueError('Unknown experiment object.')
        return json.loads(row['body'])

    def add_candidate(self, hypothesis_id, changes):
        if not isinstance(changes, dict) or not changes or not set(changes) <= TUNABLE:
            raise ValueError('Only stop distance, target multiple, entry cutoff and square-off are tunable.')
        with self.db() as db:
            hypothesis = self.load(db, 'hypotheses', hypothesis_id)
            if db.execute('SELECT COUNT(*) FROM revisions WHERE hypothesis=?', (hypothesis_id,)).fetchone()[0] >= 5:
                raise ValueError('Five registered candidate configurations per hypothesis maximum.')
            if db.execute("SELECT COUNT(*) FROM evaluations WHERE hypothesis=? AND stage='final'", (hypothesis_id,)).fetchone()[0]:
                raise ValueError('Final holdout already opened; this hypothesis is frozen.')
            config = dict(hypothesis['baselineConfig'], **changes)
            from intraday_contract import validate
            validate(config)
            identity = uuid.uuid4().hex
            body = dict(id=identity, hypothesis=hypothesis_id, config=config,
                        fingerprint=fingerprint(config), createdAt=self.clock().isoformat())
            db.execute('INSERT INTO revisions VALUES(?,?,?)', (identity, hypothesis_id, encoded(body)))
            self.event(db, 'candidate-registered', id=identity, hypothesis=hypothesis_id)
        return body

    def evaluate(self, hypothesis_id, candidate_id, bars, permitted=False, stage='final'):
        if permitted is not True:
            raise ValueError('Explicit temporary replay permission required.')
        if stage not in ('validation', 'final') or not isinstance(bars, list) or not 1 <= len(bars) <= 20000:
            raise ValueError('Choose validation/final and supply at most 20,000 candles.')
        dates = sorted({timestamp(row['date']).date().isoformat() for row in bars})
        if len(dates) < 60:
            raise ValueError('At least 60 distinct historical sessions required.')
        selected_dates = set(dates[-20:] if stage == 'final' else dates[20:-20])
        rows = [row for row in bars if timestamp(row['date']).date().isoformat() in selected_dates]
        identity = uuid.uuid4().hex
        with self.db() as db:
            hypothesis = self.load(db, 'hypotheses', hypothesis_id)
            revision = self.load(db, 'revisions', candidate_id)
            if revision['hypothesis'] != hypothesis_id:
                raise ValueError('Candidate belongs to another hypothesis.')
            data_hash = fingerprint(bars)
            if hypothesis.get('datasetFingerprint') not in (None, data_hash):
                raise ValueError('Dataset changed after the first evaluation. Register a new hypothesis.')
            if 'datasetFingerprint' not in hypothesis:
                hypothesis['datasetFingerprint'] = data_hash
                db.execute('UPDATE hypotheses SET body=? WHERE id=?', (encoded(hypothesis), hypothesis_id))
            partition = fingerprint([hypothesis['baselineConfig']['symbol'], min(selected_dates), max(selected_dates)])
            symbol = hypothesis['baselineConfig']['symbol']
            # A shifted endpoint must not make previously exposed final sessions
            # independent again, including when relabelled as validation data.
            overlap = db.execute('''SELECT 1 FROM sealed_windows WHERE symbol=?
                AND first_session<=? AND last_session>=? LIMIT 1''',
                                 (symbol, max(selected_dates), min(selected_dates))).fetchone()
            # Old databases stored only a non-reversible partition hash. Preserve
            # those seals conservatively rather than invent their missing dates.
            legacy = db.execute('''SELECT h.body FROM sealed_views s
                JOIN evaluations e ON e.id=s.evaluation
                JOIN hypotheses h ON h.id=e.hypothesis
                LEFT JOIN sealed_windows w ON w.partition=s.partition
                WHERE w.partition IS NULL''').fetchall()
            if overlap or any(json.loads(row['body'])['baselineConfig']['symbol'] == symbol for row in legacy):
                raise ValueError('This symbol/time holdout was already opened; independent final evidence unavailable.')
            if stage == 'final':
                exposed = db.execute('''SELECT 1 FROM exposed_windows WHERE symbol=?
                    AND first_session<=? AND last_session>=? LIMIT 1''',
                                     (symbol, max(selected_dates), min(selected_dates))).fetchone()
                # Previous versions did not retain validation dates. Such
                # exposure cannot safely be declared independent on migration.
                unknown = db.execute('''SELECT h.body FROM evaluations e
                    JOIN hypotheses h ON h.id=e.hypothesis
                    LEFT JOIN exposed_windows x ON x.evaluation=e.id
                    WHERE x.evaluation IS NULL''').fetchall()
                if exposed or any(json.loads(row['body'])['baselineConfig']['symbol'] == symbol for row in unknown):
                    raise ValueError('This symbol/time evidence was already opened; independent final evidence unavailable.')
                try:
                    db.execute('INSERT INTO sealed_views VALUES(?,?,?)', (partition, identity, fingerprint(rows)))
                except sqlite3.IntegrityError:
                    raise ValueError('This symbol/time holdout was already opened; independent final evidence unavailable.') from None
                db.execute('INSERT INTO sealed_windows VALUES(?,?,?,?)',
                           (partition, symbol, min(selected_dates), max(selected_dates)))
            # Persist exposure before computation, including failed or rejected
            # evaluations. Validation may repeat; final evidence may never reuse it.
            db.execute('INSERT INTO exposed_windows VALUES(?,?,?,?,?)',
                       (identity, symbol, min(selected_dates), max(selected_dates), stage))
            db.execute('INSERT INTO evaluations VALUES(?,?,?,?,?)',
                       (identity, hypothesis_id, candidate_id, stage, encoded(dict(state='running', partition=partition))))
            self.event(db, 'evaluation-opened', id=identity, stage=stage, partition=partition)
        try:
            baseline = evaluate_intraday(dict(permitted=True, config=hypothesis['baselineConfig'], bars=rows))
            candidate = evaluate_intraday(dict(permitted=True, config=revision['config'], bars=rows))
            stress_config = dict(revision['config'], costBps=min(500, revision['config']['costBps'] * 2),
                                 slippageBps=min(500, revision['config']['slippageBps'] * 2))
            stress = evaluate_intraday(dict(permitted=True, config=stress_config, bars=rows))
            base_metrics, candidate_metrics, stress_metrics = metrics(baseline), metrics(candidate), metrics(stress)
            gates = dict(ledger=candidate_metrics['ledgerMatches'] and stress_metrics['ledgerMatches'],
                         flat=candidate_metrics['openQuantity'] == 0 and stress_metrics['openQuantity'] == 0,
                         expectancy=(candidate_metrics['netExpectancy'] or 0) > 0,
                         uncertainty=(candidate_metrics['bootstrapLower95'] or 0) > 0,
                         baselineImprovement=candidate_metrics['returnPct'] > base_metrics['returnPct'],
                         drawdown=candidate_metrics['maxDrawdownPct'] <= hypothesis['criteria']['maxDrawdownPct'],
                         stress=(stress_metrics['netExpectancy'] or 0) > 0)
            result = dict(id=identity, hypothesis=hypothesis_id, revision=candidate_id, stage=stage,
                          state='eligible' if stage == 'final' and all(gates.values()) else 'rejected',
                          gates=gates, baseline=base_metrics, candidate=candidate_metrics, stress=stress_metrics,
                          datasetFingerprint=fingerprint(bars), partition=partition,
                          acceptance='One sealed final candidate; 5% seeded trade bootstrap lower bound; doubled costs/slippage.',
                          evidenceLimitations=['Assumed OHLC fills', 'Calendar and corporate-action provenance require independent verification',
                                               'No authenticated forward or executable quote acceptance',
                                               'Gap/latency/liquidity scenario suite still required before promotion'])
            scenarios = {}
            for name in ('gap', 'low-liquidity', 'rejected', 'latency-cost'):
                scenario_rows = [dict(row) for row in rows]
                scenario_config = dict(revision['config'])
                if name == 'gap':
                    for row in scenario_rows:
                        if timestamp(row['date']).strftime('%H:%M') == '11:00':
                            for key in ('open', 'high', 'low', 'close'):
                                row[key] *= .95
                elif name == 'low-liquidity':
                    for row in scenario_rows:
                        row['volume'] = 1
                elif name == 'rejected':
                    for row in scenario_rows:
                        row['reject'] = True
                else:
                    scenario_config['slippageBps'] = min(500, scenario_config['slippageBps'] * 3 + 10)
                report = evaluate_intraday(dict(permitted=True, config=scenario_config, bars=scenario_rows))
                scenarios[name] = metrics(report)
            result['scenarios'] = scenarios
            result['scenarioAcceptance'] = all(report['ledgerMatches'] and report['openQuantity'] == 0
                                               and report['maxDrawdownPct'] <= hypothesis['criteria']['maxDrawdownPct']
                                               for report in scenarios.values())
            result['promotionAllowed'] = result['state'] == 'eligible' and result['scenarioAcceptance']
        except Exception as exc:
            result = dict(id=identity, state='failed', errorType=type(exc).__name__, promotionAllowed=False)
        with self.db() as db:
            db.execute('UPDATE evaluations SET body=? WHERE id=?', (encoded(result), identity))
            self.event(db, 'evaluation-finished', id=identity, state=result['state'])
        if result.get('promotionAllowed') and self.paper is not None:
            try:
                result['automaticPromotion'] = self.promote(hypothesis_id, candidate_id)
            except (ValueError, sqlite3.Error) as exc:
                result['automaticPromotion'] = dict(state='deferred', reason=str(exc) if isinstance(exc, ValueError)
                                                    else 'Paper database unavailable; promotion deferred.')
            with self.db() as db:
                db.execute('UPDATE evaluations SET body=? WHERE id=?', (encoded(result), identity))
        return result

    def promote(self, hypothesis_id, candidate_id):
        if self.paper is None:
            raise ValueError('Trusted paper engine required for promotion.')
        with self.db() as db:
            hypothesis = self.load(db, 'hypotheses', hypothesis_id)
            revision = self.load(db, 'revisions', candidate_id)
            if revision['hypothesis'] != hypothesis_id:
                raise ValueError('Candidate belongs to another hypothesis.')
            rows = db.execute("SELECT body FROM evaluations WHERE hypothesis=? AND revision=? AND stage='final'",
                              (hypothesis_id, candidate_id)).fetchall()
            if not rows or not json.loads(rows[-1]['body']).get('promotionAllowed'):
                raise ValueError('Independent scenario, forward observation and final acceptance are incomplete.')
            self.attach_paper(db)
            account = self.paper.load(db, hypothesis['accountId'])
            self.check_flat(db, account)
            current = dict(account['config'])
            current.pop('strategyRevision', None)
            if current != hypothesis['baselineConfig']:
                raise ValueError('Account baseline changed; register a new hypothesis.')
            tables = {row[0] for row in db.execute("SELECT name FROM paper.sqlite_master WHERE type='table'")}
            if 'worker_receipts' not in tables:
                raise ValueError('Observed forward paper receipt history is unavailable.')
            observed = db.execute("SELECT stamp FROM paper.worker_receipts WHERE account=? AND mode='observed-quote-paper'",
                                  (account['id'],)).fetchall()
            observed_bars = {row['stamp'] for row in observed}
            events = [json.loads(row[0]) for row in db.execute('SELECT body FROM paper.events WHERE account=?', (account['id'],))]
            forward = forward_evidence(account, candidate_id, events, observed_bars,
                                       hypothesis['criteria']['maxDrawdownPct'])
            day = self.clock().date().isoformat()
            if not account.get('lastBar') or timestamp(account['lastBar']).date().isoformat() != day:
                raise ValueError('Promotion requires a current-session reconciled observation.')
            previous_config = dict(account['config'])
            config = dict(revision['config'], strategyRevision=candidate_id)
            identity = uuid.uuid4().hex
            try:
                db.execute('INSERT INTO paper_promotions VALUES(?,?,?,?,?,?,?,0)',
                           (identity, day, account['id'], hypothesis_id, candidate_id, encoded(account['config']), encoded(config)))
            except sqlite3.IntegrityError:
                raise ValueError('One automatic paper promotion per trading day maximum.') from None
            account['config'] = config
            self.paper.save(db, account, dict(type='strategy-promoted', revision=candidate_id,
                                             previousConfig=previous_config,
                                             config=config,
                                             forwardEvidence=forward,
                                             detail='Validated paper revision activated while flat and paused.'))
            self.event(db, 'paper-promoted', id=identity, account=account['id'], revision=candidate_id)
        return dict(id=identity, accountId=account['id'], revision=candidate_id, state='promoted', live=False)

    def attach_paper(self, db):
        if self.paper is None or self.paper.path.resolve() == self.path.resolve():
            raise ValueError('A separate trusted paper database is required.')
        db.execute('ATTACH DATABASE ? AS paper', (str(self.paper.path),))

    def check_flat(self, db, account):
        if account['quantity'] or account.get('pending') or account['status'] == 'running':
            raise ValueError('Pause ingestion and resolve all exposure and pending intents before changing versions.')
        if not self.paper.reconcile_in(db, account)['matches']:
            raise ValueError('Paper account reconciliation failed.')
        tables = db.execute("SELECT name FROM paper.sqlite_master WHERE type='table'").fetchall()
        if 'paper_workers' in {row['name'] for row in tables}:
            worker = db.execute('SELECT enabled FROM paper.paper_workers WHERE account=?', (account['id'],)).fetchone()
            if worker and worker['enabled']:
                raise ValueError('Stop the paper worker before changing strategy version.')

    def rollback(self, account_id, reason):
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError('Rollback reason required.')
        with self.db() as db:
            row = db.execute('SELECT * FROM paper_promotions WHERE account=? AND rolled_back=0 ORDER BY rowid DESC LIMIT 1',
                             (account_id,)).fetchone()
            if row is None:
                raise ValueError('No lab-promoted version exists.')
            self.attach_paper(db)
            account = self.paper.load(db, account_id)
            self.check_flat(db, account)
            if account['config'] != json.loads(row['promoted_config']):
                raise ValueError('Account configuration changed outside this promotion.')
            previous_config = account['config']
            account['config'] = json.loads(row['previous_config'])
            self.paper.save(db, account, dict(type='strategy-rollback', promotion=row['id'], reason=reason[:1000],
                                             previousConfig=previous_config, config=account['config']))
            db.execute('UPDATE paper_promotions SET rolled_back=1 WHERE id=?', (row['id'],))
            self.event(db, 'paper-rollback', id=row['id'], account=account_id, reason=reason[:1000])
        return dict(accountId=account_id, state='rolled-back', live=False)

    def status(self):
        with self.db() as db:
            hypotheses = [json.loads(row[0]) for row in db.execute('SELECT body FROM hypotheses')]
            revisions = [json.loads(row[0]) for row in db.execute('SELECT body FROM revisions')]
            evaluations = [json.loads(row[0]) for row in db.execute('SELECT body FROM evaluations')]
            history = [dict(seq=row['seq'], at=row['at'], **json.loads(row['body']))
                       for row in db.execute('SELECT * FROM lab_events ORDER BY seq DESC LIMIT 100')]
        return dict(hypotheses=hypotheses, revisions=revisions, evaluations=evaluations, history=history,
                    mode='offline-paper-research', live=False, automaticPromotionReady=self.paper is not None)
