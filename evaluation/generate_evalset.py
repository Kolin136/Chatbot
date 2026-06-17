"""평가셋 자동 생성 — Gemini에 원본 PDF를 inline 전송해 질문+정답을 뽑는다.

app/chunking/recommender.py 패턴 재사용(pydantic_ai Agent + BinaryContent + Structured Output).
채점이 아니라 '평가셋 생성'에만 Gemini를 쓴다(1회, dev-time). 채점은 로컬 LM Studio.

⚠️ 한국어 합성은 불안정할 수 있다 → 생성 후 사람이 eval_set.json을 훑어 깨진 항목을 거른다.
⚠️ Gemini로 PDF가 외부 전송된다(개인/가명정보 주의). GOOGLE_API_KEY는 기존 추천 기능과 동일 키.

예)
  .venv/bin/python -m evaluation.generate_evalset \
      --pdf chunking-results/<doc>/<원본>.pdf --n 12 --out evaluation/eval_set.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from pydantic import BaseModel, Field
from pydantic_ai import Agent, BinaryContent


class EvalItem(BaseModel):
    question: str = Field(description="문서 내용으로 답할 수 있는 구체적 질문(한국어)")
    ground_truth: str = Field(description="문서 근거에 기반한 간결한 모범답안(한국어)")


class EvalSet(BaseModel):
    items: list[EvalItem]


def _system_prompt(n: int) -> str:
    return f"""\
당신은 주어진 PDF 문서로 RAG 평가용 질문-정답 세트를 만드는 전문가입니다.

규칙:
- 정확히 {n}개의 (질문, 모범답안) 쌍을 한국어로 생성하세요.
- 질문은 반드시 이 문서의 내용으로만 답할 수 있어야 합니다(외부 지식·추측 금지).
- 표/그림/수치/고유명사 등 다양한 유형을 섞되, 너무 사소하거나 모호한 질문은 피하세요.
- 모범답안(ground_truth)은 문서에 실제로 적힌 근거에 기반해 간결하게(1~3문장) 작성하세요.
- 문서에 없는 내용을 지어내지 마세요. 근거가 약하면 그런 질문은 만들지 마세요.
"""


async def generate_from_bytes(pdf_bytes: bytes, filename: str, n: int) -> EvalSet:
    """PDF 바이트를 Gemini에 inline 전송해 평가셋을 생성한다. (CLI·웹 공용 코어)

    recommend_model이 None(=GOOGLE_API_KEY 미설정)이면 RuntimeError.
    """
    from app.config import recommend_model  # Gemini 모델 단일 진입점

    if recommend_model is None:
        raise RuntimeError(
            "Gemini 모델이 구성되지 않았습니다. .env의 GOOGLE_API_KEY를 설정하세요(추천 기능과 동일 키)."
        )

    agent: Agent[None, EvalSet] = Agent(
        recommend_model,
        output_type=EvalSet,
        system_prompt=_system_prompt(n),
    )
    result = await agent.run(
        [
            f"파일명: {filename}. 이 PDF로 평가셋 {n}개를 만들어 주세요.",
            BinaryContent(data=pdf_bytes, media_type="application/pdf"),
        ]
    )
    return result.output


async def generate(pdf_path: Path, n: int) -> EvalSet:
    """CLI용 — 파일 경로에서 바이트를 읽어 generate_from_bytes 호출."""
    return await generate_from_bytes(pdf_path.read_bytes(), pdf_path.name, n)


def main() -> int:
    import asyncio

    p = argparse.ArgumentParser(description="Gemini로 RAG 평가셋(질문+정답) 자동 생성")
    p.add_argument("--pdf", required=True, type=Path, help="원본 PDF 경로")
    p.add_argument("--n", type=int, default=12, help="생성할 질문 수")
    p.add_argument("--out", type=Path, default=Path("evaluation/eval_set.json"))
    args = p.parse_args()

    if not args.pdf.exists():
        raise SystemExit(f"PDF를 찾을 수 없습니다: {args.pdf}")

    eval_set = asyncio.run(generate(args.pdf, args.n))
    data = [{"question": it.question, "ground_truth": it.ground_truth} for it in eval_set.items]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"생성됨: {args.out} ({len(data)}문항)")
    print("⚠️ 반드시 사람이 훑어보고 깨지거나 근거 약한 항목을 직접 제거/수정하세요.")
    print("   한국어 합성은 불안정할 수 있습니다. 검수 후 run_eval에 사용하세요.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
