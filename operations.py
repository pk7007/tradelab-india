"""Local storage health and consistent per-ledger backup operations."""
import datetime as dt
import json
from pathlib import Path
import threading

from storage_ops import snapshot, verify


class Operations:
    def __init__(self, paths, root):
        self.paths = list(dict.fromkeys(Path(path).resolve() for path in paths))
        self.root = Path(root).resolve()
        self.lock = threading.Lock()

    def backup(self):
        with self.lock:
            stamp = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
            return snapshot(self.paths, self.root / 'backups' / stamp)

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
        return dict(databases=databases, latestBackup=latest,
                    consistency='Each database snapshot is consistent within its own ledger transaction.')
