import os
import gzip
import math
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