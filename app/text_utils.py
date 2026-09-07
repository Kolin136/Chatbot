"""텍스트 처리 공용 유틸 — 문장 경계 추적.

시멘틱 청킹(경계 판정)과 임베딩 시점 자식 분할이 **같은 문장 경계**를 써야 해서
어느 한쪽에 두지 않고 분리했다.
- semantic/chunker.py 에 두면 자식 분할 쪽에서 langchain_experimental 이 딸려온다
- chunking/strategies/common.py 는 docling 타입에 묶여 있다

여기는 표준 라이브러리만 쓴다.
"""
from __future__ import annotations

import re

SENTENCE_SPLIT_REGEX = r"(?<=[.?!])\s+"
"""LangChain SemanticChunker 의 sentence_split_regex 기본값과 동일.

'.', '?', '!' 뒤에 공백/개행이 오면 문장 경계로 본다.
한국어에는 한계가 있다 — 번호 목록('1. 개요')이 쪼개지고, 마침표 없는 줄(제목 등)은
다음 문장과 붙는다. 형태소 분석기 기반으로 교체하려면 이 상수와 sentence_spans 만 바꾸면 된다.
"""


def sentence_spans(
    text: str, pattern: str = SENTENCE_SPLIT_REGEX
) -> list[tuple[int, int]]:
    """문장 분리 결과를 (char_start, char_end) 목록으로 반환.

    `re.split(pattern, text)` 와 동일한 경계를 쓰되, 잘라낸 조각 대신
    원문에서의 위치를 남긴다. 구분자(문장 끝 뒤 공백)는 어느 문장에도 포함하지 않는다.

    빈 문자열이면 [(0, 0)] 을 반환한다 (re.split 이 [''] 을 내는 것과 대응).
    """
    spans: list[tuple[int, int]] = []
    pos = 0
    for m in re.finditer(pattern, text):
        spans.append((pos, m.start()))
        pos = m.end()
    spans.append((pos, len(text)))
    return spans
