"""임베딩 백엔드 — OpenAI 호환 REST 서버(LM Studio 등)에 붙는 자체 클라이언트."""
from app.embeddings.lmstudio import EmbeddingResult, LMStudioEmbedder

__all__ = ["EmbeddingResult", "LMStudioEmbedder"]
