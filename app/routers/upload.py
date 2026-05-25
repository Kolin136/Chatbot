"""PDF 업로드 + 비동기 청킹 라우터."""
from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import (
    APIRouter,
    BackgroundTasks,
    File,
    Form,
    HTTPException,
    UploadFile,
)

from app.chunking import process_pdf
from app.models import (
    ChunkingInfo,
    ChunkingsResponse,
    ChunksResponse,
    JobStatus,
    UploadStartResponse,
)
from app.upload_jobs import job_store

logger = logging.getLogger(__name__)
router = APIRouter()

DOCS_ROOT = Path("docs")
_VALID_STEM_PATTERN = re.compile(r"[^A-Za-z0-9가-힣_\-\.\[\] ]")


def _sanitize_stem(stem: str) -> str:
    cleaned = _VALID_STEM_PATTERN.sub("_", stem).strip()
    return cleaned or "document"


def _resolve_doc_name(original_stem: str) -> str:
    base = _sanitize_stem(original_stem)
    candidate = DOCS_ROOT / base
    if not candidate.exists():
        return base
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return f"{base}__{timestamp}"


def _run_chunking_job(
    job_id: str,
    pdf_path: Path,
    do_ocr: bool,
) -> None:
    """BackgroundTasks에서 실행되는 청킹 작업. JobStore 업데이트."""
    job_store.update(job_id, status="running")

    def _progress(progress: int, step: str, message: str) -> None:
        job_store.update(
            job_id, progress=progress, step=step, message=message
        )

    try:
        result = process_pdf(
            pdf_path=pdf_path,
            output_root=DOCS_ROOT,
            do_ocr=do_ocr,
            progress_callback=_progress,
        )
        job_store.update(
            job_id,
            status="completed",
            progress=100,
            step="done",
            message=f"완료 — 청크 {result.chunk_count}개",
            result={
                "doc_name": result.doc_name,
                "out_dir": str(result.out_dir),
                "chunk_count": result.chunk_count,
                "picture_count": result.picture_count,
                "table_count": result.table_count,
            },
        )
    except Exception as exc:
        logger.exception("청킹 작업 실패: job_id=%s", job_id)
        job_store.update(
            job_id,
            status="failed",
            step="error",
            message="청킹 실패",
            error=str(exc),
        )


@router.post("/upload", response_model=UploadStartResponse)
async def upload_pdf(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    do_ocr: bool = Form(False),
) -> UploadStartResponse:
    if not file.filename:
        raise HTTPException(status_code=400, detail="파일 이름이 비어있습니다.")
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="PDF 파일만 업로드 가능합니다.")

    original_stem = Path(file.filename).stem
    doc_name = _resolve_doc_name(original_stem)
    out_dir = DOCS_ROOT / doc_name
    out_dir.mkdir(parents=True, exist_ok=True)

    saved_path = out_dir / f"{doc_name}.pdf"
    try:
        content = await file.read()
        saved_path.write_bytes(content)
    except Exception as exc:
        logger.exception("PDF 저장 실패")
        raise HTTPException(status_code=500, detail=f"PDF 저장 실패: {exc}")

    job_id = str(uuid.uuid4())
    job_store.create(job_id)
    background_tasks.add_task(
        _run_chunking_job, job_id, saved_path, do_ocr
    )

    logger.info(
        "업로드 수신: %s → %s (job_id=%s)", file.filename, saved_path, job_id
    )
    return UploadStartResponse(
        job_id=job_id,
        doc_name=doc_name,
        saved_path=str(saved_path),
    )


@router.get("/upload/status/{job_id}", response_model=JobStatus)
async def upload_status(job_id: str) -> JobStatus:
    state = job_store.get(job_id)
    if state is None:
        raise HTTPException(status_code=404, detail="job_id를 찾을 수 없습니다.")
    return JobStatus(
        job_id=state.job_id,
        status=state.status,
        progress=state.progress,
        step=state.step,
        message=state.message,
        result=state.result,
        error=state.error,
    )


@router.get("/chunkings", response_model=ChunkingsResponse)
async def list_chunkings() -> ChunkingsResponse:
    """`docs/<doc_name>/chunks.jsonl` 있는 디렉터리들의 메타 목록 반환."""
    if not DOCS_ROOT.exists():
        return ChunkingsResponse(chunkings=[])

    items: list[ChunkingInfo] = []
    for child in sorted(DOCS_ROOT.iterdir()):
        if not child.is_dir():
            continue
        chunks_path = child / "chunks.jsonl"
        if not chunks_path.exists():
            continue

        info = _read_chunking_info(child, chunks_path)
        items.append(info)

    # 최신순 정렬
    items.sort(key=lambda x: x.created_at, reverse=True)
    return ChunkingsResponse(chunkings=items)


def _read_chunking_info(doc_dir: Path, chunks_path: Path) -> ChunkingInfo:
    """디렉터리에서 ChunkingInfo 구성."""
    doc_name = doc_dir.name

    # chunk_count: chunks.jsonl 의 빈 줄 제외 줄 수
    chunk_count = 0
    try:
        with chunks_path.open("r", encoding="utf-8") as fp:
            for line in fp:
                if line.strip():
                    chunk_count += 1
    except Exception:
        logger.exception("chunks.jsonl 줄 수 측정 실패: %s", chunks_path)

    # mapping.json 에서 picture/table 카운트 + source_pdf
    source_pdf = ""
    picture_count = 0
    table_count = 0
    mapping_path = doc_dir / "mapping.json"
    if mapping_path.exists():
        try:
            payload = json.loads(mapping_path.read_text(encoding="utf-8"))
            source_pdf = payload.get("source_pdf", "")
            picture_count = len(payload.get("pictures") or {})
            table_count = len(payload.get("tables") or {})
        except Exception:
            logger.exception("mapping.json 파싱 실패: %s", mapping_path)

    # source_pdf 비어있으면 디렉터리 안의 .pdf 파일 fallback
    if not source_pdf:
        pdfs = list(doc_dir.glob("*.pdf"))
        if pdfs:
            source_pdf = str(pdfs[0])

    # created_at: chunks.jsonl mtime (가장 안정적)
    try:
        mtime = chunks_path.stat().st_mtime
        created_at = datetime.fromtimestamp(mtime).isoformat(timespec="seconds")
    except Exception:
        created_at = ""

    return ChunkingInfo(
        doc_name=doc_name,
        source_pdf=source_pdf,
        chunk_count=chunk_count,
        picture_count=picture_count,
        table_count=table_count,
        created_at=created_at,
    )


@router.get("/chunkings/{doc_name}/chunks", response_model=ChunksResponse)
async def get_chunks(doc_name: str) -> ChunksResponse:
    """`docs/<doc_name>/chunks.jsonl` 을 청크 리스트로 반환. job_store 의존성 없음."""
    if not doc_name.strip():
        raise HTTPException(status_code=400, detail="doc_name이 비어있습니다.")

    out_dir = DOCS_ROOT / doc_name
    if not out_dir.is_dir():
        raise HTTPException(
            status_code=404,
            detail=f"청킹 결과 디렉터리를 찾을 수 없습니다: {out_dir}",
        )

    chunks_path = out_dir / "chunks.jsonl"
    if not chunks_path.exists():
        raise HTTPException(status_code=404, detail="chunks.jsonl을 찾을 수 없습니다.")

    chunks: list[dict] = []
    with chunks_path.open("r", encoding="utf-8") as fp:
        for line in fp:
            line = line.strip()
            if not line:
                continue
            chunks.append(json.loads(line))
    return ChunksResponse(chunks=chunks)
