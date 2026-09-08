import json
from mineru.cli.common import do_parse
from pathlib import Path

FURNITURE_TYPES = {"header", "footer", "page_number", "aside_text", "page_footnote"}
ATOMIC_TYPES = {"code", "table", "equation"}
SKIPPED_SECTIONS = {
    "contents",
    "table of contents",
    "index",
    "about the author",
    "about the reviewers",
    "acknowledgments",
    "copyright",
}


def parse_pdf(
        file: Path,
        output_dir: Path = Path("parsed"),
        backend: str = "pipeline",
        lang: str = "en",
) -> Path:
    parse_method = "vlm" if backend.startswith("vlm") else "auto"
    content_list = output_dir / file.stem / parse_method / f"{file.stem}_content_list.json"
    if content_list.exists():
        return content_list

    do_parse(
        output_dir=str(output_dir),
        pdf_file_names=[file.stem],
        pdf_bytes_list=[file.read_bytes()],
        p_lang_list=[lang],
        backend=backend,
        f_draw_layout_bbox=False,
        f_draw_span_bbox=False,
        f_dump_md=False,
        f_dump_middle_json=False,
        f_dump_model_output=False,
        f_dump_orig_pdf=False,
        f_dump_content_list=True,
    )
    return content_list


def load_blocks(content_list: Path) -> list[dict]:
    items = json.loads(content_list.read_text(encoding="utf-8"))

    blocks = []
    headings: list[str] = []
    chapter = ""
    skipping = False

    for item in items:
        item_type = item.get("type")
        if item_type in FURNITURE_TYPES:
            continue

        level = item.get("text_level") or 0
        if item_type == "text" and level:
            heading = item.get("text", "").strip()
            headings = headings[: level - 1] + [heading]
            if level == 1:
                chapter = heading
                skipping = heading.lower() in SKIPPED_SECTIONS
            continue

        if skipping:
            continue

        text = _block_text(item)
        if not text:
            continue

        blocks.append({
            "text": text,
            "type": item_type,
            "chapter": chapter,
            "section_path": " > ".join(headings),
            "page": item.get("page_idx", 0) + 1,
        })

    return blocks


def _block_text(item: dict) -> str:
    item_type = item.get("type")

    if item_type == "table":
        parts = item.get("table_caption", []) + [item.get("table_body", "")]
        return "\n".join(part for part in parts if part).strip()

    if item_type == "code":
        parts = item.get("code_caption", []) + [item.get("code_body", "")]
        return "\n".join(part for part in parts if part).strip()

    if item_type == "image":
        return "\n".join(item.get("image_caption", [])).strip()

    return (item.get("text") or "").strip()
