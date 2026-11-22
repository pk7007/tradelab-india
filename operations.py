"""Local storage health and consistent per-ledger backup operations."""
import datetime as dt
import json
from pathlib import Path
import threading
import tempfile

from storage_ops import snapshot, verify, restore


class Operations:
    def __init__(self, paths, root, paper_engine=None, alerts=None):
        self.paths = list(dict.fromkeys(Path(path).resolve() for path in paths))
        self.root = Path(root).resolve()
        self.lock = threading.Lock()
        self.paper_engine = paper_engine
        self.alerts = alerts
        self.shutdown = threading.Event()
        self.thread = None
        self.ensure_watcher = None

    def backup(self):
        with self.lock:
            stamp = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
            return snapshot(self.paths, self.root / 'backups' / stamp)

    def start(self):
        if self.thread and self.thread.is_alive():
            return
        self.shutdown.clear()
        self.thread = threading.Thread(target=self._run, name='tradelab-backups', daemon=True)
        self.thread.start()

    def stop(self):
        self.shutdown.set()
        if self.thread:
            self.thread.join(timeout=2)

    def _run(self):
        while not self.shutdown.is_set():
            if self.ensure_watcher:
                try:
                    self.ensure_watcher()
                except Exception:
                    pass  # Retry independently of backup failures on the next cycle.
            try:
                latest = self.coverage()
                now = dt.datetime.now(dt.timezone.utc)
                if (not latest or not latest['complete'] or latest['missing']
                        or now - dt.datetime.fromisoformat(latest['createdAt']) > dt.timedelta(days=1)):
                    self.backup()
                if self.alerts:
                    self.alerts.observe('backup:failed', 'Automatic private backup failed. Check storage health.', False)
            except Exception:
                if self.alerts:
                    try:
                        self.alerts.observe('backup:failed', 'Automatic private backup failed. Check storage health.', True)
                    except Exception:
                        pass  # A failed inbox must not terminate future backup retries.
            self.shutdown.wait(300)

    def coverage(self):
        manifests = sorted((self.root / 'backups').glob('*/manifest.json'))
        if not manifests:
            return None
        try:
            manifest = json.loads(manifests[-1].read_text(encoding='utf-8'))
            recorded = {Path(item['source']).resolve() for item in manifest['databases']}
            return dict(createdAt=manifest['createdAt'], complete=manifest['complete'],
                        expected=len(self.paths), included=len(recorded & set(self.paths)),
                        missing=[path.name for path in self.paths if path not in recorded])
        except (ValueError, KeyError, OSError):
            return dict(complete=False, missing=[path.name for path in self.paths], createdAt=None,
                        expected=len(self.paths), included=0)

    def restore_drill(self):
        """Restore only generated copies and reconcile their paper accounts."""
        with self.lock:
            self.root.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix='restore-drill-', dir=self.root) as directory:
                folder = Path(directory).resolve()
                if folder.parent != self.root:
                    raise ValueError('Restore drill directory is outside private storage.')
                saved = snapshot(self.paths, folder / 'backup')
                restored = restore(folder / 'backup', folder / 'restored')
                accounts = 0
                if self.paper_engine:
                    from paper import PaperEngine
                    index = next(i for i, item in enumerate(saved['databases'])
                                 if Path(item['source']).resolve() == self.paper_engine.path.resolve())
                    engine = PaperEngine(folder / 'restored' / restored['databases'][index]['file'])
                    for account in engine.status()['accounts']:
                        if not engine.reconcile(account['id'])['matches']:
                            raise ValueError('Restored paper ledger mismatch.')
                        accounts += 1
                result = dict(complete=True, checkedAt=dt.datetime.now(dt.timezone.utc).isoformat(),
                              databases=len(restored['databases']), reconciledAccounts=accounts,
                              consistency='Individually consistent ledgers; cross-ledger atomicity is unverified.')
            (self.root / 'last-restore-drill.json').write_text(json.dumps(result), encoding='utf-8')
            return result

    def status(self):
        databases = []
        for path in self.paths:
            try:
                evidence = verify(path)
                databases.append(dict(name=path.name, sizeBytes=path.stat().st_size, **evidence))
            except Exception as exc:
                databases.append(dict(name=path.name, integrity='unavailable', errorType=type(exc).__name__))
        backups = sorted((self.root / 'backups').glob('*/manifest.json'))
        latest = None
        if backups:
            try:
                manifest = json.loads(backups[-1].read_text(encoding='utf-8'))
                latest = dict(createdAt=manifest['createdAt'], complete=manifest['complete'], count=len(manifest['databases']))
            except (ValueError, KeyError, OSError):
                latest = dict(complete=False)
        drill_path = self.root / 'last-restore-drill.json'
        try:
            drill = json.loads(drill_path.read_text(encoding='utf-8')) if drill_path.exists() else None
        except (ValueError, OSError):
            drill = dict(complete=False)
        return dict(databases=databases, latestBackup=latest, backupCoverage=self.coverage(), lastRestoreDrill=drill,
                    consistency='Each database snapshot is consistent within its own ledger transaction.')
