"""실행 코어 — 한 조합을 채점해 집계 결과를 만든다. (CLI·웹 백그라운드 작업 공용)

흐름:
  1) answering(async): 질문마다 pipeline.answer 수집 → 질문별 진행률 콜백
  2) scoring(sync): asyncio.to_thread로 RAGAS evaluate 실행(중첩 이벤트 루프 회피), repeats회 반복
  3) aggregate: NaN 제외 평균 + 표준편차 + 유효 개수 + provenance
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Callable

import pandas as pd

from ragas import EvaluationDataset, RunConfig, evaluate
from ragas.dataset_schema import SingleTurnSample

from .evaluator import select_metrics
from .pipeline_adapter import Pipeline, RAGConfig

# to_pandas() 출력에서 메트릭이 아닌 입력 컬럼들(나머지는 메트릭 점수로 간주)
_INPUT_COLS = {
    "user_input", "retrieved_contexts", "reference_contexts",
    "retrieved_context_ids", "reference_context_ids", "response",
    "multi_responses", "reference", "rubrics", "persona_name",
    "query_style", "query_length",
}


@dataclass
class ResultBundle:
    label: str
    config: dict
    has_ground_truth: bool
    metrics: dict           # name -> {mean, std, n_valid, n_total, run_means}
    provenance: dict
    per_sample: list[dict] = field(default_factory=list)  # 마지막 run의 샘플별 점수

    def to_dict(self) -> dict:
        return {
            "label": self.label,
            "config": self.config,
            "has_ground_truth": self.has_ground_truth,
            "metrics": self.metrics,
            "provenance": self.provenance,
            "per_sample": self.per_sample,
        }


async def collect_samples(
    pipeline: Pipeline,
    eval_data: list[dict],
    progress_cb: Callable[[int, int], None] | None = None,
) -> list[SingleTurnSample]:
    """질문마다 파이프라인을 돌려 RAGAS 샘플을 만든다(async)."""
    samples: list[SingleTurnSample] = []
    n = len(eval_data)
    for i, row in enumerate(eval_data):
        question = row["question"]
        answer, contexts = await pipeline.answer(question)
        gt = row.get("ground_truth")
        gt = gt if (gt and str(gt).strip()) else None
        samples.append(
            SingleTurnSample(
                user_input=question,
                retrieved_contexts=list(contexts),
                response=answer,
                reference=gt,
            )
        )
        if progress_cb:
            progress_cb(i + 1, n)
    return samples


def _score_once(samples, eval_llm, eval_emb, max_workers: int, timeout: int) -> pd.DataFrame:
    """RAGAS evaluate 1회(동기). 스레드에서 호출되어야 메인 이벤트 루프와 충돌 안 함."""
    has_gt = all(s.reference for s in samples)
    metrics = select_metrics(has_gt)
    dataset = EvaluationDataset(samples=samples)
    run_config = RunConfig(max_workers=max_workers, timeout=timeout)
    result = evaluate(
        dataset=dataset,
        metrics=metrics,
        llm=eval_llm,
        embeddings=eval_emb,
        run_config=run_config,
        show_progress=False,
    )
    return result.to_pandas()


def _aggregate(label, config: RAGConfig, run_dfs: list[pd.DataFrame], has_gt: bool) -> ResultBundle:
    metric_cols = [c for c in run_dfs[0].columns if c not in _INPUT_COLS]

    metrics: dict[str, dict] = {}
    for col in metric_cols:
        all_vals = pd.concat([pd.to_numeric(df[col], errors="coerce") for df in run_dfs])
        run_means = [float(pd.to_numeric(df[col], errors="coerce").mean()) for df in run_dfs]
        valid = all_vals.dropna()
        metrics[col] = {
            "mean": (float(valid.mean()) if len(valid) else None),
            "std": (float(valid.std(ddof=0)) if len(valid) > 1 else 0.0),
            "n_valid": int(len(valid)),
            "n_total": int(len(all_vals)),
            "run_means": run_means,
        }

    last = run_dfs[-1]
    per_sample = []
    for _, r in last.iterrows():
        rec = {"user_input": r.get("user_input")}
        for col in metric_cols:
            v = pd.to_numeric(pd.Series([r.get(col)]), errors="coerce").iloc[0]
            rec[col] = (None if pd.isna(v) else float(v))
        per_sample.append(rec)

    return ResultBundle(
        label=label,
        config={
            "collection_name": config.collection_name,
            "hybrid": config.hybrid,
            "chunking": config.chunking,
            "storage": config.storage,
        },
        has_ground_truth=has_gt,
        metrics=metrics,
        provenance={},
        per_sample=per_sample,
    )


async def run_config(
    config: RAGConfig,
    pipeline: Pipeline,
    eval_data: list[dict],
    eval_llm,
    eval_emb,
    *,
    repeats: int = 1,
    max_workers: int = 2,
    timeout: int = 180,
    answering_cb: Callable[[int, int], None] | None = None,
    scoring_cb: Callable[[int, int], None] | None = None,
) -> ResultBundle:
    """한 조합을 채점한다. repeats>1이면 동일 샘플을 N회 재채점(심판 변동성 측정)."""
    samples = await collect_samples(pipeline, eval_data, progress_cb=answering_cb)
    has_gt = all(s.reference for s in samples)

    run_dfs: list[pd.DataFrame] = []
    for r in range(repeats):
        if scoring_cb:
            scoring_cb(r, repeats)
        df = await asyncio.to_thread(_score_once, samples, eval_llm, eval_emb, max_workers, timeout)
        run_dfs.append(df)

    bundle = _aggregate(config.label, config, run_dfs, has_gt)
    bundle.provenance = {
        "n_questions": len(eval_data),
        "repeats": repeats,
        "metrics": [c for c in run_dfs[0].columns if c not in _INPUT_COLS],
    }
    return bundle
