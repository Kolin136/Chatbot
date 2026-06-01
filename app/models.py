from typing import Any

from pydantic import BaseModel


# ─── Chat ────────────────────────────────────────────────────────────────


class ChatRequest(BaseModel):
    session_id: str | None = None
    message: str
    collection: str | None = None  # None이면 RAG 검색 skip
    hybrid: bool = False
    """True면 Dense + BM25 + RRF 경로 (app.retrieval.hybrid_search). False면 기존 dense-only."""


class ChatSource(BaseModel):
    """챗 응답에 포함되는 참고 청크 메타. text는 응답에 노출하지 않음."""

    chunk_id: str
    page_start: int | None = None
    page_end: int | None = None
    heading: str = ""
    score: float = 0.0


class ChatResponse(BaseModel):
    session_id: str
    answer: str
    sources: list[ChatSource] = []


# ─── Upload / Chunking ───────────────────────────────────────────────────


class UploadStartResponse(BaseModel):
    job_id: str
    doc_name: str
    saved_path: str


class JobStatus(BaseModel):
    job_id: str
    status: str
    progress: int
    step: str
    message: str
    result: dict[str, Any] | None = None
    error: str | None = None


class ChunksResponse(BaseModel):
    """GET /api/upload/{job_id}/chunks — chunks.jsonl 한 줄을 dict로 그대로 반환."""

    chunks: list[dict[str, Any]]


class ChunkingInfo(BaseModel):
    """청킹 완료된 결과 디렉터리 한 개의 메타."""

    doc_name: str
    source_pdf: str = ""
    chunk_count: int = 0
    picture_count: int = 0
    table_count: int = 0
    created_at: str = ""


class ChunkingsResponse(BaseModel):
    chunkings: list[ChunkingInfo]


# ─── Embedding ───────────────────────────────────────────────────────────


class EmbedRequest(BaseModel):
    doc_name: str
    collection_name: str
    summarize: bool = False
    """True면 청크를 LLM으로 요약 후 요약을 임베딩. False면 청크 원본을 그대로 임베딩."""


class EmbedStartResponse(BaseModel):
    embed_job_id: str
    collection_name: str


# ─── Collections ─────────────────────────────────────────────────────────


class CollectionInfo(BaseModel):
    name: str
    count: int
    created_at: str = ""


class CollectionsResponse(BaseModel):
    collections: list[CollectionInfo]
