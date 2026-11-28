"""GAP-066: a transaction that cannot start does not keep the store's lock.

Found by a full test run that stopped making progress: an engine closed a second time (after a failed release
activation) tried to give up its writer lease on a store that was already closed. The transaction helper had
taken the store's lock, failed to begin, and never released it; the next thread to touch that store waited
forever. It showed only now and then because thread identifiers are usually reused, which made the lock look
re-entrant to the next request thread.

  L1 a failed BEGIN releases the lock: another thread can use (or close) the store afterwards
  L2 closing an engine twice, from two threads, returns both times
"""

import sqlite3
import threading
import unittest

from autology.store import Store

from . import test_ingest


def in_thread(fn, timeout=5.0):
    """Run ``fn`` in a fresh thread; ``(finished, error)``."""
    box = {}

    def work():
        try:
            fn()
        except Exception as exc:  # reported to the caller
            box["error"] = exc
    t = threading.Thread(target=work, daemon=True)
    t.start()
    t.join(timeout)
    return not t.is_alive(), box.get("error")


class StoreLockTests(unittest.TestCase):
    def test_a_transaction_that_cannot_start_releases_the_lock(self):  # L1
        store = Store(":memory:")
        keep = threading.Event()
        started = threading.Event()

        def fail_and_stay_alive():  # the failing thread stays alive, so its identifier cannot be reused
            store.close()
            try:
                store.release_lease("nobody")
            except sqlite3.ProgrammingError:
                pass
            started.set()
            keep.wait(10)
        holder = threading.Thread(target=fail_and_stay_alive, daemon=True)
        holder.start()
        self.assertTrue(started.wait(5))
        finished, error = in_thread(lambda: store.close())
        keep.set()
        holder.join(5)
        self.assertTrue(finished, "another thread waits forever for the store's lock")
        self.assertIsNone(error)
        finished, error = in_thread(lambda: store.release_lease("nobody"))  # still fails, still does not hang
        self.assertTrue(finished)
        self.assertIsInstance(error, sqlite3.ProgrammingError)

    def test_an_engine_closed_twice_from_two_threads_returns(self):  # L2
        svc = test_ingest.service()
        keep, started = threading.Event(), threading.Event()

        def first():
            svc.close()
            svc.close()  # the second close cannot release the lease: logged, never blocking
            started.set()
            keep.wait(10)
        holder = threading.Thread(target=first, daemon=True)
        with self.assertLogs("autology", level="WARNING"):
            holder.start()
            self.assertTrue(started.wait(5))
        with self.assertLogs("autology", level="WARNING"):
            finished, error = in_thread(svc.close)
        keep.set()
        holder.join(5)
        self.assertTrue(finished, "a third close from another thread waits forever")
        self.assertIsNone(error)


if __name__ == "__main__":
    unittest.main()
