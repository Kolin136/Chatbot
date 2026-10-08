"""PDF → 페이지 이미지 + 텍스트 레이어 (로컬 VLM 입력용).

왜 필요한가:
    상용 API(Claude/GPT/Gemini)가 PDF를 "직접 읽는" 게 아니다. API 서버가 각 페이지를
    이미지로 렌더링하고 텍스트 레이어를 함께 추출해 비전 모델에 넣는다. 그 전처리를
    여기서 직접 수행해, 외부로 문서를 보내지 않고 로컬 VLM으로 같은 일을 한다.

    pydantic_ai에 PDF 바이트를 media_type="application/pdf"로 넘기면 OpenAI Files 스타일
    file_data 파트로 변환되는데, LM Studio는 이를 처리하지 못한다. 반드시 이미지여야 한다.

이미지와 텍스트를 둘 다 보내는 이유:
    이미지는 레이아웃·표·그림 구조를 보여주고, 텍스트 레이어는 작은 글씨나 숫자를
    정확하게 전달한다. 로컬 모델은 상용 모델보다 OCR 정확도가 낮아 텍스트 동봉이 특히 유효하다.
"""
from __future__ import annotations

import asyncio
import io
import logging
import os

from pydantic_ai import BinaryContent

logger = logging.getLogger(__name__)

# 페이지 렌더 해상도(긴 변 기준 px). Gemini가 PDF 페이지를 다루는 규격과 유사하게 잡았다.
# 키우면 작은 글씨 인식이 좋아지지만 이미지 토큰이 늘어 컨텍스트를 빨리 먹는다.
RENDER_MAX_PX = int(os.environ.get("PDF_PAGE_RENDER_MAX_PX", "1024"))

_TEXT_LAYER_HEADER = "[문서에서 추출한 텍스트 레이어]"


def _render_sync(pdf_bytes: bytes, max_px: int) -> tuple[list[bytes], str]:
    """동기 렌더링 — 호출자가 asyncio.to_thread로 감싼다.

    반환: (페이지별 PNG 바이트 목록, 전체 텍스트 레이어)
    """
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(pdf_bytes)
    try:
        images: list[bytes] = []
        texts: list[str] = []
        for i in range(len(doc)):
            page = doc[i]
            w, h = page.get_size()
            scale = max_px / max(w, h) if max(w, h) > 0 else 1.0
            img = page.render(scale=scale).to_pil()
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            images.append(buf.getvalue())

            try:
                txt = page.get_textpage().get_text_range().strip()
            except Exception:
                txt = ""
            if txt:
                texts.append(f"--- p.{i + 1} ---\n{txt}")
        return images, "\n\n".join(texts)
    finally:
        doc.close()


async def render_pdf_pages(
    pdf_bytes: bytes, max_px: int = RENDER_MAX_PX
) -> tuple[list[bytes], str]:
    """PDF 바이트 → (페이지 PNG 목록, 텍스트 레이어). CPU 작업이라 별도 스레드에서 실행."""
    images, text = await asyncio.to_thread(_render_sync, pdf_bytes, max_px)
    logger.info(
        "PDF 렌더링 완료: %d페이지, 이미지 %.1fMB, 텍스트 %d자",
        len(images), sum(len(b) for b in images) / 1024 / 1024, len(text),
    )
    return images, text


async def build_vlm_prompt(
    pdf_bytes: bytes, filename: str, instruction: str
) -> list:
    """PDF → pydantic_ai agent.run() 에 넘길 user content 목록.

    형태: [지시문 + 파일명 + 텍스트 레이어, PNG, PNG, ...]
    텍스트를 먼저 두어 모델이 맥락을 잡은 뒤 이미지를 보게 한다.
    """
    images, text = await render_pdf_pages(pdf_bytes)
    if not images:
        raise RuntimeError(f"PDF에서 페이지를 읽지 못했습니다: {filename}")

    head = f"{instruction}\n\n파일명: {filename} (총 {len(images)}페이지)"
    if text:
        head += f"\n\n{_TEXT_LAYER_HEADER}\n{text}"

    # 텍스트 레이어가 이미지보다 토큰을 훨씬 많이 먹는다(실측: 6페이지 문서에서 텍스트
    # 18k토큰 vs 이미지 3.4k토큰). 컨텍스트 초과로 실패하면 이 로그가 원인을 가리킨다.
    logger.info(
        "VLM 프롬프트 조립: %d페이지, 텍스트 %d자(약 %dk토큰 추정), 이미지 %.1fMB",
        len(images), len(text), len(text) // 2000,
        sum(len(b) for b in images) / 1024 / 1024,
    )

    parts: list = [head]
    parts.extend(
        BinaryContent(data=png, media_type="image/png") for png in images
    )
    return parts
