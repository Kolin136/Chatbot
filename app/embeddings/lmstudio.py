"""LM Studio(OpenAI 호환 `/v1/embeddings`) 임베딩 클라이언트.

호출처(`app/rag.py`, `app/routers/embed.py`,
`app/chunking/strategies/langchain/semantic/embeddings_adapter.py`,
`scripts/index_docs.py`)가 기대하는 인터페이스:

    result = await embedder.embed_documents(texts: list[str])
    result.embeddings          # Iterable[list[float]]

    result = await embedder.embed_query(text: str)
    result.embeddings[0]       # list[float]

이 인터페이스만 만족하면 호출처 코드는 무수정으로 동작한다.

설계 결정:
- httpx.AsyncClient 사용 (FastAPI / pydantic_ai 와 동일 스택, event loop 충돌 없음).
- 인증 헤더 없음 — LM Studio는 토큰 검증을 안 함 (운영 결정).
- 일시 connect/read 에러는 지수 백오프로 자동 재시도. 4xx(잘못된 모델 ID 등)는 즉시 raise.
- 호스트/포트/모델 ID는 인자로만 받음 — 절대 코드에 박지 않음 (config.py가 .env에서 주입).
"""
from __future__ import annotations

import asyncio
import logging
import socket
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

EMBEDDINGS_PATH = "/embeddings"
"""base_url 뒤에 붙는 OpenAI 호환 경로."""

DEFAULT_TIMEOUT_SEC = 60.0
DEFAULT_MAX_RETRIES = 4
"""일시 네트워크 에러 재시도 횟수. 4회 = 1+2+4+8s = 15s 동안 회복 기회."""

DEFAULT_BACKOFF_BASE_SEC = 1.0


@dataclass
class EmbeddingResult:
    """호출처가 의존하는 `.embeddings` 속성을 노출하는 결과 wrapper."""

    embeddings: list[list[float]]


