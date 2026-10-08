"""PDF를 로컬 VLM에 보여주고 청킹 전략을 추천받는다.

PDF를 페이지 이미지 + 텍스트 레이어로 변환해(app/pdf_pages.py) LM Studio에 전송한다.
상용 API가 내부적으로 하는 전처리를 직접 수행하는 것 — 문서가 외부로 나가지 않는다.

- 입력: PDF 바이트 + 파일명
- 출력: Recommendation(strategy, reason) — pydantic_ai의 structured output으로 강제

다른 청킹/임베딩/Chat 흐름과 독립. 모델은 app.config의 chat_model(LM Studio) 단일 진입점.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel
from pydantic_ai import Agent, NativeOutput

from app.pdf_pages import build_vlm_prompt

from app.config import chat_model


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

주어진 문서의 페이지 이미지와 텍스트를 직접 살펴보고 어느 전략이 더 적합한지 판단한 뒤,
그 이유를 한국어 2~3문장으로 설명하세요.
추측이 아니라 문서에 실제로 보이는 시각적·구조적 근거(헤더 단계, 표/그림 빈도, 문장 흐름 등)를 들어 답변하세요.
"""


async def recommend_strategy(pdf_bytes: bytes, filename: str) -> Recommendation:
    """PDF를 페이지 이미지로 변환해 로컬 VLM에 보내고 청킹 전략을 추천받는다.

    LM Studio 미접속·모델 미로드 등으로 호출이 실패하면 예외가 그대로 올라간다.
    호출자(라우터)가 catch해 HTTP 503으로 변환한다.
    """
    # NativeOutput(= LM Studio의 response_format: json_schema) 명시.
    # pydantic_ai 기본값인 tool-call 경로는 로컬 모델에서 필드 누락이 발생한다
    # (evaluation/generate_evalset.py 참고). 두 기능의 출력 경로를 통일한다.
    agent: Agent[None, Recommendation] = Agent(
        chat_model,
        output_type=NativeOutput(Recommendation),
        system_prompt=RECOMMEND_SYSTEM_PROMPT,
    )
    prompt = await build_vlm_prompt(
        pdf_bytes, filename, "이 문서에 어떤 청킹 전략이 적합한지 판단해 주세요."
    )
    result = await agent.run(prompt)
    return result.output
