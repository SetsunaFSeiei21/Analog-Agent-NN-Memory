"""Short, serialized SQLite writes; expensive SPICE calls stay outside the lock."""
from __future__ import annotations

import logging
import sqlite3
import threading
import time
from contextlib import closing
from pathlib import Path


_locks_guard = threading.Lock()
_locks = {}
_logger = logging.getLogger(__name__)


def database_lock(database):
    """Share a lock between all connections to one file in this process.

    The dataset's existing flock excludes a second sampling process. SQLite
    still arbitrates external connections (for example an export process).
    """
    key = str(Path(database).resolve())
    with _locks_guard:
        return _locks.setdefault(key, threading.RLock())


def _busy(error):
    code = getattr(error, "sqlite_errorcode", None)
    return code is not None and (code & 0xff) in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED)


def write_transaction(database, operation, *, timeout=300.0, attempt_timeout=5.0):
    """Retry a complete SQL-only transaction, including commit, after rollback.

    `operation` must not launch SPICE or perform other nontransactional work.
    Connections are always closed, including setup and commit failures. The
    journal mode is deliberately left alone for shared-storage compatibility.
    """
    if timeout <= 0 or attempt_timeout <= 0:
        raise ValueError("SQLite timeouts must be positive")
    with database_lock(database):
        deadline = time.monotonic() + timeout
        attempts = 0
        while True:
            remaining = max(0.001, deadline - time.monotonic())
            try:
                with closing(sqlite3.connect(database, timeout=min(attempt_timeout, remaining))) as con:
                    con.execute("PRAGMA foreign_keys = ON")
                    con.execute("PRAGMA synchronous = FULL")
                    with con:
                        con.execute("BEGIN IMMEDIATE")
                        result = operation(con)
                    return result
            except sqlite3.OperationalError as exc:
                if not _busy(exc) or time.monotonic() >= deadline:
                    raise
                attempts += 1
                if attempts == 1:
                    _logger.warning("SQLite busy; retrying short transaction: %s", database)
                # Do not touch the samplers' random generators.
                time.sleep(min(0.05 * 2 ** min(attempts - 1, 4),
                               max(0.0, deadline - time.monotonic())))
