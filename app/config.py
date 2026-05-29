"""애플리케이션 글로벌 설정 — `.env` 로딩 + 외부 서비스 클라이언트 단일 진입점.

모든 호스트/포트/모델 ID는 `.env`에서만 읽어온다. 코드에 박지 않음.
LLM/임베딩 백엔드는 LM Studio (OpenAI 호환 REST) 단일.
"""
import os

import chromadb
from dotenv import load_dotenv
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from app.embeddings import LMStudioEmbedder

load_dotenv()


def _require(key: str) -> str:
    val = os.environ.get(key)
    if not val:
        raise RuntimeError(
            f"{key} 환경변수가 설정되지 않았습니다. .env 파일을 확인하세요."
        )
    return val


# ─── LM Studio 접속 정보 (필수) ─────────────────────────────────
LMSTUDIO_BASE_URL = _require("LMSTUDIO_BASE_URL")  # 예: http://사설ip/v1
EMBEDDING_MODEL = _require("EMBEDDING_MODEL")       # 예: text-embedding-multilingual-e5-large-instruct
CHAT_MODEL = _require("CHAT_MODEL")                 # 예: google/gemma-4-e4b (vision/tool_use 둘 다 지원)

# ─── ChromaDB ────────────────────────────────────────────────────
CHROMA_HOST = os.environ.get("CHROMA_HOST", "localhost")
CHROMA_PORT = int(os.environ.get("CHROMA_PORT", "8001"))

# ─── 청킹 설정 ───────────────────────────────────────────────────
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

# LLM 호출 간격 (초). LM Studio는 자체 한도 없음 — GPU 부하 분산용으로 작은 값 권장.
# 청킹 단계(이미지/표 → VLM 설명문) 호출 간격.
CHUNK_VLM_INTERVAL_SEC = float(os.environ.get("CHUNK_VLM_INTERVAL_SEC", "0"))
# 임베딩 단계(청크 contextualized_text → 요약) 호출 간격.
EMBED_SUMMARY_INTERVAL_SEC = float(os.environ.get("EMBED_SUMMARY_INTERVAL_SEC", "0"))

# 청킹 전략 기본값 (프론트가 지정하면 무시됨)
CHUNK_STRATEGY = os.environ.get("CHUNK_STRATEGY", "docling_hybrid")

# LangChain SemanticChunker 옵션
SEMANTIC_BREAKPOINT_TYPE = os.environ.get("SEMANTIC_BREAKPOINT_TYPE", "percentile")
SEMANTIC_BREAKPOINT_AMOUNT = float(os.environ.get("SEMANTIC_BREAKPOINT_AMOUNT", "95"))


# ─── 외부 서비스 클라이언트 (단일 인스턴스) ─────────────────────
# LM Studio에 OpenAI 호환 경로로 붙는 pydantic_ai 프로바이더.
# api_key는 pydantic_ai의 더미 검증용 — LM Studio는 토큰 검증 안 함.
_lmstudio_provider = OpenAIProvider(
    base_url=LMSTUDIO_BASE_URL,
    api_key="lm-studio",
)

# Chat/VLM 공용 모델 — Agent(chat_model, ...) 형태로 호출처에 주입.
chat_model = OpenAIChatModel(CHAT_MODEL, provider=_lmstudio_provider)

# 임베딩 클라이언트 — 자체 httpx 기반.
embedder = LMStudioEmbedder(base_url=LMSTUDIO_BASE_URL, model=EMBEDDING_MODEL)

# ChromaDB HTTP 클라이언트.
chroma_client = chromadb.HttpClient(host=CHROMA_HOST, port=CHROMA_PORT)
# 컬렉션은 더 이상 고정 인스턴스를 두지 않음.
# RAG 검색 / 임베딩 / 목록 조회 시 chroma_client.get_or_create_collection(...) / list_collections() 로 동적 접근.
