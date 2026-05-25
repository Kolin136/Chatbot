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

from app.routers.chat import router as chat_router  # noqa: E402
from app.routers.collections import router as collections_router  # noqa: E402
from app.routers.embed import router as embed_router  # noqa: E402
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

# 정적 SPA 마운트 — GET / 는 index.html 자동 반환, theme.css/app.jsx 등 상대 경로도 같이 서빙
app.mount("/", StaticFiles(directory="front", html=True), name="front")
