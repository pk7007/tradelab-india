"""Read-only session presentation built from the persistent paper ledger."""
import datetime as dt
import hashlib
import json

import trading_calendar

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
INTENDED_PROFILE = dict(capital=10000, maxLoss=250, dailyLossLimit=1000)


def session_snapshot(engine, selection, settings, *, connected, storage_approved,
                     news=None, desk=None, now=None):
    """Never infer a completed exit or a running worker from requested state."""
    account = None
    events, receipts = [], []
    identity = selection.get('accountId')
    with engine.db() as db:
        if identity:
            account = engine.load(db, identity)
            reconciliation = engine.reconcile_in(db, account)
            rows = db.execute('SELECT seq,at,body FROM events WHERE account=? ORDER BY seq',
                              (identity,)).fetchall()
            events = [dict(seq=r['seq'], recordedAt=r['at'], **json.loads(r['body'])) for r in rows]
            receipts = [dict(r) for r in db.execute(
                'SELECT stamp,received,decision,mode FROM worker_receipts WHERE account=? ORDER BY stamp',
                (identity,))]
        else:
            reconciliation = None
        exposed = []
        for row in db.execute('SELECT body FROM accounts'):
            saved = json.loads(row[0])
            if saved['quantity'] or saved['pending']:
                exposed.append(dict(accountId=saved['id'], symbol=saved['config']['symbol'],
                                    quantity=saved['quantity'], pending=saved['pending']))
    no_trade = selection.get('noTradeReport')
    config = account['config'] if account else no_trade['config'] if no_trade else settings
    differences = {k: dict(saved=config.get(k), intended=v)
                   for k, v in INTENDED_PROFILE.items() if config.get(k) != v}
    fills = [event for event in events if event['type'] == 'fill']
    report = None
    if account:
        flat = not account['quantity'] and not account['pending']
        closure = ('ledger-mismatch' if not reconciliation['matches'] else
                   'reconciled-flat' if flat else 'unresolved-exposure')
        report = dict(accountId=identity, symbol=config['symbol'], strategy=config['strategy'],
                      configHash=hashlib.sha256(json.dumps(config, sort_keys=True).encode()).hexdigest(),
                      cash=account['cash'], equity=account['equity'], quantity=account['quantity'],
                      exposure=account['equity']-account['cash'], pending=account['pending'],
                      fees=account['fees'], realized=account['realized'],
                      unrealized=reconciliation['unrealized'],
                      totalPnl=account['equity']-config['capital'],
                      closureState=closure, reconciliation=reconciliation,
                      final=bool(flat and reconciliation['matches'] and not selection.get('enabled')
                                 and account['status'] != 'running'),
                      fillCount=len(fills), completedTrades=account['completedTrades'],
                      lastBar=account['lastBar'], entriesPaused=account.get('entriesPaused', False),
                      riskHalted=account['riskHalted'],
                      trace=dict(selection=selection.get('selectionTrace'), events=events,
                                 receipts=receipts, fills=fills),
                      timing='Completed five-minute observations; fills are OHLC model outcomes.')
    elif no_trade:
        report = dict(accountId=None, symbol='No stock selected', strategy=config['strategy'],
                      cash=no_trade['closingCash'], equity=no_trade['closingCash'], quantity=0,
                      exposure=0, pending=None, fees=0, realized=0, unrealized=0, totalPnl=0,
                      closureState='reconciled-flat', reconciliation=dict(matches=True, mismatches=[]),
                      final=bool(no_trade['final'] and not exposed), fillCount=0, completedTrades=0,
                      lastBar=None, entriesPaused=True, riskHalted=False,
                      trace=dict(selection=selection.get('lastScan'), events=[], receipts=[], fills=[],
                                 noTradeSession=no_trade),
                      timing='No qualifying selection or modeled fills.')
    state = selection.get('state', 'disarmed')
    attention = []
    if not connected:
        attention.append('Connect Zerodha before starting or recovering provider observations.')
    if not storage_approved:
        attention.append('Confirm approved local market-data retention in Settings.')
    calendar_state = None
    calendar_todo = None
    if isinstance(selection.get('calendar'), dict):
        moment = (now or dt.datetime.now(IST)).isoformat()
        upcoming = trading_calendar.next_open_date(selection['calendar'], moment)
        try:
            day = trading_calendar.require_trading_day(selection['calendar'], moment, strict_sessions=False,
                                                       square_off=(config or {}).get('squareOff') or '15:05')
            calendar_state = dict(ready=True, version=day['version'], date=day['date'])
        except trading_calendar.ClosedDay:
            calendar_state = dict(ready=False)
            calendar_todo = ('Today is a holiday in the calendar. The next listed open session is %s; start then.' % upcoming
                             if upcoming else 'Today is a holiday in the calendar and no later open date is listed. '
                             'Add your next trading date to the calendar.')
            attention.append('Today is marked closed in the session calendar, so a paper session cannot start. ' + calendar_todo)
        except (trading_calendar.CalendarError, ValueError, TypeError) as error:
            calendar_state = dict(ready=False)
            stale = 'stale' in str(error)
            calendar_todo = ('The calendar is more than 30 days old. Refresh it from its source and check the terms of use of that source.'
                             if stale else str(error))
            attention.append('The session calendar cannot be used: %s' % error)
    steps = [dict(key='login', label='Connect Zerodha', done=bool(connected),
                  todo='Click Connect Zerodha (top right) and sign in yourself.'),
             dict(key='retention', label='Approve local candle retention', done=bool(storage_approved),
                  todo='Set KITE_DATA_STORAGE_APPROVED=true in your own .env, then restart the app.')]
    if calendar_state is not None:
        steps.append(dict(key='calendar', label='Session calendar covers today', done=calendar_state['ready'],
                          todo=calendar_todo or 'Check the calendar.'))
    pending_steps = [step for step in steps if not step['done']]
    arming = dict(steps=steps, ready=not pending_steps,
                  nextStep=pending_steps[0]['todo'] if pending_steps else 'Press Start paper trading.')
    if report and not report['reconciliation']['matches']:
        attention.append('Ledger mismatch. Investigate before resuming entries.')
    if exposed and not selection.get('enabled'):
        attention.append('Unresolved exposure or intent remains. Processing is inactive; review recovery.')
    foreign_exposure = any(item['accountId'] != identity for item in exposed)
    recovery = bool(account and (account['quantity'] or account['pending']) and not foreign_exposure
                    and reconciliation['matches'])
    next_action = {
        'waiting-for-twenty-completed-candles': 'Wait for twenty completed session candles before selection.',
        'no-qualifying-candidate': 'Wait for the next scheduled scan; remaining in cash is valid.',
        'disarmed': 'Review the saved profile and calendar, then start paper trading.',
        'blocked': 'Review the reported failure and outstanding exposure before recovery.',
        'stopped': 'Review the closing report and any unresolved exposure.',
        'ended': 'Review the reconciled closing report.',
        'ending': 'Continue protective observations until closure is confirmed.',
    }.get(state, 'Observe the session status and next completed candle.')
    if recovery and not selection.get('enabled'):
        next_action = 'Recover observations for the saved account and review its saved entry controls.'
    return dict(mode='paper', live=False, selection=selection, account=account,
                savedProfile=config, intendedProfile=INTENDED_PROFILE,
                profileDifferences=differences, report=report, outstandingExposure=exposed,
                readiness=dict(connected=connected, storageApproved=storage_approved,
                               calendarReady=None if calendar_state is None else calendar_state['ready'],
                               recoveryRequired=recovery,
                               canRequestStart=bool(connected and storage_approved
                                                    and (calendar_state is None or calendar_state['ready'])
                                                    and not selection.get('enabled') and not foreign_exposure
                                                    and not (no_trade and no_trade.get('final'))
                                                    and (not exposed or recovery)
                                                    and (not reconciliation or reconciliation['matches']))),
                attention=attention, arming=arming, nextAction=next_action,
                news=dict(status=(news or {}).get('status', 'unavailable'),
                          stale=(news or {}).get('stale', True),
                          sources=(news or {}).get('sources', []),
                          decisionEffect='Advisory context; no validated news-based signal or sentiment rule.'),
                agents=desk or {}, deferred=['Long-term research', 'Live-money activation'],
                observedAt=dt.datetime.now(dt.timezone.utc).isoformat())
