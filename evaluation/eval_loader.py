"""평가셋 로더 — JSON `[{question, ground_truth?}]`.

ground_truth는 선택. 일부 항목만 정답이 있을 수도 있다(부분 정답 허용).
"""
from __future__ import annotations

import json
from pathlib import Path


def load_eval_set(path: str | Path) -> list[dict]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, list) or not data:
        raise ValueError("평가셋은 비어있지 않은 JSON 배열이어야 합니다: [{\"question\": ...}, ...]")
    for i, row in enumerate(data):
        if not isinstance(row, dict) or not str(row.get("question", "")).strip():
            raise ValueError(f"{i}번 항목에 비어있지 않은 'question'이 필요합니다.")
    return data


def ground_truth_coverage(eval_data: list[dict]) -> tuple[int, int]:
    """(정답 있는 항목 수, 전체 수). 모두 있으면 Context Recall 사용 가능."""
    total = len(eval_data)
    with_gt = sum(1 for r in eval_data if str(r.get("ground_truth", "")).strip())
    return with_gt, total
