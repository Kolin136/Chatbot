"""청킹 전략 공용 헬퍼 — 통합 텍스트 조립 + doc_item 역매핑.

Docling이 파싱한 DoclingDocument를 하나의 평문 텍스트로 이어붙이면서,
각 doc_item이 그 텍스트의 어느 char 구간에 해당하는지 기록한다.
이후 임의의 청크(char 구간)에 대해 페이지 번호·헤딩·이미지/표 참조를 역으로 찾을 수 있다.

langchain_semantic 과 fixed_size 가 공유한다.
docling_hybrid 는 Docling 자체 chunker가 메타를 붙이므로 이 모듈을 쓰지 않는다.

원래 semantic/chunker.py 내부 private 함수였던 것을 fixed_size 추가 시 공용으로 승격.
공유 측 편의를 위해 이름에서 밑줄을 뗐다(동작은 동일).
"""
from __future__ import annotations

from dataclasses import dataclass
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

# 이미지/표 설명문을 통합 텍스트에 끼워넣을 때 사용할 도입 문구 템플릿.
# 자연어 흐름 형태로 작성 — SemanticChunker가 의미 단위로 잘 묶도록 유도.
DEFAULT_LANG = "ko"
PICTURE_PROLOGUES = {
    "ko": "이 문서에 그림이 하나 있다. 그 설명: {desc}",
    "en": "There is a figure in this document. Description: {desc}",
}
TABLE_PROLOGUES = {
    "ko": "이 문서에 표가 하나 있다. 그 설명: {desc}",
    "en": "There is a table in this document. Description: {desc}",
}


@dataclass
class DocItemSpan:
    """통합 텍스트 안에서 한 doc_item이 차지하는 char 범위."""

    item: Any  # TextItem | SectionHeaderItem | PictureItem | TableItem | ...
    start: int  # char offset (포함)
    end: int  # char offset (제외)


def build_integrated_text(
    doc: DoclingDocument,
    pic_descriptions: dict[str, str],
    table_descriptions: dict[str, str],
    lang: str = DEFAULT_LANG,
    skip_media: bool = False,
) -> tuple[str, list[DocItemSpan]]:
    """doc.iterate_items() 순회해 통합 텍스트 + doc_item char span 생성.

    - SectionHeaderItem/TitleItem → "\\n\\n# {text}\\n\\n"
    - TextItem/ListItem → "{text}\\n"
    - PictureItem → "\\n\\n{도입문구}\\n\\n" (skip된 picture는 제외)
    - TableItem → "\\n\\n{도입문구}\\n{markdown}\\n\\n"

    skip_media=True면 PictureItem/TableItem을 통째로 제외 — 설명문도 markdown 표도
    통합 텍스트에 넣지 않는다 (본문 텍스트만 남김).
    """
    pic_prologue = PICTURE_PROLOGUES.get(lang, PICTURE_PROLOGUES[DEFAULT_LANG])
    table_prologue = TABLE_PROLOGUES.get(lang, TABLE_PROLOGUES[DEFAULT_LANG])

    parts: list[str] = []
    spans: list[DocItemSpan] = []
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
        spans.append(DocItemSpan(item=item, start=start, end=end))
        parts.append(text_block)
        cursor = end

    return "".join(parts), spans


def items_in_range(
    spans: list[DocItemSpan], char_start: int, char_end: int
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


def collect_pages(items: list[Any]) -> list[int]:
    pages: set[int] = set()
    for it in items:
        prov = getattr(it, "prov", None) or []
        for p in prov:
            page_no = getattr(p, "page_no", None)
            if page_no is not None:
                pages.add(page_no)
    return sorted(pages)


def collect_headings(items: list[Any], all_spans: list[DocItemSpan], chunk_start: int) -> list[str]:
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
