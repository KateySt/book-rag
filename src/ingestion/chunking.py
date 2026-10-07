import logging
from dataclasses import dataclass
from io import BytesIO
from pathlib import PurePath

import pypdfium2 as pdfium
from docling.datamodel.base_models import ConversionStatus, DocumentStream, InputFormat
from docling.datamodel.pipeline_options import HeadingHierarchyOptions, PdfPipelineOptions
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling_core.transforms.chunker.hybrid_chunker import HybridChunker
from docling_core.transforms.chunker.tokenizer.huggingface import HuggingFaceTokenizer
from docling_core.types.doc import DoclingDocument
from transformers import AutoTokenizer

from src.exceptions import DocumentParseError

logger = logging.getLogger(__name__)

FURNITURE_LABELS = {"page_header", "page_footer", "footnote"}


@dataclass(frozen=True, slots=True)
class Chunk:
    text: str
    embed_text: str
    type: str
    chapter: str
    section_path: str
    page_start: int
    page_end: int
    chunk_index: int
    token_count: int


class DocumentChunker:
    def __init__(
            self,
            *,
            tokenizer_name: str,
            chunk_max_tokens: int,
            max_pages: int,
            max_file_size: int,
            document_timeout: float,
            ocr_min_chars_per_page: int,
    ) -> None:
        self._tokenizer_name = tokenizer_name
        self._chunk_max_tokens = chunk_max_tokens
        self._max_pages = max_pages
        self._max_file_size = max_file_size
        self._document_timeout = document_timeout
        self._ocr_min_chars_per_page = ocr_min_chars_per_page
        self._converters: dict[bool, DocumentConverter] = {}
        self._tokenizer: HuggingFaceTokenizer | None = None
        self._chunker: HybridChunker | None = None

    def warm_up(self) -> None:
        self._converter(do_ocr=False)
        self._hybrid_chunker()

    def inspect_pdf(self, data: bytes) -> None:
        try:
            pdf = pdfium.PdfDocument(data)
        except pdfium.PdfiumError as error:
            if "password" in str(error).lower():
                raise DocumentParseError("PDF is password-protected") from error
            raise DocumentParseError("PDF is corrupted") from error
        try:
            if len(pdf) > self._max_pages:
                raise DocumentParseError(f"PDF has more than {self._max_pages} pages")
        finally:
            pdf.close()

    def load_and_chunk(self, data: bytes, filename: str) -> list[Chunk]:
        name = PurePath(filename).name or "document.pdf"
        document = self._convert(data, name, do_ocr=False)
        if self._looks_scanned(document):
            logger.info("%s looks scanned, retrying with OCR", name)
            document = self._convert(data, name, do_ocr=True)
        return self._chunk(document)

    def _converter(self, *, do_ocr: bool) -> DocumentConverter:
        if do_ocr not in self._converters:
            options = PdfPipelineOptions(
                do_ocr=do_ocr,
                do_table_structure=True,
                document_timeout=self._document_timeout,
                heading_hierarchy_options=HeadingHierarchyOptions(enabled=True),
            )
            converter = DocumentConverter(
                allowed_formats=[InputFormat.PDF],
                format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options)},
            )
            converter.initialize_pipeline(InputFormat.PDF)
            self._converters[do_ocr] = converter
        return self._converters[do_ocr]

    def _token_counter(self) -> HuggingFaceTokenizer:
        if self._tokenizer is None:
            self._tokenizer = HuggingFaceTokenizer(
                tokenizer=AutoTokenizer.from_pretrained(self._tokenizer_name),
                max_tokens=self._chunk_max_tokens,
            )
        return self._tokenizer

    def _hybrid_chunker(self) -> HybridChunker:
        if self._chunker is None:
            self._chunker = HybridChunker(tokenizer=self._token_counter(), merge_peers=True)
        return self._chunker

    def _convert(self, data: bytes, name: str, *, do_ocr: bool) -> DoclingDocument:
        result = self._converter(do_ocr=do_ocr).convert(
            DocumentStream(name=name, stream=BytesIO(data)),
            max_num_pages=self._max_pages,
            max_file_size=self._max_file_size,
            raises_on_error=False,
        )
        if result.status is not ConversionStatus.SUCCESS:
            details = "; ".join(error.error_message for error in result.errors) or result.status.value
            raise DocumentParseError(f"could not parse PDF: {details}")
        return result.document

    def _looks_scanned(self, document: DoclingDocument) -> bool:
        pages = max(document.num_pages(), 1)
        chars = sum(len(getattr(item, "text", "") or "") for item, _ in document.iterate_items())
        return chars / pages < self._ocr_min_chars_per_page

    def _chunk(self, document: DoclingDocument) -> list[Chunk]:
        chunker = self._hybrid_chunker()
        tokenizer = self._token_counter()
        chunks: list[Chunk] = []
        for raw in chunker.chunk(document):
            labels = {str(item.label) for item in raw.meta.doc_items}
            if labels and labels <= FURNITURE_LABELS:
                continue

            headings = raw.meta.headings or []
            pages = [prov.page_no for item in raw.meta.doc_items for prov in item.prov]
            embed_text = chunker.contextualize(raw)
            chunks.append(Chunk(
                text=raw.text,
                embed_text=embed_text,
                type=self._block_type(labels),
                chapter=headings[0] if headings else "",
                section_path=" > ".join(headings),
                page_start=min(pages, default=0),
                page_end=max(pages, default=0),
                chunk_index=len(chunks),
                token_count=tokenizer.count_tokens(embed_text),
            ))
        return chunks

    @staticmethod
    def _block_type(labels: set[str]) -> str:
        if labels == {"code"}:
            return "code"
        if labels == {"table"}:
            return "table"
        return "text"
