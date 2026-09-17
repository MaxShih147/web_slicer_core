"""compare_fingerprints.py: exit codes and report for the spec's comparison rules."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import compare_fingerprints as cf


def layer_lines(count: int, changed: dict[int, str] | None = None) -> list[tuple[str, str]]:
    changed = changed or {}
    return [(f"model{i:05d}.rle", changed.get(i, f"{i:064x}")) for i in range(count)]


def make_run(root: Path, name: str, layers, preview=None, platform="windows",
             case="primary", params="p" * 64) -> Path:
    run = root / name
    run.mkdir()
    preview = preview if preview is not None else [(f"model_preview{i:05d}.png", f"{i + 1:064x}")
                                                   for i in range(len(layers))]
    for filename, entries in (("layers.sha256", layers), ("preview.sha256", preview)):
        (run / filename).write_bytes("".join(f"{n}  {h}\n" for n, h in entries).encode("utf-8"))
    (run / "meta.json").write_text(json.dumps(
        {"run_id": name, "platform": platform, "case": case, "params_sha256": params}), encoding="utf-8")
    return run


def test_identical_runs_match(tmp_path, capsys):
    base = make_run(tmp_path, "base", layer_lines(590))
    test = make_run(tmp_path, "test", layer_lines(590))

    assert cf.main([str(base), str(test)]) == 0
    assert "result: MATCH" in capsys.readouterr().out


def test_single_layer_mismatch_reports_first_and_total(tmp_path, capsys):
    base = make_run(tmp_path, "base", layer_lines(590))
    test = make_run(tmp_path, "test", layer_lines(590, {316: "f" * 64}))

    assert cf.main([str(base), str(test)]) == 1
    out = capsys.readouterr().out
    assert "layers.sha256: MISMATCH" in out
    assert "first difference: model00316.rle" in out
    assert "differing entries: 1" in out
    assert "preview.sha256: match" in out


def test_first_difference_is_lowest_layer_among_many(tmp_path, capsys):
    base = make_run(tmp_path, "base", layer_lines(20))
    test = make_run(tmp_path, "test", layer_lines(20, {15: "f" * 64, 4: "e" * 64, 9: "d" * 64}))

    assert cf.main([str(base), str(test)]) == 1
    out = capsys.readouterr().out
    assert "first difference: model00004.rle" in out
    assert "differing entries: 3" in out


def test_different_layer_count_is_a_mismatch(tmp_path, capsys):
    base = make_run(tmp_path, "base", layer_lines(590))
    test = make_run(tmp_path, "test", layer_lines(589), preview=make_preview(590))

    assert cf.main([str(base), str(test)]) == 1
    out = capsys.readouterr().out
    assert "entries: base 590, test 589" in out
    assert "first difference: model00589.rle (base" in out and "test (absent))" in out


def make_preview(count):
    return [(f"model_preview{i:05d}.png", f"{i + 1:064x}") for i in range(count)]


def test_preview_mismatch_alone_fails(tmp_path, capsys):
    base = make_run(tmp_path, "base", layer_lines(10))
    test = make_run(tmp_path, "test", layer_lines(10), preview=make_preview(9))

    assert cf.main([str(base), str(test)]) == 1
    assert "preview.sha256: MISMATCH" in capsys.readouterr().out


def test_cross_platform_is_refused_by_default(tmp_path, capsys):
    base = make_run(tmp_path, "base", layer_lines(5), platform="windows")
    test = make_run(tmp_path, "test", layer_lines(5), platform="macos")

    code = cf.main([str(base), str(test)])
    captured = capsys.readouterr()
    assert code != 0 and code == cf.EXIT_CROSS_PLATFORM
    assert "platform labels differ" in captured.err
    assert "layers.sha256" not in captured.out


def test_cross_platform_report_never_passes(tmp_path, capsys):
    base = make_run(tmp_path, "base", layer_lines(5), platform="windows")
    test = make_run(tmp_path, "test", layer_lines(5), platform="macos")

    assert cf.main([str(base), str(test), "--allow-cross-platform"]) == cf.EXIT_CROSS_PLATFORM
    out = capsys.readouterr().out
    assert "NOT valid for acceptance" in out
    assert "layers.sha256: match" in out
    assert "result: MATCH" not in out


def test_parameter_and_case_differences_are_warned(tmp_path, capsys):
    base = make_run(tmp_path, "base", layer_lines(5), case="a", params="1" * 64)
    test = make_run(tmp_path, "test", layer_lines(5), case="b", params="2" * 64)

    assert cf.main([str(base), str(test)]) == 0
    out = capsys.readouterr().out
    assert "warning: case differs" in out
    assert "warning: params_sha256 differs" in out


@pytest.mark.parametrize("missing", ["meta.json", "layers.sha256", "preview.sha256"])
def test_incomplete_run_directory_is_a_usage_error(tmp_path, missing, capsys):
    base = make_run(tmp_path, "base", layer_lines(5))
    test = make_run(tmp_path, "test", layer_lines(5))
    (test / missing).unlink()

    assert cf.main([str(base), str(test)]) == cf.EXIT_USAGE
    assert missing in capsys.readouterr().err
