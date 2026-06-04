"""PDF → 청크 JSONL 파이프라인.

흐름:
1. PDF → DoclingDocument (텍스트/표 구조/이미지 추출, OCR 옵션) — 공통
2. 이미지/표 → Pydantic AI(Gemini)로 자연어 설명문 생성 — 공통
3. 원본 이미지 PNG + 표 md/html/csv 별도 저장 — 공통
4. mapping.json 저장 (청크 ↔ 원본 매핑) — 공통
5. 전체 markdown 통문서 저장 (검증용) — 공통
6. 청킹 → chunks.jsonl 저장 — **strategy 분기**
   - "docling_hybrid":     HybridChunker (구조 단위 + 토큰 한도)
   - "langchain_semantic": SemanticChunker (임베딩 유사도 기반 의미 단위)
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Literal, Optional

from app.chunking.annotator import Annotator
from app.chunking.strategies.docling import (
    DEFAULT_EMBED_MODEL,
    DEFAULT_MAX_TOKENS,
    build_chunker as build_hybrid_chunker,
    build_converter,
    save_full_markdown,
    save_picture_images,
    save_tables,
    write_chunks_jsonl as write_hybrid_chunks_jsonl,
    write_mapping_json,
)

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[int, str, str], None]
"""(progress_percent, step_key, message) — 진행 상황 알림."""

ChunkStrategy = Literal["docling_hybrid", "langchain_semantic"]
DEFAULT_STRATEGY: ChunkStrategy = "docling_hybrid"


def _default_skip_classes() -> frozenset[str]:
    raw = os.environ.get("SKIP_PICTURE_CLASSES", "logo")
    return frozenset(c.strip().lower() for c in raw.split(",") if c.strip())


def _get_picture_class(pic: Any) -> str:
    """Docling DocumentFigureClassifier 결과 → 라벨 문자열 (없으면 '')."""
    meta = getattr(pic, "meta", None)
    if meta is None:
        return ""
    classification = getattr(meta, "classification", None)
    if classification is None:
        return ""
    try:
        pred = classification.get_main_prediction()
    except Exception:
        return ""
    if pred is None:
        return ""
    return (getattr(pred, "class_name", "") or "").lower()


@dataclass
class ProcessResult:
    doc_name: str
    out_dir: Path
    full_md_path: Path
    chunks_jsonl_path: Path
    mapping_path: Path
    chunk_count: int
    picture_count: int
    table_count: int
    strategy: ChunkStrategy = DEFAULT_STRATEGY


def _noop(_progress: int, _step: str, _message: str) -> None:
    return None


async def process_pdf(
    pdf_path: str | Path,
    output_root: str | Path = "chunking-results",
    do_ocr: bool = False,
    strategy: ChunkStrategy = DEFAULT_STRATEGY,
    vlm_model: Any = None,
    embed_model: str = DEFAULT_EMBED_MODEL,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    progress_callback: Optional[ProgressCallback] = None,
) -> ProcessResult:
    """PDF 1개를 청킹 파이프라인에 통과시킴 (async).

    - 원본 PDF는 호출자가 미리 `output_root/<stem>/<stem>.pdf` 에 둘 것.
      `process_pdf` 는 그 위치(혹은 임의 위치)의 PDF를 입력으로 받아
      `output_root/<stem>/` 폴더에 청킹 결과를 떨어뜨림.
    - `strategy`: "docling_hybrid"(기본) | "langchain_semantic".
    - `progress_callback(progress, step, message)` 가 주어지면 단계별로 호출.
    """
    cb: ProgressCallback = progress_callback or _noop

    pdf_path = Path(pdf_path)
    output_root = Path(output_root)
    doc_name = pdf_path.stem
    out_dir = output_root / doc_name

    logger.info("=== 처리 시작: %s (strategy=%s) ===", pdf_path.name, strategy)
    logger.info("출력 디렉토리: %s", out_dir)
    cb(0, "convert", "PDF 변환 중...")

    # 1. PDF → DoclingDocument
    converter = build_converter(do_ocr=do_ocr)
    logger.info("PDF 변환 중 (do_ocr=%s)...", do_ocr)
    conv_res = converter.convert(pdf_path)
    doc = conv_res.document
    n_pics = len(doc.pictures)
    n_tbls = len(doc.tables)
    logger.info("변환 완료: 이미지 %d개, 표 %d개", n_pics, n_tbls)
    cb(5, "converted", f"이미지 {n_pics}개, 표 {n_tbls}개 인식")

    # 2. picture classification 확인 → skip 대상 분리 후 나머지에만 Gemini 호출
    skip_classes = _default_skip_classes()
    annotator = Annotator(model=vlm_model)
    pic_descriptions: dict[str, str] = {}
    pic_classifications: dict[str, str] = {}
    skipped_pictures: dict[str, dict[str, Any]] = {}

    for i, pic in enumerate(doc.pictures, start=1):
        cls = _get_picture_class(pic)
        pic_classifications[pic.self_ref] = cls
        if cls in skip_classes:
            logger.info("이미지 skip (class=%s): %s", cls, pic.self_ref)
            page = None
            prov = getattr(pic, "prov", None)
            if prov:
                page = getattr(prov[0], "page_no", None)
            skipped_pictures[pic.self_ref] = {
                "classification": cls,
                "reason": f"in SKIP_PICTURE_CLASSES ({cls})",
                "page_no": page,
            }
            continue
        img = pic.get_image(doc)
        if img is None:
            continue
        pct = 5 + int((i / max(n_pics, 1)) * 60)
        cb(pct, "vlm_image", f"이미지 {i}/{n_pics} 처리 중 (class={cls or '?'})")
        logger.info("이미지 설명 생성 (class=%s): %s", cls, pic.self_ref)
        pic_descriptions[pic.self_ref] = await annotator.describe_image(img)

    # 3. 표 → 자연어 설명문
    table_descriptions: dict[str, str] = {}
    for i, tbl in enumerate(doc.tables, start=1):
        try:
            df = tbl.export_to_dataframe(doc=doc)
            md = df.to_markdown(index=False)
        except Exception as exc:
            logger.warning("표 markdown 추출 실패 %s: %s", tbl.self_ref, exc)
            continue
        logger.info("표 설명 생성: %s", tbl.self_ref)
        pct = 65 + int((i / max(n_tbls, 1)) * 25)
        cb(pct, "vlm_table", f"표 {i}/{n_tbls} 처리 중")
        table_descriptions[tbl.self_ref] = await annotator.describe_table(md)

    # 4. 원본 파일 저장
    cb(90, "save_assets", "원본 이미지/표 저장 중")
    images_mapping = save_picture_images(
        doc,
        out_dir / "images",
        pic_descriptions,
        pic_classifications=pic_classifications,
        skipped_refs=set(skipped_pictures.keys()),
    )
    tables_mapping = save_tables(doc, out_dir / "tables", table_descriptions)

    # 5. mapping.json
    mapping_path = out_dir / "mapping.json"
    write_mapping_json(
        mapping_path,
        doc_name=doc_name,
        source_pdf=str(pdf_path),
        pictures=images_mapping,
        tables=tables_mapping,
        skipped_pictures=skipped_pictures,
    )

    # 6. 전체 markdown 통문서
    full_md_path = out_dir / f"{doc_name}.md"
    save_full_markdown(doc, full_md_path)

    # 7. 청킹 → chunks.jsonl  (전략 분기)
    cb(95, "chunking", f"청크 생성 중 (strategy={strategy})")
    chunks_path = out_dir / "chunks.jsonl"
    picture_refs = set(images_mapping.keys())
    table_refs = set(tables_mapping.keys())

    if strategy == "langchain_semantic":
        from app.chunking.strategies.langchain.semantic import (
            build_chunker as build_semantic_chunker,
            write_chunks_jsonl as write_semantic_chunks_jsonl,
        )

        sem_chunker = build_semantic_chunker()
        chunk_count = await write_semantic_chunks_jsonl(
            doc=doc,
            pic_descriptions=pic_descriptions,
            table_descriptions=table_descriptions,
            chunker=sem_chunker,
            out_path=chunks_path,
            doc_name=doc_name,
            picture_self_refs=picture_refs,
            table_self_refs=table_refs,
        )
    else:
        # docling_hybrid (기본)
        chunker = build_hybrid_chunker(
            pic_descriptions=pic_descriptions,
            table_descriptions=table_descriptions,
            embed_model=embed_model,
            max_tokens=max_tokens,
        )
        chunk_count = write_hybrid_chunks_jsonl(
            doc=doc,
            chunker=chunker,
            out_path=chunks_path,
            doc_name=doc_name,
            picture_self_refs=picture_refs,
            table_self_refs=table_refs,
        )

    logger.info(
        "=== 완료: %s (strategy=%s, 청크 %d개) ===",
        pdf_path.name, strategy, chunk_count,
    )
    cb(100, "done", f"완료 — 청크 {chunk_count}개")

    return ProcessResult(
        doc_name=doc_name,
        out_dir=out_dir,
        full_md_path=full_md_path,
        chunks_jsonl_path=chunks_path,
        mapping_path=mapping_path,
        chunk_count=chunk_count,
        picture_count=len(images_mapping),
        table_count=len(tables_mapping),
        strategy=strategy,
    )


__all__ = [
    "process_pdf",
    "ProcessResult",
    "ProgressCallback",
    "ChunkStrategy",
    "DEFAULT_STRATEGY",
    "DEFAULT_EMBED_MODEL",
    "DEFAULT_MAX_TOKENS",
]
