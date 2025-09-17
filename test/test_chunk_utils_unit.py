import os
import gzip
import math

import pytest

from chunks_utils import split_input_file


def _lines_in_gz(path: str) -> int:
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        return sum(1 for _ in fh)


def test_csv_chunk_sizes(csv_file_with_1k_lines, tmp_path):
    for size, expected in [(500, 2), (300, 4), (100, 10)]:
        out_dir = tmp_path / f"chunks_{size}"
        chunks, records = split_input_file(str(out_dir), csv_file_with_1k_lines, size)

        assert records == 1_000
        assert chunks == expected
        assert len([f for f in os.listdir(out_dir) if f.endswith(".csv.gz")]) == expected

        for f in out_dir.iterdir():
            assert _lines_in_gz(f) <= size


def test_max_records_limit(csv_file_with_1k_lines, tmp_path):
    out_dir = tmp_path / "limited"
    chunks, records = split_input_file(str(out_dir), csv_file_with_1k_lines, 100, max_records=350)

    assert records == 350
    expected_chunks = math.ceil(350 / 100)
    assert chunks == expected_chunks
    assert len([f for f in os.listdir(out_dir) if f.endswith(".csv.gz")]) == expected_chunks

    total = sum(_lines_in_gz(f) for f in out_dir.iterdir())
    assert total == 350


def test_empty_input_file(empty_file, tmp_path):
    """Test handling of empty input files."""
    out_dir = tmp_path / "empty_chunks"
    chunks, records = split_input_file(str(out_dir), empty_file, 100)

    assert chunks == 0
    assert records == 0
    assert len(list(out_dir.iterdir())) == 0


def test_skip_existing_chunks(csv_file_with_1k_lines, tmp_path):
    """Test idempotent behavior when chunks already exist."""
    out_dir = tmp_path / "existing"
    out_dir.mkdir()

    # Create a dummy existing chunk
    dummy_chunk = out_dir / "chunk_0001.csv.gz"
    with gzip.open(dummy_chunk, "wt", encoding="utf-8") as f:
        f.write("dummy,data\n")

    chunks, records = split_input_file(str(out_dir), csv_file_with_1k_lines, 100)

    assert chunks == 1
    assert records is None


def test_invalid_chunk_size(csv_file_with_1k_lines, tmp_path):
    """Test validation of chunk_size parameter."""
    out_dir = tmp_path / "invalid"

    with pytest.raises(ValueError, match="chunk_size must be a positive integer"):
        split_input_file(str(out_dir), csv_file_with_1k_lines, 0)

    with pytest.raises(ValueError, match="chunk_size must be a positive integer"):
        split_input_file(str(out_dir), csv_file_with_1k_lines, -5)


def test_single_record_chunks(csv_file_with_1k_lines, tmp_path):
    """Test edge case of chunk_size=1."""
    out_dir = tmp_path / "single_record"
    chunks, records = split_input_file(str(out_dir), csv_file_with_1k_lines, 1, max_records=5)

    assert chunks == 5
    assert records == 5

    for f in out_dir.iterdir():
        assert _lines_in_gz(f) == 1