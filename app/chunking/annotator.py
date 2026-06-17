"""이미지/표를 자연어 설명문으로 변환하는 Pydantic AI 어노테이터.

기본 모델은 `app.config.chat_model` (LM Studio OpenAI 호환 백엔드).
호출자가 다른 pydantic_ai 모델 인스턴스를 명시적으로 넘기는 것도 허용.
"""
from __future__ import annotations

import asyncio
import io
import logging
import time
from typing import TYPE_CHECKING, Any

from pydantic_ai import Agent, BinaryContent

from app.config import CHUNK_VLM_INTERVAL_SEC, chat_model

if TYPE_CHECKING:
    from PIL.Image import Image

logger = logging.getLogger(__name__)

DEFAULT_MIN_INTERVAL_SEC = CHUNK_VLM_INTERVAL_SEC
"""청킹 시 이미지/표 → VLM 설명문 호출 간격(초). LM Studio는 자체 한도 없음 — 0 권장."""


DEFAULT_LANG = "ko"

# 문서 언어(ko/en)별 VLM 시스템 프롬프트 — 사용자가 업로드 시 선택한 lang으로 분기.
_IMAGE_SYSTEM_PROMPTS = {
    "ko": (
        "당신은 기술 문서의 그림/다이어그램을 한국어로 정확하게 설명하는 분석가입니다. "
        "그림의 종류(아키텍처 다이어그램, 차트, 사진 등), 구성 요소, 관계, 핵심 메시지를 "
        "3~5문장으로 간결하게 설명하세요. 추측하지 말고 보이는 것만 기술하세요."
    ),
    "en": (
        "You are an analyst who accurately describes figures/diagrams in technical documents in English. "
        "Describe the figure's type (architecture diagram, chart, photo, etc.), its components, "
        "relationships, and key message concisely in 3-5 sentences. "
        "Do not speculate; describe only what is visible."
    ),
}

_TABLE_SYSTEM_PROMPTS = {
    "ko": (
        "당신은 기술 문서의 표를 한국어로 정확하게 설명하는 분석가입니다. "
        "표가 무엇에 대한 데이터인지, 어떤 컬럼들이 있는지, 핵심 패턴이나 결과를 "
        "3~5문장으로 간결하게 설명하세요. 구체적인 수치는 그대로 인용하세요."
    ),
    "en": (
        "You are an analyst who accurately describes tables in technical documents in English. "
        "Describe what data the table contains, what columns it has, and any key patterns or results "
        "concisely in 3-5 sentences. Quote specific numbers verbatim."
    ),
}

_IMAGE_USER_MSG = {
    "ko": "다음 그림을 한국어로 설명해 주세요.",
    "en": "Describe the following image in English.",
}

_TABLE_USER_MSG = {
    "ko": "다음 표를 한국어로 설명해 주세요:\n\n{table}",
    "en": "Describe the following table in English:\n\n{table}",
}

# 하위 호환: 기존에 이 상수를 import하던 코드가 있어도 깨지지 않도록 ko 기본값 유지.
IMAGE_SYSTEM_PROMPT = _IMAGE_SYSTEM_PROMPTS["ko"]
TABLE_SYSTEM_PROMPT = _TABLE_SYSTEM_PROMPTS["ko"]


class Annotator:
    """이미지/표 → 자연어 설명문 생성기.

    기본 백엔드는 `app.config.chat_model` (LM Studio OpenAI 호환).
    교체하려면 `.env`의 `CHAT_MODEL` / `LMSTUDIO_BASE_URL` 만 수정.
    """

    def __init__(
        self,
        model: Any = None,
        lang: str = DEFAULT_LANG,
        min_interval_sec: float = DEFAULT_MIN_INTERVAL_SEC,
    ) -> None:
        self._model = model if model is not None else chat_model
        self._lang = lang if lang in _IMAGE_SYSTEM_PROMPTS else DEFAULT_LANG
        self._min_interval = min_interval_sec
        self._last_call_time = 0.0
        self._image_agent: Agent[None, str] = Agent(
            self._model,
            system_prompt=_IMAGE_SYSTEM_PROMPTS[self._lang],
        )
        self._table_agent: Agent[None, str] = Agent(
            self._model,
            system_prompt=_TABLE_SYSTEM_PROMPTS[self._lang],
        )

    async def _throttle(self) -> None:
        """직전 호출로부터 min_interval_sec 만큼 간격 강제. 첫 호출은 즉시 통과."""
        if self._min_interval <= 0:
            return
        if self._last_call_time == 0.0:
            self._last_call_time = time.monotonic()
            return
        elapsed = time.monotonic() - self._last_call_time
        if elapsed < self._min_interval:
            wait = self._min_interval - elapsed
            logger.info("rate limit: %.1f초 대기", wait)
            await asyncio.sleep(wait)
        self._last_call_time = time.monotonic()

    async def describe_image(self, img: "Image") -> str:
        """PIL 이미지를 자연어로 설명 (async)."""
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        png_bytes = buf.getvalue()
        await self._throttle()
        try:
            result = await self._image_agent.run(
                [
                    _IMAGE_USER_MSG[self._lang],
                    BinaryContent(data=png_bytes, media_type="image/png"),
                ]
            )
            return result.output.strip()
        except Exception as exc:
            logger.warning("이미지 설명 생성 실패: %s", exc)
            return ""

    async def describe_table(self, markdown_table: str) -> str:
        """Markdown 형식의 표를 자연어로 설명 (async)."""
        await self._throttle()
        try:
            result = await self._table_agent.run(
                _TABLE_USER_MSG[self._lang].format(table=markdown_table)
            )
            return result.output.strip()
        except Exception as exc:
            logger.warning("표 설명 생성 실패: %s", exc)
            return ""
