"""Docling PDF 파이프라인 옵션 빌더."""
from __future__ import annotations

from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.document_converter import DocumentConverter, PdfFormatOption


def build_pipeline_options(do_ocr: bool = False) -> PdfPipelineOptions:
    opts = PdfPipelineOptions()
    opts.do_ocr = do_ocr
    opts.do_picture_description = False  # 외부 Pydantic AI로 대체
    opts.do_picture_classification = True  # DocumentFigureClassifier로 logo/chart/signature 등 분류
    opts.generate_picture_images = True
    opts.images_scale = 2.0
    return opts


def build_converter(do_ocr: bool = False) -> DocumentConverter:
    opts = build_pipeline_options(do_ocr=do_ocr)
    return DocumentConverter(
        format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=opts)}
    )
