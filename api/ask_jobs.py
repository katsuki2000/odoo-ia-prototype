"""In-memory store of asynchronous ask jobs (single process)."""

import logging
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from fastapi import HTTPException

from api.public_errors import public_error_details
from api.schemas import AskResponseV1
from config.settings import ASK_JOB_MAX_PENDING, ASK_JOB_TTL_SECONDS, ASK_JOB_WORKERS

logger = logging.getLogger(__name__)


class DuplicateJobError(Exception):
    pass


class JobCapacityError(Exception):
    pass


@dataclass
class AskJob:
    owner_uid: int
    question: str
    started_at: float = field(default_factory=time.monotonic)
    finished_at: float | None = None
    result: AskResponseV1 | None = None
    error_status: int | None = None
    error_detail: str | None = None

    @property
    def status(self) -> str:
        if self.finished_at is None:
            return 'pending'
        return 'error' if self.error_status else 'done'

    @property
    def elapsed_ms(self) -> int:
        return int(((self.finished_at or time.monotonic()) - self.started_at) * 1000)


class AskJobStore:
    def __init__(self, workers: int, max_pending: int, ttl_seconds: float):
        self._jobs: dict[str, AskJob] = {}
        self._lock = threading.Lock()
        self._executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix='ask-job')
        self._max_pending = max_pending
        self._ttl_seconds = ttl_seconds

    def submit(self, job_id: str, owner_uid: int, question: str, work: Callable[[], AskResponseV1]) -> None:
        with self._lock:
            self._drop_expired()
            if job_id in self._jobs:
                raise DuplicateJobError(job_id)
            if sum(job.status == 'pending' for job in self._jobs.values()) >= self._max_pending:
                raise JobCapacityError()
            job = self._jobs[job_id] = AskJob(owner_uid, question)
        self._executor.submit(self._run, job, work)

    def get(self, job_id: str, owner_uid: int) -> AskJob | None:
        """The job, or None when unknown, expired or owned by someone else."""
        with self._lock:
            self._drop_expired()
            job = self._jobs.get(job_id)
        return job if job is not None and job.owner_uid == owner_uid else None

    def _run(self, job: AskJob, work: Callable[[], AskResponseV1]) -> None:
        result, status, detail = None, None, None
        try:
            result = work()
        except HTTPException as error:
            status, detail = error.status_code, str(error.detail)
        except Exception as error:
            logger.exception('Ask job failed.')
            status, detail = public_error_details(error)
        with self._lock:
            job.result, job.error_status, job.error_detail = result, status, detail
            job.finished_at = time.monotonic()

    def _drop_expired(self) -> None:
        limit = time.monotonic() - self._ttl_seconds
        for job_id in [key for key, job in self._jobs.items() if job.started_at < limit]:
            del self._jobs[job_id]


ask_jobs = AskJobStore(ASK_JOB_WORKERS, ASK_JOB_MAX_PENDING, ASK_JOB_TTL_SECONDS)
