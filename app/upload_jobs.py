"""PDF 업로드/청킹 작업의 상태를 추적하는 메모리 기반 job store.

서버 재시작 시 휘발됨 — 청킹 결과 자체는 파일로 떨어지므로 영속성 불필요.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from threading import Lock
from typing import Any

JobStatusLiteral = str  # "pending" | "running" | "completed" | "failed"


@dataclass
class JobState:
    job_id: str
    status: JobStatusLiteral = "pending"
    progress: int = 0
    step: str = ""
    message: str = ""
    result: dict[str, Any] | None = None
    error: str | None = None


class JobStore:
    def __init__(self) -> None:
        self._jobs: dict[str, JobState] = {}
        self._lock = Lock()

    def create(self, job_id: str) -> JobState:
        with self._lock:
            state = JobState(job_id=job_id)
            self._jobs[job_id] = state
            return state

    def update(self, job_id: str, **kwargs: Any) -> None:
        with self._lock:
            state = self._jobs.get(job_id)
            if state is None:
                return
            for k, v in kwargs.items():
                if hasattr(state, k):
                    setattr(state, k, v)

    def get(self, job_id: str) -> JobState | None:
        with self._lock:
            return self._jobs.get(job_id)

    def to_dict(self, job_id: str) -> dict[str, Any] | None:
        state = self.get(job_id)
        return asdict(state) if state else None


job_store = JobStore()
