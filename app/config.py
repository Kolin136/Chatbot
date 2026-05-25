import os

import chromadb
from dotenv import load_dotenv
from pydantic_ai import Embedder

load_dotenv()

if "GOOGLE_API_KEY" not in os.environ:
    raise RuntimeError("GOOGLE_API_KEY 환경변수가 설정되지 않았습니다. .env 파일을 확인하세요.")

CHROMA_HOST = os.environ.get("CHROMA_HOST", "localhost")
CHROMA_PORT = int(os.environ.get("CHROMA_PORT", "8001"))

GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-flash-lite-latest")
EMBEDDING_MODEL = os.environ.get("EMBEDDING_MODEL", "google-gla:gemini-embedding-2-preview")

# 청킹 토크나이저 — RAG 임베딩 모델의 토크나이저/한도와 정렬 권장
CHUNK_TOKENIZER_MODEL = os.environ.get(
    "CHUNK_TOKENIZER_MODEL", "sentence-transformers/all-MiniLM-L6-v2"
)
CHUNK_MAX_TOKENS = int(os.environ.get("CHUNK_MAX_TOKENS", "512"))

# 청킹에서 skip할 picture 분류 라벨 (DocumentFigureClassifier 라벨, 쉼표 구분)
SKIP_PICTURE_CLASSES = frozenset(
    cls.strip().lower()
    for cls in os.environ.get("SKIP_PICTURE_CLASSES", "logo").split(",")
    if cls.strip()
)

# Gemini LLM 호출 간격 (초). free tier 분당 한도 회피용.
# 청킹 단계(이미지/표 → VLM 설명문) 호출 간격.
CHUNK_VLM_INTERVAL_SEC = float(os.environ.get("CHUNK_VLM_INTERVAL_SEC", "13"))
# 임베딩 단계(청크 contextualized_text → 요약) 호출 간격.
EMBED_SUMMARY_INTERVAL_SEC = float(os.environ.get("EMBED_SUMMARY_INTERVAL_SEC", "13"))

embedder = Embedder(EMBEDDING_MODEL)

chroma_client = chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT)
# 컬렉션은 더 이상 고정 인스턴스를 두지 않음.
# RAG 검색 / 임베딩 / 목록 조회 시 chroma_client.get_or_create_collection(...) / list_collections() 로 동적 접근.
