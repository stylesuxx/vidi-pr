from __future__ import annotations

from dataclasses import dataclass

from vidi_pr.models.review import ChangedFile, Chunk


@dataclass(frozen=True)
class PackingResult:
    chunks: list[Chunk]
    skipped: list[str]


def _file_size(file: ChangedFile) -> int:
    if file.patch is None:
        return 0

    return len(file.patch)


def pack_chunks(
    files: list[ChangedFile],
    *,
    max_files: int,
    max_chunks: int,
    max_chunk_chars: int,
) -> PackingResult:
    """
    Greedy bin-pack `files` into up to `max_chunks` chunks of `max_chunk_chars`.

    Files are never split. Files are tried largest-first so the big ones get
    placed when bins are empty. Files that don't fit in any existing chunk
    and can't open a new chunk (because we are at `max_chunks` or they are
    individually larger than `max_chunk_chars`) are skipped. The `max_files`
    cap bounds total files placed; further candidates are skipped.
    """
    sorted_files = sorted(files, key=_file_size, reverse=True)
    chunks_files: list[list[ChangedFile]] = []
    chunks_sizes: list[int] = []
    skipped: list[str] = []
    placed_count = 0

    for file in sorted_files:
        if placed_count >= max_files:
            skipped.append(file.filename)
            continue

        size = _file_size(file)
        if size > max_chunk_chars:
            skipped.append(file.filename)
            continue

        target_index: int | None = None
        for i, existing_size in enumerate(chunks_sizes):
            if existing_size + size <= max_chunk_chars:
                target_index = i
                break

        if target_index is None:
            if len(chunks_files) >= max_chunks:
                skipped.append(file.filename)
                continue

            chunks_files.append([file])
            chunks_sizes.append(size)
        else:
            chunks_files[target_index].append(file)
            chunks_sizes[target_index] += size

        placed_count += 1

    total = len(chunks_files)
    chunks = [
        Chunk(index=i + 1, total=total, files=files_in_chunk)
        for i, files_in_chunk in enumerate(chunks_files)
    ]

    return PackingResult(chunks=chunks, skipped=skipped)
