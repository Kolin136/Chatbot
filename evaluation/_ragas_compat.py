"""ragas 0.4.3 호환 셰임.

ragas/llms/base.py가 sunset된 langchain_community의 vertexai 경로를 top-level로
import한다(`from langchain_community.chat_models.vertexai import ChatVertexAI`).
본 프로젝트는 langchain 1.x(community 0.4.x)라 그 경로가 제거돼 ragas import 자체가
깨진다. 우리는 Vertex를 쓰지 않으므로(로컬 LM Studio = ChatOpenAI), 안 쓰는 클래스만
sys.modules에 stub으로 채워 import만 통과시킨다.

반드시 `import ragas` 보다 먼저 apply()가 호출돼야 한다. evaluation/__init__.py가
패키지 로드 시점에 호출하므로, evaluation.* 를 import하면 자동 적용된다.
"""
from __future__ import annotations

import sys
import types

_MISSING = "langchain_community.chat_models.vertexai"


def apply() -> None:
    """안 쓰는 vertex 경로를 stub으로 채운다. 이미 있거나 적용됐으면 no-op."""
    try:
        __import__(_MISSING)
        return  # 실제 경로 존재 → 셰임 불필요
    except Exception:
        pass

    if _MISSING in sys.modules and getattr(sys.modules[_MISSING], "_ragas_compat_stub", False):
        return  # 이미 적용됨

    stub = types.ModuleType(_MISSING)
    stub._ragas_compat_stub = True

    class ChatVertexAI:  # 미사용 stub — ragas top-level import 통과 전용
        pass

    stub.ChatVertexAI = ChatVertexAI
    sys.modules[_MISSING] = stub

    # 부모 모듈 속성으로도 노출(`from ... import` 엣지케이스 방지)
    try:
        import langchain_community.chat_models as _cm

        _cm.vertexai = stub
    except Exception:
        pass
