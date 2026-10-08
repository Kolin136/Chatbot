"""평가셋 자동 생성 — 로컬 VLM에 PDF 페이지를 보여주고 질문+정답을 뽑는다.

app/chunking/recommender.py 패턴 재사용(pydantic_ai Agent + 페이지 이미지 + Structured Output).
PDF는 페이지 이미지 + 텍스트 레이어로 변환해 LM Studio에 보낸다(app/pdf_pages.py) —
문서가 외부로 나가지 않는다.

⚠️ 로컬 모델은 상용 모델보다 한국어 합성이 불안정하다 → 생성 후 사람이 반드시 훑어
   깨진 항목·문서에 없는 내용을 지어낸 항목을 거른다. 평가셋 품질이 곧 평가 신뢰도다.

예)
  .venv/bin/python -m evaluation.generate_evalset \
      --pdf chunking-results/<doc>/<원본>.pdf --n 12 --out evaluation/eval_set.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from pydantic import BaseModel, Field
from pydantic_ai import Agent, NativeOutput

from app.pdf_pages import build_vlm_prompt


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
    """PDF를 페이지 이미지로 변환해 로컬 VLM에 보내고 평가셋을 생성한다. (CLI·웹 공용 코어)

    LM Studio 미접속 등으로 실패하면 예외가 그대로 올라간다(라우터가 503으로 변환).
    """
    from app.config import chat_model  # LM Studio 모델 단일 진입점

    # NativeOutput(= LM Studio의 response_format: json_schema) 을 명시한다.
    # pydantic_ai 기본값은 tool-call 경로인데, 로컬 gemma가 tool 인자를 채울 때
    # 중첩 리스트의 두 번째 필드(ground_truth)를 빠뜨려 ValidationError 가 났다.
    # 같은 모델이 JSON 스키마 모드에서는 동일 스키마를 정확히 채운다(실측).
    agent: Agent[None, EvalSet] = Agent(
        chat_model,
        output_type=NativeOutput(EvalSet),
        system_prompt=_system_prompt(n),
    )
    prompt = await build_vlm_prompt(
        pdf_bytes, filename, f"이 문서로 평가셋 {n}개를 만들어 주세요."
    )
    result = await agent.run(prompt)
    return result.output


async def generate(pdf_path: Path, n: int) -> EvalSet:
    """CLI용 — 파일 경로에서 바이트를 읽어 generate_from_bytes 호출."""
    return await generate_from_bytes(pdf_path.read_bytes(), pdf_path.name, n)


def main() -> int:
    import asyncio

    p = argparse.ArgumentParser(description="로컬 VLM으로 RAG 평가셋(질문+정답) 자동 생성")
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
