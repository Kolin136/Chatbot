"""ChromaDB 컬렉션 목록 조회 / 삭제 라우터."""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Response

from app.config import chroma_client
from app.models import CollectionInfo, CollectionsResponse

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/collections", response_model=CollectionsResponse)
async def list_collections() -> CollectionsResponse:
    try:
        cols = chroma_client.list_collections()
    except Exception as exc:
        logger.exception("ChromaDB list_collections 실패")
        raise HTTPException(status_code=500, detail=f"ChromaDB 연결 실패: {exc}")

    items: list[CollectionInfo] = []
    for col in cols:
        # ChromaDB 버전에 따라 Collection 객체 또는 str 반환
        name = col.name if hasattr(col, "name") else str(col)
        count = 0
        metadata: dict = {}
        try:
            obj = chroma_client.get_collection(name=name)
            count = obj.count()
            metadata = obj.metadata or {}
        except Exception:
            logger.exception("collection 상세 조회 실패: %s", name)
        items.append(
            CollectionInfo(
                name=name,
                count=count,
                created_at=metadata.get("created_at", ""),
            )
        )
    return CollectionsResponse(collections=items)


@router.delete("/collections/{name}", status_code=204)
async def delete_collection(name: str) -> Response:
    """ChromaDB 컬렉션 삭제. 없으면 404."""
    if not name.strip():
        raise HTTPException(status_code=400, detail="collection name이 비어있습니다.")
    try:
        # 존재 확인 (없으면 예외)
        chroma_client.get_collection(name=name)
    except Exception:
        raise HTTPException(status_code=404, detail=f"컬렉션을 찾을 수 없습니다: {name}")

    try:
        chroma_client.delete_collection(name=name)
    except Exception as exc:
        logger.exception("컬렉션 삭제 실패: %s", name)
        raise HTTPException(status_code=500, detail=f"삭제 실패: {exc}")

    logger.info("컬렉션 삭제 완료: %s", name)
    return Response(status_code=204)
