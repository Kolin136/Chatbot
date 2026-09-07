"""임베딩 시점 자식 분할 — 큰 청크를 검색용 조각으로 나눈다 (Parent-Child).

왜 필요한가:
    시멘틱 청킹은 크기 상한이 없어 청크가 임베딩 모델 컨텍스트(512)를 넘긴다.
    넘긴 만큼은 조용히 잘려 **검색에 존재하지 않는 상태**가 된다.

왜 512가 아니라 256을 목표로 하는가:
    512는 "넘으면 잘린다"는 상한이지 좋은 검색 단위 크기가 아니다. 한 벡터에 여러
    주제가 들어가면 평균화되어 어느 질문에도 어정쩡하게 매칭된다. 긴 컨텍스트
    임베딩 모델로 바꿔도 이 희석은 그대로다.
    256은 docling_hybrid 실측 평균(225)·fixed_size 기본값(256)과 맞춰
    전략 간 검색 단위 크기를 통일하는 효과도 있다.

여기서 만든 조각은 **벡터를 만들기 위한 것일 뿐**이다. 검색에 걸리면 LLM에는
부모 청크 전체가 전달된다(metadata.raw_text). 그래서 조각 경계에 정보가 걸쳐도
답변 근거가 반쪽이 되지 않는다.
"""
from __future__ import annotations

import logging
import math
import os
from typing import Any

from app.text_utils import sentence_spans

logger = logging.getLogger(__name__)

# 환경변수 직접 읽음 — chunking/ 하위 모듈들과 동일 관례.
TOKENIZER_MODEL = os.environ.get(
    "CHUNK_TOKENIZER_MODEL", "intfloat/multilingual-e5-large-instruct"
)
MAX_TOKENS = int(os.environ.get("EMBED_MAX_TOKENS", "512"))
"""임베딩 모델이 한 번에 받는 최대 토큰. 이 값을 넘는 청크만 분할한다."""

CHILD_TARGET_TOKENS = int(os.environ.get("EMBED_CHILD_TARGET_TOKENS", "256"))
"""자식 1개의 목표 토큰 수. 정확히 이 크기로 자르는 게 아니라
`ceil(전체/이 값)` 개로 균등 분할할 때의 기준이다 (짜투리 방지)."""

_tokenizer: Any = None


def _get_tokenizer() -> Any:
    """토크나이저 lazy 로드. 모듈 import 만으로 모델을 내려받지 않도록."""
    global _tokenizer
    if _tokenizer is None:
        from transformers import AutoTokenizer

        _tokenizer = AutoTokenizer.from_pretrained(TOKENIZER_MODEL)
        logger.info("자식 분할용 토크나이저 로드: %s", TOKENIZER_MODEL)
    return _tokenizer


def count_tokens(text: str) -> int:
    return len(_get_tokenizer().encode(text, add_special_tokens=False))


def _force_split_by_tokens(text: str, n_parts: int) -> list[str]:
    """문장이 1개뿐인데 한도를 넘는 경우의 폴백 — 토큰 offset 으로 강제 분할.

    fast tokenizer 의 offset_mapping 으로 토큰 경계를 char 경계로 환산한다.
    디코딩을 쓰지 않으므로 조각이 항상 원문의 정확한 부분문자열이다.
    """
    tok = _get_tokenizer()
    enc = tok(text, return_offsets_mapping=True, add_special_tokens=False, truncation=False)
    offsets = enc["offset_mapping"]
    if not offsets or n_parts <= 1:
        return [text]
    size = math.ceil(len(offsets) / n_parts)
    starts = [offsets[i][0] for i in range(0, len(offsets), size)]
    starts[0] = 0
    bounds = starts + [len(text)]
    parts = [text[bounds[i] : bounds[i + 1]] for i in range(len(starts))]
    return [p for p in parts if p.strip()]


def split_for_embedding(text: str) -> list[str]:
    """청크 텍스트 → 임베딩할 조각 목록.

    MAX_TOKENS 이하면 [text] 를 그대로 반환한다(부모 = 자식, 분할 없음).
    초과하면 `ceil(토큰/CHILD_TARGET_TOKENS)` 개로 **균등 분할**하되,
    경계는 목표 지점에서 가장 가까운 **문장 끝**으로 확정한다.

    균등 분할하는 이유: 256 마다 기계적으로 끊으면 마지막에 짜투리 조각이 남는데,
    그런 조각은 벡터로서 쓸모가 없다.
    """
    if not text or not text.strip():
        return []

    total = count_tokens(text)
    if total <= MAX_TOKENS:
        return [text]

    n_parts = math.ceil(total / CHILD_TARGET_TOKENS)
    spans = sentence_spans(text)

    if len(spans) < 2:
        # 문장 경계가 없음 — 강제 분할
        logger.debug("문장 경계 없음 → 토큰 강제 분할 (%d토큰 → %d조각)", total, n_parts)
        return _force_split_by_tokens(text, n_parts)

    # 문장별 토큰 수를 누적하며 목표 지점에 가장 가까운 문장 끝에서 끊는다.
    sent_tokens = [count_tokens(text[a:b]) for a, b in spans]
    target = total / n_parts

    parts: list[str] = []
    cur_start_idx = 0
    acc = 0
    for i, tk in enumerate(sent_tokens):
        acc += tk
        remaining_parts = n_parts - len(parts)
        is_last_sentence = i == len(sent_tokens) - 1
        if is_last_sentence:
            break
        # 남은 조각 수보다 남은 문장이 적으면 더 쪼갤 수 없으므로 계속 누적
        if remaining_parts <= 1:
            continue
        # 이번 문장까지 넣었을 때와 안 넣었을 때 중 target 에 가까운 쪽 선택
        if acc >= target:
            without = acc - tk
            if without > 0 and abs(without - target) < abs(acc - target):
                # 직전 문장까지가 더 가까움 → 현재 문장은 다음 조각으로
                parts.append(text[spans[cur_start_idx][0] : spans[i - 1][1]])
                cur_start_idx = i
                acc = tk
            else:
                parts.append(text[spans[cur_start_idx][0] : spans[i][1]])
                cur_start_idx = i + 1
                acc = 0

    # 남은 문장 전부를 마지막 조각으로
    if cur_start_idx < len(spans):
        parts.append(text[spans[cur_start_idx][0] : spans[-1][1]])

    parts = [p for p in parts if p.strip()]

    # 균등 분할했어도 문장 하나가 통으로 길면 여전히 한도를 넘을 수 있다 → 그 조각만 강제 분할
    out: list[str] = []
    for p in parts:
        if count_tokens(p) > MAX_TOKENS:
            sub_n = math.ceil(count_tokens(p) / CHILD_TARGET_TOKENS)
            out.extend(_force_split_by_tokens(p, sub_n))
        else:
            out.append(p)
    return out or [text]
