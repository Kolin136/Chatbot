"""RAG 검색 — 특정 ChromaDB 컬렉션에서 유사 청크 조회."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass

from app.config import chroma_client, embedder
from app.models import ChatSource

logger = logging.getLogger(__name__)


@dataclass
class RetrievedChunk:
    """RAG 검색 결과 — LLM 컨텍스트용 text + 응답 sources 메타."""

    chunk_id: str
    text: str
    page_start: int | None
    page_end: int | None
    heading: str
    score: float

    def to_source(self) -> ChatSource:
        return ChatSource(
            chunk_id=self.chunk_id,
            page_start=self.page_start,
            page_end=self.page_end,
            heading=self.heading,
            score=self.score,
        )


def dedupe_by_parent(
    chunks: list[RetrievedChunk], parents: list[str]
) -> list[RetrievedChunk]:
    """같은 부모에서 나온 자식들을 하나로 합친다 (Parent-Child 검색).

    큰 청크는 임베딩 시점에 자식 조각으로 나뉘어 색인된다(app/embeddings/child_split.py).
    자식 여러 개가 동시에 검색되면 `RetrievedChunk.text` 가 전부 같은 부모 원문이라
    LLM 프롬프트에 동일한 글이 중복 삽입된다.

    - 그룹 키: metadata.parent_chunk_id (없으면 chunk_id — 기존 컬렉션 호환)
    - 그룹 점수: 최댓값. 합산하면 자식이 많은 청크가 무조건 유리해진다
    - 점수 내림차순 정렬 — ChromaDB get(ids=...) 는 요청 순서를 보장하지 않으므로
      여기서 명시적으로 재정렬한다

    NOTE: 중복이 제거된 만큼 결과 개수가 n_results 보다 줄어들 수 있다.
    후보를 더 뽑아 채우는 것은 의도적으로 범위에서 제외했다.
    """
    best: dict[str, RetrievedChunk] = {}
    for chunk, parent in zip(chunks, parents):
        prev = best.get(parent)
        if prev is None or chunk.score > prev.score:
            best[parent] = chunk
    out = sorted(best.values(), key=lambda c: -c.score)
    if len(out) < len(chunks):
        logger.info(
            "부모 중복 제거: %d개 → %d개", len(chunks), len(out)
        )
    return out


async def search_relevant_context(
    query: str,
    collection_name: str,
    n_results: int = 3,
    hybrid: bool = False,
) -> list[RetrievedChunk]:
    """주어진 컬렉션에서 query와 유사한 청크 n_results개 반환.

    hybrid=True면 Dense + BM25 + RRF (app.retrieval.hybrid_search 위임).
    hybrid=False면 기존 dense-only 흐름 (ChromaDB 코사인 검색).
    어느 경우든 실패 시 빈 리스트 (호출자가 처리).
    """
    if hybrid:
        # 지연 import — 모듈 순환 방지 (app.retrieval이 RetrievedChunk를 import함)
        try:
            from app.retrieval import hybrid_search
            return await hybrid_search(query, collection_name, n_results=n_results)
        except Exception:
            logger.exception(
                "hybrid_search 예외 — dense-only로 fallback (collection=%s)",
                collection_name,
            )
            # fall through to dense
    result = await embedder.embed_query(query)
    query_embedding = result.embeddings[0]

    def _query():
        collection = chroma_client.get_or_create_collection(
            name=collection_name, embedding_function=None
        )
        return collection.query(
            query_embeddings=[query_embedding],
            n_results=n_results,
            include=["metadatas", "documents", "distances"],
        )

    try:
        results = await asyncio.to_thread(_query)
    except Exception:
        logger.exception("ChromaDB 검색 실패 (collection=%s)", collection_name)
        return []

    out: list[RetrievedChunk] = []
    parents: list[str] = []
    ids_list = (results.get("ids") or [[]])[0]
    docs_list = (results.get("documents") or [[]])[0]
    metas_list = (results.get("metadatas") or [[]])[0]
    dists_list = (results.get("distances") or [[]])[0]

    for chunk_id, doc, meta, dist in zip(ids_list, docs_list, metas_list, dists_list):
        meta = meta or {}
        # 기존 색인(index_docs.py)은 documents=요약문, metadata.raw_text=본문 구조.
        # 신규 색인(embed.py)은 documents=본문, metadata.raw_text 없음.
        # → raw_text 있으면 우선 사용 (실제 본문이 LLM에 들어가도록).
        text = (meta.get("raw_text") or doc or "").strip()
        heading = meta.get("heading") or meta.get("source") or ""
        page_start = meta.get("page_start")
        page_end = meta.get("page_end")
        # 신규 색인은 page 정보를 -1로 sentinel 저장 (ChromaDB가 None 불허). 복원.
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
                score=_distance_to_score(dist),
            )
        )
        parents.append(meta.get("parent_chunk_id") or meta.get("chunk_id") or chunk_id)
    return dedupe_by_parent(out, parents)


def _distance_to_score(distance: float | None) -> float:
    """ChromaDB distance를 0~1 score로 변환 (작을수록 가까움 → 높을수록 좋음)."""
    if distance is None:
        return 0.0
    # Chroma 기본은 squared L2 / cosine distance. 1 / (1 + d) 로 단조 변환.
    return round(1.0 / (1.0 + float(distance)), 4)
