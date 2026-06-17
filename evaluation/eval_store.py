"""평가셋 서버 저장소 — evaluation/eval_sets/<name>.json.

생성·검수한 평가셋을 이름 붙여 저장하고, 채점 시 이름으로 불러 재사용한다.
같은 평가셋을 모든 조합에 쓰게 만들어 비교 공정성을 강제한다.
"""
from __future__ import annotations

import json
import re
import unicodedata
from pathlib import Path

EVAL_SETS_DIR = Path(__file__).parent / "eval_sets"

_NAME_RE = re.compile(r"^[A-Za-z0-9_\-가-힣]+$")


def _safe_name(name: str) -> str:
    # 한글 자모 분해(NFD)로 들어와도 완성형(NFC)으로 합쳐 검증/저장
    name = unicodedata.normalize("NFC", (name or "").strip())
    if not name or not _NAME_RE.match(name):
        raise ValueError("평가셋 이름은 영문/숫자/한글/_/- 만 허용됩니다.")
    return name


def _validate_items(items: list[dict]) -> list[dict]:
    if not isinstance(items, list) or not items:
        raise ValueError("평가셋 items가 비어 있습니다.")
    cleaned: list[dict] = []
    for i, row in enumerate(items):
        q = str(row.get("question", "")).strip()
        if not q:
            raise ValueError(f"{i}번 항목에 'question'이 없습니다.")
        cleaned.append({"question": q, "ground_truth": str(row.get("ground_truth", "")).strip()})
    return cleaned


def save_eval_set(name: str, items: list[dict]) -> Path:
    name = _safe_name(name)
    items = _validate_items(items)
    EVAL_SETS_DIR.mkdir(parents=True, exist_ok=True)
    path = EVAL_SETS_DIR / f"{name}.json"
    path.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def list_eval_sets() -> list[dict]:
    """[{name, count, with_gt}] — with_gt는 정답이 모두 채워진 항목 수."""
    out: list[dict] = []
    if not EVAL_SETS_DIR.exists():
        return out
    for path in sorted(EVAL_SETS_DIR.glob("*.json")):
        try:
            items = json.loads(path.read_text(encoding="utf-8"))
            with_gt = sum(1 for r in items if str(r.get("ground_truth", "")).strip())
            out.append({"name": path.stem, "count": len(items), "with_gt": with_gt})
        except Exception:  # noqa: BLE001
            continue
    return out


def load_eval_set_by_name(name: str) -> list[dict]:
    name = _safe_name(name)
    path = EVAL_SETS_DIR / f"{name}.json"
    if not path.exists():
        raise FileNotFoundError(f"평가셋을 찾을 수 없습니다: {name}")
    return json.loads(path.read_text(encoding="utf-8"))
