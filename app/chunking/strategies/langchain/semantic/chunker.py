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
import re
from pathlib import Path
from typing import Any

from docling_core.types.doc.document import DoclingDocument
from langchain_core.embeddings import Embeddings
from langchain_experimental.text_splitter import SemanticChunker

# 통합 텍스트 조립 + doc_item 역매핑은 fixed_size 전략과 공유 (strategies/common.py).
# 원래 이 파일의 private 함수였던 것을 승격 — 본문 수정을 피하려 원래 이름으로 alias.
from app.chunking.strategies.common import (
    DEFAULT_LANG as _DEFAULT_LANG,
    DocItemSpan as _DocItemSpan,
    build_integrated_text as _build_integrated_text,
    collect_headings as _collect_headings,
    collect_pages as _collect_pages,
    items_in_range as _items_in_range,
)

from app.chunking.strategies.langchain.semantic.embeddings_adapter import (
    PydanticAIEmbeddingsAdapter,
)
from app.config import SEMANTIC_BREAKPOINT_AMOUNT, SEMANTIC_BREAKPOINT_TYPE

logger = logging.getLogger(__name__)

STRATEGY_NAME = "langchain_semantic"


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


def _sentence_spans(text: str, pattern: str) -> list[tuple[int, int]]:
    """문장 분리 결과를 (char_start, char_end) 목록으로 반환.

    SemanticChunker 내부의 `re.split(sentence_split_regex, text)` 와 동일한 경계를
    쓰되, 잘라낸 조각 대신 원문에서의 위치를 남긴다.
    구분자(문장 끝 뒤 공백)는 어느 문장에도 포함하지 않는다 — re.split 과 동일.
    """
    spans: list[tuple[int, int]] = []
    pos = 0
    for m in re.finditer(pattern, text):
        spans.append((pos, m.start()))
        pos = m.end()
    spans.append((pos, len(text)))
    return spans


def _map_chunks_to_spans(
    chunks: list[str], sentences: list[str], spans: list[tuple[int, int]]
) -> list[tuple[int, int]] | None:
    """SemanticChunker가 돌려준 청크 문자열 → 원문 char 구간으로 역매핑.

    청크는 연속된 문장 그룹을 `" ".join` 한 것이다(text_splitter.py:257).
    join 과정에서 원문의 개행이 공백으로 바뀌므로 청크 문자열 자체로는
    원문 위치를 찾을 수 없다. 대신 "몇 번째 문장부터 몇 번째까지인가"를
    길이 누적으로 역산해 원문 구간을 얻는다.

    한 청크라도 문장 경계와 어긋나면 None 을 반환한다(호출자가 폴백).
    """
    out: list[tuple[int, int]] = []
    i = 0
    for chunk in chunks:
        if i >= len(sentences):
            return None
        # join 길이 = 문장 길이 합 + 사이 공백 수
        acc = 0
        j = i
        while j < len(sentences):
            acc += len(sentences[j]) + (1 if j > i else 0)
            if acc == len(chunk):
                break
            if acc > len(chunk):
                return None
            j += 1
        else:
            return None
        if " ".join(sentences[i : j + 1]) != chunk:
            return None
        out.append((spans[i][0], spans[j][1]))
        i = j + 1
    return out




def _build_chunk_record(
    index: int,
    char_start: int,
    char_end: int,
    integrated_text: str,
    spans: list[_DocItemSpan],
    doc_name: str,
    picture_self_refs: set[str],
    table_self_refs: set[str],
) -> dict[str, Any]:
    """청크 1개(원문 char 구간)를 chunks.jsonl 한 줄 dict로 변환.

    텍스트는 SemanticChunker가 돌려준 문자열이 아니라 **원문에서 직접 잘라낸다**.
    SemanticChunker는 문장을 `" ".join` 으로 재조립해 개행·문단 구분이 공백으로
    뭉개지므로, 그대로 쓰면 훼손된 텍스트가 임베딩되고 원문 위치도 못 찾는다.
    """
    lc_doc_text = integrated_text[char_start:char_end]

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
    return record


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

    # SemanticChunker.split_text 는 sync 함수 → to_thread 로 비동기화
    chunk_texts = await asyncio.to_thread(chunker.split_text, integrated_text)
    logger.info("SemanticChunker 응답: 청크 %d개 생성", len(chunk_texts))

    # 청크 문자열 → 원문 char 구간 역매핑.
    # SemanticChunker와 동일한 정규식으로 문장을 나눠 위치를 추적한 뒤,
    # 각 청크가 몇 번째~몇 번째 문장인지 길이로 역산한다.
    sent_spans = _sentence_spans(integrated_text, chunker.sentence_split_regex)
    sentences = [integrated_text[a:b] for a, b in sent_spans]
    char_ranges = _map_chunks_to_spans(chunk_texts, sentences, sent_spans)

    if char_ranges is None:
        # 역매핑 실패 — 문장 경계가 어긋난 경우. 전체를 한 청크로 두느니
        # 순차 근사(직전 청크 끝부터)로 진행하되 경고를 남긴다.
        logger.warning(
            "청크→원문 역매핑 실패 — 페이지/헤딩 귀속이 부정확할 수 있습니다 "
            "(문장 %d개, 청크 %d개)", len(sentences), len(chunk_texts),
        )
        char_ranges = []
        cursor = 0
        for t in chunk_texts:
            char_ranges.append((cursor, min(cursor + len(t), len(integrated_text))))
            cursor += len(t)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with out_path.open("w", encoding="utf-8") as fp:
        for i, (char_start, char_end) in enumerate(char_ranges):
            record = _build_chunk_record(
                index=count,
                char_start=char_start,
                char_end=char_end,
                integrated_text=integrated_text,
                spans=spans,
                doc_name=doc_name,
                picture_self_refs=picture_self_refs,
                table_self_refs=table_self_refs,
            )
            if not record["text"].strip():
                continue
            fp.write(json.dumps(record, ensure_ascii=False) + "\n")
            count += 1
    logger.info("chunks.jsonl 저장 완료: %s (%d개)", out_path, count)
    return count
