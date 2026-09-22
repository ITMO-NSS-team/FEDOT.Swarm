"""marker is a subprocess and pymupdf the fallback: what happens when the binary is missing,
fails, or runs out of time, and what the report says about it."""

import os
import stat
from pathlib import Path

import pytest
from parse_pdf import _strip_running_headers, convert

PDF = Path(__file__).parents[1] / "data" / "classifier-free-guidance" / "paper.pdf"


def test_running_headers_are_stripped_but_short_lines_kept():
    pages = [f"Stay on topic with CFG, page {i}\nt\nbody {i}" for i in range(5)]
    pages = [p.replace(f"page {i}", "page") for i, p in enumerate(pages)]
    out = _strip_running_headers(pages)
    assert all("Stay on topic" not in p for p in out)
    assert all("\nt\n" in p or p.startswith("t\n") for p in out)


def test_unknown_engine_is_refused(tmp_path: Path):
    with pytest.raises(ValueError, match="unknown pdf engine"):
        convert(PDF, tmp_path / "paper.md", engine="tesseract")


def test_missing_marker_falls_back_to_pymupdf(tmp_path: Path, monkeypatch):
    pytest.importorskip("pymupdf")
    monkeypatch.setenv("MARKER_BIN", str(tmp_path / "nope"))
    meta = convert(PDF, tmp_path / "paper.md", engine="marker")
    assert meta["engine"] == "pymupdf"
    assert meta["fallbackFrom"] == "marker"
    assert (tmp_path / "paper.md").stat().st_size > 10_000


def _fake_marker(tmp_path: Path, body: str) -> Path:
    script = tmp_path / "marker_single"
    script.write_text("#!/bin/sh\n" + body)
    script.chmod(script.stat().st_mode | stat.S_IEXEC)
    return script


def test_a_failing_marker_falls_back_with_its_stderr(tmp_path: Path, monkeypatch):
    pytest.importorskip("pymupdf")
    monkeypatch.setenv(
        "MARKER_BIN", str(_fake_marker(tmp_path, "echo 'no weights' >&2\nexit 3\n"))
    )
    meta = convert(PDF, tmp_path / "paper.md", engine="marker")
    assert meta["engine"] == "pymupdf"
    assert "no weights" in meta["reason"]


def test_a_slow_marker_is_killed_and_falls_back(tmp_path: Path, monkeypatch):
    pytest.importorskip("pymupdf")
    monkeypatch.setenv("MARKER_BIN", str(_fake_marker(tmp_path, "sleep 5\n")))
    meta = convert(PDF, tmp_path / "paper.md", engine="marker", timeout=0.2)
    assert meta["engine"] == "pymupdf"
    assert "timed out" in meta["reason"]


def test_a_working_marker_output_is_moved_into_place(tmp_path: Path, monkeypatch):
    body = (
        'out="$(echo "$@" | sed -n "s/.*--output_dir \\([^ ]*\\).*/\\1/p")"\n'
        'mkdir -p "$out/paper" && printf "# Title\\n\\nbody" > "$out/paper/paper.md"\n'
    )
    monkeypatch.setenv("MARKER_BIN", str(_fake_marker(tmp_path, body)))
    meta = convert(PDF, tmp_path / "paper.md", engine="marker")
    assert meta == {
        "source": str(PDF),
        "engine": "marker",
        "ocr": meta["ocr"],
        "chars": 13,
    }
    assert (tmp_path / "paper.md").read_text() == "# Title\n\nbody"
    assert os.environ.get("MARKER_BIN") is not None


def test_marker_children_do_not_outlive_it(tmp_path: Path, monkeypatch):
    """marker 2 leaves its model servers running; the whole group has to end with it."""
    import os
    import time

    pytest.importorskip("pymupdf")
    pidfile = tmp_path / "child.pid"
    body = (
        f"sleep 30 &\necho $! > {pidfile}\n"
        'out="$(echo "$@" | sed -n "s/.*--output_dir \\([^ ]*\\).*/\\1/p")"\n'
        'mkdir -p "$out/x" && printf "# ok" > "$out/x/x.md"\n'
    )
    monkeypatch.setenv("MARKER_BIN", str(_fake_marker(tmp_path, body)))
    meta = convert(PDF, tmp_path / "paper.md", engine="marker")
    assert meta["engine"] == "marker"
    child = int(pidfile.read_text())
    for _ in range(30):
        try:
            os.kill(child, 0)
        except ProcessLookupError:
            break
        time.sleep(0.1)
    else:
        os.kill(child, 9)
        raise AssertionError("the background child of marker survived")


def test_surya_servers_named_by_sentinels_are_stopped(tmp_path: Path, monkeypatch):
    """surya keeps its model servers alive between conversions; we end them by sentinel."""
    import json
    import os
    import subprocess
    import time

    pytest.importorskip("pymupdf")
    server = subprocess.Popen(["sleep", "30"], start_new_session=True)
    cache = tmp_path / "surya"
    cache.mkdir()
    (cache / "fast_layout_server.json").write_text(
        json.dumps({"pid": server.pid, "cleanup_kind": "process", "port": 1})
    )
    (cache / "broken_server.json").write_text("{not json")
    monkeypatch.setenv("SURYA_CACHE_DIR", str(cache))
    body = (
        'out="$(echo "$@" | sed -n "s/.*--output_dir \\([^ ]*\\).*/\\1/p")"\n'
        'mkdir -p "$out/x" && printf "# ok" > "$out/x/x.md"\n'
    )
    monkeypatch.setenv("MARKER_BIN", str(_fake_marker(tmp_path, body)))
    meta = convert(PDF, tmp_path / "paper.md", engine="marker")
    assert meta["engine"] == "marker"
    for _ in range(30):
        if server.poll() is not None:
            break
        time.sleep(0.1)
    else:
        os.kill(server.pid, 9)
        raise AssertionError("the model server named by the sentinel survived")
    assert not list(cache.glob("*_server.json"))
