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


class RecommendResponse(BaseModel):
    """청킹 전략 추천 응답. strategy는 'docling_hybrid' 또는 'langchain_semantic'."""

    strategy: str
    reason: str


# ─── Embedding ───────────────────────────────────────────────────────────


class ChunkUpdateRequest(BaseModel):
    """청크 1개의 컨텍스트화된 텍스트 수정 요청.

    contextualized_text 만 수정 대상 — 임베딩 입력이자 ChromaDB documents/raw_text의
    출처이기 때문(embed.py). 원본 text 필드는 추적성을 위해 건드리지 않는다.

    chunk_id 를 URL 경로가 아닌 body 로 받는 이유: chunk_id 는 "doc#00000" 형태라
    '#' 가 URL 프래그먼트 구분자로 잘린다. 인코딩 실수 한 번에 조용히 깨지는 것을 피한다.
    """

    chunk_id: str
    contextualized_text: str


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


# ─── Evaluation (RAGAS) ──────────────────────────────────────────────────


class EvaluationRequest(BaseModel):
    collection: str
    label: str
    hybrid: bool = False  # True면 하이브리드 검색, False면 dense
    chunking: str = ""    # 표시용 라벨: hybrid|semantic
    storage: str = ""     # 표시용 라벨: raw|summary
    eval_set_name: str | None = None       # 서버 저장 평가셋 이름(우선)
    eval_set: list[dict[str, Any]] | None = None  # inline 평가셋(name 없을 때)
    repeats: int = 1      # 채점 반복(심판 변동성)


class EvaluationStartResponse(BaseModel):
    eval_job_id: str
    collection: str
    label: str


class EvaluationResultsResponse(BaseModel):
    """저장된 결과 요약 목록(비교 뷰용)."""

    results: list[dict[str, Any]]


# ─── 평가셋 (질문+정답) 생성/저장/조회 ──────────────────────────


class GeneratedEvalSet(BaseModel):
    """로컬 VLM이 PDF로 생성한 평가셋(아직 미저장 — 검수 대상)."""

    items: list[dict[str, Any]]  # [{question, ground_truth}]


class EvalSetSaveRequest(BaseModel):
    name: str
    items: list[dict[str, Any]]


class EvalSetInfo(BaseModel):
    name: str
    count: int
    with_gt: int  # 정답이 채워진 항목 수


class EvalSetsResponse(BaseModel):
    eval_sets: list[EvalSetInfo]


class EvalSetItemsResponse(BaseModel):
    name: str
    items: list[dict[str, Any]]
