"""Turns a paper's PDF into markdown for PaperBench runs, for a paper whose LaTeX source is
not at hand.

Two engines. `marker` (default) runs `marker_single` from its own tool environment: layout
detection, tables, equations back to LaTeX, and OCR of blocks whose text layer is garbled,
so a scanned or badly typeset page still comes through. It needs the marker weights and a
few minutes of CPU per paper. `pymupdf` is the plain text layer, seconds per paper, no OCR,
math as unicode glyphs; it is the fallback when marker is missing, fails, or runs out of
time. Prefer `parse_tex.py` when the LaTeX source is available.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path
from typing import Any

DATA = Path(__file__).parent / "data"
ENGINES = ("marker", "pymupdf")
MARKER_TIMEOUT = 900.0

# A line the renderer repeats near-verbatim on most pages is a running header or footer.
# Short lines are left alone even if they recur: a one-character fragment from a formula
# recurs by coincidence far more often than a real header does.
_HEADER_MIN_CHARS = 15
_HEADER_MIN_SHARE = 0.6


def _strip_running_headers(pages: list[str]) -> list[str]:
    counts: Counter[str] = Counter()
    for page in pages:
        for line in {line.strip() for line in page.split("\n") if line.strip()}:
            counts[line] += 1
    threshold = max(2, int(len(pages) * _HEADER_MIN_SHARE))
    noise = {
        line
        for line, n in counts.items()
        if n >= threshold and len(line) >= _HEADER_MIN_CHARS
    }
    if not noise:
        return pages
    return [
        "\n".join(line for line in page.split("\n") if line.strip() not in noise)
        for page in pages
    ]


def _pymupdf(source: Path, out_md: Path) -> dict[str, Any]:
    import pymupdf

    doc = pymupdf.open(source)
    pages = [page.get_text() for page in doc]
    doc.close()
    pages = _strip_running_headers(pages)
    text = "\n\n".join(page.strip() for page in pages if page.strip())
    out_md.write_text(text)
    return {"engine": "pymupdf", "pages": len(pages), "chars": len(text)}


def marker_binary() -> str | None:
    """`MARKER_BIN` when set, else `marker_single` on the PATH."""
    return os.environ.get("MARKER_BIN") or shutil.which("marker_single")


def ocr_available() -> bool:
    """marker's OCR runs a llama.cpp server; without the binary it is switched off and a
    born-digital PDF still converts from its text layer with layout intact."""
    return shutil.which(os.environ.get("LLAMA_CPP_BINARY", "llama-server")) is not None


def _run_in_own_group(argv: list[str], timeout: float) -> None:
    """Runs marker in its own process group and ends the whole group afterwards, then the
    model servers it left behind. marker 2 starts surya's layout and OCR-error servers in
    their own sessions and keeps them alive on purpose (later conversions re-attach through
    sentinel files under ~/.cache/datalab/surya); a demo box gets that gigabyte back."""
    # stderr goes to a file, not a pipe: a child that inherits the pipe would keep it open
    # after marker itself has exited, and a pipe read would then wait on the child
    with tempfile.TemporaryFile(mode="w+") as stderr:
        proc = subprocess.Popen(
            argv,
            stdout=subprocess.DEVNULL,
            stderr=stderr,
            start_new_session=True,
            env={**os.environ, "HF_HUB_DISABLE_PROGRESS_BARS": "1"},
        )
        try:
            proc.wait(timeout=timeout)
        finally:
            _end_group(proc)
            _stop_model_servers()
        stderr.seek(0)
        tail = stderr.read()
    if proc.returncode != 0:
        raise subprocess.CalledProcessError(proc.returncode, argv, stderr=tail)


def surya_cache() -> Path:
    return Path(
        os.environ.get("SURYA_CACHE_DIR") or Path.home() / ".cache/datalab/surya"
    )


def _stop_model_servers() -> None:
    """Ends the servers surya's sentinels point at and removes the sentinels, so the next
    conversion spawns fresh ones instead of attaching to a dead port. A second conversion
    running at the same moment re-spawns its server and retries once, which surya does on
    its own."""
    for sentinel in sorted(surya_cache().glob("*_server.json")):
        try:
            info = json.loads(sentinel.read_text())
            pid = int(info.get("pid") or 0)
        except (OSError, ValueError):
            pid = 0
        if pid > 0 and info.get("cleanup_kind", "process") == "process":
            _end_process(pid)
        sentinel.unlink(missing_ok=True)


def _end_process(pid: int) -> None:
    for sig in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.kill(pid, sig)
        except (ProcessLookupError, PermissionError):
            return
        for _ in range(30):
            time.sleep(0.1)
            try:
                os.kill(pid, 0)
            except (ProcessLookupError, PermissionError):
                return


def _group_alive(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # macOS answers EPERM once only zombies are left in the group
        return False
    return True


def _end_group(proc: subprocess.Popen[bytes]) -> None:
    """SIGTERM to the group, a short grace, then SIGKILL; the leader is reaped either way."""
    for sig in (signal.SIGTERM, signal.SIGKILL):
        if not _group_alive(proc.pid):
            break
        try:
            os.killpg(proc.pid, sig)
        except (ProcessLookupError, PermissionError):
            break
        for _ in range(20):
            if not _group_alive(proc.pid):
                break
            time.sleep(0.1)
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass


def _marker(source: Path, out_md: Path, timeout: float) -> dict[str, Any]:
    binary = marker_binary()
    if binary is None:
        raise FileNotFoundError("marker_single is not installed")
    with tempfile.TemporaryDirectory(prefix="marker-") as tmp:
        _run_in_own_group(
            [
                binary,
                str(source),
                "--mode",
                "fast",
                "--output_format",
                "markdown",
                "--output_dir",
                tmp,
                "--disable_image_extraction",
                "--disable_multiprocessing",
                *([] if ocr_available() else ["--disable_ocr"]),
            ],
            timeout,
        )
        found = sorted(Path(tmp).rglob("*.md"))
        if not found:
            raise FileNotFoundError("marker produced no markdown")
        text = found[0].read_text()
    out_md.write_text(text)
    return {"engine": "marker", "ocr": ocr_available(), "chars": len(text)}


def convert(
    source: Path,
    out_md: Path,
    engine: str = "marker",
    timeout: float = MARKER_TIMEOUT,
) -> dict[str, Any]:
    """Writes `out_md` and reports which engine actually did it."""
    if engine not in ENGINES:
        raise ValueError(f"unknown pdf engine {engine!r}, expected one of {ENGINES}")
    out_md.parent.mkdir(parents=True, exist_ok=True)
    meta: dict[str, Any] = {"source": str(source)}
    if engine == "marker":
        try:
            return {**meta, **_marker(source, out_md, timeout)}
        except (
            FileNotFoundError,
            subprocess.CalledProcessError,
            subprocess.TimeoutExpired,
        ) as e:
            stderr = getattr(e, "stderr", None)
            reason = str(stderr).strip()[-500:] if stderr else str(e)
            print(f"marker failed, falling back to pymupdf: {reason}", file=sys.stderr)
            meta |= {"fallbackFrom": "marker", "reason": reason}
    return {**meta, **_pymupdf(source, out_md)}


def cli() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--paper", default="stochastic-interpolants")
    p.add_argument(
        "--source",
        default=None,
        help="a .pdf file; defaults to data/<paper>/paper.pdf",
    )
    p.add_argument("--out", default=None, help="defaults to data/<paper>/paper.md")
    p.add_argument("--engine", choices=ENGINES, default="marker")
    p.add_argument("--timeout", type=float, default=MARKER_TIMEOUT)
    p.add_argument(
        "--force", action="store_true", help="overwrite an existing paper.md"
    )
    p.add_argument(
        "--check",
        action="store_true",
        help="report whether paper.md exists without converting",
    )
    return p.parse_args()


def resolve_source(paper_dir: Path, source: str | None) -> Path:
    return Path(source) if source else paper_dir / "paper.pdf"


def main(args: argparse.Namespace) -> None:
    paper_dir = DATA / args.paper
    out_md = Path(args.out) if args.out else paper_dir / "paper.md"
    if args.check:
        print(
            json.dumps(
                {
                    "paper": args.paper,
                    "paper_md": str(out_md),
                    "exists": out_md.exists(),
                    "marker": marker_binary(),
                }
            )
        )
        return
    if out_md.exists() and not args.force:
        print(f"{out_md} already exists, pass --force to reconvert.")
        return
    source = resolve_source(paper_dir, args.source)
    if not source.exists():
        raise SystemExit(f"No PDF at {source}: pass --source <file>.")
    meta = convert(source, out_md, args.engine, args.timeout)
    print(json.dumps({"paper_md": str(out_md), **meta}, ensure_ascii=False))


if __name__ == "__main__":
    main(cli())
