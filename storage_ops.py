"""Consistent private SQLite snapshots and verified restoration to new paths."""
from contextlib import closing
import datetime as dt
import hashlib
import json
from pathlib import Path
import sqlite3


def database_path(path):
    resolved = Path(path).resolve(strict=True)
    if not resolved.is_file():
        raise ValueError('Database must be a file.')
    return resolved


def verify(path):
    source = database_path(path)
    with closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)) as db:
        messages = [row[0] for row in db.execute('PRAGMA integrity_check')]
        if messages != ['ok']:
            raise ValueError('Database integrity check failed.')
        tables = [row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        # Names come from sqlite_master of a read-only file and are identifier-quoted.
        counts = {name: db.execute('SELECT COUNT(*) FROM "' + name.replace('"', '""') + '"').fetchone()[0] for name in tables}  # nosec B608
        version = db.execute('PRAGMA user_version').fetchone()[0]
    return dict(integrity='ok', tables=counts, schemaVersion=version)


def snapshot(paths, destination):
    """Each ledger is transactionally consistent; cross-ledger atomicity is not implied."""
    folder = Path(destination).resolve()
    folder.mkdir(parents=True, exist_ok=False)
    manifest = dict(createdAt=dt.datetime.now(dt.timezone.utc).isoformat(), databases=[], complete=False)
    manifest_path = folder / 'manifest.json'
    try:
        for index, path in enumerate(paths):
            source = database_path(path)
            target = folder / (str(index) + '-' + source.name)
            with closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)) as reader:
                with closing(sqlite3.connect(target)) as writer:
                    reader.backup(writer)
            evidence = verify(target)
            manifest['databases'].append(dict(file=target.name, source=str(source), sha256=hashlib.sha256(target.read_bytes()).hexdigest(), **evidence))
        manifest['complete'] = True
    finally:
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    return manifest


def restore(snapshot_folder, destination):
    """Never overwrite an existing ledger or an existing destination directory."""
    source = Path(snapshot_folder).resolve(strict=True)
    manifest = json.loads((source / 'manifest.json').read_text(encoding='utf-8'))
    if not manifest.get('complete'):
        raise ValueError('Snapshot was not completed.')
    verified = []
    for record in manifest['databases']:
        path = (source / record['file']).resolve(strict=True)
        if path.parent != source or hashlib.sha256(path.read_bytes()).hexdigest() != record['sha256']:
            raise ValueError('Snapshot identity or checksum mismatch.')
        if verify(path)['tables'] != record['tables']:
            raise ValueError('Snapshot table counts changed.')
        verified.append(path)
    return snapshot(verified, destination)
