"""Background job runner for async batch endpoints (fusion/drift/gold republish).

The HTTP handler pre-creates a LabelerRun, returns 202 + run_id, and schedules the
heavy work here. The job runs in its own DB session (on a dedicated pool) so it is
independent of the already-completed request, and persists the result/error for
polling via /runs/{id}. A bounded semaphore caps concurrent batch jobs so they can't
saturate the worker threadpool.
"""
from __future__ import annotations

import logging
import threading
from typing import Callable

from app.config import get_settings
from app.repositories.runs import RunRepository

logger = logging.getLogger("app.jobs")

# work(session, run_id) -> JSON-able result dict.
JobWork = Callable[[object, str], dict]

# Hard cap on concurrent batch jobs (bounds threadpool/pool pressure).
_BATCH_SLOTS = threading.BoundedSemaphore(get_settings().batch_max_concurrency)

_MAX_ERROR_LEN = 2000


def _record_failure(session_factory, run_id: str, message: str) -> None:
    """Mark a run FAILED on a FRESH session (the job's session may be in a broken
    transaction state after the exception)."""
    session = session_factory()
    try:
        if RunRepository(session).fail(run_id, message) is None:
            logger.warning("run %s not found while recording failure", run_id)
        session.commit()
    except Exception:  # never let failure-recording raise out of the background task
        logger.exception("could not mark run %s FAILED", run_id)
        session.rollback()
    finally:
        session.close()


def execute_run(run_id: str, work: JobWork, session_factory) -> None:
    with _BATCH_SLOTS:
        session = session_factory()
        try:
            result = work(session, run_id)
            if RunRepository(session).set_result(run_id, result) is None:
                logger.warning("run %s not found while storing result", run_id)
            session.commit()
        except Exception as exc:  # the response is already sent; record failure on the run
            session.rollback()
            logger.exception("batch run %s failed", run_id)
            _record_failure(session_factory, run_id, str(exc)[:_MAX_ERROR_LEN])
        finally:
            session.close()
