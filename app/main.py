from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.routers.chat import router as chat_router


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

app.mount("/static", StaticFiles(directory="front"), name="static")


@app.get("/")
async def root():
    return FileResponse("front/index.html")
