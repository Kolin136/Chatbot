"""이미지/표를 자연어 설명문으로 변환하는 Pydantic AI 어노테이터.

모델은 환경변수 `GEMINI_MODEL`을 따른다 (app/config.py와 동일한 키/기본값).
Pydantic AI 인터페이스라 모델 이름만 바꾸면 다른 LLM(OpenAI/Anthropic 등)으로 교체 가능.
"""
from __future__ import annotations

import io
import logging
import os
import time
from typing import TYPE_CHECKING

from pydantic_ai import Agent, BinaryContent

if TYPE_CHECKING:
    from PIL.Image import Image

logger = logging.getLogger(__name__)

# app/config.py 와 동일한 키/기본값 — config.py는 chromadb 의존성이 있어 직접 import하지 않음
DEFAULT_MODEL = os.environ.get("GEMINI_MODEL", "gemini-3-flash-preview")

# Gemini free tier 분당 한도 회피용 호출 간격 (초). 환경변수로 조정 가능.
# 청킹 시 이미지/표 → VLM 설명문 호출 간격.
DEFAULT_MIN_INTERVAL_SEC = float(os.environ.get("CHUNK_VLM_INTERVAL_SEC", "13"))


IMAGE_SYSTEM_PROMPT = (
    "당신은 기술 문서의 그림/다이어그램을 한국어로 정확하게 설명하는 분석가입니다. "
    "그림의 종류(아키텍처 다이어그램, 차트, 사진 등), 구성 요소, 관계, 핵심 메시지를 "
    "3~5문장으로 간결하게 설명하세요. 추측하지 말고 보이는 것만 기술하세요."
)

TABLE_SYSTEM_PROMPT = (
    "당신은 기술 문서의 표를 한국어로 정확하게 설명하는 분석가입니다. "
    "표가 무엇에 대한 데이터인지, 어떤 컬럼들이 있는지, 핵심 패턴이나 결과를 "
    "3~5문장으로 간결하게 설명하세요. 구체적인 수치는 그대로 인용하세요."
)


class Annotator:
    """이미지/표 → 자연어 설명문 생성기.

    Pydantic AI 인터페이스 사용 — `model_name`만 교체하면 다른 LLM 사용 가능.
    예) "google-gla:gemini-2.0-flash" → "openai:gpt-4o" → "anthropic:claude-sonnet-4-5"
    """

    def __init__(
        self,
        model_name: str | None = None,
        min_interval_sec: float = DEFAULT_MIN_INTERVAL_SEC,
    ) -> None:
        self.model_name = model_name or DEFAULT_MODEL
        self._min_interval = min_interval_sec
        self._last_call_time = 0.0
        self._image_agent: Agent[None, str] = Agent(
            model=self.model_name,
            system_prompt=IMAGE_SYSTEM_PROMPT,
        )
        self._table_agent: Agent[None, str] = Agent(
            model=self.model_name,
            system_prompt=TABLE_SYSTEM_PROMPT,
        )

    def _throttle(self) -> None:
        """직전 호출로부터 min_interval_sec 만큼 간격 강제. 첫 호출은 즉시 통과."""
        if self._last_call_time == 0.0:
            self._last_call_time = time.monotonic()
            return
        elapsed = time.monotonic() - self._last_call_time
        if elapsed < self._min_interval:
            wait = self._min_interval - elapsed
            logger.info("rate limit: %.1f초 대기", wait)
            time.sleep(wait)
        self._last_call_time = time.monotonic()

    def describe_image(self, img: "Image") -> str:
        """PIL 이미지를 자연어로 설명."""
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        png_bytes = buf.getvalue()
        self._throttle()
        try:
            result = self._image_agent.run_sync(
                [
                    "다음 그림을 한국어로 설명해 주세요.",
                    BinaryContent(data=png_bytes, media_type="image/png"),
                ]
            )
            return result.output.strip()
        except Exception as exc:
            logger.warning("이미지 설명 생성 실패: %s", exc)
            return ""

    def describe_table(self, markdown_table: str) -> str:
        """Markdown 형식의 표를 자연어로 설명."""
        self._throttle()
        try:
            result = self._table_agent.run_sync(
                f"다음 표를 한국어로 설명해 주세요:\n\n{markdown_table}"
            )
            return result.output.strip()
        except Exception as exc:
            logger.warning("표 설명 생성 실패: %s", exc)
            return ""
