# MPS(Apple Silicon GPU)가 미지원하는 연산을 CPU로 자동 fallback —
# Docling이 사용하는 PyTorch 모델에서 float64 텐서를 MPS로 보낼 때 발생하는
# "Cannot convert a MPS Tensor to float64 dtype" 에러 회피.
# 다른 어떤 import보다 먼저 설정해야 PyTorch가 들어오기 전에 적용됨.
import os

os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

# uvicorn은 자기 로거만 설정하므로, 앱 모듈 로거(`app.*`)는 root에 핸들러 없으면 출력 안 됨.
# force=True 로 기존 핸들러 덮어쓰고 INFO 레벨로 통일.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    force=True,
)
# httpx 자체 호출 로그(매 임베딩마다 한 줄)는 너무 시끄러우면 WARNING으로 올림 — 일단 INFO 유지
# logging.getLogger("httpx").setLevel(logging.WARNING)


class _SuppressPollingAccessLog(logging.Filter):
    """폴링 엔드포인트의 200 응답 access 로그를 끔.

    프론트가 2초마다 status를 조회하므로 같은 200 줄이 계속 쌓여 시끄러움.
    실패(4xx/5xx)는 그대로 출력. 다른 엔드포인트도 영향 없음.
    """

    POLL_PATHS = (
        "/api/upload/status/",
        "/api/embed/status/",
        "/api/evaluation/status/",
    )

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:
            return True
        # uvicorn access 형식: '... "GET /path HTTP/1.1" 200 OK'
        if " 200 " not in msg and not msg.endswith(" 200"):
            return True
        return not any(p in msg for p in self.POLL_PATHS)


logging.getLogger("uvicorn.access").addFilter(_SuppressPollingAccessLog())

from app.routers.chat import router as chat_router  # noqa: E402
from app.routers.collections import router as collections_router  # noqa: E402
from app.routers.embed import router as embed_router  # noqa: E402
from app.routers.evaluation import router as evaluation_router  # noqa: E402
from app.routers.upload import router as upload_router  # noqa: E402


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


app = FastAPI(title="Jarana Chatbot", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(chat_router, prefix="/api")
app.include_router(upload_router, prefix="/api")
app.include_router(embed_router, prefix="/api")
app.include_router(collections_router, prefix="/api")
app.include_router(evaluation_router, prefix="/api")

# 정적 SPA 마운트 — GET / 는 index.html 자동 반환, theme.css/app.jsx 등 상대 경로도 같이 서빙
app.mount("/", StaticFiles(directory="front", html=True), name="front")
