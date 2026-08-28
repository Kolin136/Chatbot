"""PDF 업로드 + 비동기 청킹 라우터."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
import tempfile
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
    ChunkUpdateRequest,
    JobStatus,
    RecommendResponse,
    UploadStartResponse,
)
from app.upload_jobs import job_store

logger = logging.getLogger(__name__)
router = APIRouter()

DOCS_ROOT = Path("chunking-results")
_VALID_STEM_PATTERN = re.compile(r"[^A-Za-z0-9가-힣_\-\.\[\] ]")

_chunks_write_lock = asyncio.Lock()
"""chunks.jsonl 수정 직렬화. 같은 파일에 동시 PATCH가 들어와도 read-modify-write가 겹치지 않게."""


def _resolve_chunks_path(doc_name: str) -> Path:
    """doc_name → chunking-results/<doc_name>/chunks.jsonl (경로 순회 차단).

    _sanitize_stem은 '.'을 허용해 '..'을 못 막으므로 여기서 별도 검증한다.
    macOS 파일시스템 NFD 파일명 대응으로 NFC 정규화도 함께 수행.
    """
    name = unicodedata.normalize("NFC", (doc_name or "").strip())
    if not name:
        raise HTTPException(status_code=400, detail="doc_name이 비어있습니다.")
    if "/" in name or "\\" in name or ".." in name or Path(name).is_absolute():
        raise HTTPException(status_code=400, detail="잘못된 doc_name입니다.")

    out_dir = DOCS_ROOT / name
    # 심볼릭 링크 등으로 DOCS_ROOT를 벗어나지 않는지 최종 확인
    try:
        resolved = out_dir.resolve()
        if not resolved.is_relative_to(DOCS_ROOT.resolve()):
            raise HTTPException(status_code=400, detail="잘못된 doc_name입니다.")
    except (OSError, ValueError):
        raise HTTPException(status_code=400, detail="잘못된 doc_name입니다.")

    if not out_dir.is_dir():
        raise HTTPException(
            status_code=404,
            detail=f"청킹 결과 디렉터리를 찾을 수 없습니다: {out_dir}",
        )
    chunks_path = out_dir / "chunks.jsonl"
    if not chunks_path.exists():
        raise HTTPException(status_code=404, detail="chunks.jsonl을 찾을 수 없습니다.")
    return chunks_path


def _read_chunks(chunks_path: Path) -> list[dict]:
    """chunks.jsonl → dict 리스트. 빈 줄 skip."""
    chunks: list[dict] = []
    with chunks_path.open("r", encoding="utf-8") as fp:
        for line in fp:
            line = line.strip()
            if not line:
                continue
            chunks.append(json.loads(line))
    return chunks


def _write_chunks_atomic(chunks_path: Path, chunks: list[dict]) -> None:
    """전량 재작성 — 같은 디렉터리 임시 파일에 쓴 뒤 os.replace로 교체.

    쓰기 도중 프로세스가 죽어도 반쪽 파일이 남지 않는다.
    기존 writer 규약(ensure_ascii=False + 줄 끝 개행) 동일.
    """
    fd, tmp_name = tempfile.mkstemp(
        dir=str(chunks_path.parent), prefix=".chunks-", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fp:
            for c in chunks:
                fp.write(json.dumps(c, ensure_ascii=False) + "\n")
            fp.flush()
            os.fsync(fp.fileno())
        os.replace(tmp_name, chunks_path)
    except Exception:
        Path(tmp_name).unlink(missing_ok=True)
        raise


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
    lang: str,
    skip_media: bool = False,
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
            lang=lang,
            skip_media=skip_media,
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
                "skip_media": skip_media,
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
    lang: str = Form("ko"),
    skip_media: bool = Form(False),
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
    if lang not in ("ko", "en"):
        raise HTTPException(status_code=400, detail=f"지원하지 않는 lang: {lang}")

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
        _run_chunking_job,
        job_id=job_id,
        pdf_path=saved_path,
        do_ocr=do_ocr,
        strategy=strategy,
        lang=lang,
        skip_media=skip_media,
    )

    logger.info(
        "업로드 수신: %s → %s (job_id=%s, strategy=%s, lang=%s, skip_media=%s)",
        filename, saved_path, job_id, strategy, lang, skip_media,
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
    """`chunking-results/<doc_name>/chunks.jsonl` 을 청크 리스트로 반환."""
    chunks_path = _resolve_chunks_path(doc_name)
    return ChunksResponse(chunks=_read_chunks(chunks_path))


@router.patch("/chunkings/{doc_name}/chunks")
async def update_chunk(doc_name: str, req: ChunkUpdateRequest) -> dict:
    """청크 1개의 contextualized_text 를 수정하고 chunks.jsonl 에 반영.

    임베딩 전에 사람이 청크를 교정할 수 있게 하는 용도.
    (예: 이미지 설명이 엉뚱한 섹션 청크에 붙은 경우 잘라내기)

    - contextualized_text 만 수정 — 임베딩 입력이자 ChromaDB documents/raw_text 의
      출처이기 때문. 원본 text 필드는 추적성을 위해 보존한다.
    - 최초 1회에 한해 chunks.jsonl.bak 으로 원본 백업 (이미 있으면 덮어쓰지 않음).
    - 전량 원자적 재작성.

    chunk_id 는 body 로 받는다 — "doc#00000" 의 '#' 가 URL에서 잘리기 때문.
    """
    chunk_id = req.chunk_id
    text = req.contextualized_text
    if not chunk_id.strip():
        raise HTTPException(status_code=400, detail="chunk_id가 비어있습니다.")
    if not text or not text.strip():
        raise HTTPException(
            status_code=400,
            detail="contextualized_text가 비어있습니다. 빈 청크는 임베딩할 수 없습니다.",
        )

    chunks_path = _resolve_chunks_path(doc_name)

    async with _chunks_write_lock:
        try:
            chunks = _read_chunks(chunks_path)
        except json.JSONDecodeError as exc:
            raise HTTPException(
                status_code=500, detail=f"chunks.jsonl 파싱 실패: {exc}"
            )

        target_idx = next(
            (i for i, c in enumerate(chunks) if c.get("chunk_id") == chunk_id), None
        )
        if target_idx is None:
            raise HTTPException(
                status_code=404, detail=f"chunk_id를 찾을 수 없습니다: {chunk_id}"
            )

        # 최초 편집 시에만 원본 백업 — 여러 번 고쳐도 최초 청킹 결과가 남도록.
        backup_path = chunks_path.with_suffix(chunks_path.suffix + ".bak")
        if not backup_path.exists():
            shutil.copy2(chunks_path, backup_path)
            logger.info("청크 원본 백업 생성: %s", backup_path)

        chunks[target_idx]["contextualized_text"] = text
        _write_chunks_atomic(chunks_path, chunks)

    logger.info(
        "청크 수정: doc=%s chunk_id=%s (%d자)", doc_name, chunk_id, len(text)
    )
    return chunks[target_idx]
