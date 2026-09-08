from docling_core.transforms.chunker.hybrid_chunker import HybridChunker
from docling_core.transforms.chunker.tokenizer.base import BaseTokenizer
from langchain_docling import DoclingLoader
from langchain_docling.loader import ExportType
from pathlib import Path
from typing import Any

CHUNKS_PER_GROUP = 64
FURNITURE_LABELS = {"page_header", "page_footer", "footnote"}


def load_and_chunk(file: Path, target_tokens: int = 512) -> list[dict]:
    loader = DoclingLoader(
        file_path=str(file),
        export_type=ExportType.DOC_CHUNKS,
        chunker=HybridChunker(
            max_tokens=target_tokens,
        ),
    )

    chunks = []
    for document in loader.load():
        meta = document.metadata.get("dl_meta", {})
        headings = meta.get("headings") or []
        pages = [
            prov["page_no"]
            for item in meta.get("doc_items", [])
            for prov in item.get("prov", [])
            if "page_no" in prov
        ]

        labels = {item.get("label", "") for item in meta.get("doc_items", [])}
        if bool(labels) and labels <= FURNITURE_LABELS:
            continue

        chunks.append({
            "text": document.page_content,
            "type": _block_type(labels),
            "chapter": headings[0] if headings else "",
            "section_path": " > ".join(headings),
            "page_start": min(pages) if pages else 0,
            "page_end": max(pages) if pages else 0,
            "chunk_index": len(chunks),
            "doc_group": f"{file.stem}-{len(chunks) // CHUNKS_PER_GROUP}",
        })

    return chunks


def _block_type(labels) -> str:
    if labels == {"code"}:
        return "code"
    if labels == {"table"}:
        return "table"
    return "text"
