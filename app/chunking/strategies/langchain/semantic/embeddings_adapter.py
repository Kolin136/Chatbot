"""Pydantic AI Embedder → LangChain Embeddings 인터페이스 어댑터.

`app/config.py::embedder` (pydantic_ai)를 LangChain SemanticChunker가 사용할 수 있는
`langchain_core.embeddings.Embeddings` 인터페이스로 wrap.

⚠️ event loop 주의:
SemanticChunker.split_text는 sync 함수라 `asyncio.to_thread` 로 별도 스레드(T)에서 실행됨.
스레드 T 안에서 `Embeddings.embed_documents` (sync) 가 호출되는데,
- 우리 embedder의 sync 래퍼는 새 event loop를 만들지만
- 그 내부 httpx client는 **메인 loop A**에 바인딩돼있어 충돌 발생
  (RuntimeError: bound to a different event loop)

해결: sync 메서드에서 메인 loop A에 코루틴을 던지고 결과를 받는 패턴 사용
(`asyncio.run_coroutine_threadsafe`).
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import TYPE_CHECKING

from langchain_core.embeddings import Embeddings

from app.config import embedder as default_embedder

if TYPE_CHECKING:
    from pydantic_ai import Embedder

logger = logging.getLogger(__name__)

# 임베딩 배치 크기. LM Studio는 자체 한도가 없지만 메모리 안정성 차원에서 유지.
# 분당 토큰/요청 한도(TPM/RPM)도 고려해 너무 크지 않게 잡음.
EMBED_BATCH_SIZE = int(os.environ.get("SEMANTIC_EMBED_BATCH_SIZE", "32"))


def _run_in_main_loop(coro):
    """현재 스레드의 컨텍스트에 맞춰 코루틴 실행 결과를 동기로 반환.

    - 메인 loop이 다른 스레드에서 돌고 있으면 → run_coroutine_threadsafe (가장 흔한 경우)
    - 현재 스레드에 실행 중인 loop이 있으면 → 그 안에서 await로 풀어야 함 (호출자 책임)
    - 어디에도 실행 loop이 없으면 → asyncio.run 으로 새로 실행
    """
    # 현재 스레드에 실행 중인 loop 이 있는지 확인.
    # 있다면 sync 메서드가 async 컨텍스트 안에서 직접 호출된 것 → 잘못된 사용.
    # (이전 구현은 raise 를 같은 블록의 except RuntimeError 가 삼켜 가드가 죽어 있었다)
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        pass  # 실행 중 loop 없음 — 정상 경로(별도 스레드에서 호출됨)
    else:
        raise RuntimeError(
            "sync embed_documents/embed_query는 실행 중인 event loop 안에서 직접 호출하면 안 됨. "
            "async 메서드(aembed_documents/aembed_query)를 사용하거나 별도 스레드에서 호출하세요."
        )

    # 메인 loop이 동작 중이면 거기로 던지기
    main_loop = _get_main_loop()
    if main_loop is not None and main_loop.is_running():
        future = asyncio.run_coroutine_threadsafe(coro, main_loop)
        return future.result()
    # 없으면 새 loop 으로 실행
    return asyncio.run(coro)


_main_loop_ref: "asyncio.AbstractEventLoop | None" = None


def _get_main_loop() -> "asyncio.AbstractEventLoop | None":
    """모듈 로드 후 한 번 캐치된 메인 loop 반환."""
    return _main_loop_ref


def _set_main_loop(loop: "asyncio.AbstractEventLoop") -> None:
    """async 컨텍스트에서 메인 loop을 등록 (어댑터 인스턴스 생성 시 자동 호출)."""
    global _main_loop_ref
    _main_loop_ref = loop


class PydanticAIEmbeddingsAdapter(Embeddings):
    """우리 pydantic_ai Embedder를 LangChain Embeddings로 노출."""

    def __init__(self, embedder: "Embedder | None" = None) -> None:
        self._embedder = embedder or default_embedder
        # 인스턴스 생성 시점의 실행 loop을 메인 loop으로 캐치
        try:
            _set_main_loop(asyncio.get_running_loop())
        except RuntimeError:
            # 실행 loop 없는 컨텍스트에서 만들어진 경우 — sync 메서드에서 새 loop으로 처리됨
            pass

    # ─── sync 인터페이스 (스레드에서 호출됨) ─────────────────────────
    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        # aembed_documents를 한 코루틴으로 묶어 메인 loop에서 실행 →
        # 내부적으로 배치 분할(EMBED_BATCH_SIZE)이 적용됨.
        return _run_in_main_loop(self.aembed_documents(texts))

    def embed_query(self, text: str) -> list[float]:
        result = _run_in_main_loop(self._embedder.embed_query(text))
        return list(result.embeddings[0])

    # ─── async 인터페이스 ────────────────────────────────────────────
    async def aembed_documents(self, texts: list[str]) -> list[list[float]]:
        # EMBED_BATCH_SIZE 단위로 분할 호출 (대량 문장 한 번에 보내지 않도록).
        out: list[list[float]] = []
        total = len(texts)
        if total == 0:
            return out
        n_batches = (total + EMBED_BATCH_SIZE - 1) // EMBED_BATCH_SIZE
        for batch_idx, start in enumerate(range(0, total, EMBED_BATCH_SIZE), start=1):
            batch = texts[start : start + EMBED_BATCH_SIZE]
            logger.info(
                "SemanticChunker embedding batch %d/%d (size=%d)",
                batch_idx, n_batches, len(batch),
            )
            result = await self._embedder.embed_documents(batch)
            out.extend(list(emb) for emb in result.embeddings)
        return out

    async def aembed_query(self, text: str) -> list[float]:
        result = await self._embedder.embed_query(text)
        return list(result.embeddings[0])
