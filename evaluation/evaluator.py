"""채점용 LLM/임베딩 + 메트릭 구성 — 전부 로컬 LM Studio(PIPA).

설정값은 기존 app.config 단일 진입점에서 로드(신규 .env 키 0개, 하드코딩 금지 — CLAUDE.md).
실행별 오버라이드는 인자로만 받는다(env 추가 안 함).

메트릭 진단 축:
  - 검색(청킹/검색 전략): LLMContextPrecisionWithoutReference, LLMContextRecall(정답 필요)
  - 생성: Faithfulness(환각), ResponseRelevancy(질문-답변 적합성)

NOTE(버전): ragas 0.4.3에 핀 고정. metrics는 classic 경로(ragas.metrics.*)를 쓴다.
0.4.3에서 deprecation 경고가 뜨지만(→ ragas.metrics.collections), classic evaluate()와
함께 동작하는 건 이쪽이라 핀 고정 환경에서 의도적으로 사용. (ragas 1.0 이전 환경 한정)
"""
from __future__ import annotations

import warnings

from langchain_openai import ChatOpenAI, OpenAIEmbeddings

with warnings.catch_warnings():
    warnings.simplefilter("ignore", DeprecationWarning)
    from ragas.embeddings import LangchainEmbeddingsWrapper
    from ragas.llms import LangchainLLMWrapper
    from ragas.metrics import (
        Faithfulness,
        LLMContextPrecisionWithoutReference,
        LLMContextRecall,
        ResponseRelevancy,
    )


def build_evaluator(
    base_url: str | None = None,
    chat_model: str | None = None,
    embed_model: str | None = None,
    api_key: str = "lm-studio",
):
    """로컬 LM Studio(OpenAI 호환) 기반 채점 LLM/임베딩 래퍼를 만든다.

    base_url/chat_model/embed_model 미지정 시 app.config 값을 사용.
    """
    from app.config import CHAT_MODEL, EMBEDDING_MODEL, LMSTUDIO_BASE_URL

    base_url = base_url or LMSTUDIO_BASE_URL
    chat_model = chat_model or CHAT_MODEL
    embed_model = embed_model or EMBEDDING_MODEL

    eval_llm = LangchainLLMWrapper(
        ChatOpenAI(model=chat_model, base_url=base_url, api_key=api_key, temperature=0)
    )
    eval_emb = LangchainEmbeddingsWrapper(
        OpenAIEmbeddings(
            model=embed_model,
            base_url=base_url,
            api_key=api_key,
            check_embedding_ctx_length=False,  # 비 OpenAI 엔드포인트 호환
        )
    )
    return eval_llm, eval_emb


def select_metrics(has_ground_truth: bool) -> list:
    """정답 유무로 메트릭 분기. 정답 없으면 reference-free 3종만."""
    metrics = [
        Faithfulness(),                        # 생성: 환각 여부
        ResponseRelevancy(),                   # 생성: 답변-질문 적합성
        LLMContextPrecisionWithoutReference(), # 검색: 결과 유용성(정답 불필요)
    ]
    if has_ground_truth:
        metrics.append(LLMContextRecall())     # 검색: 정답 커버리지(정답 필요)
    return metrics
