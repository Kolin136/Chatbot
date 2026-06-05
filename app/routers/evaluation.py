"""RAGAS 평가 — 웹 백그라운드 작업 엔드포인트.

POST /api/evaluation              → 평가 시작(eval_job_id 반환)
GET  /api/evaluation/status/{id}  → 진행률 폴링(JobStatus)
GET  /api/evaluation/results      → 저장된 결과 요약 목록(비교용)

채점 로직은 evaluation/ 라이브러리를 그대로 재사용(CLI와 동일). 이 라우터는 진행률만 보고한다.
OCP: 기존 RAG 파이프라인은 호출만, 수정 없음.
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, UploadFile

from app.evaluation_jobs import eval_job_store
from app.models import (
    EvalSetInfo,
    EvalSetItemsResponse,
    EvalSetsResponse,
    EvalSetSaveRequest,
    EvaluationRequest,
    EvaluationResultsResponse,
    EvaluationStartResponse,
    GeneratedEvalSet,
    JobStatus,
)

router = APIRouter()
logger = logging.getLogger(__name__)

RESULTS_DIR = Path(__file__).resolve().parents[2] / "evaluation" / "results"


def _resolve_eval_data(req: EvaluationRequest) -> list[dict]:
    """요청에서 채점할 평가셋을 확정한다. eval_set_name 우선, 없으면 inline."""
    if req.eval_set_name:
        from evaluation.eval_store import load_eval_set_by_name

        try:
            data = load_eval_set_by_name(req.eval_set_name)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
    elif req.eval_set:
        data = req.eval_set
    else:
        raise HTTPException(status_code=400, detail="eval_set_name 또는 eval_set이 필요합니다.")

    if not data:
        raise HTTPException(status_code=400, detail="평가셋이 비어 있습니다.")
    for i, row in enumerate(data):
        if not str(row.get("question", "")).strip():
            raise HTTPException(status_code=400, detail=f"{i}번 항목에 'question'이 없습니다.")
    return data


async def _run_evaluation_job(
    eval_job_id: str, req: EvaluationRequest, eval_data: list[dict]
) -> None:
    eval_job_store.update(
        eval_job_id, status="running", progress=0, step="prepare", message="준비 중"
    )
    try:
        # 지연 import — evaluation 패키지 로드시 ragas 호환 셰임 적용
        from evaluation.evaluator import build_evaluator
        from evaluation.pipeline_adapter import RAGConfig, build_pipeline
        from evaluation.runner import run_config

        config = RAGConfig(
            label=req.label,
            collection_name=req.collection,
            hybrid=req.hybrid,
            chunking=req.chunking,
            storage=req.storage,
        )
        pipeline = build_pipeline(config)
        eval_llm, eval_emb = build_evaluator()

        def answering_cb(done: int, total: int) -> None:
            eval_job_store.update(
                eval_job_id,
                progress=int(done / max(total, 1) * 50),
                step="answering",
                message=f"질문 처리 중 ({done}/{total})",
            )

        def scoring_cb(r: int, repeats: int) -> None:
            eval_job_store.update(
                eval_job_id,
                progress=50 + int(r / max(repeats, 1) * 45),
                step="scoring",
                message=f"RAGAS 채점 중 (run {r + 1}/{repeats})",
            )

        bundle = await run_config(
            config, pipeline, eval_data, eval_llm, eval_emb,
            repeats=req.repeats,
            answering_cb=answering_cb,
            scoring_cb=scoring_cb,
        )

        import hashlib

        import ragas

        eval_hash = hashlib.sha256(
            json.dumps(eval_data, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()[:12]
        bundle.provenance.update({
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "ragas_version": ragas.__version__,
            "judge": "app.config LM Studio (로컬)",
            "source": "web",
            "eval_set_name": req.eval_set_name or "(inline)",
            "eval_set_sha256_12": eval_hash,
        })

        RESULTS_DIR.mkdir(parents=True, exist_ok=True)
        result = bundle.to_dict()
        (RESULTS_DIR / f"{req.label}.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        eval_job_store.update(
            eval_job_id,
            status="completed",
            progress=100,
            step="done",
            message="평가 완료",
            result=result,
        )
    except Exception as exc:  # noqa: BLE001
        eval_job_store.update(
            eval_job_id,
            status="failed",
            step="error",
            message="평가 실패",
            error=str(exc),
        )


@router.post("/evaluation", response_model=EvaluationStartResponse)
async def start_evaluation(
    req: EvaluationRequest, background_tasks: BackgroundTasks
) -> EvaluationStartResponse:
    eval_data = _resolve_eval_data(req)
    eval_job_id = str(uuid.uuid4())
    eval_job_store.create(eval_job_id)
    background_tasks.add_task(_run_evaluation_job, eval_job_id, req, eval_data)
    return EvaluationStartResponse(
        eval_job_id=eval_job_id, collection=req.collection, label=req.label
    )


# ─── 평가셋 생성(Gemini)/저장/조회 ───────────────────────────────


@router.post("/evaluation/generate-evalset", response_model=GeneratedEvalSet)
async def generate_evalset(
    file: UploadFile = File(...), n: int = Form(12)
) -> GeneratedEvalSet:
    """PDF를 Gemini에 inline 전송해 질문+정답을 생성한다(저장 안 함 — 검수 먼저).

    GOOGLE_API_KEY 미설정 시 503. recommender 엔드포인트와 동일 패턴.
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="파일 이름이 비어있습니다.")
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="PDF 파일만 가능합니다.")
    pdf_bytes = await file.read()
    if not pdf_bytes:
        raise HTTPException(status_code=400, detail="빈 파일입니다.")
    if len(pdf_bytes) > 50 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="PDF가 50MB를 초과합니다 (Gemini 한도).")
    n = max(1, min(int(n), 50))

    try:
        from evaluation.generate_evalset import generate_from_bytes

        eval_set = await generate_from_bytes(pdf_bytes, file.filename, n)
    except RuntimeError as exc:  # GOOGLE_API_KEY 미설정
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception as exc:  # noqa: BLE001
        logger.exception("평가셋 생성 실패: %s", file.filename)
        raise HTTPException(status_code=500, detail=f"평가셋 생성 실패: {exc}")

    items = [{"question": it.question, "ground_truth": it.ground_truth} for it in eval_set.items]
    return GeneratedEvalSet(items=items)


