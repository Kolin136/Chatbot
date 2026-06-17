"""어댑터 — 기존 RAG 파이프라인을 `answer(q) -> (answer, contexts)` 하나로 감싼다.

OCP: app/ 코드는 호출만 하고 수정하지 않는다. 청킹·저장은 컬렉션에 이미 굳어 있으므로
RAGConfig는 컬렉션명 + 검색모드(hybrid)만 실제로 제어하고, chunking/storage는 리포트용 라벨.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class RAGConfig:
    label: str
    collection_name: str
    hybrid: bool = False
    # 아래 둘은 컬렉션 색인 시점에 이미 결정됨 — 표시/리포트용 라벨일 뿐 동작에 영향 없음
    chunking: str = ""  # "hybrid" | "semantic"
    storage: str = ""   # "raw" | "summary"


class Pipeline(Protocol):
    async def answer(self, question: str) -> tuple[str, list[str]]:
        """질문 → (생성 답변, 검색된 컨텍스트 텍스트 리스트)."""
        ...


class RealPipeline:
    """기존 검색(`search_relevant_context`) + 생성(`generate_response`)을 조합.

    app.* 는 메서드 내부에서 지연 import — MockPipeline만 쓰는 경로(LM Studio·Chroma 불필요)에서
    불필요한 의존성 로딩을 피한다.
    """

    def __init__(self, config: RAGConfig):
        self.config = config

    async def answer(self, question: str) -> tuple[str, list[str]]:
        from app.llm import generate_response
        from app.rag import search_relevant_context
        from app.retrieval import FINAL_TOP_N  # dense·hybrid 공통 top-k (코드에 이미 고정)

        retrieved = await search_relevant_context(
            question,
            self.config.collection_name,
            n_results=FINAL_TOP_N,
            hybrid=self.config.hybrid,
        )
        contexts = [c.text for c in retrieved]  # chat.py와 동일하게 .text 사용
        _session_id, answer = await generate_response(
            None, contexts, question  # session_id=None → 매 질문 독립(히스토리 오염 방지)
        )
        return answer, contexts


class MockPipeline:
    """고정 답변/컨텍스트를 돌려주는 더미 — 하니스 자체를 LM Studio·Chroma 없이 검증.

    qa: {question: {"answer": str, "contexts": [str, ...]}} 매핑(선택). 없으면 자동 생성.
    """

    def __init__(self, config: RAGConfig | None = None, qa: dict[str, dict] | None = None):
        self.config = config
        self._qa = qa or {}

    async def answer(self, question: str) -> tuple[str, list[str]]:
        item = self._qa.get(question)
        if item:
            return item["answer"], list(item["contexts"])
        return (
            f"[mock] {question} 에 대한 고정 답변입니다.",
            [f"[mock context] {question} 와 관련된 가짜 컨텍스트입니다."],
        )


def build_pipeline(config: RAGConfig) -> Pipeline:
    """config로 실제 파이프라인 어댑터를 조립해 반환."""
    return RealPipeline(config)
