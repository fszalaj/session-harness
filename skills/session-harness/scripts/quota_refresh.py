"""Serialize backend observations across processes without holding the accounting transaction."""
from contextlib import contextmanager
import hashlib
import os
import sqlite3


@contextmanager
def serialized(ledger, service, timeout=30):
    name = hashlib.sha256(service.encode()).hexdigest()
    path = ledger.path.with_name(ledger.path.name + '.refresh-' + name + '.sqlite3')
    if os.name == 'nt':
        from windows_security import prepare_private_file
        prepare_private_file(path)
    else:
        fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        os.close(fd)
        os.chmod(path, 0o600)
    db = sqlite3.connect(path, timeout=timeout)
    try:
        # SQLite releases the lock on process exit; no stale session lease is removed.
        db.execute('BEGIN IMMEDIATE')
        yield
        db.commit()
    finally:
        db.close()
