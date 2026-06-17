"""RAGAS 평가 작업의 상태를 추적하는 메모리 기반 job store.

upload_jobs.JobStore와 동일 구조. 서버 재시작 시 휘발 — 결과는 evaluation/results/에 파일로 저장됨.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from threading import Lock
from typing import Any


@dataclass
class EvaluationJobState:
    eval_job_id: str
    status: str = "pending"  # pending | running | completed | failed
    progress: int = 0
    step: str = ""
    message: str = ""
    result: dict[str, Any] | None = None
    error: str | None = None


class EvaluationJobStore:
    def __init__(self) -> None:
        self._jobs: dict[str, EvaluationJobState] = {}
        self._lock = Lock()

    def create(self, eval_job_id: str) -> EvaluationJobState:
        with self._lock:
            state = EvaluationJobState(eval_job_id=eval_job_id)
            self._jobs[eval_job_id] = state
            return state

    def update(self, eval_job_id: str, **kwargs: Any) -> None:
        with self._lock:
            state = self._jobs.get(eval_job_id)
            if state is None:
                return
            for k, v in kwargs.items():
                if hasattr(state, k):
                    setattr(state, k, v)

    def get(self, eval_job_id: str) -> EvaluationJobState | None:
        with self._lock:
            return self._jobs.get(eval_job_id)

    def to_dict(self, eval_job_id: str) -> dict[str, Any] | None:
        state = self.get(eval_job_id)
        return asdict(state) if state else None


eval_job_store = EvaluationJobStore()
