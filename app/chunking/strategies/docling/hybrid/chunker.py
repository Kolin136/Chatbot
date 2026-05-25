"""HybridChunker 구성 + chunks.jsonl 직렬화."""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from docling_core.transforms.chunker.hybrid_chunker import HybridChunker
from docling_core.transforms.chunker.tokenizer.huggingface import HuggingFaceTokenizer
from docling_core.types.doc.document import DoclingDocument
from transformers import AutoTokenizer

from app.chunking.strategies.docling.serializers import AnnotationSerializerProvider

logger = logging.getLogger(__name__)

# 환경변수에서 직접 읽음 — app/config.py 와 동일한 키 (config.py는 chromadb 의존성 회피용).
DEFAULT_EMBED_MODEL = os.environ.get(
    "CHUNK_TOKENIZER_MODEL", "sentence-transformers/all-MiniLM-L6-v2"
)
DEFAULT_MAX_TOKENS = int(os.environ.get("CHUNK_MAX_TOKENS", "512"))


def build_chunker(
    pic_descriptions: dict[str, str],
    table_descriptions: dict[str, str],
    embed_model: str = DEFAULT_EMBED_MODEL,
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> HybridChunker:
    tokenizer = HuggingFaceTokenizer(
        tokenizer=AutoTokenizer.from_pretrained(embed_model),
        max_tokens=max_tokens,
    )
    return HybridChunker(
        tokenizer=tokenizer,
        merge_peers=True,
        serializer_provider=AnnotationSerializerProvider(
            pic_descriptions=pic_descriptions,
            table_descriptions=table_descriptions,
        ),
    )


def _collect_pages(doc_items: list[Any]) -> list[int]:
    """청크 내 모든 doc_item의 prov[].page_no를 모아 정렬된 리스트로 반환."""
    pages: set[int] = set()
    for it in doc_items:
        prov = getattr(it, "prov", None)
        if not prov:
            continue
        for p in prov:
            page_no = getattr(p, "page_no", None)
            if page_no is not None:
                pages.add(page_no)
    return sorted(pages)


def _build_chunk_record(
    index: int,
    chunk: Any,
    chunker: HybridChunker,
    doc_name: str,
    picture_self_refs: set[str],
    table_self_refs: set[str],
) -> dict[str, Any]:
    doc_items = list(getattr(chunk.meta, "doc_items", []) or [])
    refs = [it.self_ref for it in doc_items]
    headings = list(getattr(chunk.meta, "headings", []) or [])
    pages = _collect_pages(doc_items)
    return {
        "chunk_id": f"{doc_name}#{index:05d}",
        "doc_name": doc_name,
        "text": chunk.text,
        "contextualized_text": chunker.contextualize(chunk=chunk),
        "headings": headings,
        "page_nos": pages,
        "page_start": pages[0] if pages else None,
        "page_end": pages[-1] if pages else None,
        "doc_item_refs": refs,
        "picture_refs": [r for r in refs if r in picture_self_refs],
        "table_refs": [r for r in refs if r in table_self_refs],
    }


def write_chunks_jsonl(
    doc: DoclingDocument,
    chunker: HybridChunker,
    out_path: Path,
    doc_name: str,
    picture_self_refs: set[str],
    table_self_refs: set[str],
) -> int:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with out_path.open("w", encoding="utf-8") as fp:
        for i, chunk in enumerate(chunker.chunk(dl_doc=doc)):
            record = _build_chunk_record(
                index=i,
                chunk=chunk,
                chunker=chunker,
                doc_name=doc_name,
                picture_self_refs=picture_self_refs,
                table_self_refs=table_self_refs,
            )
            fp.write(json.dumps(record, ensure_ascii=False) + "\n")
            count += 1
    logger.info("청크 저장 완료: %s (%d개)", out_path, count)
    return count
