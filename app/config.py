import os

import chromadb
from dotenv import load_dotenv
from pydantic_ai import Embedder

load_dotenv()

if "GOOGLE_API_KEY" not in os.environ:
    raise RuntimeError("GOOGLE_API_KEY 환경변수가 설정되지 않았습니다. .env 파일을 확인하세요.")

CHROMA_HOST = os.environ.get("CHROMA_HOST", "localhost")
CHROMA_PORT = int(os.environ.get("CHROMA_PORT", "8001"))

GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "google-gla:gemini-3-flash-preview")
EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "google-gla:gemini-embedding-2-preview")

embedder = Embedder(EMBEDDING_MODEL)

chroma_client = chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT)
chroma_collection = chroma_client.get_or_create_collection(
    name="jarana_faq",
    embedding_function=None,
)
