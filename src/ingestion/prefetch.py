import logging
from pathlib import Path

from src.ingestion.chunking import DocumentChunker

SAMPLE_PDF = Path(__file__).with_name("sample.pdf")


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    chunker = DocumentChunker(
        tokenizer_name="voyageai/voyage-context-4",
        chunk_max_tokens=512,
        max_pages=20,
        max_file_size=15 * 1024 * 1024,
        document_timeout=150,
        ocr_min_chars_per_page=100,
    )
    chunker.prefetch_models()
    chunks = chunker.load_and_chunk(SAMPLE_PDF.read_bytes(), SAMPLE_PDF.name)
    logging.info("prefetch done, sample produced %s chunks", len(chunks))


if __name__ == "__main__":
    main()
