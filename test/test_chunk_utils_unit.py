import logging
import os
import gzip
import math

import pytest

from chunks_utils import split_input_file


def _lines_in_gz(path: str) -> int:
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        return sum(1 for _ in fh)


def test_csv_chunk_sizes(csv_file_with_1k_lines_no_header, tmp_path):
    for size, expected in [(500, 2), (300, 4), (100, 10)]:
        out_dir = tmp_path / f"chunks_{size}"
        chunks, records = split_input_file(
            str(out_dir), csv_file_with_1k_lines_no_header, size
        )

        assert records == 1_000
        assert chunks == expected
        assert (
            len([f for f in os.listdir(out_dir) if f.endswith(".csv.gz")]) == expected
        )

        for f in out_dir.iterdir():
            assert _lines_in_gz(f) <= size


def test_csv_chunk_sizes_header(csv_file_with_1k_lines, tmp_path):
    for size, expected in [(500, 2), (300, 4), (100, 10)]:
        out_dir = tmp_path / f"chunks_{size}"
        chunks, records = split_input_file(
            str(out_dir), csv_file_with_1k_lines, size, header=True
        )

        assert records == 1_000
        assert chunks == expected
        assert (
            len([f for f in os.listdir(out_dir) if f.endswith(".csv.gz")]) == expected
        )

        for f in out_dir.iterdir():
            assert _lines_in_gz(f) - 1 <= size


def test_max_records_limit(csv_file_with_1k_lines_no_header, tmp_path):
    out_dir = tmp_path / "limited"
    chunks, records = split_input_file(
        str(out_dir), csv_file_with_1k_lines_no_header, 100, max_records=350
    )

    assert records == 350
    expected_chunks = math.ceil(350 / 100)
    assert chunks == expected_chunks
    assert (
        len([f for f in os.listdir(out_dir) if f.endswith(".csv.gz")])
        == expected_chunks
    )

    total = sum(_lines_in_gz(f) for f in out_dir.iterdir())
    assert total == 350


def test_empty_input_file(empty_file, tmp_path):
    """Test handling of empty input files."""
    out_dir = tmp_path / "empty_chunks"
    chunks, records = split_input_file(str(out_dir), empty_file, 100)

    assert chunks == 0
    assert records == 0
    assert len(list(out_dir.iterdir())) == 0


def test_skip_existing_chunks(csv_file_with_1k_lines_no_header, tmp_path):
    """Test idempotent behavior when chunks already exist."""
    out_dir = tmp_path / "existing"
    out_dir.mkdir()

    # Create a dummy existing chunk
    dummy_chunk = out_dir / "chunk_0001.csv.gz"
    with gzip.open(dummy_chunk, "wt", encoding="utf-8") as f:
        f.write("dummy,data\n")

    chunks, records = split_input_file(
        str(out_dir), csv_file_with_1k_lines_no_header, 100
    )

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
    chunks, records = split_input_file(
        str(out_dir), csv_file_with_1k_lines, 1, max_records=5
    )

    assert chunks == 5
    assert records == 5

    for f in out_dir.iterdir():
        assert _lines_in_gz(f) == 1


def test_csv_header_propagation(csv_file_with_1k_lines, tmp_path):
    with open(csv_file_with_1k_lines, "r+", encoding="utf-8") as fh:
        body = fh.read()
        fh.seek(0)
        fh.write("id,name,value\n" + body)

    out_dir = tmp_path / "header"
    split_input_file(str(out_dir), csv_file_with_1k_lines, 200, header=True)

    for f in out_dir.iterdir():
        with gzip.open(f, "rt", encoding="utf-8") as zf:
            assert zf.readline().strip() == "id,name,value"


def test_jsonl_and_jsonl_gz(csv_file_with_1k_lines_no_header, tmp_path):
    jsonl = str(tmp_path / "data.jsonl")
    with open(csv_file_with_1k_lines_no_header, "r", encoding="utf-8") as src, open(
        jsonl, "w", encoding="utf-8"
    ) as dst:
        for ln in src:
            i, n, v = ln.strip().split(",")
            dst.write(f'{{"id":{i},"name":"{n}","value":"{v}"}}\n')

    c, r = split_input_file(str(tmp_path / "jsonl"), jsonl, 100)
    assert (c, r) == (10, 1_000)

    gz_jsonl = str(tmp_path / "data.jsonl.gz")
    with open(jsonl, "rb") as src, gzip.open(gz_jsonl, "wb") as dst:
        dst.writelines(src)
    c_gz, r_gz = split_input_file(str(tmp_path / "jsonl_gz"), gz_jsonl, 100)
    assert (c_gz, r_gz) == (10, 1_000)


def test_bad_lines_skipped_and_logged(tmp_path, caplog):
    bad = tmp_path / "bad.csv"
    bad.write_text(
        "id,name,value\n"
        "1,good,line\n"
        "badlinewithoutcomma\n"
        ",missingstart\n"
        "2,another,good\n",
        encoding="utf-8",
    )

    with caplog.at_level(logging.WARNING):
        chunks, recs = split_input_file(
            str(tmp_path / "bad_chunks"), str(bad), 10, header=True
        )

    assert recs == 3
    assert "Skipped 1 bad lines" in " ".join(caplog.messages)


def test_bad_lines_skipped_and_logged_jsonl(tmp_path, caplog):
    bad = tmp_path / "bad.jsonl"
    bad.write_text(
        '{"id": 1, "name": "ok"}\n' "NOT_A_JSON\n" '{"id": 2, "name": "still_ok"}\n',
        encoding="utf-8",
    )

    with caplog.at_level(logging.WARNING):
        chunks, recs = split_input_file(
            str(tmp_path / "bad_jsonl_chunks"), str(bad), chunk_size=2
        )

    assert chunks == 1
    assert recs == 2
    assert "Skipped 1 bad lines" in " ".join(caplog.messages)