class LMStudioEmbedder:
    """OpenAI 호환 임베딩 서버 클라이언트.

    base_url 끝의 `/v1` 까지 호출자가 포함해서 넘긴다. 내부에서 `/embeddings`만 붙임.
    예: base_url=`http://172.30.1.32:1369/v1` → 실제 호출 `http://172.30.1.32:1369/v1/embeddings`.
    """

    def __init__(
        self,
        base_url: str,
        model: str,
        *,
        timeout: float = DEFAULT_TIMEOUT_SEC,
        max_retries: int = DEFAULT_MAX_RETRIES,
        backoff_base_sec: float = DEFAULT_BACKOFF_BASE_SEC,
    ) -> None:
        if not base_url:
            raise ValueError("base_url is required")
        if not model:
            raise ValueError("model is required")
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout = timeout
        self._max_retries = max_retries
        self._backoff_base = backoff_base_sec
        # httpx 클라이언트는 모듈 레벨에 두지 않는다 — 호출마다 새로 생성해 pool/state 격리.
        # (uvicorn --reload 워치독 자식 + asyncio.to_thread + run_coroutine_threadsafe 의 복잡한
        #  dispatch에서 모듈 레벨 AsyncClient가 broken pool state에 빠져 1ms 즉시 ConnectError나는 현상 회피)

    async def embed_documents(self, texts: list[str]) -> EmbeddingResult:
        """텍스트 배치 → 벡터 배치. 입력 순서대로 정렬해서 반환."""
        if not texts:
            return EmbeddingResult(embeddings=[])
        payload: dict[str, Any] = {"model": self._model, "input": texts}
        data = await self._post_embeddings(payload)
        return EmbeddingResult(embeddings=_extract_embeddings_sorted(data))

    async def embed_query(self, text: str) -> EmbeddingResult:
        """단일 쿼리 → 단일 벡터 (호출처는 `result.embeddings[0]`로 접근)."""
        payload: dict[str, Any] = {"model": self._model, "input": text}
        data = await self._post_embeddings(payload)
        return EmbeddingResult(embeddings=_extract_embeddings_sorted(data))

    async def _post_embeddings(self, payload: dict[str, Any]) -> dict[str, Any]:
        """POST 호출 + 지수 백오프 재시도. 4xx는 즉시 raise (모델 ID 오류 등).

        매 호출마다 새 httpx.AsyncClient 생성 → 호출 사이 pool state 격리.
        """
        url = f"{self._base_url}{EMBEDDINGS_PATH}"
        timeout = httpx.Timeout(
            connect=10.0,
            read=self._timeout,
            write=self._timeout,
            pool=self._timeout,
        )
        input_count = (
            1 if isinstance(payload.get("input"), str) else len(payload.get("input") or [])
        )
        last_exc: Exception | None = None

        # 첫 시도 직전 raw socket 진단 — httpx/anyio 거치지 않고 OS 단 connect 가능한지 확인.
        # uvicorn 컨텍스트에서 즉시 ConnectError 나는 원인이 OS 레벨인지 라이브러리 레벨인지 가림.
        await self._diagnose_raw_connect(url)

        for attempt in range(1, self._max_retries + 1):
            logger.info(
                "LM Studio POST attempt=%d url=%s model=%s input_count=%d",
                attempt, url, self._model, input_count,
            )
            try:
                # 매 호출마다 새 client — broken pool state 회피
                async with httpx.AsyncClient(timeout=timeout) as client:
                    response = await client.post(url, json=payload)
            except (httpx.ConnectError, httpx.ReadTimeout, httpx.RemoteProtocolError) as exc:
                last_exc = exc
                if attempt >= self._max_retries:
                    break
                wait = self._backoff_base * (2 ** (attempt - 1))
                logger.warning(
                    "LM Studio 임베딩 일시 장애 (%s: %s) — %.1fs 후 재시도 (%d/%d)",
                    type(exc).__name__, exc, wait, attempt, self._max_retries,
                )
                await asyncio.sleep(wait)
                continue
            except httpx.HTTPError as exc:
                # 기타 HTTP 에러는 재시도 안 함 — 즉시 raise
                logger.exception("LM Studio 임베딩 요청 실패: url=%s", url)
                raise RuntimeError(f"LM Studio 임베딩 요청 실패: {exc}") from exc

            if response.status_code >= 500:
                # 5xx도 일시 장애로 간주, 재시도
                last_exc = RuntimeError(f"5xx: {response.status_code} {response.text[:200]}")
                if attempt >= self._max_retries:
                    response.raise_for_status()
                wait = self._backoff_base * (2 ** (attempt - 1))
                logger.warning(
                    "LM Studio 5xx 응답 (%d) — %.1fs 후 재시도 (%d/%d)",
                    response.status_code, wait, attempt, self._max_retries,
                )
                await asyncio.sleep(wait)
                continue

            if response.status_code >= 400:
                # 4xx는 클라이언트 에러 — 재시도 무의미, 즉시 raise
                logger.error(
                    "LM Studio 임베딩 4xx: status=%d body=%s",
                    response.status_code, response.text[:500],
                )
                response.raise_for_status()

            return response.json()

        # max_retries 소진
        logger.error("LM Studio 임베딩 재시도 모두 실패: url=%s last_exc=%s", url, last_exc)
        raise RuntimeError(
            f"LM Studio 임베딩 요청 실패 (재시도 {self._max_retries}회 모두 실패): {last_exc}"
        ) from last_exc

    async def _diagnose_raw_connect(self, url: str) -> None:
        """진단용 — raw TCP socket으로 직접 connect 시도. 결과를 로그에만 남김.

        httpx/anyio 거치지 않으므로 OS 단에서 connect 가능 여부를 알 수 있다.
        - 성공이면: OS는 정상, 라이브러리 레벨 문제
        - 실패면: OS/방화벽/보안 정책 레벨 차단
        """
        try:
            parsed = urlparse(url)
            host = parsed.hostname or ""
            port = parsed.port or 80
            # asyncio.to_thread로 sync socket 호출을 별도 스레드에서 (event loop 블록 방지)
            await asyncio.to_thread(self._sync_socket_check, host, port)
        except Exception as exc:
            logger.error(
                "RAW SOCKET DIAG FAILED: host=%s port=%s err=%s: %s",
                host if "host" in dir() else "?",
                port if "port" in dir() else "?",
                type(exc).__name__, exc,
            )

    @staticmethod
    def _sync_socket_check(host: str, port: int) -> None:
        """stdlib socket으로 3초 timeout 동기 connect 시도. 성공 시 즉시 close."""
        try:
            s = socket.create_connection((host, port), timeout=3.0)
            s.close()
            logger.info("RAW SOCKET DIAG OK: host=%s port=%s", host, port)
        except Exception as exc:
            logger.error(
                "RAW SOCKET DIAG FAILED at create_connection: host=%s port=%s err=%s: %s",
                host, port, type(exc).__name__, exc,
            )
            raise


def _extract_embeddings_sorted(payload: dict[str, Any]) -> list[list[float]]:
    """OpenAI 호환 응답에서 `data[*].embedding` 추출. `index` 기준 정렬해 입력 순서 보장."""
    items = payload.get("data") or []
    if not isinstance(items, list):
        raise RuntimeError(f"임베딩 응답 'data' 필드가 list가 아님: {type(items).__name__}")
    # data[i] 가 index 필드를 가짐 — 보통 정렬돼 오지만 안전하게 명시 정렬.
    indexed = []
    for i, item in enumerate(items):
        if not isinstance(item, dict):
            raise RuntimeError(f"임베딩 응답 data[{i}] 가 dict 아님")
        idx = item.get("index", i)
        vec = item.get("embedding")
        if vec is None:
            raise RuntimeError(f"임베딩 응답 data[{i}] 에 'embedding' 없음")
        indexed.append((idx, vec))
    indexed.sort(key=lambda x: x[0])
    return [list(vec) for _, vec in indexed]
