"""하이브리드 검색 — Dense(ChromaDB) + Sparse(BM25) + RRF 융합.

흐름 (ARCHITECTURE.md §시퀀스 / §의사코드):
  사용자 쿼리 + collection
   ├── Dense:  embedder.embed_query → ChromaDB.query(n=DENSE_TOP_K) → ranked chunk_ids
   └── Sparse: tokenize_for_bm25(query) → BM25Okapi.get_scores → top-SPARSE_TOP_K chunk_ids
   ↓
  rrf_fuse([dense_ids, sparse_ids], k=RRF_K)
   ↓
  Top-N(FINAL_TOP_N) chunk_ids
   ↓
  ChromaDB에서 metadata + documents 재조회
   ↓
  RetrievedChunk[] (rag.py:74 폴백 규약 동일)

설계 규칙:
- ADR-002: rank_bm25 직접 사용. LangChain wrapper 우회.
- ADR-003: kiwipiepy 형태소 분석. NNG/NNP/VV/VA/SL/SN 보존 + lowercase.
- ADR-005: 인덱스 코퍼스는 ChromaDB metadata.raw_text (jsonl 안 봄).
- ADR-007: 어떤 단계 실패도 호출자에게 raise 안 함. silently fallback + log.
- ADR-008: LRUCache(maxsize=HYBRID_CACHE_MAXSIZE) + per-key asyncio.Lock + cache_lock.
- ADR-009: chunk_id 단일 진실 = ChromaDB ids 순서.
- ADR-010: RRF 점수 정규화 안 함.
- ADR-013: raw_text 없으면 documents fallback.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from collections import defaultdict
from typing import TYPE_CHECKING, Any

from cachetools import LRUCache
from rank_bm25 import BM25Okapi

from app.config import chroma_client, embedder
from app.rag import RetrievedChunk

if TYPE_CHECKING:
    from kiwipiepy import Kiwi

logger = logging.getLogger(__name__)

# ─── 환경변수 (모듈 로드 시 1회 읽음) ─────────────────────────
# Dense/Sparse 후보 수는 컬렉션 크기에 적응적으로 결정 (compute_top_k).
# 고정값 대신 비율을 쓰면 작은 컬렉션에선 후보 절감, 큰 컬렉션에선 일정 비율로 확장.
TOPK_PERCENT = float(os.environ.get("HYBRID_TOPK_PERCENT", "0.30"))
TOPK_MIN = int(os.environ.get("HYBRID_TOPK_MIN", "10"))
TOPK_MAX = int(os.environ.get("HYBRID_TOPK_MAX", "200"))
RRF_K = int(os.environ.get("HYBRID_RRF_K", "60"))
FINAL_TOP_N = int(os.environ.get("HYBRID_FINAL_TOP_N", "3"))
CACHE_MAXSIZE = int(os.environ.get("HYBRID_CACHE_MAXSIZE", "16"))


def compute_top_k(n: int) -> int:
    """컬렉션 청크 수 N → Dense/Sparse 후보 수.

    공식: clamp(N × PERCENT, MIN, MAX). 절대 N 초과하지 않음.
    예시 (PERCENT=0.30, MIN=10, MAX=200):
        N=5 → 5 (= N)
        N=25 → 10 (= MIN)
        N=100 → 30
        N=1000 → 200 (= MAX)
    """
    if n <= 0:
        return 0
    by_percent = int(n * TOPK_PERCENT)
    return min(max(by_percent, TOPK_MIN), TOPK_MAX, n)

# ─── 토크나이저 상수 ────────────────────────────────────────
KEEP_TAGS: frozenset[str] = frozenset({"NNG", "NNP", "VV", "VA", "SL", "SN"})
"""kiwipiepy 형태소 분석에서 BM25 인덱스에 보존할 태그.
NNG/NNP=명사, VV/VA=동사·형용사 어간, SL=외국어(영문), SN=숫자."""

_EMPTY_TOKEN = "__empty__"
"""토큰 0개인 청크용 sentinel. BM25Okapi가 빈 doc을 못 처리해서 채워둠."""

# ─── 모듈 레벨 상태 ──────────────────────────────────────────
_kiwi: "Kiwi | None" = None
_kiwi_init_lock = asyncio.Lock()
"""kiwipiepy lazy singleton + 초기화 보호. ADR-003 — 모듈 import 시 인스턴스화 금지."""

_bm25_cache: LRUCache = LRUCache(maxsize=CACHE_MAXSIZE)
_cache_lock = asyncio.Lock()
"""ADR-008 — LRUCache가 thread-safe 보장 안 함. read-modify-write 영역 보호."""

_build_locks: dict[tuple[str, int], asyncio.Lock] = {}
"""per-key 빌드 락. 같은 컬렉션 동시 첫 호출 시 빌드 1회만 (ADR-008)."""


# ─── 토크나이저 ──────────────────────────────────────────────
async def _get_kiwi() -> "Kiwi":
    """kiwipiepy 인스턴스 lazy init. 첫 호출 1회만 Kiwi() 생성."""
    global _kiwi
    if _kiwi is not None:
        return _kiwi
    async with _kiwi_init_lock:
        if _kiwi is None:
            from kiwipiepy import Kiwi
            _kiwi = Kiwi()
            logger.info("kiwipiepy Kiwi() 인스턴스화 완료")
    return _kiwi


def _get_kiwi_sync() -> "Kiwi":
    """sync 컨텍스트용. 이미 인스턴스화된 경우만 안전. 첫 호출이 sync면 즉시 생성.

    tokenize_for_bm25는 sync 함수 시그니처라 sync 진입점 필요.
    실패 시 예외 raise — 호출자 hybrid_search가 catch.
    """
    global _kiwi
    if _kiwi is None:
        from kiwipiepy import Kiwi
        _kiwi = Kiwi()
        logger.info("kiwipiepy Kiwi() 인스턴스화 완료 (sync path)")
    return _kiwi


def tokenize_for_bm25(text: str) -> list[str]:
    """텍스트 → BM25용 토큰 리스트.

    형태소 분석 후 KEEP_TAGS만 보존, 영문은 lowercase 통일.
    빈 입력 또는 토큰 0개 → [].
    예외 발생 → 빈 리스트 (silently).
    """
    if not text:
        return []
    try:
        kiwi = _get_kiwi_sync()
        return [t.form.lower() for t in kiwi.tokenize(text) if t.tag in KEEP_TAGS]
    except Exception as exc:
        logger.warning("tokenize_for_bm25 실패 (silently): %s", exc)
        return []


# ─── RRF ────────────────────────────────────────────────────
def rrf_fuse(rank_lists: list[list[str]], k: int = RRF_K) -> dict[str, float]:
    """Reciprocal Rank Fusion — score = Σ 1/(k + rank_i).

    각 ranked list의 rank는 1부터 시작. chunk_id별 점수 합산.
    빈 입력 → {}. pure function, 예외 raise 안 함.
    """
    fused: dict[str, float] = defaultdict(float)
    for rl in rank_lists:
        for rank, cid in enumerate(rl, start=1):
            fused[cid] += 1.0 / (k + rank)
    return dict(fused)


# ─── BM25 인덱스 캐시 ────────────────────────────────────────
async def get_or_build_bm25_index(
    collection_name: str,
) -> tuple[BM25Okapi, list[str]] | None:
    """컬렉션의 BM25 인덱스를 lookup or build.

    반환:
        (BM25Okapi, chunk_ids[N])  — 정상. chunk_ids 순서는 ChromaDB ids 그대로 (ADR-009)
        None                       — 컬렉션 비어있거나 raw_text/documents 전부 없음

    동시성 (ADR-008):
        같은 (collection_name, vector_count) 키로 동시 호출 시 빌드는 1회만.
        per-key asyncio.Lock + double-check.

    예외:
        ChromaDB 호출 예외는 raise (호출자 hybrid_search가 catch).
        BM25Okapi 빌드 예외는 warning + None 반환.
    """
    collection = chroma_client.get_or_create_collection(
        name=collection_name, embedding_function=None
    )

    # vector_count 조회 (캐시 키 구성용)
    vc = await asyncio.to_thread(collection.count)
    if vc == 0:
        return None

    cache_key = (collection_name, vc)

    # 1차 캐시 lookup (락 보호)
    async with _cache_lock:
        if cache_key in _bm25_cache:
            return _bm25_cache[cache_key]
        # per-key 락 dict에 없으면 생성
        if cache_key not in _build_locks:
            _build_locks[cache_key] = asyncio.Lock()
        build_lock = _build_locks[cache_key]

    # per-key 락으로 빌드 진입
    async with build_lock:
        # double-check: 다른 코루틴이 이미 빌드 끝냈을 수 있음
        async with _cache_lock:
            if cache_key in _bm25_cache:
                return _bm25_cache[cache_key]

        # 빌드 시작
        t0 = time.monotonic()
        logger.info(
            "bm25 build start: collection=%s n_chunks=%d", collection_name, vc
        )

        # 전체 청크 metadata + documents 가져오기
        full = await asyncio.to_thread(
            lambda: collection.get(include=["metadatas", "documents"])
        )
        ids = full.get("ids") or []
        metadatas = full.get("metadatas") or []
        documents = full.get("documents") or []

        # 텍스트 추출 — raw_text 우선, documents 폴백 (ADR-013 / rag.py:74)
        texts: list[str] = []
        for meta, doc in zip(metadatas, documents):
            text = (meta or {}).get("raw_text") or doc or ""
            texts.append(text)

        # 모든 텍스트가 비면 인덱스 빌드 의미 없음
        if not any(texts):
            logger.warning(
                "bm25 fallback to dense-only: reason=all_texts_empty collection=%s",
                collection_name,
            )
            return None

        # 토큰화
        tokenized: list[list[str]] = []
        total_tokens = 0
        for t in texts:
            toks = tokenize_for_bm25(t)
            if not toks:
                # 빈 청크는 sentinel로 (BM25Okapi가 빈 doc 못 처리 — E4/E6)
                toks = [_EMPTY_TOKEN]
            tokenized.append(toks)
            total_tokens += len(toks)

        # BM25Okapi 빌드
        try:
            bm25 = BM25Okapi(tokenized)
        except Exception as exc:
            logger.warning(
                "BM25Okapi build failed (silently): collection=%s err=%s",
                collection_name, exc,
            )
            return None

        build_ms = int((time.monotonic() - t0) * 1000)
        n_tokens_avg = total_tokens // max(len(tokenized), 1)
        logger.info(
            "bm25 build done: collection=%s n_tokens_avg=%d build_ms=%d",
            collection_name, n_tokens_avg, build_ms,
        )

        # 캐시 저장
        async with _cache_lock:
            # evict 발생 가능 — LRU
            prev_size = len(_bm25_cache)
            _bm25_cache[cache_key] = (bm25, list(ids))
            if prev_size >= CACHE_MAXSIZE:
                logger.warning(
                    "bm25 cache evict: key=%s (lru, current_size=%d)",
                    cache_key, len(_bm25_cache),
                )

        return _bm25_cache[cache_key]


# ─── 메인: hybrid_search ─────────────────────────────────────
async def hybrid_search(
    query: str,
    collection_name: str,
    n_results: int = FINAL_TOP_N,
) -> list[RetrievedChunk]:
    """Dense + Sparse + RRF 융합 후 top-N RetrievedChunk 반환.

    ADR-007: 어느 단계 실패도 raise 안 함. 빈 결과 + 로그.
    ADR-010: RRF 점수 그대로 RetrievedChunk.score로 노출 (정규화 X).
    """
    t_total = time.monotonic()
    cache_status = "MISS"
    dense_ms = 0
    sparse_ms = 0
    fuse_ms = 0
    fetch_ms = 0
    fallback_reason: str | None = None

    # 컬렉션 크기 기반 동적 후보 수 (Dense/Sparse 공통)
    collection = chroma_client.get_or_create_collection(
        name=collection_name, embedding_function=None
    )
    try:
        vector_count = await asyncio.to_thread(collection.count)
    except Exception as exc:
        logger.error(
            "collection count failed (silently): collection=%s err=%s",
            collection_name, exc,
        )
        vector_count = 0
    top_k = compute_top_k(vector_count)

    # ─ Dense 후보 ─────────────────────────────
    dense_ids: list[str] = []
    if top_k > 0:
        try:
            t0 = time.monotonic()
            embed_result = await embedder.embed_query(query)
            q_vec = embed_result.embeddings[0]
            dense_res = await asyncio.to_thread(
                lambda: collection.query(
                    query_embeddings=[q_vec],
                    n_results=top_k,
                    include=["metadatas", "distances"],
                )
            )
            dense_ids = (dense_res.get("ids") or [[]])[0]
            dense_ms = int((time.monotonic() - t0) * 1000)
        except Exception as exc:
            logger.error(
                "dense search failed (silently): collection=%s err=%s",
                collection_name, exc,
            )
            fallback_reason = f"dense_failed:{type(exc).__name__}"

    # ─ Sparse 후보 ────────────────────────────
    sparse_ids: list[str] = []
    try:
        t0 = time.monotonic()
        bm25_data = await get_or_build_bm25_index(collection_name)
        if bm25_data is None:
            fallback_reason = (fallback_reason or "bm25_unavailable")
        else:
            bm25, chunk_ids_index = bm25_data
            # 캐시 확인용 — 이번 호출 직후의 cache 상태로 HIT/MISS 판단
            # (정확히는 get_or_build 안에서 build 했는지 봐야 하지만 build 로그로 충분)
            async with _cache_lock:
                key = (collection_name, len(chunk_ids_index))
                if key in _bm25_cache:
                    cache_status = "HIT"

            q_tokens = tokenize_for_bm25(query)
            if not q_tokens:
                fallback_reason = (fallback_reason or "query_tokens_empty")
            else:
                scores = bm25.get_scores(q_tokens)
                top_idx = sorted(
                    range(len(scores)), key=lambda i: -scores[i]
                )[:top_k]
                sparse_ids = [chunk_ids_index[i] for i in top_idx]
        sparse_ms = int((time.monotonic() - t0) * 1000)
    except Exception as exc:
        logger.warning(
            "sparse fallback to dense-only: reason=exception err=%s collection=%s",
            exc, collection_name,
        )
        fallback_reason = (fallback_reason or f"sparse_failed:{type(exc).__name__}")

    # ─ 둘 다 비면 종료 ────────────────────────
    if not dense_ids and not sparse_ids:
        logger.warning(
            "hybrid_search empty result: collection=%s reason=%s",
            collection_name, fallback_reason or "both_empty",
        )
        return []

    # ─ RRF 융합 ───────────────────────────────
    t0 = time.monotonic()
    rank_lists = [lst for lst in (dense_ids, sparse_ids) if lst]
    fused = rrf_fuse(rank_lists, k=RRF_K)
    top_ids = sorted(fused.keys(), key=lambda cid: -fused[cid])[:n_results]
    fuse_ms = int((time.monotonic() - t0) * 1000)

    # ─ ChromaDB 재조회 ────────────────────────
    chunks: list[RetrievedChunk] = []
    if top_ids:
        try:
            t0 = time.monotonic()
            collection = chroma_client.get_or_create_collection(
                name=collection_name, embedding_function=None
            )
            fetch_res = await asyncio.to_thread(
                lambda: collection.get(
                    ids=top_ids, include=["metadatas", "documents"]
                )
            )
            fetch_ms = int((time.monotonic() - t0) * 1000)
            chunks = _build_retrieved_chunks(fetch_res, fused)
        except Exception as exc:
            logger.error(
                "hybrid fetch failed: collection=%s err=%s", collection_name, exc
            )

    total_ms = int((time.monotonic() - t_total) * 1000)
    logger.info(
        "hybrid_search: collection=%s cache=%s n=%d top_k=%d dense_n=%d sparse_n=%d "
        "dense_ms=%d sparse_ms=%d fuse_ms=%d fetch_ms=%d total_ms=%d top_n=%d%s",
        collection_name, cache_status, vector_count, top_k,
        len(dense_ids), len(sparse_ids),
        dense_ms, sparse_ms, fuse_ms, fetch_ms, total_ms, len(chunks),
        f" fallback_reason={fallback_reason}" if fallback_reason else "",
    )
    return chunks


def _build_retrieved_chunks(
    fetch_res: dict[str, Any], fused: dict[str, float]
) -> list[RetrievedChunk]:
    """ChromaDB get() 결과 + RRF 점수 → RetrievedChunk 리스트.

    필드 매핑 (ARCHITECTURE §응답 조립 매핑 / rag.py:74 동일):
        chunk_id ← metadata.chunk_id (없으면 ids[i])
        text     ← metadata.raw_text (없으면 documents[i])
        heading  ← metadata.heading (없으면 metadata.source)
        page_*   ← metadata.page_* (-1 → None)
        score    ← fused[chunk_id]  (RRF 점수 그대로 — ADR-010)
    """
    ids_list = fetch_res.get("ids") or []
    metas_list = fetch_res.get("metadatas") or []
    docs_list = fetch_res.get("documents") or []
    out: list[RetrievedChunk] = []
    for chunk_id, meta, doc in zip(ids_list, metas_list, docs_list):
        meta = meta or {}
        text = (meta.get("raw_text") or doc or "").strip()
        heading = meta.get("heading") or meta.get("source") or ""
        page_start = meta.get("page_start")
        page_end = meta.get("page_end")
        if page_start == -1:
            page_start = None
        if page_end == -1:
            page_end = None
        out.append(
            RetrievedChunk(
                chunk_id=meta.get("chunk_id", chunk_id),
                text=text,
                page_start=page_start,
                page_end=page_end,
                heading=heading,
                score=round(fused.get(chunk_id, 0.0), 6),
            )
        )
    return out
