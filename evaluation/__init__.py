"""RAGAS 오프라인 A/B 평가 하니스 (evaluation/).

청킹·저장·검색 전략 조합의 RAG 품질을 RAGAS로 채점·비교한다.
설계/계획은 docs/RAGAS_PLAN.md 참조.

이 패키지를 import하면 ragas 0.4.3 호환 셰임이 자동 적용된다(_ragas_compat).
따라서 evaluation 하위 모듈은 안전하게 `import ragas` 할 수 있다.
"""
from __future__ import annotations

from . import _ragas_compat

_ragas_compat.apply()
