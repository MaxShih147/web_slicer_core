"""fingerprint.py: decompressed per-entry hashes, metadata exclusion, file format."""
from __future__ import annotations

import hashlib
import zipfile

import pytest

import fingerprint as fp
from conftest import write_zip

LAYERS = {"model00000.rle": b"\x01" * 4096, "model00001.rle": b"\x02" * 1000 + b"\x03"}


def sl1_entries(meta_tag: bytes = b"") -> dict[str, bytes]:
    return {
        "prusaslicer.ini": b"printer = x" + meta_tag,
        "model00001.rle": LAYERS["model00001.rle"],
        "config.ini": b"expTime = 2" + meta_tag,
        "config.json": b"{}" + meta_tag,
        "thumbnail/thumbnail400x400.png": b"thumb" + meta_tag,
        "model00000.rle": LAYERS["model00000.rle"],
    }


def test_metadata_entries_are_excluded(tmp_path):
    result = fp.fingerprint_archive(write_zip(tmp_path / "a.sl1", sl1_entries()), "layers")

    assert [name for name, _ in result.entries] == ["model00000.rle", "model00001.rle"]
    assert result.excluded == ["config.ini", "config.json", "prusaslicer.ini", "thumbnail/thumbnail400x400.png"]
    assert "config.ini" not in result.lines()


def test_hashes_are_of_decompressed_bytes(tmp_path):
    result = fp.fingerprint_archive(write_zip(tmp_path / "a.sl1", sl1_entries()), "layers")

    assert dict(result.entries)["model00000.rle"] == hashlib.sha256(LAYERS["model00000.rle"]).hexdigest()


def test_zip_timestamp_and_compression_do_not_change_fingerprint(tmp_path):
    a = write_zip(tmp_path / "a.sl1", sl1_entries(b"-a"), year=2020, compression=zipfile.ZIP_DEFLATED)
    b = write_zip(tmp_path / "b.sl1", sl1_entries(b"-b"), year=2026, compression=zipfile.ZIP_STORED)
    assert a.read_bytes() != b.read_bytes()

    assert fp.fingerprint_archive(a, "layers").lines() == fp.fingerprint_archive(b, "layers").lines()


def test_png_layers_are_included_for_non_rle_runs(tmp_path):
    archive = write_zip(tmp_path / "a.sl1", {"model00000.png": b"png0", "config.ini": b"x"})

    assert [name for name, _ in fp.fingerprint_archive(archive, "layers").entries] == ["model00000.png"]


def test_preview_kind_takes_numbered_pngs_only(tmp_path):
    archive = write_zip(tmp_path / "p.zip", {
        "model_preview00001.png": b"1", "model_preview00000.png": b"0", "notes.txt": b"n", "model_preview.png": b"x",
    })
    result = fp.fingerprint_archive(archive, "preview")

    assert [name for name, _ in result.entries] == ["model_preview00000.png", "model_preview00001.png"]
    assert result.excluded == ["model_preview.png", "notes.txt"]


def test_lines_are_sorted_two_space_separated(tmp_path):
    lines = fp.fingerprint_archive(write_zip(tmp_path / "a.sl1", sl1_entries()), "layers").lines()

    assert lines.splitlines() == [f"{n}  {hashlib.sha256(LAYERS[n]).hexdigest()}" for n in sorted(LAYERS)]
    assert lines.endswith("\n")


def test_write_then_read_round_trips(tmp_path):
    result = fp.fingerprint_archive(write_zip(tmp_path / "a.sl1", sl1_entries()), "layers")
    fp.write_fingerprint(tmp_path / "layers.sha256", result)

    assert fp.read_fingerprint(tmp_path / "layers.sha256") == result.entries


@pytest.mark.parametrize("content", [
    "model00001.rle  " + "a" * 64 + "\nmodel00000.rle  " + "b" * 64 + "\n",   # unsorted
    "model00000.rle  " + "a" * 64 + "\nmodel00000.rle  " + "a" * 64 + "\n",   # duplicate
    "model00000.rle " + "a" * 64 + "\n",                                      # one space
    "model00000.rle  " + "A" * 64 + "\n",                                     # uppercase hex
    "model00000.rle  " + "a" * 63 + "\n",                                     # short digest
])
def test_read_rejects_malformed_files(tmp_path, content):
    path = tmp_path / "bad.sha256"
    path.write_bytes(content.encode("utf-8"))

    with pytest.raises(fp.FingerprintError):
        fp.read_fingerprint(path)


def test_corrupted_entry_fails_crc_check(tmp_path):
    archive = write_zip(tmp_path / "a.sl1", {"model00000.rle": b"\x01" * 64}, compression=zipfile.ZIP_STORED)
    data = bytearray(archive.read_bytes())
    data[data.index(b"\x01" * 64)] = 0x02
    archive.write_bytes(bytes(data))

    with pytest.raises(zipfile.BadZipFile):
        fp.fingerprint_archive(archive, "layers")


def test_cli_prints_lines_and_rejects_bad_usage(tmp_path, capsys):
    archive = write_zip(tmp_path / "a.sl1", sl1_entries())

    assert fp.main(["layers", str(archive)]) == 0
    assert capsys.readouterr().out.count("\n") == 2
    assert fp.main(["bogus", str(archive)]) == 2
    assert fp.main(["layers", str(tmp_path / "missing.sl1")]) == 1
