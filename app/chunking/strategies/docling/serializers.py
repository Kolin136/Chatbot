"""외부 description dict를 참조해 청크에 박는 커스텀 serializer.

공식 docling 패턴 (Examples → Advanced chunking & serialization) 의
`AnnotationPictureSerializer` 구조를 따르되, description의 출처를
외부 dict(self_ref → 설명문)로 받음. Pydantic AI로 미리 생성한 설명을 주입할 수 있도록.
"""
from __future__ import annotations

from typing import Any

from docling_core.transforms.chunker.hierarchical_chunker import (
    ChunkingDocSerializer,
    ChunkingSerializerProvider,
)
from docling_core.transforms.serializer.base import (
    BaseDocSerializer,
    SerializationResult,
)
from docling_core.transforms.serializer.common import create_ser_result
from docling_core.transforms.serializer.markdown import (
    MarkdownPictureSerializer,
    MarkdownTableSerializer,
)
from docling_core.types.doc.document import (
    DoclingDocument,
    PictureItem,
    TableItem,
)
from typing_extensions import override


class ExternalAnnotationPictureSerializer(MarkdownPictureSerializer):
    """외부에서 만들어둔 picture description을 청크 텍스트에 박음."""

    def __init__(self, descriptions: dict[str, str]) -> None:
        super().__init__()
        self._descriptions = descriptions

    @override
    def serialize(
        self,
        *,
        item: PictureItem,
        doc_serializer: BaseDocSerializer,
        doc: DoclingDocument,
        **kwargs: Any,
    ) -> SerializationResult:
        desc = self._descriptions.get(item.self_ref, "")
        if desc:
            text = f"Picture description: {desc}"
        else:
            text = "<!-- image -->"
        text = doc_serializer.post_process(text=text)
        return create_ser_result(text=text, span_source=item)


class ExternalAnnotationTableSerializer(MarkdownTableSerializer):
    """외부 description + 원본 markdown 표 둘 다 청크에 넣음.

    표는 정확한 수치 보존이 중요하므로 markdown 표는 그대로 유지하고,
    그 앞에 자연어 설명문을 prepend.
    """

    def __init__(self, descriptions: dict[str, str]) -> None:
        super().__init__()
        self._descriptions = descriptions

    @override
    def serialize(
        self,
        *,
        item: TableItem,
        doc_serializer: BaseDocSerializer,
        doc: DoclingDocument,
        **kwargs: Any,
    ) -> SerializationResult:
        md_result = super().serialize(
            item=item, doc_serializer=doc_serializer, doc=doc, **kwargs
        )
        desc = self._descriptions.get(item.self_ref, "")
        if desc:
            combined = f"Table description: {desc}\n{md_result.text}"
        else:
            combined = md_result.text
        combined = doc_serializer.post_process(text=combined)
        return create_ser_result(text=combined, span_source=item)


class AnnotationSerializerProvider(ChunkingSerializerProvider):
    """HybridChunker에 주입할 serializer provider."""

    def __init__(
        self,
        pic_descriptions: dict[str, str],
        table_descriptions: dict[str, str],
    ) -> None:
        self._pic_descriptions = pic_descriptions
        self._table_descriptions = table_descriptions

    def get_serializer(self, doc: DoclingDocument) -> ChunkingDocSerializer:
        return ChunkingDocSerializer(
            doc=doc,
            picture_serializer=ExternalAnnotationPictureSerializer(
                self._pic_descriptions
            ),
            table_serializer=ExternalAnnotationTableSerializer(
                self._table_descriptions
            ),
        )
