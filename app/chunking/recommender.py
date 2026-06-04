"""PDF를 Gemini API에 직접 전송해 청킹 전략을 추천한다.

PDF inline (base64) 입력을 지원하는 Gemini 모델을 단발성 호출한다.
- 입력: PDF 바이트 + 파일명
- 출력: Recommendation(strategy, reason) — pydantic_ai의 structured output으로 강제

다른 청킹/임베딩/Chat 흐름과 독립. 모델 인스턴스는 app.config의 recommend_model 단일 진입점에서만.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel
from pydantic_ai import Agent, BinaryContent

from app.config import recommend_model


class Recommendation(BaseModel):
    strategy: Literal["docling_hybrid", "langchain_semantic"]
    reason: str


RECOMMEND_SYSTEM_PROMPT = """\
당신은 PDF 문서를 분석해 두 청킹 전략 중 더 적합한 것을 추천하는 전문가입니다.

전략 1 — Docling Hybrid (docling_hybrid):
- 문서 구조(헤더, 문단, 표, 그림)를 단위로 분할 + 토큰 한도 보정
- 빠르고 안정적
- 적합: 명확한 헤더 계층, 코드·표·그림이 잘 구분된 기술 문서, API 레퍼런스, 매뉴얼

전략 2 — LangChain Semantic (langchain_semantic):
- 문장 단위 임베딩 유사도로 의미 변화점에서 분할 (큰 의미 덩어리 보존)
- 임베딩 호출 비용 큼, 느림
- 적합: 헤더가 약하거나 자유로운 서술형 문서, 에세이, 논문, 스토리, 인터뷰 기록

주어진 PDF를 직접 살펴보고 어느 전략이 더 적합한지 판단한 뒤,
그 이유를 한국어 2~3문장으로 설명하세요.
추측이 아니라 PDF에 실제로 보이는 시각적·구조적 근거(헤더 단계, 표/그림 빈도, 문장 흐름 등)를 들어 답변하세요.
"""


async def recommend_strategy(pdf_bytes: bytes, filename: str) -> Recommendation:
    """PDF 바이트를 Gemini에 inline 전송해 청킹 전략을 추천받는다.

    recommend_model이 None이면(=GOOGLE_API_KEY 미설정) RuntimeError를 raise.
    호출자는 라우터에서 catch해 HTTP 503으로 변환한다.
    """
    if recommend_model is None:
        raise RuntimeError("추천 모델이 구성되지 않았습니다. GOOGLE_API_KEY를 설정하세요.")

    agent: Agent[None, Recommendation] = Agent(
        recommend_model,
        output_type=Recommendation,
        system_prompt=RECOMMEND_SYSTEM_PROMPT,
    )
    result = await agent.run(
        [
            f"파일명: {filename}",
            BinaryContent(data=pdf_bytes, media_type="application/pdf"),
        ]
    )
    return result.output
