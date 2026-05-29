"""LangChain SemanticChunker 청킹 전략.

공식 문서:
- https://api.python.langchain.com/en/latest/text_splitter/langchain_experimental.text_splitter.SemanticChunker.html

분할 방식 (`breakpoint_threshold_type`):
  - "percentile" (기본): 코사인 거리 백분위수 (기본 amount=95)
  - "standard_deviation": 평균+표준편차 (기본 amount=3)
  - "interquartile": 사분위수 (기본 amount=1.5)
"""
from app.chunking.strategies.langchain.semantic.chunker import (
    build_chunker,
    write_chunks_jsonl,
)
from app.chunking.strategies.langchain.semantic.embeddings_adapter import (
    PydanticAIEmbeddingsAdapter,
)

__all__ = [
    "build_chunker",
    "write_chunks_jsonl",
    "PydanticAIEmbeddingsAdapter",
]
