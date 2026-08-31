"""고정 크기 청킹 — 통합 텍스트를 N토큰씩 균등 분할.

문서 구조도 의미도 보지 않고 일정 토큰 수로 자르는 가장 단순한 전략.
docling_hybrid(구조 기반) / langchain_semantic(의미 기반) 의 효과를 재는 기준선(baseline)으로 쓴다.
임베딩·VLM 호출이 없어 청킹이 압도적으로 빠르다.

분할 방식 (핵심):
    토큰 id를 잘라 디코딩하는 통상적 방식을 쓰지 않는다. SentencePiece 계열은 공백을
    토큰에 흡수(▁)하므로 디코딩 결과가 원문의 부분문자열이 아니게 되고, 그러면
    통합 텍스트에서 청크 위치를 되찾을 수 없어 페이지/헤딩 귀속이 깨진다.

    대신 fast tokenizer의 offset_mapping(각 토큰 ↔ 원문 char 위치)을 써서
    토큰 경계를 char 경계로 환산하고, 원문을 그대로 슬라이스한다.
    → 청크가 항상 원문의 정확한 부분문자열이고, char span을 바로 알 수 있다.

    구간 끝은 "다음 구간의 시작"으로 잡는다. 토큰 offset은 토큰 사이 공백을
    포함하지 않아, 마지막 토큰의 end를 쓰면 경계 공백이 유실된다.

토큰 수는 목표치에서 ±2 정도 흔들린다. 잘라낸 텍스트를 다시 인코딩하면 경계에서
토큰화가 미세하게 달라지기 때문. 임베딩 한도(512)에는 한참 못 미치므로 무해하다.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from docling_core.types.doc.document import DoclingDocument
from transformers import AutoTokenizer

from app.chunking.strategies.common import (
    DEFAULT_LANG,
    build_integrated_text,
    collect_headings,
    collect_pages,
    items_in_range,
)

logger = logging.getLogger(__name__)

STRATEGY_NAME = "fixed_size"

# 환경변수 직접 읽음 — app/config.py 는 chromadb 를 끌어오므로 회피
# (docling/hybrid/chunker.py 와 동일 관례).
DEFAULT_TOKENIZER_MODEL = os.environ.get(
    "CHUNK_TOKENIZER_MODEL", "intfloat/multilingual-e5-large-instruct"
)
DEFAULT_CHUNK_SIZE = int(os.environ.get("FIXED_CHUNK_SIZE", "256"))


@dataclass
class FixedSizeChunker:
    """토크나이저 + 목표 토큰 수를 묶은 분할기."""

    tokenizer: Any
    chunk_size: int

    def split_bounds(self, text: str) -> list[tuple[int, int]]:
        """텍스트 → [(char_start, char_end), ...] 구간 목록.

        구간은 빈틈 없이 이어져 전체를 덮는다(오버랩 없음).
        빈 텍스트면 빈 리스트.
        """
        if not text:
            return []
        enc = self.tokenizer(
            text,
            return_offsets_mapping=True,
            add_special_tokens=False,
            truncation=False,
        )
        offsets = enc["offset_mapping"]
        if not offsets:
            return []

        # 각 윈도우 첫 토큰의 char 시작 위치가 경계가 된다.
        starts = [offsets[i][0] for i in range(0, len(offsets), self.chunk_size)]
        starts[0] = 0  # 선행 공백이 유실되지 않도록 항상 0부터
        bounds = starts + [len(text)]
        return [(bounds[i], bounds[i + 1]) for i in range(len(starts))]


def build_chunker(
    tokenizer_model: str = DEFAULT_TOKENIZER_MODEL,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
) -> FixedSizeChunker:
    """토크나이저를 로드해 분할기 생성.

    tokenizer_model 은 임베딩 모델과 같은 계열이어야 토큰 수가 실제와 일치한다
    (기본값이 CHUNK_TOKENIZER_MODEL 인 이유).
    """
    tokenizer = AutoTokenizer.from_pretrained(tokenizer_model)
    if not getattr(tokenizer, "is_fast", False):
        raise RuntimeError(
            f"'{tokenizer_model}' 은 fast tokenizer 가 아니라 offset_mapping 을 쓸 수 없습니다. "
            "고정 크기 청킹에는 fast tokenizer 가 필요합니다."
        )
    logger.info(
        "고정 크기 청커 준비: tokenizer=%s chunk_size=%d", tokenizer_model, chunk_size
    )
    return FixedSizeChunker(tokenizer=tokenizer, chunk_size=chunk_size)


def _build_chunk_record(
    index: int,
    text: str,
    char_start: int,
    char_end: int,
    spans: list[Any],
    doc_name: str,
    picture_self_refs: set[str],
    table_self_refs: set[str],
) -> dict[str, Any]:
    """청크 1개 → chunks.jsonl 한 줄. 스키마는 다른 전략과 동일 + strategy."""
    items = items_in_range(spans, char_start, char_end)
    refs = [getattr(it, "self_ref", "") for it in items]
    pages = collect_pages(items)
    headings = collect_headings(items, spans, char_start)

    if headings and headings[0]:
        contextualized_text = headings[0] + "\n" + text
    else:
        contextualized_text = text

    return {
        "chunk_id": f"{doc_name}#{index:05d}",
        "doc_name": doc_name,
        "text": text,
        "contextualized_text": contextualized_text,
        "headings": headings,
        "page_nos": pages,
        "page_start": pages[0] if pages else None,
        "page_end": pages[-1] if pages else None,
        "doc_item_refs": refs,
        "picture_refs": [r for r in refs if r in picture_self_refs],
        "table_refs": [r for r in refs if r in table_self_refs],
        "strategy": STRATEGY_NAME,
    }


def write_chunks_jsonl(
    *,
    doc: DoclingDocument,
    pic_descriptions: dict[str, str],
    table_descriptions: dict[str, str],
    chunker: FixedSizeChunker,
    out_path: Path,
    doc_name: str,
    picture_self_refs: set[str],
    table_self_refs: set[str],
    lang: str = DEFAULT_LANG,
    skip_media: bool = False,
) -> int:
    """고정 크기로 청킹 후 chunks.jsonl 작성. 청크 개수 반환."""
    integrated_text, spans = build_integrated_text(
        doc, pic_descriptions, table_descriptions, lang, skip_media
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if not integrated_text.strip():
        if skip_media:
            logger.warning(
                "통합 텍스트가 비어있어 청킹할 내용이 없습니다 "
                "(skip_media=True — 그림/표를 제외했더니 본문이 남지 않음)."
            )
        else:
            logger.warning("통합 텍스트가 비어있어 청킹할 내용이 없습니다.")
        out_path.write_text("", encoding="utf-8")
        return 0

    bounds = chunker.split_bounds(integrated_text)
    logger.info(
        "고정 크기 분할: 통합 텍스트 %d자 → 구간 %d개 (chunk_size=%d)",
        len(integrated_text), len(bounds), chunker.chunk_size,
    )

    count = 0
    skipped_empty = 0
    with out_path.open("w", encoding="utf-8") as fp:
        for char_start, char_end in bounds:
            text = integrated_text[char_start:char_end]
            # 공백만 남는 구간은 임베딩 가치가 없으므로 제외.
            # chunk_id 는 실제로 기록한 청크 기준으로 매긴다.
            if not text.strip():
                skipped_empty += 1
                continue
            record = _build_chunk_record(
                index=count,
                text=text,
                char_start=char_start,
                char_end=char_end,
                spans=spans,
                doc_name=doc_name,
                picture_self_refs=picture_self_refs,
                table_self_refs=table_self_refs,
            )
            fp.write(json.dumps(record, ensure_ascii=False) + "\n")
            count += 1

    if skipped_empty:
        logger.info("빈 청크 %d개 제외 (공백만 있음)", skipped_empty)
    logger.info("chunks.jsonl 저장 완료: %s (%d개)", out_path, count)
    return count
