"""Local department supervision backed by bounded evidence-processing tasks."""
import copy
import datetime as dt
import threading


class DeskCoordinator:
    def __init__(self, news, market, paper, worker, agents):
        self.news, self.market, self.paper = news, market, paper
        self.worker, self.agents = worker, agents
        self.lock = threading.Lock()
        self.shutdown = threading.Event()
        self.thread = None
        self.snapshot = dict(state='starting', departments=[], executionAllowed=False)

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.shutdown.clear()
        self.agents.start()
        self.thread = threading.Thread(target=self.loop, name='tradelab-desk', daemon=True)
        self.thread.start()

    def stop(self):
        self.shutdown.set()
        if self.thread:
            self.thread.join(timeout=15)
        self.agents.stop()

    def loop(self):
        while not self.shutdown.is_set():
            try:
                self.tick()
            except Exception:
                with self.lock:
                    self.snapshot = dict(state='unavailable', executionAllowed=False,
                                         error='Department checks failed')
            self.shutdown.wait(30)

    def tick(self):
        now = dt.datetime.now(dt.timezone.utc)
        at = now.isoformat()
        departments = []
        for name, read in [('news', lambda: self.news.status(getattr(self.market, 'master', []))),
                           ('paper', self.worker.status), ('ledger', self.paper.status)]:
            try:
                value = read()
                if name == 'news':
                    state = 'degraded' if value.get('stale') or value.get('partial') else 'available'
                    detail = dict(eligibleItems=len(value.get('items', [])),
                                  mappedItems=sum(bool(r.get('symbols')) for r in value.get('items', [])))
                elif name == 'paper':
                    state = value.get('state', 'unknown')
                    detail = dict(accountId=value.get('accountId'), lastAcceptedBar=value.get('lastAcceptedBar'),
                                  reason=value.get('lastError'))
                else:
                    accounts = value.get('accounts', [])
                    mismatches = [a['id'] for a in accounts if not self.paper.reconcile(a['id'])['matches']]
                    state = 'blocked' if mismatches else 'reconciled'
                    detail = dict(accounts=len(accounts), mismatches=mismatches,
                                  openAccounts=[a['id'] for a in accounts if a['quantity'] or a['pending']])
            except Exception:
                state, detail = 'unavailable', dict(reason='Source check failed')
            departments.append(dict(name=name, state=state, detail=detail))
        tasks = []
        for department in departments:
            key = 'desk-v1-' + str(int(now.timestamp()) // 300) + '-' + department['name']
            with self.agents.db() as db:
                prior = db.execute('SELECT id FROM tasks WHERE key=?', (key,)).fetchone()
                pending = db.execute("SELECT COUNT(*) FROM tasks WHERE state IN ('queued','running','review')").fetchone()[0]
            if prior:
                tasks.append(prior['id'])
            elif pending < 100:
                # Store health metadata only. Article text and broker credentials stay with their owners.
                record = dict(id=department['name'], source='local:desk-observation',
                              observedAt=at, availableAt=at, service=department['name'],
                              state=department['state'],
                              errorCount=int(department['state'] in ('blocked', 'unavailable', 'degraded')))
                tasks.append(self.agents.enqueue(dict(capability='operations-security.monitoring',
                    input=dict(permitted=True, records=[record], maxAgeSeconds=60), evidenceCutoff=at,
                    priority=2, budgetSeconds=10, deadlineSeconds=120, idempotencyKey=key)))
        with self.lock:
            self.snapshot = dict(state='monitoring', checkedAt=at, departments=departments,
                                 tasks=tasks, reviewQueueFull=pending >= 100, executionAllowed=False,
                                 handoffs=[['news', 'research-context'], ['news', 'paper-context'],
                                           ['paper', 'ledger'], ['department-health', 'agent-review']],
                                 pendingIntegrations=['Automatic whole-market research', 'Strategy validation from news'])
        return self.status()

    def status(self):
        with self.lock:
            return dict(copy.deepcopy(self.snapshot), running=bool(self.thread and self.thread.is_alive()))
