from src.clients.voyage_client import get_token_counts
from src.parsing import ATOMIC_TYPES


def chunk_blocks(blocks: list[dict], target_tokens: int = 512) -> list[dict]:
    token_counts = get_token_counts([block["text"] for block in blocks])

    chunks: list[dict] = []
    buffer: list[dict] = []
    buffer_tokens = 0

    for block, tokens in zip(blocks, token_counts):
        same_section = not buffer or buffer[-1]["section_path"] == block["section_path"]

        if buffer and (not same_section or buffer_tokens + tokens > target_tokens):
            chunks.append(_build_chunk(buffer, len(chunks)))
            buffer = []
            buffer_tokens = 0

        if block["type"] in ATOMIC_TYPES and tokens > target_tokens:
            chunks.append(_build_chunk([block], len(chunks)))
            continue

        buffer.append(block)
        buffer_tokens += tokens

    if buffer:
        chunks.append(_build_chunk(buffer, len(chunks)))

    return chunks


def _build_chunk(blocks: list[dict], index: int) -> dict:
    first = blocks[0]
    body = "\n\n".join(block["text"] for block in blocks)
    types = {block["type"] for block in blocks}

    return {
        "text": f"{first['section_path']}\n\n{body}" if first["section_path"] else body,
        "chapter": first["chapter"],
        "section_path": first["section_path"],
        "page_start": first["page"],
        "page_end": blocks[-1]["page"],
        "chunk_index": index,
        "type": types.pop() if len(types) == 1 else "mixed",
    }
