"""One local worker or RQ/Valkey dispatch with persistent compare-and-set claims."""

from __future__ import annotations

import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from legacylift.modernization.generation import QuotaExceeded
from legacylift.modernization.pipeline import finalize, migrate
from legacylift.modernization.study import prepare_study

from .store import Store


class Cancelled(Exception):
    pass


def execute_job(home: str, job_id: str):
    store = Store(Path(home))
    owner = uuid.uuid4().hex
    if not store.claim(job_id, owner):
        return  # Duplicate queue delivery is harmless.

    def checkpoint(message, progress=0):
        if not store.checkpoint(job_id, owner, message, progress):
            raise Cancelled()

    try:
        job = store.get(job_id)
        checkpoint("Preparing controller", 0)
        if job["kind"] == "prepare":
            result = prepare_study(store.home, checkpoint)
        elif job["kind"] == "migrate":
            parameters = dict(job["parameters"])
            run_id = parameters.pop("run_id", None) or job_id
            result = migrate(store.home, **parameters, checkpoint=checkpoint, run_id=run_id)
        elif job["kind"] == "finalize":
            result = finalize(store.home, **job["parameters"], checkpoint=checkpoint)
        else:
            raise ValueError("unsupported job kind")
        job_state = {"provider_paused": "quota_paused", "provider_failed": "failed"}.get(
            result.get("status"), "succeeded"
        )
        store.finish(
            job_id,
            owner,
            job_state,
            result=result,
            message=(
                result.get("failure", {}).get("category", "")
                if job_state in {"failed", "quota_paused"}
                else "Completed; inspect the compatibility verdict in the result"
            ),
        )
    except Cancelled:
        store.finish(job_id, owner, "cancelled", message="Cancelled; owned runtime cleaned up")
    except QuotaExceeded as error:
        store.finish(job_id, owner, "quota_paused", message=str(error))
    except Exception as error:
        # Provider errors deliberately omit raw responses; no environment is logged.
        store.finish(
            job_id, owner, "failed", message=f"{type(error).__name__}: {str(error)[:1500]}"
        )
    finally:
        store.engine.dispose()


class Dispatcher:
    def __init__(self, store: Store):
        self.store = store
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="legacylift")

    def submit(self, job_id: str):
        redis_url = os.environ.get("LEGACYLIFT_REDIS_URL")
        if redis_url:
            from redis import Redis
            from rq import Queue

            Queue("legacylift", connection=Redis.from_url(redis_url)).enqueue(
                execute_job,
                str(self.store.home),
                job_id,
                job_timeout=3600,
                result_ttl=86400,
                failure_ttl=86400,
            )
        else:
            self.executor.submit(execute_job, str(self.store.home), job_id)

    def close(self):
        self.executor.shutdown(wait=False, cancel_futures=False)
