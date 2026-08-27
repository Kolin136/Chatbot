"""LangChain SemanticChunker 청킹 + chunks.jsonl 직렬화.

전체 흐름:
1. _build_integrated_text(): doc.iterate_items() 순회 — 본문/헤더/그림 설명/표 설명을 한 줄씩
   합쳐 통합 텍스트 + 각 doc_item 의 char span(start_offset, end_offset) 기록.
2. SemanticChunker.create_documents() 가 통합 텍스트를 의미 단위로 자름.
   동기 함수이므로 호출자가 asyncio.to_thread 로 감싸 실행.
3. 각 LangChain Document 의 page_content 가 통합 텍스트의 어느 char span인지 찾고,
   그 범위와 겹치는 doc_item 들을 모아 page_nos/picture_refs/table_refs/headings 부여.
4. chunks.jsonl 스키마 docling hybrid 와 동일 + strategy 필드 추가.
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from docling_core.types.doc.document import (
    DoclingDocument,
    ListItem,
    PictureItem,
    SectionHeaderItem,
    TableItem,
    TextItem,
    TitleItem,
)
from langchain_core.embeddings import Embeddings
from langchain_experimental.text_splitter import SemanticChunker

from app.chunking.strategies.langchain.semantic.embeddings_adapter import (
    PydanticAIEmbeddingsAdapter,
)
from app.config import SEMANTIC_BREAKPOINT_AMOUNT, SEMANTIC_BREAKPOINT_TYPE

logger = logging.getLogger(__name__)

STRATEGY_NAME = "langchain_semantic"

# 이미지/표 설명문을 통합 텍스트에 끼워넣을 때 사용할 도입 문구 템플릿.
# 자연어 흐름 형태로 작성 — SemanticChunker가 의미 단위로 잘 묶도록 유도.
_DEFAULT_LANG = "ko"
_PICTURE_PROLOGUES = {
    "ko": "이 문서에 그림이 하나 있다. 그 설명: {desc}",
    "en": "There is a figure in this document. Description: {desc}",
}
_TABLE_PROLOGUES = {
    "ko": "이 문서에 표가 하나 있다. 그 설명: {desc}",
    "en": "There is a table in this document. Description: {desc}",
}


@dataclass
class _DocItemSpan:
    """통합 텍스트 안에서 한 doc_item이 차지하는 char 범위."""

    item: Any  # TextItem | SectionHeaderItem | PictureItem | TableItem | ...
    start: int  # char offset (포함)
    end: int  # char offset (제외)


def build_chunker(
    *,
    embeddings: Embeddings | None = None,
    breakpoint_threshold_type: str | None = None,
    breakpoint_threshold_amount: float | None = None,
) -> SemanticChunker:
    """SemanticChunker 인스턴스 생성. 미지정 시 .env 기본값 사용."""
    bp_type = breakpoint_threshold_type or SEMANTIC_BREAKPOINT_TYPE
    bp_amount = (
        breakpoint_threshold_amount
        if breakpoint_threshold_amount is not None
        else SEMANTIC_BREAKPOINT_AMOUNT
    )
    return SemanticChunker(
        embeddings or PydanticAIEmbeddingsAdapter(),
        breakpoint_threshold_type=bp_type,
        breakpoint_threshold_amount=bp_amount,
    )


def _build_integrated_text(
    doc: DoclingDocument,
    pic_descriptions: dict[str, str],
    table_descriptions: dict[str, str],
    lang: str = _DEFAULT_LANG,
    skip_media: bool = False,
) -> tuple[str, list[_DocItemSpan]]:
    """doc.iterate_items() 순회해 통합 텍스트 + doc_item char span 생성.

    - SectionHeaderItem/TitleItem → "\\n\\n# {text}\\n\\n"
    - TextItem/ListItem → "{text}\\n"
    - PictureItem → "\\n\\n{도입문구}\\n\\n" (skip된 picture는 제외)
    - TableItem → "\\n\\n{도입문구}\\n{markdown}\\n\\n"

    skip_media=True면 PictureItem/TableItem을 통째로 제외 — 설명문도 markdown 표도
    통합 텍스트에 넣지 않는다 (본문 텍스트만 남김).
    """
    pic_prologue = _PICTURE_PROLOGUES.get(lang, _PICTURE_PROLOGUES[_DEFAULT_LANG])
    table_prologue = _TABLE_PROLOGUES.get(lang, _TABLE_PROLOGUES[_DEFAULT_LANG])

    parts: list[str] = []
    spans: list[_DocItemSpan] = []
    cursor = 0

    for item, _level in doc.iterate_items():
        text_block = ""

        if isinstance(item, (TitleItem, SectionHeaderItem)):
            heading = (getattr(item, "text", "") or "").strip()
            if not heading:
                continue
            text_block = f"\n\n# {heading}\n\n"
        elif isinstance(item, (TextItem, ListItem)):
            body = (getattr(item, "text", "") or "").strip()
            if not body:
                continue
            text_block = body + "\n"
        elif isinstance(item, PictureItem):
            if skip_media:
                continue
            desc = pic_descriptions.get(item.self_ref, "").strip()
            if not desc:
                continue  # 설명 없음(skip된 logo 등) → 통합 텍스트에 포함하지 않음
            text_block = f"\n\n{pic_prologue.format(desc=desc)}\n\n"
        elif isinstance(item, TableItem):
            if skip_media:
                continue
            desc = table_descriptions.get(item.self_ref, "").strip()
            md = ""
            try:
                df = item.export_to_dataframe(doc=doc)
                md = df.to_markdown(index=False)
            except Exception:
                pass
            if not desc and not md:
                continue
            if desc and md:
                text_block = f"\n\n{table_prologue.format(desc=desc)}\n{md}\n\n"
            elif desc:
                text_block = f"\n\n{table_prologue.format(desc=desc)}\n\n"
            else:
                text_block = f"\n\n{md}\n\n"
        else:
            continue

        start = cursor
        end = cursor + len(text_block)
        spans.append(_DocItemSpan(item=item, start=start, end=end))
        parts.append(text_block)
        cursor = end

    return "".join(parts), spans


def _items_in_range(
    spans: list[_DocItemSpan], char_start: int, char_end: int
) -> list[Any]:
    """[char_start, char_end) 범위와 겹치는 doc_item 들 반환 (위치순)."""
    result = []
    for sp in spans:
        if sp.end <= char_start:
            continue
        if sp.start >= char_end:
            break
        result.append(sp.item)
    return result


def _collect_pages(items: list[Any]) -> list[int]:
    pages: set[int] = set()
    for it in items:
        prov = getattr(it, "prov", None) or []
        for p in prov:
            page_no = getattr(p, "page_no", None)
            if page_no is not None:
                pages.add(page_no)
    return sorted(pages)


def _collect_headings(items: list[Any], all_spans: list[_DocItemSpan], chunk_start: int) -> list[str]:
    """청크 시작 이전에 등장한 가장 가까운 SectionHeader/Title 한 개를 헤더로 사용.

    완벽한 계층 추적은 안 하고 단순화 — 청크 시작점 직전의 헤더 1개만.
    """
    last_header_text = ""
    for sp in all_spans:
        if sp.start >= chunk_start:
            break
        if isinstance(sp.item, (TitleItem, SectionHeaderItem)):
            text = (getattr(sp.item, "text", "") or "").strip()
            if text:
                last_header_text = text
    return [last_header_text] if last_header_text else []


def _build_chunk_record(
    index: int,
    lc_doc_text: str,
    integrated_text: str,
    spans: list[_DocItemSpan],
    search_cursor: int,
    doc_name: str,
    picture_self_refs: set[str],
    table_self_refs: set[str],
) -> tuple[dict[str, Any], int]:
    """LangChain Document 1개를 chunks.jsonl 한 줄 dict로 변환.

    `search_cursor` 부터 통합 텍스트 안에서 lc_doc_text 시작 위치를 찾는다.
    반환: (record dict, 다음 search_cursor)
    """
    # 통합 텍스트 안에서 청크의 char span 위치 찾기
    pos = integrated_text.find(lc_doc_text, search_cursor)
    if pos < 0:
        # 만일 못 찾으면 처음부터 다시 시도
        pos = integrated_text.find(lc_doc_text)
    if pos < 0:
        # 그래도 못 찾으면 search_cursor 부터로 가정
        pos = search_cursor

    char_start = pos
    char_end = pos + len(lc_doc_text)

    items = _items_in_range(spans, char_start, char_end)
    refs = [getattr(it, "self_ref", "") for it in items]
    picture_refs = [r for r in refs if r in picture_self_refs]
    table_refs = [r for r in refs if r in table_self_refs]
    pages = _collect_pages(items)
    headings = _collect_headings(items, spans, char_start)

    # contextualized_text: heading prepend
    if headings and headings[0]:
        contextualized_text = headings[0] + "\n" + lc_doc_text
    else:
        contextualized_text = lc_doc_text

    record = {
        "chunk_id": f"{doc_name}#{index:05d}",
        "doc_name": doc_name,
        "text": lc_doc_text,
        "contextualized_text": contextualized_text,
        "headings": headings,
        "page_nos": pages,
        "page_start": pages[0] if pages else None,
        "page_end": pages[-1] if pages else None,
        "doc_item_refs": refs,
        "picture_refs": picture_refs,
        "table_refs": table_refs,
        "strategy": STRATEGY_NAME,
    }
    return record, char_end


async def write_chunks_jsonl(
    *,
    doc: DoclingDocument,
    pic_descriptions: dict[str, str],
    table_descriptions: dict[str, str],
    chunker: SemanticChunker,
    out_path: Path,
    doc_name: str,
    picture_self_refs: set[str],
    table_self_refs: set[str],
    lang: str = _DEFAULT_LANG,
    skip_media: bool = False,
) -> int:
    """SemanticChunker로 청크 생성 후 chunks.jsonl 작성. 청크 개수 반환."""
    integrated_text, spans = _build_integrated_text(
        doc, pic_descriptions, table_descriptions, lang, skip_media
    )
    if not integrated_text.strip():
        if skip_media:
            logger.warning(
                "통합 텍스트가 비어있어 청킹할 내용이 없습니다 "
                "(skip_media=True — 그림/표를 제외했더니 본문이 남지 않음)."
            )
        else:
            logger.warning("통합 텍스트가 비어있어 청킹할 내용이 없습니다.")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text("", encoding="utf-8")
        return 0

    logger.info(
        "SemanticChunker 호출: 통합 텍스트 %d자, doc_item span %d개",
        len(integrated_text),
        len(spans),
    )

    # SemanticChunker.create_documents 는 sync 함수 → to_thread 로 비동기화
    documents = await asyncio.to_thread(
        chunker.create_documents, [integrated_text]
    )
    logger.info("SemanticChunker 응답: 청크 %d개 생성", len(documents))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    search_cursor = 0
    with out_path.open("w", encoding="utf-8") as fp:
        for i, lc_doc in enumerate(documents):
            record, search_cursor = _build_chunk_record(
                index=i,
                lc_doc_text=lc_doc.page_content,
                integrated_text=integrated_text,
                spans=spans,
                search_cursor=search_cursor,
                doc_name=doc_name,
                picture_self_refs=picture_self_refs,
                table_self_refs=table_self_refs,
            )
            fp.write(json.dumps(record, ensure_ascii=False) + "\n")
            count += 1
    logger.info("chunks.jsonl 저장 완료: %s (%d개)", out_path, count)
    return count