@router.post("/evaluation/eval-sets", response_model=EvalSetInfo)
async def save_eval_set_endpoint(req: EvalSetSaveRequest) -> EvalSetInfo:
    from evaluation.eval_store import save_eval_set

    try:
        save_eval_set(req.name, req.items)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    with_gt = sum(1 for r in req.items if str(r.get("ground_truth", "")).strip())
    return EvalSetInfo(name=req.name, count=len(req.items), with_gt=with_gt)


@router.get("/evaluation/eval-sets", response_model=EvalSetsResponse)
async def list_eval_sets_endpoint() -> EvalSetsResponse:
    from evaluation.eval_store import list_eval_sets

    return EvalSetsResponse(eval_sets=[EvalSetInfo(**e) for e in list_eval_sets()])


@router.get("/evaluation/eval-sets/{name}", response_model=EvalSetItemsResponse)
async def get_eval_set_endpoint(name: str) -> EvalSetItemsResponse:
    from evaluation.eval_store import load_eval_set_by_name

    try:
        items = load_eval_set_by_name(name)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return EvalSetItemsResponse(name=name, items=items)


@router.get("/evaluation/status/{eval_job_id}", response_model=JobStatus)
async def get_evaluation_status(eval_job_id: str) -> JobStatus:
    state = eval_job_store.get(eval_job_id)
    if state is None:
        raise HTTPException(status_code=404, detail="eval_job_id를 찾을 수 없습니다.")
    return JobStatus(
        job_id=state.eval_job_id,
        status=state.status,
        progress=state.progress,
        step=state.step,
        message=state.message,
        result=state.result,
        error=state.error,
    )


@router.get("/evaluation/results", response_model=EvaluationResultsResponse)
async def list_evaluation_results() -> EvaluationResultsResponse:
    results: list[dict] = []
    if RESULTS_DIR.exists():
        for path in sorted(RESULTS_DIR.glob("*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                results.append({
                    "label": data.get("label", path.stem),
                    "config": data.get("config", {}),
                    "has_ground_truth": data.get("has_ground_truth", False),
                    "metrics": data.get("metrics", {}),
                    "provenance": data.get("provenance", {}),
                })
            except Exception:  # noqa: BLE001
                continue
    return EvaluationResultsResponse(results=results)
