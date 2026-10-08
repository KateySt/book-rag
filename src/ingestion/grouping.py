from collections.abc import Iterator

from src.ingestion.chunking import Chunk

VOYAGE_MAX_INPUTS = 1000
VOYAGE_MAX_CHUNKS = 16_000


class ChunkGrouper:
    def __init__(self, *, group_min_tokens: int, group_max_tokens: int, batch_max_tokens: int) -> None:
        self._group_min_tokens = group_min_tokens
        self._group_max_tokens = group_max_tokens
        self._batch_max_tokens = batch_max_tokens

    def group_by_chapter(self, chunks: list[Chunk]) -> list[list[Chunk]]:
        groups: list[list[Chunk]] = []
        current: list[Chunk] = []
        current_tokens = 0
        for chunk in chunks:
            chapter_changed = bool(current) and chunk.chapter != current[-1].chapter
            too_big = current_tokens + chunk.token_count > self._group_max_tokens
            if current and (too_big or (chapter_changed and current_tokens >= self._group_min_tokens)):
                groups.append(current)
                current, current_tokens = [], 0
            current.append(chunk)
            current_tokens += chunk.token_count
        if current:
            groups.append(current)
        return groups

    def batches(self, groups: list[list[Chunk]]) -> Iterator[list[list[Chunk]]]:
        batch: list[list[Chunk]] = []
        batch_tokens = batch_chunks = 0
        for group in groups:
            group_tokens = sum(chunk.token_count for chunk in group)
            if batch and (
                len(batch) >= VOYAGE_MAX_INPUTS
                or batch_chunks + len(group) > VOYAGE_MAX_CHUNKS
                or batch_tokens + group_tokens > self._batch_max_tokens
            ):
                yield batch
                batch, batch_tokens, batch_chunks = [], 0, 0
            batch.append(group)
            batch_tokens += group_tokens
            batch_chunks += len(group)
        if batch:
            yield batch
