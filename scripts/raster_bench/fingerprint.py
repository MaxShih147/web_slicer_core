#!/usr/bin/env python
"""Per-entry SHA-256 fingerprints of the engine's layer and preview archives.

Spec: ``raster-performance-baseline``, "指紋須以解壓後的項目計算".

A fingerprint is computed over the *decompressed* bytes of every image entry in
an archive, never over the zip file itself: zip headers carry timestamps and the
compressed stream depends on build settings, so two archives with identical
pixels can still differ byte for byte.

Only image entries are included. In the ``.sl1`` those are the root-level layer
files ``<project>#####.rle`` / ``<project>#####.png``; ``config.ini``,
``prusaslicer.ini`` and ``thumbnail/*.png`` are metadata and excluded. In the
preview zip they are the root-level ``<project>#####.png`` images.

Fingerprint file format: one ``<entry name>  <sha256 lowercase hex>`` line per
entry, sorted by entry name, each line ending in ``\\n``.

  python scripts/raster_bench/fingerprint.py layers  model.sl1
  python scripts/raster_bench/fingerprint.py preview model_preview.zip
"""
from __future__ import annotations

import hashlib
import re
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path

# Root-level (no "/") numbered images, matching the fork's entry names:
# SL1Archive layers "<project>%.5d.<ext>" and export_preview_zip "<project>%.5d.<ext>".
LAYER_ENTRY_RE = re.compile(r"^[^/\\]+\d{5}\.(rle|png)$")
PREVIEW_ENTRY_RE = re.compile(r"^[^/\\]+\d{5}\.png$")
KIND_PATTERNS = {"layers": LAYER_ENTRY_RE, "preview": PREVIEW_ENTRY_RE}

_LINE_RE = re.compile(r"^(\S(?:.*\S)?)  ([0-9a-f]{64})$")
_CHUNK = 1 << 20


class FingerprintError(Exception):
    """A malformed archive or fingerprint file."""


@dataclass(frozen=True)
class Fingerprint:
    entries: list[tuple[str, str]]  # (name, sha256), sorted by name
    excluded: list[str]             # entry names left out, sorted

    def lines(self) -> str:
        return "".join(f"{name}  {digest}\n" for name, digest in self.entries)


def fingerprint_archive(path: Path, kind: str) -> Fingerprint:
    """Hash every included entry's decompressed bytes. ``kind`` is "layers" or "preview"."""
    pattern = KIND_PATTERNS[kind]
    with zipfile.ZipFile(path) as zf:
        infos = [info for info in zf.infolist() if not info.is_dir()]
        names = [info.filename for info in infos]
        if len(names) != len(set(names)):
            raise FingerprintError(f"{path.name}: duplicate entry names")
        entries, excluded = [], []
        for info in infos:
            if not pattern.match(info.filename):
                excluded.append(info.filename)
                continue
            digest = hashlib.sha256()
            # ZipFile.open verifies the stored CRC-32 once the entry is fully read.
            with zf.open(info) as f:
                for chunk in iter(lambda: f.read(_CHUNK), b""):
                    digest.update(chunk)
            entries.append((info.filename, digest.hexdigest()))
    return Fingerprint(entries=sorted(entries), excluded=sorted(excluded))


def write_fingerprint(path: Path, fingerprint: Fingerprint) -> None:
    path.write_bytes(fingerprint.lines().encode("utf-8"))


def read_fingerprint(path: Path) -> list[tuple[str, str]]:
    """Parse a fingerprint file, rejecting anything the writer would not produce."""
    entries = []
    for number, line in enumerate(path.read_bytes().decode("utf-8").split("\n"), start=1):
        if line == "":
            continue
        match = _LINE_RE.match(line)
        if match is None:
            raise FingerprintError(f"{path}:{number}: malformed line {line!r}")
        entries.append((match.group(1), match.group(2)))
    names = [name for name, _ in entries]
    if names != sorted(names):
        raise FingerprintError(f"{path}: entries are not sorted by name")
    if len(names) != len(set(names)):
        raise FingerprintError(f"{path}: duplicate entry names")
    return entries


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 2 or args[0] not in KIND_PATTERNS:
        print(f"usage: fingerprint.py {{{'|'.join(KIND_PATTERNS)}}} ARCHIVE", file=sys.stderr)
        return 2
    try:
        fingerprint = fingerprint_archive(Path(args[1]), args[0])
    except (OSError, zipfile.BadZipFile, FingerprintError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    sys.stdout.write(fingerprint.lines())
    return 0


if __name__ == "__main__":
    sys.exit(main())
