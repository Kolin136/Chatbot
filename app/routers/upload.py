"""PDF 업로드 + 비동기 청킹 라우터."""
from __future__ import annotations

import json
import logging
import re
import unicodedata
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
    RecommendResponse,
    UploadStartResponse,
)
from app.upload_jobs import job_store

logger = logging.getLogger(__name__)
router = APIRouter()

DOCS_ROOT = Path("chunking-results")
_VALID_STEM_PATTERN = re.compile(r"[^A-Za-z0-9가-힣_\-\.\[\] ]")


def _fix_multipart_filename(name: str) -> str:
    """multipart filename 한글 깨짐을 두 단계로 복원.

    1) latin-1로 디코딩된 mojibake인 경우 → UTF-8로 재해석.
       (일부 starlette 환경에서 발생 가능)
    2) macOS의 NFD(분해형 자모) 한글 → NFC(합쳐진 음절) 정규화.
       (macOS Finder에서 직접 업로드 시 발생)
    """
    if not name:
        return name
    try:
        # latin-1 mojibake 케이스: 모든 글자가 0~255 → 재해석
        decoded = name.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        # 이미 정상 UTF-8 (한글 음절 NFC 또는 NFD 자모)
        decoded = name
    # NFC 정규화 — NFD 분해 자모를 합쳐진 음절로 통합
    return unicodedata.normalize("NFC", decoded)


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


async def _run_chunking_job(
    job_id: str,
    pdf_path: Path,
    do_ocr: bool,
    strategy: str,
) -> None:
    """BackgroundTasks에서 실행되는 청킹 작업 (async). JobStore 업데이트."""
    job_store.update(job_id, status="running")

    def _progress(progress: int, step: str, message: str) -> None:
        job_store.update(
            job_id, progress=progress, step=step, message=message
        )

    try:
        result = await process_pdf(
            pdf_path=pdf_path,
            output_root=DOCS_ROOT,
            do_ocr=do_ocr,
            strategy=strategy,
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
                "strategy": result.strategy,
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
    strategy: str = Form("docling_hybrid"),
) -> UploadStartResponse:
    if not file.filename:
        raise HTTPException(status_code=400, detail="파일 이름이 비어있습니다.")
    # multipart filename 인코딩 보정 (latin-1 mojibake + macOS NFD)
    filename = _fix_multipart_filename(file.filename)
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="PDF 파일만 업로드 가능합니다.")
    if strategy not in ("docling_hybrid", "langchain_semantic"):
        raise HTTPException(
            status_code=400,
            detail=f"지원하지 않는 strategy: {strategy}",
        )

    original_stem = Path(filename).stem
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
        _run_chunking_job, job_id, saved_path, do_ocr, strategy
    )

    logger.info(
        "업로드 수신: %s → %s (job_id=%s, strategy=%s)",
        filename, saved_path, job_id, strategy,
    )
    return UploadStartResponse(
        job_id=job_id,
        doc_name=doc_name,
        saved_path=str(saved_path),
    )


@router.post("/upload/recommend", response_model=RecommendResponse)
async def recommend_chunking_strategy(
    file: UploadFile = File(...),
) -> RecommendResponse:
    """PDF를 Gemini API에 직접 전송해 청킹 전략을 추천받는다.

    PDF당 1회 단발성 호출. 청킹/임베딩 파이프라인과 완전 독립.
    GOOGLE_API_KEY가 .env에 없으면 503으로 응답하고 다른 기능은 정상 동작.
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="파일 이름이 비어있습니다.")
    filename = _fix_multipart_filename(file.filename)
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="PDF 파일만 분석 가능합니다.")

    pdf_bytes = await file.read()
    if not pdf_bytes:
        raise HTTPException(status_code=400, detail="빈 파일입니다.")
    # Gemini API inline PDF 한도. 무료 티어도 동일.
    if len(pdf_bytes) > 50 * 1024 * 1024:
        raise HTTPException(
            status_code=413,
            detail="PDF가 50MB를 초과합니다 (Gemini 한도).",
        )

    try:
        from app.chunking.recommender import recommend_strategy
        rec = await recommend_strategy(pdf_bytes, filename)
    except RuntimeError as exc:
        # GOOGLE_API_KEY 미설정 — 옵션 기능 비활성 상태
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:
        logger.exception("청킹 전략 추천 실패: %s", filename)
        raise HTTPException(status_code=500, detail=f"추천 실패: {exc}")

    logger.info(
        "추천: %s → strategy=%s, reason_len=%d",
        filename, rec.strategy, len(rec.reason),
    )
    return RecommendResponse(strategy=rec.strategy, reason=rec.reason)


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
