"""임베딩 라우터 — chunks.jsonl → (요약) → 임베딩 → ChromaDB 저장.

흐름:
  contextualized_text → Gemini 요약 → 요약을 임베딩 → ChromaDB add
  - documents: 요약 (검색 매칭용)
  - metadata.raw_text: contextualized_text 원본 (LLM 컨텍스트용, rag.py 가 우선 사용)
  - metadata.summary: 요약 (조회 편의)

POST /api/embed                       : 임베딩 작업 시작 (백그라운드)
GET  /api/embed/status/{embed_job_id} : 진행률/결과 조회
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic_ai import Agent

from app.config import chat_model, chroma_client, embedder
from app.embed_jobs import embed_job_store
from app.models import (
    EmbedRequest,
    EmbedStartResponse,
    JobStatus,
)

logger = logging.getLogger(__name__)
router = APIRouter()

EMBED_BATCH_SIZE = 32
DOCS_ROOT = Path("docs")

# 요약 LLM 호출 간격 (초). Gemini free tier 분당 한도 회피용.
# 환경변수로 조정 가능. 기본 13초 = 분당 ~4.6건 (scripts/index_docs.py 와 동일 정신).
SUMMARY_INTERVAL_SEC = float(os.environ.get("EMBED_SUMMARY_INTERVAL_SEC", "13"))

SUMMARY_INSTRUCTIONS = (
    "당신은 RAG 검색 인덱싱용 텍스트 요약 도우미입니다. "
    "주어진 텍스트를 1~2문장으로 요약하고, 검색에 유용한 핵심 키워드 3~5개를 추출하세요. "
    "반드시 다음 형식으로만 출력하세요:\n"
    "요약: <요약문>\n"
    "키워드: <쉼표로 구분된 키워드>"
)
SUMMARY_PROMPT_TEMPLATE = "다음 텍스트를 요약해 주세요:\n\n{text}"

_summary_agent: Agent[None, str] = Agent(
    chat_model,
    instructions=SUMMARY_INSTRUCTIONS,
)
_summary_last_call = 0.0  # 모듈 전역 — process 내 요약 호출 throttle 공유


async def _throttle_summary() -> None:
    """직전 요약 호출로부터 SUMMARY_INTERVAL_SEC 만큼 간격 강제."""
    global _summary_last_call
    if _summary_last_call == 0.0:
        _summary_last_call = time.monotonic()
        return
    elapsed = time.monotonic() - _summary_last_call
    if elapsed < SUMMARY_INTERVAL_SEC:
        wait = SUMMARY_INTERVAL_SEC - elapsed
        logger.info("요약 rate limit: %.1f초 대기", wait)
        await asyncio.sleep(wait)
    _summary_last_call = time.monotonic()


async def _summarize_one(text: str, idx: int, total: int) -> str:
    """단일 청크 요약. 실패 시 원문 반환 (fallback)."""
    await _throttle_summary()
    logger.info("[summary %d/%d] Gemini 요약 호출 (원문 %d자)", idx, total, len(text))
    try:
        result = await _summary_agent.run(SUMMARY_PROMPT_TEMPLATE.format(text=text))
        summary = (result.output or "").strip()
        logger.info("[summary %d/%d] 요약 응답 수신 (%d자)", idx, total, len(summary))
        return summary if summary else text
    except Exception as exc:
        logger.warning("[summary %d/%d] 요약 실패, 원문 사용: %s", idx, total, exc)
        return text


@router.post("/embed", response_model=EmbedStartResponse)
async def start_embedding(
    req: EmbedRequest,
    background_tasks: BackgroundTasks,
) -> EmbedStartResponse:
    if not req.doc_name.strip():
        raise HTTPException(status_code=400, detail="doc_name이 비어있습니다.")
    if not req.collection_name.strip():
        raise HTTPException(status_code=400, detail="collection_name이 비어있습니다.")

    out_dir = DOCS_ROOT / req.doc_name
    if not out_dir.is_dir():
        raise HTTPException(
            status_code=404,
            detail=f"청킹 결과 디렉터리를 찾을 수 없습니다: {out_dir}",
        )

    chunks_path = out_dir / "chunks.jsonl"
    if not chunks_path.exists():
        raise HTTPException(status_code=404, detail="chunks.jsonl을 찾을 수 없습니다.")

    embed_job_id = str(uuid.uuid4())
    embed_job_store.create(embed_job_id)
    background_tasks.add_task(
        _run_embed_job,
        embed_job_id=embed_job_id,
        chunks_path=chunks_path,
        collection_name=req.collection_name,
        doc_name=req.doc_name,
    )

    logger.info(
        "임베딩 시작: collection=%s job=%s chunks=%s",
        req.collection_name,
        embed_job_id,
        chunks_path,
    )
    return EmbedStartResponse(
        embed_job_id=embed_job_id,
        collection_name=req.collection_name,
    )


@router.get("/embed/status/{embed_job_id}", response_model=JobStatus)
async def get_embed_status(embed_job_id: str) -> JobStatus:
    state = embed_job_store.get(embed_job_id)
    if state is None:
        raise HTTPException(status_code=404, detail="embed_job_id를 찾을 수 없습니다.")
    return JobStatus(
        job_id=state.embed_job_id,
        status=state.status,
        progress=state.progress,
        step=state.step,
        message=state.message,
        result=state.result,
        error=state.error,
    )


async def _run_embed_job(
    embed_job_id: str,
    chunks_path: Path,
    collection_name: str,
    doc_name: str,
) -> None:
    """BackgroundTasks 실행 함수 (async). embed_job_store 갱신.

    async 함수로 둬야 embedder.embed_documents (httpx) 호출 시 동일 event loop 사용 →
    'Event loop is closed' 회피.
    """
    embed_job_store.update(
        embed_job_id,
        status="running",
        progress=0,
        step="prepare",
        message="청크 로드 중",
    )

    try:
        chunks = _load_chunks(chunks_path)
        total = len(chunks)
        if total == 0:
            raise RuntimeError("청크가 0개 — 임베딩 대상이 없습니다.")

        embed_job_store.update(
            embed_job_id,
            progress=2,
            step="setup",
            message=f"ChromaDB 컬렉션 준비 중 (총 {total} 청크)",
        )

        collection = chroma_client.get_or_create_collection(
            name=collection_name,
            embedding_function=None,
            metadata={
                "created_at": datetime.now().isoformat(timespec="seconds"),
                "doc_name": doc_name,
            },
        )

        total_batches = (total + EMBED_BATCH_SIZE - 1) // EMBED_BATCH_SIZE
        logger.info(
            "요약+임베딩 배치 시작: collection=%s, 청크 %d개 → %d개 배치 (batch_size=%d, summary_interval=%.1fs)",
            collection_name, total, total_batches, EMBED_BATCH_SIZE, SUMMARY_INTERVAL_SEC,
        )

        # 청크별: ① 요약 호출 (rate limit 적용) → 배치 단위로 ② 임베딩 ③ ChromaDB add
        processed = 0
        for batch_idx, batch_start in enumerate(range(0, total, EMBED_BATCH_SIZE), start=1):
            batch = chunks[batch_start : batch_start + EMBED_BATCH_SIZE]
            raw_texts = [c.get("contextualized_text") or c.get("text") or "" for c in batch]

            # ① 요약 — 청크별 순차 호출 (throttle)
            summaries: list[str] = []
            for i, raw in enumerate(raw_texts):
                global_idx = batch_start + i + 1
                summary = await _summarize_one(raw, global_idx, total)
                summaries.append(summary)
                # 요약 단계 progress (0% ~ 70%)
                summary_pct = int((global_idx / total) * 70)
                embed_job_store.update(
                    embed_job_id,
                    progress=summary_pct,
                    step="summarize",
                    message=f"요약 생성 중 ({global_idx}/{total} 청크)",
                )

            # ② 임베딩 (요약을 임베딩)
            logger.info(
                "[batch %d/%d] Gemini 임베딩 호출 (요약 %d개)",
                batch_idx, total_batches, len(summaries),
            )
            embed_result = await embedder.embed_documents(summaries)
            embeddings = list(embed_result.embeddings)
            logger.info(
                "[batch %d/%d] 임베딩 응답 수신 (%d 벡터, dim=%d)",
                batch_idx, total_batches,
                len(embeddings),
                len(embeddings[0]) if embeddings else 0,
            )

            # ③ ChromaDB add — documents=요약, metadata.raw_text=원본
            ids = [c["chunk_id"] for c in batch]
            documents = summaries  # 검색 시 documents 필드 = 요약
            metadatas: list[dict] = []
            for c, raw, summary in zip(batch, raw_texts, summaries):
                meta = _build_metadata(c)
                meta["raw_text"] = raw  # 원본 contextualized_text (rag.py가 우선 사용)
                meta["summary"] = summary
                metadatas.append(meta)

            await asyncio.to_thread(
                collection.add,
                ids=ids,
                embeddings=embeddings,
                documents=documents,
                metadatas=metadatas,
            )
            processed += len(batch)
            # add 후 progress (70% ~ 95%)
            pct = 70 + int((processed / total) * 25)
            logger.info(
                "[batch %d/%d] ChromaDB 저장 완료 → 누적 %d/%d (%d%%)",
                batch_idx, total_batches, processed, total, pct,
            )
            embed_job_store.update(
                embed_job_id,
                progress=pct,
                step="store",
                message=f"ChromaDB 저장 중 ({processed}/{total} 청크)",
            )

        embed_job_store.update(
            embed_job_id,
            progress=95,
            step="store",
            message="ChromaDB에 저장 완료, 마무리 중",
        )

        vector_count = collection.count()
        embed_job_store.update(
            embed_job_id,
            status="completed",
            progress=100,
            step="done",
            message=f"임베딩 완료 — ChromaDB에 {vector_count}개 저장",
            result={
                "collection_name": collection_name,
                "vector_count": vector_count,
            },
        )
        logger.info(
            "임베딩 완료: collection=%s count=%d", collection_name, vector_count
        )

    except Exception as exc:
        logger.exception("임베딩 작업 실패: embed_job_id=%s", embed_job_id)
        embed_job_store.update(
            embed_job_id,
            status="failed",
            step="error",
            message="임베딩 실패",
            error=str(exc),
        )


def _load_chunks(chunks_path: Path) -> list[dict]:
    chunks: list[dict] = []
    with chunks_path.open("r", encoding="utf-8") as fp:
        for line in fp:
            line = line.strip()
            if not line:
                continue
            chunks.append(json.loads(line))
    return chunks


def _build_metadata(chunk: dict) -> dict:
    """ChromaDB는 metadata 값으로 str/int/float/bool/None만 허용."""
    headings = chunk.get("headings") or []
    heading_top = headings[0] if headings else ""
    return {
        "chunk_id": chunk.get("chunk_id", ""),
        "doc_name": chunk.get("doc_name", ""),
        "heading": heading_top,
        "page_start": chunk.get("page_start") if chunk.get("page_start") is not None else -1,
        "page_end": chunk.get("page_end") if chunk.get("page_end") is not None else -1,
    }
