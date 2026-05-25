"""Docling 기반 청킹 전략 (공통 코드 + 청커별 하위 패키지).

구조:
- 공통 (모든 청커가 공유):
    pipeline.py       — PDF → DoclingDocument 변환
    serializers.py    — 청크 직렬화 시 그림/표 설명문 주입 (모든 docling 청커 호환)
    exporters.py      — 원본 PNG/CSV/HTML 저장 + mapping.json
- 청커별:
    hybrid/           — Docling HybridChunker

향후 다른 docling 청커(HierarchicalChunker, LineBasedTokenChunker 등) 추가 시
같은 패턴으로 `hierarchical/`, `line_based/` 등을 만들고 아래 import만 분기하면 된다.

공식 문서:
- https://docling-project.github.io/docling/concepts/chunking/
- https://docling-project.github.io/docling/examples/hybrid_chunking/
"""
# 공통
from app.chunking.strategies.docling.exporters import (
    save_full_markdown,
    save_picture_images,
    save_tables,
    write_mapping_json,
)
from app.chunking.strategies.docling.pipeline import build_converter
from app.chunking.strategies.docling.serializers import (
    AnnotationSerializerProvider,
    ExternalAnnotationPictureSerializer,
    ExternalAnnotationTableSerializer,
)

# Hybrid 청커 (현재 유일한 청커)
from app.chunking.strategies.docling.hybrid import (
    DEFAULT_EMBED_MODEL,
    DEFAULT_MAX_TOKENS,
    build_chunker,
    write_chunks_jsonl,
)

__all__ = [
    "build_converter",
    "build_chunker",
    "write_chunks_jsonl",
    "DEFAULT_EMBED_MODEL",
    "DEFAULT_MAX_TOKENS",
    "save_full_markdown",
    "save_picture_images",
    "save_tables",
    "write_mapping_json",
    "AnnotationSerializerProvider",
    "ExternalAnnotationPictureSerializer",
    "ExternalAnnotationTableSerializer",
]
