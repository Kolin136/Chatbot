"""임베딩 작업 상태 store — 메모리 기반. (upload_jobs.py 와 동일 패턴.)

서버 재시작 시 휘발됨. ChromaDB 자체엔 영속 저장되므로 결과 손실 없음.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from threading import Lock
from typing import Any


@dataclass
class EmbedJobState:
    embed_job_id: str
    status: str = "pending"  # pending | running | completed | failed
    progress: int = 0
    step: str = ""
    message: str = ""
    result: dict[str, Any] | None = None
    error: str | None = None


class EmbedJobStore:
    def __init__(self) -> None:
        self._jobs: dict[str, EmbedJobState] = {}
        self._lock = Lock()

    def create(self, embed_job_id: str) -> EmbedJobState:
        with self._lock:
            state = EmbedJobState(embed_job_id=embed_job_id)
            self._jobs[embed_job_id] = state
            return state

    def update(self, embed_job_id: str, **kwargs: Any) -> None:
        with self._lock:
            state = self._jobs.get(embed_job_id)
            if state is None:
                return
            for k, v in kwargs.items():
                if hasattr(state, k):
                    setattr(state, k, v)

    def get(self, embed_job_id: str) -> EmbedJobState | None:
        with self._lock:
            return self._jobs.get(embed_job_id)

    def to_dict(self, embed_job_id: str) -> dict[str, Any] | None:
        state = self.get(embed_job_id)
        return asdict(state) if state else None


embed_job_store = EmbedJobStore()
