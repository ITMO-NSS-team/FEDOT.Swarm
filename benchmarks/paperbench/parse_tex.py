"""Cleans a paper's LaTeX source into plain text for PaperBench runs.

Reads `data/<paper>/paper_tex/` (an arXiv-style source folder: `main.tex` plus whatever
`\\input`/`\\include` files it pulls in) or a single `.tex` file, and writes
`data/<paper>/paper.md`, so `run.py` feeds the swarm the full paper text instead of the
hand-written `paper_summary.md`. Needs nothing beyond the standard library: LaTeX source
is already plain text, there is no OCR step the way there was for a PDF.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

DATA = Path(__file__).parent / "data"

_COMMENT = re.compile(r"(?<!\\)%.*")
_DOCUMENT_START = re.compile(r"\\begin\{document\}")
_DOCUMENT_END = re.compile(r"\\end\{document\}")
_BIBLIOGRAPHY = re.compile(r"\\begin\{thebibliography\}")
_BIBLIOGRAPHY_CMD = re.compile(r"\\bibliography\{[^}]*\}")


def clean_tex(text: str) -> str:
    """Strips line comments and, when present, the preamble before `\\begin{document}`
    and the bibliography: boilerplate a coding agent gets nothing from. A no-op on a file
    that has none of these, which most files `\\input` by a main one do not."""
    text = _COMMENT.sub("", text)
    if start := _DOCUMENT_START.search(text):
        text = text[start.end() :]
    text = _DOCUMENT_END.split(text)[0]
    text = _BIBLIOGRAPHY.split(text)[0]
    text = _BIBLIOGRAPHY_CMD.sub("", text)
    return text.strip()


def find_tex_files(root: Path) -> list[Path]:
    return sorted(root.rglob("*.tex"))


def convert(source: Path, out_md: Path) -> dict:
    """`source` is a single `.tex` file or a directory of them. Every file is cleaned and
    concatenated, the file that declares `\\documentclass` (the entry point) first so the
    paper's own structure leads, the rest in path order — an approximation of resolving
    `\\input`/`\\include` that is far simpler and good enough for a reader, not a compiler."""
    if source.is_dir():
        files = find_tex_files(source)
        if not files:
            raise SystemExit(f"No .tex files found under {source}")
    else:
        files = [source]

    def label(f: Path) -> str:
        return str(f.relative_to(source)) if source.is_dir() else f.name

    raw = {f: f.read_text(errors="replace") for f in files}
    mains = [f for f in files if "\\documentclass" in raw[f]]
    ordered = mains + [f for f in files if f not in mains]

    parts = []
    for f in ordered:
        cleaned = clean_tex(raw[f])
        if cleaned:
            parts.append(f"# {label(f)}\n{cleaned}")
    text = "\n\n".join(parts)
    out_md.parent.mkdir(parents=True, exist_ok=True)
    out_md.write_text(text)
    return {"source": str(source), "files": len(ordered), "chars": len(text)}


def cli() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--paper", default="stochastic-interpolants")
    p.add_argument(
        "--source",
        default=None,
        help="a .tex file or a directory of them; defaults to data/<paper>/paper_tex "
        "if it exists, else data/<paper>/paper.tex",
    )
    p.add_argument("--out", default=None, help="defaults to data/<paper>/paper.md")
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
    if source:
        return Path(source)
    as_dir = paper_dir / "paper_tex"
    return as_dir if as_dir.is_dir() else paper_dir / "paper.tex"


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
                }
            )
        )
        return
    if out_md.exists() and not args.force:
        print(f"{out_md} already exists, pass --force to reconvert.")
        return
    source = resolve_source(paper_dir, args.source)
    if not source.exists():
        raise SystemExit(f"No .tex source at {source}: pass --source <file-or-dir>.")
    meta = convert(source, out_md)
    print(json.dumps({"paper_md": str(out_md), **meta}, ensure_ascii=False))


if __name__ == "__main__":
    main(cli())
