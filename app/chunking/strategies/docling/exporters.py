"""원본 이미지/표 파일 저장 + mapping.json 빌드 + 전체 markdown 통문서 저장."""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from docling_core.transforms.serializer.markdown import MarkdownDocSerializer
from docling_core.types.doc.document import DoclingDocument

logger = logging.getLogger(__name__)


def _page_no(item: Any) -> int | None:
    prov = getattr(item, "prov", None)
    if prov:
        return getattr(prov[0], "page_no", None)
    return None


def save_full_markdown(doc: DoclingDocument, out_path: Path) -> None:
    """전체 문서를 markdown 통문서로 저장 (검증용 — 가 방식)."""
    text = MarkdownDocSerializer(doc=doc).serialize().text
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(text, encoding="utf-8")
    logger.info("전체 markdown 저장: %s (%d자)", out_path, len(text))


def save_picture_images(
    doc: DoclingDocument,
    images_dir: Path,
    pic_descriptions: dict[str, str],
    pic_classifications: dict[str, str] | None = None,
    skipped_refs: set[str] | None = None,
) -> dict[str, dict[str, Any]]:
    """이미지 원본을 PNG로 저장하고 매핑 메타 반환.

    `skipped_refs`에 있는 self_ref는 PNG 저장하지 않고 매핑에도 포함시키지 않음.
    공식 출처: Examples → Figure export — `pic.get_image(doc).save(fp, "PNG")`
    """
    images_dir.mkdir(parents=True, exist_ok=True)
    pic_classifications = pic_classifications or {}
    skipped_refs = skipped_refs or set()
    mapping: dict[str, dict[str, Any]] = {}

    for idx, pic in enumerate(doc.pictures):
        if pic.self_ref in skipped_refs:
            continue
        filename = f"picture_{idx}.png"
        path = images_dir / filename
        try:
            img = pic.get_image(doc)
            if img is None:
                logger.warning("이미지 객체 없음(skip): %s", pic.self_ref)
                continue
            with path.open("wb") as fp:
                img.save(fp, "PNG")
        except Exception as exc:
            logger.warning("이미지 저장 실패 %s: %s", pic.self_ref, exc)
            continue

        mapping[pic.self_ref] = {
            "index": idx,
            "image_path": f"images/{filename}",
            "classification": pic_classifications.get(pic.self_ref, ""),
            "description": pic_descriptions.get(pic.self_ref, ""),
            "page_no": _page_no(pic),
        }
    logger.info("이미지 저장 완료: %d개", len(mapping))
    return mapping


def save_tables(
    doc: DoclingDocument,
    tables_dir: Path,
    table_descriptions: dict[str, str],
) -> dict[str, dict[str, Any]]:
    """표 원본을 md/html/csv 세 형식으로 저장.

    공식 출처: Examples → Table export.
    """
    tables_dir.mkdir(parents=True, exist_ok=True)
    mapping: dict[str, dict[str, Any]] = {}

    for idx, tbl in enumerate(doc.tables):
        md_path = tables_dir / f"table_{idx}.md"
        html_path = tables_dir / f"table_{idx}.html"
        csv_path = tables_dir / f"table_{idx}.csv"

        try:
            df = tbl.export_to_dataframe(doc=doc)
            df.to_csv(csv_path, index=False)
        except Exception as exc:
            logger.warning("표 CSV 저장 실패 %s: %s", tbl.self_ref, exc)
            csv_path = None  # type: ignore[assignment]

        try:
            html = tbl.export_to_html(doc=doc)
            html_path.write_text(html, encoding="utf-8")
        except Exception as exc:
            logger.warning("표 HTML 저장 실패 %s: %s", tbl.self_ref, exc)
            html_path = None  # type: ignore[assignment]

        try:
            # markdown 표는 DataFrame.to_markdown()이 간단/안전
            md = df.to_markdown(index=False)
            md_path.write_text(md, encoding="utf-8")
        except Exception as exc:
            logger.warning("표 MD 저장 실패 %s: %s", tbl.self_ref, exc)
            md_path = None  # type: ignore[assignment]

        mapping[tbl.self_ref] = {
            "index": idx,
            "md_path": f"tables/table_{idx}.md" if md_path else None,
            "html_path": f"tables/table_{idx}.html" if html_path else None,
            "csv_path": f"tables/table_{idx}.csv" if csv_path else None,
            "description": table_descriptions.get(tbl.self_ref, ""),
            "page_no": _page_no(tbl),
        }
    logger.info("표 저장 완료: %d개", len(mapping))
    return mapping


def write_mapping_json(
    out_path: Path,
    doc_name: str,
    source_pdf: str,
    pictures: dict[str, dict[str, Any]],
    tables: dict[str, dict[str, Any]],
    skipped_pictures: dict[str, dict[str, Any]] | None = None,
) -> None:
    payload: dict[str, Any] = {
        "doc_name": doc_name,
        "source_pdf": source_pdf,
        "pictures": pictures,
        "tables": tables,
    }
    if skipped_pictures:
        payload["skipped_pictures"] = skipped_pictures
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info(
        "mapping.json 저장: %s (이미지 %d, 표 %d, skip %d)",
        out_path,
        len(pictures),
        len(tables),
        len(skipped_pictures or {}),
    )
