"""Local research provenance; records every viewed result, never approves trading."""
import datetime as dt
from contextlib import closing
import json
from pathlib import Path
import sqlite3


class ExperimentRegistry:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute('CREATE TABLE IF NOT EXISTS experiments (id INTEGER PRIMARY KEY, created TEXT NOT NULL, dataset TEXT NOT NULL, holdout TEXT NOT NULL, report TEXT NOT NULL)')

    def record(self, report):
        """Store results/settings/fingerprints, not raw licensed candle data."""
        with closing(sqlite3.connect(self.path, timeout=10)) as db, db:
            db.execute('BEGIN IMMEDIATE')
            seen = db.execute('SELECT COUNT(*) FROM experiments WHERE holdout=?', (report['holdoutFingerprint'],)).fetchone()[0]
            record = db.execute('INSERT INTO experiments(created,dataset,holdout,report) VALUES(?,?,?,?)',
                                (dt.datetime.now(dt.timezone.utc).isoformat(), report['datasetFingerprint'],
                                 report['holdoutFingerprint'], json.dumps(report, allow_nan=False)))
            return dict(runId=record.lastrowid, previousViews=seen, holdoutViewedBefore=seen > 0,
                        independentEvidence=False, promotionAllowed=False,
                        reason='Historical result retained, including losses. Repeated viewing is tracked; point-in-time provenance and untouched validation are not certified.')
