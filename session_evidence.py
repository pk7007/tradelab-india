"""Versioned descriptive session evidence, with no trading control authority."""
import datetime as dt
import json

from agent_handlers import digest, encode, execute
from research import timestamp
from strategy_contract import assumed_fill


class SessionEvidence:
    def __init__(self, engine, handler=execute):
        self.engine = engine
        self.handler = handler
        with engine.db() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS session_evidence_runs (
                    input_hash TEXT PRIMARY KEY, account TEXT NOT NULL,
                    domain TEXT NOT NULL, state TEXT NOT NULL,
                    input TEXT NOT NULL, cutoff TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS session_evidence_attempts (
                    input_hash TEXT NOT NULL, attempt INTEGER NOT NULL,
                    body TEXT NOT NULL, PRIMARY KEY(input_hash, attempt)
                );
            ''')

    def observe(self, selection):
        identity = selection.get('accountId')
        if not identity:
            return self.status(None)
        cutoff = dt.datetime.now(dt.timezone.utc).isoformat()
        with self.engine.db() as db:
            account = self.engine.load(db, identity)
            reconciliation = self.engine.reconcile_in(db, account)
            events = [dict(seq=row['seq'], at=row['at'], **json.loads(row['body']))
                      for row in db.execute('SELECT * FROM events WHERE account=? ORDER BY seq', (identity,))]
            latest = db.execute('SELECT body,stamp FROM bars WHERE account=? ORDER BY stamp DESC LIMIT 1',
                                (identity,)).fetchone()
            receipt = None
            if latest:
                receipt = db.execute('SELECT received FROM receipts WHERE account=? AND stamp=?',
                                     (identity, latest['stamp'])).fetchone()
                if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='worker_receipts'").fetchone():
                    provider_receipt = db.execute('SELECT received FROM worker_receipts WHERE account=? AND stamp=?',
                                                  (identity, latest['stamp'])).fetchone()
                    receipt = provider_receipt or receipt
        records, checks = self.records(account, reconciliation, events,
                                       json.loads(latest[0]) if latest else None,
                                       receipt[0] if receipt else None)
        for domain, rows in records.items():
            payload = dict(permitted=True, records=rows)
            fingerprint = digest(dict(account=identity, domain=domain, input=payload,
                                      checks=checks.get(domain, {})))
            # The write transaction also serializes competing observers. Handlers
            # are local pure functions over at most 1,000 records.
            with self.engine.db() as db:
                prior = db.execute('SELECT * FROM session_evidence_runs WHERE input_hash=?',
                                   (fingerprint,)).fetchone()
                attempts = db.execute('SELECT COUNT(*) FROM session_evidence_attempts WHERE input_hash=?',
                                      (fingerprint,)).fetchone()[0]
                if prior and (prior['state'] == 'reviewed' or attempts >= 3):
                    continue
                if not prior:
                    db.execute('INSERT INTO session_evidence_runs VALUES(?,?,?,?,?,?)',
                               (fingerprint, identity, domain, 'pending', encode(payload), cutoff))
                    run_cutoff = cutoff
                else:
                    # A retry must use the original evidence cutoff and inputs.
                    payload = json.loads(prior['input'])
                    run_cutoff = prior['cutoff']
                attempt = dict(taskId=fingerprint + ':' + str(attempts + 1), inputHash=fingerprint,
                               attempt=attempts + 1, checks=checks.get(domain, {}),
                               executionAllowed=False, roles=[])
                try:
                    analysis_role = domain + '.analysis'
                    envelope = dict(input=payload, evidenceCutoff=run_cutoff)
                    analysis = self.handler(analysis_role, envelope)
                    attempt['roles'].append(analysis_role)
                    attempt['output'] = analysis
                    review_role = domain + '.independent-review'
                    reviewed_input = dict(payload, subject=dict(capability=analysis_role, output=analysis))
                    review = self.handler(review_role, dict(input=reviewed_input, evidenceCutoff=run_cutoff))
                    attempt['roles'].append(review_role)
                    attempt['review'] = review
                    if review.get('matches') is not True:
                        raise ValueError('Descriptive analysis review mismatch.')
                    feature_role = domain + '.feature-calculation'
                    attempt['features'] = self.handler(feature_role, envelope)
                    attempt['roles'].append(feature_role)
                    state = 'reviewed'
                    attempt['state'] = state
                except Exception as exc:
                    # Store the type only. Provider content and exception messages
                    # can contain credentials and must stay with their owners.
                    state = 'quarantined' if attempts + 1 >= 3 else 'retry-pending'
                    attempt.update(state=state, errorType=type(exc).__name__)
                db.execute('INSERT INTO session_evidence_attempts VALUES(?,?,?)',
                           (fingerprint, attempts + 1, encode(attempt)))
                db.execute('UPDATE session_evidence_runs SET state=? WHERE input_hash=?',
                           (state, fingerprint))
        return self.status(identity)

    @staticmethod
    def records(account, reconciliation, events, candle, received):
        """Extract only local numeric facts and identities from a consistent read."""
        config = account['config']
        identity, symbol = account['id'], config['symbol']
        available = events[-1]['at']
        common = dict(source='local:paper-ledger', observedAt=available, availableAt=available)
        records, checks = {}, {}

        def record(domain, record_id, **values):
            records.setdefault(domain, []).append(dict(common, id=record_id, **values))

        record('strategy-versioning', identity, strategyVersion=config.get('strategyRevision', config['strategy']),
               datasetHash=digest(dict(config=config, lastBar=account['lastBar'])), state=account['status'])
        record('portfolio-exposure', identity, symbol=symbol,
               exposure=account['equity'] - account['cash'], limit=config['maxExposure'])
        record('order-position-reconciliation', identity, account=identity, symbol=symbol,
               expectedQuantity=reconciliation['quantity'], observedQuantity=account['quantity'])
        checks['order-position-reconciliation'] = dict(matches=reconciliation['matches'],
                                                       mismatches=reconciliation['mismatches'])
        record('performance-attribution', identity, strategyVersion=config['strategy'],
               realized=account['realized'], fees=account['fees'])
        checks['performance-attribution'] = dict(totalPnl=account['equity'] - config['capital'],
                                                 cash=account['cash'], equity=account['equity'])
        if candle:
            candle_record = dict(candle)
            for field in ('date', 'halted', 'reject'):
                candle_record.pop(field, None)
            record('historical-candles', candle['date'], symbol=symbol,
                   **{key: candle_record[key] for key in ('open', 'high', 'low', 'close', 'volume')})
            records['historical-candles'][0].update(observedAt=candle['date'], availableAt=received or available)
            checks['historical-candles'] = dict(
                completedAt=(timestamp(candle['date']) + dt.timedelta(minutes=5)).isoformat(),
                receiptRecorded=received is not None)
        fills = [event for event in events if event['type'] == 'fill']
        cash = config['capital']
        for fill in fills[:-1000]:
            value = fill['quantity'] * fill['price']
            cash += value - fill['fee'] if fill['side'] == 'SELL' else -value - fill['fee']
        sizing_checks, risk_checks = [], []
        for fill in fills[-1000:]:
            record_id = identity + ':' + str(fill['seq'])
            side, quantity, price, fee = (fill[key] for key in ('side', 'quantity', 'price', 'fee'))
            raw = price / (1 + (1 if side == 'BUY' else -1) * config['slippageBps'] / 10000)
            record('paper-execution', record_id, account=identity, symbol=symbol,
                   side=side, quantity=quantity, price=price)
            record('transaction-costs', record_id, symbol=symbol, fee=fee,
                   slippage=abs(price - raw) * quantity, quantity=quantity)
            if side == 'BUY':
                record('position-sizing', record_id, symbol=symbol, quantity=quantity,
                       price=price, capital=cash)
                sizing_checks.append(dict(id=record_id, fitsCashIncludingFees=quantity * price + fee <= cash + 1e-8))
                if config.get('strategy') == 'intraday-v1':
                    stop = raw * (1 - config['stopDistancePct'] / 100)
                    stop_price, stop_fee = assumed_fill(stop, quantity, 'SELL', config['costBps'], config['slippageBps'])
                    planned = quantity * (price - stop_price) + fee + stop_fee
                    record('trade-risk', record_id, symbol=symbol, entry=price, stop=stop,
                           quantity=quantity, maxLoss=config['maxLoss'])
                    risk_checks.append(dict(id=record_id, plannedLossIncludingCosts=planned,
                                            withinConfiguredTradeAllowance=planned <= config['maxLoss'] + 1e-8))
                cash -= quantity * price + fee
            else:
                cash += quantity * price - fee
            for domain in ('paper-execution', 'transaction-costs', 'position-sizing', 'trade-risk'):
                if records.get(domain) and records[domain][-1]['id'] == record_id:
                    records[domain][-1].update(observedAt=fill['bar'], availableAt=fill['at'])
        if sizing_checks:
            checks['position-sizing'] = dict(fills=sizing_checks, completeFillCoverage=len(fills) <= 1000)
        if risk_checks:
            checks['trade-risk'] = dict(fills=risk_checks, stopExecutionGuaranteed=False)
        return records, checks

    def status(self, identity):
        if not identity:
            return dict(accountId=None, tasks=[], rolesRun=[], executionAllowed=False,
                        missingStages=['No managed session selected.'])
        with self.engine.db() as db:
            rows = db.execute('''SELECT r.rowid AS version, r.*, a.body
                FROM session_evidence_runs r JOIN session_evidence_attempts a USING(input_hash)
                WHERE r.account=? AND a.attempt=(SELECT MAX(attempt) FROM session_evidence_attempts
                    WHERE input_hash=r.input_hash) ORDER BY r.rowid DESC''', (identity,)).fetchall()
        latest = {}
        for row in rows:
            if row['domain'] not in latest:
                latest[row['domain']] = dict(json.loads(row['body']), domain=row['domain'],
                                            version=row['version'], evidenceCutoff=row['cutoff'])
        tasks = list(latest.values())
        return dict(accountId=identity, tasks=tasks,
                    rolesRun=sorted({role for task in tasks for role in task['roles']}),
                    executionAllowed=False,
                    reviewScope='Deterministic re-computation of descriptive evidence; no strategy approval or quality score.',
                    missingStages=['News-to-signal validation', 'Pre-entry agent approval',
                                   'Forward-market acceptance', 'Independent strategy profitability validation'])
