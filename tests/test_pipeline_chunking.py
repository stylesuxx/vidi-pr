from vidi_pr.models.review import ChangedFile, FileStatus
from vidi_pr.pipeline.chunking import pack_chunks


def _file(name: str, patch_size: int) -> ChangedFile:
    return ChangedFile(
        filename=name,
        status=FileStatus.MODIFIED,
        additions=1,
        deletions=0,
        patch="x" * patch_size,
    )


def test_files_within_budget_share_a_chunk() -> None:
    files = [_file("a.py", 100), _file("b.py", 100), _file("c.py", 100)]
    result = pack_chunks(files, max_files=10, max_chunks=5, max_chunk_chars=1_000)

    assert len(result.chunks) == 1
    assert {f.filename for f in result.chunks[0].files} == {"a.py", "b.py", "c.py"}
    assert result.skipped == []


def test_files_get_split_into_multiple_chunks_when_budget_exceeded() -> None:
    files = [_file("a.py", 600), _file("b.py", 600), _file("c.py", 600)]
    result = pack_chunks(files, max_files=10, max_chunks=5, max_chunk_chars=1_000)

    assert len(result.chunks) == 3
    assert all(len(c.files) == 1 for c in result.chunks)
    assert result.skipped == []


def test_chunk_index_and_total_set_correctly() -> None:
    files = [_file("a.py", 600), _file("b.py", 600)]
    result = pack_chunks(files, max_files=10, max_chunks=5, max_chunk_chars=1_000)

    assert [c.index for c in result.chunks] == [1, 2]
    assert all(c.total == 2 for c in result.chunks)


def test_max_chunks_drops_remaining_files() -> None:
    files = [_file("a.py", 600), _file("b.py", 600), _file("c.py", 600)]
    result = pack_chunks(files, max_files=10, max_chunks=2, max_chunk_chars=1_000)

    assert len(result.chunks) == 2
    assert result.skipped == ["c.py"]


def test_file_individually_oversized_is_skipped() -> None:
    files = [_file("normal.py", 100), _file("huge.py", 5_000)]
    result = pack_chunks(files, max_files=10, max_chunks=5, max_chunk_chars=1_000)

    assert result.skipped == ["huge.py"]
    assert len(result.chunks) == 1
    assert result.chunks[0].files[0].filename == "normal.py"


def test_max_files_caps_total_placed() -> None:
    files = [_file(f"f{i}.py", 50) for i in range(10)]
    result = pack_chunks(files, max_files=3, max_chunks=5, max_chunk_chars=10_000)

    placed = sum(len(c.files) for c in result.chunks)
    assert placed == 3
    assert len(result.skipped) == 7


def test_files_prioritized_largest_first() -> None:
    files = [
        _file("small.py", 100),
        _file("big.py", 800),
        _file("medium.py", 300),
    ]
    result = pack_chunks(files, max_files=10, max_chunks=2, max_chunk_chars=900)

    # big.py gets placed first; small.py then fits alongside it (800+100<=900);
    # medium.py opens a second chunk because it would push chunk 1 over budget.
    assert len(result.chunks) == 2
    assert {f.filename for f in result.chunks[0].files} == {"big.py", "small.py"}
    assert {f.filename for f in result.chunks[1].files} == {"medium.py"}


def test_empty_input_returns_no_chunks() -> None:
    result = pack_chunks([], max_files=10, max_chunks=5, max_chunk_chars=1_000)

    assert result.chunks == []
    assert result.skipped == []
