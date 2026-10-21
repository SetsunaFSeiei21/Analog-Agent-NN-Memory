from __future__ import annotations

import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing

import pytest

from src.sample_optimize import sqlite_access
from src.sample_optimize.advanced.context import record_invocation
from src.sample_optimize.history_store import SamplingHistoryStore


def history(tmp_path):
    store = SamplingHistoryStore(tmp_path, "demo", "single_ended_opamp", ["W"], ["gain"], journal_mode="DELETE")
    run = store.create_run(160, 32, {"random": 160}, {})
    return store, run


def test_32_workers_keep_spice_parallel_and_all_invocations_durable(tmp_path):
    store, run = history(tmp_path)
    # A lock spanning operation() would deadlock at this barrier.
    barrier = threading.Barrier(32, timeout=10)
    def worker(index):
        for iteration in range(5):
            result = record_invocation(store.database_path, run, str(index), "design", "gain",
                                       lambda: (barrier.wait(), iteration)[1])
            assert result == iteration
    with ThreadPoolExecutor(max_workers=32) as pool:
        list(pool.map(worker, range(32)))
    with store._connect() as con:
        assert con.execute("SELECT status,COUNT(*) FROM spice_invocations GROUP BY status").fetchall()[0][:] == ("finished", 160)
        assert con.execute("PRAGMA journal_mode").fetchone()[0] == "delete"


def test_completion_retries_external_writer_without_relaunching_spice(tmp_path, monkeypatch):
    store, run = history(tmp_path)
    write = sqlite_access.write_transaction
    monkeypatch.setattr("src.sample_optimize.advanced.context.write_transaction",
                        lambda db, op: write(db, op, timeout=2, attempt_timeout=.01))
    locked = threading.Event()
    calls = []
    def holder():
        with closing(sqlite3.connect(store.database_path)) as con, con:
            con.execute("BEGIN IMMEDIATE")
            locked.set()
            time.sleep(.15)
    def launch():
        calls.append(1)
        thread.start()
        assert locked.wait(2)
        return "SPICE result"
    thread = threading.Thread(target=holder)
    try:
        assert record_invocation(store.database_path, run, "key", "design", "op", launch) == "SPICE result"
    finally:
        thread.join(timeout=3)
    assert calls == [1]
    with store._connect() as con:
        assert con.execute("SELECT status FROM spice_invocations").fetchone()[0] == "finished"


def test_commit_busy_rolls_back_before_retry(tmp_path):
    database = tmp_path / "commit.sqlite3"
    with closing(sqlite3.connect(database)) as con, con:
        con.execute("CREATE TABLE counter (value INTEGER)")
        con.execute("INSERT INTO counter VALUES (0)")
    body_ran = threading.Event()
    attempts = []
    def transaction(con):
        attempts.append(1)
        con.execute("UPDATE counter SET value=value+1")
        body_ran.set()
    # A reader permits BEGIN IMMEDIATE and the update, but blocks commit.
    with closing(sqlite3.connect(database)) as reader:
        reader.execute("BEGIN")
        reader.execute("SELECT * FROM counter").fetchall()
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(sqlite_access.write_transaction, database, transaction,
                                 timeout=2, attempt_timeout=.01)
            try:
                assert body_ran.wait(1)
                time.sleep(.15)
            finally:
                reader.rollback()
            future.result(timeout=3)
    assert len(attempts) > 1
    with closing(sqlite3.connect(database)) as con:
        assert con.execute("SELECT value FROM counter").fetchone()[0] == 1


def test_busy_timeout_is_bounded_and_other_errors_are_not_retried(tmp_path):
    store, _ = history(tmp_path)
    with closing(sqlite3.connect(store.database_path)) as blocker:
        blocker.execute("BEGIN IMMEDIATE")
        started = time.monotonic()
        with pytest.raises(sqlite3.OperationalError, match="locked"):
            sqlite_access.write_transaction(store.database_path, lambda con: None,
                                            timeout=.1, attempt_timeout=.01)
        assert time.monotonic() - started < 1
        blocker.rollback()
    calls = []
    def invalid(con):
        calls.append(1)
        con.execute("INSERT INTO missing_table VALUES (1)")
    with pytest.raises(sqlite3.OperationalError, match="no such table"):
        sqlite_access.write_transaction(store.database_path, invalid)
    assert calls == [1]


def test_failure_accounting_keeps_original_exception(tmp_path, monkeypatch):
    store, run = history(tmp_path)
    write = sqlite_access.write_transaction
    count = []
    def broken_update(db, op):
        count.append(1)
        if len(count) == 2:
            raise sqlite3.OperationalError("disk I/O error")
        return write(db, op)
    monkeypatch.setattr("src.sample_optimize.advanced.context.write_transaction", broken_update)
    def fail():
        raise TimeoutError("SPICE timed out")
    with pytest.raises(TimeoutError, match="SPICE timed out"):
        record_invocation(store.database_path, run, "key", "design", "op", fail)
    with store._connect() as con:
        assert con.execute("SELECT status FROM spice_invocations").fetchone()[0] == "reserved"
