"""고정 크기 청킹 전략 — 통합 텍스트를 N토큰씩 균등 분할 (baseline)."""
from app.chunking.strategies.fixed_size.chunker import (
    DEFAULT_CHUNK_SIZE,
    DEFAULT_TOKENIZER_MODEL,
    STRATEGY_NAME,
    FixedSizeChunker,
    build_chunker,
    write_chunks_jsonl,
)

__all__ = [
    "DEFAULT_CHUNK_SIZE",
    "DEFAULT_TOKENIZER_MODEL",
    "STRATEGY_NAME",
    "FixedSizeChunker",
    "build_chunker",
    "write_chunks_jsonl",
]
