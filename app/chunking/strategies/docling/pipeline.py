"""Docling PDF 파이프라인 옵션 빌더."""
from __future__ import annotations

import os

from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import (
    AcceleratorDevice,
    AcceleratorOptions,
    PdfPipelineOptions,
)
from docling.document_converter import DocumentConverter, PdfFormatOption

# Docling 추론에 쓸 디바이스. 기본은 CPU — Apple Silicon MPS는 float64 미지원이라
# 일부 모델 추론에서 "Cannot convert a MPS Tensor to float64" 로 죽는 케이스가 있다.
# 명시적으로 다른 디바이스를 쓰고 싶다면 .env 에서 DOCLING_DEVICE=mps|cuda|auto 로 변경.
_DEVICE_ENV = os.environ.get("DOCLING_DEVICE", "cpu").lower()
_DEVICE_MAP = {
    "auto": AcceleratorDevice.AUTO,
    "cpu": AcceleratorDevice.CPU,
    "cuda": AcceleratorDevice.CUDA,
    "mps": AcceleratorDevice.MPS,
    "xpu": AcceleratorDevice.XPU,
}
DOCLING_DEVICE: AcceleratorDevice = _DEVICE_MAP.get(_DEVICE_ENV, AcceleratorDevice.CPU)


def build_pipeline_options(do_ocr: bool = False) -> PdfPipelineOptions:
    opts = PdfPipelineOptions()
    opts.do_ocr = do_ocr
    opts.do_picture_description = False  # 외부 Pydantic AI로 대체
    opts.do_picture_classification = True  # DocumentFigureClassifier로 logo/chart/signature 등 분류
    opts.generate_picture_images = True
    opts.images_scale = 2.0
    opts.accelerator_options = AcceleratorOptions(device=DOCLING_DEVICE)
    return opts


def build_converter(do_ocr: bool = False) -> DocumentConverter:
    opts = build_pipeline_options(do_ocr=do_ocr)
    return DocumentConverter(
        format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=opts)}
    )
