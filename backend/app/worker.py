"""Background worker thread: runs the daily scheduler check and drains the durable job queue.

Jobs live in the database, so the queue survives restarts. For multi-instance deployments, run
the worker in one process only (WORKER_ENABLED=false on the others) or move to an external queue."""
import logging
import threading

from .config import get_settings
from .db import SessionLocal
from .orchestrator import recover_stale_jobs, worker_tick

log = logging.getLogger("psa.worker")


class Worker:
    def __init__(self):
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self):
        with SessionLocal() as db:
            n = recover_stale_jobs(db)
            if n:
                log.info("Recovered %s interrupted job(s)", n)
        self._thread = threading.Thread(target=self._loop, name="psa-worker", daemon=True)
        self._thread.start()

    def poke(self):
        """Run a tick now instead of waiting for the poll interval (after a user action)."""
        self._wake.set()

    def stop(self):
        self._stop.set()
        self._wake.set()
        if self._thread:
            self._thread.join(timeout=10)

    def _loop(self):
        poll = get_settings().worker_poll_seconds
        while not self._stop.is_set():
            try:
                with SessionLocal() as db:
                    worker_tick(db)
            except Exception:  # noqa: BLE001 — the loop must survive any single failure
                log.exception("Worker tick failed")
            self._wake.wait(timeout=poll)
            self._wake.clear()


worker = Worker()
